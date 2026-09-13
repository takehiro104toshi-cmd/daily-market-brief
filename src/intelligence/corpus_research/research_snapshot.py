"""CompassCorpusResearchSnapshot（Phase 3.8 §33）— Phase 3.9 / 監督者向け read model。"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Dict, List, Mapping, Sequence

from .config import ResearchConfig
from .lifecycle import PHASE_38_MAX_STATUS, STATUSES


def build_research_snapshot(*, corpus_snapshot: Mapping, structures: Mapping[str, Mapping],
                            pattern_records: Mapping[str, Mapping], similar: Mapping[str, Sequence[Mapping]],
                            dna_counts: Mapping[str, int], conflicts: Sequence[Mapping], benchmark: Mapping,
                            review_items: Sequence[Mapping], acquisition: Sequence[Mapping],
                            connector_availability: Mapping, config: ResearchConfig, now: datetime,
                            limitations: Sequence[str]) -> Dict[str, object]:
    counts = dict(corpus_snapshot.get("counts") or {})
    by_status: Dict[str, int] = {s: 0 for s in STATUSES}
    for r in pattern_records.values():
        by_status[str(r.get("status"))] = by_status.get(str(r.get("status")), 0) + 1
    ranked = sorted(pattern_records.values(), key=lambda r: (-int(r.get("support_count", 0)),
                                                             -int(r.get("regime_count", 0)), str(r["pattern_id"])))
    top = [{"pattern_id": r["pattern_id"], "pattern_type": r.get("pattern_type"), "status": r.get("status"),
            "support_count": r.get("support_count"), "regime_count": r.get("regime_count"),
            "components": r.get("components"), "date_range": r.get("date_range"),
            "limitations": list(r.get("limitations") or []) + [l for l in limitations if l.startswith(("CORPUS_SIZE", "SHORT_SPAN"))]}
           for r in ranked[:10]]
    new_candidates = [t for t in top if t["status"] == "NEW_PATTERN_CANDIDATE"]
    queue_by_kind: Dict[str, int] = {}
    for it in review_items:
        queue_by_kind[str(it.get("kind"))] = queue_by_kind.get(str(it.get("kind")), 0) + 1
    seed = "|".join(sorted(structures)) + "|" + "|".join(sorted(pattern_records)) + "|" + config.version_key
    return {
        "snapshot_id": "crn_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
        "generated_at": now.isoformat(),
        "corpus_count": counts.get("documents", 0), "eligible_count": counts.get("eligible_for_pattern_evidence", 0),
        "usable_count": counts.get("usable", 0), "date_range": list(corpus_snapshot.get("date_range") or []),
        "milestone": dict(corpus_snapshot.get("milestones") or {}),
        "coverage": {k: (corpus_snapshot.get("coverage") or {}).get(k) for k in
                     ("underrepresented_regimes", "missing_regimes", "dimensions_fully_unknown", "thresholds_version")},
        "analyzer_versions": config.versions(), "analyzed_documents": len(structures),
        "patterns_total": len(pattern_records), "patterns_by_status": by_status,
        "max_status_allowed_in_phase_3_8": PHASE_38_MAX_STATUS,
        "top_supported_candidates": top, "new_candidates": new_candidates,
        "dna_comparison_counts": dict(dna_counts), "conflicts": list(conflicts)[:20],
        "similar_documents": {d: list(v) for d, v in similar.items()},
        "benchmark": dict(benchmark), "review_queue": {"open_items": len(review_items), "by_kind": queue_by_kind},
        "acquisition_recommendations": list(acquisition)[:15],
        "market_connector": dict(connector_availability),
        "limitations": list(limitations),
        "boundaries": ["Compass statements are not market facts", "patterns are research evidence, not production rules",
                       "no pattern is APPROVED in Phase 3.8", "benchmark is not forecasting accuracy"],
    }
