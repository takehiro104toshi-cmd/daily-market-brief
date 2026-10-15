"""P10-A4 — 人の決定の実行器 ・P9 の参照の検査 ・古い先頭 ／ 再試行 ・dry-run の test（合成の P9 ／ P10 の root だけ）。"""
from __future__ import annotations

import dataclasses
import http.client
import socket
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.intelligence.personal_intelligence import decisions as dm
from src.intelligence.personal_intelligence import store_io
from src.intelligence.personal_intelligence.attention_model import AttentionState, AttentionTargetKind
from src.intelligence.personal_intelligence.authority_stores import PersonalAuthorityStores
from src.intelligence.personal_intelligence.decisions import (AttentionCreate, AttentionRevise, AttentionTransition,
                                                              ProfileCorrection, ProfileCreate, ProfileRetire,
                                                              ProfileRevise)
from src.intelligence.personal_intelligence.executor import (DryRunStatus, ExecutionRefusal, ExecutionStatus,
                                                             apply_decision, dry_run_decision)
from src.intelligence.watchlist_thesis_intelligence import store_io as p9_store_io
from src.intelligence.watchlist_thesis_intelligence.authority_stores import AuthorityStores as P9AuthorityStores
from src.intelligence.watchlist_thesis_intelligence.revision_model import ChangeKind as P9ChangeKind
from tests.intelligence.test_watchlist_thesis_semantics import (HOUR, ISSUER, ISSUER2, T0, thesis_create,
                                                                watch_create, watch_next)

AUTHOR = "human:reviewer"
MARKER = "PRIVATE-NOTE-MARKER"
D1, D2 = date(2026, 10, 1), date(2026, 10, 5)
FOCUS, MUTE, CLEARED = AttentionState.FOCUS, AttentionState.MUTE, AttentionState.CLEARED
WATCH_KIND, THESIS_KIND = AttentionTargetKind.P9_WATCH_ENTRY, AttentionTargetKind.P9_THESIS


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED")


def tree(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): (p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
            for p in sorted(path.rglob("*"))}


def build_p9(root: Path, extra=()) -> dict:
    """合成の P9 の世界: W1（後に REVISE）・W2 ・W1 の Thesis T1。"""
    root.mkdir()
    stores = P9AuthorityStores.initialize(root)
    w1 = watch_create(ISSUER, at=T0, review_due_on=D1)
    w2 = watch_create(ISSUER2, at=T0 + HOUR, review_due_on=D1)
    t1 = thesis_create(w1, at=T0 + 2 * HOUR, review_due_on=D2)
    w1b = watch_next(w1, P9ChangeKind.REVISE, reviewed_at=T0 + 3 * HOUR, review_due_on=D1)
    for revision in (w1, w2):
        stores.append_watch(revision)
    stores.append_thesis(t1)
    stores.append_watch(w1b)
    for kind, revision in extra:
        (stores.append_watch if kind == "watch" else stores.append_thesis)(revision)
    return dict(root=root, w1=w1, w2=w2, t1=t1, w1b=w1b)


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    """P9 を作った後で: network ・credential ・P9 の書き込み ／ 作成を罠にする。P10 の root は初期化済み。"""
    p9 = build_p9(tmp_path / "p9_private_root")
    p10 = tmp_path / "p10_private_root"
    p10.mkdir()
    PersonalAuthorityStores.initialize(p10)
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _trap)
    monkeypatch.setattr(socket.socket, "connect", _trap)
    monkeypatch.setattr(http.client.HTTPConnection, "__init__", _trap)
    monkeypatch.setattr(p9_store_io.RevisionStore, "_append_line", _trap)
    monkeypatch.setattr(p9_store_io.RevisionStore, "initialize", classmethod(_trap))
    monkeypatch.setattr(p9_store_io, "initialize_file", _trap)
    monkeypatch.setattr(P9AuthorityStores, "__init__", _trap)
    p9_before = tree(p9["root"])
    yield dict(p9, p10=p10, tmp=tmp_path)
    assert tree(p9["root"]) == p9_before                                              # P9 は byte も mtime も不変


def refused(code: str, fn, *args, **kwargs) -> ExecutionRefusal:
    with pytest.raises(ExecutionRefusal) as exc:
        fn(*args, **kwargs)
    assert str(exc.value) == code, str(exc.value)
    return exc.value


