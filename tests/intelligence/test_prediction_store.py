"""Phase 5 P5-1B — 追記専用 PredictionStore（JSONL journal）の凍結ガード。

gate §14 の 30 項目＋空 / 不在 journal を、隔離した一時 root（`tmp_path`）だけで証明する。
production data root・研究 root・repository 履歴・実 Compass データには触れない。
"""
from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.predictions import prediction_store as ps
from src.intelligence.predictions.prediction_record import (
    InvalidPredictionRecord,
    PredictionOrigin,
    PredictionRecord,
)
from src.intelligence.predictions.prediction_store import (
    CORRUPTION_REASONS,
    JOURNAL_FILENAME,
    PREDICTIONS_DIRNAME,
    SINGLE_WRITER_ONLY,
    AppendResult,
    AppendStatus,
    ConcurrentModificationDetected,
    PredictionConflict,
    PredictionJournalCorrupt,
    PredictionJournalError,
    PredictionStore,
    journal_path,
    parse_line,
    serialize_record,
)
from src.intelligence.reports.market_signal import SignalLevel
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES
from tests.intelligence.test_prediction_record import (
    CUTOFF,
    GOLDEN_AVAILABLE_ID,
    RECORDED_AT,
    abstained_kwargs,
    executable_source,
    imported_modules,
    make,
    mixed_kwargs,
)
from src.intelligence.predictions.prediction_record import make_prediction_record

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "prediction_store.py"


# ---------------------------------------------------------------- helpers

def store(tmp_path: Path) -> PredictionStore:
    return PredictionStore(tmp_path)


def journal(tmp_path: Path) -> Path:
    return tmp_path / PREDICTIONS_DIRNAME / JOURNAL_FILENAME


def lines(tmp_path: Path) -> list:
    return journal(tmp_path).read_bytes().split(b"\n")[:-1]


