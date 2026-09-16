"""Market breadth aggregation と aggregation manifest（Phase 3.5 §5 / §14 / §20 / §21）。

数千銘柄からの集計Factは、巨大な `FactCalculation.inputs` を持たせる代わりに
**aggregation manifest** で入力集合を固定する:

    manifest_id / input_count / input_set_hash / universe_version /
    calculation_version / session_date / input_record_ids

manifest から inputs（当日・前営業日の price record_id）を**再構築できる**。
Fact は manifest_id を evidence（RECORD）と calculation.inputs に持つ。

breadth は **状態の記述**であり、因果を説明しない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id, sha256_hex
from .price_movement import ADVANCE, DECLINE, EXCLUDED, UNCHANGED, Movement
from .universe import UniverseSnapshot

BREADTH_CALC = ("market_breadth", "1.0.0")
QUANT = Decimal("0.000001")


@dataclass(frozen=True, kw_only=True)
class AggregationManifest:
    """集計の入力集合を固定する（Fact provenance の要）。"""

    manifest_id: str
    session_date: str
    calculation_name: str
    calculation_version: str
    universe_id: str
    universe_version: str
    universe_hash: str
    master_effective_date: str
    master_applied_backwards: bool
    price_movement_version: str
    input_count: int
    input_set_hash: str
    input_record_ids: Tuple[str, ...] = ()
    excluded: Mapping[str, int] = field(default_factory=dict)

    @property
    def method(self) -> str:
        return f"{self.calculation_name}:{self.calculation_version}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "manifest_id": self.manifest_id, "record_id": self.manifest_id,
            "session_date": self.session_date,
            "calculation_name": self.calculation_name,
            "calculation_version": self.calculation_version,
            "universe_id": self.universe_id, "universe_version": self.universe_version,
            "universe_hash": self.universe_hash,
            "master_effective_date": self.master_effective_date,
            "master_applied_backwards": self.master_applied_backwards,
            "price_movement_version": self.price_movement_version,
            "input_count": self.input_count, "input_set_hash": self.input_set_hash,
            "input_record_ids": list(self.input_record_ids),
            "excluded": dict(self.excluded),
        }

    def parameters(self) -> Dict[str, str]:
        """FactCalculation.parameters へ載せる再現用の要約。"""
        return {
            "manifest_id": self.manifest_id, "session_date": self.session_date,
            "universe_version": f"{self.universe_id}:{self.universe_version}",
            "universe_hash": self.universe_hash,
            "calculation_version": self.method,
            "price_movement_version": self.price_movement_version,
            "input_count": str(self.input_count), "input_set_hash": self.input_set_hash,
            "master_applied_backwards": str(self.master_applied_backwards).lower(),
        }


def input_set_hash(record_ids: Iterable[str]) -> str:
    return sha256_hex("\n".join(sorted(set(record_ids))).encode("utf-8"))


def make_manifest(*, session_date: str, universe: UniverseSnapshot,
                  record_ids: Iterable[str], calculation: Tuple[str, str],
                  price_movement_version: str,
                  excluded: Optional[Mapping[str, int]] = None) -> AggregationManifest:
    ids = tuple(sorted(set(r for r in record_ids if r)))
    digest = input_set_hash(ids)
    name, version = calculation
    manifest_id = content_id(
        "agg", name, version, session_date, universe.token, universe.universe_hash,
        price_movement_version, digest)
    return AggregationManifest(
        manifest_id=manifest_id, session_date=session_date,
        calculation_name=name, calculation_version=version,
        universe_id=universe.universe_id, universe_version=universe.version,
        universe_hash=universe.universe_hash,
        master_effective_date=universe.master_effective_date,
        master_applied_backwards=universe.master_applied_backwards,
        price_movement_version=price_movement_version,
        input_count=len(ids), input_set_hash=digest, input_record_ids=ids,
        excluded=dict(excluded or {}))


@dataclass(frozen=True, kw_only=True)
class BreadthAggregate:
    session_date: str
    previous_session: str
    universe_id: str
    universe_version: str
    manifest_id: str
    universe_size: int
    priced: int                       # advancers + decliners + unchanged
    advancers: int
    decliners: int
    unchanged: int
    excluded: Mapping[str, int] = field(default_factory=dict)

    @property
    def advance_decline_ratio(self) -> Optional[Decimal]:
        """値上がり÷値下がり（値下がり0なら定義不能→None）。"""
        if self.decliners == 0:
            return None
        return (Decimal(self.advancers) / Decimal(self.decliners)).quantize(QUANT)

    @property
    def advance_decline_net(self) -> int:
        return self.advancers - self.decliners

    @property
    def advance_ratio_pct(self) -> Optional[Decimal]:
        """値上がり比率（%）= 値上がり ÷ (値上がり+値下がり+変化なし) × 100。"""
        if self.priced == 0:
            return None
        return (Decimal(self.advancers) / Decimal(self.priced) * Decimal(100)).quantize(QUANT)

    @property
    def record_id(self) -> str:
        return f"breadth_{self.universe_id}_{self.session_date}_{self.manifest_id[-12:]}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "record_id": self.record_id, "kind": "breadth",
            "session_date": self.session_date, "previous_session": self.previous_session,
            "universe_id": self.universe_id, "universe_version": self.universe_version,
            "manifest_id": self.manifest_id, "universe_size": self.universe_size,
            "priced": self.priced, "advancers": self.advancers,
            "decliners": self.decliners, "unchanged": self.unchanged,
            "advance_decline_ratio": (str(self.advance_decline_ratio)
                                      if self.advance_decline_ratio is not None else ""),
            "advance_decline_net": self.advance_decline_net,
            "advance_ratio_pct": (str(self.advance_ratio_pct)
                                  if self.advance_ratio_pct is not None else ""),
            "excluded": dict(self.excluded),
        }


def aggregate_breadth(*, session_date: str, previous_session: str,
                      universe: UniverseSnapshot, movements: Mapping[str, Movement],
                      price_movement_version: str
                      ) -> Tuple[BreadthAggregate, AggregationManifest]:
    """universeの Movement → 騰落集計 ＋ manifest（決定論的）。"""
    advancers = decliners = unchanged = 0
    excluded: Dict[str, int] = {}
    record_ids: List[str] = []
    for code in universe.codes:
        m = movements.get(code)
        if m is None:
            excluded["no_close"] = excluded.get("no_close", 0) + 1
            continue
        if m.record_id:
            record_ids.append(m.record_id)
        if m.previous_record_id:
            record_ids.append(m.previous_record_id)
        if m.classification == ADVANCE:
            advancers += 1
        elif m.classification == DECLINE:
            decliners += 1
        elif m.classification == UNCHANGED:
            unchanged += 1
        else:
            excluded[m.exclusion_reason or EXCLUDED] = \
                excluded.get(m.exclusion_reason or EXCLUDED, 0) + 1
    manifest = make_manifest(session_date=session_date, universe=universe,
                             record_ids=record_ids, calculation=BREADTH_CALC,
                             price_movement_version=price_movement_version,
                             excluded=excluded)
    aggregate = BreadthAggregate(
        session_date=session_date, previous_session=previous_session,
        universe_id=universe.universe_id, universe_version=universe.version,
        manifest_id=manifest.manifest_id, universe_size=len(universe.members),
        priced=advancers + decliners + unchanged, advancers=advancers,
        decliners=decliners, unchanged=unchanged, excluded=excluded)
    return aggregate, manifest


def counted_movements(movements: Mapping[str, Movement]) -> List[Movement]:
    return [m for m in movements.values() if m.counted and m.change_pct is not None]


def equal_weighted_return_pct(movements: Sequence[Movement]) -> Optional[Decimal]:
    """等ウェイト平均騰落率（%）。判定できた銘柄だけで平均する（0で埋めない）。"""
    values = [m.change_pct for m in movements if m.change_pct is not None]
    if not values:
        return None
    return (sum(values, Decimal(0)) / Decimal(len(values))).quantize(QUANT)
