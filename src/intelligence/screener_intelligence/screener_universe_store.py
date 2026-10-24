"""P8-B5A — 人が審査した Universe の追記専用 store（`<data_root>/screener_intelligence/screener_universe_authority.jsonl`）。

凍結 B3 の authority store と同じ規律: 明示の data_root（既定 ・config ・cwd の path は無い）、正準の行だけを append、write → flush →
fsync、byte 一致は `REUSED`、同じ universe_id で内容の違う行（審査者 ・審査の瞬間が違う含む）は拒否（`UNIVERSE_CONTENT_CONFLICT`）、同じ
(universe_key, version) で違う Universe は拒否（`UNIVERSE_VERSION_CONFLICT`）、破損 ／ 非正準 ／ 切断 ／ 物理的な重複 ／ 復元できない行は
fail closed（修復 ・書き直し ・削除 ・圧縮 ・移行は無い）、外部の変更は byte 長で検知（single writer）。
読み出しは正確な `universe_id` か正確な `(universe_key, version)` だけ。「最新」「現在」「既定」「最高の版」「全市場」の解決は無い。
journal の位置 ・append の順は意味を持たない。identity の解決 ・provider の適格の実行 ・network ・時計 ・SQLite は無い。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .screener_universe_model import (HUMAN_REVIEWED_SCREENING_UNIVERSE, UNIVERSE_AUTHORITY_RECORD_KIND,
                                     UniverseAuthorityRecord, UniverseMetadata, UniverseModelError,
                                     is_universe_authority_record)

UNIVERSE_DIRNAME = "screener_intelligence"
UNIVERSE_FILENAME = "screener_universe_authority.jsonl"
STORE_RULES_VERSION = "p8_screener_universe_authority_store:0.1.0"
AUTHORITY_CLASS = HUMAN_REVIEWED_SCREENING_UNIVERSE
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
#: 解決は正確な identity だけ（latest ・current ・default ・highest-version ・全市場 ・順位は無い）
RESOLUTION_RULE = "EXACT_UNIVERSE_ID_OR_EXACT_KEY_VERSION_ONLY"
CORRUPTION_REASONS: Tuple[str, ...] = ("STORE_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "INVALID_RECORD", "NON_CANONICAL_LINE", "UNIVERSE_ID_MISMATCH",
                                       "MEMBERSHIP_DIGEST_MISMATCH", "PHYSICAL_DUPLICATE", "KEY_VERSION_DUPLICATE")


class UniverseFailureCategory(str, Enum):
    STORE_MISSING = "STORE_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class UniverseStoreError(RuntimeError):
    category = UniverseFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class UniverseStoreMissing(UniverseStoreError):
    category = UniverseFailureCategory.STORE_MISSING


class UniverseStoreCorrupt(UniverseStoreError):
    category = UniverseFailureCategory.STORE_CORRUPTION


class UniverseAppendRejected(UniverseStoreError):
    category = UniverseFailureCategory.APPEND_REJECTED


class UniverseConcurrentModification(UniverseStoreError):
    category = UniverseFailureCategory.CONCURRENT_MODIFICATION


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"


@dataclass(frozen=True)
class AppendResult:
    universe_id: str
    status: AppendStatus


class IntegrityStatus(str, Enum):
    OK = "OK"
    STORE_MISSING = "STORE_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"


@dataclass(frozen=True)
class IntegrityReport:
    """journal の検査の結果（修復しない）。"""

    status: IntegrityStatus
    record_count: int
    failure_code: str = ""
    line_number: int = 0


def parse_universe_line(line: str) -> UniverseAuthorityRecord:
    """正準の 1 行 → record（model の validator で復元し、往復で byte 一致しなければ拒む）。"""
    if not isinstance(line, str) or not line.endswith(LINE_TERMINATOR):
        raise UniverseModelError("INVALID_RECORD", "line")
    try:
        data = json.loads(line)
    except ValueError:
        raise UniverseModelError("INVALID_RECORD", "json") from None
    if not isinstance(data, dict) or data.get("record_kind") != UNIVERSE_AUTHORITY_RECORD_KIND:
        raise UniverseModelError("INVALID_RECORD", "record_kind")
    record = UniverseAuthorityRecord.from_dict(data)
    if record.canonical_line() != line:
        raise UniverseModelError("NON_CANONICAL_LINE", "line")
    return record


def universe_path(data_root: Any) -> Path:
    if data_root is None or str(data_root).strip() == "":
        raise UniverseAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required")
    return Path(data_root) / UNIVERSE_DIRNAME / UNIVERSE_FILENAME


def _key_version(record: UniverseAuthorityRecord) -> Tuple[str, int]:
    return record.universe_key, record.version


class UniverseAuthorityStore:
    """人が審査した Universe の追記専用 store。読むたびに全行を model の validator で復元して検査する。他の store には触れない。"""

    def __init__(self, data_root: Any, *, read_only: bool = False, _create: bool = False) -> None:
        self.path = universe_path(data_root)
        self.data_root = data_root
        self.read_only = read_only
        if _create and not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab"):
                pass
        self._records: List[UniverseAuthorityRecord] = []
        self._lines: Dict[str, str] = {}
        self._by_key_version: Dict[Tuple[str, int], str] = {}
        self._ordered_lines: Tuple[str, ...] = ()
        self._expected_size = 0
        self.reload()

    @classmethod
    def initialize(cls, data_root: Any) -> "UniverseAuthorityStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Any, *, read_only: bool = False) -> "UniverseAuthorityStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（fail closed。修復しない）

    def reload(self) -> int:
        if not self.path.is_file():
            raise UniverseStoreMissing("STORE_MISSING", f"{UNIVERSE_FILENAME} is missing")
        journal_bytes = self.path.read_bytes()
        try:
            text = journal_bytes.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise UniverseStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise UniverseStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                     line_number=text.count(LINE_TERMINATOR) + 1)
        records: List[UniverseAuthorityRecord] = []
        by_id: Dict[str, str] = {}
        by_key_version: Dict[Tuple[str, int], str] = {}
        for line_number, line_body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = line_body + LINE_TERMINATOR
            if line_body.strip() == "":
                raise UniverseStoreCorrupt("BLANK_LINE", "blank line", line_number=line_number)
            try:
                record = parse_universe_line(line)
            except UniverseModelError as exc:
                code = exc.code if exc.code in CORRUPTION_REASONS else "INVALID_RECORD"
                raise UniverseStoreCorrupt(code, exc.detail or exc.code, line_number=line_number) from None
            if record.record_id in by_id:
                raise UniverseStoreCorrupt("PHYSICAL_DUPLICATE", "universe already present", line_number=line_number)
            if _key_version(record) in by_key_version:                           # 1 鍵 ・1 版 ＝ 1 Universe
                raise UniverseStoreCorrupt("KEY_VERSION_DUPLICATE", "second universe for one key and version",
                                         line_number=line_number)
            records.append(record)
            by_id[record.record_id] = line
            by_key_version[_key_version(record)] = record.record_id
        self._records, self._lines, self._by_key_version = records, by_id, by_key_version
        self._ordered_lines, self._expected_size = tuple(by_id[r.record_id] for r in records), len(journal_bytes)
        return len(records)

    @classmethod
    def validate(cls, data_root: Any) -> IntegrityReport:
        """journal の全行が parse ・schema ・authority の分類 ・model の validator での復元 ・id の再計算 ・重複なしを満たすか。修復しない。"""
        try:
            store = cls(data_root, read_only=True)
        except UniverseStoreMissing as exc:
            return IntegrityReport(IntegrityStatus.STORE_MISSING, 0, exc.code, exc.line_number)
        except UniverseStoreCorrupt as exc:
            return IntegrityReport(IntegrityStatus.STORE_CORRUPTION, 0, exc.code, exc.line_number)
        return IntegrityReport(IntegrityStatus.OK, len(store._records))

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.is_file() else -1
        if actual != self._expected_size:
            raise UniverseConcurrentModification("CONCURRENT_MODIFICATION", "store changed outside this writer")

    def append(self, record: Any) -> AppendResult:
        """APPENDED ／ REUSED（byte 一致）。同じ universe_id で違う内容 ・同じ (鍵, 版) で違う Universe は拒む。版の順 ・欠番は問わない。"""
        if self.read_only:
            raise UniverseAppendRejected("READ_ONLY", "store was opened read-only")
        if not is_universe_authority_record(record):
            raise UniverseAppendRejected("INVALID_TYPE", "only UniverseAuthorityRecord records can be appended")
        self.verify_unchanged()
        line = record.canonical_line()
        existing = self._lines.get(record.record_id)
        if existing is not None:
            if existing != line:
                raise UniverseAppendRejected("UNIVERSE_CONTENT_CONFLICT", "same universe_id with different content")
            return AppendResult(record.record_id, AppendStatus.REUSED)
        if _key_version(record) in self._by_key_version:                         # 同じ鍵 ・同じ版に違う Universe
            raise UniverseAppendRejected("UNIVERSE_VERSION_CONFLICT",
                                         "a different universe exists for this universe_key and version")
        data = line.encode(ENCODING)
        with self.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._expected_size += len(data)
        self._records.append(record)
        self._lines[record.record_id] = line
        self._by_key_version[_key_version(record)] = record.record_id
        self._ordered_lines = self._ordered_lines + (line,)
        return AppendResult(record.record_id, AppendStatus.APPENDED)

    # ------------------------------------------------------------ read（正確な identity だけ。位置 ・最新 ・既定は無い）

    def records(self) -> Tuple[UniverseAuthorityRecord, ...]:
        return tuple(self._records)

    def get_by_universe_id(self, universe_id: str) -> Optional[UniverseAuthorityRecord]:
        for record in self._records:
            if record.record_id == universe_id:
                return record
        return None

    def get_by_key_version(self, universe_key: str, version: int) -> Optional[UniverseAuthorityRecord]:
        """正確な (universe_key, version)。版は明示の label で、省略 ・推定 ・最高の版の選択は無い。"""
        if type(version) is not int:
            raise UniverseAppendRejected("INVALID_VERSION", "version must be an explicit int")
        universe_id = self._by_key_version.get((universe_key, version))
        return self.get_by_universe_id(universe_id) if universe_id is not None else None

    def list_metadata(self) -> Tuple[UniverseMetadata, ...]:
        """人が選ぶための metadata（member の code ・意図 ・著者なし）。並びは (鍵, 版, id) の辞書順で、「現在」の意味は無い。"""
        return tuple(sorted((UniverseMetadata.of(r) for r in self._records),
                            key=lambda m: (m.universe_key, m.version, m.universe_id)))

    def canonical_lines(self) -> Tuple[str, ...]:
        return self._ordered_lines


__all__ = ["AUTHORITY_CLASS", "AppendResult", "AppendStatus", "CORRUPTION_REASONS", "ENCODING", "IntegrityReport",
           "IntegrityStatus", "UNIVERSE_DIRNAME", "UNIVERSE_FILENAME", "RESOLUTION_RULE", "STORE_RULES_VERSION",
           "WRITER_GUARANTEE", "UniverseAppendRejected", "UniverseAuthorityStore", "UniverseConcurrentModification",
           "UniverseFailureCategory", "UniverseStoreCorrupt", "UniverseStoreError", "UniverseStoreMissing",
           "parse_universe_line", "universe_path"]
