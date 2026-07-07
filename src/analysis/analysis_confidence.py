"""Analysis Confidence（v3.2・改善10）— 旧「AI Confidence」に代わる分析根拠の充実度。

「未来が当たる確率」ではなく、レポート全体がどれだけ実データに支えられているかを
0〜100で機械的に表す。算出根拠は、取得ソース数・公式(Tier1)情報数・重複報道数
（Major Story）・鮮度・市場データの欠損状況・分析可能項目数という、いずれも
既に手元にある実データのみ。生成AIの推測は使わない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .models import AnalysisBundle, AnalysisConfidence, NewsRankingItem
from .source_trust import source_tier


def _freshness_component(freshness) -> int:
    if freshness is None or getattr(freshness, "avg_age_hours", None) is None:
        return 0
    age = freshness.avg_age_hours
    if age < 6:
        return 20
    if age < 24:
        return 14
    if age < 48:
        return 8
    return 3


def _completeness_component(market: dict) -> int:
    market = market or {}
    quotes = (
        market.get("indices", []) + market.get("forex", []) + market.get("rates", []) + market.get("commodities", [])
    )
    if not quotes:
        return 0
    ok = sum(1 for q in quotes if q is not None and q.price is not None)
    return int(round(ok / len(quotes) * 15))


def _analyzable_component(bundle: AnalysisBundle) -> int:
    checks = [
        bool(bundle.news_ranking),
        bool(bundle.sector_ranking),
        bool(bundle.future_intelligence.theme_diagnosis),
        bool(bundle.watchlist_quicklist.get("jp") or bundle.watchlist_quicklist.get("us")),
        bool(bundle.weekly_events),
    ]
    return int(round(sum(checks) / len(checks) * 10))


def build_analysis_confidence(
    sources: SourceRegistry,
    freshness,
    market: dict,
    news_items: List[NewsRankingItem],
    bundle: AnalysisBundle,
) -> AnalysisConfidence:
    """各実データ指標から Analysis Confidence(0〜100) を算出する。"""
    news_items = news_items or []
    ref_count = len(sources.all()) if sources else 0
    tier1_count = sum(1 for it in news_items if source_tier(it.headline.source) == "Tier1")
    major_count = sum(1 for it in news_items if getattr(it, "is_major_story", False))

    components = {
        "取得ソース数": min(20, ref_count),
        "公式情報数(Tier1)": min(20, tier1_count * 5),
        "重複報道(Major)": min(15, major_count * 5),
        "鮮度": _freshness_component(freshness),
        "データ欠損": _completeness_component(market),
        "分析可能項目数": _analyzable_component(bundle),
    }
    score = max(0, min(100, sum(components.values())))

    if score >= 70:
        grade = "高"
    elif score >= 45:
        grade = "中"
    elif score > 0:
        grade = "低"
    else:
        grade = "判定不能"

    basis = (
        f"取得ソース{ref_count}件・Tier1情報{tier1_count}件・Major Story{major_count}件・"
        "鮮度・市場データ欠損・分析可能項目数から機械的に算出（将来の的中確率ではありません）。"
    )
    return AnalysisConfidence(score=score, grade=grade, components=components, basis=basis)
