"""P12-A2 — 原子的な finalize の file system 側（`<p12_root>/runs/<run_id>.partial` → `<p12_root>/runs/<run_id>`）。

- 書くのは `.partial` の中だけ。各 artifact は `open("xb")` で作り、flush ・fsync し、読み戻して sha256 を照合する。最後に
  `digests.json`（名前 → sha256 の正準 JSON）を書き、directory を fsync し、`os.rename` で 1 回だけ final に替える（同じ file system）。
- final が既に在れば `DUPLICATE_INVOCATION:FINAL_EXISTS`、`.partial` が既に在れば `DUPLICATE_INVOCATION:PARTIAL_EXISTS`（黙って消さない ・
  上書きしない。回復は A4）。
- rename が済んでも **成功ではない**: 状態は `FINALIZED_PENDING_LEDGER`（ledger の record の commit は後の gate）。
- 安全な結果（`FinalizationOutcome`）は状態 ・artifact の数 ・digest だけ（path は無い）。
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from .canonical import canonical_json, is_digest
from .failure_codes import AutomationError

RUNS_DIRECTORY = "runs"
PARTIAL_SUFFIX = ".partial"
DIGESTS_ARTIFACT = "digests.json"
FINALIZED_PENDING_LEDGER = "FINALIZED_PENDING_LEDGER"
_ARTIFACT_NAME_RE = re.compile(r"\A[a-z][a-z0-9_]{0,40}\.json\Z")
MAX_ARTIFACTS = 32


@dataclass(frozen=True)
class FinalizationOutcome:
    status: str
    artifact_count: int
    artifact_digests: Tuple[str, ...]              # 全 artifact（digests.json を含む）の sha256 ・順

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "artifact_count": self.artifact_count, "artifact_digests": list(self.artifact_digests)}


def _fsync_directory(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return                                                                         # Windows: directory の fd は開けない
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_artifact(target: Path, data: bytes) -> str:
    with open(target, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if target.read_bytes() != data:
        raise AutomationError("STEP_FAILED", "ARTIFACT_READBACK")
    return hashlib.sha256(data).hexdigest()


def validate_artifacts(artifacts: Mapping[str, bytes]) -> Tuple[Tuple[str, bytes], ...]:
    if not isinstance(artifacts, Mapping) or not artifacts or len(artifacts) > MAX_ARTIFACTS:
        raise AutomationError("SCHEMA_INVALID", "ARTIFACTS")
    ordered = []
    for name in sorted(artifacts):
        data = artifacts[name]
        if not isinstance(name, str) or not _ARTIFACT_NAME_RE.match(name) or name == DIGESTS_ARTIFACT:
            raise AutomationError("SCHEMA_INVALID", "ARTIFACT_NAME")
        if not isinstance(data, bytes) or b"\r" in data or not data.endswith(b"\n"):
            raise AutomationError("SCHEMA_INVALID", "ARTIFACT_BYTES")                   # UTF-8 ・LF ・末尾の改行
        ordered.append((name, data))
    return tuple(ordered)


def run_directory(p12_root: Any, run_id: str) -> Path:
    if not is_digest(run_id):
        raise AutomationError("SCHEMA_INVALID", "RUN_ID")
    return Path(p12_root) / RUNS_DIRECTORY / run_id


def finalize_run(p12_root: Any, run_id: str, artifacts: Mapping[str, bytes]) -> FinalizationOutcome:
    ordered = validate_artifacts(artifacts)
    final = run_directory(p12_root, run_id)
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    try:
        runs = final.parent
        runs.parent.mkdir(parents=False, exist_ok=True)                                # 明示の root（親は在ること）と runs/ だけ初期化する
        runs.mkdir(parents=False, exist_ok=True)
        if final.exists() or final.is_symlink():
            raise AutomationError("DUPLICATE_INVOCATION", "FINAL_EXISTS")
        if partial.exists() or partial.is_symlink():
            raise AutomationError("DUPLICATE_INVOCATION", "PARTIAL_EXISTS")
        partial.mkdir(parents=False, exist_ok=False)
        digests: Dict[str, str] = {}
        for name, data in ordered:
            digests[name] = _write_artifact(partial / name, data)
        digest_bytes = (canonical_json(digests) + "\n").encode("utf-8")
        digests[DIGESTS_ARTIFACT] = _write_artifact(partial / DIGESTS_ARTIFACT, digest_bytes)
        for name, data in ordered:                                                     # 全 artifact の digest を再照合
            if hashlib.sha256((partial / name).read_bytes()).hexdigest() != digests[name]:
                raise AutomationError("STEP_FAILED", "ARTIFACT_DIGEST_MISMATCH")
        _fsync_directory(partial)
        if final.exists() or final.is_symlink():
            raise AutomationError("DUPLICATE_INVOCATION", "FINAL_EXISTS")
        os.rename(partial, final)                                                      # 原子的 ・1 回だけ ・上書きしない
        _fsync_directory(runs)
    except OSError:
        raise AutomationError("STEP_FAILED", "FINALIZATION_IO") from None             # path ・OS の文は出さない
    return FinalizationOutcome(status=FINALIZED_PENDING_LEDGER, artifact_count=len(digests),
                               artifact_digests=tuple(digests[name] for name in sorted(digests)))


__all__ = ["DIGESTS_ARTIFACT", "FINALIZED_PENDING_LEDGER", "MAX_ARTIFACTS", "PARTIAL_SUFFIX", "RUNS_DIRECTORY",
           "FinalizationOutcome", "finalize_run", "run_directory", "validate_artifacts"]
