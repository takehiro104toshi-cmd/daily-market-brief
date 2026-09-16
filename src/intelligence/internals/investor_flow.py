"""Investor-type flow（Phase 3.5 §17 / §18 / §19）。

P2-H の `InvestorTypeFlowRecord`（**週次**）を Internals の正式入力にする。

temporal semantics（混同禁止）:
- `published_date`（公表日）… この事実が既知になった日。**known_at はここから決める**
  （公表日の `publication_hour_jst` 時点。それ以前の朝には使えない）
- `period_start` / `period_end`（対象期間）… Fact の primary_date は period_end
  （DateRole.PERIOD_END）
- frequency = weekly … **日次として語らない**（「本日外国人が買った」は禁止）

値は source schema に存在する実値（buy / sell / total / balance）だけを使う。
単位は source の公表単位のまま保持し、換算しない。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

FLOW_RULE = "investor_flow_weekly"
FLOW_FREQUENCY = "weekly"
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True, kw_only=True)
class WeeklyFlow:
    record_id: str
    section: str
    published_date: str
    period_start: str
    period_end: str
    investor_type: str
    balance: Optional[Decimal]
    buy: Optional[Decimal] = None
    sell: Optional[Decimal] = None
    total: Optional[Decimal] = None
    frequency: str = FLOW_FREQUENCY

    @property
    def net_state(self) -> str:
        if self.balance is None:
            return "UNKNOWN"
        if self.balance > 0:
            return "NET_BUY"
        if self.balance < 0:
            return "NET_SELL"
        return "FLAT"


def _decimal(token) -> Optional[Decimal]:
    if token is None:
        return None
    text = str(token).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _flows_of(row: Mapping) -> Mapping[str, Mapping[str, str]]:
    """SQLite行（flows_json）または canonical dict（flows）から投資部門別の値を取る。"""
    try:
        raw = row["flows_json"]
    except (KeyError, IndexError):
        raw = None
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    try:
        flows = row["flows"]
    except (KeyError, IndexError):
        return {}
    return flows or {}


def weekly_flows(rows: Iterable[Mapping], *, section: str,
                 investor_types: Sequence[str]) -> List[WeeklyFlow]:
    """light store の行 → WeeklyFlow（指定section・指定投資部門のみ）。"""
    out: List[WeeklyFlow] = []
    for row in rows:
        if section and str(row["section"]) != section:
            continue
        flows = _flows_of(row)
        for investor_type in investor_types:
            entry = flows.get(investor_type)
            if not entry:
                continue
            out.append(WeeklyFlow(
                record_id=str(row["record_id"]), section=str(row["section"]),
                published_date=str(row["published_date"]),
                period_start=str(row["period_start"]), period_end=str(row["period_end"]),
                investor_type=investor_type,
                balance=_decimal(entry.get("balance")), buy=_decimal(entry.get("buy")),
                sell=_decimal(entry.get("sell")), total=_decimal(entry.get("total")),
                frequency=str(row["frequency"] or FLOW_FREQUENCY)
                if "frequency" in row.keys() else FLOW_FREQUENCY))
    out.sort(key=lambda f: (f.period_end, f.published_date, f.investor_type))
    return out


def known_at_for(published_date: str, *, hour_jst: int) -> Optional[datetime]:
    """公表日の `hour_jst` 時点（JST）を UTC aware で返す（publication gating）。"""
    try:
        year, month, day = (int(p) for p in published_date.split("-"))
        return datetime(year, month, day, hour_jst, 0, tzinfo=JST).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def latest_published_by(flows: Sequence[WeeklyFlow], cutoff: datetime, *,
                        hour_jst: int) -> Dict[str, WeeklyFlow]:
    """cutoff時点で**公表済み**の最新週（投資部門ごと）。未公表の週は使わない。"""
    latest: Dict[str, WeeklyFlow] = {}
    for flow in flows:
        known = known_at_for(flow.published_date, hour_jst=hour_jst)
        if known is None or known > cutoff:
            continue
        current = latest.get(flow.investor_type)
        if current is None or (flow.period_end, flow.published_date) > (
                current.period_end, current.published_date):
            latest[flow.investor_type] = flow
    return latest


def observed_sections(rows: Iterable[Mapping]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        key = str(row["section"])
        counts[key] = counts.get(key, 0) + 1
    return counts
