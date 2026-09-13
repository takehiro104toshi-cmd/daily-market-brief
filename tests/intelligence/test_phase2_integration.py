"""P2-F PART K: Phase 2 full integration trace。

News query → Article → SourceDocument → Evidence QA → Enrichment →
MarketContextWindow → Market observations → SQLite/query → human-readable trace
を1本で通す（market direction分析はしない——Data Bankが素材を一貫して返すことの確認）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.intelligence.core.ids import content_id, new_id
from src.intelligence.core.types import SourceTier
from src.intelligence.databank.article_store import (
    ArticleIdentityEvent,
    IdentityEventType,
    JsonlArticleStore,
)
from src.intelligence.databank.cross_domain import fetch_window_slice
from src.intelligence.databank.market_window import same_japan_trading_day_window
from src.intelligence.databank.news_model import NewsItem
from src.intelligence.databank.query import NewsQuery
from src.intelligence.databank.sqlite_index import SqliteNewsIndex
from src.intelligence.evidence_qa.assess import assess_source_document
from src.intelligence.evidence_qa.model import SourceInfo
from src.intelligence.evidence_qa.policy import HISTORICAL_V1_1
from src.intelligence.evidence_qa.store import JsonlAssessmentStore
from src.intelligence.market.backfill import MarketBackfillEngine
from src.intelligence.market.store import MarketBankStore
from src.intelligence.normalization.store import JsonlNormalizedStore
from src.intelligence.sources.model import SourceDocument

from .enrichment_fixtures import NOW, make_engine
from .market_fixtures import NIKKEI_CSV, RETRIEVED, catalog, stub_provider

NIKKEI = "index:nikkei225.close.closing.tokyo"
HEADLINE = "Nikkei rallies as semiconductor stocks surge on AI demand"


class TestPhase2IntegrationTrace:
    def _build(self, tmp_path):
        bank = tmp_path / "databank"
        published = datetime(2026, 8, 28, 4, 30, tzinfo=timezone.utc)  # 東京セッション中

        # SourceDocument（P1-D層）
        doc = SourceDocument(
            source_document_id=content_id("doc", HEADLINE),
            source_id="nikkei_news", source_tier=SourceTier.TIER2,
            title=HEADLINE, locator="https://example.com/nikkei-ai",
            canonical_locator="https://example.com/nikkei-ai",
            retrieved_at=published + timedelta(minutes=5), published_at=published,
            content_hash="h" * 64, content_fingerprint="f" * 24,
            raw_item_id="raw_integration000000000",
            normalizer_name="feed", normalizer_version="1.0.0")
        normalized = JsonlNormalizedStore(bank / "normalized")
        normalized.add_documents([doc])

        # Evidence QA（P1-E層）
        qa = JsonlAssessmentStore(bank / "evidence_qa")
        assessment = assess_source_document(
            doc, source_info=SourceInfo(source_id="nikkei_news", tier=SourceTier.TIER2),
            policy=HISTORICAL_V1_1, reference_time=published + timedelta(hours=1))
        qa.add_assessment(assessment)

        # Article Identity（P2-B層）
        articles = JsonlArticleStore(bank / "articles")
        article_id = content_id("art", HEADLINE)
        articles.append_event(ArticleIdentityEvent(
            event_id=new_id("aie", NOW), event_type=IdentityEventType.CREATE,
            article_id=article_id, created_at=NOW, document_id=doc.source_document_id,
            identity_basis="exact_canonical_url", actor="algorithm:1.0.0",
            decision_kind="distinct", representative_title=doc.title))

        # NewsItem（P2-C層）＋Enrichment（P2-E層）
        item = NewsItem(
            news_item_id=NewsItem.make_id(article_id), article_id=article_id,
            primary_document_id=doc.source_document_id, headline=HEADLINE,
            published_at=published, publisher="Example Wire", source_id="nikkei_news",
            language="en", canonical_url=doc.locator)
        engine = make_engine(bank / "news")
        engine.enrich_item(item, now=NOW)

        # News index（P2-A層）
        news_index = SqliteNewsIndex(bank / "index" / "news.sqlite3")
        news_index.index_news_items([item])
        news_index.index_classifications(list(engine.store.iter_classifications()))

        # Market Bank（P2-D層・stub provider＝オフライン）
        market = MarketBankStore(bank / "market")
        MarketBackfillEngine(
            market, catalog(), stub_provider({"s=^nkx": (200, NIKKEI_CSV)}),
            HISTORICAL_V1_1,
        ).run(start=date(2026, 8, 1), end=date(2026, 8, 29), now=RETRIEVED,
              series_ids=(NIKKEI,), with_derivations=False)

        return (bank, doc, assessment, articles, article_id, item, engine,
                news_index, market)

    def test_full_trace(self, tmp_path, capsys):
        (bank, doc, assessment, articles, article_id, item, engine,
         news_index, market) = self._build(tmp_path)

        # 1. News query（theme=aiで発見）
        found = news_index.search_news(NewsQuery(theme="ai"))
        assert [n.news_item_id for n in found] == [item.news_item_id]
        news = found[0]

        # 2. → Article（identity replay）
        identity = articles.get_identity(news.article_id)
        assert identity is not None
        assert news.primary_document_id in identity.member_document_ids

        # 3. → SourceDocument（canonical）
        normalized = JsonlNormalizedStore(bank / "normalized")
        source_doc = normalized.get_document(news.primary_document_id)
        assert source_doc is not None and source_doc.title == HEADLINE

        # 4. → Evidence QA（判定と根拠）
        qa = JsonlAssessmentStore(bank / "evidence_qa")
        latest = qa.latest_for(source_doc.source_document_id)
        assert latest is not None and latest.decision.value in (
            "accept", "accept_with_warnings")

        # 5. → Enrichment（provenance付き分類）
        effective = engine.store.effective_classifications(news.news_item_id)
        themes = {c.value for c in effective if c.dimension.value == "theme"}
        assert {"ai", "semiconductors"} <= themes

        # 6. → MarketContextWindow → Market observations（同一セッション日）
        window = same_japan_trading_day_window(date(2026, 8, 28))
        piece = fetch_window_slice(news_index, market.index, window,
                                   series_ids=(NIKKEI,))
        assert [n.news_item_id for n in piece.news_items] == [news.news_item_id]
        assert len(piece.observations) == 1
        obs_row = piece.observations[0]
        assert obs_row["trading_date"] == "2026-08-28"
        assert obs_row["value"] == "39310.25"

        # 7. → SQLite/query（market側の同値検索）
        latest_row = market.index.latest_trading_session(NIKKEI)
        assert latest_row["observation_id"] == obs_row["observation_id"]

        # 8. → human-readable trace（分析文なし——素材の一貫性のみ）
        trace = "\n".join([
            "=== PHASE 2 INTEGRATION TRACE ===",
            f"news query(theme=ai) -> {news.news_item_id}",
            f"  headline: {news.headline}",
            f"  article: {identity.article_id} (members={len(identity.member_document_ids)})",
            f"  source_document: {source_doc.source_document_id} "
            f"(source={source_doc.source_id}, raw={source_doc.raw_item_id})",
            f"  evidence_qa: {latest.decision.value} "
            f"policy={latest.policy_name}:{latest.policy_version}",
            f"  themes: {sorted(themes)}",
            f"  window: {window.name} [{window.start_utc.isoformat()} .. "
            f"{window.end_utc.isoformat()}]",
            f"  market: {obs_row['series_id']} trading_date={obs_row['trading_date']} "
            f"close={obs_row['value']} source={obs_row['source_id']}",
            "(no market direction analysis — data bank returns materials only)",
        ])
        print(trace)
        for stage in ("news query", "article:", "source_document:", "evidence_qa:",
                      "themes:", "window:", "market:"):
            assert stage in trace
        market.close()
        news_index.close()
