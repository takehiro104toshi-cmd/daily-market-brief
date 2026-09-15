"""既存storeからのReview対象取込（Phase 2-F・冪等）。

review_idは対象から決定論導出——再intakeは重複を作らない。
既にdecision済み（非OPEN）のitemは上書きしない（人間の判断を消さない）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..databank.article_store import IdentityEventType, JsonlArticleStore
from ..enrichment.model import ReviewQueueItem, ReviewReason
from .model import ReviewItem, ReviewType
from .store import JsonlReviewStore

#: enrichment ReviewQueueItem.reason → ReviewType
_REASON_TO_TYPE = {
    ReviewReason.AMBIGUOUS_ALIAS: ReviewType.AMBIGUOUS_ALIAS,
    ReviewReason.UNKNOWN_TICKER: ReviewType.UNKNOWN_TICKER,
    ReviewReason.LLM_UNKNOWN_LABEL: ReviewType.LLM_UNKNOWN_LABEL,
    ReviewReason.LLM_INVALID_OUTPUT: ReviewType.ENRICHMENT_UNCERTAIN,
}


def _add_if_new(store: JsonlReviewStore, item: ReviewItem) -> int:
    existing = store.get_item(item.review_id)
    if existing is not None:
        return 0  # 既存（decision済み含む）は上書きしない
    return 1 if store.upsert_item(item) else 0


def intake_identity_candidates(
    review_store: JsonlReviewStore, article_store: JsonlArticleStore, *, now: datetime
) -> int:
    """P2-B/C CANDIDATE（mergeされなかった曖昧候補）をreview対象化。"""
    added = 0
    for event in article_store.iter_events():
        if event.event_type is not IdentityEventType.CREATE or \
                event.decision_kind != "candidate":
            continue
        added += _add_if_new(review_store, ReviewItem(
            review_id=ReviewItem.make_id("identity_candidate", event.article_id,
                                         event.document_id),
            record_id=event.article_id,
            record_type="article",
            review_type=ReviewType.IDENTITY_CANDIDATE,
            reason_codes=("candidate_not_merged", event.identity_basis or "unknown_basis"),
            candidate_values=(event.document_id,),
            evidence_refs=(event.event_id, event.canonical_url or "",
                           event.representative_title or ""),
            created_at=now,
        ))
    return added


def intake_enrichment_queue(
    review_store: JsonlReviewStore, queue: Iterable[ReviewQueueItem], *, now: datetime
) -> int:
    """enrichment ReviewQueue（曖昧alias・未知ticker・LLM未知label等）を取込。"""
    added = 0
    for q in queue:
        review_type = _REASON_TO_TYPE[q.reason]
        added += _add_if_new(review_store, ReviewItem(
            review_id=ReviewItem.make_id(review_type.value, q.news_item_id,
                                         q.candidate_value),
            record_id=q.news_item_id,
            record_type="news_item",
            review_type=review_type,
            reason_codes=(q.reason.value,),
            candidate_values=(q.candidate_value,),
            evidence_refs=(q.review_id, f"{q.evidence_field}:{q.evidence_text}"[:120]),
            created_at=now,
        ))
    return added


def intake_source_mapping(
    review_store: JsonlReviewStore, news_items, *, now: datetime
) -> int:
    """legacy source未対応（LEGACY_UNKNOWN_SOURCE——P2-C安全表現）をreview対象化。"""
    added = 0
    seen = set()
    for item in news_items:
        if not item.source_id.startswith("legacy_unknown:"):
            continue
        if item.source_id in seen:
            continue
        seen.add(item.source_id)
        added += _add_if_new(review_store, ReviewItem(
            review_id=ReviewItem.make_id("source_mapping", item.source_id),
            record_id=item.source_id,
            record_type="source",
            review_type=ReviewType.SOURCE_MAPPING,
            reason_codes=("legacy_unknown_source",),
            candidate_values=(),
            evidence_refs=(item.news_item_id,),
            created_at=now,
        ))
    return added
