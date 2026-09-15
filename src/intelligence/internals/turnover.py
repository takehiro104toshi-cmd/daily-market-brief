"""Market turnover（Phase 3.5 §8）。

universe の売買代金（`Va`）・出来高（`Vo`）を銘柄レベルから合算し、
5 / 20 セッション平均と 当日 ÷ 20セッション平均 を計算する。

- 平均は**必要セッションが全て揃うときだけ**計算する（欠ければ None ＝ INSUFFICIENT_HISTORY）。
- 履歴Compassの「東証プライム売買代金」とはuniverse・取得経路が異なり得るため、
  値が一致しなくても無理に合わせない（比較は観測として報告する）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .breadth import AggregationManifest, make_manifest
from .price_movement import Movement
from .universe import UniverseSnapshot

TURNOVER_CALC = ("market_turnover", "1.0.0")
TURNOVER_AVERAGE_CALC = ("turnover_session_average", "1.0.0")
TURNOVER_RATIO_CALC = ("turnover_vs_average_ratio", "1.0.0")
QUANT = Decimal("0.000001")


@dataclass(frozen=True, kw_only=True)
class TurnoverAggregate:
    session_date: str
    universe_id: str
    universe_version: str
    manifest_id: str
    universe_size: int
    securities_with_value: int
    total_turnover_value: Optional[Decimal]      # JPY（sourceの Va を合算）
    total_volume: Optional[Decimal]
    excluded: Mapping[str, int] = field(default_factory=dict)

    @property
    def record_id(self) -> str:
        return f"turnover_{self.universe_id}_{self.session_date}_{self.manifest_id[-12:]}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "record_id": self.record_id, "kind": "turnover",
            "session_date": self.session_date, "universe_id": self.universe_id,
            "universe_version": self.universe_version, "manifest_id": self.manifest_id,
            "universe_size": self.universe_size,
            "securities_with_value": self.securities_with_value,
            "total_turnover_value": (str(self.total_turnover_value)
                                     if self.total_turnover_value is not None else ""),
            "total_volume": str(self.total_volume) if self.total_volume is not None else "",
            "excluded": dict(self.excluded),
        }


def aggregate_turnover(*, session_date: str, universe: UniverseSnapshot,
                       movements: Mapping[str, Movement], price_movement_version: str
                       ) -> Tuple[TurnoverAggregate, AggregationManifest]:
    """当日recordの売買代金・出来高を universe で合算する。"""
    total_value = Decimal(0)
    total_volume = Decimal(0)
    with_value = 0
    excluded: Dict[str, int] = {}
    record_ids: List[str] = []
    for code in universe.codes:
        m = movements.get(code)
        if m is None or not m.record_id:
            excluded["no_record"] = excluded.get("no_record", 0) + 1
            continue
        if m.turnover_value is None:
            excluded["no_turnover_value"] = excluded.get("no_turnover_value", 0) + 1
            continue
        record_ids.append(m.record_id)
        with_value += 1
        total_value += m.turnover_value
        if m.volume is not None:
            total_volume += m.volume
    manifest = make_manifest(session_date=session_date, universe=universe,
                             record_ids=record_ids, calculation=TURNOVER_CALC,
                             price_movement_version=price_movement_version,
                             excluded=excluded)
    aggregate = TurnoverAggregate(
        session_date=session_date, universe_id=universe.universe_id,
        universe_version=universe.version, manifest_id=manifest.manifest_id,
        universe_size=len(universe.members), securities_with_value=with_value,
        total_turnover_value=total_value if with_value else None,
        total_volume=total_volume if with_value else None, excluded=excluded)
    return aggregate, manifest


def rolling_average(values: Sequence[Optional[Decimal]], window: int) -> Optional[Decimal]:
    """末尾 `window` 件の平均。件数不足・欠測があれば None（近似値を作らない）。"""
    if window <= 0 or len(values) < window:
        return None
    tail = list(values[-window:])
    if any(v is None for v in tail):
        return None
    return (sum(tail, Decimal(0)) / Decimal(window)).quantize(QUANT)


def ratio_to_average(current: Optional[Decimal], average: Optional[Decimal]
                     ) -> Optional[Decimal]:
    if current is None or average is None or average == 0:
        return None
    return (current / average).quantize(QUANT)
