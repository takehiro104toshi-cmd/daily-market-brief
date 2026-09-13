"""Principle validator（Phase 3.5 pre-flight A）。

Fact と Investment Interpretation を分離する:

- INTERPRETIVE / RISK claim が「追い風／逆風」等の**含意**を述べるなら、
  登録済み principle（`rule_ref`）を明示していること（無ければ warning
  `interpretation_without_principle`——LLM生成物が出典を落とした場合の検知）
- `rule_ref` が registry に無ければ error `unknown_market_principle`
- `rule_ref` の principle が適用対象とする context_type を引用していなければ
  error `principle_context_mismatch`（経験則を根拠外のContextへ流用しない）
- FACTUAL claim が `rule_ref` を持てば error `factual_with_principle`
  （一般論をFactへ昇格させない）
"""
from __future__ import annotations

import re
from typing import List

from .evidence_package import EvidencePackage
from .market_principles import MARKET_PRINCIPLE_VERSION, principle
from .model import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    ClaimRole,
    ClaimType,
    CompassClaim,
    ValidationIssue,
)

VALIDATOR = "principle"
#: 経験則に基づく含意の語（これを述べるなら principle の参照が必要）
IMPLICATION_PATTERN = re.compile(r"追い風|逆風|広がり|過熱|様子見")
_RULE_TAG = re.compile(r"（経験則 ([A-Z]{2}_[A-Z]{2,4}_\d{3})）")


def _issue(claim: CompassClaim, code: str, message: str,
           severity: str = SEVERITY_ERROR) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=severity, claim_id=claim.claim_id)


def referenced_rule(claim: CompassClaim) -> str:
    """構造化 `rule_ref` を優先し、無ければ文中の（経験則 XX）タグから読む。"""
    if claim.rule_ref:
        return claim.rule_ref
    m = _RULE_TAG.search(claim.text)
    return m.group(1) if m else ""


def validate_principles(claim: CompassClaim, package: EvidencePackage
                        ) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if claim.claim_role is ClaimRole.COVERAGE:
        return issues
    rule_ref = referenced_rule(claim)
    if claim.claim_type is ClaimType.FACTUAL:
        if rule_ref:
            issues.append(_issue(claim, "factual_with_principle",
                                 "FACTUAL claimは経験則を参照しない（一般論をFactにしない）"))
        return issues
    if claim.claim_type not in (ClaimType.INTERPRETIVE, ClaimType.RISK):
        return issues
    if not rule_ref:
        if IMPLICATION_PATTERN.search(claim.text):
            issues.append(_issue(claim, "interpretation_without_principle",
                                 "含意（追い風/逆風等）に経験則の参照が無い",
                                 SEVERITY_WARNING))
        return issues
    spec = principle(rule_ref)
    if spec is None:
        issues.append(_issue(claim, "unknown_market_principle",
                             f"登録されていない経験則: {rule_ref}"))
        return issues
    cited_types = {package.context(c).context_type for c in claim.supporting_context_ids
                   if package.context(c) is not None}
    if cited_types and not (cited_types & set(spec.applies_to)):
        issues.append(_issue(claim, "principle_context_mismatch",
                             f"{rule_ref} は {'/'.join(spec.applies_to)} を対象とするが、"
                             f"引用Contextは {'/'.join(sorted(cited_types))}"))
    if claim.market_principle_version and \
            claim.market_principle_version != MARKET_PRINCIPLE_VERSION:
        issues.append(_issue(claim, "principle_version_mismatch",
                             f"経験則カタログの版が異なる: {claim.market_principle_version}",
                             SEVERITY_WARNING))
    return issues
