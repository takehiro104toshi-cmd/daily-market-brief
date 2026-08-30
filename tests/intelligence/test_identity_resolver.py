"""identity resolver（Phase 2-B）: exact規則・GUID安全・REVISION・false merge防御。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from src.intelligence.core.types import SourceTier
from src.intelligence.databank.identity_decision import IdentityDecisionKind
from src.intelligence.databank.identity_resolver import resolve
from src.intelligence.databank.identity_signals import (
    ngram_jaccard,
    numeric_tokens_differ,
    title_key,
    title_similarity,
)
from src.intelligence.databank.news_model import ArticleIdentity
from src.intelligence.ingestion.url_normalize import normalize_url
from src.intelligence.normalization.text import content_fingerprint
from src.intelligence.sources.model import SourceDocument

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def make_doc(doc_id: str, *, title: str, summary: str = "", url: str = "",
             guid: str = "", source: str = "src_a",
             published: datetime = NOW - timedelta(hours=2)) -> SourceDocument:
    basis = f"{title}|{summary}|{url}|{doc_id}"
    return SourceDocument(
        source_document_id=doc_id, source_id=source, source_tier=SourceTier.TIER2,
        title=title, locator=url or f"https://x.example/{doc_id}",
        canonical_locator=normalize_url(url) if url else "",
        retrieved_at=NOW, published_at=published, guid=guid,
        content_hash=hashlib.sha256(basis.encode()).hexdigest(),
        content_fingerprint=content_fingerprint(title, summary),
        summary=summary, normalizer_name="feed_entry", normalizer_version="1.0.0")


def article_of(*docs: SourceDocument) -> tuple:
    identity = ArticleIdentity(
        article_id=ArticleIdentity.make_id(docs[0].source_document_id),
        member_document_ids=tuple(d.source_document_id for d in docs))
    return (identity, list(docs))


# ---------------------------------------------------------------- exact stage


def test_exact_canonical_url_same_content_is_exact_match() -> None:
    a = make_doc("doc_a", title="BOJ holds rates", summary="s",
                 url="https://e.org/a?utm_source=rss")
    b = make_doc("doc_b", title="BOJ holds rates", summary="s",
                 url="https://e.org/a?utm_medium=feed")
    d = resolve(b, [article_of(a)])
    assert d.decision is IdentityDecisionKind.EXACT_MATCH
    assert "same_canonical_url" in d.matched_signals


def test_same_url_changed_content_is_revision_not_duplicate() -> None:
    a = make_doc("doc_a", title="BOJ raises rates", summary="details to follow",
                 url="https://e.org/a")
    b = make_doc("doc_b", title="BOJ raises rates, first hike since January",
                 summary="full details and market reaction", url="https://e.org/a")
    d = resolve(b, [article_of(a)])
    assert d.decision is IdentityDecisionKind.REVISION
    assert "different_fingerprint" in d.matched_signals


def test_same_guid_same_source_merges_cross_source_never() -> None:
    a = make_doc("doc_a", title="Fed statement", summary="s",
                 url="https://fed.example/1", guid="pr:104", source="fed_press")
    same = make_doc("doc_b", title="Fed statement", summary="s",
                    url="https://fed.example/2", guid="pr:104", source="fed_press")
    d = resolve(same, [article_of(a)])
    assert d.decision is IdentityDecisionKind.EXACT_MATCH
    assert "same_guid_same_source" in d.matched_signals
    # GUID安全: 別publisherの同一GUIDではmergeしない
    cross = make_doc("doc_c", title="Completely different topic entirely",
                     summary="other", url="https://other.example/9",
                     guid="pr:104", source="other_source")
    d2 = resolve(cross, [article_of(a)])
    assert d2.decision is IdentityDecisionKind.DISTINCT
    assert "guid_cross_source_ignored" in d2.failed_signals


def test_same_fingerprint_cross_publisher_is_syndicated() -> None:
    a = make_doc("doc_a", title="Dollar firms as traders trim bets",
                 summary="The dollar rose against major peers.",
                 url="https://reuters.example/fx", source="reuters_business")
    b = make_doc("doc_b", title="Dollar firms as traders trim bets",
                 summary="The dollar rose against major peers.",
                 url="https://yahoo.example/fx", source="yahoo_jp_reuters")
    d = resolve(b, [article_of(a)])
    assert d.decision is IdentityDecisionKind.SYNDICATED
    assert "same_fingerprint" in d.matched_signals


# ---------------------------------------------------------------- semantic stage


def test_light_edit_same_summary_auto_merges() -> None:
    a = make_doc("doc_a", title="BOJ holds rates steady as yen weakens past 150",
                 summary="The central bank left its target unchanged on Friday.",
                 url="https://jt.example/a", source="japan_times")
    b = make_doc("doc_b", title="BOJ holds rates steady as the yen weakens past 150",
                 summary="The central bank left its target unchanged on Friday.",
                 url="https://jt.example/b", source="japan_times",
                 published=NOW - timedelta(hours=1))
    d = resolve(b, [article_of(a)])
    assert d.decision is IdentityDecisionKind.AUTO_MERGE
    assert set(d.matched_signals) >= {"title_similarity_high", "summary_similarity_high",
                                      "published_time_close"}


def test_title_similarity_alone_never_merges() -> None:
    """定型見出しの誤結合防止: title 1.0でもsummary証拠なしではmergeしない。"""
    a = make_doc("doc_a", title="Market wrap: stocks close higher",
                 summary="Tech led the gains on upbeat earnings.", url="https://e.org/w1")
    b = make_doc("doc_b", title="Market wrap: stocks close higher",
                 summary="Energy led the gains as oil rallied.", url="https://e.org/w2")
    d = resolve(b, [article_of(a)])
    assert d.decision in (IdentityDecisionKind.CANDIDATE, IdentityDecisionKind.DISTINCT)


def test_no_summary_no_auto_merge() -> None:
    a = make_doc("doc_a", title="Exact same headline here", url="https://e.org/1")
    b = make_doc("doc_b", title="Exact same headline here", url="https://e.org/2")
    d = resolve(b, [article_of(a)])  # summaryなし→内容証拠なし→merge禁止
    assert d.decision in (IdentityDecisionKind.CANDIDATE, IdentityDecisionKind.DISTINCT)


def test_numeric_token_guard_blocks_year_and_serial_variants() -> None:
    """実データ由来ガード: 2027/2028・#1/#2型の高類似別記事を阻止。"""
    a = make_doc("doc_a", title="ECB publishes indicative operational calendars for 2027",
                 summary="The ECB published the indicative calendar for 2027.",
                 url="https://ecb.example/c27", source="ecb_press")
    b = make_doc("doc_b", title="ECB publishes indicative operational calendars for 2028",
                 summary="The ECB published the indicative calendar for 2028.",
                 url="https://ecb.example/c28", source="ecb_press",
                 published=NOW - timedelta(hours=1, minutes=55))
    assert numeric_tokens_differ(a.title, b.title)
    d = resolve(b, [article_of(a)])
    assert d.decision is not IdentityDecisionKind.AUTO_MERGE
    assert d.decision in (IdentityDecisionKind.CANDIDATE, IdentityDecisionKind.DISTINCT)