def write_raw(tmp_path: Path, payload: bytes) -> Path:
    path = journal(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def neutral() -> PredictionRecord:
    return make(level=SignalLevel.NEUTRAL_RANGE, confidence="LOW")


def abstained() -> PredictionRecord:
    return make_prediction_record(**abstained_kwargs())


def source() -> str:
    return executable_source(MODULE_PATH)


# ---------------------------------------------------------------- empty / nonexistent（§7 / §14 extra）

def test_nonexistent_journal_opens_empty_and_creates_nothing(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert len(s) == 0 and list(s.iter_records()) == [] and s.get(GOLDEN_AVAILABLE_ID) is None
    assert GOLDEN_AVAILABLE_ID not in s
    assert not journal(tmp_path).exists() and not (tmp_path / PREDICTIONS_DIRNAME).exists()
    assert list(tmp_path.iterdir()) == []


def test_zero_byte_journal_is_a_valid_empty_journal(tmp_path: Path) -> None:
    write_raw(tmp_path, b"")
    assert len(store(tmp_path)) == 0


def test_journal_path_is_under_the_caller_supplied_root(tmp_path: Path) -> None:
    assert journal_path(tmp_path) == tmp_path / "predictions" / "predictions.jsonl"
    assert store(tmp_path).path == journal(tmp_path)
    assert store(tmp_path).data_root == tmp_path


# ---------------------------------------------------------------- 1–3 first append / idempotency / bytes

def test_first_append_creates_exactly_one_terminated_line(tmp_path: Path) -> None:      # 1
    s = store(tmp_path)
    result = s.append(make())
    assert result == AppendResult(AppendStatus.APPENDED, GOLDEN_AVAILABLE_ID,
                                  wrote_line=True, line_number=1)
    raw = journal(tmp_path).read_bytes()
    assert raw.count(b"\n") == 1 and raw.endswith(b"\n") and not raw.endswith(b"\r\n")
    assert len(s) == 1 and s.get(GOLDEN_AVAILABLE_ID) == make()


def test_exact_second_append_is_idempotent(tmp_path: Path) -> None:                     # 2
    s = store(tmp_path)
    s.append(make())
    result = s.append(make())
    assert result == AppendResult(AppendStatus.ALREADY_PRESENT, GOLDEN_AVAILABLE_ID,
                                  wrote_line=False, line_number=1)
    assert len(s) == 1 and len(lines(tmp_path)) == 1


def test_exact_second_append_does_not_change_file_bytes(tmp_path: Path) -> None:        # 3
    s = store(tmp_path)
    s.append(make())
    before = journal(tmp_path).read_bytes()
    s.append(make())
    PredictionStore(tmp_path).append(make())          # 別 handle からも同じ
    assert journal(tmp_path).read_bytes() == before


def test_same_instant_other_timezone_is_the_same_stored_record(tmp_path: Path) -> None:
    from datetime import timezone
    s = store(tmp_path)
    s.append(make())
    jst = timezone(timedelta(hours=9))
    result = s.append(make(recorded_at=RECORDED_AT.astimezone(jst)))
    assert result.status is AppendStatus.ALREADY_PRESENT and not result.wrote_line


# ---------------------------------------------------------------- 4–5 same id, different content → fail closed

@pytest.mark.parametrize("override", [
    dict(brief_id="brief_" + "9" * 24),
    dict(signal_id="sig_" + "9" * 24),
    dict(package_id="pkg_" + "9" * 24),
    dict(draft_id="draft_" + "9" * 24),
])
def test_same_id_with_different_provenance_fails_closed(tmp_path: Path, override: dict) -> None:  # 4
    s = store(tmp_path)
    s.append(make())
    before = journal(tmp_path).read_bytes()
    other = make(**override)
    assert other.prediction_id == GOLDEN_AVAILABLE_ID
    with pytest.raises(PredictionConflict) as info:
        s.append(other)
    assert info.value.prediction_id == GOLDEN_AVAILABLE_ID
    assert info.value.differing_fields == tuple(sorted(override))
    assert journal(tmp_path).read_bytes() == before          # 2 行目を書かない
    assert s.get(GOLDEN_AVAILABLE_ID) == make()              # merge / 更新しない


@pytest.mark.parametrize("override", [
    dict(recorded_at=RECORDED_AT + timedelta(minutes=1)),
    dict(cutoff=CUTOFF),
    dict(principle_refs=("MP-01",)),
    dict(market_principle_version="market_rules:2.0.0"),
    dict(outlook_rule_version="outlook:1.0.0"),
])
def test_same_id_with_different_audit_metadata_fails_closed(tmp_path: Path, override: dict) -> None:  # 5
    s = store(tmp_path)
    s.append(make())
    before = journal(tmp_path).read_bytes()
    with pytest.raises(PredictionConflict) as info:
        s.append(make(**override))
    assert info.value.differing_fields == tuple(sorted(override))
    assert journal(tmp_path).read_bytes() == before
    assert len(s) == 1


def test_conflict_is_detected_across_store_instances(tmp_path: Path) -> None:
    store(tmp_path).append(make())
    with pytest.raises(PredictionConflict):
        store(tmp_path).append(make(brief_id="brief_" + "9" * 24))


# ---------------------------------------------------------------- 6–7 coexistence

def test_multiple_prediction_ids_on_one_session_coexist(tmp_path: Path) -> None:        # 6
    s = store(tmp_path)
    records = [make(), neutral(), abstained(),
               make_prediction_record(**mixed_kwargs())]
    assert len({r.session_date for r in records}) == 1
    assert len({r.prediction_id for r in records}) == 4
    for r in records:
        assert s.append(r).status is AppendStatus.APPENDED
    assert len(s) == 4 and list(s.iter_records()) == records
    assert len(lines(tmp_path)) == 4


def test_live_and_replay_coexist(tmp_path: Path) -> None:                               # 7
    s = store(tmp_path)
    live, replay = make(), make(origin=PredictionOrigin.REPLAY)
    assert live.prediction_id != replay.prediction_id
    assert s.append(live).wrote_line and s.append(replay).wrote_line
    assert [r.origin for r in s.iter_records()] == [PredictionOrigin.LIVE, PredictionOrigin.REPLAY]


# ---------------------------------------------------------------- 8–10 semantics persist unchanged / round-trip

def test_available_neutral_range_persists_unchanged(tmp_path: Path) -> None:            # 8
    store(tmp_path).append(neutral())
    back = PredictionStore(tmp_path).get(neutral().prediction_id)
    assert back == neutral()
    assert back.available is True and back.level is SignalLevel.NEUTRAL_RANGE
    assert back.is_abstention is False


def test_unavailable_abstention_persists_unchanged(tmp_path: Path) -> None:             # 9
    s = store(tmp_path)
    s.append(abstained())
    s.append(make_prediction_record(**mixed_kwargs()))
    reopened = PredictionStore(tmp_path)
    a = reopened.get(abstained().prediction_id)
    assert a == abstained() and a.is_abstention and a.level is None and a.confidence == ""
    m = reopened.get(make_prediction_record(**mixed_kwargs()).prediction_id)
    assert m.is_abstention and m.unavailable_reason == "direction_mixed"
    assert m.confidence == "MEDIUM" and m.horizon == "next_tokyo_session"


def test_serialization_round_trip_is_deterministic(tmp_path: Path) -> None:            # 10
    for record in (make(cutoff=CUTOFF, principle_refs=("MP-01", "MP-02"),
                        outlook_rule_version="outlook:1.0.0"),
                   abstained(), make_prediction_record(**mixed_kwargs())):
        line = serialize_record(record)
        assert line.endswith("\n") and line.count("\n") == 1 and " " not in line.split('"principle_refs"')[0]
        assert parse_line(line, path=journal(tmp_path), line_number=1) == record
        assert serialize_record(parse_line(line, path=journal(tmp_path), line_number=1)) == line
        assert list(json.loads(line)) == sorted(json.loads(line))
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        s = PredictionStore(root)
        s.append(make()); s.append(abstained()); s.append(neutral())
    assert journal(a).read_bytes() == journal(b).read_bytes()


# ---------------------------------------------------------------- 11–18 corruption（fail closed, no silent skip）

def test_malformed_json_fails_authoritative_load(tmp_path: Path) -> None:               # 11
    write_raw(tmp_path, serialize_record(make()).encode() + b"{not json\n")
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert (info.value.reason, info.value.line_number) == ("MALFORMED_JSON", 2)


def test_unknown_field_fails_authoritative_load(tmp_path: Path) -> None:                # 12
    data = {**make().as_dict(), "display_text": "上昇バイアス"}
    write_raw(tmp_path, (json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n").encode())
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert info.value.reason == "INVALID_RECORD" and info.value.line_number == 1
    assert isinstance(info.value.__cause__, InvalidPredictionRecord)


def test_forged_prediction_id_fails_through_the_frozen_boundary(tmp_path: Path) -> None:  # 13
    data = {**make().as_dict(), "prediction_id": "pred_" + "0" * 24}
    write_raw(tmp_path, (json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n").encode())
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert info.value.reason == "INVALID_RECORD"
    assert isinstance(info.value.__cause__, InvalidPredictionRecord)


def test_stale_id_after_semantic_edit_fails_authoritative_load(tmp_path: Path) -> None:
    data = {**make().as_dict(), "level": "DOWNWARD_LEAN"}     # 意味論を変え id 据え置き
    write_raw(tmp_path, (json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n").encode())
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert info.value.reason == "INVALID_RECORD"


@pytest.mark.parametrize("patch", [
    dict(level=""),                                  # available なのに level 無し
    dict(unavailable_reason="draft_abstained"),      # available なのに理由あり
    dict(confidence="VERY_HIGH"),                    # 語彙外
    dict(reference_session="2026-09-17"),            # 順序違反
    dict(origin="BACKTEST"),                         # 未知 origin
])
def test_invalid_state_machine_record_fails_authoritative_load(tmp_path: Path, patch: dict) -> None:  # 14
    data = {**make().as_dict(), **patch}
    write_raw(tmp_path, (json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n").encode())
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert info.value.reason == "INVALID_RECORD"


def test_physical_duplicate_identical_id_fails_authoritative_load(tmp_path: Path) -> None:  # 15
    line = serialize_record(make()).encode()
    write_raw(tmp_path, line + line)
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert (info.value.reason, info.value.line_number) == ("PHYSICAL_DUPLICATE_IDENTICAL", 2)
    assert "line 1" in info.value.detail


def test_physical_duplicate_conflicting_id_fails_authoritative_load(tmp_path: Path) -> None:  # 16
    first = serialize_record(make()).encode()
    second = serialize_record(make(brief_id="brief_" + "9" * 24)).encode()
    write_raw(tmp_path, first + serialize_record(neutral()).encode() + second)
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert (info.value.reason, info.value.line_number) == ("PHYSICAL_DUPLICATE_CONFLICTING", 3)


@pytest.mark.parametrize("tail", [
    lambda line: line[: len(line) // 2],             # JSON の途中で切れた
    lambda line: line[:-1],                          # JSON は完全だが終端改行が無い
])
def test_truncated_final_record_fails_authoritative_load(tmp_path: Path, tail) -> None:  # 17
    good = serialize_record(make()).encode()
    write_raw(tmp_path, good + tail(serialize_record(neutral()).encode()))
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert (info.value.reason, info.value.line_number) == ("TRUNCATED_FINAL_LINE", 2)


@pytest.mark.parametrize("payload,reason,line_number", [
    (b"\n", "BLANK_LINE", 1),
    (b"   \n", "BLANK_LINE", 1),
    (b"[]\n", "NOT_AN_OBJECT", 1),
    (b"\xff\xfe\n", "INVALID_ENCODING", 0),
])
def test_blank_or_non_object_or_binary_lines_are_never_skipped(tmp_path: Path, payload: bytes,
                                                              reason: str, line_number: int) -> None:  # 18
    write_raw(tmp_path, serialize_record(make()).encode() + payload
              if reason != "INVALID_ENCODING" else payload)
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert info.value.reason == reason
    assert info.value.line_number == (line_number + 1 if reason not in ("INVALID_ENCODING",) else 0)


def test_non_canonical_but_parseable_line_is_rejected_not_repaired(tmp_path: Path) -> None:
    pretty = json.dumps(make().as_dict(), ensure_ascii=False, indent=None) + "\n"   # spaces after ':'
    assert pretty != serialize_record(make())
    write_raw(tmp_path, pretty.encode())
    with pytest.raises(PredictionJournalCorrupt) as info:
        store(tmp_path)
    assert info.value.reason == "NON_CANONICAL_LINE"


def test_crlf_terminated_line_is_rejected(tmp_path: Path) -> None:
    write_raw(tmp_path, serialize_record(make()).encode().replace(b"\n", b"\r\n"))
    with pytest.raises(PredictionJournalCorrupt):
        store(tmp_path)


def test_corrupt_journal_yields_no_partial_store_and_no_silent_dedup(tmp_path: Path) -> None:  # 18
    good = serialize_record(make()).encode()
    write_raw(tmp_path, good + good + serialize_record(neutral()).encode())
    with pytest.raises(PredictionJournalCorrupt):
        store(tmp_path)                         # 同一内容でも畳まない・部分結果も返さない
    s = PredictionStore(tmp_path / "other")     # 破損を避けて別 root を開くのは呼び出し側
    assert len(s) == 0


def test_corruption_reasons_are_a_frozen_vocabulary() -> None:
    assert len(CORRUPTION_REASONS) == 9
    with pytest.raises(ValueError):
        PredictionJournalCorrupt(Path("x"), 1, "SOMETHING_ELSE")
    assert issubclass(PredictionJournalCorrupt, PredictionJournalError)
    assert issubclass(PredictionConflict, PredictionJournalError)
    assert issubclass(ConcurrentModificationDetected, PredictionJournalError)


# ---------------------------------------------------------------- 19–21 append-only discipline

def test_module_has_no_overwrite_truncate_or_delete_path() -> None:                    # 19
    src = source()
    for token in ('"w"', "'w'", '"w+"', '"r+"', '"wb"', "write_text", "write_bytes",
                  "truncate(", "unlink", "rename", "replace(", "rmtree", "remove(",
                  "seek(", "writelines"):
        assert token not in src, token
    assert src.count('.open(') == 1 and ".open('a'" in src


def test_append_preserves_existing_prefix_bytes(tmp_path: Path) -> None:               # 20
    s = store(tmp_path)
    s.append(make())
    before = journal(tmp_path).read_bytes()
    s.append(neutral())
    s.append(abstained())
    after = journal(tmp_path).read_bytes()
    assert after.startswith(before) and len(after) > len(before)


def test_no_date_keyed_overwrite_semantics(tmp_path: Path) -> None:                    # 21
    s = store(tmp_path)
    first = make()
    later = make(level=SignalLevel.DOWNWARD_LEAN, recorded_at=RECORDED_AT + timedelta(hours=1))
    assert first.session_date == later.session_date
    s.append(first); s.append(later)
    assert [r.level for r in s.iter_records()] == [SignalLevel.UPWARD_LEAN,
                                                   SignalLevel.DOWNWARD_LEAN]
    assert s.get(first.prediction_id) == first             # 「最新が勝つ」を持たない
    src = source()
    for token in ("latest", "for_session", "by_date", "by_session", "supersede"):
        assert token not in src, token


# ---------------------------------------------------------------- 22–23 JSONL authority / no SQLite

def test_jsonl_is_the_authority_and_the_index_is_rebuilt_from_it(tmp_path: Path) -> None:  # 22
    a = store(tmp_path)
    a.append(make())
    b = PredictionStore(tmp_path)                      # 別 instance は JSONL から見える
    assert b.get(GOLDEN_AVAILABLE_ID) == make()
    with journal(tmp_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(serialize_record(neutral()))      # 外部の canonical 追記
    assert neutral().prediction_id not in a
    assert a.reload() == 2 and neutral().prediction_id in a
    assert sorted(p.name for p in (tmp_path / PREDICTIONS_DIRNAME).iterdir()) == [JOURNAL_FILENAME]


def test_no_sqlite_or_index_files(tmp_path: Path) -> None:                             # 23
    assert "sqlite3" not in imported_modules(MODULE_PATH) and "sqlite" not in source()
    s = store(tmp_path)
    s.append(make())
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == [JOURNAL_FILENAME]


# ---------------------------------------------------------------- 24–27 boundaries

def test_no_network_and_stdlib_only_beyond_the_record_module() -> None:                # 24
    allowed = {"__future__", "json", "os", "dataclasses", "enum", "pathlib", "typing",
               ".prediction_record"}
    assert imported_modules(MODULE_PATH) <= allowed
    src = source()
    for token in ("urllib", "requests", "http", "socket", "jquants", "environ", "getenv"):
        assert token not in src, token


def test_no_git_or_repository_persistence(tmp_path: Path) -> None:                     # 25
    src = source()
    for token in ("git", "subprocess", "core.paths", "data_root(", "INTELLIGENCE_DATA_ROOT",
                  "config.yaml", "data/vnext", "yaml"):
        assert token not in src, token
    store(tmp_path).append(make())
    assert not (REPO_ROOT / "data" / "vnext" / PREDICTIONS_DIRNAME).exists()


def test_no_production_module_reaches_the_store() -> None:                             # 26
    assert "predictions" in EXCLUDED_PACKAGES
    offenders = []
    for path in list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py")):
        if path.parent == MODULE_PATH.parent:
            continue
        if "prediction_store" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
    local = {m for m in imported_modules(MODULE_PATH) if m.startswith(".")}
    assert local == {".prediction_record"}


def test_no_evaluation_or_outcome_fields_in_the_journal(tmp_path: Path) -> None:       # 27
    store(tmp_path).append(make())
    keys = set(json.loads(lines(tmp_path)[0]))
    assert keys == {f.name for f in dataclasses.fields(PredictionRecord)}
    for fragment in ("realized", "outcome", "evaluation", "threshold", "topix", "close",
                     "label", "display", "delivery", "markdown"):
        assert not any(fragment in k for k in keys), fragment
    src = source()
    for token in ("EvaluationRecord", "evaluations.jsonl", "realized", "outcome",
                  "calendar", "topix"):
        assert token not in src, token


# ---------------------------------------------------------------- 28 single-writer boundary

def test_single_writer_boundary_is_explicit_and_detected(tmp_path: Path) -> None:      # 28
    assert SINGLE_WRITER_ONLY is True
    a = store(tmp_path)
    a.append(make())
    PredictionStore(tmp_path).append(neutral())        # 別 writer が先に追記した
    before = journal(tmp_path).read_bytes()
    with pytest.raises(ConcurrentModificationDetected):
        a.append(abstained())                          # 古い index のまま書かない
    assert journal(tmp_path).read_bytes() == before
    assert a.reload() == 2
    assert a.append(abstained()).line_number == 3
    assert len(lines(tmp_path)) == 3


def test_module_claims_no_locking_or_thread_safety() -> None:
    src = source()
    for token in ("fcntl", "msvcrt", "threading", "Lock(", "flock", "lockf", "thread-safe",
                  "thread_safe", "multiprocessing"):
        assert token not in src, token


# ---------------------------------------------------------------- 29–30 root control / hygiene

def test_data_root_is_caller_controlled_and_never_defaulted(tmp_path: Path) -> None:   # 29
    with pytest.raises(TypeError):
        PredictionStore()                              # type: ignore[call-arg]
    with pytest.raises(ValueError):
        PredictionStore("")
    with pytest.raises(ValueError):
        journal_path(None)                             # type: ignore[arg-type]
    nested = tmp_path / "deep" / "root"
    s = PredictionStore(nested)
    assert not nested.exists()                         # 読むだけでは作らない
    s.append(make())
    assert journal(nested).exists()                    # 追記時にだけ親を作る


def test_journal_line_carries_no_secret_or_machine_path(tmp_path: Path) -> None:       # 30
    s = store(tmp_path)
    s.append(make(cutoff=CUTOFF, principle_refs=("MP-01",), outlook_rule_version="outlook:1.0.0"))
    text = journal(tmp_path).read_text(encoding="utf-8")
    for token in (str(tmp_path), "/home/", "C:\\", "Users", "JQUANTS", "api_key", "token"):
        assert token not in text, token
    assert set(json.loads(text)) == {f.name for f in dataclasses.fields(PredictionRecord)}


# ---------------------------------------------------------------- write discipline / result contract

def test_append_writes_flushes_and_fsyncs_once(tmp_path: Path, monkeypatch) -> None:
    calls = []
    real_fsync = ps.os.fsync
    monkeypatch.setattr(ps.os, "fsync", lambda fd: (calls.append(fd), real_fsync(fd)))
    s = store(tmp_path)
    s.append(make())
    assert len(calls) == 1
    s.append(make())                                   # ALREADY_PRESENT は書かず fsync もしない
    assert len(calls) == 1
    src = source()
    assert "handle.flush()" in src and "os.fsync(handle.fileno())" in src
    assert "newline=LINE_TERMINATOR" in src and ps.LINE_TERMINATOR == "\n"   # OS の改行変換を止める


def test_append_result_is_frozen_and_the_vocabulary_is_two_states(tmp_path: Path) -> None:
    result = store(tmp_path).append(make())
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = AppendStatus.ALREADY_PRESENT   # type: ignore[misc]
    assert [s.value for s in AppendStatus] == ["APPENDED", "ALREADY_PRESENT"]


def test_append_rejects_non_records(tmp_path: Path) -> None:
    s = store(tmp_path)
    with pytest.raises(TypeError):
        s.append(make().as_dict())                     # type: ignore[arg-type]
    with pytest.raises(TypeError):
        serialize_record("not a record")               # type: ignore[arg-type]
    assert not journal(tmp_path).exists()


def test_reload_rebuilds_line_numbers_from_physical_order(tmp_path: Path) -> None:
    s = store(tmp_path)
    for record in (abstained(), make(), neutral()):
        s.append(record)
    reopened = PredictionStore(tmp_path)
    assert [r.prediction_id for r in reopened.iter_records()] == \
        [abstained().prediction_id, GOLDEN_AVAILABLE_ID, neutral().prediction_id]
    assert reopened.append(make()).line_number == 2
