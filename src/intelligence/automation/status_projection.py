"""P12-A1 — ledger の record から status の projection を導く純粋な関数（projection は authority ではない）。

- 入力は record の列 ・runtime_anchor ・schedule_id ・任意の `as_of`（caller が渡す telemetry の瞬間。時計は読まない）。
- 鎖が不正なら fail closed（`LedgerError`）。anchor ・schedule が record と違えば health は ANCHOR_MISMATCH ／ SCHEDULE_MISMATCH。
- 出す欄は id ・code ・瞬間 ・件数だけ（payload ・path ・private な値は無い）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .canonical import is_git_anchor, parse_utc_iso, require_aware
from .failure_codes import AutomationError
from .ledger_model import LedgerRecord, verify_chain
from .run_state import TERMINAL_STATES, RunState
from .step_result import STEP_ORDER

STATUS_SCHEMA_VERSION = "p12_status_projection:0.1.0"
FRESH_WITHIN = timedelta(hours=24)
AGING_WITHIN = timedelta(hours=72)
STALENESS_CLASSES: Tuple[str, ...] = ("FRESH", "AGING", "STALE", "UNKNOWN")
HEALTH_CODES: Tuple[str, ...] = ("OK", "RUNNING", "FAILED", "CRASHED", "ORPHANED_FINALIZATION", "CANCELLED", "SKIPPED",
                                 "NO_RUNS", "ANCHOR_MISMATCH", "SCHEDULE_MISMATCH")


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    slot_id: str
    scheduled_for: str
    attempt: int
    state: RunState
    recorded_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {"run_id": self.run_id, "slot_id": self.slot_id, "scheduled_for": self.scheduled_for,
                "attempt": self.attempt, "state": self.state.value, "recorded_at": self.recorded_at}


@dataclass(frozen=True)
class StatusProjection:
    runtime_anchor: str
    schedule_id: str
    record_count: int
    head_digest: str
    last_successful_run: Optional[RunSummary]
    active_run: Optional[RunSummary]
    last_terminal_run: Optional[RunSummary]
    last_failure_code: Optional[str]
    staleness_class: str
    source_completeness: Mapping[str, str]
    health_code: str
    schema_version: str = STATUS_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "runtime_anchor": self.runtime_anchor,
                "schedule_id": self.schedule_id, "record_count": self.record_count, "head_digest": self.head_digest,
                "last_successful_run": None if self.last_successful_run is None else self.last_successful_run.to_dict(),
                "active_run": None if self.active_run is None else self.active_run.to_dict(),
                "last_terminal_run": None if self.last_terminal_run is None else self.last_terminal_run.to_dict(),
                "last_failure_code": self.last_failure_code, "staleness_class": self.staleness_class,
                "source_completeness": dict(self.source_completeness), "health_code": self.health_code}


def _summary(record: LedgerRecord) -> RunSummary:
    return RunSummary(run_id=record.run_id, slot_id=record.slot_id, scheduled_for=record.scheduled_for,
                      attempt=record.attempt, state=record.transition_to, recorded_at=record.recorded_at)


def project_status(records: Sequence[LedgerRecord], *, runtime_anchor: str, schedule_id: str,
                   as_of: Optional[datetime] = None) -> StatusProjection:
    if not is_git_anchor(runtime_anchor):
        raise AutomationError("SCHEMA_INVALID", "RUNTIME_ANCHOR")
    if as_of is not None:
        require_aware(as_of, "SCHEMA_INVALID")                                            # naive な瞬間は受けない
    summary = verify_chain(records)                                                   # 不正な ledger は fail closed
    last_by_run: Dict[str, LedgerRecord] = {}
    for record in records:
        last_by_run[record.run_id] = record
    ordered = sorted(last_by_run.values(), key=lambda r: r.sequence)
    successes = [r for r in ordered if r.transition_to is RunState.SUCCEEDED]
    terminals = [r for r in ordered if r.transition_to in TERMINAL_STATES]
    actives = [r for r in ordered if r.transition_to in (RunState.PLANNED, RunState.RUNNING)]
    last_success = successes[-1] if successes else None
    last_terminal = terminals[-1] if terminals else None
    active = actives[-1] if actives else None
    failures = [r for r in ordered if r.failure_code is not None]
    staleness = "UNKNOWN"
    if last_success is not None and as_of is not None:
        age = require_aware(as_of, "SCHEMA_INVALID") - parse_utc_iso(last_success.scheduled_for)
        staleness = "FRESH" if age <= FRESH_WITHIN else ("AGING" if age <= AGING_WITHIN else "STALE")
    completeness = {step: "NONE" for step in STEP_ORDER}
    if last_success is not None:
        for step in last_success.step_results:
            completeness[step.step_code] = step.completeness_code
    if any(r.runtime_anchor != runtime_anchor for r in records):
        health = "ANCHOR_MISMATCH"
    elif any(r.schedule_id != schedule_id for r in records):
        health = "SCHEDULE_MISMATCH"
    elif not records:
        health = "NO_RUNS"
    elif active is not None:
        health = "RUNNING"
    else:
        health = {RunState.SUCCEEDED: "OK", RunState.FAILED: "FAILED", RunState.CRASHED: "CRASHED",
                  RunState.ORPHANED_FINALIZATION: "ORPHANED_FINALIZATION", RunState.CANCELLED: "CANCELLED",
                  RunState.SKIPPED: "SKIPPED"}[last_terminal.transition_to]  # type: ignore[union-attr]
    return StatusProjection(runtime_anchor=runtime_anchor, schedule_id=schedule_id, record_count=summary.record_count,
                            head_digest=summary.head_digest,
                            last_successful_run=None if last_success is None else _summary(last_success),
                            active_run=None if active is None else _summary(active),
                            last_terminal_run=None if last_terminal is None else _summary(last_terminal),
                            last_failure_code=failures[-1].failure_code if failures else None, staleness_class=staleness,
                            source_completeness=completeness, health_code=health)


__all__ = ["AGING_WITHIN", "FRESH_WITHIN", "HEALTH_CODES", "RunSummary", "STALENESS_CLASSES", "STATUS_SCHEMA_VERSION",
           "StatusProjection", "project_status"]