def profile_create(at=T0 + 4 * HOUR, **over) -> ProfileCreate:
    fields = dict(author_ref=AUTHOR, reviewed_at=at, horizon_note=MARKER, liquidity_note="", risk_context_note="",
                  review_lookahead_days=14, excluded_issuer_ids=(), exclusion_reason_note="")
    return ProfileCreate(**{**fields, **over})


def content(**over) -> dict:
    fields = dict(horizon_note="long term, roughly 10 years", liquidity_note="", risk_context_note="",
                  review_lookahead_days=30, excluded_issuer_ids=(ISSUER2,), exclusion_reason_note="personal context")
    return {**fields, **over}


def focus_w1(world: dict, at=T0 + 4 * HOUR, state=FOCUS, observed=None) -> AttentionCreate:
    """W1 への印（既定は T0+4h に見える先頭 W1b を見た FOCUS）。"""
    return AttentionCreate(target_kind=WATCH_KIND, target_root_id=world["w1"].watch_entry_id,
                           observed_p9_revision_id=observed or world["w1b"].revision_id, state=state,
                           author_ref=AUTHOR, reviewed_at=at)


# ================================================ Profile


def test_a_a_profile_create_reuse_second_active_and_dry_run(world) -> None:
    p10 = world["p10"]
    decision = profile_create()
    before = tree(p10)
    assert dry_run_decision(decision, p10_root=p10).status is DryRunStatus.VALID
    assert tree(p10) == before                                                        # dry-run は書かない
    receipt = apply_decision(decision, p10_root=p10)
    assert receipt.status is ExecutionStatus.APPENDED and receipt.operation == "PROFILE_CREATE"
    assert receipt.root_id.startswith("p10prf_") and receipt.revision_id.startswith("p10prv_")
    after = tree(p10)
    assert apply_decision(decision, p10_root=p10).status is ExecutionStatus.REUSED  # 正確な再試行
    assert dry_run_decision(decision, p10_root=p10).status is DryRunStatus.WOULD_REUSE and tree(p10) == after
    second = profile_create(at=T0 + 5 * HOUR)
    refused("AUTHORITY_WORLD_INVALID:MULTIPLE_ACTIVE_PROFILES", apply_decision, second, p10_root=p10)
    result = dry_run_decision(second, p10_root=p10)
    assert (result.status, result.refusal) == (DryRunStatus.WOULD_BE_REJECTED,
                                               "AUTHORITY_WORLD_INVALID:MULTIPLE_ACTIVE_PROFILES")
    assert tree(p10) == after


def test_a_b_profile_revise_correction_retire_terminal_and_stale_head(world) -> None:
    p10 = world["p10"]
    created = apply_decision(profile_create(), p10_root=p10)
    revise = ProfileRevise(profile_id=created.root_id, expected_head_revision_id=created.revision_id,
                           author_ref=AUTHOR, reviewed_at=T0 + 5 * HOUR, **content())
    revised = apply_decision(revise, p10_root=p10)
    assert revised.status is ExecutionStatus.APPENDED
    assert apply_decision(revise, p10_root=p10).status is ExecutionStatus.REUSED      # 古い先頭の正確な再試行は REUSED
    other = dataclasses.replace(revise, horizon_note="a different revision on the old head")
    refused("STALE_AUTHORITY_HEAD", apply_decision, other, p10_root=p10)             # 黙って新しい先頭に載せない
    assert dry_run_decision(other, p10_root=p10).refusal == "STALE_AUTHORITY_HEAD"
    correction = ProfileCorrection(profile_id=created.root_id, expected_head_revision_id=revised.revision_id,
                                   corrects_revision_id=revised.revision_id, correction_reason="window was wrong",
                                   author_ref=AUTHOR, reviewed_at=T0 + 6 * HOUR, **content(review_lookahead_days=7))
    corrected = apply_decision(correction, p10_root=p10)
    bad = dataclasses.replace(correction, expected_head_revision_id=corrected.revision_id,
                              corrects_revision_id="p10prv_" + "0" * 24, reviewed_at=T0 + 7 * HOUR)
    refused("AUTHORITY_WORLD_INVALID:CORRECTION_TARGET_UNKNOWN", apply_decision, bad, p10_root=p10)
    retire = ProfileRetire(profile_id=created.root_id, expected_head_revision_id=corrected.revision_id,
                           retirement_reason="starting over", author_ref=AUTHOR, reviewed_at=T0 + 7 * HOUR)
    retired = apply_decision(retire, p10_root=p10)
    chain = PersonalAuthorityStores.open(p10).profile.chain(created.root_id)
    assert [r.change_kind.value for r in chain] == ["CREATE", "REVISE", "CORRECTION", "TRANSITION"]
    assert chain[-1].status.value == "RETIRED" and chain[-1].content() == chain[-2].content()   # 内容は変えない
    assert len(PersonalAuthorityStores.open(p10).profile.roots()) == 1              # 自動の置き換えは無い
    after_retire = dataclasses.replace(revise, expected_head_revision_id=retired.revision_id,
                                       reviewed_at=T0 + 8 * HOUR)
    refused("AUTHORITY_WORLD_INVALID:TERMINAL_STATUS", apply_decision, after_retire, p10_root=p10)
    refused("INPUT_REJECTED:AUTHORITY_ROOT_NOT_FOUND", apply_decision,
            dataclasses.replace(revise, profile_id="p10prf_" + "0" * 24), p10_root=p10)
    refused("INPUT_REJECTED:EXPECTED_HEAD_NOT_IN_CHAIN", apply_decision,
            dataclasses.replace(revise, expected_head_revision_id="p10prv_" + "0" * 24), p10_root=p10)
    assert apply_decision(profile_create(at=T0 + 9 * HOUR), p10_root=p10).status is ExecutionStatus.APPENDED


