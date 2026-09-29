"""Phase 5 P5-3A — 較正の分析契約 ＋ metric 仕様の凍結ガード。

gate §24 の 60 項目を、凍結 PredictionRecord / EvaluationRecord の fixture だけで証明する。
market / calendar / network / store / evaluation_engine に触れない。
"""
from __future__ import annotations

import dataclasses
import inspect
from datetime import timedelta
from decimal import Decimal, getcontext
from pathlib import Path

import pytest

from src.intelligence.compass.model import OutlookDirection
from src.intelligence.predictions import calibration_contract as cc
from src.intelligence.predictions.calibration_contract import (
    ACTIVE_EVALUATION_RESOLVER_VERSION,
    CALIBRATION_CONTRACT_VERSION,
    CONFIDENCE_BUCKETS,
    LEVEL_ROWS,
    METRIC_BY_NAME,
    METRIC_DEFINITIONS,
    OUTCOME_COLUMNS,
    PREDICTION_DIRECTION_MAPPING,
    PREDICTION_DIRECTION_MAPPING_VERSION,
    RATE_CONTEXT,
    SAMPLE_DISCLOSURE_THRESHOLDS,
    SAMPLE_DISCLOSURE_VERSION,
    ActiveEvaluation,
    CalibrationContractError,
    CalibrationLineage,
    CohortBoundary,
    Denominator,
    EvaluationCoverage,
    MetricKind,
    OutcomeCounts,
    PredictedDirection,
    PredictionCohort,
    Rate,
    ResolutionStatus,
    ReturnSummary,
    SampleDisclosure,
    active_evaluation_digest,
    cohort_digest,
    content_digest,
    count_outcomes,
    directional_exact_match,
    predicted_direction,
    prediction_cohorts,
    resolve_active_evaluation,
    sample_disclosure,
    summarize_returns,
    unique_session_count,
)
from src.intelligence.predictions.evaluation_record import (
    NEUTRAL_BAND_RULE_VERSION,
    DeferReason,
    EvaluationRecord,
    EvaluationStatus,
    RealizedOutcome,
)
from src.intelligence.predictions.prediction_record import PredictionOrigin, PredictionRecord
from src.intelligence.reports.market_signal import LEVEL_BY_STATE, SignalLevel
from tests.intelligence.test_evaluation_record import CREATED_AT, deferred, evaluated
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import (
    abstained_kwargs,
    base_kwargs,
    executable_source,
    imported_modules,
    make,
)
from src.intelligence.predictions.prediction_record import make_prediction_record

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "calibration_contract.py"
PID = "pred_02899d141d42096adcea4f48"
OTHER_PID = "pred_" + "f" * 24


def source() -> str:
    return executable_source(MODULE_PATH)


def chain():
    a = deferred()
    b = evaluated(supersedes_evaluation_id=a.evaluation_id)
    c = evaluated(realized_return=Decimal("0.0068"), target_close=Decimal("2718.36"),
                  supersedes_evaluation_id=b.evaluation_id)
    return a, b, c


# ---------------------------------------------------------------- 1–7 analytical mapping

def test_mapping_is_versioned_and_covers_all_five_levels() -> None:                       # 1, 2
    assert PREDICTION_DIRECTION_MAPPING_VERSION == "prediction_direction_mapping:1.0.0"
    assert set(PREDICTION_DIRECTION_MAPPING) == set(SignalLevel) and len(PREDICTION_DIRECTION_MAPPING) == 5
    assert [d.value for d in PredictedDirection] == ["UP", "RANGE", "DOWN"]


@pytest.mark.parametrize("level,direction", [
    (SignalLevel.UPWARD_LEAN, PredictedDirection.UP),               # 3
    (SignalLevel.SLIGHT_UPWARD_LEAN, PredictedDirection.UP),        # 4
    (SignalLevel.NEUTRAL_RANGE, PredictedDirection.RANGE),          # 5
    (SignalLevel.SLIGHT_DOWNWARD_LEAN, PredictedDirection.DOWN),    # 6
    (SignalLevel.DOWNWARD_LEAN, PredictedDirection.DOWN),           # 7
])
def test_level_to_direction(level: SignalLevel, direction: PredictedDirection) -> None:
    assert predicted_direction(level) is direction
    assert PREDICTION_DIRECTION_MAPPING[level] is direction


