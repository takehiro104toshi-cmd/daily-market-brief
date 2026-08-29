"""出所（provenance）ドメインモデル（Phase 1-A / schema 0.2.0）。

取得の流れとモデルの対応:
    Source（情報源カタログの1項目・人間可読slug ID）
      → RawItem（取得した生ペイロードの記録。原文へ遡る最後の砦）
        → SourceDocument（生ペイロードを解釈した文書メタデータ）
          → Statement / Observation（evidence/・market/ が所有）

設計判断:
- SourceDocument / RawItem のIDは content-addressed（同一内容→同一ID）。
  Phase 2のdedup（tankのcanonical/content/titleハッシュ資産）を受け入れる余地として
  content_hash / canonical識別をschemaに確保する（dedup engine自体は作らない）。
- source_tier はSourceDocumentへ**取得時点のスナップショット**として非正規化保持する
  （カタログの後日変更が過去文書の格付けを書き換えないため）。
- 訂正・改定は上書きせず revision_of で新レコードを積む（過去値を消さない）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware, ensure_aware_or_none
from ..core.types import SCHEMA_VERSION, SourceTier


@dataclass(frozen=True, kw_only=True)
class Source:
    """情報源カタログの1項目。source_idは knowledge/source_feeds.yaml のidと一致させる。"""

    source_id: str  # 人間可読slug（例: "fed_press", "nikkei"）
    name: str
    publisher: str = ""
    tier: SourceTier = SourceTier.TIER3
    url: str = ""  # フィード/ホームのlocator
    language: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.name:
            raise ValueError("name is required")


@dataclass(frozen=True, kw_only=True)
class RawItem:
    """取得した生ペイロードの記録。

    本文そのもの（bytes）はストレージ側（storage_ref先）に置き、ここではメタデータと
    content_hashのみ持つ。全FACTは最終的にここへ遡れる（rawが保存されなかった場合は
    storage_ref=""で「原文非保存」を明示する）。
    """

    raw_item_id: str  # content-addressed: raw_<sha256[:24]>
    source_id: str
    locator: str  # 取得したURL等
    retrieved_at: datetime
    media_type: str = "application/octet-stream"
    content_hash: str = ""  # sha256 hex（本文全体）
    size_bytes: int = 0
    storage_ref: str = ""  # 生データの保存先参照（path等）。空=原文非保存
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.raw_item_id:
            raise ValueError("raw_item_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        ensure_aware(self.retrieved_at, "RawItem.retrieved_at")

    @staticmethod
    def make_id(source_id: str, locator: str, content_hash: str) -> str:
        return content_id("raw", source_id, locator, content_hash)


@dataclass(frozen=True, kw_only=True)
class SourceDocument:
    """情報源が公表した1文書（記事・声明・統計リリース等）の解釈済みメタデータ。"""

    source_document_id: str  # content-addressed: doc_<sha256[:24]>
    source_id: str
    source_tier: SourceTier  # 取得時点のスナップショット（カタログ変更の影響を受けない）
    title: str
    locator: str  # url等。紙資料はfile locator
    retrieved_at: datetime
    published_at: Optional[datetime] = None
    publisher: str = ""
    language: str = ""
    content_hash: str = ""  # sha256 hex
    raw_item_id: str = ""  # 由来する生ペイロード（空=原文非保存を明示）
    summary: str = ""  # 権利上安全な短い要約/抜粋のみ（本文全文は持たない）
    revision_of: Optional[str] = None  # 訂正・改定元のsource_document_id（過去値は消さない）
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_document_id:
            raise ValueError("source_document_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.title:
            raise ValueError("title is required")
        if not self.content_hash:
            raise ValueError("content_hash is required (provenance)")
        ensure_aware(self.retrieved_at, "SourceDocument.retrieved_at")
        ensure_aware_or_none(self.published_at, "SourceDocument.published_at")

    @staticmethod
    def make_id(source_id: str, locator: str, content_hash: str) -> str:
        """同一内容の再取得は同一IDになる（dedup readiness）。"""
        return content_id("doc", source_id, locator, content_hash)


def latest_revisions(documents: Tuple[SourceDocument, ...]) -> Tuple[SourceDocument, ...]:
    """revision_ofで置換された文書を除いた「最新版のみ」を返す（元データは消さない）。

    supersedes関係はrevision_ofから導出する（XがYをreviseする ⇔ XはYをsupersede）。
    """
    superseded = {d.revision_of for d in documents if d.revision_of}
    return tuple(d for d in documents if d.source_document_id not in superseded)
