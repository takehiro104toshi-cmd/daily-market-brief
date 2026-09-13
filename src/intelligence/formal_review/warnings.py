"""Warning codes（Phase 3.9.5）— 表示と並び順にだけ効く。新しい自動 gate は作らない。"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from ..evaluation.models import APPROVE_RECOMMENDED
from .config import APPROVED, FormalReviewPolicy
from .groups import opposite_members

W_RECENT_TRANSITION = "W_RECENT_TRANSITION"
W_OSCILLATING = "W_OSCILLATING"
W_INSUFFICIENT_HISTORY = "W_INSUFFICIENT_HISTORY"
W_MOSTLY_STABLE_SHOW_HISTORY = "W_MOSTLY_STABLE_SHOW_HISTORY"
W_REPLAY_EVIDENCE_AGE = "W_REPLAY_EVIDENCE_AGE"
W_REPLAY_EVIDENCE_MISSING = "W_REPLAY_EVIDENCE_MISSING"
W_REPLAY_EVIDENCE_NOT_CURRENT = "W_REPLAY_EVIDENCE_NOT_CURRENT"
W_SIBLING_OPPOSITE_APPROVED = "W_SIBLING_OPPOSITE_APPROVED"                 # C1 が block する
W_SIBLING_OPPOSITE_APPROVE_RECOMMENDED = "W_SIBLING_OPPOSITE_APPROVE_RECOMMENDED"   # C3 acknowledgement が要る
W_SHADOW_DISAGREEMENT_HISTORY = "W_SHADOW_DISAGREEMENT_HISTORY"
W_DNA_CONFLICT = "W_DNA_CONFLICT"
W_CONTRADICTION_ACTIVE = "W_CONTRADICTION_ACTIVE"
W_APPEARED_ONLY_AFTER_100 = "W_APPEARED_ONLY_AFTER_100"

ORDER = (W_SIBLING_OPPOSITE_APPROVED, W_SIBLING_OPPOSITE_APPROVE_RECOMMENDED, W_REPLAY_EVIDENCE_MISSING,
         W_REPLAY_EVIDENCE_NOT_CURRENT, W_OSCILLATING, W_INSUFFICIENT_HISTORY, W_RECENT_TRANSITION,
         W_MOSTLY_STABLE_SHOW_HISTORY, W_REPLAY_EVIDENCE_AGE, W_DNA_CONFLICT, W_CONTRADICTION_ACTIVE,
         W_APPEARED_ONLY_AFTER_100, W_SHADOW_DISAGREEMENT_HISTORY)


def compute_warnings(packet: Mapping[str, Any], policy: FormalReviewPolicy) -> List[Dict[str, Any]]:
    out: Dict[str, str] = {}
    replay = dict(packet.get("replay") or {})
    stability = str(replay.get("stability_class", ""))
    if replay.get("available"):
        if stability == "RECENT_TRANSITION" and policy.warn_recent_transition:
            out[W_RECENT_TRANSITION] = "recommendation entered its current state recently (eligible documents); evidence gates are satisfied"
        if stability == "OSCILLATING" and policy.warn_oscillating:
            out[W_OSCILLATING] = "recommendation reversed at least twice in replay; likely KEEP_REVIEWING unless the reason states why"
        if stability == "INSUFFICIENT_HISTORY" and policy.warn_insufficient_history:
            out[W_INSUFFICIENT_HISTORY] = "replay history is shorter than the calibrated persistence unit"
        if stability == "MOSTLY_STABLE":
            out[W_MOSTLY_STABLE_SHOW_HISTORY] = "one reversal observed; review the replay history"
        if int(replay.get("evidence_age_eligible_docs", 0) or 0) >= policy.replay_evidence_age_warning_eligible_docs:
            out[W_REPLAY_EVIDENCE_AGE] = "replay evidence predates the current corpus by at least one transition interval"
        if not replay.get("current_compatible"):
            out[W_REPLAY_EVIDENCE_NOT_CURRENT] = "replay evidence is not compatible with the current policies or recommendation"
        if (dict(replay.get("stress") or {})).get("appeared_only_after_100"):
            out[W_APPEARED_ONLY_AFTER_100] = "first became APPROVE_RECOMMENDED only after CORPUS_100"
    else:
        out[W_REPLAY_EVIDENCE_MISSING] = "no replay evidence for this pattern; APPROVED / REJECTED are blocked"
    group = dict(packet.get("group") or {})
    for m in opposite_members(group):
        if m.get("decision_state") == APPROVED:
            out[W_SIBLING_OPPOSITE_APPROVED] = f"opposite-direction sibling {m['pattern_id']} is formally APPROVED"
        elif m.get("recommendation") == APPROVE_RECOMMENDED:
            out[W_SIBLING_OPPOSITE_APPROVE_RECOMMENDED] = f"opposite-direction sibling {m['pattern_id']} is APPROVE_RECOMMENDED and undecided"
    consistency = dict(packet.get("consistency") or {})
    if int(consistency.get("dna_conflicts", 0) or 0) > 0:
        out[W_DNA_CONFLICT] = "pattern conflicts with an existing Compass DNA rule"
    if consistency.get("contradiction_active"):
        out[W_CONTRADICTION_ACTIVE] = "a contradiction indicator is active in the current evaluation"
    sh = dict(packet.get("shadow_history") or {})
    if any(h.get("review_outcome") == "DISAGREE" for h in sh.get("outcome_history") or []):
        out[W_SHADOW_DISAGREEMENT_HISTORY] = "a human shadow review disagreed with an earlier recommendation (evidence only)"
    return [{"code": code, "message": out[code]} for code in ORDER if code in out]
