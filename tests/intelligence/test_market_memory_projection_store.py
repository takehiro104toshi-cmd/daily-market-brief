"""P13-A4b — Obsidian 投影の export の store の試験（合成の一時 root ・合成の vault だけ ・本物の private な root ・vault には触れない）。

composition root の明示の初期化 ・開く時の拒否（root の形 ・重なり ・symlink ／ reparse ・git ／ 同期 ／ vault の目印 ・人が置く目印 ・
Obsidian の設定）・2 つの writer lock（順序 ・排他 ・2 つ目の失敗 ・所有の喪失 ・2 つの private な root の競合）・観測の厳密さ（未知の
entry ・hard link ・symlink ・大小の別名）・書き込みの primitive（1 回の rename ・byte 一致の残りだけを続ける ・上書きしない ・置き換えない
移動 ・pointer の期待の照合 ・番号の保存）・空き容量 ・store の `os` だけが見る代理で記録した操作が `projection/` と `generated/` の外に
書かず人の note を読まないことを固定する。A4b の build の試験はここの helper を使う。
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import stat
import subprocess
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.intelligence.market_memory import memory_store as ms
from src.intelligence.market_memory import projection_store as ps
from tests.intelligence.test_market_memory_projection_contract import GEN_A

PLUGINS = {"core-plugins.json": '["file-explorer", "global-search", "backlink"]', "community-plugins.json": "[]",
           "app.json": '{"alwaysUpdateLinks": false}'}
HUMAN_FILES = ("Daily.md", "notes/human.md", "notes/deep/idea.md", ".obsidian/workspace.json", ".obsidian/plugins/x/data.json")
MUTATIONS = ("mkdir", "create", "write", "fsync", "rename", "replace", "unlink")


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


# ================================================ 共有の helper（build の試験も使う）


class FaultyOs:
    """projection store の module だけが見る `os` の代理。操作を記録し、n 番目の書き込みの操作（mkdir ・作成 ・書き ・file の fsync ・rename ・
    replace ・unlink）か条件に合う操作を、行う前（`after=False`）か行った後（`after=True`）に失敗させる。`torn=True` の書きは半分だけ書いて
    失敗する。他は本物の `os` へ。"""

    def __init__(self, *, faults=None, nth=None, after=False, torn=False, reparse=(), hook=None) -> None:
        self.faults, self.nth, self.after, self.torn, self.hook = dict(faults or {}), nth, after, torn, hook
        self.count, self.calls, self._fds, self._created = 0, [], {}, set()
        self.reparse = {str(p) for p in reparse}

    def __getattr__(self, name):
        return getattr(os, name)

    def _hit(self, operation: str, location: str) -> bool:
        self.calls.append((operation, location))
        hit = False
        if operation in MUTATIONS:
            self.count += 1
            hit = self.nth == self.count
        predicate = self.faults.get(operation)
        if self.hook is not None:
            self.hook(operation, location)
        return hit or (predicate is not None and predicate(location))

    def open(self, location, flags, mode=0o777):
        operation = "create" if flags & os.O_CREAT else "open"
        hit = self._hit(operation, str(location))
        if hit and not self.after:
            raise OSError("INJECTED")
        fd = os.open(location, flags, mode)
        if hit:
            os.close(fd)
            raise OSError("INJECTED_AFTER")
        self._fds[fd] = str(location)
        if operation == "create":
            self._created.add(fd)
        return fd

    def close(self, fd):
        self._fds.pop(fd, None)
        self._created.discard(fd)
        return os.close(fd)

    def write(self, fd, data):
        hit = self._hit("write", self._fds.get(fd, ""))
        if hit and self.torn:
            os.write(fd, bytes(data[:max(1, len(data) // 2)]))
            raise OSError("INJECTED_TORN")
        if hit and not self.after:
            raise OSError("INJECTED")
        written = os.write(fd, data)
        if hit:
            raise OSError("INJECTED_AFTER")
        return written

    def fsync(self, fd):
        if fd not in self._created:
            return os.fsync(fd)                                                            # directory の fsync は数えない
        return self._mutate("fsync", self._fds.get(fd, ""), lambda: os.fsync(fd))

    def _mutate(self, operation, location, perform):
        hit = self._hit(operation, str(location))
        if hit and not self.after:
            raise OSError("INJECTED")
        result = perform()
        if hit:
            raise OSError("INJECTED_AFTER")
        return result

    def mkdir(self, location, mode=0o777):
        return self._mutate("mkdir", location, lambda: os.mkdir(location, mode))

    def rename(self, source, target):
        return self._mutate("rename", source, lambda: os.rename(source, target))

    def replace(self, source, target):
        return self._mutate("replace", source, lambda: os.replace(source, target))

    def unlink(self, location):
        return self._mutate("unlink", location, lambda: os.unlink(location))

    def listdir(self, location):
        self.calls.append(("listdir", str(location)))
        return os.listdir(location)

    def lstat(self, location):
        self.calls.append(("lstat", str(location)))
        st = os.lstat(location)
        return _Reparse(st) if str(location) in self.reparse else st

    def stat(self, location, *args, **kwargs):
        self.calls.append(("stat", str(location)))
        return os.stat(location, *args, **kwargs)


class _Reparse:
    st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT

    def __init__(self, st) -> None:
        self._st = st

    def __getattr__(self, name):
        return getattr(self._st, name)


class FakeShutil:
    """store の `shutil` の代理（`disk_usage` の空きを決める ・失敗させる）。"""

    def __init__(self, free=None, error=False, shape_error=False) -> None:
        self.free, self.error, self.shape_error, self.calls = free, error, shape_error, []

    def disk_usage(self, location):
        self.calls.append(str(location))
        if self.error:
            raise OSError("INJECTED")
        if self.shape_error:
            return SimpleNamespace(free=-1)
        return SimpleNamespace(free=self.free if self.free is not None else 64 * 1024 ** 4)


def inject(monkeypatch, **kwargs) -> FaultyOs:
    proxy = FaultyOs(**kwargs)
    monkeypatch.setattr(ps, "os", proxy)
    return proxy


def make_vault(base: Path, name: str = "vault", *, plugins=None, human=True) -> Path:
    """人が用意する合成の vault（目印 ・`.obsidian` の 3 つの設定 ・`generated/` ・人の note）。"""
    vault = base / name
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ps.GENERATED_DIRECTORY).mkdir()
    (vault / ps.VAULT_MARKER_NAME).write_bytes(ps.vault_root_marker_bytes())
    for file_name, text in (PLUGINS if plugins is None else plugins).items():
        (vault / ".obsidian" / file_name).write_text(text, encoding="utf-8")
    if human:
        for relative in HUMAN_FILES:
            (vault / relative).parent.mkdir(parents=True, exist_ok=True)
            (vault / relative).write_text("human words, not generated\n", encoding="utf-8")
    return vault


def make_private(base: Path, name: str = "private", protected=None) -> Path:
    root = base / name
    ps.initialize_private_root(str(root), protected_roots={} if protected is None else protected)
    return root


def a3_publish(private: Path, gen) -> ms.PublishOutcome:
    """A3 の公開の API だけで合成の generation を memory root に公開する（試験の準備 ・A4b の store は使わない）。"""
    store = ms.open_memory_store(str(private / ps.MEMORY_CHILD), protected_roots={})
    lock = store.acquire_writer_lock(operation="BUILD", plan=gen.plan_digest)
    try:
        outcome = store.publish_generation(lock, gen)
    finally:
        assert lock.release() == ms.LOCK_RELEASED
    assert outcome.status in (ms.PublishStatus.PUBLISHED, ms.PublishStatus.REUSED), outcome.code
    return outcome


def open_store(private: Path, vault: Path, protected=None) -> ps.ProjectionStore:
    return ps.open_projection_store(str(private), str(vault), protected_roots={} if protected is None else protected)


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() and not p.is_symlink() else None, p.lstat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


def code_of(call, *args, **kwargs) -> str:
    with pytest.raises(ps.ProjectionStoreError) as exc:
        call(*args, **kwargs)
    return exc.value.code


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def private(base: Path) -> Path:
    return make_private(base)


@pytest.fixture
def vault(base: Path) -> Path:
    return make_vault(base)


@pytest.fixture
def store(private: Path, vault: Path) -> ps.ProjectionStore:
    return open_store(private, vault)


NOTE = b"---\nsynthetic note bytes for the store only\n"
LABEL = "p13pvn_" + "ab" * 12
DIGEST = "cd" * 32


# ================================================ 明示の初期化


def test_explicit_initialization_creates_only_the_marker_the_projection_layout_and_the_a3_root(base: Path) -> None:
    root = make_private(base)
    assert sorted(p.name for p in root.iterdir()) == [ps.PRIVATE_MARKER_NAME, ps.MEMORY_CHILD, ps.PROJECTION_CHILD]
    assert (root / ps.PRIVATE_MARKER_NAME).read_bytes() == ps.private_root_marker_bytes()
    assert sorted(p.name for p in (root / ps.PROJECTION_CHILD).iterdir()) == sorted(ps.PROJECTION_LAYOUT)
    assert all(not any((root / ps.PROJECTION_CHILD / n).iterdir()) for n in ps.PROJECTION_LAYOUT)        # 空の layout だけ
    memory = ms.open_memory_store(str(root / ps.MEMORY_CHILD), protected_roots={})                        # A3 が自分の layout を作った
    assert memory.read_publication().status is ms.ReadStatus.NOT_PUBLISHED
    marker = json.loads(ps.private_root_marker_bytes())
    assert set(marker) == {"schema_version", "root_class"} and ps.private_root_marker_bytes().endswith(b"}\n")
    assert code_of(ps.initialize_private_root, str(root), protected_roots={}) == ps.ROOT_ALREADY_INITIALIZED
    occupied = base / "occupied"
    occupied.mkdir()
    (occupied / "x").write_text("x")
    assert code_of(ps.initialize_private_root, str(occupied), protected_roots={}) == ps.ROOT_NOT_EMPTY
    assert code_of(ps.initialize_private_root, str(base / "a" / "b"), protected_roots={}) == ps.ROOT_PARENT_MISSING
    assert (occupied / "x").read_text() == "x"


def test_an_interrupted_initialization_is_left_in_place_and_cannot_be_opened(monkeypatch, base: Path, vault: Path) -> None:
    inject(monkeypatch, faults={"mkdir": lambda location: location.endswith(ps.STAGING_DIRECTORY)})
    assert code_of(ps.initialize_private_root, str(base / "private"), protected_roots={}) == ps.STORE_IO_FAILED
    monkeypatch.undo()
    assert (base / "private" / ps.PRIVATE_MARKER_NAME).is_file()                                    # 途中の layout は残す（消さない）
    assert code_of(open_store, base / "private", vault) in (ps.LAYOUT_INVALID, ps.UNKNOWN_ENTRY)


@pytest.mark.parametrize("bad", ["relative/root", "", " /x", "/x/../y", "/x/./y", "/x//y", 7, None])
def test_root_shapes_must_be_explicit_absolute_and_normalized(base: Path, vault: Path, bad) -> None:
    assert code_of(ps.open_projection_store, bad, str(vault), protected_roots={}) == ps.ROOT_INVALID
    assert code_of(ps.open_projection_store, str(base), bad, protected_roots={}) == ps.ROOT_INVALID
    assert code_of(ps.initialize_private_root, bad, protected_roots={}) == ps.ROOT_INVALID


# ================================================ vault ・Obsidian の設定 ・root の重なり


@pytest.mark.parametrize("mutate, code", [
    (lambda v: (v / ps.VAULT_MARKER_NAME).unlink(), ps.VAULT_MARKER_MISSING),
    (lambda v: (v / ps.VAULT_MARKER_NAME).write_bytes(b"{}\n"), ps.VAULT_MARKER_INVALID),
    (lambda v: (v / ps.VAULT_MARKER_NAME).write_bytes(ps.vault_root_marker_bytes() + b" "), ps.VAULT_MARKER_INVALID),
    (lambda v: os.rename(v / ".obsidian", v / "obsidian-moved"), ps.VAULT_INVALID),
    (lambda v: os.rename(v / ps.GENERATED_DIRECTORY, v / "generated-moved"), ps.VAULT_GENERATED_MISSING),
])
def test_the_human_placed_marker_obsidian_directory_and_generated_directory_are_required(private: Path, vault: Path, mutate, code) -> None:
    mutate(vault)
    assert code_of(open_store, private, vault) == code


def test_a_symlinked_generated_directory_or_marker_is_refused(base: Path, private: Path, vault: Path) -> None:
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    os.rename(vault / ps.GENERATED_DIRECTORY, vault / "generated-real")
    (vault / ps.GENERATED_DIRECTORY).symlink_to(elsewhere, target_is_directory=True)
    assert code_of(open_store, private, vault) == ps.ROOT_UNSAFE_COMPONENT
    (vault / ps.GENERATED_DIRECTORY).unlink()
    os.rename(vault / "generated-real", vault / ps.GENERATED_DIRECTORY)
    (base / "marker").write_bytes(ps.vault_root_marker_bytes())
    (vault / ps.VAULT_MARKER_NAME).unlink()
    (vault / ps.VAULT_MARKER_NAME).symlink_to(base / "marker")
    assert code_of(open_store, private, vault) == ps.UNSAFE_ENTRY


@pytest.mark.parametrize("files, code", [
    ({"core-plugins.json": '["sync"]'}, ps.PLUGIN_REFUSED),
    ({"core-plugins.json": '{"publish": true, "backlink": true}'}, ps.PLUGIN_REFUSED),
    ({"core-plugins.json": '{"publish": false, "sync": false}'}, None),
    ({"community-plugins.json": '["dataview", "obsidian-git"]'}, ps.PLUGIN_REFUSED),
    ({"community-plugins.json": '["remotely-save"]'}, ps.PLUGIN_REFUSED),
    ({"community-plugins.json": '["obsidian-livesync"]'}, ps.PLUGIN_REFUSED),
    ({"community-plugins.json": '["dataview"]'}, None),
    ({"app.json": '{"alwaysUpdateLinks": true}'}, ps.PLUGIN_REFUSED),
    ({"app.json": '{"alwaysUpdateLinks": "true"}'}, None),
    ({"app.json": "[]"}, ps.PLUGIN_STATE_UNVERIFIED),
    ({"core-plugins.json": "{not json"}, ps.PLUGIN_STATE_UNVERIFIED),
    ({"core-plugins.json": '[1, 2]'}, ps.PLUGIN_STATE_UNVERIFIED),
    ({"community-plugins.json": '{"a": true}'}, ps.PLUGIN_STATE_UNVERIFIED),
    ({"core-plugins.json": "[" + '"x",' * 40000 + '"y"]'}, ps.PLUGIN_STATE_UNVERIFIED),         # 有界の読み
    ({"core-plugins.json": None}, ps.PLUGIN_STATE_UNVERIFIED),                                  # 無い設定は検証できない
    ({"app.json": None}, ps.PLUGIN_STATE_UNVERIFIED),
])
def test_plugin_state_is_read_bounded_and_known_unsafe_configurations_are_refused(base: Path, private: Path, files, code) -> None:
    plugins = dict(PLUGINS)
    for name, text in files.items():
        if text is None:
            plugins.pop(name)
        else:
            plugins[name] = text
    vault = make_vault(base, plugins=plugins)
    if code is None:
        assert isinstance(open_store(private, vault), ps.ProjectionStore)
    else:
        assert code_of(open_store, private, vault) == code


def test_a_symlinked_plugin_state_file_cannot_be_verified(base: Path, private: Path, vault: Path) -> None:
    (base / "core.json").write_text('["file-explorer"]')
    (vault / ".obsidian" / "core-plugins.json").unlink()
    (vault / ".obsidian" / "core-plugins.json").symlink_to(base / "core.json")
    assert code_of(open_store, private, vault) == ps.PLUGIN_STATE_UNVERIFIED


@pytest.mark.parametrize("where, marker, code", [
    ("parent", ".git", ps.VAULT_WORKING_TREE), ("vault", ".git", ps.VAULT_WORKING_TREE),
    ("parent", ".dropbox", ps.VAULT_SYNC_FOLDER), ("vault", ".stfolder", ps.VAULT_SYNC_FOLDER),
    ("parent", ".obsidian", ps.ROOT_INSIDE_VAULT),
])
def test_vaults_in_working_trees_sync_folders_or_other_vaults_are_refused(base: Path, private: Path, where, marker, code) -> None:
    holder = base / "holder"
    holder.mkdir()
    vault = make_vault(holder)
    (holder if where == "parent" else vault).joinpath(marker).mkdir()
    assert code_of(open_store, private, vault) == code


@pytest.mark.parametrize("folder", ["OneDrive", "Dropbox", "iCloud Drive", "OneDrive - Org"])
def test_known_sync_folder_names_refuse_the_vault_and_the_private_root(base: Path, folder: str) -> None:
    synced = base / folder
    synced.mkdir()
    private = make_private(base)
    vault = make_vault(synced)
    assert code_of(open_store, private, vault) == ps.VAULT_SYNC_FOLDER
    assert code_of(ps.initialize_private_root, str(synced / "private"), protected_roots={}) == ps.ROOT_SYNC_FOLDER


def test_overlapping_private_vault_protected_and_repository_roots_are_refused(base: Path, private: Path, vault: Path) -> None:
    inner_vault = make_vault(private / ps.PROJECTION_CHILD / ps.STAGING_DIRECTORY, human=False)
    assert code_of(open_store, private, inner_vault) == ps.ROOT_OVERLAP                              # vault が private な root の中
    nested = make_vault(base, "outer")
    inner_private = nested / "private_inside"
    assert code_of(ps.initialize_private_root, str(inner_private), protected_roots={}) == ps.ROOT_INSIDE_VAULT
    assert code_of(open_store, private, vault, {"P10": vault / "notes"}) == ps.ROOT_OVERLAP           # 保護の root と重なる
    assert code_of(open_store, private, vault, {"P9": private}) == ps.ROOT_OVERLAP
    for reserved in (ps.PROJECTION_ROOT_LABEL, ps.VAULT_ROOT_LABEL, ms.CODE_REPOSITORY_LABEL):
        assert code_of(open_store, private, vault, {reserved: base / "other"}) == ps.PROTECTED_ROOT_INVALID
    assert code_of(open_store, private, vault, {"lower": base / "other"}) == ps.PROTECTED_ROOT_INVALID
    assert code_of(ps.open_projection_store, str(private), str(vault), protected_roots=[]) == ps.PROTECTED_ROOT_INVALID
    repository = Path(__file__).resolve().parents[2]
    assert code_of(ps.open_projection_store, str(private), str(repository), protected_roots={}) in (ps.ROOT_OVERLAP, ps.VAULT_WORKING_TREE)
    assert open_store(private, vault, {"P9": base / "p9_private_root"}).protected_labels == ("CODE_REPOSITORY", "P9")


def test_symlinked_roots_ancestors_and_reparse_points_are_refused(monkeypatch, base: Path, private: Path, vault: Path) -> None:
    (base / "link_private").symlink_to(private, target_is_directory=True)
    assert code_of(open_store, base / "link_private", vault) in (ps.ROOT_UNSAFE_COMPONENT, ps.ROOT_OVERLAP)
    (base / "link_vault").symlink_to(vault, target_is_directory=True)
    assert code_of(open_store, private, base / "link_vault") in (ps.ROOT_UNSAFE_COMPONENT, ps.ROOT_OVERLAP)
    inject(monkeypatch, reparse=(vault / ps.GENERATED_DIRECTORY,))                                   # Windows の reparse point の bit の模擬
    assert code_of(open_store, private, vault) == ps.ROOT_UNSAFE_COMPONENT
    monkeypatch.undo()
    inject(monkeypatch, reparse=(private,))
    assert code_of(open_store, private, vault) == ps.ROOT_UNSAFE_COMPONENT


def test_unknown_entries_in_the_composition_root_or_projection_are_refused(private: Path, vault: Path) -> None:
    (private / "extra").mkdir()
    assert code_of(open_store, private, vault) == ps.UNKNOWN_ENTRY
    (private / "extra").rmdir()
    (private / ps.PROJECTION_CHILD / "archive").mkdir()
    assert code_of(open_store, private, vault) == ps.UNKNOWN_ENTRY
    (private / ps.PROJECTION_CHILD / "archive").rmdir()
    (private / ps.PRIVATE_MARKER_NAME).write_bytes(b"{}\n")
    assert code_of(open_store, private, vault) == ps.MARKER_INVALID


# ================================================ 2 つの writer lock


def test_the_double_lock_is_exclusive_ordered_and_a_second_lock_failure_releases_only_the_first(private: Path, vault: Path,
                                                                                               store: ps.ProjectionStore) -> None:
    private_lock = private / ps.PROJECTION_CHILD / ps.LOCKS_DIRECTORY / ps.EXPORT_LOCK_NAME
    vault_lock = vault / ps.GENERATED_DIRECTORY / ps.VAULT_LOCK_NAME
    locks = store.acquire_locks(operation="PUBLISH")
    assert private_lock.read_bytes() == ps.lock_record(ps.LOCK_SCOPE_PRIVATE, "PUBLISH")
    assert vault_lock.read_bytes() == ps.lock_record(ps.LOCK_SCOPE_VAULT, "PUBLISH")
    assert private_lock.read_bytes() != vault_lock.read_bytes()                                    # 独立した identity と byte
    assert code_of(store.acquire_locks, operation="PUBLISH") == ps.PRIVATE_LOCK_PRESENT
    assert locks.release() == (ps.LOCK_RELEASED, ps.LOCK_RELEASED)
    assert not private_lock.exists() and not vault_lock.exists()
    assert locks.release() == (ps.LOCK_RELEASED, ps.LOCK_RELEASED)                                  # 1 回だけ（2 回目は同じ code）
    foreign = b"not ours\n"
    vault_lock.write_bytes(foreign)                                                                 # 他の root の vault の lock
    with pytest.raises(ps.ProjectionStoreError) as exc:
        store.acquire_locks(operation="PUBLISH")
    assert exc.value.code == ps.VAULT_LOCK_PRESENT and exc.value.detail == ps.LOCK_RELEASED          # 所有した private だけを解放した
    assert not private_lock.exists() and vault_lock.read_bytes() == foreign                         # 他の lock は動かさない
    assert code_of(store.acquire_locks, operation="TAKEOVER") == ps.STORE_INPUT_INVALID
    for record in (ps.lock_record(ps.LOCK_SCOPE_PRIVATE, "PRESERVE"), ps.lock_record(ps.LOCK_SCOPE_VAULT, "PUBLISH")):
        assert set(json.loads(record)) == {"schema_version", "scope", "operation"}                  # pid ・時刻 ・host ・user は無い


@pytest.mark.parametrize("which", ["private", "vault"])
def test_lost_lock_ownership_blocks_every_write_and_the_replaced_lock_is_never_released(private: Path, vault: Path,
                                                                                         store: ps.ProjectionStore, which) -> None:
    locks = store.acquire_locks(operation="PUBLISH")
    lock = private / ps.PROJECTION_CHILD / ps.LOCKS_DIRECTORY / ps.EXPORT_LOCK_NAME if which == "private" else \
        vault / ps.GENERATED_DIRECTORY / ps.VAULT_LOCK_NAME
    data = lock.read_bytes()
    swapped = lock.with_name("swap")
    swapped.write_bytes(data)
    os.replace(swapped, lock)                                                                       # 同じ byte ・別の file（identity が違う）
    assert not locks.owned()
    for call in (lambda: store.check_locks(locks), lambda: store.snapshot_private(locks), lambda: store.snapshot_vault(locks),
                 lambda: store.stage_notes(locks, LABEL, {LABEL + ".md": NOTE}, ()),
                 lambda: store.write_record(locks, ps.FAILURES_DIRECTORY, DIGEST, b"{}\n"),
                 lambda: store.write_evidence_bundle(locks, ps.BUNDLES_DIRECTORY, DIGEST, {ps.SCAN_RECORD: b"{}\n"}),
                 lambda: store.replace_pointer(locks, None, NOTE, DIGEST), lambda: store.move_staged(locks, LABEL),
                 lambda: store.preserve(locks, "STAGING", LABEL), lambda: store.free_space(locks)):
        assert code_of(call) == ps.LOCK_OWNERSHIP_UNVERIFIED
    released = locks.release()
    assert (released[0] if which == "vault" else released[1]) == ps.LOCK_OWNERSHIP_UNVERIFIED
    assert (released[1] if which == "vault" else released[0]) == ps.LOCK_RELEASED                   # もう一方は所有を検証して解放
    assert lock.read_bytes() == data                                                                # 所有を検証できない lock は残す
    assert not list((vault / ps.GENERATED_DIRECTORY).glob("p13pvn_*"))


def test_a_lock_release_failure_is_reported_and_the_lock_is_kept(monkeypatch, vault: Path, store: ps.ProjectionStore) -> None:
    locks = store.acquire_locks(operation="PUBLISH")
    inject(monkeypatch, faults={"unlink": lambda location: location.endswith(ps.VAULT_LOCK_NAME)})
    assert locks.release() == (ps.LOCK_RELEASE_FAILED, ps.LOCK_RELEASED)                            # vault が失敗しても private は解放を試す
    monkeypatch.undo()
    assert (vault / ps.GENERATED_DIRECTORY / ps.VAULT_LOCK_NAME).is_file()
    assert code_of(store.acquire_locks, operation="PUBLISH") == ps.VAULT_LOCK_PRESENT               # 奪取 ・自動の除去は無い


def test_two_private_roots_racing_for_one_vault_never_both_hold_the_vault_lock(base: Path, vault: Path) -> None:
    stores = [open_store(make_private(base, f"private_{i}"), vault) for i in range(2)]
    barrier, outcomes = threading.Barrier(2), {}

    def race(index: int) -> None:
        barrier.wait()
        try:
            outcomes[index] = stores[index].acquire_locks(operation="PUBLISH")
        except ps.ProjectionStoreError as exc:
            outcomes[index] = exc.code
    for _ in range(5):
        outcomes.clear()
        workers = [threading.Thread(target=race, args=(i,)) for i in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        held = [o for o in outcomes.values() if isinstance(o, ps.ExportLocks)]
        refused = [o for o in outcomes.values() if not isinstance(o, ps.ExportLocks)]
        assert len(held) == 1 and refused == [ps.VAULT_LOCK_PRESENT], outcomes                       # vault の lock は 1 つだけ
        loser = stores[[i for i, o in outcomes.items() if not isinstance(o, ps.ExportLocks)][0]]
        assert not (Path(loser.projection_location) / ps.LOCKS_DIRECTORY / ps.EXPORT_LOCK_NAME).exists()   # 負けた側は自分の lock を解放
        assert held[0].release() == (ps.LOCK_RELEASED, ps.LOCK_RELEASED)
    assert sorted(p.name for p in (vault / ps.GENERATED_DIRECTORY).iterdir()) == []                 # 何も書いていない


# ================================================ 観測の厳密さ


def _locked(store: ps.ProjectionStore) -> ps.ExportLocks:
    return store.acquire_locks(operation="PUBLISH")


@pytest.mark.parametrize("make, code", [
    (lambda g: (g / "Untitled.md").write_text("x"), ps.UNKNOWN_ENTRY),                             # Obsidian が作った note
    (lambda g: (g / ".DS_Store").write_bytes(b"x"), ps.UNKNOWN_ENTRY),                              # OS の metadata
    (lambda g: (g / "P13-memory.md").write_text("x"), ps.UNKNOWN_ENTRY),                            # 大小だけ違う名前
    (lambda g: (g / ("p13pvn_" + "AB" * 12)).mkdir(), ps.UNKNOWN_ENTRY),
    (lambda g: (g / "p13pvn_é.md").write_text("x"), ps.UNKNOWN_ENTRY),                              # ASCII 以外
    (lambda g: (g / "p13-memory (conflict).md").write_text("x"), ps.UNKNOWN_ENTRY),                 # 同期の競合の複製
    (lambda g: (g / LABEL).mkdir() or (g / LABEL / "notes.txt").write_text("x"), ps.UNKNOWN_ENTRY),
    (lambda g: (g / LABEL).mkdir() or (g / LABEL / "sub").mkdir(), ps.UNKNOWN_ENTRY),
    (lambda g: (g / ps.POINTER_NOTE_NAME).mkdir(), ps.UNSAFE_ENTRY),
    (lambda g: (g / ps.VAULT_STAGING_DIRECTORY).mkdir() or (g / ps.VAULT_STAGING_DIRECTORY / "other.tmp").write_text("x"), ps.UNKNOWN_ENTRY),
    (lambda g: (g / ps.VAULT_INTERRUPTED_DIRECTORY).mkdir() or (g / ps.VAULT_INTERRUPTED_DIRECTORY / "x").mkdir(), ps.UNKNOWN_ENTRY),
])
def test_unknown_metadata_case_variant_and_foreign_entries_in_generated_fail_closed(store: ps.ProjectionStore, vault: Path, make, code) -> None:
    make(vault / ps.GENERATED_DIRECTORY)
    locks = _locked(store)
    try:
        assert code_of(store.snapshot_vault, locks) == code
    finally:
        locks.release()


def test_hard_links_and_symlinks_inside_generated_are_refused(base: Path, store: ps.ProjectionStore, vault: Path) -> None:
    generated = vault / ps.GENERATED_DIRECTORY
    (generated / LABEL).mkdir()
    (base / "outside.md").write_bytes(NOTE)
    os.link(base / "outside.md", generated / LABEL / (LABEL + ".md"))                              # hard link（別の名前で同じ file）
    locks = _locked(store)
    try:
        assert code_of(store.snapshot_vault, locks) == ps.UNSAFE_ENTRY
        (generated / LABEL / (LABEL + ".md")).unlink()
        (generated / LABEL / (LABEL + ".md")).symlink_to(base / "outside.md")
        assert code_of(store.snapshot_vault, locks) == ps.UNSAFE_ENTRY
    finally:
        locks.release()


def test_interrupted_residue_is_measured_by_size_but_never_read(monkeypatch, store: ps.ProjectionStore, vault: Path) -> None:
    preserved = vault / ps.GENERATED_DIRECTORY / ps.VAULT_INTERRUPTED_DIRECTORY / f"{LABEL}.001.interrupted"
    preserved.mkdir(parents=True)
    (preserved / (LABEL + ".md")).write_bytes(b"x" * 5000)
    locks = _locked(store)
    proxy = inject(monkeypatch)
    try:
        snapshot = store.snapshot_vault(locks)
    finally:
        monkeypatch.undo()
        locks.release()
    assert snapshot.interrupted == (f"{LABEL}.001.interrupted",) and snapshot.versions == {} and snapshot.staging == {}
    assert snapshot.used_bytes >= 4 * ps.SIZE_UNIT + 2 * ps.SIZE_UNIT                              # generated ・lock ・2 つの directory ・切り上げた file
    opened = [location for operation, location in proxy.calls if operation == "open"]
    assert not any(ps.VAULT_INTERRUPTED_DIRECTORY in location for location in opened)                # 中身は読まない


def test_unknown_or_unsafe_private_evidence_entries_fail_closed(private: Path, store: ps.ProjectionStore) -> None:
    projection = private / ps.PROJECTION_CHILD
    locks = _locked(store)
    try:
        for make in (lambda: (projection / ps.BUNDLES_DIRECTORY / "not-a-digest").mkdir(),
                     lambda: (projection / ps.BUNDLES_DIRECTORY / DIGEST).mkdir() or (projection / ps.BUNDLES_DIRECTORY / DIGEST / "x.json").write_text("x"),
                     lambda: (projection / ps.COMPLETIONS_DIRECTORY / "x.json").write_text("x"),
                     lambda: (projection / ps.STAGING_DIRECTORY / "random.tmp").write_text("x"),
                     lambda: (projection / ps.LOCKS_DIRECTORY / "other.lock").write_text("x")):
            make()
            assert code_of(store.snapshot_private, locks) == ps.UNKNOWN_ENTRY
            for child in sorted(projection.rglob("*"), reverse=True):
                if child.name in ("not-a-digest", DIGEST, "x.json", "random.tmp", "other.lock"):
                    child.unlink() if child.is_file() else child.rmdir()
        assert store.snapshot_private(locks).bundles == {}
    finally:
        locks.release()


# ================================================ 書き込みの primitive（追加 ・置き換えない ・上書きしない）


def test_evidence_bundles_appear_by_one_rename_resume_identical_residue_and_are_never_overwritten(private: Path,
                                                                                                   store: ps.ProjectionStore) -> None:
    files = {ps.SCAN_RECORD: b'{"a":1}\n', ps.SOURCE_RECORD: b'{"b":2}\n', ps.BINDING_RECORD: b'{"c":3}\n'}
    staging = private / ps.PROJECTION_CHILD / ps.STAGING_DIRECTORY
    final = private / ps.PROJECTION_CHILD / ps.BINDINGS_DIRECTORY / DIGEST
    locks = _locked(store)
    try:
        partial = staging / f"binding.{DIGEST}.partial"
        partial.mkdir()
        (partial / ps.SCAN_RECORD).write_bytes(files[ps.SCAN_RECORD])                                # 中断した残り（byte 一致）
        before = (partial / ps.SCAN_RECORD).stat().st_ino
        assert store.write_evidence_bundle(locks, ps.BINDINGS_DIRECTORY, DIGEST, files) == ps.EVIDENCE_RECORDED
        assert not partial.exists() and (final / ps.SCAN_RECORD).stat().st_ino == before              # 在った file は触らずに続けた
        assert {p.name: p.read_bytes() for p in final.iterdir()} == files
        assert store.write_evidence_bundle(locks, ps.BINDINGS_DIRECTORY, DIGEST, files) == ps.EVIDENCE_ALREADY_RECORDED
        changed = {**files, ps.SCAN_RECORD: b'{"a":9}\n'}
        assert code_of(store.write_evidence_bundle, locks, ps.BINDINGS_DIRECTORY, DIGEST, changed) == ps.EVIDENCE_CONFLICT
        assert {p.name: p.read_bytes() for p in final.iterdir()} == files                            # 上書きしない
        other = "ef" * 32
        torn = staging / f"bundle.{other}.partial"
        torn.mkdir()
        (torn / ps.SCAN_RECORD).write_bytes(b'{"a"')                                                   # 期待の byte と違う残り
        assert code_of(store.write_evidence_bundle, locks, ps.BUNDLES_DIRECTORY, other, files) == ps.STAGING_CONFLICT
        assert (torn / ps.SCAN_RECORD).read_bytes() == b'{"a"' and not (private / ps.PROJECTION_CHILD / ps.BUNDLES_DIRECTORY / other).exists()
        assert code_of(store.write_evidence_bundle, locks, "archive", DIGEST, files) == ps.STORE_INPUT_INVALID
        assert code_of(store.write_evidence_bundle, locks, ps.BUNDLES_DIRECTORY, DIGEST, {"other.json": b"x"}) == ps.STORE_INPUT_INVALID
    finally:
        locks.release()


def test_records_resume_an_identical_temp_and_are_never_overwritten(private: Path, store: ps.ProjectionStore) -> None:
    staging = private / ps.PROJECTION_CHILD / ps.STAGING_DIRECTORY
    final = private / ps.PROJECTION_CHILD / ps.COMPLETIONS_DIRECTORY / f"{DIGEST}.json"
    locks = _locked(store)
    try:
        (staging / f"completion.{DIGEST}.tmp").write_bytes(b'{"x":1}\n')
        assert store.write_record(locks, ps.COMPLETIONS_DIRECTORY, DIGEST, b'{"x":1}\n') == ps.EVIDENCE_RECORDED
        assert final.read_bytes() == b'{"x":1}\n' and not any(staging.iterdir())
        assert store.write_record(locks, ps.COMPLETIONS_DIRECTORY, DIGEST, b'{"x":1}\n') == ps.EVIDENCE_ALREADY_RECORDED
        assert code_of(store.write_record, locks, ps.COMPLETIONS_DIRECTORY, DIGEST, b'{"x":2}\n') == ps.EVIDENCE_CONFLICT
        assert final.read_bytes() == b'{"x":1}\n'
        (staging / f"failure.{DIGEST}.tmp").write_bytes(b"{")
        assert code_of(store.write_record, locks, ps.FAILURES_DIRECTORY, DIGEST, b'{"y":1}\n') == ps.STAGING_CONFLICT
        assert (staging / f"failure.{DIGEST}.tmp").read_bytes() == b"{"                                # 違う残りは触らない
    finally:
        locks.release()


def test_failure_records_never_adopt_a_leftover_temp_and_finalize_only_their_own_verified_temp(monkeypatch, private: Path,
                                                                                               store: ps.ProjectionStore) -> None:
    staging = private / ps.PROJECTION_CHILD / ps.STAGING_DIRECTORY
    failures = private / ps.PROJECTION_CHILD / ps.FAILURES_DIRECTORY
    data = b'{"f":1}\n'
    locks = _locked(store)
    try:
        leftover = staging / f"failure.{DIGEST}.tmp"
        leftover.write_bytes(data)                                                                   # byte が同じでも前から在る一時 file
        assert code_of(store.write_record, locks, ps.FAILURES_DIRECTORY, DIGEST, data) == ps.STAGING_CONFLICT
        assert leftover.read_bytes() == data and not any(failures.iterdir())                          # 採らない ・消さない ・移さない
        other = "ef" * 32
        temp = staging / f"failure.{other}.tmp"

        original_owned = ps._owned

        def swapped_then_checked(location, identity, payload):                                       # 書いた後 ・確定の前に一時 file が替わる
            if location == str(temp):
                swapped = temp.with_name("swap")
                swapped.write_bytes(data)
                os.replace(swapped, temp)                                                            # 同じ byte ・別の file
            return original_owned(location, identity, payload)
        monkeypatch.setattr(ps, "_owned", swapped_then_checked)
        assert code_of(store.write_record, locks, ps.FAILURES_DIRECTORY, other, data) == ps.STAGING_CONFLICT   # 所有を確かめられない
        monkeypatch.undo()
        assert temp.read_bytes() == data and not (failures / f"{other}.json").exists()               # 替わった一時 file は rename しない
        third = "12" * 32
        assert store.write_record(locks, ps.FAILURES_DIRECTORY, third, data) == ps.EVIDENCE_RECORDED   # 自分が作った一時 file だけを確定する
        assert (failures / f"{third}.json").read_bytes() == data and not (staging / f"failure.{third}.tmp").exists()
        assert store.write_record(locks, ps.FAILURES_DIRECTORY, third, data) == ps.EVIDENCE_ALREADY_RECORDED
    finally:
        locks.release()


def test_staging_creates_only_missing_notes_and_never_overwrites(vault: Path, store: ps.ProjectionStore) -> None:
    folder = vault / ps.GENERATED_DIRECTORY / ps.VAULT_STAGING_DIRECTORY / LABEL
    first, second = LABEL + ".md", LABEL + "-s001.md"
    locks = _locked(store)
    try:
        store.stage_notes(locks, LABEL, {first: NOTE}, ())
        identity = (folder / first).stat().st_ino
        assert code_of(store.stage_notes, locks, LABEL, {second: NOTE}, ()) == ps.STAGING_CONFLICT     # 在る file の集合が違う
        assert code_of(store.stage_notes, locks, LABEL, {first: b"other"}, (first,)) == ps.STORE_INPUT_INVALID
        store.stage_notes(locks, LABEL, {second: NOTE + b"2"}, (first,))
        assert (folder / first).stat().st_ino == identity and (folder / first).read_bytes() == NOTE   # 在る file は触らない
        assert (folder / second).read_bytes() == NOTE + b"2"
        assert code_of(store.stage_notes, locks, LABEL, {"bad name.md": NOTE}, ()) == ps.STORE_INPUT_INVALID
    finally:
        locks.release()


def test_version_moves_never_replace_an_existing_folder(vault: Path, store: ps.ProjectionStore) -> None:
    generated = vault / ps.GENERATED_DIRECTORY
    locks = _locked(store)
    try:
        store.stage_notes(locks, LABEL, {LABEL + ".md": NOTE}, ())
        (generated / LABEL).mkdir()                                                                  # 既に在る（空でも置き換えない）
        assert code_of(store.move_staged, locks, LABEL) == ps.VERSION_CONFLICT
        (generated / LABEL).rmdir()
        store.move_staged(locks, LABEL)
        assert (generated / LABEL / (LABEL + ".md")).read_bytes() == NOTE
        assert not (generated / ps.VAULT_STAGING_DIRECTORY / LABEL).exists()
        assert code_of(store.move_staged, locks, LABEL) == ps.STAGING_CONFLICT
    finally:
        locks.release()


@pytest.mark.skipif(os.name == "nt", reason="POSIX の予約の中断だけ")
def test_an_interrupted_posix_version_move_leaves_only_the_empty_reservation(monkeypatch, vault: Path, store: ps.ProjectionStore) -> None:
    generated = vault / ps.GENERATED_DIRECTORY
    locks = _locked(store)
    try:
        store.stage_notes(locks, LABEL, {LABEL + ".md": NOTE}, ())
        inject(monkeypatch, faults={"rename": lambda location: location.endswith(LABEL)})
        assert code_of(store.move_staged, locks, LABEL) == ps.STORE_IO_FAILED
        monkeypatch.undo()
        assert (generated / LABEL).is_dir() and not any((generated / LABEL).iterdir())                # 空の予約だけ（A4a1 の VERSION_RESERVED_EMPTY）
        assert (generated / ps.VAULT_STAGING_DIRECTORY / LABEL / (LABEL + ".md")).read_bytes() == NOTE
    finally:
        locks.release()


def test_pointer_replacement_checks_the_expected_pointer_and_resumes_only_an_identical_temp(vault: Path, store: ps.ProjectionStore) -> None:
    generated = vault / ps.GENERATED_DIRECTORY
    temp = generated / ps.VAULT_STAGING_DIRECTORY / f"p13-memory.{DIGEST}.tmp"
    locks = _locked(store)
    try:
        assert code_of(store.replace_pointer, locks, b"something else", NOTE, DIGEST) == ps.POINTER_CHANGED
        assert temp.read_bytes() == NOTE and not (generated / ps.POINTER_NOTE_NAME).exists()          # 一時 file は残る（次に続ける）
        store.replace_pointer(locks, None, NOTE, DIGEST)
        assert (generated / ps.POINTER_NOTE_NAME).read_bytes() == NOTE and not temp.exists()
        temp.write_bytes(b"torn")
        assert code_of(store.replace_pointer, locks, NOTE, NOTE + b"2", DIGEST) == ps.STAGING_CONFLICT
        assert (generated / ps.POINTER_NOTE_NAME).read_bytes() == NOTE and temp.read_bytes() == b"torn"
    finally:
        locks.release()


def test_preservation_uses_numbered_slots_requires_an_empty_reservation_and_never_replaces(vault: Path, store: ps.ProjectionStore) -> None:
    generated = vault / ps.GENERATED_DIRECTORY
    interrupted = generated / ps.VAULT_INTERRUPTED_DIRECTORY
    locks = _locked(store)
    try:
        store.stage_notes(locks, LABEL, {LABEL + ".md": NOTE}, ())
        assert store.preserve(locks, "STAGING", LABEL) == f"{LABEL}.001.interrupted"
        store.stage_notes(locks, LABEL, {LABEL + ".md": NOTE + b"x"}, ())
        assert store.preserve(locks, "STAGING", LABEL) == f"{LABEL}.002.interrupted"
        assert (interrupted / f"{LABEL}.001.interrupted" / (LABEL + ".md")).read_bytes() == NOTE    # 先の保存は置き換えない
        (generated / LABEL).mkdir()
        (generated / LABEL / (LABEL + ".md")).write_bytes(NOTE)
        assert code_of(store.preserve, locks, "VERSION_RESERVATION", LABEL) == ps.RESERVATION_NOT_EMPTY
        assert (generated / LABEL / (LABEL + ".md")).read_bytes() == NOTE                            # 空でない版は動かさない
        assert code_of(store.preserve, locks, "VERSION", LABEL) == ps.STORE_INPUT_INVALID
        assert code_of(store.preserve, locks, "STAGING", LABEL) == ps.UNSAFE_ENTRY                   # 無い staging
    finally:
        locks.release()


# ================================================ 空き容量 ・記録した操作の範囲 ・code


def test_free_space_comes_only_from_disk_usage_and_unknown_values_are_unverified(monkeypatch, store: ps.ProjectionStore) -> None:
    locks = _locked(store)
    try:
        fake = FakeShutil(free=123 * ps.SIZE_UNIT)
        monkeypatch.setattr(ps, "shutil", fake)
        space = store.free_space(locks)
        assert (space.vault_free, space.private_free, space.same_volume) == (123 * ps.SIZE_UNIT, 123 * ps.SIZE_UNIT, True)
        assert len(fake.calls) == 2 and store.private_free_space(locks) == 123 * ps.SIZE_UNIT
        monkeypatch.setattr(ps, "shutil", FakeShutil(error=True))
        assert code_of(store.free_space, locks) == ps.CAPACITY_UNVERIFIED
        monkeypatch.setattr(ps, "shutil", FakeShutil(shape_error=True))
        assert code_of(store.free_space, locks) == ps.CAPACITY_UNVERIFIED
    finally:
        locks.release()
    assert ps.storage_units(0) == ps.storage_units(1) == ps.SIZE_UNIT and ps.storage_units(ps.SIZE_UNIT + 1) == 2 * ps.SIZE_UNIT


def test_every_store_operation_stays_in_projection_and_generated_and_never_lists_human_notes(monkeypatch, base: Path, private: Path,
                                                                                            vault: Path) -> None:
    before = {relative: (vault / relative).read_bytes() for relative in HUMAN_FILES}
    mtimes = {relative: (vault / relative).stat().st_mtime_ns for relative in HUMAN_FILES}
    proxy = inject(monkeypatch)
    store = open_store(private, vault)
    locks = _locked(store)
    try:
        store.snapshot_private(locks)
        store.snapshot_vault(locks)
        store.stage_notes(locks, LABEL, {LABEL + ".md": NOTE}, ())
        store.move_staged(locks, LABEL)
        store.replace_pointer(locks, None, NOTE, DIGEST)
        store.write_record(locks, ps.COMPLETIONS_DIRECTORY, DIGEST, b"{}\n")
    finally:
        locks.release()
        monkeypatch.undo()
    projection, generated = str(private / ps.PROJECTION_CHILD), str(vault / ps.GENERATED_DIRECTORY)
    writes = [(op, location) for op, location in proxy.calls if op in MUTATIONS]
    assert writes and all(location.startswith((projection + os.sep, generated + os.sep)) or location in (projection, generated)
                          for _, location in writes), writes                                       # 書くのは projection と generated だけ
    listed = {location for op, location in proxy.calls if op == "listdir"}
    assert str(vault) not in listed and not any(location.startswith(str(vault / "notes")) for location in listed)   # vault の root ・人の note は一覧しない
    assert all(location.startswith((str(private), generated)) for location in listed), listed
    opened = {location for op, location in proxy.calls if op == "open"}
    allowed = {str(vault / ps.VAULT_MARKER_NAME)} | {str(vault / ".obsidian" / n) for n in ps.PLUGIN_STATE_FILES}
    assert all(location in allowed or location.startswith((str(private), generated)) for location in opened), opened
    assert not any("workspace.json" in location or "plugins" in location.split(os.sep) for _, location in proxy.calls)
    assert {relative: (vault / relative).read_bytes() for relative in HUMAN_FILES} == before        # 人の file は byte ・mtime も不変
    assert {relative: (vault / relative).stat().st_mtime_ns for relative in HUMAN_FILES} == mtimes


def test_errors_reprs_and_records_hold_only_constant_codes_and_no_locations(base: Path, private: Path, vault: Path) -> None:
    store = open_store(private, vault, {"P9": base / "p9_private_root"})
    locks = _locked(store)
    try:
        for text in (repr(store), repr(locks), str(ps.ProjectionStoreError(ps.ROOT_OVERLAP, "P9"))):
            assert str(base) not in text and "private" not in text.replace("private=", "")
    finally:
        assert locks.release() == (ps.LOCK_RELEASED, ps.LOCK_RELEASED)
    for record in (ps.private_root_marker_bytes(), ps.vault_root_marker_bytes(), ps.lock_record(ps.LOCK_SCOPE_VAULT, "PUBLISH")):
        value = json.loads(record)
        assert not set(value) & {"pid", "host", "time", "user", "path", "root", "created_at"} and str(base).encode() not in record
    with pytest.raises(ps.ProjectionStoreError):
        ps.ProjectionStore("/x", "/y", {}, (), object())                                            # 直接の構築は無い
    with pytest.raises(ps.ProjectionStoreError):
        ps.ExportLock("/x", b"", (1, 1), object())


def test_the_store_never_reads_or_writes_the_a3_memory_child(monkeypatch, private: Path, vault: Path) -> None:
    a3_publish(private, GEN_A)
    memory = tree(private / ps.MEMORY_CHILD)
    proxy = inject(monkeypatch)
    store = open_store(private, vault)
    locks = _locked(store)
    try:
        store.snapshot_private(locks)
        store.snapshot_vault(locks)
    finally:
        locks.release()
        monkeypatch.undo()
    inside = str(private / ps.MEMORY_CHILD) + os.sep
    assert not any(location.startswith(inside) for _, location in proxy.calls)                     # A3 の root は A3 だけ（lstat の 1 つ上だけ）
    assert tree(private / ps.MEMORY_CHILD) == memory
