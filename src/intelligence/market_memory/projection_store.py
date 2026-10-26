"""P13-A4b — Obsidian 投影の export の filesystem の store（A4b で filesystem の I/O を持つ唯一の module）。

composition root（Option C ・明示の初期化だけ）:
- `<private_root>/.p13-private-root`（目印 ・schema と class だけ）・`memory/`（A3 の memory root ・A3 だけが書く ・A4b は A3 の公開の API だけで
  初期化を頼む）・`projection/`（A4b だけが書く）。
- `projection/`: `bundles/<intent digest>/`（intent ・public な manifest ・private な binding ・走査 ・source の読みの 5 record ・1 回の rename で
  現れる）・`bindings/<binding digest>/`（公開が同じ時の追加の binding ・走査 ・source の読み）・`completions/<digest>.json` ・
  `failures/<digest>.json` ・`staging/`（作業中の bundle ・record だけ）・`locks/export.lock`（private な writer lock）。
vault（人が置いた目印 ・人が作った `generated/` の中だけに書く）:
- `<vault>/.p13-vault-root`（人が置く ・code は作らない）・`.obsidian/`（人の設定 ・3 つの file の有界の読みだけ）・`generated/`（人が作る）。
- `generated/`: `p13-memory.md`（pointer ・検証した一時 file の `os.replace` だけで替える）・`p13pvn_<24>/`（不変の版）・`.p13-staging/`（開いた
  intent の staging ・pointer の一時 file）・`.p13-interrupted/`（人の明示の保存）・`.p13-export.lock`（vault の writer lock）。
- 人の note ・vault の root の一覧 ・`workspace.json` ・plugin の data は読まない（決まった名前の lstat と 3 つの設定 file だけ）。

lock: private（`projection/locks/export.lock`）→ vault（`generated/.p13-export.lock`）の順に O_CREAT|O_EXCL で取り、vault → private の順に
所有（作成した file の identity ・byte の完全一致）を確かめて消す。在れば拒む（stale の推定 ・奪取 ・自動の除去は無い）。2 つ目が取れなければ
所有を確かめた 1 つ目だけを解放する。全ての書き込みの前に両方の lock の所有と 2 つの root の identity ・目印 ・layout を確かめ直す。

書き込み: 排他の作成 ・binary ・全て書く ・fsync ・読み戻しの照合 → 版の folder ・保存は置き換えない移動（POSIX は排他の予約の後の rename ・
予約だけが残る中断は A4a1 の VERSION_RESERVED_EMPTY）・証拠の bundle ・record は不在を確かめた後の 1 回の rename（A3 の試行の証拠と同じ ・
空の予約を証拠として残さない ・検査と rename の間の TOCTOU は残る）・pointer は一時 file の `os.replace` だけ。作業中の byte が決定論の期待の byte と完全一致する時だけ続きに使う（違えば触らずに拒む）。削除は `_unlink_if_owned` の
1 箇所だけで、所有を検証した自分の lock の解放にだけ使う。版 ・証拠 ・staging ・中断の保存は消さない ・上書きしない ・自動で修復しない。
空き容量は `shutil.disk_usage`（`_free_bytes` だけ）。検査と操作の間の TOCTOU ・Windows の保証（NTFS ・ACL ・共有違反）は P13-A5。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from .canonical import CanonicalError, is_digest, require_safe_code
from .memory_generation import record_bytes
from .memory_store import (CODE_REPOSITORY_LABEL, DIRECTORY_MODE, FILE_MODE, SYNC_FOLDER_NAMES, SYNC_FOLDER_PREFIXES, SYNC_MARKER_NAMES,
                           VAULT_MARKERS, WORKING_TREE_MARKERS, MemoryStoreError, initialize_memory_root)
from .projection_contract import (MAX_EXPORT_FILES, MAX_NOTE_BYTES, MAX_OBSERVED_OBJECTS, POINTER_NOTE_NAME, PRESERVE_AREA_RESERVATION,
                                  PRESERVE_AREA_STAGING)

PRIVATE_MARKER_NAME = ".p13-private-root"
MEMORY_CHILD = "memory"
PROJECTION_CHILD = "projection"
BINDINGS_DIRECTORY = "bindings"
BUNDLES_DIRECTORY = "bundles"
COMPLETIONS_DIRECTORY = "completions"
FAILURES_DIRECTORY = "failures"
LOCKS_DIRECTORY = "locks"
STAGING_DIRECTORY = "staging"
PROJECTION_LAYOUT = (BINDINGS_DIRECTORY, BUNDLES_DIRECTORY, COMPLETIONS_DIRECTORY, FAILURES_DIRECTORY, LOCKS_DIRECTORY, STAGING_DIRECTORY)
EXPORT_LOCK_NAME = "export.lock"
VAULT_MARKER_NAME = ".p13-vault-root"
OBSIDIAN_DIRECTORY = ".obsidian"
GENERATED_DIRECTORY = "generated"
VAULT_LOCK_NAME = ".p13-export.lock"
VAULT_STAGING_DIRECTORY = ".p13-staging"
VAULT_INTERRUPTED_DIRECTORY = ".p13-interrupted"
PLUGIN_STATE_FILES = ("app.json", "community-plugins.json", "core-plugins.json")
INTENT_RECORD = "intent.json"
PUBLIC_EXPORT_RECORD = "public_export.json"
BINDING_RECORD = "binding.json"
SCAN_RECORD = "scan.json"
SOURCE_RECORD = "source.json"
EVIDENCE_RECORD_NAMES = frozenset({INTENT_RECORD, PUBLIC_EXPORT_RECORD, BINDING_RECORD, SCAN_RECORD, SOURCE_RECORD})
RECORD_SUFFIX = ".json"
PARTIAL_SUFFIX = ".partial"
TEMP_SUFFIX = ".tmp"
INTERRUPTED_SUFFIX = ".interrupted"
MAX_INTERRUPTED_SLOTS = 999
MAX_SMALL_RECORD_BYTES = 64 * 1024
SIZE_UNIT = 4 * 1024
PRIVATE_ROOT_SCHEMA_VERSION = "p13_private_root:0.1.0"
PRIVATE_ROOT_CLASS = "P13_PRIVATE_COMPOSITION_ROOT_NON_AUTHORITY"
VAULT_ROOT_SCHEMA_VERSION = "p13_vault_root:0.1.0"
VAULT_ROOT_CLASS = "P13_OBSIDIAN_VAULT_HUMAN_PLACED_MARKER"
LOCK_SCHEMA_VERSION = "p13_projection_lock:0.1.0"
LOCK_SCOPE_PRIVATE = "PRIVATE_PROJECTION"
LOCK_SCOPE_VAULT = "VAULT_EXPORT"
LOCK_OPERATIONS = ("PUBLISH", "PRESERVE")
PROJECTION_ROOT_LABEL = "PROJECTION_ROOT"
VAULT_ROOT_LABEL = "VAULT_ROOT"
#: 拒む Obsidian の設定（暫定 ・既知のものだけ ・**網羅ではない** ・plugin の id は P13-A5 で実物の manifest と照らす）。同期 ・公開 ・note を
#: 書き換える ・外へ送る ・AI の plugin と、link の自動の書き換え
REFUSED_CORE_PLUGINS = frozenset({"publish", "sync"})
REFUSED_COMMUNITY_PLUGINS = frozenset({"copilot", "obsidian-git", "obsidian-linter", "obsidian-livesync", "obsidian-local-rest-api",
                                       "obsidian-textgenerator-plugin", "remotely-save", "smart-connections", "templater-obsidian",
                                       "update-time-on-edit"})
REFUSED_APP_SETTINGS = (("alwaysUpdateLinks", True),)

#: 結果の code（固定の定数だけ ・path ・OS の文 ・値は出さない）
ROOT_INVALID = "ROOT_INVALID"
PROTECTED_ROOT_INVALID = "PROTECTED_ROOT_INVALID"
ROOT_UNSAFE_COMPONENT = "ROOT_UNSAFE_COMPONENT"
ROOT_OVERLAP = "ROOT_OVERLAP"
ROOT_SYNC_FOLDER = "ROOT_SYNC_FOLDER"
ROOT_INSIDE_WORKING_TREE = "ROOT_INSIDE_WORKING_TREE"
ROOT_INSIDE_VAULT = "ROOT_INSIDE_VAULT"
ROOT_PARENT_MISSING = "ROOT_PARENT_MISSING"
ROOT_NOT_EMPTY = "ROOT_NOT_EMPTY"
ROOT_ALREADY_INITIALIZED = "ROOT_ALREADY_INITIALIZED"
PRIVATE_ROOT_MISSING = "PRIVATE_ROOT_MISSING"
MARKER_INVALID = "MARKER_INVALID"
ROOT_IDENTITY_MISMATCH = "ROOT_IDENTITY_MISMATCH"
LAYOUT_INVALID = "LAYOUT_INVALID"
UNSAFE_ENTRY = "UNSAFE_ENTRY"
UNKNOWN_ENTRY = "UNKNOWN_ENTRY"
ENTRY_LIMIT_EXCEEDED = "ENTRY_LIMIT_EXCEEDED"
RECORD_TOO_LARGE = "RECORD_TOO_LARGE"
STORE_IO_FAILED = "STORE_IO_FAILED"
STORE_INPUT_INVALID = "STORE_INPUT_INVALID"
MEMORY_INITIALIZATION_FAILED = "MEMORY_INITIALIZATION_FAILED"
VAULT_INVALID = "VAULT_INVALID"
VAULT_MARKER_MISSING = "VAULT_MARKER_MISSING"
VAULT_MARKER_INVALID = "VAULT_MARKER_INVALID"
VAULT_WORKING_TREE = "VAULT_WORKING_TREE"
VAULT_SYNC_FOLDER = "VAULT_SYNC_FOLDER"
VAULT_GENERATED_MISSING = "VAULT_GENERATED_MISSING"
PLUGIN_STATE_UNVERIFIED = "PLUGIN_STATE_UNVERIFIED"
PLUGIN_REFUSED = "PLUGIN_REFUSED"
PRIVATE_LOCK_PRESENT = "PRIVATE_LOCK_PRESENT"
VAULT_LOCK_PRESENT = "VAULT_LOCK_PRESENT"
LOCK_OWNERSHIP_UNVERIFIED = "LOCK_OWNERSHIP_UNVERIFIED"
LOCK_RELEASED = "LOCK_RELEASED"
LOCK_RELEASE_FAILED = "LOCK_RELEASE_FAILED"
LOCK_NOT_ACQUIRED = "LOCK_NOT_ACQUIRED"
EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
EVIDENCE_ALREADY_RECORDED = "EVIDENCE_ALREADY_RECORDED"
EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
STAGING_CONFLICT = "STAGING_CONFLICT"
STAGING_VERIFICATION_FAILED = "STAGING_VERIFICATION_FAILED"
VERSION_CONFLICT = "VERSION_CONFLICT"
POINTER_CHANGED = "POINTER_CHANGED"
POINTER_VERIFICATION_FAILED = "POINTER_VERIFICATION_FAILED"
RESERVATION_NOT_EMPTY = "RESERVATION_NOT_EMPTY"
INTERRUPTED_SLOTS_EXHAUSTED = "INTERRUPTED_SLOTS_EXHAUSTED"
PRESERVATION_UNVERIFIED = "PRESERVATION_UNVERIFIED"
CAPACITY_UNVERIFIED = "CAPACITY_UNVERIFIED"
#: 開く ・初期化の拒否（呼び出し側の root ・vault ・環境の誤り。公開の状態ではない）
REFUSAL_CODES = frozenset({ROOT_INVALID, PROTECTED_ROOT_INVALID, ROOT_UNSAFE_COMPONENT, ROOT_OVERLAP, ROOT_SYNC_FOLDER,
                           ROOT_INSIDE_WORKING_TREE, ROOT_INSIDE_VAULT, ROOT_PARENT_MISSING, ROOT_NOT_EMPTY, ROOT_ALREADY_INITIALIZED,
                           VAULT_INVALID, VAULT_MARKER_MISSING, VAULT_MARKER_INVALID, VAULT_WORKING_TREE, VAULT_SYNC_FOLDER,
                           VAULT_GENERATED_MISSING, PLUGIN_STATE_UNVERIFIED, PLUGIN_REFUSED})

_BINARY = getattr(os, "O_BINARY", 0)                                                  # Windows: text mode は LF を CRLF に変える
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)                                              # POSIX: 最後の成分の symlink を辿らない
_REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
_SENTINEL = object()
_DIGEST_RE = "[0-9a-f]{64}"
_VERSION_LABEL_RE = re.compile(r"^p13pvn_[0-9a-f]{24}$")
_NOTE_NAME_RE = re.compile(r"^p13pvn_[0-9a-f]{24}(?:-[si][0-9]{3})?\.md$")
_POINTER_STEM = POINTER_NOTE_NAME[:-len(".md")]
_POINTER_TEMP_RE = re.compile(r"^" + re.escape(_POINTER_STEM) + r"\.(" + _DIGEST_RE + r")\.tmp$")
_INTERRUPTED_RE = re.compile(r"^p13pvn_[0-9a-f]{24}\.[0-9]{3}\.interrupted$")
_RECORD_FILE_RE = re.compile(r"^(" + _DIGEST_RE + r")\.json$")
_EVIDENCE_STAGING_RE = re.compile(r"^(bundle|binding)\.(" + _DIGEST_RE + r")\.partial$|^(completion|failure)\.(" + _DIGEST_RE + r")\.tmp$")
_BUNDLE_AREAS = {BUNDLES_DIRECTORY: "bundle", BINDINGS_DIRECTORY: "binding"}
_RECORD_AREAS = {COMPLETIONS_DIRECTORY: "completion", FAILURES_DIRECTORY: "failure"}
_REMOVED, _UNVERIFIED, _UNLINK_FAILED = "REMOVED", "OWNERSHIP_UNVERIFIED", "UNLINK_FAILED"


class ProjectionStoreError(ValueError):
    """store の失敗（固定の code ・短い detail だけ。path ・OS の文 ・値は持たない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def private_root_marker_bytes() -> bytes:
    """composition root の目印の byte（schema の version と root の class だけ ・path ・時刻 ・host は無い）。"""
    return record_bytes({"schema_version": PRIVATE_ROOT_SCHEMA_VERSION, "root_class": PRIVATE_ROOT_CLASS})


