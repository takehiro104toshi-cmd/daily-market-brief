"""P6-B7D — LLM 生成の決定論的な意味検証（grounding・正規化・提案 plan。純関数）。

`validate_generation(*, request, envelope, manifest) -> LlmValidationResult`

LLM の出力は信頼しない。検証が見るのは schema・handle・有界な語彙・knowledge pin・決定論の code だけで、
文の中の指示（「承認せよ」「HUMAN とせよ」など）は何の効果も持たない。

順序（どこか 1 か所でも違反すれば生成全体を拒否する。部分採用・黙った修復・近い候補への置換をしない）:

1. 型と束縛: request ↔ manifest（digest・task・cutoff・schema）と knowledge pin の一致
2. 棄権: 正しい ABSTAIN は plan 0 件の検証済み結果。形の崩れた棄権は拒否
3. canonical 形・task と candidate kind / evidence role の整合
4. 候補ごと: handle を B7C の内部対応表で解決（未知・family 違い・scope 外は拒否）→ 凍結語彙で正規化 →
   provenance を LLM に固定 → identity 文を template で作る → 凍結済みの B3 / B5C constructor に通して上流 id を得る
5. 同一生成内の意味的な重複は拒否

読まないもの: data root・store・journal・現在時刻・network・provider。書かないもの: すべて。
"""
from __future__ import annotations

import json
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..core.time import from_iso
from ..themes.model import (MECHANISM_CATEGORIES, OTHER_CATEGORY, SINGLE_PERIOD_FRAMES, ComponentType, EvidenceKind,
                            EvidenceRole, EvidenceTimeBasis, EvidenceTimeQuality, ExpectedConsequence,
                            InvalidationCondition, Limitation, Mechanism, MechanismComponent, OriginKind,
                            ScopeDimension, ScopeToken, SourceOrigin, ThemeSubject, canonical_json, normalize_text)
from .llm_manifest_model import (MECHANISM_VOCABULARY_PIN, RELATION_VOCABULARY_PIN, TASK_FAMILIES, HandleRef,
                                 LlmInputManifest, ManifestFamily)
from .llm_plan_model import (LLM_ASSERTION_PROVENANCE, LLM_ASSERTION_REF, LLM_FIXED_CERTAINTY, LLM_PROPOSER_CLASS,
                             LLM_RELATION_PROPOSER_CLASS, ROLE_TARGET_COMPONENT, LlmValidationError,
                             LlmValidationResult, PlannedEvidenceRef, SourceClaimStatus, TargetComponentKind,
                             ValidatedEvidenceProposalPlan, ValidatedProposalPlan, ValidatedRelationProposalPlan,
                             ValidatedThemeProposalPlan, ValidationOutcome, evidence_reason, relation_rationale)
from .llm_proposal_model import (OUTPUT_SCHEMA_VERSION, TASK_CANDIDATE_KINDS, TASK_EVIDENCE_ROLES, AbstentionReason,
                                 CandidateKind, EnvelopeOutcome, EvidenceCandidatePayload, LlmAbstention, LlmCandidate,
                                 LlmGenerationEnvelope, LlmGenerationRequest, RelationCandidatePayload,
                                 ThemeCandidatePayload)
from .proposal_model import EvidenceCandidateProposal, ProposalModelError, ProposalProvenance, ThemeCandidateProposal
from .relation_model import RelationEvidenceRef, RelationType, SourceAttribution, split_edge_key
from .relation_proposal_model import RelationChangeKind, RelationProposal, RelationProposalProvenance

#: 出力 schema が固定する語彙の version（schema version を上げずに Foundation / B5 の語彙が変われば fail closed）
OUTPUT_SCHEMA_VOCABULARIES: Mapping[str, Tuple[Tuple[str, str], ...]] = {
    OUTPUT_SCHEMA_VERSION: (("mechanism_vocabulary", "0.1.0"), ("theme_relation_vocabulary", "0.1.0")),
}
#: 出典が関係を「主張」しうる evidence（文章の kind）と、帰属に使える origin
ATTRIBUTABLE_KINDS: Tuple[EvidenceKind, ...] = (EvidenceKind.NEWS_ITEM, EvidenceKind.SOURCE_DOCUMENT,
                                                EvidenceKind.STATEMENT)
