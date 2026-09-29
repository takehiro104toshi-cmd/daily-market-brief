"""P6-A4b — ThemeStore: 初期化 / read-only load / 追記専用 bytes / 冪等と conflict / chain 規則 / lookup / API 表面。

fixture builder は test_theme_model から import。crash 補助（interrupt_after）は store_operations test と共有する。
"""
from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.themes import store as S
from src.intelligence.themes.model import (
    EvidenceKind, EvidenceRole, GovernanceEventType, MetadataField, ProvenanceClass, ThemeObservation, canonical_line,
)
from src.intelligence.themes.revision import revise_observation
from src.intelligence.themes.store import (
    AUTHORITY_FILENAMES, LOAD_ORDER, AppendStatus, ConcurrentModificationDetected, FailureCategory, PendingKind,
    ThemeAppendRejected, ThemeConflict, ThemeStore, ThemeStoreCorrupt, ThemeStoreError,
)
from tests.intelligence.test_theme_model import (
    FACT_A, FACT_B, ROOT_A, ROOT_B, T0, attachment, event, limitation, mapping, metadata, observation, provenance,
    root_record,
)

GOV_1 = "thgov_" + "1" * 24
META_1 = "thmeta_" + "1" * 24
MAP_1 = "thmap_" + "1" * 24


class SimulatedCrash(RuntimeError):
    pass


def interrupt_after(store: ThemeStore, allowed_writes: int) -> None:
    """allowed_writes 回の物理 write の後、次の write で crash を模擬する（append は途中で止まる）。"""
    real = store._write_line
    state = {"n": 0}

    def crashing(authority, line):
        if state["n"] >= allowed_writes:
            raise SimulatedCrash(f"crash before write #{state['n'] + 1}")
        state["n"] += 1
        real(authority, line)

    store._write_line = crashing  # type: ignore[method-assign]


def seeded(tmp_path: Path):
    """初期化済み store に candidate root A（root ＋ genesis）を入れて返す。"""
    store = ThemeStore.initialize(tmp_path)
    obs = observation()
    root = root_record(obs)
    store.append_root(root)
    store.append_observation(obs)
    return store, root, obs


def rejected(code: str):
    return pytest.raises(ThemeAppendRejected, match=f"APPEND_REJECTED/{code}")


def file_bytes(store: ThemeStore, name: str) -> bytes:
    return store.paths[name].read_bytes()


# ---------------------------------------------------------------- initialization / read-only

def test_initialize_creates_five_empty_authorities_under_explicit_data_root(tmp_path: Path) -> None:
    store = ThemeStore.initialize(tmp_path)
    base = tmp_path / "themes"
    assert base.is_dir()
    assert {p.name for p in base.iterdir()} == set(AUTHORITY_FILENAMES.values()) == {
        "theme_roots.jsonl", "theme_observations.jsonl", "theme_governance.jsonl", "theme_metadata.jsonl",
        "theme_series_mappings.jsonl"}
    assert all(p.stat().st_size == 0 for p in base.iterdir())
    assert store.counts() == {n: 0 for n in LOAD_ORDER} and LOAD_ORDER == ("roots", "observations", "governance",
                                                                           "metadata", "mappings")
    again = ThemeStore.initialize(tmp_path)   # 冪等。既存 file に触らない
    assert again.counts() == store.counts() and all(p.stat().st_size == 0 for p in base.iterdir())


def test_open_never_creates_and_requires_initialization(tmp_path: Path) -> None:
    with pytest.raises(ThemeStoreError) as info:
        ThemeStore.open(tmp_path)
    assert info.value.category is FailureCategory.NOT_INITIALIZED and not (tmp_path / "themes").exists()
    ThemeStore.initialize(tmp_path)
    (tmp_path / "themes" / "theme_metadata.jsonl").unlink()
    with pytest.raises(ThemeStoreCorrupt, match="AUTHORITY_MISSING") as info2:
        ThemeStore.open(tmp_path)
    assert info2.value.authority == "metadata" and not (tmp_path / "themes" / "theme_metadata.jsonl").exists()


def test_explicit_data_root_required_and_no_repository_fallback() -> None:
    with pytest.raises(ValueError):
        S.themes_dir("")
    with pytest.raises(ValueError):
        ThemeStore.initialize("")
    with pytest.raises(TypeError):
        ThemeStore("/somewhere")  # type: ignore[call-arg]
    source = (Path(S.__file__)).read_text(encoding="utf-8")
    assert "core.paths" not in source and "data/vnext" not in source and "theme_learning" not in source
    assert "INTELLIGENCE_DATA_ROOT" not in source