def vault_root_marker_bytes() -> bytes:
    """人が vault の root に置く目印の byte（code は書かない ・照合するだけ）。"""
    return record_bytes({"schema_version": VAULT_ROOT_SCHEMA_VERSION, "root_class": VAULT_ROOT_CLASS})


def lock_record(scope: str, operation: str) -> bytes:
    """writer lock の byte（範囲 ・操作だけ。pid ・時刻 ・host ・user ・path は無い ＝ 所有は作成した file の identity で確かめる）。"""
    if scope not in (LOCK_SCOPE_PRIVATE, LOCK_SCOPE_VAULT) or operation not in LOCK_OPERATIONS:
        raise ProjectionStoreError(STORE_INPUT_INVALID, "LOCK")
    return record_bytes({"schema_version": LOCK_SCHEMA_VERSION, "scope": scope, "operation": operation})


def storage_units(size: int) -> int:
    """容量の勘定の単位（file ・directory は少なくとも 1 単位 ・切り上げ）。"""
    return max(1, -(-size // SIZE_UNIT)) * SIZE_UNIT


# ---------------------------------------------------------------- 形 ・祖先 ・重なり ・目印（A3 と同じ規則の複製 ・A3 の private な helper は使わない）


def _is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _plain_directory(st: os.stat_result) -> bool:
    return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode) and not _is_reparse(st)


def _plain_file(st: os.stat_result) -> bool:
    return stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode) and not _is_reparse(st)


def _lstat_or_none(location: str) -> Optional[os.stat_result]:
    try:
        return os.lstat(location)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        raise ProjectionStoreError(STORE_IO_FAILED, "LSTAT") from None


def _location_text(value: Any, code: str) -> str:
    if isinstance(value, str):
        text = value
    elif hasattr(value, "__fspath__"):
        text = os.fspath(value)
        if not isinstance(text, str):
            raise ProjectionStoreError(code, "NOT_TEXT")
    else:
        raise ProjectionStoreError(code, "TYPE")
    if text == "" or "\x00" in text or text != text.strip():
        raise ProjectionStoreError(code, "SHAPE")
    if not os.path.isabs(text) or (os.name == "nt" and not os.path.splitdrive(text)[0]):
        raise ProjectionStoreError(code, "NOT_ABSOLUTE")
    return text


def _components(text: str) -> Tuple[str, ...]:
    rest = os.path.splitdrive(text)[1]
    if os.altsep:
        rest = rest.replace(os.altsep, os.sep)
    return tuple(part for part in rest.split(os.sep) if part)


def _prefixes(text: str) -> Tuple[str, ...]:
    """anchor から text までの全ての祖先（anchor ・各成分 ・text 自身）。"""
    walked = os.path.splitdrive(text)[0] + os.sep
    found = [walked]
    for part in _components(text):
        walked = os.path.join(walked, part)
        found.append(walked)
    return tuple(found)


def _root_text(value: Any) -> str:
    text = _location_text(value, ROOT_INVALID)
    parts = _components(text)
    if os.path.normpath(text) != text or (os.name != "nt" and text.startswith("//")):
        raise ProjectionStoreError(ROOT_INVALID, "NOT_NORMALIZED")
    if not parts or any(part in (".", "..") for part in parts):
        raise ProjectionStoreError(ROOT_INVALID, "TRAVERSAL_OR_ANCHOR")
    if os.name == "nt" and any(":" in part or part != part.rstrip(" .") for part in parts):
        raise ProjectionStoreError(ROOT_INVALID, "WINDOWS_ALIAS")                     # ADS ・末尾の点 ／ 空白の別名
    return text


def _check_ancestors(text: str, *, absent_code: str, root_may_be_absent: bool = False) -> Optional[os.stat_result]:
    """anchor から root までの全ての成分が実在の directory（symlink ・junction ・reparse point ・file ではない）。"""
    prefixes = _prefixes(text)
    st = None
    for index, prefix in enumerate(prefixes):
        st = _lstat_or_none(prefix)
        if st is None:
            if index == len(prefixes) - 1 and root_may_be_absent:
                return None
            raise ProjectionStoreError(absent_code, "ANCESTOR" if index < len(prefixes) - 1 else "ROOT")
        if not _plain_directory(st):
            raise ProjectionStoreError(ROOT_UNSAFE_COMPONENT, "ROOT" if index == len(prefixes) - 1 else "ANCESTOR")
    return st


