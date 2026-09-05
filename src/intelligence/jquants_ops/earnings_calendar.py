"""Earnings calendar strategy（Phase 3.6 §15）。

- 取得範囲: 今日〜 +90 日（Morning Compass の event_proximity は 90 日視野）
- refresh: 毎朝 1 リクエスト（予定は変更され得る）
- known_at: 取得時刻（公表済みの予定だけが返る。未来の予定日そのものは look-ahead ではない）
- revision: record_id = ern_<code>_<date>。日程変更は**新しい record** になり、旧 record は
  canonical に残る（append-only）。消費側は code ごとに retrieved_at が最新の record を使う
  （`latest_schedule_per_code`）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Iterable, List, Mapping


def plan_earnings_refresh(*, today: date, days_ahead: int = 90) -> Dict[str, object]:
    return {"params": {"from": today.isoformat(), "to": (today + timedelta(days=days_ahead)).isoformat()},
            "requests": 1, "frequency": "every morning"}


def latest_schedule_per_code(rows: Iterable[Mapping]) -> Dict[str, Mapping]:
    """code ごとに retrieved_at（provenance）が最新の予定 record を選ぶ（旧予定は残す）。"""
    latest: Dict[str, Mapping] = {}
    for row in rows:
        code = str(row.get("code", ""))
        retrieved = str((row.get("provenance") or {}).get("retrieved_at", ""))
        current = latest.get(code)
        if current is None or retrieved >= str((current.get("provenance") or {}).get("retrieved_at", "")):
            latest[code] = row
    return latest


def strategy() -> Dict[str, object]:
    return {
        "range": "today .. today+90d", "refresh": "every morning (1 request)",
        "known_at": "retrieved_at (published schedules only)",
        "revision": "new record per (code, date); old kept; consumer takes latest retrieved_at per code",
        "look_ahead": "future event dates are published information, not future market data",
    }
