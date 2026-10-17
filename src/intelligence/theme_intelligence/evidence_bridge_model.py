"""P6-B4E — ACCEPTED EvidenceCandidateProposal から導かれる `EvidenceAttachmentPlan` の不変 model（純）。

- plan は **計画**であって Foundation の evidence authority ではない。ThemeObservation でも revision でも governance record でも
  資格判定でもない。Foundation への実行は後続の別 gate に属する。
- plan は journal identity を持たない（content id を計算しない）。派生した ephemeral な値であり、永続化しない。
- 役割 authority は HUMAN（人間の ACCEPT 決定）。提案の出自（RULE / rule_version / 提案理由）は `ProposalOrigin` に
  分けて保持する。提案の出自と、受け入れられた役割の authority は別物である。
- B4E は SUPPORTS / CONTEXT のみを橋渡しする。CONTRADICTS / INVALIDATES は作らない。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

from ..core.time import to_utc_iso
from ..themes.model import (EvidenceAuthorityClass, EvidenceKind, EvidenceRole, EvidenceTimeBasis, EvidenceTimeQuality,
                            ProvenanceClass, SourceOrigin, canonical_json)
from .proposal_model import DecisionKind, ProposerClass

BRIDGE_MODEL_VERSION = "theme_evidence_bridge:0.1.0"
#: B4E が橋渡ししてよい役割（B3 model はより広いが、bridge 方針としてはこの 2 つだけ）
BRIDGEABLE_ROLES: Tuple[EvidenceRole, ...] = (EvidenceRole.SUPPORTS, EvidenceRole.CONTEXT)
#: 受け入れ後の役割 authority は常に人間
PLAN_ROLE_PROVENANCE = ProvenanceClass.HUMAN
#: Foundation が attachment に許す唯一の authority class
PLAN_AUTHORITY_CLASS = EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL


class EvidenceBridgeError(ValueError):
    """fail closed。code は安定した語彙、detail は短い説明（秘密値・本文を含めない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise EvidenceBridgeError(code, detail)


# ---------------------------------------------------------------- provenance snapshot（audit 専用）


@dataclass(frozen=True, kw_only=True)
class ProposalOrigin:
    """提案の出自の snapshot。役割 authority ではない（§7: origin of suggestion != authority of accepted role）。"""

    proposal_id: str
    proposal_created_at: datetime
    proposer_class: ProposerClass
    proposer_ref: str
    rule_version: str = ""
    provenance_reason: str = ""
    candidate_reason: str
    proposal_locator: str = ""
    proposal_note: str = ""

    def to_plain(self) -> Dict[str, object]:
        return {"proposal_id": self.proposal_id, "proposal_created_at": to_utc_iso(self.proposal_created_at),
                "proposer_class": self.proposer_class.value, "proposer_ref": self.proposer_ref,
                "rule_version": self.rule_version, "provenance_reason": self.provenance_reason,
                "candidate_reason": self.candidate_reason, "proposal_locator": self.proposal_locator,
                "proposal_note": self.proposal_note}


@dataclass(frozen=True, kw_only=True)
class DecisionOrigin:
    """受け入れ決定の snapshot。plan の役割 authority の根拠になる不変の governance fact。"""

    decision_id: str
    decision: DecisionKind
    actor_class: ProposerClass
    actor_ref: str
    reason: str
    recorded_at: datetime
    supersedes_decision_id: str = ""

    def to_plain(self) -> Dict[str, object]:
        return {"decision_id": self.decision_id, "decision": self.decision.value, "actor_class": self.actor_class.value,
                "actor_ref": self.actor_ref, "reason": self.reason, "recorded_at": to_utc_iso(self.recorded_at),
                "supersedes_decision_id": self.supersedes_decision_id}


# ---------------------------------------------------------------- plan


