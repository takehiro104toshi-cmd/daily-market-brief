"""P8-B4A — 凍結 B1 ・B2 の private の `ScreenerResult` → 安全な投影（metadata ・状態 ・件数だけ）。

private の結果は観測値 ・閾値 ・主語 ・provenance の参照を持つ。安全な投影はそれらを **構造的に** 持たない:
観測値 ・threshold ・threshold_high ・operator ・期間 ・方針の意図 ・著者 ・会社名 ・code ・主語の id ・観測 id ・保持 epoch の参照 ・manifest の参照 ・
生の方針 JSON ・距離 ・点数 ・path ・credential は欄が無い。provenance は件数だけ。
MATCH は「この発行体は明示に選んだ方針 X の全基準を満たした」だけを意味する。良い ・魅力 ・推奨 ・買い ・機会 ・勝者 ・上位の語は無く、
状態の語彙は凍結 B1 の `ScreenerState` ・`CriterionState` ・`DataCompleteness` だけ。順位 ・score ・重み ・「MATCH の基準の数」は作らない
（`criterion_count` は構造の件数）。
policy_ref は凍結 B1 の `policy_id`（identity payload の内容 address。閾値 ・値を含まず、逆算できない不透明の参照）。
記録: `docs/databank/PHASE8_B4A_POLICY_EVALUATION_SAFE_PROJECTION.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Tuple

from ..core.time import to_utc_iso
from .identity_model import canonical_json
from .metric_model import MetricKind, MetricStatus
from .screener_criteria_model import (CriterionResult, CriterionState, DataCompleteness, ScreenerAuthorityMode,
                                      ScreenerResult, ScreenerState)

SUMMARY_SCHEMA_VERSION = "p8_screener_result_summary:0.1.0"
SUMMARY_RULES_VERSION = "p8_screener_result_summary:0.1.0"
#: 安全な投影の authority の意味（結果は authority ではない。保存しない）
SUMMARY_CLASS = "DERIVED_SAFE_PROJECTION_NON_AUTHORITY_NON_PERSISTENT"
#: MATCH の意味（これ以上の意味は無い）
MATCH_MEANING = "ISSUER_SATISFIED_EVERY_CRITERION_OF_THE_EXPLICITLY_SELECTED_POLICY"
#: 投影に決して現れない欄の名前（test が構造を pin する）
FORBIDDEN_SUMMARY_FIELDS: Tuple[str, ...] = ("observed_value", "threshold", "threshold_high", "operator", "author_ref",
                                             "intent", "company", "company_name", "issuer", "issuer_id", "subject",
                                             "subject_id", "security", "security_id", "ticker", "code",
                                             "observation_ids", "coverage_epoch_ids", "manifest_refs",
                                             "target_period", "comparison_period", "identity_valid_at", "policy_key",
                                             "policy_json", "threshold_distance", "score", "rank", "rating",
                                             "weight", "priority", "attractiveness", "recommendation", "target_price",
                                             "expected_return", "path", "data_root")


class SummaryProjectionError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise SummaryProjectionError(code, detail)


@dataclass(frozen=True, kw_only=True)
class SafeCriterionSummary:
    """1 基準の安全な投影: id ・指標 ・状態 ・値の有無 ・理由の code ・mode ・provenance の件数。値 ・閾値 ・期間 ・参照は無い。"""

    criterion_id: str
    metric: MetricKind
    state: CriterionState
    has_value: bool
    reason_codes: Tuple[str, ...]
    authority_mode: ScreenerAuthorityMode
    inner_metric_status: Any
    observation_id_count: int
    coverage_epoch_ref_count: int
    manifest_ref_count: int

    @classmethod
    def of(cls, result: CriterionResult) -> "SafeCriterionSummary":
        _require(isinstance(result, CriterionResult), "INVALID_CRITERION_RESULT", "result")
        _require(result.inner_metric_status is None or isinstance(result.inner_metric_status, MetricStatus),
                 "INVALID_CRITERION_RESULT", "inner_metric_status")
        return cls(criterion_id=result.criterion_id, metric=result.metric, state=result.state,
                   has_value=result.has_value, reason_codes=tuple(result.reason_codes),
                   authority_mode=result.authority_mode, inner_metric_status=result.inner_metric_status,
                   observation_id_count=len(result.observation_ids),
                   coverage_epoch_ref_count=len(result.coverage_epoch_ids),
                   manifest_ref_count=len(result.manifest_refs))

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_mode": self.authority_mode.value, "coverage_epoch_ref_count": self.coverage_epoch_ref_count,
                "criterion_id": self.criterion_id, "has_value": self.has_value,
                "inner_metric_status": self.inner_metric_status.value if self.inner_metric_status else None,
                "manifest_ref_count": self.manifest_ref_count, "metric": self.metric.value,
                "observation_id_count": self.observation_id_count, "reason_codes": list(self.reason_codes),
                "state": self.state.value}


@dataclass(frozen=True, kw_only=True)
class SafeScreenerSummary:
    """方針 1 つ ・主語 1 つの評価の安全な投影。主語の identity ・値 ・閾値 ・著者 ・意図 ・参照は構造的に無い。"""

    policy_ref: str
    policy_version: int
    authority_mode: ScreenerAuthorityMode
    state: ScreenerState
    completeness: DataCompleteness
    criterion_count: int
    criteria: Tuple[SafeCriterionSummary, ...]
    evaluation_as_of: datetime
    rules_version: str = SUMMARY_RULES_VERSION
    schema_version: str = SUMMARY_SCHEMA_VERSION
    summary_class: str = SUMMARY_CLASS

    def __post_init__(self) -> None:
        _require(self.criterion_count == len(self.criteria) >= 1, "CRITERION_COUNT_MISMATCH", "criterion_count")
        _require(self.summary_class == SUMMARY_CLASS, "SUMMARY_CLASS_MISMATCH", "summary_class")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_mode": self.authority_mode.value, "completeness": self.completeness.value,
                "criteria": [c.as_dict() for c in self.criteria], "criterion_count": self.criterion_count,
                "evaluation_as_of": to_utc_iso(self.evaluation_as_of), "match_meaning": MATCH_MEANING,
                "policy_ref": self.policy_ref, "policy_version": self.policy_version,
                "rules_version": self.rules_version, "schema_version": self.schema_version,
                "state": self.state.value, "summary_class": self.summary_class}

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())


def project_safe_summary(result: ScreenerResult) -> SafeScreenerSummary:
    """private の `ScreenerResult` → 安全な投影。主語 ・値 ・閾値 ・期間 ・参照は写さない（件数だけ）。順位 ・score は作らない。"""
    _require(isinstance(result, ScreenerResult), "INVALID_SCREENER_RESULT", "result")
    criteria = tuple(SafeCriterionSummary.of(c) for c in result.criterion_results)
    return SafeScreenerSummary(policy_ref=result.policy_id, policy_version=result.policy_version,
                               authority_mode=result.authority_mode, state=result.state,
                               completeness=result.completeness, criterion_count=len(criteria), criteria=criteria,
                               evaluation_as_of=result.evaluation_as_of)


def summary_field_names() -> Dict[str, Tuple[str, ...]]:
    """投影の型の欄（test が禁止の欄の不在を pin する）。"""
    return {"SafeScreenerSummary": tuple(SafeScreenerSummary.__dataclass_fields__),
            "SafeCriterionSummary": tuple(SafeCriterionSummary.__dataclass_fields__)}


__all__ = ["FORBIDDEN_SUMMARY_FIELDS", "MATCH_MEANING", "SUMMARY_CLASS", "SUMMARY_RULES_VERSION",
           "SUMMARY_SCHEMA_VERSION", "SafeCriterionSummary", "SafeScreenerSummary", "SummaryProjectionError",
           "project_safe_summary", "summary_field_names"]
