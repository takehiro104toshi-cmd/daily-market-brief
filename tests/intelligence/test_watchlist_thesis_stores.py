"""P9-A3 — Watchlist ／ Thesis の private な authority の store の test（合成だけ ・実 root ・network なし）。

pin するもの: 正準の直列化 ／ 復元 ・追記専用（APPENDED ／ REUSED）・破損 ／ 切断 ／ 非正準 ／ 重複 ／ 鎖の誤りは fail closed ・鎖の先頭の
検査 ・記録をまたぐ不変条件は追記の前に検査 ・連鎖の書き込みなし ・外部の変更の検出 ・fsync ・時点の状態 ・削除 ／ 上書き ／ 最新の API なし。
"""
from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.watchlist_thesis_intelligence import serialization as se
from src.intelligence.watchlist_thesis_intelligence import store_io
from src.intelligence.watchlist_thesis_intelligence.authority_stores import AuthorityStores
from src.intelligence.watchlist_thesis_intelligence.revision_model import ChangeKind, SemanticModelError
from src.intelligence.watchlist_thesis_intelligence.store_io import (AppendStatus, AuthorityStoreError,
                                                                     StoreFailureCategory)
from src.intelligence.watchlist_thesis_intelligence.thesis_model import (HumanNoteEvidence, InvalidationBasis,
                                                                          ThesisStatus)
from src.intelligence.watchlist_thesis_intelligence.thesis_store import THESIS_FILENAME, ThesisStore
from src.intelligence.watchlist_thesis_intelligence.watch_model import P8ProposalProvenance, WatchStatus
from src.intelligence.watchlist_thesis_intelligence.watch_store import WATCHLIST_FILENAME, WatchlistStore
from tests.intelligence.test_watchlist_thesis_semantics import (AUTHOR, DUE, HOUR, ISSUER, ISSUER2, JST, RUN, SRS, T0,
                                                                thesis_create, thesis_next, watch_create, watch_next)

C = StoreFailureCategory
P8_PROVENANCE = P8ProposalProvenance(run_id=RUN, screen_result_id=SRS, policy_id="p8pol_" + "3" * 24,
                                     policy_version=1, universe_id="p8uni_" + "4" * 24, universe_version=2,
                                     authority_day=date(2026, 6, 30), proposal_digest="p9prp_" + "5" * 24)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "p9_private_root"
    path.mkdir()
    return path


def watch_file(root: Path) -> Path:
    return root / "watchlist_thesis_intelligence" / WATCHLIST_FILENAME


def thesis_file(root: Path) -> Path:
    return root / "watchlist_thesis_intelligence" / THESIS_FILENAME


def store_fails(category: StoreFailureCategory, code: str, fn, *args, **kwargs) -> AuthorityStoreError:
    with pytest.raises(AuthorityStoreError) as exc:
        fn(*args, **kwargs)
    assert (exc.value.category, exc.value.code) == (category, code), (exc.value.category, exc.value.code)
    return exc.value


def model_fails(code: str, fn, *args) -> None:
    with pytest.raises(SemanticModelError) as exc:
        fn(*args)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)


def full_thesis_chain():
    w = watch_create()
    t1 = thesis_create(w)
    t2 = thesis_next(t1, ChangeKind.CORRECTION, statement="corrected statement", corrects_revision_id=t1.revision_id,
                     correction_reason="typo")
    t3 = thesis_next(t2, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED,
                     invalidation_basis=InvalidationBasis.CONDITIONS,
                     invalidated_condition_ids=(t1.invalidation_conditions[1].condition_id,),
                     corrects_revision_id="", correction_reason="")
    return w, (t1, t2, t3)


# ================================================ A 正準の直列化 ／ 復元


def test_a_a_every_authority_type_round_trips_with_identical_ids() -> None:
    w, thesis = full_thesis_chain()
    watches = [w, watch_create(issuer=ISSUER2, provenance=P8_PROVENANCE),
               watch_next(w, ChangeKind.TRANSITION, WatchStatus.REMOVED)]
    for revision in watches:
        line = se.watch_line(revision)
        back = se.watch_from_dict(json.loads(line))
        assert back == revision and back.revision_id == revision.revision_id and se.watch_line(back) == line
    for revision in thesis:
        line = se.thesis_line(revision)
        back = se.thesis_from_dict(json.loads(line))
        assert back == revision and back.revision_id == revision.revision_id and se.thesis_line(back) == line
    assert se.watch_line(w) == se.watch_line(watch_create())                          # 決定論


