"""P10-A4 — 個人の見直しの view（private ・local ・派生 ・非 authority ・書き込みなし ・表示の出し方だけ）。

`read_personal_review(p10_root, p9_root, *, at, as_of_date)`: 明示の瞬間 `at`（aware）・日 `as_of_date` だけ（時計なし）。
- P10: Profile ／ Attention の store を開くだけ（作らない）・A2 の `check_personal_world` ・時点 `at` の状態。
- P9: A1 の `read_p9_private_snapshot(p9_root, at=at)` だけ（P9 の全ての root を含む ・P9 の意味は複製しない）。

各 P9 の record（Watchlist の項目 ・Thesis）に: P9 の状態 ・出所の種類 ・`review_due_on` ・期日の区分（`OVERDUE` ／ `DUE` ／ `UPCOMING`
（`review_lookahead_days` の窓の内）／ `LATER` ／ `NO_DUE_DATE`）・印（`FOCUS` ／ `NORMAL` ／ `MUTE` ・印が無い ＝ NORMAL）・
ACTIVE な profile の除外（Thesis は同じ snapshot の link した Watchlist の項目の発行体で導く）・表示の組（`EXCLUDED_BY_PROFILE` ＞
`MUTED` ＞ `REVIEW`）。全ての record を含む（MUTE ・除外も消さない）。

順（見直しの作業の順だけ ・投資の順位ではない）: 1. `review_due_on` の昇順（日の無いものは後）2. 同じ日の中だけ FOCUS → NORMAL →
MUTE 3. P9 の root の id。FOCUS は早い期日を越えない。点数 ・順位 ・推奨 ・売買の緊急度 ・期待の利回り ・目標の価格 ・配分 ・
大きさは作らない。ACTIVE な profile が無ければ除外なし ・窓は 0 日。

記録: `docs/databank/PHASE10_A4_EXECUTOR_REVIEW_VIEW.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .attention_model import AttentionState
from .attention_store import AttentionStore
from .cross_rules import check_personal_world
from .p9_view import P9ViewError, read_p9_private_snapshot
from .profile_model import ProfileStatus
from .profile_store import ProfileStore
from .revision_model import PersonalModelError
from .store_io import PersonalStoreError

REVIEW_VIEW_SCHEMA_VERSION = "p10_personal_review:0.1.0"
REVIEW_VIEW_CLASS = "PERSONAL_REVIEW_PRIVATE_LOCAL_DERIVED_NON_AUTHORITY_SURFACING_ONLY"


class RecordKind(str, Enum):
    WATCH_ENTRY = "WATCH_ENTRY"
    THESIS = "THESIS"


class DueClass(str, Enum):
    OVERDUE = "OVERDUE"
    DUE = "DUE"
    UPCOMING = "UPCOMING"
    LATER = "LATER"
    NO_DUE_DATE = "NO_DUE_DATE"


class AttentionMark(str, Enum):
    FOCUS = "FOCUS"
    NORMAL = "NORMAL"
    MUTE = "MUTE"


class SurfaceGroup(str, Enum):
    REVIEW = "REVIEW"
    MUTED = "MUTED"
    EXCLUDED_BY_PROFILE = "EXCLUDED_BY_PROFILE"


#: 同じ期日の中だけの並び（期日を越えない）
_SAME_DAY_ORDER = {AttentionMark.FOCUS: 0, AttentionMark.NORMAL: 1, AttentionMark.MUTE: 2}


class ReviewViewError(ValueError):
    """読み込みの失敗（fail closed ・書かない）。文は安全な code だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, kw_only=True)
class ReviewEntry:
    record_kind: RecordKind
    p9_root_id: str
    p9_revision_id: str
    issuer_id: Optional[str]
    linked_watch_entry_id: str
    p9_status: str
    p9_provenance_kind: str
    review_due_on: Optional[date]
    due_class: DueClass
    attention: AttentionMark
    excluded_by_profile: bool
    surface_group: SurfaceGroup


@dataclass(frozen=True, kw_only=True)
class PersonalReview:
    as_of_date: date
    review_lookahead_days: int
    active_profile_present: bool
    entries: Tuple[ReviewEntry, ...]
    live_focus_marks: int
    live_mute_marks: int
    cleared_marks: int
    unmatched_live_marks: int
    view_class: str = REVIEW_VIEW_CLASS
    schema_version: str = REVIEW_VIEW_SCHEMA_VERSION


