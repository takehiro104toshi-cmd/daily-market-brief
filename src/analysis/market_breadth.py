"""Market Breadth（v3.2・改善9）— 市場全体の強さ（値上がり/値下がりの広がり）。

将来、東証全銘柄の値上がり・値下がり銘柄数の実データを取得できるようになった
際にそのまま使えるよう、advancers/decliners を持てる構造を用意する。現状は
取得済みの主要指数・コモディティ・ウォッチリスト銘柄の前日比プラス/マイナス数から
breadth_score（0〜100・50=中立）を機械的に算出する代用値であり、東証全銘柄の
騰落そのものではない点を is_proxy=True と basis で明示する（断定・捏造はしない）。
"""
from __future__ import annotations

from typing import List, Optional

from ..collectors.market_data import Quote
from .models import MarketBreadth


def build_market_breadth(market: dict, extra_quotes: Optional[List[Quote]] = None) -> MarketBreadth:
    """取得済み銘柄の前日比から Breadth Score を算出する（全市場の代用値）。"""
    market = market or {}
    quotes: List[Quote] = (
        list(market.get("indices", []))
        + list(market.get("commodities", []))
        + list(extra_quotes or [])
    )
    advancers = decliners = unchanged = 0
    for q in quotes:
        if q is None or q.change_pct is None:
            continue
        if q.change_pct > 0:
            advancers += 1
        elif q.change_pct < 0:
            decliners += 1
        else:
            unchanged += 1

    total = advancers + decliners
    if total == 0:
        return MarketBreadth(
            advancers=advancers,
            decliners=decliners,
            unchanged=unchanged,
            breadth_score=50,
            basis="前日比を取得できた銘柄が無いため、Breadth Scoreは中立(50)としています（取得不可）。",
            is_proxy=True,
        )

    breadth_score = int(round(advancers / total * 100))
    breadth_score = max(0, min(100, breadth_score))
    basis = (
        f"取得済みの主要指数・コモディティ・ウォッチリスト銘柄 {total}件のうち、"
        f"値上がり{advancers}件・値下がり{decliners}件から算出した代用値です"
        "（東証全銘柄の値上がり/値下がり数ではありません）。"
    )
    return MarketBreadth(
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        breadth_score=breadth_score,
        basis=basis,
        is_proxy=True,
    )
