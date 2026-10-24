"""P10-A4 — 個人の見直しの view と件数だけの安全な投影の test（合成の P9 ／ P10 の root だけ ・書き込みなし）。"""
from __future__ import annotations

import dataclasses
import socket
from datetime import date, datetime
from pathlib import Path

import pytest

from src.intelligence.personal_intelligence.attention_model import AttentionState, AttentionTargetKind
from src.intelligence.personal_intelligence.authority_stores import PersonalAuthorityStores
from src.intelligence.personal_intelligence.decisions import (AttentionCreate, AttentionTransition, ProfileCreate,
                                                              ProfileRetire, ProfileRevise)
from src.intelligence.personal_intelligence.executor import apply_decision
from src.intelligence.personal_intelligence.personal_projection import (PersonalSafeProjection,
                                                                        personal_safe_projection)
from src.intelligence.personal_intelligence.review_view import (AttentionMark, DueClass, ReviewViewError,
                                                                SurfaceGroup, read_personal_review)
from src.intelligence.watchlist_thesis_intelligence.authority_stores import AuthorityStores as P9AuthorityStores
from src.intelligence.watchlist_thesis_intelligence.revision_model import ChangeKind as P9ChangeKind
from src.intelligence.watchlist_thesis_intelligence.watch_model import WatchStatus
from tests.intelligence.test_personal_intelligence_executor import tree
from tests.intelligence.test_watchlist_thesis_semantics import HOUR, T0, thesis_create, watch_create, watch_next

AUTHOR = "human:reviewer"
MARKER = "PRIVATE-NOTE-MARKER"
AS_OF = date(2026, 9, 25)
T_VIEW = T0 + 20 * HOUR
FOCUS, MUTE = AttentionState.FOCUS, AttentionState.MUTE


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED: network")


def issuer(letter: str) -> str:
    return "p8iss_" + letter * 24


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    """P9: WC（期日を過ぎた）・WA ／ WB ／ WE（同じ日）・TA（WA の Thesis ・後の日）・WD ／ WF（PAUSED ・日なし）。
    P10: profile（IA を除外 ・窓 7 日）・印（WB ・TA ・WF は FOCUS ／ WA ・WD は MUTE ／ WE は FOCUS → CLEARED）。"""
    p9 = tmp_path / "p9_private_root"
    p9.mkdir()
    stores = P9AuthorityStores.initialize(p9)
    w = {}
    for i, (name, letter, due) in enumerate((("WA", "a", date(2026, 10, 1)), ("WB", "b", date(2026, 10, 1)),
                                            ("WC", "c", date(2026, 9, 20)), ("WD", "d", date(2026, 10, 2)),
                                            ("WE", "e", date(2026, 10, 1)), ("WF", "f", date(2026, 10, 3)))):
        w[name] = watch_create(issuer(letter), at=T0 + i * HOUR, review_due_on=due)
        stores.append_watch(w[name])
    w["TA"] = thesis_create(w["WA"], at=T0 + 6 * HOUR, review_due_on=date(2026, 10, 5))
    stores.append_thesis(w["TA"])
    for name, hour in (("WD", 7), ("WF", 8)):
        w[name] = watch_next(w[name], P9ChangeKind.TRANSITION, WatchStatus.PAUSED, reviewed_at=T0 + hour * HOUR,
                             review_due_on=None)
        stores.append_watch(w[name])
    p10 = tmp_path / "p10_private_root"
    p10.mkdir()
    PersonalAuthorityStores.initialize(p10)
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _trap)
    at = T0 + 10 * HOUR
    profile = apply_decision(ProfileCreate(author_ref=AUTHOR, reviewed_at=at, horizon_note=MARKER, liquidity_note="",
                                           risk_context_note="", review_lookahead_days=7,
                                           excluded_issuer_ids=(issuer("a"),),
                                           exclusion_reason_note="personal constraint"), p10_root=p10)
    marks = {}
    for name, state in (("WB", FOCUS), ("TA", FOCUS), ("WF", FOCUS), ("WA", MUTE), ("WD", MUTE), ("WE", FOCUS)):
        record = w[name]
        is_thesis = name == "TA"
        marks[name] = apply_decision(AttentionCreate(
            target_kind=AttentionTargetKind.P9_THESIS if is_thesis else AttentionTargetKind.P9_WATCH_ENTRY,
            target_root_id=record.thesis_id if is_thesis else record.watch_entry_id,
            observed_p9_revision_id=record.revision_id, state=state, author_ref=AUTHOR, reviewed_at=at),
            p10_root=p10, p9_root=p9)
    apply_decision(AttentionTransition(attention_id=marks["WE"].root_id,
                                       expected_head_revision_id=marks["WE"].revision_id,
                                       observed_p9_revision_id=w["WE"].revision_id, state=AttentionState.CLEARED,
                                       author_ref=AUTHOR, reviewed_at=at + HOUR), p10_root=p10, p9_root=p9)
    return dict(p9=p9, p10=p10, w=w, profile=profile, tmp=tmp_path)


