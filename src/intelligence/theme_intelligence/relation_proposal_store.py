"""P6-B5C — relation 候補と人間の決定の追記専用 store（`<data_root>/theme_intelligence/` の 2 file）。

B5B の relation authority（`relation_assertions.jsonl` / `relation_governance.jsonl`）とも、B3 の proposal
authority とも別 file・別 object。本 store は B5B の authority を読みも書きもしない。

規律（P5 / Foundation / B3 / B5B を継承）: 明示 data_root、canonical 行のみ append、write → flush → fsync、
同 id ＋ byte 一致 ＝ 冪等、同 id ＋ 異 bytes ＝ CONFLICT、破損 / 非 canonical / 切断行は fail closed、
読み飛ばさない、修復しない、migration しない、外部変更は byte 長で検知（single writer）。SQLite は無い。

decision の構造規律: 対象 proposal が実在すること、分岐 append を許さないこと、そして
SOURCE_ASSERTED としての受理は提案に出典の帰属と citation が実在する場合にのみ許すこと。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple, Union

from .relation_model import AssertionClass
from .relation_proposal_model import (RELATION_DECISION_SCHEMA_VERSION, RELATION_PROPOSAL_SCHEMA_VERSION,
                                      RelationDecisionKind, RelationProposal, RelationProposalDecision,
                                      RelationProposalError, canonical_proposal_record_line, parse_proposal_record,
                                      source_authority_available)

RELATION_PROPOSAL_DIRNAME = "theme_intelligence"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
AUTHORITY_FILENAMES: Mapping[str, str] = {"proposals": "relation_proposals.jsonl",
                                          "decisions": "relation_proposal_decisions.jsonl"}
LOAD_ORDER: Tuple[str, ...] = ("proposals", "decisions")
CORRUPTION_REASONS: Tuple[str, ...] = ("AUTHORITY_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "MALFORMED_JSON", "NOT_AN_OBJECT", "INVALID_RECORD", "UNSUPPORTED_SCHEMA_VERSION",
                                       "NON_CANONICAL_LINE", "WRONG_AUTHORITY", "PHYSICAL_DUPLICATE_IDENTICAL",
                                       "PHYSICAL_DUPLICATE_CONFLICTING")
HISTORY_REASONS: Tuple[str, ...] = ("PROPOSAL_NOT_FOUND", "MISSING_PREDECESSOR", "WRONG_PROPOSAL_PREDECESSOR",
                                    "NOT_TERMINAL_PREDECESSOR", "NON_MONOTONIC_RECORDED_AT",
                                    "FORBIDDEN_SOURCE_AUTHORITY", "INVALID_TYPE")


class ProposalFailureCategory(str, Enum):
    STORE_CORRUPTION = "STORE_CORRUPTION"
    INVALID_HISTORY = "INVALID_HISTORY"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONFLICT = "CONFLICT"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class RelationProposalStoreError(RuntimeError):
    category = ProposalFailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, authority: str = "", line_number: int = 0) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.authority = authority
        self.line_number = line_number


class RelationProposalStoreCorrupt(RelationProposalStoreError):
    category = ProposalFailureCategory.STORE_CORRUPTION


class RelationProposalInvalidHistory(RelationProposalStoreError):
    category = ProposalFailureCategory.INVALID_HISTORY


class RelationProposalAppendRejected(RelationProposalStoreError):
    category = ProposalFailureCategory.APPEND_REJECTED


class RelationProposalConflict(RelationProposalStoreError):
    category = ProposalFailureCategory.CONFLICT

    def __init__(self, record_id: str, *, authority: str) -> None:
        super().__init__("CONFLICT", f"{record_id} exists with different canonical bytes", authority=authority)


class RelationProposalConcurrentModification(RelationProposalStoreError):
    category = ProposalFailureCategory.CONCURRENT_MODIFICATION

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


def relation_proposals_dir(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    return Path(data_root) / RELATION_PROPOSAL_DIRNAME


def authority_paths(data_root: Union[str, "os.PathLike[str]"]) -> Dict[str, Path]:
    return {name: relation_proposals_dir(data_root) / filename for name, filename in AUTHORITY_FILENAMES.items()}


def _record_id(name: str, record) -> str:
    return record.proposal_id if name == "proposals" else record.decision_id


class RelationProposalStore:
    """relation 候補と決定の追記専用 authority。B5B relation authority には一切書かない。"""

    def __init__(self, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False,
                 _create: bool = False) -> None:
        if data_root is None or str(data_root).strip() == "":
            raise RelationProposalAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no fallback)")
        self.data_root = Path(data_root)
        self.read_only = read_only
        self._authorities = {name: _Authority(name, path) for name, path in authority_paths(self.data_root).items()}
        self._reset_index()
        if _create:
            relation_proposals_dir(self.data_root).mkdir(parents=True, exist_ok=True)
            for authority in self._authorities.values():
                if not authority.path.exists():
                    with authority.path.open("a", encoding=ENCODING):
                        pass
        self.reload()

    @classmethod
    def initialize(cls, data_root: Union[str, "os.PathLike[str]"]) -> "RelationProposalStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False) -> "RelationProposalStore":
        return cls(data_root, read_only=read_only)

    @property
    def paths(self) -> Mapping[str, Path]:
        return {name: a.path for name, a in self._authorities.items()}

    # ------------------------------------------------------------ load

    def _reset_index(self) -> None:
        self._decisions_by_proposal: Dict[str, List[str]] = {}
        self._decision_children: Dict[str, List[str]] = {}

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
            raise RelationProposalStoreCorrupt("AUTHORITY_MISSING", f"{authority.path.name} is missing", authority=name,
                                               line_number=0)
        raw = authority.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise RelationProposalStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}", authority=name,
                                               line_number=0) from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise RelationProposalStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator", authority=name,
                                               line_number=text.count(LINE_TERMINATOR) + 1)
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            record = self._parse_line(name, line, line_number)
            rid = _record_id(name, record)
            previous = authority.entries.get(rid)
            if previous is not None:
                reason = "PHYSICAL_DUPLICATE_IDENTICAL" if previous.line == line else "PHYSICAL_DUPLICATE_CONFLICTING"
                raise RelationProposalStoreCorrupt(reason, f"{rid} first seen at line {previous.line_number}",
                                                   authority=name, line_number=line_number)
            self._validate(name, record, for_append=False, line_number=line_number)
            authority.entries[rid] = _Entry(line_number, line, record)
            self._index(name, record)
        authority.expected_size = len(raw)

    def _parse_line(self, name: str, line: str, line_number: int):
        if line.strip() == "":
            raise RelationProposalStoreCorrupt("BLANK_LINE", "blank line", authority=name, line_number=line_number)
        try:
            payload = json.loads(line)
        except ValueError:
            raise RelationProposalStoreCorrupt("MALFORMED_JSON", "line is not JSON", authority=name,
                                               line_number=line_number) from None
        if not isinstance(payload, dict):
            raise RelationProposalStoreCorrupt("NOT_AN_OBJECT", "line is not a JSON object", authority=name,
                                               line_number=line_number)
        try:
            record = parse_proposal_record(payload)
        except RelationProposalError as exc:
            reason = "UNSUPPORTED_SCHEMA_VERSION" if exc.code == "UNSUPPORTED_SCHEMA_VERSION" else "INVALID_RECORD"
            raise RelationProposalStoreCorrupt(reason, str(exc), authority=name, line_number=line_number) from None
        except Exception as exc:
            raise RelationProposalStoreCorrupt("INVALID_RECORD", str(exc), authority=name,
                                               line_number=line_number) from None
        expected = RELATION_PROPOSAL_SCHEMA_VERSION if name == "proposals" else RELATION_DECISION_SCHEMA_VERSION
        if record.schema_version != expected:
            raise RelationProposalStoreCorrupt("WRONG_AUTHORITY", f"{record.schema_version} does not belong to {name}",
                                               authority=name, line_number=line_number)
        if canonical_proposal_record_line(record) != line:
            raise RelationProposalStoreCorrupt("NON_CANONICAL_LINE",
                                               "line is not the canonical serialization of its record",
                                               authority=name, line_number=line_number)
        return record

    def _index(self, name: str, record) -> None:
        if name == "decisions":
            self._decisions_by_proposal.setdefault(record.proposal_id, []).append(record.decision_id)
            if record.supersedes_decision_id:
                self._decision_children.setdefault(record.supersedes_decision_id, []).append(record.decision_id)

    # ------------------------------------------------------------ validation

    @staticmethod
    def _reject(for_append: bool, code: str, detail: str, *, authority: str, line_number: int = 0):
        if for_append:
            raise RelationProposalAppendRejected(code, detail, authority=authority)
        raise RelationProposalInvalidHistory(code, detail, authority=authority, line_number=line_number)

    def _validate(self, name: str, record, *, for_append: bool, line_number: int = 0) -> None:
        if name == "proposals":
            return
        self._validate_decision(record, for_append, line_number)

    def _validate_decision(self, record: RelationProposalDecision, for_append: bool, line_number: int) -> None:
        proposals = self._authorities["proposals"].entries
        subject = proposals.get(record.proposal_id)
        if subject is None:
            self._reject(for_append, "PROPOSAL_NOT_FOUND", f"{record.proposal_id} is not stored", authority="decisions",
                         line_number=line_number)
        if (record.decision is RelationDecisionKind.ACCEPT
                and record.accepted_assertion_class is AssertionClass.SOURCE_ASSERTED
                and not source_authority_available(subject.record)):
            self._reject(for_append, "FORBIDDEN_SOURCE_AUTHORITY",
                         "a source asserted acceptance needs the source attribution and citation of the proposal",
                         authority="decisions", line_number=line_number)
        decisions = self._authorities["decisions"].entries
        if record.supersedes_decision_id == "":
            return
        predecessor = decisions.get(record.supersedes_decision_id)
        if predecessor is None:
            self._reject(for_append, "MISSING_PREDECESSOR", f"{record.supersedes_decision_id} is not stored",
                         authority="decisions", line_number=line_number)
        if predecessor.record.proposal_id != record.proposal_id:
            self._reject(for_append, "WRONG_PROPOSAL_PREDECESSOR", "the predecessor decides another proposal",
                         authority="decisions", line_number=line_number)
        if record.recorded_at < predecessor.record.recorded_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "a decision cannot precede the one it supersedes",
                         authority="decisions", line_number=line_number)
        if self._decision_children.get(record.supersedes_decision_id):
            self._reject(for_append, "NOT_TERMINAL_PREDECESSOR", "a decision history does not fork",
                         authority="decisions", line_number=line_number)

    # ------------------------------------------------------------ append

    def verify_unchanged(self) -> None:
        for authority in self._authorities.values():
            actual = authority.path.stat().st_size if authority.path.exists() else -1
            if actual != authority.expected_size:
                raise RelationProposalConcurrentModification(authority.name, authority.expected_size, actual)

    def _append(self, name: str, record) -> AppendResult:
        if self.read_only:
            raise RelationProposalAppendRejected("READ_ONLY", "store was opened read-only", authority=name)
        self.verify_unchanged()
        authority = self._authorities[name]
        rid = _record_id(name, record)
        line = canonical_proposal_record_line(record)
        existing = authority.entries.get(rid)
        if existing is not None:
            if existing.line == line:
                return AppendResult(name, rid, AppendStatus.ALREADY_PRESENT)
            raise RelationProposalConflict(rid, authority=name)
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

    def append_proposal(self, record: RelationProposal) -> AppendResult:
        if not isinstance(record, RelationProposal):
            raise RelationProposalAppendRejected("INVALID_TYPE", "append_proposal takes a RelationProposal",
                                                 authority="proposals")
        return self._append("proposals", record)

    def append_decision(self, record: RelationProposalDecision) -> AppendResult:
        if not isinstance(record, RelationProposalDecision):
            raise RelationProposalAppendRejected("INVALID_TYPE", "append_decision takes a RelationProposalDecision",
                                                 authority="decisions")
        return self._append("decisions", record)

    # ------------------------------------------------------------ read

    def counts(self) -> Dict[str, int]:
        return {name: len(a.entries) for name, a in self._authorities.items()}

    def canonical_lines(self, name: str) -> Tuple[str, ...]:
        return tuple(e.line for e in self._authorities[name].entries.values())

    def proposals(self) -> Tuple[RelationProposal, ...]:
        return tuple(e.record for e in self._authorities["proposals"].entries.values())  # type: ignore[misc]

    def decisions(self) -> Tuple[RelationProposalDecision, ...]:
        return tuple(e.record for e in self._authorities["decisions"].entries.values())  # type: ignore[misc]

    def get_proposal(self, proposal_id: str) -> Optional[RelationProposal]:
        entry = self._authorities["proposals"].entries.get(proposal_id)
        return entry.record if entry else None  # type: ignore[return-value]


__all__ = ["AUTHORITY_FILENAMES", "AppendResult", "AppendStatus", "CORRUPTION_REASONS", "HISTORY_REASONS",
           "ProposalFailureCategory", "RELATION_PROPOSAL_DIRNAME", "RelationProposalAppendRejected",
           "RelationProposalConcurrentModification", "RelationProposalConflict", "RelationProposalInvalidHistory",
           "RelationProposalStore", "RelationProposalStoreCorrupt", "RelationProposalStoreError",
           "WRITER_GUARANTEE", "authority_paths", "relation_proposals_dir"]
