"""Phase 5 P5-3C — 較正 end-to-end OFFLINE 検証。

凍結 PredictionRecord 集合 ＋ 凍結 EvaluationRecord 履歴 ＋ 明示 CohortBoundary
    → `analyze_calibration`（P5-3B）→ CalibrationReport → 決定論的 `as_dict()`
    → 同等の入力 record を新しく再構築 → 同一 CalibrationReport

P5-3A（契約）と P5-3B（analyzer）を 1 つの分析系として検証する。CLI・runner・較正 store・
実 journal・network・market・calendar・evaluation_engine は使わない。fixture はすべて凍結
builder（`make_prediction_record` / `make_evaluation_record`）で作る隔離 object のみ。
"""
from __future__ import annotations

import dataclasses
import json
import random
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pytest

from src.intelligence.predictions.calibration_analyzer import (
    CALIBRATION_REPORT_SCHEMA_VERSION,
    CalibrationInputError,
    CalibrationReport,
    GroupSummary,
    analyze_calibration,
)
from src.intelligence.predictions.calibration_contract import (
    ACTIVE_EVALUATION_RESOLVER_VERSION,
    CALIBRATION_CONTRACT_VERSION,
    CONFIDENCE_BUCKETS,
    LEVEL_ROWS,
    METRIC_BY_NAME,
    OUTCOME_COLUMNS,
    PREDICTION_DIRECTION_MAPPING,
    PREDICTION_DIRECTION_MAPPING_VERSION,
    RATE_CONTEXT,
    SAMPLE_DISCLOSURE_VERSION,
    CohortBoundary,
    Denominator,
    EvaluationCoverage,
    PredictedDirection,
    ResolutionStatus,
    SampleDisclosure,
    active_evaluation_digest,
    cohort_digest,
    directional_exact_match,
    resolve_active_evaluation,
    summarize_returns,
)
from src.intelligence.predictions.evaluation_record import (
    NEUTRAL_BAND_RULE_VERSION,
    DeferReason,
    EvaluationRecord,
    EvaluationStatus,
    RealizedOutcome,
    SessionVerification,
    make_evaluation_record,
    parse_canonical_decimal,
)
from src.intelligence.predictions.prediction_record import (
    PredictionOrigin,
    PredictionRecord,
    make_prediction_record,
)
from src.intelligence.reports.market_signal import LEVEL_BY_STATE, SignalLevel
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "intelligence" / "predictions"
CONTRACT_DOC = REPO_ROOT / "docs" / "databank" / "PHASE5_ENTRY_CONTRACT.md"
NOW = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
RECORDED = datetime(2026, 9, 1, 6, 30, tzinfo=timezone.utc)
LIVE, REPLAY = PredictionOrigin.LIVE, PredictionOrigin.REPLAY
LIVE_COHORT = CohortBoundary(LIVE, "2026-09-01", "2026-09-30")
REPLAY_COHORT = CohortBoundary(REPLAY, "2026-09-01", "2026-09-30")
EMPTY_COHORT = CohortBoundary(LIVE, "2027-01-01", "2027-01-31")
UP, RANGE, DOWN = RealizedOutcome.UP, RealizedOutcome.RANGE, RealizedOutcome.DOWN
L = SignalLevel

#: P5-3A ＋ P5-3B の runtime import closure（§18。store / engine / ingest / market / calendar を含まない）
ALLOWED_CLOSURE = {
    "src.intelligence", "src.intelligence.compass", "src.intelligence.compass.model",
    "src.intelligence.core", "src.intelligence.core.ids", "src.intelligence.core.time",
    "src.intelligence.predictions", "src.intelligence.predictions.calibration_analyzer",
    "src.intelligence.predictions.calibration_contract", "src.intelligence.predictions.evaluation_record",
    "src.intelligence.predictions.prediction_record", "src.intelligence.reports",
    "src.intelligence.reports.market_signal", "src.intelligence.reports.model",
}
FORBIDDEN_MODULES = ("evaluation_engine", "prediction_ingest", "prediction_store", "evaluation_store",
                     "market.model", "tokyo_calendar", "jquants", "delivery", "pages", "notif")


# ---------------------------------------------------------------- fixtures（凍結 builder のみ）

def pred(session: str, reference: str, level: SignalLevel = L.UPWARD_LEAN, confidence: str = "HIGH", *,
         origin: PredictionOrigin = LIVE) -> PredictionRecord:
    return make_prediction_record(
        session_date=session, reference_session=reference, origin=origin, available=True, level=level,
        confidence=confidence, horizon="next_tokyo_session", unavailable_reason="",
        brief_id="brief_" + "a" * 24, signal_id="sig_" + "b" * 24, morning_brief_schema_version="0.2.0",
        market_signal_schema_version="0.1.0", recorded_at=RECORDED)


def abstained(session: str, reference: str, reason: str = "draft_abstained", confidence: str = "", *,
              origin: PredictionOrigin = LIVE) -> PredictionRecord:
    keeps_outlook = reason in ("direction_mixed", "direction_uncertain")     # P4 が confidence を保持する棄権
    return make_prediction_record(
        session_date=session, reference_session=reference, origin=origin, available=False, level=None,
        confidence=confidence if keeps_outlook else "", horizon="next_tokyo_session" if keeps_outlook else "",
        unavailable_reason=reason, brief_id="brief_" + "a" * 24, signal_id="sig_" + "b" * 24,
        morning_brief_schema_version="0.2.0", market_signal_schema_version="0.1.0", recorded_at=RECORDED)


def verification(p: PredictionRecord) -> SessionVerification:
    return SessionVerification(calendar_source_id="jquants:/v2/markets/calendar", trading_divisions=("1",),
                               checked_dates=5, agreements=5, disagreement_count=0,
                               verified_session=p.session_date, verified_previous_session=p.reference_session)


def ev(p: PredictionRecord, ret: Optional[str] = None, *, deferred: bool = False, supersedes: str = "",
       created_at: datetime = NOW) -> EvaluationRecord:
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
        reference_observation_id="obs_" + "0" * 24, target_observation_id="obs_" + "1" * 24,
        source_id="jquants", market_schema_version="0.4.0", session_verification=verification(p),
        supersedes_evaluation_id=supersedes)


@dataclasses.dataclass(frozen=True)
class World:
    """代表的な意味世界（label → record）。label は fixture の可読性のためだけにあり、分析には渡さない。"""

    predictions: Dict[str, PredictionRecord]
    evaluations: Dict[str, EvaluationRecord]

    def preds(self, *, only: Sequence[str] = ()) -> List[PredictionRecord]:
        return [p for k, p in self.predictions.items() if not only or k in only]

    def evals(self, *, without: Sequence[str] = (), extra: Sequence[EvaluationRecord] = ()) -> List[EvaluationRecord]:
        return [e for k, e in self.evaluations.items() if k not in without] + list(extra)


