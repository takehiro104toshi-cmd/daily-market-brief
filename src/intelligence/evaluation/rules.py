"""Recommendation rules（Phase 3.9.2）— frozen precedence、first match wins、決定的。

    1. NOT_READY  2. REJECT_RECOMMENDED  3. APPROVE_RECOMMENDED  4. REVIEW_RECOMMENDED  5. KEEP_REVIEWING

APPROVE_RECOMMENDED は「人間が formal approval を検討することを engine が勧める」だけで、APPROVED でも
DNA promotion でもない。矛盾は再現性（volume）に勝つ（REJECT が APPROVE より先）。Reference Score は読まない。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from .config import (
    A_CONSISTENCY,
    A_CROSS,
    A_QUALITY,
    A_STRENGTH,
    A_TIME,
    CORE_AXES,
    HIGH,
    LOW,
    RANK,
    EvaluationPolicy,
    RecommendationPolicy,
)
from .models import (
    APPROVE_RECOMMENDED,
    KEEP_REVIEWING,
    NOT_READY,
    REJECT_RECOMMENDED,
    REVIEW_RECOMMENDED,
    AxisResult,
)

R_DATA_QUALITY_LOW = "NOT_READY:DATA_QUALITY_LOW"
R_TOO_FEW_CORE = "NOT_READY:INSUFFICIENT_APPLICABLE_CORE_AXES"
R_INPUTS_UNAVAILABLE = "NOT_READY:CRITICAL_INPUT_UNAVAILABLE"
R_REJECT = "REJECT:CONSISTENCY_LOW_WITH_REPEATED_MATERIAL_CONTRADICTION"
R_APPROVE = "APPROVE:ALL_APPLICABLE_CORE_CONDITIONS_MET"
R_REVIEW = "REVIEW:SUFFICIENT_EVIDENCE_FOR_HUMAN_ATTENTION"
R_KEEP = "KEEP_REVIEWING:FALLBACK"

B_TYPE_NOT_ELIGIBLE = "TYPE_NOT_APPROVAL_ELIGIBLE"
B_QUALITY_NOT_HIGH = "DATA_QUALITY_NOT_HIGH"
B_CORE_BELOW_MEDIUM = "APPLICABLE_CORE_AXIS_BELOW_MEDIUM"
B_CONSISTENCY_NOT_HIGH = "CONSISTENCY_NOT_HIGH"
B_TIME_NOT_HIGH = "TIME_STABILITY_NOT_HIGH"
B_CROSS_NOT_HIGH = "CROSS_REGIME_NOT_HIGH"
B_STRENGTH_BELOW_MEDIUM = "STRENGTH_BELOW_MEDIUM"
B_TIME_BELOW_MEDIUM = "TIME_BELOW_MEDIUM"
B_CONSISTENCY_LOW = "CONSISTENCY_LOW"
B_CONTRADICTION_NOT_REPEATED = "CONTRADICTION_NOT_REPEATED"
B_STRENGTH_NOT_HIGH = "STRENGTH_NOT_HIGH_FOR_REJECT"


@dataclass(frozen=True)
class RuleOutcome:
    recommendation: str
    triggered_rule: str
    blocking_rules: Tuple[str, ...]
    supporting_rules: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {"recommendation": self.recommendation, "triggered_rule": self.triggered_rule,
                "blocking_rules": list(self.blocking_rules), "supporting_rules": list(self.supporting_rules)}


def repeated_contradiction(axes: Mapping[str, AxisResult], policy: RecommendationPolicy) -> bool:
    """孤立した 1 件の矛盾では REJECT しない。反復・実体のある矛盾だけを認める。"""
    m = dict(axes[A_CONSISTENCY].metrics)
    support = int(m.get("eligible_support") or 0)
    if m.get("contradiction_repeated"):                                   # UP >=N かつ DOWN >=N
        return True
    if m.get("narrow_sibling_repeated"):                                  # 双方 eligible_support >= N
        return True
    if int(m.get("dna_conflicts") or 0) > 0 and support >= policy.reject_min_dna_conflict_support:
        return True
    return False


def decide(axes: Mapping[str, AxisResult], pattern_type: str, policy: RecommendationPolicy,
           evaluation_policy: EvaluationPolicy, inputs_available: bool = True) -> RuleOutcome:
    supporting: List[str] = []
    quality = axes[A_QUALITY].state
    applicable_core = [a for a in CORE_AXES if axes[a].applicable]

    # ---- 1. NOT_READY（評価そのものが信頼できない。pattern の良し悪しではない）
    if not inputs_available:
        return RuleOutcome(NOT_READY, R_INPUTS_UNAVAILABLE, (), ())
    if quality == LOW:
        return RuleOutcome(NOT_READY, R_DATA_QUALITY_LOW, (R_DATA_QUALITY_LOW,), ())
    if len(applicable_core) < policy.not_ready_min_applicable_core_axes:
        return RuleOutcome(NOT_READY, R_TOO_FEW_CORE, (R_TOO_FEW_CORE,), ())

    # ---- 2. REJECT_RECOMMENDED（矛盾は再現性に勝つ。証拠不足は決して REJECT にしない）
    reject_blocking: List[str] = []
    if axes[A_CONSISTENCY].state == policy.reject_require_consistency:
        if RANK[axes[A_STRENGTH].state] < RANK[policy.reject_min_strength]:
            reject_blocking.append(B_STRENGTH_NOT_HIGH)
        if RANK[axes[A_TIME].state] < RANK[policy.reject_min_time]:
            reject_blocking.append(B_TIME_BELOW_MEDIUM)
        if not repeated_contradiction(axes, policy):
            reject_blocking.append(B_CONTRADICTION_NOT_REPEATED)
        if not reject_blocking:
            return RuleOutcome(REJECT_RECOMMENDED, R_REJECT, (),
                               ("CONSISTENCY_LOW", "STRENGTH_HIGH", "TIME_AT_LEAST_MEDIUM", "CONTRADICTION_REPEATED"))

    # ---- 3. APPROVE_RECOMMENDED（strict。novelty は要求しない）
    blocking: List[str] = []
    if pattern_type in policy.approve_excluded_types:
        blocking.append(B_TYPE_NOT_ELIGIBLE)
    if RANK[quality] < RANK[policy.approve_require_quality]:
        blocking.append(B_QUALITY_NOT_HIGH)
    if any(RANK[axes[a].state] < RANK[policy.approve_min_applicable_core] for a in applicable_core):
        blocking.append(B_CORE_BELOW_MEDIUM)
    if RANK[axes[A_CONSISTENCY].state] < RANK[policy.approve_require_consistency]:
        blocking.append(B_CONSISTENCY_NOT_HIGH)
    if RANK[axes[A_TIME].state] < RANK[policy.approve_require_time]:
        blocking.append(B_TIME_NOT_HIGH)
    if axes[A_CROSS].applicable and RANK[axes[A_CROSS].state] < RANK[policy.approve_require_cross_regime]:
        blocking.append(B_CROSS_NOT_HIGH)
    if not blocking:
        supporting = ["DATA_QUALITY_HIGH", "TYPE_APPROVAL_ELIGIBLE", "ALL_APPLICABLE_CORE_AT_LEAST_MEDIUM",
                      "CONSISTENCY_HIGH", "TIME_STABILITY_HIGH"]
        if axes[A_CROSS].applicable:
            supporting.append("CROSS_REGIME_HIGH")
        else:
            supporting.append("CROSS_REGIME_NOT_APPLICABLE_SKIPPED")
        return RuleOutcome(APPROVE_RECOMMENDED, R_APPROVE, (), tuple(supporting))

    # ---- 4. REVIEW_RECOMMENDED（outlook-free の WHY / RISK もここまでは到達できる）
    review_blocking: List[str] = []
    if axes[A_STRENGTH].applicable and RANK[axes[A_STRENGTH].state] < RANK[policy.review_min_strength]:
        review_blocking.append(B_STRENGTH_BELOW_MEDIUM)
    if RANK[axes[A_TIME].state] < RANK[policy.review_min_time]:
        review_blocking.append(B_TIME_BELOW_MEDIUM)
    if axes[A_CONSISTENCY].state == policy.review_consistency_not:
        review_blocking.append(B_CONSISTENCY_LOW)
    if not review_blocking:
        return RuleOutcome(REVIEW_RECOMMENDED, R_REVIEW, tuple(blocking),
                           ("STRENGTH_AT_LEAST_MEDIUM", "TIME_AT_LEAST_MEDIUM", "NO_STRONG_CONTRADICTION"))

    # ---- 5. KEEP_REVIEWING（無条件 fallback。なぜ上位に届かなかったかを必ず残す）
    return RuleOutcome(KEEP_REVIEWING, R_KEEP, tuple(dict.fromkeys(review_blocking + reject_blocking + blocking)), ())