@dataclass(frozen=True, kw_only=True)
class EvidenceAttachmentPlan:
    """後続 gate が Foundation `EvidenceAttachment` を組み立てるのに必要な、確定済みの材料。

    evidence 本体（記事本文 / 市場値 / 抜粋）は複製しない。参照 identity（kind / ref_id / origin / 時刻）は提案のまま。
    """

    bridge_model_version: str = BRIDGE_MODEL_VERSION
    target_root_id: str
    target_resolver_version: str
    target_cutoff: datetime
    target_observation_id: str
    evidence_kind: EvidenceKind
    authority_class: EvidenceAuthorityClass = PLAN_AUTHORITY_CLASS
    ref_id: str
    source_origin: SourceOrigin
    evidence_time: Optional[datetime]
    evidence_time_basis: EvidenceTimeBasis
    evidence_time_quality: EvidenceTimeQuality
    evidence_date: str = ""
    role: EvidenceRole
    role_provenance: ProvenanceClass = PLAN_ROLE_PROVENANCE
    role_asserted_by: str
    attached_at: datetime
    consequence_ref: str = ""
    invalidation_condition_ref: str = ""
    limited_use: bool = False
    locator: str = ""
    note: str
    proposal: ProposalOrigin
    decision: DecisionOrigin

    def __post_init__(self) -> None:
        _require(self.bridge_model_version == BRIDGE_MODEL_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.bridge_model_version)
        _require(self.authority_class is PLAN_AUTHORITY_CLASS, "INVALID_AUTHORITY_CLASS", "attachment plans are primary observational")
        _require(self.role in BRIDGEABLE_ROLES, "FORBIDDEN_BRIDGE_ROLE", str(self.role))
        _require(self.role_provenance is PLAN_ROLE_PROVENANCE, "INVALID_ROLE_PROVENANCE", "accepted role authority is human")
        _require(self.role_asserted_by != "", "MISSING_ROLE_ASSERTER", "role_asserted_by is required")
        _require(self.note != "", "MISSING_ROLE_NOTE", "human role authority requires a stated reason")
        _require(self.invalidation_condition_ref == "", "INVALIDATION_REF_FORBIDDEN", "B4E does not bridge invalidation")
        if self.role is EvidenceRole.SUPPORTS:
            _require(self.consequence_ref != "", "CONSEQUENCE_REF_REQUIRED", "supports must name an expected consequence")
        else:
            _require(self.consequence_ref == "", "CONSEQUENCE_REF_FORBIDDEN", "context evidence has no consequence ref")
        missing = self.evidence_time_quality is EvidenceTimeQuality.MISSING
        _require(missing == (self.evidence_time is None), "INVALID_EVIDENCE_TIME", "evidence_time must match the declared quality")
        if missing:
            _require(self.role is EvidenceRole.CONTEXT, "ROLE_REQUIRES_EVIDENCE_TIME", "evidence without a time may only be context")
            _require(self.evidence_time_basis is EvidenceTimeBasis.NONE and self.evidence_date == "", "INVALID_EVIDENCE_TIME",
                     "missing quality carries no basis or date")
        else:
            _require(self.evidence_time <= self.attached_at, "EVIDENCE_AFTER_ATTACHMENT",
                     "evidence_time must not be later than attached_at")
        _require(self.limited_use == (self.evidence_time_quality is EvidenceTimeQuality.INFERRED), "INVALID_EVIDENCE_TIME",
                 "limited_use is derived from an inferred evidence time")

    @property
    def attachment_key(self) -> str:
        """Foundation の attachment key（observation 内で一意。`(ref_id, consequence_ref)`）。"""
        return f"{self.ref_id}#{self.consequence_ref}"

    def to_plain(self) -> Dict[str, object]:
        return {
            "bridge_model_version": self.bridge_model_version, "target_root_id": self.target_root_id,
            "target_resolver_version": self.target_resolver_version, "target_cutoff": to_utc_iso(self.target_cutoff),
            "target_observation_id": self.target_observation_id, "evidence_kind": self.evidence_kind.value,
            "authority_class": self.authority_class.value, "ref_id": self.ref_id,
            "source_origin": json.loads(canonical_json(self.source_origin)),
            "evidence_time": to_utc_iso(self.evidence_time) if self.evidence_time is not None else "",
            "evidence_time_basis": self.evidence_time_basis.value, "evidence_time_quality": self.evidence_time_quality.value,
            "evidence_date": self.evidence_date, "role": self.role.value, "role_provenance": self.role_provenance.value,
            "role_asserted_by": self.role_asserted_by, "attached_at": to_utc_iso(self.attached_at),
            "consequence_ref": self.consequence_ref, "invalidation_condition_ref": self.invalidation_condition_ref,
            "limited_use": self.limited_use, "locator": self.locator, "note": self.note,
            "attachment_key": self.attachment_key, "proposal": self.proposal.to_plain(), "decision": self.decision.to_plain(),
        }

    def canonical_line(self) -> str:
        """決定論的な 1 行表現（test / 監査の比較用。永続化しない）。"""
        return canonical_json(self.to_plain())


__all__ = ["BRIDGEABLE_ROLES", "BRIDGE_MODEL_VERSION", "DecisionOrigin", "EvidenceAttachmentPlan", "EvidenceBridgeError",
           "PLAN_AUTHORITY_CLASS", "PLAN_ROLE_PROVENANCE", "ProposalOrigin"]
