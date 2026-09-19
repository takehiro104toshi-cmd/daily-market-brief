"""P6-A4d — Theme Foundation E2E の代表 world（完全 synthetic・決定論・tmp data_root 上）。test 専用 helper。

代表 world（Theme A / B / C）:
    A  T0 root → T1 genesis → T2 evidence#1 → T3 evidence#2（独立 origin）→ T4 反証 → T5 LABEL → T6 TAXONOMY →
       T7 mapping → T8 CANDIDATE_ACCEPTED → T9 semantic revision → T10 遅延付与 → T11 上流 supersession（canonical 変更なし）
       → T12 RETIRED → T13 EVENT_REVERSED
    B  独立 candidate root（T0+12h root / T0+13h genesis。A の T1 と T2 の間に追記される）
    C  MERGE A+B（宣言 → crash → 結果 root → crash → 結果 genesis。世界そのものが declaration-first の途中状態を含む）

各 stage は store object を作り直す（write → discard → `ThemeStore.open`）。stage ごとに、既に過ぎた checkpoint の
resolution を `resolve_at_data_root` で snapshot し、最終状態と比較できるようにする（future leakage の証明）。
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Sequence, Tuple

from src.intelligence.themes import operations as O
from src.intelligence.themes.model import (
    EvidenceKind, EvidenceRole, GovernanceEventType, MechanismCertainty, MetadataField, OriginKind,
    ThemeGovernanceEvent, ThemeMetadataRecord, ThemeObservation, ThemeRootRecord, ThemeSeriesMapping,
)
from src.intelligence.themes.resolver import ThemeResolution, resolve_at_data_root
from src.intelligence.themes.revision import attach_evidence, revise_observation
from src.intelligence.themes.store import LOAD_ORDER, ThemeStore, authority_paths
from tests.intelligence.test_theme_model import (
    FACT_A, FACT_B, NEWS_D, ROOT_A, ROOT_B, ROOT_C, T0, attachment, condition, event, limitation, mapping, mechanism,
    metadata, observation, origin, provenance, root_record, scope, subject,
)
from tests.intelligence.test_theme_store import SimulatedCrash, interrupt_after

# ---------------------------------------------------------------- fixed identifiers（決定論。replay でも再生成しない）

DOC_MOF = "doc_" + "c" * 24
DOC_BOJ = "doc_" + "e" * 24
ROOT_X = "theme_0123456789ABCDEFGHJKMNPQRY"
ROOT_Y = "theme_0123456789ABCDEFGHJKMNPQRZ"
ROOT_Z = "theme_0123456789ABCDEFGHJKMNPQS0"
ROOT_M = "theme_0123456789ABCDEFGHJKMNPQS1"
ROOT_N = "theme_0123456789ABCDEFGHJKMNPQS2"
ROOT_Q = "theme_0123456789ABCDEFGHJKMNPQS3"
KEY_A = f"{FACT_A}#c1"
KEY_B = f"{FACT_B}#c1"
KEY_MOF = f"{DOC_MOF}#c1"
KEY_BOJ = f"{DOC_BOJ}#c1"
KEY_NEWS = f"{NEWS_D}#c1"

MOF = origin(kind=OriginKind.OFFICIAL_RELEASE, key="release:mof_japan/" + DOC_MOF, source_ids=("mof_japan",),
             publisher="mof_japan")
BOJ = origin(kind=OriginKind.OFFICIAL_RELEASE, key="release:boj/" + DOC_BOJ, source_ids=("boj",), publisher="boj")
WIRE = origin(kind=OriginKind.PUBLISHER_ARTICLE, key="article:art_" + "f" * 24, source_ids=("feed_a",),
              publisher="wire_x")
NIKKEI = origin(key="series:jquants/index:nikkei225.close")


def day(n: float, hours: float = 0) -> datetime:
    return T0 + timedelta(days=n, hours=hours)


TIMES: Dict[str, datetime] = {
    "T0_root": T0, "T1_genesis": day(0, 1), "T2_evidence1": day(1), "T3_evidence2": day(2), "T4_contradiction": day(3),
    "T5_label": day(4), "T6_taxonomy": day(5), "T7_mapping": day(6), "T8_accepted": day(7), "T9_revision": day(8),
    "T10_delayed": day(9), "T11_upstream": day(10), "T12_retired": day(11), "T13_reversed": day(12),
    "TB0_root": day(0, 12), "TB1_genesis": day(0, 13),
    "TM_event": day(14), "TM_root": day(14, 1), "TM_genesis": day(14, 2),
}

CHECKPOINTS: Dict[str, datetime] = {
    "before_root": T0 - timedelta(seconds=1),
    "root_only": T0 + timedelta(minutes=30),
    "genesis_visible": TIMES["T1_genesis"],
    "first_evidence": TIMES["T2_evidence1"],
    "second_independent_evidence": TIMES["T3_evidence2"],
    "contradiction_added": TIMES["T4_contradiction"],
    "label_added": TIMES["T5_label"],
    "taxonomy_added": TIMES["T6_taxonomy"],
    "mapping_added": TIMES["T7_mapping"],
    "accepted": TIMES["T8_accepted"],
    "semantic_revision": TIMES["T9_revision"],
    "delayed_evidence_before_attachment": TIMES["T9_revision"] + timedelta(hours=12),
    "delayed_evidence_after_attachment": TIMES["T10_delayed"],
    "upstream_superseded": TIMES["T11_upstream"],
    "retired": TIMES["T12_retired"],
    "retirement_reversed": TIMES["T13_reversed"],
    "before_merge": TIMES["TM_event"] - timedelta(seconds=1),
    "merge_declared_incomplete": TIMES["TM_event"] + timedelta(minutes=30),
    "merge_root_declared_genesis_missing": TIMES["TM_root"] + timedelta(minutes=30),
    "merge_completed": TIMES["TM_genesis"] + timedelta(hours=1),
}

STAGE_TIMES: Dict[str, datetime] = {
    "root_a": TIMES["T0_root"], "genesis_a": TIMES["T1_genesis"], "evidence1": TIMES["T2_evidence1"],
    "evidence2": TIMES["T3_evidence2"], "contradiction": TIMES["T4_contradiction"], "label": TIMES["T5_label"],
    "taxonomy": TIMES["T6_taxonomy"], "mapping": TIMES["T7_mapping"], "accepted": TIMES["T8_accepted"],
    "revision": TIMES["T9_revision"], "delayed": TIMES["T10_delayed"], "retired": TIMES["T12_retired"],
    "reversed": TIMES["T13_reversed"], "root_b": TIMES["TB0_root"], "merge_declared": TIMES["TM_event"],
    "merge_root": TIMES["TM_root"], "merge_completed": TIMES["TM_genesis"],
}

ROOT_KEYS = {"A": ROOT_A, "B": ROOT_B, "C": ROOT_C}


# ---------------------------------------------------------------- evidence used by Theme A / B

def evidence_a1(attached: datetime):
    return attachment(FACT_A, attached=attached, day="2026-08-20")                      # jquants topix series


def evidence_a2(attached: datetime):
    return attachment(DOC_MOF, EvidenceKind.SOURCE_DOCUMENT, src=MOF, day="2026-08-25", attached=attached)


def evidence_a3(attached: datetime):
    return attachment(DOC_BOJ, EvidenceKind.SOURCE_DOCUMENT, src=BOJ, day="2026-08-26", attached=attached,
                      role=EvidenceRole.CONTRADICTS)


def evidence_a4(attached: datetime):
    return attachment(NEWS_D, EvidenceKind.NEWS_ITEM, src=WIRE, day="2026-08-28", attached=attached)


def evidence_b1(attached: datetime):
    return attachment(FACT_B, src=NIKKEI, day="2026-08-21", attached=attached)


# ---------------------------------------------------------------- world

@dataclass
class World:
    data_root: Path
    ids: Dict[str, str] = field(default_factory=dict)
    times: Dict[str, datetime] = field(default_factory=lambda: dict(TIMES))
    checkpoints: Dict[str, datetime] = field(default_factory=lambda: dict(CHECKPOINTS))
    snapshots: Dict[str, Dict[Tuple[str, str], ThemeResolution]] = field(default_factory=dict)
    merge_previous: Tuple[Tuple[str, str], ...] = ()
    merge_plan: object = None
    stage_order: Tuple[str, ...] = ()

    def resolve(self, root_key: str, checkpoint: str, **kw) -> ThemeResolution:
        return resolve_at_data_root(self.data_root, ROOT_KEYS[root_key], self.checkpoints[checkpoint], **kw)

    def snapshot(self, stage: str, until: datetime = None) -> None:
        """stage 完了時点で、次の stage の record 時刻より前の checkpoint の resolution を保存する
        （後の stage が過去を変えない証明に使う。until が None なら全 checkpoint）。"""
        self.snapshots[stage] = {
            (root_key, name): resolve_at_data_root(self.data_root, root_id, cutoff)
            for root_key, root_id in ROOT_KEYS.items()
            for name, cutoff in self.checkpoints.items() if until is None or cutoff < until
        }


def _open(world: World) -> ThemeStore:
    return ThemeStore.open(world.data_root)


def _merge_plan(world: World, store: ThemeStore):
    obs_a5 = store.get_observation(world.ids["A.obs5"])
    obs_b = store.get_observation(world.ids["B.genesis"])
    spec = O.ResultRootSpec(
        root_id=ROOT_C, created_at=TIMES["TM_root"], creation_provenance="reviewer:r1",
        genesis=O.GenesisSpec(subject=subject(), mechanism=mechanism(),
                              certainty_class=MechanismCertainty.HYPOTHESIZED_MECHANISM, scope=scope(),
                              invalidation_conditions=(condition(),), provenance=provenance(reason="merged a and b"),
                              recorded_at=TIMES["TM_genesis"]),
        carried=((obs_a5.observation_id, KEY_A), (obs_b.observation_id, KEY_B)))
    return O.plan_merge(store, subject_roots=(ROOT_A, ROOT_B), result=spec, reason="same mechanism, one lineage",
                        actor_ref="reviewer:r1", recorded_at=TIMES["TM_event"], previous_event_ids=world.merge_previous)


def build_world(data_root: Path, *, stop_after: str = "merge_completed") -> World:
    """代表 world を stage 順に構築する。各 stage で store を作り直し、snapshot を取る。"""
    world = World(data_root=Path(data_root))
    stages: List[Tuple[str, Callable[[World], None]]] = [
        ("root_a", _stage_root_a), ("genesis_a", _stage_genesis_a), ("root_b", _stage_root_b),
        ("evidence1", _stage_evidence1), ("evidence2", _stage_evidence2), ("contradiction", _stage_contradiction),
        ("label", _stage_label), ("taxonomy", _stage_taxonomy), ("mapping", _stage_mapping),
        ("accepted", _stage_accepted), ("revision", _stage_revision), ("delayed", _stage_delayed),
        ("retired", _stage_retired), ("reversed", _stage_reversed), ("merge_declared", _stage_merge_declared),
        ("merge_root", _stage_merge_root), ("merge_completed", _stage_merge_completed),
    ]
    world.stage_order = tuple(name for name, _ in stages)
    for index, (name, stage) in enumerate(stages):
        stage(world)
        until = STAGE_TIMES[stages[index + 1][0]] if index + 1 < len(stages) else None
        world.snapshot(name, until)
        if name == stop_after:
            break
    return world


def _stage_root_a(world: World) -> None:
    store = ThemeStore.initialize(world.data_root)                    # 唯一の file 作成
    genesis = observation(attachments=(), recorded_at=TIMES["T1_genesis"])
    world.ids["A.genesis"] = genesis.observation_id
    store.append_root(root_record(genesis, created_at=TIMES["T0_root"]))


def _stage_genesis_a(world: World) -> None:
    store = _open(world)
    store.append_observation(observation(attachments=(), recorded_at=TIMES["T1_genesis"]))


def _attach(world: World, previous_key: str, new_key: str, attachments, at: datetime, reason: str) -> None:
    store = _open(world)
    previous = store.get_observation(world.ids[previous_key])
    new = attach_evidence(previous, attachments, recorded_at=at, provenance=provenance(reason=reason))
    store.append_observation(new)
    world.ids[new_key] = new.observation_id


def _stage_evidence1(world: World) -> None:
    _attach(world, "A.genesis", "A.obs1", (evidence_a1(TIMES["T2_evidence1"]),), TIMES["T2_evidence1"], "evidence 1")


def _stage_evidence2(world: World) -> None:
    _attach(world, "A.obs1", "A.obs2", (evidence_a2(TIMES["T3_evidence2"]),), TIMES["T3_evidence2"], "evidence 2")


def _stage_contradiction(world: World) -> None:
    _attach(world, "A.obs2", "A.obs3", (evidence_a3(TIMES["T4_contradiction"]),), TIMES["T4_contradiction"],
            "contradiction")


def _stage_label(world: World) -> None:
    store = _open(world)
    record = metadata(value=("Yen weakness and import input cost",), recorded_at=TIMES["T5_label"])
    store.append_metadata(record)
    world.ids["A.label1"] = record.metadata_id


def _stage_taxonomy(world: World) -> None:
    store = _open(world)
    record = metadata(field=MetadataField.TAXONOMY, value=("fx", "input_cost"), recorded_at=TIMES["T6_taxonomy"])
    store.append_metadata(record)
    world.ids["A.taxonomy1"] = record.metadata_id


def _stage_mapping(world: World) -> None:
    store = _open(world)
    record = mapping(recorded_at=TIMES["T7_mapping"], valid_from=TIMES["T7_mapping"])
    store.append_mapping(record)
    world.ids["A.map1"] = record.mapping_id


def _stage_accepted(world: World) -> None:
    store = _open(world)
    accepted = event(related_observations=(world.ids["A.obs3"],), recorded_at=TIMES["T8_accepted"])
    store.append_governance(accepted)
    world.ids["A.accepted"] = accepted.event_id


def _stage_revision(world: World) -> None:
    store = _open(world)
    previous = store.get_observation(world.ids["A.obs3"])
    revised = revise_observation(previous, recorded_at=TIMES["T9_revision"], provenance=provenance(reason="refined"),
                                 limitations=(limitation(), limitation("fx pass-through lag uncertain")))
    store.append_observation(revised)
    world.ids["A.obs4"] = revised.observation_id


def _stage_delayed(world: World) -> None:
    _attach(world, "A.obs4", "A.obs5", (evidence_a4(TIMES["T10_delayed"]),), TIMES["T10_delayed"], "delayed evidence")


def _stage_retired(world: World) -> None:
    store = _open(world)
    retired = event(event_type=GovernanceEventType.RETIRED, reason="mechanism no longer active",
                    previous_event_ids=((ROOT_A, world.ids["A.accepted"]),), recorded_at=TIMES["T12_retired"])
    store.append_governance(retired)
    world.ids["A.retired"] = retired.event_id


def _stage_reversed(world: World) -> None:
    store = _open(world)
    reversal = event(event_type=GovernanceEventType.EVENT_REVERSED, reverses_event_id=world.ids["A.retired"],
                     reason="retirement recorded in error", previous_event_ids=((ROOT_A, world.ids["A.retired"]),),
                     recorded_at=TIMES["T13_reversed"])
    store.append_governance(reversal)
    world.ids["A.reversed"] = reversal.event_id


def _stage_root_b(world: World) -> None:
    store = _open(world)
    genesis = observation(root_id=ROOT_B, subject=subject("tourism inflow and service demand", ""),
                          attachments=(evidence_b1(TIMES["TB1_genesis"]),), recorded_at=TIMES["TB1_genesis"])
    store.append_root(root_record(genesis, created_at=TIMES["TB0_root"]))
    store.append_observation(genesis)
    world.ids["B.genesis"] = genesis.observation_id


def _stage_merge_declared(world: World) -> None:
    store = _open(world)
    world.merge_previous = O.terminal_previous_events(store, (ROOT_A, ROOT_B))   # 最初の試行前に一度だけ
    plan = _merge_plan(world, store)
    world.merge_plan = plan
    world.ids["C.event"] = plan.event.event_id
    world.ids["C.genesis"] = plan.results[0][1].observation_id
    interrupt_after(store, 1)                                                        # event だけ書いて crash
    try:
        O.execute_declaration(store, plan)
    except SimulatedCrash:
        pass


def _stage_merge_root(world: World) -> None:
    store = _open(world)
    plan = _merge_plan(world, store)
    assert plan == world.merge_plan                                                  # 同じ入力 → 同じ plan
    interrupt_after(store, 1)                                                        # root だけ書いて crash
    try:
        O.execute_declaration(store, plan)
    except SimulatedCrash:
        pass


def _stage_merge_completed(world: World) -> None:
    store = _open(world)
    plan = _merge_plan(world, store)
    assert plan == world.merge_plan
    result = O.execute_declaration(store, plan)
    assert result.status is O.OperationStatus.COMPLETE


# ---------------------------------------------------------------- byte-level replay（test helper）

_RECORD_TYPES = {"roots": ThemeRootRecord, "observations": ThemeObservation, "governance": ThemeGovernanceEvent,
                 "metadata": ThemeMetadataRecord, "mappings": ThemeSeriesMapping}
_ID_FIELDS = {"roots": "root_id", "observations": "observation_id", "governance": "event_id",
              "metadata": "metadata_id", "mappings": "mapping_id"}


def authority_bytes(data_root: Path) -> Dict[str, bytes]:
    """5 authority の生 bytes（store を開かずに読む。破損 fixture でも使える）。無い file は key ごと省く。"""
    return {name: path.read_bytes() for name, path in authority_paths(data_root).items() if path.exists()}


def records_from_bytes(bytes_map: Mapping[str, bytes]) -> Dict[str, List[object]]:
    out: Dict[str, List[object]] = {}
    for name in LOAD_ORDER:
        text = bytes_map[name].decode("utf-8")
        out[name] = [_RECORD_TYPES[name].from_dict(json.loads(line)) for line in text.split("\n") if line]
    return out


def _dependencies(name: str, record, records: Mapping[str, List[object]]) -> set:
    roots = {r.root_id: r for r in records["roots"]}
    events = {e.event_id: e for e in records["governance"]}
    deps: set = set()
    if name == "roots":
        if record.origin_event_id:
            deps.add(record.origin_event_id)
    elif name == "observations":
        deps.add(record.root_id)
        if record.previous_observation_id:
            deps.add(record.previous_observation_id)
        root = roots.get(record.root_id)
        if root is not None and root.origin_event_id and record.previous_observation_id == "":
            event = events.get(root.origin_event_id)
            if event is not None:
                deps |= {a.source_observation_id for a in event.evidence_allocation if a.result_root_id == root.root_id}
    elif name == "governance":
        deps |= set(record.subject_roots) | set(record.related_observations)
        deps |= {previous for _, previous in record.previous_event_ids}
        if record.reverses_event_id:
            deps.add(record.reverses_event_id)
        deps |= {a.source_observation_id for a in record.evidence_allocation}
    elif name == "metadata":
        deps.add(record.root_id)
        if record.previous_metadata_id:
            deps.add(record.previous_metadata_id)
        if record.governance_event_id:
            deps.add(record.governance_event_id)
    elif name == "mappings":
        deps.add(record.root_id)
        if record.supersedes_mapping_id:
            deps.add(record.supersedes_mapping_id)
        if record.consequence_ref:
            declaring = sorted((o.recorded_at, o.observation_id) for o in records["observations"]
                               if o.root_id == record.root_id and record.consequence_ref in o.mechanism.consequence_keys)
            if declaring:
                deps.add(declaring[0][1])
    return deps


def replay(bytes_map: Mapping[str, bytes], dest_root: Path) -> ThemeStore:
    """5 authority を file ごとの物理順で消費し、依存が満たされた先頭から契約順（宣言先行・物理先行）に append する。
    root id を含む全 id は bytes のものをそのまま使う（再生成しない）。"""
    records = records_from_bytes(bytes_map)
    queues = {name: list(records[name]) for name in LOAD_ORDER}
    appended: set = set()
    store = ThemeStore.initialize(dest_root)
    append = {"roots": store.append_root, "observations": store.append_observation, "governance": store.append_governance,
              "metadata": store.append_metadata, "mappings": store.append_mapping}
    while any(queues.values()):
        progressed = False
        for name in LOAD_ORDER:
            if not queues[name]:
                continue
            head = queues[name][0]
            if _dependencies(name, head, records) <= appended:
                append[name](head)
                appended.add(getattr(head, _ID_FIELDS[name]))
                queues[name].pop(0)
                progressed = True
                break
        if not progressed:
            raise AssertionError("replay deadlock: no authority head is appendable "
                                 + str({n: len(q) for n, q in queues.items()}))
    return store


def copy_world(src_root: Path, dest_root: Path) -> Path:
    shutil.copytree(src_root / "themes", dest_root / "themes")
    return dest_root


# ---------------------------------------------------------------- digest（restart / replay 比較用の JSON 化）

def resolution_digest(res: ThemeResolution) -> dict:
    return {
        "status": res.status.value,
        "root": None if res.root is None else res.root.root_id,
        "observation": None if res.observation is None else res.observation.observation_id,
        "visible": None if res.evidence is None else [a.attachment_key for a in res.evidence.visible],
        "not_yet_attached": None if res.evidence is None else list(res.evidence.not_yet_attached),
        "context_without_time": None if res.evidence is None else [a.attachment_key for a in res.evidence.context_without_time],
        "qualification": None if res.derived is None else {
            "status": res.derived.qualification.status.value,
            "origins": res.derived.qualification.independent_origins,
            "dates": list(res.derived.qualification.evidence_dates),
            "counted": list(res.derived.qualification.counted_attachment_keys),
            "diagnostics": list(res.derived.qualification.diagnostics),
            "core": res.derived.identity_core_fingerprint, "semantic": res.derived.semantic_fingerprint,
            "links": [(l.entity.value, list(l.ref_ids)) for l in res.derived.directly_evidenced_links],
            "contradicting": res.derived.has_contradicting_evidence, "invalidating": res.derived.has_invalidating_evidence},
        "governance": {"status": res.governance.status.value, "chain": list(res.governance.chain),
                       "terminal": res.governance.terminal_event_id, "effective": res.governance.effective_event_id,
                       "effective_type": None if res.governance.effective_event_type is None else res.governance.effective_event_type.value,
                       "reversed": list(res.governance.reversed_event_ids),
                       "diagnostics": [d.kind for d in res.governance.diagnostics]},
        "metadata": {m.field.value: {"status": m.status.value, "record": m.record_id, "value": list(m.value),
                                     "diagnostics": [d.kind for d in m.diagnostics]} for m in res.metadata},
        "mapping": {"status": res.mapping.status.value, "terminals": list(res.mapping.terminal_mapping_ids),
                    "diagnostics": [d.kind for d in res.mapping.diagnostics]},
        "lineage": [(l.kind.value, l.event_id, list(l.related_roots)) for l in res.lineage],
        "carried": [(c.attachment_key, c.source_observation_id, c.source_root_id, c.origin_event_id) for c in res.carried],
        "pending": [(p.kind, p.subject_id, list(p.missing)) for p in res.pending],
        "diagnostics": [(d.kind, d.facet, d.subject_id) for d in res.diagnostics],
        "dereference": [(d.ref_id, d.status.value) for d in res.dereference],
    }


def knowable_digest(res: ThemeResolution) -> dict:
    """future leakage 比較用: state facet はそのまま、NO_STATE の理由 kind（UNKNOWN_ROOT / ROOT_AFTER_CUTOFF。
    A3 §13 が区別する診断）だけを同一視する。"""
    digest = resolution_digest(res)
    digest["diagnostics"] = [("NO_ROOT_AT_CUTOFF" if kind in ("UNKNOWN_ROOT", "ROOT_AFTER_CUTOFF") else kind, facet, subject)
                             for kind, facet, subject in digest["diagnostics"]]
    return digest
