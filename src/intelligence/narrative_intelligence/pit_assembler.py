"""P7-A2 — point-in-time 入力の組み立て（認可された一方向の読み取り adapter）。

Phase 7 で Phase 6 を import してよい唯一の module。凍結された Phase 6 の read-only API だけを使い、caller が明示した
型・Theme root・cutoff について `NarrativeInputSnapshot` を作る。Narrative（claim）は作らない。

読み方（どれも Phase 6 の authoritative な入口。JSONL を自前で読まない）:

- Theme: Foundation `ThemeStore.open(read_only=True)`（5 authority を検証してから載せる。integrity-before-PIT）→
  `ThemeHistory.from_store` → root ごとに `resolve`（PIT）。1 回の読みをすべての root と cutoff に使う。
- lifecycle: B2 `derive_lifecycle`（caller の明示の freshness policy。cutoff までの governance event だけを渡す）。
- 変化: B1 `compare_resolutions`（caller が比較 cutoff を渡したときだけ。既定の期間は無い）。
- relation: B5B `resolve_relations_at_data_root`（THEME_SET だけ。要求集合の root だけを端点として知る lookup）。

読まないもの: B3 / B5C の提案、B4 の discovery、B6 の finding / review、B7 の生成物、P4 / P5、Production DNA、knowledge。
書き込み・cache・一時 file・現在時刻・乱数・network は無い。解決できない要求 root は黙って落とさず fail closed。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..theme_intelligence.change import compare_resolutions
from ..theme_intelligence.lifecycle import derive_lifecycle
from ..theme_intelligence.lifecycle_model import (GovernanceLifecycleState, LifecyclePolicy, LifecycleViewStatus,
                                                  ThemeLifecycleError)
from ..theme_intelligence.model import ChangeSetStatus
from ..theme_intelligence.relation_resolution import EdgeState, RelationResolutionStatus, endpoint_lookup_from_roots
from ..theme_intelligence.relation_store import resolve_relations_at_data_root
from ..themes.resolver import ResolutionStatus, ThemeHistory, resolve
from ..themes.store import ThemeInvalidHistory, ThemeStore, ThemeStoreCorrupt, ThemeStoreError
from .input_model import (READER_CHANGE_MODEL, READER_LIFECYCLE_MODEL, READER_LIFECYCLE_POLICY,
                          READER_RELATION_RESOLVER, READER_RESOLVER, EvidenceConditionFlag, EvidenceSource,
                          NarrativeInputError, NarrativeInputRequest, NarrativeInputSnapshot, SOURCE_CAPABILITY_BY_KIND,
                          ThemeInput, provenance_digest)
from .synthesis_model import (EvidenceAttachmentRef, EvidenceItemRef, EvidenceKind, InvalidationConditionRef,
                              MechanismComponentRef, NarrativeKind, NarrativeModelError, RelationAssertionRef,
                              ThemeChangeRef, ThemeObservationRef)

PIT_ASSEMBLER_VERSION = "narrative_pit_assembler:0.1.0"
#: 要求 root ごとに返す失敗（他の root の組み立ては続けて全部を報告する）
ROOT_FAILURE_CODES = ("ROOT_NOT_FOUND", "ROOT_NOT_RESOLVED", "ROOT_NOT_ACCEPTED_AT_CUTOFF", "REF_NOT_PROJECTABLE",
                      "CHANGE_NOT_AVAILABLE")


def _fail(code: str, detail: str = "", *, root_id: str = "") -> None:
    raise NarrativeInputError(code, detail, root_id=root_id)


def _code(exc: Exception) -> str:
    """失敗の code だけ（本文・path を運ばない）。A1 の検査の失敗は A1 の code、それ以外は型名。"""
    return exc.code if isinstance(exc, (NarrativeModelError, NarrativeInputError)) else type(exc).__name__


def _version(value: str, expected_name: str) -> Tuple[str, str]:
    """Phase 6 の `name:version` を (name, version) にする。想定外の reader は fail closed。"""
    name, _, version = value.partition(":")
    if name != expected_name or not version:
        _fail("READER_VERSION_UNSUPPORTED", expected_name)
    return name, version


# ---------------------------------------------------------------- Theme authority（1 回だけ検証して読む）

def _read_history(data_root: Any) -> ThemeHistory:
    try:
        store = ThemeStore.open(data_root, read_only=True)
        return ThemeHistory.from_store(store)
    except ThemeStoreCorrupt as exc:
        raise NarrativeInputError("AUTHORITY_CORRUPTION", exc.code) from None
    except ThemeInvalidHistory as exc:
        raise NarrativeInputError("AUTHORITY_INVALID_HISTORY", exc.code) from None
    except ThemeStoreError as exc:
        raise NarrativeInputError("AUTHORITY_UNAVAILABLE", exc.code) from None
    except Exception as exc:                                             # 読めない authority を空とみなさない
        raise NarrativeInputError("AUTHORITY_UNAVAILABLE", _code(exc)) from None


def _resolve(history: ThemeHistory, root_id: str, cutoff) -> Any:
    try:
        resolution = resolve(history, root_id, cutoff)
    except Exception as exc:                                             # 例: history の id 重複。推測しない
        raise NarrativeInputError("AUTHORITY_INVALID_HISTORY", _code(exc)) from None
    if resolution.status is ResolutionStatus.INVALID_HISTORY:
        raise NarrativeInputError("AUTHORITY_INVALID_HISTORY", ",".join(d.kind for d in resolution.diagnostics)[:120])
    if resolution.status is ResolutionStatus.STORE_CORRUPTION:
        raise NarrativeInputError("AUTHORITY_CORRUPTION", "theme")
    return resolution


def _eligible(resolution: Any, root_id: str, events: Sequence[Any], policy: LifecyclePolicy) -> Any:
    """cutoff で ACCEPTED の reviewed Theme だけ。それ以外は root ごとの失敗 code。"""
    if resolution.status is ResolutionStatus.NO_STATE:
        _fail("ROOT_NOT_FOUND" if resolution.root is None else "ROOT_NOT_RESOLVED", resolution.status.value,
              root_id=root_id)
    if resolution.status is not ResolutionStatus.RESOLVED or resolution.observation is None:
        _fail("ROOT_NOT_RESOLVED", resolution.status.value, root_id=root_id)
    try:
        view = derive_lifecycle(resolution, policy=policy, governance_events=events)
    except ThemeLifecycleError as exc:
        raise NarrativeInputError("ROOT_NOT_RESOLVED", exc.code, root_id=root_id) from None
    state = view.governance.state
    if state in (GovernanceLifecycleState.UNRESOLVED, GovernanceLifecycleState.NOT_AVAILABLE):
        _fail("ROOT_NOT_RESOLVED", state.value, root_id=root_id)
    if state is not GovernanceLifecycleState.ACCEPTED:
        _fail("ROOT_NOT_ACCEPTED_AT_CUTOFF", state.value, root_id=root_id)
    if view.status is not LifecycleViewStatus.AVAILABLE:
        _fail("ROOT_NOT_RESOLVED", view.status.value, root_id=root_id)
    return view


def _project(resolution: Any, view: Any, changes: Optional[Tuple[ThemeChangeRef, ...]]
             ) -> Tuple[ThemeInput, List[EvidenceItemRef]]:
    root_id = resolution.root_id
    obs = resolution.observation
    anchor = {"root_id": root_id, "observation_id": obs.observation_id}
    mechanism = obs.mechanism
    try:
        observation = ThemeObservationRef(**anchor, governance_position=view.governance.state.value,
                                          mechanism_certainty=obs.certainty_class.value)
        components = tuple(MechanismComponentRef(**anchor, component_type=c.component_type.value,
                                                 component_key=c.component_key)
                           for c in (*mechanism.drivers, *mechanism.channels, *mechanism.domains,
                                     *mechanism.consequences))
        conditions = tuple(InvalidationConditionRef(**anchor, condition_key=c.condition_key)
                           for c in obs.invalidation_conditions)
        visible = resolution.evidence.visible                        # cutoff で付与済み・evidence_time が cutoff 以前
        attachments = tuple(EvidenceAttachmentRef(**anchor, ref_id=a.ref_id, evidence_kind=a.evidence_kind.value,
                                                  consequence_key=a.consequence_ref, role=a.role.value,
                                                  role_provenance=a.role_provenance.value, attached_at=a.attached_at,
                                                  invalidation_condition_key=a.invalidation_condition_ref)
                            for a in visible)
        items = [EvidenceItemRef(ref_id=a.ref_id, evidence_kind=a.evidence_kind.value, evidence_time=a.evidence_time,
                                 time_quality=a.evidence_time_quality.value) for a in visible]
        flags = tuple(EvidenceConditionFlag(f.value) for f in view.evidence.flags)
    except (NarrativeModelError, ValueError) as exc:
        raise NarrativeInputError("REF_NOT_PROJECTABLE", _code(exc),
                                  root_id=root_id) from None
    governance = resolution.governance
    digest = provenance_digest({
        "resolver_version": resolution.resolver_version, "root_id": root_id, "observation_id": obs.observation_id,
        "governance_chain": list(governance.chain), "effective_event_id": governance.effective_event_id,
        "reversed_event_ids": list(governance.reversed_event_ids), "state_event_id": view.governance.state_event_id,
        "lineage": sorted([l.kind.value, l.event_id, list(l.related_roots)] for l in resolution.lineage),
        "visible_attachment_keys": sorted(a.attachment_key for a in visible)})
    theme = ThemeInput(observation=observation, components=components, invalidation_conditions=conditions,
                       attachments=attachments, evidence_condition_flags=flags, changes=changes,
                       provenance_digest=digest)
    return theme, items


def _changes(history: ThemeHistory, after: Any, request: NarrativeInputRequest
             ) -> Tuple[Optional[Tuple[ThemeChangeRef, ...]], Optional[str]]:
    """比較 cutoff が明示されたときだけ B1 の変化を投影する（kind・facet・subject の id。本文は写さない）。"""
    if request.comparison_cutoff is None:
        return None, None
    before = _resolve(history, after.root_id, request.comparison_cutoff)
    try:
        change_set = compare_resolutions(before, after)
    except Exception as exc:
        raise NarrativeInputError("CHANGE_NOT_AVAILABLE", _code(exc), root_id=after.root_id) from None
    if change_set.status is not ChangeSetStatus.COMPUTED:
        _fail("CHANGE_NOT_AVAILABLE", change_set.status.value, root_id=after.root_id)
    try:
        refs = {ThemeChangeRef(root_id=after.root_id, from_cutoff=request.comparison_cutoff, to_cutoff=request.cutoff,
                               change_kind=c.kind.value, facet=c.facet, subject_id=c.subject_id)
                for c in change_set.changes}
    except (NarrativeModelError, ValueError) as exc:
        raise NarrativeInputError("REF_NOT_PROJECTABLE", _code(exc),
                                  root_id=after.root_id) from None
    return tuple(refs), change_set.change_model_version


# ---------------------------------------------------------------- relation authority（THEME_SET だけ）

def _relations(data_root: Any, request: NarrativeInputRequest, created_at_by_root: Mapping[str, Any]
               ) -> Tuple[Tuple[RelationAssertionRef, ...], str, str]:
    """要求集合の内側で cutoff に ACTIVE な B5B の直接の辺だけ。推移・推測・提案・共同発見の辺は無い。"""
    lookup = endpoint_lookup_from_roots(dict(created_at_by_root))     # 集合の外の端点は知らない（その辺は除外される）
    try:
        resolution = resolve_relations_at_data_root(data_root, cutoff=request.cutoff, endpoint_lookup=lookup)
    except Exception as exc:
        raise NarrativeInputError("RELATION_AUTHORITY_UNAVAILABLE", _code(exc)) from None
    if resolution.status is RelationResolutionStatus.STORE_CORRUPTION:
        codes = {d.code for d in resolution.diagnostics}
        _fail("RELATION_AUTHORITY_UNAVAILABLE" if codes == {"AUTHORITY_MISSING"} else "AUTHORITY_CORRUPTION",
              "relation")
    if resolution.status is RelationResolutionStatus.INVALID_HISTORY:
        _fail("AUTHORITY_INVALID_HISTORY", "relation")
    scope = set(request.root_ids)
    for edge in resolution.unresolved:                                 # 集合に触れる未解決の辺は推測しない
        _fail("RELATION_NOT_RESOLVED", edge.status.value)
    if resolution.status not in (RelationResolutionStatus.RESOLVED, RelationResolutionStatus.NO_STATE):
        _fail("RELATION_NOT_RESOLVED", resolution.status.value)
    edges = [e for e in resolution.edges if e.edge_state is EdgeState.ACTIVE
             and e.source_theme_root_id in scope and e.target_theme_root_id in scope]
    try:
        refs = tuple(RelationAssertionRef(relation_assertion_id=e.assertion.relation_assertion_id,
                                          source_root_id=e.source_theme_root_id, target_root_id=e.target_theme_root_id,
                                          relation_type=e.relation_type.value, assertion_class=e.assertion_class.value)
                     for e in edges)
    except (NarrativeModelError, ValueError) as exc:
        raise NarrativeInputError("REF_NOT_PROJECTABLE", _code(exc)) from None
    digest = provenance_digest({"relation_resolver_version": resolution.resolver_version, "edges": sorted(
        [e.assertion.relation_assertion_id, list(e.assertion_chain), list(e.governance_chain)] for e in edges)})
    return refs, digest, resolution.resolver_version


# ---------------------------------------------------------------- public API

def assemble_input_snapshot(*, data_root: Any, request: NarrativeInputRequest) -> NarrativeInputSnapshot:
    """caller の明示の要求から cutoff 時点の入力 snapshot を作る。Phase 6 の authority を変えない（読むだけ）。"""
    if not isinstance(request, NarrativeInputRequest):
        _fail("INVALID_REQUEST", "request must be a NarrativeInputRequest")
    if data_root is None or (isinstance(data_root, str) and data_root.strip() == ""):
        _fail("INVALID_DATA_ROOT", "an explicit data_root is required")
    history = _read_history(data_root)
    policy = LifecyclePolicy(stale_after_days=request.stale_after_days)
    events = tuple(e for e in history.events if e.recorded_at <= request.cutoff)
    themes: List[ThemeInput] = []
    items: Dict[str, EvidenceItemRef] = {}
    created: Dict[str, Any] = {}
    failures: List[Tuple[str, str]] = []
    versions: Dict[str, Tuple[str, str]] = {}
    for root_id in request.root_ids:                                   # 要求された root だけ（列挙しない）
        try:
            resolution = _resolve(history, root_id, request.cutoff)
            view = _eligible(resolution, root_id, events, policy)
            changes, change_version = _changes(history, resolution, request)
            theme, theme_items = _project(resolution, view, changes)
        except NarrativeInputError as exc:
            if exc.code not in ROOT_FAILURE_CODES:
                raise
            failures.append((root_id, exc.code))
            continue
        for item in theme_items:
            if items.setdefault(item.ref_id, item) != item:
                _fail("EVIDENCE_ITEM_INCONSISTENT", "one evidence item carries two different descriptions")
        themes.append(theme)
        created[root_id] = resolution.root.created_at
        versions[READER_RESOLVER] = _version(resolution.resolver_version, READER_RESOLVER)
        versions[READER_LIFECYCLE_MODEL] = _version(view.lifecycle_model_version, READER_LIFECYCLE_MODEL)
        versions[READER_LIFECYCLE_POLICY] = _version(view.policy.schema_version, READER_LIFECYCLE_POLICY)
        if change_version is not None:
            versions[READER_CHANGE_MODEL] = _version(change_version, READER_CHANGE_MODEL)
    if failures:
        raise NarrativeInputError(failures[0][1], "requested roots are not eligible at the cutoff",
                                  root_id=failures[0][0], failures=tuple(failures))
    relations, relation_digest = None, None
    if request.kind is NarrativeKind.THEME_SET:
        relations, relation_digest, relation_version = _relations(data_root, request, created)
        versions[READER_RELATION_RESOLVER] = _version(relation_version, READER_RELATION_RESOLVER)
    sources = tuple(EvidenceSource(item=item, capability=SOURCE_CAPABILITY_BY_KIND[EvidenceKind(item.evidence_kind)])
                    for item in items.values())
    try:
        return NarrativeInputSnapshot(kind=request.kind, root_ids=request.root_ids, cutoff=request.cutoff,
                                      comparison_cutoff=request.comparison_cutoff, themes=tuple(themes),
                                      evidence_sources=sources, relations=relations,
                                      relation_provenance_digest=relation_digest,
                                      reader_versions=tuple(versions.values()),
                                      stale_after_days=request.stale_after_days)
    except NarrativeModelError as exc:
        raise NarrativeInputError("REF_NOT_PROJECTABLE", exc.code) from None


__all__ = ["PIT_ASSEMBLER_VERSION", "ROOT_FAILURE_CODES", "assemble_input_snapshot"]
