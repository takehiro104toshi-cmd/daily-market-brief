"""ニュース見出しからテーマ・業界を抽出する。

新規にネットワークアクセスは行わず、news.py で取得済みの見出しを
config.yaml のキーワードでフィルタリングするだけの軽量な処理。

業界（セクター）判定では、見出しに含まれる語から
「追い風（ポジティブ）」「逆風（ネガティブ）」「中立」の3種類に
簡易分類する。あくまで公開見出しの字面に基づく機械的な分類であり、
投資判断のための断定的な評価ではない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .news import Headline

POSITIVE_KEYWORDS = [
    "上昇", "増加", "増益", "好調", "最高値", "上方修正", "改善",
    "回復", "加速", "上振れ", "高値", "堅調", "拡大", "受注増",
]
NEGATIVE_KEYWORDS = [
    "下落", "減少", "減益", "不調", "最安値", "下方修正", "悪化",
    "後退", "減速", "下振れ", "安値", "低迷", "懸念", "リスク",
    "規制", "制裁", "撤退", "縮小",
]


@dataclass
class ThemeMatch:
    label: str
    headlines: List[Headline]


@dataclass
class SectorMatch:
    label: str
    tailwind: List[Headline] = field(default_factory=list)
    headwind: List[Headline] = field(default_factory=list)
    neutral: List[Headline] = field(default_factory=list)
    related_tickers: List[str] = field(default_factory=list)


def classify_sentiment(title: str) -> str:
    has_pos = any(kw in title for kw in POSITIVE_KEYWORDS)
    has_neg = any(kw in title for kw in NEGATIVE_KEYWORDS)
    if has_pos and not has_neg:
        return "tailwind"
    if has_neg and not has_pos:
        return "headwind"
    return "neutral"


def match_themes(headlines: List[Headline], themes: List[str]) -> List[ThemeMatch]:
    matches: List[ThemeMatch] = []
    for theme in themes:
        hits = [h for h in headlines if theme in h.title]
        if hits:
            matches.append(ThemeMatch(label=theme, headlines=hits))
    return matches


def match_sectors(headlines: List[Headline], sectors: Dict[str, dict]) -> List[SectorMatch]:
    """sectors は {業種名: {"keywords": [...], "related_tickers": [...]}} 形式。

    後方互換のため、値が単純なキーワードのリストの場合もサポートする。
    """
    matches: List[SectorMatch] = []
    for sector_name, cfg in sectors.items():
        if isinstance(cfg, dict):
            keywords = cfg.get("keywords", [])
            related_tickers = cfg.get("related_tickers", [])
        else:
            keywords = cfg
            related_tickers = []

        hits = [h for h in headlines if any(kw in h.title for kw in keywords)]
        if not hits:
            continue

        tailwind = [h for h in hits if classify_sentiment(h.title) == "tailwind"]
        headwind = [h for h in hits if classify_sentiment(h.title) == "headwind"]
        neutral = [h for h in hits if classify_sentiment(h.title) == "neutral"]
        matches.append(
            SectorMatch(
                label=sector_name,
                tailwind=tailwind,
                headwind=headwind,
                neutral=neutral,
                related_tickers=related_tickers,
            )
        )
    return matches
