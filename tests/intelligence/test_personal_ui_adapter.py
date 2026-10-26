"""P11-A1 — governed な read の adapter と UI model の test（合成の P9 ／ P10 の root だけ ・sentinel の私的 ・決定論 ・zero network）。"""
from __future__ import annotations

import dataclasses
import http.client
import json
import math
import os
import re
import shutil
import socket
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.personal_intelligence.attention_model import AttentionState, AttentionTargetKind
from src.intelligence.personal_intelligence.authority_stores import PersonalAuthorityStores
from src.intelligence.personal_intelligence.decisions import AttentionCreate, ProfileCreate
from src.intelligence.personal_intelligence.executor import apply_decision
from src.intelligence.personal_intelligence.review_view import (AttentionMark, DueClass, RecordKind, SurfaceGroup,
                                                                read_personal_review)
from src.intelligence.personal_ui import p10_read_adapter as adapter
from src.intelligence.personal_ui import ui_model as um
from src.intelligence.personal_ui.p10_read_adapter import read_ui_model
from src.intelligence.personal_ui.ui_model import (UiModel, UiReadError, UiReviewEntry, canonical_json,
                                                   error_json_bytes, model_to_dict, ui_model_json_bytes)
from tests.intelligence.test_personal_intelligence_executor import build_p9, tree
from tests.intelligence.test_watchlist_thesis_semantics import HOUR, ISSUER, ISSUER2, T0

AUTHOR = "human:sentinel-author"
NOTE = "SENTINEL-HORIZON-NOTE long term"
LIQ = "SENTINEL-LIQUIDITY-NOTE"
RISK = "SENTINEL-RISK-NOTE"
REASON = "SENTINEL-EXCLUSION-REASON"
CREDENTIAL = "SENTINEL-CREDENTIAL-VALUE"
AT = T0 + 6 * HOUR
AS_OF = date(2026, 9, 25)
_HITS: list = []


def _trap(*_args, **_kwargs):
    _HITS.append(1)
    raise AssertionError("TRAPPED: network / jquants")


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    """P9: W1（改訂済み ・ISSUER）・W2（ISSUER2）・T1（W1 の Thesis）。P10: profile（ISSUER2 を除外 ・sentinel の文）・
    W1 に FOCUS ・T1 に MUTE。読み込みの間は credential を sentinel にし、network ・J-Quants を罠にする。"""
    p9 = build_p9(tmp_path / "p9_private_root")
    p10 = tmp_path / "p10_private_root"
    p10.mkdir()
    PersonalAuthorityStores.initialize(p10)
    at = T0 + 4 * HOUR
    profile = apply_decision(ProfileCreate(author_ref=AUTHOR, reviewed_at=at, horizon_note=NOTE, liquidity_note=LIQ,
                                           risk_context_note=RISK, review_lookahead_days=14,
                                           excluded_issuer_ids=(ISSUER2,), exclusion_reason_note=REASON), p10_root=p10)
    focus = apply_decision(AttentionCreate(target_kind=AttentionTargetKind.P9_WATCH_ENTRY,
                                           target_root_id=p9["w1"].watch_entry_id,
                                           observed_p9_revision_id=p9["w1b"].revision_id, state=AttentionState.FOCUS,
                                           author_ref=AUTHOR, reviewed_at=at), p10_root=p10, p9_root=p9["root"])
    mute = apply_decision(AttentionCreate(target_kind=AttentionTargetKind.P9_THESIS, target_root_id=p9["t1"].thesis_id,
                                          observed_p9_revision_id=p9["t1"].revision_id, state=AttentionState.MUTE,
                                          author_ref=AUTHOR, reviewed_at=at), p10_root=p10, p9_root=p9["root"])
    sentinels = {NOTE, LIQ, RISK, REASON, AUTHOR, CREDENTIAL, ISSUER, ISSUER2, str(tmp_path), "SENTINEL",
                 p9["w1"].watch_entry_id, p9["w1"].revision_id, p9["w1b"].revision_id, p9["w2"].watch_entry_id,
                 p9["w2"].revision_id, p9["t1"].thesis_id, p9["t1"].revision_id, profile.root_id, profile.revision_id,
                 focus.root_id, focus.revision_id, mute.root_id, mute.revision_id}
    monkeypatch.setenv("JQUANTS_API_KEY", CREDENTIAL)
    for target, name in ((socket, "create_connection"), (socket, "getaddrinfo"), (urllib.request, "urlopen")):
        monkeypatch.setattr(target, name, _trap)
    monkeypatch.setattr(socket.socket, "connect", _trap)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", _trap)
    for module_name, module in list(sys.modules.items()):                           # 推移的に load された J-Quants の client
        if module is not None and "jquants" in module_name:
            for attr, value in list(vars(module).items()):
                if isinstance(value, type) and value.__module__ == module_name and ("Client" in attr
                                                                                   or "Transport" in attr):
                    monkeypatch.setattr(value, "__init__", _trap)
    _HITS.clear()
    before = (tree(p9["root"]), tree(p10))
    yield dict(p9=p9, p10=p10, sentinels=sentinels, tmp=tmp_path)
    assert (tree(p9["root"]), tree(p10)) == before                                   # 読み込みは何も書かない
    assert _HITS == []                                                                 # network ・J-Quants の構築は 0


