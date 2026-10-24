"""P12-A3 — live の追記専用 ledger（`<p12_root>/ledger/ledger.jsonl` ＋ `ledger/head.json`）。A1 の LedgerRecord ・verify_chain を使う。

- `LedgerStore(p12_root).open_verified()`: file を読み、各行を正準として解析（A1 `parse_records`）・鎖を検証（A1 `verify_chain`）・
  checkpoint を分類する。不正なら `LedgerError("LEDGER_INVALID", <detail>)`（修復 ・切り捨て ・並べ替え ・書き換えはしない）。
- `append(record)`: 直前に鎖を再検証し、record の previous_record_digest ・sequence が検証済みの head と一致することを要求し、1 行を
  追記（flush ・fsync）して、checkpoint を原子的に置換する。checkpoint が遅れている（`CHECKPOINT_STALE`）間は追記を拒む
  （`LEDGER_INVALID:CHECKPOINT_STALE`。回復は A4）。
- 鎖 ＋ checkpoint は改変 ・切り捨ての検出と一貫性だけ（認証ではない）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from .atomic_files import append_line, ensure_root_subdirectory, read_text_file, replace_atomically
from .failure_codes import AutomationError
from .head_checkpoint import CHECKPOINT_OK, CHECKPOINT_STALE, HeadCheckpoint, classify_checkpoint
from .ledger_model import ChainSummary, LedgerError, LedgerRecord, parse_records, verify_chain
from .run_state import RunState

LEDGER_DIRECTORY = "ledger"
LEDGER_FILE_NAME = "ledger.jsonl"
CHECKPOINT_FILE_NAME = "head.json"


@dataclass(frozen=True)
class LedgerState:
    records: Tuple[LedgerRecord, ...]
    summary: ChainSummary
    checkpoint: Optional[HeadCheckpoint]
    checkpoint_class: str

    @property
    def run_states(self) -> Mapping[str, RunState]:
        return self.summary.run_states

    def last_record_of(self, run_id: str) -> Optional[LedgerRecord]:
        for record in reversed(self.records):
            if record.run_id == run_id:
                return record
        return None


class LedgerStore:
    def __init__(self, p12_root: Any) -> None:
        if p12_root in ("", None):
            raise AutomationError("ROOT_MISSING", "P12")
        self._root = Path(p12_root)

    def __repr__(self) -> str:
        return "LedgerStore(<private>)"

    @property
    def directory(self) -> Path:
        return self._root / LEDGER_DIRECTORY

    @property
    def ledger_file(self) -> Path:
        return self.directory / LEDGER_FILE_NAME

    @property
    def checkpoint_file(self) -> Path:
        return self.directory / CHECKPOINT_FILE_NAME

    def _read_records(self) -> Tuple[LedgerRecord, ...]:
        text = read_text_file(self.ledger_file)
        if text is None or text == "":
            return ()
        if not text.endswith("\n") or "\r" in text:
            raise LedgerError("LEDGER_NOT_LF")
        return parse_records(text[:-1].split("\n"))

    def _read_checkpoint(self) -> Optional[HeadCheckpoint]:
        text = read_text_file(self.checkpoint_file)
        if text is None:
            return None
        try:
            data = json.loads(text)
        except ValueError:
            raise LedgerError("CHECKPOINT_MALFORMED") from None
        checkpoint = HeadCheckpoint.from_dict(data)
        if checkpoint.to_bytes().decode("utf-8") != text:
            raise LedgerError("CHECKPOINT_NOT_CANONICAL")
        return checkpoint

    def open_verified(self, *, allow_stale_checkpoint: bool = False) -> LedgerState:
        """読み ・検証 ・分類。`LEDGER_INVALID:*` は例外。遅れた checkpoint は caller が明示に許す時だけ状態として返す。"""
        records = self._read_records()
        summary = verify_chain(records)
        checkpoint = self._read_checkpoint()
        checkpoint_class = classify_checkpoint(records, checkpoint)
        if checkpoint_class.startswith("LEDGER_INVALID:"):
            raise LedgerError(checkpoint_class.split(":", 1)[1])
        if checkpoint_class == CHECKPOINT_STALE and not allow_stale_checkpoint:
            raise LedgerError("CHECKPOINT_STALE")
        return LedgerState(records=records, summary=summary, checkpoint=checkpoint, checkpoint_class=checkpoint_class)

    def append(self, record: LedgerRecord) -> LedgerState:
        """検証済みの head の直後に 1 record を追記し、checkpoint を置換する。戻りは追記後の検証済みの状態。"""
        if not isinstance(record, LedgerRecord):
            raise AutomationError("SCHEMA_INVALID", "RECORD_TYPE")
        state = self.open_verified()
        if record.sequence != state.summary.record_count or record.previous_record_digest != state.summary.head_digest:
            raise LedgerError("APPEND_NOT_AT_HEAD", record.sequence)
        verify_chain((*state.records, record))                                         # 遷移の合法性も追記の前に
        ensure_root_subdirectory(self._root, LEDGER_DIRECTORY)
        append_line(self.ledger_file, record.to_json())
        self.write_checkpoint((*state.records, record))
        return self.open_verified()

    def write_checkpoint(self, records: Tuple[LedgerRecord, ...]) -> HeadCheckpoint:
        checkpoint = HeadCheckpoint.of(records)
        replace_atomically(self.checkpoint_file, checkpoint.to_bytes())
        return checkpoint


__all__ = ["CHECKPOINT_FILE_NAME", "CHECKPOINT_OK", "LEDGER_DIRECTORY", "LEDGER_FILE_NAME", "LedgerState", "LedgerStore"]
