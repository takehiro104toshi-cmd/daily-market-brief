"""イベント（決算発表予定・適時開示・マクロイベント）を今日／今週／今月で分類する。

マクロイベント（FOMC・日銀会合など）はスクレイピングせず、
config.yaml の `macro_events`（ユーザーが管理する公開スケジュール）を利用する。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import pandas as pd

from ..collectors.earnings import EarningsEvent
from ..collectors.tdnet import Disclosure
from .models import EventsBreakdown


def _days_until(date_str: Optional[str], reference: datetime) -> Optional[int]:
    if not date_str:
        return None
    try:
        parsed = pd.to_datetime(date_str)
        if pd.isna(parsed):
            return None
        return (parsed.date() - reference.date()).days
    except Exception:
        return None


def build_events_breakdown(
    earnings: List[EarningsEvent],
    disclosures: List[Disclosure],
    macro_events: List[dict],
    report_date: datetime,
) -> EventsBreakdown:
    breakdown = EventsBreakdown()

    for d in disclosures:
        breakdown.today.append(f"[適時開示] {d.time} {d.company}（{d.code}）: {d.title}")

    for e in earnings:
        days = _days_until(e.date, report_date)
        line = f"[決算発表予定] {e.name}（{e.ticker}）: {e.date}"
        if days is not None and days <= 0:
            breakdown.today.append(line)
        elif days is not None and days <= 7:
            breakdown.this_week.append(line)
        elif days is not None and days <= 30:
            breakdown.this_month.append(line)
        else:
            breakdown.this_month.append(line + "（時期未確定を含む）")

    for event in macro_events:
        label = event.get("label", "")
        date_str = event.get("date", "")
        days = _days_until(date_str, report_date)
        line = f"[マクロイベント] {date_str}: {label}"
        if days is not None and days <= 0:
            breakdown.today.append(line)
        elif days is not None and days <= 7:
            breakdown.this_week.append(line)
        elif days is not None and days <= 30:
            breakdown.this_month.append(line)

    return breakdown
