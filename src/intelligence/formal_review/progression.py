"""Queue progression（Phase 3.9.5 / formal_review 1.1.0）— KEEP_REVIEWING candidate の提示制御。READ-ONLY。

監督者採択: D「zero-new-storage hybrid」+ packet 構築後・`order_queue()` 前の queue post-filter。
新しい store も Decision state も作らない。baseline は既存の KEEP_REVIEWING Decision row
（metadata.material_digest / metadata.group_state_digest / metadata.replay_run_id / evidence snapshot）だけを読む。

review-relevant change の 4 成分（凍結・config.PROGRESSION_REENTRY_COMPONENTS）:
  M1 MACHINE EVIDENCE : 現在の material_digest（Phase 3.9.3 凍結 semantics）≠ reviewed material_digest
  M2 GROUP / SIBLING  : 現在の group_state_digest ≠ reviewed group_state_digest（sibling の Decision が reviewed head より
                        新しければ SIBLING_DECIDED_SINCE_REVIEW も併記）
  M3 REPLAY REVIEW VIEW: reviewed replay run の {stability_class, reversal_count, reject_driver, recovery_count,
                        current_recommendation} ≠ 現在の compatible replay の同 5 field（run id / digest だけの違いは無視）
  M4 DNA RELATION     : reviewed Decision evidence snapshot の {dna_classification, best_rule_id, conflict_rule_ids}
                        ≠ 現在の DNA relation（evidence snapshot と同じ導出: dna_comparisons 末尾 + conflicts）

derived queue status（Decision state ではない・enum にも transition 表にも入れない）:
  NOT_APPLICABLE / DEFERRED_UNCHANGED_KEEP_REVIEWING / REENTERED_KEEP_REVIEWING / PROGRESSION_UNVERIFIABLE
fail closed = **抑止しない**: 不変を積極的に確定できた時だけ DEFERRED。baseline 欠落・replay 不読・snapshot 不完全・
比較不能はすべて UNVERIFIABLE で可視のまま。本 module は Decision / Shadow / DNA / corpus / derived のどれにも書かない。
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .config import (
    KEEP_REVIEWING,
    PROGRESSION_DNA_RELATION_FIELDS,
    PROGRESSION_REPLAY_REVIEW_FIELDS,
)

# ------------------------------------------------------------------ derived queue statuses（NOT decision states）
QS_NOT_APPLICABLE = "NOT_APPLICABLE"
QS_DEFERRED = "DEFERRED_UNCHANGED_KEEP_REVIEWING"
QS_REENTERED = "REENTERED_KEEP_REVIEWING"
QS_UNVERIFIABLE = "PROGRESSION_UNVERIFIABLE"
QUEUE_STATUSES: Tuple[str, ...] = (QS_NOT_APPLICABLE, QS_DEFERRED, QS_REENTERED, QS_UNVERIFIABLE)

SUPPRESSION_UNCHANGED = "UNCHANGED_SINCE_KEEP_REVIEWING_DECISION"

# reason codes（人間 reason 本文・path・原文は決して含めない）
R_M1_CHANGED = "M1_MATERIAL_DIGEST_CHANGED"
R_M2_CHANGED = "M2_GROUP_STATE_CHANGED"
R_M2_SIBLING_DECIDED = "SIBLING_DECIDED_SINCE_REVIEW"
R_M3_PREFIX = "M3_REPLAY_REVIEW_VIEW_CHANGED:"
R_M4_PREFIX = "M4_DNA_RELATION_CHANGED:"
U_M1_BASELINE = "M1_MATERIAL_BASELINE_MISSING"
U_M2_BASELINE = "M2_GROUP_BASELINE_MISSING"
U_M2_CURRENT = "M2_GROUP_STATE_DIGEST_UNAVAILABLE"
U_M3_UNBOUND = "M3_HISTORICAL_REPLAY_RUN_UNBOUND"
U_M3_UNREADABLE = "M3_HISTORICAL_REPLAY_RUN_UNREADABLE"
U_M3_PATTERN_ABSENT = "M3_PATTERN_NOT_IN_HISTORICAL_REPLAY"
U_M3_CURRENT_UNAVAILABLE = "M3_CURRENT_REPLAY_UNAVAILABLE"
U_M3_CURRENT_INCOMPATIBLE = "M3_CURRENT_REPLAY_INCOMPATIBLE"
U_M4_SNAPSHOT = "M4_DECISION_EVIDENCE_SNAPSHOT_INCOMPLETE"
U_M4_CONFLICTS = "M4_CONFLICT_RULE_IDS_UNAVAILABLE"


@dataclass(frozen=True)
class ProgressionResult:
    pattern_id: str
    formal_head: str
    head_decision_id: str = ""
    head_sequence: int = 0
    queue_status: str = QS_NOT_APPLICABLE
    suppression_reason: str = ""
    reentry_reasons: Tuple[str, ...] = ()
    reviewed_material_digest: str = ""
    current_material_digest: str = ""
    reviewed_group_state_digest: str = ""
    current_group_state_digest: str = ""
    reviewed_replay_run_id: str = ""
    current_replay_run_id: str = ""
    replay_view_changed: bool = False
    dna_relation_changed: bool = False
    sibling_decided_since_review: bool = False
    reentry_triggered: bool = False
    unverifiable_reasons: Tuple[str, ...] = ()
    changed_components: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def deferred(self) -> bool:
        return self.queue_status == QS_DEFERRED

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            out[f.name] = list(v) if isinstance(v, tuple) else v
        out["deferred"] = self.deferred
        return out


# ------------------------------------------------------------------ review views（両側を同じ形に正規化する）
def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def replay_review_view_from_summary(summary: Mapping[str, Any], pattern_id: str) -> Optional[Dict[str, Any]]:
    """replay run の summary.json（pattern_metrics + reject_stress）→ review view。pattern 不在なら None。"""
    metrics = dict((dict(summary.get("pattern_metrics") or {})).get(pattern_id) or {})
    if not metrics:
        return None
    stress: Dict[str, Any] = {}
    for section in ("reject_stress", "approve_stress"):
        for item in (dict(summary.get(section) or {})).get("items") or []:
            if str(item.get("pattern_id")) == pattern_id:
                stress = dict(item)
    return _normalize_replay_view({
        "stability_class": metrics.get("stability_class", ""),
        "reversal_count": metrics.get("recommendation_reversal_count"),
        "reject_driver": stress.get("reject_driver", ""),
        "recovery_count": len(list(stress.get("contradiction_recovery_positions") or [])),
        "current_recommendation": metrics.get("current_recommendation", ""),
    })


def replay_review_view_from_packet(replay_block: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """packet["replay"]（available な場合）→ 同じ 5 field の review view。"""
    if not replay_block or not replay_block.get("available"):
        return None
    stress = dict(replay_block.get("stress") or {})
    return _normalize_replay_view({
        "stability_class": replay_block.get("stability_class", ""),
        "reversal_count": replay_block.get("reversal_count"),
        "reject_driver": stress.get("reject_driver", ""),
        "recovery_count": len(list(stress.get("contradiction_recovery_positions") or [])),
        "current_recommendation": replay_block.get("replay_current_recommendation", ""),
    })


def _normalize_replay_view(raw: Mapping[str, Any]) -> Dict[str, Any]:
    return {"stability_class": str(raw.get("stability_class") or ""),
            "reversal_count": _int_or_none(raw.get("reversal_count")),
            "reject_driver": str(raw.get("reject_driver") or ""),
            "recovery_count": int(raw.get("recovery_count") or 0),
            "current_recommendation": str(raw.get("current_recommendation") or "")}


def dna_relation_view(dna_comparison: Mapping[str, Any], conflicts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """現在の DNA relation。decision.evidence.build_evidence_snapshot と同じ導出（末尾 dna_comparison + conflicts）。"""
    return {"dna_classification": str(dna_comparison.get("classification") or ""),
            "best_rule_id": str(dna_comparison.get("best_rule_id") or ""),
            "conflict_rule_ids": sorted({str(c.get("rule_id") or "") for c in conflicts if c.get("rule_id")})}


def dna_relation_from_evidence(evidence: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """reviewed Decision の evidence snapshot → DNA relation。(view, unverifiable_reason)。"""
    ev = dict(evidence or {})
    if not ev or ev.get("pattern_found") is not True:
        return None, U_M4_SNAPSHOT
    if any(key not in ev for key in ("dna_classification", "dna_best_rule_id", "conflict_rule_ids", "conflict_count")):
        return None, U_M4_SNAPSHOT
    ids = ev.get("conflict_rule_ids")
    if not isinstance(ids, (list, tuple)):
        return None, U_M4_SNAPSHOT
    # conflict 行はあるのに rule id が 1 つも残っていない = 比較の信頼性が無い（truncated / unavailable）
    if int(ev.get("conflict_count") or 0) > 0 and not list(ids):
        return None, U_M4_CONFLICTS
    return {"dna_classification": str(ev.get("dna_classification") or ""),
            "best_rule_id": str(ev.get("dna_best_rule_id") or ""),
            "conflict_rule_ids": sorted(str(x) for x in ids)}, ""


# ------------------------------------------------------------------ classification（pure・read-only）
def classify(*, pattern_id: str, head: Optional[Mapping[str, Any]], current_material_digest: str,
             current_group_state_digest: str, current_dna_relation: Mapping[str, Any],
             current_replay_view: Optional[Mapping[str, Any]], current_replay_compatible: bool,
             current_replay_run_id: str, historical_replay_loader: Callable[[str], Optional[Mapping[str, Any]]],
             sibling_member_ids: Sequence[str] = (), decision_records: Sequence[Mapping[str, Any]] = (),
             replay_fields: Sequence[str] = PROGRESSION_REPLAY_REVIEW_FIELDS,
             dna_fields: Sequence[str] = PROGRESSION_DNA_RELATION_FIELDS) -> ProgressionResult:
    """head = pattern の最新 DecisionRecord（as_dict）。KEEP_REVIEWING 以外は NOT_APPLICABLE（通常 primary 挙動）。"""
    head = dict(head or {})
    formal_head = str(head.get("decision_type", "")) or "NONE"
    head_id = str(head.get("decision_id", ""))
    head_seq = int(head.get("sequence") or 0)
    if formal_head != KEEP_REVIEWING:
        return ProgressionResult(pattern_id=pattern_id, formal_head=formal_head, head_decision_id=head_id,
                                 head_sequence=head_seq, queue_status=QS_NOT_APPLICABLE,
                                 current_material_digest=str(current_material_digest or ""),
                                 current_group_state_digest=str(current_group_state_digest or ""),
                                 current_replay_run_id=str(current_replay_run_id or ""))
    metadata = dict(head.get("metadata") or {})
    reentry: List[str] = []
    unverifiable: List[str] = []
    changed: List[str] = []

    # ---- M1 machine evidence（凍結 material_digest そのまま）
    reviewed_material = str(metadata.get("material_digest", ""))
    current_material = str(current_material_digest or "")
    if not reviewed_material:
        unverifiable.append(U_M1_BASELINE)
    elif reviewed_material != current_material:
        reentry.append(R_M1_CHANGED)
        changed.append("M1")

    # ---- M2 group / sibling
    reviewed_group = str(metadata.get("group_state_digest", ""))
    current_group = str(current_group_state_digest or "")
    sibling_decided = any(str(r.get("pattern_id")) in set(sibling_member_ids) and int(r.get("sequence") or 0) > head_seq
                          for r in decision_records)
    if not reviewed_group:
        unverifiable.append(U_M2_BASELINE)
    elif not current_group:
        unverifiable.append(U_M2_CURRENT)
    elif reviewed_group != current_group:
        reentry.append(R_M2_CHANGED)
        changed.append("M2")
        if sibling_decided:
            reentry.append(R_M2_SIBLING_DECIDED)
    elif sibling_decided:                                   # digest 不変なのに sibling Decision が新しい: 保守的に再入
        reentry.append(R_M2_SIBLING_DECIDED)
        changed.append("M2")

    # ---- M3 replay review view（reviewed run を読み、review-relevant 5 field だけ比較）
    reviewed_run = str(metadata.get("replay_run_id", ""))
    replay_changed = False
    if not reviewed_run:
        unverifiable.append(U_M3_UNBOUND)
    else:
        try:
            summary = historical_replay_loader(reviewed_run)
        except Exception:                                    # noqa: BLE001 読めない run は検証不能（抑止しない）
            summary = None
        reviewed_view = replay_review_view_from_summary(summary, pattern_id) if summary else None
        if summary is None:
            unverifiable.append(U_M3_UNREADABLE)
        elif reviewed_view is None:
            unverifiable.append(U_M3_PATTERN_ABSENT)
        elif current_replay_view is None:
            unverifiable.append(U_M3_CURRENT_UNAVAILABLE)
        elif not current_replay_compatible:
            unverifiable.append(U_M3_CURRENT_INCOMPATIBLE)
        else:
            for name in replay_fields:
                if reviewed_view.get(name) != dict(current_replay_view).get(name):
                    reentry.append(R_M3_PREFIX + str(name))
                    replay_changed = True
            if replay_changed:
                changed.append("M3")

    # ---- M4 DNA relation
    reviewed_dna, dna_reason = dna_relation_from_evidence(dict(head.get("evidence") or {}))
    dna_changed = False
    if reviewed_dna is None:
        unverifiable.append(dna_reason)
    else:
        for name in dna_fields:
            if reviewed_dna.get(name) != dict(current_dna_relation).get(name):
                reentry.append(R_M4_PREFIX + str(name))
                dna_changed = True
        if dna_changed:
            changed.append("M4")

    if reentry:
        status, suppression = QS_REENTERED, ""
    elif unverifiable:
        status, suppression = QS_UNVERIFIABLE, ""
    else:
        status, suppression = QS_DEFERRED, SUPPRESSION_UNCHANGED
    return ProgressionResult(
        pattern_id=pattern_id, formal_head=formal_head, head_decision_id=head_id, head_sequence=head_seq,
        queue_status=status, suppression_reason=suppression, reentry_reasons=tuple(reentry),
        reviewed_material_digest=reviewed_material, current_material_digest=current_material,
        reviewed_group_state_digest=reviewed_group, current_group_state_digest=current_group,
        reviewed_replay_run_id=reviewed_run, current_replay_run_id=str(current_replay_run_id or ""),
        replay_view_changed=replay_changed, dna_relation_changed=dna_changed,
        sibling_decided_since_review=sibling_decided, reentry_triggered=bool(reentry),
        unverifiable_reasons=tuple(unverifiable), changed_components=tuple(changed))


def classify_from_packet(*, packet: Mapping[str, Any], head: Optional[Mapping[str, Any]],
                         current_material_digest: str, dna_comparison: Mapping[str, Any],
                         conflicts: Sequence[Mapping[str, Any]],
                         historical_replay_loader: Callable[[str], Optional[Mapping[str, Any]]],
                         decision_records: Sequence[Mapping[str, Any]] = ()) -> ProgressionResult:
    """service 向け便宜関数: 現在側の値を built packet から取り出して classify する。"""
    replay = dict(packet.get("replay") or {})
    group = dict(packet.get("group") or {})
    return classify(
        pattern_id=str(packet["identity"]["pattern_id"]), head=head,
        current_material_digest=current_material_digest,
        current_group_state_digest=str(group.get("group_state_digest", "")),
        current_dna_relation=dna_relation_view(dna_comparison, conflicts),
        current_replay_view=replay_review_view_from_packet(replay),
        current_replay_compatible=bool(replay.get("current_compatible")),
        current_replay_run_id=str(replay.get("replay_run_id", "")),
        historical_replay_loader=historical_replay_loader,
        sibling_member_ids=[str(m.get("pattern_id")) for m in group.get("members") or []],
        decision_records=decision_records)


def deferred_row(packet: Mapping[str, Any], result: ProgressionResult) -> Dict[str, Any]:
    """queue["deferred"] の 1 行（非 ranked・文脈のみ・reason 本文なし）。"""
    replay = dict(packet.get("replay") or {})
    return {"pattern_id": packet["identity"]["pattern_id"], "packet_id": packet["identity"]["packet_id"],
            "pattern_type": packet["identity"]["pattern_type"],
            "recommendation": packet["recommendation"]["recommendation"],
            "decision_state": packet["decision"]["current_state"],
            "head_decision_id": result.head_decision_id, "queue_status": result.queue_status,
            "suppression_reason": result.suppression_reason,
            "reviewed_material_digest": result.reviewed_material_digest,
            "reviewed_group_state_digest": result.reviewed_group_state_digest,
            "reviewed_replay_run_id": result.reviewed_replay_run_id,
            "stability_class": replay.get("stability_class", ""),
            "allowed_next_actions": list(packet["decision"]["allowed_next_actions"]),
            "sibling_group_key": (packet.get("group") or {}).get("sibling_group_key", ""),
            "packet_evidence_digest": packet["freshness"]["packet_evidence_digest"],
            "role": "DEFERRED_NON_RANKED"}


def progression_counts(results: Mapping[str, ProgressionResult]) -> Dict[str, int]:
    return {"suppressed_keep_reviewing_count": sum(1 for r in results.values() if r.queue_status == QS_DEFERRED),
            "reentered_keep_reviewing_count": sum(1 for r in results.values() if r.queue_status == QS_REENTERED),
            "progression_unverifiable_count": sum(1 for r in results.values() if r.queue_status == QS_UNVERIFIABLE)}
