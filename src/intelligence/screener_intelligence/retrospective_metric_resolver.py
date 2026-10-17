"""P8-A3-RA — 遡及の provider authority の上の財務の指標（派生 ・非 authority ・非永続。凍結 A3 の式をそのまま使う）。

STRICT A3（`fundamental_metrics` ・`fundamental_metrics_extended`）と同じ 4 つの指標の定義の、**別の解決の mode**。
- STRICT: 世界 ／ PIT の authority（cutoff）で真に解けたか。
- RETROSPECTIVE: 明示の後の authority（`authority_as_of`）で選んだ provider の保持 epoch（A2C-R）から何を再構成できるか。
どちらかを黙って他方に代えない。

監督の決定 R1: 式 ・比 ・Decimal ・丸め ・通貨 ・分母 ・期間の関係 ・規則的な年度 ・A2R の互換 ・結果の組み立ては、凍結 `fundamental_metrics` の
純 helper（`_ratio_minus` ・`_compatibility` ・`_period_relation` ・`_label_for` ・`_regular_fiscal_year` ・`_input_reasons` ・
`_result` ・`_Leg`。
A3B と同じ in-package の sanctioned な再利用）だけが持つ。本 module はそれを**複製しない**。`_resolve_leg` は STRICT の `resolve` を内側で
呼ぶため使わず、脚の解決は凍結 `resolve_retrospective` に、解決後の注記（A2R の注記の有無 ・整合 ・値の状態）だけを `_annotate` が
同じ順で再述する（parity は test が pin）。

- 外側の結果 `RetrospectiveMetricResult` が authority の意味を持つ: `resolution_mode` ・`authority_as_of` ・`identity_valid_at` ・脚ごとの
  provenance（観測 id ・保持 epoch の参照 ・manifest の参照 ・遡及の status ・diagnostic）。内側の凍結 `MetricResult` は、凍結の語彙が
  結果を**真に**表せる時だけ入れる（値 ・VALUE_ABSENT ・NOT_FOUND ・coverage の外 ・基準 ／ 区分の不一致 ・分母 0）。SEMANTIC_HOLD ・
  manifest ／ membership の失敗 ・同じ期間の epoch の不一致は NOT_FOUND ／ VALUE_ABSENT に写さず、外側だけが持つ（内側は None）。
- 同じ期間の全脚は同じ `coverage_epoch_id` でなければならない（違えば `AMBIGUOUS_AUTHORITY`。黙って混ぜない）。売上成長率の
  target と comparison は別の epoch でよい（それぞれ記録する）。
- 4 指標だけ。TTM ・年率化 ・4Q の橋渡し ・平均総資産 ・基準 ／ 区分の橋渡しは無い。時計 ・network ・IO ・保存 ・float は無い。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .fundamental_metrics import (_Leg, _compatibility, _input_reasons, _label_for, _period_relation, _ratio_minus,
                                  _regular_fiscal_year, _result)
from .metric_model import (DERIVED_NON_AUTHORITY_NON_PERSISTENT, MetricKind, MetricLeg, MetricReason, MetricResult,
                           MetricStatus, ReasonCode)
from .observation_model import (FundamentalField, ObservationHistory, ObservationModelError, PeriodBasis,
                                ReportingPeriod, StatementBasis, ValueState)
from .observation_resolver import ObservationQuery, ObservationStatus
from .observation_retrospective_resolver import RESOLUTION_MODE, resolve_retrospective
from .observation_semantics_model import ObservationSemantics
from ..core.time import to_utc_iso

RETROSPECTIVE_METRIC_RULES_VERSION = "p8_retrospective_metrics:0.1.0"
#: 同じ期間の全脚が 1 つの保持 epoch を共有する規則
SAME_PERIOD_EPOCH_RULE = "ALL_LEGS_OF_ONE_PERIOD_SHARE_ONE_COVERAGE_EPOCH"
#: 遡及の非 FOUND の status → 凍結 A3 の理由の code（真に表せるものだけ。それ以外は外側だけが持つ）
_INNER_CODES: Mapping[ObservationStatus, ReasonCode] = {
    ObservationStatus.NOT_FOUND: ReasonCode.NOT_FOUND, ObservationStatus.NOT_YET_KNOWN: ReasonCode.NOT_YET_KNOWN,
    ObservationStatus.AMBIGUOUS: ReasonCode.AMBIGUOUS, ObservationStatus.VALUE_ABSENT: ReasonCode.VALUE_ABSENT,
    ObservationStatus.INSUFFICIENT_TIME_PRECISION: ReasonCode.INSUFFICIENT_TIME_PRECISION,
    ObservationStatus.BEFORE_COVERAGE: ReasonCode.BEFORE_COVERAGE,
    ObservationStatus.OUTSIDE_COVERAGE: ReasonCode.OUTSIDE_COVERAGE,
    ObservationStatus.SUBJECT_NOT_RESOLVED: ReasonCode.SUBJECT_NOT_RESOLVED}
_AUTHORITY_FAILURES = (ObservationStatus.MANIFEST_MISSING, ObservationStatus.MANIFEST_CONFLICT,
                       ObservationStatus.MEMBERSHIP_INVALID)


class RetrospectiveMetricStatus(str, Enum):
    VALUE = "VALUE"
    INVALID_INPUT = "INVALID_INPUT"
    INSUFFICIENT_TIME_PRECISION = "INSUFFICIENT_TIME_PRECISION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SEMANTIC_HOLD = "SEMANTIC_HOLD"                      # 必要な脚が provider の行の保留に当たった（不在ではない）
    NOT_COMPARABLE = "NOT_COMPARABLE"
    UNDEFINED = "UNDEFINED"
    AUTHORITY_FAILURE = "AUTHORITY_FAILURE"              # manifest ／ membership の authority が成り立たない
    AMBIGUOUS_AUTHORITY = "AMBIGUOUS_AUTHORITY"          # epoch が曖昧 ／ 同じ期間の脚の epoch が違う


_INNER_TO_OUTER: Mapping[MetricStatus, RetrospectiveMetricStatus] = {
    MetricStatus.VALUE: RetrospectiveMetricStatus.VALUE,
    MetricStatus.INVALID_INPUT: RetrospectiveMetricStatus.INVALID_INPUT,
    MetricStatus.INSUFFICIENT_TIME_PRECISION: RetrospectiveMetricStatus.INSUFFICIENT_TIME_PRECISION,
    MetricStatus.INSUFFICIENT_DATA: RetrospectiveMetricStatus.INSUFFICIENT_DATA,
    MetricStatus.NOT_COMPARABLE: RetrospectiveMetricStatus.NOT_COMPARABLE,
    MetricStatus.UNDEFINED: RetrospectiveMetricStatus.UNDEFINED}
#: 外側だけの失敗の強さ（複数あれば最も強いもの）
_OUTER_PRECEDENCE = (RetrospectiveMetricStatus.INVALID_INPUT, RetrospectiveMetricStatus.AUTHORITY_FAILURE,
                     RetrospectiveMetricStatus.AMBIGUOUS_AUTHORITY, RetrospectiveMetricStatus.SEMANTIC_HOLD)
#: 凍結の語彙では表せない失敗（内側の `MetricResult` を置かない。INVALID_INPUT は凍結の語彙でも真）
_INNER_SUPPRESSING = (RetrospectiveMetricStatus.AUTHORITY_FAILURE, RetrospectiveMetricStatus.AMBIGUOUS_AUTHORITY,
                      RetrospectiveMetricStatus.SEMANTIC_HOLD)


@dataclass(frozen=True)
class LegProvenance:
    """1 つの脚の遡及の provenance（値は持たない）。"""

    leg: MetricLeg
    field: FundamentalField
    period_end: str                                      # ISO の日付（期間の末日）
    status: Optional[ObservationStatus]                  # None ＝ 軸 ・像の構造の違反で解決に至らない
    diagnostic: str = ""
    observation_id: str = ""
    coverage_epoch_id: str = ""                          # 選んだ `ProviderHoldingsCoverage.reference`（jq.pvh:）
    coverage_record_ids: Tuple[str, ...] = ()
    manifest_ref: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"coverage_epoch_id": self.coverage_epoch_id, "coverage_record_ids": list(self.coverage_record_ids),
                "diagnostic": self.diagnostic, "field": self.field.value, "leg": self.leg.value,
                "manifest_ref": self.manifest_ref, "observation_id": self.observation_id,
                "period_end": self.period_end, "status": self.status.value if self.status is not None else None}


@dataclass(frozen=True, kw_only=True)
class RetrospectiveMetricResult:
    """遡及の指標の結果（派生 ・非 authority ・非永続。record id ・保存は無い）。"""

    metric: MetricKind
    status: RetrospectiveMetricStatus
    subject_id: str
    statement_basis: Optional[StatementBasis]
    target_period: Optional[ReportingPeriod]
    comparison_period: Optional[ReportingPeriod]
    authority_as_of: Optional[datetime]
    identity_valid_at: Optional[datetime]
    value: Optional[str]
    metric_result: Optional[MetricResult]
    legs: Tuple[LegProvenance, ...]
    diagnostics: Tuple[str, ...]
    resolution_mode: str = RESOLUTION_MODE
    rules_version: str = RETROSPECTIVE_METRIC_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    @property
    def observation_ids(self) -> Tuple[str, ...]:
        return tuple(leg.observation_id for leg in self.legs if leg.observation_id)

    @property
    def coverage_epoch_ids(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for leg in self.legs:
            if leg.coverage_epoch_id and leg.coverage_epoch_id not in seen:
                seen.append(leg.coverage_epoch_id)
        return tuple(seen)

    @property
    def manifest_refs(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for leg in self.legs:
            if leg.manifest_ref and leg.manifest_ref not in seen:
                seen.append(leg.manifest_ref)
        return tuple(seen)

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_as_of": to_utc_iso(self.authority_as_of) if self.authority_as_of is not None else None,
                "authority_class": self.authority_class,
                "comparison_period": self.comparison_period.as_dict() if self.comparison_period else None,
                "coverage_epoch_ids": list(self.coverage_epoch_ids), "diagnostics": list(self.diagnostics),
                "identity_valid_at": to_utc_iso(self.identity_valid_at) if self.identity_valid_at is not None else None,
                "legs": [leg.as_dict() for leg in self.legs], "manifest_refs": list(self.manifest_refs),
                "metric": self.metric.value,
                "metric_result": self.metric_result.as_dict() if self.metric_result is not None else None,
                "observation_ids": list(self.observation_ids), "resolution_mode": self.resolution_mode,
                "rules_version": self.rules_version,
                "statement_basis": self.statement_basis.value if self.statement_basis else None,
                "status": self.status.value, "subject_id": self.subject_id,
                "target_period": self.target_period.as_dict() if self.target_period else None, "value": self.value}


class _Authority:
    """明示の遡及の authority（時計 ・既定 ・STRICT への fallback は無い）。"""

    def __init__(self, *, authority_as_of: Any, identity_valid_at: Any, manifests: Any, corrections: Any,
                 holdings: Any) -> None:
        self.authority_as_of = authority_as_of
        self.identity_valid_at = identity_valid_at
        self.manifests = manifests
        self.corrections = corrections
        self.holdings = holdings


def _aware(value: Any) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None


def _annotate(leg: _Leg, record: Any, semantics: Mapping[str, Any]) -> None:
    """解決**後**の注記（凍結 `_resolve_leg` の resolve の後の部分と同じ順 ・同じ判定。parity は test が pin）。"""
    leg.record = record
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


def _manifest_ref(holdings: Any, subject_id: str, coverage_epoch_id: str) -> str:
    """選んだ保持 epoch の manifest の参照（保持の像の公開の読み口 `for_subject` だけ。無ければ空）。"""
    if not coverage_epoch_id:
        return ""
    for record in holdings.for_subject(subject_id):
        if record.reference == coverage_epoch_id:
            return record.manifest_ref
    return ""


class _RetroLeg:
    """脚 ＋ その遡及の provenance ＋ 外側だけの失敗。"""

    def __init__(self, leg: MetricLeg, field: FundamentalField, period: ReportingPeriod) -> None:
        self.inner = _Leg(leg)
        self.field = field
        self.period = period
        self.provenance: Optional[LegProvenance] = None
        self.outer: Optional[RetrospectiveMetricStatus] = None
        self.diagnostic = ""

    def bind(self, history: ObservationHistory, subject_id: str, basis: StatementBasis, authority: _Authority,
                semantics: Mapping[str, Any]) -> None:
        query = ObservationQuery.actual(subject_id, self.field, basis, self.period)
        try:
            resolution = resolve_retrospective(history, query, authority_as_of=authority.authority_as_of,
                                               identity_valid_at=authority.identity_valid_at,
                                               manifests=authority.manifests, corrections=authority.corrections,
                                               holdings=authority.holdings)
        except ObservationModelError as exc:                                   # 軸 ・像の構造の違反 → 入力の誤り
            self.outer, self.diagnostic = RetrospectiveMetricStatus.INVALID_INPUT, exc.code
            self.provenance = LegProvenance(self.inner.leg, self.field, self.period.period_end.isoformat(), None,
                                            diagnostic=exc.code)
            return
        self.diagnostic = resolution.diagnostic
        self.provenance = LegProvenance(
            self.inner.leg, self.field, self.period.period_end.isoformat(), resolution.status,
            diagnostic=resolution.diagnostic,
            observation_id=resolution.record.record_id if resolution.record is not None else "",
            coverage_epoch_id=resolution.coverage_epoch_id, coverage_record_ids=resolution.coverage_record_ids,
            manifest_ref=_manifest_ref(authority.holdings, subject_id, resolution.coverage_epoch_id))
        if resolution.status is ObservationStatus.FOUND:
            _annotate(self.inner, resolution.record, semantics)
        elif resolution.status is ObservationStatus.SEMANTIC_HOLD:
            self.outer = RetrospectiveMetricStatus.SEMANTIC_HOLD
        elif resolution.status in _AUTHORITY_FAILURES:
            self.outer = RetrospectiveMetricStatus.AUTHORITY_FAILURE
        elif resolution.status is ObservationStatus.AMBIGUOUS:
            self.outer = RetrospectiveMetricStatus.AMBIGUOUS_AUTHORITY
            self.inner.fail(_INNER_CODES[resolution.status])
        else:
            self.inner.fail(_INNER_CODES.get(resolution.status, ReasonCode.NOT_FOUND))


def _epoch_disagreement(legs: Tuple[_RetroLeg, ...]) -> List[str]:
    """同じ期間の脚ごとに、選んだ epoch が 1 つであることを求める（期間が違う脚どうしは比べない）。"""
    by_period: Dict[str, set] = {}
    for leg in legs:
        if leg.provenance is not None and leg.provenance.coverage_epoch_id:
            by_period.setdefault(leg.provenance.period_end, set()).add(leg.provenance.coverage_epoch_id)
    return [f"SAME_PERIOD_EPOCH_MISMATCH:{period_end}" for period_end, epochs in sorted(by_period.items())
            if len(epochs) > 1]


def _wrap(metric: MetricKind, inner: Optional[MetricResult], legs: Tuple[_RetroLeg, ...], *, subject_id: Any,
          statement_basis: Any, target_period: Any, comparison_period: Any, authority: _Authority,
          outer_only: List[Tuple[RetrospectiveMetricStatus, str]]) -> RetrospectiveMetricResult:
    diagnostics = [":".join((leg.inner.leg.value, leg.provenance.status.value if leg.provenance.status is not None
                             else RetrospectiveMetricStatus.INVALID_INPUT.value, leg.provenance.diagnostic)).rstrip(":")
                   for leg in legs
                   if leg.provenance is not None and leg.provenance.status is not ObservationStatus.FOUND]
    diagnostics.extend(text for _, text in outer_only if text)
    statuses = [status for status, _ in outer_only]
    status = next((s for s in _OUTER_PRECEDENCE if s in statuses), None)
    if status is None:
        status = _INNER_TO_OUTER[inner.status] if inner is not None else RetrospectiveMetricStatus.INSUFFICIENT_DATA
    if status in _INNER_SUPPRESSING:
        inner = None                                                       # 外側だけの失敗では内側を嘘にしない
    value = inner.value if inner is not None and inner.status is MetricStatus.VALUE else None
    return RetrospectiveMetricResult(
        metric=metric, status=status, subject_id=subject_id if isinstance(subject_id, str) else "",
        statement_basis=statement_basis if isinstance(statement_basis, StatementBasis) else None,
        target_period=target_period if isinstance(target_period, ReportingPeriod) else None,
        comparison_period=comparison_period if isinstance(comparison_period, ReportingPeriod) else None,
        authority_as_of=authority.authority_as_of if _aware(authority.authority_as_of) else None,
        identity_valid_at=authority.identity_valid_at if _aware(authority.identity_valid_at) else None,
        value=value, metric_result=inner,
        legs=tuple(leg.provenance for leg in legs if leg.provenance is not None), diagnostics=tuple(diagnostics))


def _authority_reasons(authority: _Authority) -> List[Tuple[RetrospectiveMetricStatus, str]]:
    reasons: List[Tuple[RetrospectiveMetricStatus, str]] = []
    if not _aware(authority.identity_valid_at):
        reasons.append((RetrospectiveMetricStatus.INVALID_INPUT, "IDENTITY_VALID_AT_REQUIRED"))
    if not (hasattr(authority.holdings, "for_subject") and callable(authority.holdings.for_subject)):
        reasons.append((RetrospectiveMetricStatus.INVALID_INPUT, "HOLDINGS_VIEW_REQUIRED"))
    if not (hasattr(authority.manifests, "by_acquisition") and callable(authority.manifests.by_acquisition)):
        reasons.append((RetrospectiveMetricStatus.INVALID_INPUT, "MANIFEST_VIEW_REQUIRED"))
    if authority.corrections is None:
        reasons.append((RetrospectiveMetricStatus.INVALID_INPUT, "CORRECTION_AUTHORITY_REQUIRED"))
    return reasons


def _finish(metric: MetricKind, legs: Tuple[_RetroLeg, ...], *, numerator: _RetroLeg, denominator: _RetroLeg,
            subtract_one: bool, history: Any, subject_id: Any, statement_basis: Any, authority: _Authority,
            semantics: Any, target_period: Any, comparison_period: Any = None, label: Any = None,
            quarter: int = 0) -> RetrospectiveMetricResult:
    """全脚を遡及で解き、凍結の互換 ・比 ・結果の組み立てに渡す。外側だけの失敗は内側を作らない。"""
    for leg in legs:
        leg.bind(history, subject_id, statement_basis, authority, semantics)
    outer_only = [(leg.outer, "") for leg in legs if leg.outer is not None]     # 脚の diagnostic は provenance が持つ
    outer_only.extend((RetrospectiveMetricStatus.AMBIGUOUS_AUTHORITY, text) for text in _epoch_disagreement(legs))
    inner_legs = tuple(leg.inner for leg in legs)
    reasons: List[MetricReason] = [reason for leg in inner_legs for reason in leg.reasons]
    reasons += _compatibility(inner_legs[0], inner_legs[1])
    records = tuple(leg.record.record_id for leg in inner_legs if leg.record is not None)
    value = None
    if not reasons and not outer_only:
        value, reasons = _ratio_minus(numerator.inner.record, denominator.inner.record, subtract_one=subtract_one)
    inner = None
    if not outer_only:
        inner = _result(metric, reasons, value=value, subject_id=subject_id, statement_basis=statement_basis,
                        cutoff=authority.authority_as_of, target_period=target_period,
                        comparison_period=comparison_period, label=label, quarter=quarter, records=records)
    return _wrap(metric, inner, legs, subject_id=subject_id, statement_basis=statement_basis,
                 target_period=target_period, comparison_period=comparison_period, authority=authority,
                 outer_only=outer_only)


def _invalid(metric: MetricKind, reasons: List[MetricReason], outer_only: List[Tuple[RetrospectiveMetricStatus, str]],
             *, subject_id: Any, statement_basis: Any, authority: _Authority, target_period: Any,
             comparison_period: Any = None) -> RetrospectiveMetricResult:
    inner = _result(metric, reasons, value=None, subject_id=subject_id, statement_basis=statement_basis,
                    cutoff=authority.authority_as_of, target_period=target_period,
                    comparison_period=comparison_period) if reasons else None
    return _wrap(metric, inner, (), subject_id=subject_id, statement_basis=statement_basis,
                 target_period=target_period, comparison_period=comparison_period, authority=authority,
                 outer_only=outer_only)


def _same_period_quotient(metric: MetricKind, numerator: Tuple[MetricLeg, FundamentalField],
                       denominator: Tuple[MetricLeg, FundamentalField], *, history: Any, subject_id: Any,
                       statement_basis: Any, period: Any, authority: _Authority, semantics: Any,
                       fiscal_year_only: bool) -> RetrospectiveMetricResult:
    """同じ期間の 2 つの脚の比（凍結 A3B `_same_period_quotient` と同じ手順 ・同じ期間の検査。脚の解決だけ遡及）。"""
    reasons = _input_reasons(history, subject_id, statement_basis, authority.authority_as_of, semantics,
                             ((MetricLeg.PAIR, period),))
    outer_only = _authority_reasons(authority)
    if reasons or outer_only:
        return _invalid(metric, reasons, outer_only, subject_id=subject_id, statement_basis=statement_basis,
                        authority=authority, target_period=period)
    label = _label_for(period)
    if label is None or (fiscal_year_only and period.basis is not PeriodBasis.FISCAL_YEAR):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.PERIOD_BASIS_UNSUPPORTED))
    if not _regular_fiscal_year(period):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.FISCAL_YEAR_IRREGULAR))
    if reasons:
        return _invalid(metric, reasons, [], subject_id=subject_id, statement_basis=statement_basis,
                        authority=authority, target_period=period)
    bottom = _RetroLeg(denominator[0], denominator[1], period)
    top = _RetroLeg(numerator[0], numerator[1], period)
    return _finish(metric, (bottom, top), numerator=top, denominator=bottom, subtract_one=False, history=history,
                   subject_id=subject_id, statement_basis=statement_basis, authority=authority, semantics=semantics,
                   target_period=period, label=label, quarter=period.quarter)


def operating_margin_retrospective(history: Any, *, subject_id: Any, statement_basis: Any, period: Any,
                                   authority_as_of: Any, identity_valid_at: Any, manifests: Any, corrections: Any,
                                   holdings: Any, semantics: Any) -> RetrospectiveMetricResult:
    """営業利益率 = 同じ期間 ・同じ区分の営業利益 ／ 売上（凍結 A3A の式。脚は遡及で解く）。"""
    authority = _Authority(authority_as_of=authority_as_of, identity_valid_at=identity_valid_at, manifests=manifests,
                           corrections=corrections, holdings=holdings)
    return _same_period_quotient(MetricKind.OPERATING_MARGIN,
                              (MetricLeg.OPERATING_INCOME, FundamentalField.OPERATING_INCOME),
                              (MetricLeg.REVENUE, FundamentalField.REVENUE), history=history, subject_id=subject_id,
                              statement_basis=statement_basis, period=period, authority=authority, semantics=semantics,
                              fiscal_year_only=False)


def net_margin_retrospective(history: Any, *, subject_id: Any, statement_basis: Any, period: Any, authority_as_of: Any,
                             identity_valid_at: Any, manifests: Any, corrections: Any, holdings: Any,
                             semantics: Any) -> RetrospectiveMetricResult:
    """純利益率 = 同じ期間の当期純利益 ／ 売上（凍結 A3B の式。脚は遡及で解く）。"""
    authority = _Authority(authority_as_of=authority_as_of, identity_valid_at=identity_valid_at, manifests=manifests,
                           corrections=corrections, holdings=holdings)
    return _same_period_quotient(MetricKind.NET_MARGIN, (MetricLeg.NET_INCOME, FundamentalField.NET_INCOME),
                              (MetricLeg.REVENUE, FundamentalField.REVENUE), history=history, subject_id=subject_id,
                              statement_basis=statement_basis, period=period, authority=authority, semantics=semantics,
                              fiscal_year_only=False)


def roa_point_in_time_retrospective(history: Any, *, subject_id: Any, statement_basis: Any, fiscal_year: Any,
                                    authority_as_of: Any, identity_valid_at: Any, manifests: Any, corrections: Any,
                                    holdings: Any, semantics: Any) -> RetrospectiveMetricResult:
    """ROA（時点の分母）= 年度の当期純利益 ／ その年度の総資産（凍結 A3B の式。年度だけ。平均総資産なし）。"""
    authority = _Authority(authority_as_of=authority_as_of, identity_valid_at=identity_valid_at, manifests=manifests,
                           corrections=corrections, holdings=holdings)
    return _same_period_quotient(MetricKind.ROA_POINT_IN_TIME, (MetricLeg.NET_INCOME, FundamentalField.NET_INCOME),
                              (MetricLeg.TOTAL_ASSETS, FundamentalField.TOTAL_ASSETS), history=history,
                              subject_id=subject_id, statement_basis=statement_basis, period=fiscal_year,
                              authority=authority, semantics=semantics, fiscal_year_only=True)


def revenue_growth_retrospective(history: Any, *, subject_id: Any, statement_basis: Any, target_period: Any,
                                 comparison_period: Any, authority_as_of: Any, identity_valid_at: Any, manifests: Any,
                                 corrections: Any, holdings: Any, semantics: Any) -> RetrospectiveMetricResult:
    """売上成長率 = target の売上 ／ comparison の売上 − 1（凍結 A3A の期間の関係 ・式。2 つの期間は別の epoch でよい）。"""
    metric = MetricKind.REVENUE_GROWTH
    authority = _Authority(authority_as_of=authority_as_of, identity_valid_at=identity_valid_at, manifests=manifests,
                           corrections=corrections, holdings=holdings)
    reasons = _input_reasons(history, subject_id, statement_basis, authority_as_of, semantics,
                             ((MetricLeg.TARGET, target_period), (MetricLeg.COMPARISON, comparison_period)))
    outer_only = _authority_reasons(authority)
    if reasons or outer_only:
        return _invalid(metric, reasons, outer_only, subject_id=subject_id, statement_basis=statement_basis,
                        authority=authority, target_period=target_period, comparison_period=comparison_period)
    reasons.extend(_period_relation(target_period, comparison_period))
    if reasons:
        return _invalid(metric, reasons, [], subject_id=subject_id, statement_basis=statement_basis,
                        authority=authority, target_period=target_period, comparison_period=comparison_period)
    target = _RetroLeg(MetricLeg.TARGET, FundamentalField.REVENUE, target_period)
    comparison = _RetroLeg(MetricLeg.COMPARISON, FundamentalField.REVENUE, comparison_period)
    return _finish(metric, (target, comparison), numerator=target, denominator=comparison, subtract_one=True,
                   history=history, subject_id=subject_id, statement_basis=statement_basis, authority=authority,
                   semantics=semantics, target_period=target_period, comparison_period=comparison_period,
                   label=_label_for(target_period), quarter=target_period.quarter)


def resolve_retrospective_metric(metric: Any, history: Any, *, subject_id: Any, statement_basis: Any,
                                 target_period: Any, authority_as_of: Any, identity_valid_at: Any, manifests: Any,
                                 corrections: Any, holdings: Any, semantics: Any,
                                 comparison_period: Any = None) -> RetrospectiveMetricResult:
    """4 指標の入口（それ以外の `metric` は受けない）。"""
    if not isinstance(metric, MetricKind):
        raise ObservationModelError("UNSUPPORTED_METRIC", "retrospective metrics cover the four frozen A3 kinds only")
    common = dict(subject_id=subject_id, statement_basis=statement_basis, authority_as_of=authority_as_of,
                  identity_valid_at=identity_valid_at, manifests=manifests, corrections=corrections, holdings=holdings,
                  semantics=semantics)
    if metric is MetricKind.REVENUE_GROWTH:
        return revenue_growth_retrospective(history, target_period=target_period, comparison_period=comparison_period,
                                            **common)
    if metric is MetricKind.OPERATING_MARGIN:
        return operating_margin_retrospective(history, period=target_period, **common)
    if metric is MetricKind.NET_MARGIN:
        return net_margin_retrospective(history, period=target_period, **common)
    return roa_point_in_time_retrospective(history, fiscal_year=target_period, **common)


__all__ = ["RETROSPECTIVE_METRIC_RULES_VERSION", "SAME_PERIOD_EPOCH_RULE", "LegProvenance", "RetrospectiveMetricResult",
           "RetrospectiveMetricStatus", "net_margin_retrospective", "operating_margin_retrospective",
           "resolve_retrospective_metric", "revenue_growth_retrospective", "roa_point_in_time_retrospective"]
