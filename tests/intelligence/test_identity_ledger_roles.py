"""P2-F: identity decision ledger＋revision/syndication role精緻化のテスト。"""
from __future__ import annotations

from datetime import timedelta

from src.intelligence.core.ids import new_id
from src.intelligence.core.types import SourceTier
from src.intelligence.databank.article_store import (
    ArticleIdentityEvent,
    IdentityEventType,
    JsonlArticleStore,
)
from src.intelligence.review.identity_ledger import (
    IdentityLedgerEntry,
    JsonlIdentityLedger,
    backfill_candidate_ledger,
    record_live_decision,
)
from src.intelligence.review.revision_roles import (
    JsonlRevisionRoleStore,
    RevisionRole,
    classify_revision_roles,
)
from src.intelligence.sources.model import SourceDocument

from .enrichment_fixtures import NOW


def _doc(doc_id: str, title: str, url: str, source_id: str,
         fingerprint: str) -> SourceDocument:
    return SourceDocument(
        source_document_id=doc_id, source_id=source_id, source_tier=SourceTier.TIER2,
        title=title, locator=url, canonical_locator=url,
        retrieved_at=NOW, published_at=NOW - timedelta(hours=2),
        content_hash="h" * 64, content_fingerprint=fingerprint,
        normalizer_name="tank_article", normalizer_version="1.0.0")


class TestIdentityLedger:
    def test_backfill_candidate_ledger_migration_safe(self, tmp_path):
        articles = JsonlArticleStore(tmp_path / "articles")
        doc_a = _doc("doc_aaaa0000000000000000", "FERC Information Collection OMB No.1",
                     "https://x.gov/a", "us_federal_register", "fp_a")
        doc_b = _doc("doc_bbbb0000000000000000", "FERC Information Collection OMB No.2",
                     "https://x.gov/b", "us_federal_register", "fp_b")
        for article_id, doc, kind in (("art_a0000000000000000000", doc_a, "distinct"),
                                      ("art_b0000000000000000000", doc_b, "candidate")):
            articles.append_event(ArticleIdentityEvent(
                event_id=new_id("aie", NOW), event_type=IdentityEventType.CREATE,
                article_id=article_id, created_at=NOW,
                document_id=doc.source_document_id,
                identity_basis="exact_canonical_url", actor="algorithm:1.0.0",
                decision_kind=kind))
        events_before = len(list(articles.iter_events()))

        ledger = JsonlIdentityLedger(tmp_path / "articles")
        added = backfill_candidate_ledger(ledger, articles, [doc_a, doc_b], now=NOW)
        assert added == 1  # candidateのみ
        entry = list(ledger.iter_entries())[0]
        assert entry.derivation == "post_hoc_full_corpus"  # 元runtime判定の主張ではない
        assert entry.original_decision_kind == "candidate"
        assert entry.decision.algorithm_version  # signals/confidence付き完全判定
        assert entry.decision.matched_signals or entry.decision.failed_signals \
            or entry.decision.reason_codes
        # migration-safe: article eventsは1件も増えていない（再identityしない）
        assert len(list(articles.iter_events())) == events_before
        # 冪等
        assert backfill_candidate_ledger(ledger, articles, [doc_a, doc_b], now=NOW) == 0

    def test_live_decision_recording(self, tmp_path):
        from decimal import Decimal
        from src.intelligence.databank.identity_decision import (
            IdentityDecision, IdentityDecisionKind)
        ledger = JsonlIdentityLedger(tmp_path / "articles")
        decision = IdentityDecision(
            decision=IdentityDecisionKind.DISTINCT, document_id="doc_x",
            confidence=Decimal("0"), algorithm_version="1.0.0",
            reason_codes=("no_candidates",))
        assert record_live_decision(ledger, decision, article_id="art_x", now=NOW)
        entry = ledger.entries_for_document("doc_x")[0]
        assert entry.derivation == "live"

    def test_roundtrip(self, tmp_path):
        from src.intelligence.core import serialization
        serialization.register_domain_types()
        ledger = JsonlIdentityLedger(tmp_path / "articles")
        from decimal import Decimal
        from src.intelligence.databank.identity_decision import (
            IdentityDecision, IdentityDecisionKind)
        decision = IdentityDecision(
            decision=IdentityDecisionKind.CANDIDATE, document_id="doc_y",
            matched_article_id="art_z", confidence=Decimal("0.55"),
            matched_signals=("title_similarity_high",),
            failed_signals=("numeric_token_mismatch",),
            algorithm_version="1.0.0")
        record_live_decision(ledger, decision, article_id="art_y", now=NOW)
        reopened = JsonlIdentityLedger(tmp_path / "articles")
        entry = reopened.entries_for_document("doc_y")[0]
        assert entry.decision == decision  # nested dataclass roundtrip


