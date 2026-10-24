"""P9-A4 — 人の判断の実行器 ・private な安全な投影 ・見直しの日の報告の test（合成の P8 ／ P9 の root だけ ・network なし）。"""
from __future__ import annotations

import dataclasses
import http.client
import json
import socket
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence import jquants_local_transport as lt
from src.intelligence.screener_intelligence.jquants_live_client import JQuantsLiveClient
from src.intelligence.screener_intelligence.jquants_live_model import TransportResponse
from src.intelligence.watchlist_thesis_intelligence import local_cli
from src.intelligence.watchlist_thesis_intelligence import projection as pj
from src.intelligence.watchlist_thesis_intelligence.authority_stores import AuthorityStores
from src.intelligence.watchlist_thesis_intelligence.decision_model import (DECISION_SCHEMA_VERSION, ConditionInput,
                                                                           DecisionKind, ThesisContent, ThesisCreate,
                                                                           ThesisUpdate, WatchCreateFromProposal,
                                                                           WatchCreateManual, WatchUpdate,
                                                                           decision_from_dict)
from src.intelligence.watchlist_thesis_intelligence.executor import ExecutorError, HumanDecisionExecutor
from src.intelligence.watchlist_thesis_intelligence.p8_handoff import reconstruct_completed_run
from src.intelligence.watchlist_thesis_intelligence.p8_identity import ISSUER_RECORD_SEMANTICS
from src.intelligence.watchlist_thesis_intelligence.proposal_model import watch_proposals
from src.intelligence.watchlist_thesis_intelligence.store_io import AuthorityStoreError, StoreFailureCategory
from src.intelligence.watchlist_thesis_intelligence.thesis_model import (HumanNoteEvidence, InvalidationBasis,
                                                                          P8ScreenEvidence, ThesisStatus)
from src.intelligence.watchlist_thesis_intelligence.watch_model import ProvenanceKind, WatchStatus
from tests.intelligence.test_screener_multi_issuer_executor import (ACQ, authorities, fins, identity, master, run,
                                                                    transport)

JST = timezone(timedelta(hours=9))
R0 = datetime(2026, 7, 1, 9, 0, tzinfo=JST)                                       # P9 の人の審査（P8 の D0 の後）
HOUR = timedelta(hours=1)
AUTHOR = "human:reviewer"
DUE = date(2026, 10, 1)
CODES = ["90010", "90020", "90030", "90040", "90050"]


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED: network / credential / P8 write path")


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    """合成の完了した P8 の run（MATCH ・NO_MATCH ・NOT_EVALUABLE ・identity なし ・取得の失敗）＋ 空の P9 の root。"""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    p8 = tmp_path / "p8_private_root"
    ids = identity(p8, [(f"issuer-{c}", [c]) for c in CODES if c != "90040"])
    universe, pol = authorities(p8, CODES)
    rows = {"90010": fins("90010"), "90020": fins("90020", op="5000000000"), "90030": fins("90030", op=""),
            "90050": TransportResponse(500, "{}")}
    out = run(p8, universe, pol, transport([master(c) for c in CODES], rows), ACQ[0])
    handoff = reconstruct_completed_run(p8, out.run_id)
    proposals = {p.screener_state: p for p in watch_proposals(handoff)}
    p9 = tmp_path / "p9_private_root"
    p9.mkdir()
    AuthorityStores.initialize(p9)
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)                            # 実行器は credential を要らない
    for target, attr in ((lt.LocalHttpsTransport, "__init__"), (JQuantsLiveClient, "__init__"),
                         (http.client.HTTPSConnection, "__init__"), (socket.socket, "connect")):
        monkeypatch.setattr(target, attr, _trap)
    monkeypatch.setattr(socket, "create_connection", _trap)
    return dict(p8=p8, p9=p9, ids=ids, out=out, handoff=handoff, proposals=proposals, p8_snapshot=snapshot(p8))


def executor(w, *, p8: bool = True) -> HumanDecisionExecutor:
    return HumanDecisionExecutor(w["p9"], p8_root=w["p8"] if p8 else None)


