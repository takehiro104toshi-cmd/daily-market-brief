"""P13-A2a — P10 の governed な safe view の adapter の試験（合成の一時 root だけ ・凍結の test の builder ・凍結の P10 の書き手）。

本物の private な root には触れない。凍結の production の code は変えない。読みの間の変化 ・失敗は一時 root の操作か、adapter の
module の参照の差し替えで起こす。
"""
from __future__ import annotations

import dataclasses
import http.client
import socket
import subprocess
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.market_memory import governed_review_source as source
from src.intelligence.market_memory.review_state_change import ChangeKind, detect_changes
from src.intelligence.market_memory.review_state_sample import (OutcomeStatus, ReviewStateError, SampleCutoff, SampleEvidence,
                                                                 build_sample)
from src.intelligence.personal_intelligence.attention_model import AttentionState, AttentionTargetKind
from src.intelligence.personal_intelligence.authority_stores import PersonalAuthorityStores
from src.intelligence.personal_intelligence.decisions import AttentionCreate, ProfileCreate
from src.intelligence.personal_intelligence.executor import apply_decision
from src.intelligence.personal_intelligence.p9_view import (P9_VIEW_RULES_VERSION, P9_VIEW_SCHEMA_VERSION, SAFE_VIEW_CLASS,
                                                            P9ViewError, read_p9_safe_view)
from src.intelligence.personal_intelligence.personal_projection import (PERSONAL_PROJECTION_CLASS,
                                                                        PERSONAL_PROJECTION_SCHEMA_VERSION, personal_safe_projection)
from src.intelligence.personal_intelligence.review_view import (REVIEW_VIEW_CLASS, REVIEW_VIEW_SCHEMA_VERSION, ReviewViewError,
                                                                read_personal_review)
from src.intelligence.watchlist_thesis_intelligence.authority_stores import AuthorityStores as P9AuthorityStores
from src.intelligence.watchlist_thesis_intelligence.revision_model import ChangeKind as P9ChangeKind
from tests.intelligence.test_personal_intelligence_executor import D1, build_p9, tree
from tests.intelligence.test_watchlist_thesis_semantics import HOUR, ISSUER2, T0, watch_create, watch_next

