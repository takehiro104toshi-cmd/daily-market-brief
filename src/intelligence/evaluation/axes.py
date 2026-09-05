"""Six frozen axes（Phase 3.9.2 Q15–Q20）。決定的・config 由来・source text を読まない。

state は常に LOW / MEDIUM / HIGH。applicability は score 用の別次元で、**構造的不可能** のときだけ
NOT_APPLICABLE にする（pattern identity が試験そのものを成立させない場合。証拠不足は NOT_APPLICABLE ではない）。
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .config import (
    A_CONSISTENCY,
    A_CROSS,
    A_NOVELTY,
    A_QUALITY,
    A_STRENGTH,
    A_TIME,
    HIGH,
    LOW,
    MEDIUM,
    EvaluationPolicy,
)
from .contradiction import ContradictionIndex, document_direction_signals, own_direction, outlook_part
from .models import APPLICABLE, NOT_APPLICABLE, AxisResult

UNKNOWN = "UNKNOWN"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cells(structures: Sequence[Mapping[str, Any]], dimensions: Sequence[str]) -> Counter:
    """UNKNOWN を含む document は当該 signature へ寄与しない（UNKNOWN は regime ではない）。"""
    out: Counter = Counter()
    for s in structures:
        state = dict(s.get("market_state") or {})
        labels = [str(state.get(d, UNKNOWN)) for d in dimensions]
        if UNKNOWN in labels:
            continue
        out["|".join(labels)] += 1
    return out


# ------------------------------------------------------------------ Q15
def evidence_strength(record: Mapping[str, Any], policy: EvaluationPolicy) -> AxisResult:
    support = _int(record.get("eligible_support"))
    state = LOW if support <= policy.strength_low_max else (
        MEDIUM if support <= policy.strength_medium_max else HIGH)
    ptype = str(record.get("pattern_type", ""))
    if ptype in policy.strength_not_ranked_types:
        return AxisResult(A_STRENGTH, state, NOT_APPLICABLE,
                          "SUPPORT_NOT_RANKED: pattern identity embeds regime and content, so recurrence is "
                          "structurally near-impossible", {"eligible_support": support, "support_ranked": False})
    return AxisResult(A_STRENGTH, state, APPLICABLE, "", {"eligible_support": support, "support_ranked": True})


def relative_support_share(record: Mapping[str, Any], eligible_dates: Sequence[str],
                           policy: EvaluationPolicy) -> Tuple[Optional[float], str, int]:
    """TIE_BREAKER_ONLY。denominator が閾値未満なら NOT_APPLICABLE（順序付けにも使わない）。
    Evidence Strength の LOW/MEDIUM/HIGH は絶対に変えない。"""
    first_seen = str(record.get("first_seen") or "")
    denominator = sum(1 for d in eligible_dates if d >= first_seen) if first_seen else 0
    if denominator < policy.relative_share_min_denominator:
        return None, NOT_APPLICABLE, denominator
    share = _int(record.get("support_count")) / denominator
    return round(share, 4), APPLICABLE, denominator


# ------------------------------------------------------------------ Q16
def time_stability(record: Mapping[str, Any], structures: Sequence[Mapping[str, Any]],
                   policy: EvaluationPolicy) -> AxisResult:
    span = _int(record.get("span_days"))
    months = len({str(s.get("document_date", ""))[:7] for s in structures if s.get("document_date")})
    metrics = {"span_days": span, "distinct_calendar_months": months,
               "support_per_90d_window": round(_int(record.get("eligible_support")) /
                                               max(1, -(-max(span, 1) // 90)), 3)}   # 将来診断のみ
    if span >= policy.time_high_span_days and months >= policy.time_high_months:
        return AxisResult(A_TIME, HIGH, APPLICABLE, "SPAN_AND_MONTHS_HIGH", metrics)
    if span >= policy.time_medium_span_days and months >= policy.time_medium_months:
        return AxisResult(A_TIME, MEDIUM, APPLICABLE, "SPAN_AND_MONTHS_MEDIUM", metrics)
    return AxisResult(A_TIME, LOW, APPLICABLE,
                      "SHORT_SPAN" if span < policy.time_medium_span_days else "SINGLE_CALENDAR_MONTH", metrics)


# ------------------------------------------------------------------ Q17
def cross_regime(record: Mapping[str, Any], structures: Sequence[Mapping[str, Any]],
                 policy: EvaluationPolicy) -> Tuple[AxisResult, Dict[str, Any]]:
    core = _cells(structures, policy.cross_core_dimensions)
    confirm = _cells(structures, policy.cross_confirm_dimensions)
    distinct = len(core)
    confirmed = sum(1 for v in core.values() if v >= 2)
    support = _int(record.get("eligible_support"))
    span = _int(record.get("span_days"))
    excluded = len(structures) - sum(core.values())
    metrics = {"distinct_2d_cells": distinct, "confirmed_2d_cells": confirmed,
               "documents_excluded_unknown": excluded, "documents_counted": sum(core.values())}
    #: 3D は secondary confirmation。state を上げる力を持たない（記録のみ）。
    confirmation = {"distinct_3d_cells": len(confirm), "confirmed_3d_cells": sum(1 for v in confirm.values() if v >= 2),
                    "documents_counted": sum(confirm.values()), "role": "SECONDARY_CONFIRMATION_ONLY"}
    ptype = str(record.get("pattern_type", ""))
    if ptype in policy.cross_not_applicable_types:
        return (AxisResult(A_CROSS, LOW, NOT_APPLICABLE,
                           "REGIME_BEARING_IDENTITY: supporting documents share the pattern's regime labels by "
                           "identity, so regime diversity cannot be demonstrated", metrics), confirmation)
    if (distinct >= policy.cross_high_cells and support >= policy.cross_high_support
            and span >= policy.cross_high_span_days and confirmed >= policy.cross_high_confirmed_cells):
        return AxisResult(A_CROSS, HIGH, APPLICABLE, "GATED_HIGH", metrics), confirmation
    if distinct == policy.cross_medium_cells:
        return AxisResult(A_CROSS, MEDIUM, APPLICABLE, "TWO_CELLS", metrics), confirmation
    return AxisResult(A_CROSS, LOW, APPLICABLE,
                      "SINGLE_OR_NO_CELL" if distinct <= 1 else "HIGH_GATE_NOT_MET", metrics), confirmation


# ------------------------------------------------------------------ Q18
def evidence_consistency(record: Mapping[str, Any], structures: Sequence[Mapping[str, Any]],
                         index: ContradictionIndex, dna_conflicts: int, policy: EvaluationPolicy,
                         min_documents_each_side: int = 2) -> AxisResult:
    pid = str(record["pattern_id"])
    components = dict(record.get("components") or {})
    direction = own_direction(components)
    doc_dirs = [str((s.get("outlook_summary") or {}).get("primary_direction", "NOT_STATED")) for s in structures]
    signals = document_direction_signals(doc_dirs, policy, min_documents_each_side)
    support = _int(record.get("eligible_support"))
    committed = direction in policy.consistency_committed_directions
    metrics = {"identity_direction": direction or "NONE",
               "direction_class": "DIRECTIONAL" if committed else (
                   "CONDITIONAL_DIRECTIONAL" if direction in policy.consistency_soft_directions
                   else "NON_DIRECTIONAL"),
               "narrow_sibling_contradiction": pid in index.narrow_sibling,
               "narrow_sibling_repeated": pid in index.narrow_sibling_repeated,
               "dna_conflicts": dna_conflicts, "eligible_support": support, **signals}
    if dna_conflicts > 0:
        return AxisResult(A_CONSISTENCY, LOW, APPLICABLE, "DNA_CONFLICT", metrics)
    if pid in index.narrow_sibling:
        return AxisResult(A_CONSISTENCY, LOW, APPLICABLE, "NARROW_SIBLING_CONTRADICTION", metrics)
    if signals["contradiction"]:
        return AxisResult(A_CONSISTENCY, LOW, APPLICABLE, "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION", metrics)
    if committed and support >= policy.consistency_high_min_support and not signals["softened"]:
        return AxisResult(A_CONSISTENCY, HIGH, APPLICABLE, "COMMITTED_DIRECTION_REPEATED_NO_CONTRADICTION", metrics)
    if not direction:
        return AxisResult(A_CONSISTENCY, MEDIUM, APPLICABLE, "NON_DIRECTIONAL_CAPPED_AT_MEDIUM", metrics)
    if not committed:
        return AxisResult(A_CONSISTENCY, MEDIUM, APPLICABLE, "NON_COMMITTED_DIRECTION_CAPPED_AT_MEDIUM", metrics)
    return AxisResult(A_CONSISTENCY, MEDIUM, APPLICABLE,
                      "DIRECTION_SOFTENED" if signals["softened"] else "INSUFFICIENT_POSITIVE_EVIDENCE", metrics)


# ------------------------------------------------------------------ Q19
def dna_novelty(record: Mapping[str, Any], comparison: Optional[Mapping[str, Any]],
                policy: EvaluationPolicy) -> AxisResult:
    components = dict(record.get("components") or {})
    evidence = [str(e) for e in (components.get("evidence") or [])]
    theme = str(components.get("theme") or "")
    if theme and theme not in ("UNKNOWN", "OTHER") and theme not in evidence:
        evidence.append(theme)
    target = outlook_part(components, "target=")
    comparison = dict(comparison or {})
    classification = str(comparison.get("classification", ""))
    overlap = len(comparison.get("evidence_overlap") or [])
    target_match = bool(comparison.get("target_match"))
    relation = str(comparison.get("direction_relation", ""))
    metrics = {"classification": classification or "MISSING", "evidence_overlap": overlap,
               "target_match": target_match, "direction_relation": relation or "MISSING",
               "candidate_rule_count": len(comparison.get("candidate_rule_ids") or []),
               "has_evidence_categories": bool(evidence), "has_target": bool(target)}
    if not evidence or not target:
        return AxisResult(A_NOVELTY, MEDIUM, NOT_APPLICABLE,
                          "COMPARISON_INPUT_MISSING: DNA matching needs both evidence categories and a target; "
                          "this pattern type structurally lacks one", metrics)
    if classification == "EXPLAINED_BY_EXISTING_RULE":
        return AxisResult(A_NOVELTY, LOW, APPLICABLE, "EXPLAINED_BY_EXISTING_RULE", metrics)
    if (classification == "PARTIALLY_EXPLAINED" and overlap >= policy.novelty_low_min_overlap
            and target_match and relation in policy.novelty_low_relations):
        return AxisResult(A_NOVELTY, LOW, APPLICABLE, "EVIDENCE_GROUNDED_AGREEMENT", metrics)
    if classification == "NEW_PATTERN_CANDIDATE":
        return AxisResult(A_NOVELTY, HIGH, APPLICABLE, "NEW_PATTERN_CANDIDATE_AND_ASSESSABLE", metrics)
    return AxisResult(A_NOVELTY, MEDIUM, APPLICABLE, "PARTIAL_COVERAGE", metrics)


# ------------------------------------------------------------------ Q20
def data_quality(record: Mapping[str, Any], structures: Sequence[Mapping[str, Any]],
                 policy: EvaluationPolicy) -> AxisResult:
    declared = list(record.get("supporting_document_ids") or [])
    qualities = [str(s.get("quality", "")) for s in structures]
    schema_versions = {str(s.get("schema_version", "")) for s in structures}
    analysis_versions = {str(s.get("corpus_analysis_version", "")) for s in structures}
    support, eligible = _int(record.get("support_count")), _int(record.get("eligible_support"))
    try:
        valid_ratio = Decimal(str(record.get("valid_ratio")))
    except Exception:  # noqa: BLE001
        valid_ratio = Decimal("0")
    metrics = {"declared_supporting_documents": len(declared), "resolved_supporting_documents": len(structures),
               "document_qualities": dict(Counter(qualities)), "valid_ratio": str(valid_ratio),
               "support_count": support, "eligible_support": eligible,
               "distinct_analysis_versions": len(analysis_versions),
               "market_alignment_absent_by_design": True}
    if len(structures) != len(declared) or not structures:
        return AxisResult(A_QUALITY, LOW, APPLICABLE, "UNRESOLVED_SUPPORTING_IDS", metrics)
    if any(q in policy.quality_blocking_document_qualities for q in qualities) or any(
            not s.get("eligible") for s in structures):
        return AxisResult(A_QUALITY, LOW, APPLICABLE, "INELIGIBLE_OR_LIMITED_USE_SUPPORT", metrics)
    if valid_ratio < policy.quality_medium_valid_ratio_floor:
        return AxisResult(A_QUALITY, LOW, APPLICABLE, "VALID_RATIO_BELOW_FLOOR", metrics)
    if policy.supported_structure_schema_versions and not schema_versions <= set(
            policy.supported_structure_schema_versions):
        return AxisResult(A_QUALITY, LOW, APPLICABLE, "UNSUPPORTED_STRUCTURE_SCHEMA_VERSION", metrics)
    if policy.supported_analysis_versions and not analysis_versions <= set(policy.supported_analysis_versions):
        return AxisResult(A_QUALITY, LOW, APPLICABLE, "UNSUPPORTED_ANALYSIS_VERSION", metrics)
    if any(q in policy.quality_degraded_document_qualities for q in qualities):
        return AxisResult(A_QUALITY, MEDIUM, APPLICABLE, "PARTIAL_SUPPORTING_EVIDENCE", metrics)
    if valid_ratio < Decimal("1.0"):
        return AxisResult(A_QUALITY, MEDIUM, APPLICABLE, "VALID_RATIO_BELOW_ONE", metrics)
    if eligible != support:
        return AxisResult(A_QUALITY, MEDIUM, APPLICABLE, "ELIGIBLE_SUPPORT_BELOW_SUPPORT_COUNT", metrics)
    if len(analysis_versions) > 1:
        return AxisResult(A_QUALITY, MEDIUM, APPLICABLE, "MIXED_ANALYSIS_VERSIONS", metrics)
    return AxisResult(A_QUALITY, HIGH, APPLICABLE, "ALL_SUPPORT_VALID_AND_ELIGIBLE", metrics)