ATTRIBUTABLE_ORIGINS: Tuple[OriginKind, ...] = (OriginKind.PUBLISHER_ARTICLE, OriginKind.OFFICIAL_RELEASE)
#: component の key（B4 discovery と同じ形。LLM の順序ではなく正規化済み材料の canonical 順で振る）
COMPONENT_SLOTS: Tuple[Tuple[str, ComponentType, str], ...] = (
    ("drivers", ComponentType.DRIVER, "driver"), ("channels", ComponentType.TRANSMISSION_CHANNEL, "channel"),
    ("domains", ComponentType.AFFECTED_DOMAIN, "domain"))
ROLE_COMPONENT_FAMILY: Mapping[TargetComponentKind, str] = {
    TargetComponentKind.CONSEQUENCE: "THEME_CONSEQUENCE",
    TargetComponentKind.INVALIDATION_CONDITION: "THEME_INVALIDATION",
}
COMPONENT_DETAIL_KEY: Mapping[str, str] = {"THEME_CONSEQUENCE": "component_key",
                                           "THEME_INVALIDATION": "condition_key"}


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise LlmValidationError(code, detail)


def _upstream_code(exc: Exception) -> str:
    return str(getattr(exc, "code", "") or type(exc).__name__)


# ---------------------------------------------------------------- 束縛と knowledge


def _check_binding(request: LlmGenerationRequest, envelope: LlmGenerationEnvelope, manifest: LlmInputManifest) -> None:
    _require(isinstance(request, LlmGenerationRequest) and isinstance(envelope, LlmGenerationEnvelope)
             and isinstance(manifest, LlmInputManifest), "INVALID_INPUT",
             "a B7B request, a B7B envelope and a B7C manifest are required")
    _require(request.manifest_digest == manifest.manifest_digest(), "REQUEST_MANIFEST_MISMATCH",
             "the request was made for another manifest")
    _require(request.task is manifest.task, "TASK_MISMATCH", "the request task differs from the manifest task")
    _require(request.cutoff == manifest.cutoff, "REQUEST_MANIFEST_MISMATCH", "the request cutoff differs")
    _require(request.output_schema_version == envelope.output_schema_version == OUTPUT_SCHEMA_VERSION,
             "REQUEST_MANIFEST_MISMATCH", "the output schema differs from the request")
    _require(tuple(request.knowledge_versions) == tuple(manifest.knowledge_versions), "KNOWLEDGE_PIN_MISMATCH",
             "the request pins other knowledge than the manifest")


def _knowledge_in_force(manifest: LlmInputManifest) -> Tuple[Tuple[str, str], ...]:
    """検証に使う knowledge が manifest の pin と出力 schema が束ねた語彙に一致することを示す。"""
    pins = dict(manifest.knowledge_versions)
    code_pins = dict((MECHANISM_VOCABULARY_PIN, RELATION_VOCABULARY_PIN))
    for name, version in OUTPUT_SCHEMA_VOCABULARIES[OUTPUT_SCHEMA_VERSION]:
        _require(code_pins.get(name) == version, "KNOWLEDGE_PIN_MISMATCH",
                 f"the frozen {name} differs from the output schema")
        _require(pins.get(name, version) == version, "KNOWLEDGE_PIN_MISMATCH",
                 f"the manifest pins another {name}")
    return tuple(sorted({**dict(OUTPUT_SCHEMA_VOCABULARIES[OUTPUT_SCHEMA_VERSION]), **pins}.items()))


# ---------------------------------------------------------------- manifest の解決（B7C の内部対応表だけ）