AUTHOR = "human:reviewer"
NOTE = "PRIVATE-PROFILE-NOTE-SENTINEL"
REASON = "PRIVATE-EXCLUSION-REASON-SENTINEL"
RULES = "p13_review_state_rules:0.1.0"
DAY = date(2026, 7, 1)
BEFORE_DECISIONS = SampleCutoff(at=T0 + 3 * HOUR + HOUR // 2, as_of_date=DAY)
AFTER_DECISIONS = SampleCutoff(at=T0 + 5 * HOUR, as_of_date=DAY)
LATER = SampleCutoff(at=T0 + 9 * HOUR, as_of_date=DAY)
ISSUER3 = "p8iss_" + "c" * 24
LEAK_MARKERS = ("MALFORMED_JSON", "P10_ROOT_MISSING", "P9_ROOT_MISSING", "STORE_CHANGED", "Traceback", "human:", NOTE, REASON)


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED")


@pytest.fixture(autouse=True)
def _no_network_credentials_or_processes(monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _trap)
    monkeypatch.setattr(socket.socket, "connect", _trap)
    monkeypatch.setattr(http.client.HTTPConnection, "__init__", _trap)
    monkeypatch.setattr(urllib.request, "urlopen", _trap)
    monkeypatch.setattr(subprocess, "Popen", _trap)                                   # scheduler ／ process は無い


def _world(base: Path) -> dict:
    p9 = build_p9(base / "p9_private_root")
    p10 = base / "p10_private_root"
    p10.mkdir()
    PersonalAuthorityStores.initialize(p10)
    at = T0 + 4 * HOUR
    apply_decision(ProfileCreate(author_ref=AUTHOR, reviewed_at=at, horizon_note=NOTE, liquidity_note="", risk_context_note="",
                                 review_lookahead_days=14, excluded_issuer_ids=(ISSUER2,), exclusion_reason_note=REASON), p10_root=p10)
    apply_decision(AttentionCreate(target_kind=AttentionTargetKind.P9_WATCH_ENTRY, target_root_id=p9["w1"].watch_entry_id,
                                   observed_p9_revision_id=p9["w1b"].revision_id, state=AttentionState.FOCUS, author_ref=AUTHOR,
                                   reviewed_at=at), p10_root=p10, p9_root=p9["root"])
    return dict(p9, p10=p10, base=base)


@pytest.fixture
def world(tmp_path: Path) -> dict:
    return _world(tmp_path)


def _sample(world: dict, cutoff: SampleCutoff = AFTER_DECISIONS):
    return source.sample_review_state(world["p10"], world["root"], cutoff=cutoff, rules_version=RULES)


def _assert_failure(outcome, status: OutcomeStatus, code: str, tmp: Path) -> None:
    assert outcome.status is status and outcome.failure_code == code and outcome.sample is None   # 部分の標本は無い
    assert code in source.ADAPTER_FAILURE_CODES and (status is OutcomeStatus.MISSING) == (code in source.MISSING_CODES)
    text = repr(outcome)
    assert str(tmp) not in text and not any(marker in text for marker in LEAK_MARKERS), text   # detail ・root は出ない


# ================================================ 正: 標本 ・空 ・変化 ・決定論 ・authority の不変


def test_pinned_view_literals_equal_the_frozen_p10_constants() -> None:
    assert (source.SUPPORTED_REVIEW_VIEW_SCHEMA, source.SUPPORTED_REVIEW_VIEW_CLASS) == (REVIEW_VIEW_SCHEMA_VERSION, REVIEW_VIEW_CLASS)
    assert (source.SUPPORTED_P9_VIEW_SCHEMA, source.SUPPORTED_P9_VIEW_RULES, source.SUPPORTED_P9_VIEW_CLASS) == (
        P9_VIEW_SCHEMA_VERSION, P9_VIEW_RULES_VERSION, SAFE_VIEW_CLASS)
    assert (source.SUPPORTED_PROJECTION_SCHEMA, source.SUPPORTED_PROJECTION_CLASS) == (
        PERSONAL_PROJECTION_SCHEMA_VERSION, PERSONAL_PROJECTION_CLASS)


def test_valid_empty_samples_are_sampled_not_missing(world, tmp_path) -> None:
    before_any = source.sample_review_state(world["p10"], world["root"], cutoff=SampleCutoff(at=T0 - HOUR, as_of_date=DAY),
                                            rules_version=RULES)
    assert before_any.status is OutcomeStatus.SAMPLED and before_any.is_empty_sample
    empty9, empty10 = tmp_path / "empty_p9", tmp_path / "empty_p10"
    empty9.mkdir()
    empty10.mkdir()
    P9AuthorityStores.initialize(empty9)
    PersonalAuthorityStores.initialize(empty10)
    empty = source.sample_review_state(empty10, empty9, cutoff=AFTER_DECISIONS, rules_version=RULES)
    assert empty.status is OutcomeStatus.SAMPLED and empty.failure_code == "" and empty.is_empty_sample


def test_populated_sample_maps_only_the_approved_governed_fields(world) -> None:
    outcome = _sample(world)
    assert outcome.status is OutcomeStatus.SAMPLED and not outcome.is_empty_sample
    sample = outcome.sample
    assert sample.view_identity == source.SUPPORTED_VIEW_IDENTITY and sample.cutoff == AFTER_DECISIONS
    review = read_personal_review(world["p10"], world["root"], at=AFTER_DECISIONS.at, as_of_date=DAY)
    assert {(e.record_kind.value, e.p9_root_id, e.p9_revision_id) for e in sample.entries} == {
        (e.record_kind.value, e.p9_root_id, e.p9_revision_id) for e in review.entries}
    assert dict(sample.counts.personal)["focus_entry_count"] == 1 and dict(sample.counts.personal)["excluded_by_profile_count"] == 1
    text = sample.to_json()
    assert NOTE not in text and REASON not in text and AUTHOR not in text and str(world["base"]) not in text
    for field in ("rationale", "statement", "author_ref", "reviewed_at", "known_at", "sampled_at", "horizon_note"):
        assert field not in text


def test_changes_across_decisions_are_endpoint_differences_and_identical_endpoints_record_nothing(world) -> None:
    before, after, later = (_sample(world, c).sample for c in (BEFORE_DECISIONS, AFTER_DECISIONS, LATER))
    changes = detect_changes(before, after)
    assert {c.kind for c in changes} == {ChangeKind.CHANGED}
    fields_changed = {name for c in changes for name, _, _ in c.changed_fields}
    assert fields_changed == {"attention", "excluded_by_profile", "surface_group"}
    assert detect_changes(after, later) == ()                                          # 端点が一致（変化の不在の証明ではない）


def test_repeat_reads_are_deterministic_and_telemetry_never_touches_identity(world) -> None:
    first, second = _sample(world).sample, _sample(world).sample
    assert first == second and first.to_json() == second.to_json() and first.sample_digest == second.sample_digest
    for when in (datetime(2026, 7, 2, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc)):
        evidence = SampleEvidence(sample_id=first.sample_id, sample_digest=first.sample_digest, sampled_at=when, build_ref="BUILD_X")
        assert evidence.sample_digest == first.sample_digest
    direct = build_sample(cutoff=first.cutoff, view_identity=first.view_identity, entries=first.entries, counts=first.counts,
                          rules_version=RULES).sample
    assert direct.sample_digest == first.sample_digest                                  # adapter は A1 の identity を変えない


def test_reads_leave_both_authority_trees_byte_and_mtime_identical(world) -> None:
    before9, before10 = tree(world["root"]), tree(world["p10"])
    for cutoff in (BEFORE_DECISIONS, AFTER_DECISIONS, LATER):
        assert _sample(world, cutoff).status is OutcomeStatus.SAMPLED
    assert tree(world["root"]) == before9 and tree(world["p10"]) == before10


# ================================================ 不在 ・破損 ・世界の不正


def test_absent_stores_are_missing(world, tmp_path) -> None:
    nowhere = tmp_path / "nowhere"
    _assert_failure(source.sample_review_state(world["p10"], nowhere, cutoff=AFTER_DECISIONS, rules_version=RULES),
                    OutcomeStatus.MISSING, source.P9_STORE_MISSING, tmp_path)
    _assert_failure(source.sample_review_state(nowhere, world["root"], cutoff=AFTER_DECISIONS, rules_version=RULES),
                    OutcomeStatus.MISSING, source.P10_STORE_MISSING, tmp_path)
    _assert_failure(source.sample_review_state(nowhere, nowhere, cutoff=AFTER_DECISIONS, rules_version=RULES),
                    OutcomeStatus.MISSING, source.P9_STORE_MISSING, tmp_path)               # 最初の不在
    bare10, bare9 = tmp_path / "bare_p10", tmp_path / "bare_p9"
    bare10.mkdir()
    bare9.mkdir()
    _assert_failure(source.sample_review_state(bare10, world["root"], cutoff=AFTER_DECISIONS, rules_version=RULES),
                    OutcomeStatus.MISSING, source.P10_STORE_MISSING, tmp_path)               # 初期化されていない P10
    _assert_failure(source.sample_review_state(world["p10"], bare9, cutoff=AFTER_DECISIONS, rules_version=RULES),
                    OutcomeStatus.MISSING, source.P9_STORE_MISSING, tmp_path)                # 初期化されていない P9


def test_corruption_is_integrity_failure_and_never_missing(world, tmp_path) -> None:
    profile = next(world["p10"].rglob("profile_authority.jsonl"))
    original = profile.read_bytes()
    profile.write_bytes(original + b"{not json}\n")
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, source.P10_STORE_CORRUPTION, tmp_path)
    profile.write_bytes(original)
    watchlist = next(world["root"].rglob("watchlist_authority.jsonl"))
    watchlist.write_bytes(watchlist.read_bytes() + b"{not json}\n")
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, source.P9_STORE_CORRUPTION, tmp_path)


