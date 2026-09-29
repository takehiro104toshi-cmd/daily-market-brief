"""P8-ST1 — 会計の意味の注記（A2R）の追記専用の運用 store（`<data_root>/screener_intelligence/semantic_metadata.jsonl` の 1 file）。

凍結した A2R の record（`ObservationSemantics` ・`SemanticMappingProvenance`）をそのまま 1 つの journal に置く。authority の class は
`SEMANTIC_METADATA_RECORD`（provider の写しの運用上の metadata。市場の観測 ・投資の authority ・Production DNA ・Theme の証拠 ・推奨では
ない。監督の決定 D2）。A2 の観測の store とは別の file で、A2 ・A1 ・指標には何も書かない ・読まない。

規律（A1 ／ A2 ／ A1R の store と同じ）: 明示の data_root、正準の行だけを append、write → flush → fsync、同じ record（byte 一致）は
収束、破損 ／ 非正準 ／ 切断 ／ 物理的な重複 ／ journal の不変条件の違反は fail closed（読み飛ばさない ・修復しない ・消さない）、
外部の変更は byte 長で検知（single writer）。SQLite ・索引 ・cache ・時計 ・network は無い。

journal の不変条件（衝突は拒む。「最新が勝つ」「先勝ち」「出所で選ぶ」はしない）:
- 1 つの `observation_id` に注記は 1 つだけ。内容の違う 2 つ目 → `SEMANTICS_CONFLICT`。
- 1 つの `observation_id` に写しの provenance は 1 つだけ。内容の違う 2 つ目 → `PROVENANCE_CONFLICT`。
- 注記の `mapping_provenance_id` はその時点で journal にある provenance を指し、同じ `observation_id` のものでなければならない
  （`PROVENANCE_MISSING` ／ `PROVENANCE_MISMATCH`）。provenance を先に append する。
- 写しの規則の版の更新 ・訂正は本 store の外（明示の訂正の record。後の gate）。

raw の応答 ・credential ・path は持たない（record の型が値を持てない）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .observation_semantics_model import (MAPPING_PROVENANCE_RECORD_KIND, SEMANTIC_METADATA_RECORD,
                                          SEMANTICS_RECORD_KIND, ObservationSemantics, SemanticMappingProvenance,
                                          SemanticsModelError)

SEMANTIC_METADATA_DIRNAME = "screener_intelligence"
SEMANTIC_METADATA_FILENAME = "semantic_metadata.jsonl"
STORE_RULES_VERSION = "p8_semantic_metadata_store:0.1.0"
AUTHORITY_CLASS = SEMANTIC_METADATA_RECORD
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
CORRUPTION_REASONS: Tuple[str, ...] = ("STORE_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "INVALID_RECORD", "NON_CANONICAL_LINE", "PHYSICAL_DUPLICATE",
                                       "INVALID_JOURNAL")
_RECORD_TYPES = {SEMANTICS_RECORD_KIND: ObservationSemantics, MAPPING_PROVENANCE_RECORD_KIND: SemanticMappingProvenance}


class SemanticMetadataFailureCategory(str, Enum):
    STORE_MISSING = "STORE_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class SemanticMetadataStoreError(RuntimeError):
    category = SemanticMetadataFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.line_number = line_number


class SemanticMetadataMissing(SemanticMetadataStoreError):
    category = SemanticMetadataFailureCategory.STORE_MISSING


class SemanticMetadataCorrupt(SemanticMetadataStoreError):
    category = SemanticMetadataFailureCategory.STORE_CORRUPTION


class SemanticMetadataAppendRejected(SemanticMetadataStoreError):
    category = SemanticMetadataFailureCategory.APPEND_REJECTED


class SemanticMetadataConcurrentModification(SemanticMetadataStoreError):
    category = SemanticMetadataFailureCategory.CONCURRENT_MODIFICATION


class SemanticMetadataJournalError(ValueError):
    """journal の不変条件の違反（衝突 ・参照の欠落 ・不一致）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    record_id: str
    status: AppendStatus


def is_semantic_metadata_record(record: Any) -> bool:
    return isinstance(record, (ObservationSemantics, SemanticMappingProvenance))


