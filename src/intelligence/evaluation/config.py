"""Evaluation / Recommendation policy（Phase 3.9.2）— config.yaml `compass_evaluation` / `compass_recommendation`。

frozen spec（PHASE_3_9_2_AXIS_SPEC_FROZEN / RECOMMENDATION_SPEC_FROZEN）を config へ外出しする。
すべての threshold と weight は config 由来（magic number をコードへ埋めない）。versioned + content digest。
同じ policy_version で内容が変わったら `PolicyError`（fail closed。silent な threshold 変更を許さない）。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

CONFIG_EVALUATION = "compass_evaluation"
CONFIG_RECOMMENDATION = "compass_recommendation"

LOW, MEDIUM, HIGH = "LOW", "MEDIUM", "HIGH"
AXIS_STATES: Tuple[str, ...] = (LOW, MEDIUM, HIGH)
RANK: Dict[str, int] = {LOW: 0, MEDIUM: 1, HIGH: 2}

A_STRENGTH = "evidence_strength"
A_TIME = "time_stability"
A_CROSS = "cross_regime"
A_CONSISTENCY = "evidence_consistency"
A_NOVELTY = "dna_novelty"
A_QUALITY = "data_quality"
#: 表示する 6 axis（data_quality は gate。score には入らない）
AXES: Tuple[str, ...] = (A_STRENGTH, A_TIME, A_CROSS, A_CONSISTENCY, A_NOVELTY, A_QUALITY)
#: recommendation の core axes（novelty は非 core、quality は gate）
CORE_AXES: Tuple[str, ...] = (A_STRENGTH, A_TIME, A_CROSS, A_CONSISTENCY)
#: score 対象（data_quality は unweighted gate）
SCORED_AXES: Tuple[str, ...] = (A_STRENGTH, A_TIME, A_CROSS, A_CONSISTENCY, A_NOVELTY)

T_FULL = "FULL"
T_EVIDENCE_OUTLOOK = "EVIDENCE_OUTLOOK"
T_STATE_OUTLOOK = "STATE_OUTLOOK"
T_THEME_OUTLOOK = "THEME_OUTLOOK"
T_EVIDENCE_WHY = "EVIDENCE_WHY"
T_EVIDENCE_RISK = "EVIDENCE_RISK"
PATTERN_TYPES: Tuple[str, ...] = (T_FULL, T_EVIDENCE_OUTLOOK, T_STATE_OUTLOOK, T_THEME_OUTLOOK,
                                  T_EVIDENCE_WHY, T_EVIDENCE_RISK)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class PolicyError(ValueError):
    """policy が frozen 仕様に反する / 同一 version で内容が変わった（fail closed）。"""


def _digest(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class EvaluationPolicy:
    """6 axis の frozen threshold。"""
    policy_version: str = "1.0.0"
    # Q15 evidence strength（canonical input = eligible_support）
    strength_low_max: int = 1
    strength_medium_max: int = 3
    strength_not_ranked_types: Tuple[str, ...] = (T_FULL,)
    relative_share_min_denominator: int = 30          # これ未満は NOT_APPLICABLE（順序付けにも使わない）
    # Q16 time stability
    time_medium_span_days: int = 14
    time_medium_months: int = 2
    time_high_span_days: int = 60
    time_high_months: int = 3
    # Q17 cross-regime（2D core / 3D confirmation）
    cross_core_dimensions: Tuple[str, ...] = ("equity_direction", "yen_direction")
    cross_confirm_dimensions: Tuple[str, ...] = ("equity_direction", "yen_direction", "us_rate_direction")
    cross_medium_cells: int = 2
    cross_high_cells: int = 3
    cross_high_support: int = 3
    cross_high_span_days: int = 30
    cross_high_confirmed_cells: int = 1
    cross_not_applicable_types: Tuple[str, ...] = (T_FULL, T_STATE_OUTLOOK)
    # Q18 evidence consistency
    consistency_committed_directions: Tuple[str, ...] = ("UP", "DOWN")
    consistency_soft_directions: Tuple[str, ...] = ("RANGE", "MIXED", "UNCERTAIN")
    consistency_high_min_support: int = 2
    # Q19 dna novelty（applicability = evidence >=1 AND target present）
    novelty_low_relations: Tuple[str, ...] = ("SAME", "CONDITIONAL")
    novelty_low_min_overlap: int = 1
    # Q20 data quality
    quality_medium_valid_ratio_floor: Decimal = Decimal("0.8")
    quality_blocking_document_qualities: Tuple[str, ...] = ("LIMITED_USE", "QUARANTINED")
    quality_degraded_document_qualities: Tuple[str, ...] = ("PARTIAL",)
    supported_structure_schema_versions: Tuple[str, ...] = ("1.0.0",)
    supported_analysis_versions: Tuple[str, ...] = ("1.0.0",)   # 空 tuple = 制限なし
    # reference score
    weights: Mapping[str, int] = field(default_factory=lambda: {
        A_STRENGTH: 30, A_TIME: 25, A_CROSS: 20, A_CONSISTENCY: 15, A_NOVELTY: 10})
    score_map: Mapping[str, int] = field(default_factory=lambda: {LOW: 0, MEDIUM: 50, HIGH: 100})
    applicable_weight_floor: int = 60
    # corpus gate（Phase 3.9.1 と同じ値。formal APPROVED はあちらが fail closed で守る）
    formal_review_min_corpus: int = 100

    def as_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "strength": {"low_max": self.strength_low_max, "medium_max": self.strength_medium_max,
                         "not_ranked_types": list(self.strength_not_ranked_types),
                         "relative_share_min_denominator": self.relative_share_min_denominator},
            "time": {"medium_span_days": self.time_medium_span_days, "medium_months": self.time_medium_months,
                     "high_span_days": self.time_high_span_days, "high_months": self.time_high_months},
            "cross_regime": {"core_dimensions": list(self.cross_core_dimensions),
                             "confirm_dimensions": list(self.cross_confirm_dimensions),
                             "medium_cells": self.cross_medium_cells, "high_cells": self.cross_high_cells,
                             "high_support": self.cross_high_support, "high_span_days": self.cross_high_span_days,
                             "high_confirmed_cells": self.cross_high_confirmed_cells,
                             "not_applicable_types": list(self.cross_not_applicable_types)},
            "consistency": {"committed_directions": list(self.consistency_committed_directions),
                            "soft_directions": list(self.consistency_soft_directions),
                            "high_min_support": self.consistency_high_min_support},
            "novelty": {"low_relations": list(self.novelty_low_relations),
                        "low_min_overlap": self.novelty_low_min_overlap},
            "quality": {"medium_valid_ratio_floor": str(self.quality_medium_valid_ratio_floor),
                        "blocking_document_qualities": list(self.quality_blocking_document_qualities),
                        "degraded_document_qualities": list(self.quality_degraded_document_qualities),
                        "supported_structure_schema_versions": list(self.supported_structure_schema_versions),
                        "supported_analysis_versions": list(self.supported_analysis_versions)},
            "score": {"weights": dict(self.weights), "map": dict(self.score_map),
                      "applicable_weight_floor": self.applicable_weight_floor},
            "formal_review_min_corpus": self.formal_review_min_corpus,
        }

    def digest(self) -> str:
        return _digest(self.as_dict())

    def validate(self) -> None:
        if not _SEMVER.match(self.policy_version or ""):
            raise PolicyError(f"policy_version must be semver: {self.policy_version!r}")
        if not 0 < self.strength_low_max < self.strength_medium_max:
            raise PolicyError("strength bands must satisfy 0 < low_max < medium_max")
        if self.time_medium_span_days > self.time_high_span_days or self.time_medium_months > self.time_high_months:
            raise PolicyError("time MEDIUM thresholds must not exceed HIGH thresholds")
        if self.cross_medium_cells >= self.cross_high_cells:
            raise PolicyError("cross_regime medium_cells must be below high_cells")
        if set(self.weights) != set(SCORED_AXES):
            raise PolicyError(f"weights must cover exactly {list(SCORED_AXES)}")
        if any(int(v) < 0 for v in self.weights.values()) or sum(int(v) for v in self.weights.values()) != 100:
            raise PolicyError("weights must be non-negative and sum to 100")
        if set(self.score_map) != set(AXIS_STATES) or [self.score_map[s] for s in AXIS_STATES] != sorted(
                self.score_map[s] for s in AXIS_STATES):
            raise PolicyError("score_map must cover LOW/MEDIUM/HIGH and increase with favourability")
        if not 0 <= self.applicable_weight_floor <= 100:
            raise PolicyError("applicable_weight_floor must be between 0 and 100")
        for t in tuple(self.strength_not_ranked_types) + tuple(self.cross_not_applicable_types):
            if t not in PATTERN_TYPES:
                raise PolicyError(f"unknown pattern type in policy: {t}")


@dataclass(frozen=True)
class RecommendationPolicy:
    """recommendation state の frozen rule。precedence は first match wins。"""
    policy_version: str = "1.0.0"
    precedence: Tuple[str, ...] = ("NOT_READY", "REJECT_RECOMMENDED", "APPROVE_RECOMMENDED",
                                   "REVIEW_RECOMMENDED", "KEEP_REVIEWING")
    not_ready_min_applicable_core_axes: int = 2
    reject_require_consistency: str = LOW
    reject_min_strength: str = HIGH
    reject_min_time: str = MEDIUM
    reject_min_documents_each_side: int = 2
    reject_min_sibling_support: int = 2
    reject_min_dna_conflict_support: int = 2
    approve_require_quality: str = HIGH
    approve_require_consistency: str = HIGH
    approve_require_time: str = HIGH
    approve_require_cross_regime: str = HIGH        # applicable なときだけ課す
    approve_min_applicable_core: str = MEDIUM
    approve_excluded_types: Tuple[str, ...] = (T_FULL, T_EVIDENCE_WHY, T_EVIDENCE_RISK)
    approve_requires_novelty: bool = False          # 常に False（True は PolicyError）
    review_min_strength: str = MEDIUM
    review_min_time: str = MEDIUM
    review_consistency_not: str = LOW
    shadow_allow_approve_recommended: bool = True
    shadow_label: str = "SHADOW_ONLY"
    score_allowed_for_state_transition: bool = False   # 常に False（True は PolicyError）

    def as_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version, "precedence": list(self.precedence),
            "not_ready": {"min_applicable_core_axes": self.not_ready_min_applicable_core_axes},
            "reject": {"require_consistency": self.reject_require_consistency,
                       "min_strength": self.reject_min_strength, "min_time": self.reject_min_time,
                       "min_documents_each_side": self.reject_min_documents_each_side,
                       "min_sibling_support": self.reject_min_sibling_support,
                       "min_dna_conflict_support": self.reject_min_dna_conflict_support},
            "approve": {"require_quality": self.approve_require_quality,
                        "require_consistency": self.approve_require_consistency,
                        "require_time": self.approve_require_time,
                        "require_cross_regime_where_applicable": self.approve_require_cross_regime,
                        "min_applicable_core": self.approve_min_applicable_core,
                        "excluded_types": list(self.approve_excluded_types),
                        "requires_novelty": self.approve_requires_novelty},
            "review": {"min_strength": self.review_min_strength, "min_time": self.review_min_time,
                       "consistency_not": self.review_consistency_not},
            "shadow_mode": {"allow_approve_recommended": self.shadow_allow_approve_recommended,
                            "label": self.shadow_label},
            "score_use": {"allowed_for_state_transition": self.score_allowed_for_state_transition},
        }

    def digest(self) -> str:
        return _digest(self.as_dict())

    def validate(self) -> None:
        if not _SEMVER.match(self.policy_version or ""):
            raise PolicyError(f"policy_version must be semver: {self.policy_version!r}")
        if tuple(self.precedence) != RecommendationPolicy.precedence:
            raise PolicyError("precedence is frozen: NOT_READY > REJECT > APPROVE > REVIEW > KEEP_REVIEWING")
        if self.approve_requires_novelty:
            raise PolicyError("DNA Novelty must never be required for APPROVE_RECOMMENDED")
        if self.score_allowed_for_state_transition:
            raise PolicyError("Reference Score must never drive a state transition")
        for t in self.approve_excluded_types:
            if t not in PATTERN_TYPES:
                raise PolicyError(f"unknown pattern type in approve_excluded_types: {t}")
        for name, value in (("reject_require_consistency", self.reject_require_consistency),
                            ("reject_min_strength", self.reject_min_strength),
                            ("reject_min_time", self.reject_min_time),
                            ("approve_require_quality", self.approve_require_quality),
                            ("approve_require_consistency", self.approve_require_consistency),
                            ("approve_require_time", self.approve_require_time),
                            ("approve_require_cross_regime", self.approve_require_cross_regime),
                            ("approve_min_applicable_core", self.approve_min_applicable_core),
                            ("review_min_strength", self.review_min_strength),
                            ("review_min_time", self.review_min_time),
                            ("review_consistency_not", self.review_consistency_not)):
            if value not in AXIS_STATES:
                raise PolicyError(f"{name} must be one of {list(AXIS_STATES)}: {value!r}")
        if self.reject_min_documents_each_side < 2:
            raise PolicyError("REJECT requires repeated contradiction: min_documents_each_side >= 2")


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
        raise PolicyError(f"{key} must be a list")
    return tuple(str(v) for v in value)


def _int(section: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(section.get(key, default))
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{key} must be an integer: {exc}") from exc


def evaluation_policy_from_mapping(section: Optional[Mapping[str, Any]]) -> EvaluationPolicy:
    s = dict(section or {})
    base = EvaluationPolicy()
    strength = dict(s.get("strength") or {})
    time_ = dict(s.get("time") or {})
    cross = dict(s.get("cross_regime") or {})
    cons = dict(s.get("consistency") or {})
    nov = dict(s.get("novelty") or {})
    qual = dict(s.get("quality") or {})
    score = dict(s.get("score") or {})
    weights = dict(score.get("weights") or base.weights)
    smap = dict(score.get("map") or base.score_map)
    try:
        floor = Decimal(str(qual.get("medium_valid_ratio_floor", base.quality_medium_valid_ratio_floor)))
    except Exception as exc:  # noqa: BLE001
        raise PolicyError(f"medium_valid_ratio_floor must be numeric: {exc}") from exc
    policy = EvaluationPolicy(
        policy_version=str(s.get("policy_version", base.policy_version) or base.policy_version),
        strength_low_max=_int(strength, "low_max", base.strength_low_max),
        strength_medium_max=_int(strength, "medium_max", base.strength_medium_max),
        strength_not_ranked_types=_tuple(strength, "not_ranked_types", base.strength_not_ranked_types),
        relative_share_min_denominator=_int(strength, "relative_share_min_denominator",
                                            base.relative_share_min_denominator),
        time_medium_span_days=_int(time_, "medium_span_days", base.time_medium_span_days),
        time_medium_months=_int(time_, "medium_months", base.time_medium_months),
        time_high_span_days=_int(time_, "high_span_days", base.time_high_span_days),
        time_high_months=_int(time_, "high_months", base.time_high_months),
        cross_core_dimensions=_tuple(cross, "core_dimensions", base.cross_core_dimensions),
        cross_confirm_dimensions=_tuple(cross, "confirm_dimensions", base.cross_confirm_dimensions),
        cross_medium_cells=_int(cross, "medium_cells", base.cross_medium_cells),
        cross_high_cells=_int(cross, "high_cells", base.cross_high_cells),
        cross_high_support=_int(cross, "high_support", base.cross_high_support),
        cross_high_span_days=_int(cross, "high_span_days", base.cross_high_span_days),
        cross_high_confirmed_cells=_int(cross, "high_confirmed_cells", base.cross_high_confirmed_cells),
        cross_not_applicable_types=_tuple(cross, "not_applicable_types", base.cross_not_applicable_types),
        consistency_committed_directions=_tuple(cons, "committed_directions", base.consistency_committed_directions),
        consistency_soft_directions=_tuple(cons, "soft_directions", base.consistency_soft_directions),
        consistency_high_min_support=_int(cons, "high_min_support", base.consistency_high_min_support),
        novelty_low_relations=_tuple(nov, "low_relations", base.novelty_low_relations),
        novelty_low_min_overlap=_int(nov, "low_min_overlap", base.novelty_low_min_overlap),
        quality_medium_valid_ratio_floor=floor,
        quality_blocking_document_qualities=_tuple(qual, "blocking_document_qualities",
                                                   base.quality_blocking_document_qualities),
        quality_degraded_document_qualities=_tuple(qual, "degraded_document_qualities",
                                                   base.quality_degraded_document_qualities),
        supported_structure_schema_versions=_tuple(qual, "supported_structure_schema_versions",
                                                   base.supported_structure_schema_versions),
        supported_analysis_versions=_tuple(qual, "supported_analysis_versions", base.supported_analysis_versions),
        weights={str(k): int(v) for k, v in weights.items()},
        score_map={str(k): int(v) for k, v in smap.items()},
        applicable_weight_floor=_int(score, "applicable_weight_floor", base.applicable_weight_floor),
        formal_review_min_corpus=_int(s, "formal_review_min_corpus", base.formal_review_min_corpus))
    policy.validate()
    return policy


def recommendation_policy_from_mapping(section: Optional[Mapping[str, Any]]) -> RecommendationPolicy:
    s = dict(section or {})
    base = RecommendationPolicy()
    nr = dict(s.get("not_ready") or {})
    rj = dict(s.get("reject") or {})
    ap = dict(s.get("approve") or {})
    rv = dict(s.get("review") or {})
    sh = dict(s.get("shadow_mode") or {})
    su = dict(s.get("score_use") or {})

    def _flag(section_: Mapping[str, Any], key: str, default: bool) -> bool:
        value = section_.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value)

    policy = RecommendationPolicy(
        policy_version=str(s.get("policy_version", base.policy_version) or base.policy_version),
        precedence=_tuple(s, "precedence", base.precedence),
        not_ready_min_applicable_core_axes=_int(nr, "min_applicable_core_axes",
                                                base.not_ready_min_applicable_core_axes),
        reject_require_consistency=str(rj.get("require_consistency", base.reject_require_consistency)),
        reject_min_strength=str(rj.get("min_strength", base.reject_min_strength)),
        reject_min_time=str(rj.get("min_time", base.reject_min_time)),
        reject_min_documents_each_side=_int(rj, "min_documents_each_side", base.reject_min_documents_each_side),
        reject_min_sibling_support=_int(rj, "min_sibling_support", base.reject_min_sibling_support),
        reject_min_dna_conflict_support=_int(rj, "min_dna_conflict_support", base.reject_min_dna_conflict_support),
        approve_require_quality=str(ap.get("require_quality", base.approve_require_quality)),
        approve_require_consistency=str(ap.get("require_consistency", base.approve_require_consistency)),
        approve_require_time=str(ap.get("require_time", base.approve_require_time)),
        approve_require_cross_regime=str(ap.get("require_cross_regime_where_applicable",
                                                base.approve_require_cross_regime)),
        approve_min_applicable_core=str(ap.get("min_applicable_core", base.approve_min_applicable_core)),
        approve_excluded_types=_tuple(ap, "excluded_types", base.approve_excluded_types),
        approve_requires_novelty=_flag(ap, "requires_novelty", base.approve_requires_novelty),
        review_min_strength=str(rv.get("min_strength", base.review_min_strength)),
        review_min_time=str(rv.get("min_time", base.review_min_time)),
        review_consistency_not=str(rv.get("consistency_not", base.review_consistency_not)),
        shadow_allow_approve_recommended=_flag(sh, "allow_approve_recommended",
                                               base.shadow_allow_approve_recommended),
        shadow_label=str(sh.get("label", base.shadow_label) or base.shadow_label),
        score_allowed_for_state_transition=_flag(su, "allowed_for_state_transition",
                                                 base.score_allowed_for_state_transition))
    policy.validate()
    return policy


def load_policies(config_path: Path = Path("config.yaml")) -> "tuple[EvaluationPolicy, RecommendationPolicy]":
    return (evaluation_policy_from_mapping(_section(config_path, CONFIG_EVALUATION)),
            recommendation_policy_from_mapping(_section(config_path, CONFIG_RECOMMENDATION)))
