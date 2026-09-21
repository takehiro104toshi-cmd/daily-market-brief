"""P6-B5B — relation authority の追記専用 store（`<data_root>/theme_intelligence/` の 2 file）。

Foundation `<data_root>/themes/` とも B3 の proposal authority とも別 object・別 file。本 store は Foundation の
JSONL を読みも書きもせず、Theme root を所有しない（root id を参照するだけ）。

規律（P5 / Foundation / B3 を継承）: 明示 data_root、canonical 行のみ append、write → flush → fsync、
同 id ＋ byte 一致 ＝ 冪等、同 id ＋ 異 bytes ＝ CONFLICT、破損 / 非 canonical / 切断行は fail closed、
読み飛ばさない、修復しない、migration しない、外部変更は byte 長で検知（single writer）。SQLite は無い。

append 時の構造規律: 分岐 append を許さない（genesis は辺ごとに 1 本、訂正は唯一の terminal からのみ）。
撤回 / 復帰は governance 側にだけ現れ、assertion の改訂としては表せない。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple, Union

from .relation_model import (RELATION_ASSERTION_SCHEMA_VERSION, RELATION_GOVERNANCE_SCHEMA_VERSION,
                             RelationGovernanceEventType, RelationModelError, ThemeRelationAssertion,
                             ThemeRelationGovernanceEvent, canonical_relation_line, parse_relation_record)
from .relation_resolution import (EndpointLookup, RelationDiagnostic, RelationResolutionStatus,
                                  ThemeRelationResolution, RELATION_RESOLVER_VERSION, resolve_relation_graph)

RELATION_DIRNAME = "theme_intelligence"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
AUTHORITY_FILENAMES: Mapping[str, str] = {"assertions": "relation_assertions.jsonl",
                                          "governance": "relation_governance.jsonl"}
LOAD_ORDER: Tuple[str, ...] = ("assertions", "governance")
CORRUPTION_REASONS: Tuple[str, ...] = ("AUTHORITY_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "MALFORMED_JSON", "NOT_AN_OBJECT", "INVALID_RECORD", "UNSUPPORTED_SCHEMA_VERSION",
                                       "NON_CANONICAL_LINE", "WRONG_AUTHORITY", "PHYSICAL_DUPLICATE_IDENTICAL",
                                       "PHYSICAL_DUPLICATE_CONFLICTING")
HISTORY_REASONS: Tuple[str, ...] = ("EDGE_ALREADY_STARTED", "MISSING_PREDECESSOR", "PREDECESSOR_WRONG_EDGE",
                                    "NOT_TERMINAL_PREDECESSOR", "NON_MONOTONIC_RECORDED_AT", "UNKNOWN_EDGE",
                                    "INVALID_GOVERNANCE_TARGET", "INVALID_GOVERNANCE_SEQUENCE", "INVALID_TYPE")


class RelationFailureCategory(str, Enum):
    STORE_CORRUPTION = "STORE_CORRUPTION"
    INVALID_HISTORY = "INVALID_HISTORY"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONFLICT = "CONFLICT"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class RelationStoreError(RuntimeError):
    category = RelationFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, authority: str = "", line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.authority = authority
        self.line_number = line_number


class RelationStoreCorrupt(RelationStoreError):
    category = RelationFailureCategory.STORE_CORRUPTION


class RelationInvalidHistory(RelationStoreError):
    category = RelationFailureCategory.INVALID_HISTORY


class RelationAppendRejected(RelationStoreError):
    category = RelationFailureCategory.APPEND_REJECTED


class RelationConflict(RelationStoreError):
    category = RelationFailureCategory.CONFLICT

    def __init__(self, record_id: str, *, authority: str) -> None:
        super().__init__("CONFLICT", f"{record_id} exists with different canonical bytes", authority=authority)


class RelationConcurrentModification(RelationStoreError):
    category = RelationFailureCategory.CONCURRENT_MODIFICATION

    def __init__(self, authority: str, expected: int, actual: int) -> None:
        super().__init__("CONCURRENT_MODIFICATION", f"{authority} changed outside this writer ({expected} -> {actual})",
                         authority=authority)


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    authority: str
    record_id: str
    status: AppendStatus


@dataclass(frozen=True)
class _Entry:
    line_number: int
    line: str
    record: object


class _Authority:
    def __init__(self, name: str, path: Path) -> None:
        self.name, self.path = name, path
        self.entries: Dict[str, _Entry] = {}
        self.expected_size = 0


def relations_dir(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    return Path(data_root) / RELATION_DIRNAME


def authority_paths(data_root: Union[str, "os.PathLike[str]"]) -> Dict[str, Path]:
    return {name: relations_dir(data_root) / filename for name, filename in AUTHORITY_FILENAMES.items()}


def _record_id(name: str, record) -> str:
    return record.relation_assertion_id if name == "assertions" else record.event_id


class ThemeRelationStore:
    """relation assertion / governance の追記専用 authority。Foundation store とは別 object。"""

    def __init__(self, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False,
                 _create: bool = False) -> None:
        if data_root is None or str(data_root).strip() == "":
            raise RelationAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
        self.data_root = Path(data_root)
        self.read_only = read_only
        self._authorities = {name: _Authority(name, path) for name, path in authority_paths(self.data_root).items()}
        self._reset_index()
        if _create:
            relations_dir(self.data_root).mkdir(parents=True, exist_ok=True)
            for authority in self._authorities.values():
                if not authority.path.exists():
                    with authority.path.open("a", encoding=ENCODING):
                        pass
        self.reload()

    @classmethod
    def initialize(cls, data_root: Union[str, "os.PathLike[str]"]) -> "ThemeRelationStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False) -> "ThemeRelationStore":
        return cls(data_root, read_only=read_only)

    @property
    def paths(self) -> Mapping[str, Path]:
        return {name: a.path for name, a in self._authorities.items()}

    # ------------------------------------------------------------ load

    def _reset_index(self) -> None:
        self._assertions_by_edge: Dict[str, List[str]] = {}
        self._assertion_children: Dict[str, List[str]] = {}
        self._events_by_edge: Dict[str, List[str]] = {}
        self._event_children: Dict[str, List[str]] = {}

    def reload(self) -> Dict[str, int]:
        for authority in self._authorities.values():
            authority.entries = {}
            authority.expected_size = 0
        self._reset_index()
        for name in LOAD_ORDER:
            self._load_authority(self._authorities[name])
        return self.counts()

    def _load_authority(self, authority: _Authority) -> None:
        name = authority.name
        if not authority.path.exists():
            raise RelationStoreCorrupt("AUTHORITY_MISSING", f"{authority.path.name} is missing", authority=name,
                                       line_number=0)
        raw = authority.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise RelationStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}", authority=name, line_number=0) from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise RelationStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator", authority=name,
                                       line_number=text.count(LINE_TERMINATOR) + 1)
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            record = self._parse_line(name, line, line_number)
            rid = _record_id(name, record)
            previous = authority.entries.get(rid)
            if previous is not None:
                reason = "PHYSICAL_DUPLICATE_IDENTICAL" if previous.line == line else "PHYSICAL_DUPLICATE_CONFLICTING"
                raise RelationStoreCorrupt(reason, f"{rid} first seen at line {previous.line_number}", authority=name,
                                           line_number=line_number)
            self._validate(name, record, for_append=False, line_number=line_number)
            authority.entries[rid] = _Entry(line_number, line, record)
            self._index(name, record)
        authority.expected_size = len(raw)

    def _parse_line(self, name: str, line: str, line_number: int):
        if line.strip() == "":
            raise RelationStoreCorrupt("BLANK_LINE", "blank line", authority=name, line_number=line_number)
        try:
            payload = json.loads(line)
        except ValueError:
            raise RelationStoreCorrupt("MALFORMED_JSON", "line is not JSON", authority=name,
                                       line_number=line_number) from None
        if not isinstance(payload, dict):
            raise RelationStoreCorrupt("NOT_AN_OBJECT", "line is not a JSON object", authority=name,
                                       line_number=line_number)
        try:
            record = parse_relation_record(payload)
        except RelationModelError as exc:
            reason = "UNSUPPORTED_SCHEMA_VERSION" if exc.code == "UNSUPPORTED_SCHEMA_VERSION" else "INVALID_RECORD"
            raise RelationStoreCorrupt(reason, str(exc), authority=name, line_number=line_number) from None
        except Exception as exc:
            raise RelationStoreCorrupt("INVALID_RECORD", str(exc), authority=name, line_number=line_number) from None
        expected = RELATION_ASSERTION_SCHEMA_VERSION if name == "assertions" else RELATION_GOVERNANCE_SCHEMA_VERSION
        if record.schema_version != expected:
            raise RelationStoreCorrupt("WRONG_AUTHORITY", f"{record.schema_version} does not belong to {name}",
                                       authority=name, line_number=line_number)
        if canonical_relation_line(record) != line:
            raise RelationStoreCorrupt("NON_CANONICAL_LINE", "line is not the canonical serialization of its record",
                                       authority=name, line_number=line_number)
        return record

    def _index(self, name: str, record) -> None:
        if name == "assertions":
            self._assertions_by_edge.setdefault(record.edge_key, []).append(record.relation_assertion_id)
            if record.previous_assertion_id:
                self._assertion_children.setdefault(record.previous_assertion_id, []).append(record.relation_assertion_id)
        else:
            self._events_by_edge.setdefault(record.edge_key, []).append(record.event_id)
            if record.previous_event_id:
                self._event_children.setdefault(record.previous_event_id, []).append(record.event_id)

    # ------------------------------------------------------------ validation（load と append で共有）

    @staticmethod
    def _reject(for_append: bool, code: str, detail: str, *, authority: str, line_number: int = 0):
        if for_append:
            raise RelationAppendRejected(code, detail, authority=authority)
        raise RelationInvalidHistory(code, detail, authority=authority, line_number=line_number)

    def _validate(self, name: str, record, *, for_append: bool, line_number: int = 0) -> None:
        if name == "assertions":
            self._validate_assertion(record, for_append, line_number)
        else:
            self._validate_governance(record, for_append, line_number)

    def _terminal_assertion(self, edge_key: str) -> Optional[str]:
        ids = self._assertions_by_edge.get(edge_key, [])
        terminals = [i for i in ids if not self._assertion_children.get(i)]
        return terminals[0] if len(terminals) == 1 else None

    def _terminal_event(self, edge_key: str) -> Optional[str]:
        ids = self._events_by_edge.get(edge_key, [])
        terminals = [i for i in ids if not self._event_children.get(i)]
        return terminals[0] if len(terminals) == 1 else None

    def _validate_assertion(self, record: ThemeRelationAssertion, for_append: bool, line_number: int) -> None:
        stored = self._authorities["assertions"].entries
        existing = self._assertions_by_edge.get(record.edge_key, [])
        if record.previous_assertion_id == "":
            if existing:
                self._reject(for_append, "EDGE_ALREADY_STARTED",
                             f"{record.edge_key} already carries an assertion history", authority="assertions",
                             line_number=line_number)
            return
        predecessor = stored.get(record.previous_assertion_id)
        if predecessor is None:
            self._reject(for_append, "MISSING_PREDECESSOR", f"{record.previous_assertion_id} is not stored",
                         authority="assertions", line_number=line_number)
        if predecessor.record.edge_key != record.edge_key:
            self._reject(for_append, "PREDECESSOR_WRONG_EDGE", "the predecessor belongs to another relation history",
                         authority="assertions", line_number=line_number)
        if record.recorded_at < predecessor.record.recorded_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "a correction cannot precede its predecessor",
                         authority="assertions", line_number=line_number)
        if self._assertion_children.get(record.previous_assertion_id):
            self._reject(for_append, "NOT_TERMINAL_PREDECESSOR", "a relation history does not fork",
                         authority="assertions", line_number=line_number)

    def _validate_governance(self, record: ThemeRelationGovernanceEvent, for_append: bool, line_number: int) -> None:
        assertions = self._authorities["assertions"].entries
        edge_assertions = self._assertions_by_edge.get(record.edge_key, [])
        if not edge_assertions:
            self._reject(for_append, "UNKNOWN_EDGE", f"{record.edge_key} has no stored assertion",
                         authority="governance", line_number=line_number)
        subject = assertions.get(record.subject_assertion_id)
        if subject is None or subject.record.edge_key != record.edge_key:
            self._reject(for_append, "INVALID_GOVERNANCE_TARGET", "the subject assertion does not belong to this edge",
                         authority="governance", line_number=line_number)
        stored_events = self._authorities["governance"].entries
        if record.previous_event_id == "":
            if self._events_by_edge.get(record.edge_key):
                self._reject(for_append, "EDGE_ALREADY_STARTED", f"{record.edge_key} already carries governance history",
                             authority="governance", line_number=line_number)
            if record.event_type is not RelationGovernanceEventType.RETRACTED:
                self._reject(for_append, "INVALID_GOVERNANCE_SEQUENCE", "a governance history starts with a retraction",
                             authority="governance", line_number=line_number)
            return
        predecessor = stored_events.get(record.previous_event_id)
        if predecessor is None:
            self._reject(for_append, "MISSING_PREDECESSOR", f"{record.previous_event_id} is not stored",
                         authority="governance", line_number=line_number)
        if predecessor.record.edge_key != record.edge_key:
            self._reject(for_append, "PREDECESSOR_WRONG_EDGE", "the predecessor belongs to another relation history",
                         authority="governance", line_number=line_number)
        if record.recorded_at < predecessor.record.recorded_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "an event cannot precede its predecessor",
                         authority="governance", line_number=line_number)
        if self._event_children.get(record.previous_event_id):
            self._reject(for_append, "NOT_TERMINAL_PREDECESSOR", "a governance history does not fork",
                         authority="governance", line_number=line_number)
        if record.event_type is predecessor.record.event_type:
            self._reject(for_append, "INVALID_GOVERNANCE_SEQUENCE", "retraction and restoration alternate",
                         authority="governance", line_number=line_number)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        for authority in self._authorities.values():
            actual = authority.path.stat().st_size if authority.path.exists() else -1
            if actual != authority.expected_size:
                raise RelationConcurrentModification(authority.name, authority.expected_size, actual)

    def _append(self, name: str, record) -> AppendResult:
        if self.read_only:
            raise RelationAppendRejected("READ_ONLY", "store was opened read-only", authority=name)
        self.verify_unchanged()
        authority = self._authorities[name]
        rid = _record_id(name, record)
        line = canonical_relation_line(record)
        existing = authority.entries.get(rid)
        if existing is not None:
            if existing.line == line:
                return AppendResult(name, rid, AppendStatus.ALREADY_PRESENT)
            raise RelationConflict(rid, authority=name)
        self._validate(name, record, for_append=True)
        self._write_line(authority, line)
        authority.entries[rid] = _Entry(len(authority.entries) + 1, line, record)
        self._index(name, record)
        return AppendResult(name, rid, AppendStatus.APPENDED)

    def _write_line(self, authority: _Authority, line: str) -> None:
        data = line.encode(ENCODING)
        with authority.path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        authority.expected_size += len(data)

    def append_assertion(self, record: ThemeRelationAssertion) -> AppendResult:
        if not isinstance(record, ThemeRelationAssertion):
            raise RelationAppendRejected("INVALID_TYPE", "append_assertion takes a ThemeRelationAssertion",
                                         authority="assertions")
        return self._append("assertions", record)

    def append_event(self, record: ThemeRelationGovernanceEvent) -> AppendResult:
        if not isinstance(record, ThemeRelationGovernanceEvent):
            raise RelationAppendRejected("INVALID_TYPE", "append_event takes a ThemeRelationGovernanceEvent",
                                         authority="governance")
        return self._append("governance", record)

    # ------------------------------------------------------------ read

    def counts(self) -> Dict[str, int]:
        return {name: len(a.entries) for name, a in self._authorities.items()}

    def canonical_lines(self, name: str) -> Tuple[str, ...]:
        return tuple(e.line for e in self._authorities[name].entries.values())

    def assertions(self) -> Tuple[ThemeRelationAssertion, ...]:
        return tuple(e.record for e in self._authorities["assertions"].entries.values())  # type: ignore[misc]

    def governance_events(self) -> Tuple[ThemeRelationGovernanceEvent, ...]:
        return tuple(e.record for e in self._authorities["governance"].entries.values())  # type: ignore[misc]

    def get_assertion(self, relation_assertion_id: str) -> Optional[ThemeRelationAssertion]:
        entry = self._authorities["assertions"].entries.get(relation_assertion_id)
        return entry.record if entry else None  # type: ignore[return-value]

    def edge_keys(self) -> Tuple[str, ...]:
        return tuple(sorted(self._assertions_by_edge))


# ---------------------------------------------------------------- store を通した解決（IO ありの便宜 API）


def resolve_relations_at_data_root(data_root: Union[str, "os.PathLike[str]"], *, cutoff,
                                   endpoint_lookup: EndpointLookup) -> ThemeRelationResolution:
    """store を read-only で読み、純 resolver に渡す。破損 / 不整合は status として返す（例外にしない）。"""
    try:
        store = ThemeRelationStore.open(data_root, read_only=True)
    except RelationStoreCorrupt as exc:
        return _failure(cutoff, RelationResolutionStatus.STORE_CORRUPTION, exc)
    except RelationInvalidHistory as exc:
        return _failure(cutoff, RelationResolutionStatus.INVALID_HISTORY, exc)
    return resolve_relation_graph(store.assertions(), store.governance_events(), cutoff=cutoff,
                                  endpoint_lookup=endpoint_lookup)


def _failure(cutoff, status: RelationResolutionStatus, exc: RelationStoreError) -> ThemeRelationResolution:
    return ThemeRelationResolution(resolver_version=RELATION_RESOLVER_VERSION, cutoff=cutoff, status=status, edges=(),
                                   unresolved=(), excluded=(),
                                   diagnostics=(RelationDiagnostic(code=exc.code, detail=f"{exc.authority}:{exc.line_number}"),))


__all__ = ["AUTHORITY_FILENAMES", "AppendResult", "AppendStatus", "CORRUPTION_REASONS", "HISTORY_REASONS",
           "RELATION_DIRNAME", "RelationAppendRejected", "RelationConcurrentModification", "RelationConflict",
           "RelationFailureCategory", "RelationInvalidHistory", "RelationStoreCorrupt", "RelationStoreError",
           "ThemeRelationStore", "WRITER_GUARANTEE", "authority_paths", "relations_dir",
           "resolve_relations_at_data_root"]
