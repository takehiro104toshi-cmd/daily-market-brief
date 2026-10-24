"""P12-A4 — P12 の運用の排他 lock（`<p12_root>/locks/`。run ごとの lock と短い ledger の commit lock）。

- 取得は `os.open(O_CREAT | O_EXCL)`（Windows ・POSIX で原子的。存在の検査 → 作成の race は無い。Windows では O_BINARY も付け、
  text mode の改行の変換で正準な byte が崩れないようにする）。内容は正準 JSON の安全な
  metadata だけ: lock_version ・kind（RUN ／ LEDGER）・run_id ・pid ・process_identity ・boot_marker ・acquired_at ・scheduled_for ・attempt。
  path ・payload ・資格情報 ・command line ・user 名は無い。
- 解放は所有者が fd を閉じてから unlink（Windows は開いたままの file を消せないので、他 process の生存の信号にもなる）。
- 既に在れば `LockHeld`（`DUPLICATE_INVOCATION:RUN_ACTIVE` ／ `:LEDGER_LOCKED`）。古いだけでは stale ではない。`classify_lock` が
  process の生存 ・identity ・起動の token ・ledger の状態から分類し、曖昧なら fail closed（削除しない）。stale と分かった lock は
  人の手の回復（`release_stale_lock`）が `locks/stale/` に rename して証拠を残す。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .atomic_files import ensure_root_subdirectory, fsync_directory, read_text_file, replace_atomically
from .canonical import canonical_json, is_digest, require_fields, utc_iso
from .failure_codes import AutomationError
from .ledger_store import LedgerState
from .process_probe import ProcessProbe, this_process
from .run_state import is_terminal

LOCKS_DIRECTORY = "locks"
STALE_DIRECTORY = "stale"
LOCK_VERSION = "p12_operational_lock:0.1.0"
LEDGER_LOCK_NAME = "ledger.lock"
LOCK_KINDS = ("RUN", "LEDGER")
LOCK_CLASSES = ("LOCK_ABSENT", "LOCK_LIVE", "LOCK_STALE_DEAD", "LOCK_STALE_PID_REUSED", "LOCK_STALE_REBOOT", "LOCK_STALE_TERMINAL",
                "LOCK_MALFORMED", "LOCK_UNKNOWN_PROVENANCE")
_LOCK_FIELDS = frozenset({"lock_version", "kind", "run_id", "pid", "process_identity", "boot_marker", "acquired_at", "scheduled_for",
                          "attempt"})


class LockHeld(AutomationError):
    def __init__(self, kind: str) -> None:
        super().__init__("DUPLICATE_INVOCATION", "RUN_ACTIVE" if kind == "RUN" else "LEDGER_LOCKED")
        self.kind = kind


@dataclass(frozen=True)
class LockRecord:
    kind: str
    run_id: str
    pid: int
    process_identity: Optional[str]
    boot_marker: Optional[str]
    acquired_at: str
    scheduled_for: Optional[str]
    attempt: Optional[int]
    lock_version: str = LOCK_VERSION

    def __post_init__(self) -> None:
        if self.lock_version != LOCK_VERSION or self.kind not in LOCK_KINDS or not is_digest(self.run_id):
            raise AutomationError("SCHEMA_INVALID", "LOCK_MALFORMED")
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0:
            raise AutomationError("SCHEMA_INVALID", "LOCK_MALFORMED")
        for marker in (self.process_identity, self.boot_marker):
            if marker is not None and not is_digest(marker):
                raise AutomationError("SCHEMA_INVALID", "LOCK_MALFORMED")
        if not isinstance(self.acquired_at, str) or not self.acquired_at.endswith("Z"):
            raise AutomationError("SCHEMA_INVALID", "LOCK_MALFORMED")

    def to_dict(self) -> Dict[str, Any]:
        return {"lock_version": self.lock_version, "kind": self.kind, "run_id": self.run_id, "pid": self.pid,
                "process_identity": self.process_identity, "boot_marker": self.boot_marker, "acquired_at": self.acquired_at,
                "scheduled_for": self.scheduled_for, "attempt": self.attempt}

    def to_bytes(self) -> bytes:
        return (canonical_json(self.to_dict()) + "\n").encode("utf-8")

    @classmethod
    def from_text(cls, text: str) -> "LockRecord":
        try:
            fields = require_fields(json.loads(text), _LOCK_FIELDS, "LOCK")
        except (ValueError, AutomationError):
            raise AutomationError("SCHEMA_INVALID", "LOCK_MALFORMED") from None
        record = cls(**fields)
        if record.to_bytes().decode("utf-8") != text:
            raise AutomationError("SCHEMA_INVALID", "LOCK_MALFORMED")
        return record


def run_lock_file(p12_root: Any, run_id: str) -> Path:
    if not is_digest(run_id):
        raise AutomationError("SCHEMA_INVALID", "RUN_ID")
    return Path(p12_root) / LOCKS_DIRECTORY / f"run.{run_id}.lock"


def ledger_lock_file(p12_root: Any) -> Path:
    return Path(p12_root) / LOCKS_DIRECTORY / LEDGER_LOCK_NAME


class HeldLock:
    """取得済みの lock。`release()` は所有者だけ（fd を閉じてから unlink）。context manager として使う。"""

    def __init__(self, target: Path, record: LockRecord) -> None:
        self.target, self.record, self._released = target, record, False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            os.unlink(self.target)
            fsync_directory(self.target.parent)
        except OSError:
            raise AutomationError("STEP_FAILED", "LOCK_RELEASE_IO") from None

    def __enter__(self) -> "HeldLock":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()


def acquire_lock(p12_root: Any, kind: str, run_id: str, *, probe: ProcessProbe, clock_instant: datetime,
                 scheduled_for: Optional[str] = None, attempt: Optional[int] = None) -> HeldLock:
    """O_CREAT | O_EXCL で原子的に取得。既に在れば `LockHeld`（分類はしない: 生きている lock と stale の区別は caller の回復）。"""
    if kind not in LOCK_KINDS:
        raise AutomationError("SCHEMA_INVALID", "LOCK_KIND")
    directory = ensure_root_subdirectory(p12_root, LOCKS_DIRECTORY)
    target = directory / LEDGER_LOCK_NAME if kind == "LEDGER" else run_lock_file(p12_root, run_id)
    me = this_process(probe)
    record = LockRecord(kind=kind, run_id=run_id, pid=me["pid"], process_identity=me["process_identity"], boot_marker=me["boot_marker"],
                        acquired_at=utc_iso(clock_instant), scheduled_for=scheduled_for, attempt=attempt)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY                                                           # Windows: text mode would turn the LF into CRLF
    try:
        fd = os.open(str(target), flags, 0o600)
    except FileExistsError:
        raise LockHeld(kind) from None
    except OSError:
        raise AutomationError("STEP_FAILED", "LOCK_IO") from None
    try:
        os.write(fd, record.to_bytes())
        os.fsync(fd)
    except OSError:
        os.close(fd)
        raise AutomationError("STEP_FAILED", "LOCK_IO") from None
    os.close(fd)                                                                       # Windows: 開いたままだと自分も消せない
    fsync_directory(directory)
    return HeldLock(target, record)


def read_lock(target: Path) -> Optional[LockRecord]:
    text = read_text_file(target)
    return None if text is None else LockRecord.from_text(text)


def classify_lock(target: Path, *, probe: ProcessProbe, ledger_state: Optional[LedgerState] = None) -> Dict[str, Any]:
    """lock の分類（削除しない）。provenance が証明できなければ `LOCK_UNKNOWN_PROVENANCE`（fail closed）。"""
    try:
        record = read_lock(target)
    except AutomationError:
        return {"lock_class": "LOCK_MALFORMED", "run_id": None, "pid": None}
    if record is None:
        return {"lock_class": "LOCK_ABSENT", "run_id": None, "pid": None}
    base = {"run_id": record.run_id, "pid": record.pid, "kind": record.kind, "acquired_at": record.acquired_at}
    boot = probe.boot_marker()
    if record.boot_marker is not None and boot is not None and record.boot_marker != boot:
        return {**base, "lock_class": "LOCK_STALE_REBOOT"}                              # 起動が変わった: process は確実に居ない
    alive = probe.is_alive(record.pid)
    if alive is None:
        return {**base, "lock_class": "LOCK_UNKNOWN_PROVENANCE"}
    if alive is False:
        state = ledger_state.run_states.get(record.run_id) if ledger_state is not None and record.kind == "RUN" else None
        if state is not None and is_terminal(state):
            return {**base, "lock_class": "LOCK_STALE_TERMINAL"}                        # commit 済みの終端の run の取り残し
        return {**base, "lock_class": "LOCK_STALE_DEAD"}
    identity = probe.identity(record.pid)
    if record.process_identity is not None and identity is not None and identity != record.process_identity:
        return {**base, "lock_class": "LOCK_STALE_PID_REUSED"}                          # 生きているが別の process（再利用の証明）
    if record.process_identity is None or identity is None:
        return {**base, "lock_class": "LOCK_UNKNOWN_PROVENANCE"}                        # 同じ pid だが identity を証明できない
    return {**base, "lock_class": "LOCK_LIVE"}                                          # 生きていれば終端でも LIVE（解放待ち）


def lock_is_stale(classification: Dict[str, Any]) -> bool:
    return classification["lock_class"] in ("LOCK_STALE_DEAD", "LOCK_STALE_PID_REUSED", "LOCK_STALE_REBOOT", "LOCK_STALE_TERMINAL")


def release_stale_lock(p12_root: Any, target: Path, classification: Dict[str, Any]) -> Dict[str, Any]:
    """stale と分類された lock だけを `locks/stale/` に rename して証拠を残す（LIVE ・MALFORMED ・UNKNOWN は拒む）。"""
    if not lock_is_stale(classification):
        raise AutomationError("DUPLICATE_INVOCATION", classification["lock_class"])
    stale_dir = ensure_root_subdirectory(p12_root, LOCKS_DIRECTORY) / STALE_DIRECTORY
    try:
        stale_dir.mkdir(parents=False, exist_ok=True)
        text = read_text_file(target)
        if text is None:
            return {**classification, "released": False}
        evidence = stale_dir / f"{target.name}.{classification['acquired_at'].replace(':', '')}.json"
        replace_atomically(evidence, text.encode("utf-8"))
        os.unlink(target)
        fsync_directory(target.parent)
    except OSError:
        raise AutomationError("STEP_FAILED", "LOCK_RELEASE_IO") from None
    return {**classification, "released": True}


__all__ = ["LEDGER_LOCK_NAME", "LOCKS_DIRECTORY", "LOCK_CLASSES", "LOCK_KINDS", "LOCK_VERSION", "STALE_DIRECTORY", "HeldLock",
           "LockHeld", "LockRecord", "acquire_lock", "classify_lock", "ledger_lock_file", "lock_is_stale", "read_lock",
           "release_stale_lock", "run_lock_file"]
