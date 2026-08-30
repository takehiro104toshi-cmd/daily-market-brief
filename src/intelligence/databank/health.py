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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from ..core.types import SCHEMA_VERSION

#: Phase 3 blocker（docs/sources/SOURCE_GAPS.md G10/G11と対応）。
#: (gap対象series, P2-Gで解決を担うseries, gap ID, 制約note)
#: 解決状況はカタログ（probe=false＝live実証済み）とローカルデータの実在から
#: 機械導出する——「コードを書いた」だけではRESOLVEDにならない。
CRITICAL_MARKET_GAPS = (
    ("index:topix.close.closing.tokyo", "index:topix.close.closing.tokyo",
     "G10", "TOPIX指数（ETF代用禁止。P2-G: J-Quants公式系API経路——credential要）"),
    ("rates:JGB10Y.yield.closing.tokyo", "rates:JGB10Y.yield.closing.tokyo",
     "G11", "JGB10Y（別期間/商品の代用禁止。P2-G: 財務省国債金利情報経路）"),
    ("rates:UST2Y.yield.closing.us", "rates:UST2Y_par.yield.closing.us",
     "G11", "UST2Y（別概念yieldの代用禁止。P2-G: Treasury official par yield別series）"),
)

HEALTHY, DEGRADED, BLOCKED = "HEALTHY", "DEGRADED", "BLOCKED"

#: live実証済みだがcanonicalが本data rootに無い（market runner運用の正直な申告）
SOURCE_VALIDATED_NOT_LOCAL = "SOURCE_VALIDATED_DATA_NOT_LOCAL"


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
    # 状態導出: カタログのprobe=false（live実証済み）＝source_validated、
    # ローカルmarket bankに解決seriesのraw実データ（25DMA可能な25行以上）＝データ実在。
    try:
        from ..market.series_catalog import load_catalog
        catalog = load_catalog()
    except Exception:  # noqa: BLE001 カタログ不在でもhealthは落とさない（gapは未解決扱い）
        catalog = None
    market_db = market_root / "index" / "market.sqlite3"

    def _series_rows(series_id: str) -> int:
        if not market_db.exists():
            return 0
        conn = sqlite3.connect(str(market_db))
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM observations WHERE series_id = ? AND kind = 'raw'",
                (series_id,)).fetchone()[0]
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()

    # P2-G.1: TOPIXはfreshness（当日利用可否）まで見て状態を決める
    #   ——「APIが繋がった」だけでRESOLVEDにしない（DO NOT LIE ABOUT FRESHNESS）
    from ..market.topix_freshness import (
        G10_PARTIAL,
        G10_RESOLVED,
        TOPIX_SERIES_ID,
        evaluate_topix_freshness,
        g10_state,
    )

    def _topix_state(local_rows: int, source_validated: bool):
        from ..market.jquants_topix import credential_status

        credential_present = bool(credential_status()["present"])
        if local_rows and market_db.exists():
            from ..market.store import SqliteMarketIndex

            index = SqliteMarketIndex(market_db)
            try:
                freshness = evaluate_topix_freshness(
                    index, now=datetime.now(timezone.utc))
            finally:
                index.close()
            state, codes = g10_state(freshness, credential_present=credential_present)
            return state, codes, freshness.as_dict()
        if source_validated:
            return (SOURCE_VALIDATED_NOT_LOCAL,
                    ("live_validated_on_runner", "market_bank_not_local"), {})
        return (G10_PARTIAL,
                ("topix_credential_missing" if not credential_present
                 else "topix_not_live_validated",
                 "adapter_implemented_not_live_validated"), {})

    gaps = []
    blocking = 0
    for gap_series, resolving_series, gap_id, note in CRITICAL_MARKET_GAPS:
        spec = catalog.get(resolving_series) if catalog is not None else None
        source_validated = bool(spec is not None and spec.enabled and not spec.probe)
        local_rows = _series_rows(resolving_series)
        freshness_detail: Dict = {}
        if gap_series == TOPIX_SERIES_ID:
            status, reason_codes, freshness_detail = _topix_state(
                local_rows, source_validated)
        elif source_validated and local_rows >= 25:
            status, reason_codes = G10_RESOLVED, ("live_validated", "history_ge_25dma")
        elif source_validated:
            status, reason_codes = (SOURCE_VALIDATED_NOT_LOCAL,
                                    ("live_validated_on_runner", "market_bank_not_local"))
        else:
            status, reason_codes = G10_PARTIAL, ("source_not_live_validated",)
        if status not in (G10_RESOLVED, SOURCE_VALIDATED_NOT_LOCAL):
            blocking += 1
        entry = {"series_id": gap_series, "resolving_series": resolving_series,
                 "gap": gap_id, "status": status,
                 "reason_codes": list(reason_codes),
                 "local_raw_rows": local_rows, "note": note}
        if freshness_detail:
            entry["freshness"] = freshness_detail
        gaps.append(entry)
    components["phase3_readiness"] = {
        "state": BLOCKED if blocking else DEGRADED,
        "reason_codes": (["critical_market_source_gaps_unresolved"] if blocking
                         else ["gap_closure_validated_awaiting_supervisor_promotion"]),
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
