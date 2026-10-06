"""P6-B1 — Theme change detection（`theme_intelligence.change`）の契約 test（test matrix 1〜42）。

A4d の代表 world（theme_foundation_fixtures）と、その上に合成した ThemeHistory 変種を入力にする。書き込みは tmp_path のみ。
"""
from __future__ import annotations

import dataclasses
import random
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence import change as C
from src.intelligence.theme_intelligence.model import (
    CHANGE_MODEL_VERSION, CHANGE_SCHEMA_VERSION, Change, ChangeKind, ChangeSetStatus, EvidenceTimeRelation,
    ThemeChangeError, ThemeChangeSet,
)
from src.intelligence.themes.model import (
    DroppedAttachment, EvidenceKind, EvidenceRole, GovernanceEventType, MetadataField, OriginKind, ScopeDimension,
    ScopeToken, canonical_json,
)
from src.intelligence.themes.resolver import (
    DereferenceStatus, GovernanceStatus, ResolutionStatus, ThemeHistory, resolve, resolve_at_data_root,
)
from src.intelligence.themes.revision import attach_evidence, revise_observation
from src.intelligence.themes.store import ThemeStore
from tests.intelligence.test_theme_model import (
    FACT_A, FACT_B, ROOT_A, ROOT_B, ROOT_C, attachment, consequence, event, limitation, mapping, mechanism, metadata,
    origin, provenance,
)
from tests.intelligence.test_theme_foundation_remediation import IDENTITY_BREAKS, rebuilt
from tests.intelligence.theme_foundation_fixtures import (
    CHECKPOINTS, DOC_BOJ, DOC_MOF, KEY_A, KEY_BOJ, KEY_MOF, KEY_NEWS, NEWS_D, ROOT_KEYS, TIMES, World, authority_bytes,
    build_world, copy_world, day,
)

H1 = timedelta(hours=1)
FACT_A2 = "fact_" + "a" * 23 + "2"
FACT_X = "fact_" + "9" * 24
DOC_X = "doc_" + "7" * 24
ORDER = list(CHECKPOINTS)
K = ChangeKind


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    return build_world(tmp_path_factory.mktemp("change_world") / "data")


@pytest.fixture(scope="module")
def history(world: World) -> ThemeHistory:
    return ThemeHistory.from_store(ThemeStore.open(world.data_root, read_only=True))


def cs(history: ThemeHistory, root_key: str, a: str, b: str, **kw) -> ThemeChangeSet:
    return C.detect_changes(history, ROOT_KEYS[root_key], CHECKPOINTS[a], CHECKPOINTS[b], **kw)


def kinds(change_set: ThemeChangeSet) -> list:
    return [c.kind for c in change_set.changes]


def subjects(change_set: ThemeChangeSet, kind: ChangeKind) -> list:
    return [c.subject_id for c in change_set.changes if c.kind is kind]


def terminal(world: World, history: ThemeHistory):
    return next(o for o in history.observations if o.observation_id == world.ids["A.obs5"])


def extended(history: ThemeHistory, *observations, events=(), metadata=(), mappings=()) -> ThemeHistory:
    return ThemeHistory(history.roots, history.observations + tuple(observations), history.events + tuple(events),
                        history.metadata + tuple(metadata), history.mappings + tuple(mappings))


def shuffled(h: ThemeHistory, seed: int) -> ThemeHistory:
    rng = random.Random(seed)
    return ThemeHistory(*(tuple(rng.sample(list(part), len(part)))
                          for part in (h.roots, h.observations, h.events, h.metadata, h.mappings)))


# ---------------------------------------------------------------- 1〜3 identity / root

def test_01_same_resolution_gives_an_empty_change_set(world: World) -> None:
    res = world.resolve("A", "accepted")
    change_set = C.compare_resolutions(res, res)
    assert change_set.is_empty and change_set.changes == () and change_set.status is ChangeSetStatus.COMPUTED
    assert change_set.schema_version == CHANGE_SCHEMA_VERSION and change_set.change_model_version == CHANGE_MODEL_VERSION
    assert change_set.from_cutoff == change_set.to_cutoff == CHECKPOINTS["accepted"]
    assert change_set.from_status is change_set.to_status is ResolutionStatus.RESOLVED
    assert change_set.knowledge_axis.evidence == () and change_set.evidence_time_axis.evidence == ()


def test_02_before_root_to_root_only_is_root_appeared(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "before_root", "root_only")
    assert kinds(change_set) == [K.ROOT_APPEARED, K.PENDING_APPEARED]
    root_change = change_set.of_kind(K.ROOT_APPEARED)[0]
    assert root_change.subject_id == ROOT_A and root_change.detail == "CANDIDATE"
    assert change_set.of_kind(K.PENDING_APPEARED)[0].after == "PENDING_GENESIS"
    assert change_set.from_status is change_set.to_status is ResolutionStatus.NO_STATE


