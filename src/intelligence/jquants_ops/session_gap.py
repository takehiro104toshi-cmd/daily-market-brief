"""Session gap detection（Phase 3.6 §8）。

Tokyo calendar（validated HolDiv=1）から **期待 session** を作り、canonical の保存状況と比較する:

    CURRENT           期待どおり保存済み（行数も十分）
    MISSING_SESSION   期待 session に行が無い
    PARTIAL_SESSION   行数が期待の partial_session_ratio 未満（取得途中の失敗等）
    STALE             latest_completed より保存最新が古い（＝末尾が MISSING）
    FUTURE_DATA       latest_completed より新しい session が保存されている（未完了 session の混入）
    CALENDAR_UNKNOWN  calendar が無く期待 session を決められない

missing session を黙って飛ばさない（全件を machine-readable に列挙する）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

CURRENT = "CURRENT"
MISSING_SESSION = "MISSING_SESSION"
PARTIAL_SESSION = "PARTIAL_SESSION"
STALE = "STALE"
FUTURE_DATA = "FUTURE_DATA"
CALENDAR_UNKNOWN = "CALENDAR_UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class SessionState:
    session_date: str
    status: str
    rows: int = 0
    expected_rows: int = 0

    def as_dict(self) -> Dict[str, object]:
        return {"session_date": self.session_date, "status": self.status, "rows": self.rows,
                "expected_rows": self.expected_rows}


@dataclass(frozen=True, kw_only=True)
class GapReport:
    dataset: str
    latest_completed: str
    latest_stored: str
    states: Tuple[SessionState, ...]
    overall: str                       # CURRENT / STALE / MISSING_SESSION / PARTIAL_SESSION / CALENDAR_UNKNOWN
    future_sessions: Tuple[str, ...] = ()
    expected_rows: int = 0

    @property
    def missing(self) -> List[str]:
        return [s.session_date for s in self.states if s.status == MISSING_SESSION]

    @property
    def partial(self) -> List[str]:
        return [s.session_date for s in self.states if s.status == PARTIAL_SESSION]

    @property
    def to_fetch(self) -> List[str]:
        return sorted(self.missing + self.partial)

    def as_dict(self) -> Dict[str, object]:
        return {
            "dataset": self.dataset, "latest_completed": self.latest_completed,
            "latest_stored": self.latest_stored, "overall": self.overall,
            "expected_sessions": len(self.states), "current": sum(
                1 for s in self.states if s.status == CURRENT),
            "missing": self.missing, "partial": self.partial,
            "future_sessions": list(self.future_sessions), "expected_rows": self.expected_rows,
            "gap_count": len(self.missing) + len(self.partial),
            "states_tail": [s.as_dict() for s in self.states[-5:]],
        }


def expected_rows_from(rows_by_session: Mapping[str, int]) -> int:
    """保存済み session の行数の中央値（期待行数の基準。推測ではなく観測から）。"""
    values = sorted(v for v in rows_by_session.values() if v > 0)
    if not values:
        return 0
    return values[len(values) // 2]


def detect_gaps(*, dataset: str, expected_sessions: Sequence[str],
                rows_by_session: Mapping[str, int], latest_completed: Optional[str],
                partial_ratio: Decimal = Decimal("0.90"),
                expected_rows: Optional[int] = None) -> GapReport:
    """期待 session × 保存行数 → GapReport。"""
    stored_sessions = sorted(s for s, n in rows_by_session.items() if n > 0)
    latest_stored = stored_sessions[-1] if stored_sessions else ""
    if not expected_sessions or not latest_completed:
        return GapReport(dataset=dataset, latest_completed=latest_completed or "",
                         latest_stored=latest_stored, states=(), overall=CALENDAR_UNKNOWN)
    baseline = expected_rows if expected_rows is not None else expected_rows_from(rows_by_session)
    threshold = int(Decimal(baseline) * partial_ratio) if baseline else 0
    states: List[SessionState] = []
    for session in sorted(expected_sessions):
        if session > latest_completed:
            continue
        rows = int(rows_by_session.get(session, 0))
        if rows <= 0:
            status = MISSING_SESSION
        elif threshold and rows < threshold:
            status = PARTIAL_SESSION
        else:
            status = CURRENT
        states.append(SessionState(session_date=session, status=status, rows=rows,
                                   expected_rows=baseline))
    future = tuple(s for s in stored_sessions if s > latest_completed)
    if any(s.status == MISSING_SESSION for s in states) and states and \
            states[-1].status == MISSING_SESSION:
        overall = STALE
    elif any(s.status == MISSING_SESSION for s in states):
        overall = MISSING_SESSION
    elif any(s.status == PARTIAL_SESSION for s in states):
        overall = PARTIAL_SESSION
    elif future:
        overall = FUTURE_DATA
    else:
        overall = CURRENT
    return GapReport(dataset=dataset, latest_completed=latest_completed,
                     latest_stored=latest_stored, states=tuple(states), overall=overall,
                     future_sessions=future, expected_rows=baseline)


def expected_sessions_for_window(trading_days: Sequence[str], latest_completed: str,
                                 window: int) -> List[str]:
    """latest_completed 以前の営業日を末尾から window 件。"""
    completed = [d for d in trading_days if d <= latest_completed]
    return completed[-window:]
