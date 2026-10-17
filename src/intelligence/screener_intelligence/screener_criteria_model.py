"""P8-B1 — Screener v1 の閉じた意味の model（基準 ・方針 ・評価の文脈 ・結果。評価の実行は無い）。

Phase 8 の Screener は「明示の基準と authority の下で、どの発行体が観察 ／ 調査に値するか」を**構造化**する。推奨 ・順位 ・score ・
目標株価 ・期待 return ・portfolio ・個人化 ・Theme → 企業の推定は作らない。本 module は型と不変条件だけを持つ:

- `Criterion`（FINANCIAL ・ISSUER ・凍結 A3 の 4 指標の 1 つ ・閉じた operator ・正準の Decimal の閾値 ・型つきの期間の規則 ・authority の
  mode ・固定の欠損の扱い）。内容 address `p8crt_`。Theme の次元（`THEME_EXPOSURE`）は予約だけで、v1 では構築できない（P8-OBS-62）。
- `CriteriaPolicy`（人が書く ・版つき ・内容 address `p8pol_` ・`ALL_OF` だけ ・順序つきの基準 ・1 つの authority mode ・aware な
  `reviewed_at` ・著者の参照 ・bounded な意図の文）。閾値は方針の中身で、code ・`config.yaml` には置かない。保存は P8-B3（private authority
  store）。
- `EvaluationContext`（主語 ・評価の瞬間 ・identity の有効時刻 ・authority mode ・方針の参照。view は B2 の runtime の入力）。
- `CriterionResult` ・`ScreenerResult`（説明できるが順位にならない。`threshold_distance` ・score ・weight ・rank は無い。完全性は
  data の完全性の語彙だけで、数ではない）。派生 ・非 authority ・非永続。
- authority の mode `STRICT_PIT` と `RETROSPECTIVE_PROVIDER_AUTHORITY` は別で、互いに fallback しない。

「Candidate（候補）」は人の文書の概念で、runtime の語彙は `ScreenerResult.state is MATCH`（`is_match`）。
記録: `docs/databank/PHASE8_B1_SCREENER_SEMANTIC_MODELS.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from .identity_model import CREDENTIAL_MARKERS, SubjectKind, canonical_json, is_issuer_id
from .metric_model import DERIVED_NON_AUTHORITY_NON_PERSISTENT, MetricKind, MetricStatus
from .observation_model import ObservationModelError, ReportingPeriod, StatementBasis, canonical_decimal
from ..core.ids import content_id
from ..core.time import to_utc_iso

SCREENER_RULES_VERSION = "p8_screener_semantics:0.1.0"
CRITERION_SCHEMA_VERSION = "p8_screener_criterion:0.1.0"
POLICY_SCHEMA_VERSION = "p8_screener_policy:0.1.0"
RESULT_SCHEMA_VERSION = "p8_screener_result:0.1.0"
CRITERION_ID_PREFIX = "p8crt"
POLICY_ID_PREFIX = "p8pol"
#: Screener の結果の意味: 明示の方針 ・authority mode ・評価の瞬間の下で基準をすべて満たした、ということだけ（推奨 ・買い ・thesis ではない）
SCREENER_MATCH_DEFINITION = ("ISSUER_SATISFIES_EVERY_CRITERION_OF_A_NAMED_POLICY"
                             "_UNDER_A_NAMED_AUTHORITY_MODE_AT_A_NAMED_INSTANT")
#: 欠損 ・保留 ・authority の失敗は決して MATCH にならない（v1 で許す唯一の欠損の扱い）
MISSING_DATA_RULE = "NOT_EVALUABLE_IS_NOT_MATCH"
#: 結果 ・基準 ・方針に決して置かない欄（順位 ・推奨の原始になる数と語）
FORBIDDEN_RESULT_FIELDS: Tuple[str, ...] = ("threshold_distance", "score", "weight", "rank", "rating", "priority",
                                            "attractiveness", "recommendation", "expected_return", "target_price")
#: 方針の意図の文に許さない語（評価 ・推奨の語彙。小文字で比べる）
FORBIDDEN_INTENT_WORDS: Tuple[str, ...] = ("buy", "sell", "recommend", "watchlist", "portfolio", "target price",
                                           "expected return", "score", "rank", "rating", "best",
                                           "推奨", "注目", "おすすめ", "有望", "割安", "上位", "買い", "売り")
MAX_INTENT_LEN = 500
MAX_AUTHOR_REF_LEN = 120
_POLICY_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_AUTHOR_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,119}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*(:[A-Za-z0-9_]+)*$")
_OBSERVATION_ID_RE = re.compile(r"^p8obs_[0-9a-f]{24}$")
_EPOCH_REF_RE = re.compile(r"^jq\.pvh:[0-9a-f]{24}$")
_MANIFEST_REF_RE = re.compile(r"^jq\.man:[0-9a-f]{24}$")
_POLICY_ID_RE = re.compile(r"^p8pol_[0-9a-f]{24}$")
_CRITERION_ID_RE = re.compile(r"^p8crt_[0-9a-f]{24}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class ScreenerModelError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ScreenerModelError(code, detail)


def _enum(value: Any, kind: type, field_name: str) -> None:
    _require(isinstance(value, kind), "INVALID_ENUM", field_name)


def _aware(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, datetime) and value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None,
             "NAIVE_OR_MISSING_DATETIME", field_name)
    return value


def _text(value: Any, field_name: str, pattern: re.Pattern) -> None:
    _require(isinstance(value, str) and bool(pattern.match(value)), "INVALID_TEXT", field_name)
    _no_credential(value, field_name)


def _no_credential(value: str, field_name: str) -> None:
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)


def canonical_threshold(value: Any) -> str:
    """閾値の正準の Decimal の文字列（文字列だけを受ける。float ・bool ・NaN ・Infinity ・不正な形は拒む）。"""
    _require(isinstance(value, str), "THRESHOLD_NOT_TEXT", "threshold")    # 数（float ・int ・bool）は受けない。文字列だけ
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        raise ScreenerModelError("INVALID_THRESHOLD", "threshold") from None
    _require(number.is_finite(), "INVALID_THRESHOLD", "threshold")
    try:
        return canonical_decimal(number)
    except ObservationModelError:
        raise ScreenerModelError("INVALID_THRESHOLD", "threshold") from None


# ---------------------------------------------------------------- 閉じた語彙


class ScreenerDimension(str, Enum):
    FINANCIAL = "FINANCIAL"
    THEME_EXPOSURE = "THEME_EXPOSURE"                    # 予約。v1 では基準を構築できない（人が審査した exposure の authority が無い）


class ScreenerAuthorityMode(str, Enum):
    STRICT_PIT = "STRICT_PIT"                                            # 世界 ／ PIT の authority（凍結 A3）
    RETROSPECTIVE_PROVIDER_AUTHORITY = "RETROSPECTIVE_PROVIDER_AUTHORITY"  # 選んだ provider の保持 epoch（凍結 A3-RA）


class CriterionOperator(str, Enum):
    LT = "LT"
    LE = "LE"
    GT = "GT"
    GE = "GE"
    BETWEEN = "BETWEEN"                                  # threshold <= value <= threshold_high（両端を含む）


class PeriodRule(str, Enum):
    """target の期間の規則（凍結の指標の期間の意味に対応。journal の順 ・任意の fallback は無い）。"""

    NEWEST_SUPPORTED_FY_OR_CUMULATIVE = "NEWEST_SUPPORTED_FY_OR_CUMULATIVE"  # FY ／ 累計の中で period_end 最大
    NEWEST_FY = "NEWEST_FY"                                                  # 年度だけ
    NEWEST_WITH_COMPARABLE_PRIOR = "NEWEST_WITH_COMPARABLE_PRIOR"            # 凍結の期間の関係が comparable な prior を持つ最新


class MissingDataPolicy(str, Enum):
    NOT_EVALUABLE_IS_NOT_MATCH = MISSING_DATA_RULE


class CriteriaComposition(str, Enum):
    ALL_OF = "ALL_OF"                                    # v1 はこれだけ（ANY_OF ・入れ子は無い）


class CriterionState(str, Enum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    HOLD = "HOLD"                                        # authority が意味の理由で値を留めた（SEMANTIC_HOLD）
    NOT_EVALUABLE = "NOT_EVALUABLE"                      # 真の値が無い（欠損 ・coverage ・比較不能 ・未定義 ・target なし）
    AUTHORITY_FAILURE = "AUTHORITY_FAILURE"              # manifest ／ membership ／ 曖昧な epoch ／ 入力の違反


class ScreenerState(str, Enum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    HOLD = "HOLD"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    AUTHORITY_FAILURE = "AUTHORITY_FAILURE"


class DataCompleteness(str, Enum):
    """data の完全性（評価できた基準の有無）。投資の質ではなく、基準 ・順位の入力にはならない。数は持たない。"""

    COMPLETE = "COMPLETE"                                # 全基準が MATCH ／ NO_MATCH に評価できた
    PARTIAL = "PARTIAL"                                  # 一部だけ評価できた
    NONE = "NONE"                                        # 1 つも評価できなかった


#: 指標 ↔ 期間の規則の許す組（凍結の指標の意味そのまま。ROA は年度だけ、売上成長率は comparable な prior が要る）
METRIC_PERIOD_RULES: Mapping[MetricKind, Tuple[PeriodRule, ...]] = {
    MetricKind.REVENUE_GROWTH: (PeriodRule.NEWEST_WITH_COMPARABLE_PRIOR,),
    MetricKind.OPERATING_MARGIN: (PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE, PeriodRule.NEWEST_FY),
    MetricKind.NET_MARGIN: (PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE, PeriodRule.NEWEST_FY),
    MetricKind.ROA_POINT_IN_TIME: (PeriodRule.NEWEST_FY,),
}
#: v1 で構築できる次元（Theme は予約）
CONSTRUCTIBLE_DIMENSIONS: Tuple[ScreenerDimension, ...] = (ScreenerDimension.FINANCIAL,)
#: 値を持つ状態（これ以外は観測値を運ばない）
VALUED_STATES: Tuple[CriterionState, ...] = (CriterionState.MATCH, CriterionState.NO_MATCH)


# ---------------------------------------------------------------- Criterion


@dataclass(frozen=True, kw_only=True)
class Criterion:
    """1 つの基準（FINANCIAL ・ISSUER ・凍結の 1 指標 ・閉じた operator ・正準の閾値）。式 ・重み ・score は無い。"""

    dimension: ScreenerDimension
    subject_kind: SubjectKind
    metric: MetricKind
    operator: CriterionOperator
    threshold: str
    threshold_high: Optional[str] = None
    period_rule: PeriodRule
    authority_mode: ScreenerAuthorityMode
    statement_basis: StatementBasis
    missing_policy: MissingDataPolicy = MissingDataPolicy.NOT_EVALUABLE_IS_NOT_MATCH
    rules_version: str = SCREENER_RULES_VERSION

    def __post_init__(self) -> None:
        _enum(self.dimension, ScreenerDimension, "dimension")
        _require(self.dimension in CONSTRUCTIBLE_DIMENSIONS, "DIMENSION_NOT_CONSTRUCTIBLE_IN_V1", self.dimension.value)
        _enum(self.subject_kind, SubjectKind, "subject_kind")
        _require(self.subject_kind is SubjectKind.ISSUER, "FINANCIAL_CRITERION_REQUIRES_ISSUER", "subject_kind")
        _enum(self.metric, MetricKind, "metric")
        _enum(self.operator, CriterionOperator, "operator")
        _enum(self.period_rule, PeriodRule, "period_rule")
        _require(self.period_rule in METRIC_PERIOD_RULES[self.metric], "PERIOD_RULE_INCOMPATIBLE_WITH_METRIC",
                 self.metric.value)
        _enum(self.authority_mode, ScreenerAuthorityMode, "authority_mode")
        _enum(self.statement_basis, StatementBasis, "statement_basis")
        _enum(self.missing_policy, MissingDataPolicy, "missing_policy")
        _require(self.rules_version == SCREENER_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        object.__setattr__(self, "threshold", canonical_threshold(self.threshold))
        if self.operator is CriterionOperator.BETWEEN:
            _require(self.threshold_high is not None, "BETWEEN_REQUIRES_TWO_THRESHOLDS", "threshold_high")
            high = canonical_threshold(self.threshold_high)
            _require(Decimal(self.threshold) < Decimal(high), "BETWEEN_BOUNDS_NOT_ASCENDING", "threshold_high")
            object.__setattr__(self, "threshold_high", high)
        else:
            _require(self.threshold_high is None, "THRESHOLD_HIGH_ONLY_FOR_BETWEEN", "threshold_high")

    def identity_payload(self) -> Dict[str, Any]:
        """identity に入る欄（すべて）。"""
        return {"authority_mode": self.authority_mode.value, "dimension": self.dimension.value,
                "metric": self.metric.value, "missing_policy": self.missing_policy.value,
                "operator": self.operator.value, "period_rule": self.period_rule.value,
                "rules_version": self.rules_version, "schema_version": CRITERION_SCHEMA_VERSION,
                "statement_basis": self.statement_basis.value, "subject_kind": self.subject_kind.value,
                "threshold": self.threshold, "threshold_high": self.threshold_high}

    @property
    def criterion_id(self) -> str:
        return content_id(CRITERION_ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "criterion_id": self.criterion_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Criterion":
        _require(isinstance(data, Mapping), "INVALID_RECORD", "criterion")
        _require(data.get("schema_version") == CRITERION_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        allowed = set(cls.__dataclass_fields__)
        allowed.update(("schema_version", "criterion_id"))
        _require(set(data) <= allowed, "UNKNOWN_FIELD", "criterion")
        try:
            record = cls(dimension=ScreenerDimension(data["dimension"]), subject_kind=SubjectKind(data["subject_kind"]),
                         metric=MetricKind(data["metric"]), operator=CriterionOperator(data["operator"]),
                         threshold=data["threshold"], threshold_high=data.get("threshold_high"),
                         period_rule=PeriodRule(data["period_rule"]),
                         authority_mode=ScreenerAuthorityMode(data["authority_mode"]),
                         statement_basis=StatementBasis(data["statement_basis"]),
                         missing_policy=MissingDataPolicy(data.get("missing_policy", MISSING_DATA_RULE)),
                         rules_version=data.get("rules_version", SCREENER_RULES_VERSION))
        except (KeyError, ValueError) as exc:
            if isinstance(exc, ScreenerModelError):
                raise
            raise ScreenerModelError("INVALID_RECORD", "criterion") from None
        if "criterion_id" in data:
            _require(data["criterion_id"] == record.criterion_id, "ID_MISMATCH", "criterion_id")
        return record


# ---------------------------------------------------------------- CriteriaPolicy


@dataclass(frozen=True, kw_only=True)
class CriteriaPolicy:
    """人が書いた ・版つき ・内容 address の方針（ALL_OF ・順序つきの基準 ・1 つの authority mode）。閾値はここにだけ在る。"""

    policy_key: str
    version: int
    author_ref: str
    reviewed_at: datetime
    intent: str
    criteria: Tuple[Criterion, ...]
    authority_mode: ScreenerAuthorityMode
    composition: CriteriaComposition = CriteriaComposition.ALL_OF
    rules_version: str = SCREENER_RULES_VERSION

    def __post_init__(self) -> None:
        _text(self.policy_key, "policy_key", _POLICY_KEY_RE)
        _require(type(self.version) is int and self.version >= 1, "INVALID_VERSION", "version")
        _text(self.author_ref, "author_ref", _AUTHOR_REF_RE)
        _aware(self.reviewed_at, "reviewed_at")
        _require(isinstance(self.intent, str) and 1 <= len(self.intent) <= MAX_INTENT_LEN
                 and not _CONTROL_RE.search(self.intent), "INVALID_INTENT", "intent")
        _no_credential(self.intent, "intent")
        lowered = self.intent.lower()
        _require(not any(word in lowered for word in FORBIDDEN_INTENT_WORDS), "FORBIDDEN_INTENT_VOCABULARY", "intent")
        _enum(self.composition, CriteriaComposition, "composition")
        _enum(self.authority_mode, ScreenerAuthorityMode, "authority_mode")
        _require(isinstance(self.criteria, tuple) and len(self.criteria) >= 1, "POLICY_REQUIRES_CRITERIA", "criteria")
        for criterion in self.criteria:
            _require(isinstance(criterion, Criterion), "INVALID_CRITERION", "criteria")
            _require(criterion.authority_mode is self.authority_mode, "CRITERION_AUTHORITY_MODE_MISMATCH",
                     criterion.criterion_id)
        ids = [c.criterion_id for c in self.criteria]
        _require(len(set(ids)) == len(ids), "DUPLICATE_CRITERION", "criteria")
        _require(self.rules_version == SCREENER_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")

    def identity_payload(self) -> Dict[str, Any]:
        """identity に入る欄: 鍵 ・版 ・著者 ・審査の瞬間 ・意図 ・構成 ・authority mode ・基準の id（順序つき）。"""
        return {"author_ref": self.author_ref, "authority_mode": self.authority_mode.value,
                "composition": self.composition.value, "criterion_ids": [c.criterion_id for c in self.criteria],
                "intent": self.intent, "policy_key": self.policy_key, "reviewed_at": to_utc_iso(self.reviewed_at),
                "rules_version": self.rules_version, "schema_version": POLICY_SCHEMA_VERSION, "version": self.version}

    @property
    def policy_id(self) -> str:
        return content_id(POLICY_ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "criteria": [c.as_dict() for c in self.criteria],
                "policy_id": self.policy_id}


# ---------------------------------------------------------------- EvaluationContext（意味 ・設定の部分）


@dataclass(frozen=True, kw_only=True)
class EvaluationContext:
    """評価の文脈の意味の部分（主語 ・瞬間 ・identity の有効時刻 ・authority mode ・方針）。像（history 等）は B2 の runtime の入力。"""

    subject_id: str
    evaluation_as_of: datetime
    identity_valid_at: datetime
    authority_mode: ScreenerAuthorityMode
    policy_id: str
    rules_version: str = SCREENER_RULES_VERSION

    def __post_init__(self) -> None:
        _require(is_issuer_id(self.subject_id), "INVALID_SUBJECT", "subject_id")
        _aware(self.evaluation_as_of, "evaluation_as_of")
        _aware(self.identity_valid_at, "identity_valid_at")
        _require(self.identity_valid_at <= self.evaluation_as_of, "IDENTITY_VALID_AT_AFTER_EVALUATION",
                 "identity_valid_at")
        _enum(self.authority_mode, ScreenerAuthorityMode, "authority_mode")
        _text(self.policy_id, "policy_id", _POLICY_ID_RE)
        _require(self.rules_version == SCREENER_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_mode": self.authority_mode.value, "evaluation_as_of": to_utc_iso(self.evaluation_as_of),
                "identity_valid_at": to_utc_iso(self.identity_valid_at), "policy_id": self.policy_id,
                "rules_version": self.rules_version, "subject_id": self.subject_id}


# ---------------------------------------------------------------- 結果


def _refs(values: Any, field_name: str, pattern: re.Pattern) -> None:
    _require(isinstance(values, tuple) and all(isinstance(v, str) and bool(pattern.match(v)) for v in values),
             "INVALID_REFERENCE", field_name)
    _require(len(set(values)) == len(values), "DUPLICATE_REFERENCE", field_name)


@dataclass(frozen=True, kw_only=True)
class CriterionResult:
    """1 基準の結果（説明できるが順位にならない）。値は MATCH ／ NO_MATCH の時だけ ・private の表面だけに出す。"""

    criterion_id: str
    state: CriterionState
    metric: MetricKind
    operator: CriterionOperator
    threshold: str
    threshold_high: Optional[str] = None
    authority_mode: ScreenerAuthorityMode
    has_value: bool
    observed_value: Optional[str] = None
    target_period: Optional[ReportingPeriod] = None
    comparison_period: Optional[ReportingPeriod] = None
    observation_ids: Tuple[str, ...] = ()
    coverage_epoch_ids: Tuple[str, ...] = ()
    manifest_refs: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()
    inner_metric_status: Optional[MetricStatus] = None

    def __post_init__(self) -> None:
        _text(self.criterion_id, "criterion_id", _CRITERION_ID_RE)
        _enum(self.state, CriterionState, "state")
        _enum(self.metric, MetricKind, "metric")
        _enum(self.operator, CriterionOperator, "operator")
        object.__setattr__(self, "threshold", canonical_threshold(self.threshold))
        if self.threshold_high is not None:
            _require(self.operator is CriterionOperator.BETWEEN, "THRESHOLD_HIGH_ONLY_FOR_BETWEEN", "threshold_high")
            object.__setattr__(self, "threshold_high", canonical_threshold(self.threshold_high))
        _enum(self.authority_mode, ScreenerAuthorityMode, "authority_mode")
        _require(type(self.has_value) is bool, "INVALID_FLAG", "has_value")
        valued = self.state in VALUED_STATES
        _require(self.has_value is valued, "VALUE_FLAG_INCONSISTENT_WITH_STATE", self.state.value)
        if valued:
            _require(self.observed_value is not None, "VALUED_STATE_REQUIRES_OBSERVED_VALUE", "observed_value")
            object.__setattr__(self, "observed_value", canonical_threshold(self.observed_value))
        else:
            _require(self.observed_value is None, "OBSERVED_VALUE_ONLY_WHEN_VALUED", "observed_value")
        for name, period in (("target_period", self.target_period), ("comparison_period", self.comparison_period)):
            _require(period is None or isinstance(period, ReportingPeriod), "INVALID_PERIOD", name)
        _refs(self.observation_ids, "observation_ids", _OBSERVATION_ID_RE)
        _refs(self.coverage_epoch_ids, "coverage_epoch_ids", _EPOCH_REF_RE)
        _refs(self.manifest_refs, "manifest_refs", _MANIFEST_REF_RE)
        _refs(self.reason_codes, "reason_codes", _REASON_CODE_RE)
        _require(self.reason_codes == tuple(sorted(self.reason_codes)), "REASON_CODES_NOT_SORTED", "reason_codes")
        _require(self.inner_metric_status is None or isinstance(self.inner_metric_status, MetricStatus), "INVALID_ENUM",
                 "inner_metric_status")

    def as_dict(self, *, include_value: bool = False) -> Dict[str, Any]:
        """結果の直列化。観測値は `include_value=True`（private の表面）の時だけ。"""
        data = {"authority_mode": self.authority_mode.value,
                "comparison_period": self.comparison_period.as_dict() if self.comparison_period else None,
                "coverage_epoch_ids": list(self.coverage_epoch_ids), "criterion_id": self.criterion_id,
                "has_value": self.has_value,
                "inner_metric_status": self.inner_metric_status.value if self.inner_metric_status else None,
                "manifest_refs": list(self.manifest_refs), "metric": self.metric.value,
                "observation_ids": list(self.observation_ids), "operator": self.operator.value,
                "reason_codes": list(self.reason_codes), "state": self.state.value,
                "target_period": self.target_period.as_dict() if self.target_period else None,
                "threshold": self.threshold, "threshold_high": self.threshold_high}
        if include_value:
            data["observed_value"] = self.observed_value
        return data


@dataclass(frozen=True, kw_only=True)
class ScreenerResult:
    """1 発行体 × 1 方針 × 1 文脈の結果（派生 ・非 authority ・非永続）。`state is MATCH` が「Candidate」の runtime の意味。"""

    subject_id: str
    policy_id: str
    policy_version: int
    evaluation_as_of: datetime
    identity_valid_at: datetime
    authority_mode: ScreenerAuthorityMode
    criterion_results: Tuple[CriterionResult, ...]
    state: ScreenerState
    completeness: DataCompleteness
    rules_version: str = SCREENER_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def __post_init__(self) -> None:
        _require(is_issuer_id(self.subject_id), "INVALID_SUBJECT", "subject_id")
        _text(self.policy_id, "policy_id", _POLICY_ID_RE)
        _require(type(self.policy_version) is int and self.policy_version >= 1, "INVALID_VERSION", "policy_version")
        _aware(self.evaluation_as_of, "evaluation_as_of")
        _aware(self.identity_valid_at, "identity_valid_at")
        _require(self.identity_valid_at <= self.evaluation_as_of, "IDENTITY_VALID_AT_AFTER_EVALUATION",
                 "identity_valid_at")
        _enum(self.authority_mode, ScreenerAuthorityMode, "authority_mode")
        _require(isinstance(self.criterion_results, tuple) and len(self.criterion_results) >= 1,
                 "RESULT_REQUIRES_CRITERIA", "criterion_results")
        for result in self.criterion_results:
            _require(isinstance(result, CriterionResult), "INVALID_CRITERION_RESULT", "criterion_results")
            _require(result.authority_mode is self.authority_mode, "CRITERION_AUTHORITY_MODE_MISMATCH",
                     result.criterion_id)
        ids = [r.criterion_id for r in self.criterion_results]
        _require(len(set(ids)) == len(ids), "DUPLICATE_CRITERION", "criterion_results")
        _enum(self.state, ScreenerState, "state")
        states = [r.state for r in self.criterion_results]
        if self.state is ScreenerState.MATCH:                                    # 定義: 全基準が MATCH の時だけ
            _require(all(s is CriterionState.MATCH for s in states), "MATCH_REQUIRES_ALL_CRITERIA_MATCH", "state")
        else:
            _require(not all(s is CriterionState.MATCH for s in states), "ALL_CRITERIA_MATCH_REQUIRES_MATCH", "state")
        _enum(self.completeness, DataCompleteness, "completeness")
        _require(self.completeness is completeness_of(states), "COMPLETENESS_INCONSISTENT", "completeness")
        _require(self.rules_version == SCREENER_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        _require(self.authority_class == DERIVED_NON_AUTHORITY_NON_PERSISTENT, "INVALID_AUTHORITY_CLASS",
                 "authority_class")

    @property
    def is_match(self) -> bool:
        return self.state is ScreenerState.MATCH

    def as_dict(self, *, include_values: bool = False) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "authority_mode": self.authority_mode.value,
                "completeness": self.completeness.value,
                "criterion_results": [r.as_dict(include_value=include_values) for r in self.criterion_results],
                "evaluation_as_of": to_utc_iso(self.evaluation_as_of),
                "identity_valid_at": to_utc_iso(self.identity_valid_at), "policy_id": self.policy_id,
                "policy_version": self.policy_version, "rules_version": self.rules_version,
                "schema_version": RESULT_SCHEMA_VERSION, "state": self.state.value, "subject_id": self.subject_id}


def completeness_of(states: Any) -> DataCompleteness:
    """基準の状態 → data の完全性（評価できた ＝ MATCH ／ NO_MATCH）。質 ・順位の意味は無い。"""
    states = tuple(states)
    _require(len(states) >= 1 and all(isinstance(s, CriterionState) for s in states), "INVALID_ENUM", "states")
    evaluated = sum(1 for s in states if s in VALUED_STATES)
    if evaluated == len(states):
        return DataCompleteness.COMPLETE
    return DataCompleteness.PARTIAL if evaluated else DataCompleteness.NONE


def model_field_names() -> Dict[str, Tuple[str, ...]]:
    """guard のための欄の一覧（禁止の欄が無いことを機械で確かめる）。"""
    return {cls.__name__: tuple(f.name for f in fields(cls))
            for cls in (Criterion, CriteriaPolicy, EvaluationContext, CriterionResult, ScreenerResult)}


__all__ = ["CONSTRUCTIBLE_DIMENSIONS", "CRITERION_ID_PREFIX", "CRITERION_SCHEMA_VERSION", "FORBIDDEN_INTENT_WORDS",
           "FORBIDDEN_RESULT_FIELDS", "MAX_AUTHOR_REF_LEN", "MAX_INTENT_LEN", "METRIC_PERIOD_RULES",
           "MISSING_DATA_RULE", "POLICY_ID_PREFIX", "POLICY_SCHEMA_VERSION", "RESULT_SCHEMA_VERSION",
           "SCREENER_MATCH_DEFINITION", "SCREENER_RULES_VERSION", "VALUED_STATES", "CriteriaComposition",
           "CriteriaPolicy", "Criterion", "CriterionOperator", "CriterionResult", "CriterionState",
           "DataCompleteness", "EvaluationContext", "MissingDataPolicy", "PeriodRule", "ScreenerAuthorityMode",
           "ScreenerDimension", "ScreenerModelError", "ScreenerResult", "ScreenerState", "canonical_threshold",
           "completeness_of", "model_field_names"]
