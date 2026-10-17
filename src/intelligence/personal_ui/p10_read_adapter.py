"""P11-A1 — 凍結 Phase 10 の governed な read の API だけを使う Phase 11 の唯一の read の adapter。

`read_ui_model(p10_root, p9_root, *, at, as_of_date) -> UiModel`:
1. 入力の検査（root は非空の path ・`at` は aware な datetime ・`as_of_date` は date。既定 ・時計は無い）→ `INPUT_INVALID:<code>`。
2. 凍結 P10 の `read_personal_review`（private な見直しの view。P10 の store を開くだけ ・P9 は A1 の adapter で）→
   `personal_safe_projection`（件数）→ 凍結 P10 の `read_p9_safe_view`（凍結 P9 の件数だけの view）。全て同じ `at` ・`as_of_date`。
3. governed な view の順のまま `UiReviewEntry` に写す。P9 ／ P10 の id ・revision の id ・発行体 ・link の id は捨てる（Thesis の link は
   同じ応答の中の Watchlist の行の `ordinal` に写す）。文 ・除外の id ／ 理由 ・著者は governed な view に無く、P11 は新しい reader を
   足さない。
4. 下の層の型つきの失敗は安定した P11 の code に写す（`P10_UNAVAILABLE` ・`P10_INVALID` ・`P9_UNAVAILABLE` ・`P9_INVALID` ・
   `INPUT_INVALID`）。detail は大文字の code だけ（path ・id ・文は入らない）。修復 ・作成 ・書き込み ・network ・環境変数は無い。

決定論: 同じ P9 ／ P10 の store の byte ・同じ瞬間（UTC で正準化）・同じ日 → 同じ JSON の byte。

記録: `docs/databank/PHASE11_A1_GOVERNED_READ_ADAPTER.md`。
"""
from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Tuple

from ..personal_intelligence.p9_view import P9ViewError, read_p9_safe_view
from ..personal_intelligence.personal_projection import personal_safe_projection
from ..personal_intelligence.review_view import ReviewViewError, read_personal_review
from .ui_model import UiModel, UiReadError, UiReviewEntry

ADAPTER_RULES_VERSION = "p11_p10_read_adapter:0.1.0"
_SOURCE_KINDS = {"WATCH_ENTRY": "WATCH", "THESIS": "THESIS"}
_INPUT_CODES = ("INSTANT_NOT_AWARE", "INVALID_DATE")


def _check_root(value: Any, name: str) -> Any:
    if isinstance(value, str):
        ok = value.strip() != ""
    else:
        ok = hasattr(value, "__fspath__")
    if not ok:
        raise UiReadError("INPUT_INVALID", f"ROOT_REQUIRED:{name}")
    return value


def _check_inputs(at: Any, as_of_date: Any) -> None:
    if not (isinstance(at, datetime) and at.tzinfo is not None and at.tzinfo.utcoffset(at) is not None):
        raise UiReadError("INPUT_INVALID", "INSTANT_NOT_AWARE")
    if type(as_of_date) is not date:
        raise UiReadError("INPUT_INVALID", "INVALID_DATE")


def _map_review_error(exc: ReviewViewError) -> UiReadError:
    if exc.code in _INPUT_CODES:
        return UiReadError("INPUT_INVALID", exc.code)
    if exc.code == "P10_STORE_UNAVAILABLE":
        return UiReadError("P10_UNAVAILABLE", exc.detail)
    if exc.code == "P10_WORLD_INVALID":
        return UiReadError("P10_INVALID", exc.detail)
    if exc.code == "P9_UNAVAILABLE":
        return UiReadError("P9_UNAVAILABLE", exc.detail)
    return UiReadError("P10_READ_FAILED", exc.code)


def _map_p9_error(exc: P9ViewError) -> UiReadError:
    if exc.code in _INPUT_CODES:
        return UiReadError("INPUT_INVALID", exc.code)
    if exc.code == "P9_STORE_UNAVAILABLE":
        return UiReadError("P9_UNAVAILABLE", exc.detail)
    if exc.code == "P9_WORLD_INVALID":
        return UiReadError("P9_INVALID", exc.detail)
    return UiReadError("P9_READ_FAILED", exc.code)


def _sorted_counts(mapping: Dict[str, int]) -> Tuple[Tuple[str, int], ...]:
    return tuple((key, mapping[key]) for key in sorted(mapping))


def _p9_counts(safe_view: Any) -> Tuple[Tuple[str, int], ...]:
    """凍結 P9 の安全な view（件数だけ）を平らな件数に写す（`<field>` ・`<field>.<key>`）。文 ・日の欄は入れない。"""
    flat: Dict[str, int] = {}
    for field in fields(safe_view):
        value = getattr(safe_view, field.name)
        if type(value) is int:
            flat[field.name] = value
        elif isinstance(value, tuple):
            for key, count in value:
                flat[f"{field.name}.{key}"] = count
    return _sorted_counts(flat)


def _entries(review: Any) -> Tuple[UiReviewEntry, ...]:
    """governed な view の順のまま。id は link の `ordinal` を求めるのに関数の中だけで使い、出さない。"""
    watch_ordinals = {e.p9_root_id: i for i, e in enumerate(review.entries) if e.record_kind.value == "WATCH_ENTRY"}
    rows: List[UiReviewEntry] = []
    for ordinal, entry in enumerate(review.entries):
        kind = _SOURCE_KINDS[entry.record_kind.value]
        linked = watch_ordinals.get(entry.linked_watch_entry_id) if kind == "THESIS" else None
        rows.append(UiReviewEntry(
            ordinal=ordinal, source_kind=kind, p9_status=entry.p9_status, p9_provenance_kind=entry.p9_provenance_kind,
            review_due_on=entry.review_due_on.isoformat() if entry.review_due_on is not None else None,
            due_class=entry.due_class.value, attention=entry.attention.value,
            excluded_by_profile=entry.excluded_by_profile, surface_group=entry.surface_group.value,
            linked_watch_ordinal=linked))
    return tuple(rows)


def read_ui_model(p10_root: Any, p9_root: Any, *, at: Any, as_of_date: Any) -> UiModel:
    """凍結 P10 の governed な view を明示の `at` ・`as_of_date` で読み、不変の UI model に写す（書かない ・作らない）。"""
    _check_root(p10_root, "P10")
    _check_root(p9_root, "P9")
    _check_inputs(at, as_of_date)
    try:
        review = read_personal_review(p10_root, p9_root, at=at, as_of_date=as_of_date)
    except ReviewViewError as exc:
        raise _map_review_error(exc) from None
    projection = personal_safe_projection(review)
    try:
        safe_view = read_p9_safe_view(p9_root, at=at, as_of_date=as_of_date)
    except P9ViewError as exc:
        raise _map_p9_error(exc) from None
    personal_counts = _sorted_counts({f.name: getattr(projection, f.name) for f in fields(projection)
                                      if type(getattr(projection, f.name)) is int})
    return UiModel(
        at=at.astimezone(timezone.utc).isoformat(), as_of_date=as_of_date.isoformat(),
        active_profile_present=review.active_profile_present, review_lookahead_days=review.review_lookahead_days,
        personal_counts=personal_counts, p9_counts=_p9_counts(safe_view),
        unmatched_live_mark_count=review.unmatched_live_marks, entries=_entries(review),
        source_schema_versions=(("p10_personal_projection", projection.schema_version),
                                ("p10_review_view", review.schema_version),
                                ("p9_safe_view", safe_view.schema_version)))


__all__ = ["ADAPTER_RULES_VERSION", "read_ui_model"]