def test_mapping_is_the_inverse_of_the_frozen_p4_direction_component() -> None:
    """P4 と矛盾しない証明: LEVEL_BY_STATE の方向成分を逆射影すると凍結写像そのものになる。"""
    direction_of = {OutlookDirection.UPWARD_BIAS.value: PredictedDirection.UP,
                    OutlookDirection.RANGE_BOUND.value: PredictedDirection.RANGE,
                    OutlookDirection.DOWNWARD_BIAS.value: PredictedDirection.DOWN}
    derived = {level: direction_of[direction] for (direction, _c), level in LEVEL_BY_STATE.items()}
    assert derived == dict(PREDICTION_DIRECTION_MAPPING)
    with pytest.raises(CalibrationContractError):
        predicted_direction("UPWARD_LEAN")                          # type: ignore[arg-type]


@pytest.mark.parametrize("level,outcome,match", [
    (SignalLevel.UPWARD_LEAN, RealizedOutcome.UP, True),
    (SignalLevel.SLIGHT_UPWARD_LEAN, RealizedOutcome.UP, True),
    (SignalLevel.NEUTRAL_RANGE, RealizedOutcome.RANGE, True),
    (SignalLevel.DOWNWARD_LEAN, RealizedOutcome.DOWN, True),
    (SignalLevel.SLIGHT_DOWNWARD_LEAN, RealizedOutcome.RANGE, False),
    (SignalLevel.UPWARD_LEAN, RealizedOutcome.DOWN, False),
    (SignalLevel.NEUTRAL_RANGE, RealizedOutcome.UP, False),
])
def test_directional_exact_match_definition(level, outcome, match) -> None:              # 9 §9
    assert directional_exact_match(level, outcome) is match
    with pytest.raises(CalibrationContractError):
        directional_exact_match(level, "UP")                          # type: ignore[arg-type]


# ---------------------------------------------------------------- 8–13 cohorts / eligibility

def test_unavailable_prediction_is_in_abstained_cohort_not_available() -> None:         # 8, 9
    abstained = make_prediction_record(**abstained_kwargs())
    assert prediction_cohorts(abstained) == (PredictionCohort.ALL, PredictionCohort.ABSTAINED)
    assert prediction_cohorts(make()) == (PredictionCohort.ALL, PredictionCohort.AVAILABLE)
    exact = METRIC_BY_NAME["directional_exact_match_rate"]
    assert exact.denominator is Denominator.AVAILABLE_WITH_ACTIVE_EVALUATED   # 棄権は分母に入らない
    assert METRIC_BY_NAME["abstention_rate"].denominator is Denominator.TOTAL_PREDICTIONS


def test_deferred_is_excluded_from_outcomes_but_kept_in_coverage() -> None:              # 10, 11
    a = deferred()
    res = resolve_active_evaluation(PID, [a])
    assert res.status is ResolutionStatus.RESOLVED and res.coverage is EvaluationCoverage.ACTIVE_DEFERRED
    assert res.realized_outcome is None and res.realized_return is None
    with pytest.raises(CalibrationContractError):
        summarize_returns([a])
    assert METRIC_BY_NAME["active_deferred_rate"].denominator is Denominator.PREDICTIONS_IN_COHORT


def test_no_evaluation_is_tracked_separately_and_evaluated_is_eligible() -> None:        # 12, 13
    none = resolve_active_evaluation(OTHER_PID, [evaluated()])
    assert none.status is ResolutionStatus.NO_EVALUATION and none.coverage is EvaluationCoverage.NO_EVALUATION
    assert none.active is None
    ok = resolve_active_evaluation(PID, [evaluated()])
    assert ok.coverage is EvaluationCoverage.ACTIVE_EVALUATED and ok.realized_outcome is RealizedOutcome.UP
    assert METRIC_BY_NAME["no_evaluation_rate"].denominator is Denominator.PREDICTIONS_IN_COHORT


