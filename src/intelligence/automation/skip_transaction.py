"""P12-A5.1 — scheduler の意味の skip の transaction（MISSED ・NON_BUSINESS_DAY）。ledger に PLANNED → SKIPPED の終端を commit する。

A0 の規則: ledger が運用の実行の authority。Task Scheduler の履歴は補助の telemetry であり、MISSED ・NON_BUSINESS_DAY の証拠にはならない。
A2 の実行 ・artifact の directory は無い（純粋な skip）。status.json だけを書く偽の skip はしない。

順: 1 ledger ＋ checkpoint の検証と重複の分類（A4 の `preflight`。同じ run_id の終端 SKIPPED は ALREADY_SKIPPED として no-op）→ 2 run の lock
→ 3 要求の証拠 → 4 PLANNED → 5 PLANNED → SKIPPED（failure_code ＝ skip の code）→ 6 再検証 → 7 status の再生成 → 8 lock の解放。
identity は通常の run と同じ（attempt 1。Task Scheduler が 2 度起こしても attempt 2 は作らない）。retry の意味は SKIPPED には無い。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .canonical import utc_iso
from .execution_request import AutomationExecutionRequest
from .failure_codes import AutomationError, is_safe_code
from .injection import NO_INJECTION, InjectionPoints
from .ledger_commit import LockedLedger
from .ledger_model import LedgerError, make_record
from .operational_lock import LockHeld, acquire_lock, classify_lock, lock_is_stale, run_lock_file
from .preconditions import PrivateRoots
from .process_probe import ProcessProbe
from .run_state import RunState
from .run_transaction import preflight, record_request
from .status_store import write_status

SKIP_STAGES: Tuple[str, ...] = ("LEDGER_VERIFIED", "LOCK_ACQUIRED", "REQUEST_RECORDED", "PLANNED_RECORDED", "SKIPPED_RECORDED",
                                "LEDGER_REVERIFIED", "STATUS_PROJECTED", "LOCK_RELEASED")
SKIP_SCHEMA_VERSION = "p12_skip_transaction:0.1.0"
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class SkipResult:
    run_id: str
    status: str                                # SKIPPED（今 commit した）・ALREADY_SKIPPED（既に終端）・FAILED
    skip_code: Optional[str]                   # ledger の failure_code（SKIPPED ／ ALREADY_SKIPPED）
    failure_code: Optional[str]                # FAILED の code
    stages_completed: Tuple[str, ...]
    ledger_record_count: Optional[int]
    ledger_head_digest: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": SKIP_SCHEMA_VERSION, "run_id": self.run_id, "status": self.status, "skip_code": self.skip_code,
                "failure_code": self.failure_code, "stages_completed": list(self.stages_completed),
                "ledger_record_count": self.ledger_record_count, "ledger_head_digest": self.ledger_head_digest}


def commit_skip(request: AutomationExecutionRequest, roots: PrivateRoots, *, skip_code: str, environment: Mapping[str, str],
                clock: Clock, probe: Optional[ProcessProbe] = None, injection: InjectionPoints = NO_INJECTION) -> SkipResult:
    if not isinstance(request, AutomationExecutionRequest) or not isinstance(roots, PrivateRoots):
        raise AutomationError("SCHEMA_INVALID", "TRANSACTION_INPUT")
    if not is_safe_code(skip_code):
        raise AutomationError("SCHEMA_INVALID", "SKIP_CODE")
    if not callable(clock):
        raise AutomationError("SCHEMA_INVALID", "CLOCK_REQUIRED")
    probe = ProcessProbe() if probe is None else probe
    ledger = LockedLedger(roots.p12_root, probe=probe, clock=clock, injection=injection)
    run = request.run
    stages: list = []

    def failed(code: str, state: Any = None) -> SkipResult:
        return SkipResult(run_id=request.run_id, status="FAILED", skip_code=None, failure_code=code, stages_completed=tuple(stages),
                          ledger_record_count=None if state is None else state.summary.record_count,
                          ledger_head_digest=None if state is None else state.summary.head_digest)

    try:
        state = preflight(ledger, request, roots, environment, probe)
    except AutomationError as exc:
        if exc.public_code == "DUPLICATE_INVOCATION:RUN_TERMINAL":
            recorded = ledger.read_verified(request.run_id).last_record_of(request.run_id)
            if recorded is not None and recorded.transition_to is RunState.SKIPPED:        # 既に記録済みの skip: 重複は追記しない
                return SkipResult(run_id=request.run_id, status="ALREADY_SKIPPED", skip_code=recorded.failure_code, failure_code=None,
                                  stages_completed=("LEDGER_VERIFIED",), ledger_record_count=None, ledger_head_digest=None)
        return failed(exc.public_code)
    stages.append("LEDGER_VERIFIED")
    try:
        held = acquire_lock(roots.p12_root, "RUN", request.run_id, probe=probe, clock_instant=clock(),
                            scheduled_for=utc_iso(request.scheduled_for), attempt=request.attempt)
    except LockHeld:
        classification = classify_lock(run_lock_file(roots.p12_root, request.run_id), probe=probe, ledger_state=state)
        if classification["lock_class"] == "LOCK_LIVE":
            return failed("DUPLICATE_INVOCATION:RUN_ACTIVE", state)
        return failed("DUPLICATE_INVOCATION:LOCK_STALE" if lock_is_stale(classification) else
                      f"DUPLICATE_INVOCATION:{classification['lock_class']}", state)
    except AutomationError as exc:
        return failed(exc.public_code, state)
    stages.append("LOCK_ACQUIRED")
    injection.fire("AFTER_LOCK_ACQUIRED")

    def transition(to_state: RunState, from_state: Optional[RunState], **extra: Any) -> Any:
        return ledger.commit(request.run_id, lambda head, _s: make_record(head, run, transition_from=from_state, transition_to=to_state,
                                                                          recorded_at=utc_iso(clock()), **extra))

    try:
        record_request(roots.p12_root, request)
        stages.append("REQUEST_RECORDED")
        state = transition(RunState.PLANNED, None)
        stages.append("PLANNED_RECORDED")
        injection.fire("AFTER_PLANNED_APPEND")
        state = transition(RunState.SKIPPED, RunState.PLANNED, failure_code=skip_code)
        stages.append("SKIPPED_RECORDED")
        reverified = ledger.store.open_verified()
        if reverified.run_states.get(request.run_id) is not RunState.SKIPPED:
            raise LedgerError("REVERIFY_MISMATCH")
        state = reverified
        stages.append("LEDGER_REVERIFIED")
        injection.fire("BEFORE_STATUS_WRITE")
        write_status(roots.p12_root, state, runtime_anchor=request.runtime_anchor, schedule_id=request.schedule_id, as_of=clock())
        stages.append("STATUS_PROJECTED")
    except AutomationError as exc:
        injection.fire("BEFORE_LOCK_RELEASE")
        held.release()
        stages.append("LOCK_RELEASED")
        return failed(exc.public_code, state)
    injection.fire("BEFORE_LOCK_RELEASE")
    held.release()
    stages.append("LOCK_RELEASED")
    return SkipResult(run_id=request.run_id, status="SKIPPED", skip_code=skip_code, failure_code=None, stages_completed=tuple(stages),
                      ledger_record_count=state.summary.record_count, ledger_head_digest=state.summary.head_digest)


__all__ = ["SKIP_SCHEMA_VERSION", "SKIP_STAGES", "SkipResult", "commit_skip"]