def _sync_name(part: str) -> bool:
    folded = part.casefold()
    return folded in SYNC_FOLDER_NAMES or folded.startswith(SYNC_FOLDER_PREFIXES)


def _check_private_markers(text: str) -> None:
    """composition root: 既知の同期 folder の名前 ・祖先の目印（同期 ・git の作業木 ・Obsidian の vault）。検出は網羅ではない。"""
    if any(_sync_name(part) for part in _components(text)):
        raise ProjectionStoreError(ROOT_SYNC_FOLDER, "NAME")
    for prefix in _prefixes(text)[:-1]:
        for names, code in ((WORKING_TREE_MARKERS, ROOT_INSIDE_WORKING_TREE), (VAULT_MARKERS, ROOT_INSIDE_VAULT),
                            (SYNC_MARKER_NAMES, ROOT_SYNC_FOLDER)):
            for name in names:
                if _lstat_or_none(os.path.join(prefix, name)) is not None:
                    raise ProjectionStoreError(code, "MARKER")


def _check_vault_markers(text: str) -> None:
    """vault: 同期 folder の名前 ・祖先の git ／ vault ／ 同期の目印 ・vault の root 自身の git ／ 同期の目印（決まった名前の lstat だけ）。"""
    if any(_sync_name(part) for part in _components(text)):
        raise ProjectionStoreError(VAULT_SYNC_FOLDER, "NAME")
    for prefix in _prefixes(text)[:-1]:
        for names, code in ((WORKING_TREE_MARKERS, VAULT_WORKING_TREE), (VAULT_MARKERS, ROOT_INSIDE_VAULT),
                            (SYNC_MARKER_NAMES, VAULT_SYNC_FOLDER)):
            for name in names:
                if _lstat_or_none(os.path.join(prefix, name)) is not None:
                    raise ProjectionStoreError(code, "ANCESTOR_MARKER")
    for names, code in ((WORKING_TREE_MARKERS, VAULT_WORKING_TREE), (SYNC_MARKER_NAMES, VAULT_SYNC_FOLDER)):
        for name in names:
            if _lstat_or_none(os.path.join(text, name)) is not None:
                raise ProjectionStoreError(code, "VAULT_MARKER")


def _code_repository() -> str:
    """この code の repository（package の 4 つ上）。呼び出し側が渡さなくても常に保護する。"""
    location = os.path.abspath(__file__)
    for _ in range(4):
        location = os.path.dirname(location)
    return location


def _forms(text: str) -> Tuple[str, ...]:
    return tuple(sorted({os.path.normcase(os.path.normpath(text)), os.path.normcase(os.path.realpath(text))}))


def _within(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False                                                                  # Windows: 別の drive


def _identities(text: str) -> Tuple[frozenset, frozenset]:
    """(祖先と自身の identity の集合, 自身の identity の集合)。symlink は辿った先も含める（`st_ino` が 0 なら比べない）。"""
    chain, own = set(), set()
    prefixes = _prefixes(os.path.normpath(text))
    for index, prefix in enumerate(prefixes):
        for probe in (os.lstat, os.stat):
            try:
                st = probe(prefix)
            except OSError:
                continue
            if st.st_ino:
                chain.add((st.st_dev, st.st_ino))
                if index == len(prefixes) - 1:
                    own.add((st.st_dev, st.st_ino))
    return frozenset(chain), frozenset(own)


def _overlaps(root: str, other: str) -> bool:
    """文字の形（正規化 ・大小の畳み ・realpath）か file の identity（祖先 ↔ 自身）で重なれば True。最善の努力（TOCTOU ・別名は A5）。"""
    for left in _forms(root):
        for right in _forms(other):
            if left == right or _within(left, right) or _within(right, left):
                return True
    root_chain, root_own = _identities(root)
    other_chain, other_own = _identities(other)
    return bool(other_own & root_chain or root_own & other_chain)


def _protected(protected_roots: Any) -> Tuple[Tuple[str, str], ...]:
    if not isinstance(protected_roots, Mapping):
        raise ProjectionStoreError(PROTECTED_ROOT_INVALID, "NOT_A_MAPPING")
    pairs = {(CODE_REPOSITORY_LABEL, _code_repository())}
    for label, location in protected_roots.items():
        try:
            require_safe_code(label, PROTECTED_ROOT_INVALID)
        except CanonicalError:
            raise ProjectionStoreError(PROTECTED_ROOT_INVALID, "LABEL") from None
        if label in (PROJECTION_ROOT_LABEL, VAULT_ROOT_LABEL, CODE_REPOSITORY_LABEL):
            raise ProjectionStoreError(PROTECTED_ROOT_INVALID, "RESERVED_LABEL")
        pairs.add((label, _location_text(location, PROTECTED_ROOT_INVALID)))
    return tuple(sorted(pairs))


def _check_disjoint(root: str, protected: Tuple[Tuple[str, str], ...]) -> None:
    for label, location in protected:
        if _overlaps(root, location):
            raise ProjectionStoreError(ROOT_OVERLAP, label)


# ---------------------------------------------------------------- file の I/O（binary ・排他 ・fsync ・有界の読み ・読み戻し）


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(data):
        count = os.write(fd, view[written:])
        if count <= 0:
            raise OSError("SHORT_WRITE")
        written += count


def _create_file(location: str, data: bytes) -> Tuple[int, int]:
    """排他の作成（在れば FileExistsError）・binary ・全て書く ・fsync。作った file の identity を返す（所有の検証に使う）。"""
    fd = os.open(location, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _BINARY | _NOFOLLOW, FILE_MODE)
    try:
        _write_all(fd, data)
        os.fsync(fd)
        st = os.fstat(fd)
    finally:
        os.close(fd)
    return (st.st_dev, st.st_ino)


def _read_file(location: str, limit: int) -> bytes:
    """正規の file だけを読む（symlink ・reparse point ・hard link ・特殊 file ・上限を超える長さは拒む。開いた fd の identity も照合）。"""
    st = os.lstat(location)
    if not _plain_file(st) or st.st_nlink != 1:
        raise ProjectionStoreError(UNSAFE_ENTRY, "FILE_KIND")
    if st.st_size > limit:
        raise ProjectionStoreError(RECORD_TOO_LARGE)
    fd = os.open(location, os.O_RDONLY | _BINARY | _NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino) or not stat.S_ISREG(opened.st_mode):
            raise ProjectionStoreError(UNSAFE_ENTRY, "CHANGED_WHILE_OPENING")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, MAX_SMALL_RECORD_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ProjectionStoreError(RECORD_TOO_LARGE)
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b"".join(chunks)


def _read_bytes(location: str, limit: int) -> bytes:
    try:
        return _read_file(location, limit)
    except OSError:
        raise ProjectionStoreError(STORE_IO_FAILED, "READ") from None


def _read_optional(location: str, limit: int) -> Optional[bytes]:
    try:
        return _read_file(location, limit)
    except FileNotFoundError:
        return None
    except OSError:
        raise ProjectionStoreError(STORE_IO_FAILED, "READ") from None


def _entries(location: str, limit: int = MAX_OBSERVED_OBJECTS) -> Tuple[str, ...]:
    """1 つの directory の名前の一覧だけ（再帰しない ・上限を超えれば拒む）。"""
    st = _lstat_or_none(location)
    if st is None:
        raise ProjectionStoreError(LAYOUT_INVALID, "DIRECTORY_ABSENT")
    if not _plain_directory(st):
        raise ProjectionStoreError(UNSAFE_ENTRY, "DIRECTORY_KIND")
    try:
        names = os.listdir(location)
    except OSError:
        raise ProjectionStoreError(STORE_IO_FAILED, "LIST") from None
    if len(names) > limit:
        raise ProjectionStoreError(ENTRY_LIMIT_EXCEEDED)
    return tuple(sorted(names))


def _fsync_directory(location: str) -> None:
    try:
        fd = os.open(location, os.O_RDONLY)
    except OSError:
        return                                                                         # Windows: directory の fd は開けない（A5）
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _make_directory(location: str) -> None:
    """排他の directory の作成（在れば FileExistsError）と親の fsync。"""
    os.mkdir(location, DIRECTORY_MODE)
    _fsync_directory(os.path.dirname(location))


def _owned(location: str, identity: Tuple[int, int], data: bytes) -> bool:
    """所有の検証: 作成した時と同じ file の identity（0 は検証できない）・正規の file ・byte の完全一致。"""
    try:
        st = os.lstat(location)
    except OSError:
        return False
    if not _plain_file(st) or not identity[1] or (st.st_dev, st.st_ino) != identity or st.st_size != len(data):
        return False
    try:
        return _read_file(location, len(data)) == data
    except (OSError, ProjectionStoreError):
        return False


def _unlink_if_owned(location: str, identity: Tuple[int, int], data: bytes) -> str:
    """A4b の唯一の削除。自分が排他で作り、まだ所有している writer lock だけ。曖昧なら消さずに残す。検証と unlink の間の TOCTOU は
    stdlib では閉じない（記録に明記）。"""
    if not _owned(location, identity, data):
        return _UNVERIFIED
    try:
        os.unlink(location)
    except OSError:
        return _UNLINK_FAILED
    _fsync_directory(os.path.dirname(location))
    return _REMOVED


def _move_without_replacing(source: str, target: str, *, directory: bool) -> None:
    """source を target へ移す。target に既存の entry が在れば失敗する（置き換えない）。Windows の `os.rename` は既存の target を
    置き換えない。POSIX の rename は既存の file ・空の directory を黙って置き換えるので、先に target を排他で予約し（空の file は O_EXCL ・
    directory は mkdir）、所有を確かめた自分の空の予約だけを置き換える。予約と rename の間の TOCTOU は stdlib では閉じない。"""
    if os.name != "nt":
        if directory:
            os.mkdir(target, DIRECTORY_MODE)                                               # 既存なら FileExistsError（空でない予約は rename が拒む）
        else:
            identity = _create_file(target, b"")
            if not _owned(target, identity, b""):
                raise OSError("RESERVATION_NOT_OWNED")                                     # 予約が替わった: 置き換えない（予約は残す）
    os.rename(source, target)


def _free_bytes(location: str) -> int:
    """空き容量（`shutil.disk_usage` の唯一の呼び出し）。取れない ・形が違えば容量は検証できない。"""
    try:
        usage = shutil.disk_usage(location)
    except OSError:
        raise ProjectionStoreError(CAPACITY_UNVERIFIED, "DISK_USAGE") from None
    free = usage.free
    if type(free) is not int or free < 0:
        raise ProjectionStoreError(CAPACITY_UNVERIFIED, "DISK_USAGE_SHAPE")
    return free


class _Usage:
    """観測した byte の勘定（file ・directory ごとに単位へ切り上げ）。"""

    def __init__(self) -> None:
        self.total = 0

    def add(self, st: os.stat_result) -> None:
        self.total += SIZE_UNIT if _plain_directory(st) else storage_units(st.st_size)


# ---------------------------------------------------------------- 観測の写像（byte だけ ・意味の検証は build ・A4a1）


@dataclass(frozen=True, kw_only=True)
class PrivateSnapshot:
    """`projection/` の byte（bundle ・追加の binding ・完了 ・失敗 ・作業中の残り）と勘定した byte。repr に値は出さない。"""

    bundles: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict, repr=False)
    bindings: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict, repr=False)
    completions: Mapping[str, bytes] = field(default_factory=dict, repr=False)
    failures: Mapping[str, bytes] = field(default_factory=dict, repr=False)
    residue: Mapping[Tuple[str, str], Any] = field(default_factory=dict, repr=False)
    used_bytes: int = 0


