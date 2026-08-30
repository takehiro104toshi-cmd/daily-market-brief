"""P2-E: enrichment backfill（run manifest・段階実行・冪等・index・クエリ）のテスト。"""
from __future__ import annotations

from datetime import datetime, timezone

from src.intelligence.databank.backfill import JsonlNewsBankStore
from src.intelligence.databank.query import NewsQuery
from src.intelligence.databank.sqlite_index import SqliteNewsIndex
from src.intelligence.enrichment.backfill import EnrichmentBackfillEngine, corpus_fingerprint

from .enrichment_fixtures import NOW, make_engine, make_item

HEADLINES = [
    "Nvidia earnings beat estimates as AI chip demand surges",
    "日銀、利上げを見送り 円安が進行",
    "US open to diplomacy after ninth night of bombing Iran",
    "Hot tubs and £80 rosé: the festival gets a luxury makeover",  # 分類ゼロ想定
    "Toyota plans to build EV plant in India by 2030",
]


def _bank(tmp_path) -> JsonlNewsBankStore:
    bank = JsonlNewsBankStore(tmp_path / "news")
    for h in HEADLINES:
        bank.add_news_item(make_item(h))
    return bank


class TestBackfillRun:
    def test_manifest_accounting_and_versions(self, tmp_path):
        bank = _bank(tmp_path)
        engine = make_engine(tmp_path)
        run = EnrichmentBackfillEngine(bank, engine).run(now=NOW)
        assert run.records_seen == 5
        assert run.records_seen == run.records_classified + run.records_unclassified \
            + run.records_failed
        assert run.records_unclassified == 1  # festival記事（正直な未分類）
        assert run.records_failed == 0
        assert run.classifications_added == run.events_added
        assert run.corpus_fingerprint == corpus_fingerprint(list(bank.iter_news_items()))
        assert run.entity_catalog_version == "1.0.0"
        assert run.theme_taxonomy_version == "1.0.0"
        assert run.event_taxonomy_version == "1.0.0"
        assert any(v.startswith("entity_matcher:") for v in run.classifier_versions)
        assert run.llm_provider == "" and run.llm_model == ""  # LLM未使用の正直な申告
        assert list(engine.store.iter_runs())[-1].run_id == run.run_id

    def test_staged_execution_with_limit(self, tmp_path):
        bank = _bank(tmp_path)
        engine = make_engine(tmp_path)
        backfill = EnrichmentBackfillEngine(bank, engine)
        small = backfill.run(limit=2, now=NOW)
        assert small.records_seen == 2 and small.limit == 2
        full = backfill.run(now=NOW)
        assert full.records_seen == 5

    def test_idempotent_rerun(self, tmp_path):
        bank = _bank(tmp_path)
        engine = make_engine(tmp_path)
        backfill = EnrichmentBackfillEngine(bank, engine)
        first = backfill.run(now=NOW)
        assert first.classifications_added > 0
        second = backfill.run(now=NOW)
        assert second.classifications_added == 0
        assert second.events_added == 0
        assert second.review_queued == 0
        assert second.corpus_fingerprint == first.corpus_fingerprint

    def test_fingerprint_changes_with_corpus(self, tmp_path):
        bank = _bank(tmp_path)
        fp1 = corpus_fingerprint(list(bank.iter_news_items()))
        bank.add_news_item(make_item("Another headline entirely"))
        fp2 = corpus_fingerprint(list(bank.iter_news_items()))
        assert fp1 != fp2


class TestIndexAndQueries:
    def _build(self, tmp_path):
        bank = _bank(tmp_path)
        engine = make_engine(tmp_path)
        index = SqliteNewsIndex(tmp_path / "news.sqlite3")
        index.index_news_items(list(bank.iter_news_items()))
        EnrichmentBackfillEngine(bank, engine, index=index).run(now=NOW)
        return bank, engine, index

    def test_theme_query(self, tmp_path):
        _bank_, _engine, index = self._build(tmp_path)
        got = index.search_news(NewsQuery(theme="ai"))
        assert [n.headline for n in got] == [HEADLINES[0]]

    def test_company_and_theme_query(self, tmp_path):
        _bank_, _engine, index = self._build(tmp_path)
        got = index.search_news(NewsQuery(company="company:toyota", theme="india"))
        assert [n.headline for n in got] == [HEADLINES[4]]

    def test_ticker_query(self, tmp_path):
        _bank_, _engine, index = self._build(tmp_path)
        got = index.search_news(NewsQuery(ticker="NVDA"))
        assert [n.headline for n in got] == [HEADLINES[0]]

    def test_country_event_query(self, tmp_path):
        _bank_, _engine, index = self._build(tmp_path)
        got = index.search_news(NewsQuery(country="IR", event_type="GEOPOLITICS"))
        assert [n.headline for n in got] == [HEADLINES[2]]

    def test_date_and_theme_query(self, tmp_path):
        _bank_, _engine, index = self._build(tmp_path)
        got = index.search_news(NewsQuery(
            theme="fx",
            date_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 7, 31, tzinfo=timezone.utc)))
        assert [n.headline for n in got] == [HEADLINES[1]]

    def test_index_rebuild_from_canonical(self, tmp_path):
        bank, engine, index = self._build(tmp_path)
        before = index.search_news(NewsQuery(theme="ai"))
        index.rebuild()
        assert index.search_news(NewsQuery(theme="ai")) == []
        # canonical（bank＋enrichment store）から完全再構築
        index.index_news_items(list(bank.iter_news_items()))
        index.index_classifications(list(engine.store.iter_classifications()))
        after = index.search_news(NewsQuery(theme="ai"))
        assert [n.news_item_id for n in after] == [n.news_item_id for n in before]

    def test_temporal_count_foundation(self, tmp_path):
        _bank_, _engine, index = self._build(tmp_path)
        rows = index.count_by_dimension_over_time("theme", granularity="day")
        assert ("2026-07-10", "ai", 1) in rows
        counts = index.count_values("event_type")
        assert counts.get("GEOPOLITICS") == 1
        # 件数取得まで（傾向の主張・分析文はここでは生成しない）
