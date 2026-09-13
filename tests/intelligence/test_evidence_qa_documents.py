"""SourceDocument QA（Phase 1-E）: 次元別評価・Gate判定・health/validity分離。"""
from __future__ import annotations

from src.intelligence.core import serialization
from src.intelligence.core.types import Horizon, SourceTier
from src.intelligence.evidence_qa.assess import assess_source_document
from src.intelligence.evidence_qa.model import (
    DimensionStatus,
    GateDecision,
    QADimension,
)
from src.intelligence.evidence_qa.policy import DAILY_MARKET_V1, GENERIC_V1
from tests.intelligence.qa_fixtures import REF, make_doc, make_source_info

serialization.register_domain_types()


def assess(doc, info=None, policy=GENERIC_V1, **kw):
    return assess_source_document(
        doc, source_info=info or make_source_info(), policy=policy,
        reference_time=REF, **kw)


def test_tier1_fresh_complete_provenance_is_accept() -> None:
    a = assess(make_doc())
    assert a.decision is GateDecision.ACCEPT
    assert a.dimension(QADimension.PROVENANCE).status is DimensionStatus.PASS
    assert a.dimension(QADimension.SOURCE_QUALITY).status is DimensionStatus.PASS
    assert a.issues == ()


def test_tier2_fresh_is_accept() -> None:
    a = assess(make_doc(tier=SourceTier.TIER2),
               make_source_info(tier=SourceTier.TIER2, investment_value="HIGH"))
    assert a.decision is GateDecision.ACCEPT


def test_tier3_general_source_warns_but_not_rejected() -> None:
    """Tier1=truthではない、の裏面: Tier3も即棄却ではなく1次元のWARNにすぎない。"""
    a = assess(make_doc(tier=SourceTier.TIER3),
               make_source_info(tier=SourceTier.TIER3, investment_value="MEDIUM"))
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS
    assert "tier3_general_source" in a.decision_reasons


def test_stale_document_generic_vs_daily_market() -> None:
    """freshnessは用途（policy）依存: 同じ48時間前の文書でも判定が変わる。"""
    doc = make_doc(published_age_hours=48)
    assert assess(doc, policy=GENERIC_V1).decision is GateDecision.ACCEPT
    daily = assess(doc, policy=DAILY_MARKET_V1)
    assert daily.decision is GateDecision.ACCEPT_WITH_WARNINGS  # aging(24h超72h以内)
    very_old = make_doc(published_age_hours=24 * 40)
    assert assess(very_old, policy=GENERIC_V1).decision is GateDecision.LIMITED_USE
    assert "stale_for_policy" in assess(very_old, policy=GENERIC_V1).decision_reasons


def test_horizon_aware_freshness() -> None:
    """3日前の文書: 1週間horizonでは使えるが、intradayではstale。"""
    doc = make_doc(published_age_hours=72)
    ok = assess(doc, policy=GENERIC_V1, horizon=Horizon.ONE_WEEK)
    assert ok.dimension(QADimension.FRESHNESS).status is DimensionStatus.PASS
    intraday = assess(doc, policy=GENERIC_V1, horizon=Horizon.INTRADAY)
    assert intraday.decision is GateDecision.LIMITED_USE
    assert "stale_for_horizon" in intraday.decision_reasons


def test_published_unknown_not_auto_reject() -> None:
    """日付不明は即REJECTしない。GENERICはWARN、DAILY_MARKETはLIMITED。"""
    doc = make_doc(published_age_hours=None)
    assert assess(doc).decision is GateDecision.ACCEPT_WITH_WARNINGS
    assert assess(doc, policy=DAILY_MARKET_V1).decision is GateDecision.LIMITED_USE
    assert "published_unknown" in assess(doc).decision_reasons


def test_inferred_and_naive_dates_warn() -> None:
    a = assess(make_doc(published_inferred=True))
    assert "inferred_date" in [i.code for i in a.issues]
    b = assess(make_doc(date_quality="source_provided_naive"))
    assert "naive_date" in [i.code for i in b.issues]


def test_source_health_separated_from_document_validity() -> None:
    """昨日取得したBOJ文書は、今日endpointが死んでいても無効化されない。"""
    a = assess(make_doc(), make_source_info(health_state="dead"))
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS  # REJECTにならない
    assert "source_dead_now" in [i.code for i in a.issues]
    health = a.dimension(QADimension.SOURCE_HEALTH)
    assert health.status is DimensionStatus.WARN


