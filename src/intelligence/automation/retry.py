"""P12-A4 — retry は常に新しい run（同じ schedule_id ・slot_id ・scheduled_for ・runtime_anchor ・attempt ＋ 1 ・retry_of ＝ 前の run_id）。

- 許す source（ledger の終端）: FAILED ・CRASHED ・ORPHANED_FINALIZATION。拒む: SUCCEEDED（ALREADY_SUCCEEDED）・SKIPPED ・CANCELLED
  （人の明示の承認は v1 に無い）・開いている run（RUNNING ／ PLANNED: `DUPLICATE_INVOCATION:RUN_OPEN` ・lock が生きていれば RUN_ACTIVE）。
- attempt は人が決めない: 同じ identity（schedule_id ・slot_id ・scheduled_for ・runtime_anchor）の ledger の最大の attempt ＋ 1。
- 前の run の directory ・record は変えない。要求は `requests/<run_id>.json` の証拠から再構成する（PIT ・schedule_digest ・session を保つ）。
"""
from __future__ import annotations

from typing import Any, Dict

from .execution_request import AutomationExecutionRequest
from .failure_codes import AutomationError
from .ledger_store import LedgerState
from .operational_lock import classify_lock, run_lock_file
from .preconditions import PrivateRoots
from .process_probe import ProcessProbe
from .run_state import RunState
from .run_transaction import read_recorded_request

RETRYABLE_STATES = frozenset({RunState.FAILED, RunState.CRASHED, RunState.ORPHANED_FINALIZATION})


def next_attempt(state: LedgerState, prior: AutomationExecutionRequest) -> int:
    same = [r.attempt for r in state.records if r.schedule_id == prior.schedule_id and r.slot_id == prior.slot_id
            and r.scheduled_for == prior.to_dict()["scheduled_for"] and r.runtime_anchor == prior.runtime_anchor]
    return 1 + max(same, default=prior.attempt)


def build_retry_request(roots: PrivateRoots, prior_run_id: str, *, state: LedgerState, probe: ProcessProbe,
                        operator: str) -> AutomationExecutionRequest:
    prior_state = state.run_states.get(prior_run_id)
    if prior_state is None:
        raise AutomationError("DUPLICATE_INVOCATION", "RUN_UNKNOWN")
    if prior_state is RunState.SUCCEEDED:
        raise AutomationError("ALREADY_SUCCEEDED")
    if prior_state in (RunState.PLANNED, RunState.RUNNING):
        lock_class = classify_lock(run_lock_file(roots.p12_root, prior_run_id), probe=probe, ledger_state=state)["lock_class"]
        raise AutomationError("DUPLICATE_INVOCATION", "RUN_ACTIVE" if lock_class == "LOCK_LIVE" else "RUN_OPEN")
    if prior_state not in RETRYABLE_STATES:
        raise AutomationError("DUPLICATE_INVOCATION", f"NOT_RETRYABLE_{prior_state.value}")
    prior = read_recorded_request(roots.p12_root, prior_run_id)
    if prior is None or prior.run_id != prior_run_id:
        raise AutomationError("SCHEMA_INVALID", "REQUEST_EVIDENCE_MISSING")
    return AutomationExecutionRequest(schedule_id=prior.schedule_id, slot_id=prior.slot_id, scheduled_for=prior.scheduled_for,
                                      as_of_date=prior.as_of_date, session_date=prior.session_date, runtime_anchor=prior.runtime_anchor,
                                      attempt=next_attempt(state, prior), operator=operator, schedule_digest=prior.schedule_digest,
                                      retry_of=prior_run_id, supersedes=None, readiness_only=prior.readiness_only)


def retry_summary(prior_run_id: str, request: AutomationExecutionRequest) -> Dict[str, Any]:
    return {"retry_of": prior_run_id, "run_id": request.run_id, "attempt": request.attempt}


__all__ = ["RETRYABLE_STATES", "build_retry_request", "next_attempt", "retry_summary"]
