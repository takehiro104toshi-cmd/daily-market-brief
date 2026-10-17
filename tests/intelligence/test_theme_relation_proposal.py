"""P6-B5C — relation 候補 / 人間の決定 / 受理 plan（matrix 1〜58）。

提案は authority ではなく、ACCEPT も authority ではなく、plan も authority ではない。
B5B relation authority への追記は本 gate に存在しない。
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from src.intelligence.theme_intelligence.relation_model import (AssertionClass, RelationProvenance, RelationType,
                                                                SOURCE_ASSERTED_MEANING, SOURCE_ASSERTED_NON_MEANING,
                                                                SourceAttribution, ThemeRelationAssertion, edge_key_of)
from src.intelligence.theme_intelligence.relation_proposal_bridge import (RELATION_PLAN_VERSION, RelationAssertionPlan,
                                                                          RelationBridgeError,
                                                                          plan_relation_assertion_from_accepted_proposal)
from src.intelligence.theme_intelligence.relation_proposal_model import (ACCEPTABLE_ASSERTION_CLASSES,
                                                                         PROPOSER_IS_NOT_AUTHORITY,
                                                                         RelationChangeKind, RelationDecisionKind,
                                                                         RelationProposal, RelationProposalDecision,
                                                                         RelationProposalError,
                                                                         RelationProposalProvenance,
                                                                         RelationProposalType, RelationProposerClass,
                                                                         SourceClaimVerification,
                                                                         source_asserted_refusal,
                                                                         source_authority_available)
from src.intelligence.theme_intelligence.relation_proposal_resolution import (RelationProposalStatus,
                                                                              derive_relation_proposal_status,
                                                                              open_relation_proposals,
                                                                              resolve_active_relation_decision)
from src.intelligence.theme_intelligence.relation_resolution import (EndpointState, endpoint_lookup_from_roots,
                                                                     resolve_relation_graph)
from src.intelligence.themes.model import ProvenanceClass
from tests.intelligence.test_theme_relation import A, ACTOR, ATTRIBUTION, B, C, T0, evidence, retraction

UTC = timezone.utc
DECIDED_AT = T0 + timedelta(hours=1)
PLANNED_AT = T0 + timedelta(hours=2)
MISSING_ASSERTION_ID = "threl_" + "0" * 24
OTHER_SOURCE = SourceAttribution(attributed_to="publisher:other_wire")


def provenance(proposer=RelationProposerClass.RULE, ref: str = "rule:relation_candidate", version: str = "",
               note: str = "") -> RelationProposalProvenance:
    return RelationProposalProvenance(proposer_class=proposer, proposer_ref=ref, rule_version=version, note=note)


def proposal(source=A, target=B, *, relation_type=RelationType.AMPLIFIES, proposer=RelationProposerClass.RULE,
             proposer_ref="rule:relation_candidate", rationale="construction demand lifts electricity use",
             refs=(), attribution=None, change_kind=RelationChangeKind.NEW_RELATION, previous="", at=T0,
             rule_version="", note="") -> RelationProposal:
    return RelationProposal.build(source_theme_root_id=source, target_theme_root_id=target,
                                  relation_type=relation_type, rationale=rationale, evidence_refs=refs,
                                  source_attribution=attribution, change_kind=change_kind,
                                  previous_assertion_id=previous,
                                  provenance=provenance(proposer, proposer_ref, rule_version, note), created_at=at)


def causal(**kw) -> RelationProposal:
    kw.setdefault("refs", (evidence(),))
    return proposal(relation_type=RelationType.CAUSES, **kw)


def sourced(**kw) -> RelationProposal:
    kw.setdefault("refs", (evidence(),))
    kw.setdefault("attribution", ATTRIBUTION)
    kw.setdefault("proposer", RelationProposerClass.SOURCE)
    kw.setdefault("proposer_ref", "publisher:example_wire")
    return proposal(**kw)


DERIVE_VERIFICATION = object()          # P6-B5C-R1: SOURCE_ASSERTED の受理では既定で確認を組み立てる


def verification(candidate, *, attributed_to=None, evidence_ref=None, locus="section:2",
                 summary="the release states that the first theme drives the second", source=None, target=None,
                 relation_type=None, verifier="reviewer:r1", at=None) -> SourceClaimVerification:
    """提案に整合する人間の出典主張確認（既定）。ずらした引数で不一致 case を作る。"""
    ref = evidence_ref if evidence_ref is not None else (candidate.evidence_refs[0] if candidate.evidence_refs
                                                         else evidence())
    named = candidate.source_attribution.attributed_to if candidate.source_attribution is not None else \
        ATTRIBUTION.attributed_to
    return SourceClaimVerification(attributed_to=attributed_to or named, evidence_kind=ref.evidence_kind,
                                   evidence_ref_id=ref.ref_id, assertion_locus=locus, claim_summary=summary,
                                   source_theme_root_id=source or candidate.source_theme_root_id,
                                   target_theme_root_id=target or candidate.target_theme_root_id,
                                   relation_type=relation_type or candidate.relation_type, verified_by=verifier,
                                   verified_at=at or candidate.created_at)


def decide(candidate, kind=RelationDecisionKind.ACCEPT, *, accepted=AssertionClass.HUMAN_ASSERTED,
           actor="reviewer:r1", reason="checked the cited release", at=DECIDED_AT,
           supersedes="", verified=DERIVE_VERIFICATION) -> RelationProposalDecision:
    if verified is DERIVE_VERIFICATION:
        verified = (verification(candidate) if kind is RelationDecisionKind.ACCEPT
                    and accepted is AssertionClass.SOURCE_ASSERTED else None)
    return RelationProposalDecision.build(proposal_id=candidate.proposal_id, decision=kind,
                                          accepted_assertion_class=accepted if kind is RelationDecisionKind.ACCEPT else None,
                                          source_claim_verification=verified, actor_ref=actor, reason=reason,
                                          recorded_at=at, supersedes_decision_id=supersedes)


def lookup(*roots, retired=(), superseded=(), created=None):
    return endpoint_lookup_from_roots({r: (created or T0) for r in (roots or (A, B, C))}, retired=retired,
                                      superseded=superseded)


def plan_of(candidate, decisions, *, endpoint=None, at=PLANNED_AT, existing=()) -> RelationAssertionPlan:
    return plan_relation_assertion_from_accepted_proposal(candidate, tuple(decisions), endpoint_lookup=endpoint or lookup(),
                                                          recorded_at=at, existing_relations=tuple(existing))


def fails_model(code: str, builder) -> None:
    with pytest.raises(RelationProposalError) as info:
        builder()
    assert info.value.code == code, info.value.code


def fails_plan(code: str, *args, **kw) -> RelationBridgeError:
    with pytest.raises(RelationBridgeError) as info:
        plan_of(*args, **kw)
    assert info.value.code == code, info.value.code
    return info.value


def authority_edges(*assertions, retracted_events=()):
    resolution = resolve_relation_graph(list(assertions), list(retracted_events), cutoff=T0 + timedelta(days=30),
                                        endpoint_lookup=lookup())
    return resolution.edges


def b5b_assertion(source=A, target=B, *, relation_type=RelationType.AMPLIFIES,
                  assertion_class=AssertionClass.HUMAN_ASSERTED, rationale="construction demand lifts electricity use",
                  refs=(), attribution=None, previous="", at=T0) -> ThemeRelationAssertion:
    return ThemeRelationAssertion.build(source_theme_root_id=source, target_theme_root_id=target,
                                        relation_type=relation_type, assertion_class=assertion_class,
                                        rationale=rationale, evidence_refs=refs, source_attribution=attribution,
                                        previous_assertion_id=previous, provenance=ACTOR, recorded_at=at)


# ---------------------------------------------------------------- 1〜11 model


@pytest.mark.parametrize("proposer", list(RelationProposerClass))
def test_01_04_every_proposer_class_may_submit_a_candidate(proposer) -> None:
    candidate = (sourced() if proposer is RelationProposerClass.SOURCE
                 else proposal(proposer=proposer, proposer_ref=f"{proposer.value.lower()}:x"))
    assert candidate.proposal_type is RelationProposalType.RELATION_CANDIDATE
    assert candidate.provenance.proposer_class is proposer
    assert [c.value for c in RelationProposerClass] == ["HUMAN", "SOURCE", "RULE", "LLM"]
    assert PROPOSER_IS_NOT_AUTHORITY == "a proposer class describes who proposed, not who asserts"
    assert tuple(c.value for c in ACCEPTABLE_ASSERTION_CLASSES) == ("HUMAN_ASSERTED", "SOURCE_ASSERTED")


def test_05_a_self_relation_never_becomes_a_candidate() -> None:
    fails_model("SELF_RELATION", lambda: proposal(A, A))
    fails_model("UNKNOWN_THEME_ROOT", lambda: proposal("root_x", B))


def test_06_the_candidate_carries_the_four_relation_types_only() -> None:
    for relation_type in RelationType:
        built = causal() if relation_type is RelationType.CAUSES else proposal(relation_type=relation_type)
        assert built.relation_type in tuple(RelationType)
    payload = proposal().as_dict()
    fails_model("INVALID_VOCABULARY", lambda: RelationProposal.from_dict(dict(payload, relation_type="RELATED_TO")))


def test_07_a_candidate_carries_no_score_or_ranking() -> None:
    plain = json.dumps(proposal().as_dict()).lower()
    for token in ("score", "rank", "confidence", "probability", "strength", "weight", "priority"):
        assert token not in plain, token
    for attribute in ("score", "confidence", "strength"):
        assert not hasattr(proposal(), attribute)


def test_08_09_identity_is_content_addressed_and_ignores_the_discovering_mechanism() -> None:
    base = proposal(proposer=RelationProposerClass.RULE, proposer_ref="rule:a")
    same_claim = proposal(proposer=RelationProposerClass.HUMAN, proposer_ref="reviewer:r1")
    later = proposal(at=T0 + timedelta(days=5))
    assert base.proposal_id == same_claim.proposal_id == later.proposal_id
    assert base.proposal_id.startswith("threlprop_")
    identity = base.identity_payload()
    assert "provenance" not in identity and "created_at" not in identity
    assert "provenance" in base.as_dict() and "created_at" in base.as_dict()
    assert base.as_dict() != same_claim.as_dict()          # 同 id ＋ 異 bytes は store で CONFLICT になる


def test_10_11_source_attribution_and_evidence_change_the_claim() -> None:
    base = sourced()
    assert sourced(attribution=OTHER_SOURCE, proposer_ref="publisher:other_wire").proposal_id != base.proposal_id
    assert sourced(refs=(evidence("b"),)).proposal_id != base.proposal_id
    assert proposal(rationale="a different stated reason").proposal_id != proposal().proposal_id
    assert proposal(C, B).proposal_id != proposal().proposal_id
    assert proposal(relation_type=RelationType.MITIGATES).proposal_id != proposal().proposal_id


# ---------------------------------------------------------------- 12〜15 source safety


def test_12_14_a_source_candidate_needs_attribution_citation_and_a_summary() -> None:
    fails_model("MISSING_SOURCE_ATTRIBUTION", lambda: proposal(proposer=RelationProposerClass.SOURCE,
                                                               proposer_ref="publisher:example_wire",
                                                               refs=(evidence(),)))
    fails_model("MISSING_SOURCE_CITATION", lambda: proposal(proposer=RelationProposerClass.SOURCE,
                                                            proposer_ref="publisher:example_wire",
                                                            attribution=ATTRIBUTION, refs=()))
    fails_model("MISSING_FIELD", lambda: sourced(rationale=""))
    assert source_authority_available(sourced()) and not source_authority_available(proposal())


def test_15_a_source_candidate_records_an_attributed_claim_not_a_verified_truth() -> None:
    candidate = sourced()
    accepted = plan_of(candidate, (decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED),))
    assert accepted.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert accepted.source_attribution == ATTRIBUTION
    assert accepted.proposal_origin.proposer_class is RelationProposerClass.SOURCE
    body = accepted.to_plain()
    origin = body.pop("verification_origin")                       # P6-B5C-R1: 凍結文言だけを別に検査する
    assert origin["meaning"] == "a person verified that the cited source asserted this relation"
    assert origin["non_meaning"] == "a person verified that this relation is objectively true"
    plain = json.dumps(body).lower()
    for token in ("true", "proven", "confirmed_truth", "objectively"):
        assert token not in plain, token
    assert SOURCE_ASSERTED_MEANING == "the cited source asserted this relation"
    assert SOURCE_ASSERTED_NON_MEANING == "the system verified this relation as causal truth"


# ---------------------------------------------------------------- 16〜29 decision


def test_16_17_acceptance_names_the_final_authority() -> None:
    human = proposal()
    assert plan_of(human, (decide(human),)).assertion_class is AssertionClass.HUMAN_ASSERTED
    source = sourced()
    accepted = plan_of(source, (decide(source, accepted=AssertionClass.SOURCE_ASSERTED),))
    assert accepted.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert accepted.edge_key == edge_key_of(A, B, RelationType.AMPLIFIES, AssertionClass.SOURCE_ASSERTED,
                                            ATTRIBUTION.attribution_key)


@pytest.mark.parametrize("proposer", [RelationProposerClass.RULE, RelationProposerClass.LLM])
def test_18_21_rule_and_llm_candidates_can_only_become_human_authority(proposer) -> None:
    candidate = causal(proposer=proposer, proposer_ref=f"{proposer.value.lower()}:x")
    accepted = plan_of(candidate, (decide(candidate),))
    assert accepted.assertion_class is AssertionClass.HUMAN_ASSERTED
    assert accepted.proposal_origin.proposer_class is proposer and accepted.source_attribution is None
    laundering = decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED)
    fails_plan("MISSING_SOURCE_ATTRIBUTION", candidate, (laundering,))
    with_source = causal(proposer=proposer, proposer_ref=f"{proposer.value.lower()}:x", attribution=ATTRIBUTION)
    ok = plan_of(with_source, (decide(with_source, accepted=AssertionClass.SOURCE_ASSERTED),))
    assert ok.assertion_class is AssertionClass.SOURCE_ASSERTED and ok.source_attribution == ATTRIBUTION


@pytest.mark.parametrize("kind,status", [(RelationDecisionKind.REJECT, "REJECTED"),
                                         (RelationDecisionKind.DEFER, "OPEN_DEFERRED")])
def test_22_23_reject_and_defer_close_or_hold_without_a_final_authority(kind, status) -> None:
    candidate = proposal()
    decision = decide(candidate, kind)
    assert decision.accepted_assertion_class is None
    assert derive_relation_proposal_status(candidate, (decision,)).value == status
    fails_plan("PROPOSAL_NOT_ACCEPTED", candidate, (decision,))
    fails_model("ACCEPTED_AUTHORITY_FORBIDDEN", lambda: RelationProposalDecision.build(
        proposal_id=candidate.proposal_id, decision=kind, accepted_assertion_class=AssertionClass.HUMAN_ASSERTED,
        actor_ref="reviewer:r1", reason="x", recorded_at=DECIDED_AT))
    fails_model("MISSING_ACCEPTED_AUTHORITY", lambda: RelationProposalDecision.build(
        proposal_id=candidate.proposal_id, decision=RelationDecisionKind.ACCEPT, actor_ref="reviewer:r1",
        reason="x", recorded_at=DECIDED_AT))


def test_24_a_later_human_decision_supersedes_an_earlier_one() -> None:
    candidate = proposal()
    rejected = decide(candidate, RelationDecisionKind.REJECT, reason="not yet verified")
    accepted = decide(candidate, at=DECIDED_AT + timedelta(hours=1), supersedes=rejected.decision_id)
    assert derive_relation_proposal_status(candidate, (rejected, accepted)) is RelationProposalStatus.ACCEPTED
    built = plan_of(candidate, (rejected, accepted))
    assert built.decision_origin.decision_id == accepted.decision_id
    assert built.decision_origin.supersedes_decision_id == rejected.decision_id


@pytest.mark.parametrize("status,build", [
    ("OPEN", lambda c: ()),
    ("OPEN_UNRESOLVED", lambda c: (decide(c, reason="first look"), decide(c, reason="second look"))),
    ("INVALID_DECISION_HISTORY", lambda c: (decide(c, supersedes="threldec_" + "0" * 24),))])
def test_25_27_broken_or_ambiguous_decision_history(status, build) -> None:
    candidate = proposal()
    decisions = build(candidate)
    assert derive_relation_proposal_status(candidate, decisions).value == status
    error = fails_plan("PROPOSAL_NOT_ACCEPTED", candidate, decisions)
    assert error.detail == status


def test_27b_a_decision_fork_is_unresolved_and_a_cycle_is_invalid() -> None:
    candidate = proposal()
    first = decide(candidate, RelationDecisionKind.DEFER, reason="hold")
    left = decide(candidate, reason="accept one", supersedes=first.decision_id)
    right = decide(candidate, reason="accept two", supersedes=first.decision_id)
    resolution = resolve_active_relation_decision(candidate.proposal_id, (first, left, right))
    assert resolution.diagnostics == ("FORK",) and resolution.active_decision is None
    other = proposal(C, B)
    wrong = decide(other, reason="decides another candidate")
    mixed = decide(candidate, reason="chained to the wrong proposal", supersedes=wrong.decision_id)
    assert resolve_active_relation_decision(candidate.proposal_id, (wrong, mixed)).diagnostics == (
        "WRONG_PROPOSAL_PREDECESSOR",)


def test_28_decision_order_does_not_decide_the_winner() -> None:
    candidate = proposal()
    deferred = decide(candidate, RelationDecisionKind.DEFER, reason="hold")
    accepted = decide(candidate, at=DECIDED_AT + timedelta(hours=1), supersedes=deferred.decision_id)
    base = plan_of(candidate, (deferred, accepted)).to_plain()
    for seed in range(10):
        decisions = [deferred, accepted]
        random.Random(seed).shuffle(decisions)
        assert plan_of(candidate, decisions).to_plain() == base, seed
    assert open_relation_proposals((candidate,), (deferred,)) == ((candidate.proposal_id,
                                                                   RelationProposalStatus.OPEN_DEFERRED),)


@pytest.mark.parametrize("actor_class", [ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL])
def test_29_a_decision_actor_is_always_human(actor_class) -> None:
    candidate = proposal()
    fails_model("FORBIDDEN_DECISION_AUTHORITY", lambda: RelationProposalDecision(
        decision_id="threldec_" + "0" * 24, proposal_id=candidate.proposal_id, decision=RelationDecisionKind.ACCEPT,
        accepted_assertion_class=AssertionClass.HUMAN_ASSERTED, actor_class=actor_class, actor_ref="rule:x",
        reason="automatic", recorded_at=DECIDED_AT))


# ---------------------------------------------------------------- 30〜50 plan


def test_30_an_accepted_candidate_produces_a_plan() -> None:
    candidate = causal()
    built = plan_of(candidate, (decide(candidate),))
    assert isinstance(built, RelationAssertionPlan) and built.plan_version == RELATION_PLAN_VERSION
    assert built.relation_type is RelationType.CAUSES and built.recorded_at == PLANNED_AT
    assert built.change_kind is RelationChangeKind.NEW_RELATION and built.previous_assertion_id == ""
    assert built.source_endpoint is EndpointState.EXISTS_AT_CUTOFF


def test_31_35_only_an_accepted_candidate_can_be_planned() -> None:
    candidate = proposal()
    for decisions in ((), (decide(candidate, RelationDecisionKind.DEFER),), (decide(candidate, RelationDecisionKind.REJECT),),
                      (decide(candidate, reason="a"), decide(candidate, reason="b")),
                      (decide(candidate, supersedes="threldec_" + "0" * 24),)):
        fails_plan("PROPOSAL_NOT_ACCEPTED", candidate, decisions)
    fails_plan("INVALID_PROPOSAL_TYPE", object(), ())


def test_36_a_causal_plan_requires_evidence() -> None:
    bare = proposal(relation_type=RelationType.CAUSES)
    assert bare.evidence_refs == ()
    fails_plan("MISSING_CAUSAL_EVIDENCE", bare, (decide(bare),))
    assert plan_of(causal(), (decide(causal()),)).evidence_refs


def test_37_39_final_authority_and_both_origins_stay_auditable() -> None:
    candidate = causal(proposer=RelationProposerClass.LLM, proposer_ref="model:candidate_reader",
                       rule_version="0.1.0", note="drafted from the release text", attribution=ATTRIBUTION)
    decision = decide(candidate, reason="verified the release myself")
    built = plan_of(candidate, (decision,))
    assert built.assertion_class is AssertionClass.HUMAN_ASSERTED and built.source_attribution is None
    origin = built.proposal_origin
    assert origin.proposer_class is RelationProposerClass.LLM and origin.proposer_ref == "model:candidate_reader"
    assert origin.rule_version == "0.1.0" and origin.proposer_note == "drafted from the release text"
    assert origin.proposal_id == candidate.proposal_id and origin.proposal_created_at == candidate.created_at
    assert origin.proposal_source_attribution == ATTRIBUTION.attributed_to     # 提案側の帰属は失われない
    assert built.decision_origin.actor_class is ProvenanceClass.HUMAN
    assert built.decision_origin.actor_ref == "reviewer:r1" and built.decision_origin.reason == "verified the release myself"
    assert built.decision_origin.accepted_assertion_class is AssertionClass.HUMAN_ASSERTED


@pytest.mark.parametrize("created", [{B: T0}, {A: T0, B: T0 + timedelta(days=30)}])
def test_40_41_an_endpoint_that_is_unknown_or_not_yet_created_fails_closed(created) -> None:
    candidate = proposal()
    error = fails_plan("ENDPOINT_NOT_AVAILABLE", candidate, (decide(candidate),),
                       endpoint=endpoint_lookup_from_roots(created))
    assert error.detail.split(":")[1] in ("UNKNOWN_ROOT", "NOT_CREATED_YET")


def test_42_43_retired_and_superseded_endpoints_are_planned_without_rewriting() -> None:
    candidate = proposal()
    retired = plan_of(candidate, (decide(candidate),), endpoint=lookup(A, B, retired=(B,)))
    assert retired.target_endpoint is EndpointState.RETIRED and "ENDPOINT_RETIRED:TARGET" in retired.diagnostics
    superseded = plan_of(candidate, (decide(candidate),), endpoint=lookup(A, B, superseded=(A,)))
    assert superseded.source_endpoint is EndpointState.SUPERSEDED
    assert "ENDPOINT_SUPERSEDED:SOURCE" in superseded.diagnostics
    assert superseded.source_theme_root_id == A and superseded.target_theme_root_id == B


def test_44_47_plan_time_must_be_aware_and_not_precede_its_inputs() -> None:
    candidate = causal()
    decisions = (decide(candidate),)
    fails_plan("INVALID_RECORDED_AT", candidate, decisions, at=datetime(2026, 9, 21))
    fails_plan("INVALID_RECORDED_AT", candidate, decisions, at="2026-09-21T00:00:00+00:00")
    fails_plan("PLAN_BEFORE_DECISION", candidate, decisions, at=DECIDED_AT - timedelta(seconds=1))
    late = causal(at=PLANNED_AT + timedelta(days=1))
    fails_plan("PLAN_BEFORE_PROPOSAL", late, (decide(late, at=PLANNED_AT + timedelta(days=1)),), at=PLANNED_AT)
    # evidence_time <= created_at（model 不変条件）かつ plan >= created_at なので、plan >= evidence_time は含意される。
    # 防御的な検査は残しつつ、ここでは等号境界が通ることと含意の成立を固定する。
    at_boundary = proposal(relation_type=RelationType.CAUSES, refs=(evidence(at=T0),), at=T0)
    built = plan_of(at_boundary, (decide(at_boundary, at=T0),), at=T0)
    assert built.recorded_at == T0 == built.evidence_refs[0].evidence_time
    assert all(e.evidence_time <= at_boundary.created_at <= built.recorded_at for e in built.evidence_refs)
    fails_model("EVIDENCE_AFTER_RECORD", lambda: proposal(refs=(evidence(at=T0 + timedelta(days=1)),), at=T0))


def test_48_50_the_plan_is_deterministic_and_carries_no_authority_identity() -> None:
    candidate = causal()
    decision = decide(candidate)
    base = plan_of(candidate, (decision,))
    assert plan_of(candidate, (decision,)) == base
    assert base.canonical_line() == plan_of(candidate, (decision,)).canonical_line()
    plain = base.to_plain()
    assert "relation_assertion_id" not in plain and not hasattr(base, "relation_assertion_id")
    assert "proposal_id" not in plain and plain["proposal_origin"]["proposal_id"] == candidate.proposal_id
    assert list(json.loads(base.canonical_line())) == sorted(plain)


def test_49_the_plan_can_build_a_b5b_assertion_without_the_bridge_doing_it(tmp_path) -> None:
    candidate = sourced()
    built = plan_of(candidate, (decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED),))
    assertion = ThemeRelationAssertion.build(
        source_theme_root_id=built.source_theme_root_id, target_theme_root_id=built.target_theme_root_id,
        relation_type=built.relation_type, assertion_class=built.assertion_class, rationale=built.rationale,
        evidence_refs=built.evidence_refs, source_attribution=built.source_attribution,
        previous_assertion_id=built.previous_assertion_id,
        provenance=RelationProvenance(actor_ref=built.decision_origin.actor_ref), recorded_at=built.recorded_at)
    assert assertion.edge_key == built.edge_key and assertion.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------- 51〜58 既存 authority との相互作用


def test_51_an_already_authoritative_relation_is_refused() -> None:
    existing = b5b_assertion()
    candidate = proposal()
    fails_plan("RELATION_ALREADY_AUTHORITATIVE", candidate, (decide(candidate),),
               existing=authority_edges(existing))


def test_52_a_retracted_relation_is_never_auto_restored() -> None:
    existing = b5b_assertion()
    edges = authority_edges(existing, retracted_events=(retraction(existing),))
    assert edges[0].edge_state.value == "RETRACTED"
    candidate = proposal()
    fails_plan("RELATION_RETRACTED_REQUIRES_GOVERNANCE", candidate, (decide(candidate),), existing=edges)


def test_53_a_semantically_different_relation_is_not_merged() -> None:
    existing = b5b_assertion(relation_type=RelationType.MITIGATES)
    candidate = proposal(relation_type=RelationType.AMPLIFIES)
    built = plan_of(candidate, (decide(candidate),), existing=authority_edges(existing))
    assert built.relation_type is RelationType.AMPLIFIES
    assert built.edge_key != authority_edges(existing)[0].edge_key
    same_edge = proposal(rationale="a materially different reason")
    fails_plan("EDGE_ALREADY_STARTED", same_edge, (decide(same_edge),), existing=authority_edges(b5b_assertion()))


def test_54_a_new_relation_plan_needs_no_authority_view() -> None:
    candidate = proposal()
    built = plan_of(candidate, (decide(candidate),))
    assert built.change_kind is RelationChangeKind.NEW_RELATION and built.previous_assertion_id == ""


def test_55_58_a_correction_names_its_predecessor_explicitly() -> None:
    existing = b5b_assertion()
    edges = authority_edges(existing)
    correction = proposal(change_kind=RelationChangeKind.CORRECTION, previous=existing.relation_assertion_id,
                          rationale="a revised reason")
    built = plan_of(correction, (decide(correction),), existing=edges)
    assert built.change_kind is RelationChangeKind.CORRECTION
    assert built.previous_assertion_id == existing.relation_assertion_id
    assert built.proposal_origin.change_kind is RelationChangeKind.CORRECTION
    fails_model("MISSING_PREDECESSOR", lambda: proposal(change_kind=RelationChangeKind.CORRECTION))
    fails_model("PREDECESSOR_FORBIDDEN", lambda: proposal(previous=existing.relation_assertion_id))
    orphan = proposal(change_kind=RelationChangeKind.CORRECTION, previous=MISSING_ASSERTION_ID,
                      rationale="a revised reason")
    fails_plan("PREDECESSOR_NOT_FOUND", orphan, (decide(orphan),), existing=edges)
    other_edge = b5b_assertion(relation_type=RelationType.MITIGATES)
    wrong = proposal(change_kind=RelationChangeKind.CORRECTION, previous=other_edge.relation_assertion_id,
                     rationale="a revised reason")
    fails_plan("PREDECESSOR_WRONG_EDGE", wrong, (decide(wrong),), existing=authority_edges(existing, other_edge))
    unchanged = proposal(change_kind=RelationChangeKind.CORRECTION, previous=existing.relation_assertion_id)
    fails_plan("RELATION_ALREADY_AUTHORITATIVE", unchanged, (decide(unchanged),), existing=edges)


def test_58b_a_correction_must_continue_from_the_terminal_assertion() -> None:
    first = b5b_assertion()
    second = b5b_assertion(rationale="an earlier revision", previous=first.relation_assertion_id,
                           at=T0 + timedelta(days=1))
    edges = authority_edges(first, second)
    stale = proposal(change_kind=RelationChangeKind.CORRECTION, previous=first.relation_assertion_id,
                     rationale="a later revision")
    fails_plan("PREDECESSOR_NOT_TERMINAL", stale, (decide(stale),), existing=edges)


# ---------------------------------------------------------------- 80〜95 出典主張の確認（P6-B5C-R1）


def test_80_the_verification_is_immutable_and_binds_every_semantic_axis() -> None:
    import dataclasses
    subject = verification(sourced())
    with pytest.raises(dataclasses.FrozenInstanceError):
        subject.assertion_locus = "section:9"                      # type: ignore[misc]
    bound = set(dataclasses.asdict(subject))
    assert {"attributed_to", "evidence_kind", "evidence_ref_id", "assertion_locus", "claim_summary",
            "source_theme_root_id", "target_theme_root_id", "relation_type", "verifier_class", "verified_by",
            "verified_at"} <= bound
    assert not [name for name in bound if name in ("verified", "is_valid", "ok", "approved")]


def test_81_the_verification_serializes_deterministically() -> None:
    subject = verification(sourced())
    assert json.loads(json.dumps(subject.as_dict())) == subject.as_dict()
    assert SourceClaimVerification.from_dict(subject.as_dict()) == subject
    assert subject.evidence_key == f"{subject.evidence_kind.value}:{subject.evidence_ref_id}"
    assert subject.attribution_key == ATTRIBUTION.attribution_key


def test_82_the_verification_participates_in_the_decision_identity() -> None:
    candidate = sourced()
    left = decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED,
                  verified=verification(candidate, locus="section:2"))
    right = decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED,
                   verified=verification(candidate, locus="section:7"))
    assert left.decision_id != right.decision_id
    assert left.identity_payload()["source_claim_verification"] != right.identity_payload()["source_claim_verification"]
    same = decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED, verified=verification(candidate, locus="section:2"))
    assert same.decision_id == left.decision_id                    # 同じ authorization は収束する


@pytest.mark.parametrize("field,code", [("assertion_locus", "MISSING_FIELD"), ("claim_summary", "MISSING_FIELD"),
                                        ("attributed_to", "MISSING_FIELD"), ("verified_by", "MISSING_FIELD")])
def test_83_86_every_required_text_field_is_required(field, code) -> None:
    candidate = sourced()
    base = verification(candidate).as_dict()
    base[field] = ""
    fails_model(code, lambda: SourceClaimVerification.from_dict(base))


def test_87_the_verification_time_must_be_aware() -> None:
    candidate = sourced()
    base = verification(candidate)
    fails_model("INVALID_TIME", lambda: SourceClaimVerification(
        attributed_to=base.attributed_to, evidence_kind=base.evidence_kind, evidence_ref_id=base.evidence_ref_id,
        assertion_locus=base.assertion_locus, claim_summary=base.claim_summary,
        source_theme_root_id=base.source_theme_root_id, target_theme_root_id=base.target_theme_root_id,
        relation_type=base.relation_type, verified_by=base.verified_by, verified_at=datetime(2026, 9, 20)))


def test_88_the_verification_rejects_a_self_relation_and_an_unknown_root() -> None:
    candidate = sourced()
    base = verification(candidate).as_dict()
    fails_model("SELF_RELATION", lambda: SourceClaimVerification.from_dict({**base, "target_theme_root_id": A}))
    fails_model("UNKNOWN_THEME_ROOT", lambda: SourceClaimVerification.from_dict({**base, "source_theme_root_id": "x"}))


def test_89_the_verification_ref_id_must_match_its_evidence_kind() -> None:
    candidate = sourced()
    base = verification(candidate).as_dict()
    fails_model("REF_ID_KIND_MISMATCH", lambda: SourceClaimVerification.from_dict({**base, "evidence_kind": "NEWS_ITEM"}))


def test_90_the_verification_refuses_a_machine_specific_path_or_a_credential_url() -> None:
    candidate = sourced()
    base = verification(candidate).as_dict()
    drive = "D" + ":" + chr(92) + "research" + chr(92) + "note"
    fails_model("PROHIBITED_CONTENT", lambda: SourceClaimVerification.from_dict({**base, "assertion_locus": drive}))
    leaked = "https://user:pw@example.invalid/release"
    fails_model("PROHIBITED_CONTENT", lambda: SourceClaimVerification.from_dict({**base, "claim_summary": leaked}))


@pytest.mark.parametrize("proposer", [RelationProposerClass.RULE, RelationProposerClass.LLM])
def test_91_92_a_source_backed_machine_proposal_may_become_source_asserted(proposer) -> None:
    """RULE / LLM が出典裏付きで提案し、人間が確認して受理すれば SOURCE_ASSERTED になれる。"""
    candidate = proposal(proposer=proposer, proposer_ref=f"{proposer.value.lower()}:extractor",
                         attribution=ATTRIBUTION, refs=(evidence(),),
                         rationale="the release states the first theme drives the second")
    plan = plan_of(candidate, (decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED),))
    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert plan.proposal_origin.proposer_class is proposer
    assert plan.verification_origin.verifier_class is ProvenanceClass.HUMAN


@pytest.mark.parametrize("proposer", [RelationProposerClass.RULE, RelationProposerClass.LLM])
def test_93_94_a_machine_inference_with_a_citation_only_cannot(proposer) -> None:
    """citation を付けただけの機械推論は SOURCE_ASSERTED にならない（帰属が無い）。"""
    candidate = proposal(proposer=proposer, proposer_ref=f"{proposer.value.lower()}:reasoner", refs=(evidence(),),
                         rationale="inferred without a source claim")
    decision = decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED)
    assert source_asserted_refusal(candidate, decision) == "MISSING_SOURCE_ATTRIBUTION"
    fails_plan("MISSING_SOURCE_ATTRIBUTION", candidate, (decision,))
    assert plan_of(candidate, (decide(candidate),)).assertion_class is AssertionClass.HUMAN_ASSERTED


def test_95_the_verification_records_a_locus_not_a_reproduction_of_the_source() -> None:
    """長文の引用を要求しない。短い所在と主張の要約だけを記録する（著作権面の抑制）。"""
    from src.intelligence.theme_intelligence.relation_proposal_model import MAX_LOCUS_LEN, MAX_TEXT_LEN
    assert MAX_LOCUS_LEN == 200 and MAX_TEXT_LEN == 240
    candidate = sourced()
    base = verification(candidate).as_dict()
    fails_model("FIELD_TOO_LONG", lambda: SourceClaimVerification.from_dict({**base, "claim_summary": "x" * 241}))
    fails_model("FIELD_TOO_LONG", lambda: SourceClaimVerification.from_dict({**base, "assertion_locus": "y" * 201}))
