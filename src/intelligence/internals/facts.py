"""Market Internals → Fact（Phase 3.5 §14 / §17 / §20 / §21）。

Phase 3-A の Fact model をそのまま使う（別のFact概念を作らない）。

- 集計Fact（breadth / turnover / sector / size）は **aggregation manifest** を
  evidence（RECORD）と calculation.inputs に持ち、manifest から数千件の入力recordを
  再構築できる。
- 履歴Fact（5/20セッション平均・25日騰落レシオ）は入力Factの fact_id を inputs に持つ
  （Fact→Fact の citation chain）。
- 週次flow Fact は primary_date = period_end（PERIOD_END）、known_at = 公表日の
  publication hour（publication gating）。日次Factとして扱わない。
- known_at（日次集計）: そのsessionの東京クローズ（JST 15:30）。値は Decimal、欠測は
  Fact を作らない（0で埋めない）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..facts.model import (
    ConflictState,
    DateRole,
    EvidenceKind,
    Fact,
    FactCalculation,
    FactEvidenceRef,
    FactStatus,
    FactSubject,
    FactTimeContext,
    FactValue,
    make_fact_id,
    value_token,
)
from .breadth import BREADTH_CALC, AggregationManifest, BreadthAggregate
from .breadth_history import (
    AD_RATIO_CALC,
    BREADTH_AVERAGE_CALC,
    advance_decline_ratio_n,
    advance_ratio_average,
)
from .investor_flow import WeeklyFlow, known_at_for
from .sector import SECTOR_CALC, SectorAggregate
from .size import SIZE_CALC, SizeAggregate
from .turnover import (
    TURNOVER_AVERAGE_CALC,
    TURNOVER_CALC,
    TURNOVER_RATIO_CALC,
    TurnoverAggregate,
    ratio_to_average,
    rolling_average,
)
from .types import (
    MARKET_SUBJECT,
    SIZE_LABELS,
    SIZE_SUMMARY_SUBJECT,
    flow_subject,
    sector_subject,
    size_subject,
)

JST = timezone(timedelta(hours=9))
SOURCE_ID = "jquants"

# ---- fact types（market internals）
MARKET_ADVANCERS = "market_advancers"
MARKET_DECLINERS = "market_decliners"
MARKET_UNCHANGED = "market_unchanged"
MARKET_PRICED = "market_priced_securities"
MARKET_UNIVERSE_SIZE = "market_universe_size"
ADVANCE_DECLINE_RATIO = "advance_decline_ratio"
ADVANCE_DECLINE_NET = "advance_decline_net"
ADVANCE_RATIO_PCT = "advance_ratio_pct"
MARKET_TURNOVER_VALUE = "market_turnover_value"
MARKET_VOLUME = "market_volume"
TURNOVER_5S_AVG = "turnover_5session_avg"
TURNOVER_20S_AVG = "turnover_20session_avg"
TURNOVER_VS_20S_RATIO = "turnover_vs_20session_avg_ratio"
UNIVERSE_EW_RETURN = "universe_return_ew_pct"
SECTOR_EW_RETURN = "sector_return_ew_pct"
SECTOR_RELATIVE_RETURN = "sector_relative_return_pct_point"
SECTOR_ADVANCE_RATIO = "sector_advance_ratio_pct"
SECTOR_TURNOVER = "sector_turnover_value"
SIZE_EW_RETURN = "size_return_ew_pct"
SIZE_RELATIVE_RETURN = "size_relative_return_pct_point"
SIZE_LARGE_VS_SMALL = "size_large_vs_small_pct_point"
INVESTOR_FLOW_NET = "investor_flow_net"
AD_RATIO_25S = "advance_decline_ratio_25session"
ADVANCE_RATIO_5S_AVG = "advance_ratio_5session_avg"
ADVANCE_RATIO_20S_AVG = "advance_ratio_20session_avg"

INTERNALS_FACT_TYPES: Tuple[str, ...] = (
    MARKET_ADVANCERS, MARKET_DECLINERS, MARKET_UNCHANGED, MARKET_PRICED,
    MARKET_UNIVERSE_SIZE, ADVANCE_DECLINE_RATIO, ADVANCE_DECLINE_NET, ADVANCE_RATIO_PCT,
    MARKET_TURNOVER_VALUE, MARKET_VOLUME, TURNOVER_5S_AVG, TURNOVER_20S_AVG,
    TURNOVER_VS_20S_RATIO, UNIVERSE_EW_RETURN, SECTOR_EW_RETURN, SECTOR_RELATIVE_RETURN,
    SECTOR_ADVANCE_RATIO, SECTOR_TURNOVER, SIZE_EW_RETURN, SIZE_RELATIVE_RETURN,
    SIZE_LARGE_VS_SMALL, INVESTOR_FLOW_NET, AD_RATIO_25S, ADVANCE_RATIO_5S_AVG,
    ADVANCE_RATIO_20S_AVG,
)

MARKET_LABEL = "東証プライム普通株"
INVESTOR_LABELS: Mapping[str, str] = {
    "foreign_investors": "海外投資家", "individuals": "個人投資家",
    "trust_banks": "信託銀行", "business_corporations": "事業法人",
    "insurance_companies": "生保・損保", "investment_trusts": "投資信託",
    "banks": "銀行", "securities_companies": "証券会社",
}


def tokyo_close_utc(session_date: str) -> datetime:
    """東京現物クローズ（JST 15:30）= このsessionの日次集計が既知になる時点。"""
    year, month, day = (int(p) for p in session_date.split("-"))
    return datetime(year, month, day, 15, 30, tzinfo=JST).astimezone(timezone.utc)


def market_subject() -> FactSubject:
    return FactSubject(subject_type="market", subject_id=MARKET_SUBJECT,
                       display_name=MARKET_LABEL)


def _manifest_evidence(manifest: AggregationManifest) -> FactEvidenceRef:
    return FactEvidenceRef(kind=EvidenceKind.RECORD, ref_id=manifest.manifest_id,
                           locator="aggregation_manifest")


def _manifest_calc(manifest: AggregationManifest, calculation: Tuple[str, str],
                   extra: Optional[Mapping[str, str]] = None) -> FactCalculation:
    params = dict(manifest.parameters())
    if extra:
        params.update(extra)
    return FactCalculation(name=calculation[0], version=calculation[1],
                           inputs=(manifest.manifest_id,), parameters=params)


def _fact(*, fact_type: str, subject: FactSubject, session_date: str,
          value: Optional[Decimal], unit: str, calculation: Optional[FactCalculation],
          evidence: Sequence[FactEvidenceRef], created_at: datetime,
          limited: bool = False, discriminator: str = "", note: str = "",
          session_count: int = 0, currency: str = "",
          date_role: DateRole = DateRole.TRADING_DATE,
          known_at: Optional[datetime] = None, period_start: str = "",
          period_end: str = "") -> Optional[Fact]:
    if value is None:
        return None
    known = known_at or tokyo_close_utc(session_date)
    method = calculation.method if calculation else ""
    return Fact(
        fact_id=make_fact_id(fact_type=fact_type, subject=subject,
                             primary_date=session_date, value_token=value_token(value),
                             calculation_method=method, discriminator=discriminator),
        fact_type=fact_type, identity_discriminator=discriminator, subject=subject,
        value=FactValue(value=value, unit=unit, currency=currency),
        time=FactTimeContext(primary_date=session_date, date_role=date_role,
                             as_of=known, known_at=known, session_count=session_count,
                             period_start=period_start, period_end=period_end),
        evidence=tuple(evidence), calculation=calculation,
        status=FactStatus.LIMITED_USE if limited else FactStatus.USABLE,
        conflict_state=ConflictState.UNKNOWN, source_ids=(SOURCE_ID,),
        qa_decision="limited_use" if limited else "accept",
        created_at=created_at, note=note)


# ------------------------------------------------------------------ breadth

def build_breadth_facts(aggregate: BreadthAggregate, manifest: AggregationManifest, *,
                        now: datetime, limited: bool = False) -> List[Fact]:
    subject = market_subject()
    calc = _manifest_calc(manifest, BREADTH_CALC)
    ev = (_manifest_evidence(manifest),)
    sd = aggregate.session_date
    rows = (
        (MARKET_ADVANCERS, Decimal(aggregate.advancers), "issues"),
        (MARKET_DECLINERS, Decimal(aggregate.decliners), "issues"),
        (MARKET_UNCHANGED, Decimal(aggregate.unchanged), "issues"),
        (MARKET_PRICED, Decimal(aggregate.priced), "issues"),
        (MARKET_UNIVERSE_SIZE, Decimal(aggregate.universe_size), "issues"),
        (ADVANCE_DECLINE_RATIO, aggregate.advance_decline_ratio, "x"),
        (ADVANCE_DECLINE_NET, Decimal(aggregate.advance_decline_net), "issues"),
        (ADVANCE_RATIO_PCT, aggregate.advance_ratio_pct, "pct"),
    )
    out: List[Fact] = []
    for fact_type, value, unit in rows:
        fact = _fact(fact_type=fact_type, subject=subject, session_date=sd, value=value,
                     unit=unit, calculation=calc, evidence=ev, created_at=now,
                     limited=limited, session_count=2,
                     note=f"previous_session={aggregate.previous_session}")
        if fact is not None:
            out.append(fact)
    return out


# ------------------------------------------------------------------ turnover

def build_turnover_facts(aggregate: TurnoverAggregate, manifest: AggregationManifest, *,
                         now: datetime, limited: bool = False) -> List[Fact]:
    subject = market_subject()
    calc = _manifest_calc(manifest, TURNOVER_CALC)
    ev = (_manifest_evidence(manifest),)
    out: List[Fact] = []
    for fact_type, value, unit, currency in (
            (MARKET_TURNOVER_VALUE, aggregate.total_turnover_value, "jpy", "JPY"),
            (MARKET_VOLUME, aggregate.total_volume, "shares", "")):
        fact = _fact(fact_type=fact_type, subject=subject,
                     session_date=aggregate.session_date, value=value, unit=unit,
                     currency=currency, calculation=calc, evidence=ev, created_at=now,
                     limited=limited, session_count=1,
                     note=f"securities_with_value={aggregate.securities_with_value}")
        if fact is not None:
            out.append(fact)
    return out


def _fact_refs(facts: Sequence[Fact]) -> Tuple[FactEvidenceRef, ...]:
    return tuple(FactEvidenceRef(kind=EvidenceKind.FACT, ref_id=f.fact_id,
                                 locator=f.time.primary_date) for f in facts)


def build_turnover_history_facts(daily: Mapping[str, Fact], sessions: Sequence[str], *,
                                 now: datetime) -> List[Fact]:
    """日次売買代金Fact → 5/20セッション平均 ＋ 当日÷20平均（揃うsessionだけ）。"""
    subject = market_subject()
    out: List[Fact] = []
    ordered = [s for s in sessions if s in daily]
    for idx, session in enumerate(ordered):
        for window, fact_type in ((5, TURNOVER_5S_AVG), (20, TURNOVER_20S_AVG)):
            if idx + 1 < window:
                continue
            window_facts = [daily[s] for s in ordered[idx + 1 - window: idx + 1]]
            value = rolling_average([f.value.value for f in window_facts], window)
            limited = any(f.status is FactStatus.LIMITED_USE for f in window_facts)
            calc = FactCalculation(
                name=TURNOVER_AVERAGE_CALC[0], version=TURNOVER_AVERAGE_CALC[1],
                inputs=tuple(f.fact_id for f in window_facts),
                parameters={"window": str(window), "session_date": session})
            fact = _fact(fact_type=fact_type, subject=subject, session_date=session,
                         value=value, unit="jpy", currency="JPY", calculation=calc,
                         evidence=_fact_refs(window_facts), created_at=now,
                         limited=limited, session_count=window)
            if fact is not None:
                out.append(fact)
                if window == 20:
                    ratio = ratio_to_average(daily[session].value.value, value)
                    ratio_calc = FactCalculation(
                        name=TURNOVER_RATIO_CALC[0], version=TURNOVER_RATIO_CALC[1],
                        inputs=(daily[session].fact_id, fact.fact_id),
                        parameters={"window": "20", "session_date": session})
                    ratio_fact = _fact(
                        fact_type=TURNOVER_VS_20S_RATIO, subject=subject,
                        session_date=session, value=ratio, unit="x",
                        calculation=ratio_calc,
                        evidence=_fact_refs([daily[session], fact]), created_at=now,
                        limited=limited, session_count=20)
                    if ratio_fact is not None:
                        out.append(ratio_fact)
    return out


# ------------------------------------------------------------------ sector / size

def build_sector_facts(aggregates: Sequence[SectorAggregate], manifest: AggregationManifest,
                       *, universe_ew_return: Optional[Decimal], now: datetime,
                       limited: bool = False) -> List[Fact]:
    out: List[Fact] = []
    ev = (_manifest_evidence(manifest),)
    sd = manifest.session_date
    market = _fact(fact_type=UNIVERSE_EW_RETURN, subject=market_subject(), session_date=sd,
                   value=universe_ew_return, unit="pct",
                   calculation=_manifest_calc(manifest, SECTOR_CALC, {"scope": "universe"}),
                   evidence=ev, created_at=now, limited=limited, session_count=2)
    if market is not None:
        out.append(market)
    for agg in aggregates:
        subject = FactSubject(subject_type="sector", subject_id=sector_subject(agg.sector_code),
                              display_name=agg.sector_name)
        calc = _manifest_calc(manifest, SECTOR_CALC, {
            "classification": agg.classification, "sector_code": agg.sector_code,
            "members": str(agg.members), "priced": str(agg.priced)})
        for fact_type, value, unit, currency in (
                (SECTOR_EW_RETURN, agg.ew_return_pct, "pct", ""),
                (SECTOR_RELATIVE_RETURN, agg.relative_return_pct_point, "pct_point", ""),
                (SECTOR_ADVANCE_RATIO, agg.advance_ratio_pct, "pct", ""),
                (SECTOR_TURNOVER, agg.turnover_value, "jpy", "JPY")):
            fact = _fact(fact_type=fact_type, subject=subject, session_date=sd, value=value,
                         unit=unit, currency=currency, calculation=calc, evidence=ev,
                         created_at=now, limited=limited, session_count=2,
                         note=f"classification={agg.classification}")
            if fact is not None:
                out.append(fact)
    return out


def build_size_facts(aggregates: Sequence[SizeAggregate], gap: Optional[Decimal],
                     manifest: AggregationManifest, *, now: datetime,
                     limited: bool = False) -> List[Fact]:
    out: List[Fact] = []
    ev = (_manifest_evidence(manifest),)
    sd = manifest.session_date
    for agg in aggregates:
        subject = FactSubject(subject_type="size", subject_id=size_subject(agg.group),
                              display_name=SIZE_LABELS.get(agg.group, agg.group))
        calc = _manifest_calc(manifest, SIZE_CALC, {
            "group": agg.group, "categories": "|".join(agg.categories),
            "members": str(agg.members), "priced": str(agg.priced)})
        for fact_type, value, unit in ((SIZE_EW_RETURN, agg.ew_return_pct, "pct"),
                                       (SIZE_RELATIVE_RETURN, agg.relative_return_pct_point,
                                        "pct_point")):
            fact = _fact(fact_type=fact_type, subject=subject, session_date=sd, value=value,
                         unit=unit, calculation=calc, evidence=ev, created_at=now,
                         limited=limited, session_count=2)
            if fact is not None:
                out.append(fact)
    summary = FactSubject(subject_type="size", subject_id=SIZE_SUMMARY_SUBJECT,
                          display_name="大型株 vs 小型株")
    gap_fact = _fact(fact_type=SIZE_LARGE_VS_SMALL, subject=summary, session_date=sd,
                     value=gap, unit="pct_point",
                     calculation=_manifest_calc(manifest, SIZE_CALC,
                                                {"comparison": "topix100_minus_small"}),
                     evidence=ev, created_at=now, limited=limited, session_count=2)
    if gap_fact is not None:
        out.append(gap_fact)
    return out


# ------------------------------------------------------------------ investor flow

def build_flow_facts(flows: Iterable[WeeklyFlow], *, hour_jst: int, now: datetime
                     ) -> List[Fact]:
    """週次flow → Fact（primary_date=period_end, known_at=公表日の公表時刻）。"""
    out: List[Fact] = []
    for flow in flows:
        known = known_at_for(flow.published_date, hour_jst=hour_jst)
        if known is None:
            continue                                  # 公表日が読めなければ既知にしない
        subject = FactSubject(
            subject_type="investor_type",
            subject_id=flow_subject(flow.section, flow.investor_type),
            display_name=INVESTOR_LABELS.get(flow.investor_type, flow.investor_type))
        fact = _fact(fact_type=INVESTOR_FLOW_NET, subject=subject,
                     session_date=flow.period_end, value=flow.balance, unit="source_unit",
                     calculation=None,
                     evidence=(FactEvidenceRef(kind=EvidenceKind.RECORD, ref_id=flow.record_id,
                                               locator=f"flows.{flow.investor_type}.balance"),),
                     created_at=now, date_role=DateRole.PERIOD_END, known_at=known,
                     period_start=flow.period_start, period_end=flow.period_end,
                     note=f"published_date={flow.published_date};frequency=weekly;"
                          f"section={flow.section};state={flow.net_state}")
        if fact is not None:
            out.append(fact)
    return out


# ------------------------------------------------------------------ breadth history

def build_breadth_history_facts(aggregates: Sequence[BreadthAggregate],
                                facts_by_session: Mapping[str, Mapping[str, Fact]], *,
                                ad_ratio_sessions: int, now: datetime) -> List[Fact]:
    """25日騰落レシオ ＋ 値上がり比率の5/20セッション平均（揃うsessionだけ）。"""
    subject = market_subject()
    out: List[Fact] = []
    ordered = sorted(aggregates, key=lambda a: a.session_date)
    for idx, agg in enumerate(ordered):
        history = ordered[: idx + 1]
        # ---- 25日騰落レシオ
        n = ad_ratio_sessions
        ratio = advance_decline_ratio_n(history, n)
        if ratio is not None:
            window = history[-n:]
            inputs = [facts_by_session[a.session_date][t] for a in window
                      for t in (MARKET_ADVANCERS, MARKET_DECLINERS)
                      if a.session_date in facts_by_session
                      and t in facts_by_session[a.session_date]]
            if len(inputs) == 2 * n:
                limited = any(f.status is FactStatus.LIMITED_USE for f in inputs)
                calc = FactCalculation(
                    name=AD_RATIO_CALC[0], version=AD_RATIO_CALC[1],
                    inputs=tuple(f.fact_id for f in inputs),
                    parameters={"sessions": str(n), "session_date": agg.session_date,
                                "definition": "sum_advancers/sum_decliners*100"})
                fact = _fact(fact_type=AD_RATIO_25S, subject=subject,
                             session_date=agg.session_date, value=ratio, unit="pct",
                             calculation=calc, evidence=_fact_refs(inputs), created_at=now,
                             limited=limited, session_count=n)
                if fact is not None:
                    out.append(fact)
        # ---- 値上がり比率の平均
        for window_n, fact_type in ((5, ADVANCE_RATIO_5S_AVG), (20, ADVANCE_RATIO_20S_AVG)):
            avg = advance_ratio_average(history, window_n)
            if avg is None:
                continue
            inputs = [facts_by_session[a.session_date][ADVANCE_RATIO_PCT]
                      for a in history[-window_n:]
                      if a.session_date in facts_by_session
                      and ADVANCE_RATIO_PCT in facts_by_session[a.session_date]]
            if len(inputs) != window_n:
                continue
            limited = any(f.status is FactStatus.LIMITED_USE for f in inputs)
            calc = FactCalculation(
                name=BREADTH_AVERAGE_CALC[0], version=BREADTH_AVERAGE_CALC[1],
                inputs=tuple(f.fact_id for f in inputs),
                parameters={"window": str(window_n), "session_date": agg.session_date})
            fact = _fact(fact_type=fact_type, subject=subject, session_date=agg.session_date,
                         value=avg, unit="pct", calculation=calc,
                         evidence=_fact_refs(inputs), created_at=now, limited=limited,
                         session_count=window_n)
            if fact is not None:
                out.append(fact)
    return out


def facts_by_session_and_type(facts: Iterable[Fact], subject_id: str = MARKET_SUBJECT
                              ) -> Dict[str, Dict[str, Fact]]:
    out: Dict[str, Dict[str, Fact]] = {}
    for fact in facts:
        if fact.subject.subject_id != subject_id:
            continue
        out.setdefault(fact.time.primary_date, {})[fact.fact_type] = fact
    return out