def _due_class(due: Optional[date], as_of: date, window: int) -> DueClass:
    if due is None:
        return DueClass.NO_DUE_DATE
    if due < as_of:
        return DueClass.OVERDUE
    if due == as_of:
        return DueClass.DUE
    return DueClass.UPCOMING if (due - as_of).days <= window else DueClass.LATER


def _order(entry: ReviewEntry) -> Tuple[Any, ...]:
    return (entry.review_due_on is None, entry.review_due_on or date.min, _SAME_DAY_ORDER[entry.attention],
            entry.p9_root_id)


def read_personal_review(p10_root: Any, p9_root: Any, *, at: Any, as_of_date: Any) -> PersonalReview:
    if not isinstance(at, datetime) or at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise ReviewViewError("INSTANT_NOT_AWARE", "at")
    if type(as_of_date) is not date:
        raise ReviewViewError("INVALID_DATE", "as_of_date")
    try:
        profiles, attention = ProfileStore.open(p10_root), AttentionStore.open(p10_root)   # 開くだけ
    except PersonalStoreError as exc:
        raise ReviewViewError("P10_STORE_UNAVAILABLE", f"{exc.category.value}:{exc.code}") from None
    try:
        check_personal_world(list(profiles.all_revisions()), list(attention.all_revisions()))
    except PersonalModelError as exc:
        raise ReviewViewError("P10_WORLD_INVALID", exc.code) from None
    try:
        snapshot = read_p9_private_snapshot(p9_root, at=at)
    except P9ViewError as exc:
        raise ReviewViewError("P9_UNAVAILABLE", exc.code) from None
    active = [head for head in profiles.states_at(at).values() if head.status is ProfileStatus.ACTIVE]
    excluded = set(active[0].excluded_issuer_ids) if active else set()
    window = active[0].review_lookahead_days if active else 0
    heads = attention.states_at(at).values()
    marks: Dict[str, AttentionMark] = {h.target_root_id: AttentionMark(h.state.value) for h in heads
                                       if h.state is not AttentionState.CLEARED}
    watch_by_id = {w.watch_entry_id: w for w in snapshot.watch}
    rows = []
    for w in snapshot.watch:
        rows += [(RecordKind.WATCH_ENTRY, w.watch_entry_id, w.revision_id, w.issuer_id, "", w.status,
                  w.provenance_kind, w.review_due_on)]
    for t in snapshot.thesis:
        linked = watch_by_id.get(t.watch_entry_id)
        rows += [(RecordKind.THESIS, t.thesis_id, t.revision_id, linked.issuer_id if linked else None,
                  t.watch_entry_id, t.status, "", t.review_due_on)]
    entries = []
    for kind, root_id, revision_id, issuer_id, linked_id, status, provenance, due in rows:
        mark = marks.get(root_id, AttentionMark.NORMAL)
        is_excluded = issuer_id is not None and issuer_id in excluded
        group = (SurfaceGroup.EXCLUDED_BY_PROFILE if is_excluded else
                 SurfaceGroup.MUTED if mark is AttentionMark.MUTE else SurfaceGroup.REVIEW)
        entries += [ReviewEntry(record_kind=kind, p9_root_id=root_id, p9_revision_id=revision_id, issuer_id=issuer_id,
                                linked_watch_entry_id=linked_id, p9_status=status, p9_provenance_kind=provenance,
                                review_due_on=due, due_class=_due_class(due, as_of_date, window), attention=mark,
                                excluded_by_profile=is_excluded, surface_group=group)]
    visible_roots = {e.p9_root_id for e in entries}
    return PersonalReview(
        as_of_date=as_of_date, review_lookahead_days=window, active_profile_present=bool(active),
        entries=tuple(sorted(entries, key=_order)),
        live_focus_marks=sum(1 for m in marks.values() if m is AttentionMark.FOCUS),
        live_mute_marks=sum(1 for m in marks.values() if m is AttentionMark.MUTE),
        cleared_marks=sum(1 for h in heads if h.state is AttentionState.CLEARED),
        unmatched_live_marks=sum(1 for root in marks if root not in visible_roots))


__all__ = ["AttentionMark", "DueClass", "PersonalReview", "REVIEW_VIEW_CLASS", "REVIEW_VIEW_SCHEMA_VERSION",
           "RecordKind", "ReviewEntry", "ReviewViewError", "SurfaceGroup", "read_personal_review"]
