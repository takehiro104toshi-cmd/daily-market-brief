"""Backfill decision（Phase 3.5 §29 / §35）。

pilot の**実測**（1 sessionあたりの request / 行数 / bytes / 秒）から、
full universe × 必要履歴 の records / API calls / runtime / disk / rebuild time を
外挿し、推奨を1つ返す:

    FULL_BACKFILL_RECOMMENDED / ROLLING_WINDOW_RECOMMENDED /
    ON_DEMAND_RECOMMENDED / DEFER

今回は自動で5年backfillを**しない**（見積りと提案のみ）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

FULL = "FULL_BACKFILL_RECOMMENDED"
ROLLING = "ROLLING_WINDOW_RECOMMENDED"
ON_DEMAND = "ON_DEMAND_RECOMMENDED"
DEFER = "DEFER"

SESSIONS_PER_YEAR = 244            # P2-H実測（2025-09-01〜2026-09-01: 244セッション）
ROLLING_WINDOW_SESSIONS = 60       # 25日騰落レシオ＋20日平均＋余裕（朝の運用に必要な最小）
FULL_YEARS = 5


@dataclass(frozen=True, kw_only=True)
class Measured:
    date_mode_available: bool
    universe_size: int
    rows_per_session: float
    requests_per_session: float
    seconds_per_session_fetch: float
    seconds_per_session_aggregate: float
    canonical_bytes_per_row: float
    sqlite_bytes_per_row: float
    rebuild_seconds_per_row: float
    sessions_measured: int


def _plan(m: Measured, sessions: int) -> Dict[str, object]:
    rows = m.rows_per_session * sessions
    return {
        "sessions": sessions,
        "records": int(rows),
        "api_calls": int(m.requests_per_session * sessions) if m.date_mode_available
        else m.universe_size,
        "fetch_runtime_minutes": round(m.seconds_per_session_fetch * sessions / 60, 1),
        "aggregate_runtime_minutes": round(m.seconds_per_session_aggregate * sessions / 60, 1),
        "canonical_disk_mb": round(rows * m.canonical_bytes_per_row / 1e6, 1),
        "sqlite_disk_mb": round(rows * m.sqlite_bytes_per_row / 1e6, 1),
        "rebuild_minutes": round(rows * m.rebuild_seconds_per_row / 60, 1),
    }


def estimate(m: Measured) -> Dict[str, object]:
    full_sessions = SESSIONS_PER_YEAR * FULL_YEARS
    full = _plan(m, full_sessions)
    rolling = _plan(m, ROLLING_WINDOW_SESSIONS)
    daily = _plan(m, 1)
    if not m.date_mode_available:
        recommendation, reason = DEFER, (
            "date指定取得が使えず、全銘柄をcode指定で取ると1日あたり"
            f"{m.universe_size}リクエストになる。Light契約での定常運用に耐えないため保留")
    elif full["fetch_runtime_minutes"] <= 60 and full["canonical_disk_mb"] <= 2000:
        recommendation, reason = FULL, "1時間・2GB以内で5年分を取得できる見積り"
    else:
        recommendation, reason = ROLLING, (
            "朝の運用（騰落レシオ25日・20日平均）に必要なのは直近"
            f"{ROLLING_WINDOW_SESSIONS}セッションで、日次1リクエスト・数秒で維持できる。"
            "5年分は52週高値/安値など用途が確定してから別途判断する")
    return {
        "measured": {
            "date_mode_available": m.date_mode_available,
            "universe_size": m.universe_size,
            "rows_per_session": round(m.rows_per_session, 1),
            "requests_per_session": round(m.requests_per_session, 2),
            "seconds_per_session_fetch": round(m.seconds_per_session_fetch, 2),
            "seconds_per_session_aggregate": round(m.seconds_per_session_aggregate, 3),
            "canonical_bytes_per_row": round(m.canonical_bytes_per_row, 1),
            "sqlite_bytes_per_row": round(m.sqlite_bytes_per_row, 1),
            "rebuild_seconds_per_row": round(m.rebuild_seconds_per_row, 6),
            "sessions_measured": m.sessions_measured,
        },
        "full_universe_5y": full,
        "rolling_window": rolling,
        "daily_operation": daily,
        "recommendation": recommendation,
        "reason": reason,
        "not_done_now": "full 5-year backfill was NOT executed (estimate only)",
    }