@pytest.mark.parametrize("raised, code", [
    (P9ViewError("P9_WORLD_INVALID", "THESIS_WITHOUT_WATCH"), "P9_WORLD_INVALID"),
    (P9ViewError("P9_STORE_UNAVAILABLE", "CONCURRENT_MODIFICATION:STORE_CHANGED_SINCE_LOAD"), "SOURCE_CHANGED_DURING_READ"),
    (P9ViewError("P9_STORE_UNAVAILABLE", "STORE_MISSING:SOMETHING_NEW"), "SOURCE_READ_UNCLASSIFIED"),
    (P9ViewError("P9_STORE_UNAVAILABLE", "UNFORMATTED"), "SOURCE_READ_UNCLASSIFIED"),
    (P9ViewError("BRAND_NEW_CODE", ""), "SOURCE_READ_UNCLASSIFIED"),
    (P9ViewError("INSTANT_NOT_AWARE", "at"), "SOURCE_INPUT_REJECTED"),
])
def test_first_p9_read_errors_fail_closed_with_safe_codes(world, monkeypatch, tmp_path, raised, code) -> None:
    def failing(*_a, **_k):
        raise raised
    monkeypatch.setattr(source, "read_p9_safe_view", failing)
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, code, tmp_path)


@pytest.mark.parametrize("raised, code", [
    (ReviewViewError("P10_WORLD_INVALID", "LIVE_MARK_CONFLICT"), "P10_WORLD_INVALID"),
    (ReviewViewError("P10_STORE_UNAVAILABLE", "CONCURRENT_MODIFICATION:STORE_CHANGED_SINCE_LOAD"), "SOURCE_CHANGED_DURING_READ"),
    (ReviewViewError("P10_STORE_UNAVAILABLE", "ROOT_REJECTED:ROOT_IS_SYMLINK"), "SOURCE_INPUT_REJECTED"),
    (ReviewViewError("P10_STORE_UNAVAILABLE", "STORE_MISSING:SOMETHING_NEW"), "SOURCE_READ_UNCLASSIFIED"),
    (ReviewViewError("P9_UNAVAILABLE", "P9_STORE_UNAVAILABLE"), "SOURCE_CHANGED_DURING_READ"),
    (ReviewViewError("P9_UNAVAILABLE", "P9_WORLD_INVALID"), "SOURCE_CHANGED_DURING_READ"),
    (ReviewViewError("BRAND_NEW_CODE", ""), "SOURCE_READ_UNCLASSIFIED"),
])
def test_review_read_errors_fail_closed_with_safe_codes(world, monkeypatch, tmp_path, raised, code) -> None:
    def failing(*_a, **_k):
        raise raised
    monkeypatch.setattr(source, "read_personal_review", failing)
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, code, tmp_path)


