"""P11-A1 — Phase 11 の UI model（不変 ・派生 ・非 authority ・表示の構造だけ）と決定論の JSON（表示の直列化 ・authority の形ではない）。

- `UiModel` ＝ 明示の瞬間 `at`（UTC の ISO）・日 `as_of_date` ・ACTIVE な profile の有無 ・見直しの窓の日数 ・件数（P10 の安全な投影 ・
  凍結 P9 の安全な view）・`UiReviewEntry` の列（凍結 P10 の見直しの view の順のまま。P11 で並べ替えない）。
- `UiReviewEntry` ＝ `ordinal`（応答の中の位置 ＝ 表示の鍵。authority の id ではなく ・id を復元できない）・種類（WATCH ／ THESIS）・
  P9 の状態 ・出所の種類 ・期日 ・期日の区分 ・印（FOCUS ／ NORMAL ／ MUTE）・除外の有無 ・表示の組 ・link した Watchlist の `ordinal`。
  P9 ／ P10 の id ・revision の id ・発行体 ・profile の文 ・除外の id ／ 理由 ・著者 ・path は持たない（型に欄が無い）。
- 語彙は凍結 P10 の列挙の値の複製（一致は test が pin）。点数 ・順位 ・推奨 ・保有の欄は無い。
- JSON: UTF-8 ・key の文字の順 ・区切りの空白なし ・NaN ／ Infinity は拒む ・schema の版を含む。入力の順は governed な view の順を保つ。
- `UiReadError` ＝ 安全な code と、大文字の code の文字だけの detail（それ以外の detail は捨てる ・path ・id ・文は入らない）。

記録: `docs/databank/PHASE11_A1_GOVERNED_READ_ADAPTER.md`。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from typing import Any, Dict, Mapping, Optional, Tuple

UI_MODEL_SCHEMA_VERSION = "p11_ui_model:0.1.0"
UI_MODEL_VIEW_CLASS = "P11_UI_MODEL_PRIVATE_LOCAL_DERIVED_NON_AUTHORITY_READ_ONLY"
UI_ERROR_SCHEMA_VERSION = "p11_ui_error:0.1.0"
#: 凍結 P10 の列挙の値の複製（一致は test が pin）
SOURCE_KINDS = ("WATCH", "THESIS")
ATTENTION_MARKS = ("FOCUS", "NORMAL", "MUTE")
DUE_CLASSES = ("OVERDUE", "DUE", "UPCOMING", "LATER", "NO_DUE_DATE")
SURFACE_GROUPS = ("REVIEW", "MUTED", "EXCLUDED_BY_PROFILE")
Counts = Tuple[Tuple[str, int], ...]
Versions = Tuple[Tuple[str, str], ...]
_UTC_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_DETAIL_RE = re.compile(r"^[A-Z0-9_:]{1,80}$")


class UiReadError(ValueError):
    """P11 の読み込みの失敗（fail closed ・書かない）。文は安全な code と大文字の code の detail だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        safe = detail if isinstance(detail, str) and _SAFE_DETAIL_RE.match(detail) else ""
        super().__init__(f"{code}:{safe}" if safe else code)
        self.code = code
        self.detail = safe


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise UiReadError(code, detail)


def _counts(value: Any, name: str) -> Counts:
    _require(isinstance(value, tuple), "MODEL_INVALID", f"COUNTS:{name.upper()}")
    keys = [k for k, _ in value]
    for key, count in value:
        _require(isinstance(key, str) and key != "" and type(count) is int and count >= 0, "MODEL_INVALID",
                 f"COUNTS:{name.upper()}")
    _require(keys == sorted(keys) and len(set(keys)) == len(keys), "MODEL_INVALID", f"COUNTS_ORDER:{name.upper()}")
    return value


@dataclass(frozen=True, kw_only=True)
class UiReviewEntry:
    """見直しの 1 行の表示の構造（凍結 P10 の `ReviewEntry` から id ・発行体 ・link の id を捨てたもの）。"""

    ordinal: int
    source_kind: str
    p9_status: str
    p9_provenance_kind: str
    review_due_on: Optional[str]
    due_class: str
    attention: str
    excluded_by_profile: bool
    surface_group: str
    linked_watch_ordinal: Optional[int]

    def __post_init__(self) -> None:
        _require(type(self.ordinal) is int and self.ordinal >= 0, "MODEL_INVALID", "ORDINAL")
        _require(self.source_kind in SOURCE_KINDS, "MODEL_INVALID", "SOURCE_KIND")
        _require(isinstance(self.p9_status, str) and self.p9_status.isupper(), "MODEL_INVALID", "P9_STATUS")
        _require(isinstance(self.p9_provenance_kind, str) and (self.p9_provenance_kind == ""
                                                               or self.p9_provenance_kind.isupper()),
                 "MODEL_INVALID", "P9_PROVENANCE_KIND")
        _require(self.review_due_on is None or (isinstance(self.review_due_on, str)
                                                and bool(_DATE_RE.match(self.review_due_on))),
                 "MODEL_INVALID", "REVIEW_DUE_ON")
        _require(self.due_class in DUE_CLASSES, "MODEL_INVALID", "DUE_CLASS")
        _require(self.attention in ATTENTION_MARKS, "MODEL_INVALID", "ATTENTION")
        _require(type(self.excluded_by_profile) is bool, "MODEL_INVALID", "EXCLUDED_BY_PROFILE")
        _require(self.surface_group in SURFACE_GROUPS, "MODEL_INVALID", "SURFACE_GROUP")
        _require(self.linked_watch_ordinal is None or (type(self.linked_watch_ordinal) is int
                                                       and self.linked_watch_ordinal >= 0),
                 "MODEL_INVALID", "LINKED_WATCH_ORDINAL")
        _require((self.source_kind == "THESIS") or self.linked_watch_ordinal is None, "MODEL_INVALID",
                 "LINKED_WATCH_ORDINAL")


