"""宣言先行の論理操作（Phase 6 P6-A4b）— A3 §9 / §17 / §18 / §19 を ThemeStore の公開 API の上で組み立てる。

原則:
- **plan は先に全 id を確定する**（root id は呼び出し側が `new_root_id` で生成して渡す。observation / event id は
  content-addressed）。plan は同じ入力から同じ record を返す純関数（store からは不変 record を読むだけ）。
- **execute は append の列**であり、各 append は byte 冪等。途中で止まれば store は PENDING_EVENT / PENDING_GENESIS
  を示し、**同じ plan** を再実行すると残りだけが書かれる。別の id を生成しない。crash 後に plan を失った場合は、
  store の PENDING が宣言済みの result root id を示すので、同じ入力で plan を作り直せる（content id は一致する）。
- 現在時刻を呼ばない（すべて注入）。cross-file の原子性は主張しない。部分完了を隠さない。
- 順序は固定: 宣言 event → 結果 RootRecord → 結果 genesis（A3 §9）。逆順は store が拒否する。
- carried evidence は宣言 event の `evidence_allocation` に列挙したものだけを、source attachment と **byte 同一**で
  genesis に載せる（元 attached_at / role provenance を保持。lineage は event の配分が保持する）。暗黙の carry なし。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .model import (CreationMethod, EvidenceAllocation, EvidenceAttachment, GovernanceEventType, InferredExposureLink,
                    InvalidationCondition, Limitation, Mechanism, MechanismCertainty, ObservationProvenance,
                    ProvenanceClass, ScopeToken, ThemeGovernanceEvent, ThemeObservation, ThemeRootRecord,
                    ThemeSubject, make_root_record)
from .store import AppendResult, AppendStatus, PendingItem, ThemeAppendRejected, ThemeStore


class OperationStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class StepResult:
    authority: str
    record_id: str
    status: AppendStatus


@dataclass(frozen=True)
class OperationResult:
    operation: str
    status: OperationStatus
    steps: Tuple[StepResult, ...]
    pending: Tuple[PendingItem, ...]


@dataclass(frozen=True, kw_only=True)
class GenesisSpec:
    """genesis observation の semantic content（root id を除く）。attachment は candidate のみ直接持てる。"""

    subject: ThemeSubject
    mechanism: Mechanism
    certainty_class: MechanismCertainty
    scope: Tuple[ScopeToken, ...]
    invalidation_conditions: Tuple[InvalidationCondition, ...]
    limitations: Tuple[Limitation, ...] = ()
    inferred_links: Tuple[InferredExposureLink, ...] = ()
    provenance: ObservationProvenance
    recorded_at: datetime


@dataclass(frozen=True, kw_only=True)
class ResultRootSpec:
    """MERGE / SPLIT / SUCCESSOR の結果 root 1 つ分。`carried` は (source observation id, attachment_key) の明示列挙。"""

    root_id: str
    created_at: datetime
    creation_provenance: str
    genesis: GenesisSpec
    carried: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CandidatePlan:
    root: ThemeRootRecord
    genesis: ThemeObservation


@dataclass(frozen=True)
class DeclarationPlan:
    operation: str
    event: ThemeGovernanceEvent
    results: Tuple[Tuple[ThemeRootRecord, ThemeObservation], ...]


# ---------------------------------------------------------------- helpers

def terminal_previous_events(store: ThemeStore, roots: Sequence[str]) -> Tuple[Tuple[str, str], ...]:
    """各 root の物理 terminal event を previous_event_ids として返す（履歴の無い root は含めない）。

    曖昧（terminal が複数）なら拒否する。**最初の試行の前に一度だけ**呼び、再試行では同じ値を渡すこと
    （宣言 event が書かれた後に呼ぶと terminal がその event になり、別の event id が生まれる）。
    """
    out: List[Tuple[str, str]] = []
    for root_id in sorted(set(roots)):
        terminals = store.physical_terminal_events(root_id)
        if len(terminals) > 1:
            raise ThemeAppendRejected("NON_TERMINAL_PREDECESSOR",
                                      f"root {root_id} has {len(terminals)} physical terminal events; human decision required",
                                      authority="governance")
        if terminals:
            out.append((root_id, terminals[0]))
    return tuple(out)


def _build_genesis(root_id: str, spec: GenesisSpec, attachments: Sequence[EvidenceAttachment],
                   governance_event_id: str = "") -> ThemeObservation:
    provenance = spec.provenance
    if governance_event_id and not provenance.governance_event_id:
        provenance = replace(provenance, governance_event_id=governance_event_id)
    return ThemeObservation.build(
        root_id=root_id, previous_observation_id="", subject=spec.subject, mechanism=spec.mechanism,
        certainty_class=spec.certainty_class, scope=spec.scope, limitations=spec.limitations,
        invalidation_conditions=spec.invalidation_conditions, inferred_links=spec.inferred_links,
        attachments=tuple(attachments), provenance=provenance, recorded_at=spec.recorded_at)


def _carried_attachments(store: ThemeStore, carried: Sequence[Tuple[str, str]]) -> Tuple[EvidenceAttachment, ...]:
    out: List[EvidenceAttachment] = []
    for source_id, key in carried:
        source = store.get_observation(source_id)
        attachment = None if source is None else source.attachment(key)
        if attachment is None:
            raise ThemeAppendRejected("ALLOCATION_VIOLATION", f"{key} is not an attachment of stored {source_id}",
                                      authority="governance")
        out.append(attachment)   # byte 同一のまま carry（元 attached_at / provenance を保持）
    return tuple(out)


def _step(result: AppendResult) -> StepResult:
    return StepResult(result.authority, result.record_id, result.status)


# ---------------------------------------------------------------- CANDIDATE root

def plan_candidate(*, root_id: str, created_at: datetime, creator_class: ProvenanceClass, creation_provenance: str,
                   genesis: GenesisSpec, attachments: Sequence[EvidenceAttachment] = ()) -> CandidatePlan:
    """通常 root の作成 plan: genesis id を先に確定し、RootRecord がそれを宣言する（A3 §4.1）。"""
    observation = _build_genesis(root_id, genesis, attachments)
    root = make_root_record(root_id=root_id, created_at=created_at, creation_method=CreationMethod.CANDIDATE,
                            creator_class=creator_class, creation_provenance=creation_provenance,
                            genesis_observation_id=observation.observation_id)
    return CandidatePlan(root=root, genesis=observation)


def execute_candidate(store: ThemeStore, plan: CandidatePlan) -> OperationResult:
    """RootRecord → genesis の順に append（各 append は冪等。途中で止まれば PENDING_GENESIS）。"""
    steps = [_step(store.append_root(plan.root)), _step(store.append_observation(plan.genesis))]
    pending = tuple(p for p in store.pending() if p.subject_id == plan.root.root_id)
    status = OperationStatus.COMPLETE if not pending else OperationStatus.INCOMPLETE
    return OperationResult("CANDIDATE", status, tuple(steps), pending)


# ---------------------------------------------------------------- MERGE / SPLIT / SUCCESSOR（宣言先行）

_METHOD_BY_EVENT = {GovernanceEventType.MERGE: CreationMethod.MERGE_RESULT,
                    GovernanceEventType.SPLIT: CreationMethod.SPLIT_RESULT,
                    GovernanceEventType.SUPERSEDED_BY_ROOT: CreationMethod.SUCCESSOR_RESULT}


def _plan_declaration(store: ThemeStore, *, event_type: GovernanceEventType, subject_roots: Sequence[str],
                      results: Sequence[ResultRootSpec], reason: str, actor_ref: str, recorded_at: datetime,
                      previous_event_ids: Sequence[Tuple[str, str]]) -> DeclarationPlan:
    allocation = tuple(EvidenceAllocation(source_observation_id=src, attachment_key=key, result_root_id=spec.root_id)
                       for spec in results for src, key in spec.carried)
    event = ThemeGovernanceEvent.build(
        event_type=event_type, subject_roots=tuple(subject_roots), result_roots=tuple(s.root_id for s in results),
        reason=reason, actor_ref=actor_ref, recorded_at=recorded_at, previous_event_ids=tuple(previous_event_ids),
        evidence_allocation=allocation)
    built: List[Tuple[ThemeRootRecord, ThemeObservation]] = []
    for spec in results:
        genesis = _build_genesis(spec.root_id, spec.genesis, _carried_attachments(store, spec.carried), event.event_id)
        root = make_root_record(root_id=spec.root_id, created_at=spec.created_at,
                                creation_method=_METHOD_BY_EVENT[event_type], creator_class=ProvenanceClass.HUMAN,
                                creation_provenance=spec.creation_provenance,
                                genesis_observation_id=genesis.observation_id, origin_event_id=event.event_id)
        built.append((root, genesis))
    return DeclarationPlan(event_type.value, event, tuple(built))


def plan_merge(store: ThemeStore, *, subject_roots: Sequence[str], result: ResultRootSpec, reason: str,
               actor_ref: str, recorded_at: datetime,
               previous_event_ids: Sequence[Tuple[str, str]]) -> DeclarationPlan:
    return _plan_declaration(store, event_type=GovernanceEventType.MERGE, subject_roots=subject_roots,
                             results=(result,), reason=reason, actor_ref=actor_ref, recorded_at=recorded_at,
                             previous_event_ids=previous_event_ids)


def plan_split(store: ThemeStore, *, subject_root: str, children: Sequence[ResultRootSpec], reason: str,
               actor_ref: str, recorded_at: datetime,
               previous_event_ids: Sequence[Tuple[str, str]]) -> DeclarationPlan:
    return _plan_declaration(store, event_type=GovernanceEventType.SPLIT, subject_roots=(subject_root,),
                             results=tuple(children), reason=reason, actor_ref=actor_ref, recorded_at=recorded_at,
                             previous_event_ids=previous_event_ids)


def plan_successor(store: ThemeStore, *, subject_root: str, result: ResultRootSpec, reason: str, actor_ref: str,
                   recorded_at: datetime, previous_event_ids: Sequence[Tuple[str, str]]) -> DeclarationPlan:
    return _plan_declaration(store, event_type=GovernanceEventType.SUPERSEDED_BY_ROOT, subject_roots=(subject_root,),
                             results=(result,), reason=reason, actor_ref=actor_ref, recorded_at=recorded_at,
                             previous_event_ids=previous_event_ids)


def execute_declaration(store: ThemeStore, plan: DeclarationPlan) -> OperationResult:
    """event → (root → genesis)* の固定順で append。各 append は冪等。途中で止まれば PENDING_EVENT / PENDING_GENESIS。"""
    steps = [_step(store.append_governance(plan.event))]
    for root, genesis in plan.results:
        steps.append(_step(store.append_root(root)))
        steps.append(_step(store.append_observation(genesis)))
    involved = {plan.event.event_id} | {root.root_id for root, _ in plan.results}
    pending = tuple(p for p in store.pending() if p.subject_id in involved)
    status = OperationStatus.COMPLETE if not pending else OperationStatus.INCOMPLETE
    return OperationResult(plan.operation, status, tuple(steps), pending)


__all__ = [
    "OperationStatus", "StepResult", "OperationResult", "GenesisSpec", "ResultRootSpec", "CandidatePlan",
    "DeclarationPlan", "terminal_previous_events", "plan_candidate", "execute_candidate", "plan_merge", "plan_split",
    "plan_successor", "execute_declaration",
]
