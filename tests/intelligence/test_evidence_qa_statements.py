"""Fact / Analysis / Forecast QA（Phase 1-E）: 裏付け・矛盾・独立corroboration・依存伝播。"""
from __future__ import annotations

from src.intelligence.core.types import VerificationState
from src.intelligence.evidence.model import EvidenceRelation
from src.intelligence.evidence_qa.assess import (
    assess_analysis,
    assess_fact,
    assess_forecast,
    assess_source_document,
)
from src.intelligence.evidence_qa.model import DimensionStatus, GateDecision, QADimension
from src.intelligence.evidence_qa.policy import GENERIC_V1
from tests.intelligence.qa_fixtures import (
    REF,
    make_analysis,
    make_doc,
    make_fact,
    make_forecast,
    make_link,
    make_source_info,
)


def doc_assessment(doc, info=None):
    return assess_source_document(
        doc, source_info=info or make_source_info(), policy=GENERIC_V1,
        reference_time=REF)


def fact_qa(fact, links, **kw):
    return assess_fact(fact, links, policy=GENERIC_V1, reference_time=REF, **kw)


def test_supported_fact_with_tier1_evidence_accepts() -> None:
    fact = make_fact()
    links = (make_link("link_1", "fact_1", "doc_tier1_fresh"),)
    a = fact_qa(fact, links,
                evidence_source_info={"doc_tier1_fresh": make_source_info()})
    assert a.decision is GateDecision.ACCEPT
    assert "supported" in [c for d in a.dimensions for c in d.reason_codes]


def test_unsupported_fact_rejected_regardless_of_origin() -> None:
    """Evidenceゼロ→REJECT。AI生成の自信は通過理由にならない（P1-A invariant維持）。"""
    a = fact_qa(make_fact("fact_ai_generated"), links=())
    assert a.decision is GateDecision.REJECT
    assert "unsupported_fact" in a.decision_reasons


def test_conflicting_fact_limited_not_false() -> None:
    """supporting＋contradicting併存→LIMITED_USE。自動でFALSE判定しない。"""
    fact = make_fact()
    links = (
        make_link("link_s", "fact_1", "doc_a"),
        make_link("link_c", "fact_1", "doc_b", EvidenceRelation.CONTRADICTS),
    )
    a = fact_qa(fact, links)
    assert a.decision is GateDecision.LIMITED_USE
    assert "conflicting_evidence" in a.decision_reasons
    assert a.dimension(QADimension.SUPPORT).status is DimensionStatus.PASS  # 裏付け自体は有


def test_syndicated_corroboration_is_not_independent() -> None:
    """転載2件（同一duplicate_group）≠ 独立2source。"""
    fact = make_fact()
    links = (
        make_link("link_1", "fact_1", "doc_reuters_a"),
        make_link("link_2", "fact_1", "doc_reuters_b"),
    )
    same_group = {
        "doc_reuters_a": make_source_info("reuters_business", duplicate_group="reuters"),
        "doc_reuters_b": make_source_info("yahoo_jp_reuters", duplicate_group="reuters"),
    }
    a = fact_qa(fact, links, evidence_source_info=same_group)
    dup = a.dimension(QADimension.DUPLICATION)
    assert dup.status is DimensionStatus.WARN
    assert "syndicated_duplicate" in dup.reason_codes


def test_independent_corroboration_recognized() -> None:
    fact = make_fact()
    links = (
        make_link("link_1", "fact_1", "doc_boj"),
        make_link("link_2", "fact_1", "doc_nhk"),
    )
    infos = {
        "doc_boj": make_source_info("boj_whatsnew"),
        "doc_nhk": make_source_info("nhk_business"),
    }
    a = fact_qa(fact, links, evidence_source_info=infos)
    dup = a.dimension(QADimension.DUPLICATION)
    assert dup.status is DimensionStatus.PASS
    assert "corroborated_independent" in dup.reason_codes


def test_fact_with_all_supporting_evidence_rejected_is_limited() -> None:
    """依存伝播: 支持Evidence全滅→Factは自動削除せずLIMITED_USE。"""
    bad_doc = make_doc("doc_bad", raw_item_id="")
    bad_assessment = doc_assessment(bad_doc)
    # 強制的にREJECT相当のassessmentを合成せず、実際にREJECTになる文書を使う:
    from src.intelligence.core import serialization
    serialization.register_domain_types()
    broken = serialization.decode({**serialization.encode(bad_doc),
                                   "locator": "", "source_document_id": "doc_rejected"})
    rejected_assessment = doc_assessment(broken)
    assert rejected_assessment.decision is GateDecision.REJECT

    fact = make_fact()
    links = (make_link("link_1", "fact_1", "doc_rejected"),)
    a = fact_qa(fact, links, evidence_assessments={"doc_rejected": rejected_assessment})
    assert a.decision is GateDecision.LIMITED_USE
    assert "weak_supporting_evidence" in a.decision_reasons
    assert bad_assessment.decision is not GateDecision.REJECT  # 対照


def test_retracted_fact_rejected_for_current_analysis() -> None:
    fact = make_fact(verification=VerificationState.RETRACTED)
    links = (make_link("link_1", "fact_1", "doc_a"),)
    a = fact_qa(fact, links)
    assert a.decision is GateDecision.REJECT
    assert "retracted" in a.decision_reasons


def test_analysis_with_rejected_dependency_is_limited_not_deleted() -> None:
    unsupported = fact_qa(make_fact("fact_bad"), links=())
    assert unsupported.decision is GateDecision.REJECT
    analysis = make_analysis(inputs=("fact_bad",))
    a = assess_analysis(analysis, policy=GENERIC_V1, reference_time=REF,
                        input_assessments=(unsupported,))
    assert a.decision is GateDecision.LIMITED_USE  # 自動削除しない・用途制限
    assert "dependency_rejected" in a.decision_reasons


def test_analysis_with_clean_dependency_accepts() -> None:
    good = fact_qa(make_fact(), (make_link("link_1", "fact_1", "doc_a"),))
    a = assess_analysis(make_analysis(), policy=GENERIC_V1, reference_time=REF,
                        input_assessments=(good,))
    assert a.decision is GateDecision.ACCEPT


def test_analysis_with_unassessed_dependency_warns() -> None:
    a = assess_analysis(make_analysis(), policy=GENERIC_V1, reference_time=REF,
                        input_assessments=())
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS
    assert "dependency_unassessed" in a.decision_reasons


def test_forecast_with_weak_evidence_is_limited() -> None:
    rejected = fact_qa(make_fact("fact_weak"), links=())
    forecast = make_forecast(supporting=("fact_weak",))
    a = assess_forecast(forecast, policy=GENERIC_V1, reference_time=REF,
                        supporting_assessments=(rejected,))
    assert a.decision is GateDecision.LIMITED_USE
    assert a.record_type == "forecast"
    assert a.horizon is not None  # ForecastMetadata.horizonが引き継がれる


def test_forecast_with_good_evidence_accepts() -> None:
    good = fact_qa(make_fact(), (make_link("link_1", "fact_1", "doc_a"),))
    a = assess_forecast(make_forecast(), policy=GENERIC_V1, reference_time=REF,
                        supporting_assessments=(good,))
    assert a.decision is GateDecision.ACCEPT
