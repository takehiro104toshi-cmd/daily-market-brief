"""AI Executive Summary（レポート冒頭・今日最重要ニュース最大3件）を生成する。

既に計算済みの news_ranking（重要度順）の上位3件を対象に、日本株・ドル円・
金利それぞれへの影響、および100文字以内の営業トークを付与する。
新たな重要度スコアリングは行わず、news_ranking.py の結果をそのまま利用する
「まとめ役」に徹する。断定表現は避け、「〜の可能性があります」等で統一する。
"""
from __future__ import annotations

from typing import Dict, List

from ..collectors.market_data import Quote
from ..collectors.news import Headline
from ..collectors.themes import SectorMatch
from ..report.format_utils import NOT_AVAILABLE, find_quote, truncate_to_chars
from .models import ExecutiveSummaryItem, NewsRankingItem

MAX_ITEMS = 3
SALES_TALK_MAX_CHARS = 100


def _sector_for_headline(headline: Headline, sector_matches: List[SectorMatch]) -> SectorMatch | None:
    return next(
        (m for m in sector_matches if headline in m.tailwind or headline in m.headwind or headline in m.neutral),
        None,
    )


def _jp_stock_impact(headline: Headline, sector_matches: List[SectorMatch], ticker_lookup: Dict[str, Quote]) -> str:
    sector = _sector_for_headline(headline, sector_matches)
    if sector is None:
        return "個別業種への直接的な影響は現時点で確認されていません。"

    names = [ticker_lookup[t].name for t in sector.related_tickers if t in ticker_lookup][:2]
    names_txt = "・".join(names) if names else sector.label

    if headline in sector.tailwind:
        return f"{names_txt}など「{sector.label}」関連銘柄への追い風が意識されやすい局面です。"
    if headline in sector.headwind:
        return f"{names_txt}など「{sector.label}」関連銘柄には注意が必要な局面です。"
    return f"{names_txt}など「{sector.label}」関連銘柄の材料として意識されています。"


def _usdjpy_impact(headline: Headline, market: dict) -> str:
    usdjpy = find_quote(market.get("forex", []), "米ドル/円")
    fx_keywords = ("円", "ドル", "為替", "米ドル", "日銀", "FRB", "金利")
    if not any(kw in headline.title for kw in fx_keywords):
        return "為替への直接的な影響は限定的とみられます。"
    if usdjpy is None or usdjpy.price is None:
        return f"為替データが{NOT_AVAILABLE}のため、影響度は別途ご確認ください。"
    return f"米ドル/円（現在{usdjpy.price:.2f}円）の変動要因として意識される可能性があります。"


def _rate_impact(headline: Headline, market: dict) -> str:
    tnx = find_quote(market.get("rates", []), "10年")
    rate_keywords = ("金利", "日銀", "FOMC", "利上げ", "利下げ", "FRB", "国債")
    if not any(kw in headline.title for kw in rate_keywords):
        return "金利への直接的な影響は限定的とみられます。"
    if tnx is None or tnx.price is None:
        return f"金利データが{NOT_AVAILABLE}のため、影響度は別途ご確認ください。"
    return f"米10年金利（現在{tnx.price:.2f}%）の変動を通じて株式市場に波及する可能性があります。"


def _sales_talk(headline: Headline, affected_sector: str) -> str:
    if affected_sector and affected_sector != "特定業種なし":
        text = f"「{affected_sector}」関連は材料出尽くしや利益確定売りが入りやすい局面と考えられます。"
    else:
        text = f"「{headline.title}」は市場全体の地合いを確認する材料の一つと考えられます。"
    return truncate_to_chars(text, SALES_TALK_MAX_CHARS)


def build_executive_summary(
    news_ranking_items: List[NewsRankingItem],
    market: dict,
    sector_matches: List[SectorMatch],
    ticker_lookup: Dict[str, Quote],
) -> List[ExecutiveSummaryItem]:
    results: List[ExecutiveSummaryItem] = []
    for item in news_ranking_items[:MAX_ITEMS]:
        headline = item.headline
        conclusion = f"「{headline.title}」（{headline.source}）"
        reason = item.reason or "本日のニュースの中で相対的に注目度が高いと判断しました。"
        results.append(
            ExecutiveSummaryItem(
                rank=item.rank,
                headline=headline,
                stars=item.stars,
                conclusion=conclusion,
                reason=reason,
                jp_stock_impact=_jp_stock_impact(headline, sector_matches, ticker_lookup),
                usdjpy_impact=_usdjpy_impact(headline, market),
                rate_impact=_rate_impact(headline, market),
                sales_talk=item.sales_talk or _sales_talk(headline, item.affected_sector),
            )
        )
    return results