def build_world() -> World:
    """LIVE 18（available 14 ＋ 棄権 4）・REPLAY 3・期間外 2、評価 28（chain / fork / 独立 terminal / orphan）。"""
    P: Dict[str, PredictionRecord] = {}
    P["L1"] = pred("2026-09-02", "2026-09-01", L.UPWARD_LEAN, "HIGH")               # UP    一致
    P["L2"] = pred("2026-09-03", "2026-09-02", L.UPWARD_LEAN, "MEDIUM")             # DOWN  不一致
    P["L3"] = pred("2026-09-04", "2026-09-03", L.SLIGHT_UPWARD_LEAN, "LOW")         # UP    一致
    P["L4"] = pred("2026-09-07", "2026-09-04", L.NEUTRAL_RANGE, "LOW")              # RANGE 一致
    P["L5"] = pred("2026-09-08", "2026-09-07", L.NEUTRAL_RANGE, "LOW")              # UP    不一致
    P["L6"] = pred("2026-09-09", "2026-09-08", L.SLIGHT_DOWNWARD_LEAN, "LOW")       # DOWN  一致
    P["L7"] = pred("2026-09-10", "2026-09-09", L.DOWNWARD_LEAN, "HIGH")             # RANGE 不一致（return 0）
    P["L8"] = pred("2026-09-11", "2026-09-10", L.DOWNWARD_LEAN, "MEDIUM")           # DOWN  一致
    P["L9"] = pred("2026-09-14", "2026-09-11", L.DOWNWARD_LEAN, "HIGH")             # DEFERRED → EVALUATED UP 不一致
    P["L10"] = pred("2026-09-15", "2026-09-14", L.UPWARD_LEAN, "HIGH")              # UP → 訂正 DOWN 不一致
    P["L11"] = pred("2026-09-16", "2026-09-15", L.SLIGHT_UPWARD_LEAN, "LOW")        # 評価なし
    P["L12"] = pred("2026-09-17", "2026-09-16", L.UPWARD_LEAN, "MEDIUM")            # fork → UNRESOLVED
    P["L13"] = pred("2026-09-18", "2026-09-17", L.NEUTRAL_RANGE, "LOW")             # 独立 terminal 複数 → UNRESOLVED
    P["L14"] = pred("2026-09-18", "2026-09-17", L.UPWARD_LEAN, "HIGH")              # 同一 session の別 id。UP 一致
    P["A1"] = abstained("2026-09-02", "2026-09-01")                                 # 棄権・EVALUATED DOWN（同一 session）
    P["A2"] = abstained("2026-09-03", "2026-09-02", "direction_mixed", "MEDIUM")    # 棄権（confidence 保持）・DEFERRED
    P["A3"] = abstained("2026-09-04", "2026-09-03", "no_outlook")                   # 棄権・評価なし
    P["A4"] = abstained("2026-09-07", "2026-09-04", "direction_uncertain", "LOW")   # 棄権（confidence 保持）・fork
    P["R1"] = pred("2026-09-02", "2026-09-01", L.UPWARD_LEAN, "HIGH", origin=REPLAY)    # LIVE L1 と同 session
    P["R2"] = pred("2026-09-03", "2026-09-02", L.DOWNWARD_LEAN, "HIGH", origin=REPLAY)  # UP 不一致
    P["R3"] = abstained("2026-09-04", "2026-09-03", origin=REPLAY)                      # 棄権・評価なし
    P["O1"] = pred("2026-10-01", "2026-09-30")                                      # 期間外（後）
    P["O2"] = pred("2026-08-31", "2026-08-28")                                      # 期間外（前）
    unknown = pred("2026-09-25", "2026-09-24", L.NEUTRAL_RANGE, "LOW")             # 供給しない予測（orphan 評価用）

    E: Dict[str, EvaluationRecord] = {}
    E["L1"] = ev(P["L1"], "0.01")
    E["L2"] = ev(P["L2"], "-0.01")
    E["L3"] = ev(P["L3"], "0.005")
    E["L4"] = ev(P["L4"], "0.001")
    E["L5"] = ev(P["L5"], "0.02")
    E["L6"] = ev(P["L6"], "-0.02")
    E["L7"] = ev(P["L7"], "0")
    E["L8"] = ev(P["L8"], "-0.004")
    E["L9a"] = ev(P["L9"], deferred=True, created_at=NOW - timedelta(days=10))
    E["L9b"] = ev(P["L9"], "0.01", supersedes=E["L9a"].evaluation_id)
    E["L10a"] = ev(P["L10"], "0.01", created_at=NOW - timedelta(days=5))
    E["L10b"] = ev(P["L10"], "-0.01", supersedes=E["L10a"].evaluation_id, created_at=NOW - timedelta(days=6))
    E["L12a"] = ev(P["L12"], "0.01")
    E["L12b"] = ev(P["L12"], "0.02", supersedes=E["L12a"].evaluation_id, created_at=NOW - timedelta(days=1))
    E["L12c"] = ev(P["L12"], "-0.02", supersedes=E["L12a"].evaluation_id, created_at=NOW + timedelta(days=1))
    E["L13a"] = ev(P["L13"], "0.001")
    E["L13b"] = ev(P["L13"], "0.002")
    E["L14"] = ev(P["L14"], "0.03")
    E["A1"] = ev(P["A1"], "-0.01")
    E["A2"] = ev(P["A2"], deferred=True)
    E["A4a"] = ev(P["A4"], "0.01")
    E["A4b"] = ev(P["A4"], "0.02", supersedes=E["A4a"].evaluation_id)
    E["A4c"] = ev(P["A4"], "0.03", supersedes=E["A4a"].evaluation_id)
    E["R1"] = ev(P["R1"], "0.01")
    E["R2"] = ev(P["R2"], "0.01")
    E["O1"] = ev(P["O1"], "0.01")
    E["O2"] = ev(P["O2"], "0.01")
    E["X"] = ev(unknown, "0.001")
    return World(P, E)


LIVE_SELECTED = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11", "L12", "L13", "L14",
                 "A1", "A2", "A3", "A4")
ELIGIBLE = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L14")      # available ∧ active EVALUATED
ACTIVE_OF = {"L1": "L1", "L2": "L2", "L3": "L3", "L4": "L4", "L5": "L5", "L6": "L6", "L7": "L7", "L8": "L8",
             "L9": "L9b", "L10": "L10b", "L14": "L14"}
EXPECTED_MATRIX = {                                            # (level → (UP, RANGE, DOWN))。§5 の明示期待値
    L.UPWARD_LEAN: (2, 0, 2), L.SLIGHT_UPWARD_LEAN: (1, 0, 0), L.NEUTRAL_RANGE: (1, 1, 0),
    L.SLIGHT_DOWNWARD_LEAN: (0, 0, 1), L.DOWNWARD_LEAN: (1, 1, 1),
}
FOREIGN = ("R1", "R2", "O1", "O2", "X")


def analyze(world: World, cohort: CohortBoundary = LIVE_COHORT, **kw) -> CalibrationReport:
    return analyze_calibration(world.preds(), world.evals(**kw), cohort)


def level_summary(rep: CalibrationReport, level: SignalLevel) -> GroupSummary:
    return next(s for s in rep.level_summaries if s.key == level.value)