def test_a_b_unknown_missing_enum_id_instant_and_date_errors_are_rejected_without_defaults() -> None:
    base = json.loads(se.watch_line(watch_create()))
    cases = [({**base, "extra": 1}, "UNKNOWN_FIELD"),
             ({k: v for k, v in base.items() if k != "rationale"}, "MISSING_FIELD"),
             ({**base, "status": "WATCHING"}, "INVALID_ENUM"),
             ({**base, "issuer_id": "p8iss_xyz"}, "INVALID_ISSUER_ID"),
             ({**base, "reviewed_at": "2026-07-01T00:00:00"}, "INSTANT_NOT_AWARE"),
             ({**base, "reviewed_at": "2026-07-01T09:00:00+09:00"}, "NON_CANONICAL_INSTANT"),
             ({**base, "review_due_on": "2026-10-1"}, "INVALID_DATE"),
             ({**base, "seq": True}, "INVALID_INTEGER"),
             ({**base, "provenance": {"kind": "MANUAL", "note": "x"}}, "UNKNOWN_FIELD"),
             ({**base, "revision_id": "p9wrv_" + "0" * 24}, "REVISION_ID_MISMATCH"),
             ({**base, "author_ref": "system:auto"}, "AUTHOR_NOT_HUMAN")]
    for data, code in cases:
        model_fails(code, se.watch_from_dict, data)
    thesis = json.loads(se.thesis_line(thesis_create(watch_create())))
    model_fails("UNKNOWN_FIELD", se.thesis_from_dict, {**thesis, "score": 1})
    model_fails("INVALID_ENUM", se.thesis_from_dict, {**thesis, "supporting_evidence": [{"kind": "RUMOR"}]})
    model_fails("INVALID_ENUM", se.thesis_from_dict, {**thesis, "invalidation_basis": "MAYBE"})


# ================================================ B Watchlist の store


def test_b_a_append_reuse_and_reload(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    assert watch_file(root).read_bytes() == b"" and thesis_file(root).read_bytes() == b""
    w = watch_create()
    assert stores.append_watch(w).status is AppendStatus.APPENDED
    before = watch_file(root).read_bytes()
    assert stores.append_watch(w).status is AppendStatus.REUSED and watch_file(root).read_bytes() == before
    assert before == (se.watch_line(w) + "\n").encode("utf-8")
    reopened = AuthorityStores.open(root)
    assert reopened.watch.revision(w.revision_id) == w and reopened.watch.roots() == (w.watch_entry_id,)
    assert reopened.watch.revision_at_seq(w.watch_entry_id, 1) == w
    store_fails(C.APPEND_REJECTED, "INVALID_REVISION", stores.append_watch, thesis_create(w))


def test_b_b_chain_head_seq_prev_regression_and_terminal_rules_are_enforced_on_append(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w1 = watch_create()
    stores.append_watch(w1)
    store_fails(C.APPEND_REJECTED, "CHAIN_HEAD_MISMATCH", stores.append_watch,
                watch_create(rationale="a second create for the same root"))              # 同じ root の 2 つ目の作成
    w2 = watch_next(w1, ChangeKind.REVISE, rationale="second")
    stores.append_watch(w2)
    stale = watch_next(w1, ChangeKind.REVISE, rationale="built on an old head")
    store_fails(C.APPEND_REJECTED, "CHAIN_HEAD_MISMATCH", stores.append_watch, stale)
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:REVIEWED_AT_REGRESSED", stores.append_watch,
                watch_next(w2, ChangeKind.REVISE, rationale="third", reviewed_at=w2.reviewed_at - 3 * HOUR))
    store_fails(C.APPEND_REJECTED, "ROOT_NOT_FOUND", stores.append_watch,
                watch_next(watch_create(issuer=ISSUER2), ChangeKind.REVISE))
    removed = watch_next(w2, ChangeKind.TRANSITION, WatchStatus.REMOVED)
    stores.append_watch(removed)
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:TERMINAL_STATUS", stores.append_watch,
                watch_next(removed, ChangeKind.TRANSITION, WatchStatus.ACTIVE))
    readd = watch_create(at=removed.reviewed_at + HOUR)
    assert stores.append_watch(readd).status is AppendStatus.APPENDED                # 再追加は新しい root
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:DUPLICATE_LIVE_WATCH_ENTRY", stores.append_watch,
                watch_create(at=readd.reviewed_at + HOUR, rationale="a second live entry"))


