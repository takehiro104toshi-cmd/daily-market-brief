"""Market Data Bankドメイン（Phase 2-A）: series identity・観測種別の区別。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.intelligence.core import serialization
from src.intelligence.databank.market_model import (
    MarketSeries,
    ObservationType,
    make_series_id,
)
from src.intelligence.market.model import Observation, ObservationKind

serialization.register_domain_types()
NOW = datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc)


def test_same_instrument_different_sessions_are_distinct_series() -> None:
    """同じUSDJPYでもspot / Tokyo close / NY closeは別series（雑に同一視しない）。"""
    spot = make_series_id("fx:USDJPY", "rate", "intraday_quote")
    tokyo = make_series_id("fx:USDJPY", "rate", "closing", "tokyo")
    ny = make_series_id("fx:USDJPY", "rate", "closing", "ny")
    assert len({spot, tokyo, ny}) == 3


def test_series_id_must_follow_derivation_rule() -> None:
    ok = MarketSeries(
        series_id="index:nikkei225.close.closing.tokyo",
        instrument_id="index:nikkei225", metric="close",
        observation_type=ObservationType.CLOSING, market_session="tokyo",
        unit="index", currency="JPY",
        preferred_source_ids=("yahoo_finance_us_all",))
    assert ok.series_id == make_series_id("index:nikkei225", "close", "closing", "tokyo")
    with pytest.raises(ValueError):
        MarketSeries(series_id="my_custom_id", instrument_id="fx:USDJPY", metric="rate",
                     observation_type=ObservationType.CLOSING)


def test_observation_types_distinguish_quote_fixing_statistic() -> None:
    values = {t.value for t in ObservationType}
    assert {"closing", "intraday_quote", "official_fixing",
            "economic_statistic", "derived_metric"} == values


def test_observation_links_to_series_with_full_provenance() -> None:
    series_id = make_series_id("rates:JGB10Y", "yield", "closing", "tokyo")
    obs = Observation(
        observation_id="obs_x", entity_id="rates:JGB10Y", metric="yield",
        value=Decimal("1.085"), unit="pct", as_of=NOW,
        kind=ObservationKind.RAW, source_id="synthetic_market",
        calculation_method="api_field", series_id=series_id)
    assert obs.series_id == series_id
    decoded = serialization.decode(serialization.encode(obs))
    assert decoded.series_id == series_id and decoded.value == Decimal("1.085")


def test_derived_series_requires_input_provenance() -> None:
    with pytest.raises(ValueError):
        Observation(observation_id="obs_d", entity_id="index:nikkei225",
                    metric="dev_25dma", value=Decimal("2.1"), unit="pct", as_of=NOW,
                    kind=ObservationKind.DERIVED, calculation_method="ma_deviation",
                    inputs=())  # derivedはinputs必須（P1-A維持）


def test_market_series_serialization_roundtrip() -> None:
    series = MarketSeries(
        series_id=make_series_id("macro:jp_cpi", "yoy_pct", "economic_statistic"),
        instrument_id="macro:jp_cpi", metric="yoy_pct",
        observation_type=ObservationType.ECONOMIC_STATISTIC,
        unit="pct", description="全国CPI 前年比")
    assert serialization.decode(serialization.encode(series)) == series