def test_03_root_only_to_genesis_is_became_observed(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "root_only", "genesis_visible")
    assert K.ROOT_BECAME_OBSERVED in kinds(change_set) and K.ROOT_APPEARED not in kinds(change_set)
    assert change_set.of_kind(K.PENDING_CLEARED)[0].before == "PENDING_GENESIS"
    assert K.EVIDENCE_ADDED not in kinds(change_set)                      # genesis は evidence 0 件
    both = cs(history, "A", "before_root", "genesis_visible")
    assert kinds(both)[:2] == [K.ROOT_APPEARED, K.ROOT_BECAME_OBSERVED]  # 1 window で両方
    assert both.knowledge_axis.observation_recorded_at == TIMES["T1_genesis"]


# ---------------------------------------------------------------- 4〜5 semantic

def test_04_semantic_revision_is_observation_revised(world: World, history: ThemeHistory) -> None:
    change_set = cs(history, "A", "accepted", "semantic_revision")
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.SEMANTIC_FIELD_CHANGED]
    revised = change_set.of_kind(K.OBSERVATION_REVISED)[0]
    assert revised.subject_id == world.ids["A.obs4"] and revised.related == (world.ids["A.obs3"],)
    assert subjects(change_set, K.SEMANTIC_FIELD_CHANGED) == ["limitations"]
    assert change_set.from_observation_id == world.ids["A.obs3"] and change_set.to_observation_id == world.ids["A.obs4"]
    assert not any(c.facet == "evidence" for c in change_set.changes)     # attachment は引き継がれ変化なし


def test_05_scope_and_consequence_changes_are_named_per_field(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    revised = revise_observation(obs, recorded_at=day(13), provenance=provenance(reason="scope + consequence"),
                                 scope=tuple(s for s in obs.scope if s.dimension is not ScopeDimension.REGION)
                                       + (ScopeToken(dimension=ScopeDimension.REGION, value="us"),),
                                 mechanism=mechanism(consequences=obs.mechanism.consequences
                                                     + (consequence(key="c2", target="fx:USDJPY.vol"),)))
    change_set = C.detect_changes(extended(history, revised), ROOT_A, day(12, 12), day(13, 12))
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.SEMANTIC_FIELD_CHANGED, K.SEMANTIC_FIELD_CHANGED]
    assert subjects(change_set, K.SEMANTIC_FIELD_CHANGED) == ["mechanism.consequences", "scope"]
    field = change_set.of_kind(K.SEMANTIC_FIELD_CHANGED)[1]
    assert field.before != field.after and '"us"' in field.after and '"us"' not in field.before
    assert not any(c.subject_id.startswith("mechanism.d") for c in change_set.changes)   # identity core は不変


# ---------------------------------------------------------------- 6〜10 evidence

def test_06_delayed_attachment_is_a_knowledge_change_dated_before_the_window(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "delayed_evidence_before_attachment", "delayed_evidence_after_attachment")
    assert subjects(change_set, K.EVIDENCE_ADDED) == [KEY_NEWS]
    learned = change_set.knowledge_axis.evidence
    assert [(e.attachment_key, e.attached_at, e.kind) for e in learned] == [(KEY_NEWS, TIMES["T10_delayed"], K.EVIDENCE_ADDED)]
    timing = change_set.evidence_time_axis
    assert [(t.attachment_key, t.evidence_date, t.relation) for t in timing.evidence] == [
        (KEY_NEWS, "2026-08-28", EvidenceTimeRelation.DATED_BEFORE_WINDOW)]
    assert timing.dated_before_window == 1 and timing.dated_within_window == 0 and timing.new_evidence_dates == ("2026-08-28",)
    assert cs(history, "A", "semantic_revision", "delayed_evidence_before_attachment").is_empty   # 知る前は何も変わらない


def test_07_evidence_add(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "genesis_visible", "first_evidence")
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.EVIDENCE_ADDED, K.NEW_SOURCE_ORIGIN, K.NEW_EVIDENCE_DATE]
    added = change_set.of_kind(K.EVIDENCE_ADDED)[0]
    assert added.subject_id == KEY_A and added.after == "SUPPORTS" and added.related == (FACT_A,)
    assert change_set.knowledge_axis.evidence[0].attached_at == TIMES["T2_evidence1"]
    assert change_set.evidence_time_axis.evidence[0].relation is EvidenceTimeRelation.DATED_BEFORE_WINDOW