# ---------------------------------------------------------------- 14–20 resolver

def test_deferred_then_evaluated_resolves_to_terminal_evaluated() -> None:              # 14
    a, b, _ = chain()
    res = resolve_active_evaluation(PID, [a, b])
    assert res.active == b and res.chain_ids == (a.evaluation_id, b.evaluation_id)
    assert res.coverage is EvaluationCoverage.ACTIVE_EVALUATED


def test_evaluated_to_evaluated_correction_resolves_terminal() -> None:                  # 15
    a = evaluated()
    b = evaluated(realized_return=Decimal("-0.004"), target_close=Decimal("2689.2"),
                  supersedes_evaluation_id=a.evaluation_id)
    res = resolve_active_evaluation(PID, [a, b])
    assert res.active == b and res.realized_outcome is RealizedOutcome.DOWN
    assert res.terminal_ids == (b.evaluation_id,)


def test_three_step_chain_resolves_c_regardless_of_input_order() -> None:               # 16
    a, b, c = chain()
    for order in ([a, b, c], [c, b, a], [b, c, a], [c, a, b]):
        res = resolve_active_evaluation(PID, order)
        assert res.status is ResolutionStatus.RESOLVED and res.active == c
        assert res.chain_ids == (a.evaluation_id, b.evaluation_id, c.evaluation_id)


def test_fork_is_detected_and_excluded_with_diagnostic() -> None:                         # 17
    a, b, _ = chain()
    fork = evaluated(realized_return=Decimal("0.0069"), target_close=Decimal("2718.63"),
                     supersedes_evaluation_id=a.evaluation_id)
    res = resolve_active_evaluation(PID, [a, b, fork])
    assert res.status is ResolutionStatus.FORK and res.active is None
    assert res.coverage is EvaluationCoverage.UNRESOLVED and a.evaluation_id in res.diagnostic
    assert set(res.terminal_ids) == {b.evaluation_id, fork.evaluation_id}


def test_multiple_independent_terminals_fail_closed_with_diagnostic() -> None:          # 18
    a = deferred()
    independent = evaluated()
    res = resolve_active_evaluation(PID, [a, independent])
    assert res.status is ResolutionStatus.MULTIPLE_TERMINALS and res.active is None
    assert res.coverage is EvaluationCoverage.UNRESOLVED
    assert set(res.terminal_ids) == {a.evaluation_id, independent.evaluation_id}


def test_resolver_uses_neither_created_at_nor_physical_order() -> None:                  # 19, 20
    a, b, _ = chain()
    older_correction = evaluated(created_at=CREATED_AT - timedelta(days=30),
                                 supersedes_evaluation_id=a.evaluation_id)
    res = resolve_active_evaluation(PID, [older_correction, a])          # 古い created_at・先頭でも active
    assert res.active == older_correction
    import ast
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "resolve_active_evaluation")
    fn.body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) else fn.body   # docstring を除いた本体だけ
    resolver_src = ast.unparse(fn)
    for token in ("created_at", "line_number", "[-1]", "iter_records", "reversed(", "max("):
        assert token not in resolver_src, token
    assert "created_at" not in source() and "line_number" not in source()
    assert resolve_active_evaluation(PID, [a, b]) == resolve_active_evaluation(PID, [b, a])


def test_resolver_diagnostics_for_dangling_subject_mismatch_and_duplicate_id() -> None:
    a, b, _ = chain()
    assert resolve_active_evaluation(PID, [b]).status is ResolutionStatus.DANGLING_SUPERSESSION
    other_session = evaluated(reference_session="2026-09-10", session_date="2026-09-11",
                              session_verification=__import__(
                                  "tests.intelligence.test_evaluation_record", fromlist=["verification"]
                              ).verification(verified_session="2026-09-11",
                                             verified_previous_session="2026-09-10"))
    assert resolve_active_evaluation(PID, [a, other_session]).status is ResolutionStatus.SUBJECT_MISMATCH
    forged = dataclasses.replace  # 同 id・別内容は EvaluationRecord では作れないため dict で模倣しない
    assert forged is not None
    twice = resolve_active_evaluation(PID, [a, a])                       # 同一内容の重複は 1 件として扱う
    assert twice.status is ResolutionStatus.RESOLVED and twice.active == a
    with pytest.raises(CalibrationContractError):
        resolve_active_evaluation(PID, [a.as_dict()])                    # type: ignore[list-item]