def test_a_c_input_is_validated_before_any_revision_is_built_and_nothing_is_written(world) -> None:
    p10 = world["p10"]
    before = tree(p10)
    for over in (dict(horizon_note="\ud800"), dict(author_ref="human:\ud800"),
                 dict(excluded_issuer_ids=("p8iss_\ud800",), exclusion_reason_note="r")):
        error = refused("INPUT_REJECTED:UNENCODABLE_TEXT", apply_decision, profile_create(**over), p10_root=p10)
        assert "\ud800" not in str(error) and MARKER not in str(error)                   # 文を返さない
        assert dry_run_decision(profile_create(**over), p10_root=p10).refusal == "INPUT_REJECTED:UNENCODABLE_TEXT"
    refused("INPUT_REJECTED:UNENCODABLE_TEXT", apply_decision,
            AttentionCreate(target_kind=WATCH_KIND, target_root_id="p9wat_\ud800", observed_p9_revision_id="x",
                            state=FOCUS, author_ref=AUTHOR, reviewed_at=T0), p10_root=p10, p9_root=world["root"])
    from datetime import datetime
    for decision, code in ((profile_create(at=datetime(2026, 7, 1, 9)), "INPUT_REJECTED:INSTANT_NOT_AWARE"),
                           (profile_create(author_ref="llm:model"), "INPUT_REJECTED:AUTHOR_NOT_HUMAN"),
                           (profile_create(review_lookahead_days=91), "INPUT_REJECTED:INVALID_REVIEW_LOOKAHEAD_DAYS"),
                           (profile_create(review_lookahead_days=True),
                            "INPUT_REJECTED:INVALID_REVIEW_LOOKAHEAD_DAYS"),
                           (profile_create(excluded_issuer_ids=(ISSUER, ISSUER), exclusion_reason_note="r"),
                            "INPUT_REJECTED:DUPLICATE_EXCLUDED_ISSUER"),
                           (profile_create(excluded_issuer_ids=[ISSUER], exclusion_reason_note="r"),
                            "INPUT_REJECTED:INVALID_LIST:excluded_issuer_ids"),
                           (profile_create(operation="PROFILE_REVISE"), "INPUT_REJECTED:OPERATION_MISMATCH"),
                           (object(), "INPUT_REJECTED:UNKNOWN_DECISION")):
        refused(code, apply_decision, decision, p10_root=p10)
    assert tree(p10) == before


