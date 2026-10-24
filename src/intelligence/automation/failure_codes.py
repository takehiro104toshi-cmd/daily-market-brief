"""P12-A1 — 安全な機械可読の失敗 ／ skip の code と、private な診断の分離。

- 安全な code は `[A-Z][A-Z0-9_]*` に `:` で 1 段の detail を付けた形だけ。例外の文 ・path ・private な値 ・id ・payload は
  決して code にならない（`Diagnostic.private_detail` は直列化 ・repr ・str に出ない）。
- A1 は型 ／ model だけ（log ・file ・出力は後の gate）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import FrozenSet, Optional

SAFE_CODE_RE = re.compile(r"\A[A-Z][A-Z0-9_]{2,63}(:[A-Z][A-Z0-9_]{1,63})?\Z")

#: 予約した安全な code（失敗 ・skip ・運用の状態）。A1 以後の gate は足すだけで意味を変えない
FAILURE_CODES: FrozenSet[str] = frozenset({
    "REPO_NOT_CLEAN", "REPO_HEAD_MISMATCH", "FROZEN_DRIFT", "ROOT_MISSING", "SCHEMA_INVALID", "SOURCE_STALE",
    "SOURCE_INCOMPLETE", "DUPLICATE_INVOCATION", "OUTSIDE_WINDOW", "NON_BUSINESS_DAY", "CALENDAR_UNAVAILABLE",
    "INTERRUPTED", "ORPHANED_FINALIZATION", "DISABLED", "SLOT_NOT_FOUND", "ALREADY_SUCCEEDED", "CANCELLED",
    "ILLEGAL_TRANSITION", "LEDGER_INVALID", "SELECTION_CLOCK_NOT_AWARE", "WEEKDAY_NOT_IN_MASK", "CREDENTIAL_PRESENT",
    "STEP_FAILED",
})


def is_safe_code(value: object) -> bool:
    return isinstance(value, str) and SAFE_CODE_RE.match(value) is not None


def safe_code(value: object) -> str:
    """安全な code の形でなければ `AutomationError("SCHEMA_INVALID", "UNSAFE_CODE")`。"""
    if not is_safe_code(value):
        raise AutomationError("SCHEMA_INVALID", "UNSAFE_CODE")
    return value  # type: ignore[return-value]


def is_reserved_code(value: str) -> bool:
    return value.split(":", 1)[0] in FAILURE_CODES


class AutomationError(ValueError):
    """Phase 12 の domain の誤り。文は安全な code（と安全な detail）だけ。private な診断は属性に留まり、str ・repr に出ない。"""

    def __init__(self, code: str, detail: str = "", private_detail: Optional[str] = None) -> None:
        if not is_safe_code(code) or ":" in code:
            code = "SCHEMA_INVALID"
        if detail and not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", detail):
            detail = "UNSAFE_DETAIL"                       # 安全でない detail（path ・文）は code に置き換える
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.private_detail = private_detail

    def __repr__(self) -> str:
        return f"AutomationError({str(self)!r})"

    @property
    def public_code(self) -> str:
        return str(self)


@dataclass(frozen=True, repr=False)
class Diagnostic:
    """安全な code と private な診断の対。直列化 ・repr ・str は code だけ。"""

    code: str
    private_detail: Optional[str] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        safe_code(self.code)

    def __repr__(self) -> str:
        return f"Diagnostic({self.code!r})"

    __str__ = __repr__

    def to_public(self) -> str:
        return self.code


__all__ = ["AutomationError", "Diagnostic", "FAILURE_CODES", "SAFE_CODE_RE", "is_reserved_code", "is_safe_code",
           "safe_code"]
