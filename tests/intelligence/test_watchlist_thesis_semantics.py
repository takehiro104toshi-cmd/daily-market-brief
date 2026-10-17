"""P9-A2 — Watchlist ／ Thesis の意味の model ・提案 ・revision ・状態機械 ・記録をまたぐ不変条件の純の test（合成だけ）。"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence.identity_model import is_issuer_id as frozen_is_issuer_id
from src.intelligence.screener_intelligence.screener_criteria_model import ScreenerState
from src.intelligence.watchlist_thesis_intelligence import cross_rules as cr
from src.intelligence.watchlist_thesis_intelligence import proposal_model as pm
from src.intelligence.watchlist_thesis_intelligence import revision_model as rm
from src.intelligence.watchlist_thesis_intelligence import thesis_model as tm
from src.intelligence.watchlist_thesis_intelligence import watch_model as wm
from src.intelligence.watchlist_thesis_intelligence.p8_handoff import reconstruct_completed_run
from src.intelligence.watchlist_thesis_intelligence.revision_model import ChangeKind, SemanticModelError
from src.intelligence.watchlist_thesis_intelligence.thesis_model import (HumanNoteEvidence, InvalidationBasis,
                                                                          InvalidationCondition, P8ScreenEvidence,
                                                                          ThesisRevision, ThesisStatus)
from src.intelligence.watchlist_thesis_intelligence.watch_model import (ManualProvenance, P8ProposalProvenance,
                                                                         WatchEntryRevision, WatchStatus)
from tests.intelligence.test_screener_multi_issuer_executor import (ACQ, authorities, fins, identity, master, run,
                                                                    transport)

JST = timezone(timedelta(hours=9))
T0 = datetime(2026, 7, 1, 9, 0, tzinfo=JST)
HOUR = timedelta(hours=1)
AUTHOR = "human:reviewer"
ISSUER, ISSUER2 = "p8iss_" + "a" * 24, "p8iss_" + "b" * 24
RUN, SRS = "p8run_" + "1" * 24, "p8srs_" + "2" * 24
DUE = date(2026, 10, 1)


def fails(code: str, fn, *args, **kwargs) -> SemanticModelError:
    with pytest.raises(SemanticModelError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


# ---------------------------------------------------------------- builders（caller が瞬間 ・日を全て渡す）


def watch_create(issuer: str = ISSUER, at: datetime = T0, provenance=None, **over) -> WatchEntryRevision:
    provenance = provenance or ManualProvenance()
    root = wm.derive_watch_entry_id(issuer_id=issuer, author_ref=AUTHOR, reviewed_at=at, provenance=provenance)
    fields = dict(watch_entry_id=root, seq=1, prev_revision_id="", change_kind=ChangeKind.CREATE, issuer_id=issuer,
                  status=WatchStatus.ACTIVE, rationale="follow the issuer for the stated reasons", review_due_on=DUE,
                  removal_reason="", thesis_ids=(), provenance=provenance, author_ref=AUTHOR, reviewed_at=at)
    return WatchEntryRevision(**{**fields, **over})


def watch_next(prev: WatchEntryRevision, kind: ChangeKind, status: WatchStatus = None, **over) -> WatchEntryRevision:
    status = status or prev.status
    fields = dict(seq=prev.seq + 1, prev_revision_id=prev.revision_id, change_kind=kind, status=status,
                  reviewed_at=prev.reviewed_at + HOUR, review_due_on=None if status is WatchStatus.REMOVED else DUE,
                  removal_reason="no longer followed" if status is WatchStatus.REMOVED else "")
    return dataclasses.replace(prev, **{**fields, **over})


def conditions(thesis_id: str, *keys: str):
    return tuple(InvalidationCondition(condition_id=tm.derive_condition_id(thesis_id, key), key=key,
                                       text=f"the thesis fails if condition {key} is observed") for key in keys)


def thesis_create(watch: WatchEntryRevision, at: datetime = None, **over) -> ThesisRevision:
    at = at or watch.reviewed_at + HOUR
    root = tm.derive_thesis_id(issuer_id=watch.issuer_id, watch_entry_id=watch.watch_entry_id, author_ref=AUTHOR,
                               reviewed_at=at)
    fields = dict(thesis_id=root, seq=1, prev_revision_id="", change_kind=ChangeKind.CREATE,
                  issuer_id=watch.issuer_id, watch_entry_id=watch.watch_entry_id, status=ThesisStatus.ACTIVE,
                  statement="the issuer's margins hold up", mechanism="pricing and mix",
                  catalysts=("next annual results",), risks=("input costs",), assumptions=("demand is stable",),
                  invalidation_conditions=conditions(root, "c1", "c2"),
                  supporting_evidence=(P8ScreenEvidence(run_id=RUN, screen_result_id=SRS, issuer_id=watch.issuer_id,
                                                        screener_state="MATCH"),),
                  counter_evidence=(HumanNoteEvidence(note="competitor capacity is growing"),),
                  horizon_note="several reporting periods", review_due_on=DUE,
                  confidence_note="moderate; depends on the next results", author_ref=AUTHOR, reviewed_at=at)
    return ThesisRevision(**{**fields, **over})


def thesis_next(prev: ThesisRevision, kind: ChangeKind, status: ThesisStatus = None, **over) -> ThesisRevision:
    status = status or prev.status
    live = status in tm.LIVE_THESIS_STATUSES
    fields = dict(seq=prev.seq + 1, prev_revision_id=prev.revision_id, change_kind=kind, status=status,
                  reviewed_at=prev.reviewed_at + HOUR, review_due_on=DUE if live else None,
                  status_reason="human reason for the transition" if kind is ChangeKind.TRANSITION else "",
                  invalidation_basis=None, invalidated_condition_ids=())
    return dataclasses.replace(prev, **{**fields, **over})


# ================================================ A Watchlist


def test_a_a_valid_create_has_stable_root_and_content_addressed_revision() -> None:
    w = watch_create()
    assert w.watch_entry_id.startswith("p9wat_") and w.revision_id.startswith("p9wrv_")
    assert w.revision_id == watch_create().revision_id                              # 決定論
    assert w.revision_id != watch_create(rationale="another rationale").revision_id
    assert wm.validate_watch_chain([w]) == (w,)


def test_a_b_transitions_follow_the_state_machine_and_removed_is_terminal() -> None:
    w1 = watch_create()
    w2 = watch_next(w1, ChangeKind.TRANSITION, WatchStatus.PAUSED, review_due_on=None)   # PAUSED は見直しを止めてよい
    w3 = watch_next(w2, ChangeKind.TRANSITION, WatchStatus.ACTIVE)
    w4 = watch_next(w3, ChangeKind.TRANSITION, WatchStatus.REMOVED)
    assert wm.validate_watch_chain([w4, w2, w1, w3])[-1] is w4                       # 入力の順に依らない
    w5 = watch_next(w4, ChangeKind.TRANSITION, WatchStatus.ACTIVE)
    fails("TERMINAL_STATUS", wm.validate_watch_successor, w4, w5)
    fails("TERMINAL_STATUS", wm.validate_watch_successor, w4,
          watch_next(w4, ChangeKind.CORRECTION, corrects_revision_id=w4.revision_id, correction_reason="undo"))
    p = watch_next(w1, ChangeKind.TRANSITION, WatchStatus.PAUSED)
    fails("ILLEGAL_TRANSITION", wm.validate_watch_successor, p, watch_next(p, ChangeKind.TRANSITION,
                                                                          WatchStatus.PAUSED))
    fails("STATUS_CHANGE_REQUIRES_TRANSITION", wm.validate_watch_successor, w1,
          watch_next(w1, ChangeKind.REVISE, WatchStatus.PAUSED))
    assert set(wm.WATCH_TRANSITIONS) == set(WatchStatus) and wm.WATCH_TRANSITIONS[WatchStatus.REMOVED] == ()


def test_a_c_removal_reason_and_review_dates_are_required_where_defined() -> None:
    w1 = watch_create()
    fails("INVALID_TEXT", watch_next, w1, ChangeKind.TRANSITION, WatchStatus.REMOVED, removal_reason="")
    fails("REMOVAL_REASON_ONLY_FOR_REMOVED", watch_next, w1, ChangeKind.REVISE, removal_reason="why")
    fails("DATE_REQUIRED", watch_create, review_due_on=None)                        # ACTIVE は見直しの日が要る
    fails("INVALID_DATE", watch_create, review_due_on=datetime(2026, 10, 1, tzinfo=JST))
    fails("REVIEW_DUE_ON_REMOVED", watch_next, w1, ChangeKind.TRANSITION, WatchStatus.REMOVED, review_due_on=DUE)


def test_a_d_caller_supplied_aware_instants_and_human_authors_only() -> None:
    fails("INSTANT_NOT_AWARE", watch_create, at=datetime(2026, 7, 1, 9, 0))
    for author in ("system", "llm:model", "code:auto", "", "human:", "human:api_key"):
        with pytest.raises(SemanticModelError):
            watch_create(author_ref=author)
    for field in ("reviewed_at", "review_due_on", "author_ref"):                     # 既定の値は無い
        assert wm.WatchEntryRevision.__dataclass_fields__[field].default is dataclasses.MISSING


def test_a_e_invalid_seq_prev_root_and_regression_are_rejected() -> None:
    w1 = watch_create()
    w2 = watch_next(w1, ChangeKind.REVISE, rationale="updated rationale")
    fails("SEQ_NOT_CONSECUTIVE", wm.validate_watch_successor, w1, dataclasses.replace(w2, seq=3))
    fails("PREV_REVISION_MISMATCH", wm.validate_watch_successor, w1,
          dataclasses.replace(w2, prev_revision_id="p9wrv_" + "0" * 24))
    fails("REVIEWED_AT_REGRESSED", wm.validate_watch_successor, w1, dataclasses.replace(w2, reviewed_at=T0 - HOUR))
    fails("ROOT_MISMATCH", wm.validate_watch_successor, w1, dataclasses.replace(w2, watch_entry_id="p9wat_" + "0" * 24))
    fails("ISSUER_CHANGED", wm.validate_watch_successor, w1, dataclasses.replace(w2, issuer_id=ISSUER2))
    fails("WATCH_ENTRY_ID_MISMATCH", watch_create, watch_entry_id="p9wat_" + "0" * 24)
    fails("INVALID_INITIAL_REVISION", watch_create, status=WatchStatus.PAUSED, review_due_on=None)
    fails("INVALID_INITIAL_REVISION", wm.validate_watch_chain, [w2])
    fails("DUPLICATE_REVISION", wm.validate_watch_chain, [w1, w1])


def test_a_f_correction_keeps_status_and_targets_a_known_revision() -> None:
    w1 = watch_create()
    fix = watch_next(w1, ChangeKind.CORRECTION, rationale="corrected", corrects_revision_id=w1.revision_id,
                     correction_reason="typo in the rationale")
    assert wm.validate_watch_chain([w1, fix])[-1] is fix
    fails("CORRECTION_TARGET_UNKNOWN", wm.validate_watch_successor, w1,
          dataclasses.replace(fix, corrects_revision_id="p9wrv_" + "0" * 24))
    fails("CORRECTION_FIELDS_UNEXPECTED", watch_next, w1, ChangeKind.REVISE, corrects_revision_id=w1.revision_id)
    fails("PROVENANCE_CHANGED", wm.validate_watch_successor, w1, dataclasses.replace(
        fix, provenance=P8ProposalProvenance(run_id=RUN, screen_result_id=SRS, policy_id="p8pol_" + "3" * 24,
                                             policy_version=1, universe_id="p8uni_" + "4" * 24, universe_version=1,
                                             authority_day=date(2026, 6, 30), proposal_digest="p9prp_" + "5" * 24)))


def test_a_g_readding_after_removal_is_a_new_root_and_only_one_live_entry_per_issuer() -> None:
    w1 = watch_create()
    removed = watch_next(w1, ChangeKind.TRANSITION, WatchStatus.REMOVED)
    again = watch_create(at=removed.reviewed_at + HOUR)
    assert again.watch_entry_id != w1.watch_entry_id
    cr.check_world([w1, removed, again], [])
    duplicate = watch_create(at=T0 + HOUR)                                           # 同じ発行体 ・別の root ・両方とも生きている
    fails("DUPLICATE_LIVE_WATCH_ENTRY", cr.check_world, [w1, duplicate], [])
    cr.check_world([w1, watch_create(issuer=ISSUER2, at=T0 + HOUR)], [])


def test_a_h_point_in_time_uses_seq_and_reviewed_at_not_input_order() -> None:
    w1 = watch_create()
    w2 = watch_next(w1, ChangeKind.TRANSITION, WatchStatus.PAUSED)
    w3 = watch_next(w2, ChangeKind.TRANSITION, WatchStatus.ACTIVE)
    chain = wm.validate_watch_chain([w3, w1, w2])
    assert rm.state_at(chain, T0 - HOUR) is None
    assert rm.state_at(chain, T0) is w1 and rm.state_at(chain, T0 + HOUR) is w2 and rm.state_at(chain, T0 + 9 * HOUR) is w3
    tie = watch_next(w3, ChangeKind.REVISE, rationale="same instant revision", reviewed_at=w3.reviewed_at)
    assert rm.state_at(wm.validate_watch_chain([w1, w2, w3, tie]), w3.reviewed_at) is tie   # 同じ瞬間は最大の seq


# ================================================ B Thesis


def test_b_a_valid_create_and_active_content_revision() -> None:
    w = watch_create()
    t1 = thesis_create(w)
    assert t1.thesis_id.startswith("p9ths_") and t1.revision_id.startswith("p9trv_")
    assert all(c.condition_id.startswith("p9inv_") for c in t1.invalidation_conditions)
    t2 = thesis_next(t1, ChangeKind.REVISE, statement="refined statement")
    assert t2.condition_ids == t1.condition_ids                                      # 文を直しても条件の id は安定
    t3 = thesis_next(t2, ChangeKind.REVISE, invalidation_conditions=(
        dataclasses.replace(t1.invalidation_conditions[0], text="reworded condition"),))
    assert t3.invalidation_conditions[0].condition_id == t1.invalidation_conditions[0].condition_id
    assert tm.validate_thesis_chain([t3, t1, t2])[-1] is t3
    cr.check_world([w], [t1, t2, t3])


def test_b_b_challenged_round_trip_and_revise_only_when_active() -> None:
    t1 = thesis_create(watch_create())
    c = thesis_next(t1, ChangeKind.TRANSITION, ThesisStatus.CHALLENGED,
                    counter_evidence=t1.counter_evidence + (HumanNoteEvidence(note="new contrary report"),))
    back = thesis_next(c, ChangeKind.TRANSITION, ThesisStatus.ACTIVE)
    assert tm.validate_thesis_chain([t1, c, back])[-1] is back
    fails("REVISE_ONLY_WHEN_ACTIVE", tm.validate_thesis_successor, c, thesis_next(c, ChangeKind.REVISE))
    fails("INVALID_TEXT", thesis_next, t1, ChangeKind.TRANSITION, ThesisStatus.CHALLENGED, status_reason="")


def test_b_c_invalidation_needs_known_conditions_or_explicit_other_with_reason() -> None:
    t1 = thesis_create(watch_create())
    ok = thesis_next(t1, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED,
                     invalidation_basis=InvalidationBasis.CONDITIONS,
                     invalidated_condition_ids=(t1.invalidation_conditions[0].condition_id,))
    assert tm.validate_thesis_chain([t1, ok])[-1] is ok
    other = thesis_next(t1, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED, invalidation_basis=InvalidationBasis.OTHER,
                        status_reason="a structural change outside the stated conditions")
    tm.validate_thesis_successor(t1, other)
    fails("UNKNOWN_CONDITION_REF", thesis_next, t1, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED,
          invalidation_basis=InvalidationBasis.CONDITIONS, invalidated_condition_ids=("p9inv_" + "0" * 24,))
    fails("UNKNOWN_CONDITION_REF", thesis_next, t1, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED,
          invalidation_basis=InvalidationBasis.CONDITIONS, invalidated_condition_ids=())
    fails("OTHER_WITH_CONDITION_REFS", thesis_next, t1, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED,
          invalidation_basis=InvalidationBasis.OTHER, invalidated_condition_ids=t1.condition_ids[:1])
    fails("INVALIDATION_BASIS_REQUIRED", thesis_next, t1, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED)
    fails("INVALIDATION_FIELDS_ONLY_FOR_INVALIDATED", thesis_next, t1, ChangeKind.TRANSITION, ThesisStatus.RETIRED,
          invalidation_basis=InvalidationBasis.OTHER)
    # 次の revision で条件を消し、消した条件で無効にすることはできない（直前の revision の既知の条件だけ）
    pruned = thesis_next(t1, ChangeKind.REVISE, invalidation_conditions=t1.invalidation_conditions[1:])
    gone = t1.invalidation_conditions[0]
    sneaky = thesis_next(pruned, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED,
                         invalidation_basis=InvalidationBasis.CONDITIONS,
                         invalidation_conditions=t1.invalidation_conditions,
                         invalidated_condition_ids=(gone.condition_id,))
    fails("UNKNOWN_CONDITION_REF", tm.validate_thesis_successor, pruned, sneaky)


def test_b_d_retired_and_invalidated_are_terminal() -> None:
    t1 = thesis_create(watch_create())
    retired = thesis_next(t1, ChangeKind.TRANSITION, ThesisStatus.RETIRED)
    for nxt in (thesis_next(retired, ChangeKind.TRANSITION, ThesisStatus.ACTIVE),
                thesis_next(retired, ChangeKind.CORRECTION, corrects_revision_id=t1.revision_id,
                            correction_reason="undo")):
        fails("TERMINAL_STATUS", tm.validate_thesis_successor, retired, nxt)
    fails("REVIEW_DUE_ON_TERMINAL", thesis_next, t1, ChangeKind.TRANSITION, ThesisStatus.RETIRED, review_due_on=DUE)
    assert tm.THESIS_TRANSITIONS[ThesisStatus.INVALIDATED] == () == tm.THESIS_TRANSITIONS[ThesisStatus.RETIRED]


def test_b_e_confidence_is_text_only_and_numeric_confidence_is_rejected() -> None:
    w = watch_create()
    for bad in ("8", "80%", "0.8", "7/10", " 4.5 / 5 "):
        fails("NUMERIC_CONFIDENCE_REJECTED", thesis_create, w, confidence_note=bad)
    fails("TEXT_NOT_STRING", thesis_create, w, confidence_note=0.8)
    thesis_create(w, confidence_note="high if the next two reports confirm the trend; 3 risks remain open")
    assert all("confidence" not in f or f == "confidence_note" for f in tm.ThesisRevision.__dataclass_fields__)


def test_b_f_supporting_and_counter_evidence_are_separate_typed_and_bound_to_the_issuer() -> None:
    w = watch_create()
    t1 = thesis_create(w)
    assert t1.supporting_evidence[0].kind is tm.EvidenceKind.P8_SCREEN_RESULT
    assert t1.counter_evidence[0].kind is tm.EvidenceKind.HUMAN_NOTE
    same = t1.supporting_evidence[0]
    fails("EVIDENCE_BOTH_SUPPORTING_AND_COUNTER", thesis_create, w, counter_evidence=(same,))
    fails("EVIDENCE_ISSUER_MISMATCH", thesis_create, w, supporting_evidence=(dataclasses.replace(same,
                                                                                                issuer_id=ISSUER2),))
    fails("INVALID_SCREENER_STATE", P8ScreenEvidence, run_id=RUN, screen_result_id=SRS, issuer_id=ISSUER,
          screener_state="TOP")
    fails("DUPLICATE_EVIDENCE", thesis_create, w, supporting_evidence=(same, same))
    fails("INVALID_EVIDENCE_KIND", thesis_create, w, supporting_evidence=("a plain string",))
    assert set(f for f in P8ScreenEvidence.__dataclass_fields__) == {"run_id", "screen_result_id", "issuer_id",
                                                                     "screener_state", "kind"}   # 指標の値なし


def test_b_g_wrong_issuer_or_watch_linkage_is_rejected() -> None:
    w = watch_create()
    t1 = thesis_create(w)
    fails("THESIS_ID_MISMATCH", thesis_create, w, issuer_id=ISSUER2, supporting_evidence=())
    fails("WATCH_ENTRY_CHANGED", tm.validate_thesis_successor, t1, thesis_next(
        t1, ChangeKind.REVISE, watch_entry_id="p9wat_" + "0" * 24))
    fails("ISSUER_CHANGED", tm.validate_thesis_successor, t1, thesis_next(t1, ChangeKind.REVISE, issuer_id=ISSUER2,
                                                                         supporting_evidence=()))
    w2 = watch_create(issuer=ISSUER2, at=T0 + HOUR)
    fails("THESIS_ID_MISMATCH", dataclasses.replace, t1, watch_entry_id=w2.watch_entry_id)   # root は項目に結び付く
    fails("INVALIDATION_CONDITIONS_REQUIRED", thesis_create, w, invalidation_conditions=())
    fails("CONDITION_ID_MISMATCH", thesis_create, w,
          invalidation_conditions=(dataclasses.replace(t1.invalidation_conditions[0], key="zz"),))


# ================================================ C 記録をまたぐ不変条件（自動の書き換えなし）


def test_c_a_thesis_requires_a_live_watch_entry_of_the_same_issuer() -> None:
    w = watch_create()
    removed = watch_next(w, ChangeKind.TRANSITION, WatchStatus.REMOVED)
    late = thesis_create(w, at=removed.reviewed_at + HOUR)
    fails("LIVE_THESIS_ON_REMOVED_WATCH_ENTRY", cr.check_world, [w, removed], [late])
    early = thesis_create(w, at=T0 - HOUR)                                           # Watchlist の項目より前
    fails("THESIS_WITHOUT_WATCH_ENTRY", cr.check_world, [w], [early])
    other = watch_create(issuer=ISSUER2, at=T0 + HOUR)
    bad = thesis_create(other, at=T0 + 2 * HOUR)
    bad = dataclasses.replace(bad, issuer_id=ISSUER, supporting_evidence=(),
                              thesis_id=tm.derive_thesis_id(issuer_id=ISSUER, watch_entry_id=other.watch_entry_id,
                                                            author_ref=AUTHOR, reviewed_at=bad.reviewed_at),
                              invalidation_conditions=conditions(tm.derive_thesis_id(
                                  issuer_id=ISSUER, watch_entry_id=other.watch_entry_id, author_ref=AUTHOR,
                                  reviewed_at=bad.reviewed_at), "c1"))
    fails("THESIS_ISSUER_MISMATCH", cr.check_world, [w, other], [bad])


def test_c_b_watch_entry_cannot_be_removed_while_a_thesis_is_live() -> None:
    w = watch_create()
    t1 = thesis_create(w)
    removed = watch_next(w, ChangeKind.TRANSITION, WatchStatus.REMOVED, reviewed_at=t1.reviewed_at + HOUR)
    fails("LIVE_THESIS_ON_REMOVED_WATCH_ENTRY", cr.check_world, [w, removed], [t1])
    challenged = thesis_next(t1, ChangeKind.TRANSITION, ThesisStatus.CHALLENGED)
    fails("LIVE_THESIS_ON_REMOVED_WATCH_ENTRY", cr.check_world,
          [w, dataclasses.replace(removed, reviewed_at=challenged.reviewed_at + HOUR)], [t1, challenged])
    retired = thesis_next(t1, ChangeKind.TRANSITION, ThesisStatus.RETIRED)
    after = watch_next(w, ChangeKind.TRANSITION, WatchStatus.REMOVED, reviewed_at=retired.reviewed_at + HOUR)
    cr.check_world([w, after], [t1, retired])                                        # 終わった thesis の後なら削除できる


def test_c_c_declared_thesis_ids_are_an_index_not_authority() -> None:
    w = watch_create()
    t1 = thesis_create(w)
    linked = watch_next(w, ChangeKind.REVISE, thesis_ids=(t1.thesis_id,), reviewed_at=t1.reviewed_at + HOUR)
    cr.check_world([w, linked], [t1])
    cr.check_world([w], [t1])                                                        # 索引が全てを列挙する必要はない
    dangling = watch_next(w, ChangeKind.REVISE, thesis_ids=("p9ths_" + "0" * 24,))
    fails("DECLARED_THESIS_LINK_INVALID", cr.check_world, [w, dangling], [])
    early = watch_next(w, ChangeKind.REVISE, thesis_ids=(t1.thesis_id,), reviewed_at=T0 + HOUR / 2)
    fails("DECLARED_THESIS_LINK_INVALID", cr.check_world, [w, early], [t1])          # まだ存在しない thesis を宣言


# ================================================ D L0 の提案（非 authority ・決定論 ・MATCH は特別ではない）


@pytest.fixture
def handoff(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    root = tmp_path / "p8_private_root"
    codes = ["90010", "90020", "90030", "90040"]
    identity(root, [(f"issuer-{c}", [c]) for c in codes[:3]])                       # 4 つ目は identity なし
    universe, pol = authorities(root, codes)
    rows = {"90010": fins("90010"), "90020": fins("90020", op="5000000000"), "90030": fins("90030", op="")}
    out = run(root, universe, pol, transport([master(c) for c in codes], rows), ACQ[0])
    return reconstruct_completed_run(root, out.run_id)


def test_d_a_every_evaluated_issuer_gets_a_deterministic_digest_bound_proposal(handoff) -> None:
    proposals = pm.watch_proposals(handoff)
    states = sorted(p.screener_state for p in proposals)
    assert states == ["MATCH", "NOT_EVALUABLE", "NO_MATCH"]                          # MATCH は特別ではない ・選ばない
    assert [p.issuer_id for p in proposals] == sorted(p.issuer_id for p in proposals)
    assert {p.issuer_id for p in proposals} == {r.issuer_id for r in handoff.result.issuer_results}
    assert all(p.run_member_count == 4 and p.run_issuer_count == 3 for p in proposals)
    assert proposals[0].run_member_outcome_counts["IDENTITY_UNRESOLVED"] == 1        # coverage を隠さない
    again = pm.watch_proposals(handoff)
    assert [p.proposal_digest for p in again] == [p.proposal_digest for p in proposals]
    assert all(p.proposal_digest.startswith("p9prp_") for p in proposals)
    assert len({p.proposal_digest for p in proposals}) == 3


def test_d_b_digest_changes_with_any_input_and_binding_is_exact(handoff) -> None:
    proposal = pm.watch_proposals(handoff)[0]
    for change in (dict(screener_state="HOLD"), dict(run_id="p8run_" + "9" * 24), dict(policy_version=2),
                   dict(authority_day=date(2026, 7, 1))):
        assert dataclasses.replace(proposal, **change).proposal_digest != proposal.proposal_digest
    provenance = proposal.provenance()
    assert provenance.proposal_digest == proposal.proposal_digest
    assert pm.require_proposal_binding(proposal, provenance) is proposal
    fails("PROPOSAL_BINDING_MISMATCH", pm.require_proposal_binding, proposal,
          dataclasses.replace(provenance, proposal_digest="p9prp_" + "0" * 24))
    created = watch_create(issuer=proposal.issuer_id, provenance=provenance)
    assert created.provenance.kind is wm.ProvenanceKind.P8_PROPOSAL


def test_d_c_proposals_have_no_authority_state_and_review_due_is_derived_from_a_caller_date(handoff) -> None:
    fields = set(pm.WatchProposal.__dataclass_fields__)
    assert not fields & {"status", "author_ref", "reviewed_at", "seq", "revision_id"}
    assert pm.PROPOSAL_CLASS.startswith("NON_AUTHORITATIVE_L0_PROPOSAL")
    w = watch_create()
    t1 = thesis_create(w)
    assert pm.review_due_proposals([w, t1], as_of=DUE - timedelta(days=1)) == ()
    due = pm.review_due_proposals([w, t1], as_of=DUE)
    assert {p.root_id for p in due} == {w.watch_entry_id, t1.thesis_id} and all(p.review_due_on == DUE for p in due)
    fails("INVALID_DATE", pm.review_due_proposals, [w], as_of=datetime(2026, 10, 1, tzinfo=JST))
    fails("HANDOFF_INVALID", pm.watch_proposals, handoff.result)
    assert "OVERDUE" not in {s.value for s in WatchStatus} | {s.value for s in ThesisStatus}
    assert "PROPOSED" not in {s.value for s in WatchStatus}


# ================================================ E 凍結の値との一致 ・禁止の意味（構造）


def test_e_a_duplicated_frozen_vocabulary_matches_the_frozen_definitions() -> None:
    assert set(tm.P8_SCREENER_STATES) == {s.value for s in ScreenerState}
    for value in ("p8iss_" + "a" * 24, "p8iss_" + "A" * 24, "p8iss_" + "a" * 23, "p8sec_" + "a" * 24, "", None, 7):
        assert rm.is_issuer_id(value) == frozen_is_issuer_id(value), value


FORBIDDEN_FIELD_WORDS = {"rank", "score", "priority", "recommend", "recommendation", "buy", "sell", "target",
                         "expected", "weight", "allocation", "position", "conviction", "rating", "preference",
                         "holding", "holdings", "portfolio", "trade", "instruction", "price", "return"}


def test_e_b_no_field_enum_or_identifier_carries_ranking_recommendation_or_trading_semantics() -> None:
    classes = (WatchEntryRevision, P8ProposalProvenance, ManualProvenance, ThesisRevision, P8ScreenEvidence,
               HumanNoteEvidence, InvalidationCondition, pm.WatchProposal, pm.ReviewDueProposal)
    for cls in classes:
        for name in cls.__dataclass_fields__:
            assert not set(name.split("_")) & FORBIDDEN_FIELD_WORDS, (cls.__name__, name)
    for enum in (WatchStatus, ThesisStatus, ChangeKind, tm.EvidenceKind, tm.InvalidationBasis, wm.ProvenanceKind,
                 pm.ProposalKind):
        for member in enum:
            assert not set(member.value.lower().split("_")) & FORBIDDEN_FIELD_WORDS, member
    for prefix in (wm.WATCH_ENTRY_ID_PREFIX, wm.WATCH_REVISION_ID_PREFIX, tm.THESIS_ID_PREFIX,
                   tm.THESIS_REVISION_ID_PREFIX, tm.CONDITION_ID_PREFIX, pm.PROPOSAL_ID_PREFIX):
        assert prefix.startswith("p9") and len(prefix) == 5
    # 自由文は普通の語を検閲しない（人の Thesis が書ける）
    thesis_create(watch_create(), statement="investors may buy or sell for many reasons; the target market grows",
                  risks=("price competition", "return on capital falls"))
