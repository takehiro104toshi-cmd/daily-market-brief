"""P13-A3 — Memory の private root の store（P13 で filesystem の I/O を持つ唯一の module）。

root:
- 明示の絶対 path だけ（既定 ・暗黙の作成は無い）。初期化は `initialize_memory_root` の明示の呼び出しだけで、空の directory（または親の
  在る未作成の名前）に目印 `.p13-memory-root` と固定の layout を作る。開く時と重要な操作の前に root の identity（`st_dev` ・`st_ino`）・
  目印 ・layout を再検査する。
- 呼び出し側が渡した保護する root（P8 〜 P12 の authority ・source ・vault など）と、この code の repository の位置に重なる root は拒む。
  **位置を渡されていない root の重なりは検査できない**（主張しない）。祖先に `.git` ・`.obsidian` ・既知の同期 folder の名前 ／ 目印が在れば
  拒む（同期の検出は網羅ではない）。
- root から file までの全ての成分で symlink ・junction ・reparse point を拒む（`os.lstat` ・Windows は `st_file_attributes`。host の OS と
  Python が出す範囲だけ）。検査と操作の間の TOCTOU は stdlib では閉じない。

layout（`<root>/market_memory/`）: `generations/<generation digest>/`（不変）・`staging/`（作業中 ・在れば書き込みを拒む）・`interrupted/`
（明示の回復が保存した物）・`attempts/<attempt digest>.json`（不完全な計画の証拠）・`locks/writer.lock`・`publication.json`（公開の pointer）。

書き込み: 単一の writer lock（O_CREAT|O_EXCL）→ staging に排他の作成 ・binary ・全て書く ・fsync ・読み戻しの照合 ・厳密な検証 → generation の
directory の 1 回の rename → 読み戻しの検証 → pointer の一時 file → `os.replace` → pointer ・generation ・manifest の読み戻しの検証。
rename だけでは公開の成功ではない。削除は `_unlink_if_owned` の 1 箇所だけで、所有を検証した自分の writer lock の解放と、自分の pointer の
一時 file の破棄にだけ使う。generation ・試行の証拠 ・中断の staging ・公開済みの data は消さない ・上書きしない ・自動で修復しない。

人の明示の回復は 2 つだけ（自動では呼ばれない ・何も消さない ・既存の entry を置き換えない）: 中断の staging の保存と、形が壊れた ／ 参照先が
確定的に検証できない pointer の保存。残った ／ 所有を検証できない writer lock を動かす ・奪う手段は P13 に無い（lock は書き込みを拒み続ける）。
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from .canonical import CanonicalError, is_digest, require_safe_code
from .memory_generation import (MANIFEST_RECORD_NAME, MAX_GENERATION_RECORDS, MAX_RECORD_BYTES, RECORD_SUFFIX, SCHEMA_UNSUPPORTED,
                                UNAUTHORIZED_ENTRY, AttemptRecord, MemoryGeneration, MemoryGenerationError, PublicationRecord,
                                VerifiedGeneration, check_marker, is_generation_record_name, lock_bytes, marker_bytes, parse_attempt,
                                parse_publication, verify_generation_records)

MARKER_NAME = ".p13-memory-root"
MEMORY_DIRECTORY = "market_memory"
ATTEMPTS_DIRECTORY = "attempts"
GENERATIONS_DIRECTORY = "generations"
INTERRUPTED_DIRECTORY = "interrupted"
LOCKS_DIRECTORY = "locks"
STAGING_DIRECTORY = "staging"
LAYOUT_DIRECTORIES = (ATTEMPTS_DIRECTORY, GENERATIONS_DIRECTORY, INTERRUPTED_DIRECTORY, LOCKS_DIRECTORY, STAGING_DIRECTORY)
PUBLICATION_NAME = "publication.json"
WRITER_LOCK_NAME = "writer.lock"
PARTIAL_SUFFIX = ".partial"
TEMP_SUFFIX = ".tmp"
INTERRUPTED_SUFFIX = ".interrupted"
MAX_INTERRUPTED_SLOTS = 999
MAX_SMALL_RECORD_BYTES = 64 * 1024
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
CODE_REPOSITORY_LABEL = "CODE_REPOSITORY"
#: 既知の同期 folder の名前（大小を畳んだ完全一致 ・接頭辞）と、祖先に在れば拒む目印。**網羅ではない**（未知の同期 ・後からの同期は防げない）
SYNC_FOLDER_NAMES = frozenset({"onedrive", "dropbox", "google drive", "googledrive", "my drive", "icloud drive", "iclouddrive",
                               "mobile documents", "com~apple~clouddocs", "box", "box sync", "nextcloud", "owncloud", "pcloud drive",
                               "mega", "megasync", "syncthing", "resilio sync", "tresorit", "sugarsync", "yandex.disk",
                               "creative cloud files"})
SYNC_FOLDER_PREFIXES = ("onedrive - ", "onedrive-", "dropbox (")
SYNC_MARKER_NAMES = (".dropbox", ".dropbox.cache", ".stfolder", ".sync", ".SynologyWorkingDirectory", ".tresorit", ".owncloudsync.log")
WORKING_TREE_MARKERS = (".git",)
VAULT_MARKERS = (".obsidian",)

#: 結果の code（固定の定数だけ ・path ・OS の文は出さない）
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
MEMORY_ROOT_MISSING = "MEMORY_ROOT_MISSING"
MARKER_INVALID = "MARKER_INVALID"
ROOT_IDENTITY_MISMATCH = "ROOT_IDENTITY_MISMATCH"
LAYOUT_INVALID = "LAYOUT_INVALID"
UNSAFE_ENTRY = "UNSAFE_ENTRY"
RECORD_TOO_LARGE = "RECORD_TOO_LARGE"
STORE_IO_FAILED = "STORE_IO_FAILED"
STORE_INPUT_INVALID = "STORE_INPUT_INVALID"
WRITER_LOCK_PRESENT = "WRITER_LOCK_PRESENT"
LOCK_OWNERSHIP_UNVERIFIED = "LOCK_OWNERSHIP_UNVERIFIED"
LOCK_RELEASED = "LOCK_RELEASED"
LOCK_RELEASE_FAILED = "LOCK_RELEASE_FAILED"
LOCK_NOT_ACQUIRED = "LOCK_NOT_ACQUIRED"
STAGING_PRESENT = "STAGING_PRESENT"
STAGING_VERIFICATION_FAILED = "STAGING_VERIFICATION_FAILED"
GENERATION_CONFLICT = "GENERATION_CONFLICT"
GENERATION_ABSENT = "GENERATION_ABSENT"
GENERATION_VERIFIED = "GENERATION_VERIFIED"
PUBLICATION_VERIFIED = "PUBLICATION_VERIFIED"
PUBLICATION_VERIFICATION_FAILED = "PUBLICATION_VERIFICATION_FAILED"
PUBLICATION_NOT_VERIFIED = "PUBLICATION_NOT_VERIFIED"
POINTER_PUBLICATION_FAILED = "POINTER_PUBLICATION_FAILED"
POINTER_VERIFICATION_FAILED = "POINTER_VERIFICATION_FAILED"
PUBLICATION_POINTER_INCONSISTENT = "PUBLICATION_POINTER_INCONSISTENT"
MEMORY_NOT_PUBLISHED = "MEMORY_NOT_PUBLISHED"
ATTEMPT_RECORDED = "ATTEMPT_RECORDED"
ATTEMPT_ALREADY_RECORDED = "ATTEMPT_ALREADY_RECORDED"
ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
INTERRUPTED_SLOTS_EXHAUSTED = "INTERRUPTED_SLOTS_EXHAUSTED"
PRESERVED = "PRESERVED"
NOTHING_TO_PRESERVE = "NOTHING_TO_PRESERVE"
POINTER_VERIFIED_NOT_PRESERVED = "POINTER_VERIFIED_NOT_PRESERVED"
PUBLICATION_STATE_UNCERTAIN = "PUBLICATION_STATE_UNCERTAIN"
PRESERVATION_UNVERIFIED = "PRESERVATION_UNVERIFIED"
#: 呼び出し側の root ・保護の root の誤り（開く ・初期化の拒否。読みの状態ではない）
REFUSAL_CODES = frozenset({ROOT_INVALID, PROTECTED_ROOT_INVALID, ROOT_UNSAFE_COMPONENT, ROOT_OVERLAP, ROOT_SYNC_FOLDER,
                           ROOT_INSIDE_WORKING_TREE, ROOT_INSIDE_VAULT, ROOT_PARENT_MISSING, ROOT_NOT_EMPTY, ROOT_ALREADY_INITIALIZED})

_BINARY = getattr(os, "O_BINARY", 0)                                                  # Windows: text mode は LF を CRLF に変える
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)                                              # POSIX: 最後の成分の symlink を辿らない
_REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
_SENTINEL = object()
_STAGING_NAME = re.compile(r"^(?:[0-9a-f]{64}\.partial|(?:publication|attempt)\.[0-9a-f]{64}\.tmp)$")
_INTERRUPTED_NAME = re.compile(r"^(?:[0-9a-f]{64}\.partial|(?:publication|attempt)\.[0-9a-f]{64}\.tmp|publication\.json)"
                               r"\.\d{3}\.interrupted$")                                    # writer lock は移さない（名前も認めない）
_ATTEMPT_NAME = re.compile(r"^[0-9a-f]{64}\.json$")
_REMOVED, _UNVERIFIED, _UNLINK_FAILED = "REMOVED", "OWNERSHIP_UNVERIFIED", "UNLINK_FAILED"
#: 公開の状態の層: 検証済み ／ pointer が無い ／ pointer の byte が壊れている ／ 参照先が確定的に不整合（不在 ・manifest の不一致 ・純粋な検証の
#: 失敗）／ 曖昧（root ・layout ・I/O ・安全でない entry ・読みの最中の変化）。pointer を移してよいのは POINTER ・REFERENCE だけ
_VERIFIED, _ABSENT, _POINTER, _REFERENCE, _UNCERTAIN = "VERIFIED", "ABSENT", "POINTER", "REFERENCE", "UNCERTAIN"


class MemoryStoreError(ValueError):
    """store の失敗（固定の code ・短い detail だけ。path ・OS の文 ・値は持たない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


class ReadStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    MISSING = "MISSING"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"


class PublishStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    REUSED = "REUSED"
    FAILED = "FAILED"
    REFUSED = "REFUSED"


@dataclass(frozen=True, kw_only=True)
class ReadResult:
    """読みの結果（固定の code ・digest だけ。検証済みの generation は repr に出さない）。"""

    status: ReadStatus
    code: str
    staging_present: bool = False
    verified: Optional[VerifiedGeneration] = field(default=None, repr=False)

    @property
    def generation_digest(self) -> Optional[str]:
        return None if self.verified is None else self.verified.generation_digest

    @property
    def manifest_digest(self) -> Optional[str]:
        return None if self.verified is None else self.verified.manifest_digest


@dataclass(frozen=True, kw_only=True)
class PublishOutcome:
    """公開の結果。`publication_*` は操作の後に実際に読み戻して検証した pointer の状態（検証しない主張はしない）。"""

    status: PublishStatus
    code: str
    generation_digest: Optional[str]
    manifest_digest: Optional[str]
    publication_status: ReadStatus
    publication_code: str
    publication_generation_digest: Optional[str]


@dataclass(frozen=True, kw_only=True)
class PreservationResult:
    """明示の回復の結果: 固定の code（PRESERVED ・NOTHING_TO_PRESERVE ・拒否の理由）・`interrupted/` に移した名前（digest ・固定の接尾辞だけ）・
    lock の解放の code。"""

    code: str
    preserved: Tuple[str, ...]
    lock_release: str


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
        raise MemoryStoreError(STORE_IO_FAILED, "LSTAT") from None


# ---------------------------------------------------------------- root の形 ・祖先 ・重なり ・目印


def _location_text(value: Any, code: str) -> str:
    if isinstance(value, str):
        text = value
    elif hasattr(value, "__fspath__"):
        text = os.fspath(value)
        if not isinstance(text, str):
            raise MemoryStoreError(code, "NOT_TEXT")
    else:
        raise MemoryStoreError(code, "TYPE")
    if text == "" or "\x00" in text or text != text.strip():
        raise MemoryStoreError(code, "SHAPE")
    if not os.path.isabs(text) or (os.name == "nt" and not os.path.splitdrive(text)[0]):
        raise MemoryStoreError(code, "NOT_ABSOLUTE")
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
        raise MemoryStoreError(ROOT_INVALID, "NOT_NORMALIZED")
    if not parts or any(part in (".", "..") for part in parts):
        raise MemoryStoreError(ROOT_INVALID, "TRAVERSAL_OR_ANCHOR")
    if os.name == "nt" and any(":" in part or part != part.rstrip(" .") for part in parts):
        raise MemoryStoreError(ROOT_INVALID, "WINDOWS_ALIAS")                         # ADS ・末尾の点 ／ 空白の別名
    return text


