"""Grounding validator（Phase 3-C §12 / §13）。

各claimが**Evidence Packageの中のFact / Context**だけを根拠にしているかを検査する。

- COVERAGE以外のclaimは根拠IDを1つ以上持つ（citation_missing）
- FACTUALはfact_id、RELATIONAL / INTERPRETIVE / OUTLOOK / RISKはcontext_idが必須
- 未知のID（packageに無い）は unknown_fact_id / unknown_context_id
- 引用したContextの supporting_fact_ids が package に無ければ broken_citation_chain
- 引用したFactの known_at が cutoff より後なら look_ahead_citation（fail-closed）
"""
from __future__ import annotations

from typing import List

from .evidence_package import EvidencePackage
from .model import (
    SEVERITY_ERROR,
    ClaimRole,
    ClaimType,
    CompassClaim,
    ValidationIssue,
)

VALIDATOR = "grounding"

_NEEDS_FACT = (ClaimType.FACTUAL,)
_NEEDS_CONTEXT = (ClaimType.RELATIONAL, ClaimType.INTERPRETIVE, ClaimType.OUTLOOK,
                  ClaimType.RISK)


def _issue(claim: CompassClaim, code: str, message: str,
           severity: str = SEVERITY_ERROR) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=severity, claim_id=claim.claim_id)


def validate_grounding(claim: CompassClaim, package: EvidencePackage
                       ) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if claim.claim_role is ClaimRole.COVERAGE:
        return issues                      # 範囲の宣言は根拠IDを要しない
    if not claim.supporting_fact_ids and not claim.supporting_context_ids:
        issues.append(_issue(claim, "citation_missing", "根拠IDが無い"))
        return issues
    if claim.claim_type in _NEEDS_FACT and not claim.supporting_fact_ids:
        issues.append(_issue(claim, "fact_citation_missing",
                             "FACTUAL claimはfact_idを引用する必要がある"))
    if claim.claim_type in _NEEDS_CONTEXT and not claim.supporting_context_ids:
        issues.append(_issue(claim, "context_citation_missing",
                             f"{claim.claim_type.value} claimはcontext_idを引用する必要がある"))
    for fid in claim.supporting_fact_ids:
        fact = package.fact(fid)
        if fact is None:
            issues.append(_issue(claim, "unknown_fact_id",
                                 f"Evidence Packageに無いfact_id: {fid[:16]}"))
            continue
        if fact.time.known_at is None or fact.time.known_at > package.cutoff:
            issues.append(_issue(claim, "look_ahead_citation",
                                 f"cutoff後に既知になったFactを引用: {fid[:16]}"))
    for cid in claim.supporting_context_ids:
        item = package.context(cid)
        if item is None:
            issues.append(_issue(claim, "unknown_context_id",
                                 f"Evidence Packageに無いcontext_id: {cid[:16]}"))
            continue
        for fid in item.supporting_fact_ids:
            if package.fact(fid) is None:
                issues.append(_issue(claim, "broken_citation_chain",
                                     f"Contextの根拠Factがpackageに無い: {fid[:16]}"))
    return issues
