"""P12-A4 — 注入した crash ・回復（窓 A ／ B ／ C ・partial ・crashed）・retry ・cancel ・idempotency ・CLI ・process 間の race の test。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.automation import ledger_commit as lc
from src.intelligence.automation import ledger_store as ls
from src.intelligence.automation import run_cli
from src.intelligence.automation.cancel_authority import cancel_file, write_cancel_request
from src.intelligence.automation.execution_request import AutomationExecutionRequest
from src.intelligence.automation.failure_codes import AutomationError
from src.intelligence.automation.injection import POINTS, RaisingInjection, raise_type
from src.intelligence.automation.ledger_store import LedgerStore
from src.intelligence.automation.operational_lock import ledger_lock_file, run_lock_file
from src.intelligence.automation.preconditions import PrivateRoots
from src.intelligence.automation.process_probe import ProcessProbe, StaticProbe
from src.intelligence.automation.recovery import (recover_crashed, recover_orphan, recover_partial, regenerate_status,
                                                  release_lock, repair_checkpoint)
from src.intelligence.automation.retry import build_retry_request
from src.intelligence.automation.run_state import RunState
from src.intelligence.automation.run_transaction import STAGES, classify_after_crash, commit_run, request_file
from src.intelligence.automation.status_store import read_status, status_file
from tests.intelligence.test_automation_executor import ARTIFACT_NAMES, AS_OF, SCHEDULED_FOR, build_world
from tests.intelligence.test_automation_preconditions import SCHEDULE_DIGEST, make_repo
from tests.intelligence.test_automation_transaction import InjectedCrash, ticking_clock
from tests.intelligence.test_personal_intelligence_executor import tree

REPO_ROOT = Path(__file__).resolve().parents[2]
ME = os.getpid()
DEAD = StaticProbe({ME: False}, {}, boot=None)
LIVE = ProcessProbe()


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(lc, "LEDGER_LOCK_WAIT_SECONDS", 0.5)                               # test: 残った ledger lock を長く待たない
    built = build_world(tmp_path)
    repo, head = make_repo(tmp_path / "repo")
    request = AutomationExecutionRequest(schedule_id="ops-daily", slot_id="slot-a", scheduled_for=SCHEDULED_FOR, as_of_date=AS_OF,
                                         session_date=AS_OF, runtime_anchor=head, attempt=1, operator="human",
                                         schedule_digest=SCHEDULE_DIGEST)
    roots = PrivateRoots(built["p9"]["root"], built["p10"], tmp_path / "p12_private_root")
    before = (tree(built["p9"]["root"]), tree(built["p10"]))
    yield dict(request=request, roots=roots, repo=repo, head=head, tmp=tmp_path, **built)
    assert (tree(built["p9"]["root"]), tree(built["p10"])) == before


def commit(world, request=None, **overrides):
    args = dict(repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
    args.update(overrides)
    return commit_run(request or world["request"], world["roots"], **args)


def crash_at(world, point: str, request=None, **overrides):
    injection = RaisingInjection({point: raise_type(InjectedCrash)})
    with pytest.raises(InjectedCrash):
        commit(world, request, injection=injection, **overrides)
    return injection


def ledger(world) -> LedgerStore:
    return LedgerStore(world["roots"].p12_root)


def classify(world, run_id=None, probe=LIVE) -> dict:
    return classify_after_crash(world["roots"], run_id or world["request"].run_id, probe=probe)


def final_dir(world, request=None) -> Path:
    return world["roots"].p12_root / "runs" / (request or world["request"]).run_id


# ================================================================ injection points → evidence


def test_every_injection_point_leaves_classifiable_evidence_and_the_lock_of_a_dead_process(world) -> None:
    expected = {"AFTER_LOCK_ACQUIRED": ("NOT_STARTED", None, 0), "AFTER_PLANNED_APPEND": ("IN_FLIGHT", "PLANNED", 1),
                "AFTER_RUNNING_APPEND": ("IN_FLIGHT", "RUNNING", 2), "BEFORE_EXECUTION": ("IN_FLIGHT", "RUNNING", 2),
                "AFTER_FINALIZATION": ("ORPHANED_FINALIZATION", "RUNNING", 2), "AFTER_TERMINAL_APPEND": ("STATUS_STALE", "SUCCEEDED", 3),
                "AFTER_CHECKPOINT": ("STATUS_STALE", "SUCCEEDED", 3), "BEFORE_STATUS_WRITE": ("STATUS_STALE", "SUCCEEDED", 3),
                "AFTER_STATUS_WRITE": ("COMMITTED", "SUCCEEDED", 3), "BEFORE_LOCK_RELEASE": ("COMMITTED", "SUCCEEDED", 3)}
    assert set(expected) == set(POINTS)
    for index, point in enumerate(POINTS):
        request = AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": f"slot-{index}"})
        before = ledger(world).open_verified(allow_stale_checkpoint=True).summary.record_count if index else 0
        injection = crash_at(world, point, request)
        assert injection.fired[-1] == point
        evidence = classify(world, request.run_id)
        classification, ledger_state, appended = expected[point]
        assert (evidence["classification"], evidence["ledger_state"]) == (classification, ledger_state), point
        assert ledger(world).open_verified(allow_stale_checkpoint=True).summary.record_count == before + appended, point
        assert evidence["lock_class"] in ("LOCK_LIVE", "LOCK_UNKNOWN_PROVENANCE"), point   # 自分の process は生きている
        assert classify(world, request.run_id, probe=DEAD)["lock_class"] == "LOCK_STALE_DEAD" or classification in ("COMMITTED", "STATUS_STALE")
        if point in ("AFTER_TERMINAL_APPEND", "AFTER_CHECKPOINT"):
            assert ledger_lock_file(world["roots"].p12_root).exists()                     # ledger lock の中で死んだ: 残る
            assert release_lock(world["roots"], probe=DEAD)["released"]
        assert (final_dir(world, request).is_dir()) == (classification in ("ORPHANED_FINALIZATION", "STATUS_STALE", "COMMITTED"))
        if classification != "COMMITTED":
            assert read_status(world["roots"].p12_root) is None or read_status(world["roots"].p12_root)["ledger_record_count"] < before + appended
        release_lock(world["roots"], probe=DEAD, run_id=request.run_id)                  # 次の slot のために stale な lock を片付ける


def test_a_leftover_live_lock_blocks_the_same_run_and_a_proven_stale_lock_needs_explicit_release(world) -> None:
    crash_at(world, "AFTER_PLANNED_APPEND")
    assert run_lock_file(world["roots"].p12_root, world["request"].run_id).exists()
    again = commit(world)                                                                 # 同じ pid が生きている: RUN_ACTIVE
    assert (again.status, again.failure_code, again.stages_completed) == ("FAILED", "DUPLICATE_INVOCATION:RUN_ACTIVE", ())
    assert commit(world, probe=DEAD).failure_code == "DUPLICATE_INVOCATION:RUN_OPEN"      # dead: lock より先に open run の回復が要る
    outcome = release_lock(world["roots"], probe=DEAD, run_id=world["request"].run_id)
    assert outcome["released"] and outcome["lock_class"] == "LOCK_STALE_DEAD"
    assert classify(world)["lock_class"] == "LOCK_ABSENT" and classify(world)["classification"] == "IN_FLIGHT"
    recovered = recover_crashed(world["roots"], world["request"].run_id, probe=DEAD, clock=ticking_clock())
    assert recovered["terminal_state"] == "CRASHED" and recovered["from_state"] == "PLANNED"
    assert commit(world).failure_code == "DUPLICATE_INVOCATION:RUN_TERMINAL"               # 同じ attempt は再利用しない
    state = ledger(world).open_verified()
    retry = build_retry_request(world["roots"], world["request"].run_id, state=state, probe=LIVE, operator="human")
    assert retry.attempt == 2 and retry.retry_of == world["request"].run_id and retry.run_id != world["request"].run_id
    assert commit(world, retry).status == "SUCCEEDED"
    assert release_lock(world["roots"], probe=DEAD, run_id=world["request"].run_id)["lock_class"] == "LOCK_ABSENT"   # もう無い
    assert not any(ledger(world).directory.parent.joinpath("locks").glob("*.lock"))


# ================================================================ window A ・B ・C ・partial


def test_window_a_orphaned_finalization_is_recorded_conservatively_and_then_retried_as_a_new_run(world) -> None:
    crash_at(world, "AFTER_FINALIZATION")
    assert classify(world)["classification"] == "ORPHANED_FINALIZATION"
    before = tree(final_dir(world))
    with pytest.raises(AutomationError) as e:
        recover_orphan(world["roots"], world["request"].run_id, probe=LIVE, clock=ticking_clock())   # 生きた lock: 触らない
    assert e.value.code == "DUPLICATE_INVOCATION" and tree(final_dir(world)) == before
    (final_dir(world) / "snapshot.json").write_bytes(b"{}\n")                              # 改変: 回復は拒む
    with pytest.raises(AutomationError) as e:
        recover_orphan(world["roots"], world["request"].run_id, probe=DEAD, clock=ticking_clock())
    assert e.value.public_code == "SCHEMA_INVALID:ARTIFACT_DIGEST_MISMATCH"
    assert ledger(world).open_verified().run_states[world["request"].run_id] is RunState.RUNNING
    (final_dir(world) / "snapshot.json").write_bytes(before["snapshot.json"][0])
    outcome = recover_orphan(world["roots"], world["request"].run_id, probe=DEAD, clock=ticking_clock())
    assert outcome["terminal_state"] == "ORPHANED_FINALIZATION" and outcome["artifact_count"] == 7 and outcome["ledger_record_count"] == 3
    state = ledger(world).open_verified()
    record = state.records[-1]
    assert record.transition_to is RunState.ORPHANED_FINALIZATION and record.failure_code == "ORPHANED_FINALIZATION"
    assert record.artifact_digests == outcome["artifact_digests"] and "SUCCEEDED" not in {r.transition_to.value for r in state.records}
    assert {p.name: p.read_bytes() for p in final_dir(world).iterdir()} == {k: v[0] for k, v in before.items()}   # 証拠は不変
    assert read_status(world["roots"].p12_root)["projection"]["health_code"] == "ORPHANED_FINALIZATION"
    assert classify(world, probe=DEAD)["classification"] == "COMMITTED"
    with pytest.raises(AutomationError) as e:
        recover_orphan(world["roots"], world["request"].run_id, probe=DEAD, clock=ticking_clock())
    assert e.value.public_code == "DUPLICATE_INVOCATION:COMMITTED"
    release_lock(world["roots"], probe=DEAD, run_id=world["request"].run_id)
    retry = build_retry_request(world["roots"], world["request"].run_id, state=ledger(world).open_verified(), probe=LIVE, operator="human")
    assert retry.attempt == 2 and retry.retry_of == world["request"].run_id
    result = commit(world, retry)
    assert result.status == "SUCCEEDED" and final_dir(world, retry).is_dir() and final_dir(world).is_dir()
    assert ledger(world).open_verified().records[-1].run_id == retry.run_id


def test_window_b_checkpoint_catch_up_requires_the_lock_and_never_touches_history(world, monkeypatch) -> None:
    real = ls.LedgerStore.write_checkpoint
    monkeypatch.setattr(ls.LedgerStore, "write_checkpoint", lambda self, records: (_ for _ in ()).throw(InjectedCrash())
                        if len(records) == 3 else real(self, records))
    with pytest.raises(InjectedCrash):
        commit(world)
    monkeypatch.undo()
    monkeypatch.setattr(lc, "LEDGER_LOCK_WAIT_SECONDS", 0.5)                               # undo は fixture の短い待ちも戻すので再設定
    root = world["roots"].p12_root
    assert classify(world, probe=DEAD)["classification"] == "LEDGER_COMMITTED_CHECKPOINT_STALE"
    assert ledger_lock_file(root).exists()                                                 # checkpoint の置換の中で死んだ: ledger lock も残る
    before_ledger = ledger(world).ledger_file.read_bytes()
    with pytest.raises(AutomationError) as e:
        repair_checkpoint(world["roots"], probe=DEAD, clock=ticking_clock())
    assert e.value.public_code == "DUPLICATE_INVOCATION:LEDGER_LOCKED"                      # 壊さない: 先に release-lock
    assert release_lock(world["roots"], probe=DEAD)["lock_class"] == "LOCK_STALE_DEAD"
    outcome = repair_checkpoint(world["roots"], probe=DEAD, clock=ticking_clock())
    assert outcome["previous_checkpoint_count"] == 2 and outcome["ledger_record_count"] == 3 and outcome["checkpoint_class"] == "CHECKPOINT_OK"
    assert ledger(world).ledger_file.read_bytes() == before_ledger                        # 履歴は不変
    assert classify(world, probe=DEAD)["classification"] == "STATUS_STALE"
    regenerated = regenerate_status(world["roots"], clock=ticking_clock())
    assert regenerated["health_code"] == "OK" and classify(world, probe=DEAD)["classification"] == "COMMITTED"
    release_lock(world["roots"], probe=DEAD, run_id=world["request"].run_id)
    assert commit(world).failure_code == "ALREADY_SUCCEEDED"


def test_window_c_status_regeneration_changes_no_authority(world) -> None:
    crash_at(world, "BEFORE_STATUS_WRITE")
    root = world["roots"].p12_root
    assert read_status(root) is None and classify(world, probe=DEAD)["classification"] == "STATUS_STALE"
    before = (ledger(world).ledger_file.read_bytes(), ledger(world).checkpoint_file.read_bytes(), tree(final_dir(world)))
    outcome = regenerate_status(world["roots"], clock=ticking_clock())
    assert outcome["health_code"] == "OK" and read_status(root)["ledger_record_count"] == 3
    assert (ledger(world).ledger_file.read_bytes(), ledger(world).checkpoint_file.read_bytes(), tree(final_dir(world))) == before
    status_file(root).write_text("{corrupt", encoding="utf-8")
    assert classify(world, probe=DEAD)["classification"] == "STATUS_STALE"
    regenerate_status(world["roots"], clock=ticking_clock())
    assert classify(world, probe=DEAD)["classification"] == "COMMITTED"


def test_partial_directories_are_classified_and_preserved_as_crashed_evidence_never_deleted(world) -> None:
    crash_at(world, "BEFORE_EXECUTION")                                                    # RUNNING ・directory 無し
    root = world["roots"].p12_root
    partial = final_dir(world).with_name(final_dir(world).name + ".partial")
    partial.mkdir(parents=True)                                                           # runs/ は finalize の前なら無い
    (partial / "request.json").write_bytes(b"{}\n")
    assert classify(world)["classification"] == "PARTIAL_PRESENT"
    with pytest.raises(AutomationError) as e:
        recover_partial(world["roots"], world["request"].run_id, probe=LIVE, clock=ticking_clock())   # 生きた lock: ACTIVE
    assert e.value.public_code == "DUPLICATE_INVOCATION:RUN_ACTIVE" and partial.exists()
    outcome = recover_partial(world["roots"], world["request"].run_id, probe=DEAD, clock=ticking_clock())
    crashed = final_dir(world).with_name(final_dir(world).name + ".crashed")
    assert outcome["partial_class"] == "PARTIAL_ABANDONED" and outcome["recovery"] == "PARTIAL_PRESERVED_AND_CRASHED_RECORDED"
    assert not partial.exists() and (crashed / "request.json").read_bytes() == b"{}\n"
    assert ledger(world).open_verified().run_states[world["request"].run_id] is RunState.CRASHED
    assert commit(world, probe=DEAD).failure_code == "DUPLICATE_INVOCATION:RUN_TERMINAL"
    orphan_id = "e" * 64                                                                   # ledger に無い partial
    (root / "runs" / (orphan_id + ".partial")).mkdir()
    outcome = recover_partial(world["roots"], orphan_id, probe=DEAD, clock=ticking_clock())
    assert outcome["partial_class"] == "PARTIAL_ORPHAN" and (root / "runs" / (orphan_id + ".crashed")).is_dir()
    assert ledger(world).open_verified().summary.record_count == 3                         # ledger は増えない
    with pytest.raises(AutomationError) as e:
        recover_partial(world["roots"], orphan_id, probe=DEAD, clock=ticking_clock())
    assert e.value.public_code == "DUPLICATE_INVOCATION:PARTIAL_ABSENT"
    (root / "runs" / (orphan_id + ".partial")).mkdir()
    with pytest.raises(AutomationError) as e:
        recover_partial(world["roots"], orphan_id, probe=DEAD, clock=ticking_clock())
    assert e.value.public_code == "DUPLICATE_INVOCATION:CRASHED_EVIDENCE_EXISTS"            # 既存の証拠は上書きしない
    with pytest.raises(AutomationError) as e:
        recover_crashed(world["roots"], orphan_id, probe=DEAD, clock=ticking_clock())
    assert e.value.public_code == "DUPLICATE_INVOCATION:PARTIAL_PRESENT"


# ================================================================ retry ・cancel ・idempotency


def test_retry_sources_attempt_numbering_and_refusals(world) -> None:
    first = commit(world)
    state = ledger(world).open_verified()
    with pytest.raises(AutomationError) as e:
        build_retry_request(world["roots"], world["request"].run_id, state=state, probe=LIVE, operator="human")
    assert e.value.code == "ALREADY_SUCCEEDED"
    with pytest.raises(AutomationError) as e:
        build_retry_request(world["roots"], "f" * 64, state=state, probe=LIVE, operator="human")
    assert e.value.public_code == "DUPLICATE_INVOCATION:RUN_UNKNOWN"
    failed_request = AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": "slot-b", "runtime_anchor": "0" * 40})
    assert commit(world, failed_request).failure_code == "REPO_HEAD_MISMATCH"
    state = ledger(world).open_verified()
    retry = build_retry_request(world["roots"], failed_request.run_id, state=state, probe=LIVE, operator="human")
    assert (retry.attempt, retry.retry_of, retry.runtime_anchor, retry.slot_id) == (2, failed_request.run_id, "0" * 40, "slot-b")
    assert retry.scheduled_for == failed_request.scheduled_for and retry.schedule_digest == SCHEDULE_DIGEST
    assert commit(world, retry).failure_code == "REPO_HEAD_MISMATCH"                        # 同じ誤りでも新しい run
    state = ledger(world).open_verified()
    third = build_retry_request(world["roots"], failed_request.run_id, state=state, probe=LIVE, operator="human")
    assert third.attempt == 3 and third.retry_of == failed_request.run_id                    # 最大の attempt ＋ 1（1 を retry しても 2 は使わない）
    cancelled = AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": "slot-c"})
    write_cancel_request(world["roots"].p12_root, cancelled.run_id, operator="human", requested_at=datetime(2026, 7, 2, tzinfo=timezone.utc))
    assert commit(world, cancelled).failure_code == "CANCELLED"
    with pytest.raises(AutomationError) as e:
        build_retry_request(world["roots"], cancelled.run_id, state=ledger(world).open_verified(), probe=LIVE, operator="human")
    assert e.value.public_code == "DUPLICATE_INVOCATION:NOT_RETRYABLE_CANCELLED"
    crash_at(world, "AFTER_RUNNING_APPEND", AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": "slot-d"}))
    open_id = AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": "slot-d"}).run_id
    with pytest.raises(AutomationError) as e:
        build_retry_request(world["roots"], open_id, state=ledger(world).open_verified(), probe=LIVE, operator="human")
    assert e.value.public_code == "DUPLICATE_INVOCATION:RUN_ACTIVE"
    with pytest.raises(AutomationError) as e:
        build_retry_request(world["roots"], open_id, state=ledger(world).open_verified(), probe=DEAD, operator="human")
    assert e.value.public_code == "DUPLICATE_INVOCATION:RUN_OPEN"
    assert first.status == "SUCCEEDED" and tree(final_dir(world))                           # 前の run の directory は不変


def test_cooperative_cancel_commits_cancelled_between_steps_and_never_during_commit(world) -> None:
    root = world["roots"].p12_root
    with pytest.raises(AutomationError):
        write_cancel_request(root, world["request"].run_id, operator="scheduler", requested_at=datetime(2026, 7, 2, tzinfo=timezone.utc))
    document = write_cancel_request(root, world["request"].run_id, operator="human", requested_at=datetime(2026, 7, 2, tzinfo=timezone.utc))
    assert set(document) == {"schema_version", "run_id", "requested_at", "operator", "reason_code"}
    result = commit(world)
    assert (result.status, result.failure_code) == ("FAILED", "CANCELLED") and result.execution is None
    assert "LOCK_RELEASED" in result.stages_completed and "EXECUTED" not in result.stages_completed
    state = ledger(world).open_verified()
    assert [r.transition_to for r in state.records] == [RunState.PLANNED, RunState.CANCELLED] and not final_dir(world).exists()
    assert read_status(root)["projection"]["health_code"] == "CANCELLED"
    late = AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": "slot-b"})

    def request_cancel():
        write_cancel_request(root, late.run_id, operator="human", requested_at=datetime(2026, 7, 2, tzinfo=timezone.utc))
        return None

    result = commit(world, late, injection=RaisingInjection({"AFTER_RUNNING_APPEND": request_cancel}))
    assert result.failure_code == "CANCELLED" and result.execution is None
    assert [r.transition_to for r in ledger(world).open_verified().records[-3:]] == [RunState.PLANNED, RunState.RUNNING, RunState.CANCELLED]
    after = AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": "slot-c"})

    def request_cancel_after():
        write_cancel_request(root, after.run_id, operator="human", requested_at=datetime(2026, 7, 2, tzinfo=timezone.utc))
        return None

    result = commit(world, after, injection=RaisingInjection({"BEFORE_EXECUTION": request_cancel_after}))
    assert result.status == "SUCCEEDED"                                                    # 実行が始まった後の要求は commit を止めない
    cancel_file(root, "d" * 64).parent.mkdir(parents=True, exist_ok=True)
    malformed = AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": "slot-d"})
    cancel_file(root, malformed.run_id).write_text("{bad\n", encoding="utf-8")
    result = commit(world, malformed)
    assert result.failure_code == "SCHEMA_INVALID:CANCEL_MALFORMED" and "LOCK_RELEASED" in result.stages_completed


def test_repeated_commands_are_idempotent_without_overwrite(world) -> None:
    first = commit(world)
    before = tree(final_dir(world))
    for probe in (LIVE, DEAD):
        again = commit(world, probe=probe)
        assert (again.status, again.failure_code, again.stages_completed) == ("FAILED", "ALREADY_SUCCEEDED", ())
    assert tree(final_dir(world)) == before and ledger(world).open_verified().summary.record_count == 3
    assert request_file(world["roots"].p12_root, world["request"].run_id).read_bytes() == world["request"].to_bytes()
    assert first.ledger_head_digest == ledger(world).open_verified().summary.head_digest


# ================================================================ CLI ・process 間の race


def cli(world, *argv, environment=None):
    out = io.StringIO()
    code = run_cli.main(list(argv), stdout=out, environment={} if environment is None else environment)
    return code, out.getvalue()


def root_args(world):
    return ["--private-root", str(world["roots"].p12_root), "--p9-root", str(world["p9"]["root"]), "--p10-root", str(world["p10"]),
            "--repo-root", str(world["repo"]), "--runtime-root", str(REPO_ROOT)]


def test_the_cli_retry_and_recovery_commands_are_explicit_classified_and_safe(world) -> None:
    root = world["roots"].p12_root
    failed_request = AutomationExecutionRequest(**{**world["request"].__dict__, "runtime_anchor": "0" * 40})
    (world["tmp"] / "req.json").write_bytes(failed_request.to_bytes())
    code, text = cli(world, "run", "--request-file", str(world["tmp"] / "req.json"), *root_args(world))
    assert code == 1 and text.splitlines()[-1] == "REPORT: RUN_FAILED CODE=REPO_HEAD_MISMATCH"
    code, text = cli(world, "retry", "--run-id", failed_request.run_id, *root_args(world))
    lines = text.splitlines()
    assert code == 1 and lines[0] == f"REPORT: RETRY_OF={failed_request.run_id} ATTEMPT=2" and lines[1].startswith("REPORT: RUN_ID=")
    assert lines[-1] == "REPORT: RUN_FAILED CODE=REPO_HEAD_MISMATCH"
    code, text = cli(world, "retry", "--run-id", "f" * 64, *root_args(world))
    assert (code, text) == (1, "REPORT: RUN_FAILED CODE=DUPLICATE_INVOCATION:RUN_UNKNOWN\n")
    code, text = cli(world, "retry", "--run-id", failed_request.run_id, *root_args(world), environment={"JQUANTS_API_KEY": "x"})
    assert (code, text) == (1, "REPORT: RUN_FAILED CODE=CREDENTIAL_PRESENT\n")
    code, text = cli(world, "cancel", "--run-id", world["request"].run_id, "--private-root", str(root))
    assert (code, text) == (0, f"REPORT: CANCEL_REQUESTED RUN_ID={world['request'].run_id}\n")
    (world["tmp"] / "good.json").write_bytes(world["request"].to_bytes())
    code, text = cli(world, "run", "--request-file", str(world["tmp"] / "good.json"), *root_args(world))
    assert code == 1 and text.splitlines()[-1] == "REPORT: RUN_FAILED CODE=CANCELLED"
    code, text = cli(world, "recover-orphan", "--run-id", world["request"].run_id, "--private-root", str(root))
    assert code == 1 and "RUN_CLASSIFICATION" in text and text.splitlines()[-1] == "REPORT: RUN_FAILED CODE=DUPLICATE_INVOCATION:COMMITTED"
    code, text = cli(world, "repair-checkpoint", "--private-root", str(root))
    assert (code, text) == (1, "REPORT: RUN_FAILED CODE=DUPLICATE_INVOCATION:CHECKPOINT_NOT_STALE\n")
    code, text = cli(world, "regenerate-status", "--private-root", str(root))
    assert code == 0 and text.startswith("REPORT: RECOVERY STATUS_REGENERATED HEALTH=")
    code, text = cli(world, "release-lock", "--private-root", str(root))
    assert (code, text) == (0, "REPORT: LOCK LOCK_ABSENT RELEASED=NO\n")
    code, text = cli(world, "release-lock", "--private-root", str(root), "--run-id", world["request"].run_id)
    assert (code, text) == (0, "REPORT: LOCK LOCK_ABSENT RELEASED=NO\n")
    for blob in (text,):
        assert str(world["tmp"]) not in blob
    code, text = cli(world, "recover-partial", "--run-id", world["request"].run_id, "--private-root", str(root))
    assert code == 1 and text.splitlines()[-1] == "REPORT: RUN_FAILED CODE=DUPLICATE_INVOCATION:PARTIAL_ABSENT"


def _spawn(world, request_file: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("JQUANTS_")}
    return subprocess.Popen([sys.executable, "-m", "src.intelligence.automation.run_cli", "run", "--request-file", str(request_file),
                             *root_args(world)], cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def test_two_processes_racing_the_same_run_commit_exactly_once_and_the_ledger_stays_valid(world) -> None:
    (world["tmp"] / "same.json").write_bytes(world["request"].to_bytes())
    processes = [_spawn(world, world["tmp"] / "same.json") for _ in range(2)]
    outputs = [p.communicate(timeout=300) for p in processes]
    finals = [o.strip().splitlines()[-1] for o, _ in outputs]
    assert sorted(p.returncode for p in processes) == [0, 1] and all(e == "" for _, e in outputs)
    assert "REPORT: RUN_SUCCEEDED" in finals
    other = [f for f in finals if f != "REPORT: RUN_SUCCEEDED"][0]
    assert other in ("REPORT: RUN_FAILED CODE=DUPLICATE_INVOCATION:RUN_ACTIVE", "REPORT: RUN_FAILED CODE=ALREADY_SUCCEEDED",
                     "REPORT: RUN_FAILED CODE=DUPLICATE_INVOCATION:RUN_OPEN")
    state = ledger(world).open_verified()
    assert state.summary.record_count == 3 and state.run_states == {world["request"].run_id: RunState.SUCCEEDED}
    assert state.checkpoint.head_digest == state.summary.head_digest
    assert [p.name for p in (world["roots"].p12_root / "runs").iterdir()] == [world["request"].run_id]
    assert not list((world["roots"].p12_root / "locks").glob("*.lock"))


def test_two_processes_running_different_slots_both_commit_and_ledger_commits_serialize(world) -> None:
    second = AutomationExecutionRequest(**{**world["request"].__dict__, "slot_id": "slot-b"})
    (world["tmp"] / "a.json").write_bytes(world["request"].to_bytes())
    (world["tmp"] / "b.json").write_bytes(second.to_bytes())
    processes = [_spawn(world, world["tmp"] / "a.json"), _spawn(world, world["tmp"] / "b.json")]
    outputs = [p.communicate(timeout=300) for p in processes]
    assert [p.returncode for p in processes] == [0, 0], outputs
    assert all(o.strip().splitlines()[-1] == "REPORT: RUN_SUCCEEDED" for o, _ in outputs)
    state = ledger(world).open_verified()
    assert state.summary.record_count == 6 and set(state.run_states.values()) == {RunState.SUCCEEDED}
    assert set(state.run_states) == {world["request"].run_id, second.run_id} and [r.sequence for r in state.records] == list(range(6))
    assert state.checkpoint.record_count == 6 and state.checkpoint.head_digest == state.records[-1].record_digest
    assert sorted(p.name for p in (world["roots"].p12_root / "runs").iterdir()) == sorted([world["request"].run_id, second.run_id])
    assert read_status(world["roots"].p12_root)["ledger_record_count"] == 6 and not list((world["roots"].p12_root / "locks").glob("*.lock"))
    for name in ARTIFACT_NAMES:
        assert (final_dir(world) / name).is_file() and (final_dir(world, second) / name).is_file()
