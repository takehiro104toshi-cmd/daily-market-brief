"""P12-A2 — P11 の snapshot の導出 ・loopback の readiness ・原子的な finalize ・決定論の orchestrator ・privacy の test。

合成の P9 ／ P10 の世界（P10 ／ P11 の test と同じ builder）・tmp の git repo ・tmp の P12 root。本物の root ・network ・資格情報は無い。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.automation import finalization as fz
from src.intelligence.automation import run_executor as rx
from src.intelligence.automation.execution_request import AutomationExecutionRequest
from src.intelligence.automation.execution_result import AutomationExecutionResult
from src.intelligence.automation.failure_codes import AutomationError
from src.intelligence.automation.finalization import FINALIZED_PENDING_LEDGER, FinalizationOutcome, finalize_run
from src.intelligence.automation.frozen_anchors import P11_FROZEN_ANCHOR
from src.intelligence.automation.ledger_model import make_record, verify_chain
from src.intelligence.automation.network_deny import NetworkDenied, NetworkPolicy, network_guard
from src.intelligence.automation.preconditions import PrivateRoots
from src.intelligence.automation.run_executor import execute_run
from src.intelligence.automation.run_state import RunState
from src.intelligence.automation.schedule_model import TOKYO
from src.intelligence.automation.server_readiness import ReadinessReport, verify_server_readiness
from src.intelligence.automation.snapshot_orchestrator import AutomationSnapshot, build_snapshot
from src.intelligence.automation.source_manifests import build_root_manifest
from src.intelligence.automation.step_result import STEP_ORDER
from src.intelligence.personal_intelligence.attention_model import AttentionState, AttentionTargetKind
from src.intelligence.personal_intelligence.authority_stores import PersonalAuthorityStores
from src.intelligence.personal_intelligence.decisions import AttentionCreate, ProfileCreate
from src.intelligence.personal_intelligence.executor import apply_decision
from src.intelligence.personal_ui.p10_read_adapter import read_ui_model
from src.intelligence.personal_ui.ui_model import ui_model_json_bytes
from tests.intelligence.test_automation_preconditions import SCHEDULE_DIGEST, make_repo
from tests.intelligence.test_personal_intelligence_executor import build_p9, tree
from tests.intelligence.test_watchlist_thesis_semantics import HOUR, ISSUER2, T0

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHOR = "human:sentinel-author"
NOTE = "SENTINEL-HORIZON-NOTE"
REASON = "SENTINEL-EXCLUSION-REASON"
SCHEDULED_FOR = (T0 + 6 * HOUR).astimezone(TOKYO)                                   # 合成の世界の後の明示の瞬間
AS_OF = SCHEDULED_FOR.date()
CLOCK_INSTANT = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)
ARTIFACT_NAMES = ("digests.json", "evidence.json", "manifests.json", "readiness.json", "request.json", "snapshot.json",
                  "snapshot_metadata.json")


def build_world(tmp: Path) -> dict:
    p9 = build_p9(tmp / "p9_private_root")
    p10 = tmp / "p10_private_root"
    p10.mkdir()
    PersonalAuthorityStores.initialize(p10)
    at = T0 + 4 * HOUR
    apply_decision(ProfileCreate(author_ref=AUTHOR, reviewed_at=at, horizon_note=NOTE, liquidity_note="", risk_context_note="",
                                 review_lookahead_days=14, excluded_issuer_ids=(ISSUER2,), exclusion_reason_note=REASON),
                   p10_root=p10)
    apply_decision(AttentionCreate(target_kind=AttentionTargetKind.P9_WATCH_ENTRY, target_root_id=p9["w1"].watch_entry_id,
                                   observed_p9_revision_id=p9["w1b"].revision_id, state=AttentionState.FOCUS, author_ref=AUTHOR,
                                   reviewed_at=at), p10_root=p10, p9_root=p9["root"])
    sentinels = {NOTE, REASON, AUTHOR, ISSUER2, str(tmp), "SENTINEL", p9["w1"].watch_entry_id, p9["w1b"].revision_id,
                 p9["t1"].thesis_id, "Traceback", "p9wat_", "p10prf_", "p10att_", "human:"}
    return dict(p9=p9, p10=p10, sentinels=sentinels)


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    built = build_world(tmp_path)
    repo, head = make_repo(tmp_path / "repo")
    request = AutomationExecutionRequest(schedule_id="ops-daily", slot_id="slot-a", scheduled_for=SCHEDULED_FOR, as_of_date=AS_OF,
                                         session_date=AS_OF, runtime_anchor=head, attempt=1, operator="scheduler",
                                         schedule_digest=SCHEDULE_DIGEST)
    roots = PrivateRoots(built["p9"]["root"], built["p10"], tmp_path / "p12_private_root")
    before = (tree(built["p9"]["root"]), tree(built["p10"]))
    yield dict(request=request, roots=roots, repo=repo, head=head, tmp=tmp_path, **built)
    assert (tree(built["p9"]["root"]), tree(built["p10"])) == before                      # P9 ／ P10 は byte も mtime も不変


def run(world, **overrides) -> AutomationExecutionResult:
    args = dict(repo_root=world["repo"], runtime_root=REPO_ROOT, environment={}, clock=lambda: CLOCK_INSTANT)
    args.update(overrides)
    return execute_run(world["request"], world["roots"], **args)


def final_dir(world) -> Path:
    return world["roots"].p12_root / "runs" / world["request"].run_id


# ================================================================ snapshot


def test_snapshot_equals_the_direct_p11_model_and_counts_are_correct(world) -> None:
    snapshot = build_snapshot(world["request"], world["roots"])
    direct = read_ui_model(world["p10"], world["p9"]["root"], at=SCHEDULED_FOR, as_of_date=AS_OF)
    assert isinstance(snapshot, AutomationSnapshot) and snapshot.body == ui_model_json_bytes(direct)
    assert snapshot.entry_count == len(direct.entries) == 3
    assert snapshot.focus_count == sum(1 for e in direct.entries if e.attention == "FOCUS") == 1
    assert snapshot.mute_count == 0 and snapshot.excluded_count == 1 and snapshot.unmatched_live_marks == 0
    assert snapshot.p11_runtime_anchor == P11_FROZEN_ANCHOR and snapshot.run_id == world["request"].run_id
    assert snapshot.scheduled_for == "2026-07-01T06:00:00Z" and snapshot.as_of_date == "2026-07-01"
    safe = snapshot.to_safe_dict()
    assert "body" not in safe and "entries" not in json.dumps(safe) and repr(snapshot).count("run_id") == 1
    assert json.loads(snapshot.body)["at"] == "2026-07-01T06:00:00+00:00"                   # PIT は scheduled_for だけ
    again = build_snapshot(world["request"], world["roots"])
    assert again.body == snapshot.body and again.model_digest == snapshot.model_digest


def test_changed_source_changes_manifest_digest_and_snapshot_while_unchanged_source_is_stable(tmp_path: Path) -> None:
    built = build_world(tmp_path)                                                              # この test だけは P10 を意図して変える
    request = AutomationExecutionRequest(schedule_id="ops-daily", slot_id="slot-a", scheduled_for=SCHEDULED_FOR, as_of_date=AS_OF,
                                         session_date=AS_OF, runtime_anchor="a" * 40, attempt=1, operator="scheduler",
                                         schedule_digest=SCHEDULE_DIGEST)
    roots = PrivateRoots(built["p9"]["root"], built["p10"], tmp_path / "p12")
    p10_before = build_root_manifest(built["p10"], "P10")
    p9_before = build_root_manifest(built["p9"]["root"], "P9")
    snapshot_before = build_snapshot(request, roots)
    apply_decision(AttentionCreate(target_kind=AttentionTargetKind.P9_WATCH_ENTRY, target_root_id=built["p9"]["w2"].watch_entry_id,
                                   observed_p9_revision_id=built["p9"]["w2"].revision_id, state=AttentionState.MUTE,
                                   author_ref=AUTHOR, reviewed_at=T0 + 5 * HOUR), p10_root=built["p10"], p9_root=built["p9"]["root"])
    p10_after = build_root_manifest(built["p10"], "P10")
    snapshot_after = build_snapshot(request, roots)
    assert p10_after.content_digest != p10_before.content_digest and p10_after.byte_count > p10_before.byte_count
    assert snapshot_after.body != snapshot_before.body and snapshot_after.mute_count == 1 and snapshot_before.mute_count == 0
    assert build_root_manifest(built["p9"]["root"], "P9") == p9_before                         # 触っていない source は不変


def test_snapshot_failures_map_to_source_incomplete_with_p11_codes_only(world, tmp_path: Path) -> None:
    empty = tmp_path / "empty_p10"
    empty.mkdir()
    with pytest.raises(AutomationError) as e:
        build_snapshot(world["request"], PrivateRoots(world["p9"]["root"], empty, world["roots"].p12_root))
    assert e.value.code == "SOURCE_INCOMPLETE" and e.value.detail == "P10_UNAVAILABLE"
    assert str(tmp_path) not in str(e.value) and "SENTINEL" not in repr(e.value)
    with pytest.raises(AutomationError):
        build_snapshot("request", world["roots"])  # type: ignore[arg-type]


# ================================================================ server readiness


def test_server_readiness_probes_loopback_only_and_the_api_bytes_equal_the_snapshot(world) -> None:
    snapshot = build_snapshot(world["request"], world["roots"])
    with network_guard(NetworkPolicy(allow_loopback=True)) as guard:
        report = verify_server_readiness(world["roots"], world["request"], snapshot.body)
    assert isinstance(report, ReadinessReport) and report.probes_ok == ("HEALTH", "VERSION", "STATIC_SHELL", "API_VIEW")
    assert report.api_model_digest == snapshot.model_digest and report.api_matches_snapshot and guard.denied == 0
    assert set(report.to_dict()) == {"schema_version", "bind", "probes_ok", "api_model_digest", "api_matches_snapshot"}
    assert report.to_dict()["bind"] == "127.0.0.1" and "port" not in report.to_dict()
    with network_guard(NetworkPolicy(allow_loopback=True)):
        with pytest.raises(AutomationError) as e:
            verify_server_readiness(world["roots"], world["request"], snapshot.body[:-1] + b" ")
    assert e.value.public_code == "STEP_FAILED:API_MODEL_MISMATCH"
    with network_guard(NetworkPolicy(allow_loopback=False)):                                  # loopback さえ policy が無ければ拒む
        with pytest.raises(NetworkDenied):
            verify_server_readiness(world["roots"], world["request"], snapshot.body)
    assert socket.getaddrinfo("127.0.0.1", 80)                                                # guard は元に戻る


def test_server_readiness_refuses_a_present_credential_and_reports_startup_codes_only(world, monkeypatch) -> None:
    monkeypatch.setenv("JQUANTS_API_KEY", "SENTINEL-CREDENTIAL-VALUE")
    snapshot = build_snapshot(world["request"], world["roots"])
    with network_guard(NetworkPolicy(allow_loopback=True)):
        with pytest.raises(AutomationError) as e:
            verify_server_readiness(world["roots"], world["request"], snapshot.body)
    assert e.value.public_code == "STEP_FAILED:SERVER_CREDENTIAL_PRESENT" and "SENTINEL" not in repr(e.value)


# ================================================================ finalization


def test_finalization_writes_only_in_partial_then_renames_atomically(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "p12"
    run_id = "c" * 64
    artifacts = {"request.json": b'{"a":1}\n', "snapshot.json": b'{"b":2}\n'}
    final = root / "runs" / run_id
    partial = root / "runs" / (run_id + ".partial")
    seen = []
    real_write = fz._write_artifact

    def spy(target: Path, data: bytes) -> str:
        seen.append((target.parent.name, final.exists(), sorted(p.name for p in (root / "runs").iterdir())))
        return real_write(target, data)

    monkeypatch.setattr(fz, "_write_artifact", spy)
    outcome = finalize_run(root, run_id, artifacts)
    assert isinstance(outcome, FinalizationOutcome) and outcome.status == FINALIZED_PENDING_LEDGER and outcome.artifact_count == 3
    assert all(parent == run_id + ".partial" and not existed and names == [run_id + ".partial"] for parent, existed, names in seen)
    assert final.is_dir() and not partial.exists() and sorted(p.name for p in final.iterdir()) == ["digests.json", "request.json",
                                                                                                  "snapshot.json"]
    digests = json.loads((final / "digests.json").read_text(encoding="utf-8"))
    assert set(digests) == {"request.json", "snapshot.json"} and len(outcome.artifact_digests) == 3
    assert (final / "request.json").read_bytes() == artifacts["request.json"]
    assert "SUCCEEDED" not in json.dumps(outcome.to_dict()) and str(tmp_path) not in json.dumps(outcome.to_dict())


def test_finalization_fails_closed_on_existing_final_or_partial_and_never_overwrites(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    run_id = "d" * 64
    artifacts = {"request.json": b'{"a":1}\n'}
    finalize_run(root, run_id, artifacts)
    final = root / "runs" / run_id
    before = tree(final)
    with pytest.raises(AutomationError) as e:
        finalize_run(root, run_id, {"request.json": b'{"a":2}\n'})
    assert e.value.public_code == "DUPLICATE_INVOCATION:FINAL_EXISTS" and tree(final) == before
    assert not (root / "runs" / (run_id + ".partial")).exists()
    other = "e" * 64
    (root / "runs" / (other + ".partial")).mkdir()
    with pytest.raises(AutomationError) as e:
        finalize_run(root, other, artifacts)
    assert e.value.public_code == "DUPLICATE_INVOCATION:PARTIAL_EXISTS" and not (root / "runs" / other).exists()
    for bad, detail in (({}, "ARTIFACTS"), ({"Bad.json": b"{}\n"}, "ARTIFACT_NAME"), ({"digests.json": b"{}\n"}, "ARTIFACT_NAME"),
                        ({"x.json": b"{}"}, "ARTIFACT_BYTES"), ({"x.json": b"{}\r\n"}, "ARTIFACT_BYTES"), ({"x.json": "{}\n"}, "ARTIFACT_BYTES")):
        with pytest.raises(AutomationError) as e:
            finalize_run(root, "f" * 64, bad)
        assert e.value.detail == detail, detail
    with pytest.raises(AutomationError) as e:
        finalize_run(tmp_path / "no" / "parent" / "p12", "f" * 64, artifacts)
    assert e.value.public_code == "STEP_FAILED:FINALIZATION_IO" and str(tmp_path) not in str(e.value)


def test_finalization_io_failure_leaves_partial_evidence_and_no_final(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "p12"
    run_id = "a" * 64
    real_write = fz._write_artifact
    calls = []

    def failing(target: Path, data: bytes) -> str:
        calls.append(target.name)
        if len(calls) == 2:
            raise OSError("SENTINEL-OS-TEXT")
        return real_write(target, data)

    monkeypatch.setattr(fz, "_write_artifact", failing)
    with pytest.raises(AutomationError) as e:
        finalize_run(root, run_id, {"a.json": b"{}\n", "b.json": b"{}\n"})
    assert e.value.public_code == "STEP_FAILED:FINALIZATION_IO" and "SENTINEL" not in repr(e.value)
    assert not (root / "runs" / run_id).exists() and (root / "runs" / (run_id + ".partial")).is_dir()   # 証拠は残る（回復は A4）


# ================================================================ executor


def test_execute_run_finalizes_pending_ledger_with_all_steps_ok_and_safe_result(world) -> None:
    result = run(world)
    assert isinstance(result, AutomationExecutionResult) and result.status == FINALIZED_PENDING_LEDGER
    assert result.failure_code is None and [s.step_code for s in result.step_results] == list(STEP_ORDER)
    assert all(s.status == "OK" for s in result.step_results)
    assert result.run_id == world["request"].run_id and result.p11_runtime_anchor == P11_FROZEN_ANCHOR
    assert result.runtime_anchor == world["head"] and result.scheduled_for == "2026-07-01T06:00:00Z"
    assert set(result.source_manifest_digests) == {"P9", "P10", "P11_RUNTIME"}
    assert result.snapshot_metadata["entry_count"] == 3 and result.readiness["probes_ok"] == ["HEALTH", "VERSION", "STATIC_SHELL",
                                                                                               "API_VIEW"]
    assert result.step_results[2].artifact_digest == result.snapshot_metadata["model_digest"] == result.readiness["api_model_digest"]
    assert len(result.artifact_digests) == 7 and result.started_at == result.completed_at == "2026-07-02T00:00:00Z"
    final = final_dir(world)
    assert sorted(p.name for p in final.iterdir()) == list(ARTIFACT_NAMES)
    assert not (final.parent / (final.name + ".partial")).exists()
    digests = json.loads((final / "digests.json").read_text(encoding="utf-8"))
    import hashlib
    for name in ARTIFACT_NAMES[1:]:
        assert hashlib.sha256((final / name).read_bytes()).hexdigest() == digests[name]
    assert set(result.artifact_digests) == set(digests.values()) | {hashlib.sha256((final / "digests.json").read_bytes()).hexdigest()}
    assert (final / "snapshot.json").read_bytes() == ui_model_json_bytes(read_ui_model(world["p10"], world["p9"]["root"],
                                                                                        at=SCHEDULED_FOR, as_of_date=AS_OF)) + b"\n"
    assert json.loads((final / "request.json").read_text())["request_digest"] == result.request_digest
    evidence = json.loads((final / "evidence.json").read_text())
    assert evidence["status"] == FINALIZED_PENDING_LEDGER and [s["step_code"] for s in evidence["step_results"]] == list(STEP_ORDER[:4])
    text = result.to_json()
    assert "SUCCEEDED" not in text and "RUNNING" not in text and "PLANNED" not in text          # 成功は ledger の commit だけ
    assert json.loads(text)["telemetry"] == {"started_at": "2026-07-02T00:00:00Z", "completed_at": "2026-07-02T00:00:00Z"}
    assert "telemetry" not in result.semantic_dict() and "started_at" not in result.semantic_dict()
    assert sorted(p.name for p in world["roots"].p12_root.iterdir()) == ["runs"]                # runs/ だけ初期化する


def test_execute_run_result_feeds_the_a1_ledger_record_without_being_success_itself(world) -> None:
    result = run(world)
    planned = make_record(None, world["request"].run, transition_to=RunState.PLANNED, recorded_at="2026-07-01T06:00:30Z")
    running = make_record(planned, world["request"].run, transition_from=RunState.PLANNED, transition_to=RunState.RUNNING,
                          recorded_at="2026-07-01T06:00:31Z")
    succeeded = make_record(running, world["request"].run, transition_from=RunState.RUNNING, transition_to=RunState.SUCCEEDED,
                            recorded_at="2026-07-01T06:01:00Z", step_results=result.step_results,
                            artifact_digests=result.artifact_digests)
    assert verify_chain([planned, running, succeeded]).run_states == {result.run_id: RunState.SUCCEEDED}
    assert succeeded.artifact_digests == tuple(sorted(set(result.artifact_digests)))      # record の入力はそのまま使える


def test_execute_run_twice_fails_closed_on_the_existing_final_directory_without_overwrite(world) -> None:
    first = run(world)
    before = tree(final_dir(world))
    second = run(world)
    assert second.status == "FAILED" and second.failure_code == "DUPLICATE_INVOCATION:FINAL_EXISTS"
    assert [s.status for s in second.step_results] == ["OK", "OK", "OK", "OK", "FAILED"] and second.artifact_digests == ()
    assert tree(final_dir(world)) == before and first.semantic_dict()["artifact_digests"]
    assert not (final_dir(world).parent / (final_dir(world).name + ".partial")).exists()


def test_execute_run_is_deterministic_across_independent_roots_except_telemetry(world, tmp_path: Path) -> None:
    first = run(world, clock=lambda: CLOCK_INSTANT)
    other_root = tmp_path / "second_p12_root"
    world_b = dict(world, roots=PrivateRoots(world["roots"].p9_root, world["roots"].p10_root, other_root))
    second = run(world_b, clock=lambda: datetime(2026, 7, 3, 1, 2, 3, tzinfo=timezone.utc))
    assert first.semantic_dict() == second.semantic_dict() and first.to_dict() != second.to_dict()
    assert first.run_id == second.run_id and first.artifact_digests == second.artifact_digests
    dir_a, dir_b = final_dir(world), other_root / "runs" / first.run_id
    assert {p.name: p.read_bytes() for p in dir_a.iterdir()} == {p.name: p.read_bytes() for p in dir_b.iterdir()}
    third = run(dict(world, roots=PrivateRoots(world["roots"].p9_root, world["roots"].p10_root, tmp_path / "third")), clock=None)
    assert third.started_at is None and third.semantic_dict() == first.semantic_dict()


def test_execute_run_failure_stops_later_steps_deterministically_with_safe_codes(world, monkeypatch) -> None:
    wrong = AutomationExecutionRequest(**{**world["request"].__dict__, "runtime_anchor": "0" * 40})
    result = execute_run(wrong, world["roots"], repo_root=world["repo"], runtime_root=REPO_ROOT, environment={})
    assert result.status == "FAILED" and result.failure_code == "REPO_HEAD_MISMATCH"
    assert [(s.step_code, s.status) for s in result.step_results] == [("PRECONDITIONS", "FAILED")] + [
        (step, "SKIPPED") for step in STEP_ORDER[1:]]
    assert result.step_results[0].completeness_code == "PARTIAL" and result.preconditions_passed == ("REQUEST_IDENTITY",
                                                                                                   "CREDENTIAL_ABSENT", "NETWORK_POLICY")
    assert result.snapshot_metadata is None and result.readiness is None and result.artifact_digests == ()
    assert not world["roots"].p12_root.exists()                                                # 失敗では root さえ作らない
    assert run(world, environment={"JQUANTS_API_KEY": "SENTINEL-CREDENTIAL-VALUE"}).failure_code == "CREDENTIAL_PRESENT"
    missing = execute_run(world["request"], PrivateRoots(world["tmp"] / "absent", world["p10"], world["roots"].p12_root),
                          repo_root=world["repo"], runtime_root=REPO_ROOT, environment={})
    assert missing.failure_code == "ROOT_MISSING:P9"
    monkeypatch.setattr(rx, "build_snapshot", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("SENTINEL-UNEXPECTED")))
    unexpected = run(world)
    assert unexpected.failure_code == "STEP_FAILED:UNEXPECTED" and [s.status for s in unexpected.step_results] == [
        "OK", "OK", "FAILED", "SKIPPED", "SKIPPED"]
    assert "SENTINEL" not in unexpected.to_json() and not final_dir(world).exists()


def test_execute_run_denies_external_network_during_steps_and_allows_loopback_only_for_readiness(world, monkeypatch) -> None:
    def outbound(*_a, **_k):
        socket.create_connection(("203.0.113.1", 80), timeout=1)

    monkeypatch.setattr(rx, "build_snapshot", outbound)
    result = run(world)
    assert result.failure_code == "INTERRUPTED:NETWORK_DENIED" and result.step_results[2].status == "FAILED"
    monkeypatch.undo()

    def loopback_in_manifests(root, source_id):                                                # readiness 以外では loopback も拒む
        socket.getaddrinfo("127.0.0.1", 80)
        return build_root_manifest(root, source_id)

    monkeypatch.setattr(rx, "build_root_manifest", loopback_in_manifests)
    assert run(world).failure_code == "INTERRUPTED:NETWORK_DENIED"
    monkeypatch.undo()
    assert run(world).status == FINALIZED_PENDING_LEDGER
    assert socket.getaddrinfo("127.0.0.1", 80) and "connect" not in vars(socket.socket)


# ================================================================ privacy


def test_safe_result_and_private_artifacts_carry_no_paths_sentinels_exception_text_or_authority_dumps(world) -> None:
    result = run(world)
    safe = result.to_json()
    for sentinel in world["sentinels"]:
        assert sentinel not in safe, sentinel
    assert "/" not in safe.replace("p12_execution_result:0.1.0", "").replace("p12_automation_snapshot:0.1.0", "").replace(
        "p12_server_readiness:0.1.0", "").replace("p12_p11_read_adapter", "").replace("p11_p10_read_adapter:0.1.0", "").replace(
        "p11_ui_model:0.1.0", "")
    final = final_dir(world)
    for name in ARTIFACT_NAMES:
        text = (final / name).read_text(encoding="utf-8")
        assert text.endswith("\n") and "\r" not in text and str(world["tmp"]) not in text, name
        for sentinel in world["sentinels"] - {"human:"} if name == "snapshot.json" else world["sentinels"]:
            assert sentinel not in text, (name, sentinel)
        assert "Traceback" not in text and "Exception" not in text
    manifests = json.loads((final / "manifests.json").read_text(encoding="utf-8"))
    for source in ("P9", "P10"):
        for entry in manifests[source]["files"]:
            assert not entry["name"].startswith("/") and ":" not in entry["name"] and set(entry) == {"name", "size", "sha256"}
    raw_p10 = b"".join(p.read_bytes() for p in sorted(world["p10"].rglob("*")) if p.is_file())
    for name in ARTIFACT_NAMES:
        assert (final / name).read_bytes() not in raw_p10 and raw_p10[:64] not in (final / name).read_bytes()
    assert not any(p.name == "output" or p.name == "docs" for p in world["roots"].p12_root.iterdir())
    assert subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.count(
        "src/intelligence/automation") <= 11 + 10                                             # repo を書かない（自分の untracked の file だけ）
