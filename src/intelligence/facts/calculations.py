"""Fact計算レジストリ（Phase 3-A STEP 8/12）。

**NO FABRICATED CALCULATION**:
- 必要inputが**同一の適切なtime context**で揃っている場合のみ値を返す。
- 欠測を forward fill / backfill / 0補完 / nearest date substitution で埋めない。
- 不足なら `None` を返し、builderはFactを作らない（FAIL-CLOSED）。

全計算は `name:version` を持ち、ロジック変更時は**versionを上げる**ことで
旧Factと区別できるようにする（Factの `calculation_method` に焼き込まれる）。
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional, Sequence

#: 丸め規約（calculation versionの一部。変更時はversionを上げる）
QUANT = Decimal("0.000001")

RETURN_PCT = ("return_pct", "1.0.0")
CHANGE_ABS = ("change_abs", "1.0.0")
MOVING_AVERAGE = ("moving_average", "1.0.0")
DISTANCE_FROM_MA_PCT = ("distance_from_ma_pct", "1.0.0")
NT_RATIO = ("nt_ratio", "1.0.0")
YIELD_SPREAD = ("yield_spread", "1.0.0")


def quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANT, rounding=ROUND_HALF_EVEN)


def change_abs(current: Optional[Decimal], previous: Optional[Decimal]) -> Optional[Decimal]:
    """絶対変化（current - previous）。片側欠測ならNone。"""
    if current is None or previous is None:
        return None
    return quantize(current - previous)


def return_pct(current: Optional[Decimal], previous: Optional[Decimal]) -> Optional[Decimal]:
    """変化率（%）。基準が0/欠測ならNone（無限大や0埋めを作らない）。"""
    if current is None or previous is None or previous == 0:
        return None
    return quantize((current - previous) / previous * Decimal(100))


def moving_average(values: Sequence[Optional[Decimal]], window: int) -> Optional[Decimal]:
    """単純移動平均。

    **必要session数が不足していれば None**（短い窓で代用しない）。
    窓内に欠測が1つでもあればNone（部分平均で誤魔化さない）。
    """
    if window <= 0 or len(values) < window:
        return None
    window_values = list(values)[-window:]
    if any(v is None for v in window_values):
        return None
    total = sum(window_values, Decimal(0))
    return quantize(total / Decimal(window))


def distance_from_ma_pct(current: Optional[Decimal],
                         ma: Optional[Decimal]) -> Optional[Decimal]:
    """移動平均からの乖離率（%）。"""
    if current is None or ma is None or ma == 0:
        return None
    return quantize((current - ma) / ma * Decimal(100))


def nt_ratio(nikkei: Optional[Decimal], topix: Optional[Decimal]) -> Optional[Decimal]:
    """NT倍率（日経225 ÷ TOPIX）。**同一trading_dateの入力のみ**で呼ぶこと。"""
    if nikkei is None or topix is None or topix == 0:
        return None
    return quantize(nikkei / topix)


def yield_spread(long_yield: Optional[Decimal],
                 short_yield: Optional[Decimal]) -> Optional[Decimal]:
    """金利スプレッド（長期 − 短期・pct_point）。同一trading_dateの入力のみ。"""
    if long_yield is None or short_yield is None:
        return None
    return quantize(long_yield - short_yield)


#: 登録済み計算（name → version）。Factの `calculation_method` はここから作る。
REGISTRY = {
    RETURN_PCT[0]: RETURN_PCT[1],
    CHANGE_ABS[0]: CHANGE_ABS[1],
    MOVING_AVERAGE[0]: MOVING_AVERAGE[1],
    DISTANCE_FROM_MA_PCT[0]: DISTANCE_FROM_MA_PCT[1],
    NT_RATIO[0]: NT_RATIO[1],
    YIELD_SPREAD[0]: YIELD_SPREAD[1],
}
