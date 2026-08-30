"""News Data Bankドメイン（Phase 2-A）: 分離原則・provenance必須・God object禁止。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.intelligence.core import serialization
from src.intelligence.databank.news_model import (
    ArticleIdentity,
    ClassificationDimension,
    ClassificationProvenance,
    DocumentLinkRole,
    EntityKind,
    EntityReference,
    LegacyAnnotation,
    NewsClassification,
    NewsDocumentLink,
    NewsItem,
    NewsScore,
    ScoreType,
    ThemeReference,
)

serialization.register_domain_types()
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def make_article(members=("doc_reuters", "doc_yahoo")) -> ArticleIdentity:
    return ArticleIdentity(
        article_id=ArticleIdentity.make_id("https://example.org/a1"),
        member_document_ids=tuple(members),
        canonical_url="https://example.org/a1",
        representative_title="BOJ holds rates",
        first_published_at=NOW,
        identity_basis="exact_canonical_url",
    )


def make_news(article: ArticleIdentity) -> NewsItem:
    return NewsItem(
        news_item_id=NewsItem.make_id(article.article_id),
        article_id=article.article_id,
        primary_document_id=article.member_document_ids[0],
        headline="BOJ holds rates",
        published_at=NOW,
        publisher="Reuters",
        source_id="reuters_business",
        language="en",
        canonical_url=article.canonical_url,
        guid="tag:example:a1",
        entity_refs=(EntityReference(kind=EntityKind.CENTRAL_BANK, value="BOJ"),),
        theme_refs=(ThemeReference(theme_label="金融政策"),),
    )


def test_source_document_vs_article_separation() -> None:
    """Reuters記事＋Yahoo転載＝2 SourceDocument → 1 ArticleIdentity。"""
    article = make_article()
    assert len(article.member_document_ids) == 2
    news = make_news(article)
    assert news.article_id == article.article_id
    assert news.primary_document_id in article.member_document_ids
    links = (
        NewsDocumentLink(news_item_id=news.news_item_id,
                         source_document_id="doc_reuters", role=DocumentLinkRole.PRIMARY),
        NewsDocumentLink(news_item_id=news.news_item_id,
                         source_document_id="doc_yahoo", role=DocumentLinkRole.SYNDICATED),
    )
    assert {l.role for l in links} == {DocumentLinkRole.PRIMARY, DocumentLinkRole.SYNDICATED}


def test_article_identity_deterministic_and_validated() -> None:
    a = ArticleIdentity.make_id("https://example.org/a1")
    assert a == ArticleIdentity.make_id("https://example.org/a1")
    assert a.startswith("art_")
    with pytest.raises(ValueError):
        ArticleIdentity(article_id="art_x", member_document_ids=())  # 空の束は禁止
    with pytest.raises(ValueError):
        ArticleIdentity(article_id="art_x", member_document_ids=("d",),
                        identity_basis="vibes")  # 未知basis拒否


def test_news_item_is_metadata_only_no_god_object() -> None:
    """NewsItemは分類・スコアのフィールドを持たない（別レコード強制）。"""
    field_names = set(NewsItem.__dataclass_fields__)
    # 分類・スコア系フィールドの埋め込み禁止（entity_refs/theme_refsは明示参照なので許可）
    forbidden = {"importance", "importance_score", "market_impact", "market_impact_score",
                 "theme", "themes", "sentiment", "classification", "classifications",
                 "score", "scores", "event_type", "urgency_score"}
    assert not (field_names & forbidden), field_names & forbidden


def test_classification_requires_provenance_and_versions() -> None:
    cls = NewsClassification(
        classification_id=NewsClassification.make_id("news_1", "theme", "半導体", "rule:CR_X"),
        news_item_id="news_1",
        dimension=ClassificationDimension.THEME,
        value="半導体",
        provenance=ClassificationProvenance.RULE_BASED,
        classifier_name="rule:CR_X",
        classifier_version="1.0.0",
        created_at=NOW,
    )
    assert cls.provenance is ClassificationProvenance.RULE_BASED  # valueと分離保持
    with pytest.raises(ValueError):
        NewsClassification(
            classification_id="cls_x", news_item_id="n", value="x",
            dimension=ClassificationDimension.THEME,
            provenance=ClassificationProvenance.LLM,
            classifier_name="", classifier_version="", created_at=NOW)  # 版なし拒否


def test_score_requires_decimal_and_provenance() -> None:
    score = NewsScore(
        score_id="scr_1", news_item_id="news_1", score_type=ScoreType.IMPORTANCE,
        value=Decimal("0.8"), provenance=ClassificationProvenance.USER,
        scorer_name="user_manual", scorer_version="1", created_at=NOW)
    assert isinstance(score.value, Decimal)
    with pytest.raises(TypeError):
        NewsScore(score_id="scr_2", news_item_id="n", score_type=ScoreType.IMPORTANCE,
                  value=0.8, provenance=ClassificationProvenance.USER,  # type: ignore
                  scorer_name="u", scorer_version="1", created_at=NOW)


def test_speculative_llm_entity_tagging_rejected_in_p2a() -> None:
    with pytest.raises(ValueError):
        EntityReference(kind=EntityKind.COMPANY, value="トヨタ",
                        provenance=ClassificationProvenance.LLM)


def test_legacy_annotation_quarantines_tank_interpreted_fields() -> None:
    tank_article = {
        "article_id": "art_x", "title_original": "t",
        "importance_score": 0.9, "themes": ["ai_semiconductor"],
        "sentiment": "negative", "event_type": "policy",
        "canonical_url": "https://e.org/x",
    }
    ann = LegacyAnnotation.from_tank_article(tank_article, target_record_id="doc_x")
    keys = dict(ann.annotations)
    assert keys["importance_score"] == "0.9"
    assert "ai_semiconductor" in keys["themes"]
    assert ann.origin == "tank"
    assert "not ground truth" in ann.note  # 新Truthにしない宣言がレコード自身に残る


def test_serialization_roundtrip_all_news_types() -> None:
    article = make_article()
    news = make_news(article)
    link = NewsDocumentLink(news_item_id=news.news_item_id, source_document_id="doc_reuters")
    for obj in (article, news, link):
        assert serialization.decode(serialization.encode(obj)) == obj
    decoded = serialization.decode(serialization.encode(news))
    assert decoded.entity_refs[0].kind is EntityKind.CENTRAL_BANK
    assert decoded.theme_refs[0].theme_label == "金融政策"