def confidence_summary(rep: CalibrationReport, confidence: str) -> GroupSummary:
    return next(s for s in rep.confidence_summaries if s.key == confidence)


def cell(rep: CalibrationReport, level: SignalLevel, confidence: str) -> GroupSummary:
    return next(s for s in rep.level_confidence if s.key == f"{level.value}|{confidence}")


def coverage_tuple(cov) -> Tuple[int, int, int, int]:
    return (cov.active_evaluated, cov.active_deferred, cov.no_evaluation, cov.unresolved)


def walk(value, path=()):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk(v, path + (k,))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from walk(v, path + (i,))
    else:
        yield path, value


def snapshot(world: World) -> Tuple[list, list]:
    return ([p.as_dict() for p in world.predictions.values()], [e.as_dict() for e in world.evaluations.values()])


@pytest.fixture(scope="module")
def world() -> World:
    return build_world()


# ---------------------------------------------------------------- §1 / §3 primary happy path

def test_e2e_primary_live_path(world: World) -> None:                                   # §3 1–8
    rep = analyze(world)
    assert rep.schema_version == CALIBRATION_REPORT_SCHEMA_VERSION == "calibration_report:0.1.0"
    assert rep.cohort == LIVE_COHORT and rep.as_dict()["cohort"] == LIVE_COHORT.as_dict()
    assert rep.prediction_count == 18 == len(LIVE_SELECTED)
    assert rep.unique_session_count == 13 == len({world.predictions[k].session_date for k in LIVE_SELECTED})
    assert rep.supplied_prediction_count == 23 and rep.supplied_evaluation_count == 28
    assert rep.associated_evaluation_count == 23 and rep.foreign_evaluation_count == 5
    assert rep.associated_evaluation_count + rep.foreign_evaluation_count == rep.supplied_evaluation_count
    assert coverage_tuple(rep.coverage) == (12, 1, 2, 3) and rep.coverage.predictions == 18
    assert dict(rep.coverage.unresolved_by_status) == {"FORK": 2, "MULTIPLE_TERMINALS": 1}
    assert set(rep.unresolved_prediction_ids) == {world.predictions[k].prediction_id for k in ("L12", "L13", "A4")}


def test_e2e_exact_match_matrix_and_groups(world: World) -> None:                       # §3 9–15
    rep = analyze(world)
    assert (rep.directional_match.numerator, rep.directional_match.denominator) == (6, 11)
    assert rep.directional_match.denominator == len(ELIGIBLE) == rep.confusion_matrix.total
    assert list(rep.confusion_matrix.rows) == list(LEVEL_ROWS) and len(rep.confusion_matrix.rows) == 5
    assert rep.as_dict()["confusion_matrix"]["columns"] == ["UP", "RANGE", "DOWN"] == [o.value for o in OUTCOME_COLUMNS]
    assert [s.key for s in rep.confidence_summaries] == ["HIGH", "MEDIUM", "LOW"]
    assert [s.key for s in rep.level_confidence] == [f"{l.value}|{c}" for l in LEVEL_ROWS for c in CONFIDENCE_BUCKETS]
    assert len(rep.level_confidence) == 15 and len(rep.level_summaries) == 5


def test_e2e_abstention_deferred_unresolved_separation(world: World) -> None:           # §3 16–21
    rep = analyze(world)
    ab = rep.as_dict()["abstention"]
    assert ab["abstained"] == 4 and ab["outcomes"] == {"UP": 0, "RANGE": 0, "DOWN": 1, "total": 1}
    assert "directional_exact_match" not in ab and not hasattr(rep.abstention, "directional_match")
    # DEFERRED（A2）は RANGE にならず、overall / 棄権 outcome のどこにも数えられない
    assert rep.overall.outcomes.total == 11 and rep.overall.outcomes.range == 2                 # L4, L7
    assert rep.abstention.coverage.active_deferred == 1 and rep.abstention.outcome.outcomes.total == 1
    # unresolved（L12 / L13）・評価なし（L11）は outcome 分母に入らない
    assert level_summary(rep, L.UPWARD_LEAN).coverage.unresolved == 1
    assert level_summary(rep, L.UPWARD_LEAN).directional_match.denominator == 4
    assert level_summary(rep, L.SLIGHT_UPWARD_LEAN).coverage.no_evaluation == 1
    assert level_summary(rep, L.SLIGHT_UPWARD_LEAN).directional_match.denominator == 1
    # return 要約は active EVALUATED（訂正後の active・DEFERRED→EVALUATED 後の active）だけ
    active_records = [world.evaluations[ACTIVE_OF[k]] for k in ELIGIBLE]
    assert rep.overall.returns == summarize_returns(active_records)
    assert rep.overall.returns.n == 11 and rep.overall.returns.median == Decimal("0.001")
    assert rep.overall.returns.minimum == Decimal("-0.02") and rep.overall.returns.maximum == Decimal("0.03")
    assert rep.overall.returns.mean == sum((r.realized_return for r in active_records), Decimal(0)) / Decimal(11)


def test_e2e_disclosure_versions_and_digests(world: World) -> None:                     # §3 22–25
    rep = analyze(world)
    assert rep.directional_match.disclosure is SampleDisclosure.LIMITED_SAMPLE                 # N = 11
    assert level_summary(rep, L.SLIGHT_DOWNWARD_LEAN).directional_match.disclosure is SampleDisclosure.INSUFFICIENT_SAMPLE
    assert rep.overall.returns.disclosure is SampleDisclosure.LIMITED_SAMPLE
    versions = rep.as_dict()["versions"]
    assert versions == {"calibration_report": "calibration_report:0.1.0",
                        "calibration_contract": CALIBRATION_CONTRACT_VERSION,
                        "prediction_direction_mapping": PREDICTION_DIRECTION_MAPPING_VERSION,
                        "active_evaluation_resolver": ACTIVE_EVALUATION_RESOLVER_VERSION,
                        "sample_disclosure": SAMPLE_DISCLOSURE_VERSION,
                        "realized_classification": [NEUTRAL_BAND_RULE_VERSION]}
    selected = [world.predictions[k] for k in LIVE_SELECTED]
    assert rep.lineage.cohort_digest == cohort_digest(selected)
    expected_active = active_evaluation_digest(
        resolve_active_evaluation(p.prediction_id, [e for e in world.evaluations.values()
                                                    if e.prediction_id == p.prediction_id])
        for p in sorted(selected, key=lambda p: p.prediction_id))
    assert rep.lineage.active_evaluation_digest == expected_active
    assert rep.lineage.prediction_record_count == 23 and rep.lineage.evaluation_record_count == 28


def test_e2e_fresh_reconstruction_yields_identical_report(world: World) -> None:        # §1 再構築
    baseline = analyze(world).as_dict()
    rebuilt = build_world()                                                                  # builder から再構築
    assert all(a is not b for a, b in zip(world.predictions.values(), rebuilt.predictions.values()))
    assert analyze(rebuilt).as_dict() == baseline
    # 凍結 from_dict による再構築（JSON を経由。journal reload と同等の入力集合）
    preds = [PredictionRecord.from_dict(json.loads(json.dumps(p.as_dict()))) for p in world.predictions.values()]
    evals = [EvaluationRecord.from_dict(json.loads(json.dumps(e.as_dict()))) for e in world.evaluations.values()]
    assert [p.prediction_id for p in preds] == [p.prediction_id for p in world.predictions.values()]
    assert analyze_calibration(preds, evals, LIVE_COHORT).as_dict() == baseline
    assert json.dumps(analyze_calibration(preds, evals, LIVE_COHORT).as_dict()) == json.dumps(baseline)


