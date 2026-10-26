"""P10-A3 — Phase 10 の authority の追記専用 JSONL の仕組み（唯一の物理的な書き込みの module）と、検査済みの read-only の像の基底。

- 場所: `<caller が明示に渡す P10 の root>/personal_intelligence/<file>`。root は既存の絶対の directory。`..` の部品 ・相対 ・空 ・NUL ・
  symlink（root ・authority の directory ・file）は拒む。他の root（P8 ・P9）を探さない ・推測しない ・触れない。
- 初期化と開くことは別: `_initialize_files`（coordinator の `initialize` だけが呼ぶ）は root が既に在ることを要し、無い
  `personal_intelligence/` と無い file だけを作る（file は排他の作成 ・既存の file には触れない）。開く（`AuthorityFile.open`）は何も
  作らない（無ければ fail closed）。
- 読み込み（fail closed ・修復 ・切り詰め ・skip ・正規化なし）: UTF-8 ・最後の LF ・空行 ・JSON ・正準の行 ・物理的な重複 ・A2 の型の
  復元 ・`revision_id` の再計算 ・鎖 ・A2 の `check_personal_world`。読んだ同じ byte から byte 長 ・sha256 を記録する。
- 書き込み: module の私的な `_append_line` だけ（coordinator だけが import する）。直前に byte 長 ・sha256 を確かめ（外部の変更は
  `CONCURRENT_MODIFICATION`）、binary の追記 → flush → fsync → 長さの確認 → 全体の再読み込み。上書き ・切り詰め ・削除 ・修復の API は
  無い。lock は持たない（本人の local な単一の書き手の楽観的な並行性。同時の書き手は検出して fail closed）。
- 例外の文は安全な code ・file の種類 ・行の番号だけ（path ・id ・文 ・記録の内容は入れない）。

記録: `docs/databank/PHASE10_A3_PROFILE_ATTENTION_STORES.md`。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from .revision_model import PersonalModelError, canonical_json, revision_at_seq, state_at, states_at

STORE_SCHEMA_VERSION = "p10_authority_store:0.1.0"
PERSONAL_DIRNAME = "personal_intelligence"
PROFILE_FILENAME = "profile_authority.jsonl"
ATTENTION_FILENAME = "attention_authority.jsonl"
AUTHORITY_FILENAMES = (PROFILE_FILENAME, ATTENTION_FILENAME)


class StoreFailureCategory(str, Enum):
    ROOT_REJECTED = "ROOT_REJECTED"
    STORE_MISSING = "STORE_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    APPEND_REJECTED = "APPEND_REJECTED"
    NOT_FOUND = "NOT_FOUND"


class PersonalStoreError(RuntimeError):
    """store の失敗（fail closed）。文は安全な code ・file の種類 ・行の番号だけ。"""

    def __init__(self, category: StoreFailureCategory, code: str, detail: str = "", *, line_number: int = 0) -> None:
        text = f"{category.value}:{code}" + (f": {detail}" if detail else "") + (f" @{line_number}" if line_number else "")
        super().__init__(text)
        self.category = category
        self.code = code
        self.detail = detail
        self.line_number = line_number


def fail(category: StoreFailureCategory, code: str, detail: str = "", line: int = 0) -> PersonalStoreError:
    return PersonalStoreError(category, code, detail, line_number=line)


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"


@dataclass(frozen=True)
class AppendResult:
    revision_id: str
    status: AppendStatus


# ---------------------------------------------------------------- root の安全（明示の root だけ）


def _explicit_root(p10_root: Any) -> Path:
    """明示の絶対 path（`..` ・相対 ・空 ・NUL は拒む ・正規化で救わない）。filesystem の検査は `_existing_root`。"""
    if not isinstance(p10_root, (str, Path)) or str(p10_root).strip() == "" or "\x00" in str(p10_root):
        raise fail(StoreFailureCategory.ROOT_REJECTED, "ROOT_REQUIRED", "p10_root")
    path = Path(p10_root)
    if not path.is_absolute():
        raise fail(StoreFailureCategory.ROOT_REJECTED, "ROOT_NOT_ABSOLUTE", "p10_root")
    if ".." in path.parts:
        raise fail(StoreFailureCategory.ROOT_REJECTED, "ROOT_TRAVERSAL", "p10_root")
    return path


def _existing_root(p10_root: Any) -> Path:
    root = _explicit_root(p10_root)
    if root.is_symlink():
        raise fail(StoreFailureCategory.ROOT_REJECTED, "ROOT_IS_SYMLINK", "p10_root")
    if not root.is_dir():
        raise fail(StoreFailureCategory.STORE_MISSING, "P10_ROOT_MISSING", "p10_root")
    return root


def _authority_dir(root: Path, *, required: bool) -> Path:
    directory = root / PERSONAL_DIRNAME
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise fail(StoreFailureCategory.ROOT_REJECTED, "AUTHORITY_DIR_UNSAFE", PERSONAL_DIRNAME)
    if required and not directory.is_dir():
        raise fail(StoreFailureCategory.STORE_MISSING, "AUTHORITY_DIR_MISSING", PERSONAL_DIRNAME)
    return directory


def _regular_file(path: Path, kind: str) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise fail(StoreFailureCategory.ROOT_REJECTED, "AUTHORITY_FILE_UNSAFE", kind)
    if not path.is_file():
        raise fail(StoreFailureCategory.STORE_MISSING, "STORE_MISSING", kind)


def _initialize_files(p10_root: Any) -> None:
    """明示の初期化（coordinator の `initialize` だけ）。root は既に在ること。無い directory ・無い file だけを作る（既存は触れない）。"""
    directory = _authority_dir(_existing_root(p10_root), required=False)
    if not directory.exists():
        directory.mkdir()
    for filename in AUTHORITY_FILENAMES:
        path = directory / filename
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise fail(StoreFailureCategory.ROOT_REJECTED, "AUTHORITY_FILE_UNSAFE", filename)
        if not path.exists():
            with path.open("xb"):                                                # 排他の作成（切り詰めない）
                pass


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- 検査済みの read-only の像


class AuthorityFile:
    """1 つの JSONL の authority の検査済みの read-only の像（正確な選択 ・時点の状態だけ。最新 ／ 現在 ・追記の API は無い）。"""

    FILENAME = ""
    KIND = ""
    _parse: Callable[[Any], Any] = staticmethod(lambda record: record)
    _chains_of: Callable[[Sequence[Any]], Dict[str, Tuple[Any, ...]]] = staticmethod(lambda revisions: {})
    _line: Callable[[Any], str] = staticmethod(lambda revision: "")

    def __init__(self, p10_root: Any) -> None:
        self._directory = _authority_dir(_existing_root(p10_root), required=True)
        self._path = self._directory / self.FILENAME
        self._size = -1
        self._digest = ""
        self._lines: Dict[str, str] = {}
        self._revisions: Dict[str, Any] = {}
        self._chains: Dict[str, Tuple[Any, ...]] = {}
        self._load(self._read())

    @classmethod
    def open(cls, p10_root: Any) -> "AuthorityFile":
        """既存の file を読むだけ（何も作らない ・無い ／ 壊れていれば fail closed）。"""
        return cls(p10_root)

    def _read(self) -> bytes:
        _regular_file(self._path, self.KIND)
        return self._path.read_bytes()

    def _load(self, data: bytes) -> None:
        corrupt = StoreFailureCategory.STORE_CORRUPTION
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise fail(corrupt, "INVALID_ENCODING", self.KIND) from None
        if text and not text.endswith("\n"):
            raise fail(corrupt, "MISSING_FINAL_NEWLINE", self.KIND, text.count("\n") + 1)
        lines: Dict[str, str] = {}
        revisions: Dict[str, Any] = {}
        for number, line in enumerate(text.split("\n")[:-1] if text else (), 1):
            if line == "":
                raise fail(corrupt, "BLANK_LINE", self.KIND, number)
            try:
                record = json.loads(line)
            except ValueError:
                raise fail(corrupt, "MALFORMED_JSON", self.KIND, number) from None
            if not isinstance(record, dict) or canonical_json(record) != line:
                raise fail(corrupt, "NON_CANONICAL_LINE", self.KIND, number)
            try:
                revision = type(self)._parse(record)
            except PersonalModelError as exc:
                raise fail(corrupt, f"INVALID_RECORD:{exc.code}", self.KIND, number) from None
            if revision.revision_id in lines:
                raise fail(corrupt, "DUPLICATE_REVISION", self.KIND, number)        # 物理的な重複も拒む
            lines[revision.revision_id] = line
            revisions[revision.revision_id] = revision
        try:
            chains = type(self)._chains_of(tuple(revisions.values()))             # 鎖 ＋ A2 の世界の規則
        except PersonalModelError as exc:
            raise fail(corrupt, f"INVALID_AUTHORITY:{exc.code}", self.KIND) from None
        self._size, self._digest = len(data), _digest(data)
        self._lines, self._revisions, self._chains = lines, revisions, chains

    def _unchanged_bytes(self) -> bytes:
        """読み込み時と同じ byte 長 ・sha256 の byte（消えた ・置き換わった ・変わった file は `CONCURRENT_MODIFICATION`）。"""
        try:
            data = self._read()
        except PersonalStoreError:
            raise fail(StoreFailureCategory.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", self.KIND) from None
        if len(data) != self._size or _digest(data) != self._digest:
            raise fail(StoreFailureCategory.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", self.KIND)
        return data

    def verify_unchanged(self) -> None:
        self._unchanged_bytes()

    def revalidate(self) -> None:
        """byte が読み込み時と同じことを確かめ、同じ byte を全て検査し直す（fail closed）。"""
        self._load(self._unchanged_bytes())

    def same_directory(self, other: "AuthorityFile") -> bool:
        return self._directory == other._directory

    # ------------------------------------------------------------ 正確な選択 ・時点の状態（暗黙の最新 ／ 現在は無い）

    def roots(self) -> Tuple[str, ...]:
        return tuple(sorted(self._chains))

    def chain(self, root_id: str) -> Tuple[Any, ...]:
        if root_id not in self._chains:
            raise fail(StoreFailureCategory.NOT_FOUND, "ROOT_NOT_FOUND", self.KIND)
        return self._chains[root_id]

    def revision(self, revision_id: str) -> Optional[Any]:
        return self._revisions.get(revision_id)

    def revision_at_seq(self, root_id: str, seq: int) -> Any:
        try:
            return revision_at_seq(self.chain(root_id), seq)
        except PersonalModelError as exc:
            raise fail(StoreFailureCategory.NOT_FOUND, exc.code, self.KIND) from None

    def state_at(self, root_id: str, at: datetime) -> Optional[Any]:
        """時点 T（明示 ・aware）の root の状態: `reviewed_at <= T` の最大の seq（物理の順は使わない）。"""
        return state_at(self.chain(root_id), at)

    def states_at(self, at: datetime) -> Dict[str, Any]:
        return states_at(self._chains, at)

    def all_revisions(self) -> Tuple[Any, ...]:
        return tuple(r for root in self.roots() for r in self._chains[root])

    def line_for(self, revision_id: str) -> Optional[str]:
        return self._lines.get(revision_id)

    def line_of(self, revision: Any) -> str:
        return type(self)._line(revision)


def _append_line(store: AuthorityFile, line: str) -> None:
    """唯一の物理的な追記（coordinator だけが、全ての検査の後に呼ぶ）。binary ・LF ・flush ・fsync ・前後の長さの検査 ・再読み込み。"""
    if not isinstance(line, str) or line == "" or "\n" in line or "\r" in line:
        raise fail(StoreFailureCategory.APPEND_REJECTED, "INVALID_LINE", store.KIND)
    store.verify_unchanged()
    encoded = (line + "\n").encode("utf-8")
    with store._path.open("ab") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    if store._path.stat().st_size != store._size + len(encoded):
        raise fail(StoreFailureCategory.CONCURRENT_MODIFICATION, "STORE_CHANGED_DURING_APPEND", store.KIND)
    store._load(store._read())                                                   # 全体を再検査（fail closed）


__all__ = ["ATTENTION_FILENAME", "AUTHORITY_FILENAMES", "AppendResult", "AppendStatus", "AuthorityFile",
           "PERSONAL_DIRNAME", "PROFILE_FILENAME", "PersonalStoreError", "STORE_SCHEMA_VERSION",
           "StoreFailureCategory", "fail"]
