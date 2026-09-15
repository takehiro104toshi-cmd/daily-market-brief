"""Request budget（Phase 3.6 §19）。

scenario ごとの J-Quants リクエスト数（date 指定・1 session = 1 リクエストを前提。run #20 実測）。
"""
from __future__ import annotations

from typing import Dict

from .rolling_window import WindowPolicy


def request_budget(policy: WindowPolicy, *, seed_sessions: int = 0,
                   repair_missing_sessions: int = 3, event_codes: int = 20,
                   master_snapshots_in_seed: int = 0) -> Dict[str, Dict[str, int]]:
    seed = seed_sessions or policy.seed_sessions
    masters = master_snapshots_in_seed or (seed // 5 + 1)
    normal = {"topix": 1, "daily_bars": 1, "investor_types": 1, "equities_earnings_cal": 1,
              "markets_calendar": 0, "listed_master": 0, "fins_summary": 0}
    weekly = {"markets_calendar": 1, "listed_master": 1}
    event = {"fins_summary": event_codes}
    repair = {"daily_bars": repair_missing_sessions, "listed_master": 1}
    initial = {"markets_calendar": 1, "listed_master": masters, "daily_bars": seed,
               "investor_types": 1, "equities_earnings_cal": 1, "topix": 1}
    def total(d):
        return sum(d.values())
    return {
        "normal_morning": dict(normal, total=total(normal)),
        "weekly_refresh": dict(weekly, total=total(weekly)),
        "master_refresh": {"listed_master": 1, "total": 1},
        "event_refresh": dict(event, total=total(event)),
        "repair_day": dict(repair, total=total(repair)),
        "initial_seed": dict(initial, total=total(initial)),
    }
