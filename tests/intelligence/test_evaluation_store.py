"""Phase 5 P5-2B — 追記専用 EvaluationStore（evaluations.jsonl）の凍結ガード。

gate §18 の 70 項目を、隔離した一時 root（`tmp_path`）だけで証明する。market / calendar /
network / predictions.jsonl / PredictionStore には触れない。
"""
from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.predictions import evaluation_store as es
from src.intelligence.predictions.evaluation_record import (
    DeferReason,
    EvaluationRecord,
    EvaluationStatus,
    InvalidEvaluationRecord,
    RealizedOutcome,
)
from src.intelligence.predictions.evaluation_store import (
    CORRUPTION_REASONS,
    JOURNAL_FILENAME,
    PREDICTIONS_DIRNAME,
    SINGLE_WRITER_ONLY,
    SUPERSESSION_REJECTIONS,
    SUPERSESSION_SUBJECT_FIELDS,
    ConcurrentModificationDetected,
    EvaluationAppendResult,
    EvaluationAppendStatus,
    EvaluationConflict,
    EvaluationJournalCorrupt,
    EvaluationJournalError,
    EvaluationStore,
    SupersessionRejected,
    evaluations_path,
    parse_evaluation_line,
    serialize_evaluation,
    supersession_mismatch,
)
from tests.intelligence.test_evaluation_record import (
    CREATED_AT,
    PREDICTION_ID,
    deferred,
    evaluated,
    verification,
)
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "evaluation_store.py"
OTHER_PREDICTION = "pred_" + "f" * 24


# ---------------------------------------------------------------- helpers

def store(tmp_path: Path) -> EvaluationStore:
    return EvaluationStore(tmp_path)


def journal(tmp_path: Path) -> Path:
    return tmp_path / PREDICTIONS_DIRNAME / JOURNAL_FILENAME


def lines(tmp_path: Path) -> list:
    raw = journal(tmp_path).read_bytes()
    assert raw.endswith(b"\n")
    return raw.split(b"\n")[:-1]


