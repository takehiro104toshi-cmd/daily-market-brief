"""P10-A4 — Phase 10 の個人の状態の安全な投影（件数だけ ・派生 ・非 authority ・保存しない）。

個人の見直しの view から件数だけを数える。profile の文 ・除外の理由 ・発行体 ・P9 ／ P10 の id ・revision の id ・著者 ・瞬間 ・期日 ・
日は入れない。

記録: `docs/databank/PHASE10_A4_EXECUTOR_REVIEW_VIEW.md`。
"""
from __future__ import annotations

from dataclasses import dataclass

from .review_view import AttentionMark, DueClass, PersonalReview, SurfaceGroup

PERSONAL_PROJECTION_SCHEMA_VERSION = "p10_personal_safe_projection:0.1.0"
PERSONAL_PROJECTION_CLASS = "PERSONAL_SAFE_PROJECTION_COUNTS_ONLY_DERIVED_NON_AUTHORITY_NOT_PERSISTED"


@dataclass(frozen=True, kw_only=True)
class PersonalSafeProjection:
    active_profile_count: int
    live_focus_mark_count: int
    live_mute_mark_count: int
    cleared_mark_count: int
    review_entry_count: int
    overdue_count: int
    due_count: int
    upcoming_count: int
    later_count: int
    no_due_date_count: int
    focus_entry_count: int
    muted_entry_count: int
    excluded_by_profile_count: int
    projection_class: str = PERSONAL_PROJECTION_CLASS
    schema_version: str = PERSONAL_PROJECTION_SCHEMA_VERSION


def personal_safe_projection(review: PersonalReview) -> PersonalSafeProjection:
    entries = review.entries

    def count(predicate) -> int:
        return sum(1 for entry in entries if predicate(entry))

    return PersonalSafeProjection(
        active_profile_count=1 if review.active_profile_present else 0, live_focus_mark_count=review.live_focus_marks,
        live_mute_mark_count=review.live_mute_marks, cleared_mark_count=review.cleared_marks,
        review_entry_count=len(entries), overdue_count=count(lambda e: e.due_class is DueClass.OVERDUE),
        due_count=count(lambda e: e.due_class is DueClass.DUE),
        upcoming_count=count(lambda e: e.due_class is DueClass.UPCOMING),
        later_count=count(lambda e: e.due_class is DueClass.LATER),
        no_due_date_count=count(lambda e: e.due_class is DueClass.NO_DUE_DATE),
        focus_entry_count=count(lambda e: e.attention is AttentionMark.FOCUS),
        muted_entry_count=count(lambda e: e.attention is AttentionMark.MUTE),
        excluded_by_profile_count=count(lambda e: e.surface_group is SurfaceGroup.EXCLUDED_BY_PROFILE))


__all__ = ["PERSONAL_PROJECTION_CLASS", "PERSONAL_PROJECTION_SCHEMA_VERSION", "PersonalSafeProjection",
           "personal_safe_projection"]
