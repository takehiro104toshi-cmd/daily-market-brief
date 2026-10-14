"""P9-A3 — Watchlist ＋ Thesis の authority の唯一の追記の経路（記録をまたぐ不変条件の検査の後だけ書く）。

`AuthorityStores.open(p9_root)`: 両方の store を読み込み（各 store の全検査）、A2 の `cross_rules.check_world` を全ての鎖で検査する
（違えば `STORE_CORRUPTION`）。

追記（`append_watch` ／ `append_thesis`）の流れ:
1. 両方の file が読み込み時と同じ（byte 長 ・sha256）ことを確かめる（外部の変更は `CONCURRENT_MODIFICATION`）。
2. 同じ `revision_id` が既に在れば: 正準の行が同じなら `REUSED`（書かない）・違えば `REVISION_CONFLICT`。
3. 鎖の先頭の検査: 新しい root は seq 1 の CREATE（root が既に在れば拒む）・既存の root は先頭の seq ＋1 で `prev_revision_id` が
   先頭の revision（古い先頭に繋ぐ追記は `CHAIN_HEAD_MISMATCH`）。
4. 提案の世界（既存の全 revision ＋ 候補）で A2 の鎖の検査 ＋ `check_world`（全ての審査の瞬間の像）。違えば `APPEND_REJECTED`。
5. 対象の store にだけ 1 行を追記（他方の store は書かない ・連鎖の書き込みは無い）→ 全体を再読み込みして再検査。

A1 の発行体の存在の検査はここでは行わない（store を P8 の root に結び付けない ・P8 を import しない）。A4 の実行器が人の入力を
作る前に行う（文書 §8）。

記録: `docs/databank/PHASE9_A3_AUTHORITY_STORES.md`。
"""
from __future__ import annotations

from typing import Any, Tuple

from .cross_rules import check_world
from .revision_model import ChangeKind, SemanticModelError
from .store_io import AppendResult, AppendStatus, AuthorityStoreError, StoreFailureCategory
from .thesis_model import ThesisRevision
from .thesis_store import ThesisStore
from .watch_model import WatchEntryRevision
from .watch_store import WatchlistStore


def _rejected(code: str, detail: str = "") -> AuthorityStoreError:
    return AuthorityStoreError(StoreFailureCategory.APPEND_REJECTED, code, detail)


class AuthorityStores:
    """両方の store の検査済みの像 ＋ 唯一の追記の経路。最新 ／ 現在の API は無い（store の正確な選択 ・時点の状態を使う）。"""

    def __init__(self, watch: WatchlistStore, thesis: ThesisStore) -> None:
        self.watch = watch
        self.thesis = thesis
        self._check_world(watch.all_revisions(), thesis.all_revisions(), StoreFailureCategory.STORE_CORRUPTION)

    @classmethod
    def initialize(cls, p9_root: Any) -> "AuthorityStores":
        return cls(WatchlistStore.initialize(p9_root), ThesisStore.initialize(p9_root))

    @classmethod
    def open(cls, p9_root: Any) -> "AuthorityStores":
        return cls(WatchlistStore.open(p9_root), ThesisStore.open(p9_root))

    @staticmethod
    def _check_world(watch: Tuple[Any, ...], thesis: Tuple[Any, ...], category: StoreFailureCategory) -> None:
        try:
            check_world(list(watch), list(thesis))
        except SemanticModelError as exc:
            raise AuthorityStoreError(category, f"WORLD_INVALID:{exc.code}", exc.detail) from None

    def append_watch(self, revision: Any) -> AppendResult:
        if not isinstance(revision, WatchEntryRevision):
            raise _rejected("INVALID_REVISION", "watch")
        return self._append(self.watch, revision, watch=True)

    def append_thesis(self, revision: Any) -> AppendResult:
        if not isinstance(revision, ThesisRevision):
            raise _rejected("INVALID_REVISION", "thesis")
        return self._append(self.thesis, revision, watch=False)

    def _append(self, store: Any, revision: Any, *, watch: bool) -> AppendResult:
        self.watch.verify_unchanged()
        self.thesis.verify_unchanged()
        line = store.line_of(revision)
        existing = store.line_for(revision.revision_id)
        if existing is not None:
            if existing != line:
                raise _rejected("REVISION_CONFLICT", revision.revision_id)
            return AppendResult(revision.revision_id, AppendStatus.REUSED)
        if revision.root_id in store.roots():
            head = store.chain(revision.root_id)[-1]                              # 鎖の構造上の先頭（seq の最大）
            if revision.seq != head.seq + 1 or revision.prev_revision_id != head.revision_id:
                raise _rejected("CHAIN_HEAD_MISMATCH", revision.root_id)
        elif revision.seq != 1 or revision.change_kind is not ChangeKind.CREATE:
            raise _rejected("ROOT_NOT_FOUND", revision.root_id)
        watch_revisions = self.watch.all_revisions() + ((revision,) if watch else ())
        thesis_revisions = self.thesis.all_revisions() + (() if watch else (revision,))
        self._check_world(watch_revisions, thesis_revisions, StoreFailureCategory.APPEND_REJECTED)
        store._append_line(line)                                                 # 対象の store だけ（連鎖の書き込みなし）
        return AppendResult(revision.revision_id, AppendStatus.APPENDED)


__all__ = ["AuthorityStores"]