# ---------------------------------------------------------------- §4 LIVE / REPLAY separation

def test_e2e_live_and_replay_are_separate_reports(world: World) -> None:
    live, replay = analyze(world), analyze(world, REPLAY_COHORT)
    live_ids = {world.predictions[k].prediction_id for k in LIVE_SELECTED}
    replay_ids = {world.predictions[k].prediction_id for k in ("R1", "R2", "R3")}
    assert live.prediction_count == 18 and replay.prediction_count == 3
    assert live.lineage.cohort_digest == cohort_digest(world.preds(only=LIVE_SELECTED))
    assert replay.lineage.cohort_digest == cohort_digest(world.preds(only=("R1", "R2", "R3")))
    assert live.lineage.cohort_digest != replay.lineage.cohort_digest and live_ids.isdisjoint(replay_ids)
    # 同じ session_date が両 origin にあっても衝突せず、別の観測として残る
    assert world.predictions["L1"].session_date == world.predictions["R1"].session_date
    assert world.predictions["L1"].prediction_id != world.predictions["R1"].prediction_id
    assert replay.unique_session_count == 3 and coverage_tuple(replay.coverage) == (2, 0, 1, 0)
    assert (replay.directional_match.numerator, replay.directional_match.denominator) == (1, 2)
    assert replay.associated_evaluation_count == 2 and replay.foreign_evaluation_count == 26
    assert replay.abstention.abstained == 1 and replay.abstention.abstention_rate.as_dict()["denominator"] == 3
    # origin は date から推定されない・COMBINED report は存在しない
    assert live.cohort.origin is LIVE and replay.cohort.origin is REPLAY
    assert not any(hasattr(rep, name) for rep in (live, replay) for name in ("combined", "headline", "overall_origin"))
    assert "COMBINED" not in json.dumps(live.as_dict()) + json.dumps(replay.as_dict())
    with pytest.raises(Exception):
        CohortBoundary("LIVE", "2026-09-01", "2026-09-30")                                   # type: ignore[arg-type]


# ---------------------------------------------------------------- §5 five × three matrix

def test_e2e_matrix_cells_match_explicit_expectations(world: World) -> None:
    rep = analyze(world)
    for level, (up, rng, down) in EXPECTED_MATRIX.items():
        counts = rep.confusion_matrix.rows[level]
        assert (counts.up, counts.range, counts.down) == (up, rng, down), level
    d = rep.as_dict()["confusion_matrix"]
    assert sum(d["rows"][l.value][o] for l in LEVEL_ROWS for o in ("UP", "RANGE", "DOWN")) == 11
    assert d["total"] == 11 == rep.directional_match.denominator
    assert {l.value for l in LEVEL_ROWS if d["rows"][l.value]["total"] > 0} == {l.value for l in LEVEL_ROWS}  # 5 level 全部が出現
    # 一致件数 = 凍結写像で一致する cell の和（analyzer は写像を再実装していない）
    matching = sum(getattr(rep.confusion_matrix.rows[level], PREDICTION_DIRECTION_MAPPING[level].value.lower())
                   for level in LEVEL_ROWS)
    assert matching == 6 == rep.directional_match.numerator
    assert all(directional_exact_match(level, RealizedOutcome(PREDICTION_DIRECTION_MAPPING[level].value))
               for level in LEVEL_ROWS)
    # 行率は分母付き（UPWARD_LEAN: 4 件中 UP 2）
    assert d["rows"]["UPWARD_LEAN"]["row_frequencies"]["UP"] == {"numerator": 2, "denominator": 4, "value": "0.5",
                                                                  "disclosure": "INSUFFICIENT_SAMPLE"}


def test_e2e_level_and_confidence_group_expectations(world: World) -> None:
    rep = analyze(world)
    expect = {L.UPWARD_LEAN: (5, (4, 0, 0, 1), (2, 4)), L.SLIGHT_UPWARD_LEAN: (2, (1, 0, 1, 0), (1, 1)),
              L.NEUTRAL_RANGE: (3, (2, 0, 0, 1), (1, 2)), L.SLIGHT_DOWNWARD_LEAN: (1, (1, 0, 0, 0), (1, 1)),
              L.DOWNWARD_LEAN: (3, (3, 0, 0, 0), (1, 3))}
    for level, (n, cov, (num, den)) in expect.items():
        s = level_summary(rep, level)
        assert s.coverage.predictions == n and coverage_tuple(s.coverage) == cov, level
        assert (s.directional_match.numerator, s.directional_match.denominator) == (num, den), level
    for conf, (n, cov, (num, den)) in {"HIGH": (5, (5, 0, 0, 0), (2, 5)), "MEDIUM": (3, (2, 0, 0, 1), (1, 2)),
                                       "LOW": (6, (4, 0, 1, 1), (3, 4))}.items():
        s = confidence_summary(rep, conf)
        assert s.coverage.predictions == n and coverage_tuple(s.coverage) == cov, conf
        assert (s.directional_match.numerator, s.directional_match.denominator) == (num, den), conf
    # P4 が生成する 7 組だけが埋まり、残り 8 cell は 0 件のまま可視
    populated = {c.key for c in rep.level_confidence if c.coverage.predictions > 0}
    assert populated == {f"{level.value}|{conf}" for (_d, conf), level in LEVEL_BY_STATE.items()}
    assert len([c for c in rep.level_confidence if c.coverage.predictions == 0]) == 8
    assert cell(rep, L.UPWARD_LEAN, "HIGH").coverage.predictions == 3                          # L1, L10, L14
    assert cell(rep, L.UPWARD_LEAN, "HIGH").directional_match.as_dict()["numerator"] == 2      # L1, L14


# ---------------------------------------------------------------- §6 correction / supersession

