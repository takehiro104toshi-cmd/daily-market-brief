"""Replay policy（Phase 3.9.4）— config.yaml `compass_replay`。versioned + content digest・fail closed。

digest 規約は他 Phase と同じ「canonical JSON の sha256 先頭 16 桁」。
stability 閾値は **PROVISIONAL_CALIBRATION_ONLY**（語彙は凍結・値は実 FULL_REPLAY で較正してから凍結）。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .errors import ReplayPolicyError

CONFIG_SECTION = "compass_replay"

MODE_MILESTONE = "MILESTONE_REPLAY"
MODE_TRANSITION = "TRANSITION_REPLAY"
MODE_MILESTONE_AND_TRANSITION = "MILESTONE_AND_TRANSITION"
MODE_FULL = "FULL_REPLAY"
MODES: Tuple[str, ...] = (MODE_MILESTONE, MODE_TRANSITION, MODE_MILESTONE_AND_TRANSITION, MODE_FULL)

ORDER_CHRONOLOGICAL = "CHRONOLOGICAL"
ORDER_INGESTION = "INGESTION"
ORDERINGS: Tuple[str, ...] = (ORDER_CHRONOLOGICAL, ORDER_INGESTION)

CALIBRATION_PROVISIONAL = "PROVISIONAL_CALIBRATION_ONLY"
CALIBRATION_STATES: Tuple[str, ...] = (CALIBRATION_PROVISIONAL, "SUPERVISOR_APPROVED")

STABILITY_UNIT = "eligible_documents"

# 安定性分類の凍結語彙（値は provisional）
STABLE = "STABLE"
MOSTLY_STABLE = "MOSTLY_STABLE"
OSCILLATING = "OSCILLATING"
RECENT_TRANSITION = "RECENT_TRANSITION"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
STABILITY_CLASSES: Tuple[str, ...] = (STABLE, MOSTLY_STABLE, OSCILLATING, RECENT_TRANSITION, INSUFFICIENT_HISTORY)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _digest(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ReplayPolicy:
    policy_version: str = "1.0.0"
    default_mode: str = MODE_MILESTONE_AND_TRANSITION
    default_ordering: str = ORDER_CHRONOLOGICAL
    milestone_points: Tuple[int, ...] = (10, 30, 50, 100, 200)
    transition_resolution: int = 5
    refine_transitions: bool = True
    include_shadow_queue: bool = True
    full_replay_enabled: bool = False
    max_snapshots: int = 2000
    max_undated_ratio: Decimal = Decimal("0.05")
    identity_ambiguity_tolerance: int = 0
    temp_workspace: str = ""
    retain_debug_runs: bool = False
    fail_on_input_drift: bool = True
    stability_calibration_state: str = CALIBRATION_PROVISIONAL
    stability_unit: str = STABILITY_UNIT
    stable_min_persistence: int = 15
    mostly_stable_ratio: Decimal = Decimal("0.8")
    oscillating_min_reversals: int = 2

    def as_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "default_mode": self.default_mode, "default_ordering": self.default_ordering,
            "milestone_points": list(self.milestone_points),
            "transition_resolution": self.transition_resolution,
            "refine_transitions": self.refine_transitions,
            "include_shadow_queue": self.include_shadow_queue,
            "full_replay_enabled": self.full_replay_enabled,
            "max_snapshots": self.max_snapshots,
            "max_undated_ratio": str(self.max_undated_ratio),
            "identity_ambiguity_tolerance": self.identity_ambiguity_tolerance,
            "temp_workspace": self.temp_workspace,
            "retain_debug_runs": self.retain_debug_runs,
            "fail_on_input_drift": self.fail_on_input_drift,
            "stability": {"calibration_state": self.stability_calibration_state,
                          "unit": self.stability_unit,
                          "stable_min_persistence": self.stable_min_persistence,
                          "mostly_stable_ratio": str(self.mostly_stable_ratio),
                          "oscillating_min_reversals": self.oscillating_min_reversals},
        }

    # digest から除外する運用フィールド（replay 意味論に影響しないもの）。
    _NON_SEMANTIC_KEYS = ("temp_workspace", "retain_debug_runs")

    def semantic_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.as_dict().items() if k not in self._NON_SEMANTIC_KEYS}

    def digest(self) -> str:
        return _digest(self.semantic_dict())

    def validate(self) -> None:
        if not _SEMVER.match(self.policy_version or ""):
            raise ReplayPolicyError(f"policy_version must be semver: {self.policy_version!r}")
        if self.default_mode not in MODES:
            raise ReplayPolicyError(f"unknown default_mode: {self.default_mode}")
        if self.default_mode == MODE_FULL and not self.full_replay_enabled:
            raise ReplayPolicyError("FULL_REPLAY must never be the default")
        if self.default_ordering not in ORDERINGS:
            raise ReplayPolicyError(f"unknown default_ordering: {self.default_ordering}")
        if not self.milestone_points or list(self.milestone_points) != sorted(set(self.milestone_points)):
            raise ReplayPolicyError("milestone_points must be strictly increasing")
        if any(int(p) < 1 for p in self.milestone_points):
            raise ReplayPolicyError("milestone_points must be >= 1")
        if self.transition_resolution < 1:
            raise ReplayPolicyError("transition_resolution must be >= 1")
        if self.max_snapshots < 1:
            raise ReplayPolicyError("max_snapshots must be >= 1")
        if not Decimal("0") <= self.max_undated_ratio <= Decimal("1"):
            raise ReplayPolicyError("max_undated_ratio must be within [0, 1]")
        if self.identity_ambiguity_tolerance != 0:
            raise ReplayPolicyError("identity_ambiguity_tolerance is frozen at 0 in v1")
        if self.stability_calibration_state not in CALIBRATION_STATES:
            raise ReplayPolicyError(f"unknown stability.calibration_state: {self.stability_calibration_state}")
        if self.stability_unit != STABILITY_UNIT:
            raise ReplayPolicyError("stability.unit is frozen: eligible_documents (never snapshot count)")
        if self.stable_min_persistence < 1 or self.oscillating_min_reversals < 1:
            raise ReplayPolicyError("stability thresholds must be >= 1")
        if not Decimal("0") < self.mostly_stable_ratio <= Decimal("1"):
            raise ReplayPolicyError("mostly_stable_ratio must be within (0, 1]")


def _section(config_path: Path, name: str) -> Mapping[str, Any]:
    if not config_path.is_file():
        return {}
    try:
        import yaml

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return raw.get(name) or {}
    except Exception:  # noqa: BLE001
        return {}


def _int(s: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(s.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ReplayPolicyError(f"{key} must be an integer: {exc}") from exc


def _flag(s: Mapping[str, Any], key: str, default: bool) -> bool:
    v = s.get(key, default)
    return v.strip().lower() in ("true", "1", "yes") if isinstance(v, str) else bool(v)


def _dec(s: Mapping[str, Any], key: str, default: Decimal) -> Decimal:
    try:
        return Decimal(str(s.get(key, default)))
    except (InvalidOperation, TypeError) as exc:
        raise ReplayPolicyError(f"{key} must be numeric: {exc}") from exc


def replay_policy_from_mapping(section: Optional[Mapping[str, Any]]) -> ReplayPolicy:
    s = dict(section or {})
    base = ReplayPolicy()
    st = dict(s.get("stability") or {})
    points = s.get("milestone_points", list(base.milestone_points))
    if not isinstance(points, (list, tuple)):
        raise ReplayPolicyError("milestone_points must be a list")
    policy = ReplayPolicy(
        policy_version=str(s.get("policy_version", base.policy_version) or base.policy_version),
        default_mode=str(s.get("default_mode", base.default_mode)),
        default_ordering=str(s.get("default_ordering", base.default_ordering)),
        milestone_points=tuple(int(p) for p in points),
        transition_resolution=_int(s, "transition_resolution", base.transition_resolution),
        refine_transitions=_flag(s, "refine_transitions", base.refine_transitions),
        include_shadow_queue=_flag(s, "include_shadow_queue", base.include_shadow_queue),
        full_replay_enabled=_flag(s, "full_replay_enabled", base.full_replay_enabled),
        max_snapshots=_int(s, "max_snapshots", base.max_snapshots),
        max_undated_ratio=_dec(s, "max_undated_ratio", base.max_undated_ratio),
        identity_ambiguity_tolerance=_int(s, "identity_ambiguity_tolerance", base.identity_ambiguity_tolerance),
        temp_workspace=str(s.get("temp_workspace", base.temp_workspace) or ""),
        retain_debug_runs=_flag(s, "retain_debug_runs", base.retain_debug_runs),
        fail_on_input_drift=_flag(s, "fail_on_input_drift", base.fail_on_input_drift),
        stability_calibration_state=str(st.get("calibration_state", base.stability_calibration_state)),
        stability_unit=str(st.get("unit", base.stability_unit)),
        stable_min_persistence=_int(st, "stable_min_persistence", base.stable_min_persistence),
        mostly_stable_ratio=_dec(st, "mostly_stable_ratio", base.mostly_stable_ratio),
        oscillating_min_reversals=_int(st, "oscillating_min_reversals", base.oscillating_min_reversals))
    policy.validate()
    return policy


def load_replay_policy(config_path: Path = Path("config.yaml")) -> ReplayPolicy:
    return replay_policy_from_mapping(_section(config_path, CONFIG_SECTION))
