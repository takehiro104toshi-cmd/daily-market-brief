"""P6-B5C — 受理された relation 候補 → `RelationAssertionPlan`（純関数。計画境界のみ）。

`plan_relation_assertion_from_accepted_proposal(proposal, decisions, *, endpoint_lookup, recorded_at,
existing_relations=())`

- plan は **authority ではない**。B5B の `ThemeRelationAssertion` を append できるのは将来の実行 gate だけで、
  本 module は relation store の追記 API を import も呼び出しもしない。
- 最終的な主張 authority は受理決定が明示した class（HUMAN_ASSERTED / SOURCE_ASSERTED）。
  SOURCE_ASSERTED は、受理決定が持つ人間の `SourceClaimVerification` が提案の出典 / citation / 端点 / 関係型と
  厳密に一致する場合にのみ許す（P6-B5C-R1）。citation が在るだけでは許さない。提案者が RULE / LLM であることも
  出典の権威の代わりにならない（authority laundering の禁止）。
- 提案の出自（誰が提案したか）と、受理された主張 authority（誰が主張するか）は別物として両方保持する。
- 端点 Theme root は呼び出し側が渡す read-only lookup だけが答える。Foundation store を読まない。
- 退役 / 後継の端点でも書き換えない。既存 authority と同内容なら fail closed で、黙って成功しない。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Sequence, Tuple

from ..core.time import to_utc_iso
from ..themes.model import ProvenanceClass, canonical_json
from .relation_model import (AssertionClass, RELATION_VOCAB_VERSION, RelationEvidenceRef, RelationType,
                             SourceAttribution, edge_key_of)
from .relation_proposal_model import (SOURCE_CLAIM_VERIFICATION_MEANING, SOURCE_CLAIM_VERIFICATION_NON_MEANING,
                                      RelationChangeKind, RelationDecisionKind, RelationProposal,
                                      RelationProposalDecision, RelationProposalError, RelationProposerClass,
                                      SourceClaimVerification, source_asserted_refusal)
from .relation_proposal_resolution import (RelationProposalStatus, derive_relation_proposal_status,
                                           resolve_active_relation_decision)
from .relation_resolution import ENDPOINT_PRESENT_STATES, EdgeState, EndpointLookup, EndpointState, ResolvedRelation

RELATION_PLAN_VERSION = "theme_relation_assertion_plan:0.1.0"
#: CAUSES は B5B と同じく evidence を必須にする（B5B の制約を弱めない）
EVIDENCE_REQUIRED_TYPES: Tuple[RelationType, ...] = (RelationType.CAUSES,)


class RelationBridgeError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise RelationBridgeError(code, detail)


def _aware(value: object, name: str) -> datetime:
    _require(isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
             "INVALID_RECORDED_AT", f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _plain(value) -> object:
    return json.loads(canonical_json(value))


# ---------------------------------------------------------------- provenance snapshot


@dataclass(frozen=True, kw_only=True)
class RelationProposalOrigin:
    """提案の出自。受理された主張 authority とは別物として保持する。"""

    proposal_id: str
    proposal_created_at: datetime
    proposer_class: RelationProposerClass
    proposer_ref: str
    rule_version: str = ""
    proposer_note: str = ""
    change_kind: RelationChangeKind
    proposal_rationale: str
    proposal_source_attribution: Optional[str] = None

    def to_plain(self) -> Dict[str, object]:
        return {"proposal_id": self.proposal_id, "proposal_created_at": to_utc_iso(self.proposal_created_at),
                "proposer_class": self.proposer_class.value, "proposer_ref": self.proposer_ref,
                "rule_version": self.rule_version, "proposer_note": self.proposer_note,
                "change_kind": self.change_kind.value, "proposal_rationale": self.proposal_rationale,
                "proposal_source_attribution": self.proposal_source_attribution}


@dataclass(frozen=True, kw_only=True)
class RelationDecisionOrigin:
    decision_id: str
    decision: RelationDecisionKind
    accepted_assertion_class: AssertionClass
    actor_class: ProvenanceClass
    actor_ref: str
    reason: str
    recorded_at: datetime
    supersedes_decision_id: str = ""

    def to_plain(self) -> Dict[str, object]:
        return {"decision_id": self.decision_id, "decision": self.decision.value,
                "accepted_assertion_class": self.accepted_assertion_class.value, "actor_class": self.actor_class.value,
                "actor_ref": self.actor_ref, "reason": self.reason, "recorded_at": to_utc_iso(self.recorded_at),
                "supersedes_decision_id": self.supersedes_decision_id}


@dataclass(frozen=True, kw_only=True)
class RelationVerificationOrigin:
    """P6-B5C-R1 — 受理を authorize した人間の出典主張確認。監査のためにそのまま plan に残す。

    `meaning` / `non_meaning` は凍結文言であり、「人間がこの関係を客観的真実として検証した」とは読ませない。
    """

    verified_by: str
    verifier_class: ProvenanceClass
    attributed_to: str
    evidence_kind: str
    evidence_ref_id: str
    assertion_locus: str
    claim_summary: str
    source_theme_root_id: str
    target_theme_root_id: str
    relation_type: RelationType
    verified_at: datetime
    meaning: str = SOURCE_CLAIM_VERIFICATION_MEANING
    non_meaning: str = SOURCE_CLAIM_VERIFICATION_NON_MEANING

    @classmethod
    def of(cls, verification: SourceClaimVerification) -> "RelationVerificationOrigin":
        return cls(verified_by=verification.verified_by, verifier_class=verification.verifier_class,
                   attributed_to=verification.attributed_to, evidence_kind=verification.evidence_kind.value,
                   evidence_ref_id=verification.evidence_ref_id, assertion_locus=verification.assertion_locus,
                   claim_summary=verification.claim_summary,
                   source_theme_root_id=verification.source_theme_root_id,
                   target_theme_root_id=verification.target_theme_root_id,
                   relation_type=verification.relation_type, verified_at=verification.verified_at)

    def to_plain(self) -> Dict[str, object]:
        return {"verified_by": self.verified_by, "verifier_class": self.verifier_class.value,
                "attributed_to": self.attributed_to, "evidence_kind": self.evidence_kind,
                "evidence_ref_id": self.evidence_ref_id, "assertion_locus": self.assertion_locus,
                "claim_summary": self.claim_summary, "source_theme_root_id": self.source_theme_root_id,
                "target_theme_root_id": self.target_theme_root_id, "relation_type": self.relation_type.value,
                "verified_at": to_utc_iso(self.verified_at), "meaning": self.meaning,
                "non_meaning": self.non_meaning}


# ---------------------------------------------------------------- plan


@dataclass(frozen=True, kw_only=True)
class RelationAssertionPlan:
    """B5B の assertion を後で組み立てるための確定材料。journal identity を持たず、永続化しない。"""

    plan_version: str = RELATION_PLAN_VERSION
    relation_vocab_version: str = RELATION_VOCAB_VERSION
    source_theme_root_id: str
    target_theme_root_id: str
    relation_type: RelationType
    assertion_class: AssertionClass
    source_attribution: Optional[SourceAttribution] = None
    rationale: str
    evidence_refs: Tuple[RelationEvidenceRef, ...] = ()
    previous_assertion_id: str = ""
    change_kind: RelationChangeKind
    edge_key: str
    recorded_at: datetime
    source_endpoint: EndpointState
    target_endpoint: EndpointState
    diagnostics: Tuple[str, ...] = ()
    proposal_origin: RelationProposalOrigin
    decision_origin: RelationDecisionOrigin
    verification_origin: Optional[RelationVerificationOrigin] = None

    def to_plain(self) -> Dict[str, object]:
        return {
            "plan_version": self.plan_version, "relation_vocab_version": self.relation_vocab_version,
            "source_theme_root_id": self.source_theme_root_id, "target_theme_root_id": self.target_theme_root_id,
            "relation_type": self.relation_type.value, "assertion_class": self.assertion_class.value,
            "source_attribution": _plain(self.source_attribution) if self.source_attribution is not None else None,
            "rationale": self.rationale, "evidence_refs": [_plain(e) for e in self.evidence_refs],
            "previous_assertion_id": self.previous_assertion_id, "change_kind": self.change_kind.value,
            "edge_key": self.edge_key, "recorded_at": to_utc_iso(self.recorded_at),
            "source_endpoint": self.source_endpoint.value, "target_endpoint": self.target_endpoint.value,
            "diagnostics": list(self.diagnostics), "proposal_origin": self.proposal_origin.to_plain(),
            "decision_origin": self.decision_origin.to_plain(),
            "verification_origin": (self.verification_origin.to_plain()
                                    if self.verification_origin is not None else None),
        }

    def canonical_line(self) -> str:
        return canonical_json(self.to_plain())


# ---------------------------------------------------------------- 既存 authority との照合


def _content_key(relation_type: RelationType, assertion_class: AssertionClass,
                 attribution: Optional[SourceAttribution], rationale: str,
                 evidence_refs: Sequence[RelationEvidenceRef]) -> str:
    return canonical_json({"relation_type": relation_type.value, "assertion_class": assertion_class.value,
                           "source_attribution": _plain(attribution) if attribution is not None else None,
                           "rationale": rationale,
                           "evidence_refs": sorted(canonical_json(e) for e in evidence_refs)})


def _existing_content_key(edge: ResolvedRelation) -> str:
    record = edge.assertion
    return _content_key(record.relation_type, record.assertion_class, record.source_attribution, record.rationale,
                        record.evidence_refs)


def _check_existing_authority(proposal: RelationProposal, edge_key: str, content_key: str,
                              existing_relations: Sequence[ResolvedRelation]) -> None:
    if proposal.change_kind is RelationChangeKind.CORRECTION:
        owner = next((e for e in existing_relations if proposal.previous_assertion_id in e.assertion_chain), None)
        _require(owner is not None, "PREDECESSOR_NOT_FOUND",
                 "the corrected assertion is not present in the supplied authority view")
        _require(owner.edge_key == edge_key, "PREDECESSOR_WRONG_EDGE",
                 "the corrected assertion belongs to another relation history")
        _require(owner.edge_state is not EdgeState.RETRACTED, "RELATION_RETRACTED_REQUIRES_GOVERNANCE",
                 "a retracted relation is restored through governance, not through a new assertion")
        _require(owner.assertion.relation_assertion_id == proposal.previous_assertion_id, "PREDECESSOR_NOT_TERMINAL",
                 "a correction continues from the terminal assertion of its history")
        _require(_existing_content_key(owner) != content_key, "RELATION_ALREADY_AUTHORITATIVE",
                 "the authoritative assertion already carries these semantics")
        return
    same = next((e for e in existing_relations if e.edge_key == edge_key), None)
    if same is None:
        return
    _require(same.edge_state is not EdgeState.RETRACTED, "RELATION_RETRACTED_REQUIRES_GOVERNANCE",
             "a retracted relation is restored through governance, not through a new assertion")
    _require(_existing_content_key(same) != content_key, "RELATION_ALREADY_AUTHORITATIVE",
             "the authoritative assertion already carries these semantics")
    _require(False, "EDGE_ALREADY_STARTED", "this relation history exists; record a correction instead")


# ---------------------------------------------------------------- entry point


def plan_relation_assertion_from_accepted_proposal(proposal: object, decisions: Sequence[RelationProposalDecision], *,
                                                   endpoint_lookup: EndpointLookup, recorded_at: object,
                                                   existing_relations: Sequence[ResolvedRelation] = ()
                                                   ) -> RelationAssertionPlan:
    """受理済みの関係候補から、B5B の assertion を後で組み立てるための不変 plan を導く（永続化しない）。"""
    _require(isinstance(proposal, RelationProposal), "INVALID_PROPOSAL_TYPE",
             "only a relation candidate proposal can be bridged")
    _require(isinstance(decisions, (tuple, list)) and all(isinstance(d, RelationProposalDecision) for d in decisions),
             "INVALID_TYPE", "decisions must be a sequence of relation proposal decisions")
    _require(callable(endpoint_lookup), "INVALID_TYPE", "endpoint_lookup must be callable")
    _require(isinstance(existing_relations, (tuple, list))
             and all(isinstance(e, ResolvedRelation) for e in existing_relations), "INVALID_TYPE",
             "existing_relations must be resolved relations")

    decisions = tuple(decisions)
    status = derive_relation_proposal_status(proposal, decisions)
    _require(status is RelationProposalStatus.ACCEPTED, "PROPOSAL_NOT_ACCEPTED", status.value)
    decision = resolve_active_relation_decision(proposal.proposal_id, decisions).active_decision
    _require(decision is not None and decision.decision is RelationDecisionKind.ACCEPT, "PROPOSAL_NOT_ACCEPTED",
             "the resolved decision is not an acceptance")
    assertion_class = decision.accepted_assertion_class
    _require(assertion_class is not None, "MISSING_ACCEPTED_AUTHORITY", "an acceptance names the final authority")

    if assertion_class is AssertionClass.SOURCE_ASSERTED:
        refusal = source_asserted_refusal(proposal, decision)             # P6-B5C-R1
        _require(refusal == "", refusal or "FORBIDDEN_SOURCE_AUTHORITY",
                 "a source asserted relation needs the human verification of the cited claim")
        attribution = proposal.source_attribution
    else:
        attribution = None
    if proposal.relation_type in EVIDENCE_REQUIRED_TYPES:
        _require(len(proposal.evidence_refs) >= 1, "MISSING_CAUSAL_EVIDENCE",
                 f"{proposal.relation_type.value} requires at least one evidence reference")

    moment = _aware(recorded_at, "recorded_at")
    _require(moment >= proposal.created_at, "PLAN_BEFORE_PROPOSAL", "the plan time precedes the proposal")
    _require(moment >= decision.recorded_at, "PLAN_BEFORE_DECISION", "the plan time precedes the acceptance")
    for item in proposal.evidence_refs:
        if item.evidence_time is not None:
            _require(moment >= item.evidence_time, "PLAN_BEFORE_EVIDENCE_TIME", "the plan time precedes its evidence")

    source_state = endpoint_lookup(proposal.source_theme_root_id, moment)
    target_state = endpoint_lookup(proposal.target_theme_root_id, moment)
    for name, state in (("SOURCE", source_state), ("TARGET", target_state)):
        _require(state in ENDPOINT_PRESENT_STATES, "ENDPOINT_NOT_AVAILABLE", f"{name}:{state.value}")
    annotations = [f"ENDPOINT_{state.value}:{name}" for name, state in (("SOURCE", source_state), ("TARGET", target_state))
                   if state in (EndpointState.SUPERSEDED, EndpointState.RETIRED)]

    attribution_key = attribution.attribution_key if attribution is not None else ""
    edge_key = edge_key_of(proposal.source_theme_root_id, proposal.target_theme_root_id, proposal.relation_type,
                           assertion_class, attribution_key)
    content_key = _content_key(proposal.relation_type, assertion_class, attribution, proposal.rationale,
                               proposal.evidence_refs)
    _check_existing_authority(proposal, edge_key, content_key, tuple(existing_relations))

    origin = RelationProposalOrigin(
        proposal_id=proposal.proposal_id, proposal_created_at=proposal.created_at,
        proposer_class=proposal.provenance.proposer_class, proposer_ref=proposal.provenance.proposer_ref,
        rule_version=proposal.provenance.rule_version, proposer_note=proposal.provenance.note,
        change_kind=proposal.change_kind, proposal_rationale=proposal.rationale,
        proposal_source_attribution=(proposal.source_attribution.attributed_to
                                     if proposal.source_attribution is not None else None))
    accepted = RelationDecisionOrigin(
        decision_id=decision.decision_id, decision=decision.decision, accepted_assertion_class=assertion_class,
        actor_class=decision.actor_class, actor_ref=decision.actor_ref, reason=decision.reason,
        recorded_at=decision.recorded_at, supersedes_decision_id=decision.supersedes_decision_id)
    return RelationAssertionPlan(
        source_theme_root_id=proposal.source_theme_root_id, target_theme_root_id=proposal.target_theme_root_id,
        relation_type=proposal.relation_type, assertion_class=assertion_class, source_attribution=attribution,
        rationale=proposal.rationale, evidence_refs=proposal.evidence_refs,
        previous_assertion_id=proposal.previous_assertion_id, change_kind=proposal.change_kind, edge_key=edge_key,
        recorded_at=moment, source_endpoint=source_state, target_endpoint=target_state,
        diagnostics=tuple(sorted(annotations)), proposal_origin=origin, decision_origin=accepted,
        verification_origin=(RelationVerificationOrigin.of(decision.source_claim_verification)
                             if decision.source_claim_verification is not None else None))


__all__ = ["EVIDENCE_REQUIRED_TYPES", "RELATION_PLAN_VERSION", "RelationAssertionPlan", "RelationBridgeError",
           "RelationDecisionOrigin", "RelationProposalOrigin", "RelationVerificationOrigin",
           "plan_relation_assertion_from_accepted_proposal"]