class TestRevisionRoles:
    def _events(self, articles: JsonlArticleStore, revision_doc: str):
        articles.append_event(ArticleIdentityEvent(
            event_id=new_id("aie", NOW), event_type=IdentityEventType.CREATE,
            article_id="art_r0000000000000000000", created_at=NOW,
            document_id="doc_old00000000000000000",
            identity_basis="exact_canonical_url", actor="algorithm:1.0.0",
            decision_kind="distinct"))
        articles.append_event(ArticleIdentityEvent(
            event_id=new_id("aie", NOW), event_type=IdentityEventType.MARK_REVISION,
            article_id="art_r0000000000000000000", created_at=NOW,
            document_id=revision_doc, actor="algorithm:1.0.0",
            decision_kind="revision", note="same_canonical_url,different_fingerprint"))

    def test_same_publisher_update(self, tmp_path):
        articles = JsonlArticleStore(tmp_path / "a")
        self._events(articles, "doc_new00000000000000000")
        docs = {
            "doc_old00000000000000000": _doc("doc_old00000000000000000", "Jobs and taxes",
                                             "https://bbc.co.uk/news/1", "bbc_business", "f1"),
            "doc_new00000000000000000": _doc("doc_new00000000000000000", "Jobs, borrowing and taxes",
                                             "https://bbc.co.uk/news/1", "bbc_business", "f2"),
        }
        records = classify_revision_roles(articles, docs, now=NOW)
        assert records[0].role is RevisionRole.SAME_PUBLISHER_UPDATE
        assert "same_source_feed" in records[0].basis

    def test_cross_feed_same_article(self, tmp_path):
        articles = JsonlArticleStore(tmp_path / "a")
        self._events(articles, "doc_new00000000000000000")
        docs = {
            "doc_old00000000000000000": _doc("doc_old00000000000000000", "Story",
                                             "https://bbc.co.uk/news/1", "bbc_business", "f1"),
            "doc_new00000000000000000": _doc("doc_new00000000000000000", "Story v2",
                                             "https://bbc.co.uk/news/1", "bbc_scienv", "f2"),
        }
        records = classify_revision_roles(articles, docs, now=NOW)
        assert records[0].role is RevisionRole.CROSS_FEED_SAME_ARTICLE
        assert "same_canonical_url" in records[0].basis
        assert "same_publisher_domain" in records[0].basis

    def test_unprovable_stays_unknown(self, tmp_path):
        # DO NOT GUESS: URL不一致×別feedは証明不能→UNKNOWN
        articles = JsonlArticleStore(tmp_path / "a")
        self._events(articles, "doc_new00000000000000000")
        docs = {
            "doc_old00000000000000000": _doc("doc_old00000000000000000", "Story",
                                             "https://a.com/1", "feed_a", "f1"),
            "doc_new00000000000000000": _doc("doc_new00000000000000000", "Story",
                                             "https://b.com/2", "feed_b", "f2"),
        }
        records = classify_revision_roles(articles, docs, now=NOW)
        assert records[0].role is RevisionRole.UNKNOWN
        assert "relation_unprovable" in records[0].basis

    def test_store_idempotent(self, tmp_path):
        articles = JsonlArticleStore(tmp_path / "a")
        self._events(articles, "doc_new00000000000000000")
        docs = {}
        store = JsonlRevisionRoleStore(tmp_path / "a")
        records = classify_revision_roles(articles, docs, now=NOW)
        assert store.add(records[0]) is True
        assert store.add(records[0]) is False
        reopened = JsonlRevisionRoleStore(tmp_path / "a")
        assert len(list(reopened.iter_records())) == 1