def _check_ancestors(text: str, *, absent_code: str, root_may_be_absent: bool) -> Optional[os.stat_result]:
    """anchor から root までの全ての成分が実在の directory（symlink ・junction ・reparse point ・file ではない）。"""
    prefixes = _prefixes(text)
    st = None
    for index, prefix in enumerate(prefixes):
        st = _lstat_or_none(prefix)
        if st is None:
            if index == len(prefixes) - 1 and root_may_be_absent:
                return None
            raise MemoryStoreError(absent_code, "ANCESTOR" if index < len(prefixes) - 1 else "ROOT")
        if not _plain_directory(st):
            raise MemoryStoreError(ROOT_UNSAFE_COMPONENT, "ROOT" if index == len(prefixes) - 1 else "ANCESTOR")
    return st


def _check_markers(text: str) -> None:
    """既知の同期 folder の名前 ・祖先の目印（同期 ・git の作業木 ・Obsidian の vault）。検出は網羅ではない。"""
    for part in _components(text):
        folded = part.casefold()
        if folded in SYNC_FOLDER_NAMES or folded.startswith(SYNC_FOLDER_PREFIXES):
            raise MemoryStoreError(ROOT_SYNC_FOLDER, "NAME")
    for prefix in _prefixes(text)[:-1]:
        for names, code in ((WORKING_TREE_MARKERS, ROOT_INSIDE_WORKING_TREE), (VAULT_MARKERS, ROOT_INSIDE_VAULT),
                            (SYNC_MARKER_NAMES, ROOT_SYNC_FOLDER)):
            for name in names:
                if _lstat_or_none(os.path.join(prefix, name)) is not None:
                    raise MemoryStoreError(code, "MARKER")


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
        raise MemoryStoreError(PROTECTED_ROOT_INVALID, "NOT_A_MAPPING")
    pairs = {(CODE_REPOSITORY_LABEL, _code_repository())}
    for label, location in protected_roots.items():
        try:
            require_safe_code(label, PROTECTED_ROOT_INVALID)
        except CanonicalError:
            raise MemoryStoreError(PROTECTED_ROOT_INVALID, "LABEL") from None
        pairs.add((label, _location_text(location, PROTECTED_ROOT_INVALID)))
    return tuple(sorted(pairs))


def _check_disjoint(root: str, protected: Tuple[Tuple[str, str], ...]) -> None:
    for label, location in protected:
        if _overlaps(root, location):
            raise MemoryStoreError(ROOT_OVERLAP, label)


# ---------------------------------------------------------------- file の I/O（binary ・排他 ・fsync ・読み戻し）


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
    """正規の file だけを読む（symlink ・reparse point ・特殊 file ・上限を超える長さは拒む。開いた fd の identity も照合）。"""
    st = os.lstat(location)
    if not _plain_file(st):
        raise MemoryStoreError(UNSAFE_ENTRY, "FILE_KIND")
    if st.st_size > limit:
        raise MemoryStoreError(RECORD_TOO_LARGE)
    fd = os.open(location, os.O_RDONLY | _BINARY | _NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino) or not stat.S_ISREG(opened.st_mode):
            raise MemoryStoreError(UNSAFE_ENTRY, "CHANGED_WHILE_OPENING")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, MAX_SMALL_RECORD_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise MemoryStoreError(RECORD_TOO_LARGE)
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b"".join(chunks)


def _read_optional(location: str, limit: int = MAX_RECORD_BYTES) -> Optional[bytes]:
    try:
        return _read_file(location, limit)
    except FileNotFoundError:
        return None
    except OSError:
        raise MemoryStoreError(STORE_IO_FAILED, "READ") from None


def _entries(location: str) -> Tuple[str, ...]:
    st = _lstat_or_none(location)
    if st is None:
        raise MemoryStoreError(LAYOUT_INVALID, "DIRECTORY_ABSENT")
    if not _plain_directory(st):
        raise MemoryStoreError(UNSAFE_ENTRY, "DIRECTORY_KIND")
    try:
        return tuple(sorted(os.listdir(location)))
    except OSError:
        raise MemoryStoreError(STORE_IO_FAILED, "LIST") from None


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
    except (OSError, MemoryStoreError):
        return False


def _unlink_if_owned(location: str, identity: Tuple[int, int], data: bytes) -> str:
    """P13 の唯一の削除。自分が排他で作り、まだ所有している一時の file（writer lock ・pointer の一時 file）だけ。曖昧なら消さずに残す。
    検証と unlink の間の TOCTOU は stdlib では閉じない（文書に記録）。"""
    if not _owned(location, identity, data):
        return _UNVERIFIED
    try:
        os.unlink(location)
    except OSError:
        return _UNLINK_FAILED
    _fsync_directory(os.path.dirname(location))
    return _REMOVED


def _move_without_replacing(source: str, target: str, *, directory: bool) -> None:
    """source を target へ移す。target に既存の entry が在れば失敗する（他の file ・証拠を置き換えない）。Windows の `os.rename` は既存の
    target を置き換えない。POSIX の rename は既存の file ・空の directory を黙って置き換えるので、先に target を排他で予約し（空の file は
    O_EXCL ・directory は mkdir）、所有を確かめた自分の空の予約だけを置き換える。予約と rename の間の TOCTOU は stdlib では閉じない。"""
    if os.name != "nt":
        if directory:
            os.mkdir(target, DIRECTORY_MODE)                                               # 既存なら FileExistsError（空でない予約は rename が拒む）
        else:
            identity = _create_file(target, b"")
            if not _owned(target, identity, b""):
                raise OSError("RESERVATION_NOT_OWNED")                                     # 予約が替わった: 置き換えない（予約は残す）
    os.rename(source, target)


def _read_status(code: str) -> ReadStatus:
    if code == MEMORY_ROOT_MISSING:
        return ReadStatus.MISSING
    if code == SCHEMA_UNSUPPORTED:
        return ReadStatus.SCHEMA_UNSUPPORTED
    return ReadStatus.INTEGRITY_FAILURE


def _verify_marker(root: str) -> None:
    try:
        data = _read_file(os.path.join(root, MARKER_NAME), MAX_SMALL_RECORD_BYTES)
    except FileNotFoundError:
        raise MemoryStoreError(MEMORY_ROOT_MISSING, "MARKER") from None
    except OSError:
        raise MemoryStoreError(STORE_IO_FAILED, "MARKER") from None
    try:
        check_marker(data)
    except MemoryGenerationError as exc:
        raise MemoryStoreError(SCHEMA_UNSUPPORTED if exc.code == SCHEMA_UNSUPPORTED else MARKER_INVALID, "MARKER") from None


