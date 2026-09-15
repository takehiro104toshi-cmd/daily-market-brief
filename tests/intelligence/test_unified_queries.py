"""P2-F: unified query layer（News複合・Market複合・時系列formal）のテスト。"""
from __future__ import annotations

from datetime import date, datetime, timezone

from src.intelligence.databank.news_model import ClassificationDimension
from src.intelligence.databank.query import MarketQuery, NewsQuery
from src.intelligence.databank.sqlite_index import SqliteNewsIndex
from src.intelligence.enrichment.backfill import EnrichmentBackfillEngine
from src.intelligence.enrichment.override import apply_user_override
from src.intelligence.evidence_qa.policy import HISTORICAL_V1
from src.intelligence.market.backfill import MarketBackfillEngine
from src.intelligence.market.store import MarketBankStore
from src.intelligence.review.intake import intake_enrichment_queue
from src.intelligence.review.store import JsonlReviewStore

from .enrichment_fixtures import NOW, make_engine, make_item
from .market_fixtures import NIKKEI_CSV, RETRIEVED, UST10Y_CSV, catalog, stub_provider

HEADLINES = [
    "Fed holds rates steady as Powell cites inflation risks",
    "Nvidia earnings beat estimates as AI chip demand surges",
    "Apple falls from tree in Somerset orchard",
]


def _news_setup(tmp_path):
    engine = make_engine(tmp_path)
    items = [make_item(h) for h in HEADLINES]
    index = SqliteNewsIndex(tmp_path / "news.sqlite3")
    index.index_news_items(items)
    for item in items:
        engine.enrich_item(item, now=NOW)
    index.index_classifications(list(engine.store.iter_classifications()))
    return engine, items, index


class TestNewsCompoundQuery:
    def test_entity_cross_dimension_filter(self, tmp_path):
        _engine, _items, index = _news_setup(tmp_path)
        got = index.search_news(NewsQuery(entity="central_bank:fed"))
        assert [n.headline for n in got] == [HEADLINES[0]]

    def test_provenance_filter(self, tmp_path):
        engine, items, index = _news_setup(tmp_path)
        apple = items[2]
        apply_user_override(engine.store, news_item_id=apple.news_item_id,
                            dimension=ClassificationDimension.COMPANY,
                            value="company:apple", now=NOW)
        index.index_classifications(list(engine.store.iter_classifications()))
        got = index.search_news(NewsQuery(classification_provenance="user"))
        assert [n.news_item_id for n in got] == [apple.news_item_id]

    def test_review_status_filter(self, tmp_path):
        engine, items, index = _news_setup(tmp_path)
        reviews = JsonlReviewStore(tmp_path / "review")
        intake_enrichment_queue(reviews, engine.store.iter_review_queue(), now=NOW)
        index.index_review_items(list(reviews.iter_items()))
        got = index.search_news(NewsQuery(review_status="open"))
        assert [n.headline for n in got] == [HEADLINES[2]]  # Apple曖昧aliasの記事

    def test_compound_conditions(self, tmp_path):
        _engine, _items, index = _news_setup(tmp_path)
        got = index.search_news(NewsQuery(
            theme="ai", event_type="EARNINGS", company="company:nvidia",
            language="en",
            date_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 7, 31, tzinfo=timezone.utc)))
        assert [n.headline for n in got] == [HEADLINES[1]]


class TestMarketCompoundQuery:
    def _market(self, tmp_path) -> MarketBankStore:
        store = MarketBankStore(tmp_path / "market")
        engine = MarketBackfillEngine(
            store, catalog(),
            stub_provider({"s=^nkx": (200, NIKKEI_CSV), "s=10usy.b": (200, UST10Y_CSV)}),
            HISTORICAL_V1)
        engine.run(start=date(2026, 8, 1), end=date(2026, 8, 29), now=RETRIEVED,
                   series_ids=("index:nikkei225.close.closing.tokyo",
                               "rates:UST10Y.yield.closing.us"))
        return store

    def test_series_and_trading_date_range(self, tmp_path):
        store = self._market(tmp_path)
        rows = store.index.search_market(MarketQuery(
            series_id="index:nikkei225.close.closing.tokyo",
            trading_date_from="2026-08-25", trading_date_to="2026-08-27"))
        assert [r["trading_date"] for r in rows] == \
            ["2026-08-25", "2026-08-26", "2026-08-27"]

    def test_source_decision_kind_filters(self, tmp_path):
        store = self._market(tmp_path)
        rows = store.index.search_market(MarketQuery(
            source_id="stooq", kinds=("raw",),
            qa_decision="accept_with_warnings"))
        assert len(rows) == 10  # 2系列×5営業日
        assert store.index.search_market(MarketQuery(source_id="ghost")) == []

    def test_latest_session_only(self, tmp_path):
        store = self._market(tmp_path)
        rows = store.index.search_market(MarketQuery(kinds=("raw",),
                                                     latest_session_only=True))
        by_series = {r["series_id"]: r["trading_date"] for r in rows}
        assert by_series == {
            "index:nikkei225.close.closing.tokyo": "2026-08-28",
            "rates:UST10Y.yield.closing.us": "2026-08-28"}

    def test_instrument_prefix_and_metric(self, tmp_path):
        store = self._market(tmp_path)
        rows = store.index.search_market(MarketQuery(
            instrument_id="rates:UST10Y", metric="yield", kinds=("raw",)))
        assert len(rows) == 5

    def test_revision_current_vs_all(self, tmp_path):
        from src.intelligence.market.ingest import build_observations
        from .market_fixtures import fetch_result_from_csv, spec_for
        store = self._market(tmp_path)
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        revised = build_observations(
            spec, fetch_result_from_csv(spec, b"Date,Close\n2026-08-28,39999.99\n"),
            existing_by_date=store.current_by_date(spec.series_id))
        store.add_observations(revised.observations)
        current = store.index.search_market(MarketQuery(
            series_id=spec.series_id, kinds=("raw",), current_only=True))
        every = store.index.search_market(MarketQuery(
            series_id=spec.series_id, kinds=("raw",), current_only=False))
        assert len(every) == len(current) + 1  # 旧revisionは消えない


class TestTemporalFormalQueries:
    def test_theme_and_publisher_counts(self, tmp_path):
        _engine, _items, index = _news_setup(tmp_path)
        theme_rows = index.count_by_dimension_over_time("theme", granularity="month")
        assert ("2026-07", "ai", 1) in theme_rows
        pub_rows = index.count_publishers_over_time(granularity="month")
        assert ("2026-07", "Test Wire", 3) in pub_rows
        # 数値集計のみ（trend claim・分析文を返すAPIは存在しない）
        assert not hasattr(index, "detect_trend")
        assert not hasattr(index, "emerging_themes")
