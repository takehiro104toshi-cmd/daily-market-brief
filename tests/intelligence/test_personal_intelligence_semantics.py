"""P10-A2 — Personal Profile ／ Attention の純な意味の model の test（合成の id だけ ・file の入出力なし ・時計なし）。"""
from __future__ import annotations

import builtins
import dataclasses
import socket
from datetime import datetime, timedelta, timezone

import pytest

from src.intelligence.personal_intelligence import attention_model as am
from src.intelligence.personal_intelligence import cross_rules as cr
from src.intelligence.personal_intelligence import profile_model as pm
from src.intelligence.personal_intelligence import revision_model as rm
from src.intelligence.personal_intelligence.attention_model import (AttentionRevision, AttentionState,
                                                                    AttentionTargetKind, derive_attention_id,
                                                                    validate_attention_chain)
from src.intelligence.personal_intelligence.cross_rules import check_personal_snapshot, check_personal_world
from src.intelligence.personal_intelligence.profile_model import (PersonalProfileRevision, ProfileStatus,
                                                                  canonical_excluded_issuer_ids, derive_profile_id,
                                                                  validate_profile_chain)
from src.intelligence.personal_intelligence.revision_model import (ChangeKind, PersonalModelError, revision_at_seq,
                                                                   state_at, states_at)
from src.intelligence.watchlist_thesis_intelligence import revision_model as p9_rm
from src.intelligence.watchlist_thesis_intelligence import thesis_model as p9_tm
from src.intelligence.watchlist_thesis_intelligence import watch_model as p9_wm
from tests.intelligence.test_watchlist_thesis_semantics import (HOUR, ISSUER, ISSUER2, T0, thesis_create,
                                                                watch_create, watch_next)

AUTHOR = "human:reviewer"
WATCH = watch_create()                                                           # 合成の P9 の記録（凍結 P9 の型で作る）
WATCH_B = watch_next(WATCH, p9_rm.ChangeKind.REVISE, reviewed_at=T0 + HOUR)
WATCH2 = watch_create(issuer=ISSUER2, at=T0 + HOUR)
THESIS = thesis_create(WATCH)
BASE = dict(horizon_note="long term, roughly 10 years", liquidity_note="", risk_context_note="",
            review_lookahead_days=14, excluded_issuer_ids=(), exclusion_reason_note="")
NO_EXTRA = dict(retirement_reason="", corrects_revision_id="", correction_reason="")
FORBIDDEN_SCHEMA_TOKENS = ("score", "suitability", "risk_category", "expected_return", "target_return", "target_price",
                           "allocation", "weight", "position", "buy", "sell", "rebalance", "recommend", "rating",
                           "conviction", "holding", "portfolio", "rank", "priority", "urgency", "importance")


