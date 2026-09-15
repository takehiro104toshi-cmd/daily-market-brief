"""Numeric validator（Phase 3-C §14）。

claim文中の**すべての数値**が、Evidence Package内のFact値 / Context magnitude
（丸め後）と一致することを要求する。一致しない数値は根拠なし＝error。
一致はするが引用していないFact/Contextの数値なら warning（引用漏れ）。

日付（ISO）・rule_id（JP_XX_000）・英数字識別子・「25日」「5営業日」「10年」等の
数え語は数値として扱わない（temporal validatorが別に見る）。
丸めは ROUND_HALF_UP（生成側 lexicon.fmt_* と同じ）。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, List, Sequence, Set, Tuple

from .evidence_package import EvidencePackage
from .model import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    CompassClaim,
    ValidationIssue,
)

VALIDATOR = "numeric"

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_RULE_ID = re.compile(r"[A-Z]{2}_[A-Z]{2,4}_\d{3}")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[+-]?\d+(?:\.\d+)?")
#: 数え語・時間語（直後に続くと数値検証の対象外）
_COUNT_SUFFIX = re.compile(r"^(?:年|月|日|営業日|時|分|秒|回|件|本|つ|次元|セッション|番|位)")


def _issue(claim: CompassClaim, code: str, message: str,
           severity: str = SEVERITY_ERROR) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=severity, claim_id=claim.claim_id)


def extract_numbers(text: str) -> List[Tuple[str, Decimal, int, bool]]:
    """(生トークン, 値, 小数桁, 符号明示) のリスト。"""
    cleaned = _ISO_DATE.sub(" ", text)
    cleaned = _RULE_ID.sub(" ", cleaned)
    cleaned = _IDENTIFIER.sub(" ", cleaned)
    out: List[Tuple[str, Decimal, int, bool]] = []
    for match in _NUMBER.finditer(cleaned):
        token = match.group(0)
        tail = cleaned[match.end():]
        if _COUNT_SUFFIX.match(tail):
            continue
        # 「10年-2年」のような範囲表記の後半（直前が数字+ハイフン）は数値ではない
        before = cleaned[:match.start()]
        if token.startswith("-") and before and before[-1].isdigit():
            continue
        try:
            value = Decimal(token.replace(",", ""))
        except InvalidOperation:
            continue
        places = len(token.split(".")[1]) if "." in token else 0
        out.append((token, value, places, token[0] in "+-"))
    return out


def _candidates(package: EvidencePackage, fact_ids: Iterable[str],
                context_ids: Iterable[str]) -> List[Decimal]:
    values: List[Decimal] = []
    for fid in fact_ids:
        fact = package.fact(fid)
        if fact is not None and fact.value.value is not None:
            values.append(fact.value.value)
    for cid in context_ids:
        item = package.context(cid)
        if item is not None and item.magnitude is not None:
            values.append(item.magnitude)
    return values


def _matches(value: Decimal, places: int, signed: bool, candidates: Sequence[Decimal],
             tolerance: Decimal) -> bool:
    q = Decimal(1).scaleb(-places)
    for cand in candidates:
        target = cand if signed else abs(cand)
        try:
            if target.quantize(q, rounding=ROUND_HALF_UP) == value:
                return True
        except InvalidOperation:
            continue
        if abs(target - value) <= tolerance:
            return True
    return False


def validate_numbers(claim: CompassClaim, package: EvidencePackage, *,
                     tolerance: Decimal = Decimal("0.005")) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    numbers = extract_numbers(claim.text)
    if not numbers:
        return issues
    cited_facts: Set[str] = set(claim.supporting_fact_ids)
    for cid in claim.supporting_context_ids:
        item = package.context(cid)
        if item is not None:
            cited_facts.update(item.supporting_fact_ids)
    cited = _candidates(package, cited_facts, claim.supporting_context_ids)
    everything = _candidates(package, package.fact_ids, package.context_ids)
    for token, value, places, signed in numbers:
        if _matches(value, places, signed, cited, tolerance):
            continue
        if _matches(value, places, signed, everything, tolerance):
            issues.append(_issue(claim, "number_not_in_citations",
                                 f"数値 {token} は引用したFact/Contextに無い",
                                 SEVERITY_WARNING))
            continue
        issues.append(_issue(claim, "unsupported_number",
                             f"数値 {token} はEvidence Packageのどの値とも一致しない"))
    return issues
