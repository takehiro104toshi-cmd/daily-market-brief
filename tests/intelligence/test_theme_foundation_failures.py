"""P6-A4d — crash / PENDING を resolver まで通す E2E、fork / ambiguity の facet 隔離、store 破損の fail closed。"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.themes import operations as O
from src.intelligence.themes.model import GovernanceEventType, MetadataField, ProvenanceClass, canonical_line
from src.intelligence.themes.resolver import (
    GovernanceStatus, MappingStatus, MetadataStatus, ResolutionStatus, ThemeHistory, resolve, resolve_at_data_root,
)
from src.intelligence.themes.revision import revise_observation
from src.intelligence.themes.store import ThemeStore
from tests.intelligence.test_theme_model import (
    FACT_A, ROOT_A, ROOT_C, attachment, condition, event, limitation, mapping, mechanism, metadata, observation,
    provenance, root_record, scope, subject,
)
from tests.intelligence.test_theme_store import SimulatedCrash, interrupt_after
from tests.intelligence.theme_foundation_fixtures import (
    CHECKPOINTS, ROOT_KEYS, ROOT_Q, TIMES, World, authority_bytes, build_world, copy_world, day, evidence_a2,
)

H1 = timedelta(hours=1)


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    return build_world(tmp_path_factory.mktemp("world") / "data")


def facet(res, field_):
    return next(m for m in res.metadata if m.field is field_)


# ---------------------------------------------------------------- §8 crash / PENDING through the resolver

def test_candidate_crash_pending_resume_e2e(tmp_path: Path) -> None:
    root = tmp_path / "q"
    store = ThemeStore.initialize(root)
    spec = O.GenesisSpec(subject=subject(), mechanism=mechanism(), certainty_class=O.MechanismCertainty.HYPOTHESIZED_MECHANISM,
                         scope=scope(), invalidation_conditions=(condition(),), provenance=provenance(), recorded_at=day(0, 2))
    plan = O.plan_candidate(root_id=ROOT_Q, created_at=day(0), creator_class=ProvenanceClass.HUMAN,
                            creation_provenance="reviewer:r1", genesis=spec, attachments=(attachment(FACT_A, attached=day(0, 1)),))
    interrupt_after(store, 1)
    with pytest.raises(SimulatedCrash):
        O.execute_candidate(store, plan)
    frozen = authority_bytes(root)
    crash_cutoff = day(0, 1)
    at_crash = resolve_at_data_root(root, ROOT_Q, crash_cutoff)
    assert at_crash.status is ResolutionStatus.NO_STATE and [p.kind for p in at_crash.pending] == ["PENDING_GENESIS"]
    assert authority_bytes(root) == frozen                                                    # resolver / open は直さない
    result = O.execute_candidate(ThemeStore.open(root), plan)
    assert result.status is O.OperationStatus.COMPLETE
    assert resolve_at_data_root(root, ROOT_Q, day(0, 3)).status is ResolutionStatus.RESOLVED
    assert resolve_at_data_root(root, ROOT_Q, crash_cutoff) == at_crash                        # 旧 cutoff は PENDING のまま


def test_merge_crash_stages_are_visible_through_the_resolver(world: World) -> None:
    """代表 world 自体が event → crash → root → crash → genesis で作られている。stage ごとの snapshot が証拠。"""
    declared_a = world.snapshots["merge_declared"][("A", "merge_declared_incomplete")]      # subject 側は PENDING を示す
    assert declared_a.status is ResolutionStatus.RESOLVED and [(p.kind, p.missing) for p in declared_a.pending] == [
        ("PENDING_EVENT", (ROOT_C,))]
    assert world.snapshots["merge_completed"][("A", "merge_declared_incomplete")] == declared_a     # 遡及しない
    root_only = world.snapshots["merge_root"][("C", "merge_root_declared_genesis_missing")]
    assert root_only.status is ResolutionStatus.NO_STATE and {p.kind for p in root_only.pending} == {"PENDING_GENESIS", "PENDING_EVENT"}
    assert world.snapshots["merge_completed"][("C", "merge_root_declared_genesis_missing")] == root_only
    assert world.snapshots["merge_root"][("A", "merge_root_declared_genesis_missing")].pending[0].missing == (world.ids["C.genesis"],)
    assert world.resolve("C", "merge_completed").status is ResolutionStatus.RESOLVED


@pytest.mark.xfail(strict=True, reason="BLOCKER A4D-3: declared-but-uncreated result root resolves to UNKNOWN_ROOT without "
                                       "PENDING_EVENT / lineage (only the subject roots show the pending declaration)")
def test_declared_but_uncreated_result_root_shows_pending_event(world: World) -> None:
    declared_c = world.snapshots["merge_declared"][("C", "merge_declared_incomplete")]
    assert declared_c.status is ResolutionStatus.NO_STATE and [p.kind for p in declared_c.pending] == ["PENDING_EVENT"]
    assert [l.kind.value for l in declared_c.lineage] == ["MERGE_OF"]


@pytest.mark.parametrize("builder_name,writes,result_index,result_pending", [
    ("split", 1, 0, None),                                     # event のみ: 子 root は未作成
    ("split", 3, 1, None),                                     # Y 完了、Z 未作成
    ("split", 4, 1, ["PENDING_GENESIS", "PENDING_EVENT"]),     # Z root あり、genesis なし
    ("successor", 1, 0, None),
    ("successor", 2, 0, ["PENDING_GENESIS", "PENDING_EVENT"]),
])
def test_split_and_successor_partial_completion_e2e(tmp_path: Path, builder_name, writes, result_index,
                                                    result_pending) -> None:
    from tests.intelligence.test_theme_foundation_e2e import split_world, successor_world
    builder = split_world if builder_name == "split" else successor_world
    root = tmp_path / builder_name
    times, genesis, plan = builder(root)
    store = ThemeStore.open(root)
    interrupt_after(store, writes)
    with pytest.raises(SimulatedCrash):
        O.execute_declaration(store, plan)
    frozen = authority_bytes(root)
    cutoff = max(times.values()) + H1                                                        # crash 時点（全 record より後）
    subject_root = plan.event.subject_roots[0]
    subject_view = resolve_at_data_root(root, subject_root, cutoff)
    assert subject_view.status is ResolutionStatus.RESOLVED and [p.kind for p in subject_view.pending] == ["PENDING_EVENT"]
    result_root_id = plan.results[result_index][0].root_id
    result_view = resolve_at_data_root(root, result_root_id, cutoff)
    assert result_view.status is ResolutionStatus.NO_STATE
    if result_pending is not None:                                    # root あり genesis なし: result 側も PENDING を示す
        assert [p.kind for p in result_view.pending] == result_pending
    # result_pending is None（root 未作成）の result 側 PENDING は BLOCKER A4D-3（strict xfail に固定）
    assert authority_bytes(root) == frozen
    resumed = O.execute_declaration(ThemeStore.open(root), plan)
    assert resumed.status is O.OperationStatus.COMPLETE
    for result_root, _ in plan.results:
        assert resolve_at_data_root(root, result_root.root_id, cutoff).status is ResolutionStatus.RESOLVED
    assert resolve_at_data_root(root, subject_root, times["event"] + timedelta(minutes=1)).pending[0].kind == "PENDING_EVENT"


@pytest.mark.xfail(strict=True, reason="BLOCKER A4D-1: A3 §7 / §23 assign IDENTITY_CORE_CHANGED to the persistence "
                                       "boundary, but the store accepts an observation whose identity core differs from "
                                       "its predecessor (only the pure revision helper enforces it)")
def test_store_rejects_identity_core_change_within_a_root(tmp_path: Path) -> None:
    from src.intelligence.themes.store import ThemeAppendRejected
    from src.intelligence.themes.model import ThemeObservation
    from src.intelligence.themes.fingerprint import identity_core_fingerprint
    from tests.intelligence.test_theme_model import component
    from tests.intelligence.test_theme_store import seeded
    store, root_record_, obs = seeded(tmp_path / "s")
    changed = ThemeObservation.build(
        root_id=ROOT_A, previous_observation_id=obs.observation_id, subject=obs.subject,
        mechanism=mechanism(drivers=(component(category="POLICY_RATE", typed_reference="rates:boj"),)),
        certainty_class=obs.certainty_class, scope=obs.scope, limitations=obs.limitations,
        invalidation_conditions=obs.invalidation_conditions, attachments=obs.attachments,
        provenance=provenance(), recorded_at=obs.recorded_at + H1)
    assert identity_core_fingerprint(changed) != identity_core_fingerprint(obs)
    with pytest.raises(ThemeAppendRejected, match="IDENTITY_CORE_CHANGED"):
        store.append_observation(changed)


# ---------------------------------------------------------------- §9 fork / ambiguity isolation

def test_observation_fork_only_breaks_the_semantic_facet(world: World) -> None:
    store = ThemeStore.open(world.data_root, read_only=True)
    base = ThemeHistory.from_store(store)
    obs5 = store.get_observation(world.ids["A.obs5"])
    left = revise_observation(obs5, recorded_at=day(13), provenance=provenance(), limitations=())
    right = revise_observation(obs5, recorded_at=day(13, 6), provenance=provenance(), limitations=(limitation("late"),))
    forked = ThemeHistory(base.roots, base.observations + (right, left), base.events, base.metadata, base.mappings)
    at = resolve(forked, ROOT_A, day(13, 12))
    assert at.status is ResolutionStatus.UNRESOLVED and at.observation is None
    assert [d.kind for d in at.diagnostics] == ["FORK"]
    assert at.governance.status is GovernanceStatus.RESOLVED and at.governance.effective_event_type is GovernanceEventType.CANDIDATE_ACCEPTED
    assert facet(at, MetadataField.LABEL).status is MetadataStatus.RESOLVED and at.mapping.status is MappingStatus.RESOLVED
    assert resolve(forked, ROOT_A, day(12, 23)).observation == obs5                            # fork 前は線形


def test_governance_fork_only_breaks_the_governance_facet(world: World) -> None:
    store = ThemeStore.open(world.data_root, read_only=True)
    base = ThemeHistory.from_store(store)
    left = event(event_type=GovernanceEventType.RETIRED, reason="retire again a",
                 previous_event_ids=((ROOT_A, world.ids["A.reversed"]),), recorded_at=day(13))
    right = event(event_type=GovernanceEventType.RETIRED, reason="retire again b",
                  previous_event_ids=((ROOT_A, world.ids["A.reversed"]),), recorded_at=day(13, 6))
    forked = ThemeHistory(base.roots, base.observations, base.events + (right, left), base.metadata, base.mappings)
    at = resolve(forked, ROOT_A, day(13, 12))
    assert at.status is ResolutionStatus.RESOLVED and at.observation.observation_id == world.ids["A.obs5"]
    assert at.governance.status is GovernanceStatus.UNRESOLVED and [d.kind for d in at.governance.diagnostics] == ["FORK"]
    assert at.governance.effective_event_id == ""                                                # 勝者を選ばない
    assert facet(at, MetadataField.LABEL).status is MetadataStatus.RESOLVED and at.mapping.status is MappingStatus.RESOLVED


def test_label_fork_only_breaks_the_label_facet(world: World) -> None:
    store = ThemeStore.open(world.data_root, read_only=True)
    base = ThemeHistory.from_store(store)
    left = metadata(value=("L",), previous_metadata_id=world.ids["A.label1"], recorded_at=day(13))
    right = metadata(value=("R",), previous_metadata_id=world.ids["A.label1"], recorded_at=day(13, 6))
    forked = ThemeHistory(base.roots, base.observations, base.events, base.metadata + (right, left), base.mappings)
    at = resolve(forked, ROOT_A, day(13, 12))
    assert at.status is ResolutionStatus.RESOLVED
    assert facet(at, MetadataField.LABEL).status is MetadataStatus.UNRESOLVED and facet(at, MetadataField.LABEL).value == ()
    assert facet(at, MetadataField.TAXONOMY).status is MetadataStatus.RESOLVED
    assert at.governance.status is GovernanceStatus.RESOLVED and at.mapping.status is MappingStatus.RESOLVED


def test_mapping_fork_only_breaks_the_mapping_facet(world: World) -> None:
    store = ThemeStore.open(world.data_root, read_only=True)
    base = ThemeHistory.from_store(store)
    left = mapping(series_ref="a.series", supersedes_mapping_id=world.ids["A.map1"], recorded_at=day(13), valid_from=day(13))
    right = mapping(series_ref="b.series", supersedes_mapping_id=world.ids["A.map1"], recorded_at=day(13, 6), valid_from=day(13, 6))
    forked = ThemeHistory(base.roots, base.observations, base.events, base.metadata, base.mappings + (right, left))
    at = resolve(forked, ROOT_A, day(13, 12))
    assert at.status is ResolutionStatus.RESOLVED and at.mapping.status is MappingStatus.UNRESOLVED
    assert at.governance.status is GovernanceStatus.RESOLVED and facet(at, MetadataField.LABEL).status is MetadataStatus.RESOLVED
    assert resolve(forked, ROOT_A, day(13, 1)).mapping.terminal_mapping_ids == (left.mapping_id,)


# ---------------------------------------------------------------- §14 store failure / corruption（copy 上で破壊）

def corrupt(path: Path, how: str, sample_line: str) -> None:
    if how == "malformed_json":
        path.write_bytes(path.read_bytes() + b"{not json\n")
    elif how == "noncanonical_line":
        record = json.loads(sample_line)
        path.write_bytes(path.read_bytes() + (json.dumps(record, ensure_ascii=False, indent=None, separators=(", ", ": "),
                                                          sort_keys=True) + "\n").encode("utf-8"))
    elif how == "truncated_final_line":
        path.write_bytes(path.read_bytes() + sample_line.encode("utf-8")[:-1])
    elif how == "duplicate_conflicting_id":
        record = json.loads(sample_line)
        record["recorded_at"] = "2030-01-01T00:00:00+00:00"
        path.write_bytes(path.read_bytes() + (json.dumps(record, ensure_ascii=False, sort_keys=True,
                                                          separators=(",", ":")) + "\n").encode("utf-8"))
    elif how == "missing_authority_file":
        path.unlink()


@pytest.mark.parametrize("how,code", [
    ("malformed_json", "MALFORMED_JSON"), ("noncanonical_line", "NON_CANONICAL_LINE"),
    ("truncated_final_line", "TRUNCATED_FINAL_LINE"), ("duplicate_conflicting_id", "PHYSICAL_DUPLICATE_CONFLICTING"),
    ("missing_authority_file", "AUTHORITY_MISSING"),
])
def test_corruption_is_fail_closed_at_the_resolver_entry_point(world: World, tmp_path: Path, how, code) -> None:
    original = authority_bytes(world.data_root)
    root = copy_world(world.data_root, tmp_path / how)
    store = ThemeStore.open(root, read_only=True)
    sample = store.canonical_lines("observations")[-1]
    del store
    corrupt(root / "themes" / "theme_observations.jsonl", how, sample)
    damaged = authority_bytes(root) if how != "missing_authority_file" else None
    for root_id in ROOT_KEYS.values():
        res = resolve_at_data_root(root, root_id, CHECKPOINTS["merge_completed"])
        assert res.status is ResolutionStatus.STORE_CORRUPTION and res.diagnostics[0].kind == code
        assert res.diagnostics[0].facet == "store" and res.observation is None
        assert res.governance.status is GovernanceStatus.NOT_EVALUATED
    if damaged is not None:
        assert authority_bytes(root) == damaged                                                 # 修復・truncate・rewrite なし
    else:
        assert not (root / "themes" / "theme_observations.jsonl").exists()
    assert authority_bytes(world.data_root) == original                                         # 元 fixture は無傷
    assert world.resolve("A", "merge_completed").status is ResolutionStatus.RESOLVED
