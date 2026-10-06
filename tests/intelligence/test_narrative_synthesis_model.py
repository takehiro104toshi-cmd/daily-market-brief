"""P7-A1 — Narrative の意味論と純 model の test matrix A〜AO（境界の guard AP〜AS は `test_narrative_intelligence_boundary.py`）。

契約: `docs/databank/PHASE7_NARRATIVE_SEMANTICS_MODEL_CONTRACT.md`。
"""
from __future__ import annotations

import dataclasses
import itertools
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

import pytest

from src.intelligence.core.ids import content_id
from src.intelligence.narrative_intelligence import synthesis_model as m
from src.intelligence.narrative_intelligence.synthesis_model import (
    ALLOWED_TRIPLES, MAX_CLAIMS, MAX_KNOWLEDGE_PINS, MAX_REFS_PER_CLAIM, MAX_SUBJECTS, ClaimKind, EpistemicClass,
    EvidenceAttachmentRef, EvidenceItemRef, InvalidationConditionRef, MechanismComponentRef, NarrativeClaim,
    NarrativeKind, NarrativeModelError, NarrativeSynthesis, Predicate, RelationAssertionRef, ThemeChangeRef,
    ThemeObservationRef, UncertaintyCode, canonical_json, ref_from_dict)

REPO_ROOT = Path(__file__).resolve().parents[2]
R1, R2, R3, R4 = (f"theme_01J{'0' * 22}{c}" for c in "1234")
OBS = {R1: "thobs_" + "a" * 24, R2: "thobs_" + "b" * 24, R3: "thobs_" + "c" * 24, R4: "thobs_" + "d" * 24}
CERTAINTY = {R1: "EVIDENCE_SUPPORTED_MECHANISM", R2: "HYPOTHESIZED_MECHANISM", R3: "OBSERVED_ASSOCIATION",
             R4: "EXPLICIT_SOURCE_CAUSAL_CLAIM"}
REL1, REL2, REL3 = ("threl_" + c * 24 for c in "123")
CUTOFF = datetime(2026, 3, 31, 6, 0, tzinfo=timezone.utc)
T0 = CUTOFF - timedelta(days=30)
PINS = (("narrative_semantics", "0.1.0"), ("theme_resolver", "0.1.0"))
DIGEST = "narin_" + "1" * 24
RI, OF, DS, UN, AH = ("REVIEWED_INTERPRETATION", "OBSERVED_FACT", "DERIVED_SYNTHESIS", "UNCERTAINTY",
                      "ALTERNATIVE_HYPOTHESIS")


# ---------------------------------------------------------------- builders

def obs(root, **kw):
    return ThemeObservationRef(root_id=root, observation_id=kw.get("observation_id", OBS[root]),
                               governance_position=kw.get("position", "ACCEPTED"),
                               mechanism_certainty=kw.get("certainty", CERTAINTY[root]))


def att(root, ref_id="fact_a1", role="SUPPORTS", kind=None, **kw):
    kind = kind or {"fact": "FACT", "obs": "OBSERVATION", "doc": "SOURCE_DOCUMENT", "news": "NEWS_ITEM"}[
        ref_id.split("_")[0]]
    return EvidenceAttachmentRef(root_id=root, observation_id=kw.get("observation_id", OBS[root]), ref_id=ref_id,
                                 evidence_kind=kind, consequence_key=kw.get("consequence", ""), role=role,
                                 role_provenance=kw.get("provenance", "HUMAN"), attached_at=kw.get("at", T0),
                                 invalidation_condition_key=kw.get("condition", ""))


def item(ref_id="fact_a1", kind="FACT", at=T0, quality="RELIABLE"):
    return EvidenceItemRef(ref_id=ref_id, evidence_kind=kind, evidence_time=at, time_quality=quality)


def comp(root, ctype="DRIVER", key="rate_path"):
    return MechanismComponentRef(root_id=root, observation_id=OBS[root], component_type=ctype, component_key=key)


def cond(root, key="curve_reverts"):
    return InvalidationConditionRef(root_id=root, observation_id=OBS[root], condition_key=key)


def chg(root, kind="EVIDENCE_ADDED", facet="evidence", subject="fact_a1#", start=T0, end=CUTOFF):
    return ThemeChangeRef(root_id=root, from_cutoff=start, to_cutoff=end, change_kind=kind, facet=facet,
                          subject_id=subject)


def rel(source, target, rid=REL1, klass="HUMAN_ASSERTED", rtype="CAUSES"):
    return RelationAssertionRef(relation_assertion_id=rid, source_root_id=source, target_root_id=target,
                                relation_type=rtype, assertion_class=klass)


def C(klass, kind, predicate, *refs, code=None):
    return NarrativeClaim(epistemic_class=klass, claim_kind=kind, predicate=predicate, refs=refs,
                          uncertainty_code=code)


def state(root, **kw):
    return C(RI, "STATE", "THEME_REVIEWED_STATE", obs(root, **kw))


def mechanism(root, ctype="DRIVER", key="rate_path"):
    return C(RI, "MECHANISM", "RECORDS_MECHANISM_COMPONENT", comp(root, ctype, key))


def evidence(ref):
    return C(RI, "EVIDENCE", "EVIDENCE_ATTACHED", ref)


def fact(ref):
    return C(OF, "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", ref)


def change(ref):
    return C(DS, "CHANGE", "CHANGED_BETWEEN_CUTOFFS", ref)


def condition(root, key="curve_reverts"):
    return C(RI, "INVALIDATION", "RECORDS_INVALIDATION_CONDITION", cond(root, key))


def invalidating(root, ref_id="fact_a3", key="curve_reverts"):
    return C(RI, "INVALIDATION", "INVALIDATING_EVIDENCE_ATTACHED", cond(root, key),
             att(root, ref_id, "INVALIDATES", condition=key))


def relation(source, target, rid=REL1, klass="HUMAN_ASSERTED"):
    predicate = "HUMAN_ASSERTED_RELATION" if klass == "HUMAN_ASSERTED" else "SOURCE_ASSERTED_RELATION"
    return C(RI, "RELATION", predicate, rel(source, target, rid, klass), obs(source), obs(target))


def uncertain(code, root, *extra):
    kind = "MECHANISM" if code == "MECHANISM_HYPOTHESIZED" else "EVIDENCE"
    return C(UN, kind, "IS_UNCERTAIN", obs(root), *extra, code=code)


