"""P10-A4 — 人の決定の型つきの入力（authority を担う値だけ ・root ／ revision の id ・seq ・prev は持たない）。

7 つの操作だけ（汎用の revision の API は無い）: `PROFILE_CREATE` ・`PROFILE_REVISE` ・`PROFILE_CORRECTION` ・`PROFILE_RETIRE` ・
`ATTENTION_CREATE` ・`ATTENTION_REVISE` ・`ATTENTION_TRANSITION`。更新は `expected_head_revision_id`（人が見た鎖の先頭）を持つ。
作成は root ／ revision の id を受けない（実行器が導く）。`author_ref`（`human:`）・`reviewed_at`（aware）は明示で、時計の既定は無い。

`decision_from_mapping` は local の JSON の object を欄の完全一致で型に写す（未知 ／ 欠けた欄 ・型の違いは拒む ・既定値で補わない）。
値の意味の検査（UTF-8 ・A2 の規則）は実行器が行う。

記録: `docs/databank/PHASE10_A4_EXECUTOR_REVIEW_VIEW.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Tuple, Union

from .attention_model import AttentionState, AttentionTargetKind


class DecisionInputError(ValueError):
    """決定の入力の形の誤り（安全な code と欄の名前だけ ・値は入れない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, kw_only=True)
class ProfileCreate:
    author_ref: str
    reviewed_at: datetime
    horizon_note: str
    liquidity_note: str
    risk_context_note: str
    review_lookahead_days: int
    excluded_issuer_ids: Tuple[str, ...]
    exclusion_reason_note: str
    operation: str = "PROFILE_CREATE"


@dataclass(frozen=True, kw_only=True)
class ProfileRevise:
    profile_id: str
    expected_head_revision_id: str
    author_ref: str
    reviewed_at: datetime
    horizon_note: str
    liquidity_note: str
    risk_context_note: str
    review_lookahead_days: int
    excluded_issuer_ids: Tuple[str, ...]
    exclusion_reason_note: str
    operation: str = "PROFILE_REVISE"


@dataclass(frozen=True, kw_only=True)
class ProfileCorrection:
    profile_id: str
    expected_head_revision_id: str
    corrects_revision_id: str
    correction_reason: str
    author_ref: str
    reviewed_at: datetime
    horizon_note: str
    liquidity_note: str
    risk_context_note: str
    review_lookahead_days: int
    excluded_issuer_ids: Tuple[str, ...]
    exclusion_reason_note: str
    operation: str = "PROFILE_CORRECTION"


@dataclass(frozen=True, kw_only=True)
class ProfileRetire:
    profile_id: str
    expected_head_revision_id: str
    retirement_reason: str
    author_ref: str
    reviewed_at: datetime
    operation: str = "PROFILE_RETIRE"


@dataclass(frozen=True, kw_only=True)
class AttentionCreate:
    target_kind: AttentionTargetKind
    target_root_id: str
    observed_p9_revision_id: str
    state: AttentionState
    author_ref: str
    reviewed_at: datetime
    operation: str = "ATTENTION_CREATE"


@dataclass(frozen=True, kw_only=True)
class AttentionRevise:
    attention_id: str
    expected_head_revision_id: str
    observed_p9_revision_id: str
    author_ref: str
    reviewed_at: datetime
    operation: str = "ATTENTION_REVISE"


@dataclass(frozen=True, kw_only=True)
class AttentionTransition:
    attention_id: str
    expected_head_revision_id: str
    observed_p9_revision_id: str
    state: AttentionState
    author_ref: str
    reviewed_at: datetime
    operation: str = "ATTENTION_TRANSITION"


Decision = Union[ProfileCreate, ProfileRevise, ProfileCorrection, ProfileRetire, AttentionCreate, AttentionRevise,
                 AttentionTransition]
DECISION_TYPES: Dict[str, type] = {cls.operation: cls for cls in (
    ProfileCreate, ProfileRevise, ProfileCorrection, ProfileRetire, AttentionCreate, AttentionRevise,
    AttentionTransition)}
_CONTENT = ("horizon_note", "liquidity_note", "risk_context_note", "review_lookahead_days", "excluded_issuer_ids",
            "exclusion_reason_note")
#: 操作 → JSON の欄（`operation` を含む ・完全一致）
DECISION_FIELDS: Dict[str, Tuple[str, ...]] = {
    "PROFILE_CREATE": ("operation", "author_ref", "reviewed_at", *_CONTENT),
    "PROFILE_REVISE": ("operation", "profile_id", "expected_head_revision_id", "author_ref", "reviewed_at", *_CONTENT),
    "PROFILE_CORRECTION": ("operation", "profile_id", "expected_head_revision_id", "corrects_revision_id",
                           "correction_reason", "author_ref", "reviewed_at", *_CONTENT),
    "PROFILE_RETIRE": ("operation", "profile_id", "expected_head_revision_id", "retirement_reason", "author_ref",
                       "reviewed_at"),
    "ATTENTION_CREATE": ("operation", "target_kind", "target_root_id", "observed_p9_revision_id", "state",
                         "author_ref", "reviewed_at"),
    "ATTENTION_REVISE": ("operation", "attention_id", "expected_head_revision_id", "observed_p9_revision_id",
                         "author_ref", "reviewed_at"),
    "ATTENTION_TRANSITION": ("operation", "attention_id", "expected_head_revision_id", "observed_p9_revision_id",
                             "state", "author_ref", "reviewed_at"),
}


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise DecisionInputError("INVALID_TIMESTAMP", "reviewed_at")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise DecisionInputError("INVALID_TIMESTAMP", "reviewed_at") from None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise DecisionInputError("INSTANT_NOT_AWARE", "reviewed_at")
    return parsed


def decision_from_mapping(data: Any) -> Decision:
    """JSON の object → 型つきの決定（欄の完全一致 ・既定値で補わない）。"""
    if not isinstance(data, dict) or not isinstance(data.get("operation"), str):
        raise DecisionInputError("INVALID_DECISION", "operation")
    operation = data["operation"]
    if operation not in DECISION_FIELDS:
        raise DecisionInputError("UNKNOWN_OPERATION", "operation")
    expected = set(DECISION_FIELDS[operation])
    if set(data) - expected:
        raise DecisionInputError("UNKNOWN_FIELDS", operation)
    if expected - set(data):
        raise DecisionInputError("MISSING_FIELDS", operation)
    values: Dict[str, Any] = {k: v for k, v in data.items() if k != "operation"}
    values["reviewed_at"] = _instant(data["reviewed_at"])
    if "excluded_issuer_ids" in values:
        if not isinstance(values["excluded_issuer_ids"], list):
            raise DecisionInputError("INVALID_LIST", "excluded_issuer_ids")
        values["excluded_issuer_ids"] = tuple(values["excluded_issuer_ids"])
    for name, kind in (("target_kind", AttentionTargetKind), ("state", AttentionState)):
        if name in values:
            if not isinstance(values[name], str) or values[name] not in {m.value for m in kind}:
                raise DecisionInputError("INVALID_ENUM", name)
            values[name] = kind(values[name])
    return DECISION_TYPES[operation](**values)


__all__ = ["AttentionCreate", "AttentionRevise", "AttentionTransition", "DECISION_FIELDS", "DECISION_TYPES",
           "Decision", "DecisionInputError", "ProfileCorrection", "ProfileCreate", "ProfileRetire", "ProfileRevise",
           "decision_from_mapping"]
