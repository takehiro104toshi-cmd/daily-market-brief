"""Accept bridge（P6-B3）— ACCEPT 済み THEME_CANDIDATE から Foundation candidate 作成に必要な **不変 plan** を作る純 helper。

- ACCEPT decision ≠ Theme 作成。本 module は Foundation に書かず、`execute_candidate` / `ThemeStore.append_*` /
  `operations.execute_*` を呼ばない。caller が別 gate で root_id を生成し Foundation operation を明示実行する。
- root_id は Foundation operation 側の責務。plan は root_id を持たない。
- plan には accepted proposal id と decision id の provenance を含める。creator class は HUMAN。
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from typing import Sequence, Tuple

from ..core.time import ensure_aware
from ..themes.fingerprint import identity_core_fingerprint, semantic_fingerprint
from ..themes.model import (EvidenceAttachment, InferredExposureLink, InvalidationCondition, Limitation, Mechanism,
                            MechanismCertainty, ObservationProvenance, ProvenanceClass, ScopeToken, ThemeSubject)
from .proposal_model import DecisionKind, ProposalDecision, ProposalType, ThemeCandidateProposal
from .proposal_resolution import DecisionResolutionStatus, resolve_active_decision

BRIDGE_PLAN_VERSION = "theme_creation_plan:0.1.0"


class BridgeError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


@dataclass(frozen=True, kw_only=True)
class ThemeCreationPlan:
    """Foundation `plan_candidate(root_id=<caller>, created_at, creator_class, creation_provenance, genesis, attachments)`
    に渡す材料。root_id を持たない（Foundation 側で生成）。"""

    plan_version: str = BRIDGE_PLAN_VERSION
    proposal_id: str
    decision_id: str
    creator_class: ProvenanceClass = ProvenanceClass.HUMAN
    creation_provenance: str
    created_at: datetime
    subject: ThemeSubject
    mechanism: Mechanism
    certainty_class: MechanismCertainty
    scope: Tuple[ScopeToken, ...]
    limitations: Tuple[Limitation, ...]
    invalidation_conditions: Tuple[InvalidationCondition, ...]
    inferred_links: Tuple[InferredExposureLink, ...]
    attachments: Tuple[EvidenceAttachment, ...]        # attached_at ＝ created_at（Theme 作成時の付与）
    provenance: ObservationProvenance                   # genesis observation の provenance（HUMAN、decision を参照）
    semantic_fingerprint: str
    identity_core_fingerprint: str


def plan_theme_creation_from_accepted_proposal(proposal: ThemeCandidateProposal, decisions: Sequence[ProposalDecision], *,
                                              created_at: datetime) -> ThemeCreationPlan:
    """active decision が ACCEPT の THEME_CANDIDATE だけを Foundation candidate plan の材料に変換する（書かない）。"""
    if not isinstance(proposal, ThemeCandidateProposal) or proposal.proposal_type is not ProposalType.THEME_CANDIDATE:
        raise BridgeError("PROPOSAL_TYPE_NOT_BRIDGEABLE", "only THEME_CANDIDATE proposals can be bridged")
    resolution = resolve_active_decision(proposal.proposal_id, decisions)
    if resolution.status is not DecisionResolutionStatus.RESOLVED:
        raise BridgeError("NOT_ACCEPTED", f"decision history is {resolution.status.value}: {resolution.diagnostics}")
    decision = resolution.active_decision
    if decision.decision is not DecisionKind.ACCEPT:
        raise BridgeError("NOT_ACCEPTED", f"active decision is {decision.decision.value}")
    created_at = ensure_aware(created_at, "created_at")
    if created_at < decision.recorded_at:
        raise BridgeError("CREATED_BEFORE_DECISION", "theme creation cannot precede the accepting decision")
    if (semantic_fingerprint(proposal) != proposal.semantic_fingerprint
            or identity_core_fingerprint(proposal) != proposal.identity_core_fingerprint):
        raise BridgeError("FINGERPRINT_MISMATCH", "proposal fingerprints do not match its content")
    if not proposal.invalidation_conditions or not proposal.scope:
        raise BridgeError("INCOMPLETE_CANDIDATE", "scope and invalidation conditions are required")
    attachments = tuple(replace(a, attached_at=created_at) for a in proposal.evidence_refs)
    provenance = ObservationProvenance(
        writer_class=ProvenanceClass.HUMAN, writer_ref=decision.actor_ref,
        reason=f"accepted proposal {proposal.proposal_id} by decision {decision.decision_id}")
    return ThemeCreationPlan(
        proposal_id=proposal.proposal_id, decision_id=decision.decision_id,
        creation_provenance=f"proposal:{proposal.proposal_id};decision:{decision.decision_id};actor:{decision.actor_ref}",
        created_at=created_at, subject=proposal.subject, mechanism=proposal.mechanism, certainty_class=proposal.certainty_class,
        scope=proposal.scope, limitations=proposal.limitations, invalidation_conditions=proposal.invalidation_conditions,
        inferred_links=proposal.inferred_links, attachments=attachments, provenance=provenance,
        semantic_fingerprint=proposal.semantic_fingerprint, identity_core_fingerprint=proposal.identity_core_fingerprint)


PLAN_FIELDS: Tuple[str, ...] = tuple(f.name for f in fields(ThemeCreationPlan))

__all__ = ["BRIDGE_PLAN_VERSION", "BridgeError", "ThemeCreationPlan", "plan_theme_creation_from_accepted_proposal", "PLAN_FIELDS"]
