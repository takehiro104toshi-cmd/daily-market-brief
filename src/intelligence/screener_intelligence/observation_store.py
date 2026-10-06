"""P8-A2 — 観測の authority の追記専用 store（`<data_root>/screener_intelligence/observation_records.jsonl` の 1 file）。

規律（A1 の identity の store と同じ）: 明示の data_root、正準の行だけを append、write → flush → fsync、同じ record
（byte 一致）は収束、履歴の不変条件に反する append は拒否、破損 ／ 非正準 ／ 切断 ／ 物理的な重複 ／ 履歴の違反は
fail closed（読み飛ばさない ・修復しない ・migration しない）、外部の変更は byte 長で検知（single writer）。
SQLite ・索引 ・cache は持たない（既存の J-Quants light store の索引とは無関係。P8-OBS-2 を持ち込まない）。

主語の検査のため、同じ data_root の A1 identity の authority を read-only で読む（`open_identity_history` だけ）。A1 には
何も書かない。A1 が無ければ `IDENTITY_AUTHORITY_MISSING`、壊れていれば `IDENTITY_STORE_CORRUPTION`。
エラーの文には file 名と行番号だけを入れ、path ・行の中身を入れない。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Tuple

from .identity_store import IdentityAuthorityMissing, IdentityStoreCorrupt, open_identity_history
from .observation_model import (ObservationHistory, ObservationHistoryError, ObservationModelError,
                                is_observation_record, parse_canonical_line)

OBSERVATION_DIRNAME = "screener_intelligence"
OBSERVATION_FILENAME = "observation_records.jsonl"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
CORRUPTION_REASONS: Tuple[str, ...] = ("AUTHORITY_MISSING", "IDENTITY_AUTHORITY_MISSING", "IDENTITY_STORE_CORRUPTION",
                                       "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE", "INVALID_RECORD",
                                       "PHYSICAL_DUPLICATE", "INVALID_HISTORY")


class ObservationFailureCategory(str, Enum):
    AUTHORITY_MISSING = "AUTHORITY_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class ObservationStoreError(RuntimeError):
    category = ObservationFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class ObservationAuthorityMissing(ObservationStoreError):
    category = ObservationFailureCategory.AUTHORITY_MISSING


class ObservationStoreCorrupt(ObservationStoreError):
    category = ObservationFailureCategory.STORE_CORRUPTION


class ObservationAppendRejected(ObservationStoreError):
    category = ObservationFailureCategory.APPEND_REJECTED


class ObservationConcurrentModification(ObservationStoreError):
    category = ObservationFailureCategory.CONCURRENT_MODIFICATION


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    record_id: str
    status: AppendStatus


def observation_path(data_root: Any) -> Path:
    if data_root is None or str(data_root).strip() == "":
        raise ObservationAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
    return Path(data_root) / OBSERVATION_DIRNAME / OBSERVATION_FILENAME


def _identity(data_root: Any):
    try:
        return open_identity_history(data_root)
    except IdentityAuthorityMissing:
        raise ObservationAuthorityMissing("IDENTITY_AUTHORITY_MISSING", "the A1 identity authority is missing") from None
    except IdentityStoreCorrupt as exc:
        raise ObservationStoreCorrupt("IDENTITY_STORE_CORRUPTION", exc.code) from None


class ObservationStore:
    """観測の authority（追記専用）。読むたびに全行を検査し、A1 の identity に照らした検証済みの履歴を持つ。"""

    def __init__(self, data_root: Any, *, read_only: bool = False, _create: bool = False) -> None:
        self.path = observation_path(data_root)
        self.data_root = data_root
        self.read_only = read_only
        identity = _identity(data_root)                                         # A1 が無ければ何も作らない
        if _create and not self.path.exists():
            with self.path.open("ab"):
                pass
        self._history = ObservationHistory(identity)
        self._lines: Tuple[str, ...] = ()
        self._expected_size = 0
        self.reload(identity)

    @classmethod
    def initialize(cls, data_root: Any) -> "ObservationStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Any, *, read_only: bool = False) -> "ObservationStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（fail closed。修復しない）

    def reload(self, identity=None) -> int:
        identity = identity if identity is not None else _identity(self.data_root)
        if not self.path.is_file():
            raise ObservationAuthorityMissing("AUTHORITY_MISSING", f"{OBSERVATION_FILENAME} is missing")
        raw = self.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise ObservationStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise ObservationStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                          line_number=text.count(LINE_TERMINATOR) + 1)
        history = ObservationHistory(identity)
        lines = []
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            if body.strip() == "":
                raise ObservationStoreCorrupt("BLANK_LINE", "blank line", line_number=line_number)
            try:
                record = parse_canonical_line(line)
            except ObservationModelError as exc:
                raise ObservationStoreCorrupt("INVALID_RECORD", exc.code, line_number=line_number) from None
            if history.contains(record.record_id):
                raise ObservationStoreCorrupt("PHYSICAL_DUPLICATE", "record already present", line_number=line_number)
            try:
                history.add(record)
            except ObservationHistoryError as exc:
                raise ObservationStoreCorrupt("INVALID_HISTORY", exc.code, line_number=line_number) from None
            lines.append(line)
        self._history, self._lines, self._expected_size = history, tuple(lines), len(raw)
        return len(lines)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.is_file() else -1
        if actual != self._expected_size:
            raise ObservationConcurrentModification("CONCURRENT_MODIFICATION", "authority changed outside this writer")

    def append(self, record: Any) -> AppendResult:
        if self.read_only:
            raise ObservationAppendRejected("READ_ONLY", "store was opened read-only")
        if not is_observation_record(record):
            raise ObservationAppendRejected("INVALID_TYPE", "only observation records can be appended")
        self.verify_unchanged()
        if self._history.contains(record.record_id):
            return AppendResult(record.record_id, AppendStatus.ALREADY_PRESENT)
        try:
            self._history.check(record)
        except ObservationHistoryError as exc:
            raise ObservationAppendRejected(exc.code, exc.detail) from None
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
    def history(self) -> ObservationHistory:
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


def open_observation_history(data_root: Any) -> ObservationHistory:
    """read-only で開いて検証済みの履歴を返す（何も書かない）。欠落 ／ 破損は例外のまま（呼び手が status にする）。"""
    return ObservationStore.open(data_root, read_only=True).history


__all__ = ["AppendResult", "AppendStatus", "CORRUPTION_REASONS", "ENCODING", "OBSERVATION_DIRNAME",
           "OBSERVATION_FILENAME", "ObservationAppendRejected", "ObservationAuthorityMissing",
           "ObservationConcurrentModification", "ObservationFailureCategory", "ObservationStore",
           "ObservationStoreCorrupt", "ObservationStoreError", "WRITER_GUARANTEE", "observation_path",
           "open_observation_history"]
