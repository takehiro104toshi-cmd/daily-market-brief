"""P8-B2 — 財務の基準の決定論の評価器（凍結 B1 の model の上。式 ・順位 ・推奨 ・保存 ・Theme は無い）。

答える問い: 「この発行体は、名前と版のある人が書いた財務の方針を、明示の authority mode と評価の文脈の下で満たすか」だけ。
良い会社か ・買うべきか ・魅力 ・最良 ・順位 ・期待 return は答えない。

- 脚の解決は凍結の入口だけ。STRICT_PIT は凍結 A3（`operating_margin` ・`net_margin` ・`roa_point_in_time` ・`revenue_growth`。
  cutoff ＝ `evaluation_as_of`）。RETROSPECTIVE_PROVIDER_AUTHORITY は凍結 A3-RA `resolve_retrospective_metric`
  （`authority_as_of` ＝ `evaluation_as_of`、`identity_valid_at` は文脈のまま、保持 ・manifest ・A1R の修正の authority ・A2R の
  注記は明示）。式 ・private helper ・保持の解決の複製は無い。mode 間の fallback は無い。方針と文脈の mode が違えば
  `AUTHORITY_FAILURE / POLICY_AUTHORITY_MODE_MISMATCH`（例外ではなく結果）。
- target の期間は型つきの規則（凍結 B1 `PeriodRule`）で、authority に見える期間だけから選ぶ。RETROSPECTIVE は保持 record
  （`holdings_as_of <= evaluation_as_of`）× 結び付いた manifest の CANONICAL の期間、STRICT は cutoff までに確かに知られた観測の
  期間。journal の順 ・任意の fallback は無い。無ければ `NOT_EVALUABLE / TARGET_UNAVAILABLE`、同じ period_end に意味の違う期間が
  複数なら `NOT_EVALUABLE / TARGET_AMBIGUOUS`。売上成長率は凍結 A3 の期間の関係の code が無い最初の対（私的な遡及 E2E runner と同じ
  意味。test が runner の選択との一致を pin する。runtime は runner を import しない）。
- 比較は Decimal だけ（LT ・LE ・GT ・GE ・BETWEEN は両端を含む）。丸め ・epsilon ・距離 ・点数は無い。
- ALL_OF の集約の優先: AUTHORITY_FAILURE ＞ HOLD ＞ NO_MATCH ＞ NOT_EVALUABLE ＞ 全基準 MATCH の時だけ MATCH。全基準を評価する
  （短絡しない）。
- provenance は凍結の authority が返したものだけを写す（観測 id ・保持 epoch の参照 ・manifest の参照 ・期間 ・内側の status ・
  理由）。観測値は結果の private の表面だけ。
記録: `docs/databank/PHASE8_B2_FINANCIAL_CRITERIA_EVALUATOR.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .fundamental_metrics import operating_margin, revenue_growth
from .fundamental_metrics_extended import net_margin, roa_point_in_time
from .metric_model import MetricKind, MetricResult, MetricStatus, ReasonCode
from .observation_model import FundamentalActual, ObservationHistory, PeriodBasis, ReportingPeriod
from .retrospective_metric_resolver import (RetrospectiveMetricResult, RetrospectiveMetricStatus,
                                            resolve_retrospective_metric)
from .screener_criteria_model import (SCREENER_RULES_VERSION, CriteriaComposition, CriteriaPolicy, Criterion,
                                      CriterionOperator, CriterionResult, CriterionState, EvaluationContext,
                                      PeriodRule, ScreenerAuthorityMode, ScreenerDimension, ScreenerResult,
                                      ScreenerState, completeness_of)

EVALUATOR_RULES_VERSION = "p8_screener_evaluator:0.1.0"
#: ALL_OF の集約の優先（固定。他の状態は無い）
AGGREGATION_PRECEDENCE: Tuple[ScreenerState, ...] = (ScreenerState.AUTHORITY_FAILURE, ScreenerState.HOLD,
                                                      ScreenerState.NO_MATCH, ScreenerState.NOT_EVALUABLE)
#: 比較の規則: Decimal だけ ・BETWEEN は両端を含む ・丸め ・epsilon ・距離なし
COMPARISON_RULE = "DECIMAL_ONLY_INCLUSIVE_BETWEEN_NO_ROUNDING_NO_TOLERANCE"
#: target の期間が選べる期間の種類（凍結 A3 の `_label_for` と同じ: 年度と年度の初めからの累計）
SUPPORTED_TARGET_BASES: Tuple[PeriodBasis, ...] = (PeriodBasis.FISCAL_YEAR, PeriodBasis.CUMULATIVE_YEAR_TO_DATE)
#: 凍結 A3 の期間の関係の理由（売上成長率の comparable な prior の判定に読む。式 ・関係は複製しない）
PERIOD_RELATION_CODES: Tuple[ReasonCode, ...] = (ReasonCode.PERIOD_BASIS_UNSUPPORTED, ReasonCode.FISCAL_YEAR_IRREGULAR,
                                                 ReasonCode.PERIOD_BASIS_MISMATCH, ReasonCode.PERIOD_QUARTER_DIFFERS,
                                                 ReasonCode.PERIOD_NOT_ADJACENT)
_RETRO_STATES: Mapping[RetrospectiveMetricStatus, CriterionState] = {
    RetrospectiveMetricStatus.SEMANTIC_HOLD: CriterionState.HOLD,
    RetrospectiveMetricStatus.INSUFFICIENT_DATA: CriterionState.NOT_EVALUABLE,
    RetrospectiveMetricStatus.INSUFFICIENT_TIME_PRECISION: CriterionState.NOT_EVALUABLE,
    RetrospectiveMetricStatus.NOT_COMPARABLE: CriterionState.NOT_EVALUABLE,
    RetrospectiveMetricStatus.UNDEFINED: CriterionState.NOT_EVALUABLE,
    RetrospectiveMetricStatus.AUTHORITY_FAILURE: CriterionState.AUTHORITY_FAILURE,
    RetrospectiveMetricStatus.AMBIGUOUS_AUTHORITY: CriterionState.AUTHORITY_FAILURE,
    RetrospectiveMetricStatus.INVALID_INPUT: CriterionState.AUTHORITY_FAILURE}
_STRICT_STATES: Mapping[MetricStatus, CriterionState] = {
    MetricStatus.INSUFFICIENT_DATA: CriterionState.NOT_EVALUABLE,
    MetricStatus.INSUFFICIENT_TIME_PRECISION: CriterionState.NOT_EVALUABLE,
    MetricStatus.NOT_COMPARABLE: CriterionState.NOT_EVALUABLE,
    MetricStatus.UNDEFINED: CriterionState.NOT_EVALUABLE,
    MetricStatus.INVALID_INPUT: CriterionState.AUTHORITY_FAILURE}


class ScreenerEvaluationError(ValueError):
    """評価の契約の違反（B1 の構築が防ぐはずの入力 ・像の欠落）。authority の失敗は例外ではなく結果。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ScreenerEvaluationError(code, detail)


