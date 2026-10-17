"""P8-B2 — 財務の基準の決定論の評価器の test。

凍結 B1 の model ・凍結 A3 STRICT ・凍結 A3-RA の上で、方針の意味の評価が「authority の不一致 → 型つきの失敗 ・authority に見える期間だけの
型つきの選択 ・Decimal だけの比較 ・ALL_OF の固定の優先 ・凍結の provenance の写し」であることを pin する。PILOT2B の runner の選択との一致は
test だけが runner を import して証明する（runtime は import しない）。
"""
from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.intelligence import jquants_pilot2_local as pl
from src.intelligence.screener_intelligence import screener_evaluator as ev
from src.intelligence.screener_intelligence.acquisition_manifest_store import ManifestStore
from src.intelligence.screener_intelligence.identity_correction_model import CorrectionHistory
from src.intelligence.screener_intelligence.metric_model import (MetricKind, MetricLeg, MetricReason, MetricResult,
                                                                 MetricStatus, ReasonCode)
from src.intelligence.screener_intelligence.observation_model import PeriodBasis
from src.intelligence.screener_intelligence.provider_holdings_store import ProviderHoldingsStore
from src.intelligence.screener_intelligence.retrospective_metric_resolver import RetrospectiveMetricStatus
from src.intelligence.screener_intelligence.screener_criteria_model import (CriterionOperator, CriterionResult,
                                                                            CriterionState, DataCompleteness,
                                                                            EvaluationContext, PeriodRule,
                                                                            ScreenerAuthorityMode, ScreenerResult,
                                                                            ScreenerState, StatementBasis,
                                                                            completeness_of)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_acquisition_manifest import ACQ1, ACQ2, CTX1, CTX2, I1, IDS
from tests.intelligence.test_screener_acquisition_manifest import root as manifest_root  # noqa: F401  fixture
from tests.intelligence.test_screener_criteria_model import criterion, policy
from tests.intelligence.test_screener_fundamental_metrics import C_2025_06, C_2026_06, FY23, FY24, FY25, World
from tests.intelligence.test_screener_fundamental_metrics import I1 as STRICT_I1
from tests.intelligence.test_screener_jquants_adapter import quarterly, row
from tests.intelligence.test_screener_observation_retrospective import history_of
from tests.intelligence.test_screener_pilot2b_retrospective_runner import q1_row
from tests.intelligence.test_screener_provider_holdings_executor import NC_BROKEN, produce
from tests.intelligence.test_screener_retrospective_metrics import PRIOR_1Q, PRIOR_FY, fy_epoch, semantics_of
from tests.intelligence.test_screener_retrospective_metrics import root  # noqa: F401  fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / PHASE8_PACKAGE / "screener_evaluator.py"
K, R, S, C = MetricKind, RetrospectiveMetricStatus, CriterionState, CriterionOperator
RETRO, STRICT = ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY, ScreenerAuthorityMode.STRICT_PIT
CONS, NC = StatementBasis.CONSOLIDATED, StatementBasis.NON_CONSOLIDATED
RULE = {K.OPERATING_MARGIN: PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE,
        K.NET_MARGIN: PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE, K.ROA_POINT_IN_TIME: PeriodRule.NEWEST_FY,
        K.REVENUE_GROWTH: PeriodRule.NEWEST_WITH_COMPARABLE_PRIOR}
#: 合成の閾値（投資の閾値ではない。harness の値 0.08 ・0.06 ・0.033333 ・0.25 の周りに置く）
T_OM, T_NM, T_ROA, T_G_LOW, T_G_HIGH = "0.05", "0.10", "0.01", "0.2", "0.3"


def crit(metric: K, operator: C = C.GE, threshold: str = T_OM, *, high=None, mode=RETRO, basis=CONS, rule=None):
    return criterion(metric=metric, operator=operator, threshold=threshold, threshold_high=high,
                     period_rule=rule or RULE[metric], authority_mode=mode, statement_basis=basis)


def four(mode=RETRO, basis=CONS):
    return (crit(K.OPERATING_MARGIN, C.GE, T_OM, mode=mode, basis=basis),
            crit(K.NET_MARGIN, C.GT, T_NM, mode=mode, basis=basis),
            crit(K.ROA_POINT_IN_TIME, C.GE, T_ROA, mode=mode, basis=basis),
            crit(K.REVENUE_GROWTH, C.BETWEEN, T_G_LOW, high=T_G_HIGH, mode=mode, basis=basis))