def test_japanese_near_duplicate_auto_merges() -> None:
    a = make_doc("doc_a", title="日銀、政策金利を維持　円安進行に警戒感",
                 summary="日銀は決定会合で政策金利の維持を決めた。総裁は円安に言及した。",
                 url="https://nhk.example/a", source="nhk_business")
    b = make_doc("doc_b", title="日銀 政策金利を維持、円安進行に警戒感",
                 summary="日銀は決定会合で政策金利の維持を決めた。総裁は円安に言及した。",
                 url="https://nhk.example/b", source="nhk_business",
                 published=NOW - timedelta(hours=1))
    d = resolve(b, [article_of(a)])
    assert d.decision is IdentityDecisionKind.AUTO_MERGE


def test_published_time_far_blocks_auto_merge() -> None:
    a = make_doc("doc_a", title="Quarterly outlook for chip demand strengthens",
                 summary="Analysts raised forecasts for wafer shipments.",
                 url="https://e.org/q1", published=NOW - timedelta(days=30))
    b = make_doc("doc_b", title="Quarterly outlook for chip demand strengthens",
                 summary="Analysts raised forecasts for wafer shipments.",
                 url="https://e.org/q2", published=NOW)
    # 注: fingerprint一致（同一内容）は時刻に関わらずSYNDICATED/EXACTになるため、
    # summaryを微差にしてsemantic経路で時刻条件を検証する
    b2 = make_doc("doc_b2", title="Quarterly outlook for chip demand strengthens",
                  summary="Analysts raised forecasts for wafer shipments this week.",
                  url="https://e.org/q2", published=NOW)
    d = resolve(b2, [article_of(a)])
    assert d.decision is not IdentityDecisionKind.AUTO_MERGE


# ---------------------------------------------------------------- signals単体


def test_title_key_and_similarity_work_for_ja_and_en() -> None:
    assert title_key("日銀、政策金利を維持！") == title_key("日銀 政策金利を維持")
    assert ngram_jaccard("日銀、政策金利を維持", "日銀 政策金利を維持") == 1.0
    assert title_similarity("BOJ holds rates", "BOJ holds rates") == 1.0
    assert title_similarity("BOJ holds rates", "Completely unrelated") < 0.2


def test_decision_model_requires_trace_fields() -> None:
    import pytest
    from decimal import Decimal
    from src.intelligence.databank.identity_decision import IdentityDecision

    with pytest.raises(ValueError):
        IdentityDecision(decision=IdentityDecisionKind.AUTO_MERGE, document_id="d",
                         algorithm_version="1.0.0")  # matched_article_idなし
    with pytest.raises(ValueError):
        IdentityDecision(decision=IdentityDecisionKind.DISTINCT, document_id="d",
                         algorithm_version="")  # version必須
    ok = IdentityDecision(decision=IdentityDecisionKind.DISTINCT, document_id="d",
                          algorithm_version="1.0.0", confidence=Decimal("0"))
    assert ok.confidence == Decimal("0")