# ================================================ 読みの間の変化 ・P9 の再読の限界


def _wrap_review(monkeypatch, before=None, after=None) -> None:
    real = source.read_personal_review

    def wrapped(*args, **kwargs):
        if before:
            before()
        result = real(*args, **kwargs)
        if after:
            after()
        return result
    monkeypatch.setattr(source, "read_personal_review", wrapped)


def test_p9_change_between_the_two_safe_view_reads_fails_closed(world, monkeypatch, tmp_path) -> None:
    def add_watch() -> None:
        P9AuthorityStores.open(world["root"]).append_watch(watch_create(ISSUER3, at=T0 + 4 * HOUR + HOUR // 2, review_due_on=D1))
    _wrap_review(monkeypatch, after=add_watch)
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, source.SOURCE_CHANGED_DURING_READ, tmp_path)


def test_p9_failure_after_the_first_successful_read_is_never_missing(world, monkeypatch, tmp_path) -> None:
    watchlist = next(world["root"].rglob("watchlist_authority.jsonl"))
    _wrap_review(monkeypatch, after=lambda: watchlist.write_bytes(watchlist.read_bytes() + b"{not json}\n"))
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, source.SOURCE_CHANGED_DURING_READ, tmp_path)


def test_p9_disappearing_before_the_review_read_is_a_change_not_absence(world, monkeypatch, tmp_path) -> None:
    watchlist = next(world["root"].rglob("watchlist_authority.jsonl"))
    _wrap_review(monkeypatch, before=watchlist.unlink)
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, source.SOURCE_CHANGED_DURING_READ, tmp_path)