@dataclass(frozen=True, kw_only=True)
class VaultSnapshot:
    """`generated/` の byte（pointer ・版 ・staging ・pointer の一時 file ・中断の保存の名前）と勘定した byte。"""

    pointer: Optional[bytes] = field(default=None, repr=False)
    versions: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict, repr=False)
    staging: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict, repr=False)
    pointer_temps: Mapping[str, bytes] = field(default_factory=dict, repr=False)
    interrupted: Tuple[str, ...] = ()
    used_bytes: int = 0


@dataclass(frozen=True, kw_only=True)
class FreeSpace:
    vault_free: int
    private_free: int
    same_volume: bool


# ---------------------------------------------------------------- lock


class ExportLock:
    """取得した 1 つの writer lock。解放は作った所有者だけ: 作成時の file の identity と byte が一致する時だけ消す（曖昧なら残す）。"""

    def __init__(self, location: str, data: bytes, identity: Tuple[int, int], sentinel: object) -> None:
        if sentinel is not _SENTINEL:
            raise ProjectionStoreError(LOCK_OWNERSHIP_UNVERIFIED, "DIRECT_CONSTRUCTION")
        self._location, self._data, self._identity = location, data, identity
        self._release_code: Optional[str] = None

    def __repr__(self) -> str:
        return f"ExportLock(release_code={self._release_code!r})"

    def owned(self) -> bool:
        return self._release_code is None and _owned(self._location, self._identity, self._data)

    def release(self) -> str:
        """1 回だけ。所有を検証できれば消して LOCK_RELEASED、できなければ残して LOCK_OWNERSHIP_UNVERIFIED、消せなければ LOCK_RELEASE_FAILED。"""
        if self._release_code is None:
            outcome = _unlink_if_owned(self._location, self._identity, self._data)
            self._release_code = {_REMOVED: LOCK_RELEASED, _UNVERIFIED: LOCK_OWNERSHIP_UNVERIFIED}.get(outcome, LOCK_RELEASE_FAILED)
        return self._release_code


class ExportLocks:
    """private と vault の 2 つの writer lock（独立に所有を検証する ・解放は vault → private）。"""

    def __init__(self, store: "ProjectionStore", private: ExportLock, vault: ExportLock, sentinel: object) -> None:
        if sentinel is not _SENTINEL:
            raise ProjectionStoreError(LOCK_OWNERSHIP_UNVERIFIED, "DIRECT_CONSTRUCTION")
        self._store, self._private, self._vault = store, private, vault

    def __repr__(self) -> str:
        return f"ExportLocks(private={self._private!r}, vault={self._vault!r})"

    def owned(self) -> bool:
        return self._private.owned() and self._vault.owned()

    def release(self) -> Tuple[str, str]:
        """(vault の解放の code, private の解放の code)。vault を先に ・どちらも所有を検証できなければ残す。"""
        try:
            vault = self._vault.release()
        finally:
            private = self._private.release()
        return vault, private


# ---------------------------------------------------------------- store


