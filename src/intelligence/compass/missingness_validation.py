"""Missingness / conflict-aware validation（Phase 3-C §16 / §36）。

claimが言及した主語の**market state dimension**が、Evidence Packageの
`dimension_status` で MISSING / STALE / CONFLICTED / INSUFFICIENT_HISTORY のとき、
その主語について**断定する文は拒否**する（欠けている次元を語ってはならない）。

COVERAGE roleは「語れない次元」を明示する役割なので対象外。
25日移動平均（MA）は独立した次元を持たないためスキップする。
"""
from __future__ import annotations

from typing import Dict, List

from ..context.model import ContextStatus
from .evidence_package import EvidencePackage
from .lexicon import KEY_DIMENSION, SUBJECT_PATTERN
from .model import ClaimRole, CompassClaim, SEVERITY_ERROR, ValidationIssue

VALIDATOR = "missingness"

_CODES: Dict[ContextStatus, str] = {
    ContextStatus.MISSING: "missing_dimension_assertion",
    ContextStatus.STALE: "stale_dimension_assertion",
    ContextStatus.CONFLICTED: "conflicted_dimension_assertion",
    ContextStatus.INSUFFICIENT_HISTORY: "insufficient_history_assertion",
    ContextStatus.NOT_ENTITLED: "not_entitled_dimension_assertion",
}


def _issue(claim: CompassClaim, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=SEVERITY_ERROR, claim_id=claim.claim_id)


def mentioned_dimensions(text: str) -> List[str]:
    """文中の主語 → dimension（出現順・重複なし）。"""
    out: List[str] = []
    for m in SUBJECT_PATTERN.finditer(text):
        key = m.lastgroup or ""
        dim = KEY_DIMENSION.get(key)
        if dim and dim not in out:
            out.append(dim)
    return out


def validate_missingness(claim: CompassClaim, package: EvidencePackage
                         ) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if claim.claim_role is ClaimRole.COVERAGE:
        return issues
    for dim in mentioned_dimensions(claim.text):
        status = package.dimension_status.get(dim)
        if status is None:
            issues.append(_issue(claim, "missing_dimension_assertion",
                                 f"Evidence Packageに存在しない次元への言及: {dim}"))
            continue
        code = _CODES.get(status)
        if code:
            issues.append(_issue(claim, code,
                                 f"{dim} は {status.value} のため断定できない"))
    return issues