def _text_of(model: UiModel) -> str:
    return ui_model_json_bytes(model).decode("utf-8") + repr(model) + repr(model_to_dict(model))


def test_a_a_model_mirrors_the_governed_review_in_order_without_identifiers(world) -> None:
    model = read_ui_model(world["p10"], world["p9"]["root"], at=AT, as_of_date=AS_OF)
    review = read_personal_review(world["p10"], world["p9"]["root"], at=AT, as_of_date=AS_OF)
    assert len(model.entries) == len(review.entries) == 3
    for ordinal, (ui, gov) in enumerate(zip(model.entries, review.entries)):          # 順は governed な view のまま
        assert ui.ordinal == ordinal
        assert ui.source_kind == {"WATCH_ENTRY": "WATCH", "THESIS": "THESIS"}[gov.record_kind.value]
        assert (ui.p9_status, ui.p9_provenance_kind) == (gov.p9_status, gov.p9_provenance_kind)
        assert ui.review_due_on == (gov.review_due_on.isoformat() if gov.review_due_on else None)
        assert (ui.due_class, ui.attention, ui.surface_group) == (gov.due_class.value, gov.attention.value,
                                                                   gov.surface_group.value)
        assert ui.excluded_by_profile is gov.excluded_by_profile
    by_kind = {e.attention: e for e in model.entries}
    assert {e.attention for e in model.entries} == {"FOCUS", "NORMAL", "MUTE"}
    muted = by_kind["MUTE"]
    assert muted.source_kind == "THESIS" and muted.surface_group == "MUTED"            # MUTE は消さない
    excluded = by_kind["NORMAL"]
    assert excluded.excluded_by_profile and excluded.surface_group == "EXCLUDED_BY_PROFILE"   # 除外は消さない
    focus = by_kind["FOCUS"]
    assert muted.linked_watch_ordinal == focus.ordinal                                 # Thesis → 同じ応答の Watchlist の位置
    assert focus.linked_watch_ordinal is None and excluded.linked_watch_ordinal is None
    assert model.active_profile_present and model.review_lookahead_days == 14
    assert model.as_of_date == "2026-09-25" and model.at == AT.astimezone(timezone.utc).isoformat()
    assert dict(model.personal_counts)["review_entry_count"] == 3
    assert dict(model.personal_counts)["excluded_by_profile_count"] == 1
    assert dict(model.p9_counts)["watch_count"] == 2 and dict(model.p9_counts)["thesis_count"] == 1
    assert "watch_status_counts.ACTIVE" in dict(model.p9_counts)
    assert model.unmatched_live_mark_count == 0
    assert dict(model.source_schema_versions).keys() == {"p10_personal_projection", "p10_review_view", "p9_safe_view"}


