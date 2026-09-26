"""Theme lifecycle derivation（P6-B2）— `ThemeResolution` 1 つから 2 層の lifecycle snapshot を導く純関数。

規則:
- 入力は Foundation resolver の `ThemeResolution`（T 固定）と明示の `LifecyclePolicy`。B1 の ChangeSet は入力にしない
  （lifecycle ＝ snapshot 意味論、ChangeSet ＝ delta 意味論）。
- governance 層は Foundation の `governance.status` / `effective_event_type` / `lineage` だけから決める。独自の
  latest-wins や競合解決をしない。Foundation が UNRESOLVED なら UNRESOLVED。
- evidence 層は Foundation の `EvidenceView` / `DerivedView`（counted attachments・independent origin・evidence date・
  qualification・contradiction / invalidation flag）を **再 count せず**参照する。
- correction event（ROLE_CORRECTION_APPROVED / CERTAINTY_CHANGE_APPROVED / METADATA_CORRECTION_APPROVED）は lifecycle 状態を
  変えない。それが effective（terminal）のときは、caller が渡した governance event（read-only）で chain を遡り、
  効力を持つ最後の lifecycle event を用いる。渡されなければ推測せず fail closed。
- 現在時刻・乱数・IO・network を使わない。journal を書かない。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from ..themes.model import EvidenceAttachment, EvidenceRole, EvidenceTimeQuality, GovernanceEventType, ThemeGovernanceEvent
from ..themes.qualification import QualificationStatus
from ..themes.resolver import GovernanceStatus, LineageKind, ResolutionStatus, ThemeResolution
from .lifecycle_model import (LIFECYCLE_MODEL_VERSION, LIFECYCLE_VIEW_SCHEMA_VERSION, EvidenceConditionFlag,
                              EvidenceConditionStatus, EvidenceConditionView, GovernanceLifecycleState,
                              GovernanceLifecycleView, LifecycleDiagnostic, LifecyclePolicy, LifecycleViewStatus,
                              ThemeLifecycleError, ThemeLifecycleView)
from .model import SUPPORTED_RESOLVER_VERSION

FAILURE_STATUSES = (ResolutionStatus.INVALID_HISTORY, ResolutionStatus.STORE_CORRUPTION)
#: lifecycle 状態を変えない governance event（訂正の承認）
CORRECTION_EVENT_TYPES = (GovernanceEventType.ROLE_CORRECTION_APPROVED, GovernanceEventType.CERTAINTY_CHANGE_APPROVED,
                          GovernanceEventType.METADATA_CORRECTION_APPROVED)
#: subject root 側の lineage（この root が移行元）
_SUBJECT_LINEAGE = {GovernanceEventType.MERGE: LineageKind.MERGED_INTO, GovernanceEventType.SPLIT: LineageKind.SPLIT_INTO,
                    GovernanceEventType.SUPERSEDED_BY_ROOT: LineageKind.SUPERSEDED_BY}
_TERMINAL_STATE = {GovernanceEventType.MERGE: GovernanceLifecycleState.MERGED,
                   GovernanceEventType.SPLIT: GovernanceLifecycleState.SPLIT,
                   GovernanceEventType.SUPERSEDED_BY_ROOT: GovernanceLifecycleState.SUPERSEDED}
_SIMPLE_STATE = {GovernanceEventType.CANDIDATE_ACCEPTED: GovernanceLifecycleState.ACCEPTED,
                 GovernanceEventType.REOPENED: GovernanceLifecycleState.ACCEPTED,
                 GovernanceEventType.CANDIDATE_REJECTED: GovernanceLifecycleState.REJECTED,
                 GovernanceEventType.RETIRED: GovernanceLifecycleState.RETIRED}


# ---------------------------------------------------------------- public API

def derive_lifecycle(resolution: ThemeResolution, *, policy: LifecyclePolicy,
                     governance_events: Optional[Iterable[ThemeGovernanceEvent]] = None) -> ThemeLifecycleView:
    """T 固定の `ThemeResolution` から 2 層 lifecycle view を導く。`policy` は明示入力（結果に残す）。

    `governance_events` は任意（read-only）。effective event が correction のときだけ chain を遡るために使う。"""
    if not isinstance(policy, LifecyclePolicy):
        raise ThemeLifecycleError("INVALID_POLICY", "policy must be a LifecyclePolicy")
    if resolution.resolver_version != SUPPORTED_RESOLVER_VERSION:
        raise ThemeLifecycleError("RESOLVER_VERSION_INCOMPATIBLE",
                                  f"{resolution.resolver_version!r} != {SUPPORTED_RESOLVER_VERSION!r}")
    diagnostics: List[LifecycleDiagnostic] = []
    if resolution.status in FAILURE_STATUSES:
        diagnostics.append(LifecycleDiagnostic("RESOLUTION_UNAVAILABLE", resolution.status.value,
                                               tuple(d.kind for d in resolution.diagnostics)))
        return _view(resolution, policy, LifecycleViewStatus.UNAVAILABLE,
                     GovernanceLifecycleView(resolution.governance.status, GovernanceLifecycleState.NOT_AVAILABLE),
                     EvidenceConditionView(EvidenceConditionStatus.NOT_EVALUATED, stale_after_days=policy.stale_after_days),
                     diagnostics)
    if resolution.status is ResolutionStatus.NO_STATE:
        diagnostics.append(LifecycleDiagnostic("NO_THEME_STATE", "no eligible observation at the cutoff",
                                               tuple(d.kind for d in resolution.diagnostics)
                                               + tuple(p.kind for p in resolution.pending)))
        governance = GovernanceLifecycleView(resolution.governance.status, GovernanceLifecycleState.NOT_AVAILABLE,
                                             resolution.governance.effective_event_id,
                                             resolution.governance.effective_event_type)
        return _view(resolution, policy, LifecycleViewStatus.UNAVAILABLE, governance,
                     EvidenceConditionView(EvidenceConditionStatus.NOT_EVALUATED, stale_after_days=policy.stale_after_days),
                     diagnostics)
    governance = _governance(resolution, governance_events, diagnostics)
    evidence = _evidence(resolution, policy, diagnostics)
    if governance.state is GovernanceLifecycleState.UNRESOLVED or evidence.status is EvidenceConditionStatus.UNRESOLVED:
        status = LifecycleViewStatus.PARTIALLY_AVAILABLE
    else:
        status = LifecycleViewStatus.AVAILABLE
    return _view(resolution, policy, status, governance, evidence, diagnostics)


# ---------------------------------------------------------------- governance layer

def _governance(resolution: ThemeResolution, governance_events: Optional[Iterable[ThemeGovernanceEvent]],
                diagnostics: List[LifecycleDiagnostic]) -> GovernanceLifecycleView:
    facet = resolution.governance
    if facet.status is GovernanceStatus.UNRESOLVED:
        diagnostics.append(LifecycleDiagnostic("GOVERNANCE_UNRESOLVED", "Foundation governance facet is UNRESOLVED",
                                               tuple(d.kind for d in facet.diagnostics)))
        return GovernanceLifecycleView(facet.status, GovernanceLifecycleState.UNRESOLVED)
    if facet.status is GovernanceStatus.NOT_EVALUATED:
        return GovernanceLifecycleView(facet.status, GovernanceLifecycleState.NOT_AVAILABLE)
    if facet.status is GovernanceStatus.NO_GOVERNANCE or facet.effective_event_type is None:
        return GovernanceLifecycleView(facet.status, GovernanceLifecycleState.UNREVIEWED, facet.effective_event_id,
                                       facet.effective_event_type)
    state_event_id, event_type = facet.effective_event_id, facet.effective_event_type
    if event_type in CORRECTION_EVENT_TYPES:
        state_event_id, event_type = _lifecycle_event_before_correction(resolution, governance_events, diagnostics)
    state = _state_for(resolution, state_event_id, event_type, diagnostics)
    return GovernanceLifecycleView(facet.status, state, facet.effective_event_id, facet.effective_event_type,
                                   state_event_id)


def _lifecycle_event_before_correction(resolution: ThemeResolution,
                                       governance_events: Optional[Iterable[ThemeGovernanceEvent]],
                                       diagnostics: List[LifecycleDiagnostic]) -> Tuple[str, Optional[GovernanceEventType]]:
    """effective event が correction のとき、chain を遡って効力を持つ最後の lifecycle event を返す（無ければ空）。"""
    facet = resolution.governance
    if governance_events is None:
        raise ThemeLifecycleError("GOVERNANCE_EVENTS_REQUIRED",
                                  f"effective event {facet.effective_event_id} is a correction; pass governance_events "
                                  "to walk the chain (the lifecycle state is not guessed)")
    types: Mapping[str, GovernanceEventType] = {e.event_id: e.event_type for e in governance_events}
    missing = tuple(event_id for event_id in facet.chain if event_id not in types)
    if missing:
        raise ThemeLifecycleError("GOVERNANCE_EVENTS_INCOMPLETE", f"chain events not supplied: {missing[:3]}")
    reversed_ids = set(facet.reversed_event_ids)
    for event_id in reversed(facet.chain):
        kind = types[event_id]
        if event_id in reversed_ids or kind is GovernanceEventType.EVENT_REVERSED or kind in CORRECTION_EVENT_TYPES:
            continue
        diagnostics.append(LifecycleDiagnostic("CORRECTION_TERMINAL_IGNORED",
                                               f"{facet.effective_event_type.value} does not change the lifecycle state",
                                               (facet.effective_event_id, event_id)))
        return event_id, kind
    diagnostics.append(LifecycleDiagnostic("CORRECTION_TERMINAL_IGNORED",
                                           f"{facet.effective_event_type.value} does not change the lifecycle state",
                                           (facet.effective_event_id,)))
    return "", None


def _state_for(resolution: ThemeResolution, event_id: str, event_type: Optional[GovernanceEventType],
               diagnostics: List[LifecycleDiagnostic]) -> GovernanceLifecycleState:
    if event_type is None:
        return GovernanceLifecycleState.UNREVIEWED
    if event_type in _SIMPLE_STATE:
        return _SIMPLE_STATE[event_type]
    if event_type in _TERMINAL_STATE:
        subject_kind = _SUBJECT_LINEAGE[event_type]
        if any(l.event_id == event_id and l.kind is subject_kind for l in resolution.lineage):
            return _TERMINAL_STATE[event_type]
        # この root は event の result 側（MERGE_OF / SPLIT_FROM / SUCCESSOR_OF）: 宣言 event は受理決定ではない
        diagnostics.append(LifecycleDiagnostic("ORIGIN_EVENT_ONLY",
                                               f"{event_type.value} is this root's origin event, not a review decision",
                                               (event_id,)))
        return GovernanceLifecycleState.UNREVIEWED
    raise ThemeLifecycleError("UNKNOWN_GOVERNANCE_EVENT_TYPE", str(event_type))


# ---------------------------------------------------------------- evidence layer

def _evidence(resolution: ThemeResolution, policy: LifecyclePolicy,
              diagnostics: List[LifecycleDiagnostic]) -> EvidenceConditionView:
    if resolution.status is ResolutionStatus.UNRESOLVED:
        diagnostics.append(LifecycleDiagnostic("SEMANTIC_UNRESOLVED", "evidence condition is not evaluated",
                                               tuple(d.kind for d in resolution.diagnostics)))
        return EvidenceConditionView(EvidenceConditionStatus.UNRESOLVED, stale_after_days=policy.stale_after_days)
    view, derived = resolution.evidence, resolution.derived
    qualification = derived.qualification
    counted_keys = set(qualification.counted_attachment_keys)
    visible: Tuple[EvidenceAttachment, ...] = view.visible
    counted = tuple(a for a in visible if a.attachment_key in counted_keys)
    flags: List[EvidenceConditionFlag] = []
    if not counted:
        flags.append(EvidenceConditionFlag.NO_VISIBLE_EVIDENCE)
        if visible:
            flags.append(EvidenceConditionFlag.HAS_CONTEXT_ONLY)
    if any(a.role is EvidenceRole.SUPPORTS for a in counted):
        flags.append(EvidenceConditionFlag.HAS_SUPPORT)
    if qualification.independent_origins == 1:
        flags.append(EvidenceConditionFlag.SINGLE_SOURCE)
    elif qualification.independent_origins >= 2:
        flags.append(EvidenceConditionFlag.MULTI_SOURCE)
    if len(qualification.evidence_dates) == 1:
        flags.append(EvidenceConditionFlag.SINGLE_EVIDENCE_DATE)
    elif len(qualification.evidence_dates) >= 2:
        flags.append(EvidenceConditionFlag.MULTI_DATE)
    if qualification.status is QualificationStatus.QUALIFIES_SEMANTICALLY:
        flags.append(EvidenceConditionFlag.QUALIFIES)
    if derived.has_contradicting_evidence:
        flags.append(EvidenceConditionFlag.CONTESTED)
    if derived.has_invalidating_evidence:
        flags.append(EvidenceConditionFlag.INVALIDATION_EVIDENCE_PRESENT)
    latest, elapsed = _freshness(counted, resolution.cutoff)
    if latest is None:
        diagnostics.append(LifecycleDiagnostic("STALE_NOT_EVALUABLE_NO_DATED_EVIDENCE",
                                               "no counted evidence with a known evidence_time"))
    elif elapsed >= policy.stale_after_days:
        flags.append(EvidenceConditionFlag.STALE)
    return EvidenceConditionView(
        EvidenceConditionStatus.EVALUATED, flags=tuple(sorted(flags, key=_FLAG_ORDER.__getitem__)),
        visible_evidence_count=len(visible), counted_evidence_count=len(counted),
        independent_origin_count=qualification.independent_origins, evidence_date_count=len(qualification.evidence_dates),
        qualification_status=qualification.status, latest_dated_evidence_time=latest, elapsed_calendar_days=elapsed,
        stale_after_days=policy.stale_after_days)


def _freshness(counted: Tuple[EvidenceAttachment, ...], cutoff: datetime) -> Tuple[Optional[datetime], Optional[int]]:
    """最新の dated counted evidence の evidence_time と、その日付から cutoff の日付までの calendar 日数。"""
    dated = [a.evidence_time for a in counted
             if a.evidence_time is not None and a.evidence_time_quality is not EvidenceTimeQuality.MISSING]
    if not dated:
        return None, None
    latest = max(dated)
    elapsed = (cutoff.astimezone(timezone.utc).date() - latest.astimezone(timezone.utc).date()).days
    return latest, elapsed


_FLAG_ORDER: Dict[EvidenceConditionFlag, int] = {flag: index for index, flag in enumerate(EvidenceConditionFlag)}


# ---------------------------------------------------------------- assembly

def _view(resolution: ThemeResolution, policy: LifecyclePolicy, status: LifecycleViewStatus,
          governance: GovernanceLifecycleView, evidence: EvidenceConditionView,
          diagnostics: List[LifecycleDiagnostic]) -> ThemeLifecycleView:
    return ThemeLifecycleView(
        schema_version=LIFECYCLE_VIEW_SCHEMA_VERSION, lifecycle_model_version=LIFECYCLE_MODEL_VERSION, policy=policy,
        root_id=resolution.root_id, cutoff=resolution.cutoff, resolution_status=resolution.status, status=status,
        governance=governance, evidence=evidence, diagnostics=tuple(diagnostics))


__all__ = ["derive_lifecycle", "CORRECTION_EVENT_TYPES", "FAILURE_STATUSES"]