class _Grounding:
    def __init__(self, manifest: LlmInputManifest) -> None:
        self.task = manifest.task
        self.table: Dict[str, HandleRef] = {ref.handle: ref for ref in manifest.resolution}
        self.evidence_entities = {view.handle: set(view.entity_handles) for view in manifest.evidence}
        self.finding_subject = {view.handle: view.subject_handle for view in manifest.findings}
        self.theme_components = {theme.handle: {
            "THEME_CONSEQUENCE": [c.handle for c in theme.consequences if c.handle],
            "THEME_INVALIDATION": [i.handle for i in theme.invalidation_conditions if i.handle]}
            for theme in manifest.themes}

    def resolve(self, handle: object, family: str) -> HandleRef:
        ref = self.table.get(handle) if isinstance(handle, str) else None
        _require(ref is not None, "UNKNOWN_HANDLE", "a cited handle is not in the manifest")
        _require(ref.family == family, "HANDLE_FAMILY_MISMATCH",  # type: ignore[union-attr]
                 f"{handle} is not a {family.lower()} handle")
        return ref  # type: ignore[return-value]

    def evidence(self, handle: str) -> Tuple[HandleRef, Dict[str, object]]:
        ref = self.resolve(handle, "EVIDENCE")
        detail = dict(ref.detail)
        try:
            material = {
                "evidence_kind": EvidenceKind(detail["evidence_kind"]), "ref_id": ref.ref,
                "source_origin": SourceOrigin.from_dict(json.loads(str(detail["source_origin"]))),
                "evidence_time": from_iso(str(detail["evidence_time"])) if detail["evidence_time"] else None,
                "evidence_time_basis": EvidenceTimeBasis(detail["evidence_time_basis"]),
                "evidence_time_quality": EvidenceTimeQuality(detail["evidence_time_quality"]),
                "evidence_date": str(detail["evidence_date"])}
        except (KeyError, ValueError, TypeError):
            raise LlmValidationError("NON_CANONICAL_INPUT", f"{handle} does not resolve to evidence material") from None
        return ref, material

    def permits(self, family: ManifestFamily) -> bool:
        families = TASK_FAMILIES[self.task]
        return family in set(families.required) | set(families.optional) | set(families.derived)


def _context_findings(grounding: _Grounding, candidate: LlmCandidate, subject_handle: str) -> Tuple[str, ...]:
    """MON は文脈だけ。task が許し、候補と同じ Theme を扱う finding に限る。evidence にはならない。"""
    refs = []
    for handle in candidate.context_handles:
        ref = grounding.resolve(handle, "MONITORING")
        _require(grounding.permits(ManifestFamily.MONITORING), "OUT_OF_SCOPE_REFERENCE",
                 "this task does not take monitoring context")
        _require(grounding.finding_subject.get(handle) == subject_handle, "OUT_OF_SCOPE_REFERENCE",
                 f"{handle} concerns another Theme")
        refs.append(ref.ref)
    return tuple(refs)


# ---------------------------------------------------------------- 候補ごとの検証 → plan


def _evidence_plan(grounding: _Grounding, candidate: LlmCandidate, request: LlmGenerationRequest
                   ) -> ValidatedEvidenceProposalPlan:
    payload = candidate.payload
    _require(isinstance(payload, EvidenceCandidatePayload), "INVALID_INPUT", "an evidence candidate payload")
    _require(len(candidate.evidence_handles) == 1, "NON_CANONICAL_INPUT", "an evidence candidate cites one item")
    _ref, material = grounding.evidence(candidate.evidence_handles[0])
    target = grounding.resolve(payload.target_handle, "THEME")
    role = payload.proposed_role
    _require(isinstance(role, EvidenceRole) and role in TASK_EVIDENCE_ROLES.get(grounding.task, ()),
             "INVALID_EVIDENCE_ROLE", "the role is not allowed for this task")
    _require(material["evidence_time_quality"] is not EvidenceTimeQuality.MISSING or role is EvidenceRole.CONTEXT,
             "INVALID_EVIDENCE_ROLE", "evidence without a reliable time may only be context")
    component = ROLE_TARGET_COMPONENT[role]
    key = ""
    if component is TargetComponentKind.NONE:
        _require(payload.component_handle == "", "INVALID_TARGET", "context evidence names no component")
    else:
        family = ROLE_COMPONENT_FAMILY[component]
        if payload.component_handle == "":
            options = grounding.theme_components.get(payload.target_handle, {}).get(family, [])
            _require(len(options) <= 1, "AMBIGUOUS_TARGET", f"{role.value} needs one of several components")
            _require(False, "INVALID_TARGET", f"{role.value} needs an explicit component")
        part = grounding.resolve(payload.component_handle, family)
        _require(part.ref == target.ref, "INVALID_TARGET", "the component belongs to another Theme")
        key = str(dict(part.detail).get(COMPONENT_DETAIL_KEY[family], ""))
        _require(key != "", "NON_CANONICAL_INPUT", "the component does not resolve to a key")
    findings = _context_findings(grounding, candidate, payload.target_handle)
    reason = evidence_reason(role, material["evidence_kind"], component, key)  # type: ignore[arg-type]
    upstream = EvidenceCandidateProposal.build(
        **material, proposed_role=role, reason=reason, target_root_id=target.ref,  # type: ignore[arg-type]
        provenance=ProposalProvenance(LLM_PROPOSER_CLASS, request.request_id,
                                      rule_version=request.prompt_contract_version),
        created_at=request.generated_at)
    return ValidatedEvidenceProposalPlan.build(
        **material, proposed_role=role, target_root_id=target.ref, target_component=component,
        target_component_key=key, reason=reason, upstream_proposal_id=upstream.proposal_id,
        llm_rationale=candidate.rationale, context_finding_refs=findings)


