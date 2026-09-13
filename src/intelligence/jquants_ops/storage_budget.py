"""Storage lifecycle / budget（Phase 3.6 §17 / §18）。

run #20 実測（45 session）から日次・月次・年次の増分を store 別に推定する。
canonical は append-only（rolling window は削除ではない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

SESSIONS_PER_MONTH = 20
SESSIONS_PER_YEAR = 244


@dataclass(frozen=True)
class MeasuredStorage:
    """run #20 の実測値（1 session あたり）。"""

    price_rows_per_session: float = 4441.7
    canonical_bytes_per_price_row: float = 786.1
    light_sqlite_bytes_per_price_row: float = 203.6
    internals_canonical_bytes_per_session: float = 0.0      # manifests+aggregates（実測で上書き）
    internals_sqlite_bytes_per_session: float = 21192704 / 45
    facts_per_session: float = 4123 / 45
    facts_sqlite_bytes_per_fact: float = 6418432 / 4288
    facts_canonical_bytes_per_fact: float = 1400.0            # 概算（Fact as_dict JSON）
    contexts_per_session: float = 535 / 45
    contexts_sqlite_bytes_per_context: float = 622592 / 594
    contexts_canonical_bytes_per_context: float = 1200.0
    master_snapshot_bytes: float = 4441 * 900.0               # 週次 snapshot 1 回分（canonical）


def _mb(value: float) -> float:
    return round(value / 1e6, 2)


def storage_budget(m: MeasuredStorage = MeasuredStorage()) -> Dict[str, object]:
    per_session = {
        "canonical_prices": m.price_rows_per_session * m.canonical_bytes_per_price_row,
        "light_sqlite": m.price_rows_per_session * m.light_sqlite_bytes_per_price_row,
        "internals_canonical": m.internals_canonical_bytes_per_session,
        "internals_sqlite": m.internals_sqlite_bytes_per_session,
        "facts_canonical": m.facts_per_session * m.facts_canonical_bytes_per_fact,
        "facts_sqlite": m.facts_per_session * m.facts_sqlite_bytes_per_fact,
        "contexts_canonical": m.contexts_per_session * m.contexts_canonical_bytes_per_context,
        "contexts_sqlite": m.contexts_per_session * m.contexts_sqlite_bytes_per_context,
    }
    weekly_master_per_session = m.master_snapshot_bytes / 5
    per_session["master_canonical"] = weekly_master_per_session
    total = sum(per_session.values())

    def scale(n: int) -> Dict[str, float]:
        out = {k: _mb(v * n) for k, v in per_session.items()}
        out["total"] = _mb(total * n)
        return out

    return {
        "per_session_bytes": {k: int(v) for k, v in per_session.items()},
        "daily_mb": scale(1), "monthly_mb": scale(SESSIONS_PER_MONTH),
        "annual_mb": scale(SESSIONS_PER_YEAR),
        "retention": {"canonical": "append-only, never deleted by the rolling window",
                      "sqlite": "rebuildable from canonical; keep all rows (rolling = calculation window)",
                      "active_calculation_window": "60 sessions (config jquants_ops)"},
        "note": "1 year of daily operation ≈ total below; a 5-year backfill is NOT implied",
    }
