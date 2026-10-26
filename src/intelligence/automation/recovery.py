"""P12-A4 — crash の状態の明示の回復（人の手だけ ・分類が先 ・曖昧なら拒む ・証拠を消さない ・P9 ／ P10 ／ P11 は触れない）。

- `recover_orphan`（窓 A）: final の directory の digests.json と file の sha256 ・request.json の run_id を照合し、ledger の最後が RUNNING で
  lock が生きていなければ、ledger lock の中で RUNNING → ORPHANED_FINALIZATION（artifact の digest を添える）を commit する。
  artifact は証拠として残す。**SUCCEEDED には変えない**（保守的。成功は transaction の中でだけ生まれる）。
- `recover_crashed`: ledger が PLANNED ／ RUNNING で final も .partial も無く、lock が生きていなければ → CRASHED（INTERRUPTED）。
- `recover_partial`（窓 D）: `.partial` を分類（lock が生きていれば ACTIVE → 拒む ・ledger が開いていれば ABANDONED ・無ければ ORPHAN）し、
  `<run_id>.crashed` に rename して証拠を残す。ledger が開いていれば CRASHED も commit する。消さない。
- `repair_checkpoint`（窓 B）: `LockedLedger.repair_checkpoint`（鎖は変えない）。
- `regenerate_status`（窓 C）: 検証済みの ledger から status.json を再生成（authority は変わらない）。
- `release_lock`: stale と証明できた lock だけを `locks/stale/` に rename（LIVE ・MALFORMED ・UNKNOWN は拒む）。
戻りは全て安全な dict（分類 ・code ・件数 ・digest。path ・pid 以外の process の情報は無い）。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .atomic_files import fsync_directory
from .canonical import utc_iso
from .crash_classification import classify_run
from .failure_codes import AutomationError
from .finalization import DIGESTS_ARTIFACT, PARTIAL_SUFFIX, run_directory
from .ledger_commit import LockedLedger
from .ledger_model import make_record
from .ledger_store import LedgerState
from .operational_lock import classify_lock, ledger_lock_file, release_stale_lock, run_lock_file
from .preconditions import PrivateRoots
from .process_probe import ProcessProbe
from .run_state import RunState
from .run_transaction import read_recorded_request
from .status_store import write_status

CRASHED_SUFFIX = ".crashed"
PARTIAL_CLASSES = ("PARTIAL_ACTIVE", "PARTIAL_ABANDONED", "PARTIAL_ORPHAN", "PARTIAL_MALFORMED")
Clock = Callable[[], datetime]


def _verified_state(ledger: LockedLedger) -> LedgerState:
    return ledger.store.open_verified(allow_stale_checkpoint=True)


def _lock_class(roots: PrivateRoots, run_id: str, probe: ProcessProbe, state: LedgerState) -> str:
    return classify_lock(run_lock_file(roots.p12_root, run_id), probe=probe, ledger_state=state)["lock_class"]


def _require_not_live(lock_class: str) -> None:
    if lock_class == "LOCK_LIVE":
        raise AutomationError("DUPLICATE_INVOCATION", "RUN_ACTIVE")
    if lock_class in ("LOCK_UNKNOWN_PROVENANCE", "LOCK_MALFORMED"):
        raise AutomationError("DUPLICATE_INVOCATION", lock_class)                        # provenance を証明できなければ触れない


def verify_final_artifacts(final: Path, run_id: str) -> Dict[str, Any]:
    """digests.json と file の sha256 ・request.json の run_id を照合（読むだけ）。不一致は `SCHEMA_INVALID:ARTIFACT_*`。"""
    try:
        digests = json.loads((final / DIGESTS_ARTIFACT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AutomationError("SCHEMA_INVALID", "ARTIFACT_DIGESTS_UNREADABLE") from None
    names = sorted(p.name for p in final.iterdir() if p.is_file())
    if not isinstance(digests, dict) or sorted([*digests, DIGESTS_ARTIFACT]) != names:
        raise AutomationError("SCHEMA_INVALID", "ARTIFACT_SET_MISMATCH")
    for name, digest in digests.items():
        if hashlib.sha256((final / name).read_bytes()).hexdigest() != digest:
            raise AutomationError("SCHEMA_INVALID", "ARTIFACT_DIGEST_MISMATCH")
    try:
        recorded = json.loads((final / "request.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AutomationError("SCHEMA_INVALID", "ARTIFACT_REQUEST_UNREADABLE") from None
    from .execution_request import AutomationExecutionRequest
    if AutomationExecutionRequest.from_dict(recorded).run_id != run_id:
        raise AutomationError("SCHEMA_INVALID", "ARTIFACT_RUN_ID_MISMATCH")
    all_digests = tuple(sorted(set(digests.values()) | {hashlib.sha256((final / DIGESTS_ARTIFACT).read_bytes()).hexdigest()}))
    return {"artifact_count": len(names), "artifact_digests": all_digests}


def recover_orphan(roots: PrivateRoots, run_id: str, *, probe: ProcessProbe, clock: Clock) -> Dict[str, Any]:
    ledger = LockedLedger(roots.p12_root, probe=probe, clock=clock)
    state = _verified_state(ledger)
    evidence = classify_run(roots.p12_root, run_id, state)
    if evidence.classification != "ORPHANED_FINALIZATION":
        raise AutomationError("DUPLICATE_INVOCATION", evidence.classification)
    if state.run_states.get(run_id) is not RunState.RUNNING:
        raise AutomationError("DUPLICATE_INVOCATION", "LEDGER_NOT_RUNNING")              # ledger の record が無い final は recover-partial 相当ではない: 拒む
    _require_not_live(_lock_class(roots, run_id, probe, state))
    verified = verify_final_artifacts(run_directory(roots.p12_root, run_id), run_id)
    request = read_recorded_request(roots.p12_root, run_id)
    if request is None or request.run_id != run_id:
        raise AutomationError("SCHEMA_INVALID", "REQUEST_EVIDENCE_MISSING")
    run = request.run

    def builder(head: Any, _state: Any) -> Any:
        return make_record(head, run, transition_from=RunState.RUNNING, transition_to=RunState.ORPHANED_FINALIZATION,
                           recorded_at=utc_iso(clock()), failure_code="ORPHANED_FINALIZATION", artifact_digests=verified["artifact_digests"])

    committed = ledger.commit(run_id, builder)
    write_status(roots.p12_root, committed, runtime_anchor=request.runtime_anchor, schedule_id=request.schedule_id, as_of=clock())
    return {"run_id": run_id, "recovery": "ORPHAN_RECORDED", "terminal_state": "ORPHANED_FINALIZATION", **verified,
            "ledger_record_count": committed.summary.record_count, "ledger_head_digest": committed.summary.head_digest}


def recover_crashed(roots: PrivateRoots, run_id: str, *, probe: ProcessProbe, clock: Clock) -> Dict[str, Any]:
    ledger = LockedLedger(roots.p12_root, probe=probe, clock=clock)
    state = _verified_state(ledger)
    evidence = classify_run(roots.p12_root, run_id, state)
    if evidence.classification != "IN_FLIGHT":
        raise AutomationError("DUPLICATE_INVOCATION", evidence.classification)
    _require_not_live(_lock_class(roots, run_id, probe, state))
    request = read_recorded_request(roots.p12_root, run_id)
    if request is None:
        raise AutomationError("SCHEMA_INVALID", "REQUEST_EVIDENCE_MISSING")
    from_state = state.run_states[run_id]

    def builder(head: Any, _state: Any) -> Any:
        return make_record(head, request.run, transition_from=from_state, transition_to=RunState.CRASHED,
                           recorded_at=utc_iso(clock()), failure_code="INTERRUPTED")

    committed = ledger.commit(run_id, builder)
    write_status(roots.p12_root, committed, runtime_anchor=request.runtime_anchor, schedule_id=request.schedule_id, as_of=clock())
    return {"run_id": run_id, "recovery": "CRASHED_RECORDED", "terminal_state": "CRASHED", "from_state": from_state.value,
            "ledger_record_count": committed.summary.record_count, "ledger_head_digest": committed.summary.head_digest}


def classify_partial(roots: PrivateRoots, run_id: str, *, probe: ProcessProbe, state: LedgerState) -> str:
    final = run_directory(roots.p12_root, run_id)
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    if not partial.exists():
        raise AutomationError("DUPLICATE_INVOCATION", "PARTIAL_ABSENT")
    if not partial.is_dir():
        return "PARTIAL_MALFORMED"
    if _lock_class(roots, run_id, probe, state) == "LOCK_LIVE":
        return "PARTIAL_ACTIVE"
    run_state = state.run_states.get(run_id)
    if run_state is None:
        return "PARTIAL_ORPHAN"
    return "PARTIAL_ABANDONED" if run_state in (RunState.PLANNED, RunState.RUNNING) else "PARTIAL_MALFORMED"


def recover_partial(roots: PrivateRoots, run_id: str, *, probe: ProcessProbe, clock: Clock) -> Dict[str, Any]:
    ledger = LockedLedger(roots.p12_root, probe=probe, clock=clock)
    state = _verified_state(ledger)
    partial_class = classify_partial(roots, run_id, probe=probe, state=state)
    if partial_class == "PARTIAL_ACTIVE":
        raise AutomationError("DUPLICATE_INVOCATION", "RUN_ACTIVE")
    _require_not_live(_lock_class(roots, run_id, probe, state))
    final = run_directory(roots.p12_root, run_id)
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    crashed = final.with_name(final.name + CRASHED_SUFFIX)
    if crashed.exists():
        raise AutomationError("DUPLICATE_INVOCATION", "CRASHED_EVIDENCE_EXISTS")        # 既に回復の証拠がある: 上書きしない
    try:
        os.rename(partial, crashed)
        fsync_directory(final.parent)
    except OSError:
        raise AutomationError("STEP_FAILED", "PARTIAL_RENAME_IO") from None
    result: Dict[str, Any] = {"run_id": run_id, "recovery": "PARTIAL_PRESERVED", "partial_class": partial_class,
                              "evidence_suffix": CRASHED_SUFFIX}
    if partial_class == "PARTIAL_ABANDONED":
        result.update(recover_crashed(roots, run_id, probe=probe, clock=clock))
        result["recovery"] = "PARTIAL_PRESERVED_AND_CRASHED_RECORDED"
    return result


def repair_checkpoint(roots: PrivateRoots, *, probe: ProcessProbe, clock: Clock) -> Dict[str, Any]:
    ledger = LockedLedger(roots.p12_root, probe=probe, clock=clock)
    before = _verified_state(ledger)
    repaired = ledger.repair_checkpoint()
    return {"recovery": "CHECKPOINT_REPAIRED", "previous_checkpoint_count": None if before.checkpoint is None else before.checkpoint.record_count,
            "ledger_record_count": repaired.summary.record_count, "ledger_head_digest": repaired.summary.head_digest,
            "checkpoint_class": repaired.checkpoint_class}


def regenerate_status(roots: PrivateRoots, *, clock: Clock, runtime_anchor: Optional[str] = None,
                      schedule_id: Optional[str] = None) -> Dict[str, Any]:
    ledger = LockedLedger(roots.p12_root, probe=ProcessProbe(), clock=clock)
    state = ledger.store.open_verified()                                                # 遅れた checkpoint は先に repair
    if not state.records and (runtime_anchor is None or schedule_id is None):
        raise AutomationError("SCHEMA_INVALID", "STATUS_SCOPE_REQUIRED")
    anchor = runtime_anchor or state.records[-1].runtime_anchor
    schedule = schedule_id or state.records[-1].schedule_id
    document = write_status(roots.p12_root, state, runtime_anchor=anchor, schedule_id=schedule, as_of=clock())
    return {"recovery": "STATUS_REGENERATED", "ledger_record_count": state.summary.record_count,
            "ledger_head_digest": state.summary.head_digest, "health_code": document["projection"]["health_code"]}


def release_lock(roots: PrivateRoots, *, probe: ProcessProbe, run_id: Optional[str] = None) -> Dict[str, Any]:
    """stale と証明できた lock だけを解放（証拠は locks/stale/）。run_id が無ければ ledger lock。"""
    state = None
    try:
        state = LockedLedger(roots.p12_root, probe=probe, clock=lambda: datetime.min).store.open_verified(allow_stale_checkpoint=True)
    except AutomationError:
        state = None                                                                    # ledger が不正でも lock の分類はできる
    target = ledger_lock_file(roots.p12_root) if run_id is None else run_lock_file(roots.p12_root, run_id)
    classification = classify_lock(target, probe=probe, ledger_state=state)
    if classification["lock_class"] == "LOCK_ABSENT":
        return {**classification, "released": False}
    return release_stale_lock(roots.p12_root, target, classification)


__all__ = ["CRASHED_SUFFIX", "PARTIAL_CLASSES", "classify_partial", "recover_crashed", "recover_orphan", "recover_partial",
           "regenerate_status", "release_lock", "repair_checkpoint", "verify_final_artifacts"]
