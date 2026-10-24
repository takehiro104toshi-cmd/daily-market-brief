"""P10-A3 — Personal Profile ／ Attention の private な追記専用の authority の store の test（合成の id ・tmp の root だけ）。"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import socket
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.personal_intelligence import serialization as se
from src.intelligence.personal_intelligence import store_io
from src.intelligence.personal_intelligence.attention_model import (AttentionRevision, AttentionState,
                                                                    AttentionTargetKind)
from src.intelligence.personal_intelligence.attention_store import AttentionStore
from src.intelligence.personal_intelligence.authority_stores import PersonalAuthorityStores
from src.intelligence.personal_intelligence.profile_model import PersonalProfileRevision, ProfileStatus
from src.intelligence.personal_intelligence.profile_store import ProfileStore
from src.intelligence.personal_intelligence.revision_model import ChangeKind, PersonalModelError, canonical_json
from src.intelligence.personal_intelligence.store_io import (AppendStatus, PersonalStoreError,
                                                             StoreFailureCategory as C)
from src.intelligence.watchlist_thesis_intelligence import store_io as p9_store_io
from src.intelligence.watchlist_thesis_intelligence.authority_stores import AuthorityStores as P9AuthorityStores
from tests.intelligence.test_personal_intelligence_semantics import (HOUR, T0, THESIS, WATCH, WATCH2,
                                                                     attention_create, attention_next, profile_create,
                                                                     profile_next, retire)

MARKER = "PRIVATE-NOTE-MARKER"
DIR = store_io.PERSONAL_DIRNAME


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED")


@pytest.fixture(autouse=True)
def guarded(monkeypatch):
    """network ・credential ・P9 の store を罠にし、filesystem の読み書きの path を記録する。"""
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _trap)
    monkeypatch.setattr(socket.socket, "connect", _trap)
    monkeypatch.setattr(p9_store_io.RevisionStore, "__init__", _trap)
    monkeypatch.setattr(p9_store_io, "initialize_file", _trap)
    monkeypatch.setattr(P9AuthorityStores, "__init__", _trap)
    touched = []
    for name in ("open", "read_bytes", "mkdir"):
        original = getattr(pathlib.Path, name)

        def wrapper(self, *args, __original=original, **kwargs):
            touched.append(Path(self))
            return __original(self, *args, **kwargs)
        monkeypatch.setattr(pathlib.Path, name, wrapper)
    return touched


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "p10_private_root"
    path.mkdir()
    return path


def tree(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): (p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
            for p in sorted(path.rglob("*"))}


def fails(category, code: str, fn, *args, **kwargs) -> PersonalStoreError:
    with pytest.raises(PersonalStoreError) as exc:
        fn(*args, **kwargs)
    assert (exc.value.category, exc.value.code) == (category, code), str(exc.value)
    return exc.value


def lines(root: Path, filename: str) -> list:
    return (root / DIR / filename).read_bytes().decode("utf-8").split("\n")


def write(root: Path, filename: str, data: bytes) -> None:
    (root / DIR).mkdir(exist_ok=True)
    for other in store_io.AUTHORITY_FILENAMES:
        if not (root / DIR / other).exists():
            (root / DIR / other).write_bytes(b"")
    (root / DIR / filename).write_bytes(data)


def line_bytes(*revisions) -> bytes:
    return b"".join(((se.profile_line(r) if isinstance(r, PersonalProfileRevision) else se.attention_line(r)) + "\n")
                    .encode("utf-8") for r in revisions)


# ================================================ 初期化 ・開く ・root の安全


def test_a_a_initialize_creates_exactly_the_directory_and_two_empty_files_once(root: Path, guarded) -> None:
    guarded.clear()                                                                   # fixture の準備は数えない
    stores = PersonalAuthorityStores.initialize(root)
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == [
        DIR, f"{DIR}/attention_authority.jsonl", f"{DIR}/profile_authority.jsonl"]
    assert (root / DIR / "profile_authority.jsonl").read_bytes() == b""
    assert stores.profile.roots() == () and stores.attention.roots() == ()
    stores.append_profile_revision(profile_create())
    before = tree(root)
    again = PersonalAuthorityStores.initialize(root)                                  # 既存の file には触れない
    assert tree(root) == before and len(again.profile.roots()) == 1
    (root / DIR / "attention_authority.jsonl").unlink()
    PersonalAuthorityStores.initialize(root)                                          # 無い file だけを作る
    assert tree(root)[f"{DIR}/profile_authority.jsonl"] == before[f"{DIR}/profile_authority.jsonl"]
    assert (root / DIR / "attention_authority.jsonl").read_bytes() == b""
    assert all(root in p.parents or p == root for p in guarded), guarded             # 明示の root の下だけ


def test_a_b_missing_root_and_rejected_roots_create_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    fails(C.STORE_MISSING, "P10_ROOT_MISSING", PersonalAuthorityStores.initialize, missing)
    fails(C.STORE_MISSING, "P10_ROOT_MISSING", PersonalAuthorityStores.open, missing)
    assert not missing.exists()
    for bad, code in (("relative/root", "ROOT_NOT_ABSOLUTE"), ("", "ROOT_REQUIRED"), (None, "ROOT_REQUIRED"),
                      (7, "ROOT_REQUIRED"), (str(tmp_path / "a" / ".." / "b"), "ROOT_TRAVERSAL"),
                      (str(tmp_path) + "\x00x", "ROOT_REQUIRED")):
        fails(C.ROOT_REJECTED, code, PersonalAuthorityStores.initialize, bad)
        fails(C.ROOT_REJECTED, code, PersonalAuthorityStores.open, bad)
    a_file = tmp_path / "file_root"
    a_file.write_bytes(b"x")
    fails(C.STORE_MISSING, "P10_ROOT_MISSING", PersonalAuthorityStores.initialize, a_file)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["file_root"]


def test_a_c_open_reads_existing_only_and_never_creates(root: Path) -> None:
    fails(C.STORE_MISSING, "AUTHORITY_DIR_MISSING", PersonalAuthorityStores.open, root)
    assert list(root.iterdir()) == []
    (root / DIR).mkdir()
    fails(C.STORE_MISSING, "STORE_MISSING", PersonalAuthorityStores.open, root)
    (root / DIR / "profile_authority.jsonl").write_bytes(b"")
    fails(C.STORE_MISSING, "STORE_MISSING", PersonalAuthorityStores.open, root)       # attention が無い
    fails(C.STORE_MISSING, "STORE_MISSING", AttentionStore.open, root)
    assert sorted(p.name for p in (root / DIR).iterdir()) == ["profile_authority.jsonl"]
    (root / DIR / "profile_authority.jsonl").unlink()
    (root / DIR / "attention_authority.jsonl").write_bytes(b"")
    fails(C.STORE_MISSING, "STORE_MISSING", ProfileStore.open, root)
    assert sorted(p.name for p in (root / DIR).iterdir()) == ["attention_authority.jsonl"]
    PersonalAuthorityStores.initialize(root).append_profile_revision(profile_create())
    before = tree(root)
    reopened = PersonalAuthorityStores.open(root)
    assert tree(root) == before and reopened.profile.all_revisions() == (profile_create(),)


def test_a_d_other_roots_and_lookalike_children_are_never_inferred_or_touched(tmp_path: Path, root: Path,
                                                                               guarded) -> None:
    for child in ("watchlist_thesis_intelligence", "screener_intelligence"):         # P9 ／ P8 らしい子
        (root / child).mkdir()
        (root / child / "watchlist_authority.jsonl").write_bytes(b"{}\n")
    sibling = tmp_path / "p9_private_root"
    sibling.mkdir()
    (sibling / "marker").write_bytes(b"m")
    outside = {k: v for k, v in tree(tmp_path).items() if not k.startswith(f"p10_private_root/{DIR}")
               and k != "p10_private_root"}                                           # root の mtime は子の作成で変わる
    guarded.clear()
    stores = PersonalAuthorityStores.initialize(root)
    stores.append_profile_revision(profile_create())
    PersonalAuthorityStores.open(root)
    used = list(guarded)
    assert used and all((root / DIR) in p.parents or p == root / DIR for p in used), used   # authority の下だけ
    assert {k: v for k, v in tree(tmp_path).items() if not k.startswith(f"p10_private_root/{DIR}")
            and k != "p10_private_root"} == outside
    nested = root / DIR                                                               # 名前が同じ root も推測しない
    PersonalAuthorityStores.initialize(nested)
    assert (nested / DIR / "profile_authority.jsonl").is_file()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_a_e_symlinked_root_directory_or_files_are_rejected(tmp_path: Path, root: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    try:
        (tmp_path / "linked_root").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not permitted")
    fails(C.ROOT_REJECTED, "ROOT_IS_SYMLINK", PersonalAuthorityStores.initialize, tmp_path / "linked_root")
    (root / DIR).symlink_to(target, target_is_directory=True)
    fails(C.ROOT_REJECTED, "AUTHORITY_DIR_UNSAFE", PersonalAuthorityStores.initialize, root)
    fails(C.ROOT_REJECTED, "AUTHORITY_DIR_UNSAFE", PersonalAuthorityStores.open, root)
    (root / DIR).unlink()
    (root / DIR).mkdir()
    (target / "x.jsonl").write_bytes(b"")
    (root / DIR / "profile_authority.jsonl").symlink_to(target / "x.jsonl")
    fails(C.ROOT_REJECTED, "AUTHORITY_FILE_UNSAFE", PersonalAuthorityStores.initialize, root)
    assert list(target.iterdir()) == [target / "x.jsonl"] and (target / "x.jsonl").read_bytes() == b""


# ================================================ 直列化 ・破損（fail closed ・修復なし）


def test_b_a_canonical_round_trip_and_exact_field_sets() -> None:
    profile = profile_create(excluded_issuer_ids=(WATCH.issuer_id,), exclusion_reason_note="長期の文脈")
    attention = attention_create()
    assert set(se.PROFILE_RECORD_FIELDS) == {f.name for f in dataclasses.fields(PersonalProfileRevision)} | {
        "revision_id"}
    assert set(se.ATTENTION_RECORD_FIELDS) == {f.name for f in dataclasses.fields(AttentionRevision)} | {
        "revision_id"}
    for revision, line_of, parse, fields in ((profile, se.profile_line, se.profile_from_record,
                                              se.PROFILE_RECORD_FIELDS),
                                             (attention, se.attention_line, se.attention_from_record,
                                              se.ATTENTION_RECORD_FIELDS)):
        line = line_of(revision)
        record = json.loads(line)
        assert canonical_json(record) == line and tuple(sorted(record)) == fields == tuple(sorted(fields))
        assert parse(record) == revision and record["revision_id"] == revision.revision_id
        assert record["reviewed_at"].endswith("+00:00")                               # UTC の ISO
        for bad, code in ((dict(record, extra=1), "UNKNOWN_FIELDS"),
                          ({k: v for k, v in record.items() if k != "author_ref"}, "MISSING_FIELDS"),
                          (dict(record, change_kind="create"), "INVALID_ENUM"),
                          (dict(record, reviewed_at=T0.isoformat()), "NON_CANONICAL_TIMESTAMP"),
                          (dict(record, reviewed_at="not-a-time"), "INVALID_TIMESTAMP"),
                          (dict(record, revision_id=revision.revision_id[:-1] + "0"
                                if not revision.revision_id.endswith("0") else revision.revision_id[:-1] + "1"),
                           "REVISION_ID_MISMATCH"),
                          (dict(record, author_ref=None), "INVALID_STRING"), ([record], "RECORD_NOT_OBJECT")):
            with pytest.raises(PersonalModelError) as exc:
                parse(bad)
            assert exc.value.code == code, (code, exc.value.code)
    with pytest.raises(PersonalModelError) as exc:
        se.profile_from_record(dict(json.loads(se.profile_line(profile)), excluded_issuer_ids=WATCH.issuer_id))
    assert exc.value.code == "INVALID_LIST"
    with pytest.raises(PersonalModelError) as exc:                                   # A2 は対の無い surrogate を通す
        se.profile_line(profile_create(horizon_note="\ud800"))
    assert exc.value.code == "UNENCODABLE_TEXT"


def _corrupt_cases():
    p1 = profile_create()
    p2 = profile_next(p1, ChangeKind.REVISE, at=T0 + HOUR)
    good = line_bytes(p1)
    record = json.loads(se.profile_line(p1))
    p1_twin = profile_create(horizon_note="a different create at the same instant")
    return [
        ("profile", b"\xff\xfe\n", "INVALID_ENCODING"),
        ("profile", b"{\n", "MALFORMED_JSON"),
        ("profile", good + b"\n", "BLANK_LINE"),
        ("profile", good[:-1], "MISSING_FINAL_NEWLINE"),
        ("profile", good[:-1] + b"\r\n", "NON_CANONICAL_LINE"),
        ("profile", (json.dumps(record) + "\n").encode("utf-8"), "NON_CANONICAL_LINE"),
        ("profile", (canonical_json(dict(record, revision_id="p10prv_" + "0" * 24)) + "\n").encode("utf-8"),
         "INVALID_RECORD:REVISION_ID_MISMATCH"),
        ("profile", good + good, "DUPLICATE_REVISION"),
        ("profile", line_bytes(p1, dataclasses.replace(p2, prev_revision_id="p10prv_" + "0" * 24)),
         "INVALID_AUTHORITY:PREV_REVISION_MISMATCH"),
        ("profile", line_bytes(p1, dataclasses.replace(p2, seq=3)), "INVALID_AUTHORITY:SEQ_NOT_CONSECUTIVE"),
        ("profile", line_bytes(p1, profile_next(p1, ChangeKind.REVISE, at=T0 - HOUR)),
         "INVALID_AUTHORITY:REVIEWED_AT_REGRESSED"),
        ("profile", line_bytes(p1, profile_next(p1, ChangeKind.TRANSITION, at=T0 + HOUR)),
         "INVALID_AUTHORITY:ILLEGAL_TRANSITION"),
        ("profile", line_bytes(p1, p1_twin), "INVALID_AUTHORITY:SEQ_NOT_CONSECUTIVE"),   # 同じ root の 2 つの作成
        ("profile", line_bytes(p1, profile_create(at=T0 + HOUR)), "INVALID_AUTHORITY:MULTIPLE_ACTIVE_PROFILES"),
        ("profile", line_bytes(p2, p1), None),                                       # 物理の順は authority ではない
        ("attention", line_bytes(attention_create(), attention_create(AttentionState.MUTE, at=T0 + HOUR)),
         "INVALID_AUTHORITY:DUPLICATE_LIVE_ATTENTION"),
        ("attention", line_bytes(attention_create(), dataclasses.replace(
            attention_next(attention_create(), ChangeKind.TRANSITION, AttentionState.CLEARED, at=T0 + HOUR)),
            attention_next(attention_next(attention_create(), ChangeKind.TRANSITION, AttentionState.CLEARED,
                                          at=T0 + HOUR), ChangeKind.TRANSITION, AttentionState.FOCUS,
                           at=T0 + 2 * HOUR)), "INVALID_AUTHORITY:TERMINAL_STATE"),
    ]


@pytest.mark.parametrize("kind,data,code", _corrupt_cases())
def test_b_b_every_corruption_fails_closed_without_repair(root: Path, kind: str, data: bytes, code) -> None:
    filename = store_io.PROFILE_FILENAME if kind == "profile" else store_io.ATTENTION_FILENAME
    write(root, filename, data)
    before = tree(root)
    if code is None:
        assert len(PersonalAuthorityStores.open(root).profile.roots()) == 1
        return
    error = fails(C.STORE_CORRUPTION, code, PersonalAuthorityStores.open, root)
    assert error.detail == kind
    fails(C.STORE_CORRUPTION, code, PersonalAuthorityStores.initialize, root)          # 初期化も修復しない
    assert tree(root) == before


# ================================================ Profile


def test_c_a_profile_appends_reuse_pit_and_rejections(root: Path) -> None:
    stores = PersonalAuthorityStores.initialize(root)
    p1 = profile_create(horizon_note=MARKER)
    p2 = profile_next(p1, ChangeKind.REVISE, at=T0 + HOUR, excluded_issuer_ids=(WATCH.issuer_id,),
                      exclusion_reason_note="personal constraint")
    p3 = profile_next(p2, ChangeKind.CORRECTION, at=T0 + 2 * HOUR, review_lookahead_days=30,
                      corrects_revision_id=p2.revision_id, correction_reason="the window was recorded wrong")
    p4 = retire(p3, T0 + 3 * HOUR)
    for revision in (p1, p2, p3, p4):
        assert stores.append_profile_revision(revision).status is AppendStatus.APPENDED
    path = root / DIR / store_io.PROFILE_FILENAME
    before = path.read_bytes()
    assert before.endswith(b"\n") and before.count(b"\n") == 4 and b"\r" not in before
    assert stores.append_profile_revision(p2).status is AppendStatus.REUSED          # 正確な再試行（先頭でなくても）
    assert stores.append_profile_revision(p4).revision_id == p4.revision_id and path.read_bytes() == before
    reopened = PersonalAuthorityStores.open(root).profile
    assert reopened.roots() == (p1.profile_id,) and reopened.chain(p1.profile_id) == (p1, p2, p3, p4)
    assert reopened.state_at(p1.profile_id, T0 - timedelta(seconds=1)) is None       # 前
    assert reopened.state_at(p1.profile_id, T0 + HOUR) == p2                          # ちょうど
    assert reopened.state_at(p1.profile_id, T0 + 9 * HOUR).status is ProfileStatus.RETIRED   # 後
    assert reopened.states_at(T0 + 2 * HOUR) == {p1.profile_id: p3}
    assert reopened.revision_at_seq(p1.profile_id, 3) == p3 and reopened.revision(p3.revision_id) == p3
    assert reopened.revision("p10prv_" + "0" * 24) is None
    fails(C.NOT_FOUND, "SEQ_NOT_FOUND", reopened.revision_at_seq, p1.profile_id, 9)
    fails(C.NOT_FOUND, "ROOT_NOT_FOUND", reopened.chain, "p10prf_" + "0" * 24)
    # 拒否（file は変わらない）
    fails(C.APPEND_REJECTED, "WORLD_INVALID:TERMINAL_STATUS", stores.append_profile_revision,
          profile_next(p4, ChangeKind.REVISE, at=T0 + 4 * HOUR, status=ProfileStatus.RETIRED, retirement_reason="r"))
    fails(C.APPEND_REJECTED, "CHAIN_HEAD_MISMATCH", stores.append_profile_revision,
          profile_next(p1, ChangeKind.REVISE, at=T0 + HOUR, horizon_note="a fork onto an old head"))
    fails(C.APPEND_REJECTED, "ROOT_NOT_FOUND", stores.append_profile_revision,
          profile_next(profile_create(at=T0 + 5 * HOUR), ChangeKind.REVISE, at=T0 + 6 * HOUR))
    fails(C.APPEND_REJECTED, "INVALID_REVISION", stores.append_profile_revision, attention_create())
    fails(C.APPEND_REJECTED, "INVALID_REVISION", stores.append_attention_revision, p1)
    fails(C.APPEND_REJECTED, "INVALID_REVISION", stores.append_profile_revision, json.loads(se.profile_line(p1)))
    assert path.read_bytes() == before
    second = profile_create(at=T0 + 3 * HOUR)                                        # 退役の後の新しい root
    assert stores.append_profile_revision(second).status is AppendStatus.APPENDED


def test_c_b_two_active_profiles_and_conflicting_lines_are_rejected(root: Path, monkeypatch) -> None:
    stores = PersonalAuthorityStores.initialize(root)
    p1 = profile_create()
    stores.append_profile_revision(p1)
    before = tree(root)
    fails(C.APPEND_REJECTED, "WORLD_INVALID:MULTIPLE_ACTIVE_PROFILES", stores.append_profile_revision,
          profile_create(at=T0 + HOUR))
    fails(C.APPEND_REJECTED, "UNENCODABLE_TEXT", stores.append_profile_revision,
          profile_next(p1, ChangeKind.REVISE, at=T0 + HOUR, horizon_note="\ud800"))
    monkeypatch.setattr(ProfileStore, "_line", staticmethod(lambda revision: se.profile_line(revision) + " "))
    fails(C.APPEND_REJECTED, "REVISION_CONFLICT", stores.append_profile_revision, p1)   # 同じ id ・違う行
    assert tree(root) == before


# ================================================ Attention


def test_d_a_attention_appends_transitions_clear_re_add_reuse_and_pit(root: Path) -> None:
    stores = PersonalAuthorityStores.initialize(root)
    focus = attention_create()
    mute_other = attention_create(AttentionState.MUTE, p9=WATCH2)
    to_mute = attention_next(focus, ChangeKind.TRANSITION, AttentionState.MUTE, at=T0 + HOUR)
    cleared = attention_next(to_mute, ChangeKind.TRANSITION, AttentionState.CLEARED, at=T0 + 2 * HOUR)
    re_add = attention_create(AttentionState.FOCUS, at=T0 + 3 * HOUR)
    for revision in (focus, mute_other, to_mute, cleared, re_add):
        assert stores.append_attention_revision(revision).status is AppendStatus.APPENDED
    assert stores.append_attention_revision(to_mute).status is AppendStatus.REUSED
    fails(C.APPEND_REJECTED, "WORLD_INVALID:DUPLICATE_LIVE_ATTENTION", stores.append_attention_revision,
          attention_create(AttentionState.MUTE, at=T0 + 4 * HOUR))                  # 同じ対象の 2 つ目の生きた印
    fails(C.APPEND_REJECTED, "WORLD_INVALID:TERMINAL_STATE", stores.append_attention_revision,
          attention_next(cleared, ChangeKind.TRANSITION, AttentionState.FOCUS, at=T0 + 4 * HOUR))
    store = PersonalAuthorityStores.open(root).attention
    assert store.roots() == tuple(sorted({focus.attention_id, mute_other.attention_id, re_add.attention_id}))
    assert store.state_at(focus.attention_id, T0 - HOUR) is None
    assert store.state_at(focus.attention_id, T0 + HOUR).state is AttentionState.MUTE
    assert store.state_at(focus.attention_id, T0 + 9 * HOUR).state is AttentionState.CLEARED
    live = {r.target_root_id: r.state for r in store.states_at(T0 + 9 * HOUR).values()
            if r.state is not AttentionState.CLEARED}
    assert live == {WATCH.watch_entry_id: AttentionState.FOCUS, WATCH2.watch_entry_id: AttentionState.MUTE}


def test_d_b_profile_exclusion_with_focus_or_mute_is_stored_without_inference(root: Path) -> None:
    stores = PersonalAuthorityStores.initialize(root)
    stores.append_profile_revision(profile_create(excluded_issuer_ids=(WATCH.issuer_id,),
                                                  exclusion_reason_note="personal constraint"))
    focus = attention_create()
    mute = attention_create(AttentionState.MUTE, p9=THESIS, kind=AttentionTargetKind.P9_THESIS)
    assert stores.append_attention_revision(focus).status is AppendStatus.APPENDED
    assert stores.append_attention_revision(mute).status is AppendStatus.APPENDED
    reopened = PersonalAuthorityStores.open(root)
    assert reopened.attention.all_revisions() == tuple(sorted((focus, mute), key=lambda r: r.attention_id))
    assert len(reopened.profile.all_revisions()) == 1                                # 何も導かない ・連鎖しない


# ================================================ 並行性 ・決定論 ・私的


def test_e_a_external_changes_to_either_file_are_concurrent_modifications(root: Path) -> None:
    first = PersonalAuthorityStores.initialize(root)
    second = PersonalAuthorityStores.open(root)
    first.append_profile_revision(profile_create())
    before = tree(root)
    fails(C.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", second.append_attention_revision,
          attention_create())                                                        # 他方の file の変更も検出
    fails(C.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", second.append_profile_revision,
          profile_create(at=T0 + HOUR))
    assert tree(root) == before
    stores = PersonalAuthorityStores.open(root)
    path = root / DIR / store_io.PROFILE_FILENAME
    data = path.read_bytes()
    path.write_bytes(data.replace(b"long term", b"LONG TERM"))                      # 同じ長さ ・違う sha256
    fails(C.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", stores.append_attention_revision,
          attention_create())
    path.write_bytes(data)
    stores = PersonalAuthorityStores.open(root)
    (root / DIR / store_io.ATTENTION_FILENAME).unlink()
    fails(C.CONCURRENT_MODIFICATION, "STORE_CHANGED_SINCE_LOAD", stores.append_profile_revision,
          retire(profile_create(), T0 + HOUR))
    assert path.read_bytes() == data


def test_e_b_files_are_deterministic_and_errors_hold_no_private_content(tmp_path: Path) -> None:
    outputs = []
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        stores = PersonalAuthorityStores.initialize(root)
        stores.append_profile_revision(profile_create(horizon_note=MARKER))
        stores.append_attention_revision(attention_create())
        outputs.append(tuple((root / DIR / f).read_bytes() for f in store_io.AUTHORITY_FILENAMES))
    assert outputs[0] == outputs[1]
    root = tmp_path / "one"
    profile_path = root / DIR / store_io.PROFILE_FILENAME
    profile_path.write_bytes(profile_path.read_bytes().replace(MARKER.encode(), b"X" * len(MARKER)))
    errors = []
    for fn, args in ((PersonalAuthorityStores.open, (root,)),
                     (PersonalAuthorityStores.open, (tmp_path / "absent",)),
                     (PersonalAuthorityStores.initialize, (str(tmp_path / "a" / ".." / "b"),))):
        with pytest.raises(PersonalStoreError) as exc:
            fn(*args)
        errors.append(exc.value)
    stores = PersonalAuthorityStores.open(tmp_path / "two")
    with pytest.raises(PersonalStoreError) as exc:
        stores.append_profile_revision(profile_create(at=T0 + HOUR, horizon_note=MARKER))
    errors.append(exc.value)
    for error in errors:
        text = f"{error} {error.detail!r} {error.args!r}"
        for leak in (MARKER, str(tmp_path), "p10prf_", "p10prv_", "p10att_", "p9wat_", "p8iss_", "human:"):
            assert leak not in text, (leak, text)
