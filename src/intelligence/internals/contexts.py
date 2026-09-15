"""Market Internals → Context（Phase 3.5 §10 / §12 / §13 / §18 / §22）。

Phase 3-B の ContextItem をそのまま使う（決定論的・supporting_fact_ids必須・因果なし）。

- breadth_state       : UP（値上がり優勢）/ DOWN（値下がり優勢）/ FLAT（同数）
- breadth_trend       : UP（improving）/ DOWN（deteriorating）/ FLAT（5日平均−20日平均が閾値内）
- turnover_state      : ABOVE / BELOW / FLAT（当日 ÷ 20セッション平均、flat band付き）
- sector_leadership   : 要約（leaders/laggards）＋ 業種別（OUTPERFORM / UNDERPERFORM）
- size_leadership     : OUTPERFORM（大型>小型）/ UNDERPERFORM / FLAT
- investor_flow_state : UP（買い越し）/ DOWN（売り越し）/ FLAT（**週次**。session_date=period_end）
- index_leadership    : NIKKEI_LED / TOPIX_LED × BROAD_CONFIRMATION / NARROW_LEADERSHIP
                        （既存のindex_direction / nt_ratio_state Contextと breadth の組合せ。
                        データ不足なら UNKNOWN）

閾値は config（version付き）。恣意的なscoreを作らない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..context.builders import INDEX_DIRECTION, NIKKEI, NT_RATIO_STATE, NT_SUBJECT, TOPIX
from ..context.model import (
    ContextItem,
    ContextStatus,
    ContextSubject,
    ContextTimeContext,
    Direction,
    Relationship,
    make_context_id,
)
from ..facts.model import Fact, FactStatus
from .config import InternalsConfig
from .facts import (
    AD_RATIO_25S,
    ADVANCE_DECLINE_NET,
    ADVANCE_RATIO_20S_AVG,
    ADVANCE_RATIO_5S_AVG,
    ADVANCE_RATIO_PCT,
    INVESTOR_FLOW_NET,
    MARKET_ADVANCERS,
    MARKET_DECLINERS,
    MARKET_LABEL,
    MARKET_TURNOVER_VALUE,
    MARKET_UNCHANGED,
    SECTOR_EW_RETURN,
    SECTOR_RELATIVE_RETURN,
    SIZE_EW_RETURN,
    SIZE_LARGE_VS_SMALL,
    TURNOVER_20S_AVG,
    TURNOVER_VS_20S_RATIO,
)
from .types import (
    BREADTH_STATE,
    BREADTH_TREND,
    BROAD_CONFIRMATION,
    INDEX_LEADERSHIP,
    INDEX_LEADERSHIP_SUBJECT,
    INVESTOR_FLOW_STATE,
    MARKET_SUBJECT,
    MIXED_LEADERSHIP,
    NARROW_LEADERSHIP,
    NET_BUY,
    NET_SELL,
    NIKKEI_LED,
    SECTOR_LEADERSHIP,
    SECTOR_SUBJECT_PREFIX,
    SECTOR_SUMMARY_SUBJECT,
    SIZE_LEADERSHIP,
    SIZE_SUMMARY_SUBJECT,
    TOPIX_LED,
    TURNOVER_STATE,
    UNKNOWN_LEADERSHIP,
    size_subject,
)

RULE_VERSION = "1.0.0"


# ------------------------------------------------------------------ helpers

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
    times = [f.time.known_at for f in facts]
    if not times or any(t is None for t in times):
        return None
    return max(times)


def _item(*, context_type: str, subject: ContextSubject, session_date: str,
          direction: Direction, facts: Sequence[Fact], magnitude: Optional[Decimal] = None,
          magnitude_unit: str = "", relationship: Optional[Relationship] = None,
          rule_name: str, created_at: datetime, session_count: int = 0,
          note: str = "") -> Optional[ContextItem]:
    if not facts:
        return None
    fact_ids = tuple(dict.fromkeys(f.fact_id for f in facts))
    return ContextItem(
        context_id=make_context_id(
            context_type=context_type, subject=subject, session_date=session_date,
            rule=f"{rule_name}:{RULE_VERSION}", direction=direction, magnitude=magnitude,
            supporting_fact_ids=fact_ids),
        context_type=context_type, subject=subject,
        time=ContextTimeContext(session_date=session_date, known_at=_known_at(facts),
                                session_count=session_count),
        direction=direction, relationship=relationship, magnitude=magnitude,
        magnitude_unit=magnitude_unit, supporting_fact_ids=fact_ids, rule_name=rule_name,
        rule_version=RULE_VERSION, status=_status_of(facts), quality=_quality_of(facts),
        created_at=created_at, note=note)


class InternalsFactIndex:
    """session × subject × fact_type で Fact を引く（UNUSABLE / SUPERSEDED は除く）。"""

    def __init__(self, facts: Iterable[Fact]) -> None:
        self._by: Dict[Tuple[str, str, str], Fact] = {}
        self._by_type: Dict[Tuple[str, str], List[Fact]] = {}
        for fact in facts:
            if fact.status in (FactStatus.UNUSABLE, FactStatus.SUPERSEDED):
                continue
            key = (fact.time.primary_date, fact.subject.subject_id, fact.fact_type)
            self._by[key] = fact
            self._by_type.setdefault((fact.time.primary_date, fact.fact_type), []).append(fact)

    def get(self, session_date: str, subject_id: str, fact_type: str) -> Optional[Fact]:
        return self._by.get((session_date, subject_id, fact_type))

    def of_type(self, session_date: str, fact_type: str) -> List[Fact]:
        return sorted(self._by_type.get((session_date, fact_type), []),
                      key=lambda f: f.subject.subject_id)

    @property
    def sessions(self) -> List[str]:
        return sorted({k[0] for k in self._by})


def _market_subject() -> ContextSubject:
    return ContextSubject(subject_type="market", subject_id=MARKET_SUBJECT,
                          display_name=MARKET_LABEL)


# ------------------------------------------------------------------ builders

def build_breadth_context(index: InternalsFactIndex, session_date: str, *,
                          config: InternalsConfig, created_at: datetime
                          ) -> List[ContextItem]:
    adv = index.get(session_date, MARKET_SUBJECT, MARKET_ADVANCERS)
    dec = index.get(session_date, MARKET_SUBJECT, MARKET_DECLINERS)
    unch = index.get(session_date, MARKET_SUBJECT, MARKET_UNCHANGED)
    ratio = index.get(session_date, MARKET_SUBJECT, ADVANCE_RATIO_PCT)
    net = index.get(session_date, MARKET_SUBJECT, ADVANCE_DECLINE_NET)
    if adv is None or dec is None or unch is None or ratio is None:
        return []
    a, d = adv.value.value, dec.value.value
    if a > d:
        direction, state = Direction.UP, "BREADTH_POSITIVE"
    elif a < d:
        direction, state = Direction.DOWN, "BREADTH_NEGATIVE"
    else:
        direction, state = Direction.FLAT, "BREADTH_MIXED"
    share = ratio.value.value
    extreme = (share >= config.breadth_extreme_advance_ratio_pct
               or share <= Decimal(100) - config.breadth_extreme_advance_ratio_pct)
    facts = [adv, dec, unch, ratio] + ([net] if net is not None else [])
    ad25 = index.get(session_date, MARKET_SUBJECT, AD_RATIO_25S)
    if ad25 is not None:
        facts.append(ad25)
    item = _item(context_type=BREADTH_STATE, subject=_market_subject(),
                 session_date=session_date, direction=direction, facts=facts,
                 magnitude=share, magnitude_unit="pct", rule_name=BREADTH_STATE,
                 created_at=created_at, session_count=2,
                 note=f"state={state};extreme={'true' if extreme else 'false'}")
    return [item] if item else []


def build_breadth_trend_context(index: InternalsFactIndex, session_date: str, *,
                                config: InternalsConfig, created_at: datetime
                                ) -> List[ContextItem]:
    avg5 = index.get(session_date, MARKET_SUBJECT, ADVANCE_RATIO_5S_AVG)
    avg20 = index.get(session_date, MARKET_SUBJECT, ADVANCE_RATIO_20S_AVG)
    if avg5 is None or avg20 is None:
        return []
    diff = (avg5.value.value - avg20.value.value).quantize(Decimal("0.000001"))
    threshold = config.breadth_trend_threshold_pct_point
    if diff >= threshold:
        direction, state = Direction.UP, "IMPROVING"
    elif diff <= -threshold:
        direction, state = Direction.DOWN, "DETERIORATING"
    else:
        direction, state = Direction.FLAT, "STABLE"
    item = _item(context_type=BREADTH_TREND, subject=_market_subject(),
                 session_date=session_date, direction=direction, facts=[avg5, avg20],
                 magnitude=diff, magnitude_unit="pct_point", rule_name=BREADTH_TREND,
                 created_at=created_at, session_count=20,
                 note=f"state={state};threshold_pct_point={threshold}")
    return [item] if item else []


def build_turnover_context(index: InternalsFactIndex, session_date: str, *,
                           config: InternalsConfig, created_at: datetime
                           ) -> List[ContextItem]:
    total = index.get(session_date, MARKET_SUBJECT, MARKET_TURNOVER_VALUE)
    avg20 = index.get(session_date, MARKET_SUBJECT, TURNOVER_20S_AVG)
    ratio = index.get(session_date, MARKET_SUBJECT, TURNOVER_VS_20S_RATIO)
    if total is None or avg20 is None or ratio is None:
        return []
    r = ratio.value.value
    band, unusual = config.turnover_flat_band_ratio, config.turnover_unusual_ratio
    if r >= Decimal(1) + band:
        direction, state = Direction.ABOVE, "ABOVE_AVERAGE"
    elif r <= Decimal(1) - band:
        direction, state = Direction.BELOW, "BELOW_AVERAGE"
    else:
        direction, state = Direction.FLAT, "NEAR_AVERAGE"
    is_unusual = r >= Decimal(1) + unusual or r <= Decimal(1) - unusual
    item = _item(context_type=TURNOVER_STATE, subject=_market_subject(),
                 session_date=session_date, direction=direction,
                 facts=[total, avg20, ratio], magnitude=r, magnitude_unit="x",
                 rule_name=TURNOVER_STATE, created_at=created_at, session_count=20,
                 note=f"state={state};unusual={'true' if is_unusual else 'false'}")
    return [item] if item else []


def build_sector_contexts(index: InternalsFactIndex, session_date: str, *,
                          config: InternalsConfig, created_at: datetime
                          ) -> List[ContextItem]:
    relatives = index.of_type(session_date, SECTOR_RELATIVE_RETURN)
    if not relatives:
        return []
    ranked = sorted(relatives, key=lambda f: (-f.value.value, f.subject.subject_id))
    gap = config.sector_min_relative_gap_pct_point
    leaders = [f for f in ranked[:config.sector_top_n] if f.value.value >= gap]
    laggards = [f for f in reversed(ranked[-config.sector_top_n:])
                if -f.value.value >= gap and f not in leaders]
    out: List[ContextItem] = []
    for facts, direction in ((leaders, Direction.OUTPERFORM), (laggards, Direction.UNDERPERFORM)):
        for rel in facts:
            ew = index.get(session_date, rel.subject.subject_id, SECTOR_EW_RETURN)
            subject = ContextSubject(subject_type="sector", subject_id=rel.subject.subject_id,
                                     display_name=rel.subject.display_name,
                                     related_subject_ids=(MARKET_SUBJECT,))
            item = _item(context_type=SECTOR_LEADERSHIP, subject=subject,
                         session_date=session_date, direction=direction,
                         facts=[rel] + ([ew] if ew else []), magnitude=rel.value.value,
                         magnitude_unit="pct_point", rule_name=f"{SECTOR_LEADERSHIP}_sector",
                         created_at=created_at, session_count=2,
                         note=f"classification={config.sector_classification};"
                              f"relative_to=universe_ew_return")
            if item:
                out.append(item)
    chosen = leaders + laggards
    summary_facts = chosen or relatives
    if chosen:
        direction = Direction.MIXED if (leaders and laggards) else (
            Direction.OUTPERFORM if leaders else Direction.UNDERPERFORM)
        relationship = Relationship.DIVERGING
        magnitude = max((abs(f.value.value) for f in chosen), default=None)
    else:
        direction, relationship, magnitude = Direction.FLAT, Relationship.CONFIRMING, None
    def names(fs):
        return ",".join(f"{f.subject.subject_id.split(':')[-1]}:{f.subject.display_name}"
                        for f in fs)
    subject = ContextSubject(subject_type="market", subject_id=SECTOR_SUMMARY_SUBJECT,
                             display_name=f"業種別（{config.sector_classification}）の相対パフォーマンス",
                             related_subject_ids=tuple(f.subject.subject_id for f in chosen))
    summary = _item(context_type=SECTOR_LEADERSHIP, subject=subject,
                    session_date=session_date, direction=direction, facts=summary_facts,
                    magnitude=magnitude, magnitude_unit="pct_point",
                    relationship=relationship, rule_name=SECTOR_LEADERSHIP,
                    created_at=created_at, session_count=2,
                    note=f"leaders={names(leaders)};laggards={names(laggards)};"
                         f"min_gap_pct_point={gap}")
    if summary:
        out.insert(0, summary)
    return out


def build_size_context(index: InternalsFactIndex, session_date: str, *,
                       created_at: datetime) -> List[ContextItem]:
    gap = index.get(session_date, SIZE_SUMMARY_SUBJECT, SIZE_LARGE_VS_SMALL)
    if gap is None:
        return []
    large = index.get(session_date, size_subject("topix100"), SIZE_EW_RETURN)
    small = index.get(session_date, size_subject("small"), SIZE_EW_RETURN)
    g = gap.value.value
    if g > 0:
        direction, state = Direction.OUTPERFORM, "LARGE_LED"
    elif g < 0:
        direction, state = Direction.UNDERPERFORM, "SMALL_LED"
    else:
        direction, state = Direction.FLAT, "EVEN"
    subject = ContextSubject(subject_type="market", subject_id=SIZE_SUMMARY_SUBJECT,
                             display_name="大型株 vs 小型株",
                             related_subject_ids=(size_subject("topix100"),
                                                  size_subject("small")))
    item = _item(context_type=SIZE_LEADERSHIP, subject=subject, session_date=session_date,
                 direction=direction, facts=[gap] + [f for f in (large, small) if f],
                 magnitude=g, magnitude_unit="pct_point", rule_name=SIZE_LEADERSHIP,
                 created_at=created_at, session_count=2,
                 note=f"state={state};comparison=topix100_minus_small(ScaleCat)")
    return [item] if item else []


def build_flow_contexts(facts: Iterable[Fact], *, created_at: datetime) -> List[ContextItem]:
    """週次flow Fact → Context（session_date = period_end。日次として扱わない）。"""
    out: List[ContextItem] = []
    for fact in sorted((f for f in facts if f.fact_type == INVESTOR_FLOW_NET),
                       key=lambda f: (f.time.primary_date, f.subject.subject_id)):
        if fact.status in (FactStatus.UNUSABLE, FactStatus.SUPERSEDED):
            continue
        balance = fact.value.value
        if balance > 0:
            direction, state = Direction.UP, NET_BUY
        elif balance < 0:
            direction, state = Direction.DOWN, NET_SELL
        else:
            direction, state = Direction.FLAT, "FLAT"
        subject = ContextSubject(subject_type="investor_type",
                                 subject_id=fact.subject.subject_id,
                                 display_name=fact.subject.display_name)
        published = ""
        for token in fact.note.split(";"):
            if token.startswith("published_date="):
                published = token.split("=", 1)[1]
        item = _item(context_type=INVESTOR_FLOW_STATE, subject=subject,
                     session_date=fact.time.primary_date, direction=direction,
                     facts=[fact], magnitude=balance, magnitude_unit="source_unit",
                     rule_name=INVESTOR_FLOW_STATE, created_at=created_at,
                     session_count=1,
                     note=f"state={state};frequency=weekly;publication={published};"
                          f"period={fact.time.period_start}~{fact.time.period_end}")
        if item:
            out.append(item)
    return out


_STATUS_ORDER = {ContextStatus.AVAILABLE: 0, ContextStatus.LIMITED_USE: 1,
                 ContextStatus.STALE: 2, ContextStatus.CONFLICTED: 3}


def _combined_item(*, context_type: str, subject: ContextSubject, session_date: str,
                   direction: Direction, sources: Sequence[ContextItem],
                   relationship: Optional[Relationship], rule_name: str,
                   created_at: datetime, note: str) -> Optional[ContextItem]:
    """既存Contextの**組合せ**Context。根拠Fact / known_at / status は元Contextから継承する。"""
    fact_ids = tuple(dict.fromkeys(f for s in sources for f in s.supporting_fact_ids))
    if not fact_ids:
        return None
    times = [s.time.known_at for s in sources]
    known_at = None if any(t is None for t in times) else max(times)
    status = max((s.status for s in sources), key=lambda s: _STATUS_ORDER.get(s, 4))
    order = {"reject": 0, "limited_use": 1, "accept_with_warnings": 2, "accept": 3}
    qualities = [s.quality for s in sources if s.quality]
    quality = min(qualities, key=lambda d: order.get(d, 4)) if qualities else ""
    return ContextItem(
        context_id=make_context_id(
            context_type=context_type, subject=subject, session_date=session_date,
            rule=f"{rule_name}:{RULE_VERSION}", direction=direction, magnitude=None,
            supporting_fact_ids=fact_ids),
        context_type=context_type, subject=subject,
        time=ContextTimeContext(session_date=session_date, known_at=known_at, session_count=2),
        direction=direction, relationship=relationship, supporting_fact_ids=fact_ids,
        rule_name=rule_name, rule_version=RULE_VERSION, status=status, quality=quality,
        created_at=created_at, note=note)


def build_index_leadership_context(session_date: str, *,
                                   market_items: Sequence[ContextItem],
                                   breadth_item: Optional[ContextItem],
                                   created_at: datetime) -> List[ContextItem]:
    """既存の index_direction(TOPIX) / nt_ratio_state と breadth の**組合せ**（決定論的）。"""
    topix = next((i for i in market_items if i.context_type == INDEX_DIRECTION
                  and i.subject.subject_id == TOPIX and i.time.session_date == session_date),
                 None)
    nt = next((i for i in market_items if i.context_type == NT_RATIO_STATE
               and i.subject.subject_id == NT_SUBJECT and i.time.session_date == session_date),
              None)
    if topix is None and nt is None:
        return []
    if nt is not None and nt.direction is Direction.UP:
        lead, direction = NIKKEI_LED, Direction.OUTPERFORM
    elif nt is not None and nt.direction is Direction.DOWN:
        lead, direction = TOPIX_LED, Direction.UNDERPERFORM
    elif nt is not None and nt.direction is Direction.FLAT:
        lead, direction = MIXED_LEADERSHIP, Direction.FLAT
    else:
        lead, direction = UNKNOWN_LEADERSHIP, Direction.UNKNOWN
    if topix is None or breadth_item is None:
        breadth_state, relationship = UNKNOWN_LEADERSHIP, Relationship.INSUFFICIENT_DATA
    elif topix.direction in (Direction.UP, Direction.DOWN) and \
            breadth_item.direction == topix.direction:
        breadth_state, relationship = BROAD_CONFIRMATION, Relationship.CONFIRMING
    elif topix.direction in (Direction.UP, Direction.DOWN) and \
            breadth_item.direction in (Direction.UP, Direction.DOWN):
        breadth_state, relationship = NARROW_LEADERSHIP, Relationship.DIVERGING
    else:
        breadth_state, relationship = MIXED_LEADERSHIP, Relationship.MIXED
    sources = [i for i in (topix, nt, breadth_item) if i is not None]
    subject = ContextSubject(subject_type="market", subject_id=INDEX_LEADERSHIP_SUBJECT,
                             display_name="指数の主導構造（日経/TOPIX × breadth）",
                             related_subject_ids=(NIKKEI, TOPIX, MARKET_SUBJECT))
    item = _combined_item(
        context_type=INDEX_LEADERSHIP, subject=subject, session_date=session_date,
        direction=direction, sources=sources, relationship=relationship,
        rule_name=INDEX_LEADERSHIP, created_at=created_at,
        note=f"state={lead}|{breadth_state};"
             f"nt_direction={nt.direction.value if nt else 'NONE'};"
             f"index_direction={topix.direction.value if topix else 'NONE'};"
             f"breadth_direction={breadth_item.direction.value if breadth_item else 'NONE'}")
    return [item] if item else []


def build_internals_contexts(facts: Sequence[Fact], session_date: str, *,
                             config: InternalsConfig,
                             market_items: Sequence[ContextItem] = (),
                             now: Optional[datetime] = None) -> List[ContextItem]:
    """1セッション分の internals Context（flowは別途 build_flow_contexts）。"""
    created_at = now or datetime.now(timezone.utc)
    index = InternalsFactIndex(facts)
    items: List[ContextItem] = []
    breadth = build_breadth_context(index, session_date, config=config, created_at=created_at)
    items += breadth
    items += build_breadth_trend_context(index, session_date, config=config,
                                         created_at=created_at)
    items += build_turnover_context(index, session_date, config=config, created_at=created_at)
    items += build_sector_contexts(index, session_date, config=config, created_at=created_at)
    items += build_size_context(index, session_date, created_at=created_at)
    items += build_index_leadership_context(
        session_date, market_items=market_items, breadth_item=breadth[0] if breadth else None,
        created_at=created_at)
    return items
