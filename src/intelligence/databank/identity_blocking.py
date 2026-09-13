"""Identity候補生成のblocking index（Phase 2-C）。

IMPORTANT IDENTITY SCALING（監督者指示）: 「3,056件だから総当たり」は禁止。
候補生成は exact key＋blocking bucket のindex参照で行い、全件比較のO(n²)を
backfill本線に入れない（将来10万/100万件へ伸ばせる形）。

blockingキー:
- exact: canonical_locator / (source_id, guid) / content_fingerprint / content_hash
- near-dup bucket: title_keyの先頭12文字（軽微な末尾編集・数字違い連載を同バケットに集める）
- near-dup bucket: (published日付, source_id)（同日同ソースの改稿・連載）

blockingはrecall側の制約（bucket外の準重複は比較されない）であり、precision側の
安全規則（resolver）はそのまま適用される。exact系は完全に捕捉される。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Set

from ..sources.model import SourceDocument
from .identity_signals import title_key


class BlockingIndex:
    """document_id候補集合を返すindex（追加はO(1)キー数・照会はbucket参照のみ）。"""

    def __init__(self) -> None:
        self._by_canonical: Dict[str, Set[str]] = defaultdict(set)
        self._by_guid: Dict[tuple, Set[str]] = defaultdict(set)
        self._by_fingerprint: Dict[str, Set[str]] = defaultdict(set)
        self._by_content_hash: Dict[str, Set[str]] = defaultdict(set)
        self._by_title_prefix: Dict[str, Set[str]] = defaultdict(set)
        self._by_day_source: Dict[tuple, Set[str]] = defaultdict(set)
        self.documents_indexed = 0

    @staticmethod
    def _keys(doc: SourceDocument):
        prefix = title_key(doc.title).replace(" ", "")[:12]
        day = doc.published_at.date().isoformat() if doc.published_at else ""
        return prefix, day

    def add(self, doc: SourceDocument) -> None:
        doc_id = doc.source_document_id
        if doc.canonical_locator:
            self._by_canonical[doc.canonical_locator].add(doc_id)
        if doc.guid:
            self._by_guid[(doc.source_id, doc.guid)].add(doc_id)
        if doc.content_fingerprint:
            self._by_fingerprint[doc.content_fingerprint].add(doc_id)
        if doc.content_hash:
            self._by_content_hash[doc.content_hash].add(doc_id)
        prefix, day = self._keys(doc)
        if prefix:
            self._by_title_prefix[prefix].add(doc_id)
        if day:
            self._by_day_source[(day, doc.source_id)].add(doc_id)
        self.documents_indexed += 1

    def candidates(self, doc: SourceDocument) -> Set[str]:
        """比較すべき既存document_id集合（総当たりの代替）。"""
        result: Set[str] = set()
        if doc.canonical_locator:
            result |= self._by_canonical.get(doc.canonical_locator, set())
        if doc.guid:
            result |= self._by_guid.get((doc.source_id, doc.guid), set())
        if doc.content_fingerprint:
            result |= self._by_fingerprint.get(doc.content_fingerprint, set())
        if doc.content_hash:
            result |= self._by_content_hash.get(doc.content_hash, set())
        prefix, day = self._keys(doc)
        if prefix:
            result |= self._by_title_prefix.get(prefix, set())
        if day:
            result |= self._by_day_source.get((day, doc.source_id), set())
        result.discard(doc.source_document_id)
        return result
