"""P6-B5B — relation authority の point-in-time 解決（純関数。filesystem / network / 現在時刻を使わない）。

`resolve_relation_graph(assertions, governance_events, *, cutoff, endpoint_lookup)`

- cutoff T までに記録された assertion / governance event だけを見る。将来の訂正・将来の governance は見えない。
- 端点の Theme root は T までに存在していなければならない（B5-D6）。観測状態（ThemeObservation）の解決は要求しない。
- 端点の存在判定は呼び出し側が渡す read-only な lookup が答える。Foundation store を読まない（B5-D7 / §12）。
- 物理順で勝者を選ばない。chain は predecessor graph だけで解く。fork / 複数 start は UNRESOLVED、
  dangling / cycle / 非単調 / 不正な governance 列は INVALID_HISTORY。
- 撤回は assertion の改訂ではなく governance chain で表す。撤回しても assertion 履歴は消えない。
- 推移的な関係を導出しない。score / 順位付け / 中心性を持たない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .relation_model import (AssertionClass, RelationGovernanceEventType, RelationModelError, RelationType,
                             ThemeRelationAssertion, ThemeRelationGovernanceEvent, split_edge_key)

RELATION_RESOLVER_VERSION = "theme_relation_resolver:0.1.0"


class RelationResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_STATE = "NO_STATE"
    UNRESOLVED = "UNRESOLVED"
    INVALID_HISTORY = "INVALID_HISTORY"
    STORE_CORRUPTION = "STORE_CORRUPTION"


class EdgeState(str, Enum):
    """graph 上の意味論的状態。resolver の失敗状態とは別物。"""

    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"


class EndpointState(str, Enum):
    """端点 Theme root について B5 が必要とする最小限の答え。Foundation の変更 API は公開しない。"""

    EXISTS_AT_CUTOFF = "EXISTS_AT_CUTOFF"
    NOT_CREATED_YET = "NOT_CREATED_YET"
    UNKNOWN_ROOT = "UNKNOWN_ROOT"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


#: 端点が「その cutoff に存在した」とみなせる状態（退役・後継ありでも歴史的 node として残る）
ENDPOINT_PRESENT_STATES: Tuple[EndpointState, ...] = (EndpointState.EXISTS_AT_CUTOFF, EndpointState.SUPERSEDED,
                                                      EndpointState.RETIRED)
EndpointLookup = Callable[[str, datetime], EndpointState]


@dataclass(frozen=True, kw_only=True)
class RelationDiagnostic:
    code: str
    edge_key: str = ""
    detail: str = ""

    def as_tuple(self) -> Tuple[str, str, str]:
        return (self.code, self.edge_key, self.detail)


@dataclass(frozen=True, kw_only=True)
class ResolvedRelation:
    """構造的に解決できた 1 辺。`edge_state` は意味論、`assertion` は terminal の主張。"""

    edge_key: str
    source_theme_root_id: str
    target_theme_root_id: str
    relation_type: RelationType
    assertion_class: AssertionClass
    attribution_key: str
    assertion: ThemeRelationAssertion
    assertion_chain: Tuple[str, ...]
    edge_state: EdgeState
    governance_chain: Tuple[str, ...]
    source_endpoint: EndpointState
    target_endpoint: EndpointState
    diagnostics: Tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class UnresolvedEdge:
    edge_key: str
    status: RelationResolutionStatus
    diagnostics: Tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class ExcludedEdge:
    edge_key: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class ThemeRelationResolution:
    resolver_version: str
    cutoff: datetime
    status: RelationResolutionStatus
    edges: Tuple[ResolvedRelation, ...]
    unresolved: Tuple[UnresolvedEdge, ...]
    excluded: Tuple[ExcludedEdge, ...]
    diagnostics: Tuple[RelationDiagnostic, ...]


# ---------------------------------------------------------------- endpoint lookup helper


def endpoint_lookup_from_roots(created_at_by_root: Mapping[str, datetime], *, retired: Sequence[str] = (),
                               superseded: Sequence[str] = ()) -> EndpointLookup:
    """呼び出し側が read-only の端点証拠から lookup を組み立てるための helper（Foundation store を読まない）。"""
    retired_set, superseded_set = set(retired), set(superseded)

    def lookup(root_id: str, cutoff: datetime) -> EndpointState:
        created = created_at_by_root.get(root_id)
        if created is None:
            return EndpointState.UNKNOWN_ROOT
        if created > cutoff:
            return EndpointState.NOT_CREATED_YET
        if root_id in superseded_set:
            return EndpointState.SUPERSEDED
        if root_id in retired_set:
            return EndpointState.RETIRED
        return EndpointState.EXISTS_AT_CUTOFF

    return lookup


# ---------------------------------------------------------------- chain 解決（共通）


@dataclass(frozen=True, kw_only=True)
class _ChainOutcome:
    order: Tuple[str, ...]
    status: RelationResolutionStatus
    diagnostics: Tuple[str, ...]


def _resolve_chain(records: Mapping[str, object], *, predecessor_of: Mapping[str, str],
                   recorded_at_of: Mapping[str, datetime], known_ids: Set[str]) -> _ChainOutcome:
    """predecessor graph だけで chain を解く。時刻や物理順で勝者を選ばない。"""
    diagnostics: List[str] = []
    for rid in sorted(records):
        predecessor = predecessor_of[rid]
        if predecessor and predecessor not in records:
            code = "PREDECESSOR_WRONG_EDGE" if predecessor in known_ids else "DANGLING_PREDECESSOR"
            return _ChainOutcome(order=(), status=RelationResolutionStatus.INVALID_HISTORY, diagnostics=(f"{code}:{rid}",))
    children: Dict[str, List[str]] = {}
    starts: List[str] = []
    for rid in sorted(records):
        predecessor = predecessor_of[rid]
        if predecessor == "":
            starts.append(rid)
        else:
            children.setdefault(predecessor, []).append(rid)
    if any(len(v) > 1 for v in children.values()):
        diagnostics.append("RELATION_FORK")
    if len(starts) > 1:
        diagnostics.append("MULTIPLE_STARTS")
    if not starts:
        return _ChainOutcome(order=(), status=RelationResolutionStatus.INVALID_HISTORY, diagnostics=("CYCLE",))
    if diagnostics:
        return _ChainOutcome(order=(), status=RelationResolutionStatus.UNRESOLVED, diagnostics=tuple(diagnostics))
    order: List[str] = []
    seen: Set[str] = set()
    cursor: Optional[str] = starts[0]
    while cursor:
        if cursor in seen:
            return _ChainOutcome(order=(), status=RelationResolutionStatus.INVALID_HISTORY, diagnostics=("CYCLE",))
        seen.add(cursor)
        order.append(cursor)
        following = children.get(cursor, [])
        cursor = following[0] if following else None
    if len(order) != len(records):
        return _ChainOutcome(order=(), status=RelationResolutionStatus.INVALID_HISTORY, diagnostics=("CYCLE",))
    for earlier, later in zip(order, order[1:]):
        if recorded_at_of[later] < recorded_at_of[earlier]:
            return _ChainOutcome(order=(), status=RelationResolutionStatus.INVALID_HISTORY,
                                 diagnostics=(f"NON_MONOTONIC_RECORDED_AT:{later}",))
    return _ChainOutcome(order=tuple(order), status=RelationResolutionStatus.RESOLVED, diagnostics=())


# ---------------------------------------------------------------- governance 解決


def _governance_state(events: Mapping[str, ThemeRelationGovernanceEvent], chain_ids: Set[str], known_event_ids: Set[str]
                      ) -> Tuple[EdgeState, Tuple[str, ...], RelationResolutionStatus, Tuple[str, ...]]:
    if not events:
        return EdgeState.ACTIVE, (), RelationResolutionStatus.RESOLVED, ()
    outcome = _resolve_chain(events, predecessor_of={k: v.previous_event_id for k, v in events.items()},
                             recorded_at_of={k: v.recorded_at for k, v in events.items()}, known_ids=known_event_ids)
    if outcome.status is not RelationResolutionStatus.RESOLVED:
        return EdgeState.ACTIVE, (), outcome.status, outcome.diagnostics
    expected = RelationGovernanceEventType.RETRACTED
    for event_id in outcome.order:
        event = events[event_id]
        if event.subject_assertion_id not in chain_ids:
            return (EdgeState.ACTIVE, outcome.order, RelationResolutionStatus.INVALID_HISTORY,
                    (f"INVALID_GOVERNANCE_TARGET:{event_id}",))
        if event.event_type is not expected:
            return (EdgeState.ACTIVE, outcome.order, RelationResolutionStatus.INVALID_HISTORY,
                    (f"INVALID_GOVERNANCE_SEQUENCE:{event_id}",))
        expected = (RelationGovernanceEventType.RESTORED if expected is RelationGovernanceEventType.RETRACTED
                    else RelationGovernanceEventType.RETRACTED)
    terminal = events[outcome.order[-1]]
    state = EdgeState.RETRACTED if terminal.event_type is RelationGovernanceEventType.RETRACTED else EdgeState.ACTIVE
    return state, outcome.order, RelationResolutionStatus.RESOLVED, ()


# ---------------------------------------------------------------- feedback loop（記述的な診断のみ）


def _loop_members(edges: Sequence[ResolvedRelation]) -> Tuple[str, ...]:
    """有向閉路に含まれる root（MVP では閉路は妥当。破損ではない）。"""
    adjacency: Dict[str, List[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source_theme_root_id, []).append(edge.target_theme_root_id)
    for key in adjacency:
        adjacency[key] = sorted(set(adjacency[key]))
    members: Set[str] = set()
    for origin in sorted(adjacency):
        stack: List[str] = [origin]
        seen: Set[str] = set()
        while stack:
            node = stack.pop()
            for following in adjacency.get(node, ()):
                if following == origin:
                    members.add(origin)
                if following not in seen:
                    seen.add(following)
                    stack.append(following)
    return tuple(sorted(members))


# ---------------------------------------------------------------- entry point


def _cutoff(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RelationModelError("INVALID_CUTOFF", "cutoff must be an aware datetime")
    return value.astimezone(timezone.utc)


def resolve_relation_graph(assertions: Sequence[ThemeRelationAssertion],
                           governance_events: Sequence[ThemeRelationGovernanceEvent], *, cutoff: datetime,
                           endpoint_lookup: EndpointLookup) -> ThemeRelationResolution:
    """同じ record 集合・同じ cutoff・同じ endpoint lookup なら、順序に依らず同じ結果を返す。"""
    moment = _cutoff(cutoff)
    assertions = tuple(assertions)
    governance_events = tuple(governance_events)
    if not all(isinstance(a, ThemeRelationAssertion) for a in assertions):
        raise RelationModelError("INVALID_TYPE", "assertions must be ThemeRelationAssertion records")
    if not all(isinstance(g, ThemeRelationGovernanceEvent) for g in governance_events):
        raise RelationModelError("INVALID_TYPE", "governance_events must be ThemeRelationGovernanceEvent records")
    if not callable(endpoint_lookup):
        raise RelationModelError("INVALID_TYPE", "endpoint_lookup must be callable")

    diagnostics: List[RelationDiagnostic] = []
    known_assertion_ids = {a.relation_assertion_id for a in assertions}
    known_event_ids = {g.event_id for g in governance_events}
    visible_assertions = [a for a in assertions if a.recorded_at <= moment]
    for record in assertions:
        if record.recorded_at > moment:
            diagnostics.append(RelationDiagnostic(code="FUTURE_RELATION", edge_key=record.edge_key,
                                                  detail=record.relation_assertion_id))
    visible_events = [g for g in governance_events if g.recorded_at <= moment]
    for event in governance_events:
        if event.recorded_at > moment:
            diagnostics.append(RelationDiagnostic(code="FUTURE_GOVERNANCE", edge_key=event.edge_key, detail=event.event_id))

    grouped: Dict[str, Dict[str, ThemeRelationAssertion]] = {}
    for record in visible_assertions:
        grouped.setdefault(record.edge_key, {})[record.relation_assertion_id] = record
    events_by_edge: Dict[str, Dict[str, ThemeRelationGovernanceEvent]] = {}
    for event in visible_events:
        events_by_edge.setdefault(event.edge_key, {})[event.event_id] = event
    for edge_key in sorted(set(events_by_edge) - set(grouped)):
        diagnostics.append(RelationDiagnostic(code="UNKNOWN_EDGE_GOVERNANCE", edge_key=edge_key))

    resolved: List[ResolvedRelation] = []
    unresolved: List[UnresolvedEdge] = []
    excluded: List[ExcludedEdge] = []

    for edge_key in sorted(grouped):
        source_root, target_root, relation_type, assertion_class, attribution_key = split_edge_key(edge_key)
        source_state = endpoint_lookup(source_root, moment)
        target_state = endpoint_lookup(target_root, moment)
        if source_state not in ENDPOINT_PRESENT_STATES or target_state not in ENDPOINT_PRESENT_STATES:
            missing = source_state if source_state not in ENDPOINT_PRESENT_STATES else target_state
            excluded.append(ExcludedEdge(edge_key=edge_key, reason=f"ENDPOINT_NOT_AVAILABLE_AT_CUTOFF:{missing.value}"))
            diagnostics.append(RelationDiagnostic(code="ENDPOINT_NOT_AVAILABLE_AT_CUTOFF", edge_key=edge_key,
                                                  detail=missing.value))
            continue
        records = grouped[edge_key]
        outcome = _resolve_chain(records, predecessor_of={k: v.previous_assertion_id for k, v in records.items()},
                                 recorded_at_of={k: v.recorded_at for k, v in records.items()},
                                 known_ids=known_assertion_ids)
        if outcome.status is not RelationResolutionStatus.RESOLVED:
            unresolved.append(UnresolvedEdge(edge_key=edge_key, status=outcome.status, diagnostics=outcome.diagnostics))
            diagnostics.extend(RelationDiagnostic(code=d.split(":")[0], edge_key=edge_key, detail=d)
                               for d in outcome.diagnostics)
            continue
        state, governance_chain, governance_status, governance_diagnostics = _governance_state(
            events_by_edge.get(edge_key, {}), set(outcome.order), known_event_ids)
        if governance_status is not RelationResolutionStatus.RESOLVED:
            unresolved.append(UnresolvedEdge(edge_key=edge_key, status=governance_status,
                                             diagnostics=governance_diagnostics))
            diagnostics.extend(RelationDiagnostic(code=d.split(":")[0], edge_key=edge_key, detail=d)
                               for d in governance_diagnostics)
            continue
        annotations: List[str] = []
        for name, endpoint in (("SOURCE", source_state), ("TARGET", target_state)):
            if endpoint is EndpointState.SUPERSEDED:
                annotations.append(f"ENDPOINT_SUPERSEDED:{name}")
            elif endpoint is EndpointState.RETIRED:
                annotations.append(f"ENDPOINT_RETIRED:{name}")
        resolved.append(ResolvedRelation(
            edge_key=edge_key, source_theme_root_id=source_root, target_theme_root_id=target_root,
            relation_type=relation_type, assertion_class=assertion_class, attribution_key=attribution_key,
            assertion=records[outcome.order[-1]], assertion_chain=outcome.order, edge_state=state,
            governance_chain=governance_chain, source_endpoint=source_state, target_endpoint=target_state,
            diagnostics=tuple(annotations)))

    loop_members = _loop_members([e for e in resolved if e.edge_state is EdgeState.ACTIVE])
    if loop_members:
        diagnostics.append(RelationDiagnostic(code="FEEDBACK_LOOP_PRESENT", detail=",".join(loop_members)))

    if any(u.status is RelationResolutionStatus.INVALID_HISTORY for u in unresolved):
        status = RelationResolutionStatus.INVALID_HISTORY
    elif unresolved:
        status = RelationResolutionStatus.UNRESOLVED
    elif not resolved:
        status = RelationResolutionStatus.NO_STATE
    else:
        status = RelationResolutionStatus.RESOLVED
    return ThemeRelationResolution(
        resolver_version=RELATION_RESOLVER_VERSION, cutoff=moment, status=status,
        edges=tuple(sorted(resolved, key=lambda e: e.edge_key)),
        unresolved=tuple(sorted(unresolved, key=lambda u: u.edge_key)),
        excluded=tuple(sorted(excluded, key=lambda e: (e.edge_key, e.reason))),
        diagnostics=tuple(sorted(set(diagnostics), key=lambda d: d.as_tuple())))


__all__ = ["ENDPOINT_PRESENT_STATES", "EdgeState", "EndpointLookup", "EndpointState", "ExcludedEdge",
           "RELATION_RESOLVER_VERSION", "RelationDiagnostic", "RelationResolutionStatus", "ResolvedRelation",
           "ThemeRelationResolution", "UnresolvedEdge", "endpoint_lookup_from_roots", "resolve_relation_graph"]
