"""P10-A4 — 明示の管理の初期化（authority の適用とは別 ・実行器は呼ばない）。

`init_personal_root(p10_root)`（A3 の初期化の primitive より厳しい包み）:
- 両方の authority の file が無い → A3 の `initialize`（root は既存であること）→ `INITIALIZED`。
- 両方が在り、開ける（全検査）→ `ALREADY_INITIALIZED`（何も変えない）。
- 片方だけ在る → `PARTIAL_LAYOUT` で拒む（既存の authority の横に無い file を黙って作らない ・補修しない）。
- root の拒否 ・無い root ・破損は拒む（作らない ・修復しない）。

記録: `docs/databank/PHASE10_A4_EXECUTOR_REVIEW_VIEW.md`。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from .authority_stores import PersonalAuthorityStores
from .store_io import AUTHORITY_FILENAMES, PERSONAL_DIRNAME, PersonalStoreError, StoreFailureCategory


class InitStatus(str, Enum):
    INITIALIZED = "INITIALIZED"
    ALREADY_INITIALIZED = "ALREADY_INITIALIZED"


class InitRefusal(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def init_personal_root(p10_root: Any) -> InitStatus:
    try:
        PersonalAuthorityStores.open(p10_root)                                   # 両方が在り正しい
        return InitStatus.ALREADY_INITIALIZED
    except PersonalStoreError as exc:
        absent = exc.category is StoreFailureCategory.STORE_MISSING and exc.code in ("AUTHORITY_DIR_MISSING",
                                                                                      "STORE_MISSING")
        if not absent:
            raise InitRefusal("INIT_REFUSED", f"{exc.category.value}:{exc.code}") from None
    directory = Path(p10_root) / PERSONAL_DIRNAME                                 # root は open が検査済み
    present = [name for name in AUTHORITY_FILENAMES if (directory / name).exists() or (directory / name).is_symlink()]
    if present:
        raise InitRefusal("PARTIAL_LAYOUT")
    try:
        PersonalAuthorityStores.initialize(p10_root)
    except PersonalStoreError as exc:
        raise InitRefusal("INIT_REFUSED", f"{exc.category.value}:{exc.code}") from None
    return InitStatus.INITIALIZED


__all__ = ["InitRefusal", "InitStatus", "init_personal_root"]