def _check_layout_entries(memory: str, name: str) -> None:
    location = os.path.join(memory, name)
    for entry in _entries(location):
        st = _lstat_or_none(os.path.join(location, entry))
        if st is None:
            raise MemoryStoreError(LAYOUT_INVALID, "ENTRY_VANISHED")
        if name == GENERATIONS_DIRECTORY:
            accepted, kind_ok = is_digest(entry), _plain_directory(st)
        elif name == ATTEMPTS_DIRECTORY:
            accepted, kind_ok = bool(_ATTEMPT_NAME.match(entry)), _plain_file(st)
        elif name == LOCKS_DIRECTORY:
            accepted, kind_ok = entry == WRITER_LOCK_NAME, _plain_file(st)
        elif name == STAGING_DIRECTORY:
            accepted, kind_ok = bool(_STAGING_NAME.match(entry)), _plain_file(st) or _plain_directory(st)
        else:
            accepted, kind_ok = bool(_INTERRUPTED_NAME.match(entry)), _plain_file(st) or _plain_directory(st)
        if not accepted:
            raise MemoryStoreError(UNAUTHORIZED_ENTRY, name.upper())
        if not kind_ok:
            raise MemoryStoreError(UNSAFE_ENTRY, name.upper())


def _verify_layout(root: str) -> None:
    top = set(_entries(root))
    if top - {MARKER_NAME, MEMORY_DIRECTORY}:
        raise MemoryStoreError(UNAUTHORIZED_ENTRY, "ROOT")
    if MEMORY_DIRECTORY not in top:
        raise MemoryStoreError(LAYOUT_INVALID, "MEMORY_DIRECTORY")
    memory = os.path.join(root, MEMORY_DIRECTORY)
    inside = set(_entries(memory))
    if inside - set(LAYOUT_DIRECTORIES) - {PUBLICATION_NAME}:
        raise MemoryStoreError(UNAUTHORIZED_ENTRY, "MEMORY_DIRECTORY")
    if set(LAYOUT_DIRECTORIES) - inside:
        raise MemoryStoreError(LAYOUT_INVALID, "LAYOUT_DIRECTORY")
    for name in LAYOUT_DIRECTORIES:
        _check_layout_entries(memory, name)
    if PUBLICATION_NAME in inside:
        st = _lstat_or_none(os.path.join(memory, PUBLICATION_NAME))
        if st is None or not _plain_file(st):
            raise MemoryStoreError(UNSAFE_ENTRY, "PUBLICATION")


# ---------------------------------------------------------------- lock ・store


class WriterLock:
    """取得した単一の writer lock。解放は作った所有者だけ: 作成時の file の identity と byte が一致する時だけ消す（曖昧なら保存する）。"""

    def __init__(self, store: "MemoryStore", location: str, data: bytes, identity: Tuple[int, int], sentinel: object) -> None:
        if sentinel is not _SENTINEL:
            raise MemoryStoreError(LOCK_OWNERSHIP_UNVERIFIED, "DIRECT_CONSTRUCTION")
        self._store, self._location, self._data, self._identity = store, location, data, identity
        self._release_code: Optional[str] = None

    def __repr__(self) -> str:
        return f"WriterLock(release_code={self._release_code!r})"

    @property
    def release_code(self) -> Optional[str]:
        return self._release_code

    def owned(self) -> bool:
        return self._release_code is None and _owned(self._location, self._identity, self._data)

    def release(self) -> str:
        """1 回だけ。所有を検証できれば消して LOCK_RELEASED、できなければ残して LOCK_OWNERSHIP_UNVERIFIED、消せなければ LOCK_RELEASE_FAILED。"""
        if self._release_code is None:
            outcome = _unlink_if_owned(self._location, self._identity, self._data)
            self._release_code = {_REMOVED: LOCK_RELEASED, _UNVERIFIED: LOCK_OWNERSHIP_UNVERIFIED}.get(outcome, LOCK_RELEASE_FAILED)
        return self._release_code


