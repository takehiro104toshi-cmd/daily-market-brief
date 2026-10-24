"""P8-A3A — 決定論の財務の指標: 売上成長率 ・営業利益率（派生 ・非 authority ・非永続。A2 ・A2R を変えない追加）。

入力は caller が開いた A2 の `ObservationHistory`（読むだけ）、明示の aware な cutoff、A2R の注記の lookup
（観測の record id → `ObservationSemantics`）。revision の選択は凍結した A2 の resolver（`resolve`）だけを使い、
競合する resolver を作らない。

指標が使う観測は、canonical の A2 の財務の観測で、A2R の注記が会計基準 ・連結の区分とも KNOWN、A2R の互換の gate が
`COMPATIBLE`、caller の cutoff で PIT に確かに知られ、指標が定める期間の関係を満たすものだけ。UNKNOWN は fail closed。
会計基準の変更は revision ではなく意味の不連続で、基準が違えば `NOT_COMPARABLE`（監督の決定 P8-OBS-57。橋渡しの authority は無い）。

- 売上成長率 = target の売上 ／ comparison の売上 − 1。期間の関係は (a) 年度 ↔ 直前の年度、(b) 年度の初めからの累計 ↔ 直前の
  年度の同じ四半期の累計、だけ。年率化 ・TTM ・補間 ・累計から単独の四半期への変換はしない。
- 営業利益率 = 同じ期間 ・同じ基準の営業利益 ／ 売上。経常利益（OdP）で代用しない。売上 ≤ 0 → `UNDEFINED`。
- 4Q ・5Q ・OtherPeriod ・単独の四半期 ・不規則な長さの年度は fail closed（`NOT_COMPARABLE`）。
- 値は Decimal（float なし）。桁（Scale）は正確な 10 進の倍率で揃え、通貨が違えば比べない。

記録: `docs/databank/PHASE8_A3A_FUNDAMENTAL_METRICS.md`。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .identity_model import SourceClass, is_issuer_id
from .metric_model import (MetricKind, MetricLeg, MetricPeriodLabel, MetricReason, MetricResult, ReasonCode,
                           ordered_reasons, status_for)
from .observation_model import (FundamentalField, ObservationHistory, PeriodBasis, ReportingPeriod, Scale,
                                StatementBasis, ValueState, canonical_decimal)
from .observation_resolver import ObservationQuery, ObservationStatus, resolve
from .observation_semantics_gate import CompatibilityReason, CompatibilityVerdict, decide_compatibility
from .observation_semantics_model import ObservationSemantics

#: 規則の版は結果の model と共有（`METRIC_RULES_VERSION`）
#: 年度の長さ（日）が「規則的」と見なす範囲。決算期の変更の年（A2 は 550 日まで受ける）は比べない
REGULAR_FISCAL_YEAR_DAYS = (360, 371)
#: 桁の倍率（正確な 10 進）
_SCALE_MULTIPLIER: Mapping[Scale, Decimal] = {Scale.ONE: Decimal(1), Scale.THOUSAND: Decimal(1000),
                                              Scale.MILLION: Decimal(1000000)}
_QUANTUM = Decimal(1).scaleb(-6)
#: A2 の resolver の非 FOUND の status → 理由の code
_RESOLVER_CODES: Mapping[ObservationStatus, ReasonCode] = {
    ObservationStatus.NOT_FOUND: ReasonCode.NOT_FOUND, ObservationStatus.NOT_YET_KNOWN: ReasonCode.NOT_YET_KNOWN,
    ObservationStatus.AMBIGUOUS: ReasonCode.AMBIGUOUS,
    ObservationStatus.INSUFFICIENT_TIME_PRECISION: ReasonCode.INSUFFICIENT_TIME_PRECISION,
    ObservationStatus.BEFORE_COVERAGE: ReasonCode.BEFORE_COVERAGE,
    ObservationStatus.OUTSIDE_COVERAGE: ReasonCode.OUTSIDE_COVERAGE,
    ObservationStatus.SUBJECT_NOT_RESOLVED: ReasonCode.SUBJECT_NOT_RESOLVED}
#: A2R の互換の gate の理由 → (脚の選び方, code)。LEFT ＝ 1 つ目の脚、RIGHT ＝ 2 つ目の脚、違いは PAIR
_GATE_CODES: Mapping[CompatibilityReason, Tuple[int, ReasonCode]] = {
    CompatibilityReason.ACCOUNTING_STANDARD_DIFFERS: (2, ReasonCode.ACCOUNTING_STANDARD_DIFFERS),
    CompatibilityReason.STATEMENT_BASIS_DIFFERS: (2, ReasonCode.STATEMENT_BASIS_DIFFERS),
    CompatibilityReason.LEFT_ACCOUNTING_STANDARD_UNKNOWN: (0, ReasonCode.ACCOUNTING_STANDARD_UNKNOWN),
    CompatibilityReason.LEFT_STATEMENT_BASIS_UNKNOWN: (0, ReasonCode.STATEMENT_BASIS_UNKNOWN),
    CompatibilityReason.RIGHT_ACCOUNTING_STANDARD_UNKNOWN: (1, ReasonCode.ACCOUNTING_STANDARD_UNKNOWN),
    CompatibilityReason.RIGHT_STATEMENT_BASIS_UNKNOWN: (1, ReasonCode.STATEMENT_BASIS_UNKNOWN)}


class _Leg:
    """1 つの脚の解決の結果（record ・注記 ・理由）。"""

    def __init__(self, leg: MetricLeg) -> None:
        self.leg = leg
        self.record: Any = None
        self.semantics: Optional[ObservationSemantics] = None
        self.reasons: List[MetricReason] = []

    def fail(self, code: ReasonCode) -> None:
        self.reasons.append(MetricReason(self.leg, code))


def _aware(value: Any) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None


def _regular_fiscal_year(period: ReportingPeriod) -> bool:
    days = (period.fiscal_year_end - period.fiscal_year_start).days + 1
    return REGULAR_FISCAL_YEAR_DAYS[0] <= days <= REGULAR_FISCAL_YEAR_DAYS[1]


def _label_for(period: ReportingPeriod) -> Optional[MetricPeriodLabel]:
    if period.basis is PeriodBasis.FISCAL_YEAR:
        return MetricPeriodLabel.FISCAL_YEAR
    if period.basis is PeriodBasis.CUMULATIVE_YEAR_TO_DATE:
        return MetricPeriodLabel.CUMULATIVE_YEAR_TO_DATE
    return None                                                            # 単独の四半期は A3A で支えない


def _resolve_leg(history: ObservationHistory, leg: _Leg, query: ObservationQuery, cutoff: datetime,
                 semantics: Mapping[str, Any]) -> None:
    """凍結した A2 の resolver で脚を解決し、注記を付ける。値の状態と注記の整合も見る。"""
    resolution = resolve(history, query, cutoff=cutoff)
    if resolution.status is not ObservationStatus.FOUND:
        leg.fail(_RESOLVER_CODES.get(resolution.status, ReasonCode.NOT_FOUND))
        return
    leg.record = resolution.record
    annotation = semantics.get(leg.record.record_id)
    if annotation is None:
        leg.fail(ReasonCode.SEMANTICS_MISSING)
        return
    if not isinstance(annotation, ObservationSemantics) or annotation.observation_id != leg.record.record_id or (
            annotation.statement_basis is not None and annotation.statement_basis is not leg.record.statement_basis):
        leg.fail(ReasonCode.SEMANTICS_MISMATCH)
        return
    leg.semantics = annotation
    if leg.record.value.state is not ValueState.VALUE_PRESENT:
        leg.fail(ReasonCode.VALUE_ABSENT)


def _compatibility(first: _Leg, second: _Leg) -> List[MetricReason]:
    """A2R の互換の gate（KNOWN ・同じ基準 ・同じ区分）。UNKNOWN と違いを脚の理由に写す。"""
    if first.semantics is None or second.semantics is None:
        return []
    decision = decide_compatibility(first.semantics, second.semantics)
    if decision.verdict is CompatibilityVerdict.COMPATIBLE:
        return []
    legs = (first.leg, second.leg, MetricLeg.PAIR)
    return [MetricReason(legs[side], code) for side, code in (_GATE_CODES[reason] for reason in decision.reasons)]


def _amount(record: Any) -> Decimal:
    return Decimal(record.value.amount) * _SCALE_MULTIPLIER[record.value.scale]


def _ratio_minus(numerator: Any, denominator: Any, subtract_one: bool) -> Tuple[Optional[str], List[MetricReason]]:
    """分子 ／ 分母（− 1）。分母 ≤ 0 と通貨の違いは値にしない。"""
    reasons: List[MetricReason] = []
    if numerator.value.currency is not denominator.value.currency:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.CURRENCY_DIFFERS))
    bottom = _amount(denominator)
    if bottom == 0:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.DENOMINATOR_ZERO))
    elif bottom < 0:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.DENOMINATOR_NEGATIVE))
    if reasons:
        return None, reasons
    with localcontext() as context:
        context.prec = 40
        quotient = _amount(numerator) / bottom
        if subtract_one:
            quotient -= 1
        return canonical_decimal(quotient.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)), []


def _result(metric: MetricKind, reasons: List[MetricReason], *, value: Optional[str], subject_id: Any,
            statement_basis: Any, cutoff: Any, target_period: Any, comparison_period: Any = None,
            label: Optional[MetricPeriodLabel] = None, quarter: int = 0, records: Tuple[str, ...] = ()) -> MetricResult:
    ordered = ordered_reasons(reasons)
    status = status_for(ordered)
    return MetricResult(metric=metric, status=status, reasons=ordered, value=value if not ordered else None,
                        subject_id=subject_id if isinstance(subject_id, str) else "",
                        statement_basis=statement_basis if isinstance(statement_basis, StatementBasis) else None,
                        cutoff=cutoff if _aware(cutoff) else None,
                        target_period=target_period if isinstance(target_period, ReportingPeriod) else None,
                        comparison_period=comparison_period if isinstance(comparison_period, ReportingPeriod) else None,
                        period_label=label if not ordered else None, quarter=quarter if not ordered else 0,
                        input_record_ids=records)


def _input_reasons(history: Any, issuer_id: Any, statement_basis: Any, cutoff: Any, semantics: Any,
                   periods: Tuple[Tuple[MetricLeg, Any], ...]) -> List[MetricReason]:
    reasons: List[MetricReason] = []
    if not isinstance(history, ObservationHistory):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.INVALID_HISTORY))
    if not is_issuer_id(issuer_id):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.INVALID_SUBJECT))
    if not isinstance(statement_basis, StatementBasis):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.INVALID_STATEMENT_BASIS))
    if not _aware(cutoff):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.INVALID_CUTOFF))
    if not isinstance(semantics, Mapping):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.INVALID_SEMANTICS_LOOKUP))
    for leg, period in periods:
        if not isinstance(period, ReportingPeriod):
            reasons.append(MetricReason(leg, ReasonCode.INVALID_PERIOD))
    return reasons


def _period_relation(target: ReportingPeriod, comparison: ReportingPeriod) -> List[MetricReason]:
    """売上成長率が支える期間の関係: 年度 ↔ 直前の年度、累計 ↔ 直前の年度の同じ四半期の累計。"""
    reasons: List[MetricReason] = []
    for leg, period in ((MetricLeg.TARGET, target), (MetricLeg.COMPARISON, comparison)):
        if _label_for(period) is None:
            reasons.append(MetricReason(leg, ReasonCode.PERIOD_BASIS_UNSUPPORTED))
        if not _regular_fiscal_year(period):
            reasons.append(MetricReason(leg, ReasonCode.FISCAL_YEAR_IRREGULAR))
    if reasons:
        return reasons
    if target.basis is not comparison.basis:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.PERIOD_BASIS_MISMATCH))
    elif target.quarter != comparison.quarter:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.PERIOD_QUARTER_DIFFERS))
    if comparison.fiscal_year_end + timedelta(days=1) != target.fiscal_year_start:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.PERIOD_NOT_ADJACENT))
    return reasons


def revenue_growth(history: Any, *, issuer_id: Any, statement_basis: Any, target_period: Any, comparison_period: Any,
                   cutoff: Any, semantics: Any, comparison_issuer_id: Any = None,
                   comparison_statement_basis: Any = None, source_class: Optional[SourceClass] = None) -> MetricResult:
    """売上成長率 = target の売上 ／ comparison の売上 − 1（同じ発行体 ・同じ基準 ・同じ区分 ・支える期間の関係 ・PIT）。

    `comparison_issuer_id` ・`comparison_statement_basis` は省くと target と同じ。違えば `NOT_COMPARABLE`（橋渡しはしない）。
    """
    metric = MetricKind.REVENUE_GROWTH
    comparison_issuer = issuer_id if comparison_issuer_id is None else comparison_issuer_id
    comparison_basis = statement_basis if comparison_statement_basis is None else comparison_statement_basis
    reasons = _input_reasons(history, issuer_id, statement_basis, cutoff, semantics,
                             ((MetricLeg.TARGET, target_period), (MetricLeg.COMPARISON, comparison_period)))
    if not is_issuer_id(comparison_issuer):
        reasons.append(MetricReason(MetricLeg.COMPARISON, ReasonCode.INVALID_SUBJECT))
    if not isinstance(comparison_basis, StatementBasis):
        reasons.append(MetricReason(MetricLeg.COMPARISON, ReasonCode.INVALID_STATEMENT_BASIS))
    if source_class is not None and not isinstance(source_class, SourceClass):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.INVALID_SEMANTICS_LOOKUP))
    if reasons:
        return _result(metric, reasons, value=None, subject_id=issuer_id, statement_basis=statement_basis,
                       cutoff=cutoff, target_period=target_period, comparison_period=comparison_period)
    if comparison_issuer != issuer_id:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.SUBJECT_DIFFERS))
    if comparison_basis is not statement_basis:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.STATEMENT_BASIS_DIFFERS))
    reasons.extend(_period_relation(target_period, comparison_period))
    if reasons:
        return _result(metric, reasons, value=None, subject_id=issuer_id, statement_basis=statement_basis,
                       cutoff=cutoff, target_period=target_period, comparison_period=comparison_period)
    target, comparison = _Leg(MetricLeg.TARGET), _Leg(MetricLeg.COMPARISON)
    _resolve_leg(history, target, ObservationQuery.actual(issuer_id, FundamentalField.REVENUE, statement_basis,
                                                          target_period, source_class=source_class), cutoff, semantics)
    _resolve_leg(history, comparison, ObservationQuery.actual(comparison_issuer, FundamentalField.REVENUE,
                                                              comparison_basis, comparison_period,
                                                              source_class=source_class), cutoff, semantics)
    reasons = target.reasons + comparison.reasons + _compatibility(target, comparison)
    records = tuple(leg.record.record_id for leg in (target, comparison) if leg.record is not None)
    value = None
    if not reasons:
        value, reasons = _ratio_minus(target.record, comparison.record, subtract_one=True)
    return _result(metric, reasons, value=value, subject_id=issuer_id, statement_basis=statement_basis, cutoff=cutoff,
                   target_period=target_period, comparison_period=comparison_period, label=_label_for(target_period),
                   quarter=target_period.quarter, records=records)


def operating_margin(history: Any, *, issuer_id: Any, statement_basis: Any, period: Any, cutoff: Any, semantics: Any,
                     source_class: Optional[SourceClass] = None) -> MetricResult:
    """営業利益率 = 同じ期間 ・同じ基準の営業利益 ／ 売上（累計の期間なら累計の期間の利益率。単独の四半期ではない）。"""
    metric = MetricKind.OPERATING_MARGIN
    reasons = _input_reasons(history, issuer_id, statement_basis, cutoff, semantics, ((MetricLeg.PAIR, period),))
    if source_class is not None and not isinstance(source_class, SourceClass):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.INVALID_SEMANTICS_LOOKUP))
    if reasons:
        return _result(metric, reasons, value=None, subject_id=issuer_id, statement_basis=statement_basis,
                       cutoff=cutoff, target_period=period)
    label = _label_for(period)
    if label is None:
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.PERIOD_BASIS_UNSUPPORTED))
    if not _regular_fiscal_year(period):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.FISCAL_YEAR_IRREGULAR))
    if reasons:
        return _result(metric, reasons, value=None, subject_id=issuer_id, statement_basis=statement_basis,
                       cutoff=cutoff, target_period=period)
    revenue, income = _Leg(MetricLeg.REVENUE), _Leg(MetricLeg.OPERATING_INCOME)
    for leg, field in ((revenue, FundamentalField.REVENUE), (income, FundamentalField.OPERATING_INCOME)):
        _resolve_leg(history, leg, ObservationQuery.actual(issuer_id, field, statement_basis, period,
                                                           source_class=source_class), cutoff, semantics)
    reasons = revenue.reasons + income.reasons + _compatibility(revenue, income)
    records = tuple(leg.record.record_id for leg in (revenue, income) if leg.record is not None)
    value = None
    if not reasons:
        value, reasons = _ratio_minus(income.record, revenue.record, subtract_one=False)
    return _result(metric, reasons, value=value, subject_id=issuer_id, statement_basis=statement_basis, cutoff=cutoff,
                   target_period=period, label=label, quarter=period.quarter, records=records)


__all__ = ["REGULAR_FISCAL_YEAR_DAYS", "operating_margin", "revenue_growth"]
