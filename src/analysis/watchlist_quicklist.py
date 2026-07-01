"""「今日のウォッチリスト」: 監視銘柄を★評価＋1行理由でさっと確認できる一覧を作る。

「保有・監視銘柄分析」（今日／1週間／1か月／長期の詳細分析）とは別に、
一目で状況を把握できる簡易版として提供する。ロジックの重複を避けるため、
業種の追い風/逆風判定は stock_ranking.py の既存ヘルパーを再利用する。
"""
from __future__ import annotations

from typing import Dict, List

from ..collectors.market_data import Quote
from ..collectors.news import Headline
from ..collectors.themes import SectorMatch
from ..report.format_utils import NOT_AVAILABLE, importance_stars
from .models import WatchlistQuickEntry
from .stock_ranking import _sector_for_ticker


def _reason_line(quote: Quote, headlines: List[Headline], sector_matches: List[SectorMatch]) -> str:
    matched = [h for h in headlines if quote.name in h.title]
    if matched:
        return f"「{matched[0].title}」など関連ニュースあり。"

    sector = _sector_for_ticker(quote.symbol, sector_matches)
    if sector is not None:
        if len(sector.tailwind) > len(sector.headwind):
            return f"業種「{sector.label}」に追い風の動きがあります。"
        if len(sector.headwind) > len(sector.tailwind):
            return f"業種「{sector.label}」に逆風の動きがあります。"
        return f"業種「{sector.label}」は強弱まちまちです。"

    if quote.change_pct is None:
        return f"データを取得できませんでした（{NOT_AVAILABLE}）。"
    direction = "上昇" if quote.change_pct >= 0 else "下落"
    return f"前日比{direction}、個別の材料は確認されませんでした。"


def _build_entries(quotes: List[Quote], headlines: List[Headline], sector_matches: List[SectorMatch]) -> List[WatchlistQuickEntry]:
    return [
        WatchlistQuickEntry(
            quote=q,
            stars=importance_stars(q.change_pct, max_stars=5),
            reason=_reason_line(q, headlines, sector_matches),
        )
        for q in quotes
    ]


def build_watchlist_quicklist(
    jp_quotes: List[Quote],
    us_quotes: List[Quote],
    headlines: List[Headline],
    sector_matches: List[SectorMatch],
) -> Dict[str, List[WatchlistQuickEntry]]:
    return {
        "jp": _build_entries(jp_quotes, headlines, sector_matches),
        "us": _build_entries(us_quotes, headlines, sector_matches),
    }
