"""Temporal validation（Phase 3-C §15 / §35）。

claim文中の**日付・時間表現**が根拠と整合しているかを機械的に見る。

- FACTUAL claimの日付は reference_session 以前でなければならない（未来の事実は存在しない）
- 他のroleの日付も session_date 以前、または根拠にした EVENT_PROXIMITY Context の
  event_date に限る（「来週の決算」等の未来言及は EVENT Context を引用した場合のみ許す）
- 「〜まで N 日」「N 日後」等のイベント距離は EVENT_PROXIMITY Context の magnitude に一致
  しなければならない

Fact / Context の look-ahead（known_at > cutoff）自体は grounding validator が拒否する。
本validatorは**文面**の時間参照を見る。
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import List, Optional, Set

from ..context.builders import EVENT_PROXIMITY
from ..context.model import ContextItem
from .evidence_package import EvidencePackage
from .model import ClaimRole, ClaimType, CompassClaim, SEVERITY_ERROR, ValidationIssue

VALIDATOR = "temporal"

_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_EVENT_DAYS = re.compile(r"まで(\d+)(?:営業)?日|(\d+)(?:営業)?日(?:後|以内|先)")
_FUTURE_MARKER = re.compile(r"明日|来週|来月|翌営業日|翌週|今後数日")
_EVENT_WORD = re.compile(r"決算|発表|イベント|FOMC|日銀会合|金融政策決定会合")
_EVENT_DATE_NOTE = re.compile(r"event_date=(\d{4}-\d{2}-\d{2})")


def _issue(claim: CompassClaim, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=SEVERITY_ERROR, claim_id=claim.claim_id)


def _parse_date(text: str) -> Optional[date]:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _event_contexts(claim: CompassClaim, package: EvidencePackage) -> List[ContextItem]:
    out: List[ContextItem] = []
    for cid in claim.supporting_context_ids:
        item = package.context(cid)
        if item is not None and item.context_type == EVENT_PROXIMITY:
            out.append(item)
    return out


def event_dates_of(items: List[ContextItem]) -> Set[str]:
    dates: Set[str] = set()
    for item in items:
        m = _EVENT_DATE_NOTE.search(item.note or "")
        if m:
            dates.add(m.group(1))
    return dates


def validate_temporal(claim: CompassClaim, package: EvidencePackage
                      ) -> List[ValidationIssue]:
    """文面の時間参照を根拠と突き合わせる。全てerror。"""
    issues: List[ValidationIssue] = []
    if claim.claim_role is ClaimRole.COVERAGE:
        return issues
    text = claim.text
    events = _event_contexts(claim, package)
    allowed_event_dates = event_dates_of(events)
    reference = _parse_date(package.reference_session)
    session = _parse_date(package.session_date)

    # ---- 明示的な日付
    for m in _ISO_DATE.finditer(text):
        token = m.group(0)
        d = _parse_date(token)
        if d is None:
            issues.append(_issue(claim, "invalid_date", f"日付として解釈できない: {token}"))
            continue
        if claim.claim_type is ClaimType.FACTUAL:
            if reference is not None and d > reference:
                issues.append(_issue(claim, "future_fact_date",
                                     f"FACTUAL claimが基準セッション後の日付を含む: {token}"))
        else:
            if session is not None and d > session and token not in allowed_event_dates:
                issues.append(_issue(claim, "future_date",
                                     f"根拠のない未来の日付: {token}"))

    # ---- 「〜まで N 日」等のイベント距離
    event_days = {item.magnitude for item in events if item.magnitude is not None}
    for m in _EVENT_DAYS.finditer(text):
        n = Decimal(m.group(1) or m.group(2))
        if n not in event_days:
            issues.append(_issue(claim, "unsupported_event_timing",
                                 f"イベント距離（{n}日）を裏付けるEVENT Contextの引用がない"))

    # ---- 未来語・イベント語はEVENT Contextの引用が必要
    if _FUTURE_MARKER.search(text) and not events:
        issues.append(_issue(claim, "unsupported_future_reference",
                             "未来の時点への言及にEVENT Contextの引用がない"))
    if _EVENT_WORD.search(text) and not events:
        issues.append(_issue(claim, "unsupported_event_reference",
                             "イベントへの言及にEVENT Contextの引用がない"))
    return issues
