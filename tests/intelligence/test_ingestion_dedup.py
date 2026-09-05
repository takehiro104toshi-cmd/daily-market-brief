"""exact dedup（Phase 1-C最小構成）の検証。semantic dedupはPhase 2で別実装。"""
from __future__ import annotations

from src.intelligence.ingestion.dedup import ExactDedupIndex
from src.intelligence.ingestion.feed_parser import FeedEntry


def entry(link: str = "https://example.org/a?utm_source=x", guid: str = "g-1") -> FeedEntry:
    from src.intelligence.ingestion.url_normalize import normalize_url

    return FeedEntry(title="t", link_original=link, link_canonical=normalize_url(link), guid=guid)


def test_content_hash_exact_duplicate() -> None:
    idx = ExactDedupIndex()
    idx.add_content_hash("ab" * 32)
    assert idx.seen_content_hash("ab" * 32)
    assert not idx.seen_content_hash("cd" * 32)
    assert not idx.seen_content_hash("")


def test_canonical_url_duplicate_absorbs_tracking_variants() -> None:
    idx = ExactDedupIndex()
    idx.add_entry("src_a", entry(link="https://www.example.org/a?utm_source=x"))
    # 同一記事の別トラッキング付きURL → canonical一致で重複と判定
    dup = entry(link="http://example.org/a/?utm_medium=y", guid="g-other")
    assert idx.is_duplicate_entry("src_a", dup)


def test_guid_duplicate_is_scoped_per_source() -> None:
    idx = ExactDedupIndex()
    idx.add_entry("src_a", entry(link="https://example.org/a", guid="tag:1"))
    same_guid_other_link = entry(link="https://example.org/b", guid="tag:1")
    assert idx.is_duplicate_entry("src_a", same_guid_other_link)
    # 別ソースの同名GUIDは重複としない（source内スコープ）
    assert not idx.is_duplicate_entry("src_b", same_guid_other_link)


def test_rebuild_from_repository(tmp_path) -> None:
    from datetime import datetime, timezone

    from src.intelligence.ingestion.raw_store import JsonlRawRepository
    from src.intelligence.sources.model import RawItem

    repo = JsonlRawRepository(tmp_path)
    h, loc, _ = repo.store_body(b"body")
    repo.add_raw_item(RawItem(
        raw_item_id=RawItem.make_id("s", "https://e.org/f", h),
        source_id="s", locator="https://e.org/f",
        retrieved_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        content_hash=h, storage_ref=loc,
    ))
    idx = ExactDedupIndex()
    idx.add_from_repository(repo)  # 導出インデックス（二重保存しない）
    assert idx.seen_content_hash(h)
