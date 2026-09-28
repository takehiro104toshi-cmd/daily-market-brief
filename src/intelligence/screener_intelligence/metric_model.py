"""P8-A3A — 決定論の財務の指標の結果の純 model（派生 ・非 authority ・非永続）。

答える問い: 明示の cutoff で、A2 の観測（A2R の注記つき）から 1 つの指標の値を**算出できたか**、できなければ**どの理由で**か。
良い会社か ・割安か ・screen を通るか ・順位 ・score ・推奨 ・Theme は答えない。

- 結果は `VALUE` か、型つきの非値（`NOT_COMPARABLE` ・`INSUFFICIENT_DATA` ・`INVALID_INPUT` ・`INSUFFICIENT_TIME_PRECISION` ・
  `UNDEFINED`）。失敗を None に潰さない。理由は閉じた語彙（脚 × code）で決定論の順。
- 値は 10 進の正準の文字列（A2 と同じ `canonical_decimal`）。float は無い。
- 結果は record にならない（`DERIVED_NON_AUTHORITY_NON_PERSISTENT`）。id ・保存 ・時計 ・乱数 ・IO は無い。

記録: `docs/databank/PHASE8_A3A_FUNDAMENTAL_METRICS.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .observation_model import ReportingPeriod, StatementBasis
from ..core.time import to_utc_iso

METRIC_RULES_VERSION = "p8_fundamental_metrics:0.1.0"
#: 結果の authority の種類（record ではない ・保存しない）
DERIVED_NON_AUTHORITY_NON_PERSISTENT = "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
#: 値の小数の桁（ROUND_HALF_EVEN で丸めてから正準の文字列にする）
VALUE_PLACES = 6


class MetricKind(str, Enum):
    REVENUE_GROWTH = "REVENUE_GROWTH"
    OPERATING_MARGIN = "OPERATING_MARGIN"


class MetricStatus(str, Enum):
    VALUE = "VALUE"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_INPUT = "INVALID_INPUT"
    INSUFFICIENT_TIME_PRECISION = "INSUFFICIENT_TIME_PRECISION"
    UNDEFINED = "UNDEFINED"


class MetricPeriodLabel(str, Enum):
    """値がどの期間の種類の上のものか（累計の期間の値を単独の四半期と呼ばない）。"""

    FISCAL_YEAR = "FISCAL_YEAR"
    CUMULATIVE_YEAR_TO_DATE = "CUMULATIVE_YEAR_TO_DATE"


class MetricLeg(str, Enum):
    """理由が指す入力の脚。`PAIR` は 2 つの脚の関係（比較 ・期間 ・分母）。"""

    TARGET = "TARGET"
    COMPARISON = "COMPARISON"
    REVENUE = "REVENUE"
    OPERATING_INCOME = "OPERATING_INCOME"
    PAIR = "PAIR"


class ReasonCode(str, Enum):
    # INVALID_INPUT
    INVALID_SUBJECT = "INVALID_SUBJECT"
    INVALID_STATEMENT_BASIS = "INVALID_STATEMENT_BASIS"
    INVALID_PERIOD = "INVALID_PERIOD"
    INVALID_CUTOFF = "INVALID_CUTOFF"
    INVALID_HISTORY = "INVALID_HISTORY"
    INVALID_SEMANTICS_LOOKUP = "INVALID_SEMANTICS_LOOKUP"
    SEMANTICS_MISMATCH = "SEMANTICS_MISMATCH"
    # INSUFFICIENT_TIME_PRECISION
    INSUFFICIENT_TIME_PRECISION = "INSUFFICIENT_TIME_PRECISION"
    # INSUFFICIENT_DATA（A2 の resolver の status と値の状態 ・注記の欠落）
    SUBJECT_NOT_RESOLVED = "SUBJECT_NOT_RESOLVED"
    BEFORE_COVERAGE = "BEFORE_COVERAGE"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"
    NOT_YET_KNOWN = "NOT_YET_KNOWN"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    VALUE_ABSENT = "VALUE_ABSENT"
    SEMANTICS_MISSING = "SEMANTICS_MISSING"
    # NOT_COMPARABLE
    SUBJECT_DIFFERS = "SUBJECT_DIFFERS"
    ACCOUNTING_STANDARD_UNKNOWN = "ACCOUNTING_STANDARD_UNKNOWN"
    STATEMENT_BASIS_UNKNOWN = "STATEMENT_BASIS_UNKNOWN"
    ACCOUNTING_STANDARD_DIFFERS = "ACCOUNTING_STANDARD_DIFFERS"
    STATEMENT_BASIS_DIFFERS = "STATEMENT_BASIS_DIFFERS"
    PERIOD_BASIS_UNSUPPORTED = "PERIOD_BASIS_UNSUPPORTED"
    PERIOD_BASIS_MISMATCH = "PERIOD_BASIS_MISMATCH"
    PERIOD_QUARTER_DIFFERS = "PERIOD_QUARTER_DIFFERS"
    PERIOD_NOT_ADJACENT = "PERIOD_NOT_ADJACENT"
    FISCAL_YEAR_IRREGULAR = "FISCAL_YEAR_IRREGULAR"
    CURRENCY_DIFFERS = "CURRENCY_DIFFERS"
    # UNDEFINED
    DENOMINATOR_ZERO = "DENOMINATOR_ZERO"
    DENOMINATOR_NEGATIVE = "DENOMINATOR_NEGATIVE"


#: code → 結果の status（結果の status は、含まれる理由の中で最も強いもの。VALUE は理由が無い時だけ）
STATUS_FOR_CODE: Dict[ReasonCode, MetricStatus] = {
    **{code: MetricStatus.INVALID_INPUT for code in (
        ReasonCode.INVALID_SUBJECT, ReasonCode.INVALID_STATEMENT_BASIS, ReasonCode.INVALID_PERIOD,
        ReasonCode.INVALID_CUTOFF, ReasonCode.INVALID_HISTORY, ReasonCode.INVALID_SEMANTICS_LOOKUP,
        ReasonCode.SEMANTICS_MISMATCH)},
    ReasonCode.INSUFFICIENT_TIME_PRECISION: MetricStatus.INSUFFICIENT_TIME_PRECISION,
    **{code: MetricStatus.INSUFFICIENT_DATA for code in (
        ReasonCode.SUBJECT_NOT_RESOLVED, ReasonCode.BEFORE_COVERAGE, ReasonCode.OUTSIDE_COVERAGE,
        ReasonCode.NOT_YET_KNOWN, ReasonCode.NOT_FOUND, ReasonCode.AMBIGUOUS, ReasonCode.VALUE_ABSENT,
        ReasonCode.SEMANTICS_MISSING)},
    **{code: MetricStatus.NOT_COMPARABLE for code in (
        ReasonCode.SUBJECT_DIFFERS, ReasonCode.ACCOUNTING_STANDARD_UNKNOWN, ReasonCode.STATEMENT_BASIS_UNKNOWN,
        ReasonCode.ACCOUNTING_STANDARD_DIFFERS, ReasonCode.STATEMENT_BASIS_DIFFERS,
        ReasonCode.PERIOD_BASIS_UNSUPPORTED, ReasonCode.PERIOD_BASIS_MISMATCH, ReasonCode.PERIOD_QUARTER_DIFFERS,
        ReasonCode.PERIOD_NOT_ADJACENT, ReasonCode.FISCAL_YEAR_IRREGULAR, ReasonCode.CURRENCY_DIFFERS)},
    ReasonCode.DENOMINATOR_ZERO: MetricStatus.UNDEFINED,
    ReasonCode.DENOMINATOR_NEGATIVE: MetricStatus.UNDEFINED,
}
#: status の強さ（複数の理由があれば最も強い status）
STATUS_PRECEDENCE: Tuple[MetricStatus, ...] = (
    MetricStatus.INVALID_INPUT, MetricStatus.INSUFFICIENT_TIME_PRECISION, MetricStatus.INSUFFICIENT_DATA,
    MetricStatus.NOT_COMPARABLE, MetricStatus.UNDEFINED)
_LEG_ORDER = {member: index for index, member in enumerate(MetricLeg)}
_CODE_ORDER = {member: index for index, member in enumerate(ReasonCode)}


class MetricModelError(ValueError):
    """結果の model の構造の違反（結果を組み立てる側の誤り。指標の入力の誤りは INVALID_INPUT の結果で返す）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class MetricReason:
    """理由（脚 × code）。文字列は `LEG:CODE`。"""

    leg: MetricLeg
    code: ReasonCode

    def __post_init__(self) -> None:
        if not isinstance(self.leg, MetricLeg) or not isinstance(self.code, ReasonCode):
            raise MetricModelError("INVALID_REASON")

    @property
    def status(self) -> MetricStatus:
        return STATUS_FOR_CODE[self.code]

    def as_text(self) -> str:
        return f"{self.leg.value}:{self.code.value}"


