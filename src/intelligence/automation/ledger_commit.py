"""P12-A4 — ledger の commit の直列化（短い global な ledger lock の中で: 検証 → head で record を組む → 追記 ＋ fsync → checkpoint → 再検証）。

- `LockedLedger(p12_root, probe, clock).commit(builder)`: ledger lock を O_EXCL で取り（他 process が持っていれば有界に待って再試行。
  `LEDGER_LOCK_WAIT_SECONDS` を超えれば `DUPLICATE_INVOCATION:LEDGER_LOCKED`）、lock の **中で** ledger を読み直して鎖を検証し、
  `builder(head_record)` で record を組む（previous_record_digest は実際の commit 済みの head から）、A1 store の `append`
  （再検証 ・追記 ・fsync ・checkpoint ・再検証）、`AFTER_TERMINAL_APPEND` ／ `AFTER_CHECKPOINT` の注入点、解放。
- lock の前に読んだ head は信用しない。transaction の前の検証の読み（`read_verified`）も lock の中で行う（他 process の追記と checkpoint の
  置換の間を「遅れた checkpoint」と誤読しないため）。lock が stale（dead process）でも自動では壊さない: 人の手の `release-lock`。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Optional

from .failure_codes import AutomationError
from .injection import NO_INJECTION, InjectionPoints
from .ledger_model import LedgerRecord
from .ledger_store import LedgerState, LedgerStore
from .operational_lock import LockHeld, acquire_lock
from .process_probe import ProcessProbe

LEDGER_LOCK_WAIT_SECONDS = 30.0
LEDGER_LOCK_POLL_SECONDS = 0.05
Clock = Callable[[], datetime]
RecordBuilder = Callable[[Optional[LedgerRecord], LedgerState], LedgerRecord]


class LockedLedger:
    def __init__(self, p12_root: Any, *, probe: ProcessProbe, clock: Clock, injection: InjectionPoints = NO_INJECTION,
                 wait_seconds: Optional[float] = None) -> None:
        self._root, self._probe, self._clock, self._injection = p12_root, probe, clock, injection
        self._wait = LEDGER_LOCK_WAIT_SECONDS if wait_seconds is None else wait_seconds   # 既定は呼ぶ時の module の値
        self.store = LedgerStore(p12_root)

    def _acquire(self, run_id: str):
        deadline = time.monotonic() + self._wait
        while True:
            try:
                return acquire_lock(self._root, "LEDGER", run_id, probe=self._probe, clock_instant=self._clock())
            except LockHeld:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(LEDGER_LOCK_POLL_SECONDS)                                    # 有界の待ち（短い lock の解放を待つ）

    def read_verified(self, run_id: str, *, allow_stale_checkpoint: bool = False) -> LedgerState:
        """lock の中で読む（読むだけ: 常に解放）。lock の外で読むと、他 process の追記と checkpoint の置換の間を「遅れ」と誤読し得る。"""
        held = self._acquire(run_id)
        try:
            return self.store.open_verified(allow_stale_checkpoint=allow_stale_checkpoint)
        finally:
            held.release()

    def commit(self, run_id: str, builder: RecordBuilder, *, after_append_point: Optional[str] = None) -> LedgerState:
        """lock の中で検証 → builder → append（fsync ・checkpoint ・再検証）→ 解放。戻りは追記後の検証済みの状態。"""
        held = self._acquire(run_id)
        try:
            state = self.store.open_verified()                                          # lock の中で読み直す（前の head は信用しない）
            record = builder(state.records[-1] if state.records else None, state)
            if not isinstance(record, LedgerRecord):
                raise AutomationError("SCHEMA_INVALID", "RECORD_TYPE")
            committed = self.store.append(record)
            if after_append_point is not None:                                         # 終端の commit だけが注入点を持つ
                self._injection.fire(after_append_point)
                self._injection.fire("AFTER_CHECKPOINT")
        except AutomationError:
            held.release()                                                              # 想定内の失敗: lock は返す
            raise
        held.release()                                                                  # 想定外の例外（process の死）では残る → 分類で回復
        return committed

    def repair_checkpoint(self) -> LedgerState:
        """窓 B の回復: lock の中で鎖を検証し、遅れた checkpoint が過去の状態と一致することを確かめて置換 → 再検証。履歴は変えない。"""
        held = self._acquire("0" * 64)
        try:
            stale = self.store.open_verified(allow_stale_checkpoint=True)
            if stale.checkpoint_class != "CHECKPOINT_STALE":
                raise AutomationError("DUPLICATE_INVOCATION", "CHECKPOINT_NOT_STALE")
            self.store.write_checkpoint(stale.records)
            repaired = self.store.open_verified()
        except AutomationError:
            held.release()
            raise
        held.release()
        return repaired


__all__ = ["LEDGER_LOCK_POLL_SECONDS", "LEDGER_LOCK_WAIT_SECONDS", "LockedLedger"]