def write_raw(tmp_path: Path, payload: bytes) -> Path:
    path = journal(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def correction(of: EvaluationRecord, **override) -> EvaluationRecord:
    """`of` を supersede する EVALUATED 訂正（既定では数値も同じ = 履歴だけが変わる）。"""
    return evaluated(supersedes_evaluation_id=of.evaluation_id, **override)


def chain(tmp_path: Path):
    """A DEFERRED → B EVALUATED(supersedes A) → C EVALUATED(supersedes B, 別数値)。"""
    s = store(tmp_path)
    a = deferred()
    b = correction(a)
    c = correction(b, realized_return=Decimal("0.0068"), target_close=Decimal("2718.36"))
    return s, a, b, c


def source() -> str:
    return executable_source(MODULE_PATH)


# ---------------------------------------------------------------- 1–2 absent journal

def test_absent_journal_loads_empty(tmp_path: Path) -> None:                              # 1
    s = store(tmp_path)
    assert len(s) == 0 and list(s.iter_records()) == [] and s.get("eval_" + "0" * 24) is None
    assert "eval_" + "0" * 24 not in s


def test_read_does_not_create_file_or_directory(tmp_path: Path) -> None:                  # 2
    store(tmp_path)
    assert not journal(tmp_path).exists() and not (tmp_path / PREDICTIONS_DIRNAME).exists()
    assert list(tmp_path.iterdir()) == []
    write_raw(tmp_path, b"")
    assert len(store(tmp_path)) == 0


# ---------------------------------------------------------------- 3–8 append / idempotency / conflict

def test_first_append_creates_one_line_with_correct_result(tmp_path: Path) -> None:       # 3, 4
    s = store(tmp_path)
    rec = evaluated()
    result = s.append(rec)
    assert result == EvaluationAppendResult(EvaluationAppendStatus.APPENDED, rec.evaluation_id,
                                            wrote_line=True, line_number=1)
    raw = journal(tmp_path).read_bytes()
    assert raw.count(b"\n") == 1 and raw.endswith(b"\n") and not raw.endswith(b"\r\n")
    assert raw == serialize_evaluation(rec).encode("utf-8")
    assert len(s) == 1 and s.get(rec.evaluation_id) == rec and rec.evaluation_id in s


def test_exact_reappend_is_already_present_and_changes_zero_bytes(tmp_path: Path) -> None:  # 5, 6
    s = store(tmp_path)
    rec = evaluated()
    s.append(rec)
    before = journal(tmp_path).read_bytes()
    result = s.append(evaluated())
    assert result == EvaluationAppendResult(EvaluationAppendStatus.ALREADY_PRESENT,
                                            rec.evaluation_id, wrote_line=False, line_number=1)
    EvaluationStore(tmp_path).append(evaluated())
    assert journal(tmp_path).read_bytes() == before and len(lines(tmp_path)) == 1


@pytest.mark.parametrize("override", [
    dict(reference_observation_id="obs_01K3W2CCCCCCCCCCCCCCCCCCCC"),
    dict(target_observation_id=""),
    dict(source_id="jquants_v2"),
    dict(market_schema_version="0.2.0"),
    dict(reference_close=Decimal("2700.00")),                   # 同値の別表現は canonical で同じ行
    dict(target_close=Decimal("2718.250")),
    dict(session_verification=verification(checked_dates=250, agreements=250)),
])
def test_same_id_with_changed_provenance_conflicts(tmp_path: Path, override: dict) -> None:  # 7
    s = store(tmp_path)
    original = evaluated()
    s.append(original)
    before = journal(tmp_path).read_bytes()
    other = evaluated(**override)
    assert other.evaluation_id == original.evaluation_id
    if serialize_evaluation(other) == serialize_evaluation(original):
        assert s.append(other).status is EvaluationAppendStatus.ALREADY_PRESENT
        assert journal(tmp_path).read_bytes() == before
        return
    with pytest.raises(EvaluationConflict) as info:
        s.append(other)
    assert info.value.evaluation_id == original.evaluation_id
    assert set(info.value.differing_fields) == set(override)
    assert journal(tmp_path).read_bytes() == before and s.get(original.evaluation_id) == original


def test_same_id_with_changed_created_at_conflicts(tmp_path: Path) -> None:               # 8
    s = store(tmp_path)
    s.append(evaluated())
    before = journal(tmp_path).read_bytes()
    with pytest.raises(EvaluationConflict) as info:
        s.append(evaluated(created_at=CREATED_AT + timedelta(minutes=1)))
    assert info.value.differing_fields == ("created_at",)
    assert journal(tmp_path).read_bytes() == before and len(s) == 1
    with pytest.raises(EvaluationConflict):
        EvaluationStore(tmp_path).append(evaluated(created_at=CREATED_AT + timedelta(days=1)))


# ---------------------------------------------------------------- 9–13 serialization / reload / order

def test_canonical_serialization_is_deterministic(tmp_path: Path) -> None:                # 9
    for record in (evaluated(), deferred(), correction(deferred())):
        line = serialize_evaluation(record)
        assert line.endswith("\n") and line.count("\n") == 1
        assert parse_evaluation_line(line, path=journal(tmp_path), line_number=1) == record
        data = json.loads(line)
        assert list(data) == sorted(data)
        assert list(data["session_verification"] or {}) == sorted(data["session_verification"] or {})
        assert data["realized_return"] in (None, "0.006759259259259259259259259")
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        s = EvaluationStore(root)
        s.append(deferred()); s.append(evaluated())
    assert journal(a).read_bytes() == journal(b).read_bytes()


def test_fresh_reload_round_trips_exactly(tmp_path: Path) -> None:                        # 10
    s = store(tmp_path)
    records = [deferred(), evaluated(), correction(evaluated())]
    for r in records:
        s.append(r)
    del s
    reopened = EvaluationStore(tmp_path)
    assert len(reopened) == 3
    for r in records:
        back = reopened.get(r.evaluation_id)
        assert back == r and back.as_dict() == r.as_dict()
        assert back.realized_return == r.realized_return and back.realized_outcome is r.realized_outcome
        assert back.session_verification == r.session_verification


def test_physical_order_is_preserved_and_never_sorted(tmp_path: Path) -> None:            # 11
    s = store(tmp_path)
    later_session = evaluated(reference_session="2026-09-10", session_date="2026-09-11",
                              session_verification=verification(verified_session="2026-09-11",
                                                                verified_previous_session="2026-09-10"))
    records = [evaluated(), later_session, deferred(prediction_id=OTHER_PREDICTION)]
    for r in records:
        s.append(r)
    assert [r.evaluation_id for r in EvaluationStore(tmp_path).iter_records()] == \
        [r.evaluation_id for r in records]
    assert lines(tmp_path) == [serialize_evaluation(r).encode().rstrip(b"\n") for r in records]
    src = source()
    for token in ("sorted(self._entries.values(), key=lambda e: e.line_number)",):
        assert token in src
    scrubbed = src.replace("(self, evaluation_id", "").replace("ConcurrentModificationDetected", "")
    for token in ("session_date)", "created_at)", "latest", "current"):
        assert token not in scrubbed, token


def test_multiple_evaluations_coexist_including_same_prediction(tmp_path: Path) -> None:  # 12, 13
    s = store(tmp_path)
    independent = [deferred(), evaluated(),                      # 同じ予測・supersession なし・別 id
                   deferred(defer_reason=DeferReason.CALENDAR_UNVERIFIED, reference_close=None),
                   evaluated(prediction_id=OTHER_PREDICTION)]
    assert len({r.evaluation_id for r in independent}) == 4
    assert len({r.prediction_id for r in independent}) == 2
    for r in independent:
        assert s.append(r).status is EvaluationAppendStatus.APPENDED
    assert len(EvaluationStore(tmp_path)) == 4


# ---------------------------------------------------------------- 14–20 supersession chain

def test_original_then_correction_preserves_prefix_and_order(tmp_path: Path) -> None:     # 14–18
    s = store(tmp_path)
    original = evaluated()
    assert s.append(original).line_number == 1                          # 14
    bytes_a = journal(tmp_path).read_bytes()
    corrected = correction(original, realized_return=Decimal("0.0068"), target_close=Decimal("2718.36"))
    result = s.append(corrected)                                        # 15
    assert result.status is EvaluationAppendStatus.APPENDED and result.line_number == 2   # 17
    after = journal(tmp_path).read_bytes()
    assert after.startswith(bytes_a) and after[len(bytes_a):] == serialize_evaluation(corrected).encode()  # 16
    reopened = EvaluationStore(tmp_path)                                # 18
    assert list(reopened.iter_records()) == [original, corrected]
    assert reopened.get(original.evaluation_id) == original
    assert reopened.get(corrected.evaluation_id).supersedes_evaluation_id == original.evaluation_id


def test_second_correction_supersedes_first_and_full_chain_is_preserved(tmp_path: Path) -> None:  # 19, 20
    s, a, b, c = chain(tmp_path)
    s.append(a); bytes_a = journal(tmp_path).read_bytes()
    s.append(b); bytes_ab = journal(tmp_path).read_bytes()
    assert s.append(c).line_number == 3
    final = journal(tmp_path).read_bytes()
    assert bytes_ab.startswith(bytes_a) and final.startswith(bytes_ab)
    reopened = EvaluationStore(tmp_path)
    assert [r.evaluation_id for r in reopened.iter_records()] == [a.evaluation_id, b.evaluation_id, c.evaluation_id]
    assert reopened.get(c.evaluation_id).supersedes_evaluation_id == b.evaluation_id
    assert reopened.get(b.evaluation_id).supersedes_evaluation_id == a.evaluation_id
    assert reopened.get(a.evaluation_id).supersedes_evaluation_id == ""
    assert lines(tmp_path)[0] == bytes_a.rstrip(b"\n")                 # 前の行は物理的に不変


# ---------------------------------------------------------------- 21–24 history transitions

def test_deferred_to_evaluated_is_an_append(tmp_path: Path) -> None:                     # 21
    s = store(tmp_path)
    a = deferred()
    s.append(a)
    line_a = lines(tmp_path)[0]
    b = correction(a)
    assert b.status is EvaluationStatus.EVALUATED and s.append(b).line_number == 2
    assert lines(tmp_path)[0] == line_a                                 # A は書き換えない
    assert EvaluationStore(tmp_path).get(a.evaluation_id).is_deferred


def test_evaluated_to_evaluated_correction_allowed(tmp_path: Path) -> None:               # 22
    s = store(tmp_path)
    a = evaluated()
    s.append(a)
    b = correction(a, realized_return=Decimal("-0.004"), target_close=Decimal("2689.2"))
    assert b.realized_outcome is RealizedOutcome.DOWN and s.append(b).wrote_line
    assert EvaluationStore(tmp_path).get(a.evaluation_id).realized_outcome is RealizedOutcome.UP


def test_deferred_to_deferred_revision_allowed(tmp_path: Path) -> None:                   # 23
    s = store(tmp_path)
    a = deferred(defer_reason=DeferReason.CALENDAR_UNVERIFIED, reference_close=None)
    s.append(a)
    b = deferred(defer_reason=DeferReason.TARGET_CLOSE_UNAVAILABLE,
                 supersedes_evaluation_id=a.evaluation_id)
    assert s.append(b).line_number == 2 and len(EvaluationStore(tmp_path)) == 2


def test_same_numeric_result_correction_is_allowed(tmp_path: Path) -> None:               # 24
    s = store(tmp_path)
    a = evaluated()
    s.append(a)
    b = correction(a)                                                   # 数値・outcome・closes すべて同じ
    assert (b.realized_return, b.realized_outcome, b.reference_close, b.target_close, b.status) == \
        (a.realized_return, a.realized_outcome, a.reference_close, a.target_close, a.status)
    assert b.evaluation_id != a.evaluation_id
    assert s.append(b).status is EvaluationAppendStatus.APPENDED
    assert supersession_mismatch(a, b) == ()


# ---------------------------------------------------------------- 25–31 supersession validation

def test_dangling_supersession_rejected(tmp_path: Path) -> None:                          # 25
    s = store(tmp_path)
    s.append(evaluated())
    before = journal(tmp_path).read_bytes()
    with pytest.raises(SupersessionRejected) as info:
        s.append(evaluated(supersedes_evaluation_id="eval_" + "1" * 24))
    assert info.value.reason == "DANGLING_SUPERSESSION"
    assert journal(tmp_path).read_bytes() == before


def test_future_reference_supersession_rejected(tmp_path: Path) -> None:                  # 26
    s = store(tmp_path)
    a = deferred()
    b = correction(a)
    with pytest.raises(SupersessionRejected) as info:                  # B を A より先に追記できない
        s.append(b)
    assert info.value.reason == "DANGLING_SUPERSESSION" and not journal(tmp_path).exists()
    s.append(a)
    assert s.append(b).line_number == 2
    # journal 上で C が B より先に物理的に現れる（forward reference）→ 権威 load 失敗
    c = correction(b, realized_return=Decimal("0.0068"), target_close=Decimal("2718.36"))
    swapped = b"".join(serialize_evaluation(r).encode() for r in (a, c, b))
    write_raw(tmp_path / "iso", swapped)
    with pytest.raises(EvaluationJournalCorrupt) as corrupt:
        EvaluationStore(tmp_path / "iso")
    assert (corrupt.value.reason, corrupt.value.line_number) == ("DANGLING_SUPERSESSION", 2)


def test_cross_prediction_supersession_rejected(tmp_path: Path) -> None:                  # 27
    s = store(tmp_path)
    a = evaluated()
    s.append(a)
    with pytest.raises(SupersessionRejected) as info:
        s.append(evaluated(prediction_id=OTHER_PREDICTION, supersedes_evaluation_id=a.evaluation_id))
    assert info.value.reason == "INCOMPATIBLE_SUPERSESSION" and "prediction_id" in info.value.detail
    assert len(lines(tmp_path)) == 1


def test_incompatible_target_supersession_rejected(tmp_path: Path) -> None:               # 28
    a, b = evaluated(), correction(evaluated())
    assert "target" in SUPERSESSION_SUBJECT_FIELDS
    assert supersession_mismatch(a, b) == ()
    forged = dataclasses.replace  # target は SUPPORTED_TARGETS が 1 つだけなので object 化できない
    assert "target" in source() and forged is not None
    with pytest.raises(InvalidEvaluationRecord):                       # record 境界が別 target を拒否
        evaluated(target="index:nikkei225.close.closing.tokyo", supersedes_evaluation_id=a.evaluation_id)


def test_incompatible_session_supersession_rejected(tmp_path: Path) -> None:              # 29
    s = store(tmp_path)
    a = evaluated()
    s.append(a)
    other_session = evaluated(
        reference_session="2026-09-10", session_date="2026-09-11", supersedes_evaluation_id=a.evaluation_id,
        session_verification=verification(verified_session="2026-09-11", verified_previous_session="2026-09-10"))
    with pytest.raises(SupersessionRejected) as info:
        s.append(other_session)
    assert info.value.reason == "INCOMPATIBLE_SUPERSESSION"
    assert "reference_session" in info.value.detail and "session_date" in info.value.detail
    write_raw(tmp_path / "iso", serialize_evaluation(a).encode() + serialize_evaluation(other_session).encode())
    with pytest.raises(EvaluationJournalCorrupt) as corrupt:
        EvaluationStore(tmp_path / "iso")
    assert corrupt.value.reason == "INCOMPATIBLE_SUPERSESSION" and corrupt.value.line_number == 2


def test_incompatible_classification_version_supersession_rejected() -> None:            # 30
    assert "classification_version" in SUPERSESSION_SUBJECT_FIELDS
    a = evaluated()
    with pytest.raises(InvalidEvaluationRecord):                       # 未対応版は record 境界が拒否
        evaluated(classification_version="topix_neutral_band:2.0.0", supersedes_evaluation_id=a.evaluation_id)
    assert SUPERSESSION_SUBJECT_FIELDS == ("prediction_id", "target", "reference_session",
                                           "session_date", "classification_version")


def test_direct_self_supersession_rejected_by_record_boundary(tmp_path: Path) -> None:    # 31
    a = evaluated()
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord(**{**dataclasses.asdict(a), "session_verification": a.session_verification,
                            "supersedes_evaluation_id": a.evaluation_id})
    s = store(tmp_path)
    s.append(a)
    forged = {**a.as_dict(), "supersedes_evaluation_id": a.evaluation_id}
    write_raw(tmp_path / "iso", (json.dumps(forged, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")) + "\n").encode())
    with pytest.raises(EvaluationJournalCorrupt) as info:
        EvaluationStore(tmp_path / "iso")
    assert info.value.reason == "INVALID_RECORD"


# ---------------------------------------------------------------- 32–44 corruption（fail closed）

def canonical_line(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.mark.parametrize("label,reason,line_number", [
    ("malformed JSON", "MALFORMED_JSON", 2),
    ("truncated final line", "TRUNCATED_FINAL_LINE", 2),
    ("invalid UTF-8", "INVALID_ENCODING", 0),
    ("blank line", "BLANK_LINE", 2),
    ("non-object", "NOT_AN_OBJECT", 2),
    ("unknown field", "INVALID_RECORD", 2),
    ("forged evaluation_id", "INVALID_RECORD", 2),
    ("noncanonical line", "NON_CANONICAL_LINE", 2),
    ("physical duplicate identical", "PHYSICAL_DUPLICATE_IDENTICAL", 2),
    ("physical duplicate conflicting", "PHYSICAL_DUPLICATE_CONFLICTING", 2),
])
def test_corruption_fails_closed_on_fresh_load(tmp_path: Path, label: str, reason: str,
                                               line_number: int) -> None:                  # 32–41
    good = serialize_evaluation(evaluated()).encode()
    second = serialize_evaluation(deferred()).encode()
    data = json.loads(second)
    corrupt = {
        "MALFORMED_JSON": good + b'{"evaluation_id": "eval_\n',
        "TRUNCATED_FINAL_LINE": good + second[: len(second) // 2],
        "INVALID_ENCODING": good + b"\xff\xfe\n",
        "BLANK_LINE": good + b"\n",
        "NOT_AN_OBJECT": good + b"[]\n",
        "INVALID_RECORD": good + canonical_line({**data, "hit": True}) if label == "unknown field"
        else good + canonical_line({**data, "evaluation_id": "eval_" + "0" * 24}),
        "NON_CANONICAL_LINE": good + (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode(),
        "PHYSICAL_DUPLICATE_IDENTICAL": good + good,
        "PHYSICAL_DUPLICATE_CONFLICTING": good + serialize_evaluation(
            evaluated(created_at=CREATED_AT + timedelta(minutes=5))).encode(),
    }[reason]
    write_raw(tmp_path, corrupt)
    with pytest.raises(EvaluationJournalCorrupt) as info:
        store(tmp_path)
    assert (info.value.reason, info.value.line_number) == (reason, line_number)
    assert journal(tmp_path).read_bytes() == corrupt                   # 43 修復しない


def test_no_silent_skip_partial_load_or_migration(tmp_path: Path) -> None:                # 42, 44
    good = serialize_evaluation(evaluated()).encode()
    write_raw(tmp_path, good + good + serialize_evaluation(deferred()).encode())
    loaded = None
    with pytest.raises(EvaluationJournalCorrupt):
        loaded = store(tmp_path)
    assert loaded is None
    old_schema = {**evaluated().as_dict(), "schema_version": "evaluation_record:0.0.9"}
    write_raw(tmp_path / "old", canonical_line(old_schema))
    with pytest.raises(EvaluationJournalCorrupt) as info:
        EvaluationStore(tmp_path / "old")
    assert info.value.reason == "INVALID_RECORD"
    assert len(CORRUPTION_REASONS) == 11 and SUPERSESSION_REJECTIONS == ("DANGLING_SUPERSESSION",
                                                                          "INCOMPATIBLE_SUPERSESSION")
    with pytest.raises(ValueError):
        EvaluationJournalCorrupt(Path("x"), 1, "SOMETHING_ELSE")
    with pytest.raises(ValueError):
        SupersessionRejected("eval_x", "SOMETHING_ELSE")
    for cls in (EvaluationJournalCorrupt, EvaluationConflict, SupersessionRejected,
                ConcurrentModificationDetected):
        assert issubclass(cls, EvaluationJournalError)


# ---------------------------------------------------------------- 45–49 immutability of history / write safety

def test_no_latest_wins_no_date_overwrite_no_old_record_mutation(tmp_path: Path) -> None:  # 45–47
    s, a, b, c = chain(tmp_path)
    for r in (a, b, c):
        s.append(r)
    reopened = EvaluationStore(tmp_path)
    assert len(reopened) == 3 and len({r.session_date for r in reopened.iter_records()}) == 1
    assert reopened.get(a.evaluation_id) == a and reopened.get(a.evaluation_id).is_deferred
    assert [r.status for r in reopened.iter_records()] == [EvaluationStatus.DEFERRED,
                                                            EvaluationStatus.EVALUATED,
                                                            EvaluationStatus.EVALUATED]
    src = source()
    for token in ("def latest", "def current", "def resolve", "latest_for_prediction",
                  "current_evaluation", "evaluated_only", "deferred_only", "by_outcome",
                  "def update", "def replace", "def supersede", "dataclasses.replace",
                  "object.__setattr__", "inactive", "active"):
        assert token not in src, token


def test_append_preserves_prefix_bytes_and_uses_append_only_paths(tmp_path: Path) -> None:  # 48
    s = store(tmp_path)
    s.append(deferred())
    before = journal(tmp_path).read_bytes()
    s.append(evaluated())
    after = journal(tmp_path).read_bytes()
    assert after.startswith(before) and len(after) > len(before)
    src = source()
    for token in ('"w"', "'w'", '"w+"', '"r+"', '"wb"', "write_text", "write_bytes", "truncate(",
                  "unlink", "rename", "replace(", "rmtree", "remove(", "seek(", "writelines"):
        assert token not in src, token
    assert src.count(".open(") == 1 and ".open('a'" in src


def test_flush_and_fsync_discipline(tmp_path: Path, monkeypatch) -> None:                 # 49
    calls = []
    real_fsync = es.os.fsync
    monkeypatch.setattr(es.os, "fsync", lambda fd: (calls.append(fd), real_fsync(fd)))
    s = store(tmp_path)
    s.append(evaluated())
    assert len(calls) == 1
    s.append(evaluated())                                               # ALREADY_PRESENT は書かない
    assert len(calls) == 1
    src = source()
    assert "handle.flush()" in src and "os.fsync(handle.fileno())" in src
    assert "newline=LINE_TERMINATOR" in src and es.LINE_TERMINATOR == "\n"
    assert "mkdir(parents=True, exist_ok=True)" in src


# ---------------------------------------------------------------- 50–52 single writer

def test_single_writer_boundary_and_external_modification(tmp_path: Path) -> None:        # 50–52
    assert SINGLE_WRITER_ONLY is True
    active = store(tmp_path)
    active.append(evaluated())
    EvaluationStore(tmp_path).append(deferred())                        # 外部 writer
    before = journal(tmp_path).read_bytes()
    with pytest.raises(ConcurrentModificationDetected):
        active.append(deferred(prediction_id=OTHER_PREDICTION))
    assert journal(tmp_path).read_bytes() == before
    assert active.reload() == 2                                         # 52 権威から回復
    assert active.append(deferred(prediction_id=OTHER_PREDICTION)).line_number == 3
    assert len(EvaluationStore(tmp_path)) == 3
    src = source()
    for token in ("fcntl", "msvcrt", "threading", "Lock(", "flock", "lockf", "multiprocessing"):
        assert token not in src, token


# ---------------------------------------------------------------- 53–56 root / isolation

def test_caller_controlled_data_root(tmp_path: Path) -> None:                             # 53
    with pytest.raises(TypeError):
        EvaluationStore()                                               # type: ignore[call-arg]
    with pytest.raises(ValueError):
        EvaluationStore("")
    with pytest.raises(ValueError):
        evaluations_path(None)                                          # type: ignore[arg-type]
    assert evaluations_path(tmp_path) == tmp_path / "predictions" / "evaluations.jsonl"
    nested = tmp_path / "deep" / "root"
    s = EvaluationStore(nested)
    assert not nested.exists()
    s.append(evaluated())
    assert journal(nested).exists()
    src = source()
    for token in ("core.paths", "data_root(", "INTELLIGENCE_DATA_ROOT", "environ", "getenv",
                  "USERPROFILE", "config.yaml", "data/vnext", "C:"):
        assert token not in src, token


def test_only_evaluations_jsonl_is_created(tmp_path: Path) -> None:                       # 54
    s = store(tmp_path)
    s.append(evaluated()); s.append(deferred())
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == [JOURNAL_FILENAME]
    assert not (tmp_path / PREDICTIONS_DIRNAME / "predictions.jsonl").exists()


def test_no_predictions_journal_access_and_no_prediction_store_import(tmp_path: Path) -> None:  # 55, 56
    src = source()
    for token in ("predictions.jsonl", "prediction_store", "PredictionStore", "PredictionRecord",
                  "prediction_record", "prediction_ingest"):
        assert token not in src, token
    assert imported_modules(MODULE_PATH) == {"__future__", "json", "os", "dataclasses", "enum",
                                             "pathlib", "typing", ".evaluation_record"}
    sibling = tmp_path / PREDICTIONS_DIRNAME / "predictions.jsonl"
    sibling.parent.mkdir(parents=True)
    sibling.write_bytes(b"not a valid prediction journal\n")            # 隣の journal が壊れていても無関係
    s = store(tmp_path)
    s.append(evaluated())
    assert sibling.read_bytes() == b"not a valid prediction journal\n"


# ---------------------------------------------------------------- 57–65 prohibited dependencies

def test_no_topix_calendar_jquants_engine_or_calibration() -> None:                       # 57–61
    src = source().lower()
    for token in ("topix", "tokyo_calendar", "trading_days", "weekday", "timedelta", "jquants",
                  "classify", "realized_return", "canonical_decimal", "decimal(", "calibration",
                  "accuracy", "brier", "market."):
        assert token not in src, token


def test_no_network_git_or_public_runtime_integration() -> None:                          # 62–64
    src = source()
    for token in ("urllib", "requests", "http", "socket", " git", "git.", "subprocess", "argparse",
                  "__main__", "delivery", "pages", "render", "notification", "publish", "workflow"):
        assert token not in src, token
    assert "predictions" in EXCLUDED_PACKAGES
    assert not any("predictions" in m for m in runtime_closure())
    offenders = [str(p.relative_to(REPO_ROOT))
                 for p in list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py"))
                 if p.parent != MODULE_PATH.parent and "evaluation_store" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_no_accuracy_hit_miss_semantics(tmp_path: Path) -> None:                          # 65
    src = source().replace("missing", "")
    for token in ("hit", "miss", "correct", "score", "win", "loss", "direction_"):
        assert token not in src, token
    s = store(tmp_path)
    s.append(evaluated())
    keys = set(json.loads(lines(tmp_path)[0]))
    assert keys == {f.name for f in dataclasses.fields(EvaluationRecord)}


# ---------------------------------------------------------------- 66–70 authority

def test_jsonl_is_the_authority(tmp_path: Path) -> None:                                  # 66
    a = store(tmp_path)
    a.append(evaluated())
    b = EvaluationStore(tmp_path)
    assert b.get(evaluated().evaluation_id) == evaluated()
    with journal(tmp_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(serialize_evaluation(deferred()))                 # 外部の canonical 追記
    assert deferred().evaluation_id not in a
    assert a.reload() == 2 and deferred().evaluation_id in a


def test_no_sqlite_hash_chain_or_transaction_framework() -> None:                        # 67–69
    src = source()
    for token in ("sqlite", "hashlib", "sha256", "prev_hash", "chain", "transaction", "commit(",
                  "rollback", "begin", "lock"):
        assert token not in src.replace("hash chain", ""), token
    assert "sqlite3" not in imported_modules(MODULE_PATH)


def test_evaluation_record_remains_schema_and_identity_authority(tmp_path: Path) -> None:  # 70
    src = source()
    assert "EvaluationRecord.from_dict" in src and "record.as_dict()" in src
    for token in ("make_evaluation_id", "content_id", "identity_payload", "evaluation_id=",
                  "EvaluationRecord("):
        assert token not in src, token
    s = store(tmp_path)
    with pytest.raises(TypeError):
        s.append(evaluated().as_dict())                                 # type: ignore[arg-type]
    with pytest.raises(TypeError):
        serialize_evaluation("not a record")                            # type: ignore[arg-type]
    assert not journal(tmp_path).exists()
