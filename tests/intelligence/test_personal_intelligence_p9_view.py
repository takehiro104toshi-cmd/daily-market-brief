"""P10-A1 — 凍結の Phase 9 の read-only の adapter の test（合成の P9 の root だけ ・network なし ・書き込みなし）。"""
from __future__ import annotations

import dataclasses
import http.client
import socket
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.personal_intelligence import p9_view as pv
from src.intelligence.personal_intelligence.p9_view import (P9PrivateSnapshot, P9SafeView, P9ViewError,
                                                            read_p9_private_snapshot, read_p9_safe_view)
from src.intelligence.watchlist_thesis_intelligence import serialization as se
from src.intelligence.watchlist_thesis_intelligence import store_io
from src.intelligence.watchlist_thesis_intelligence.authority_stores import AuthorityStores
from src.intelligence.watchlist_thesis_intelligence.revision_model import ChangeKind
from src.intelligence.watchlist_thesis_intelligence.thesis_model import ThesisStatus
from src.intelligence.watchlist_thesis_intelligence.watch_model import WatchStatus
from tests.intelligence.test_watchlist_thesis_semantics import (DUE, HOUR, ISSUER, ISSUER2, T0, thesis_create,
                                                                thesis_next, watch_create, watch_next)

UTC = timezone.utc


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED: network / write path")


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


@pytest.fixture
def traps(monkeypatch):
    """読み込みの間だけ: credential なし ・socket ／ HTTP ・P9 の store の作成 ／ 追記 ・`AuthorityStores` を罠にする。"""
    def arm() -> None:
        monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
        monkeypatch.setattr(socket, "create_connection", _trap)
        monkeypatch.setattr(socket.socket, "connect", _trap)
        monkeypatch.setattr(http.client.HTTPConnection, "__init__", _trap)
        monkeypatch.setattr(http.client.HTTPSConnection, "__init__", _trap)
        monkeypatch.setattr(store_io.RevisionStore, "initialize", classmethod(_trap))
        monkeypatch.setattr(store_io.RevisionStore, "_append_line", _trap)
        monkeypatch.setattr(store_io, "initialize_file", _trap)
        monkeypatch.setattr(AuthorityStores, "__init__", _trap)                      # P10 は使わない
    return arm


@pytest.fixture
def world(tmp_path: Path):
    """合成の P9 の世界: 2 つの Watchlist の項目（1 つは PAUSED へ）と 1 つの Thesis（CHALLENGED へ）。"""
    root = tmp_path / "p9_private_root"
    root.mkdir()
    stores = AuthorityStores.initialize(root)
    w1 = watch_create()
    w2 = watch_create(issuer=ISSUER2, at=T0 + HOUR)
    t1 = thesis_create(w1, at=T0 + 2 * HOUR)
    w1b = watch_next(w1, ChangeKind.TRANSITION, WatchStatus.PAUSED, reviewed_at=T0 + 3 * HOUR, review_due_on=None)
    t1b = thesis_next(t1, ChangeKind.TRANSITION, ThesisStatus.CHALLENGED, reviewed_at=T0 + 4 * HOUR)
    for revision in (w1, w2):
        stores.append_watch(revision)
    stores.append_thesis(t1)
    stores.append_watch(w1b)
    stores.append_thesis(t1b)
    return dict(root=root, w1=w1, w2=w2, t1=t1, w1b=w1b, t1b=t1b)


