"""Enrichmentドメインモデル（Phase 2-E / schema 0.4.x）。

- EnrichmentEvent … 分類の追加・上書き・撤回の**append-only**イベント（監査履歴）。
  NewsItem本体は破壊的更新しない（NO DESTRUCTIVE UPDATE）。
- ReviewQueueItem … canonicalへ入れなかった候補（LLM未知label・曖昧alias等）。
  黙って捨てない——人間レビューのための置き場（処理はP2-F）。
- EnrichmentRun … enrichment実行のrun manifest（corpus fingerprint・taxonomy版数・
  会計を監査可能に記録）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION


class EnrichmentAction(str, Enum):
    ADD_CLASSIFICATION = "add_classification"
    OVERRIDE = "override"              # USERによる置換（旧classificationは残る）
    RETRACT = "retract"                # USERによる撤回（レコードは消さずeffective viewから除外）
    REVIEW_QUEUED = "review_queued"


class ReviewReason(str, Enum):
    LLM_UNKNOWN_LABEL = "llm_unknown_label"      # taxonomyへmapできないLLM出力
    LLM_INVALID_OUTPUT = "llm_invalid_output"    # スキーマ不正のLLM出力（reject）
    AMBIGUOUS_ALIAS = "ambiguous_alias"          # 文脈条件を満たさなかった曖昧alias
    UNKNOWN_TICKER = "unknown_ticker"            # 明示ticker記法だがカタログ未登録


@dataclass(frozen=True, kw_only=True)
class EnrichmentEvent:
    """分類系操作のappend-onlyイベント（Black Box化しない監査線）。"""

    event_id: str  # enr_<ULID>
    news_item_id: str
    action: EnrichmentAction
    dimension: str = ""
    value: str = ""
    classification_id: str = ""          # 対象/新規のNewsClassification
    previous_classification_id: str = ""  # OVERRIDE/RETRACT時の対象
    provenance: str = ""
    classifier_name: str = ""
    classifier_version: str = ""
    created_at: datetime
    note: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_id or not self.news_item_id:
            raise ValueError("event_id / news_item_id are required")
        ensure_aware(self.created_at, "EnrichmentEvent.created_at")
        if self.action in (EnrichmentAction.OVERRIDE, EnrichmentAction.RETRACT):
            if not self.previous_classification_id:
                raise ValueError(f"{self.action.value}はprevious_classification_id必須（履歴保持）")


@dataclass(frozen=True, kw_only=True)
class ReviewQueueItem:
    """canonical taxonomyへ入れなかった候補（NO FREE-FORM DATABASE POLLUTION）。"""

    review_id: str  # rvq_<sha256[:24]>（決定論——同一候補の重複積み上げ防止）
    news_item_id: str
    dimension: str
    candidate_value: str
    reason: ReviewReason
    evidence_field: str = ""
    evidence_text: str = ""
    classifier_name: str = ""
    created_at: datetime
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.review_id or not self.news_item_id or not self.candidate_value:
            raise ValueError("review_id / news_item_id / candidate_value are required")
        ensure_aware(self.created_at, "ReviewQueueItem.created_at")

    @staticmethod
    def make_id(news_item_id: str, dimension: str, candidate: str, reason: str) -> str:
        return content_id("rvq", news_item_id, dimension, candidate, reason)


@dataclass(frozen=True, kw_only=True)
class EnrichmentRun:
    """enrichment実行のrun manifest（append-only・enrichment_runs.jsonl）。"""

    run_id: str  # erun_<ULID>
    started_at: datetime
    completed_at: Optional[datetime] = None
    corpus_fingerprint: str = ""         # 対象NewsItem集合の決定論fingerprint
    entity_catalog_version: str = ""
    theme_taxonomy_version: str = ""
    event_taxonomy_version: str = ""
    classifier_versions: Tuple[str, ...] = ()  # "name:version"の列
    llm_provider: str = ""               # 未使用なら空（LLMはoptional layer）
    llm_model: str = ""
    records_seen: int = 0
    records_classified: int = 0          # 1件以上の分類が付いたNewsItem数
    records_unclassified: int = 0        # 分類ゼロ（正直なギャップ）
    records_failed: int = 0
    classifications_added: int = 0
    events_added: int = 0
    review_queued: int = 0
    status: str = "running"              # running / completed
    limit: int = 0                       # 段階実行の上限（0=全件）
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        ensure_aware(self.started_at, "EnrichmentRun.started_at")
