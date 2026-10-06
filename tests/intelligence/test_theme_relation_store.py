"""P6-B5B — relation store の永続化規律と B5B の境界（matrix 29〜39, 59〜65）。

追記専用・canonical 行のみ・冪等・衝突は fail closed・破損は読み飛ばさず修復しない。
Foundation / B3 / B4 のどの authority も触らない。
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.relation_model import (RELATION_ASSERTION_SCHEMA_VERSION,
                                                                canonical_relation_line)
from src.intelligence.theme_intelligence.relation_resolution import (RelationResolutionStatus,
                                                                     endpoint_lookup_from_roots)
from src.intelligence.theme_intelligence.relation_store import (AUTHORITY_FILENAMES, AppendStatus,
                                                                RelationAppendRejected, RelationConcurrentModification,
                                                                RelationConflict, RelationStoreCorrupt,
                                                                ThemeRelationStore, WRITER_GUARANTEE, authority_paths,
                                                                relations_dir, resolve_relations_at_data_root)
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_relation import A, B, ACTOR, T0, assertion, causal, retraction

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
B5B_MODULES = ("relation_model", "relation_resolution", "relation_graph", "relation_store")
PURE_MODULES = ("relation_model", "relation_resolution", "relation_graph")


def store_at(tmp_path: Path) -> ThemeRelationStore:
    return ThemeRelationStore.initialize(tmp_path / "data")


def corrupt(tmp_path: Path, text: str, *, authority: str = "assertions", binary: bytes = None) -> Path:
    path = authority_paths(tmp_path / "data")[authority]
    if binary is not None:
        path.write_bytes(binary)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def expect_corrupt(tmp_path: Path, reason: str) -> None:
    with pytest.raises(RelationStoreCorrupt) as info:
        ThemeRelationStore.open(tmp_path / "data")
    assert info.value.code == reason, info.value.code


# ---------------------------------------------------------------- 29〜32 基本


def test_29_initialize_creates_exactly_two_empty_authorities(tmp_path) -> None:
    store = store_at(tmp_path)
    assert store.counts() == {"assertions": 0, "governance": 0}
    directory = relations_dir(tmp_path / "data")
    assert sorted(p.name for p in directory.iterdir()) == sorted(AUTHORITY_FILENAMES.values())
    assert all(p.read_bytes() == b"" for p in store.paths.values())
    assert WRITER_GUARANTEE == "SINGLE_WRITER"
    assert not (tmp_path / "data" / "themes").exists()


def test_30_a_read_only_store_refuses_to_append(tmp_path) -> None:
    store_at(tmp_path)
    reader = ThemeRelationStore.open(tmp_path / "data", read_only=True)
    with pytest.raises(RelationAppendRejected) as info:
        reader.append_assertion(assertion())
    assert info.value.code == "READ_ONLY"
    with pytest.raises(RelationAppendRejected) as info:
        ThemeRelationStore.open("")
    assert info.value.code == "DATA_ROOT_REQUIRED"


def test_31_the_identical_record_is_idempotent(tmp_path) -> None:
    store = store_at(tmp_path)
    record = assertion()
    assert store.append_assertion(record).status is AppendStatus.APPENDED
    before = store.paths["assertions"].read_bytes()
    assert store.append_assertion(record).status is AppendStatus.ALREADY_PRESENT
    assert store.paths["assertions"].read_bytes() == before and store.counts()["assertions"] == 1


def test_32_the_same_identity_with_different_bytes_is_a_conflict(tmp_path) -> None:
    store = store_at(tmp_path)
    first = assertion(at=T0)
    later = assertion(at=T0 + timedelta(days=1))
    assert first.relation_assertion_id == later.relation_assertion_id
    assert canonical_relation_line(first) != canonical_relation_line(later)
    store.append_assertion(first)
    with pytest.raises(RelationConflict) as info:
        store.append_assertion(later)
    assert info.value.code == "CONFLICT" and store.counts()["assertions"] == 1


# ---------------------------------------------------------------- 33〜36 破損


@pytest.mark.parametrize("reason,text,binary", [
    ("MALFORMED_JSON", "{not json}\n", None),
    ("NOT_AN_OBJECT", "[1,2]\n", None),
    ("BLANK_LINE", "\n", None),
    ("INVALID_ENCODING", None, b"\xff\xfe\n"),
])
def test_33_36_unreadable_lines_fail_closed(tmp_path, reason, text, binary) -> None:
    store_at(tmp_path)
    corrupt(tmp_path, text, binary=binary)
    expect_corrupt(tmp_path, reason)


def test_34_a_non_canonical_serialization_is_refused(tmp_path) -> None:
    store = store_at(tmp_path)
    record = assertion()
    store.append_assertion(record)
    corrupt(tmp_path, json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True, indent=None,
                                 separators=(", ", ": ")) + "\n")
    expect_corrupt(tmp_path, "NON_CANONICAL_LINE")


def test_35_an_unknown_schema_version_is_refused(tmp_path) -> None:
    store = store_at(tmp_path)
    record = assertion()
    store.append_assertion(record)
    payload = dict(record.as_dict(), schema_version="theme_relation_assertion:9.9.9")
    corrupt(tmp_path, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    expect_corrupt(tmp_path, "UNSUPPORTED_SCHEMA_VERSION")


def test_36b_structural_corruption_is_named_precisely(tmp_path) -> None:
    store = store_at(tmp_path)
    record = assertion()
    store.append_assertion(record)
    line = canonical_relation_line(record)
    corrupt(tmp_path, line.rstrip("\n"))
    expect_corrupt(tmp_path, "TRUNCATED_FINAL_LINE")
    corrupt(tmp_path, line + line)
    expect_corrupt(tmp_path, "PHYSICAL_DUPLICATE_IDENTICAL")
    other = assertion(at=T0 + timedelta(days=1))
    corrupt(tmp_path, line + canonical_relation_line(other))
    expect_corrupt(tmp_path, "PHYSICAL_DUPLICATE_CONFLICTING")
    event = retraction(record)
    corrupt(tmp_path, canonical_relation_line(event))
    expect_corrupt(tmp_path, "WRONG_AUTHORITY")
    broken = dict(record.as_dict(), target_theme_root_id=record.source_theme_root_id)
    corrupt(tmp_path, json.dumps(broken, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    expect_corrupt(tmp_path, "INVALID_RECORD")


def test_36c_a_loaded_history_violation_is_not_corruption(tmp_path) -> None:
    store = store_at(tmp_path)
    record = assertion()
    store.append_assertion(record)
    orphan = assertion(rationale="orphan correction", previous="threl_" + "0" * 24, at=T0 + timedelta(days=1))
    corrupt(tmp_path, canonical_relation_line(record) + canonical_relation_line(orphan))
    from src.intelligence.theme_intelligence.relation_store import RelationInvalidHistory

    with pytest.raises(RelationInvalidHistory) as info:
        ThemeRelationStore.open(tmp_path / "data")
    assert info.value.code == "MISSING_PREDECESSOR"


# ---------------------------------------------------------------- 37〜39 外部変更 / 再読み込み / 修復なし


def test_37_an_external_write_is_detected_before_appending(tmp_path) -> None:
    store = store_at(tmp_path)
    store.append_assertion(assertion())
    with store.paths["assertions"].open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(RelationConcurrentModification) as info:
        store.append_assertion(causal(A, "theme_" + "2" * 26))
    assert info.value.code == "CONCURRENT_MODIFICATION"


def test_38_reopening_replays_the_same_lines(tmp_path) -> None:
    store = store_at(tmp_path)
    first = assertion()
    store.append_assertion(first)
    store.append_assertion(assertion(rationale="revised", previous=first.relation_assertion_id,
                                     at=T0 + timedelta(days=1)))
    store.append_event(retraction(first))
    lines = {name: store.canonical_lines(name) for name in ("assertions", "governance")}
    again = ThemeRelationStore.open(tmp_path / "data")
    assert {name: again.canonical_lines(name) for name in lines} == lines
    assert again.counts() == store.counts() == {"assertions": 2, "governance": 1}
    assert again.edge_keys() == (first.edge_key,)


def test_39_a_corrupt_store_is_never_repaired(tmp_path) -> None:
    store = store_at(tmp_path)
    store.append_assertion(assertion())
    path = store.paths["assertions"]
    broken = path.read_text(encoding="utf-8") + "{}\n"
    path.write_text(broken, encoding="utf-8")
    expect_corrupt(tmp_path, "UNSUPPORTED_SCHEMA_VERSION")
    assert path.read_text(encoding="utf-8") == broken
    resolution = resolve_relations_at_data_root(tmp_path / "data", cutoff=T0 + timedelta(days=7),
                                                endpoint_lookup=endpoint_lookup_from_roots({A: T0, B: T0}))
    assert resolution.status is RelationResolutionStatus.STORE_CORRUPTION and resolution.edges == ()
    assert path.read_text(encoding="utf-8") == broken


def test_39b_the_store_backed_resolution_matches_the_pure_resolver(tmp_path) -> None:
    store = store_at(tmp_path)
    record = assertion()
    store.append_assertion(record)
    store.append_event(retraction(record))
    endpoint = endpoint_lookup_from_roots({A: T0, B: T0})
    resolution = resolve_relations_at_data_root(tmp_path / "data", cutoff=T0 + timedelta(days=7),
                                                endpoint_lookup=endpoint)
    assert resolution.status is RelationResolutionStatus.RESOLVED and len(resolution.edges) == 1
    assert resolution.edges[0].edge_state.value == "RETRACTED"


# ---------------------------------------------------------------- 59〜65 境界


def test_59_60_relation_writes_touch_no_other_authority(tmp_path) -> None:
    root = tmp_path / "data"
    store = ThemeRelationStore.initialize(root)
    first = assertion()
    store.append_assertion(first)
    store.append_event(retraction(first))
    assert sorted(p.name for p in root.iterdir()) == ["theme_intelligence"]
    assert sorted(p.name for p in (root / "theme_intelligence").iterdir()) == sorted(AUTHORITY_FILENAMES.values())
    for absent in ("themes", "predictions", "reports"):
        assert not (root / absent).exists()
    for absent in ("proposals.jsonl", "proposal_decisions.jsonl"):
        assert not (root / "theme_intelligence" / absent).exists()


def test_61_62_there_is_no_relation_proposal_and_no_discovery_path() -> None:
    assert not (PACKAGE_DIR / "relation_proposal.py").exists()
    assert not (PACKAGE_DIR / "relation_operations.py").exists()
    for name in B5B_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("Proposal", "PROPOSED", "proposal", "discover", "Discovery", "taxonomy", "entity_catalog",
                      "co_occurrence", "correlation", "overlap"):
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any(m.endswith((".discovery", ".discovery_adapter", ".proposal_store", ".proposal_model",
                                   ".taxonomy", ".entity_catalog", ".evidence_bridge")) for m in imports), name


def test_63_64_no_ranking_scoring_network_llm_or_wall_clock() -> None:
    for name in B5B_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("score", "rank", "weight", "confidence", "centrality", "pagerank", "PageRank", "importance",
                      "recommend", "similarity", "embedding", "cosine", "probability", "percentile"):
            assert token not in source, (name, token)
        for token in (".now(", "utcnow", "time.time", "random.", "secrets.", "requests", "urllib", "socket",
                      "openai", "anthropic", "sqlite", "subprocess"):
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not ({"random", "secrets", "requests", "urllib", "socket", "sqlite3", "subprocess"} & imports), name
    for name in PURE_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("open(", "Path(", "read_bytes(", "read_text(", ".write(", "fsync", "data_root", "jsonl"):
            assert token not in source, (name, token)


def test_65_the_relation_authority_is_not_wired_to_any_public_surface() -> None:
    for path in (REPO_ROOT / ".github").rglob("*.yml"):
        assert "relation_" not in path.read_text(encoding="utf-8"), path.name
    for path in (REPO_ROOT / "scripts").glob("*.py"):
        assert "relation_model" not in path.read_text(encoding="utf-8"), path.name
    config = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    assert "relation_model" not in config and "relation_assertions" not in config
    for path in (REPO_ROOT / "docs" / "v2").rglob("*"):
        if path.is_file():
            assert "relation_assertions" not in path.read_text(encoding="utf-8", errors="ignore"), path.name


def test_65b_relation_sources_carry_no_machine_paths_or_credentials() -> None:
    bs, sep = chr(92), chr(47)
    machine = re.compile("|".join(("[A-Za-z]:" + bs * 2, sep + "User" + "s" + sep,
                                   sep + "hom" + "e" + sep + "[a-z]+" + sep)))
    secrets = tuple("".join(parts) for parts in (("api", "_key"), ("pass", "word"), ("tok", "en=")))
    for name in B5B_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        assert not machine.search(source), name
        if name == "relation_model":
            continue                                    # 禁止語の検出 pattern を持つ唯一の module（値ではない）
        for token in secrets:
            assert token not in source, (name, token)
