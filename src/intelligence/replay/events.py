"""Transition events（Phase 3.9.4）— timeline から派生する。FIRST_* は identity ごとに最大 1 回、
*_CHANGED は隣接 snapshot 間の差分のみ。Reference Score / Cross-Regime / Quality gate は event 化しない。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from ..corpus_research.lifecycle import (
    NEW_PATTERN_CANDIDATE,
    OBSERVED,
    REVIEW_CANDIDATE,
    STRONG_PATTERN_CANDIDATE,
)
from ..evaluation.models import APPROVE_RECOMMENDED, NOT_READY, REJECT_RECOMMENDED, REVIEW_RECOMMENDED
from .timeline import SECTION_MAIN

FIRST_LIFECYCLE = {OBSERVED: "FIRST_OBSERVED", NEW_PATTERN_CANDIDATE: "FIRST_NEW_PATTERN_CANDIDATE",
                   REVIEW_CANDIDATE: "FIRST_REVIEW_CANDIDATE", STRONG_PATTERN_CANDIDATE: "FIRST_STRONG_PATTERN_CANDIDATE"}
FIRST_RECOMMENDATION = {REVIEW_RECOMMENDED: "FIRST_REVIEW_RECOMMENDED", APPROVE_RECOMMENDED: "FIRST_APPROVE_RECOMMENDED",
                        REJECT_RECOMMENDED: "FIRST_REJECT_RECOMMENDED", NOT_READY: "FIRST_NOT_READY"}
RECOMMENDATION_CHANGED = "RECOMMENDATION_CHANGED"
LIFECYCLE_CHANGED = "LIFECYCLE_CHANGED"
CONSISTENCY_CHANGED = "CONSISTENCY_CHANGED"
FIRST_SURFACED_IN_MAIN = "FIRST_SURFACED_IN_MAIN"


def rows_by_pattern(rows: Iterable[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    out: Dict[str, List[Mapping[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r["pattern_id"]), []).append(r)
    for pid in out:
        out[pid].sort(key=lambda r: int(r["position"]))
    return out


def _event(run_id: str, row: Mapping[str, Any], kind: str, **extra) -> Dict[str, Any]:
    return {"run_id": run_id, "event": kind, "pattern_id": row["pattern_id"], "pattern_type": row["pattern_type"],
            "position": int(row["position"]), "latest_document_date": row["latest_document_date"],
            "snapshot_id": row["snapshot_id"], **extra}


def derive_events(run_id: str, rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for pid, history in sorted(rows_by_pattern(rows).items()):
        seen_life: set = set()
        seen_rec: set = set()
        surfaced = False
        prev = None
        for row in history:
            life, rec = row["lifecycle_status"], row["recommendation"]
            cons = str((row.get("axis_states") or {}).get("evidence_consistency", ""))
            if life in FIRST_LIFECYCLE and life not in seen_life:
                seen_life.add(life)
                events.append(_event(run_id, row, FIRST_LIFECYCLE[life]))
            if rec in FIRST_RECOMMENDATION and rec not in seen_rec:
                seen_rec.add(rec)
                events.append(_event(run_id, row, FIRST_RECOMMENDATION[rec]))
            if row["queue_section"] == SECTION_MAIN and not surfaced:
                surfaced = True
                events.append(_event(run_id, row, FIRST_SURFACED_IN_MAIN, queue_rank=row.get("queue_rank")))
            if prev is not None:
                if prev["recommendation"] != rec:
                    events.append(_event(run_id, row, RECOMMENDATION_CHANGED, from_state=prev["recommendation"], to_state=rec,
                                         from_position=int(prev["position"])))
                if prev["lifecycle_status"] != life:
                    events.append(_event(run_id, row, LIFECYCLE_CHANGED, from_state=prev["lifecycle_status"], to_state=life,
                                         from_position=int(prev["position"])))
                pcons = str((prev.get("axis_states") or {}).get("evidence_consistency", ""))
                if pcons != cons:
                    events.append(_event(run_id, row, CONSISTENCY_CHANGED, from_state=pcons, to_state=cons,
                                         from_position=int(prev["position"])))
            prev = row
    return events
