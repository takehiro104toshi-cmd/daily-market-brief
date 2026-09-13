"""News Data Bankドメインモデル（Phase 2-A / schema 0.3.0）。

identity階層（混同禁止）:
    SourceDocument … 1媒体×1取得×1正規化の文書（P1-D所有）
    Article        … 「同じ記事」の束（転載・再配信を跨ぐ）。ArticleIdentityが表す
    News Event     … 「同じ出来事」の束（複数Articleを跨ぐ。Phase 2後半以降）

God NewsItem禁止の分割:
    NewsItem           … 記事単位の索引レコード（metadataのみ。分類・スコアは持たない）
    NewsDocumentLink   … NewsItem↔SourceDocumentの関係（PRIMARY/SYNDICATED/UPDATE）
    NewsClassification … 分類1件=1レコード（value＋**provenance**を必ず分離保持）
    NewsScore          … スコア1件=1レコード（P2-Aでは自動生成しない。モデルのみ）
    EntityReference / ThemeReference … 明示的参照（推測taggingは構築時に拒否）
    LegacyAnnotation   … tank等のINTERPRETED値の隔離置き場（新Truthにしない）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Optional, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware, ensure_aware_or_none
from ..core.types import SCHEMA_VERSION


class ClassificationProvenance(str, Enum):
    """分類・スコアの出所（valueと必ず分離して保持する）。"""

    SOURCE_EXPLICIT = "source_explicit"    # sourceが明示提供（ticker欄・カテゴリ欄等）
    RULE_BASED = "rule_based"              # knowledge/の決定論ルール
    ENTITY_DATABASE = "entity_database"    # 名寄せ辞書（Phase 2 entity resolver）
    LLM = "llm"                            # LLM分類（P2-E以降。承認制）
    USER = "user"                          # ユーザー手動


class DocumentLinkRole(str, Enum):
    PRIMARY = "primary"        # Articleの代表文書
    SYNDICATED = "syndicated"  # 転載・再配信
    UPDATE = "update"          # 同一Articleの更新版


class EntityKind(str, Enum):
    COUNTRY = "country"
    COMPANY = "company"
    TICKER = "ticker"
    SECTOR = "sector"
    INDUSTRY = "industry"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    CENTRAL_BANK = "central_bank"
    # --- Phase 2-E追加（0.x非破壊） ---
    INDEX = "index"
    GOVERNMENT = "government"
    PERSON = "person"


class ClassificationDimension(str, Enum):
    COUNTRY = "country"
    COMPANY = "company"
    INDUSTRY = "industry"
    SECTOR = "sector"
    THEME = "theme"
    EVENT_TYPE = "event_type"
    TIME_HORIZON = "time_horizon"
    # --- Phase 2-E追加（0.x非破壊）: entity mention系の次元 ---
    TICKER = "ticker"
    INDEX = "index"
    CENTRAL_BANK = "central_bank"
    GOVERNMENT = "government"
    PERSON = "person"
    COMMODITY = "commodity"
    CURRENCY = "currency"


class ScoreType(str, Enum):
    IMPORTANCE = "importance"
    MARKET_IMPACT = "market_impact"
    NOVELTY = "novelty"
    LONG_TERM_IMPORTANCE = "long_term_importance"
    USER_RELEVANCE = "user_relevance"


@dataclass(frozen=True, kw_only=True)
class EntityReference:
    """sourceまたは辞書が**明示的に**与えたentity参照。推測taggingは拒否。"""

    kind: EntityKind
    value: str  # 例: "JP", "7203.T", "semiconductor"
    provenance: ClassificationProvenance = ClassificationProvenance.SOURCE_EXPLICIT
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("entity value is required")
        if self.provenance is ClassificationProvenance.LLM:
            raise ValueError("LLM由来のEntityReferenceはP2-Aでは作成禁止（P2-E以降・承認制）")


@dataclass(frozen=True, kw_only=True)
class ThemeReference:
    theme_label: str  # knowledge/theme_relations/themes.yaml のlabel
    provenance: ClassificationProvenance = ClassificationProvenance.SOURCE_EXPLICIT
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.theme_label:
            raise ValueError("theme_label is required")


@dataclass(frozen=True, kw_only=True)
class ArticleIdentity:
    """「同じ記事」の束。P2-Aは**モデルのみ**（semantic clusteringはP2-B）。

    identity_basis: この束が何を根拠に作られたか（P2-B判定器の出力語彙）:
        exact_canonical_url / exact_guid / exact_fingerprint / manual
    """

    article_id: str  # art_<sha256[:24]>（決定論: 代表キーから導出）
    member_document_ids: Tuple[str, ...]  # 構成SourceDocument（≥1）
    canonical_url: str = ""
    representative_title: str = ""
    first_published_at: Optional[datetime] = None
    identity_basis: str = "exact_canonical_url"
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.article_id:
            raise ValueError("article_id is required")
        if not self.member_document_ids:
            raise ValueError("ArticleIdentityは構成文書≥1（空の束を作らない）")
        if self.identity_basis not in (
            "exact_canonical_url", "exact_guid", "exact_fingerprint", "manual"
        ):
            raise ValueError(f"unknown identity_basis: {self.identity_basis}")
        ensure_aware_or_none(self.first_published_at, "ArticleIdentity.first_published_at")

    @staticmethod
    def make_id(basis_key: str) -> str:
        """代表キー（canonical URL等）からの決定論的ID。"""
        return content_id("art", basis_key)


@dataclass(frozen=True, kw_only=True)
class NewsItem:
    """記事単位の索引レコード（**metadataのみ**。分類・スコアは別レコード）。

    headlineはSourceDocument由来のmetadataであり、Fact claimではない
    （「売上が20%増えた」等のclaimはFact層＝P1-A Statement）。
    """

    news_item_id: str  # news_<sha256[:24]>（article_idから決定論導出）
    article_id: str
    primary_document_id: str  # 代表SourceDocument
    headline: str
    published_at: Optional[datetime] = None
    publisher: str = ""
    source_id: str = ""
    language: str = "und"
    canonical_url: str = ""
    summary: str = ""  # source提供のもののみ（生成しない）
    guid: str = ""
    author: str = ""  # source明示のもののみ
    entity_refs: Tuple[EntityReference, ...] = field(default=())
    theme_refs: Tuple[ThemeReference, ...] = field(default=())
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.news_item_id:
            raise ValueError("news_item_id is required")
        if not self.article_id:
            raise ValueError("article_id is required（SourceDocumentへ直接ぶら下げない）")
        if not self.primary_document_id:
            raise ValueError("primary_document_id is required")
        if not self.headline:
            raise ValueError("headline is required")
        ensure_aware_or_none(self.published_at, "NewsItem.published_at")

    @staticmethod
    def make_id(article_id: str) -> str:
        return content_id("news", article_id)


@dataclass(frozen=True, kw_only=True)
class NewsDocumentLink:
    """NewsItem（記事）とSourceDocument（媒体別文書）の関係。"""

    news_item_id: str
    source_document_id: str
    role: DocumentLinkRole = DocumentLinkRole.PRIMARY
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.news_item_id or not self.source_document_id:
            raise ValueError("news_item_id / source_document_id are required")


@dataclass(frozen=True, kw_only=True)
class NewsClassification:
    """分類1件=1レコード。value と provenance を分離保持（将来のtheme=AI等でも
    「どこから来た分類か」を失わない）。P2-Aでは自動生成しない（モデルのみ）。"""

    classification_id: str  # cls_<sha256[:24]>
    news_item_id: str
    dimension: ClassificationDimension
    value: str
    provenance: ClassificationProvenance
    classifier_name: str  # 例: "source_category_field" / "rule:CR_XXX" / モデル名
    classifier_version: str
    created_at: datetime
    # --- Phase 2-E追加（0.x非破壊）。EVERY ENRICHMENT MUST HAVE PROVENANCE ---
    confidence: Optional[Decimal] = None  # 意味はconfidence_typeに従う（雑に統一しない）
    confidence_type: str = ""  # "deterministic_exact" / "rule_multi_signal" / "llm_stated" 等
    role: str = ""  # "" / "primary" / "secondary" / "mention"（primary強制はしない）
    evidence_field: str = ""  # マッチ根拠のフィールド（"headline" / "summary"）
    evidence_text: str = ""   # マッチ根拠の抜粋（全文コピーはしない。説明可能性のため）
    taxonomy_version: str = ""  # 使用したtaxonomy/entity catalogのversion
    basis_document_id: str = ""  # 分類時のprimary document（revision連鎖の追跡）
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.classification_id or not self.news_item_id:
            raise ValueError("classification_id / news_item_id are required")
        if not self.value:
            raise ValueError("classification value is required")
        if not self.classifier_name or not self.classifier_version:
            raise ValueError("classifier name/version are required（provenance追跡）")
        ensure_aware(self.created_at, "NewsClassification.created_at")
        if self.confidence is not None:
            if not isinstance(self.confidence, Decimal):
                raise TypeError("confidence must be Decimal（float禁止）")
            if not (Decimal("0") <= self.confidence <= Decimal("1")):
                raise ValueError(f"confidence out of range: {self.confidence}")
            if not self.confidence_type:
                raise ValueError("confidenceを持つ場合confidence_type必須（意味の混同禁止）")
        if self.role not in ("", "primary", "secondary", "mention"):
            raise ValueError(f"unknown role: {self.role}")

    @staticmethod
    def make_id(news_item_id: str, dimension: str, value: str, classifier: str) -> str:
        return content_id("cls", news_item_id, dimension, value, classifier)


@dataclass(frozen=True, kw_only=True)
class NewsScore:
    """スコア1件=1レコード（importance等）。P2-Aでは自動生成禁止（モデルのみ）。"""

    score_id: str  # scr_<sha256[:24]>
    news_item_id: str
    score_type: ScoreType
    value: Decimal  # floatは拒否
    provenance: ClassificationProvenance
    scorer_name: str
    scorer_version: str
    created_at: datetime
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.score_id or not self.news_item_id:
            raise ValueError("score_id / news_item_id are required")
        if not isinstance(self.value, Decimal):
            raise TypeError("NewsScore.value must be Decimal（float禁止）")
        if not self.scorer_name or not self.scorer_version:
            raise ValueError("scorer name/version are required")
        ensure_aware(self.created_at, "NewsScore.created_at")


@dataclass(frozen=True, kw_only=True)
class LegacyAnnotation:
    """tank等の旧INTERPRETED値の隔離レコード。

    **新classification systemのGround Truthにしない**（参考情報として保持するだけ。
    NewsClassification/NewsScoreへ自動変換しない）。
    """

    annotation_id: str  # lga_<sha256[:24]>
    target_record_id: str  # 対応するSourceDocument / NewsItemのID
    origin: str  # "tank" 等
    annotations: Tuple[Tuple[str, str], ...]  # (key, value文字列)の列。値は文字列で凍結
    note: str = "legacy interpreted data — not ground truth"
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.annotation_id or not self.target_record_id or not self.origin:
            raise ValueError("annotation_id / target_record_id / origin are required")

    @staticmethod
    def from_tank_article(article: Mapping[str, object], target_record_id: str) -> "LegacyAnnotation":
        """tank記事dictのINTERPRETED系フィールドを文字列化して隔離する。"""
        keys = ("importance_score", "market_impact_score", "urgency_score",
                "structural_score", "sentiment", "expected_direction", "themes",
                "industries", "sectors", "event_type", "primary_category")
        pairs = tuple(
            (k, str(article[k])) for k in keys if k in article and article[k] not in ("", [], None)
        )
        return LegacyAnnotation(
            annotation_id=content_id("lga", target_record_id, "tank"),
            target_record_id=target_record_id,
            origin="tank",
            annotations=pairs,
        )