def from_proposal(w, state: str = "NO_MATCH", **over) -> WatchCreateFromProposal:
    proposal = w["proposals"][state]
    fields = dict(issuer_id=proposal.issuer_id, run_id=proposal.run_id, screen_result_id=proposal.screen_result_id,
                  proposal_digest=proposal.proposal_digest, rationale="follow the issuer", review_due_on=DUE,
                  author_ref=AUTHOR, reviewed_at=R0)
    return WatchCreateFromProposal(**{**fields, **over})


def manual(w, code: str = "90030", **over) -> WatchCreateManual:
    fields = dict(issuer_id=w["ids"][f"issuer-{code}"], rationale="manually followed", review_due_on=DUE,
                  author_ref=AUTHOR, reviewed_at=R0)
    return WatchCreateManual(**{**fields, **over})


def content(w=None, *, state: str = None, issuer: str = None, **over) -> ThesisContent:
    support = (HumanNoteEvidence(note="management commentary"),)
    if state:
        p = w["proposals"][state]
        support += (P8ScreenEvidence(run_id=p.run_id, screen_result_id=p.screen_result_id,
                                     issuer_id=issuer or p.issuer_id, screener_state=state),)
    fields = dict(statement="margins hold up", mechanism="pricing", catalysts=("annual results",),
                  risks=("input costs",), assumptions=("stable demand",),
                  invalidation_conditions=(ConditionInput(key="c1", text="margin falls below the stated level"),
                                           ConditionInput(key="c2", text="pricing power is lost")),
                  supporting_evidence=support, counter_evidence=(HumanNoteEvidence(note="new capacity"),),
                  horizon_note="several periods", confidence_note="moderate")
    return ThesisContent(**{**fields, **over})