def test_08_evidence_drop(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    dropped = revise_observation(obs, recorded_at=day(13), provenance=provenance(
        reason="withdrawn", dropped=(DroppedAttachment(ref_id=NEWS_D, reason="source retracted"),)),
        attachments=tuple(a for a in obs.attachments if a.ref_id != NEWS_D))
    change_set = C.detect_changes(extended(history, dropped), ROOT_A, day(12, 12), day(13, 12))
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.EVIDENCE_DROPPED, K.SOURCE_ORIGIN_LOST, K.EVIDENCE_DATE_LOST]
    drop = change_set.of_kind(K.EVIDENCE_DROPPED)[0]
    assert drop.subject_id == KEY_NEWS and drop.before == "SUPPORTS" and drop.detail == "source retracted"
    assert change_set.knowledge_axis.evidence == () and change_set.evidence_time_axis.evidence == ()


def test_09_deterministic_role_correction(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    corrected = tuple(dataclasses.replace(a, role=EvidenceRole.CONTRADICTS, role_provenance=a.role_provenance)
                      if a.attachment_key == KEY_A else a for a in obs.attachments)
    revised = revise_observation(obs, recorded_at=day(13), provenance=provenance(reason="role"), attachments=corrected)
    change_set = C.detect_changes(extended(history, revised), ROOT_A, day(12, 12), day(13, 12))
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.EVIDENCE_ROLE_CHANGED]                 # 同一 key
    role = change_set.of_kind(K.EVIDENCE_ROLE_CHANGED)[0]
    assert (role.subject_id, role.before, role.after) == (KEY_A, "SUPPORTS", "CONTRADICTS")
    assert change_set.knowledge_axis.evidence[0].kind is K.EVIDENCE_ROLE_CHANGED
    assert change_set.evidence_time_axis.evidence == ()                                           # 新しい evidence ではない
    # consequence_ref が変わる訂正: 同一 ref_id で 1:1 に対応づく → ROLE_CHANGED（ADDED / DROPPED にしない）
    widened = revise_observation(obs, recorded_at=day(13), provenance=provenance(reason="c2"),
                                 mechanism=mechanism(consequences=obs.mechanism.consequences
                                                     + (consequence(key="c2", target="fx:USDJPY.vol"),)))
    moved = tuple(dataclasses.replace(a, consequence_ref="c2", role=EvidenceRole.CONTRADICTS)
                  if a.attachment_key == KEY_A else a for a in widened.attachments)
    re_attributed = revise_observation(widened, recorded_at=day(13, 6), provenance=provenance(reason="move"),
                                       attachments=moved)
    change_set = C.detect_changes(extended(history, widened, re_attributed), ROOT_A, day(13, 3), day(13, 9))
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.EVIDENCE_ROLE_CHANGED]
    role = change_set.of_kind(K.EVIDENCE_ROLE_CHANGED)[0]
    assert role.subject_id == f"{FACT_A}#c2" and role.related == (KEY_A,) and role.detail == "consequence_ref changed"