def test_read_only_open_and_audit_do_not_write(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    store.append_root(root_record(observation(root_id=ROOT_B)))   # PENDING_GENESIS を残す
    before = {n: file_bytes(store, n) for n in LOAD_ORDER}
    ro = ThemeStore.open(tmp_path, read_only=True)
    with pytest.raises(ThemeStoreError) as info:
        ro.append_metadata(metadata())
    assert info.value.category is FailureCategory.READ_ONLY
    audit = ThemeStore.audit(tmp_path)
    assert audit.counts == {"roots": 2, "observations": 1, "governance": 0, "metadata": 0, "mappings": 0}
    assert [p.kind for p in audit.pending] == [PendingKind.PENDING_GENESIS] and audit.diagnostics == ()
    assert {n: file_bytes(store, n) for n in LOAD_ORDER} == before


# ---------------------------------------------------------------- append bytes / idempotency / conflict

def test_append_writes_exact_canonical_line_with_flush_and_fsync(tmp_path: Path, monkeypatch) -> None:
    calls = []
    real_fsync = os.fsync
    monkeypatch.setattr(S.os, "fsync", lambda fd: (calls.append(fd), real_fsync(fd)))
    store = ThemeStore.initialize(tmp_path)
    obs = observation()
    root = root_record(obs)
    result = store.append_root(root)
    assert result.status is AppendStatus.APPENDED and result.wrote_line and result.line_number == 1
    assert file_bytes(store, "roots") == canonical_line(root).encode("utf-8")
    store.append_observation(obs)
    assert file_bytes(store, "observations") == canonical_line(obs).encode("utf-8")
    assert len(calls) >= 2
    line = file_bytes(store, "observations").decode("utf-8")
    assert line.endswith("\n") and json.loads(line) == obs.as_dict()


def test_exact_idempotency_same_id_same_bytes(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    before = file_bytes(store, "observations")
    again = store.append_observation(ThemeObservation.from_dict(json.loads(canonical_line(obs))))
    assert again.status is AppendStatus.ALREADY_PRESENT and not again.wrote_line and again.line_number == 1
    assert store.append_root(root).status is AppendStatus.ALREADY_PRESENT
    assert file_bytes(store, "observations") == before and store.counts()["observations"] == 1


def test_same_id_different_bytes_is_conflict_even_for_non_identity_fields(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    before = {n: file_bytes(store, n) for n in LOAD_ORDER}
    with pytest.raises(ThemeConflict) as info:
        store.append_observation(observation(provenance=provenance(reason="different reason")))
    assert info.value.differing_fields == ("provenance",) and info.value.category is FailureCategory.CONFLICT
    with pytest.raises(ThemeConflict) as info2:
        store.append_observation(observation(recorded_at=obs.recorded_at + timedelta(minutes=5)))
    assert info2.value.differing_fields == ("recorded_at",)
    with pytest.raises(ThemeConflict) as info3:
        store.append_root(root_record(obs, created_at=T0 - timedelta(hours=1)))
    assert info3.value.differing_fields == ("created_at",)
    assert {n: file_bytes(store, n) for n in LOAD_ORDER} == before   # 上書きも追記も無い


def test_append_rejects_wrong_record_type(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    with rejected("INVALID_TYPE"):
        store.append_root(obs)  # type: ignore[arg-type]
    with rejected("INVALID_TYPE"):
        store.append_observation(root)  # type: ignore[arg-type]


# ---------------------------------------------------------------- root / genesis

def test_root_before_genesis_is_pending_then_completed(tmp_path: Path) -> None:
    store = ThemeStore.initialize(tmp_path)
    obs = observation()
    root = root_record(obs)
    store.append_root(root)
    pending = store.pending()
    assert [(p.kind, p.subject_id, p.missing) for p in pending] == [(PendingKind.PENDING_GENESIS, ROOT_A,
                                                                    (obs.observation_id,))]
    reopened = ThemeStore.open(tmp_path)
    assert reopened.pending() == pending and reopened.counts()["observations"] == 0   # load は補完しない
    assert store.append_observation(obs).status is AppendStatus.APPENDED
    assert store.pending() == ()


def test_genesis_validation(tmp_path: Path) -> None:
    store = ThemeStore.initialize(tmp_path)
    obs = observation()
    with rejected("ROOT_NOT_FOUND"):
        store.append_observation(obs)
    store.append_root(root_record(obs))
    with rejected("GENESIS_MISMATCH"):
        store.append_observation(observation(limitations=()))
    early = observation(attachments=(), recorded_at=T0 - timedelta(hours=1))
    store.append_root(root_record(early, root_id=ROOT_B))
    with rejected("OBSERVATION_BEFORE_ROOT"):
        store.append_observation(early)


# ---------------------------------------------------------------- predecessor rules

def test_predecessor_rules(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    later = obs.recorded_at + timedelta(hours=1)
    with rejected("DANGLING_PREDECESSOR"):
        store.append_observation(observation(previous_observation_id="thobs_" + "1" * 24, recorded_at=later))
    obs_b = observation(root_id=ROOT_B)
    store.append_root(root_record(obs_b))
    store.append_observation(obs_b)
    wrong_root = ThemeObservation.build(
        root_id=ROOT_A, previous_observation_id=obs_b.observation_id, subject=obs.subject, mechanism=obs.mechanism,
        certainty_class=obs.certainty_class, scope=obs.scope, limitations=(), invalidation_conditions=obs.invalidation_conditions,
        attachments=obs.attachments, provenance=provenance(), recorded_at=later)
    with rejected("WRONG_ROOT_PREDECESSOR"):
        store.append_observation(wrong_root)
    second = revise_observation(obs, recorded_at=later, provenance=provenance(), limitations=())
    assert store.append_observation(second).status is AppendStatus.APPENDED
    assert store.physical_terminal_observations(ROOT_A) == (second.observation_id,)
    fork = revise_observation(obs, recorded_at=later, provenance=provenance(), limitations=(limitation("z"),))
    with rejected("NON_TERMINAL_PREDECESSOR"):
        store.append_observation(fork)
    earlier = ThemeObservation.build(
        root_id=ROOT_A, previous_observation_id=second.observation_id, subject=obs.subject, mechanism=obs.mechanism,
        certainty_class=obs.certainty_class, scope=obs.scope, limitations=(), invalidation_conditions=obs.invalidation_conditions,
        attachments=obs.attachments, provenance=provenance(), recorded_at=obs.recorded_at)
    with rejected("NON_MONOTONIC_RECORDED_AT"):
        store.append_observation(earlier)
    assert store.counts()["observations"] == 3


def test_attached_at_bounds_relative_to_root(tmp_path: Path) -> None:
    store = ThemeStore.initialize(tmp_path)
    early_attachment = attachment(FACT_A, attached=T0 - timedelta(days=1), day="2026-08-20")
    obs = observation(attachments=(early_attachment,))
    store.append_root(root_record(obs))
    with rejected("ATTACHED_AT_OUT_OF_RANGE"):
        store.append_observation(obs)


# ---------------------------------------------------------------- metadata / mapping chains

def test_metadata_chain_rules(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    with rejected("ROOT_NOT_FOUND"):
        store.append_metadata(metadata(root_id=ROOT_B))
    with rejected("METADATA_PREDECESSOR_MISSING"):
        store.append_metadata(metadata(previous_metadata_id=META_1))
    with rejected("GOVERNANCE_REFERENCE_MISSING"):
        store.append_metadata(metadata(governance_event_id=GOV_1))
    with rejected("NON_MONOTONIC_RECORDED_AT"):
        store.append_metadata(metadata(recorded_at=T0 - timedelta(hours=1)))
    first = metadata()
    store.append_metadata(first)
    with rejected("MISSING_PREVIOUS_METADATA"):
        store.append_metadata(metadata(value=("Second",)))
    with rejected("METADATA_PREDECESSOR_MISSING"):
        store.append_metadata(metadata(field=MetadataField.ALIAS, value=("x",), previous_metadata_id=first.metadata_id))
    with rejected("NON_MONOTONIC_RECORDED_AT"):
        store.append_metadata(metadata(value=("Second",), previous_metadata_id=first.metadata_id,
                                       recorded_at=T0 - timedelta(minutes=1)))
    second = metadata(value=("Second",), previous_metadata_id=first.metadata_id, recorded_at=T0 + timedelta(days=1))
    store.append_metadata(second)
    with rejected("NON_TERMINAL_PREDECESSOR"):
        store.append_metadata(metadata(value=("Third",), previous_metadata_id=first.metadata_id,
                                       recorded_at=T0 + timedelta(days=2)))
    assert store.physical_terminal_metadata(ROOT_A, MetadataField.LABEL) == (second.metadata_id,)
    assert [m.metadata_id for m in store.metadata_for_root(ROOT_A, MetadataField.LABEL)] == [first.metadata_id,
                                                                                            second.metadata_id]
    assert store.get_observation(obs.observation_id) == obs   # metadata は observation を変えない


def test_mapping_chain_rules(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    with rejected("ROOT_NOT_FOUND"):
        store.append_mapping(mapping(root_id=ROOT_B))
    with rejected("MAPPING_CONSEQUENCE_UNKNOWN"):
        store.append_mapping(mapping(consequence_ref="c9"))
    with rejected("MAPPING_PREDECESSOR_MISSING"):
        store.append_mapping(mapping(supersedes_mapping_id=MAP_1))
    with rejected("NON_MONOTONIC_RECORDED_AT"):
        store.append_mapping(mapping(recorded_at=T0 - timedelta(hours=1), valid_from=T0 - timedelta(hours=1)))
    first = mapping()
    store.append_mapping(first)
    second = mapping(series_ref="fx:USDJPY.close.closing.tokyo", supersedes_mapping_id=first.mapping_id,
                     recorded_at=T0 + timedelta(days=1))
    store.append_mapping(second)
    with rejected("NON_TERMINAL_PREDECESSOR"):
        store.append_mapping(mapping(series_ref="other", supersedes_mapping_id=first.mapping_id,
                                     recorded_at=T0 + timedelta(days=2)))
    obs_b = observation(root_id=ROOT_B)
    store.append_root(root_record(obs_b))
    store.append_observation(obs_b)
    with rejected("MAPPING_PREDECESSOR_MISSING"):
        store.append_mapping(mapping(root_id=ROOT_B, supersedes_mapping_id=second.mapping_id,
                                     recorded_at=T0 + timedelta(days=3)))
    assert [m.mapping_id for m in store.mappings_for_root(ROOT_A)] == [first.mapping_id, second.mapping_id]
    assert store.get_observation(obs.observation_id) == obs


# ---------------------------------------------------------------- governance references

def test_governance_physical_references(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    with rejected("GOVERNANCE_REFERENCE_MISSING"):
        store.append_governance(event(subject_roots=(ROOT_B,)))
    with rejected("GOVERNANCE_REFERENCE_MISSING"):
        store.append_governance(event(related_observations=("thobs_" + "2" * 24,)))
    with rejected("GOVERNANCE_REFERENCE_MISSING"):
        store.append_governance(event(previous_event_ids=((ROOT_A, GOV_1),)))
    with rejected("GOVERNANCE_REFERENCE_MISSING"):
        store.append_governance(event(event_type=GovernanceEventType.EVENT_REVERSED, reverses_event_id=GOV_1))
    with rejected("NON_MONOTONIC_RECORDED_AT"):
        store.append_governance(event(related_observations=(obs.observation_id,), recorded_at=T0))
    with rejected("NON_MONOTONIC_RECORDED_AT"):
        store.append_governance(event(recorded_at=T0 - timedelta(hours=1)))
    obs_b = observation(root_id=ROOT_B)
    store.append_root(root_record(obs_b))
    store.append_observation(obs_b)
    with rejected("GOVERNANCE_REFERENCE_MISSING"):
        store.append_governance(event(related_observations=(obs_b.observation_id,)))   # 別 root の observation
    accepted = event(related_observations=(obs.observation_id,))
    store.append_governance(accepted)
    assert store.physical_terminal_events(ROOT_A) == (accepted.event_id,)
    with rejected("MISSING_PREVIOUS_EVENT"):
        store.append_governance(event(event_type=GovernanceEventType.RETIRED, reason="retire"))
    retired = event(event_type=GovernanceEventType.RETIRED, reason="retire",
                    previous_event_ids=((ROOT_A, accepted.event_id),), recorded_at=T0 + timedelta(days=2))
    store.append_governance(retired)
    with rejected("NON_TERMINAL_PREDECESSOR"):
        store.append_governance(event(event_type=GovernanceEventType.REOPENED, reason="reopen",
                                      previous_event_ids=((ROOT_A, accepted.event_id),),
                                      recorded_at=T0 + timedelta(days=3)))
    with rejected("MALFORMED_REVERSAL"):
        store.append_governance(event(event_type=GovernanceEventType.EVENT_REVERSED, subject_roots=(ROOT_B,),
                                      reverses_event_id=retired.event_id, reason="oops",
                                      recorded_at=T0 + timedelta(days=3)))
    reversal = event(event_type=GovernanceEventType.EVENT_REVERSED, reverses_event_id=retired.event_id, reason="oops",
                     previous_event_ids=((ROOT_A, retired.event_id),), recorded_at=T0 + timedelta(days=3))
    store.append_governance(reversal)
    assert store.physical_terminal_events(ROOT_A) == (reversal.event_id,)
    assert [e.event_id for e in store.events_for_root(ROOT_A)] == [accepted.event_id, retired.event_id,
                                                                    reversal.event_id]


def test_result_roots_are_declared_before_they_exist(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    obs_b = observation(root_id=ROOT_B)
    store.append_root(root_record(obs_b))
    store.append_observation(obs_b)
    with rejected("RESULT_ROOT_ALREADY_EXISTS"):
        store.append_governance(event(event_type=GovernanceEventType.SUPERSEDED_BY_ROOT, subject_roots=(ROOT_A,),
                                      result_roots=(ROOT_B,)))


# ---------------------------------------------------------------- reload / lookups / API surface

def test_reload_preserves_bytes_and_records(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    second = revise_observation(obs, recorded_at=obs.recorded_at + timedelta(hours=1), provenance=provenance(),
                                attachments=obs.attachments + (attachment("doc_" + "9" * 24, EvidenceKind.SOURCE_DOCUMENT,
                                                                          role=EvidenceRole.CONTRADICTS,
                                                                          attached=obs.recorded_at + timedelta(hours=1)),))
    store.append_observation(second)
    store.append_metadata(metadata())
    store.append_mapping(mapping())
    store.append_governance(event(related_observations=(second.observation_id,)))
    before = {n: file_bytes(store, n) for n in LOAD_ORDER}
    reopened = ThemeStore.open(tmp_path)
    assert reopened.counts() == store.counts() == {"roots": 1, "observations": 2, "governance": 1, "metadata": 1,
                                                    "mappings": 1}
    assert {n: file_bytes(reopened, n) for n in LOAD_ORDER} == before
    assert reopened.get_root(ROOT_A) == root and reopened.get_observation(second.observation_id) == second
    assert reopened.canonical_lines("observations") == (canonical_line(obs), canonical_line(second))
    assert reopened.observations_for_root(ROOT_A) == (obs, second)
    assert reopened.get_root("theme_0123456789ABCDEFGHJKMNPQRW") is None


def test_collection_order_independence_at_the_store_boundary(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    reordered = observation(attachments=tuple(reversed(obs.attachments)), scope=tuple(reversed(obs.scope)))
    assert store.append_observation(reordered).status is AppendStatus.ALREADY_PRESENT


def test_single_writer_claim_matches_implementation(tmp_path: Path) -> None:
    assert S.WRITER_GUARANTEE == "SINGLE_WRITER"
    store, root, obs = seeded(tmp_path)
    other = ThemeStore.open(tmp_path)              # 第 2 の writer（保証外の使い方）
    other.append_metadata(metadata())
    with pytest.raises(ConcurrentModificationDetected) as info:
        store.append_metadata(metadata(value=("B",)))
    assert info.value.authority == "metadata" and info.value.category is FailureCategory.CONCURRENT_MODIFICATION
    assert "lock" not in S.ThemeStore.__doc__.lower() or "ではない" in S.__doc__
    store.reload()                                  # 明示の reload だけが外部変化を取り込む
    assert store.counts()["metadata"] == 1


def test_no_resolver_or_latest_api(tmp_path: Path) -> None:
    names = {n for n in dir(ThemeStore) if not n.startswith("_")}
    for forbidden in ("resolve_theme", "state_at", "current_theme", "latest_theme", "active_theme", "governance_state",
                      "metadata_at", "mapping_at", "latest", "current", "resolve"):
        assert forbidden not in names
    assert not [n for n in names if "latest" in n or "current" in n or "resolve" in n or "state" in n]
    assert {"append_root", "append_observation", "append_governance", "append_metadata", "append_mapping",
            "get_root", "get_observation", "get_governance_event", "get_metadata", "get_mapping", "pending",
            "diagnostics", "verify_unchanged", "reload", "initialize", "open", "audit", "counts",
            "physical_terminal_observations", "physical_terminal_events", "physical_terminal_metadata"} <= names
    source = Path(S.__file__).read_text(encoding="utf-8")
    assert "sqlite" not in source.lower() and "def append_json" not in source
