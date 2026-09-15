"""Morning data contract（Phase 3.6 §4）。

東京市場開始前の cutoff（JST 06:00）時点で、J-Quants 由来データが**どの時点のものであるべきか**
を dataset ごとに明示する。「今日のデータ」と「前営業日完了データ」を混同しない。

    DAILY      : 前営業日（latest completed session）のクローズ後データ
    WEEKLY     : cutoff までに **公表済み** の最新週（対象期間 ≠ 公表日）
    REFERENCE  : cutoff 時点で有効な snapshot（master は前営業日以前で最新、calendar は先まで）
    EVENT      : cutoff までに公表済みの予定（未公表の予定は存在しない）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from ..facts.availability import morning_cutoff
from .registry import (
    DAILY,
    EVENT_DRIVEN,
    REFERENCE,
    ROLE_INTERNALS,
    ROLE_NONE,
    ROLE_OPTIONAL,
    ROLE_REQUIRED,
    WEEKLY,
    morning_datasets,
)


@dataclass(frozen=True, kw_only=True)
class ContractItem:
    dataset: str
    frequency_class: str
    morning_role: str
    expected_reference: str          # 期待する時点（session / 週 / snapshot 日）
    expected_rule: str               # 期待の決め方（機械的）
    known_at_rule: str
    must_be_present: bool

    def as_dict(self) -> Dict[str, object]:
        return {"dataset": self.dataset, "frequency_class": self.frequency_class,
                "morning_role": self.morning_role, "expected_reference": self.expected_reference,
                "expected_rule": self.expected_rule, "known_at_rule": self.known_at_rule,
                "must_be_present": self.must_be_present}


@dataclass(frozen=True, kw_only=True)
class MorningContract:
    morning_session: str
    cutoff_utc: str
    previous_session: str
    items: Tuple[ContractItem, ...]

    def by_role(self, role: str) -> List[ContractItem]:
        return [i for i in self.items if i.morning_role == role]

    def as_dict(self) -> Dict[str, object]:
        return {"morning_session": self.morning_session, "cutoff_utc": self.cutoff_utc,
                "previous_session": self.previous_session,
                "required": [i.dataset for i in self.by_role(ROLE_REQUIRED)],
                "internals": [i.dataset for i in self.by_role(ROLE_INTERNALS)],
                "optional": [i.dataset for i in self.by_role(ROLE_OPTIONAL)],
                "items": [i.as_dict() for i in self.items],
                "rule": "today's session is never an input; previous completed session is the reference"}


def previous_session_of(morning_session: str, trading_days: Sequence[str]) -> str:
    before = [d for d in trading_days if d < morning_session]
    return before[-1] if before else ""


def morning_contract(morning_session: str, trading_days: Sequence[str], *,
                     master_refresh_days: int = 7, flow_max_age_days: int = 14,
                     earnings_days_ahead: int = 90) -> MorningContract:
    previous = previous_session_of(morning_session, trading_days)
    cutoff = morning_cutoff(morning_session)
    morning = date.fromisoformat(morning_session)
    items: List[ContractItem] = []
    for cap in morning_datasets(ROLE_REQUIRED, ROLE_INTERNALS, ROLE_OPTIONAL):
        if cap.frequency_class == DAILY:
            expected, rule = previous, "latest completed Tokyo session (< morning); today's close is unknown"
        elif cap.frequency_class == WEEKLY:
            expected = (f"latest week with PubDate {cap.known_at_rule.split('（')[0]} <= cutoff; "
                        f"period_end >= {(morning - timedelta(days=flow_max_age_days)).isoformat()}")
            rule = "publication gating: use only weeks published before cutoff; never 'today'"
        elif cap.frequency_class == REFERENCE:
            if cap.dataset == "listed_master":
                expected = (f"snapshot effective <= {previous} and refreshed within "
                            f"{master_refresh_days} days")
                rule = "latest master snapshot at or before the previous session"
            else:
                expected = (f"covers {previous}..{(morning + timedelta(days=60)).isoformat()}")
                rule = "validated trading-day divisions; must cover previous session and forward window"
        elif cap.frequency_class == EVENT_DRIVEN:
            expected = f"schedules published by cutoff for {morning_session}..{(morning + timedelta(days=earnings_days_ahead)).isoformat()}"
            rule = "only published schedules; a future event date is not look-ahead"
        else:
            expected, rule = "on demand", "not part of the morning contract"
        items.append(ContractItem(
            dataset=cap.dataset, frequency_class=cap.frequency_class,
            morning_role=cap.morning_role, expected_reference=expected, expected_rule=rule,
            known_at_rule=cap.known_at_rule, must_be_present=cap.morning_role == ROLE_REQUIRED))
    return MorningContract(morning_session=morning_session, cutoff_utc=cutoff.isoformat(),
                           previous_session=previous, items=tuple(items))
