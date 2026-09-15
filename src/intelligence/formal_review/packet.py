"""Evidence packet（Phase 3.9.5）— 人間が実際に見る証拠を 1 pattern = 1 packet にまとめ、内容 digest で束縛する。

- material_digest: Phase 3.9.3 の凍結 semantics をそのまま再利用（機械側の material change 追跡・reopen 用）。
- packet_evidence_digest: 人間が見た証拠そのものの freshness anchor（生成時刻・path・corpus 件数を含めない）。
- 原文・ファイル名・path は入れない（forbidden key scan を通す）。Reference Score は NON_DECISIONAL_REFERENCE_ONLY。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..evaluation.config import A_CONSISTENCY, A_CROSS, A_NOVELTY, A_QUALITY, A_STRENGTH, A_TIME, AXES
from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED
from ..shadow_review.models import find_forbidden_keys
from .config import (
    APPROVED,
    KEEP_REVIEWING,
    REJECTED,
    REOPENED_FOR_REVIEW,
    RETIRED,
    SUPERSEDED,
    FormalReviewPolicy,
)
from .errors import ForbiddenKeyInPacket

REFERENCE_LABEL = "NON_DECISIONAL_REFERENCE_ONLY"
PACKET_ID_PREFIX = "frp_"
EVIDENCE_ONLY = "EVIDENCE_ONLY"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest16(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:16]


def _m(evaluation: Mapping[str, Any], axis: str) -> Dict[str, Any]:
    return dict((dict(evaluation.get("axis_metrics") or {})).get(axis) or {})


def allowed_actions(head_state: str, recommendation: str, reopen_eligible: bool) -> List[str]:
    """Phase 3.9.1 transition × recommendation symmetry（凍結）。"""
    if head_state in ("", KEEP_REVIEWING, REOPENED_FOR_REVIEW):
        if recommendation == APPROVE_RECOMMENDED:
            return [APPROVED, KEEP_REVIEWING]
        if recommendation == REJECT_RECOMMENDED:
            return [REJECTED, KEEP_REVIEWING]
        return [KEEP_REVIEWING]
    if head_state == APPROVED:
        return [SUPERSEDED, RETIRED]
    if head_state == REJECTED:
        return [REOPENED_FOR_REVIEW] if reopen_eligible else []
    return []


def build_packet(*, pattern_id: str, evaluation: Mapping[str, Any], pattern_record: Mapping[str, Any],
                 dna_comparison: Mapping[str, Any], conflicts: Sequence[Mapping[str, Any]],
                 replay: Optional[Mapping[str, Any]], shadow_history: Mapping[str, Any],
                 decision: Mapping[str, Any], group: Mapping[str, Any], material_digest: str,
                 policy_digests: Mapping[str, str], policy_versions: Mapping[str, str],
                 corpus_eligible: int, reopen: Mapping[str, Any], policy: FormalReviewPolicy,
                 built_at: str) -> Dict[str, Any]:
    comp = dict(pattern_record.get("components") or {})
    strength, time_, cross = _m(evaluation, A_STRENGTH), _m(evaluation, A_TIME), _m(evaluation, A_CROSS)
    consistency, novelty, quality = _m(evaluation, A_CONSISTENCY), _m(evaluation, A_NOVELTY), _m(evaluation, A_QUALITY)
    recommendation = str(evaluation.get("recommendation", ""))
    head_state = str(decision.get("state", ""))
    packet: Dict[str, Any] = {
        "identity": {
            "pattern_id": pattern_id, "pattern_type": str(evaluation.get("pattern_type", "")),
            "pattern_version": str(evaluation.get("pattern_version", "")),
            "lifecycle_status": str(pattern_record.get("status", "")),
            "components": {k: (list(v) if isinstance(v, (list, tuple)) else v) for k, v in comp.items()},
            "packet_schema_version": policy.packet_schema_version, "built_at": built_at,
        },
        "recommendation": {
            "recommendation": recommendation, "triggered_rule": str(evaluation.get("triggered_rule", "")),
            "blocking_rules": list(evaluation.get("blocking_rules") or []),
            "supporting_rules": list(evaluation.get("supporting_rules") or []),
            "shadow_mode": bool(evaluation.get("shadow_mode")),
            "formal_review_gate_reached": bool(evaluation.get("formal_review_gate_reached")),
            "corpus_size": int(evaluation.get("corpus_size", 0) or 0),
            "corpus_milestone": str(evaluation.get("corpus_milestone", "")),
        },
        "axes": {
            "states": {a: str((evaluation.get("axis_states") or {}).get(a, "")) for a in AXES},
            "applicability": {a: str((evaluation.get("axis_applicability") or {}).get(a, "")) for a in AXES},
            "reasons": {a: str((evaluation.get("axis_reasons") or {}).get(a, "")) for a in AXES},
            "eligible_support": int(strength.get("eligible_support", quality.get("eligible_support", 0)) or 0),
            "support_count": int(quality.get("support_count", pattern_record.get("support_count", 0)) or 0),
            "span_days": int(time_.get("span_days", pattern_record.get("span_days", 0)) or 0),
            "distinct_calendar_months": int(time_.get("distinct_calendar_months", 0) or 0),
            "distinct_2d_cells": int(cross.get("distinct_2d_cells", 0) or 0),
            "confirmed_2d_cells": int(cross.get("confirmed_2d_cells", 0) or 0),
            "document_qualities": dict(quality.get("document_qualities") or {}),
            "valid_ratio": str(quality.get("valid_ratio", pattern_record.get("valid_ratio", ""))),
            "regime_coverage": sorted(str(r) for r in (pattern_record.get("regime_coverage") or [])),
            "regime_count": pattern_record.get("regime_count"),
        },
        "reference": {
            "label": REFERENCE_LABEL, "reference_score": evaluation.get("reference_score"),
            "reference_score_comparable": bool(evaluation.get("reference_score_comparable")),
            "relative_support_share": evaluation.get("relative_support_share"),
            "relative_support_applicability": str(evaluation.get("relative_support_applicability", "")),
        },
        "consistency": {
            "direction_counts": dict(consistency.get("direction_counts") or {}),
            "direction_class": str(consistency.get("direction_class", "")),
            "identity_direction": str(consistency.get("identity_direction", "")),
            "document_contradiction": bool(consistency.get("contradiction")),
            "document_contradiction_repeated": bool(consistency.get("contradiction_repeated")),
            "narrow_sibling_contradiction": bool(consistency.get("narrow_sibling_contradiction")),
            "narrow_sibling_repeated": bool(consistency.get("narrow_sibling_repeated")),
            "dna_conflicts": int(consistency.get("dna_conflicts", 0) or 0),
            "contradiction_active": bool(consistency.get("contradiction") or consistency.get("narrow_sibling_contradiction")
                                         or int(consistency.get("dna_conflicts", 0) or 0) > 0),
        },
        "dna": {
            "classification": str(novelty.get("classification", dna_comparison.get("classification", ""))),
            "best_rule_id": str(dna_comparison.get("best_rule_id", "")),
            "direction_relation": str(novelty.get("direction_relation", dna_comparison.get("direction_relation", ""))),
            "candidate_rule_count": int(novelty.get("candidate_rule_count", len(dna_comparison.get("candidate_rule_ids") or [])) or 0),
            "conflict_rule_ids": sorted({str(c.get("rule_id", "")) for c in conflicts if c.get("rule_id")}),
            "conflict_count": len(list(conflicts)),
            "boundary": "APPROVED never edits Compass DNA; promotion is a later separate gate",
        },
        "replay": _replay_block(replay, recommendation, corpus_eligible),
        "shadow_history": {**dict(shadow_history), "boundary": f"{EVIDENCE_ONLY}: AGREE is not APPROVED, DISAGREE is not REJECTED"},
        "decision": {
            "current_state": head_state or "NONE", "head_decision_id": str(decision.get("decision_id", "")),
            "history_length": int(decision.get("history_length", 0) or 0),
            "promotion_status": str(decision.get("promotion_status", "NOT_PROMOTED") or "NOT_PROMOTED"),
            "reopen": dict(reopen),
            "allowed_next_actions": allowed_actions(head_state, recommendation, bool(reopen.get("eligible"))),
        },
        "group": dict(group),
        "freshness": {
            "material_digest": material_digest,
            "evaluation_id": str(evaluation.get("evaluation_id", "")),
            "inputs_digest": str(evaluation.get("inputs_digest", "")),
            "informational_only": ["evaluation_id", "inputs_digest"],       # corpus_size を含むため freshness anchor にしない
            "policy_digests": dict(policy_digests), "policy_versions": dict(policy_versions),
            "corpus_eligible_at_build": int(corpus_eligible),
            "head_decision_id": str(decision.get("decision_id", "")),
        },
    }
    packet["freshness"]["packet_evidence_digest"] = packet_evidence_digest(packet)
    packet["identity"]["packet_id"] = packet_id_for(pattern_id, packet["freshness"]["packet_evidence_digest"],
                                                    policy.packet_schema_version, str(policy_digests.get("formal_review", "")))
    found = find_forbidden_keys(packet)
    if found:
        raise ForbiddenKeyInPacket(",".join(found))
    return packet


def _replay_block(replay: Optional[Mapping[str, Any]], recommendation: str, corpus_eligible: int) -> Dict[str, Any]:
    if not replay:
        return {"available": False, "current_compatible": False, "reason": "NO_REPLAY_RUN_OR_PATTERN_NOT_IN_REPLAY"}
    m = dict(replay.get("metrics") or {})
    approve = recommendation == APPROVE_RECOMMENDED
    first_pos = m.get("first_approve_recommended_position") if approve else m.get("first_reject_recommended_position")
    first_date = m.get("first_approve_recommended_date") if approve else m.get("first_reject_recommended_date")
    persistence = m.get("approve_persistence_ratio") if approve else m.get("reject_persistence_ratio")
    captured = int(replay.get("captured_eligible", 0) or 0)
    stress = dict(replay.get("stress") or {})
    block: Dict[str, Any] = {
        "available": True,
        "replay_run_id": str(replay.get("run_id", "")), "replay_run_digest": str(replay.get("run_digest", "")),
        "captured_eligible": captured,
        "replay_current_recommendation": str(m.get("current_recommendation", "")),
        "current_compatible": bool(replay.get("current_compatible")),
        "compatibility_reasons": list(replay.get("compatibility_reasons") or []),
        "first_recommendation_position": first_pos, "first_recommendation_date": first_date,
        "persistence_ratio": persistence, "reversal_count": m.get("recommendation_reversal_count"),
        "eligible_documents_in_current_state": m.get("eligible_documents_in_current_state"),
        "stability_class": str(m.get("stability_class", "")), "calibration_state": str(m.get("calibration_state", "")),
        "worst_consistency_observed": m.get("worst_consistency_observed"),
        "positions_with_time_high": m.get("positions_with_time_high"),
        "positions_with_cross_regime_high": m.get("positions_with_cross_regime_high"),
        "first_surfaced_in_main_position": m.get("first_surfaced_in_main_position"),
        "evidence_age_eligible_docs": max(0, int(corpus_eligible) - captured),
        "stress": {k: stress.get(k) for k in (
            "appeared_only_after_100", "reversions", "first_material_contradiction_position", "reject_driver",
            "contradiction_recovery_positions", "was_review_before_reject", "recommendation_before_reject",
            "contradiction_at_reject", "dna_conflicts_at_reject") if k in stress},
        "boundary": "NOT_PREDICTIVE: persistence measures rule consistency, not forecast quality",
    }
    return block


# ------------------------------------------------------------------ digests
# corpus 件数（corpus_size / corpus_milestone / corpus_eligible_at_build / age）は corpus 増加だけで変わるので
# freshness anchor に含めない（凍結: corpus-only growth は stale にしない）。gate flag は含める。
EVIDENCE_VIEW_EXCLUDED = ("built_at", "packet_id", "packet_evidence_digest", "corpus_eligible_at_build",
                          "evidence_age_eligible_docs", "informational_only", "corpus_size", "corpus_milestone")


def evidence_view(packet: Mapping[str, Any]) -> Dict[str, Any]:
    """packet_evidence_digest の対象: 人間が見る証拠すべて。生成時刻・corpus 件数（増加は stale にしない）・
    そこから派生する age・evaluation_id / inputs_digest（corpus_size を含む）は除外。"""
    def strip(obj: Any) -> Any:
        if isinstance(obj, Mapping):
            return {k: strip(v) for k, v in obj.items() if k not in EVIDENCE_VIEW_EXCLUDED
                    and k not in ("evaluation_id", "inputs_digest", "replay_run_id")}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj
    view = {k: strip(v) for k, v in packet.items() if k not in ("warnings", "ordering")}
    # shadow history は「現在状態 + 履歴 digest」で束縛する（本文は表示用に残す）
    sh = dict(packet.get("shadow_history") or {})
    view["shadow_history"] = {"current_review": strip(sh.get("current_review")), "history_digest": sh.get("history_digest"),
                              "event_count": sh.get("event_count")}
    return view


def packet_evidence_digest(packet: Mapping[str, Any]) -> str:
    return digest16(evidence_view(packet))


def packet_id_for(pattern_id: str, evidence_digest: str, schema_version: str, formal_policy_digest: str) -> str:
    return PACKET_ID_PREFIX + hashlib.sha256(
        f"{pattern_id}|{evidence_digest}|{schema_version}|{formal_policy_digest}".encode("utf-8")).hexdigest()[:16]


def shadow_history_block(events: Sequence[Mapping[str, Any]], current_review: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    history = [{"shadow_review_id": str(e.get("shadow_review_id", "")), "reviewed_at": str(e.get("reviewed_at", "")),
                "review_outcome": str(e.get("review_outcome", "")),
                "recommendation_at_review": str(e.get("recommendation_at_review", "")),
                "related_pattern_id": str(e.get("related_pattern_id", "")), "reason": str(e.get("reason", "")),
                "reviewer_id": str(e.get("reviewer_id", ""))} for e in events]
    return {"event_count": len(history), "outcome_history": history,
            "history_digest": digest16([{k: h[k] for k in ("shadow_review_id", "review_outcome", "recommendation_at_review",
                                                          "related_pattern_id")} for h in history]),
            "current_review": dict(current_review) if current_review else None}
