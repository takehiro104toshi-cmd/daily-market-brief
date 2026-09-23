"""P6-B6B — monitoring model / vocabulary（model gate。engine も ruleset も store も作らない）。

finding は derived な観測であって指示ではない。ReviewItemState は「人間が見た」ことの operational 記録であって
governance decision ではない。本 file は runtime で実際の monitoring condition を評価しない。
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.monitoring_model import (ALLOWED_CATEGORIES_BY_STATE_KIND,
                                                                  CONDITION_ID_IS_SEMANTIC, FINDING_ID_PREFIX,
                                                                  FINDING_MEANING, FINDING_NON_MEANING,
                                                                  MONITORING_FINDING_SCHEMA_VERSION,
                                                                  MONITORING_RUN_REPORT_SCHEMA_VERSION,
                                                                  MONITORING_VOCAB_VERSION,
                                                                  REVIEW_IS_NOT_GOVERNANCE,
                                                                  REVIEW_ITEM_STATE_SCHEMA_VERSION,
                                                                  SALIENT_STATE_KEYS, TECHNICAL_CATEGORIES,
                                                                  MonitoringCategory, MonitoringFinding,
                                                                  MonitoringModelError, MonitoringReference,
                                                                  MonitoringRunReport, MonitoringRunStatus,
                                                                  MonitoringSubjectKind, ReviewChainStatus,
                                                                  ReviewDisposition, ReviewItemState, SalientState,
                                                                  SalientStateKind, canonical_monitoring_line,
                                                                  parse_monitoring_record, resolve_review_state)
from src.intelligence.themes.model import ProvenanceClass
from tests.intelligence.test_prediction_record import executable_source, imported_modules

UTC = timezone.utc
T0 = datetime(2026, 9, 20, tzinfo=UTC)
LATER = T0 + timedelta(days=5)
A = "theme_" + "0" * 26
B = "theme_" + "1" * 26
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
MODULE = PACKAGE_DIR / "monitoring_model.py"
SEEDS = tuple(range(11))


def state(kind=SalientStateKind.EVIDENCE_ROLE_PRESENCE, **facts) -> SalientState:
    defaults = {
        SalientStateKind.EVIDENCE_ROLE_PRESENCE: {"theme_root_id": A, "role": "CONTRADICTS"},
        SalientStateKind.EVIDENCE_ABSENCE: {"theme_root_id": A, "absence_kind": "COUNTED_ZERO"},
        SalientStateKind.FRESHNESS_THRESHOLD: {"theme_root_id": A, "threshold_token": "stale_after_days:90"},
        SalientStateKind.SEMANTIC_REVISION: {"theme_root_id": A, "observation_id": "thobs_" + "a" * 24},
        SalientStateKind.LIFECYCLE_DIVERGENCE: {"theme_root_id": A, "governance_state": "ACCEPTED",
                                                "evidence_condition": "NO_VISIBLE_EVIDENCE"},
        SalientStateKind.RETIRED_ROOT_EVIDENCE: {"theme_root_id": A, "attachment_key": "SUPPORTS:doc_x"},
        SalientStateKind.DECISION_BACKLOG: {"proposal_id": "thprop_" + "b" * 24, "proposal_status": "OPEN_DEFERRED",
                                            "threshold_token": "backlog_after_days:30"},
        SalientStateKind.CHAIN_UNRESOLVED: {"chain_kind": "PROPOSAL_DECISION", "diagnostic_code": "FORK",
                                            "subject_token": "thprop_" + "b" * 24},
        SalientStateKind.DISCOVERY_OUTCOME: {"proposal_id": "thprop_" + "c" * 24,
                                             "outcome_token": "NO_ACCEPTED_PROPOSAL"},
        SalientStateKind.VERSION_DRIFT: {"knowledge_name": "theme_taxonomy", "from_version": "0.1.0",
                                         "to_version": "0.2.0"},
        SalientStateKind.RELATION_ENDPOINT_STATE: {"edge_key": "edge|one", "endpoint_role": "SOURCE",
                                                   "endpoint_state": "RETIRED"},
        SalientStateKind.RELATION_PROPOSAL_CONFLICT: {"edge_key": "edge|one",
                                                      "relation_proposal_id": "threlprop_" + "d" * 24,
                                                      "conflict_token": "EDGE_ALREADY_STARTED"},
        SalientStateKind.RELATION_SOURCE_CONTESTED: {"edge_key": "edge|one", "theme_root_id": A,
                                                     "role": "CONTRADICTS"},
        SalientStateKind.AUTHORITY_INTEGRITY: {"authority_name": "relation_proposals", "failure_class": "MALFORMED",
                                               "locator_token": "line:12"},
    }[kind]
    return SalientState(state_kind=kind, facts={**defaults, **facts})


def finding(*, condition_id="CONTRADICTION_EVIDENCE_PRESENT", category=MonitoringCategory.EVIDENCE,
            subject_kind=MonitoringSubjectKind.THEME_ROOT, subject_ref=A, salient=None, cutoff=T0,
            **kw) -> MonitoringFinding:
    return MonitoringFinding.build(condition_id=condition_id, category=category, subject_kind=subject_kind,
                                   subject_ref=subject_ref, salient_state=salient or state(), cutoff=cutoff, **kw)


def report(**kw) -> MonitoringRunReport:
    kw.setdefault("cutoff", T0)
    kw.setdefault("ruleset_version", "monitoring_rules:1.0.0")
    kw.setdefault("recorded_at", kw["cutoff"])
    return MonitoringRunReport.build(**kw)


def review(item=None, *, disposition=ReviewDisposition.ACKNOWLEDGED, actor="reviewer:r1", note="",
           at=T0, supersedes="") -> ReviewItemState:
    return ReviewItemState.build(finding_id=(item or finding()).finding_id, disposition=disposition, actor_ref=actor,
                                 note=note, recorded_at=at, supersedes_review_state_id=supersedes)


def fails(code: str, builder) -> None:
    with pytest.raises(MonitoringModelError) as info:
        builder()
    assert info.value.code == code, info.value.code


# ================================================================ A 語彙


def test_01_the_category_vocabulary_is_exact_and_carries_no_order() -> None:
    assert tuple(c.value for c in MonitoringCategory) == ("EVIDENCE", "SEMANTIC", "LIFECYCLE", "PROPOSAL",
                                                          "DISCOVERY", "RELATION", "INTEGRITY")
    assert TECHNICAL_CATEGORIES == (MonitoringCategory.INTEGRITY,)
    for token in ("LOW", "MEDIUM", "HIGH", "CRITICAL", "MAJOR", "MINOR", "URGENT"):
        assert token not in {c.value for c in MonitoringCategory}, token


def test_02_the_subject_kind_vocabulary_is_exact_and_closed() -> None:
    assert tuple(k.value for k in MonitoringSubjectKind) == ("THEME_ROOT", "THEME_PROPOSAL", "EVIDENCE_PROPOSAL",
                                                             "RELATION_EDGE", "RELATION_PROPOSAL",
                                                             "GOVERNANCE_CHAIN", "AUTHORITY_STORE",
                                                             "KNOWLEDGE_VERSION")
    assert "OTHER" not in {k.value for k in MonitoringSubjectKind}
    assert "GENERIC" not in {k.value for k in MonitoringSubjectKind}


def test_03_the_run_status_vocabulary_has_no_failed_report() -> None:
    assert tuple(s.value for s in MonitoringRunStatus) == ("COMPLETE", "PARTIAL")


def test_04_the_review_disposition_vocabulary_excludes_resolved_and_governance_words() -> None:
    assert tuple(d.value for d in ReviewDisposition) == ("ACKNOWLEDGED", "DISMISSED", "DEFERRED")
    forbidden = {"RESOLVED", "APPROVED", "REJECTED", "ACCEPTED", "PROMOTED", "EXECUTED", "RETIRED"}
    assert forbidden.isdisjoint({d.value for d in ReviewDisposition})


def test_05_every_salient_state_kind_declares_its_identity_keys() -> None:
    assert set(SALIENT_STATE_KEYS) == set(SalientStateKind)
    assert set(ALLOWED_CATEGORIES_BY_STATE_KIND) == set(SalientStateKind)
    for kind, keys in SALIENT_STATE_KEYS.items():
        assert keys == tuple(sorted(keys)), kind
        assert len(keys) == len(set(keys)) and 1 <= len(keys) <= 4, kind


def test_06_the_frozen_meaning_strings_are_unchanged() -> None:
    assert FINDING_MEANING == "a deterministic observation that a condition holds for a subject"
    assert FINDING_NON_MEANING == "an instruction to change any authority"
    assert REVIEW_IS_NOT_GOVERNANCE == "a review disposition records that a person looked, not that a person decided"
    assert CONDITION_ID_IS_SEMANTIC == "a condition_id names the meaning; a changed meaning needs a new condition_id"


# ================================================================ B 不変性


@pytest.mark.parametrize("record,field", [("finding", "condition_id"), ("report", "status"),
                                          ("review", "disposition"), ("state", "state_kind"),
                                          ("reference", "ref_id")])
def test_07_11_every_record_is_immutable(record, field) -> None:
    subject = {"finding": finding, "report": report, "review": review, "state": state,
               "reference": lambda: MonitoringReference(ref_kind="evidence", ref_id="doc_x")}[record]()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(subject, field, "x")


# ================================================================ C / D 直列化と identity


@pytest.mark.parametrize("builder", [finding, report, review])
def test_12_14_canonical_round_trip_is_stable(builder) -> None:
    subject = builder()
    rebuilt = parse_monitoring_record(subject.as_dict())
    assert rebuilt == subject
    assert canonical_monitoring_line(rebuilt) == canonical_monitoring_line(subject)
    assert canonical_monitoring_line(subject).endswith("\n")
    assert json.loads(canonical_monitoring_line(subject))["schema_version"] == subject.schema_version


@pytest.mark.parametrize("builder", [finding, report, review])
def test_15_17_identical_content_yields_identical_ids(builder) -> None:
    assert canonical_monitoring_line(builder()) == canonical_monitoring_line(builder())


def test_18_the_finding_id_is_verified_against_its_content() -> None:
    subject = finding()
    fails("INVALID_RECORD_ID", lambda: dataclasses.replace(subject, condition_id="SOMETHING_ELSE"))
    fails("INVALID_RECORD_ID", lambda: dataclasses.replace(subject, finding_id=FINDING_ID_PREFIX + "_" + "0" * 24))


def test_19_the_run_and_review_ids_are_verified_against_their_content() -> None:
    fails("INVALID_RECORD_ID", lambda: dataclasses.replace(report(), ruleset_version="other:9.9.9"))
    fails("INVALID_RECORD_ID", lambda: dataclasses.replace(review(), actor_ref="reviewer:r2"))


# ================================================================ E 物理順の非依存


@pytest.mark.parametrize("seed", SEEDS)
def test_20_salient_facts_are_order_independent(seed) -> None:
    facts = [("theme_root_id", A), ("governance_state", "ACCEPTED"), ("evidence_condition", "NO_VISIBLE_EVIDENCE")]
    shuffled = list(facts)
    random.Random(seed).shuffle(shuffled)
    left = SalientState(state_kind=SalientStateKind.LIFECYCLE_DIVERGENCE, facts=tuple(facts))
    right = SalientState(state_kind=SalientStateKind.LIFECYCLE_DIVERGENCE, facts=tuple(shuffled))
    assert left == right and left.to_plain() == right.to_plain()


@pytest.mark.parametrize("seed", SEEDS)
def test_21_run_report_collections_are_order_independent(seed) -> None:
    ids = [finding().finding_id, finding(subject_ref=B, salient=state(theme_root_id=B)).finding_id]
    codes = ["INPUT_EXCLUDED", "ALIAS_AMBIGUOUS"]
    versions = [("theme_taxonomy", "0.2.0"), ("entity_catalog", "0.2.0")]
    for collection in (ids, codes, versions):
        random.Random(seed).shuffle(collection)
    left = report(finding_ids=tuple(ids), diagnostics=tuple(codes), knowledge_versions=tuple(versions))
    right = report(finding_ids=tuple(sorted(ids)), diagnostics=tuple(sorted(codes)),
                   knowledge_versions=tuple(sorted(versions)))
    assert left.run_id == right.run_id
    assert canonical_monitoring_line(left) == canonical_monitoring_line(right)


# ================================================================ F〜J 入力の拒否


@pytest.mark.parametrize("builder", [finding, report, review])
def test_22_24_unknown_fields_are_rejected(builder) -> None:
    payload = {**builder().as_dict(), "extra": "x"}
    fails("UNKNOWN_FIELD", lambda: parse_monitoring_record(payload))


@pytest.mark.parametrize("builder", [finding, report, review])
def test_25_27_an_unsupported_schema_version_is_rejected(builder) -> None:
    payload = {**builder().as_dict(), "schema_version": "theme_monitoring_unknown:9.9.9"}
    fails("UNSUPPORTED_SCHEMA_VERSION", lambda: parse_monitoring_record(payload))
    fails("UNSUPPORTED_SCHEMA_VERSION", lambda: parse_monitoring_record({"schema_version": "nope"}))


def test_28_a_naive_datetime_is_rejected_on_construction() -> None:
    fails("INVALID_TIME", lambda: dataclasses.replace(finding(), cutoff=datetime(2026, 9, 20)))
    fails("INVALID_TIME", lambda: dataclasses.replace(review(), recorded_at=datetime(2026, 9, 20)))
    fails("INVALID_TYPE", lambda: dataclasses.replace(finding(), cutoff="2026-09-20T00:00:00Z"))


def test_29_prohibited_content_is_rejected_everywhere_text_is_stored() -> None:
    drive = "D" + ":" + chr(92) + "research"
    unc = chr(92) * 2 + "host" + chr(92) + "share"
    leaked = "https://user:pw@example.invalid/x"
    query = "https://example.invalid/x?api_key=zz"
    for bad in (drive, unc, leaked, query):
        fails("PROHIBITED_CONTENT", lambda bad=bad: review(note=bad))
    for bad in (drive, unc):
        fails("PROHIBITED_CONTENT", lambda bad=bad: state(role=bad))


def test_30_every_text_field_is_bounded() -> None:
    fails("FIELD_TOO_LONG", lambda: review(note="x" * 241))
    fails("FIELD_TOO_LONG", lambda: review(actor="r" * 201))
    fails("FIELD_TOO_LONG", lambda: finding(condition_id="C" * 65))
    fails("TOO_MANY_ITEMS", lambda: report(diagnostics=tuple(f"CODE_{i}" for i in range(65))))


@pytest.mark.parametrize("bad,code", [("has space", "INVALID_TOKEN"), ("  ", "INVALID_TOKEN"),
                                      ("-leading", "INVALID_TOKEN"), ("", "MISSING_FIELD")])
def test_31_identity_bearing_values_must_be_stable_tokens(bad, code) -> None:
    fails(code, lambda: state(role=bad))


def test_32_a_multi_line_value_is_rejected() -> None:
    fails("INVALID_TEXT", lambda: review(note="first\nsecond"))


# ================================================================ K〜M finding identity から除外するもの


def test_33_the_finding_identity_excludes_the_cutoff() -> None:
    """同じ状態は cutoff が違っても同じ finding である（D-B6-3）。"""
    base = finding(cutoff=T0)
    for moment in (T0 + timedelta(microseconds=1), LATER, T0 + timedelta(days=400)):
        assert finding(cutoff=moment).finding_id == base.finding_id
    assert "cutoff" not in base.identity_payload()


def test_34_the_finding_identity_excludes_versions_and_run_provenance() -> None:
    base = finding()
    drifted = finding(condition_version="2.0.0", ruleset_version="monitoring_rules:2.0.0",
                      knowledge_versions={"theme_taxonomy": "0.9.9"})
    assert drifted.finding_id == base.finding_id
    for key in ("condition_version", "ruleset_version", "knowledge_versions", "run_id"):
        assert key not in base.identity_payload(), key


def test_35_the_finding_identity_excludes_presentation_wording() -> None:
    base = finding()
    worded = finding(message_key="theme.contradiction.review")
    assert worded.finding_id == base.finding_id
    assert "message_key" not in base.identity_payload()


def test_36_the_finding_identity_excludes_references_and_diagnostics() -> None:
    base = finding()
    enriched = finding(trigger_refs=(MonitoringReference(ref_kind="attachment", ref_id="CONTRADICTS:doc_a"),),
                       supporting_refs=(MonitoringReference(ref_kind="attachment", ref_id="CONTRADICTS:doc_b"),),
                       diagnostics=("PARTIAL_INPUT",))
    assert enriched.finding_id == base.finding_id
    for key in ("trigger_refs", "supporting_refs", "diagnostics"):
        assert key not in base.identity_payload(), key


def test_37_the_finding_identity_is_exactly_six_keys() -> None:
    assert set(finding().identity_payload()) == {"schema_version", "condition_id", "category", "subject_kind",
                                                 "subject_ref", "salient_state"}


def test_38_a_different_condition_or_subject_is_a_different_finding() -> None:
    base = finding()
    assert finding(condition_id="INVALIDATION_EVIDENCE_PRESENT").finding_id != base.finding_id
    assert finding(subject_ref=B, salient=state(theme_root_id=B)).finding_id != base.finding_id
    assert finding(salient=state(role="INVALIDATES")).finding_id != base.finding_id


# ================================================================ N〜R salient state の安定性


def test_39_the_salient_state_rejects_a_free_form_payload() -> None:
    fails("SALIENT_STATE_KEY_MISMATCH", lambda: state(extra_key="x"))
    fails("SALIENT_STATE_KEY_MISMATCH",
          lambda: SalientState(state_kind=SalientStateKind.EVIDENCE_ROLE_PRESENCE, facts={"theme_root_id": A}))
    fails("INVALID_TYPE", lambda: SalientState.from_dict({"state_kind": "EVIDENCE_ROLE_PRESENCE", "facts": "x"}))
    fails("UNKNOWN_FIELD", lambda: SalientState.from_dict({"state_kind": "EVIDENCE_ROLE_PRESENCE",
                                                           "facts": {}, "note": "x"}))


def test_40_the_salient_state_cannot_hold_a_number_a_time_or_a_score() -> None:
    """値は token 文字列だけ。日数・件数・score を構造的に保持できない。"""
    for bad in (7, 7.5, True, None, T0, ["a"], {"a": 1}):
        with pytest.raises(MonitoringModelError) as info:
            state(role=bad)
        assert info.value.code == "INVALID_TYPE", bad
    source = executable_source(MODULE)
    for token in ("float(", "int(", "Decimal"):
        assert token not in source.split("class SalientState")[1].split("class ")[0], token


@pytest.mark.parametrize("kind", list(SalientStateKind))
def test_41_54_every_state_kind_builds_and_round_trips(kind) -> None:
    subject = state(kind)
    assert SalientState.from_dict(subject.to_plain()) == subject
    assert tuple(subject.fact_map) == SALIENT_STATE_KEYS[kind]
    category = ALLOWED_CATEGORIES_BY_STATE_KIND[kind][0]
    built = finding(condition_id=f"CONDITION_{kind.value}", category=category,
                    subject_kind=MonitoringSubjectKind.AUTHORITY_STORE, subject_ref="authority:x", salient=subject)
    assert built.salient_state == subject


def test_55_a_freshness_finding_does_not_change_every_day() -> None:
    """STALE は「何日 stale か」を identity に持たない。閾値を跨いだという状態だけを持つ。"""
    base = finding(condition_id="THEME_EVIDENCE_STALE", salient=state(SalientStateKind.FRESHNESS_THRESHOLD))
    for day in range(1, 8):
        later = finding(condition_id="THEME_EVIDENCE_STALE", salient=state(SalientStateKind.FRESHNESS_THRESHOLD),
                        cutoff=T0 + timedelta(days=day))
        assert later.finding_id == base.finding_id, day
    assert "age_days" not in SALIENT_STATE_KEYS[SalientStateKind.FRESHNESS_THRESHOLD]


def test_56_a_backlog_finding_does_not_change_every_day() -> None:
    base = finding(condition_id="PROPOSAL_DEFERRED_BEYOND_THRESHOLD", category=MonitoringCategory.PROPOSAL,
                   subject_kind=MonitoringSubjectKind.THEME_PROPOSAL, subject_ref="thprop_" + "b" * 24,
                   salient=state(SalientStateKind.DECISION_BACKLOG))
    for day in range(1, 8):
        later = finding(condition_id="PROPOSAL_DEFERRED_BEYOND_THRESHOLD", category=MonitoringCategory.PROPOSAL,
                        subject_kind=MonitoringSubjectKind.THEME_PROPOSAL, subject_ref="thprop_" + "b" * 24,
                        salient=state(SalientStateKind.DECISION_BACKLOG), cutoff=T0 + timedelta(days=day))
        assert later.finding_id == base.finding_id, day
    assert "age_days" not in SALIENT_STATE_KEYS[SalientStateKind.DECISION_BACKLOG]


def test_57_an_extra_contradicting_evidence_does_not_create_a_second_finding() -> None:
    """「CONTRADICTS が存在する」の identity に evidence 集合を入れない（§10）。"""
    one = finding(trigger_refs=(MonitoringReference(ref_kind="attachment", ref_id="CONTRADICTS:doc_a"),))
    two = finding(trigger_refs=(MonitoringReference(ref_kind="attachment", ref_id="CONTRADICTS:doc_a"),
                                MonitoringReference(ref_kind="attachment", ref_id="CONTRADICTS:doc_b"),))
    assert one.finding_id == two.finding_id
    assert len(two.trigger_refs) == 2                                  # 根拠は provenance として残る


def test_58_a_new_evidence_on_a_retired_root_is_its_own_finding() -> None:
    """逆に、撤退 root への evidence は 1 件ごとに review 対象であるため identity を担う。"""
    left = finding(condition_id="RETIRED_ROOT_RECEIVED_EVIDENCE", category=MonitoringCategory.LIFECYCLE,
                   salient=state(SalientStateKind.RETIRED_ROOT_EVIDENCE, attachment_key="SUPPORTS:doc_a"))
    right = finding(condition_id="RETIRED_ROOT_RECEIVED_EVIDENCE", category=MonitoringCategory.LIFECYCLE,
                    salient=state(SalientStateKind.RETIRED_ROOT_EVIDENCE, attachment_key="SUPPORTS:doc_b"))
    assert left.finding_id != right.finding_id


def test_59_the_same_integrity_failure_converges_on_one_finding() -> None:
    fingerprint = state(SalientStateKind.AUTHORITY_INTEGRITY)
    runs = [finding(condition_id="AUTHORITY_STORE_CORRUPT", category=MonitoringCategory.INTEGRITY,
                    subject_kind=MonitoringSubjectKind.AUTHORITY_STORE, subject_ref="authority:relation_proposals",
                    salient=fingerprint, cutoff=T0 + timedelta(days=day)) for day in range(5)]
    assert len({item.finding_id for item in runs}) == 1
    other = finding(condition_id="AUTHORITY_STORE_CORRUPT", category=MonitoringCategory.INTEGRITY,
                    subject_kind=MonitoringSubjectKind.AUTHORITY_STORE, subject_ref="authority:relation_proposals",
                    salient=state(SalientStateKind.AUTHORITY_INTEGRITY, locator_token="line:99"))
    assert other.finding_id != runs[0].finding_id


def test_60_a_state_kind_cannot_be_filed_under_the_wrong_category() -> None:
    fails("CATEGORY_STATE_MISMATCH", lambda: finding(category=MonitoringCategory.INTEGRITY))
    fails("CATEGORY_STATE_MISMATCH",
          lambda: finding(condition_id="X", category=MonitoringCategory.EVIDENCE,
                          subject_kind=MonitoringSubjectKind.AUTHORITY_STORE, subject_ref="authority:x",
                          salient=state(SalientStateKind.AUTHORITY_INTEGRITY)))
    for kind, categories in ALLOWED_CATEGORIES_BY_STATE_KIND.items():
        if kind in (SalientStateKind.CHAIN_UNRESOLVED, SalientStateKind.AUTHORITY_INTEGRITY):
            assert categories == (MonitoringCategory.INTEGRITY,), kind
        else:
            assert MonitoringCategory.INTEGRITY not in categories, kind


def test_61_a_theme_root_subject_must_carry_a_theme_root_id() -> None:
    fails("UNKNOWN_THEME_ROOT", lambda: finding(subject_ref="not_a_root"))
    fails("UNKNOWN_THEME_ROOT", lambda: state(theme_root_id="not_a_root"))


# ================================================================ S〜Y run report


def test_62_the_run_identity_includes_the_cutoff() -> None:
    """finding とは逆に、run identity は cutoff を担う（同じ座標の run は同じ run）。"""
    base = report()
    assert report(cutoff=LATER).run_id != base.run_id
    assert "cutoff" in base.identity_payload()


def test_63_the_run_identity_includes_the_ruleset_and_knowledge_versions() -> None:
    base = report()
    assert report(ruleset_version="monitoring_rules:2.0.0").run_id != base.run_id
    assert report(knowledge_versions={"theme_taxonomy": "0.2.0"}).run_id != base.run_id
    assert {"ruleset_version", "knowledge_versions"} <= set(base.identity_payload())


def test_64_the_run_identity_includes_the_input_digests() -> None:
    base = report()
    assert report(input_digests={"theme_roots": "a" * 24}).run_id != base.run_id
    assert report(input_digests={"theme_roots": "b" * 24}).run_id \
        != report(input_digests={"theme_roots": "a" * 24}).run_id
    assert "input_digests" in base.identity_payload()


def test_65_the_run_identity_excludes_the_execution_time_and_the_results() -> None:
    base = report()
    assert report(recorded_at=T0 + timedelta(hours=9)).run_id == base.run_id
    assert report(finding_ids=(finding().finding_id,)).run_id == base.run_id
    assert report(diagnostics=("INPUT_EXCLUDED",)).run_id == base.run_id
    assert set(base.identity_payload()) == {"schema_version", "cutoff", "ruleset_version", "knowledge_versions",
                                            "input_digests"}


def test_66_a_partial_run_must_name_what_it_could_not_evaluate() -> None:
    fails("PARTIAL_RUN_WITHOUT_REASON", lambda: report(status=MonitoringRunStatus.PARTIAL))
    partial = report(status=MonitoringRunStatus.PARTIAL, unevaluated_conditions=("RELATION_ENDPOINT_RETIRED",),
                     diagnostics=("AUTHORITY_UNREADABLE",))
    assert partial.status is MonitoringRunStatus.PARTIAL
    assert partial.unevaluated_conditions == ("RELATION_ENDPOINT_RETIRED",)


def test_67_a_complete_run_cannot_silently_hide_an_unevaluated_condition() -> None:
    """authority が読めなかった run を「finding 0 件で COMPLETE」にできない。"""
    fails("INCOMPLETE_RUN_MARKED_COMPLETE",
          lambda: report(status=MonitoringRunStatus.COMPLETE, unevaluated_conditions=("THEME_EVIDENCE_STALE",)))
    empty = report()
    assert empty.status is MonitoringRunStatus.COMPLETE and empty.finding_ids == ()
    assert empty.unevaluated_conditions == ()


def test_68_a_run_cannot_be_recorded_before_its_cutoff() -> None:
    fails("REPORT_BEFORE_CUTOFF", lambda: report(recorded_at=T0 - timedelta(microseconds=1)))
    assert report(recorded_at=T0).recorded_at == T0


def test_69_the_run_report_only_holds_well_formed_finding_ids() -> None:
    fails("INVALID_RECORD_ID", lambda: report(finding_ids=("thprop_" + "a" * 24,)))
    fails("DUPLICATE_CODE", lambda: report(finding_ids=(finding().finding_id, finding().finding_id)))


# ================================================================ Z〜AD review state


def test_70_a_review_state_is_recorded_by_a_person_only() -> None:
    subject = review()
    assert subject.actor_class is ProvenanceClass.HUMAN
    for actor in (ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL):
        fails("FORBIDDEN_REVIEW_AUTHORITY",
              lambda actor=actor: ReviewItemState.from_dict({**subject.as_dict(), "actor_class": actor.value}))


def test_71_a_review_state_binds_to_a_monitoring_finding_only() -> None:
    fails("INVALID_RECORD_ID", lambda: ReviewItemState.build(finding_id="thprop_" + "a" * 24,
                                                             disposition=ReviewDisposition.ACKNOWLEDGED,
                                                             actor_ref="reviewer:r1", recorded_at=T0))


def test_72_the_same_review_content_yields_the_same_review_id() -> None:
    assert review().review_state_id == review().review_state_id
    assert review(at=LATER).review_state_id == review().review_state_id         # 時刻は identity 外
    assert review(note="checked the release").review_state_id != review().review_state_id
    assert review(disposition=ReviewDisposition.DISMISSED).review_state_id != review().review_state_id
    assert "recorded_at" not in review().identity_payload()


def test_73_a_review_chain_resolves_by_predecessor_not_by_time() -> None:
    item = finding()
    first = review(item, disposition=ReviewDisposition.DEFERRED, note="waiting for a second reader")
    second = review(item, disposition=ReviewDisposition.ACKNOWLEDGED, at=T0 + timedelta(hours=1),
                    supersedes=first.review_state_id)
    for order in ((first, second), (second, first)):
        resolution = resolve_review_state(item.finding_id, order)
        assert resolution.status is ReviewChainStatus.RESOLVED
        assert resolution.terminal == second and resolution.chain == (first.review_state_id, second.review_state_id)
    stray = review(item, disposition=ReviewDisposition.DISMISSED, at=T0 + timedelta(days=9), note="late stray")
    assert resolve_review_state(item.finding_id, (first, second, stray)).status is ReviewChainStatus.UNRESOLVED


def test_74_no_review_state_resolves_to_none() -> None:
    resolution = resolve_review_state(finding().finding_id, ())
    assert resolution.status is ReviewChainStatus.NONE and resolution.terminal is None


def test_75_a_predecessor_from_another_finding_is_rejected() -> None:
    mine, other = finding(), finding(subject_ref=B, salient=state(theme_root_id=B))
    foreign = review(other, note="reviewed the other item")
    crossed = review(mine, at=T0 + timedelta(hours=1), supersedes=foreign.review_state_id, note="wrong predecessor")
    resolution = resolve_review_state(mine.finding_id, (foreign, crossed))
    assert resolution.status is ReviewChainStatus.INVALID
    assert resolution.diagnostics == ("CROSS_FINDING_PREDECESSOR",)


def test_76_a_dangling_or_forked_review_chain_fails_closed() -> None:
    item = finding()
    orphan = review(item, supersedes="thmrev_" + "0" * 24)
    assert resolve_review_state(item.finding_id, (orphan,)).diagnostics == ("DANGLING_PREDECESSOR",)
    seed = review(item, disposition=ReviewDisposition.DEFERRED, note="seed")
    left = review(item, disposition=ReviewDisposition.ACKNOWLEDGED, at=T0 + timedelta(hours=1),
                  supersedes=seed.review_state_id, note="branch one")
    right = review(item, disposition=ReviewDisposition.DISMISSED, at=T0 + timedelta(hours=2),
                   supersedes=seed.review_state_id, note="branch two")
    assert resolve_review_state(item.finding_id, (seed, left, right)).diagnostics == ("FORK",)


def test_77_a_review_state_cannot_supersede_itself() -> None:
    subject = review()
    fails("INVALID_RECORD", lambda: dataclasses.replace(subject,
                                                        supersedes_review_state_id=subject.review_state_id))


# ================================================================ AE〜AF 隠れた authority の不在


FORBIDDEN_FINDING_FIELDS = ("approve", "reject", "promote", "mutate", "execute", "attach", "buy", "sell",
                            "target_price", "probability", "confidence_score", "severity", "rank", "priority_score",
                            "weight", "score", "stance", "recommendation", "signal")


@pytest.mark.parametrize("builder", [finding, report, review])
def test_78_80_no_record_carries_a_governance_or_scoring_field(builder) -> None:
    fields = set(dataclasses.asdict(builder()))
    for token in FORBIDDEN_FINDING_FIELDS:
        assert not any(token in name for name in fields), token
    body = json.dumps(builder().as_dict()).lower()
    for token in ("target_price", "probability", "confidence", "severity", "priority", "recommendation"):
        assert token not in body, token


def test_81_the_model_carries_no_governance_or_execution_vocabulary() -> None:
    source = executable_source(MODULE)
    for token in ("RelationAssertionPlan", "EvidenceAttachmentPlan", "append_assertion", "append_proposal",
                  "ThemeStore", "execute", "promote", "AUTO_ACCEPT", "governance_action"):
        assert token not in source, token


def test_82_the_model_carries_no_ordinal_or_scoring_vocabulary() -> None:
    source = executable_source(MODULE)
    for token in ("severity", "priority", "probability", "centrality", "pagerank", "ranking"):
        assert token.lower() not in source.lower(), token


# ================================================================ AG 時計 / 乱数 / network / LLM の不在


def test_83_the_model_reads_no_clock_and_no_randomness() -> None:
    source = executable_source(MODULE)
    for token in (".now(", "utcnow", "time.time", "random.", "secrets.", "uuid", "monotonic", "new_ulid", "new_id("):
        assert token not in source, token


def test_84_the_model_reaches_no_network_no_storage_and_no_model_provider() -> None:
    source = executable_source(MODULE)
    for token in ("requests", "urllib", "socket", "httpx", "sqlite", "subprocess", "anthropic", "openai",
                  "transformers", "embedding", "nltk", "spacy", "open(", "Path("):
        assert token not in source, token


# ================================================================ AH import 境界


def test_85_the_monitoring_model_imports_only_the_pure_foundation_surface() -> None:
    modules = imported_modules(MODULE)
    assert set(modules) <= {"__future__", "json", "re", "dataclasses", "datetime", "enum", "typing",
                            "..core.ids", "..core.time", "..themes.model"}, sorted(modules)


def test_86_the_monitoring_model_imports_no_b1_to_b5_runtime() -> None:
    source = executable_source(MODULE)
    for token in ("change", "lifecycle", "proposal_model", "proposal_store", "dedup", "discovery", "taxonomy",
                  "entity_catalog", "knowledge_loader", "relation_model", "relation_store", "evidence_bridge"):
        assert f"from .{token}" not in source and f"import {token}" not in source, token


def test_87_nothing_outside_the_theme_intelligence_package_imports_the_model() -> None:
    """model を参照してよいのは同じ package の monitoring 層だけ（B6C の engine / rules を含む）。"""
    hits = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        if path == MODULE or path.parent == PACKAGE_DIR:
            continue
        if "monitoring_model" in executable_source(path):
            hits.append(str(path.relative_to(REPO_ROOT)))
    assert hits == [], hits
    inside = sorted(p.stem for p in PACKAGE_DIR.glob("*.py") if "monitoring_model" in executable_source(p))
    assert inside == ["monitoring_engine", "monitoring_rules"], inside      # model 自身は自分を名指さない


def test_88_no_store_runner_scheduler_or_notifier_was_created() -> None:
    """B6B の model gate が禁じた operational 面は、B6C の engine / ruleset 追加後も存在しない。"""
    present = sorted(p.stem for p in PACKAGE_DIR.glob("monitoring*.py"))
    assert present == ["monitoring_engine", "monitoring_model", "monitoring_rules"], present
    for stem in ("monitoring_store", "monitoring_runner", "monitoring_scheduler", "monitoring_notifier",
                 "monitoring_review_store"):
        assert not (PACKAGE_DIR / f"{stem}.py").exists(), stem