def test_missing_provenance_rejects() -> None:
    doc = make_doc(content_hash="x")  # 空はコンストラクタが拒否するため別経路で検証
    broken = serialization.decode({**serialization.encode(doc), "locator": ""})
    a = assess(broken)
    assert a.decision is GateDecision.REJECT
    assert "missing_locator" in a.decision_reasons


def test_corrupt_blob_hash_rejects(tmp_path) -> None:
    from src.intelligence.ingestion.raw_store import JsonlRawRepository
    from src.intelligence.sources.model import RawItem

    repo = JsonlRawRepository(tmp_path)
    h, loc, _ = repo.store_body(b"original body")
    repo.add_raw_item(RawItem(
        raw_item_id="raw_item_1", source_id="boj_whatsnew",
        locator="https://www.example.jp/rss", retrieved_at=REF,
        content_hash=h, storage_ref=loc))
    (tmp_path / loc).write_bytes(b"tampered")  # 改竄を模擬
    a = assess(make_doc(), raw_repository=repo)
    assert a.decision is GateDecision.REJECT
    assert "blob_hash_mismatch" in a.decision_reasons


def test_missing_raw_item_reference_rejects_when_repo_given(tmp_path) -> None:
    from src.intelligence.ingestion.raw_store import JsonlRawRepository

    a = assess(make_doc(), raw_repository=JsonlRawRepository(tmp_path))
    assert a.decision is GateDecision.REJECT
    assert "raw_item_not_found" in a.decision_reasons


def test_tank_document_without_raw_is_warn_not_reject() -> None:
    """原文非保存の明示（raw_item_id=""）は断絶とは区別しWARN止まり。"""
    a = assess(make_doc(raw_item_id=""))
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS
    assert "missing_raw_item" in [i.code for i in a.issues]


def test_partial_normalization_warns() -> None:
    from src.intelligence.normalization.model import (
        NormalizationEvent, NormalizationIssue, NormalizationStatus)

    doc = make_doc()
    event = NormalizationEvent(
        event_id="norm_1", raw_item_id=doc.raw_item_id,
        normalizer_name="feed_entry", normalizer_version=doc.normalizer_version,
        normalized_at=REF, status=NormalizationStatus.PARTIAL,
        issues=(NormalizationIssue(code="missing_date"),),
        produced_document_ids=(doc.source_document_id,))
    a = assess(doc, normalization_events=(event,))
    assert "normalization_partial" in [i.code for i in a.issues]
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS


def test_superseded_document_limited_for_daily_market() -> None:
    old = make_doc("doc_old")
    newer = make_doc("doc_new", revision_of="doc_old")
    generic = assess(old, existing_documents=(newer,))
    assert generic.decision is GateDecision.ACCEPT_WITH_WARNINGS  # 歴史用途を広く許す
    daily = assess(old, policy=DAILY_MARKET_V1, existing_documents=(newer,))
    assert daily.decision is GateDecision.LIMITED_USE  # 現在値用途では限定
    assert "superseded" in daily.decision_reasons


def test_retracted_document_rejected_only_with_explicit_evidence() -> None:
    doc = make_doc()
    # 明示evidenceなし → retracted扱いしない（推測しない）
    assert assess(doc).decision is GateDecision.ACCEPT
    a = assess(doc, retracted_ids=frozenset({doc.source_document_id}))
    assert a.decision is GateDecision.REJECT
    assert "retracted" in a.decision_reasons


def test_syndicated_duplicate_warns() -> None:
    doc = make_doc("doc_a", source_id="boj_whatsnew")
    twin = make_doc("doc_b", source_id="mirror_feed")  # 同一fingerprint・別source
    a = assess(doc, existing_documents=(twin,))
    assert "syndicated_duplicate" in [i.code for i in a.issues]


def test_usage_restricted_is_warning_not_trust_failure() -> None:
    a = assess(make_doc(), make_source_info(usage_status="restricted"))
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS
    assert "usage_restricted" in [i.code for i in a.issues]
    # trust系次元はPASSのまま（rightsとtrustを混同しない）
    assert a.dimension(QADimension.SOURCE_QUALITY).status is DimensionStatus.PASS
