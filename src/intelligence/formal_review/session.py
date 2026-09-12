"""First human formal review session（Phase 3.9.5）— 人間が 1 pattern ずつ読むための決定的な提示。

packet に既にある事実だけを短い文へ変換する（narrative 生成も推論もしない）。助言表現
（should be approved / safe to approve など）は語彙として禁止し、test で機械的に検査する。
人間の Shadow Review reason 本文は brief に載せない（件数・現在 outcome・履歴 digest のみ）。

この module は読み取り専用である。Decision も derived artifact も書かない。real write は
CLI の 2 段階（dry-run → 明示 confirmation token）を経て `DecisionService` だけが行う。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..evaluation.config import AXES
from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED
from .config import APPROVED, KEEP_REVIEWING, REJECTED
from .groups import blocking_approved_siblings, pending_approve_acknowledgements

SESSION_SCHEMA_VERSION = "1.0.0"
CONFIRM_PREFIX = "CONFIRM"

#: 提示に現れてはならない助言表現（機械推奨を人間の判断へすり替える言い回し）。
FORBIDDEN_ADVISORY: Tuple[str, ...] = (
    "should be approved", "should be rejected", "should approve", "should reject",
    "safe to approve", "safe to reject", "clearly reject", "clearly approve",
    "recommend approving", "recommend rejecting", "we suggest", "you should",
    "obviously", "no need to review",
)

#: reject driver code → 事実としての説明句（packet の値だけから引く）。
REJECT_DRIVER_PHRASES: Dict[str, str] = {
    "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION": "repeated supporting-document directional contradiction",
    "NARROW_SIBLING_CONTRADICTION": "directional contradiction with a narrow sibling pattern",
    "DNA_CONFLICT": "conflict with an existing Compass DNA rule",
}

HUMAN_DECISION_REQUIRED = "Human formal decision required"
EVIDENCE_ONLY_NOTE = "This presentation is evidence only; it does not select an action."

APPROVE_QUESTIONS: Tuple[Tuple[str, str], ...] = (
    ("A1", "Do I understand what this pattern claims?"),
    ("A2", "Is the machine evidence internally consistent with that claim?"),
    ("A3", "Does replay show sufficiently persistent behaviour that the recommendation is not a one-document artifact?"),
    ("A4", "Is there any DNA relation or group context that makes formal approval premature?"),
    ("A5", "Do I choose APPROVED or KEEP_REVIEWING?"),
    ("A6", "Write a substantive reason (at least 20 characters, not the recommendation label)."),
)
REJECT_QUESTIONS: Tuple[Tuple[str, str], ...] = (
    ("R1", "Do I understand the contradiction or reject driver?"),
    ("R2", "Is the contradiction still active?"),
    ("R3", "Has replay shown any recovery?"),
    ("R4", "Would formal REJECTED remove a genuinely contradictory or unreliable pattern, rather than one I merely dislike?"),
    ("R5", "Do I choose REJECTED or KEEP_REVIEWING?"),
    ("R6", "Write a substantive reason (at least 20 characters, not the recommendation label)."),
)


def confirmation_token(decision_type: str, pattern_id: str) -> str:
    """real write に必要な明示 confirmation（例: `CONFIRM APPROVED cpt_x`）。偶然一致しない形にする。"""
    return f"{CONFIRM_PREFIX} {decision_type} {pattern_id}"


def assert_no_advisory_language(payload: Any) -> None:
    blob = json.dumps(payload, ensure_ascii=False, default=str).lower()
    hits = sorted({phrase for phrase in FORBIDDEN_ADVISORY if phrase in blob})
    if hits:
        raise ValueError(f"advisory language is not allowed in the review presentation: {hits}")


def _replay(packet: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(packet.get("replay") or {})


def _stress(packet: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(_replay(packet).get("stress") or {})


def allowed_human_actions(packet: Mapping[str, Any]) -> List[str]:
    return [str(a) for a in (packet.get("decision") or {}).get("allowed_next_actions") or []]


def sibling_status(packet: Mapping[str, Any]) -> Dict[str, Any]:
    """C1 / C3 の予測（guard.py が権威。ここは人間へ先に見せるだけ）。"""
    group = dict(packet.get("group") or {})
    blocking = blocking_approved_siblings(group)
    pending = pending_approve_acknowledgements(group)
    approve_candidate = str((packet.get("recommendation") or {}).get("recommendation", "")) == APPROVE_RECOMMENDED
    return {
        "sibling_group_key": str(group.get("sibling_group_key", "")),
        "group_size": len(group.get("members") or []) + 1 if group.get("sibling_group_key") else 0,
        "member_count": len(group.get("members") or []),
        "opposite_direction_members": [
            {"pattern_id": m["pattern_id"], "direction": m.get("direction", ""), "recommendation": m.get("recommendation", ""),
             "decision_state": m.get("decision_state", "") or "NONE"}
            for m in group.get("members") or [] if m.get("relationship") == "OPPOSITE"],
        "member_decision_states": {str(m["pattern_id"]): str(m.get("decision_state", "") or "NONE")
                                   for m in group.get("members") or []},
        "C1_blocking_approved_siblings": blocking,
        "C1_status": ("APPROVED_BLOCKED_BY_OPPOSITE_SIBLING" if (approve_candidate and blocking)
                      else "CLEAR" if approve_candidate else "NOT_APPLICABLE_FOR_THIS_ACTION"),
        "C3_acknowledgement_required_for": pending,
        "C3_status": ("ACKNOWLEDGEMENT_REQUIRED" if (approve_candidate and pending)
                      else "NOT_REQUIRED" if approve_candidate else "NOT_APPLICABLE_FOR_THIS_ACTION"),
        "group_state_digest": str(group.get("group_state_digest", "")),
    }


def candidate_brief(packet: Mapping[str, Any], *, queue_rank: Optional[int] = None, section: str = "") -> Dict[str, Any]:
    """人間 1 人が 1 candidate を判断するために見る 10 節。原文・path・human reason 本文は含めない。"""
    identity, rec = dict(packet.get("identity") or {}), dict(packet.get("recommendation") or {})
    axes, consistency = dict(packet.get("axes") or {}), dict(packet.get("consistency") or {})
    dna, decision = dict(packet.get("dna") or {}), dict(packet.get("decision") or {})
    replay, stress = _replay(packet), _stress(packet)
    shadow = dict(packet.get("shadow_history") or {})
    is_reject = str(rec.get("recommendation", "")) == REJECT_RECOMMENDED
    brief: Dict[str, Any] = {
        "session_schema_version": SESSION_SCHEMA_VERSION,
        "1_identity": {
            "queue_rank": queue_rank, "section": section or str(rec.get("recommendation", "")),
            "pattern_id": identity.get("pattern_id"), "pattern_type": identity.get("pattern_type"),
            "lifecycle": identity.get("lifecycle_status"), "packet_id": identity.get("packet_id"),
        },
        "2_recommendation": {
            "machine_recommendation": rec.get("recommendation"), "triggered_rule": rec.get("triggered_rule"),
            "supporting_rules": list(rec.get("supporting_rules") or []),
            "blocking_rules": list(rec.get("blocking_rules") or []),
            "formal_review_gate_reached": rec.get("formal_review_gate_reached"),
            "corpus_size": rec.get("corpus_size"), "corpus_milestone": rec.get("corpus_milestone"),
        },
        "3_evidence": {
            "eligible_support": axes.get("eligible_support"), "support_count": axes.get("support_count"),
            "span_days": axes.get("span_days"), "distinct_calendar_months": axes.get("distinct_calendar_months"),
            "distinct_2d_cells": axes.get("distinct_2d_cells"), "confirmed_2d_cells": axes.get("confirmed_2d_cells"),
            "regime_coverage_count": len(axes.get("regime_coverage") or []),
            "document_qualities": dict(axes.get("document_qualities") or {}), "valid_ratio": axes.get("valid_ratio"),
            "axis_states": {a: (axes.get("states") or {}).get(a) for a in AXES},
            "axis_applicability": {a: (axes.get("applicability") or {}).get(a) for a in AXES},
            "axis_reasons": {a: (axes.get("reasons") or {}).get(a) for a in AXES},
            "reference_score_note": (packet.get("reference") or {}).get("label"),
        },
        "4_replay": {
            "available": replay.get("available"), "current_compatible": replay.get("current_compatible"),
            "compatibility_reasons": list(replay.get("compatibility_reasons") or []),
            "first_recommendation_position": replay.get("first_recommendation_position"),
            "first_recommendation_date": replay.get("first_recommendation_date"),
            "persistence_ratio": replay.get("persistence_ratio"), "reversal_count": replay.get("reversal_count"),
            "eligible_documents_in_current_state": replay.get("eligible_documents_in_current_state"),
            "stability_class": replay.get("stability_class"), "calibration_state": replay.get("calibration_state"),
            "worst_consistency_observed": replay.get("worst_consistency_observed"),
            "positions_with_time_high": replay.get("positions_with_time_high"),
            "positions_with_cross_regime_high": replay.get("positions_with_cross_regime_high"),
            "first_surfaced_in_main_position": replay.get("first_surfaced_in_main_position"),
            "evidence_age_eligible_docs": replay.get("evidence_age_eligible_docs"),
            "replay_run_digest": replay.get("replay_run_digest"),
            "appeared_only_after_100": stress.get("appeared_only_after_100"),
            "reversions": stress.get("reversions"),
        },
        "5_dna_relation": {
            "classification": dna.get("classification"), "best_rule_id": dna.get("best_rule_id"),
            "direction_relation": dna.get("direction_relation"), "candidate_rule_count": dna.get("candidate_rule_count"),
            "conflict_count": dna.get("conflict_count"), "conflict_rule_ids": list(dna.get("conflict_rule_ids") or []),
            "boundary": dna.get("boundary"),
        },
        "6_contradiction": {
            "applies_to": "REJECT_RECOMMENDED candidates" if is_reject else "shown for completeness",
            "reject_driver": stress.get("reject_driver"),
            "first_material_contradiction_position": stress.get("first_material_contradiction_position"),
            "contradiction_recovery_positions": stress.get("contradiction_recovery_positions"),
            "was_review_before_reject": stress.get("was_review_before_reject"),
            "recommendation_before_reject": stress.get("recommendation_before_reject"),
            "currently_active": consistency.get("contradiction_active"),
            "document_contradiction": consistency.get("document_contradiction"),
            "document_contradiction_repeated": consistency.get("document_contradiction_repeated"),
            "narrow_sibling_contradiction": consistency.get("narrow_sibling_contradiction"),
            "narrow_sibling_repeated": consistency.get("narrow_sibling_repeated"),
            "dna_conflicts": consistency.get("dna_conflicts"),
            "direction_counts": dict(consistency.get("direction_counts") or {}),
            "direction_class": consistency.get("direction_class"),
        },
        "7_group_context": sibling_status(packet),
        "8_human_history": {                       # reason 本文は載せない（件数・現在 outcome・digest のみ）
            "shadow_review_event_count": shadow.get("event_count"),
            "current_outcome": (dict(shadow.get("current_review") or {})).get("last_outcome", "") or "NONE",
            "history_digest": shadow.get("history_digest"),
            "related_pattern_reference_count": sum(1 for h in shadow.get("outcome_history") or [] if h.get("related_pattern_id")),
            "note": "human review reason text stays inside the packet file and is not shown in this presentation",
        },
        "9_decision_state": {
            "current_formal_state": decision.get("current_state"), "head_decision_id": decision.get("head_decision_id"),
            "history_length": decision.get("history_length"), "promotion_status": decision.get("promotion_status"),
            "allowed_actions": allowed_human_actions(packet),
            "reopen_status": (dict(decision.get("reopen") or {})).get("status"),
        },
        "10_warnings": [dict(w) for w in packet.get("warnings") or []],
        "freshness": {
            "packet_evidence_digest": (packet.get("freshness") or {}).get("packet_evidence_digest"),
            "material_digest": (packet.get("freshness") or {}).get("material_digest"),
            "note": "the packet is revalidated immediately before any write; a changed digest blocks the decision",
        },
    }
    assert_no_advisory_language(brief)
    return brief


def explanation(packet: Mapping[str, Any]) -> List[str]:
    """packet の事実だけを短い文へ変換する（決定的・同じ packet なら常に同じ文）。"""
    rec = dict(packet.get("recommendation") or {})
    axes = dict(packet.get("axes") or {})
    consistency = dict(packet.get("consistency") or {})
    dna = dict(packet.get("dna") or {})
    replay, stress = _replay(packet), _stress(packet)
    recommendation = str(rec.get("recommendation", ""))
    lines: List[str] = [f"Machine recommendation is {recommendation} under rule {rec.get('triggered_rule', '')}."]

    if not replay.get("available"):
        lines.append("No replay evidence is available for this pattern; APPROVED and REJECTED are blocked until it exists.")
    elif not replay.get("current_compatible"):
        reasons = ", ".join(str(r) for r in replay.get("compatibility_reasons") or []) or "unspecified"
        lines.append(f"Replay evidence is not compatible with the current policies ({reasons}); APPROVED and REJECTED are blocked.")
    else:
        pos, date = replay.get("first_recommendation_position"), replay.get("first_recommendation_date")
        short = "APPROVE" if recommendation == APPROVE_RECOMMENDED else "REJECT" if recommendation == REJECT_RECOMMENDED else recommendation
        if recommendation == REJECT_RECOMMENDED:
            driver = REJECT_DRIVER_PHRASES.get(str(stress.get("reject_driver", "")), "a recorded contradiction")
            recovery = list(stress.get("contradiction_recovery_positions") or [])
            tail = f"and has recovered at eligible positions {recovery}" if recovery else "and has not recovered"
            lines.append(f"Recommendation became {short} at eligible position {pos} ({date}) due to {driver} {tail}.")
        else:
            lines.append(f"Recommendation became {short} at eligible position {pos} ({date}) and has remained {short} "
                         f"through the current replay with {replay.get('reversal_count')} reversals.")
        lines.append(f"Persistence ratio in the current state is {replay.get('persistence_ratio')} over "
                     f"{replay.get('eligible_documents_in_current_state')} eligible documents; stability class is "
                     f"{replay.get('stability_class')} under calibration {replay.get('calibration_state')}.")
        if int(replay.get("evidence_age_eligible_docs") or 0) > 0:
            lines.append(f"Replay evidence predates the current corpus by {replay.get('evidence_age_eligible_docs')} eligible documents.")
        if stress.get("appeared_only_after_100"):
            lines.append("This recommendation first appeared only after the corpus passed 100 eligible documents.")

    lines.append(f"Evidence: {axes.get('eligible_support')} eligible supporting documents over {axes.get('span_days')} days "
                 f"across {axes.get('distinct_calendar_months')} calendar months and {axes.get('distinct_2d_cells')} market-regime cells.")
    if consistency.get("contradiction_active"):
        active = [name for name, flag in (("document contradiction", consistency.get("document_contradiction")),
                                          ("repeated document contradiction", consistency.get("document_contradiction_repeated")),
                                          ("narrow sibling contradiction", consistency.get("narrow_sibling_contradiction")),
                                          ("DNA conflict", int(consistency.get("dna_conflicts") or 0) > 0)) if flag]
        lines.append("Contradiction indicators currently active: " + ", ".join(active) + ".")
    else:
        lines.append("No contradiction indicator is active in the current evaluation.")
    rule = f" (closest rule {dna.get('best_rule_id')}, direction relation {dna.get('direction_relation')})" if dna.get("best_rule_id") else ""
    lines.append(f"DNA relation is {dna.get('classification')}{rule}; a formal decision never edits Compass DNA.")
    sib = sibling_status(packet)
    if sib["member_count"]:
        opposite = len(sib["opposite_direction_members"])
        lines.append(f"Sibling group has {sib['member_count']} other member(s), of which "
                     f"{opposite} {'is' if opposite == 1 else 'are'} opposite-direction.")
        if sib["C1_blocking_approved_siblings"]:
            lines.append(f"An opposite-direction sibling is already formally APPROVED, so APPROVED is blocked here: "
                         f"{sib['C1_blocking_approved_siblings']}.")
        if sib["C3_acknowledgement_required_for"]:
            lines.append(f"APPROVED requires explicit acknowledgement of undecided opposite-direction sibling(s): "
                         f"{sib['C3_acknowledgement_required_for']}.")
    else:
        lines.append("This pattern has no sibling group member under the frozen EVIDENCE_OUTLOOK relation.")
    actions = allowed_human_actions(packet)
    lines.append(f"{HUMAN_DECISION_REQUIRED}: choose one of {actions}. {EVIDENCE_ONLY_NOTE}")
    assert_no_advisory_language(lines)
    return lines


def review_questions(packet: Mapping[str, Any]) -> List[Dict[str, str]]:
    recommendation = str((packet.get("recommendation") or {}).get("recommendation", ""))
    questions = REJECT_QUESTIONS if recommendation == REJECT_RECOMMENDED else APPROVE_QUESTIONS
    return [{"id": qid, "question": text} for qid, text in questions]


def decision_commands(packet: Mapping[str, Any], *, actor: str = "<human-actor-id>") -> List[Dict[str, Any]]:
    """各許可 action の 2 段階 command（stage 1 dry-run → stage 2 confirmation token 付き real write）。"""
    identity = dict(packet.get("identity") or {})
    pid, packet_id = identity.get("pattern_id", ""), identity.get("packet_id", "")
    acks = pending_approve_acknowledgements(dict(packet.get("group") or {}))
    out: List[Dict[str, Any]] = []
    for decision_type in allowed_human_actions(packet):
        action = {APPROVED: "approve", REJECTED: "reject", KEEP_REVIEWING: "keep-reviewing",
                  "REOPENED_FOR_REVIEW": "reopen", "SUPERSEDED": "supersede", "RETIRED": "retire"}.get(decision_type, "")
        ack_flags = "".join(f" --acknowledge-sibling {a}" for a in acks) if decision_type == APPROVED else ""
        base = (f"python -m src.intelligence.formal_review.cli decide {pid} --packet {packet_id} "
                f"--action {action} --reason \"<substantive human reason>\" --actor {actor}{ack_flags}")
        out.append({"decision_type": decision_type, "action": action,
                    "stage_1_dry_run": base + " --dry-run",
                    "stage_2_real_write": base + f" --confirm \"{confirmation_token(decision_type, pid)}\"",
                    "confirmation_token": confirmation_token(decision_type, pid),
                    "acknowledge_siblings_required": acks if decision_type == APPROVED else []})
    return out


def candidate_step(packet: Mapping[str, Any], *, queue_rank: Optional[int] = None, section: str = "",
                   actor: str = "<human-actor-id>") -> Dict[str, Any]:
    return {"brief": candidate_brief(packet, queue_rank=queue_rank, section=section),
            "explanation": explanation(packet), "review_questions": review_questions(packet),
            "commands": decision_commands(packet, actor=actor)}


SESSION_RULES: Tuple[str, ...] = (
    "ONE_PATTERN_AT_A_TIME: every decision is a separate invocation; no batch command exists",
    "TWO_STAGE: stage 1 is --dry-run, stage 2 repeats the same action with the exact confirmation token",
    "NO_DEFAULT_ACTION: the human selects the action; nothing is pre-selected",
    "PACKET_BOUND: the decision is accepted only against the packet id the human reviewed",
    "REBUILD_BETWEEN_DECISIONS: rebuild the queue after each write so the next packet is fresh",
    "NOT_PROMOTED: every formal decision stays NOT_PROMOTED; Compass DNA is never edited here",
)


def session_plan(queue: Mapping[str, Any], packets: Mapping[str, Mapping[str, Any]], *,
                 actor: str = "<human-actor-id>", sections: Sequence[str] = ()) -> Dict[str, Any]:
    """queue の凍結順（REJECT → APPROVE → REOPEN）そのままの session 手順。並べ替えない。"""
    order = list(sections) or [s for s in (queue.get("section_order") or (queue.get("sections") or {}).keys())]
    steps: List[Dict[str, Any]] = []
    for section in order:
        for row in (queue.get("sections") or {}).get(section, []):
            pid = str(row.get("pattern_id"))
            packet = packets.get(pid)
            if packet is None:
                continue
            steps.append({"step": len(steps) + 1, "section": section, "queue_rank": row.get("queue_rank"),
                          **candidate_step(packet, queue_rank=row.get("queue_rank"), section=section, actor=actor)})
    plan = {"session_schema_version": SESSION_SCHEMA_VERSION, "built_at": queue.get("built_at"),
            "total_steps": len(steps), "rules": list(SESSION_RULES),
            "section_order": order, "steps": steps,
            "context_patterns": [{"pattern_id": c.get("pattern_id"), "recommendation": c.get("recommendation"),
                                  "role": c.get("role")} for c in queue.get("context") or []],
            "deferred_patterns": [{"pattern_id": d.get("pattern_id"), "recommendation": d.get("recommendation"),
                                   "decision_state": d.get("decision_state"), "queue_status": d.get("queue_status"),
                                   "role": d.get("role")} for d in queue.get("deferred") or []],
            "note": "context patterns are evidence for sibling reasoning and cannot be decided from this queue; "
                    "deferred KEEP_REVIEWING patterns are not ranked here but remain decidable"}
    assert_no_advisory_language(plan["rules"])
    return plan
