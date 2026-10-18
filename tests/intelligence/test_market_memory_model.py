"""P13-A1 — Review State Memory の純粋な model の合成の世界の試験（正 ・負）。

凍結の phase は import しない。入力は P10 の governed な view と同じ形の合成の値。時計 ・file ・環境は使わない。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from src.intelligence.market_memory.canonical import (CanonicalError, assert_no_short_id_collision, canonical_json, domain_digest,
                                                       parse_utc_iso, require_aware, require_date, require_fields, short_id, utc_iso)
from src.intelligence.market_memory.review_state_change import (CHANGE_DOMAIN, CHANGE_ID_PREFIX, ENDPOINT_MATCH_IS_NOT_PROOF_OF_NO_CHANGE,
                                                                 INTERPRETATION, ChangeKind, ReviewStateChange, check_comparable,
                                                                 detect_changes, detect_changes_over)
from src.intelligence.market_memory.review_state_sample import (AUTHORITY_CLASS, BUILD_DOMAIN, FORBIDDEN_FIELD_NAMES, PROVENANCE_CLASS,
                                                                 RESERVED_PIT_STATES, SAMPLE_DOMAIN, SAMPLE_ID_PREFIX, STRUCTURAL_FIELDS,
                                                                 AttentionMark, DueClass, OutcomeStatus, P9SafeCounts, PitState, RecordKind,
                                                                 ReviewStateCounts, ReviewStateEntry, ReviewStateError, ReviewStateSample,
                                                                 SampleCutoff, SampleEvidence, SampleOutcome, SourceViewIdentity,
                                                                 StalenessLabel, SurfaceGroup, build_digest, build_sample, check_sample_ids,
                                                                 outcome_for_source_failure, staleness_label)

UTC = timezone.utc
JST = timezone(timedelta(hours=9))
RULES = "p13_review_state_rules:0.1.0"
VIEW = SourceViewIdentity(review_view_schema_version="p10_personal_review:0.1.0", p9_safe_view_schema_version="p10_p9_view:0.1.0",
                          p9_view_rules_version="p10_p9_view:0.1.0", personal_projection_schema_version="p10_personal_projection:0.1.0")
PRIVATE_PATTERNS = (r"[A-Za-z]:\\", r"\b\d{5}\b", r"p9wat_", r"p9ths_", r"p8iss_", r"p10prf_", r"p10att_", r"human:", r"x-api-key",
                    r"api\.jquants", r"S-1-5-\d", r"JQUANTS_")
TEXT_FIELDS = ("rationale", "statement", "mechanism", "note", "author_ref", "reviewed_at", "known_at", "sampled_at")


def cutoff(day: int, hour: int = 0, as_of_day: int | None = None) -> SampleCutoff:
    return SampleCutoff(at=datetime(2026, 1, day, hour, tzinfo=UTC), as_of_date=date(2026, 1, as_of_day or day))


def watch(root: str, issuer: str, *, status="ACTIVE", provenance="MANUAL", due=None, attention=AttentionMark.NORMAL, excluded=False,
          due_class=DueClass.NO_DUE_DATE, revision="rev-1") -> ReviewStateEntry:
    group = SurfaceGroup.EXCLUDED_BY_PROFILE if excluded else SurfaceGroup.MUTED if attention is AttentionMark.MUTE else SurfaceGroup.REVIEW
    return ReviewStateEntry(record_kind=RecordKind.WATCH_ENTRY, p9_root_id=root, p9_revision_id=f"{root}-{revision}", issuer_id=issuer,
                            linked_watch_entry_id="", p9_status=status, p9_provenance_kind=provenance, review_due_on=due,
                            due_class=due_class, attention=attention, excluded_by_profile=excluded, surface_group=group)


def thesis(root: str, link: str, issuer, *, status="ACTIVE", due=None, attention=AttentionMark.NORMAL, excluded=False,
           due_class=DueClass.NO_DUE_DATE, revision="rev-1") -> ReviewStateEntry:
    group = SurfaceGroup.EXCLUDED_BY_PROFILE if excluded else SurfaceGroup.MUTED if attention is AttentionMark.MUTE else SurfaceGroup.REVIEW
    return ReviewStateEntry(record_kind=RecordKind.THESIS, p9_root_id=root, p9_revision_id=f"{root}-{revision}", issuer_id=issuer,
                            linked_watch_entry_id=link, p9_status=status, p9_provenance_kind="", review_due_on=due, due_class=due_class,
                            attention=attention, excluded_by_profile=excluded, surface_group=group)


def tally(values) -> tuple:
    counts: dict = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return tuple(sorted(counts.items()))


def make_counts(entries, cut: SampleCutoff, *, lookahead=7, active=True, unmatched=0, cleared=0, links=0) -> ReviewStateCounts:
    """view と同じ意味で件数を導く（試験の鏡。model はこれを検算する）。"""
    watches = [e for e in entries if e.record_kind is RecordKind.WATCH_ENTRY]
    theses = [e for e in entries if e.record_kind is RecordKind.THESIS]
    focus = sum(1 for e in entries if e.attention is AttentionMark.FOCUS)
    mute = sum(1 for e in entries if e.attention is AttentionMark.MUTE)
    due = lambda rows: sum(1 for e in rows if e.review_due_on is not None and e.review_due_on <= cut.as_of_date)  # noqa: E731
    by = lambda c: sum(1 for e in entries if e.due_class is c)  # noqa: E731
    personal = (("active_profile_count", 1 if active else 0), ("cleared_mark_count", cleared), ("due_count", by(DueClass.DUE)),
                ("excluded_by_profile_count", sum(1 for e in entries if e.excluded_by_profile)), ("focus_entry_count", focus),
                ("later_count", by(DueClass.LATER)), ("live_focus_mark_count", focus),
                ("live_mute_mark_count", mute + unmatched), ("muted_entry_count", mute), ("no_due_date_count", by(DueClass.NO_DUE_DATE)),
                ("overdue_count", by(DueClass.OVERDUE)), ("review_entry_count", len(entries)), ("upcoming_count", by(DueClass.UPCOMING)))
    p9 = P9SafeCounts(watch_count=len(watches), watch_status_counts=tally(e.p9_status for e in watches),
                      watch_provenance_kind_counts=tally(e.p9_provenance_kind for e in watches), watch_review_due_count=due(watches),
                      watch_declared_thesis_link_count=links, thesis_count=len(theses), thesis_status_counts=tally(e.p9_status for e in theses),
                      thesis_review_due_count=due(theses), thesis_invalidation_basis_counts=(), thesis_supporting_evidence_kind_counts=(),
                      thesis_counter_evidence_kind_counts=())
    return ReviewStateCounts(active_profile_present=active, review_lookahead_days=lookahead if active else 0, live_focus_marks=focus,
                             live_mute_marks=mute + unmatched, cleared_marks=cleared, unmatched_live_marks=unmatched, p9=p9, personal=personal)


def world_a(cut: SampleCutoff):
    entries = [watch("watch-a", "issuer-a", due=date(2026, 1, 5), due_class=DueClass.OVERDUE, attention=AttentionMark.FOCUS),
               watch("watch-b", "issuer-b", status="PAUSED", provenance="P8_PROPOSAL", attention=AttentionMark.MUTE),
               thesis("thesis-t1", "watch-a", "issuer-a", due=date(2026, 1, 15), due_class=DueClass.UPCOMING)]
    return entries, make_counts(entries, cut, links=1)


def sample_a(cut: SampleCutoff = cutoff(10)) -> ReviewStateSample:
    entries, counts = world_a(cut)
    outcome = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=counts, rules_version=RULES)
    assert outcome.status is OutcomeStatus.SAMPLED, outcome.failure_code
    return outcome.sample


# ================================================ canonical


def test_canonical_json_is_stable_rejects_floats_and_non_string_keys() -> None:
    assert canonical_json({"b": 1, "a": [True, None, "é"]}) == canonical_json({"a": [True, None, "é"], "b": 1}) == '{"a":[true,null,"é"],"b":1}'
    for bad in ({"x": 1.0}, [0.5], {1: "a"}, {"x": object()}, {"x": datetime(2026, 1, 1, tzinfo=UTC)}):
        with pytest.raises(CanonicalError):
            canonical_json(bad)


def test_domain_digest_matches_independent_sha256_and_short_ids_abbreviate() -> None:
    value = {"k": "v", "n": 2}
    expected = hashlib.sha256(b"p13.test.v1\0" + json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    digest = domain_digest("p13.test.v1", value)
    assert digest == expected and len(digest) == 64
    assert domain_digest("p13.other.v1", value) != digest                                      # domain を変えると別
    assert short_id("p13smp_", digest) == "p13smp_" + digest[:24]
    with pytest.raises(CanonicalError):
        short_id("p13smp_", digest[:63])


def test_short_id_collision_is_detected_fail_closed() -> None:
    head = "a" * 24
    assert_no_short_id_collision([("p13smp_" + head, head + "b" * 40), ("p13smp_" + head, head + "b" * 40)])   # 同じ digest は衝突ではない
    with pytest.raises(CanonicalError) as exc:
        assert_no_short_id_collision([("p13smp_" + head, head + "b" * 40), ("p13smp_" + head, head + "c" * 40)])
    assert exc.value.code == "SHORT_ID_COLLISION"


def test_instants_must_be_aware_and_are_normalized_to_utc_dates_must_be_dates() -> None:
    with pytest.raises(CanonicalError):
        require_aware(datetime(2026, 1, 1, 9), "X")
    with pytest.raises(CanonicalError):
        require_aware(date(2026, 1, 1), "X")
    utc = require_aware(datetime(2026, 1, 1, 9, tzinfo=JST), "X")
    assert utc == datetime(2026, 1, 1, 0, tzinfo=UTC) and utc_iso(utc).endswith("+00:00")
    assert parse_utc_iso(utc_iso(utc)) == utc
    with pytest.raises(CanonicalError):
        parse_utc_iso("2026-01-01T09:00:00+09:00")                                            # UTC だけ
    with pytest.raises(CanonicalError):
        require_date(datetime(2026, 1, 1, tzinfo=UTC), "X")                                  # datetime は date ではない
    assert require_date(date(2026, 1, 1), "X") == date(2026, 1, 1)
    with pytest.raises(CanonicalError):
        require_fields({"a": 1, "b": 2}, frozenset({"a"}), "T")                               # 未知の鍵
    with pytest.raises(CanonicalError):
        require_fields({"a": 1}, frozenset({"a", "b"}), "T")                                  # 欠落


# ================================================ cutoff ・identity


def test_cutoff_requires_aware_at_and_explicit_date_and_never_derives_one_from_the_other() -> None:
    with pytest.raises(CanonicalError):
        SampleCutoff(at=datetime(2026, 1, 10), as_of_date=date(2026, 1, 10))
    with pytest.raises(CanonicalError):
        SampleCutoff(at=datetime(2026, 1, 10, tzinfo=UTC), as_of_date=datetime(2026, 1, 10, tzinfo=UTC))
    jst = SampleCutoff(at=datetime(2026, 1, 11, 8, 30, tzinfo=JST), as_of_date=date(2026, 1, 11))
    assert jst.content() == {"at": "2026-01-10T23:30:00+00:00", "as_of_date": "2026-01-11"}      # 日は明示 ・at から導かない
    assert SampleCutoff.from_dict(jst.content()) == jst


def test_sample_is_deterministic_independent_of_entry_order_and_digest_is_recomputable() -> None:
    cut = cutoff(10)
    entries, counts = world_a(cut)
    first = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=counts, rules_version=RULES).sample
    second = build_sample(cutoff=cut, view_identity=VIEW, entries=list(reversed(entries)), counts=counts, rules_version=RULES).sample
    assert first == second and first.to_json() == second.to_json() and first.sample_digest == second.sample_digest
    expected = hashlib.sha256((SAMPLE_DOMAIN + "\0" + first.to_json()).encode("utf-8")).hexdigest()
    assert first.sample_digest == expected and first.sample_id == SAMPLE_ID_PREFIX + expected[:24]
    assert [e.key for e in first.entries] == sorted(e.key for e in first.entries)
    assert first.provenance_class == PROVENANCE_CLASS and first.authority_class == AUTHORITY_CLASS


def test_sample_round_trips_through_canonical_dict_and_rejects_unknown_fields() -> None:
    sample = sample_a()
    data = json.loads(sample.to_json())
    assert ReviewStateSample.from_dict(data) == sample
    data["extra"] = 1
    with pytest.raises(CanonicalError):
        ReviewStateSample.from_dict(data)


def test_telemetry_lives_in_evidence_and_never_touches_identity_or_known_at() -> None:
    sample = sample_a()
    e1 = SampleEvidence(sample_id=sample.sample_id, sample_digest=sample.sample_digest, sampled_at=datetime(2026, 2, 1, tzinfo=UTC), build_ref="BUILD_A")
    e2 = SampleEvidence(sample_id=sample.sample_id, sample_digest=sample.sample_digest, sampled_at=datetime(2026, 3, 1, 5, tzinfo=JST), build_ref="BUILD_B")
    assert e1.sample_digest == e2.sample_digest == sample.sample_digest                          # telemetry が違っても identity は同じ
    assert "sampled_at" not in sample.to_json() and "known_at" not in sample.to_json() and "reviewed_at" not in sample.to_json()
    assert e1.content()["telemetry"] == "NOT_KNOWN_AT_NOT_IDENTITY"
    with pytest.raises(CanonicalError):
        SampleEvidence(sample_id=sample.sample_id, sample_digest=sample.sample_digest, sampled_at=datetime(2026, 2, 1), build_ref="BUILD_A")
    with pytest.raises(ReviewStateError):
        SampleEvidence(sample_id="p13smp_" + "0" * 24, sample_digest=sample.sample_digest, sampled_at=datetime(2026, 2, 1, tzinfo=UTC), build_ref="B")


def test_schema_has_no_forbidden_fields_and_serialization_holds_no_private_shapes_or_text() -> None:
    for kind in (SampleCutoff, SourceViewIdentity, ReviewStateEntry, P9SafeCounts, ReviewStateCounts, ReviewStateSample, ReviewStateChange):
        names = {f.name for f in kind.__dataclass_fields__.values()}
        assert not names & FORBIDDEN_FIELD_NAMES, kind.__name__
        assert not names & set(TEXT_FIELDS), kind.__name__
    text = sample_a().to_json()
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for field in TEXT_FIELDS:
        assert field not in text
    for state in RESERVED_PIT_STATES:
        assert state.value not in text                                                           # 予約語はこの経路に出ない
    assert set(STRUCTURAL_FIELDS) < {f.name for f in ReviewStateEntry.__dataclass_fields__.values()}


# ================================================ 失敗の区別 ・件数の検算


def test_counts_are_validated_against_view_semantics_and_tampering_is_integrity_failure() -> None:
    cut = cutoff(10)
    entries, counts = world_a(cut)
    good = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=counts, rules_version=RULES)
    assert good.status is OutcomeStatus.SAMPLED and good.failure_code == ""
    personal = dict(counts.personal)
    tampered = [
        ("review_entry_count", 99), ("overdue_count", 0), ("focus_entry_count", 2), ("muted_entry_count", 0), ("excluded_by_profile_count", 1),
        ("active_profile_count", 0), ("live_focus_mark_count", 5)]
    for key, value in tampered:
        bad_personal = tuple(sorted({**personal, key: value}.items()))
        try:
            bad = ReviewStateCounts(**{**{f: getattr(counts, f) for f in counts.__dataclass_fields__}, "personal": bad_personal})
        except ReviewStateError as exc:
            assert exc.code == "COUNTS_INCONSISTENT", key
            continue
        outcome = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=bad, rules_version=RULES)
        assert outcome.status is OutcomeStatus.INTEGRITY_FAILURE and outcome.sample is None and outcome.failure_code == "COUNTS_INCONSISTENT", key
    p9_bad = P9SafeCounts(**{**{f: getattr(counts.p9, f) for f in counts.p9.__dataclass_fields__}, "watch_review_due_count": 0})
    bad = ReviewStateCounts(**{**{f: getattr(counts, f) for f in counts.__dataclass_fields__}, "p9": p9_bad})
    assert build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=bad, rules_version=RULES).failure_code == "COUNTS_INCONSISTENT"
    with pytest.raises(ReviewStateError):                                                        # status の分布の和は件数
        P9SafeCounts(**{**{f: getattr(counts.p9, f) for f in counts.p9.__dataclass_fields__}, "watch_status_counts": (("ACTIVE", 5),)})


def test_as_of_date_mismatch_between_view_and_cutoff_fails_closed() -> None:
    cut = cutoff(10)
    entries, counts = world_a(cut)
    shifted = SampleCutoff(at=cut.at, as_of_date=date(2026, 1, 20))                             # 期日の区分が as_of と矛盾する
    outcome = build_sample(cutoff=shifted, view_identity=VIEW, entries=entries, counts=counts, rules_version=RULES)
    assert outcome.status is OutcomeStatus.INTEGRITY_FAILURE and outcome.failure_code == "COUNTS_INCONSISTENT"


def test_entry_shape_rules_mirror_the_governed_view() -> None:
    with pytest.raises(ReviewStateError):                                                        # watch に発行体が無い
        watch("w", None)
    with pytest.raises(ReviewStateError):                                                        # thesis に出所の種類
        ReviewStateEntry(record_kind=RecordKind.THESIS, p9_root_id="t", p9_revision_id="t-1", issuer_id=None, linked_watch_entry_id="w",
                         p9_status="ACTIVE", p9_provenance_kind="MANUAL", review_due_on=None, due_class=DueClass.NO_DUE_DATE,
                         attention=AttentionMark.NORMAL, excluded_by_profile=False, surface_group=SurfaceGroup.REVIEW)
    with pytest.raises(ReviewStateError):                                                        # 表示の組と印の矛盾
        ReviewStateEntry(record_kind=RecordKind.WATCH_ENTRY, p9_root_id="w", p9_revision_id="w-1", issuer_id="i", linked_watch_entry_id="",
                         p9_status="ACTIVE", p9_provenance_kind="MANUAL", review_due_on=None, due_class=DueClass.NO_DUE_DATE,
                         attention=AttentionMark.MUTE, excluded_by_profile=False, surface_group=SurfaceGroup.REVIEW)
    with pytest.raises(ReviewStateError):                                                        # 自由文のような id
        watch("w", "issuer with spaces")
    with pytest.raises(ReviewStateError):                                                        # 期日の無い OVERDUE
        watch("w", "i", due_class=DueClass.OVERDUE)
    cut = cutoff(10)
    entries = [watch("watch-a", "issuer-a"), thesis("thesis-t1", "watch-a", "issuer-other")]   # thesis の発行体が link と違う
    outcome = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=make_counts(entries, cut), rules_version=RULES)
    assert outcome.status is OutcomeStatus.INTEGRITY_FAILURE and outcome.failure_code == "SAMPLE_INVALID"
    dup = [watch("watch-a", "issuer-a"), watch("watch-a", "issuer-a", revision="rev-2")]
    assert build_sample(cutoff=cut, view_identity=VIEW, entries=dup, counts=make_counts(dup, cut), rules_version=RULES).failure_code == "SAMPLE_INVALID"


def test_missing_integrity_failure_and_empty_sample_are_distinct() -> None:
    missing = outcome_for_source_failure("P10_STORE_UNAVAILABLE")
    assert missing.status is OutcomeStatus.MISSING and missing.sample is None and missing.failure_code == "P10_STORE_UNAVAILABLE"
    assert outcome_for_source_failure("P9_UNAVAILABLE").status is OutcomeStatus.MISSING
    broken = outcome_for_source_failure("P10_WORLD_INVALID")
    assert broken.status is OutcomeStatus.INTEGRITY_FAILURE and broken.sample is None
    assert outcome_for_source_failure("SOMETHING_ELSE").status is OutcomeStatus.INTEGRITY_FAILURE          # 未知は fail closed
    assert outcome_for_source_failure("bad code with spaces").failure_code == "SOURCE_FAILURE_UNCLASSIFIED"
    assert outcome_for_source_failure(None).failure_code == "SOURCE_FAILURE_UNCLASSIFIED"
    cut = cutoff(10)
    empty = build_sample(cutoff=cut, view_identity=VIEW, entries=[], counts=make_counts([], cut, active=False), rules_version=RULES)
    assert empty.status is OutcomeStatus.SAMPLED and empty.is_empty_sample and not missing.is_empty_sample and not broken.is_empty_sample
    with pytest.raises(ReviewStateError):                                                        # 失敗に部分の標本は無い
        SampleOutcome(status=OutcomeStatus.MISSING, failure_code="P9_UNAVAILABLE", sample=empty.sample)
    with pytest.raises(ReviewStateError):
        SampleOutcome(status=OutcomeStatus.SAMPLED, failure_code="", sample=None)


def test_staleness_is_a_label_from_a_declared_window_and_pit_vocabulary_is_reserved() -> None:
    assert staleness_label(None, cutoff(10), window_days=3) is StalenessLabel.UNDETERMINED
    assert staleness_label(cutoff(8), cutoff(10), window_days=3) is StalenessLabel.FRESH
    assert staleness_label(cutoff(1), cutoff(10), window_days=3) is StalenessLabel.STALE
    with pytest.raises(ReviewStateError):
        staleness_label(cutoff(10), cutoff(10), window_days=3)
    with pytest.raises(ReviewStateError):
        staleness_label(None, cutoff(10), window_days=-1)
    assert set(RESERVED_PIT_STATES) == {PitState.UNKNOWN, PitState.UNCERTAIN, PitState.AMBIGUOUS}
    assert {s.value for s in OutcomeStatus} == {"SAMPLED", "MISSING", "INTEGRITY_FAILURE"}        # 標本の経路の結果に予約語は無い


def test_build_identity_depends_on_ordered_cutoffs_view_identity_rules_and_descriptors_only() -> None:
    cuts = (cutoff(8), cutoff(10))
    digest = build_digest(cuts, VIEW, rules_version=RULES)
    expected = hashlib.sha256((BUILD_DOMAIN + "\0" + canonical_json({"schema_version": "p13_review_state_sample:0.1.0", "rules_version": RULES,
                                                                      "cutoffs": [c.content() for c in cuts], "view_identity": VIEW.content(),
                                                                      "input_descriptors": []})).encode("utf-8")).hexdigest()
    assert digest == expected
    assert build_digest(cuts, VIEW, rules_version=RULES, input_descriptors=(("P9_ROOT_MANIFEST", "abc"),)) != digest
    with pytest.raises(ReviewStateError):
        build_digest((cutoff(10), cutoff(8)), VIEW, rules_version=RULES)                       # 順序
    with pytest.raises(ReviewStateError):
        build_digest((cutoff(10), cutoff(10)), VIEW, rules_version=RULES)                      # 重複
    with pytest.raises(ReviewStateError):
        build_digest((), VIEW, rules_version=RULES)


def test_combining_samples_detects_abbreviated_id_collisions() -> None:
    check_sample_ids((sample_a(cutoff(8)), sample_a(cutoff(10))))
    head = "f" * 24
    with pytest.raises(CanonicalError):
        assert_no_short_id_collision([("p13smp_" + head, head + "1" * 40), ("p13smp_" + head, head + "2" * 40)])


# ================================================ 変化（端点の差）


def test_changes_are_endpoint_differences_only_appeared_disappeared_changed() -> None:
    c1, c2 = cutoff(8), cutoff(10)
    e1 = [watch("watch-a", "issuer-a", attention=AttentionMark.FOCUS), watch("watch-b", "issuer-b", status="PAUSED", provenance="P8_PROPOSAL")]
    e2 = [watch("watch-a", "issuer-a", attention=AttentionMark.NORMAL, status="PAUSED", revision="rev-2"),
          thesis("thesis-t1", "watch-a", "issuer-a")]
    s1 = build_sample(cutoff=c1, view_identity=VIEW, entries=e1, counts=make_counts(e1, c1), rules_version=RULES).sample
    s2 = build_sample(cutoff=c2, view_identity=VIEW, entries=e2, counts=make_counts(e2, c2), rules_version=RULES).sample
    changes = detect_changes(s1, s2)
    kinds = {(c.record_kind.value, c.p9_root_id): c for c in changes}
    assert set(kinds) == {("THESIS", "thesis-t1"), ("WATCH_ENTRY", "watch-a"), ("WATCH_ENTRY", "watch-b")}
    assert kinds[("THESIS", "thesis-t1")].kind is ChangeKind.APPEARED and kinds[("WATCH_ENTRY", "watch-b")].kind is ChangeKind.DISAPPEARED
    changed = kinds[("WATCH_ENTRY", "watch-a")]
    assert changed.kind is ChangeKind.CHANGED
    assert changed.changed_fields == (("attention", "FOCUS", "NORMAL"), ("p9_revision_id", "watch-a-rev-1", "watch-a-rev-2"), ("p9_status", "ACTIVE", "PAUSED"))
    assert changed.after_cutoff == c1 and changed.through_cutoff == c2 and changed.interpretation == INTERPRETATION
    assert changed.from_sample_digest == s1.sample_digest and changed.to_sample_digest == s2.sample_digest
    expected = hashlib.sha256((CHANGE_DOMAIN + "\0" + changed.to_json()).encode("utf-8")).hexdigest()
    assert changed.change_digest == expected and changed.change_id == CHANGE_ID_PREFIX + expected[:24]
    assert ReviewStateChange.from_dict(json.loads(changed.to_json())) == changed
    assert all(c.kind is not ChangeKind.CHANGED or c.changed_fields for c in changes)
    for c in changes:
        for name, _, _ in c.changed_fields:
            assert name in STRUCTURAL_FIELDS


def test_identical_endpoints_yield_no_records_even_when_revisions_moved_in_between() -> None:
    s1, s2, s3 = sample_a(cutoff(8)), sample_a(cutoff(9)), sample_a(cutoff(10))
    e_mid = [watch("watch-a", "issuer-a", due=date(2026, 1, 5), due_class=DueClass.OVERDUE, attention=AttentionMark.FOCUS, revision="rev-9"),
             watch("watch-b", "issuer-b", status="PAUSED", provenance="P8_PROPOSAL", attention=AttentionMark.MUTE),
             thesis("thesis-t1", "watch-a", "issuer-a", due=date(2026, 1, 15), due_class=DueClass.UPCOMING)]
    mid = build_sample(cutoff=cutoff(9), view_identity=VIEW, entries=e_mid, counts=make_counts(e_mid, cutoff(9), links=1), rules_version=RULES).sample
    assert detect_changes(s1, s3) == ()                                                          # 端点が一致 → 記録無し
    assert len(detect_changes(s1, mid)) == 1 and len(detect_changes(mid, s3)) == 1             # 間の標本があれば往復が見える
    assert detect_changes_over((s1, mid, s3))[0].changed_fields == (("p9_revision_id", "watch-a-rev-1", "watch-a-rev-9"),)
    assert detect_changes_over((s1, s2, s3)) == ()
    assert "DO_NOT_PROVE_ABSENCE" in ENDPOINT_MATCH_IS_NOT_PROOF_OF_NO_CHANGE                   # 「変化なし」は主張しない


def test_changes_require_same_view_identity_rules_and_strictly_increasing_cutoffs() -> None:
    s1, s2 = sample_a(cutoff(8)), sample_a(cutoff(10))
    with pytest.raises(ReviewStateError) as exc:
        detect_changes(s2, s1)
    assert exc.value.code == "CUTOFF_ORDER_INVALID"
    with pytest.raises(ReviewStateError):
        detect_changes(s1, sample_a(cutoff(8, as_of_day=9)))                                    # 同じ at は比べない
    other_view = SourceViewIdentity(**{**VIEW.content(), "review_view_schema_version": "p10_personal_review:0.2.0"})
    entries, counts = world_a(cutoff(10))
    s_other = build_sample(cutoff=cutoff(10), view_identity=other_view, entries=entries, counts=counts, rules_version=RULES).sample
    with pytest.raises(ReviewStateError) as exc:
        check_comparable(s1, s_other)
    assert exc.value.code == "VIEW_IDENTITY_MISMATCH"
    s_rules = build_sample(cutoff=cutoff(10), view_identity=VIEW, entries=entries, counts=counts, rules_version="other:0.1.0").sample
    with pytest.raises(ReviewStateError) as exc:
        check_comparable(s1, s_rules)
    assert exc.value.code == "RULES_VERSION_MISMATCH"
    with pytest.raises(ReviewStateError):                                                        # 失敗の結果（標本無し）はまたげない
        detect_changes(s1, outcome_for_source_failure("P9_UNAVAILABLE").sample)
    with pytest.raises(ReviewStateError):
        detect_changes_over((s1,))


def test_change_records_reject_non_structural_fields_fabricated_instants_and_same_sample() -> None:
    s1, s2 = sample_a(cutoff(8)), sample_a(cutoff(10))
    base = dict(after_cutoff=s1.cutoff, through_cutoff=s2.cutoff, from_sample_digest=s1.sample_digest, to_sample_digest=s2.sample_digest,
                record_kind=RecordKind.WATCH_ENTRY, p9_root_id="watch-a")
    ok = ReviewStateChange(kind=ChangeKind.CHANGED, changed_fields=(("p9_status", "ACTIVE", "PAUSED"),), **base)
    assert "transition" not in ok.to_json().lower().replace("not_a_transition", "")
    with pytest.raises(ReviewStateError):
        ReviewStateChange(kind=ChangeKind.CHANGED, changed_fields=(("reviewed_at", "a", "b"),), **base)       # 時刻の捏造
    with pytest.raises(ReviewStateError):
        ReviewStateChange(kind=ChangeKind.CHANGED, changed_fields=(("rationale", "a", "b"),), **base)         # 文
    with pytest.raises(ReviewStateError):
        ReviewStateChange(kind=ChangeKind.CHANGED, changed_fields=(), **base)
    with pytest.raises(ReviewStateError):
        ReviewStateChange(kind=ChangeKind.APPEARED, changed_fields=(("p9_status", "A", "B"),), **base)
    with pytest.raises(ReviewStateError):
        ReviewStateChange(kind=ChangeKind.CHANGED, changed_fields=(("p9_status", "A", "A"),), **base)        # 差が無い
    with pytest.raises(ReviewStateError):
        ReviewStateChange(kind=ChangeKind.CHANGED, changed_fields=(("p9_status", "A", "B"),), **{**base, "to_sample_digest": s1.sample_digest})
    with pytest.raises(ReviewStateError):
        ReviewStateChange(kind=ChangeKind.CHANGED, changed_fields=(("p9_status", "A", "B"),), **{**base, "after_cutoff": s2.cutoff, "through_cutoff": s1.cutoff})
