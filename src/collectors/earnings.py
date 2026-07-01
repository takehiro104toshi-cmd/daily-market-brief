"""config.yaml の watchlist に登録された銘柄の決算発表予定日を取得する。

yfinance の calendar 情報（Yahoo Finance が公開している決算スケジュール）を
日本株・米国株の両方に対して共通で利用する。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from ..utils import SourceRegistry

logger = logging.getLogger("market_brief")

try:
    import yfinance as yf
except ImportError:
    yf = None


@dataclass
class EarningsEvent:
    ticker: str
    name: str
    date: Optional[str]
    source_url: str


def _extract_earnings_date(calendar) -> Optional[str]:
    if calendar is None:
        return None
    try:
        if isinstance(calendar, dict):
            dates = calendar.get("Earnings Date")
            if dates:
                return str(dates[0])
            return None
        if hasattr(calendar, "empty"):
            if calendar.empty or "Earnings Date" not in calendar.index:
                return None
            value = calendar.loc["Earnings Date"]
            return str(value.iloc[0] if hasattr(value, "iloc") else value)
    except Exception:
        return None
    return None


def fetch_earnings_calendar(config: dict, sources: SourceRegistry) -> List[EarningsEvent]:
    events: List[EarningsEvent] = []
    if yf is None:
        return events

    watchlist = config.get("watchlist", {})
    all_tickers = watchlist.get("jp_stocks", []) + watchlist.get("us_stocks", [])

    for item in all_tickers:
        ticker = item["ticker"]
        name = item.get("name", ticker)
        try:
            earnings_date = _extract_earnings_date(yf.Ticker(ticker).calendar)
        except Exception as exc:
            logger.warning("決算日程取得失敗 %s: %s", ticker, exc)
            continue
        if not earnings_date:
            continue
        url = f"https://finance.yahoo.com/quote/{ticker}"
        sources.add(f"{name} 決算スケジュール", url, "決算予定")
        events.append(EarningsEvent(ticker=ticker, name=name, date=earnings_date, source_url=url))

    return events