class ProjectionStore:
    """開いた composition root と vault。`open_projection_store` だけが作る。repr に root は出さない。"""

    def __init__(self, private_root: str, vault_root: str, identities: Mapping[str, Tuple[int, int]],
                 protected: Tuple[Tuple[str, str], ...], sentinel: object) -> None:
        if sentinel is not _SENTINEL:
            raise ProjectionStoreError(ROOT_INVALID, "DIRECT_CONSTRUCTION")
        self._private_root, self._vault_root, self._identities, self._protected = private_root, vault_root, dict(identities), protected

    def __repr__(self) -> str:
        return f"ProjectionStore(protected_labels={self.protected_labels!r})"

    @property
    def protected_labels(self) -> Tuple[str, ...]:
        """重なりを検査した保護の root の label（渡されていない root は含まない ＝ 主張しない）。"""
        return tuple(sorted({label for label, _ in self._protected}))

    @property
    def memory_location(self) -> str:
        """A3 の memory root の位置（A3 の公開の API に渡すだけ ・A4b はここを読まない ・書かない）。"""
        return os.path.join(self._private_root, MEMORY_CHILD)

    @property
    def projection_location(self) -> str:
        return os.path.join(self._private_root, PROJECTION_CHILD)

    @property
    def vault_location(self) -> str:
        return self._vault_root

    def _projection(self, *parts: str) -> str:
        return os.path.join(self._private_root, PROJECTION_CHILD, *parts)

    def _generated(self, *parts: str) -> str:
        return os.path.join(self._vault_root, GENERATED_DIRECTORY, *parts)

    # ------------------------------------------------ root の再検査

    def _verify_identity(self, key: str, location: str, absent_code: str) -> None:
        st = _lstat_or_none(location)
        if st is None:
            raise ProjectionStoreError(absent_code, key)
        if not _plain_directory(st):
            raise ProjectionStoreError(ROOT_UNSAFE_COMPONENT, key)
        if (st.st_dev, st.st_ino) != self._identities[key]:
            raise ProjectionStoreError(ROOT_IDENTITY_MISMATCH, key)

    def _verify_private(self) -> None:
        """composition root: 祖先 ・identity ・目印の完全一致 ・最上位は目印 ・memory ・projection だけ ・projection の layout の完全一致。"""
        _check_ancestors(self._private_root, absent_code=PRIVATE_ROOT_MISSING)
        self._verify_identity("PRIVATE", self._private_root, PRIVATE_ROOT_MISSING)
        if _read_optional(os.path.join(self._private_root, PRIVATE_MARKER_NAME), MAX_SMALL_RECORD_BYTES) != private_root_marker_bytes():
            raise ProjectionStoreError(MARKER_INVALID, "PRIVATE")
        top = set(_entries(self._private_root))
        if top - {PRIVATE_MARKER_NAME, MEMORY_CHILD, PROJECTION_CHILD}:
            raise ProjectionStoreError(UNKNOWN_ENTRY, "PRIVATE_ROOT")
        if {MEMORY_CHILD, PROJECTION_CHILD} - top:
            raise ProjectionStoreError(LAYOUT_INVALID, "PRIVATE_CHILD")
        memory = _lstat_or_none(os.path.join(self._private_root, MEMORY_CHILD))
        if memory is None or not _plain_directory(memory):
            raise ProjectionStoreError(UNSAFE_ENTRY, "MEMORY_CHILD")
        self._verify_identity("PROJECTION", self._projection(), LAYOUT_INVALID)
        inside = set(_entries(self._projection()))
        if inside != set(PROJECTION_LAYOUT):
            raise ProjectionStoreError(UNKNOWN_ENTRY if inside - set(PROJECTION_LAYOUT) else LAYOUT_INVALID, "PROJECTION")
        for name in PROJECTION_LAYOUT:
            st = _lstat_or_none(self._projection(name))
            if st is None or not _plain_directory(st):
                raise ProjectionStoreError(UNSAFE_ENTRY, "PROJECTION_LAYOUT")

    def _verify_vault(self) -> None:
        """vault: 祖先 ・identity ・人が置いた目印の完全一致 ・`.obsidian` ・`generated` の identity（人の note は一覧しない）。"""
        _check_ancestors(self._vault_root, absent_code=VAULT_INVALID)
        self._verify_identity("VAULT", self._vault_root, VAULT_INVALID)
        marker = _read_optional(os.path.join(self._vault_root, VAULT_MARKER_NAME), MAX_SMALL_RECORD_BYTES)
        if marker is None:
            raise ProjectionStoreError(VAULT_MARKER_MISSING)
        if marker != vault_root_marker_bytes():
            raise ProjectionStoreError(VAULT_MARKER_INVALID)
        obsidian = _lstat_or_none(os.path.join(self._vault_root, OBSIDIAN_DIRECTORY))
        if obsidian is None or not _plain_directory(obsidian):
            raise ProjectionStoreError(VAULT_INVALID, "OBSIDIAN_DIRECTORY")
        self._verify_identity("GENERATED", self._generated(), VAULT_GENERATED_MISSING)

    def _check_plugins(self) -> None:
        """`.obsidian` の 3 つの設定 file の有界の読み（無い ・壊れた ・symlink ・大き過ぎるものは検証できない）。拒む設定は既知のものだけ。"""
        for name in PLUGIN_STATE_FILES:
            location = os.path.join(self._vault_root, OBSIDIAN_DIRECTORY, name)
            try:
                data = _read_optional(location, MAX_SMALL_RECORD_BYTES)
            except ProjectionStoreError:
                raise ProjectionStoreError(PLUGIN_STATE_UNVERIFIED, "READ") from None
            if data is None:
                raise ProjectionStoreError(PLUGIN_STATE_UNVERIFIED, "ABSENT")
            try:
                value = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                raise ProjectionStoreError(PLUGIN_STATE_UNVERIFIED, "JSON") from None
            if name == "core-plugins.json":
                if isinstance(value, list) and all(isinstance(v, str) for v in value):
                    enabled = set(value)
                elif isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, bool) for k, v in value.items()):
                    enabled = {k for k, v in value.items() if v}
                else:
                    raise ProjectionStoreError(PLUGIN_STATE_UNVERIFIED, "CORE_SHAPE")
                if enabled & REFUSED_CORE_PLUGINS:
                    raise ProjectionStoreError(PLUGIN_REFUSED, "CORE")
            elif name == "community-plugins.json":
                if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                    raise ProjectionStoreError(PLUGIN_STATE_UNVERIFIED, "COMMUNITY_SHAPE")
                if set(value) & REFUSED_COMMUNITY_PLUGINS:
                    raise ProjectionStoreError(PLUGIN_REFUSED, "COMMUNITY")
            else:
                if not isinstance(value, dict):
                    raise ProjectionStoreError(PLUGIN_STATE_UNVERIFIED, "APP_SHAPE")
                if any(value.get(key) is refused for key, refused in REFUSED_APP_SETTINGS):
                    raise ProjectionStoreError(PLUGIN_REFUSED, "APP")

    # ------------------------------------------------ lock

    def _create_lock(self, location: str, data: bytes, present_code: str) -> ExportLock:
        try:
            identity = _create_file(location, data)
        except FileExistsError:
            raise ProjectionStoreError(present_code) from None
        except OSError:
            raise ProjectionStoreError(STORE_IO_FAILED, "LOCK_CREATE") from None             # 書きかけの lock は残す（人の手順）
        _fsync_directory(os.path.dirname(location))
        return ExportLock(location, data, identity, _SENTINEL)

    def acquire_locks(self, *, operation: str) -> ExportLocks:
        """private → vault の順に O_CREAT|O_EXCL。どちらかが既に在れば拒む（奪取は無い）。vault が取れなければ private だけを解放する。"""
        if operation not in LOCK_OPERATIONS:
            raise ProjectionStoreError(STORE_INPUT_INVALID, "LOCK_OPERATION")
        self._verify_private()
        self._verify_vault()
        private = self._create_lock(self._projection(LOCKS_DIRECTORY, EXPORT_LOCK_NAME), lock_record(LOCK_SCOPE_PRIVATE, operation),
                                    PRIVATE_LOCK_PRESENT)
        try:
            self._verify_vault()
            vault = self._create_lock(self._generated(VAULT_LOCK_NAME), lock_record(LOCK_SCOPE_VAULT, operation), VAULT_LOCK_PRESENT)
        except ProjectionStoreError as exc:
            released = private.release()                                                  # 所有を検証できた 1 つ目だけ
            raise ProjectionStoreError(exc.code, released) from None
        return ExportLocks(self, private, vault, _SENTINEL)

    def _require_locks(self, locks: Any) -> None:
        if not isinstance(locks, ExportLocks) or locks._store is not self or not locks.owned():
            raise ProjectionStoreError(LOCK_OWNERSHIP_UNVERIFIED)

    def check_locks(self, locks: ExportLocks) -> None:
        """両方の lock の所有 ・composition root と vault の identity ・目印 ・layout（全ての書き込みの前に呼ぶ）。"""
        self._require_locks(locks)
        self._verify_private()
        self._verify_vault()

    def _check_private_locks(self, locks: ExportLocks) -> None:
        """private な証拠だけを書く前: 両方の lock の所有と composition root（vault には書かない）。"""
        self._require_locks(locks)
        self._verify_private()

    # ------------------------------------------------ 観測（有界 ・正規の file だけ ・人の note は読まない）

    def _read_notes(self, location: str, usage: _Usage) -> Dict[str, bytes]:
        notes = {}
        for name in _entries(location, MAX_EXPORT_FILES):
            st = _lstat_or_none(os.path.join(location, name))
            if st is None:
                raise ProjectionStoreError(LAYOUT_INVALID, "ENTRY_VANISHED")
            if not _NOTE_NAME_RE.match(name):
                raise ProjectionStoreError(UNKNOWN_ENTRY, "NOTE_NAME")
            if not _plain_file(st):
                raise ProjectionStoreError(UNSAFE_ENTRY, "NOTE")
            notes[name] = _read_bytes(os.path.join(location, name), MAX_NOTE_BYTES)
            usage.add(st)
        return notes

    def _read_records(self, location: str, usage: _Usage) -> Dict[str, bytes]:
        records = {}
        for name in _entries(location, len(EVIDENCE_RECORD_NAMES)):
            st = _lstat_or_none(os.path.join(location, name))
            if name not in EVIDENCE_RECORD_NAMES:
                raise ProjectionStoreError(UNKNOWN_ENTRY, "RECORD_NAME")
            if st is None or not _plain_file(st):
                raise ProjectionStoreError(UNSAFE_ENTRY, "RECORD")
            records[name] = _read_bytes(os.path.join(location, name), MAX_NOTE_BYTES)
            usage.add(st)
        return records

    def snapshot_private(self, locks: ExportLocks) -> PrivateSnapshot:
        """`projection/` の全ての証拠の byte（名前 ・種類 ・大きさは厳密 ・未知の entry は拒む）。"""
        self._check_private_locks(locks)
        usage = _Usage()
        groups: Dict[str, Dict[str, Any]] = {name: {} for name in PROJECTION_LAYOUT}
        residue: Dict[Tuple[str, str], Any] = {}
        for area in PROJECTION_LAYOUT:
            location = self._projection(area)
            usage.total += SIZE_UNIT
            for name in _entries(location):
                entry = os.path.join(location, name)
                st = _lstat_or_none(entry)
                if st is None:
                    raise ProjectionStoreError(LAYOUT_INVALID, "ENTRY_VANISHED")
                usage.total += SIZE_UNIT if _plain_directory(st) else 0
                if area in _BUNDLE_AREAS:
                    if not is_digest(name):
                        raise ProjectionStoreError(UNKNOWN_ENTRY, area.upper())
                    if not _plain_directory(st):
                        raise ProjectionStoreError(UNSAFE_ENTRY, area.upper())
                    groups[area][name] = self._read_records(entry, usage)
                elif area in _RECORD_AREAS:
                    match = _RECORD_FILE_RE.match(name)
                    if match is None:
                        raise ProjectionStoreError(UNKNOWN_ENTRY, area.upper())
                    if not _plain_file(st):
                        raise ProjectionStoreError(UNSAFE_ENTRY, area.upper())
                    groups[area][match.group(1)] = _read_bytes(entry, MAX_SMALL_RECORD_BYTES)
                    usage.add(st)
                elif area == LOCKS_DIRECTORY:
                    if name != EXPORT_LOCK_NAME or not _plain_file(st):
                        raise ProjectionStoreError(UNKNOWN_ENTRY, "LOCKS")
                    usage.add(st)
                else:
                    match = _EVIDENCE_STAGING_RE.match(name)
                    if match is None:
                        raise ProjectionStoreError(UNKNOWN_ENTRY, "STAGING")
                    if match.group(1) is not None:
                        if not _plain_directory(st):
                            raise ProjectionStoreError(UNSAFE_ENTRY, "STAGING")
                        residue[(match.group(1).upper(), match.group(2))] = self._read_records(entry, usage)
                    else:
                        if not _plain_file(st):
                            raise ProjectionStoreError(UNSAFE_ENTRY, "STAGING")
                        residue[(match.group(3).upper(), match.group(4))] = _read_bytes(entry, MAX_SMALL_RECORD_BYTES)
                        usage.add(st)
        return PrivateSnapshot(bundles=groups[BUNDLES_DIRECTORY], bindings=groups[BINDINGS_DIRECTORY],
                               completions=groups[COMPLETIONS_DIRECTORY], failures=groups[FAILURES_DIRECTORY], residue=residue,
                               used_bytes=usage.total)

    def snapshot_vault(self, locks: ExportLocks) -> VaultSnapshot:
        """`generated/` の byte（pointer ・版 ・staging ・pointer の一時 file）と中断の保存の名前 ・大きさ（中身は読まない）。未知の entry は拒む。"""
        self.check_locks(locks)
        usage = _Usage()
        usage.total += SIZE_UNIT
        pointer, versions, staging, temps, interrupted = None, {}, {}, {}, []
        for name in _entries(self._generated()):
            entry = self._generated(name)
            st = _lstat_or_none(entry)
            if st is None:
                raise ProjectionStoreError(LAYOUT_INVALID, "ENTRY_VANISHED")
            if name in (VAULT_LOCK_NAME, POINTER_NOTE_NAME):
                if not _plain_file(st):
                    raise ProjectionStoreError(UNSAFE_ENTRY, "GENERATED_FILE")
                if name == POINTER_NOTE_NAME:
                    pointer = _read_bytes(entry, MAX_NOTE_BYTES)
                usage.add(st)
            elif _VERSION_LABEL_RE.match(name):
                if not _plain_directory(st):
                    raise ProjectionStoreError(UNSAFE_ENTRY, "VERSION")
                usage.add(st)
                versions[name] = self._read_notes(entry, usage)
            elif name == VAULT_STAGING_DIRECTORY:
                if not _plain_directory(st):
                    raise ProjectionStoreError(UNSAFE_ENTRY, "VAULT_STAGING")
                usage.add(st)
                for child in _entries(entry):
                    location = os.path.join(entry, child)
                    child_st = _lstat_or_none(location)
                    if child_st is None:
                        raise ProjectionStoreError(LAYOUT_INVALID, "ENTRY_VANISHED")
                    temp = _POINTER_TEMP_RE.match(child)
                    if _VERSION_LABEL_RE.match(child) and _plain_directory(child_st):
                        usage.add(child_st)
                        staging[child] = self._read_notes(location, usage)
                    elif temp is not None and _plain_file(child_st):
                        temps[temp.group(1)] = _read_bytes(location, MAX_NOTE_BYTES)
                        usage.add(child_st)
                    else:
                        raise ProjectionStoreError(UNKNOWN_ENTRY, "VAULT_STAGING")
            elif name == VAULT_INTERRUPTED_DIRECTORY:
                if not _plain_directory(st):
                    raise ProjectionStoreError(UNSAFE_ENTRY, "VAULT_INTERRUPTED")
                usage.add(st)
                for child in _entries(entry):
                    location = os.path.join(entry, child)
                    child_st = _lstat_or_none(location)
                    if not _INTERRUPTED_RE.match(child) or child_st is None or not _plain_directory(child_st):
                        raise ProjectionStoreError(UNKNOWN_ENTRY, "VAULT_INTERRUPTED")
                    usage.add(child_st)
                    for note in _entries(location, MAX_EXPORT_FILES):                       # 大きさだけ（中身は読まない）
                        note_st = _lstat_or_none(os.path.join(location, note))
                        if note_st is None or not _plain_file(note_st):
                            raise ProjectionStoreError(UNSAFE_ENTRY, "VAULT_INTERRUPTED")
                        usage.add(note_st)
                    interrupted.append(child)
            else:
                raise ProjectionStoreError(UNKNOWN_ENTRY, "GENERATED")
        return VaultSnapshot(pointer=pointer, versions=versions, staging=staging, pointer_temps=temps, interrupted=tuple(interrupted),
                             used_bytes=usage.total)

    def _volume(self, location: str) -> int:
        st = _lstat_or_none(location)
        if st is None:
            raise ProjectionStoreError(CAPACITY_UNVERIFIED, "VOLUME")
        return st.st_dev

    def free_space(self, locks: ExportLocks) -> FreeSpace:
        """vault の `generated/` と `projection/` の volume の空き（同じ volume かどうかも）。取れなければ容量は検証できない。"""
        self.check_locks(locks)
        return FreeSpace(vault_free=_free_bytes(self._generated()), private_free=_free_bytes(self._projection()),
                         same_volume=self._volume(self._generated()) == self._volume(self._projection()))

    def private_free_space(self, locks: ExportLocks) -> int:
        """失敗の証拠だけを書く前の `projection/` の volume の空き。"""
        self._check_private_locks(locks)
        return _free_bytes(self._projection())

    # ------------------------------------------------ 書き込み（全て 2 つの lock の下 ・追加 ・置き換えない移動 ・pointer の置換だけ）

    def _finish_bundle_files(self, locks: ExportLocks, partial: str, files: Mapping[str, bytes]) -> None:
        present = set(_entries(partial, len(EVIDENCE_RECORD_NAMES)))
        if present - set(files):
            raise ProjectionStoreError(STAGING_CONFLICT, "FOREIGN_RECORD")
        for name in sorted(present):
            if _read_bytes(os.path.join(partial, name), MAX_NOTE_BYTES) != files[name]:
                raise ProjectionStoreError(STAGING_CONFLICT, "RECORD_BYTES")             # 決定論の期待と違う作業中の byte は触らない
        for name in sorted(set(files) - present):
            self._check_private_locks(locks)
            try:
                _create_file(os.path.join(partial, name), files[name])
            except FileExistsError:
                raise ProjectionStoreError(STAGING_CONFLICT, "APPEARED") from None
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "RECORD_WRITE") from None
        _fsync_directory(partial)

    def write_evidence_bundle(self, locks: ExportLocks, area: str, name: str, files: Mapping[str, bytes]) -> str:
        """`bundles/` ／ `bindings/` の 1 つの bundle を staging で作り（byte 一致の作業中の残りは続きに使う）、読み戻して 1 回の置き換えない
        移動で現れさせる。既に在れば byte 一致の時だけ EVIDENCE_ALREADY_RECORDED（違えば上書きしない）。"""
        if (area not in _BUNDLE_AREAS or not is_digest(name) or not isinstance(files, Mapping) or not files
                or set(files) - EVIDENCE_RECORD_NAMES or not all(isinstance(d, bytes) and 0 < len(d) <= MAX_NOTE_BYTES for d in files.values())):
            raise ProjectionStoreError(STORE_INPUT_INVALID, "BUNDLE")
        self._check_private_locks(locks)
        final = self._projection(area, name)
        usage = _Usage()
        if _lstat_or_none(final) is not None:
            if self._read_records(final, usage) != dict(files):
                raise ProjectionStoreError(EVIDENCE_CONFLICT, area.upper())
            return EVIDENCE_ALREADY_RECORDED
        partial = self._projection(STAGING_DIRECTORY, f"{_BUNDLE_AREAS[area]}.{name}{PARTIAL_SUFFIX}")
        st = _lstat_or_none(partial)
        if st is None:
            try:
                _make_directory(partial)
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "STAGING_CREATE") from None
        elif not _plain_directory(st):
            raise ProjectionStoreError(STAGING_CONFLICT, "STAGING_KIND")
        self._finish_bundle_files(locks, partial, files)
        if self._read_records(partial, usage) != dict(files):
            raise ProjectionStoreError(STAGING_VERIFICATION_FAILED, "BUNDLE_READ_BACK")
        self._check_private_locks(locks)
        if _lstat_or_none(final) is not None:
            raise ProjectionStoreError(EVIDENCE_CONFLICT, "APPEARED")
        try:
            os.rename(partial, final)                                                      # 1 回だけ（空でない directory は置き換えられない）
        except OSError:
            raise ProjectionStoreError(STORE_IO_FAILED, "BUNDLE_MOVE") from None
        _fsync_directory(self._projection(area))
        _fsync_directory(self._projection(STAGING_DIRECTORY))
        if self._read_records(final, usage) != dict(files):
            raise ProjectionStoreError(STAGING_VERIFICATION_FAILED, "BUNDLE_FINAL")
        return EVIDENCE_RECORDED

    def write_record(self, locks: ExportLocks, area: str, name: str, data: bytes) -> str:
        """`completions/` ／ `failures/` の 1 つの record を一時 file から 1 回の rename で置く（既に在れば byte 一致の時だけ
        EVIDENCE_ALREADY_RECORDED）。完了は byte 一致の残りの一時 file を続きに使う。FAILED の一時 file は**この操作が作って所有を確かめた
        ものだけ**を rename する（前から在る一時 file は byte が同じでも採らない ・消さない ・移さない ・STAGING_CONFLICT）。完了は vault も、
        失敗は composition root だけを確かめる。"""
        if area not in _RECORD_AREAS or not is_digest(name) or not isinstance(data, bytes) or not 0 < len(data) <= MAX_SMALL_RECORD_BYTES:
            raise ProjectionStoreError(STORE_INPUT_INVALID, "RECORD")
        check = self.check_locks if area == COMPLETIONS_DIRECTORY else self._check_private_locks
        check(locks)
        final = self._projection(area, name + RECORD_SUFFIX)
        existing = _read_optional(final, MAX_SMALL_RECORD_BYTES)
        if existing is not None:
            if existing != data:
                raise ProjectionStoreError(EVIDENCE_CONFLICT, area.upper())
            return EVIDENCE_ALREADY_RECORDED
        temporary = self._projection(STAGING_DIRECTORY, f"{_RECORD_AREAS[area]}.{name}{TEMP_SUFFIX}")
        identity = None
        if _lstat_or_none(temporary) is not None:
            if area == FAILURES_DIRECTORY:
                raise ProjectionStoreError(STAGING_CONFLICT, "FAILURE_RESIDUE")              # 残った FAILED の一時 file は採らない
            if _read_optional(temporary, MAX_SMALL_RECORD_BYTES) != data:
                raise ProjectionStoreError(STAGING_CONFLICT, "RECORD_BYTES")
        else:
            try:
                identity = _create_file(temporary, data)
            except FileExistsError:
                raise ProjectionStoreError(STAGING_CONFLICT, "APPEARED") from None
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "RECORD_WRITE") from None
        if _read_optional(temporary, MAX_SMALL_RECORD_BYTES) != data:
            raise ProjectionStoreError(STAGING_VERIFICATION_FAILED, "RECORD_READ_BACK")
        check(locks)
        if identity is not None and not _owned(temporary, identity, data):
            raise ProjectionStoreError(STAGING_CONFLICT, "TEMP_NOT_OWNED")                    # 作った一時 file が替わった: rename しない
        if _lstat_or_none(final) is not None:
            raise ProjectionStoreError(EVIDENCE_CONFLICT, "APPEARED")
        try:
            os.rename(temporary, final)                                                    # A3 の試行の証拠と同じ（予約の空 file を残さない）
        except OSError:
            raise ProjectionStoreError(STORE_IO_FAILED, "RECORD_MOVE") from None
        _fsync_directory(self._projection(area))
        _fsync_directory(self._projection(STAGING_DIRECTORY))
        if _read_optional(final, MAX_SMALL_RECORD_BYTES) != data:
            raise ProjectionStoreError(STAGING_VERIFICATION_FAILED, "RECORD_FINAL")
        return EVIDENCE_RECORDED

    def _vault_staging(self) -> str:
        location = self._generated(VAULT_STAGING_DIRECTORY)
        st = _lstat_or_none(location)
        if st is None:
            try:
                _make_directory(location)
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "VAULT_STAGING_CREATE") from None
        elif not _plain_directory(st):
            raise ProjectionStoreError(UNSAFE_ENTRY, "VAULT_STAGING")
        return location

    def stage_notes(self, locks: ExportLocks, label: str, notes: Mapping[str, bytes], existing: Tuple[str, ...]) -> None:
        """開いた intent の staging に note を排他で作る（`existing` に挙げた在る file には触らない ・在る file の集合が違えば拒む ・
        上書きは無い）。作った file は読み戻して照らす。"""
        if (not isinstance(label, str) or not _VERSION_LABEL_RE.match(label) or not isinstance(notes, Mapping)
                or not all(isinstance(n, str) and _NOTE_NAME_RE.match(n) and isinstance(d, bytes) and 0 < len(d) <= MAX_NOTE_BYTES
                           for n, d in notes.items()) or not isinstance(existing, tuple) or set(existing) & set(notes)):
            raise ProjectionStoreError(STORE_INPUT_INVALID, "STAGE")
        self.check_locks(locks)
        folder = os.path.join(self._vault_staging(), label)
        st = _lstat_or_none(folder)
        if st is None:
            if existing:
                raise ProjectionStoreError(STAGING_CONFLICT, "STAGING_ABSENT")
            try:
                _make_directory(folder)
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "STAGING_CREATE") from None
        elif not _plain_directory(st) or set(_entries(folder, MAX_EXPORT_FILES)) != set(existing):
            raise ProjectionStoreError(STAGING_CONFLICT, "STAGING_ENTRIES")
        for name in sorted(notes):
            self.check_locks(locks)
            try:
                _create_file(os.path.join(folder, name), notes[name])
            except FileExistsError:
                raise ProjectionStoreError(STAGING_CONFLICT, "APPEARED") from None
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "NOTE_WRITE") from None
        _fsync_directory(folder)
        for name in sorted(notes):
            if _read_bytes(os.path.join(folder, name), MAX_NOTE_BYTES) != notes[name]:
                raise ProjectionStoreError(STAGING_VERIFICATION_FAILED, "NOTE_READ_BACK")

    def move_staged(self, locks: ExportLocks, label: str) -> None:
        """検証した staging を版の folder へ 1 回の置き換えない移動で移す（版の folder が既に在れば拒む）。"""
        if not isinstance(label, str) or not _VERSION_LABEL_RE.match(label):
            raise ProjectionStoreError(STORE_INPUT_INVALID, "MOVE")
        self.check_locks(locks)
        source = self._generated(VAULT_STAGING_DIRECTORY, label)
        st = _lstat_or_none(source)
        if st is None or not _plain_directory(st):
            raise ProjectionStoreError(STAGING_CONFLICT, "STAGING_ABSENT")
        target = self._generated(label)
        if _lstat_or_none(target) is not None:
            raise ProjectionStoreError(VERSION_CONFLICT, "PRESENT")
        try:
            _move_without_replacing(source, target, directory=True)
        except FileExistsError:
            raise ProjectionStoreError(VERSION_CONFLICT, "APPEARED") from None
        except OSError:
            raise ProjectionStoreError(STORE_IO_FAILED, "VERSION_MOVE") from None
        _fsync_directory(self._generated())
        _fsync_directory(self._generated(VAULT_STAGING_DIRECTORY))

    def replace_pointer(self, locks: ExportLocks, expected: Optional[bytes], replacement: bytes, export_digest: str) -> None:
        """pointer の置換: 一時 file（byte 一致の作業中の残りは続きに使う）を読み戻し、pointer が `expected` のままであることを確かめて
        `os.replace` で替え、読み戻して照らす（他の vault の file は替えない）。"""
        if not isinstance(replacement, bytes) or not 0 < len(replacement) <= MAX_NOTE_BYTES or not is_digest(export_digest) or not (
                expected is None or isinstance(expected, bytes)):
            raise ProjectionStoreError(STORE_INPUT_INVALID, "POINTER")
        self.check_locks(locks)
        temporary = os.path.join(self._vault_staging(), f"{_POINTER_STEM}.{export_digest}{TEMP_SUFFIX}")
        held = _read_optional(temporary, MAX_NOTE_BYTES)
        if held is None:
            try:
                _create_file(temporary, replacement)
            except FileExistsError:
                raise ProjectionStoreError(STAGING_CONFLICT, "APPEARED") from None
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "POINTER_TEMP") from None
        elif held != replacement:
            raise ProjectionStoreError(STAGING_CONFLICT, "POINTER_TEMP_BYTES")
        if _read_optional(temporary, MAX_NOTE_BYTES) != replacement:
            raise ProjectionStoreError(STAGING_VERIFICATION_FAILED, "POINTER_TEMP")
        self.check_locks(locks)
        target = self._generated(POINTER_NOTE_NAME)
        if _read_optional(target, MAX_NOTE_BYTES) != expected:
            raise ProjectionStoreError(POINTER_CHANGED)                                   # 観測の後に替わった pointer には触らない
        try:
            os.replace(temporary, target)
        except OSError:
            raise ProjectionStoreError(STORE_IO_FAILED, "POINTER_REPLACE") from None        # 一時 file は残す（byte 一致なら次に続ける）
        _fsync_directory(self._generated())
        _fsync_directory(self._generated(VAULT_STAGING_DIRECTORY))
        if _read_optional(target, MAX_NOTE_BYTES) != replacement:
            raise ProjectionStoreError(POINTER_VERIFICATION_FAILED)

    def preserve(self, locks: ExportLocks, area: str, label: str) -> str:
        """人の明示の保存: 開いた intent の staging、または空の版の予約を `.p13-interrupted/<label>.<NNN>.interrupted` に移す（空いた番号
        だけ ・消さない ・既存の entry を置き換えない）。移した先に同じ identity が在ることを確かめる。"""
        if area not in (PRESERVE_AREA_STAGING, PRESERVE_AREA_RESERVATION) or not isinstance(label, str) or not _VERSION_LABEL_RE.match(label):
            raise ProjectionStoreError(STORE_INPUT_INVALID, "PRESERVE")
        self.check_locks(locks)
        source = self._generated(VAULT_STAGING_DIRECTORY, label) if area == PRESERVE_AREA_STAGING else self._generated(label)
        before = _lstat_or_none(source)
        if before is None or not _plain_directory(before):
            raise ProjectionStoreError(UNSAFE_ENTRY, "PRESERVE_SOURCE")
        if area == PRESERVE_AREA_RESERVATION and _entries(source, 1):
            raise ProjectionStoreError(RESERVATION_NOT_EMPTY)                              # 空であることを移す直前に確かめる
        interrupted = self._generated(VAULT_INTERRUPTED_DIRECTORY)
        st = _lstat_or_none(interrupted)
        if st is None:
            try:
                _make_directory(interrupted)
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "INTERRUPTED_CREATE") from None
        elif not _plain_directory(st):
            raise ProjectionStoreError(UNSAFE_ENTRY, "VAULT_INTERRUPTED")
        for slot in range(1, MAX_INTERRUPTED_SLOTS + 1):
            preserved = f"{label}.{slot:03d}{INTERRUPTED_SUFFIX}"
            target = os.path.join(interrupted, preserved)
            if _lstat_or_none(target) is not None:
                continue
            self.check_locks(locks)
            try:
                _move_without_replacing(source, target, directory=True)
            except FileExistsError:
                continue                                                                   # 番号が埋まった: 次の番号（置き換えない）
            except OSError:
                raise ProjectionStoreError(STORE_IO_FAILED, "PRESERVE_MOVE") from None
            _fsync_directory(interrupted)
            _fsync_directory(os.path.dirname(source))
            after = _lstat_or_none(target)
            if after is None or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or _lstat_or_none(source) is not None:
                raise ProjectionStoreError(PRESERVATION_UNVERIFIED)
            return preserved
        raise ProjectionStoreError(INTERRUPTED_SLOTS_EXHAUSTED)


