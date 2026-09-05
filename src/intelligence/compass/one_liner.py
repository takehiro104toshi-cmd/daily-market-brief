"""Customer-facing one-liner（Phase 3-C §22 / §23）。

**grounded claimの文だけ**を組み合わせて2〜4文の短文を作る（新しい文は書かない）:
HEADLINE（事実） → OUTLOOK（見通し・1文目のみ） → RISK（反対材料・1文目のみ）。

推奨・数値目標は language_rules で拒否済みだが、最終出力でも再検査する
（fail-closed: 満たさなければ空文字＝出さない）。
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence

from .config import CompassConfig
from .language_rules import (
    ADVICE_PATTERN, OUTLOOK_FORMS, TARGET_NUMBER_PATTERN, TARGET_WORD_PATTERN,
)
from .model import ClaimRole, CompassClaim, SEVERITY_ERROR, SEVERITY_WARNING, ValidationIssue

VALIDATOR = "one_liner"
_SENTENCE = re.compile(r"[^。]+。")
#: 顧客向け短文では出典タグ（経験則ID）を外す（内容は変えない。claim側に残る）
_PROVENANCE_TAG = re.compile(r"（経験則 [A-Z]{2}_[A-Z]{2,4}_\d{3}）")


def strip_provenance(text: str) -> str:
    return _PROVENANCE_TAG.sub("", text)


def sentences(text: str) -> List[str]:
    return [m.group(0) for m in _SENTENCE.finditer(text)]


def sentence_count(text: str) -> int:
    return len(sentences(text))


def _first(claims: Sequence[CompassClaim], role: ClaimRole) -> Optional[CompassClaim]:
    for c in claims:
        if c.claim_role is role and c.is_grounded:
            return c
    return None


def build_one_liner(claims: Sequence[CompassClaim], config: CompassConfig) -> str:
    """grounded claimからone-linerを組む。必須要素が欠ければ空文字。"""
    headline = _first(claims, ClaimRole.HEADLINE) or _first(claims, ClaimRole.WHAT_HAPPENED)
    outlook = _first(claims, ClaimRole.OUTLOOK)
    risk = _first(claims, ClaimRole.RISK)
    if headline is None or outlook is None or risk is None:
        return ""
    parts: List[str] = []
    parts += sentences(headline.text)[:2]
    parts += sentences(outlook.text)[:1]
    parts += sentences(risk.text)[:1]
    if not (config.one_liner_min_sentences <= len(parts) <= config.one_liner_max_sentences):
        # 4文超なら見出しを1文に詰める（それでも範囲外なら出さない）
        parts = sentences(headline.text)[:1] + sentences(outlook.text)[:1] \
            + sentences(risk.text)[:1]
        if not (config.one_liner_min_sentences <= len(parts) <= config.one_liner_max_sentences):
            return ""
    return strip_provenance("".join(parts))


def validate_one_liner(text: str, config: CompassConfig) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if not text:
        return [ValidationIssue(validator=VALIDATOR, code="empty", message="one-linerが空",
                                severity=SEVERITY_WARNING)]
    n = sentence_count(text)
    if not (config.one_liner_min_sentences <= n <= config.one_liner_max_sentences):
        issues.append(ValidationIssue(
            validator=VALIDATOR, code="sentence_count",
            message=f"文数 {n} が {config.one_liner_min_sentences}–"
                    f"{config.one_liner_max_sentences} の範囲外", severity=SEVERITY_ERROR))
    if ADVICE_PATTERN.search(text):
        issues.append(ValidationIssue(validator=VALIDATOR, code="advice_language",
                                      message="推奨語彙を含む", severity=SEVERITY_ERROR))
    if TARGET_WORD_PATTERN.search(text) or TARGET_NUMBER_PATTERN.search(text):
        issues.append(ValidationIssue(validator=VALIDATOR, code="numeric_target",
                                      message="数値目標を含む", severity=SEVERITY_ERROR))
    if not any(form in text for form in OUTLOOK_FORMS):
        issues.append(ValidationIssue(validator=VALIDATOR, code="outlook_form",
                                      message="見通し文（見込まれる/可能性がある/余地がある）を含まない",
                                      severity=SEVERITY_WARNING))
    return issues
