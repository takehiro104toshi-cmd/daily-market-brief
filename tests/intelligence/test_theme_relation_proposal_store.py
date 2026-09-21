"""P6-B5C — relation proposal store の永続化規律と B5C の境界（matrix 59〜79）。

提案 / 決定は B5B relation authority とは別 file に追記される。B5C はどの既存 authority にも書かない。
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.relation_model import AssertionClass
from src.intelligence.theme_intelligence.relation_proposal_model import (RelationDecisionKind,
                                                                         canonical_proposal_record_line)
from src.intelligence.theme_intelligence.relation_proposal_store import (AUTHORITY_FILENAMES, AppendStatus,
                                                                         RelationProposalAppendRejected,
                                                                         RelationProposalConcurrentModification,
                                                                         RelationProposalConflict,
                                                                         RelationProposalInvalidHistory,
                                                                         RelationProposalStore,
                                                                         RelationProposalStoreCorrupt,
                                                                         WRITER_GUARANTEE, authority_paths,
                                                                         relation_proposals_dir)
from src.intelligence.theme_intelligence.relation_proposal_resolution import (RelationProposalStatus,
                                                                              derive_relation_proposal_status)
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_relation import T0
from tests.intelligence.test_theme_relation_proposal import (DECIDED_AT, RelationProposerClass, causal, decide,
                                                             proposal, sourced)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
B5C_MODULES = ("relation_proposal_model", "relation_proposal_resolution", "relation_proposal_bridge",
               "relation_proposal_store")
PURE_MODULES = ("relation_proposal_model", "relation_proposal_resolution", "relation_proposal_bridge")


def store_at(tmp_path: Path) -> RelationProposalStore:
    return RelationProposalStore.initialize(tmp_path / "data")


def corrupt(tmp_path: Path, text: str, *, authority: str = "proposals", binary: bytes = None) -> None:
    path = authority_paths(tmp_path / "data")[authority]
    if binary is not None:
        path.write_bytes(binary)
    else:
        path.write_text(text, encoding="utf-8")


def expect_corrupt(tmp_path: Path, reason: str) -> None:
    with pytest.raises(RelationProposalStoreCorrupt) as info:
        RelationProposalStore.open(tmp_path / "data")
    assert info.value.code == reason, info.value.code


# ---------------------------------------------------------------- 59〜63


def test_59_initialize_creates_exactly_two_empty_authorities(tmp_path) -> None:
    store = store_at(tmp_path)
    assert store.counts() == {"proposals": 0, "decisions": 0}
    directory = relation_proposals_dir(tmp_path / "data")
    assert sorted(AUTHORITY_FILENAMES.values()) == ["relation_proposal_decisions.jsonl", "relation_proposals.jsonl"]
    assert set(AUTHORITY_FILENAMES.values()) <= {p.name for p in directory.iterdir()}
    assert all(p.read_bytes() == b"" for p in store.paths.values()) and WRITER_GUARANTEE == "SINGLE_WRITER"


def test_60_61_proposals_and_decisions_append(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    assert store.append_proposal(candidate).status is AppendStatus.APPENDED
    decision = decide(candidate)
    assert store.append_decision(decision).status is AppendStatus.APPENDED
    assert store.counts() == {"proposals": 1, "decisions": 1}
    assert derive_relation_proposal_status(store.get_proposal(candidate.proposal_id),
                                           store.decisions()) is RelationProposalStatus.ACCEPTED


def test_61b_a_decision_needs_its_proposal_and_a_sound_chain(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    orphan = decide(candidate)
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(orphan)
    assert info.value.code == "PROPOSAL_NOT_FOUND"
    store.append_proposal(candidate)
    first = decide(candidate, RelationDecisionKind.DEFER, reason="hold")
    store.append_decision(first)
    store.append_decision(decide(candidate, reason="accept one", supersedes=first.decision_id,
                                 at=DECIDED_AT + timedelta(hours=1)))
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(decide(candidate, reason="accept two", supersedes=first.decision_id,
                                     at=DECIDED_AT + timedelta(hours=1)))
    assert info.value.code == "NOT_TERMINAL_PREDECESSOR"
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(decide(candidate, reason="orphan chain", supersedes="threldec_" + "0" * 24))
    assert info.value.code == "MISSING_PREDECESSOR"


def test_61c_source_authority_cannot_be_laundered_through_the_store(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal(proposer=RelationProposerClass.RULE, proposer_ref="rule:x")
    store.append_proposal(candidate)
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(decide(candidate, accepted=AssertionClass.SOURCE_ASSERTED))
    assert info.value.code == "FORBIDDEN_SOURCE_AUTHORITY"
    attributed = sourced()
    store.append_proposal(attributed)
    assert store.append_decision(decide(attributed, accepted=AssertionClass.SOURCE_ASSERTED)).status is AppendStatus.APPENDED


def test_62_63_idempotency_and_conflict(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = proposal(proposer=RelationProposerClass.RULE, proposer_ref="rule:a")
    assert store.append_proposal(candidate).status is AppendStatus.APPENDED
    before = store.paths["proposals"].read_bytes()
    assert store.append_proposal(candidate).status is AppendStatus.ALREADY_PRESENT
    assert store.paths["proposals"].read_bytes() == before
    same_claim = proposal(proposer=RelationProposerClass.HUMAN, proposer_ref="reviewer:r1")
    assert same_claim.proposal_id == candidate.proposal_id
    with pytest.raises(RelationProposalConflict) as info:
        store.append_proposal(same_claim)
    assert info.value.code == "CONFLICT" and store.counts()["proposals"] == 1


# ---------------------------------------------------------------- 64〜67 破損


@pytest.mark.parametrize("reason,text,binary", [
    ("MALFORMED_JSON", "{not json}\n", None),
    ("NOT_AN_OBJECT", "[1,2]\n", None),
    ("BLANK_LINE", "\n", None),
    ("INVALID_ENCODING", None, b"\xff\xfe\n")])
def test_64_67_unreadable_lines_fail_closed(tmp_path, reason, text, binary) -> None:
    store_at(tmp_path)
    corrupt(tmp_path, text, binary=binary)
    expect_corrupt(tmp_path, reason)


def test_65_66_67b_structural_corruption_is_named_precisely(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    store.append_proposal(candidate)
    line = canonical_proposal_record_line(candidate)
    corrupt(tmp_path, json.dumps(candidate.as_dict(), ensure_ascii=False, sort_keys=True, separators=(", ", ": ")) + "\n")
    expect_corrupt(tmp_path, "NON_CANONICAL_LINE")
    payload = dict(candidate.as_dict(), schema_version="theme_relation_proposal:9.9.9")
    corrupt(tmp_path, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    expect_corrupt(tmp_path, "UNSUPPORTED_SCHEMA_VERSION")
    corrupt(tmp_path, line.rstrip("\n"))
    expect_corrupt(tmp_path, "TRUNCATED_FINAL_LINE")
    corrupt(tmp_path, line + line)
    expect_corrupt(tmp_path, "PHYSICAL_DUPLICATE_IDENTICAL")
    other = proposal(proposer=RelationProposerClass.HUMAN, proposer_ref="reviewer:r1", relation_type=candidate.relation_type,
                     refs=candidate.evidence_refs)
    corrupt(tmp_path, line + canonical_proposal_record_line(other))
    expect_corrupt(tmp_path, "PHYSICAL_DUPLICATE_CONFLICTING")
    corrupt(tmp_path, canonical_proposal_record_line(decide(candidate)))
    expect_corrupt(tmp_path, "WRONG_AUTHORITY")
    broken = dict(candidate.as_dict(), target_theme_root_id=candidate.source_theme_root_id)
    corrupt(tmp_path, json.dumps(broken, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    expect_corrupt(tmp_path, "INVALID_RECORD")


def test_67c_a_loaded_history_violation_is_not_corruption(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    store.append_proposal(candidate)
    corrupt(tmp_path, canonical_proposal_record_line(decide(candidate, supersedes="threldec_" + "0" * 24)),
            authority="decisions")
    with pytest.raises(RelationProposalInvalidHistory) as info:
        RelationProposalStore.open(tmp_path / "data")
    assert info.value.code == "MISSING_PREDECESSOR"


# ---------------------------------------------------------------- 68〜70


def test_68_an_external_write_is_detected_before_appending(tmp_path) -> None:
    store = store_at(tmp_path)
    store.append_proposal(causal())
    with store.paths["proposals"].open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(RelationProposalConcurrentModification) as info:
        store.append_proposal(proposal(rationale="another candidate"))
    assert info.value.code == "CONCURRENT_MODIFICATION"


def test_69_a_read_only_store_refuses_to_append(tmp_path) -> None:
    store_at(tmp_path)
    reader = RelationProposalStore.open(tmp_path / "data", read_only=True)
    with pytest.raises(RelationProposalAppendRejected) as info:
        reader.append_proposal(causal())
    assert info.value.code == "READ_ONLY"
    with pytest.raises(RelationProposalAppendRejected) as info:
        RelationProposalStore.open("")
    assert info.value.code == "DATA_ROOT_REQUIRED"


def test_70_reopening_replays_the_same_lines(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    store.append_proposal(candidate)
    store.append_decision(decide(candidate))
    lines = {name: store.canonical_lines(name) for name in ("proposals", "decisions")}
    again = RelationProposalStore.open(tmp_path / "data")
    assert {name: again.canonical_lines(name) for name in lines} == lines
    assert again.counts() == store.counts() == {"proposals": 1, "decisions": 1}
    assert again.proposals() == store.proposals() and again.decisions() == store.decisions()


# ---------------------------------------------------------------- 71〜76 境界


def test_71_73_the_proposal_layer_touches_no_other_authority(tmp_path) -> None:
    root = tmp_path / "data"
    store = RelationProposalStore.initialize(root)
    candidate = causal()
    store.append_proposal(candidate)
    store.append_decision(decide(candidate))
    assert sorted(p.name for p in root.iterdir()) == ["theme_intelligence"]
    present = sorted(p.name for p in (root / "theme_intelligence").iterdir())
    assert present == ["relation_proposal_decisions.jsonl", "relation_proposals.jsonl"]
    for absent in ("relation_assertions.jsonl", "relation_governance.jsonl", "proposals.jsonl",
                   "proposal_decisions.jsonl"):
        assert not (root / "theme_intelligence" / absent).exists()
    for absent in ("themes", "predictions", "reports"):
        assert not (root / absent).exists()


def test_74_no_discovery_or_automatic_candidate_generation() -> None:
    for name in B5C_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("discover", "Discovery", "taxonomy", "entity_catalog", "co_occurrence", "correlation",
                      "overlap", "ChangeSet", "lifecycle"):
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any(m.endswith((".discovery", ".discovery_adapter", ".taxonomy", ".entity_catalog", ".change",
                                   ".lifecycle", ".proposal_store", ".proposal_model", ".evidence_bridge"))
                       for m in imports), name


def test_75_76_no_network_llm_clock_or_ranking() -> None:
    for name in B5C_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("score", "rank", "weight", "confidence", "probability", "strength", "centrality", "pagerank",
                      "recommend", "similarity", "embedding", "cosine"):
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


def test_76b_b5c_never_appends_to_the_relation_authority() -> None:
    for name in B5C_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("ThemeRelationStore", "append_assertion", "append_event", "relation_store",
                      "ThemeRelationAssertion", "ThemeRelationGovernanceEvent", "themes.store", "themes.operations"):
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any(m.endswith((".relation_store", "themes.store", "themes.operations", "themes.revision"))
                       for m in imports), name


def test_76c_relation_proposal_sources_carry_no_machine_paths() -> None:
    bs, sep = chr(92), chr(47)
    machine = re.compile("|".join(("[A-Za-z]:" + bs * 2, sep + "User" + "s" + sep,
                                   sep + "hom" + "e" + sep + "[a-z]+" + sep)))
    secrets = tuple("".join(parts) for parts in (("api", "_key"), ("pass", "word"), ("tok", "en=")))
    for name in B5C_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        assert not machine.search(source), name
        if name == "relation_proposal_model":
            continue                                   # 禁止語の検出 pattern を持つ唯一の module（値ではない）
        for token in secrets:
            assert token not in source, (name, token)
