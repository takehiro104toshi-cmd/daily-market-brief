"""CorpusSnapshot（Phase 3.7 §26）— Phase 3.8 Automatic Analyzer へ渡す read model。

documents / analysis artifacts / quality / coverage / provenance / versions を 1 つの
machine-readable 構造で取得できる。書き込みはしない（store の read のみ）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from .config import CorpusConfig
from .coverage import COVERAGE_DIMENSIONS, CoverageLabels, coverage_report
from .family import MARKERS_VERSION
from .milestones import milestone_status
from .quality import LIMITED_USE, PARTIAL, QUARANTINED, VALID
from .status import ANALYZED, FAILED
from .status import PARTIAL as STATUS_PARTIAL
from .status import QUARANTINED as STATUS_QUARANTINED
from .store import CorpusStore
from .versioning import CORPUS_SCHEMA_VERSION, VersionSet, supersession_chain

SNAPSHOT_FILE = "snapshot.json"

#: milestone / coverage に数える document（quality VALID + PARTIAL）。
#: pattern evidence へ無条件投入できるのは VALID のみ（quality.eligible_for_pattern_evidence）。
USABLE_QUALITIES = (VALID, PARTIAL)


@dataclass(frozen=True)
class CorpusSnapshot:
    snapshot_id: str
    generated_at: str
    corpus_root: str
    versions: Mapping[str, str]
    counts: Mapping[str, int]
    date_range: Tuple[str, str]
    documents: Tuple[Dict[str, object], ...]
    coverage: Mapping[str, object]
    milestones: Mapping[str, object]
    store_counts: Mapping[str, int]

    def as_dict(self) -> Dict[str, object]:
        return {"snapshot_id": self.snapshot_id, "generated_at": self.generated_at,
                "corpus_root": self.corpus_root, "versions": dict(self.versions),
                "counts": dict(self.counts), "date_range": list(self.date_range),
                "documents": list(self.documents), "coverage": dict(self.coverage),
                "milestones": dict(self.milestones), "store_counts": dict(self.store_counts)}


def build_snapshot(store: CorpusStore, config: CorpusConfig, now: datetime) -> CorpusSnapshot:
    docs = store.documents()
    views: List[Dict[str, object]] = []
    labels: List[CoverageLabels] = []
    counts = {"documents": 0, "usable": 0, "eligible_for_pattern_evidence": 0, "valid": 0,
              "partial": 0, "limited_use": 0, "quarantined": 0, "failed": 0,
              "duplicates_seen": len(store.duplicates())}
    dates: List[str] = []
    for doc in docs:
        counts["documents"] += 1
        status = store.current_status(doc.document_id)
        quality = store.quality_for(doc.document_id)
        q = str(quality["quality"]) if quality else ""
        if status == FAILED:
            counts["failed"] += 1
        elif status == STATUS_QUARANTINED:
            counts["quarantined"] += 1
        if q == VALID:
            counts["valid"] += 1
        elif q == PARTIAL:
            counts["partial"] += 1
        elif q == LIMITED_USE:
            counts["limited_use"] += 1
        if q in USABLE_QUALITIES and status in (ANALYZED, STATUS_PARTIAL):
            counts["usable"] += 1
            if doc.document_date:
                dates.append(doc.document_date)
        if quality and quality.get("eligible_for_pattern_evidence"):
            counts["eligible_for_pattern_evidence"] += 1
        analyses = store.analyses_for(doc.document_id)
        current = store.current_analysis(doc.document_id)
        cov = store.coverage_for(doc.document_id)
        if cov and q in USABLE_QUALITIES:
            labels.append(CoverageLabels(
                label_id=str(cov["label_id"]), document_id=doc.document_id,
                document_date=doc.document_date, labels=dict(cov["labels"]),
                sources=dict(cov["sources"]), thresholds_version=str(cov["thresholds_version"]),
                analysis_version=str(cov["analysis_version"]), created_at=str(cov["created_at"])))
        temporal = store.temporal_for(doc.document_id) or {}
        alignments = store.alignments_for(doc.document_id)
        align_summary: Dict[str, int] = {}
        for a in alignments:
            align_summary[a["status"]] = align_summary.get(a["status"], 0) + 1
        views.append({
            "document_id": doc.document_id, "document_date": doc.document_date,
            "date_sequence": doc.date_sequence, "status": status, "quality": q,
            "eligible_for_pattern_evidence": bool(quality and quality.get("eligible_for_pattern_evidence")),
            "sha256": doc.sha256, "storage_locator": doc.storage_locator,
            "page_count": doc.page_count, "family_confidence": doc.family_confidence,
            "received_at": doc.received_at, "publication_date": doc.publication_date,
            "publication_time_source": temporal.get("publication_time_source", ""),
            "referenced_market_session": temporal.get("referenced_market_session", ""),
            "current_analysis_id": str(current.get("record_id", "")) if current else "",
            "analysis_versions": [str(a.get("analysis_version", "")) for a in analyses],
            "supersession_chain": supersession_chain(analyses),
            "artifact_count": len(store.artifacts_for(doc.document_id, config.extractor_version)),
            "observation_counts": dict(current.get("counts") or {}) if current else {},
            "coverage_labels": dict(cov["labels"]) if cov else {},
            "coverage_sources": dict(cov["sources"]) if cov else {},
            "alignment_summary": align_summary,
        })
    report = coverage_report(labels, min_docs_per_label=config.coverage_min_docs_per_label,
                             thresholds_version=config.coverage_thresholds_version)
    milestones = milestone_status(counts["usable"], config.milestones)
    versions = VersionSet(schema_version=CORPUS_SCHEMA_VERSION,
                          extractor_version=config.extractor_version,
                          analysis_version=config.analysis_version,
                          coverage_thresholds_version=config.coverage_thresholds_version,
                          family_markers_version=MARKERS_VERSION).as_dict()
    seed = json.dumps({"docs": [v["document_id"] for v in views],
                       "current": [v["current_analysis_id"] for v in views],
                       "versions": versions}, sort_keys=True)
    return CorpusSnapshot(
        snapshot_id="css_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
        generated_at=now.isoformat(), corpus_root=str(store.root), versions=versions,
        counts=counts, date_range=(min(dates), max(dates)) if dates else ("", ""),
        documents=tuple(views), coverage=report, milestones=milestones.as_dict(),
        store_counts=store.counts())


def write_snapshot(root: Path, snapshot: CorpusSnapshot) -> Path:
    path = Path(root) / SNAPSHOT_FILE
    path.write_text(json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=1, default=str),
                    encoding="utf-8")
    return path


def coverage_summary(snapshot: CorpusSnapshot) -> Dict[str, object]:
    """§25 の machine-readable coverage report（snapshot の要約）。"""
    cov = dict(snapshot.coverage)
    return {
        "unique_documents": snapshot.counts["documents"],
        "usable_documents": snapshot.counts["usable"],
        "eligible_for_pattern_evidence": snapshot.counts["eligible_for_pattern_evidence"],
        "partial_documents": snapshot.counts["partial"],
        "limited_use_documents": snapshot.counts["limited_use"],
        "quarantined": snapshot.counts["quarantined"],
        "failed": snapshot.counts["failed"],
        "date_range": list(snapshot.date_range),
        "coverage_by_dimension": {d: cov["dimensions"][d]["counts"] for d in COVERAGE_DIMENSIONS},
        "label_sources_by_dimension": {d: cov["dimensions"][d]["sources"] for d in COVERAGE_DIMENSIONS},
        "well_represented": {d: cov["dimensions"][d]["well_represented"] for d in COVERAGE_DIMENSIONS},
        "underrepresented_regimes": cov["underrepresented_regimes"],
        "missing_regimes": cov["missing_regimes"],
        "dimensions_fully_unknown": cov["dimensions_fully_unknown"],
        "thresholds_version": cov["thresholds_version"],
        "next_milestone": snapshot.milestones["next_milestone"],
        "documents_needed_to_next_milestone": snapshot.milestones["documents_needed"],
        "reached_milestone": snapshot.milestones["reached"],
    }