def test_limit_equal_p9_reads_cannot_rule_out_an_intervening_round_trip(world, monkeypatch) -> None:
    """限界の記録: P9 を書き換えて戻す（ABA）と、2 回の P9 の読みは一致し、見直しの view は一時の状態を見る。adapter はこれを
    検出できない（不可分な snapshot ではない）。この試験は成功を主張せず、限界が在ることを固定する。"""
    watchlist = next(world["root"].rglob("watchlist_authority.jsonl"))
    saved = watchlist.read_bytes()
    transient = watch_next(world["w2"], P9ChangeKind.REVISE, reviewed_at=T0 + 4 * HOUR + HOUR // 2, review_due_on=D1,
                           rationale="a transient revision that is reverted before the second read")
    _wrap_review(monkeypatch, before=lambda: P9AuthorityStores.open(world["root"]).append_watch(transient),
                 after=lambda: watchlist.write_bytes(saved))
    outcome = _sample(world)
    assert outcome.status is OutcomeStatus.SAMPLED                                        # 検出できない（限界）
    assert transient.revision_id in {e.p9_revision_id for e in outcome.sample.entries}   # 一時の revision を標本が含む
    assert "ABA" in (source.__doc__ or "") and "不可分な snapshot の証明ではなく" in (source.__doc__ or "")


# ================================================ 版 ・class ・形 ・as_of の不一致


def _replace_p9(monkeypatch, **changes) -> None:
    real = source.read_p9_safe_view
    monkeypatch.setattr(source, "read_p9_safe_view", lambda *a, **k: dataclasses.replace(real(*a, **k), **changes))


def _replace_review(monkeypatch, **changes) -> None:
    real = source.read_personal_review
    monkeypatch.setattr(source, "read_personal_review", lambda *a, **k: dataclasses.replace(real(*a, **k), **changes))


def _replace_projection(monkeypatch, **changes) -> None:
    real = source.personal_safe_projection
    monkeypatch.setattr(source, "personal_safe_projection", lambda review: dataclasses.replace(real(review), **changes))


@pytest.mark.parametrize("patch, code", [
    (lambda m: _replace_p9(m, schema_version="p10_p9_view:9.9.9"), "VIEW_SCHEMA_UNSUPPORTED"),
    (lambda m: _replace_p9(m, rules_version="p10_p9_view:9.9.9"), "VIEW_SCHEMA_UNSUPPORTED"),
    (lambda m: _replace_p9(m, view_class="SOME_OTHER_VIEW"), "VIEW_CLASS_UNSUPPORTED"),
    (lambda m: _replace_review(m, schema_version="p10_personal_review:9.9.9"), "VIEW_SCHEMA_UNSUPPORTED"),
    (lambda m: _replace_review(m, view_class="SOME_OTHER_VIEW"), "VIEW_CLASS_UNSUPPORTED"),
    (lambda m: _replace_projection(m, schema_version="p10_personal_safe_projection:9.9.9"), "VIEW_SCHEMA_UNSUPPORTED"),
    (lambda m: _replace_projection(m, projection_class="SOME_OTHER_PROJECTION"), "VIEW_CLASS_UNSUPPORTED"),
    (lambda m: _replace_review(m, as_of_date=date(2026, 7, 2)), "VIEW_AS_OF_MISMATCH"),
    (lambda m: _replace_p9(m, as_of_date=date(2026, 7, 2)), "VIEW_AS_OF_MISMATCH"),
    (lambda m: _replace_review(m, entries=list()), "VIEW_SHAPE_UNSUPPORTED"),
    (lambda m: _replace_review(m, review_lookahead_days=-1), "VIEW_CONTENT_INVALID"),
])
def test_unknown_versions_classes_shapes_and_as_of_dates_fail_closed(world, monkeypatch, tmp_path, patch, code) -> None:
    patch(monkeypatch)
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, code, tmp_path)


def test_non_dataclass_or_reshaped_views_are_rejected(world, monkeypatch, tmp_path) -> None:
    @dataclasses.dataclass(frozen=True)
    class Reshaped:
        extra: int = 0
    monkeypatch.setattr(source, "read_p9_safe_view", lambda *a, **k: Reshaped())
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, source.VIEW_SHAPE_UNSUPPORTED, tmp_path)
    monkeypatch.setattr(source, "read_p9_safe_view", lambda *a, **k: object())
    _assert_failure(_sample(world), OutcomeStatus.INTEGRITY_FAILURE, source.VIEW_SHAPE_UNSUPPORTED, tmp_path)