@dataclass(frozen=True, kw_only=True)
class UiModel:
    """Phase 11 v1 の読み取りの応答（private ・local ・派生 ・非 authority ・保存しない）。"""

    at: str
    as_of_date: str
    active_profile_present: bool
    review_lookahead_days: int
    personal_counts: Counts
    p9_counts: Counts
    unmatched_live_mark_count: int
    entries: Tuple[UiReviewEntry, ...]
    source_schema_versions: Versions
    schema_version: str = UI_MODEL_SCHEMA_VERSION
    view_class: str = UI_MODEL_VIEW_CLASS

    def __post_init__(self) -> None:
        _require(isinstance(self.at, str) and bool(_UTC_INSTANT_RE.match(self.at)), "MODEL_INVALID", "AT")
        _require(isinstance(self.as_of_date, str) and bool(_DATE_RE.match(self.as_of_date)), "MODEL_INVALID",
                 "AS_OF_DATE")
        _require(type(self.active_profile_present) is bool, "MODEL_INVALID", "ACTIVE_PROFILE_PRESENT")
        _require(type(self.review_lookahead_days) is int and self.review_lookahead_days >= 0, "MODEL_INVALID",
                 "REVIEW_LOOKAHEAD_DAYS")
        _counts(self.personal_counts, "personal")
        _counts(self.p9_counts, "p9")
        _require(type(self.unmatched_live_mark_count) is int and self.unmatched_live_mark_count >= 0,
                 "MODEL_INVALID", "UNMATCHED_LIVE_MARK_COUNT")
        _require(isinstance(self.entries, tuple) and all(isinstance(e, UiReviewEntry) for e in self.entries),
                 "MODEL_INVALID", "ENTRIES")
        _require([e.ordinal for e in self.entries] == list(range(len(self.entries))), "MODEL_INVALID", "ORDINALS")
        for entry in self.entries:
            _require(entry.linked_watch_ordinal is None or (entry.linked_watch_ordinal < len(self.entries)
                                                             and self.entries[entry.linked_watch_ordinal].source_kind
                                                             == "WATCH"), "MODEL_INVALID", "LINKED_WATCH_ORDINAL")
        _require(isinstance(self.source_schema_versions, tuple) and all(
            isinstance(k, str) and isinstance(v, str) and k and v for k, v in self.source_schema_versions)
            and [k for k, _ in self.source_schema_versions] == sorted(k for k, _ in self.source_schema_versions),
            "MODEL_INVALID", "SOURCE_SCHEMA_VERSIONS")
        _require(self.schema_version == UI_MODEL_SCHEMA_VERSION, "MODEL_INVALID", "SCHEMA_VERSION")
        _require(self.view_class == UI_MODEL_VIEW_CLASS, "MODEL_INVALID", "VIEW_CLASS")


# ---------------------------------------------------------------- 決定論の JSON（表示の直列化。authority の形ではない）


def model_to_dict(model: UiModel) -> Dict[str, Any]:
    """UI model → JSON にできる plain な dict（件数の tuple は dict ・列は list。順は governed な view のまま）。"""
    _require(isinstance(model, UiModel), "MODEL_INVALID", "MODEL")
    payload: Dict[str, Any] = {}
    for field in fields(UiModel):
        value = getattr(model, field.name)
        if field.name in ("personal_counts", "p9_counts", "source_schema_versions"):
            payload[field.name] = dict(value)
        elif field.name == "entries":
            payload[field.name] = [{f.name: getattr(e, f.name) for f in fields(UiReviewEntry)} for e in value]
        else:
            payload[field.name] = value
    return payload


def canonical_json(payload: Mapping[str, Any]) -> str:
    """正準の JSON（key の文字の順 ・区切りの空白なし ・非 ASCII はそのまま ・NaN ／ Infinity は拒む）。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def ui_model_json_bytes(model: UiModel) -> bytes:
    return canonical_json(model_to_dict(model)).encode("utf-8")


def error_payload(error: UiReadError) -> Dict[str, Any]:
    _require(isinstance(error, UiReadError), "MODEL_INVALID", "ERROR")
    return {"code": error.code, "detail": error.detail, "schema_version": UI_ERROR_SCHEMA_VERSION}


def error_json_bytes(error: UiReadError) -> bytes:
    return canonical_json(error_payload(error)).encode("utf-8")


__all__ = ["ATTENTION_MARKS", "Counts", "DUE_CLASSES", "SOURCE_KINDS", "SURFACE_GROUPS", "UI_ERROR_SCHEMA_VERSION",
           "UI_MODEL_SCHEMA_VERSION", "UI_MODEL_VIEW_CLASS", "UiModel", "UiReadError", "UiReviewEntry", "Versions",
           "canonical_json", "error_json_bytes", "error_payload", "model_to_dict", "ui_model_json_bytes"]
