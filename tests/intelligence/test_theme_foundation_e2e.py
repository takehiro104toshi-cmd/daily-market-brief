"""P6-A4d — Theme Foundation E2E: 代表 world の time-travel checkpoint、restart / reload、correction / revision、
merge / split / successor、carried evidence、upstream revision、derived 再計算、契約 traceability。"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.themes import operations as O
from src.intelligence.themes.model import (
    CreationMethod, EvidenceRole, GovernanceEventType, MechanismCertainty, MetadataField, ProvenanceClass,
    ThemeGovernanceEvent, ThemeObservation, canonical_line,
)
from src.intelligence.themes.resolver import (
    DereferenceStatus, GovernanceStatus, LineageKind, MappingStatus, MetadataStatus, ResolutionStatus, ThemeHistory,
    resolve, resolve_at_data_root, resolve_from_store,
)
from src.intelligence.themes.revision import revise_observation
from src.intelligence.themes.store import ThemeStore
from tests.intelligence.test_theme_model import (
    FACT_A, ROOT_A, ROOT_B, ROOT_C, T0, attachment, condition, event, mapping, mechanism, metadata, observation,
    provenance, root_record, scope, subject,
)
from tests.intelligence.theme_foundation_fixtures import (
    CHECKPOINTS, DOC_MOF, KEY_A, KEY_B, KEY_BOJ, KEY_MOF, KEY_NEWS, MOF, ROOT_KEYS, ROOT_M, ROOT_N, ROOT_Q, ROOT_X,
    ROOT_Y, ROOT_Z, TIMES, World, authority_bytes, build_world, day, evidence_a2, resolution_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
H1 = timedelta(hours=1)
D1 = timedelta(days=1)


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    return build_world(tmp_path_factory.mktemp("world") / "data")


def facet(res, field_):
    return next(m for m in res.metadata if m.field is field_)


# ---------------------------------------------------------------- §3 time-travel checkpoints（literal）

def test_checkpoints_before_root_and_root_only(world: World) -> None:
    before = world.resolve("A", "before_root")
    assert before.status is ResolutionStatus.NO_STATE and [d.kind for d in before.diagnostics] == ["ROOT_AFTER_CUTOFF"]
    assert before.governance.status is GovernanceStatus.NOT_EVALUATED
    root_only = world.resolve("A", "root_only")
    assert root_only.status is ResolutionStatus.NO_STATE and root_only.root.root_id == ROOT_A
    assert [(p.kind, p.missing) for p in root_only.pending] == [("PENDING_GENESIS", (world.ids["A.genesis"],))]
    assert root_only.governance.status is GovernanceStatus.NO_GOVERNANCE
    assert [m.status for m in root_only.metadata] == [MetadataStatus.NO_METADATA] * 4
    assert root_only.mapping.status is MappingStatus.NO_MAPPING
    assert world.resolve("B", "root_only").status is ResolutionStatus.NO_STATE       # B は T0+12h 作成


def test_checkpoints_evidence_accumulation(world: World) -> None:
    genesis = world.resolve("A", "genesis_visible")
    assert genesis.status is ResolutionStatus.RESOLVED and genesis.observation.observation_id == world.ids["A.genesis"]
    assert genesis.evidence.visible == () and genesis.derived.qualification.status.value == "THEME_CANDIDATE_POSSIBLE"
    assert "NO_COUNTED_EVIDENCE" in genesis.derived.qualification.diagnostics
    first = world.resolve("A", "first_evidence")
    assert first.observation.observation_id == world.ids["A.obs1"]
    assert [a.attachment_key for a in first.evidence.visible] == [KEY_A]
    assert first.derived.qualification.status.value == "THEME_CANDIDATE_POSSIBLE"
    assert first.derived.qualification.independent_origins == 1 and first.derived.qualification.evidence_dates == ("2026-08-20",)
    assert {"SINGLE_SOURCE_ORIGIN", "SINGLE_EVIDENCE_DATE"} <= set(first.derived.qualification.diagnostics)
    second = world.resolve("A", "second_independent_evidence")
    assert second.observation.observation_id == world.ids["A.obs2"]
    assert [a.attachment_key for a in second.evidence.visible] == [KEY_MOF, KEY_A]
    assert second.derived.qualification.status.value == "QUALIFIES_SEMANTICALLY"
    assert second.derived.qualification.independent_origins == 2
    assert second.derived.qualification.evidence_dates == ("2026-08-20", "2026-08-25")
    assert not second.derived.has_contradicting_evidence
    contradiction = world.resolve("A", "contradiction_added")
    assert contradiction.observation.observation_id == world.ids["A.obs3"]
    assert [a.attachment_key for a in contradiction.evidence.visible] == [KEY_MOF, KEY_BOJ, KEY_A]
    assert contradiction.derived.has_contradicting_evidence and not contradiction.derived.has_invalidating_evidence
    assert contradiction.derived.qualification.status.value == "QUALIFIES_SEMANTICALLY"
    assert "HAS_CONTRADICTING_EVIDENCE" in contradiction.derived.qualification.diagnostics
    assert contradiction.governance.status is GovernanceStatus.NO_GOVERNANCE
    b = world.resolve("B", "first_evidence")
    assert b.status is ResolutionStatus.RESOLVED and [a.attachment_key for a in b.evidence.visible] == [KEY_B]


def test_checkpoints_metadata_mapping_governance(world: World) -> None:
    label = world.resolve("A", "label_added")
    assert facet(label, MetadataField.LABEL).status is MetadataStatus.RESOLVED
    assert facet(label, MetadataField.LABEL).value == ("Yen weakness and import input cost",)
    assert facet(label, MetadataField.TAXONOMY).status is MetadataStatus.NO_METADATA
    assert label.mapping.status is MappingStatus.NO_MAPPING and label.observation.observation_id == world.ids["A.obs3"]
    taxonomy = world.resolve("A", "taxonomy_added")
    assert facet(taxonomy, MetadataField.TAXONOMY).value == ("fx", "input_cost")
    mapped = world.resolve("A", "mapping_added")
    assert mapped.mapping.status is MappingStatus.RESOLVED and mapped.mapping.terminal_mapping_ids == (world.ids["A.map1"],)
    assert mapped.governance.status is GovernanceStatus.NO_GOVERNANCE
    accepted = world.resolve("A", "accepted")
    assert accepted.governance.status is GovernanceStatus.RESOLVED
    assert accepted.governance.chain == (world.ids["A.accepted"],)
    assert accepted.governance.effective_event_type is GovernanceEventType.CANDIDATE_ACCEPTED
    assert accepted.observation.observation_id == world.ids["A.obs3"]                  # metadata / governance は semantic を変えない


def test_checkpoints_revision_delayed_evidence_and_upstream(world: World) -> None:
    revised = world.resolve("A", "semantic_revision")
    before = world.resolve("A", "accepted")
    assert revised.observation.observation_id == world.ids["A.obs4"] != before.observation.observation_id
    assert len(revised.observation.limitations) == 2 and len(before.observation.limitations) == 1
    assert [a.attachment_key for a in revised.evidence.visible] == [KEY_MOF, KEY_BOJ, KEY_A]
    assert revised.derived.identity_core_fingerprint == before.derived.identity_core_fingerprint
    assert revised.derived.semantic_fingerprint == before.derived.semantic_fingerprint    # limitations は fingerprint 外
    pre = world.resolve("A", "delayed_evidence_before_attachment")
    assert pre.observation.observation_id == world.ids["A.obs4"]
    assert KEY_NEWS not in [a.attachment_key for a in pre.evidence.visible]              # evidence 日付 08-28 は T より前だが付与は T 後
    post = world.resolve("A", "delayed_evidence_after_attachment")
    assert post.observation.observation_id == world.ids["A.obs5"]
    assert [a.attachment_key for a in post.evidence.visible] == [KEY_MOF, KEY_BOJ, KEY_A, KEY_NEWS]
    assert post.derived.qualification.independent_origins == 4 and len(post.derived.qualification.evidence_dates) == 4
    upstream = world.resolve("A", "upstream_superseded",
                             dereference=lambda a: DereferenceStatus.SUPERSEDED if a.ref_id == FACT_A else DereferenceStatus.AVAILABLE)
    assert upstream.observation.observation_id == post.observation.observation_id
    assert dict((d.ref_id, d.status) for d in upstream.dereference)[FACT_A] is DereferenceStatus.SUPERSEDED
    assert upstream.evidence == post.evidence and upstream.derived == post.derived


def test_checkpoints_retired_reversed_and_merge(world: World) -> None:
    retired = world.resolve("A", "retired")
    assert retired.governance.effective_event_type is GovernanceEventType.RETIRED
    assert retired.governance.chain == (world.ids["A.accepted"], world.ids["A.retired"])
    reversed_ = world.resolve("A", "retirement_reversed")
    assert reversed_.governance.effective_event_type is GovernanceEventType.CANDIDATE_ACCEPTED
    assert reversed_.governance.terminal_event_id == world.ids["A.reversed"]
    assert reversed_.governance.reversed_event_ids == (world.ids["A.retired"],)
    assert len(reversed_.governance.chain) == 3 and reversed_.observation.observation_id == world.ids["A.obs5"]
    before_merge = world.resolve("A", "before_merge")
    assert before_merge.lineage == () and before_merge.pending == ()
    assert world.resolve("C", "before_merge").status is ResolutionStatus.NO_STATE
    assert world.resolve("C", "before_merge").pending == ()
    declared = world.resolve("A", "merge_declared_incomplete")
    assert declared.governance.effective_event_type is GovernanceEventType.MERGE and len(declared.governance.chain) == 4
    assert [(l.kind, l.related_roots) for l in declared.lineage] == [(LineageKind.MERGED_INTO, (ROOT_C,))]
    assert [(p.kind, p.missing) for p in declared.pending] == [("PENDING_EVENT", (ROOT_C,))]
    assert declared.observation.observation_id == world.ids["A.obs5"]
    c_declared = world.resolve("C", "merge_declared_incomplete")
    assert c_declared.status is ResolutionStatus.NO_STATE and [p.kind for p in c_declared.pending] == ["PENDING_EVENT"]
    assert [l.kind for l in c_declared.lineage] == [LineageKind.MERGE_OF]
    c_root = world.resolve("C", "merge_root_declared_genesis_missing")
    assert c_root.status is ResolutionStatus.NO_STATE and {p.kind for p in c_root.pending} == {"PENDING_GENESIS", "PENDING_EVENT"}
    assert world.resolve("A", "merge_root_declared_genesis_missing").pending[0].missing == (world.ids["C.genesis"],)
    completed = world.resolve("C", "merge_completed")
    assert completed.status is ResolutionStatus.RESOLVED and completed.observation.observation_id == world.ids["C.genesis"]
    assert [a.attachment_key for a in completed.evidence.visible] == [KEY_A, KEY_B]
    assert completed.derived.qualification.status.value == "QUALIFIES_SEMANTICALLY"
    assert completed.derived.qualification.independent_origins == 2
    assert [(c.attachment_key, c.source_observation_id, c.source_root_id) for c in completed.carried] == [
        (KEY_A, world.ids["A.obs5"], ROOT_A), (KEY_B, world.ids["B.genesis"], ROOT_B)]
    assert completed.governance.chain == (world.ids["C.event"],) and completed.pending == ()
    assert world.resolve("A", "merge_completed").pending == () and world.resolve("B", "merge_completed").lineage[0].kind is LineageKind.MERGED_INTO


# ---------------------------------------------------------------- §4 restart / reload

def test_restart_reload_gives_identical_results(world: World) -> None:
    for root_key, root_id in ROOT_KEYS.items():
        for name, cutoff in CHECKPOINTS.items():
            via_store = resolve_from_store(ThemeStore.open(world.data_root, read_only=True), root_id, cutoff)
            via_path = resolve_at_data_root(world.data_root, root_id, cutoff)
            via_history = resolve(ThemeHistory.from_store(ThemeStore.open(world.data_root, read_only=True)), root_id, cutoff)
            assert via_store == via_path == via_history, (root_key, name)


def test_restart_in_a_separate_process_matches(world: World) -> None:
    probes = [(root_id, name) for root_id in ROOT_KEYS.values()
              for name in ("root_only", "contradiction_added", "retirement_reversed", "merge_declared_incomplete",
                           "merge_completed")]
    code = (
        "import json, sys\n"
        "from tests.intelligence.theme_foundation_fixtures import CHECKPOINTS, resolution_digest\n"
        "from src.intelligence.themes.resolver import resolve_at_data_root\n"
        f"root = {str(world.data_root)!r}\n"
        f"probes = {probes!r}\n"
        "print(json.dumps([resolution_digest(resolve_at_data_root(root, r, CHECKPOINTS[c])) for r, c in probes], sort_keys=True))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                          env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    other_process = json.loads(proc.stdout)
    here = [resolution_digest(resolve_at_data_root(world.data_root, r, CHECKPOINTS[c])) for r, c in probes]
    assert json.loads(json.dumps(here, sort_keys=True)) == other_process


# ---------------------------------------------------------------- §10 correction / revision（別 fixture）

def correction_world(root: Path):
    """Q: genesis（FACT_A SUPPORTS ＋ MOF）→ label typo → label 訂正 ＋ 承認 → 役割訂正（新 observation ＋ 承認）→
    mapping supersession → revert-as-new-observation。各 stage で store を作り直す。"""
    times = {"root": day(0), "genesis": day(0, 1), "label1": day(1), "label2": day(2), "label_ok": day(2, 1),
             "map1": day(1, 2), "role": day(3), "role_ok": day(3, 1), "map2": day(4), "revert": day(5)}
    store = ThemeStore.initialize(root)
    genesis = observation(root_id=ROOT_Q, attachments=(attachment(FACT_A, attached=times["genesis"]),
                                                       evidence_a2(times["genesis"])), recorded_at=times["genesis"])
    store.append_root(root_record(genesis, created_at=times["root"]))
    store.append_observation(genesis)
    store = ThemeStore.open(root)
    label1 = metadata(root_id=ROOT_Q, value=("Yen weakness / inpt cost",), recorded_at=times["label1"])
    store.append_metadata(label1)
    map1 = mapping(root_id=ROOT_Q, recorded_at=times["map1"], valid_from=times["map1"])
    store.append_mapping(map1)
    store = ThemeStore.open(root)
    label2 = metadata(root_id=ROOT_Q, value=("Yen weakness / input cost",), previous_metadata_id=label1.metadata_id,
                      recorded_at=times["label2"], reason="typo")
    store.append_metadata(label2)
    # NOTE: METADATA_CORRECTION_APPROVED は BLOCKER A4D-2（store の load 順で再 open 不能）のため本 world には入れない。
    #       再現は test_metadata_correction_approval_survives_reload（strict xfail）に固定する。
    store = ThemeStore.open(root)
    corrected = attachment(FACT_A, attached=times["role"], role=EvidenceRole.CONTRADICTS, provenance=ProvenanceClass.HUMAN,
                           asserted_by="reviewer:r1", note="direction was misread")
    role_obs = revise_observation(genesis, recorded_at=times["role"], provenance=provenance(reason="role correction"),
                                  attachments=(corrected, evidence_a2(times["genesis"])))
    store.append_observation(role_obs)
    role_ok = event(event_type=GovernanceEventType.ROLE_CORRECTION_APPROVED, subject_roots=(ROOT_Q,),
                    related_observations=(role_obs.observation_id,), reason="role corrected",
                    recorded_at=times["role_ok"])
    store.append_governance(role_ok)
    store = ThemeStore.open(root)
    map2 = mapping(root_id=ROOT_Q, series_ref="fx:USDJPY.close.closing.tokyo", supersedes_mapping_id=map1.mapping_id,
                   recorded_at=times["map2"], valid_from=times["map2"])
    store.append_mapping(map2)
    store = ThemeStore.open(root)
    revert = revise_observation(role_obs, recorded_at=times["revert"], provenance=provenance(reason="revert role"),
                                attachments=genesis.attachments)
    store.append_observation(revert)
    return times, dict(genesis=genesis, label1=label1, label2=label2, role_obs=role_obs, role_ok=role_ok, map1=map1,
                       map2=map2, revert=revert)


def test_correction_and_revision_are_new_history_with_old_bytes_intact(tmp_path: Path) -> None:
    root = tmp_path / "q"
    times, r = correction_world(root)
    lines = ThemeStore.open(root, read_only=True).canonical_lines("observations")
    assert lines[0] == canonical_line(r["genesis"]) and lines[1] == canonical_line(r["role_obs"])
    assert lines[2] == canonical_line(r["revert"])                                            # 旧 bytes は不変・追記のみ
    res = lambda t: resolve_at_data_root(root, ROOT_Q, t)
    # metadata correction: old cutoff = typo, new cutoff = corrected（observation は無変化）
    assert facet(res(times["label1"]), MetadataField.LABEL).value == ("Yen weakness / inpt cost",)
    assert facet(res(times["label2"]), MetadataField.LABEL).value == ("Yen weakness / input cost",)
    assert res(times["label2"]).observation == r["genesis"] and res(times["label1"]).observation == r["genesis"]
    assert res(times["label2"]).governance.status is GovernanceStatus.NO_GOVERNANCE
    # role correction: SUPPORTS → CONTRADICTS as a new observation; old cutoff keeps SUPPORTS
    before_role = res(times["role"] - H1)
    after_role = res(times["role_ok"])
    assert before_role.observation.attachment(KEY_A).role is EvidenceRole.SUPPORTS
    assert after_role.observation.attachment(KEY_A).role is EvidenceRole.CONTRADICTS
    assert after_role.observation.observation_id == r["role_obs"].observation_id
    assert after_role.governance.effective_event_type is GovernanceEventType.ROLE_CORRECTION_APPROVED
    assert after_role.derived.has_contradicting_evidence and not before_role.derived.has_contradicting_evidence
    assert after_role.derived.identity_core_fingerprint == before_role.derived.identity_core_fingerprint
    # mapping supersession
    assert res(times["map1"]).mapping.terminal_mapping_ids == (r["map1"].mapping_id,)
    assert res(times["map2"]).mapping.terminal_mapping_ids == (r["map2"].mapping_id,)
    # revert-as-new-observation: same semantics as genesis, new id, previous = role_obs
    reverted = res(times["revert"])
    assert reverted.observation.observation_id == r["revert"].observation_id
    assert reverted.observation.previous_observation_id == r["role_obs"].observation_id
    assert reverted.observation.attachments == r["genesis"].attachments
    assert reverted.observation.observation_id != r["genesis"].observation_id
    assert res(times["role_ok"] + H1).observation.observation_id == r["role_obs"].observation_id   # revert 前の T は訂正状態


@pytest.mark.xfail(strict=True, reason="BLOCKER A4D-2: store validates METADATA_CORRECTION_APPROVED related metadata in "
                                       "the intra pass although metadata loads after governance; a valid history cannot be reopened")
def test_metadata_correction_approval_survives_reload(tmp_path: Path) -> None:
    root = tmp_path / "q2"
    store = ThemeStore.initialize(root)
    genesis = observation(root_id=ROOT_Q, recorded_at=day(0, 1))
    store.append_root(root_record(genesis, created_at=day(0)))
    store.append_observation(genesis)
    label1 = metadata(root_id=ROOT_Q, value=("Yen weakness / inpt cost",), recorded_at=day(1))
    store.append_metadata(label1)
    label2 = metadata(root_id=ROOT_Q, value=("Yen weakness / input cost",), previous_metadata_id=label1.metadata_id,
                      recorded_at=day(2), reason="typo")
    store.append_metadata(label2)
    approval = event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED, subject_roots=(ROOT_Q,),
                     related_observations=(label2.metadata_id,), reason="typo fixed", recorded_at=day(2, 1))
    store.append_governance(approval)                                          # append は受理される
    frozen = authority_bytes(root)
    reopened = ThemeStore.open(root, read_only=True)                          # ← ここで INVALID_HISTORY になる（欠陥）
    assert reopened.counts()["governance"] == 1 and authority_bytes(root) == frozen
    res = resolve_at_data_root(root, ROOT_Q, day(3))
    assert res.governance.effective_event_type is GovernanceEventType.METADATA_CORRECTION_APPROVED
    assert facet(res, MetadataField.LABEL).value == ("Yen weakness / input cost",)


# ---------------------------------------------------------------- §11 merge / split / successor

def test_merge_semantics_e2e(world: World) -> None:
    store = ThemeStore.open(world.data_root, read_only=True)
    pre_lines = store.canonical_lines("observations")
    a_obs5 = store.get_observation(world.ids["A.obs5"])
    c_genesis = store.get_observation(world.ids["C.genesis"])
    root_c = store.get_root(ROOT_C)
    assert root_c.creation_method is CreationMethod.MERGE_RESULT and root_c.origin_event_id == world.ids["C.event"]
    assert canonical_line(a_obs5) in pre_lines and c_genesis.observation_id not in {o.observation_id for o in (a_obs5,)}
    # old roots addressable / old semantics not rewritten
    assert world.resolve("A", "merge_completed").observation == a_obs5
    assert world.resolve("B", "merge_completed").observation.observation_id == world.ids["B.genesis"]
    # explicit allocation only: MOF / BOJ / NEWS attachments of A were not carried
    assert {a.attachment_key for a in c_genesis.attachments} == {KEY_A, KEY_B}
    assert c_genesis.attachment(KEY_A) == a_obs5.attachment(KEY_A)                                # byte-identical
    assert c_genesis.attachment(KEY_A).attached_at < root_c.created_at                           # original attached_at
    event_ = store.get_governance_event(world.ids["C.event"])
    assert {(a.source_observation_id, a.attachment_key) for a in event_.evidence_allocation} == {
        (world.ids["A.obs5"], KEY_A), (world.ids["B.genesis"], KEY_B)}
    assert world.resolve("A", "before_merge").lineage == () and world.resolve("A", "merge_completed").lineage != ()


def split_world(root: Path):
    times = {"root": day(0), "genesis": day(0, 1), "event": day(2), "y_root": day(3), "y_genesis": day(3, 1),
             "z_root": day(3, 2), "z_genesis": day(3, 3)}
    store = ThemeStore.initialize(root)
    genesis = observation(root_id=ROOT_X, recorded_at=times["genesis"])            # KEY_A / KEY_B
    store.append_root(root_record(genesis, created_at=times["root"]))
    store.append_observation(genesis)
    store = ThemeStore.open(root)

    def spec(root_id, key, created, recorded):
        return O.ResultRootSpec(root_id=root_id, created_at=created, creation_provenance="reviewer:r1",
                                genesis=O.GenesisSpec(subject=subject(), mechanism=mechanism(),
                                                      certainty_class=MechanismCertainty.HYPOTHESIZED_MECHANISM,
                                                      scope=scope(), invalidation_conditions=(condition(),),
                                                      provenance=provenance(reason="split child"), recorded_at=recorded),
                                carried=((genesis.observation_id, key),))

    plan = O.plan_split(store, subject_root=ROOT_X,
                        children=(spec(ROOT_Y, KEY_A, times["y_root"], times["y_genesis"]),
                                  spec(ROOT_Z, KEY_B, times["z_root"], times["z_genesis"])),
                        reason="two domains", actor_ref="reviewer:r1", recorded_at=times["event"],
                        previous_event_ids=O.terminal_previous_events(store, (ROOT_X,)))
    return times, genesis, plan


def test_split_semantics_e2e(tmp_path: Path) -> None:
    root = tmp_path / "x"
    times, genesis, plan = split_world(root)
    O.execute_declaration(ThemeStore.open(root), plan)
    res = lambda rid, t: resolve_at_data_root(root, rid, t)
    assert res(ROOT_X, times["event"] - H1).lineage == () and res(ROOT_Y, times["event"] - H1).status is ResolutionStatus.NO_STATE
    declared = res(ROOT_X, times["event"] + H1)
    assert [l.kind for l in declared.lineage] == [LineageKind.SPLIT_INTO] and set(declared.lineage[0].related_roots) == {ROOT_Y, ROOT_Z}
    assert [(p.kind, set(p.missing)) for p in declared.pending] == [("PENDING_EVENT", {ROOT_Y, ROOT_Z})]
    partial = res(ROOT_X, times["y_genesis"] + timedelta(minutes=30))                       # Y 完了、Z 未作成
    assert [(p.kind, p.missing) for p in partial.pending] == [("PENDING_EVENT", (ROOT_Z,))]
    done_x = res(ROOT_X, times["z_genesis"] + H1)
    assert done_x.pending == () and done_x.observation == genesis                           # 旧 root は不変で addressable
    y = res(ROOT_Y, times["z_genesis"] + H1)
    z = res(ROOT_Z, times["z_genesis"] + H1)
    assert y.status is z.status is ResolutionStatus.RESOLVED and y.observation.observation_id != z.observation.observation_id
    assert [a.attachment_key for a in y.evidence.visible] == [KEY_A] and [a.attachment_key for a in z.evidence.visible] == [KEY_B]
    assert y.evidence.visible[0] == genesis.attachment(KEY_A) and y.evidence.visible[0].attached_at < y.root.created_at
    assert y.carried[0].source_observation_id == genesis.observation_id and y.lineage[0].kind is LineageKind.SPLIT_FROM
    assert y.root.creation_method is CreationMethod.SPLIT_RESULT and y.root.origin_event_id == plan.event.event_id


def successor_world(root: Path):
    times = {"root": day(0), "genesis": day(0, 1), "event": day(2), "n_root": day(3), "n_genesis": day(3, 1)}
    store = ThemeStore.initialize(root)
    genesis = observation(root_id=ROOT_M, recorded_at=times["genesis"])
    store.append_root(root_record(genesis, created_at=times["root"]))
    store.append_observation(genesis)
    store = ThemeStore.open(root)
    from tests.intelligence.test_theme_model import component
    from src.intelligence.themes.model import ComponentType
    new_mechanism = mechanism(drivers=(component(category="POLICY_RATE", typed_reference="rates:boj"),))   # driver 置換 ＝ 新 root
    spec = O.ResultRootSpec(root_id=ROOT_N, created_at=times["n_root"], creation_provenance="reviewer:r1",
                            genesis=O.GenesisSpec(subject=subject(), mechanism=new_mechanism,
                                                  certainty_class=MechanismCertainty.HYPOTHESIZED_MECHANISM,
                                                  scope=scope(), invalidation_conditions=(condition(),),
                                                  provenance=provenance(reason="driver replaced"),
                                                  recorded_at=times["n_genesis"]),
                            carried=((genesis.observation_id, KEY_A),))
    plan = O.plan_successor(store, subject_root=ROOT_M, result=spec, reason="driver replaced", actor_ref="reviewer:r1",
                            recorded_at=times["event"], previous_event_ids=O.terminal_previous_events(store, (ROOT_M,)))
    return times, genesis, plan


def test_successor_semantics_e2e(tmp_path: Path) -> None:
    root = tmp_path / "m"
    times, genesis, plan = successor_world(root)
    O.execute_declaration(ThemeStore.open(root), plan)
    res = lambda rid, t: resolve_at_data_root(root, rid, t)
    assert res(ROOT_M, times["event"] - H1).lineage == ()
    declared = res(ROOT_M, times["event"] + H1)
    assert [(l.kind, l.related_roots) for l in declared.lineage] == [(LineageKind.SUPERSEDED_BY, (ROOT_N,))]
    assert [(p.kind, p.missing) for p in declared.pending] == [("PENDING_EVENT", (ROOT_N,))]
    old = res(ROOT_M, times["n_genesis"] + H1)
    new = res(ROOT_N, times["n_genesis"] + H1)
    assert old.observation == genesis and old.governance.effective_event_type is GovernanceEventType.SUPERSEDED_BY_ROOT
    assert new.status is ResolutionStatus.RESOLVED and new.root.creation_method is CreationMethod.SUCCESSOR_RESULT
    assert new.derived.identity_core_fingerprint != old.derived.identity_core_fingerprint     # identity core が違う ＝ 別 root
    assert [a.attachment_key for a in new.evidence.visible] == [KEY_A] and new.carried[0].source_root_id == ROOT_M
    assert new.lineage[0].kind is LineageKind.SUCCESSOR_OF


# ---------------------------------------------------------------- §12 upstream revision / §13 derived

def test_upstream_supersession_changes_only_dereference_status(world: World) -> None:
    before_bytes = authority_bytes(world.data_root)
    available = world.resolve("A", "upstream_superseded", dereference=lambda a: DereferenceStatus.AVAILABLE)
    superseded = world.resolve("A", "upstream_superseded",
                               dereference=lambda a: DereferenceStatus.SUPERSEDED if a.ref_id == FACT_A else DereferenceStatus.AVAILABLE)
    assert available.observation == superseded.observation and available.evidence == superseded.evidence
    assert available.derived == superseded.derived and available.governance == superseded.governance
    assert [d.status for d in available.dereference] != [d.status for d in superseded.dereference]
    assert authority_bytes(world.data_root) == before_bytes
    joined = b"".join(before_bytes.values()).decode("utf-8")
    assert "SUPERSEDED" not in joined and "dereference" not in joined and "NOT_CHECKED" not in joined


def test_derived_values_are_recomputed_and_never_stored(world: World) -> None:
    joined = b"".join(authority_bytes(world.data_root).values()).decode("utf-8")
    for token in ("fingerprint", "thcore_", "thsem_", "qualification", "QUALIFIES", "CANDIDATE_POSSIBLE",
                  "independent_origins", "DIRECTLY_EVIDENCED", "has_contradicting", '"lineage":', "carried_from",
                  "PENDING", '"current', '"latest', "dereference", "NOT_CHECKED"):
        assert token not in joined, token
    progression = [world.resolve("A", cp).derived.qualification for cp in
                   ("genesis_visible", "first_evidence", "second_independent_evidence", "delayed_evidence_after_attachment")]
    assert [q.independent_origins for q in progression] == [0, 1, 2, 4]
    assert [len(q.evidence_dates) for q in progression] == [0, 1, 2, 4]
    assert [q.status.value for q in progression] == ["THEME_CANDIDATE_POSSIBLE", "THEME_CANDIDATE_POSSIBLE",
                                                     "QUALIFIES_SEMANTICALLY", "QUALIFIES_SEMANTICALLY"]
    assert world.resolve("A", "contradiction_added").derived.has_contradicting_evidence
    assert world.resolve("C", "merge_completed").derived.directly_evidenced_links == ()


# ---------------------------------------------------------------- §16 contract traceability

def test_a1_semantic_authority_traceability(world: World) -> None:
    obs = world.resolve("A", "merge_completed").observation
    assert not {"label", "description", "narrative", "prose", "recommendation", "horizon", "target_price"} & set(obs.__dataclass_fields__)
    assert obs.certainty_class in MechanismCertainty and obs.mechanism.consequences and obs.invalidation_conditions
    store = ThemeStore.open(world.data_root, read_only=True)
    assert all(e.actor_class is ProvenanceClass.HUMAN for e in store.events_for_root(ROOT_A))       # governance は人間 decision
    from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
    assert not any(".themes" in m for m in runtime_closure())                                        # Theme は production authority ではない


def test_a2_identity_evidence_traceability(world: World) -> None:
    store = ThemeStore.open(world.data_root, read_only=True)
    chain = store.observations_for_root(ROOT_A)
    assert len({o.observation_id for o in chain}) == 6 and len({o.root_id for o in chain}) == 1        # 二層 identity
    for att in world.resolve("A", "delayed_evidence_after_attachment").evidence.visible:
        assert att.evidence_time <= att.attached_at and att.source_origin.is_known                     # 二重時点・origin
    q = world.resolve("A", "delayed_evidence_after_attachment").derived.qualification
    assert q.independent_origins == 4 and len(q.evidence_dates) == 4                                    # diversity
    assert world.resolve("A", "genesis_visible").derived.identity_core_fingerprint == world.resolve("A", "merge_completed").derived.identity_core_fingerprint


def test_a3_persistence_traceability(world: World) -> None:
    store = ThemeStore.open(world.data_root, read_only=True)
    assert store.counts() == {"roots": 3, "observations": 8, "governance": 4, "metadata": 2, "mappings": 1}
    lines = store.canonical_lines("observations")
    assert len(lines) == len(set(lines)) and all(line.endswith("\n") for line in lines)                 # append-only canonical
    assert store.pending() == () and store.diagnostics() == ()
    assert world.resolve("C", "merge_declared_incomplete").pending and world.resolve("C", "merge_completed").pending == ()
