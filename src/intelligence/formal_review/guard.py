"""FormalReviewGuard（Phase 3.9.5）— formal Decision 書き込み前の fail-closed 検査。guard 自身は何も書かない。

検査順（凍結・監督者指示 3〜20）: candidate 存在 → packet 帰属 → recommendation 一致 → symmetry → material →
packet_evidence_digest → policy digest → formal gate → lifecycle → head 不変 → transition → replay evidence →
sibling C1 / C3 → reopen 適格 → HUMAN actor → reason → metadata 制約 → forbidden key。
合格時は Decision metadata（packet binding）を返す。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..corpus_research.lifecycle import PHASE_38_ALLOWED
from ..decision.models import ACTOR_HUMAN, MAX_METADATA_KEYS, MAX_METADATA_VALUE_CHARS
from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED
from ..shadow_review.models import find_forbidden_keys
from .config import (
    APPROVED,
    DISPOSITION_DUPLICATE,
    KEEP_REVIEWING,
    REJECTED,
    REOPENED_FOR_REVIEW,
    SUPERSEDED,
    FormalReviewPolicy,
)
from .errors import (
    ActionNotAllowed,
    ApproveAgainstRecommendationBlocked,
    CandidateMissing,
    DecisionHeadChanged,
    ForbiddenKeyInPacket,
    FormalGateNotReached,
    LifecycleIncompatible,
    MaterialDigestChanged,
    MetadataInvalid,
    NonHumanActor,
    PacketEvidenceDigestChanged,
    PacketPatternMismatch,
    PolicyDigestMismatch,
    ReasonNotSubstantive,
    ReasonTooShort,
    RecommendationMismatch,
    RejectAgainstRecommendationBlocked,
    ReopenNotEligible,
    ReplacementPatternRequired,
    ReplayEvidenceRequired,
    SiblingAcknowledgementRequired,
    SiblingConflictBlocked,
)
from .groups import opposite_members
from .packet import allowed_actions, digest16, evidence_view

LABEL_ONLY = {"APPROVERECOMMENDED", "APPROVED", "APPROVE", "REJECTRECOMMENDED", "REJECTED", "REJECT",
              "KEEPREVIEWING", "OK", "YES", "AGREE"}
QUEUE_HEADS = ("", KEEP_REVIEWING, REOPENED_FOR_REVIEW)


class FormalReviewGuard:
    def __init__(self, policy: FormalReviewPolicy, formal_review_min_corpus: int) -> None:
        self.policy = policy
        self.min_corpus = int(formal_review_min_corpus)

    # ------------------------------------------------------------- main check
    def check(self, *, action: str, pattern_id: str, reviewed: Mapping[str, Any], current: Mapping[str, Any],
              head: Optional[Mapping[str, Any]], corpus_eligible: int, actor_type: str, reason: str,
              acknowledge_siblings: Sequence[str] = (), related_pattern_id: str = "", replacement_pattern_id: str = "",
              reason_category: str = "", disposition: str = "", pattern_ids: Sequence[str] = ()) -> Dict[str, Any]:
        checks: List[str] = []
        # 3. candidate exists
        if pattern_id not in set(pattern_ids):
            raise CandidateMissing(f"pattern {pattern_id} is not in the current registry / evaluation")
        checks.append("CANDIDATE_EXISTS")
        # 4. packet belongs to the candidate
        if reviewed["identity"]["pattern_id"] != pattern_id or current["identity"]["pattern_id"] != pattern_id:
            raise PacketPatternMismatch("packet does not belong to the named pattern")
        checks.append("PACKET_BELONGS_TO_CANDIDATE")
        # 5. recommendation unchanged
        rec_now = current["recommendation"]["recommendation"]
        rec_then = reviewed["recommendation"]["recommendation"]
        if rec_now != rec_then:
            raise RecommendationMismatch(f"recommendation changed {rec_then} -> {rec_now}; rebuild the packet")
        checks.append("RECOMMENDATION_UNCHANGED")
        # 6. symmetry
        if action == APPROVED and rec_now != APPROVE_RECOMMENDED:
            raise ApproveAgainstRecommendationBlocked(f"formal APPROVED requires APPROVE_RECOMMENDED (now {rec_now})")
        if action == REJECTED and rec_now != REJECT_RECOMMENDED:
            raise RejectAgainstRecommendationBlocked(f"formal REJECTED requires REJECT_RECOMMENDED (now {rec_now})")
        checks.append("RECOMMENDATION_SYMMETRY")
        # 7. material digest
        if current["freshness"]["material_digest"] != reviewed["freshness"]["material_digest"]:
            raise MaterialDigestChanged("machine material digest changed since the packet was built")
        checks.append("MATERIAL_DIGEST_UNCHANGED")
        # 8. packet evidence digest（freshness anchor）。何が変わったかを block 単位で診断し、policy digest の変化は
        #    PolicyDigestMismatch、head の変化は DecisionHeadChanged として返す（どれも StaleReviewPacket）。
        if current["freshness"]["packet_evidence_digest"] != reviewed["freshness"]["packet_evidence_digest"]:
            changed = evidence_diff(reviewed, current)
            if dict(current["freshness"]["policy_digests"]) != dict(reviewed["freshness"]["policy_digests"]):
                raise PolicyDigestMismatch(f"policy digests changed since the packet was built (blocks: {changed})")
            if str(current["freshness"]["head_decision_id"]) != str(reviewed["freshness"]["head_decision_id"]):
                raise DecisionHeadChanged(f"a decision was written since the packet was built (blocks: {changed})")
            raise PacketEvidenceDigestChanged(f"the evidence the human reviewed changed (blocks: {changed}); rebuild and re-review")
        checks.append("PACKET_EVIDENCE_DIGEST_UNCHANGED")
        # 9. policy digests
        for key, value in dict(reviewed["freshness"]["policy_digests"]).items():
            if str(current["freshness"]["policy_digests"].get(key, "")) != str(value):
                raise PolicyDigestMismatch(f"{key} policy digest changed since the packet was built")
        checks.append("POLICY_DIGESTS_CURRENT")
        # 10. formal gate（evaluation record と live corpus の両方）
        if not current["recommendation"]["formal_review_gate_reached"] or int(corpus_eligible) < self.min_corpus:
            raise FormalGateNotReached(f"formal review gate requires eligible >= {self.min_corpus}")
        checks.append("FORMAL_GATE_REACHED")
        # 11. lifecycle
        if current["identity"]["lifecycle_status"] not in PHASE_38_ALLOWED:
            raise LifecycleIncompatible(f"lifecycle {current['identity']['lifecycle_status']} is not a Phase 3.8 status")
        checks.append("LIFECYCLE_COMPATIBLE")
        # 12. head unchanged
        head_id = str((head or {}).get("decision_id", ""))
        if head_id != str(reviewed["freshness"]["head_decision_id"]):
            raise DecisionHeadChanged("a decision was written since the packet was built")
        checks.append("DECISION_HEAD_UNCHANGED")
        # 13. transition / allowed action（reopen 適格も含む）
        head_state = str((head or {}).get("decision_type", ""))
        reopen_ok = bool(current["decision"]["reopen"].get("eligible"))
        allowed = allowed_actions(head_state, rec_now, reopen_ok)
        if action not in allowed:
            if action == REOPENED_FOR_REVIEW and head_state == REJECTED and not reopen_ok:
                raise ReopenNotEligible(f"reopen requires a detected material change ({current['decision']['reopen'].get('status')})")
            raise ActionNotAllowed(f"{head_state or 'NONE'} -> {action} not allowed here; allowed: {allowed}")
        checks.append("TRANSITION_ALLOWED")
        # 14. replay evidence
        replay = dict(current.get("replay") or {})
        if action in self.policy.replay_evidence_required_for and not (replay.get("available") and replay.get("current_compatible")):
            raise ReplayEvidenceRequired(f"{action} requires current-compatible replay evidence: "
                                         f"{replay.get('compatibility_reasons') or replay.get('reason')}")
        checks.append("REPLAY_EVIDENCE")
        # 15. sibling C1 / C3（APPROVED のみ）
        acknowledged: List[str] = []
        if action == APPROVED:
            for member in opposite_members(dict(current.get("group") or {})):
                if member.get("decision_state") == APPROVED:
                    raise SiblingConflictBlocked(f"opposite-direction sibling {member['pattern_id']} is formally APPROVED (no override)")
                if member.get("recommendation") == APPROVE_RECOMMENDED and member.get("decision_state", "") in QUEUE_HEADS:
                    if member["pattern_id"] not in set(acknowledge_siblings):
                        raise SiblingAcknowledgementRequired(
                            f"opposite-direction sibling {member['pattern_id']} is APPROVE_RECOMMENDED and undecided; "
                            "acknowledge it explicitly")
                    acknowledged.append(member["pattern_id"])
        checks.append("SIBLING_C1_C3")
        # 16. reopen eligibility（transition で判定済み・明示記録）
        checks.append("REOPEN_ELIGIBILITY")
        # 17. actor
        if actor_type != ACTOR_HUMAN:
            raise NonHumanActor("formal decisions require a HUMAN actor")
        checks.append("ACTOR_HUMAN")
        # 18. reason
        self._check_reason(action, reason, current, reason_category, disposition, related_pattern_id,
                           replacement_pattern_id, pattern_ids)
        checks.append("REASON")
        # 19. metadata
        metadata = self.metadata(action=action, reviewed=reviewed, corpus_eligible_at_write=corpus_eligible,
                                 acknowledged=acknowledged, related_pattern_id=related_pattern_id,
                                 replacement_pattern_id=replacement_pattern_id, reason_category=reason_category,
                                 disposition=disposition)
        checks.append("METADATA")
        # 20. forbidden keys
        found = find_forbidden_keys(current) + find_forbidden_keys(metadata)
        if found:
            raise ForbiddenKeyInPacket(",".join(sorted(set(found))))
        checks.append("FORBIDDEN_KEY_SCAN")
        return {"checks_passed": checks, "metadata": metadata, "acknowledged_siblings": acknowledged}

    # ------------------------------------------------------------- reason
    def _check_reason(self, action: str, reason: str, current: Mapping[str, Any], reason_category: str,
                      disposition: str, related_pattern_id: str, replacement_pattern_id: str,
                      pattern_ids: Sequence[str]) -> None:
        text = str(reason or "").strip()
        minimum = int(self.policy.min_reason_chars.get(action, 20))
        if len(text) < minimum:
            raise ReasonTooShort(f"{action} requires a reason of at least {minimum} characters")
        if re.sub(r"[^A-Za-z]", "", text).upper() in LABEL_ONLY:
            raise ReasonNotSubstantive(f"{action} reason must not be only the recommendation label")
        if action == REJECTED and not current["consistency"]["contradiction_active"]:
            raise RejectAgainstRecommendationBlocked("formal REJECTED requires an active contradiction indicator in the packet")
        if reason_category and reason_category not in self.policy.reason_categories:
            raise ReasonNotSubstantive(f"unknown reason_category {reason_category}")
        if reason_category and action != KEEP_REVIEWING:
            raise ReasonNotSubstantive("reason_category applies to KEEP_REVIEWING only")
        if disposition:
            if disposition != DISPOSITION_DUPLICATE or action != KEEP_REVIEWING:
                raise ReasonNotSubstantive("duplicate/overlap disposition is KEEP_REVIEWING with DUPLICATE_OR_OVERLAPPING only")
            if not related_pattern_id or related_pattern_id == current["identity"]["pattern_id"] \
                    or related_pattern_id not in set(pattern_ids):
                raise ReasonNotSubstantive("DUPLICATE_OR_OVERLAPPING requires a different, existing related_pattern_id")
        if action == SUPERSEDED:
            if not replacement_pattern_id or replacement_pattern_id == current["identity"]["pattern_id"] \
                    or replacement_pattern_id not in set(pattern_ids):
                raise ReplacementPatternRequired("SUPERSEDED requires an existing replacement_pattern_id different from the pattern")

    # ------------------------------------------------------------- metadata binder
    def metadata(self, *, action: str, reviewed: Mapping[str, Any], corpus_eligible_at_write: int,
                 acknowledged: Sequence[str], related_pattern_id: str, replacement_pattern_id: str,
                 reason_category: str, disposition: str) -> Dict[str, str]:
        """Decision metadata（20 key / 500 chars 制約）。凍結層 digest 4 種 + formal review digest は 1 key に
        `layer:digest;...` で束ね、全 binding の canonical digest（metadata_payload_digest）も残す。
        直接 key で残すのは最重要 binding（packet / evidence digest / material / run digest / group / head）。"""
        fresh = dict(reviewed["freshness"])
        replay = dict(reviewed.get("replay") or {})
        digests = dict(fresh.get("policy_digests") or {})
        binding = {
            "packet_id": reviewed["identity"]["packet_id"],
            "packet_schema_version": reviewed["identity"]["packet_schema_version"],
            "packet_evidence_digest": fresh["packet_evidence_digest"], "material_digest": fresh["material_digest"],
            "recommendation": reviewed["recommendation"]["recommendation"], "action": action,
            "policy_digests": digests, "policy_versions": dict(fresh.get("policy_versions") or {}),
            "replay_run_id": replay.get("replay_run_id", ""), "replay_run_digest": replay.get("replay_run_digest", ""),
            "replay_captured_eligible": replay.get("captured_eligible"),
            "group_state_digest": (reviewed.get("group") or {}).get("group_state_digest", ""),
            "stability_class": replay.get("stability_class", ""),
            "corpus_eligible_at_packet": fresh.get("corpus_eligible_at_build"),
            "corpus_eligible_at_write": int(corpus_eligible_at_write),
            "head_decision_id_at_packet": fresh.get("head_decision_id", ""),
            "acknowledged_sibling": list(acknowledged), "disposition": disposition,
            "related_pattern_id": related_pattern_id, "replacement_pattern_id": replacement_pattern_id,
            "reason_category": reason_category,
        }
        policy_line = ";".join(f"{k}:{digests[k]}" for k in sorted(digests))
        md: Dict[str, str] = {
            "packet_id": str(binding["packet_id"]),
            "packet_evidence_digest": str(binding["packet_evidence_digest"]),
            "material_digest": str(binding["material_digest"]),
            "recommendation": str(binding["recommendation"]),
            "policy_digests": policy_line,
            "replay_run_id": str(binding["replay_run_id"]),
            "replay_run_digest": str(binding["replay_run_digest"]),
            "group_state_digest": str(binding["group_state_digest"]),
            "stability_class": str(binding["stability_class"]),
            "formal_review_schema_version": str(binding["packet_schema_version"]),
            "corpus_eligible_at_packet": str(binding["corpus_eligible_at_packet"]),
            "corpus_eligible_at_write": str(binding["corpus_eligible_at_write"]),
            "head_decision_id_at_packet": str(binding["head_decision_id_at_packet"]),
            "metadata_payload_digest": digest16(binding),
        }
        if acknowledged:
            md["acknowledged_sibling"] = ",".join(acknowledged)
        if disposition:
            md["disposition"] = disposition
        if related_pattern_id:
            md["related_pattern_id"] = related_pattern_id
        if replacement_pattern_id:
            md["replacement_pattern_id"] = replacement_pattern_id
        if reason_category:
            md["reason_category"] = reason_category
        if len(md) > MAX_METADATA_KEYS or any(len(v) > MAX_METADATA_VALUE_CHARS for v in md.values()):
            raise MetadataInvalid("decision metadata exceeds Phase 3.9.1 constraints")
        return md


def evidence_diff(reviewed: Mapping[str, Any], current: Mapping[str, Any]) -> List[str]:
    """evidence view の top-level block ごとの差分（診断用・path や原文は含まない）。"""
    a, b = evidence_view(reviewed), evidence_view(current)
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