def test_e2e_correction_changes_active_outcome_but_not_history_or_cohort(world: World) -> None:
    before = snapshot(world)
    r1 = analyze(world, without=("L10b",))                        # 訂正前: A（UP・一致）が active
    r2 = analyze(world)                                           # 訂正後: B（DOWN・不一致）が active
    a, b = world.evaluations["L10a"], world.evaluations["L10b"]
    assert b.supersedes_evaluation_id == a.evaluation_id and b.created_at < a.created_at   # 古い created_at でも訂正が active
    assert (r1.directional_match.numerator, r1.directional_match.denominator) == (7, 11)
    assert (r2.directional_match.numerator, r2.directional_match.denominator) == (6, 11)
    assert (r1.confusion_matrix.rows[L.UPWARD_LEAN].up, r1.confusion_matrix.rows[L.UPWARD_LEAN].down) == (3, 1)
    assert (r2.confusion_matrix.rows[L.UPWARD_LEAN].up, r2.confusion_matrix.rows[L.UPWARD_LEAN].down) == (2, 2)
    assert r1.overall.returns.mean != r2.overall.returns.mean and r1.overall.returns.n == r2.overall.returns.n == 11
    assert r1.lineage.cohort_digest == r2.lineage.cohort_digest
    assert r1.lineage.active_evaluation_digest != r2.lineage.active_evaluation_digest
    assert (r1.supplied_evaluation_count, r2.supplied_evaluation_count) == (27, 28)
    assert (r1.lineage.evaluation_record_count, r2.lineage.evaluation_record_count) == (27, 28)
    assert (r1.associated_evaluation_count, r2.associated_evaluation_count) == (22, 23)
    # source history: A は残り、predictions は不変、journal は存在しない（変更対象がない）
    assert a in world.evals() and snapshot(world) == before
    active = resolve_active_evaluation(world.predictions["L10"].prediction_id, world.evals())
    assert active.active == b and active.chain_ids == (a.evaluation_id, b.evaluation_id)


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_e2e_three_step_chain_activates_terminal_regardless_of_order(world: World, seed: int) -> None:
    a, b = world.evaluations["L10a"], world.evaluations["L10b"]
    c = ev(world.predictions["L10"], "0.02", supersedes=b.evaluation_id, created_at=NOW - timedelta(days=30))
    evals = world.evals(extra=[c])
    random.Random(seed).shuffle(evals)
    preds = world.preds()
    random.Random(seed + 100).shuffle(preds)
    rep = analyze_calibration(preds, evals, LIVE_COHORT)
    assert (rep.directional_match.numerator, rep.directional_match.denominator) == (7, 11)      # C = UP → 一致
    assert rep.confusion_matrix.rows[L.UPWARD_LEAN].up == 3
    active = resolve_active_evaluation(world.predictions["L10"].prediction_id, evals)
    assert active.active == c and active.chain_ids == (a.evaluation_id, b.evaluation_id, c.evaluation_id)
    assert c.created_at < b.created_at < a.created_at                                          # 最古の created_at が active
    assert rep.as_dict() == analyze(world, extra=[c]).as_dict()
    assert rep.lineage.active_evaluation_digest != analyze(world).lineage.active_evaluation_digest


# ---------------------------------------------------------------- §7 DEFERRED → EVALUATED

def test_e2e_deferred_then_evaluated_supersession(world: World) -> None:
    a, b = world.evaluations["L9a"], world.evaluations["L9b"]
    assert a.status is EvaluationStatus.DEFERRED and b.status is EvaluationStatus.EVALUATED
    assert b.supersedes_evaluation_id == a.evaluation_id
    before, after = analyze(world, without=("L9b",)), analyze(world)
    assert coverage_tuple(before.coverage) == (11, 2, 2, 3) and coverage_tuple(after.coverage) == (12, 1, 2, 3)
    assert before.directional_match.as_dict()["denominator"] == 10 and after.directional_match.denominator == 11
    assert before.directional_match.numerator == after.directional_match.numerator == 6              # L9 は不一致
    assert before.confusion_matrix.rows[L.DOWNWARD_LEAN].as_dict() == {"UP": 0, "RANGE": 1, "DOWN": 1, "total": 2}
    assert after.confusion_matrix.rows[L.DOWNWARD_LEAN].as_dict() == {"UP": 1, "RANGE": 1, "DOWN": 1, "total": 3}
    assert before.overall.returns.n == 10 and after.overall.returns.n == 11
    high_before, high_after = confidence_summary(before, "HIGH"), confidence_summary(after, "HIGH")
    assert coverage_tuple(high_before.coverage) == (4, 1, 0, 0) and coverage_tuple(high_after.coverage) == (5, 0, 0, 0)
    assert high_before.directional_match.denominator == 4 and high_after.directional_match.denominator == 5
    # DEFERRED の間は realized outcome が無い（RANGE にも wrong にもならない）
    deferred = resolve_active_evaluation(world.predictions["L9"].prediction_id, [a])
    assert deferred.coverage is EvaluationCoverage.ACTIVE_DEFERRED and deferred.realized_outcome is None
    assert a.realized_outcome is None and a.realized_return is None and a in world.evals()  # A は書き換えない
    assert before.lineage.cohort_digest == after.lineage.cohort_digest
    assert before.lineage.active_evaluation_digest != after.lineage.active_evaluation_digest


# ---------------------------------------------------------------- §8 unresolved

@pytest.mark.parametrize("seed", [0, 7, 42])
def test_e2e_fork_and_multiple_terminals_stay_unresolved(world: World, seed: int) -> None:
    evals = world.evals()
    random.Random(seed).shuffle(evals)
    rep = analyze_calibration(world.preds(), evals, LIVE_COHORT)
    fork = resolve_active_evaluation(world.predictions["L12"].prediction_id, evals)
    multi = resolve_active_evaluation(world.predictions["L13"].prediction_id, evals)
    assert fork.status is ResolutionStatus.FORK and fork.coverage is EvaluationCoverage.UNRESOLVED
    assert multi.status is ResolutionStatus.MULTIPLE_TERMINALS and multi.coverage is EvaluationCoverage.UNRESOLVED
    assert fork.active is None and multi.active is None and fork.realized_outcome is None
    assert set(fork.terminal_ids) == {world.evaluations["L12b"].evaluation_id, world.evaluations["L12c"].evaluation_id}
    assert set(multi.terminal_ids) == {world.evaluations["L13a"].evaluation_id, world.evaluations["L13b"].evaluation_id}
    assert rep.coverage.unresolved == 3 and dict(rep.coverage.unresolved_by_status) == {"FORK": 2, "MULTIPLE_TERMINALS": 1}
    assert rep.as_dict()["coverage"]["unresolved_by_status"] == {"MULTIPLE_TERMINALS": 1, "FORK": 2,
                                                                  "DANGLING_SUPERSESSION": 0, "SUBJECT_MISMATCH": 0,
                                                                  "DUPLICATE_ID": 0, "CYCLE": 0}
    # outcome / return / exact match に寄与しない（fork の枝 0.02 / -0.02、独立 terminal 0.001 / 0.002 は現れない）
    assert rep.overall.outcomes.total == 11 and rep.overall.returns.n == 11
    assert Decimal("0.002") not in {world.evaluations[ACTIVE_OF[k]].realized_return for k in ELIGIBLE}
    assert level_summary(rep, L.NEUTRAL_RANGE).directional_match.denominator == 2                 # L13 除外
    assert confidence_summary(rep, "MEDIUM").directional_match.denominator == 2                   # L12 除外
    # created_at（L12b 古い / L12c 新しい）でも物理順でも選ばれない
    assert world.evaluations["L12b"].created_at < world.evaluations["L12c"].created_at
    assert rep.as_dict() == analyze(world).as_dict()


# ---------------------------------------------------------------- §9 abstention

