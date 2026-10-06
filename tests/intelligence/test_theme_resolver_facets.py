"""P6-A4c — governance / metadata / mapping facet の独立解決、EVENT_REVERSED、merge / split / successor の前後、
carried evidence lineage、upstream dereference 境界。"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.themes import operations as O
from src.intelligence.themes.model import GovernanceEventType, MetadataField, ThemeModelError
from src.intelligence.themes.resolver import (
    DereferenceStatus, GovernanceStatus, LineageKind, MappingStatus, MetadataStatus, ResolutionStatus, ThemeHistory,
    resolve,
)
from src.intelligence.themes.store import ThemeStore
from tests.intelligence.test_theme_model import (
    FACT_A, FACT_B, ROOT_A, ROOT_B, ROOT_C, T0, event, mapping, metadata, observation, root_record,
)
from tests.intelligence.test_theme_store import seeded
from tests.intelligence.test_theme_store_operations import (
    KEY_A, KEY_B, ROOT_D, ROOT_E, merge_plan, split_plan, successor_plan, two_roots,
)

H1 = timedelta(hours=1)
D1 = timedelta(days=1)


def history(store: ThemeStore) -> ThemeHistory:
    return ThemeHistory.from_store(store)


def governance_chain(store: ThemeStore, obs):
    """A: CANDIDATE_ACCEPTED（T0+1d）→ RETIRED（T0+2d）→ EVENT_REVERSED(RETIRED)（T0+3d）。"""
    accepted = event(related_observations=(obs.observation_id,), recorded_at=T0 + D1)
    store.append_governance(accepted)
    retired = event(event_type=GovernanceEventType.RETIRED, reason="retire",
                    previous_event_ids=((ROOT_A, accepted.event_id),), recorded_at=T0 + 2 * D1)
    store.append_governance(retired)
    reversal = event(event_type=GovernanceEventType.EVENT_REVERSED, reverses_event_id=retired.event_id, reason="oops",
                     previous_event_ids=((ROOT_A, retired.event_id),), recorded_at=T0 + 3 * D1)
    store.append_governance(reversal)
    return accepted, retired, reversal


# ---------------------------------------------------------------- governance

def test_no_governance_is_distinct_from_no_state(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    at = resolve(history(store), ROOT_A, T0 + H1)
    assert at.status is ResolutionStatus.RESOLVED and at.governance.status is GovernanceStatus.NO_GOVERNANCE
    assert at.governance.chain == () and at.governance.effective_event_type is None


def test_governance_unique_chain_and_cutoffs(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    accepted, retired, reversal = governance_chain(store, obs)
    h = history(store)
    g1 = resolve(h, ROOT_A, T0 + D1).governance
    assert g1.status is GovernanceStatus.RESOLVED and g1.chain == (accepted.event_id,)
    assert g1.effective_event_type is GovernanceEventType.CANDIDATE_ACCEPTED
    g2 = resolve(h, ROOT_A, T0 + 2 * D1 + H1).governance
    assert g2.chain == (accepted.event_id, retired.event_id) and g2.terminal_event_id == retired.event_id
    assert g2.effective_event_type is GovernanceEventType.RETIRED and g2.reversed_event_ids == ()


def test_event_reversed_restores_prior_state_without_deleting_history(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    accepted, retired, reversal = governance_chain(store, obs)
    h = history(store)
    g = resolve(h, ROOT_A, T0 + 3 * D1 + H1).governance
    assert g.status is GovernanceStatus.RESOLVED
    assert g.chain == (accepted.event_id, retired.event_id, reversal.event_id)   # 履歴は残る
    assert g.terminal_event_id == reversal.event_id
    assert g.effective_event_id == accepted.event_id and g.effective_event_type is GovernanceEventType.CANDIDATE_ACCEPTED
    assert g.reversed_event_ids == (retired.event_id,)
    # 取消の取消: RETIRED が再び効力を持つ
    second = event(event_type=GovernanceEventType.EVENT_REVERSED, reverses_event_id=reversal.event_id, reason="undo",
                   previous_event_ids=((ROOT_A, reversal.event_id),), recorded_at=T0 + 4 * D1)
    store.append_governance(second)
    g2 = resolve(history(store), ROOT_A, T0 + 5 * D1).governance
    assert g2.effective_event_type is GovernanceEventType.RETIRED and g2.reversed_event_ids == (reversal.event_id,)
    assert len(g2.chain) == 4
    # reversal 前の T では RETIRED のまま（latest-wins ではなく cutoff）
    assert resolve(history(store), ROOT_A, T0 + 2 * D1 + H1).governance.effective_event_type is GovernanceEventType.RETIRED


def test_governance_fork_is_isolated_to_the_governance_facet(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    accepted = event(related_observations=(obs.observation_id,), recorded_at=T0 + D1)
    store.append_governance(accepted)
    store.append_metadata(metadata(recorded_at=T0 + D1))
    base = history(store)
    left = event(event_type=GovernanceEventType.RETIRED, reason="retire a",
                 previous_event_ids=((ROOT_A, accepted.event_id),), recorded_at=T0 + 2 * D1)
    right = event(event_type=GovernanceEventType.RETIRED, reason="retire b",
                  previous_event_ids=((ROOT_A, accepted.event_id),), recorded_at=T0 + 3 * D1)
    forked = ThemeHistory(roots=base.roots, observations=base.observations, events=base.events + (left, right),
                          metadata=base.metadata)
    at = resolve(forked, ROOT_A, T0 + 4 * D1)
    assert at.status is ResolutionStatus.RESOLVED and at.observation == obs        # semantic は無傷
    assert at.governance.status is GovernanceStatus.UNRESOLVED
    assert [d.kind for d in at.governance.diagnostics] == ["FORK"] and set(at.governance.diagnostics[0].related) == {
        left.event_id, right.event_id}
    assert at.metadata[0].status is MetadataStatus.RESOLVED                        # LABEL も無傷
    before_fork = resolve(forked, ROOT_A, T0 + 2 * D1 + H1).governance
    assert before_fork.status is GovernanceStatus.RESOLVED and before_fork.effective_event_type is GovernanceEventType.RETIRED


# ---------------------------------------------------------------- merge / split / successor

def test_merge_before_and_after(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    O.execute_declaration(store, plan)
    h = history(store)
    pre_a = resolve(h, ROOT_A, T0 + D1)
    assert pre_a.status is ResolutionStatus.RESOLVED and pre_a.governance.status is GovernanceStatus.NO_GOVERNANCE
    assert pre_a.lineage == () and resolve(h, ROOT_C, T0 + D1).status is ResolutionStatus.NO_STATE
    post_a = resolve(h, ROOT_A, T0 + 4 * D1)
    assert post_a.observation == pre_a.observation                                  # 旧 root の semantic は不変
    assert post_a.governance.effective_event_type is GovernanceEventType.MERGE
    assert [(l.kind, l.related_roots) for l in post_a.lineage] == [(LineageKind.MERGED_INTO, (ROOT_C,))]
    post_b = resolve(h, ROOT_B, T0 + 4 * D1)
    assert post_b.lineage[0].kind is LineageKind.MERGED_INTO and post_b.observation == obs_b
    post_c = resolve(h, ROOT_C, T0 + 4 * D1)
    assert post_c.status is ResolutionStatus.RESOLVED and post_c.observation == plan.results[0][1]
    assert [(l.kind, l.related_roots) for l in post_c.lineage] == [(LineageKind.MERGE_OF, (ROOT_A, ROOT_B))]
    assert post_c.governance.effective_event_type is GovernanceEventType.MERGE
    assert post_c.governance.chain == (plan.event.event_id,)


def test_split_before_and_after(tmp_path: Path) -> None:
    store, root, obs_a = seeded(tmp_path)
    plan = split_plan(store, obs_a)
    O.execute_declaration(store, plan)
    h = history(store)
    assert resolve(h, ROOT_A, T0 + D1).lineage == ()
    assert resolve(h, ROOT_D, T0 + D1).status is ResolutionStatus.NO_STATE
    post = resolve(h, ROOT_A, T0 + 4 * D1)
    assert post.observation == obs_a and post.governance.effective_event_type is GovernanceEventType.SPLIT
    assert [(l.kind, set(l.related_roots)) for l in post.lineage] == [(LineageKind.SPLIT_INTO, {ROOT_D, ROOT_E})]
    d = resolve(h, ROOT_D, T0 + 4 * D1)
    e = resolve(h, ROOT_E, T0 + 4 * D1)
    assert d.lineage[0].kind is LineageKind.SPLIT_FROM and e.lineage[0].kind is LineageKind.SPLIT_FROM
    assert [a.attachment_key for a in d.evidence.visible] == [KEY_A]
    assert [a.attachment_key for a in e.evidence.visible] == [KEY_B]
    assert [c.attachment_key for c in d.carried] == [KEY_A] and d.carried[0].source_observation_id == obs_a.observation_id


def test_successor_before_and_after(tmp_path: Path) -> None:
    store, root, obs_a = seeded(tmp_path)
    plan = successor_plan(store, obs_a)
    O.execute_declaration(store, plan)
    h = history(store)
    assert resolve(h, ROOT_A, T0 + D1).lineage == ()
    old = resolve(h, ROOT_A, T0 + 4 * D1)
    assert old.status is ResolutionStatus.RESOLVED and old.observation == obs_a         # 旧 root は書き換えられない
    assert old.governance.effective_event_type is GovernanceEventType.SUPERSEDED_BY_ROOT
    assert [(l.kind, l.related_roots) for l in old.lineage] == [(LineageKind.SUPERSEDED_BY, (ROOT_D,))]
    new = resolve(h, ROOT_D, T0 + 4 * D1)
    assert new.lineage[0].kind is LineageKind.SUCCESSOR_OF and new.lineage[0].related_roots == (ROOT_A,)
    assert new.observation == plan.results[0][1]


def test_carried_evidence_lineage_reconstruction(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    O.execute_declaration(store, plan)
    at = resolve(history(store), ROOT_C, T0 + 4 * D1)
    assert [(c.attachment_key, c.source_observation_id, c.source_root_id, c.origin_event_id) for c in at.carried] == [
        (KEY_A, obs_a.observation_id, ROOT_A, plan.event.event_id)]
    carried = at.evidence.visible[0]
    assert carried == obs_a.attachment(KEY_A)
    assert carried.attached_at < at.root.created_at                                       # 元 attached_at を保持
    assert at.derived.qualification.counted_attachment_keys == (KEY_A,)
    assert "carried_from" not in carried.__dataclass_fields__                            # schema は変えない


# ---------------------------------------------------------------- metadata facet

def test_metadata_per_field_resolution(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    first = metadata(recorded_at=T0 + D1)
    store.append_metadata(first)
    second = metadata(value=("Second label",), previous_metadata_id=first.metadata_id, recorded_at=T0 + 3 * D1)
    store.append_metadata(second)
    taxonomy = metadata(field=MetadataField.TAXONOMY, value=("t2", "t1"), recorded_at=T0 + 2 * D1)
    store.append_metadata(taxonomy)
    h = history(store)

    def facet(at, field_):
        return next(m for m in at.metadata if m.field is field_)

    early = resolve(h, ROOT_A, T0 + H1)
    assert all(m.status is MetadataStatus.NO_METADATA for m in early.metadata)
    mid = resolve(h, ROOT_A, T0 + 2 * D1 + H1)
    assert facet(mid, MetadataField.LABEL).value == first.value and facet(mid, MetadataField.LABEL).record_id == first.metadata_id
    assert facet(mid, MetadataField.TAXONOMY).value == ("t1", "t2")
    assert facet(mid, MetadataField.DESCRIPTION).status is MetadataStatus.NO_METADATA
    late = resolve(h, ROOT_A, T0 + 4 * D1)
    assert facet(late, MetadataField.LABEL).value == ("Second label",)
    assert late.observation == obs and late.observation.observation_id == mid.observation.observation_id   # metadata は semantic を変えない


def test_label_fork_does_not_break_semantic_state(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    first = metadata(recorded_at=T0 + D1)
    store.append_metadata(first)
    base = history(store)
    left = metadata(value=("Left",), previous_metadata_id=first.metadata_id, recorded_at=T0 + 2 * D1)
    right = metadata(value=("Right",), previous_metadata_id=first.metadata_id, recorded_at=T0 + 3 * D1)
    taxonomy = metadata(field=MetadataField.TAXONOMY, value=("t1",), recorded_at=T0 + D1)
    forked = ThemeHistory(roots=base.roots, observations=base.observations, metadata=base.metadata + (left, right, taxonomy))
    at = resolve(forked, ROOT_A, T0 + 4 * D1)
    assert at.status is ResolutionStatus.RESOLVED and at.observation == obs
    label = next(m for m in at.metadata if m.field is MetadataField.LABEL)
    assert label.status is MetadataStatus.UNRESOLVED and label.diagnostics[0].kind == "FORK" and label.value == ()
    assert next(m for m in at.metadata if m.field is MetadataField.TAXONOMY).status is MetadataStatus.RESOLVED
    assert at.governance.status is GovernanceStatus.NO_GOVERNANCE and at.mapping.status is MappingStatus.NO_MAPPING
    assert next(m for m in resolve(forked, ROOT_A, T0 + D1 + H1).metadata if m.field is MetadataField.LABEL).value == first.value


# ---------------------------------------------------------------- mapping facet

def test_mapping_supersession_and_valid_from(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    first = mapping(recorded_at=T0 + D1, valid_from=T0 + D1)
    store.append_mapping(first)
    second = mapping(series_ref="fx:USDJPY.close.closing.tokyo", supersedes_mapping_id=first.mapping_id,
                     recorded_at=T0 + 3 * D1, valid_from=T0 + 3 * D1)
    store.append_mapping(second)
    future = mapping(series_ref="rates:UST10Y_par.close", recorded_at=T0 + D1, valid_from=T0 + 10 * D1)   # 先日付で有効
    store.append_mapping(future)
    h = history(store)
    assert resolve(h, ROOT_A, T0 + H1).mapping.status is MappingStatus.NO_MAPPING
    mid = resolve(h, ROOT_A, T0 + 2 * D1).mapping
    assert mid.status is MappingStatus.RESOLVED and mid.terminal_mapping_ids == (first.mapping_id,)
    late = resolve(h, ROOT_A, T0 + 4 * D1).mapping
    assert late.terminal_mapping_ids == (second.mapping_id,) and late.mappings[0].series_ref == second.series_ref
    effective = resolve(h, ROOT_A, T0 + 11 * D1).mapping
    assert set(effective.terminal_mapping_ids) == {second.mapping_id, future.mapping_id}   # 並行 chain は正当
    assert resolve(h, ROOT_A, T0 + 4 * D1).observation == obs


def test_mapping_ambiguity_is_isolated(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    first = mapping(recorded_at=T0 + D1, valid_from=T0 + D1)
    store.append_mapping(first)
    base = history(store)
    left = mapping(series_ref="a.series", supersedes_mapping_id=first.mapping_id, recorded_at=T0 + 2 * D1,
                   valid_from=T0 + 2 * D1)
    right = mapping(series_ref="b.series", supersedes_mapping_id=first.mapping_id, recorded_at=T0 + 3 * D1,
                    valid_from=T0 + 3 * D1)
    forked = ThemeHistory(roots=base.roots, observations=base.observations, mappings=base.mappings + (left, right))
    at = resolve(forked, ROOT_A, T0 + 4 * D1)
    assert at.status is ResolutionStatus.RESOLVED and at.observation == obs
    assert at.mapping.status is MappingStatus.UNRESOLVED and at.mapping.diagnostics[0].kind == "FORK"
    assert resolve(forked, ROOT_A, T0 + 2 * D1 + H1).mapping.terminal_mapping_ids == (left.mapping_id,)


# ---------------------------------------------------------------- upstream dereference boundary

def test_upstream_dereference_is_caller_supplied_and_separate(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    h = history(store)
    default = resolve(h, ROOT_A, T0 + D1)
    assert [(d.ref_id, d.status) for d in default.dereference] == [(FACT_A, DereferenceStatus.NOT_CHECKED),
                                                                    (FACT_B, DereferenceStatus.NOT_CHECKED)]
    calls = []

    def lookup(att):
        calls.append(att.ref_id)
        return DereferenceStatus.SUPERSEDED if att.ref_id == FACT_A else DereferenceStatus.AVAILABLE

    checked = resolve(h, ROOT_A, T0 + D1, dereference=lookup)
    assert [(d.ref_id, d.status) for d in checked.dereference] == [(FACT_A, DereferenceStatus.SUPERSEDED),
                                                                    (FACT_B, DereferenceStatus.AVAILABLE)]
    assert checked.observation == default.observation and checked.evidence == default.evidence   # 再構成は不変
    assert checked.derived == default.derived and sorted(calls) == [FACT_A, FACT_B]
    with pytest.raises(ThemeModelError, match="^INVALID_VOCABULARY"):
        resolve(h, ROOT_A, T0 + D1, dereference=lambda att: "superseded")  # type: ignore[arg-type,return-value]


def test_facet_statuses_do_not_propagate_to_each_other(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    O.execute_declaration(store, plan)
    base = history(store)
    first = metadata(root_id=ROOT_C, recorded_at=T0 + 4 * D1)
    left = metadata(root_id=ROOT_C, value=("L",), previous_metadata_id=first.metadata_id, recorded_at=T0 + 5 * D1)
    right = metadata(root_id=ROOT_C, value=("R",), previous_metadata_id=first.metadata_id, recorded_at=T0 + 5 * D1)
    h = ThemeHistory(roots=base.roots, observations=base.observations, events=base.events,
                     metadata=(first, left, right), mappings=base.mappings)
    at = resolve(h, ROOT_C, T0 + 6 * D1)
    assert at.status is ResolutionStatus.RESOLVED
    assert at.governance.status is GovernanceStatus.RESOLVED
    assert next(m for m in at.metadata if m.field is MetadataField.LABEL).status is MetadataStatus.UNRESOLVED
    assert at.mapping.status is MappingStatus.NO_MAPPING and at.carried and at.lineage