def ids(world: dict, *names: str):
    return [world["w"][n].thesis_id if n == "TA" else world["w"][n].watch_entry_id for n in names]


def test_a_a_order_groups_marks_and_due_classes_follow_the_lock(world) -> None:
    before = (tree(world["p9"]), tree(world["p10"]))
    review = read_personal_review(world["p10"], world["p9"], at=T_VIEW, as_of_date=AS_OF)
    assert [e.p9_root_id for e in review.entries] == ids(world, "WC", "WB", "WE", "WA", "TA", "WF", "WD")
    by = {e.p9_root_id: e for e in review.entries}
    wa, ta, wd, wf, we = (by[i] for i in ids(world, "WA", "TA", "WD", "WF", "WE"))
    assert [e.due_class for e in review.entries] == [DueClass.OVERDUE, DueClass.UPCOMING, DueClass.UPCOMING,
                                                     DueClass.UPCOMING, DueClass.LATER, DueClass.NO_DUE_DATE,
                                                     DueClass.NO_DUE_DATE]
    assert [e.attention for e in review.entries] == [AttentionMark.NORMAL, AttentionMark.FOCUS, AttentionMark.NORMAL,
                                                     AttentionMark.MUTE, AttentionMark.FOCUS, AttentionMark.FOCUS,
                                                     AttentionMark.MUTE]
    # 除外は消さずに組で見せる ・FOCUS ／ MUTE の印は残す（矛盾ではない）・Thesis は link した Watchlist の発行体で導く
    assert (wa.surface_group, wa.attention, wa.excluded_by_profile) == (SurfaceGroup.EXCLUDED_BY_PROFILE,
                                                                       AttentionMark.MUTE, True)
    assert (ta.surface_group, ta.attention, ta.issuer_id) == (SurfaceGroup.EXCLUDED_BY_PROFILE, AttentionMark.FOCUS,
                                                             issuer("a"))
    assert ta.linked_watch_entry_id == world["w"]["WA"].watch_entry_id
    assert wd.surface_group is SurfaceGroup.MUTED and wf.surface_group is SurfaceGroup.REVIEW   # MUTE も見える
    assert we.attention is AttentionMark.NORMAL                                       # CLEARED ＝ 印なし
    assert len(review.entries) == 7 and review.active_profile_present and review.review_lookahead_days == 7
    assert (review.live_focus_marks, review.live_mute_marks, review.cleared_marks, review.unmatched_live_marks) == \
        (3, 2, 1, 0)
    assert read_personal_review(world["p10"], world["p9"], at=T_VIEW, as_of_date=AS_OF) == review   # 決定論
    assert (tree(world["p9"]), tree(world["p10"])) == before                         # 書かない


def test_a_b_focus_breaks_ties_only_inside_one_due_date(world) -> None:
    review = read_personal_review(world["p10"], world["p9"], at=T_VIEW, as_of_date=AS_OF)
    dated = [e for e in review.entries if e.review_due_on is not None]
    assert [e.review_due_on for e in dated] == sorted(e.review_due_on for e in dated)   # 期日が主
    assert all(e.review_due_on is None for e in review.entries[len(dated):])          # 日の無いものは後
    later_focus = next(e for e in review.entries if e.p9_root_id == ids(world, "TA")[0])
    earlier_normal = next(e for e in review.entries if e.p9_root_id == ids(world, "WE")[0])
    assert review.entries.index(earlier_normal) < review.entries.index(later_focus)   # FOCUS は早い期日を越えない