@dataclass(frozen=True, kw_only=True)
class EvaluationInputs:
    """評価の runtime の像（意味の文脈は凍結 B1 `EvaluationContext`）。STRICT は history ・semantics、RETROSPECTIVE はさらに保持 ・manifest ・
    A1R の修正の authority。像は読むだけ。"""

    history: ObservationHistory
    semantics: Mapping[str, Any]
    holdings: Any = None
    manifests: Any = None
    corrections: Any = None

    def __post_init__(self) -> None:
        _require(isinstance(self.history, ObservationHistory), "INVALID_HISTORY", "history")
        _require(isinstance(self.semantics, Mapping), "INVALID_SEMANTICS_LOOKUP", "semantics")

    def retrospective_views_present(self) -> bool:
        return (self.holdings is not None and hasattr(self.holdings, "for_subject")
                and self.manifests is not None and hasattr(self.manifests, "by_acquisition")
                and self.corrections is not None)


# ---------------------------------------------------------------- target の期間（authority に見える期間だけ ・意味で選ぶ）


def visible_periods(criterion: Criterion, context: EvaluationContext, inputs: EvaluationInputs) -> Dict[date, Set[Any]]:
    """period_end → 候補の `ReportingPeriod` の集合。RETROSPECTIVE: 保持 record（`holdings_as_of <= evaluation_as_of`）× 結び付いた
    manifest の CANONICAL の entry（同じ period_end ・同じ区分）。STRICT: cutoff までに確かに知られた主語 ・区分の観測の期間。"""
    found: Dict[date, Set[Any]] = {}
    if context.authority_mode is ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY:
        for record in inputs.holdings.for_subject(context.subject_id):
            if record.holdings_as_of > context.evaluation_as_of:
                continue
            manifest = inputs.manifests.by_acquisition(record.acquisition_ref)
            if manifest is None:
                continue                                                         # authority の失敗は A3-RA が報告する
            for entry in manifest.entries:
                if entry.disposition.value == "CANONICAL" and entry.period is not None \
                        and entry.period.period_end == record.period_end \
                        and entry.statement_basis is criterion.statement_basis:
                    found.setdefault(record.period_end, set()).add(entry.period)
        return found
    for record in inputs.history.records:
        if isinstance(record, FundamentalActual) and record.subject == context.subject_id \
                and record.statement_basis is criterion.statement_basis \
                and record.knowledge.certain_by <= context.evaluation_as_of:
            found.setdefault(record.period.period_end, set()).add(record.period)
    return found


