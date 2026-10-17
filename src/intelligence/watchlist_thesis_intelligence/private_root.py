"""P9-A1 — Phase 9 の private root の規約（定義だけ。A1 では使わない ・何も作らない）。

Phase 9 の authority は caller が明示に渡す private root の `<root>/watchlist_thesis_intelligence/` に置く（後の gate）。Phase 8 の
root と Phase 9 の root は構造的に分ける: 同じ path ・一方が他方の中にある組は拒む（P9 が P8 の store に書く経路を作らない）。
既定の path ・利用者の機械の path ・時計 ・filesystem への書き込みは無い。
"""
from __future__ import annotations

import os.path
from pathlib import Path
from typing import Any

PHASE9_DIRNAME = "watchlist_thesis_intelligence"
PRIVATE_ROOT_RULES_VERSION = "p9_private_root:0.1.0"


class PrivateRootError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _explicit(value: Any, field_name: str) -> Path:
    if not isinstance(value, (str, Path)) or str(value).strip() == "":
        raise PrivateRootError("ROOT_REQUIRED", field_name)
    path = Path(value)
    if not path.is_absolute():
        raise PrivateRootError("ROOT_NOT_ABSOLUTE", field_name)
    return Path(os.path.normpath(str(path)))                                   # 文字の上で正規化（`..` を畳む）


def phase9_authority_dir(p9_root: Any) -> Path:
    """`<p9_root>/watchlist_thesis_intelligence`（path の計算だけ。存在の確認 ・作成はしない）。"""
    return _explicit(p9_root, "p9_root") / PHASE9_DIRNAME


def require_separate_roots(p8_root: Any, p9_root: Any) -> None:
    """P8 の root と P9 の root が同じ ・入れ子なら拒む（文字の上の path で比べる。filesystem には触れない）。"""
    p8, p9 = _explicit(p8_root, "p8_root"), _explicit(p9_root, "p9_root")
    if p8 == p9 or p8 in p9.parents or p9 in p8.parents:
        raise PrivateRootError("ROOTS_NOT_SEPARATE", "p8_root/p9_root")


__all__ = ["PHASE9_DIRNAME", "PRIVATE_ROOT_RULES_VERSION", "PrivateRootError", "phase9_authority_dir",
           "require_separate_roots"]
