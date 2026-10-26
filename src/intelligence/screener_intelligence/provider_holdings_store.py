"""P8-A2C-R — `ProviderHoldingsCoverage` の追記専用 store（`<data_root>/screener_intelligence/provider_holdings_coverage.jsonl`）

A2 の観測 journal ・ACQ0 ・manifest ・保留の store とは別の journal（世界の完全性と provider の保持を混ぜない。監督の決定 C1）。
規律は P8 の authority store と同じ: 明示の data_root、正準の行だけを append、write → flush → fsync、byte 一致は `REUSED`、同じ id で
内容が違う行 ・同じ取得 ・同じ period_end に内容の違う record は拒否（`PROVIDER_HOLDINGS_CONFLICT`）、破損 ／ 非正準 ／ 切断 ／ 物理的な
重複は fail closed（修復 ・書き直し ・削除 ・圧縮は無い）、外部の変更は byte 長で検知（single writer）。
検索は id ・参照 ・（主語, period_end）による。journal の位置は意味を持たない。時計 ・network ・SQLite は無い。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .provider_holdings_model import (HOLDINGS_RECORD_KIND, PROVIDER_HOLDINGS_RECORD, HoldingsModelError,
                                      ProviderHoldingsCoverage, is_provider_holdings_coverage)

HOLDINGS_DIRNAME = "screener_intelligence"
HOLDINGS_FILENAME = "provider_holdings_coverage.jsonl"
STORE_RULES_VERSION = "p8_provider_holdings_store:0.1.0"
AUTHORITY_CLASS = PROVIDER_HOLDINGS_RECORD
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
CORRUPTION_REASONS: Tuple[str, ...] = ("STORE_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "INVALID_RECORD", "NON_CANONICAL_LINE", "PHYSICAL_DUPLICATE",
                                       "EPOCH_PERIOD_DUPLICATE")


class HoldingsFailureCategory(str, Enum):
    STORE_MISSING = "STORE_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class HoldingsStoreError(RuntimeError):
    category = HoldingsFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class HoldingsStoreMissing(HoldingsStoreError):
    category = HoldingsFailureCategory.STORE_MISSING


class HoldingsStoreCorrupt(HoldingsStoreError):
    category = HoldingsFailureCategory.STORE_CORRUPTION


class HoldingsAppendRejected(HoldingsStoreError):
    category = HoldingsFailureCategory.APPEND_REJECTED


class HoldingsConcurrentModification(HoldingsStoreError):
    category = HoldingsFailureCategory.CONCURRENT_MODIFICATION


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"


@dataclass(frozen=True)
class AppendResult:
    record_id: str
    status: AppendStatus


def parse_holdings_line(line: str) -> ProviderHoldingsCoverage:
    """正準の 1 行 → record（往復で byte 一致しなければ拒む）。"""
    if not isinstance(line, str) or not line.endswith(LINE_TERMINATOR):
        raise HoldingsModelError("INVALID_RECORD", "line")
    try:
        data = json.loads(line)
    except ValueError:
        raise HoldingsModelError("INVALID_RECORD", "json") from None
    if not isinstance(data, dict) or data.get("record_kind") != HOLDINGS_RECORD_KIND:
        raise HoldingsModelError("INVALID_RECORD", "record_kind")
    record = ProviderHoldingsCoverage.from_dict(data)
    if record.canonical_line() != line:
        raise HoldingsModelError("NON_CANONICAL_LINE", "line")
    return record


def holdings_path(data_root: Any) -> Path:
    if data_root is None or str(data_root).strip() == "":
        raise HoldingsAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required")
    return Path(data_root) / HOLDINGS_DIRNAME / HOLDINGS_FILENAME


def _epoch_key(record: ProviderHoldingsCoverage) -> Tuple[str, str]:
    return record.acquisition_ref, record.period_end.isoformat()


class ProviderHoldingsStore:
    """provider の保持 epoch の追記専用 store。読むたびに全行を検査する。他の store には触れない。"""

    def __init__(self, data_root: Any, *, read_only: bool = False, _create: bool = False) -> None:
        self.path = holdings_path(data_root)
        self.data_root = data_root
        self.read_only = read_only
        if _create and not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab"):
                pass
        self._records: List[ProviderHoldingsCoverage] = []
        self._lines: Dict[str, str] = {}
        self._by_epoch: Dict[Tuple[str, str], str] = {}
        self._ordered_lines: Tuple[str, ...] = ()
        self._expected_size = 0
        self.reload()

    @classmethod
    def initialize(cls, data_root: Any) -> "ProviderHoldingsStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Any, *, read_only: bool = False) -> "ProviderHoldingsStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（fail closed。修復しない）

    def reload(self) -> int:
        if not self.path.is_file():
            raise HoldingsStoreMissing("STORE_MISSING", f"{HOLDINGS_FILENAME} is missing")
        journal_bytes = self.path.read_bytes()
        try:
            text = journal_bytes.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise HoldingsStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise HoldingsStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                       line_number=text.count(LINE_TERMINATOR) + 1)
        records: List[ProviderHoldingsCoverage] = []
        by_id: Dict[str, str] = {}
        by_epoch: Dict[Tuple[str, str], str] = {}
        for line_number, line_body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = line_body + LINE_TERMINATOR
            if line_body.strip() == "":
                raise HoldingsStoreCorrupt("BLANK_LINE", "blank line", line_number=line_number)
            try:
                record = parse_holdings_line(line)
            except HoldingsModelError as exc:
                raise HoldingsStoreCorrupt("INVALID_RECORD" if exc.code != "NON_CANONICAL_LINE" else exc.code,
                                           exc.code, line_number=line_number) from None
            if record.record_id in by_id:
                raise HoldingsStoreCorrupt("PHYSICAL_DUPLICATE", "record already present", line_number=line_number)
            if _epoch_key(record) in by_epoch:                                   # 1 取得 ・1 period_end ＝ 1 record
                raise HoldingsStoreCorrupt("EPOCH_PERIOD_DUPLICATE", "second record for one acquisition and period",
                                           line_number=line_number)
            records.append(record)
            by_id[record.record_id] = line
            by_epoch[_epoch_key(record)] = record.record_id
        self._records, self._lines, self._by_epoch = records, by_id, by_epoch
        self._ordered_lines, self._expected_size = tuple(by_id[r.record_id] for r in records), len(journal_bytes)
        return len(records)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.is_file() else -1
        if actual != self._expected_size:
            raise HoldingsConcurrentModification("CONCURRENT_MODIFICATION", "store changed outside this writer")

    def append(self, record: Any) -> AppendResult:
        if self.read_only:
            raise HoldingsAppendRejected("READ_ONLY", "store was opened read-only")
        if not is_provider_holdings_coverage(record):
            raise HoldingsAppendRejected("INVALID_TYPE", "only ProviderHoldingsCoverage records can be appended")
        self.verify_unchanged()
        line = record.canonical_line()
        existing = self._lines.get(record.record_id)
        if existing is not None:
            if existing != line:
                raise HoldingsAppendRejected("HOLDINGS_CONTENT_CONFLICT", "same id with different content")
            return AppendResult(record.record_id, AppendStatus.REUSED)
        if _epoch_key(record) in self._by_epoch:                                 # 同じ取得 ・同じ period_end に違う record
            raise HoldingsAppendRejected("PROVIDER_HOLDINGS_CONFLICT",
                                         "a different record exists for this acquisition and period_end")
        data = line.encode(ENCODING)
        with self.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._expected_size += len(data)
        self._records.append(record)
        self._lines[record.record_id] = line
        self._by_epoch[_epoch_key(record)] = record.record_id
        self._ordered_lines = self._ordered_lines + (line,)
        return AppendResult(record.record_id, AppendStatus.APPENDED)

    # ------------------------------------------------------------ read（id ・参照 ・（主語, period_end）で探す。位置は使わない）

    def records(self) -> Tuple[ProviderHoldingsCoverage, ...]:
        return tuple(self._records)

    def get(self, record_id: str) -> Optional[ProviderHoldingsCoverage]:
        for record in self._records:
            if record.record_id == record_id:
                return record
        return None

    def by_reference(self, reference: str) -> Optional[ProviderHoldingsCoverage]:
        for record in self._records:
            if record.reference == reference:
                return record
        return None

    def for_subject(self, subject_id: str) -> Tuple[ProviderHoldingsCoverage, ...]:
        """主語の全 record（`holdings_as_of`、次に id の順。journal の位置ではない）。"""
        return tuple(sorted((r for r in self._records if r.subject_id == subject_id),
                            key=lambda r: (r.holdings_as_of, r.record_id)))

    def for_slot(self, subject_id: str, period_end: Any) -> Tuple[ProviderHoldingsCoverage, ...]:
        """主語 ・period_end の epoch（`holdings_as_of`、次に id の順）。遡及の resolver の epoch の選択の源。"""
        return tuple(r for r in self.for_subject(subject_id) if r.covers(period_end))

    def canonical_lines(self) -> Tuple[str, ...]:
        return self._ordered_lines


__all__ = ["AUTHORITY_CLASS", "AppendResult", "AppendStatus", "CORRUPTION_REASONS", "ENCODING", "HOLDINGS_DIRNAME",
           "HOLDINGS_FILENAME", "STORE_RULES_VERSION", "WRITER_GUARANTEE", "HoldingsAppendRejected",
           "HoldingsConcurrentModification", "HoldingsFailureCategory", "HoldingsStoreCorrupt", "HoldingsStoreError",
           "HoldingsStoreMissing", "ProviderHoldingsStore", "holdings_path", "parse_holdings_line"]
