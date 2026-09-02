"""Morning snapshot への market_internals 次元の付与（Phase 3.5 §23 / §33）。

Phase 3-B の `morning_context_snapshot`（look-ahead FAIL-CLOSED）をそのまま使い、
その結果に **internals_status** を付ける（既存の dimension_status は変えない）:

    breadth / turnover / sector_leadership / size_leadership / investor_flow
      → AVAILABLE / MISSING / STALE / INSUFFICIENT_HISTORY / NOT_ENTITLED
        （／ LIMITED_USE / CONFLICTED）

- 日次次元: 代表Contextの session が reference_session より古ければ STALE
- investor_flow（週次）: 最新公表週の period_end が reference_session から
  `flow_max_age_days` を超えて古ければ STALE（次の公表が来ていない）
- Contextが無い場合は呼び出し側の availability（INSUFFICIENT_HISTORY / NOT_ENTITLED）
  を尊重し、無ければ MISSING
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Dict, Mapping, Optional, Sequence, Tuple

from ..context.model import CompassContextSnapshot, ContextItem, ContextStatus
from ..context.snapshot import morning_context_snapshot
from .config import InternalsConfig
from .types import DIM_FLOW, INTERNALS_DIMENSIONS, internals_dimension_sources

_STATUS_BY_NAME = {s.value: s for s in ContextStatus}


def _latest_by_key(items: Sequence[ContextItem]) -> Dict[Tuple[str, str], ContextItem]:
    latest: Dict[Tuple[str, str], ContextItem] = {}
    for item in items:
        key = (item.context_type, item.subject.subject_id)
        current = latest.get(key)
        if current is None or item.time.session_date > current.time.session_date:
            latest[key] = item
    return latest


def internals_status(items: Sequence[ContextItem], *, reference_session: str,
                     section: str, availability: Optional[Mapping[str, str]] = None,
                     flow_max_age_days: int = 14) -> Dict[str, ContextStatus]:
    """cutoff時点で利用可能な items（snapshot.items）から internals 次元の status を決める。"""
    latest = _latest_by_key(items)
    sources = internals_dimension_sources(section)
    fallback = dict(availability or {})
    out: Dict[str, ContextStatus] = {}
    for dimension in INTERNALS_DIMENSIONS:
        item = latest.get(sources[dimension])
        if item is None:
            out[dimension] = _STATUS_BY_NAME.get(fallback.get(dimension, ""),
                                                 ContextStatus.MISSING)
            continue
        status = item.status
        if dimension == DIM_FLOW:
            try:
                age = (date.fromisoformat(reference_session)
                       - date.fromisoformat(item.time.session_date)).days
            except ValueError:
                age = flow_max_age_days + 1
            if age > flow_max_age_days and status is ContextStatus.AVAILABLE:
                status = ContextStatus.STALE
        elif item.time.session_date < reference_session and status is ContextStatus.AVAILABLE:
            status = ContextStatus.STALE
        out[dimension] = status
    return out


def attach_internals(snapshot: CompassContextSnapshot,
                     status: Mapping[str, ContextStatus]) -> CompassContextSnapshot:
    return replace(snapshot, internals_status=dict(status))


def morning_internals_snapshot(items: Sequence[ContextItem], session_date: str, *,
                               config: InternalsConfig,
                               availability: Optional[Mapping[str, str]] = None,
                               generated_at: Optional[datetime] = None
                               ) -> CompassContextSnapshot:
    """3-Bのmorning snapshot ＋ internals_status（look-ahead判定は3-Bのまま）。"""
    snapshot = morning_context_snapshot(items, session_date, generated_at=generated_at)
    status = internals_status(snapshot.items, reference_session=snapshot.reference_session,
                              section=config.flow_section, availability=availability,
                              flow_max_age_days=config.flow_max_age_days)
    return attach_internals(snapshot, status)
