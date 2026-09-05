"""Language rules（Phase 3-C §7 / §23 / §33 / §36）。

文面に対する**語彙レベル**の禁止事項:

- 根拠のない因果主張（「〜を受けて」「〜により」等）→ `unsupported_causal_claim`
  Context Engineは**同時性**しか確認していない（因果は主張しない）
- 投資助言（買い／売り／推奨／目標株価 等）→ `advice_language`
- 数値目標（「〜円を目指す」「上値目処」等）→ `numeric_target`
- prompt injection痕跡（「以前の指示を無視」等）→ `injection_marker`
  source text が generator control を奪えない構造の**最終防衛線**

warning:
- FACTUAL claimに推量表現（とみられる／となろう）が混じる → `factual_form`
- OUTLOOK claimに「となろう」が無い → `outlook_form`
  （Compass DNA: 事実＝〜した／分析＝〜とみられる／予想＝〜となろう）
"""
from __future__ import annotations

import re
from typing import List

from .model import (
    ClaimRole, ClaimType, CompassClaim, SEVERITY_ERROR, SEVERITY_WARNING, ValidationIssue,
)

VALIDATOR = "language"

CAUSAL_PATTERN = re.compile(
    r"押し下げ|押し上げ|を受け|受けて|背景に|により|によって|要因|影響で|につれて|に伴い"
    r"|because|due to|caused|driven by", re.IGNORECASE)
#: 「買い越し／売り越し」は投資部門別の**事実**語であり助言ではない（除外）
ADVICE_PATTERN = re.compile(
    r"買い(?!越)|売り(?!越)|推奨|買い場|売り場|目標株価|参入|エントリー|利確|損切り|ポートフォリオ|組み入れ"
    r"|\bbuy\b|\bsell\b", re.IGNORECASE)
TARGET_WORD_PATTERN = re.compile(r"目標|ターゲット|目指す|上値目処|下値目処|メド|目処")
TARGET_NUMBER_PATTERN = re.compile(
    r"[+-]?\d[\d,]*(?:\.\d+)?\s*(?:円|ドル|ポイント|pt|%)?\s*(?:まで|を目指|に達する|到達)")
INJECTION_PATTERN = re.compile(
    r"ignore (?:all |the )?(?:previous|prior|above) instructions|system prompt"
    r"|以前の指示|指示を無視|instructions?\s*:\s*|新しい指示", re.IGNORECASE)
INFERENTIAL_PATTERN = re.compile(r"とみられる|となろう|見込|だろう|可能性|余地")
OUTLOOK_FORM = "となろう"
#: 見通し文として認める述語（confidence別の強度表現。Phase 3.5 pre-flight B）
OUTLOOK_FORMS = ("となろう", "見込まれる", "可能性がある", "余地がある")
#: 週次データ（投資部門別売買）を日次として語る文（Phase 3.5 §19: 絶対に書かない）
FLOW_SUBJECT_PATTERN = re.compile(r"投資家|投資部門")
DAILY_WORD_PATTERN = re.compile(r"本日|今日|当日|きょう")


def _issue(claim: CompassClaim, code: str, message: str,
           severity: str = SEVERITY_ERROR) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=severity, claim_id=claim.claim_id)


def validate_language(claim: CompassClaim) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    text = claim.text
    if INJECTION_PATTERN.search(text):
        issues.append(_issue(claim, "injection_marker", "指示文らしき文字列を含む"))
    if claim.claim_role is ClaimRole.COVERAGE:
        return issues
    if CAUSAL_PATTERN.search(text):
        issues.append(_issue(claim, "unsupported_causal_claim",
                             "因果を主張する語彙を含む（Contextは同時性のみ）"))
    if ADVICE_PATTERN.search(text):
        issues.append(_issue(claim, "advice_language", "投資助言に該当する語彙を含む"))
    if TARGET_WORD_PATTERN.search(text) or TARGET_NUMBER_PATTERN.search(text):
        issues.append(_issue(claim, "numeric_target", "数値目標・目処を含む"))
    if claim.claim_type is ClaimType.FACTUAL and INFERENTIAL_PATTERN.search(text):
        issues.append(_issue(claim, "factual_form", "事実文に推量表現が混じる",
                             SEVERITY_WARNING))
    if claim.claim_role is ClaimRole.OUTLOOK and not any(f in text for f in OUTLOOK_FORMS):
        issues.append(_issue(claim, "outlook_form",
                             "見通し文が強度表現（見込まれる/可能性がある/余地がある）で結ばれていない",
                             SEVERITY_WARNING))
    if FLOW_SUBJECT_PATTERN.search(text) and DAILY_WORD_PATTERN.search(text):
        issues.append(_issue(claim, "weekly_flow_as_daily",
                             "週次の投資部門別売買を日次（本日/今日）として語っている"))
    return issues
