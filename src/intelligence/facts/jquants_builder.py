"""J-Quants Light records → Fact（Phase 3-A STEP 7-D/24）。

**Fact Layer ≠ Data Duplication**（STEP 25）: P2-Hのrecordを無条件でFactへ複製しない。
Intelligence用途が説明できるものだけをatomic factにする。

採用するのは3種:
- `earnings_schedule` … 「決算発表予定日」（Morning Brief / Watchlistが
  「決算まで何日」を計算するため）
- `reported_financial_value` … 開示済みの**実績**値
- `company_forecast_value` … **会社予想**値（実績と混同しない）

security master / daily price / calendar / investor flow は**Factへ複製しない**:
- security masterはFactではなく参照マスタ（subjectの属性）
- 個別銘柄の日次価格はMorning Compassの現行スコープ外（必要になった時点で
  market builderと同じ規律で追加する）
- calendarはsession判定の基盤であってFactではない
- investor flowは**週次**のためMorning Compassのdaily factとしては扱わず、
  期間Factが必要になった段階で `period_end` を主日付として追加する
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, List, Mapping, Optional, Sequence

from .model import (
    ConflictState,
    DateRole,
    EvidenceKind,
    Fact,
    FactEvidenceRef,
    FactStatus,
    FactSubject,
    FactTimeContext,
    FactValue,
    make_fact_id,
    value_token,
)

EARNINGS_SCHEDULE = "earnings_schedule"
REPORTED_FINANCIAL_VALUE = "reported_financial_value"
COMPANY_FORECAST_VALUE = "company_forecast_value"

#: 実績としてFact化する項目（record属性名 → metric名・単位）
REPORTED_METRICS = (
    ("net_sales", "net_sales", "jpy"),
    ("operating_profit", "operating_profit", "jpy"),
    ("ordinary_profit", "ordinary_profit", "jpy"),
    ("net_profit", "net_profit", "jpy"),
    ("eps", "eps", "jpy_per_share"),
)
#: 会社予想としてFact化する項目（**実績と別fact_type**にする）
FORECAST_METRICS = (
    ("forecast_net_sales", "net_sales", "jpy"),
    ("forecast_operating_profit", "operating_profit", "jpy"),
    ("forecast_net_profit", "net_profit", "jpy"),
    ("forecast_eps", "eps", "jpy_per_share"),
)


def _security_subject(record) -> FactSubject:
    return FactSubject(subject_type="security", subject_id=record.security_id,
                       display_name=getattr(record, "company_name", "") or record.code)


def _to_decimal(token: str) -> Optional[Decimal]:
    from ..market.jquants_records import to_decimal
    return to_decimal(token)


def _evidence(record, locator: str) -> FactEvidenceRef:
    provenance = record.provenance
    return FactEvidenceRef(
        kind=EvidenceKind.RECORD, ref_id=record.record_id,
        locator=f"{provenance.endpoint}#{locator}",
        qa_decision="")


def _known_at(record) -> Optional[datetime]:
    """このrecordが既知になった時刻（取得時刻）。

    決算予定・開示値は**公表されて初めて既知**になる。開示日時が取れるものは
    それを使い、無ければ取得時刻で近似する（未来情報の混入は起きない方向の近似）。
    """
    disclosed = getattr(record, "disclosed_date", "")
    if disclosed:
        try:
            year, month, day = (int(p) for p in disclosed.split("-"))
            # 開示日の東京クローズ後（JST 15:30 = UTC 06:30）を既知時刻とする
            return datetime(year, month, day, 6, 30, tzinfo=timezone.utc)
        except ValueError:
            pass
    retrieved = record.provenance.retrieved_at
    if retrieved:
        try:
            return datetime.fromisoformat(retrieved)
        except ValueError:
            return None
    return None


def build_earnings_schedule_facts(
    records: Iterable, *, now: Optional[datetime] = None
) -> List[Fact]:
    """決算発表予定 → Fact（「決算まで何日」の計算基盤）。"""
    created_at = now or datetime.now(timezone.utc)
    facts: List[Fact] = []
    for record in records:
        if not record.announcement_date:
            continue
        subject = _security_subject(record)
        text = f"{record.fiscal_year}Q{record.fiscal_quarter}".strip("Q")
        facts.append(Fact(
            fact_id=make_fact_id(
                fact_type=EARNINGS_SCHEDULE, subject=subject,
                primary_date=record.announcement_date,
                value_token=value_token(None, text or record.announcement_date)),
            fact_type=EARNINGS_SCHEDULE, subject=subject,
            value=FactValue(text_value=text or record.announcement_date),
            time=FactTimeContext(
                primary_date=record.announcement_date, date_role=DateRole.EVENT_DATE,
                known_at=_known_at(record)),
            evidence=(_evidence(record, "Date"),),
            status=FactStatus.USABLE, conflict_state=ConflictState.UNKNOWN,
            source_ids=(record.provenance.source,), created_at=created_at))
    return facts


def _financial_facts(record, metrics, fact_type: str, created_at: datetime,
                     date_role: DateRole) -> List[Fact]:
    subject = _security_subject(record)
    primary_date = record.disclosed_date
    if not primary_date:
        return []
    out: List[Fact] = []
    for attribute, metric, unit in metrics:
        token = getattr(record, attribute, "")
        value = _to_decimal(token)
        if value is None:
            continue                      # 欠測はFactを作らない（0で埋めない）
        out.append(Fact(
            fact_id=make_fact_id(
                fact_type=fact_type, subject=subject, primary_date=primary_date,
                value_token=f"{metric}|{value_token(value)}"),
            fact_type=fact_type, subject=subject,
            value=FactValue(value=value, unit=unit, currency="JPY"),
            time=FactTimeContext(
                primary_date=primary_date, date_role=date_role,
                known_at=_known_at(record),
                period_start=record.period_start, period_end=record.period_end),
            evidence=(_evidence(record, attribute),),
            status=FactStatus.USABLE, conflict_state=ConflictState.UNKNOWN,
            source_ids=(record.provenance.source,), created_at=created_at,
            note=f"metric={metric}"))
    return out


def build_financial_facts(
    records: Iterable, *, now: Optional[datetime] = None
) -> List[Fact]:
    """財務サマリー → 実績Fact＋会社予想Fact（**別fact_typeで分離**）。"""
    created_at = now or datetime.now(timezone.utc)
    facts: List[Fact] = []
    for record in records:
        facts.extend(_financial_facts(
            record, REPORTED_METRICS, REPORTED_FINANCIAL_VALUE, created_at,
            DateRole.PUBLICATION_DATE))
        facts.extend(_financial_facts(
            record, FORECAST_METRICS, COMPANY_FORECAST_VALUE, created_at,
            DateRole.PUBLICATION_DATE))
    return facts
