"""P13-A3 — 明示の計画から Memory を作る build の試験（合成の一時 root だけ ・凍結の test の builder ・凍結の P10 の書き手）。

本物の private な root ・Obsidian の vault には触れない。取得 ・資格情報 ・network ・process は罠で塞ぐ。source の変化 ・不在 ・破損は
一時 root の操作で起こし、store の障害は store の module の `os` の代理で注入する。
"""
from __future__ import annotations

import http.client
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest

from src.intelligence.market_memory import memory_build as mb
from src.intelligence.market_memory import memory_generation as mg
from src.intelligence.market_memory import memory_store as ms
from src.intelligence.market_memory.governed_review_source import ADAPTER_RULES_VERSION, SUPPORTED_VIEW_IDENTITY, sample_review_state
from src.intelligence.market_memory.review_state_change import detect_changes_over
from src.intelligence.watchlist_thesis_intelligence.authority_stores import AuthorityStores as P9AuthorityStores
from tests.intelligence.test_market_memory_governed_source import AFTER_DECISIONS, AUTHOR, BEFORE_DECISIONS, ISSUER3, LATER, NOTE, REASON, _world
from tests.intelligence.test_market_memory_store import LOCK, inject, tree
from tests.intelligence.test_personal_intelligence_executor import D1
from tests.intelligence.test_watchlist_thesis_semantics import HOUR, T0, watch_create

PLAN = (BEFORE_DECISIONS, AFTER_DECISIONS, LATER)


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED")


@pytest.fixture(autouse=True)
def _no_network_credentials_or_processes(monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _trap)
    monkeypatch.setattr(socket.socket, "connect", _trap)
    monkeypatch.setattr(http.client.HTTPConnection, "__init__", _trap)
    monkeypatch.setattr(urllib.request, "urlopen", _trap)
    monkeypatch.setattr(subprocess, "Popen", _trap)                                   # scheduler ／ process は無い


@pytest.fixture
def world(tmp_path: Path) -> dict:
    return _world(tmp_path)


def _protected(world: dict) -> dict:
    return {"P9": world["root"], "P10": world["p10"], "OBSIDIAN_VAULT": world["base"] / "vault"}


@pytest.fixture
def store(world: dict) -> ms.MemoryStore:
    return ms.initialize_memory_root(world["base"] / "memory", protected_roots=_protected(world))


def build(store: ms.MemoryStore, world: dict, plan=PLAN, **roots) -> mb.BuildResult:
    return mb.build_memory(store, roots.get("p10", world["p10"]), roots.get("p9", world["root"]), cutoffs=list(plan))


def generation_files(world: dict, digest: str) -> dict:
    return tree(world["base"] / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY / digest)


# ================================================ 正: 公開 ・再読 ・決定論 ・REUSED ・歴史


def test_valid_build_publishes_and_the_strict_reread_reproduces_the_adapter_samples_and_changes(store, world) -> None:
    result = build(store, world)
    assert (result.status, result.code, result.lock_release) == (mb.BuildStatus.PUBLISHED, "PUBLISHED", ms.LOCK_RELEASED)
    assert result.publication_status is ms.ReadStatus.VERIFIED and result.publication_generation_digest == result.generation_digest
    assert result.plan_digest == mg.plan_digest(PLAN, SUPPORTED_VIEW_IDENTITY, adapter_rules_version=ADAPTER_RULES_VERSION)
    read = ms.read_memory(world["base"] / "memory", protected_roots=_protected(world))
    assert read.status is ms.ReadStatus.VERIFIED and read.generation_digest == result.generation_digest
    expected = tuple(sample_review_state(world["p10"], world["root"], cutoff=c, rules_version=ADAPTER_RULES_VERSION).sample for c in PLAN)
    assert read.verified.generation.samples == expected                                             # 標本の再生
    assert read.verified.generation.changes == detect_changes_over(expected) and read.verified.generation.changes   # 端点の差の再生
    assert not store.staging_present() and not (world["base"] / Path(*LOCK)).exists()
    assert store.list_attempts() == ()


def test_repeated_builds_are_deterministic_reused_and_never_rewrite_the_generation(store, world) -> None:
    first = build(store, world)
    files = generation_files(world, first.generation_digest)
    second = build(store, world)
    assert (second.status, second.generation_digest, second.manifest_digest) == (mb.BuildStatus.REUSED, first.generation_digest,
                                                                                  first.manifest_digest)
    assert generation_files(world, first.generation_digest) == files                                 # byte ・mtime は不変
    assert store.list_generations() == (first.generation_digest,)