def _entity(grounding: _Grounding, handle: str, cited: set) -> str:
    if handle == "":
        return ""
    ref = grounding.resolve(handle, "ENTITY")
    _require(handle in cited, "OUT_OF_SCOPE_REFERENCE", f"{handle} is not carried by the cited evidence")
    return ref.ref


def _unique(items: Sequence[object], what: str) -> List[object]:
    """正規化後の材料を canonical 順に並べる。正規化で同じになったものは入力が canonical でない（黙って畳まない）。"""
    keyed = sorted(((canonical_json(item), item) for item in items), key=lambda pair: pair[0])
    keys = [key for key, _item in keyed]
    _require(len(keys) == len(set(keys)), "NON_CANONICAL_INPUT", f"two {what} normalize to the same material")
    return [item for _key, item in keyed]


def _category(component_type: ComponentType, category: object, statement: str) -> str:
    _require(isinstance(category, str) and category in MECHANISM_CATEGORIES[component_type], "UNSUPPORTED_VOCABULARY",
             f"{component_type.value} category is not in the mechanism vocabulary")
    _require(category != OTHER_CATEGORY or statement != "", "UNSUPPORTED_VOCABULARY", "OTHER needs a statement")
    return str(category)


def _mechanism(grounding: _Grounding, payload: ThemeCandidatePayload, cited: set) -> Mechanism:
    parts: Dict[str, Tuple[MechanismComponent, ...]] = {}
    for name, component_type, prefix in COMPONENT_SLOTS:
        drafts = getattr(payload, name)
        _require(isinstance(drafts, tuple) and len(drafts) >= 1, "NON_CANONICAL_INPUT", f"theme {name} are required")
        materials = []
        for draft in drafts:
            statement = normalize_text(draft.statement)
            materials.append({"category": _category(component_type, draft.category, statement),
                              "typed_reference": _entity(grounding, draft.entity_handle, cited),
                              "normalized_statement": statement})
        parts[name] = tuple(
            MechanismComponent(component_type=component_type, component_key=f"{prefix}_{index}",
                               assertion_provenance=LLM_ASSERTION_PROVENANCE, provenance_ref=LLM_ASSERTION_REF,
                               **item)  # type: ignore[arg-type]
            for index, item in enumerate(_unique(materials, name), start=1))
    consequences = []
    for draft in payload.consequences:
        statement = normalize_text(draft.statement)
        consequences.append({"category": _category(ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE, draft.category,
                                                    statement),
                             "observable_target": draft.observable_target, "expected_change": draft.expected_change,
                             "normalized_statement": statement})
    expected = tuple(
        ExpectedConsequence(component_key=f"consequence_{index}", assertion_provenance=LLM_ASSERTION_PROVENANCE,
                            provenance_ref=LLM_ASSERTION_REF, **item)  # type: ignore[arg-type]
        for index, item in enumerate(_unique(consequences, "consequences"), start=1))
    return Mechanism(drivers=parts["drivers"], channels=parts["channels"], domains=parts["domains"],
                     consequences=expected)


