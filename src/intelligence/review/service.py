"""Review decision適用サービス（Phase 2-F PART B）。

- decideは (1) decision記録をappend → (2) 効果を各storeへ適用（manual優先の
  既存機構を使用: article eventsのuser actor / enrichmentのUSER provenance）→
  (3) ReviewItemの新version追記（status更新・履歴保持）の順で行う。
- decision種はALLOWED_DECISIONSで型的に制限（誤適用の構造防止）。
- 適用効果のID（発行したevent/classification）はdecisionレコードへ記録される
  （何がどう変わったか後から追跡可能——EXPLAINABLE / CORRECTABLE）。
- 本phaseはCLI/service layerまで（本格frontendなし。将来PWAが呼ぶ契約を優先）。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Dict, Mapping, Optional, Tuple

from ..core.ids import new_id
from ..databank.article_store import ArticleIdentityEvent, IdentityEventType, JsonlArticleStore
from ..databank.news_model import ClassificationDimension
from ..enrichment.override import apply_user_override, retract_classification
from ..enrichment.store import JsonlEnrichmentStore
from .model import (
    ALLOWED_DECISIONS,
    ReviewDecisionKind,
    ReviewDecisionRecord,
    ReviewItem,
    ReviewStatus,
)
from .store import JsonlReviewStore

#: decision → 遷移後status
_STATUS_AFTER = {
    ReviewDecisionKind.MERGE: ReviewStatus.RESOLVED,
    ReviewDecisionKind.KEEP_SEPARATE: ReviewStatus.RESOLVED,
    ReviewDecisionKind.MARK_REVISION: ReviewStatus.RESOLVED,
    ReviewDecisionKind.MARK_SYNDICATED: ReviewStatus.RESOLVED,
    ReviewDecisionKind.LINK_ENTITY: ReviewStatus.APPROVED,
    ReviewDecisionKind.REJECT_ENTITY: ReviewStatus.REJECTED,
    ReviewDecisionKind.ADD_ALIAS: ReviewStatus.RESOLVED,
    ReviewDecisionKind.CLASSIFY: ReviewStatus.APPROVED,
    ReviewDecisionKind.RETRACT_CLASSIFICATION: ReviewStatus.RESOLVED,
    ReviewDecisionKind.DEFER: ReviewStatus.DEFERRED,
}


class ReviewService:
    def __init__(
        self,
        review_store: JsonlReviewStore,
        *,
        article_store: Optional[JsonlArticleStore] = None,
        enrichment_store: Optional[JsonlEnrichmentStore] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.reviews = review_store
        self.articles = article_store
        self.enrichment = enrichment_store
        self._clock = clock

    # ------------------------------------------------------------- 参照系

    def open_items(self, review_type=None):
        return list(self.reviews.iter_items(status=ReviewStatus.OPEN,
                                            review_type=review_type))

    # ------------------------------------------------------------- decision

    def decide(
        self,
        review_id: str,
        decision: ReviewDecisionKind,
        *,
        decided_by: str,
        params: Mapping[str, str] = {},
        notes: str = "",
    ) -> ReviewDecisionRecord:
        item = self.reviews.get_item(review_id)
        if item is None:
            raise ValueError(f"unknown review item: {review_id}")
        if decision not in ALLOWED_DECISIONS[item.review_type]:
            raise ValueError(
                f"{item.review_type.value}に{decision.value}は適用できない")
        now = self._clock()
        effects = self._apply(item, decision, params, decided_by, now)
        record = ReviewDecisionRecord(
            decision_id=new_id("rvd", now),
            review_id=review_id,
            decision=decision,
            decided_by=decided_by,
            decided_at=now,
            params=tuple(sorted((str(k), str(v)) for k, v in params.items())),
            applied_effects=effects,
            notes=notes,
        )
        self.reviews.add_decision(record)
        resolution = decision.value + (
            f"({';'.join(f'{k}={v}' for k, v in record.params)})" if record.params else "")
        self.reviews.upsert_item(replace(
            item, status=_STATUS_AFTER[decision], resolution=resolution,
            resolved_at=now, resolved_by=decided_by,
            notes=(item.notes + " | " if item.notes else "") + notes if notes else item.notes,
        ))
        return record

    # ------------------------------------------------------------- 効果適用

    def _apply(self, item: ReviewItem, decision: ReviewDecisionKind,
               params: Mapping[str, str], decided_by: str,
               now: datetime) -> Tuple[str, ...]:
        if decision in (ReviewDecisionKind.MERGE, ReviewDecisionKind.MARK_REVISION,
                        ReviewDecisionKind.MARK_SYNDICATED) \
                and item.record_type == "article":
            return self._apply_identity(item, decision, params, decided_by, now)
        if decision is ReviewDecisionKind.LINK_ENTITY and self.enrichment is not None \
                and item.record_type == "news_item":
            entity_id = params.get("entity_id") or (
                item.candidate_values[0] if item.candidate_values else "")
            if not entity_id:
                raise ValueError("LINK_ENTITYはentity_id必須")
            dimension = ClassificationDimension(params.get("dimension", "company"))
            cls = apply_user_override(
                self.enrichment, news_item_id=item.record_id, dimension=dimension,
                value=entity_id, note=f"review:{item.review_id}", now=now)
            return (cls.classification_id,)
        if decision is ReviewDecisionKind.CLASSIFY and self.enrichment is not None:
            value = params.get("value", "")
            if not value:
                raise ValueError("CLASSIFYはvalue必須")
            dimension = ClassificationDimension(params.get("dimension", "theme"))
            cls = apply_user_override(
                self.enrichment, news_item_id=item.record_id, dimension=dimension,
                value=value, note=f"review:{item.review_id}", now=now)
            return (cls.classification_id,)
        if decision is ReviewDecisionKind.RETRACT_CLASSIFICATION \
                and self.enrichment is not None:
            target = params.get("classification_id", "")
            if not target:
                raise ValueError("RETRACT_CLASSIFICATIONはclassification_id必須")
            retract_classification(self.enrichment, classification_id=target,
                                   note=f"review:{item.review_id}", now=now)
            return (target,)
        if decision is ReviewDecisionKind.ADD_ALIAS:
            # カタログはversioned knowledge asset——コードからの自動書換えはしない。
            # decisionとして記録し、カタログ更新（version上げ）を人間タスク化する。
            return (f"catalog_change_required:{params.get('ticker', '')}",)
        # KEEP_SEPARATE / REJECT_ENTITY / DEFER: 記録のみ（状態変更なし）
        return ()

    def _apply_identity(self, item: ReviewItem, decision: ReviewDecisionKind,
                        params: Mapping[str, str], decided_by: str,
                        now: datetime) -> Tuple[str, ...]:
        if self.articles is None:
            raise ValueError("article_store未接続でidentity decisionは適用できない")
        target_article = params.get("target_article_id", "")
        if not target_article:
            raise ValueError(f"{decision.value}はtarget_article_id必須")
        if self.articles.get_identity(target_article) is None:
            raise ValueError(f"unknown target article: {target_article}")
        document_id = item.candidate_values[0] if item.candidate_values else ""
        event_type = {
            ReviewDecisionKind.MERGE: IdentityEventType.MANUAL_MERGE,
            ReviewDecisionKind.MARK_REVISION: IdentityEventType.MARK_REVISION,
            ReviewDecisionKind.MARK_SYNDICATED: IdentityEventType.MARK_SYNDICATED,
        }[decision]
        event = ArticleIdentityEvent(
            event_id=new_id("aie", now),
            event_type=event_type,
            article_id=target_article,
            created_at=now,
            document_id=document_id,
            merged_from_article_id=item.record_id
            if decision is ReviewDecisionKind.MERGE else "",
            actor=decided_by,  # user:<name> → manual優先（P2-B機構）
            note=f"review:{item.review_id}",
        )
        self.articles.append_event(event)
        return (event.event_id,)
