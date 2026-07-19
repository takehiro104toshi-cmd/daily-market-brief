"""External Intelligence Bundle 組み立て（v4.x, Article Intelligence Data Tank連携）。

src.data.external_intelligence_client が取得した package(dict)/status(dict) を、
既存の AnalysisBundle へ接続できる軽量な ExternalIntelligenceBundle へ変換する。

Data Tank側で既に件数上限が適用されているはずだが、万一パッケージが上限を超えていても
Market Intelligence側で再度キャップする（防御的プログラミング）。既存Engineへは
まだ接続しない（AnalysisBundleへ保持するだけ・将来の段階的接続の基盤）。
"""
from __future__ import annotations

from typing import Optional

from .models import ExternalIntelligenceBundle

DEFAULT_LIMITS = {
    "hot_articles": 100,
    "global_drivers": 20,
    "market_reactions": 30,
    "risk_radar": 20,
    "theme_summary": 30,
    "event_clusters": 30,
    "historical_matches": 20,
}


def build_external_intelligence_bundle(
    package: Optional[dict],
    status: Optional[dict],
    limits: Optional[dict] = None,
) -> ExternalIntelligenceBundle:
    status = status or {}
    limits = {**DEFAULT_LIMITS, **(limits or {})}

    bundle = ExternalIntelligenceBundle(
        usage_state=status.get("usage_state", "disabled"),
        freshness_label=status.get("freshness_label", ""),
        package_generated_at=status.get("package_generated_at", ""),
        fetched_at=status.get("fetched_at", ""),
        schema_version=status.get("schema_version", ""),
        reason=status.get("reason", ""),
    )
    if not package:
        return bundle

    tank_status = package.get("tank_status", {}) or {}
    bundle.tank_total_articles = int(tank_status.get("total_articles", 0) or 0)
    bundle.tank_new_articles_24h = int(tank_status.get("new_articles_24h", 0) or 0)
    bundle.hot_articles = list(package.get("hot_articles", []) or [])[: limits["hot_articles"]]
    bundle.global_drivers = list(package.get("global_drivers", []) or [])[: limits["global_drivers"]]
    bundle.market_reactions = list(package.get("market_reactions", []) or [])[: limits["market_reactions"]]
    bundle.risk_radar = list(package.get("risk_radar", []) or [])[: limits["risk_radar"]]
    bundle.theme_summary = list(package.get("theme_summary", []) or [])[: limits["theme_summary"]]
    bundle.event_clusters = list(package.get("event_clusters", []) or [])[: limits["event_clusters"]]
    bundle.historical_matches = list(package.get("historical_matches", []) or [])[: limits["historical_matches"]]
    return bundle
