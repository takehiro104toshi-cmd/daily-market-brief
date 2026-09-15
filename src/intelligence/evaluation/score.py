"""Reference Score（Phase 3.9.2）— secondary display / ordering のみ。state transition には絶対使わない。

score = Σ(weight × map(state)) / Σ(weight) over **applicable** axes × 100（構造的 N/A は weight ごと除外して
再正規化する。不可能な試験に減点を課さない）。applicable_weight_sum が floor 未満なら NOT_COMPARABLE。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .config import SCORED_AXES, EvaluationPolicy
from .models import AxisResult


def reference_score(axes: Mapping[str, AxisResult], policy: EvaluationPolicy
                    ) -> Tuple[Optional[float], bool, Tuple[str, ...], int]:
    """(score, comparable, applicable_axes, applicable_weight_sum) を返す。"""
    applicable = tuple(a for a in SCORED_AXES if a in axes and axes[a].applicable)
    weight_sum = sum(int(policy.weights[a]) for a in applicable)
    if weight_sum <= 0 or weight_sum < policy.applicable_weight_floor:
        return None, False, applicable, weight_sum
    total = sum(int(policy.weights[a]) * int(policy.score_map[axes[a].state]) for a in applicable)
    return round(total / weight_sum, 2), True, applicable, weight_sum


def ordering_key(record: Mapping[str, Any], policy: EvaluationPolicy) -> Tuple[int, float, float, str]:
    """review queue の並べ替え用。qualitative state を第一に、score は tie-break に留める。
    （score 単独で state を決めないという凍結方針の実装上の担保）"""
    states = dict(record.get("axis_states") or {})
    applicability = dict(record.get("axis_applicability") or {})
    highs = sum(1 for a in SCORED_AXES
                if applicability.get(a) == "APPLICABLE" and states.get(a) == "HIGH")
    score = record.get("reference_score")
    share = record.get("relative_support_share")
    return (-highs,
            -(float(score) if record.get("reference_score_comparable") and score is not None else -1.0),
            -(float(share) if share is not None else -1.0),
            str(record.get("pattern_id", "")))
