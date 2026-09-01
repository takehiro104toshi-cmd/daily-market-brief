"""P2-H J-Quants Light core のオフラインテスト（ネットワーク不使用）。

監督者指定の最低テスト項目を網羅する:
V2 auth regression / secret safety / pagination / rate limit handling /
security master / price schema / Decimal / trading date / price identity /
fundamental schema / earnings schedule / calendar semantics /
investor-flow temporal semantics / canonical persistence / SQLite rebuild /
query / idempotency / revision / provider neutrality / TOPIX regression /
no V1 production reachability。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.market.jquants_light_datasets import (
    ALL_DATASETS,
    AVAILABLE,
    INGESTED_DATASETS,
    MARKET_BANK_OWNED,
    NOT_ENTITLED,
    REQUIRED,
    capability_matrix,
    get_dataset,
)
from src.intelligence.market.jquants_light_store import JQuantsLightStore
from src.intelligence.market.jquants_records import (
    NORMALIZER_VERSION,
    RecordProvenance,
    parse_daily_price,
    parse_earnings_schedule,
    parse_financial_summary,
    parse_investor_type_flow,
    parse_security_master,
    parse_trading_calendar,
    security_id_for,
    to_decimal,
)
from src.intelligence.market.jquants_v2_client import (
    NOT_ENTITLED as CLIENT_NOT_ENTITLED,
    JQuantsV2Client,
)
from src.intelligence.market.tokyo_calendar import (
    DEFAULT_TRADING_DIVISIONS,
    latest_completed_session,
    trading_days,
    validate_divisions,
)

API_KEY = "TEST-ONLY-SYNTHETIC-JQUANTS-V2-KEY"
PROV = RecordProvenance(endpoint="/equities/master", retrieved_at="2026-09-01T00:00:00+00:00",
                        raw_item_id="raw_x", fetch_attempt_id="att_x")

# --- 実測（live probe run #1）に基づくfixture行 -----------------------------
MASTER_ROW = {
    "Code": "72030", "Date": "2026-09-01", "CoName": "トヨタ自動車",
    "CoNameEn": "TOYOTA MOTOR CORPORATION", "Mkt": "0111", "MktNm": "プライム",
    "S17": "6", "S17Nm": "自動車・輸送機", "S33": "3700", "S33Nm": "輸送用機器",
    "ScaleCat": "TOPIX Core30", "Mrgn": "1", "MrgnNm": "信用", "ProdCat": "1",
}
PRICE_ROW = {
    "Code": "72030", "Date": "2026-09-01", "O": "3000.5", "H": "3050", "L": "2990",
    "C": "3010.5", "Vo": "12345600", "Va": "37000000000",
    "AdjO": "1500.25", "AdjH": "1525", "AdjL": "1495", "AdjC": "1505.25",
    "AdjVo": "24691200", "AdjFactor": "0.5", "UL": "3500", "LL": "2500",
    "MktCap": "49000000000000",
}
FIN_ROW = {
    "Code": "72030", "DiscDate": "2026-08-05", "DiscTime": "15:00", "DiscNo": "20260805001",
    "DocType": "FYFinancialStatements", "CurPerType": "FY",
    "CurFYSt": "2025-04-01", "CurFYEn": "2026-03-31",
    "CurPerSt": "2025-04-01", "CurPerEn": "2026-03-31",
    "NxtFYSt": "2026-04-01", "NxtFYEn": "2027-03-31",
    "Sales": "45000000000000", "OP": "5000000000000", "OdP": "5200000000000",
    "NP": "3800000000000", "EPS": "290.5", "DEPS": "289.9", "BPS": "2500.0",
    "ROE": "12.3", "TA": "90000000000000", "Eq": "30000000000000", "EqAR": "0.33",
    "CFO": "4000000000000", "CFI": "-2000000000000", "CFF": "-1000000000000",
    "CashEq": "8000000000000",
    "FSales": "46000000000000", "FOP": "5100000000000", "FOdP": "5300000000000",
    "FNP": "3900000000000", "FEPS": "300.0",
    "NxFSales": "47000000000000", "NxFOP": "5200000000000", "NxFOdP": "5400000000000",
    "NxFNp": "4000000000000", "NxFEPS": "310.0", "RetroRst": "false",
}
EARNINGS_ROW = {"Code": "72030", "Date": "2026-11-05", "CoName": "トヨタ自動車",
                "FQ": "2", "FY": "2027", "Section": "Prime", "SectorNm": "輸送用機器"}
CALENDAR_ROWS = [
    {"Date": "2026-08-28", "HolDiv": "1"},   # 金
    {"Date": "2026-08-29", "HolDiv": "0"},   # 土
    {"Date": "2026-08-30", "HolDiv": "0"},   # 日
    {"Date": "2026-08-31", "HolDiv": "1"},   # 月
    {"Date": "2026-09-01", "HolDiv": "1"},   # 火
]
FLOW_ROW = {
    "Section": "TSEPrime", "PubDate": "2026-08-27", "StDate": "2026-08-17",
    "EnDate": "2026-08-21",
    "FrgnBuy": "1000", "FrgnSell": "900", "FrgnTot": "1900", "FrgnBal": "100",
    "IndBuy": "500", "IndSell": "600", "IndTot": "1100", "IndBal": "-100",
    "TotBuy": "1500", "TotSell": "1500", "TotTot": "3000", "TotBal": "0",
}


def _client(pages, *, status=200, body=None, calls=None):
    log = calls if calls is not None else []

    def http(url, method, headers, payload):
        log.append({"url": url, "headers": dict(headers)})
        if status != 200:
            return status, body or b'{"message":"Forbidden"}'
        for key, page in pages.items():
            if (key == "" and "pagination_key" not in url) or (
                    key and f"pagination_key={key}" in url):
                return 200, json.dumps(page).encode()
        raise AssertionError(f"unexpected url {url}")

    return JQuantsV2Client(http, env={"JQUANTS_API_KEY": API_KEY},
                           sleeper=lambda s: None), log


# ============================================================ client / auth

class TestClientAuthAndSafety:
    def test_api_key_sent_as_header_never_in_url(self):
        client, log = _client({"": {"data": [MASTER_ROW]}})
        result = client.fetch("listed_master", "/equities/master")
        assert result.ok and result.status_code == 200
        assert log[0]["headers"]["x-api-key"] == API_KEY
        assert API_KEY not in log[0]["url"]
        assert API_KEY not in result.url          # 永続化locatorに秘密が残らない

    def test_missing_credential_makes_no_network_call(self):
        calls = []
        client = JQuantsV2Client(lambda *a: calls.append(1), env={},
                                 sleeper=lambda s: None)
        result = client.fetch("listed_master", "/equities/master")
        assert result.error_kind == "no_credentials"
        assert calls == [] and client.request_count == 0

    def test_v2_base_and_api_version(self):
        client, log = _client({"": {"data": [MASTER_ROW]}})
        client.fetch("listed_master", "/equities/master", {"date": "2026-09-01"})
        assert log[0]["url"].startswith("https://api.jquants.com/v2/equities/master")
        assert "/v1/" not in log[0]["url"]
        assert client.api_version == "v2"
        assert client.provider_id == "jquants"

    def test_pagination_follows_key_and_concatenates(self):
        pages = {"": {"data": [MASTER_ROW], "pagination_key": "P2"},
                 "P2": {"data": [dict(MASTER_ROW, Code="99840")]}}
        client, log = _client(pages)
        result = client.fetch("listed_master", "/equities/master")
        assert len(log) == 2 and "pagination_key=P2" in log[1]["url"]
        assert len(result.rows) == 2 and result.pages == 2

    def test_page_limit_is_bounded(self):
        """終わらないpaginationでも上限で止まる（retry/loop stormを起こさない）。"""
        pages = {"": {"data": [MASTER_ROW], "pagination_key": ""}}

        def http(url, method, headers, payload):
            return 200, json.dumps({"data": [MASTER_ROW], "pagination_key": "X"}).encode()

        client = JQuantsV2Client(http, env={"JQUANTS_API_KEY": API_KEY},
                                 sleeper=lambda s: None)
        result = client.fetch("listed_master", "/equities/master", max_pages=3)
        assert result.pages == 3 and client.request_count == 3

    def test_plan_not_entitled_is_classified_and_returns_no_rows(self):
        body = json.dumps({"message": "This API is not available on your subscription."}).encode()
        client, _log = _client({}, status=403, body=body)
        result = client.fetch("fins_dividend", "/fins/dividend")
        assert result.entitlement == CLIENT_NOT_ENTITLED
        assert result.rows == ()               # FAIL-CLOSED: 部分成功にしない
        assert result.failure_cause == "plan_not_entitled"

    def test_schema_error_when_required_field_missing(self):
        client, _log = _client({"": {"data": [{"Code": "72030"}]}})
        result = client.fetch("daily_bars", "/equities/bars/daily",
                              required_fields=("Code", "Date", "C"))
        assert result.error_kind == "schema_error"
        assert "Date" in result.error_detail and result.rows == ()

    def test_missing_data_array_is_schema_error(self):
        client, _log = _client({"": {"topix": [{"Date": "2026-09-01"}]}})
        result = client.fetch("topix", "/indices/bars/daily/topix")
        assert result.error_kind == "schema_error"


# ============================================================ records

class TestSecurityMaster:
    def test_maps_measured_fields(self):
        rec = parse_security_master(MASTER_ROW, PROV)
        assert rec.security_id == security_id_for("72030") == "jp:security:72030"
        assert rec.code == "72030"
        assert rec.company_name == "トヨタ自動車"
        assert rec.market_name == "プライム"
        assert rec.sector33_code == "3700" and rec.sector33_name == "輸送用機器"
        assert rec.sector17_code == "6"
        assert rec.scale_category == "TOPIX Core30"
        assert rec.effective_date == "2026-09-01"
        assert rec.listing_status == "listed"

    def test_security_id_is_namespaced_not_bare_ticker(self):
        """tickerそのものをIDにしない（体系変更に耐える）。"""
        rec = parse_security_master(MASTER_ROW, PROV)
        assert rec.security_id != rec.code
        assert rec.security_id.startswith("jp:security:")

    def test_company_and_security_are_not_conflated(self):
        """security recordはcompany entityのidentityを張らない。"""
        rec = parse_security_master(MASTER_ROW, PROV)
        assert not hasattr(rec, "company_id")
        assert not hasattr(rec, "entity_id")
        assert rec.company_name          # 表示名として保持するだけ

    def test_row_without_code_is_skipped(self):
        assert parse_security_master({"CoName": "x"}, PROV) is None

    def test_provenance_is_attached(self):
        rec = parse_security_master(MASTER_ROW, PROV)
        assert rec.provenance.api_version == "v2"
        assert rec.provenance.provider == "jquants"
        assert rec.provenance.raw_item_id == "raw_x"
        assert rec.provenance.normalizer_version == NORMALIZER_VERSION


class TestPriceIdentity:
    def test_raw_and_adjusted_are_separate_fields(self):
        rec = parse_daily_price(PRICE_ROW, PROV)
        assert rec.close == "3010.5"              # 生
        assert rec.adjusted_close == "1505.25"    # 調整後
        assert rec.close != rec.adjusted_close
        assert rec.adjustment_factor == "0.5"

    def test_decimal_conversion_without_float(self):
        rec = parse_daily_price(PRICE_ROW, PROV)
        assert rec.close_decimal == Decimal("3010.5")
        assert rec.adjusted_close_decimal == Decimal("1505.25")
        assert isinstance(rec.close_decimal, Decimal)

    def test_volume_and_turnover_are_distinct(self):
        rec = parse_daily_price(PRICE_ROW, PROV)
        assert rec.volume == "12345600"
        assert rec.turnover_value == "37000000000"

    def test_trading_date_preserved_and_as_of_separate(self):
        rec = parse_daily_price(PRICE_ROW, PROV)
        assert rec.trading_date == "2026-09-01"
        assert rec.as_of == ""                    # 別概念（呼び出し側が付与）

    def test_missing_values_stay_missing(self):
        rec = parse_daily_price({"Code": "1", "Date": "2026-09-01", "C": ""}, PROV)
        assert rec.close == "" and rec.close_decimal is None   # 0で埋めない

    def test_no_total_return_field_invented(self):
        rec = parse_daily_price(PRICE_ROW, PROV)
        assert not hasattr(rec, "total_return")

    def test_to_decimal_rejects_garbage(self):
        assert to_decimal("") is None and to_decimal("n/a") is None


class TestFinancialSummary:
    def test_actual_forecast_and_next_forecast_are_separate(self):
        rec = parse_financial_summary(FIN_ROW, PROV)
        assert rec.net_sales == "45000000000000"          # 実績
        assert rec.forecast_net_sales == "46000000000000"  # 当期会社予想
        assert rec.next_forecast_net_sales == "47000000000000"  # 翌期予想
        assert len({rec.net_sales, rec.forecast_net_sales,
                    rec.next_forecast_net_sales}) == 3

    def test_fiscal_period_and_disclosure_are_distinct(self):
        rec = parse_financial_summary(FIN_ROW, PROV)
        assert rec.disclosed_date == "2026-08-05"
        assert rec.period_start == "2025-04-01" and rec.period_end == "2026-03-31"
        assert rec.fiscal_year_end == "2026-03-31"
        assert rec.next_fiscal_year_start == "2026-04-01"

    def test_revision_context_kept(self):
        rec = parse_financial_summary(FIN_ROW, PROV)
        assert rec.retrospective_restatement == "false"
        assert rec.disclosure_number == "20260805001"

    def test_record_id_uses_disclosure_number(self):
        rec = parse_financial_summary(FIN_ROW, PROV)
        assert rec.record_id == "fin_72030_20260805001"

    def test_no_score_or_recommendation_fields(self):
        """P2-Hはraw/normalizedまで。分析値を持たない。"""
        rec = parse_financial_summary(FIN_ROW, PROV)
        for banned in ("growth_score", "quality_score", "valuation_score",
                       "recommendation", "rating"):
            assert not hasattr(rec, banned)


class TestEarningsSchedule:
    def test_maps_announcement_date(self):
        rec = parse_earnings_schedule(EARNINGS_ROW, PROV)
        assert rec.announcement_date == "2026-11-05"
        assert rec.code == "72030" and rec.fiscal_quarter == "2"
        assert rec.record_id == "ern_72030_2026-11-05"


class TestTradingCalendarSemantics:
    def test_holiday_division_kept_as_source_value(self):
        rec = parse_trading_calendar(CALENDAR_ROWS[0], PROV)
        assert rec.holiday_division == "1"       # 原値のまま（意味を勝手に翻訳しない）

    def test_trading_days_filtered_by_division(self):
        days = trading_days(CALENDAR_ROWS)
        assert days == ["2026-08-28", "2026-08-31", "2026-09-01"]

    def test_validation_against_observed_dates(self):
        """観測がある日は営業日のはず、で区分の意味を実測検証する。"""
        v = validate_divisions(CALENDAR_ROWS, ["2026-08-28", "2026-08-31", "2026-09-01"])
        assert v.validated and v.checked_dates == 3 and v.agreements == 3

    def test_validation_fails_on_any_disagreement(self):
        v = validate_divisions(CALENDAR_ROWS, ["2026-08-29"])   # 土曜に観測がある想定
        assert not v.validated and v.disagreements

    def test_unvalidated_divisions_are_not_assumed(self):
        """既定の営業日区分に含まれない値を営業日扱いしない。"""
        rows = [{"Date": "2026-09-02", "HolDiv": "3"}]
        assert trading_days(rows) == []

    def test_latest_completed_session_before_close_returns_previous_day(self):
        before_close = datetime(2026, 9, 1, 9, 0)     # JST 09:00（引け前）
        assert latest_completed_session(CALENDAR_ROWS, now=before_close) == "2026-08-31"

    def test_latest_completed_session_after_close_returns_today(self):
        after_close = datetime(2026, 9, 1, 16, 0)     # JST 16:00（引け後）
        assert latest_completed_session(CALENDAR_ROWS, now=after_close) == "2026-09-01"

    def test_no_calendar_returns_none_not_a_guess(self):
        assert latest_completed_session([], now=datetime(2026, 9, 1, 16, 0)) is None


class TestInvestorFlowTemporalSemantics:
    def test_published_and_target_period_are_separate(self):
        rec = parse_investor_type_flow(FLOW_ROW, PROV)
        assert rec.published_date == "2026-08-27"       # 公表日
        assert rec.period_start == "2026-08-17"         # 対象期間
        assert rec.period_end == "2026-08-21"
        assert rec.published_date != rec.period_end

    def test_frequency_is_weekly_not_daily(self):
        rec = parse_investor_type_flow(FLOW_ROW, PROV)
        assert rec.frequency == "weekly"

    def test_investor_types_are_named_not_raw_prefixes(self):
        rec = parse_investor_type_flow(FLOW_ROW, PROV)
        assert "foreign_investors" in rec.flows
        assert rec.flows["foreign_investors"]["buy"] == "1000"
        assert rec.flows["individuals"]["balance"] == "-100"

    def test_no_analysis_fields(self):
        """「海外投資家が買っている」等の判断を持たない。"""
        rec = parse_investor_type_flow(FLOW_ROW, PROV)
        for banned in ("signal", "direction", "interpretation", "sentiment"):
            assert not hasattr(rec, banned)


# ============================================================ store / query

@pytest.fixture()
def store(tmp_path):
    s = JQuantsLightStore(tmp_path / "jquants_light")
    yield s
    s.close()


def _seed(store):
    store.append("listed_master", [parse_security_master(MASTER_ROW, PROV)])
    store.append("daily_bars", [
        parse_daily_price(dict(PRICE_ROW, Date=d), PROV)
        for d in ("2026-08-28", "2026-08-31", "2026-09-01")])
    store.append("fins_summary", [parse_financial_summary(FIN_ROW, PROV)])
    store.append("equities_earnings_cal", [parse_earnings_schedule(EARNINGS_ROW, PROV)])
    store.append("markets_calendar", [parse_trading_calendar(r, PROV) for r in CALENDAR_ROWS])
    store.append("investor_types", [parse_investor_type_flow(FLOW_ROW, PROV)])


class TestPersistenceAndQuery:
    def test_canonical_is_append_only_jsonl(self, store):
        _seed(store)
        path = store.canonical_dir / "security_master.jsonl"
        assert path.exists()
        lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
        assert lines[0]["code"] == "72030"
        assert lines[0]["provenance"]["api_version"] == "v2"

    def test_append_is_idempotent(self, store):
        _seed(store)
        before = store.count("daily_bars")
        _seed(store)                       # 同じrecordを再投入
        assert store.count("daily_bars") == before

    def test_sqlite_rebuilds_from_canonical_only(self, store):
        _seed(store)
        before = {d.key: store.count(d.key) for d in INGESTED_DATASETS}
        rebuilt = store.rebuild_index()
        after = {d.key: store.count(d.key) for d in INGESTED_DATASETS}
        assert before == after
        assert rebuilt["daily_bars"] == 3

    def test_query_security_by_code_and_name(self, store):
        _seed(store)
        assert store.security_by_code("72030")["company_name"] == "トヨタ自動車"
        assert len(store.securities_by_company_name("トヨタ")) == 1

    def test_query_price_history_and_latest(self, store):
        _seed(store)
        history = store.price_history("72030")
        assert [r["trading_date"] for r in history] == [
            "2026-08-28", "2026-08-31", "2026-09-01"]
        latest = store.latest_price("72030")
        assert latest["trading_date"] == "2026-09-01"
        assert latest["close"] and latest["adjusted_close"]
        assert latest["close"] != latest["adjusted_close"]

    def test_query_price_history_range(self, store):
        _seed(store)
        rows = store.price_history("72030", start="2026-08-31", end="2026-09-01")
        assert len(rows) == 2

    def test_query_financials_and_latest_forecast(self, store):
        _seed(store)
        assert len(store.financials_for_security("72030")) == 1
        forecast = store.latest_company_forecast("72030")
        assert forecast["forecast_net_sales"] == "46000000000000"

    def test_latest_forecast_skips_disclosure_without_forecast(self, store):
        store.append("fins_summary", [parse_financial_summary(
            dict(FIN_ROW, DiscNo="2", DiscDate="2026-09-01", FSales="", FOP="",
                 FNP="", FEPS=""), PROV)])
        store.append("fins_summary", [parse_financial_summary(FIN_ROW, PROV)])
        forecast = store.latest_company_forecast("72030")
        assert forecast["disclosed_date"] == "2026-08-05"   # 予想入りの方

    def test_query_earnings_within_range(self, store):
        _seed(store)
        assert len(store.earnings_within("2026-11-01", "2026-11-30")) == 1
        assert store.earnings_within("2026-12-01", "2026-12-31") == []

    def test_query_calendar_and_flows(self, store):
        _seed(store)
        assert len(store.calendar_range("2026-08-28", "2026-09-01")) == 5
        flows = store.investor_flows_for_period("2026-08-01", "2026-08-31")
        assert len(flows) == 1
        assert json.loads(flows[0]["flows_json"])["foreign_investors"]["buy"] == "1000"

    def test_revision_replaces_index_row_but_keeps_canonical_history(self, store):
        """同一record_idの再取り込みはindexを更新し、canonicalは履歴を失わない。"""
        _seed(store)
        revised = parse_daily_price(dict(PRICE_ROW, C="9999"), PROV)
        store._index("daily_bars", [revised])            # 索引のみ更新（revision相当）
        assert store.latest_price("72030")["close"] == "9999"
        rows = list(store.iter_canonical("daily_bars"))
        assert any(r["close"] == "3010.5" for r in rows)  # 旧値がcanonicalに残る


# ============================================================ registry / policy

class TestDatasetRegistry:
    def test_every_ingested_dataset_declares_investment_use(self):
        """用途を説明できないdatasetは採用しない（CORE PRINCIPLE）。"""
        for spec in INGESTED_DATASETS:
            assert spec.investment_use.strip(), spec.key
            assert spec.entitlement == AVAILABLE

    def test_not_entitled_datasets_are_not_ingested(self):
        ingested = {d.key for d in INGESTED_DATASETS}
        for spec in ALL_DATASETS.values():
            if spec.entitlement == NOT_ENTITLED:
                assert spec.key not in ingested, spec.key

    def test_topix_is_owned_by_market_bank_not_light_store(self):
        """TOPIXを二重保管しない（二重の真実を作らない）。"""
        assert [d.key for d in MARKET_BANK_OWNED] == ["topix"]
        assert "topix" not in {d.key for d in INGESTED_DATASETS}

    def test_capability_matrix_covers_all_datasets(self):
        matrix = capability_matrix()
        assert len(matrix) == len(ALL_DATASETS)
        for row in matrix:
            assert row["light_availability"] in (AVAILABLE, NOT_ENTITLED, "UNKNOWN")
            assert row["implementation_status"] in (
                "INGESTED_LIGHT_STORE", "INGESTED_MARKET_BANK", "NOT_IMPLEMENTED")

    def test_required_datasets_have_required_fields(self):
        for spec in INGESTED_DATASETS:
            if spec.classification == REQUIRED:
                assert spec.required_fields, spec.key

    def test_unknown_entitlement_is_not_promoted(self):
        """400（パラメータ違い）をAVAILABLE扱いしない。"""
        spec = get_dataset("fins_earnings_date")
        assert spec.entitlement == "UNKNOWN"
        assert spec.key not in {d.key for d in INGESTED_DATASETS}


class TestNoV1AndProviderNeutrality:
    def test_light_modules_do_not_import_v1(self):
        for name in ("jquants_v2_client", "jquants_light_datasets",
                     "jquants_records", "jquants_light_store",
                     "tokyo_calendar", "p2h_light_pilot"):
            text = Path(f"src/intelligence/market/{name}.py").read_text(encoding="utf-8")
            assert "jquants_topix" not in text, name
            assert "api.jquants.com/v1" not in text, name

    def test_records_are_provider_neutral_shape(self):
        """recordはprovider固有の項目名を露出しない（V2短縮名を持ち出さない）。"""
        rec = parse_daily_price(PRICE_ROW, PROV)
        for v2_only in ("AdjC", "Vo", "Va", "MktCap"):
            assert not hasattr(rec, v2_only)
