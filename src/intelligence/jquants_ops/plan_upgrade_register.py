"""Plan upgrade register（Phase 3.6 §26）。

現在 NOT_ENTITLED の有用 dataset について、用途・ブロックされる機能・必要プラン・優先度・
現在の回避策・upgrade の価値を記録する。**推奨を水増ししない**: 現行 Light で足りるものは
LIGHT_SUFFICIENT を明示する。upgrade は自動実施しない（監督者判断）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

LIGHT_SUFFICIENT = "LIGHT_SUFFICIENT"
UPGRADE_VALUE_LOW = "LOW"
UPGRADE_VALUE_MEDIUM = "MEDIUM"
UPGRADE_VALUE_HIGH = "HIGH"


@dataclass(frozen=True, kw_only=True)
class UpgradeEntry:
    dataset: str
    potential_use: str
    blocked_feature: str
    required_plan: str
    priority: str                  # P1 / P2 / P3
    current_workaround: str
    upgrade_value: str             # LOW / MEDIUM / HIGH
    verdict: str                   # LIGHT_SUFFICIENT / UPGRADE_CANDIDATE / NOT_NEEDED

    def as_dict(self) -> Dict[str, str]:
        return {"dataset": self.dataset, "potential_use": self.potential_use,
                "blocked_feature": self.blocked_feature, "required_plan": self.required_plan,
                "priority": self.priority, "current_workaround": self.current_workaround,
                "upgrade_value": self.upgrade_value, "verdict": self.verdict}


REGISTER: Tuple[UpgradeEntry, ...] = (
    UpgradeEntry(dataset="markets_short_ratio", potential_use="業種別空売り比率（需給の日次観測）",
                 blocked_feature="Internals: 空売り需給次元", required_plan="Standard",
                 priority="P2", current_workaround="investor_types（週次）で需給を部分観測",
                 upgrade_value=UPGRADE_VALUE_MEDIUM, verdict="UPGRADE_CANDIDATE"),
    UpgradeEntry(dataset="indices_bars_daily", potential_use="TOPIX以外の指数（グロース250等）",
                 blocked_feature="Internals: 市場区分別指数の横断",
                 required_plan="Standard", priority="P3",
                 current_workaround="Nikkei225 は承認済み代替 source、プライム内部は daily bars 集計で充足",
                 upgrade_value=UPGRADE_VALUE_LOW, verdict=LIGHT_SUFFICIENT),
    UpgradeEntry(dataset="markets_breakdown", potential_use="売買内訳（信用・現物等）",
                 blocked_feature="需給の詳細分解", required_plan="Premium", priority="P3",
                 current_workaround="なし（未要求）", upgrade_value=UPGRADE_VALUE_LOW,
                 verdict="NOT_NEEDED"),
    UpgradeEntry(dataset="equities_bars_am", potential_use="前場終値（当日朝の速報性）",
                 blocked_feature="当日昼の Compass 更新", required_plan="Premium", priority="P3",
                 current_workaround="朝の Compass は前営業日クローズ基準で設計されている",
                 upgrade_value=UPGRADE_VALUE_LOW, verdict=LIGHT_SUFFICIENT),
    UpgradeEntry(dataset="fins_dividend", potential_use="配当（インカム観点の Screener）",
                 blocked_feature="Screener（Phase 対象外）", required_plan="Standard", priority="P3",
                 current_workaround="なし（未要求）", upgrade_value=UPGRADE_VALUE_LOW,
                 verdict="NOT_NEEDED"),
    UpgradeEntry(dataset="fins_details", potential_use="詳細財務",
                 blocked_feature="Company Intelligence 深掘り（Phase 対象外）",
                 required_plan="Standard", priority="P3",
                 current_workaround="fins_summary（実績・会社予想）で充足",
                 upgrade_value=UPGRADE_VALUE_LOW, verdict=LIGHT_SUFFICIENT),
)


def register_rows() -> List[Dict[str, str]]:
    return [e.as_dict() for e in REGISTER]


def summary() -> Dict[str, object]:
    return {
        "entries": len(REGISTER),
        "upgrade_candidates": [e.dataset for e in REGISTER if e.verdict == "UPGRADE_CANDIDATE"],
        "light_sufficient": [e.dataset for e in REGISTER if e.verdict == LIGHT_SUFFICIENT],
        "not_needed": [e.dataset for e in REGISTER if e.verdict == "NOT_NEEDED"],
        "overall": "LIGHT_SUFFICIENT for Morning Compass / Internals; "
                   "markets_short_ratio is the only P2 candidate (not auto-upgraded)",
    }
