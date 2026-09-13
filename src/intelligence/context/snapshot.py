"""Morning Context Snapshot と missingness（Phase 3-B STEP 24/25/26）。

**LOOK-AHEAD禁止**: Contextが利用可能なのは、**その支持Factが全て**朝のcutoff
時点で既知だった場合のみ（Phase 3-Aの `known_at` 意味論をそのまま使う）。

**MISSINGNESS MATTERS**: 中核次元が欠けているのに黙って省略しない。
`AVAILABLE / MISSING / STALE / INSUFFICIENT_HISTORY / CONFLICTED / LIMITED_USE`
を次元ごとに報告し、Phase 3-Cが「証拠が弱いときは語らない」判断をできるようにする。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..facts.availability import morning_cutoff
from .builders import (
    CURVE_SHAPE,
    FX_DIRECTION,
    INDEX_DIRECTION,
    JGB10Y,
    NIKKEI,
    NT_RATIO_STATE,
    RATE_DIRECTION,
    RELATIVE_PERFORMANCE,
    TOPIX,
    USDJPY,
    UST2Y,
    UST10Y,
)
from .model import (
    CompassContextSnapshot,
    ContextItem,
    ContextStatus,
    Direction,
    MarketState,
    STATE_DIMENSIONS,
)
from .salience import rank_contexts

#: 各state次元を満たすのに必要な (context_type, subject_id)
_DIMENSION_SOURCES: Mapping[str, Tuple[str, str]] = {
    "japan_equities": (INDEX_DIRECTION, TOPIX),
    "nikkei_vs_topix": (RELATIVE_PERFORMANCE, f"{NIKKEI}|{TOPIX}"),
    "nt_ratio": (NT_RATIO_STATE, "index:nikkei225_topix"),
    "japan_rates": (RATE_DIRECTION, JGB10Y),
    "us_rates_2y": (RATE_DIRECTION, UST2Y),
    "us_rates_10y": (RATE_DIRECTION, UST10Y),
    "us_curve": (CURVE_SHAPE, "rates:UST10Y_par_UST2Y_par"),
    "usd_jpy": (FX_DIRECTION, USDJPY),
}


def is_available_at(item: ContextItem, cutoff: datetime) -> bool:
    """**全支持Factが既知**であることを要求する（`known_at` が無ければ不可）。"""
    if item.time.known_at is None:
        return False
    return item.time.known_at <= cutoff


def leaked_contexts(items: Sequence[ContextItem],
                    cutoff: datetime) -> List[ContextItem]:
    return [i for i in items if not is_available_at(i, cutoff)]


def build_market_state(items: Sequence[ContextItem], *,
                       reference_session: str = "") -> MarketState:
    """利用可能なContextからmarket state vectorを組む。欠けた次元は UNKNOWN。

    同じ次元に複数sessionのContextがある場合は**最新session**を採用する
    （並び順に依存させない）。`reference_session` より古いsessionしか無い次元は
    `STALE` として報告する——黙って最新の状態のように見せない。
    """
    by_key: Dict[Tuple[str, str], ContextItem] = {}
    for item in items:
        key = (item.context_type, item.subject.subject_id)
        current = by_key.get(key)
        if current is None or item.time.session_date > current.time.session_date:
            by_key[key] = item
    values: Dict[str, Direction] = {}
    statuses: Dict[str, ContextStatus] = {}
    for dimension in STATE_DIMENSIONS:
        source = _DIMENSION_SOURCES.get(dimension)
        item = by_key.get(source) if source else None
        if item is None:
            values[dimension] = Direction.UNKNOWN
            statuses[dimension] = ContextStatus.MISSING
            continue
        values[dimension] = item.direction
        status = item.status
        if (reference_session and item.time.session_date < reference_session
                and status is ContextStatus.AVAILABLE):
            status = ContextStatus.STALE     # 品質起因のstatusは上書きしない
        statuses[dimension] = status
    return MarketState(values=values, statuses=statuses)


def morning_context_snapshot(
    items: Sequence[ContextItem],
    session_date: str,
    *,
    hour: int = 6,
    generated_at: Optional[datetime] = None,
) -> CompassContextSnapshot:
    """`session_date` の朝時点で成立していたContextだけを返す。

    Phase 3-Cの直接入力。**自然言語テキストは含まない**。
    """
    cutoff = morning_cutoff(session_date, hour=hour)
    available = [i for i in items if is_available_at(i, cutoff)]
    # 朝のCompassは**当日クローズを知り得ない**ため、鮮度の基準は
    # 「cutoff時点で利用できた最新session」（通常は前営業日）とする。
    reference = max((i.time.session_date for i in available), default=session_date)
    ranked = rank_contexts(available, session_date=reference)
    state = build_market_state(ranked, reference_session=reference)
    dimension_status = {d: state.statuses.get(d, ContextStatus.MISSING)
                        for d in STATE_DIMENSIONS}
    missing = tuple(d for d, s in dimension_status.items()
                    if s is ContextStatus.MISSING)
    return CompassContextSnapshot(
        session_date=session_date, cutoff=cutoff, items=tuple(ranked),
        market_state=state, dimension_status=dimension_status,
        missing_dimensions=missing, reference_session=reference,
        generated_at=generated_at)