class MemoryStore:
    """開いた（または初期化した）memory root。`open_memory_store` ／ `initialize_memory_root` だけが作る。repr に root は出さない。"""

    def __init__(self, root: str, identity: Tuple[int, int], protected: Tuple[Tuple[str, str], ...], sentinel: object) -> None:
        if sentinel is not _SENTINEL:
            raise MemoryStoreError(ROOT_INVALID, "DIRECT_CONSTRUCTION")
        self._root, self._identity, self._protected = root, identity, protected

    def __repr__(self) -> str:
        return f"MemoryStore(protected_labels={self.protected_labels!r})"

    @property
    def protected_labels(self) -> Tuple[str, ...]:
        """重なりを検査した保護の root の label（渡されていない root は含まない ＝ 主張しない）。"""
        return tuple(sorted({label for label, _ in self._protected}))

    def _memory(self, *parts: str) -> str:
        return os.path.join(self._root, MEMORY_DIRECTORY, *parts)

    def _verify_root(self) -> None:
        st = _check_ancestors(self._root, absent_code=MEMORY_ROOT_MISSING, root_may_be_absent=False)
        if (st.st_dev, st.st_ino) != self._identity:
            raise MemoryStoreError(ROOT_IDENTITY_MISMATCH)
        _verify_marker(self._root)
        _verify_layout(self._root)

    def check_disjoint(self, roots: Mapping[str, Any]) -> None:
        """追加の root（source ・vault など）がこの memory root と重ならないこと（渡された root だけを検査する）。"""
        if not isinstance(roots, Mapping):
            raise MemoryStoreError(PROTECTED_ROOT_INVALID, "NOT_A_MAPPING")
        pairs = []
        for label, location in roots.items():
            try:
                require_safe_code(label, PROTECTED_ROOT_INVALID)
            except CanonicalError:
                raise MemoryStoreError(PROTECTED_ROOT_INVALID, "LABEL") from None
            pairs.append((label, _location_text(location, PROTECTED_ROOT_INVALID)))
        _check_disjoint(self._root, tuple(sorted(pairs)))

    def acquire_writer_lock(self, *, operation: str, plan: Optional[str]) -> WriterLock:
        """O_CREAT|O_EXCL の単一の writer lock。既に在れば WRITER_LOCK_PRESENT（stale の推定 ・奪取は無い）。"""
        self._verify_root()
        location = self._memory(LOCKS_DIRECTORY, WRITER_LOCK_NAME)
        try:
            data = lock_bytes(operation, plan)
        except MemoryGenerationError:
            raise MemoryStoreError(STORE_INPUT_INVALID, "LOCK") from None
        try:
            identity = _create_file(location, data)
        except FileExistsError:
            raise MemoryStoreError(WRITER_LOCK_PRESENT) from None
        except OSError:
            raise MemoryStoreError(STORE_IO_FAILED, "LOCK_CREATE") from None                   # 書きかけの lock は残す（人の回復）
        _fsync_directory(self._memory(LOCKS_DIRECTORY))
        return WriterLock(self, location, data, identity, _SENTINEL)

    def _require_lock(self, lock: Any) -> None:
        if not isinstance(lock, WriterLock) or lock._store is not self or not lock.owned():
            raise MemoryStoreError(LOCK_OWNERSHIP_UNVERIFIED)

    def check_writable(self, lock: WriterLock) -> None:
        """lock の所有 ・root の identity ・目印 ・layout ・staging が空であること（中断の staging が在れば書き込みを拒む）。"""
        self._require_lock(lock)
        self._verify_root()
        if _entries(self._memory(STAGING_DIRECTORY)):
            raise MemoryStoreError(STAGING_PRESENT)

    # ------------------------------------------------ 読み

    def staging_present(self) -> bool:
        self._verify_root()
        return bool(_entries(self._memory(STAGING_DIRECTORY)))

    def list_generations(self) -> Tuple[str, ...]:
        self._verify_root()
        return _entries(self._memory(GENERATIONS_DIRECTORY))

    def list_attempts(self) -> Tuple[str, ...]:
        self._verify_root()
        return tuple(name[:-len(RECORD_SUFFIX)] for name in _entries(self._memory(ATTEMPTS_DIRECTORY)))

    def read_attempt(self, attempt_digest: str) -> AttemptRecord:
        if not is_digest(attempt_digest):
            raise MemoryStoreError(STORE_INPUT_INVALID, "ATTEMPT_DIGEST")
        self._verify_root()
        data = _read_optional(self._memory(ATTEMPTS_DIRECTORY, attempt_digest + RECORD_SUFFIX), MAX_SMALL_RECORD_BYTES)
        if data is None:
            raise MemoryStoreError(LAYOUT_INVALID, "ATTEMPT_ABSENT")
        try:
            record = parse_attempt(data)
        except MemoryGenerationError as exc:
            raise MemoryStoreError(exc.code, "ATTEMPT") from None
        if record.attempt_digest != attempt_digest:
            raise MemoryStoreError(ATTEMPT_CONFLICT, "DIGEST")
        return record

    def _generation_records(self, location: str) -> Dict[str, bytes]:
        names = _entries(location)
        if len(names) > MAX_GENERATION_RECORDS + 1:
            raise MemoryStoreError(UNAUTHORIZED_ENTRY, "RECORD_COUNT")
        records = {}
        for name in names:
            if not is_generation_record_name(name):
                raise MemoryStoreError(UNAUTHORIZED_ENTRY, "GENERATION_ENTRY")
            try:
                records[name] = _read_file(os.path.join(location, name), MAX_RECORD_BYTES)
            except OSError:
                raise MemoryStoreError(STORE_IO_FAILED, "GENERATION_READ") from None
        return records

    def _verified_generation(self, generation_digest: str) -> VerifiedGeneration:
        records = self._generation_records(self._memory(GENERATIONS_DIRECTORY, generation_digest))
        return verify_generation_records(records, expected_generation_digest=generation_digest)

    def _generation_state(self, generation_digest: str) -> Tuple[str, ReadResult]:
        """(層, 結果)。store の失敗（root ・layout ・I/O ・安全でない entry）は曖昧、純粋な検証の失敗は確定的な不整合。"""
        if not is_digest(generation_digest):
            raise MemoryStoreError(STORE_INPUT_INVALID, "GENERATION_DIGEST")
        try:
            self._verify_root()
            staging = bool(_entries(self._memory(STAGING_DIRECTORY)))
            if _lstat_or_none(self._memory(GENERATIONS_DIRECTORY, generation_digest)) is None:
                return _ABSENT, ReadResult(status=ReadStatus.MISSING, code=GENERATION_ABSENT, staging_present=staging)
            verified = self._verified_generation(generation_digest)
        except MemoryStoreError as exc:
            return _UNCERTAIN, ReadResult(status=_read_status(exc.code), code=exc.code)
        except MemoryGenerationError as exc:
            return _REFERENCE, ReadResult(status=_read_status(exc.code), code=exc.code, staging_present=staging)
        return _VERIFIED, ReadResult(status=ReadStatus.VERIFIED, code=GENERATION_VERIFIED, staging_present=staging, verified=verified)

    def read_generation(self, generation_digest: str) -> ReadResult:
        """1 つの generation の厳密な読み（不在は MISSING ・検証の失敗は INTEGRITY_FAILURE ／ SCHEMA_UNSUPPORTED）。"""
        return self._generation_state(generation_digest)[1]

    def _publication_state(self) -> Tuple[str, ReadResult]:
        """(層, 結果): pointer の正準性 → 参照先の generation の全ての検証 → manifest の digest の一致。"""
        try:
            self._verify_root()
            staging = bool(_entries(self._memory(STAGING_DIRECTORY)))
            data = _read_optional(self._memory(PUBLICATION_NAME), MAX_SMALL_RECORD_BYTES)
        except MemoryStoreError as exc:
            return _UNCERTAIN, ReadResult(status=_read_status(exc.code), code=exc.code)
        if data is None:
            return _ABSENT, ReadResult(status=ReadStatus.NOT_PUBLISHED, code=MEMORY_NOT_PUBLISHED, staging_present=staging)
        try:
            pointer = parse_publication(data)
        except MemoryGenerationError as exc:
            unsupported = exc.code == SCHEMA_UNSUPPORTED
            return _POINTER, ReadResult(status=ReadStatus.SCHEMA_UNSUPPORTED if unsupported else ReadStatus.INTEGRITY_FAILURE,
                                        code=SCHEMA_UNSUPPORTED if unsupported else PUBLICATION_POINTER_INCONSISTENT,
                                        staging_present=staging)
        layer, result = self._generation_state(pointer.generation_digest)
        if layer == _ABSENT:
            return _REFERENCE, ReadResult(status=ReadStatus.INTEGRITY_FAILURE, code=PUBLICATION_POINTER_INCONSISTENT,
                                          staging_present=staging)
        if layer != _VERIFIED:
            return layer, ReadResult(status=result.status, code=result.code, staging_present=staging)
        if result.manifest_digest != pointer.manifest_digest:
            return _REFERENCE, ReadResult(status=ReadStatus.INTEGRITY_FAILURE, code=PUBLICATION_POINTER_INCONSISTENT,
                                          staging_present=staging)
        return _VERIFIED, ReadResult(status=ReadStatus.VERIFIED, code=PUBLICATION_VERIFIED, staging_present=staging,
                                     verified=result.verified)

    def read_publication(self) -> ReadResult:
        """公開の pointer の厳密な読み: pointer の正準性 → 参照先の generation の全ての検証 → manifest の digest の一致。"""
        return self._publication_state()[1]

    # ------------------------------------------------ 書き（全て lock の下）

    def _outcome(self, status: PublishStatus, code: str, generation_digest: Optional[str], manifest_digest: Optional[str],
                 publication: Optional[ReadResult] = None) -> PublishOutcome:
        after = self.read_publication() if publication is None else publication          # 操作の後に実際に検証した状態だけを報告する
        return PublishOutcome(status=status, code=code, generation_digest=generation_digest, manifest_digest=manifest_digest,
                              publication_status=after.status, publication_code=after.code,
                              publication_generation_digest=after.generation_digest)

    def _stage_generation(self, lock: WriterLock, generation_digest: str, records: Dict[str, bytes]) -> None:
        partial = self._memory(STAGING_DIRECTORY, generation_digest + PARTIAL_SUFFIX)
        final = self._memory(GENERATIONS_DIRECTORY, generation_digest)
        try:
            os.mkdir(partial, DIRECTORY_MODE)
        except OSError:
            raise MemoryStoreError(STORE_IO_FAILED, "STAGING_CREATE") from None
        for name in sorted(records, key=lambda n: (n == MANIFEST_RECORD_NAME, n)):          # manifest は最後
            try:
                _create_file(os.path.join(partial, name), records[name])
            except OSError:
                raise MemoryStoreError(STORE_IO_FAILED, "ARTIFACT_WRITE") from None          # .partial は残す（明示の回復だけ）
        _fsync_directory(partial)
        staged = self._generation_records(partial)
        if staged != records:
            raise MemoryStoreError(STAGING_VERIFICATION_FAILED, "READ_BACK")
        try:
            verify_generation_records(staged, expected_generation_digest=generation_digest)
        except MemoryGenerationError as exc:
            raise MemoryStoreError(STAGING_VERIFICATION_FAILED, exc.code) from None
        self._require_lock(lock)
        self._verify_root()
        if _lstat_or_none(final) is not None:
            raise MemoryStoreError(GENERATION_CONFLICT, "APPEARED")
        try:
            os.rename(partial, final)                                                      # 1 回だけ（rename は公開の成功ではない）
        except OSError:
            raise MemoryStoreError(STORE_IO_FAILED, "GENERATION_RENAME") from None
        _fsync_directory(self._memory(GENERATIONS_DIRECTORY))
        _fsync_directory(self._memory(STAGING_DIRECTORY))
        try:
            self._verified_generation(generation_digest)
        except (MemoryStoreError, MemoryGenerationError) as exc:
            raise MemoryStoreError(PUBLICATION_VERIFICATION_FAILED, exc.code) from None

    def _publish_pointer(self, lock: WriterLock, generation_digest: str, manifest_digest: str, reused: bool) -> PublishOutcome:
        data = PublicationRecord(generation_digest=generation_digest, manifest_digest=manifest_digest).to_bytes()
        target = self._memory(PUBLICATION_NAME)
        success = PublishStatus.REUSED if reused else PublishStatus.PUBLISHED
        try:
            existing = _read_optional(target, MAX_SMALL_RECORD_BYTES)
        except MemoryStoreError as exc:
            return self._outcome(PublishStatus.FAILED, exc.code, generation_digest, manifest_digest)
        if existing != data:
            try:
                self.check_writable(lock)
            except MemoryStoreError as exc:
                return self._outcome(PublishStatus.FAILED, exc.code, generation_digest, manifest_digest)
            temporary = self._memory(STAGING_DIRECTORY, "publication." + generation_digest + TEMP_SUFFIX)
            try:
                identity = _create_file(temporary, data)
            except OSError:
                return self._outcome(PublishStatus.FAILED, POINTER_PUBLICATION_FAILED, generation_digest, manifest_digest)
            try:
                if _read_file(temporary, len(data)) != data:
                    raise MemoryStoreError(STAGING_VERIFICATION_FAILED, "POINTER")
                self._require_lock(lock)
                self._verify_root()
                os.replace(temporary, target)
            except MemoryStoreError as exc:
                _unlink_if_owned(temporary, identity, data)                                 # 自分の一時 file だけ（曖昧なら残す）
                return self._outcome(PublishStatus.FAILED, exc.code, generation_digest, manifest_digest)
            except OSError:
                _unlink_if_owned(temporary, identity, data)
                return self._outcome(PublishStatus.FAILED, POINTER_PUBLICATION_FAILED, generation_digest, manifest_digest)
            _fsync_directory(self._memory())
            _fsync_directory(self._memory(STAGING_DIRECTORY))
        after = self.read_publication()
        if (after.status is ReadStatus.VERIFIED and after.generation_digest == generation_digest
                and after.manifest_digest == manifest_digest):
            return self._outcome(success, success.value, generation_digest, manifest_digest, after)
        return self._outcome(PublishStatus.FAILED, POINTER_VERIFICATION_FAILED, generation_digest, manifest_digest, after)

    def publish_generation(self, lock: WriterLock, generation: MemoryGeneration) -> PublishOutcome:
        """完全な generation を不変の directory に置き、pointer を原子的に替え、読み戻しで検証する（同じ generation は REUSED）。"""
        if not isinstance(generation, MemoryGeneration):
            raise MemoryStoreError(STORE_INPUT_INVALID, "GENERATION")
        try:
            self.check_writable(lock)
        except MemoryStoreError as exc:
            return self._outcome(PublishStatus.REFUSED, exc.code, None, None)
        prior = self.read_publication()
        if prior.status not in (ReadStatus.VERIFIED, ReadStatus.NOT_PUBLISHED):           # 壊れた pointer は上書きしない（証拠を保存）
            return self._outcome(PublishStatus.REFUSED, PUBLICATION_NOT_VERIFIED, None, None, prior)
        generation_digest = generation.generation_digest
        manifest = generation.manifest()
        records = dict(generation.records())
        records[MANIFEST_RECORD_NAME] = manifest.to_bytes()
        try:
            present = _lstat_or_none(self._memory(GENERATIONS_DIRECTORY, generation_digest)) is not None
            if present:
                try:
                    verified = self._verified_generation(generation_digest)
                except (MemoryStoreError, MemoryGenerationError) as exc:
                    raise MemoryStoreError(GENERATION_CONFLICT, exc.code) from None          # 既存を上書きしない
                if verified.manifest_digest != manifest.manifest_digest:
                    raise MemoryStoreError(GENERATION_CONFLICT, "MANIFEST")
            else:
                self._stage_generation(lock, generation_digest, records)
        except MemoryStoreError as exc:
            return self._outcome(PublishStatus.FAILED, exc.code, generation_digest, manifest.manifest_digest)
        return self._publish_pointer(lock, generation_digest, manifest.manifest_digest, reused=present)

    def record_attempt(self, lock: WriterLock, attempt: AttemptRecord) -> str:
        """不完全な計画の証拠を `attempts/<attempt digest>.json` に 1 度だけ置く（同じ byte は再記録しない ・違う byte は上書きしない）。"""
        if not isinstance(attempt, AttemptRecord):
            raise MemoryStoreError(STORE_INPUT_INVALID, "ATTEMPT")
        self.check_writable(lock)
        data = attempt.to_bytes()
        final = self._memory(ATTEMPTS_DIRECTORY, attempt.attempt_digest + RECORD_SUFFIX)
        existing = _read_optional(final, MAX_SMALL_RECORD_BYTES)
        if existing is not None:
            if existing == data:
                return ATTEMPT_ALREADY_RECORDED
            raise MemoryStoreError(ATTEMPT_CONFLICT)
        temporary = self._memory(STAGING_DIRECTORY, "attempt." + attempt.attempt_digest + TEMP_SUFFIX)
        try:
            _create_file(temporary, data)
        except OSError:
            raise MemoryStoreError(STORE_IO_FAILED, "ATTEMPT_WRITE") from None
        if _read_optional(temporary, MAX_SMALL_RECORD_BYTES) != data:
            raise MemoryStoreError(STAGING_VERIFICATION_FAILED, "ATTEMPT")
        self._require_lock(lock)
        self._verify_root()
        if _lstat_or_none(final) is not None:
            raise MemoryStoreError(ATTEMPT_CONFLICT, "APPEARED")
        try:
            os.rename(temporary, final)
        except OSError:
            raise MemoryStoreError(STORE_IO_FAILED, "ATTEMPT_RENAME") from None
        _fsync_directory(self._memory(ATTEMPTS_DIRECTORY))
        _fsync_directory(self._memory(STAGING_DIRECTORY))
        if _read_optional(final, MAX_SMALL_RECORD_BYTES) != data:
            raise MemoryStoreError(STAGING_VERIFICATION_FAILED, "ATTEMPT_READ_BACK")
        return ATTEMPT_RECORDED

    def _preserve(self, source: str, name: str) -> str:
        """1 つの entry を `interrupted/<name>.<NNN>.interrupted` に移す（空いた番号だけ ・消さない ・既存の entry を置き換えない）。
        移した後に同じ file の identity が移った先に在ることを確かめる（確かめられなければ PRESERVATION_UNVERIFIED ・何も戻さない）。"""
        before = _lstat_or_none(source)
        if before is None or not (_plain_file(before) or _plain_directory(before)):
            raise MemoryStoreError(UNSAFE_ENTRY, "PRESERVE_SOURCE")
        directory = _plain_directory(before)
        for slot in range(1, MAX_INTERRUPTED_SLOTS + 1):
            preserved = f"{name}.{slot:03d}{INTERRUPTED_SUFFIX}"
            target = self._memory(INTERRUPTED_DIRECTORY, preserved)
            if _lstat_or_none(target) is not None:
                continue
            try:
                _move_without_replacing(source, target, directory=directory)
            except FileExistsError:
                continue                                                                   # 番号が埋まった: 次の番号（置き換えない）
            except OSError:
                raise MemoryStoreError(STORE_IO_FAILED, "PRESERVE_MOVE") from None
            _fsync_directory(self._memory(INTERRUPTED_DIRECTORY))
            _fsync_directory(os.path.dirname(source))
            after = _lstat_or_none(target)
            if after is None or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or _lstat_or_none(source) is not None:
                raise MemoryStoreError(PRESERVATION_UNVERIFIED)
            return preserved
        raise MemoryStoreError(INTERRUPTED_SLOTS_EXHAUSTED)


