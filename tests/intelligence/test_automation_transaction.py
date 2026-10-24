"""P12-A3 — 運用の transaction（A2 → finalize → ledger の commit → status）・crash の窓 ・重複 ・手の CLI ・privacy ・決定論の test。

合成の世界 ・tmp の git repo ・tmp の P12 root。crash は commit の境界で例外を注入して模す（process の死と同じ: 捕らえない）。
"""
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
from src.intelligence.automation import run_transaction as rt
from src.intelligence.automation.process_probe import StaticProbe
from src.intelligence.automation.recovery import release_lock
from src.intelligence.automation.execution_request import AutomationExecutionRequest
from src.intelligence.automation.head_checkpoint import HeadCheckpoint
from src.intelligence.automation.ledger_store import LedgerStore
from src.intelligence.automation.preconditions import PrivateRoots
from src.intelligence.automation.run_state import RunState
from src.intelligence.automation.run_transaction import STAGES, TransactionResult, classify_after_crash, commit_run
from src.intelligence.automation.status_store import read_status, status_file, write_status
from tests.intelligence.test_automation_executor import ARTIFACT_NAMES, AS_OF, SCHEDULED_FOR, build_world
from tests.intelligence.test_automation_models import calendar, schedule
from tests.intelligence.test_automation_preconditions import SCHEDULE_DIGEST, make_repo
from tests.intelligence.test_personal_intelligence_executor import tree

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_INSTANT = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)


class InjectedCrash(RuntimeError):
    """process の死の模し（AutomationError ではないので transaction は捕らえない）。"""


def ticking_clock(start: datetime = BASE_INSTANT):
    state = {"t": start}

    def clock() -> datetime:
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return clock


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
    assert (tree(built["p9"]["root"]), tree(built["p10"])) == before                      # P9 ／ P10 は不変


