"""tank記事互換（Phase 1-D）: 代表sampleがP1-D pipelineへ投入可能なことの確認。

3,056件のfull migrationは禁止（Phase 2正式backfill）。fixtureは実shardの
スキーマを写した合成データ。tank cloneが存在する環境では実レコード数件でも検証する。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.core.types import SourceTier
from src.intelligence.normalization.feed_normalizer import SourceMeta
from src.intelligence.normalization.model import NormalizationStatus
from src.intelligence.normalization.tank_article_normalizer import normalize_tank_article

META = SourceMeta(source_id="bbc_world", tier=SourceTier.TIER2, publisher="BBC News")

#: 実shard（2026-07-19.jsonl）のスキーマを写した合成代表レコード
FIXTURE_ARTICLE = {
    "article_id": "art_0000000000000000fixture1",
    "canonical_url": "https://www.example.co.uk/news/articles/abc123?at_campaign=rss",
    "normalized_url": "https://www.example.co.uk/news/articles/abc123",
    "source_name": "BBC News — World",
    "source_domain": "example.co.uk",
    "language": "en",
    "title_original": "Central bank &amp; markets update",
    "description": "A summary  of the\r\narticle body.",
    "published_at_utc": "2026-07-18T16:56:34+00:00",
    "fetched_at_utc": "2026-07-18T17:01:53.929101+00:00",
    "content_hash": "38" * 32,
    "source_type": "rss",
    "source_trust": 0.8,
}

FIXTURE_DATE_INFERRED = {
    **FIXTURE_ARTICLE,
    "article_id": "art_0000000000000000fixture2",
    "published_at_utc": "2026-07-18T17:01:53+00:00",
    "date_inferred": True,
    "raw_published_at": "18 Jul 2026",  # 元のnaive文字列
}


def test_tank_article_maps_to_source_document() -> None:
    result = normalize_tank_article(FIXTURE_ARTICLE, META)
    assert result.status is NormalizationStatus.NORMALIZED
    doc = result.documents[0]
    assert doc.title == "Central bank & markets update"
    assert doc.locator == FIXTURE_ARTICLE["canonical_url"]  # originalを失わない
    # at_campaign等はtank実証済みトラッキングリスト外（tank実データも保持）→残る。
    # www除去・スキーム畳み・キー順ソートのみ適用される
    assert doc.canonical_locator == "https://example.co.uk/news/articles/abc123?at_campaign=rss"
    assert doc.published_at == datetime(2026, 7, 18, 16, 56, 34, tzinfo=timezone.utc)
    assert doc.retrieved_at.tzinfo is not None
    assert doc.guid == FIXTURE_ARTICLE["article_id"]
    assert doc.content_hash == FIXTURE_ARTICLE["content_hash"]
    assert doc.language == "en"
    assert doc.raw_item_id == ""  # tank記事はraw非保存（原文非保存の明示）
    assert doc.normalizer_name == "tank_article"


def test_tank_date_inferred_flag_carried_machine_readable() -> None:
    doc = normalize_tank_article(FIXTURE_DATE_INFERRED, META).documents[0]
    assert doc.published_inferred is True
    assert doc.published_inferred_from == "tank_fetched_at"
    assert doc.published_raw == "18 Jul 2026"  # 元文字列を保持（後から検証可能）


def test_tank_interpreted_fields_are_not_imported() -> None:
    """INTERPRETED層（importance/themes/sentiment等）は意図的に取り込まない。"""
    article = {**FIXTURE_ARTICLE, "importance_score": 0.9,
               "themes": ["ai_semiconductor"], "sentiment": "negative"}
    doc = normalize_tank_article(article, META).documents[0]
    encoded = str(doc)
    assert "ai_semiconductor" not in encoded and "negative" not in encoded


def test_tank_missing_title_rejected_not_silently_fixed() -> None:
    result = normalize_tank_article({**FIXTURE_ARTICLE, "title_original": ""}, META)
    assert result.status is NormalizationStatus.REJECTED
    assert any(i.code == "missing_title" for i in result.issues)


TANK_SHARD = Path(
    "/home/user/takehiro104toshi-cmd/article-intelligence-data-tank"
    "/data/article_store/shards/2026/07/2026-07-19.jsonl"
)


@pytest.mark.skipif(not TANK_SHARD.exists(), reason="tank clone not present (CI等)")
def test_real_tank_shard_sample_normalizes() -> None:
    """実shardの先頭5件（代表sample・READ ONLY）で互換性を確認する。bulk禁止。"""
    with TANK_SHARD.open(encoding="utf-8") as f:
        records = [json.loads(next(f)) for _ in range(5)]
    ok = 0
    for rec in records:
        result = normalize_tank_article(rec, META)
        assert result.status in (NormalizationStatus.NORMALIZED, NormalizationStatus.PARTIAL)
        ok += len(result.documents)
    assert ok == 5