def test_changed_source_results_give_a_distinct_generation_and_older_generations_are_preserved(store, world) -> None:
    first = build(store, world)
    files = generation_files(world, first.generation_digest)
    P9AuthorityStores.open(world["root"]).append_watch(watch_create(ISSUER3, at=T0 + 6 * HOUR, review_due_on=D1))
    second = build(store, world)
    assert second.status is mb.BuildStatus.PUBLISHED and second.plan_digest == first.plan_digest      # 同じ計画 ・別の結果
    assert second.generation_digest != first.generation_digest
    assert set(store.list_generations()) == {first.generation_digest, second.generation_digest}
    assert generation_files(world, first.generation_digest) == files                                 # 古い generation は残る
    assert store.read_generation(first.generation_digest).status is ms.ReadStatus.VERIFIED
    assert store.read_publication().generation_digest == second.generation_digest


def test_builds_leave_the_p9_and_p10_authority_bytes_and_mtimes_unchanged(store, world) -> None:
    before9, before10 = tree(world["root"]), tree(world["p10"])
    assert build(store, world).status is mb.BuildStatus.PUBLISHED
    assert build(store, world).status is mb.BuildStatus.REUSED
    assert build(store, world, plan=(AFTER_DECISIONS,), p10=world["base"] / "absent").status is mb.BuildStatus.INCOMPLETE
    assert tree(world["root"]) == before9 and tree(world["p10"]) == before10


def test_canonical_bytes_are_independent_of_the_root_location_working_directory_and_timezone(world, tmp_path, monkeypatch) -> None:
    (tmp_path / "left").mkdir()
    left = ms.initialize_memory_root(tmp_path / "left" / "memory_a", protected_roots=_protected(world))
    first = build(left, world)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    right = ms.initialize_memory_root(tmp_path / "other_memory", protected_roots=_protected(world))
    second = build(right, world)
    assert (first.plan_digest, first.generation_digest, first.manifest_digest) == (
        second.plan_digest, second.generation_digest, second.manifest_digest)
    a = tmp_path / "left" / "memory_a" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY / first.generation_digest
    b = tmp_path / "other_memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY / second.generation_digest
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir())
    for name in names:
        data = (a / name).read_bytes()
        assert data == (b / name).read_bytes(), name
        for leak in (str(tmp_path), str(world["base"]), NOTE, REASON, AUTHOR, "sampled_at", "\r"):
            assert leak.encode("utf-8") not in data, (name, leak)


# ================================================ 不完全な計画 ・入力の拒否


def test_missing_input_is_incomplete_records_safe_attempt_evidence_and_never_publishes(store, world) -> None:
    result = build(store, world, plan=(AFTER_DECISIONS, LATER), p10=world["base"] / "absent_p10")
    assert (result.status, result.code, result.attempt_code) == (mb.BuildStatus.INCOMPLETE, "P10_STORE_MISSING", ms.ATTEMPT_RECORDED)
    assert result.generation_digest is None and store.list_generations() == ()                     # INCOMPLETE の generation は無い
    assert result.publication_status is ms.ReadStatus.NOT_PUBLISHED and result.lock_release == ms.LOCK_RELEASED
    attempt = store.read_attempt(result.attempt_digest)
    assert attempt.plan_digest == result.plan_digest and attempt.outcomes == (("MISSING", "P10_STORE_MISSING"),) * 2
    data = (world["base"] / "memory" / ms.MEMORY_DIRECTORY / ms.ATTEMPTS_DIRECTORY / (result.attempt_digest + ".json")).read_bytes()
    for leak in (str(world["base"]), NOTE, REASON, AUTHOR, "p8iss_", "p9wat_", "sampled_at"):
        assert leak.encode("utf-8") not in data, leak                                               # source の詳細 ・telemetry は無い
    again = build(store, world, plan=(AFTER_DECISIONS, LATER), p10=world["base"] / "absent_p10")
    assert again.attempt_code == ms.ATTEMPT_ALREADY_RECORDED and again.attempt_digest == result.attempt_digest


def test_corrupt_input_is_incomplete_and_leaves_the_published_generation_in_place(store, world) -> None:
    published = build(store, world)
    profile = next(world["p10"].rglob("profile_authority.jsonl"))
    profile.write_bytes(profile.read_bytes() + b"{not json}\n")
    result = build(store, world)
    assert (result.status, result.code) == (mb.BuildStatus.INCOMPLETE, "P10_STORE_CORRUPTION")
    assert result.publication_status is ms.ReadStatus.VERIFIED and result.publication_generation_digest == published.generation_digest
    assert store.read_attempt(result.attempt_digest).outcomes == (("INTEGRITY_FAILURE", "P10_STORE_CORRUPTION"),) * 3
    assert store.list_generations() == (published.generation_digest,)


