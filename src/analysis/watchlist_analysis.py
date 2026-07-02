"""保有・監視銘柄について、今日・1週間・1か月・長期の見立てを毎朝生成する。

ウォッチリストの全銘柄が対象（TOP10ランキングとは異なり、件数の絞り込みは行わない）。
decision (決算発表) の日付が事実として存在する場合は、その日付までの
日数をもとに「今後1週間」「今後1か月」の文言に反映する。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from ..collectors.earnings import EarningsEvent
from ..collectors.market_data import Quote
from ..collectors.news import Headline
from ..collectors.themes import SectorMatch
from .models import WatchlistEntry
from .stock_ranking import _long_term, _mid_term, _sector_for_ticker, _short_term


def _days_until(date_str: Optional[str], reference: datetime) -> Optional[int]:
    if not date_str:
        return None
    try:
        parsed = pd.to_datetime(date_str)
        if pd.isna(parsed):
            return None
        return (parsed.date() - reference.date()).days
    except Exception:
        return None


def _month_outlook(ticker: str, sector_matches: List[SectorMatch]) -> str:
    sector = _sector_for_ticker(ticker, sector_matches)
    if sector is None:
        return "業種動向の判断材料が乏しく、1か月程度の見通しも不透明です。"
    if len(sector.tailwind) > len(sector.headwind):
        return f"「{sector.label}」への追い風が続けば、1か月程度のスパンでも堅調な推移が期待される可能性があります。"
    if len(sector.headwind) > len(sector.tailwind):
        return f"「{sector.label}」への逆風が続く場合、1か月程度のスパンでも軟調な推移になる可能性があります。"
    return f"「{sector.label}」の方向感がはっきりするまでは、1か月程度の見通しも中立的に捉えるのが妥当と考えられます。"


def _next_week_text(ticker: str, sector_matches: List[SectorMatch], ev: Optional[EarningsEvent], reference: datetime) -> str:
    base = _mid_term(ticker, sector_matches)
    days = _days_until(ev.date if ev else None, reference)
    if ev and days is not None and 0 <= days <= 7:
        return f"決算発表（{ev.date}）を控えており、株価変動が大きくなりやすい1週間です。{base}"
    if ev:
        return f"{base}（参考: 決算発表予定 {ev.date}）"
    return base


def _next_month_text(ticker: str, sector_matches: List[SectorMatch], ev: Optional[EarningsEvent], reference: datetime) -> str:
    base = _month_outlook(ticker, sector_matches)
    days = _days_until(ev.date if ev else None, reference)
    if ev and days is not None and 0 <= days <= 30:
        return f"今月中に決算発表（{ev.date}）が予定されており、業績見通しの変化が材料になりやすい状況です。{base}"
    if ev:
        return f"{base}（参考: 決算発表予定 {ev.date}）"
    return base


def _risk_text(
    quote: Quote,
    ticker: str,
    sector_matches: List[SectorMatch],
    ev: Optional[EarningsEvent],
    reference: datetime,
) -> str:
    risks: List[str] = []
    days = _days_until(ev.date if ev else None, reference)
    if ev and days is not None and 0 <= days <= 14:
        risks.append(f"決算発表（{ev.date}）を控えており、結果次第で株価が急変動するリスクがあります。")

    sector = _sector_for_ticker(ticker, sector_matches)
    if sector is not None and len(sector.headwind) > len(sector.tailwind):
        risks.append(f"業種「{sector.label}」への逆風ニュースが優勢なため、想定より弱い展開になるリスクがあります。")

    if quote.change_pct is not None and abs(quote.change_pct) >= 3:
        risks.append("直近の値動きが大きく、短期的な過熱・反動のリスクに注意が必要な局面です。")

    if not risks:
        return "現時点で突出したリスク要因は確認されていませんが、相場全体の急変には留意が必要です。"
    return " ".join(risks)


def build_watchlist_analysis(
    jp_quotes: List[Quote],
    us_quotes: List[Quote],
    headlines: List[Headline],
    sector_matches: List[SectorMatch],
    earnings: List[EarningsEvent],
    report_date: datetime,
) -> Dict[str, List[WatchlistEntry]]:
    earnings_by_ticker = {e.ticker: e for e in earnings}

    def _build(quotes: List[Quote]) -> List[WatchlistEntry]:
        entries = []
        for q in quotes:
            ev = earnings_by_ticker.get(q.symbol)
            entries.append(
                WatchlistEntry(
                    quote=q,
                    today=_short_term(q, headlines),
                    next_week=_next_week_text(q.symbol, sector_matches, ev, report_date),
                    next_month=_next_month_text(q.symbol, sector_matches, ev, report_date),
                    long_term=_long_term(q.symbol, sector_matches),
                    risk=_risk_text(q, q.symbol, sector_matches, ev, report_date),
                )
            )
        return entries

    return {"jp": _build(jp_quotes), "us": _build(us_quotes)}
