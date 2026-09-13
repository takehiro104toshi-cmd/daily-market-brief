"""単位の取り違え防止（Phase 1-D）。

「4.25 %」「0.0425 ratio」「425 bps」は**同じ量の異なる表現**であり、
unitラベル無しの数値比較・雑な同一視を禁止する。変換は明示的なDecimal演算のみ。

Observation（P1-A）の unit / currency フィールドへ入れる語彙と、
表現間の決定論的変換関数を提供する。floatは一切使わない。
"""
from __future__ import annotations

from decimal import Decimal

#: 比率系unitの正準語彙
UNIT_PERCENT = "pct"     # 4.25 (%表記の数値)
UNIT_BPS = "bps"         # 425
UNIT_RATIO = "ratio"     # 0.0425
UNIT_PERCENT_POINT = "pct_point"  # 差分（%ポイント）。%と混同しない

_HUNDRED = Decimal("100")
_TEN_THOUSAND = Decimal("10000")


def pct_to_bps(value: Decimal) -> Decimal:
    return value * _HUNDRED


def bps_to_pct(value: Decimal) -> Decimal:
    return value / _HUNDRED


def pct_to_ratio(value: Decimal) -> Decimal:
    return value / _HUNDRED


def ratio_to_pct(value: Decimal) -> Decimal:
    return value * _HUNDRED


def bps_to_ratio(value: Decimal) -> Decimal:
    return value / _TEN_THOUSAND


def ratio_to_bps(value: Decimal) -> Decimal:
    return value * _TEN_THOUSAND


def same_quantity(value_a: Decimal, unit_a: str, value_b: Decimal, unit_b: str) -> bool:
    """異unit間の同値判定は必ず明示変換を通す（unit無視の比較をさせない）。"""
    to_ratio = {
        UNIT_PERCENT: pct_to_ratio,
        UNIT_BPS: bps_to_ratio,
        UNIT_RATIO: lambda v: v,
    }
    if unit_a not in to_ratio or unit_b not in to_ratio:
        raise ValueError(f"same_quantity supports ratio-family units only: {unit_a}, {unit_b}")
    return to_ratio[unit_a](value_a) == to_ratio[unit_b](value_b)