# ---------------------------------------------------------------- 明示の入口（初期化 ・開く ・読む ・人の回復）


def open_memory_store(root: Any, *, protected_roots: Mapping[str, Any]) -> MemoryStore:
    """初期化済みの memory root を開く（作らない）。root の形 ・祖先 ・同期 ／ git ／ vault の目印 ・重なり ・目印 ・layout を検査する。"""
    text = _root_text(root)
    protected = _protected(protected_roots)
    _check_disjoint(text, protected)
    _check_markers(text)
    st = _check_ancestors(text, absent_code=MEMORY_ROOT_MISSING, root_may_be_absent=False)
    if not st.st_ino:
        raise MemoryStoreError(ROOT_UNSAFE_COMPONENT, "IDENTITY_UNAVAILABLE")             # identity を検証できない file system は拒む
    store = MemoryStore(text, (st.st_dev, st.st_ino), protected, _SENTINEL)
    store._verify_root()
    return store


def initialize_memory_root(root: Any, *, protected_roots: Mapping[str, Any]) -> MemoryStore:
    """明示の初期化だけ: 空の directory（または親が在る未作成の名前）に目印と固定の layout を作る。既存 ・空でない root は拒む。"""
    text = _root_text(root)
    protected = _protected(protected_roots)
    _check_disjoint(text, protected)
    _check_markers(text)
    st = _check_ancestors(text, absent_code=ROOT_PARENT_MISSING, root_may_be_absent=True)
    if st is None:
        try:
            os.mkdir(text, DIRECTORY_MODE)
        except FileExistsError:
            raise MemoryStoreError(ROOT_NOT_EMPTY, "APPEARED") from None
        except OSError:
            raise MemoryStoreError(STORE_IO_FAILED, "ROOT_CREATE") from None
        _fsync_directory(os.path.dirname(text))
    else:
        existing = _entries(text)
        if MARKER_NAME in existing:
            raise MemoryStoreError(ROOT_ALREADY_INITIALIZED)
        if existing:
            raise MemoryStoreError(ROOT_NOT_EMPTY)
    _check_ancestors(text, absent_code=MEMORY_ROOT_MISSING, root_may_be_absent=False)
    try:
        _create_file(os.path.join(text, MARKER_NAME), marker_bytes())
    except FileExistsError:
        raise MemoryStoreError(ROOT_ALREADY_INITIALIZED, "APPEARED") from None
    except OSError:
        raise MemoryStoreError(STORE_IO_FAILED, "MARKER_CREATE") from None
    try:
        os.mkdir(os.path.join(text, MEMORY_DIRECTORY), DIRECTORY_MODE)
        for name in LAYOUT_DIRECTORIES:
            os.mkdir(os.path.join(text, MEMORY_DIRECTORY, name), DIRECTORY_MODE)
    except OSError:
        raise MemoryStoreError(STORE_IO_FAILED, "LAYOUT_CREATE") from None                 # 途中の layout は残す（LAYOUT_INVALID で開けない）
    _fsync_directory(os.path.join(text, MEMORY_DIRECTORY))
    _fsync_directory(text)
    return open_memory_store(text, protected_roots=protected_roots)


