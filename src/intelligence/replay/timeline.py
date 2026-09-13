"""Pattern timeline row（Phase 3.9.4）— (snapshot, pattern) 1 行。本文・path・ファイル名を持たない。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional

from ..evaluation.config import A_CONSISTENCY, A_CROSS, A_NOVELTY, A_QUALITY, A_STRENGTH, A_TIME
from ..shadow_review.models import find_forbidden_keys

SECTION_MAIN = "MAIN"
SECTION_ADVERSE_OVERFLOW = "ADVERSE_OVERFLOW"
SECTION_BACKLOG = "BACKLOG"
SECTION_NOT_SURFACED = "NOT_SURFACED"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def components_digest(components: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(components or {})).encode("utf-8")).hexdigest()[:16]


def _metrics(record: Mapping[str, Any], axis: str) -> Dict[str, Any]:
    return dict((dict(record.get("axis_metrics") or {}).get(axis) or {}))


def timeline_row(*, run_id: str, snapshot: Mapping[str, Any], evaluation: Mapping[str, Any],
                 pattern: Mapping[str, Any], queue_section: str, queue_rank: Optional[int],
                 material_digest: str, policy_digests: Mapping[str, str]) -> Dict[str, Any]:
    strength = _metrics(evaluation, A_STRENGTH)
    time_ = _metrics(evaluation, A_TIME)
    cross = _metrics(evaluation, A_CROSS)
    consistency = _metrics(evaluation, A_CONSISTENCY)
    novelty = _metrics(evaluation, A_NOVELTY)
    quality = _metrics(evaluation, A_QUALITY)
    row = {
        "run_id": run_id,
        "snapshot_id": snapshot["snapshot_id"], "snapshot_mode": snapshot["snapshot_mode"],
        "ordering_mode": snapshot["ordering_mode"], "position": int(snapshot["position"]),
        "usable_position": int(snapshot["usable_position"]),
        "latest_document_date": snapshot["latest_document_date"],
        "eligible_documents": int(snapshot["eligible_documents"]),
        "usable_documents": int(snapshot["usable_documents"]),
        "milestone": snapshot["milestone"],
        "pattern_id": str(evaluation["pattern_id"]), "pattern_version": str(evaluation.get("pattern_version", "")),
        "pattern_type": str(evaluation["pattern_type"]),
        "components_digest": components_digest(pattern.get("components") or {}),
        "lifecycle_status": str(pattern.get("status", "")),
        "support_count": int(pattern.get("support_count", 0) or 0),
        "eligible_support": int(pattern.get("eligible_support", strength.get("eligible_support", 0)) or 0),
        "regime_count": int(pattern.get("regime_count", 0) or 0),
        "span_days": int(time_.get("span_days", pattern.get("span_days", 0)) or 0),
        "distinct_calendar_months": int(time_.get("distinct_calendar_months", 0) or 0),
        "pattern_first_seen": str(pattern.get("first_seen", "")),
        "recommendation": str(evaluation["recommendation"]),
        "triggered_rule": str(evaluation.get("triggered_rule", "")),
        "blocking_rules": list(evaluation.get("blocking_rules") or []),
        "supporting_rules": list(evaluation.get("supporting_rules") or []),
        "axis_states": dict(evaluation.get("axis_states") or {}),
        "axis_applicability": dict(evaluation.get("axis_applicability") or {}),
        "axis_reasons": dict(evaluation.get("axis_reasons") or {}),
        "reference_score": evaluation.get("reference_score"),
        "reference_score_comparable": bool(evaluation.get("reference_score_comparable")),
        "applicable_weight_sum": int(evaluation.get("applicable_weight_sum", 0) or 0),
        "distinct_2d_cells": int(cross.get("distinct_2d_cells", 0) or 0),
        "confirmed_2d_cells": int(cross.get("confirmed_2d_cells", 0) or 0),
        "relative_support_share": evaluation.get("relative_support_share"),
        "relative_support_share_applicability": str(evaluation.get("relative_support_applicability", "")),
        "dna_classification": str(novelty.get("classification", "")),
        "dna_conflicts": int(consistency.get("dna_conflicts", 0) or 0),
        "contradiction": {"narrow_sibling": bool(consistency.get("narrow_sibling_contradiction")),
                          "narrow_sibling_repeated": bool(consistency.get("narrow_sibling_repeated")),
                          "document": bool(consistency.get("contradiction")),
                          "document_repeated": bool(consistency.get("contradiction_repeated"))},
        "document_qualities": dict(quality.get("document_qualities") or {}),
        "material_digest": material_digest,
        "queue_section": queue_section, "queue_rank": queue_rank,
        "evaluation_policy_digest": policy_digests["evaluation"],
        "recommendation_policy_digest": policy_digests["recommendation"],
        "shadow_review_policy_digest": policy_digests["shadow_review"],
        "research_version_key": policy_digests["research_version_key"],
        "replay_policy_digest": policy_digests["replay"],
    }
    bad = find_forbidden_keys(row)
    if bad:
        raise ValueError("timeline row carries forbidden keys: " + ",".join(bad))
    return row


#: run_digest / snapshot_digest から除外する非意味的 field
VOLATILE_ROW_KEYS = ("run_id",)


def semantic_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in dict(row).items() if k not in VOLATILE_ROW_KEYS}


def rows_digest(rows: List[Mapping[str, Any]]) -> str:
    view = sorted((canonical_json(semantic_row(r)) for r in rows))
    return hashlib.sha256("\n".join(view).encode("utf-8")).hexdigest()[:16]
