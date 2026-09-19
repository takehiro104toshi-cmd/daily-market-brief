"""Phase 5 P5-2D — Evaluation の end-to-end OFFLINE 検証（P5-2 最終 gate）。

凍結 PredictionRecord → 検証済み東京カレンダー証拠 → TOPIX Observation → evaluation_engine →
EvaluationRecord → EvaluationStore → evaluations.jsonl → process 再起動 → 権威 reload →
元と同一の不変 EvaluationRecord、を 1 つの系として証明する。市場 outcome の検証だけを行い、
予測の正誤・較正・5 level → 3 state の写像は扱わない。

- 入力は P5-2C と同じ fixture（凍結 builder の PredictionRecord・既存 `Observation`・カレンダー行）
- 書き込みは `tmp_path` 隔離 root のみ。predictions.jsonl は開かず、network も使わない
"""
from __future__ import annotations

import dataclasses
import json
import random
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import List, Tuple

import pytest

from src.intelligence.core.types import SCHEMA_VERSION
from src.intelligence.predictions.evaluation_engine import (
    DEFER_PRECEDENCE,
    RETURN_CONTEXT,
    SUPPORTED_OBSERVATION_SCHEMA_VERSIONS,
    SUPPORTED_SOURCE_IDS,
    TARGET_SERIES_ID,
    CalendarEvidence,
    evaluate_and_append,
    evaluate_prediction,
)
from src.intelligence.predictions.evaluation_record import (
    IDENTITY_KEYS,
    NEUTRAL_BAND_RULE_VERSION,
    TARGET_TOPIX,
    DeferReason,
    EvaluationRecord,
    EvaluationStatus,
    RealizedOutcome,
    classify_realized_return,
)
from src.intelligence.predictions.evaluation_store import (
    SINGLE_WRITER_ONLY,
    SUPERSESSION_SUBJECT_FIELDS,
    ConcurrentModificationDetected,
    EvaluationAppendStatus,
    EvaluationConflict,
    EvaluationJournalCorrupt,
    EvaluationStore,
    serialize_evaluation,
)
from src.intelligence.predictions.prediction_record import PredictionOrigin, PredictionRecord
from src.intelligence.reports.market_signal import SignalLevel
from tests.intelligence.test_evaluation_engine import (
    CALENDAR,
    CALENDAR_ROWS,
    CALENDAR_SOURCE,
    CREATED_AT,
    REFERENCE,
    SESSION,
    abstained_prediction,
    market,
    obs,
    prediction,
)
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "intelligence" / "predictions"
LATER = CREATED_AT + timedelta(days=1)

#: P5-2 三 module（＋凍結 PredictionRecord）を import したときに読み込まれてよい module
ALLOWED_CLOSURE = {
    "src.intelligence", "src.intelligence.compass", "src.intelligence.compass.model",
    "src.intelligence.core", "src.intelligence.core.ids", "src.intelligence.core.time",
    "src.intelligence.core.types", "src.intelligence.market", "src.intelligence.market.model",
    "src.intelligence.market.tokyo_calendar", "src.intelligence.predictions",
    "src.intelligence.predictions.evaluation_engine", "src.intelligence.predictions.evaluation_record",
    "src.intelligence.predictions.evaluation_store", "src.intelligence.predictions.prediction_record",
    "src.intelligence.reports", "src.intelligence.reports.market_signal", "src.intelligence.reports.model",
}


# ---------------------------------------------------------------- helpers

def journal(root: Path) -> Path:
    return root / "predictions" / "evaluations.jsonl"


def physical_lines(root: Path) -> list:
    raw = journal(root).read_bytes()
    assert raw.endswith(b"\n")
    return raw.split(b"\n")[:-1]


def fresh_reload(root: Path) -> EvaluationStore:
    """process 再起動相当: 既存 instance を捨て、evaluations.jsonl だけから index を再構築する。"""
    return EvaluationStore(root)


def run(store: EvaluationStore, pred: PredictionRecord = None, evidence=None, *, calendar=CALENDAR,
        created_at=CREATED_AT, supersedes: str = ""):
    return evaluate_and_append(store, pred or prediction(), calendar,
                               market() if evidence is None else evidence,
                               created_at=created_at, supersedes_evaluation_id=supersedes)


