"""P8-A3B — 決定論の財務の指標の拡張: 純利益率 ・ROA（時点の分母）（派生 ・非 authority ・非永続。A3A の architecture の再利用）。

凍結した A3A（`fundamental_metrics` の脚の解決 ・A2R の互換 ・Decimal の比 ・結果の組み立て）をそのまま使い、指標を 2 つ足す。
競合する指標の枠組み ・resolver ・結果の model は作らない。

- 純利益率 = 同じ期間 ・同じ基準 ・同じ区分の当期純利益（A2 の `NET_INCOME` ＝ 公式の `NP`: 親会社株主に帰属する当期純利益）／
  売上。営業利益 ・経常利益 ・他の利益で代用しない。年度と年度の初めからの累計を支え、累計は累計の期間の利益率（単独の四半期では
  ない）。売上 ≤ 0 → `UNDEFINED`。純利益が負なら負の値。
- ROA（時点の分母）= 年度の当期純利益 ／ **その年度の総資産（A2 の `TOTAL_ASSETS`。data_date は年度末）**。平均の総資産は作らない
  （期首 ・期末の平均は別の明示の契約が要る）。年度だけ。総資産 ≤ 0 → `UNDEFINED`。名前 `ROA_POINT_IN_TIME` がこの定義を示し、
  平均の総資産の ROA と呼ばない。
- 会計基準 ・連結の区分が違う ・UNKNOWN → fail closed（A2R の gate。基準の変更は不連続。P8-OBS-57）。
- revision の選択は凍結した A2 の resolver（A3A の脚の解決を経て）だけ。cutoff は明示。日付だけの知識に日の途中の cutoff は
  `INSUFFICIENT_TIME_PRECISION`。

記録: `docs/databank/PHASE8_A3B_NET_MARGIN_ROA.md`。
"""
from __future__ import annotations

from typing import Any, Optional

from .fundamental_metrics import (_Leg, _compatibility, _input_reasons, _label_for, _ratio_minus,
                                  _regular_fiscal_year, _resolve_leg, _result)
from .identity_model import SourceClass
from .metric_model import MetricKind, MetricLeg, MetricReason, MetricResult, ReasonCode
from .observation_model import FundamentalField, PeriodBasis
from .observation_resolver import ObservationQuery


def _same_period_ratio(metric: MetricKind, numerator: tuple, denominator: tuple, *, history: Any, issuer_id: Any,
                       statement_basis: Any, period: Any, cutoff: Any, semantics: Any,
                       source_class: Optional[SourceClass], fiscal_year_only: bool) -> MetricResult:
    """同じ期間の 2 つの脚の比（A3A の営業利益率と同じ手順。分子 ／ 分母、− 1 なし）。"""
    reasons = _input_reasons(history, issuer_id, statement_basis, cutoff, semantics, ((MetricLeg.PAIR, period),))
    if source_class is not None and not isinstance(source_class, SourceClass):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.INVALID_SEMANTICS_LOOKUP))
    if reasons:
        return _result(metric, reasons, value=None, subject_id=issuer_id, statement_basis=statement_basis,
                       cutoff=cutoff, target_period=period)
    label = _label_for(period)
    if label is None or (fiscal_year_only and period.basis is not PeriodBasis.FISCAL_YEAR):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.PERIOD_BASIS_UNSUPPORTED))
    if not _regular_fiscal_year(period):
        reasons.append(MetricReason(MetricLeg.PAIR, ReasonCode.FISCAL_YEAR_IRREGULAR))
    if reasons:
        return _result(metric, reasons, value=None, subject_id=issuer_id, statement_basis=statement_basis,
                       cutoff=cutoff, target_period=period)
    top, bottom = _Leg(numerator[0]), _Leg(denominator[0])
    for leg, field in ((bottom, denominator[1]), (top, numerator[1])):
        _resolve_leg(history, leg, ObservationQuery.actual(issuer_id, field, statement_basis, period,
                                                           source_class=source_class), cutoff, semantics)
    reasons = bottom.reasons + top.reasons + _compatibility(bottom, top)
    records = tuple(leg.record.record_id for leg in (bottom, top) if leg.record is not None)
    value = None
    if not reasons:
        value, reasons = _ratio_minus(top.record, bottom.record, subtract_one=False)
    return _result(metric, reasons, value=value, subject_id=issuer_id, statement_basis=statement_basis, cutoff=cutoff,
                   target_period=period, label=label, quarter=period.quarter, records=records)


def net_margin(history: Any, *, issuer_id: Any, statement_basis: Any, period: Any, cutoff: Any, semantics: Any,
               source_class: Optional[SourceClass] = None) -> MetricResult:
    """純利益率 = 同じ期間の当期純利益（親会社株主に帰属）／ 売上。年度 ・累計（累計の期間の利益率）。"""
    return _same_period_ratio(MetricKind.NET_MARGIN, (MetricLeg.NET_INCOME, FundamentalField.NET_INCOME),
                              (MetricLeg.REVENUE, FundamentalField.REVENUE), history=history, issuer_id=issuer_id,
                              statement_basis=statement_basis, period=period, cutoff=cutoff, semantics=semantics,
                              source_class=source_class, fiscal_year_only=False)


def roa_point_in_time(history: Any, *, issuer_id: Any, statement_basis: Any, fiscal_year: Any, cutoff: Any,
                      semantics: Any, source_class: Optional[SourceClass] = None) -> MetricResult:
    """ROA（時点の分母）= 年度の当期純利益 ／ その年度の総資産（年度末の残高）。年度だけ。平均の総資産ではない。"""
    return _same_period_ratio(MetricKind.ROA_POINT_IN_TIME, (MetricLeg.NET_INCOME, FundamentalField.NET_INCOME),
                              (MetricLeg.TOTAL_ASSETS, FundamentalField.TOTAL_ASSETS), history=history,
                              issuer_id=issuer_id, statement_basis=statement_basis, period=fiscal_year, cutoff=cutoff,
                              semantics=semantics, source_class=source_class, fiscal_year_only=True)


__all__ = ["net_margin", "roa_point_in_time"]
