"""P6-A4a — evidence attachment・二重時点・authority / role・source / temporal diversity・資格判定・entity link。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import IntEnum

import pytest

from src.intelligence.themes import model as M
from src.intelligence.themes import qualification as Q
from src.intelligence.themes.model import (
    AssertionProvenance, ComponentType, EntityLinkClass, EntityRef, EvidenceAuthorityClass, EvidenceKind,
    EvidenceRole, EvidenceTimeBasis, EvidenceTimeQuality, MechanismCertainty, OriginKind, ProvenanceClass,
    SourceOrigin, ThemeEntityKind, ThemeModelError,
)
from tests.intelligence.test_theme_model import (
    DOC_C, FACT_A, FACT_B, NEWS_D, OBS_X, T0, UTC, attachment, component, condition, consequence, inferred_link,
    mechanism, observation, origin, raises, scope,
)

MOF = SourceOrigin(origin_kind=OriginKind.OFFICIAL_RELEASE, origin_key="release:mof_japan/doc_" + "c" * 24,
                   source_ids=("mof_japan",), publisher="mof_japan")
BOJ = SourceOrigin(origin_kind=OriginKind.OFFICIAL_RELEASE, origin_key="release:boj/doc_" + "e" * 24,
                   source_ids=("boj",), publisher="boj")
ARTICLE = SourceOrigin(origin_kind=OriginKind.PUBLISHER_ARTICLE, origin_key="article:art_" + "f" * 24,
                       source_ids=("feed_a",), publisher="wire_x")
UNKNOWN = SourceOrigin(origin_kind=OriginKind.UNKNOWN)


def doc(ref=DOC_C, src=MOF, day="2026-08-25", **kw):
    return attachment(ref, EvidenceKind.SOURCE_DOCUMENT, src=src, day=day, **kw)


# ---------------------------------------------------------------- attachment 構造

def test_attachment_round_trip_and_key() -> None:
    a = attachment()
    assert M.EvidenceAttachment.from_dict(a.as_dict() if hasattr(a, "as_dict") else M._as_json(a)) == a
    assert a.attachment_key == f"{FACT_A}#c1" and a.is_evidentiary
    assert set(M._as_json(a)) >= {"evidence_kind", "authority_class", "ref_id", "source_origin", "evidence_time",
                                  "evidence_time_basis", "evidence_time_quality", "attached_at", "role",
                                  "role_provenance", "consequence_ref", "invalidation_condition_ref", "is_trigger",
                                  "source_causal_claim", "limited_use", "qa_decision_at_attachment", "locator",
                                  "excerpt", "note"}


def test_evidence_time_after_attached_at_is_rejected() -> None:
    with raises("EVIDENCE_AFTER_ATTACHMENT"):
        attachment(evidence_time=T0 + timedelta(seconds=1), attached=T0)
    ok = attachment(evidence_time=T0 - timedelta(days=10), attached=T0, day="2026-08-22")
    assert ok.evidence_time < ok.attached_at


def test_evidence_time_and_attached_at_are_independent_fields() -> None:
    a = attachment(day="2026-08-01", attached=T0)
    data = M._as_json(a)
    assert data["evidence_time"] == "2026-08-01T00:00:00+00:00" and data["attached_at"] == "2026-09-01T00:00:00+00:00"
    # 代替になりうる時刻の語彙は存在しない
    assert not {"RETRIEVED_AT", "INGESTED_AT", "CREATED_AT", "RECORDED_AT"} & {b.value for b in EvidenceTimeBasis}


def test_missing_evidence_time_only_as_context() -> None:
    with raises("MISSING_EVIDENCE_TIME"):
        attachment(quality=EvidenceTimeQuality.MISSING, role=EvidenceRole.SUPPORTS)
    with raises("MISSING_EVIDENCE_TIME"):
        attachment(quality=EvidenceTimeQuality.MISSING, role=EvidenceRole.CONTRADICTS)
    ctx = attachment(quality=EvidenceTimeQuality.MISSING, role=EvidenceRole.CONTEXT, cref="")
    assert ctx.evidence_time is None and ctx.evidence_date == "" and ctx.evidence_time_basis is EvidenceTimeBasis.NONE
    with raises("INVALID_EVIDENCE_TIME"):
        M.EvidenceAttachment(**{**M._as_json(ctx), "evidence_time": None, "evidence_time_basis": EvidenceTimeBasis.KNOWN_AT,
                                "evidence_kind": EvidenceKind.FACT, "authority_class": ctx.authority_class,
                                "source_origin": ctx.source_origin, "evidence_time_quality": ctx.evidence_time_quality,
                                "attached_at": ctx.attached_at, "role": ctx.role, "role_provenance": ctx.role_provenance,
                                "subject_refs": ()})
    with raises("MISSING_EVIDENCE_TIME"):
        attachment(evidence_time=None, quality=EvidenceTimeQuality.RELIABLE) if False else \
            M.EvidenceAttachment(evidence_kind=EvidenceKind.FACT, authority_class=EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL,
                                 ref_id=FACT_A, source_origin=origin(), evidence_time=None,
                                 evidence_time_basis=EvidenceTimeBasis.KNOWN_AT,
                                 evidence_time_quality=EvidenceTimeQuality.RELIABLE, evidence_date="2026-08-20",
                                 attached_at=T0, role=EvidenceRole.SUPPORTS, role_provenance=ProvenanceClass.RULE,
                                 role_asserted_by="rule:R1@1", consequence_ref="c1")


def test_evidence_time_basis_and_quality_follow_kind() -> None:
    with raises("INVALID_EVIDENCE_TIME"):
        attachment(basis=EvidenceTimeBasis.AS_OF)                                  # Fact は KNOWN_AT
    with raises("INVALID_EVIDENCE_TIME"):
        attachment(OBS_X, EvidenceKind.OBSERVATION, quality=EvidenceTimeQuality.DECLARED)  # Observation は RELIABLE のみ
    with raises("INVALID_EVIDENCE_TIME"):
        doc(quality=EvidenceTimeQuality.INFERRED)                                  # INFERRED は limited_use 必須
    inferred = doc(quality=EvidenceTimeQuality.INFERRED, limited_use=True)
    assert inferred.limited_use
    declared = attachment(quality=EvidenceTimeQuality.DECLARED)
    assert declared.evidence_time_quality is EvidenceTimeQuality.DECLARED
    with raises("INVALID_DATE"):
        attachment(day="2026-8-20") if False else \
            M.EvidenceAttachment(**{**M._as_json(declared), "evidence_date": "2026/08/20",
                                    "evidence_kind": EvidenceKind.FACT, "authority_class": declared.authority_class,
                                    "source_origin": declared.source_origin, "evidence_time": declared.evidence_time,
                                    "evidence_time_basis": declared.evidence_time_basis,
                                    "evidence_time_quality": declared.evidence_time_quality,
                                    "attached_at": declared.attached_at, "role": declared.role,
                                    "role_provenance": declared.role_provenance, "subject_refs": ()})


def test_only_primary_observational_can_be_attached() -> None:
    for klass in (EvidenceAuthorityClass.DERIVED_INTERPRETIVE, EvidenceAuthorityClass.PROPOSAL_ONLY,
                  EvidenceAuthorityClass.NOT_THEME_EVIDENCE):
        with raises("PROHIBITED_EVIDENCE_CLASS"):
            attachment(authority_class=klass)


def test_context_item_kind_is_prohibited_and_ref_prefix_enforced() -> None:
    data = M._as_json(attachment())
    data["evidence_kind"] = "CONTEXT_ITEM"
    with raises("PROHIBITED_EVIDENCE_KIND"):
        M.EvidenceAttachment.from_dict(data)
    with raises("REF_ID_KIND_MISMATCH"):
        attachment(DOC_C, EvidenceKind.FACT)
    with raises("REF_ID_KIND_MISMATCH"):
        attachment(FACT_A, EvidenceKind.NEWS_ITEM)
    assert attachment("stmt_1", EvidenceKind.STATEMENT, basis=EvidenceTimeBasis.EVENT_TIME).evidence_kind is EvidenceKind.STATEMENT


def test_invalidates_requires_condition_reference_and_dangling_refs_fail() -> None:
    with raises("MISSING_INVALIDATION_REF"):
        attachment(role=EvidenceRole.INVALIDATES)
    with raises("INVALID_ROLE_COMBINATION"):
        attachment(role=EvidenceRole.SUPPORTS, invalidation_condition_ref="inv1")
    inv = attachment(role=EvidenceRole.INVALIDATES, invalidation_condition_ref="inv1", cref="")
    assert observation(attachments=(inv,)).attachments[0].role is EvidenceRole.INVALIDATES
    with raises("DANGLING_INVALIDATION_REF"):
        observation(attachments=(attachment(role=EvidenceRole.INVALIDATES, invalidation_condition_ref="nope", cref=""),))
    with raises("DANGLING_CONSEQUENCE_REF"):
        observation(attachments=(attachment(cref="c9"),))


def test_trigger_is_a_flag_not_a_role_and_one_role_per_attachment() -> None:
    trig = attachment(is_trigger=True)
    assert trig.role is EvidenceRole.SUPPORTS and trig.is_trigger
    assert len({f.name for f in M.fields(M.EvidenceAttachment) if f.name == "role"}) == 1
    with raises("DUPLICATE_ATTACHMENT"):
        observation(attachments=(attachment(FACT_A), attachment(FACT_A, role=EvidenceRole.CONTRADICTS)))
    two = observation(attachments=(attachment(FACT_A, cref="c1"),
                                   attachment(FACT_A, cref="c2", role=EvidenceRole.CONTRADICTS)),
                      mechanism=mechanism(consequences=(consequence("c1"), consequence("c2", target="y"))))
    assert len(two.attachments) == 2


def test_human_role_requires_note_and_llm_role_is_provisional() -> None:
    with raises("MISSING_REASON"):
        attachment(provenance=ProvenanceClass.HUMAN, asserted_by="reviewer:r1")
    human = attachment(provenance=ProvenanceClass.HUMAN, asserted_by="reviewer:r1", note="matches consequence c1")
    llm = attachment(FACT_B, provenance=ProvenanceClass.LLM_PROPOSAL, asserted_by="model:x@prompt:v3", day="2026-08-21")
    assert Q.counted_attachments((human, llm)) == (human,)


def test_source_causal_claim_requires_textual_kind_and_class_requires_flag() -> None:
    with raises("INVALID_ROLE_COMBINATION"):
        attachment(source_causal_claim=True)  # Fact は因果主張の担い手ではない
    claim = doc(source_causal_claim=True)
    with raises("MISSING_SOURCE_CAUSAL_CLAIM"):
        observation(certainty_class=MechanismCertainty.EXPLICIT_SOURCE_CAUSAL_CLAIM)
    obs = observation(certainty_class=MechanismCertainty.EXPLICIT_SOURCE_CAUSAL_CLAIM, attachments=(claim,))
    assert obs.certainty_class is MechanismCertainty.EXPLICIT_SOURCE_CAUSAL_CLAIM
    # SOURCE_CLAIM component は付与済み evidence を指さなければならない
    with raises("DANGLING_SOURCE_CLAIM"):
        observation(mechanism=mechanism(channels=(component(ComponentType.TRANSMISSION_CHANNEL, "ch1", "INPUT_COST", "",
                                                            provenance=AssertionProvenance.SOURCE_CLAIM,
                                                            provenance_ref="doc_" + "0" * 24),)))
    cited = observation(attachments=(claim,), mechanism=mechanism(channels=(component(
        ComponentType.TRANSMISSION_CHANNEL, "ch1", "INPUT_COST", "", provenance=AssertionProvenance.SOURCE_CLAIM,
        provenance_ref=DOC_C),)))
    assert cited.mechanism.channels[0].provenance_ref == DOC_C


def test_evidence_supported_class_requires_supporting_attachment_bound_to_consequence() -> None:
    with raises("UNSUPPORTED_CERTAINTY_CLASS"):
        observation(certainty_class=MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM, attachments=())
    with raises("UNSUPPORTED_CERTAINTY_CLASS"):
        observation(certainty_class=MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM,
                    attachments=(attachment(cref="", role=EvidenceRole.CONTEXT),))
    with raises("UNSUPPORTED_CERTAINTY_CLASS"):
        observation(certainty_class=MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM,
                    attachments=(attachment(provenance=ProvenanceClass.LLM_PROPOSAL, asserted_by="model:x"),))
    ok = observation(certainty_class=MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM)
    assert ok.certainty_class is MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM


def test_certainty_classes_carry_no_rank_or_arithmetic() -> None:
    assert not issubclass(MechanismCertainty, (IntEnum, int))
    assert all(isinstance(c.value, str) for c in MechanismCertainty)
    numeric_maps = [n for n in dir(M) if "CERTAINTY" in n.upper() and isinstance(getattr(M, n), dict)]
    assert numeric_maps == []
    assert not any(n for n in dir(M) + dir(Q) if "rank" in n.lower() or "score" in n.lower() or "average" in n.lower())


def test_attached_at_after_recorded_at_rejected() -> None:
    with raises("ATTACHED_AT_OUT_OF_RANGE"):
        observation(attachments=(attachment(attached=T0 + timedelta(days=2)),), recorded_at=T0 + timedelta(hours=1))


# ---------------------------------------------------------------- source diversity（保守的）

def test_syndicated_copies_count_as_one_origin() -> None:
    copies = tuple(attachment(f"news_{i:0>24}", EvidenceKind.NEWS_ITEM, src=ARTICLE, day="2026-08-25")
                   for i in range(5))
    assert Q.independent_origin_count(copies) == 1 and len(Q.source_origin_groups(copies)[0]) == 5
    assert not Q.has_source_diversity(copies)


def test_release_document_news_item_and_statement_share_origin() -> None:
    doc_a = doc()
    news = attachment(NEWS_D, EvidenceKind.NEWS_ITEM, day="2026-08-25",
                      src=SourceOrigin(origin_kind=OriginKind.PUBLISHER_ARTICLE, origin_key="article:art_1",
                                       source_ids=("feed_a",), lineage_refs=(DOC_C,)))
    stmt = attachment("stmt_9", EvidenceKind.STATEMENT, basis=EvidenceTimeBasis.PUBLISHED_AT, day="2026-08-25",
                      src=SourceOrigin(origin_kind=OriginKind.OFFICIAL_RELEASE, origin_key="release:other",
                                       source_ids=("mof_japan",), lineage_refs=(DOC_C,)))
    assert Q.independent_origin_count((doc_a, news, stmt)) == 1


def test_observation_and_its_fact_share_origin_and_derived_fact_is_not_independent_from_inputs() -> None:
    obs_att = attachment(OBS_X, EvidenceKind.OBSERVATION, day="2026-08-20")
    fact = attachment(FACT_A, src=origin(lineage=(OBS_X,)), day="2026-08-20")
    assert Q.independent_origin_count((obs_att, fact)) == 1
    derived = attachment(FACT_B, src=SourceOrigin(origin_kind=OriginKind.DERIVED, origin_key="derived:" + FACT_B,
                                                   lineage_refs=(FACT_A, "fact_" + "z" * 24)), day="2026-08-20")
    assert Q.independent_origin_count((fact, derived)) == 1
    with raises("INVALID_ORIGIN"):
        SourceOrigin(origin_kind=OriginKind.DERIVED, origin_key="derived:x")   # 入力 lineage の無い derived は不可


def test_same_record_multiple_facts_share_origin() -> None:
    close = attachment(FACT_A, src=origin(key="record:jquants/2026-08-20/7203"), day="2026-08-20")
    volume = attachment(FACT_B, src=origin(key="record:jquants/2026-08-20/7203"), day="2026-08-20")
    assert Q.independent_origin_count((close, volume)) == 1


def test_unknown_origin_is_never_independent() -> None:
    a = attachment(FACT_A, src=UNKNOWN)
    b = attachment(FACT_B, src=UNKNOWN, day="2026-08-21")
    assert Q.independent_origin_count((a, b)) == 0 and Q.source_origin_groups((a, b)) == ()
    known = doc()
    assert Q.independent_origin_count((a, known)) == 1
    with raises("INVALID_ORIGIN"):
        SourceOrigin(origin_kind=OriginKind.UNKNOWN, origin_key="something")
    with raises("INVALID_ORIGIN"):
        SourceOrigin(origin_kind=OriginKind.OFFICIAL_RELEASE)


def test_two_independent_official_releases_and_release_plus_market_observation() -> None:
    assert Q.independent_origin_count((doc(), doc("doc_" + "e" * 24, BOJ, day="2026-08-26"))) == 2
    assert Q.independent_origin_count((doc(), attachment(OBS_X, EvidenceKind.OBSERVATION))) == 2
    assert Q.source_origin_set((doc(), attachment(OBS_X, EvidenceKind.OBSERVATION))) == (f"{DOC_C}#c1", f"{OBS_X}#c1")


def test_diversity_helpers_are_predicates_not_scores() -> None:
    atts = (doc(), attachment(OBS_X, EvidenceKind.OBSERVATION))
    assert Q.has_source_diversity(atts) is True and isinstance(Q.independent_origin_count(atts), int)
    assert Q.has_temporal_diversity(atts) is True and Q.evidence_date_set(atts) == ("2026-08-20", "2026-08-25")


# ---------------------------------------------------------------- temporal diversity

def test_same_series_two_dates_is_temporal_not_source_diversity() -> None:
    atts = (attachment(FACT_A, day="2026-08-20"), attachment(FACT_B, day="2026-08-21"))
    assert Q.has_temporal_diversity(atts) and not Q.has_source_diversity(atts)
    result = Q.evaluate_qualification(observation(attachments=atts))
    assert result.status is Q.QualificationStatus.THEME_CANDIDATE_POSSIBLE
    assert "SINGLE_SOURCE_ORIGIN" in result.diagnostics and result.independent_origins == 1


def test_same_day_multiple_times_is_one_evidence_date() -> None:
    a = attachment(FACT_A, evidence_time=datetime(2026, 8, 20, 1, tzinfo=UTC), day="2026-08-20")
    b = attachment(FACT_B, evidence_time=datetime(2026, 8, 20, 7, tzinfo=UTC), day="2026-08-20")
    assert Q.evidence_date_set((a, b)) == ("2026-08-20",) and not Q.has_temporal_diversity((a, b))


# ---------------------------------------------------------------- 資格判定

def test_qualification_requires_both_diversities() -> None:
    qualifies = observation(attachments=(attachment(FACT_A, day="2026-08-20"), doc(day="2026-08-25")))
    result = Q.evaluate_qualification(qualifies)
    assert result.status is Q.QualificationStatus.QUALIFIES_SEMANTICALLY and result.diagnostics == ()
    assert result.independent_origins == 2 and result.evidence_dates == ("2026-08-20", "2026-08-25")
    same_day = observation(attachments=(attachment(FACT_A, day="2026-08-20"), doc(day="2026-08-20")))
    assert Q.evaluate_qualification(same_day).status is Q.QualificationStatus.THEME_CANDIDATE_POSSIBLE
    assert "SINGLE_EVIDENCE_DATE" in Q.evaluate_qualification(same_day).diagnostics


def test_qualification_excludes_context_llm_missing_and_unknown() -> None:
    atts = (
        attachment(FACT_A, role=EvidenceRole.CONTEXT, cref=""),
        attachment(FACT_B, provenance=ProvenanceClass.LLM_PROPOSAL, asserted_by="model:x", day="2026-08-21"),
        doc(quality=EvidenceTimeQuality.MISSING, role=EvidenceRole.CONTEXT, cref=""),
        attachment(OBS_X, EvidenceKind.OBSERVATION, src=UNKNOWN, day="2026-08-22"),
    )
    result = Q.evaluate_qualification(observation(attachments=atts))
    assert result.status is Q.QualificationStatus.THEME_CANDIDATE_POSSIBLE
    assert set(result.diagnostics) >= {"CONTEXT_ROLE_EXCLUDED:2", "LLM_PROPOSAL_ROLE_EXCLUDED:1",
                                       "UNKNOWN_ORIGIN_EXCLUDED:1", "NO_KNOWN_SOURCE_ORIGIN"}
    assert result.counted_attachment_keys == (f"{OBS_X}#c1",) and result.independent_origins == 0


def test_qualification_single_event_frame_does_not_qualify() -> None:
    for frame in M.SINGLE_PERIOD_FRAMES:
        result = Q.evaluate_qualification(observation(scope=scope(frame=frame),
                                                      attachments=(attachment(FACT_A), doc(day="2026-08-25"))))
        assert result.status is Q.QualificationStatus.DOES_NOT_QUALIFY
        assert f"Q4_SINGLE_PERIOD_FRAME:{frame}" in result.diagnostics


def test_qualification_without_evidence_is_candidate_and_result_has_no_score() -> None:
    result = Q.evaluate_qualification(observation(attachments=()))
    assert result.status is Q.QualificationStatus.THEME_CANDIDATE_POSSIBLE
    assert "NO_COUNTED_EVIDENCE" in result.diagnostics
    assert {f.name for f in M.fields(Q.QualificationResult)} == {"status", "diagnostics", "counted_attachment_keys",
                                                                  "independent_origins", "evidence_dates"}


def test_qualification_is_pure_and_flags_contradiction_and_invalidation() -> None:
    obs = observation(attachments=(attachment(FACT_A), doc(role=EvidenceRole.CONTRADICTS),
                                   attachment(NEWS_D, EvidenceKind.NEWS_ITEM, src=ARTICLE, day="2026-08-27",
                                              role=EvidenceRole.INVALIDATES, invalidation_condition_ref="inv1", cref="")))
    line_before = M.canonical_line(obs)
    result = Q.evaluate_qualification(obs)
    assert M.canonical_line(obs) == line_before
    assert {"HAS_CONTRADICTING_EVIDENCE", "HAS_INVALIDATING_EVIDENCE"} <= set(result.diagnostics)
    assert result.status is Q.QualificationStatus.QUALIFIES_SEMANTICALLY   # 反証があっても資格判定は独立
    with pytest.raises(Exception):
        result.status = Q.QualificationStatus.DOES_NOT_QUALIFY  # type: ignore[misc]


def test_evidence_supported_class_without_diversity_is_diagnosed_not_changed() -> None:
    obs = observation(certainty_class=MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM,
                      attachments=(attachment(FACT_A), attachment(FACT_B, day="2026-08-21")))
    result = Q.evaluate_qualification(obs)
    assert "EVIDENCE_SUPPORTED_CLASS_WITHOUT_DIVERSITY" in result.diagnostics
    assert obs.certainty_class is MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM


# ---------------------------------------------------------------- entity links

def test_directly_evidenced_links_are_derived_from_attachment_subjects() -> None:
    e1 = EntityRef(kind=ThemeEntityKind.INDEX, value="index:topix")
    e2 = EntityRef(kind=ThemeEntityKind.COMPANY, value="jp:security:72030")
    obs = observation(attachments=(attachment(FACT_A, subject_refs=(e1,)), attachment(FACT_B, day="2026-08-21",
                                                                                      subject_refs=(e2, e1))))
    links = Q.directly_evidenced_links(obs)
    assert [(l.entity.value, l.ref_ids, l.link_class) for l in links] == [
        ("jp:security:72030", (FACT_B,), EntityLinkClass.DIRECTLY_EVIDENCED),
        ("index:topix", (FACT_A, FACT_B), EntityLinkClass.DIRECTLY_EVIDENCED)]
    assert "directly_evidenced" not in M.canonical_line(obs) and "DIRECTLY_EVIDENCED" not in M.canonical_line(obs)


def test_inferred_links_are_semantic_with_provenance_and_no_recommendation_fields() -> None:
    names = {f.name for f in M.fields(M.InferredExposureLink)}
    assert names == {"entity", "exposure_kind", "uncertainty", "provenance_class", "provenance_ref", "note", "link_class"}
    assert not {"weight", "side", "target_price", "position", "buy", "sell"} & names
    with raises("MISSING_PROVENANCE"):
        inferred_link(provenance=ProvenanceClass.RULE)
    with raises("MISSING_PROVENANCE"):
        inferred_link(provenance=ProvenanceClass.LLM_PROPOSAL)
    conflicting = M.InferredExposureLink(entity=EntityRef(kind=ThemeEntityKind.COMPANY, value="jp:security:72030"),
                                         exposure_kind=M.ExposureKind.BENEFICIARY,
                                         uncertainty=M.ExposureUncertainty.HYPOTHESIZED,
                                         provenance_class=ProvenanceClass.HUMAN)
    with raises("DUPLICATE_KEY"):
        observation(inferred_links=(inferred_link(), conflicting))          # 同一 entity に 2 つの link は不可
    assert len(observation(inferred_links=(inferred_link(), inferred_link())).inferred_links) == 1  # 同一 link は集合
    obs = observation(inferred_links=(inferred_link(),))
    assert obs.identity_payload()["inferred_links"] == obs.inferred_links   # semantic（identity core 外）


def test_entity_link_class_representations_follow_a2() -> None:
    data = M._as_json(inferred_link())
    data["link_class"] = "DIRECTLY_EVIDENCED"
    with raises("INVALID_VOCABULARY"):
        M.InferredExposureLink.from_dict(data)
    data["link_class"] = "TAXONOMIC_ASSOCIATION"
    with raises("INVALID_VOCABULARY"):
        M.InferredExposureLink.from_dict(data)
    # TAXONOMIC_ASSOCIATION は metadata（ThemeMetadataRecord.TAXONOMY）であり observation には field が無い
    assert "TAXONOMY" in {f.value for f in M.MetadataField}
    assert not {"taxonomy", "taxonomic_links"} & {f.name for f in M.fields(M.ThemeObservation)}