def context(pol, when, *, subject=I1, identity_valid_at=None, mode=None) -> EvaluationContext:
    return EvaluationContext(subject_id=subject, evaluation_as_of=when, identity_valid_at=identity_valid_at or when,
                             authority_mode=mode or pol.authority_mode, policy_id=pol.policy_id)


def retro_inputs(root: Path, **overrides) -> ev.EvaluationInputs:
    base = dict(history=history_of(root), semantics=semantics_of(root),
                holdings=ProviderHoldingsStore.open(root, read_only=True),
                manifests=ManifestStore.open(root, read_only=True), corrections=CorrectionHistory(IDS.history()))
    return ev.EvaluationInputs(**{**base, **overrides})


def strict_inputs(world: World = None, records=None) -> ev.EvaluationInputs:
    world = world or World()
    return ev.EvaluationInputs(history=world.history(records), semantics=world.semantics())


def by_metric(result: ScreenerResult) -> dict:
    return {r.metric: r for r in result.criterion_results}


def ends(result: CriterionResult):
    return (result.target_period.period_end.isoformat() if result.target_period else None,
            result.comparison_period.period_end.isoformat() if result.comparison_period else None)


def rejects(code: str, fn, *args, **kwargs) -> None:
    with pytest.raises(ev.ScreenerEvaluationError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, exc.value.code


def fake_retro(status: R, value=None, inner: MetricResult = None, diagnostics=()):
    return SimpleNamespace(status=status, value=value, metric_result=inner, diagnostics=tuple(diagnostics),
                           observation_ids=(), coverage_epoch_ids=(), manifest_refs=())


# ================================================================ A 比較は Decimal だけ


@pytest.mark.parametrize("operator, value, threshold, high, expected", [
    (C.LT, "0.0499", "0.05", None, True), (C.LT, "0.05", "0.05", None, False),
    (C.LE, "0.05", "0.05", None, True), (C.LE, "0.0500001", "0.05", None, False),
    (C.GT, "0.05", "0.05", None, False), (C.GT, "0.050000000001", "0.05", None, True),
    (C.GE, "0.05", "0.0500", None, True), (C.GE, "-0.05", "0", None, False),
    (C.BETWEEN, "0.2", "0.2", "0.3", True), (C.BETWEEN, "0.3", "0.2", "0.3", True),
    (C.BETWEEN, "0.30000000000000001", "0.2", "0.3", False), (C.BETWEEN, "0.19999999999999999", "0.2", "0.3", False),
    (C.GE, "0.1", "0.1000000000000000055511151231257827", None, False),      # float なら等しい ・Decimal なら小さい
])
def test_a_comparison_is_exact_decimal_and_between_includes_both_bounds(operator, value, threshold, high, expected):
    assert ev.compare(operator, value, threshold, high) is expected
    assert ev.COMPARISON_RULE == "DECIMAL_ONLY_INCLUSIVE_BETWEEN_NO_ROUNDING_NO_TOLERANCE"


def test_a_between_without_a_second_bound_is_a_contract_violation() -> None:
    rejects("BETWEEN_REQUIRES_TWO_THRESHOLDS", ev.compare, C.BETWEEN, "0.25", "0.2", None)


# ================================================================ B authority mode の不一致（例外ではなく型つきの結果）


def test_b_policy_context_mode_mismatch_is_an_authority_failure_without_any_upstream_call(root: Path, monkeypatch):
    fy_epoch(root)
    pol = policy(*four(RETRO), authority_mode=RETRO)
    ctx = context(pol, ACQ2, mode=STRICT)                                                # 文脈だけ STRICT
    monkeypatch.setattr(ev, "resolve_retrospective_metric", lambda *a, **k: pytest.fail("A3-RA was called"))
    monkeypatch.setattr(ev, "operating_margin", lambda *a, **k: pytest.fail("A3 was called"))
    result = ev.evaluate_policy(pol, ctx, retro_inputs(root))
    assert result.state is ScreenerState.AUTHORITY_FAILURE and result.authority_mode is STRICT
    assert result.completeness is DataCompleteness.NONE
    for r in result.criterion_results:
        assert r.state is S.AUTHORITY_FAILURE and r.reason_codes == ("POLICY_AUTHORITY_MODE_MISMATCH",)
        assert r.has_value is False and r.observed_value is None and r.inner_metric_status is None
        assert r.target_period is None and r.observation_ids == () and r.coverage_epoch_ids == ()
        assert r.authority_mode is STRICT and r.criterion_id in {c.criterion_id for c in pol.criteria}
    strict_ctx = context(pol, ACQ2, mode=RETRO)
    single = ev.evaluate_criterion(replace(pol.criteria[0], authority_mode=STRICT), strict_ctx,
                                   retro_inputs(root))
    assert single.state is S.AUTHORITY_FAILURE and single.reason_codes == ("POLICY_AUTHORITY_MODE_MISMATCH",)


def test_b_there_is_no_fallback_between_modes_and_exactly_two_modes_exist() -> None:
    assert {m.value for m in ScreenerAuthorityMode} == {"STRICT_PIT", "RETROSPECTIVE_PROVIDER_AUTHORITY"}
    source = executable_source(MODULE)
    assert "fallback" not in source.lower().replace("fallback は無い", "").replace("fallback は", "")
    assert source.count("POLICY_AUTHORITY_MODE_MISMATCH") == 1


# ================================================================ C 契約の違反だけが例外


def test_c_contract_violations_are_deterministic_errors_not_results(root: Path) -> None:
    fy_epoch(root)
    pol, other = policy(*four()), policy(*four(), version=2)
    rejects("POLICY_CONTEXT_MISMATCH", ev.evaluate_policy, pol, context(other, ACQ2), retro_inputs(root))
    rejects("RETROSPECTIVE_INPUTS_REQUIRED", ev.evaluate_policy, pol, context(pol, ACQ2),
            ev.EvaluationInputs(history=history_of(root), semantics=semantics_of(root)))
    rejects("RETROSPECTIVE_INPUTS_REQUIRED", ev.evaluate_policy, pol, context(pol, ACQ2),
            retro_inputs(root, corrections=None))
    rejects("INVALID_HISTORY", ev.EvaluationInputs, history=object(), semantics={})
    rejects("INVALID_SEMANTICS_LOOKUP", ev.EvaluationInputs, history=history_of(root), semantics=[])
    rejects("INVALID_POLICY", ev.evaluate_policy, object(), context(pol, ACQ2), retro_inputs(root))
    rejects("INVALID_CONTEXT", ev.evaluate_policy, pol, object(), retro_inputs(root))
    rejects("INVALID_CRITERION", ev.evaluate_criterion, object(), context(pol, ACQ2), retro_inputs(root))
    rejects("INVALID_INPUTS", ev.evaluate_criterion, pol.criteria[0], context(pol, ACQ2), object())
    rejects("INVALID_STATES", ev.aggregate, ())
    assert issubclass(ev.ScreenerEvaluationError, ValueError) and ev.ScreenerEvaluationError("X", "y").code == "X"


# ================================================================ D A3-RA の外側の status の写像（閉じた表）


@pytest.mark.parametrize("outer, expected", [
    (R.SEMANTIC_HOLD, S.HOLD), (R.INSUFFICIENT_DATA, S.NOT_EVALUABLE), (R.INSUFFICIENT_TIME_PRECISION, S.NOT_EVALUABLE),
    (R.NOT_COMPARABLE, S.NOT_EVALUABLE), (R.UNDEFINED, S.NOT_EVALUABLE), (R.AUTHORITY_FAILURE, S.AUTHORITY_FAILURE),
    (R.AMBIGUOUS_AUTHORITY, S.AUTHORITY_FAILURE), (R.INVALID_INPUT, S.AUTHORITY_FAILURE)])
def test_d_every_non_value_outer_status_maps_to_the_closed_vocabulary(root: Path, monkeypatch, outer, expected):
    fy_epoch(root)
    pol = policy(crit(K.OPERATING_MARGIN))
    monkeypatch.setattr(ev, "resolve_retrospective_metric",
                        lambda *a, **k: fake_retro(outer, diagnostics=("REVENUE:SYNTHETIC",)))
    result = ev.evaluate_policy(pol, context(pol, ACQ2), retro_inputs(root))
    r = result.criterion_results[0]
    assert r.state is expected and result.state.value == expected.value and r.has_value is False
    assert r.observed_value is None and r.inner_metric_status is None and r.reason_codes == ("REVENUE:SYNTHETIC",)
    assert ends(r) == ("2025-03-31", None)                                                # 選んだ期間は残す
    assert set(R) == set(ev._RETRO_STATES) | {R.VALUE}                                   # 表は閉じている


def test_d_value_is_compared_and_a_value_without_an_observed_value_is_a_contract_violation(root: Path, monkeypatch):
    fy_epoch(root)
    pol = policy(crit(K.OPERATING_MARGIN, C.GE, "0.08"))
    monkeypatch.setattr(ev, "resolve_retrospective_metric", lambda *a, **k: fake_retro(R.VALUE, None))
    rejects("VALUE_WITHOUT_OBSERVED_VALUE", ev.evaluate_policy, pol, context(pol, ACQ2), retro_inputs(root))


# ================================================================ E STRICT の MetricStatus の写像（真に写す）


def test_e_strict_statuses_map_truthfully_and_outside_coverage_is_not_evaluable() -> None:
    assert set(MetricStatus) == set(ev._STRICT_STATES) | {MetricStatus.VALUE}
    assert ev._STRICT_STATES[MetricStatus.INVALID_INPUT] is S.AUTHORITY_FAILURE
    pol = policy(*four(STRICT), authority_mode=STRICT)
    world = World()
    no_coverage = strict_inputs(world, [r for r in world.records if r.KIND.value == "FUNDAMENTAL_ACTUAL"])
    result = ev.evaluate_policy(pol, context(pol, C_2026_06, subject=STRICT_I1), no_coverage)
    assert result.state is ScreenerState.NOT_EVALUABLE and result.completeness is DataCompleteness.NONE
    for r in result.criterion_results:
        assert r.state is S.NOT_EVALUABLE and r.inner_metric_status is MetricStatus.INSUFFICIENT_DATA
        assert all(code.endswith(":OUTSIDE_COVERAGE") for code in r.reason_codes) and r.reason_codes
        assert r.has_value is False and r.observed_value is None and r.coverage_epoch_ids == ()
        assert r.observation_ids == () and r.manifest_refs == () and r.target_period is not None


def test_e_strict_invalid_input_is_an_authority_failure_of_the_criterion(monkeypatch) -> None:
    pol = policy(crit(K.OPERATING_MARGIN, mode=STRICT), authority_mode=STRICT)
    ctx = context(pol, C_2025_06, subject=STRICT_I1)
    real = ev.operating_margin

    def invalid(*args, **kwargs):
        ok = real(*args, **kwargs)
        return replace(ok, status=MetricStatus.INVALID_INPUT, value=None, period_label=None,
                       reasons=(MetricReason(MetricLeg.REVENUE, ReasonCode.SEMANTICS_MISMATCH),))
    monkeypatch.setattr(ev, "operating_margin", invalid)
    r = ev.evaluate_policy(pol, ctx, strict_inputs()).criterion_results[0]
    assert r.state is S.AUTHORITY_FAILURE and r.inner_metric_status is MetricStatus.INVALID_INPUT
    assert r.reason_codes == ("REVENUE:SEMANTICS_MISMATCH",) and r.has_value is False


# ================================================================ F 期間の選択（authority に見える期間だけ ・PILOT2B と同じ意味）


def test_f_visible_periods_and_target_selection_match_the_pilot2b_runner_exactly(root: Path) -> None:
    produce(root, [PRIOR_FY, PRIOR_1Q], CTX1)
    produce(root, [row(), q1_row(row()["Code"])], CTX2)
    pol = policy(*four())
    ctx = context(pol, ACQ2)
    inputs = retro_inputs(root)
    visible = ev.visible_periods(pol.criteria[0], ctx, inputs)
    assert visible == pl._target_candidates(root, I1, ACQ2)
    assert {d.isoformat() for d in visible} == {"2023-06-30", "2024-03-31", "2025-03-31", "2025-06-30"}
    for rule, bases in ((PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE, pl.SUPPORTED_TARGET_BASES),
                        (PeriodRule.NEWEST_FY, (PeriodBasis.FISCAL_YEAR,))):
        assert ev.select_target(visible, rule) == pl._select_target(visible, bases)
    assert ev.select_target(visible, PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE)[0].period_end.isoformat() \
        == "2025-06-30"
    assert ev.select_target(visible, PeriodRule.NEWEST_FY)[0].period_end.isoformat() == "2025-03-31"
    assert ev.SUPPORTED_TARGET_BASES == pl.SUPPORTED_TARGET_BASES
    assert tuple(c.value for c in ev.PERIOD_RELATION_CODES) == tuple(pl.PERIOD_RELATION_CODES)


def test_f_margins_take_the_newest_supported_period_roa_the_fy_and_growth_the_first_comparable_pair(root: Path,
                                                                                                    monkeypatch):
    produce(root, [PRIOR_FY, PRIOR_1Q], CTX1)
    produce(root, [row(), q1_row(row()["Code"])], CTX2)                                   # PILOT2B の test c と同じ像
    pol = policy(*four())
    seen: dict = {}
    original = ev.resolve_retrospective_metric

    def spy(kind, history, **kwargs):
        seen.setdefault(kind.value, []).append((kwargs["target_period"].period_end.isoformat(),
                                               kwargs["comparison_period"].period_end.isoformat()
                                               if kwargs["comparison_period"] else None))
        assert kwargs["authority_as_of"] == ACQ2 and kwargs["identity_valid_at"] == ACQ2
        return original(kind, history, **kwargs)
    monkeypatch.setattr(ev, "resolve_retrospective_metric", spy)
    result = ev.evaluate_policy(pol, context(pol, ACQ2), retro_inputs(root))
    assert seen["OPERATING_MARGIN"] == [("2025-06-30", None)] and seen["NET_MARGIN"] == [("2025-06-30", None)]
    assert seen["ROA_POINT_IN_TIME"] == [("2025-03-31", None)]
    assert seen["REVENUE_GROWTH"][0] == ("2025-06-30", "2025-03-31")                    # 1Q と年度は comparable でない
    assert seen["REVENUE_GROWTH"][-1] == ("2025-03-31", "2024-03-31")                   # 最初の comparable な対
    r = by_metric(result)
    assert ends(r[K.REVENUE_GROWTH]) == ("2025-03-31", "2024-03-31") and r[K.REVENUE_GROWTH].state is S.MATCH
    assert r[K.REVENUE_GROWTH].observed_value == "0.25" and ends(r[K.ROA_POINT_IN_TIME]) == ("2025-03-31", None)
    assert ends(r[K.OPERATING_MARGIN]) == ("2025-06-30", None)


def test_f_only_holdings_visible_at_evaluation_as_of_can_supply_a_target(root: Path) -> None:
    produce(root, [PRIOR_FY, PRIOR_1Q], CTX1)
    fy_epoch(root)                                                                           # ACQ2 の epoch
    pol = policy(crit(K.OPERATING_MARGIN), crit(K.REVENUE_GROWTH, C.GE, "0"))
    early = ev.evaluate_policy(pol, context(pol, ACQ1), retro_inputs(root))                 # ACQ2 の保持はまだ見えない
    r = by_metric(early)
    assert ends(r[K.OPERATING_MARGIN]) == ("2024-03-31", None) and r[K.OPERATING_MARGIN].state is S.MATCH
    assert r[K.REVENUE_GROWTH].state is S.NOT_EVALUABLE
    assert r[K.REVENUE_GROWTH].reason_codes == ("NO_COMPARABLE_PRIOR_PERIOD",)
    before = ev.evaluate_policy(pol, context(pol, ACQ1 - timedelta(hours=1)), retro_inputs(root))
    for r in before.criterion_results:
        assert r.state is S.NOT_EVALUABLE and r.reason_codes == ("TARGET_UNAVAILABLE",)
        assert r.target_period is None and r.observation_ids == () and r.coverage_epoch_ids == ()
    assert before.state is ScreenerState.NOT_EVALUABLE and before.completeness is DataCompleteness.NONE


def test_f_ambiguous_targets_are_never_chosen(root: Path) -> None:
    manifest, fy = fy_epoch(root)
    irregular = replace(fy, fiscal_year_start=date(2024, 1, 1), period_start=date(2024, 1, 1))  # 同じ末日 ・別の年度

    class Doubled:
        def by_acquisition(self, reference):
            real = ManifestStore.open(root, read_only=True).by_acquisition(reference)
            extra = SimpleNamespace(disposition=real.entries[0].disposition, period=irregular,
                                    statement_basis=real.entries[0].statement_basis)
            return SimpleNamespace(entries=tuple(real.entries) + (extra,), reference=real.reference)
    pol = policy(*four())
    result = ev.evaluate_policy(pol, context(pol, ACQ2), retro_inputs(root, manifests=Doubled()))
    r = by_metric(result)
    for kind in K:                                                                       # 年度だけの規則も曖昧（任意に選ばない）
        assert r[kind].state is S.NOT_EVALUABLE and r[kind].reason_codes == ("TARGET_AMBIGUOUS",), kind
        assert r[kind].target_period is None and r[kind].coverage_epoch_ids == ()
    assert result.state is ScreenerState.NOT_EVALUABLE


def test_f_strict_targets_are_the_periods_certainly_known_by_the_cutoff(monkeypatch) -> None:
    pol = policy(*four(STRICT), authority_mode=STRICT)
    inputs = strict_inputs()
    seen: dict = {}
    for name in ("operating_margin", "net_margin", "roa_point_in_time", "revenue_growth"):
        real = getattr(ev, name)

        def spy(history, _real=real, _name=name, **kwargs):
            seen.setdefault(_name, []).append(kwargs["cutoff"])
            return _real(history, **kwargs)
        monkeypatch.setattr(ev, name, spy)
    at_2025 = by_metric(ev.evaluate_policy(pol, context(pol, C_2025_06, subject=STRICT_I1), inputs))
    assert at_2025[K.OPERATING_MARGIN].target_period == FY24 and at_2025[K.OPERATING_MARGIN].observed_value == "0.08"
    assert at_2025[K.REVENUE_GROWTH].target_period == FY24 and at_2025[K.REVENUE_GROWTH].comparison_period == FY23
    assert at_2025[K.REVENUE_GROWTH].state is S.MATCH and at_2025[K.REVENUE_GROWTH].observed_value == "0.25"
    at_2026 = by_metric(ev.evaluate_policy(pol, context(pol, C_2026_06, subject=STRICT_I1), inputs))
    assert at_2026[K.REVENUE_GROWTH].target_period == FY25 and at_2026[K.REVENUE_GROWTH].comparison_period == FY24
    assert at_2026[K.REVENUE_GROWTH].state is S.NO_MATCH and at_2026[K.REVENUE_GROWTH].observed_value == "0.014056"
    assert at_2026[K.OPERATING_MARGIN].state is S.NOT_EVALUABLE                             # FY25 の営業利益は無い
    assert at_2026[K.OPERATING_MARGIN].reason_codes == ("OPERATING_INCOME:NOT_FOUND",)
    assert set(seen) == {"operating_margin", "net_margin", "roa_point_in_time", "revenue_growth"}
    assert all(cutoff in (C_2025_06, C_2026_06) for calls in seen.values() for cutoff in calls)
    visible = ev.visible_periods(pol.criteria[0], context(pol, C_2025_06, subject=STRICT_I1), inputs)
    assert FY24 in visible[FY24.period_end] and FY25.period_end not in visible                # 2026-05 の知識は見えない


# ================================================================ G 合成の E2E（保持 → A3-RA → B2）


def test_g_end_to_end_match_through_provider_holdings_and_a3_ra_with_frozen_provenance(root: Path) -> None:
    _, prior, _ = produce(root, [PRIOR_FY, PRIOR_1Q], CTX1)
    manifest, fy = fy_epoch(root)
    pol = policy(*four())
    ctx = context(pol, ACQ2)
    result = ev.evaluate_policy(pol, ctx, retro_inputs(root))
    r = by_metric(result)
    assert r[K.OPERATING_MARGIN].state is S.MATCH and r[K.OPERATING_MARGIN].observed_value == "0.08"
    assert r[K.NET_MARGIN].state is S.NO_MATCH and r[K.NET_MARGIN].observed_value == "0.06"   # 0.06 > 0.10 は偽
    assert r[K.ROA_POINT_IN_TIME].state is S.MATCH and r[K.ROA_POINT_IN_TIME].observed_value == "0.033333"
    assert r[K.REVENUE_GROWTH].state is S.MATCH and r[K.REVENUE_GROWTH].observed_value == "0.25"
    assert result.state is ScreenerState.NO_MATCH and result.completeness is DataCompleteness.COMPLETE
    epoch = ProviderHoldingsStore.open(root, read_only=True).for_subject(I1)
    fy_epoch_ref = {e.reference for e in epoch if e.period_end == fy.period_end}
    for kind in (K.OPERATING_MARGIN, K.NET_MARGIN, K.ROA_POINT_IN_TIME):
        assert set(r[kind].coverage_epoch_ids) == fy_epoch_ref and r[kind].manifest_refs == (manifest.reference,)
        assert set(r[kind].observation_ids) <= set(manifest.observation_ids) and len(r[kind].observation_ids) == 2
        assert r[kind].inner_metric_status is MetricStatus.VALUE and r[kind].reason_codes == ()
    growth = r[K.REVENUE_GROWTH]
    assert set(growth.manifest_refs) == {manifest.reference, prior.reference} and len(growth.coverage_epoch_ids) == 2
    assert result.identity_valid_at == ACQ2 and result.evaluation_as_of == ACQ2 and result.authority_mode is RETRO
    assert result.rules_version == "p8_screener_semantics:0.1.0"
    matching = policy(crit(K.OPERATING_MARGIN, C.GE, T_OM), crit(K.REVENUE_GROWTH, C.BETWEEN, "0.2", high="0.25"))
    passed = ev.evaluate_policy(matching, context(matching, ACQ2), retro_inputs(root))
    assert passed.state is ScreenerState.MATCH and all(r.state is S.MATCH for r in passed.criterion_results)


def test_g_held_rows_build_no_visible_period_and_a_hold_upstream_outranks_no_match(root: Path, monkeypatch) -> None:
    manifest, fy = fy_epoch(root, [row(), NC_BROKEN])                                       # NC の行は CANONICAL でない
    assert {e.disposition.value for e in manifest.entries} == {"CANONICAL", "UNSUPPORTED"}
    pol = policy(crit(K.OPERATING_MARGIN, C.GE, T_OM, basis=NC), crit(K.NET_MARGIN, C.GT, T_NM))
    result = ev.evaluate_policy(pol, context(pol, ACQ2), retro_inputs(root))
    r = by_metric(result)
    assert r[K.OPERATING_MARGIN].state is S.NOT_EVALUABLE                                  # 保留の行は authority の期間を作らない
    assert r[K.OPERATING_MARGIN].reason_codes == ("TARGET_UNAVAILABLE",) and r[K.OPERATING_MARGIN].target_period is None
    assert r[K.NET_MARGIN].state is S.NO_MATCH and result.state is ScreenerState.NO_MATCH
    held = ev.resolve_retrospective_metric(K.OPERATING_MARGIN, history_of(root), subject_id=I1, statement_basis=NC,
                                           target_period=fy, authority_as_of=ACQ2, identity_valid_at=ACQ2,
                                           manifests=ManifestStore.open(root, read_only=True),
                                           corrections=CorrectionHistory(IDS.history()),
                                           holdings=ProviderHoldingsStore.open(root, read_only=True),
                                           semantics=semantics_of(root))
    assert held.status is R.SEMANTIC_HOLD                                                   # 期間を明示すれば A3-RA は保留
    monkeypatch.setattr(ev, "select_target", lambda periods, rule: (fy, ""))                 # 保留の脚を B2 に写す
    forced = ev.evaluate_policy(pol, context(pol, ACQ2), retro_inputs(root))
    f = by_metric(forced)
    assert f[K.OPERATING_MARGIN].state is S.HOLD and f[K.OPERATING_MARGIN].inner_metric_status is None
    assert f[K.OPERATING_MARGIN].reason_codes == ("OPERATING_INCOME:SEMANTIC_HOLD:HELD_ROW_AT_PERIOD",
                                                  "REVENUE:SEMANTIC_HOLD:HELD_ROW_AT_PERIOD")
    assert f[K.OPERATING_MARGIN].coverage_epoch_ids and f[K.OPERATING_MARGIN].has_value is False
    assert f[K.NET_MARGIN].state is S.NO_MATCH
    assert forced.state is ScreenerState.HOLD and forced.completeness is DataCompleteness.PARTIAL


# ================================================================ H ALL_OF の集約（短絡しない ・固定の優先）


@pytest.mark.parametrize("states, expected", [
    ((S.MATCH, S.MATCH), ScreenerState.MATCH), ((S.MATCH,), ScreenerState.MATCH),
    ((S.MATCH, S.NOT_EVALUABLE), ScreenerState.NOT_EVALUABLE), ((S.NOT_EVALUABLE, S.NO_MATCH), ScreenerState.NO_MATCH),
    ((S.NO_MATCH, S.HOLD, S.MATCH), ScreenerState.HOLD),
    ((S.HOLD, S.AUTHORITY_FAILURE, S.NO_MATCH, S.NOT_EVALUABLE, S.MATCH), ScreenerState.AUTHORITY_FAILURE)])
def test_h_aggregation_follows_the_fixed_precedence(states, expected) -> None:
    assert ev.aggregate(states) is expected
    assert ev.AGGREGATION_PRECEDENCE == (ScreenerState.AUTHORITY_FAILURE, ScreenerState.HOLD, ScreenerState.NO_MATCH,
                                         ScreenerState.NOT_EVALUABLE)


def test_h_every_criterion_is_evaluated_in_policy_order_and_completeness_is_the_frozen_vocabulary(root: Path,
                                                                                                  monkeypatch):
    fy_epoch(root)
    pol = policy(crit(K.NET_MARGIN, C.GT, T_NM), crit(K.OPERATING_MARGIN), crit(K.ROA_POINT_IN_TIME, C.GE, T_ROA),
                 crit(K.REVENUE_GROWTH, C.GE, "0"))
    calls: list = []
    original = ev.resolve_retrospective_metric

    def spy(kind, history, **kwargs):
        calls.append(kind)
        return original(kind, history, **kwargs)
    monkeypatch.setattr(ev, "resolve_retrospective_metric", spy)
    result = ev.evaluate_policy(pol, context(pol, ACQ2), retro_inputs(root))
    assert [r.criterion_id for r in result.criterion_results] == [c.criterion_id for c in pol.criteria]
    assert calls == [K.NET_MARGIN, K.OPERATING_MARGIN, K.ROA_POINT_IN_TIME, K.REVENUE_GROWTH]  # NO_MATCH が先でも止まらない
    states = tuple(r.state for r in result.criterion_results)
    assert states == (S.NO_MATCH, S.MATCH, S.MATCH, S.NOT_EVALUABLE)
    assert result.state is ScreenerState.NO_MATCH and result.completeness is completeness_of(states)
    assert result.completeness is DataCompleteness.PARTIAL


# ================================================================ I 値の表面 ・決定論


def test_i_observed_values_exist_only_for_valued_states_and_stay_out_of_the_default_dict(root: Path) -> None:
    produce(root, [PRIOR_FY], CTX1)
    fy_epoch(root)
    pol = policy(*four(), crit(K.REVENUE_GROWTH, C.GE, "0", rule=PeriodRule.NEWEST_WITH_COMPARABLE_PRIOR))
    first = ev.evaluate_policy(pol, context(pol, ACQ2), retro_inputs(root))
    second = ev.evaluate_policy(pol, context(pol, ACQ2), retro_inputs(root))
    assert first == second and first.as_dict() == second.as_dict()                          # 決定論
    for r in first.criterion_results:
        assert (r.observed_value is not None) is (r.state in (S.MATCH, S.NO_MATCH)) is r.has_value
        assert "observed_value" not in r.as_dict()
        assert r.as_dict(include_value=True)["observed_value"] == r.observed_value
        assert all(isinstance(code, str) for code in r.reason_codes) and list(r.reason_codes) == sorted(r.reason_codes)
    assert "0.08" not in str(first.as_dict()) and "0.25" not in str(first.as_dict())


# ================================================================ J 表面の guard（純 ・凍結の入口だけ ・順位の原始なし）


def test_j_the_evaluator_is_pure_uses_only_frozen_public_entrypoints_and_has_no_ranking_surface() -> None:
    source = executable_source(MODULE)
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {"." * node.level + node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported == {"__future__", "dataclasses", "datetime", "decimal", "typing", ".fundamental_metrics",
                        ".fundamental_metrics_extended", ".metric_model", ".observation_model",
                        ".retrospective_metric_resolver", ".screener_criteria_model"}
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert not any(name.startswith("_") for name in names - {"__future__"})                 # private helper は使わない
    assert {"operating_margin", "net_margin", "roa_point_in_time", "revenue_growth", "resolve_retrospective_metric",
            "completeness_of"} <= names and "_resolve_leg" not in source
    for token in ("jquants_pilot2", "theme", "Theme", "narrative", "p6", "p7", "float(", "round(", "math.", "now(",
                  "today(", "utcnow", "open(", "Path(", "os.", "json.", "://", "llm", "prompt", "store.append",
                  "history.add(", "key=lambda", "sort(", "weight", "score", "rank", "recommend", "watchlist",
                  "portfolio", "distance", "epsilon", "tolerance", "abs(", "min(", "max(", "sum(", "getattr", "eval("):
        assert token not in source, token
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Name) and node.id in {"float", "round", "print", "open", "exec", "eval"}), \
            node.id
        assert not isinstance(node, ast.BinOp), ast.dump(node)                              # 算術は無い（距離 ・点数なし）
        assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id == "Exception"))), "broad except"
    for line in MODULE.read_text(encoding="utf-8").splitlines():
        assert len(line) <= 120, line
    assert ev.EVALUATOR_RULES_VERSION == "p8_screener_evaluator:0.1.0"
    assert set(ev.__all__) == {"AGGREGATION_PRECEDENCE", "COMPARISON_RULE", "EVALUATOR_RULES_VERSION",
                               "PERIOD_RELATION_CODES", "SUPPORTED_TARGET_BASES", "EvaluationInputs",
                               "ScreenerEvaluationError", "aggregate", "compare", "evaluate_criterion",
                               "evaluate_policy", "select_target", "visible_periods"}