@pytest.mark.parametrize("damage,code", [
    (lambda data: data + b"not json\n", "MALFORMED_JSON"),
    (lambda data: data[:-1], "TRUNCATED_FINAL_LINE"),
    (lambda data: data + data, "DUPLICATE_REVISION"),
    (lambda data: data + b"\n", "BLANK_LINE"),
    (lambda data: b"\xff" + data, "INVALID_ENCODING"),
    (lambda data: (json.dumps(json.loads(data), sort_keys=False, indent=1).replace("\n", "") + "\n").encode(),
     "NON_CANONICAL_LINE"),
])
def test_b_c_corruption_fails_closed_and_is_never_repaired(root: Path, damage, code: str) -> None:
    AuthorityStores.initialize(root).append_watch(watch_create())
    path = watch_file(root)
    path.write_bytes(damage(path.read_bytes()))
    damaged = path.read_bytes()
    store_fails(C.STORE_CORRUPTION, code, AuthorityStores.open, root)
    store_fails(C.STORE_CORRUPTION, code, WatchlistStore.open, root)
    assert path.read_bytes() == damaged                                               # 修復 ・切り詰めなし


def test_b_d_raw_written_broken_chains_and_duplicate_live_issuers_fail_on_load(root: Path) -> None:
    AuthorityStores.initialize(root)
    w1 = watch_create()
    gap = watch_next(watch_next(w1, ChangeKind.REVISE, rationale="b"), ChangeKind.REVISE, rationale="c")
    watch_file(root).write_text(se.watch_line(w1) + "\n" + se.watch_line(gap) + "\n", encoding="utf-8")
    error = store_fails(C.STORE_CORRUPTION, "CHAIN_INVALID:SEQ_NOT_CONSECUTIVE", WatchlistStore.open, root)
    assert error.detail == w1.watch_entry_id
    twin = watch_create(at=T0 + HOUR, rationale="twin")
    watch_file(root).write_text(se.watch_line(w1) + "\n" + se.watch_line(twin) + "\n", encoding="utf-8")
    store_fails(C.STORE_CORRUPTION, "DUPLICATE_LIVE_WATCH_ENTRY", WatchlistStore.open, root)


