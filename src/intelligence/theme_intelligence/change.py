"""Theme change detection（P6-B1）— 2 つの点時刻再構成の **純比較**。authority ではない。

問い: 「root_id について、T1 に知られていた状態と T2 に知られていた状態の間で何が変わったか」。

規則:
- 入力は Foundation resolver の `ThemeResolution` 2 つ（before / after）。store / resolver の意味論を再実装しない。
- 同一 before / after → 同一 `ThemeChangeSet`（frozen dataclass 等価）。現在時刻・乱数・IO を使わない。
- T1 <= T2、同一 root_id、同一（かつ対応する）resolver version を要求し、違反は fail closed（`ThemeChangeError`）。
- INVALID_HISTORY / STORE_CORRUPTION は通常の変化として扱わず、`ChangeSetStatus.UNAVAILABLE` で返す。
  NO_STATE / UNRESOLVED は failure ではない。
- knowledge 軸（attached_at / recorded_at: subsystem がいつ知ったか）と evidence-time 軸（evidence_time: evidence が指す
  時点）を別 field に分けて返す。
- evidence の対応は attachment_key。role 訂正で key が変わる場合は同一 ref_id（または `revision_of_at_attachment`）から
  決定論的に 1:1 対応づくときだけ EVIDENCE_ROLE_CHANGED / EVIDENCE_REF_REVISED とし、曖昧なら ADDED / DROPPED のまま。
- diversity（independent origin / evidence date）は Foundation DerivedView の値（A4a の保守的 helper の結果）を比較する。
  B1 で origin grouping を再定義しない。
- 上流 dereference の変化は canonical の変化と別の change class（DEREFERENCE_CHANGED）。canonical evidence は残る。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Mapping, Optional, Set, Tuple

from ..themes.model import EvidenceAttachment, EvidenceTimeQuality, MetadataField, ThemeObservation, canonical_json
from ..themes.qualification import QualificationResult
from ..themes.resolver import (GovernanceStatus, MappingStatus, MetadataFacet, MetadataStatus, ResolutionStatus,
                               ThemeHistory, ThemeResolution, UpstreamLookup, resolve)
from .model import (CHANGE_MODEL_VERSION, CHANGE_SCHEMA_VERSION, FACET_ORDER, SUPPORTED_RESOLVER_VERSION, Change,
                    ChangeDiagnostic, ChangeKind, ChangeSetStatus, EvidenceKnowledge, EvidenceTimeAxis,
                    EvidenceTimeRelation, EvidenceTiming, KnowledgeAxis, ThemeChangeError, ThemeChangeSet)

FAILURE_STATUSES = (ResolutionStatus.INVALID_HISTORY, ResolutionStatus.STORE_CORRUPTION)
#: semantic field（attachment / provenance / id / version / recorded_at を除く）。identity core は同一 root で不変だが検査する。
SEMANTIC_FIELDS: Tuple[str, ...] = ("subject", "mechanism.drivers", "mechanism.channels", "mechanism.domains",
                                    "mechanism.consequences", "certainty_class", "scope", "limitations",
                                    "invalidation_conditions", "inferred_links")
#: attachment の比較で無視する field（identity）
_ATTACHMENT_IDENTITY_FIELDS = ("ref_id", "consequence_ref")
CLEARED_NOTE = ("cleared means the current observation at T2 has no visible evidence in this role; "
                "it does not mean the earlier evidence was refuted or removed from history")
NOT_A_PROMOTION = "qualification is the A2 §19 predicate (source/date diversity), not a lifecycle promotion"
_KIND_ORDER = {kind: index for index, kind in enumerate(ChangeKind)}


# ---------------------------------------------------------------- public API

def compare_resolutions(before: ThemeResolution, after: ThemeResolution) -> ThemeChangeSet:
    """主 authority: 2 つの ThemeResolution（同一 root、T1 <= T2）の決定論的差分。"""
    _validate(before, after)
    if before.status in FAILURE_STATUSES or after.status in FAILURE_STATUSES:
        return _unavailable(before, after)
    changes: List[Change] = []
    diagnostics: List[ChangeDiagnostic] = []
    knowledge_evidence: List[EvidenceKnowledge] = []
    timing: List[EvidenceTiming] = []
    _root_changes(before, after, changes)
    baseline, observation_recorded_at = _semantic_changes(before, after, changes, diagnostics)
    new_dates: Tuple[str, ...] = ()
    if baseline is not None:
        _evidence_changes(before, after, baseline, changes, knowledge_evidence, timing)
        new_dates = _derived_changes(before, after, baseline, changes)
    _governance_changes(before, after, changes)
    _metadata_changes(before, after, changes)
    mappings_recorded_at = _mapping_changes(before, after, changes)
    _lineage_changes(before, after, changes)
    _pending_changes(before, after, changes)
    _dereference_changes(before, after, changes)
    changes.sort(key=_sort_key)
    knowledge_evidence.sort(key=lambda e: (e.attached_at, e.attachment_key))
    timing.sort(key=lambda t: (t.evidence_time or datetime.min.replace(tzinfo=before.cutoff.tzinfo), t.attachment_key))
    return ThemeChangeSet(
        schema_version=CHANGE_SCHEMA_VERSION, change_model_version=CHANGE_MODEL_VERSION,
        resolver_version=after.resolver_version, root_id=after.root_id, from_cutoff=before.cutoff,
        to_cutoff=after.cutoff, status=ChangeSetStatus.COMPUTED, from_status=before.status, to_status=after.status,
        from_observation_id=_observation_id(before), to_observation_id=_observation_id(after),
        changes=tuple(changes),
        knowledge_axis=KnowledgeAxis(evidence=tuple(knowledge_evidence), observation_recorded_at=observation_recorded_at,
                                     mappings_recorded_at=mappings_recorded_at),
        evidence_time_axis=EvidenceTimeAxis(
            evidence=tuple(timing), new_evidence_dates=new_dates,
            dated_within_window=sum(1 for t in timing if t.relation is EvidenceTimeRelation.DATED_WITHIN_WINDOW),
            dated_before_window=sum(1 for t in timing if t.relation is EvidenceTimeRelation.DATED_BEFORE_WINDOW),
            undated=sum(1 for t in timing if t.relation is EvidenceTimeRelation.UNDATED)),
        diagnostics=tuple(diagnostics))


def detect_changes(history: ThemeHistory, root_id: str, from_cutoff: datetime, to_cutoff: datetime, *,
                   dereference_before: Optional[UpstreamLookup] = None,
                   dereference_after: Optional[UpstreamLookup] = None) -> ThemeChangeSet:
    """任意 wrapper: 同じ history を T1 / T2 で解決して比較する（resolver の公開 entry point 経由。IO なし）。"""
    if from_cutoff > to_cutoff:
        raise ThemeChangeError("CUTOFF_ORDER", "from_cutoff must be <= to_cutoff")
    before = resolve(history, root_id, from_cutoff, dereference=dereference_before)
    after = resolve(history, root_id, to_cutoff, dereference=dereference_after)
    return compare_resolutions(before, after)


# ---------------------------------------------------------------- validation / failure

def _validate(before: ThemeResolution, after: ThemeResolution) -> None:
    if before.root_id != after.root_id:
        raise ThemeChangeError("ROOT_MISMATCH", f"{before.root_id} != {after.root_id}")
    if before.cutoff > after.cutoff:
        raise ThemeChangeError("CUTOFF_ORDER", "before.cutoff must be <= after.cutoff")
    if before.resolver_version != after.resolver_version or after.resolver_version != SUPPORTED_RESOLVER_VERSION:
        raise ThemeChangeError("RESOLVER_VERSION_INCOMPATIBLE",
                               f"{before.resolver_version!r} / {after.resolver_version!r} != {SUPPORTED_RESOLVER_VERSION!r}")


def _unavailable(before: ThemeResolution, after: ThemeResolution) -> ThemeChangeSet:
    diagnostics = []
    for side, res in (("before", before), ("after", after)):
        if res.status in FAILURE_STATUSES:
            diagnostics.append(ChangeDiagnostic(f"{side.upper()}_UNAVAILABLE", res.status.value,
                                                tuple(d.kind for d in res.diagnostics)))
    return ThemeChangeSet(
        schema_version=CHANGE_SCHEMA_VERSION, change_model_version=CHANGE_MODEL_VERSION,
        resolver_version=after.resolver_version, root_id=after.root_id, from_cutoff=before.cutoff,
        to_cutoff=after.cutoff, status=ChangeSetStatus.UNAVAILABLE, from_status=before.status, to_status=after.status,
        from_observation_id=_observation_id(before), to_observation_id=_observation_id(after), changes=(),
        knowledge_axis=KnowledgeAxis(), evidence_time_axis=EvidenceTimeAxis(), diagnostics=tuple(diagnostics))


# ---------------------------------------------------------------- root / semantic

def _root_changes(before: ThemeResolution, after: ThemeResolution, changes: List[Change]) -> None:
    if before.root is None and after.root is not None:
        changes.append(Change(ChangeKind.ROOT_APPEARED, "root", after.root_id, after=_iso(after.root.created_at),
                              detail=after.root.creation_method.value))
    if before.status is ResolutionStatus.NO_STATE and after.status in (ResolutionStatus.RESOLVED,
                                                                        ResolutionStatus.UNRESOLVED):
        changes.append(Change(ChangeKind.ROOT_BECAME_OBSERVED, "root", after.root_id,
                              after=_observation_id(after), detail=after.status.value))


def _semantic_changes(before: ThemeResolution, after: ThemeResolution, changes: List[Change],
                      diagnostics: List[ChangeDiagnostic]) -> Tuple[Optional[str], Optional[datetime]]:
    """戻り値: (evidence / derived 差分の baseline 種別 'FULL' / 'EMPTY' / None, T2 observation の recorded_at)。"""
    b, a = before.status, after.status
    resolved, unresolved, no_state = ResolutionStatus.RESOLVED, ResolutionStatus.UNRESOLVED, ResolutionStatus.NO_STATE
    if b is resolved and a is resolved:
        recorded = None
        if before.observation.observation_id != after.observation.observation_id:
            changes.append(Change(ChangeKind.OBSERVATION_REVISED, "observation", after.observation.observation_id,
                                  before=_iso(before.observation.recorded_at), after=_iso(after.observation.recorded_at),
                                  related=(before.observation.observation_id,)))
            recorded = after.observation.recorded_at
        for name in SEMANTIC_FIELDS:
            old, new = _semantic_field(before.observation, name), _semantic_field(after.observation, name)
            if old != new:
                changes.append(Change(ChangeKind.SEMANTIC_FIELD_CHANGED, "observation", name, before=old, after=new))
        return "FULL", recorded
    if b is no_state and a is resolved:
        return "EMPTY", after.observation.recorded_at
    if a is unresolved and b is not unresolved:
        changes.append(Change(ChangeKind.SEMANTIC_BECAME_UNRESOLVED, "observation", after.root_id,
                              before=_observation_id(before) or b.value, detail=b.value + " -> UNRESOLVED",
                              related=tuple(d.kind for d in after.diagnostics)))
        diagnostics.append(ChangeDiagnostic("SEMANTIC_UNRESOLVED_AT_T2",
                                            "observation / evidence / derived differences are not computed",
                                            tuple(d.kind for d in after.diagnostics)))
        return None, None
    if b is unresolved and a is resolved:
        changes.append(Change(ChangeKind.SEMANTIC_BECAME_RESOLVED, "observation", after.root_id,
                              after=after.observation.observation_id, detail="UNRESOLVED -> RESOLVED"))
        diagnostics.append(ChangeDiagnostic("EVIDENCE_BASELINE_UNAVAILABLE",
                                            "T1 was UNRESOLVED; evidence / derived differences are not computed"))
        return None, after.observation.recorded_at
    if b is unresolved and a is unresolved:
        diagnostics.append(ChangeDiagnostic("SEMANTIC_UNRESOLVED_BOTH", "no observation baseline at T1 or T2"))
        return None, None
    if a is no_state and b is not no_state:
        diagnostics.append(ChangeDiagnostic("NON_MONOTONIC_INPUT", f"{b.value} at T1 but {a.value} at T2"))
        return None, None
    return None, None          # NO_STATE → NO_STATE（root / pending / lineage の変化だけがありうる）


def _semantic_field(observation: ThemeObservation, name: str) -> str:
    payload = observation.as_dict()
    head, _, tail = name.partition(".")
    value = payload[head]
    if tail:
        value = value[tail]      # type: ignore[index]
    return canonical_json(value)


# ---------------------------------------------------------------- evidence

def _evidence_changes(before: ThemeResolution, after: ThemeResolution, baseline: str, changes: List[Change],
                      knowledge: List[EvidenceKnowledge], timing: List[EvidenceTiming]) -> None:
    old: Dict[str, EvidenceAttachment] = ({a.attachment_key: a for a in before.evidence.visible}
                                          if baseline == "FULL" else {})
    new: Dict[str, EvidenceAttachment] = {a.attachment_key: a for a in after.evidence.visible}
    carried = {c.attachment_key for c in after.carried}
    dropped_reasons = {d.ref_id: d.reason for d in after.observation.provenance.dropped_attachments}
    added = sorted(set(new) - set(old))
    dropped = sorted(set(old) - set(new))
    paired_new: Set[str] = set()
    paired_old: Set[str] = set()

    def learned(key: str, kind: ChangeKind, *, world_time: bool) -> None:
        attachment = new[key]
        knowledge.append(EvidenceKnowledge(key, attachment.attached_at, kind))
        if world_time:
            timing.append(EvidenceTiming(key, attachment.evidence_time, attachment.evidence_date,
                                         _time_relation(attachment, before.cutoff, after.cutoff)))

    # 1. 上流 revision への付け替え（revision_of_at_attachment が旧 ref_id を指し、consequence が同じ 1 件だけに対応）
    for key in added:
        link = new[key].revision_of_at_attachment
        if not link:
            continue
        candidates = [k for k in dropped if k not in paired_old and old[k].ref_id == link
                      and old[k].consequence_ref == new[key].consequence_ref]
        if len(candidates) == 1:
            paired_new.add(key)
            paired_old.add(candidates[0])
            roles = (old[candidates[0]].role.value, new[key].role.value)
            changes.append(Change(ChangeKind.EVIDENCE_REF_REVISED, "evidence", key, before=old[candidates[0]].ref_id,
                                  after=new[key].ref_id, related=(candidates[0],),
                                  detail="" if roles[0] == roles[1] else f"role {roles[0]} -> {roles[1]}"))
            learned(key, ChangeKind.EVIDENCE_REF_REVISED, world_time=True)
    # 2. 同一 ref_id の 1:1 対応（consequence_ref が変わった role 訂正）。曖昧（複数）なら対応づけない
    by_ref_new: Dict[str, List[str]] = {}
    by_ref_old: Dict[str, List[str]] = {}
    for key in added:
        if key not in paired_new:
            by_ref_new.setdefault(new[key].ref_id, []).append(key)
    for key in dropped:
        if key not in paired_old:
            by_ref_old.setdefault(old[key].ref_id, []).append(key)
    for ref in sorted(set(by_ref_new) & set(by_ref_old)):
        if len(by_ref_new[ref]) == 1 and len(by_ref_old[ref]) == 1:
            new_key, old_key = by_ref_new[ref][0], by_ref_old[ref][0]
            if old[old_key].role is not new[new_key].role:
                paired_new.add(new_key)
                paired_old.add(old_key)
                changes.append(Change(ChangeKind.EVIDENCE_ROLE_CHANGED, "evidence", new_key,
                                      before=old[old_key].role.value, after=new[new_key].role.value,
                                      related=(old_key,), detail="consequence_ref changed"))
                learned(new_key, ChangeKind.EVIDENCE_ROLE_CHANGED, world_time=False)
    # 3. 同一 key
    for key in sorted(set(old) & set(new)):
        if old[key].role is not new[key].role:
            changes.append(Change(ChangeKind.EVIDENCE_ROLE_CHANGED, "evidence", key, before=old[key].role.value,
                                  after=new[key].role.value))
            learned(key, ChangeKind.EVIDENCE_ROLE_CHANGED, world_time=False)
        elif old[key] != new[key]:
            changed = tuple(sorted(f for f, (x, y) in _attachment_fields(old[key], new[key]).items() if x != y))
            changes.append(Change(ChangeKind.EVIDENCE_ATTRIBUTE_CHANGED, "evidence", key, related=changed))
    # 4. 残り
    for key in added:
        if key in paired_new:
            continue
        kind = ChangeKind.EVIDENCE_CARRIED if key in carried else ChangeKind.EVIDENCE_ADDED
        changes.append(Change(kind, "evidence", key, after=new[key].role.value,
                              detail=f"{new[key].evidence_kind.value} {new[key].ref_id}", related=(new[key].ref_id,)))
        learned(key, kind, world_time=True)
    for key in dropped:
        if key in paired_old:
            continue
        changes.append(Change(ChangeKind.EVIDENCE_DROPPED, "evidence", key, before=old[key].role.value,
                              detail=dropped_reasons.get(old[key].ref_id, ""), related=(old[key].ref_id,)))


def _attachment_fields(a: EvidenceAttachment, b: EvidenceAttachment) -> Dict[str, Tuple[str, str]]:
    da, db = a.as_dict(), b.as_dict()
    return {name: (canonical_json(da[name]), canonical_json(db[name])) for name in sorted(da)
            if name not in _ATTACHMENT_IDENTITY_FIELDS}


def _time_relation(attachment: EvidenceAttachment, from_cutoff: datetime, to_cutoff: datetime) -> EvidenceTimeRelation:
    if attachment.evidence_time is None or attachment.evidence_time_quality is EvidenceTimeQuality.MISSING:
        return EvidenceTimeRelation.UNDATED
    if attachment.evidence_time <= from_cutoff:
        return EvidenceTimeRelation.DATED_BEFORE_WINDOW
    return EvidenceTimeRelation.DATED_WITHIN_WINDOW      # evidence_time <= attached_at <= T2 は model が保証


# ---------------------------------------------------------------- derived（qualification / diversity / flags）

def _derived_changes(before: ThemeResolution, after: ThemeResolution, baseline: str,
                     changes: List[Change]) -> Tuple[str, ...]:
    old_q: Optional[QualificationResult] = before.derived.qualification if baseline == "FULL" else None
    new_q = after.derived.qualification
    old_origins = old_q.independent_origins if old_q else 0
    old_dates = set(old_q.evidence_dates) if old_q else set()
    root_id = after.root_id
    if new_q.independent_origins > old_origins:
        changes.append(Change(ChangeKind.NEW_SOURCE_ORIGIN, "derived", root_id, before=str(old_origins),
                              after=str(new_q.independent_origins), detail="counted independent source origins"))
    elif new_q.independent_origins < old_origins:
        changes.append(Change(ChangeKind.SOURCE_ORIGIN_LOST, "derived", root_id, before=str(old_origins),
                              after=str(new_q.independent_origins), detail="counted independent source origins"))
    new_dates = tuple(sorted(set(new_q.evidence_dates) - old_dates))
    for date in new_dates:
        changes.append(Change(ChangeKind.NEW_EVIDENCE_DATE, "derived", date, detail="counted evidence date"))
    for date in sorted(old_dates - set(new_q.evidence_dates)):
        changes.append(Change(ChangeKind.EVIDENCE_DATE_LOST, "derived", date, detail="counted evidence date"))
    old_status = old_q.status.value if old_q else ""
    if old_status != new_q.status.value:
        changes.append(Change(ChangeKind.QUALIFICATION_CHANGED, "derived", root_id, before=old_status,
                              after=new_q.status.value, detail=NOT_A_PROMOTION))
    old_contra = before.derived.has_contradicting_evidence if baseline == "FULL" else False
    old_inval = before.derived.has_invalidating_evidence if baseline == "FULL" else False
    _flag(changes, root_id, old_contra, after.derived.has_contradicting_evidence,
          ChangeKind.CONTRADICTION_APPEARED, ChangeKind.CONTRADICTION_CLEARED)
    _flag(changes, root_id, old_inval, after.derived.has_invalidating_evidence,
          ChangeKind.INVALIDATION_APPEARED, ChangeKind.INVALIDATION_CLEARED)
    return new_dates


def _flag(changes: List[Change], root_id: str, old: bool, new: bool, appeared: ChangeKind, cleared: ChangeKind) -> None:
    if not old and new:
        changes.append(Change(appeared, "derived", root_id, before="false", after="true"))
    elif old and not new:
        changes.append(Change(cleared, "derived", root_id, before="true", after="false", detail=CLEARED_NOTE))


# ---------------------------------------------------------------- facets（governance / metadata / mapping）

def _facet_transition(facet: str, root_id: str, old_unresolved: bool, new_unresolved: bool,
                      related: Tuple[str, ...], changes: List[Change]) -> bool:
    """UNRESOLVED の出入りを記録し、両側とも解決済みなら True（内容比較してよい）。"""
    if new_unresolved and not old_unresolved:
        changes.append(Change(ChangeKind.FACET_BECAME_UNRESOLVED, facet, root_id, related=related))
    elif old_unresolved and not new_unresolved:
        changes.append(Change(ChangeKind.FACET_BECAME_RESOLVED, facet, root_id))
    return not old_unresolved and not new_unresolved


def _governance_changes(before: ThemeResolution, after: ThemeResolution, changes: List[Change]) -> None:
    old, new = before.governance, after.governance
    comparable = _facet_transition("governance", after.root_id, old.status is GovernanceStatus.UNRESOLVED,
                                   new.status is GovernanceStatus.UNRESOLVED, tuple(d.kind for d in new.diagnostics),
                                   changes)
    if not comparable:
        return
    parts = []
    if old.effective_event_id != new.effective_event_id or old.effective_event_type is not new.effective_event_type:
        parts.append("effective_event")
    if old.terminal_event_id != new.terminal_event_id:
        parts.append("terminal_event")
    if old.reversed_event_ids != new.reversed_event_ids:
        parts.append("reversal")
    if parts:
        changes.append(Change(ChangeKind.GOVERNANCE_CHANGED, "governance",
                              new.effective_event_id or new.terminal_event_id,
                              before=old.effective_event_type.value if old.effective_event_type else "",
                              after=new.effective_event_type.value if new.effective_event_type else "",
                              detail=",".join(parts), related=tuple(e for e in new.chain if e not in old.chain)))


def _metadata_changes(before: ThemeResolution, after: ThemeResolution, changes: List[Change]) -> None:
    old_by_field = {m.field: m for m in before.metadata}
    new_by_field = {m.field: m for m in after.metadata}
    for field in MetadataField:
        old = old_by_field.get(field, MetadataFacet(field, MetadataStatus.NOT_EVALUATED))
        new = new_by_field.get(field, MetadataFacet(field, MetadataStatus.NOT_EVALUATED))
        facet = f"metadata:{field.value}"
        comparable = _facet_transition(facet, after.root_id, old.status is MetadataStatus.UNRESOLVED,
                                       new.status is MetadataStatus.UNRESOLVED, tuple(d.kind for d in new.diagnostics),
                                       changes)
        if comparable and (old.record_id, old.value) != (new.record_id, new.value):
            changes.append(Change(ChangeKind.METADATA_CHANGED, facet, new.record_id, before=canonical_json(list(old.value)),
                                  after=canonical_json(list(new.value)),
                                  related=(old.record_id,) if old.record_id else ()))


def _mapping_changes(before: ThemeResolution, after: ThemeResolution,
                     changes: List[Change]) -> Tuple[Tuple[str, datetime], ...]:
    old, new = before.mapping, after.mapping
    comparable = _facet_transition("mapping", after.root_id, old.status is MappingStatus.UNRESOLVED,
                                   new.status is MappingStatus.UNRESOLVED, tuple(d.kind for d in new.diagnostics), changes)
    if not comparable:
        return ()
    old_ids, new_ids = set(old.terminal_mapping_ids), set(new.terminal_mapping_ids)
    if old_ids == new_ids:
        return ()
    added = tuple(sorted(new_ids - old_ids))
    changes.append(Change(ChangeKind.MAPPING_CHANGED, "mapping", after.root_id, before=canonical_json(sorted(old_ids)),
                          after=canonical_json(sorted(new_ids)), related=added,
                          detail="superseded:" + ",".join(sorted(old_ids - new_ids)) if old_ids - new_ids else ""))
    recorded = {m.mapping_id: m.recorded_at for m in new.mappings}
    return tuple((mapping_id, recorded[mapping_id]) for mapping_id in added if mapping_id in recorded)


# ---------------------------------------------------------------- lineage / pending / dereference

def _lineage_changes(before: ThemeResolution, after: ThemeResolution, changes: List[Change]) -> None:
    old = {(l.kind.value, l.event_id, l.related_roots) for l in before.lineage}
    new = {(l.kind.value, l.event_id, l.related_roots) for l in after.lineage}
    for kind, event_id, roots in sorted(new - old):
        changes.append(Change(ChangeKind.LINEAGE_CHANGED, "lineage", event_id, after=kind, related=roots))
    for kind, event_id, roots in sorted(old - new):
        changes.append(Change(ChangeKind.LINEAGE_CHANGED, "lineage", event_id, before=kind, related=roots,
                              detail="lineage relation no longer visible (not expected for one history)"))


def _pending_changes(before: ThemeResolution, after: ThemeResolution, changes: List[Change]) -> None:
    old = {(p.kind, p.subject_id, p.missing) for p in before.pending}
    new = {(p.kind, p.subject_id, p.missing) for p in after.pending}
    for kind, subject_id, missing in sorted(new - old):
        changes.append(Change(ChangeKind.PENDING_APPEARED, "pending", subject_id, after=kind, related=missing))
    for kind, subject_id, missing in sorted(old - new):
        changes.append(Change(ChangeKind.PENDING_CLEARED, "pending", subject_id, before=kind, related=missing))


def _dereference_changes(before: ThemeResolution, after: ThemeResolution, changes: List[Change]) -> None:
    old = {d.ref_id: d.status for d in before.dereference}
    new = {d.ref_id: d.status for d in after.dereference}
    for ref_id in sorted(set(old) & set(new)):
        if old[ref_id] is not new[ref_id]:
            changes.append(Change(ChangeKind.DEREFERENCE_CHANGED, "dereference", ref_id, before=old[ref_id].value,
                                  after=new[ref_id].value, detail="upstream dereference only; canonical evidence unchanged"))


# ---------------------------------------------------------------- helpers

def _observation_id(resolution: ThemeResolution) -> str:
    return resolution.observation.observation_id if resolution.observation is not None else ""


def _iso(value: datetime) -> str:
    return value.isoformat()


def _sort_key(change: Change) -> Tuple[int, int, str, str, str, Tuple[str, ...]]:
    facet = change.facet.split(":", 1)[0]
    return (FACET_ORDER.index(facet), _KIND_ORDER[change.kind], change.subject_id, change.before, change.after,
            change.related)


__all__ = ["compare_resolutions", "detect_changes", "SEMANTIC_FIELDS", "FAILURE_STATUSES", "CLEARED_NOTE"]