def fails(code: str, fn, *args, **kwargs) -> PersonalModelError:
    with pytest.raises(PersonalModelError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


def profile_create(at: datetime = T0, author: str = AUTHOR, **over) -> PersonalProfileRevision:
    fields = dict(BASE, **over)
    return PersonalProfileRevision(profile_id=derive_profile_id(author_ref=author, reviewed_at=at), seq=1,
                                   prev_revision_id="", change_kind=ChangeKind.CREATE, status=ProfileStatus.ACTIVE,
                                   author_ref=author, reviewed_at=at, **fields)


def profile_next(prev: PersonalProfileRevision, kind: ChangeKind, *, at: datetime, **over) -> PersonalProfileRevision:
    return dataclasses.replace(prev, **dict(NO_EXTRA, seq=prev.seq + 1, prev_revision_id=prev.revision_id,
                                            change_kind=kind, reviewed_at=at, **over))


def retire(prev: PersonalProfileRevision, at: datetime) -> PersonalProfileRevision:
    return profile_next(prev, ChangeKind.TRANSITION, at=at, status=ProfileStatus.RETIRED,
                        retirement_reason="starting over with a new profile")


def attention_create(state: AttentionState = AttentionState.FOCUS, at: datetime = T0, p9=WATCH,
                     kind: AttentionTargetKind = AttentionTargetKind.P9_WATCH_ENTRY) -> AttentionRevision:
    target = p9.watch_entry_id if kind is AttentionTargetKind.P9_WATCH_ENTRY else p9.thesis_id
    return AttentionRevision(attention_id=derive_attention_id(target_kind=kind, target_root_id=target,
                                                              author_ref=AUTHOR, reviewed_at=at),
                             seq=1, prev_revision_id="", change_kind=ChangeKind.CREATE, target_kind=kind,
                             target_root_id=target, observed_p9_revision_id=p9.revision_id, state=state,
                             author_ref=AUTHOR, reviewed_at=at)


def attention_next(prev: AttentionRevision, kind: ChangeKind, state: AttentionState = None, *, at: datetime,
                   **over) -> AttentionRevision:
    return dataclasses.replace(prev, seq=prev.seq + 1, prev_revision_id=prev.revision_id, change_kind=kind,
                               state=state or prev.state, reviewed_at=at, **over)


@pytest.fixture(autouse=True)
def pure(monkeypatch):
    """純な model: file ・network ・credential を使わない（使えば落ちる）。"""
    def trap(*_args, **_kwargs):
        raise AssertionError("TRAPPED: io / network")
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", trap)
    monkeypatch.setattr(socket.socket, "connect", trap)
    yield
    monkeypatch.setattr(builtins, "open", builtins.open)


# ================================================ 共通の revision ・Phase 9 の構文の一致


def test_a_a_phase9_reference_syntax_and_author_rule_are_parity_pinned_to_frozen_p9() -> None:
    assert rm.P9_ISSUER_ID_PREFIX + "_" + "a" * 24 == ISSUER and p9_rm.is_issuer_id(ISSUER)
    assert rm.P9_WATCH_ENTRY_ID_PREFIX == p9_wm.WATCH_ENTRY_ID_PREFIX
    assert rm.P9_WATCH_REVISION_ID_PREFIX == p9_wm.WATCH_REVISION_ID_PREFIX
    assert rm.P9_THESIS_ID_PREFIX == p9_tm.THESIS_ID_PREFIX
    assert rm.P9_THESIS_REVISION_ID_PREFIX == p9_tm.THESIS_REVISION_ID_PREFIX
    assert rm.id_pattern("x").pattern == p9_rm.id_pattern("x").pattern
    assert rm.CREDENTIAL_MARKERS == p9_rm.CREDENTIAL_MARKERS
    for author in ("human:reviewer", "human:a.b@c", "human:", "llm:model", "system", "human:my-token", "HUMAN:x",
                   "human:" + "a" * 114, "human:" + "a" * 115, 7, None):
        p9_ok = p10_ok = True
        try:
            p9_rm.check_author(author)
        except p9_rm.SemanticModelError:
            p9_ok = False
        try:
            rm.check_author(author)
        except PersonalModelError:
            p10_ok = False
        assert p9_ok == p10_ok, author
    for p9_record, prefix in ((WATCH, rm.P9_WATCH_REVISION_ID_PREFIX), (THESIS, rm.P9_THESIS_REVISION_ID_PREFIX)):
        assert p9_record.revision_id.startswith(prefix + "_")
    assert {k.value for k in ChangeKind} == {"CREATE", "REVISE", "CORRECTION", "TRANSITION"}


def test_a_b_point_in_time_helpers_use_seq_and_reviewed_at_not_input_order() -> None:
    p1 = profile_create()
    p2 = profile_next(p1, ChangeKind.REVISE, at=T0 + HOUR, review_lookahead_days=30)
    p3 = profile_next(p2, ChangeKind.REVISE, at=T0 + HOUR, horizon_note="I want to review this every 30 days")
    chain = validate_profile_chain([p3, p1, p2])
    assert chain == (p1, p2, p3)
    assert state_at(chain, T0 - timedelta(seconds=1)) is None                     # 前
    assert state_at(chain, T0) == p1                                              # ちょうど
    assert state_at(chain, T0 + HOUR) == p3                                       # 同じ瞬間は最大の seq
    assert state_at(chain, T0 + 10 * HOUR) == p3                                  # 後
    assert revision_at_seq(chain, 2) == p2
    fails("SEQ_NOT_FOUND", revision_at_seq, chain, 4)
    fails("INVALID_SEQ", revision_at_seq, chain, 0)
    fails("INSTANT_NOT_AWARE", state_at, chain, datetime(2026, 7, 1, 9, 0))
    assert states_at({p1.profile_id: chain}, T0 - HOUR) == {}
    assert states_at({p1.profile_id: chain}, T0) == {p1.profile_id: p1}


# ================================================ Profile


def test_b_a_profile_create_revise_correction_retire_is_valid_and_ids_are_deterministic() -> None:
    p1 = profile_create(liquidity_note="I do not want concentrated positions")
    assert p1.profile_id.startswith("p10prf_") and p1.revision_id.startswith("p10prv_")
    assert profile_create(liquidity_note="I do not want concentrated positions") == p1
    assert profile_create(liquidity_note="I do not want concentrated positions").revision_id == p1.revision_id
    same_instant = T0.astimezone(timezone.utc)
    assert profile_create(at=same_instant, liquidity_note="I do not want concentrated positions").revision_id == \
        p1.revision_id                                                            # 瞬間は UTC で正準化
    p2 = profile_next(p1, ChangeKind.REVISE, at=T0 + HOUR, excluded_issuer_ids=(ISSUER,),
                      exclusion_reason_note="personal reasons")
    p3 = profile_next(p2, ChangeKind.CORRECTION, at=T0 + 2 * HOUR, excluded_issuer_ids=(ISSUER, ISSUER2),
                      corrects_revision_id=p2.revision_id, correction_reason="the second one was missing")
    p4 = profile_next(p3, ChangeKind.REVISE, at=T0 + 3 * HOUR)                    # 同じ内容の REVISE も有効
    p5 = retire(p4, T0 + 4 * HOUR)
    chain = validate_profile_chain([p1, p2, p3, p4, p5])
    assert [r.status for r in chain] == [ProfileStatus.ACTIVE] * 4 + [ProfileStatus.RETIRED]
    assert p4.content() == p3.content() and p5.content() == p4.content()          # 種類は差を意味しない
    assert state_at(chain, T0 + HOUR + timedelta(minutes=30)) == p2               # 訂正の前の時点は記録のまま
    assert len({r.revision_id for r in chain}) == 5
    for name, value in (("horizon_note", "x"), ("review_lookahead_days", 15), ("excluded_issuer_ids", (ISSUER2,)),
                        ("author_ref", "human:other")):
        changed = dataclasses.replace(p2, **{name: value, **({"exclusion_reason_note": "r"} if name ==
                                                              "excluded_issuer_ids" else {})})
        assert changed.revision_id != p2.revision_id, name
    assert p1.as_dict()["revision_id"] == p1.revision_id and p1.as_dict()["status"] == "ACTIVE"


def test_b_b_profile_state_machine_retired_is_terminal_and_kinds_are_enforced() -> None:
    p1 = profile_create()
    p2 = retire(p1, T0 + HOUR)
    fails("TERMINAL_STATUS", validate_profile_chain, [p1, p2, profile_next(p2, ChangeKind.REVISE, at=T0 + 2 * HOUR,
                                                                           status=ProfileStatus.RETIRED,
                                                                           retirement_reason="again")])
    fails("TERMINAL_STATUS", validate_profile_chain, [p1, p2, profile_next(p2, ChangeKind.TRANSITION,   # 復活なし
                                                                           at=T0 + 2 * HOUR,
                                                                           status=ProfileStatus.ACTIVE)])
    assert pm.PROFILE_TRANSITIONS[ProfileStatus.RETIRED] == ()
    fails("STATUS_CHANGE_REQUIRES_TRANSITION", validate_profile_chain,
          [p1, profile_next(p1, ChangeKind.REVISE, at=T0 + HOUR, status=ProfileStatus.RETIRED,
                            retirement_reason="r")])
    fails("TRANSITION_CHANGES_CONTENT", validate_profile_chain,
          [p1, profile_next(p1, ChangeKind.TRANSITION, at=T0 + HOUR, status=ProfileStatus.RETIRED,
                            retirement_reason="r", horizon_note="changed")])
    fails("ILLEGAL_TRANSITION", validate_profile_chain, [p1, profile_next(p1, ChangeKind.TRANSITION, at=T0 + HOUR)])
    fails("NOTE_REQUIRED", profile_next, p1, ChangeKind.TRANSITION, at=T0 + HOUR, status=ProfileStatus.RETIRED)
    fails("RETIREMENT_REASON_ONLY_FOR_RETIRED", profile_next, p1, ChangeKind.REVISE, at=T0 + HOUR,
          retirement_reason="r")
    fails("INVALID_INITIAL_REVISION", dataclasses.replace, p1, status=ProfileStatus.RETIRED, retirement_reason="r")
    fails("INVALID_INITIAL_REVISION", dataclasses.replace, p1, change_kind=ChangeKind.REVISE)
    fails("PROFILE_ID_MISMATCH", dataclasses.replace, p1, author_ref="human:other")
    # CORRECTION: 同じ鎖の既存の revision だけ ・理由つき ・他の種類は訂正の欄を持たない
    fails("CORRECTION_TARGET_UNKNOWN", validate_profile_chain,
          [p1, profile_next(p1, ChangeKind.CORRECTION, at=T0 + HOUR, corrects_revision_id="p10prv_" + "0" * 24,
                            correction_reason="r")])
    fails("NOTE_REQUIRED", profile_next, p1, ChangeKind.CORRECTION, at=T0 + HOUR,
          corrects_revision_id=p1.revision_id)
    fails("CORRECTION_FIELDS_UNEXPECTED", profile_next, p1, ChangeKind.REVISE, at=T0 + HOUR,
          corrects_revision_id=p1.revision_id, correction_reason="r")


def test_b_c_profile_chain_linkage_monotonic_review_and_human_author() -> None:
    p1 = profile_create()
    p2 = profile_next(p1, ChangeKind.REVISE, at=T0 + HOUR)
    fails("REVIEWED_AT_REGRESSED", validate_profile_chain, [p1, profile_next(p1, ChangeKind.REVISE,
                                                                             at=T0 - HOUR)])
    fails("SEQ_NOT_CONSECUTIVE", validate_profile_chain, [p1, dataclasses.replace(p2, seq=3)])
    fails("PREV_REVISION_MISMATCH", validate_profile_chain,
          [p1, dataclasses.replace(p2, prev_revision_id="p10prv_" + "0" * 24)])
    fails("INVALID_PREV_REVISION_ID", dataclasses.replace, p2, prev_revision_id="")
    fails("DUPLICATE_REVISION", validate_profile_chain, [p1, p2, p2])
    fails("EMPTY_CHAIN", validate_profile_chain, [])
    fails("INVALID_INITIAL_REVISION", validate_profile_chain, [p2])
    other = profile_create(at=T0 + HOUR)
    fails("ROOT_MISMATCH", validate_profile_chain, [p1, dataclasses.replace(other, seq=2, change_kind=ChangeKind.REVISE,
                                                                            prev_revision_id=p1.revision_id)])
    for author in ("llm:model", "system:x", "human:", "reviewer", "human:api_key_x"):
        with pytest.raises(PersonalModelError) as exc:
            profile_create(author=author)
        assert exc.value.code in ("AUTHOR_NOT_HUMAN", "CREDENTIAL_LIKE_TEXT")
    fails("INSTANT_NOT_AWARE", profile_create, at=datetime(2026, 7, 1, 9, 0))


def test_b_d_profile_lookahead_bounds_exclusions_and_notes() -> None:
    assert (pm.REVIEW_LOOKAHEAD_MIN_DAYS, pm.REVIEW_LOOKAHEAD_MAX_DAYS) == (0, 90)
    for days in (0, 1, 90):
        assert profile_create(review_lookahead_days=days).review_lookahead_days == days
    for days in (-1, 91, 365, True, 7.0, "7", None):
        fails("INVALID_REVIEW_LOOKAHEAD_DAYS", profile_create, review_lookahead_days=days)
    assert canonical_excluded_issuer_ids([ISSUER2, ISSUER]) == (ISSUER, ISSUER2)
    fails("DUPLICATE_EXCLUDED_ISSUER", canonical_excluded_issuer_ids, [ISSUER, ISSUER])
    fails("INVALID_EXCLUDED_ISSUER_IDS", canonical_excluded_issuer_ids, ["7203"])
    fails("INVALID_EXCLUDED_ISSUER_IDS", canonical_excluded_issuer_ids, [WATCH.watch_entry_id])
    fails("EXCLUDED_ISSUER_IDS_NOT_CANONICAL", profile_create, excluded_issuer_ids=(ISSUER2, ISSUER),
          exclusion_reason_note="r")
    fails("DUPLICATE_EXCLUDED_ISSUER", profile_create, excluded_issuer_ids=(ISSUER, ISSUER), exclusion_reason_note="r")
    fails("INVALID_EXCLUDED_ISSUER_IDS", profile_create, excluded_issuer_ids=[ISSUER], exclusion_reason_note="r")
    fails("INVALID_EXCLUDED_ISSUER_IDS", profile_create,
          excluded_issuer_ids=tuple(sorted(f"p8iss_{i:024x}" for i in range(pm.MAX_EXCLUDED_ISSUERS + 1))),
          exclusion_reason_note="r")
    fails("NOTE_REQUIRED", profile_create, excluded_issuer_ids=(ISSUER,))
    fails("EXCLUSION_REASON_WITHOUT_EXCLUSION", profile_create, exclusion_reason_note="orphan")
    # 普通の文の数字 ・語は有効（文は解釈しない）。制御文字 ・credential らしい文 ・長さ ・型だけを拒む
    for note in ("long term, roughly 10 years", "I want to review this every 30 days",
                 "I do not want concentrated positions", "長期で 10 年くらい\n二行目", ""):
        assert profile_create(horizon_note=note, risk_context_note=note).horizon_note == note
    fails("CONTROL_CHARACTER", profile_create, horizon_note="a\x00b")
    fails("CREDENTIAL_LIKE_TEXT", profile_create, risk_context_note="my password is here")
    fails("INVALID_NOTE", profile_create, liquidity_note="x" * (rm.MAX_NOTE_LEN + 1))
    fails("INVALID_NOTE", profile_create, liquidity_note="   ")
    fails("NOTE_NOT_STRING", profile_create, horizon_note=10)


def test_b_e_the_typed_profile_schema_cannot_hold_scores_allocations_or_trade_concepts() -> None:
    fields = {f.name for f in dataclasses.fields(PersonalProfileRevision)}
    assert fields == {"profile_id", "seq", "prev_revision_id", "change_kind", "status", *pm.PROFILE_CONTENT_FIELDS,
                      "author_ref", "reviewed_at", "retirement_reason", "corrects_revision_id", "correction_reason",
                      "authority_class", "rules_version", "schema_version"}
    assert pm.PROFILE_CONTENT_FIELDS == ("horizon_note", "liquidity_note", "risk_context_note",
                                         "review_lookahead_days", "excluded_issuer_ids", "exclusion_reason_note")
    for name in fields | {f.name for f in dataclasses.fields(AttentionRevision)}:
        assert not any(token in name for token in FORBIDDEN_SCHEMA_TOKENS), name
    numeric = {f.name for f in dataclasses.fields(PersonalProfileRevision) if f.type in ("int", "float")}
    assert numeric == {"seq", "review_lookahead_days"}                             # 数の authority は窓の日数だけ
    for extra in ("risk_score", "suitability_score", "risk_category", "expected_return", "target_return",
                  "target_price", "allocation", "weight", "position_size", "buy", "sell", "rebalance",
                  "recommendation", "rating", "conviction", "holdings", "portfolio"):
        with pytest.raises(TypeError):
            profile_create(**{extra: 1})
    fails("AUTHORITY_CLASS_MISMATCH", dataclasses.replace, profile_create(), authority_class="RECOMMENDATION")
    fails("SCHEMA_MISMATCH", dataclasses.replace, profile_create(), schema_version="x")
    fails("RULES_VERSION_MISMATCH", dataclasses.replace, profile_create(), rules_version="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile_create().horizon_note = "x"


# ================================================ Attention


def test_c_a_attention_focus_mute_transitions_and_cleared_is_terminal() -> None:
    focus = attention_create()
    assert focus.attention_id.startswith("p10att_") and focus.revision_id.startswith("p10arv_")
    assert attention_create(AttentionState.MUTE).state is AttentionState.MUTE
    fails("INVALID_INITIAL_REVISION", attention_create, AttentionState.CLEARED)
    a2 = attention_next(focus, ChangeKind.TRANSITION, AttentionState.MUTE, at=T0 + HOUR)
    a3 = attention_next(a2, ChangeKind.TRANSITION, AttentionState.FOCUS, at=T0 + 2 * HOUR)
    a4 = attention_next(a3, ChangeKind.REVISE, at=T0 + 3 * HOUR,                  # 後の P9 の revision を見て改める
                        observed_p9_revision_id=WATCH_B.revision_id)
    a5 = attention_next(a4, ChangeKind.TRANSITION, AttentionState.CLEARED, at=T0 + 4 * HOUR)
    chain = validate_attention_chain([a5, a3, focus, a4, a2])
    assert [r.state for r in chain] == [AttentionState.FOCUS, AttentionState.MUTE, AttentionState.FOCUS,
                                        AttentionState.FOCUS, AttentionState.CLEARED]
    assert state_at(chain, T0 - HOUR) is None and state_at(chain, T0 + HOUR) == a2
    assert state_at(chain, T0 + 3 * HOUR + timedelta(minutes=1)) == a4 and state_at(chain, T0 + 9 * HOUR) == a5
    fails("TERMINAL_STATE", validate_attention_chain,
          [*chain, attention_next(a5, ChangeKind.TRANSITION, AttentionState.FOCUS, at=T0 + 5 * HOUR)])
    assert am.ATTENTION_TRANSITIONS[AttentionState.CLEARED] == ()
    fails("STATE_CHANGE_REQUIRES_TRANSITION", validate_attention_chain,
          [focus, attention_next(focus, ChangeKind.REVISE, AttentionState.MUTE, at=T0 + HOUR)])
    fails("ILLEGAL_TRANSITION", validate_attention_chain,
          [focus, attention_next(focus, ChangeKind.TRANSITION, AttentionState.FOCUS, at=T0 + HOUR)])
    fails("CHANGE_KIND_NOT_SUPPORTED", attention_next, focus, ChangeKind.CORRECTION, at=T0 + HOUR)
    fails("REVIEWED_AT_REGRESSED", validate_attention_chain,
          [focus, attention_next(focus, ChangeKind.REVISE, at=T0 - HOUR)])
    fails("SEQ_NOT_CONSECUTIVE", validate_attention_chain, [focus, dataclasses.replace(a2, seq=3)])
    fails("PREV_REVISION_MISMATCH", validate_attention_chain,
          [focus, dataclasses.replace(a2, prev_revision_id="p10arv_" + "0" * 24)])


def test_c_b_attention_target_is_one_p9_root_with_structural_syntax_only() -> None:
    on_thesis = attention_create(AttentionState.MUTE, p9=THESIS, kind=AttentionTargetKind.P9_THESIS)
    assert on_thesis.target_root_id == THESIS.thesis_id and on_thesis.observed_p9_revision_id == THESIS.revision_id
    focus = attention_create()
    fails("TARGET_CHANGED", validate_attention_chain,
          [focus, attention_next(focus, ChangeKind.REVISE, at=T0 + HOUR, target_root_id=WATCH2.watch_entry_id,
                                 observed_p9_revision_id=WATCH2.revision_id)])
    fails("INVALID_TARGET_ROOT_ID", dataclasses.replace, focus, target_root_id=THESIS.thesis_id)   # 種類と構文の不一致
    fails("INVALID_TARGET_ROOT_ID", dataclasses.replace, focus, target_root_id=ISSUER)            # 発行体だけは無い
    fails("INVALID_OBSERVED_P9_REVISION_ID", dataclasses.replace, focus, observed_p9_revision_id=THESIS.revision_id)
    fails("INVALID_OBSERVED_P9_REVISION_ID", dataclasses.replace, focus, observed_p9_revision_id="")
    fails("INVALID_TARGET_KIND", dataclasses.replace, focus, target_kind="P9_WATCH_ENTRY")
    fails("INVALID_STATE", dataclasses.replace, focus, state="FOCUS")
    fails("ATTENTION_ID_MISMATCH", dataclasses.replace, focus, reviewed_at=T0 + HOUR)
    assert {s.value for s in AttentionState} == {"FOCUS", "MUTE", "CLEARED"}       # NORMAL は保存しない
    assert {k.value for k in AttentionTargetKind} == {"P9_WATCH_ENTRY", "P9_THESIS"}
    fields = {f.name: f.type for f in dataclasses.fields(AttentionRevision)}
    assert set(fields) == {"attention_id", "seq", "prev_revision_id", "change_kind", "target_kind", "target_root_id",
                           "observed_p9_revision_id", "state", "author_ref", "reviewed_at", "authority_class",
                           "rules_version", "schema_version"}                     # 自由文 ・数の重みは無い
    assert [n for n, t in fields.items() if t in ("int", "float")] == ["seq"]
    assert attention_create() == focus and attention_create().revision_id == focus.revision_id
    assert attention_create(at=T0.astimezone(timezone.utc)).revision_id == focus.revision_id
    assert attention_create(AttentionState.MUTE).attention_id == focus.attention_id   # root は状態に依らない
    assert attention_create(AttentionState.MUTE).revision_id != focus.revision_id


# ================================================ 記録をまたぐ規則


def test_d_a_at_most_one_active_profile_at_every_reviewed_instant() -> None:
    p1 = profile_create()
    p2 = profile_create(at=T0 + 2 * HOUR)
    fails("MULTIPLE_ACTIVE_PROFILES", check_personal_world, [p1, p2], [])
    r1 = retire(p1, T0 + HOUR)
    profiles, _ = check_personal_world([p2, r1, p1], [])                            # 退役 → 新しい root
    assert set(profiles) == {p1.profile_id, p2.profile_id} and p1.profile_id != p2.profile_id
    check_personal_world([p1, retire(p1, T0 + 2 * HOUR), p2], [])                    # 同じ瞬間の退役と作成は有効
    fails("MULTIPLE_ACTIVE_PROFILES", check_personal_world, [p1, retire(p1, T0 + 3 * HOUR), p2], [])   # 過去を壊す
    fails("MULTIPLE_ACTIVE_PROFILES", check_personal_snapshot, {p1.profile_id: (p1,), p2.profile_id: (p2,)}, {},
          T0 + 2 * HOUR)
    check_personal_snapshot({p1.profile_id: (p1,), p2.profile_id: (p2,)}, {}, T0 + HOUR)


def test_d_b_at_most_one_live_attention_per_p9_target_and_re_add_after_clear() -> None:
    focus = attention_create()
    mute_same = attention_create(AttentionState.MUTE, at=T0 + HOUR)
    fails("DUPLICATE_LIVE_ATTENTION", check_personal_world, [], [focus, mute_same])   # FOCUS と MUTE は同時に無い
    fails("DUPLICATE_LIVE_ATTENTION", check_personal_world, [], [focus, attention_create(at=T0 + HOUR)])
    cleared = attention_next(focus, ChangeKind.TRANSITION, AttentionState.CLEARED, at=T0 + HOUR)
    _, chains = check_personal_world([], [focus, cleared, mute_same])                # 消した後の付け直しは新しい root
    assert set(chains) == {focus.attention_id, mute_same.attention_id}
    early = attention_create(AttentionState.MUTE, at=T0 + timedelta(minutes=30))
    fails("DUPLICATE_LIVE_ATTENTION", check_personal_world, [], [focus, cleared, early])
    other = attention_create(AttentionState.MUTE, p9=WATCH2)
    on_thesis = attention_create(AttentionState.MUTE, p9=THESIS, kind=AttentionTargetKind.P9_THESIS)
    check_personal_world([], [focus, other, on_thesis])                                 # 対象が違えば独立
    fails("INVALID_REVISIONS", check_personal_world, [], {focus})
    fails("INVALID_REVISION", check_personal_world, [focus], [])
    fails("INVALID_REVISION", check_personal_world, [], [profile_create()])


def test_d_c_profile_exclusion_with_focus_or_mute_is_valid_and_nothing_is_inferred() -> None:
    profile = profile_create(excluded_issuer_ids=(WATCH.issuer_id,), exclusion_reason_note="personal constraint")
    focus = attention_create()                                                       # 除外した発行体の Watchlist の項目
    mute = attention_create(AttentionState.MUTE, p9=THESIS, kind=AttentionTargetKind.P9_THESIS)
    profiles, attention = check_personal_world([profile], [focus, mute])
    assert profiles == {profile.profile_id: (profile,)}
    assert attention == {focus.attention_id: (focus,), mute.attention_id: (mute,)}  # 消さない ・拒まない ・変えない
    assert check_personal_world([profile], [mute, focus]) == (profiles, attention)   # 入力の順に依らない
    assert check_personal_world([profile], []) == (profiles, {})                     # 除外から印を導かない
    assert check_personal_world([], [focus]) == ({}, {focus.attention_id: (focus,)})  # 印から profile を導かない
    assert cr.__all__ == ["AttentionChains", "ProfileChains", "check_personal_snapshot", "check_personal_world"]
    assert "issuer_id" not in {f.name for f in dataclasses.fields(AttentionRevision)}


def test_d_d_the_models_are_pure_no_file_io_during_construction_validation_or_world_checks(monkeypatch) -> None:
    def trap(*_args, **_kwargs):
        raise AssertionError("TRAPPED: file io")
    monkeypatch.setattr(builtins, "open", trap)
    p1 = profile_create(excluded_issuer_ids=(ISSUER,), exclusion_reason_note="r")
    a1 = attention_create()
    a2 = attention_next(a1, ChangeKind.TRANSITION, AttentionState.MUTE, at=T0 + HOUR)
    check_personal_world([p1, retire(p1, T0 + HOUR)], [a1, a2])
    assert p1.as_dict() == p1.as_dict() and a2.revision_id == a2.revision_id
