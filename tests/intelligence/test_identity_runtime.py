"""Identity runtime（Phase 2-B）: ingest→Article→NewsItem接続・primary選定・validation。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.intelligence.core.types import SourceTier
from src.intelligence.databank.article_store import JsonlArticleStore
from src.intelligence.databank.identity_decision import IdentityDecisionKind
from src.intelligence.databank.identity_runtime import IdentityRuntime, select_primary
from src.intelligence.databank.news_model import DocumentLinkRole
from src.intelligence.databank.validation import validate_data_bank
from tests.intelligence.test_identity_resolver import make_doc

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def make_runtime(tmp_path: Path) -> IdentityRuntime:
    return IdentityRuntime(JsonlArticleStore(tmp_path), clock=lambda: NOW)


def test_ingest_distinct_creates_article(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    doc = make_doc("doc_1", title="BOJ holds rates", summary="s", url="https://e.org/a")
    result = runtime.ingest_document(doc)
    assert result.decision.decision is IdentityDecisionKind.DISTINCT
    assert result.article is not None
    assert result.article.member_document_ids == ("doc_1",)


def test_syndication_flow_to_news_item(tmp_path: Path) -> None:
    """Reuters原文＋Yahoo転載 → 同一Article＋role=SYNDICATED＋NewsItem。"""
    runtime = make_runtime(tmp_path)
    original = make_doc("doc_reuters", title="Dollar firms as traders trim bets",
                        summary="The dollar rose against major peers.",
                        url="https://reuters.example/fx", source="reuters_business",
                        published=NOW - timedelta(hours=3))
    relay = make_doc("doc_yahoo", title="Dollar firms as traders trim bets",
                     summary="The dollar rose against major peers.",
                     url="https://yahoo.example/fx", source="yahoo_jp_reuters",
                     published=NOW - timedelta(hours=2))
    r1 = runtime.ingest_document(original)
    r2 = runtime.ingest_document(relay)
    assert r2.decision.decision is IdentityDecisionKind.SYNDICATED
    assert r2.article.article_id == r1.article.article_id
    assert set(r2.article.member_document_ids) == {"doc_reuters", "doc_yahoo"}

    news, links = runtime.build_news_item(r2.article)
    assert news.article_id == r1.article.article_id
    assert news.primary_document_id == "doc_reuters"  # 原文（非転載・先行公開）がprimary
    assert news.headline == "Dollar firms as traders trim bets"
    roles = {l.source_document_id: l.role for l in links}
    assert roles["doc_reuters"] is DocumentLinkRole.PRIMARY
    assert roles["doc_yahoo"] is DocumentLinkRole.SYNDICATED
    # NewsItem IDはarticle IDから導出されるが別名前空間（news_ prefix）
    assert news.news_item_id.startswith("news_") and news.article_id.startswith("art_")


def test_revision_flow(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    v1 = make_doc("doc_v1", title="BOJ raises rates", summary="details to follow",
                  url="https://e.org/hike", published=NOW - timedelta(hours=5))
    v2 = make_doc("doc_v2", title="BOJ raises rates, first hike since January",
                  summary="full details and reaction", url="https://e.org/hike",
                  published=NOW - timedelta(hours=4))
    runtime.ingest_document(v1)
    r2 = runtime.ingest_document(v2)
    assert r2.decision.decision is IdentityDecisionKind.REVISION
    assert set(r2.article.member_document_ids) == {"doc_v1", "doc_v2"}


def test_candidate_never_merges_creates_new_article(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    a = make_doc("doc_a", title="Market wrap: stocks close higher",
                 summary="Tech led the gains.", url="https://e.org/w1")
    b = make_doc("doc_b", title="Market wrap: stocks close higher",
                 summary="Energy led the gains.", url="https://e.org/w2")
    runtime.ingest_document(a)
    r = runtime.ingest_document(b)
    assert r.decision.decision is IdentityDecisionKind.CANDIDATE
    assert r.article.member_document_ids == ("doc_b",)  # mergeせず新Article


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    doc = make_doc("doc_1", title="T", summary="s", url="https://e.org/a")
    first = runtime.ingest_document(doc)
    again = runtime.ingest_document(doc)
    assert again.article.article_id == first.article.article_id
    assert again.article.member_document_ids == ("doc_1",)


def test_primary_selection_rule_and_basis() -> None:
    early_t2 = make_doc("doc_early", title="T", summary="s", url="https://e.org/1",
                        published=NOW - timedelta(hours=10))
    late_t1 = make_doc("doc_late", title="T", summary="s", url="https://e.org/2",
                       published=NOW - timedelta(hours=1))
    object.__setattr__(late_t1, "source_tier", SourceTier.TIER1)
    # 「Tierが高い=原文」とは限らない: 先行公開が優先される
    primary, basis = select_primary([late_t1, early_t2])
    assert primary == "doc_early"
    assert "earliest_published" in basis
    # 転載は原文に劣後
    primary2, _ = select_primary([early_t2, late_t1],
                                 syndicated_ids=frozenset({"doc_early"}))
    assert primary2 == "doc_late"


def test_news_layer_validation_via_runtime(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    doc = make_doc("doc_1", title="BOJ holds rates", summary="s", url="https://e.org/a")
    result = runtime.ingest_document(doc)
    news, links = runtime.build_news_item(result.article)
    issues = validate_data_bank(
        documents=(doc,), news_items=(news,),
        article_identities=(result.article,), document_links=links)
    assert issues == ()
    # orphan NewsItem: 参照するarticleが存在しない場合は検出される
    from src.intelligence.databank.news_model import NewsItem

    orphan = NewsItem(
        news_item_id="news_ghost", article_id="art_ghost",
        primary_document_id=doc.source_document_id, headline="ghost")
    ghost_issues = validate_data_bank(
        documents=(doc,), news_items=(orphan,), article_identities=(result.article,))
    assert any(i.code == "orphan_reference" and "art_ghost" in i.detail
               for i in ghost_issues)
