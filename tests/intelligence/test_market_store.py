"""PART A/I: canonical store・SQLite index・latest semanticsのテスト。"""
from __future__ import annotations

from decimal import Decimal

from src.intelligence.market.ingest import build_observations
from src.intelligence.market.store import MarketBankStore

from .market_fixtures import NIKKEI_CSV, fetch_result_from_csv, spec_for

NIKKEI = "index:nikkei225.close.closing.tokyo"


def _loaded_store(tmp_path) -> MarketBankStore:
    store = MarketBankStore(tmp_path / "market")
    spec = spec_for(NIKKEI)
    outcome = build_observations(spec, fetch_result_from_csv(spec, NIKKEI_CSV))
    store.add_observations(outcome.observations)
    return store


class TestCanonicalStore:
    def test_add_idempotent(self, tmp_path):
        store = _loaded_store(tmp_path)
        spec = spec_for(NIKKEI)
        outcome = build_observations(spec, fetch_result_from_csv(spec, NIKKEI_CSV))
        assert store.add_observations(outcome.observations) == 0  # 二重追記しない

    def test_reopen_from_jsonl(self, tmp_path):
        store = _loaded_store(tmp_path)
        store.close()
        reopened = MarketBankStore(tmp_path / "market")
        assert sum(1 for _ in reopened.normalized.iter_observations()) == 5
        assert reopened.current_by_date(NIKKEI)["2026-08-28"].value == Decimal("39310.25")

    def test_raw_csv_blob_preserved(self, tmp_path):
        store = MarketBankStore(tmp_path / "market")
        spec = spec_for(NIKKEI)
        result = fetch_result_from_csv(spec, NIKKEI_CSV)
        attempt_id, raw_item_id = store.record_provider_fetch(result, "fetch_TEST")
        assert attempt_id == "fetch_TEST" and raw_item_id
        item = store.raw.get_raw_item(raw_item_id)
        assert store.raw.read_body(item) == NIKKEI_CSV  # 生CSVがそのまま読み戻せる
        attempts = list(store.raw.iter_attempts())
        assert attempts[0].content_hash == item.content_hash

    def test_failed_fetch_still_recorded(self, tmp_path):
        store = MarketBankStore(tmp_path / "market")
        spec = spec_for(NIKKEI)
        result = fetch_result_from_csv(spec, NIKKEI_CSV)
        failed = type(result)(**{**result.__dict__, "status_code": 404,
                                 "error_kind": "http_error", "error_detail": "HTTP 404",
                                 "records": ()})
        _attempt_id, raw_item_id = store.record_provider_fetch(failed, "fetch_FAIL")
        assert raw_item_id is None  # RawItemは作らない
        assert list(store.raw.iter_attempts())[0].status_code == 404  # 試行は必ず記録


class TestSqliteIndexQueries:
    def test_query_filters(self, tmp_path):
        store = _loaded_store(tmp_path)
        rows = store.index.query(series_id=NIKKEI, date_from="2026-08-25",
                                 date_to="2026-08-27")
        assert [r["trading_date"] for r in rows] == \
            ["2026-08-25", "2026-08-26", "2026-08-27"]
        assert store.index.query(source_id="stooq") and not store.index.query(source_id="x")
        assert store.index.query(kind="derived") == []

    def test_value_stored_as_text_not_float(self, tmp_path):
        store = _loaded_store(tmp_path)
        row = store.index.latest_trading_session(NIKKEI)
        assert row["value"] == "39310.25" and isinstance(row["value"], str)

    def test_rebuild_from_canonical_matches(self, tmp_path):
        store = _loaded_store(tmp_path)
        before = store.index.count_by_series()
        obs_count, _ = store.index.rebuild(store.normalized.iter_observations())
        assert obs_count == 5 and store.index.count_by_series() == before


class TestLatestSemantics:
    def _with_revision(self, tmp_path) -> MarketBankStore:
        store = _loaded_store(tmp_path)
        spec = spec_for(NIKKEI)
        revised = build_observations(
            spec, fetch_result_from_csv(spec, b"Date,Close\n2026-08-28,39999.99\n"),
            existing_by_date=store.current_by_date(NIKKEI))
        store.add_observations(revised.observations)
        return store

    def test_latest_trading_session_resolves_revisions(self, tmp_path):
        store = self._with_revision(tmp_path)
        row = store.index.latest_trading_session(NIKKEI)
        assert row["trading_date"] == "2026-08-28"
        assert row["value"] == "39999.99"  # 最新改定版（旧値ではない）

    def test_old_value_preserved_in_chain(self, tmp_path):
        store = self._with_revision(tmp_path)
        chain = store.index.revision_chain(NIKKEI, "2026-08-28")
        assert [r["value"] for r in chain] == ["39310.25", "39999.99"]
        assert chain[1]["revision_of"] == chain[0]["observation_id"]
        # current_only=Falseなら旧値もクエリで見える（消えていない）
        all_rows = store.index.query(series_id=NIKKEI, current_only=False)
        assert len(all_rows) == 6

    def test_latest_revision_for_specific_date(self, tmp_path):
        store = self._with_revision(tmp_path)
        row = store.index.latest_revision_for(NIKKEI, "2026-08-28")
        assert row["value"] == "39999.99"
        assert store.index.latest_revision_for(NIKKEI, "2026-08-27")["value"] == "39250.00"

    def test_latest_as_of_distinct_semantics(self, tmp_path):
        store = self._with_revision(tmp_path)
        by_session = store.index.latest_trading_session(NIKKEI)
        by_as_of = store.index.latest_as_of(NIKKEI)
        # 本系列では一致する（別クエリとして明示提供されることが要点）
        assert by_session["observation_id"] == by_as_of["observation_id"]

    def test_query_default_hides_superseded(self, tmp_path):
        store = self._with_revision(tmp_path)
        current = store.index.query(series_id=NIKKEI)
        assert len(current) == 5  # 5セッション（改定解決済み）
        assert "39310.25" not in [r["value"] for r in current]
