"""P12-A1 — hash 鎖の ledger の record ・鎖の検証 ・status の projection ・privacy の test（全て合成の値 ・file は書かない）。"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from src.intelligence.automation.failure_codes import AutomationError
from src.intelligence.automation.holiday_calendar import HolidayCalendar
from src.intelligence.automation.ledger_model import (GENESIS_DIGEST, LEDGER_RECORD_VERSION, LedgerError, LedgerRecord,
                                                      make_record, parse_records, verify_chain)
from src.intelligence.automation.run_identity import AutomationRun
from src.intelligence.automation.run_planning import PriorRunSummary, plan_run
from src.intelligence.automation.run_state import IllegalTransition, RunState
from src.intelligence.automation.schedule_model import TIMEZONE_V1, TOKYO, AutomationSchedule, ScheduleSlot
from src.intelligence.automation.status_projection import STATUS_SCHEMA_VERSION, StatusProjection, project_status
from src.intelligence.automation.step_result import STEP_ORDER, AutomationStepResult

ANCHOR = "a" * 40
OTHER_ANCHOR = "b" * 40
UTC = timezone.utc
T0 = "2026-01-04T22:31:00Z"
T1 = "2026-01-04T22:32:00Z"
T2 = "2026-01-04T22:40:00Z"
PRIVATE_SHAPES = ("D:\\", "/home/", "\\\\", "Traceback", ".json", "p9wat_", "p10prf_", "human:", "api", "key", "token")


def calendar() -> HolidayCalendar:
    return HolidayCalendar(calendar_id="ops-cal", version=1, dates=("2026-01-12",))


def schedule() -> AutomationSchedule:
    slot = ScheduleSlot(slot_id="slot-a", local_time="07:30", weekday_mask=("MON", "TUE", "WED", "THU", "FRI"),
                        late_window_seconds=3600, readiness_on_non_business_day=False, enabled=True)
    return AutomationSchedule(schedule_id="ops-daily", version=1, timezone=TIMEZONE_V1, enabled=True, slots=(slot,),
                              holiday_calendar_ref=calendar().reference(), created_at="2026-01-01T00:00:00Z")


def run(day: int = 5, attempt_after=()) -> AutomationRun:
    clock = datetime(2026, 1, day, 7, 45, tzinfo=TOKYO)
    planned = plan_run(schedule(), calendar(), slot_id="slot-a", selection_clock_at=clock, prior_runs=attempt_after)
    return AutomationRun.from_planned(planned, ANCHOR)


def ok_steps() -> tuple:
    return tuple(AutomationStepResult(code, "OK", str(i) * 64, "COMPLETE", None) for i, code in enumerate(STEP_ORDER, 1))


def chain_for(r: AutomationRun, final: RunState, failure_code=None, steps=(), artifacts=(), start=None) -> list:
    """PLANNED → RUNNING → final の 3 record（start は前の鎖の最後の record）。"""
    r0 = make_record(start, r, transition_to=RunState.PLANNED, recorded_at=T0)
    r1 = make_record(r0, r, transition_from=RunState.PLANNED, transition_to=RunState.RUNNING, recorded_at=T1)
    r2 = make_record(r1, r, transition_from=RunState.RUNNING, transition_to=final, recorded_at=T2,
                     failure_code=failure_code, step_results=steps, artifact_digests=artifacts)
    return [r0, r1, r2]


# ================================================================ record ・鎖


def test_a_valid_chain_verifies_and_records_are_canonical_hash_addressed_and_recomputable() -> None:
    records = chain_for(run(), RunState.SUCCEEDED, steps=ok_steps(), artifacts=("f" * 64, "e" * 64))
    summary = verify_chain(records)
    assert summary.record_count == 3 and summary.head_digest == records[2].record_digest
    assert summary.run_states == {run().run_id: RunState.SUCCEEDED}
    assert records[0].previous_record_digest == GENESIS_DIGEST and records[0].sequence == 0
    assert records[1].previous_record_digest == records[0].record_digest and records[2].sequence == 2
    assert records[2].artifact_digests == ("e" * 64, "f" * 64) and records[2].status is RunState.SUCCEEDED
    for record in records:
        data = json.loads(record.to_json())
        assert data["record_version"] == LEDGER_RECORD_VERSION and data["status"] == data["transition_to"]
        assert LedgerRecord.from_dict(data) == record and LedgerRecord.from_dict(data).record_digest == record.record_digest
        assert set(data) == {"record_version", "sequence", "previous_record_digest", "record_digest", "run_id", "schedule_id",
                             "slot_id", "scheduled_for", "runtime_anchor", "attempt", "operator", "transition_from",
                             "transition_to", "status", "failure_code", "step_results", "artifact_digests", "recorded_at"}
    assert parse_records([r.to_json() for r in records]) == tuple(records)
    assert verify_chain([]).record_count == 0 and verify_chain([]).head_digest == GENESIS_DIGEST
    with pytest.raises(FrozenInstanceError):
        records[0].sequence = 5  # type: ignore[misc]
    assert replace(records[2], recorded_at="2026-01-04T22:41:00Z").record_digest != records[2].record_digest
    assert replace(records[2], recorded_at="2026-01-04T22:41:00Z").run_id == records[2].run_id  # telemetry は identity 外


def test_mutation_of_any_record_field_breaks_the_chain() -> None:
    records = chain_for(run(), RunState.SUCCEEDED, steps=ok_steps())
    for index, mutated in ((1, replace(records[1], recorded_at="2026-01-04T22:33:00Z")),
                           (1, replace(records[1], operator="human")),
                           (1, replace(records[1], step_results=ok_steps()[:1])),
                           (0, replace(records[0], attempt=2))):
        broken = list(records)
        broken[index] = mutated
        with pytest.raises(LedgerError) as e:
            verify_chain(broken)
        assert (e.value.code, e.value.detail, e.value.sequence) == ("LEDGER_INVALID", "CHAIN_BREAK", index + 1)
    tail = list(records)                                                                  # 最後の record の改変: 鎖の次が無い
    tail[2] = replace(records[2], step_results=ok_steps()[:4])
    assert verify_chain(tail).head_digest != verify_chain(records).head_digest             # head の digest が変わる（外で照合）
    line = records[2].to_json().replace('"transition_to":"SUCCEEDED"', '"transition_to":"FAILED"')
    with pytest.raises(AutomationError):                                                   # 直列化の改変は digest ・規則で止まる
        parse_records([records[0].to_json(), records[1].to_json(), line])
    tampered = json.loads(records[1].to_json())
    tampered["recorded_at"] = "2026-01-04T22:33:00Z"
    with pytest.raises(LedgerError) as e:
        LedgerRecord.from_dict(tampered)
    assert e.value.detail == "RECORD_DIGEST_MISMATCH" and e.value.sequence == 1


def test_deletion_insertion_and_reordering_are_detected() -> None:
    first = chain_for(run(5), RunState.FAILED, failure_code="SOURCE_STALE")
    second = chain_for(run(6), RunState.SUCCEEDED, steps=ok_steps(), start=first[2])
    records = first + second
    assert verify_chain(records).record_count == 6
    with pytest.raises(LedgerError) as e:                                                 # 削除（途中）
        verify_chain(records[:2] + records[3:])
    assert (e.value.detail, e.value.sequence) == ("SEQUENCE_BREAK", 2)
    with pytest.raises(LedgerError) as e:                                                 # 並べ替え
        verify_chain([records[0], records[2], records[1]] + records[3:])
    assert (e.value.detail, e.value.sequence) == ("SEQUENCE_BREAK", 1)
    foreign = make_record(records[1], run(5), transition_from=RunState.RUNNING, transition_to=RunState.CANCELLED,
                          recorded_at=T2, failure_code="CANCELLED")
    with pytest.raises(LedgerError) as e:                                                 # 差し替え（record 2 を別の record に）
        verify_chain(records[:2] + [foreign] + records[3:])
    assert (e.value.detail, e.value.sequence) == ("CHAIN_BREAK", 3)
    inserted = make_record(records[2], run(7), transition_to=RunState.PLANNED, recorded_at=T2)
    with pytest.raises(LedgerError) as e:                                                 # 挿入（後続の sequence が飛ぶ）
        verify_chain(records[:3] + [inserted] + records[3:])
    assert (e.value.detail, e.value.sequence) == ("SEQUENCE_BREAK", 4)
    truncated = records[:5]                                                               # 末尾の削除は鎖だけでは見えない
    assert verify_chain(truncated).head_digest == records[4].record_digest != records[5].record_digest
    with pytest.raises(LedgerError) as e:
        verify_chain(["not a record"])  # type: ignore[list-item]
    assert e.value.detail == "RECORD_TYPE"


def test_chain_verification_enforces_the_state_machine_per_run() -> None:
    r = run()
    r0 = make_record(None, r, transition_to=RunState.PLANNED, recorded_at=T0)
    r1 = make_record(r0, r, transition_from=RunState.PLANNED, transition_to=RunState.RUNNING, recorded_at=T1)
    r2 = make_record(r1, r, transition_from=RunState.RUNNING, transition_to=RunState.FAILED, recorded_at=T2,
                     failure_code="SOURCE_INCOMPLETE")
    with pytest.raises(IllegalTransition):                                                 # FAILED → SUCCEEDED は組めない
        make_record(r2, r, transition_from=RunState.FAILED, transition_to=RunState.SUCCEEDED, recorded_at=T2)
    with pytest.raises(IllegalTransition):
        make_record(r0, r, transition_from=RunState.PLANNED, transition_to=RunState.SUCCEEDED, recorded_at=T1)
    reopened = make_record(r2, r, transition_to=RunState.PLANNED, recorded_at=T2)          # 終端の後の record
    with pytest.raises(LedgerError) as e:
        verify_chain([r0, r1, r2, reopened])
    assert (e.value.detail, e.value.sequence) == ("RUN_AFTER_TERMINAL", 3)
    skipped_open = make_record(None, r, transition_from=RunState.PLANNED, transition_to=RunState.RUNNING, recorded_at=T0)
    with pytest.raises(LedgerError) as e:                                                 # 開かれていない run の遷移
        verify_chain([skipped_open])
    assert e.value.detail == "RUN_NOT_OPENED"
    r1b = make_record(r0, r, transition_from=RunState.RUNNING, transition_to=RunState.FAILED, recorded_at=T1,
                      failure_code="INTERRUPTED")
    with pytest.raises(LedgerError) as e:                                                 # from が前の状態と違う
        verify_chain([r0, r1b])
    assert e.value.detail == "TRANSITION_FROM_MISMATCH"
    with pytest.raises(AutomationError) as e:
        make_record(None, r, transition_from=None, transition_to=RunState.RUNNING, recorded_at=T0)
    assert e.value.detail == "RECORD_FIRST_NOT_PLANNED"
    with pytest.raises(AutomationError) as e:
        make_record(r1, r, transition_from=RunState.RUNNING, transition_to=RunState.FAILED, recorded_at=T2)
    assert e.value.detail == "RECORD_TERMINAL_WITHOUT_CODE"
    with pytest.raises(AutomationError) as e:
        make_record(r1, r, transition_from=RunState.RUNNING, transition_to=RunState.SUCCEEDED, recorded_at=T2,
                    failure_code="SOURCE_STALE")
    assert e.value.detail == "RECORD_CODE_WITHOUT_FAILURE"
    retry = run(5, attempt_after=(PriorRunSummary("ops-daily", "slot-a", r.identity.scheduled_for, 1, RunState.FAILED),))
    assert retry.run_id != r.run_id and retry.identity.attempt == 2                        # retry は新しい run
    r3 = make_record(r2, retry, transition_to=RunState.PLANNED, recorded_at=T2)
    assert verify_chain([r0, r1, r2, r3]).run_states == {r.run_id: RunState.FAILED, retry.run_id: RunState.PLANNED}


def test_malformed_records_fail_closed() -> None:
    good = chain_for(run(), RunState.SUCCEEDED, steps=ok_steps())[0]
    data = good.to_dict()
    for mutate, detail in ((lambda d: d.update(note="x"), "RECORD_UNKNOWN_FIELD"),
                           (lambda d: d.pop("operator"), "RECORD_MISSING_FIELD"),
                           (lambda d: d.update(status="RUNNING"), "RECORD_STATUS_MISMATCH"),
                           (lambda d: d.update(step_results={}), "RECORD_LISTS"),
                           (lambda d: d.update(transition_to="DONE", status="DONE"), "RUN_STATE"),
                           (lambda d: d.update(record_version="other"), "RECORD_VERSION"),
                           (lambda d: d.update(sequence=-1), "RECORD_SEQUENCE"),
                           (lambda d: d.update(recorded_at="2026-01-04 22:31"), "SCHEMA_INVALID"),
                           (lambda d: d.update(runtime_anchor="abc"), "RECORD_ANCHOR"),
                           (lambda d: d.update(operator="robot"), "RECORD_OPERATOR"),
                           (lambda d: d.update(artifact_digests=["x"]), "RECORD_ARTIFACTS")):
        broken = json.loads(json.dumps(data))
        mutate(broken)
        with pytest.raises(AutomationError) as e:
            LedgerRecord.from_dict(broken)
        assert e.value.detail == detail or e.value.code == detail, detail
    with pytest.raises(LedgerError) as e:
        parse_records(["{not json"])
    assert e.value.detail == "RECORD_NOT_JSON"
    with pytest.raises(LedgerError) as e:
        parse_records([json.dumps(data, indent=1)])                                       # 正準でない形
    assert e.value.detail == "RECORD_NOT_CANONICAL"
    with pytest.raises(AutomationError) as e:
        make_record(None, "run", transition_to=RunState.PLANNED, recorded_at=T0)  # type: ignore[arg-type]
    assert e.value.detail == "RUN_TYPE"
    with pytest.raises(AutomationError):
        make_record(None, run(), transition_to=RunState.PLANNED, recorded_at="2026-01-04T22:31:00.5Z")


# ================================================================ status projection


def test_status_projection_empty_running_success_and_failure() -> None:
    empty = project_status([], runtime_anchor=ANCHOR, schedule_id="ops-daily")
    assert isinstance(empty, StatusProjection) and empty.health_code == "NO_RUNS" and empty.record_count == 0
    assert empty.last_successful_run is None and empty.active_run is None and empty.staleness_class == "UNKNOWN"
    assert empty.source_completeness == {step: "NONE" for step in STEP_ORDER} and empty.head_digest == GENESIS_DIGEST
    assert empty.to_dict()["schema_version"] == STATUS_SCHEMA_VERSION
    records = chain_for(run(), RunState.SUCCEEDED, steps=ok_steps())
    running = project_status(records[:2], runtime_anchor=ANCHOR, schedule_id="ops-daily")
    assert running.health_code == "RUNNING" and running.active_run.state is RunState.RUNNING
    assert running.active_run.run_id == run().run_id and running.last_successful_run is None
    ok = project_status(records, runtime_anchor=ANCHOR, schedule_id="ops-daily",
                        as_of=datetime(2026, 1, 5, 12, 0, tzinfo=UTC))
    assert ok.health_code == "OK" and ok.active_run is None and ok.last_failure_code is None
    assert ok.last_successful_run.scheduled_for == "2026-01-04T22:30:00Z" and ok.staleness_class == "FRESH"
    assert ok.source_completeness == {step: "COMPLETE" for step in STEP_ORDER}
    aging = project_status(records, runtime_anchor=ANCHOR, schedule_id="ops-daily", as_of=datetime(2026, 1, 7, 0, 0, tzinfo=UTC))
    stale = project_status(records, runtime_anchor=ANCHOR, schedule_id="ops-daily", as_of=datetime(2026, 1, 9, 0, 0, tzinfo=UTC))
    assert aging.staleness_class == "AGING" and stale.staleness_class == "STALE"
    assert project_status(records, runtime_anchor=ANCHOR, schedule_id="ops-daily").staleness_class == "UNKNOWN"  # as_of 無し
    failed = chain_for(run(6), RunState.FAILED, failure_code="SOURCE_STALE",
                       steps=(AutomationStepResult("PRECONDITIONS", "OK", "1" * 64, "COMPLETE", None),
                              AutomationStepResult("ROOT_MANIFESTS", "FAILED", None, "PARTIAL", "SOURCE_STALE")), start=records[2])
    status = project_status(records + failed, runtime_anchor=ANCHOR, schedule_id="ops-daily")
    assert status.health_code == "FAILED" and status.last_failure_code == "SOURCE_STALE"
    assert status.last_successful_run.run_id == run().run_id and status.last_terminal_run.state is RunState.FAILED
    assert status.source_completeness["ROOT_MANIFESTS"] == "COMPLETE"                     # completeness は最後の成功から


def test_status_projection_crash_orphaned_finalization_and_mismatches() -> None:
    crashed = chain_for(run(), RunState.CRASHED, failure_code="INTERRUPTED")
    assert project_status(crashed, runtime_anchor=ANCHOR, schedule_id="ops-daily").health_code == "CRASHED"
    orphaned = chain_for(run(), RunState.ORPHANED_FINALIZATION, failure_code="ORPHANED_FINALIZATION",
                         artifacts=("d" * 64,))
    status = project_status(orphaned, runtime_anchor=ANCHOR, schedule_id="ops-daily")
    assert status.health_code == "ORPHANED_FINALIZATION" and status.last_successful_run is None   # 成功と解釈しない
    assert status.last_failure_code == "ORPHANED_FINALIZATION" and status.source_completeness == {s: "NONE" for s in STEP_ORDER}
    planned_only = chain_for(run(), RunState.SUCCEEDED, steps=ok_steps())[:1]
    assert project_status(planned_only, runtime_anchor=ANCHOR, schedule_id="ops-daily").health_code == "RUNNING"
    assert project_status(crashed, runtime_anchor=OTHER_ANCHOR, schedule_id="ops-daily").health_code == "ANCHOR_MISMATCH"
    assert project_status(crashed, runtime_anchor=ANCHOR, schedule_id="other").health_code == "SCHEDULE_MISMATCH"
    with pytest.raises(AutomationError) as e:
        project_status(crashed, runtime_anchor="bad", schedule_id="ops-daily")
    assert e.value.detail == "RUNTIME_ANCHOR"
    with pytest.raises(AutomationError):
        project_status(crashed, runtime_anchor=ANCHOR, schedule_id="ops-daily", as_of=datetime(2026, 1, 5))   # naive


def test_status_projection_fails_closed_on_an_invalid_ledger() -> None:
    records = chain_for(run(), RunState.SUCCEEDED, steps=ok_steps())
    broken = [records[0], replace(records[1], operator="human"), records[2]]
    with pytest.raises(LedgerError):
        project_status(broken, runtime_anchor=ANCHOR, schedule_id="ops-daily")
    with pytest.raises(LedgerError):
        project_status([records[0], records[2]], runtime_anchor=ANCHOR, schedule_id="ops-daily")
    with pytest.raises(LedgerError):
        project_status([records[1]], runtime_anchor=ANCHOR, schedule_id="ops-daily")


# ================================================================ privacy


def test_serialized_models_errors_and_projections_carry_no_paths_exception_text_or_payloads() -> None:
    records = chain_for(run(), RunState.FAILED, failure_code="ROOT_MISSING",
                        steps=(AutomationStepResult("PRECONDITIONS", "FAILED", None, "NONE", "ROOT_MISSING"),))
    status = project_status(records, runtime_anchor=ANCHOR, schedule_id="ops-daily")
    texts = [r.to_json() for r in records] + [json.dumps(status.to_dict()), schedule().to_json(), calendar().to_json(),
                                              json.dumps(run().to_dict())]
    for text in texts:
        lowered = text.lower()
        for shape in PRIVATE_SHAPES:
            assert shape.lower() not in lowered, (shape, text[:80])
        assert "payload" not in lowered and "message" not in lowered and "exception" not in lowered
    err = AutomationError("ROOT_MISSING", "MANIFEST", private_detail="D:\\private\\root")
    for rendered in (str(err), repr(err), err.public_code):
        assert "D:\\" not in rendered and "private" not in rendered.lower()
    try:
        raise LedgerError("CHAIN_BREAK", 3)
    except AutomationError as caught:
        assert str(caught) == "LEDGER_INVALID:CHAIN_BREAK" and caught.sequence == 3
    for value in status.to_dict().values():                                               # id ・code ・瞬間 ・件数 ・入れ子の同じ形だけ
        assert isinstance(value, (str, int, dict, type(None)))
