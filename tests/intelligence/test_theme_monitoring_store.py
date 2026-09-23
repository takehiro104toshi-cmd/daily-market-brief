"""P6-B6D — 人間の review 状態だけを持つ追記専用 store（`monitoring_store`）の契約 test（§24 matrix）。

書き込みは `tmp_path` のみ。finding は**保存しない**（B6A Option C）ことも合わせて固定する。
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.monitoring_model import (MONITORING_FINDING_SCHEMA_VERSION,
                                                                  MONITORING_RUN_REPORT_SCHEMA_VERSION,
                                                                  MonitoringModelError, ReviewChainStatus,
                                                                  ReviewDisposition, ReviewItemState,
                                                                  canonical_monitoring_line, resolve_review_state)
from src.intelligence.theme_intelligence.monitoring_store import (AppendStatus, CORRUPTION_REASONS, HISTORY_REASONS,
                                                                  MONITORING_DIRNAME, MonitoringReviewStore,
                                                                  REVIEW_STATE_FILENAME, ReviewAppendRejected,
                                                                  ReviewConcurrentModification, ReviewConflict,
                                                                  ReviewFailureCategory, ReviewInvalidHistory,
                                                                  ReviewStoreCorrupt, WRITER_GUARANTEE,
                                                                  monitoring_dir, review_state_path)
from src.intelligence.themes.model import ProvenanceClass
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
F1 = "thmfind_" + "a" * 24
F2 = "thmfind_" + "b" * 24
ACTOR = "reviewer:r1"
T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
D = ReviewDisposition


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def state(*, finding_id: str = F1, disposition: ReviewDisposition = D.ACKNOWLEDGED, actor_ref: str = ACTOR,
          recorded_at: datetime = T0, note: str = "", supersedes: str = "") -> ReviewItemState:
    return ReviewItemState.build(finding_id=finding_id, disposition=disposition, actor_ref=actor_ref,
                                 recorded_at=recorded_at, note=note, supersedes_review_state_id=supersedes)


def opened(tmp_path: Path, name: str = "data") -> MonitoringReviewStore:
    return MonitoringReviewStore.initialize(tmp_path / name)


def corrupt(tmp_path: Path, *lines: str) -> Path:
    root = tmp_path / "broken"
    (root / MONITORING_DIRNAME).mkdir(parents=True, exist_ok=True)
    path = review_state_path(root)
    path.write_text("".join(lines), encoding="utf-8")
    return root


# ---------------------------------------------------------------- 1〜6 場所・初期化・明示 data_root

def test_01_path_is_explicit_and_under_the_given_data_root(tmp_path: Path) -> None:
    assert monitoring_dir(tmp_path / "d") == tmp_path / "d" / MONITORING_DIRNAME
    assert review_state_path(tmp_path / "d").name == REVIEW_STATE_FILENAME == "monitoring_review_states.jsonl"
    store = opened(tmp_path)
    assert store.path == review_state_path(tmp_path / "data") and store.path.exists()


def test_02_initialize_is_idempotent_and_keeps_existing_lines(tmp_path: Path) -> None:
    store = opened(tmp_path)
    store.append_review_state(state())
    again = MonitoringReviewStore.initialize(tmp_path / "data")
    assert again.count() == 1


def test_03_missing_journal_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(tmp_path / "never_initialized")
    assert exc.value.code == "AUTHORITY_MISSING" and exc.value.category is ReviewFailureCategory.STORE_CORRUPTION


@pytest.mark.parametrize("root", ["", "   ", None])
def test_04_data_root_is_required(root) -> None:
    with pytest.raises(ReviewAppendRejected) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "DATA_ROOT_REQUIRED"


def test_05_no_implicit_home_or_machine_path_in_source() -> None:
    source = (PACKAGE_DIR / "monitoring_store.py").read_text(encoding="utf-8")
    for token in ("expanduser", "home()", "environ", "getenv", chr(92) + chr(92), "C:" + chr(92)):
        assert token not in source, token
    assert WRITER_GUARANTEE == "SINGLE_WRITER"


def test_06_store_never_reads_the_current_clock() -> None:
    source = executable_source(PACKAGE_DIR / "monitoring_store.py")
    for token in (".now(", "utcnow", "time.time", "datetime.today"):
        assert token not in source, token


# ---------------------------------------------------------------- 7〜12 append の冪等性と衝突

def test_07_append_is_append_only_and_fsyncs(tmp_path: Path) -> None:
    source = executable_source(PACKAGE_DIR / "monitoring_store.py")
    assert "open('ab')" in source and "fsync" in source
    for token in ("'w'", '"w"', "truncate(", "unlink(", "os.remove", "os.replace"):
        assert token not in source, token
    store = opened(tmp_path)
    first = store.append_review_state(state())
    assert first.status is AppendStatus.APPENDED
    assert store.path.read_bytes().endswith(b"\n") and store.path.read_bytes().count(b"\n") == 1


def test_08_identical_bytes_are_already_present(tmp_path: Path) -> None:
    store = opened(tmp_path)
    record = state()
    assert store.append_review_state(record).status is AppendStatus.APPENDED
    again = store.append_review_state(record)
    assert again.status is AppendStatus.ALREADY_PRESENT and store.count() == 1
    assert store.path.read_bytes().count(b"\n") == 1


def test_09_same_id_different_bytes_is_a_conflict(tmp_path: Path) -> None:
    store = opened(tmp_path)
    first = state(recorded_at=T0)
    later = state(recorded_at=at(3))                      # recorded_at は identity に入らない → 同 id・異 bytes
    assert first.review_state_id == later.review_state_id
    store.append_review_state(first)
    with pytest.raises(ReviewConflict) as exc:
        store.append_review_state(later)
    assert exc.value.code == "CONFLICT" and exc.value.category is ReviewFailureCategory.CONFLICT
    assert store.count() == 1


def test_10_read_only_store_refuses_to_append(tmp_path: Path) -> None:
    opened(tmp_path)
    store = MonitoringReviewStore.open(tmp_path / "data", read_only=True)
    with pytest.raises(ReviewAppendRejected) as exc:
        store.append_review_state(state())
    assert exc.value.code == "READ_ONLY" and store.count() == 0


def test_11_external_change_is_detected_before_writing(tmp_path: Path) -> None:
    store = opened(tmp_path)
    store.append_review_state(state())
    with review_state_path(tmp_path / "data").open("ab") as handle:
        handle.write(canonical_monitoring_line(state(finding_id=F2)).encode("utf-8"))
    with pytest.raises(ReviewConcurrentModification) as exc:
        store.append_review_state(state(disposition=D.DISMISSED))
    assert exc.value.code == "CONCURRENT_MODIFICATION"


def test_12_append_rejects_anything_that_is_not_a_review_state(tmp_path: Path) -> None:
    store = opened(tmp_path)
    for value in (None, "x", 1, object()):
        with pytest.raises(ReviewAppendRejected) as exc:
            store.append_review_state(value)
        assert exc.value.code == "INVALID_TYPE"


# ---------------------------------------------------------------- 13〜22 破損の fail closed

def test_13_blank_line_fails_closed(tmp_path: Path) -> None:
    root = corrupt(tmp_path, "\n")
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "BLANK_LINE" and exc.value.line_number == 1


def test_14_truncated_final_line_fails_closed(tmp_path: Path) -> None:
    line = canonical_monitoring_line(state())
    root = corrupt(tmp_path, line, line[:-5])
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "TRUNCATED_FINAL_LINE"


def test_15_malformed_json_fails_closed(tmp_path: Path) -> None:
    root = corrupt(tmp_path, "{not json\n")
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "MALFORMED_JSON"


@pytest.mark.parametrize("body", ["[1,2]", '"text"', "12"])
def test_16_non_object_line_fails_closed(tmp_path: Path, body: str) -> None:
    root = corrupt(tmp_path, body + "\n")
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "NOT_AN_OBJECT"


def test_17_unsupported_schema_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(canonical_monitoring_line(state()))
    payload["schema_version"] = "theme_monitoring_review_item_state:9.9.9"
    root = corrupt(tmp_path, json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "UNSUPPORTED_SCHEMA_VERSION"


@pytest.mark.parametrize("schema", [MONITORING_FINDING_SCHEMA_VERSION, MONITORING_RUN_REPORT_SCHEMA_VERSION])
def test_18_another_monitoring_record_is_not_accepted_here(tmp_path: Path, schema: str) -> None:
    payload = json.loads(canonical_monitoring_line(state()))
    payload["schema_version"] = schema
    root = corrupt(tmp_path, json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code in ("INVALID_RECORD", "WRONG_AUTHORITY")


def test_19_non_canonical_line_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(canonical_monitoring_line(state()))
    root = corrupt(tmp_path, json.dumps(payload, sort_keys=True, separators=(", ", ": ")) + "\n")
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "NON_CANONICAL_LINE"


def test_20_invalid_record_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(canonical_monitoring_line(state()))
    payload["actor_class"] = ProvenanceClass.RULE.value
    root = corrupt(tmp_path, json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "INVALID_RECORD"


@pytest.mark.parametrize("identical", [True, False])
def test_21_physical_duplicate_ids_fail_closed(tmp_path: Path, identical: bool) -> None:
    line = canonical_monitoring_line(state())
    second = line if identical else canonical_monitoring_line(state(recorded_at=at(5)))
    root = corrupt(tmp_path, line, second)
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    expected = "PHYSICAL_DUPLICATE_IDENTICAL" if identical else "PHYSICAL_DUPLICATE_CONFLICTING"
    assert exc.value.code == expected and exc.value.code in CORRUPTION_REASONS


def test_22_invalid_encoding_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "bytes"
    (root / MONITORING_DIRNAME).mkdir(parents=True)
    review_state_path(root).write_bytes(b"\xff\xfe{}\n")
    with pytest.raises(ReviewStoreCorrupt) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "INVALID_ENCODING"


# ---------------------------------------------------------------- 23〜30 chain の構造規律

def test_23_predecessor_must_exist(tmp_path: Path) -> None:
    store = opened(tmp_path)
    with pytest.raises(ReviewAppendRejected) as exc:
        store.append_review_state(state(disposition=D.DISMISSED, supersedes="thmrev_" + "0" * 24))
    assert exc.value.code == "MISSING_PREDECESSOR" and exc.value.code in HISTORY_REASONS


def test_23b_a_dangling_predecessor_on_disk_is_invalid_history(tmp_path: Path) -> None:
    """append 経路は APPEND_REJECTED、既に書かれた history は INVALID_HISTORY（Foundation / B3 と同じ分け方）。"""
    first = state()
    orphan = state(finding_id=F2, disposition=D.DEFERRED, recorded_at=at(1), supersedes="thmrev_" + "0" * 24)
    root = corrupt(tmp_path, canonical_monitoring_line(first), canonical_monitoring_line(orphan))
    with pytest.raises(ReviewInvalidHistory) as exc:
        MonitoringReviewStore.open(root)
    assert exc.value.code == "MISSING_PREDECESSOR" and exc.value.line_number == 2


def test_24_predecessor_must_review_the_same_finding(tmp_path: Path) -> None:
    store = opened(tmp_path)
    first = state()
    store.append_review_state(first)
    with pytest.raises(ReviewAppendRejected) as exc:
        store.append_review_state(state(finding_id=F2, disposition=D.DISMISSED,
                                        supersedes=first.review_state_id))
    assert exc.value.code == "CROSS_FINDING_PREDECESSOR"


def test_25_a_review_history_does_not_fork(tmp_path: Path) -> None:
    store = opened(tmp_path)
    first = state()
    store.append_review_state(first)
    store.append_review_state(state(disposition=D.DEFERRED, recorded_at=at(1), supersedes=first.review_state_id))
    with pytest.raises(ReviewAppendRejected) as exc:
        store.append_review_state(state(disposition=D.DISMISSED, recorded_at=at(2),
                                        supersedes=first.review_state_id))
    assert exc.value.code == "NOT_TERMINAL_PREDECESSOR"


def test_26_recorded_at_is_monotonic_along_the_chain(tmp_path: Path) -> None:
    store = opened(tmp_path)
    first = state(recorded_at=at(5))
    store.append_review_state(first)
    with pytest.raises(ReviewAppendRejected) as exc:
        store.append_review_state(state(disposition=D.DISMISSED, recorded_at=at(1),
                                        supersedes=first.review_state_id))
    assert exc.value.code == "NON_MONOTONIC_RECORDED_AT"


def test_26b_a_predecessor_always_precedes_physically(tmp_path: Path) -> None:
    """追記専用なので「後から前を足す」ことはできない。読み飛ばしも順序の補修もしない。"""
    store = opened(tmp_path)
    first = state()
    with pytest.raises(ReviewAppendRejected) as exc:
        store.append_review_state(state(disposition=D.DEFERRED, recorded_at=at(1),
                                        supersedes=first.review_state_id))
    assert exc.value.code == "MISSING_PREDECESSOR" and store.count() == 0


def test_27_a_state_cannot_supersede_itself(tmp_path: Path) -> None:
    store = opened(tmp_path)
    first = state()
    with pytest.raises(MonitoringModelError) as exc:
        ReviewItemState(schema_version=first.schema_version, monitoring_vocab_version=first.monitoring_vocab_version,
                        review_state_id=first.review_state_id, finding_id=F1, disposition=D.ACKNOWLEDGED,
                        actor_class=ProvenanceClass.HUMAN, actor_ref=ACTOR, note="",
                        supersedes_review_state_id=first.review_state_id, recorded_at=T0)
    assert exc.value.code == "INVALID_RECORD"


def test_28_a_cycle_on_disk_is_unresolved_not_a_winner(tmp_path: Path) -> None:
    """content id のため実在の cycle は作れない。resolver 側が cycle を INVALID とすることを固定する。"""
    first = state()
    second = state(disposition=D.DEFERRED, recorded_at=at(1), supersedes=first.review_state_id)

    class _Duck:
        review_state_id = first.review_state_id
        finding_id = F1
        supersedes_review_state_id = second.review_state_id

    resolution = resolve_review_state(F1, (_Duck(), second))
    assert resolution.status is ReviewChainStatus.INVALID and resolution.diagnostics == ("CYCLE",)


def test_29_multiple_starts_are_unresolved(tmp_path: Path) -> None:
    store = opened(tmp_path)
    store.append_review_state(state())
    store.append_review_state(state(disposition=D.DISMISSED, recorded_at=at(1)))
    resolution = resolve_review_state(F1, store.states_for(F1))
    assert resolution.status is ReviewChainStatus.UNRESOLVED and "MULTIPLE_STARTS" in resolution.diagnostics
    assert resolution.terminal is None                              # latest-wins にしない


def test_30_store_does_not_implement_its_own_latest_wins() -> None:
    source = executable_source(PACKAGE_DIR / "monitoring_store.py")
    for token in ("latest", "def current", "def active", "terminal", "winner", "sort(key=lambda"):
        assert token not in source, token
    assert "resolve_review_state" not in source


# ---------------------------------------------------------------- 31〜36 読み取り面と解決

def test_31_resolution_uses_the_predecessor_graph_only(tmp_path: Path) -> None:
    store = opened(tmp_path)
    first = state()
    second = state(disposition=D.DEFERRED, recorded_at=at(1), supersedes=first.review_state_id)
    third = state(disposition=D.DISMISSED, recorded_at=at(2), supersedes=second.review_state_id)
    for record in (first, second, third):
        store.append_review_state(record)
    stored = store.states_for(F1)
    for order in (stored, tuple(reversed(stored)), (stored[1], stored[2], stored[0])):
        resolution = resolve_review_state(F1, order)                 # 入力順は勝者を決めない
        assert resolution.status is ReviewChainStatus.RESOLVED
        assert resolution.terminal.disposition is D.DISMISSED and len(resolution.chain) == 3


def test_32_states_for_is_scoped_to_one_finding(tmp_path: Path) -> None:
    store = opened(tmp_path)
    store.append_review_state(state())
    store.append_review_state(state(finding_id=F2, disposition=D.DEFERRED))
    assert {s.finding_id for s in store.states_for(F1)} == {F1} and store.count() == 2
    assert resolve_review_state("thmfind_" + "c" * 24, store.review_states()).status is ReviewChainStatus.NONE


def test_33_reload_restores_exactly_what_was_written(tmp_path: Path) -> None:
    store = opened(tmp_path)
    first = state()
    store.append_review_state(first)
    store.append_review_state(state(disposition=D.DEFERRED, recorded_at=at(1), supersedes=first.review_state_id))
    before = review_state_path(tmp_path / "data").read_bytes()
    reopened = MonitoringReviewStore.open(tmp_path / "data", read_only=True)
    assert reopened.count() == 2 and reopened.canonical_lines() == store.canonical_lines()
    assert review_state_path(tmp_path / "data").read_bytes() == before        # 読むだけで書かない
    assert reopened.get(first.review_state_id) == first


def test_34_no_repair_and_no_migration_in_source() -> None:
    source = executable_source(PACKAGE_DIR / "monitoring_store.py")
    for token in ("repair", "migrat", "rewrite", "upgrade", "backfill", "compact"):
        assert token not in source, token


def test_35_records_are_bounded_and_reject_machine_paths_or_credentials(tmp_path: Path) -> None:
    store = opened(tmp_path)
    for note in ("C:" + chr(92) + "Users" + chr(92) + "someone" + chr(92) + "notes.txt",
                 "https://user:pw@example.test/x", "https://example.test/x?api_key=abc", "x" * 241, "two\nlines"):
        with pytest.raises(MonitoringModelError):
            store.append_review_state(state(note=note))
    assert store.count() == 0


@pytest.mark.parametrize("actor_class", [ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL])
def test_36_only_a_person_can_record_a_review(actor_class: ProvenanceClass) -> None:
    base = state()
    with pytest.raises(MonitoringModelError) as exc:
        ReviewItemState(schema_version=base.schema_version, monitoring_vocab_version=base.monitoring_vocab_version,
                        review_state_id=base.review_state_id, finding_id=F1, disposition=D.ACKNOWLEDGED,
                        actor_class=actor_class, actor_ref=ACTOR, note="",
                        supersedes_review_state_id="", recorded_at=T0)
    assert exc.value.code == "FORBIDDEN_REVIEW_AUTHORITY"
    assert state().actor_class is ProvenanceClass.HUMAN


# ---------------------------------------------------------------- 37〜42 finding を authority にしない

def test_37_no_finding_journal_exists(tmp_path: Path) -> None:
    store = opened(tmp_path)
    store.append_review_state(state())
    files = sorted(p.name for p in monitoring_dir(tmp_path / "data").glob("*"))
    assert files == [REVIEW_STATE_FILENAME]
    assert not (PACKAGE_DIR / "finding_store.py").exists()
    assert not list(PACKAGE_DIR.glob("*.jsonl"))


def test_38_no_finding_persistence_api_anywhere_in_the_package() -> None:
    for path in sorted(PACKAGE_DIR.glob("monitoring_*.py")):
        source = executable_source(path)
        for token in ("append_finding", "save_finding", "monitoring_findings", "finding_store", "persist_finding"):
            assert token not in source, (path.name, token)


def test_39_review_state_references_a_finding_without_copying_it(tmp_path: Path) -> None:
    store = opened(tmp_path)
    record = state(note="looked at it")
    store.append_review_state(record)
    payload = json.loads(store.canonical_lines()[0])
    assert payload["finding_id"] == F1
    for key in ("condition_id", "salient_state", "category", "subject_kind", "subject_ref", "cutoff",
                "ruleset_version", "trigger_refs", "supporting_refs"):
        assert key not in payload, key


def test_40_only_human_dispositions_exist() -> None:
    assert {d.value for d in ReviewDisposition} == {"ACKNOWLEDGED", "DISMISSED", "DEFERRED"}
    for token in ("RESOLVED", "CLOSED", "FIXED", "REOPENED", "AUTO"):
        assert token not in {d.value for d in ReviewDisposition}


def test_41_the_only_write_path_is_append_review_state() -> None:
    tree = ast.parse((PACKAGE_DIR / "monitoring_store.py").read_text(encoding="utf-8"))
    writers = [node.name for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef) and "self.path.open" in ast.unparse(node) and "'ab'" in ast.unparse(node)]
    assert writers == ["append_review_state"]


def test_42_failure_vocabulary_is_stable() -> None:
    assert set(CORRUPTION_REASONS) >= {"AUTHORITY_MISSING", "MALFORMED_JSON", "NON_CANONICAL_LINE",
                                       "UNSUPPORTED_SCHEMA_VERSION", "TRUNCATED_FINAL_LINE"}
    assert set(HISTORY_REASONS) == {"MISSING_PREDECESSOR", "CROSS_FINDING_PREDECESSOR", "NOT_TERMINAL_PREDECESSOR",
                                    "NON_MONOTONIC_RECORDED_AT", "INVALID_TYPE"}
    assert {c.value for c in ReviewFailureCategory} == {"STORE_CORRUPTION", "INVALID_HISTORY", "APPEND_REJECTED",
                                                        "CONFLICT", "CONCURRENT_MODIFICATION"}
