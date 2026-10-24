"""P9-A3 — Phase 9 の authority の追記専用 JSONL の仕組み（唯一の書き込みの module）と、検査済みの read-only の像の基底。

- 場所: `<P9 の private root>/watchlist_thesis_intelligence/<file>`（A1 の規約 ・利用者の機械の path は無い）。root は既存の
  directory（絶対）。`initialize` は無い file だけを空で作る（上書きしない）。
- 読み込み（fail closed ・修復 ・切り詰め ・skip しない）: encoding ・最後の改行（切断）・空行 ・JSON ・正準の行 ・物理的な重複 ・
  model の復元 ・`revision_id` ・鎖 ・file 固有の不変条件。
- 書き込み: 直前に file の byte 長 ・sha256 が読み込み時と同じことを確かめ（外部の変更は `CONCURRENT_MODIFICATION`）、1 行を
  `open("ab")` → write → flush → fsync。後に byte 長を確かめる。削除 ・上書き ・修復 ・圧縮の API は無い。lock は持たない（本人の
  local な単一の書き手。同時の書き手は検出して fail closed）。
- 公開の追記の API は無い（追記は `authority_stores.AuthorityStores` だけが、記録をまたぐ不変条件を検査した後に呼ぶ）。

記録: `docs/databank/PHASE9_A3_AUTHORITY_STORES.md`。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .private_root import PrivateRootError, phase9_authority_dir
from .revision_model import SemanticModelError, canonical_json, check_instant, state_at

STORE_SCHEMA_VERSION = "p9_authority_store:0.1.0"


class StoreFailureCategory(str, Enum):
    STORE_MISSING = "STORE_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    APPEND_REJECTED = "APPEND_REJECTED"


class AuthorityStoreError(RuntimeError):
    def __init__(self, category: StoreFailureCategory, code: str, detail: str = "", *, line_number: int = 0) -> None:
        super().__init__(f"{category.value}:{code}: {detail}" if detail else f"{category.value}:{code}")
        self.category = category
        self.code = code
        self.detail = detail
        self.line_number = line_number


def _fail(category: StoreFailureCategory, code: str, detail: str = "", line: int = 0) -> AuthorityStoreError:
    return AuthorityStoreError(category, code, detail, line_number=line)


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"


@dataclass(frozen=True)
class AppendResult:
    revision_id: str
    status: AppendStatus


def store_path(p9_root: Any, filename: str) -> Path:
    """`<p9_root>/watchlist_thesis_intelligence/<filename>`。root は絶対 ・既存の directory（作らない）。"""
    try:
        directory = phase9_authority_dir(p9_root)
    except PrivateRootError as exc:
        raise _fail(StoreFailureCategory.STORE_MISSING, exc.code, "p9_root") from None
    if not directory.parent.is_dir():
        raise _fail(StoreFailureCategory.STORE_MISSING, "P9_ROOT_MISSING", "p9_root")
    return directory / filename


def initialize_file(path: Path) -> None:
    """無い file だけを空で作る（既存の file には触れない）。"""
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        with path.open("ab"):
            pass


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RevisionStore:
    """1 つの JSONL の authority の検査済みの read-only の像（正確な選択 ・時点の状態だけ。最新 ／ 現在の API は無い）。"""

    FILENAME = ""
    _parse: Callable[[Any], Any] = staticmethod(lambda data: data)
    _validate_chain: Callable[[Any], Tuple[Any, ...]] = staticmethod(lambda revisions: tuple(revisions))
    _line: Callable[[Any], str] = staticmethod(lambda revision: "")

    def __init__(self, p9_root: Any) -> None:
        self.path = store_path(p9_root, self.FILENAME)
        self._size = -1
        self._digest = ""
        self._lines: Dict[str, str] = {}
        self._revisions: Dict[str, Any] = {}
        self._chains: Dict[str, Tuple[Any, ...]] = {}
        self._load()

    @classmethod
    def initialize(cls, p9_root: Any) -> "RevisionStore":
        initialize_file(store_path(p9_root, cls.FILENAME))
        return cls(p9_root)

    @classmethod
    def open(cls, p9_root: Any) -> "RevisionStore":
        return cls(p9_root)

    # ------------------------------------------------------------ 読み込み（fail closed）

    def _load(self) -> None:
        if not self.path.is_file():
            raise _fail(StoreFailureCategory.STORE_MISSING, "STORE_MISSING", self.FILENAME)
        data = self.path.read_bytes()
        corrupt = StoreFailureCategory.STORE_CORRUPTION
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise _fail(corrupt, "INVALID_ENCODING", self.FILENAME) from None
        if text and not text.endswith("\n"):
            raise _fail(corrupt, "TRUNCATED_FINAL_LINE", self.FILENAME, text.count("\n") + 1)
        lines: Dict[str, str] = {}
        revisions: Dict[str, Any] = {}
        for number, line in enumerate(text.split("\n")[:-1] if text else (), 1):
            if line == "":
                raise _fail(corrupt, "BLANK_LINE", self.FILENAME, number)
            try:
                record = json.loads(line)
            except ValueError:
                raise _fail(corrupt, "MALFORMED_JSON", self.FILENAME, number) from None
            if not isinstance(record, dict) or canonical_json(record) != line:
                raise _fail(corrupt, "NON_CANONICAL_LINE", self.FILENAME, number)
            try:
                revision = type(self)._parse(record)
            except SemanticModelError as exc:
                raise _fail(corrupt, f"INVALID_RECORD:{exc.code}", exc.detail, number) from None
            if revision.revision_id in lines:
                raise _fail(corrupt, "DUPLICATE_REVISION", revision.revision_id, number)   # 物理的な重複も拒む
            lines[revision.revision_id] = line
            revisions[revision.revision_id] = revision
        chains: Dict[str, Tuple[Any, ...]] = {}
        for root in sorted({r.root_id for r in revisions.values()}):
            try:
                chains[root] = type(self)._validate_chain([r for r in revisions.values() if r.root_id == root])
            except SemanticModelError as exc:
                raise _fail(corrupt, f"CHAIN_INVALID:{exc.code}", root) from None
        self._check_store_invariants(chains)
        self._size, self._digest = len(data), _digest(data)
        self._lines, self._revisions, self._chains = lines, revisions, chains

    def _check_store_invariants(self, chains: Mapping[str, Tuple[Any, ...]]) -> None:
        """file 固有の不変条件（subclass）。"""

    def verify_unchanged(self) -> None:
        data = self.path.read_bytes() if self.path.is_file() else b""
        if not self.path.is_file() or len(data) != self._size or _digest(data) != self._digest:
            raise _fail(StoreFailureCategory.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", self.FILENAME)

    def _append_line(self, line: str) -> None:
        """1 行の追記（`AuthorityStores` だけが、不変条件の検査の後に呼ぶ）。write → flush → fsync ・前後の長さの検査。"""
        self.verify_unchanged()
        encoded = (line + "\n").encode("utf-8")
        with self.path.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if self.path.stat().st_size != self._size + len(encoded):
            raise _fail(StoreFailureCategory.CONCURRENT_MODIFICATION, "STORE_CHANGED_DURING_APPEND", self.FILENAME)
        self._load()                                                             # 全体を再検査（fail closed）

    # ------------------------------------------------------------ 正確な選択 ・時点の状態（暗黙の最新 ／ 現在は無い）

    def roots(self) -> Tuple[str, ...]:
        return tuple(sorted(self._chains))

    def chain(self, root_id: str) -> Tuple[Any, ...]:
        if root_id not in self._chains:
            raise _fail(StoreFailureCategory.STORE_MISSING, "ROOT_NOT_FOUND", root_id)
        return self._chains[root_id]

    def revision(self, revision_id: str) -> Optional[Any]:
        return self._revisions.get(revision_id)

    def revision_at_seq(self, root_id: str, seq: int) -> Optional[Any]:
        return next((r for r in self.chain(root_id) if r.seq == seq), None)

    def state_at(self, root_id: str, at: datetime) -> Optional[Any]:
        """時点 T（明示 ・aware）の root の状態: `reviewed_at <= T` の最大の seq。"""
        return state_at(self.chain(root_id), check_instant(at, "at"))

    def states_at(self, at: datetime) -> Dict[str, Any]:
        instant = check_instant(at, "at")
        return {root: head for root, chain in self._chains.items() if (head := state_at(chain, instant))}

    def all_revisions(self) -> Tuple[Any, ...]:
        return tuple(r for root in self.roots() for r in self._chains[root])

    def line_for(self, revision_id: str) -> Optional[str]:
        return self._lines.get(revision_id)

    def line_of(self, revision: Any) -> str:
        return type(self)._line(revision)


__all__ = ["AppendResult", "AppendStatus", "AuthorityStoreError", "RevisionStore", "STORE_SCHEMA_VERSION",
           "StoreFailureCategory", "initialize_file", "store_path"]
