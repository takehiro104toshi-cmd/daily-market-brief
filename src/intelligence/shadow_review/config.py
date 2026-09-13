"""Shadow Review policy（Phase 3.9.3）— config.yaml `compass_shadow_review`。

frozen spec（PHASE_3_9_3_SPEC_FROZEN）を config へ外出しする。threshold・cooldown・型順序は
すべて config 由来（magic number をコードへ埋めない）。versioned + content digest で、同じ
policy_version のまま内容が変われば `ShadowReviewPolicyError`（fail closed。silent な review
policy drift を許さない）。

digest 規約は Phase 3.9.2 と同じ「canonical JSON の sha256 先頭 16 桁」を踏襲する
（プロジェクト内で digest の読み方を 1 つに保つため）。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from ..evaluation.config import PATTERN_TYPES
from ..evaluation.models import RECOMMENDATION_STATES

CONFIG_SECTION = "compass_shadow_review"

# --- queue section ---------------------------------------------------------
SECTION_MAIN = "MAIN"
SECTION_ADVERSE_OVERFLOW = "ADVERSE_OVERFLOW"
SECTION_BACKLOG = "BACKLOG"
SECTION_WATCH = "WATCH"
SECTIONS: Tuple[str, ...] = (SECTION_MAIN, SECTION_ADVERSE_OVERFLOW, SECTION_BACKLOG, SECTION_WATCH)

# --- shadow review outcome（Decision state とも Recommendation state とも交差しない）---
AGREE = "AGREE"
DISAGREE = "DISAGREE"
NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
UNCLEAR = "UNCLEAR"
DUPLICATE_OR_OVERLAPPING = "DUPLICATE_OR_OVERLAPPING"
NOT_ACTIONABLE = "NOT_ACTIONABLE"
OUTCOMES: Tuple[str, ...] = (AGREE, DISAGREE, NEEDS_MORE_EVIDENCE, UNCLEAR,
                             DUPLICATE_OR_OVERLAPPING, NOT_ACTIONABLE)

#: Phase 3.9.1 Decision state の語彙（**import せず**ここに写す。decision package と結合しないため）。
#: 実体との一致は test で検証する（drift したら test が落ちる）。
RESERVED_DECISION_STATES: Tuple[str, ...] = ("KEEP_REVIEWING", "APPROVED", "REJECTED",
                                             "REOPENED_FOR_REVIEW", "SUPERSEDED", "RETIRED")
#: Phase 3.8 review queue の status 語彙。
RESERVED_RESEARCH_QUEUE_STATES: Tuple[str, ...] = ("OPEN",)

# --- reason requirement ----------------------------------------------------
REQ_OPTIONAL = "OPTIONAL"
REQ_REQUIRED = "REQUIRED"
REQ_REQUIRED_STRUCTURED = "REQUIRED_STRUCTURED"
REQ_REQUIRED_WITH_REFERENCE = "REQUIRED_WITH_REFERENCE"
REASON_REQUIREMENTS: Tuple[str, ...] = (REQ_OPTIONAL, REQ_REQUIRED, REQ_REQUIRED_STRUCTURED,
                                        REQ_REQUIRED_WITH_REFERENCE)

MISSING_MORE_DOCUMENTS = "MORE_DOCUMENTS"
MISSING_MORE_REGIMES = "MORE_REGIMES"
MISSING_LONGER_SPAN = "LONGER_SPAN"
MISSING_BETTER_QUALITY = "BETTER_QUALITY"
MISSING_CATEGORIES: Tuple[str, ...] = (MISSING_MORE_DOCUMENTS, MISSING_MORE_REGIMES,
                                       MISSING_LONGER_SPAN, MISSING_BETTER_QUALITY)

REVIEWER_TYPE_HUMAN = "HUMAN"
REVIEWER_TYPE_SYSTEM = "SYSTEM"          # 受け付けない（定数は拒否判定のためだけに存在する）

MODE_ROUND_ROBIN_WITH_CAP = "ROUND_ROBIN_WITH_CAP"

#: ranking の凍結順序（§5）。config で並べ替えられないことを validate で担保する。
FROZEN_RANKING_ORDER: Tuple[str, ...] = ("high_axis_count", "reference_score", "relative_support_share",
                                         "eligible_support", "span_days", "pattern_id")
#: material digest に**入れてはならない** field（Reference Score が再レビューを駆動しないための担保）。
FORBIDDEN_MATERIAL_FIELDS: Tuple[str, ...] = ("reference_score", "relative_support_share",
                                              "span_days", "confirmed_3d_cells")
#: cooldown の 0 は「時間では戻さない（material change のみ）」を意味する。数値 0 = cooldown 無しではない。
MATERIAL_CHANGE_ONLY = 0

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class ShadowReviewPolicyError(ValueError):
    """policy が frozen 仕様に反する / 同一 version で内容が変わった（fail closed）。"""


def _digest(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ShadowReviewPolicy:
    """queue / cooldown / reason 要件の frozen policy。"""
    policy_version: str = "1.0.0"
    top_n: int = 8
    watch_n: int = 0                                   # v1 は 0（WATCH 機構はあるが既定で空）
    state_priority: Tuple[str, ...] = ("REJECT_RECOMMENDED", "APPROVE_RECOMMENDED", "REVIEW_RECOMMENDED")
    excluded_states: Tuple[str, ...] = ("NOT_READY",)
    watch_source_state: str = "KEEP_REVIEWING"
    watch_excluded_lifecycles: Tuple[str, ...] = ("OBSERVED",)
    ranking_order: Tuple[str, ...] = FROZEN_RANKING_ORDER
    diversity_mode: str = MODE_ROUND_ROBIN_WITH_CAP
    diversity_bypass_states: Tuple[str, ...] = ("REJECT_RECOMMENDED", "APPROVE_RECOMMENDED")
    type_order: Tuple[str, ...] = ("EVIDENCE_OUTLOOK", "STATE_OUTLOOK", "THEME_OUTLOOK",
                                   "EVIDENCE_WHY", "EVIDENCE_RISK", "FULL")
    type_caps: Mapping[str, int] = field(default_factory=lambda: {"EVIDENCE_WHY": 3, "EVIDENCE_RISK": 3})
    cooldowns: Mapping[str, int] = field(default_factory=lambda: {
        AGREE: 30, DISAGREE: MATERIAL_CHANGE_ONLY, NEEDS_MORE_EVIDENCE: MATERIAL_CHANGE_ONLY,
        UNCLEAR: 14, DUPLICATE_OR_OVERLAPPING: 90, NOT_ACTIONABLE: 90})
    adverse_cooldown_cap: int = 7
    material_change_fields: Tuple[str, ...] = ("recommendation", "axis_states", "axis_applicability",
                                               "eligible_support", "distinct_2d_cells", "contradiction",
                                               "lifecycle", "evaluation_policy_digest",
                                               "recommendation_policy_digest")
    material_change_excluded: Tuple[str, ...] = FORBIDDEN_MATERIAL_FIELDS
    review_outcomes: Tuple[str, ...] = OUTCOMES
    reason_requirements: Mapping[str, str] = field(default_factory=lambda: {
        AGREE: REQ_OPTIONAL, DISAGREE: REQ_REQUIRED, NEEDS_MORE_EVIDENCE: REQ_REQUIRED_STRUCTURED,
        UNCLEAR: REQ_REQUIRED, DUPLICATE_OR_OVERLAPPING: REQ_REQUIRED_WITH_REFERENCE,
        NOT_ACTIONABLE: REQ_REQUIRED})
    min_reason_chars: int = 10
    show_supporting_document_dates: bool = True
    default_reviewer_id: str = "SUPERVISOR"
    allowed_reviewer_types: Tuple[str, ...] = (REVIEWER_TYPE_HUMAN,)
    auto_decision_write: bool = False                  # 常に False（True は PolicyError）
    auto_promotion: bool = False                       # 常に False（True は PolicyError）

    def as_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "top_n": self.top_n, "watch_n": self.watch_n,
            "state_priority": list(self.state_priority),
            "excluded_states": list(self.excluded_states),
            "watch_source_state": self.watch_source_state,
            "watch_excluded_lifecycles": list(self.watch_excluded_lifecycles),
            "ranking_order": list(self.ranking_order),
            "type_diversity": {"mode": self.diversity_mode,
                               "bypass_states": list(self.diversity_bypass_states),
                               "type_order": list(self.type_order),
                               "type_caps": {str(k): int(v) for k, v in sorted(self.type_caps.items())}},
            "cooldowns": {str(k): int(v) for k, v in sorted(self.cooldowns.items())},
            "adverse_cooldown_cap": self.adverse_cooldown_cap,
            "material_change_fields": list(self.material_change_fields),
            "material_change_excluded": list(self.material_change_excluded),
            "review_outcomes": list(self.review_outcomes),
            "reason_requirements": {str(k): str(v) for k, v in sorted(self.reason_requirements.items())},
            "min_reason_chars": self.min_reason_chars,
            "show_supporting_document_dates": self.show_supporting_document_dates,
            "default_reviewer_id": self.default_reviewer_id,
            "allowed_reviewer_types": list(self.allowed_reviewer_types),
            "auto_decision_write": self.auto_decision_write,
            "auto_promotion": self.auto_promotion,
        }

    def digest(self) -> str:
        return _digest(self.as_dict())

    def cooldown_days(self, outcome: str) -> int:
        return int(self.cooldowns.get(outcome, MATERIAL_CHANGE_ONLY))

    def type_cap(self, pattern_type: str) -> int:
        try:
            return int(self.type_caps[pattern_type])
        except (KeyError, TypeError, ValueError):
            return 10 ** 9                             # cap 未設定 = 実質無制限（round-robin が抑える）

    def validate(self) -> None:  # noqa: C901 fail-closed の条件は 1 箇所に集める
        if not _SEMVER.match(self.policy_version or ""):
            raise ShadowReviewPolicyError(f"policy_version must be semver: {self.policy_version!r}")
        if self.auto_decision_write:
            raise ShadowReviewPolicyError("Shadow Review must never write a formal Decision")
        if self.auto_promotion:
            raise ShadowReviewPolicyError("Shadow Review must never promote a pattern to Compass DNA")
        if self.top_n < 1:
            raise ShadowReviewPolicyError("top_n must be >= 1")
        if self.watch_n < 0:
            raise ShadowReviewPolicyError("watch_n must be >= 0")
        if self.min_reason_chars < 1:
            raise ShadowReviewPolicyError("min_reason_chars must be >= 1")
        if self.adverse_cooldown_cap < 0:
            raise ShadowReviewPolicyError("adverse_cooldown_cap must be >= 0")
        if self.diversity_mode != MODE_ROUND_ROBIN_WITH_CAP:
            raise ShadowReviewPolicyError(f"type_diversity.mode is frozen: {MODE_ROUND_ROBIN_WITH_CAP}")
        if tuple(self.ranking_order) != FROZEN_RANKING_ORDER:
            raise ShadowReviewPolicyError(f"ranking_order is frozen: {list(FROZEN_RANKING_ORDER)}")
        # --- outcome 語彙（Decision / Recommendation / Phase 3.8 queue と交差禁止）---
        if tuple(self.review_outcomes) != OUTCOMES:
            raise ShadowReviewPolicyError(f"review_outcomes is frozen: {list(OUTCOMES)}")
        reserved = set(RESERVED_DECISION_STATES) | set(RECOMMENDATION_STATES) | set(RESERVED_RESEARCH_QUEUE_STATES)
        clash = sorted(set(self.review_outcomes) & reserved)
        if clash:
            raise ShadowReviewPolicyError(
                "review_outcomes must not reuse Decision / Recommendation / research queue vocabulary: "
                + ",".join(clash))
        # --- reviewer ---
        if REVIEWER_TYPE_SYSTEM in self.allowed_reviewer_types:
            raise ShadowReviewPolicyError("allowed_reviewer_types must never contain SYSTEM")
        if tuple(self.allowed_reviewer_types) != (REVIEWER_TYPE_HUMAN,):
            raise ShadowReviewPolicyError("allowed_reviewer_types is frozen: ['HUMAN']")
        if not str(self.default_reviewer_id).strip():
            raise ShadowReviewPolicyError("default_reviewer_id must not be empty")
        # --- state 語彙 ---
        for name, states in (("state_priority", self.state_priority),
                             ("excluded_states", self.excluded_states),
                             ("type_diversity.bypass_states", self.diversity_bypass_states)):
            for s in states:
                if s not in RECOMMENDATION_STATES:
                    raise ShadowReviewPolicyError(f"unknown recommendation state in {name}: {s}")
        for banned in ("NOT_READY", "KEEP_REVIEWING"):
            if banned in self.state_priority:
                raise ShadowReviewPolicyError(f"{banned} must never enter the main queue priority")
        if self.watch_source_state not in RECOMMENDATION_STATES:
            raise ShadowReviewPolicyError(f"unknown watch_source_state: {self.watch_source_state}")
        if self.watch_source_state in self.state_priority:
            raise ShadowReviewPolicyError("watch_source_state must stay outside the main queue")
        # --- pattern type 語彙 ---
        for t in tuple(self.type_order) + tuple(self.type_caps):
            if t not in PATTERN_TYPES:
                raise ShadowReviewPolicyError(f"unknown pattern type: {t}")
        if any(int(v) < 1 for v in self.type_caps.values()):
            raise ShadowReviewPolicyError("type_caps must be >= 1")
        # --- outcome ごとの設定 ---
        for name, mapping in (("cooldowns", self.cooldowns), ("reason_requirements", self.reason_requirements)):
            missing = sorted(set(OUTCOMES) - set(mapping))
            if missing:
                raise ShadowReviewPolicyError(f"{name} must cover every outcome; missing: {','.join(missing)}")
            unknown = sorted(set(mapping) - set(OUTCOMES))
            if unknown:
                raise ShadowReviewPolicyError(f"unknown outcome in {name}: {','.join(unknown)}")
        if any(int(v) < 0 for v in self.cooldowns.values()):
            raise ShadowReviewPolicyError("cooldowns must be >= 0 (0 means material-change-only)")
        for outcome, req in self.reason_requirements.items():
            if req not in REASON_REQUIREMENTS:
                raise ShadowReviewPolicyError(f"unknown reason requirement for {outcome}: {req}")
        # --- material change（Reference Score が再レビューを駆動しないことの担保）---
        bad = sorted(set(self.material_change_fields) & set(FORBIDDEN_MATERIAL_FIELDS))
        if bad:
            raise ShadowReviewPolicyError(
                "material_change_fields must never contain score/volatile fields: " + ",".join(bad))
        missing_excluded = sorted(set(FORBIDDEN_MATERIAL_FIELDS) - set(self.material_change_excluded))
        if missing_excluded:
            raise ShadowReviewPolicyError(
                "material_change_excluded must list every excluded field; missing: " + ",".join(missing_excluded))
        if not self.material_change_fields:
            raise ShadowReviewPolicyError("material_change_fields must not be empty")


# ------------------------------------------------------------------- loading
def _section(config_path: Path, name: str) -> Mapping[str, Any]:
    if not config_path.is_file():
        return {}
    try:
        import yaml

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return raw.get(name) or {}
    except Exception:  # noqa: BLE001 設定破損 → 既定（frozen）値へ
        return {}


def _tuple(section: Mapping[str, Any], key: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    value = section.get(key)
    if value is None:
        return default
    if not isinstance(value, (list, tuple)):
        raise ShadowReviewPolicyError(f"{key} must be a list")
    return tuple(str(v) for v in value)


def _int(section: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(section.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ShadowReviewPolicyError(f"{key} must be an integer: {exc}") from exc


def _flag(section: Mapping[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def shadow_review_policy_from_mapping(section: Optional[Mapping[str, Any]]) -> ShadowReviewPolicy:
    s = dict(section or {})
    base = ShadowReviewPolicy()
    div = dict(s.get("type_diversity") or {})
    cooldowns = dict(s.get("cooldowns") or base.cooldowns)
    reasons = dict(s.get("reason_requirements") or base.reason_requirements)
    caps = dict(div.get("type_caps") or base.type_caps)
    try:
        caps = {str(k): int(v) for k, v in caps.items()}
        cooldowns = {str(k): int(v) for k, v in cooldowns.items()}
    except (TypeError, ValueError) as exc:
        raise ShadowReviewPolicyError(f"type_caps / cooldowns must be integers: {exc}") from exc
    policy = ShadowReviewPolicy(
        policy_version=str(s.get("policy_version", base.policy_version) or base.policy_version),
        top_n=_int(s, "top_n", base.top_n),
        watch_n=_int(s, "watch_n", base.watch_n),
        state_priority=_tuple(s, "state_priority", base.state_priority),
        excluded_states=_tuple(s, "excluded_states", base.excluded_states),
        watch_source_state=str(s.get("watch_source_state", base.watch_source_state)),
        watch_excluded_lifecycles=_tuple(s, "watch_excluded_lifecycles", base.watch_excluded_lifecycles),
        ranking_order=_tuple(s, "ranking_order", base.ranking_order),
        diversity_mode=str(div.get("mode", base.diversity_mode)),
        diversity_bypass_states=_tuple(div, "bypass_states", base.diversity_bypass_states),
        type_order=_tuple(div, "type_order", base.type_order),
        type_caps=caps,
        cooldowns=cooldowns,
        adverse_cooldown_cap=_int(s, "adverse_cooldown_cap", base.adverse_cooldown_cap),
        material_change_fields=_tuple(s, "material_change_fields", base.material_change_fields),
        material_change_excluded=_tuple(s, "material_change_excluded", base.material_change_excluded),
        review_outcomes=_tuple(s, "review_outcomes", base.review_outcomes),
        reason_requirements={str(k): str(v) for k, v in reasons.items()},
        min_reason_chars=_int(s, "min_reason_chars", base.min_reason_chars),
        show_supporting_document_dates=_flag(s, "show_supporting_document_dates",
                                             base.show_supporting_document_dates),
        default_reviewer_id=str(s.get("default_reviewer_id", base.default_reviewer_id)
                                or base.default_reviewer_id),
        allowed_reviewer_types=_tuple(s, "allowed_reviewer_types", base.allowed_reviewer_types),
        auto_decision_write=_flag(s, "auto_decision_write", base.auto_decision_write),
        auto_promotion=_flag(s, "auto_promotion", base.auto_promotion))
    policy.validate()
    return policy


def load_shadow_review_policy(config_path: Path = Path("config.yaml")) -> ShadowReviewPolicy:
    return shadow_review_policy_from_mapping(_section(config_path, CONFIG_SECTION))
