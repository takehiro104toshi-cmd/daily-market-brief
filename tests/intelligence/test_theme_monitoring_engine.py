"""P6-B6C — monitoring engine ＋ versioned ruleset（純評価 gate。store も runner も作らない）。

engine は既存の derived 状態を指差すだけで、新しい主張も governance action も作らない。
本 file の corpus 結果は **synthetic gate result only** であり、実世界の precision / recall を主張しない。
"""
from __future__ import annotations

import dataclasses
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.knowledge_loader import KnowledgeError
from src.intelligence.theme_intelligence.monitoring_engine import (ENGINE_EMITS_OBSERVATIONS_ONLY,
                                                                   MONITORING_ENGINE_VERSION,
                                                                   AuthorityFailureSnapshot, KnowledgeDriftSnapshot,
                                                                   MonitoringEngineError, MonitoringEvaluationInput,
                                                                   ProposalSnapshot, RelationProposalSnapshot,
                                                                   RelationSnapshot, SubjectAvailability,
                                                                   ThemeSnapshot, evaluate_monitoring)
from src.intelligence.theme_intelligence.monitoring_model import (MonitoringCategory, MonitoringRunStatus,
                                                                  canonical_monitoring_line)
from src.intelligence.theme_intelligence.monitoring_rules import (CONDITION_REGISTRY, MONITORING_RULES_SCHEMA_VERSION,
                                                                  PROHIBITED_RULE_KEYS, REQUIRED_CONDITION_IDS,
                                                                  compute_monitoring_rules_digest,
                                                                  load_monitoring_rules_version,
                                                                  monitoring_rules_path)
from tests.intelligence.test_prediction_record import executable_source, imported_modules

