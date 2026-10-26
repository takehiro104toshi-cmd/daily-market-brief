"""P12-A3 — live の ledger store ・head checkpoint ・原子的な file ・status store ・schedule ／ calendar の authority I/O の test。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.automation.atomic_files import append_line, ensure_root_subdirectory, read_text_file, replace_atomically
from src.intelligence.automation.calendar_authority import calendar_file, read_calendar_authority, write_calendar_authority
from src.intelligence.automation.failure_codes import AutomationError
from src.intelligence.automation.head_checkpoint import (CHECKPOINT_OK, CHECKPOINT_STALE, HeadCheckpoint,
                                                         classify_checkpoint)
from src.intelligence.automation.holiday_calendar import HolidayCalendar
from src.intelligence.automation.ledger_model import GENESIS_DIGEST, LedgerError, make_record
from src.intelligence.automation.ledger_store import LedgerStore
from src.intelligence.automation.run_identity import AutomationRun
from src.intelligence.automation.run_state import RunState
from src.intelligence.automation.schedule_authority import (read_schedule_authority, read_schedule_authority_if_present,
                                                            schedule_file, write_schedule_authority)
from src.intelligence.automation.status_store import (STATUS_OK, STATUS_STALE, classify_status, read_status, status_file,
                                                      write_status)
from tests.intelligence.test_automation_ledger import ok_steps, run
from tests.intelligence.test_automation_models import calendar, schedule

ANCHOR = "a" * 40
T = ["2026-01-04T22:3%d:00Z" % i for i in range(10)]


def planned_running(store: LedgerStore, r: AutomationRun, start=None):
    p = make_record(start, r, transition_to=RunState.PLANNED, recorded_at=T[0])
    store.append(p)
    q = make_record(p, r, transition_from=RunState.PLANNED, transition_to=RunState.RUNNING, recorded_at=T[1])
    return p, store.append(q), q


# ================================================================ atomic files


def test_atomic_replace_read_and_append_are_lf_canonical_and_leave_no_temporaries(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    replace_atomically(target, b'{"a":1}\n')
    assert read_text_file(target) == '{"a":1}\n' and sorted(p.name for p in tmp_path.iterdir()) == ["x.json"]
    (tmp_path / "x.json.tmp").write_bytes(b"stale")                                       # 前回の中断の一時 file は片付ける
    replace_atomically(target, b'{"a":2}\n')
    assert read_text_file(target) == '{"a":2}\n' and sorted(p.name for p in tmp_path.iterdir()) == ["x.json"]
    for bad in (b"{}", b"{}\r\n", "{}\n"):
        with pytest.raises(AutomationError) as e:
            replace_atomically(target, bad)  # type: ignore[arg-type]
        assert e.value.detail == "FILE_BYTES"
    assert read_text_file(tmp_path / "absent.json") is None
    append_line(tmp_path / "l.jsonl", "{}")
    append_line(tmp_path / "l.jsonl", '{"b":1}')
    assert read_text_file(tmp_path / "l.jsonl") == '{}\n{"b":1}\n'
    for bad in ("", "a\nb", "a\r"):
        with pytest.raises(AutomationError):
            append_line(tmp_path / "l.jsonl", bad)
    with pytest.raises(AutomationError) as e:
        ensure_root_subdirectory(tmp_path / "no" / "parent" / "root", "ledger")
    assert e.value.public_code == "ROOT_MISSING:P12"
    assert ensure_root_subdirectory(tmp_path / "root", "ledger").is_dir() and (tmp_path / "root").is_dir()
    with pytest.raises(AutomationError) as e:
        replace_atomically(tmp_path / "missing" / "x.json", b"{}\n")
    assert e.value.public_code == "STEP_FAILED:ATOMIC_REPLACE_IO" and str(tmp_path) not in str(e.value)


# ================================================================ head checkpoint


def test_head_checkpoint_classification_covers_ok_stale_truncated_and_mismatch(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "p12")
    r = run()
    p, state, q = planned_running(store, r)
    records = state.records
    assert classify_checkpoint((), None) == CHECKPOINT_OK and classify_checkpoint(records, None) == CHECKPOINT_STALE
    assert classify_checkpoint(records, HeadCheckpoint.of(records)) == CHECKPOINT_OK
    assert classify_checkpoint(records, HeadCheckpoint.of(records[:1])) == CHECKPOINT_STALE
    assert classify_checkpoint(records[:1], HeadCheckpoint.of(records)) == "LEDGER_INVALID:TAIL_TRUNCATED"
    assert classify_checkpoint(records, HeadCheckpoint(2, "f" * 64)) == "LEDGER_INVALID:CHECKPOINT_MISMATCH"
    assert classify_checkpoint(records, HeadCheckpoint(1, "f" * 64)) == "LEDGER_INVALID:CHECKPOINT_MISMATCH"
    assert classify_checkpoint((), HeadCheckpoint(0, GENESIS_DIGEST)) == CHECKPOINT_OK
    for bad in (dict(record_count=0, head_digest="f" * 64), dict(record_count=1, head_digest=GENESIS_DIGEST),
                dict(record_count=-1, head_digest=GENESIS_DIGEST), dict(record_count=True, head_digest=GENESIS_DIGEST)):
        with pytest.raises(AutomationError) as e:
            HeadCheckpoint(**bad)
        assert e.value.public_code == "LEDGER_INVALID:CHECKPOINT_MALFORMED"
    with pytest.raises(AutomationError) as e:
        HeadCheckpoint.from_dict({**HeadCheckpoint.of(records).to_dict(), "extra": 1})
    assert e.value.detail == "CHECKPOINT_MALFORMED"
    assert json.loads(store.checkpoint_file.read_text()) == HeadCheckpoint.of(records).to_dict()
    assert HeadCheckpoint.from_dict(json.loads(store.checkpoint_file.read_text())) == HeadCheckpoint.of(records)


# ================================================================ ledger store


def test_ledger_store_appends_at_the_verified_head_and_refuses_everything_else(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "p12")
    assert repr(store) == "LedgerStore(<private>)" and str(tmp_path) not in repr(store)
    empty = store.open_verified()
    assert empty.records == () and empty.summary.head_digest == GENESIS_DIGEST and empty.checkpoint is None
    r = run()
    p, state, q = planned_running(store, r)
    assert state.summary.record_count == 2 and state.checkpoint_class == CHECKPOINT_OK and state.run_states == {r.run_id: RunState.RUNNING}
    assert store.ledger_file.read_text(encoding="utf-8") == p.to_json() + "\n" + q.to_json() + "\n"
    assert state.last_record_of(r.run_id) == q and state.last_record_of("f" * 64) is None
    with pytest.raises(LedgerError) as e:                                                 # head でない追記
        store.append(make_record(p, r, transition_from=RunState.PLANNED, transition_to=RunState.RUNNING, recorded_at=T[2]))
    assert e.value.detail == "APPEND_NOT_AT_HEAD"
    with pytest.raises(LedgerError):                                                      # 不正な遷移は追記の前に止まる
        store.append(make_record(q, r, transition_from=RunState.PLANNED, transition_to=RunState.SKIPPED, recorded_at=T[2],
                                 failure_code="CANCELLED"))
    assert store.open_verified().summary.record_count == 2
    with pytest.raises(AutomationError):
        store.append("record")  # type: ignore[arg-type]
    done = store.append(make_record(q, r, transition_from=RunState.RUNNING, transition_to=RunState.SUCCEEDED, recorded_at=T[3],
                                    step_results=ok_steps()))
    assert done.run_states == {r.run_id: RunState.SUCCEEDED} and LedgerStore(tmp_path / "p12").open_verified() == done
    with pytest.raises(AutomationError) as e:
        LedgerStore("")
    assert e.value.public_code == "ROOT_MISSING:P12"


def test_ledger_store_fails_closed_on_malformed_mutated_deleted_reordered_truncated_and_stale(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "p12")
    r = run()
    p, state, q = planned_running(store, r)
    store.append(make_record(q, r, transition_from=RunState.RUNNING, transition_to=RunState.FAILED, recorded_at=T[3],
                             failure_code="SOURCE_STALE"))
    good_text = store.ledger_file.read_bytes()
    good_head = store.checkpoint_file.read_bytes()
    lines = good_text.decode("utf-8").split("\n")[:-1]

    def restore() -> None:
        store.ledger_file.write_bytes(good_text)
        store.checkpoint_file.write_bytes(good_head)

    def mutate(text: str) -> None:
        store.ledger_file.write_bytes(text.encode("utf-8"))                               # explicit LF bytes (A6: Windows text mode writes CRLF)
        assert b"\r" not in store.ledger_file.read_bytes()

    def expect(detail: str) -> None:
        with pytest.raises(LedgerError) as e:
            store.open_verified()
        assert e.value.public_code == f"LEDGER_INVALID:{detail}", detail
        restore()

    mutate("\n".join(lines[:1] + ["{not json"] + lines[2:]) + "\n")
    expect("RECORD_NOT_JSON")
    mutate("\n".join(lines[:1] + [lines[1].replace('"operator":"scheduler"', '"operator":"human"')] + lines[2:]) + "\n")
    expect("RECORD_DIGEST_MISMATCH")
    mutate("\n".join([lines[0], lines[2]]) + "\n")                                                # 真ん中の削除
    expect("SEQUENCE_BREAK")
    mutate("\n".join([lines[0], lines[2], lines[1]]) + "\n")                                      # 並べ替え
    expect("SEQUENCE_BREAK")
    mutate("\n".join(lines[:2]) + "\n")                                                           # 尾の切り捨て（checkpoint は 3）
    expect("TAIL_TRUNCATED")
    mutate("\n".join(lines) + "\n")
    store.checkpoint_file.write_bytes(HeadCheckpoint(3, "f" * 64).to_bytes())
    expect("CHECKPOINT_MISMATCH")
    store.checkpoint_file.write_bytes(b"{broken\n")
    expect("CHECKPOINT_MALFORMED")
    store.checkpoint_file.write_bytes(b'{"record_count": 3}\n')
    expect("CHECKPOINT_MALFORMED")
    store.checkpoint_file.write_bytes(json.dumps(HeadCheckpoint.of(state.records).to_dict(), indent=1).encode() + b"\n")
    expect("CHECKPOINT_NOT_CANONICAL")                                                     # 内容が合っても正準でなければ拒む
    store.ledger_file.write_bytes(store.ledger_file.read_bytes()[:-1])                                 # 末尾の改行なし（byte のまま）
    expect("LEDGER_NOT_LF")
    store.ledger_file.write_bytes(good_text.replace(b"\n", b"\r\n"))                                  # CRLF の ledger は拒む（Windows でも）
    expect("LEDGER_NOT_LF")
    mutate("\n".join(lines[:2]) + "\n" + json.dumps(json.loads(lines[2]), indent=1).replace("\n", "") + "\n")
    expect("RECORD_NOT_CANONICAL")                                                         # 行は正準の byte だけ
    store.checkpoint_file.write_bytes(HeadCheckpoint.of(state.records[:2]).to_bytes())           # 遅れた checkpoint
    with pytest.raises(LedgerError) as e:
        store.open_verified()
    assert e.value.detail == "CHECKPOINT_STALE"
    stale = store.open_verified(allow_stale_checkpoint=True)
    assert stale.checkpoint_class == CHECKPOINT_STALE and stale.summary.record_count == 3
    with pytest.raises(LedgerError) as e:                                                 # 遅れている間は追記しない（回復は A4）
        store.append(make_record(stale.records[-1], run(6), transition_to=RunState.PLANNED, recorded_at=T[4]))
    assert e.value.detail == "CHECKPOINT_STALE" and store.ledger_file.read_bytes() == good_text
    store.checkpoint_file.unlink()                                                        # 無い checkpoint ＝ 遅れ（空でなければ）
    with pytest.raises(LedgerError) as e:
        store.open_verified()
    assert e.value.detail == "CHECKPOINT_STALE"
    restore()
    assert store.open_verified().checkpoint_class == CHECKPOINT_OK
    for rendered in (str(e.value), repr(e.value)):
        assert str(tmp_path) not in rendered and "Traceback" not in rendered


# ================================================================ status store


def test_status_store_writes_canonical_projection_and_classifies_stale_or_corrupt_files(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    store = LedgerStore(root)
    r = run()
    p, state, q = planned_running(store, r)
    assert classify_status(root, state) == STATUS_STALE and read_status(root) is None
    document = write_status(root, state, runtime_anchor=ANCHOR, schedule_id="ops-daily",
                            as_of=datetime(2026, 1, 5, tzinfo=timezone.utc))
    assert classify_status(root, state) == STATUS_OK and read_status(root) == document
    assert document["projection"]["health_code"] == "RUNNING" and document["ledger_record_count"] == 2
    assert document["generated_at"] == "2026-01-05T00:00:00Z" and document["ledger_head_digest"] == state.summary.head_digest
    text = status_file(root).read_text(encoding="utf-8")
    assert text == json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    done = store.append(make_record(q, r, transition_from=RunState.RUNNING, transition_to=RunState.SUCCEEDED, recorded_at=T[3],
                                    step_results=ok_steps()))
    assert classify_status(root, done) == STATUS_STALE                                    # ledger が進めば古い
    write_status(root, done, runtime_anchor=ANCHOR, schedule_id="ops-daily")
    assert classify_status(root, done) == STATUS_OK and read_status(root)["projection"]["health_code"] == "OK"
    status_file(root).write_text("{corrupt", encoding="utf-8")
    assert classify_status(root, done) == STATUS_STALE and read_status(root) is None
    status_file(root).unlink()
    assert classify_status(root, done) == STATUS_STALE
    again = write_status(root, done, runtime_anchor=ANCHOR, schedule_id="ops-daily")      # 常に再生成できる
    assert classify_status(root, done) == STATUS_OK and again["projection"]["last_successful_run"]["run_id"] == r.run_id
    assert str(tmp_path) not in status_file(root).read_text(encoding="utf-8")
    with pytest.raises(AutomationError):
        write_status(root, done, runtime_anchor="bad", schedule_id="ops-daily")


# ================================================================ schedule ／ calendar authority


def test_schedule_authority_io_is_canonical_human_only_and_supersedes_explicitly(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    s1 = schedule()
    assert read_schedule_authority_if_present(root) is None
    with pytest.raises(AutomationError) as e:
        read_schedule_authority(root)
    assert e.value.detail == "SCHEDULE_AUTHORITY_MISSING"
    with pytest.raises(AutomationError) as e:
        write_schedule_authority(root, s1, operator="scheduler")
    assert e.value.detail == "AUTHORITY_WRITE_NOT_HUMAN" and not schedule_file(root).exists()
    assert write_schedule_authority(root, s1, operator="human") == s1.content_digest
    assert schedule_file(root).read_text(encoding="utf-8") == s1.to_json() + "\n" and read_schedule_authority(root) == s1
    assert write_schedule_authority(root, s1, operator="human") == s1.content_digest       # 同じ内容: 何も変えない
    s2 = schedule(version=2)
    with pytest.raises(AutomationError) as e:
        write_schedule_authority(root, s2, operator="human")
    assert e.value.detail == "SUPERSEDES_REQUIRED" and read_schedule_authority(root) == s1
    with pytest.raises(AutomationError) as e:
        write_schedule_authority(root, schedule(version=1, supersedes=s1.content_digest, enabled=False), operator="human")
    assert e.value.detail == "VERSION_NOT_INCREASED"
    with pytest.raises(AutomationError) as e:
        write_schedule_authority(root, schedule(schedule_id="other", version=2, supersedes=s1.content_digest), operator="human")
    assert e.value.detail == "SCHEDULE_ID_CHANGED"
    s2 = schedule(version=2, supersedes=s1.content_digest)
    assert write_schedule_authority(root, s2, operator="human") == s2.content_digest
    assert read_schedule_authority(root) == s2
    history = root / "authority" / "history" / f"schedule.{s1.content_digest}.json"
    assert history.read_text(encoding="utf-8") == s1.to_json() + "\n"                      # 旧版は残る
    schedule_file(root).write_text(json.dumps(s2.to_dict(), indent=1) + "\n", encoding="utf-8")
    with pytest.raises(AutomationError) as e:
        read_schedule_authority(root)
    assert e.value.detail == "SCHEDULE_AUTHORITY_NOT_CANONICAL"
    schedule_file(root).write_text(s2.to_json().replace('"enabled":true', '"enabled":false') + "\n", encoding="utf-8")
    with pytest.raises(AutomationError) as e:
        read_schedule_authority(root)
    assert e.value.detail == "SCHEDULE_DIGEST_MISMATCH"
    with pytest.raises(AutomationError) as e:
        write_schedule_authority(tmp_path / "fresh", schedule(supersedes="f" * 64), operator="human")
    assert e.value.detail == "SUPERSEDES_WITHOUT_PREDECESSOR"


def test_calendar_authority_io_validates_the_reference_and_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    c1 = calendar()
    with pytest.raises(AutomationError) as e:
        read_calendar_authority(root)
    assert e.value.public_code == "CALENDAR_UNAVAILABLE:CALENDAR_MISSING"
    with pytest.raises(AutomationError):
        write_calendar_authority(root, c1, operator="scheduler")
    assert write_calendar_authority(root, c1, operator="human") == c1.content_digest
    assert read_calendar_authority(root) == c1 and read_calendar_authority(root, c1.reference()) == c1
    other = HolidayCalendar(calendar_id="ops-cal", version=2, dates=("2026-01-12", "2026-01-13"))
    with pytest.raises(AutomationError) as e:
        read_calendar_authority(root, other.reference())
    assert e.value.public_code == "CALENDAR_UNAVAILABLE:CALENDAR_REF_MISMATCH"
    with pytest.raises(AutomationError) as e:
        write_calendar_authority(root, HolidayCalendar(calendar_id="ops-cal", version=1, dates=("2026-01-13",)), operator="human")
    assert e.value.detail == "VERSION_NOT_INCREASED"
    assert write_calendar_authority(root, other, operator="human") == other.content_digest
    assert read_calendar_authority(root) == other
    assert (root / "authority" / "history" / f"holiday_calendar.{c1.content_digest}.json").read_text() == c1.to_json() + "\n"
    calendar_file(root).write_text(other.to_json().replace("2026-01-13", "2026-01-14") + "\n", encoding="utf-8")
    with pytest.raises(AutomationError) as e:
        read_calendar_authority(root)
    assert e.value.public_code == "CALENDAR_UNAVAILABLE:CALENDAR_DIGEST_MISMATCH"
    calendar_file(root).write_text("not json\n", encoding="utf-8")
    with pytest.raises(AutomationError) as e:
        read_calendar_authority(root)
    assert e.value.public_code == "CALENDAR_UNAVAILABLE:CALENDAR_NOT_JSON"
