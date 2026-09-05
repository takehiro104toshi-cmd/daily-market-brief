"""Unified Data Bank Audit / Phase 2 Reconciliation（Phase 2-F PART A）。

News/Market横断の一括監査:
record counts / orphan references / duplicate IDs / schema versions /
QA coverage / classification coverage / identity coverage / revision chains /
source provenance / storage consistency / SQLite vs canonical。

目的:「どこかで何件消えたか不明」= ZERO UNKNOWN LOSS の機械証明。
検知のみ（自動修復しない）。
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Dict, List, Set

from ..databank.article_store import IdentityEventType, JsonlArticleStore
from ..databank.backfill import JsonlNewsBankStore
from ..enrichment.store import JsonlEnrichmentStore
from ..evidence_qa.store import JsonlAssessmentStore
from ..normalization.store import JsonlNormalizedStore


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


def build_phase2_reconciliation(data_root: Path) -> Dict:
    """実data rootに対する全record種の会計恒等式＋整合性検査。"""
    bank = Path(data_root) / "databank"
    news = JsonlNewsBankStore(bank / "news")
    normalized = JsonlNormalizedStore(bank / "normalized")
    qa = JsonlAssessmentStore(bank / "evidence_qa")
    articles = JsonlArticleStore(bank / "articles")
    enrichment = JsonlEnrichmentStore(bank / "news" / "enrichment")

    issues: List[str] = []
    docs = list(normalized.iter_documents())
    items = list(news.iter_news_items())
    identities = list(articles.iter_identities())
    classifications = list(enrichment.iter_classifications())
    annotations = list(news.iter_annotations())
    assessments = list(qa.iter_assessments())

    # ---- duplicate ID検査 ----
    for name, ids in (
        ("source_documents", [d.source_document_id for d in docs]),
        ("news_items", [i.news_item_id for i in items]),
        ("articles", [a.article_id for a in identities]),
        ("classifications", [c.classification_id for c in classifications]),
        ("legacy_annotations", [a.annotation_id for a in annotations]),
    ):
        dupes = [k for k, v in Counter(ids).items() if v > 1]
        if dupes:
            issues.append(f"duplicate_ids:{name}:{len(dupes)}")

    # ---- identity会計（P2-C恒等式の再検証） ----
    decision_counts = Counter(
        e.decision_kind for e in articles.iter_events()
        if e.event_type is IdentityEventType.CREATE or
        e.event_type is IdentityEventType.MARK_REVISION)
    distinct = decision_counts.get("distinct", 0)
    candidate = decision_counts.get("candidate", 0)
    revision = decision_counts.get("revision", 0)
    identity_ok = (distinct + candidate + revision == len(docs)) and \
        (distinct + candidate == len(identities) == len(items))
    if not identity_ok:
        issues.append("identity_accounting_mismatch")

    # ---- orphan参照 ----
    doc_ids: Set[str] = {d.source_document_id for d in docs}
    item_ids: Set[str] = {i.news_item_id for i in items}
    orphan_cls = sum(1 for c in classifications if c.news_item_id not in item_ids)
    orphan_ann = sum(1 for a in annotations if a.target_record_id not in doc_ids)
    orphan_item_docs = sum(1 for i in items if i.primary_document_id not in doc_ids)
    for name, count in (("classifications_to_items", orphan_cls),
                        ("annotations_to_docs", orphan_ann),
                        ("items_to_primary_docs", orphan_item_docs)):
        if count:
            issues.append(f"orphans:{name}:{count}")

    # ---- QA coverage / provenance ----
    assessed = {a.record_id for a in assessments}
    unassessed_docs = len(doc_ids - assessed)
    if unassessed_docs:
        issues.append(f"qa_coverage_gap:{unassessed_docs}")
    missing_source = sum(1 for d in docs if not d.source_id)
    if missing_source:
        issues.append(f"missing_source_provenance:{missing_source}")

    # ---- schema versions ----
    schema_versions = sorted({d.schema_version for d in docs}
                             | {i.schema_version for i in items}
                             | {c.schema_version for c in classifications})

    # ---- SQLite vs canonical ----
    index_db = bank / "index" / "news.sqlite3"
    sqlite_items = _sqlite_count(index_db, "news_items")
    sqlite_cls = _sqlite_count(index_db, "classifications")
    sqlite_consistent = (sqlite_items in (-1, len(items))) and \
        (sqlite_cls in (-1, len(classifications)))
    if not sqlite_consistent:
        issues.append("sqlite_vs_canonical_mismatch（indexは導出物——rebuildで解消）")

    # ---- Market Bank（存在すれば同型の会計） ----
    market: Dict = {"present": False}
    market_root = bank / "market"
    if (market_root / "normalized" / "observations.jsonl").exists():
        market_normalized = JsonlNormalizedStore(market_root / "normalized")
        market_qa = JsonlAssessmentStore(market_root / "evidence_qa")
        observations = list(market_normalized.iter_observations())
        raw = [o for o in observations if o.kind.value == "raw"]
        derived = [o for o in observations if o.kind.value == "derived"]
        market_assessed = {a.record_id for a in market_qa.iter_assessments()}
        market_index = _sqlite_count(market_root / "index" / "market.sqlite3",
                                     "observations")
        market = {
            "present": True,
            "observations_raw": len(raw),
            "observations_derived": len(derived),
            "assessments": sum(1 for _ in market_qa.iter_assessments()),
            "unassessed_observations": len(
                {o.observation_id for o in observations} - market_assessed),
            "sqlite_observations": market_index,
        }
        if market["unassessed_observations"]:
            issues.append(f"market_qa_coverage_gap:{market['unassessed_observations']}")
        if market_index not in (-1, len(observations)):
            issues.append("market_sqlite_vs_canonical_mismatch")

    counts = {
        "news_source_documents": len(docs),
        "articles": len(identities),
        "news_items": len(items),
        "classifications": len(classifications),
        "legacy_annotations": len(annotations),
        "identity_candidates": candidate,
        "identity_revisions": revision,
        "enrichment_review_queue": sum(1 for _ in enrichment.iter_review_queue()),
        "evidence_assessments": len(assessments),
        "recovered_lines_total": (news.recovered_lines + normalized.recovered_lines
                                  + qa.recovered_lines + enrichment.recovered_lines),
    }
    return {
        "counts": counts,
        "identity_accounting": {
            "documents": len(docs), "distinct": distinct, "candidate": candidate,
            "revision": revision,
            "identity_ok": identity_ok,
            "equation": f"{distinct}+{candidate}+{revision}=={len(docs)}",
        },
        "market": market,
        "schema_versions": schema_versions,
        "sqlite_consistent": sqlite_consistent,
        "issues": issues,
        "zero_unknown_loss": not issues,
    }
