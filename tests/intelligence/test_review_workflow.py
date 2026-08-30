"""P2-F: human review workflow（lifecycle・decision provenance・manual適用）のテスト。"""
from __future__ import annotations

import pytest

from src.intelligence.core.ids import content_id, new_id
from src.intelligence.databank.article_store import (
    ArticleIdentityEvent,
    IdentityEventType,
    JsonlArticleStore,
)
from src.intelligence.databank.news_model import ClassificationDimension
from src.intelligence.review.intake import (
    intake_enrichment_queue,
    intake_identity_candidates,
    intake_source_mapping,
)
from src.intelligence.review.model import (
    ReviewDecisionKind,
    ReviewItem,
    ReviewStatus,
    ReviewType,
)
from src.intelligence.review.service import ReviewService
from src.intelligence.review.store import JsonlReviewStore

from .enrichment_fixtures import NOW, make_engine, make_item


def _article_store_with_candidate(tmp_path) -> JsonlArticleStore:
    store = JsonlArticleStore(tmp_path / "articles")
    for article_id, doc_id, kind in (
        ("art_target00000000000000", "doc_target00000000000000", "distinct"),
        ("art_cand0000000000000000", "doc_cand0000000000000000", "candidate"),
    ):
        store.append_event(ArticleIdentityEvent(
            event_id=new_id("aie", NOW), event_type=IdentityEventType.CREATE,
            article_id=article_id, created_at=NOW, document_id=doc_id,
            identity_basis="exact_canonical_url", actor="algorithm:1.0.0",
            decision_kind=kind, representative_title="t"))
    return store


class TestIntake:
    def test_identity_candidates_intake_idempotent(self, tmp_path):
        articles = _article_store_with_candidate(tmp_path)
        reviews = JsonlReviewStore(tmp_path / "review")
        assert intake_identity_candidates(reviews, articles, now=NOW) == 1
        assert intake_identity_candidates(reviews, articles, now=NOW) == 0  # 冪等
        item = list(reviews.iter_items(review_type=ReviewType.IDENTITY_CANDIDATE))[0]
        assert item.status is ReviewStatus.OPEN
        assert "candidate_not_merged" in item.reason_codes

    def test_enrichment_queue_intake(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.enrich_item(make_item("Apple falls from tree in Somerset orchard"), now=NOW)
        engine.enrich_item(make_item("$ZZZZ soared today"), now=NOW)
        reviews = JsonlReviewStore(tmp_path / "review")
        added = intake_enrichment_queue(reviews, engine.store.iter_review_queue(), now=NOW)
        assert added == 2
        types = {i.review_type for i in reviews.iter_items()}
        assert types == {ReviewType.AMBIGUOUS_ALIAS, ReviewType.UNKNOWN_TICKER}

    def test_source_mapping_intake(self, tmp_path):
        reviews = JsonlReviewStore(tmp_path / "review")
        items = [make_item("headline A"), make_item("headline B")]
        items = [type(items[0])(**{**i.__dict__, "source_id": "legacy_unknown:example.com"})
                 for i in items]
        assert intake_source_mapping(reviews, items, now=NOW) == 1  # source単位で1件


class TestDecisionLifecycle:
    def _reviews_with_item(self, tmp_path, review_type=ReviewType.AMBIGUOUS_ALIAS,
                           record_id="news_x", candidates=("company:apple",)):
        reviews = JsonlReviewStore(tmp_path / "review")
        reviews.upsert_item(ReviewItem(
            review_id=ReviewItem.make_id(review_type.value, record_id, candidates[0]),
            record_id=record_id, record_type="news_item", review_type=review_type,
            candidate_values=candidates, created_at=NOW))
        return reviews

    def test_full_lifecycle_open_to_resolved(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item("Apple falls from tree in Somerset orchard")
        engine.enrich_item(item, now=NOW)
        reviews = self._reviews_with_item(tmp_path, record_id=item.news_item_id)
        service = ReviewService(reviews, enrichment_store=engine.store,
                                clock=lambda: NOW)
        review_id = list(reviews.iter_items())[0].review_id

        record = service.decide(review_id, ReviewDecisionKind.LINK_ENTITY,
                                decided_by="user:takehiro", notes="果物ではなくAAPL記事")
        # decision provenance: 誰が・いつ・何を・何に効いたか
        assert record.decided_by == "user:takehiro"
        assert record.applied_effects  # USER classificationが発行された
        updated = reviews.get_item(review_id)
        assert updated.status is ReviewStatus.APPROVED
        assert updated.resolved_by == "user:takehiro"
        # 効果: USER分類がeffective viewに現れる（manual優先）
        effective = engine.store.effective_classifications(item.news_item_id)
        assert any(c.value == "company:apple" and c.provenance.value == "user"
                   for c in effective)

    def test_decision_type_guard(self, tmp_path):
        reviews = self._reviews_with_item(tmp_path)
        service = ReviewService(reviews, clock=lambda: NOW)
        review_id = list(reviews.iter_items())[0].review_id
        with pytest.raises(ValueError, match="適用できない"):
            service.decide(review_id, ReviewDecisionKind.MERGE, decided_by="user:x")

    def test_defer_and_history_preserved(self, tmp_path):
        reviews = self._reviews_with_item(tmp_path)
        service = ReviewService(reviews, clock=lambda: NOW)
        review_id = list(reviews.iter_items())[0].review_id
        service.decide(review_id, ReviewDecisionKind.DEFER, decided_by="user:x",
                       notes="後で")
        assert reviews.get_item(review_id).status is ReviewStatus.DEFERRED
        # append-only: itemsログに旧version（OPEN）と新version（DEFERRED）が両方残る
        lines = (tmp_path / "review" / "review_items.jsonl").read_text().strip().split("\n")
        assert len(lines) == 2
        assert len(reviews.decisions_for(review_id)) == 1

    def test_manual_identity_merge_applies_user_event(self, tmp_path):
        articles = _article_store_with_candidate(tmp_path)
        reviews = JsonlReviewStore(tmp_path / "review")
        intake_identity_candidates(reviews, articles, now=NOW)
        service = ReviewService(reviews, article_store=articles, clock=lambda: NOW)
        review_id = list(reviews.iter_items())[0].review_id
        record = service.decide(
            review_id, ReviewDecisionKind.MERGE, decided_by="user:takehiro",
            params={"target_article_id": "art_target00000000000000"})
        events = list(articles.iter_events())
        manual = [e for e in events if e.event_type is IdentityEventType.MANUAL_MERGE]
        assert len(manual) == 1
        assert manual[0].is_manual  # user actor → algorithm判定より優先（P2-B機構）
        assert record.applied_effects == (manual[0].event_id,)

    def test_unknown_target_article_rejected(self, tmp_path):
        articles = _article_store_with_candidate(tmp_path)
        reviews = JsonlReviewStore(tmp_path / "review")
        intake_identity_candidates(reviews, articles, now=NOW)
        service = ReviewService(reviews, article_store=articles, clock=lambda: NOW)
        review_id = list(reviews.iter_items())[0].review_id
        with pytest.raises(ValueError, match="unknown target"):
            service.decide(review_id, ReviewDecisionKind.MERGE,
                           decided_by="user:x", params={"target_article_id": "art_ghost"})

    def test_no_delete_api(self, tmp_path):
        reviews = JsonlReviewStore(tmp_path / "review")
        assert not hasattr(reviews, "delete_item")
        assert not hasattr(reviews, "delete_decision")