def test_b_e_point_in_time_requires_an_explicit_aware_instant(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w1 = watch_create()
    w2 = watch_next(w1, ChangeKind.TRANSITION, WatchStatus.PAUSED)
    w3 = watch_next(w2, ChangeKind.TRANSITION, WatchStatus.ACTIVE)
    for revision in (w1, w2, w3):
        stores.append_watch(revision)
    store = WatchlistStore.open(root)
    root_id = w1.watch_entry_id
    assert store.state_at(root_id, T0 - HOUR) is None and store.state_at(root_id, T0) == w1
    assert store.state_at(root_id, T0 + HOUR + timedelta(minutes=30)) == w2 and store.state_at(root_id, T0 + 5 * HOUR) == w3
    assert store.states_at(T0 + HOUR) == {root_id: w2}
    assert store.chain(root_id) == (w1, w2, w3) and store.revision_at_seq(root_id, 2) == w2
    assert store.revision_at_seq(root_id, 9) is None and store.revision("p9wrv_" + "0" * 24) is None
    model_fails("INSTANT_NOT_AWARE", store.state_at, root_id, datetime(2026, 7, 1, 12, 0))
    store_fails(C.STORE_MISSING, "ROOT_NOT_FOUND", store.chain, "p9wat_" + "0" * 24)


# ================================================ C Thesis の store


def test_c_a_thesis_append_reuse_conditions_terminal_and_pit(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w, (t1, t2, t3) = full_thesis_chain()
    stores.append_watch(w)
    for revision in (t1, t2, t3):
        assert stores.append_thesis(revision).status is AppendStatus.APPENDED
    assert stores.append_thesis(t2).status is AppendStatus.REUSED
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:TERMINAL_STATUS", stores.append_thesis,
                thesis_next(t3, ChangeKind.TRANSITION, ThesisStatus.ACTIVE, invalidation_basis=None,
                            invalidated_condition_ids=()))
    thesis = ThesisStore.open(root)
    assert thesis.chain(t1.thesis_id) == (t1, t2, t3) and thesis.state_at(t1.thesis_id, t2.reviewed_at) == t2
    # 条件を消した後、その条件で無効にする追記は拒む（直前の revision の既知の条件だけ）
    w2 = watch_create(issuer=ISSUER2, at=T0 + 10 * HOUR)
    stores.append_watch(w2)
    u1 = thesis_create(w2)
    pruned = thesis_next(u1, ChangeKind.REVISE, invalidation_conditions=u1.invalidation_conditions[1:])
    stores.append_thesis(u1)
    stores.append_thesis(pruned)
    sneaky = thesis_next(pruned, ChangeKind.TRANSITION, ThesisStatus.INVALIDATED,
                         invalidation_basis=InvalidationBasis.CONDITIONS,
                         invalidation_conditions=u1.invalidation_conditions,
                         invalidated_condition_ids=(u1.invalidation_conditions[0].condition_id,))
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:UNKNOWN_CONDITION_REF", stores.append_thesis, sneaky)


def test_c_b_thesis_corruption_and_broken_chains_fail_closed(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w, (t1, t2, _) = full_thesis_chain()
    stores.append_watch(w)
    stores.append_thesis(t1)
    path = thesis_file(root)
    path.write_bytes(path.read_bytes()[:-3])
    store_fails(C.STORE_CORRUPTION, "TRUNCATED_FINAL_LINE", ThesisStore.open, root)
    path.write_text(se.thesis_line(t2) + "\n", encoding="utf-8")                     # seq 2 だけ（先頭が無い）
    store_fails(C.STORE_CORRUPTION, "CHAIN_INVALID:INVALID_INITIAL_REVISION", ThesisStore.open, root)


# ================================================ D 記録をまたぐ不変条件（追記の前 ・連鎖の書き込みなし）


def test_d_a_thesis_without_watch_wrong_issuer_and_after_removal_are_rejected(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w = watch_create()
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:THESIS_WITHOUT_WATCH_ENTRY", stores.append_thesis, thesis_create(w))
    stores.append_watch(w)
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:THESIS_WITHOUT_WATCH_ENTRY", stores.append_thesis,
                thesis_create(w, at=T0 - HOUR))                                        # 項目より前
    removed = watch_next(w, ChangeKind.TRANSITION, WatchStatus.REMOVED)
    stores.append_watch(removed)
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:LIVE_THESIS_ON_REMOVED_WATCH_ENTRY", stores.append_thesis,
                thesis_create(w, at=removed.reviewed_at + HOUR))


def test_d_b_removal_is_rejected_while_a_thesis_is_live_and_allowed_after_it_ends(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w = watch_create()
    t1 = thesis_create(w)
    stores.append_watch(w)
    stores.append_thesis(t1)
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:LIVE_THESIS_ON_REMOVED_WATCH_ENTRY", stores.append_watch,
                watch_next(w, ChangeKind.TRANSITION, WatchStatus.REMOVED, reviewed_at=t1.reviewed_at + HOUR))
    retired = thesis_next(t1, ChangeKind.TRANSITION, ThesisStatus.RETIRED)
    stores.append_thesis(retired)
    after = watch_next(w, ChangeKind.TRANSITION, WatchStatus.REMOVED, reviewed_at=retired.reviewed_at + HOUR)
    assert stores.append_watch(after).status is AppendStatus.APPENDED


def test_d_c_declared_thesis_index_is_validated_and_no_write_cascades(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w = watch_create()
    stores.append_watch(w)
    store_fails(C.APPEND_REJECTED, "WORLD_INVALID:DECLARED_THESIS_LINK_INVALID", stores.append_watch,
                watch_next(w, ChangeKind.REVISE, thesis_ids=("p9ths_" + "0" * 24,)))
    watch_before = watch_file(root).read_bytes()
    t1 = thesis_create(w)
    stores.append_thesis(t1)
    assert watch_file(root).read_bytes() == watch_before                             # thesis の追記は Watchlist を書かない
    thesis_before = thesis_file(root).read_bytes()
    stores.append_watch(watch_next(w, ChangeKind.REVISE, thesis_ids=(t1.thesis_id,), reviewed_at=t1.reviewed_at + HOUR))
    assert thesis_file(root).read_bytes() == thesis_before                           # 逆も同じ
    AuthorityStores.open(root)                                                        # 世界は全体として正しい


def test_d_d_a_raw_written_cross_store_violation_fails_on_open(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w = watch_create()
    stores.append_watch(w)
    thesis_file(root).write_text(se.thesis_line(thesis_create(w, at=T0 - HOUR)) + "\n", encoding="utf-8")
    store_fails(C.STORE_CORRUPTION, "WORLD_INVALID:THESIS_WITHOUT_WATCH_ENTRY", AuthorityStores.open, root)


# ================================================ E file の安全 ・境界


def test_e_a_external_modification_of_either_store_is_detected_before_append(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w = watch_create()
    stores.append_watch(w)
    other = AuthorityStores.open(root)
    other.append_watch(watch_create(issuer=ISSUER2, at=T0 + HOUR))                  # 別の書き手
    store_fails(C.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", stores.append_watch,
                watch_next(w, ChangeKind.REVISE, rationale="late writer"))
    fresh = AuthorityStores.open(root)
    fresh.append_watch(watch_next(w, ChangeKind.REVISE, rationale="fine"))
    thesis_file(root).write_text(se.thesis_line(thesis_create(w)) + "\n", encoding="utf-8")
    store_fails(C.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", fresh.append_watch,
                watch_next(fresh.watch.chain(w.watch_entry_id)[-1], ChangeKind.REVISE, rationale="x"))


def test_e_b_append_flushes_and_fsyncs(root: Path, monkeypatch) -> None:
    calls = []
    real = store_io.os.fsync
    monkeypatch.setattr(store_io.os, "fsync", lambda fd: (calls.append(fd), real(fd)))
    stores = AuthorityStores.initialize(root)
    stores.append_watch(watch_create())
    assert len(calls) == 1
    stores.append_watch(watch_create())                                              # REUSED は書かない
    assert len(calls) == 1


def test_e_c_root_must_be_explicit_absolute_and_existing(tmp_path: Path) -> None:
    store_fails(C.STORE_MISSING, "ROOT_NOT_ABSOLUTE", AuthorityStores.initialize, "relative/root")
    store_fails(C.STORE_MISSING, "P9_ROOT_MISSING", AuthorityStores.initialize, tmp_path / "missing")
    assert not (tmp_path / "missing").exists()
    (tmp_path / "empty").mkdir()
    store_fails(C.STORE_MISSING, "STORE_MISSING", AuthorityStores.open, tmp_path / "empty")
    assert list((tmp_path / "empty").iterdir()) == []                                # open は作らない


def test_e_d_no_delete_overwrite_repair_or_implicit_latest_api() -> None:
    forbidden = ("delete", "remove", "repair", "truncate", "overwrite", "rewrite", "compact", "latest", "current",
                 "now", "today", "head", "update", "migrate")
    for cls in (WatchlistStore, ThesisStore, AuthorityStores, store_io.RevisionStore):
        public = {name for name in dir(cls) if not name.startswith("_")}
        assert not {n for n in public if any(word in n for word in forbidden)}, cls
    assert {n for n in dir(AuthorityStores) if n.startswith("append")} == {"append_thesis", "append_watch"}
    assert not any(n.startswith("append") for n in dir(WatchlistStore) if not n.startswith("_"))
    assert not any(n.startswith("append") for n in dir(ThesisStore) if not n.startswith("_"))


def test_e_e_mixed_offsets_compare_by_instant(root: Path) -> None:
    stores = AuthorityStores.initialize(root)
    w = watch_create()                                                               # JST の 09:00
    stores.append_watch(w)
    nxt = watch_next(w, ChangeKind.REVISE, rationale="same instant in UTC",
                     reviewed_at=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc))      # 同じ瞬間（非減少）
    assert stores.append_watch(nxt).status is AppendStatus.APPENDED
    assert AuthorityStores.open(root).watch.chain(w.watch_entry_id)[-1] == nxt
