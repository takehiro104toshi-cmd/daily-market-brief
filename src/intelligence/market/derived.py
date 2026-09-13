"""派生系列の基盤（Phase 2-D PART F——foundation only・TAライブラリ化はしない）。

対象（カタログderivationsと対応）:
- return_1d / return_5d（観測セッション基準の変化率・pct）
- ma25（直近25観測セッションの単純移動平均）
- dist_25dma（25DMAからの乖離率・pct）
- yield_spread（2系列の差。UST10Y−UST2Y等・pct_point）
- nt_ratio（2系列の比。日経/TOPIX・倍率x）

原則:
- derivedは**入力observation_id（provenance）＋calculation_method（name:version）必須**
  （Observation型が強制）。
- 全演算Decimal（float非経由）。丸めは6桁固定（ROUND_HALF_EVEN）——calculation versionの
  一部として固定し、変更時はversionを上げる。
- 欠測セッションは**補間しない**: 値のあるセッション列の上でのみ計算する
  （データ不足のwindowは出力しない——0で埋める方が誤り）。
- 決定論ID: 同一入力×同一計算→同一observation_id（再実行が冪等）。
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import List, Sequence, Tuple

from ..core.ids import content_id
from .model import Observation, ObservationKind
from .series_catalog import (
    CrossSeriesDerivation,
    PerSeriesDerivation,
    SeriesSpec,
    derived_series_id_for,
)

#: 丸め規約（calculation versionに含まれる固定パラメータ）
_Q = Decimal("0.000001")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_Q, rounding=ROUND_HALF_EVEN)


def _derived_id(series_id: str, trading_date: str, calculation: str, inputs: Sequence[str]) -> str:
    return content_id("obs", series_id, trading_date, calculation, *inputs)


def _make(
    *,
    series_id: str,
    instrument_id: str,
    metric: str,
    value: Decimal,
    unit: str,
    template: Observation,
    calculation: str,
    inputs: Tuple[str, ...],
    currency: str = "",
) -> Observation:
    """templateのas_of/trading_dateを引き継いだderived Observation。"""
    return Observation(
        observation_id=_derived_id(series_id, template.trading_date, calculation, inputs),
        entity_id=instrument_id,
        metric=metric,
        value=value,
        unit=unit,
        as_of=template.as_of,
        kind=ObservationKind.DERIVED,
        currency=currency,
        calculation_method=calculation,
        inputs=inputs,
        series_id=series_id,
        trading_date=template.trading_date,
    )


def _observed(observations: Sequence[Observation]) -> List[Observation]:
    """値のあるrawのみ・trading_date昇順（欠測は補間せず単に対象外）。"""
    return sorted(
        (o for o in observations if o.value is not None and o.trading_date),
        key=lambda o: o.trading_date,
    )


def derive_per_series(
    spec: SeriesSpec,
    derivations: Sequence[PerSeriesDerivation],
    observations: Sequence[Observation],
) -> Tuple[Observation, ...]:
    """1系列のraw観測列（改定解決済み）→ 汎用派生の全Observation。"""
    series = _observed(observations)
    out: List[Observation] = []
    by_metric = {d.metric: d for d in derivations}

    def emit(metric: str, value: Decimal, template: Observation, inputs: Tuple[str, ...]) -> None:
        d = by_metric[metric]
        unit = spec.unit if d.unit == "same_as_base" else d.unit
        out.append(_make(
            series_id=derived_series_id_for(spec, metric),
            instrument_id=spec.series.instrument_id,
            metric=metric, value=value, unit=unit, template=template,
            calculation=d.calculation, inputs=inputs,
            currency=spec.currency if d.unit == "same_as_base" else "",
        ))

    for offset, metric in ((1, "return_1d"), (5, "return_5d")):
        if metric not in by_metric:
            continue
        for i in range(offset, len(series)):
            prev, cur = series[i - offset], series[i]
            if prev.value == 0:
                continue  # 0割は出力しない（issueは品質レポート側で把握可能）
            change = _quantize((cur.value - prev.value) / prev.value * Decimal(100))
            emit(metric, change, cur,
                 (prev.observation_id, cur.observation_id))

    window = 25
    if "ma25" in by_metric:
        for i in range(window - 1, len(series)):
            chunk = series[i - window + 1: i + 1]
            mean = _quantize(sum(o.value for o in chunk) / Decimal(window))
            template = chunk[-1]
            inputs = tuple(o.observation_id for o in chunk)
            emit("ma25", mean, template, inputs)
            if "dist_25dma" in by_metric and mean != 0:
                dist = _quantize((template.value - mean) / mean * Decimal(100))
                emit("dist_25dma", dist, template,
                     (template.observation_id, out[-1].observation_id))
    return tuple(out)


def derive_cross_series(
    cross: CrossSeriesDerivation,
    left: Sequence[Observation],
    right: Sequence[Observation],
) -> Tuple[Observation, ...]:
    """2系列のraw観測列 → スプレッド/比率（trading_dateが両方に存在する日のみ）。

    片側欠測の日は**出力しない**（補間・持ち越しをしない）。
    """
    calc_name = cross.calculation.split(":", 1)[0]
    if calc_name not in ("yield_spread", "nt_ratio"):
        raise ValueError(f"unknown cross calculation: {cross.calculation}")
    instrument_id, remainder = cross.series_id.split(".", 1)
    metric = remainder.split(".", 1)[0]

    right_by_date = {o.trading_date: o for o in _observed(right)}
    out: List[Observation] = []
    for a in _observed(left):
        b = right_by_date.get(a.trading_date)
        if b is None:
            continue
        if calc_name == "yield_spread":
            value = _quantize(a.value - b.value)
        else:  # nt_ratio
            if b.value == 0:
                continue
            value = _quantize(a.value / b.value)
        out.append(_make(
            series_id=cross.series_id,
            instrument_id=instrument_id,
            metric=metric, value=value, unit=cross.unit, template=a,
            calculation=cross.calculation,
            inputs=(a.observation_id, b.observation_id),
        ))
    return tuple(out)