def select_target(periods: Mapping[date, Set[Any]], rule: PeriodRule) -> Tuple[Optional[ReportingPeriod], str]:
    """単一の期間の規則: period_end の降順で最初の支える候補。同じ period_end に意味の違う期間が複数なら曖昧（選ばない）。"""
    bases = (PeriodBasis.FISCAL_YEAR,) if rule is PeriodRule.NEWEST_FY else SUPPORTED_TARGET_BASES
    for period_end in sorted(periods, reverse=True):
        supported = {p for p in periods[period_end] if p.basis in bases}
        if not supported:
            continue
        if len(supported) != 1:
            return None, "TARGET_AMBIGUOUS"
        return next(iter(supported)), ""
    return None, "TARGET_UNAVAILABLE"


def _unique_supported(periods: Mapping[date, Set[Any]], period_end: date) -> Optional[ReportingPeriod]:
    supported = {p for p in periods[period_end] if p.basis in SUPPORTED_TARGET_BASES}
    return next(iter(supported)) if len(supported) == 1 else None


# ---------------------------------------------------------------- 凍結の入口


def _strict(criterion: Criterion, context: EvaluationContext, inputs: EvaluationInputs, target: ReportingPeriod,
            comparison: Optional[ReportingPeriod]) -> MetricResult:
    common = dict(issuer_id=context.subject_id, statement_basis=criterion.statement_basis,
                  cutoff=context.evaluation_as_of, semantics=inputs.semantics)
    if criterion.metric is MetricKind.REVENUE_GROWTH:
        return revenue_growth(inputs.history, target_period=target, comparison_period=comparison, **common)
    if criterion.metric is MetricKind.OPERATING_MARGIN:
        return operating_margin(inputs.history, period=target, **common)
    if criterion.metric is MetricKind.NET_MARGIN:
        return net_margin(inputs.history, period=target, **common)
    return roa_point_in_time(inputs.history, fiscal_year=target, **common)


def _retrospective(criterion: Criterion, context: EvaluationContext, inputs: EvaluationInputs,
                   target: ReportingPeriod, comparison: Optional[ReportingPeriod]) -> RetrospectiveMetricResult:
    return resolve_retrospective_metric(criterion.metric, inputs.history, subject_id=context.subject_id,
                                        statement_basis=criterion.statement_basis, target_period=target,
                                        comparison_period=comparison, authority_as_of=context.evaluation_as_of,
                                        identity_valid_at=context.identity_valid_at, manifests=inputs.manifests,
                                        corrections=inputs.corrections, holdings=inputs.holdings,
                                        semantics=inputs.semantics)


def _inner(result: Any) -> Optional[MetricResult]:
    return result if isinstance(result, MetricResult) else result.metric_result


def _relation_rejected(result: Any) -> bool:
    inner = _inner(result)
    return inner is not None and any(reason.code in PERIOD_RELATION_CODES for reason in inner.reasons)


# ---------------------------------------------------------------- 比較（Decimal だけ）