def ordered_reasons(reasons: Any) -> Tuple[MetricReason, ...]:
    """重複を除き、脚 ・code の語彙の順に並べる（決定論）。"""
    unique = set(reasons)
    for reason in unique:
        if not isinstance(reason, MetricReason):
            raise MetricModelError("INVALID_REASON")
    return tuple(sorted(unique, key=lambda r: (_LEG_ORDER[r.leg], _CODE_ORDER[r.code])))


def status_for(reasons: Tuple[MetricReason, ...]) -> MetricStatus:
    """理由が無ければ VALUE。あれば最も強い status。"""
    if not reasons:
        return MetricStatus.VALUE
    present = {reason.status for reason in reasons}
    for status in STATUS_PRECEDENCE:
        if status in present:
            return status
    raise MetricModelError("INVALID_REASON")


@dataclass(frozen=True, kw_only=True)
class MetricResult:
    """1 つの指標の結果（派生 ・非 authority ・非永続。record id は無い）。"""

    metric: MetricKind
    status: MetricStatus
    reasons: Tuple[MetricReason, ...]
    value: Optional[str]
    subject_id: str
    statement_basis: Optional[StatementBasis]
    cutoff: Optional[datetime]
    target_period: Optional[ReportingPeriod]
    comparison_period: Optional[ReportingPeriod] = None
    period_label: Optional[MetricPeriodLabel] = None
    quarter: int = 0
    input_record_ids: Tuple[str, ...] = ()
    rules_version: str = METRIC_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def __post_init__(self) -> None:
        if not isinstance(self.metric, MetricKind) or not isinstance(self.status, MetricStatus):
            raise MetricModelError("INVALID_RESULT", "metric")
        if self.reasons != ordered_reasons(self.reasons) or status_for(self.reasons) is not self.status:
            raise MetricModelError("INVALID_RESULT", "reasons")
        if (self.status is MetricStatus.VALUE) != (self.value is not None):
            raise MetricModelError("INVALID_RESULT", "value")
        if self.value is not None and not isinstance(self.value, str):
            raise MetricModelError("INVALID_RESULT", "value")
        if self.status is MetricStatus.VALUE and self.period_label is None:
            raise MetricModelError("INVALID_RESULT", "period_label")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class,
                "comparison_period": self.comparison_period.as_dict() if self.comparison_period else None,
                "cutoff": to_utc_iso(self.cutoff) if self.cutoff is not None else None,
                "input_record_ids": list(self.input_record_ids), "metric": self.metric.value,
                "period_label": self.period_label.value if self.period_label else None, "quarter": self.quarter,
                "reasons": [reason.as_text() for reason in self.reasons], "rules_version": self.rules_version,
                "statement_basis": self.statement_basis.value if self.statement_basis else None,
                "status": self.status.value, "subject_id": self.subject_id,
                "target_period": self.target_period.as_dict() if self.target_period else None, "value": self.value}
