"""External Intelligence Bundle 組み立て（v4.x, Article Intelligence Data Tank連携）。

src.data.external_intelligence_client が取得した package(dict)/status(dict) を、
既存の AnalysisBundle へ接続できる軽量な ExternalIntelligenceBundle へ変換する。

Data Tank側で既に件数上限が適用されているはずだが、万一パッケージが上限を超えていても
Market Intelligence側で再度キャップする（防御的プログラミング）。既存Engineへは
まだ接続しない（AnalysisBundleへ保持するだけ・将来の段階的接続の基盤）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..collectors.news import Headline, _normalize_title
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


TANK_SOURCE_PREFIX = "Data Tank"


def hot_articles_to_headlines(hot_articles: Optional[list]) -> List[Headline]:
    """Data Tankのhot_articles（allowlist済みの公開ビュー）を、既存ニュース収集
    パイプラインが扱うHeadlineへ変換する（段階的接続の第一歩）。

    既存の news.dedupe_headlines はタイトル正規化のみでグルーピングするため、
    ここで生成したHeadlineをそのまま既存の見出しリストへ合流させれば、
    同じニュースを既存RSSとData Tank双方が配信していた場合は信頼度
    （reliability = source_trust）の高い方へ自動的に統合される。
    本文（public_excerpt等）はHeadlineに保持フィールドが無いため、
    ここでも一切引き継がない（構造的に本文が混入しない）。
    """
    fetched_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    headlines: List[Headline] = []
    for article in hot_articles or []:
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not title or not url:
            continue
        source_name = (article.get("source") or "").strip()
        source_label = f"{TANK_SOURCE_PREFIX}: {source_name}" if source_name else TANK_SOURCE_PREFIX
        headlines.append(Headline(
            title=title,
            link=url,
            source=source_label,
            published=article.get("published_at") or "",
            reliability=float(article.get("source_trust") or 0.5),
            fetched_at=fetched_at,
        ))
    return headlines


def build_tank_signal_lookup(bundle: Optional[ExternalIntelligenceBundle]) -> Dict[str, dict]:
    """タイトル正規化キー → Data Tankの市場反応シグナル、のルックアップを作る。

    既存ニュースパイプラインの重複判定（news._normalize_title）と同じ正規化を使う
    ため、Tank由来でも既存RSS由来でも「同じニュース」なら同じキーで引ける。
    Tank側が既に計算済みのスコアを転記するだけで、brief側で再計算はしない:
      - has_market_reaction: 記事の属するevent_clusterに実際の市場反応
        （market_reactions）が記録されているか（Market Reaction First）
      - in_global_drivers: Tankの主要因クラスタ（global_drivers）に該当するか
      - market_impact_score / importance_score: Tankの0.0〜1.0スコア
    bundleがNone・リストが空なら空dictを返し、呼び出し側の採点は従来通りになる。
    """
    if bundle is None:
        return {}
    reaction_cluster_ids = {
        r.get("event_cluster_id") for r in (bundle.market_reactions or []) if r.get("event_cluster_id")
    }
    driver_cluster_ids = {
        d.get("event_cluster_id") for d in (bundle.global_drivers or []) if d.get("event_cluster_id")
    }
    lookup: Dict[str, dict] = {}
    for article in bundle.hot_articles or []:
        title = (article.get("title") or "").strip()
        if not title:
            continue
        cluster_id = article.get("event_cluster_id") or ""
        lookup[_normalize_title(title)] = {
            "has_market_reaction": bool(cluster_id and cluster_id in reaction_cluster_ids),
            "in_global_drivers": bool(cluster_id and cluster_id in driver_cluster_ids),
            "market_impact_score": float(article.get("market_impact_score") or 0.0),
            "importance_score": float(article.get("importance_score") or 0.0),
        }
    return lookup
