"""Shadow Review ranking（Phase 3.9.3）— Phase 3.9.2 の `ordering_key()` をそのまま基底に使う。

    1. applicable core の HIGH 本数 DESC    ← 質的 state が第一（score では覆せない）
    2. Reference Score DESC                 ← comparable のときだけ。NOT_COMPARABLE は最下位扱い
    3. relative_support_share DESC          ← Phase 3.9.2 の applicability 判定に従う
    4. eligible_support DESC                ← 3.9.3 で追加
    5. span_days DESC                       ← 3.9.3 で追加
    6. pattern_id ASC                       ← 完全決定化

1〜3 と 6 は `evaluation.score.ordering_key()` の戻り値をそのまま使い、4〜5 を間に差し込むだけ。
Phase 3.9.2 の frozen code は一切変更しない。
"""
from __future__ import annotations

from typing import Any, Mapping, Tuple

from ..evaluation.config import A_STRENGTH, A_TIME, EvaluationPolicy
from ..evaluation.score import ordering_key

MISSING = -1.0          # 値が無いものは最下位（ordering_key と同じ約束）


def _metric(row: Mapping[str, Any], axis: str, key: str) -> float:
    metrics = dict(row.get("axis_metrics") or {}).get(axis) or {}
    try:
        return float(metrics[key])
    except (KeyError, TypeError, ValueError):
        return MISSING


def eligible_support(row: Mapping[str, Any]) -> float:
    value = _metric(row, A_STRENGTH, "eligible_support")
    return value if value != MISSING else _metric(row, "data_quality", "eligible_support")


def span_days(row: Mapping[str, Any]) -> float:
    return _metric(row, A_TIME, "span_days")


def shadow_ordering_key(row: Mapping[str, Any], policy: EvaluationPolicy
                        ) -> Tuple[int, float, float, float, float, str]:
    highs, score, share, pattern_id = ordering_key(row, policy)
    return (highs, score, share, -eligible_support(row), -span_days(row), pattern_id)
