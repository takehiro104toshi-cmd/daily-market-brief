"""P13-A3 — private な Memory Store の試験（合成の一時 root だけ ・本物の private な root ・vault には触れない）。

generation は純粋な合成の標本から作る（P10 ／ P9 は読まない）。障害は store の module だけが見る `os` の代理で注入する
（書き込み ・fsync ・rename ・pointer の置換 ・lock の解放）。どの経路でも generation ・試行 ・中断の staging は消えない。
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import stat
import subprocess
import urllib.request
from pathlib import Path

import pytest

from src.intelligence.market_memory import memory_generation as mg
from src.intelligence.market_memory import memory_store as ms
from tests.intelligence.test_market_memory_generation import ADAPTER, PLAN, generation

LOCK = ("memory", "market_memory", "locks", "writer.lock")


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED")


@pytest.fixture(autouse=True)
def _no_network_credentials_or_processes(monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _trap)
    monkeypatch.setattr(socket.socket, "connect", _trap)
    monkeypatch.setattr(http.client.HTTPConnection, "__init__", _trap)
    monkeypatch.setattr(urllib.request, "urlopen", _trap)
    monkeypatch.setattr(subprocess, "Popen", _trap)


class FaultyOs:
    """store の module だけが見る `os` の代理。指定した操作を、対象の位置が条件に合う時だけ失敗させる（他は本物へ）。"""

    def __init__(self, faults: dict, after_replace=None, reparse=()) -> None:
        self._faults, self._fds, self._after_replace, self._reparse = faults, {}, after_replace, tuple(str(p) for p in reparse)

    def __getattr__(self, name):
        return getattr(os, name)

    def _check(self, operation: str, location) -> None:
        predicate = self._faults.get(operation)
        if predicate is not None and predicate(str(location)):
            raise OSError("INJECTED")

    def open(self, location, flags, mode=0o777):
        fd = os.open(location, flags, mode)
        self._fds[fd] = str(location)
        return fd

    def write(self, fd, data):
        self._check("write", self._fds.get(fd, ""))
        return os.write(fd, data)

    def fsync(self, fd):
        self._check("fsync", self._fds.get(fd, ""))
        return os.fsync(fd)

    def rename(self, source, target):
        self._check("rename", source)
        return os.rename(source, target)

    def replace(self, source, target):
        self._check("replace", source)
        os.replace(source, target)
        if self._after_replace:
            self._after_replace(target)

    def unlink(self, location):
        self._check("unlink", location)
        return os.unlink(location)

    def lstat(self, location):
        st = os.lstat(location)
        return _Reparse(st) if str(location) in self._reparse else st


class _Reparse:
    st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT

    def __init__(self, st) -> None:
        self._st = st

    def __getattr__(self, name):
        return getattr(self._st, name)


def inject(monkeypatch, **kwargs) -> FaultyOs:
    proxy = FaultyOs(kwargs.pop("faults", {}), **kwargs)
    monkeypatch.setattr(ms, "os", proxy)
    return proxy


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None, p.lstat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def protected(base: Path) -> dict:
    return {"P9": base / "p9_private_root", "P10": base / "p10_private_root", "OBSIDIAN_VAULT": base / "vault"}


@pytest.fixture
def store(base: Path, protected: dict) -> ms.MemoryStore:
    return ms.initialize_memory_root(base / "memory", protected_roots=protected)


def publish(store: ms.MemoryStore, gen: mg.MemoryGeneration) -> ms.PublishOutcome:
    lock = store.acquire_writer_lock(operation="BUILD", plan=gen.plan_digest)
    try:
        return store.publish_generation(lock, gen)
    finally:
        assert lock.release() == ms.LOCK_RELEASED


def code_of(call, *args, **kwargs) -> str:
    with pytest.raises(ms.MemoryStoreError) as exc:
        call(*args, **kwargs)
    return exc.value.code


# ================================================ 明示の初期化 ・root の拒否


def test_explicit_initialization_creates_only_the_marker_and_the_fixed_layout(base, protected, store) -> None:
    root = base / "memory"
    assert sorted(p.name for p in root.iterdir()) == [ms.MARKER_NAME, ms.MEMORY_DIRECTORY]
    assert sorted(p.name for p in (root / ms.MEMORY_DIRECTORY).iterdir()) == sorted(ms.LAYOUT_DIRECTORIES)
    assert (root / ms.MARKER_NAME).read_bytes() == mg.marker_bytes()
    if os.name != "nt":
        assert stat.S_IMODE((root / ms.MEMORY_DIRECTORY).stat().st_mode) & 0o077 == 0                 # POSIX: 0o700 ・0o600（ACL は A5）
        assert stat.S_IMODE((root / ms.MARKER_NAME).stat().st_mode) & 0o077 == 0
    assert store.read_publication().status is ms.ReadStatus.NOT_PUBLISHED
    assert store.protected_labels == ("CODE_REPOSITORY", "OBSIDIAN_VAULT", "P10", "P9")             # 検査した label だけ
    assert str(base) not in repr(store)
    assert code_of(ms.initialize_memory_root, root, protected_roots=protected) == ms.ROOT_ALREADY_INITIALIZED
    occupied = base / "occupied"
    occupied.mkdir()
    (occupied / "note.txt").write_bytes(b"x")
    assert code_of(ms.initialize_memory_root, occupied, protected_roots=protected) == ms.ROOT_NOT_EMPTY
    assert code_of(ms.initialize_memory_root, base / "absent" / "memory", protected_roots=protected) == ms.ROOT_PARENT_MISSING
    assert not (base / "absent").exists()                                                       # 親は作らない
    assert code_of(ms.open_memory_store, base / "never", protected_roots=protected) == ms.MEMORY_ROOT_MISSING   # 開くは作らない
    assert not (base / "never").exists()
    assert ms.read_memory(base / "never", protected_roots=protected).status is ms.ReadStatus.MISSING
    empty = base / "empty"
    empty.mkdir()
    assert code_of(ms.open_memory_store, empty, protected_roots=protected) == ms.MEMORY_ROOT_MISSING  # 目印の無い directory


@pytest.mark.parametrize("bad", ["memory", "", " /x", "/x\x00y", 7, b"/x", None])
def test_root_shape_must_be_explicit_absolute_and_normalized(base, protected, bad) -> None:
    assert code_of(ms.initialize_memory_root, bad, protected_roots=protected) == ms.ROOT_INVALID


def test_traversal_unnormalized_and_anchor_roots_are_rejected(base, protected) -> None:
    for bad in (f"{base}/x/../memory", f"{base}//memory", f"{base}/memory/", f"{base}/./memory", os.sep):
        assert code_of(ms.initialize_memory_root, bad, protected_roots=protected) == ms.ROOT_INVALID, bad
    assert code_of(ms.initialize_memory_root, base / "m", protected_roots=["P9"]) == ms.PROTECTED_ROOT_INVALID
    assert code_of(ms.initialize_memory_root, base / "m", protected_roots={"p9": base / "x"}) == ms.PROTECTED_ROOT_INVALID
    assert code_of(ms.initialize_memory_root, base / "m", protected_roots={"P9": "relative"}) == ms.PROTECTED_ROOT_INVALID


def test_symlinked_roots_and_ancestors_are_refused(base, protected) -> None:
    real = base / "real"
    real.mkdir()
    try:
        (base / "alias").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink は作れない（権限）")
    assert code_of(ms.initialize_memory_root, base / "alias", protected_roots=protected) == ms.ROOT_UNSAFE_COMPONENT
    assert code_of(ms.initialize_memory_root, base / "alias" / "memory", protected_roots=protected) == ms.ROOT_UNSAFE_COMPONENT
    assert list(real.iterdir()) == []                                                           # 辿って作らない


def test_symlinks_inside_the_layout_or_a_generation_are_unsafe(store, base) -> None:
    gen = generation()
    assert publish(store, gen).status is ms.PublishStatus.PUBLISHED
    folder = base / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY / gen.generation_digest
    name = mg.sample_record_name(gen.samples[0].sample_digest)
    saved = (folder / name).read_bytes()
    (base / "outside.json").write_bytes(saved)
    (folder / name).unlink()
    try:
        (folder / name).symlink_to(base / "outside.json")
    except OSError:
        pytest.skip("symlink は作れない（権限）")
    result = store.read_publication()
    assert result.status is ms.ReadStatus.INTEGRITY_FAILURE and result.code == ms.UNSAFE_ENTRY


def test_reparse_points_are_refused_where_the_runtime_reports_them(monkeypatch, base, protected) -> None:
    target = base / "junction_like"
    target.mkdir()
    inject(monkeypatch, reparse=(target,))                                                       # Windows の reparse point の bit の模擬
    assert code_of(ms.initialize_memory_root, target / "memory", protected_roots=protected) == ms.ROOT_UNSAFE_COMPONENT
    assert code_of(ms.initialize_memory_root, target, protected_roots=protected) == ms.ROOT_UNSAFE_COMPONENT


def test_overlaps_with_supplied_protected_roots_and_the_code_repository_are_refused(base, protected) -> None:
    for location in (protected["P9"], protected["P9"] / "memory", base / "p9_private_root" / "deep" / "memory"):
        assert code_of(ms.initialize_memory_root, location, protected_roots=protected) == ms.ROOT_OVERLAP, location
    holder = base / "holder"
    assert code_of(ms.initialize_memory_root, holder, protected_roots={"P10": holder / "p10"}) == ms.ROOT_OVERLAP   # 保護の root を含む
    repository = Path(__file__).resolve().parents[2]
    assert code_of(ms.initialize_memory_root, repository / "memory_inside_repo", protected_roots={}) in (
        ms.ROOT_OVERLAP, ms.ROOT_INSIDE_WORKING_TREE)                                            # code の repository は常に保護
    real = base / "real_p9"
    real.mkdir()
    try:
        (base / "p9_alias").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink は作れない（権限）")
    assert code_of(ms.initialize_memory_root, real / "memory", protected_roots={"P9": base / "p9_alias"}) == ms.ROOT_OVERLAP  # 別名
    store = ms.initialize_memory_root(base / "memory", protected_roots={})
    assert store.protected_labels == ("CODE_REPOSITORY",)                                       # 渡されていない root は主張しない
    assert code_of(store.check_disjoint, {"SOURCE_P9": base / "memory" / "x"}) == ms.ROOT_OVERLAP
    store.check_disjoint({"SOURCE_P9": base / "elsewhere"})


@pytest.mark.parametrize("parts, marker", [(("OneDrive - Example", "memory"), None), (("Dropbox", "memory"), None),
                                           (("iCloud Drive", "memory"), None), (("box", "memory"), None),
                                           (("plain", "memory"), ".stfolder"), (("plain", "memory"), ".dropbox"),
                                           (("plain", "memory"), ".obsidian"), (("plain", "memory"), ".git")])
def test_known_sync_folders_vaults_and_working_trees_are_refused(base, protected, parts, marker) -> None:
    location = base.joinpath(*parts)
    location.parent.mkdir(parents=True)
    if marker:
        (location.parent / marker).mkdir()
    expected = {".obsidian": ms.ROOT_INSIDE_VAULT, ".git": ms.ROOT_INSIDE_WORKING_TREE}.get(marker, ms.ROOT_SYNC_FOLDER)
    assert code_of(ms.initialize_memory_root, location, protected_roots=protected) == expected
    assert not location.exists()


# ================================================ 公開 ・厳密な再読 ・REUSED ・歴史


def test_publish_strict_reread_reuse_and_history_preservation(store, base) -> None:
    first = generation()
    outcome = publish(store, first)
    assert (outcome.status, outcome.code, outcome.generation_digest) == (ms.PublishStatus.PUBLISHED, "PUBLISHED", first.generation_digest)
    assert outcome.publication_status is ms.ReadStatus.VERIFIED and outcome.publication_generation_digest == first.generation_digest
    read = store.read_publication()
    assert read.status is ms.ReadStatus.VERIFIED and read.verified.generation == first and not read.staging_present
    snapshot = tree(base / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY)
    again = publish(store, generation())
    assert again.status is ms.PublishStatus.REUSED and again.generation_digest == first.generation_digest
    assert tree(base / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY) == snapshot           # 書き直さない（byte ・mtime）
    second = generation(mute_b_at=0)
    assert publish(store, second).status is ms.PublishStatus.PUBLISHED
    assert set(store.list_generations()) == {first.generation_digest, second.generation_digest}
    for path, value in snapshot.items():
        assert tree(base / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY)[path] == value       # 古い generation は不変
    assert store.read_generation(first.generation_digest).status is ms.ReadStatus.VERIFIED
    assert store.read_publication().generation_digest == second.generation_digest
    back = publish(store, generation())                                                          # 古い generation へ戻す: REUSED
    assert back.status is ms.PublishStatus.REUSED and store.read_publication().generation_digest == first.generation_digest
    assert store.read_generation("e" * 64).status is ms.ReadStatus.MISSING
    assert str(base) not in repr(outcome) + repr(read) + repr(store)


# ================================================ lock


def test_writer_lock_is_exclusive_fail_closed_and_released_only_by_its_verified_owner(store, base) -> None:
    lock = store.acquire_writer_lock(operation="BUILD", plan=None)
    assert code_of(store.acquire_writer_lock, operation="BUILD", plan=None) == ms.WRITER_LOCK_PRESENT
    data = base.joinpath(*LOCK).read_bytes()
    assert json.loads(data) == {"schema_version": mg.LOCK_SCHEMA_VERSION, "operation": "BUILD", "plan_digest": None}   # telemetry は無い
    assert lock.owned() and lock.release() == ms.LOCK_RELEASED and lock.release() == ms.LOCK_RELEASED
    assert not base.joinpath(*LOCK).exists() and not lock.owned()
    with pytest.raises(ms.MemoryStoreError):
        ms.WriterLock(store, str(base.joinpath(*LOCK)), data, (1, 1), object())                  # 直接は作れない
    with pytest.raises(ms.MemoryStoreError):
        ms.MemoryStore(str(base), (1, 1), (), object())


@pytest.mark.parametrize("swap", ["content", "identity"])
def test_unverifiable_lock_ownership_retains_the_lock_and_keeps_blocking_writes(store, base, swap) -> None:
    lock = store.acquire_writer_lock(operation="BUILD", plan=None)
    lock_file = base.joinpath(*LOCK)
    data = lock_file.read_bytes()
    if swap == "content":
        lock_file.write_bytes(data.replace(b"BUILD", b"PRESERVE"))                               # 内容が変わった
    else:
        lock_file.rename(base / "aside_lock")                                                     # root の外へ（試験の操作）
        lock_file.write_bytes(data)                                                              # 同じ byte ・別の file（identity が違う）
    kept = lock_file.read_bytes(), lock_file.lstat().st_ino
    assert not lock.owned() and lock.release() == ms.LOCK_OWNERSHIP_UNVERIFIED                  # 消さない
    assert (lock_file.read_bytes(), lock_file.lstat().st_ino) == kept
    assert code_of(store.acquire_writer_lock, operation="BUILD", plan=None) == ms.WRITER_LOCK_PRESENT


def test_an_existing_lock_cannot_be_moved_or_taken_over_by_any_p13_operation(store, base, protected) -> None:
    held = store.acquire_writer_lock(operation="BUILD", plan=None)                                # 別の writer が持つ（または残った）lock
    lock_file = base.joinpath(*LOCK)
    kept = lock_file.read_bytes(), lock_file.lstat().st_ino, lock_file.lstat().st_mtime_ns
    assert not hasattr(ms, "preserve_writer_lock")                                               # lock の回復 ・奪取の API は無い
    assert code_of(store.acquire_writer_lock, operation="BUILD", plan=None) == ms.WRITER_LOCK_PRESENT
    assert code_of(ms.preserve_interrupted_staging, store) == ms.WRITER_LOCK_PRESENT
    assert code_of(ms.preserve_publication_pointer, store) == ms.WRITER_LOCK_PRESENT
    other = ms.open_memory_store(base / "memory", protected_roots=protected)                     # 別の handle は他人の lock を使えない
    assert other.publish_generation(held, generation()).code == ms.LOCK_OWNERSHIP_UNVERIFIED
    assert (lock_file.read_bytes(), lock_file.lstat().st_ino) == kept[:2]
    interrupted = base / "memory" / ms.MEMORY_DIRECTORY / ms.INTERRUPTED_DIRECTORY
    assert list(interrupted.iterdir()) == []                                                     # lock は移っていない
    assert held.release() == ms.LOCK_RELEASED                                                    # 所有者の通常の解放は働く
    (interrupted / "writer.lock.001.interrupted").write_bytes(kept[0])                          # 人が手で移した lock は layout の外
    assert store.read_publication().code == mg.UNAUTHORIZED_ENTRY


def test_lock_cleanup_failure_is_reported_and_the_lock_is_preserved(monkeypatch, store, base) -> None:
    lock = store.acquire_writer_lock(operation="BUILD", plan=None)
    inject(monkeypatch, faults={"unlink": lambda location: location.endswith("writer.lock")})
    assert lock.release() == ms.LOCK_RELEASE_FAILED and base.joinpath(*LOCK).exists()
    monkeypatch.undo()
    assert code_of(store.acquire_writer_lock, operation="BUILD", plan=None) == ms.WRITER_LOCK_PRESENT


def test_an_operation_with_a_foreign_or_released_lock_is_refused(store, base, protected) -> None:
    other_store = ms.initialize_memory_root(base / "memory2", protected_roots=protected)
    foreign = other_store.acquire_writer_lock(operation="BUILD", plan=None)
    outcome = store.publish_generation(foreign, generation())
    assert (outcome.status, outcome.code) == (ms.PublishStatus.REFUSED, ms.LOCK_OWNERSHIP_UNVERIFIED)
    foreign.release()
    lock = store.acquire_writer_lock(operation="BUILD", plan=None)
    lock.release()
    assert store.publish_generation(lock, generation()).code == ms.LOCK_OWNERSHIP_UNVERIFIED
    assert store.read_publication().status is ms.ReadStatus.NOT_PUBLISHED


# ================================================ 各段の障害 ・中断 ・回復


@pytest.mark.parametrize("faults, code", [
    ({"write": lambda location: ".partial" in location}, ms.STORE_IO_FAILED),
    ({"fsync": lambda location: ".partial" in location}, ms.STORE_IO_FAILED),
    ({"rename": lambda location: location.endswith(".partial")}, ms.STORE_IO_FAILED),
])
def test_failures_during_artifact_write_fsync_and_rename_preserve_staging_and_the_old_pointer(monkeypatch, store, base, faults, code) -> None:
    first = generation()
    assert publish(store, first).status is ms.PublishStatus.PUBLISHED
    inject(monkeypatch, faults=faults)
    outcome = publish(store, generation(mute_b_at=0))
    monkeypatch.undo()
    assert (outcome.status, outcome.code) == (ms.PublishStatus.FAILED, code)
    assert outcome.publication_status is ms.ReadStatus.VERIFIED and outcome.publication_generation_digest == first.generation_digest
    assert store.list_generations() == (first.generation_digest,)                                # 部分の generation は公開されない
    assert store.staging_present()
    staged = sorted(p.name for p in (base / "memory" / ms.MEMORY_DIRECTORY / ms.STAGING_DIRECTORY).iterdir())
    assert len(staged) == 1 and staged[0].endswith(ms.PARTIAL_SUFFIX)
    read = store.read_publication()
    assert read.status is ms.ReadStatus.VERIFIED and read.staging_present                       # 読みは続く ・書きは拒む
    refused = publish(store, generation(mute_b_at=0))
    assert (refused.status, refused.code) == (ms.PublishStatus.REFUSED, ms.STAGING_PRESENT)
    preserved = ms.preserve_interrupted_staging(store)                                           # 人の明示の回復
    assert preserved.preserved == (staged[0] + ".001.interrupted",) and preserved.lock_release == ms.LOCK_RELEASED
    assert (base / "memory" / ms.MEMORY_DIRECTORY / ms.INTERRUPTED_DIRECTORY / preserved.preserved[0]).is_dir()   # 消さない
    assert publish(store, generation(mute_b_at=0)).status is ms.PublishStatus.PUBLISHED


def test_pointer_replacement_failure_discards_only_the_owned_temp_and_reports_the_verified_state(monkeypatch, store, base) -> None:
    first, second = generation(), generation(mute_b_at=0)
    assert publish(store, first).status is ms.PublishStatus.PUBLISHED
    inject(monkeypatch, faults={"replace": lambda location: True})
    outcome = publish(store, second)
    monkeypatch.undo()
    assert (outcome.status, outcome.code) == (ms.PublishStatus.FAILED, ms.POINTER_PUBLICATION_FAILED)
    assert outcome.publication_status is ms.ReadStatus.VERIFIED and outcome.publication_generation_digest == first.generation_digest
    assert not store.staging_present()                                                           # 自分の一時 file だけを破棄した
    assert set(store.list_generations()) == {first.generation_digest, second.generation_digest}  # rename 済みの generation は残る
    assert publish(store, second).status is ms.PublishStatus.REUSED                              # 次は検証して REUSED


def test_a_pointer_temp_whose_ownership_cannot_be_verified_is_preserved(monkeypatch, store, base) -> None:
    staging = base / "memory" / ms.MEMORY_DIRECTORY / ms.STAGING_DIRECTORY

    def swap(location: str) -> bool:
        Path(location).write_bytes(b"someone else\n")                                             # 一時 file の内容が替わった
        return True
    inject(monkeypatch, faults={"replace": swap})
    outcome = publish(store, generation())
    monkeypatch.undo()
    assert outcome.code == ms.POINTER_PUBLICATION_FAILED and outcome.publication_status is ms.ReadStatus.NOT_PUBLISHED
    assert [p.name.startswith("publication.") for p in staging.iterdir()] == [True]              # 曖昧なら消さない
    assert publish(store, generation()).code == ms.STAGING_PRESENT


def test_pointer_verification_failure_is_reported_without_claiming_the_old_pointer(monkeypatch, store) -> None:
    def tamper(target: str) -> None:
        Path(target).write_bytes(b"{}\n")
    inject(monkeypatch, after_replace=tamper)
    outcome = publish(store, generation())
    monkeypatch.undo()
    assert (outcome.status, outcome.code) == (ms.PublishStatus.FAILED, ms.POINTER_VERIFICATION_FAILED)
    assert outcome.publication_status is ms.ReadStatus.INTEGRITY_FAILURE and outcome.publication_generation_digest is None


# ================================================ pointer ・generation ・layout の破損


def test_pointer_corruption_missing_generation_and_unsupported_schema_fail_closed_and_are_never_overwritten(store, base) -> None:
    gen = generation()
    assert publish(store, gen).status is ms.PublishStatus.PUBLISHED
    pointer = base / "memory" / ms.MEMORY_DIRECTORY / ms.PUBLICATION_NAME
    good = pointer.read_bytes()
    cases = ((b"{not json}\n", ms.ReadStatus.INTEGRITY_FAILURE, ms.PUBLICATION_POINTER_INCONSISTENT),
             (mg.PublicationRecord(generation_digest="d" * 64, manifest_digest="e" * 64).to_bytes(), ms.ReadStatus.INTEGRITY_FAILURE,
              ms.PUBLICATION_POINTER_INCONSISTENT),
             (mg.PublicationRecord(generation_digest=gen.generation_digest, manifest_digest="e" * 64).to_bytes(),
              ms.ReadStatus.INTEGRITY_FAILURE, ms.PUBLICATION_POINTER_INCONSISTENT),
             (good.replace(mg.PUBLICATION_SCHEMA_VERSION.encode(), b"p13_memory_publication:9.9.9"), ms.ReadStatus.SCHEMA_UNSUPPORTED,
              mg.SCHEMA_UNSUPPORTED))
    for data, status, code in cases:
        pointer.write_bytes(data)
        result = store.read_publication()
        assert (result.status, result.code) == (status, code), data
        refused = publish(store, generation(mute_b_at=0))
        assert (refused.status, refused.code) == (ms.PublishStatus.REFUSED, ms.PUBLICATION_NOT_VERIFIED)
        assert pointer.read_bytes() == data                                                      # 修復 ・上書きしない
    preserved = ms.preserve_publication_pointer(store)
    assert (preserved.code, preserved.preserved) == (ms.PRESERVED, ("publication.json.001.interrupted",)) and not pointer.exists()
    assert store.read_publication().status is ms.ReadStatus.NOT_PUBLISHED                       # 自動の再公開は無い
    assert publish(store, gen).status is ms.PublishStatus.REUSED                                 # 公開は別の明示の build だけ


def test_generation_tampering_missing_and_extra_files_are_detected_on_read_and_block_republication(store, base) -> None:
    gen = generation()
    assert publish(store, gen).status is ms.PublishStatus.PUBLISHED
    folder = base / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY / gen.generation_digest
    name = mg.sample_record_name(gen.samples[0].sample_digest)
    original = (folder / name).read_bytes()
    (folder / name).write_bytes(original.replace(b"watch-a", b"watch-z"))
    assert store.read_publication().code == mg.MANIFEST_MISMATCH
    (folder / name).write_bytes(original)
    (folder / mg.CHANGES_RECORD_NAME).rename(base / "aside")
    assert store.read_publication().code == mg.GENERATION_INCOMPLETE
    (base / "aside").rename(folder / mg.CHANGES_RECORD_NAME)
    (folder / "extra.txt").write_bytes(b"x")
    assert store.read_publication().code == mg.UNAUTHORIZED_ENTRY
    (folder / "extra.txt").unlink()
    assert store.read_publication().status is ms.ReadStatus.VERIFIED
    (folder / name).write_bytes(original + b" ")
    ms.preserve_publication_pointer(store)
    snapshot = tree(folder)
    conflict = publish(store, gen)                                                               # 壊れた既存の generation は上書きしない
    assert (conflict.status, conflict.code) == (ms.PublishStatus.FAILED, ms.GENERATION_CONFLICT)
    assert tree(folder) == snapshot


@pytest.mark.parametrize("mutate, code", [
    (lambda root: (root / "stray.txt").write_bytes(b"x"), mg.UNAUTHORIZED_ENTRY),
    (lambda root: (root / ms.MEMORY_DIRECTORY / "exports").mkdir(), mg.UNAUTHORIZED_ENTRY),
    (lambda root: (root / ms.MEMORY_DIRECTORY / ms.LOCKS_DIRECTORY / "other.lock").write_bytes(b"x"), mg.UNAUTHORIZED_ENTRY),
    (lambda root: (root / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY / "latest").mkdir(), mg.UNAUTHORIZED_ENTRY),
    (lambda root: (root / ms.MEMORY_DIRECTORY / ms.ATTEMPTS_DIRECTORY / "a.json").write_bytes(b"x"), mg.UNAUTHORIZED_ENTRY),
    (lambda root: (root / ms.MEMORY_DIRECTORY / ms.STAGING_DIRECTORY / "random.bin").write_bytes(b"x"), mg.UNAUTHORIZED_ENTRY),
    (lambda root: (root / ms.MEMORY_DIRECTORY / ms.INTERRUPTED_DIRECTORY).rename(root / "moved"), mg.UNAUTHORIZED_ENTRY),
    (lambda root: (root / ms.MEMORY_DIRECTORY / ms.INTERRUPTED_DIRECTORY).rmdir(), ms.LAYOUT_INVALID),
    (lambda root: (root / ms.MARKER_NAME).write_bytes(b"{}\n"), ms.MARKER_INVALID),
    (lambda root: (root / ms.MARKER_NAME).write_bytes(mg.marker_bytes().replace(b"0.1.0", b"9.9.9")), mg.SCHEMA_UNSUPPORTED),
    (lambda root: (root / ms.MARKER_NAME).unlink(), ms.MEMORY_ROOT_MISSING),
])
def test_unauthorized_layout_entries_and_marker_problems_fail_closed(store, base, mutate, code) -> None:
    mutate(base / "memory")
    result = store.read_publication()
    assert result.code == code and result.status is {ms.MEMORY_ROOT_MISSING: ms.ReadStatus.MISSING,
                                                     mg.SCHEMA_UNSUPPORTED: ms.ReadStatus.SCHEMA_UNSUPPORTED}.get(code, ms.ReadStatus.INTEGRITY_FAILURE)
    assert code_of(store.acquire_writer_lock, operation="BUILD", plan=None) == code             # 書き込みも拒む


def test_root_identity_mismatch_is_detected_before_critical_operations(store, base, protected) -> None:
    (base / "memory").rename(base / "memory_original")
    ms.initialize_memory_root(base / "memory", protected_roots=protected)                       # 同じ位置の別の root
    assert code_of(store.acquire_writer_lock, operation="BUILD", plan=None) == ms.ROOT_IDENTITY_MISMATCH
    assert store.read_publication().code == ms.ROOT_IDENTITY_MISMATCH
    assert not (base / "memory_original" / ms.MEMORY_DIRECTORY / ms.LOCKS_DIRECTORY / ms.WRITER_LOCK_NAME).exists()


def test_root_substitution_between_staging_and_publication_fails_closed(monkeypatch, store, base, protected) -> None:
    real_verify = mg.verify_generation_records
    swapped = []

    def substitute(records, *, expected_generation_digest):
        verified = real_verify(records, expected_generation_digest=expected_generation_digest)
        if not swapped:
            swapped.append(True)
            (base / "memory").rename(base / "memory_original")
            ms.initialize_memory_root(base / "memory", protected_roots=protected)
        return verified
    monkeypatch.setattr(ms, "verify_generation_records", substitute)
    lock = store.acquire_writer_lock(operation="BUILD", plan=None)
    outcome = store.publish_generation(lock, generation())
    monkeypatch.undo()
    assert outcome.status is ms.PublishStatus.FAILED and outcome.code in (ms.LOCK_OWNERSHIP_UNVERIFIED, ms.ROOT_IDENTITY_MISMATCH)
    assert lock.release() == ms.LOCK_OWNERSHIP_UNVERIFIED                                        # 差し替えた先の lock は自分のではない
    original = base / "memory_original" / ms.MEMORY_DIRECTORY
    assert [p.name for p in (original / ms.STAGING_DIRECTORY).iterdir()][0].endswith(ms.PARTIAL_SUFFIX)   # 元の root の証拠は残る
    assert (original / ms.LOCKS_DIRECTORY / ms.WRITER_LOCK_NAME).exists()
    assert list((base / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY).iterdir()) == []


# ================================================ 試行の証拠


def test_attempt_evidence_is_recorded_once_and_never_overwritten(store, base) -> None:
    plan = mg.plan_digest(PLAN, generation().view_identity, adapter_rules_version=ADAPTER)
    attempt = mg.AttemptRecord(plan_digest=plan, cutoffs=PLAN, outcomes=(("SAMPLED", ""), ("MISSING", "P10_STORE_MISSING"), ("SAMPLED", "")))
    lock = store.acquire_writer_lock(operation="BUILD", plan=plan)
    assert store.record_attempt(lock, attempt) == ms.ATTEMPT_RECORDED
    assert store.record_attempt(lock, attempt) == ms.ATTEMPT_ALREADY_RECORDED
    lock.release()
    assert store.list_attempts() == (attempt.attempt_digest,) and store.read_attempt(attempt.attempt_digest) == attempt
    assert store.read_publication().status is ms.ReadStatus.NOT_PUBLISHED                        # pointer は変えない
    location = base / "memory" / ms.MEMORY_DIRECTORY / ms.ATTEMPTS_DIRECTORY / (attempt.attempt_digest + ".json")
    location.write_bytes(location.read_bytes().replace(b"MISSING", b"INTEGRITY_FAILURE"))
    lock = store.acquire_writer_lock(operation="BUILD", plan=plan)
    assert code_of(store.record_attempt, lock, attempt) == ms.ATTEMPT_CONFLICT
    lock.release()
    assert code_of(store.read_attempt, attempt.attempt_digest) == ms.ATTEMPT_CONFLICT


def test_errors_and_results_hold_only_constant_codes_and_no_locations(monkeypatch, store, base, protected) -> None:
    texts = []
    for call in (lambda: ms.initialize_memory_root(base / "memory", protected_roots=protected),
                 lambda: ms.open_memory_store(base / "nowhere", protected_roots=protected),
                 lambda: ms.initialize_memory_root(protected["P9"], protected_roots=protected)):
        with pytest.raises(ms.MemoryStoreError) as exc:
            call()
        texts.append(str(exc.value))
    texts.append(repr(publish(store, generation())))
    texts.append(repr(store.read_publication()))
    for text in texts:
        assert str(base) not in text and "Traceback" not in text and "watch-a" not in text, text


# ================================================ pointer の回復の安全（明示 ・検証できる pointer は移さない ・置き換えない）


def evidence(base: Path) -> dict:
    memory = base / "memory" / ms.MEMORY_DIRECTORY
    return {name: tree(memory / name) for name in (ms.GENERATIONS_DIRECTORY, ms.ATTEMPTS_DIRECTORY)}


def record_some_attempt(store: ms.MemoryStore) -> None:
    plan = mg.plan_digest(PLAN, generation().view_identity, adapter_rules_version=ADAPTER)
    lock = store.acquire_writer_lock(operation="BUILD", plan=plan)
    store.record_attempt(lock, mg.AttemptRecord(plan_digest=plan, cutoffs=PLAN, outcomes=(("MISSING", "P10_STORE_MISSING"),) * 3))
    assert lock.release() == ms.LOCK_RELEASED


def test_a_valid_or_absent_pointer_is_never_preserved(store, base) -> None:
    pointer = base / "memory" / ms.MEMORY_DIRECTORY / ms.PUBLICATION_NAME
    absent = ms.preserve_publication_pointer(store)
    assert (absent.code, absent.preserved, absent.lock_release) == (ms.NOTHING_TO_PRESERVE, (), ms.LOCK_RELEASED)
    assert publish(store, generation()).status is ms.PublishStatus.PUBLISHED
    record_some_attempt(store)
    before, kept = evidence(base), (pointer.read_bytes(), pointer.lstat().st_ino, pointer.lstat().st_mtime_ns)
    refused = ms.preserve_publication_pointer(store)
    assert (refused.code, refused.preserved, refused.lock_release) == (ms.POINTER_VERIFIED_NOT_PRESERVED, (), ms.LOCK_RELEASED)
    assert (pointer.read_bytes(), pointer.lstat().st_ino, pointer.lstat().st_mtime_ns) == kept
    assert evidence(base) == before and store.read_publication().status is ms.ReadStatus.VERIFIED
    assert list((base / "memory" / ms.MEMORY_DIRECTORY / ms.INTERRUPTED_DIRECTORY).iterdir()) == []


def test_an_uncertain_publication_state_fails_closed_and_moves_nothing(monkeypatch, store, base) -> None:
    gen = generation()
    assert publish(store, gen).status is ms.PublishStatus.PUBLISHED
    pointer = base / "memory" / ms.MEMORY_DIRECTORY / ms.PUBLICATION_NAME
    kept = pointer.read_bytes(), pointer.lstat().st_ino
    folder = base / "memory" / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY / gen.generation_digest
    target = folder / mg.GENERATION_RECORD_NAME
    real_open = os.open

    def failing_open(location, flags, mode=0o777):
        if str(location) == str(target) and not flags & os.O_WRONLY:
            raise OSError("INJECTED")                                                            # 読みの I/O の失敗（確定ではない）
        return real_open(location, flags, mode)
    proxy = inject(monkeypatch)
    proxy.open = failing_open
    assert store.read_publication().code == ms.STORE_IO_FAILED
    result = ms.preserve_publication_pointer(store)
    monkeypatch.undo()
    assert (result.code, result.preserved) == (ms.PUBLICATION_STATE_UNCERTAIN, ())
    assert (pointer.read_bytes(), pointer.lstat().st_ino) == kept and store.read_publication().status is ms.ReadStatus.VERIFIED


def test_corrupt_pointer_preservation_is_explicit_moves_the_same_bytes_and_never_overwrites_evidence(store, base) -> None:
    gen = generation()
    assert publish(store, gen).status is ms.PublishStatus.PUBLISHED
    record_some_attempt(store)
    memory = base / "memory" / ms.MEMORY_DIRECTORY
    pointer = memory / ms.PUBLICATION_NAME
    occupied = memory / ms.INTERRUPTED_DIRECTORY / "publication.json.001.interrupted"
    occupied.write_bytes(b"earlier evidence\n")                                                 # 既に在る証拠（置き換えてはならない）
    pointer.write_bytes(b"{corrupt pointer}\n")
    identity = pointer.lstat().st_ino
    before = evidence(base)
    assert store.read_publication().code == ms.PUBLICATION_POINTER_INCONSISTENT                  # 読むだけでは何も動かない
    assert pointer.exists() and list((memory / ms.INTERRUPTED_DIRECTORY).iterdir()) == [occupied]
    result = ms.preserve_publication_pointer(store)
    assert (result.code, result.preserved) == (ms.PRESERVED, ("publication.json.002.interrupted",))
    moved = memory / ms.INTERRUPTED_DIRECTORY / result.preserved[0]
    assert moved.read_bytes() == b"{corrupt pointer}\n" and moved.lstat().st_ino == identity     # 同じ file ・同じ byte
    assert occupied.read_bytes() == b"earlier evidence\n"                                        # 既存の証拠は不変
    assert not pointer.exists() and evidence(base) == before                                     # generation ・試行は不変
    assert store.read_publication().status is ms.ReadStatus.NOT_PUBLISHED and store.list_generations() == (gen.generation_digest,)


def test_the_no_replace_move_refuses_an_existing_target_file_or_directory(base) -> None:
    for directory in (False, True):
        source, target = base / f"source_{directory}", base / f"target_{directory}"
        if directory:
            source.mkdir()
            (source / "inner").write_bytes(b"inner")
            target.mkdir()
            (target / "kept").write_bytes(b"kept")
        else:
            source.write_bytes(b"source")
            target.write_bytes(b"kept")
        with pytest.raises(OSError):
            ms._move_without_replacing(str(source), str(target), directory=directory)
        assert source.exists() and (target / "kept" if directory else target).read_bytes() == b"kept"   # どちらも不変
    fresh = base / "fresh_target"
    ms._move_without_replacing(str(base / "source_False"), str(fresh), directory=False)
    assert fresh.read_bytes() == b"source" and not (base / "source_False").exists()


def test_recovery_operations_leave_generation_and_attempt_evidence_unchanged(monkeypatch, store, base) -> None:
    assert publish(store, generation()).status is ms.PublishStatus.PUBLISHED
    record_some_attempt(store)
    inject(monkeypatch, faults={"rename": lambda location: location.endswith(ms.PARTIAL_SUFFIX)})
    assert publish(store, generation(mute_b_at=0)).code == ms.STORE_IO_FAILED
    monkeypatch.undo()
    before = evidence(base)
    assert ms.preserve_interrupted_staging(store).code == ms.PRESERVED
    assert ms.preserve_interrupted_staging(store).code == ms.NOTHING_TO_PRESERVE
    assert ms.preserve_publication_pointer(store).code == ms.POINTER_VERIFIED_NOT_PRESERVED
    (base / "memory" / ms.MEMORY_DIRECTORY / ms.PUBLICATION_NAME).write_bytes(b"{}\n")
    assert ms.preserve_publication_pointer(store).code == ms.PRESERVED
    assert evidence(base) == before


def test_only_the_owned_lock_and_the_owned_pointer_temp_are_ever_unlinked(monkeypatch, store, base) -> None:
    calls = []
    proxy = inject(monkeypatch)
    for operation in ("unlink", "rename", "replace"):
        real = getattr(proxy, operation)

        def recording(*args, _operation=operation, _real=real):
            calls.append((_operation, str(args[0])))
            return _real(*args)
        setattr(proxy, operation, recording)
    assert publish(store, generation()).status is ms.PublishStatus.PUBLISHED
    proxy._faults["replace"] = lambda location: True
    assert publish(store, generation(mute_b_at=0)).code == ms.POINTER_PUBLICATION_FAILED
    del proxy._faults["replace"]
    (base / "memory" / ms.MEMORY_DIRECTORY / ms.PUBLICATION_NAME).write_bytes(b"{}\n")
    ms.preserve_publication_pointer(store)
    monkeypatch.undo()
    memory = str(base / "memory" / ms.MEMORY_DIRECTORY)
    unlinked = [location for operation, location in calls if operation == "unlink"]
    assert unlinked and all(location.endswith(ms.WRITER_LOCK_NAME) or
                            (location.startswith(f"{memory}{os.sep}{ms.STAGING_DIRECTORY}{os.sep}publication.") and location.endswith(ms.TEMP_SUFFIX))
                            for location in unlinked)                                            # lock と pointer の一時 file だけ
    for operation, location in calls:                                                            # 歴史の証拠を動かす ・消す操作は無い
        for protected in (ms.GENERATIONS_DIRECTORY, ms.ATTEMPTS_DIRECTORY, ms.INTERRUPTED_DIRECTORY):
            assert not location.startswith(f"{memory}{os.sep}{protected}{os.sep}"), (operation, protected)
