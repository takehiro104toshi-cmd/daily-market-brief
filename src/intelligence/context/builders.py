"""Context builders（Phase 3-B STEP 6/10/14/15/16/17/18/19）。

Factを入力に、**決定論的**にContextItemを生成する（LLM非依存）。

規律:
- **CONTEXT ≠ FACT**: 既にderived Factとして存在する量（25DMA乖離など）は
  重複生成せず、**参照**する。
- **NO CAUSAL CLAIMS**: 同時性は `CO_OCCURRING` としてのみ記録する。
- **同一session安全**: 比較は同じ `session_date` のFact同士でのみ行う。
- 入力が欠ければContextを**作らない**（欠落は snapshot 側でstatusとして報告する）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..facts.model import Fact, FactStatus
from .model import (
    ContextItem,
    ContextStatus,
    ContextSubject,
    ContextTimeContext,
    Direction,
    Relationship,
    compare_direction,
    direction_of,
    make_context_id,
)

RULE_VERSION = "1.0.0"

# ---- context types（最小セット。増やすこと自体は目的ではない）
TREND_VS_MA = "index_trend_vs_ma25"
RELATIVE_PERFORMANCE = "relative_performance"
NT_RATIO_STATE = "nt_ratio_state"
INDEX_DIRECTION = "index_direction"
RATE_DIRECTION = "rate_direction"
CURVE_SHAPE = "us_curve_shape"
FX_DIRECTION = "fx_direction"
CROSS_ASSET_COOCCURRENCE = "cross_asset_cooccurrence"
EVENT_PROXIMITY = "event_proximity"

#: 系列ID（Phase 3-A pilotと同一）
NIKKEI = "index:nikkei225.close.closing.tokyo"
TOPIX = "index:topix.close.closing.tokyo"
JGB10Y = "rates:JGB10Y.yield.closing.tokyo"
UST2Y = "rates:UST2Y_par.yield.closing.us"
UST10Y = "rates:UST10Y_par.yield.closing.us"
USDJPY = "fx:USDJPY.rate.closing.global"
NT_SUBJECT = "index:nikkei225_topix"
CURVE_SUBJECT = "rates:UST10Y_par_UST2Y_par"

#: **USDJPY UP = 円安（JPY weaker）/ DOWN = 円高（JPY stronger）**（STEP 18で明文化）
USDJPY_UP_MEANS = Direction.WEAKER
USDJPY_DOWN_MEANS = Direction.STRONGER


def _quality_of(facts: Sequence[Fact]) -> str:
    order = {"reject": 0, "limited_use": 1, "accept_with_warnings": 2, "accept": 3}
    known = [f.qa_decision.lower() for f in facts if f.qa_decision]
    return min(known, key=lambda d: order.get(d, 4)) if known else ""


def _status_of(facts: Sequence[Fact]) -> ContextStatus:
    if any(f.conflict_state.value == "conflict" for f in facts):
        return ContextStatus.CONFLICTED
    if any(f.status is FactStatus.LIMITED_USE for f in facts):
        return ContextStatus.LIMITED_USE
    return ContextStatus.AVAILABLE


def _known_at(facts: Sequence[Fact]) -> Optional[datetime]:
    """**全支持Factが既知になった時点**（最も遅い）。1つでも不明ならNone。"""
    times = [f.time.known_at for f in facts]
    if not times or any(t is None for t in times):
        return None
    return max(times)


def _item(
    *, context_type: str, subject: ContextSubject, session_date: str,
    direction: Direction, facts: Sequence[Fact],
    magnitude: Optional[Decimal] = None, magnitude_unit: str = "",
    relationship: Optional[Relationship] = None, rule_name: str,
    created_at: datetime, session_count: int = 0, note: str = "",
) -> Optional[ContextItem]:
    if not facts:
        return None
    fact_ids = tuple(f.fact_id for f in facts)
    return ContextItem(
        context_id=make_context_id(
            context_type=context_type, subject=subject, session_date=session_date,
            rule=f"{rule_name}:{RULE_VERSION}", direction=direction,
            magnitude=magnitude, supporting_fact_ids=fact_ids),
        context_type=context_type, subject=subject,
        time=ContextTimeContext(session_date=session_date,
                                known_at=_known_at(facts),
                                session_count=session_count),
        direction=direction, relationship=relationship,
        magnitude=magnitude, magnitude_unit=magnitude_unit,
        supporting_fact_ids=fact_ids, rule_name=rule_name,
        rule_version=RULE_VERSION, status=_status_of(facts),
        quality=_quality_of(facts), created_at=created_at, note=note)


class FactIndex:
    """session_date × series × fact_type でFactを引くための軽量索引。"""

    def __init__(self, facts: Iterable[Fact]) -> None:
        self._by: Dict[Tuple[str, str, str], Fact] = {}
        self.sessions: set = set()
        for fact in facts:
            if fact.status is FactStatus.UNUSABLE:
                continue
            key = (fact.time.primary_date, fact.subject.subject_id, fact.fact_type)
            self._by[key] = fact
            self.sessions.add(fact.time.primary_date)

    def get(self, session_date: str, subject_id: str, fact_type: str) -> Optional[Fact]:
        return self._by.get((session_date, subject_id, fact_type))


# ------------------------------------------------------------------ builders

def build_trend_contexts(index: FactIndex, session_date: str, *,
                         created_at: datetime) -> List[ContextItem]:
    """指数の方向と25DMAとの位置関係（乖離率Factは**参照**して重複生成しない）。"""
    out: List[ContextItem] = []
    for series_id, name in ((NIKKEI, "日経平均株価"), (TOPIX, "TOPIX")):
        subject = ContextSubject(subject_type="series", subject_id=series_id,
                                 display_name=name)
        change = index.get(session_date, series_id, "index_change_pct")
        if change is not None:
            item = _item(context_type=INDEX_DIRECTION, subject=subject,
                         session_date=session_date,
                         direction=direction_of(change.value.value, unit="pct"),
                         facts=[change], magnitude=change.value.value,
                         magnitude_unit="pct", rule_name=INDEX_DIRECTION,
                         created_at=created_at, session_count=2)
            if item:
                out.append(item)
        distance = index.get(session_date, series_id, "distance_from_ma25_pct")
        if distance is not None and distance.value.value is not None:
            above = distance.value.value > 0
            item = _item(context_type=TREND_VS_MA, subject=subject,
                         session_date=session_date,
                         direction=Direction.ABOVE if above else Direction.BELOW,
                         facts=[distance], magnitude=distance.value.value,
                         magnitude_unit="pct", rule_name=TREND_VS_MA,
                         created_at=created_at, session_count=25,
                         note="25DMA乖離率Factを参照（再計算していない）")
            if item:
                out.append(item)
    return out


def build_relative_performance_contexts(
    index: FactIndex, session_date: str, *, created_at: datetime
) -> List[ContextItem]:
    """日経 vs TOPIX の相対パフォーマンス（5/20セッション）。"""
    out: List[ContextItem] = []
    subject = ContextSubject(
        subject_type="series_pair", subject_id=f"{NIKKEI}|{TOPIX}",
        display_name="日経平均 vs TOPIX", related_subject_ids=(NIKKEI, TOPIX))
    for fact_type, sessions in (("return_5session_pct", 5),
                                ("return_20session_pct", 20)):
        nikkei = index.get(session_date, NIKKEI, fact_type)
        topix = index.get(session_date, TOPIX, fact_type)
        if nikkei is None or topix is None:
            continue                       # 片側欠落ならContextを作らない
        # TOPIX基準で見る（TOPIXが上回れば TOPIX_OUTPERFORM）
        direction = compare_direction(topix.value.value, nikkei.value.value)
        gap = (topix.value.value - nikkei.value.value
               if topix.value.value is not None and nikkei.value.value is not None
               else None)
        item = _item(context_type=RELATIVE_PERFORMANCE, subject=subject,
                     session_date=session_date, direction=direction,
                     facts=[nikkei, topix], magnitude=gap, magnitude_unit="pct_point",
                     relationship=(Relationship.CONFIRMING
                                   if direction is Direction.FLAT
                                   else Relationship.DIVERGING),
                     rule_name=f"{RELATIVE_PERFORMANCE}_{sessions}s",
                     created_at=created_at, session_count=sessions,
                     note="TOPIX基準: OUTPERFORM=TOPIXが上回る")
        if item:
            out.append(item)
    return out


def build_nt_ratio_context(index: FactIndex, session_date: str, *,
                           previous_session: Optional[str],
                           created_at: datetime) -> List[ContextItem]:
    """NT倍率の水準と、直前セッションからの方向。"""
    current = index.get(session_date, NT_SUBJECT, "nt_ratio")
    if current is None:
        return []
    subject = ContextSubject(subject_type="series_pair", subject_id=NT_SUBJECT,
                             display_name="NT倍率",
                             related_subject_ids=(NIKKEI, TOPIX))
    facts = [current]
    direction = Direction.UNKNOWN
    magnitude: Optional[Decimal] = None
    if previous_session:
        previous = index.get(previous_session, NT_SUBJECT, "nt_ratio")
        if previous is not None and previous.value.value is not None \
                and current.value.value is not None:
            magnitude = current.value.value - previous.value.value
            direction = direction_of(magnitude, unit="x")
            facts.append(previous)
    item = _item(context_type=NT_RATIO_STATE, subject=subject,
                 session_date=session_date, direction=direction, facts=facts,
                 magnitude=magnitude, magnitude_unit="x",
                 rule_name=NT_RATIO_STATE, created_at=created_at,
                 session_count=len(facts),
                 note=f"level={current.value.value}")
    return [item] if item else []


def build_rate_contexts(index: FactIndex, session_date: str, *,
                        created_at: datetime) -> List[ContextItem]:
    """各国金利の方向（pct_pointの公表精度でFLAT判定）。"""
    out: List[ContextItem] = []
    for series_id, name in ((JGB10Y, "日本10年国債利回り"),
                            (UST2Y, "米2年国債利回り(par)"),
                            (UST10Y, "米10年国債利回り(par)")):
        change = index.get(session_date, series_id, "yield_change")
        if change is None:
            continue
        subject = ContextSubject(subject_type="series", subject_id=series_id,
                                 display_name=name)
        item = _item(context_type=RATE_DIRECTION, subject=subject,
                     session_date=session_date,
                     direction=direction_of(change.value.value, unit="pct_point"),
                     facts=[change], magnitude=change.value.value,
                     magnitude_unit="pct_point", rule_name=RATE_DIRECTION,
                     created_at=created_at, session_count=2)
        if item:
            out.append(item)
    return out


def build_curve_context(index: FactIndex, session_date: str, *,
                        previous_session: Optional[str],
                        created_at: datetime) -> List[ContextItem]:
    """米10年-2年カーブの形状変化（**同一sessionの入力が揃うときのみ**）。"""
    current = index.get(session_date, CURVE_SUBJECT, "yield_spread")
    if current is None or not previous_session:
        return []
    previous = index.get(previous_session, CURVE_SUBJECT, "yield_spread")
    if previous is None or current.value.value is None or previous.value.value is None:
        return []
    delta = current.value.value - previous.value.value
    base = direction_of(delta, unit="pct_point")
    direction = {Direction.UP: Direction.STEEPENING,
                 Direction.DOWN: Direction.FLATTENING,
                 Direction.FLAT: Direction.FLAT}.get(base, Direction.UNKNOWN)
    subject = ContextSubject(subject_type="series_pair", subject_id=CURVE_SUBJECT,
                             display_name="米10年-2年スプレッド",
                             related_subject_ids=(UST10Y, UST2Y))
    item = _item(context_type=CURVE_SHAPE, subject=subject,
                 session_date=session_date, direction=direction,
                 facts=[current, previous], magnitude=delta,
                 magnitude_unit="pct_point", rule_name=CURVE_SHAPE,
                 created_at=created_at, session_count=2,
                 note=f"spread_level={current.value.value}")
    return [item] if item else []


def build_fx_context(index: FactIndex, session_date: str, *,
                     created_at: datetime) -> List[ContextItem]:
    """ドル円の方向。**USDJPY UP = 円安 / DOWN = 円高**（決定論的写像）。"""
    change = index.get(session_date, USDJPY, "fx_change_pct")
    if change is None:
        return []
    base = direction_of(change.value.value, unit="pct")
    yen = {Direction.UP: USDJPY_UP_MEANS, Direction.DOWN: USDJPY_DOWN_MEANS,
           Direction.FLAT: Direction.FLAT}.get(base, Direction.UNKNOWN)
    subject = ContextSubject(subject_type="series", subject_id=USDJPY,
                             display_name="ドル円")
    item = _item(context_type=FX_DIRECTION, subject=subject,
                 session_date=session_date, direction=yen, facts=[change],
                 magnitude=change.value.value, magnitude_unit="pct",
                 rule_name=FX_DIRECTION, created_at=created_at, session_count=2,
                 note="USDJPY UP=円安(JPY weaker) / DOWN=円高(JPY stronger)")
    return [item] if item else []


def build_cross_asset_context(index: FactIndex, session_date: str, *,
                              created_at: datetime) -> List[ContextItem]:
    """株・金利・為替の**同時性**（因果ではない）を構造化して記録する。"""
    topix = index.get(session_date, TOPIX, "index_change_pct")
    jgb = index.get(session_date, JGB10Y, "yield_change")
    fx = index.get(session_date, USDJPY, "fx_change_pct")
    facts = [f for f in (topix, jgb, fx) if f is not None]
    if len(facts) < 2:
        return []                          # 2つ以上揃わなければ同時性を語らない
    subject = ContextSubject(
        subject_type="market", subject_id="market:japan_cross_asset",
        display_name="日本株・金利・為替の同時状態",
        related_subject_ids=tuple(f.subject.subject_id for f in facts))
    directions = []
    if topix is not None:
        directions.append(direction_of(topix.value.value, unit="pct"))
    if jgb is not None:
        directions.append(direction_of(jgb.value.value, unit="pct_point"))
    if fx is not None:
        directions.append(direction_of(fx.value.value, unit="pct"))
    known = [d for d in directions if d in (Direction.UP, Direction.DOWN)]
    if not known:
        relationship = Relationship.INSUFFICIENT_DATA
    elif len(set(known)) == 1:
        relationship = Relationship.CONFIRMING
    else:
        relationship = Relationship.MIXED
    item = _item(context_type=CROSS_ASSET_COOCCURRENCE, subject=subject,
                 session_date=session_date, direction=Direction.MIXED
                 if relationship is Relationship.MIXED else Direction.UNKNOWN,
                 facts=facts, relationship=Relationship.CO_OCCURRING,
                 rule_name=CROSS_ASSET_COOCCURRENCE, created_at=created_at,
                 session_count=1,
                 note="同時に観測された状態の記録。因果は主張しない"
                      f"（内部一致度: {relationship.value}）")
    return [item] if item else []


def build_event_contexts(
    event_facts: Sequence[Fact], session_date: str, *, created_at: datetime,
    horizon_days: int = 90,
) -> List[ContextItem]:
    """決算発表予定などのevent proximity（`days_until_event` を持たせる）。"""
    from datetime import date

    out: List[ContextItem] = []
    try:
        session = date.fromisoformat(session_date)
    except ValueError:
        return out
    for fact in event_facts:
        try:
            event_day = date.fromisoformat(fact.time.primary_date)
        except ValueError:
            continue
        days_until = (event_day - session).days
        if days_until < 0 or days_until > horizon_days:
            continue                       # 過ぎた/遠すぎるeventはContextにしない
        subject = ContextSubject(subject_type=fact.subject.subject_type,
                                 subject_id=fact.subject.subject_id,
                                 display_name=fact.subject.display_name)
        item = _item(context_type=EVENT_PROXIMITY, subject=subject,
                     session_date=session_date, direction=Direction.UNKNOWN,
                     facts=[fact], magnitude=Decimal(days_until),
                     magnitude_unit="days", rule_name=EVENT_PROXIMITY,
                     created_at=created_at,
                     note=f"event_type={fact.fact_type};"
                          f"event_date={fact.time.primary_date}")
        if item:
            out.append(item)
    return out


def build_session_contexts(
    facts: Sequence[Fact], session_date: str, *,
    previous_session: Optional[str] = None,
    event_facts: Sequence[Fact] = (),
    now: Optional[datetime] = None,
) -> List[ContextItem]:
    """1セッション分のContextをまとめて生成する。"""
    created_at = now or datetime.now(timezone.utc)
    index = FactIndex(facts)
    items: List[ContextItem] = []
    items += build_trend_contexts(index, session_date, created_at=created_at)
    items += build_relative_performance_contexts(index, session_date,
                                                 created_at=created_at)
    items += build_nt_ratio_context(index, session_date,
                                    previous_session=previous_session,
                                    created_at=created_at)
    items += build_rate_contexts(index, session_date, created_at=created_at)
    items += build_curve_context(index, session_date,
                                 previous_session=previous_session,
                                 created_at=created_at)
    items += build_fx_context(index, session_date, created_at=created_at)
    items += build_cross_asset_context(index, session_date, created_at=created_at)
    items += build_event_contexts(event_facts, session_date, created_at=created_at)
    return items
