"""評価オーケストレーション（Phase 1-E）。レコード種別ごとに次元を束ねgateへ渡す。

- 決定論: 基準時刻（reference_time）と入力を全て引数で受ける。LLM・乱数なし。
- dependency propagation: 上流EvidenceがREJECTでも下流を**自動削除しない**。
  品質警告（dependency_rejected等）として伝播し、gateがLIMITED_USE等へ落とす。
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional, Sequence, Tuple

from ..core.ids import new_id
from ..core.types import Horizon, SourceTier, VerificationState
from ..evidence.invariants import derive_verification
from ..evidence.model import AnalysisStatement, EvidenceLink, EvidenceRelation, FactStatement, ForecastStatement
from ..market.model import Observation
from ..sources.model import SourceDocument
from . import dimensions as dims
from .gate import collect_issues, decide
from .model import (
    DimensionResult,
    DimensionStatus,
    EvidenceAssessment,
    GateDecision,
    QADimension,
    SourceInfo,
)
from .policy import TrustPolicy


def load_source_info(catalog_feed: Mapping[str, object]) -> SourceInfo:
    """source_feeds.yaml v3のfeedエントリ1件 → SourceInfo（I/Oは呼び出し側）。"""
    endpoint = catalog_feed.get("endpoint") or {}
    health = catalog_feed.get("current_health") or {}
    return SourceInfo(
        source_id=str(catalog_feed["id"]),
        tier=SourceTier(int(catalog_feed.get("tier", 3))),
        investment_value=str(catalog_feed.get("investment_value", "MEDIUM")),
        health_state=str(health.get("state", "unverified")),
        usage_status=str(endpoint.get("usage_status", "public_feed")),
        duplicate_group=str(catalog_feed.get("duplicate_group", "") or ""),
    )


def _build(
    record_id: str,
    record_type: str,
    dimension_results: Sequence[DimensionResult],
    *,
    policy: TrustPolicy,
    reference_time: datetime,
    horizon: Optional[Horizon],
) -> EvidenceAssessment:
    decision, reasons = decide(dimension_results)
    return EvidenceAssessment(
        assessment_id=new_id("qa", reference_time),
        record_id=record_id,
        record_type=record_type,
        assessed_at=reference_time,
        policy_name=policy.name,
        policy_version=policy.version,
        horizon=horizon,
        dimensions=tuple(dimension_results),
        issues=collect_issues(dimension_results),
        decision=decision,
        decision_reasons=reasons,
    )


# ---------------------------------------------------------------- SourceDocument


def assess_source_document(
    doc: SourceDocument,
    *,
    source_info: SourceInfo,
    policy: TrustPolicy,
    reference_time: datetime,
    horizon: Optional[Horizon] = None,
    raw_repository=None,
    normalization_events: Sequence = (),
    existing_documents: Sequence[SourceDocument] = (),
    retracted_ids: frozenset = frozenset(),
) -> EvidenceAssessment:
    results = [
        dims.eval_document_provenance(doc),
        dims.eval_source_quality(source_info),
        dims.eval_source_health(source_info, policy),
        dims.eval_freshness(doc.published_at, policy, reference_time, horizon),
        dims.eval_date_quality(doc, policy),
        dims.eval_content_integrity(doc, raw_repository),
        dims.eval_revision(doc, existing_documents, policy, retracted_ids),
        dims.eval_duplication(doc, existing_documents),
        dims.eval_normalization_quality(doc, normalization_events),
        dims.eval_usage_rights(source_info, policy),
    ]
    return _build(doc.source_document_id, "source_document", results,
                  policy=policy, reference_time=reference_time, horizon=horizon)


# ---------------------------------------------------------------- Observation


def assess_observation(
    obs: Observation,
    *,
    source_info: SourceInfo,
    policy: TrustPolicy,
    reference_time: datetime,
    horizon: Optional[Horizon] = None,
    input_assessments: Sequence[EvidenceAssessment] = (),
) -> EvidenceAssessment:
    results = [
        dims.eval_observation_provenance(obs),
        dims.eval_source_quality(source_info),
        dims.eval_source_health(source_info, policy),
        dims.eval_freshness(obs.as_of, policy, reference_time, horizon),
        dims.eval_observation_validity(obs, policy, reference_time),
        dims.eval_usage_rights(source_info, policy),
    ]
    if obs.kind.value == "derived":
        results.append(_dependency_dimension(
            tuple(a.decision for a in input_assessments), policy,
            expected=len(obs.inputs)))
    return _build(obs.observation_id, "observation", results,
                  policy=policy, reference_time=reference_time, horizon=horizon)


# ---------------------------------------------------------------- 依存伝播（共通）


def _dependency_dimension(
    upstream_decisions: Tuple[GateDecision, ...],
    policy: TrustPolicy,
    *,
    expected: int,
) -> DimensionResult:
    """上流EvidenceのGate結果を下流へ伝播する（自動削除はしない）。"""
    codes = []
    if expected and len(upstream_decisions) < expected:
        codes.append("dependency_unassessed")
    if any(d is GateDecision.REJECT for d in upstream_decisions):
        codes.append("dependency_rejected")
        return DimensionResult(
            dimension=QADimension.SUPPORT, status=policy.dependency_rejected_status,
            reason_codes=tuple(codes),
            detail="上流REJECT。下流は削除せず用途制限（policy化）")
    if any(d is GateDecision.LIMITED_USE for d in upstream_decisions):
        codes.append("dependency_limited")
        return DimensionResult(dimension=QADimension.SUPPORT,
                               status=DimensionStatus.WARN, reason_codes=tuple(codes))
    if codes:  # unassessedのみ
        return DimensionResult(dimension=QADimension.SUPPORT,
                               status=DimensionStatus.WARN, reason_codes=tuple(codes))
    return DimensionResult(dimension=QADimension.SUPPORT, status=DimensionStatus.PASS)


# ---------------------------------------------------------------- Fact


def assess_fact(
    fact: FactStatement,
    links: Sequence[EvidenceLink],
    *,
    policy: TrustPolicy,
    reference_time: datetime,
    horizon: Optional[Horizon] = None,
    evidence_assessments: Mapping[str, EvidenceAssessment] = {},
    evidence_source_info: Mapping[str, SourceInfo] = {},
) -> EvidenceAssessment:
    """FactのQA。UNSUPPORTED→REJECT（AI生成の自信は通過理由にならない）。

    corroboration: SUPPORTS evidenceの**独立source数**を数える
    （同一source・同一duplicate_groupは1と数える——転載10件≠独立10source）。
    """
    state = derive_verification(fact, links)
    own = [l for l in links if l.claim_id == fact.statement_id]
    supports = [l for l in own if l.relation is EvidenceRelation.SUPPORTS]

    # SUPPORT次元
    if state is VerificationState.UNSUPPORTED or not supports:
        support_result = DimensionResult(
            dimension=QADimension.SUPPORT, status=DimensionStatus.FAIL,
            reason_codes=("unsupported_fact",),
            detail="SUPPORTSリンクなし（P1-A invariant）")
    else:
        rejected = [
            l.evidence_id for l in supports
            if evidence_assessments.get(l.evidence_id) is not None
            and evidence_assessments[l.evidence_id].decision is GateDecision.REJECT
        ]
        usable = [l for l in supports if l.evidence_id not in set(rejected)]
        if not usable:
            support_result = DimensionResult(
                dimension=QADimension.SUPPORT, status=policy.dependency_rejected_status,
                reason_codes=("weak_supporting_evidence", "dependency_rejected"),
                detail="支持Evidenceが全てREJECT")
        else:
            support_result = DimensionResult(
                dimension=QADimension.SUPPORT, status=DimensionStatus.PASS,
                reason_codes=("supported",))

    # CONFLICT次元（矛盾は自動FALSEにしない。両論保持のうえ用途制限）
    if state is VerificationState.CONFLICTING:
        has_support = bool(supports)
        conflict_result = DimensionResult(
            dimension=QADimension.CONFLICT, status=policy.conflicting_status,
            reason_codes=("conflicting_evidence",) if has_support else ("contradiction_only",),
            detail="矛盾Evidence併存（自動でFALSE判定しない）")
    elif state is VerificationState.RETRACTED:
        conflict_result = DimensionResult(
            dimension=QADimension.CONFLICT, status=DimensionStatus.FAIL,
            reason_codes=("retracted",), detail="明示的撤回（推測ではない）")
    else:
        conflict_result = DimensionResult(dimension=QADimension.CONFLICT,
                                          status=DimensionStatus.PASS)

    # DUPLICATION次元 = corroborationの独立性
    independent = set()
    for l in supports:
        info = evidence_source_info.get(l.evidence_id)
        if info is None:
            independent.add(f"unknown:{l.evidence_id}")
        else:
            independent.add(info.duplicate_group or info.source_id)
    if len(supports) >= 2 and len(independent) == 1:
        dup_result = DimensionResult(
            dimension=QADimension.DUPLICATION, status=DimensionStatus.WARN,
            reason_codes=("syndicated_duplicate", "single_source_only"),
            detail=f"支持{len(supports)}件だが独立source 1系統のみ")
    elif len(independent) >= 2:
        dup_result = DimensionResult(
            dimension=QADimension.DUPLICATION, status=DimensionStatus.PASS,
            reason_codes=("corroborated_independent",),
            detail=f"独立{len(independent)}系統が支持")
    elif supports:
        dup_result = DimensionResult(
            dimension=QADimension.DUPLICATION, status=DimensionStatus.PASS,
            reason_codes=("single_source_only",))
    else:
        dup_result = DimensionResult(dimension=QADimension.DUPLICATION,
                                     status=DimensionStatus.NOT_APPLICABLE)

    results = [
        support_result,
        conflict_result,
        dup_result,
        dims.eval_freshness(fact.event_time, policy, reference_time, horizon),
    ]
    return _build(fact.statement_id, "fact", results,
                  policy=policy, reference_time=reference_time, horizon=horizon)


# ---------------------------------------------------------------- Analysis / Forecast


def assess_analysis(
    analysis: AnalysisStatement,
    *,
    policy: TrustPolicy,
    reference_time: datetime,
    horizon: Optional[Horizon] = None,
    input_assessments: Sequence[EvidenceAssessment] = (),
) -> EvidenceAssessment:
    """AnalysisのQA。構造（inputs/rule_id/agent）＋上流Gate結果の伝播。"""
    if not analysis.inputs or not analysis.rule_id or not analysis.agent:
        prov = DimensionResult(
            dimension=QADimension.PROVENANCE, status=DimensionStatus.FAIL,
            reason_codes=("missing_supporting_evidence_ref",))
    else:
        prov = DimensionResult(dimension=QADimension.PROVENANCE,
                               status=DimensionStatus.PASS)
    results = [
        prov,
        _dependency_dimension(tuple(a.decision for a in input_assessments), policy,
                              expected=len(analysis.inputs)),
    ]
    return _build(analysis.statement_id, "analysis", results,
                  policy=policy, reference_time=reference_time, horizon=horizon)


def assess_forecast(
    forecast: ForecastStatement,
    *,
    policy: TrustPolicy,
    reference_time: datetime,
    supporting_assessments: Sequence[EvidenceAssessment] = (),
) -> EvidenceAssessment:
    """ForecastのQA。P1-A invariant（型で保証済み）＋支持EvidenceのGate結果。

    Prediction Journal（的中評価）はPhase 5——ここでは実装しない。
    """
    meta = forecast.forecast
    results = [
        DimensionResult(dimension=QADimension.PROVENANCE, status=DimensionStatus.PASS,
                        detail=f"supporting={len(meta.supporting_evidence)} "
                               f"invalidation={len(meta.invalidation_conditions)}"),
        _dependency_dimension(
            tuple(a.decision for a in supporting_assessments), policy,
            expected=len(meta.supporting_evidence)),
    ]
    return _build(forecast.statement_id, "forecast", results,
                  policy=policy, reference_time=reference_time, horizon=meta.horizon)
