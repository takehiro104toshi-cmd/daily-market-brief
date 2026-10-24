"""凍結 pin の共通規則（test helper）。

B6 の凍結 pin は「B6 時点の runtime が変わっていない」ことを守る。P6-B7 以降に**新規追加**される LLM 提案層 module
（`src/intelligence/theme_intelligence/llm_<name>.py`、package 直下のみ）だけを対象外にする。

- 既存 file の変更（status M / D / R 等）は対象外にならない。
- subdirectory・別 package・`llm_` 以外の名前は対象外にならない。
- B7 の各 gate が凍結した B7 module は、それぞれの anchor との byte 比較で別に守る。
"""
from __future__ import annotations

import re

NEW_LLM_MODULE_RE = re.compile(r"^src/intelligence/theme_intelligence/llm_[a-z0-9_]+\.py$")
#: `git diff --name-status` の追加、`git status --porcelain` の staged 追加 / 未追跡
ADDITION_STATUSES = ("A", "??")


def is_new_llm_module(status: str, path: str) -> bool:
    return status in ADDITION_STATUSES and bool(NEW_LLM_MODULE_RE.match(path))


__all__ = ["ADDITION_STATUSES", "NEW_LLM_MODULE_RE", "is_new_llm_module"]
