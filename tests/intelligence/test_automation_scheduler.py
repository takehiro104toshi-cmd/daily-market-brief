"""P12-A5 — scheduled-run の解決 ・無人の方針 ・exit code ・task の定義 ・Task Scheduler の adapter ・install ／ remove ／ status ・pin の test。

Windows は要らない（adapter は InMemory の double）。合成の世界 ・tmp の git repo ・tmp の P12 root。network ・資格情報は無い。
"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.automation import ledger_commit as lc
from src.intelligence.automation import run_cli
from src.intelligence.automation import run_executor as rx
from src.intelligence.automation.calendar_authority import calendar_file, write_calendar_authority
from src.intelligence.automation.execution_request import AutomationExecutionRequest
from src.intelligence.automation.failure_codes import AutomationError
from src.intelligence.automation.head_checkpoint import HeadCheckpoint
from src.intelligence.automation.holiday_calendar import HolidayCalendar
from src.intelligence.automation.injection import RaisingInjection, raise_type
from src.intelligence.automation.ledger_store import LedgerStore
from src.intelligence.automation.operational_lock import acquire_lock, run_lock_file
from src.intelligence.automation.preconditions import PrivateRoots
from src.intelligence.automation.process_probe import ProcessProbe, StaticProbe
from src.intelligence.automation.run_state import RunState
from src.intelligence.automation.run_transaction import commit_run
from src.intelligence.automation.runtime_pin import pin_clean_head, read_runtime_pin, write_runtime_pin
from src.intelligence.automation.schedule_authority import write_schedule_authority
from src.intelligence.automation.schedule_model import TIMEZONE_V1, TOKYO, AutomationSchedule, ScheduleSlot
from src.intelligence.automation.scheduled_run import (EXIT_AUTHORITY_INVALID, EXIT_DUPLICATE_ACTIVE, EXIT_FAILED, EXIT_MISSED, EXIT_OK,
                                                       EXIT_PRECONDITION_REFUSED, EXIT_RECOVERY_REQUIRED, run_scheduled)
from src.intelligence.automation.scheduler_install import install_tasks, plan_install, remove_tasks, scheduler_status
from src.intelligence.automation.status_store import read_status, status_file
from src.intelligence.automation.task_definition import (OWNER_MARKER, TASK_NAMESPACE, SchedulerPaths, owned_task_names,
                                                         task_definitions, task_name, task_xml)
from src.intelligence.automation.task_scheduler_adapter import InMemoryTaskScheduler, TaskQuery
from tests.intelligence.test_automation_executor import build_world
from tests.intelligence.test_automation_preconditions import make_repo
from tests.intelligence.test_automation_transaction import InjectedCrash, ticking_clock
from tests.intelligence.test_personal_intelligence_executor import tree

REPO_ROOT = Path(__file__).resolve().parents[2]
HOLIDAY = "2026-07-02"                                                                     # 木（合成）
PATHS = SchedulerPaths(interpreter="C:\\compass\\venv\\Scripts\\python.exe", repo_root="C:\\compass\\repo",
                       runtime_root="C:\\compass\\repo", private_root="D:\\compass_private\\p12", p9_root="D:\\compass_private\\p9",
                       p10_root="D:\\compass_private\\p10")


def calendar() -> HolidayCalendar:
    return HolidayCalendar(calendar_id="ops-cal", version=1, dates=(HOLIDAY,))


def schedule(**overrides) -> AutomationSchedule:
    slots = (ScheduleSlot(slot_id="slot-a", local_time="15:00", weekday_mask=("MON", "TUE", "WED", "THU", "FRI"), late_window_seconds=3600,
                          readiness_on_non_business_day=False, enabled=True),
             ScheduleSlot(slot_id="slot-b", local_time="23:30", weekday_mask=("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"),
                          late_window_seconds=7200, readiness_on_non_business_day=True, enabled=True),
             ScheduleSlot(slot_id="slot-c", local_time="12:00", weekday_mask=("MON",), late_window_seconds=0,
                          readiness_on_non_business_day=False, enabled=False))
    fields = dict(schedule_id="ops-daily", version=1, timezone=TIMEZONE_V1, enabled=True, slots=slots,
                  holiday_calendar_ref=calendar().reference(), created_at="2026-01-01T00:00:00Z", supersedes=None)
    fields.update(overrides)
    return AutomationSchedule(**fields)


def tokyo(day: int, hh: int, mm: int, ss: int = 0, month: int = 7) -> datetime:
    return datetime(2026, month, day, hh, mm, ss, tzinfo=TOKYO)


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(lc, "LEDGER_LOCK_WAIT_SECONDS", 0.5)
    built = build_world(tmp_path)
    repo, head = make_repo(tmp_path / "repo")
    root = tmp_path / "p12_private_root"
    write_schedule_authority(root, schedule(), operator="human")
    write_calendar_authority(root, calendar(), operator="human")
    write_runtime_pin(root, head, operator="human", pinned_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    roots = PrivateRoots(built["p9"]["root"], built["p10"], root)
    before = (tree(built["p9"]["root"]), tree(built["p10"]))
    yield dict(roots=roots, root=root, repo=repo, head=head, tmp=tmp_path, **built)
    assert (tree(built["p9"]["root"]), tree(built["p10"])) == before


def scheduled(world, slot: str, at: datetime, **overrides):
    args = dict(repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, selection_clock_at=at, clock=ticking_clock())
    args.update(overrides)
    return run_scheduled(slot, world["roots"], **args)


def ledger(world) -> LedgerStore:
    return LedgerStore(world["root"])


def snapshot_of_root(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ================================================================ time ・window


def test_scheduled_run_at_the_exact_instant_commits_a_scheduler_run_whose_pit_comes_from_scheduled_for(world) -> None:
    outcome = scheduled(world, "slot-a", tokyo(1, 15, 0))                                  # 水 15:00 ＝ scheduled_for
    assert (outcome.kind, outcome.code, outcome.exit_code) == ("SUCCEEDED", "RUN_SUCCEEDED", EXIT_OK)
    assert outcome.scheduled_for == "2026-07-01T06:00:00Z" and outcome.transaction.status == "SUCCEEDED"
    state = ledger(world).open_verified()
    record = state.records[-1]
    assert record.operator == "scheduler" and record.attempt == 1 and record.runtime_anchor == world["head"]
    request = json.loads((world["root"] / "requests" / f"{outcome.run_id}.json").read_text())
    assert (request["as_of_date"], request["session_date"], request["readiness_only"]) == ("2026-07-01", "2026-07-01", False)
    inside = scheduled(world, "slot-a", tokyo(1, 15, 30))                                  # 窓の中の 2 回目: 同じ instance
    assert (inside.kind, inside.code, inside.exit_code) == ("SKIPPED", "ALREADY_SUCCEEDED", EXIT_OK)
    assert ledger(world).open_verified().summary.record_count == 3                         # 書かない


def test_late_window_boundaries_not_due_and_missed(world) -> None:
    before = scheduled(world, "slot-a", tokyo(1, 14, 59, 59))
    assert (before.kind, before.code, before.exit_code) == ("SKIPPED", "OUTSIDE_WINDOW:NOT_DUE", EXIT_OK)
    assert not (world["root"] / "ledger").exists()                                        # NOT_DUE は書かない
    edge = scheduled(world, "slot-a", tokyo(1, 16, 0, 0))                                  # 両端を含む
    assert edge.kind == "SUCCEEDED" and edge.exit_code == EXIT_OK
    late = scheduled(world, "slot-a", tokyo(1, 16, 0, 1))                                  # 成功の後の窓の外: 記録済みの SUCCEEDED が authority
    assert (late.kind, late.code, late.exit_code) == ("SKIPPED", "ALREADY_SUCCEEDED", EXIT_OK)
    assert ledger(world).open_verified().summary.record_count == 3


def test_midnight_crossing_weekday_mask_weekend_holiday_and_missing_calendar(world) -> None:
    crossing = scheduled(world, "slot-b", tokyo(2, 0, 30))                                 # 木 0:30 → 水 23:30 の instance
    assert crossing.kind == "SUCCEEDED" and crossing.scheduled_for == "2026-07-01T14:30:00Z"
    request = json.loads((world["root"] / "requests" / f"{crossing.run_id}.json").read_text())
    assert request["as_of_date"] == "2026-07-01" and request["readiness_only"] is False
    mask = scheduled(world, "slot-a", tokyo(4, 15, 10))                                    # 土: slot-a の mask の外
    assert (mask.kind, mask.code, mask.exit_code) == ("SKIPPED", "OUTSIDE_WINDOW:WEEKDAY_NOT_IN_MASK", EXIT_OK)
    weekend = scheduled(world, "slot-b", tokyo(4, 23, 40))                                 # 土: readiness だけの run
    assert weekend.kind == "SUCCEEDED"
    weekend_request = json.loads((world["root"] / "requests" / f"{weekend.run_id}.json").read_text())
    assert weekend_request["readiness_only"] is True and weekend_request["session_date"] == "2026-07-03"
    holiday = scheduled(world, "slot-a", tokyo(2, 15, 10))                                 # 木 ＝ 休日: SKIPPED を ledger に記録
    assert (holiday.kind, holiday.code, holiday.exit_code) == ("SKIPPED", "NON_BUSINESS_DAY:HOLIDAY", EXIT_OK)
    assert ledger(world).open_verified().run_states[holiday.run_id] is RunState.SKIPPED
    count = ledger(world).open_verified().summary.record_count
    calendar_file(world["root"]).unlink()
    missing = scheduled(world, "slot-a", tokyo(1, 15, 10))
    assert (missing.kind, missing.code, missing.exit_code) == ("AUTHORITY_INVALID", "CALENDAR_UNAVAILABLE:CALENDAR_MISSING", EXIT_AUTHORITY_INVALID)
    write_calendar_authority(world["root"], HolidayCalendar(calendar_id="ops-cal", version=2, dates=(HOLIDAY, "2026-07-03")), operator="human")
    mismatch = scheduled(world, "slot-a", tokyo(1, 15, 10))                                # 参照と違う版: fail closed
    assert mismatch.code == "CALENDAR_UNAVAILABLE:CALENDAR_REF_MISMATCH" and mismatch.exit_code == EXIT_AUTHORITY_INVALID
    assert ledger(world).open_verified().summary.record_count == count


# ================================================================ invocation ・authority


def test_wrong_slot_disabled_slot_and_disabled_schedule(world) -> None:
    wrong = scheduled(world, "slot-x", tokyo(1, 15, 0))
    assert (wrong.kind, wrong.code, wrong.exit_code) == ("AUTHORITY_INVALID", "SCHEMA_INVALID:SLOT_NOT_FOUND", EXIT_AUTHORITY_INVALID)
    disabled_slot = scheduled(world, "slot-c", tokyo(6, 12, 0))
    assert (disabled_slot.kind, disabled_slot.code, disabled_slot.exit_code) == ("SKIPPED", "DISABLED:SLOT_DISABLED", EXIT_OK)
    off = schedule(version=2, enabled=False, supersedes=schedule().content_digest)
    write_schedule_authority(world["root"], off, operator="human")
    disabled = scheduled(world, "slot-a", tokyo(1, 15, 0))
    assert (disabled.kind, disabled.code, disabled.exit_code) == ("SKIPPED", "DISABLED:SCHEDULE_DISABLED", EXIT_OK)
    assert not (world["root"] / "ledger").exists()


def test_unattended_preconditions_refuse_before_writing_and_failures_are_committed(world, monkeypatch) -> None:
    credential = scheduled(world, "slot-a", tokyo(1, 15, 0), environment={"JQUANTS_API_KEY": "SENTINEL"})
    assert (credential.kind, credential.code, credential.exit_code) == ("REFUSED", "CREDENTIAL_PRESENT", EXIT_PRECONDITION_REFUSED)
    write_runtime_pin(world["root"], "0" * 40, operator="human", pinned_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    head = scheduled(world, "slot-a", tokyo(1, 15, 0))
    assert (head.kind, head.code, head.exit_code) == ("REFUSED", "REPO_HEAD_MISMATCH", EXIT_PRECONDITION_REFUSED)
    (world["root"] / "authority" / "runtime_pin.json").unlink()
    unpinned = scheduled(world, "slot-a", tokyo(1, 15, 0))
    assert (unpinned.kind, unpinned.code, unpinned.exit_code) == ("AUTHORITY_INVALID", "SCHEMA_INVALID:RUNTIME_PIN_MISSING", EXIT_AUTHORITY_INVALID)
    assert not (world["root"] / "ledger").exists() and not (world["root"] / "runs").exists()   # 何も書いていない
    write_runtime_pin(world["root"], world["head"], operator="human", pinned_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    (world["repo"] / "dirty.txt").write_text("x", encoding="utf-8")
    dirty = scheduled(world, "slot-a", tokyo(1, 15, 0))
    assert (dirty.kind, dirty.code, dirty.exit_code) == ("FAILED", "REPO_NOT_CLEAN", EXIT_FAILED)
    assert ledger(world).open_verified().run_states[dirty.run_id] is RunState.FAILED      # ledger に FAILED として残る
    (world["repo"] / "dirty.txt").unlink()
    prior = scheduled(world, "slot-a", tokyo(1, 15, 0))                                    # 前の attempt が在る: 無人では retry しない
    assert (prior.kind, prior.code, prior.exit_code) == ("RECOVERY_REQUIRED", "DUPLICATE_INVOCATION:PRIOR_ATTEMPT_EXISTS", EXIT_RECOVERY_REQUIRED)
    missing_root = run_scheduled("slot-b", PrivateRoots(world["tmp"] / "absent", world["p10"], world["root"]), repo_root=world["repo"],
                                 runtime_root=REPO_ROOT, environment={}, selection_clock_at=tokyo(1, 23, 40), clock=ticking_clock())
    assert (missing_root.kind, missing_root.code, missing_root.exit_code) == ("FAILED", "ROOT_MISSING:P9", EXIT_FAILED)

    def outbound(*_a, **_k):
        socket.create_connection(("203.0.113.1", 80), timeout=1)

    monkeypatch.setattr(rx, "build_snapshot", outbound)
    denied = scheduled(world, "slot-b", tokyo(3, 23, 40))                                  # 別の instance（金）
    assert (denied.kind, denied.code, denied.exit_code) == ("FAILED", "INTERRUPTED:NETWORK_DENIED", EXIT_FAILED)
    assert socket.getaddrinfo("127.0.0.1", 80)


def test_unattended_runs_never_recover_stale_locks_orphans_checkpoints_or_partials(world) -> None:
    root = world["root"]
    request = AutomationExecutionRequest(schedule_id="ops-daily", slot_id="slot-a", scheduled_for=tokyo(1, 15, 0), as_of_date=tokyo(1, 15, 0).date(),
                                         session_date=tokyo(1, 15, 0).date(), runtime_anchor=world["head"], attempt=1, operator="scheduler",
                                         schedule_digest=schedule().content_digest)
    me = os.getpid()
    live = acquire_lock(root, "RUN", request.run_id, probe=ProcessProbe(), clock_instant=tokyo(1, 15, 0))
    active = scheduled(world, "slot-a", tokyo(1, 15, 0))
    assert (active.kind, active.code, active.exit_code) == ("DUPLICATE_ACTIVE", "DUPLICATE_INVOCATION:RUN_ACTIVE", EXIT_DUPLICATE_ACTIVE)
    live.release()
    acquire_lock(root, "RUN", request.run_id, probe=StaticProbe({me: True}, {me: "1" * 64}, boot="b" * 64), clock_instant=tokyo(1, 15, 0))
    stale = scheduled(world, "slot-a", tokyo(1, 15, 0))                                    # 本物の probe から見れば再起動後: stale
    assert (stale.kind, stale.code, stale.exit_code) == ("RECOVERY_REQUIRED", "DUPLICATE_INVOCATION:LOCK_STALE", EXIT_RECOVERY_REQUIRED)
    assert run_lock_file(root, request.run_id).exists()                                    # 自動では解放しない
    run_lock_file(root, request.run_id).unlink()
    acquire_lock(root, "RUN", request.run_id, probe=StaticProbe({me: True}, {}, boot=None), clock_instant=tokyo(1, 15, 0))
    unknown = scheduled(world, "slot-a", tokyo(1, 15, 0), probe=StaticProbe({me: True}, {}, boot=None))
    assert unknown.code == "DUPLICATE_INVOCATION:LOCK_UNKNOWN_PROVENANCE" and unknown.exit_code == EXIT_RECOVERY_REQUIRED
    run_lock_file(root, request.run_id).unlink()
    with pytest.raises(InjectedCrash):                                                     # 窓 A: 孤児
        commit_run(request, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock(),
                   injection=RaisingInjection({"AFTER_FINALIZATION": raise_type(InjectedCrash)}))
    frozen = snapshot_of_root(root)
    dead = StaticProbe({me: False}, {}, boot=None)                                         # 死んだ process の lock（本物の crash の形）
    orphan = scheduled(world, "slot-a", tokyo(1, 15, 0), probe=dead)
    assert (orphan.kind, orphan.code, orphan.exit_code) == ("RECOVERY_REQUIRED", "DUPLICATE_INVOCATION:PRIOR_ATTEMPT_EXISTS", EXIT_RECOVERY_REQUIRED)
    assert snapshot_of_root(root) == frozen                                                # 証拠は不変
    store = ledger(world)
    store.checkpoint_file.write_bytes(HeadCheckpoint.of(store.open_verified(allow_stale_checkpoint=True).records[:1]).to_bytes())
    stale_checkpoint = scheduled(world, "slot-b", tokyo(1, 23, 40))
    assert (stale_checkpoint.kind, stale_checkpoint.code, stale_checkpoint.exit_code) == ("RECOVERY_REQUIRED", "LEDGER_INVALID:CHECKPOINT_STALE",
                                                                                           EXIT_RECOVERY_REQUIRED)
    store.checkpoint_file.write_bytes(HeadCheckpoint.of(store.open_verified(allow_stale_checkpoint=True).records).to_bytes())
    partial_request = AutomationExecutionRequest(**{**request.__dict__, "slot_id": "slot-b", "scheduled_for": tokyo(1, 23, 30)})
    (root / "runs" / (partial_request.run_id + ".partial")).mkdir(parents=True)
    partial = scheduled(world, "slot-b", tokyo(1, 23, 40))
    assert (partial.kind, partial.code, partial.exit_code) == ("RECOVERY_REQUIRED", "DUPLICATE_INVOCATION:PARTIAL_EXISTS", EXIT_RECOVERY_REQUIRED)
    assert (root / "runs" / (partial_request.run_id + ".partial")).is_dir()
    (root / "runs" / (partial_request.run_id + ".partial")).rmdir()
    ok = scheduled(world, "slot-b", tokyo(1, 23, 40))                                      # 回復が要らない slot は進む
    assert ok.kind == "SUCCEEDED"
    status_file(root).unlink()                                                             # 古い status だけ: 進んで再生成
    crossing = scheduled(world, "slot-b", tokyo(2, 23, 40))
    assert crossing.kind == "SUCCEEDED" and read_status(root)["ledger_record_count"] == ledger(world).open_verified().summary.record_count


# ================================================================ task definition ・adapter ・install


def test_task_definitions_are_deterministic_owned_least_privilege_and_free_of_secrets() -> None:
    definitions = task_definitions(schedule(), PATHS)
    assert [d.task_name for d in definitions] == [f"{TASK_NAMESPACE}\\ops-daily\\slot-a", f"{TASK_NAMESPACE}\\ops-daily\\slot-b",
                                                  f"{TASK_NAMESPACE}\\ops-daily\\slot-c"]
    assert [d.enabled for d in definitions] == [True, True, False]
    again = task_definitions(schedule(), PATHS)
    assert [d.xml for d in again] == [d.xml for d in definitions] and task_xml(schedule(), schedule().slots[0], PATHS) == definitions[0].xml
    xml = definitions[0].xml
    assert xml[:2] == b"\xff\xfe" and b"\n\x00" in xml and b"\r\x00\n\x00" in xml
    text = xml.decode("utf-16")
    assert "<StartBoundary>2000-01-03T15:00:00</StartBoundary>" in text
    assert "<DaysOfWeek><Monday /><Tuesday /><Wednesday /><Thursday /><Friday /></DaysOfWeek>" in text
    assert "<Saturday />" not in text and "<Sunday />" in definitions[1].xml.decode("utf-16")
    for clause in ("<LogonType>InteractiveToken</LogonType>", "<RunLevel>LeastPrivilege</RunLevel>", "<MultipleInstancesPolicy>IgnoreNew",
                   "<StartWhenAvailable>true</StartWhenAvailable>", "<WakeToRun>false</WakeToRun>", "<ExecutionTimeLimit>PT30M",
                   "<RunOnlyIfNetworkAvailable>false", f"<Description>{OWNER_MARKER} schedule_digest={schedule().content_digest}",
                   f"<URI>{TASK_NAMESPACE}\\ops-daily\\slot-a</URI>", "<Author>P12</Author>", "<Command>C:\\compass\\venv\\Scripts\\python.exe</Command>",
                   "<Arguments>-m src.intelligence.automation.run_cli scheduled-run --slot-id slot-a --private-root D:\\compass_private\\p12",
                   "<WorkingDirectory>C:\\compass\\repo</WorkingDirectory>", "<Enabled>true</Enabled>"):
        assert clause in text, clause
    assert "<Enabled>false</Enabled>" in definitions[2].xml.decode("utf-16").split("</Triggers>")[0]
    for banned in ("Password", "<UserId>", "SYSTEM", "HighestAvailable", "git ", "selection-clock", "JQUANTS", "RunLevel>Highest"):
        assert banned not in text, banned
    assert text.count("http") == 1 and "schemas.microsoft.com/windows/2004/02/mit/task" in text   # 名前空間の URI だけ ・network の命令は無い
    import getpass
    user = getpass.getuser()
    assert f"\\{user}\\" not in text and f"/{user}/" not in text and f"<Author>{user}" not in text   # user 名は path にも Author にも無い
    safe = definitions[0].to_safe_dict()
    assert set(safe) == {"task_name", "slot_id", "enabled", "xml_digest"} and "C:\\" not in json.dumps(safe) and "D:\\" not in json.dumps(safe)
    assert owned_task_names(schedule()) == tuple(d.task_name for d in definitions) and task_name("ops-daily", "slot-a") == definitions[0].task_name
    assert repr(PATHS) == "SchedulerPaths(<private>)"
    with pytest.raises(AutomationError):
        SchedulerPaths(interpreter="", repo_root="x", runtime_root="x", private_root="x", p9_root="x", p10_root="x")
    with pytest.raises(AutomationError):
        task_definitions("schedule", PATHS)  # type: ignore[arg-type]


def test_install_plan_apply_remove_and_status_touch_only_owned_tasks(world) -> None:
    root = world["root"]
    wrong_zone = InMemoryTaskScheduler(timezone_name="Pacific Standard Time")
    with pytest.raises(AutomationError) as e:
        plan_install(root, PATHS, wrong_zone)
    assert e.value.detail == "SYSTEM_TIMEZONE_NOT_TOKYO"
    adapter = InMemoryTaskScheduler()
    foreign_name = task_name("ops-daily", "slot-c")
    adapter.tasks[foreign_name] = {"xml": "<Task><RegistrationInfo><Author>someone</Author></RegistrationInfo></Task>", "enabled": True,
                                   "last_result": 0}                                      # 同名だが所有の印が無い
    plan = plan_install(root, PATHS, adapter)
    assert plan.to_safe_dict()["schedule_id"] == "ops-daily" and len(plan.definitions) == 3
    assert "D:\\" not in json.dumps(plan.to_safe_dict()) and adapter.calls == [("timezone",)]
    before = scheduler_status(root, adapter)
    assert before["installed_task_count"] == 0 and before["not_owned_count"] == 1 and before["scheduler_installed"] is False
    with pytest.raises(AutomationError):
        install_tasks(root, plan, adapter, operator="scheduler")
    with pytest.raises(AutomationError) as e:
        install_tasks(root, plan, adapter, operator="human")                                     # 同名の無関係な task: 上書きしない
    assert e.value.public_code == "DUPLICATE_INVOCATION:TASK_NOT_OWNED" and not any(c[0] == "register" for c in adapter.calls)
    foreign = adapter.tasks.pop(foreign_name)                                              # 人が片付けた後
    outcome = install_tasks(root, plan, adapter, operator="human")
    assert outcome["task_count"] == 3 and sorted(p.name for p in (root / "scheduler").iterdir()) == ["ops-daily.slot-a.xml", "ops-daily.slot-b.xml",
                                                                                                      "ops-daily.slot-c.xml"]
    assert (root / "scheduler" / "ops-daily.slot-a.xml").read_bytes() == plan.definitions[0].xml
    after = scheduler_status(root, adapter)
    assert after["scheduler_installed"] is True and after["installed_task_count"] == 3 and after["enabled_task_count"] == 2
    assert after["enabled_slot_count"] == 2 and after["expected_task_count"] == 3 and after["recovery_required"] is False
    assert set(after) == {"scheduler_installed", "expected_task_count", "installed_task_count", "enabled_task_count", "not_owned_count",
                          "enabled_slot_count", "last_scheduler_result_code", "recovery_required"}
    adapter.tasks[foreign_name] = foreign                                                 # 無関係な同名の task が戻ってきた
    dry = remove_tasks(root, adapter, operator="human", apply=False)
    assert dry["applied"] is False and len(dry["removed"]) == 2 and dry["not_owned"] == [foreign_name] and len(adapter.tasks) == 3
    applied = remove_tasks(root, adapter, operator="human", apply=True)
    assert applied["applied"] and len(applied["removed"]) == 2 and foreign_name in adapter.tasks and len(adapter.tasks) == 1   # 無関係は残る
    assert ("delete", foreign_name) not in adapter.calls
    assert scheduler_status(root, adapter)["installed_task_count"] == 0
    query = adapter.query(foreign_name)
    assert isinstance(query, TaskQuery) and query.to_safe_dict() == {"present": True, "enabled": True, "last_result": 0}


def test_runtime_pin_is_written_from_a_clean_head_only_and_validated_on_read(tmp_path: Path) -> None:
    repo, head = make_repo(tmp_path / "repo")
    root = tmp_path / "p12"
    with pytest.raises(AutomationError):
        pin_clean_head(root, repo, operator="scheduler", pinned_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert pin_clean_head(root, repo, operator="human", pinned_at=datetime(2026, 7, 1, tzinfo=timezone.utc)) == head
    assert read_runtime_pin(root) == head
    (repo / "dirty.txt").write_text("x", encoding="utf-8")
    with pytest.raises(AutomationError) as e:
        pin_clean_head(root, repo, operator="human", pinned_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert e.value.code == "REPO_NOT_CLEAN" and read_runtime_pin(root) == head
    with pytest.raises(AutomationError) as e:
        pin_clean_head(root, tmp_path / "not-a-repo", operator="human", pinned_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert e.value.public_code == "REPO_HEAD_MISMATCH:GIT_UNAVAILABLE"
    (root / "authority" / "runtime_pin.json").write_text("{bad\n", encoding="utf-8")
    with pytest.raises(AutomationError) as e:
        read_runtime_pin(root)
    assert e.value.detail == "RUNTIME_PIN_MALFORMED"


# ================================================================ CLI ・process 間


def cli_args(world, *extra):
    return [*extra, "--private-root", str(world["root"]), "--p9-root", str(world["p9"]["root"]), "--p10-root", str(world["p10"]),
            "--repo-root", str(world["repo"]), "--runtime-root", str(REPO_ROOT)]


def test_the_cli_scheduled_run_prints_safe_report_lines_and_returns_the_contract_exit_codes(world) -> None:
    out = io.StringIO()
    code = run_cli.main(["scheduled-run", "--slot-id", "slot-a", "--selection-clock-at", "2026-07-01T06:00:00Z", *cli_args(world)],
                        stdout=out, environment={})
    lines = out.getvalue().splitlines()
    assert code == EXIT_OK and lines[0] == "REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=SUCCEEDED CODE=RUN_SUCCEEDED"
    assert lines[1].startswith("REPORT: RUN_ID=") and "REPORT: RUN_SUCCEEDED" in lines and lines[-1] == "REPORT: EXIT=0"
    assert all(line.startswith("REPORT: ") for line in lines) and str(world["tmp"]) not in out.getvalue()
    for sentinel in world["sentinels"]:
        assert sentinel not in out.getvalue(), sentinel
    out = io.StringIO()
    code = run_cli.main(["scheduled-run", "--slot-id", "slot-b", "--selection-clock-at", "2026-07-01T18:00:00Z", *cli_args(world)],
                        stdout=out, environment={})                                        # slot-b 23:30 の窓（〜01:30）の後 ＝ MISSED
    lines = out.getvalue().splitlines()
    assert code == EXIT_MISSED and lines[0] == "REPORT: SCHEDULED_RUN SLOT=slot-b OUTCOME=MISSED CODE=OUTSIDE_WINDOW:MISSED"
    assert lines[1].startswith("REPORT: RUN_ID=") and lines[-1] == "REPORT: EXIT=4"
    out = io.StringIO()
    code = run_cli.main(["scheduled-run", "--slot-id", "slot-a", *cli_args(world)], stdout=out, environment={"JQUANTS_API_KEY": "x"})
    assert code == EXIT_PRECONDITION_REFUSED and "CODE=CREDENTIAL_PRESENT" in out.getvalue()
    out = io.StringIO()
    code = run_cli.main(["scheduled-run", "--slot-id", "slot-a", *cli_args(world)], stdout=out, environment={})   # 本物の時計: 窓の外
    assert code in (EXIT_OK, EXIT_MISSED) and "OUTCOME=" in out.getvalue()
    out = io.StringIO()
    assert run_cli.main(["pin-runtime", "--private-root", str(world["root"]), "--repo-root", str(world["repo"])], stdout=out,
                        environment={}) == 0
    assert out.getvalue() == f"REPORT: RUNTIME_PINNED ANCHOR={world['head']}\n"
    adapter = InMemoryTaskScheduler()
    out = io.StringIO()
    code = run_cli.main(["scheduler-install", *cli_args(world), "--interpreter", "C:\\compass\\venv\\Scripts\\python.exe"], stdout=out,
                        environment={}, scheduler=adapter)
    text = out.getvalue()
    assert code == 0 and text.count("REPORT: SCHEDULER_TASK NAME=") == 3 and "REPORT: SCHEDULER_PLAN TASKS=3 APPLIED=NO" in text
    assert adapter.tasks == {} and str(world["tmp"]) not in text and "C:\\" not in text
    out = io.StringIO()
    code = run_cli.main(["scheduler-install", *cli_args(world), "--interpreter", "C:\\compass\\venv\\Scripts\\python.exe", "--apply"],
                        stdout=out, environment={}, scheduler=adapter)
    assert code == 0 and out.getvalue().splitlines()[-1] == "REPORT: SCHEDULER_INSTALLED TASKS=3" and len(adapter.tasks) == 3
    out = io.StringIO()
    assert run_cli.main(["scheduler-status", "--private-root", str(world["root"])], stdout=out, environment={}, scheduler=adapter) == 0
    assert out.getvalue().startswith("REPORT: SCHEDULER_STATUS ") and "SCHEDULER_INSTALLED=True" in out.getvalue()
    out = io.StringIO()
    assert run_cli.main(["scheduler-remove", "--private-root", str(world["root"])], stdout=out, environment={}, scheduler=adapter) == 0
    assert out.getvalue() == "REPORT: SCHEDULER_REMOVE APPLIED=NO REMOVED=3 ABSENT=0 NOT_OWNED=0\n" and len(adapter.tasks) == 3
    out = io.StringIO()
    assert run_cli.main(["scheduler-remove", "--private-root", str(world["root"]), "--apply"], stdout=out, environment={}, scheduler=adapter) == 0
    assert adapter.tasks == {} and out.getvalue() == "REPORT: SCHEDULER_REMOVE APPLIED=YES REMOVED=3 ABSENT=0 NOT_OWNED=0\n"
    out = io.StringIO()
    code = run_cli.main(["scheduler-install", *cli_args(world), "--interpreter", "C:\\compass\\venv\\Scripts\\python.exe"], stdout=out,
                        environment={}, scheduler=InMemoryTaskScheduler(timezone_name="UTC"))
    assert (code, out.getvalue()) == (1, "REPORT: RUN_FAILED CODE=SCHEMA_INVALID:SYSTEM_TIMEZONE_NOT_TOKYO\n")


def test_two_scheduled_processes_for_the_same_slot_commit_exactly_once(world) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JQUANTS_")}
    argv = [sys.executable, "-m", "src.intelligence.automation.run_cli", "scheduled-run", "--slot-id", "slot-a", "--selection-clock-at",
            "2026-07-01T06:10:00Z", *cli_args(world)]
    processes = [subprocess.Popen(argv, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for _ in range(2)]
    outputs = [p.communicate(timeout=300) for p in processes]
    codes = sorted(p.returncode for p in processes)
    assert codes in ([EXIT_OK, EXIT_OK], [EXIT_OK, EXIT_DUPLICATE_ACTIVE]) and all(e == "" for _, e in outputs), outputs
    firsts = [o.splitlines()[0] for o, _ in outputs]
    assert "REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=SUCCEEDED CODE=RUN_SUCCEEDED" in firsts
    other = [f for f in firsts if "OUTCOME=SUCCEEDED" not in f][0]
    assert other in ("REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=SKIPPED CODE=ALREADY_SUCCEEDED",
                     "REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=DUPLICATE_ACTIVE CODE=DUPLICATE_INVOCATION:RUN_ACTIVE",
                     "REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=DUPLICATE_ACTIVE CODE=DUPLICATE_INVOCATION:LEDGER_LOCKED"), other
    state = ledger(world).open_verified()
    assert state.summary.record_count == 3 and set(state.run_states.values()) == {RunState.SUCCEEDED}
    assert len(list((world["root"] / "runs").iterdir())) == 1 and not list((world["root"] / "locks").glob("*.lock"))


# ================================================================ A5.1: skip の証拠


def test_missed_slot_commits_planned_then_skipped_without_execution_and_repeats_resolve_to_the_record(world) -> None:
    root = world["root"]
    missed = scheduled(world, "slot-a", tokyo(1, 16, 0, 1))                                # 水 15:00 の窓（〜16:00）の後
    assert (missed.kind, missed.code, missed.exit_code) == ("MISSED", "OUTSIDE_WINDOW:MISSED", EXIT_MISSED)
    assert missed.scheduled_for == "2026-07-01T06:00:00Z" and missed.skip.status == "SKIPPED" and missed.transaction is None
    state = ledger(world).open_verified()
    assert [r.transition_to for r in state.records] == [RunState.PLANNED, RunState.SKIPPED]
    assert state.records[1].failure_code == "OUTSIDE_WINDOW:MISSED" and state.records[1].operator == "scheduler" and state.records[1].attempt == 1
    assert state.checkpoint == HeadCheckpoint.of(state.records) and state.checkpoint_class == "CHECKPOINT_OK"
    assert not (root / "runs").exists() and (root / "requests" / f"{missed.run_id}.json").exists()   # A2 は走らない ・要求の証拠はある
    status_doc = read_status(root)
    assert status_doc["projection"]["health_code"] == "SKIPPED" and status_doc["projection"]["last_terminal_run"]["state"] == "SKIPPED"
    assert status_doc["projection"]["last_failure_code"] == "OUTSIDE_WINDOW:MISSED" and status_doc["ledger_record_count"] == 2
    frozen = snapshot_of_root(root)
    again = scheduled(world, "slot-a", tokyo(1, 17, 0))                                    # 2 度目: 記録済みの終端に解決
    assert (again.kind, again.code, again.exit_code) == ("MISSED", "ALREADY_SKIPPED:OUTSIDE_WINDOW:MISSED", EXIT_MISSED)
    assert again.run_id == missed.run_id and again.skip.status == "ALREADY_SKIPPED"
    assert snapshot_of_root(root) == frozen and ledger(world).open_verified().summary.record_count == 2   # 重複は追記しない ・attempt 2 は無い
    assert not list((root / "locks").glob("*.lock"))
    request = json.loads((root / "requests" / f"{missed.run_id}.json").read_text())
    assert request["attempt"] == 1 and request["as_of_date"] == "2026-07-01" and request["session_date"] == "2026-07-01"
    for blob in ((root / "ledger" / "ledger.jsonl").read_text(encoding="utf-8"), status_file(root).read_text(encoding="utf-8")):
        for sentinel in world["sentinels"] | {str(world["tmp"]), "Traceback", "Exception"}:
            assert sentinel not in blob, sentinel
    yesterday = scheduled(world, "slot-b", tokyo(2, 2, 0))                                 # 木 02:00: 水 23:30 の instance の窓（〜01:30）の後
    assert yesterday.kind == "MISSED" and yesterday.scheduled_for == "2026-07-01T14:30:00Z"
    assert scheduled(world, "slot-b", tokyo(2, 12, 0)).code == "ALREADY_SKIPPED:OUTSIDE_WINDOW:MISSED"   # 木 12:00: 同じ instance


def test_non_business_day_skip_is_committed_once_and_readiness_slots_execute_normally(world) -> None:
    root = world["root"]
    holiday = scheduled(world, "slot-a", tokyo(2, 15, 10))
    assert (holiday.kind, holiday.code, holiday.exit_code) == ("SKIPPED", "NON_BUSINESS_DAY:HOLIDAY", EXIT_OK)
    state = ledger(world).open_verified()
    assert [r.transition_to for r in state.records] == [RunState.PLANNED, RunState.SKIPPED] and state.records[1].failure_code == "NON_BUSINESS_DAY:HOLIDAY"
    assert not (root / "runs").exists() and read_status(root)["projection"]["health_code"] == "SKIPPED"
    frozen = snapshot_of_root(root)
    again = scheduled(world, "slot-a", tokyo(2, 15, 30))
    assert (again.kind, again.code, again.exit_code) == ("SKIPPED", "ALREADY_SKIPPED:NON_BUSINESS_DAY:HOLIDAY", EXIT_OK)
    assert snapshot_of_root(root) == frozen
    weekend = scheduled(world, "slot-b", tokyo(4, 23, 40))                                 # readiness を許す slot: 通常の readiness だけの run
    assert weekend.kind == "SUCCEEDED" and weekend.skip is None and weekend.transaction is not None
    assert (root / "runs" / weekend.run_id).is_dir()
    assert json.loads((root / "requests" / f"{weekend.run_id}.json").read_text())["readiness_only"] is True
    all_days = ScheduleSlot(slot_id="slot-a", local_time="15:00", weekday_mask=("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"),
                            late_window_seconds=3600, readiness_on_non_business_day=False, enabled=True)
    weekend_schedule = schedule(version=2, supersedes=schedule().content_digest, slots=(all_days, schedule().slots[1], schedule().slots[2]))
    write_schedule_authority(root, weekend_schedule, operator="human")
    saturday = scheduled(world, "slot-a", tokyo(4, 15, 10))
    assert (saturday.kind, saturday.code, saturday.exit_code) == ("SKIPPED", "NON_BUSINESS_DAY:WEEKEND", EXIT_OK)
    assert ledger(world).open_verified().records[-1].failure_code == "NON_BUSINESS_DAY:WEEKEND"


def test_no_evidence_outcomes_never_touch_the_ledger(world) -> None:
    root = world["root"]
    scheduled(world, "slot-a", tokyo(1, 14, 0))                                            # NOT_DUE
    scheduled(world, "slot-c", tokyo(6, 12, 0))                                            # DISABLED slot
    assert not (root / "ledger").exists()
    done = scheduled(world, "slot-a", tokyo(1, 15, 0))
    assert done.kind == "SUCCEEDED"
    frozen = snapshot_of_root(root)
    assert scheduled(world, "slot-a", tokyo(1, 15, 30)).code == "ALREADY_SUCCEEDED"       # ALREADY_SUCCEEDED
    assert snapshot_of_root(root) == frozen
    live = acquire_lock(root, "RUN", "f" * 64, probe=ProcessProbe(), clock_instant=tokyo(1, 15, 0))   # 無関係な lock は影響しない
    live.release()
    off = schedule(version=2, enabled=False, supersedes=schedule().content_digest)
    write_schedule_authority(root, off, operator="human")
    disabled = scheduled(world, "slot-a", tokyo(1, 16, 30))                                # DISABLED schedule（窓の外でも書かない）
    assert disabled.code == "DISABLED:SCHEDULE_DISABLED" and ledger(world).open_verified().summary.record_count == 3


def test_two_processes_observing_the_same_missed_slot_commit_exactly_one_skip(world) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JQUANTS_")}
    argv = [sys.executable, "-m", "src.intelligence.automation.run_cli", "scheduled-run", "--slot-id", "slot-a", "--selection-clock-at",
            "2026-07-01T07:30:00Z", *cli_args(world)]
    processes = [subprocess.Popen(argv, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for _ in range(2)]
    outputs = [p.communicate(timeout=300) for p in processes]
    assert all(e == "" for _, e in outputs), outputs
    firsts = sorted(o.splitlines()[0] for o, _ in outputs)
    codes = sorted(p.returncode for p in processes)
    assert "REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=MISSED CODE=OUTSIDE_WINDOW:MISSED" in firsts
    other = [f for f in firsts if f != "REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=MISSED CODE=OUTSIDE_WINDOW:MISSED"][0]
    assert other in ("REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=MISSED CODE=ALREADY_SKIPPED:OUTSIDE_WINDOW:MISSED",
                     "REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=DUPLICATE_ACTIVE CODE=DUPLICATE_INVOCATION:RUN_ACTIVE",
                     "REPORT: SCHEDULED_RUN SLOT=slot-a OUTCOME=DUPLICATE_ACTIVE CODE=DUPLICATE_INVOCATION:LEDGER_LOCKED"), other
    assert codes in ([EXIT_MISSED, EXIT_MISSED], [EXIT_MISSED, EXIT_DUPLICATE_ACTIVE])
    state = ledger(world).open_verified()
    assert [r.transition_to for r in state.records] == [RunState.PLANNED, RunState.SKIPPED] and state.checkpoint == HeadCheckpoint.of(state.records)
    assert not (world["root"] / "runs").exists() and not list((world["root"] / "locks").glob("*.lock"))