def test_e2e_abstention_diagnostics_and_available_only_confidence(world: World) -> None:
    rep = analyze(world)
    ab = rep.abstention
    assert (ab.total_predictions, ab.available, ab.abstained) == (18, 14, 4)
    assert ab.abstention_rate.as_dict() == {"numerator": 4, "denominator": 18,
                                            "value": "0.2222222222222222222222222222", "disclosure": "LIMITED_SAMPLE"}
    assert coverage_tuple(ab.coverage) == (1, 1, 1, 1) and dict(ab.coverage.unresolved_by_status) == {"FORK": 1}
    assert ab.outcome.outcomes.as_dict() == {"UP": 0, "RANGE": 0, "DOWN": 1, "total": 1}
    assert ab.outcome.returns.n == 1 and ab.outcome.returns.mean == Decimal("-0.01")
    assert ab.outcome.frequency(DOWN).as_dict()["numerator"] == 1
    # 棄権は方向 exact match の分母に入らない・RANGE / 正誤へ変換されない
    assert rep.directional_match.denominator == 11 and rep.confusion_matrix.total == 11
    assert rep.overall.outcomes.as_dict() == {"UP": 5, "RANGE": 2, "DOWN": 4, "total": 11}       # DOWN = L2, L6, L8, L10（A1 は含まない）
    # confidence を保持した棄権（A2 MEDIUM / A4 LOW）は confidence bucket に入らない
    assert world.predictions["A2"].confidence == "MEDIUM" and world.predictions["A4"].confidence == "LOW"
    assert confidence_summary(rep, "MEDIUM").coverage.predictions == 3                          # L2, L8, L12
    assert confidence_summary(rep, "LOW").coverage.predictions == 6                             # L3, L4, L5, L6, L11, L13
    assert sum(s.coverage.predictions for s in rep.confidence_summaries) == 14 == ab.available
    assert sum(c.coverage.predictions for c in rep.level_confidence) == 14
    assert confidence_summary(rep, "MEDIUM").coverage.active_deferred == 0                      # A2 の DEFERRED は入らない


# ---------------------------------------------------------------- §10 coverage partition

def test_e2e_coverage_partition_holds_everywhere(world: World) -> None:
    rep = analyze(world)
    groups = [("overall", rep.coverage), ("abstention", rep.abstention.coverage)]
    groups += [(s.key, s.coverage) for s in rep.level_summaries + rep.confidence_summaries + rep.level_confidence]
    for key, cov in groups:
        assert sum(coverage_tuple(cov)) == cov.predictions, key
        assert sum(cov.unresolved_by_status.values()) == cov.unresolved, key
    assert rep.coverage.predictions == rep.prediction_count == 18
    assert sum(s.coverage.predictions for s in rep.level_summaries) == 14
    assert sum(s.coverage.predictions for s in rep.confidence_summaries) == 14
    assert sum(s.coverage.predictions for s in rep.level_confidence) == 14
    assert 14 + rep.abstention.coverage.predictions == rep.prediction_count
    for bucket in range(4):
        assert (sum(coverage_tuple(s.coverage)[bucket] for s in rep.level_summaries)
                + coverage_tuple(rep.abstention.coverage)[bucket]) == coverage_tuple(rep.coverage)[bucket]
    # 各 rate の分母は凍結 Denominator の意味と数値で一致
    assert rep.coverage.completion_rate.as_dict()["denominator"] == 18
    assert METRIC_BY_NAME["evaluation_completion_rate"].denominator is Denominator.PREDICTIONS_IN_COHORT
    assert METRIC_BY_NAME["directional_exact_match_rate"].denominator is Denominator.AVAILABLE_WITH_ACTIVE_EVALUATED
    assert METRIC_BY_NAME["abstention_rate"].denominator is Denominator.TOTAL_PREDICTIONS


# ---------------------------------------------------------------- §11 sample disclosure boundaries

def disclosure_world(n: int) -> Tuple[List[PredictionRecord], List[EvaluationRecord], CohortBoundary]:
    wide = CohortBoundary(LIVE, "2026-08-01", "2026-09-30")
    preds, evals = [], []
    for i in range(n):
        session = date(2026, 9, 30) - timedelta(days=i)
        p = pred(session.isoformat(), (session - timedelta(days=1)).isoformat())
        preds.append(p)
        evals.append(ev(p, "0.01"))
    return preds, evals, wide


@pytest.mark.parametrize("n,label", [(0, "NO_DATA"), (1, "INSUFFICIENT_SAMPLE"), (9, "INSUFFICIENT_SAMPLE"),
                                     (10, "LIMITED_SAMPLE"), (29, "LIMITED_SAMPLE"), (30, "REPORTABLE")])
def test_e2e_sample_disclosure_boundaries_through_analyzer(n: int, label: str) -> None:
    preds, evals, cohort = disclosure_world(n)
    d = analyze_calibration(preds, evals, cohort).as_dict()
    assert d["directional_exact_match"] == {"numerator": n, "denominator": n, "value": None if n == 0 else "1",
                                            "disclosure": label}
    assert d["overall"]["outcome_frequencies"]["UP"]["disclosure"] == label
    assert d["overall"]["outcome_frequencies"]["UP"]["numerator"] == n and d["overall"]["returns"]["n"] == n
    assert d["overall"]["returns"]["disclosure"] == label
    row = d["confusion_matrix"]["rows"]["UPWARD_LEAN"]
    assert row["UP"] == n and row["row_frequencies"]["UP"]["disclosure"] == label
    assert d["level_summaries"][0]["directional_exact_match"]["denominator"] == n
    assert d["coverage"]["evaluation_completion_rate"] == {"numerator": n, "denominator": n,
                                                           "value": None if n == 0 else "1", "disclosure": label}
    text = json.dumps(d).lower()
    for token in ("significan", "p-value", "confidence interval", "p_value", "z-score", "skill"):
        assert token not in text, token


# ---------------------------------------------------------------- §12 empty cohort

def test_e2e_empty_cohort_is_valid_and_stable(world: World) -> None:
    rep = analyze(world, EMPTY_COHORT)                          # 予測は供給されるが 1 件も選ばれない
    d = rep.as_dict()
    assert d["prediction_count"] == 0 and d["unique_session_count"] == 0
    assert d["supplied_prediction_count"] == 23 and d["associated_evaluation_count"] == 0
    assert d["foreign_evaluation_count"] == 28 == d["supplied_evaluation_count"]
    assert coverage_tuple(rep.coverage) == (0, 0, 0, 0) and rep.coverage.predictions == 0
    assert (rep.abstention.total_predictions, rep.abstention.available, rep.abstention.abstained) == (0, 0, 0)
    assert d["directional_exact_match"] == {"numerator": 0, "denominator": 0, "value": None, "disclosure": "NO_DATA"}
    assert d["coverage"]["evaluation_completion_rate"]["value"] is None
    assert list(d["confusion_matrix"]["rows"]) == [l.value for l in LEVEL_ROWS] and d["confusion_matrix"]["total"] == 0
    assert d["confusion_matrix"]["columns"] == ["UP", "RANGE", "DOWN"]
    assert len(d["confidence_summaries"]) == 3 and len(d["level_confidence"]) == 15 and len(d["level_summaries"]) == 5
    assert d["overall"]["returns"]["n"] == 0 and d["overall"]["returns"]["mean"] is None
    assert d["versions"]["realized_classification"] == [] and d["unresolved_prediction_ids"] == []
    assert rep.lineage.cohort_digest == cohort_digest([]) and rep.lineage.active_evaluation_digest == active_evaluation_digest([])
    assert analyze(world, EMPTY_COHORT).as_dict() == d
    bare = analyze_calibration([], [], EMPTY_COHORT).as_dict()
    assert bare["lineage"]["cohort_digest"] == d["lineage"]["cohort_digest"]
    assert bare["lineage"]["active_evaluation_digest"] == d["lineage"]["active_evaluation_digest"]
    assert bare["lineage"]["prediction_record_count"] == 0 and analyze_calibration([], [], EMPTY_COHORT).as_dict() == bare