def commit(world, **overrides) -> TransactionResult:
    args = dict(repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
    args.update(overrides)
    return commit_run(world["request"], world["roots"], **args)


def store_of(world) -> LedgerStore:
    return LedgerStore(world["roots"].p12_root)


def final_dir(world) -> Path:
    return world["roots"].p12_root / "runs" / world["request"].run_id


def classify(world) -> str:
    return classify_after_crash(world["roots"], world["request"].run_id)["classification"]


# ================================================================ normal


def test_a_clean_first_run_commits_and_only_the_validated_ledger_record_establishes_success(world) -> None:
    result = commit(world)
    assert result.status == "SUCCEEDED" and result.failure_code is None and result.stages_completed == STAGES
    assert result.ledger_record_count == 3 and result.status_projection_written and result.execution.status == "FINALIZED_PENDING_LEDGER"
    state = store_of(world).open_verified()
    assert [r.transition_to for r in state.records] == [RunState.PLANNED, RunState.RUNNING, RunState.SUCCEEDED]
    assert state.run_states == {world["request"].run_id: RunState.SUCCEEDED} and state.checkpoint == HeadCheckpoint.of(state.records)
    assert state.summary.head_digest == result.ledger_head_digest == json.loads(store_of(world).checkpoint_file.read_text())["head_digest"]
    assert state.records[2].artifact_digests == tuple(sorted(result.execution.artifact_digests))
    assert state.records[2].step_results == result.execution.step_results and state.records[2].failure_code is None
    status = read_status(world["roots"].p12_root)
    assert status["ledger_head_digest"] == state.summary.head_digest and status["projection"]["health_code"] == "OK"
    assert status["projection"]["last_successful_run"]["run_id"] == world["request"].run_id
    assert classify(world) == "COMMITTED" and final_dir(world).is_dir()
    assert sorted(p.name for p in world["roots"].p12_root.iterdir()) == ["ledger", "locks", "requests", "runs", "status"]   # A4: lock ・要求の証拠
    assert not any(world["roots"].p12_root.joinpath("locks").iterdir())                    # lock は解放済み
    text = json.dumps(result.to_dict())
    assert "SUCCEEDED" in text and str(world["tmp"]) not in text
    recorded = [r.recorded_at for r in state.records]
    assert recorded == sorted(recorded) and recorded[0] > "2026-07-02T00:00:00Z"            # telemetry は注入した時計から（lock の後）


def test_a_failed_execution_is_committed_as_failed_with_the_safe_code_and_no_artifacts(world) -> None:
    wrong = AutomationExecutionRequest(**{**world["request"].__dict__, "runtime_anchor": "0" * 40})
    result = commit_run(wrong, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
    assert result.status == "FAILED" and result.failure_code == "REPO_HEAD_MISMATCH" and result.stages_completed == STAGES
    state = store_of(world).open_verified()
    assert state.run_states == {wrong.run_id: RunState.FAILED} and state.records[2].failure_code == "REPO_HEAD_MISMATCH"
    assert state.records[2].artifact_digests == () and not (world["roots"].p12_root / "runs").exists()
    assert read_status(world["roots"].p12_root)["projection"]["health_code"] == "FAILED"
    assert classify_after_crash(world["roots"], wrong.run_id)["classification"] == "COMMITTED"
    retry = AutomationExecutionRequest(**{**wrong.__dict__, "runtime_anchor": world["head"], "attempt": 2, "retry_of": wrong.run_id})
    again = commit_run(retry, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
    assert again.status == "SUCCEEDED" and store_of(world).open_verified().summary.record_count == 6   # retry は新しい run


# ================================================================ ledger faults before orchestration


def test_an_invalid_ledger_fails_closed_before_any_orchestration_and_is_never_repaired(world) -> None:
    first = commit(world)
    store = store_of(world)
    good_text, good_head = store.ledger_file.read_bytes(), store.checkpoint_file.read_bytes()
    lines = good_text.decode("utf-8").split("\n")[:-1]
    retry = AutomationExecutionRequest(**{**world["request"].__dict__, "attempt": 2})
    cases = {
        "RECORD_NOT_JSON": ("\n".join([lines[0], "{bad", lines[2]]) + "\n", None),
        "RECORD_DIGEST_MISMATCH": ("\n".join([lines[0], lines[1].replace('"attempt":1', '"attempt":2'), lines[2]]) + "\n", None),
        "SEQUENCE_BREAK": ("\n".join([lines[0], lines[2]]) + "\n", None),
        "TAIL_TRUNCATED": ("\n".join(lines[:2]) + "\n", None),
        "CHECKPOINT_MISMATCH": (None, HeadCheckpoint(3, "f" * 64).to_bytes()),
        "CHECKPOINT_MALFORMED": (None, b'{"x":1}\n'),
        "CHECKPOINT_STALE": (None, HeadCheckpoint.of(store.open_verified().records[:2]).to_bytes()),
        "LEDGER_NOT_LF": (good_text.decode("utf-8").replace("\n", "\r\n"), None),              # CRLF ledger stays refused
    }
    for detail, (ledger_text, head_bytes) in cases.items():
        if ledger_text is not None:
            store.ledger_file.write_bytes(ledger_text.encode("utf-8"))                    # explicit bytes (A6: Windows text mode writes CRLF)
            assert (b"\r" in store.ledger_file.read_bytes()) == (detail == "LEDGER_NOT_LF")
        if head_bytes is not None:
            store.checkpoint_file.write_bytes(head_bytes)
        before = (store.ledger_file.read_bytes(), store.checkpoint_file.read_bytes())
        result = commit_run(retry, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
        assert (result.status, result.failure_code, result.stages_completed) == ("FAILED", f"LEDGER_INVALID:{detail}", ()), detail
        assert (store.ledger_file.read_bytes(), store.checkpoint_file.read_bytes()) == before    # 修復 ・切り捨て ・書き換えなし
        assert not (world["roots"].p12_root / "runs" / retry.run_id).exists()
        store.ledger_file.write_bytes(good_text)
        store.checkpoint_file.write_bytes(good_head)
    store.checkpoint_file.unlink()                                                        # 無い checkpoint ＋ record あり ＝ 遅れ
    result = commit_run(retry, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
    assert result.failure_code == "LEDGER_INVALID:CHECKPOINT_STALE"
    assert classify(world) == "LEDGER_COMMITTED_CHECKPOINT_STALE"
    store.checkpoint_file.write_bytes(good_head)
    assert classify(world) == "COMMITTED" and first.status == "SUCCEEDED"
    status_file(world["roots"].p12_root).write_text(json.dumps({"projection": {"health_code": "OK"}}) + "\n")   # status は authority でない
    store.ledger_file.write_bytes(("\n".join([lines[0], lines[2]]) + "\n").encode("utf-8"))      # explicit LF bytes
    assert commit_run(retry, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={},
                      clock=ticking_clock()).failure_code == "LEDGER_INVALID:SEQUENCE_BREAK"
    assert classify_after_crash(world["roots"], retry.run_id)["classification"] == "LEDGER_INVALID:SEQUENCE_BREAK"


# ================================================================ crash windows


def test_crash_window_a_after_artifact_rename_before_terminal_append_is_orphaned_finalization(world, monkeypatch) -> None:
    real = rt.execute_run

    def crash_after_finalize(*args, **kwargs):
        result = real(*args, **kwargs)
        assert result.status == "FINALIZED_PENDING_LEDGER"
        raise InjectedCrash()

    monkeypatch.setattr(rt, "execute_run", crash_after_finalize)
    with pytest.raises(InjectedCrash):
        commit(world)
    monkeypatch.undo()
    state = store_of(world).open_verified()
    assert state.run_states == {world["request"].run_id: RunState.RUNNING} and final_dir(world).is_dir()
    assert classify(world) == "ORPHANED_FINALIZATION"
    evidence = classify_after_crash(world["roots"], world["request"].run_id)
    assert evidence["ledger_state"] == "RUNNING" and evidence["final_present"] and not evidence["partial_present"]
    before = tree(final_dir(world))
    again = commit(world)                                                                 # 再実行は上書きせず分類で止まる
    assert (again.status, again.failure_code, again.stages_completed) == ("FAILED", "ORPHANED_FINALIZATION", ())
    assert tree(final_dir(world)) == before and store_of(world).open_verified().summary.record_count == 2
    assert read_status(world["roots"].p12_root) is None                                   # 成功の status は生まれない


def test_crash_window_b_after_ledger_append_before_checkpoint_replace_is_checkpoint_stale(world, monkeypatch) -> None:
    real = ls.LedgerStore.write_checkpoint
    calls = []

    def crash_on_terminal(self, records):
        calls.append(len(records))
        if len(records) == 3:
            raise InjectedCrash()
        return real(self, records)

    monkeypatch.setattr(ls.LedgerStore, "write_checkpoint", crash_on_terminal)
    with pytest.raises(InjectedCrash):
        commit(world)
    monkeypatch.undo()
    monkeypatch.setattr(lc, "LEDGER_LOCK_WAIT_SECONDS", 0.5)                               # undo は fixture の短い待ちも戻すので再設定
    store = store_of(world)
    stale = store.open_verified(allow_stale_checkpoint=True)
    assert stale.summary.record_count == 3 and stale.run_states == {world["request"].run_id: RunState.SUCCEEDED}
    assert stale.checkpoint.record_count == 2 and stale.checkpoint_class == "CHECKPOINT_STALE"
    assert classify(world) == "LEDGER_COMMITTED_CHECKPOINT_STALE" and final_dir(world).is_dir()
    before = (store.ledger_file.read_bytes(), store.checkpoint_file.read_bytes(), tree(final_dir(world)))
    locked = commit(world)                                                                # A4: ledger lock の中で死んだ → lock が残る
    assert locked.failure_code == "DUPLICATE_INVOCATION:LEDGER_LOCKED" and locked.stages_completed == ()
    assert release_lock(world["roots"], probe=StaticProbe({os.getpid(): False}, {}, boot=None))["released"]
    again = commit(world)
    assert again.failure_code == "LEDGER_INVALID:CHECKPOINT_STALE" and again.stages_completed == ()
    assert (store.ledger_file.read_bytes(), store.checkpoint_file.read_bytes(), tree(final_dir(world))) == before


def test_crash_window_c_after_checkpoint_before_status_write_is_status_stale_and_regenerable(world, monkeypatch) -> None:
    monkeypatch.setattr(rt, "write_status", lambda *a, **k: (_ for _ in ()).throw(InjectedCrash()))
    with pytest.raises(InjectedCrash):
        commit(world)
    monkeypatch.undo()
    state = store_of(world).open_verified()
    assert state.run_states == {world["request"].run_id: RunState.SUCCEEDED} and state.checkpoint_class == "CHECKPOINT_OK"
    assert read_status(world["roots"].p12_root) is None and classify(world) == "STATUS_STALE"
    again = commit(world)
    assert again.failure_code == "ALREADY_SUCCEEDED" and store_of(world).open_verified().summary.record_count == 3   # ledger が authority
    write_status(world["roots"].p12_root, state, runtime_anchor=world["head"], schedule_id="ops-daily", as_of=BASE_INSTANT)
    assert classify(world) == "COMMITTED" and read_status(world["roots"].p12_root)["projection"]["health_code"] == "OK"


def test_crash_window_d_after_status_write_before_cli_return_leaves_a_committed_run(world, monkeypatch) -> None:
    request_file = world["tmp"] / "request.json"
    request_file.write_bytes(world["request"].to_bytes())
    real = run_cli._report

    def crash_on_final_line(stdout, line):
        if line == "RUN_SUCCEEDED":
            raise InjectedCrash()
        real(stdout, line)

    monkeypatch.setattr(run_cli, "_report", crash_on_final_line)
    out = io.StringIO()
    with pytest.raises(InjectedCrash):
        cli(world, request_file, out)
    monkeypatch.undo()
    assert "REPORT: STATUS_PROJECTION_OK" in out.getvalue() and "RUN_SUCCEEDED" not in out.getvalue()
    assert classify(world) == "COMMITTED"
    assert cli(world, request_file, io.StringIO())[0] == 1                                # 2 回目は ALREADY_SUCCEEDED


# ================================================================ duplicates


def test_duplicates_fail_closed_deterministically_without_overwriting_evidence(world) -> None:
    from src.intelligence.automation.run_executor import execute_run
    first = commit(world)
    before = tree(final_dir(world))
    again = commit(world)
    assert (again.status, again.failure_code, again.stages_completed) == ("FAILED", "ALREADY_SUCCEEDED", ())
    assert tree(final_dir(world)) == before and store_of(world).open_verified().summary.record_count == 3
    orphan = AutomationExecutionRequest(**{**world["request"].__dict__, "attempt": 2})
    execute_run(orphan, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={})   # ledger 無しの final
    orphan_dir = world["roots"].p12_root / "runs" / orphan.run_id
    before_orphan = tree(orphan_dir)
    result = commit_run(orphan, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
    assert (result.status, result.failure_code) == ("FAILED", "ORPHANED_FINALIZATION") and tree(orphan_dir) == before_orphan
    assert classify_after_crash(world["roots"], orphan.run_id)["classification"] == "ORPHANED_FINALIZATION"
    partial = AutomationExecutionRequest(**{**world["request"].__dict__, "attempt": 3})
    (world["roots"].p12_root / "runs" / (partial.run_id + ".partial")).mkdir()
    result = commit_run(partial, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
    assert result.failure_code == "DUPLICATE_INVOCATION:PARTIAL_EXISTS"
    assert classify_after_crash(world["roots"], partial.run_id)["classification"] == "PARTIAL_PRESENT"
    assert store_of(world).open_verified().summary.record_count == 3 and first.status == "SUCCEEDED"


# ================================================================ CLI


def cli(world, request_file: Path, out, environment=None, private_root=None):
    argv = ["run", "--request-file", str(request_file), "--private-root", str(private_root or world["roots"].p12_root),
            "--p9-root", str(world["p9"]["root"]), "--p10-root", str(world["p10"]), "--repo-root", str(world["repo"]),
            "--runtime-root", str(REPO_ROOT)]
    return run_cli.main(argv, stdout=out, environment={} if environment is None else environment), out.getvalue()


def test_the_manual_cli_commits_one_explicit_run_and_prints_only_safe_report_lines(world) -> None:
    request_file = world["tmp"] / "request.json"
    request_file.write_bytes(world["request"].to_bytes())
    code, text = cli(world, request_file, io.StringIO())
    lines = text.splitlines()
    assert code == 0 and all(line.startswith("REPORT: ") for line in lines)
    assert lines[0] == f"REPORT: RUN_ID={world['request'].run_id}" and lines[-1] == "REPORT: RUN_SUCCEEDED"
    assert "REPORT: STEP PRECONDITIONS OK" in lines and "REPORT: STEP FINALIZATION OK" in lines
    assert "REPORT: STATUS_PROJECTION_OK" in lines and any(line.startswith("REPORT: LEDGER_COMMIT_OK RECORDS=3 HEAD=") for line in lines)
    for sentinel in world["sentinels"] | {str(world["tmp"]), "Traceback", "/"}:
        assert sentinel not in text.replace("REPORT: ", ""), sentinel
    code, text = cli(world, request_file, io.StringIO())
    assert code == 1 and text.splitlines()[-1] == "REPORT: RUN_FAILED CODE=ALREADY_SUCCEEDED"
    state = store_of(world).open_verified()
    assert state.summary.record_count == 3 and all(r.recorded_at.endswith("Z") for r in state.records)   # telemetry は CLI の時計


def test_the_cli_refuses_credentials_non_human_operators_bad_input_and_usage_before_orchestration(world) -> None:
    request_file = world["tmp"] / "request.json"
    request_file.write_bytes(world["request"].to_bytes())
    code, text = cli(world, request_file, io.StringIO(), environment={"JQUANTS_API_KEY": "SENTINEL-CREDENTIAL-VALUE"})
    assert (code, text) == (1, "REPORT: RUN_FAILED CODE=CREDENTIAL_PRESENT\n") and not world["roots"].p12_root.exists()
    code, text = cli(world, request_file, io.StringIO(), environment={"JQUANTS_LATER_TOKEN": "x"})
    assert code == 1 and "CREDENTIAL_PRESENT" in text and not world["roots"].p12_root.exists()
    scheduler = AutomationExecutionRequest(**{**world["request"].__dict__, "operator": "scheduler"})
    (world["tmp"] / "sched.json").write_bytes(scheduler.to_bytes())
    code, text = cli(world, world["tmp"] / "sched.json", io.StringIO())
    assert code == 1 and text.splitlines()[-1] == "REPORT: RUN_FAILED CODE=SCHEMA_INVALID:OPERATOR_NOT_HUMAN"
    assert not world["roots"].p12_root.exists()
    (world["tmp"] / "bad.json").write_text("{not json", encoding="utf-8")
    code, text = cli(world, world["tmp"] / "bad.json", io.StringIO())
    assert (code, text) == (1, "REPORT: RUN_FAILED CODE=SCHEMA_INVALID:INPUT_FILE_NOT_JSON\n")
    tampered = json.loads(world["request"].to_json())
    tampered["as_of_date"] = "2026-07-02"
    (world["tmp"] / "tampered.json").write_text(json.dumps(tampered), encoding="utf-8")
    code, text = cli(world, world["tmp"] / "tampered.json", io.StringIO())
    assert code == 1 and "CODE=SCHEMA_INVALID:" in text and str(world["tmp"]) not in text
    code, text = cli(world, world["tmp"] / "absent.json", io.StringIO())
    assert (code, text) == (1, "REPORT: RUN_FAILED CODE=SCHEMA_INVALID:INPUT_FILE_UNREADABLE\n")
    err = io.StringIO()
    sys_stderr, sys.stderr = sys.stderr, err
    try:
        assert run_cli.main(["run", "--request-file", "x"], stdout=io.StringIO(), environment={}) == 2
        assert run_cli.main([], stdout=io.StringIO(), environment={}) == 2
    finally:
        sys.stderr = sys_stderr


def test_the_cli_writes_authorities_human_only_classifies_runs_and_runs_as_a_module(world) -> None:
    root = world["roots"].p12_root
    s1, c1 = schedule(), calendar()
    (world["tmp"] / "schedule.json").write_bytes((s1.to_json() + "\n").encode())
    (world["tmp"] / "calendar.json").write_bytes((c1.to_json() + "\n").encode())
    out = io.StringIO()
    assert run_cli.main(["write-schedule", "--file", str(world["tmp"] / "schedule.json"), "--private-root", str(root)], stdout=out,
                        environment={}) == 0
    assert out.getvalue() == f"REPORT: SCHEDULE_AUTHORITY_WRITTEN DIGEST={s1.content_digest}\n"
    out = io.StringIO()
    assert run_cli.main(["write-calendar", "--file", str(world["tmp"] / "calendar.json"), "--private-root", str(root)], stdout=out,
                        environment={}) == 0
    assert out.getvalue() == f"REPORT: CALENDAR_AUTHORITY_WRITTEN DIGEST={c1.content_digest}\n"
    assert (root / "authority" / "schedule.json").read_text() == s1.to_json() + "\n"
    out = io.StringIO()
    assert run_cli.main(["write-schedule", "--file", str(world["tmp"] / "schedule.json"), "--private-root", str(root)], stdout=out,
                        environment={}) == 0                                                 # 同じ内容は無害
    (world["tmp"] / "s2.json").write_bytes((schedule(version=2).to_json() + "\n").encode())
    out = io.StringIO()
    assert run_cli.main(["write-schedule", "--file", str(world["tmp"] / "s2.json"), "--private-root", str(root)], stdout=out,
                        environment={}) == 1
    assert out.getvalue() == "REPORT: RUN_FAILED CODE=SCHEMA_INVALID:SUPERSEDES_REQUIRED\n"
    commit(world)
    out = io.StringIO()
    assert run_cli.main(["classify", "--run-id", world["request"].run_id, "--private-root", str(root)], stdout=out, environment={}) == 0
    assert out.getvalue() == f"REPORT: RUN_CLASSIFICATION RUN_ID={world['request'].run_id} CLASS=COMMITTED\n"
    env = {k: v for k, v in os.environ.items() if not k.startswith("JQUANTS_")}
    completed = subprocess.run([sys.executable, "-m", "src.intelligence.automation.run_cli", "classify", "--run-id", "f" * 64,
                                "--private-root", str(root)], cwd=REPO_ROOT, capture_output=True, text=True, env=env, timeout=120)
    assert completed.returncode == 0 and completed.stdout == f"REPORT: RUN_CLASSIFICATION RUN_ID={'f' * 64} CLASS=NOT_STARTED\n"
    assert completed.stderr == ""


# ================================================================ privacy ・determinism


def test_ledger_status_and_stdout_carry_no_paths_private_payloads_exception_text_or_credentials(world) -> None:
    request_file = world["tmp"] / "request.json"
    request_file.write_bytes(world["request"].to_bytes())
    code, text = cli(world, request_file, io.StringIO())
    assert code == 0
    root = world["roots"].p12_root
    ledger_text = (root / "ledger" / "ledger.jsonl").read_text(encoding="utf-8")
    status_text = status_file(root).read_text(encoding="utf-8")
    for blob in (text, ledger_text, status_text, (root / "ledger" / "head.json").read_text(encoding="utf-8")):
        for sentinel in world["sentinels"] | {str(world["tmp"]), "Traceback", "Exception", "payload", "note", "D:\\", "/home/"}:
            assert sentinel not in blob, sentinel
    for line in ledger_text.splitlines():
        record = json.loads(line)
        assert set(record) >= {"record_digest", "previous_record_digest", "run_id", "status"} and "body" not in record
        assert all(not isinstance(v, str) or "/" not in v for v in record.values() if not isinstance(v, (list, dict)))
    raw_p10 = b"".join(p.read_bytes() for p in sorted(world["p10"].rglob("*")) if p.is_file())
    assert ledger_text.encode() not in raw_p10 and raw_p10[:64] not in ledger_text.encode() and raw_p10[:64] not in status_text.encode()
    assert "SUCCEEDED" in status_text and "/" not in json.dumps(read_status(root)["projection"])


def test_identical_transactions_in_independent_roots_are_byte_identical_except_telemetry(world, tmp_path: Path) -> None:
    first = commit(world, clock=ticking_clock())
    other = PrivateRoots(world["roots"].p9_root, world["roots"].p10_root, tmp_path / "second_root")
    second = commit_run(world["request"], other, repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=ticking_clock())
    assert first.status == second.status == "SUCCEEDED" and first.ledger_head_digest == second.ledger_head_digest   # 同じ時計 → 同じ鎖
    a, b = world["roots"].p12_root, tmp_path / "second_root"
    for relative in ("ledger/ledger.jsonl", "ledger/head.json", "status/status.json", *(f"runs/{first.run_id}/{n}" for n in ARTIFACT_NAMES)):
        assert (a / relative).read_bytes() == (b / relative).read_bytes(), relative
    third_root = PrivateRoots(world["roots"].p9_root, world["roots"].p10_root, tmp_path / "third_root")
    third = commit_run(world["request"], third_root, repo_root=world["repo"], runtime_root=REPO_ROOT, environment={},
                       clock=ticking_clock(BASE_INSTANT + timedelta(days=1)))
    assert third.ledger_head_digest != first.ledger_head_digest                            # 違う telemetry → 違う digest（意味は同じ）
    for relative in (f"runs/{first.run_id}/{n}" for n in ARTIFACT_NAMES):
        assert (a / relative).read_bytes() == (tmp_path / "third_root" / relative).read_bytes(), relative
    strip = ("recorded_at", "record_digest", "previous_record_digest")
    for x, y in zip((a / "ledger" / "ledger.jsonl").read_text().splitlines(), (tmp_path / "third_root" / "ledger" / "ledger.jsonl").read_text().splitlines()):
        assert {k: v for k, v in json.loads(x).items() if k not in strip} == {k: v for k, v in json.loads(y).items() if k not in strip}
    assert first.execution.semantic_dict() == third.execution.semantic_dict()