def test_duplicate_non_increasing_and_malformed_plans_are_rejected_before_any_read(store, world, monkeypatch) -> None:
    reads = []
    monkeypatch.setattr(mb, "sample_review_state", lambda *a, **k: reads.append(1))
    for plan, detail in (((AFTER_DECISIONS, AFTER_DECISIONS), mg.CUTOFF_ORDER_INVALID), ((LATER, AFTER_DECISIONS), mg.CUTOFF_ORDER_INVALID),
                         ((), mg.PLAN_INVALID), (("not-a-cutoff",), mg.PLAN_INVALID)):
        with pytest.raises(mb.MemoryBuildError) as exc:
            build(store, world, plan=plan)
        assert (exc.value.code, exc.value.detail) == (mb.BUILD_INPUT_INVALID, detail), plan
    with pytest.raises(mb.MemoryBuildError):
        mb.build_memory(object(), world["p10"], world["root"], cutoffs=list(PLAN))
    assert reads == [] and not (world["base"] / Path(*LOCK)).exists()


def test_source_roots_overlapping_the_memory_root_are_refused(world) -> None:
    store = ms.initialize_memory_root(world["base"] / "memory", protected_roots={})                # 呼び出し側が保護を渡さなくても
    inside = world["base"] / "memory" / "p9"
    result = build(store, world, p9=inside)
    assert (result.status, result.code, result.lock_release) == (mb.BuildStatus.REFUSED, ms.ROOT_OVERLAP, ms.LOCK_NOT_ACQUIRED)
    assert build(store, world, p10="relative/p10").code == ms.PROTECTED_ROOT_INVALID


# ================================================ lock ・staging ・障害 ・回復


def test_an_existing_lock_or_incomplete_staging_refuses_the_build_without_reading(store, world, monkeypatch) -> None:
    held = store.acquire_writer_lock(operation="BUILD", plan=None)
    result = build(store, world)
    assert (result.status, result.code, result.lock_release) == (mb.BuildStatus.REFUSED, ms.WRITER_LOCK_PRESENT, ms.LOCK_NOT_ACQUIRED)
    assert held.release() == ms.LOCK_RELEASED
    (world["base"] / "memory" / ms.MEMORY_DIRECTORY / ms.STAGING_DIRECTORY / ("a" * 64 + ms.PARTIAL_SUFFIX)).mkdir()
    reads = []
    monkeypatch.setattr(mb, "sample_review_state", lambda *a, **k: reads.append(1))
    result = build(store, world)
    assert (result.status, result.code, result.lock_release) == (mb.BuildStatus.REFUSED, ms.STAGING_PRESENT, ms.LOCK_RELEASED)
    assert reads == []


def test_a_failed_rename_preserves_evidence_blocks_publication_and_explicit_recovery_resumes(monkeypatch, store, world) -> None:
    inject(monkeypatch, faults={"rename": lambda location: location.endswith(ms.PARTIAL_SUFFIX)})
    failed = build(store, world)
    monkeypatch.undo()
    assert (failed.status, failed.code, failed.lock_release) == (mb.BuildStatus.FAILED, ms.STORE_IO_FAILED, ms.LOCK_RELEASED)
    assert failed.publication_status is ms.ReadStatus.NOT_PUBLISHED and store.list_generations() == ()
    assert build(store, world).code == ms.STAGING_PRESENT
    preserved = ms.preserve_interrupted_staging(store)
    assert len(preserved.preserved) == 1 and preserved.preserved[0].endswith(".partial.001.interrupted")
    assert build(store, world).status is mb.BuildStatus.PUBLISHED
    assert (world["base"] / "memory" / ms.MEMORY_DIRECTORY / ms.INTERRUPTED_DIRECTORY / preserved.preserved[0]).is_dir()


