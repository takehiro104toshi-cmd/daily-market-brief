"""Immutable Raw Store（Phase 1-C）の検証: atomic・冪等・crash-safe・hash照合。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.ingestion.raw_store import BlobStore, JsonlRawRepository
from src.intelligence.sources.model import RawItem

NOW = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)


def make_item(content_hash: str, locator: str, source_id: str = "src_a") -> RawItem:
    return RawItem(
        raw_item_id=RawItem.make_id(source_id, "https://example.org/f", content_hash),
        source_id=source_id,
        locator="https://example.org/f",
        retrieved_at=NOW,
        media_type="application/rss+xml",
        content_hash=content_hash,
        size_bytes=10,
        storage_ref=locator,
        endpoint_id="ep_x",
        fetch_attempt_id="fetch_x",
    )


def test_blob_store_atomic_and_dedup(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    body = b"<rss>hello</rss>"
    h1, loc1, created1 = store.store(body)
    assert created1 and store.exists(h1)
    assert h1 == hashlib.sha256(body).hexdigest()
    # 同一bodyの再格納 → 物理dedup（新規作成なし）
    h2, loc2, created2 = store.store(body)
    assert (h1, loc1) == (h2, loc2) and not created2
    # tempファイル残骸なし（atomic write）
    assert not list(tmp_path.rglob(".blob-*.tmp"))
    assert store.read(h1) == body
    assert store.verify_blob(h1)


def test_blob_verify_detects_corruption(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    h, loc, _ = store.store(b"original")
    (tmp_path / loc).write_bytes(b"tampered!")
    assert not store.verify_blob(h)


def test_blob_locator_cannot_escape_root(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    with pytest.raises(ValueError):
        store.read_locator("../../etc/passwd")


def test_repository_roundtrip_and_reopen(tmp_path: Path) -> None:
    repo = JsonlRawRepository(tmp_path)
    h, loc, _ = repo.store_body(b"body-bytes")
    item = make_item(h, loc)
    assert repo.add_raw_item(item) is True
    # 再オープンで読み戻せる（re-open/read）
    repo2 = JsonlRawRepository(tmp_path)
    got = repo2.get_raw_item(item.raw_item_id)
    assert got == item
    assert repo2.read_body(got) == b"body-bytes"  # metadata→body lookup
    assert repo2.recovered_lines == 0


def test_repository_idempotent_and_collision(tmp_path: Path) -> None:
    repo = JsonlRawRepository(tmp_path)
    h, loc, _ = repo.store_body(b"same")
    item = make_item(h, loc)
    assert repo.add_raw_item(item) is True
    assert repo.add_raw_item(item) is False  # 同一ID＋同一内容 → 冪等スキップ
    conflicting = make_item(h, loc)
    object.__setattr__(conflicting, "media_type", "text/plain")  # 同一IDで内容差を偽造
    with pytest.raises(ValueError):
        repo.add_raw_item(conflicting)


def test_repository_recovers_from_truncated_jsonl(tmp_path: Path) -> None:
    """crash-safe: 末尾の書きかけ行があっても安全に復帰し、件数を失わない。"""
    repo = JsonlRawRepository(tmp_path)
    h, loc, _ = repo.store_body(b"complete")
    repo.add_raw_item(make_item(h, loc))
    # クラッシュを模擬: JSONL末尾に不完全な行を残す
    with (tmp_path / "raw_items.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"_type": "RawItem", "raw_item_id": "raw_trunc')
    repo2 = JsonlRawRepository(tmp_path)
    assert len(list(repo2.iter_raw_items())) == 1
    assert repo2.recovered_lines == 1  # silent failureにしない


def test_read_body_refuses_unsaved_original(tmp_path: Path) -> None:
    """storage_ref="" は「原文非保存」の明示 → body lookupはエラーで応える。"""
    repo = JsonlRawRepository(tmp_path)
    item = RawItem(
        raw_item_id="raw_nosave",
        source_id="src_a",
        locator="https://example.org/f",
        retrieved_at=NOW,
        content_hash="ab" * 32,
        storage_ref="",
    )
    with pytest.raises(ValueError):
        repo.read_body(item)
