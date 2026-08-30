"""Data Bank Health Report（Phase 2-F PART H）。

状態は単一scoreではなく **state＋reason codes**:
    HEALTHY  … 整合性チェック全通過
    DEGRADED … 非致命の問題（recovered lines・index未同期・backup未検証等）
    BLOCKED  … 決定的欠陥または前提未充足（Phase 3判定はcritical source gapsで常にBLOCKED）

CRITICAL SOURCE GAPS（TOPIX/JGB10Y/UST2Y——Phase 3 blocker）は解決状況に
関わらず**必ず表示**する（P2-F中に解決しなくてよい・隠さない）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List

from ..core.types import SCHEMA_VERSION

#: Phase 3 blocker（docs/sources/SOURCE_GAPS.md G10/G11と対応）
CRITICAL_MARKET_GAPS = (
    ("index:topix.close.closing.tokyo", "G10", "TOPIX指数の供給元未確保（ETF代用禁止）"),
    ("rates:JGB10Y.yield.closing.tokyo", "G11", "JGB10Y供給元未確保（別期間/商品の代用禁止）"),
    ("rates:UST2Y.yield.closing.us", "G11", "UST2Y供給元未確保（別概念yieldの代用禁止）"),
)

HEALTHY, DEGRADED, BLOCKED = "HEALTHY", "DEGRADED", "BLOCKED"


def _file_inventory(root: Path) -> List[Dict]:
    files = []
    for path in sorted(root.rglob("*.jsonl")) + sorted(root.rglob("*.sqlite3")):
        files.append({"path": path.relative_to(root).as_posix(),
                      "size": path.stat().st_size})
    return files


def _sqlite_count(db: Path, table: str) -> int:
    if not db.exists():
        return -1
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return -1
    finally:
        conn.close()


def build_health_report(data_root: Path) -> Dict:
    """data root全体のhealth（読み取りのみ・修復しない）。"""
    from ..databank.article_store import JsonlArticleStore
    from ..databank.backfill import JsonlNewsBankStore
    from ..enrichment.store import JsonlEnrichmentStore
    from ..evidence_qa.store import JsonlAssessmentStore
    from ..normalization.store import JsonlNormalizedStore
    from ..review.store import JsonlReviewStore

    bank = Path(data_root) / "databank"
    reasons: List[str] = []
    components: Dict[str, Dict] = {}

    # ---- News Bank ----
    news = JsonlNewsBankStore(bank / "news")
    normalized = JsonlNormalizedStore(bank / "normalized")
    qa = JsonlAssessmentStore(bank / "evidence_qa")
    articles = JsonlArticleStore(bank / "articles")
    enrichment = JsonlEnrichmentStore(bank / "news" / "enrichment")
    review = JsonlReviewStore(bank / "news" / "review")

    docs = sum(1 for _ in normalized.iter_documents())
    items = sum(1 for _ in news.iter_news_items())
    identities = sum(1 for _ in articles.iter_identities())
    assessed_docs = {a.record_id for a in qa.iter_assessments()}
    qa_coverage = round(100 * len(assessed_docs & {
        d.source_document_id for d in normalized.iter_documents()}) / docs, 1) if docs else 0
    classified_items = {c.news_item_id for c in enrichment.iter_classifications()}
    recovered = (news.recovered_lines + normalized.recovered_lines + qa.recovered_lines
                 + enrichment.recovered_lines + review.recovered_lines)
    index_items = _sqlite_count(bank / "index" / "news.sqlite3", "news_items")
    news_state = HEALTHY
    if items != identities:
        news_state = BLOCKED
        reasons.append("news_items_vs_articles_mismatch")
    if recovered:
        news_state = DEGRADED if news_state == HEALTHY else news_state
        reasons.append("recovered_lines_present")
    if index_items >= 0 and index_items != items:
        news_state = DEGRADED if news_state == HEALTHY else news_state
        reasons.append("news_index_out_of_sync（rebuild可能な導出物——再構築で解消）")
    components["news_bank"] = {
        "state": news_state,
        "documents": docs, "articles": identities, "news_items": items,
        "qa_coverage_pct": qa_coverage,
        "classified_items": len(classified_items),
        "classification_coverage_pct": round(100 * len(classified_items) / items, 1) if items else 0,
        "sqlite_news_items": index_items,
        "recovered_lines": recovered,
    }

    # ---- Market Bank（存在すれば） ----
    market_root = bank / "market"
    if (market_root / "normalized" / "observations.jsonl").exists():
        market_normalized = JsonlNormalizedStore(market_root / "normalized")
        market_obs = sum(1 for _ in market_normalized.iter_observations())
        market_index = _sqlite_count(market_root / "index" / "market.sqlite3", "observations")
        market_state = HEALTHY
        if market_index >= 0 and market_index != market_obs:
            market_state = DEGRADED
            reasons.append("market_index_out_of_sync")
        components["market_bank"] = {
            "state": market_state, "observations": market_obs,
            "sqlite_observations": market_index,
            "recovered_lines": market_normalized.recovered_lines,
        }
    else:
        components["market_bank"] = {
            "state": DEGRADED, "observations": 0,
            "note": "本data rootにmarket canonicalなし（live pilotはActions runner上で"
                    "実行——恒久蓄積は永続data rootでの運用開始後）",
        }
        reasons.append("market_bank_not_local")

    # ---- Review ----
    components["review"] = {"state": HEALTHY,
                            "counts_by_status": review.counts_by_status()}

    # ---- Backup ----
    backup_dir = Path(data_root) / "backup"
    manifests = sorted(backup_dir.glob("manifest_*.json")) if backup_dir.exists() else []
    components["backup"] = {
        "state": HEALTHY if manifests else DEGRADED,
        "latest_manifest": manifests[-1].name if manifests else "",
        "manifest_count": len(manifests),
    }
    if not manifests:
        reasons.append("no_backup_manifest")

    # ---- Critical source gaps（必ず表示・Phase 3判定） ----
    gaps = [{"series_id": s, "gap": g, "note": n} for s, g, n in CRITICAL_MARKET_GAPS]
    components["phase3_readiness"] = {
        "state": BLOCKED,
        "reason_codes": ["critical_market_source_gaps_unresolved"],
        "critical_source_gaps": gaps,
    }

    # ---- 総合（phase3_readinessは別軸として扱う） ----
    bank_states = [components[k]["state"] for k in ("news_bank", "market_bank",
                                                    "review", "backup")]
    overall = BLOCKED if BLOCKED in bank_states else (
        DEGRADED if DEGRADED in bank_states else HEALTHY)
    return {
        "schema_version": SCHEMA_VERSION,
        "overall_state": overall,
        "reason_codes": reasons,
        "components": components,
        "canonical_files": _file_inventory(bank),
        "last_runs": {
            "news_backfill": max((r.run_id for r in news.iter_runs()), default=""),
            "enrichment": max((r.run_id for r in enrichment.iter_runs()), default=""),
        },
    }