def _scope(payload: ThemeCandidatePayload) -> Tuple[ScopeToken, ...]:
    tokens = []
    for draft in payload.scope:
        _require(isinstance(draft.dimension, ScopeDimension), "UNSUPPORTED_VOCABULARY", "unknown scope dimension")
        value = normalize_text(draft.value)
        _require(draft.dimension is not ScopeDimension.PERIOD_FRAME or value not in SINGLE_PERIOD_FRAMES,
                 "UNSUPPORTED_VOCABULARY", "a single session or event is not a Theme period")
        tokens.append(ScopeToken(dimension=draft.dimension, value=value))
    frames = [t for t in tokens if t.dimension is ScopeDimension.PERIOD_FRAME]
    _require(len(frames) == 1, "UNSUPPORTED_VOCABULARY", "a Theme declares exactly one PERIOD_FRAME")
    return tuple(_unique(tokens, "scope tokens"))  # type: ignore[arg-type]


def _theme_plan(grounding: _Grounding, candidate: LlmCandidate, request: LlmGenerationRequest
                ) -> ValidatedThemeProposalPlan:
    payload = candidate.payload
    _require(isinstance(payload, ThemeCandidatePayload), "INVALID_INPUT", "a theme candidate payload")
    evidence = [grounding.evidence(handle) for handle in candidate.evidence_handles]
    cited = set().union(*(grounding.evidence_entities.get(ref.handle, set()) for ref, _m in evidence))
    _context_findings(grounding, candidate, "")
    subject = ThemeSubject(normalized_subject=normalize_text(payload.subject_statement),
                           typed_reference=_entity(grounding, payload.subject_entity_handle, cited))
    mechanism = _mechanism(grounding, payload, cited)
    scope = _scope(payload)
    conditions = tuple(
        InvalidationCondition(condition_key=f"invalidation_{index}", **item)  # type: ignore[arg-type]
        for index, item in enumerate(_unique([
            {"normalized_statement": normalize_text(c.statement), "observable_target": c.observable_target,
             "expected_change": c.expected_change} for c in payload.invalidation_conditions],
            "invalidation conditions"), start=1))
    limitations = tuple(_unique([Limitation(category=item.category, normalized_statement=normalize_text(item.statement))
                                 for item in candidate.limitations], "limitations"))
    refs = tuple(_unique([PlannedEvidenceRef(**material) for _ref, material in evidence],  # type: ignore[arg-type]
                         "evidence refs"))
    upstream = ThemeCandidateProposal.build(
        subject=subject, mechanism=mechanism, certainty_class=LLM_FIXED_CERTAINTY, scope=scope,
        invalidation_conditions=conditions, limitations=limitations,  # type: ignore[arg-type]
        evidence_refs=tuple(ref.attachment(request.generated_at) for ref in refs),  # type: ignore[union-attr]
        provenance=ProposalProvenance(LLM_PROPOSER_CLASS, request.request_id,
                                      rule_version=request.prompt_contract_version),
        created_at=request.generated_at)
    return ValidatedThemeProposalPlan.build(
        subject=subject, mechanism=mechanism, scope=scope, invalidation_conditions=conditions, limitations=limitations,
        evidence_refs=refs, upstream_proposal_id=upstream.proposal_id, llm_rationale=candidate.rationale)


def _attribution(grounding: _Grounding, handle: str, cited: Sequence[str]) -> Optional[SourceAttribution]:
    """出典帰属 ＝ 引用した文章 evidence の origin（Foundation の source identity）。真実性でも確認でもない。"""
    if handle == "":
        return None
    _require(handle in cited, "INVALID_ATTRIBUTION", "the attributed evidence is not cited")
    _ref, material = grounding.evidence(handle)
    origin = material["source_origin"]
    _require(material["evidence_kind"] in ATTRIBUTABLE_KINDS and origin.origin_kind in ATTRIBUTABLE_ORIGINS,  # type: ignore[union-attr]
             "INVALID_ATTRIBUTION", f"{handle} is not a source that can assert a relation")
    return SourceAttribution(attributed_to=origin.origin_key)  # type: ignore[union-attr]


