"""Rolling window strategy（Phase 3.6 §5 / §17）。

Phase 3.5 実測（60 session ≈ 266k 行 ≈ 210 MB ≈ 4.8分 seed、daily 1リクエスト＋数秒）を基準に、

- seed window        : 初期構築で取る session 数（active + safety buffer）
- retention          : canonical は **append-only で削除しない**（rolling ≠ 削除）
- calculation window : 朝の指標計算に使う直近 session 数
- safety buffer      : corporate action / 欠落 session / 部分 session の余裕

を分離する。**指標窓（25）ちょうどしか保持しない設計は禁止**。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from .config import OpsConfig

RETENTION_CANONICAL = "canonical_append_only_never_delete"
RETENTION_SQLITE = "sqlite_rebuildable_keep_all"

#: 指標 → 必要 session 数（Phase 3.5 の実装値）
METRIC_WINDOWS: Mapping[str, int] = {
    "advance_decline_ratio_25session": 25, "turnover_20session_avg": 20,
    "advance_ratio_20session_avg": 20, "turnover_5session_avg": 5,
    "advance_ratio_5session_avg": 5, "index_change / breadth": 2,
}


@dataclass(frozen=True)
class WindowPolicy:
    seed_sessions: int
    active_calculation_sessions: int
    safety_buffer_sessions: int
    max_metric_window: int
    retention_canonical: str = RETENTION_CANONICAL
    retention_sqlite: str = RETENTION_SQLITE

    @property
    def minimum_sessions_for_all_metrics(self) -> int:
        """全指標を計算できる最小 session 数（最長窓 + 1 前営業日）。"""
        return self.max_metric_window + 1

    @property
    def required_sessions(self) -> int:
        """朝に保持していなければならない session 数（最長窓 + buffer）。"""
        return self.max_metric_window + self.safety_buffer_sessions

    def validate(self) -> List[str]:
        problems: List[str] = []
        if self.active_calculation_sessions <= self.max_metric_window:
            problems.append("active_calculation_sessions must exceed max_metric_window")
        if self.safety_buffer_sessions < 5:
            problems.append("safety_buffer_sessions must be >= 5 (corporate action / gaps)")
        if self.seed_sessions < self.active_calculation_sessions + self.safety_buffer_sessions:
            problems.append("seed_sessions must be >= active + buffer")
        return problems

    def as_dict(self) -> Dict[str, object]:
        return {
            "seed_sessions": self.seed_sessions,
            "active_calculation_sessions": self.active_calculation_sessions,
            "safety_buffer_sessions": self.safety_buffer_sessions,
            "max_metric_window": self.max_metric_window,
            "minimum_sessions_for_all_metrics": self.minimum_sessions_for_all_metrics,
            "required_sessions": self.required_sessions,
            "retention_canonical": self.retention_canonical,
            "retention_sqlite": self.retention_sqlite,
            "metric_windows": dict(METRIC_WINDOWS),
            "rule": "rolling window = active calculation window; canonical history is never deleted",
        }


def policy_from_config(config: OpsConfig) -> WindowPolicy:
    return WindowPolicy(seed_sessions=config.seed_sessions,
                        active_calculation_sessions=config.active_calculation_sessions,
                        safety_buffer_sessions=config.safety_buffer_sessions,
                        max_metric_window=config.max_metric_window)


def calculation_sessions(stored_sessions: Sequence[str], policy: WindowPolicy) -> List[str]:
    """active window（直近 N session）。canonical から削除はしない。"""
    ordered = sorted(stored_sessions)
    return ordered[-policy.active_calculation_sessions:]


def seed_sessions(expected_sessions: Sequence[str], policy: WindowPolicy,
                  *, count: int = 0) -> List[str]:
    """seed 対象（expected の末尾 seed_sessions 件。count 指定で pilot 用に縮小可）。"""
    n = count or policy.seed_sessions
    return sorted(expected_sessions)[-n:]


def affected_sessions(new_sessions: Sequence[str], stored_sessions: Sequence[str],
                      policy: WindowPolicy) -> Tuple[str, str]:
    """新規 session が影響する rolling 指標の再計算範囲（最初の新規 session 以降）。

    Fact は決定論的・冪等なので、最初の新規 session から末尾までを再生成すれば十分。
    入力には最長窓 + 1 の過去 session が必要（範囲の開始をその分だけ遡る）。
    """
    if not new_sessions:
        return "", ""
    ordered = sorted(stored_sessions)
    first_new = min(new_sessions)
    idx = ordered.index(first_new) if first_new in ordered else len(ordered)
    start = ordered[max(0, idx - policy.max_metric_window - 1)]
    return start, ordered[-1] if ordered else first_new
