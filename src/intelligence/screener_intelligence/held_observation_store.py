"""P8-ST1 — 保留の観測の追記専用の運用 store（`<data_root>/screener_intelligence/held_observations.jsonl` の 1 file）。

`HeldObservation` だけを受け付ける。A2 の観測 ・A1 の identity ・A2R の注記 ・指標は受け付けず、それらの store に何も書かない
（authority ではない ・自動の昇格 ・再試行 ・削除は無い。監督の決定 D3）。

規律（A1 ／ A2 ／ A1R ／ 注記の store と同じ）: 明示の data_root、正準の行だけを append、write → flush → fsync、同じ record（byte 一致）は
収束、同じ id で内容（`audit_note`）が違う append は `HELD_CONTENT_CONFLICT` で拒否、破損 ／ 非正準 ／ 切断 ／ 物理的な重複は fail closed
（読み飛ばさない ・修復しない ・消さない）、外部の変更は byte 長で検知（single writer）。SQLite ・索引 ・cache ・時計 ・network は無い。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .held_observation_model import (HELD_RECORD_KIND, OPERATIONAL_HOLD_RECORD, HeldObservation,
                                     HeldObservationModelError, is_held_observation)

HELD_DIRNAME = "screener_intelligence"
HELD_FILENAME = "held_observations.jsonl"
STORE_RULES_VERSION = "p8_held_observation_store:0.1.0"
AUTHORITY_CLASS = OPERATIONAL_HOLD_RECORD
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
CORRUPTION_REASONS: Tuple[str, ...] = ("STORE_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "INVALID_RECORD", "NON_CANONICAL_LINE", "PHYSICAL_DUPLICATE")


class HeldFailureCategory(str, Enum):
    STORE_MISSING = "STORE_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class HeldStoreError(RuntimeError):
    category = HeldFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class HeldStoreMissing(HeldStoreError):
    category = HeldFailureCategory.STORE_MISSING


class HeldStoreCorrupt(HeldStoreError):
    category = HeldFailureCategory.STORE_CORRUPTION


class HeldAppendRejected(HeldStoreError):
    category = HeldFailureCategory.APPEND_REJECTED


class HeldConcurrentModification(HeldStoreError):
    category = HeldFailureCategory.CONCURRENT_MODIFICATION


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    record_id: str
    status: AppendStatus


def parse_held_line(line: str) -> HeldObservation:
    """正準の 1 行 → record（往復で byte 一致しなければ拒む）。"""
    if not isinstance(line, str) or not line.endswith(LINE_TERMINATOR):
        raise HeldObservationModelError("INVALID_RECORD", "line")
    try:
        data = json.loads(line)
    except ValueError:
        raise HeldObservationModelError("INVALID_RECORD", "json") from None
    if not isinstance(data, dict) or data.get("record_kind") != HELD_RECORD_KIND:
        raise HeldObservationModelError("INVALID_RECORD", "record_kind")
    record = HeldObservation.from_dict(data)
    if record.canonical_line() != line:
        raise HeldObservationModelError("NON_CANONICAL_LINE", "line")
    return record


def held_path(data_root: Any) -> Path:
    if data_root is None or str(data_root).strip() == "":
        raise HeldAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
    return Path(data_root) / HELD_DIRNAME / HELD_FILENAME


class HeldObservationStore:
    """保留の観測の運用 store（追記専用）。読むたびに全行を検査する。A2 ・A1 ・注記 ・指標には触れない。"""

    def __init__(self, data_root: Any, *, read_only: bool = False, _create: bool = False) -> None:
        self.path = held_path(data_root)
        self.data_root = data_root
        self.read_only = read_only
        if _create and not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab"):
                pass
        self._records: List[HeldObservation] = []
        self._lines: Dict[str, str] = {}
        self._ordered_lines: Tuple[str, ...] = ()
        self._expected_size = 0
        self.reload()

    @classmethod
    def initialize(cls, data_root: Any) -> "HeldObservationStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Any, *, read_only: bool = False) -> "HeldObservationStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（fail closed。修復しない）

    def reload(self) -> int:
        if not self.path.is_file():
            raise HeldStoreMissing("STORE_MISSING", f"{HELD_FILENAME} is missing")
        journal_bytes = self.path.read_bytes()
        try:
            text = journal_bytes.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise HeldStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise HeldStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                   line_number=text.count(LINE_TERMINATOR) + 1)
        records: List[HeldObservation] = []
        by_id: Dict[str, str] = {}
        for line_number, line_body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = line_body + LINE_TERMINATOR
            if line_body.strip() == "":
                raise HeldStoreCorrupt("BLANK_LINE", "blank line", line_number=line_number)
            try:
                record = parse_held_line(line)
            except HeldObservationModelError as exc:
                raise HeldStoreCorrupt("INVALID_RECORD" if exc.code != "NON_CANONICAL_LINE" else exc.code, exc.code,
                                       line_number=line_number) from None
            if record.record_id in by_id:
                raise HeldStoreCorrupt("PHYSICAL_DUPLICATE", "record already present", line_number=line_number)
            records.append(record)
            by_id[record.record_id] = line
        self._records, self._lines = records, by_id
        self._ordered_lines, self._expected_size = tuple(by_id[r.record_id] for r in records), len(journal_bytes)
        return len(records)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.is_file() else -1
        if actual != self._expected_size:
            raise HeldConcurrentModification("CONCURRENT_MODIFICATION", "store changed outside this writer")

    def append(self, record: Any) -> AppendResult:
        if self.read_only:
            raise HeldAppendRejected("READ_ONLY", "store was opened read-only")
        if not is_held_observation(record):
            raise HeldAppendRejected("INVALID_TYPE", "only HeldObservation records can be appended")
        self.verify_unchanged()
        line = record.canonical_line()
        existing = self._lines.get(record.record_id)
        if existing is not None:
            if existing != line:
                raise HeldAppendRejected("HELD_CONTENT_CONFLICT", "same id with different content")
            return AppendResult(record.record_id, AppendStatus.ALREADY_PRESENT)
        data = line.encode(ENCODING)
        with self.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._expected_size += len(data)
        self._records.append(record)
        self._lines[record.record_id] = line
        self._ordered_lines = self._ordered_lines + (line,)
        return AppendResult(record.record_id, AppendStatus.APPENDED)

    # ------------------------------------------------------------ read

    def records(self) -> Tuple[HeldObservation, ...]:
        return tuple(self._records)

    def get(self, record_id: str) -> Optional[HeldObservation]:
        for record in self._records:
            if record.record_id == record_id:
                return record
        return None

    def canonical_lines(self) -> Tuple[str, ...]:
        return self._ordered_lines

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for record in self._records:
            for reason in record.reasons:
                counts[reason.value] = counts.get(reason.value, 0) + 1
        return counts


__all__ = ["AUTHORITY_CLASS", "AppendResult", "AppendStatus", "CORRUPTION_REASONS", "ENCODING", "HELD_DIRNAME",
           "HELD_FILENAME", "STORE_RULES_VERSION", "HeldAppendRejected", "HeldConcurrentModification",
           "HeldFailureCategory", "HeldObservationStore", "HeldStoreCorrupt", "HeldStoreError", "HeldStoreMissing",
           "WRITER_GUARANTEE", "held_path", "parse_held_line"]