def _relation_plan(grounding: _Grounding, candidate: LlmCandidate, request: LlmGenerationRequest
                   ) -> ValidatedRelationProposalPlan:
    payload = candidate.payload
    _require(isinstance(payload, RelationCandidatePayload), "INVALID_INPUT", "a relation candidate payload")
    source = grounding.resolve(payload.source_handle, "THEME")
    target = grounding.resolve(payload.target_handle, "THEME")
    _require(source.ref != target.ref, "INVALID_RELATION_ENDPOINT", "a relation connects two distinct Themes")
    _require(isinstance(payload.relation_type, RelationType), "UNSUPPORTED_VOCABULARY", "unknown relation type")
    attribution = _attribution(grounding, payload.attribution_evidence_handle, candidate.evidence_handles)
    refs = []
    for handle in candidate.evidence_handles:
        _ref, material = grounding.evidence(handle)
        carries = attribution is not None and handle == payload.attribution_evidence_handle
        refs.append(RelationEvidenceRef(evidence_kind=material["evidence_kind"], ref_id=material["ref_id"],  # type: ignore[arg-type]
                                        source_origin=material["source_origin"],  # type: ignore[arg-type]
                                        evidence_time=material["evidence_time"],  # type: ignore[arg-type]
                                        attribution=attribution.attributed_to if carries else ""))  # type: ignore[union-attr]
    change, previous = RelationChangeKind.NEW_RELATION, ""
    if payload.previous_relation_handle:
        edge = grounding.resolve(payload.previous_relation_handle, "RELATION")
        try:
            edge_source, edge_target, edge_type, _class, edge_attribution = split_edge_key(
                str(dict(edge.detail).get("edge_key", "")))
        except ValueError:
            raise LlmValidationError("NON_CANONICAL_INPUT", "the corrected relation has no edge key") from None
        _require((edge_source, edge_target, edge_type) == (source.ref, target.ref, payload.relation_type),
                 "INVALID_TARGET", "a correction keeps the endpoints and type of the corrected relation")
        _require(edge_attribution == (attribution.attribution_key if attribution else ""), "INVALID_TARGET",
                 "a correction keeps the attribution of the corrected relation")
        change, previous = RelationChangeKind.CORRECTION, edge.ref
    _context_findings(grounding, candidate, "")
    rationale = relation_rationale(payload.relation_type, change)
    status = SourceClaimStatus.UNVERIFIED if attribution is not None else SourceClaimStatus.NOT_CLAIMED
    upstream = RelationProposal.build(
        source_theme_root_id=source.ref, target_theme_root_id=target.ref, relation_type=payload.relation_type,
        rationale=rationale, change_kind=change, previous_assertion_id=previous, source_attribution=attribution,
        evidence_refs=tuple(refs), created_at=request.generated_at,
        provenance=RelationProposalProvenance(proposer_class=LLM_RELATION_PROPOSER_CLASS,
                                              proposer_ref=request.request_id,
                                              rule_version=request.prompt_contract_version))
    return ValidatedRelationProposalPlan.build(
        source_theme_root_id=source.ref, target_theme_root_id=target.ref, relation_type=payload.relation_type,
        change_kind=change, previous_assertion_id=previous, source_attribution=attribution, source_claim_status=status,
        evidence_refs=tuple(refs), rationale=rationale, upstream_proposal_id=upstream.proposal_id,
        llm_rationale=candidate.rationale)


PLANNERS = {CandidateKind.EVIDENCE: _evidence_plan, CandidateKind.THEME: _theme_plan,
            CandidateKind.RELATION: _relation_plan}


# ---------------------------------------------------------------- 生成全体


def _check_abstention(envelope: LlmGenerationEnvelope) -> Optional[AbstentionReason]:
    _require(isinstance(envelope.outcome, EnvelopeOutcome), "INVALID_INPUT", "unknown envelope outcome")
    if envelope.outcome is EnvelopeOutcome.ABSTAIN:
        abstention = envelope.abstention
        _require(tuple(envelope.candidates) == () and isinstance(abstention, LlmAbstention)
                 and isinstance(abstention.reason, AbstentionReason), "INVALID_ABSTENTION",
                 "an abstention carries a bounded reason and no candidate")
        return abstention.reason  # type: ignore[union-attr]
    _require(envelope.abstention is None and len(envelope.candidates) >= 1, "INVALID_ABSTENTION",
             "candidates are never mixed with an abstention, and an empty output is not an abstention")
    return None


