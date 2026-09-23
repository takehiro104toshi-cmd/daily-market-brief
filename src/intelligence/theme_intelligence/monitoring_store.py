"""P6-B6D — 人間の review 状態だけを保持する追記専用 operational store。

**governance authority ではない。** ここに入るのは「人間がこの finding を見て、どう扱ったか」だけであり、
Theme / evidence / proposal / relation について何かを決めたことではない。後者が必要になった時点で、
それは B3 / B5C の提案と決定 authority を通らなければならない。

`MonitoringFinding` は永続化しない（B6A Option C）。finding は authority ＋ knowledge version ＋ ruleset ＋
cutoff から常に再導出できるため、保存すると再導出結果との食い違いが「どちらが正か」を生み、
事実上 B6 に authority を与えてしまう。

規律（P5 / Foundation / B3 / B5B / B5C を継承）: 明示 data_root、canonical 行のみ append、write → flush → fsync、
同 id ＋ byte 一致 ＝ 冪等、同 id ＋ 異 bytes ＝ CONFLICT、破損 / 非 canonical / 切断行は fail closed、
読み飛ばさない、修復しない、migration しない、外部変更は byte 長で検知（single writer）。

chain の解決は B6B の `resolve_review_state` だけが行う。本 store は独自の latest-wins を持たない。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple, Union

from .monitoring_model import (REVIEW_ITEM_STATE_SCHEMA_VERSION, MonitoringModelError, ReviewItemState,
                               canonical_monitoring_line, parse_monitoring_record)

MONITORING_DIRNAME = "theme_intelligence"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
REVIEW_STATE_FILENAME = "monitoring_review_states.jsonl"
AUTHORITY_FILENAMES: Mapping[str, str] = {"review_states": REVIEW_STATE_FILENAME}
CORRUPTION_REASONS: Tuple[str, ...] = ("AUTHORITY_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "MALFORMED_JSON", "NOT_AN_OBJECT", "INVALID_RECORD", "UNSUPPORTED_SCHEMA_VERSION",
                                       "NON_CANONICAL_LINE", "WRONG_AUTHORITY", "PHYSICAL_DUPLICATE_IDENTICAL",
                                       "PHYSICAL_DUPLICATE_CONFLICTING")
HISTORY_REASONS: Tuple[str, ...] = ("MISSING_PREDECESSOR", "CROSS_FINDING_PREDECESSOR", "NOT_TERMINAL_PREDECESSOR",
                                    "NON_MONOTONIC_RECORDED_AT", "INVALID_TYPE")


class ReviewFailureCategory(str, Enum):
    STORE_CORRUPTION = "STORE_CORRUPTION"
    INVALID_HISTORY = "INVALID_HISTORY"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONFLICT = "CONFLICT"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class ReviewStoreError(RuntimeError):
    category = ReviewFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class ReviewStoreCorrupt(ReviewStoreError):
    category = ReviewFailureCategory.STORE_CORRUPTION


class ReviewInvalidHistory(ReviewStoreError):
    category = ReviewFailureCategory.INVALID_HISTORY


class ReviewAppendRejected(ReviewStoreError):
    category = ReviewFailureCategory.APPEND_REJECTED


class ReviewConflict(ReviewStoreError):
    category = ReviewFailureCategory.CONFLICT

    def __init__(self, record_id: str) -> None:
        super().__init__("CONFLICT", f"{record_id} exists with different canonical bytes")


class ReviewConcurrentModification(ReviewStoreError):
    category = ReviewFailureCategory.CONCURRENT_MODIFICATION

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__("CONCURRENT_MODIFICATION", f"the journal changed outside this writer ({expected} -> {actual})")


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    record_id: str
    status: AppendStatus


@dataclass(frozen=True)
class _Entry:
    line_number: int
    line: str
    record: ReviewItemState


def monitoring_dir(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    return Path(data_root) / MONITORING_DIRNAME


def review_state_path(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    return monitoring_dir(data_root) / REVIEW_STATE_FILENAME


class MonitoringReviewStore:
    """人間の review 状態の追記専用 journal。Theme / proposal / relation の authority には一切書かない。"""

    def __init__(self, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False,
                 _create: bool = False) -> None:
        if data_root is None or str(data_root).strip() == "":
            raise ReviewAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
        self.data_root = Path(data_root)
        self.read_only = read_only
        self.path = review_state_path(self.data_root)
        self._entries: Dict[str, _Entry] = {}
        self._children: Dict[str, List[str]] = {}
        self._expected_size = 0
        if _create:
            monitoring_dir(self.data_root).mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                with self.path.open("a", encoding=ENCODING):
                    pass
        self.reload()

    @classmethod
    def initialize(cls, data_root: Union[str, "os.PathLike[str]"]) -> "MonitoringReviewStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False) -> "MonitoringReviewStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load

    def reload(self) -> int:
        self._entries = {}
        self._children = {}
        self._expected_size = 0
        if not self.path.exists():
            raise ReviewStoreCorrupt("AUTHORITY_MISSING", f"{REVIEW_STATE_FILENAME} is missing")
        raw = self.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise ReviewStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise ReviewStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                     line_number=text.count(LINE_TERMINATOR) + 1)
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            record = self._parse_line(line, line_number)
            previous = self._entries.get(record.review_state_id)
            if previous is not None:
                reason = "PHYSICAL_DUPLICATE_IDENTICAL" if previous.line == line else "PHYSICAL_DUPLICATE_CONFLICTING"
                raise ReviewStoreCorrupt(reason, f"{record.review_state_id} first seen at line {previous.line_number}",
                                         line_number=line_number)
            self._validate(record, for_append=False, line_number=line_number)
            self._entries[record.review_state_id] = _Entry(line_number, line, record)
            self._index(record)
        self._expected_size = len(raw)
        return len(self._entries)

    def _parse_line(self, line: str, line_number: int) -> ReviewItemState:
        if line.strip() == "":
            raise ReviewStoreCorrupt("BLANK_LINE", "blank line", line_number=line_number)
        try:
            payload = json.loads(line)
        except ValueError:
            raise ReviewStoreCorrupt("MALFORMED_JSON", "line is not JSON", line_number=line_number) from None
        if not isinstance(payload, dict):
            raise ReviewStoreCorrupt("NOT_AN_OBJECT", "line is not a JSON object", line_number=line_number)
        try:
            record = parse_monitoring_record(payload)
        except MonitoringModelError as exc:
            reason = "UNSUPPORTED_SCHEMA_VERSION" if exc.code == "UNSUPPORTED_SCHEMA_VERSION" else "INVALID_RECORD"
            raise ReviewStoreCorrupt(reason, str(exc), line_number=line_number) from None
        except Exception as exc:
            raise ReviewStoreCorrupt("INVALID_RECORD", str(exc), line_number=line_number) from None
        if not isinstance(record, ReviewItemState):
            raise ReviewStoreCorrupt("WRONG_AUTHORITY", f"{record.schema_version} does not belong to this journal",
                                     line_number=line_number)
        if canonical_monitoring_line(record) != line:
            raise ReviewStoreCorrupt("NON_CANONICAL_LINE", "line is not the canonical serialization of its record",
                                     line_number=line_number)
        return record

    def _index(self, record: ReviewItemState) -> None:
        if record.supersedes_review_state_id:
            self._children.setdefault(record.supersedes_review_state_id, []).append(record.review_state_id)

    # ------------------------------------------------------------ validation

    @staticmethod
    def _reject(for_append: bool, code: str, detail: str, *, line_number: int = 0):
        if for_append:
            raise ReviewAppendRejected(code, detail)
        raise ReviewInvalidHistory(code, detail, line_number=line_number)

    def _validate(self, record: ReviewItemState, for_append: bool, line_number: int = 0) -> None:
        """構造規律のみ。どの記録が「現在の処理」かは `resolve_review_state` だけが答える。"""
        if record.supersedes_review_state_id == "":
            return
        predecessor = self._entries.get(record.supersedes_review_state_id)
        if predecessor is None:
            self._reject(for_append, "MISSING_PREDECESSOR", f"{record.supersedes_review_state_id} is not stored",
                         line_number=line_number)
        if predecessor.record.finding_id != record.finding_id:
            self._reject(for_append, "CROSS_FINDING_PREDECESSOR", "the predecessor reviews another finding",
                         line_number=line_number)
        if record.recorded_at < predecessor.record.recorded_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT",
                         "a review cannot precede the one it supersedes", line_number=line_number)
        if self._children.get(record.supersedes_review_state_id):
            self._reject(for_append, "NOT_TERMINAL_PREDECESSOR", "a review history does not fork",
                         line_number=line_number)

    # ------------------------------------------------------------ append（人間の明示的な行為だけ）

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.exists() else -1
        if actual != self._expected_size:
            raise ReviewConcurrentModification(self._expected_size, actual)

    def append_review_state(self, record: ReviewItemState) -> AppendResult:
        """**人間が明示的に行った review だけ**をここへ通す。monitoring run はこの API を呼ばない。"""
        if not isinstance(record, ReviewItemState):
            raise ReviewAppendRejected("INVALID_TYPE", "append_review_state takes a ReviewItemState")
        if self.read_only:
            raise ReviewAppendRejected("READ_ONLY", "store was opened read-only")
        self.verify_unchanged()
        line = canonical_monitoring_line(record)
        existing = self._entries.get(record.review_state_id)
        if existing is not None:
            if existing.line == line:
                return AppendResult(record.review_state_id, AppendStatus.ALREADY_PRESENT)
            raise ReviewConflict(record.review_state_id)
        self._validate(record, for_append=True)
        data = line.encode(ENCODING)
        with self.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._expected_size += len(data)
        self._entries[record.review_state_id] = _Entry(len(self._entries) + 1, line, record)
        self._index(record)
        return AppendResult(record.review_state_id, AppendStatus.APPENDED)

    # ------------------------------------------------------------ read

    def count(self) -> int:
        return len(self._entries)

    def canonical_lines(self) -> Tuple[str, ...]:
        return tuple(entry.line for entry in self._entries.values())

    def review_states(self) -> Tuple[ReviewItemState, ...]:
        return tuple(entry.record for entry in self._entries.values())

    def states_for(self, finding_id: str) -> Tuple[ReviewItemState, ...]:
        return tuple(sorted((entry.record for entry in self._entries.values()
                             if entry.record.finding_id == finding_id),
                            key=lambda record: record.review_state_id))

    def get(self, review_state_id: str) -> Optional[ReviewItemState]:
        entry = self._entries.get(review_state_id)
        return entry.record if entry else None


__all__ = ["AUTHORITY_FILENAMES", "AppendResult", "AppendStatus", "CORRUPTION_REASONS", "HISTORY_REASONS",
           "MONITORING_DIRNAME", "MonitoringReviewStore", "REVIEW_STATE_FILENAME", "ReviewAppendRejected",
           "ReviewConcurrentModification", "ReviewConflict", "ReviewFailureCategory", "ReviewInvalidHistory",
           "ReviewStoreCorrupt", "ReviewStoreError", "WRITER_GUARANTEE", "monitoring_dir", "review_state_path"]
