"""Phase 5 P5-2C — OFFLINE 評価 engine の凍結ガード。

gate §21 の 70 項目を、fixture の domain object（凍結 PredictionRecord・既存 `Observation`・
カレンダー行）だけで証明する。network・J-Quants・filesystem 探索・現在時刻は使わない。
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext, localcontext
from pathlib import Path

import pytest

from src.intelligence.core.types import SCHEMA_VERSION
from src.intelligence.market.model import Observation, ObservationKind
from src.intelligence.predictions import evaluation_engine as engine
from src.intelligence.predictions.evaluation_engine import (
    DEFER_PRECEDENCE,
    RETURN_CONTEXT,
    SUPPORTED_OBSERVATION_SCHEMA_VERSIONS,
    SUPPORTED_SOURCE_IDS,
    TARGET_SERIES_ID,
    CalendarEvidence,
    EvaluationInputError,
    evaluate_and_append,
    evaluate_prediction,
    select_session_evidence,
    verify_sessions,
)
from src.intelligence.predictions.evaluation_record import (
    NEUTRAL_BAND_RULE_VERSION,
    TARGET_TOPIX,
    DeferReason,
    EvaluationRecord,
    EvaluationStatus,
    RealizedOutcome,
    classify_realized_return,
)
from src.intelligence.predictions.evaluation_store import (
    EvaluationAppendStatus,
    EvaluationConflict,
    EvaluationStore,
    SupersessionRejected,
)
from src.intelligence.predictions.prediction_record import PredictionOrigin, make_prediction_record
from src.intelligence.reports.market_signal import SignalLevel
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "evaluation_engine.py"

CREATED_AT = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
AS_OF = datetime(2026, 9, 1, 6, 30, tzinfo=timezone.utc)
CALENDAR_SOURCE = "jquants:/v2/markets/calendar"
#: 2026-09-19/20 は週末、09-21 は祝日（敬老の日）— カレンダー証拠だけが gap を決める
CALENDAR_ROWS = tuple({"calendar_date": d, "holiday_division": h} for d, h in [
    ("2026-09-16", "1"), ("2026-09-17", "1"), ("2026-09-18", "1"), ("2026-09-19", "0"),
    ("2026-09-20", "0"), ("2026-09-21", "0"), ("2026-09-22", "1"), ("2026-09-23", "1"),
])
CALENDAR = CalendarEvidence(calendar_source_id=CALENDAR_SOURCE, rows=CALENDAR_ROWS)
REFERENCE, SESSION = "2026-09-18", "2026-09-22"
REF_CLOSE, TGT_CLOSE = Decimal("2700"), Decimal("2718.25")


# ---------------------------------------------------------------- fixtures

def obs(day: str, value, *, oid: str = "", source: str = "jquants", schema: str = SCHEMA_VERSION,
        **override) -> Observation:
    kwargs = dict(observation_id=oid or "obs_" + day.replace("-", "") + "a" * 16,
                  entity_id="index:topix", metric="close",
                  value=None if value is None else Decimal(value), unit="index", as_of=AS_OF,
                  kind=ObservationKind.RAW, source_id=source, series_id=TARGET_SERIES_ID,
                  trading_date=day, schema_version=schema)
    kwargs.update(override)
    return Observation(**kwargs)


def market(*days_and_values) -> list:
    return [obs(day, value) for day, value in (days_and_values or ((REFERENCE, "2700"), (SESSION, "2718.25")))]


def prediction(session: str = SESSION, reference: str = REFERENCE, **override):
    kwargs = dict(session_date=session, reference_session=reference, origin=PredictionOrigin.LIVE,
                  available=True, level=SignalLevel.UPWARD_LEAN, confidence="HIGH",
                  horizon="next_tokyo_session", unavailable_reason="", brief_id="brief_" + "a" * 24,
                  signal_id="sig_" + "b" * 24, morning_brief_schema_version="0.2.0",
                  market_signal_schema_version="0.1.0",
                  recorded_at=datetime(2026, 9, 22, 6, 30, tzinfo=timezone.utc))
    kwargs.update(override)
    return make_prediction_record(**kwargs)


def abstained_prediction():
    return prediction(available=False, level=None, confidence="", horizon="",
                      unavailable_reason="draft_abstained")


def evaluate(pred=None, calendar: CalendarEvidence = CALENDAR, evidence=None, **kw) -> EvaluationRecord:
    return evaluate_prediction(pred or prediction(), calendar, market() if evidence is None else evidence,
                               created_at=kw.pop("created_at", CREATED_AT), **kw)


def source() -> str:
    return executable_source(MODULE_PATH)


# ---------------------------------------------------------------- 1–10 evaluated / return / classification

def test_valid_prediction_calendar_and_closes_produce_evaluated() -> None:               # 1
    rec = evaluate()
    assert rec.status is EvaluationStatus.EVALUATED and not rec.is_deferred
    assert rec.realized_outcome is RealizedOutcome.UP and rec.defer_reason is None
    assert rec.reference_close == REF_CLOSE and rec.target_close == TGT_CLOSE
    assert rec.session_verification.validated


def test_exact_decimal_return_calculation() -> None:                                     # 2, 8, 10
    rec = evaluate()
    with localcontext(RETURN_CONTEXT):
        expected = TGT_CLOSE / REF_CLOSE - Decimal(1)
    assert rec.realized_return == expected == Decimal("0.006759259259259259259259259")
    assert isinstance(rec.realized_return, Decimal)
    assert RETURN_CONTEXT.prec == 28
    src = source()
    for token in ("float(", "round(", "quantize", "math.", "numpy"):
        assert token not in src, token


@pytest.mark.parametrize("target_close,outcome", [
    ("2708.11", RealizedOutcome.UP),        # 3  > +0.30%
    ("2708.1", RealizedOutcome.RANGE),      # 4  exactly +0.30%（2700 × 1.003）
    ("2700", RealizedOutcome.RANGE),        # 5  zero
    ("2691.9", RealizedOutcome.RANGE),      # 6  exactly -0.30%
    ("2691.89", RealizedOutcome.DOWN),      # 7  < -0.30%
])
def test_frozen_classification_boundaries(target_close: str, outcome: RealizedOutcome) -> None:
    rec = evaluate(evidence=[obs(REFERENCE, "2700"), obs(SESSION, target_close)])
    assert rec.realized_outcome is outcome
    assert rec.realized_outcome is classify_realized_return(rec.realized_return)


def test_no_rounding_before_classification_and_continuous_return_preserved() -> None:    # 9, 10
    rec = evaluate(evidence=[obs(REFERENCE, "2700"), obs(SESSION, "2708.1000001")])
    assert rec.realized_outcome is RealizedOutcome.UP                # 丸めていれば RANGE に見える
    assert rec.realized_return > Decimal("0.003")
    assert rec.as_dict()["realized_return"].startswith("0.00300000")
    assert "0.003" not in source() and "NEUTRAL_BAND" not in source()  # 閾値を持たない


# ---------------------------------------------------------------- 11–15 calendar contract

def test_verified_previous_session_is_required_and_derived_from_calendar() -> None:      # 11, 38
    rec = evaluate()
    proof = rec.session_verification
    assert proof.calendar_source_id == CALENDAR_SOURCE and proof.trading_divisions == ("1",)
    assert proof.verified_session == SESSION and proof.verified_previous_session == REFERENCE
    assert proof.checked_dates == 2 and proof.agreements == 2 and proof.disagreement_count == 0
    direct = verify_sessions(CALENDAR, session_date=SESSION, observed_trading_dates=[REFERENCE, SESSION])
    assert direct == proof


def test_weekend_and_holiday_gap_resolves_through_calendar_evidence() -> None:           # 12, 13
    assert (datetime(2026, 9, 22) - datetime(2026, 9, 18)).days == 4    # 金 → 火（週末 ＋ 祝日）
    rec = evaluate()
    assert rec.status is EvaluationStatus.EVALUATED
    src = source()
    for token in ("weekday", "timedelta", "isoweekday", "date.fromisoformat", "days=1", "monday", "friday"):
        assert token not in src.lower(), token


def test_calendar_unverified_defers(tmp_path: Path) -> None:                             # 14
    for calendar in (CalendarEvidence(CALENDAR_SOURCE, ()),                           # 行無し
                     CalendarEvidence("", CALENDAR_ROWS),                             # source 無し
                     CalendarEvidence(CALENDAR_SOURCE, CALENDAR_ROWS, trading_divisions=("9",))):
        rec = evaluate(calendar=calendar)
        assert rec.is_deferred and rec.defer_reason is DeferReason.CALENDAR_UNVERIFIED
        assert rec.session_verification is None or not rec.session_verification.validated
    contradicted = evaluate(evidence=market() + [obs("2026-09-21", "2705")])         # 祝日に観測 = 食い違い
    assert contradicted.defer_reason is DeferReason.CALENDAR_UNVERIFIED
    assert contradicted.session_verification.disagreement_count == 1


def test_wrong_previous_session_defers() -> None:                                        # 15
    holiday_reference = evaluate(prediction(reference="2026-09-21"),
                                 evidence=[obs("2026-09-21", "2705"), obs(SESSION, "2718.25")]
                                 if False else market())
    assert holiday_reference.defer_reason is DeferReason.REFERENCE_SESSION_UNVERIFIED
    skipped = evaluate(prediction(reference="2026-09-17"), evidence=[obs("2026-09-17", "2690"), obs(SESSION, "2718.25")])
    assert skipped.defer_reason is DeferReason.REFERENCE_SESSION_UNVERIFIED         # 2 session 跨ぎ
    assert skipped.session_verification.verified_previous_session == REFERENCE
    not_trading_day = evaluate(prediction(session="2026-09-21", reference=REFERENCE),
                               evidence=[obs(REFERENCE, "2700"), obs("2026-09-21", "2705")])
    assert not_trading_day.defer_reason is DeferReason.CALENDAR_UNVERIFIED          # 観測が区分と矛盾
    out_of_range = evaluate(prediction(session="2026-09-16", reference="2026-09-15"),
                            evidence=[obs("2026-09-15", "2680"), obs("2026-09-16", "2690")])
    assert out_of_range.defer_reason is DeferReason.REFERENCE_SESSION_UNVERIFIED    # 直前がカレンダー範囲外


# ---------------------------------------------------------------- 16–26 observation contract

def test_reference_close_missing_defers_and_keeps_target_evidence() -> None:             # 16
    rec = evaluate(evidence=[obs(SESSION, "2718.25")])
    assert rec.defer_reason is DeferReason.REFERENCE_CLOSE_UNAVAILABLE
    assert rec.reference_close is None and rec.reference_observation_id == ""
    assert rec.target_close == TGT_CLOSE and rec.target_observation_id and rec.source_id == "jquants"
    assert rec.session_verification.validated


def test_target_close_missing_defers_and_keeps_reference_evidence() -> None:             # 17
    rec = evaluate(evidence=[obs(REFERENCE, "2700")])
    assert rec.defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE
    assert rec.target_close is None and rec.target_observation_id == ""
    assert rec.reference_close == REF_CLOSE and rec.market_schema_version == SCHEMA_VERSION


@pytest.mark.parametrize("bad", [
    dict(value=None), dict(value="0"), dict(value="-1"), dict(entity_id="index:nikkei225"),
    dict(metric="open"), dict(unit="pct"), dict(valid_until=AS_OF),
])
def test_invalid_reference_or_target_observation_defers(bad: dict) -> None:            # 18, 19, 66
    ref_bad = evaluate(evidence=[obs(REFERENCE, "2700", **bad) if "value" not in bad
                                 else obs(REFERENCE, bad["value"], **{k: v for k, v in bad.items() if k != "value"}),
                                 obs(SESSION, "2718.25")])
    assert ref_bad.defer_reason is DeferReason.OBSERVATION_INVALID
    assert ref_bad.reference_close is None and ref_bad.target_close == TGT_CLOSE  # 有効な側は保持
    tgt_bad = evaluate(evidence=[obs(REFERENCE, "2700"),
                                 obs(SESSION, "2718.25", **bad) if "value" not in bad
                                 else obs(SESSION, bad["value"], **{k: v for k, v in bad.items() if k != "value"})])
    assert tgt_bad.defer_reason is DeferReason.OBSERVATION_INVALID
    assert tgt_bad.target_close is None and tgt_bad.reference_close == REF_CLOSE


@pytest.mark.parametrize("override", [dict(source="test"), dict(source="stooq"), dict(schema="0.3.0"),
                                      dict(schema="1.0.0")])
def test_unsupported_source_or_schema_defers_without_market_provenance(override: dict) -> None:  # 20, 68
    rec = evaluate(evidence=[obs(REFERENCE, "2700", **override), obs(SESSION, "2718.25")])
    assert rec.defer_reason is DeferReason.SOURCE_UNSUPPORTED
    assert rec.reference_close is None and rec.target_close is None and rec.source_id == ""
    assert SUPPORTED_SOURCE_IDS == ("jquants",)
    assert SUPPORTED_OBSERVATION_SCHEMA_VERSIONS == (SCHEMA_VERSION,)


def test_incoherent_source_between_sessions_defers() -> None:                            # 13 §13
    rec = evaluate(evidence=[obs(REFERENCE, "2700", source="jquants"), obs(SESSION, "2718.25", source="jquants",
                                                                          schema="0.3.0")])
    assert rec.defer_reason is DeferReason.SOURCE_UNSUPPORTED


def test_conflicting_duplicate_observation_defers_closed() -> None:                      # 21, 69
    dup = obs(SESSION, "2719", oid="obs_duplicate" + "b" * 11)
    rec = evaluate(evidence=market() + [dup])
    assert rec.defer_reason is DeferReason.OBSERVATION_INVALID
    assert rec.target_close is None and rec.reference_close == REF_CLOSE
    identical_value = obs(SESSION, "2718.25", oid="obs_duplicate" + "c" * 11)        # 同値でも曖昧
    assert evaluate(evidence=market() + [identical_value]).defer_reason is DeferReason.OBSERVATION_INVALID


def test_resolved_revision_uses_existing_authority_not_latest_wins() -> None:           # 14 §14
    original = obs(SESSION, "2718.25")
    revised = obs(SESSION, "2719", oid="obs_revision" + "d" * 12, revision_of=original.observation_id)
    rec = evaluate(evidence=[obs(REFERENCE, "2700"), original, revised])
    assert rec.status is EvaluationStatus.EVALUATED and rec.target_close == Decimal("2719")
    assert rec.target_observation_id == revised.observation_id
    src = source()
    assert "latest_revisions" in src and "latest_close" not in src and "max(" not in src


@pytest.mark.parametrize("evidence,reason", [
    ([obs("2026-09-17", "2690"), obs(SESSION, "2718.25")], DeferReason.REFERENCE_CLOSE_UNAVAILABLE),  # 22 nearest
    ([obs(REFERENCE, "2700"), obs("2026-09-23", "2720")], DeferReason.TARGET_CLOSE_UNAVAILABLE),      # 22 nearest after
    ([obs("2026-09-17", "2690"), obs("2026-09-23", "2720")], DeferReason.REFERENCE_CLOSE_UNAVAILABLE),
    ([obs(REFERENCE, "2700"), obs("2026-09-16", "2680")], DeferReason.TARGET_CLOSE_UNAVAILABLE),      # 23 forward fill
    ([obs(SESSION, "2718.25"), obs("2026-09-23", "2720")], DeferReason.REFERENCE_CLOSE_UNAVAILABLE),  # 24 backward fill
])
def test_no_nearest_date_forward_backward_fill_or_interpolation(evidence, reason) -> None:  # 22–26
    rec = evaluate(evidence=evidence)
    assert rec.is_deferred and rec.defer_reason is reason
    src = source()
    for token in ("ffill", "bfill", "interpolat", "nearest", "bisect", "latest_close", "<= session", ">= session"):
        assert token not in src, token


# ---------------------------------------------------------------- 27–29 prediction availability

def test_unavailable_prediction_with_complete_evidence_is_evaluated() -> None:           # 27, 49
    pred = abstained_prediction()
    assert pred.is_abstention
    rec = evaluate(pred)
    assert rec.status is EvaluationStatus.EVALUATED and rec.realized_outcome is RealizedOutcome.UP
    assert rec.prediction_id == pred.prediction_id


def test_available_neutral_range_prediction_is_evaluated_normally() -> None:            # 28
    pred = prediction(level=SignalLevel.NEUTRAL_RANGE, confidence="LOW")
    rec = evaluate(pred)
    assert rec.status is EvaluationStatus.EVALUATED and rec.realized_outcome is RealizedOutcome.UP


def test_prediction_state_does_not_affect_realized_outcome() -> None:                    # 29, 51
    variants = [prediction(), prediction(level=SignalLevel.DOWNWARD_LEAN),
                prediction(level=SignalLevel.NEUTRAL_RANGE, confidence="LOW"), abstained_prediction(),
                prediction(origin=PredictionOrigin.REPLAY)]
    outcomes = {(evaluate(p).realized_return, evaluate(p).realized_outcome) for p in variants}
    assert len(outcomes) == 1
    assert len({evaluate(p).evaluation_id for p in variants}) == 5     # prediction_id は identity
    src = source()
    for token in ("SignalLevel", "UPWARD_LEAN", "NEUTRAL_RANGE", ".level", ".confidence", ".available",
                  "is_abstention", "unavailable_reason"):
        assert token not in src, token


# ---------------------------------------------------------------- 30–40 provenance / purity

def test_explicit_created_at_required_and_copied_exactly() -> None:                      # 30, 32
    assert inspect.signature(evaluate_prediction).parameters["created_at"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        evaluate_prediction(prediction(), CALENDAR, market())            # type: ignore[call-arg]
    with pytest.raises(ValueError):
        evaluate(created_at=datetime(2026, 9, 23, 8, 0))                 # naive
    stamped = CREATED_AT + timedelta(days=40)
    assert evaluate(created_at=stamped).created_at == stamped


def test_no_datetime_now_or_hidden_time_dependency() -> None:                            # 31, 70
    src = source()
    for token in ("now(", "utcnow", "time.time", "date.today", "perf_counter", "random"):
        assert token not in src, token
    assert imported_modules(MODULE_PATH).isdisjoint({"time", "random", "os", "sys", "pathlib"})
    a = evaluate()
    b = evaluate()
    assert a == b and a.created_at == CREATED_AT


def test_prediction_id_sessions_closes_ids_and_provenance_copied_exactly() -> None:      # 33–37
    ref, tgt = obs(REFERENCE, "2700", oid="obs_" + "1" * 24), obs(SESSION, "2718.25", oid="obs_" + "2" * 24)
    pred = prediction()
    rec = evaluate(pred, evidence=[tgt, ref])
    assert rec.prediction_id == pred.prediction_id
    assert (rec.reference_session, rec.session_date) == (pred.reference_session, pred.session_date)
    assert (rec.reference_close, rec.target_close) == (ref.value, tgt.value)
    assert (rec.reference_observation_id, rec.target_observation_id) == (ref.observation_id, tgt.observation_id)
    assert (rec.source_id, rec.market_schema_version) == (ref.source_id, ref.schema_version) == ("jquants", SCHEMA_VERSION)


def test_classification_version_and_target_are_frozen() -> None:                        # 39, 40
    rec = evaluate()
    assert rec.classification_version == NEUTRAL_BAND_RULE_VERSION == "topix_neutral_band:1.0.0"
    assert rec.target == TARGET_TOPIX == TARGET_SERIES_ID == "index:topix.close.closing.tokyo"
    assert inspect.signature(evaluate_prediction).parameters.keys() == {
        "prediction", "calendar_evidence", "market_evidence", "created_at", "supersedes_evaluation_id"}
    nikkei = obs(SESSION, "45000", entity_id="index:nikkei225", series_id="index:nikkei225.close.closing.tokyo")
    rec = evaluate(evidence=[obs(REFERENCE, "2700"), nikkei])
    assert rec.defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE      # 別 index は候補にすらならない


# ---------------------------------------------------------------- 41–43 determinism

def test_same_input_same_output() -> None:                                               # 41
    assert evaluate() == evaluate()
    assert evaluate(evidence=[obs(SESSION, "2718.25")]) == evaluate(evidence=[obs(SESSION, "2718.25")])


def test_defer_precedence_is_frozen_and_deterministic() -> None:                         # 42
    assert DEFER_PRECEDENCE == (
        DeferReason.SOURCE_UNSUPPORTED, DeferReason.CALENDAR_UNVERIFIED,
        DeferReason.REFERENCE_SESSION_UNVERIFIED, DeferReason.OBSERVATION_INVALID,
        DeferReason.REFERENCE_CLOSE_UNAVAILABLE, DeferReason.TARGET_CLOSE_UNAVAILABLE)
    assert set(DEFER_PRECEDENCE) == set(DeferReason)
    # source 未対応 ＋ カレンダー無し ＋ target 欠落 → source_unsupported が勝つ
    rec = evaluate(calendar=CalendarEvidence(CALENDAR_SOURCE, ()), evidence=[obs(REFERENCE, "2700", source="test")])
    assert rec.defer_reason is DeferReason.SOURCE_UNSUPPORTED
    # カレンダー無し ＋ 無効観測 → calendar_unverified が勝つ
    rec = evaluate(calendar=CalendarEvidence(CALENDAR_SOURCE, ()), evidence=[obs(REFERENCE, None), obs(SESSION, "2718.25")])
    assert rec.defer_reason is DeferReason.CALENDAR_UNVERIFIED
    # 無効な reference ＋ target 欠落 → observation_invalid が勝つ
    rec = evaluate(evidence=[obs(REFERENCE, "0")])
    assert rec.defer_reason is DeferReason.OBSERVATION_INVALID
    # 観測ゼロ → カレンダーの実測検証が成立しない（calendar_unverified が真実）
    rec = evaluate(evidence=[])
    assert rec.defer_reason is DeferReason.CALENDAR_UNVERIFIED
    # 両方欠落（別日の観測でカレンダーは検証済み）→ reference が先
    rec = evaluate(evidence=[obs("2026-09-17", "2690"), obs("2026-09-23", "2720")])
    assert rec.defer_reason is DeferReason.REFERENCE_CLOSE_UNAVAILABLE


def test_evidence_ordering_cannot_change_the_result() -> None:                           # 43
    evidence = market() + [obs("2026-09-17", "2690"), obs("2026-09-23", "2720"),
                           obs(SESSION, "2719", oid="obs_rev" + "e" * 17, revision_of=market()[1].observation_id)]
    baseline = evaluate(evidence=evidence)
    rng = random.Random(7)
    for _ in range(10):
        shuffled = list(evidence)
        rng.shuffle(shuffled)
        assert evaluate(evidence=shuffled) == baseline
    rows = list(CALENDAR_ROWS)
    rng.shuffle(rows)
    assert evaluate(calendar=CalendarEvidence(CALENDAR_SOURCE, tuple(rows)), evidence=evidence) == baseline


# ---------------------------------------------------------------- 44–47 supersession / store

def test_optional_supersedes_id_is_passed_through_without_lookup() -> None:              # 44, 45
    original = evaluate()
    corrected = evaluate(evidence=[obs(REFERENCE, "2700"), obs(SESSION, "2719")],
                         supersedes_evaluation_id=original.evaluation_id)
    assert corrected.supersedes_evaluation_id == original.evaluation_id and corrected.is_correction
    assert corrected.evaluation_id != original.evaluation_id
    assert evaluate().supersedes_evaluation_id == ""
    src = source()
    scrubbed = src.replace("store.append(record)", "").replace("latest_revisions", "").replace(
        "resolve_topix_observations", "").replace("resolved", "")
    for token in ("iter_records", ".get(", "latest", "current", "resolve", "chain", "predecessor"):
        assert token not in scrubbed, token


def test_pure_evaluate_does_not_require_a_store() -> None:                               # 46
    params = inspect.signature(evaluate_prediction).parameters
    assert "store" not in params
    assert evaluate().status is EvaluationStatus.EVALUATED


def test_append_helper_uses_the_frozen_store(tmp_path: Path) -> None:                    # 47, §22
    store = EvaluationStore(tmp_path)
    record, result = evaluate_and_append(store, prediction(), CALENDAR, market(), created_at=CREATED_AT)
    assert result.status is EvaluationAppendStatus.APPENDED and store.get(record.evaluation_id) == record
    again, result2 = evaluate_and_append(store, prediction(), CALENDAR, market(), created_at=CREATED_AT)
    assert again == record and result2.status is EvaluationAppendStatus.ALREADY_PRESENT
    with pytest.raises(EvaluationConflict):
        evaluate_and_append(store, prediction(), CALENDAR, market(), created_at=CREATED_AT + timedelta(minutes=1))
    corrected, result3 = evaluate_and_append(store, prediction(), CALENDAR,
                                             [obs(REFERENCE, "2700"), obs(SESSION, "2719")],
                                             created_at=CREATED_AT, supersedes_evaluation_id=record.evaluation_id)
    assert result3.status is EvaluationAppendStatus.APPENDED and result3.line_number == 2
    with pytest.raises(SupersessionRejected):
        evaluate_and_append(store, prediction(), CALENDAR, market(), created_at=CREATED_AT,
                            supersedes_evaluation_id="eval_" + "0" * 24)
    with pytest.raises(EvaluationInputError):
        evaluate_and_append(object(), prediction(), CALENDAR, market(), created_at=CREATED_AT)  # type: ignore[arg-type]
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["evaluations.jsonl"]


# ---------------------------------------------------------------- 48–52 semantics boundaries

def test_deferred_is_not_range() -> None:                                                # 48
    rec = evaluate(evidence=[obs(REFERENCE, "2700")])
    assert rec.is_deferred and rec.realized_outcome is None and rec.realized_return is None


def test_no_hit_miss_accuracy_or_scoring() -> None:                                      # 50, 52
    src = source()
    for token in ("hit", "miss", "correct", "accuracy", "score", "win", "loss", "calibration", "brier",
                  "ranking", "recommend"):
        assert token not in src, token
    assert "prediction.level" not in src and "prediction.available" not in src


# ---------------------------------------------------------------- 53–59 purity / isolation

def test_no_network_jquants_environment_filesystem_or_git() -> None:                     # 53–57
    src = source()
    for token in ("urllib", "requests", "http", "socket", "jquants_v2", "JQuants", "environ", "getenv",
                  "open(", "Path(", "glob", "listdir", "read_text", "data_root", "subprocess", " git"):
        assert token not in src, token
    allowed = {"__future__", "dataclasses", "datetime", "decimal", "typing", "..core.time", "..core.types",
               "..market.model", "..market.tokyo_calendar", ".evaluation_record", ".evaluation_store",
               ".prediction_record"}
    assert imported_modules(MODULE_PATH) <= allowed


def test_no_public_or_runtime_integration_and_p4_cannot_reach_the_engine() -> None:       # 58, 59
    assert "predictions" in EXCLUDED_PACKAGES
    assert not any("predictions" in m for m in runtime_closure())
    offenders = [str(p.relative_to(REPO_ROOT))
                 for p in list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py"))
                 if p.parent != MODULE_PATH.parent and "evaluation_engine" in p.read_text(encoding="utf-8")]
    assert offenders == []
    src = source()
    for token in ("delivery", "pages", "render", "notification", "argparse", "__main__", "MorningBrief",
                  "MarketSignal", "CompassDraft", "compass", "reports."):
        assert token not in src, token


def test_engine_is_downstream_only_of_frozen_records() -> None:                          # 20 §20
    engine_imports = imported_modules(MODULE_PATH)
    for upstream in ("prediction_record.py", "prediction_store.py", "prediction_ingest.py",
                     "evaluation_record.py", "evaluation_store.py"):
        text = (MODULE_PATH.parent / upstream).read_text(encoding="utf-8")
        assert "evaluation_engine" not in text
    for p4 in ("reports", "compass", "context", "market"):
        for path in (REPO_ROOT / "src" / "intelligence" / p4).rglob("*.py"):
            assert "evaluation_engine" not in path.read_text(encoding="utf-8"), path
    assert ".prediction_record" in engine_imports


# ---------------------------------------------------------------- 60–63 frozen components / source objects

def test_frozen_records_stores_and_source_objects_unchanged() -> None:                   # 60–63
    pred = prediction()
    evidence = market()
    before = (pred.as_dict(), [json.dumps(o.value.as_tuple(), default=str) + o.observation_id for o in evidence],
              [dict(r) for r in CALENDAR_ROWS])
    evaluate(pred, evidence=evidence)
    evaluate(pred, evidence=evidence, supersedes_evaluation_id="")
    after = (pred.as_dict(), [json.dumps(o.value.as_tuple(), default=str) + o.observation_id for o in evidence],
             [dict(r) for r in CALENDAR_ROWS])
    assert before == after
    with pytest.raises(dataclasses.FrozenInstanceError):
        pred.session_date = "2026-01-01"                                # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        evidence[0].value = Decimal("1")                                # type: ignore[misc]
    src = source()
    for token in ("setattr", "__dict__", "replace(", "PredictionRecord(", "EvaluationRecord(", "Observation("):
        assert token not in src, token


# ---------------------------------------------------------------- 64–69 contradictions

def test_contradictory_session_evidence_defers_closed() -> None:                         # 64
    misdated = obs(SESSION, "2718.25", trading_date="2026-09-23")      # 目標 session の観測が別日付
    rec = evaluate(evidence=[obs(REFERENCE, "2700"), misdated])
    assert rec.defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE
    other_previous = tuple({"calendar_date": d, "holiday_division": h} for d, h in [
        ("2026-09-18", "1"), ("2026-09-19", "0"), ("2026-09-20", "0"), ("2026-09-21", "1"), ("2026-09-22", "1")])
    rec = evaluate(calendar=CalendarEvidence(CALENDAR_SOURCE, other_previous))
    assert rec.defer_reason is DeferReason.REFERENCE_SESSION_UNVERIFIED  # カレンダーは 09-21 を直前と言う
    assert rec.session_verification.verified_previous_session == "2026-09-21"


def test_contradictory_target_evidence_defers_closed() -> None:                          # 65
    wrong_series = obs(SESSION, "2718.25", series_id="index:topix.close.closing.osaka")
    assert evaluate(evidence=[obs(REFERENCE, "2700"), wrong_series]).defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE
    derived = obs(SESSION, "0.67", kind=ObservationKind.DERIVED, calculation_method="return_1d:1.0.0",
                  inputs=("obs_x",), source_id="")
    assert evaluate(evidence=[obs(REFERENCE, "2700"), derived]).defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE
    mislabelled = obs(SESSION, "2718.25", metric="open")
    assert evaluate(evidence=[obs(REFERENCE, "2700"), mislabelled]).defer_reason is DeferReason.OBSERVATION_INVALID


def test_nan_and_infinity_observations_are_deferred_not_evaluated() -> None:            # 67
    for bad in ("NaN", "Infinity", "-Infinity"):
        rec = evaluate(evidence=[obs(REFERENCE, "2700"), obs(SESSION, bad)])
        assert rec.defer_reason is DeferReason.OBSERVATION_INVALID and rec.target_close is None


def test_input_type_errors_fail_closed_rather_than_defer() -> None:
    with pytest.raises(EvaluationInputError):
        evaluate_prediction(prediction().as_dict(), CALENDAR, market(), created_at=CREATED_AT)  # type: ignore[arg-type]
    with pytest.raises(EvaluationInputError):
        evaluate_prediction(prediction(), CALENDAR_ROWS, market(), created_at=CREATED_AT)  # type: ignore[arg-type]
    with pytest.raises(EvaluationInputError):
        evaluate_prediction(prediction(), CALENDAR, [market()[0].as_dict() if hasattr(market()[0], "as_dict") else {}],
                            created_at=CREATED_AT)  # type: ignore[list-item]
    with pytest.raises(EvaluationInputError):
        evaluate(supersedes_evaluation_id=None)                       # type: ignore[arg-type]
    with pytest.raises(EvaluationInputError):
        CalendarEvidence(CALENDAR_SOURCE, CALENDAR_ROWS, trading_divisions=())
    with pytest.raises(EvaluationInputError):
        select_session_evidence([object()], (SESSION,))               # type: ignore[list-item]


def test_return_arithmetic_is_independent_of_the_ambient_decimal_context() -> None:
    baseline = evaluate()
    previous = getcontext().prec
    try:
        getcontext().prec = 6
        assert evaluate() == baseline
    finally:
        getcontext().prec = previous
    assert baseline.realized_return == Decimal("0.006759259259259259259259259")