# ---------------------------------------------------------------- 明示の入口（初期化 ・開く）


def initialize_private_root(root: Any, *, protected_roots: Mapping[str, Any]) -> None:
    """明示の初期化だけ: 空の directory（または親が在る未作成の名前）に目印 ・`projection/` の固定の layout を作り、`memory/` は A3 の公開の
    `initialize_memory_root` に作らせる（A3 の layout は A3 だけが作る）。既存 ・空でない root は拒む。途中の失敗は残す（消さない）。"""
    text = _root_text(root)
    protected = _protected(protected_roots)
    _check_disjoint(text, protected)
    _check_private_markers(text)
    st = _check_ancestors(text, absent_code=ROOT_PARENT_MISSING, root_may_be_absent=True)
    if st is None:
        try:
            _make_directory(text)
        except FileExistsError:
            raise ProjectionStoreError(ROOT_NOT_EMPTY, "APPEARED") from None
        except OSError:
            raise ProjectionStoreError(STORE_IO_FAILED, "ROOT_CREATE") from None
    else:
        existing = _entries(text)
        if PRIVATE_MARKER_NAME in existing:
            raise ProjectionStoreError(ROOT_ALREADY_INITIALIZED)
        if existing:
            raise ProjectionStoreError(ROOT_NOT_EMPTY)
    _check_ancestors(text, absent_code=PRIVATE_ROOT_MISSING)
    try:
        _create_file(os.path.join(text, PRIVATE_MARKER_NAME), private_root_marker_bytes())
    except FileExistsError:
        raise ProjectionStoreError(ROOT_ALREADY_INITIALIZED, "APPEARED") from None
    except OSError:
        raise ProjectionStoreError(STORE_IO_FAILED, "MARKER_CREATE") from None
    projection = os.path.join(text, PROJECTION_CHILD)
    try:
        _make_directory(projection)
        for name in PROJECTION_LAYOUT:
            _make_directory(os.path.join(projection, name))
    except OSError:
        raise ProjectionStoreError(STORE_IO_FAILED, "LAYOUT_CREATE") from None             # 途中の layout は残す（LAYOUT_INVALID で開けない）
    try:
        initialize_memory_root(os.path.join(text, MEMORY_CHILD), protected_roots={**dict(protected_roots), PROJECTION_ROOT_LABEL: projection})
    except MemoryStoreError as exc:
        raise ProjectionStoreError(MEMORY_INITIALIZATION_FAILED, exc.code) from None


