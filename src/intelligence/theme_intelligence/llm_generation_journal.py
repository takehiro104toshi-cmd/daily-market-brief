"""P6-B7E — 生成監査 journal（追記専用。OPERATIONAL / AUDIT。**意味の authority ではない**）。

`<data_root>/theme_intelligence/llm_generation_records.jsonl` に `LlmGenerationAuditRecord` の canonical 行だけを追記する。
B7E で唯一の書き込み面であり、Theme / evidence / relation / governance / B3 / B5C / review の journal には書かない。

- journal は次回の生成入力にも evidence にもならない（`JOURNAL_IS_NOT_INPUT`）。読み手は監査だけ。
- raw prompt・raw response・本文・推論過程・資格情報を保存しない（record 自体がそれらの欄を持たない）。

規律（P5 / Foundation / B3 / B5B / B5C / B6D の store idiom を継承）: 明示 data_root、canonical 行のみ追記、
write → flush → fsync、同 attempt ＋ byte 一致 ＝ 冪等（ALREADY_PRESENT）、同 attempt ＋ 異 bytes ＝ CONFLICT、
破損 / 非 canonical / 切断 / 空行 / 未知 field / 未対応 schema は fail closed、読み飛ばさない、修復しない、
外部変更は byte 長で検知（single writer）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from .llm_generation_model import (GenerationModelError, LlmGenerationAuditRecord, canonical_audit_line)

GENERATION_DIRNAME = "theme_intelligence"
GENERATION_RECORDS_FILENAME = "llm_generation_records.jsonl"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
CORRUPTION_REASONS: Tuple[str, ...] = ("JOURNAL_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "MALFORMED_JSON", "NOT_AN_OBJECT", "INVALID_RECORD", "UNSUPPORTED_SCHEMA_VERSION",
                                       "NON_CANONICAL_LINE", "PHYSICAL_DUPLICATE_IDENTICAL",
                                       "PHYSICAL_DUPLICATE_CONFLICTING")


class JournalFailureCategory(str, Enum):
    JOURNAL_CORRUPTION = "JOURNAL_CORRUPTION"
    JOURNAL_REJECTED = "JOURNAL_REJECTED"
    JOURNAL_CONFLICT = "JOURNAL_CONFLICT"
    JOURNAL_CONCURRENT_MODIFICATION = "JOURNAL_CONCURRENT_MODIFICATION"


class GenerationJournalError(RuntimeError):
    category = JournalFailureCategory.JOURNAL_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class GenerationJournalCorrupt(GenerationJournalError):
    category = JournalFailureCategory.JOURNAL_CORRUPTION


class GenerationJournalRejected(GenerationJournalError):
    category = JournalFailureCategory.JOURNAL_REJECTED


class GenerationJournalConflict(GenerationJournalError):
    category = JournalFailureCategory.JOURNAL_CONFLICT

    def __init__(self, attempt_id: str) -> None:
        super().__init__("CONFLICT", f"{attempt_id} exists with different canonical bytes")


class GenerationJournalConcurrentModification(GenerationJournalError):
    category = JournalFailureCategory.JOURNAL_CONCURRENT_MODIFICATION

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__("CONCURRENT_MODIFICATION", f"the journal changed outside this writer ({expected} -> {actual})")


class JournalAppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class JournalAppendResult:
    attempt_id: str
    status: JournalAppendStatus


@dataclass(frozen=True)
class _Entry:
    line_number: int
    line: str
    record: LlmGenerationAuditRecord


def generation_dir(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    return Path(data_root) / GENERATION_DIRNAME


def generation_journal_path(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    return generation_dir(data_root) / GENERATION_RECORDS_FILENAME


class LlmGenerationJournal:
    """生成監査 record の追記専用 journal。authority の journal には一切書かない。"""

    def __init__(self, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False,
                 _create: bool = False) -> None:
        if data_root is None or str(data_root).strip() == "":
            raise GenerationJournalRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
        self.data_root = Path(data_root)
        self.read_only = read_only
        self.path = generation_journal_path(self.data_root)
        self._entries: Dict[str, _Entry] = {}
        self._expected_size = 0
        if _create:
            generation_dir(self.data_root).mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                with self.path.open("a", encoding=ENCODING):
                    pass
        self.reload()

    @classmethod
    def initialize(cls, data_root: Union[str, "os.PathLike[str]"]) -> "LlmGenerationJournal":
        return cls(data_root, _create=True)

    @classmethod
    def open_journal(cls, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False
                     ) -> "LlmGenerationJournal":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（strict。読み飛ばさない・修復しない）

    def reload(self) -> int:
        self._entries = {}
        self._expected_size = 0
        if not self.path.exists():
            raise GenerationJournalCorrupt("JOURNAL_MISSING", f"{GENERATION_RECORDS_FILENAME} is missing")
        raw = self.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise GenerationJournalCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise GenerationJournalCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                           line_number=text.count(LINE_TERMINATOR) + 1)
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            record = self._parse_line(line, line_number)
            previous = self._entries.get(record.attempt_id)
            if previous is not None:
                reason = "PHYSICAL_DUPLICATE_IDENTICAL" if previous.line == line else "PHYSICAL_DUPLICATE_CONFLICTING"
                raise GenerationJournalCorrupt(reason, f"{record.attempt_id} first seen at line {previous.line_number}",
                                               line_number=line_number)
            self._entries[record.attempt_id] = _Entry(line_number, line, record)
        self._expected_size = len(raw)
        return len(self._entries)

    @staticmethod
    def _parse_line(line: str, line_number: int) -> LlmGenerationAuditRecord:
        if line.strip() == "":
            raise GenerationJournalCorrupt("BLANK_LINE", "blank line", line_number=line_number)
        try:
            payload = json.loads(line)
        except ValueError:
            raise GenerationJournalCorrupt("MALFORMED_JSON", "line is not JSON", line_number=line_number) from None
        if not isinstance(payload, dict):
            raise GenerationJournalCorrupt("NOT_AN_OBJECT", "line is not a JSON object", line_number=line_number)
        try:
            record = LlmGenerationAuditRecord.from_dict(payload)
        except GenerationModelError as exc:
            reason = "UNSUPPORTED_SCHEMA_VERSION" if exc.code == "UNSUPPORTED_SCHEMA_VERSION" else "INVALID_RECORD"
            raise GenerationJournalCorrupt(reason, exc.code, line_number=line_number) from None
        except (TypeError, ValueError, KeyError):
            raise GenerationJournalCorrupt("INVALID_RECORD", "the record is malformed", line_number=line_number) from None
        if canonical_audit_line(record) != line:
            raise GenerationJournalCorrupt("NON_CANONICAL_LINE", "line is not the canonical serialization of its record",
                                           line_number=line_number)
        return record

    def revalidate(self) -> int:
        """journal 全体を読み直して検証する（生成の前に呼ぶ。使えない journal では生成しない）。"""
        return self.reload()

    # ------------------------------------------------------------ 追記（生成監査 record だけ）

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.exists() else -1
        if actual != self._expected_size:
            raise GenerationJournalConcurrentModification(self._expected_size, actual)

    def append(self, record: LlmGenerationAuditRecord) -> JournalAppendResult:
        if not isinstance(record, LlmGenerationAuditRecord):
            raise GenerationJournalRejected("INVALID_TYPE", "the journal takes a generation audit record")
        if self.read_only:
            raise GenerationJournalRejected("READ_ONLY", "journal was opened read-only")
        self.verify_unchanged()
        line = canonical_audit_line(record)
        existing = self._entries.get(record.attempt_id)
        if existing is not None:
            if existing.line == line:
                return JournalAppendResult(record.attempt_id, JournalAppendStatus.ALREADY_PRESENT)
            raise GenerationJournalConflict(record.attempt_id)
        data = line.encode(ENCODING)
        with self.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._expected_size += len(data)
        self._entries[record.attempt_id] = _Entry(len(self._entries) + 1, line, record)
        return JournalAppendResult(record.attempt_id, JournalAppendStatus.APPENDED)

    # ------------------------------------------------------------ 監査の読み取り（生成入力には使わない）

    def count(self) -> int:
        return len(self._entries)

    def canonical_lines(self) -> Tuple[str, ...]:
        return tuple(entry.line for entry in self._entries.values())

    def records(self) -> Tuple[LlmGenerationAuditRecord, ...]:
        return tuple(entry.record for entry in self._entries.values())

    def get(self, attempt_id: str) -> Optional[LlmGenerationAuditRecord]:
        entry = self._entries.get(attempt_id)
        return entry.record if entry else None


__all__ = ["CORRUPTION_REASONS", "GENERATION_DIRNAME", "GENERATION_RECORDS_FILENAME", "GenerationJournalConcurrentModification",
           "GenerationJournalConflict", "GenerationJournalCorrupt", "GenerationJournalError",
           "GenerationJournalRejected", "JournalAppendResult", "JournalAppendStatus", "JournalFailureCategory",
           "LlmGenerationJournal", "WRITER_GUARANTEE", "generation_dir", "generation_journal_path"]
