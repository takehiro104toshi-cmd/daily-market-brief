"""Local inbox contract（Phase 3.7 §28）。Phase 3.75 が使う。

    incoming path → stable-file detection → processing lock → intake → outcome ledger

- **copy 途中のファイルは処理しない**（size が 2 回の sample で不変、かつ mtime が stable_seconds 以上前）。
- lock は `<lock_dir>/<name>.lock` の排他作成。取れなければ SKIPPED_LOCKED。
- 原本は移動・削除しない（default）。処理結果は append-only ledger に残し、同一 hash は再処理しない。
- folder watcher daemon は実装しない（scan は呼び出し側が起動する）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .config import CorpusConfig
from .identity import sha256_file
from .intake import ACCEPTED, CompassIntakeService, IntakeRequest, SOURCE_INBOX

STATE_STABLE = "STABLE"
STATE_UNSTABLE = "UNSTABLE"            # copy 途中（size 変化 or mtime が新しすぎる）
STATE_LOCKED = "LOCKED"
STATE_ALREADY_PROCESSED = "ALREADY_PROCESSED"
STATE_NOT_PDF = "NOT_PDF"

OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_DUPLICATE = "DUPLICATE"
OUTCOME_QUARANTINE = "QUARANTINE"
OUTCOME_FAILURE = "FAILURE"
OUTCOME_SKIPPED_UNSTABLE = "SKIPPED_UNSTABLE"
OUTCOME_SKIPPED_LOCKED = "SKIPPED_LOCKED"
OUTCOME_SKIPPED_PROCESSED = "SKIPPED_PROCESSED"
OUTCOME_SKIPPED_NOT_PDF = "SKIPPED_NOT_PDF"

Sampler = Callable[[Path], Tuple[int, float]]      # → (size, mtime)
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class InboxContract:
    incoming_dir: Path
    lock_dir: Path
    ledger_path: Path
    stable_seconds: int
    stable_samples: int
    allowed_suffixes: Tuple[str, ...] = (".pdf",)

    def as_dict(self) -> Dict[str, object]:
        return {"incoming_dir": str(self.incoming_dir), "lock_dir": str(self.lock_dir),
                "ledger_path": str(self.ledger_path), "stable_seconds": self.stable_seconds,
                "stable_samples": self.stable_samples,
                "allowed_suffixes": list(self.allowed_suffixes),
                "states": [STATE_STABLE, STATE_UNSTABLE, STATE_LOCKED, STATE_ALREADY_PROCESSED,
                           STATE_NOT_PDF],
                "outcomes": [OUTCOME_SUCCESS, OUTCOME_DUPLICATE, OUTCOME_QUARANTINE,
                             OUTCOME_FAILURE, OUTCOME_SKIPPED_UNSTABLE, OUTCOME_SKIPPED_LOCKED,
                             OUTCOME_SKIPPED_PROCESSED, OUTCOME_SKIPPED_NOT_PDF],
                "moves_or_deletes_originals": False}


@dataclass(frozen=True)
class InboxCandidate:
    path: Path
    state: str
    size: int
    sha256: str = ""


def inbox_contract(base_dir: Path, config: CorpusConfig) -> InboxContract:
    base = Path(base_dir)
    contract = InboxContract(incoming_dir=base / "incoming", lock_dir=base / ".processing",
                             ledger_path=base / "inbox_ledger.jsonl",
                             stable_seconds=config.inbox_stable_seconds,
                             stable_samples=max(2, config.inbox_stable_samples))
    contract.incoming_dir.mkdir(parents=True, exist_ok=True)
    contract.lock_dir.mkdir(parents=True, exist_ok=True)
    return contract


def sample_file(path: Path) -> Tuple[int, float]:
    st = Path(path).stat()
    return st.st_size, st.st_mtime


def is_stable(samples: Sequence[Tuple[int, float]], now_ts: float, stable_seconds: int) -> bool:
    if len(samples) < 2:
        return False
    sizes = {s for s, _ in samples}
    if len(sizes) != 1 or 0 in sizes:
        return False
    return (now_ts - max(m for _, m in samples)) >= stable_seconds


def processed_hashes(contract: InboxContract) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    if not contract.ledger_path.exists():
        return out
    with contract.ledger_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("outcome") in (OUTCOME_SUCCESS, OUTCOME_DUPLICATE, OUTCOME_QUARANTINE):
                out[str(d.get("sha256", ""))] = d
    return out


def scan_inbox(contract: InboxContract, *, sampler: Sampler = sample_file,
               sleeper: Sleeper = time.sleep, now_ts: Optional[float] = None,
               sample_interval: float = 0.0) -> List[InboxCandidate]:
    now_ts = time.time() if now_ts is None else now_ts
    done = processed_hashes(contract)
    out: List[InboxCandidate] = []
    for path in sorted(p for p in contract.incoming_dir.iterdir() if p.is_file()):
        if path.suffix.lower() not in contract.allowed_suffixes:
            out.append(InboxCandidate(path, STATE_NOT_PDF, 0))
            continue
        samples = [sampler(path)]
        for _ in range(contract.stable_samples - 1):
            if sample_interval > 0:
                sleeper(sample_interval)
            samples.append(sampler(path))
        if not is_stable(samples, now_ts, contract.stable_seconds):
            out.append(InboxCandidate(path, STATE_UNSTABLE, samples[-1][0]))
            continue
        digest = sha256_file(path)
        if digest in done:
            out.append(InboxCandidate(path, STATE_ALREADY_PROCESSED, samples[-1][0], digest))
            continue
        if (contract.lock_dir / (path.name + ".lock")).exists():
            out.append(InboxCandidate(path, STATE_LOCKED, samples[-1][0], digest))
            continue
        out.append(InboxCandidate(path, STATE_STABLE, samples[-1][0], digest))
    return out


def acquire_lock(contract: InboxContract, path: Path) -> Optional[Path]:
    lock = contract.lock_dir / (Path(path).name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(datetime.now(timezone.utc).isoformat())
    return lock


def release_lock(lock: Optional[Path]) -> None:
    if lock is not None:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _ledger_write(contract: InboxContract, entry: Dict) -> None:
    with contract.ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def process_inbox(contract: InboxContract, service: CompassIntakeService, *, now: datetime,
                  sampler: Sampler = sample_file, sleeper: Sleeper = time.sleep,
                  sample_interval: float = 0.0) -> List[Dict]:
    """scan → lock → intake → ledger。原本は動かさない。"""
    results: List[Dict] = []
    now_ts = now.timestamp()
    for cand in scan_inbox(contract, sampler=sampler, sleeper=sleeper, now_ts=now_ts,
                           sample_interval=sample_interval):
        base = {"file": cand.path.name, "state": cand.state, "sha256": cand.sha256,
                "at": now.isoformat()}
        if cand.state == STATE_NOT_PDF:
            results.append({**base, "outcome": OUTCOME_SKIPPED_NOT_PDF})
            continue
        if cand.state == STATE_UNSTABLE:
            results.append({**base, "outcome": OUTCOME_SKIPPED_UNSTABLE})
            continue
        if cand.state == STATE_ALREADY_PROCESSED:
            results.append({**base, "outcome": OUTCOME_SKIPPED_PROCESSED})
            continue
        if cand.state == STATE_LOCKED:
            results.append({**base, "outcome": OUTCOME_SKIPPED_LOCKED})
            continue
        lock = acquire_lock(contract, cand.path)
        if lock is None:
            results.append({**base, "outcome": OUTCOME_SKIPPED_LOCKED})
            continue
        try:
            outcome = service.submit(IntakeRequest(path=cand.path, original_filename=cand.path.name,
                                                   source_type=SOURCE_INBOX, received_at=now,
                                                   channel="inbox"))
            mapped = {ACCEPTED: OUTCOME_SUCCESS, "DUPLICATE": OUTCOME_DUPLICATE,
                      "QUARANTINED": OUTCOME_QUARANTINE}.get(outcome.status, OUTCOME_FAILURE)
            entry = {**base, "outcome": mapped, "document_id": outcome.document_id,
                     "reasons": list(outcome.reasons),
                     "ledger_id": "cil_" + hashlib.sha1(
                         f"{cand.sha256}|{cand.path.name}|{now.isoformat()}".encode("utf-8")).hexdigest()[:16]}
            _ledger_write(contract, entry)
            results.append(entry)
        finally:
            release_lock(lock)
    return results
