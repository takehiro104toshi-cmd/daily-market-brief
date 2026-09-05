"""Investor-type flow update strategy（Phase 3.6 §13）。

週次公表（PubDate）の semantics を維持しつつ、**毎朝 1 リクエスト**で差分だけ取る:

    latest stored period_end
      → from = period_end − lookback（公表遅延・訂正の余裕）, to = today
      → 応答のうち record_id（section × period）が既知の行は append されない（冪等）
      → 新規公表週だけが追加される

publication 前の週は Fact（known_at = PubDate 16:00 JST）として朝に使われない。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional, Tuple

from ..market.jquants_light_store import JQuantsLightStore

MODE_SEED = "SEED"
MODE_CHECK = "CHECK"


def latest_stored_period(light: JQuantsLightStore, section: str = "") -> Tuple[str, str]:
    rows = light.investor_flows_published_by("9999-12-31", section)
    if not rows:
        return "", ""
    latest = max(rows, key=lambda r: (r["period_end"], r["published_date"]))
    return str(latest["period_end"]), str(latest["published_date"])


def plan_flow_refresh(light: JQuantsLightStore, *, today: date, section: str = "",
                      lookback_days: int = 14, seed_days: int = 60) -> Dict[str, object]:
    period_end, published = latest_stored_period(light, section)
    if not period_end:
        start = today - timedelta(days=seed_days)
        return {"mode": MODE_SEED, "params": {"from": start.isoformat(), "to": today.isoformat()},
                "latest_stored_period_end": "", "latest_stored_published": "", "requests": 1}
    start = date.fromisoformat(period_end) - timedelta(days=lookback_days)
    return {"mode": MODE_CHECK, "params": {"from": start.isoformat(), "to": today.isoformat()},
            "latest_stored_period_end": period_end, "latest_stored_published": published,
            "requests": 1, "rule": "append new periods only (record_id idempotent)"}


def strategy() -> Dict[str, object]:
    return {
        "frequency": "WEEKLY publication; checked once per morning with 1 request",
        "full_history_each_morning": False,
        "known_at": "PubDate 16:00 JST (config investor_flow.publication_hour_jst)",
        "pre_publication_use": "forbidden (facts carry known_at; morning snapshot filters)",
        "daily_wording": "forbidden (language:weekly_flow_as_daily)",
    }
