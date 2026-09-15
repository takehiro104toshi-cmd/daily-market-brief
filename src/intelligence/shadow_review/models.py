"""Shadow Review event / card model（Phase 3.9.3）— schema-versioned, deterministic, no source text。

review event は **人間の発話だけ**を持つ append-only history。policy 由来の派生値（cooldown 等）は
derived 側にしか置かない。card / event のどこにも本文・page text・path・ファイル名を入れない
（FORBIDDEN_KEYS を再帰的に検査して fail closed）。

Shadow Review は Decision ではない:
- AGREE は「推奨状態に同意する」であって formal APPROVED ではない
- REJECT_RECOMMENDED への AGREE は「否定レビューが妥当」であって formal REJECTED ではない
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..evaluation.models import RECOMMENDATION_STATES
from .config import (
    MISSING_CATEGORIES,
    OUTCOMES,
    REVIEWER_TYPE_HUMAN,
    SECTIONS,
    ShadowReviewPolicy,
)

SCHEMA_VERSION = "1.0.0"
EVENT_ID_PREFIX = "srv_"

#: event / card のどこにも現れてはならない key（Phase 3.9.2 の FORBIDDEN_KEYS を継承し、
#: Phase 3.9.3 で file 名・title 系を追加。再帰的に検査する）。
FORBIDDEN_KEYS: Tuple[str, ...] = (
    "text", "source_text", "page_text", "body", "raw", "statement", "path",
    "file_path", "filename", "file_name", "source_filename", "source_path",
    "title", "raw_title", "headline", "contents", "content", "pdf_text", "page_texts",
)

#: 結論に必ず付ける boundary（Phase 3.9.2 の BASE_LIMITATIONS を Shadow Review 用に引き継ぐ）。
REVIEW_BOUNDARIES: Tuple[str, ...] = (
    "SHADOW_MODE: this queue is advice for a human reviewer, never a formal decision",
    "NOT_PREDICTIVE: shadow review measures analytical reconstruction, not forecasting accuracy",
    "NOT_FORMAL_APPROVAL: AGREE is not APPROVED and DISAGREE is not REJECTED",
    "HUMAN_FEEDBACK_ONLY: no shadow review outcome promotes anything to Compass DNA",
)


class ShadowReviewValidationError(ValueError):
    def __init__(self, errors: List[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_forbidden_keys(obj: Any, _found: Optional[set] = None) -> List[str]:
    """dict / list を**再帰的に**歩いて禁止 key を探す（string の substring 判定に頼らない）。"""
    found = _found if _found is not None else set()
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                found.add(str(key).lower())
            find_forbidden_keys(value, found)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            find_forbidden_keys(item, found)
    return sorted(found)


def assert_no_forbidden_keys(obj: Any, where: str) -> None:
    bad = find_forbidden_keys(obj)
    if bad:
        raise ShadowReviewValidationError([f"FORBIDDEN_KEY:{where}:{k}" for k in bad])


@dataclass(frozen=True)
class ShadowReviewEvent:
    """1 件の人間レビュー。append-only・不変。id は内容 hash（reviewed_at を含めない）。"""
    shadow_review_id: str
    pattern_id: str
    reviewed_at: str                                   # ISO-8601 UTC（id には含めない）
    reviewer_id: str
    reviewer_type: str                                 # HUMAN 固定（SYSTEM は拒否）
    review_outcome: str
    reason: str
    structured_reason: Mapping[str, Any]
    related_pattern_id: str
    recommendation_at_review: str
    axis_states_at_review: Mapping[str, str]
    axis_applicability_at_review: Mapping[str, str]
    reference_score_at_review: Optional[float]
    queue_rank_at_review: int
    queue_section_at_review: str
    material_digest_at_review: str
    evaluation_id: str
    inputs_digest: str
    lifecycle_at_review: str
    evaluation_policy_version: str
    evaluation_policy_digest: str
    recommendation_policy_version: str
    recommendation_policy_digest: str
    shadow_review_policy_version: str
    shadow_review_policy_digest: str
    corpus_size: int
    corpus_milestone: str
    shadow_mode: bool
    formal_review_gate_reached: bool
    schema_version: str = SCHEMA_VERSION
    sequence: int = 0                                  # store が append 時に付与（1 始まり・連番）
    previous_record_hash: str = ""
    record_hash: str = ""

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, Mapping):
                v = dict(v)
            elif isinstance(v, tuple):
                v = list(v)
            out[f.name] = v
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowReviewEvent":
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in dict(data).items() if k in names}
        for key in ("structured_reason", "axis_states_at_review", "axis_applicability_at_review"):
            kw[key] = dict(kw.get(key) or {})
        return cls(**kw)


def shadow_review_id_for(payload: Mapping[str, Any]) -> str:
    """deterministic id。同じ内容の再送は同じ id → store 側で冪等に扱える（reviewed_at は含めない）。"""
    seed = canonical_json({
        "pattern_id": payload.get("pattern_id"),
        "reviewer_id": payload.get("reviewer_id"),
        "review_outcome": payload.get("review_outcome"),
        "reason": payload.get("reason"),
        "structured_reason": dict(payload.get("structured_reason") or {}),
        "related_pattern_id": payload.get("related_pattern_id"),
        "material_digest_at_review": payload.get("material_digest_at_review"),
        "evaluation_id": payload.get("evaluation_id"),
        "shadow_review_policy_digest": payload.get("shadow_review_policy_digest"),
        "schema_version": SCHEMA_VERSION,
    })
    return EVENT_ID_PREFIX + sha256_hex(seed)[:16]


def record_hash_for(row: Mapping[str, Any]) -> str:
    """record_hash を除いた全 field の hash（chain 用）。"""
    view = {k: v for k, v in dict(row).items() if k != "record_hash"}
    return sha256_hex(canonical_json(view))


def validate_event(row: Mapping[str, Any], policy: Optional[ShadowReviewPolicy] = None,
                   allow_unsealed: bool = False) -> List[str]:
    """schema-level validation（error code の list。空 = valid）。"""
    errors: List[str] = []
    if not isinstance(row, Mapping):
        return ["EVENT_NOT_OBJECT"]
    missing = sorted({f.name for f in fields(ShadowReviewEvent)} - set(row.keys()))
    if missing:
        return ["MISSING_FIELDS:" + ",".join(missing)]
    if str(row["schema_version"]) != SCHEMA_VERSION:
        errors.append("SCHEMA_VERSION_MISMATCH")
    if not str(row["shadow_review_id"]).startswith(EVENT_ID_PREFIX):
        errors.append("SHADOW_REVIEW_ID_FORMAT")
    if not str(row["pattern_id"]).strip():
        errors.append("PATTERN_ID_MISSING")
    if row["review_outcome"] not in OUTCOMES:
        errors.append("REVIEW_OUTCOME_UNKNOWN")
    if row["reviewer_type"] != REVIEWER_TYPE_HUMAN:
        errors.append("REVIEWER_TYPE_MUST_BE_HUMAN")
    if not str(row["reviewer_id"]).strip():
        errors.append("REVIEWER_ID_MISSING")
    if row["recommendation_at_review"] not in RECOMMENDATION_STATES:
        errors.append("RECOMMENDATION_AT_REVIEW_UNKNOWN")
    if row["queue_section_at_review"] not in SECTIONS:
        errors.append("QUEUE_SECTION_UNKNOWN")
    if not isinstance(row["queue_rank_at_review"], int) or row["queue_rank_at_review"] < 0:
        errors.append("QUEUE_RANK_INVALID")
    if not str(row["material_digest_at_review"]).strip():
        errors.append("MATERIAL_DIGEST_MISSING")
    if not str(row["shadow_review_policy_digest"]).strip():
        errors.append("SHADOW_REVIEW_POLICY_DIGEST_MISSING")
    if not str(row["evaluation_policy_digest"]).strip() or not str(row["recommendation_policy_digest"]).strip():
        errors.append("POLICY_DIGEST_MISSING")
    score = row["reference_score_at_review"]
    if score is not None and (not isinstance(score, (int, float)) or not 0 <= float(score) <= 100):
        errors.append("REFERENCE_SCORE_INVALID")
    structured = row["structured_reason"] or {}
    if not isinstance(structured, Mapping):
        errors.append("STRUCTURED_REASON_NOT_OBJECT")
    else:
        for cat in structured.get("missing") or []:
            if str(cat) not in MISSING_CATEGORIES:
                errors.append(f"MISSING_CATEGORY_UNKNOWN:{cat}")
    if not allow_unsealed:
        if not isinstance(row["sequence"], int) or row["sequence"] < 1:
            errors.append("SEQUENCE_INVALID")
        if not str(row["record_hash"]).strip():
            errors.append("RECORD_HASH_MISSING")
        elif record_hash_for(row) != row["record_hash"]:
            errors.append("RECORD_HASH_MISMATCH")
    errors.extend(f"FORBIDDEN_KEY:{k}" for k in find_forbidden_keys(row))
    if policy is not None:
        errors.extend(validate_reason(row, policy))
    return errors


def validate_reason(row: Mapping[str, Any], policy: ShadowReviewPolicy) -> List[str]:
    """§12 の理由要件。満たさない書き込みは fail closed。"""
    from .config import REQ_OPTIONAL, REQ_REQUIRED, REQ_REQUIRED_STRUCTURED, REQ_REQUIRED_WITH_REFERENCE

    outcome = str(row.get("review_outcome", ""))
    requirement = policy.reason_requirements.get(outcome)
    if requirement is None:
        return [f"REASON_REQUIREMENT_MISSING:{outcome}"]
    errors: List[str] = []
    reason = str(row.get("reason") or "").strip()
    structured = dict(row.get("structured_reason") or {})
    related = str(row.get("related_pattern_id") or "").strip()
    if requirement == REQ_OPTIONAL:
        return errors
    if requirement in (REQ_REQUIRED, REQ_REQUIRED_WITH_REFERENCE) and len(reason) < policy.min_reason_chars:
        errors.append("REASON_REQUIRED")
    if requirement == REQ_REQUIRED_WITH_REFERENCE:
        if not related:
            errors.append("RELATED_PATTERN_ID_REQUIRED")
        elif related == str(row.get("pattern_id") or ""):
            errors.append("RELATED_PATTERN_ID_MUST_DIFFER")
    if requirement == REQ_REQUIRED_STRUCTURED:
        categories = [str(c) for c in (structured.get("missing") or [])]
        if not categories:
            errors.append("STRUCTURED_REASON_REQUIRED")
        for cat in categories:
            if cat not in MISSING_CATEGORIES:
                errors.append(f"MISSING_CATEGORY_UNKNOWN:{cat}")
    return errors


@dataclass(frozen=True)
class ReviewCard:
    """queue に出す 1 枚。JSON を読まずに「なぜ今これを見せられているか」が分かること。"""
    queue_rank: int
    queue_section: str
    pattern_id: str
    pattern_type: str
    lifecycle_status: str
    recommendation: str
    why_surfaced: str
    axes: Mapping[str, Mapping[str, str]]
    reference_score: Optional[float]
    reference_score_comparable: bool
    evidence: Mapping[str, Any]
    relations: Mapping[str, Any]
    rules: Mapping[str, Any]
    governance: Mapping[str, Any]
    history: Mapping[str, Any]
    supporting_document_dates: Tuple[str, ...] = ()
    supporting_document_ids: Tuple[str, ...] = ()
    material_digest: str = ""
    evaluation_id: str = ""
    inputs_digest: str = ""
    limitations: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, Mapping):
                v = dict(v)
            elif isinstance(v, tuple):
                v = list(v)
            out[f.name] = v
        return out