def read_memory(root: Any, *, protected_roots: Mapping[str, Any]) -> ReadResult:
    """root を開いて公開の pointer を厳密に読む。root の不在は MISSING（呼び出し側の root の誤りは例外のまま）。"""
    try:
        store = open_memory_store(root, protected_roots=protected_roots)
    except MemoryStoreError as exc:
        if exc.code in REFUSAL_CODES:
            raise
        return ReadResult(status=_read_status(exc.code), code=exc.code)
    return store.read_publication()


def preserve_interrupted_staging(store: MemoryStore) -> PreservationResult:
    """人の明示の回復: writer lock の下で、staging の全ての entry を `interrupted/` に移す（自動では呼ばれない ・何も消さない ・既存の
    entry を置き換えない）。lock が既に在れば WRITER_LOCK_PRESENT で拒む（lock を動かさない）。"""
    if not isinstance(store, MemoryStore):
        raise MemoryStoreError(STORE_INPUT_INVALID, "STORE")
    lock = store.acquire_writer_lock(operation="PRESERVE", plan=None)
    preserved = []
    try:
        store._require_lock(lock)
        store._verify_root()
        for name in _entries(store._memory(STAGING_DIRECTORY)):
            preserved.append(store._preserve(store._memory(STAGING_DIRECTORY, name), name))
    finally:
        release = lock.release()
    return PreservationResult(code=PRESERVED if preserved else NOTHING_TO_PRESERVE, preserved=tuple(preserved), lock_release=release)