def test_inconsistent_governed_counts_are_integrity_failure_from_the_model(world, monkeypatch, tmp_path) -> None:
    real = source.personal_safe_projection
    monkeypatch.setattr(source, "personal_safe_projection",
                        lambda review: dataclasses.replace(real(review), review_entry_count=99))
    outcome = _sample(world)
    assert outcome.status is OutcomeStatus.INTEGRITY_FAILURE and outcome.sample is None and outcome.failure_code == "COUNTS_INCONSISTENT"


# ================================================ 入力 ・漏えい ・面


@pytest.mark.parametrize("p10_root, p9_root, cutoff, rules_version, detail", [
    ("", "x", AFTER_DECISIONS, RULES, "P10_ROOT"),
    (None, "x", AFTER_DECISIONS, RULES, "P10_ROOT"),
    (123, "x", AFTER_DECISIONS, RULES, "P10_ROOT"),
    ("a\x00b", "x", AFTER_DECISIONS, RULES, "P10_ROOT"),
    ("x", "   ", AFTER_DECISIONS, RULES, "P9_ROOT"),
    ("x", "x", datetime(2026, 7, 1, tzinfo=timezone.utc), RULES, "CUTOFF"),
    ("x", "x", AFTER_DECISIONS, "", "RULES_VERSION"),
    ("x", "x", AFTER_DECISIONS, "has spaces", "RULES_VERSION"),
    ("x", "x", AFTER_DECISIONS, None, "RULES_VERSION"),
])
def test_invalid_caller_inputs_raise_a_typed_error_without_reading(monkeypatch, p10_root, p9_root, cutoff, rules_version, detail) -> None:
    monkeypatch.setattr(source, "read_p9_safe_view", _trap)
    monkeypatch.setattr(source, "read_personal_review", _trap)
    with pytest.raises(ReviewStateError) as exc:
        source.sample_review_state(p10_root, p9_root, cutoff=cutoff, rules_version=rules_version)
    assert exc.value.code == source.ADAPTER_INPUT_INVALID and exc.value.detail == detail and "\x00" not in str(exc.value)


def test_relative_or_unsafe_roots_rejected_by_the_governed_readers_are_input_rejections(world, tmp_path) -> None:
    _assert_failure(source.sample_review_state(world["p10"], "relative/p9", cutoff=AFTER_DECISIONS, rules_version=RULES),
                    OutcomeStatus.INTEGRITY_FAILURE, source.SOURCE_INPUT_REJECTED, tmp_path)
    _assert_failure(source.sample_review_state("relative/p10", world["root"], cutoff=AFTER_DECISIONS, rules_version=RULES),
                    OutcomeStatus.INTEGRITY_FAILURE, source.SOURCE_INPUT_REJECTED, tmp_path)
    _assert_failure(source.sample_review_state(str(world["p10"]) + "/../p10_private_root", world["root"], cutoff=AFTER_DECISIONS,
                                               rules_version=RULES),
                    OutcomeStatus.INTEGRITY_FAILURE, source.SOURCE_INPUT_REJECTED, tmp_path)


def test_the_adapter_exposes_only_the_sanctioned_governed_surface() -> None:
    governed = {"read_personal_review", "read_p9_safe_view", "personal_safe_projection", "ReviewViewError", "P9ViewError"}
    imported_from_p10 = {name for name, value in vars(source).items()
                         if getattr(value, "__module__", "").startswith("src.intelligence.personal_intelligence")}
    assert imported_from_p10 == governed
    for forbidden in ("read_p9_private_snapshot", "ProfileStore", "AttentionStore", "WatchlistStore", "ThesisStore",
                      "AuthorityStores", "outcome_for_source_failure", "SampleEvidence"):
        assert not hasattr(source, forbidden), forbidden
    assert source.read_personal_review is read_personal_review and source.read_p9_safe_view is read_p9_safe_view
    assert source.personal_safe_projection is personal_safe_projection