def parse_semantic_metadata_line(line: str) -> Any:
    """正準の 1 行 → record（往復で byte 一致しなければ拒む）。"""
    if not isinstance(line, str) or not line.endswith(LINE_TERMINATOR):
        raise SemanticsModelError("INVALID_RECORD", "line")
    try:
        data = json.loads(line)
    except ValueError:
        raise SemanticsModelError("INVALID_RECORD", "json") from None
    if not isinstance(data, dict) or data.get("record_kind") not in _RECORD_TYPES:
        raise SemanticsModelError("INVALID_RECORD", "record_kind")
    record = _RECORD_TYPES[data["record_kind"]].from_dict(data)
    if record.canonical_line() != line:
        raise SemanticsModelError("NON_CANONICAL_LINE", "line")
    return record


class SemanticMetadataJournal:
    """検証済みの注記の集合（memory 内。不変条件を検査する）。"""

    def __init__(self, records: Any = ()) -> None:
        self._records: List[Any] = []
        self._by_id: Dict[str, Any] = {}
        self._semantics: Dict[str, ObservationSemantics] = {}
        self._provenance: Dict[str, SemanticMappingProvenance] = {}
        for record in records:
            self.add(record)

    @property
    def records(self) -> Tuple[Any, ...]:
        return tuple(self._records)

    def contains(self, record_id: str) -> bool:
        return record_id in self._by_id

    def get(self, record_id: str) -> Optional[Any]:
        return self._by_id.get(record_id)

    def semantics_for(self, observation_id: str) -> Optional[ObservationSemantics]:
        return self._semantics.get(observation_id)

    def provenance_for(self, observation_id: str) -> Optional[SemanticMappingProvenance]:
        return self._provenance.get(observation_id)

    def check(self, record: Any) -> None:
        if not is_semantic_metadata_record(record):
            raise SemanticMetadataJournalError("INVALID_TYPE", "not a semantic metadata record")
        if isinstance(record, SemanticMappingProvenance):
            existing = self._provenance.get(record.observation_id)
            if existing is not None and existing.record_id != record.record_id:
                raise SemanticMetadataJournalError("PROVENANCE_CONFLICT", "observation already has a provenance")
            return
        existing = self._semantics.get(record.observation_id)
        if existing is not None and existing.record_id != record.record_id:
            raise SemanticMetadataJournalError("SEMANTICS_CONFLICT", "observation already has semantics")
        provenance = self._by_id.get(record.mapping_provenance_id)
        if provenance is None or not isinstance(provenance, SemanticMappingProvenance):
            raise SemanticMetadataJournalError("PROVENANCE_MISSING", "mapping_provenance_id")
        if provenance.observation_id != record.observation_id:
            raise SemanticMetadataJournalError("PROVENANCE_MISMATCH", "mapping_provenance_id")

    def add(self, record: Any) -> bool:
        """検査して加える。byte 一致の同じ record なら何もしない（False）。"""
        if is_semantic_metadata_record(record) and record.record_id in self._by_id:
            return False
        self.check(record)
        self._records.append(record)
        self._by_id[record.record_id] = record
        if isinstance(record, SemanticMappingProvenance):
            self._provenance[record.observation_id] = record
        else:
            self._semantics[record.observation_id] = record
        return True


def semantic_metadata_path(data_root: Any) -> Path:
    if data_root is None or str(data_root).strip() == "":
        raise SemanticMetadataAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
    return Path(data_root) / SEMANTIC_METADATA_DIRNAME / SEMANTIC_METADATA_FILENAME


