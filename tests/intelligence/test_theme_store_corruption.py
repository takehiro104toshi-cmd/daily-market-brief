"""P6-A4b — STORE_CORRUPTION / INVALID_HISTORY / PENDING / 外部改変 / fork 診断の区別（潰さない・直さない・skip しない）。"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.themes.model import CreationMethod, ThemeObservation, canonical_line
from src.intelligence.themes.revision import revise_observation
from src.intelligence.themes.store import (
    ConcurrentModificationDetected, FailureCategory, PendingKind, ThemeAppendRejected, ThemeInvalidHistory, ThemeStore,
    ThemeStoreCorrupt,
)
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B, T0, limitation, metadata, observation, provenance, root_record
from tests.intelligence.test_theme_store import file_bytes, seeded

GOV_1 = "thgov_" + "1" * 24


def write(store: ThemeStore, name: str, text: str, *, append: bool = False) -> None:
    path = store.paths[name]
    mode = "ab" if append else "wb"
    with path.open(mode) as handle:
        handle.write(text.encode("utf-8"))


def corrupt(tmp_path: Path, reason: str, *, authority: str, line_number: int):
    with pytest.raises(ThemeStoreCorrupt) as info:
        ThemeStore.open(tmp_path)
    assert info.value.code == reason and info.value.authority == authority and info.value.line_number == line_number
    assert info.value.category is FailureCategory.STORE_CORRUPTION
    return info.value


def invalid(tmp_path: Path, reason: str, *, authority: str, line_number: int):
    with pytest.raises(ThemeInvalidHistory) as info:
        ThemeStore.open(tmp_path)
    assert info.value.code == reason and info.value.authority == authority and info.value.line_number == line_number
    assert info.value.category is FailureCategory.INVALID_HISTORY
    return info.value


# ---------------------------------------------------------------- STORE_CORRUPTION

def test_malformed_json_fails_closed_with_location(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    write(store, "observations", '{"not json"\n', append=True)
    corrupt(tmp_path, "MALFORMED_JSON", authority="observations", line_number=2)


def test_noncanonical_json_is_rejected_even_when_semantically_equal(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    pretty = json.dumps(root.as_dict(), ensure_ascii=False, indent=1) + "\n"   # 複数行 → 1 行目が JSON でない
    write(store, "roots", pretty)
    corrupt(tmp_path, "MALFORMED_JSON", authority="roots", line_number=1)
    reordered = dict(reversed(list(root.as_dict().items())))
    unsorted = json.dumps(reordered, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"
    assert unsorted != canonical_line(root) and json.loads(unsorted) == root.as_dict()
    write(store, "roots", unsorted)
    corrupt(tmp_path, "NON_CANONICAL_LINE", authority="roots", line_number=1)
    spaced = canonical_line(root).replace('":"', '": "', 1)
    write(store, "roots", spaced)
    corrupt(tmp_path, "NON_CANONICAL_LINE", authority="roots", line_number=1)


def test_unsupported_schema_id_mismatch_unknown_field_and_bad_vocabulary(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    data = json.loads(canonical_line(root))
    data["schema_version"] = "theme_root:9.0.0"
    write(store, "roots", json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    corrupt(tmp_path, "UNSUPPORTED_SCHEMA_VERSION", authority="roots", line_number=1)
    data = json.loads(canonical_line(obs))
    data["observation_id"] = "thobs_" + "0" * 24
    write(store, "roots", canonical_line(root))
    write(store, "observations", json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    error = corrupt(tmp_path, "INVALID_RECORD", authority="observations", line_number=1)
    assert "IDENTITY_MISMATCH" in error.detail
    data = json.loads(canonical_line(obs))
    data["label"] = "sneaky"
    write(store, "observations", json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    assert "UNKNOWN_FIELDS" in corrupt(tmp_path, "INVALID_RECORD", authority="observations", line_number=1).detail
    data = json.loads(canonical_line(obs))
    data["certainty_class"] = "PROBABLY"
    write(store, "observations", json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    assert "INVALID_VOCABULARY" in corrupt(tmp_path, "INVALID_RECORD", authority="observations", line_number=1).detail


def test_partial_blank_non_object_and_encoding_failures(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    write(store, "observations", canonical_line(obs)[:-1])                 # 終端改行なし
    corrupt(tmp_path, "TRUNCATED_FINAL_LINE", authority="observations", line_number=1)
    write(store, "observations", canonical_line(obs) + "\n")               # 空行
    corrupt(tmp_path, "BLANK_LINE", authority="observations", line_number=2)
    write(store, "observations", canonical_line(obs) + "[1,2]\n")          # object でない
    corrupt(tmp_path, "NOT_AN_OBJECT", authority="observations", line_number=2)
    store.paths["observations"].write_bytes(b"\xff\xfe" + canonical_line(obs).encode("utf-8"))
    corrupt(tmp_path, "INVALID_ENCODING", authority="observations", line_number=0)


def test_physical_duplicates(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    write(store, "roots", canonical_line(root), append=True)
    corrupt(tmp_path, "PHYSICAL_DUPLICATE_IDENTICAL", authority="roots", line_number=2)
    other = root_record(obs, created_at=T0 - timedelta(hours=1))
    write(store, "roots", canonical_line(root) + canonical_line(other))
    corrupt(tmp_path, "PHYSICAL_DUPLICATE_CONFLICTING", authority="roots", line_number=2)


def test_corrupt_lines_are_never_skipped(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    second = revise_observation(obs, recorded_at=obs.recorded_at + timedelta(hours=1), provenance=provenance(),
                                limitations=())
    write(store, "observations", canonical_line(obs) + "garbage\n" + canonical_line(second))
    corrupt(tmp_path, "MALFORMED_JSON", authority="observations", line_number=2)   # 3 行目が valid でも store は開かない
    assert store.paths["observations"].read_bytes().count(b"\n") == 3               # 何も書き換えていない


# ---------------------------------------------------------------- 外部改変検知

def test_external_growth_and_shrink_are_detected(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    write(store, "metadata", canonical_line(metadata()), append=True)     # 外部 writer の追記
    with pytest.raises(ConcurrentModificationDetected) as info:
        store.append_metadata(metadata(value=("B",)))
    assert info.value.authority == "metadata" and info.value.expected == 0 and info.value.actual > 0
    with pytest.raises(ConcurrentModificationDetected):
        store.verify_unchanged()
    store.reload()
    store.verify_unchanged()
    store.paths["observations"].write_bytes(b"")                          # 外部 truncate
    with pytest.raises(ConcurrentModificationDetected) as info2:
        store.append_metadata(metadata(value=("B",), previous_metadata_id=metadata().metadata_id,
                                       recorded_at=T0 + timedelta(days=1)))
    assert info2.value.authority == "observations" and info2.value.actual == 0


# ---------------------------------------------------------------- INVALID_HISTORY（個々は valid、履歴として不可能）

def test_genesis_without_root_is_invalid_history(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    write(store, "roots", "")
    invalid(tmp_path, "ROOT_NOT_FOUND", authority="observations", line_number=1)


def test_second_mismatching_genesis_and_wrong_root_predecessor(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    other_genesis = observation(limitations=())
    write(store, "observations", canonical_line(obs) + canonical_line(other_genesis))
    invalid(tmp_path, "GENESIS_MISMATCH", authority="observations", line_number=2)
    obs_b = observation(root_id=ROOT_B)
    write(store, "roots", canonical_line(root) + canonical_line(root_record(obs_b)))
    cross = ThemeObservation.build(
        root_id=ROOT_A, previous_observation_id=obs_b.observation_id, subject=obs.subject, mechanism=obs.mechanism,
        certainty_class=obs.certainty_class, scope=obs.scope, limitations=(), invalidation_conditions=obs.invalidation_conditions,
        attachments=obs.attachments, provenance=provenance(), recorded_at=obs.recorded_at + timedelta(hours=1))
    write(store, "observations", canonical_line(obs) + canonical_line(obs_b) + canonical_line(cross))
    invalid(tmp_path, "WRONG_ROOT_PREDECESSOR", authority="observations", line_number=3)


def test_result_root_without_declaring_event_is_invalid_history(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    orphan = root_record(observation(root_id=ROOT_B), creation_method=CreationMethod.MERGE_RESULT, origin_event_id=GOV_1)
    write(store, "roots", canonical_line(root) + canonical_line(orphan))
    invalid(tmp_path, "ORIGIN_EVENT_MISSING", authority="roots", line_number=2)


def test_metadata_predecessor_missing_at_load(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    write(store, "metadata", canonical_line(metadata(previous_metadata_id="thmeta_" + "1" * 24)))
    invalid(tmp_path, "METADATA_PREDECESSOR_MISSING", authority="metadata", line_number=1)


# ---------------------------------------------------------------- fork on disk: 選ばない・直さない

def test_fork_on_disk_is_diagnosed_not_resolved(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    later = obs.recorded_at + timedelta(hours=1)
    left = revise_observation(obs, recorded_at=later, provenance=provenance(), limitations=())
    right = revise_observation(obs, recorded_at=later, provenance=provenance(), limitations=(limitation("z"),))
    store.append_observation(left)
    write(store, "observations", canonical_line(right), append=True)   # writer を迂回した fork
    before = file_bytes(store, "observations")
    reopened = ThemeStore.open(tmp_path)
    diagnostics = reopened.diagnostics()
    assert [(d.kind, d.root_id, d.subject_id) for d in diagnostics] == [("FORK", ROOT_A, obs.observation_id)]
    assert set(diagnostics[0].children) == {left.observation_id, right.observation_id}
    assert set(reopened.physical_terminal_observations(ROOT_A)) == {left.observation_id, right.observation_id}
    assert reopened.get_observation(left.observation_id) == left and reopened.get_observation(right.observation_id) == right
    with pytest.raises(ThemeAppendRejected, match="FORKED_ROOT"):
        reopened.append_observation(revise_observation(left, recorded_at=later + timedelta(hours=1),
                                                       provenance=provenance(), limitations=(limitation("q"),)))
    assert file_bytes(reopened, "observations") == before


def test_failure_categories_are_distinct_and_pending_is_not_an_error(tmp_path: Path) -> None:
    assert {c.value for c in FailureCategory} == {"STORE_CORRUPTION", "INVALID_HISTORY", "APPEND_REJECTED", "CONFLICT",
                                                  "CONCURRENT_MODIFICATION", "NOT_INITIALIZED", "READ_ONLY"}
    assert ThemeStoreCorrupt.category is not ThemeInvalidHistory.category
    store = ThemeStore.initialize(tmp_path)
    obs = observation()
    store.append_root(root_record(obs))
    before = file_bytes(store, "roots")
    reopened = ThemeStore.open(tmp_path)                                # 例外なし
    assert reopened.pending()[0].kind is PendingKind.PENDING_GENESIS
    assert file_bytes(reopened, "roots") == before and file_bytes(reopened, "observations") == b""
    with pytest.raises(ValueError):
        ThemeStoreCorrupt("NOT_A_REASON", authority="roots", line_number=1)
