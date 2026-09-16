"""Reviewドメインモデル（Phase 2-F PART B）。

- ReviewItem … 人間reviewの1対象（identity CANDIDATE・曖昧alias・未知ticker・
  LLM未知label・revision/syndication曖昧・source mapping曖昧）。
  statusの更新は**新version追記**（append-log latest-wins。破壊的上書きなし）。
- ReviewDecisionRecord … 人間のdecision 1件（append-only。削除不可）。
  manual decisionはalgorithm判定より優先される（適用先の各storeが保証:
  article eventsのuser actor / enrichmentのUSER provenance）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION


class ReviewType(str, Enum):
    IDENTITY_CANDIDATE = "identity_candidate"        # P2-B/C CANDIDATE（mergeされなかった）
    AMBIGUOUS_ALIAS = "ambiguous_alias"              # 文脈条件未達の曖昧entity alias
    UNKNOWN_TICKER = "unknown_ticker"                # 明示ticker記法・カタログ未登録
    LLM_UNKNOWN_LABEL = "llm_unknown_label"          # taxonomy外のLLM label
    ENRICHMENT_UNCERTAIN = "enrichment_uncertain"    # その他enrichment保留（LLM不正出力等）
    REVISION_SYNDICATION = "revision_syndication"    # revision/syndication関係の曖昧
    SOURCE_MAPPING = "source_mapping"                # legacy source対応の曖昧


class ReviewStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"
    DEFERRED = "deferred"


class ReviewDecisionKind(str, Enum):
    MERGE = "merge"
    KEEP_SEPARATE = "keep_separate"
    MARK_REVISION = "mark_revision"
    MARK_SYNDICATED = "mark_syndicated"
    LINK_ENTITY = "link_entity"
    REJECT_ENTITY = "reject_entity"
    ADD_ALIAS = "add_alias"
    CLASSIFY = "classify"
    RETRACT_CLASSIFICATION = "retract_classification"
    DEFER = "defer"


#: review typeごとに許されるdecision（誤適用の構造防止）
ALLOWED_DECISIONS = {
    ReviewType.IDENTITY_CANDIDATE: frozenset({
        ReviewDecisionKind.MERGE, ReviewDecisionKind.KEEP_SEPARATE,
        ReviewDecisionKind.MARK_REVISION, ReviewDecisionKind.MARK_SYNDICATED,
        ReviewDecisionKind.DEFER}),
    ReviewType.AMBIGUOUS_ALIAS: frozenset({
        ReviewDecisionKind.LINK_ENTITY, ReviewDecisionKind.REJECT_ENTITY,
        ReviewDecisionKind.DEFER}),
    ReviewType.UNKNOWN_TICKER: frozenset({
        ReviewDecisionKind.ADD_ALIAS, ReviewDecisionKind.REJECT_ENTITY,
        ReviewDecisionKind.DEFER}),
    ReviewType.LLM_UNKNOWN_LABEL: frozenset({
        ReviewDecisionKind.CLASSIFY, ReviewDecisionKind.REJECT_ENTITY,
        ReviewDecisionKind.DEFER}),
    ReviewType.ENRICHMENT_UNCERTAIN: frozenset({
        ReviewDecisionKind.CLASSIFY, ReviewDecisionKind.RETRACT_CLASSIFICATION,
        ReviewDecisionKind.REJECT_ENTITY, ReviewDecisionKind.DEFER}),
    ReviewType.REVISION_SYNDICATION: frozenset({
        ReviewDecisionKind.MARK_REVISION, ReviewDecisionKind.MARK_SYNDICATED,
        ReviewDecisionKind.KEEP_SEPARATE, ReviewDecisionKind.DEFER}),
    ReviewType.SOURCE_MAPPING: frozenset({
        ReviewDecisionKind.LINK_ENTITY, ReviewDecisionKind.KEEP_SEPARATE,
        ReviewDecisionKind.DEFER}),
}


@dataclass(frozen=True, kw_only=True)
class ReviewItem:
    review_id: str  # rvw_<sha256[:24]>（対象から決定論——重複intake防止）
    record_id: str  # 対象レコード（article_id / news_item_id / document_id等）
    record_type: str  # "article" / "news_item" / "source_document" / "source"
    review_type: ReviewType
    reason_codes: Tuple[str, ...] = ()
    candidate_values: Tuple[str, ...] = ()  # 候補（entity_id・label・article_id等）
    evidence_refs: Tuple[str, ...] = ()     # 根拠参照（event_id・classification_id・抜粋）
    created_at: datetime
    status: ReviewStatus = ReviewStatus.OPEN
    resolution: str = ""       # 決定内容の要約（decision kind＋主要params）
    resolved_at: Optional[datetime] = None
    resolved_by: str = ""
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.review_id or not self.record_id:
            raise ValueError("review_id / record_id are required")
        ensure_aware(self.created_at, "ReviewItem.created_at")
        if self.status is not ReviewStatus.OPEN and not self.resolution \
                and self.status is not ReviewStatus.DEFERRED:
            raise ValueError("非OPEN statusにはresolution必須（黙って閉じない）")

    @staticmethod
    def make_id(review_type: str, record_id: str, discriminator: str = "") -> str:
        return content_id("rvw", review_type, record_id, discriminator)


@dataclass(frozen=True, kw_only=True)
class ReviewDecisionRecord:
    """人間decision 1件（append-only監査履歴。削除・上書きAPIなし）。"""

    decision_id: str  # rvd_<ULID>
    review_id: str
    decision: ReviewDecisionKind
    decided_by: str   # "user:<name>"
    decided_at: datetime
    params: Tuple[Tuple[str, str], ...] = ()   # 例: (("target_article_id", "art_x"),)
    applied_effects: Tuple[str, ...] = ()      # 実際に発行したevent/classification ID等
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.decision_id or not self.review_id:
            raise ValueError("decision_id / review_id are required")
        if not self.decided_by.startswith("user:"):
            raise ValueError("decided_byは 'user:<name>' 形式（manual優先制御に必須）")
        ensure_aware(self.decided_at, "ReviewDecisionRecord.decided_at")
