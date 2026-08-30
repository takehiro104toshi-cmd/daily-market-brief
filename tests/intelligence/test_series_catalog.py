"""PART B: MarketSeriesカタログとseries identity安全のテスト。"""
from __future__ import annotations

import pytest

from src.intelligence.databank.market_model import MarketSeries, ObservationType, make_series_id
from src.intelligence.market.series_catalog import derived_series_id_for

from .market_fixtures import catalog


class TestCatalogLoad:
    def test_core_series_present_and_valid(self):
        c = catalog()
        assert c.catalog_version == "1.2.0"
        enabled = {s.series_id for s in c.enabled_series()}
        # 監督者指定CORE集合（取得可能分）が全て定義されている
        for required in (
            "index:nikkei225.close.closing.tokyo",
            "index:topix.close.closing.tokyo",
            "index:dji.close.closing.us",
            "index:spx.close.closing.us",
            "index:nasdaq_composite.close.closing.us",
            "index:sox.close.closing.us",
            "index:vix.close.closing.us",
            "fx:USDJPY.rate.closing.global",
            "fx:EURUSD.rate.closing.global",
            "rates:JGB10Y.yield.closing.tokyo",
            "rates:UST2Y_par.yield.closing.us",   # P2-G: official par系列がCORE
            "rates:UST10Y_par.yield.closing.us",
            "rates:UST10Y.yield.closing.us",
            "futures:wti_cont.close.closing.us",
            "futures:gold_cont.close.closing.us",
            "crypto:BTCUSD.close.closing.global",
        ):
            assert required in enabled, required

    def test_enabled_series_have_provider_symbol(self):
        for spec in catalog().enabled_series():
            assert spec.symbol_for(spec.preferred_source), spec.series_id

    def test_growth250_is_honest_gap_not_fake(self):
        spec = catalog().get("index:growth250.close.closing.tokyo")
        assert spec is not None  # identityは定義される
        assert spec.enabled is False  # 取得元が無いものをenabledにしない
        assert spec.symbol_for("stooq") is None

    def test_asset_class_coverage_for_pilot(self):
        classes = {s.asset_class for s in catalog().enabled_series()}
        # live pilot要件: 株価指数・FX・金利・コモディティ・ボラティリティを跨ぐ
        assert {"equity_index", "fx", "rates", "commodity", "volatility"} <= classes


class TestSeriesIdentitySafety:
    def test_series_id_must_derive_from_identity(self):
        with pytest.raises(ValueError, match="series_id"):
            MarketSeries(
                series_id="index:nikkei225",  # 規約無視のID
                instrument_id="index:nikkei225", metric="close",
                observation_type=ObservationType.CLOSING, market_session="tokyo")

    def test_spot_close_and_fixing_are_distinct_series(self):
        # 同じUSDJPYでもprovider日足close / 東京仲値fixingは別series_id
        close_id = make_series_id("fx:USDJPY", "rate", "closing", "global")
        fixing_id = make_series_id("fx:USDJPY", "rate", "official_fixing", "tokyo")
        assert close_id != fixing_id

    def test_index_vs_futures_distinct_instruments(self):
        c = catalog()
        wti = c.get("futures:wti_cont.close.closing.us")
        assert wti.series.instrument_id.startswith("futures:")
        # 指数系はindex:のまま（ETF/先物と混ざらない）
        assert c.get("index:spx.close.closing.us").series.instrument_id == "index:spx"

    def test_yield_series_fixed_to_pct_unit(self):
        for spec in catalog().series:
            if spec.series.metric == "yield":
                assert spec.unit == "pct", spec.series_id

    def test_composite_vs_nasdaq100_not_conflated(self):
        c = catalog()
        composite = c.get("index:nasdaq_composite.close.closing.us")
        n100 = c.get("index:nasdaq100.close.closing.us")
        assert composite and n100
        assert composite.series.instrument_id != n100.series.instrument_id


class TestDerivations:
    def test_per_series_derived_id(self):
        spec = catalog().get("index:nikkei225.close.closing.tokyo")
        assert derived_series_id_for(spec, "return_1d") == \
            "index:nikkei225.return_1d.derived_metric.tokyo"

    def test_cross_series_inputs_exist(self):
        c = catalog()
        ids = {s.series_id for s in c.series}
        for cross in c.cross_series_derivations:
            for input_id in cross.inputs:
                assert input_id in ids

    def test_foundation_set_defined(self):
        c = catalog()
        assert {d.metric for d in c.per_series_derivations} == \
            {"return_1d", "return_5d", "ma25", "dist_25dma"}
        assert {x.calculation.split(":")[0] for x in c.cross_series_derivations} == \
            {"yield_spread", "nt_ratio"}
