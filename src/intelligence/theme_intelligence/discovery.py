"""P6-B4C — deterministic Theme discovery（純関数）。

`discover(inputs, *, taxonomy, entity_catalog, ruleset, cutoff, run_created_at, existing_proposals=(), existing_decisions=(),
theme_resolutions=(), include_dedup=True) -> DiscoveryResult`

- pin: ruleset は taxonomy_version / catalog_version を正確に pin し、3 つの knowledge はいずれも published_at ≤ cutoff。
- rule 評価: ACTIVE rule ごとに、input_kinds で候補を絞り → negative predicate（一致で除外。部分点なし）→ predicate（入力単位）→
  集約 MIN_DISTINCT → 生成。DEPRECATED rule は評価せず報告のみ。
- EVIDENCE_CANDIDATE: matched 入力ごとに B3 `EvidenceCandidateProposal`。reason は rule 非依存の canonical 文字列。
- THEME_CANDIDATE: L1 hit ≥ 1、template（人間 authoring の因果仮説）＋ 決定論的 binding（${entity} / ${entity.<attr>} / ${series}）＋
  同一 rule 内の evidence 集約（重複 ref は畳む。同一 origin は独立と呼ばない）。certainty は HYPOTHESIZED_MECHANISM 固定。
- 収束: 等価な semantic proposal は rule を跨いで同一 proposal_id（rule 由来の値は ProposalProvenance と run report にのみ置く）。
- suppression: 既存 proposal と同 id は返さない（decision 状態は診断にだけ載せる。決定を変えない）。
- dedup: 新 THEME_CANDIDATE に対し B3 の exact dedup 検出器を呼ぶ（任意）。fuzzy 拡張なし。

書かない: ProposalStore / Foundation / decision。呼ばない: 現在時刻 / network / LLM。持たない: score / rank / 順位。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..themes.model import (AssertionProvenance, EntityRef, EvidenceAttachment, EvidenceAuthorityClass, EvidenceRole, EvidenceTimeQuality,
                            ExpectedConsequence, InvalidationCondition, Limitation, Mechanism, MechanismComponent, ComponentType,
                            ProvenanceClass, ScopeToken, ThemeEntityKind, ThemeSubject, normalize_text)
from .dedup import detect_exact_duplicates
from .discovery_model import (BINDING_ENTITY, BINDING_ENTITY_ATTRIBUTE_PREFIX, BINDING_SERIES, FIXED_CERTAINTY, TEMPLATE_PROVENANCE_REF,
                              DiscoveryError, DiscoveryInputRecord, DiscoveryResult, DiscoveryRule, DiscoveryRuleset, DiscoveryRunReport,
                              MatchLevel, PredicateHit, RuleEvaluation, RuleHit, RuleOutputType, RuleStatus)
from .discovery_adapter import adapt_inputs
from .discovery_predicates import evaluate_aggregate, evaluate_predicate
from .discovery_rules import check_ruleset_pins
from .entity_model import EntityCatalogSnapshot
from .proposal_model import (DEDUP_MODEL_VERSION, EvidenceCandidateProposal, ProposalProvenance, ProposalType, ProposerClass,
                             ThemeCandidateProposal)
from .proposal_resolution import derive_proposal_status
from .taxonomy_model import TaxonomySnapshot

EVIDENCE_REASON_TEMPLATE = "discovery evidence candidate {role} {kind}"


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DiscoveryError("INVALID_RUN_TIME", f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _pins_reason(taxonomy: TaxonomySnapshot, entity_catalog: EntityCatalogSnapshot, ruleset: DiscoveryRuleset) -> str:
    return (f"pins taxonomy={taxonomy.taxonomy_version} catalog={entity_catalog.catalog_version} "
            f"ruleset={ruleset.ruleset_version}")


def _provenance(rule: DiscoveryRule, pins: str) -> ProposalProvenance:
    return ProposalProvenance(ProposerClass.RULE, rule.rule_ref, rule_version=rule.rule_version, reason=pins)


def evidence_reason(role: EvidenceRole, kind: str) -> str:
    """rule id / version を含まない canonical reason（同じ evidence × role × target の提案は rule を跨いで同一 id になる）。"""
    return normalize_text(EVIDENCE_REASON_TEMPLATE.format(role=role.value, kind=kind))


# ---------------------------------------------------------------- binding


def _bind(value: str, *, rule: DiscoveryRule, entity_catalog: EntityCatalogSnapshot) -> str:
    if value == BINDING_ENTITY:
        return rule.entity_refs[0]
    if value.startswith(BINDING_ENTITY_ATTRIBUTE_PREFIX) and value.endswith("}"):
        attribute = value[len(BINDING_ENTITY_ATTRIBUTE_PREFIX):-1]
        entity = entity_catalog.entity(rule.entity_refs[0]) if rule.entity_refs else None
        attributes = dict(entity.attributes) if entity is not None else {}
        if attribute not in attributes:
            raise DiscoveryError("BINDING_UNRESOLVED", value)
        return attributes[attribute]
    if value == BINDING_SERIES:
        series = rule.series_binding()
        if not series:
            raise DiscoveryError("BINDING_UNRESOLVED", value)
        return series
    return value


def _entity_ref(entity_id: str) -> EntityRef:
    kind_value = entity_id.split(":", 1)[0]
    return EntityRef(kind=ThemeEntityKind(kind_value), value=entity_id)


PRIMARY_CONSEQUENCE_KEY = "consequence_1"      # SUPPORTS evidence は template の第 1 consequence に結びつける（MVP。B3 が要求）


def _attachment(record: DiscoveryInputRecord, rule: DiscoveryRule, attached_at: datetime) -> Tuple[Optional[EvidenceAttachment], str]:
    if record.evidence_time_quality is EvidenceTimeQuality.MISSING and rule.proposed_role is not EvidenceRole.CONTEXT:
        return None, f"ROLE_REQUIRES_EVIDENCE_TIME:{record.input_id}"
    subject_refs = tuple(_entity_ref(h.entity_id) for h in record.entity_hits if h.level is MatchLevel.L1)
    consequence_ref = PRIMARY_CONSEQUENCE_KEY if rule.proposed_role is EvidenceRole.SUPPORTS else ""
    try:
        attachment = EvidenceAttachment(
            evidence_kind=record.evidence_kind, authority_class=EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL, ref_id=record.input_id,
            source_origin=record.source_origin, evidence_time=record.evidence_time, evidence_time_basis=record.evidence_time_basis,
            evidence_time_quality=record.evidence_time_quality, evidence_date=record.evidence_date, attached_at=attached_at,
            role=rule.proposed_role, role_provenance=ProvenanceClass.RULE, role_asserted_by=TEMPLATE_PROVENANCE_REF,
            consequence_ref=consequence_ref, limited_use=record.evidence_time_quality is EvidenceTimeQuality.INFERRED,
            subject_refs=subject_refs)
    except ValueError as exc:                                              # Foundation の検証（時刻 / 語彙）に落ちた入力は付与しない
        return None, f"ATTACHMENT_REJECTED:{record.input_id}:{getattr(exc, 'code', type(exc).__name__)}"
    return attachment, ""


def _build_theme_candidate(rule: DiscoveryRule, records: Sequence[DiscoveryInputRecord], *, entity_catalog: EntityCatalogSnapshot,
                           run_created_at: datetime, pins: str) -> Tuple[Optional[ThemeCandidateProposal], Tuple[str, ...]]:
    diagnostics: List[str] = []
    template = rule.mechanism_template
    subject_template = rule.subject_template
    assert template is not None and subject_template is not None
    bind = lambda value: _bind(value, rule=rule, entity_catalog=entity_catalog)  # noqa: E731
    try:
        components = {}
        for name, component_type in (("drivers", ComponentType.DRIVER), ("channels", ComponentType.TRANSMISSION_CHANNEL),
                                     ("domains", ComponentType.AFFECTED_DOMAIN)):
            components[name] = tuple(
                MechanismComponent(component_type=component_type, component_key=f"{name[:-1]}_{index + 1}", category=item.category,
                                   typed_reference=bind(item.typed_reference), normalized_statement=item.normalized_statement,
                                   assertion_provenance=AssertionProvenance.RULE, provenance_ref=TEMPLATE_PROVENANCE_REF)
                for index, item in enumerate(getattr(template, name)))
        consequences = tuple(
            ExpectedConsequence(component_key=f"consequence_{index + 1}", category=item.category, observable_target=bind(item.observable_target),
                                expected_change=item.expected_change, normalized_statement=item.normalized_statement,
                                assertion_provenance=AssertionProvenance.RULE, provenance_ref=TEMPLATE_PROVENANCE_REF)
            for index, item in enumerate(template.consequences))
        mechanism = Mechanism(drivers=components["drivers"], channels=components["channels"], domains=components["domains"],
                              consequences=consequences)
        subject = ThemeSubject(normalized_subject=subject_template.normalized_subject, typed_reference=bind(subject_template.typed_reference))
        scope = tuple(ScopeToken(dimension=item.dimension, value=normalize_text(bind(item.value))) for item in rule.scope_template)
        invalidation = tuple(InvalidationCondition(condition_key=item.condition_key, normalized_statement=item.normalized_statement,
                                                   observable_target=bind(item.observable_target) if item.observable_target else "",
                                                   expected_change=item.expected_change) for item in rule.invalidation_template)
        limitations = tuple(Limitation(category=item.category, normalized_statement=item.normalized_statement) for item in rule.limitations_template)
    except DiscoveryError as exc:
        return None, (f"{exc.code}:{exc.detail}",)
    except ValueError as exc:
        return None, (f"TEMPLATE_REJECTED:{getattr(exc, 'code', type(exc).__name__)}",)
    attachments: Dict[str, EvidenceAttachment] = {}
    for record in records:                                                 # input_id 順（決定論）。重複 ref は畳む
        if record.input_id in attachments:
            continue
        attachment, problem = _attachment(record, rule, run_created_at)
        if attachment is None:
            diagnostics.append(problem)
            continue
        attachments[record.input_id] = attachment
    if not attachments:
        diagnostics.append("NO_EVIDENCE_REFS")
        return None, tuple(diagnostics)
    try:
        candidate = ThemeCandidateProposal.build(
            subject=subject, mechanism=mechanism, certainty_class=FIXED_CERTAINTY, scope=scope, invalidation_conditions=invalidation,
            limitations=limitations, evidence_refs=tuple(attachments[k] for k in sorted(attachments)), provenance=_provenance(rule, pins),
            created_at=run_created_at)
    except ValueError as exc:
        return None, tuple(diagnostics) + (f"CANDIDATE_BUILD_FAILED:{getattr(exc, 'code', type(exc).__name__)}",)
    return candidate, tuple(diagnostics)


def _build_evidence_candidate(rule: DiscoveryRule, record: DiscoveryInputRecord, *, run_created_at: datetime, pins: str
                              ) -> Tuple[Optional[EvidenceCandidateProposal], str]:
    if record.evidence_time_quality is EvidenceTimeQuality.MISSING and rule.proposed_role is not EvidenceRole.CONTEXT:
        return None, f"ROLE_REQUIRES_EVIDENCE_TIME:{record.input_id}"
    try:
        proposal = EvidenceCandidateProposal.build(
            evidence_kind=record.evidence_kind, ref_id=record.input_id, source_origin=record.source_origin, evidence_time=record.evidence_time,
            evidence_time_basis=record.evidence_time_basis, evidence_time_quality=record.evidence_time_quality,
            evidence_date=record.evidence_date, proposed_role=rule.proposed_role, reason=evidence_reason(rule.proposed_role, record.evidence_kind.value),
            target_root_id=rule.target_root_id, provenance=_provenance(rule, pins), created_at=run_created_at)
    except ValueError as exc:
        return None, f"CANDIDATE_BUILD_FAILED:{record.input_id}:{getattr(exc, 'code', type(exc).__name__)}"
    return proposal, ""


# ---------------------------------------------------------------- run


def discover(inputs: Sequence[object], *, taxonomy: TaxonomySnapshot, entity_catalog: EntityCatalogSnapshot, ruleset: DiscoveryRuleset,
             cutoff: datetime, run_created_at: datetime, existing_proposals: Sequence[object] = (),
             existing_decisions: Sequence[object] = (), theme_resolutions: Sequence[object] = (),
             include_dedup: bool = True) -> DiscoveryResult:
    cutoff_utc = _aware(cutoff, "cutoff")
    created = _aware(run_created_at, "run_created_at")
    if created < cutoff_utc:
        raise DiscoveryError("INVALID_RUN_TIME", "run_created_at must not be earlier than cutoff")
    if not isinstance(taxonomy, TaxonomySnapshot) or not isinstance(entity_catalog, EntityCatalogSnapshot) or not isinstance(ruleset, DiscoveryRuleset):
        raise DiscoveryError("INVALID_TYPE", "taxonomy / entity_catalog / ruleset must be pinned snapshots")
    for name, snapshot in (("taxonomy", taxonomy), ("entity_catalog", entity_catalog), ("ruleset", ruleset)):
        if snapshot.published_at > cutoff_utc:
            raise DiscoveryError("FUTURE_KNOWLEDGE", f"{name} published after cutoff")
    check_ruleset_pins(ruleset, taxonomy, entity_catalog)
    pins = _pins_reason(taxonomy, entity_catalog, ruleset)

    adapted = adapt_inputs(inputs, taxonomy=taxonomy, entity_catalog=entity_catalog, cutoff=cutoff_utc)
    existing_by_id = {p.proposal_id: p for p in existing_proposals}
    generated: Dict[str, object] = {}
    emitters: Dict[str, List[str]] = {}
    evaluations: List[RuleEvaluation] = []
    hits_report: List[RuleHit] = []
    diagnostics: List[str] = list(adapted.diagnostics)

    for rule in ruleset.rules:
        if rule.status is not RuleStatus.ACTIVE:
            evaluations.append(RuleEvaluation(rule_id=rule.rule_id, rule_version=rule.rule_version, status=rule.status,
                                              output_type=rule.output_type, candidate_input_ids=(), matched_input_ids=(), l1_hit_count=0,
                                              l2_hit_count=0, negative_exclusions=(), aggregate_satisfied=False, emitted_proposal_ids=(),
                                              converged_proposal_ids=(), diagnostics=("RULE_DEPRECATED",)))
            continue
        candidates = [r for r in adapted.records if r.input_kind in rule.input_kinds]
        excluded: List[str] = []
        matched: List[Tuple[DiscoveryInputRecord, Tuple[PredicateHit, ...], Tuple[PredicateHit, ...]]] = []
        for record in candidates:
            if any(evaluate_predicate(neg, record).matched for neg in rule.negative_predicates):
                excluded.append(record.input_id)
                continue
            outcome = evaluate_predicate(rule.predicate, record)
            if outcome.matched:
                matched.append((record, outcome.l1_hits, outcome.l2_hits))
        rule_diagnostics: List[str] = [f"EXCLUDED_BY_NEGATIVE_PREDICATE:{i}" for i in excluded]
        matched_records = [m[0] for m in matched]
        for record, l1, l2 in matched:
            hits_report.append(RuleHit(rule_id=rule.rule_id, input_id=record.input_id, l1_hits=l1, l2_hits=l2))
        aggregate_ok, aggregate_diag = evaluate_aggregate(rule.aggregate_predicates, matched_records)
        rule_diagnostics.extend(aggregate_diag)
        emitted: List[str] = []
        if matched and aggregate_ok:
            if rule.output_type is RuleOutputType.EVIDENCE_CANDIDATE:
                for record, _l1, _l2 in matched:
                    proposal, problem = _build_evidence_candidate(rule, record, run_created_at=created, pins=pins)
                    if proposal is None:
                        rule_diagnostics.append(problem)
                        continue
                    emitted.append(proposal.proposal_id)
                    generated.setdefault(proposal.proposal_id, proposal)
                    emitters.setdefault(proposal.proposal_id, []).append(rule.rule_id)
            else:
                if not any(l1 for _r, l1, _l2 in matched):
                    rule_diagnostics.append("THEME_CANDIDATE_REQUIRES_L1_HIT")
                else:
                    proposal, problems = _build_theme_candidate(rule, matched_records, entity_catalog=entity_catalog, run_created_at=created,
                                                                pins=pins)
                    rule_diagnostics.extend(problems)
                    if proposal is not None:
                        emitted.append(proposal.proposal_id)
                        generated.setdefault(proposal.proposal_id, proposal)
                        emitters.setdefault(proposal.proposal_id, []).append(rule.rule_id)
                        origins = {r.source_origin.origin_key for r in matched_records if r.source_origin.is_known}
                        rule_diagnostics.append(f"EVIDENCE_REFS:{len(proposal.evidence_refs)};ORIGIN_KEYS:{len(origins)}"
                                                ";NOT_AN_INDEPENDENCE_CLAIM")
        evaluations.append(RuleEvaluation(
            rule_id=rule.rule_id, rule_version=rule.rule_version, status=rule.status, output_type=rule.output_type,
            candidate_input_ids=tuple(r.input_id for r in candidates), matched_input_ids=tuple(r.input_id for r in matched_records),
            l1_hit_count=sum(len(l1) for _r, l1, _l2 in matched), l2_hit_count=sum(len(l2) for _r, _l1, l2 in matched),
            negative_exclusions=tuple(excluded), aggregate_satisfied=aggregate_ok, emitted_proposal_ids=tuple(sorted(set(emitted))),
            converged_proposal_ids=(), diagnostics=tuple(rule_diagnostics)))

    # 収束（同 id を複数 rule が出した）を report に反映
    converged = {pid for pid, rules in emitters.items() if len(set(rules)) > 1}
    evaluations = [RuleEvaluation(**{**e.__dict__, "converged_proposal_ids": tuple(sorted(p for p in e.emitted_proposal_ids if p in converged))})
                   for e in evaluations]

    # suppression: 既存 id は返さない。decision 状態は診断のみ
    suppressed: List[str] = []
    fresh: Dict[str, object] = {}
    for pid in sorted(generated):
        if pid in existing_by_id:
            suppressed.append(pid)
            status = derive_proposal_status(existing_by_id[pid], existing_decisions)
            diagnostics.append(f"EXISTING_{status.value}_PROPOSAL:{pid}")
        else:
            fresh[pid] = generated[pid]

    # dedup（B3 exact detector。NOT_DUPLICATE suppression は B3 側）
    review_ids: List[str] = []
    if include_dedup:
        new_candidates = [p for p in fresh.values() if isinstance(p, ThemeCandidateProposal)]
        pool = tuple(existing_proposals) + tuple(new_candidates)
        for candidate in sorted(new_candidates, key=lambda p: p.proposal_id):
            for review in detect_exact_duplicates(candidate, resolutions=tuple(theme_resolutions), proposals=pool,
                                                  decisions=tuple(existing_decisions), created_at=created,
                                                  dedup_model_version=DEDUP_MODEL_VERSION):
                if review.proposal_id in existing_by_id:
                    suppressed.append(review.proposal_id)
                    continue
                if review.proposal_id not in fresh:
                    fresh[review.proposal_id] = review
                    review_ids.append(review.proposal_id)

    order = {ProposalType.EVIDENCE_CANDIDATE: 0, ProposalType.THEME_CANDIDATE: 1, ProposalType.DEDUP_REVIEW: 2}
    proposals = tuple(sorted(fresh.values(), key=lambda p: (order[p.proposal_type], p.proposal_id)))
    report = DiscoveryRunReport(
        cutoff=cutoff_utc, run_created_at=created, taxonomy_version=taxonomy.taxonomy_version, catalog_version=entity_catalog.catalog_version,
        ruleset_version=ruleset.ruleset_version, input_count=len(inputs), normalized_input_count=len(adapted.records),
        excluded_inputs=adapted.excluded, origin_groups=adapted.origin_groups, rule_evaluations=tuple(evaluations),
        rule_hits=tuple(sorted(hits_report, key=lambda h: (h.rule_id, h.input_id))), proposal_ids=tuple(p.proposal_id for p in proposals),
        suppressed_existing_ids=tuple(sorted(set(suppressed))), dedup_review_ids=tuple(sorted(review_ids)),
        diagnostics=tuple(sorted(set(diagnostics))))
    return DiscoveryResult(proposals=proposals, run_report=report)


__all__ = ["discover", "evidence_reason", "EVIDENCE_REASON_TEMPLATE"]