def test_a_c_lookahead_bounds_as_of_date_and_point_in_time(world) -> None:
    p10, p9 = world["p10"], world["p9"]
    head = world["profile"]
    content = dict(horizon_note=MARKER, liquidity_note="", risk_context_note="", excluded_issuer_ids=(issuer("a"),),
                   exclusion_reason_note="personal constraint")
    for days, hour in ((0, 21), (90, 23)):
        head = apply_decision(ProfileRevise(profile_id=head.root_id, expected_head_revision_id=head.revision_id,
                                            author_ref=AUTHOR, reviewed_at=T0 + hour * HOUR,
                                            review_lookahead_days=days, **content), p10_root=p10)

    def classes(at, as_of=AS_OF):
        return [e.due_class for e in read_personal_review(p10, p9, at=at, as_of_date=as_of).entries]

    assert classes(T0 + 22 * HOUR)[1:5] == [DueClass.LATER] * 4                       # 窓 0 日: UPCOMING なし
    assert classes(T0 + 24 * HOUR)[1:5] == [DueClass.UPCOMING] * 4                    # 窓 90 日
    assert classes(T_VIEW)[4] is DueClass.LATER                                        # 時点 T は窓 7 日のまま
    assert classes(T_VIEW, date(2026, 10, 1))[:4] == [DueClass.OVERDUE, DueClass.DUE, DueClass.DUE, DueClass.DUE]
    apply_decision(ProfileRetire(profile_id=head.root_id, expected_head_revision_id=head.revision_id,
                                 retirement_reason="paused", author_ref=AUTHOR, reviewed_at=T0 + 25 * HOUR),
                   p10_root=p10)
    for at in (T0 + 9 * HOUR, T0 + 26 * HOUR):                                         # profile の前 ／ 退役の後
        review = read_personal_review(p10, p9, at=at, as_of_date=AS_OF)
        assert not review.active_profile_present and review.review_lookahead_days == 0
        assert not any(e.excluded_by_profile for e in review.entries)
    after = read_personal_review(p10, p9, at=T0 + 26 * HOUR, as_of_date=AS_OF)
    wa = next(e for e in after.entries if e.p9_root_id == ids(world, "WA")[0])
    assert wa.surface_group is SurfaceGroup.MUTED


def test_a_d_explicit_inputs_and_fail_closed_reads_create_nothing(world) -> None:
    for kwargs, code in ((dict(at=datetime(2026, 7, 1, 9), as_of_date=AS_OF), "INSTANT_NOT_AWARE"),
                         (dict(at=T_VIEW, as_of_date=T_VIEW), "INVALID_DATE")):
        with pytest.raises(ReviewViewError) as exc:
            read_personal_review(world["p10"], world["p9"], **kwargs)
        assert exc.value.code == code
    absent = world["tmp"] / "absent"
    for p10, p9, code in ((absent, world["p9"], "P10_STORE_UNAVAILABLE"), (world["p10"], absent, "P9_UNAVAILABLE")):
        with pytest.raises(ReviewViewError) as exc:
            read_personal_review(p10, p9, at=T_VIEW, as_of_date=AS_OF)
        assert exc.value.code == code
    assert not absent.exists()


def test_b_a_the_safe_projection_holds_counts_only(world) -> None:
    review = read_personal_review(world["p10"], world["p9"], at=T_VIEW, as_of_date=AS_OF)
    projection = personal_safe_projection(review)
    counts = {k: v for k, v in vars(projection).items() if k not in ("projection_class", "schema_version")}
    assert counts == dict(active_profile_count=1, live_focus_mark_count=3, live_mute_mark_count=2,
                          cleared_mark_count=1, review_entry_count=7, overdue_count=1, due_count=0, upcoming_count=3,
                          later_count=1, no_due_date_count=2, focus_entry_count=3, muted_entry_count=2,
                          excluded_by_profile_count=2)
    assert all(type(v) is int for v in counts.values())
    assert {f.name for f in dataclasses.fields(PersonalSafeProjection)} == set(counts) | {"projection_class",
                                                                                         "schema_version"}
    text = repr(projection)
    for leak in ("p9wat_", "p9ths_", "p8iss_", "p10", "human:", MARKER, "personal constraint", "2026", "T0"):
        assert leak not in text.replace("p10_personal_safe_projection", ""), leak
    with pytest.raises(dataclasses.FrozenInstanceError):
        projection.due_count = 9