def compare(operator: CriterionOperator, value: str, threshold: str, threshold_high: Optional[str]) -> bool:
    """正準の Decimal の文字列どうしの比較。BETWEEN は両端を含む。丸め ・epsilon ・距離は無い。"""
    observed, low = Decimal(value), Decimal(threshold)
    if operator is CriterionOperator.LT:
        return observed < low
    if operator is CriterionOperator.LE:
        return observed <= low
    if operator is CriterionOperator.GT:
        return observed > low
    if operator is CriterionOperator.GE:
        return observed >= low
    _require(threshold_high is not None, "BETWEEN_REQUIRES_TWO_THRESHOLDS", "threshold_high")
    return low <= observed <= Decimal(threshold_high)


# ---------------------------------------------------------------- 1 基準の結果


def _result(criterion: Criterion, context: EvaluationContext, state: CriterionState, *, value: Optional[str] = None,
            target: Optional[ReportingPeriod] = None, comparison: Optional[ReportingPeriod] = None,
            observation_ids: Tuple[str, ...] = (), coverage_epoch_ids: Tuple[str, ...] = (),
            manifest_refs: Tuple[str, ...] = (), reasons: Any = (),
            inner_status: Optional[MetricStatus] = None) -> CriterionResult:
    valued = state in (CriterionState.MATCH, CriterionState.NO_MATCH)
    return CriterionResult(criterion_id=criterion.criterion_id, state=state, metric=criterion.metric,
                           operator=criterion.operator, threshold=criterion.threshold,
                           threshold_high=criterion.threshold_high, authority_mode=context.authority_mode,
                           has_value=valued, observed_value=value if valued else None, target_period=target,
                           comparison_period=comparison, observation_ids=observation_ids,
                           coverage_epoch_ids=coverage_epoch_ids, manifest_refs=manifest_refs,
                           reason_codes=tuple(sorted(set(reasons))), inner_metric_status=inner_status)


def _from_metric(criterion: Criterion, context: EvaluationContext, result: Any, target: ReportingPeriod,
                 comparison: Optional[ReportingPeriod]) -> CriterionResult:
    """凍結の指標の結果 → 基準の結果（status を真に写し、VALUE だけを比べる。provenance は authority のものを写すだけ）。"""
    inner = _inner(result)
    reasons: List[str] = [reason.as_text() for reason in inner.reasons] if inner is not None else []
    if isinstance(result, MetricResult):
        status, observation_ids, epochs, manifests = result.status, result.input_record_ids, (), ()
        state = CriterionState.MATCH if status is MetricStatus.VALUE else _STRICT_STATES[status]
    else:
        reasons.extend(result.diagnostics)
        observation_ids, epochs, manifests = result.observation_ids, result.coverage_epoch_ids, result.manifest_refs
        state = CriterionState.MATCH if result.status is RetrospectiveMetricStatus.VALUE \
            else _RETRO_STATES[result.status]
    value = result.value if state is CriterionState.MATCH else None
    if value is not None:
        state = CriterionState.MATCH if compare(criterion.operator, value, criterion.threshold,
                                                criterion.threshold_high) else CriterionState.NO_MATCH
    elif state is CriterionState.MATCH:                                          # VALUE なのに値が無いことは無い（契約）
        raise ScreenerEvaluationError("VALUE_WITHOUT_OBSERVED_VALUE", criterion.metric.value)
    return _result(criterion, context, state, value=value, target=target, comparison=comparison,
                   observation_ids=tuple(observation_ids), coverage_epoch_ids=tuple(epochs),
                   manifest_refs=tuple(manifests), reasons=reasons,
                   inner_status=inner.status if inner is not None else None)


