"""Theme point-in-time resolver（Phase 6 P6-A4c）— canonical history の **読み取り専用の解釈器**。新しい authority ではない。

問い（A3 §13 / D17）: 「root_id と cutoff T が与えられたとき、その時点までに Theme subsystem が正当に知り得た状態は何か」。

規則:
- 入力は canonical record の in-memory 集合（`ThemeHistory`）。file を読むのは `ThemeHistory.from_store` /
  `resolve_at_data_root` が store の read-only API を通じて行うだけ。書込み・修復・reload・時計・乱数・network なし。
- eligibility: root `created_at <= T`、observation / governance / metadata `recorded_at <= T`、mapping `recorded_at <= T`
  かつ `valid_from <= T`、evidence attachment `evidence_time <= T` かつ `attached_at <= T`。T より後の record は
  結果に影響しない（診断にも現れない）。
- terminal は predecessor graph だけで決める。recorded_at 最大・物理行順・「最後の行」を勝者にしない。fork / 複数
  terminal は UNRESOLVED。
- facet（semantic observation / governance / metadata field ごと / mapping）は独立に解決し、1 facet の曖昧を他へ
  伝播させない。構造的に不可能な履歴（INVALID_HISTORY）だけが上位 failure。
- PENDING_GENESIS / PENDING_EVENT は「T 時点で未完了だった」という事実として診断に返す。修復しない。
- DERIVED（fingerprint / 資格判定 / diversity / DIRECTLY_EVIDENCED link）は resolved observation ＋ **T で visible な
  attachment だけ**から A4a の純関数で再計算する。authority ではない。
- carried evidence の lineage は A4b どおり origin event の `evidence_allocation` ＋ byte 同一 attachment から再構成する。
  attachment schema に `carried_from` は追加しない。
- upstream evidence の dereference は caller 供給の純 lookup に委ね、canonical 再構成とは分けて報告する（既定 NOT_CHECKED）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from ..core.time import ensure_aware
from .fingerprint import identity_core_fingerprint, semantic_fingerprint
from .model import (SINGLE_PERIOD_FRAMES, CreationMethod, EntityRef, EvidenceAttachment, EvidenceAuthorityClass,
                    EvidenceRole, EvidenceTimeQuality, GovernanceEventType, MechanismCertainty, MetadataField,
                    ThemeGovernanceEvent, ThemeMetadataRecord, ThemeModelError, ThemeObservation, ThemeRootRecord,
                    ThemeSeriesMapping, canonical_json, is_root_id)
from .qualification import (DirectlyEvidencedLink, QualificationResult, QualificationStatus, counted_attachments,
                            evidence_date_set, exclusion_diagnostics, has_source_diversity, has_temporal_diversity,
                            independent_origin_count, period_frame)
from .store import LOAD_ORDER, ThemeInvalidHistory, ThemeStore, ThemeStoreCorrupt

RESOLVER_VERSION = "theme_resolver:0.1.0"


# ---------------------------------------------------------------- status vocabulary（A3 §13 / §23。統合しない）

class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_STATE = "NO_STATE"
    UNRESOLVED = "UNRESOLVED"
    INVALID_HISTORY = "INVALID_HISTORY"
    STORE_CORRUPTION = "STORE_CORRUPTION"


class GovernanceStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_GOVERNANCE = "NO_GOVERNANCE"
    UNRESOLVED = "UNRESOLVED"
    NOT_EVALUATED = "NOT_EVALUATED"   # 上位 failure（INVALID_HISTORY / STORE_CORRUPTION / root 不在）のとき


class MetadataStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_METADATA = "NO_METADATA"
    UNRESOLVED = "UNRESOLVED"
    NOT_EVALUATED = "NOT_EVALUATED"


class MappingStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_MAPPING = "NO_MAPPING"
    UNRESOLVED = "UNRESOLVED"
    NOT_EVALUATED = "NOT_EVALUATED"


class DereferenceStatus(str, Enum):
    """upstream evidence の現在状態（canonical 再構成とは別軸）。resolver 自身は何も取りに行かない。"""

    NOT_CHECKED = "NOT_CHECKED"
    AVAILABLE = "AVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    SUPERSEDED = "SUPERSEDED"
    UNUSABLE = "UNUSABLE"
    DUPLICATE_ORIGIN = "DUPLICATE_ORIGIN"


class LineageKind(str, Enum):
    MERGED_INTO = "MERGED_INTO"
    MERGE_OF = "MERGE_OF"
    SPLIT_INTO = "SPLIT_INTO"
    SPLIT_FROM = "SPLIT_FROM"
    SUPERSEDED_BY = "SUPERSEDED_BY"
    SUCCESSOR_OF = "SUCCESSOR_OF"


# ---------------------------------------------------------------- result model（frozen。authority ではない）

@dataclass(frozen=True)
class Diagnostic:
    kind: str            # FORK / MULTIPLE_TERMINALS / MULTIPLE_STARTS / DANGLING_PREDECESSOR / CYCLE / GENESIS_MISMATCH / ...
    facet: str           # root / observation / governance / metadata:<FIELD> / mapping / store
    subject_id: str
    detail: str = ""
    related: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingDiagnostic:
    kind: str            # PENDING_GENESIS / PENDING_EVENT
    subject_id: str      # root_id / event_id
    missing: Tuple[str, ...]


@dataclass(frozen=True)
class LineageRelation:
    kind: LineageKind
    event_id: str
    related_roots: Tuple[str, ...]


@dataclass(frozen=True)
class CarriedEvidence:
    """result root の attachment が origin event の配分どおり source から carry されたことの再構成。"""

    attachment_key: str
    source_observation_id: str
    source_root_id: str
    origin_event_id: str


@dataclass(frozen=True)
class EvidenceView:
    visible: Tuple[EvidenceAttachment, ...]
    not_yet_attached: Tuple[str, ...]           # attached_at > T（知識は存在しても Theme への付与は T 後）
    evidence_after_cutoff: Tuple[str, ...]      # evidence_time > T
    context_without_time: Tuple[EvidenceAttachment, ...]   # quality MISSING の CONTEXT（authoritative view 外）


@dataclass(frozen=True)
class GovernanceFacet:
    status: GovernanceStatus
    chain: Tuple[str, ...] = ()                 # start → terminal（RESOLVED のとき）
    terminal_event_id: str = ""
    effective_event_id: str = ""                # 取消を畳み込んだ後に効力を持つ最後の event（無ければ空）
    effective_event_type: Optional[GovernanceEventType] = None
    reversed_event_ids: Tuple[str, ...] = ()
    diagnostics: Tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class MetadataFacet:
    field: MetadataField
    status: MetadataStatus
    record_id: str = ""
    value: Tuple[str, ...] = ()
    diagnostics: Tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class MappingFacet:
    status: MappingStatus
    terminal_mapping_ids: Tuple[str, ...] = ()
    mappings: Tuple[ThemeSeriesMapping, ...] = ()
    diagnostics: Tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class DerivedView:
    identity_core_fingerprint: str
    semantic_fingerprint: str
    qualification: QualificationResult
    directly_evidenced_links: Tuple[DirectlyEvidencedLink, ...]
    has_contradicting_evidence: bool
    has_invalidating_evidence: bool


@dataclass(frozen=True)
class DereferenceResult:
    ref_id: str
    status: DereferenceStatus
    detail: str = ""


@dataclass(frozen=True)
class ThemeResolution:
    resolver_version: str
    root_id: str
    cutoff: datetime
    status: ResolutionStatus
    root: Optional[ThemeRootRecord]
    observation: Optional[ThemeObservation]
    evidence: Optional[EvidenceView]
    governance: GovernanceFacet
    metadata: Tuple[MetadataFacet, ...]
    mapping: MappingFacet
    lineage: Tuple[LineageRelation, ...]
    carried: Tuple[CarriedEvidence, ...]
    pending: Tuple[PendingDiagnostic, ...]
    diagnostics: Tuple[Diagnostic, ...]
    derived: Optional[DerivedView]
    dereference: Tuple[DereferenceResult, ...]


UpstreamLookup = Callable[[EvidenceAttachment], DereferenceStatus]


# ---------------------------------------------------------------- history（in-memory canonical records）

@dataclass(frozen=True)
class ThemeHistory:
    """5 authority の record 集合。順序は意味を持たない（resolver は id で並べ直す）。"""

    roots: Tuple[ThemeRootRecord, ...] = ()
    observations: Tuple[ThemeObservation, ...] = ()
    events: Tuple[ThemeGovernanceEvent, ...] = ()
    metadata: Tuple[ThemeMetadataRecord, ...] = ()
    mappings: Tuple[ThemeSeriesMapping, ...] = ()

    @classmethod
    def from_store(cls, store: ThemeStore) -> "ThemeHistory":
        """store の canonical 行（read-only API）から record を復元する。書かない・reload しない。"""
        parsed = {name: tuple(_RECORD_TYPES[name].from_dict(json.loads(line)) for line in store.canonical_lines(name))
                  for name in LOAD_ORDER}
        return cls(roots=parsed["roots"], observations=parsed["observations"], events=parsed["governance"],
                   metadata=parsed["metadata"], mappings=parsed["mappings"])


_RECORD_TYPES = {"roots": ThemeRootRecord, "observations": ThemeObservation, "governance": ThemeGovernanceEvent,
                 "metadata": ThemeMetadataRecord, "mappings": ThemeSeriesMapping}


class _Index:
    """history を id で引ける形に整える（決定論: 同一 id 集合なら入力順に依らず同一）。"""

    def __init__(self, history: ThemeHistory) -> None:
        self.roots: Dict[str, ThemeRootRecord] = {r.root_id: r for r in history.roots}
        self.observations: Dict[str, ThemeObservation] = {o.observation_id: o for o in history.observations}
        self.events: Dict[str, ThemeGovernanceEvent] = {e.event_id: e for e in history.events}
        self.metadata: Dict[str, ThemeMetadataRecord] = {m.metadata_id: m for m in history.metadata}
        self.mappings: Dict[str, ThemeSeriesMapping] = {m.mapping_id: m for m in history.mappings}
        for name, records in (("roots", history.roots), ("observations", history.observations),
                              ("events", history.events), ("metadata", history.metadata),
                              ("mappings", history.mappings)):
            ids = [getattr(r, _ID_ATTR[name]) for r in records]
            if len(ids) != len(set(ids)):
                raise ThemeModelError("DUPLICATE_ID", f"history contains duplicate ids in {name}")


_ID_ATTR = {"roots": "root_id", "observations": "observation_id", "events": "event_id", "metadata": "metadata_id",
            "mappings": "mapping_id"}


class _Invalid(Exception):
    def __init__(self, diagnostic: Diagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.kind)


# ---------------------------------------------------------------- chain resolution（predecessor graph のみ）

@dataclass(frozen=True)
class _Chain:
    status: str                   # RESOLVED / NONE / UNRESOLVED
    order: Tuple[str, ...]        # start → terminal（RESOLVED のとき）
    terminals: Tuple[str, ...]
    diagnostics: Tuple[Diagnostic, ...]


def _resolve_linear_chain(nodes: Mapping[str, str], *, facet: str, known_ids: Set[str],
                          subject: str) -> _Chain:
    """nodes: id → predecessor id（start は ""）。唯一の線形 chain を要求する。時刻・順序は使わない。"""
    if not nodes:
        return _Chain("NONE", (), (), ())
    ordered_ids = sorted(nodes)
    children: Dict[str, List[str]] = {}
    starts: List[str] = []
    for node_id in ordered_ids:
        predecessor = nodes[node_id]
        if predecessor == "":
            starts.append(node_id)
            continue
        if predecessor not in nodes:
            code = "NON_MONOTONIC_RECORDED_AT" if predecessor in known_ids else "DANGLING_PREDECESSOR"
            raise _Invalid(Diagnostic(code, facet, node_id,
                                      f"predecessor {predecessor} is not eligible at the cutoff" if predecessor in known_ids
                                      else f"predecessor {predecessor} is not in the history", (predecessor,)))
        children.setdefault(predecessor, []).append(node_id)
    diagnostics: List[Diagnostic] = []
    for predecessor in sorted(children):
        if len(children[predecessor]) > 1:
            diagnostics.append(Diagnostic("FORK", facet, predecessor,
                                          f"{len(children[predecessor])} successors share one predecessor",
                                          tuple(sorted(children[predecessor]))))
    if len(starts) > 1:
        diagnostics.append(Diagnostic("MULTIPLE_STARTS", facet, subject, "more than one chain start", tuple(starts)))
    if not starts:
        raise _Invalid(Diagnostic("CYCLE", facet, subject, "no chain start (cycle)", tuple(ordered_ids)))
    terminals = tuple(n for n in ordered_ids if n not in children)
    if len(terminals) != 1 and not any(d.kind == "FORK" for d in diagnostics) and len(starts) == 1:
        diagnostics.append(Diagnostic("MULTIPLE_TERMINALS", facet, subject, f"{len(terminals)} terminals", terminals))
    if diagnostics:
        return _Chain("UNRESOLVED", (), terminals, tuple(diagnostics))
    order: List[str] = []
    cursor: Optional[str] = terminals[0]
    seen: Set[str] = set()
    while cursor:
        if cursor in seen:
            raise _Invalid(Diagnostic("CYCLE", facet, subject, "predecessor cycle", tuple(order)))
        seen.add(cursor)
        order.append(cursor)
        cursor = nodes[cursor] or None
    return _Chain("RESOLVED", tuple(reversed(order)), terminals, ())


# ---------------------------------------------------------------- resolver

def _cutoff(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ThemeModelError("INVALID_TYPE", "cutoff must be datetime")
    try:
        return ensure_aware(value, "cutoff")
    except ValueError as exc:
        raise ThemeModelError("NAIVE_DATETIME", str(exc)) from None


def resolve(history: ThemeHistory, root_id: str, cutoff: datetime, *,
            dereference: Optional[UpstreamLookup] = None) -> ThemeResolution:
    """純関数: 同一 history（同一 record 集合）・同一 root_id・同一 cutoff → 同一 ThemeResolution。"""
    cutoff = _cutoff(cutoff)
    if not is_root_id(root_id):
        raise ThemeModelError("INVALID_ROOT_ID", f"{root_id!r} is not a Theme root id")
    index = _Index(history)
    try:
        return _resolve(index, root_id, cutoff, dereference)
    except _Invalid as invalid:
        return _failure(root_id, cutoff, ResolutionStatus.INVALID_HISTORY, index.roots.get(root_id),
                        (invalid.diagnostic,))


def resolve_from_store(store: ThemeStore, root_id: str, cutoff: datetime, *,
                       dereference: Optional[UpstreamLookup] = None) -> ThemeResolution:
    """store の read-only API から history を取り、`resolve` する。store には書かない。"""
    return resolve(ThemeHistory.from_store(store), root_id, cutoff, dereference=dereference)


def resolve_at_data_root(data_root: Union[str, "object"], root_id: str, cutoff: datetime, *,
                         dereference: Optional[UpstreamLookup] = None) -> ThemeResolution:
    """data_root を read-only で開いて解決する。store が fail closed した場合は STORE_CORRUPTION / INVALID_HISTORY を
    **status として**返す（意味を曖昧にしない）。未初期化などその他の store error はそのまま送出する。"""
    cutoff = _cutoff(cutoff)
    if not is_root_id(root_id):
        raise ThemeModelError("INVALID_ROOT_ID", f"{root_id!r} is not a Theme root id")
    try:
        store = ThemeStore.open(data_root, read_only=True)
    except ThemeStoreCorrupt as exc:
        return _failure(root_id, cutoff, ResolutionStatus.STORE_CORRUPTION, None,
                        (Diagnostic(exc.code, "store", exc.authority, exc.detail, (str(exc.line_number),)),))
    except ThemeInvalidHistory as exc:
        return _failure(root_id, cutoff, ResolutionStatus.INVALID_HISTORY, None,
                        (Diagnostic(exc.code, "store", exc.authority, exc.detail, (str(exc.line_number),)),))
    return resolve_from_store(store, root_id, cutoff, dereference=dereference)


def _replace_pending(resolution: ThemeResolution, pending: Tuple[PendingDiagnostic, ...],
                     lineage: Tuple[LineageRelation, ...]) -> ThemeResolution:
    return ThemeResolution(**{**resolution.__dict__, "pending": pending, "lineage": lineage})


def _failure(root_id: str, cutoff: datetime, status: ResolutionStatus, root: Optional[ThemeRootRecord],
             diagnostics: Tuple[Diagnostic, ...]) -> ThemeResolution:
    return ThemeResolution(
        resolver_version=RESOLVER_VERSION, root_id=root_id, cutoff=cutoff, status=status, root=root, observation=None,
        evidence=None, governance=GovernanceFacet(GovernanceStatus.NOT_EVALUATED),
        metadata=tuple(MetadataFacet(f, MetadataStatus.NOT_EVALUATED) for f in MetadataField),
        mapping=MappingFacet(MappingStatus.NOT_EVALUATED), lineage=(), carried=(), pending=(), diagnostics=diagnostics,
        derived=None, dereference=())


def _resolve(index: _Index, root_id: str, cutoff: datetime, dereference: Optional[UpstreamLookup]) -> ThemeResolution:
    root = index.roots.get(root_id)
    if root is None:
        return _failure(root_id, cutoff, ResolutionStatus.NO_STATE, None,
                        (Diagnostic("UNKNOWN_ROOT", "root", root_id, "no RootRecord in the history"),))
    if root.created_at > cutoff:
        declaring = {e.event_id: e for e in index.events.values()
                     if e.recorded_at <= cutoff and root_id in e.result_roots}
        failure = _failure(root_id, cutoff, ResolutionStatus.NO_STATE, None,
                           (Diagnostic("ROOT_AFTER_CUTOFF", "root", root_id, "root created after the cutoff"),))
        if declaring:   # 宣言 event は T で可視だが root はまだ無い ＝ その時点で未完了だった事実
            pending = tuple(PendingDiagnostic("PENDING_EVENT", event_id, (root_id,)) for event_id in sorted(declaring))
            failure = _replace_pending(failure, pending, _lineage(root_id, declaring))
        return failure
    eligible_events = {e.event_id: e for e in index.events.values()
                       if e.recorded_at <= cutoff and (root_id in e.subject_roots or root_id in e.result_roots)}
    _check_root_origin(root, index, cutoff)

    # --- semantic observation chain（root 内・eligible のみ）
    eligible_obs = {o.observation_id: o for o in index.observations.values()
                    if o.root_id == root_id and o.recorded_at <= cutoff}
    diagnostics: List[Diagnostic] = []
    pending = _pending(root, index, cutoff, eligible_events)
    lineage = _lineage(root_id, eligible_events)
    governance = _governance(root_id, eligible_events, index, cutoff)
    metadata = _metadata(root_id, index, cutoff)
    mapping = _mapping(root_id, index, cutoff)
    if not eligible_obs:
        return ThemeResolution(
            resolver_version=RESOLVER_VERSION, root_id=root_id, cutoff=cutoff, status=ResolutionStatus.NO_STATE,
            root=root, observation=None, evidence=None, governance=governance, metadata=metadata, mapping=mapping,
            lineage=lineage, carried=(), pending=pending,
            diagnostics=(Diagnostic("NOT_YET_OBSERVED", "observation", root_id,
                                    "no observation recorded at or before the cutoff"),),
            derived=None, dereference=())
    for obs in sorted(eligible_obs.values(), key=lambda o: o.observation_id):
        if obs.is_genesis and obs.observation_id != root.genesis_observation_id:
            raise _Invalid(Diagnostic("GENESIS_MISMATCH", "observation", obs.observation_id,
                                      f"root declares genesis {root.genesis_observation_id}"))
        if not obs.is_genesis:
            predecessor = index.observations.get(obs.previous_observation_id)
            if predecessor is not None and predecessor.root_id != root_id:
                raise _Invalid(Diagnostic("WRONG_ROOT_PREDECESSOR", "observation", obs.observation_id,
                                          "predecessor belongs to another root", (predecessor.observation_id,)))
    if root.genesis_observation_id not in eligible_obs:
        raise _Invalid(Diagnostic("GENESIS_NOT_VISIBLE", "observation", root_id,
                                  "observations exist at the cutoff but the declared genesis does not"))
    chain = _resolve_linear_chain({o: eligible_obs[o].previous_observation_id for o in eligible_obs},
                                  facet="observation", known_ids=set(index.observations), subject=root_id)
    if chain.status == "UNRESOLVED":
        return ThemeResolution(
            resolver_version=RESOLVER_VERSION, root_id=root_id, cutoff=cutoff, status=ResolutionStatus.UNRESOLVED,
            root=root, observation=None, evidence=None, governance=governance, metadata=metadata, mapping=mapping,
            lineage=lineage, carried=(), pending=pending, diagnostics=chain.diagnostics, derived=None, dereference=())
    terminal = eligible_obs[chain.order[-1]]
    evidence = _evidence_view(terminal, cutoff)
    carried = _carried(root, terminal, index, evidence)
    derived = _derived(terminal, evidence)
    deref = _dereference(evidence, dereference)
    return ThemeResolution(
        resolver_version=RESOLVER_VERSION, root_id=root_id, cutoff=cutoff, status=ResolutionStatus.RESOLVED, root=root,
        observation=terminal, evidence=evidence, governance=governance, metadata=metadata, mapping=mapping,
        lineage=lineage, carried=carried, pending=pending, diagnostics=tuple(diagnostics), derived=derived,
        dereference=deref)


def _check_root_origin(root: ThemeRootRecord, index: _Index, cutoff: datetime) -> None:
    if root.creation_method is CreationMethod.CANDIDATE:
        return
    event = index.events.get(root.origin_event_id)
    if event is None:
        raise _Invalid(Diagnostic("ORIGIN_EVENT_MISSING", "root", root.root_id, "declaring event is not in the history",
                                  (root.origin_event_id,)))
    if event.recorded_at > root.created_at or root.root_id not in event.result_roots:
        raise _Invalid(Diagnostic("RESULT_ROOT_NOT_DECLARED", "root", root.root_id,
                                  "result root is not declared by an earlier event", (event.event_id,)))


# ---------------------------------------------------------------- evidence view / derived / dereference

def _evidence_view(observation: ThemeObservation, cutoff: datetime) -> EvidenceView:
    visible: List[EvidenceAttachment] = []
    not_yet: List[str] = []
    after: List[str] = []
    context_without_time: List[EvidenceAttachment] = []
    for att in observation.attachments:
        if att.attached_at > cutoff:
            not_yet.append(att.attachment_key)
            continue
        if att.evidence_time is None:                      # quality MISSING（CONTEXT のみ）。authoritative view 外
            context_without_time.append(att)
            continue
        if att.evidence_time > cutoff:
            after.append(att.attachment_key)
            continue
        visible.append(att)
    return EvidenceView(tuple(visible), tuple(not_yet), tuple(after), tuple(context_without_time))


def _derived(observation: ThemeObservation, evidence: EvidenceView) -> DerivedView:
    """A4a の純関数を visible attachment だけに適用する（`evaluate_qualification` と同じ合成。再定義ではない）。"""
    visible = evidence.visible
    counted = counted_attachments(visible)
    diagnostics: List[str] = list(exclusion_diagnostics(visible))
    origins = independent_origin_count(counted)
    dates = evidence_date_set(counted)
    keys = tuple(a.attachment_key for a in counted)
    frame = period_frame(observation)
    if frame in SINGLE_PERIOD_FRAMES:
        diagnostics.append(f"Q4_SINGLE_PERIOD_FRAME:{frame}")
        status = QualificationStatus.DOES_NOT_QUALIFY
    else:
        if not counted:
            diagnostics.append("NO_COUNTED_EVIDENCE")
        else:
            if origins < 2:
                diagnostics.append("SINGLE_SOURCE_ORIGIN" if origins == 1 else "NO_KNOWN_SOURCE_ORIGIN")
            if len(dates) < 2:
                diagnostics.append("SINGLE_EVIDENCE_DATE")
        if observation.certainty_class is MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM:
            if not (has_source_diversity(counted) and has_temporal_diversity(counted)):
                diagnostics.append("EVIDENCE_SUPPORTED_CLASS_WITHOUT_DIVERSITY")
            if not any(a.role is EvidenceRole.CONTRADICTS for a in visible):
                diagnostics.append("NO_CONTRADICTING_EVIDENCE_RECORDED")
        contradicting = any(a.role is EvidenceRole.CONTRADICTS for a in visible)
        invalidating = any(a.role is EvidenceRole.INVALIDATES for a in visible)
        if contradicting:
            diagnostics.append("HAS_CONTRADICTING_EVIDENCE")
        if invalidating:
            diagnostics.append("HAS_INVALIDATING_EVIDENCE")
        qualifies = bool(counted) and origins >= 2 and len(dates) >= 2
        status = QualificationStatus.QUALIFIES_SEMANTICALLY if qualifies else QualificationStatus.THEME_CANDIDATE_POSSIBLE
    qualification = QualificationResult(status=status, diagnostics=tuple(diagnostics), counted_attachment_keys=keys,
                                        independent_origins=origins, evidence_dates=dates)
    by_entity: Dict[Tuple[str, str], Set[str]] = {}
    entities: Dict[Tuple[str, str], EntityRef] = {}
    for att in visible:
        if att.authority_class is not EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL:
            continue
        for entity in att.subject_refs:
            key = (entity.kind.value, entity.value)
            entities[key] = entity
            by_entity.setdefault(key, set()).add(att.ref_id)
    links = tuple(DirectlyEvidencedLink(entity=entities[k], ref_ids=tuple(sorted(by_entity[k]))) for k in sorted(by_entity))
    return DerivedView(
        identity_core_fingerprint=identity_core_fingerprint(observation),
        semantic_fingerprint=semantic_fingerprint(observation), qualification=qualification,
        directly_evidenced_links=links,
        has_contradicting_evidence=any(a.role is EvidenceRole.CONTRADICTS for a in visible),
        has_invalidating_evidence=any(a.role is EvidenceRole.INVALIDATES for a in visible))


def _dereference(evidence: EvidenceView, lookup: Optional[UpstreamLookup]) -> Tuple[DereferenceResult, ...]:
    out: List[DereferenceResult] = []
    for att in evidence.visible:
        if lookup is None:
            out.append(DereferenceResult(att.ref_id, DereferenceStatus.NOT_CHECKED))
            continue
        status = lookup(att)
        if not isinstance(status, DereferenceStatus):
            raise ThemeModelError("INVALID_VOCABULARY", "upstream lookup must return DereferenceStatus")
        out.append(DereferenceResult(att.ref_id, status))
    return tuple(out)


# ---------------------------------------------------------------- pending / lineage / carried

def _genesis_visible(root: ThemeRootRecord, index: _Index, cutoff: datetime) -> bool:
    genesis = index.observations.get(root.genesis_observation_id)
    return genesis is not None and genesis.root_id == root.root_id and genesis.recorded_at <= cutoff


def _pending(root: ThemeRootRecord, index: _Index, cutoff: datetime,
             eligible_events: Mapping[str, ThemeGovernanceEvent]) -> Tuple[PendingDiagnostic, ...]:
    out: List[PendingDiagnostic] = []
    if not _genesis_visible(root, index, cutoff):
        out.append(PendingDiagnostic("PENDING_GENESIS", root.root_id, (root.genesis_observation_id,)))
    for event_id in sorted(eligible_events):
        event = eligible_events[event_id]
        if not event.result_roots:
            continue
        missing: List[str] = []
        for result_id in event.result_roots:
            result_root = index.roots.get(result_id)
            if result_root is None or result_root.created_at > cutoff:
                missing.append(result_id)
            elif not _genesis_visible(result_root, index, cutoff):
                missing.append(result_root.genesis_observation_id)
        if missing:
            out.append(PendingDiagnostic("PENDING_EVENT", event_id, tuple(missing)))
    return tuple(out)


def _lineage(root_id: str, eligible_events: Mapping[str, ThemeGovernanceEvent]) -> Tuple[LineageRelation, ...]:
    out: List[LineageRelation] = []
    for event_id in sorted(eligible_events):
        event = eligible_events[event_id]
        as_subject = root_id in event.subject_roots
        if event.event_type is GovernanceEventType.MERGE:
            kind = LineageKind.MERGED_INTO if as_subject else LineageKind.MERGE_OF
            related = event.result_roots if as_subject else event.subject_roots
        elif event.event_type is GovernanceEventType.SPLIT:
            kind = LineageKind.SPLIT_INTO if as_subject else LineageKind.SPLIT_FROM
            related = event.result_roots if as_subject else event.subject_roots
        elif event.event_type is GovernanceEventType.SUPERSEDED_BY_ROOT:
            kind = LineageKind.SUPERSEDED_BY if as_subject else LineageKind.SUCCESSOR_OF
            related = event.result_roots if as_subject else event.subject_roots
        else:
            continue
        out.append(LineageRelation(kind, event_id, tuple(related)))
    return tuple(out)


def _carried(root: ThemeRootRecord, observation: ThemeObservation, index: _Index,
             evidence: EvidenceView) -> Tuple[CarriedEvidence, ...]:
    """origin event の配分 ＋ byte 同一 attachment から carry の lineage を再構成する（A4b と同じ authority）。"""
    if root.creation_method is CreationMethod.CANDIDATE:
        return ()
    event = index.events.get(root.origin_event_id)
    if event is None:
        return ()
    allocation = {a.attachment_key: a.source_observation_id for a in event.evidence_allocation
                  if a.result_root_id == root.root_id}
    out: List[CarriedEvidence] = []
    for att in sorted(observation.attachments, key=lambda a: a.attachment_key):
        source_id = allocation.get(att.attachment_key)
        source = index.observations.get(source_id) if source_id else None
        source_att = source.attachment(att.attachment_key) if source is not None else None
        if source_att is not None and canonical_json(source_att) == canonical_json(att):
            out.append(CarriedEvidence(att.attachment_key, source.observation_id, source.root_id, event.event_id))
    return tuple(out)


# ---------------------------------------------------------------- governance facet

def _governance(root_id: str, eligible_events: Mapping[str, ThemeGovernanceEvent], index: _Index,
                cutoff: datetime) -> GovernanceFacet:
    if not eligible_events:
        return GovernanceFacet(GovernanceStatus.NO_GOVERNANCE)
    nodes: Dict[str, str] = {}
    for event_id, event in eligible_events.items():
        previous = dict(event.previous_event_ids).get(root_id, "") if root_id in event.subject_roots else ""
        nodes[event_id] = previous
    known = {e.event_id for e in index.events.values() if root_id in e.subject_roots or root_id in e.result_roots}
    chain = _resolve_linear_chain(nodes, facet="governance", known_ids=known, subject=root_id)
    if chain.status == "UNRESOLVED":
        return GovernanceFacet(GovernanceStatus.UNRESOLVED, terminal_event_id="", diagnostics=chain.diagnostics)
    reversals: Dict[str, List[str]] = {}
    diagnostics: List[Diagnostic] = []
    for event_id in chain.order:
        event = eligible_events[event_id]
        if event.event_type is GovernanceEventType.EVENT_REVERSED:
            if event.reverses_event_id not in eligible_events:
                raise _Invalid(Diagnostic("REVERSAL_TARGET_MISSING", "governance", event_id,
                                          "reversed event is not eligible at the cutoff", (event.reverses_event_id,)))
            reversals.setdefault(event.reverses_event_id, []).append(event_id)

    def in_force(event_id: str) -> bool:
        return not any(in_force(r) for r in reversals.get(event_id, ()))

    effective_id = ""
    for event_id in chain.order:                       # start → terminal。効力を持つ最後の非取消 event
        event = eligible_events[event_id]
        if event.event_type is GovernanceEventType.EVENT_REVERSED:
            continue
        if in_force(event_id):
            effective_id = event_id
    reversed_ids = tuple(sorted(e for e in reversals if not in_force(e)))
    effective_type = eligible_events[effective_id].event_type if effective_id else None
    return GovernanceFacet(GovernanceStatus.RESOLVED, chain=chain.order, terminal_event_id=chain.order[-1],
                           effective_event_id=effective_id, effective_event_type=effective_type,
                           reversed_event_ids=reversed_ids, diagnostics=tuple(diagnostics))


# ---------------------------------------------------------------- metadata facet（field ごとに独立）

def _metadata(root_id: str, index: _Index, cutoff: datetime) -> Tuple[MetadataFacet, ...]:
    facets: List[MetadataFacet] = []
    for field_ in MetadataField:
        eligible = {m.metadata_id: m for m in index.metadata.values()
                    if m.root_id == root_id and m.field is field_ and m.recorded_at <= cutoff}
        if not eligible:
            facets.append(MetadataFacet(field_, MetadataStatus.NO_METADATA))
            continue
        known = {m.metadata_id for m in index.metadata.values() if m.root_id == root_id and m.field is field_}
        chain = _resolve_linear_chain({m: eligible[m].previous_metadata_id for m in eligible},
                                      facet=f"metadata:{field_.value}", known_ids=known, subject=root_id)
        if chain.status == "UNRESOLVED":
            facets.append(MetadataFacet(field_, MetadataStatus.UNRESOLVED, diagnostics=chain.diagnostics))
            continue
        terminal = eligible[chain.order[-1]]
        facets.append(MetadataFacet(field_, MetadataStatus.RESOLVED, record_id=terminal.metadata_id,
                                    value=terminal.value))
    return tuple(facets)


# ---------------------------------------------------------------- mapping facet（複数 chain は正当。fork だけが曖昧）

def _mapping(root_id: str, index: _Index, cutoff: datetime) -> MappingFacet:
    eligible = {m.mapping_id: m for m in index.mappings.values()
                if m.root_id == root_id and m.recorded_at <= cutoff and m.valid_from <= cutoff}
    if not eligible:
        return MappingFacet(MappingStatus.NO_MAPPING)
    children: Dict[str, List[str]] = {}
    diagnostics: List[Diagnostic] = []
    for mapping_id in sorted(eligible):
        predecessor = eligible[mapping_id].supersedes_mapping_id
        if not predecessor:
            continue
        if predecessor not in index.mappings:
            raise _Invalid(Diagnostic("MAPPING_PREDECESSOR_MISSING", "mapping", mapping_id,
                                      "superseded mapping is not in the history", (predecessor,)))
        if predecessor in eligible:
            children.setdefault(predecessor, []).append(mapping_id)
        else:
            diagnostics.append(Diagnostic("PREDECESSOR_NOT_YET_ELIGIBLE", "mapping", mapping_id,
                                          "superseded mapping is not yet effective at the cutoff", (predecessor,)))
    forks = [Diagnostic("FORK", "mapping", p, f"{len(c)} eligible mappings supersede one predecessor", tuple(sorted(c)))
             for p, c in sorted(children.items()) if len(c) > 1]
    if forks:
        return MappingFacet(MappingStatus.UNRESOLVED, diagnostics=tuple(forks + diagnostics))
    terminals = tuple(m for m in sorted(eligible) if m not in children)
    return MappingFacet(MappingStatus.RESOLVED, terminal_mapping_ids=terminals,
                        mappings=tuple(eligible[m] for m in terminals), diagnostics=tuple(diagnostics))


__all__ = [
    "RESOLVER_VERSION", "ResolutionStatus", "GovernanceStatus", "MetadataStatus", "MappingStatus", "DereferenceStatus",
    "LineageKind", "Diagnostic", "PendingDiagnostic", "LineageRelation", "CarriedEvidence", "EvidenceView",
    "GovernanceFacet", "MetadataFacet", "MappingFacet", "DerivedView", "DereferenceResult", "ThemeResolution",
    "ThemeHistory", "UpstreamLookup", "resolve", "resolve_from_store", "resolve_at_data_root",
]