def test_a_d_the_executor_never_initializes_or_repairs_a_layout(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    refused("STORE_UNAVAILABLE:STORE_MISSING:AUTHORITY_DIR_MISSING", apply_decision, profile_create(), p10_root=fresh)
    result = dry_run_decision(profile_create(), p10_root=fresh)
    assert result.status is DryRunStatus.WOULD_BE_REJECTED and list(fresh.iterdir()) == []
    (fresh / store_io.PERSONAL_DIRNAME).mkdir()
    (fresh / store_io.PERSONAL_DIRNAME / store_io.PROFILE_FILENAME).write_bytes(b"")
    refused("STORE_UNAVAILABLE:STORE_MISSING:STORE_MISSING", apply_decision, profile_create(), p10_root=fresh)
    assert [p.name for p in (fresh / store_io.PERSONAL_DIRNAME).iterdir()] == [store_io.PROFILE_FILENAME]


# ================================================ Attention ・P9 の検査


def test_b_a_attention_create_transitions_clear_re_add_and_reuse(world) -> None:
    p10, p9 = world["p10"], world["root"]
    create = focus_w1(world)
    assert dry_run_decision(create, p10_root=p10, p9_root=p9).status is DryRunStatus.VALID
    made = apply_decision(create, p10_root=p10, p9_root=p9)
    assert made.status is ExecutionStatus.APPENDED and made.root_id.startswith("p10att_")
    assert apply_decision(create, p10_root=p10, p9_root=p9).status is ExecutionStatus.REUSED
    on_thesis = AttentionCreate(target_kind=THESIS_KIND, target_root_id=world["t1"].thesis_id,
                                observed_p9_revision_id=world["t1"].revision_id, state=MUTE, author_ref=AUTHOR,
                                reviewed_at=T0 + 4 * HOUR)
    assert apply_decision(on_thesis, p10_root=p10, p9_root=p9).status is ExecutionStatus.APPENDED
    head = made.revision_id
    for state, hour in ((MUTE, 5), (FOCUS, 6), (CLEARED, 7)):
        step = AttentionTransition(attention_id=made.root_id, expected_head_revision_id=head,
                                   observed_p9_revision_id=world["w1b"].revision_id, state=state, author_ref=AUTHOR,
                                   reviewed_at=T0 + hour * HOUR)
        receipt = apply_decision(step, p10_root=p10, p9_root=p9)
        assert receipt.status is ExecutionStatus.APPENDED
        head = receipt.revision_id
    refused("AUTHORITY_WORLD_INVALID:TERMINAL_STATE", apply_decision,
            dataclasses.replace(step, expected_head_revision_id=head, state=FOCUS, reviewed_at=T0 + 8 * HOUR),
            p10_root=p10, p9_root=p9)
    re_add = focus_w1(world, at=T0 + 8 * HOUR, state=MUTE)                           # 付け直しは新しい root
    assert apply_decision(re_add, p10_root=p10, p9_root=p9).root_id != made.root_id
    refused("INPUT_REJECTED:INVALID_INITIAL_REVISION", apply_decision,
            focus_w1(world, at=T0 + 9 * HOUR, state=CLEARED), p10_root=p10, p9_root=p9)
    assert not hasattr(dm, "AttentionCorrection") and "ATTENTION_CORRECTION" not in dm.DECISION_FIELDS


def test_b_b_duplicate_live_target_and_stale_head_are_refused(world) -> None:
    p10, p9 = world["p10"], world["root"]
    made = apply_decision(focus_w1(world), p10_root=p10, p9_root=p9)
    before = tree(p10)
    refused("AUTHORITY_WORLD_INVALID:DUPLICATE_LIVE_ATTENTION", apply_decision,
            focus_w1(world, at=T0 + 5 * HOUR, state=MUTE), p10_root=p10, p9_root=p9)
    to_mute = AttentionTransition(attention_id=made.root_id, expected_head_revision_id=made.revision_id,
                                  observed_p9_revision_id=world["w1b"].revision_id, state=MUTE, author_ref=AUTHOR,
                                  reviewed_at=T0 + 5 * HOUR)
    assert tree(p10) == before
    apply_decision(to_mute, p10_root=p10, p9_root=p9)
    refused("STALE_AUTHORITY_HEAD", apply_decision, dataclasses.replace(to_mute, state=CLEARED), p10_root=p10,
            p9_root=p9)
    refused("AUTHORITY_WORLD_INVALID:ILLEGAL_TRANSITION", apply_decision,
            dataclasses.replace(to_mute, expected_head_revision_id=apply_decision(
                to_mute, p10_root=p10, p9_root=p9).revision_id, reviewed_at=T0 + 6 * HOUR), p10_root=p10, p9_root=p9)


def test_b_c_p9_validation_requires_the_exact_visible_revision_of_that_target_at_reviewed_at(world) -> None:
    p10, p9 = world["p10"], world["root"]
    before = tree(p10)
    refused("P9_TARGET_ABSENT", apply_decision,
            AttentionCreate(target_kind=WATCH_KIND, target_root_id="p9wat_" + "0" * 24,
                            observed_p9_revision_id=world["w1b"].revision_id, state=FOCUS, author_ref=AUTHOR,
                            reviewed_at=T0 + 4 * HOUR), p10_root=p10, p9_root=p9)
    refused("P9_TARGET_ABSENT", apply_decision,                                       # まだ見えない対象
            AttentionCreate(target_kind=WATCH_KIND, target_root_id=world["w2"].watch_entry_id,
                            observed_p9_revision_id=world["w2"].revision_id, state=FOCUS, author_ref=AUTHOR,
                            reviewed_at=T0 + timedelta(minutes=30)), p10_root=p10, p9_root=p9)
    refused("P9_TARGET_KIND_MISMATCH", apply_decision,
            AttentionCreate(target_kind=THESIS_KIND, target_root_id=world["w1"].watch_entry_id,
                            observed_p9_revision_id=world["w1b"].revision_id, state=FOCUS, author_ref=AUTHOR,
                            reviewed_at=T0 + 4 * HOUR), p10_root=p10, p9_root=p9)
    refused("P9_REVISION_STALE_OR_MISMATCH", apply_decision, focus_w1(world, observed=world["w1"].revision_id),
            p10_root=p10, p9_root=p9)                                                # 古い非先頭は受けない
    refused("P9_REVISION_STALE_OR_MISMATCH", apply_decision, focus_w1(world, observed=world["t1"].revision_id),
            p10_root=p10, p9_root=p9)                                                # 他の対象の revision
    refused("P9_REVISION_STALE_OR_MISMATCH", apply_decision,                          # その時点では W1 が先頭
            focus_w1(world, at=T0 + 2 * HOUR), p10_root=p10, p9_root=p9)
    assert apply_decision(focus_w1(world, at=T0 + 2 * HOUR, observed=world["w1"].revision_id), p10_root=p10,
                          p9_root=p9).status is ExecutionStatus.APPENDED             # その時点の先頭なら可
    refused("INPUT_REJECTED:P9_ROOT_REQUIRED", apply_decision, focus_w1(world), p10_root=p10)
    refused("P9_UNAVAILABLE:P9_STORE_UNAVAILABLE", apply_decision, focus_w1(world), p10_root=p10,
            p9_root=world["tmp"] / "absent")
    refused("INPUT_REJECTED:AUTHOR_NOT_HUMAN", apply_decision,
            dataclasses.replace(focus_w1(world), author_ref="system:x"), p10_root=p10, p9_root=p9)
    assert len(tree(p10)) == len(before)


def test_b_d_revise_refreshes_provenance_to_a_newer_p9_head_without_changing_state(tmp_path: Path, monkeypatch) -> None:
    p9 = build_p9(tmp_path / "p9")
    stores = P9AuthorityStores.open(p9["root"])
    w1c = watch_next(p9["w1b"], P9ChangeKind.REVISE, reviewed_at=T0 + 6 * HOUR, review_due_on=D1)
    stores.append_watch(w1c)
    p10 = tmp_path / "p10"
    p10.mkdir()
    PersonalAuthorityStores.initialize(p10)
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _trap)
    made = apply_decision(focus_w1(p9), p10_root=p10, p9_root=p9["root"])
    revise = AttentionRevise(attention_id=made.root_id, expected_head_revision_id=made.revision_id,
                             observed_p9_revision_id=p9["w1b"].revision_id, author_ref=AUTHOR,
                             reviewed_at=T0 + 7 * HOUR)
    refused("P9_REVISION_STALE_OR_MISMATCH", apply_decision, revise, p10_root=p10, p9_root=p9["root"])
    refreshed = apply_decision(dataclasses.replace(revise, observed_p9_revision_id=w1c.revision_id), p10_root=p10,
                               p9_root=p9["root"])
    head = PersonalAuthorityStores.open(p10).attention.chain(made.root_id)[-1]
    assert refreshed.status is ExecutionStatus.APPENDED and head.state is FOCUS
    assert head.observed_p9_revision_id == w1c.revision_id and head.change_kind.value == "REVISE"
    assert dry_run_decision(dataclasses.replace(revise, observed_p9_revision_id=w1c.revision_id), p10_root=p10,
                            p9_root=p9["root"]).status is DryRunStatus.WOULD_REUSE
