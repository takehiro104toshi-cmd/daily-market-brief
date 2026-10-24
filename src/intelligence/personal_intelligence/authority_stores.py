"""P10-A3 — Personal Profile ＋ Attention の authority の唯一の追記の経路（全世界の検査の後だけ 1 行を書く）。

`PersonalAuthorityStores.open(p10_root)`: 両方の store を読み込み（各 store の全検査 ・何も作らない）、A2 の `check_personal_world` を
全ての鎖で検査する（違えば `STORE_CORRUPTION`）。`initialize(p10_root)` は明示の初期化（root は既存 ・無い directory ／ file だけを作る）
の後に開く。

追記（`append_profile_revision` ／ `append_attention_revision`。型を限った 2 つだけ ・汎用の追記は無い）の流れ:
1. 両方の store を読み込み時の byte（長さ ・sha256）と比べ、同じ byte を全て検査し直す（外部の変更は `CONCURRENT_MODIFICATION`）。
2. 同じ `revision_id` が既に在れば: 正準の行が同じなら `REUSED`（書かない）・違えば `REVISION_CONFLICT`。
3. 鎖の先頭: 新しい root は seq 1 の CREATE ・既存の root は先頭の seq ＋1 で `prev_revision_id` が先頭の revision（古い先頭への追記は
   `CHAIN_HEAD_MISMATCH` ・新しい先頭の上に黙って載せない）。
4. 提案の世界（両方の既存の全 revision ＋ 候補）で A2 の `check_personal_world`。違えば `APPEND_REJECTED`。
5. 両方の byte を直前に確かめ、対象の store にだけ 1 行を追記（他方は書かない ・連鎖の書き込みなし）→ 全体を再検査。

P9 の root ／ revision の実在の検査 ・人の入力の実行器 ・人向けの古い先頭の意味は A4。

記録: `docs/databank/PHASE10_A3_PROFILE_ATTENTION_STORES.md`。
"""
from __future__ import annotations

from typing import Any, Tuple

from .attention_model import AttentionRevision
from .attention_store import AttentionStore
from .cross_rules import check_personal_world
from .profile_model import PersonalProfileRevision
from .profile_store import ProfileStore
from .revision_model import ChangeKind, PersonalModelError
from .store_io import (AppendResult, AppendStatus, AuthorityFile, PersonalStoreError, StoreFailureCategory,
                       _append_line, _initialize_files, fail)


def _rejected(code: str, detail: str = "") -> PersonalStoreError:
    return fail(StoreFailureCategory.APPEND_REJECTED, code, detail)


class PersonalAuthorityStores:
    """両方の store の検査済みの read-only の像 ＋ 唯一の追記の経路。最新 ／ 現在の API は無い。"""

    def __init__(self, profile: ProfileStore, attention: AttentionStore) -> None:
        if not isinstance(profile, ProfileStore) or not isinstance(attention, AttentionStore):
            raise _rejected("INVALID_STORE", "stores")
        if not profile.same_directory(attention):
            raise fail(StoreFailureCategory.ROOT_REJECTED, "STORES_NOT_IN_ONE_ROOT", "stores")
        self._profile = profile
        self._attention = attention
        self._check_world(profile.all_revisions(), attention.all_revisions(), StoreFailureCategory.STORE_CORRUPTION)

    @property
    def profile(self) -> ProfileStore:
        return self._profile

    @property
    def attention(self) -> AttentionStore:
        return self._attention

    @classmethod
    def initialize(cls, p10_root: Any) -> "PersonalAuthorityStores":
        """明示の初期化（root は既存であること ・無い `personal_intelligence/` と無い file だけを作る）→ 開く。"""
        _initialize_files(p10_root)
        return cls.open(p10_root)

    @classmethod
    def open(cls, p10_root: Any) -> "PersonalAuthorityStores":
        """既存の store を読むだけ（何も作らない）。"""
        return cls(ProfileStore.open(p10_root), AttentionStore.open(p10_root))

    @staticmethod
    def _check_world(profiles: Tuple[Any, ...], attention: Tuple[Any, ...], category: StoreFailureCategory) -> None:
        try:
            check_personal_world(list(profiles), list(attention))
        except PersonalModelError as exc:
            raise fail(category, f"WORLD_INVALID:{exc.code}") from None

    def append_profile_revision(self, revision: Any) -> AppendResult:
        if not isinstance(revision, PersonalProfileRevision):
            raise _rejected("INVALID_REVISION", "profile")
        return self._append(self._profile, revision, profile=True)

    def append_attention_revision(self, revision: Any) -> AppendResult:
        if not isinstance(revision, AttentionRevision):
            raise _rejected("INVALID_REVISION", "attention")
        return self._append(self._attention, revision, profile=False)

    def _append(self, store: AuthorityFile, revision: Any, *, profile: bool) -> AppendResult:
        self._profile.revalidate()                                               # 1. byte の一致 ＋ 全検査
        self._attention.revalidate()
        try:
            line = store.line_of(revision)
        except PersonalModelError as exc:
            raise _rejected(exc.code, store.KIND) from None
        existing = store.line_for(revision.revision_id)                          # 2. 冪等 ／ 衝突
        if existing is not None:
            if existing != line:
                raise _rejected("REVISION_CONFLICT", store.KIND)
            return AppendResult(revision.revision_id, AppendStatus.REUSED)
        if revision.root_id in store.roots():                                    # 3. 鎖の先頭
            head = store.chain(revision.root_id)[-1]
            if revision.seq != head.seq + 1 or revision.prev_revision_id != head.revision_id:
                raise _rejected("CHAIN_HEAD_MISMATCH", store.KIND)
        elif revision.seq != 1 or revision.change_kind is not ChangeKind.CREATE:
            raise _rejected("ROOT_NOT_FOUND", store.KIND)
        profiles = self._profile.all_revisions() + ((revision,) if profile else ())
        attention = self._attention.all_revisions() + (() if profile else (revision,))
        self._check_world(profiles, attention, StoreFailureCategory.APPEND_REJECTED)   # 4. 提案の世界
        (self._attention if profile else self._profile).verify_unchanged()       # 5. 他方の byte も直前に確かめる
        _append_line(store, line)                                                # 対象の store だけ（連鎖の書き込みなし）
        return AppendResult(revision.revision_id, AppendStatus.APPENDED)


__all__ = ["PersonalAuthorityStores"]
