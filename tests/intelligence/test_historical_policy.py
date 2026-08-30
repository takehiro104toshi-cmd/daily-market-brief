"""HISTORICAL Trust Policy（Phase 2-B追加承認）: context-dependent trustの実証。"""
from __future__ import annotations

from src.intelligence.core import serialization
from src.intelligence.evidence_qa.assess import assess_source_document
from src.intelligence.evidence_qa.model import DimensionStatus, GateDecision, QADimension
from src.intelligence.evidence_qa.policy import (
    DAILY_MARKET_V1,
    GENERIC_V1,
    HISTORICAL_V1,
    get_policy,
)
from tests.intelligence.qa_fixtures import REF, make_doc, make_source_info

serialization.register_domain_types()


def assess(doc, policy):
    return assess_source_document(doc, source_info=make_source_info(), policy=policy,
                                  reference_time=REF)


def test_historical_policy_is_registered() -> None:
    assert get_policy("HISTORICAL", "1.0.0") is HISTORICAL_V1


def test_old_article_accept_historical_limited_daily() -> None:
    """同一文書: HISTORICAL=ACCEPT / DAILY_MARKET=LIMITED（context-dependent trust）。"""
    six_weeks_old = make_doc(published_age_hours=24 * 42)
    assert assess(six_weeks_old, HISTORICAL_V1).decision is GateDecision.ACCEPT
    assert assess(six_weeks_old, DAILY_MARKET_V1).decision is GateDecision.LIMITED_USE
    assert assess(six_weeks_old, GENERIC_V1).decision is GateDecision.LIMITED_USE


def test_age_itself_never_limits_under_historical() -> None:
    ancient = make_doc(published_age_hours=24 * 365 * 3)  # 3年前
    a = assess(ancient, HISTORICAL_V1)
    assert a.decision is GateDecision.ACCEPT
    freshness = a.dimension(QADimension.FRESHNESS)
    assert freshness.status is DimensionStatus.PASS  # 古さでWARN/LIMITを発生させない


def test_other_gates_preserved_under_historical() -> None:
    """HISTORICALでもprovenance/integrity/retraction等のGateは維持される。"""
    doc = make_doc()
    broken = serialization.decode({**serialization.encode(doc), "locator": ""})
    assert assess(broken, HISTORICAL_V1).decision is GateDecision.REJECT  # provenance
    retracted = assess_source_document(
        doc, source_info=make_source_info(), policy=HISTORICAL_V1, reference_time=REF,
        retracted_ids=frozenset({doc.source_document_id}))
    assert retracted.decision is GateDecision.REJECT  # retraction
    unknown_date = make_doc(published_age_hours=None)
    a = assess(unknown_date, HISTORICAL_V1)
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS  # 日付不明は警告のまま


def test_superseded_usable_as_history_with_warning() -> None:
    old = make_doc("doc_old")
    newer = make_doc("doc_new", revision_of="doc_old")
    a = assess_source_document(
        make_doc("doc_old"), source_info=make_source_info(), policy=HISTORICAL_V1,
        reference_time=REF, existing_documents=(newer,))
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS  # 旧版も歴史として利用可
    assert "superseded" in [i.code for i in a.issues]
