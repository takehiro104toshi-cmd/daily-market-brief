"""朝会向け「今日の注目5銘柄」を機械的に選定する（日本株5銘柄・米国株5銘柄）。

既存の個別株ランキング（日本株TOP10・米国株TOP10、stock_ranking.py）とは別に、
日本株・米国株それぞれ単独で前日比変化率の大きい順にTOP5だけを抜き出し、
コード・企業名（quote.symbol / quote.name）・理由・注目材料・短期見通しを
朝会でそのまま読み上げられる形で付与する。ランキング基準・考察ロジックは
stock_ranking.pyと同じ（追い風/逆風・関連見出しの有無）であり、
新たな考察ロジックは持たない。表示を朝会向けに絞り込むだけの薄い層。

v3では日本株・米国株を横断した1本のTOP5だったが、v4で
「日本株・米国株それぞれ5銘柄」という要望に合わせて分割した。
"""
from __future__ import annotations

from typing import Dict, List

from ..collectors.market_data import Quote
from ..collectors.news import Headline
from ..collectors.themes import SectorMatch
from ..report.format_utils import NOT_AVAILABLE, fmt_change, importance_stars
from .models import TopPickEntry
from .stock_ranking import _sector_for_ticker

TOP_N = 5


def _matched_headline(quote: Quote, headlines: List[Headline]) -> Headline | None:
    return next((h for h in headlines if quote.name in h.title), None)


def _reason(quote: Quote) -> str:
    return f"前日比{fmt_change(quote.change, quote.change_pct)}と値動きが大きく、本日の注目銘柄として選定しました。"


def _material(quote: Quote, headlines: List[Headline]) -> str:
    matched = _matched_headline(quote, headlines)
    if matched:
        return f"「{matched.title}」（{matched.source}）"
    return f"個別の関連見出しは確認されていません（{NOT_AVAILABLE}または該当なし）。"


def _short_term_outlook(quote: Quote, sector_matches: List[SectorMatch]) -> str:
    sector = _sector_for_ticker(quote.symbol, sector_matches)
    if sector is None:
        return "業種動向からの短期見通しは、本日時点では判断材料が不足しています。"
    if len(sector.tailwind) > len(sector.headwind):
        return f"業種「{sector.label}」への追い風が続けば、短期的に堅調な推移が意識される可能性があります。"
    if len(sector.headwind) > len(sector.tailwind):
        return f"業種「{sector.label}」への逆風が続く場合、短期的に上値が重い展開が意識される可能性があります。"
    return f"業種「{sector.label}」の材料が拮抗しており、短期的には方向感を欠く展開も考えられます。"


def _build_side(quotes: List[Quote], headlines: List[Headline], sector_matches: List[SectorMatch]) -> List[TopPickEntry]:
    ranked = sorted((q for q in quotes if q.change_pct is not None), key=lambda q: abs(q.change_pct), reverse=True)
    top = ranked[:TOP_N]
    return [
        TopPickEntry(
            rank=rank,
            quote=q,
            stars=importance_stars(q.change_pct, max_stars=5),
            reason=_reason(q),
            material=_material(q, headlines),
            short_term=_short_term_outlook(q, sector_matches),
        )
        for rank, q in enumerate(top, start=1)
    ]


def build_top_picks(
    jp_quotes: List[Quote],
    us_quotes: List[Quote],
    headlines: List[Headline],
    sector_matches: List[SectorMatch],
) -> Dict[str, List[TopPickEntry]]:
    return {
        "jp": _build_side(jp_quotes, headlines, sector_matches),
        "us": _build_side(us_quotes, headlines, sector_matches),
    }
