"""Financial summary strategy（Phase 3.6 §14）。

全銘柄の財務サマリーを毎朝取り直さない。最小コスト戦略:

1. **event-driven**: 前営業日に決算発表予定（earnings calendar）があった銘柄だけ code 指定で取得
   （通常 0〜数十リクエスト。決算集中日でも bounded）
2. `date` 指定（1 日分の全開示）が使えるなら 1 リクエストで代替できる —— 可否は
   run #21 の実応答で判定する（P2-H probe は code 指定で成功した時点で停止していた）
3. 周期 refresh は Company Intelligence（将来 Phase）の要求が出てから ON_DEMAND で設計

実績 / 当期会社予想 / 翌期予想 の分離（`FinancialSummaryRecord`）は維持する。
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from ..market.jquants_light_store import JQuantsLightStore

STRATEGY_EVENT_DRIVEN = "EVENT_DRIVEN_BY_EARNINGS_CALENDAR"
STRATEGY_DATE_MODE = "DATE_MODE_ONE_REQUEST_PER_SESSION"
MAX_EVENT_CODES_PER_MORNING = 200


def codes_announced_on(light: JQuantsLightStore, session_date: str) -> List[str]:
    rows = light.earnings_within(session_date, session_date)
    return sorted({str(r["code"]) for r in rows})


def plan_financial_refresh(light: JQuantsLightStore, *, previous_session: str,
                           date_mode_available: bool) -> Dict[str, object]:
    codes = codes_announced_on(light, previous_session)
    if date_mode_available:
        return {"strategy": STRATEGY_DATE_MODE, "params": {"date": previous_session},
                "requests": 1, "codes_announced": len(codes)}
    bounded = codes[:MAX_EVENT_CODES_PER_MORNING]
    return {"strategy": STRATEGY_EVENT_DRIVEN, "codes": bounded, "requests": len(bounded),
            "codes_announced": len(codes), "truncated": len(codes) > len(bounded)}


def strategy() -> Dict[str, object]:
    return {
        "default": STRATEGY_EVENT_DRIVEN,
        "alternative_if_verified": STRATEGY_DATE_MODE,
        "full_universe_each_morning": False,
        "periodic_full_refresh": "ON_DEMAND (Company Intelligence phase)",
        "separation": ["actual", "current_forecast", "next_forecast"],
        "known_at": "DiscDate Tokyo close (jquants_builder)",
        "morning_role": "NONE (not consumed by Morning Compass)",
    }
