"""P8-B5B — 複数発行体の全結果の集合 → 構造的に最小化した安全な投影（private ・local。公開の承認ではない）。

安全な投影は件数 ・状態 ・規則の版だけを持つ。発行体の id ・provider の code ・会社名 ・Universe の member ・criterion_id ・観測値 ・閾値 ・意図 ・
著者 ・生の根拠 ・journal の行 ・credential ・path ・正確な評価の瞬間（日だけ）・Universe の参照 ・結果の id は欄が無い。
coverage の偏りを隠さない: 「評価できた 5 発行体のうち 5 が MATCH」と「100 member の Universe のうち 95 が NOT_EVALUABLE で 5 が MATCH」が
同じに見えないよう、member の結果の件数 ・Screener の状態の件数 ・data の完全性の件数 ・理由の code の件数を必ず並べる（比率 ・点数は作らない）。
MATCH は「明示の方針の全基準を満たした」だけを意味し、順位 ・推奨 ・魅力の語は無い。
記録: `docs/databank/PHASE8_B5B_RESULT_SET.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Tuple

from .identity_model import canonical_json
from .screener_result_set import (MATCH_SUBSET_MEANING, ExecutionCompleteness, MemberOutcomeKind, ResultSetError,
                                  ScreenResultSet)

SET_SUMMARY_SCHEMA_VERSION = "p8_screener_result_set_summary:0.1.0"
SET_SUMMARY_RULES_VERSION = "p8_screener_result_set_summary:0.1.0"
#: 投影の意味（結果は authority ではない。保存しない。private ・local だけ）
SET_SUMMARY_CLASS = "DERIVED_SAFE_PROJECTION_NON_AUTHORITY_NON_PERSISTENT_PRIVATE_LOCAL"
#: 投影に決して置かない欄（test が型の欄 ・dict の鍵で pin する）
FORBIDDEN_SET_SUMMARY_FIELDS: Tuple[str, ...] = ("issuer_id", "issuer_ids", "match_issuer_ids", "member_code",
                                                 "member_codes", "universe_members", "universe_id", "universe_ref",
                                                 "screen_result_id", "criterion_id", "criteria", "observed_value",
                                                 "threshold", "threshold_high", "intent", "author_ref",
                                                 "evaluation_as_of", "observation_ids", "coverage_epoch_ids",
                                                 "manifest_refs", "company", "security", "ticker", "code", "path")


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ResultSetError(code, detail)


def _sorted_counts(values) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


@dataclass(frozen=True, kw_only=True)
class SafeScreenSetSummary:
    """件数 ・状態 ・規則の版だけの投影。順位 ・点数 ・比率 ・主語の identity は構造的に無い。"""

    policy_ref: str
    policy_version: int
    universe_version: int
    authority_mode: str
    authority_day: date
    execution_completeness: ExecutionCompleteness
    member_count: int
    issuer_count: int
    member_outcome_counts: Dict[str, int]
    screener_state_counts: Dict[str, int]
    data_completeness_counts: Dict[str, int]
    member_reason_code_counts: Dict[str, int]
    evaluation_reason_code_counts: Dict[str, int]
    rules_version: str = SET_SUMMARY_RULES_VERSION
    schema_version: str = SET_SUMMARY_SCHEMA_VERSION
    summary_class: str = SET_SUMMARY_CLASS

    def __post_init__(self) -> None:
        _require(sum(self.member_outcome_counts.values()) == self.member_count, "COUNT_MISMATCH", "member_count")
        _require(sum(self.screener_state_counts.values()) == self.issuer_count, "COUNT_MISMATCH", "issuer_count")
        _require(sum(self.data_completeness_counts.values()) == self.issuer_count, "COUNT_MISMATCH",
                 "data_completeness_counts")
        _require(self.member_outcome_counts[MemberOutcomeKind.EVALUATED.value] >= self.issuer_count,
                 "COUNT_MISMATCH", "evaluated")                                  # 複数の code → 1 発行体
        _require(self.summary_class == SET_SUMMARY_CLASS, "SUMMARY_CLASS_MISMATCH", "summary_class")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_day": self.authority_day.isoformat(), "authority_mode": self.authority_mode,
                "data_completeness_counts": dict(self.data_completeness_counts),
                "evaluation_reason_code_counts": dict(self.evaluation_reason_code_counts),
                "execution_completeness": self.execution_completeness.value, "issuer_count": self.issuer_count,
                "match_subset_meaning": MATCH_SUBSET_MEANING, "member_count": self.member_count,
                "member_outcome_counts": dict(self.member_outcome_counts),
                "member_reason_code_counts": dict(self.member_reason_code_counts), "policy_ref": self.policy_ref,
                "policy_version": self.policy_version, "rules_version": self.rules_version,
                "schema_version": self.schema_version, "screener_state_counts": dict(self.screener_state_counts),
                "summary_class": self.summary_class, "universe_version": self.universe_version}

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())


def project_safe_set_summary(result_set: ScreenResultSet) -> SafeScreenSetSummary:
    """private の全結果の集合 → 安全な投影（件数だけ。member ・発行体ごとの行は写さない）。"""
    _require(isinstance(result_set, ScreenResultSet), "INVALID_RESULT_SET", "result_set")
    member_reasons = (code for outcome in result_set.member_outcomes for code in outcome.reason_codes)
    evaluation_reasons = (code for result in result_set.issuer_results for criterion in result.evaluation.criteria
                          for code in criterion.reason_codes)
    return SafeScreenSetSummary(policy_ref=result_set.policy_id, policy_version=result_set.policy_version,
                                universe_version=result_set.universe_version,
                                authority_mode=result_set.authority_mode.value,
                                authority_day=result_set.authority_day,
                                execution_completeness=result_set.execution_completeness,
                                member_count=len(result_set.member_outcomes),
                                issuer_count=len(result_set.issuer_results),
                                member_outcome_counts=result_set.member_outcome_counts,
                                screener_state_counts=result_set.screener_state_counts,
                                data_completeness_counts=result_set.data_completeness_counts,
                                member_reason_code_counts=_sorted_counts(member_reasons),
                                evaluation_reason_code_counts=_sorted_counts(evaluation_reasons))


def set_summary_field_names() -> Tuple[str, ...]:
    return tuple(SafeScreenSetSummary.__dataclass_fields__)


__all__ = ["FORBIDDEN_SET_SUMMARY_FIELDS", "SET_SUMMARY_CLASS", "SET_SUMMARY_RULES_VERSION",
           "SET_SUMMARY_SCHEMA_VERSION", "SafeScreenSetSummary", "project_safe_set_summary",
           "set_summary_field_names"]
