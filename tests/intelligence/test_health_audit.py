"""P2-F: health report＋Phase 2 reconciliation（合成data root）のテスト。"""
from __future__ import annotations

from datetime import timedelta

from src.intelligence.core.ids import content_id, new_id
from src.intelligence.core.types import SourceTier
from src.intelligence.databank.article_store import (
    ArticleIdentityEvent,
    IdentityEventType,
    JsonlArticleStore,
)
from src.intelligence.databank.backfill import JsonlNewsBankStore
from src.intelligence.databank.health import (
    BLOCKED,
    DEGRADED,
    SOURCE_VALIDATED_NOT_LOCAL,
    build_health_report,
)
from src.intelligence.databank.news_model import NewsItem
from src.intelligence.databank.phase2_audit import build_phase2_reconciliation
from src.intelligence.databank.sqlite_index import SqliteNewsIndex
from src.intelligence.evidence_qa.assess import assess_source_document
from src.intelligence.evidence_qa.model import SourceInfo
from src.intelligence.evidence_qa.policy import HISTORICAL_V1
from src.intelligence.evidence_qa.store import JsonlAssessmentStore
from src.intelligence.normalization.store import JsonlNormalizedStore
from src.intelligence.sources.model import SourceDocument

from .enrichment_fixtures import NOW


def _build_bank(data_root):
    bank = data_root / "databank"
    normalized = JsonlNormalizedStore(bank / "normalized")
    news = JsonlNewsBankStore(bank / "news")
    articles = JsonlArticleStore(bank / "articles")
    qa = JsonlAssessmentStore(bank / "evidence_qa")
    index = SqliteNewsIndex(bank / "index" / "news.sqlite3")

    items = []
    for n, kind in ((1, "distinct"), (2, "distinct"), (3, "candidate")):
        doc = SourceDocument(
            source_document_id=content_id("doc", f"synthetic{n}"),
            source_id="test_source", source_tier=SourceTier.TIER2,
            title=f"headline {n}", locator=f"https://example.com/{n}",
            canonical_locator=f"https://example.com/{n}",
            retrieved_at=NOW, published_at=NOW - timedelta(hours=n),
            content_hash="h" * 64, content_fingerprint="f" * 24,
            normalizer_name="feed", normalizer_version="1.0.0")
        normalized.add_documents([doc])
        article_id = content_id("art", f"synthetic{n}")
        articles.append_event(ArticleIdentityEvent(
            event_id=new_id("aie", NOW), event_type=IdentityEventType.CREATE,
            article_id=article_id, created_at=NOW,
            document_id=doc.source_document_id,
            identity_basis="exact_canonical_url", actor="algorithm:1.0.0",
            decision_kind=kind, representative_title=doc.title))
        item = NewsItem(
            news_item_id=NewsItem.make_id(article_id), article_id=article_id,
            primary_document_id=doc.source_document_id, headline=doc.title,
            published_at=doc.published_at, publisher="Test", source_id="test_source",
            language="en", canonical_url=doc.locator)
        news.add_news_item(item)
        items.append(item)
        qa.add_assessment(assess_source_document(
            doc, source_info=SourceInfo(source_id="test_source", tier=SourceTier.TIER2),
            policy=HISTORICAL_V1, reference_time=NOW))
    index.index_news_items(items)
    index.close()
    return bank


class TestReconciliation:
    def test_zero_unknown_loss_on_consistent_bank(self, tmp_path):
        _build_bank(tmp_path)
        result = build_phase2_reconciliation(tmp_path)
        assert result["zero_unknown_loss"] is True
        assert result["identity_accounting"]["identity_ok"] is True
        assert result["counts"]["news_source_documents"] == 3
        assert result["counts"]["identity_candidates"] == 1
        assert result["schema_versions"] == ["0.4.0"]
        assert result["sqlite_consistent"] is True

    def test_orphan_detected(self, tmp_path):
        bank = _build_bank(tmp_path)
        # 孤児classificationを注入
        from src.intelligence.databank.news_model import (
            ClassificationDimension, ClassificationProvenance, NewsClassification)
        from src.intelligence.enrichment.store import JsonlEnrichmentStore
        enrichment = JsonlEnrichmentStore(bank / "news" / "enrichment")
        enrichment.add_classification(NewsClassification(
            classification_id=NewsClassification.make_id("news_ghost", "theme", "ai", "x:1"),
            news_item_id="news_ghost", dimension=ClassificationDimension.THEME,
            value="ai", provenance=ClassificationProvenance.RULE_BASED,
            classifier_name="x", classifier_version="1", created_at=NOW))
        result = build_phase2_reconciliation(tmp_path)
        assert result["zero_unknown_loss"] is False
        assert any(i.startswith("orphans:classifications") for i in result["issues"])

    def test_identity_mismatch_detected(self, tmp_path):
        bank = _build_bank(tmp_path)
        # NewsItem欠落を注入（articleより少ない）→ 会計不一致
        import os
        path = bank / "news" / "news_items.jsonl"
        lines = path.read_text().strip().split("\n")
        path.write_text("\n".join(lines[:-1]) + "\n")
        result = build_phase2_reconciliation(tmp_path)
        assert "identity_accounting_mismatch" in result["issues"]


class TestHealthReport:
    def test_states_and_critical_gaps_always_visible(self, tmp_path):
        _build_bank(tmp_path)
        report = build_health_report(tmp_path)
        assert report["components"]["news_bank"]["state"] == "HEALTHY"
        assert report["components"]["news_bank"]["qa_coverage_pct"] == 100.0
        # market bankなし→DEGRADED理由コード（単一scoreではなくreason優先）
        assert "market_bank_not_local" in report["reason_codes"]
        # CRITICAL SOURCE GAPSは**状態に関わらず必ず表示**する
        p3 = report["components"]["phase3_readiness"]
        gaps = {g["series_id"] for g in p3["critical_source_gaps"]}
        assert gaps == {"index:topix.close.closing.tokyo",
                        "rates:JGB10Y.yield.closing.tokyo",
                        "rates:UST2Y.yield.closing.us"}
        # P2-G.2 closeout後: 3ギャップともカタログ上live実証済み（probe:false）だが、
        # このfixtureにはmarket bankが無い。「供給元は実証済み・ローカルには無い」を
        # BLOCKEDと混同せず区別する（ローカル欠如を供給元ギャップとして偽らない）。
        assert all(g["status"] == SOURCE_VALIDATED_NOT_LOCAL
                   for g in p3["critical_source_gaps"])
        assert p3["state"] == DEGRADED
        assert p3["reason_codes"] == [
            "gap_closure_validated_awaiting_supervisor_promotion"]

    def test_mismatch_becomes_blocked(self, tmp_path):
        bank = _build_bank(tmp_path)
        path = bank / "news" / "news_items.jsonl"
        lines = path.read_text().strip().split("\n")
        path.write_text("\n".join(lines[:-1]) + "\n")
        report = build_health_report(tmp_path)
        assert report["components"]["news_bank"]["state"] == BLOCKED
        assert "news_items_vs_articles_mismatch" in report["reason_codes"]
