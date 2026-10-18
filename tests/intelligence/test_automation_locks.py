"""P12-A4 — 運用の lock（原子的な取得 ・分類 ・stale の解放）・process の探り ・ledger の commit の直列化の test。"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.automation.failure_codes import AutomationError
from src.intelligence.automation.ledger_commit import LockedLedger
from src.intelligence.automation.ledger_model import make_record
from src.intelligence.automation.ledger_store import LedgerStore
from src.intelligence.automation.operational_lock import (LOCK_VERSION, LockHeld, LockRecord, acquire_lock, classify_lock,
                                                          ledger_lock_file, lock_is_stale, read_lock, release_stale_lock,
                                                          run_lock_file)
from src.intelligence.automation.process_probe import ProcessProbe, StaticProbe, this_process
from src.intelligence.automation.run_state import RunState
from tests.intelligence.test_automation_ledger import ok_steps, run

T0 = datetime(2026, 7, 2, tzinfo=timezone.utc)
RUN_ID = "a" * 64
ALIVE = StaticProbe({os.getpid(): True}, {os.getpid(): "1" * 64}, boot="b" * 64)


def clock() -> datetime:
    return T0


# ================================================================ acquisition


def test_lock_acquisition_is_atomic_exclusive_canonical_and_released_by_the_owner(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    held = acquire_lock(root, "RUN", RUN_ID, probe=ALIVE, clock_instant=T0, scheduled_for="2026-07-01T06:00:00Z", attempt=1)
    target = run_lock_file(root, RUN_ID)
    assert target.is_file() and held.target == target
    record = read_lock(target)
    assert record == LockRecord(kind="RUN", run_id=RUN_ID, pid=os.getpid(), process_identity="1" * 64, boot_marker="b" * 64,
                                acquired_at="2026-07-02T00:00:00Z", scheduled_for="2026-07-01T06:00:00Z", attempt=1)
    text = target.read_text(encoding="utf-8")
    assert json.loads(text)["lock_version"] == LOCK_VERSION and set(json.loads(text)) == {
        "lock_version", "kind", "run_id", "pid", "process_identity", "boot_marker", "acquired_at", "scheduled_for", "attempt"}
    assert str(tmp_path) not in text and "USER" not in text and "/" not in text
    with pytest.raises(LockHeld) as e:
        acquire_lock(root, "RUN", RUN_ID, probe=ALIVE, clock_instant=T0)
    assert e.value.public_code == "DUPLICATE_INVOCATION:RUN_ACTIVE" and read_lock(target) == record    # 2 回目は決定論に失敗
    with pytest.raises(LockHeld) as e:
        with acquire_lock(root, "LEDGER", RUN_ID, probe=ALIVE, clock_instant=T0):
            acquire_lock(root, "LEDGER", "c" * 64, probe=ALIVE, clock_instant=T0)
    assert e.value.public_code == "DUPLICATE_INVOCATION:LEDGER_LOCKED" and not ledger_lock_file(root).exists()
    held.release()
    assert not target.exists()
    held.release()                                                                        # 2 回目は無害
    acquire_lock(root, "RUN", RUN_ID, probe=ALIVE, clock_instant=T0).release()
    with pytest.raises(AutomationError):
        acquire_lock(root, "FILE", RUN_ID, probe=ALIVE, clock_instant=T0)
    with pytest.raises(AutomationError):
        acquire_lock(tmp_path / "no" / "parent" / "p12", "RUN", RUN_ID, probe=ALIVE, clock_instant=T0)


def test_racing_threads_acquire_exactly_one_run_lock(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    (root).mkdir()
    outcomes: list = []
    barrier = threading.Barrier(16)

    def attempt() -> None:
        barrier.wait()
        try:
            held = acquire_lock(root, "RUN", RUN_ID, probe=ALIVE, clock_instant=T0)
            outcomes.append(("acquired", held))
        except LockHeld as exc:
            outcomes.append((exc.public_code, None))

    threads = [threading.Thread(target=attempt) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for o, _ in outcomes if o == "acquired") == 1 and len(outcomes) == 16
    assert {o for o, _ in outcomes} == {"acquired", "DUPLICATE_INVOCATION:RUN_ACTIVE"}


# ================================================================ classification


def test_lock_classification_distinguishes_live_dead_reused_rebooted_terminal_malformed_and_unknown(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    target = run_lock_file(root, RUN_ID)
    me = os.getpid()
    assert classify_lock(target, probe=ALIVE)["lock_class"] == "LOCK_ABSENT"
    acquire_lock(root, "RUN", RUN_ID, probe=ALIVE, clock_instant=T0)
    assert classify_lock(target, probe=ALIVE)["lock_class"] == "LOCK_LIVE"
    real_target = run_lock_file(root, "d" * 64)
    acquire_lock(root, "RUN", "d" * 64, probe=ProcessProbe(), clock_instant=T0)             # 本物の probe で取った lock は本物で LIVE
    assert classify_lock(real_target, probe=ProcessProbe())["lock_class"] in ("LOCK_LIVE", "LOCK_UNKNOWN_PROVENANCE")
    assert classify_lock(target, probe=ProcessProbe())["lock_class"] == "LOCK_STALE_REBOOT"   # 偽の起動 token の lock は本物から見れば再起動後
    dead = StaticProbe({me: False}, {}, boot="b" * 64)
    assert classify_lock(target, probe=dead)["lock_class"] == "LOCK_STALE_DEAD"
    reused = StaticProbe({me: True}, {me: "2" * 64}, boot="b" * 64)
    assert classify_lock(target, probe=reused)["lock_class"] == "LOCK_STALE_PID_REUSED"
    rebooted = StaticProbe({me: True}, {me: "1" * 64}, boot="c" * 64)
    assert classify_lock(target, probe=rebooted)["lock_class"] == "LOCK_STALE_REBOOT"
    unknown_alive = StaticProbe({me: None}, {}, boot="b" * 64)
    assert classify_lock(target, probe=unknown_alive)["lock_class"] == "LOCK_UNKNOWN_PROVENANCE"
    no_identity = StaticProbe({me: True}, {me: None}, boot="b" * 64)
    assert classify_lock(target, probe=no_identity)["lock_class"] == "LOCK_UNKNOWN_PROVENANCE"
    store = LedgerStore(root)
    r = run()
    p = make_record(None, r, transition_to=RunState.PLANNED, recorded_at="2026-01-04T22:31:00Z")
    store.append(p)
    q = make_record(p, r, transition_from=RunState.PLANNED, transition_to=RunState.RUNNING, recorded_at="2026-01-04T22:32:00Z")
    store.append(q)
    done = store.append(make_record(q, r, transition_from=RunState.RUNNING, transition_to=RunState.SUCCEEDED,
                                    recorded_at="2026-01-04T22:33:00Z", step_results=ok_steps()))
    terminal_lock = run_lock_file(root, r.run_id)
    acquire_lock(root, "RUN", r.run_id, probe=ALIVE, clock_instant=T0)
    assert classify_lock(terminal_lock, probe=dead, ledger_state=done)["lock_class"] == "LOCK_STALE_TERMINAL"
    assert classify_lock(terminal_lock, probe=ALIVE, ledger_state=done)["lock_class"] == "LOCK_LIVE"   # 生きていれば終端でも LIVE
    target.write_text("{broken\n", encoding="utf-8")
    assert classify_lock(target, probe=ALIVE)["lock_class"] == "LOCK_MALFORMED"
    target.write_text(json.dumps(read_lock(terminal_lock).to_dict(), indent=1) + "\n", encoding="utf-8")   # 正準でない
    assert classify_lock(target, probe=ALIVE)["lock_class"] == "LOCK_MALFORMED"
    for classification in ("LOCK_STALE_DEAD", "LOCK_STALE_PID_REUSED", "LOCK_STALE_REBOOT", "LOCK_STALE_TERMINAL"):
        assert lock_is_stale({"lock_class": classification})
    for classification in ("LOCK_LIVE", "LOCK_MALFORMED", "LOCK_UNKNOWN_PROVENANCE", "LOCK_ABSENT"):
        assert not lock_is_stale({"lock_class": classification})


def test_only_provably_stale_locks_are_released_and_evidence_is_kept(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    me = os.getpid()
    acquire_lock(root, "RUN", RUN_ID, probe=ALIVE, clock_instant=T0)
    target = run_lock_file(root, RUN_ID)
    original = target.read_text(encoding="utf-8")
    for probe in (ALIVE, StaticProbe({me: None}, {}, boot="b" * 64)):
        with pytest.raises(AutomationError) as e:
            release_stale_lock(root, target, classify_lock(target, probe=probe))
        assert e.value.code == "DUPLICATE_INVOCATION" and target.exists()
    outcome = release_stale_lock(root, target, classify_lock(target, probe=StaticProbe({me: False}, {}, boot="b" * 64)))
    assert outcome["released"] and outcome["lock_class"] == "LOCK_STALE_DEAD" and not target.exists()
    evidence = sorted((root / "locks" / "stale").iterdir())
    assert len(evidence) == 1 and evidence[0].read_text(encoding="utf-8") == original and evidence[0].name.startswith("run.")
    target.write_text("{broken\n", encoding="utf-8")
    with pytest.raises(AutomationError) as e:
        release_stale_lock(root, target, classify_lock(target, probe=ALIVE))
    assert e.value.public_code == "DUPLICATE_INVOCATION:LOCK_MALFORMED" and target.exists()      # 壊れた lock は消さない


def test_process_probe_reports_the_this_process_as_alive_with_a_stable_identity() -> None:
    probe = ProcessProbe()
    me = this_process(probe)
    assert me["pid"] == os.getpid() and probe.is_alive(os.getpid()) is True
    assert probe.is_alive(0) is None and probe.is_alive(-5) is None and probe.identity(0) is None
    if me["process_identity"] is not None:                                                # Linux: /proc の starttime
        assert me["process_identity"] == probe.identity(os.getpid()) and len(me["process_identity"]) == 64
    assert probe.is_alive(2 ** 22 + 12345) in (False, None)
    static = StaticProbe({1: True}, {1: "f" * 64}, boot="e" * 64)
    assert static.is_alive(1) is True and static.is_alive(2) is None and static.identity(1) == "f" * 64 and static.boot_marker() == "e" * 64


# ================================================================ ledger commit serialization


def test_locked_ledger_serializes_concurrent_appends_and_keeps_the_checkpoint_in_step(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    root.mkdir()
    ledger = LockedLedger(root, probe=ALIVE, clock=clock)
    runs = [run(day) for day in range(5, 10)]
    barrier = threading.Barrier(len(runs))
    errors: list = []

    def commit(r) -> None:
        barrier.wait()
        try:
            ledger.commit(r.run_id, lambda head, _state: make_record(head, r, transition_to=RunState.PLANNED,
                                                                     recorded_at="2026-01-04T22:31:00Z"))
        except AutomationError as exc:
            errors.append(exc.public_code)

    threads = [threading.Thread(target=commit, args=(r,)) for r in runs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    state = LedgerStore(root).open_verified()
    assert errors == [] and state.summary.record_count == 5 and state.checkpoint.record_count == 5
    assert state.checkpoint.head_digest == state.summary.head_digest == state.records[-1].record_digest
    assert [r.sequence for r in state.records] == [0, 1, 2, 3, 4] and not ledger_lock_file(root).exists()
    assert {r.run_id for r in state.records} == {r.run_id for r in runs}


def test_locked_ledger_waits_boundedly_for_a_held_ledger_lock_and_never_breaks_it(tmp_path: Path) -> None:
    root = tmp_path / "p12"
    root.mkdir()
    ledger = LockedLedger(root, probe=ALIVE, clock=clock, wait_seconds=0.3)
    r = run()
    held = acquire_lock(root, "LEDGER", "c" * 64, probe=ALIVE, clock_instant=T0)
    with pytest.raises(LockHeld) as e:
        ledger.commit(r.run_id, lambda head, _s: make_record(head, r, transition_to=RunState.PLANNED, recorded_at="2026-01-04T22:31:00Z"))
    assert e.value.public_code == "DUPLICATE_INVOCATION:LEDGER_LOCKED" and ledger_lock_file(root).exists()
    assert LedgerStore(root).open_verified().summary.record_count == 0
    released = []

    def release_later() -> None:
        import time
        time.sleep(0.1)
        held.release()
        released.append(True)

    threading.Thread(target=release_later).start()
    state = ledger.commit(r.run_id, lambda head, _s: make_record(head, r, transition_to=RunState.PLANNED, recorded_at="2026-01-04T22:31:00Z"))
    assert state.summary.record_count == 1 and released == [True]                          # 解放を待って進む
    with pytest.raises(AutomationError) as e:
        ledger.commit(r.run_id, lambda head, _s: make_record(None, r, transition_to=RunState.PLANNED, recorded_at="2026-01-04T22:31:00Z"))
    assert e.value.public_code in ("LEDGER_INVALID:APPEND_NOT_AT_HEAD", "LEDGER_INVALID:RUN_AFTER_TERMINAL",
                                   "LEDGER_INVALID:TRANSITION_FROM_MISMATCH") and not ledger_lock_file(root).exists()
    with pytest.raises(AutomationError) as e:
        ledger.repair_checkpoint()
    assert e.value.public_code == "DUPLICATE_INVOCATION:CHECKPOINT_NOT_STALE"