# ---------------------------------------------------------------- 21–22 LIVE / REPLAY

def test_live_and_replay_are_separate_cohorts_with_no_implicit_combined() -> None:       # 21, 22
    live = CohortBoundary(PredictionOrigin.LIVE, "2026-09-01", "2026-09-30")
    replay = CohortBoundary(PredictionOrigin.REPLAY, "2026-09-01", "2026-09-30")
    p_live = make()
    p_replay = make_prediction_record(**base_kwargs(origin=PredictionOrigin.REPLAY))
    assert live.contains(p_live) and not live.contains(p_replay)
    assert replay.contains(p_replay) and not replay.contains(p_live)
    assert live.select([p_live, p_replay]) == (p_live,)
    assert "COMBINED" not in source() and "combined" not in source()
    assert not any(m.value == "COMBINED" for m in PredictionOrigin)
    with pytest.raises(CalibrationContractError):
        CohortBoundary("LIVE", "2026-09-01", "2026-09-30")            # type: ignore[arg-type]


# ---------------------------------------------------------------- 23–29 matrix / rates / counts

def test_confusion_matrix_axes_are_five_by_three() -> None:                              # 23, 24
    assert LEVEL_ROWS == tuple(SignalLevel) and len(LEVEL_ROWS) == 5
    assert OUTCOME_COLUMNS == tuple(RealizedOutcome) and len(OUTCOME_COLUMNS) == 3
    assert [l.value for l in LEVEL_ROWS] == ["UPWARD_LEAN", "SLIGHT_UPWARD_LEAN", "NEUTRAL_RANGE",
                                              "SLIGHT_DOWNWARD_LEAN", "DOWNWARD_LEAN"]


def test_exact_match_numerator_and_denominator_are_explicit() -> None:                   # 25, 26, 27
    outcomes = [(SignalLevel.UPWARD_LEAN, RealizedOutcome.UP), (SignalLevel.UPWARD_LEAN, RealizedOutcome.RANGE),
                (SignalLevel.NEUTRAL_RANGE, RealizedOutcome.RANGE), (SignalLevel.DOWNWARD_LEAN, RealizedOutcome.UP)]
    matches = sum(1 for level, outcome in outcomes if directional_exact_match(level, outcome))
    rate = Rate(matches, len(outcomes))
    assert (rate.numerator, rate.denominator) == (2, 4) and rate.value == Decimal("0.5")
    assert rate.as_dict() == {"numerator": 2, "denominator": 4, "value": "0.5", "disclosure": "INSUFFICIENT_SAMPLE"}
    with pytest.raises(CalibrationContractError):
        Rate(5, 4)
    with pytest.raises(CalibrationContractError):
        Rate(1.0, 4)                                                    # type: ignore[arg-type]


def test_level_conditional_counts_and_decimal_rates() -> None:                          # 28, 29
    counts = count_outcomes([RealizedOutcome.UP, RealizedOutcome.UP, RealizedOutcome.RANGE])
    assert counts == OutcomeCounts(up=2, range=1, down=0) and counts.total == 3
    assert counts.as_dict() == {"UP": 2, "RANGE": 1, "DOWN": 0, "total": 3}
    p_up = Rate(counts.up, counts.total)
    assert isinstance(p_up.value, Decimal) and p_up.value == Decimal("0.6666666666666666666666666667")
    assert Rate(1, 3).value == Rate(1, 3).value                         # 決定論的
    assert METRIC_BY_NAME["level_outcome_frequency"].denominator is Denominator.LEVEL_WITH_ACTIVE_EVALUATED


# ---------------------------------------------------------------- 30–32 confidence