def test_10_ambiguous_replacement_stays_added_and_dropped(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    widened = revise_observation(obs, recorded_at=day(13), provenance=provenance(reason="c2 c3"),
                                 mechanism=mechanism(consequences=obs.mechanism.consequences
                                                     + (consequence(key="c2", target="fx:USDJPY.vol"),
                                                        consequence(key="c3", target="fx:USDJPY.skew"))),
                                 attachments=obs.attachments + (attachment(FACT_A, cref="c2", attached=day(13)),))
    replaced = revise_observation(widened, recorded_at=day(13, 6), provenance=provenance(reason="ambiguous"),
                                  attachments=tuple(a for a in widened.attachments if a.ref_id != FACT_A)
                                              + (attachment(FACT_A, cref="c3", role=EvidenceRole.CONTRADICTS,
                                                            attached=day(13, 6)),))
    change_set = C.detect_changes(extended(history, widened, replaced), ROOT_A, day(13, 3), day(13, 9))
    assert K.EVIDENCE_ROLE_CHANGED not in kinds(change_set)
    assert subjects(change_set, K.EVIDENCE_ADDED) == [f"{FACT_A}#c3"]
    assert subjects(change_set, K.EVIDENCE_DROPPED) == [KEY_A, f"{FACT_A}#c2"]


def test_09b_upstream_revision_replacement_is_ref_revised(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    revised_ref = attachment(FACT_A2, attached=day(13), revision_of_at_attachment=FACT_A)
    swapped = revise_observation(obs, recorded_at=day(13), provenance=provenance(reason="upstream revision"),
                                 attachments=tuple(a for a in obs.attachments if a.ref_id != FACT_A) + (revised_ref,))
    change_set = C.detect_changes(extended(history, swapped), ROOT_A, day(12, 12), day(13, 12))
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.EVIDENCE_REF_REVISED]
    ref = change_set.of_kind(K.EVIDENCE_REF_REVISED)[0]
    assert (ref.subject_id, ref.before, ref.after, ref.related) == (f"{FACT_A2}#c1", FACT_A, FACT_A2, (KEY_A,))


# ---------------------------------------------------------------- 11〜13 diversity

def test_11_new_independent_origin(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "first_evidence", "second_independent_evidence")
    origin_change = change_set.of_kind(K.NEW_SOURCE_ORIGIN)[0]
    assert (origin_change.before, origin_change.after) == ("1", "2") and subjects(change_set, K.EVIDENCE_ADDED) == [KEY_MOF]


def test_12_same_origin_extra_evidence_is_not_a_new_origin(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    more = attach_evidence(obs, (attachment(FACT_B, day="2026-08-21", attached=day(13)),),      # FACT_A と同じ origin
                           recorded_at=day(13), provenance=provenance(reason="same origin"))
    change_set = C.detect_changes(extended(history, more), ROOT_A, day(12, 12), day(13, 12))
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.EVIDENCE_ADDED, K.NEW_EVIDENCE_DATE]
    assert K.NEW_SOURCE_ORIGIN not in kinds(change_set) and subjects(change_set, K.NEW_EVIDENCE_DATE) == ["2026-08-21"]


def test_13_new_origin_on_an_already_counted_date_is_not_a_new_date(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    same_day = attachment(DOC_X, EvidenceKind.SOURCE_DOCUMENT, day="2026-08-20", attached=day(13),
                          src=origin(kind=OriginKind.OFFICIAL_RELEASE, key="release:meti/" + DOC_X, source_ids=("meti",),
                                     publisher="meti"))
    more = attach_evidence(obs, (same_day,), recorded_at=day(13), provenance=provenance(reason="new origin"))
    change_set = C.detect_changes(extended(history, more), ROOT_A, day(12, 12), day(13, 12))
    assert kinds(change_set) == [K.OBSERVATION_REVISED, K.EVIDENCE_ADDED, K.NEW_SOURCE_ORIGIN]
    assert change_set.evidence_time_axis.new_evidence_dates == ()


# ---------------------------------------------------------------- 14〜19 qualification / flags

def test_14_qualification_forward(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "first_evidence", "second_independent_evidence")
    q = change_set.of_kind(K.QUALIFICATION_CHANGED)[0]
    assert (q.before, q.after) == ("THEME_CANDIDATE_POSSIBLE", "QUALIFIES_SEMANTICALLY")
    assert "not a lifecycle promotion" in q.detail


def test_15_qualification_backward(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    narrowed = revise_observation(obs, recorded_at=day(13), provenance=provenance(reason="narrow"),
                                  attachments=tuple(a for a in obs.attachments if a.ref_id == FACT_A))
    change_set = C.detect_changes(extended(history, narrowed), ROOT_A, day(12, 12), day(13, 12))
    q = change_set.of_kind(K.QUALIFICATION_CHANGED)[0]
    assert (q.before, q.after) == ("QUALIFIES_SEMANTICALLY", "THEME_CANDIDATE_POSSIBLE")
    assert K.CONTRADICTION_CLEARED in kinds(change_set) and len(change_set.of_kind(K.EVIDENCE_DROPPED)) == 3


def test_16_contradiction_appeared(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "second_independent_evidence", "contradiction_added")
    assert K.CONTRADICTION_APPEARED in kinds(change_set) and subjects(change_set, K.EVIDENCE_ADDED) == [KEY_BOJ]


def test_17_contradiction_cleared_is_about_the_current_view_only(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    without = revise_observation(obs, recorded_at=day(13), provenance=provenance(reason="drop contra"),
                                 attachments=tuple(a for a in obs.attachments if a.ref_id != DOC_BOJ))
    change_set = C.detect_changes(extended(history, without), ROOT_A, day(12, 12), day(13, 12))
    cleared = change_set.of_kind(K.CONTRADICTION_CLEARED)[0]
    assert cleared.before == "true" and cleared.after == "false" and "does not mean" in cleared.detail
    assert subjects(change_set, K.EVIDENCE_DROPPED) == [KEY_BOJ]
    assert C.detect_changes(extended(history, without), ROOT_A, day(3), day(12)).of_kind(K.CONTRADICTION_CLEARED) == ()


def invalidated(world: World, history: ThemeHistory):
    obs = terminal(world, history)
    key = obs.invalidation_conditions[0].condition_key
    inv = attachment(FACT_X, day="2026-09-05", attached=day(13), role=EvidenceRole.INVALIDATES,
                     invalidation_condition_ref=key, cref="")
    with_inv = attach_evidence(obs, (inv,), recorded_at=day(13), provenance=provenance(reason="invalidation"))
    without = revise_observation(with_inv, recorded_at=day(13, 6), provenance=provenance(reason="withdraw"),
                                 attachments=obs.attachments)
    return extended(history, with_inv, without), inv


def test_18_invalidation_appeared(world: World, history: ThemeHistory) -> None:
    h, inv = invalidated(world, history)
    change_set = C.detect_changes(h, ROOT_A, day(12, 12), day(13, 3))
    assert K.INVALIDATION_APPEARED in kinds(change_set) and subjects(change_set, K.EVIDENCE_ADDED) == [inv.attachment_key]
    assert change_set.evidence_time_axis.evidence[0].relation is EvidenceTimeRelation.DATED_BEFORE_WINDOW


def test_19_invalidation_cleared(world: World, history: ThemeHistory) -> None:
    h, inv = invalidated(world, history)
    change_set = C.detect_changes(h, ROOT_A, day(13, 3), day(13, 9))
    assert K.INVALIDATION_CLEARED in kinds(change_set) and subjects(change_set, K.EVIDENCE_DROPPED) == [inv.attachment_key]
    assert "does not mean" in change_set.of_kind(K.INVALIDATION_CLEARED)[0].detail


# ---------------------------------------------------------------- 20〜27 facets

def test_20_governance_changed(world: World, history: ThemeHistory) -> None:
    change_set = cs(history, "A", "mapping_added", "accepted")
    assert kinds(change_set) == [K.GOVERNANCE_CHANGED]
    g = change_set.changes[0]
    assert (g.before, g.after, g.subject_id) == ("", "CANDIDATE_ACCEPTED", world.ids["A.accepted"])
    assert g.detail == "effective_event,terminal_event" and g.related == (world.ids["A.accepted"],)


def test_21_governance_reversal(world: World, history: ThemeHistory) -> None:
    retired = cs(history, "A", "upstream_superseded", "retired").changes[0]
    assert (retired.before, retired.after) == ("CANDIDATE_ACCEPTED", "RETIRED")
    reversed_ = cs(history, "A", "retired", "retirement_reversed").changes[0]
    assert (reversed_.kind, reversed_.before, reversed_.after) == (K.GOVERNANCE_CHANGED, "RETIRED", "CANDIDATE_ACCEPTED")
    assert "reversal" in reversed_.detail and reversed_.related == (world.ids["A.reversed"],)


def test_22_metadata_label(world: World, history: ThemeHistory) -> None:
    change_set = cs(history, "A", "contradiction_added", "label_added")
    assert kinds(change_set) == [K.METADATA_CHANGED]
    m = change_set.changes[0]
    assert m.facet == "metadata:LABEL" and m.subject_id == world.ids["A.label1"] and m.before == "[]" and m.related == ()


def test_23_metadata_taxonomy(world: World, history: ThemeHistory) -> None:
    change_set = cs(history, "A", "label_added", "taxonomy_added")
    assert [c.facet for c in change_set.changes] == ["metadata:TAXONOMY"]
    assert change_set.changes[0].subject_id == world.ids["A.taxonomy1"]


def test_24_mapping_change(world: World, history: ThemeHistory) -> None:
    change_set = cs(history, "A", "taxonomy_added", "mapping_added")
    assert kinds(change_set) == [K.MAPPING_CHANGED]
    m = change_set.changes[0]
    assert m.related == (world.ids["A.map1"],) and m.before == "[]" and m.detail == ""
    assert change_set.knowledge_axis.mappings_recorded_at == ((world.ids["A.map1"], TIMES["T7_mapping"]),)


def test_25_lineage_change(world: World, history: ThemeHistory) -> None:
    change_set = cs(history, "A", "before_merge", "merge_declared_incomplete")
    assert kinds(change_set) == [K.GOVERNANCE_CHANGED, K.LINEAGE_CHANGED, K.PENDING_APPEARED]
    lineage = change_set.of_kind(K.LINEAGE_CHANGED)[0]
    assert (lineage.subject_id, lineage.after, lineage.related) == (world.ids["C.event"], "MERGED_INTO", (ROOT_C,))
    c_side = cs(history, "C", "before_merge", "merge_declared_incomplete")
    assert kinds(c_side) == [K.LINEAGE_CHANGED, K.PENDING_APPEARED] and c_side.changes[0].after == "MERGE_OF"


def test_26_pending_appeared(world: World, history: ThemeHistory) -> None:
    change_set = cs(history, "A", "before_merge", "merge_declared_incomplete")
    pending = change_set.of_kind(K.PENDING_APPEARED)[0]
    assert (pending.subject_id, pending.after, pending.related) == (world.ids["C.event"], "PENDING_EVENT", (ROOT_C,))


def test_27_pending_cleared_and_carried_evidence(world: World, history: ThemeHistory) -> None:
    change_set = cs(history, "C", "merge_root_declared_genesis_missing", "merge_completed")
    assert [c.before for c in change_set.of_kind(K.PENDING_CLEARED)] == ["PENDING_GENESIS", "PENDING_EVENT"]
    assert K.ROOT_BECAME_OBSERVED in kinds(change_set) and K.EVIDENCE_ADDED not in kinds(change_set)
    assert subjects(change_set, K.EVIDENCE_CARRIED) == sorted(c.attachment_key for c in world.resolve("C", "merge_completed").carried)
    assert K.LINEAGE_CHANGED not in kinds(change_set)                     # carried は lineage change と区別する
    root = cs(history, "C", "merge_declared_incomplete", "merge_root_declared_genesis_missing")
    assert K.ROOT_APPEARED in kinds(root) and [c.after for c in root.of_kind(K.PENDING_APPEARED)] == ["PENDING_GENESIS", "PENDING_EVENT"]


# ---------------------------------------------------------------- 28〜32 unresolved

def forked_semantic(world: World, history: ThemeHistory) -> ThemeHistory:
    obs = terminal(world, history)
    left = revise_observation(obs, recorded_at=day(13), provenance=provenance(), limitations=())
    right = revise_observation(obs, recorded_at=day(13, 6), provenance=provenance(), limitations=(limitation("late"),))
    return extended(history, right, left)


def test_28_semantic_resolved_to_unresolved(world: World, history: ThemeHistory) -> None:
    change_set = C.detect_changes(forked_semantic(world, history), ROOT_A, day(12, 12), day(13, 12))
    assert kinds(change_set) == [K.SEMANTIC_BECAME_UNRESOLVED]
    became = change_set.changes[0]
    assert became.before == world.ids["A.obs5"] and became.related == ("FORK",) and change_set.to_observation_id == ""
    assert [d.code for d in change_set.diagnostics] == ["SEMANTIC_UNRESOLVED_AT_T2"]
    assert change_set.to_status is ResolutionStatus.UNRESOLVED and change_set.status is ChangeSetStatus.COMPUTED


def test_29_semantic_unresolved_to_resolved(world: World, history: ThemeHistory) -> None:
    before = resolve(forked_semantic(world, history), ROOT_A, day(13, 12))
    after = world.resolve("A", "merge_completed")
    change_set = C.compare_resolutions(before, after)
    assert K.SEMANTIC_BECAME_RESOLVED in kinds(change_set)
    assert not any(c.facet in ("evidence", "derived") for c in change_set.changes)       # baseline が無い
    assert [d.code for d in change_set.diagnostics] == ["EVIDENCE_BASELINE_UNAVAILABLE"]


def test_30_governance_facet_unresolved_only(world: World, history: ThemeHistory) -> None:
    left = event(event_type=GovernanceEventType.RETIRED, reason="retire again a",
                 previous_event_ids=((ROOT_A, world.ids["A.reversed"]),), recorded_at=day(13))
    right = event(event_type=GovernanceEventType.RETIRED, reason="retire again b",
                  previous_event_ids=((ROOT_A, world.ids["A.reversed"]),), recorded_at=day(13, 6))
    change_set = C.detect_changes(extended(history, events=(right, left)), ROOT_A, day(12, 12), day(13, 12))
    assert kinds(change_set) == [K.FACET_BECAME_UNRESOLVED]
    assert change_set.changes[0].facet == "governance" and change_set.changes[0].related == ("FORK",)
    assert change_set.to_status is ResolutionStatus.RESOLVED


def test_31_metadata_facet_unresolved_only(world: World, history: ThemeHistory) -> None:
    left = metadata(value=("L",), previous_metadata_id=world.ids["A.label1"], recorded_at=day(13))
    right = metadata(value=("R",), previous_metadata_id=world.ids["A.label1"], recorded_at=day(13, 6))
    change_set = C.detect_changes(extended(history, metadata=(right, left)), ROOT_A, day(12, 12), day(13, 12))
    assert [(c.kind, c.facet) for c in change_set.changes] == [(K.FACET_BECAME_UNRESOLVED, "metadata:LABEL")]


def test_32_mapping_facet_unresolved_only(world: World, history: ThemeHistory) -> None:
    left = mapping(series_ref="a.series", supersedes_mapping_id=world.ids["A.map1"], recorded_at=day(13), valid_from=day(13))
    right = mapping(series_ref="b.series", supersedes_mapping_id=world.ids["A.map1"], recorded_at=day(13, 6),
                    valid_from=day(13, 6))
    h = extended(history, mappings=(right, left))
    change_set = C.detect_changes(h, ROOT_A, day(12, 12), day(13, 12))
    assert [(c.kind, c.facet) for c in change_set.changes] == [(K.FACET_BECAME_UNRESOLVED, "mapping")]
    single = C.detect_changes(h, ROOT_A, day(12, 12), day(13, 1))                          # fork 前は通常の MAPPING_CHANGED
    assert kinds(single) == [K.MAPPING_CHANGED] and single.changes[0].related == (left.mapping_id,)


# ---------------------------------------------------------------- 33〜39 no-state / dereference / failure / determinism

def test_33_no_state_is_not_a_failure(history: ThemeHistory) -> None:
    unknown = C.detect_changes(history, ROOT_B.replace("RV", "ZZ") if False else "theme_0123456789ABCDEFGHJKMNPQZZ",
                               CHECKPOINTS["before_root"], CHECKPOINTS["merge_completed"])
    assert unknown.status is ChangeSetStatus.COMPUTED and unknown.is_empty
    assert unknown.from_status is unknown.to_status is ResolutionStatus.NO_STATE
    assert cs(history, "A", "before_root", "root_only").status is ChangeSetStatus.COMPUTED


def test_34_dereference_change_is_separate_from_canonical_evidence(history: ThemeHistory) -> None:
    at = CHECKPOINTS["upstream_superseded"]
    def before_lookup(a):
        return DereferenceStatus.AVAILABLE
    def after_lookup(a):
        return DereferenceStatus.SUPERSEDED if a.ref_id == DOC_MOF else DereferenceStatus.AVAILABLE
    change_set = C.detect_changes(history, ROOT_A, at, at, dereference_before=before_lookup, dereference_after=after_lookup)
    assert kinds(change_set) == [K.DEREFERENCE_CHANGED]
    d = change_set.changes[0]
    assert (d.subject_id, d.before, d.after, d.facet) == (DOC_MOF, "AVAILABLE", "SUPERSEDED", "dereference")
    assert K.EVIDENCE_DROPPED not in kinds(change_set)
    assert C.detect_changes(history, ROOT_A, at, at, dereference_before=after_lookup, dereference_after=after_lookup).is_empty


def test_35_no_canonical_mutation(world: World) -> None:
    frozen = authority_bytes(world.data_root)
    history = ThemeHistory.from_store(ThemeStore.open(world.data_root, read_only=True))
    for prev, cur in zip(ORDER, ORDER[1:]):
        for root_key in ROOT_KEYS:
            cs(history, root_key, prev, cur)
    assert authority_bytes(world.data_root) == frozen
    assert not hasattr(ThemeChangeSet, "as_dict") and not hasattr(ThemeChangeSet, "append")


def test_36_input_order_is_irrelevant_and_comparison_is_pure(history: ThemeHistory) -> None:
    pairs = [("before_root", "root_only"), ("first_evidence", "contradiction_added"), ("accepted", "retirement_reversed"),
             ("before_merge", "merge_completed")]
    for seed in (3, 11, 29):
        h = shuffled(history, seed)
        for a, b in pairs:
            for root_key in ROOT_KEYS:
                assert cs(h, root_key, a, b) == cs(history, root_key, a, b), (seed, a, b, root_key)
    res_a, res_b = resolve(history, ROOT_A, CHECKPOINTS["accepted"]), resolve(history, ROOT_A, CHECKPOINTS["retired"])
    assert C.compare_resolutions(res_a, res_b) == C.compare_resolutions(res_a, res_b)


def test_37_from_after_to_is_rejected(history: ThemeHistory) -> None:
    with pytest.raises(ThemeChangeError, match="CUTOFF_ORDER"):
        C.detect_changes(history, ROOT_A, CHECKPOINTS["accepted"], CHECKPOINTS["first_evidence"])
    with pytest.raises(ThemeChangeError, match="CUTOFF_ORDER"):
        C.compare_resolutions(resolve(history, ROOT_A, CHECKPOINTS["accepted"]),
                              resolve(history, ROOT_A, CHECKPOINTS["first_evidence"]))


def test_38_root_mismatch_and_resolver_version_are_rejected(history: ThemeHistory) -> None:
    a, b = resolve(history, ROOT_A, CHECKPOINTS["accepted"]), resolve(history, ROOT_B, CHECKPOINTS["retired"])
    with pytest.raises(ThemeChangeError, match="ROOT_MISMATCH"):
        C.compare_resolutions(a, b)
    foreign = dataclasses.replace(resolve(history, ROOT_A, CHECKPOINTS["retired"]), resolver_version="theme_resolver:9.9.9")
    with pytest.raises(ThemeChangeError, match="RESOLVER_VERSION_INCOMPATIBLE"):
        C.compare_resolutions(a, foreign)


def test_39_invalid_or_corrupt_history_is_unavailable_not_a_change(world: World, history: ThemeHistory,
                                                                    tmp_path: Path) -> None:
    obs = terminal(world, history)
    broken = extended(history, rebuilt(obs, recorded_at=day(13), **IDENTITY_BREAKS["driver"]()))
    change_set = C.detect_changes(broken, ROOT_A, day(12, 12), day(13, 12))
    assert change_set.status is ChangeSetStatus.UNAVAILABLE and change_set.changes == ()
    assert [(d.code, d.related) for d in change_set.diagnostics] == [("AFTER_UNAVAILABLE", ("IDENTITY_CORE_CHANGED",))]
    assert change_set.to_status is ResolutionStatus.INVALID_HISTORY and not change_set.is_empty
    root = copy_world(world.data_root, tmp_path / "corrupt")
    path = ThemeStore.open(root, read_only=True).paths["observations"]
    path.write_bytes(path.read_bytes() + b"{not json\n")
    corrupt = resolve_at_data_root(root, ROOT_A, CHECKPOINTS["merge_completed"])
    assert corrupt.status is ResolutionStatus.STORE_CORRUPTION
    change_set = C.compare_resolutions(world.resolve("A", "accepted"), corrupt)
    assert change_set.status is ChangeSetStatus.UNAVAILABLE and change_set.diagnostics[0].code == "AFTER_UNAVAILABLE"
    assert change_set.diagnostics[0].detail == "STORE_CORRUPTION"


# ---------------------------------------------------------------- 40〜42 vocabulary / score / purity（source は boundary test）

FORBIDDEN_WORDS = ("EMERGING", "ACCELERATING", "MATURE", "WEAKENING", "STRONG", "WEAK", "BULLISH", "BEARISH",
                   "WINNING", "LOSING", "DORMANT", "ESTABLISHED", "PROMOT", "SCORE", "RANK", "WEIGHT", "CONFIDENCE")


def test_40_change_vocabulary_has_no_lifecycle_or_direction_words() -> None:
    for kind in ChangeKind:
        assert not any(word in kind.value for word in FORBIDDEN_WORDS), kind
    assert {k.value for k in ChangeKind} >= {
        "ROOT_APPEARED", "ROOT_BECAME_OBSERVED", "OBSERVATION_REVISED", "SEMANTIC_FIELD_CHANGED", "EVIDENCE_ADDED",
        "EVIDENCE_DROPPED", "EVIDENCE_ROLE_CHANGED", "NEW_SOURCE_ORIGIN", "NEW_EVIDENCE_DATE", "QUALIFICATION_CHANGED",
        "CONTRADICTION_APPEARED", "CONTRADICTION_CLEARED", "INVALIDATION_APPEARED", "INVALIDATION_CLEARED",
        "GOVERNANCE_CHANGED", "METADATA_CHANGED", "MAPPING_CHANGED", "LINEAGE_CHANGED", "PENDING_APPEARED",
        "PENDING_CLEARED", "SEMANTIC_BECAME_UNRESOLVED", "SEMANTIC_BECAME_RESOLVED", "FACET_BECAME_UNRESOLVED",
        "FACET_BECAME_RESOLVED", "DEREFERENCE_CHANGED"}


def test_41_change_set_carries_no_score_or_rank(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "before_root", "merge_completed")
    for field in dataclasses.fields(ThemeChangeSet):
        assert not any(word in field.name.upper() for word in ("SCORE", "RANK", "WEIGHT", "CONFIDENCE", "STRENGTH"))
    for change in change_set.changes:
        assert isinstance(change.before, str) and isinstance(change.after, str)
        assert not isinstance(getattr(change, "value", None), float)
    text = canonical_json([dataclasses.asdict(c) for c in change_set.changes])
    assert not any(word.lower() in text.lower() for word in ("score", "rank", "bullish", "bearish", "winning"))


def test_42_change_set_fields_are_data_only(history: ThemeHistory) -> None:
    change_set = cs(history, "A", "before_root", "merge_completed")
    assert change_set.kinds()[:2] == (K.ROOT_APPEARED, K.ROOT_BECAME_OBSERVED)
    assert isinstance(hash(change_set), int)                             # frozen（決定論比較可能）
    with pytest.raises(dataclasses.FrozenInstanceError):
        change_set.changes = ()                                          # type: ignore[misc]
