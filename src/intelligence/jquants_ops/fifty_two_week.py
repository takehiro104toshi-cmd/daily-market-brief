"""52週高値 / 安値の判断（Phase 3.6 §27）。

Phase 3.5 で DEFER した機能を、必要履歴・storage・requests・Compass value から判定する。
この機能だけを理由に 5 年 backfill はしない。
"""
from __future__ import annotations

from typing import Dict

IMPLEMENT_LATER = "IMPLEMENT_LATER"
ON_DEMAND = "ON_DEMAND"
DEFER = "DEFER"
NOT_WORTH_COST = "NOT_WORTH_COST"

REQUIRED_SESSIONS = 250          # 52週 ≈ 250 営業日


def decision(*, stored_sessions: int, rows_per_session: float = 4441.7,
             canonical_bytes_per_row: float = 786.1, seconds_per_session_fetch: float = 4.77,
             active_window: int = 60) -> Dict[str, object]:
    missing = max(0, REQUIRED_SESSIONS - stored_sessions)
    rows = missing * rows_per_session
    return {
        "required_history_sessions": REQUIRED_SESSIONS,
        "stored_sessions": stored_sessions,
        "missing_sessions_for_one_time_seed": missing,
        "one_time_seed": {"requests": missing, "rows": int(rows),
                          "canonical_mb": round(rows * canonical_bytes_per_row / 1e6, 1),
                          "fetch_minutes": round(missing * seconds_per_session_fetch / 60, 1)},
        "accrual_path": {"mechanism": "daily incremental keeps canonical append-only; "
                                      "history accrues 1 session per trading day",
                         "trading_days_until_available": missing},
        "compass_value": "MEDIUM: new-high/new-low counts are a recognised breadth signal, but no "
                         "Compass DNA rule references them yet (no INTERPRETIVE claim possible)",
        "decision": IMPLEMENT_LATER,
        "reason": "history accrues naturally under the rolling strategy (canonical never deleted); "
                  "implement once >= 250 sessions are stored or a Compass DNA v2 rule needs it; "
                  "no 5-year backfill for this feature",
        "active_window_unchanged": active_window,
    }
