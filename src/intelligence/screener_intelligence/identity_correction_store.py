"""P8-A1R — identity の訂正の追記専用 store（`<data_root>/screener_intelligence/identity_corrections.jsonl` の 1 file）。

A1 の identity の journal とは別の file にする: 凍結の A1 の store は A1 の record 以外を受け付けず（同じ file に訂正を足すと
A1 の読み込みが破損として止まる）、A1 の journal は A1 の再生のためにそのまま保つ。訂正は A1 の journal を読んで検査するが、
A1 の journal に書かない。

規律は A1 と同じ: 明示の data_root、正準の行だけを append、write → flush → fsync、同じ訂正（byte 一致）は収束、訂正の鎖の
違反は拒否、破損 ／ 非正準 ／ 切断 ／ 物理的な重複 ／ 鎖の違反 ／ A1 の authority の欠落 ／ 破損は fail closed（読み飛ばさない・
修復しない・消さない）、外部の変更は byte 長で検知（single writer）。SQLite ・索引 ・cache は持たない。read-only で開いたら
何も書かない。エラーの文には file 名と行番号だけを入れる。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .identity_correction_model import (CorrectionHistory, CorrectionHistoryError, CorrectionModelError,
                                        IdentityCorrection, parse_correction_line)
from .identity_store import IDENTITY_DIRNAME, IdentityAuthorityMissing, IdentityStoreCorrupt, open_identity_history

CORRECTION_FILENAME = "identity_corrections.jsonl"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
CORRUPTION_REASONS: Tuple[str, ...] = ("CORRECTIONS_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE",
                                       "BLANK_LINE", "INVALID_RECORD", "PHYSICAL_DUPLICATE", "INVALID_HISTORY")


class CorrectionFailureCategory(str, Enum):
    AUTHORITY_MISSING = "AUTHORITY_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class CorrectionStoreError(RuntimeError):
    category = CorrectionFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class CorrectionAuthorityMissing(CorrectionStoreError):
    category = CorrectionFailureCategory.AUTHORITY_MISSING


class CorrectionStoreCorrupt(CorrectionStoreError):
    category = CorrectionFailureCategory.STORE_CORRUPTION


class CorrectionAppendRejected(CorrectionStoreError):
    category = CorrectionFailureCategory.APPEND_REJECTED


class CorrectionConcurrentModification(CorrectionStoreError):
    category = CorrectionFailureCategory.CONCURRENT_MODIFICATION


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    record_id: str
    status: AppendStatus


def correction_path(data_root: Any) -> Path:
    if data_root is None or str(data_root).strip() == "":
        raise CorrectionAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
    return Path(data_root) / IDENTITY_DIRNAME / CORRECTION_FILENAME


def _identity(data_root: Any):
    """A1 の authority を read-only で開く（欠落 ／ 破損は訂正の store の失敗として返す。空の authority にしない）。"""
    try:
        return open_identity_history(data_root)
    except IdentityAuthorityMissing as exc:
        raise CorrectionAuthorityMissing(f"IDENTITY_{exc.code}", exc.detail) from None
    except IdentityStoreCorrupt as exc:
        raise CorrectionStoreCorrupt(f"IDENTITY_{exc.code}", exc.detail, line_number=exc.line_number) from None


class CorrectionStore:
    """訂正の authority（追記専用）。読むたびに全行を A1 の authority に対して検査し、検証済みの `CorrectionHistory` を持つ。"""

    def __init__(self, data_root: Any, *, read_only: bool = False, _create: bool = False) -> None:
        self.data_root = data_root
        self.path = correction_path(data_root)
        self.read_only = read_only
        if _create:
            _identity(data_root)                                   # A1 の authority が先に在ること
            if not self.path.exists():
                with self.path.open("ab"):
                    pass
        self._history: Optional[CorrectionHistory] = None
        self._lines: Tuple[str, ...] = ()
        self._expected_size = 0
        self.reload()

    @classmethod
    def initialize(cls, data_root: Any) -> "CorrectionStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Any, *, read_only: bool = False) -> "CorrectionStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（fail closed。修復しない）

    def reload(self) -> int:
        identity = _identity(self.data_root)
        if not self.path.is_file():
            raise CorrectionAuthorityMissing("CORRECTIONS_MISSING", f"{CORRECTION_FILENAME} is missing")
        raw = self.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise CorrectionStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise CorrectionStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                         line_number=text.count(LINE_TERMINATOR) + 1)
        history = CorrectionHistory(identity)
        lines = []
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            if body.strip() == "":
                raise CorrectionStoreCorrupt("BLANK_LINE", "blank line", line_number=line_number)
            try:
                correction = parse_correction_line(line)
            except CorrectionModelError as exc:
                raise CorrectionStoreCorrupt("INVALID_RECORD", exc.code, line_number=line_number) from None
            if history.contains(correction.record_id):
                raise CorrectionStoreCorrupt("PHYSICAL_DUPLICATE", "record already present", line_number=line_number)
            try:
                history.add(correction)
            except CorrectionHistoryError as exc:
                raise CorrectionStoreCorrupt("INVALID_HISTORY", exc.code, line_number=line_number) from None
            lines.append(line)
        self._history, self._lines, self._expected_size = history, tuple(lines), len(raw)
        return len(lines)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.is_file() else -1
        if actual != self._expected_size:
            raise CorrectionConcurrentModification("CONCURRENT_MODIFICATION", "corrections changed outside this writer")

    def append(self, correction: Any) -> AppendResult:
        if self.read_only:
            raise CorrectionAppendRejected("READ_ONLY", "store was opened read-only")
        if not isinstance(correction, IdentityCorrection):
            raise CorrectionAppendRejected("INVALID_TYPE", "only identity corrections can be appended")
        self.verify_unchanged()
        try:
            history = CorrectionHistory(_identity(self.data_root), self._history.records)   # 最新の A1 に対して
        except CorrectionHistoryError as exc:
            raise CorrectionAppendRejected(exc.code, exc.detail) from None
        if history.contains(correction.record_id):
            return AppendResult(correction.record_id, AppendStatus.ALREADY_PRESENT)
        try:
            history.check_against_all(correction)
        except CorrectionHistoryError as exc:
            raise CorrectionAppendRejected(exc.code, exc.detail) from None
        line = correction.canonical_line()
        data = line.encode(ENCODING)
        with self.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._expected_size += len(data)
        history.add(correction)
        self._history = history
        self._lines = self._lines + (line,)
        return AppendResult(correction.record_id, AppendStatus.APPENDED)

    # ------------------------------------------------------------ read

    @property
    def history(self) -> CorrectionHistory:
        return self._history

    def records(self) -> Tuple[IdentityCorrection, ...]:
        return self._history.records

    def canonical_lines(self) -> Tuple[str, ...]:
        return self._lines

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for correction in self._history.records:
            counts[correction.action.value] = counts.get(correction.action.value, 0) + 1
        return counts


def open_correction_history(data_root: Any) -> CorrectionHistory:
    """read-only で開いて検証済みの訂正の履歴を返す（何も書かない）。欠落 ／ 破損は例外のまま（呼び手が status にする）。"""
    return CorrectionStore.open(data_root, read_only=True).history


__all__ = ["AppendResult", "AppendStatus", "CORRECTION_FILENAME", "CORRUPTION_REASONS", "CorrectionAppendRejected",
           "CorrectionAuthorityMissing", "CorrectionConcurrentModification", "CorrectionFailureCategory",
           "CorrectionStore", "CorrectionStoreCorrupt", "CorrectionStoreError", "ENCODING", "WRITER_GUARANTEE",
           "correction_path", "open_correction_history"]