def fails(code: str, fn, *args, **kwargs) -> P9ViewError:
    with pytest.raises(P9ViewError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


def _walk(value, seen=None):
    """返り値の中の全ての値（dataclass ・tuple を辿る）。"""
    yield value
    if dataclasses.is_dataclass(value):
        for field in dataclasses.fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _walk(item)


ALLOWED_LEAF_TYPES = (str, int, date, type(None))


def _only_immutable_values(value) -> None:
    for item in _walk(value):
        if dataclasses.is_dataclass(item):
            assert type(item).__dataclass_params__.frozen, type(item)
            assert type(item).__module__ == pv.__name__, type(item)                 # P10 が持つ型だけ（P9 の型を返さない）
        else:
            assert isinstance(item, (tuple,) + ALLOWED_LEAF_TYPES), type(item)
            assert not isinstance(item, (store_io.RevisionStore, AuthorityStores)), type(item)


# ================================================ A 安全な view（既定 ・件数だけ）


def test_a_a_safe_view_reuses_the_frozen_projection_as_immutable_counts(world, traps) -> None:
    before = snapshot(world["root"])
    traps()
    view = read_p9_safe_view(world["root"], at=T0 + 5 * HOUR, as_of_date=DUE)
    assert isinstance(view, P9SafeView) and view.as_of_date == DUE
    assert view.watch_count == 2 and dict(view.watch_status_counts) == {"ACTIVE": 1, "PAUSED": 1}
    assert dict(view.watch_provenance_kind_counts) == {"MANUAL": 2}
    assert view.thesis_count == 1 and dict(view.thesis_status_counts) == {"CHALLENGED": 1}
    assert view.watch_review_due_count == 1 and view.thesis_review_due_count == 1
    assert view == read_p9_safe_view(world["root"], at=T0 + 5 * HOUR, as_of_date=DUE)    # 決定論
    _only_immutable_values(view)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.watch_count = 9
    text = repr(view)
    for leak in (ISSUER, ISSUER2, world["w1"].watch_entry_id, world["t1"].thesis_id, world["w1"].rationale,
                 world["t1"].statement, "p8iss_", "p9wat_", "p9ths_", "p9wrv_", "p9trv_", "human:"):
        assert leak not in text, leak
    assert snapshot(world["root"]) == before                                         # 書かない


# ================================================ B private な snapshot（最小の欄 ・時点）


def test_b_a_private_snapshot_is_minimal_immutable_and_point_in_time(world, traps) -> None:
    traps()
    at_end = read_p9_private_snapshot(world["root"], at=T0 + 5 * HOUR)
    assert isinstance(at_end, P9PrivateSnapshot)
    by_root = {w.watch_entry_id: w for w in at_end.watch}
    first = by_root[world["w1"].watch_entry_id]
    assert (first.status, first.review_due_on, first.revision_id) == ("PAUSED", None, world["w1b"].revision_id)
    assert (first.issuer_id, first.provenance_kind) == (ISSUER, "MANUAL")
    assert by_root[world["w2"].watch_entry_id].status == "ACTIVE"
    (thesis,) = at_end.thesis
    assert (thesis.thesis_id, thesis.status, thesis.watch_entry_id, thesis.revision_id) == (
        world["t1"].thesis_id, "CHALLENGED", world["w1"].watch_entry_id, world["t1b"].revision_id)
    assert set(f.name for f in dataclasses.fields(pv.P9WatchState)) == {
        "watch_entry_id", "revision_id", "issuer_id", "status", "review_due_on", "provenance_kind"}
    assert set(f.name for f in dataclasses.fields(pv.P9ThesisState)) == {
        "thesis_id", "revision_id", "watch_entry_id", "status", "review_due_on"}       # 文 ・根拠 ・著者 ・瞬間なし
    _only_immutable_values(at_end)
    # 時点: 前 ・ちょうど ・後
    assert read_p9_private_snapshot(world["root"], at=T0 - HOUR) == P9PrivateSnapshot(watch=(), thesis=())
    at_create = read_p9_private_snapshot(world["root"], at=T0)
    assert [w.watch_entry_id for w in at_create.watch] == [world["w1"].watch_entry_id] and at_create.thesis == ()
    mid = read_p9_private_snapshot(world["root"], at=T0 + 2 * HOUR + timedelta(minutes=30))
    assert {w.status for w in mid.watch} == {"ACTIVE"} and mid.thesis[0].status == "ACTIVE"
    assert read_p9_private_snapshot(world["root"], at=(T0 + 3 * HOUR).astimezone(UTC)).watch[
        [w.watch_entry_id for w in mid.watch].index(world["w1"].watch_entry_id)].status == "PAUSED"
    assert read_p9_private_snapshot(world["root"], at=T0 + 5 * HOUR) == at_end   # 決定論


def test_b_b_explicit_instants_and_dates_are_required(world, traps) -> None:
    traps()
    fails("INSTANT_NOT_AWARE", read_p9_private_snapshot, world["root"], at=datetime(2026, 7, 1, 9, 0))
    fails("INSTANT_NOT_AWARE", read_p9_private_snapshot, world["root"], at=None)
    fails("INVALID_DATE", read_p9_safe_view, world["root"], at=T0, as_of_date=datetime(2026, 10, 1, tzinfo=UTC))
    fails("INVALID_DATE", read_p9_safe_view, world["root"], at=T0, as_of_date="2026-10-01")


# ================================================ C fail closed（作らない ・修復しない ・書かない）


def test_c_a_missing_root_and_missing_files_fail_closed_without_creating_anything(world, tmp_path: Path,
                                                                                    traps) -> None:
    traps()
    missing = tmp_path / "missing_root"
    fails("P9_STORE_UNAVAILABLE", read_p9_safe_view, missing, at=T0, as_of_date=DUE)
    assert not missing.exists()
    empty = tmp_path / "empty_root"
    empty.mkdir()
    fails("P9_STORE_UNAVAILABLE", read_p9_private_snapshot, empty, at=T0)
    assert list(empty.iterdir()) == []
    thesis_file = world["root"] / "watchlist_thesis_intelligence" / "thesis_authority.jsonl"
    thesis_file.unlink()
    before = snapshot(world["root"])
    error = fails("P9_STORE_UNAVAILABLE", read_p9_private_snapshot, world["root"], at=T0)
    assert error.detail == "STORE_MISSING:STORE_MISSING" and str(world["root"]) not in str(error)
    assert not thesis_file.exists() and snapshot(world["root"]) == before
    fails("P9_STORE_UNAVAILABLE", read_p9_safe_view, "relative/root", at=T0, as_of_date=DUE)


@pytest.mark.parametrize("name", ["watchlist_authority.jsonl", "thesis_authority.jsonl"])
def test_c_b_corrupt_stores_fail_closed_and_are_not_repaired(world, traps, name: str) -> None:
    path = world["root"] / "watchlist_thesis_intelligence" / name
    path.write_bytes(path.read_bytes() + b"not json\n")
    damaged = snapshot(world["root"])
    traps()
    error = fails("P9_STORE_UNAVAILABLE", read_p9_private_snapshot, world["root"], at=T0)
    assert error.detail == "STORE_CORRUPTION:MALFORMED_JSON"
    fails("P9_STORE_UNAVAILABLE", read_p9_safe_view, world["root"], at=T0, as_of_date=DUE)
    assert snapshot(world["root"]) == damaged


def test_c_c_an_invalid_cross_store_world_fails_closed_through_the_frozen_check(tmp_path: Path, traps) -> None:
    root = tmp_path / "p9_private_root"
    root.mkdir()
    stores = AuthorityStores.initialize(root)
    w = watch_create()
    stores.append_watch(w)
    early = thesis_create(w, at=T0 - HOUR)                                           # Watchlist の項目より前（世界の違反）
    thesis_file = root / "watchlist_thesis_intelligence" / "thesis_authority.jsonl"
    thesis_file.write_bytes((se.thesis_line(early) + "\n").encode("utf-8"))           # 各 store 単体は正しい
    before = snapshot(root)
    traps()
    error = fails("P9_WORLD_INVALID", read_p9_private_snapshot, root, at=T0 + HOUR)
    assert error.detail == "THESIS_WITHOUT_WATCH_ENTRY"
    fails("P9_WORLD_INVALID", read_p9_safe_view, root, at=T0 + HOUR, as_of_date=DUE)
    assert snapshot(root) == before


# ================================================ D store の object が外へ出ない ・追記 ／ 作成の面がない


def test_d_a_no_store_object_or_write_capable_surface_escapes(world, traps) -> None:
    traps()
    write_or_read_surfaces = ("initialize", "_append_line", "append_watch", "append_thesis", "open", "states_at",
                              "state_at", "chain", "all_revisions", "verify_unchanged")
    for value in (read_p9_safe_view(world["root"], at=T0 + 5 * HOUR, as_of_date=DUE),
                  read_p9_private_snapshot(world["root"], at=T0 + 5 * HOUR)):
        _only_immutable_values(value)
        for item in _walk(value):
            assert not any(hasattr(item, name) for name in write_or_read_surfaces), type(item)
    assert set(pv.__all__) == {
        "P9PrivateSnapshot", "P9SafeView", "P9ThesisState", "P9ViewError", "P9WatchState", "P9_VIEW_RULES_VERSION",
        "P9_VIEW_SCHEMA_VERSION", "PRIVATE_SNAPSHOT_CLASS", "SAFE_VIEW_CLASS", "read_p9_private_snapshot",
        "read_p9_safe_view"}                                                         # store ・世界の像は公開しない
    assert pv._ReadOnlyWorld.__slots__ == ("watch", "thesis")                         # 関数の中だけの像