def fails(code: str, fn, *args, **kwargs) -> ExecutorError:
    with pytest.raises(ExecutorError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


def store_fails(code: str, fn, *args, **kwargs) -> None:
    with pytest.raises(AuthorityStoreError) as exc:
        fn(*args, **kwargs)
    assert (exc.value.category, exc.value.code) == (StoreFailureCategory.APPEND_REJECTED, code), exc.value.code


def created_watch(w, decision=None):
    receipt = executor(w).execute(decision or from_proposal(w))
    return receipt, AuthorityStores.open(w["p9"]).watch.revision(receipt.revision_id)


# ================================================ A P8 の提案からの Watchlist の作成


@pytest.mark.parametrize("state", ["MATCH", "NO_MATCH", "NOT_EVALUABLE"])
def test_a_a_any_evaluated_issuer_can_be_created_from_its_exact_proposal(world, state: str) -> None:
    receipt, revision = created_watch(world, from_proposal(world, state))
    assert receipt.status == "APPENDED" and receipt.seq == 1 and receipt.root_id.startswith("p9wat_")
    assert revision.provenance.kind is ProvenanceKind.P8_PROPOSAL
    assert revision.provenance.proposal_digest == world["proposals"][state].proposal_digest
    assert snapshot(world["p8"]) == world["p8_snapshot"]                              # P8 に書かない


def test_a_b_binding_mismatches_fail_closed_before_any_write(world) -> None:
    ex = executor(world)
    before = snapshot(world["p9"])
    fails("PROPOSAL_DIGEST_MISMATCH", ex.execute, from_proposal(world, proposal_digest="p9prp_" + "0" * 24))
    fails("P8_RESULT_DRIFT", ex.execute, from_proposal(world, screen_result_id="p8srs_" + "0" * 24))
    fails("P8_LEDGER_INVALID", ex.execute, from_proposal(world, run_id="p8run_" + "0" * 24))
    fails("PROPOSAL_ISSUER_ABSENT", ex.execute, from_proposal(world, issuer_id="p8iss_" + "e" * 24))
    failed_issuer = world["ids"]["issuer-90050"]                                     # 取得の失敗（EVALUATED ではない）
    assert failed_issuer not in {r.issuer_id for r in world["handoff"].result.issuer_results}
    fails("PROPOSAL_ISSUER_ABSENT", ex.execute, from_proposal(world, issuer_id=failed_issuer))
    other = world["proposals"]["MATCH"]
    fails("PROPOSAL_DIGEST_MISMATCH", ex.execute, from_proposal(world, "NO_MATCH", proposal_digest=other.proposal_digest))
    fails("P8_ROOT_REQUIRED", executor(world, p8=False).execute, from_proposal(world))
    fails("ROOTS_NOT_SEPARATE", HumanDecisionExecutor, world["p9"], p8_root=world["p9"])
    assert snapshot(world["p9"]) == before and snapshot(world["p8"]) == world["p8_snapshot"]


# ================================================ B MANUAL の出所（凍結 A1 の人が審査した発行体の登録の record）


def test_b_a_manual_creation_confirms_a_reviewed_a1_issuer_record_only(world) -> None:
    receipt, revision = created_watch(world, manual(world))
    assert revision.provenance.kind is ProvenanceKind.MANUAL and receipt.status == "APPENDED"
    assert "NOT_A_LISTING_OR_COVERAGE_CLAIM" in ISSUER_RECORD_SEMANTICS
    ex = executor(world)
    fails("ISSUER_AUTHORITY_UNKNOWN", ex.execute, manual(world, issuer_id="p8iss_" + "e" * 24))
    fails("ISSUER_NOT_KNOWN_BY_REVIEWED_AT", ex.execute,
          manual(world, "90020", reviewed_at=datetime(2026, 6, 30, 8, 0, tzinfo=JST)))   # record より前の審査
    fails("P8_ROOT_REQUIRED", executor(world, p8=False).execute, manual(world, "90020"))
    assert snapshot(world["p8"]) == world["p8_snapshot"]


def test_b_b_missing_identity_authority_fails_closed_without_creating_it(world, tmp_path: Path) -> None:
    bare = tmp_path / "bare_p8_root"
    bare.mkdir()
    fails("IDENTITY_AUTHORITY_UNAVAILABLE", HumanDecisionExecutor(world["p9"], p8_root=bare).execute, manual(world))
    assert list(bare.iterdir()) == []


# ================================================ C Watchlist の更新（先頭 ・遷移 ・訂正 ・A3 の世界）


def update(w, head, kind: DecisionKind, **over) -> WatchUpdate:
    fields = dict(kind=kind, watch_entry_id=head.watch_entry_id, expected_head_revision_id=head.revision_id,
                  rationale=head.rationale, review_due_on=DUE, thesis_ids=(), author_ref=AUTHOR,
                  reviewed_at=head.reviewed_at + HOUR)
    return WatchUpdate(**{**fields, **over})


def test_c_a_revise_transition_and_correction_derive_seq_and_prev_from_the_reviewed_head(world) -> None:
    _, w1 = created_watch(world)
    ex = executor(world)
    r2 = ex.execute(update(world, w1, DecisionKind.WATCH_REVISE, rationale="sharper rationale"))
    w2 = ex.stores.watch.revision(r2.revision_id)
    assert (w2.seq, w2.prev_revision_id) == (2, w1.revision_id)
    r3 = ex.execute(update(world, w2, DecisionKind.WATCH_TRANSITION, to_status=WatchStatus.PAUSED, review_due_on=None))
    w3 = ex.stores.watch.revision(r3.revision_id)
    assert w3.status is WatchStatus.PAUSED and w3.review_due_on is None
    r4 = ex.execute(update(world, w3, DecisionKind.WATCH_CORRECTION, rationale="corrected", review_due_on=None,
                           corrects_revision_id=w2.revision_id, correction_reason="wrong wording"))
    assert ex.stores.watch.revision(r4.revision_id).status is WatchStatus.PAUSED
    fails("ILLEGAL_TRANSITION", ex.execute, update(world, ex.stores.watch.revision(r4.revision_id),
                                                   DecisionKind.WATCH_TRANSITION, to_status=WatchStatus.PAUSED))
    fails("EXPECTED_HEAD_UNKNOWN", ex.execute, update(world, w1, DecisionKind.WATCH_REVISE,
                                                      expected_head_revision_id="p9wrv_" + "0" * 24))
    fails("INVALID_DECISION:DATE_REQUIRED", ex.execute,
          update(world, ex.stores.watch.revision(r4.revision_id), DecisionKind.WATCH_TRANSITION,
                 to_status=WatchStatus.ACTIVE, review_due_on=None))


def test_c_b_stale_heads_fail_closed_and_exact_retries_are_reused(world) -> None:
    _, w1 = created_watch(world)
    ex = executor(world)
    first = update(world, w1, DecisionKind.WATCH_REVISE, rationale="first edit")
    assert ex.execute(first).status == "APPENDED"
    assert executor(world).execute(first).status == "REUSED"                         # 同じ入力の再試行
    assert executor(world).execute(from_proposal(world)).status == "REUSED"          # 作成の再試行
    fails("STALE_AUTHORITY_HEAD", executor(world).execute,
          update(world, w1, DecisionKind.WATCH_REVISE, rationale="a different edit on the old head"))


def test_c_c_duplicate_live_issuer_is_rejected_by_the_a3_world_check(world) -> None:
    created_watch(world, from_proposal(world, "MATCH"))
    proposal = world["proposals"]["MATCH"]
    issuer_code = next(c for c in CODES if world["ids"].get(f"issuer-{c}") == proposal.issuer_id)
    store_fails("WORLD_INVALID:DUPLICATE_LIVE_WATCH_ENTRY", executor(world).execute,
                manual(world, issuer_code, reviewed_at=R0 + HOUR))


# ================================================ D Thesis


def thesis_create(w, watch, **over) -> ThesisCreate:
    fields = dict(watch_entry_id=watch.watch_entry_id, issuer_id=watch.issuer_id, content=content(),
                  review_due_on=DUE, author_ref=AUTHOR, reviewed_at=watch.reviewed_at + HOUR)
    return ThesisCreate(**{**fields, **over})


def thesis_update(head, kind: DecisionKind, **over) -> ThesisUpdate:
    fields = dict(kind=kind, thesis_id=head.thesis_id, expected_head_revision_id=head.revision_id, review_due_on=DUE,
                  author_ref=AUTHOR, reviewed_at=head.reviewed_at + HOUR)
    return ThesisUpdate(**{**fields, **over})


def test_d_a_thesis_create_checks_the_watch_link_issuer_liveness_and_new_p8_evidence(world) -> None:
    _, watch = created_watch(world, from_proposal(world, "NO_MATCH"))
    ex = executor(world)
    receipt = ex.execute(thesis_create(world, watch, content=content(world, state="NO_MATCH")))
    assert receipt.status == "APPENDED" and receipt.root_id.startswith("p9ths_")
    fails("WATCH_ENTRY_NOT_FOUND", ex.execute, thesis_create(world, watch, watch_entry_id="p9wat_" + "0" * 24))
    fails("ISSUER_MISMATCH", ex.execute, thesis_create(world, watch, issuer_id="p8iss_" + "e" * 24))
    fails("WATCH_ENTRY_NOT_LIVE_AT_REVIEW", ex.execute, thesis_create(world, watch, reviewed_at=R0 - HOUR))
    fails("P8_EVIDENCE_MISMATCH", ex.execute,
          thesis_create(world, watch, content=content(world, state="NO_MATCH", supporting_evidence=(
              P8ScreenEvidence(run_id=watch.provenance.run_id, screen_result_id=watch.provenance.screen_result_id,
                               issuer_id=watch.issuer_id, screener_state="MATCH"),))))
    fails("P8_ROOT_REQUIRED", executor(world, p8=False).execute,
          thesis_create(world, watch, content=content(world, state="NO_MATCH"), reviewed_at=R0 + 3 * HOUR))


def test_d_b_challenge_invalidate_retire_correct_and_stale_heads(world) -> None:
    _, watch = created_watch(world)
    ex = executor(world)
    t1 = ex.stores.thesis.revision(ex.execute(thesis_create(world, watch)).revision_id)
    t2 = ex.stores.thesis.revision(ex.execute(thesis_update(
        t1, DecisionKind.THESIS_CORRECTION, content=content(statement="corrected statement"),
        corrects_revision_id=t1.revision_id, correction_reason="typo")).revision_id)
    t3 = ex.stores.thesis.revision(ex.execute(thesis_update(
        t2, DecisionKind.THESIS_TRANSITION, to_status=ThesisStatus.CHALLENGED,
        status_reason="contrary report")).revision_id)
    assert t3.status is ThesisStatus.CHALLENGED and t3.statement == "corrected statement"   # 遷移は内容を変えない
    fails("STALE_AUTHORITY_HEAD", ex.execute, thesis_update(t2, DecisionKind.THESIS_REVISE, content=content()))
    fails("UNKNOWN_CONDITION_KEY", ex.execute, thesis_update(
        t3, DecisionKind.THESIS_TRANSITION, to_status=ThesisStatus.INVALIDATED, status_reason="met",
        invalidation_basis=InvalidationBasis.CONDITIONS, invalidated_condition_keys=("zz",), review_due_on=None))
    t4 = ex.stores.thesis.revision(ex.execute(thesis_update(
        t3, DecisionKind.THESIS_TRANSITION, to_status=ThesisStatus.INVALIDATED, status_reason="condition met",
        invalidation_basis=InvalidationBasis.CONDITIONS, invalidated_condition_keys=("c2",),
        review_due_on=None)).revision_id)
    assert t4.status is ThesisStatus.INVALIDATED and len(t4.invalidated_condition_ids) == 1
    fails("INVALID_DECISION:TERMINAL_STATUS", ex.execute, thesis_update(
        t4, DecisionKind.THESIS_TRANSITION, to_status=ThesisStatus.ACTIVE, status_reason="undo"))


def test_d_c_retirement_and_the_a3_removal_rule(world) -> None:
    _, watch = created_watch(world)
    ex = executor(world)
    t1 = ex.stores.thesis.revision(ex.execute(thesis_create(world, watch)).revision_id)
    remove = update(world, watch, DecisionKind.WATCH_TRANSITION, to_status=WatchStatus.REMOVED, review_due_on=None,
                    removal_reason="no longer followed", reviewed_at=t1.reviewed_at + HOUR)
    store_fails("WORLD_INVALID:LIVE_THESIS_ON_REMOVED_WATCH_ENTRY", ex.execute, remove)
    t2 = ex.stores.thesis.revision(ex.execute(thesis_update(
        t1, DecisionKind.THESIS_TRANSITION, to_status=ThesisStatus.RETIRED, status_reason="horizon passed",
        review_due_on=None)).revision_id)
    after = dataclasses.replace(remove, reviewed_at=t2.reviewed_at + HOUR)
    assert executor(world).execute(after).status == "APPENDED"


# ================================================ E dry-run ・冪等


def test_e_a_dry_run_validates_without_writing(world) -> None:
    ex = executor(world)
    before = snapshot(world["p9"])
    assert ex.execute(from_proposal(world), dry_run=True).status == "VALID"
    assert snapshot(world["p9"]) == before
    created_watch(world)
    ex = executor(world)
    assert ex.execute(from_proposal(world), dry_run=True).status == "WOULD_REUSE"
    proposal = world["proposals"]["NO_MATCH"]
    issuer_code = next(c for c in CODES if world["ids"].get(f"issuer-{c}") == proposal.issuer_id)
    fails("WOULD_BE_REJECTED:DUPLICATE_LIVE_WATCH_ENTRY", ex.execute,
          manual(world, issuer_code, reviewed_at=R0 + HOUR), dry_run=True)


# ================================================ F 安全な投影 ・見直しの日（派生 ・追記なし ・時計なし）


def test_f_a_safe_projection_counts_only_and_never_leaks_identifiers_or_text(world) -> None:
    _, watch = created_watch(world, from_proposal(world, "NO_MATCH"))
    created_watch(world, manual(world, "90010", reviewed_at=R0 + HOUR))
    ex = executor(world)
    ex.execute(thesis_create(world, watch, content=content(world, state="NO_MATCH")))
    stores = AuthorityStores.open(world["p9"])
    view = pj.safe_projection(stores, at=R0 + 5 * HOUR, as_of_date=DUE).as_dict()
    assert view["watch"]["count"] == 2 and view["watch"]["status_counts"] == {"ACTIVE": 2}
    assert view["watch"]["provenance_kind_counts"] == {"MANUAL": 1, "P8_PROPOSAL": 1}
    assert view["watch"]["review_due_count"] == 2 and view["thesis"]["count"] == 1
    assert view["thesis"]["supporting_evidence_kind_counts"] == {"HUMAN_NOTE": 1, "P8_SCREEN_RESULT": 1}
    assert pj.safe_projection(stores, at=R0 + 5 * HOUR, as_of_date=DUE - timedelta(days=1)).watch_review_due_count == 0
    assert pj.safe_projection(stores, at=R0 - HOUR, as_of_date=DUE).watch_entry_count == 0     # 時点の像
    text = json.dumps(view)
    for leak in (watch.issuer_id, watch.watch_entry_id, watch.rationale, "margins hold up", "management commentary",
                 watch.provenance.run_id, watch.provenance.screen_result_id, AUTHOR, "p8iss_", "p9wat_", "p9ths_"):
        assert leak not in text, leak

    def keys(obj):
        return set(obj) | {k for v in obj.values() if isinstance(v, dict) for k in keys(v)} if isinstance(obj, dict) \
            else set()
    assert not keys(view) & set(pj.FORBIDDEN_PROJECTION_FIELDS)


def test_f_b_review_due_report_is_derived_deterministic_and_never_appends(world) -> None:
    _, watch = created_watch(world)
    stores = AuthorityStores.open(world["p9"])
    before = snapshot(world["p9"])
    first = pj.review_due_report(stores, at=R0 + HOUR, as_of_date=DUE)
    assert first == pj.review_due_report(stores, at=R0 + HOUR, as_of_date=DUE) and len(first) == 1
    assert first[0].root_id == watch.watch_entry_id and first[0].review_due_on == DUE
    assert pj.review_due_report(stores, at=R0 + HOUR, as_of_date=DUE - timedelta(days=1)) == ()
    assert snapshot(world["p9"]) == before
    assert "OVERDUE" not in {s.value for s in WatchStatus} | {s.value for s in ThesisStatus}


# ================================================ G 人の判断の file ・local の入口


def test_g_a_decision_files_parse_exactly_and_the_local_cli_applies_and_summarizes(world, tmp_path: Path,
                                                                                   capsys) -> None:
    proposal = world["proposals"]["NO_MATCH"]
    data = {"schema_version": DECISION_SCHEMA_VERSION, "kind": "WATCH_CREATE_FROM_PROPOSAL",
            "issuer_id": proposal.issuer_id, "run_id": proposal.run_id, "screen_result_id": proposal.screen_result_id,
            "proposal_digest": proposal.proposal_digest, "rationale": "follow", "review_due_on": "2026-10-01",
            "author_ref": AUTHOR, "reviewed_at": "2026-07-01T09:00:00+09:00"}
    assert isinstance(decision_from_dict(data), WatchCreateFromProposal)
    for bad in ({**data, "seq": 1}, {k: v for k, v in data.items() if k != "reviewed_at"},
                {**data, "schema_version": "x"}, {**data, "kind": "WATCH_PROMOTE"}):
        with pytest.raises(Exception):
            decision_from_dict(bad)
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    args = ["apply", "--p9-root", str(world["p9"]), "--decision", str(path), "--p8-root", str(world["p8"])]
    assert local_cli.run_cli(args + ["--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VALID"
    assert local_cli.run_cli(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "APPENDED" and set(receipt) == {"decision_kind", "revision_id", "root_id", "seq",
                                                                 "status"}
    assert local_cli.run_cli(["summary", "--p9-root", str(world["p9"]), "--at", "2026-07-02T00:00:00+09:00",
                              "--as-of-date", "2026-10-01"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["watch"]["count"] == 1 and proposal.issuer_id not in json.dumps(summary)
    path.write_text(json.dumps({**data, "proposal_digest": "p9prp_" + "0" * 24}), encoding="utf-8")
    assert local_cli.run_cli(args) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "PROPOSAL_DIGEST_MISMATCH"
    assert snapshot(world["p8"]) == world["p8_snapshot"]
