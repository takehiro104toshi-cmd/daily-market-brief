"""個別株を値動きの大きさでランキングし、短期・中期・長期の見立てを付与する。

ランキング基準は前日比変化率の絶対値（ルールベース）。
短期は本日の値動きと関連見出し、中期は業種の追い風/逆風、
長期はその業種の方向感からの機械的な延長線上の見立てであり、
将来を保証する予測ではない。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..collectors.market_data import Quote
from ..collectors.news import Headline
from ..collectors.themes import SectorMatch
from ..report.format_utils import NOT_AVAILABLE, fmt_change, fmt_price, importance_stars
from .models import StockRankingEntry

TOP_N = 10


def _rank_quotes(quotes: List[Quote]) -> List[Quote]:
    with_data = [q for q in quotes if q.change_pct is not None]
    with_data.sort(key=lambda q: abs(q.change_pct), reverse=True)
    return with_data[:TOP_N]


def _sector_for_ticker(ticker: str, sector_matches: List[SectorMatch]) -> Optional[SectorMatch]:
    return next((m for m in sector_matches if ticker in m.related_tickers), None)


def _short_term(quote: Quote, headlines: List[Headline]) -> str:
    matched = [h for h in headlines if quote.name in h.title][:1]
    move_txt = f"前日比{fmt_change(quote.change, quote.change_pct)}。"
    if matched:
        return move_txt + f" 関連見出し: 「{matched[0].title}」（{matched[0].source}）"
    return move_txt + " 本日、個別の関連見出しは確認されませんでした。"


def _mid_term(ticker: str, sector_matches: List[SectorMatch]) -> str:
    sector = _sector_for_ticker(ticker, sector_matches)
    if sector is None:
        return f"中長期材料として関連付けられる業種動向は確認されませんでした（{NOT_AVAILABLE}または該当なし）。"
    if len(sector.tailwind) > len(sector.headwind):
        return f"業種「{sector.label}」に追い風のニュースが多く、資金流入が続く可能性があります。"
    if len(sector.headwind) > len(sector.tailwind):
        return f"業種「{sector.label}」に逆風のニュースが多く、上値の重い展開になる可能性があります。"
    return f"業種「{sector.label}」の見出しは強弱まちまちで、方向感がはっきりしません。"


def _long_term(ticker: str, sector_matches: List[SectorMatch]) -> str:
    sector = _sector_for_ticker(ticker, sector_matches)
    if sector is None:
        return "業種動向からの長期見解は本日時点では判断材料が不足しています。"
    if len(sector.tailwind) > len(sector.headwind):
        return f"「{sector.label}」テーマが継続すれば、構造的な成長ストーリーとして意識され続ける可能性があります。"
    if len(sector.headwind) > len(sector.tailwind):
        return f"「{sector.label}」への逆風が続く場合、長期的な戦略の見直しが材料視される可能性があります。"
    return f"「{sector.label}」の方向感が定まるまでは、長期見解も中立的に捉えるのが妥当と考えられます。"


def _build_entries(quotes: List[Quote], headlines: List[Headline], sector_matches: List[SectorMatch]) -> List[StockRankingEntry]:
    ranked = _rank_quotes(quotes)
    entries = []
    for rank, q in enumerate(ranked, start=1):
        entries.append(
            StockRankingEntry(
                rank=rank,
                quote=q,
                stars=importance_stars(q.change_pct, max_stars=5),
                short_term=_short_term(q, headlines),
                mid_term=_mid_term(q.symbol, sector_matches),
                long_term=_long_term(q.symbol, sector_matches),
            )
        )
    return entries


def build_stock_ranking(
    jp_quotes: List[Quote],
    us_quotes: List[Quote],
    headlines: List[Headline],
    sector_matches: List[SectorMatch],
) -> Dict[str, List[StockRankingEntry]]:
    return {
        "jp": _build_entries(jp_quotes, headlines, sector_matches),
        "us": _build_entries(us_quotes, headlines, sector_matches),
    }
