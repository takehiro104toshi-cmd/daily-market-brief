"""派生観測のprovenance/同日結合ガード（PROJECT-WIDE RETROACTIVE AUDIT）。

live pilot run #15 の実測形（TOPIXが2026-09-01まで、基準の日経平均は
2026-08-31まで）を固定する。**片側だけ新しい日付があるとき、直近値を
forward-fillしてNT倍率を作ってはならない**（捏造の禁止）。

既存テストは「左（日経）が新しく右（TOPIX）が欠ける」向きを扱っていたため、
実測で起きた**逆向き**（右が新しい）をここで固定する。
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from src.intelligence.market.derived import derive_cross_series
from src.intelligence.market.ingest import as_of_for
from src.intelligence.market.model import Observation, ObservationKind
from src.intelligence.market.series_catalog import load_catalog

CATALOG = load_catalog(Path("knowledge/market_series/core_series.yaml"))
NIKKEI = "index:nikkei225.close.closing.tokyo"
TOPIX = "index:topix.close.closing.tokyo"
NT_SERIES = "index:nikkei225_topix.nt_ratio.derived_metric"


def _cross():
    for cross in CATALOG.cross_series_derivations:
        if cross.series_id == NT_SERIES:
            return cross
    raise AssertionError("NT倍率のcross derivationがカタログに無い")


def _sessions(count: int, *, end: date):
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def _obs(series_id: str, day: date, value: str, tag: str):
    spec = CATALOG.get(series_id)
    return Observation(
        observation_id=f"obs_{tag}_{day.isoformat()}",
        entity_id=spec.series.instrument_id, metric=spec.series.metric,
        value=Decimal(value), unit=spec.unit,
        as_of=as_of_for(spec, day.isoformat()), kind=ObservationKind.RAW,
        series_id=series_id, trading_date=day.isoformat(), source_id="test")


class TestNtRatioSameDateOnly:
    def test_extra_topix_session_does_not_forward_fill_nikkei(self):
        """TOPIXだけ1営業日新しいとき、その日のNT倍率を生成しない（run #15形）。"""
        days = _sessions(5, end=date(2026, 9, 1))
        nikkei = [_obs(NIKKEI, d, "39000", "nk") for d in days[:-1]]   # 〜08-31
        topix = [_obs(TOPIX, d, "2700", "tp") for d in days]           # 〜09-01

        out = derive_cross_series(_cross(), nikkei, topix)
        produced = {o.trading_date for o in out}

        assert days[-1].isoformat() not in produced, "片側欠落日を捏造している"
        assert produced == {d.isoformat() for d in days[:-1]}

    def test_extra_nikkei_session_does_not_forward_fill_topix(self):
        """逆向き（日経だけ新しい）でも同様に生成しない。"""
        days = _sessions(5, end=date(2026, 9, 1))
        nikkei = [_obs(NIKKEI, d, "39000", "nk") for d in days]
        topix = [_obs(TOPIX, d, "2700", "tp") for d in days[:-1]]

        produced = {o.trading_date for o in derive_cross_series(_cross(), nikkei, topix)}
        assert days[-1].isoformat() not in produced

    def test_provenance_is_complete_on_every_derived_row(self):
        """全派生行が入力2件のobservation_idとcalculation_method/versionを保持。"""
        days = _sessions(4, end=date(2026, 9, 1))
        nikkei = [_obs(NIKKEI, d, "39000", "nk") for d in days]
        topix = [_obs(TOPIX, d, "2700", "tp") for d in days]

        out = derive_cross_series(_cross(), nikkei, topix)
        assert out
        for row in out:
            assert len(row.inputs) == 2
            assert row.inputs[0].startswith("obs_nk_")
            assert row.inputs[1].startswith("obs_tp_")
            assert row.calculation_method == "nt_ratio:1.0.0"
            assert ":" in row.calculation_method      # name:version 形式
            assert row.unit == "x"
            assert isinstance(row.value, Decimal)
            assert row.kind == ObservationKind.DERIVED

    def test_value_is_decimal_quotient_not_float(self):
        day = date(2026, 9, 1)
        out = derive_cross_series(
            _cross(), [_obs(NIKKEI, day, "39000.10", "nk")],
            [_obs(TOPIX, day, "2700.20", "tp")])
        assert len(out) == 1
        expected = (Decimal("39000.10") / Decimal("2700.20")).quantize(Decimal("0.000001"))
        assert out[0].value == expected

    def test_zero_denominator_is_skipped_not_infinite(self):
        day = date(2026, 9, 1)
        out = derive_cross_series(
            _cross(), [_obs(NIKKEI, day, "39000", "nk")],
            [_obs(TOPIX, day, "0", "tp")])
        assert out == ()

    def test_missing_value_rows_are_excluded(self):
        """値がNoneの観測は結合対象にしない（欠測を0扱いしない）。"""
        day = date(2026, 9, 1)
        spec = CATALOG.get(TOPIX)
        empty = Observation(
            observation_id="obs_tp_empty", entity_id=spec.series.instrument_id,
            metric=spec.series.metric, value=None, unit=spec.unit,
            as_of=as_of_for(spec, day.isoformat()), kind=ObservationKind.RAW,
            series_id=TOPIX, trading_date=day.isoformat(), source_id="test")
        out = derive_cross_series(_cross(), [_obs(NIKKEI, day, "39000", "nk")], [empty])
        assert out == ()
