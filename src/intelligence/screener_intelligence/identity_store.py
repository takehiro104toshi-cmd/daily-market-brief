"""P8-A1 — identity の authority の追記専用 store（`<data_root>/screener_intelligence/identity_records.jsonl` の 1 file）。

規律（Phase 5 ／ Phase 6 の store を継承）: 明示の data_root（既定の場所に fallback しない）、正準の行だけを append、
write → flush → fsync、同じ record（byte 一致）は収束、履歴の不変条件に反する append は拒否、破損 ／ 非正準 ／ 切断 ／
物理的な重複 ／ 履歴の違反は fail closed（読み飛ばさない・修復しない・migration しない）、外部の変更は byte 長で検知
（single writer）。SQLite ・索引 ・cache は持たない。read-only で開いたら何も書かない（directory ・file も作らない）。

エラーの文には file 名と行番号だけを入れ、path ・行の中身を入れない。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Tuple

from .identity_model import (IdentityHistory, IdentityHistoryError, IdentityModelError, is_identity_record,
                             parse_canonical_line)

IDENTITY_DIRNAME = "screener_intelligence"
IDENTITY_FILENAME = "identity_records.jsonl"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
CORRUPTION_REASONS: Tuple[str, ...] = ("AUTHORITY_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "INVALID_RECORD", "PHYSICAL_DUPLICATE", "INVALID_HISTORY")


class IdentityFailureCategory(str, Enum):
    AUTHORITY_MISSING = "AUTHORITY_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class IdentityStoreError(RuntimeError):
    category = IdentityFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class IdentityAuthorityMissing(IdentityStoreError):
    category = IdentityFailureCategory.AUTHORITY_MISSING


class IdentityStoreCorrupt(IdentityStoreError):
    category = IdentityFailureCategory.STORE_CORRUPTION


class IdentityAppendRejected(IdentityStoreError):
    category = IdentityFailureCategory.APPEND_REJECTED


class IdentityConcurrentModification(IdentityStoreError):
    category = IdentityFailureCategory.CONCURRENT_MODIFICATION


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    record_id: str
    status: AppendStatus


def identity_path(data_root: Any) -> Path:
    if data_root is None or str(data_root).strip() == "":
        raise IdentityAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
    return Path(data_root) / IDENTITY_DIRNAME / IDENTITY_FILENAME


class IdentityStore:
    """identity の authority（追記専用）。読むたびに全行を検査し、検証済みの `IdentityHistory` を持つ。"""

    def __init__(self, data_root: Any, *, read_only: bool = False, _create: bool = False) -> None:
        self.path = identity_path(data_root)
        self.read_only = read_only
        if _create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                with self.path.open("ab"):
                    pass
        self._history = IdentityHistory()
        self._lines: Tuple[str, ...] = ()
        self._expected_size = 0
        self.reload()

    @classmethod
    def initialize(cls, data_root: Any) -> "IdentityStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Any, *, read_only: bool = False) -> "IdentityStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（fail closed。修復しない）

    def reload(self) -> int:
        if not self.path.is_file():
            raise IdentityAuthorityMissing("AUTHORITY_MISSING", f"{IDENTITY_FILENAME} is missing")
        raw = self.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise IdentityStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise IdentityStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                       line_number=text.count(LINE_TERMINATOR) + 1)
        history = IdentityHistory()
        lines = []
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            if body.strip() == "":
                raise IdentityStoreCorrupt("BLANK_LINE", "blank line", line_number=line_number)
            try:
                record = parse_canonical_line(line)
            except IdentityModelError as exc:
                raise IdentityStoreCorrupt("INVALID_RECORD", exc.code, line_number=line_number) from None
            if history.contains(record.record_id):
                raise IdentityStoreCorrupt("PHYSICAL_DUPLICATE", "record already present", line_number=line_number)
            try:
                history.add(record)
            except IdentityHistoryError as exc:
                raise IdentityStoreCorrupt("INVALID_HISTORY", exc.code, line_number=line_number) from None
            lines.append(line)
        self._history, self._lines, self._expected_size = history, tuple(lines), len(raw)
        return len(lines)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.is_file() else -1
        if actual != self._expected_size:
            raise IdentityConcurrentModification("CONCURRENT_MODIFICATION", "authority changed outside this writer")

    def append(self, record: Any) -> AppendResult:
        if self.read_only:
            raise IdentityAppendRejected("READ_ONLY", "store was opened read-only")
        if not is_identity_record(record):
            raise IdentityAppendRejected("INVALID_TYPE", "only identity records can be appended")
        self.verify_unchanged()
        if self._history.contains(record.record_id):
            return AppendResult(record.record_id, AppendStatus.ALREADY_PRESENT)
        try:
            self._history.check(record)
        except IdentityHistoryError as exc:
            raise IdentityAppendRejected(exc.code, exc.detail) from None
        line = record.canonical_line()
        data = line.encode(ENCODING)
        with self.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._expected_size += len(data)
        self._history.add(record)
        self._lines = self._lines + (line,)
        return AppendResult(record.record_id, AppendStatus.APPENDED)

    # ------------------------------------------------------------ read

    @property
    def history(self) -> IdentityHistory:
        return self._history

    def records(self) -> Tuple[Any, ...]:
        return self._history.records

    def canonical_lines(self) -> Tuple[str, ...]:
        return self._lines

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for record in self._history.records:
            counts[record.KIND.value] = counts.get(record.KIND.value, 0) + 1
        return counts


def open_identity_history(data_root: Any) -> IdentityHistory:
    """read-only で開いて検証済みの履歴を返す（何も書かない）。破損 ／ 欠落は例外のまま（呼び手が status にする）。"""
    return IdentityStore.open(data_root, read_only=True).history


__all__ = ["AppendResult", "AppendStatus", "CORRUPTION_REASONS", "ENCODING", "IDENTITY_DIRNAME", "IDENTITY_FILENAME",
           "IdentityAppendRejected", "IdentityAuthorityMissing", "IdentityConcurrentModification",
           "IdentityFailureCategory", "IdentityStore", "IdentityStoreCorrupt", "IdentityStoreError",
           "WRITER_GUARANTEE", "identity_path", "open_identity_history"]