def _check_canonical(grounding: _Grounding, candidates: Sequence[object]) -> None:
    _require(isinstance(candidates, tuple) and all(isinstance(c, LlmCandidate) for c in candidates),
             "NON_CANONICAL_INPUT", "candidates are B7B candidates")
    keys = [c.structural_key() for c in candidates]  # type: ignore[union-attr]
    _require(keys == sorted(set(keys)), "NON_CANONICAL_INPUT", "candidates are not in the canonical form")
    for candidate in candidates:
        for handles in (candidate.evidence_handles, candidate.context_handles):  # type: ignore[union-attr]
            _require(isinstance(handles, tuple) and list(handles) == sorted(set(handles)), "NON_CANONICAL_INPUT",
                     "cited handles are not in the canonical form")
        _require(candidate.candidate_kind in TASK_CANDIDATE_KINDS[grounding.task], "TASK_MISMATCH",  # type: ignore[union-attr]
                 "this task does not produce this candidate kind")


def _output_digest(envelope: LlmGenerationEnvelope) -> str:
    try:
        return envelope.output_digest()
    except (AttributeError, TypeError, ValueError):             # 構造検査の後で書き換えられた envelope
        raise LlmValidationError("NON_CANONICAL_INPUT", "the envelope has no canonical form") from None


def validate_generation(*, request: LlmGenerationRequest, envelope: LlmGenerationEnvelope,
                        manifest: LlmInputManifest) -> LlmValidationResult:
    """構造化出力を、その要求の manifest に対してだけ検証する。違反が 1 件でもあれば全体を拒否する。"""
    _check_binding(request, envelope, manifest)
    knowledge = _knowledge_in_force(manifest)
    reason = _check_abstention(envelope)
    common = dict(request_id=request.request_id, manifest_digest=manifest.manifest_digest(), task=manifest.task,
                  cutoff=manifest.cutoff, knowledge_versions=knowledge)
    if reason is not None:
        return LlmValidationResult.build(outcome=ValidationOutcome.ABSTAINED, abstention_reason=reason,
                                         output_digest=_output_digest(envelope), **common)
    grounding = _Grounding(manifest)
    _check_canonical(grounding, envelope.candidates)
    plans: List[ValidatedProposalPlan] = []
    codes: List[str] = []
    first: Optional[LlmValidationError] = None
    for candidate in envelope.candidates:
        try:
            plans.append(PLANNERS[candidate.candidate_kind](grounding, candidate, request))
        except LlmValidationError as exc:                    # 残りも検査して code を集める（採用はしない）
            codes.extend(exc.codes)
            first = first or exc
        except (ValueError, ProposalModelError) as exc:      # 凍結済みの上流 model が拒否した（code だけを残す）
            first = first or LlmValidationError("UPSTREAM_CONTRACT_VIOLATION", _upstream_code(exc))
            codes.append("UPSTREAM_CONTRACT_VIOLATION")
        except (TypeError, AttributeError, KeyError):        # 型の崩れた入力（本文を echo しない）
            first = first or LlmValidationError("INVALID_INPUT", "a candidate is malformed")
            codes.append("INVALID_INPUT")
    if first is not None:
        raise LlmValidationError(first.code, first.detail, tuple(codes))
    ids = [plan.plan_id for plan in plans]
    _require(len(ids) == len(set(ids)), "DUPLICATE_SEMANTIC_CANDIDATE",
             "two candidates normalize to the same proposal material")
    return LlmValidationResult.build(outcome=ValidationOutcome.PLANS, plans=tuple(plans),
                                     output_digest=_output_digest(envelope), **common)


__all__ = ["ATTRIBUTABLE_KINDS", "ATTRIBUTABLE_ORIGINS", "OUTPUT_SCHEMA_VOCABULARIES", "validate_generation"]
