"""P2-E enrichmentテスト共通フィクスチャ（オフライン決定論）。"""
from __future__ import annotations

from datetime import datetime, timezone

from src.intelligence.core.ids import content_id
from src.intelligence.databank.news_model import NewsItem
from src.intelligence.enrichment.catalog import load_entity_catalog
from src.intelligence.enrichment.engine import EnrichmentEngine
from src.intelligence.enrichment.store import JsonlEnrichmentStore
from src.intelligence.enrichment.taxonomy import load_event_taxonomy, load_theme_taxonomy

NOW = datetime(2026, 8, 30, 9, 0, 0, tzinfo=timezone.utc)
PUBLISHED = datetime(2026, 7, 10, 3, 0, 0, tzinfo=timezone.utc)

_ec = _tt = _et = None


def catalogs():
    global _ec, _tt, _et
    if _ec is None:
        _ec, _tt, _et = load_entity_catalog(), load_theme_taxonomy(), load_event_taxonomy()
    return _ec, _tt, _et


def make_item(headline: str, *, summary: str = "", publisher: str = "Test Wire",
              language: str = "en", published=PUBLISHED,
              entity_refs=(), theme_refs=()) -> NewsItem:
    article_id = content_id("art", headline)
    return NewsItem(
        news_item_id=NewsItem.make_id(article_id),
        article_id=article_id,
        primary_document_id=content_id("doc", headline),
        headline=headline,
        summary=summary,
        published_at=published,
        publisher=publisher,
        source_id="test_source",
        language=language,
        canonical_url=f"https://example.com/{article_id}",
        entity_refs=tuple(entity_refs),
        theme_refs=tuple(theme_refs),
    )


def make_engine(tmp_path, llm=None) -> EnrichmentEngine:
    ec, tt, et = catalogs()
    store = JsonlEnrichmentStore(tmp_path / "enrichment")
    return EnrichmentEngine(store, ec, tt, et, llm_classifier=llm)
