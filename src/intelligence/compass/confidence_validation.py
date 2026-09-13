"""Confidence–language coupling validator（Phase 3.5 pre-flight B）。

OUTLOOK claim の**言語強度**は outlook.confidence と機械的に整合していなければならない。

    HIGH   → 強い表現   「〜が見込まれる」（「〜となろう」も同格）
    MEDIUM → 中程度     「〜する可能性がある」
    LOW    → 弱い表現   「〜の余地がある」「方向感は限定的」

文中の強度マーカーを lexicon（`STRENGTH_LEXICON`）で読み、confidence と食い違えば
error `confidence_language_mismatch`。強度マーカーが無ければ error
`confidence_language_missing`（確度を語らない見通しは検証できない）。
"""
from __future__ import annotations

from typing import List, Optional

from .lexicon import asserted_strength
from .model import (
    SEVERITY_ERROR,
    ClaimRole,
    CompassClaim,
    CompassOutlook,
    ValidationIssue,
)

VALIDATOR = "confidence"


def _issue(claim: CompassClaim, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=SEVERITY_ERROR, claim_id=claim.claim_id)


def validate_confidence(claim: CompassClaim, outlook: Optional[CompassOutlook]
                        ) -> List[ValidationIssue]:
    if claim.claim_role is not ClaimRole.OUTLOOK or outlook is None:
        return []
    strength = asserted_strength(claim.text)
    if strength is None:
        return [_issue(claim, "confidence_language_missing",
                       "見通し文に強度表現（見込まれる/可能性がある/余地がある）が無い")]
    if strength is not outlook.confidence:
        return [_issue(claim, "confidence_language_mismatch",
                       f"文の強度は{strength.value}だがconfidenceは{outlook.confidence.value}")]
    return []
