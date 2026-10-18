"""P12-A1 — run の計画の純粋な意味（時計を読まない。`selection_clock_at` は caller が渡す）。

- `selection_clock_at` ＝ slot の選択に影響してよい唯一の壁時計の観測。それが決めるのは「どの slot の instance か」だけ。
- `scheduled_for`（slot の名目の瞬間。Asia/Tokyo）だけが `as_of_date` ・`session_date` ・時点 ・市場の意味を決める。
- 窓: `scheduled_for <= selection_clock_at <= scheduled_for + late_window`。前日の instance の窓が日付を跨ぐ場合も見る。
- 非営業日（週末 ・休日）: slot が readiness を許せば `readiness_only=True` の run（session_date は直近の営業日）、許さなければ
  NON_BUSINESS_DAY。calendar が無い ・参照と一致しない → CALENDAR_UNAVAILABLE（営業日でも fail closed）。
- `ALREADY_SUCCEEDED` は caller が前の run の要約を明示に渡した時だけ。attempt は前の run の最大 ＋ 1（retry は新しい run）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from .canonical import date_iso, require_aware, utc_iso
from .failure_codes import AutomationError
from .holiday_calendar import HolidayCalendar
from .run_state import RunState
from .schedule_model import TOKYO, WEEKDAYS, AutomationSchedule, ScheduleSlot

OPERATORS: Tuple[str, ...] = ("scheduler", "human")
PLAN_OUTCOMES: Tuple[str, ...] = ("PLANNED", "DISABLED", "OUTSIDE_WINDOW", "NON_BUSINESS_DAY", "CALENDAR_UNAVAILABLE",
                                  "SLOT_NOT_FOUND", "ALREADY_SUCCEEDED")
MAX_ATTEMPT = 999


@dataclass(frozen=True)
class PlannedRun:
    schedule_id: str
    schedule_digest: str
    slot_id: str
    scheduled_for: datetime                       # aware（Asia/Tokyo）
    as_of_date: date                              # scheduled_for の Tokyo の暦日（見直しの基準の日）
    session_date: date                            # as_of_date 以前の直近の営業日（市場の session の日）
    timezone: str
    operator: str
    attempt: int
    readiness_only: bool                          # 非営業日の readiness だけの run

    def __post_init__(self) -> None:
        require_aware(self.scheduled_for, "SCHEMA_INVALID")
        if self.operator not in OPERATORS:
            raise AutomationError("SCHEMA_INVALID", "OPERATOR")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or not 1 <= self.attempt <= MAX_ATTEMPT:
            raise AutomationError("SCHEMA_INVALID", "ATTEMPT_RANGE")
        if self.session_date > self.as_of_date:
            raise AutomationError("SCHEMA_INVALID", "SESSION_AFTER_AS_OF")

    def to_dict(self) -> Dict[str, Any]:
        return {"outcome": "PLANNED", "schedule_id": self.schedule_id, "schedule_digest": self.schedule_digest,
                "slot_id": self.slot_id, "scheduled_for": utc_iso(self.scheduled_for),
                "scheduled_for_local": self.scheduled_for.astimezone(TOKYO).isoformat(),
                "as_of_date": date_iso(self.as_of_date), "session_date": date_iso(self.session_date),
                "timezone": self.timezone, "operator": self.operator, "attempt": self.attempt,
                "readiness_only": self.readiness_only}


@dataclass(frozen=True)
class NonRun:
    """run にならない明示の結果（code だけ。理由の文 ・path ・private な値は無い）。"""

    outcome: str
    detail: str
    schedule_id: str
    slot_id: str
    scheduled_for: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.outcome not in PLAN_OUTCOMES or self.outcome == "PLANNED":
            raise AutomationError("SCHEMA_INVALID", "OUTCOME")

    def to_dict(self) -> Dict[str, Any]:
        return {"outcome": self.outcome, "detail": self.detail, "schedule_id": self.schedule_id, "slot_id": self.slot_id,
                "scheduled_for": utc_iso(self.scheduled_for) if self.scheduled_for is not None else None}


@dataclass(frozen=True)
class PriorRunSummary:
    """caller が明示に渡す前の run の要約（ledger の projection から作る。authority ではない）。"""

    schedule_id: str
    slot_id: str
    scheduled_for: datetime
    attempt: int
    status: RunState

    def __post_init__(self) -> None:
        require_aware(self.scheduled_for, "SCHEMA_INVALID")
        if not isinstance(self.status, RunState):
            raise AutomationError("SCHEMA_INVALID", "PRIOR_STATUS")


def nominal_instant(slot: ScheduleSlot, local_day: date) -> datetime:
    return datetime(local_day.year, local_day.month, local_day.day, slot.hour, slot.minute, tzinfo=TOKYO)


def _window_contains(slot: ScheduleSlot, scheduled_for: datetime, clock: datetime) -> bool:
    return scheduled_for <= clock <= scheduled_for + timedelta(seconds=slot.late_window_seconds)


def plan_run(schedule: AutomationSchedule, calendar: Optional[HolidayCalendar], *, slot_id: str,
             selection_clock_at: datetime, operator: str = "scheduler",
             prior_runs: Sequence[PriorRunSummary] = (), attempt: Optional[int] = None) -> Union[PlannedRun, NonRun]:
    """schedule ・calendar ・`selection_clock_at` から PlannedRun か明示の NonRun を返す（純粋 ・時計を読まない）。"""
    if not isinstance(schedule, AutomationSchedule):
        raise AutomationError("SCHEMA_INVALID", "SCHEDULE_TYPE")
    clock = require_aware(selection_clock_at, "SELECTION_CLOCK_NOT_AWARE")
    if operator not in OPERATORS:
        raise AutomationError("SCHEMA_INVALID", "OPERATOR")
    if not isinstance(slot_id, str):
        raise AutomationError("SCHEMA_INVALID", "SLOT_ID")
    slot = schedule.slot(slot_id)
    if slot is None:
        return NonRun("SLOT_NOT_FOUND", "SLOT_NOT_FOUND", schedule.schedule_id, slot_id)
    if not schedule.enabled:
        return NonRun("DISABLED", "SCHEDULE_DISABLED", schedule.schedule_id, slot_id)
    if not slot.enabled:
        return NonRun("DISABLED", "SLOT_DISABLED", schedule.schedule_id, slot_id)
    local_clock = clock.astimezone(TOKYO)
    scheduled_for: Optional[datetime] = None
    for day_offset in (0, -1):                                              # 当日の instance ・日付を跨ぐ前日の窓
        candidate = nominal_instant(slot, local_clock.date() + timedelta(days=day_offset))
        if _window_contains(slot, candidate, clock):
            scheduled_for = candidate
            break
    if scheduled_for is None:
        return NonRun("OUTSIDE_WINDOW", "OUTSIDE_WINDOW", schedule.schedule_id, slot_id,
                      nominal_instant(slot, local_clock.date()))
    if WEEKDAYS[scheduled_for.weekday()] not in slot.weekday_mask:
        return NonRun("OUTSIDE_WINDOW", "WEEKDAY_NOT_IN_MASK", schedule.schedule_id, slot_id, scheduled_for)
    if calendar is None or not isinstance(calendar, HolidayCalendar):
        return NonRun("CALENDAR_UNAVAILABLE", "CALENDAR_MISSING", schedule.schedule_id, slot_id, scheduled_for)
    if calendar.reference() != schedule.holiday_calendar_ref:
        return NonRun("CALENDAR_UNAVAILABLE", "CALENDAR_REF_MISMATCH", schedule.schedule_id, slot_id, scheduled_for)
    as_of_date = scheduled_for.date()
    business_day = calendar.is_business_day(as_of_date)
    if not business_day and not slot.readiness_on_non_business_day:
        return NonRun("NON_BUSINESS_DAY", "HOLIDAY" if as_of_date.weekday() < 5 else "WEEKEND", schedule.schedule_id,
                      slot_id, scheduled_for)
    session_date = calendar.last_business_day_on_or_before(as_of_date)
    if session_date is None:
        return NonRun("CALENDAR_UNAVAILABLE", "NO_SESSION_DATE", schedule.schedule_id, slot_id, scheduled_for)
    matching = [p for p in prior_runs if isinstance(p, PriorRunSummary) and p.schedule_id == schedule.schedule_id
                and p.slot_id == slot_id and p.scheduled_for == scheduled_for]
    if any(p.status is RunState.SUCCEEDED for p in matching):
        return NonRun("ALREADY_SUCCEEDED", "ALREADY_SUCCEEDED", schedule.schedule_id, slot_id, scheduled_for)
    next_attempt = 1 + max((p.attempt for p in matching), default=0)
    if attempt is not None:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < next_attempt:
            raise AutomationError("SCHEMA_INVALID", "ATTEMPT_NOT_NEW")                       # retry は常に新しい run
        next_attempt = attempt
    return PlannedRun(schedule_id=schedule.schedule_id, schedule_digest=schedule.content_digest, slot_id=slot_id,
                      scheduled_for=scheduled_for, as_of_date=as_of_date, session_date=session_date,
                      timezone=schedule.timezone, operator=operator, attempt=next_attempt, readiness_only=not business_day)


__all__ = ["MAX_ATTEMPT", "NonRun", "OPERATORS", "PLAN_OUTCOMES", "PlannedRun", "PriorRunSummary", "nominal_instant",
           "plan_run"]
