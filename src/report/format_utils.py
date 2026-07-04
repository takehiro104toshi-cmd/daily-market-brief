"""Markdownレポート生成で共通して使う整形ヘルパー。

builder.py と src/analysis/ 配下の各モジュールの両方から利用される、
値のフォーマットや★評価の算出などの小さな純粋関数を集約する。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..collectors.market_data import Quote
from ..collectors.news import Headline

NOT_AVAILABLE = "取得不可"


def fmt_price(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return NOT_AVAILABLE
    return f"{value:,.{digits}f}"


def fmt_change(change: Optional[float], change_pct: Optional[float]) -> str:
    if change is None or change_pct is None:
        return NOT_AVAILABLE
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:,.2f} ({sign}{change_pct:,.2f}%)"


def fmt_change_compact(change_pct: Optional[float]) -> str:
    """前日比を「+0.40%」のように短く表示する（モバイル向けの狭いテーブル用）。"""
    if change_pct is None:
        return NOT_AVAILABLE
    sign = "+" if change_pct >= 0 else ""
    return f"{sign}{change_pct:,.2f}%"


def stars(score: int, max_stars: int = 5) -> str:
    score = max(0, min(score, max_stars))
    return "★" * score + "☆" * (max_stars - score)


def importance_stars(change_pct: Optional[float], max_stars: int = 3) -> str:
    if change_pct is None:
        return NOT_AVAILABLE
    pct = abs(change_pct)
    if pct >= 2.0:
        score = max_stars
    elif pct >= 1.0:
        score = max_stars - 1
    elif pct > 0:
        score = max(1, max_stars - 2)
    else:
        score = 0
    return stars(score, max_stars)


def count_stars(count: int, max_stars: int = 3) -> str:
    if count >= 5:
        score = max_stars
    elif count >= 3:
        score = max_stars - 1
    elif count >= 1:
        score = max(1, max_stars - 2)
    else:
        score = 0
    return stars(score, max_stars)


def quote_table(quotes: List[Quote]) -> str:
    """スマホでも横に広がりすぎないよう、列を絞った狭いテーブルを生成する。

    出典は列に収めず「🔗」リンクのみとし（列幅を最小化）、
    前日比は「+0.40%」のようにパーセントのみの表記にする。
    """
    if not quotes:
        return f"データがありません（{NOT_AVAILABLE}）。\n"
    lines = ["| 名称 | 値 | 前日比 | ★ | 出典 |", "|---|---|---|---|---|"]
    for q in quotes:
        source = f"[🔗]({q.source_url})"
        lines.append(
            f"| {q.name} | {fmt_price(q.price)} | {fmt_change_compact(q.change_pct)} "
            f"| {importance_stars(q.change_pct)} | {source} |"
        )
    return "\n".join(lines) + "\n"


def headline_list(headlines: List[Headline], limit: int = 10) -> str:
    if not headlines:
        return f"該当する見出しはありませんでした（{NOT_AVAILABLE}または該当なし）。\n"
    lines = []
    for h in headlines[:limit]:
        lines.append(f"- [{h.title}]({h.link}) — {h.source}")
    return "\n".join(lines) + "\n"


def find_quote(quotes: List[Quote], keyword: str) -> Optional[Quote]:
    return next((q for q in quotes if keyword in q.name), None)


def ticker_lookup(watchlist_quotes: dict) -> Dict[str, Quote]:
    lookup: Dict[str, Quote] = {}
    for q in watchlist_quotes.get("jp_stocks", []) + watchlist_quotes.get("us_stocks", []):
        lookup[q.symbol] = q
    return lookup


def first_sentence(text: str) -> str:
    """「。」までの最初の1文だけを取り出す（モバイル版の1文要約などに使用）。"""
    if not text:
        return text
    idx = text.find("。")
    if idx == -1:
        return text
    return text[: idx + 1]


def todays_action_items(market: dict, analysis) -> List[str]:
    """「Today's Action」用の当日確認事項リスト（最大5件）。

    新たな分析・予測は一切行わず、既に計算済みのTheme Momentum Score最上位
    テーマ・events.today・ドル円レートの有無・industry_momentum最上位・
    「決算」を含む既存ニュース見出しの有無だけから、機械的に「確認事項」を
    組み立てる（断定的な将来予測ではない）。
    """
    items: List[str] = []

    fi = analysis.future_intelligence
    if fi.theme_momentum:
        top_theme = max(fi.theme_momentum, key=lambda tm: tm.momentum_score)
        items.append(f"「{top_theme.label}」関連ニュースを確認")

    if find_quote(market.get("forex", []), "米ドル/円") is not None:
        items.append("ドル円の値動きを確認")

    if analysis.events.today:
        items.append(f"{analysis.events.today[0]}に注目")

    if fi.industry_momentum:
        top_industry = fi.industry_momentum[0]
        items.append(f"「{top_industry.label}」関連指標を確認")

    earnings_news = next(
        (item.headline.title for item in analysis.news_ranking if "決算" in item.headline.title),
        None,
    )
    if earnings_news:
        items.append(f"{earnings_news}を確認")

    return items[:5]


def truncate_to_chars(text: str, max_chars: int) -> str:
    """文字数で切り詰める。可能なら文の区切り（「。」）で自然に切る。

    AIまとめ（300文字以内）や5分で読む版ダイジェスト（200〜300文字）など、
    文字数上限が定められた要約文で共通して使うためのユーティリティ。
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_period = cut.rfind("。")
    if last_period >= int(max_chars * 0.5):
        return cut[: last_period + 1]
    return cut[: max_chars - 1] + "…"
