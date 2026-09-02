"""Market Internals の構築パイプライン（Phase 3.5）。

light store（J-Quants canonical）に永続化済みの record だけを入力に、

    universe（session毎） → Movement → breadth / turnover / sector / size 集計
      → manifest → Fact（3-A model） → 履歴Fact（5/20平均・25日騰落レシオ）
      → 週次flow Fact → Context（3-B model）

を**決定論的**に組む。ネットワークは使わない（取得は `ingest.py`）。
pilot と offline test が同じ関数を使う（fixtureだけで完了判定しないための共有経路）。
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..context.model import ContextItem
from ..facts.model import Fact
from ..market.jquants_light_store import JQuantsLightStore
from .breadth import AggregationManifest, BreadthAggregate, aggregate_breadth, equal_weighted_return_pct
from .config import InternalsConfig
from .contexts import build_flow_contexts, build_internals_contexts
from .facts import (
    TURNOVER_VS_20S_RATIO,
    build_breadth_facts,
    build_breadth_history_facts,
    build_flow_facts,
    build_sector_facts,
    build_size_facts,
    build_turnover_facts,
    build_turnover_history_facts,
    facts_by_session_and_type,
    MARKET_TURNOVER_VALUE,
)
from .investor_flow import WeeklyFlow, observed_sections, weekly_flows
from .price_movement import Movement, classify_session
from .quality import session_quality
from .sector import SectorAggregate, aggregate_sectors
from .size import SizeAggregate, aggregate_sizes, large_vs_small_gap
from .turnover import TurnoverAggregate, aggregate_turnover
from .types import DIM_BREADTH, DIM_FLOW, DIM_SECTOR, DIM_SIZE, DIM_TURNOVER
from .universe import UniverseSnapshot, build_universe, select_master_for_session


@dataclass
class SessionBuild:
    session_date: str
    previous_session: str
    universe: UniverseSnapshot
    movements: Dict[str, Movement]
    breadth: BreadthAggregate
    breadth_manifest: AggregationManifest
    turnover: TurnoverAggregate
    turnover_manifest: AggregationManifest
    sectors: List[SectorAggregate]
    sector_meta: Dict[str, object]
    sizes: List[SizeAggregate]
    size_meta: Dict[str, object]
    size_gap: Optional[Decimal]
    universe_ew_return: Optional[Decimal]
    quality: Dict[str, object]


@dataclass
class InternalsBuild:
    sessions: List[str]
    builds: Dict[str, SessionBuild]
    facts: List[Fact]
    flow_facts: List[Fact]
    manifests: List[AggregationManifest]
    aggregate_rows: List[Dict]
    availability: Dict[str, Dict[str, str]]
    flows: List[WeeklyFlow]
    flow_sections: Dict[str, int]
    limited: bool
    timings: Dict[str, float] = field(default_factory=dict)

    @property
    def all_facts(self) -> List[Fact]:
        return list(self.facts) + list(self.flow_facts)


def load_price_rows(light: JQuantsLightStore, session_date: str) -> Dict[str, Mapping]:
    return {str(r["code"]): r for r in light.prices_on(session_date)}


def universe_for_session(light: JQuantsLightStore, config: InternalsConfig,
                         session_date: str, *, effective_dates: Sequence[str]
                         ) -> UniverseSnapshot:
    effective, backwards = select_master_for_session(effective_dates, session_date)
    rows = light.securities_effective(effective) if effective else []
    return build_universe(rows, config.universe, session_date=session_date,
                          master_effective_date=effective,
                          master_applied_backwards=backwards)


def build_internals(light: JQuantsLightStore, config: InternalsConfig,
                    sessions: Sequence[str], *, now: Optional[datetime] = None,
                    limited: bool = False) -> InternalsBuild:
    """`sessions`（昇順）の2件目以降を集計する（1件目は前営業日としてのみ使う）。"""
    created_at = now or datetime.now(timezone.utc)
    started = _time.monotonic()
    ordered = sorted(sessions)
    effective_dates = light.security_effective_dates()
    rows_cache: Dict[str, Dict[str, Mapping]] = {}

    def rows_for(session: str) -> Dict[str, Mapping]:
        if session not in rows_cache:
            rows_cache[session] = load_price_rows(light, session)
        return rows_cache[session]

    builds: Dict[str, SessionBuild] = {}
    facts: List[Fact] = []
    manifests: List[AggregationManifest] = []
    aggregate_rows: List[Dict] = []
    daily_turnover: Dict[str, Fact] = {}
    breadth_aggregates: List[BreadthAggregate] = []
    for idx in range(1, len(ordered)):
        session, previous = ordered[idx], ordered[idx - 1]
        universe = universe_for_session(light, config, session, effective_dates=effective_dates)
        if not universe.members:
            continue
        movements = classify_session(rows_for(session), rows_for(previous), universe.codes,
                                     session_date=session, previous_session=previous)
        breadth, b_manifest = aggregate_breadth(
            session_date=session, previous_session=previous, universe=universe,
            movements=movements, price_movement_version=config.price_movement_version)
        turnover, t_manifest = aggregate_turnover(
            session_date=session, universe=universe, movements=movements,
            price_movement_version=config.price_movement_version)
        sectors, sector_meta = aggregate_sectors(
            session_date=session, universe=universe, movements=movements,
            classification=config.sector_classification, manifest_id=b_manifest.manifest_id)
        sizes, size_meta = aggregate_sizes(session_date=session, universe=universe,
                                           movements=movements,
                                           manifest_id=b_manifest.manifest_id)
        gap = large_vs_small_gap(sizes)
        universe_ew = equal_weighted_return_pct([m for m in movements.values() if m.counted])
        build = SessionBuild(
            session_date=session, previous_session=previous, universe=universe,
            movements=movements, breadth=breadth, breadth_manifest=b_manifest,
            turnover=turnover, turnover_manifest=t_manifest, sectors=sectors,
            sector_meta=sector_meta, sizes=sizes, size_meta=size_meta, size_gap=gap,
            universe_ew_return=universe_ew,
            quality=session_quality(universe, movements))
        builds[session] = build
        breadth_aggregates.append(breadth)
        manifests += [b_manifest, t_manifest]
        aggregate_rows.append(breadth.as_dict())
        aggregate_rows.append(turnover.as_dict())
        aggregate_rows += [s.as_dict() for s in sectors]
        aggregate_rows += [s.as_dict() for s in sizes]
        facts += build_breadth_facts(breadth, b_manifest, now=created_at, limited=limited)
        t_facts = build_turnover_facts(turnover, t_manifest, now=created_at, limited=limited)
        facts += t_facts
        for f in t_facts:
            if f.fact_type == MARKET_TURNOVER_VALUE:
                daily_turnover[session] = f
        facts += build_sector_facts(sectors, b_manifest, universe_ew_return=universe_ew,
                                    now=created_at, limited=limited)
        facts += build_size_facts(sizes, gap, b_manifest, now=created_at, limited=limited)
    aggregated_sessions = list(builds)
    facts += build_turnover_history_facts(daily_turnover, aggregated_sessions, now=created_at)
    facts += build_breadth_history_facts(
        breadth_aggregates, facts_by_session_and_type(facts),
        ad_ratio_sessions=config.ad_ratio_sessions, now=created_at)
    aggregate_seconds = _time.monotonic() - started

    # ---- 週次flow（sectionはconfig。観測されたsectionは報告用に数える）
    flow_rows = light.investor_flows_published_by("9999-12-31")
    flow_sections = observed_sections(flow_rows)
    flows = weekly_flows(flow_rows, section=config.flow_section,
                         investor_types=config.flow_investor_types)
    flow_facts = build_flow_facts(flows, hour_jst=config.flow_publication_hour_jst,
                                  now=created_at)

    # ---- 次元ごとの「Contextが無い理由」（snapshotが尊重する）
    by_session = facts_by_session_and_type(facts)
    availability: Dict[str, Dict[str, str]] = {}
    for session in aggregated_sessions:
        reasons: Dict[str, str] = {}
        if TURNOVER_VS_20S_RATIO not in by_session.get(session, {}):
            reasons[DIM_TURNOVER] = "INSUFFICIENT_HISTORY"
        if not builds[session].sectors:
            reasons[DIM_SECTOR] = "MISSING"
        if builds[session].size_gap is None:
            reasons[DIM_SIZE] = "MISSING"
        if not flows:
            reasons[DIM_FLOW] = "MISSING"
        availability[session] = reasons
    return InternalsBuild(
        sessions=aggregated_sessions, builds=builds, facts=facts, flow_facts=flow_facts,
        manifests=manifests, aggregate_rows=aggregate_rows, availability=availability,
        flows=flows, flow_sections=flow_sections, limited=limited,
        timings={"aggregate_seconds": round(aggregate_seconds, 3),
                 "seconds_per_session": round(
                     aggregate_seconds / max(1, len(aggregated_sessions)), 3)})


def internals_contexts(build: InternalsBuild, config: InternalsConfig, *,
                       market_items: Mapping[str, Sequence[ContextItem]] = None,
                       now: Optional[datetime] = None) -> List[ContextItem]:
    """全sessionの internals Context ＋ 週次flow Context。"""
    created_at = now or datetime.now(timezone.utc)
    market_items = market_items or {}
    all_facts = build.all_facts
    items: List[ContextItem] = []
    for session in build.sessions:
        items += build_internals_contexts(all_facts, session, config=config,
                                          market_items=market_items.get(session, ()),
                                          now=created_at)
    items += build_flow_contexts(build.flow_facts, created_at=created_at)
    return items


def availability_for(build: InternalsBuild, reference_session: str) -> Dict[str, str]:
    """朝のsnapshot用: 参照session（前営業日）の「Contextが無い理由」。"""
    return dict(build.availability.get(reference_session, {}))


def latest_availability(build: InternalsBuild) -> Dict[str, str]:
    return availability_for(build, build.sessions[-1]) if build.sessions else {}
