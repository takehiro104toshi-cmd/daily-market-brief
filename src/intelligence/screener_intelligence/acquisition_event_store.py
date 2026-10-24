"""P8-ACQ0 — 取得 event の追記専用 store（`<data_root>/screener_intelligence/acquisition_events.jsonl` の 1 file）。

`AcquisitionEvent` だけを受け付ける。A1 ・A2 ・注記 ・保留の store には何も書かない（coverage ・観測 ・identity を作らない）。

規律（A1 ／ A2 ／ A1R ／ 注記 ／ 保留の store と同じ）: 明示の data_root、正準の行だけを append、write → flush → fsync、同じ record
（byte 一致）は `REUSED` で収束、同じ id で内容が違う append は `ACQUISITION_CONTENT_CONFLICT` で拒否、破損 ／ 非正準 ／ 切断 ／ 物理的な
重複は fail closed（読み飛ばさない ・修復しない ・消さない ・書き直さない ・圧縮しない）、外部の変更は byte 長で検知（single writer）。
SQLite ・索引 ・cache ・時計 ・network は無い。replay は保存した `acquired_at` を使う。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .acquisition_event_model import (ACQUISITION_EVIDENCE_RECORD, ACQUISITION_RECORD_KIND, AcquisitionEvent,
                                      AcquisitionModelError, is_acquisition_event)

ACQUISITION_DIRNAME = "screener_intelligence"
ACQUISITION_FILENAME = "acquisition_events.jsonl"
STORE_RULES_VERSION = "p8_acquisition_event_store:0.1.0"
AUTHORITY_CLASS = ACQUISITION_EVIDENCE_RECORD
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
CORRUPTION_REASONS: Tuple[str, ...] = ("STORE_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "INVALID_RECORD", "NON_CANONICAL_LINE", "PHYSICAL_DUPLICATE")


class AcquisitionFailureCategory(str, Enum):
    STORE_MISSING = "STORE_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class AcquisitionStoreError(RuntimeError):
    category = AcquisitionFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class AcquisitionStoreMissing(AcquisitionStoreError):
    category = AcquisitionFailureCategory.STORE_MISSING


class AcquisitionStoreCorrupt(AcquisitionStoreError):
    category = AcquisitionFailureCategory.STORE_CORRUPTION


class AcquisitionAppendRejected(AcquisitionStoreError):
    category = AcquisitionFailureCategory.APPEND_REJECTED


class AcquisitionConcurrentModification(AcquisitionStoreError):
    category = AcquisitionFailureCategory.CONCURRENT_MODIFICATION


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"


@dataclass(frozen=True)
class AppendResult:
    record_id: str
    status: AppendStatus


def parse_acquisition_line(line: str) -> AcquisitionEvent:
    """正準の 1 行 → record（往復で byte 一致しなければ拒む）。"""
    if not isinstance(line, str) or not line.endswith(LINE_TERMINATOR):
        raise AcquisitionModelError("INVALID_RECORD", "line")
    try:
        data = json.loads(line)
    except ValueError:
        raise AcquisitionModelError("INVALID_RECORD", "json") from None
    if not isinstance(data, dict) or data.get("record_kind") != ACQUISITION_RECORD_KIND:
        raise AcquisitionModelError("INVALID_RECORD", "record_kind")
    record = AcquisitionEvent.from_dict(data)
    if record.canonical_line() != line:
        raise AcquisitionModelError("NON_CANONICAL_LINE", "line")
    return record


def acquisition_path(data_root: Any) -> Path:
    if data_root is None or str(data_root).strip() == "":
        raise AcquisitionAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
    return Path(data_root) / ACQUISITION_DIRNAME / ACQUISITION_FILENAME


class AcquisitionEventStore:
    """取得 event の追記専用 store。読むたびに全行を検査する。A1 ・A2 ・注記 ・保留 ・指標には触れない。"""

    def __init__(self, data_root: Any, *, read_only: bool = False, _create: bool = False) -> None:
        self.path = acquisition_path(data_root)
        self.data_root = data_root
        self.read_only = read_only
        if _create and not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab"):
                pass
        self._records: List[AcquisitionEvent] = []
        self._lines: Dict[str, str] = {}
        self._ordered_lines: Tuple[str, ...] = ()
        self._expected_size = 0
        self.reload()

    @classmethod
    def initialize(cls, data_root: Any) -> "AcquisitionEventStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Any, *, read_only: bool = False) -> "AcquisitionEventStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（fail closed。修復しない）

    def reload(self) -> int:
        if not self.path.is_file():
            raise AcquisitionStoreMissing("STORE_MISSING", f"{ACQUISITION_FILENAME} is missing")
        journal_bytes = self.path.read_bytes()
        try:
            text = journal_bytes.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise AcquisitionStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise AcquisitionStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                          line_number=text.count(LINE_TERMINATOR) + 1)
        records: List[AcquisitionEvent] = []
        by_id: Dict[str, str] = {}
        for line_number, line_body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = line_body + LINE_TERMINATOR
            if line_body.strip() == "":
                raise AcquisitionStoreCorrupt("BLANK_LINE", "blank line", line_number=line_number)
            try:
                record = parse_acquisition_line(line)
            except AcquisitionModelError as exc:
                raise AcquisitionStoreCorrupt("INVALID_RECORD" if exc.code != "NON_CANONICAL_LINE" else exc.code,
                                              exc.code, line_number=line_number) from None
            if record.record_id in by_id:
                raise AcquisitionStoreCorrupt("PHYSICAL_DUPLICATE", "record already present", line_number=line_number)
            records.append(record)
            by_id[record.record_id] = line
        self._records, self._lines = records, by_id
        self._ordered_lines, self._expected_size = tuple(by_id[r.record_id] for r in records), len(journal_bytes)
        return len(records)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.is_file() else -1
        if actual != self._expected_size:
            raise AcquisitionConcurrentModification("CONCURRENT_MODIFICATION", "store changed outside this writer")

    def append(self, record: Any) -> AppendResult:
        if self.read_only:
            raise AcquisitionAppendRejected("READ_ONLY", "store was opened read-only")
        if not is_acquisition_event(record):
            raise AcquisitionAppendRejected("INVALID_TYPE", "only AcquisitionEvent records can be appended")
        self.verify_unchanged()
        line = record.canonical_line()
        existing = self._lines.get(record.record_id)
        if existing is not None:
            if existing != line:
                raise AcquisitionAppendRejected("ACQUISITION_CONTENT_CONFLICT", "same id with different content")
            return AppendResult(record.record_id, AppendStatus.REUSED)
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

    def records(self) -> Tuple[AcquisitionEvent, ...]:
        return tuple(self._records)

    def get(self, record_id: str) -> Optional[AcquisitionEvent]:
        for record in self._records:
            if record.record_id == record_id:
                return record
        return None

    def canonical_lines(self) -> Tuple[str, ...]:
        return self._ordered_lines

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for record in self._records:
            counts[record.status.value] = counts.get(record.status.value, 0) + 1
        return counts


__all__ = ["ACQUISITION_DIRNAME", "ACQUISITION_FILENAME", "AUTHORITY_CLASS", "AppendResult", "AppendStatus",
           "CORRUPTION_REASONS", "ENCODING", "STORE_RULES_VERSION", "WRITER_GUARANTEE", "AcquisitionAppendRejected",
           "AcquisitionConcurrentModification", "AcquisitionEventStore", "AcquisitionFailureCategory",
           "AcquisitionStoreCorrupt", "AcquisitionStoreError", "AcquisitionStoreMissing", "acquisition_path",
           "parse_acquisition_line"]
