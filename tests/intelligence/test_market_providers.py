"""PART C: provider層（CSV parse・stringトークン保持・エラー分類）のテスト。"""
from __future__ import annotations

from datetime import date

from src.intelligence.market.providers import parse_stooq_daily_csv

from .market_fixtures import NIKKEI_CSV, spec_for, stub_provider


class TestParseStooqCsv:
    def test_tokens_stay_strings(self):
        records, issues = parse_stooq_daily_csv(NIKKEI_CSV)
        assert issues == ()
        assert len(records) == 5
        first = records[0]
        assert first.trading_date == "2026-08-24"
        assert first.close == "38975.55" and isinstance(first.close, str)
        assert first.volume == "1234500"

    def test_header_driven_not_positional(self):
        body = b"Close,Date\n123.45,2026-08-28\n"
        records, issues = parse_stooq_daily_csv(body)
        assert issues == ()
        assert records[0].close == "123.45"
        assert records[0].trading_date == "2026-08-28"

    def test_missing_volume_column_ok(self):
        body = b"Date,Open,High,Low,Close\n2026-08-28,1,2,0.5,1.5\n"
        records, _ = parse_stooq_daily_csv(body)
        assert records[0].close == "1.5" and records[0].volume == ""

    def test_na_token_becomes_missing_not_zero(self):
        body = b"Date,Close\n2026-08-28,N/A\n"
        records, _ = parse_stooq_daily_csv(body)
        assert records[0].close == ""  # 欠測トークンは空（0にしない）

    def test_invalid_date_line_skipped_with_issue(self):
        body = b"Date,Close\nbroken,1.5\n2026-08-28,2.5\n"
        records, issues = parse_stooq_daily_csv(body)
        assert len(records) == 1
        assert any("invalid_date" in i for i in issues)

    def test_no_data_and_empty_responses(self):
        assert parse_stooq_daily_csv(b"No data")[1] == ("no_data_response",)
        assert parse_stooq_daily_csv(b"")[1] == ("empty_body",)
        issues = parse_stooq_daily_csv(b"foo,bar\n1,2\n")[1]
        assert issues[0] == "missing_date_column"
        assert issues[1].startswith("body_head=foo,bar")  # 応答先頭の診断snippet

    def test_html_response_diagnosed(self):
        issues = parse_stooq_daily_csv(b"<html><body>limit exceeded</body></html>")[1]
        assert issues[0] == "missing_date_column"
        assert "html" in issues[1]

    def test_stooq_ua_reuses_legacy_proven_value(self):
        # LEGACY REUSE: 本番実績のあるUA（src/utils.py DEFAULT_HEADERS）と一致
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        try:
            from utils import DEFAULT_HEADERS
        finally:
            sys.path.pop(0)
        from src.intelligence.market.providers import STOOQ_USER_AGENT
        assert STOOQ_USER_AGENT == DEFAULT_HEADERS["User-Agent"]


class TestStooqProvider:
    def test_url_contains_symbol_and_range(self):
        provider = stub_provider({})
        url = provider.build_url("^nkx", date(2025, 8, 1), date(2026, 8, 29))
        assert "s=^nkx" in url and "d1=20250801" in url and "d2=20260829" in url

    def test_success_fetch(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        provider = stub_provider({"s=^nkx": (200, NIKKEI_CSV)})
        result = provider.fetch_daily_history(spec, start=date(2026, 8, 1), end=date(2026, 8, 29))
        assert result.ok and len(result.records) == 5
        assert result.body == NIKKEI_CSV  # 生CSVがそのまま保持される（blob保存用）
        assert result.provider_normalized is False
        assert result.symbol == "^nkx"

    def test_http_error_reported_not_hidden(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        provider = stub_provider({"s=^nkx": (404, b"not found")})
        result = provider.fetch_daily_history(spec, start=date(2026, 8, 1), end=date(2026, 8, 29))
        assert not result.ok and result.error_kind == "http_error"
        assert result.status_code == 404

    def test_no_data_classified_for_gap_handling(self):
        spec = spec_for("rates:JGB10Y.yield.closing.tokyo")  # probe系列
        provider = stub_provider({"s=10jpy.b": (200, b"No data")})
        result = provider.fetch_daily_history(spec, start=date(2026, 8, 1), end=date(2026, 8, 29))
        assert result.error_kind == "no_data"

    def test_transport_failure_propagates_kind(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        provider = stub_provider({})  # 応答未設定→dns
        result = provider.fetch_daily_history(spec, start=date(2026, 8, 1), end=date(2026, 8, 29))
        assert result.error_kind == "dns"

    def test_missing_symbol_is_no_symbol(self):
        spec = spec_for("index:growth250.close.closing.tokyo")
        provider = stub_provider({})
        result = provider.fetch_daily_history(spec, start=date(2026, 8, 1), end=date(2026, 8, 29))
        assert result.error_kind == "no_symbol"