class SemanticMetadataStore:
    """注記の運用 store（追記専用）。読むたびに全行を検査した journal を持つ。A2 ・A1 には触れない。"""

    def __init__(self, data_root: Any, *, read_only: bool = False, _create: bool = False) -> None:
        self.path = semantic_metadata_path(data_root)
        self.data_root = data_root
        self.read_only = read_only
        if _create and not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab"):
                pass
        self._journal = SemanticMetadataJournal()
        self._lines: Tuple[str, ...] = ()
        self._expected_size = 0
        self.reload()

    @classmethod
    def initialize(cls, data_root: Any) -> "SemanticMetadataStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Any, *, read_only: bool = False) -> "SemanticMetadataStore":
        return cls(data_root, read_only=read_only)

    # ------------------------------------------------------------ load（fail closed。修復しない）

    def reload(self) -> int:
        if not self.path.is_file():
            raise SemanticMetadataMissing("STORE_MISSING", f"{SEMANTIC_METADATA_FILENAME} is missing")
        journal_bytes = self.path.read_bytes()
        try:
            text = journal_bytes.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise SemanticMetadataCorrupt("INVALID_ENCODING", f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise SemanticMetadataCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator",
                                          line_number=text.count(LINE_TERMINATOR) + 1)
        journal = SemanticMetadataJournal()
        lines = []
        for line_number, line_body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = line_body + LINE_TERMINATOR
            if line_body.strip() == "":
                raise SemanticMetadataCorrupt("BLANK_LINE", "blank line", line_number=line_number)
            try:
                record = parse_semantic_metadata_line(line)
            except SemanticsModelError as exc:
                raise SemanticMetadataCorrupt("INVALID_RECORD" if exc.code != "NON_CANONICAL_LINE" else exc.code,
                                              exc.code, line_number=line_number) from None
            if journal.contains(record.record_id):
                raise SemanticMetadataCorrupt("PHYSICAL_DUPLICATE", "record already present", line_number=line_number)
            try:
                journal.add(record)
            except SemanticMetadataJournalError as exc:
                raise SemanticMetadataCorrupt("INVALID_JOURNAL", exc.code, line_number=line_number) from None
            lines.append(line)
        self._journal, self._lines, self._expected_size = journal, tuple(lines), len(journal_bytes)
        return len(lines)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        actual = self.path.stat().st_size if self.path.is_file() else -1
        if actual != self._expected_size:
            raise SemanticMetadataConcurrentModification("CONCURRENT_MODIFICATION",
                                                         "store changed outside this writer")

    def append(self, record: Any) -> AppendResult:
        if self.read_only:
            raise SemanticMetadataAppendRejected("READ_ONLY", "store was opened read-only")
        if not is_semantic_metadata_record(record):
            raise SemanticMetadataAppendRejected("INVALID_TYPE", "only A2R semantic metadata records can be appended")
        self.verify_unchanged()
        if self._journal.contains(record.record_id):
            return AppendResult(record.record_id, AppendStatus.ALREADY_PRESENT)
        try:
            self._journal.check(record)
        except SemanticMetadataJournalError as exc:
            raise SemanticMetadataAppendRejected(exc.code, exc.detail) from None
        line = record.canonical_line()
        data = line.encode(ENCODING)
        with self.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._expected_size += len(data)
        self._journal.add(record)
        self._lines = self._lines + (line,)
        return AppendResult(record.record_id, AppendStatus.APPENDED)

    # ------------------------------------------------------------ read

    @property
    def journal(self) -> SemanticMetadataJournal:
        return self._journal

    def records(self) -> Tuple[Any, ...]:
        return self._journal.records

    def canonical_lines(self) -> Tuple[str, ...]:
        return self._lines

    def semantics_for(self, observation_id: str) -> Optional[ObservationSemantics]:
        return self._journal.semantics_for(observation_id)

    def provenance_for(self, observation_id: str) -> Optional[SemanticMappingProvenance]:
        return self._journal.provenance_for(observation_id)

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for record in self._journal.records:
            counts[record.KIND] = counts.get(record.KIND, 0) + 1
        return counts


def open_semantic_metadata_journal(data_root: Any) -> SemanticMetadataJournal:
    """read-only で開いて検証済みの journal を返す（何も書かない）。"""
    return SemanticMetadataStore.open(data_root, read_only=True).journal


__all__ = ["AUTHORITY_CLASS", "AppendResult", "AppendStatus", "CORRUPTION_REASONS", "ENCODING",
           "SEMANTIC_METADATA_DIRNAME", "SEMANTIC_METADATA_FILENAME", "STORE_RULES_VERSION",
           "SemanticMetadataAppendRejected", "SemanticMetadataConcurrentModification", "SemanticMetadataCorrupt",
           "SemanticMetadataFailureCategory", "SemanticMetadataJournal", "SemanticMetadataJournalError",
           "SemanticMetadataMissing", "SemanticMetadataStore", "SemanticMetadataStoreError", "WRITER_GUARANTEE",
           "is_semantic_metadata_record", "open_semantic_metadata_journal", "parse_semantic_metadata_line",
           "semantic_metadata_path"]