def alternative(ref_id, *roots):
    refs = [r for root in roots for r in (obs(root), att(root, ref_id))]
    return C(AH, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE", *refs)


def synth(kind, subjects, claims, **kw):
    return NarrativeSynthesis(kind=kind, subject_root_ids=tuple(subjects), cutoff=kw.get("cutoff", CUTOFF),
                              knowledge_pins=kw.get("pins", PINS), input_digest=kw.get("digest", DIGEST),
                              claims=tuple(claims))


def state_claims():
    """THEME_STATE（subject R1）の全部入り。WHAT / WHY / EVIDENCE / CHANGE / RELATIONS / UNCERTAINTY / INVALIDATION /
    ALTERNATIVES をすべて構造で持つ。"""
    return [state(R1), mechanism(R1), evidence(att(R1, "fact_a1")), fact(item("fact_a1")), change(chg(R1)),
            condition(R1), invalidating(R1), relation(R1, R2), relation(R3, R1, REL2, "SOURCE_ASSERTED"),
            uncertain("STALE_EVIDENCE", R1), alternative("fact_a1", R1, R2)]


def set_claims():
    """THEME_SET（subject R1・R2）。R2 は仮説の機構と、支持と反証の両方の evidence を持つ。"""
    return [state(R1), state(R2), mechanism(R1), mechanism(R2, "TRANSMISSION_CHANNEL", "credit_spread"),
            uncertain("MECHANISM_HYPOTHESIZED", R2), evidence(att(R2, "obs_b1")),
            evidence(att(R2, "news_b2", "CONTRADICTS")),
            uncertain("CONTESTED_EVIDENCE", R2, att(R2, "obs_b1"), att(R2, "news_b2", "CONTRADICTS")),
            fact(item("obs_b1", "OBSERVATION")), relation(R1, R2), relation(R2, R3, REL2, "SOURCE_ASSERTED"),
            alternative("fact_a1", R1, R2), change(chg(R2, "GOVERNANCE_CHANGED", "governance", "thgov_" + "e" * 24))]


def state_synthesis(**kw):
    return synth("THEME_STATE", [R1], kw.pop("claims", state_claims()), **kw)


def set_synthesis(**kw):
    return synth("THEME_SET", kw.pop("subjects", [R1, R2]), kw.pop("claims", set_claims()), **kw)


def fails(expected, fn, *args, **kwargs):
    with pytest.raises(NarrativeModelError) as info:
        fn(*args, **kwargs)
    assert info.value.code == expected, (info.value.code, info.value.detail)
    return info.value


def payload(synthesis):
    return json.loads(synthesis.to_canonical_json())


# ================================================================ A〜B 正しい THEME_STATE ／ THEME_SET

def test_a_a_valid_theme_state_synthesis_is_built() -> None:
    synthesis = state_synthesis()
    assert synthesis.kind is NarrativeKind.THEME_STATE and synthesis.subject_root_ids == (R1,)
    assert synthesis.cutoff == CUTOFF and synthesis.knowledge_pins == PINS and synthesis.input_digest == DIGEST
    assert len(synthesis.claims) == len(state_claims())


def test_a_the_theme_state_answers_every_question_structurally_without_prose() -> None:
    claims = state_synthesis().claims
    assert {c.claim_kind for c in claims} == set(ClaimKind)                   # WHAT / WHY / EVIDENCE / CHANGE / RELATIONS / INVALIDATION
    assert {c.epistemic_class for c in claims} == set(EpistemicClass)         # 事実・解釈・派生・不確実性・代替を区別する
    assert {c.predicate for c in claims} == set(Predicate)
    for claim in claims:                                                      # 自由文なし: enum・ref の組・id・code だけ
        values = [getattr(claim, f.name) for f in dataclasses.fields(claim)]
        assert all(isinstance(value, (Enum, tuple)) or value is None or value == claim.claim_id for value in values)


def test_b_a_valid_theme_set_synthesis_is_built() -> None:
    synthesis = set_synthesis()
    assert synthesis.kind is NarrativeKind.THEME_SET and synthesis.subject_root_ids == (R1, R2)
    three = set_synthesis(subjects=[R3, R1, R2], claims=set_claims() + [state(R3)])
    assert three.subject_root_ids == (R1, R2, R3)


def test_b_the_theme_set_holds_contested_and_hypothesized_readings_side_by_side() -> None:
    codes = {c.uncertainty_code for c in set_synthesis().claims if c.uncertainty_code}
    assert codes == {UncertaintyCode.CONTESTED_EVIDENCE, UncertaintyCode.MECHANISM_HYPOTHESIZED}


# ================================================================ C〜D cardinality

@pytest.mark.parametrize("subjects", [[], [R1, R2]])
def test_c_theme_state_requires_exactly_one_subject(subjects) -> None:
    fails("THEME_STATE_REQUIRES_ONE_SUBJECT", synth, "THEME_STATE", subjects, [state(R1), state(R2)])


def test_c_the_single_subject_needs_its_reviewed_state_claim() -> None:
    fails("SUBJECT_STATE_REQUIRED", synth, "THEME_STATE", [R1], [uncertain("STALE_EVIDENCE", R1)])
    fails("UNREVIEWED_THEME_REFERENCE", synth, "THEME_STATE", [R1], [mechanism(R1)])


@pytest.mark.parametrize("subjects", [[], [R1]])
def test_d_theme_set_requires_two_or_more_subjects(subjects) -> None:
    fails("THEME_SET_REQUIRES_TWO_OR_MORE_SUBJECTS", synth, "THEME_SET", subjects, [state(R1)])


def test_d_theme_set_subjects_are_unique_bounded_and_each_stated() -> None:
    fails("DUPLICATE_SUBJECT", synth, "THEME_SET", [R1, R1, R2], [state(R1), state(R2)])
    roots = [f"theme_01K{'0' * 21}{n:02d}" for n in range(MAX_SUBJECTS + 1)]
    fails("TOO_MANY_SUBJECTS", synth, "THEME_SET", roots, [state(R1)])
    fails("SUBJECT_STATE_REQUIRED", synth, "THEME_SET", [R1, R2], [state(R1)])


# ================================================================ E〜F 順位・確信度の field なし

RANKING_WORDS = ("rank", "score", "priority", "weight", "dominant", "primary", "winner", "beneficiar", "top", "best",
                 "order", "strength", "confidence", "probability", "likelihood")
MODEL_TYPES = (NarrativeSynthesis, NarrativeClaim, ThemeObservationRef, MechanismComponentRef, InvalidationConditionRef,
               EvidenceAttachmentRef, EvidenceItemRef, ThemeChangeRef, RelationAssertionRef)


@pytest.mark.parametrize("model_type", MODEL_TYPES)
def test_e_no_model_field_can_carry_a_ranking_or_a_confidence(model_type) -> None:
    for f in dataclasses.fields(model_type):
        assert not any(word in f.name.lower() for word in RANKING_WORDS), f.name
        assert not re.search(r"\b(int|float|Decimal|bool)\b", str(f.type)), (f.name, f.type)


def test_e_the_theme_set_has_no_order_between_subjects() -> None:
    forward = set_synthesis(subjects=[R1, R2])
    backward = set_synthesis(subjects=[R2, R1], claims=list(reversed(set_claims())))
    assert forward.synthesis_id == backward.synthesis_id
    assert forward.to_canonical_json() == backward.to_canonical_json()
    assert forward.subject_root_ids == (R1, R2)                              # id の並び（非意味的）。順位ではない


@pytest.mark.parametrize("name", ["rank", "ranking", "priority", "dominant_theme", "primary_theme", "winner",
                                  "beneficiary", "beneficiaries", "weight", "strength"])
def test_e_ranking_fields_are_rejected_in_serialized_form(name) -> None:
    data = payload(set_synthesis())
    data[name] = "R1"
    fails("PROHIBITED_FIELD", NarrativeSynthesis.from_dict, data)
    data = payload(set_synthesis())
    data["claims"][0][name] = "1"
    fails("PROHIBITED_FIELD", NarrativeSynthesis.from_dict, data)


@pytest.mark.parametrize("name", ["confidence", "score", "probability", "likelihood"])
def test_f_confidence_fields_are_rejected_everywhere(name) -> None:
    data = payload(state_synthesis())
    data["claims"][0]["refs"][0][name] = "0.9"
    fails("PROHIBITED_FIELD", NarrativeSynthesis.from_dict, data)
    data = payload(state_synthesis())
    data[name] = "high"
    fails("PROHIBITED_FIELD", NarrativeSynthesis.from_dict, data)


def test_f_vocabularies_carry_no_numbers_or_ranking_words() -> None:
    for enum_type in (NarrativeKind, EpistemicClass, ClaimKind, Predicate, UncertaintyCode, m.MechanismCertainty):
        for member in enum_type:
            assert not any(ch.isdigit() for ch in member.value), member
            assert not any(word.upper() in member.value for word in ("RANK", "SCORE", "WIN", "DOMINANT", "BEST",
                                                                      "TOP", "PROBAB", "CONFIDENCE", "WEIGHT")), member


# ================================================================ G〜I 予測・monitoring・B7 の ref なし

@pytest.mark.parametrize("ref_type", ["PREDICTION", "EVALUATION", "CALIBRATION", "MARKET_SIGNAL", "COMPASS_DRAFT"])
def test_g_prediction_and_signal_refs_do_not_exist(ref_type) -> None:
    fails("PROHIBITED_REF_TYPE", ref_from_dict, {"ref_type": ref_type, "id": "x"})


@pytest.mark.parametrize("name", ["prediction", "forecast", "target_price", "direction", "signal", "recommendation"])
def test_g_prediction_fields_are_rejected(name) -> None:
    data = payload(state_synthesis())
    data["claims"][0][name] = "UP"
    fails("PROHIBITED_FIELD", NarrativeSynthesis.from_dict, data)


def test_g_no_vocabulary_forecasts_or_recommends() -> None:
    words = ("PREDICT", "FORECAST", "BUY", "SELL", "RECOMMEND", "TARGET", "EXPECTED_RETURN", "OUTPERFORM", "SIGNAL")
    for enum_type in (NarrativeKind, EpistemicClass, ClaimKind, Predicate, UncertaintyCode):
        for member in enum_type:
            assert not any(word in member.value for word in words), member


@pytest.mark.parametrize("ref_type", ["MONITORING_FINDING", "REVIEW_ITEM_STATE"])
def test_h_monitoring_findings_and_review_state_are_not_references(ref_type) -> None:
    fails("PROHIBITED_REF_TYPE", ref_from_dict, {"ref_type": ref_type})
    assert not any("monitor" in name.lower() or "finding" in name.lower() for name in dir(m))


@pytest.mark.parametrize("ref_type", ["LLM_PROPOSAL", "LLM_GENERATION", "LLM_OUTPUT", "THEME_PROPOSAL",
                                      "EVIDENCE_PROPOSAL", "RELATION_PROPOSAL", "PROPOSAL_DECISION", "DISCOVERY_HIT"])
def test_i_b7_and_unreviewed_proposal_refs_are_prohibited(ref_type) -> None:
    fails("PROHIBITED_REF_TYPE", ref_from_dict, {"ref_type": ref_type})


@pytest.mark.parametrize("position", ["UNREVIEWED", "REJECTED", "RETIRED", "MERGED", "SPLIT", "SUPERSEDED",
                                      "UNRESOLVED", "NOT_AVAILABLE"])
def test_i_only_reviewed_accepted_themes_can_ground_an_interpretation(position) -> None:
    fails("THEME_NOT_REVIEWED", obs, R1, position=position)


def test_i_an_unreviewed_context_lane_is_deferred_not_modelled() -> None:
    fails("REF_TYPE_DEFERRED", ref_from_dict, {"ref_type": "UNREVIEWED_CONTEXT"})


def test_i_every_referenced_theme_must_be_reviewed_in_the_synthesis() -> None:
    orphan_change = change(chg(R2))
    fails("UNREVIEWED_THEME_REFERENCE", synth, "THEME_STATE", [R1], [state(R1), orphan_change])


# ================================================================ J〜P 認識の guard

@pytest.mark.parametrize("ref", [lambda: obs(R1), lambda: att(R1), lambda: comp(R1), lambda: cond(R1)])
def test_j_an_observed_fact_cannot_cite_only_a_theme_interpretation(ref) -> None:
    fails("FACT_CITES_ONLY_INTERPRETATION", C, OF, "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", ref())


@pytest.mark.parametrize("ref_id,kind", [("doc_1", "SOURCE_DOCUMENT"), ("news_1", "NEWS_ITEM"), ("st_1", "STATEMENT")])
def test_j_source_content_is_never_an_observed_fact(ref_id, kind) -> None:
    fails("FACT_REQUIRES_OBSERVATIONAL_EVIDENCE", C, OF, "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", item(ref_id, kind))


def test_j_an_inferred_time_does_not_establish_an_observed_fact() -> None:
    fails("FACT_TIME_NOT_ESTABLISHED", C, OF, "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", item(quality="INFERRED"))
    fails("TIME_QUALITY_INCONSISTENT", item, quality="MISSING")


def test_j_an_observed_fact_mixed_with_interpretation_refs_is_rejected() -> None:
    fails("REF_SHAPE_INVALID", C, OF, "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", item(), obs(R1))


def test_j_an_observed_fact_must_be_attached_to_a_subject() -> None:
    fails("ORPHAN_OBSERVED_FACT", synth, "THEME_STATE", [R1], [state(R1), fact(item("fact_zz"))])
    fails("ORPHAN_OBSERVED_FACT", synth, "THEME_STATE", [R1], [state(R1), evidence(att(R1, "fact_a1")),
                                                               fact(item("fact_a2"))])


@pytest.mark.parametrize("predicate", [p for p in Predicate if p is not Predicate.EVIDENCE_ITEM_OBSERVED])
def test_k_l_nothing_but_an_observed_evidence_item_can_be_an_observed_fact(predicate) -> None:
    kinds = m.PREDICATE_SIGNATURES[predicate][1]
    fails("EPISTEMIC_CLASS_MISMATCH", C, OF, kinds[0].value, predicate.value, obs(R1))


def test_k_alternatives_are_never_observed_facts() -> None:
    fails("EPISTEMIC_CLASS_MISMATCH", C, OF, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE",
          obs(R1), att(R1), obs(R2), att(R2))
    fails("EPISTEMIC_CLASS_MISMATCH", C, AH, "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", item())


def test_l_uncertainty_is_never_an_observed_fact() -> None:
    fails("EPISTEMIC_CLASS_MISMATCH", C, OF, "EVIDENCE", "IS_UNCERTAIN", obs(R1), code="STALE_EVIDENCE")
    fails("EPISTEMIC_CLASS_MISMATCH", C, UN, "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", item(), code="STALE_EVIDENCE")


def test_m_a_relation_claim_needs_a_relation_ref() -> None:
    for predicate in ("HUMAN_ASSERTED_RELATION", "SOURCE_ASSERTED_RELATION"):
        fails("RELATION_REF_REQUIRED", C, RI, "RELATION", predicate, obs(R1), obs(R2))
    fails("CLAIM_KIND_MISMATCH", C, UN, "RELATION", "IS_UNCERTAIN", obs(R1), code="STALE_EVIDENCE")


def test_n_an_invalidation_claim_needs_an_invalidation_ref() -> None:
    fails("INVALIDATION_REF_REQUIRED", C, RI, "INVALIDATION", "RECORDS_INVALIDATION_CONDITION", obs(R1))
    fails("INVALIDATION_REF_REQUIRED", C, RI, "INVALIDATION", "INVALIDATING_EVIDENCE_ATTACHED",
          att(R1, "fact_a3", "INVALIDATES", condition="curve_reverts"))


EXPECTED_TRIPLES = {
    (RI, "STATE", "THEME_REVIEWED_STATE"), (RI, "MECHANISM", "RECORDS_MECHANISM_COMPONENT"),
    (RI, "EVIDENCE", "EVIDENCE_ATTACHED"), (OF, "EVIDENCE", "EVIDENCE_ITEM_OBSERVED"),
    (DS, "CHANGE", "CHANGED_BETWEEN_CUTOFFS"), (RI, "RELATION", "HUMAN_ASSERTED_RELATION"),
    (RI, "RELATION", "SOURCE_ASSERTED_RELATION"), (RI, "INVALIDATION", "RECORDS_INVALIDATION_CONDITION"),
    (RI, "INVALIDATION", "INVALIDATING_EVIDENCE_ATTACHED"),
    (AH, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE"), (UN, "EVIDENCE", "IS_UNCERTAIN"),
    (UN, "MECHANISM", "IS_UNCERTAIN")}


def test_o_the_allowed_class_kind_predicate_triples_are_frozen() -> None:
    assert {(k.value, c.value, p.value) for k, c, p in ALLOWED_TRIPLES} == EXPECTED_TRIPLES
    assert {e.value for e in EpistemicClass} == {RI, OF, DS, UN, AH}
    assert {e.value for e in ClaimKind} == {"STATE", "MECHANISM", "EVIDENCE", "CHANGE", "RELATION", "INVALIDATION"}
    assert not ({e.value for e in EpistemicClass} & {e.value for e in ClaimKind})   # kind と class は別の軸


@pytest.mark.parametrize("klass,kind,predicate", [t for t in itertools.product(
    [e.value for e in EpistemicClass], [e.value for e in ClaimKind], [e.value for e in Predicate])
    if t not in EXPECTED_TRIPLES])
def test_o_every_other_combination_fails_closed(klass, kind, predicate) -> None:
    with pytest.raises(NarrativeModelError) as info:
        C(klass, kind, predicate, obs(R1), code="STALE_EVIDENCE" if predicate == "IS_UNCERTAIN" else None)
    assert info.value.code in ("EPISTEMIC_CLASS_MISMATCH", "CLAIM_KIND_MISMATCH")


def test_p_uncertainty_codes_are_required_only_for_uncertainty_and_match_their_kind() -> None:
    fails("UNCERTAINTY_CODE_REQUIRED", C, UN, "EVIDENCE", "IS_UNCERTAIN", obs(R1))
    fails("UNCERTAINTY_CODE_NOT_ALLOWED", C, RI, "STATE", "THEME_REVIEWED_STATE", obs(R1), code="STALE_EVIDENCE")
    fails("CLAIM_KIND_MISMATCH", C, UN, "MECHANISM", "IS_UNCERTAIN", obs(R1), code="STALE_EVIDENCE")
    fails("CLAIM_KIND_MISMATCH", C, UN, "EVIDENCE", "IS_UNCERTAIN", obs(R2), code="MECHANISM_HYPOTHESIZED")


def test_p_uncertainty_cannot_contradict_its_own_refs() -> None:
    fails("UNCERTAINTY_CONTRADICTS_REFS", uncertain, "MECHANISM_HYPOTHESIZED", R1)       # R1 は仮説ではない
    no_support = [state(R1), evidence(att(R1)), uncertain("NO_SUPPORTING_EVIDENCE", R1)]
    fails("UNCERTAINTY_CONTRADICTS_REFS", synth, "THEME_STATE", [R1], no_support)


def test_p_a_hypothesized_mechanism_must_be_surfaced_as_uncertainty() -> None:
    claims = [state(R2), mechanism(R2)]
    fails("HYPOTHESIZED_MECHANISM_NOT_SURFACED", synth, "THEME_STATE", [R2], claims)
    assert synth("THEME_STATE", [R2], claims + [uncertain("MECHANISM_HYPOTHESIZED", R2)])


def test_p_certainty_is_carried_as_attribution_and_never_upgraded() -> None:
    fails("REF_INCONSISTENT", synth, "THEME_STATE", [R2],
          [state(R2), mechanism(R2), uncertain("MECHANISM_HYPOTHESIZED", R2),
           C(RI, "RELATION", "HUMAN_ASSERTED_RELATION", rel(R2, R1), obs(R2, certainty="EVIDENCE_SUPPORTED_MECHANISM"),
             obs(R1))])


# ================================================================ Q〜U evidence の role を保つ

@pytest.mark.parametrize("role", ["SUPPORTS", "CONTRADICTS", "CONTEXT", "INVALIDATES"])
def test_q_every_role_survives_serialization_unchanged(role) -> None:
    kw = {"condition": "curve_reverts"} if role == "INVALIDATES" else {}
    ref = att(R1, "fact_a9", role, provenance="LLM_PROPOSAL", **kw)
    assert ref_from_dict(json.loads(canonical_json(ref.to_dict()))) == ref
    assert ref.role.value == role and ref.role_provenance.value == "LLM_PROPOSAL"


def test_r_the_same_attachment_cannot_be_relabelled() -> None:
    claims = [state(R1), evidence(att(R1, "fact_a1", "SUPPORTS")), evidence(att(R1, "fact_a1", "CONTEXT"))]
    fails("EVIDENCE_ROLE_RELABELLED", synth, "THEME_STATE", [R1], claims)
    claims = [state(R1), evidence(att(R1, "fact_a1")), evidence(att(R1, "fact_a1", provenance="RULE"))]
    fails("REF_INCONSISTENT", synth, "THEME_STATE", [R1], claims)


def test_r_different_themes_may_hold_different_roles_for_the_same_item() -> None:
    claims = [state(R1), state(R2), evidence(att(R1, "fact_a1")), evidence(att(R2, "fact_a1", "CONTEXT"))]
    roles = {ref.role.value for c in synth("THEME_SET", [R1, R2], claims).claims for ref in c.refs
             if isinstance(ref, EvidenceAttachmentRef)}
    assert roles == {"SUPPORTS", "CONTEXT"}


def test_s_invalidates_is_bound_to_a_condition_and_is_never_executed() -> None:
    fails("INVALIDATION_CONDITION_REQUIRED", att, R1, "fact_a3", "INVALIDATES")
    fails("INVALIDATION_CONDITION_ONLY_FOR_INVALIDATES", att, R1, "fact_a3", "SUPPORTS", condition="curve_reverts")
    fails("INVALIDATION_EVIDENCE_MISMATCH", C, RI, "INVALIDATION", "INVALIDATING_EVIDENCE_ATTACHED", cond(R1),
          att(R1, "fact_a3", "INVALIDATES", condition="other_condition"))
    assert not any(word in p.value for p in Predicate for word in ("INVALIDATED", "FALSIFIED", "REFUTED"))


def test_s_invalidating_evidence_is_surfaced_and_its_condition_recorded() -> None:
    hidden = [state(R1), condition(R1), evidence(att(R1, "fact_a3", "INVALIDATES", condition="curve_reverts"))]
    fails("INVALIDATION_EVIDENCE_NOT_SURFACED", synth, "THEME_STATE", [R1], hidden)
    fails("INVALIDATION_CONDITION_NOT_RECORDED", synth, "THEME_STATE", [R1], [state(R1), invalidating(R1)])


def test_t_supporting_and_contradicting_evidence_require_a_contested_uncertainty() -> None:
    claims = [c for c in set_claims() if c.uncertainty_code is not UncertaintyCode.CONTESTED_EVIDENCE]
    fails("CONTESTED_EVIDENCE_NOT_SURFACED", set_synthesis, claims=claims)


def test_t_a_contested_uncertainty_needs_both_sides_of_the_same_theme() -> None:
    fails("REF_SHAPE_INVALID", uncertain, "CONTESTED_EVIDENCE", R2, att(R2, "obs_b1"))
    fails("UNCERTAINTY_CONTRADICTS_REFS", uncertain, "CONTESTED_EVIDENCE", R2, att(R2, "obs_b1"),
          att(R2, "news_b2", "CONTEXT"))
    fails("UNCERTAINTY_CONTRADICTS_REFS", uncertain, "CONTESTED_EVIDENCE", R2, att(R2, "obs_b1"),
          att(R1, "news_b2", "CONTRADICTS"))


def test_u_alternatives_are_explicit_unranked_and_keep_their_roles() -> None:
    fails("REF_SHAPE_INVALID", alternative, "fact_a1", R1)
    fails("ALTERNATIVES_REQUIRE_SHARED_EVIDENCE", C, AH, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE",
          obs(R1), att(R1, "fact_a1"), obs(R2), att(R2, "fact_a2"))
    fails("ALTERNATIVES_REQUIRE_SUPPORTS", C, AH, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE",
          obs(R1), att(R1, "fact_a1"), obs(R2), att(R2, "fact_a1", "CONTRADICTS"))
    fails("ALTERNATIVE_THEMES_MISMATCH", C, AH, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE",
          obs(R1), att(R1, "fact_a1"), obs(R3), att(R2, "fact_a1"))
    fails("ALTERNATIVE_DUPLICATE_THEME", C, AH, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE",
          obs(R1), att(R1, "fact_a1"), att(R1, "fact_a1", consequence="k1"), obs(R2))
    assert alternative("fact_a1", R1, R2).claim_id == alternative("fact_a1", R2, R1).claim_id   # 並べるだけ・勝者なし
    assert {f.name for f in dataclasses.fields(NarrativeClaim)} == {
        "epistemic_class", "claim_kind", "predicate", "refs", "uncertainty_code", "claim_id"}


def test_u_alternatives_must_touch_a_subject() -> None:
    fails("ALTERNATIVE_OUTSIDE_SUBJECTS", synth, "THEME_STATE", [R1], [state(R1), alternative("fact_a1", R2, R3)])


# ================================================================ V〜W SOURCE_ASSERTED と relation

def test_v_source_asserted_relations_stay_attributed_to_the_source() -> None:
    fails("ASSERTION_CLASS_MISMATCH", C, RI, "RELATION", "HUMAN_ASSERTED_RELATION",
          rel(R1, R2, klass="SOURCE_ASSERTED"), obs(R1), obs(R2))
    fails("ASSERTION_CLASS_MISMATCH", C, RI, "RELATION", "SOURCE_ASSERTED_RELATION", rel(R1, R2), obs(R1), obs(R2))
    fails("EPISTEMIC_CLASS_MISMATCH", C, OF, "RELATION", "SOURCE_ASSERTED_RELATION",
          rel(R1, R2, klass="SOURCE_ASSERTED"), obs(R1), obs(R2))
    assert m.PREDICATE_SIGNATURES[Predicate.SOURCE_ASSERTED_RELATION][0] is EpistemicClass.REVIEWED_INTERPRETATION
    assert m.SOURCE_ASSERTED_MEANING == "a source asserted this relation; the narrative does not assert it"


def test_w_a_relation_claim_is_one_direct_edge_with_both_reviewed_endpoints() -> None:
    fails("RELATION_ENDPOINTS_REQUIRED", C, RI, "RELATION", "HUMAN_ASSERTED_RELATION", rel(R1, R2), obs(R1), obs(R3))
    fails("REF_SHAPE_INVALID", C, RI, "RELATION", "HUMAN_ASSERTED_RELATION", rel(R1, R2), obs(R1))
    fails("REF_SHAPE_INVALID", C, RI, "RELATION", "HUMAN_ASSERTED_RELATION", rel(R1, R2), rel(R2, R3, REL2),
          obs(R1), obs(R2))                                                                        # 経路（推移辺）は作れない
    fails("SELF_RELATION", rel, R1, R1)
    fails("RELATION_OUTSIDE_SUBJECTS", synth, "THEME_STATE", [R1], [state(R1), relation(R2, R3)])


def test_w_shared_evidence_is_never_a_relation_and_carries_no_causality() -> None:
    kinds = {m.PREDICATE_SIGNATURES[p][1] for p in Predicate if p not in m.RELATION_PREDICATES}
    assert all(ClaimKind.RELATION not in k for k in kinds)
    assert not any(name in {e.name for e in Predicate} for name in ("CAUSES", "IMPLIES", "LEADS_TO", "DRIVES"))
    assert not any("central" in name.lower() or "degree" in name.lower() or "path" in name.lower() for name in dir(m)
                   if not name.startswith("_"))


# ================================================================ X〜AC identity と決定論

def test_x_the_synthesis_id_is_content_addressed() -> None:
    synthesis = state_synthesis()
    expected = content_id("narsyn", canonical_json({
        "schema_version": m.SCHEMA_VERSION, "kind": "THEME_STATE", "subject_root_ids": [R1],
        "cutoff": "2026-03-31T06:00:00+00:00",
        "knowledge_pins": [{"name": n, "version": v} for n, v in PINS], "input_digest": DIGEST,
        "claim_ids": sorted(c.claim_id for c in synthesis.claims)}))
    assert synthesis.synthesis_id == expected and len(expected) == len("narsyn_") + 24


def test_x_no_operational_metadata_exists_to_alter_identity() -> None:
    names = {f.name for f in dataclasses.fields(NarrativeSynthesis)}
    assert names == {"kind", "subject_root_ids", "cutoff", "knowledge_pins", "input_digest", "claims", "synthesis_id"}
    for name in ("generated_at", "created_at", "run_id", "recorded_at"):
        data = payload(state_synthesis())
        data[name] = "2026-01-01T00:00:00+00:00"
        fails("PROHIBITED_FIELD", NarrativeSynthesis.from_dict, data)


def test_y_nonsemantic_order_never_changes_identity() -> None:
    base = state_synthesis()
    shuffled = synth("THEME_STATE", [R1], list(reversed(state_claims())), pins=tuple(reversed(PINS)))
    assert shuffled.synthesis_id == base.synthesis_id and shuffled.to_canonical_json() == base.to_canonical_json()
    claim = relation(R1, R2)
    reordered = NarrativeClaim(epistemic_class=RI, claim_kind="RELATION", predicate="HUMAN_ASSERTED_RELATION",
                               refs=tuple(reversed(claim.refs)))
    assert reordered.claim_id == claim.claim_id and reordered.refs == claim.refs


@pytest.mark.parametrize("change", [
    {"cutoff": CUTOFF + timedelta(seconds=1)}, {"digest": "narin_" + "2" * 24},
    {"pins": (("narrative_semantics", "0.1.1"), ("theme_resolver", "0.1.0"))},
    {"claims": state_claims()[:-1]}])
def test_z_semantic_content_changes_identity(change) -> None:
    assert state_synthesis(**change).synthesis_id != state_synthesis().synthesis_id


def test_z_the_narrative_key_names_the_question_not_the_answer() -> None:
    assert state_synthesis().narrative_key == state_synthesis(cutoff=CUTOFF + timedelta(days=1)).narrative_key
    assert state_synthesis().narrative_key != set_synthesis().narrative_key
    assert state_synthesis().narrative_key.startswith("narkey_")


def test_aa_claim_identity_is_deterministic_and_content_sensitive() -> None:
    assert uncertain("STALE_EVIDENCE", R1).claim_id == uncertain("STALE_EVIDENCE", R1).claim_id
    assert uncertain("STALE_EVIDENCE", R1).claim_id != uncertain("SINGLE_SOURCE_EVIDENCE", R1).claim_id
    assert evidence(att(R1, "fact_a1")).claim_id != evidence(att(R1, "fact_a1", "CONTEXT")).claim_id
    claim = evidence(att(R1))
    assert claim.claim_id == content_id("narclm", canonical_json({
        "schema_version": m.CLAIM_SCHEMA_VERSION, "epistemic_class": RI, "claim_kind": "EVIDENCE",
        "predicate": "EVIDENCE_ATTACHED", "uncertainty_code": None, "refs": [att(R1).to_dict()]}))


def test_ab_identity_is_reproduced_in_fresh_processes_without_clock_or_randomness() -> None:
    code = ("from tests.intelligence.test_narrative_synthesis_model import state_synthesis, set_synthesis\n"
            "print(state_synthesis().to_canonical_json()); print(set_synthesis().to_canonical_json())\n")
    outputs = set()
    for seed in ("1", "2"):
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                              env={"PYTHONPATH": str(REPO_ROOT), "PYTHONHASHSEED": seed, "PATH": os.environ.get(
                                  "PATH", "")})
        outputs.add(proc.stdout)
    assert outputs == {state_synthesis().to_canonical_json() + "\n" + set_synthesis().to_canonical_json() + "\n"}


@pytest.mark.parametrize("builder,kwargs", [
    (obs, {"position": "accepted"}), (obs, {"certainty": "hypothesized_mechanism"}),
    (att, {"role": "supports"}), (att, {"role": "SUPPORTS "}), (comp, {"key": "Rate_Path"}),
    (comp, {"key": " rate_path"}), (cond, {"key": "curve reverts"})])
def test_ac_no_fuzzy_matching_or_normalization_of_tokens(builder, kwargs) -> None:
    with pytest.raises(NarrativeModelError):
        builder(R1, **kwargs)


@pytest.mark.parametrize("root", [R1.lower(), R1 + " ", "theme_" + "I" * 26, "Theme_" + R1[6:], R1[:-1]])
def test_ac_root_ids_are_matched_exactly(root) -> None:
    fails("INVALID_ROOT_ID", ThemeObservationRef, root_id=root, observation_id=OBS[R1], governance_position="ACCEPTED",
          mechanism_certainty="OBSERVED_ASSOCIATION")


# ================================================================ AD〜AJ 厳格な検査

@pytest.mark.parametrize("kind", ["MARKET_STATE", "EVIDENCE_LINKED", "SCENARIO_NARRATIVE", "RISK_NARRATIVE",
                                  "theme_state", ""])
def test_ad_unknown_narrative_kinds_fail_closed(kind) -> None:
    fails("UNKNOWN_NARRATIVE_KIND", synth, kind, [R1], [state(R1)])


def test_ae_unknown_and_not_adopted_epistemic_classes_fail_closed() -> None:
    fails("EPISTEMIC_CLASS_NOT_ADOPTED", C, "SCENARIO_CONDITION", "INVALIDATION", "RECORDS_INVALIDATION_CONDITION",
          cond(R1))
    for klass in ("OBSERVED", "HYPOTHESIS", "UNREVIEWED_CONTEXT", "FACT", ""):
        fails("UNKNOWN_EPISTEMIC_CLASS", C, klass, "STATE", "THEME_REVIEWED_STATE", obs(R1))


@pytest.mark.parametrize("field,value,code", [
    ("claim_kind", "WHY", "UNKNOWN_CLAIM_KIND"), ("claim_kind", "UNCERTAINTY", "UNKNOWN_CLAIM_KIND"),
    ("predicate", "CAUSES", "UNKNOWN_PREDICATE"), ("predicate", "IS_LIKELY", "UNKNOWN_PREDICATE"),
    ("uncertainty_code", "PROBABLY", "UNKNOWN_UNCERTAINTY_CODE")])
def test_af_unknown_vocabulary_fails_closed(field, value, code) -> None:
    kw = dict(epistemic_class=UN, claim_kind="EVIDENCE", predicate="IS_UNCERTAIN", refs=(obs(R1),),
              uncertainty_code="STALE_EVIDENCE")
    kw[field] = value
    fails(code, NarrativeClaim, **kw)


@pytest.mark.parametrize("builder,kwargs,code", [
    (att, {"role": "TRIGGER"}, "UNKNOWN_EVIDENCE_ROLE"), (att, {"kind": "CONTEXT_ITEM"}, "UNKNOWN_EVIDENCE_KIND"),
    (att, {"provenance": "SYSTEM"}, "UNKNOWN_ROLE_PROVENANCE"), (comp, {"ctype": "CATALYST"}, "UNKNOWN_COMPONENT_TYPE"),
    (chg, {"kind": "PRICE_MOVED"}, "UNKNOWN_CHANGE_KIND"), (chg, {"facet": "price"}, "UNKNOWN_CHANGE_FACET"),
    (obs, {"certainty": "PROVEN"}, "UNKNOWN_MECHANISM_CERTAINTY")])
def test_af_unknown_ref_vocabulary_fails_closed(builder, kwargs, code) -> None:
    fails(code, builder, R1, **kwargs)


def test_af_unknown_relation_vocabulary_and_ref_types_fail_closed() -> None:
    fails("UNKNOWN_RELATION_TYPE", rel, R1, R2, rtype="CORRELATES")
    fails("UNKNOWN_ASSERTION_CLASS", rel, R1, R2, klass="LLM_ASSERTED")
    fails("UNKNOWN_REF_TYPE", ref_from_dict, {"ref_type": "THEME_ROOT"})
    fails("REF_TYPE_MISMATCH", ThemeObservationRef.from_dict, dict(obs(R1).to_dict(), ref_type="MECHANISM_COMPONENT"))
    for ref_type in ("DNA_RULE", "P4_FACT", "P4_CONTEXT", "P4_INTERNALS", "THEME_LIMITATION", "THEME_LINEAGE"):
        fails("REF_TYPE_DEFERRED", ref_from_dict, {"ref_type": ref_type})


def test_ag_naive_or_untyped_datetimes_fail_closed() -> None:
    naive = datetime(2026, 1, 1)
    fails("NAIVE_DATETIME", synth, "THEME_STATE", [R1], [state(R1)], cutoff=naive)
    fails("NAIVE_DATETIME", att, R1, at=naive)
    fails("NAIVE_DATETIME", item, at=naive)
    fails("NAIVE_DATETIME", chg, R1, start=naive)
    fails("INVALID_TYPE", synth, "THEME_STATE", [R1], [state(R1)], cutoff="2026-03-31T06:00:00+00:00")


def test_ah_nothing_after_the_cutoff_is_visible() -> None:
    later = CUTOFF + timedelta(microseconds=1)
    fails("REF_AFTER_CUTOFF", synth, "THEME_STATE", [R1], [state(R1), evidence(att(R1, at=later))])
    fails("REF_AFTER_CUTOFF", synth, "THEME_STATE", [R1], [state(R1), evidence(att(R1)), fact(item(at=later))])
    fails("REF_AFTER_CUTOFF", synth, "THEME_STATE", [R1], [state(R1), change(chg(R1, end=later))])
    fails("CHANGE_WINDOW_INVALID", chg, R1, start=CUTOFF, end=CUTOFF)
    assert synth("THEME_STATE", [R1], [state(R1), evidence(att(R1, at=CUTOFF))])      # cutoff ちょうどは見える


def test_ah_one_observation_per_theme_at_the_cutoff() -> None:
    other = "thobs_" + "f" * 24
    fails("OBSERVATION_INCONSISTENT", synth, "THEME_STATE", [R1],
          [state(R1), evidence(att(R1, observation_id=other))])


def test_ai_duplicates_are_rejected_not_silently_removed() -> None:
    fails("DUPLICATE_REF", C, AH, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE", obs(R1), obs(R1),
          att(R1), att(R2))
    fails("DUPLICATE_CLAIM", synth, "THEME_STATE", [R1], [state(R1), state(R1)])
    fails("DUPLICATE_KNOWLEDGE_PIN", state_synthesis, pins=(("theme_resolver", "0.1.0"), ("theme_resolver", "0.2.0")))


def test_aj_structural_bounds_are_enforced_without_truncation() -> None:
    fails("CLAIM_COUNT_OUT_OF_BOUNDS", synth, "THEME_STATE", [R1], [])
    fails("KNOWLEDGE_PINS_OUT_OF_BOUNDS", state_synthesis, pins=())
    pins = tuple((f"pin_{n:02d}", "0.1.0") for n in range(MAX_KNOWLEDGE_PINS + 1))
    fails("KNOWLEDGE_PINS_OUT_OF_BOUNDS", state_synthesis, pins=pins)
    fails("REF_COUNT_OUT_OF_BOUNDS", C, RI, "STATE", "THEME_REVIEWED_STATE")
    roots = [f"theme_01K{'0' * 21}{n:02d}" for n in range(MAX_REFS_PER_CLAIM)]
    refs = [r for root in roots for r in (
        ThemeObservationRef(root_id=root, observation_id="thobs_" + "a" * 24, governance_position="ACCEPTED",
                            mechanism_certainty="OBSERVED_ASSOCIATION"),)]
    fails("REF_COUNT_OUT_OF_BOUNDS", C, AH, "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE", *refs, att(R1))
    claims = [state(R1)] + [mechanism(R1, key=f"k{n:03d}") for n in range(MAX_CLAIMS)]
    fails("CLAIM_COUNT_OUT_OF_BOUNDS", synth, "THEME_STATE", [R1], claims)


def test_aj_invalid_pins_and_digests_fail_closed() -> None:
    for pins in ((("Theme", "0.1.0"),), (("theme", "v1"),), (("theme",),), ("theme",)):
        fails("INVALID_KNOWLEDGE_PIN", state_synthesis, pins=pins)
    for digest in ("", "narin_" + "g" * 24, "NARIN_" + "1" * 24, "narin_" + "1" * 23, "sha256:" + "1" * 24):
        fails("INVALID_INPUT_DIGEST", state_synthesis, digest=digest)


def test_aj_claims_and_refs_must_be_model_instances() -> None:
    fails("INVALID_CLAIM", synth, "THEME_STATE", [R1], [state(R1).to_dict()])
    fails("INVALID_REF", C, RI, "STATE", "THEME_REVIEWED_STATE", obs(R1).to_dict())
    fails("INVALID_REF", C, RI, "STATE", "THEME_REVIEWED_STATE", "src/intelligence/themes/model.py")


def test_aj_claims_about_non_subjects_are_rejected() -> None:
    fails("CLAIM_OUTSIDE_SUBJECTS", synth, "THEME_STATE", [R1], [state(R1), state(R2)])
    fails("CLAIM_OUTSIDE_SUBJECTS", synth, "THEME_STATE", [R1], [state(R1), relation(R1, R2), mechanism(R2)])


# ================================================================ AK〜AO 直列化・text policy・機密

@pytest.mark.parametrize("builder", [state_synthesis, set_synthesis])
def test_ak_canonical_serialization_round_trips_byte_identically(builder) -> None:
    synthesis = builder()
    text = synthesis.to_canonical_json()
    again = NarrativeSynthesis.from_json(text)
    assert again == synthesis and again.to_canonical_json() == text
    assert NarrativeSynthesis.from_dict(json.loads(text)) == synthesis
    assert text == canonical_json(json.loads(text))


def test_ak_every_ref_type_round_trips() -> None:
    refs = [obs(R1), comp(R1), cond(R1), att(R1), item(), chg(R1), rel(R1, R2)]
    assert {type(r).REF_TYPE for r in refs} == set(m.REF_TYPES)
    for ref in refs:
        assert ref_from_dict(json.loads(canonical_json(ref.to_dict()))) == ref


def test_al_from_dict_is_strict_about_shape_and_types() -> None:
    base = payload(state_synthesis())
    fails("UNKNOWN_FIELD", NarrativeSynthesis.from_dict, dict(base, extra="x"))
    fails("MISSING_FIELD", NarrativeSynthesis.from_dict, {k: v for k, v in base.items() if k != "input_digest"})
    fails("UNSUPPORTED_SCHEMA_VERSION", NarrativeSynthesis.from_dict, dict(base, schema_version="narrative_synthesis:9"))
    fails("INVALID_TYPE", NarrativeSynthesis.from_dict, dict(base, input_digest=1))
    fails("INVALID_TYPE", NarrativeSynthesis.from_dict, dict(base, kind=True))
    fails("INVALID_TYPE", NarrativeSynthesis.from_dict, dict(base, claims={}))
    fails("INVALID_TYPE", NarrativeSynthesis.from_dict, [base])
    claim = dict(base["claims"][0], uncertainty_code=0)
    fails("INVALID_TYPE", NarrativeSynthesis.from_dict, dict(base, claims=[claim] + base["claims"][1:]))


def test_al_non_canonical_serializations_are_rejected() -> None:
    base = payload(state_synthesis())
    fails("NON_CANONICAL_DATETIME", NarrativeSynthesis.from_dict, dict(base, cutoff="2026-03-31T15:00:00+09:00"))
    fails("INVALID_DATETIME", NarrativeSynthesis.from_dict, dict(base, cutoff="yesterday"))
    fails("NON_CANONICAL_SERIALIZATION", NarrativeSynthesis.from_dict, dict(base, claims=list(reversed(base["claims"]))))
    text = state_synthesis().to_canonical_json()
    fails("NON_CANONICAL_SERIALIZATION", NarrativeSynthesis.from_json, json.dumps(json.loads(text), indent=1))
    fails("DUPLICATE_JSON_KEY", NarrativeSynthesis.from_json, '{"kind":"THEME_STATE","kind":"THEME_SET"}')
    fails("INVALID_JSON", NarrativeSynthesis.from_json, "{not json")
    fails("INVALID_TYPE", NarrativeSynthesis.from_json, b"{}")


def test_am_tampered_identities_are_detected() -> None:
    base = payload(state_synthesis())
    fails("SYNTHESIS_ID_MISMATCH", NarrativeSynthesis.from_dict, dict(base, synthesis_id="narsyn_" + "0" * 24))
    claims = [dict(base["claims"][0], claim_id="narclm_" + "0" * 24)] + base["claims"][1:]
    fails("CLAIM_ID_MISMATCH", NarrativeSynthesis.from_dict, dict(base, claims=claims))
    flipped = json.loads(json.dumps(base).replace('"STALE_EVIDENCE"', '"SINGLE_SOURCE_EVIDENCE"'))
    fails("CLAIM_ID_MISMATCH", NarrativeSynthesis.from_dict, flipped)


HOSTILE = ["**bold**", "<b>x</b>", "https://example.invalid/x", "C:\\Users\\x", "/home/user/x", "a b", "a\nb",
           "../x", "x?api_key=1", "`x`", "[x](y)", "", " x"]


@pytest.mark.parametrize("value", HOSTILE)
def test_an_every_string_field_is_a_bounded_token_not_text(value) -> None:
    attempts = [lambda: comp(R1, key=value), lambda: cond(R1, key=value), lambda: chg(R1, subject=value),
                lambda: chg(R1, facet=value), lambda: state_synthesis(pins=((value, "0.1.0"),)),
                lambda: state_synthesis(pins=(("theme", value),)), lambda: state_synthesis(digest=value)]
    if value:                                                                 # 空の consequence は「無し」の意味で許される
        attempts += [lambda: att(R1, ref_id="fact_" + value), lambda: att(R1, consequence=value)]
    for attempt in attempts:
        with pytest.raises(NarrativeModelError):
            attempt()


def test_an_no_model_type_has_a_free_text_field() -> None:
    text_like = ("text", "prose", "summary", "statement", "note", "excerpt", "locator", "title", "description",
                 "rationale", "headline", "body", "comment", "reason")
    for model_type in MODEL_TYPES:
        for f in dataclasses.fields(model_type):
            assert not any(word in f.name for word in text_like), (model_type.__name__, f.name)


@pytest.mark.parametrize("name", ["excerpt", "note", "locator", "raw", "raw_payload", "url", "path", "api_key",
                                  "token", "secret", "text", "display_text", "summary"])
def test_ao_confidential_and_raw_fields_are_rejected(name) -> None:
    data = payload(state_synthesis())
    data["claims"][0]["refs"][0][name] = "canary-value-7731"
    error = fails("PROHIBITED_FIELD", NarrativeSynthesis.from_dict, data)
    assert "canary-value-7731" not in str(error)


def test_ao_errors_never_echo_rejected_values() -> None:
    canary = "canary-value-7731"
    for attempt in (lambda: comp(R1, key=canary + " x"), lambda: att(R1, ref_id="fact_" + canary + "/x"),
                    lambda: state_synthesis(digest=canary), lambda: obs(R1, position=canary),
                    lambda: ref_from_dict({"ref_type": canary})):
        with pytest.raises(NarrativeModelError) as info:
            attempt()
        assert canary not in str(info.value) and canary not in info.value.detail


def test_ao_the_authority_statement_is_part_of_the_model() -> None:
    for phrase in ("derived", "non-authoritative", "non-persistent", "prediction", "recommendation", "trading signal"):
        assert phrase in m.SYNTHESIS_IS_NOT_AUTHORITY
