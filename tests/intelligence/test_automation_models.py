"""P12-A1 — schedule の authority ・休日 calendar ・計画 ・run の identity ・状態機械 ・step の結果の純粋な model の test。

全て合成の値（本物の id ・発行体 ・資格情報 ・private な root は無い）。時計は読まない（`selection_clock_at` は test が渡す）。
"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone

import pytest

from src.intelligence.automation.canonical import canonical_json, domain_digest, parse_utc_iso, require_fields, utc_iso
from src.intelligence.automation.failure_codes import (FAILURE_CODES, AutomationError, Diagnostic, is_reserved_code,
                                                       is_safe_code, safe_code)
from src.intelligence.automation.holiday_calendar import HolidayCalendar
from src.intelligence.automation.run_identity import RUN_ID_DOMAIN, AutomationRun, RunIdentity
from src.intelligence.automation.run_planning import NonRun, PlannedRun, PriorRunSummary, plan_run
from src.intelligence.automation.run_state import (TERMINAL_STATES, TRANSITIONS, IllegalTransition, RunState,
                                                   can_transition, is_terminal, transition)
from src.intelligence.automation.schedule_model import (SCHEDULE_SCHEMA_VERSION, TIMEZONE_V1, TOKYO, AutomationSchedule,
                                                        HolidayCalendarReference, ScheduleSlot)
from src.intelligence.automation.step_result import STEP_ORDER, AutomationStepResult, validate_step_results

ANCHOR = "a" * 40
OTHER_ANCHOR = "b" * 40
UTC = timezone.utc
#: 合成の calendar: 2026-01-12（月）だけを休日にする
HOLIDAY = "2026-01-12"


def calendar() -> HolidayCalendar:
    return HolidayCalendar(calendar_id="ops-cal", version=1, dates=(HOLIDAY,))


def slots() -> tuple:
    return (ScheduleSlot(slot_id="slot-a", local_time="07:30", weekday_mask=("MON", "TUE", "WED", "THU", "FRI"),
                         late_window_seconds=3600, readiness_on_non_business_day=False, enabled=True),
            ScheduleSlot(slot_id="slot-b", local_time="23:30", weekday_mask=("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"),
                         late_window_seconds=7200, readiness_on_non_business_day=True, enabled=True),
            ScheduleSlot(slot_id="slot-c", local_time="12:00", weekday_mask=("MON",), late_window_seconds=0,
                         readiness_on_non_business_day=False, enabled=False))


def schedule(**overrides) -> AutomationSchedule:
    fields = dict(schedule_id="ops-daily", version=1, timezone=TIMEZONE_V1, enabled=True, slots=slots(),
                  holiday_calendar_ref=calendar().reference(), created_at="2026-01-01T00:00:00Z", supersedes=None)
    fields.update(overrides)
    return AutomationSchedule(**fields)


def tokyo(y: int, m: int, d: int, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=TOKYO)


# ================================================================ canonical ・failure codes


def test_canonical_json_is_sorted_compact_and_rejects_floats_and_non_string_keys() -> None:
    assert canonical_json({"b": 1, "a": [True, None, "x"]}) == '{"a":[true,null,"x"],"b":1}'
    assert canonical_json({"k": "日本"}) == '{"k":"日本"}'                                   # ensure_ascii=False
    with pytest.raises(AutomationError) as e:
        canonical_json({"x": 1.5})
    assert e.value.code == "SCHEMA_INVALID"
    with pytest.raises(AutomationError):
        canonical_json({1: "x"})
    assert domain_digest("d1", {"a": 1}) != domain_digest("d2", {"a": 1})                   # domain の分離
    assert domain_digest("d1", {"a": 1}) == domain_digest("d1", {"a": 1}) and len(domain_digest("d1", {})) == 64
    assert utc_iso(tokyo(2026, 1, 5, 9, 0)) == "2026-01-05T00:00:00Z"
    assert parse_utc_iso("2026-01-05T00:00:00Z") == tokyo(2026, 1, 5, 9, 0)
    with pytest.raises(AutomationError):
        utc_iso(datetime(2026, 1, 5))                                                       # naive は拒む
    with pytest.raises(AutomationError) as e:
        require_fields({"a": 1, "zz": 2}, frozenset({"a"}), "CTX")
    assert e.value.detail == "CTX_UNKNOWN_FIELD"
    with pytest.raises(AutomationError) as e:
        require_fields({}, frozenset({"a"}), "CTX")
    assert e.value.detail == "CTX_MISSING_FIELD"


def test_failure_codes_are_reserved_safe_and_errors_never_expose_private_detail() -> None:
    for code in ("REPO_NOT_CLEAN", "REPO_HEAD_MISMATCH", "FROZEN_DRIFT", "ROOT_MISSING", "SCHEMA_INVALID", "SOURCE_STALE",
                 "SOURCE_INCOMPLETE", "DUPLICATE_INVOCATION", "OUTSIDE_WINDOW", "NON_BUSINESS_DAY", "CALENDAR_UNAVAILABLE",
                 "INTERRUPTED", "ORPHANED_FINALIZATION"):
        assert code in FAILURE_CODES and is_reserved_code(code) and is_safe_code(code)
    assert is_safe_code("SCHEMA_INVALID:SLOT_ID") and not is_safe_code("bad code") and not is_safe_code("D:\\x")
    assert not is_safe_code("A" * 65) and not is_reserved_code("NOT_A_CODE")
    with pytest.raises(AutomationError) as e:
        safe_code("not safe")
    assert (e.value.code, e.value.detail) == ("SCHEMA_INVALID", "UNSAFE_CODE")
    err = AutomationError("ROOT_MISSING", "MANIFEST", private_detail="D:\\private\\root\\manifest.json")
    assert err.public_code == "ROOT_MISSING:MANIFEST" and str(err) == "ROOT_MISSING:MANIFEST"
    assert "D:" not in repr(err) and "private" not in repr(err) and err.private_detail.startswith("D:")
    unsafe = AutomationError("ROOT_MISSING", "bad detail with path /x")                     # 安全でない detail は code に置換
    assert unsafe.detail == "UNSAFE_DETAIL" and "/x" not in str(unsafe) and "/x" not in repr(unsafe)
    assert AutomationError("not a code").code == "SCHEMA_INVALID"
    diag = Diagnostic("SOURCE_STALE", private_detail="private text")
    assert diag.to_public() == "SOURCE_STALE" and "private" not in repr(diag) and "private" not in str(diag)
    assert Diagnostic("SOURCE_STALE", private_detail="a") == Diagnostic("SOURCE_STALE", private_detail="b")


# ================================================================ schedule model


def test_schedule_canonical_json_is_field_order_independent_and_digest_is_recomputable() -> None:
    s = schedule()
    text = s.to_json()
    data = json.loads(text)
    shuffled = dict(reversed(list(data.items())))
    shuffled["slots"] = [dict(reversed(list(x.items()))) for x in shuffled["slots"]]
    rebuilt = AutomationSchedule.from_dict(shuffled)
    assert rebuilt == s and rebuilt.to_json() == text and canonical_json(shuffled) == text
    assert data["content_digest"] == s.content_digest and len(s.content_digest) == 64
    assert data["schema_version"] == SCHEDULE_SCHEMA_VERSION and data["timezone"] == TIMEZONE_V1
    assert set(data) == {"schema_version", "schedule_id", "version", "timezone", "enabled", "slots", "holiday_calendar_ref",
                         "created_at", "supersedes", "content_digest"}
    assert set(data["slots"][0]) == {"slot_id", "local_time", "weekday_mask", "late_window_seconds",
                                     "readiness_on_non_business_day", "enabled"}
    assert schedule(version=2).content_digest != s.content_digest                          # 内容が変われば digest も
    assert schedule(supersedes=s.content_digest).content_digest != s.content_digest
    assert s.slot("slot-a") is not None and s.slot("missing") is None


def test_schedule_unknown_fields_missing_fields_wrong_types_and_digest_mismatch_fail_closed() -> None:
    data = schedule().to_dict()
    for mutate, detail in ((lambda d: d.update(extra=1), "SCHEDULE_UNKNOWN_FIELD"),
                           (lambda d: d.pop("enabled"), "SCHEDULE_MISSING_FIELD"),
                           (lambda d: d["slots"][0].update(cron="* * * * *"), "SLOT_UNKNOWN_FIELD"),
                           (lambda d: d["holiday_calendar_ref"].update(path="x"), "CALENDAR_REF_UNKNOWN_FIELD"),
                           (lambda d: d.update(enabled="yes"), "SCHEDULE_ENABLED_NOT_BOOL"),
                           (lambda d: d.update(version=0), "SCHEDULE_VERSION_RANGE"),
                           (lambda d: d.update(schedule_id="Bad Id"), "SCHEDULE_ID"),
                           (lambda d: d.update(created_at="2026-01-01T09:00:00+09:00"), "CREATED_AT_NOT_CANONICAL"),
                           (lambda d: d.update(schema_version="other"), "SCHEDULE_SCHEMA_VERSION"),
                           (lambda d: d.update(content_digest="0" * 64), "SCHEDULE_DIGEST_MISMATCH"),
                           (lambda d: d.update(slots=[]), "SCHEDULE_SLOTS"),
                           (lambda d: d["slots"][0].update(local_time="7:30"), "SLOT_LOCAL_TIME"),
                           (lambda d: d["slots"][0].update(local_time="24:00"), "SLOT_LOCAL_TIME"),
                           (lambda d: d["slots"][0].update(weekday_mask=[]), "SLOT_WEEKDAY_MASK"),
                           (lambda d: d["slots"][0].update(weekday_mask=["FRI", "MON"]), "SLOT_WEEKDAY_MASK_ORDER"),
                           (lambda d: d["slots"][0].update(weekday_mask=["MON", "MON"]), "SLOT_WEEKDAY_MASK"),
                           (lambda d: d["slots"][0].update(late_window_seconds=86400), "SLOT_LATE_WINDOW_RANGE"),
                           (lambda d: d["slots"][0].update(late_window_seconds=True), "SLOT_LATE_WINDOW_RANGE"),
                           (lambda d: d["slots"][0].update(readiness_on_non_business_day=None), "SLOT_READINESS_NOT_BOOL")):
        broken = json.loads(json.dumps(data))
        mutate(broken)
        with pytest.raises(AutomationError) as e:
            AutomationSchedule.from_dict(broken)
        assert e.value.code == "SCHEMA_INVALID" and e.value.detail == detail, detail
    with pytest.raises(AutomationError) as e:                                                # 重複の slot_id ・順
        schedule(slots=(slots()[0], slots()[0]))
    assert e.value.detail == "SLOT_ID_DUPLICATE"
    with pytest.raises(AutomationError) as e:
        schedule(slots=(slots()[1], slots()[0]))
    assert e.value.detail == "SLOT_ORDER"
    with pytest.raises(FrozenInstanceError):
        schedule().enabled = False  # type: ignore[misc]


def test_schedule_timezone_is_asia_tokyo_only_with_no_implicit_default() -> None:
    for tz in ("UTC", "Asia/Osaka", "JST", "", "+09:00", "America/New_York"):
        with pytest.raises(AutomationError) as e:
            schedule(timezone=tz)
        assert e.value.detail == "TIMEZONE_NOT_SUPPORTED", tz
    data = schedule().to_dict()
    del data["timezone"]
    with pytest.raises(AutomationError) as e:
        AutomationSchedule.from_dict(data)
    assert e.value.detail == "SCHEDULE_MISSING_FIELD"                                       # 暗黙の timezone は無い
    assert TOKYO.utcoffset(None) == timedelta(hours=9) and TOKYO.tzname(None) == TIMEZONE_V1


def test_holiday_calendar_is_canonical_and_its_reference_must_match_the_schedule() -> None:
    c = calendar()
    ref = c.reference()
    assert isinstance(ref, HolidayCalendarReference) and ref.content_digest == c.content_digest
    assert HolidayCalendar.from_dict(json.loads(c.to_json())) == c
    assert c.is_holiday(date(2026, 1, 12)) and not c.is_business_day(date(2026, 1, 12))
    assert not c.is_business_day(date(2026, 1, 10)) and c.is_business_day(date(2026, 1, 9))   # 土 ・金
    assert c.last_business_day_on_or_before(date(2026, 1, 12)) == date(2026, 1, 9)
    assert c.last_business_day_on_or_before(date(2026, 1, 11)) == date(2026, 1, 9)
    for dates, detail in (((HOLIDAY, HOLIDAY), "CALENDAR_DATES_ORDER"), (("2026-01-13", HOLIDAY), "CALENDAR_DATES_ORDER"),
                          (("2026/01/12",), "SCHEMA_INVALID")):
        with pytest.raises(AutomationError) as e:
            HolidayCalendar(calendar_id="ops-cal", version=1, dates=dates)
        assert e.value.code == "SCHEMA_INVALID"
    data = c.to_dict()
    data["dates"] = []
    with pytest.raises(AutomationError) as e:
        HolidayCalendar.from_dict(data)
    assert e.value.detail == "CALENDAR_DIGEST_MISMATCH"
    assert HolidayCalendar(calendar_id="ops-cal", version=2, dates=(HOLIDAY,)).reference() != ref


# ================================================================ planning


def test_planning_inside_the_window_yields_a_planned_run_whose_dates_come_from_scheduled_for_only() -> None:
    s = schedule()
    planned = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 7, 45))   # 月
    assert isinstance(planned, PlannedRun)
    assert planned.scheduled_for == tokyo(2026, 1, 5, 7, 30) and planned.as_of_date == date(2026, 1, 5)
    assert planned.session_date == date(2026, 1, 5) and planned.attempt == 1 and planned.operator == "scheduler"
    assert planned.schedule_digest == s.content_digest and planned.timezone == TIMEZONE_V1 and not planned.readiness_only
    same = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 8, 29, 59))
    assert same == planned                                                                   # 窓の中の時計の違いは結果を変えない
    as_utc = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=datetime(2026, 1, 4, 22, 45, tzinfo=UTC))
    assert as_utc == planned                                                                 # UTC で渡しても同じ
    d = planned.to_dict()
    assert d["scheduled_for"] == "2026-01-04T22:30:00Z" and d["scheduled_for_local"] == "2026-01-05T07:30:00+09:00"
    assert d["outcome"] == "PLANNED" and d["as_of_date"] == "2026-01-05"


def test_planning_late_window_boundaries_are_inclusive_and_outside_is_an_explicit_non_run() -> None:
    s = schedule()
    at_start = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 7, 30, 0))
    at_end = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 8, 30, 0))
    assert isinstance(at_start, PlannedRun) and isinstance(at_end, PlannedRun)
    before = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 7, 29, 59))
    after = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 8, 30, 1))
    for outcome in (before, after):
        assert isinstance(outcome, NonRun) and outcome.outcome == "OUTSIDE_WINDOW" and outcome.detail == "OUTSIDE_WINDOW"
        assert outcome.scheduled_for == tokyo(2026, 1, 5, 7, 30) and outcome.to_dict()["outcome"] == "OUTSIDE_WINDOW"
    zero = replace(slots()[2], enabled=True)                                                 # late_window 0: 瞬間だけ
    s0 = schedule(slots=(slots()[0], slots()[1], zero))
    assert isinstance(plan_run(s0, calendar(), slot_id="slot-c", selection_clock_at=tokyo(2026, 1, 5, 12, 0)), PlannedRun)
    assert plan_run(s0, calendar(), slot_id="slot-c", selection_clock_at=tokyo(2026, 1, 5, 12, 0, 1)).outcome == "OUTSIDE_WINDOW"


def test_planning_a_window_crossing_midnight_selects_the_previous_local_day_instance() -> None:
    s = schedule()
    planned = plan_run(s, calendar(), slot_id="slot-b", selection_clock_at=tokyo(2026, 1, 6, 0, 45))   # 火 の 0:45
    assert isinstance(planned, PlannedRun) and planned.scheduled_for == tokyo(2026, 1, 5, 23, 30)
    assert planned.as_of_date == date(2026, 1, 5) and planned.session_date == date(2026, 1, 5)     # 日付は scheduled_for から


def test_planning_weekend_holiday_and_readiness_only_semantics() -> None:
    s = schedule()
    weekend = plan_run(s, calendar(), slot_id="slot-b", selection_clock_at=tokyo(2026, 1, 10, 23, 40))   # 土
    assert isinstance(weekend, PlannedRun) and weekend.readiness_only
    assert weekend.as_of_date == date(2026, 1, 10) and weekend.session_date == date(2026, 1, 9)
    holiday = plan_run(s, calendar(), slot_id="slot-b", selection_clock_at=tokyo(2026, 1, 12, 23, 40))   # 休日の月
    assert isinstance(holiday, PlannedRun) and holiday.readiness_only and holiday.session_date == date(2026, 1, 9)
    strict_holiday = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 12, 7, 40))
    assert isinstance(strict_holiday, NonRun) and (strict_holiday.outcome, strict_holiday.detail) == ("NON_BUSINESS_DAY", "HOLIDAY")
    saturday_a = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 10, 7, 40))  # mask 外の土
    assert (saturday_a.outcome, saturday_a.detail) == ("OUTSIDE_WINDOW", "WEEKDAY_NOT_IN_MASK")
    all_days = replace(slots()[0], weekday_mask=("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"))
    s2 = schedule(slots=(all_days, slots()[1], slots()[2]))
    saturday = plan_run(s2, calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 10, 7, 40))
    assert (saturday.outcome, saturday.detail) == ("NON_BUSINESS_DAY", "WEEKEND")


def test_planning_missing_or_mismatched_calendar_and_disabled_schedule_or_slot_fail_closed() -> None:
    s = schedule()
    clock = tokyo(2026, 1, 5, 7, 45)
    missing = plan_run(s, None, slot_id="slot-a", selection_clock_at=clock)
    assert (missing.outcome, missing.detail) == ("CALENDAR_UNAVAILABLE", "CALENDAR_MISSING")
    other = HolidayCalendar(calendar_id="ops-cal", version=2, dates=(HOLIDAY,))
    mismatch = plan_run(s, other, slot_id="slot-a", selection_clock_at=clock)
    assert (mismatch.outcome, mismatch.detail) == ("CALENDAR_UNAVAILABLE", "CALENDAR_REF_MISMATCH")
    assert plan_run(schedule(enabled=False), calendar(), slot_id="slot-a", selection_clock_at=clock).detail == "SCHEDULE_DISABLED"
    disabled_slot = plan_run(s, calendar(), slot_id="slot-c", selection_clock_at=tokyo(2026, 1, 5, 12, 0))
    assert (disabled_slot.outcome, disabled_slot.detail) == ("DISABLED", "SLOT_DISABLED")
    assert plan_run(s, calendar(), slot_id="slot-x", selection_clock_at=clock).outcome == "SLOT_NOT_FOUND"
    assert plan_run(s, None, slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 3, 0)).outcome == "OUTSIDE_WINDOW"   # 窓が先


def test_planning_requires_an_explicit_aware_selection_clock_and_never_reads_the_wall_clock() -> None:
    with pytest.raises(AutomationError) as e:
        plan_run(schedule(), calendar(), slot_id="slot-a", selection_clock_at=datetime(2026, 1, 5, 7, 45))
    assert e.value.code == "SELECTION_CLOCK_NOT_AWARE"
    with pytest.raises(TypeError):
        plan_run(schedule(), calendar(), slot_id="slot-a")  # type: ignore[call-arg]
    with pytest.raises(AutomationError):
        plan_run(schedule(), calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 7, 45), operator="robot")


def test_planning_already_succeeded_and_attempt_numbering_come_only_from_supplied_prior_runs() -> None:
    s = schedule()
    clock = tokyo(2026, 1, 5, 7, 45)
    first = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=clock)
    prior_failed = PriorRunSummary("ops-daily", "slot-a", first.scheduled_for, 1, RunState.FAILED)
    retry = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=clock, prior_runs=(prior_failed,))
    assert isinstance(retry, PlannedRun) and retry.attempt == 2 and retry.scheduled_for == first.scheduled_for
    prior_ok = PriorRunSummary("ops-daily", "slot-a", first.scheduled_for, 2, RunState.SUCCEEDED)
    done = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=clock, prior_runs=(prior_failed, prior_ok))
    assert isinstance(done, NonRun) and done.outcome == "ALREADY_SUCCEEDED"
    unrelated = PriorRunSummary("ops-daily", "slot-a", tokyo(2026, 1, 2, 7, 30), 1, RunState.SUCCEEDED)
    assert plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=clock, prior_runs=(unrelated,)).attempt == 1
    with pytest.raises(AutomationError) as e:                                                # 古い attempt の再利用は拒む
        plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=clock, prior_runs=(prior_failed,), attempt=1)
    assert e.value.detail == "ATTEMPT_NOT_NEW"
    human = plan_run(s, calendar(), slot_id="slot-a", selection_clock_at=clock, operator="human", attempt=5)
    assert human.attempt == 5 and human.operator == "human"


# ================================================================ run identity


def test_run_id_is_deterministic_domain_separated_and_excludes_telemetry_status_and_paths() -> None:
    planned = plan_run(schedule(), calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 7, 45))
    run = AutomationRun.from_planned(planned, ANCHOR)
    identity = run.identity
    expected = domain_digest(RUN_ID_DOMAIN, {"schedule_id": "ops-daily", "slot_id": "slot-a",
                                             "scheduled_for": "2026-01-04T22:30:00Z", "runtime_anchor": ANCHOR, "attempt": 1})
    assert run.run_id == expected == identity.run_id and len(run.run_id) == 64
    assert RunIdentity("ops-daily", "slot-a", datetime(2026, 1, 4, 22, 30, tzinfo=UTC), ANCHOR, 1).run_id == expected
    assert replace(identity, attempt=2).run_id != expected
    assert replace(identity, runtime_anchor=OTHER_ANCHOR).run_id != expected
    assert replace(identity, slot_id="slot-b").run_id != expected
    assert replace(identity, scheduled_for=tokyo(2026, 1, 6, 7, 30)).run_id != expected
    assert set(identity.content()) == {"schedule_id", "slot_id", "scheduled_for", "runtime_anchor", "attempt"}
    later = plan_run(schedule(), calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 8, 20))
    assert AutomationRun.from_planned(later, ANCHOR).run_id == expected                       # selection_clock は identity 外
    assert AutomationRun.from_planned(planned, ANCHOR, retry_of="c" * 64 if False else None).run_id == expected
    assert run.to_dict()["run_id"] == expected and "started_at" not in run.to_dict() and "status" not in run.to_dict()
    assert domain_digest("other.domain", identity.content()) != expected


def test_run_lineage_is_metadata_and_validated_but_never_part_of_identity() -> None:
    planned = plan_run(schedule(), calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 7, 45))
    first = AutomationRun.from_planned(planned, ANCHOR)
    retry_plan = plan_run(schedule(), calendar(), slot_id="slot-a", selection_clock_at=tokyo(2026, 1, 5, 7, 45),
                          prior_runs=(PriorRunSummary("ops-daily", "slot-a", planned.scheduled_for, 1, RunState.CRASHED),))
    retry = AutomationRun.from_planned(retry_plan, ANCHOR, retry_of=first.run_id)
    assert retry.retry_of == first.run_id and retry.run_id == AutomationRun.from_planned(retry_plan, ANCHOR).run_id
    assert retry.run_id != first.run_id and retry.identity.attempt == 2
    with pytest.raises(AutomationError) as e:
        AutomationRun.from_planned(planned, ANCHOR, retry_of=first.run_id)                   # attempt 1 は retry ではない
    assert e.value.detail == "RETRY_ATTEMPT"
    with pytest.raises(AutomationError) as e:
        AutomationRun.from_planned(planned, ANCHOR, supersedes=first.run_id)
    assert e.value.detail == "SELF_LINK"
    with pytest.raises(AutomationError):
        AutomationRun.from_planned(planned, "not-an-anchor")
    with pytest.raises(AutomationError):
        AutomationRun.from_planned(planned, ANCHOR, supersedes="short")
    with pytest.raises(FrozenInstanceError):
        first.operator = "human"  # type: ignore[misc]


# ================================================================ state machine


def test_state_machine_legal_transitions_are_exactly_the_table() -> None:
    legal = {(a, b) for a, targets in TRANSITIONS.items() for b in targets}
    assert legal == {(RunState.PLANNED, RunState.RUNNING), (RunState.PLANNED, RunState.SKIPPED),
                     (RunState.PLANNED, RunState.CANCELLED), (RunState.PLANNED, RunState.CRASHED),
                     (RunState.RUNNING, RunState.SUCCEEDED), (RunState.RUNNING, RunState.FAILED),
                     (RunState.RUNNING, RunState.CANCELLED), (RunState.RUNNING, RunState.CRASHED),
                     (RunState.RUNNING, RunState.ORPHANED_FINALIZATION)}
    for a, b in legal:
        assert transition(a, b) is b and can_transition(a, b)
    assert TERMINAL_STATES == {RunState.SUCCEEDED, RunState.FAILED, RunState.SKIPPED, RunState.CANCELLED, RunState.CRASHED,
                               RunState.ORPHANED_FINALIZATION}
    assert set(RunState) == TERMINAL_STATES | {RunState.PLANNED, RunState.RUNNING}
    for state in RunState:
        assert is_terminal(state) == (state in TERMINAL_STATES)


def test_state_machine_every_illegal_transition_raises_a_deterministic_domain_error() -> None:
    legal = {(a, b) for a, targets in TRANSITIONS.items() for b in targets}
    for a in RunState:
        for b in RunState:
            if (a, b) in legal:
                continue
            with pytest.raises(IllegalTransition) as e:
                transition(a, b)
            assert isinstance(e.value, AutomationError) and e.value.code == "ILLEGAL_TRANSITION"
            assert e.value.detail == f"{a.value}_TO_{b.value}" and not can_transition(a, b)
    for a, b in ((RunState.FAILED, RunState.SUCCEEDED), (RunState.CRASHED, RunState.SUCCEEDED),
                 (RunState.SUCCEEDED, RunState.RUNNING), (RunState.ORPHANED_FINALIZATION, RunState.SUCCEEDED),
                 (RunState.PLANNED, RunState.SUCCEEDED), (RunState.RUNNING, RunState.PLANNED)):
        with pytest.raises(IllegalTransition):
            transition(a, b)
    with pytest.raises(AutomationError) as e:
        transition("PLANNED", "RUNNNING")
    assert e.value.detail == "RUN_STATE"
    assert transition("PLANNED", "RUNNING") is RunState.RUNNING


# ================================================================ step results


def test_step_results_are_ordered_immutable_and_carry_only_codes_and_digests() -> None:
    assert STEP_ORDER == ("PRECONDITIONS", "ROOT_MANIFESTS", "P11_MODEL_SNAPSHOT", "SERVER_READINESS", "FINALIZATION")
    ok = AutomationStepResult("PRECONDITIONS", "OK", "1" * 64, "COMPLETE", None)
    failed = AutomationStepResult("ROOT_MANIFESTS", "FAILED", None, "PARTIAL", "ROOT_MISSING")
    skipped = AutomationStepResult("P11_MODEL_SNAPSHOT", "SKIPPED", None, "NONE", None)
    assert validate_step_results((ok, failed, skipped)) == (ok, failed, skipped)
    assert set(ok.to_dict()) == {"step_code", "status", "artifact_digest", "completeness_code", "failure_code"}
    assert AutomationStepResult.from_dict(ok.to_dict()) == ok
    for args, detail in ((("OTHER", "OK", None, "COMPLETE", None), "STEP_CODE"),
                         (("PRECONDITIONS", "DONE", None, "COMPLETE", None), "STEP_STATUS"),
                         (("PRECONDITIONS", "OK", "abc", "COMPLETE", None), "STEP_ARTIFACT_DIGEST"),
                         (("PRECONDITIONS", "OK", None, "FULL", None), "STEP_COMPLETENESS"),
                         (("PRECONDITIONS", "FAILED", None, "NONE", "bad code"), "STEP_FAILURE_CODE"),
                         (("PRECONDITIONS", "OK", None, "COMPLETE", "ROOT_MISSING"), "STEP_OK_WITH_FAILURE"),
                         (("PRECONDITIONS", "FAILED", None, "NONE", None), "STEP_FAILED_WITHOUT_CODE"),
                         (("PRECONDITIONS", "FAILED", "1" * 64, "NONE", "ROOT_MISSING"), "STEP_ARTIFACT_WITHOUT_OK"),
                         (("PRECONDITIONS", "SKIPPED", None, "PARTIAL", None), "STEP_SKIPPED_COMPLETENESS")):
        with pytest.raises(AutomationError) as e:
            AutomationStepResult(*args)
        assert e.value.detail == detail, detail
    with pytest.raises(AutomationError) as e:
        validate_step_results((failed, ok))                                                  # 順の逆転
    assert e.value.detail == "STEP_ORDER"
    with pytest.raises(AutomationError) as e:
        validate_step_results((ok, ok))                                                      # 重複
    assert e.value.detail == "STEP_ORDER"
    with pytest.raises(AutomationError) as e:
        validate_step_results((failed, AutomationStepResult("FINALIZATION", "OK", None, "COMPLETE", None)))
    assert e.value.detail == "STEP_AFTER_FAILURE"
    with pytest.raises(AutomationError) as e:
        AutomationStepResult.from_dict({**ok.to_dict(), "path": "x"})
    assert e.value.detail == "STEP_UNKNOWN_FIELD"
    with pytest.raises(FrozenInstanceError):
        ok.status = "FAILED"  # type: ignore[misc]