def preserve_publication_pointer(store: MemoryStore) -> PreservationResult:
    """人の明示の回復: 形が壊れた ／ 未知の版の pointer、または参照先が確定的に不整合（不在 ・manifest の不一致 ・純粋な検証の失敗）な pointer
    だけを `interrupted/` に移す（修復 ・再公開 ・削除はしない ・既存の entry を置き換えない ・generation は触らない）。検証できる pointer は
    移さない（POINTER_VERIFIED_NOT_PRESERVED）・pointer が無ければ NOTHING_TO_PRESERVE ・root ／ layout ／ I/O の失敗などの曖昧な状態は
    PUBLICATION_STATE_UNCERTAIN（何も移さない ・fail closed）。lock が既に在れば WRITER_LOCK_PRESENT で拒む。"""
    if not isinstance(store, MemoryStore):
        raise MemoryStoreError(STORE_INPUT_INVALID, "STORE")
    lock = store.acquire_writer_lock(operation="PRESERVE", plan=None)
    preserved = []
    try:
        store._require_lock(lock)
        layer, _ = store._publication_state()
        if layer in (_POINTER, _REFERENCE):
            preserved.append(store._preserve(store._memory(PUBLICATION_NAME), PUBLICATION_NAME))
            code = PRESERVED
        else:
            code = {_VERIFIED: POINTER_VERIFIED_NOT_PRESERVED, _ABSENT: NOTHING_TO_PRESERVE}.get(layer, PUBLICATION_STATE_UNCERTAIN)
    finally:
        release = lock.release()
    return PreservationResult(code=code, preserved=tuple(preserved), lock_release=release)


__all__ = ["ATTEMPTS_DIRECTORY", "ATTEMPT_ALREADY_RECORDED", "ATTEMPT_CONFLICT", "ATTEMPT_RECORDED", "CODE_REPOSITORY_LABEL",
           "DIRECTORY_MODE", "FILE_MODE", "GENERATIONS_DIRECTORY", "GENERATION_ABSENT", "GENERATION_CONFLICT", "GENERATION_VERIFIED",
           "INTERRUPTED_DIRECTORY", "INTERRUPTED_SLOTS_EXHAUSTED", "INTERRUPTED_SUFFIX", "LAYOUT_DIRECTORIES", "LAYOUT_INVALID",
           "LOCKS_DIRECTORY", "LOCK_NOT_ACQUIRED", "LOCK_OWNERSHIP_UNVERIFIED", "LOCK_RELEASED", "LOCK_RELEASE_FAILED", "MARKER_INVALID", "MARKER_NAME",
           "MEMORY_DIRECTORY", "MEMORY_NOT_PUBLISHED", "MEMORY_ROOT_MISSING", "MemoryStore", "MemoryStoreError", "NOTHING_TO_PRESERVE",
           "PARTIAL_SUFFIX", "POINTER_PUBLICATION_FAILED", "POINTER_VERIFICATION_FAILED", "POINTER_VERIFIED_NOT_PRESERVED",
           "PRESERVATION_UNVERIFIED", "PRESERVED", "PROTECTED_ROOT_INVALID", "PUBLICATION_NAME", "PUBLICATION_STATE_UNCERTAIN",
           "PUBLICATION_NOT_VERIFIED", "PUBLICATION_POINTER_INCONSISTENT", "PUBLICATION_VERIFICATION_FAILED", "PUBLICATION_VERIFIED",
           "PreservationResult", "PublishOutcome", "PublishStatus", "RECORD_TOO_LARGE", "REFUSAL_CODES", "ROOT_ALREADY_INITIALIZED",
           "ROOT_IDENTITY_MISMATCH", "ROOT_INSIDE_VAULT", "ROOT_INSIDE_WORKING_TREE", "ROOT_INVALID", "ROOT_NOT_EMPTY", "ROOT_OVERLAP",
           "ROOT_PARENT_MISSING", "ROOT_SYNC_FOLDER", "ROOT_UNSAFE_COMPONENT", "ReadResult", "ReadStatus", "STAGING_DIRECTORY",
           "STAGING_PRESENT", "STAGING_VERIFICATION_FAILED", "STORE_INPUT_INVALID", "STORE_IO_FAILED", "SYNC_FOLDER_NAMES",
           "SYNC_FOLDER_PREFIXES", "SYNC_MARKER_NAMES", "TEMP_SUFFIX", "UNSAFE_ENTRY", "VAULT_MARKERS", "WORKING_TREE_MARKERS",
           "WRITER_LOCK_NAME", "WRITER_LOCK_PRESENT", "WriterLock", "initialize_memory_root", "open_memory_store",
           "preserve_interrupted_staging", "preserve_publication_pointer", "read_memory"]
