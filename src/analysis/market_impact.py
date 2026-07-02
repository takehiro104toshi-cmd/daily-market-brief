"""「マーケットインパクト」: 12対象（指数・為替・金利・主要業種）への
本日の影響度（★1〜5）と方向（プラス／マイナス／中立）を一覧化する。

指数・為替・金利は実データの前日比から、業種は本日の見出しの追い風/逆風
件数（themes.classify_sentiment を再利用）から機械的に判定する。
config.yaml の sectors 設定に依存せず、対象業種のキーワードは本モジュール内に
固定で持つ（ユーザーのsectors設定を変更しても12対象が必ず揃うようにするため）。
"""
from __future__ import annotations

from typing import List

from ..collectors.news import Headline
from ..collectors.themes import classify_sentiment
from ..report.format_utils import NOT_AVAILABLE, find_quote, stars
from .models import MarketImpactEntry

# 対象業種の判定キーワード（config.yaml の sectors とは独立）
SECTOR_KEYWORDS = {
    "半導体": ["半導体", "半導体製造装置", "東京エレクトロン", "アドバンテスト", "ニデック"],
    "銀行": ["銀行", "メガバンク", "邦銀", "地銀"],
    "商社": ["商社", "三菱商事", "三井物産", "伊藤忠", "丸紅", "住友商事"],
    "自動車": ["自動車", "EV", "トヨタ", "日産", "ホンダ", "デンソー"],
    "海運": ["海運", "コンテナ船", "バルチック指数", "運賃"],
    "電力": ["電力", "電力会社", "再エネ", "原発", "送配電"],
    "素材": ["素材", "化学", "鉄鋼", "非鉄", "石油化学"],
    "不動産": ["不動産", "REIT", "住宅", "マンション", "オフィスビル"],
}

_DIRECTION_PLUS = "プラス"
_DIRECTION_MINUS = "マイナス"
_DIRECTION_NEUTRAL = "中立"


def _stars_for_change_pct(change_pct: float) -> str:
    magnitude = abs(change_pct)
    if magnitude >= 2.0:
        score = 5
    elif magnitude >= 1.0:
        score = 4
    elif magnitude >= 0.5:
        score = 3
    elif magnitude >= 0.2:
        score = 2
    else:
        score = 1
    return stars(score, max_stars=5)


def _quote_impact(target: str, quote) -> MarketImpactEntry:
    if quote is None or quote.change_pct is None:
        return MarketImpactEntry(target=target, stars=NOT_AVAILABLE, direction=_DIRECTION_NEUTRAL)
    direction = _DIRECTION_PLUS if quote.change_pct >= 0 else _DIRECTION_MINUS
    return MarketImpactEntry(target=target, stars=_stars_for_change_pct(quote.change_pct), direction=direction)


def _sector_impact(target: str, headlines: List[Headline]) -> MarketImpactEntry:
    keywords = SECTOR_KEYWORDS[target]
    matched = [h for h in headlines if any(kw in h.title for kw in keywords)]
    if not matched:
        return MarketImpactEntry(target=target, stars=stars(1, max_stars=5), direction=_DIRECTION_NEUTRAL)

    tailwind = sum(1 for h in matched if classify_sentiment(h.title) == "tailwind")
    headwind = sum(1 for h in matched if classify_sentiment(h.title) == "headwind")

    if tailwind > headwind:
        direction = _DIRECTION_PLUS
    elif headwind > tailwind:
        direction = _DIRECTION_MINUS
    else:
        direction = _DIRECTION_NEUTRAL

    score = min(5, max(1, len(matched)))
    return MarketImpactEntry(target=target, stars=stars(score, max_stars=5), direction=direction)


def build_market_impact(market: dict, headlines: List[Headline]) -> List[MarketImpactEntry]:
    n225 = find_quote(market.get("indices", []), "日経")
    topix = find_quote(market.get("indices", []), "TOPIX")
    usdjpy = find_quote(market.get("forex", []), "米ドル/円")
    tnx = find_quote(market.get("rates", []), "10年")

    entries = [
        _quote_impact("日経平均", n225),
        _quote_impact("TOPIX", topix),
        _quote_impact("ドル円", usdjpy),
        _quote_impact("長期金利", tnx),
    ]
    entries.extend(_sector_impact(target, headlines) for target in SECTOR_KEYWORDS)
    return entries
