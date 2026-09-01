"""Compass generation pipeline（Phase 3-C §3 / §29 / §30 / §31）。

Morning Context Snapshot
  → Evidence Package（決定論的）
  → Outlook（決定論的）
  → Narrative Plan（決定論的）
  → generator（deterministic / LLM boundary / fake）
  → Quality gate（全validator）
  → repair（REJECTED claimを落とし、必須roleが欠ければ決定論的生成で補う）
  → one-liner
  → CompassDraft（content-addressed draft_id: 同じ入力 → 同じID）

generatorが利用不可（LLM provider未設定等）なら決定論的生成へフォールバックし、
`generator_fallback` に記録する（例外で止めない・secretを要求しない）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..context.snapshot import CompassContextSnapshot
from ..facts.model import Fact
from .config import CompassConfig
from .evidence_package import EvidencePackage, build_evidence_package
from .generator import (
    DETERMINISTIC, DeterministicNarrativeGenerator, GeneratorUnavailable, NarrativeGenerator,
)
from .model import (
    ClaimRole, CompassClaim, CompassDraft, CompassOutlook, QualityVerdict, SEVERITY_ERROR,
    SEVERITY_WARNING, ValidationIssue, make_draft_id,
)
from .narrative_plan import NarrativePlan, build_narrative_plan
from .one_liner import build_one_liner, validate_one_liner
from .outlook import Implication, build_outlook
from .quality_gate import GateResult, run_quality_gate

PIPELINE_RULE_VERSION = "compass_pipeline:1.0.0"
VALIDATOR = "pipeline"
FALLBACK_OUTPUT_REJECTED = "generator_output_rejected"
ABSTAIN_ONE_LINER = "one_liner_unavailable"   # 根拠付きOUTLOOK/HEADLINEが残らず要約不可

#: 必須role（欠ければ決定論的生成で補う）
MANDATORY_ROLES: Tuple[ClaimRole, ...] = (
    ClaimRole.HEADLINE, ClaimRole.WHY, ClaimRole.OUTLOOK, ClaimRole.RISK, ClaimRole.COVERAGE,
)


@dataclass(frozen=True, kw_only=True)
class PipelineResult:
    """中間生成物を含む結果（pilot・テストが検査する）。"""

    package: EvidencePackage
    outlook: CompassOutlook
    implications: Mapping[str, Implication]
    plan: NarrativePlan
    generator_name: str
    raw_claims: Tuple[CompassClaim, ...]
    first_gate: GateResult
    repaired_claim_ids: Tuple[str, ...]
    gate: GateResult
    draft: CompassDraft
    generator_fallback: str = ""
    generator_report: Dict[str, object] = field(default_factory=dict)


def _generate(generator: Optional[NarrativeGenerator], package: EvidencePackage,
              plan: NarrativePlan, outlook: CompassOutlook,
              implications: Mapping[str, Implication]
              ) -> Tuple[Sequence[CompassClaim], str, str]:
    """(claims, generator_name, fallback_reason)。利用不可なら決定論的へ。"""
    fallback = DeterministicNarrativeGenerator()
    if generator is None:
        return fallback.generate(package, plan, outlook, implications), fallback.name, ""
    try:
        claims = generator.generate(package, plan, outlook, implications)
    except GeneratorUnavailable as exc:
        reason = str(exc) or "generator_unavailable"
        return (fallback.generate(package, plan, outlook, implications), fallback.name,
                reason)
    return claims, getattr(generator, "name", "unknown"), ""


def _repair(gate: GateResult, package: EvidencePackage, plan: NarrativePlan,
            outlook: CompassOutlook, implications: Mapping[str, Implication],
            generator_name: str) -> Tuple[List[CompassClaim], List[str]]:
    """REJECTED claimは残す（provenance）が、必須roleが欠ければ決定論的に補う。

    決定論的生成物そのものが欠けている場合は補わない（同じ結果になる）。
    """
    kept = list(gate.claims)
    added: List[str] = []
    if generator_name == DETERMINISTIC:
        return kept, added
    missing = [r for r in MANDATORY_ROLES if not gate.grounded_for(r)]
    if not missing:
        return kept, added
    backfill = DeterministicNarrativeGenerator().generate(package, plan, outlook,
                                                          implications)
    existing = {c.claim_id for c in kept}
    for claim in backfill:
        if claim.claim_role in missing and claim.claim_id not in existing:
            kept.append(claim)
            added.append(claim.claim_id)
    return kept, added


def run_pipeline(snapshot: CompassContextSnapshot, facts: Iterable[Fact], *,
                 generator: Optional[NarrativeGenerator] = None,
                 config: Optional[CompassConfig] = None,
                 now: Optional[datetime] = None) -> PipelineResult:
    cfg = config or CompassConfig()
    facts = tuple(facts)
    package = build_evidence_package(snapshot, facts, budget=cfg.evidence_budget)
    outlook, implications = build_outlook(package, horizon=cfg.outlook_horizon,
                                          near_event_days=cfg.near_event_days)
    plan = build_narrative_plan(package, outlook, implications,
                                min_counter=cfg.min_counter_contexts)

    raw, gen_name, fallback = _generate(generator, package, plan, outlook, implications)
    raw = tuple(raw)
    first_gate = run_quality_gate(raw, package, plan, outlook, cfg)
    issues: List[ValidationIssue] = []
    if first_gate.verdict is QualityVerdict.REJECTED and gen_name != DETERMINISTIC:
        # 生成物の大半が根拠不整合 → 生成物を**丸ごと捨てて**決定論的生成へ（§29）
        issues.append(ValidationIssue(
            validator=VALIDATOR, code=FALLBACK_OUTPUT_REJECTED,
            message=f"{gen_name} の生成物 {len(raw)} 件中 {len(first_gate.rejected)} 件が"
                    "REJECTEDのため破棄した", severity=SEVERITY_WARNING))
        fallback = FALLBACK_OUTPUT_REJECTED
        gen_name = DETERMINISTIC
        repaired = list(DeterministicNarrativeGenerator().generate(
            package, plan, outlook, implications))
        added = [c.claim_id for c in repaired]
    else:
        repaired, added = _repair(first_gate, package, plan, outlook, implications,
                                  gen_name)
    gate = first_gate if not added else run_quality_gate(repaired, package, plan, outlook,
                                                         cfg)

    verdict = gate.verdict
    abstain_reason = gate.abstain_reason
    one_liner = ""
    issues += list(gate.issues)
    if verdict in (QualityVerdict.VALID, QualityVerdict.VALID_WITH_WARNINGS):
        one_liner = build_one_liner(gate.claims, cfg)
        ol_issues = validate_one_liner(one_liner, cfg)
        if any(i.severity == SEVERITY_ERROR for i in ol_issues) or not one_liner:
            one_liner = ""
            verdict = QualityVerdict.ABSTAINED
            abstain_reason = ABSTAIN_ONE_LINER
        issues += ol_issues

    ordered = sorted(gate.claims, key=lambda c: (c.order, c.claim_id))
    draft = CompassDraft(
        draft_id=make_draft_id(session_date=package.session_date,
                               package_id=package.package_id, plan_id=plan.plan_id,
                               generator=gen_name, claim_ids=[c.claim_id for c in ordered],
                               verdict=verdict, one_liner=one_liner),
        session_date=package.session_date,
        reference_session=package.reference_session,
        package_id=package.package_id, plan_id=plan.plan_id,
        generator=gen_name, verdict=verdict, claims=tuple(ordered),
        outlook=outlook if plan.can_generate else None,
        one_liner=one_liner, issues=tuple(issues),
        evidence_fact_ids=package.fact_ids, evidence_context_ids=package.context_ids,
        missing_dimensions=package.unreliable_dimensions,
        abstain_reason=abstain_reason if verdict is QualityVerdict.ABSTAINED else "",
        generator_fallback=fallback, generated_at=now or datetime.now(timezone.utc))
    report = dict(getattr(generator, "last_report", {}) or {}) if generator else {}
    return PipelineResult(package=package, outlook=outlook, implications=implications,
                          plan=plan, generator_name=gen_name, raw_claims=raw,
                          first_gate=first_gate, repaired_claim_ids=tuple(added),
                          gate=gate, draft=draft, generator_fallback=fallback,
                          generator_report=report)


def generate_compass(snapshot: CompassContextSnapshot, facts: Iterable[Fact], *,
                     generator: Optional[NarrativeGenerator] = None,
                     config: Optional[CompassConfig] = None,
                     now: Optional[datetime] = None) -> CompassDraft:
    """snapshot + facts → CompassDraft（§30）。"""
    return run_pipeline(snapshot, facts, generator=generator, config=config, now=now).draft