def test_confidence_buckets_and_metric_denominators() -> None:                          # 30–32
    assert CONFIDENCE_BUCKETS == ("HIGH", "MEDIUM", "LOW")
    assert METRIC_BY_NAME["confidence_completion_rate"].denominator is Denominator.CONFIDENCE_PREDICTIONS
    assert METRIC_BY_NAME["confidence_exact_match_rate"].denominator is Denominator.CONFIDENCE_WITH_ACTIVE_EVALUATED
    assert METRIC_BY_NAME["confidence_exact_match_rate"].kind is MetricKind.EXACT_MATCH
    assert {make().confidence, make(confidence="MEDIUM").confidence,
            make(level=SignalLevel.NEUTRAL_RANGE, confidence="LOW").confidence} == set(CONFIDENCE_BUCKETS)


# ---------------------------------------------------------------- 33–36 abstention / coverage

def test_abstention_and_coverage_metric_contracts() -> None:                            # 33–36
    total = [make(), make(session_date="2026-09-18", reference_session="2026-09-17"),
             make_prediction_record(**abstained_kwargs())]
    abstained = [p for p in total if PredictionCohort.ABSTAINED in prediction_cohorts(p)]
    rate = Rate(len(abstained), len(total))
    assert (rate.numerator, rate.denominator) == (1, 3)
    assert METRIC_BY_NAME["abstained_outcome_frequency"].denominator is Denominator.ABSTAINED_WITH_ACTIVE_EVALUATED
    assert METRIC_BY_NAME["abstained_outcome_frequency"].kind is MetricKind.DESCRIPTIVE   # 採点しない
    completion = METRIC_BY_NAME["evaluation_completion_rate"]
    assert completion.kind is MetricKind.COVERAGE and completion.denominator is Denominator.PREDICTIONS_IN_COHORT
    coverage = [resolve_active_evaluation(p.prediction_id, [evaluated()]).coverage for p in total]
    assert coverage.count(EvaluationCoverage.ACTIVE_EVALUATED) == 1
    assert coverage.count(EvaluationCoverage.NO_EVALUATION) == 2


# ---------------------------------------------------------------- 37–39 sessions / cohort boundary

def test_unique_sessions_and_no_dedupe_by_date() -> None:                                # 37, 38
    same_day = [make(), make(level=SignalLevel.DOWNWARD_LEAN),
                make_prediction_record(**base_kwargs(origin=PredictionOrigin.REPLAY))]
    assert len({p.prediction_id for p in same_day}) == 3 and unique_session_count(same_day) == 1
    live = CohortBoundary(PredictionOrigin.LIVE, "2026-09-17", "2026-09-17")
    assert len(live.select(same_day)) == 2                             # 同一 session の 2 予測を両方保持
    assert "session_date" in source() and "dedup" not in source()


def test_cohort_start_and_end_are_explicit_and_based_on_session_date() -> None:         # 39
    boundary = CohortBoundary(PredictionOrigin.LIVE, "2026-09-01", "2026-09-16")
    assert boundary.label == "LIVE 2026-09-01..2026-09-16"
    assert not boundary.contains(make())                                # session 2026-09-17 は範囲外
    assert boundary.as_dict() == {"origin": "LIVE", "start_session": "2026-09-01", "end_session": "2026-09-16"}
    with pytest.raises(TypeError):
        CohortBoundary(PredictionOrigin.LIVE)                           # type: ignore[call-arg]
    with pytest.raises(CalibrationContractError):
        CohortBoundary(PredictionOrigin.LIVE, "2026-09-30", "2026-09-01")
    with pytest.raises(CalibrationContractError):
        CohortBoundary(PredictionOrigin.LIVE, "2026/09/01", "2026-09-30")
    params = inspect.signature(CohortBoundary).parameters
    assert all(p.default is inspect.Parameter.empty for p in params.values())


# ---------------------------------------------------------------- 40–45 sample disclosure

