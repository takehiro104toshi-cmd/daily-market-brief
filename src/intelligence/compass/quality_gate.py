"""Quality gate（Phase 3-C §12–§17 / §38）。

全validatorをclaim毎に実行し、grounding statusを確定する:

- error が1つでもあれば **REJECTED**（fail-closed）
- warning のみなら GROUNDED_WITH_WARNINGS
- 指摘なしなら GROUNDED

draft全体のverdict:

- plan が abstain → ABSTAINED
- claim が無い → ABSTAINED
- REJECTED比率が閾値超 → REJECTED（生成物を信用しない）
- grounded HEADLINE / WHAT_HAPPENED が無い、grounded WHY が無い、
  grounded RISK が無い（反対材料の常設）→ ABSTAINED
- warning / rejection を含む → VALID_WITH_WARNINGS
- それ以外 → VALID

LLM出力は**untrusted**（§29）——validatorの結果だけが真。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from .config import CompassConfig
from .direction_validation import validate_direction
from .evidence_package import EvidencePackage
from .grounding import validate_grounding
from .language_rules import validate_language
from .missingness_validation import validate_missingness
from .model import (
    ClaimRole, CompassClaim, CompassOutlook, GroundingStatus, QualityVerdict,
    SEVERITY_ERROR, SEVERITY_WARNING, ValidationIssue,
)
from .narrative_plan import NarrativePlan
from .numeric_validation import validate_numbers
from .temporal_validation import validate_temporal

GATE_RULE_VERSION = "quality_gate:1.0.0"
VALIDATOR = "quality_gate"

#: 必須role（grounded claimが無ければ語らない）
ABSTAIN_NO_HEADLINE = "no_grounded_headline"
ABSTAIN_NO_WHY = "no_grounded_why"
ABSTAIN_NO_RISK = "no_grounded_risk"
ABSTAIN_NO_OUTLOOK = "no_grounded_outlook"
ABSTAIN_NO_CLAIMS = "no_claims"
REJECT_RATIO = "rejected_ratio_exceeded"


def evaluate_claim(claim: CompassClaim, package: EvidencePackage,
                   outlook: Optional[CompassOutlook], config: CompassConfig
                   ) -> CompassClaim:
    """1 claimに全validatorを適用してstatusを確定する。"""
    issues: List[ValidationIssue] = []
    issues += validate_grounding(claim, package)
    issues += validate_numbers(claim, package, tolerance=config.numeric_tolerance_abs)
    issues += validate_direction(claim, package, outlook)
    issues += validate_temporal(claim, package)
    issues += validate_missingness(claim, package)
    issues += validate_language(claim)
    if any(i.severity == SEVERITY_ERROR for i in issues):
        status = GroundingStatus.REJECTED
    elif issues:
        status = GroundingStatus.GROUNDED_WITH_WARNINGS
    else:
        status = GroundingStatus.GROUNDED
    return claim.with_status(status, issues)


@dataclass(frozen=True, kw_only=True)
class GateResult:
    claims: Tuple[CompassClaim, ...]
    verdict: QualityVerdict
    abstain_reason: str = ""
    issues: Tuple[ValidationIssue, ...] = ()
    stats: Dict[str, int] = field(default_factory=dict)
    rule_version: str = GATE_RULE_VERSION

    @property
    def grounded(self) -> List[CompassClaim]:
        return [c for c in self.claims if c.is_grounded]

    @property
    def rejected(self) -> List[CompassClaim]:
        return [c for c in self.claims if c.grounding_status is GroundingStatus.REJECTED]

    def grounded_for(self, role: ClaimRole) -> List[CompassClaim]:
        return [c for c in self.grounded if c.claim_role is role]

    def issue_codes(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for c in self.claims:
            for i in c.issues:
                key = f"{i.validator}:{i.code}"
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def as_dict(self) -> Dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "abstain_reason": self.abstain_reason,
            "issues": [i.as_dict() for i in self.issues],
            "stats": dict(self.stats),
            "issue_codes": self.issue_codes(),
            "rule_version": self.rule_version,
        }


def _draft_issue(code: str, message: str, severity: str = SEVERITY_ERROR) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=severity)


def run_quality_gate(claims: Sequence[CompassClaim], package: EvidencePackage,
                     plan: NarrativePlan, outlook: Optional[CompassOutlook],
                     config: CompassConfig) -> GateResult:
    evaluated = tuple(evaluate_claim(c, package, outlook, config) for c in claims)
    rejected = [c for c in evaluated if c.grounding_status is GroundingStatus.REJECTED]
    warned = [c for c in evaluated
              if c.grounding_status is GroundingStatus.GROUNDED_WITH_WARNINGS]
    grounded = [c for c in evaluated if c.is_grounded]

    def count(role: ClaimRole) -> int:
        return sum(1 for c in grounded if c.claim_role is role)

    stats = {
        "claims": len(evaluated), "grounded": len(grounded),
        "warnings": len(warned), "rejected": len(rejected),
        **{f"grounded_{r.value.lower()}": count(r) for r in ClaimRole},
    }
    issues: List[ValidationIssue] = []
    abstain = ""
    if plan.abstain_reason:
        verdict, abstain = QualityVerdict.ABSTAINED, plan.abstain_reason
    elif not evaluated:
        verdict, abstain = QualityVerdict.ABSTAINED, ABSTAIN_NO_CLAIMS
    else:
        ratio = Decimal(len(rejected)) / Decimal(len(evaluated))
        if ratio > config.max_rejected_ratio:
            verdict = QualityVerdict.REJECTED
            issues.append(_draft_issue(
                REJECT_RATIO, f"REJECTED比率 {ratio:.2f} が閾値 {config.max_rejected_ratio} 超"))
        elif count(ClaimRole.HEADLINE) == 0 and count(ClaimRole.WHAT_HAPPENED) == 0:
            verdict, abstain = QualityVerdict.ABSTAINED, ABSTAIN_NO_HEADLINE
        elif count(ClaimRole.WHY) == 0:
            verdict, abstain = QualityVerdict.ABSTAINED, ABSTAIN_NO_WHY
        elif count(ClaimRole.RISK) == 0:
            verdict, abstain = QualityVerdict.ABSTAINED, ABSTAIN_NO_RISK
        elif count(ClaimRole.OUTLOOK) == 0:
            verdict, abstain = QualityVerdict.ABSTAINED, ABSTAIN_NO_OUTLOOK
        elif rejected or warned:
            verdict = QualityVerdict.VALID_WITH_WARNINGS
        else:
            verdict = QualityVerdict.VALID
    if abstain:
        issues.append(_draft_issue(abstain, "生成物が必須条件を満たさないため語らない",
                                   SEVERITY_WARNING))
    return GateResult(claims=evaluated, verdict=verdict, abstain_reason=abstain,
                      issues=tuple(issues), stats=stats)
