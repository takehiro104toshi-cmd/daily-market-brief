"""P6-B7D — 検証済み提案 plan の純 model（DERIVED・非 authority・非永続。I/O なし）。

plan は「後の gate（B7F）が既存の B3 / B5C constructor を**意味の即興なしに**呼べる材料」だけを持つ:

- `ValidatedEvidenceProposalPlan` → B3 `EvidenceCandidateProposal.build`
- `ValidatedThemeProposalPlan` → B3 `ThemeCandidateProposal.build`
- `ValidatedRelationProposalPlan` → B5C `RelationProposal.build`

plan は B3 / B5C の提案でも、decision でも、Theme / evidence / relation の authority でも、人間の確認でもない。

固定（provenance lock。LLM 由来のものは LLM より強い出自を名乗れない）:

- B3 の提案者 class は `LLM_PROPOSAL`、B5C は `LLM`。Foundation の component 主張 provenance と attachment の role
  provenance は `LLM_PROPOSAL`、確度 class は `HYPOTHESIZED_MECHANISM`。これより強い値は `PROVENANCE_ESCALATION`。
- relation の出典帰属は常に「未確認」（`SourceClaimStatus.UNVERIFIED`）。確認済みを表す値は存在しない。

identity:

- `plan_id` は正規化済みの提案材料だけの content id。LLM の説明文・MON 文脈・provider / model・時刻・候補の順序を含まない。
- `upstream_proposal_id` は凍結済みの B3 / B5C constructor がこの材料から計算した id。B3 / B5C の identity は
  provenance と created_at を含まないので、B7F が同じ材料を渡せば同じ id になる。`plan_id` とは別物である。
- identity に入る自由文（B3 の `reason`、B5C の `rationale`）は、検証済みの構造 field だけから作る template。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Mapping, Optional, Tuple, Union

from ..core.ids import content_id
from ..themes.model import (MECHANISM_VOCABULARY_VERSION, SINGLE_PERIOD_FRAMES, AssertionProvenance, EvidenceAttachment,
                            EvidenceAuthorityClass, EvidenceKind, EvidenceRole, EvidenceTimeBasis, EvidenceTimeQuality,
                            InvalidationCondition, Limitation, Mechanism, MechanismCertainty, ProvenanceClass,
                            ScopeDimension, ScopeToken, SourceOrigin, ThemeSubject, canonical_json, is_root_id,
                            normalize_text)
from .llm_proposal_model import AbstentionReason, LlmTask
from .proposal_model import PROPOSAL_ID_PREFIX, ProposerClass, is_content_id
from .relation_model import RELATION_VOCAB_VERSION, RelationEvidenceRef, RelationType, SourceAttribution
from .relation_proposal_model import PROPOSAL_ID_PREFIX as RELATION_PROPOSAL_ID_PREFIX
from .relation_proposal_model import RelationChangeKind, RelationProposerClass

PLAN_SCHEMA_VERSION = "theme_llm_proposal_plan:0.1.0"
RESULT_SCHEMA_VERSION = "theme_llm_validation_result:0.1.0"
VALIDATOR_VERSION = "theme_llm_semantic_validator:0.1.0"
PLAN_ID_PREFIX = "thllmplan"
RESULT_ID_PREFIX = "thllmval"

#: 凍結文言（contract / test で固定する）
PLAN_IS_NOT_AUTHORITY = "a validated plan is derived material for a later proposal, never a proposal, decision or assertion"
SOURCE_CLAIM_IS_UNVERIFIED = "an llm attribution names the cited source; only a person can verify that the source asserted it"
RATIONALE_IS_NOT_IDENTITY = "llm wording is audit metadata; identity text comes from templates over validated fields"

# ---------------------------------------------------------------- provenance lock（contract の固定値）

LLM_PROPOSER_CLASS = ProposerClass.LLM_PROPOSAL
LLM_RELATION_PROPOSER_CLASS = RelationProposerClass.LLM
LLM_ROLE_PROVENANCE = ProvenanceClass.LLM_PROPOSAL
LLM_ASSERTION_PROVENANCE = AssertionProvenance.LLM_PROPOSAL
#: component の provenance_ref と attachment の role_asserted_by。生成ごとに変わる値を置かない（identity を揺らさない）
LLM_ASSERTION_REF = "llm:proposal"
LLM_FIXED_CERTAINTY = MechanismCertainty.HYPOTHESIZED_MECHANISM
#: THEME 候補の evidence は CONTEXT で引く（LLM は consequence ごとの支持を構造で述べないため、SUPPORTS を作らない）
THEME_EVIDENCE_ROLE = EvidenceRole.CONTEXT

# ---------------------------------------------------------------- identity text template

EVIDENCE_REASON_TEMPLATE = "evidence candidate {role} {kind}{component}"
RELATION_RATIONALE_TEMPLATE = "relation candidate {relation_type} {change_kind}"

VALIDATION_ERROR_CODES: Tuple[str, ...] = (
    "INVALID_INPUT", "REQUEST_MANIFEST_MISMATCH", "TASK_MISMATCH", "KNOWLEDGE_PIN_MISMATCH", "UNKNOWN_HANDLE",
    "HANDLE_FAMILY_MISMATCH", "OUT_OF_SCOPE_REFERENCE", "UNSUPPORTED_VOCABULARY", "INVALID_TARGET", "AMBIGUOUS_TARGET",
    "INVALID_EVIDENCE_ROLE", "PROVENANCE_ESCALATION", "INVALID_RELATION_ENDPOINT", "INVALID_ATTRIBUTION",
    "SOURCE_ASSERTED_UNVERIFIED", "DUPLICATE_SEMANTIC_CANDIDATE", "INVALID_ABSTENTION", "NON_CANONICAL_INPUT",
    "UPSTREAM_CONTRACT_VIOLATION")


class LlmValidationError(ValueError):
    """生成全体の拒否（fail closed）。code は `VALIDATION_ERROR_CODES` の語。detail に LLM の文・出典の文・秘密値を入れない。"""

    def __init__(self, code: str, detail: str = "", codes: Tuple[str, ...] = ()) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.codes = tuple(sorted(set(codes) | {code}))


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise LlmValidationError(code, detail)


class PlanKind(str, Enum):
    EVIDENCE = "EVIDENCE"         # → B3 EVIDENCE_CANDIDATE
    THEME = "THEME"               # → B3 THEME_CANDIDATE
    RELATION = "RELATION"         # → B5C RELATION_CANDIDATE


class TargetComponentKind(str, Enum):
    """evidence 候補が指す既存 Theme の部品。役割ごとに 1 つに決まる。"""

    NONE = "NONE"                                     # CONTEXT
    CONSEQUENCE = "CONSEQUENCE"                       # SUPPORTS / CONTRADICTS
    INVALIDATION_CONDITION = "INVALIDATION_CONDITION"  # INVALIDATES


ROLE_TARGET_COMPONENT: Mapping[EvidenceRole, TargetComponentKind] = {
    EvidenceRole.SUPPORTS: TargetComponentKind.CONSEQUENCE,
    EvidenceRole.CONTRADICTS: TargetComponentKind.CONSEQUENCE,
    EvidenceRole.INVALIDATES: TargetComponentKind.INVALIDATION_CONDITION,
    EvidenceRole.CONTEXT: TargetComponentKind.NONE,
}


class SourceClaimStatus(str, Enum):
    """relation plan の出典帰属の状態。**確認済みを表す値は無い**（確認は人間の SourceClaimVerification だけ）。"""

    NOT_CLAIMED = "NOT_CLAIMED"
    UNVERIFIED = "UNVERIFIED"


class ValidationOutcome(str, Enum):
    PLANS = "PLANS"
    ABSTAINED = "ABSTAINED"


def evidence_reason(role: EvidenceRole, kind: EvidenceKind, component: TargetComponentKind, component_key: str) -> str:
    """B3 EVIDENCE_CANDIDATE の `reason`（identity に入る）。LLM の文言を使わない。"""
    suffix = {TargetComponentKind.NONE: "",
              TargetComponentKind.CONSEQUENCE: f" consequence {component_key}",
              TargetComponentKind.INVALIDATION_CONDITION: f" invalidation condition {component_key}"}[component]
    return normalize_text(EVIDENCE_REASON_TEMPLATE.format(role=role.value, kind=kind.value, component=suffix))


def relation_rationale(relation_type: RelationType, change_kind: RelationChangeKind) -> str:
    """B5C RELATION_CANDIDATE の `rationale`（identity に入る）。LLM の文言を使わない。"""
    return normalize_text(RELATION_RATIONALE_TEMPLATE.format(relation_type=relation_type.value,
                                                             change_kind=change_kind.value))


def _plan_id(payload: Mapping[str, object]) -> str:
    return content_id(PLAN_ID_PREFIX, canonical_json(payload))


def _audit_text(value: object) -> str:
    _require(isinstance(value, str), "INVALID_INPUT", "audit text must be a string")
    return str(value)


def _finding_refs(values: object) -> Tuple[str, ...]:
    _require(isinstance(values, tuple) and all(isinstance(v, str) and v for v in values), "INVALID_INPUT",
             "context finding refs are a tuple of ids")
    return tuple(sorted(set(values)))  # type: ignore[arg-type]


def _shell(cls, defaults: Mapping[str, object], values: Mapping[str, object]):
    """identity を計算するための仮 object（__post_init__ を通さない）。"""
    shell = object.__new__(cls)
    for name, value in {**defaults, **values}.items():
        object.__setattr__(shell, name, value)
    return shell


def _check_plan_id(plan) -> None:
    _require(plan.plan_id == _plan_id(plan.identity_payload()), "NON_CANONICAL_INPUT",
             "plan_id does not match the plan material")


# ---------------------------------------------------------------- EVIDENCE


@dataclass(frozen=True, kw_only=True)
class ValidatedEvidenceProposalPlan:
    """B3 EVIDENCE_CANDIDATE の材料。反証（CONTRADICTS）・無効化（INVALIDATES）も提案にとどまる（Foundation を変えない）。"""

    plan_schema_version: str = PLAN_SCHEMA_VERSION
    plan_kind: PlanKind = PlanKind.EVIDENCE
    proposer_class: ProposerClass = LLM_PROPOSER_CLASS
    evidence_kind: EvidenceKind
    ref_id: str
    source_origin: SourceOrigin
    evidence_time: Optional[datetime]
    evidence_time_basis: EvidenceTimeBasis
    evidence_time_quality: EvidenceTimeQuality
    evidence_date: str
    proposed_role: EvidenceRole
    target_root_id: str
    target_component: TargetComponentKind
    target_component_key: str = ""
    reason: str
    upstream_proposal_id: str
    llm_rationale: str = ""                           # 監査用。identity に入らない
    context_finding_refs: Tuple[str, ...] = ()        # 監査用（MON は文脈であって evidence ではない）。identity に入らない
    plan_id: str

    def __post_init__(self) -> None:
        _require(self.plan_schema_version == PLAN_SCHEMA_VERSION and self.plan_kind is PlanKind.EVIDENCE,
                 "NON_CANONICAL_INPUT", "unsupported plan schema")
        _require(self.proposer_class is LLM_PROPOSER_CLASS, "PROVENANCE_ESCALATION",
                 "an llm evidence plan is proposed by LLM_PROPOSAL only")
        _require(isinstance(self.proposed_role, EvidenceRole) and isinstance(self.target_component, TargetComponentKind)
                 and isinstance(self.evidence_kind, EvidenceKind), "INVALID_INPUT", "role, kind and component are enums")
        _require(ROLE_TARGET_COMPONENT[self.proposed_role] is self.target_component, "INVALID_TARGET",
                 "the role and the targeted component disagree")
        _require((self.target_component is TargetComponentKind.NONE) == (self.target_component_key == ""),
                 "INVALID_TARGET", "a targeted component names its key")
        _require(is_root_id(self.target_root_id), "INVALID_TARGET", "the target is a Theme root")
        _require(self.reason == evidence_reason(self.proposed_role, self.evidence_kind, self.target_component,
                                                self.target_component_key),
                 "NON_CANONICAL_INPUT", "the reason is not the template text")
        _require(is_content_id(self.upstream_proposal_id, PROPOSAL_ID_PREFIX), "NON_CANONICAL_INPUT",
                 "upstream_proposal_id is a B3 proposal id")
        object.__setattr__(self, "llm_rationale", _audit_text(self.llm_rationale))
        object.__setattr__(self, "context_finding_refs", _finding_refs(self.context_finding_refs))
        _check_plan_id(self)

    def upstream_arguments(self) -> Dict[str, object]:
        """`EvidenceCandidateProposal.build` の引数（provenance と created_at は B7F が付ける）。"""
        return {"evidence_kind": self.evidence_kind, "ref_id": self.ref_id, "source_origin": self.source_origin,
                "evidence_time": self.evidence_time, "evidence_time_basis": self.evidence_time_basis,
                "evidence_time_quality": self.evidence_time_quality, "evidence_date": self.evidence_date,
                "proposed_role": self.proposed_role, "reason": self.reason, "target_root_id": self.target_root_id}

    def identity_payload(self) -> Dict[str, object]:
        return {"plan_schema_version": self.plan_schema_version, "plan_kind": self.plan_kind,
                "material": self.upstream_arguments(), "target_component": self.target_component,
                "target_component_key": self.target_component_key}

    @classmethod
    def build(cls, **values) -> "ValidatedEvidenceProposalPlan":
        shell = _shell(cls, {"plan_schema_version": PLAN_SCHEMA_VERSION, "plan_kind": PlanKind.EVIDENCE,
                             "target_component_key": ""}, values)
        return cls(plan_id=_plan_id(cls.identity_payload(shell)), **values)


# ---------------------------------------------------------------- THEME


@dataclass(frozen=True, kw_only=True)
class PlannedEvidenceRef:
    """THEME 候補が引く evidence（Foundation attachment の材料。attached_at は B7F が付ける）。"""

    evidence_kind: EvidenceKind
    ref_id: str
    source_origin: SourceOrigin
    evidence_time: Optional[datetime]
    evidence_time_basis: EvidenceTimeBasis
    evidence_time_quality: EvidenceTimeQuality
    evidence_date: str
    role: EvidenceRole = THEME_EVIDENCE_ROLE
    role_provenance: ProvenanceClass = LLM_ROLE_PROVENANCE
    role_asserted_by: str = LLM_ASSERTION_REF

    def __post_init__(self) -> None:
        _require(self.role is THEME_EVIDENCE_ROLE and self.role_provenance is LLM_ROLE_PROVENANCE
                 and self.role_asserted_by == LLM_ASSERTION_REF, "PROVENANCE_ESCALATION",
                 "llm theme evidence is CONTEXT asserted by LLM_PROPOSAL only")

    def attachment(self, attached_at: datetime) -> EvidenceAttachment:
        """Foundation の attachment（検証は Foundation model そのもの）。"""
        return EvidenceAttachment(
            evidence_kind=self.evidence_kind, authority_class=EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL,
            ref_id=self.ref_id, source_origin=self.source_origin, evidence_time=self.evidence_time,
            evidence_time_basis=self.evidence_time_basis, evidence_time_quality=self.evidence_time_quality,
            evidence_date=self.evidence_date, attached_at=attached_at, role=self.role,
            role_provenance=self.role_provenance, role_asserted_by=self.role_asserted_by,
            limited_use=self.evidence_time_quality is EvidenceTimeQuality.INFERRED)


def _check_mechanism_lock(mechanism: Mechanism) -> None:
    for component in mechanism.all_components():
        _require(component.assertion_provenance is LLM_ASSERTION_PROVENANCE  # type: ignore[attr-defined]
                 and component.provenance_ref == LLM_ASSERTION_REF,  # type: ignore[attr-defined]
                 "PROVENANCE_ESCALATION", "llm mechanism components are asserted by LLM_PROPOSAL only")


@dataclass(frozen=True, kw_only=True)
class ValidatedThemeProposalPlan:
    """B3 THEME_CANDIDATE の材料。ThemeRoot も governance lifecycle も作らない。"""

    plan_schema_version: str = PLAN_SCHEMA_VERSION
    plan_kind: PlanKind = PlanKind.THEME
    proposer_class: ProposerClass = LLM_PROPOSER_CLASS
    subject: ThemeSubject
    mechanism: Mechanism
    certainty_class: MechanismCertainty = LLM_FIXED_CERTAINTY
    scope: Tuple[ScopeToken, ...]
    invalidation_conditions: Tuple[InvalidationCondition, ...]
    limitations: Tuple[Limitation, ...] = ()
    evidence_refs: Tuple[PlannedEvidenceRef, ...]
    mechanism_vocabulary_version: str = MECHANISM_VOCABULARY_VERSION
    upstream_proposal_id: str
    llm_rationale: str = ""                           # 監査用。identity に入らない
    plan_id: str

    def __post_init__(self) -> None:
        _require(self.plan_schema_version == PLAN_SCHEMA_VERSION and self.plan_kind is PlanKind.THEME,
                 "NON_CANONICAL_INPUT", "unsupported plan schema")
        _require(self.proposer_class is LLM_PROPOSER_CLASS, "PROVENANCE_ESCALATION",
                 "an llm theme plan is proposed by LLM_PROPOSAL only")
        _require(self.certainty_class is LLM_FIXED_CERTAINTY, "PROVENANCE_ESCALATION",
                 "an llm theme plan is a hypothesized mechanism only")
        _require(isinstance(self.subject, ThemeSubject) and isinstance(self.mechanism, Mechanism), "INVALID_INPUT",
                 "subject and mechanism are Foundation values")
        _check_mechanism_lock(self.mechanism)
        _require(self.mechanism_vocabulary_version == MECHANISM_VOCABULARY_VERSION, "KNOWLEDGE_PIN_MISMATCH",
                 "the plan was validated against another mechanism vocabulary")
        for name, item_type in (("scope", ScopeToken), ("invalidation_conditions", InvalidationCondition),
                                ("limitations", Limitation), ("evidence_refs", PlannedEvidenceRef)):
            items = getattr(self, name)
            _require(isinstance(items, tuple) and all(isinstance(i, item_type) for i in items), "INVALID_INPUT",
                     f"{name} is a tuple of {item_type.__name__}")
        frames = [s.value for s in self.scope if s.dimension is ScopeDimension.PERIOD_FRAME]
        _require(len(frames) == 1 and frames[0] not in SINGLE_PERIOD_FRAMES, "UNSUPPORTED_VOCABULARY",
                 "a Theme declares one PERIOD_FRAME that is not a single session or event")
        _require(len(self.invalidation_conditions) >= 1 and len(self.evidence_refs) >= 1, "INVALID_INPUT",
                 "a Theme plan cites evidence and names an invalidation condition")
        _require(is_content_id(self.upstream_proposal_id, PROPOSAL_ID_PREFIX), "NON_CANONICAL_INPUT",
                 "upstream_proposal_id is a B3 proposal id")
        object.__setattr__(self, "llm_rationale", _audit_text(self.llm_rationale))
        _check_plan_id(self)

    def upstream_arguments(self, attached_at: datetime) -> Dict[str, object]:
        """`ThemeCandidateProposal.build` の引数（provenance と created_at は B7F が付ける）。"""
        return {"subject": self.subject, "mechanism": self.mechanism, "certainty_class": self.certainty_class,
                "scope": self.scope, "invalidation_conditions": self.invalidation_conditions,
                "limitations": self.limitations,
                "evidence_refs": tuple(ref.attachment(attached_at) for ref in self.evidence_refs)}

    def identity_payload(self) -> Dict[str, object]:
        return {"plan_schema_version": self.plan_schema_version, "plan_kind": self.plan_kind,
                "subject": self.subject, "mechanism": self.mechanism, "certainty_class": self.certainty_class,
                "scope": sorted(canonical_json(s) for s in self.scope),
                "invalidation_conditions": sorted(canonical_json(c) for c in self.invalidation_conditions),
                "limitations": sorted(canonical_json(item) for item in self.limitations),
                "evidence_refs": sorted(canonical_json(ref) for ref in self.evidence_refs),
                "mechanism_vocabulary_version": self.mechanism_vocabulary_version}

    @classmethod
    def build(cls, **values) -> "ValidatedThemeProposalPlan":
        shell = _shell(cls, {"plan_schema_version": PLAN_SCHEMA_VERSION, "plan_kind": PlanKind.THEME,
                             "certainty_class": LLM_FIXED_CERTAINTY, "limitations": (),
                             "mechanism_vocabulary_version": MECHANISM_VOCABULARY_VERSION}, values)
        return cls(plan_id=_plan_id(cls.identity_payload(shell)), **values)


# ---------------------------------------------------------------- RELATION


@dataclass(frozen=True, kw_only=True)
class ValidatedRelationProposalPlan:
    """B5C RELATION_CANDIDATE の材料。主張 class を持たない（ACCEPT で人間が決める）。推移的な辺を作らない。"""

    plan_schema_version: str = PLAN_SCHEMA_VERSION
    plan_kind: PlanKind = PlanKind.RELATION
    proposer_class: RelationProposerClass = LLM_RELATION_PROPOSER_CLASS
    source_theme_root_id: str
    target_theme_root_id: str
    relation_type: RelationType
    change_kind: RelationChangeKind = RelationChangeKind.NEW_RELATION
    previous_assertion_id: str = ""
    source_attribution: Optional[SourceAttribution] = None
    source_claim_status: SourceClaimStatus
    evidence_refs: Tuple[RelationEvidenceRef, ...]
    rationale: str
    relation_vocabulary_version: str = RELATION_VOCAB_VERSION
    upstream_proposal_id: str
    llm_rationale: str = ""                           # 監査用。identity に入らない
    plan_id: str

    def __post_init__(self) -> None:
        _require(self.plan_schema_version == PLAN_SCHEMA_VERSION and self.plan_kind is PlanKind.RELATION,
                 "NON_CANONICAL_INPUT", "unsupported plan schema")
        _require(self.proposer_class is LLM_RELATION_PROPOSER_CLASS, "PROVENANCE_ESCALATION",
                 "an llm relation plan is proposed by LLM only")
        _require(is_root_id(self.source_theme_root_id) and is_root_id(self.target_theme_root_id)
                 and self.source_theme_root_id != self.target_theme_root_id, "INVALID_RELATION_ENDPOINT",
                 "a relation connects two distinct Theme roots")
        _require(isinstance(self.relation_type, RelationType) and isinstance(self.change_kind, RelationChangeKind),
                 "INVALID_INPUT", "relation type and change kind are enums")
        _require(isinstance(self.source_claim_status, SourceClaimStatus), "SOURCE_ASSERTED_UNVERIFIED",
                 "an llm relation plan never carries a verified source claim")
        attributed = self.source_attribution is not None
        _require(attributed == (self.source_claim_status is SourceClaimStatus.UNVERIFIED), "SOURCE_ASSERTED_UNVERIFIED",
                 "an attribution is carried as unverified, and only an attribution is")
        _require(isinstance(self.evidence_refs, tuple) and len(self.evidence_refs) >= 1
                 and all(isinstance(e, RelationEvidenceRef) for e in self.evidence_refs), "INVALID_INPUT",
                 "a relation plan cites at least one evidence ref")
        carriers = [e for e in self.evidence_refs if e.attribution]
        if attributed:
            _require(isinstance(self.source_attribution, SourceAttribution) and len(carriers) == 1
                     and carriers[0].attribution == self.source_attribution.attributed_to,  # type: ignore[union-attr]
                     "INVALID_ATTRIBUTION", "exactly the cited source carries the attribution")
        else:
            _require(not carriers, "INVALID_ATTRIBUTION", "no evidence carries an attribution without a claim")
        _require((self.change_kind is RelationChangeKind.CORRECTION) == (self.previous_assertion_id != ""),
                 "INVALID_TARGET", "a correction names the assertion it corrects")
        _require(self.rationale == relation_rationale(self.relation_type, self.change_kind), "NON_CANONICAL_INPUT",
                 "the rationale is not the template text")
        _require(self.relation_vocabulary_version == RELATION_VOCAB_VERSION, "KNOWLEDGE_PIN_MISMATCH",
                 "the plan was validated against another relation vocabulary")
        _require(is_content_id(self.upstream_proposal_id, RELATION_PROPOSAL_ID_PREFIX), "NON_CANONICAL_INPUT",
                 "upstream_proposal_id is a B5C proposal id")
        object.__setattr__(self, "llm_rationale", _audit_text(self.llm_rationale))
        _check_plan_id(self)

    def upstream_arguments(self) -> Dict[str, object]:
        """`RelationProposal.build` の引数（provenance と created_at は B7F が付ける）。"""
        return {"source_theme_root_id": self.source_theme_root_id, "target_theme_root_id": self.target_theme_root_id,
                "relation_type": self.relation_type, "rationale": self.rationale, "change_kind": self.change_kind,
                "previous_assertion_id": self.previous_assertion_id, "source_attribution": self.source_attribution,
                "evidence_refs": self.evidence_refs}

    def identity_payload(self) -> Dict[str, object]:
        arguments = self.upstream_arguments()
        arguments["evidence_refs"] = sorted(canonical_json(e) for e in self.evidence_refs)
        return {"plan_schema_version": self.plan_schema_version, "plan_kind": self.plan_kind,
                "material": arguments, "source_claim_status": self.source_claim_status,
                "relation_vocabulary_version": self.relation_vocabulary_version}

    @classmethod
    def build(cls, **values) -> "ValidatedRelationProposalPlan":
        shell = _shell(cls, {"plan_schema_version": PLAN_SCHEMA_VERSION, "plan_kind": PlanKind.RELATION,
                             "change_kind": RelationChangeKind.NEW_RELATION, "previous_assertion_id": "",
                             "source_attribution": None, "relation_vocabulary_version": RELATION_VOCAB_VERSION}, values)
        return cls(plan_id=_plan_id(cls.identity_payload(shell)), **values)


ValidatedProposalPlan = Union[ValidatedEvidenceProposalPlan, ValidatedThemeProposalPlan, ValidatedRelationProposalPlan]
PLAN_TYPES: Mapping[PlanKind, type] = {PlanKind.EVIDENCE: ValidatedEvidenceProposalPlan,
                                       PlanKind.THEME: ValidatedThemeProposalPlan,
                                       PlanKind.RELATION: ValidatedRelationProposalPlan}


# ---------------------------------------------------------------- 検証結果（生成 1 回分）


@dataclass(frozen=True, kw_only=True)
class LlmValidationResult:
    """生成 1 回の決定論的な検証結果。provider / model / 時刻を持たない。棄権なら plan は 0 件。"""

    result_schema_version: str = RESULT_SCHEMA_VERSION
    validator_version: str = VALIDATOR_VERSION
    request_id: str
    manifest_digest: str
    output_digest: str
    task: LlmTask
    cutoff: datetime
    knowledge_versions: Tuple[Tuple[str, str], ...]
    outcome: ValidationOutcome
    abstention_reason: Optional[AbstentionReason] = None
    plans: Tuple[ValidatedProposalPlan, ...] = ()
    result_id: str

    def __post_init__(self) -> None:
        _require(self.result_schema_version == RESULT_SCHEMA_VERSION and self.validator_version == VALIDATOR_VERSION,
                 "NON_CANONICAL_INPUT", "unsupported result schema")
        _require(isinstance(self.outcome, ValidationOutcome) and isinstance(self.task, LlmTask), "INVALID_INPUT",
                 "outcome and task are enums")
        plans = tuple(self.plans)
        _require(all(isinstance(p, tuple(PLAN_TYPES.values())) for p in plans), "INVALID_INPUT",
                 "plans are validated plan objects")
        if self.outcome is ValidationOutcome.ABSTAINED:
            _require(not plans and isinstance(self.abstention_reason, AbstentionReason), "INVALID_ABSTENTION",
                     "an abstention carries a reason and no plan")
        else:
            _require(len(plans) >= 1 and self.abstention_reason is None, "INVALID_ABSTENTION",
                     "validated candidates carry plans and no abstention")
        ids = [p.plan_id for p in plans]
        _require(len(ids) == len(set(ids)), "DUPLICATE_SEMANTIC_CANDIDATE", "two candidates plan the same proposal")
        object.__setattr__(self, "plans", tuple(sorted(plans, key=lambda p: p.plan_id)))
        _require(self.result_id == content_id(RESULT_ID_PREFIX, canonical_json(self.identity_payload())),
                 "NON_CANONICAL_INPUT", "result_id does not match the result content")

    def identity_payload(self) -> Dict[str, object]:
        return {"result_schema_version": self.result_schema_version, "validator_version": self.validator_version,
                "request_id": self.request_id, "manifest_digest": self.manifest_digest,
                "output_digest": self.output_digest, "task": self.task, "cutoff": self.cutoff,
                "knowledge_versions": [list(pin) for pin in self.knowledge_versions], "outcome": self.outcome,
                "abstention_reason": self.abstention_reason,
                "plan_ids": [p.plan_id for p in self.plans]}

    def as_dict(self) -> Dict[str, object]:
        return {**self.identity_payload(), "plans": self.plans, "result_id": self.result_id}

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())

    @classmethod
    def build(cls, **values) -> "LlmValidationResult":
        plans = tuple(sorted(values.get("plans", ()), key=lambda p: p.plan_id))
        shell = _shell(cls, {"result_schema_version": RESULT_SCHEMA_VERSION, "validator_version": VALIDATOR_VERSION,
                             "abstention_reason": None}, {**values, "plans": plans})
        return cls(result_id=content_id(RESULT_ID_PREFIX, canonical_json(cls.identity_payload(shell))),
                   **{**values, "plans": plans})


__all__ = ["EVIDENCE_REASON_TEMPLATE", "LLM_ASSERTION_PROVENANCE", "LLM_ASSERTION_REF", "LLM_FIXED_CERTAINTY",
           "LLM_PROPOSER_CLASS", "LLM_RELATION_PROPOSER_CLASS", "LLM_ROLE_PROVENANCE", "LlmValidationError",
           "LlmValidationResult", "PLAN_ID_PREFIX", "PLAN_IS_NOT_AUTHORITY", "PLAN_SCHEMA_VERSION", "PLAN_TYPES",
           "PlanKind", "PlannedEvidenceRef", "RATIONALE_IS_NOT_IDENTITY", "RELATION_RATIONALE_TEMPLATE",
           "RESULT_ID_PREFIX", "RESULT_SCHEMA_VERSION", "ROLE_TARGET_COMPONENT", "SOURCE_CLAIM_IS_UNVERIFIED",
           "SourceClaimStatus", "THEME_EVIDENCE_ROLE", "TargetComponentKind", "VALIDATION_ERROR_CODES",
           "VALIDATOR_VERSION", "ValidatedEvidenceProposalPlan", "ValidatedProposalPlan", "ValidatedRelationProposalPlan",
           "ValidatedThemeProposalPlan", "ValidationOutcome", "evidence_reason", "relation_rationale"]
