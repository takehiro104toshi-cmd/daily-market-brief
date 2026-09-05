"""Market Fact Builder（Phase 3-A STEP 9/10/11/16）。

market observationsから**決定論的**にatomic factを生成する。

規律:
- **session-aware**: calendar dayとtrading sessionを混同しない。前営業日・N営業日
  リターン・移動平均はすべて**観測が存在するセッション列**の上で数える。
- **NO FABRICATED CALCULATION**: 必要セッション数が足りなければFactを作らない。
- **QA統合**: REJECT判定のevidenceからproduction Factを作らない。LIMITED_USEは
  status=LIMITED_USE として明示的に区別する（黙って通常Fact扱いしない）。
- **provenance必須**: 全FactがObservation（→RawItem→FetchAttempt）へ辿れる。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import calculations as calc
from .model import (
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

#: Morning Compassのcore fact types（STEP 7/11。増やすことが目的ではない）
INDEX_CLOSE = "index_close"
INDEX_CHANGE = "index_change"
INDEX_CHANGE_PCT = "index_change_pct"
RETURN_5D = "return_5session_pct"
RETURN_20D = "return_20session_pct"
MOVING_AVERAGE_25 = "moving_average_25session"
DISTANCE_FROM_MA25 = "distance_from_ma25_pct"
YIELD_LEVEL = "yield_level"
YIELD_CHANGE = "yield_change"
FX_LEVEL = "fx_level"
FX_CHANGE = "fx_change"
FX_CHANGE_PCT = "fx_change_pct"
YIELD_SPREAD = "yield_spread"
NT_RATIO = "nt_ratio"

#: QA判定 → Fact生成可否（REJECTからproduction Factを作らない）
_QA_BLOCKS = {"reject"}
_QA_LIMITED = {"limited_use"}

#: 系列の性質ごとのfact type（レベル・変化・変化率）
_LEVEL_TYPES = {
    "index": (INDEX_CLOSE, INDEX_CHANGE, INDEX_CHANGE_PCT),
    "rates": (YIELD_LEVEL, YIELD_CHANGE, None),      # 金利は「%変化」を作らない（pt差が意味）
    "fx": (FX_LEVEL, FX_CHANGE, FX_CHANGE_PCT),
}


@dataclass(frozen=True, kw_only=True)
class SessionPoint:
    """1セッション分の観測（builderの入力。storeに依存しない形にする）。"""

    trading_date: str
    value: Optional[Decimal]
    observation_id: str
    as_of: Optional[datetime] = None
    source_id: str = ""
    qa_decision: str = ""
    unit: str = ""
    currency: str = ""

    @property
    def usable(self) -> bool:
        return self.value is not None and self.qa_decision.lower() not in _QA_BLOCKS


def _kind_of(series_id: str) -> str:
    return series_id.split(":", 1)[0] if ":" in series_id else "index"


def _status_for(decisions: Iterable[str]) -> FactStatus:
    lowered = [d.lower() for d in decisions if d]
    if any(d in _QA_BLOCKS for d in lowered):
        return FactStatus.UNUSABLE
    if any(d in _QA_LIMITED for d in lowered):
        return FactStatus.LIMITED_USE
    return FactStatus.USABLE


def _weakest_decision(decisions: Iterable[str]) -> str:
    order = {"reject": 0, "limited_use": 1, "accept_with_warnings": 2, "accept": 3}
    known = [d.lower() for d in decisions if d]
    if not known:
        return ""
    return min(known, key=lambda d: order.get(d, 4))


def _ref(point: SessionPoint) -> FactEvidenceRef:
    return FactEvidenceRef(
        kind=EvidenceKind.OBSERVATION, ref_id=point.observation_id,
        locator=f"series={point.trading_date}", qa_decision=point.qa_decision)


def _known_at(point: SessionPoint) -> Optional[datetime]:
    """この観測が既知になった時刻。

    market観測は `as_of`（セッションクローズ時点）をもって既知とする。
    取得時刻ではなく**値が確定した時点**を使うのは、朝の再現時に
    「その時点で市場が知り得た情報」を基準にするため。
    """
    return point.as_of


def _make(
    *, fact_type: str, subject: FactSubject, points: Sequence[SessionPoint],
    value: Optional[Decimal], unit: str, primary: SessionPoint,
    calculation: Optional[FactCalculation] = None, created_at: datetime,
    currency: str = "", session_count: int = 0,
) -> Optional[Fact]:
    """Fact 1件を組み立てる。値が無ければ**作らない**（FAIL-CLOSED）。"""
    if value is None:
        return None
    decisions = [p.qa_decision for p in points]
    status = _status_for(decisions)
    if status is FactStatus.UNUSABLE:
        return None                      # REJECT由来はproduction Factにしない
    fact_value = FactValue(value=value, unit=unit, currency=currency)
    method = calculation.method if calculation else ""
    return Fact(
        fact_id=make_fact_id(fact_type=fact_type, subject=subject,
                             primary_date=primary.trading_date,
                             value_token=value_token(value),
                             calculation_method=method),
        fact_type=fact_type, subject=subject, value=fact_value,
        time=FactTimeContext(
            primary_date=primary.trading_date, date_role=DateRole.TRADING_DATE,
            as_of=primary.as_of, known_at=_known_at(primary),
            session_count=session_count),
        evidence=tuple(_ref(p) for p in points),
        calculation=calculation, status=status,
        conflict_state=ConflictState.UNKNOWN,
        source_ids=tuple(sorted({p.source_id for p in points if p.source_id})),
        qa_decision=_weakest_decision(decisions), created_at=created_at)


def build_series_facts(
    series_id: str,
    points: Sequence[SessionPoint],
    *,
    display_name: str = "",
    now: Optional[datetime] = None,
    ma_window: int = 25,
) -> List[Fact]:
    """1系列のsession列 → core facts（STEP 11）。

    `points` は **trading_date昇順**の観測列（欠測セッションは含めない）。
    """
    created_at = now or datetime.now(timezone.utc)
    usable = [p for p in points if p.usable]
    if not usable:
        return []
    subject = FactSubject(subject_type="series", subject_id=series_id,
                          display_name=display_name)
    latest = usable[-1]
    unit = latest.unit
    currency = latest.currency
    kind = _kind_of(series_id)
    level_type, change_type, change_pct_type = _LEVEL_TYPES.get(
        kind, _LEVEL_TYPES["index"])

    facts: List[Fact] = []

    # --- level（当日終値・利回り水準・為替水準）
    level = _make(fact_type=level_type, subject=subject, points=[latest],
                  value=latest.value, unit=unit, primary=latest,
                  created_at=created_at, currency=currency, session_count=1)
    if level:
        facts.append(level)

    # --- previous session change / change pct（**連続する営業日**でのみ）
    if len(usable) >= 2:
        previous = usable[-2]
        pair = [previous, latest]
        change = _make(
            fact_type=change_type, subject=subject, points=pair,
            value=calc.change_abs(latest.value, previous.value),
            unit=("pct_point" if kind == "rates" else unit), primary=latest,
            calculation=FactCalculation(
                name=calc.CHANGE_ABS[0], version=calc.CHANGE_ABS[1],
                inputs=(previous.observation_id, latest.observation_id),
                parameters={"previous_trading_date": previous.trading_date}),
            created_at=created_at, currency=currency, session_count=2)
        if change:
            facts.append(change)
        if change_pct_type:
            change_pct = _make(
                fact_type=change_pct_type, subject=subject, points=pair,
                value=calc.return_pct(latest.value, previous.value), unit="pct",
                primary=latest,
                calculation=FactCalculation(
                    name=calc.RETURN_PCT[0], version=calc.RETURN_PCT[1],
                    inputs=(previous.observation_id, latest.observation_id),
                    parameters={"previous_trading_date": previous.trading_date}),
                created_at=created_at, session_count=2)
            if change_pct:
                facts.append(change_pct)

    # --- N-session returns（セッション数で数える。calendar dayで数えない）
    for sessions, fact_type in ((5, RETURN_5D), (20, RETURN_20D)):
        if len(usable) < sessions + 1:
            continue                      # 不足なら**作らない**
        base = usable[-(sessions + 1)]
        window = [base, latest]
        fact = _make(
            fact_type=fact_type, subject=subject, points=window,
            value=calc.return_pct(latest.value, base.value), unit="pct",
            primary=latest,
            calculation=FactCalculation(
                name=calc.RETURN_PCT[0], version=calc.RETURN_PCT[1],
                inputs=(base.observation_id, latest.observation_id),
                parameters={"sessions": str(sessions),
                            "base_trading_date": base.trading_date}),
            created_at=created_at, session_count=sessions + 1)
        if fact:
            facts.append(fact)

    # --- 25セッション移動平均と乖離率（indexのみ。金利/為替のMAはCompass未使用）
    if kind == "index" and len(usable) >= ma_window:
        window_points = usable[-ma_window:]
        ma_value = calc.moving_average([p.value for p in window_points], ma_window)
        ma_fact = _make(
            fact_type=MOVING_AVERAGE_25, subject=subject, points=window_points,
            value=ma_value, unit=unit, primary=latest,
            calculation=FactCalculation(
                name=calc.MOVING_AVERAGE[0], version=calc.MOVING_AVERAGE[1],
                inputs=tuple(p.observation_id for p in window_points),
                parameters={"window_sessions": str(ma_window)}),
            created_at=created_at, currency=currency, session_count=ma_window)
        if ma_fact:
            facts.append(ma_fact)
            distance = _make(
                fact_type=DISTANCE_FROM_MA25, subject=subject, points=window_points,
                value=calc.distance_from_ma_pct(latest.value, ma_value), unit="pct",
                primary=latest,
                calculation=FactCalculation(
                    name=calc.DISTANCE_FROM_MA_PCT[0],
                    version=calc.DISTANCE_FROM_MA_PCT[1],
                    inputs=(ma_fact.fact_id, latest.observation_id),
                    parameters={"window_sessions": str(ma_window)}),
                created_at=created_at, session_count=ma_window)
            if distance:
                facts.append(distance)
    return facts


def build_cross_series_fact(
    fact_type: str,
    left_series: str,
    right_series: str,
    left_points: Sequence[SessionPoint],
    right_points: Sequence[SessionPoint],
    *,
    subject_id: str,
    unit: str,
    calculation_name: Tuple[str, str],
    display_name: str = "",
    now: Optional[datetime] = None,
) -> Optional[Fact]:
    """2系列のcross fact（NT倍率・金利スプレッド）。

    **同一trading_dateの入力が揃っている場合のみ**生成する。
    片側だけ新しい日付があっても前日値で埋めない（P2-G.2で確立した規律）。
    """
    created_at = now or datetime.now(timezone.utc)
    right_by_date = {p.trading_date: p for p in right_points if p.usable}
    pairs = [(l, right_by_date[l.trading_date])
             for l in left_points if l.usable and l.trading_date in right_by_date]
    if not pairs:
        return None
    left, right = pairs[-1]
    if calculation_name[0] == calc.NT_RATIO[0]:
        value = calc.nt_ratio(left.value, right.value)
    else:
        value = calc.yield_spread(left.value, right.value)
    subject = FactSubject(subject_type="series", subject_id=subject_id,
                          display_name=display_name)
    return _make(
        fact_type=fact_type, subject=subject, points=[left, right], value=value,
        unit=unit, primary=left,
        calculation=FactCalculation(
            name=calculation_name[0], version=calculation_name[1],
            inputs=(left.observation_id, right.observation_id),
            parameters={"left_series": left_series, "right_series": right_series,
                        "trading_date": left.trading_date}),
        created_at=created_at, session_count=1)


def build_history_facts(
    series_id: str,
    points: Sequence[SessionPoint],
    *,
    sessions: int,
    display_name: str = "",
    now: Optional[datetime] = None,
    ma_window: int = 25,
) -> List[Fact]:
    """直近 `sessions` 本の**各セッション時点**のFactを生成する（STEP 19/22）。

    各セッションについて「そのセッションまでの観測だけ」を入力にしてFactを作る。
    未来の観測を一切見ないため、生成物はそのままlook-ahead-freeなsnapshot素材になる。

    `fact_id` は決定論的なので、期間が重なる再実行でも重複は生じない（冪等）。
    """
    usable = [p for p in points if p.usable]
    if not usable:
        return []
    out: List[Fact] = []
    seen: set = set()
    start_index = max(0, len(usable) - sessions)
    for end_index in range(start_index, len(usable)):
        window = usable[: end_index + 1]
        for fact in build_series_facts(series_id, window, display_name=display_name,
                                       now=now, ma_window=ma_window):
            if fact.fact_id not in seen:
                seen.add(fact.fact_id)
                out.append(fact)
    return out


def build_cross_series_history_facts(
    fact_type: str,
    left_series: str,
    right_series: str,
    left_points: Sequence[SessionPoint],
    right_points: Sequence[SessionPoint],
    *,
    subject_id: str,
    unit: str,
    calculation_name: Tuple[str, str],
    sessions: int,
    display_name: str = "",
    now: Optional[datetime] = None,
) -> List[Fact]:
    """cross fact（NT倍率・スプレッド）を直近 `sessions` 本ぶん生成する。"""
    right_by_date = {p.trading_date: p for p in right_points if p.usable}
    paired_dates = [p.trading_date for p in left_points
                    if p.usable and p.trading_date in right_by_date]
    out: List[Fact] = []
    seen: set = set()
    for trading_date in paired_dates[-sessions:]:
        left_slice = [p for p in left_points if p.trading_date <= trading_date]
        right_slice = [p for p in right_points if p.trading_date <= trading_date]
        fact = build_cross_series_fact(
            fact_type, left_series, right_series, left_slice, right_slice,
            subject_id=subject_id, unit=unit, calculation_name=calculation_name,
            display_name=display_name, now=now)
        if fact and fact.fact_id not in seen:
            seen.add(fact.fact_id)
            out.append(fact)
    return out

