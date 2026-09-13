"""Size / scale internals（Phase 3.5 §11）。

Security master の `ScaleCat`（TOPIX size区分）を **sourceの定義のまま**使う:

    TOPIX 100 = TOPIX Core30 + TOPIX Large70   （大型）
    TOPIX Mid400                               （中型）
    TOPIX Small = TOPIX Small 1 + TOPIX Small 2（小型）

独自に時価総額の閾値を発明しない。ScaleCat が無い銘柄（TOPIX非構成）は
`unclassified` として件数だけ報告し、集計に含めない。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .breadth import QUANT, equal_weighted_return_pct
from .price_movement import ADVANCE, DECLINE, UNCHANGED, Movement
from .types import SIZE_GROUPS, SIZE_LABELS
from .universe import UniverseSnapshot

SIZE_CALC = ("size_internals", "1.0.0")
LARGE_GROUP = "topix100"
SMALL_GROUP = "small"


@dataclass(frozen=True, kw_only=True)
class SizeAggregate:
    session_date: str
    group: str                           # topix100 / mid400 / small
    categories: Tuple[str, ...]
    members: int
    priced: int
    advancers: int
    decliners: int
    unchanged: int
    ew_return_pct: Optional[Decimal]
    relative_return_pct_point: Optional[Decimal]
    manifest_id: str = ""

    @property
    def label(self) -> str:
        return SIZE_LABELS.get(self.group, self.group)

    @property
    def advance_ratio_pct(self) -> Optional[Decimal]:
        if self.priced == 0:
            return None
        return (Decimal(self.advancers) / Decimal(self.priced) * Decimal(100)).quantize(QUANT)

    @property
    def record_id(self) -> str:
        return f"size_{self.group}_{self.session_date}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "record_id": self.record_id, "kind": "size", "session_date": self.session_date,
            "group": self.group, "categories": list(self.categories),
            "members": self.members, "priced": self.priced, "advancers": self.advancers,
            "decliners": self.decliners, "unchanged": self.unchanged,
            "ew_return_pct": str(self.ew_return_pct) if self.ew_return_pct is not None else "",
            "relative_return_pct_point": (str(self.relative_return_pct_point)
                                          if self.relative_return_pct_point is not None else ""),
            "manifest_id": self.manifest_id,
        }


def group_of(scale_category: str) -> str:
    for group, categories in SIZE_GROUPS.items():
        if scale_category in categories:
            return group
    return "unclassified"


def aggregate_sizes(*, session_date: str, universe: UniverseSnapshot,
                    movements: Mapping[str, Movement], manifest_id: str = ""
                    ) -> Tuple[List[SizeAggregate], Dict[str, int]]:
    groups: Dict[str, List[Movement]] = {g: [] for g in SIZE_GROUPS}
    unclassified = 0
    universe_ew = equal_weighted_return_pct([m for m in movements.values() if m.counted])
    for member in universe.members:
        group = group_of(member.scale_category)
        m = movements.get(member.code)
        if group == "unclassified":
            unclassified += 1
            continue
        if m is not None:
            groups[group].append(m)
    out: List[SizeAggregate] = []
    for group, moves in groups.items():
        if not moves:
            continue
        counted = [m for m in moves if m.counted]
        ew = equal_weighted_return_pct(counted)
        relative = ((ew - universe_ew).quantize(QUANT)
                    if ew is not None and universe_ew is not None else None)
        out.append(SizeAggregate(
            session_date=session_date, group=group, categories=SIZE_GROUPS[group],
            members=len(moves), priced=len(counted),
            advancers=sum(1 for m in counted if m.classification == ADVANCE),
            decliners=sum(1 for m in counted if m.classification == DECLINE),
            unchanged=sum(1 for m in counted if m.classification == UNCHANGED),
            ew_return_pct=ew, relative_return_pct_point=relative, manifest_id=manifest_id))
    return out, {"scale_unclassified": unclassified, "groups": len(out)}


def large_vs_small_gap(aggregates: Sequence[SizeAggregate]) -> Optional[Decimal]:
    """大型（TOPIX 100）− 小型（TOPIX Small）の等ウェイト騰落率差（pct_point）。"""
    by_group = {a.group: a for a in aggregates}
    large, small = by_group.get(LARGE_GROUP), by_group.get(SMALL_GROUP)
    if large is None or small is None or large.ew_return_pct is None or small.ew_return_pct is None:
        return None
    return (large.ew_return_pct - small.ew_return_pct).quantize(QUANT)