def canonical_line(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


# ---------------------------------------------------------------- §4 happy path（A–Q を 1 本で）

def test_happy_path_end_to_end(tmp_path: Path) -> None:
    root = tmp_path / "root"
    pred = prediction()                                                    # A
    assert pred.reference_session == REFERENCE and pred.session_date == SESSION
    calendar = CALENDAR                                                    # B（09-18 → 週末＋祝日 → 09-22）
    evidence = market()                                                    # C
    store = EvaluationStore(root)
    record, result = run(store, pred, evidence, calendar=calendar)         # D
    assert record.status is EvaluationStatus.EVALUATED                     # E
    assert result.status is EvaluationAppendStatus.APPENDED and result.wrote_line
    with localcontext(RETURN_CONTEXT):                                     # F
        expected = Decimal("2718.25") / Decimal("2700") - Decimal(1)
    assert record.realized_return == expected == Decimal("0.006759259259259259259259259")
    assert record.realized_outcome is classify_realized_return(expected) is RealizedOutcome.UP  # G
    assert record.session_verification.verified_previous_session == REFERENCE
    assert len(physical_lines(root)) == 1                                  # H
    stored_bytes = journal(root).read_bytes()
    assert stored_bytes == serialize_evaluation(record).encode("utf-8")

    del store                                                              # I
    reopened = fresh_reload(root)                                          # J / K
    assert len(reopened) == 1
    reloaded = reopened.get(record.evaluation_id)
    assert reloaded == record                                              # L
    assert reloaded.evaluation_id == record.evaluation_id                  # M
    assert reloaded.as_dict() == record.as_dict()                          # N
    assert (reloaded.reference_observation_id, reloaded.target_observation_id) == \
        (evidence[0].observation_id, evidence[1].observation_id)
    assert reloaded.source_id == "jquants" and reloaded.market_schema_version == SCHEMA_VERSION
    assert reloaded.created_at == CREATED_AT and reloaded.prediction_id == pred.prediction_id

    again, second = run(reopened, pred, evidence, calendar=calendar)       # O
    assert second.status is EvaluationAppendStatus.ALREADY_PRESENT and not second.wrote_line  # P
    assert again == record
    assert journal(root).read_bytes() == stored_bytes                      # Q


# ---------------------------------------------------------------- §5 outcome state coverage

@pytest.mark.parametrize("target_close,outcome", [
    ("2718.25", RealizedOutcome.UP),
    ("2708.11", RealizedOutcome.UP),        # +0.30% のすぐ外
    ("2708.1", RealizedOutcome.RANGE),      # +0.30% 境界
    ("2708.09", RealizedOutcome.RANGE),     # +0.30% のすぐ内
    ("2700", RealizedOutcome.RANGE),        # 零
    ("2691.91", RealizedOutcome.RANGE),     # -0.30% のすぐ内
    ("2691.9", RealizedOutcome.RANGE),      # -0.30% 境界
    ("2691.89", RealizedOutcome.DOWN),      # -0.30% のすぐ外
    ("2650", RealizedOutcome.DOWN),
])
def test_outcome_states_survive_engine_record_jsonl_and_reload(tmp_path: Path, target_close: str,
                                                                outcome: RealizedOutcome) -> None:
    evidence = [obs(REFERENCE, "2700"), obs(SESSION, target_close)]
    record, _ = run(EvaluationStore(tmp_path), evidence=evidence)
    assert record.realized_outcome is outcome
    reloaded = fresh_reload(tmp_path).get(record.evaluation_id)
    assert reloaded == record
    assert reloaded.realized_return == record.realized_return               # 連続値が drift しない
    assert reloaded.as_dict()["realized_return"] == record.as_dict()["realized_return"]
    assert reloaded.realized_outcome is outcome is classify_realized_return(reloaded.realized_return)
    with localcontext(RETURN_CONTEXT):
        assert reloaded.realized_return == Decimal(target_close) / Decimal("2700") - Decimal(1)


# ---------------------------------------------------------------- §6 prediction state independence

def test_prediction_state_does_not_change_the_realized_outcome(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    predictions = [prediction(),                                           # available 方向
                   prediction(level=SignalLevel.NEUTRAL_RANGE, confidence="LOW"),  # available NEUTRAL_RANGE
                   abstained_prediction()]                                 # unavailable / 棄権
    assert predictions[2].is_abstention
    records = [run(store, p)[0] for p in predictions]
    assert all(r.status is EvaluationStatus.EVALUATED for r in records)
    assert len({(r.realized_return, r.realized_outcome) for r in records}) == 1
    assert len({r.evaluation_id for r in records}) == 3                    # prediction_id が identity
    reopened = fresh_reload(tmp_path)
    for p, r in zip(predictions, records):
        assert reopened.get(r.evaluation_id) == r and r.prediction_id == p.prediction_id
    keys = set(json.loads(physical_lines(tmp_path)[0]))
    assert keys.isdisjoint({"level", "confidence", "available", "hit", "correct", "score", "accuracy"})


# ---------------------------------------------------------------- §7 calendar / holiday proof

def test_holiday_gap_is_evaluated_only_through_calendar_evidence(tmp_path: Path) -> None:
    assert (REFERENCE, SESSION) == ("2026-09-18", "2026-09-22")            # 金 → 火（週末 ＋ 祝日 09-21）
    divisions = {r["calendar_date"]: r["holiday_division"] for r in CALENDAR_ROWS}
    assert divisions["2026-09-19"] == divisions["2026-09-20"] == divisions["2026-09-21"] == "0"
    record, _ = run(EvaluationStore(tmp_path))
    assert record.status is EvaluationStatus.EVALUATED
    proof = fresh_reload(tmp_path).get(record.evaluation_id).session_verification
    assert proof.verified_session == SESSION and proof.verified_previous_session == REFERENCE
    assert proof.calendar_source_id == CALENDAR_SOURCE and proof.validated
    engine_src = executable_source(PACKAGE / "evaluation_engine.py")   # docstring を除いた実行内容
    for token in ("weekday", "timedelta", "isoweekday", "business_day"):
        assert token not in engine_src.lower(), token


def test_unverified_calendar_and_wrong_previous_session_defer_and_journal(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    unverified, r1 = run(store, calendar=CalendarEvidence(CALENDAR_SOURCE, ()))
    assert unverified.defer_reason is DeferReason.CALENDAR_UNVERIFIED and r1.wrote_line
    wrong_previous, r2 = run(store, prediction(reference="2026-09-17"),
                             [obs("2026-09-17", "2690"), obs(SESSION, "2718.25")])
    assert wrong_previous.defer_reason is DeferReason.REFERENCE_SESSION_UNVERIFIED and r2.wrote_line
    assert wrong_previous.session_verification.verified_previous_session == REFERENCE
    reopened = fresh_reload(tmp_path)
    assert [r.defer_reason for r in reopened.iter_records()] == [DeferReason.CALENDAR_UNVERIFIED,
                                                                 DeferReason.REFERENCE_SESSION_UNVERIFIED]
    assert all(r.is_deferred and r.realized_outcome is None for r in reopened.iter_records())


# ---------------------------------------------------------------- §8 missing / invalid market evidence

@pytest.mark.parametrize("evidence,reason", [
    ([obs(SESSION, "2718.25")], DeferReason.REFERENCE_CLOSE_UNAVAILABLE),
    ([obs(REFERENCE, "2700")], DeferReason.TARGET_CLOSE_UNAVAILABLE),
    ([obs(REFERENCE, "2700"), obs(SESSION, None)], DeferReason.OBSERVATION_INVALID),
    ([obs(REFERENCE, "2700"), obs(SESSION, "2718.25", source="test")], DeferReason.SOURCE_UNSUPPORTED),
])
def test_deferred_records_are_journaled_and_survive_reload(tmp_path: Path, evidence, reason) -> None:
    record, result = run(EvaluationStore(tmp_path), evidence=evidence)
    assert record.is_deferred and record.defer_reason is reason and result.wrote_line
    assert record.realized_outcome is None and record.realized_return is None   # DEFERRED ≠ RANGE
    reopened = fresh_reload(tmp_path)
    assert len(reopened) == 1                                             # coverage から消えない
    reloaded = reopened.get(record.evaluation_id)
    assert reloaded == record and reloaded.defer_reason is reason
    assert reloaded.session_verification == record.session_verification
    assert reloaded.reference_close == record.reference_close and reloaded.target_close == record.target_close


# ---------------------------------------------------------------- §9 defer precedence E2E

def test_frozen_defer_precedence_is_order_independent_and_survives_reload(tmp_path: Path) -> None:
    #  reference 観測は未対応 source、target 観測は無効値、カレンダーは検証不能 → source_unsupported が勝つ
    evidence = [obs(REFERENCE, "2700", source="test"), obs(SESSION, None), obs("2026-09-17", "2690")]
    calendar = CalendarEvidence(CALENDAR_SOURCE, ())
    rng = random.Random(11)
    reasons = set()
    for _ in range(8):
        shuffled = list(evidence)
        rng.shuffle(shuffled)
        reasons.add(evaluate_prediction(prediction(), calendar, shuffled, created_at=CREATED_AT).defer_reason)
    assert reasons == {DEFER_PRECEDENCE[0]} == {DeferReason.SOURCE_UNSUPPORTED}
    record, _ = run(EvaluationStore(tmp_path), evidence=evidence, calendar=calendar)
    assert fresh_reload(tmp_path).get(record.evaluation_id).defer_reason is DeferReason.SOURCE_UNSUPPORTED
    #  同じ入力からカレンダー問題だけを残す → calendar_unverified、reload 後も同じ
    calendar_only = [obs(REFERENCE, "2700"), obs(SESSION, None)]
    record2, _ = run(EvaluationStore(tmp_path / "b"), evidence=calendar_only, calendar=calendar)
    assert record2.defer_reason is DeferReason.CALENDAR_UNVERIFIED
    assert fresh_reload(tmp_path / "b").get(record2.evaluation_id).defer_reason is DeferReason.CALENDAR_UNVERIFIED
    assert set(DEFER_PRECEDENCE) == set(DeferReason) and len(DEFER_PRECEDENCE) == len(DeferReason)


# ---------------------------------------------------------------- §10 multi-record journal

def multi_record_journal(root: Path) -> Tuple[EvaluationStore, List[EvaluationRecord]]:
    store = EvaluationStore(root)
    records = []
    add = lambda *a, **k: records.append(run(store, *a, **k)[0])          # noqa: E731
    add(prediction("2026-09-17", "2026-09-16"), [obs("2026-09-16", "2680"), obs("2026-09-17", "2690")])
    add(prediction("2026-09-18", "2026-09-17"), [obs("2026-09-17", "2690")])          # DEFERRED
    add(prediction(), market())                                                       # EVALUATED
    add(prediction(origin=PredictionOrigin.REPLAY), market())                          # 別 prediction_id
    add(abstained_prediction(), market())
    add(prediction(), [obs(REFERENCE, "2700"), obs(SESSION, "2719")],
        supersedes=records[2].evaluation_id, created_at=LATER)                        # 訂正 chain
    return store, records


def test_multi_record_journal_survives_restart_in_physical_order(tmp_path: Path) -> None:
    store, records = multi_record_journal(tmp_path)
    assert [r.status for r in records].count(EvaluationStatus.DEFERRED) == 1
    assert len({r.prediction_id for r in records}) == 5 and len({r.session_date for r in records}) == 3
    assert len({r.evaluation_id for r in records}) == 6
    del store
    reopened = fresh_reload(tmp_path)
    assert len(reopened) == 6 and list(reopened.iter_records()) == records
    for r in records:
        assert reopened.get(r.evaluation_id) == r
    assert physical_lines(tmp_path) == [serialize_evaluation(r).encode().rstrip(b"\n") for r in records]
    same_session = [r for r in reopened.iter_records() if r.session_date == SESSION]
    assert len(same_session) == 4                                        # date / prediction overwrite なし
    assert reopened.get(records[2].evaluation_id) == records[2]          # 旧評価は残る
    assert reopened.get(records[5].evaluation_id).supersedes_evaluation_id == records[2].evaluation_id


# ---------------------------------------------------------------- §11 idempotency E2E

def test_idempotency_through_the_full_evaluation_boundary(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    first, r1 = run(store)
    after_first = journal(tmp_path).read_bytes()
    second, r2 = run(store)
    assert r1.status is EvaluationAppendStatus.APPENDED and r2.status is EvaluationAppendStatus.ALREADY_PRESENT
    assert second == first and journal(tmp_path).read_bytes() == after_first
    del store
    third, r3 = run(fresh_reload(tmp_path))                                # 再構築後も同じ判定
    assert r3.status is EvaluationAppendStatus.ALREADY_PRESENT and third == first
    assert journal(tmp_path).read_bytes() == after_first and len(physical_lines(tmp_path)) == 1


# ---------------------------------------------------------------- §12 provenance / audit conflict E2E

@pytest.mark.parametrize("label,variant,expected", [
    ("created_at", dict(created_at=CREATED_AT + timedelta(minutes=1)), {"created_at"}),
    ("observation id (provenance only)", dict(evidence=[obs(REFERENCE, "2700"),
                                                          obs(SESSION, "2718.25", oid="obs_" + "9" * 24)]),
     {"target_observation_id"}),
])
def test_conflict_through_the_evaluation_boundary(tmp_path: Path, label: str, variant: dict,
                                                  expected: set) -> None:
    store = EvaluationStore(tmp_path)
    original, _ = run(store)
    stored = journal(tmp_path).read_bytes()
    with pytest.raises(EvaluationConflict) as info:
        run(store, **variant)
    assert info.value.evaluation_id == original.evaluation_id
    assert set(info.value.differing_fields) == expected
    assert journal(tmp_path).read_bytes() == stored                       # bytes / 元の行 不変
    reopened = fresh_reload(tmp_path)
    assert len(reopened) == 1 and reopened.get(original.evaluation_id) == original
    with pytest.raises(EvaluationConflict):
        run(reopened, **variant)


# ---------------------------------------------------------------- §13 correction / supersession E2E

def test_correction_chain_is_appended_and_preserved(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    a, _ = run(store)
    bytes_a = journal(tmp_path).read_bytes()
    b, rb = run(store, evidence=[obs(REFERENCE, "2700"), obs(SESSION, "2719")],
                supersedes=a.evaluation_id, created_at=LATER)
    assert b.evaluation_id != a.evaluation_id and b.supersedes_evaluation_id == a.evaluation_id
    assert rb.status is EvaluationAppendStatus.APPENDED and rb.line_number == 2
    bytes_ab = journal(tmp_path).read_bytes()
    assert bytes_ab.startswith(bytes_a)                                    # A は byte 単位で不変
    for field in SUPERSESSION_SUBJECT_FIELDS:
        assert getattr(a, field) == getattr(b, field)
    c, rc = run(store, evidence=[obs(REFERENCE, "2700"), obs(SESSION, "2720")],
                supersedes=b.evaluation_id, created_at=LATER + timedelta(days=1))
    assert rc.line_number == 3 and journal(tmp_path).read_bytes().startswith(bytes_ab)
    reopened = fresh_reload(tmp_path)
    assert [r.evaluation_id for r in reopened.iter_records()] == [a.evaluation_id, b.evaluation_id, c.evaluation_id]
    assert reopened.get(a.evaluation_id) == a and reopened.get(b.evaluation_id) == b
    assert reopened.get(c.evaluation_id).supersedes_evaluation_id == b.evaluation_id
    assert reopened.get(a.evaluation_id).target_close == Decimal("2718.25")   # A は書き換わらない
    assert not hasattr(reopened, "latest") and not hasattr(reopened, "current_evaluation")


# ---------------------------------------------------------------- §14 DEFERRED → EVALUATED E2E

def test_deferred_then_evaluated_history_is_preserved(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    a, _ = run(store, evidence=[obs(REFERENCE, "2700")])                   # target close がまだ無い
    assert a.is_deferred and a.defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE
    line_a = physical_lines(tmp_path)[0]
    b, rb = run(store, evidence=market(), supersedes=a.evaluation_id, created_at=LATER)
    assert b.status is EvaluationStatus.EVALUATED and b.supersedes_evaluation_id == a.evaluation_id
    assert rb.line_number == 2 and physical_lines(tmp_path)[0] == line_a
    reopened = fresh_reload(tmp_path)
    assert reopened.get(a.evaluation_id).is_deferred                      # A は DEFERRED のまま
    assert reopened.get(b.evaluation_id).realized_outcome is RealizedOutcome.UP
    assert [r.status for r in reopened.iter_records()] == [EvaluationStatus.DEFERRED, EvaluationStatus.EVALUATED]


# ---------------------------------------------------------------- §15 corruption E2E

@pytest.mark.parametrize("reason", [
    "MALFORMED_JSON", "TRUNCATED_FINAL_LINE", "INVALID_RECORD", "PHYSICAL_DUPLICATE_IDENTICAL",
    "PHYSICAL_DUPLICATE_CONFLICTING", "DANGLING_SUPERSESSION", "INCOMPATIBLE_SUPERSESSION",
    "NON_CANONICAL_LINE",
])
def test_corruption_of_a_valid_journal_fails_closed_on_fresh_load(tmp_path: Path, reason: str) -> None:
    store, records = multi_record_journal(tmp_path / "valid")
    good = journal(tmp_path / "valid").read_bytes()
    lines = good.split(b"\n")[:-1]
    a, correction = records[2], records[5]
    last = json.loads(lines[-1])
    if reason == "MALFORMED_JSON":
        corrupt = good + b'{"evaluation_id": "eval_\n'
    elif reason == "TRUNCATED_FINAL_LINE":
        corrupt = good[: -len(lines[-1]) // 2]
    elif reason == "INVALID_RECORD":
        corrupt = b"\n".join(lines[:-1] + [canonical_line({**last, "evaluation_id": "eval_" + "0" * 24})[:-1]]) + b"\n"
    elif reason == "PHYSICAL_DUPLICATE_IDENTICAL":
        corrupt = good + lines[0] + b"\n"
    elif reason == "PHYSICAL_DUPLICATE_CONFLICTING":
        conflicting = evaluate_prediction(prediction(), CALENDAR, market(), created_at=CREATED_AT + timedelta(hours=1))
        assert conflicting.evaluation_id == a.evaluation_id and conflicting != a
        corrupt = good + serialize_evaluation(conflicting).encode()
    elif reason == "DANGLING_SUPERSESSION":
        corrupt = b"\n".join(lines[:2] + lines[3:]) + b"\n"               # A を抜く → 訂正が宙に浮く
    elif reason == "INCOMPATIBLE_SUPERSESSION":
        other_subject = evaluate_prediction(prediction(origin=PredictionOrigin.REPLAY), CALENDAR,
                                            [obs(REFERENCE, "2700"), obs(SESSION, "2721")],
                                            created_at=LATER, supersedes_evaluation_id=a.evaluation_id)
        corrupt = good + serialize_evaluation(other_subject).encode()
    else:
        corrupt = b"\n".join(lines[:-1] + [(json.dumps(last, ensure_ascii=False, sort_keys=True)).encode()]) + b"\n"
    isolated = tmp_path / "isolated" / "predictions"
    isolated.mkdir(parents=True)
    (isolated / "evaluations.jsonl").write_bytes(corrupt)
    loaded = None
    with pytest.raises(EvaluationJournalCorrupt) as info:
        loaded = EvaluationStore(tmp_path / "isolated")
    assert loaded is None and info.value.reason == reason
    assert (isolated / "evaluations.jsonl").read_bytes() == corrupt      # 修復しない
    assert len(fresh_reload(tmp_path / "valid")) == 6                     # 元の journal は無傷


# ---------------------------------------------------------------- §16 process restart

def test_process_restart_rebuilds_solely_from_jsonl(tmp_path: Path) -> None:
    store, records = multi_record_journal(tmp_path)
    del store
    restarted = fresh_reload(tmp_path)
    assert list(restarted.iter_records()) == records
    again, result = run(restarted)                                        # 正確な再評価
    assert result.status is EvaluationAppendStatus.ALREADY_PRESENT and again == records[2]
    new, added = run(restarted, prediction("2026-09-23", SESSION), [obs(SESSION, "2718.25"), obs("2026-09-23", "2725")])
    assert added.status is EvaluationAppendStatus.APPENDED and added.line_number == 7
    del restarted
    final = fresh_reload(tmp_path)
    assert len(final) == 7 and list(final.iter_records()) == records + [new]
    assert all(isinstance(r, EvaluationRecord) for r in final.iter_records())


# ---------------------------------------------------------------- §17 prediction journal separation

def test_evaluation_does_not_need_or_touch_the_prediction_journal(tmp_path: Path) -> None:
    sibling = tmp_path / "predictions" / "predictions.jsonl"
    sibling.parent.mkdir(parents=True)
    sibling.write_bytes(b"not a prediction journal\n")                   # 壊れていても評価に無関係
    record, result = run(EvaluationStore(tmp_path))
    assert result.status is EvaluationAppendStatus.APPENDED
    assert sibling.read_bytes() == b"not a prediction journal\n"
    assert sorted(p.name for p in (tmp_path / "predictions").iterdir()) == ["evaluations.jsonl", "predictions.jsonl"]
    code = (
        "import sys\n"
        "import src.intelligence.predictions.evaluation_engine\n"
        "import src.intelligence.predictions.evaluation_store\n"
        "import src.intelligence.predictions.evaluation_record\n"
        "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('src.intelligence'))))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True,
                          check=True, env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    closure = set(proc.stdout.split())
    assert closure == ALLOWED_CLOSURE
    assert "src.intelligence.predictions.prediction_store" not in closure
    assert "src.intelligence.predictions.prediction_ingest" not in closure


# ---------------------------------------------------------------- §18 point-in-time / look-ahead boundary

def test_prediction_is_immutable_and_outcome_flows_only_downstream(tmp_path: Path) -> None:
    pred = prediction()
    before = pred.as_dict()
    record, _ = run(EvaluationStore(tmp_path), pred)
    run(fresh_reload(tmp_path), pred)
    assert pred.as_dict() == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        pred.session_date = "2026-01-01"                                  # type: ignore[misc]
    assert "realized" not in json.dumps(pred.as_dict()) and "prediction_id" in record.as_dict()
    assert "predictions" in EXCLUDED_PACKAGES
    production = runtime_closure()
    for module in ("evaluation_record", "evaluation_store", "evaluation_engine"):
        assert not any(module in m for m in production)
    for p4 in ("reports", "compass", "context", "market", "facts"):
        for path in (REPO_ROOT / "src" / "intelligence" / p4).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "evaluation_" not in text or "evaluation_engine" not in text, path
            for module in ("evaluation_record", "evaluation_store", "evaluation_engine"):
                assert module not in text, (path, module)
    for upstream in ("prediction_record.py", "prediction_store.py", "prediction_ingest.py"):
        assert "evaluation_" not in (PACKAGE / upstream).read_text(encoding="utf-8")


# ---------------------------------------------------------------- §19 single-writer boundary

def test_single_writer_detection_through_the_evaluation_boundary(tmp_path: Path) -> None:
    assert SINGLE_WRITER_ONLY is True
    active = EvaluationStore(tmp_path)
    run(active)
    run(EvaluationStore(tmp_path), abstained_prediction())                # 外部 writer
    before = journal(tmp_path).read_bytes()
    with pytest.raises(ConcurrentModificationDetected):
        run(active, prediction(origin=PredictionOrigin.REPLAY))
    assert journal(tmp_path).read_bytes() == before
    assert active.reload() == 2
    assert run(active, prediction(origin=PredictionOrigin.REPLAY))[1].line_number == 3
    assert len(fresh_reload(tmp_path)) == 3


# ---------------------------------------------------------------- §20 completion audit（P5-2A / B / C の整合）

def test_p5_2_components_are_aligned() -> None:
    assert TARGET_SERIES_ID == TARGET_TOPIX == "index:topix.close.closing.tokyo"
    assert NEUTRAL_BAND_RULE_VERSION == "topix_neutral_band:1.0.0"
    assert set(DEFER_PRECEDENCE) == set(DeferReason) and len(DEFER_PRECEDENCE) == 6   # 語彙が一致
    assert set(SUPERSESSION_SUBJECT_FIELDS) <= set(IDENTITY_KEYS)          # store の subject は record identity の一部
    assert SUPPORTED_SOURCE_IDS == ("jquants",) and SUPPORTED_OBSERVATION_SCHEMA_VERSIONS == (SCHEMA_VERSION,)
    record = evaluate_prediction(prediction(), CALENDAR, market(), created_at=CREATED_AT)
    assert record.realized_outcome is classify_realized_return(record.realized_return)
    assert record.session_verification.verified_previous_session == record.reference_session
    assert record.session_verification.verified_session == record.session_date
    assert EvaluationRecord.from_dict(json.loads(serialize_evaluation(record))) == record
    for name in ("evaluation_record.py", "evaluation_store.py", "evaluation_engine.py"):
        text = (PACKAGE / name).read_text(encoding="utf-8")
        assert "__main__" not in text and "argparse" not in text


def test_no_validation_runner_or_cli_was_added() -> None:
    assert sorted(p.name for p in PACKAGE.glob("*.py")) == [
        "__init__.py", "calibration_contract.py",
        "evaluation_engine.py", "evaluation_record.py", "evaluation_store.py",
        "prediction_ingest.py", "prediction_record.py", "prediction_store.py",
        "topix_neutral_band_measure.py", "topix_research_acquire.py",
    ]