@pytest.mark.parametrize("n,label", [
    (0, SampleDisclosure.NO_DATA),                                      # 40
    (1, SampleDisclosure.INSUFFICIENT_SAMPLE), (9, SampleDisclosure.INSUFFICIENT_SAMPLE),   # 41
    (10, SampleDisclosure.LIMITED_SAMPLE), (29, SampleDisclosure.LIMITED_SAMPLE),          # 42
    (30, SampleDisclosure.REPORTABLE), (1000, SampleDisclosure.REPORTABLE),                # 43
])
def test_sample_disclosure_thresholds(n: int, label: SampleDisclosure) -> None:
    assert sample_disclosure(n) is label
    assert SAMPLE_DISCLOSURE_THRESHOLDS == (10, 30) and SAMPLE_DISCLOSURE_VERSION == "sample_disclosure:1.0.0"


def test_raw_count_survives_insufficient_sample_and_no_significance_claim() -> None:    # 44, 45
    rate = Rate(2, 3)
    assert rate.disclosure is SampleDisclosure.INSUFFICIENT_SAMPLE
    assert rate.as_dict()["numerator"] == 2 and rate.as_dict()["denominator"] == 3     # 生の件数は残る
    src = source()
    for token in ("significan", "p_value", "confidence_interval", "z_score", "t_test", "sharpe",
                  "annualiz", "pnl", "p&l", "backtest", "transaction_cost"):
        assert token not in src.lower(), token
    with pytest.raises(CalibrationContractError):
        sample_disclosure(-1)
    with pytest.raises(CalibrationContractError):
        sample_disclosure(True)


# ---------------------------------------------------------------- 46–47 numeric policy

def test_rates_and_summaries_are_decimal_with_no_float_authority() -> None:              # 46, 47
    summary = summarize_returns([evaluated(), evaluated(realized_return=Decimal("-0.004"),
                                                        target_close=Decimal("2689.2"))])
    assert isinstance(summary.mean, Decimal) and isinstance(summary.median, Decimal)
    assert summary.n == 2 and summary.outcomes == OutcomeCounts(up=1, range=0, down=1)
    assert summary.minimum == Decimal("-0.004") and summary.maximum == evaluated().realized_return
    assert summary.disclosure is SampleDisclosure.INSUFFICIENT_SAMPLE
    assert summarize_returns([]) == ReturnSummary(0, None, None, None, None, None, OutcomeCounts())
    assert summarize_returns([]).as_dict()["disclosure"] == "NO_DATA"
    odd = summarize_returns([evaluated(realized_return=Decimal(v), target_close=Decimal("2700") * (1 + Decimal(v)))
                             for v in ("0.01", "-0.02", "0.005")])
    assert odd.median == Decimal("0.005")
    src = source()
    for token in ("float(", "round(", "quantize", "statistics", "math.", "numpy", "pandas"):
        assert token not in src, token
    assert RATE_CONTEXT.prec == 28
    previous = getcontext().prec
    try:
        getcontext().prec = 5
        assert Rate(1, 3).value == Decimal("0.3333333333333333333333333333")   # ambient context 非依存
    finally:
        getcontext().prec = previous


# ---------------------------------------------------------------- 48–50 digests / lineage

def test_cohort_digest_is_deterministic_and_order_independent() -> None:                 # 48
    a, b = make(), make(level=SignalLevel.DOWNWARD_LEAN)
    assert cohort_digest([a, b]) == cohort_digest([b, a]) == cohort_digest([a, b, a])
    assert cohort_digest([a]) != cohort_digest([a, b])
    assert cohort_digest([]).startswith("cal_") and len(cohort_digest([])) == 28
    assert content_digest(["x", "y"]) == content_digest(("y", "x"))


def test_active_evaluation_digest_changes_with_a_correction() -> None:                  # 49, 50
    a, b, c = chain()
    before = active_evaluation_digest([resolve_active_evaluation(PID, [a])])
    after = active_evaluation_digest([resolve_active_evaluation(PID, [a, b])])
    final = active_evaluation_digest([resolve_active_evaluation(PID, [a, b, c])])
    assert before != after != final and before != final
    assert active_evaluation_digest([resolve_active_evaluation(PID, [b, a])]) == after
    lineage = CalibrationLineage(prediction_record_count=1, evaluation_record_count=3,
                                 cohort_digest=cohort_digest([make()]), active_evaluation_digest=final)
    assert lineage.as_dict()["mapping_version"] == PREDICTION_DIRECTION_MAPPING_VERSION
    assert lineage.as_dict()["resolver_version"] == ACTIVE_EVALUATION_RESOLVER_VERSION == "active_evaluation_resolver:1.0.0"
    assert lineage.as_dict()["calibration_contract_version"] == CALIBRATION_CONTRACT_VERSION == "calibration_contract:0.1.0"
    with pytest.raises(CalibrationContractError):
        CalibrationLineage(-1, 0, "cal_x", "cal_y")
    assert "hashlib" not in source() and "prev_hash" not in source() and "chain_hash" not in source()


