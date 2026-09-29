"""Phase 5 P5-3B — 純粋 OFFLINE 較正 analyzer の凍結ガード。

gate §26 の 80 項目を、凍結 PredictionRecord / EvaluationRecord の fixture だけで証明する。
store・filesystem・market・calendar・network・evaluation_engine に触れない。
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from src.intelligence.predictions import calibration_analyzer as ca
from src.intelligence.predictions.calibration_analyzer import (
    CALIBRATION_REPORT_SCHEMA_VERSION,
    UNRESOLVED_STATUSES,
    AbstentionSummary,
    CalibrationInputError,
    CalibrationReport,
    ConfusionMatrix,
    CoverageCounts,
    GroupSummary,
    analyze_calibration,
)
from src.intelligence.predictions.calibration_contract import (
    ACTIVE_EVALUATION_RESOLVER_VERSION,
    CALIBRATION_CONTRACT_VERSION,
    CONFIDENCE_BUCKETS,
    LEVEL_ROWS,
    PREDICTION_DIRECTION_MAPPING_VERSION,
    SAMPLE_DISCLOSURE_VERSION,
    CohortBoundary,
    OutcomeCounts,
    Rate,
    ResolutionStatus,
    SampleDisclosure,
    active_evaluation_digest,
    resolve_active_evaluation,
)
from src.intelligence.predictions.evaluation_record import (
    NEUTRAL_BAND_RULE_VERSION,
    DeferReason,
    EvaluationRecord,
    EvaluationStatus,
    RealizedOutcome,
    SessionVerification,
    make_evaluation_record,
)
from src.intelligence.predictions.prediction_record import (
    PredictionOrigin,
    PredictionRecord,
    make_prediction_record,
)
from src.intelligence.reports.market_signal import SignalLevel
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "calibration_analyzer.py"
NOW = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
RECORDED = datetime(2026, 9, 1, 6, 30, tzinfo=timezone.utc)
LIVE, REPLAY = PredictionOrigin.LIVE, PredictionOrigin.REPLAY
COHORT = CohortBoundary(LIVE, "2026-09-01", "2026-09-30")


# ---------------------------------------------------------------- fixtures（凍結 builder のみ）

def pred(session: str, reference: str, level: SignalLevel = SignalLevel.UPWARD_LEAN,
         confidence: str = "HIGH", *, origin: PredictionOrigin = LIVE, available: bool = True,
         reason: str = "", brief: str = "brief_" + "a" * 24) -> PredictionRecord:
    return make_prediction_record(
        session_date=session, reference_session=reference, origin=origin, available=available,
        level=level if available else None, confidence=confidence if available else "",
        horizon="next_tokyo_session" if available else "", unavailable_reason=reason,
        brief_id=brief, signal_id="sig_" + "b" * 24, morning_brief_schema_version="0.2.0",
        market_signal_schema_version="0.1.0", recorded_at=RECORDED)


def abstained(session: str, reference: str, **kw) -> PredictionRecord:
    return pred(session, reference, available=False, reason="draft_abstained", **kw)


def verification(p: PredictionRecord) -> SessionVerification:
    return SessionVerification(calendar_source_id="jquants:/v2/markets/calendar", trading_divisions=("1",),
                               checked_dates=5, agreements=5, disagreement_count=0,
                               verified_session=p.session_date, verified_previous_session=p.reference_session)


def ev(p: PredictionRecord, ret: Optional[str] = None, *, deferred: bool = False, supersedes: str = "",
       created_at: datetime = NOW, target_oid: str = "obs_" + "1" * 24) -> EvaluationRecord:
    if deferred:
        return make_evaluation_record(
            prediction_id=p.prediction_id, reference_session=p.reference_session, session_date=p.session_date,
            status=EvaluationStatus.DEFERRED, created_at=created_at,
            defer_reason=DeferReason.TARGET_CLOSE_UNAVAILABLE, reference_close=Decimal("2700"),
            supersedes_evaluation_id=supersedes)
    r = Decimal(ret)
    return make_evaluation_record(
        prediction_id=p.prediction_id, reference_session=p.reference_session, session_date=p.session_date,
        status=EvaluationStatus.EVALUATED, created_at=created_at, realized_return=r,
        reference_close=Decimal("2700"), target_close=Decimal("2700") * (Decimal(1) + r),
        reference_observation_id="obs_" + "0" * 24, target_observation_id=target_oid, source_id="jquants",
        market_schema_version="0.4.0", session_verification=verification(p),
        supersedes_evaluation_id=supersedes)


def mixed_world():
    """cohort 内 6 予測（5 session）＋ REPLAY 1 ＋ 範囲外 1、評価 10（chain・fork・orphan を含む）。"""
    p1 = pred("2026-09-02", "2026-09-01")                                        # UP match
    p2 = pred("2026-09-03", "2026-09-02", SignalLevel.NEUTRAL_RANGE, "LOW")       # RANGE match
    p3 = pred("2026-09-04", "2026-09-03", SignalLevel.DOWNWARD_LEAN, "MEDIUM")    # DEFERRED → EVALUATED UP（非 match）
    p4 = abstained("2026-09-04", "2026-09-03")                                    # 棄権（同 session）
    p5 = pred("2026-09-07", "2026-09-04", SignalLevel.SLIGHT_UPWARD_LEAN, "LOW")  # 評価なし
    p6 = pred("2026-09-08", "2026-09-07", origin=REPLAY)                          # REPLAY → cohort 外
    p7 = pred("2026-10-01", "2026-09-30")                                         # 期間外
    p8 = pred("2026-09-09", "2026-09-08", SignalLevel.SLIGHT_DOWNWARD_LEAN, "LOW")  # fork → UNRESOLVED
    e1, e2 = ev(p1, "0.01"), ev(p2, "0.001")
    e3a = ev(p3, deferred=True)
    e3b = ev(p3, "0.02", supersedes=e3a.evaluation_id)
    e4, e6, e7 = ev(p4, "-0.01"), ev(p6, "0.01"), ev(p7, "0.01")
    e8a = ev(p8, "0")
    e8b = ev(p8, "0.001", supersedes=e8a.evaluation_id)
    e8c = ev(p8, "0.002", supersedes=e8a.evaluation_id)
    preds = dict(p1=p1, p2=p2, p3=p3, p4=p4, p5=p5, p6=p6, p7=p7, p8=p8)
    evals = [e1, e2, e3a, e3b, e4, e6, e7, e8a, e8b, e8c]
    return preds, evals


def report(preds=None, evals=None, cohort: CohortBoundary = COHORT) -> CalibrationReport:
    if preds is None:
        world, evals_default = mixed_world()
        preds, evals = list(world.values()), evals_default if evals is None else evals
    return analyze_calibration(preds, evals, cohort)


def level_summary(rep: CalibrationReport, level: SignalLevel) -> GroupSummary:
    return next(s for s in rep.level_summaries if s.key == level.value)


def confidence_summary(rep: CalibrationReport, confidence: str) -> GroupSummary:
    return next(s for s in rep.confidence_summaries if s.key == confidence)


def source() -> str:
    return executable_source(MODULE_PATH)


# ---------------------------------------------------------------- 1–10 cohort

def test_basic_mixed_cohort_report() -> None:                                            # 1, 9, 10
    rep = report()
    assert rep.schema_version == CALIBRATION_REPORT_SCHEMA_VERSION == "calibration_report:0.1.0"
    assert rep.prediction_count == 6 and rep.unique_session_count == 5
    assert rep.supplied_prediction_count == 8 and rep.supplied_evaluation_count == 10
    assert rep.associated_evaluation_count == 8 and rep.foreign_evaluation_count == 2
    assert rep.coverage.as_dict()["predictions"] == 6


def test_cohort_origin_filtering_and_live_replay_separation() -> None:                   # 2, 6, 7
    world, evals = mixed_world()
    live = report()
    replay = analyze_calibration(world.values(), evals, CohortBoundary(REPLAY, "2026-09-01", "2026-09-30"))
    assert live.prediction_count == 6 and replay.prediction_count == 1
    assert replay.directional_match.as_dict() == {"numerator": 1, "denominator": 1, "value": "1",
                                                  "disclosure": "INSUFFICIENT_SAMPLE"}
    assert live.lineage.cohort_digest != replay.lineage.cohort_digest
    assert inspect.signature(analyze_calibration).parameters["cohort"].default is inspect.Parameter.empty
    assert "COMBINED" not in source() and "combined" not in source()


def test_inclusive_start_and_end_boundaries_and_outside_exclusion() -> None:            # 3, 4, 5
    world, evals = mixed_world()
    start_only = analyze_calibration(world.values(), evals, CohortBoundary(LIVE, "2026-09-02", "2026-09-02"))
    assert start_only.prediction_count == 1 and start_only.coverage.active_evaluated == 1
    end_only = analyze_calibration(world.values(), evals, CohortBoundary(LIVE, "2026-09-08", "2026-09-09"))
    assert end_only.prediction_count == 1 and end_only.coverage.unresolved == 1       # p8 のみ（p6 は REPLAY）
    october = analyze_calibration(world.values(), evals, CohortBoundary(LIVE, "2026-10-01", "2026-10-31"))
    assert october.prediction_count == 1 and october.directional_match.denominator == 1
    assert report().prediction_count == 6                                             # p7（10-01）は 9 月 cohort 外
    src = source()
    for token in ("created_at", "today(", "now(", "line_number"):
        assert token not in src, token


def test_same_session_multiple_prediction_ids_are_retained() -> None:                    # 8
    rep = report()
    assert rep.prediction_count == 6 and rep.unique_session_count == 5                  # p3 と p4 が同 session
    assert rep.abstention.abstained == 1 and rep.abstention.total_predictions == 6
    assert "dedup" not in source()


# ---------------------------------------------------------------- 11–20 association / coverage

def test_active_evaluated_association_is_by_prediction_id_only() -> None:               # 11
    world, evals = mixed_world()
    p1 = world["p1"]
    stranger = pred("2026-09-02", "2026-09-01", SignalLevel.DOWNWARD_LEAN, "MEDIUM", brief="brief_" + "c" * 24)
    rep = analyze_calibration([p1, stranger], [ev(p1, "0.01")], COHORT)               # 同じ session の別予測
    assert rep.coverage.active_evaluated == 1 and rep.coverage.no_evaluation == 1
    assert level_summary(rep, SignalLevel.DOWNWARD_LEAN).coverage.no_evaluation == 1
    src = source()
    assert "resolve_active_evaluation(p.prediction_id" in src
    for token in ("session_date ==", "reference_session ==", "sorted(evaluations, key=lambda e: e.created_at"):
        assert token not in src, token


def test_active_deferred_no_evaluation_and_unresolved_buckets() -> None:                # 12–15
    world, evals = mixed_world()
    rep = report()
    assert rep.coverage.active_evaluated == 4 and rep.coverage.active_deferred == 0
    assert rep.coverage.no_evaluation == 1 and rep.coverage.unresolved == 1
    assert rep.coverage.unresolved_by_status == {"FORK": 1}
    assert rep.unresolved_prediction_ids == (world["p8"].prediction_id,)
    only_deferred = analyze_calibration([world["p3"]], [evals[2]], COHORT)             # e3a のみ
    assert only_deferred.coverage.active_deferred == 1 and only_deferred.directional_match.denominator == 0
    independent = analyze_calibration([world["p1"]], [ev(world["p1"], "0.01"), ev(world["p1"], "0.02")], COHORT)
    assert independent.coverage.unresolved == 1
    assert independent.coverage.unresolved_by_status == {"MULTIPLE_TERMINALS": 1}
    assert set(independent.coverage.as_dict()["unresolved_by_status"]) == {s.value for s in UNRESOLVED_STATUSES}


def test_unresolved_deferred_and_no_evaluation_stay_out_of_outcome_denominators() -> None:  # 16–18
    rep = report()
    assert rep.directional_match.denominator == 3                                     # p1, p2, p3 だけ
    assert rep.confusion_matrix.total == 3 and rep.overall.outcomes.total == 3
    assert level_summary(rep, SignalLevel.SLIGHT_DOWNWARD_LEAN).directional_match.denominator == 0   # fork
    assert level_summary(rep, SignalLevel.SLIGHT_UPWARD_LEAN).directional_match.denominator == 0     # 評価なし


def test_unavailable_excluded_from_exact_match_but_retained_in_abstention() -> None:    # 19, 20
    rep = report()
    assert rep.abstention.abstained == 1 and rep.abstention.coverage.active_evaluated == 1
    assert rep.abstention.outcome.outcomes == OutcomeCounts(down=1)
    assert rep.directional_match.denominator == 3                                     # p4 は入らない
    assert rep.coverage.predictions == 6                                              # ALL coverage には残る


# ---------------------------------------------------------------- 21–27 exact match / matrix

def test_directional_numerator_denominator_and_decimal_rate() -> None:                  # 21–23
    rep = report()
    match = rep.directional_match
    assert (match.numerator, match.denominator) == (2, 3)                             # p1 UP✓ p2 RANGE✓ p3 UP✗
    assert isinstance(match.value, Decimal) and match.value == Decimal("0.6666666666666666666666666667")
    assert match.as_dict()["disclosure"] == "INSUFFICIENT_SAMPLE"


def test_confusion_matrix_shape_zero_cells_and_total() -> None:                         # 24–27
    rep = report()
    d = rep.confusion_matrix.as_dict()
    assert list(d["rows"]) == [l.value for l in LEVEL_ROWS] and d["columns"] == ["UP", "RANGE", "DOWN"]
    assert d["rows"]["UPWARD_LEAN"]["UP"] == 1 and d["rows"]["NEUTRAL_RANGE"]["RANGE"] == 1
    assert d["rows"]["DOWNWARD_LEAN"]["UP"] == 1 and d["rows"]["DOWNWARD_LEAN"]["DOWN"] == 0
    assert d["rows"]["SLIGHT_UPWARD_LEAN"] == {"UP": 0, "RANGE": 0, "DOWN": 0, "total": 0,
                                               "row_frequencies": {o: {"numerator": 0, "denominator": 0, "value": None,
                                                                       "disclosure": "NO_DATA"} for o in ("UP", "RANGE", "DOWN")}}
    assert d["total"] == rep.directional_match.denominator == 3
    with pytest.raises(CalibrationInputError):
        ConfusionMatrix(rows={SignalLevel.UPWARD_LEAN: OutcomeCounts()})


# ---------------------------------------------------------------- 28–31 level summaries

def test_level_summaries_all_five_with_counts_match_and_returns() -> None:              # 28–31
    rep = report()
    assert [s.key for s in rep.level_summaries] == [l.value for l in LEVEL_ROWS]
    up = level_summary(rep, SignalLevel.UPWARD_LEAN)
    assert up.coverage.predictions == 1 and up.outcome.outcomes == OutcomeCounts(up=1)
    assert (up.directional_match.numerator, up.directional_match.denominator) == (1, 1)
    assert up.outcome.returns.n == 1 and up.outcome.returns.mean == Decimal("0.01")
    down = level_summary(rep, SignalLevel.DOWNWARD_LEAN)
    assert (down.directional_match.numerator, down.directional_match.denominator) == (0, 1)
    assert down.outcome.returns.mean == Decimal("0.02") and down.outcome.frequency(RealizedOutcome.UP).value == Decimal("1")
    neutral = level_summary(rep, SignalLevel.NEUTRAL_RANGE)
    assert neutral.outcome.frequency(RealizedOutcome.RANGE).as_dict()["numerator"] == 1
    assert level_summary(rep, SignalLevel.SLIGHT_UPWARD_LEAN).outcome.returns.n == 0
    for s in rep.level_summaries:
        assert s.coverage.predictions == s.coverage.active_evaluated + s.coverage.active_deferred + \
            s.coverage.no_evaluation + s.coverage.unresolved


# ---------------------------------------------------------------- 32–37 confidence summaries

def test_confidence_summaries_all_three_and_zero_bucket_preserved() -> None:            # 32–35
    rep = report()
    assert [s.key for s in rep.confidence_summaries] == list(CONFIDENCE_BUCKETS) == ["HIGH", "MEDIUM", "LOW"]
    assert confidence_summary(rep, "HIGH").coverage.predictions == 1
    assert confidence_summary(rep, "MEDIUM").coverage.predictions == 1
    assert confidence_summary(rep, "LOW").coverage.predictions == 3                    # p2, p5, p8
    world, evals = mixed_world()
    only_high = analyze_calibration([world["p1"]], evals, COHORT)
    low = confidence_summary(only_high, "LOW")
    assert low.coverage.predictions == 0 and low.directional_match.disclosure is SampleDisclosure.NO_DATA
    assert low.outcome.returns.as_dict()["disclosure"] == "NO_DATA"


def test_confidence_completion_and_exact_match_denominators() -> None:                  # 36, 37
    rep = report()
    low = confidence_summary(rep, "LOW")
    assert low.coverage.completion_rate.as_dict()["denominator"] == 3                  # 予測件数（available）
    assert low.coverage.completion_rate.numerator == 1                                 # p2 のみ評価済み
    assert (low.directional_match.numerator, low.directional_match.denominator) == (1, 1)  # active EVALUATED のみ
    assert confidence_summary(rep, "MEDIUM").directional_match.as_dict() == {
        "numerator": 0, "denominator": 1, "value": "0", "disclosure": "INSUFFICIENT_SAMPLE"}


def test_confidence_summaries_cover_available_predictions_only() -> None:
    # direction_mixed は P4 の outlook confidence/horizon を保持したまま棄権する唯一の理由。
    # confidence="MEDIUM" を持っていても、棄権予測は confidence 集計・方向一致の母集団に入らない。
    mixed_with_conf = make_prediction_record(
        session_date="2026-09-02", reference_session="2026-09-01", origin=LIVE, available=False, level=None,
        confidence="MEDIUM", horizon="next_tokyo_session", unavailable_reason="direction_mixed",
        brief_id="brief_" + "a" * 24, signal_id="sig_" + "b" * 24,
        morning_brief_schema_version="0.2.0", market_signal_schema_version="0.1.0", recorded_at=RECORDED)
    rep = analyze_calibration([mixed_with_conf], [ev(mixed_with_conf, "0.01")], COHORT)
    assert rep.abstention.abstained == 1 and rep.abstention.outcome.outcomes == OutcomeCounts(up=1)
    assert sum(s.coverage.predictions for s in rep.confidence_summaries) == 0            # 棄権は confidence 集計外
    assert rep.directional_match.denominator == 0


# ---------------------------------------------------------------- 38 level × confidence

def test_level_confidence_cross_tab_has_all_fifteen_cells() -> None:                    # 38
    rep = report()
    keys = [c.key for c in rep.level_confidence]
    assert keys == [f"{l.value}|{c}" for l in LEVEL_ROWS for c in CONFIDENCE_BUCKETS] and len(keys) == 15
    by_key = {c.key: c for c in rep.level_confidence}
    assert by_key["UPWARD_LEAN|HIGH"].coverage.predictions == 1
    assert by_key["NEUTRAL_RANGE|HIGH"].coverage.predictions == 0                     # P4 が生成しない組も可視
    assert by_key["NEUTRAL_RANGE|LOW"].directional_match.as_dict()["numerator"] == 1
    assert sum(c.coverage.predictions for c in rep.level_confidence) == 5               # available 予測数


# ---------------------------------------------------------------- 39–41 abstention / overall returns

def test_abstention_outcomes_and_no_exact_match_for_abstentions() -> None:              # 39, 40
    rep = report()
    ab = rep.abstention.as_dict()
    assert ab["outcomes"] == {"UP": 0, "RANGE": 0, "DOWN": 1, "total": 1}
    assert ab["outcome_frequencies"]["DOWN"]["numerator"] == 1 and ab["returns"]["n"] == 1
    assert ab["abstention_rate"] == {"numerator": 1, "denominator": 6,
                                     "value": "0.1666666666666666666666666667", "disclosure": "INSUFFICIENT_SAMPLE"}
    assert "directional_exact_match" not in ab and not hasattr(rep.abstention, "directional_match")
    assert "predicted_direction" not in source()


def test_overall_available_return_summary_is_decimal_and_continuous() -> None:          # 41–43
    rep = report()
    returns = rep.overall.returns
    assert returns.n == 3 and isinstance(returns.mean, Decimal)
    assert returns.mean == (Decimal("0.01") + Decimal("0.001") + Decimal("0.02")) / Decimal(3)
    assert returns.median == Decimal("0.01") and returns.minimum == Decimal("0.001") and returns.maximum == Decimal("0.02")
    assert rep.overall.outcomes == OutcomeCounts(up=2, range=1)
    text = json.dumps(rep.as_dict())
    assert "0.0103333333333333333333333333" in text                                   # 連続値の canonical
    src = source()
    for token in ("float(", "round(", "quantize", "statistics", "math.", "numpy", "pandas"):
        assert token not in src, token
    assert not any(isinstance(v, float) for v in _flatten(rep.as_dict()))


def _flatten(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _flatten(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _flatten(v)
    else:
        yield value


# ---------------------------------------------------------------- 44–47 sample disclosure

@pytest.mark.parametrize("n,label", [(0, "NO_DATA"), (1, "INSUFFICIENT_SAMPLE"), (9, "INSUFFICIENT_SAMPLE"),
                                     (10, "LIMITED_SAMPLE"), (29, "LIMITED_SAMPLE"), (30, "REPORTABLE")])
def test_sample_disclosure_flows_from_frozen_rule(n: int, label: str) -> None:           # 44–47
    # session_date は予測 identity に入るため、n 件の相異なる session を用意する（8/1〜9/30 の広い cohort）。
    wide = CohortBoundary(LIVE, "2026-08-01", "2026-09-30")
    preds, evals = [], []
    for i in range(n):
        session = date(2026, 9, 30) - timedelta(days=i)
        p = pred(session.isoformat(), (session - timedelta(days=1)).isoformat(), brief="brief_" + f"{i:024d}")
        preds.append(p)
        evals.append(ev(p, "0.01"))
    assert len({p.prediction_id for p in preds}) == n
    rep = analyze_calibration(preds, evals, wide)
    assert rep.directional_match.denominator == n and rep.directional_match.as_dict()["disclosure"] == label
    assert rep.overall.returns.as_dict()["disclosure"] == label
    assert level_summary(rep, SignalLevel.UPWARD_LEAN).outcome.frequency(RealizedOutcome.UP).as_dict()["disclosure"] == label
    assert rep.directional_match.numerator == n                                       # 生の件数は常に残る


# ---------------------------------------------------------------- 48–50 empty cohort

def test_empty_cohort_is_a_valid_report() -> None:                                       # 48–50
    rep = analyze_calibration([], [], COHORT)
    d = rep.as_dict()
    assert d["prediction_count"] == 0 and d["unique_session_count"] == 0
    assert d["directional_exact_match"] == {"numerator": 0, "denominator": 0, "value": None, "disclosure": "NO_DATA"}
    assert d["coverage"]["evaluation_completion_rate"]["value"] is None
    assert d["abstention"]["abstention_rate"]["denominator"] == 0
    assert len(d["level_summaries"]) == 5 and len(d["confidence_summaries"]) == 3 and len(d["level_confidence"]) == 15
    assert list(d["confusion_matrix"]["rows"]) == [l.value for l in LEVEL_ROWS] and d["confusion_matrix"]["total"] == 0
    assert d["overall"]["returns"]["n"] == 0 and d["overall"]["returns"]["mean"] is None
    assert d["versions"]["realized_classification"] == [] and d["lineage"]["prediction_record_count"] == 0
    assert analyze_calibration([], [], COHORT).as_dict() == d


# ---------------------------------------------------------------- 51–53 determinism

def test_shuffled_inputs_give_identical_reports() -> None:                              # 51–53
    world, evals = mixed_world()
    baseline = report().as_dict()
    rng = random.Random(5)
    for _ in range(6):
        preds = list(world.values())
        evs = list(evals)
        rng.shuffle(preds)
        rng.shuffle(evs)
        assert analyze_calibration(preds, evs, COHORT).as_dict() == baseline
        assert analyze_calibration(reversed(preds), reversed(evs), COHORT).lineage == report().lineage
    assert json.dumps(baseline, sort_keys=True) == json.dumps(report().as_dict(), sort_keys=True)


# ---------------------------------------------------------------- 54–57 duplicates / orphans

def test_duplicate_prediction_and_evaluation_ids_fail_closed() -> None:                 # 54, 55
    world, evals = mixed_world()
    with pytest.raises(CalibrationInputError, match="duplicate prediction_id"):
        analyze_calibration(list(world.values()) + [world["p1"]], evals, COHORT)
    with pytest.raises(CalibrationInputError, match="duplicate evaluation_id"):
        analyze_calibration(world.values(), evals + [evals[0]], COHORT)
    with pytest.raises(CalibrationInputError):
        analyze_calibration([world["p1"].as_dict()], evals, COHORT)                   # type: ignore[list-item]
    with pytest.raises(CalibrationInputError):
        analyze_calibration(world.values(), [evals[0].as_dict()], COHORT)             # type: ignore[list-item]
    with pytest.raises(CalibrationInputError):
        analyze_calibration(world.values(), evals, ("LIVE", "2026-09-01", "2026-09-30"))  # type: ignore[arg-type]


def test_orphan_and_out_of_cohort_evaluations_are_excluded_from_metrics() -> None:      # 56, 57
    world, evals = mixed_world()
    baseline = report().as_dict()
    orphan = ev(pred("2026-09-15", "2026-09-14", brief="brief_" + "9" * 24), "0.05")      # 未知の prediction_id
    with_orphan = analyze_calibration(world.values(), evals + [orphan], COHORT)
    d = with_orphan.as_dict()
    for key in ("coverage", "directional_exact_match", "overall", "confusion_matrix", "level_summaries",
                "confidence_summaries", "abstention", "prediction_count"):
        assert d[key] == baseline[key], key
    assert with_orphan.foreign_evaluation_count == 3 and with_orphan.supplied_evaluation_count == 11
    assert d["lineage"]["evaluation_record_count"] == 11                              # 供給 source 件数
    assert d["lineage"]["active_evaluation_digest"] == baseline["lineage"]["active_evaluation_digest"]
    assert with_orphan.coverage.no_evaluation == 1                                    # orphan は誰の NO_EVALUATION も変えない


# ---------------------------------------------------------------- 58–62 correction / supersession

def test_correction_changes_active_outcome_metrics_and_digest() -> None:                # 58–60
    world, evals = mixed_world()
    p1 = world["p1"]
    before = analyze_calibration([p1], [ev(p1, "0.01")], COHORT)
    corrected = ev(p1, "-0.02", supersedes=ev(p1, "0.01").evaluation_id, created_at=NOW + timedelta(days=1))
    after = analyze_calibration([p1], [ev(p1, "0.01"), corrected], COHORT)
    assert before.directional_match.numerator == 1 and after.directional_match.numerator == 0
    assert after.overall.outcomes == OutcomeCounts(down=1) and after.overall.returns.mean == Decimal("-0.02")
    assert after.lineage.active_evaluation_digest != before.lineage.active_evaluation_digest
    assert after.lineage.cohort_digest == before.lineage.cohort_digest
    assert after.coverage.active_evaluated == 1 and after.confusion_matrix.total == 1  # superseded は数えない
    assert after.associated_evaluation_count == 2


def test_created_at_and_physical_order_do_not_select_the_active_record() -> None:      # 61, 62
    world, _ = mixed_world()
    p1 = world["p1"]
    original = ev(p1, "0.01", created_at=NOW + timedelta(days=5))                      # 新しい created_at
    correction = ev(p1, "-0.02", supersedes=original.evaluation_id, created_at=NOW - timedelta(days=5))  # 古い
    for order in ([original, correction], [correction, original]):
        rep = analyze_calibration([p1], order, COHORT)
        assert rep.overall.outcomes == OutcomeCounts(down=1)                          # supersession が決める
    assert "created_at" not in source() and "reversed(" not in source() and "[-1]" not in source()


# ---------------------------------------------------------------- 63–65 read-only

def test_inputs_are_unchanged_and_nothing_is_written(tmp_path: Path, monkeypatch) -> None:  # 63–65
    world, evals = mixed_world()
    before = ([p.as_dict() for p in world.values()], [e.as_dict() for e in evals])
    monkeypatch.chdir(tmp_path)
    report()
    assert ([p.as_dict() for p in world.values()], [e.as_dict() for e in evals]) == before
    assert list(tmp_path.iterdir()) == []
    src = source()
    for token in ("open(", "write", "jsonl", "Path(", "mkdir", "fsync", "store.", "Store(", "reload(", "setattr"):
        assert token not in src, token
    with pytest.raises(dataclasses.FrozenInstanceError):
        report().prediction_count = 0                                                # type: ignore[misc]


# ---------------------------------------------------------------- 66–75 dependencies

def test_no_store_requirement_and_no_forbidden_dependencies() -> None:                  # 66–71
    allowed = {"__future__", "dataclasses", "typing", "..reports.market_signal", ".calibration_contract",
               ".evaluation_record", ".prediction_record"}
    assert imported_modules(MODULE_PATH) <= allowed
    src = source()
    for token in ("PredictionStore", "EvaluationStore", "prediction_store", "evaluation_store",
                  "evaluation_engine", "tokyo_calendar", "market.model", "Observation", "jquants",
                  "urllib", "requests", "http", "socket", "environ", "getenv", "pipeline", "compass",
                  "build_market_signal", "MorningBrief"):
        assert token not in src, token


def test_no_public_output_tuning_or_trading_semantics() -> None:                        # 72–75
    assert "predictions" in EXCLUDED_PACKAGES
    assert not any("predictions" in m for m in runtime_closure())
    offenders = [str(p.relative_to(REPO_ROOT))
                 for p in list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py"))
                 if p.parent != MODULE_PATH.parent and "calibration_analyzer" in p.read_text(encoding="utf-8")]
    assert offenders == []
    src = source().lower()
    for token in ("delivery", "pages", "render", "notification", "argparse", "__main__", "threshold",
                  "tune", "optimiz", "market_rules", "compass_dna", "0.003", "recommend", "buy", "sell",
                  "portfolio", "backtest", "sharpe", "pnl", "annualiz", "trade"):
        assert token not in src, token


# ---------------------------------------------------------------- 76–80 lineage / schema / rates

def test_lineage_versions_and_order_independent_digests() -> None:                      # 76, 77
    rep = report()
    lineage = rep.lineage.as_dict()
    assert lineage["calibration_contract_version"] == CALIBRATION_CONTRACT_VERSION
    assert lineage["mapping_version"] == PREDICTION_DIRECTION_MAPPING_VERSION
    assert lineage["resolver_version"] == ACTIVE_EVALUATION_RESOLVER_VERSION
    assert lineage["sample_disclosure_version"] == SAMPLE_DISCLOSURE_VERSION
    assert lineage["prediction_record_count"] == 8 and lineage["evaluation_record_count"] == 10
    world, evals = mixed_world()
    selected = [p for p in world.values() if COHORT.contains(p)]
    expected = active_evaluation_digest(
        resolve_active_evaluation(p.prediction_id, [e for e in evals if e.prediction_id == p.prediction_id])
        for p in selected)
    assert lineage["active_evaluation_digest"] == expected
    assert rep.classification_versions == (NEUTRAL_BAND_RULE_VERSION,)


def test_report_schema_is_explicit_and_distinct() -> None:                              # 78
    versions = report().as_dict()["versions"]
    assert versions["calibration_report"] == "calibration_report:0.1.0"
    assert len({versions["calibration_report"], versions["calibration_contract"],
                versions["prediction_direction_mapping"], versions["active_evaluation_resolver"],
                versions["sample_disclosure"], versions["realized_classification"][0]}) == 6


def test_every_rate_exposes_numerator_denominator_and_raw_counts() -> None:            # 79, 80
    d = report().as_dict()
    rates = []

    def collect(value):
        if isinstance(value, dict):
            if set(value) == {"numerator", "denominator", "value", "disclosure"}:
                rates.append(value)
            for v in value.values():
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)
    collect(d)
    assert len(rates) >= 60
    for r in rates:
        assert isinstance(r["numerator"], int) and isinstance(r["denominator"], int)
        assert r["numerator"] <= r["denominator"]
        assert (r["value"] is None) == (r["denominator"] == 0)
    tiny = level_summary(report(), SignalLevel.DOWNWARD_LEAN).directional_match
    assert tiny.disclosure is SampleDisclosure.INSUFFICIENT_SAMPLE and (tiny.numerator, tiny.denominator) == (0, 1)
    with pytest.raises(CalibrationInputError):
        CoverageCounts(predictions=2, active_evaluated=1, active_deferred=0, no_evaluation=0, unresolved=0,
                       unresolved_by_status={})
