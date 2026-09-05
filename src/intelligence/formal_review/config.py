"""Formal review policy（Phase 3.9.5）— config.yaml `compass_formal_review`。versioned・digest・fail closed。

凍結事項（値を変えるには policy_version を上げる。同 version で digest が変わる run は拒否）:
- recommendation symmetry: APPROVED は APPROVE_RECOMMENDED のみ、REJECTED は REJECT_RECOMMENDED のみ
- batch action なし / promotion は常に NOT_PROMOTED / 重複・重なりは KEEP_REVIEWING + metadata
- sibling guard: EVIDENCE_OUTLOOK narrow sibling のみ（C1 hard block・C3 acknowledgement）
- packet freshness anchor は packet_evidence_digest（corpus 増加だけでは stale にしない）
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .errors import FormalReviewPolicyError

CONFIG_SECTION = "compass_formal_review"
PACKET_SCHEMA_VERSION = "1.0.0"

# 決定 state（Phase 3.9.1 の語彙。import せず写し、test で一致を検証する）
APPROVED = "APPROVED"
REJECTED = "REJECTED"
KEEP_REVIEWING = "KEEP_REVIEWING"
REOPENED_FOR_REVIEW = "REOPENED_FOR_REVIEW"
SUPERSEDED = "SUPERSEDED"
RETIRED = "RETIRED"
DECISION_STATES: Tuple[str, ...] = (KEEP_REVIEWING, APPROVED, REJECTED, REOPENED_FOR_REVIEW, SUPERSEDED, RETIRED)

# CLI action → decision_type
ACTIONS: Dict[str, str] = {"approve": APPROVED, "reject": REJECTED, "keep-reviewing": KEEP_REVIEWING,
                           "reopen": REOPENED_FOR_REVIEW, "supersede": SUPERSEDED, "retire": RETIRED}

STABILITY_RANK: Tuple[str, ...] = ("STABLE", "MOSTLY_STABLE", "RECENT_TRANSITION", "INSUFFICIENT_HISTORY", "OSCILLATING")
REJECT_ORDERING: Tuple[str, ...] = ("first_reject_position", "reject_persistence_ratio_desc", "eligible_support_desc",
                                    "pattern_id")
APPROVE_ORDERING: Tuple[str, ...] = ("stability_rank", "first_approve_position", "eligible_support_desc", "span_days_desc",
                                     "pattern_id")
REOPEN_ORDERING: Tuple[str, ...] = ("first_reject_position", "pattern_id")

SIBLING_GUARD_MODE = "C1_HARD_BLOCK_C3_ACKNOWLEDGE"
SIBLING_RELATION = "EVIDENCE_OUTLOOK_NARROW_SIBLING"
FRESHNESS_ANCHOR = "packet_evidence_digest"
DUPLICATE_DISPOSITION = "KEEP_REVIEWING_WITH_METADATA"
DISPOSITION_DUPLICATE = "DUPLICATE_OR_OVERLAPPING"
PROMOTION_BOUNDARY = "NOT_PROMOTED"
REASON_CATEGORIES: Tuple[str, ...] = ("MORE_DOCUMENTS", "MORE_REGIMES", "LONGER_SPAN", "BETTER_QUALITY")

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _digest(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class FormalReviewPolicy:
    policy_version: str = "1.0.0"
    packet_schema_version: str = PACKET_SCHEMA_VERSION
    recommendation_symmetry: bool = True
    sibling_guard_mode: str = SIBLING_GUARD_MODE
    sibling_relation: str = SIBLING_RELATION
    replay_evidence_required_for: Tuple[str, ...] = (APPROVED, REJECTED)
    replay_evidence_age_warning_eligible_docs: int = 5
    freshness_anchor: str = FRESHNESS_ANCHOR
    stale_on_corpus_growth: bool = False
    require_recommendation_match: bool = True
    min_reason_chars: Mapping[str, int] = None  # type: ignore[assignment]  # set in __post_init__
    reason_categories: Tuple[str, ...] = REASON_CATEGORIES
    duplicate_disposition: str = DUPLICATE_DISPOSITION
    batch_actions_allowed: bool = False
    promotion_boundary: str = PROMOTION_BOUNDARY
    stability_rank: Tuple[str, ...] = STABILITY_RANK
    reject_ordering: Tuple[str, ...] = REJECT_ORDERING
    approve_ordering: Tuple[str, ...] = APPROVE_ORDERING
    reopen_ordering: Tuple[str, ...] = REOPEN_ORDERING
    warn_recent_transition: bool = True
    warn_oscillating: bool = True
    warn_insufficient_history: bool = True

    def __post_init__(self) -> None:
        if self.min_reason_chars is None:
            object.__setattr__(self, "min_reason_chars", {APPROVED: 20, REJECTED: 20, KEEP_REVIEWING: 10,
                                                          REOPENED_FOR_REVIEW: 20, SUPERSEDED: 20, RETIRED: 20})

    def as_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version, "packet_schema_version": self.packet_schema_version,
            "recommendation_symmetry": self.recommendation_symmetry,
            "sibling_guard": {"mode": self.sibling_guard_mode, "relation": self.sibling_relation},
            "replay_evidence": {"required_for": list(self.replay_evidence_required_for),
                                "age_warning_eligible_docs": self.replay_evidence_age_warning_eligible_docs},
            "freshness": {"anchor": self.freshness_anchor, "stale_on_corpus_growth": self.stale_on_corpus_growth,
                          "require_recommendation_match": self.require_recommendation_match},
            "reason": {"min_chars": {k: int(v) for k, v in sorted(dict(self.min_reason_chars).items())},
                       "categories": list(self.reason_categories)},
            "duplicate_disposition": self.duplicate_disposition,
            "batch_actions_allowed": self.batch_actions_allowed,
            "promotion_boundary": self.promotion_boundary,
            "ordering": {"stability_rank": list(self.stability_rank), "reject": list(self.reject_ordering),
                         "approve": list(self.approve_ordering), "reopen": list(self.reopen_ordering)},
            "warnings": {"recent_transition": self.warn_recent_transition, "oscillating": self.warn_oscillating,
                         "insufficient_history": self.warn_insufficient_history},
        }

    def digest(self) -> str:
        return _digest(self.as_dict())

    def validate(self) -> None:
        if not _SEMVER.match(self.policy_version or ""):
            raise FormalReviewPolicyError(f"policy_version must be semver: {self.policy_version!r}")
        if not _SEMVER.match(self.packet_schema_version or ""):
            raise FormalReviewPolicyError("packet_schema_version must be semver")
        if self.recommendation_symmetry is not True:
            raise FormalReviewPolicyError("recommendation_symmetry is frozen: APPROVED only for APPROVE_RECOMMENDED, "
                                          "REJECTED only for REJECT_RECOMMENDED")
        if self.sibling_guard_mode != SIBLING_GUARD_MODE or self.sibling_relation != SIBLING_RELATION:
            raise FormalReviewPolicyError("sibling guard is frozen in v1 (C1 hard block, C3 acknowledgement, "
                                          "EVIDENCE_OUTLOOK narrow sibling only)")
        if set(self.replay_evidence_required_for) != {APPROVED, REJECTED}:
            raise FormalReviewPolicyError("replay evidence is required exactly for APPROVED and REJECTED")
        if int(self.replay_evidence_age_warning_eligible_docs) < 1:
            raise FormalReviewPolicyError("replay_evidence_age_warning_eligible_docs must be >= 1")
        if self.freshness_anchor != FRESHNESS_ANCHOR or self.stale_on_corpus_growth is not False \
                or self.require_recommendation_match is not True:
            raise FormalReviewPolicyError("freshness rules are frozen: packet_evidence_digest anchor, corpus growth "
                                          "alone never stales, recommendation must match")
        for state in DECISION_STATES:
            if state not in self.min_reason_chars:
                raise FormalReviewPolicyError(f"min_reason_chars missing for {state}")
        for state, floor in ((APPROVED, 20), (REJECTED, 20), (KEEP_REVIEWING, 10), (REOPENED_FOR_REVIEW, 20),
                             (SUPERSEDED, 20), (RETIRED, 20)):
            if int(self.min_reason_chars[state]) < floor:
                raise FormalReviewPolicyError(f"min_reason_chars[{state}] must be >= {floor}")
        if tuple(self.reason_categories) != REASON_CATEGORIES:
            raise FormalReviewPolicyError("reason_categories are frozen (shadow review structured categories)")
        if self.duplicate_disposition != DUPLICATE_DISPOSITION:
            raise FormalReviewPolicyError("duplicate/overlap disposition is frozen: KEEP_REVIEWING with metadata")
        if self.batch_actions_allowed is not False:
            raise FormalReviewPolicyError("batch actions are never allowed")
        if self.promotion_boundary != PROMOTION_BOUNDARY:
            raise FormalReviewPolicyError("promotion boundary is frozen: every formal decision stays NOT_PROMOTED")
        if tuple(self.stability_rank) != STABILITY_RANK or tuple(self.reject_ordering) != REJECT_ORDERING \
                or tuple(self.approve_ordering) != APPROVE_ORDERING or tuple(self.reopen_ordering) != REOPEN_ORDERING:
            raise FormalReviewPolicyError("ordering is frozen in v1")


def _flag(section: Mapping[str, Any], key: str, default: bool) -> bool:
    raw = section.get(key, default)
    if isinstance(raw, str):
        return raw.strip().lower() in ("true", "1", "yes")
    return bool(raw)


def formal_review_policy_from_mapping(section: Optional[Mapping[str, Any]]) -> FormalReviewPolicy:
    s = dict(section or {})
    base = FormalReviewPolicy()
    sib = dict(s.get("sibling_guard") or {})
    rep = dict(s.get("replay_evidence") or {})
    fresh = dict(s.get("freshness") or {})
    reason = dict(s.get("reason") or {})
    ordering = dict(s.get("ordering") or {})
    warnings = dict(s.get("warnings") or {})
    min_chars = dict(base.min_reason_chars)
    for k, v in dict(reason.get("min_chars") or {}).items():
        try:
            min_chars[str(k)] = int(v)
        except (TypeError, ValueError) as exc:
            raise FormalReviewPolicyError(f"reason.min_chars[{k}] must be an integer") from exc
    try:
        age = int(rep.get("age_warning_eligible_docs", base.replay_evidence_age_warning_eligible_docs))
    except (TypeError, ValueError) as exc:
        raise FormalReviewPolicyError("replay_evidence.age_warning_eligible_docs must be an integer") from exc
    policy = FormalReviewPolicy(
        policy_version=str(s.get("policy_version", base.policy_version) or base.policy_version),
        packet_schema_version=str(s.get("packet_schema_version", base.packet_schema_version)),
        recommendation_symmetry=_flag(s, "recommendation_symmetry", base.recommendation_symmetry),
        sibling_guard_mode=str(sib.get("mode", base.sibling_guard_mode)),
        sibling_relation=str(sib.get("relation", base.sibling_relation)),
        replay_evidence_required_for=tuple(str(x) for x in (rep.get("required_for") or base.replay_evidence_required_for)),
        replay_evidence_age_warning_eligible_docs=age,
        freshness_anchor=str(fresh.get("anchor", base.freshness_anchor)),
        stale_on_corpus_growth=_flag(fresh, "stale_on_corpus_growth", base.stale_on_corpus_growth),
        require_recommendation_match=_flag(fresh, "require_recommendation_match", base.require_recommendation_match),
        min_reason_chars=min_chars,
        reason_categories=tuple(str(x) for x in (reason.get("categories") or base.reason_categories)),
        duplicate_disposition=str(s.get("duplicate_disposition", base.duplicate_disposition)),
        batch_actions_allowed=_flag(s, "batch_actions_allowed", base.batch_actions_allowed),
        promotion_boundary=str(s.get("promotion_boundary", base.promotion_boundary)),
        stability_rank=tuple(str(x) for x in (ordering.get("stability_rank") or base.stability_rank)),
        reject_ordering=tuple(str(x) for x in (ordering.get("reject") or base.reject_ordering)),
        approve_ordering=tuple(str(x) for x in (ordering.get("approve") or base.approve_ordering)),
        reopen_ordering=tuple(str(x) for x in (ordering.get("reopen") or base.reopen_ordering)),
        warn_recent_transition=_flag(warnings, "recent_transition", base.warn_recent_transition),
        warn_oscillating=_flag(warnings, "oscillating", base.warn_oscillating),
        warn_insufficient_history=_flag(warnings, "insufficient_history", base.warn_insufficient_history),
    )
    policy.validate()
    return policy


def load_formal_review_policy(config_path: Path = Path("config.yaml")) -> FormalReviewPolicy:
    section: Mapping[str, Any] = {}
    if config_path.is_file():
        try:
            import yaml

            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            section = raw.get(CONFIG_SECTION) or {}
        except Exception:  # noqa: BLE001 設定ファイル破損 → 凍結既定値
            section = {}
    return formal_review_policy_from_mapping(section)