# ---------------------------------------------------------------- 51–60 immutability / no coupling

def test_journals_records_and_inputs_are_not_mutated() -> None:                         # 51–53
    pred, evals = make(), list(chain())
    before = (pred.as_dict(), [e.as_dict() for e in evals])
    resolve_active_evaluation(PID, evals)
    summarize_returns([evals[1], evals[2]])
    prediction_cohorts(pred)
    assert (pred.as_dict(), [e.as_dict() for e in evals]) == before
    src = source()
    for token in ("open(", "write", "jsonl", "Path(", "append(", "setattr", "replace(", "MarketSignal",
                  "market_signal.build", "LEVEL_BY_STATE", "SIGNAL_LEVEL_JA"):
        assert token not in src.replace("successors.setdefault(predecessor, []).append(", "")\
                                 .replace("chain.append(", "").replace("values.append(", "")\
                                 .replace("outcomes.append(", ""), token
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolve_active_evaluation(PID, evals).status = ResolutionStatus.FORK   # type: ignore[misc]


def test_no_compass_dna_threshold_or_confidence_tuning() -> None:                      # 54, 58, 59
    src = source()
    for token in ("market_rules", "compass_dna", "knowledge/", "yaml", "threshold", "tune", "optimiz",
                  "NEUTRAL_BAND", "0.003", "Confidence.HIGH", "promote", "formal_review"):
        assert token not in src, token
    assert NEUTRAL_BAND_RULE_VERSION == "topix_neutral_band:1.0.0"      # 分類版は参照のみ


def test_no_market_calendar_network_or_engine_dependency() -> None:                     # 55, 56
    allowed = {"__future__", "dataclasses", "decimal", "enum", "typing", "..core.ids",
               "..reports.market_signal", ".evaluation_record", ".prediction_record"}
    assert imported_modules(MODULE_PATH) <= allowed
    src = source()
    for token in ("evaluation_engine", "evaluation_store", "prediction_store", "tokyo_calendar",
                  "market.model", "Observation", "jquants", "urllib", "requests", "http", "socket",
                  "environ", "getenv", "topix_research", "neutral_band_measure"):
        assert token not in src, token


def test_no_public_runtime_or_trading_semantics() -> None:                             # 57, 60
    assert "predictions" in EXCLUDED_PACKAGES
    assert not any("predictions" in m for m in runtime_closure())
    offenders = [str(p.relative_to(REPO_ROOT))
                 for p in list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py"))
                 if p.parent != MODULE_PATH.parent and "calibration_contract" in p.read_text(encoding="utf-8")]
    assert offenders == []
    src = source().lower()
    for token in ("delivery", "pages", "render", "notification", "argparse", "__main__", "recommend",
                  "buy", "sell", "position", "portfolio", "backtest", "sharpe", "pnl", "trade"):
        assert token not in src, token


def test_metric_definitions_are_frozen_and_name_their_denominators() -> None:
    names = [m.name for m in METRIC_DEFINITIONS]
    assert len(names) == len(set(names)) == 9
    assert all(isinstance(m.denominator, Denominator) and isinstance(m.kind, MetricKind) for m in METRIC_DEFINITIONS)
    assert {m.kind for m in METRIC_DEFINITIONS} == set(MetricKind)
    with pytest.raises(dataclasses.FrozenInstanceError):
        METRIC_DEFINITIONS[0].denominator = Denominator.TOTAL_PREDICTIONS   # type: ignore[misc]
    assert isinstance(METRIC_BY_NAME, dict) and set(METRIC_BY_NAME) == set(names)
