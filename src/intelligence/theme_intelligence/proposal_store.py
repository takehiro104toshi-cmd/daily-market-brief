"""Proposal store（P6-B3）— `<data_root>/theme_intelligence/` の 2 authority を 1 writer が所有する追記専用 JSONL store。

Foundation `<data_root>/themes/` とは別 authority。本 store は Foundation の JSONL を読みも書きもしない。
規律（P5 / Foundation を継承）: 明示 data_root、canonical 行のみ append、write → flush → fsync、同 id ＋ byte 一致 ＝ 冪等、
同 id ＋ 異 bytes ＝ CONFLICT、破損 / 非 canonical / 切断行は fail closed、読み飛ばさない、修復しない、migration しない、
外部変更は byte 長で検知（single writer）。SQLite は無い。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple, Union

from .proposal_model import (ALLOWED_DECISIONS, CounterpartKind, DedupReviewProposal, EvidenceCandidateProposal,
                             Proposal, ProposalDecision, ProposalModelError, ProposalType, ThemeCandidateProposal,
                             canonical_proposal_line, parse_proposal)

PROPOSAL_DIRNAME = "theme_intelligence"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"
AUTHORITY_FILENAMES: Mapping[str, str] = {"proposals": "proposals.jsonl", "decisions": "proposal_decisions.jsonl"}
LOAD_ORDER: Tuple[str, ...] = ("proposals", "decisions")
CORRUPTION_REASONS: Tuple[str, ...] = ("AUTHORITY_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                       "MALFORMED_JSON", "NOT_AN_OBJECT", "INVALID_RECORD", "UNSUPPORTED_SCHEMA_VERSION",
                                       "NON_CANONICAL_LINE", "PHYSICAL_DUPLICATE_IDENTICAL", "PHYSICAL_DUPLICATE_CONFLICTING")
HISTORY_REASONS: Tuple[str, ...] = ("PROPOSAL_NOT_FOUND", "SUBJECT_PROPOSAL_MISSING", "SUBJECT_NOT_THEME_CANDIDATE",
                                    "COUNTERPART_PROPOSAL_MISSING", "TARGET_PROPOSAL_MISSING", "DECISION_NOT_ALLOWED",
                                    "DANGLING_PREDECESSOR", "WRONG_PROPOSAL_PREDECESSOR", "NON_TERMINAL_PREDECESSOR",
                                    "MISSING_PREDECESSOR", "NON_MONOTONIC_RECORDED_AT", "FORKED_PROPOSAL", "INVALID_TYPE")


class FailureCategory(str, Enum):
    STORE_CORRUPTION = "STORE_CORRUPTION"
    INVALID_HISTORY = "INVALID_HISTORY"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONFLICT = "CONFLICT"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"


class ProposalStoreError(Exception):
    category: FailureCategory = FailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, authority: str = "", line_number: int = 0) -> None:
        self.code, self.detail, self.authority, self.line_number = code, detail, authority, line_number
        where = f" [{authority}:{line_number}]" if authority else ""
        super().__init__(f"{self.category.value}/{code}{where}: {detail}" if detail else f"{self.category.value}/{code}{where}")


class ProposalStoreCorrupt(ProposalStoreError):
    category = FailureCategory.STORE_CORRUPTION


class ProposalInvalidHistory(ProposalStoreError):
    category = FailureCategory.INVALID_HISTORY


class ProposalAppendRejected(ProposalStoreError):
    category = FailureCategory.APPEND_REJECTED


class ProposalConflict(ProposalStoreError):
    category = FailureCategory.CONFLICT

    def __init__(self, record_id: str, *, authority: str) -> None:
        super().__init__("CONFLICT", f"{record_id} exists with different canonical bytes", authority=authority)


class ProposalConcurrentModification(ProposalStoreError):
    category = FailureCategory.CONCURRENT_MODIFICATION

    def __init__(self, authority: str, expected: int, actual: int) -> None:
        super().__init__("CONCURRENT_MODIFICATION", f"{authority} changed size {expected} -> {actual} outside this writer",
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
class HistoryDiagnostic:
    kind: str            # DECISION_FORK / DECISION_MULTIPLE_STARTS
    proposal_id: str
    subject_id: str
    children: Tuple[str, ...]


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


def proposals_dir(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    return Path(data_root) / PROPOSAL_DIRNAME


def authority_paths(data_root: Union[str, "os.PathLike[str]"]) -> Dict[str, Path]:
    return {name: proposals_dir(data_root) / filename for name, filename in AUTHORITY_FILENAMES.items()}


def _record_id(name: str, record) -> str:
    return record.proposal_id if name == "proposals" else record.decision_id


class ProposalStore:
    """proposal / decision の append-only authority。Foundation store とは別 object・別 directory。"""

    def __init__(self, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False, _create: bool = False) -> None:
        if data_root is None or str(data_root).strip() == "":
            raise ProposalAppendRejected("DATA_ROOT_REQUIRED", "an explicit data_root is required (no repository fallback)")
        self.data_root = Path(data_root)
        self.read_only = read_only
        self._authorities = {name: _Authority(name, path) for name, path in authority_paths(self.data_root).items()}
        self._reset_index()
        if _create:
            proposals_dir(self.data_root).mkdir(parents=True, exist_ok=True)
            for authority in self._authorities.values():
                if not authority.path.exists():
                    with authority.path.open("a", encoding=ENCODING):
                        pass
        self.reload()

    @classmethod
    def initialize(cls, data_root: Union[str, "os.PathLike[str]"]) -> "ProposalStore":
        return cls(data_root, _create=True)

    @classmethod
    def open(cls, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False) -> "ProposalStore":
        return cls(data_root, read_only=read_only)

    @property
    def paths(self) -> Mapping[str, Path]:
        return {name: a.path for name, a in self._authorities.items()}

    # ------------------------------------------------------------ load

    def _reset_index(self) -> None:
        self._decisions_by_proposal: Dict[str, List[str]] = {}
        self._decision_children: Dict[str, List[str]] = {}
        self._forked_proposals: set = set()
        self._diagnostics: List[HistoryDiagnostic] = []

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
            raise ProposalStoreCorrupt("AUTHORITY_MISSING", f"{authority.path.name} is missing", authority=name, line_number=0)
        raw = authority.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise ProposalStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}", authority=name, line_number=0) from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise ProposalStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator", authority=name,
                                       line_number=text.count(LINE_TERMINATOR) + 1)
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            record = self._parse_line(name, line, line_number)
            rid = _record_id(name, record)
            previous = authority.entries.get(rid)
            if previous is not None:
                reason = "PHYSICAL_DUPLICATE_IDENTICAL" if previous.line == line else "PHYSICAL_DUPLICATE_CONFLICTING"
                raise ProposalStoreCorrupt(reason, f"{rid} first seen at line {previous.line_number}", authority=name,
                                           line_number=line_number)
            self._validate(name, record, for_append=False, line_number=line_number)
            authority.entries[rid] = _Entry(line_number, line, record)
            self._index(name, record)
        authority.expected_size = len(raw)

    def _parse_line(self, name: str, line: str, line_number: int):
        if line.strip() == "":
            raise ProposalStoreCorrupt("BLANK_LINE", "blank line", authority=name, line_number=line_number)
        try:
            payload = json.loads(line)
        except ValueError:
            raise ProposalStoreCorrupt("MALFORMED_JSON", "line is not JSON", authority=name, line_number=line_number) from None
        if not isinstance(payload, dict):
            raise ProposalStoreCorrupt("NOT_AN_OBJECT", "line is not a JSON object", authority=name, line_number=line_number)
        try:
            record = parse_proposal(payload) if name == "proposals" else ProposalDecision.from_dict(payload)
        except ProposalModelError as exc:
            reason = "UNSUPPORTED_SCHEMA_VERSION" if exc.code == "UNSUPPORTED_SCHEMA_VERSION" else "INVALID_RECORD"
            raise ProposalStoreCorrupt(reason, str(exc), authority=name, line_number=line_number) from None
        except Exception as exc:   # Foundation model の検証失敗も record として無効
            raise ProposalStoreCorrupt("INVALID_RECORD", str(exc), authority=name, line_number=line_number) from None
        if canonical_proposal_line(record) != line:
            raise ProposalStoreCorrupt("NON_CANONICAL_LINE", "line is not the canonical serialization of its record",
                                       authority=name, line_number=line_number)
        return record

    def _index(self, name: str, record) -> None:
        if name == "decisions":
            self._decisions_by_proposal.setdefault(record.proposal_id, []).append(record.decision_id)
            if record.supersedes_decision_id:
                self._decision_children.setdefault(record.supersedes_decision_id, []).append(record.decision_id)

    # ------------------------------------------------------------ validation（load と append で共有）

    @staticmethod
    def _reject(for_append: bool, code: str, detail: str, *, authority: str, line_number: int = 0):
        if for_append:
            raise ProposalAppendRejected(code, detail, authority=authority)
        raise ProposalInvalidHistory(code, detail, authority=authority, line_number=line_number)

    def _validate(self, name: str, record, *, for_append: bool, line_number: int = 0) -> None:
        if name == "proposals":
            self._validate_proposal(record, for_append, line_number)
        else:
            self._validate_decision(record, for_append, line_number)

    def _validate_proposal(self, record: Proposal, for_append: bool, line_number: int) -> None:
        proposals = self._authorities["proposals"].entries
        if isinstance(record, DedupReviewProposal):
            subject = proposals.get(record.subject_proposal_id)
            if subject is None:
                self._reject(for_append, "SUBJECT_PROPOSAL_MISSING", f"subject {record.subject_proposal_id} is not stored",
                             authority="proposals", line_number=line_number)
            if not isinstance(subject.record, ThemeCandidateProposal):
                self._reject(for_append, "SUBJECT_NOT_THEME_CANDIDATE", "dedup reviews concern THEME_CANDIDATE proposals",
                             authority="proposals", line_number=line_number)
            for counterpart in record.counterparts:
                if counterpart.kind is CounterpartKind.THEME_PROPOSAL and counterpart.ref_id not in proposals:
                    self._reject(for_append, "COUNTERPART_PROPOSAL_MISSING", f"counterpart {counterpart.ref_id} is not stored",
                                 authority="proposals", line_number=line_number)
        elif isinstance(record, EvidenceCandidateProposal):
            if record.target_proposal_id and record.target_proposal_id not in proposals:
                self._reject(for_append, "TARGET_PROPOSAL_MISSING", f"target {record.target_proposal_id} is not stored",
                             authority="proposals", line_number=line_number)
        elif not isinstance(record, ThemeCandidateProposal):
            self._reject(for_append, "INVALID_TYPE", "unknown proposal record", authority="proposals", line_number=line_number)

    def _validate_decision(self, decision: ProposalDecision, for_append: bool, line_number: int) -> None:
        proposals = self._authorities["proposals"].entries
        decisions = self._authorities["decisions"].entries
        entry = proposals.get(decision.proposal_id)
        if entry is None:
            self._reject(for_append, "PROPOSAL_NOT_FOUND", f"proposal {decision.proposal_id} is not stored",
                         authority="decisions", line_number=line_number)
        proposal: Proposal = entry.record  # type: ignore[assignment]
        if decision.decision not in ALLOWED_DECISIONS[proposal.proposal_type]:
            self._reject(for_append, "DECISION_NOT_ALLOWED",
                         f"{decision.decision.value} is not allowed for {proposal.proposal_type.value}",
                         authority="decisions", line_number=line_number)
        if decision.recorded_at < proposal.created_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "decision recorded before its proposal was created",
                         authority="decisions", line_number=line_number)
        if for_append and decision.proposal_id in self._forked_proposals:
            self._reject(True, "FORKED_PROPOSAL", f"proposal {decision.proposal_id} has a decision fork on disk; no branch is selected",
                         authority="decisions")
        existing = self._decisions_by_proposal.get(decision.proposal_id, [])
        if decision.supersedes_decision_id == "":
            if existing:
                if for_append:
                    self._reject(True, "MISSING_PREDECESSOR",
                                 f"proposal {decision.proposal_id} already has decisions; supersedes_decision_id must name its terminal",
                                 authority="decisions")
                self._diagnostics.append(HistoryDiagnostic("DECISION_MULTIPLE_STARTS", decision.proposal_id, "",
                                                           tuple(existing) + (decision.decision_id,)))
                self._forked_proposals.add(decision.proposal_id)
            return
        pred_entry = decisions.get(decision.supersedes_decision_id)
        if pred_entry is None:
            self._reject(for_append, "DANGLING_PREDECESSOR", f"predecessor {decision.supersedes_decision_id} is not stored",
                         authority="decisions", line_number=line_number)
        predecessor: ProposalDecision = pred_entry.record  # type: ignore[assignment]
        if predecessor.proposal_id != decision.proposal_id:
            self._reject(for_append, "WRONG_PROPOSAL_PREDECESSOR", "predecessor decides a different proposal",
                         authority="decisions", line_number=line_number)
        if predecessor.recorded_at > decision.recorded_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "decision recorded before its predecessor",
                         authority="decisions", line_number=line_number)
        children = self._decision_children.get(decision.supersedes_decision_id, [])
        if children:
            if for_append:
                self._reject(True, "NON_TERMINAL_PREDECESSOR",
                             f"{decision.supersedes_decision_id} already has successor {children[0]}; appending would fork",
                             authority="decisions")
            self._diagnostics.append(HistoryDiagnostic("DECISION_FORK", decision.proposal_id, decision.supersedes_decision_id,
                                                       tuple(children) + (decision.decision_id,)))
            self._forked_proposals.add(decision.proposal_id)

    # ------------------------------------------------------------ append（validate-before-append）

    def verify_unchanged(self) -> None:
        for authority in self._authorities.values():
            actual = authority.path.stat().st_size if authority.path.exists() else -1
            if actual != authority.expected_size:
                raise ProposalConcurrentModification(authority.name, authority.expected_size, actual)

    def _append(self, name: str, record) -> AppendResult:
        if self.read_only:
            raise ProposalAppendRejected("READ_ONLY", "store was opened read-only", authority=name)
        self.verify_unchanged()
        authority = self._authorities[name]
        rid = _record_id(name, record)
        line = canonical_proposal_line(record)
        existing = authority.entries.get(rid)
        if existing is not None:
            if existing.line == line:
                return AppendResult(name, rid, AppendStatus.ALREADY_PRESENT)
            raise ProposalConflict(rid, authority=name)
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

    def append_proposal(self, record: Proposal) -> AppendResult:
        if not isinstance(record, (ThemeCandidateProposal, EvidenceCandidateProposal, DedupReviewProposal)):
            raise ProposalAppendRejected("INVALID_TYPE", "append_proposal takes a proposal record", authority="proposals")
        return self._append("proposals", record)

    def append_decision(self, record: ProposalDecision) -> AppendResult:
        if not isinstance(record, ProposalDecision):
            raise ProposalAppendRejected("INVALID_TYPE", "append_decision takes a ProposalDecision", authority="decisions")
        return self._append("decisions", record)

    # ------------------------------------------------------------ read

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        entry = self._authorities["proposals"].entries.get(proposal_id)
        return entry.record if entry else None  # type: ignore[return-value]

    def get_decision(self, decision_id: str) -> Optional[ProposalDecision]:
        entry = self._authorities["decisions"].entries.get(decision_id)
        return entry.record if entry else None  # type: ignore[return-value]

    def proposals(self) -> Tuple[Proposal, ...]:
        return tuple(e.record for e in self._authorities["proposals"].entries.values())  # type: ignore[misc]

    def decisions(self) -> Tuple[ProposalDecision, ...]:
        return tuple(e.record for e in self._authorities["decisions"].entries.values())  # type: ignore[misc]

    def decisions_for(self, proposal_id: str) -> Tuple[ProposalDecision, ...]:
        return tuple(d for d in self.decisions() if d.proposal_id == proposal_id)

    def counts(self) -> Dict[str, int]:
        return {name: len(a.entries) for name, a in self._authorities.items()}

    def canonical_lines(self, name: str) -> Tuple[str, ...]:
        return tuple(e.line for e in self._authorities[name].entries.values())

    def diagnostics(self) -> Tuple[HistoryDiagnostic, ...]:
        return tuple(self._diagnostics)


__all__ = ["PROPOSAL_DIRNAME", "AUTHORITY_FILENAMES", "LOAD_ORDER", "WRITER_GUARANTEE", "CORRUPTION_REASONS", "HISTORY_REASONS",
           "FailureCategory", "ProposalStoreError", "ProposalStoreCorrupt", "ProposalInvalidHistory", "ProposalAppendRejected",
           "ProposalConflict", "ProposalConcurrentModification", "AppendStatus", "AppendResult", "HistoryDiagnostic",
           "ProposalStore", "proposals_dir", "authority_paths"]
