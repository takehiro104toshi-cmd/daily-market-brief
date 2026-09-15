"""ページ section 判定（layout 非依存・textual marker）。REPORT_STRUCTURE_SPEC の紙面構造に対応。"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence

P1_JP_OUTLOOK = "p1_japan_outlook"            # 市場データ表＋日本株相場見通し
GLOBAL_STRATEGY = "global_strategy"           # グローバル投資戦略 & 要人発言（米株 or 為替）
INVESTMENT_IDEA = "investment_idea"           # グローバル投資アイデア
FEATURED_STOCKS = "featured_stocks"           # 注目の日本株
JP_WEEKLY_REVIEW = "jp_weekly_review"         # 日本株：先週までの物色動向（月曜）
US_WEEKLY_REVIEW = "us_weekly_review"         # 米国株：先週の物色動向（月曜）
PUBLICATIONS = "publications"                 # 資料・セミナー案内
UNKNOWN_SECTION = "unknown_section"

P2_MODE_US_EQUITY = "us_equity_outlook"
P2_MODE_FX = "fx_outlook"
P2_MODE_UNKNOWN = "unknown"

_WS = re.compile(r"\s+")


def _compact(text: str) -> str:
    return _WS.sub("", text or "")


def classify_page(text: str) -> str:
    t = _compact(text)
    if "羅針盤" in t and "グローバル投資の" in t and "前日比" in t:
        return P1_JP_OUTLOOK
    if "米国株：先週の物色動向" in t or ("先週の物色動向" in t and "S&P500" in t and "業種" in t):
        return US_WEEKLY_REVIEW
    if "先週までの物色動向" in t:
        return JP_WEEKLY_REVIEW
    if "グローバル投資戦略" in t:
        return GLOBAL_STRATEGY
    if "グローバル投資アイデア" in t:
        return INVESTMENT_IDEA
    if "注目の日本株" in t:
        return FEATURED_STOCKS
    if "▼最新資料" in t or "セミナー" in t and "資料" in t:
        return PUBLICATIONS
    return UNKNOWN_SECTION


def classify_pages(page_texts: Sequence[str]) -> List[str]:
    return [classify_page(t) for t in page_texts]


def p2_mode(text: str) -> str:
    """P2 左カラム: 月水金=米国株見通し / 火木=為替見通し（数値レンジ必須）。"""
    t = _compact(text)
    if "ドル円相場" in t and ("予想レンジ" in t or "レンジ" in t):
        return P2_MODE_FX
    if "米国株" in t and ("見通し" in t or "相場" in t):
        return P2_MODE_US_EQUITY
    return P2_MODE_UNKNOWN


def section_summary(page_texts: Sequence[str]) -> Dict[str, object]:
    sections = classify_pages(page_texts)
    counts: Dict[str, int] = {}
    for s in sections:
        counts[s] = counts.get(s, 0) + 1
    mode = P2_MODE_UNKNOWN
    for text, sec in zip(page_texts, sections):
        if sec == GLOBAL_STRATEGY:
            mode = p2_mode(text)
            break
    return {"sections": sections, "counts": counts, "p2_mode": mode,
            "has_weekly_review": JP_WEEKLY_REVIEW in sections or US_WEEKLY_REVIEW in sections}
