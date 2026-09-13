"""Breadth history（Phase 3.5 §13 / §15）。

- 25日騰落レシオ（advance_decline_ratio_25session）:
  日本市場で一般的な定義 **Σ(値上がり銘柄数, 25営業日) ÷ Σ(値下がり銘柄数, 25営業日) × 100**
  （変わらずは分子・分母に含めない。対象市場は東証プライム）。
  publishedされている騰落レシオはベンダーのuniverse（プライム全銘柄等）に基づくため、
  本実装（プライム普通株・corporate action除外）の値とは差異が出得る（LIMITATION）。
- breadth trend: 値上がり比率（%）の 5セッション平均 と 20セッション平均 の差で
  improving / deteriorating を判定する（閾値は config で version化）。

いずれも**必要セッションが揃わなければ計算しない**（INSUFFICIENT_HISTORY）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

from .breadth import QUANT, BreadthAggregate

AD_RATIO_CALC = ("advance_decline_ratio_nsession", "1.0.0")
BREADTH_AVERAGE_CALC = ("advance_ratio_session_average", "1.0.0")


def advance_decline_ratio_n(aggregates: Sequence[BreadthAggregate], n: int
                            ) -> Optional[Decimal]:
    """末尾 n セッションの Σ値上がり ÷ Σ値下がり × 100。不足・分母0なら None。"""
    if n <= 0 or len(aggregates) < n:
        return None
    tail = aggregates[-n:]
    advancers = sum(a.advancers for a in tail)
    decliners = sum(a.decliners for a in tail)
    if decliners == 0:
        return None
    return (Decimal(advancers) / Decimal(decliners) * Decimal(100)).quantize(QUANT)


def advance_ratio_average(aggregates: Sequence[BreadthAggregate], window: int
                          ) -> Optional[Decimal]:
    """値上がり比率（%）の末尾 window セッション平均。"""
    if window <= 0 or len(aggregates) < window:
        return None
    values = [a.advance_ratio_pct for a in aggregates[-window:]]
    if any(v is None for v in values):
        return None
    return (sum(values, Decimal(0)) / Decimal(window)).quantize(QUANT)
