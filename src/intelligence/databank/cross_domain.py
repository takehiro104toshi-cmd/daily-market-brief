"""Cross-domain query foundation（Phase 2-F PART F）。

同一TradingWindowのニュースとmarket観測を**取得できる**契約。
「このニュースで株価が上がった」等のcausal分析は**しない**（Phase 6以降）——
関連データを同じwindowで並べて返すだけ。

market側の紐付けはtrading_date/セッション優先（windowがtrading_dateを持つ場合）、
無い場合はas_of時刻範囲（TIMEZONE SAFETY: いずれもUTC aware比較）。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Sequence, Tuple

from ..databank.news_model import NewsItem
from .market_window import TradingWindow
from .query import NewsQuery


@dataclass(frozen=True, kw_only=True)
class CrossDomainSlice:
    """1 windowぶんの読み出し結果（分析判断なしの素材集合）。"""

    window: TradingWindow
    news_items: Tuple[NewsItem, ...]
    observations: Tuple[dict, ...]  # market index行のdict（observation_id/value/…）
    note: str = "no causal analysis — same-window retrieval only"


def fetch_window_slice(
    news_index,     # SqliteNewsIndex（search_news）
    market_index,   # SqliteMarketIndex（query/search_market）
    window: TradingWindow,
    *,
    series_ids: Sequence[str] = (),
    news_query: NewsQuery = NewsQuery(),
    news_limit: int = 200,
) -> CrossDomainSlice:
    """windowに対応するニュース（published_at∈window）とmarket観測を取得する。"""
    news = news_index.search_news(replace(
        news_query, date_from=window.start_utc, date_to=window.end_utc,
        limit=news_limit))

    observations: List[dict] = []
    for series_id in series_ids:
        if window.trading_date:
            # セッション日で紐付け（UTC暦日joinをしない——TIMEZONE SAFETY）
            rows = market_index.query(
                series_id=series_id, date_from=window.trading_date,
                date_to=window.trading_date, kind="raw")
        else:
            rows = [r for r in market_index.query(series_id=series_id, kind="raw")
                    if window.start_utc.isoformat() <= r["as_of_utc"]
                    <= window.end_utc.isoformat()]
        observations.extend({k: r[k] for k in r.keys()} for r in rows)

    return CrossDomainSlice(
        window=window,
        news_items=tuple(news),
        observations=tuple(observations),
    )