def open_projection_store(private_root: Any, vault_root: Any, *, protected_roots: Mapping[str, Any]) -> ProjectionStore:
    """初期化済みの composition root と人が用意した vault を開く（作らない）。2 つの root の形 ・祖先 ・同期 ／ git ／ vault の目印 ・互いと
    保護の root ・repository との重なり ・目印 ・layout ・Obsidian の設定を検査する。"""
    private_text, vault_text = _root_text(private_root), _root_text(vault_root)
    protected = _protected(protected_roots)
    if _overlaps(private_text, vault_text):
        raise ProjectionStoreError(ROOT_OVERLAP, VAULT_ROOT_LABEL)
    _check_disjoint(private_text, protected)
    _check_disjoint(vault_text, protected)
    _check_private_markers(private_text)
    _check_vault_markers(vault_text)
    identities = {}
    for key, location, absent in (("PRIVATE", private_text, PRIVATE_ROOT_MISSING), ("VAULT", vault_text, VAULT_INVALID)):
        st = _check_ancestors(location, absent_code=absent)
        if not st.st_ino:
            raise ProjectionStoreError(ROOT_UNSAFE_COMPONENT, "IDENTITY_UNAVAILABLE")      # identity を検証できない file system は拒む
        identities[key] = (st.st_dev, st.st_ino)
    for key, location, absent in (("PROJECTION", os.path.join(private_text, PROJECTION_CHILD), LAYOUT_INVALID),
                                  ("GENERATED", os.path.join(vault_text, GENERATED_DIRECTORY), VAULT_GENERATED_MISSING)):
        st = _lstat_or_none(location)
        if st is None:
            raise ProjectionStoreError(absent, key)
        if not _plain_directory(st) or not st.st_ino:
            raise ProjectionStoreError(ROOT_UNSAFE_COMPONENT, key)
        identities[key] = (st.st_dev, st.st_ino)
    store = ProjectionStore(private_text, vault_text, identities, protected, _SENTINEL)
    store._verify_private()
    store._verify_vault()
    store._check_plugins()
    return store


