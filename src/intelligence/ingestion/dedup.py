"""Exact重複検出（Phase 1-C最小構成）。

P1-Cで扱うのは**exact系のみ**:
  1. body content hash完全一致（同一バイト列の再取得）
  2. canonical URL完全一致（表記ゆれをnormalize_urlで吸収した上での同一URL）
  3. source内GUID完全一致（フィードが宣言する項目ID）

semantic duplicate / cross-publisher再配信検出（tank title_hash / syndicated duplicate）
は**Phase 2のNews Dedup Engine**の責務であり、ここでは実装しない。

インデックスは保存済みレコードから**再構築可能な導出物**（二重保存しない）。
"""
from __future__ import annotations

from typing import Set, Tuple

from .feed_parser import FeedEntry


class ExactDedupIndex:
    """exact重複のin-memoryインデックス。RawRepositoryやパース結果から構築する。"""

    def __init__(self) -> None:
        self._content_hashes: Set[str] = set()
        self._canonical_urls: Set[str] = set()
        self._guids: Set[Tuple[str, str]] = set()  # (source_id, guid)

    # ---- 登録 ----

    def add_content_hash(self, content_hash: str) -> None:
        if content_hash:
            self._content_hashes.add(content_hash)

    def add_entry(self, source_id: str, entry: FeedEntry) -> None:
        if entry.link_canonical:
            self._canonical_urls.add(entry.link_canonical)
        if entry.guid:
            self._guids.add((source_id, entry.guid))

    def add_from_repository(self, repository) -> None:
        """JsonlRawRepository等からbody hash群を取り込む（再構築可能な導出）。"""
        for item in repository.iter_raw_items():
            self.add_content_hash(item.content_hash)

    # ---- 照会 ----

    def seen_content_hash(self, content_hash: str) -> bool:
        return bool(content_hash) and content_hash in self._content_hashes

    def seen_canonical_url(self, canonical_url: str) -> bool:
        return bool(canonical_url) and canonical_url in self._canonical_urls

    def seen_guid(self, source_id: str, guid: str) -> bool:
        return bool(guid) and (source_id, guid) in self._guids

    def is_duplicate_entry(self, source_id: str, entry: FeedEntry) -> bool:
        """canonical URL一致 または source内GUID一致（exact判定のみ）。"""
        return self.seen_canonical_url(entry.link_canonical) or self.seen_guid(source_id, entry.guid)