# ---------------------------------------------------------------- §13 duplicate input fail-closed

def test_e2e_duplicate_inputs_fail_closed_without_touching_inputs(world: World) -> None:
    before = snapshot(world)
    preds, evals = world.preds(), world.evals()
    p_same = world.predictions["L1"]
    p_equiv = PredictionRecord.from_dict(json.loads(json.dumps(p_same.as_dict())))      # 意味的に同一の別 object
    e_same = world.evaluations["L1"]
    e_equiv = EvaluationRecord.from_dict(json.loads(json.dumps(e_same.as_dict())))
    assert p_equiv == p_same and p_equiv is not p_same and e_equiv == e_same and e_equiv is not e_same
    for dup_preds, dup_evals in ((preds + [p_same], evals), (preds + [p_equiv], evals),
                                 (preds, evals + [e_same]), (preds, evals + [e_equiv]),
                                 ([p_same, p_same], []), ([], [e_same, e_same])):
        with pytest.raises(CalibrationInputError):
            analyze_calibration(dup_preds, dup_evals, LIVE_COHORT)
    assert len(preds) == 23 and len(evals) == 28 and snapshot(world) == before
    assert analyze(world).as_dict() == analyze_calibration(preds, evals, LIVE_COHORT).as_dict()


# ---------------------------------------------------------------- §14 foreign / out-of-cohort evaluations

def strip_source_counts(d: dict) -> dict:
    out = json.loads(json.dumps(d))
    for key in ("supplied_prediction_count", "supplied_evaluation_count", "foreign_evaluation_count"):
        out.pop(key)
    out["lineage"].pop("prediction_record_count")
    out["lineage"].pop("evaluation_record_count")
    return out


def test_e2e_foreign_evaluations_change_only_source_counts(world: World) -> None:
    full = analyze(world).as_dict()
    trimmed = analyze(world, without=FOREIGN).as_dict()
    assert full["supplied_evaluation_count"] == 28 and trimmed["supplied_evaluation_count"] == 23
    assert full["foreign_evaluation_count"] == 5 and trimmed["foreign_evaluation_count"] == 0
    assert full["associated_evaluation_count"] == trimmed["associated_evaluation_count"] == 23
    assert full["lineage"]["evaluation_record_count"] == 28 and trimmed["lineage"]["evaluation_record_count"] == 23
    assert strip_source_counts(full) == strip_source_counts(trimmed)
    assert full["lineage"]["cohort_digest"] == trimmed["lineage"]["cohort_digest"]
    assert full["lineage"]["active_evaluation_digest"] == trimmed["lineage"]["active_evaluation_digest"]
    # cohort 外の予測（REPLAY / 期間外）を供給しなくても metric は同じ。supplied 件数だけ変わる
    only_live = analyze_calibration(world.preds(only=LIVE_SELECTED), world.evals(), LIVE_COHORT).as_dict()
    assert only_live["supplied_prediction_count"] == 18 and only_live["lineage"]["prediction_record_count"] == 18
    assert only_live["foreign_evaluation_count"] == 5 and strip_source_counts(only_live) == strip_source_counts(full)
    # 各 foreign の種類: 期間外（前後）・別 origin・未知 prediction_id
    ids = {p.prediction_id for p in world.preds()}
    assert world.evaluations["X"].prediction_id not in ids
    assert not LIVE_COHORT.contains(world.predictions["O1"]) and not LIVE_COHORT.contains(world.predictions["O2"])
    assert not LIVE_COHORT.contains(world.predictions["R1"])


# ---------------------------------------------------------------- §15 determinism

@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5, 6, 7])
def test_e2e_shuffled_inputs_are_byte_identical(world: World, seed: int) -> None:
    baseline = json.dumps(analyze(world).as_dict())
    rng = random.Random(seed)
    preds, evals = world.preds(), world.evals()
    rng.shuffle(preds)
    rng.shuffle(evals)
    if seed % 2:
        preds.reverse()
    rep = analyze_calibration(preds, evals, LIVE_COHORT)
    assert json.dumps(rep.as_dict()) == baseline
    d = rep.as_dict()
    assert list(d["confusion_matrix"]["rows"]) == [l.value for l in LEVEL_ROWS]
    assert [s["key"] for s in d["level_summaries"]] == [l.value for l in LEVEL_ROWS]
    assert [s["key"] for s in d["confidence_summaries"]] == list(CONFIDENCE_BUCKETS)
    assert [s["key"] for s in d["level_confidence"]] == [f"{l.value}|{c}" for l in LEVEL_ROWS for c in CONFIDENCE_BUCKETS]
    assert d["unresolved_prediction_ids"] == sorted(d["unresolved_prediction_ids"])
    assert d["lineage"] == analyze(world).lineage.as_dict()


# ---------------------------------------------------------------- §16 serialization

def test_e2e_report_serialization_is_json_decimal_and_timestamp_free(world: World) -> None:
    d = analyze(world).as_dict()
    text = json.dumps(d)
    assert json.loads(text) == d
    numeric_keys = {"value", "mean", "median", "mean_abs", "min", "max"}
    for path, value in walk(d):
        assert not isinstance(value, float), path
        assert type(value) in (int, str, bool, type(None)), (path, type(value))
        if path[-1] in numeric_keys and value is not None:
            assert isinstance(value, str) and parse_canonical_decimal(value, str(path[-1])) == Decimal(value), path
        assert not (isinstance(value, str) and value.endswith("Z") and "T" in value and value[:4].isdigit()), path
    keys = {str(k) for path, _ in walk(d) for k in path if isinstance(k, str)}
    for forbidden in ("created_at", "generated_at", "recorded_at", "now", "timestamp", "analyzed_at"):
        assert forbidden not in keys, forbidden
    # 零 bucket・診断 status・版はすべて残る
    assert d["confusion_matrix"]["rows"]["SLIGHT_DOWNWARD_LEAN"]["UP"] == 0
    assert next(c for c in d["level_confidence"] if c["key"] == "NEUTRAL_RANGE|HIGH")["coverage"]["predictions"] == 0
    assert set(d["coverage"]["unresolved_by_status"]) == {s.value for s in ResolutionStatus
                                                          if s not in (ResolutionStatus.RESOLVED, ResolutionStatus.NO_EVALUATION)}
    assert set(d["versions"]) == {"calibration_report", "calibration_contract", "prediction_direction_mapping",
                                  "active_evaluation_resolver", "sample_disclosure", "realized_classification"}
    assert d["overall"]["returns"]["mean"] == "0.002909090909090909090909090909"                # 0.032 / 11
    assert not hasattr(CalibrationReport, "from_dict")                                           # P5-3B 通り追加しない


