"""Data Bank validation gate＋query契約＋SQLite索引（Phase 2-A）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.core.contracts import NewsRepository
from src.intelligence.databank.news_model import (
    ArticleIdentity,
    ClassificationDimension,
    ClassificationProvenance,
    NewsClassification,
    NewsItem,
)
from src.intelligence.databank.query import NewsQuery, NewsQueryable
from src.intelligence.databank.sqlite_index import SqliteNewsIndex
from src.intelligence.databank.validation import validate_data_bank
from src.intelligence.market.model import Observation, ObservationKind
from tests.intelligence.qa_fixtures import REF, make_doc, make_source_info
from src.intelligence.evidence_qa.assess import assess_source_document
from src.intelligence.evidence_qa.policy import GENERIC_V1

NOW = REF


def make_news(news_id: str = "news_1", article_id: str = "art_1",
              doc_id: str = "doc_tier1_fresh", **kw) -> NewsItem:
    defaults = dict(
        news_item_id=news_id, article_id=article_id, primary_document_id=doc_id,
        headline="BOJ holds rates", published_at=NOW - timedelta(hours=6),
        publisher="BOJ", source_id="boj_whatsnew", language="en",
        canonical_url="https://example.jp/a1", guid="g1")
    defaults.update(kw)
    return NewsItem(**defaults)


# ---------------------------------------------------------------- validation gate


def test_validation_passes_consistent_bank() -> None:
    doc = make_doc()
    article = ArticleIdentity(article_id="art_1",
                              member_document_ids=(doc.source_document_id,))
    news = make_news(doc_id=doc.source_document_id)
    issues = validate_data_bank(documents=(doc,), news_items=(news,),
                                article_identities=(article,))
    assert issues == ()


def test_validation_detects_duplicate_and_orphan() -> None:
    doc = make_doc()
    issues = validate_data_bank(
        documents=(doc, doc),  # duplicate id
        news_items=(make_news(doc_id="doc_missing"),),  # orphan primary doc
        article_identities=(ArticleIdentity(
            article_id="art_1", member_document_ids=("doc_ghost",)),),  # orphan member
    )
    codes = [i.code for i in issues]
    assert codes.count("duplicate_id") == 1
    assert codes.count("orphan_reference") >= 2


def test_validation_detects_broken_revision_and_bad_decimal() -> None:
    doc = make_doc(revision_of="doc_nonexistent")
    obs = Observation(observation_id="obs_nan", entity_id="x", metric="m",
                      value=Decimal("NaN"), unit="pct", as_of=NOW,
                      kind=ObservationKind.RAW, source_id="s")
    issues = validate_data_bank(documents=(doc,), observations=(obs,))
    codes = {i.code for i in issues}
    assert "broken_revision_relation" in codes
    assert "invalid_decimal" in codes


def test_validation_requires_qa_when_enabled() -> None:
    doc = make_doc()
    without = validate_data_bank(documents=(doc,), require_qa=True)
    assert any(i.code == "qa_result_missing" for i in without)
    assessment = assess_source_document(doc, source_info=make_source_info(),
                                        policy=GENERIC_V1, reference_time=NOW)
    with_qa = validate_data_bank(documents=(doc,), assessments=(assessment,),
                                 require_qa=True)
    assert not any(i.code == "qa_result_missing" for i in with_qa)


# ---------------------------------------------------------------- query / sqlite索引


@pytest.fixture()
def index(tmp_path: Path) -> SqliteNewsIndex:
    idx = SqliteNewsIndex(tmp_path / "index.sqlite3")
    yield idx
    idx.close()


def test_sqlite_index_satisfies_query_contract(index: SqliteNewsIndex) -> None:
    assert isinstance(index, NewsQueryable)
    assert isinstance(index, NewsRepository) is False  # 索引は検索専用（追加契約は別）


def test_search_by_date_publisher_source(index: SqliteNewsIndex) -> None:
    old = make_news("news_old", "art_o", published_at=NOW - timedelta(days=40))
    fresh = make_news("news_fresh", "art_f")
    other = make_news("news_other", "art_x", publisher="Reuters",
                      source_id="reuters_business")
    index.index_news_items([old, fresh, other])
    got = index.search_news(NewsQuery(date_from=NOW - timedelta(days=7)))
    assert {n.news_item_id for n in got} == {"news_fresh", "news_other"}
    got = index.search_news(NewsQuery(publisher="BOJ"))
    assert {n.news_item_id for n in got} == {"news_old", "news_fresh"}
    got = index.search_news(NewsQuery(source_id="reuters_business"))
    assert [n.news_item_id for n in got] == ["news_other"]


def test_search_by_classification_and_trust(index: SqliteNewsIndex) -> None:
    doc = make_doc()
    news = make_news(doc_id=doc.source_document_id)
    index.index_news_items([news])
    index.index_classifications([NewsClassification(
        classification_id="cls_1", news_item_id=news.news_item_id,
        dimension=ClassificationDimension.THEME, value="金融政策",
        provenance=ClassificationProvenance.RULE_BASED,
        classifier_name="rule:test", classifier_version="1", created_at=NOW)])
    assessment = assess_source_document(doc, source_info=make_source_info(),
                                        policy=GENERIC_V1, reference_time=NOW)
    index.index_assessments([assessment])

    assert [n.news_item_id for n in
            index.search_news(NewsQuery(theme="金融政策"))] == [news.news_item_id]
    assert index.search_news(NewsQuery(theme="半導体")) == []
    got = index.search_news(NewsQuery(trust_decisions=("accept",)))
    assert [n.news_item_id for n in got] == [news.news_item_id]
    assert index.search_news(NewsQuery(trust_decisions=("reject",))) == []


def test_index_is_rebuildable_derived_artifact(index: SqliteNewsIndex) -> None:
    news = make_news()
    index.index_news_items([news])
    index.rebuild()  # 全消去
    assert index.search_news(NewsQuery()) == []
    index.index_news_items([news])  # 正本から再構築
    assert len(index.search_news(NewsQuery())) == 1


def test_news_query_validates_inputs() -> None:
    with pytest.raises(ValueError):
        NewsQuery(date_from=datetime(2026, 8, 1))  # naive拒否
    with pytest.raises(ValueError):
        NewsQuery(limit=0)