__all__ = ["BINDINGS_DIRECTORY", "BINDING_RECORD", "BUNDLES_DIRECTORY", "CAPACITY_UNVERIFIED", "COMPLETIONS_DIRECTORY", "ENTRY_LIMIT_EXCEEDED",
           "EVIDENCE_ALREADY_RECORDED", "EVIDENCE_CONFLICT", "EVIDENCE_RECORDED", "EVIDENCE_RECORD_NAMES", "EXPORT_LOCK_NAME", "ExportLock",
           "ExportLocks", "FAILURES_DIRECTORY", "FreeSpace", "GENERATED_DIRECTORY", "INTENT_RECORD", "INTERRUPTED_SLOTS_EXHAUSTED",
           "LAYOUT_INVALID", "LOCKS_DIRECTORY", "LOCK_NOT_ACQUIRED", "LOCK_OPERATIONS", "LOCK_OWNERSHIP_UNVERIFIED", "LOCK_RELEASED",
           "LOCK_RELEASE_FAILED", "LOCK_SCHEMA_VERSION", "MARKER_INVALID", "MEMORY_CHILD", "MEMORY_INITIALIZATION_FAILED", "OBSIDIAN_DIRECTORY",
           "PLUGIN_REFUSED", "PLUGIN_STATE_FILES", "PLUGIN_STATE_UNVERIFIED", "POINTER_CHANGED", "POINTER_VERIFICATION_FAILED",
           "PRESERVATION_UNVERIFIED", "PRIVATE_LOCK_PRESENT", "PRIVATE_MARKER_NAME", "PRIVATE_ROOT_MISSING", "PROJECTION_CHILD",
           "PROJECTION_LAYOUT", "PROJECTION_ROOT_LABEL", "PROTECTED_ROOT_INVALID", "PUBLIC_EXPORT_RECORD", "PrivateSnapshot",
           "ProjectionStore", "ProjectionStoreError", "REFUSAL_CODES", "REFUSED_APP_SETTINGS", "REFUSED_COMMUNITY_PLUGINS",
           "REFUSED_CORE_PLUGINS", "RESERVATION_NOT_EMPTY", "ROOT_ALREADY_INITIALIZED", "ROOT_IDENTITY_MISMATCH", "ROOT_INSIDE_VAULT",
           "ROOT_INSIDE_WORKING_TREE", "ROOT_INVALID", "ROOT_NOT_EMPTY", "ROOT_OVERLAP", "ROOT_PARENT_MISSING", "ROOT_SYNC_FOLDER",
           "ROOT_UNSAFE_COMPONENT", "SCAN_RECORD", "SIZE_UNIT", "SOURCE_RECORD", "STAGING_CONFLICT", "STAGING_DIRECTORY",
           "STAGING_VERIFICATION_FAILED", "STORE_INPUT_INVALID", "STORE_IO_FAILED", "UNKNOWN_ENTRY", "UNSAFE_ENTRY", "VAULT_GENERATED_MISSING",
           "VAULT_INTERRUPTED_DIRECTORY", "VAULT_INVALID", "VAULT_LOCK_NAME", "VAULT_LOCK_PRESENT", "VAULT_MARKER_INVALID",
           "VAULT_MARKER_MISSING", "VAULT_MARKER_NAME", "VAULT_ROOT_LABEL", "VAULT_STAGING_DIRECTORY", "VAULT_SYNC_FOLDER",
           "VAULT_WORKING_TREE", "VERSION_CONFLICT", "VaultSnapshot", "initialize_private_root", "lock_record", "open_projection_store",
           "private_root_marker_bytes", "storage_units", "vault_root_marker_bytes"]
