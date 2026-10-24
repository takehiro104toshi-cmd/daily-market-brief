"""P12-A5 — scheduled-run の解決と無人の実行（Task Scheduler → CLI → ここ → A3 ／ A4 の transaction）。

時間の規則（A0）: `selection_clock_at` は process の入口で 1 回だけ観測し、どの slot の instance が eligible かを決めるだけに使う。
`scheduled_for` は schedule authority（A1 `plan_run`）から導き、as_of_date ・session_date ・identity ・source の選択は全て scheduled_for から。
telemetry の時計は別に渡す（意味に影響しない）。backfill ・近い slot の選択 ・曖昧な推定はしない。

無人の方針（監督の lock）: 回復が要る状態（不正な ledger ・遅れた checkpoint ・孤児 ・partial ・stale ／ 不明な lock ・前の attempt の存在）
では **何もせず** `RECOVERY_REQUIRED` で止まる（証拠は触らない ・retry しない）。生きた lock の重複は `DUPLICATE_ACTIVE`。

結果の証拠の方針（A5.1 ・監督の lock）: NOT_DUE ・DISABLED は ledger に書かない（意味の run ではない ・authority が証拠）。
MISSED ・NON_BUSINESS_DAY（readiness を許さない slot）は **ledger に PLANNED → SKIPPED を commit する**（`skip_transaction`。A2 の実行 ・artifact は
無い）。ALREADY_SUCCEEDED ・DUPLICATE_ACTIVE ・RECOVERY_REQUIRED は追記しない。同じ instance の 2 度目の起動は記録済みの終端に解決する
（ALREADY_SKIPPED ・attempt 2 は作らない）。

exit code（Task Scheduler は stdout を読まない）:
  0 SUCCEEDED ／ 安全な no-op（NOT_DUE ・DISABLED ・ALREADY_SUCCEEDED）／ 記録した skip（NON_BUSINESS_DAY）
  1 transaction が FAILED（A2 の step の失敗 ・repo が汚れている ・凍結の drift ・root 不在など ledger に記録された失敗）
  4 MISSED（late window の外。ledger に SKIPPED を記録）  5 RECOVERY_REQUIRED  6 DUPLICATE_ACTIVE  7 AUTHORITY_INVALID（schedule ・calendar ・pin ・slot）
  8 PRECONDITION_REFUSED（資格情報 ・HEAD ≠ pin。transaction の前 ・ledger に書かない）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .calendar_authority import read_calendar_authority
from .canonical import utc_iso
from .execution_request import AutomationExecutionRequest
from .failure_codes import AutomationError
from .ledger_commit import LockedLedger
from .ledger_model import LedgerError
from .operational_lock import LockHeld, classify_lock, run_lock_file
from .preconditions import PrivateRoots, credential_present
from .process_probe import ProcessProbe
from .run_planning import NonRun, PlannedRun, plan_run, nominal_instant
from .run_state import RunState
from .run_transaction import TransactionResult, commit_run
from .runtime_pin import read_runtime_pin, repo_head
from .schedule_authority import read_schedule_authority
from .schedule_model import TOKYO
from .skip_transaction import SkipResult, commit_skip

EXIT_OK, EXIT_FAILED, EXIT_MISSED, EXIT_RECOVERY_REQUIRED, EXIT_DUPLICATE_ACTIVE, EXIT_AUTHORITY_INVALID, EXIT_PRECONDITION_REFUSED = 0, 1, 4, 5, 6, 7, 8
SCHEDULED_OPERATOR = "scheduler"
RECOVERY_CODES = ("ORPHANED_FINALIZATION", "DUPLICATE_INVOCATION:PARTIAL_EXISTS", "DUPLICATE_INVOCATION:RUN_OPEN",
                  "DUPLICATE_INVOCATION:RUN_TERMINAL", "DUPLICATE_INVOCATION:LOCK_STALE", "DUPLICATE_INVOCATION:LOCK_UNKNOWN_PROVENANCE",
                  "DUPLICATE_INVOCATION:LOCK_MALFORMED", "DUPLICATE_INVOCATION:REQUEST_MISMATCH")
DUPLICATE_CODES = ("DUPLICATE_INVOCATION:RUN_ACTIVE", "DUPLICATE_INVOCATION:LEDGER_LOCKED")
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class ScheduledOutcome:
    kind: str                                  # SUCCEEDED ・FAILED ・SKIPPED ・MISSED ・RECOVERY_REQUIRED ・DUPLICATE_ACTIVE ・AUTHORITY_INVALID ・REFUSED
    code: str
    exit_code: int
    run_id: Optional[str] = None
    scheduled_for: Optional[str] = None
    transaction: Optional[TransactionResult] = None
    skip: Optional[SkipResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "code": self.code, "exit_code": self.exit_code, "run_id": self.run_id,
                "scheduled_for": self.scheduled_for}


def classify_window(slot: Any, selection_clock_at: datetime) -> Tuple[str, Optional[datetime]]:
    """OUTSIDE_WINDOW の精密化。候補は今日の instance と、late window が今日に跨る時だけ昨日の instance（それ以外の昨日は見ない:
    期限の切れた前日を backfill しない）。時計以前の最新の候補が無ければ NOT_DUE（記録しない）、在ればその instance の窓の後 ＝ MISSED
    （その scheduled_for を skip として記録する）。他の slot ・曖昧な推定はしない。"""
    local = selection_clock_at.astimezone(TOKYO)
    same_day = nominal_instant(slot, local.date())
    prior_day = nominal_instant(slot, local.date() - timedelta(days=1))
    candidates = [same_day]
    if prior_day + timedelta(seconds=slot.late_window_seconds) >= same_day.replace(hour=0, minute=0):
        candidates.append(prior_day)                                                       # 窓が日付を跨ぐ slot だけ
    due = [c for c in candidates if c <= selection_clock_at]
    if not due:
        return "NOT_DUE", None
    nominal = max(due)
    if selection_clock_at > nominal + timedelta(seconds=slot.late_window_seconds):
        return "MISSED", nominal
    return "OUTSIDE_WINDOW", nominal


def resolve_scheduled_run(p12_root: Any, slot_id: str, *, selection_clock_at: datetime, runtime_anchor: str,
                          probe: ProcessProbe, clock: Clock) -> Tuple[Any, Optional[AutomationExecutionRequest]]:
    """schedule ・calendar の authority と ledger から PlannedRun ／ NonRun を導き、要求を組む（書かない）。"""
    schedule = read_schedule_authority(p12_root)
    slot = schedule.slot(slot_id)
    if slot is None:
        raise AutomationError("SCHEMA_INVALID", "SLOT_NOT_FOUND")
    calendar = read_calendar_authority(p12_root, schedule.holiday_calendar_ref)        # 無い ・違う → CALENDAR_UNAVAILABLE
    planned = plan_run(schedule, calendar, slot_id=slot_id, selection_clock_at=selection_clock_at, operator=SCHEDULED_OPERATOR)
    if isinstance(planned, NonRun):
        if planned.outcome == "OUTSIDE_WINDOW" and planned.detail == "OUTSIDE_WINDOW":
            window, nominal = classify_window(slot, selection_clock_at)
            planned = NonRun(planned.outcome, window, planned.schedule_id, planned.slot_id, nominal)
        if planned.detail == "MISSED" or planned.outcome == "NON_BUSINESS_DAY":
            scheduled_for = planned.scheduled_for
            as_of_date = scheduled_for.astimezone(TOKYO).date()
            session_date = calendar.last_business_day_on_or_before(as_of_date) or as_of_date
            request = AutomationExecutionRequest(schedule_id=schedule.schedule_id, slot_id=slot_id, scheduled_for=scheduled_for,
                                                 as_of_date=as_of_date, session_date=session_date, runtime_anchor=runtime_anchor, attempt=1,
                                                 operator=SCHEDULED_OPERATOR, schedule_digest=schedule.content_digest, readiness_only=False)
            return planned, request                                                     # 意味の skip: ledger に記録する要求
        return planned, None
    assert isinstance(planned, PlannedRun)
    state = LockedLedger(p12_root, probe=probe, clock=clock).read_verified("0" * 64)      # lock の中で読む
    scheduled_for_text = utc_iso(planned.scheduled_for)
    prior = [r for r in state.records if r.schedule_id == schedule.schedule_id and r.slot_id == slot_id
             and r.scheduled_for == scheduled_for_text]
    if prior:
        states = {state.run_states[r.run_id] for r in prior}
        if any(s is RunState.SUCCEEDED for s in states):
            return NonRun("ALREADY_SUCCEEDED", "ALREADY_SUCCEEDED", schedule.schedule_id, slot_id, planned.scheduled_for), None
        last_prior = prior[-1]
        if state.run_states[last_prior.run_id] in (RunState.PLANNED, RunState.RUNNING):
            lock_class = classify_lock(run_lock_file(p12_root, last_prior.run_id), probe=probe, ledger_state=state)["lock_class"]
            if lock_class == "LOCK_LIVE":
                raise AutomationError("DUPLICATE_INVOCATION", "RUN_ACTIVE")                # 同じ instance が今走っている（重複の起動）
        raise AutomationError("DUPLICATE_INVOCATION", "PRIOR_ATTEMPT_EXISTS")             # 無人では retry しない（人の手）
    request = AutomationExecutionRequest(schedule_id=schedule.schedule_id, slot_id=slot_id, scheduled_for=planned.scheduled_for,
                                         as_of_date=planned.as_of_date, session_date=planned.session_date, runtime_anchor=runtime_anchor,
                                         attempt=1, operator=SCHEDULED_OPERATOR, schedule_digest=schedule.content_digest,
                                         readiness_only=planned.readiness_only)
    return planned, request


def _commit_scheduled_skip(planned: NonRun, request: AutomationExecutionRequest, roots: PrivateRoots, *, environment: Mapping[str, str],
                           clock: Clock, probe: ProcessProbe) -> ScheduledOutcome:
    missed = planned.detail == "MISSED"
    kind = "MISSED" if missed else "SKIPPED"
    exit_code = EXIT_MISSED if missed else EXIT_OK
    skip_code = "OUTSIDE_WINDOW:MISSED" if missed else f"{planned.outcome}:{planned.detail}"
    scheduled_text = utc_iso(request.scheduled_for)
    result = commit_skip(request, roots, skip_code=skip_code, environment=environment, clock=clock, probe=probe)
    if result.status == "SKIPPED":
        return ScheduledOutcome(kind, skip_code, exit_code, request.run_id, scheduled_text, skip=result)
    if result.status == "ALREADY_SKIPPED":
        return ScheduledOutcome(kind, f"ALREADY_SKIPPED:{result.skip_code}", exit_code, request.run_id, scheduled_text, skip=result)
    code = result.failure_code or "FAILED"
    if code == "ALREADY_SUCCEEDED":                                                        # 既に成功していた instance: 記録済みが authority
        return ScheduledOutcome("SKIPPED", code, EXIT_OK, request.run_id, scheduled_text, skip=result)
    if code in DUPLICATE_CODES:
        return ScheduledOutcome("DUPLICATE_ACTIVE", code, EXIT_DUPLICATE_ACTIVE, request.run_id, scheduled_text, skip=result)
    if code in RECOVERY_CODES or code.startswith("LEDGER_INVALID"):
        return ScheduledOutcome("RECOVERY_REQUIRED", code, EXIT_RECOVERY_REQUIRED, request.run_id, scheduled_text, skip=result)
    return ScheduledOutcome("FAILED", code, EXIT_FAILED, request.run_id, scheduled_text, skip=result)


def run_scheduled(slot_id: str, roots: PrivateRoots, *, repo_root: Any, runtime_root: Any, environment: Mapping[str, str],
                  selection_clock_at: datetime, clock: Clock, probe: Optional[ProcessProbe] = None) -> ScheduledOutcome:
    probe = ProcessProbe() if probe is None else probe
    if credential_present(environment):
        return ScheduledOutcome("REFUSED", "CREDENTIAL_PRESENT", EXIT_PRECONDITION_REFUSED)
    try:
        pinned = read_runtime_pin(roots.p12_root)
    except AutomationError as exc:
        return ScheduledOutcome("AUTHORITY_INVALID", exc.public_code, EXIT_AUTHORITY_INVALID)
    head = repo_head(repo_root)
    if head is None:
        return ScheduledOutcome("REFUSED", "REPO_HEAD_MISMATCH:GIT_UNAVAILABLE", EXIT_PRECONDITION_REFUSED)
    if head != pinned:
        return ScheduledOutcome("REFUSED", "REPO_HEAD_MISMATCH", EXIT_PRECONDITION_REFUSED)  # pull ・checkout はしない
    try:
        planned, request = resolve_scheduled_run(roots.p12_root, slot_id, selection_clock_at=selection_clock_at, runtime_anchor=pinned,
                                                 probe=probe, clock=clock)
    except LockHeld as exc:
        return ScheduledOutcome("DUPLICATE_ACTIVE", exc.public_code, EXIT_DUPLICATE_ACTIVE)
    except LedgerError as exc:
        return ScheduledOutcome("RECOVERY_REQUIRED", exc.public_code, EXIT_RECOVERY_REQUIRED)
    except AutomationError as exc:
        if exc.public_code == "DUPLICATE_INVOCATION:PRIOR_ATTEMPT_EXISTS":
            return ScheduledOutcome("RECOVERY_REQUIRED", exc.public_code, EXIT_RECOVERY_REQUIRED)
        if exc.public_code in DUPLICATE_CODES:
            return ScheduledOutcome("DUPLICATE_ACTIVE", exc.public_code, EXIT_DUPLICATE_ACTIVE)
        return ScheduledOutcome("AUTHORITY_INVALID", exc.public_code, EXIT_AUTHORITY_INVALID)
    if isinstance(planned, NonRun):
        scheduled_text = utc_iso(planned.scheduled_for) if planned.scheduled_for is not None else None
        if request is not None:                                                            # MISSED ・NON_BUSINESS_DAY: ledger に skip を記録
            return _commit_scheduled_skip(planned, request, roots, environment=environment, clock=clock, probe=probe)
        if planned.outcome == "SLOT_NOT_FOUND":
            return ScheduledOutcome("AUTHORITY_INVALID", "SCHEMA_INVALID:SLOT_NOT_FOUND", EXIT_AUTHORITY_INVALID)
        if planned.outcome == "CALENDAR_UNAVAILABLE":
            return ScheduledOutcome("AUTHORITY_INVALID", f"CALENDAR_UNAVAILABLE:{planned.detail}", EXIT_AUTHORITY_INVALID, scheduled_for=scheduled_text)
        code = planned.outcome if planned.detail == planned.outcome else f"{planned.outcome}:{planned.detail}"
        return ScheduledOutcome("SKIPPED", code, EXIT_OK, scheduled_for=scheduled_text)
    result = commit_run(request, roots, repo_root=repo_root, runtime_root=runtime_root, environment=environment, clock=clock, probe=probe)
    scheduled_text = utc_iso(request.scheduled_for)
    if result.status == "SUCCEEDED":
        return ScheduledOutcome("SUCCEEDED", "RUN_SUCCEEDED", EXIT_OK, request.run_id, scheduled_text, result)
    code = result.failure_code or "FAILED"
    if code == "ALREADY_SUCCEEDED":
        return ScheduledOutcome("SKIPPED", code, EXIT_OK, request.run_id, scheduled_text, result)
    if code in DUPLICATE_CODES:
        return ScheduledOutcome("DUPLICATE_ACTIVE", code, EXIT_DUPLICATE_ACTIVE, request.run_id, scheduled_text, result)
    if code in RECOVERY_CODES or code.startswith("LEDGER_INVALID"):
        return ScheduledOutcome("RECOVERY_REQUIRED", code, EXIT_RECOVERY_REQUIRED, request.run_id, scheduled_text, result)
    return ScheduledOutcome("FAILED", code, EXIT_FAILED, request.run_id, scheduled_text, result)


__all__ = ["DUPLICATE_CODES", "EXIT_AUTHORITY_INVALID", "EXIT_DUPLICATE_ACTIVE", "EXIT_FAILED", "EXIT_MISSED", "EXIT_OK",
           "EXIT_PRECONDITION_REFUSED", "EXIT_RECOVERY_REQUIRED", "RECOVERY_CODES", "SCHEDULED_OPERATOR", "ScheduledOutcome",
           "classify_window", "resolve_scheduled_run", "run_scheduled"]
