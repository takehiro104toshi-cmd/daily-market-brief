"""TOPIX strategy（Phase 3.6 §16）。

既存の `jquants_v2.JQuantsV2TopixProvider`（Market Data Bank 所有・P2-G.2 live 実証）を
**変更しない**。日次 contract を正式化し、Nikkei（承認済み代替 source）との
same-session alignment を毎朝確認する。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Sequence

CONTRACT: Dict[str, str] = {
    "owner": "Market Data Bank (databank/market)",
    "provider": "jquants_v2.JQuantsV2TopixProvider (unchanged)",
    "frequency": "DAILY; 1 request per morning (from=latest_stored+1 to=today)",
    "known_at": "session 15:30 JST (exchange_close)",
    "update_time_source": "J-Quants updates TOPIX around 16:30 JST on trading days",
    "identity": "TOPIX index only (no ETF/futures proxy)",
    "alignment": "Nikkei225 (legacy approved source) must share the latest session; otherwise nt_ratio/relative contexts are not built for that session",
    "failure": "AUTH/NOT_ENTITLED => ABSTAIN for japan_equities (REQUIRED); no retry storm",
}


def topix_daily_params(latest_stored: str, today: date) -> Dict[str, str]:
    if latest_stored:
        start = date.fromisoformat(latest_stored) + timedelta(days=1)
    else:
        start = today - timedelta(days=45)
    return {"from": start.isoformat(), "to": today.isoformat()}


def same_session_alignment(topix_dates: Sequence[str], nikkei_dates: Sequence[str]
                           ) -> Dict[str, object]:
    t, n = sorted(set(topix_dates)), sorted(set(nikkei_dates))
    common = sorted(set(t) & set(n))
    return {"topix_latest": t[-1] if t else "", "nikkei_latest": n[-1] if n else "",
            "latest_common_session": common[-1] if common else "",
            "aligned": bool(t and n and t[-1] == n[-1]),
            "topix_only_sessions": len(set(t) - set(n)), "nikkei_only_sessions": len(set(n) - set(t))}