def test_a_b_discarded_fields_and_forbidden_vocabulary_are_absent_from_the_schema() -> None:
    entry_fields = {f.name for f in dataclasses.fields(UiReviewEntry)}
    model_fields = {f.name for f in dataclasses.fields(UiModel)}
    assert entry_fields == {"ordinal", "source_kind", "p9_status", "p9_provenance_kind", "review_due_on", "due_class",
                            "attention", "excluded_by_profile", "surface_group", "linked_watch_ordinal"}
    assert model_fields == {"at", "as_of_date", "active_profile_present", "review_lookahead_days", "personal_counts",
                            "p9_counts", "unmatched_live_mark_count", "entries", "source_schema_versions",
                            "schema_version", "view_class"}
    for discarded in ("p9_root_id", "p9_revision_id", "issuer_id", "linked_watch_entry_id", "horizon_note",
                      "liquidity_note", "risk_context_note", "excluded_issuer_ids", "exclusion_reason_note",
                      "author_ref", "reviewed_at", "revision_id", "profile_id", "attention_id"):
        assert discarded not in entry_fields | model_fields
    for token in ("score", "rank", "priority", "recommend", "urgency", "confidence", "return", "target", "price",
                  "buy", "sell", "allocation", "suitability", "holding", "position", "weight", "portfolio"):
        assert not any(token in name for name in entry_fields | model_fields), token
    # 語彙は凍結 P10 の列挙の値の複製
    assert set(um.ATTENTION_MARKS) == {m.value for m in AttentionMark}
    assert set(um.DUE_CLASSES) == {d.value for d in DueClass}
    assert set(um.SURFACE_GROUPS) == {g.value for g in SurfaceGroup}
    assert {"WATCH_ENTRY": "WATCH", "THESIS": "THESIS"}.keys() == {k.value for k in RecordKind}


def test_b_a_output_is_deterministic_and_canonical(world) -> None:
    first = ui_model_json_bytes(read_ui_model(world["p10"], world["p9"]["root"], at=AT, as_of_date=AS_OF))
    second = ui_model_json_bytes(read_ui_model(world["p10"], world["p9"]["root"], at=AT, as_of_date=AS_OF))
    same_instant_utc = ui_model_json_bytes(read_ui_model(world["p10"], world["p9"]["root"],
                                                         at=AT.astimezone(timezone.utc), as_of_date=AS_OF))
    assert first == second == same_instant_utc
    text = first.decode("utf-8")
    payload = json.loads(text)
    assert canonical_json(payload) == text and json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                                          ensure_ascii=False) == text
    assert list(payload) == sorted(payload) and payload["schema_version"] == um.UI_MODEL_SCHEMA_VERSION
    assert [e["ordinal"] for e in payload["entries"]] == [0, 1, 2]
    assert "\n" not in text and ": " not in text
    with pytest.raises(ValueError):
        canonical_json({"x": math.nan})
    with pytest.raises(ValueError):
        canonical_json({"x": math.inf})
    later = ui_model_json_bytes(read_ui_model(world["p10"], world["p9"]["root"], at=AT, as_of_date=AS_OF
                                              + timedelta(days=30)))
    assert later != first                                                              # 入力が違えば違う


def test_b_b_sentinel_private_values_never_appear_in_model_json_or_errors(world) -> None:
    model = read_ui_model(world["p10"], world["p9"]["root"], at=AT, as_of_date=AS_OF)
    texts = [_text_of(model)]
    errors = []
    for args in ((world["tmp"] / "absent", world["p9"]["root"]), (world["p10"], world["tmp"] / "absent"),
                 ("", world["p9"]["root"])):
        with pytest.raises(UiReadError) as exc:
            read_ui_model(*args, at=AT, as_of_date=AS_OF)
        errors.append(exc.value)
    with pytest.raises(UiReadError) as exc:
        read_ui_model(world["p10"], world["p9"]["root"], at=datetime(2026, 7, 1, 9), as_of_date=AS_OF)
    errors.append(exc.value)
    for error in errors:
        texts.append(str(error) + repr(error.args) + error_json_bytes(error).decode("utf-8"))
    for text in texts:
        for sentinel in world["sentinels"]:
            assert sentinel not in text, sentinel
        for prefix in ("p9wat_", "p9ths_", "p9wrv_", "p9trv_", "p8iss_", "p10prf_", "p10prv_", "p10att_", "p10arv_",
                       "human:", "/tmp", "\\\\"):
            assert prefix not in text, prefix
        assert not re.search(r"[A-Za-z]:\\\\", text)                                       # Windows の drive の path
    assert os.environ["JQUANTS_API_KEY"] == CREDENTIAL                                 # 環境に在っても読まない ・出さない
    for path in (adapter.__file__, um.__file__):
        source = Path(path).read_text(encoding="utf-8")
        for token in ("environ", "getenv", "socket", "http", "urllib", "requests", "open(", "Path(", "now(", "today("):
            assert token not in source, (path, token)