def test_a_lock_release_failure_is_reported_and_the_lock_keeps_blocking_without_any_takeover(monkeypatch, store, world) -> None:
    inject(monkeypatch, faults={"unlink": lambda location: location.endswith(ms.WRITER_LOCK_NAME)})
    result = build(store, world)
    monkeypatch.undo()
    assert (result.status, result.lock_release) == (mb.BuildStatus.PUBLISHED, ms.LOCK_RELEASE_FAILED)
    lock_file = world["base"] / Path(*LOCK)
    kept = lock_file.read_bytes(), lock_file.lstat().st_ino
    again = build(store, world)
    assert (again.status, again.code, again.lock_release) == (mb.BuildStatus.REFUSED, ms.WRITER_LOCK_PRESENT, ms.LOCK_NOT_ACQUIRED)
    with pytest.raises(ms.MemoryStoreError) as exc:
        ms.preserve_interrupted_staging(store)                                                      # 回復も lock を動かさない
    assert exc.value.code == ms.WRITER_LOCK_PRESENT
    assert (lock_file.read_bytes(), lock_file.lstat().st_ino) == kept and not hasattr(ms, "preserve_writer_lock")
    assert again.publication_status is None                                                          # lock の前の拒否は何も読まない
    assert store.read_publication().generation_digest == result.generation_digest                    # 公開は不変


def test_root_substitution_during_sampling_fails_closed_and_preserves_the_original_root(monkeypatch, store, world) -> None:
    real = mb.sample_review_state
    calls = []

    def substitute(*args, **kwargs):
        outcome = real(*args, **kwargs)
        calls.append(1)
        if len(calls) == len(PLAN):
            (world["base"] / "memory").rename(world["base"] / "memory_original")
            ms.initialize_memory_root(world["base"] / "memory", protected_roots=_protected(world))
        return outcome
    monkeypatch.setattr(mb, "sample_review_state", substitute)
    result = build(store, world)
    assert result.status in (mb.BuildStatus.REFUSED, mb.BuildStatus.FAILED) and result.code in (ms.ROOT_IDENTITY_MISMATCH,
                                                                                                ms.LOCK_OWNERSHIP_UNVERIFIED)
    assert result.lock_release == ms.LOCK_OWNERSHIP_UNVERIFIED                                      # 差し替えた root の lock は消さない
    assert result.publication_status is ms.ReadStatus.INTEGRITY_FAILURE
    original = world["base"] / "memory_original" / ms.MEMORY_DIRECTORY
    assert (original / ms.LOCKS_DIRECTORY / ms.WRITER_LOCK_NAME).exists() and list((original / ms.GENERATIONS_DIRECTORY).iterdir()) == []
    assert list((world["base"] / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY).iterdir()) == []


def test_a_corrupt_pointer_refuses_the_build_and_is_never_repaired_automatically(store, world) -> None:
    first = build(store, world)
    pointer = world["base"] / "memory" / ms.MEMORY_DIRECTORY / ms.PUBLICATION_NAME
    pointer.write_bytes(b"{not json}\n")
    result = build(store, world)
    assert (result.status, result.code) == (mb.BuildStatus.REFUSED, ms.PUBLICATION_NOT_VERIFIED)
    assert result.publication_status is ms.ReadStatus.INTEGRITY_FAILURE and pointer.read_bytes() == b"{not json}\n"
    assert ms.preserve_publication_pointer(store).code == ms.PRESERVED                               # 人の明示の呼び出しだけ
    again = build(store, world)
    assert again.status is mb.BuildStatus.REUSED and again.generation_digest == first.generation_digest


def test_no_build_path_invokes_pointer_preservation_or_any_recovery(monkeypatch, store, world) -> None:
    first = build(store, world)
    pointer = world["base"] / "memory" / ms.MEMORY_DIRECTORY / ms.PUBLICATION_NAME
    pointer.write_bytes(b"{not json}\n")
    for name in ("preserve_publication_pointer", "preserve_interrupted_staging"):
        monkeypatch.setattr(ms, name, _trap)
    monkeypatch.setattr(ms.MemoryStore, "_preserve", _trap)
    results = [build(store, world), build(store, world, plan=(AFTER_DECISIONS,), p10=world["base"] / "absent")]
    assert [r.code for r in results] == [ms.PUBLICATION_NOT_VERIFIED, ms.PUBLICATION_NOT_VERIFIED]   # 拒むだけ ・修復しない
    assert pointer.read_bytes() == b"{not json}\n" and store.list_generations() == (first.generation_digest,)
    assert list((world["base"] / "memory" / ms.MEMORY_DIRECTORY / ms.INTERRUPTED_DIRECTORY).iterdir()) == []
    assert "preserve" not in Path(mb.__file__).read_text(encoding="utf-8")                          # build は回復を参照しない


def test_results_hold_only_codes_and_digests(store, world) -> None:
    results = [build(store, world), build(store, world, plan=(AFTER_DECISIONS,), p10=world["base"] / "absent")]
    for result in results:
        text = repr(result)
        for leak in (str(world["base"]), NOTE, REASON, AUTHOR, "p8iss_", "Traceback"):
            assert leak not in text, leak
