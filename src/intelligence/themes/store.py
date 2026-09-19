"""Theme canonical store（Phase 6 P6-A4b）— 5 authority を 1 writer が所有する追記専用 JSONL store。

契約: docs/databank/PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md（A3）§3〜§9・§23〜§25。前例: P5 store。

    <data_root>/themes/theme_roots.jsonl            ThemeRootRecord
    <data_root>/themes/theme_observations.jsonl     ThemeObservation
    <data_root>/themes/theme_governance.jsonl       ThemeGovernanceEvent
    <data_root>/themes/theme_metadata.jsonl         ThemeMetadataRecord
    <data_root>/themes/theme_series_mappings.jsonl  ThemeSeriesMapping

保証（誠実に、これ以上を主張しない）:
- **追記専用。** open mode は `"a"` のみ。上書き・truncate・rename・compact・sort・修復・行 skip の経路が無い。
  1 行 ＝ A4a `canonical_line(record)` の bytes。write → flush → `os.fsync()`。
- **冪等 / conflict。** 同一 id ＋ byte 一致 ＝ no-op（ALREADY_PRESENT）。同一 id ＋ bytes 差異 ＝ ThemeConflict
  （provenance / recorded_at だけの差でも。上書き・新しい方の採用・merge をしない）。
- **load は fail closed。** 非 canonical・破損・未知 schema・id 不一致・physical duplicate は ThemeStoreCorrupt
  （authority・行番号・reason code 付き）。個々に valid でも履歴として不可能なら ThemeInvalidHistory。黙って skip しない。
- **load は read-only。** file を作らず、append・修復・PENDING 完了・id 生成をしない（`initialize` だけが空 file を作る）。
- **SINGLE_WRITER。** 1 process の 1 store object が 5 file を所有する。複数 process・複数 writer・並行 append・
  cross-file transaction の安全性は保証しない。file ごとの byte 長を記憶し、append 前に外部変化（増減）を検知して
  fail closed する（lock ではない。検知できない競合は保証外）。
- **宣言が先、完了が後。** MERGE / SPLIT / SUPERSEDED_BY_ROOT は event（result root id を宣言）→ 結果 RootRecord →
  結果 genesis の順。途中で止まれば PENDING_EVENT / PENDING_GENESIS として **明示**され、自動では完了しない
  （`operations.py` の plan を同じ入力で再実行すると冪等に完了する）。
- **resolver ではない。** 点時刻状態・governance 状態・lifecycle・latest / current を返す API は無い。append の安全性に
  必要な **物理 terminal**（predecessor に子が無いこと）だけを検査する。file 上の fork は選ばず、診断として返す。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple, Union

from .model import (CreationMethod, EvidenceAllocation, GovernanceEventType, MetadataField, ThemeGovernanceEvent,
                    ThemeMetadataRecord, ThemeModelError, ThemeObservation, ThemeRootRecord, ThemeSeriesMapping,
                    canonical_json, canonical_line)

THEMES_DIRNAME = "themes"
ENCODING = "utf-8"
LINE_TERMINATOR = "\n"
WRITER_GUARANTEE = "SINGLE_WRITER"

#: authority 名 → file 名（A3 §3。load 順は LOAD_ORDER）
AUTHORITY_FILENAMES: Mapping[str, str] = {
    "roots": "theme_roots.jsonl",
    "observations": "theme_observations.jsonl",
    "governance": "theme_governance.jsonl",
    "metadata": "theme_metadata.jsonl",
    "mappings": "theme_series_mappings.jsonl",
}
LOAD_ORDER: Tuple[str, ...] = ("roots", "observations", "governance", "metadata", "mappings")
_RECORD_TYPES = {"roots": ThemeRootRecord, "observations": ThemeObservation, "governance": ThemeGovernanceEvent,
                 "metadata": ThemeMetadataRecord, "mappings": ThemeSeriesMapping}
_ID_FIELDS = {"roots": "root_id", "observations": "observation_id", "governance": "event_id",
              "metadata": "metadata_id", "mappings": "mapping_id"}

#: STORE_CORRUPTION の reason code（A3 §23）
CORRUPTION_REASONS: Tuple[str, ...] = (
    "AUTHORITY_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE", "MALFORMED_JSON", "NOT_AN_OBJECT",
    "INVALID_RECORD", "UNSUPPORTED_SCHEMA_VERSION", "NON_CANONICAL_LINE", "PHYSICAL_DUPLICATE_IDENTICAL",
    "PHYSICAL_DUPLICATE_CONFLICTING",
)
#: INVALID_HISTORY（load）/ APPEND_REJECTED（append）で共有する reason code（A3 §7 / §23）
HISTORY_REASONS: Tuple[str, ...] = (
    "ROOT_NOT_FOUND", "GENESIS_MISMATCH", "DANGLING_PREDECESSOR", "WRONG_ROOT_PREDECESSOR", "NON_TERMINAL_PREDECESSOR",
    "NON_MONOTONIC_RECORDED_AT", "OBSERVATION_BEFORE_ROOT", "ATTACHED_AT_OUT_OF_RANGE", "FORKED_ROOT",
    "ORIGIN_EVENT_MISSING", "ORIGIN_EVENT_MISMATCH", "RESULT_ROOT_NOT_DECLARED", "RESULT_ROOT_DECLARED_ELSEWHERE",
    "RESULT_ROOT_ALREADY_EXISTS", "RESULT_ROOT_REDECLARED", "GOVERNANCE_REFERENCE_MISSING", "MISSING_PREVIOUS_EVENT",
    "MALFORMED_REVERSAL", "ALLOCATION_VIOLATION", "METADATA_PREDECESSOR_MISSING", "MISSING_PREVIOUS_METADATA",
    "MAPPING_PREDECESSOR_MISSING", "MAPPING_CONSEQUENCE_UNKNOWN", "NON_CANONICAL_RECORD", "INVALID_TYPE",
)


# ---------------------------------------------------------------- errors / results

class FailureCategory(str, Enum):
    STORE_CORRUPTION = "STORE_CORRUPTION"
    INVALID_HISTORY = "INVALID_HISTORY"
    APPEND_REJECTED = "APPEND_REJECTED"
    CONFLICT = "CONFLICT"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    READ_ONLY = "READ_ONLY"


class ThemeStoreError(Exception):
    """store の失敗。`category` / `code` は機械可読。"""

    category: FailureCategory = FailureCategory.APPEND_REJECTED

    def __init__(self, code: str, detail: str = "", *, authority: str = "", line_number: int = 0) -> None:
        self.code = code
        self.detail = detail
        self.authority = authority
        self.line_number = line_number
        where = f" [{authority}:{line_number}]" if authority else ""
        super().__init__(f"{self.category.value}/{code}{where}: {detail}" if detail
                         else f"{self.category.value}/{code}{where}")


class ThemeStoreCorrupt(ThemeStoreError):
    """bytes / 行が信用できない（A3 §23 STORE_CORRUPTION）。store 全体の load が失敗する。"""

    category = FailureCategory.STORE_CORRUPTION

    def __init__(self, code: str, detail: str = "", *, authority: str, line_number: int) -> None:
        if code not in CORRUPTION_REASONS:
            raise ValueError(f"unknown corruption reason: {code!r}")
        super().__init__(code, detail, authority=authority, line_number=line_number)


class ThemeInvalidHistory(ThemeStoreError):
    """個々の record は valid だが履歴として不可能（A3 §23 INVALID_HISTORY）。store 全体の load が失敗する。"""

    category = FailureCategory.INVALID_HISTORY


class ThemeAppendRejected(ThemeStoreError):
    """validate-before-append の拒否（A3 §7）。何も書かれていない。"""

    category = FailureCategory.APPEND_REJECTED


class ThemeConflict(ThemeStoreError):
    """同一 id ＋ 異 bytes（A3 §7 CONFLICT）。上書きも新しい方の採用もしない。"""

    category = FailureCategory.CONFLICT

    def __init__(self, record_id: str, differing_fields: Tuple[str, ...], *, authority: str) -> None:
        self.record_id = record_id
        self.differing_fields = differing_fields
        super().__init__("CONFLICT", f"{record_id} already stored with different {', '.join(differing_fields) or 'bytes'}",
                         authority=authority)


class ConcurrentModificationDetected(ThemeStoreError):
    """append 前の byte 長検査で外部変化を検知（A3 §8。lock ではなく検知）。"""

    category = FailureCategory.CONCURRENT_MODIFICATION

    def __init__(self, authority: str, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__("CONCURRENT_MODIFICATION",
                         f"{AUTHORITY_FILENAMES[authority]} changed on disk (expected {expected} bytes, found {actual}); "
                         f"{WRITER_GUARANTEE} boundary violated — reload before appending", authority=authority)


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    status: AppendStatus
    authority: str
    record_id: str
    line_number: int
    wrote_line: bool


class PendingKind(str, Enum):
    PENDING_GENESIS = "PENDING_GENESIS"   # RootRecord はあるが宣言された genesis observation が無い
    PENDING_EVENT = "PENDING_EVENT"       # 宣言 event はあるが result root / genesis が揃っていない


@dataclass(frozen=True)
class PendingItem:
    """明示の未完了状態（A3 §9 / §20）。corruption ではなく、自動では完了しない。"""

    kind: PendingKind
    subject_id: str            # root_id（PENDING_GENESIS）/ event_id（PENDING_EVENT）
    missing: Tuple[str, ...]   # 欠けている record の id（genesis: "thobs_…"、root: "theme_…"）
    detail: str = ""


@dataclass(frozen=True)
class HistoryDiagnostic:
    """load 時に検出した曖昧構造（fork 等）。A4b は選ばない・直さない。UNRESOLVED の判定は A4c。"""

    kind: str          # FORK / GOVERNANCE_FORK / GOVERNANCE_MULTIPLE_STARTS / METADATA_FORK / METADATA_MULTIPLE_STARTS / MAPPING_FORK
    authority: str
    root_id: str
    subject_id: str    # predecessor id 等
    children: Tuple[str, ...]


@dataclass(frozen=True)
class StoreAudit:
    data_root: str
    counts: Mapping[str, int]
    sizes: Mapping[str, int]
    pending: Tuple[PendingItem, ...]
    diagnostics: Tuple[HistoryDiagnostic, ...]


@dataclass(frozen=True)
class _Entry:
    line_number: int
    line: str
    record: object


class _Authority:
    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        self.path = path
        self.entries: Dict[str, _Entry] = {}
        self.expected_size = 0


def themes_dir(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    if data_root is None or str(data_root) == "":
        raise ValueError("data_root must be an explicit, non-empty path (no repository fallback)")
    return Path(data_root) / THEMES_DIRNAME


def authority_paths(data_root: Union[str, "os.PathLike[str]"]) -> Dict[str, Path]:
    base = themes_dir(data_root)
    return {name: base / filename for name, filename in AUTHORITY_FILENAMES.items()}


def _record_id(authority: str, record) -> str:
    return getattr(record, _ID_FIELDS[authority])


def _differing_fields(stored, offered) -> Tuple[str, ...]:
    a, b = stored.as_dict(), offered.as_dict()
    return tuple(sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k)))


# ---------------------------------------------------------------- store

class ThemeStore:
    """5 authority の唯一の所有者。`initialize`（明示の書込み）/ `open`（read-only load）/ `audit` で得る。"""

    def __init__(self, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False,
                 _initialized_by_factory: bool = False) -> None:
        if not _initialized_by_factory:
            raise TypeError("use ThemeStore.open(data_root) / ThemeStore.initialize(data_root)")
        self.data_root = Path(data_root)
        self.read_only = read_only
        self._paths = authority_paths(data_root)
        self._authorities: Dict[str, _Authority] = {n: _Authority(n, self._paths[n]) for n in LOAD_ORDER}
        self._reset_index()
        self.reload()

    # ------------------------------------------------------------ factories

    @classmethod
    def initialize(cls, data_root: Union[str, "os.PathLike[str]"]) -> "ThemeStore":
        """明示の書込み操作: `<data_root>/themes/` と 5 つの空 authority file を作る（既存は触らない。冪等）。"""
        base = themes_dir(data_root)
        base.mkdir(parents=True, exist_ok=True)
        for path in authority_paths(data_root).values():
            if not path.exists():
                with path.open("a", encoding=ENCODING, newline=LINE_TERMINATOR) as handle:
                    handle.flush()
                    os.fsync(handle.fileno())
        return cls(data_root, _initialized_by_factory=True)

    @classmethod
    def open(cls, data_root: Union[str, "os.PathLike[str]"], *, read_only: bool = False) -> "ThemeStore":
        """read-only load。file を作らず、書かず、修復しない。未初期化なら NOT_INITIALIZED。"""
        base = themes_dir(data_root)
        if not base.is_dir():
            error = ThemeStoreError("NOT_INITIALIZED", f"{base} does not exist; call ThemeStore.initialize explicitly")
            error.category = FailureCategory.NOT_INITIALIZED
            raise error
        return cls(data_root, read_only=read_only, _initialized_by_factory=True)

    @classmethod
    def audit(cls, data_root: Union[str, "os.PathLike[str]"]) -> StoreAudit:
        """read-only 監査（件数・byte 長・PENDING・診断）。何も書かない。"""
        store = cls.open(data_root, read_only=True)
        return StoreAudit(data_root=str(store.data_root), counts=store.counts(),
                          sizes={n: a.expected_size for n, a in store._authorities.items()},
                          pending=store.pending(), diagnostics=store.diagnostics())

    @property
    def paths(self) -> Mapping[str, Path]:
        return dict(self._paths)

    # ------------------------------------------------------------ load（read-only・fail closed）

    def _reset_index(self) -> None:
        self._obs_children: Dict[str, List[str]] = {}
        self._obs_by_root: Dict[str, List[str]] = {}
        self._events_by_root: Dict[str, List[str]] = {}
        self._event_children: Dict[Tuple[str, str], List[str]] = {}
        self._result_declared_by: Dict[str, str] = {}
        self._meta_children: Dict[str, List[str]] = {}
        self._meta_by_root_field: Dict[Tuple[str, str], List[str]] = {}
        self._map_children: Dict[str, List[str]] = {}
        self._map_by_root: Dict[str, List[str]] = {}
        self._diagnostics: List[HistoryDiagnostic] = []
        self._forked_roots: set = set()

    def reload(self) -> Dict[str, int]:
        """5 authority を固定順で全再読込（fail closed）。何も書かない。"""
        for authority in self._authorities.values():
            authority.entries = {}
            authority.expected_size = 0
        self._reset_index()
        for name in LOAD_ORDER:
            self._load_authority(self._authorities[name])
        self._validate_cross_authority()
        return self.counts()

    def _load_authority(self, authority: _Authority) -> None:
        name = authority.name
        if not authority.path.exists():
            raise ThemeStoreCorrupt("AUTHORITY_MISSING", f"{authority.path.name} is missing", authority=name, line_number=0)
        raw = authority.path.read_bytes()
        try:
            text = raw.decode(ENCODING)
        except UnicodeDecodeError as exc:
            raise ThemeStoreCorrupt("INVALID_ENCODING", f"byte {exc.start}", authority=name, line_number=0) from None
        if text and not text.endswith(LINE_TERMINATOR):
            raise ThemeStoreCorrupt("TRUNCATED_FINAL_LINE", "final line lacks its terminator", authority=name,
                                    line_number=text.count(LINE_TERMINATOR) + 1)
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            record = self._parse_line(name, line, line_number)
            rid = _record_id(name, record)
            previous = authority.entries.get(rid)
            if previous is not None:
                reason = "PHYSICAL_DUPLICATE_IDENTICAL" if previous.line == line else "PHYSICAL_DUPLICATE_CONFLICTING"
                raise ThemeStoreCorrupt(reason, f"{rid} first seen at line {previous.line_number}", authority=name,
                                        line_number=line_number)
            self._validate_history(name, record, for_append=False, line_number=line_number, phase="intra")
            authority.entries[rid] = _Entry(line_number, line, record)
            self._index(name, record)
        authority.expected_size = len(raw)

    def _parse_line(self, name: str, line: str, line_number: int):
        if not line.endswith(LINE_TERMINATOR):
            raise ThemeStoreCorrupt("TRUNCATED_FINAL_LINE", "", authority=name, line_number=line_number)
        body = line[:-1]
        if body.strip() == "":
            raise ThemeStoreCorrupt("BLANK_LINE", "", authority=name, line_number=line_number)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ThemeStoreCorrupt("MALFORMED_JSON", f"col {exc.colno}", authority=name, line_number=line_number) from None
        if not isinstance(data, dict):
            raise ThemeStoreCorrupt("NOT_AN_OBJECT", "", authority=name, line_number=line_number)
        try:
            record = _RECORD_TYPES[name].from_dict(data)
        except ThemeModelError as exc:
            reason = "UNSUPPORTED_SCHEMA_VERSION" if exc.code == "UNSUPPORTED_SCHEMA_VERSION" else "INVALID_RECORD"
            raise ThemeStoreCorrupt(reason, str(exc), authority=name, line_number=line_number) from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise ThemeStoreCorrupt("INVALID_RECORD", str(exc), authority=name, line_number=line_number) from exc
        if canonical_line(record) != line:
            raise ThemeStoreCorrupt("NON_CANONICAL_LINE", "stored bytes are not the canonical line of the decoded record",
                                    authority=name, line_number=line_number)
        return record

    # ------------------------------------------------------------ index（append 安全性のための物理 graph のみ）

    def _index(self, name: str, record) -> None:
        if name == "observations":
            self._obs_by_root.setdefault(record.root_id, []).append(record.observation_id)
            if record.previous_observation_id:
                self._obs_children.setdefault(record.previous_observation_id, []).append(record.observation_id)
        elif name == "governance":
            for root in set(record.subject_roots) | set(record.result_roots):
                self._events_by_root.setdefault(root, []).append(record.event_id)
            for root, previous in record.previous_event_ids:
                self._event_children.setdefault((root, previous), []).append(record.event_id)
            for root in record.result_roots:
                self._result_declared_by[root] = record.event_id
        elif name == "metadata":
            self._meta_by_root_field.setdefault((record.root_id, record.field.value), []).append(record.metadata_id)
            if record.previous_metadata_id:
                self._meta_children.setdefault(record.previous_metadata_id, []).append(record.metadata_id)
        elif name == "mappings":
            self._map_by_root.setdefault(record.root_id, []).append(record.mapping_id)
            if record.supersedes_mapping_id:
                self._map_children.setdefault(record.supersedes_mapping_id, []).append(record.mapping_id)

    # ------------------------------------------------------------ history validation（load と append で共有）
    #
    # load は authority を固定順（roots → observations → governance → metadata → mappings）で 1 行ずつ読む。
    # 同一 file 内・先行 authority への参照は行ごとに検査し（intra）、後続 authority への参照（root の origin event、
    # observation の carried allocation、event の result root 整合）は全 authority 読込後の第 2 pass で検査する（cross）。
    # append 時は全 authority が memory にあるので両方を即時に検査する。

    @staticmethod
    def _reject(for_append: bool, code: str, detail: str, *, authority: str, line_number: int = 0):
        if for_append:
            raise ThemeAppendRejected(code, detail, authority=authority)
        raise ThemeInvalidHistory(code, detail, authority=authority, line_number=line_number)

    def _validate_history(self, name: str, record, *, for_append: bool, line_number: int = 0,
                          phase: str = "all") -> None:
        intra = phase in ("all", "intra")
        cross = phase in ("all", "cross")
        if name == "roots" and cross:
            self._validate_root(record, for_append, line_number)
        elif name == "observations":
            if intra:
                self._validate_observation_chain(record, for_append, line_number)
            if cross:
                self._validate_observation_attachments(record, for_append, line_number)
        elif name == "governance":
            if intra:
                self._validate_event(record, for_append, line_number)
            if cross:
                self._validate_event_results(record, for_append, line_number)
        elif name == "metadata" and intra:
            self._validate_metadata(record, for_append, line_number)
        elif name == "mappings" and intra:
            self._validate_mapping(record, for_append, line_number)

    def _validate_cross_authority(self) -> None:
        """第 2 pass（load のみ）: 後続 authority への参照を検査する。何も書かない。"""
        for name in ("roots", "observations", "governance"):
            for entry in list(self._authorities[name].entries.values()):
                self._validate_history(name, entry.record, for_append=False, line_number=entry.line_number,
                                       phase="cross")

    def _validate_root(self, root: ThemeRootRecord, for_append: bool, line_number: int) -> None:
        events = self._authorities["governance"].entries
        if root.creation_method is CreationMethod.CANDIDATE:
            if root.root_id in self._result_declared_by:
                self._reject(for_append, "RESULT_ROOT_DECLARED_ELSEWHERE",
                             f"{root.root_id} is declared as a result root by {self._result_declared_by[root.root_id]}",
                             authority="roots", line_number=line_number)
            return
        entry = events.get(root.origin_event_id)
        if entry is None:
            self._reject(for_append, "ORIGIN_EVENT_MISSING",
                         f"origin event {root.origin_event_id} must be appended before the result root (declaration first)",
                         authority="roots", line_number=line_number)
        event: ThemeGovernanceEvent = entry.record  # type: ignore[assignment]
        expected = {CreationMethod.MERGE_RESULT: GovernanceEventType.MERGE,
                    CreationMethod.SPLIT_RESULT: GovernanceEventType.SPLIT,
                    CreationMethod.SUCCESSOR_RESULT: GovernanceEventType.SUPERSEDED_BY_ROOT}[root.creation_method]
        if event.event_type is not expected:
            self._reject(for_append, "ORIGIN_EVENT_MISMATCH",
                         f"{root.creation_method.value} root cites a {event.event_type.value} event",
                         authority="roots", line_number=line_number)
        if root.root_id not in event.result_roots:
            self._reject(for_append, "RESULT_ROOT_NOT_DECLARED", f"{event.event_id} does not declare {root.root_id}",
                         authority="roots", line_number=line_number)
        if root.created_at < event.recorded_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "result root created before its declaring event",
                         authority="roots", line_number=line_number)

    def _carried_allowance(self, root: ThemeRootRecord) -> Dict[str, str]:
        """origin event がこの root に配分した attachment_key → source observation id。CANDIDATE では空。"""
        if root.creation_method is CreationMethod.CANDIDATE:
            return {}
        entry = self._authorities["governance"].entries.get(root.origin_event_id)
        if entry is None:
            return {}
        return {a.attachment_key: a.source_observation_id for a in entry.record.evidence_allocation
                if a.result_root_id == root.root_id}

    def _validate_observation_chain(self, obs: ThemeObservation, for_append: bool, line_number: int) -> None:
        roots = self._authorities["roots"].entries
        observations = self._authorities["observations"].entries
        root_entry = roots.get(obs.root_id)
        if root_entry is None:
            self._reject(for_append, "ROOT_NOT_FOUND", f"root {obs.root_id} is not stored", authority="observations",
                         line_number=line_number)
        root: ThemeRootRecord = root_entry.record  # type: ignore[assignment]
        if obs.recorded_at < root.created_at:
            self._reject(for_append, "OBSERVATION_BEFORE_ROOT", "observation recorded before its root was created",
                         authority="observations", line_number=line_number)
        if for_append and obs.root_id in self._forked_roots:
            self._reject(for_append, "FORKED_ROOT",
                         f"root {obs.root_id} has a fork on disk; no branch is selected (A3 §5) — human decision required",
                         authority="observations")
        if obs.is_genesis:
            if obs.observation_id != root.genesis_observation_id:
                self._reject(for_append, "GENESIS_MISMATCH",
                             f"root declares genesis {root.genesis_observation_id}, got {obs.observation_id}",
                             authority="observations", line_number=line_number)
            return
        pred_entry = observations.get(obs.previous_observation_id)
        if pred_entry is None:
            self._reject(for_append, "DANGLING_PREDECESSOR",
                         f"predecessor {obs.previous_observation_id} is not physically before this observation",
                         authority="observations", line_number=line_number)
        predecessor: ThemeObservation = pred_entry.record  # type: ignore[assignment]
        if predecessor.root_id != obs.root_id:
            self._reject(for_append, "WRONG_ROOT_PREDECESSOR", "predecessor belongs to a different root",
                         authority="observations", line_number=line_number)
        if predecessor.recorded_at > obs.recorded_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "observation recorded before its predecessor",
                         authority="observations", line_number=line_number)
        children = self._obs_children.get(obs.previous_observation_id, [])
        if children:
            if for_append:
                self._reject(True, "NON_TERMINAL_PREDECESSOR",
                             f"{obs.previous_observation_id} already has successor {children[0]}; appending would fork",
                             authority="observations")
            self._diagnostics.append(HistoryDiagnostic("FORK", "observations", obs.root_id, obs.previous_observation_id,
                                                       tuple(children) + (obs.observation_id,)))
            self._forked_roots.add(obs.root_id)

    def _validate_observation_attachments(self, obs: ThemeObservation, for_append: bool, line_number: int) -> None:
        roots = self._authorities["roots"].entries
        observations = self._authorities["observations"].entries
        root: ThemeRootRecord = roots[obs.root_id].record  # type: ignore[assignment]
        carried = self._carried_allowance(root)
        for att in obs.attachments:
            source_id = carried.get(att.attachment_key)
            if source_id is not None:
                source_entry = observations.get(source_id)
                source_att = source_entry.record.attachment(att.attachment_key) if source_entry else None
                if source_att is not None and canonical_json(source_att) == canonical_json(att):
                    continue   # 明示配分どおり byte 同一で carry された attachment（元 attached_at / provenance を保持）
                if obs.is_genesis:
                    self._reject(for_append, "ALLOCATION_VIOLATION",
                                 f"carried attachment {att.attachment_key} differs from its allocated source",
                                 authority="observations", line_number=line_number)
            elif obs.is_genesis and root.creation_method is not CreationMethod.CANDIDATE:
                self._reject(for_append, "ALLOCATION_VIOLATION",
                             f"attachment {att.attachment_key} is not allocated to {root.root_id} by {root.origin_event_id}",
                             authority="observations", line_number=line_number)
            if att.attached_at < root.created_at:
                self._reject(for_append, "ATTACHED_AT_OUT_OF_RANGE",
                             f"attachment {att.attachment_key} attached before root creation", authority="observations",
                             line_number=line_number)
            if att.attached_at > obs.recorded_at:
                self._reject(for_append, "ATTACHED_AT_OUT_OF_RANGE",
                             f"attachment {att.attachment_key} attached after the observation was recorded",
                             authority="observations", line_number=line_number)
            if att.evidence_time is not None and att.evidence_time > att.attached_at:
                self._reject(for_append, "ATTACHED_AT_OUT_OF_RANGE", "evidence_time later than attached_at",
                             authority="observations", line_number=line_number)

    def _validate_event(self, event: ThemeGovernanceEvent, for_append: bool, line_number: int) -> None:
        roots = self._authorities["roots"].entries
        observations = self._authorities["observations"].entries
        events = self._authorities["governance"].entries
        metadata = self._authorities["metadata"].entries
        for root_id in event.subject_roots:
            entry = roots.get(root_id)
            if entry is None:
                self._reject(for_append, "GOVERNANCE_REFERENCE_MISSING", f"subject root {root_id} is not stored",
                             authority="governance", line_number=line_number)
            if event.recorded_at < entry.record.created_at:
                self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "event recorded before its subject root was created",
                             authority="governance", line_number=line_number)
        for root_id in event.result_roots:
            if for_append and root_id in roots:
                self._reject(True, "RESULT_ROOT_ALREADY_EXISTS",
                             f"{root_id} already exists; result roots are declared before they are created",
                             authority="governance")
            declared_by = self._result_declared_by.get(root_id)
            if declared_by is not None and declared_by != event.event_id:
                self._reject(for_append, "RESULT_ROOT_REDECLARED", f"{root_id} is already declared by {declared_by}",
                             authority="governance", line_number=line_number)
        related_store = metadata if event.event_type is GovernanceEventType.METADATA_CORRECTION_APPROVED else observations
        for related_id in event.related_observations:
            entry = related_store.get(related_id)
            if entry is None:
                self._reject(for_append, "GOVERNANCE_REFERENCE_MISSING", f"related record {related_id} is not stored",
                             authority="governance", line_number=line_number)
            if entry.record.root_id not in event.subject_roots:
                self._reject(for_append, "GOVERNANCE_REFERENCE_MISSING",
                             f"related record {related_id} belongs to a root outside the event's subjects",
                             authority="governance", line_number=line_number)
            if event.recorded_at < entry.record.recorded_at:
                self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "approval recorded before the approved record",
                             authority="governance", line_number=line_number)
        previous_roots = {root for root, _ in event.previous_event_ids}
        for root_id, previous_id in event.previous_event_ids:
            entry = events.get(previous_id)
            if entry is None:
                self._reject(for_append, "GOVERNANCE_REFERENCE_MISSING", f"previous event {previous_id} is not stored",
                             authority="governance", line_number=line_number)
            previous: ThemeGovernanceEvent = entry.record  # type: ignore[assignment]
            if root_id not in set(previous.subject_roots) | set(previous.result_roots):
                self._reject(for_append, "GOVERNANCE_REFERENCE_MISSING",
                             f"previous event {previous_id} does not concern root {root_id}",
                             authority="governance", line_number=line_number)
            if event.recorded_at < previous.recorded_at:
                self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "event recorded before its previous event",
                             authority="governance", line_number=line_number)
            children = self._event_children.get((root_id, previous_id), [])
            if children:
                if for_append:
                    self._reject(True, "NON_TERMINAL_PREDECESSOR",
                                 f"{previous_id} already has successor {children[0]} for root {root_id}",
                                 authority="governance")
                self._diagnostics.append(HistoryDiagnostic("GOVERNANCE_FORK", "governance", root_id, previous_id,
                                                           tuple(children) + (event.event_id,)))
        for root_id in event.subject_roots:
            if root_id not in previous_roots and self._events_by_root.get(root_id):
                if for_append:
                    self._reject(True, "MISSING_PREVIOUS_EVENT",
                                 f"root {root_id} already has governance history; previous_event_ids must name its terminal",
                                 authority="governance")
                self._diagnostics.append(HistoryDiagnostic("GOVERNANCE_MULTIPLE_STARTS", "governance", root_id, "",
                                                           tuple(self._events_by_root[root_id]) + (event.event_id,)))
        if event.event_type is GovernanceEventType.EVENT_REVERSED:
            entry = events.get(event.reverses_event_id)
            if entry is None:
                self._reject(for_append, "GOVERNANCE_REFERENCE_MISSING",
                             f"reversed event {event.reverses_event_id} is not stored", authority="governance",
                             line_number=line_number)
            reversed_event: ThemeGovernanceEvent = entry.record  # type: ignore[assignment]
            if tuple(reversed_event.subject_roots) != tuple(event.subject_roots):
                self._reject(for_append, "MALFORMED_REVERSAL", "a reversal names exactly the reversed event's subject roots",
                             authority="governance", line_number=line_number)
            if event.recorded_at < reversed_event.recorded_at:
                self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "reversal recorded before the reversed event",
                             authority="governance", line_number=line_number)
        seen_keys: Dict[Tuple[str, str], str] = {}
        for item in event.evidence_allocation:
            entry = observations.get(item.source_observation_id)
            if entry is None:
                self._reject(for_append, "ALLOCATION_VIOLATION",
                             f"source observation {item.source_observation_id} is not stored", authority="governance",
                             line_number=line_number)
            source: ThemeObservation = entry.record  # type: ignore[assignment]
            if source.root_id not in event.subject_roots:
                self._reject(for_append, "ALLOCATION_VIOLATION", "allocation source must belong to a subject root",
                             authority="governance", line_number=line_number)
            if source.attachment(item.attachment_key) is None:
                self._reject(for_append, "ALLOCATION_VIOLATION",
                             f"{item.attachment_key} is not an attachment of {item.source_observation_id}",
                             authority="governance", line_number=line_number)
            key = (item.result_root_id, item.attachment_key)
            if key in seen_keys and seen_keys[key] != item.source_observation_id:
                self._reject(for_append, "ALLOCATION_VIOLATION",
                             f"{item.attachment_key} is allocated to {item.result_root_id} from two different sources",
                             authority="governance", line_number=line_number)
            seen_keys[key] = item.source_observation_id

    def _validate_event_results(self, event: ThemeGovernanceEvent, for_append: bool, line_number: int) -> None:
        """第 2 pass: 既に存在する result root は、この event を origin として作られたものでなければならない。"""
        roots = self._authorities["roots"].entries
        for root_id in event.result_roots:
            entry = roots.get(root_id)
            if entry is not None and entry.record.origin_event_id != event.event_id:
                self._reject(for_append, "RESULT_ROOT_REDECLARED",
                             f"{root_id} exists with origin {entry.record.origin_event_id!r}, not {event.event_id}",
                             authority="governance", line_number=line_number)

    def _validate_metadata(self, record: ThemeMetadataRecord, for_append: bool, line_number: int) -> None:
        roots = self._authorities["roots"].entries
        metadata = self._authorities["metadata"].entries
        events = self._authorities["governance"].entries
        root_entry = roots.get(record.root_id)
        if root_entry is None:
            self._reject(for_append, "ROOT_NOT_FOUND", f"root {record.root_id} is not stored", authority="metadata",
                         line_number=line_number)
        if record.recorded_at < root_entry.record.created_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "metadata recorded before its root was created",
                         authority="metadata", line_number=line_number)
        key = (record.root_id, record.field.value)
        if record.previous_metadata_id:
            entry = metadata.get(record.previous_metadata_id)
            if entry is None:
                self._reject(for_append, "METADATA_PREDECESSOR_MISSING",
                             f"previous metadata {record.previous_metadata_id} is not stored", authority="metadata",
                             line_number=line_number)
            previous: ThemeMetadataRecord = entry.record  # type: ignore[assignment]
            if previous.root_id != record.root_id or previous.field is not record.field:
                self._reject(for_append, "METADATA_PREDECESSOR_MISSING",
                             "previous metadata belongs to a different root or field", authority="metadata",
                             line_number=line_number)
            if previous.recorded_at > record.recorded_at:
                self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "metadata recorded before its predecessor",
                             authority="metadata", line_number=line_number)
            children = self._meta_children.get(record.previous_metadata_id, [])
            if children:
                if for_append:
                    self._reject(True, "NON_TERMINAL_PREDECESSOR",
                                 f"{record.previous_metadata_id} already has successor {children[0]}", authority="metadata")
                self._diagnostics.append(HistoryDiagnostic("METADATA_FORK", "metadata", record.root_id,
                                                           record.previous_metadata_id,
                                                           tuple(children) + (record.metadata_id,)))
        elif self._meta_by_root_field.get(key):
            if for_append:
                self._reject(True, "MISSING_PREVIOUS_METADATA",
                             f"{record.field.value} of {record.root_id} already has history; previous_metadata_id is required",
                             authority="metadata")
            self._diagnostics.append(HistoryDiagnostic("METADATA_MULTIPLE_STARTS", "metadata", record.root_id,
                                                       record.field.value,
                                                       tuple(self._meta_by_root_field[key]) + (record.metadata_id,)))
        if record.governance_event_id and record.governance_event_id not in events:
            self._reject(for_append, "GOVERNANCE_REFERENCE_MISSING",
                         f"governance event {record.governance_event_id} is not stored", authority="metadata",
                         line_number=line_number)

    def _validate_mapping(self, record: ThemeSeriesMapping, for_append: bool, line_number: int) -> None:
        roots = self._authorities["roots"].entries
        mappings = self._authorities["mappings"].entries
        observations = self._authorities["observations"].entries
        root_entry = roots.get(record.root_id)
        if root_entry is None:
            self._reject(for_append, "ROOT_NOT_FOUND", f"root {record.root_id} is not stored", authority="mappings",
                         line_number=line_number)
        if record.recorded_at < root_entry.record.created_at:
            self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "mapping recorded before its root was created",
                         authority="mappings", line_number=line_number)
        if record.consequence_ref:
            known = any(record.consequence_ref in observations[o].record.mechanism.consequence_keys
                        for o in self._obs_by_root.get(record.root_id, ()))
            if not known:
                self._reject(for_append, "MAPPING_CONSEQUENCE_UNKNOWN",
                             f"no stored observation of {record.root_id} declares consequence {record.consequence_ref!r}",
                             authority="mappings", line_number=line_number)
        if record.supersedes_mapping_id:
            entry = mappings.get(record.supersedes_mapping_id)
            if entry is None:
                self._reject(for_append, "MAPPING_PREDECESSOR_MISSING",
                             f"superseded mapping {record.supersedes_mapping_id} is not stored", authority="mappings",
                             line_number=line_number)
            previous: ThemeSeriesMapping = entry.record  # type: ignore[assignment]
            if previous.root_id != record.root_id:
                self._reject(for_append, "MAPPING_PREDECESSOR_MISSING", "superseded mapping belongs to a different root",
                             authority="mappings", line_number=line_number)
            if previous.recorded_at > record.recorded_at:
                self._reject(for_append, "NON_MONOTONIC_RECORDED_AT", "mapping recorded before the mapping it supersedes",
                             authority="mappings", line_number=line_number)
            children = self._map_children.get(record.supersedes_mapping_id, [])
            if children:
                if for_append:
                    self._reject(True, "NON_TERMINAL_PREDECESSOR",
                                 f"{record.supersedes_mapping_id} is already superseded by {children[0]}",
                                 authority="mappings")
                self._diagnostics.append(HistoryDiagnostic("MAPPING_FORK", "mappings", record.root_id,
                                                           record.supersedes_mapping_id,
                                                           tuple(children) + (record.mapping_id,)))

    # ------------------------------------------------------------ append（追記専用・validate-before-append）

    def verify_unchanged(self) -> None:
        """5 file の byte 長が load / 最終 append 時と同じか（SINGLE_WRITER 境界の検知。lock ではない）。"""
        for authority in self._authorities.values():
            actual = authority.path.stat().st_size if authority.path.exists() else -1
            if actual != authority.expected_size:
                raise ConcurrentModificationDetected(authority.name, authority.expected_size, actual)

    def _append(self, name: str, record) -> AppendResult:
        if self.read_only:
            error = ThemeStoreError("READ_ONLY", "store was opened read-only")
            error.category = FailureCategory.READ_ONLY
            raise error
        record_type = _RECORD_TYPES[name]
        if not isinstance(record, record_type):
            raise ThemeAppendRejected("INVALID_TYPE", f"{name} accepts {record_type.__name__} only", authority=name)
        line = canonical_line(record)
        try:
            if self._parse_line(name, line, 0) != record:
                raise ThemeAppendRejected("NON_CANONICAL_RECORD", "record does not survive its own canonical round-trip",
                                          authority=name)
        except ThemeStoreCorrupt as exc:
            raise ThemeAppendRejected("NON_CANONICAL_RECORD", str(exc), authority=name) from exc
        authority = self._authorities[name]
        rid = _record_id(name, record)
        existing = authority.entries.get(rid)
        if existing is not None:
            if existing.line == line:
                return AppendResult(AppendStatus.ALREADY_PRESENT, name, rid, existing.line_number, wrote_line=False)
            raise ThemeConflict(rid, _differing_fields(existing.record, record), authority=name)
        self._validate_history(name, record, for_append=True)
        self.verify_unchanged()
        self._write_line(authority, line)
        line_number = len(authority.entries) + 1
        authority.entries[rid] = _Entry(line_number, line, record)
        self._index(name, record)
        return AppendResult(AppendStatus.APPENDED, name, rid, line_number, wrote_line=True)

    def _write_line(self, authority: _Authority, line: str) -> None:
        """唯一の書込み経路: open("a") → write → flush → fsync。expected_size を更新する。"""
        payload = line.encode(ENCODING)
        with authority.path.open("a", encoding=ENCODING, newline=LINE_TERMINATOR) as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        authority.expected_size += len(payload)

    def append_root(self, record: ThemeRootRecord) -> AppendResult:
        return self._append("roots", record)

    def append_observation(self, record: ThemeObservation) -> AppendResult:
        return self._append("observations", record)

    def append_governance(self, record: ThemeGovernanceEvent) -> AppendResult:
        return self._append("governance", record)

    def append_metadata(self, record: ThemeMetadataRecord) -> AppendResult:
        return self._append("metadata", record)

    def append_mapping(self, record: ThemeSeriesMapping) -> AppendResult:
        return self._append("mappings", record)

    # ------------------------------------------------------------ exact lookup（参照検査用。resolver ではない）

    def _get(self, name: str, record_id: str):
        entry = self._authorities[name].entries.get(record_id)
        return None if entry is None else entry.record

    def get_root(self, root_id: str) -> Optional[ThemeRootRecord]:
        return self._get("roots", root_id)

    def get_observation(self, observation_id: str) -> Optional[ThemeObservation]:
        return self._get("observations", observation_id)

    def get_governance_event(self, event_id: str) -> Optional[ThemeGovernanceEvent]:
        return self._get("governance", event_id)

    def get_metadata(self, metadata_id: str) -> Optional[ThemeMetadataRecord]:
        return self._get("metadata", metadata_id)

    def get_mapping(self, mapping_id: str) -> Optional[ThemeSeriesMapping]:
        return self._get("mappings", mapping_id)

    def observations_for_root(self, root_id: str) -> Tuple[ThemeObservation, ...]:
        return tuple(self._get("observations", o) for o in self._obs_by_root.get(root_id, ()))

    def events_for_root(self, root_id: str) -> Tuple[ThemeGovernanceEvent, ...]:
        return tuple(self._get("governance", e) for e in self._events_by_root.get(root_id, ()))

    def metadata_for_root(self, root_id: str, field: Optional[MetadataField] = None) -> Tuple[ThemeMetadataRecord, ...]:
        keys = [k for k in self._meta_by_root_field if k[0] == root_id and (field is None or k[1] == field.value)]
        return tuple(self._get("metadata", m) for k in sorted(keys) for m in self._meta_by_root_field[k])

    def mappings_for_root(self, root_id: str) -> Tuple[ThemeSeriesMapping, ...]:
        return tuple(self._get("mappings", m) for m in self._map_by_root.get(root_id, ()))

    def physical_terminal_observations(self, root_id: str) -> Tuple[str, ...]:
        """子を持たない observation（物理 chain の末端）。fork なら複数。時刻・行順では選ばない。"""
        return tuple(o for o in self._obs_by_root.get(root_id, ()) if not self._obs_children.get(o))

    def physical_terminal_events(self, root_id: str) -> Tuple[str, ...]:
        return tuple(e for e in self._events_by_root.get(root_id, ()) if not self._event_children.get((root_id, e)))

    def physical_terminal_metadata(self, root_id: str, field: MetadataField) -> Tuple[str, ...]:
        return tuple(m for m in self._meta_by_root_field.get((root_id, field.value), ())
                     if not self._meta_children.get(m))

    def counts(self) -> Dict[str, int]:
        return {name: len(self._authorities[name].entries) for name in LOAD_ORDER}

    def canonical_lines(self, name: str) -> Tuple[str, ...]:
        """authority の canonical 行（物理順）。監査・test 用の読み取りのみ。"""
        return tuple(e.line for e in self._authorities[name].entries.values())

    # ------------------------------------------------------------ PENDING / 診断（読み取りのみ。修復しない）

    def pending(self) -> Tuple[PendingItem, ...]:
        roots = self._authorities["roots"].entries
        observations = self._authorities["observations"].entries
        out: List[PendingItem] = []
        for root_id in sorted(roots):
            root: ThemeRootRecord = roots[root_id].record  # type: ignore[assignment]
            if root.genesis_observation_id not in observations:
                out.append(PendingItem(PendingKind.PENDING_GENESIS, root_id, (root.genesis_observation_id,),
                                       f"{root.creation_method.value} root awaits its declared genesis"))
        for event_id in sorted(self._authorities["governance"].entries):
            event: ThemeGovernanceEvent = self._authorities["governance"].entries[event_id].record  # type: ignore[assignment]
            if not event.result_roots:
                continue
            missing: List[str] = []
            for root_id in event.result_roots:
                entry = roots.get(root_id)
                if entry is None:
                    missing.append(root_id)
                elif entry.record.genesis_observation_id not in observations:
                    missing.append(entry.record.genesis_observation_id)
            if missing:
                out.append(PendingItem(PendingKind.PENDING_EVENT, event_id, tuple(missing),
                                       f"{event.event_type.value} awaits declared result records"))
        return tuple(out)

    def diagnostics(self) -> Tuple[HistoryDiagnostic, ...]:
        return tuple(self._diagnostics)


__all__ = [
    "THEMES_DIRNAME", "AUTHORITY_FILENAMES", "LOAD_ORDER", "WRITER_GUARANTEE", "CORRUPTION_REASONS", "HISTORY_REASONS",
    "FailureCategory", "ThemeStoreError", "ThemeStoreCorrupt", "ThemeInvalidHistory", "ThemeAppendRejected",
    "ThemeConflict", "ConcurrentModificationDetected", "AppendStatus", "AppendResult", "PendingKind", "PendingItem",
    "HistoryDiagnostic", "StoreAudit", "ThemeStore", "themes_dir", "authority_paths",
]
