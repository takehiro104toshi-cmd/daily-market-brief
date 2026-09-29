"""P6-B4E — ACCEPTED EvidenceCandidateProposal → `EvidenceAttachmentPlan`（純関数。計画境界のみ）。

`plan_evidence_attachment_from_accepted_proposal(proposal, decisions, *, target_resolution, created_at,
consequence_ref=None, invalidation_ref=None) -> EvidenceAttachmentPlan`

- proposal の受け入れは **計画の作成** を authorize するだけで、Foundation authority を変えない。Foundation への追記・
  observation の改訂・root 生成・governance event・proposal / decision 履歴の変更は一切行わない。
- 対象は **明示された Foundation root** だけ。THEME_CANDIDATE proposal を root に解決しない。taxonomy / entity /
  fingerprint / dedup / 類似度 / 既存 Theme から root を推測しない。
- 受け入れ判定は B3 の decision chain resolver をそのまま使う（latest-wins の再実装をしない）。
- SUPPORTS は明示的で実在する consequence ref を必須にする（先頭の consequence を自動採用しない）。CONTEXT は禁止。
- INVALIDATES / CONTRADICTS は橋渡ししない。invalidation ref は常に禁止。
- 資格判定・独立 source 数・lifecycle・change set は計算しない。store / 時計 / network / LLM / 乱数を使わない。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence, Set

from ..themes.model import EvidenceRole, EvidenceTimeQuality
from ..themes.resolver import ResolutionStatus, ThemeResolution
from .evidence_bridge_model import (BRIDGEABLE_ROLES, DecisionOrigin, EvidenceAttachmentPlan, EvidenceBridgeError,
                                    ProposalOrigin)
from .proposal_model import DecisionKind, EvidenceCandidateProposal, ProposalDecision
from .proposal_resolution import ProposalStatus, derive_proposal_status, resolve_active_decision


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise EvidenceBridgeError(code, detail)


def _aware(value: object, name: str) -> datetime:
    _require(isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
             "INVALID_CREATED_AT", f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _existing_attachment_keys(resolution: ThemeResolution) -> Set[str]:
    """対象 root の現在の観測が既に持つ attachment key（可視・時刻欠落 context を含む保守的な集合）。"""
    keys = {a.attachment_key for a in resolution.observation.attachments}
    view = resolution.evidence
    if view is not None:
        keys.update(a.attachment_key for a in view.visible)
        keys.update(a.attachment_key for a in view.context_without_time)
    return keys


def _accepted_decision(proposal: EvidenceCandidateProposal, decisions: Sequence[ProposalDecision]) -> ProposalDecision:
    status = derive_proposal_status(proposal, decisions)
    _require(status is ProposalStatus.ACCEPTED, "PROPOSAL_NOT_ACCEPTED", status.value)
    decision = resolve_active_decision(proposal.proposal_id, decisions).active_decision
    _require(decision is not None and decision.decision is DecisionKind.ACCEPT, "PROPOSAL_NOT_ACCEPTED",
             "the resolved decision is not an acceptance")
    return decision


def _validated_target(proposal: EvidenceCandidateProposal, target_resolution: object) -> ThemeResolution:
    _require(proposal.target_root_id != "", "TARGET_NOT_FOUNDATION_ROOT",
             "only an explicit Foundation root id is bridgeable in this gate")
    _require(isinstance(target_resolution, ThemeResolution), "INVALID_TYPE", "target_resolution must be a Theme resolution")
    _require(target_resolution.root_id == proposal.target_root_id, "TARGET_ROOT_MISMATCH",
             "target_resolution does not describe the proposal target root")
    _require(target_resolution.status is ResolutionStatus.RESOLVED, "TARGET_NOT_RESOLVED", target_resolution.status.value)
    _require(target_resolution.observation is not None, "TARGET_NOT_RESOLVED", "the target root has no observed state")
    return target_resolution


def _validated_consequence(proposal: EvidenceCandidateProposal, target: ThemeResolution,
                           consequence_ref: Optional[str]) -> str:
    if proposal.proposed_role is EvidenceRole.SUPPORTS:
        _require(consequence_ref is not None and consequence_ref != "", "CONSEQUENCE_REF_REQUIRED",
                 "supporting evidence must name an expected consequence of the target theme")
        _require(consequence_ref in set(target.observation.mechanism.consequence_keys), "UNKNOWN_CONSEQUENCE_REF",
                 "the named consequence does not exist in the resolved theme state")
        return consequence_ref
    _require(consequence_ref is None, "CONSEQUENCE_REF_FORBIDDEN", "context evidence is not tied to a consequence")
    return ""


def _validated_time(proposal: EvidenceCandidateProposal, decision: ProposalDecision, created_at: object) -> datetime:
    attached_at = _aware(created_at, "created_at")
    _require(attached_at >= proposal.created_at, "CREATED_BEFORE_PROPOSAL", "attachment time precedes the proposal")
    _require(attached_at >= decision.recorded_at, "CREATED_BEFORE_DECISION", "attachment time precedes the acceptance")
    if proposal.evidence_time is not None:
        _require(attached_at >= proposal.evidence_time, "CREATED_BEFORE_EVIDENCE_TIME",
                 "attachment time precedes the evidence time")
    return attached_at


def plan_evidence_attachment_from_accepted_proposal(proposal: object, decisions: Sequence[ProposalDecision], *,
                                                    target_resolution: object, created_at: object,
                                                    consequence_ref: Optional[str] = None,
                                                    invalidation_ref: Optional[str] = None) -> EvidenceAttachmentPlan:
    """受理済み evidence 候補から、Foundation attachment を後で組み立てるための不変 plan を導く（永続化しない）。"""
    _require(invalidation_ref is None, "INVALIDATION_REF_FORBIDDEN", "B4E does not bridge invalidation evidence")
    _require(isinstance(proposal, EvidenceCandidateProposal), "INVALID_PROPOSAL_TYPE",
             "only an evidence candidate proposal can be bridged")
    _require(isinstance(decisions, (tuple, list)) and all(isinstance(d, ProposalDecision) for d in decisions),
             "INVALID_TYPE", "decisions must be a sequence of proposal decisions")
    _require(consequence_ref is None or isinstance(consequence_ref, str), "INVALID_TYPE", "consequence_ref must be str or None")

    decision = _accepted_decision(proposal, tuple(decisions))
    target = _validated_target(proposal, target_resolution)
    _require(proposal.proposed_role in BRIDGEABLE_ROLES, "FORBIDDEN_BRIDGE_ROLE", proposal.proposed_role.value)
    quality = proposal.evidence_time_quality
    if quality is EvidenceTimeQuality.MISSING:
        _require(proposal.proposed_role is EvidenceRole.CONTEXT, "ROLE_REQUIRES_EVIDENCE_TIME",
                 "evidence without a reliable time may only be attached as context")
    resolved_consequence = _validated_consequence(proposal, target, consequence_ref)
    attached_at = _validated_time(proposal, decision, created_at)

    key = f"{proposal.ref_id}#{resolved_consequence}"
    _require(key not in _existing_attachment_keys(target), "ATTACHMENT_ALREADY_PRESENT", key)

    origin = ProposalOrigin(
        proposal_id=proposal.proposal_id, proposal_created_at=proposal.created_at,
        proposer_class=proposal.provenance.proposer_class, proposer_ref=proposal.provenance.proposer_ref,
        rule_version=proposal.provenance.rule_version, provenance_reason=proposal.provenance.reason,
        candidate_reason=proposal.reason, proposal_locator=proposal.locator, proposal_note=proposal.note)
    accepted = DecisionOrigin(
        decision_id=decision.decision_id, decision=decision.decision, actor_class=decision.actor_class,
        actor_ref=decision.actor_ref, reason=decision.reason, recorded_at=decision.recorded_at,
        supersedes_decision_id=decision.supersedes_decision_id)
    return EvidenceAttachmentPlan(
        target_root_id=target.root_id, target_resolver_version=target.resolver_version, target_cutoff=target.cutoff,
        target_observation_id=target.observation.observation_id, evidence_kind=proposal.evidence_kind,
        ref_id=proposal.ref_id, source_origin=proposal.source_origin, evidence_time=proposal.evidence_time,
        evidence_time_basis=proposal.evidence_time_basis, evidence_time_quality=quality,
        evidence_date=proposal.evidence_date, role=proposal.proposed_role, role_asserted_by=decision.actor_ref,
        attached_at=attached_at, consequence_ref=resolved_consequence,
        limited_use=quality is EvidenceTimeQuality.INFERRED, locator=proposal.locator,
        note=proposal.note or decision.reason, proposal=origin, decision=accepted)


__all__ = ["plan_evidence_attachment_from_accepted_proposal"]
