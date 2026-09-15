"""P2-G公式ソースprovider（Treasury / MOF / J-Quants）のオフラインテスト。

fixtureはlive probe（run #6）で実測した応答フォーマットに基づく（値は架空）。
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.market.ingest import as_of_for, build_observations
from src.intelligence.market.jquants_topix import JQuantsTopixProvider
from src.intelligence.market.mof_jgb import (
    MofJgbYieldProvider,
    parse_mof_jgbcm_csv,
    wareki_to_iso,
)
from src.intelligence.market.series_catalog import load_catalog
from src.intelligence.market.treasury_curve import (
    TreasuryParYieldProvider,
    parse_treasury_par_yield_csv,
)

from .market_fixtures import StubTransport

CATALOG = load_catalog(Path("knowledge/market_series/core_series.yaml"))

#: probe実測ヘッダ（run #6）＋架空値。行は実応答同様newest-first
TREASURY_2026_CSV = (
    'Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr",'
    '"5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
    "01/06/2026,3.84,3.83,3.86,3.90,3.94,4.02,4.15,4.34,4.41,4.48,4.59,4.73,5.21,5.22\n"
    "01/05/2026,3.81,3.79,3.81,3.84,3.88,3.94,4.04,4.30,4.38,4.45,4.56,4.70,5.18,5.19\n"
    "01/02/2026,3.72,3.71,3.66,3.65,3.62,3.58,3.47,,3.55,3.74,3.95,4.19,4.81,4.86\n"
).encode()

TREASURY_2025_CSV = (
    'Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr",'
    '"5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
    "12/31/2025,3.74,3.75,3.67,3.67,3.63,3.59,3.48,3.47,3.55,3.73,3.94,4.18,4.79,4.84\n"
    "12/30/2025,3.65,3.71,3.65,3.65,3.63,3.59,3.47,3.46,3.54,3.72,3.93,4.17,4.78,4.83\n"
).encode()

#: probe実測構造（タイトル行→ヘッダ→和暦データ行→注記行）＋架空値・cp932
MOF_ALL_CSV = (
    "国債金利情報,,,,,,,,,,,,,,,(単位 : %)\n"
    "基準日,1年,2年,3年,4年,5年,6年,7年,8年,9年,10年,15年,20年,25年,30年,40年\n"
    "S49.9.24,10.327,9.362,8.83,8.515,8.348,8.29,8.24,8.121,8.127,-,-,-,-,-,-\n"
    "R8.7.30,1.243,1.497,1.638,1.862,2.033,2.192,2.345,2.521,2.661,2.801,3.376,3.68,3.973,3.971,3.967\n"
    "R8.7.31,1.255,1.507,1.658,1.876,2.044,2.19,2.343,2.517,2.658,2.801,3.382,3.69,3.987,3.982,3.967\n"
).encode("cp932")

MOF_CURRENT_CSV = (
    "国債金利情報 (令和8年8月),,,,,,,,,,,,,,,(単位 : %)\n"
    "基準日,1年,2年,3年,4年,5年,6年,7年,8年,9年,10年,15年,20年,25年,30年,40年\n"
    "R8.7.31,1.255,1.507,1.658,1.876,2.044,2.19,2.343,2.517,2.658,2.801,3.382,3.69,3.987,3.982,3.967\n"
    "R8.8.3,1.287,1.562,1.714,1.933,2.1,2.241,2.389,2.554,2.689,2.824,3.402,3.695,3.994,3.982,3.948\n"
    "※最新のcsvデータがダウンロードできない場合はキャッシュを削除してください,,,,,,,,,,,,,,,\n"
).encode("cp932")


def spec(series_id: str):
    s = CATALOG.get(series_id)
    assert s is not None, series_id
    return s


# =====================================================================
# Treasury（Daily Treasury Par Yield Curve Rates）
# =====================================================================

class TestTreasuryParser:
    def test_column_pick_and_date_conversion(self):
        records, issues = parse_treasury_par_yield_csv(TREASURY_2026_CSV, "2 Yr")
        by_date = {r.trading_date: r.close for r in records}
        assert by_date["2026-01-06"] == "4.34"
        assert by_date["2026-01-05"] == "4.30"
        assert by_date["2026-01-02"] == ""  # 空欄トークン=欠測（埋めない）
        assert not issues

    def test_10yr_column_is_distinct(self):
        records, _ = parse_treasury_par_yield_csv(TREASURY_2026_CSV, "10 Yr")
        assert {r.trading_date: r.close for r in records}["2026-01-06"] == "4.73"

    def test_concatenated_year_files_with_repeated_header(self):
        body = TREASURY_2025_CSV + b"\n" + TREASURY_2026_CSV
        records, issues = parse_treasury_par_yield_csv(body, "2 Yr")
        days = sorted(r.trading_date for r in records)
        assert days[0] == "2025-12-30" and days[-1] == "2026-01-06"
        assert len(records) == 5
        assert not issues

    def test_missing_column_reports_issue(self):
        records, issues = parse_treasury_par_yield_csv(TREASURY_2026_CSV, "50 Yr")
        assert records == ()
        assert any("missing_column" in i for i in issues)

    def test_html_body_rejected(self):
        records, issues = parse_treasury_par_yield_csv(
            b"<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD></HTML>", "2 Yr")
        assert records == ()
        assert issues[0] == "missing_header_row"


class TestTreasuryProvider:
    def _provider(self):
        transport = StubTransport({
            "field_tdr_date_value=2025": (200, TREASURY_2025_CSV),
            "field_tdr_date_value=2026": (200, TREASURY_2026_CSV),
        })
        return TreasuryParYieldProvider(transport), transport

    def test_multi_year_fetch_with_disclosure(self):
        provider, transport = self._provider()
        result = provider.fetch_daily_history(
            spec("rates:UST2Y_par.yield.closing.us"),
            start=date(2025, 12, 30), end=date(2026, 1, 6))
        assert result.ok
        assert len(transport.requests) == 2  # 年ファイルごとに1リクエスト
        assert "concatenated_year_files:2025,2026" in result.parse_issues
        assert {r.trading_date for r in result.records} == {
            "2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06"}
        # bodyは受信payloadの連結そのまま（raw保存対象）
        assert TREASURY_2025_CSV in result.body and TREASURY_2026_CSV in result.body

    def test_range_filter_single_year(self):
        provider, transport = self._provider()
        result = provider.fetch_daily_history(
            spec("rates:UST2Y_par.yield.closing.us"),
            start=date(2026, 1, 1), end=date(2026, 1, 31))
        assert len(transport.requests) == 1
        assert {r.trading_date for r in result.records} == {
            "2026-01-02", "2026-01-05", "2026-01-06"}
        assert "concatenated_year_files" not in ";".join(result.parse_issues)

    def test_http_error_is_reported(self):
        transport = StubTransport({"field_tdr_date_value": (403, b"Access Denied")})
        provider = TreasuryParYieldProvider(transport)
        result = provider.fetch_daily_history(
            spec("rates:UST2Y_par.yield.closing.us"),
            start=date(2026, 1, 1), end=date(2026, 1, 31))
        assert result.error_kind == "http_error"
        assert not result.ok


# =====================================================================
# MOF（財務省 国債金利情報）
# =====================================================================

class TestWareki:
    @pytest.mark.parametrize("token,expected", [
        ("S49.9.24", "1974-09-24"),
        ("H31.4.30", "2019-04-30"),
        ("R1.5.1", "2019-05-01"),
        ("R8.8.3", "2026-08-03"),
    ])
    def test_conversion(self, token, expected):
        assert wareki_to_iso(token) == expected

    @pytest.mark.parametrize("token", ["", "X9.1.1", "R8.13.1", "2026-08-03", "R8/8/3"])
    def test_invalid_raises(self, token):
        with pytest.raises(ValueError):
            wareki_to_iso(token)


class TestMofParser:
    def test_structure_rows_skipped_and_column_picked(self):
        records, issues = parse_mof_jgbcm_csv(MOF_CURRENT_CSV, "10年")
        by_date = {r.trading_date: r.close for r in records}
        assert by_date == {"2026-07-31": "2.801", "2026-08-03": "2.824"}
        assert not issues  # タイトル・注記行はissueにしない（構造行）

    def test_missing_token_dash(self):
        records, _ = parse_mof_jgbcm_csv(MOF_ALL_CSV, "10年")
        assert {r.trading_date: r.close for r in records}["1974-09-24"] == ""

    def test_concatenated_all_plus_current_dedup(self):
        body = MOF_ALL_CSV + b"\n" + MOF_CURRENT_CSV
        records, issues = parse_mof_jgbcm_csv(body, "10年")
        days = [r.trading_date for r in records]
        assert days.count("2026-07-31") == 1  # 両ファイルに載る月末日は初出優先
        assert "duplicate_date_across_files:2026-07-31" in issues
        assert "2026-08-03" in days and "1974-09-24" in days

    def test_missing_column(self):
        records, issues = parse_mof_jgbcm_csv(MOF_ALL_CSV, "50年")
        assert records == ()
        assert any("missing_column" in i for i in issues)


class TestMofProvider:
    def test_two_file_fetch_with_disclosure_and_range(self):
        transport = StubTransport({
            "jgbcm_all.csv": (200, MOF_ALL_CSV),
            "interest_rate/jgbcm.csv": (200, MOF_CURRENT_CSV),
        })
        provider = MofJgbYieldProvider(transport)
        result = provider.fetch_daily_history(
            spec("rates:JGB10Y.yield.closing.tokyo"),
            start=date(2026, 7, 1), end=date(2026, 8, 31))
        assert result.ok
        assert len(transport.requests) == 2
        assert "concatenated_files:jgbcm_all+jgbcm_current" in result.parse_issues
        assert {r.trading_date for r in result.records} == {
            "2026-07-30", "2026-07-31", "2026-08-03"}  # 期間filter（1974年行は範囲外）

    def test_http_error(self):
        transport = StubTransport({"jgbcm": (404, b"not found")})
        provider = MofJgbYieldProvider(transport)
        result = provider.fetch_daily_history(
            spec("rates:JGB10Y.yield.closing.tokyo"),
            start=date(2026, 7, 1), end=date(2026, 8, 31))
        assert result.error_kind == "http_error"


# =====================================================================
# J-Quants（TOPIX）
# =====================================================================

def _jquants_http(pages):
    """auth 2段階＋ページングを再現するstub http_fn。"""
    calls = []

    def http_fn(url, method, headers, payload):
        calls.append((url, method, dict(headers), payload))
        if url.endswith("/token/auth_user"):
            body = json.loads(payload)
            assert body["mailaddress"] == "user@example.com"
            return 200, json.dumps({"refreshToken": "REFRESH"}).encode()
        if "/token/auth_refresh" in url:
            assert "refreshtoken=REFRESH" in url
            return 200, json.dumps({"idToken": "IDTOKEN"}).encode()
        assert headers.get("Authorization") == "Bearer IDTOKEN"
        for key, page in pages.items():
            if (key == "" and "pagination_key" not in url) or (
                    key and f"pagination_key={key}" in url):
                return 200, json.dumps(page).encode()
        raise AssertionError(f"unexpected url {url}")

    return http_fn, calls


class TestJQuantsProvider:
    ENV = {"JQUANTS_MAIL": "user@example.com", "JQUANTS_PASSWORD": "pw"}

    def test_no_credentials_is_honest_gap(self):
        provider = JQuantsTopixProvider(env={})
        result = provider.fetch_daily_history(
            spec("index:topix.close.closing.tokyo"),
            start=date(2026, 8, 1), end=date(2026, 8, 28))
        assert result.error_kind == "no_credentials"
        assert not result.ok

    def test_fetch_with_pagination_and_string_tokens(self):
        http_fn, calls = _jquants_http({
            "": {"topix": [
                {"Date": "2026-08-27", "Open": 2750.1, "High": 2760.0,
                 "Low": 2740.5, "Close": 2755.55}],
                "pagination_key": "K2"},
            "K2": {"topix": [
                {"Date": "2026-08-28", "Open": 2756.0, "High": 2765.4,
                 "Low": 2750.0, "Close": 2760.05}]},
        })
        provider = JQuantsTopixProvider(http_fn, env=self.ENV)
        result = provider.fetch_daily_history(
            spec("index:topix.close.closing.tokyo"),
            start=date(2026, 8, 1), end=date(2026, 8, 28))
        assert result.ok
        # parse_float=str: floatを経由せずJSONの数値表記そのまま
        tokens = {r.trading_date: r.close for r in result.records}
        assert tokens == {"2026-08-27": "2755.55", "2026-08-28": "2760.05"}
        assert "paginated_response:2pages" in result.parse_issues
        assert result.media_type == "application/json"
        # 永続化されるlocatorへtoken/pagination_keyを含めない
        assert "token" not in result.url and "pagination_key" not in result.url
        # bodyは両ページのraw JSONを保持
        assert result.body.count(b'"topix"') == 2

    def test_auth_http_error(self):
        def http_fn(url, method, headers, payload):
            return 403, b'{"message":"Forbidden"}'
        provider = JQuantsTopixProvider(http_fn, env=self.ENV)
        result = provider.fetch_daily_history(
            spec("index:topix.close.closing.tokyo"),
            start=date(2026, 8, 1), end=date(2026, 8, 28))
        assert result.error_kind == "auth_error"


# =====================================================================
# identity / catalog（official vs proxyの区別・概念整合）
# =====================================================================

class TestSeriesIdentity:
    def test_no_proxy_substitution_in_catalog(self):
        topix = spec("index:topix.close.closing.tokyo")
        # ETF（1306等）・先物symbolを指数seriesに持たない
        assert all("1306" not in sym and ".T" not in sym
                   for _, sym in topix.provider_symbols)
        jgb = spec("rates:JGB10Y.yield.closing.tokyo")
        assert jgb.preferred_source == "mof_japan"
        assert jgb.symbol_for("stooq") is None  # 概念の異なる旧経路は除外済み

    def test_official_par_series_is_separate_from_market_yield(self):
        old = spec("rates:UST2Y.yield.closing.us")
        par = spec("rates:UST2Y_par.yield.closing.us")
        assert old.series.instrument_id != par.series.instrument_id
        assert not old.enabled and par.enabled
        # 既存^TNX series（市場実勢）は削除・上書きされない
        tnx = spec("rates:UST10Y.yield.closing.us")
        assert tnx.enabled and tnx.symbol_for("yfinance") == "^TNX"
        par10 = spec("rates:UST10Y_par.yield.closing.us")
        assert par10.series.instrument_id == "rates:UST10Y_par"

    def test_spread_concept_consistency(self):
        spread = next(c for c in CATALOG.cross_series_derivations
                      if "spread" in c.series_id)
        # official par同士のみ（^TNX×official parの混合spreadは存在しない）
        assert set(spread.inputs) == {"rates:UST10Y_par.yield.closing.us",
                                      "rates:UST2Y_par.yield.closing.us"}
        assert spread.unit == "pct_point"

    def test_official_providers_registered_tier1(self):
        for pid in ("treasury_gov", "mof_japan", "jquants"):
            info = CATALOG.providers[pid]
            assert info.source_type == "PRIMARY_OFFICIAL"
            assert info.tier == 1

    def test_units(self):
        assert spec("index:topix.close.closing.tokyo").unit == "index"
        assert spec("rates:JGB10Y.yield.closing.tokyo").unit == "pct"
        assert spec("rates:UST2Y_par.yield.closing.us").unit == "pct"


class TestDateSemantics:
    def test_jgb_as_of_is_1500_jst(self):
        as_of = as_of_for(spec("rates:JGB10Y.yield.closing.tokyo"), "2026-08-03")
        assert as_of.isoformat() == "2026-08-03T06:00:00+00:00"  # 15:00 JST

    def test_treasury_as_of_follows_us_dst(self):
        s = spec("rates:UST2Y_par.yield.closing.us")
        assert as_of_for(s, "2026-08-28").isoformat() == "2026-08-28T19:30:00+00:00"  # EDT
        assert as_of_for(s, "2026-01-06").isoformat() == "2026-01-06T20:30:00+00:00"  # EST

    def test_decimal_from_string_token(self):
        provider = TreasuryParYieldProvider(StubTransport({
            "field_tdr_date_value=2026": (200, TREASURY_2026_CSV)}))
        result = provider.fetch_daily_history(
            spec("rates:UST2Y_par.yield.closing.us"),
            start=date(2026, 1, 1), end=date(2026, 1, 31))
        outcome = build_observations(spec("rates:UST2Y_par.yield.closing.us"), result)
        values = {o.trading_date: o.value for o in outcome.observations}
        assert values["2026-01-06"] == Decimal("4.34")
        assert values["2026-01-02"] is None  # 欠測は欠測のまま
        assert all(o.unit == "pct" for o in outcome.observations)


# =====================================================================
# engine統合（gap系列のfull pipeline・派生・冪等・revision・QA）
# =====================================================================

from src.intelligence.evidence_qa.policy import MARKET_OBSERVATION_V1  # noqa: E402
from src.intelligence.market.backfill import MarketBackfillEngine  # noqa: E402
from src.intelligence.market.store import MarketBankStore  # noqa: E402

GAP_SERIES = ("rates:UST2Y_par.yield.closing.us",
              "rates:UST10Y_par.yield.closing.us",
              "rates:JGB10Y.yield.closing.tokyo",
              "index:topix.close.closing.tokyo")


def _gap_engine(tmp_path, *, policy=MARKET_OBSERVATION_V1,
                treasury_csv=TREASURY_2026_CSV):
    http_fn, _calls = _jquants_http({
        "": {"topix": [
            {"Date": "2026-01-05", "Open": 2700.0, "High": 2712.0,
             "Low": 2695.0, "Close": 2710.25},
            {"Date": "2026-01-06", "Open": 2711.0, "High": 2722.5,
             "Low": 2705.0, "Close": 2720.5}]},
    })
    mof_csv = (
        "国債金利情報,,,,,,,,,,,,,,,(単位 : %)\n"
        "基準日,1年,2年,3年,4年,5年,6年,7年,8年,9年,10年,15年,20年,25年,30年,40年\n"
        "R8.1.5,0.9,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.75,1.8,2.2,2.5,2.7,2.8,2.9\n"
        "R8.1.6,0.91,1.11,1.21,1.31,1.41,1.51,1.61,1.71,1.76,1.81,2.21,2.51,2.71,2.81,2.91\n"
    ).encode("cp932")
    providers = {
        "treasury_gov": TreasuryParYieldProvider(StubTransport({
            "field_tdr_date_value=2026": (200, treasury_csv)})),
        "mof_japan": MofJgbYieldProvider(StubTransport({
            "jgbcm_all.csv": (200, mof_csv),
            "interest_rate/jgbcm.csv": (200, mof_csv)})),
        "jquants": JQuantsTopixProvider(
            http_fn, env={"JQUANTS_MAIL": "user@example.com",
                          "JQUANTS_PASSWORD": "pw"}),
    }
    return MarketBackfillEngine(MarketBankStore(tmp_path / "market"), CATALOG,
                                providers, policy)


class TestGapSeriesPipeline:
    def test_full_run_success_with_official_spread(self, tmp_path):
        engine = _gap_engine(tmp_path)
        run = engine.run(start=date(2026, 1, 1), end=date(2026, 1, 31),
                         series_ids=GAP_SERIES)
        by_id = {r.series_id: r for r in run.results}
        assert run.series_failed == 0
        assert by_id["rates:UST2Y_par.yield.closing.us"].status == "success"
        assert by_id["rates:UST10Y_par.yield.closing.us"].status == "success"
        assert by_id["rates:JGB10Y.yield.closing.tokyo"].status == "success"
        assert by_id["index:topix.close.closing.tokyo"].status == "success"
        # official par同士のspread（1/5: 4.70-4.30=0.40 / 1/6: 4.73-4.34=0.39）
        spread = [o for o in engine.store.normalized.iter_observations()
                  if o.series_id == "rates:UST10Y_par_UST2Y_par.spread.derived_metric"]
        values = {o.trading_date: str(o.value) for o in spread}
        assert values["2026-01-05"] == "0.400000"
        assert values["2026-01-06"] == "0.390000"
        assert all(len(o.inputs) == 2 and o.calculation_method == "yield_spread:1.0.0"
                   for o in spread)  # calculation provenance必須

    def test_qa_accepts_with_provider_trace(self, tmp_path):
        engine = _gap_engine(tmp_path)
        engine.run(start=date(2026, 1, 1), end=date(2026, 1, 31),
                   series_ids=GAP_SERIES, with_derivations=False)
        obs_by_id = {o.observation_id: o
                     for o in engine.store.normalized.iter_observations()}
        for a in engine.store.qa.iter_assessments():
            codes = [i.code for i in a.issues]
            if obs_by_id[a.record_id].value is None:
                # 欠測値観測は正直にwarning（埋めない・捏造しない）
                assert a.decision.value == "accept_with_warnings"
                assert codes == ["value_missing"]
            else:
                # provider trace検証済み→missing_supporting_evidence_ref無しでACCEPT
                assert a.decision.value == "accept", (a.record_id, codes)
                assert "missing_supporting_evidence_ref" not in codes

    def test_idempotent_rerun(self, tmp_path):
        engine = _gap_engine(tmp_path)
        first = engine.run(start=date(2026, 1, 1), end=date(2026, 1, 31),
                           series_ids=GAP_SERIES)
        second = engine.run(start=date(2026, 1, 1), end=date(2026, 1, 31),
                            series_ids=GAP_SERIES)
        assert first.observations_added > 0
        assert second.observations_added == 0
        assert second.derived_added == 0

    def test_revision_on_changed_official_value(self, tmp_path):
        engine = _gap_engine(tmp_path)
        engine.run(start=date(2026, 1, 1), end=date(2026, 1, 31),
                   series_ids=("rates:UST2Y_par.yield.closing.us",),
                   with_derivations=False)
        revised = TREASURY_2026_CSV.replace(b"4.34", b"4.35")
        engine2 = _gap_engine(tmp_path, treasury_csv=revised)
        run = engine2.run(start=date(2026, 1, 1), end=date(2026, 1, 31),
                          series_ids=("rates:UST2Y_par.yield.closing.us",),
                          with_derivations=False)
        result = run.results[0]
        assert result.revisions == 1  # 旧値は消さず新Observation＋revision_of