UTC = timezone.utc
T0 = datetime(2026, 9, 30, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
RULES_PATH = KNOWLEDGE_ROOT / "theme_intelligence" / "monitoring_rules.0.1.0.yaml"
ENGINE = PACKAGE_DIR / "monitoring_engine.py"
RULES_MODULE = PACKAGE_DIR / "monitoring_rules.py"
A = "theme_" + "0" * 26
B = "theme_" + "1" * 26
PROPOSAL = "thprop_" + "a" * 24
EDGE = "theme_0|theme_1|CAUSES|SOURCE_ASSERTED|publisher_x"
SEEDS = tuple(range(11))


def ruleset(cutoff=T0):
    return load_monitoring_rules_version(RULES_PATH, expected_version="0.1.0", cutoff=cutoff)


RULES = ruleset()


def evaluate(*, cutoff=T0, recorded_at=None, rules=None, **kw):
    return evaluate_monitoring(MonitoringEvaluationInput(cutoff=cutoff, **kw), ruleset=rules or RULES,
                               recorded_at=recorded_at or cutoff)


def theme(**kw) -> ThemeSnapshot:
    kw.setdefault("theme_root_id", A)
    return ThemeSnapshot(**kw)


def proposal(**kw) -> ProposalSnapshot:
    kw.setdefault("proposal_id", PROPOSAL)
    return ProposalSnapshot(**kw)


def relation(**kw) -> RelationSnapshot:
    kw.setdefault("edge_key", EDGE)
    kw.setdefault("edge_state", "ACTIVE")
    return RelationSnapshot(**kw)


def ids(evaluation) -> list:
    return [item.condition_id for item in evaluation.findings]


def one(evaluation, condition_id):
    matches = [item for item in evaluation.findings if item.condition_id == condition_id]
    assert len(matches) == 1, (condition_id, ids(evaluation))
    return matches[0]


# ================================================================ ruleset loader


def test_01_the_published_ruleset_loads_with_an_exact_version_and_digest() -> None:
    rules = ruleset()
    assert rules.schema_version == MONITORING_RULES_SCHEMA_VERSION and rules.ruleset_version == "0.1.0"
    assert rules.content_digest == compute_monitoring_rules_digest(RULES_PATH)
    assert len(rules.rules) == len(REQUIRED_CONDITION_IDS) == 18
    assert rules.enabled_condition_ids == REQUIRED_CONDITION_IDS
    assert monitoring_rules_path(KNOWLEDGE_ROOT, "0.1.0") == RULES_PATH


def test_02_every_registry_condition_is_declared_exactly_once() -> None:
    declared = [rule.condition_id for rule in ruleset().rules]
    assert sorted(declared) == list(REQUIRED_CONDITION_IDS) and len(declared) == len(set(declared))
    for rule in ruleset().rules:
        spec = CONDITION_REGISTRY[rule.condition_id]
        assert rule.spec is spec
        assert (rule.threshold_days is not None) is spec.needs_threshold_days


def test_03_only_b6_owned_thresholds_live_in_the_ruleset() -> None:
    """stale の日数は B2 LifecyclePolicy が所有するため ruleset に無い。提案の滞留だけが B6 の所有。"""
    thresholds = {r.condition_id: r.threshold_days for r in ruleset().rules if r.threshold_days is not None}
    assert set(thresholds) == {"THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD", "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD"}
    body = RULES_PATH.read_text(encoding="utf-8")
    for token in ("stale_after_days", "stale_days", "freshness_days"):
        assert token not in body, token


def test_04_a_wrong_version_or_a_future_ruleset_is_refused() -> None:
    with pytest.raises(KnowledgeError) as info:
        load_monitoring_rules_version(RULES_PATH, expected_version="0.2.0", cutoff=T0)
    assert info.value.code == "VERSION_MISMATCH"
    with pytest.raises(KnowledgeError) as info:
        load_monitoring_rules_version(RULES_PATH, expected_version="0.1.0", cutoff=datetime(2026, 1, 1, tzinfo=UTC))
    assert info.value.code == "FUTURE_VERSION"


def write_rules(tmp_path: Path, *, mutate=None, drop=None) -> Path:
    import yaml
    document = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    if mutate:
        mutate(document)
    if drop:
        document["conditions"] = [c for c in document["conditions"] if c["condition_id"] != drop]
    target = tmp_path / "theme_intelligence"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "monitoring_rules.0.1.0.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return path


def reseal(path: Path) -> Path:
    import yaml
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["content_digest"] = ""
    path.write_text(yaml.safe_dump(document, sort_keys=True, allow_unicode=True), encoding="utf-8")
    digest = compute_monitoring_rules_digest(path)
    document["content_digest"] = digest
    path.write_text(yaml.safe_dump(document, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return path


def loader_fails(code: str, path: Path) -> None:
    with pytest.raises(KnowledgeError) as info:
        load_monitoring_rules_version(path, expected_version="0.1.0", cutoff=T0)
    assert info.value.code == code, info.value.code


def test_05_a_tampered_ruleset_fails_the_digest(tmp_path) -> None:
    path = write_rules(tmp_path, mutate=lambda d: d["conditions"][0].update({"enabled": False}))
    loader_fails("DIGEST_MISMATCH", path)


def test_06_an_unknown_condition_id_is_refused(tmp_path) -> None:
    path = reseal(write_rules(tmp_path, mutate=lambda d: d["conditions"][0].update({"condition_id": "MADE_UP"})))
    loader_fails("UNSUPPORTED_CONDITION_ID", path)


def test_07_a_mismatched_category_subject_or_state_mapping_is_refused(tmp_path) -> None:
    for key, value in (("category", "INTEGRITY"), ("subject_kind", "AUTHORITY_STORE"),
                       ("salient_state_kind", "AUTHORITY_INTEGRITY")):
        path = reseal(write_rules(tmp_path / key, mutate=lambda d, k=key, v=value: d["conditions"][1].update({k: v})))
        loader_fails("CONDITION_MAPPING_MISMATCH", path)


def test_08_a_duplicate_or_missing_condition_is_refused(tmp_path) -> None:
    path = reseal(write_rules(tmp_path / "dup",
                              mutate=lambda d: d["conditions"].append(dict(d["conditions"][0]))))
    loader_fails("DUPLICATE_CONDITION_ID", path)
    path = reseal(write_rules(tmp_path / "missing", drop="KNOWLEDGE_VERSION_DRIFT"))
    loader_fails("MISSING_CONDITION", path)


@pytest.mark.parametrize("key", ["expression", "python", "eval", "regex", "prompt", "model", "weight", "score",
                                 "priority", "probability", "severity", "rank", "confidence", "stance"])
def test_09_22_any_execution_or_scoring_key_is_refused(tmp_path, key) -> None:
    assert key in PROHIBITED_RULE_KEYS
    path = reseal(write_rules(tmp_path / key, mutate=lambda d, k=key: d["conditions"][0].update({k: "x"})))
    loader_fails("PROHIBITED_RULE_KEY", path)


def test_23_an_unknown_key_or_a_coerced_type_is_refused(tmp_path) -> None:
    path = reseal(write_rules(tmp_path / "unknown", mutate=lambda d: d["conditions"][0].update({"note": "x"})))
    loader_fails("UNKNOWN_FIELD", path)
    path = reseal(write_rules(tmp_path / "yes", mutate=lambda d: d["conditions"][0].update({"enabled": "yes"})))
    loader_fails("INVALID_TYPE", path)
    path = reseal(write_rules(tmp_path / "num", mutate=lambda d: d["conditions"][0].update({"condition_version": 1})))
    loader_fails("INVALID_TYPE", path)


def test_24_a_threshold_is_bounded_and_owned_only_where_declared(tmp_path) -> None:
    def set_threshold(document, condition_id, value):
        for item in document["conditions"]:
            if item["condition_id"] == condition_id:
                item["threshold_days"] = value

    path = reseal(write_rules(tmp_path / "zero",
                              mutate=lambda d: set_threshold(d, "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD", 0)))
    loader_fails("INVALID_THRESHOLD", path)
    path = reseal(write_rules(tmp_path / "huge",
                              mutate=lambda d: set_threshold(d, "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD", 99999)))
    loader_fails("INVALID_THRESHOLD", path)
    path = reseal(write_rules(tmp_path / "extra",
                              mutate=lambda d: set_threshold(d, "THEME_EVIDENCE_STALE", 10)))
    loader_fails("THRESHOLD_FORBIDDEN", path)
    path = reseal(write_rules(tmp_path / "gone",
                              mutate=lambda d: [c.pop("threshold_days") for c in d["conditions"]
                                                if c["condition_id"] == "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD"]))
    loader_fails("MISSING_THRESHOLD", path)


def test_25_a_disabled_condition_emits_nothing(tmp_path) -> None:
    def disable(document):
        for item in document["conditions"]:
            if item["condition_id"] == "THEME_CONTRADICTION_EVIDENCE_PRESENT":
                item["enabled"] = False

    path = reseal(write_rules(tmp_path, mutate=disable))
    rules = load_monitoring_rules_version(path, expected_version="0.1.0", cutoff=T0)
    assert "THEME_CONTRADICTION_EVIDENCE_PRESENT" not in rules.enabled_condition_ids
    found = evaluate(rules=rules, themes=(theme(evidence_roles_present=("CONTRADICTS",)),))
    assert ids(found) == []


# ================================================================ condition ごとの TRUE / FALSE / UNAVAILABLE


TRUE_CASES = (
    ("THEME_CONTRADICTION_EVIDENCE_PRESENT", dict(themes=(theme(evidence_roles_present=("CONTRADICTS",)),))),
    ("THEME_INVALIDATION_EVIDENCE_PRESENT", dict(themes=(theme(evidence_roles_present=("INVALIDATES",)),))),
    ("THEME_WITHOUT_COUNTED_EVIDENCE", dict(themes=(theme(evidence_flags=("NO_VISIBLE_EVIDENCE",)),))),
    ("THEME_EVIDENCE_STALE", dict(themes=(theme(evidence_flags=("STALE",),
                                                freshness_policy_token="stale_after_days:90"),))),
    ("ACCEPTED_THEME_SEMANTIC_REVISION", dict(themes=(theme(governance_state="ACCEPTED",
                                                            semantic_revision_observation_id="thobs_" + "a" * 24),))),
    ("RETIRED_ROOT_RECEIVED_EVIDENCE", dict(themes=(theme(governance_state="RETIRED",
                                                          arrived_attachment_keys=("SUPPORTS:doc_a",)),))),
    ("GOVERNANCE_EVIDENCE_DIVERGENCE", dict(themes=(theme(governance_state="ACCEPTED",
                                                          evidence_flags=("NO_VISIBLE_EVIDENCE",)),))),
    ("THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD", dict(proposals=(proposal(proposal_status="OPEN",
                                                                      created_at=T0 - timedelta(days=61)),))),
    ("THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD", dict(proposals=(proposal(proposal_status="OPEN_DEFERRED",
                                                                          created_at=T0 - timedelta(days=31)),))),
    ("PROPOSAL_DECISION_CHAIN_UNRESOLVED", dict(proposals=(proposal(decision_chain_status="UNRESOLVED",
                                                                    decision_chain_diagnostic="FORK"),))),
    ("DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL",
     dict(proposals=(proposal(discovery_outcome_token="NO_ACCEPTED_PROPOSAL"),))),
    ("ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT",
     dict(proposals=(proposal(discovery_outcome_token="NO_OBSERVED_EFFECT"),))),
    ("KNOWLEDGE_VERSION_DRIFT", dict(knowledge_drift=(KnowledgeDriftSnapshot(knowledge_name="theme_taxonomy",
                                                                             from_version="0.1.0",
                                                                             to_version="0.2.0"),))),
    ("RELATION_ENDPOINT_NOT_ACTIVE", dict(relations=(relation(source_endpoint_state="RETIRED"),))),
    ("RETRACTED_RELATION_HAS_NEW_PROPOSAL",
     dict(relation_proposals=(RelationProposalSnapshot(relation_proposal_id="threlprop_" + "b" * 24, edge_key=EDGE,
                                                       conflict_token="RELATION_RETRACTED"),))),
    ("SOURCE_ASSERTED_RELATION_CONTESTED", dict(relations=(relation(assertion_class="SOURCE_ASSERTED",
                                                                    contested_theme_root_id=A,
                                                                    contested_role="CONTRADICTS"),))),
    ("RELATION_GOVERNANCE_CHAIN_UNRESOLVED", dict(relations=(relation(governance_chain_status="INVALID",
                                                                      governance_chain_diagnostic="CYCLE"),))),
    ("AUTHORITY_STATE_UNUSABLE",
     dict(authority_failures=(AuthorityFailureSnapshot(authority_name="theme_roots", failure_class="MALFORMED_JSON",
                                                       locator_token="line:12"),))),
)


@pytest.mark.parametrize("condition_id,payload", TRUE_CASES, ids=[row[0] for row in TRUE_CASES])
def test_26_43_every_mvp_condition_fires_on_its_true_case(condition_id, payload) -> None:
    found = evaluate(**payload)
    item = one(found, condition_id)
    spec = CONDITION_REGISTRY[condition_id]
    assert item.category is spec.category and item.subject_kind is spec.subject_kind
    assert item.salient_state.state_kind is spec.salient_state_kind
    assert item.ruleset_version == "0.1.0" and item.message_key
    assert found.report.status is MonitoringRunStatus.COMPLETE


def test_44_the_registry_and_the_true_case_matrix_cover_the_same_conditions() -> None:
    assert sorted(row[0] for row in TRUE_CASES) == list(REQUIRED_CONDITION_IDS)


# ================================================================ §25 false-positive 合成 gate（synthetic only）


CLEAN_CASES = (
    ("supports_only", dict(themes=(theme(governance_state="ACCEPTED", evidence_roles_present=("SUPPORTS",),
                                         evidence_flags=("HAS_SUPPORT", "MULTI_SOURCE", "QUALIFIES")),))),
    ("fresh_theme", dict(themes=(theme(governance_state="ACCEPTED", evidence_roles_present=("SUPPORTS",),
                                       evidence_flags=("HAS_SUPPORT",), freshness_policy_token="stale_after_days:90"),))),
    ("proposal_below_threshold", dict(proposals=(proposal(proposal_status="OPEN_DEFERRED",
                                                          created_at=T0 - timedelta(days=29),
                                                          decision_chain_status="RESOLVED"),))),
    ("open_below_threshold", dict(proposals=(proposal(proposal_status="OPEN", created_at=T0 - timedelta(days=59),
                                                      decision_chain_status="RESOLVED"),))),
    ("active_relation", dict(relations=(relation(source_endpoint_state="EXISTS_AT_CUTOFF",
                                                 target_endpoint_state="EXISTS_AT_CUTOFF",
                                                 assertion_class="HUMAN_ASSERTED",
                                                 governance_chain_status="RESOLVED"),))),
    ("ordinary_source_asserted", dict(relations=(relation(assertion_class="SOURCE_ASSERTED",
                                                          source_endpoint_state="EXISTS_AT_CUTOFF",
                                                          target_endpoint_state="EXISTS_AT_CUTOFF",
                                                          governance_chain_status="RESOLVED"),))),
    ("clean_chain", dict(proposals=(proposal(proposal_status="ACCEPTED", created_at=T0 - timedelta(days=400),
                                             decision_chain_status="RESOLVED"),))),
    ("no_drift", dict(knowledge_drift=(KnowledgeDriftSnapshot(knowledge_name="theme_taxonomy", from_version="0.2.0",
                                                              to_version="0.2.0"),))),
    ("retired_without_new_evidence", dict(themes=(theme(governance_state="RETIRED"),))),
)


@pytest.mark.parametrize("label,payload", CLEAN_CASES, ids=[row[0] for row in CLEAN_CASES])
def test_45_53_normal_operation_raises_no_finding(label, payload) -> None:
    """**synthetic gate result only** — 実世界の precision / recall を主張しない。"""
    found = evaluate(**payload)
    assert found.findings == (), (label, ids(found))
    assert found.report.status is MonitoringRunStatus.COMPLETE
    assert found.report.unevaluated_conditions == ()


def test_54_a_fully_clean_world_produces_an_empty_complete_run() -> None:
    found = evaluate(themes=(theme(governance_state="ACCEPTED", evidence_roles_present=("SUPPORTS",),
                                   evidence_flags=("HAS_SUPPORT", "QUALIFIES"),
                                   freshness_policy_token="stale_after_days:90"),),
                     proposals=(proposal(proposal_status="ACCEPTED", created_at=T0, decision_chain_status="RESOLVED"),),
                     relations=(relation(source_endpoint_state="EXISTS_AT_CUTOFF",
                                         target_endpoint_state="EXISTS_AT_CUTOFF",
                                         governance_chain_status="RESOLVED"),))
    assert found.findings == () and found.report.status is MonitoringRunStatus.COMPLETE


# ================================================================ §10 PARTIAL / fail-closed


@pytest.mark.parametrize("kind", ["theme", "proposal", "relation", "relation_proposal"])
def test_55_58_an_unusable_subject_never_reads_as_condition_false(kind) -> None:
    broken = {"theme": dict(themes=(theme(availability=SubjectAvailability.UNAVAILABLE,
                                          authority_name="theme_observations", failure_class="STORE_CORRUPTION"),)),
              "proposal": dict(proposals=(proposal(availability=SubjectAvailability.UNAVAILABLE,
                                                   authority_name="proposals", failure_class="INVALID_HISTORY"),)),
              "relation": dict(relations=(relation(availability=SubjectAvailability.UNAVAILABLE,
                                                   authority_name="relation_assertions",
                                                   failure_class="NON_CANONICAL_LINE"),)),
              "relation_proposal": dict(relation_proposals=(
                  RelationProposalSnapshot(relation_proposal_id="threlprop_" + "c" * 24, edge_key=EDGE,
                                           availability=SubjectAvailability.UNAVAILABLE,
                                           authority_name="relation_proposals",
                                           failure_class="UNSUPPORTED_SCHEMA_VERSION"),))}[kind]
    found = evaluate(**broken)
    assert found.report.status is MonitoringRunStatus.PARTIAL
    assert found.report.unevaluated_conditions != ()
    integrity = one(found, "AUTHORITY_STATE_UNUSABLE")
    assert integrity.category is MonitoringCategory.INTEGRITY
    assert found.report.diagnostics != ()


def test_59_an_authority_failure_marks_the_conditions_it_blocks() -> None:
    found = evaluate(authority_failures=(AuthorityFailureSnapshot(
        authority_name="relation_assertions", failure_class="TRUNCATED_FINAL_LINE",
        blocked_condition_ids=("RELATION_ENDPOINT_NOT_ACTIVE", "SOURCE_ASSERTED_RELATION_CONTESTED")),))
    assert found.report.status is MonitoringRunStatus.PARTIAL
    assert found.report.unevaluated_conditions == ("RELATION_ENDPOINT_NOT_ACTIVE",
                                                   "SOURCE_ASSERTED_RELATION_CONTESTED")
    assert one(found, "AUTHORITY_STATE_UNUSABLE").salient_state.fact_map["failure_class"] == "TRUNCATED_FINAL_LINE"


def test_60_an_unknown_blocked_condition_id_fails_closed() -> None:
    with pytest.raises(MonitoringEngineError) as info:
        evaluate(authority_failures=(AuthorityFailureSnapshot(authority_name="x", failure_class="y",
                                                              blocked_condition_ids=("MADE_UP",)),))
    assert info.value.code == "UNKNOWN_CONDITION_ID"


def test_61_a_missing_freshness_policy_does_not_silently_clear_stale() -> None:
    """B2 policy の version が無ければ STALE を評価しない（偽で通さない）。"""
    found = evaluate(themes=(theme(evidence_flags=("STALE",)),))
    assert "THEME_EVIDENCE_STALE" not in ids(found)
    assert found.report.status is MonitoringRunStatus.PARTIAL
    assert "THEME_EVIDENCE_STALE" in found.report.unevaluated_conditions
    assert "FRESHNESS_POLICY_TOKEN_MISSING" in found.report.diagnostics


def test_62_a_missing_proposal_creation_time_does_not_silently_clear_aging() -> None:
    found = evaluate(proposals=(proposal(proposal_status="OPEN_DEFERRED"),))
    assert found.report.status is MonitoringRunStatus.PARTIAL
    assert "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD" in found.report.unevaluated_conditions
    assert "PROPOSAL_CREATED_AT_MISSING" in found.report.diagnostics


def test_63_one_integrity_fingerprint_does_not_fan_out() -> None:
    """同じ障害を何度渡しても INTEGRITY finding は 1 件に収束する（identity が同じため）。"""
    failure = AuthorityFailureSnapshot(authority_name="theme_roots", failure_class="MALFORMED_JSON",
                                       locator_token="line:12")
    found = evaluate(authority_failures=(failure, failure, dataclasses.replace(failure)))
    assert len([item for item in found.findings if item.condition_id == "AUTHORITY_STATE_UNUSABLE"]) == 1
    assert len(found.report.diagnostics) == 1


# ================================================================ §24 必須 identity test（A〜K）


CONTRADICTION = dict(themes=(theme(evidence_roles_present=("CONTRADICTS",)),))


def test_64_a_same_state_at_a_later_cutoff_is_the_same_finding() -> None:
    base = one(evaluate(**CONTRADICTION), "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    for day in (1, 7, 400):
        later = one(evaluate(cutoff=T0 + timedelta(days=day), **CONTRADICTION),
                    "THEME_CONTRADICTION_EVIDENCE_PRESENT")
        assert later.finding_id == base.finding_id, day


def test_65_a_same_state_under_a_different_ruleset_version_is_the_same_finding(tmp_path) -> None:
    path = reseal(write_rules(tmp_path, mutate=lambda d: d.update({"ruleset_version": "0.2.0"})))
    other = load_monitoring_rules_version(path, expected_version="0.2.0", cutoff=T0)
    base = one(evaluate(**CONTRADICTION), "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    drifted = one(evaluate(rules=other, **CONTRADICTION), "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    assert drifted.finding_id == base.finding_id and drifted.ruleset_version == "0.2.0"


def test_66_a_same_state_with_different_wording_is_the_same_finding(tmp_path) -> None:
    def reword(document):
        for item in document["conditions"]:
            if item["condition_id"] == "THEME_CONTRADICTION_EVIDENCE_PRESENT":
                item["message_key"] = "theme.other_wording"

    path = reseal(write_rules(tmp_path, mutate=reword))
    other = load_monitoring_rules_version(path, expected_version="0.1.0", cutoff=T0)
    base = one(evaluate(**CONTRADICTION), "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    reworded = one(evaluate(rules=other, **CONTRADICTION), "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    assert reworded.finding_id == base.finding_id and reworded.message_key == "theme.other_wording"


def test_67_extra_supporting_references_do_not_change_the_finding() -> None:
    base = one(evaluate(**CONTRADICTION), "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    enriched = one(evaluate(themes=(theme(evidence_roles_present=("CONTRADICTS",),
                                          arrived_attachment_keys=("CONTRADICTS:doc_a", "CONTRADICTS:doc_b")),)),
                   "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    assert enriched.finding_id == base.finding_id
    assert len(enriched.supporting_refs) == 2 and base.supporting_refs == ()


def test_68_a_stale_theme_does_not_drift_day_by_day() -> None:
    payload = dict(themes=(theme(evidence_flags=("STALE",), freshness_policy_token="stale_after_days:90"),))
    base = one(evaluate(**payload), "THEME_EVIDENCE_STALE")
    for day in range(1, 8):
        assert one(evaluate(cutoff=T0 + timedelta(days=day), **payload), "THEME_EVIDENCE_STALE").finding_id \
            == base.finding_id, day


def test_69_a_deferred_proposal_does_not_drift_day_by_day() -> None:
    created = T0 - timedelta(days=31)
    base = one(evaluate(proposals=(proposal(proposal_status="OPEN_DEFERRED", created_at=created),)),
               "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD")
    for day in range(1, 8):
        later = one(evaluate(cutoff=T0 + timedelta(days=day),
                             proposals=(proposal(proposal_status="OPEN_DEFERRED", created_at=created),)),
                    "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD")
        assert later.finding_id == base.finding_id, day


def test_70_extra_contradicting_evidence_does_not_create_a_second_finding() -> None:
    one_ref = evaluate(themes=(theme(evidence_roles_present=("CONTRADICTS",),
                                     arrived_attachment_keys=("CONTRADICTS:doc_a",)),))
    two_refs = evaluate(themes=(theme(evidence_roles_present=("CONTRADICTS",),
                                      arrived_attachment_keys=("CONTRADICTS:doc_a", "CONTRADICTS:doc_b")),))
    left = one(one_ref, "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    right = one(two_refs, "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    assert left.finding_id == right.finding_id


def test_71_a_real_semantic_change_is_a_different_finding() -> None:
    base = one(evaluate(**CONTRADICTION), "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    other_root = one(evaluate(themes=(theme(theme_root_id=B, evidence_roles_present=("CONTRADICTS",)),)),
                     "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    other_role = one(evaluate(themes=(theme(evidence_roles_present=("INVALIDATES",)),)),
                     "THEME_INVALIDATION_EVIDENCE_PRESENT")
    assert base.finding_id not in (other_root.finding_id, other_role.finding_id)


def test_72_the_run_identity_tracks_the_cutoff_ruleset_and_input_digests(tmp_path) -> None:
    base = evaluate(**CONTRADICTION).report
    assert evaluate(cutoff=T0 + timedelta(days=1), recorded_at=T0 + timedelta(days=1),
                    **CONTRADICTION).report.run_id != base.run_id
    path = reseal(write_rules(tmp_path, mutate=lambda d: d.update({"ruleset_version": "0.2.0"})))
    other = load_monitoring_rules_version(path, expected_version="0.2.0", cutoff=T0)
    assert evaluate(rules=other, **CONTRADICTION).report.run_id != base.run_id
    assert evaluate(input_digests=(("theme_roots", "a" * 24),), **CONTRADICTION).report.run_id != base.run_id
    assert evaluate(knowledge_versions=(("theme_taxonomy", "0.2.0"),), **CONTRADICTION).report.run_id != base.run_id
    assert evaluate(recorded_at=T0 + timedelta(hours=9), **CONTRADICTION).report.run_id == base.run_id


# ================================================================ §23 決定論 / 敵対的入力


@pytest.mark.parametrize("seed", SEEDS)
def test_73_the_result_does_not_depend_on_physical_input_order(seed) -> None:
    themes = [theme(theme_root_id=A, evidence_roles_present=("CONTRADICTS",)),
              theme(theme_root_id=B, evidence_flags=("NO_VISIBLE_EVIDENCE",))]
    proposals = [proposal(proposal_id="thprop_" + "a" * 24, proposal_status="OPEN",
                          created_at=T0 - timedelta(days=61)),
                 proposal(proposal_id="thprop_" + "b" * 24, decision_chain_status="UNRESOLVED",
                          decision_chain_diagnostic="FORK")]
    relations = [relation(edge_key="e|1", source_endpoint_state="RETIRED"),
                 relation(edge_key="e|2", target_endpoint_state="SUPERSEDED")]
    ordered = evaluate(themes=tuple(themes), proposals=tuple(proposals), relations=tuple(relations))
    for collection in (themes, proposals, relations):
        random.Random(seed).shuffle(collection)
    shuffled = evaluate(themes=tuple(themes), proposals=tuple(proposals), relations=tuple(relations))
    assert [f.finding_id for f in shuffled.findings] == [f.finding_id for f in ordered.findings]
    assert canonical_monitoring_line(shuffled.report) == canonical_monitoring_line(ordered.report)


def test_74_the_output_order_is_canonical_and_carries_no_priority() -> None:
    found = evaluate(themes=(theme(evidence_roles_present=("CONTRADICTS", "INVALIDATES"),
                                   evidence_flags=("NO_VISIBLE_EVIDENCE",)),))
    identifiers = [item.finding_id for item in found.findings]
    assert identifiers == sorted(identifiers)
    assert list(found.report.finding_ids) == sorted(identifiers)
    source = executable_source(ENGINE)
    for token in ("priority", "severity", "rank", "score", "probability"):
        assert token not in source.lower(), token


def test_75_a_duplicate_subject_does_not_duplicate_a_finding() -> None:
    subject = theme(evidence_roles_present=("CONTRADICTS",))
    found = evaluate(themes=(subject, subject, dataclasses.replace(subject)))
    assert len(found.findings) == 1


def test_76_a_repeated_evaluation_is_byte_identical() -> None:
    first = evaluate(**CONTRADICTION)
    second = evaluate(**CONTRADICTION)
    assert [canonical_monitoring_line(f) for f in first.findings] == \
        [canonical_monitoring_line(f) for f in second.findings]
    assert canonical_monitoring_line(first.report) == canonical_monitoring_line(second.report)


def test_77_a_resolved_condition_simply_stops_being_produced() -> None:
    present = evaluate(**CONTRADICTION)
    cleared = evaluate(themes=(theme(evidence_roles_present=("SUPPORTS",)),))
    assert "THEME_CONTRADICTION_EVIDENCE_PRESENT" in ids(present) and cleared.findings == ()
    reappeared = one(evaluate(cutoff=T0 + timedelta(days=30), **CONTRADICTION),
                     "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    assert reappeared.finding_id == one(present, "THEME_CONTRADICTION_EVIDENCE_PRESENT").finding_id


def test_78_a_threshold_boundary_is_inclusive_and_one_day_short_is_not() -> None:
    at_threshold = evaluate(proposals=(proposal(proposal_status="OPEN_DEFERRED",
                                                created_at=T0 - timedelta(days=30)),))
    below = evaluate(proposals=(proposal(proposal_status="OPEN_DEFERRED",
                                         created_at=T0 - timedelta(days=30) + timedelta(microseconds=1)),))
    assert "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD" in ids(at_threshold) and below.findings == ()


def test_79_the_engine_refuses_an_impossible_time_or_a_future_ruleset() -> None:
    for code, kw in (("INVALID_CUTOFF", dict(cutoff=datetime(2026, 9, 30))),
                     ("RECORDED_BEFORE_CUTOFF", dict(recorded_at=T0 - timedelta(microseconds=1)))):
        with pytest.raises(MonitoringEngineError) as info:
            evaluate(**kw)
        assert info.value.code == code
    with pytest.raises(MonitoringEngineError) as info:
        evaluate(cutoff=datetime(2026, 9, 22, tzinfo=UTC), recorded_at=datetime(2026, 9, 22, tzinfo=UTC))
    assert info.value.code == "FUTURE_RULESET"


# ================================================================ §26 非改変 / §27 security / 境界


def test_80_the_engine_does_not_mutate_its_input() -> None:
    subject = theme(evidence_roles_present=("CONTRADICTS",), arrived_attachment_keys=("CONTRADICTS:doc_a",))
    payload = MonitoringEvaluationInput(cutoff=T0, themes=(subject,))
    before = dataclasses.asdict(payload)
    evaluate_monitoring(payload, ruleset=RULES, recorded_at=T0)
    assert dataclasses.asdict(payload) == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        subject.governance_state = "RETIRED"


def test_81_no_authority_file_is_created_or_written(tmp_path) -> None:
    before = sorted(p.name for p in tmp_path.iterdir())
    evaluate(**CONTRADICTION)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    for module in (ENGINE,):
        source = executable_source(module)
        for token in ("open(", "Path(", ".write(", "append", "fsync", "sqlite", "mkdir", "read_text", "read_bytes"):
            assert token not in source, token


def test_82_the_engine_reads_no_clock_no_randomness_and_no_network() -> None:
    source = executable_source(ENGINE)
    for token in (".now(", "utcnow", "time.time", "random.", "secrets.", "uuid", "requests", "urllib", "socket",
                  "httpx", "subprocess", "anthropic", "openai", "transformers", "embedding", "nltk", "spacy",
                  "environ", "getenv"):
        assert token not in source, token


def test_83_the_engine_carries_no_governance_or_execution_vocabulary() -> None:
    source = executable_source(ENGINE)
    for token in ("RelationAssertionPlan", "EvidenceAttachmentPlan", "append_assertion", "ThemeStore", "EXECUTE",
                  "SHOULD_EXECUTE", "READY_TO_PROMOTE", "AUTO_APPEND", "promote", "ACCEPT_NOW"):
        assert token not in source, token
    assert ENGINE_EMITS_OBSERVATIONS_ONLY == "the engine reports observed state and never asks for an action"
    body = json.dumps([f.as_dict() for f in evaluate(**CONTRADICTION).findings])
    for token in ("execute", "promote", "approve", "target_price", "severity", "probability"):
        assert token not in body.lower(), token


def test_84_the_engine_does_not_reimplement_upstream_derived_semantics() -> None:
    """STALE の日数計算・CONTESTED 判定・端点解決・chain 解決を engine が持たない。"""
    source = executable_source(ENGINE)
    for token in ("stale_after_days", "independent_origin", "qualification", "resolve_relation_graph",
                  "resolve_at_data_root", "compare_resolutions", "derive_lifecycle", "endpoint_lookup"):
        assert token not in source, token
    modules = imported_modules(ENGINE)
    assert set(modules) <= {"__future__", "dataclasses", "datetime", "enum", "typing", "..core.time",
                            ".monitoring_model", ".monitoring_rules"}, sorted(modules)


def test_85_the_rules_module_owns_the_only_file_access() -> None:
    modules = imported_modules(RULES_MODULE)
    assert set(modules) <= {"__future__", "dataclasses", "datetime", "pathlib", "typing", ".knowledge_loader",
                            ".monitoring_model"}, sorted(modules)
    source = executable_source(RULES_MODULE)
    assert "read_yaml_document" in source and "yaml.load" not in source     # YAML は knowledge_loader 経由のみ


def test_86_no_store_runner_or_scheduler_was_created() -> None:
    """B6D で review store / adapter / runner が加わった後も、engine は純関数のままで finding store は無い。"""
    present = sorted(p.stem for p in PACKAGE_DIR.glob("monitoring*.py"))
    assert present == ["monitoring_adapter", "monitoring_engine", "monitoring_model", "monitoring_rules",
                       "monitoring_runner", "monitoring_store"], present
    for stem in ("monitoring_scheduler", "monitoring_notifier", "finding_store"):
        assert not (PACKAGE_DIR / f"{stem}.py").exists(), stem
    engine = executable_source(ENGINE)
    for token in ("open(", "Path(", "data_root", "jsonl", "run_monitoring", "append_"):
        assert token not in engine, token


def test_87_the_ruleset_carries_no_path_credential_or_article_text() -> None:
    body = RULES_PATH.read_text(encoding="utf-8")
    drive = "D" + ":" + chr(92)
    for token in (drive, chr(92) * 2, "api_key=", "password", "secret", "portfolio", "http://", "https://"):
        assert token not in body, token
    assert max(len(line) for line in body.split("\n")) <= 120


def test_88_findings_carry_no_article_body_and_only_bounded_tokens() -> None:
    found = evaluate(themes=(theme(evidence_roles_present=("CONTRADICTS",),
                                   arrived_attachment_keys=("CONTRADICTS:doc_a",)),))
    for item in found.findings:
        for value in item.salient_state.fact_map.values():
            assert len(value) <= 200 and " " not in value
        assert len(item.message_key) <= 64
    assert MONITORING_ENGINE_VERSION == "theme_monitoring_engine:0.1.0"