def evaluate_criterion(criterion: Criterion, context: EvaluationContext, inputs: EvaluationInputs) -> CriterionResult:
    """1 基準を評価する。authority の不一致 ・target なし ・曖昧 ・保留 ・不足はすべて型つきの結果（例外ではない）。"""
    _require(isinstance(criterion, Criterion), "INVALID_CRITERION", "criterion")
    _require(isinstance(context, EvaluationContext), "INVALID_CONTEXT", "context")
    _require(isinstance(inputs, EvaluationInputs), "INVALID_INPUTS", "inputs")
    _require(criterion.dimension is ScreenerDimension.FINANCIAL, "DIMENSION_NOT_EVALUABLE", criterion.dimension.value)
    if criterion.authority_mode is not context.authority_mode:
        return _result(criterion, context, CriterionState.AUTHORITY_FAILURE,
                       reasons=("POLICY_AUTHORITY_MODE_MISMATCH",))
    if context.authority_mode is ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY:
        _require(inputs.retrospective_views_present(), "RETROSPECTIVE_INPUTS_REQUIRED",
                 "holdings/manifests/corrections")
    resolve = _retrospective if context.authority_mode is ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY \
        else _strict
    periods = visible_periods(criterion, context, inputs)
    if criterion.period_rule is not PeriodRule.NEWEST_WITH_COMPARABLE_PRIOR:
        target, code = select_target(periods, criterion.period_rule)
        if target is None:
            return _result(criterion, context, CriterionState.NOT_EVALUABLE, reasons=(code,))
        return _from_metric(criterion, context, resolve(criterion, context, inputs, target, None), target, None)
    ends = sorted(periods, reverse=True)
    for end in ends:                                                             # 売上成長率: comparable な prior を持つ最新
        supported = {p for p in periods[end] if p.basis in SUPPORTED_TARGET_BASES}
        if not supported:
            continue
        if len(supported) != 1:
            return _result(criterion, context, CriterionState.NOT_EVALUABLE, reasons=("TARGET_AMBIGUOUS",))
        target = next(iter(supported))
        for prior_end in ends:
            if prior_end >= end:
                continue
            prior = _unique_supported(periods, prior_end)
            if prior is None:
                continue
            result = resolve(criterion, context, inputs, target, prior)
            if _relation_rejected(result):
                continue                                                         # 凍結の関係が comparable と言わない
            return _from_metric(criterion, context, result, target, prior)
    code = "NO_COMPARABLE_PRIOR_PERIOD" if any(p.basis in SUPPORTED_TARGET_BASES for ps in periods.values()
                                              for p in ps) else "TARGET_UNAVAILABLE"
    return _result(criterion, context, CriterionState.NOT_EVALUABLE, reasons=(code,))


# ---------------------------------------------------------------- ALL_OF の集約


def aggregate(states: Tuple[CriterionState, ...]) -> ScreenerState:
    """固定の優先: AUTHORITY_FAILURE ＞ HOLD ＞ NO_MATCH ＞ NOT_EVALUABLE ＞ 全 MATCH の時だけ MATCH。"""
    _require(len(states) >= 1 and all(isinstance(s, CriterionState) for s in states), "INVALID_STATES", "states")
    present = {s.value for s in states}
    for outcome in AGGREGATION_PRECEDENCE:
        if outcome.value in present:
            return outcome
    return ScreenerState.MATCH


def evaluate_policy(policy: CriteriaPolicy, context: EvaluationContext, inputs: EvaluationInputs) -> ScreenerResult:
    """方針の全基準を評価し（短絡しない）、ALL_OF で集約する。完全性は凍結 B1 の data の語彙。"""
    _require(isinstance(policy, CriteriaPolicy), "INVALID_POLICY", "policy")
    _require(isinstance(context, EvaluationContext), "INVALID_CONTEXT", "context")
    _require(context.policy_id == policy.policy_id, "POLICY_CONTEXT_MISMATCH", "policy_id")
    _require(policy.composition is CriteriaComposition.ALL_OF, "COMPOSITION_UNSUPPORTED", policy.composition.value)
    results = tuple(evaluate_criterion(criterion, context, inputs) for criterion in policy.criteria)
    states = tuple(result.state for result in results)
    return ScreenerResult(subject_id=context.subject_id, policy_id=policy.policy_id, policy_version=policy.version,
                          evaluation_as_of=context.evaluation_as_of, identity_valid_at=context.identity_valid_at,
                          authority_mode=context.authority_mode, criterion_results=results, state=aggregate(states),
                          completeness=completeness_of(states), rules_version=SCREENER_RULES_VERSION)


__all__ = ["AGGREGATION_PRECEDENCE", "COMPARISON_RULE", "EVALUATOR_RULES_VERSION", "PERIOD_RELATION_CODES",
           "SUPPORTED_TARGET_BASES", "EvaluationInputs", "ScreenerEvaluationError", "aggregate", "compare",
           "evaluate_criterion", "evaluate_policy", "select_target", "visible_periods"]
