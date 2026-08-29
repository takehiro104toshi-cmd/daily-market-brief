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
    locator: str  # 取得したURL等（redact済み）
    retrieved_at: datetime
    media_type: str = "application/octet-stream"
    content_hash: str = ""  # sha256 hex（本文全体）
    size_bytes: int = 0
    storage_ref: str = ""  # 生データの保存先参照（content locator）。空=原文非保存
    # --- Phase 1-C追加（0.x非破壊。取得パイプラインのtrace用） ---
    endpoint_id: str = ""  # 由来するSourceEndpoint
    encoding: str = ""  # HTTP charset等から判明した場合のみ（bodyの解釈ヒント）
    fetch_attempt_id: str = ""  # 由来する取得試行（FetchAttempt）
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


# ---------------------------------------------------------------------------
# Phase 1-B: Source Registry & Health（God object化を避け、3概念へ分離）
#   Source                  … 情報源のidentity（既存）
#   SourceEndpoint          … 取得口の技術属性（protocol/format/auth/usage）
#   SourceHealthObservation … 死活観測の時系列レコード（現在状態≠履歴を分離）
# ---------------------------------------------------------------------------
from enum import Enum as _Enum  # noqa: E402


class SourceCategory(str, _Enum):
    """情報源カテゴリ（SourceTierとのmapping: docs/sources/SOURCE_CLASSIFICATION.md）。

    PRIMARY_OFFICIAL       → Tier1（中央銀行・政府統計・取引所・企業IR・規制当局・国際機関）
    HIGH_QUALITY_SECONDARY → Tier2（主要経済報道・専門金融メディア）
    GENERAL_SECONDARY      → Tier3（一般ニュース）
    MARKET_DATA_PROVIDER   → Tier2（相場・指標データ提供者）
    OTHER                  → Tier3
    """

    PRIMARY_OFFICIAL = "primary_official"
    HIGH_QUALITY_SECONDARY = "high_quality_secondary"
    GENERAL_SECONDARY = "general_secondary"
    MARKET_DATA_PROVIDER = "market_data_provider"
    OTHER = "other"


class HealthState(str, _Enum):
    HEALTHY = "healthy"            # 到達可・パース可・鮮度良好
    DEGRADED = "degraded"          # 到達はするが品質問題（0件継続・古い・ブロック疑い等）
    AUTH_REQUIRED = "auth_required"  # 認証が無いと使えない（401 / APIキー未設定）
    RATE_LIMITED = "rate_limited"  # 429等
    MOVED = "moved"                # 恒久移転（canonical URLをreplacementへ記録）
    DEAD = "dead"                  # 提供終了・恒常404/410・DNS消滅
    UNVERIFIED = "unverified"      # 現時点で未検証（ネットワーク不能環境からのcheck不成立を含む）


class AuthType(str, _Enum):
    NONE = "none"
    API_KEY_HEADER = "api_key_header"
    API_KEY_QUERY = "api_key_query"    # 禁止予定（Secret規則）。移行対象の記録用
    BEARER = "bearer"
    OTHER = "other"


class FeedFormat(str, _Enum):
    RSS2 = "rss2"
    ATOM = "atom"
    RDF = "rdf"
    JSON_API = "json_api"
    HTML = "html"
    UNKNOWN = "unknown"


class UsageStatus(str, _Enum):
    PUBLIC_FEED = "public_feed"    # 公開RSS/Atom等
    API_TERMS = "api_terms"        # 利用規約付き公式API（EDINET/e-Stat等）
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class SourceEndpoint:
    """取得口の技術属性（identityから分離）。"""

    source_id: str
    url: str
    protocol: str = "https"
    declared_format: FeedFormat = FeedFormat.UNKNOWN
    auth_type: AuthType = AuthType.NONE
    usage_status: UsageStatus = UsageStatus.UNKNOWN
    # Phase 1-C追加: 取得口の安定ID（未指定ならsource_id＋urlから決定的に導出）
    endpoint_id: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("url must be http(s)")
        if not self.endpoint_id:
            object.__setattr__(self, "endpoint_id", self.make_id(self.source_id, self.url))

    @staticmethod
    def make_id(source_id: str, url: str) -> str:
        """同一source×同一URLは常に同一endpoint_id（content-addressed）。"""
        return content_id("ep", source_id, url)


@dataclass(frozen=True, kw_only=True)
class SourceHealthObservation:
    """死活観測1回分の記録（時系列で積む。現在状態はここから導出する）。

    Secret値・認証情報は一切保持しない（auth関連はAuthType列挙のみ）。
    """

    health_obs_id: str  # obs時刻順ID: shealth_<ULID>
    source_id: str
    checked_at: datetime
    state: HealthState
    http_status: int = 0  # 0 = リクエスト不成立（ネットワーク不能等）
    final_url: str = ""  # リダイレクト後の到達URL
    permanent_redirect: bool = False
    content_type: str = ""
    detected_format: FeedFormat = FeedFormat.UNKNOWN
    etag_present: bool = False
    last_modified: Optional[datetime] = None
    latest_item_at: Optional[datetime] = None
    freshness_age_hours: Optional[int] = None
    method: str = "live_http"  # live_http / legacy_ci_report / tank_shards 等のevidence種別
    note: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.health_obs_id:
            raise ValueError("health_obs_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        ensure_aware(self.checked_at, "SourceHealthObservation.checked_at")
        ensure_aware_or_none(self.last_modified, "last_modified")
        ensure_aware_or_none(self.latest_item_at, "latest_item_at")