# ---------------------------------------------------------------- §17 input immutability

def test_e2e_source_records_are_never_mutated(world: World) -> None:
    before = snapshot(world)
    ids_before = [id(p) for p in world.predictions.values()] + [id(e) for e in world.evaluations.values()]
    preds, evals = world.preds(), world.evals()
    analyze(world)
    analyze(world)
    for seed in range(3):
        random.Random(seed).shuffle(preds)
        random.Random(seed).shuffle(evals)
        analyze_calibration(preds, evals, LIVE_COHORT)
    analyze(world, without=("L10b",))
    c = ev(world.predictions["L10"], "0.02", supersedes=world.evaluations["L10b"].evaluation_id)
    analyze(world, extra=[c])
    analyze(world, REPLAY_COHORT)
    analyze(world, EMPTY_COHORT)
    assert snapshot(world) == before
    assert [id(p) for p in world.predictions.values()] + [id(e) for e in world.evaluations.values()] == ids_before
    assert len(world.predictions) == 23 and len(world.evaluations) == 28
    with pytest.raises(dataclasses.FrozenInstanceError):
        world.predictions["L1"].session_date = "2026-01-01"                                       # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        world.evaluations["L1"].realized_return = Decimal("1")                                     # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        analyze(world).prediction_count = 0                                                        # type: ignore[misc]


def test_e2e_analysis_writes_nothing(tmp_path: Path, monkeypatch, world: World) -> None:         # §18 / §20
    monkeypatch.chdir(tmp_path)
    analyze(world)
    analyze(world, REPLAY_COHORT)
    analyze(world, without=("L10b",))
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- §18 dependency / read-only proof

def test_e2e_calibration_runtime_closure_is_journal_record_analytics_only() -> None:
    code = (
        "import sys\n"
        "import src.intelligence.predictions.calibration_analyzer\n"
        "import src.intelligence.predictions.calibration_contract\n"
        "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('src.intelligence'))))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True,
                          check=True, env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    closure = set(proc.stdout.split())
    assert closure == ALLOWED_CLOSURE and len(closure) == 14
    for forbidden in FORBIDDEN_MODULES:
        assert not any(forbidden in m for m in closure), forbidden
    for name in ("calibration_analyzer", "calibration_contract"):
        modules = imported_modules(PACKAGE / f"{name}.py")
        assert not any(any(f in m for f in FORBIDDEN_MODULES) for m in modules), (name, modules)
        src = executable_source(PACKAGE / f"{name}.py")
        for token in ("open(", "write_text", "write_bytes", "mkdir", "unlink", "rename(", "os.replace", "shutil",
                      "store.append", "Store(", "urllib", "socket", "requests", "http", "subprocess",
                      "environ", "getenv", "datetime.now", "date.today", "git"):
            assert token not in src, (name, token)
    assert "predictions" in EXCLUDED_PACKAGES and not any("predictions" in m for m in runtime_closure())
    offenders = [str(p.relative_to(REPO_ROOT))
                 for p in list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py"))
                 if p.parent != PACKAGE and "calibration_" in p.read_text(encoding="utf-8")]
    assert offenders == []
    # この E2E module 自身も store / engine / ingest / market / calendar を import しない
    own = imported_modules(Path(__file__))
    assert not any(any(f in m for f in ("prediction_store", "evaluation_store", "evaluation_engine",
                                        "prediction_ingest", "market.model", "tokyo_calendar")) for m in own), own


# ---------------------------------------------------------------- §19 P5-3A / P5-3B completion audit

def test_e2e_contract_analyzer_and_docs_agree(world: World) -> None:
    rep = analyze(world)
    lineage = rep.lineage.as_dict()
    assert lineage["calibration_contract_version"] == CALIBRATION_CONTRACT_VERSION == "calibration_contract:0.1.0"
    assert lineage["mapping_version"] == PREDICTION_DIRECTION_MAPPING_VERSION == "prediction_direction_mapping:1.0.0"
    assert lineage["resolver_version"] == ACTIVE_EVALUATION_RESOLVER_VERSION == "active_evaluation_resolver:1.0.0"
    assert lineage["sample_disclosure_version"] == SAMPLE_DISCLOSURE_VERSION == "sample_disclosure:1.0.0"
    assert rep.schema_version == "calibration_report:0.1.0"
    doc = CONTRACT_DOC.read_text(encoding="utf-8")
    for token in ("## 18.", "## 19.", "calibration_contract:0.1.0", "prediction_direction_mapping:1.0.0",
                  "active_evaluation_resolver:1.0.0", "sample_disclosure:1.0.0", "calibration_report:0.1.0",
                  "AVAILABLE 予測のみ", "FORK", "MULTIPLE_TERMINALS", "prediction_id", "CalibrationInputError"):
        assert token in doc, token
    # 写像は P4 LEVEL_BY_STATE の方向成分の逆射影（analyzer は写像を再実装しない）
    inverse = {level: direction for (direction, _c), level in LEVEL_BY_STATE.items()}
    expected = {"UPWARD_BIAS": PredictedDirection.UP, "RANGE_BOUND": PredictedDirection.RANGE,
                "DOWNWARD_BIAS": PredictedDirection.DOWN}
    assert {lvl: expected[d] for lvl, d in inverse.items()} == dict(PREDICTION_DIRECTION_MAPPING)
    # 分母定義と analyzer の数値が一致（独立に fixture から数える）
    available_active = [k for k in LIVE_SELECTED if world.predictions[k].available
                        and resolve_active_evaluation(world.predictions[k].prediction_id, world.evals()).coverage
                        is EvaluationCoverage.ACTIVE_EVALUATED]
    assert len(available_active) == rep.directional_match.denominator == 11
    abstained_n = sum(1 for k in LIVE_SELECTED if not world.predictions[k].available)
    assert abstained_n == rep.abstention.abstained == 4 and rep.abstention.abstention_rate.denominator == 18
    # Decimal 方針: prec 28 / ROUND_HALF_EVEN、float を権威にしない
    assert RATE_CONTEXT.prec == 28 and RATE_CONTEXT.rounding == "ROUND_HALF_EVEN"
    assert isinstance(rep.directional_match.value, Decimal) and isinstance(rep.overall.returns.mean, Decimal)
    # LIVE / REPLAY 分離・cohort 閉区間・棄権 / DEFERRED / unresolved 分離は上の各テストで証明済み。ここでは矛盾の不在
    assert "COMBINED" not in [c.name for c in PredictionOrigin]
    assert LIVE_COHORT.contains(world.predictions["L1"]) and not LIVE_COHORT.contains(world.predictions["R1"])
    assert rep.coverage.active_deferred + rep.coverage.unresolved + rep.coverage.no_evaluation == 18 - 12