def test_c_a_errors_map_to_stable_safe_codes(world) -> None:
    def fails(code: str, detail: str, *args, **kwargs) -> None:
        with pytest.raises(UiReadError) as exc:
            read_ui_model(*args, **kwargs)
        assert (exc.value.code, exc.value.detail) == (code, detail), str(exc.value)

    p10, p9, absent = world["p10"], world["p9"]["root"], world["tmp"] / "absent"
    fails("INPUT_INVALID", "INSTANT_NOT_AWARE", p10, p9, at=datetime(2026, 7, 1, 9), as_of_date=AS_OF)
    fails("INPUT_INVALID", "INSTANT_NOT_AWARE", p10, p9, at="2026-07-01", as_of_date=AS_OF)
    fails("INPUT_INVALID", "INVALID_DATE", p10, p9, at=AT, as_of_date=AT)
    fails("INPUT_INVALID", "ROOT_REQUIRED:P10", "", p9, at=AT, as_of_date=AS_OF)
    fails("INPUT_INVALID", "ROOT_REQUIRED:P9", p10, None, at=AT, as_of_date=AS_OF)
    fails("P10_UNAVAILABLE", "STORE_MISSING:P10_ROOT_MISSING", absent, p9, at=AT, as_of_date=AS_OF)
    fails("P9_UNAVAILABLE", "P9_STORE_UNAVAILABLE", p10, absent, at=AT, as_of_date=AS_OF)
    corrupt = world["tmp"] / "p10_corrupt_copy"                                       # 複製を壊す（fixture の root は不変）
    shutil.copytree(p10, corrupt)
    target = corrupt / "personal_intelligence" / "attention_authority.jsonl"
    target.write_bytes(target.read_bytes()[:-1])                                       # 最後の LF を欠く
    fails("P10_UNAVAILABLE", "STORE_CORRUPTION:MISSING_FINAL_NEWLINE", corrupt, p9, at=AT, as_of_date=AS_OF)
    assert not absent.exists()                                                         # 作らない
    unsafe = UiReadError("P10_UNAVAILABLE", "has/a/path and p10prf_" + "0" * 24)
    assert unsafe.detail == "" and str(unsafe) == "P10_UNAVAILABLE"                  # 安全でない detail は捨てる
    assert json.loads(error_json_bytes(unsafe)) == {"code": "P10_UNAVAILABLE", "detail": "",
                                                    "schema_version": um.UI_ERROR_SCHEMA_VERSION}
    with pytest.raises(UiReadError) as exc:
        UiReviewEntry(ordinal=0, source_kind="WATCH", p9_status="ACTIVE", p9_provenance_kind="MANUAL",
                      review_due_on=None, due_class="NO_DUE_DATE", attention="HIGH", excluded_by_profile=False,
                      surface_group="REVIEW", linked_watch_ordinal=None)
    assert str(exc.value) == "MODEL_INVALID:ATTENTION"                                 # 列挙の外の値は型が拒む
    with pytest.raises(dataclasses.FrozenInstanceError):
        read_ui_model(p10, p9, at=AT, as_of_date=AS_OF).entries[0].attention = "FOCUS"


def test_c_b_no_active_profile_means_window_zero_and_no_exclusions(tmp_path: Path, monkeypatch) -> None:
    p9 = build_p9(tmp_path / "p9")
    p10 = tmp_path / "p10"
    p10.mkdir()
    PersonalAuthorityStores.initialize(p10)
    monkeypatch.setattr(socket, "create_connection", _trap)
    model = read_ui_model(p10, p9["root"], at=AT, as_of_date=AS_OF)
    assert not model.active_profile_present and model.review_lookahead_days == 0
    assert not any(e.excluded_by_profile for e in model.entries) and all(e.attention == "NORMAL" for e in model.entries)
    assert dict(model.personal_counts)["active_profile_count"] == 0
    assert [e.surface_group for e in model.entries] == ["REVIEW"] * 3
    before = read_ui_model(p10, p9["root"], at=T0 - HOUR, as_of_date=AS_OF)          # P9 が無い時点
    assert before.entries == () and dict(before.p9_counts)["watch_count"] == 0
