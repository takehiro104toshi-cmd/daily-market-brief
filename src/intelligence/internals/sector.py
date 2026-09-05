"""Sector internals（Phase 3.5 §9 / §10）。

Security master の業種分類で universe を分け、業種ごとに

- 等ウェイト平均騰落率（%）
- 市場（universe）等ウェイト平均との差（pct_point）＝ relative performance
- 値上がり比率（%）
- 売買代金合計

を計算する。**Morning Compass用途は17業種（S17）**を採用する（33業種は粒度が細かく
朝の説明には向かない。設定 `sector_classification` で切替可能だが両体系を大量生成しない）。

leaders / laggards は「市場平均との差」の上位／下位（`sector_top_n`）で、差が
`sector_min_relative_gap_pct_point` 未満なら**選ばない**（ノイズをリーダーと呼ばない）。

これは「銀行が買われた理由」を説明するものではない（状態の記述のみ）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .breadth import QUANT, equal_weighted_return_pct
from .price_movement import ADVANCE, DECLINE, UNCHANGED, Movement
from .universe import SecurityRef, UniverseSnapshot

SECTOR_CALC = ("sector_internals", "1.0.0")
S17 = "S17"
S33 = "S33"


@dataclass(frozen=True, kw_only=True)
class SectorAggregate:
    session_date: str
    classification: str                 # S17 / S33
    sector_code: str
    sector_name: str
    members: int
    priced: int
    advancers: int
    decliners: int
    unchanged: int
    ew_return_pct: Optional[Decimal]
    relative_return_pct_point: Optional[Decimal]
    turnover_value: Optional[Decimal]
    manifest_id: str = ""

    @property
    def advance_ratio_pct(self) -> Optional[Decimal]:
        if self.priced == 0:
            return None
        return (Decimal(self.advancers) / Decimal(self.priced) * Decimal(100)).quantize(QUANT)

    @property
    def record_id(self) -> str:
        return f"sector_{self.classification}_{self.sector_code}_{self.session_date}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "record_id": self.record_id, "kind": "sector",
            "session_date": self.session_date, "classification": self.classification,
            "sector_code": self.sector_code, "sector_name": self.sector_name,
            "members": self.members, "priced": self.priced,
            "advancers": self.advancers, "decliners": self.decliners,
            "unchanged": self.unchanged,
            "ew_return_pct": str(self.ew_return_pct) if self.ew_return_pct is not None else "",
            "relative_return_pct_point": (str(self.relative_return_pct_point)
                                          if self.relative_return_pct_point is not None else ""),
            "advance_ratio_pct": (str(self.advance_ratio_pct)
                                  if self.advance_ratio_pct is not None else ""),
            "turnover_value": (str(self.turnover_value)
                               if self.turnover_value is not None else ""),
            "manifest_id": self.manifest_id,
        }


def _sector_of(member: SecurityRef, classification: str) -> Tuple[str, str]:
    if classification == S33:
        return member.sector33_code, member.sector33_name
    return member.sector17_code, member.sector17_name


def aggregate_sectors(*, session_date: str, universe: UniverseSnapshot,
                      movements: Mapping[str, Movement], classification: str = S17,
                      manifest_id: str = "") -> Tuple[List[SectorAggregate], Dict[str, int]]:
    """業種別集計。戻り値は (aggregates, {"sector_unknown": n, ...})。"""
    groups: Dict[Tuple[str, str], List[Movement]] = {}
    counts: Dict[str, int] = {}
    unknown = 0
    universe_moves = [m for m in movements.values() if m.counted]
    universe_ew = equal_weighted_return_pct(universe_moves)
    for member in universe.members:
        code, name = _sector_of(member, classification)
        if not code:
            unknown += 1
            continue
        m = movements.get(member.code)
        if m is None:
            continue
        groups.setdefault((code, name), []).append(m)
        counts[code] = counts.get(code, 0) + 1
    out: List[SectorAggregate] = []
    for (code, name), moves in sorted(groups.items()):
        counted = [m for m in moves if m.counted]
        ew = equal_weighted_return_pct(counted)
        relative = ((ew - universe_ew).quantize(QUANT)
                    if ew is not None and universe_ew is not None else None)
        turnover_values = [m.turnover_value for m in moves if m.turnover_value is not None]
        out.append(SectorAggregate(
            session_date=session_date, classification=classification,
            sector_code=code, sector_name=name, members=len(moves),
            priced=len(counted),
            advancers=sum(1 for m in counted if m.classification == ADVANCE),
            decliners=sum(1 for m in counted if m.classification == DECLINE),
            unchanged=sum(1 for m in counted if m.classification == UNCHANGED),
            ew_return_pct=ew, relative_return_pct_point=relative,
            turnover_value=sum(turnover_values, Decimal(0)) if turnover_values else None,
            manifest_id=manifest_id))
    return out, {"sector_unknown": unknown, "sectors": len(out),
                 "universe_ew_return_pct": str(universe_ew) if universe_ew is not None else ""}


def leaders_and_laggards(aggregates: Sequence[SectorAggregate], *, top_n: int,
                         min_gap: Decimal) -> Tuple[List[SectorAggregate], List[SectorAggregate]]:
    """市場平均との差で上位／下位を選ぶ（差が閾値未満なら選ばない）。決定論的並び。"""
    ranked = [a for a in aggregates if a.relative_return_pct_point is not None]
    ranked.sort(key=lambda a: (-a.relative_return_pct_point, a.sector_code))
    leaders = [a for a in ranked[:top_n] if a.relative_return_pct_point >= min_gap]
    laggards = [a for a in reversed(ranked[-top_n:]) if -a.relative_return_pct_point >= min_gap]
    laggards = [a for a in laggards if a not in leaders]
    return leaders, laggards
