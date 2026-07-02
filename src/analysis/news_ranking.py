"""ニュース見出しを重要度でランキングし、最重要ニュースを1件選定する。

スコアリングはすべてルールベース（生成AIではない）。
- テーマ・業種キーワードに一致: 加点
- 相場インパクトの大きいサプライズ語（上方修正・規制など）に一致: 加点
- ウォッチリスト銘柄名に言及: 加点

最高スコアの見出しを「AIが本日最重要と判断したニュース」として
必ず1位に固定する。同点の場合は見出しの出現順を優先する。

各見出しには「理由」「影響市場」「影響業種」も付与する
（②今日の重要ニュースランキング向け）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..collectors.news import Headline
from ..report.format_utils import stars, truncate_to_chars
from .models import NewsRankingItem

SALES_TALK_MAX_CHARS = 100

SURPRISE_KEYWORDS = [
    "上方修正", "下方修正", "最高値", "最安値", "規制", "制裁", "決算",
    "提携", "買収", "増資", "上場", "撤退", "経営統合", "自社株買い",
]

# 影響市場の判定キーワード（先に一致したものを優先）
MARKET_KEYWORDS = [
    ("為替", ["円", "ドル", "為替", "米ドル"]),
    ("米国株", ["米国", "NY", "ダウ", "S&P", "ナスダック", "FRB", "米国株", "米株"]),
    ("日本株", ["日経", "東京市場", "日本株", "TOPIX"]),
    ("金利", ["金利", "日銀", "FOMC", "利上げ", "利下げ"]),
]


@dataclass
class _HeadlineAnalysis:
    score: int
    reason: str
    affected_market: str
    affected_sector: str


def _matched_theme(headline: Headline, themes: List[str]) -> Optional[str]:
    return next((theme for theme in themes if theme in headline.title), None)


def _matched_sector(headline: Headline, sectors: Dict) -> Optional[str]:
    for sector_name, cfg in sectors.items():
        keywords = cfg.get("keywords", []) if isinstance(cfg, dict) else cfg
        if any(kw in headline.title for kw in keywords):
            return sector_name
    return None


def _matched_surprise(headline: Headline) -> Optional[str]:
    return next((kw for kw in SURPRISE_KEYWORDS if kw in headline.title), None)


def _matched_watchlist_name(headline: Headline, watchlist_names: List[str]) -> Optional[str]:
    return next((name for name in watchlist_names if name in headline.title), None)


def _affected_market(headline: Headline) -> str:
    for market_label, keywords in MARKET_KEYWORDS:
        if any(kw in headline.title for kw in keywords):
            return market_label
    return "市場全体"


def _analyze_headline(
    headline: Headline,
    themes: List[str],
    sectors: Dict,
    watchlist_names: List[str],
) -> _HeadlineAnalysis:
    matched_theme = _matched_theme(headline, themes)
    matched_sector = _matched_sector(headline, sectors)
    matched_surprise = _matched_surprise(headline)
    matched_watchlist = _matched_watchlist_name(headline, watchlist_names)

    score = 0
    if matched_theme:
        score += 2
    if matched_sector:
        score += 2
    if matched_surprise:
        score += 1
    if matched_watchlist:
        score += 3

    reason_parts = []
    if matched_theme:
        reason_parts.append(f"テーマ「{matched_theme}」に関連する")
    if matched_sector:
        reason_parts.append(f"業種「{matched_sector}」に関連する")
    if matched_surprise:
        reason_parts.append(f"「{matched_surprise}」という材料を含む")
    if matched_watchlist:
        reason_parts.append(f"ウォッチリスト銘柄「{matched_watchlist}」に言及している")

    if reason_parts:
        reason = "、".join(reason_parts) + "ため、重要度が高いと判断しました。"
    else:
        reason = "本日のニュースの中で相対的に注目度が高いと判断しました。"

    return _HeadlineAnalysis(
        score=score,
        reason=reason,
        affected_market=_affected_market(headline),
        affected_sector=matched_sector or "特定業種なし",
    )


def _sales_talk(headline: Headline, analysis: "_HeadlineAnalysis") -> str:
    """営業現場でそのまま読める、100文字以内の営業トークを生成する（断定は避ける）。"""
    if analysis.affected_sector and analysis.affected_sector != "特定業種なし":
        text = f"「{analysis.affected_sector}」関連は材料出尽くしや利益確定売りが入りやすい局面と考えられます。"
    elif analysis.affected_market and analysis.affected_market != "市場全体":
        text = f"{analysis.affected_market}への影響が意識されており、値動きを確認したい局面です。"
    else:
        text = f"「{headline.title}」は市場全体の地合いを確認する材料の一つと考えられます。"
    return truncate_to_chars(text, SALES_TALK_MAX_CHARS)


def build_news_ranking(
    headlines: List[Headline],
    themes: List[str],
    sectors: Dict,
    watchlist_names: List[str],
    limit: int = 10,
) -> List[NewsRankingItem]:
    if not headlines:
        return []

    analyzed = [
        (headline, _analyze_headline(headline, themes, sectors, watchlist_names))
        for headline in headlines
    ]
    # スコア降順・原順序維持のため安定ソートを利用
    ranked = sorted(enumerate(analyzed), key=lambda item: (-item[1][1].score, item[0]))

    items: List[NewsRankingItem] = []
    for rank, (_, (headline, analysis)) in enumerate(ranked[:limit], start=1):
        star_score = min(5, max(1, 1 + analysis.score))
        items.append(
            NewsRankingItem(
                rank=rank,
                stars=stars(star_score, max_stars=5),
                headline=headline,
                is_top_pick=(rank == 1),
                reason=analysis.reason,
                affected_market=analysis.affected_market,
                affected_sector=analysis.affected_sector,
                sales_talk=_sales_talk(headline, analysis),
            )
        )
    return items
