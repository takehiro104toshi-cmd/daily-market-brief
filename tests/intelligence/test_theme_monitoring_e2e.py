"""P6-B6E — B6A architecture / B6B model / B6C engine / B6D operational layer を 1 系として検証する gate。

**runtime を 1 byte も変更しない。** 本 file は validation のみで、閾値も condition も identity も触らない。
finding 件数を重要度・投資妥当性・予測として解釈しない。データはすべて synthetic（合成 world ＋ 合成 record）で、
書き込みは `tmp_path` のみ。

層:

- §A  18 condition の positive / negative matrix（adapter → engine）
- §B  corruption matrix（store → runner。fail closed / PARTIAL / 自動修復なし）
- §C  cross-layer E2E（authority fixture → resolver → B2/B3/B5 derived → adapter → engine → review lookup）
- §D  決定論 replay / physical order / PIT matrix
- §E  zero-write / hidden authority / RR-3 / source-origin / security
- §F  read-only shadow harness と real-data precheck

§D の提案 PIT 2 件は B6E（8655d8d）で strict xfail として BLOCKER-1 を記録していた。P6-B6D-R1 で runner が
B3 / B5C の record を cutoff で濾過するようになったため、同じ契約のまま通常の test に戻した。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.lifecycle_model import LifecyclePolicy, default_lifecycle_policy
from src.intelligence.theme_intelligence.monitoring_adapter import (MonitoringObservations, build_evaluation_input,
                                                                    freshness_policy_token)
from src.intelligence.theme_intelligence.monitoring_engine import (AuthorityFailureSnapshot, KnowledgeDriftSnapshot,
                                                                   ProposalSnapshot, RelationProposalSnapshot,
                                                                   RelationSnapshot, SubjectAvailability,
                                                                   ThemeSnapshot, evaluate_monitoring)
from src.intelligence.theme_intelligence.monitoring_model import (MonitoringCategory, MonitoringRunStatus,
                                                                  ReviewChainStatus, ReviewDisposition,
                                                                  ReviewItemState, canonical_monitoring_line)
from src.intelligence.theme_intelligence.monitoring_rules import (CONDITION_REGISTRY, load_monitoring_rules_version,
                                                                  monitoring_rules_path)
from src.intelligence.theme_intelligence.monitoring_runner import ReviewLookupStatus, run_monitoring
from src.intelligence.theme_intelligence.monitoring_store import (MonitoringReviewStore, ReviewAppendRejected,
                                                                  ReviewStoreCorrupt, review_state_path)
from src.intelligence.theme_intelligence.proposal_model import DecisionKind, canonical_proposal_line
from src.intelligence.theme_intelligence.proposal_store import ProposalStore
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.relation_model import RelationType, canonical_relation_line
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as relation_proposal_paths
from src.intelligence.theme_intelligence.relation_resolution import RelationResolutionStatus, endpoint_lookup_from_roots
from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
from src.intelligence.theme_intelligence.relation_store import authority_paths as relation_paths
from src.intelligence.theme_intelligence.relation_store import resolve_relations_at_data_root
from src.intelligence.themes.model import EvidenceKind, EvidenceRole, GovernanceEventType
from src.intelligence.themes.resolver import resolve_at_data_root
from src.intelligence.themes.revision import attach_evidence
from src.intelligence.themes.store import ThemeStore
from src.intelligence.themes.store import authority_paths as theme_paths
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B, ROOT_C, attachment, event, provenance
from tests.intelligence.test_theme_proposal import decision, evidence_candidate
from tests.intelligence.test_theme_relation import causal, retraction, sourced
from tests.intelligence.test_theme_relation_proposal import proposal as relation_candidate
from tests.intelligence.theme_foundation_fixtures import CHECKPOINTS, build_world, day

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
SHADOW_HARNESS = Path(__file__).with_name("theme_monitoring_shadow.py")
#: B6E が凍結として扱う runtime（1 byte も変えない）
FROZEN_RUNTIME = ("monitoring_model.py", "monitoring_engine.py", "monitoring_rules.py", "monitoring_store.py",
                  "monitoring_adapter.py", "monitoring_runner.py")
FROZEN_KNOWLEDGE = KNOWLEDGE_ROOT / "theme_intelligence" / "monitoring_rules.0.1.0.yaml"
POLICY = default_lifecycle_policy()
STALE_POLICY = LifecyclePolicy(stale_after_days=1)
SCOPE = (ROOT_A, ROOT_B, ROOT_C)
REVIEWER = "reviewer:r1"
SEEDS = tuple(range(11))
T = datetime(2026, 10, 1, tzinfo=UTC)
PROPOSAL_ID = "thprop_" + "a" * 24
RELATION_PROPOSAL_ID = "threlprop_" + "a" * 24
OBSERVATION_ID = "thobs_" + "a" * 24
EDGE = "theme_0|theme_1|CAUSES|SOURCE_ASSERTED|publisher_x"
ARRIVED = "fact:arrived:one"

REAL_RULES = load_monitoring_rules_version(monitoring_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0",
                                           cutoff=datetime(2026, 9, 30, tzinfo=UTC))
#: 合成 world（2026-09）でも使えるよう published_at だけ前倒しした同一 ruleset（内容は不変）
RULES = dataclasses.replace(REAL_RULES, published_at=datetime(2026, 8, 1, tzinfo=UTC))


# ---------------------------------------------------------------- helpers

def theme(**kw) -> ThemeSnapshot:
    kw.setdefault("theme_root_id", ROOT_A)
    return ThemeSnapshot(**kw)


def proposal(**kw) -> ProposalSnapshot:
    kw.setdefault("proposal_id", PROPOSAL_ID)
    return ProposalSnapshot(**kw)


def relation(**kw) -> RelationSnapshot:
    kw.setdefault("edge_key", EDGE)
    kw.setdefault("edge_state", "ACTIVE")
    return RelationSnapshot(**kw)


def relation_proposal(**kw) -> RelationProposalSnapshot:
    kw.setdefault("relation_proposal_id", RELATION_PROPOSAL_ID)
    kw.setdefault("edge_key", EDGE)
    return RelationProposalSnapshot(**kw)


#: P6-B6R1: condition matrix は観測 channel をすべて供給した完全な入力で評価する（未供給は coverage test が固定）
ALL_SUPPLIED = MonitoringObservations(arrived_attachment_keys={}, semantic_revision_observation_ids={},
                                      discovery_outcome_tokens={})


def evaluate(cutoff=T, **families):
    families.setdefault("observations", ALL_SUPPLIED)
    return evaluate_monitoring(build_evaluation_input(cutoff=cutoff, **families), ruleset=RULES, recorded_at=cutoff)


def fired(evaluation) -> set:
    return {finding.condition_id for finding in evaluation.findings}


def journal_digests(root: Path) -> dict:
    paths = {f"themes:{k}": v for k, v in theme_paths(root).items()}
    paths.update({f"proposals:{k}": v for k, v in proposal_paths(root).items()})
    paths.update({f"relations:{k}": v for k, v in relation_paths(root).items()})
    paths.update({f"relation_proposals:{k}": v for k, v in relation_proposal_paths(root).items()})
    paths["review_states"] = review_state_path(root)
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
               for name, path in paths.items()}
    for path in sorted(FROZEN_KNOWLEDGE.parent.glob("*.yaml")):
        digests[f"knowledge:{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def inventory(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------- §A 18 condition matrix

STALE_TOKEN = freshness_policy_token(POLICY)
OLD = T - timedelta(days=61)
DEFERRED_OLD = T - timedelta(days=31)

POSITIVE = {
    "THEME_CONTRADICTION_EVIDENCE_PRESENT": dict(themes=(theme(evidence_roles_present=("CONTRADICTS",)),)),
    "THEME_INVALIDATION_EVIDENCE_PRESENT": dict(themes=(theme(evidence_roles_present=("INVALIDATES",)),)),
    "THEME_WITHOUT_COUNTED_EVIDENCE": dict(themes=(theme(evidence_flags=("NO_VISIBLE_EVIDENCE",)),)),
    "THEME_EVIDENCE_STALE": dict(themes=(theme(evidence_flags=("STALE",), freshness_policy_token=STALE_TOKEN),)),
    "ACCEPTED_THEME_SEMANTIC_REVISION": dict(themes=(theme(governance_state="ACCEPTED",
                                                           semantic_revision_observation_id=OBSERVATION_ID),)),
    "RETIRED_ROOT_RECEIVED_EVIDENCE": dict(themes=(theme(governance_state="RETIRED",
                                                         arrived_attachment_keys=(ARRIVED,)),)),
    "GOVERNANCE_EVIDENCE_DIVERGENCE": dict(themes=(theme(governance_state="ACCEPTED",
                                                         evidence_flags=("NO_VISIBLE_EVIDENCE",)),)),
    "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD": dict(proposals=(proposal(proposal_status="OPEN", created_at=OLD),)),
    "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD": dict(proposals=(proposal(proposal_status="OPEN_DEFERRED",
                                                                         created_at=DEFERRED_OLD),)),
    "PROPOSAL_DECISION_CHAIN_UNRESOLVED": dict(proposals=(proposal(proposal_status="OPEN_UNRESOLVED",
                                                                   decision_chain_status="UNRESOLVED",
                                                                   decision_chain_diagnostic="FORK"),)),
    "DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL": dict(proposals=(proposal(proposal_status="REJECTED",
                                                                        discovery_outcome_token="NO_ACCEPTED_PROPOSAL"),)),
    "ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT": dict(proposals=(proposal(proposal_status="ACCEPTED",
                                                                           discovery_outcome_token="NO_OBSERVED_EFFECT"),)),
    "KNOWLEDGE_VERSION_DRIFT": dict(knowledge_drift=(KnowledgeDriftSnapshot(knowledge_name="taxonomy",
                                                                            from_version="0.1.0", to_version="0.2.0"),)),
    "RELATION_ENDPOINT_NOT_ACTIVE": dict(relations=(relation(source_endpoint_state="RETIRED",
                                                             target_endpoint_state="EXISTS_AT_CUTOFF"),)),
    "RETRACTED_RELATION_HAS_NEW_PROPOSAL": dict(relation_proposals=(relation_proposal(
        conflict_token="OPEN_PROPOSAL_ON_RETRACTED_EDGE"),)),
    "SOURCE_ASSERTED_RELATION_CONTESTED": dict(relations=(relation(assertion_class="SOURCE_ASSERTED",
                                                                   contested_theme_root_id=ROOT_A,
                                                                   contested_role="CONTRADICTS"),)),
    "RELATION_GOVERNANCE_CHAIN_UNRESOLVED": dict(relations=(relation(governance_chain_status="UNRESOLVED",
                                                                     governance_chain_diagnostic="FORK"),)),
    "AUTHORITY_STATE_UNUSABLE": dict(authority_failures=(AuthorityFailureSnapshot(authority_name="theme_proposals",
                                                                                   failure_class="STORE_CORRUPTION"),)),
}
NEGATIVE = {
    "THEME_CONTRADICTION_EVIDENCE_PRESENT": dict(themes=(theme(evidence_roles_present=("INVALIDATES",)),)),
    "THEME_INVALIDATION_EVIDENCE_PRESENT": dict(themes=(theme(evidence_roles_present=("CONTRADICTS",)),)),
    "THEME_WITHOUT_COUNTED_EVIDENCE": dict(themes=(theme(evidence_flags=("HAS_SUPPORT",)),)),
    "THEME_EVIDENCE_STALE": dict(themes=(theme(evidence_flags=("HAS_SUPPORT",), freshness_policy_token=STALE_TOKEN),)),
    "ACCEPTED_THEME_SEMANTIC_REVISION": dict(themes=(theme(governance_state="UNREVIEWED",
                                                           semantic_revision_observation_id=OBSERVATION_ID),)),
    "RETIRED_ROOT_RECEIVED_EVIDENCE": dict(themes=(theme(governance_state="ACCEPTED",
                                                         arrived_attachment_keys=(ARRIVED,)),)),
    "GOVERNANCE_EVIDENCE_DIVERGENCE": dict(themes=(theme(governance_state="ACCEPTED",
                                                         evidence_flags=("HAS_SUPPORT",)),)),
    "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD": dict(proposals=(proposal(proposal_status="OPEN",
                                                                     created_at=T - timedelta(days=59)),)),
    "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD": dict(proposals=(proposal(proposal_status="OPEN_DEFERRED",
                                                                         created_at=T - timedelta(days=29)),)),
    "PROPOSAL_DECISION_CHAIN_UNRESOLVED": dict(proposals=(proposal(proposal_status="OPEN", created_at=T),)),
    "DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL": dict(proposals=(proposal(proposal_status="ACCEPTED",
                                                                        discovery_outcome_token="NO_OBSERVED_EFFECT"),)),
    "ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT": dict(proposals=(proposal(proposal_status="REJECTED",
                                                                           discovery_outcome_token="NO_ACCEPTED_PROPOSAL"),)),
    "KNOWLEDGE_VERSION_DRIFT": dict(knowledge_drift=(KnowledgeDriftSnapshot(knowledge_name="taxonomy",
                                                                            from_version="0.1.0", to_version="0.1.0"),)),
    "RELATION_ENDPOINT_NOT_ACTIVE": dict(relations=(relation(source_endpoint_state="EXISTS_AT_CUTOFF",
                                                             target_endpoint_state="EXISTS_AT_CUTOFF"),)),
    "RETRACTED_RELATION_HAS_NEW_PROPOSAL": dict(relation_proposals=(relation_proposal(conflict_token=""),)),
    "SOURCE_ASSERTED_RELATION_CONTESTED": dict(relations=(relation(assertion_class="HUMAN_ASSERTED",
                                                                   contested_theme_root_id=ROOT_A),)),
    "RELATION_GOVERNANCE_CHAIN_UNRESOLVED": dict(relations=(relation(governance_chain_status=""),)),
    "AUTHORITY_STATE_UNUSABLE": dict(themes=(theme(governance_state="ACCEPTED"),)),
}
CONDITION_IDS = tuple(sorted(CONDITION_REGISTRY))


def test_a00_the_matrix_covers_every_registered_condition() -> None:
    assert len(CONDITION_IDS) == 18
    assert sorted(POSITIVE) == list(CONDITION_IDS) and sorted(NEGATIVE) == list(CONDITION_IDS)


@pytest.mark.parametrize("condition_id", CONDITION_IDS)
def test_a01_positive_fixture_fires_exactly_the_expected_condition(condition_id: str) -> None:
    evaluation = evaluate(**POSITIVE[condition_id])
    assert condition_id in fired(evaluation), (condition_id, sorted(fired(evaluation)))
    spec = CONDITION_REGISTRY[condition_id]
    finding = next(f for f in evaluation.findings if f.condition_id == condition_id)
    assert finding.category is spec.category and finding.subject_kind is spec.subject_kind
    assert finding.salient_state.state_kind is spec.salient_state_kind
    assert finding.ruleset_version == RULES.ruleset_version and finding.cutoff == T


@pytest.mark.parametrize("condition_id", CONDITION_IDS)
def test_a02_negative_fixture_does_not_fire_it(condition_id: str) -> None:
    assert condition_id not in fired(evaluate(**NEGATIVE[condition_id])), condition_id


@pytest.mark.parametrize("condition_id", CONDITION_IDS)
def test_a03_finding_identity_is_stable_across_cutoffs(condition_id: str) -> None:
    """cutoff は finding identity に入らない（B6B）。別 cutoff でも同じ id に収束する。"""
    later = T + timedelta(days=5)
    families = POSITIVE[condition_id]
    if condition_id.startswith("THEME_PROPOSAL_"):
        pytest.skip("aging condition は threshold_token が閾値由来のため別 cutoff でも同一（別 test で固定）")
    first = next(f for f in evaluate(**families).findings if f.condition_id == condition_id)
    second = next(f for f in evaluate(cutoff=later, **families).findings if f.condition_id == condition_id)
    assert first.finding_id == second.finding_id and first.cutoff != second.cutoff


def test_a04_aging_findings_keep_their_identity_while_the_threshold_holds() -> None:
    families = POSITIVE["THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD"]
    ids = {next(f.finding_id for f in evaluate(cutoff=T + timedelta(days=n), **families).findings
                if f.condition_id == "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD") for n in (0, 5, 40)}
    assert len(ids) == 1                                       # 経過日数が identity に入らない


@pytest.mark.parametrize("condition_id", CONDITION_IDS)
def test_a05_a_positive_fixture_reports_complete_unless_a_subject_is_unusable(condition_id: str) -> None:
    evaluation = evaluate(**POSITIVE[condition_id])
    assert evaluation.report.status is MonitoringRunStatus.COMPLETE
    assert evaluation.report.unevaluated_conditions == ()


def test_a06_an_unusable_subject_makes_the_run_partial() -> None:
    evaluation = evaluate(themes=(theme(availability=SubjectAvailability.UNAVAILABLE,
                                        authority_name="theme_observations", failure_class="STORE_CORRUPTION"),))
    assert evaluation.report.status is MonitoringRunStatus.PARTIAL
    assert "AUTHORITY_STATE_UNUSABLE" in fired(evaluation) and evaluation.report.unevaluated_conditions


def test_a07_a_healthy_world_produces_no_finding() -> None:
    evaluation = evaluate(themes=(theme(governance_state="ACCEPTED", evidence_flags=("HAS_SUPPORT", "QUALIFIES"),
                                        freshness_policy_token=STALE_TOKEN),),
                          proposals=(proposal(proposal_status="ACCEPTED", created_at=T),),
                          relations=(relation(source_endpoint_state="EXISTS_AT_CUTOFF",
                                              target_endpoint_state="EXISTS_AT_CUTOFF"),),
                          relation_proposals=(relation_proposal(conflict_token=""),))
    assert evaluation.findings == () and evaluation.report.status is MonitoringRunStatus.COMPLETE


def test_a08_categories_stay_within_the_frozen_vocabulary() -> None:
    seen = {CONDITION_REGISTRY[c].category for c in CONDITION_IDS}
    assert seen <= set(MonitoringCategory)
    technical = {c for c in CONDITION_IDS if CONDITION_REGISTRY[c].category is MonitoringCategory.INTEGRITY}
    assert technical == {"PROPOSAL_DECISION_CHAIN_UNRESOLVED", "RELATION_GOVERNANCE_CHAIN_UNRESOLVED",
                         "AUTHORITY_STATE_UNUSABLE"}


def test_a09_duplicate_semantic_conditions_converge_to_one_finding() -> None:
    """同一 origin から同じ観測が何度来ても finding は 1 件へ収束する（件数を evidence 強度にしない）。"""
    same = tuple(theme(evidence_roles_present=("CONTRADICTS",)) for _ in range(4))
    evaluation = evaluate(themes=same)
    assert len([f for f in evaluation.findings if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT"]) == 1


# ---------------------------------------------------------------- 合成 world（cross-layer E2E）

def _seed_world(root: Path) -> dict:
    """代表 world に B3 / B5B / B5C / B6D の合成 record を足し、18 condition の到達性を作る。"""
    world = build_world(root)
    store = ThemeStore.open(root)
    terminal = resolve_at_data_root(root, ROOT_C, day(16)).governance.terminal_event_id
    store.append_governance(event(event_type=GovernanceEventType.CANDIDATE_ACCEPTED, subject_roots=(ROOT_C,),
                                  reason="accepted for the monitoring e2e gate", recorded_at=day(16),
                                  previous_event_ids=((ROOT_C, terminal),)))
    invalidating = attachment("doc_" + "d" * 24, EvidenceKind.SOURCE_DOCUMENT, day="2026-09-10", attached=day(17),
                              role=EvidenceRole.INVALIDATES, cref="", invalidation_condition_ref="inv1")
    revised = attach_evidence(store.get_observation(world.ids["C.genesis"]), (invalidating,), recorded_at=day(17),
                              provenance=provenance(reason="invalidating release"))
    store.append_observation(revised)
    for cls in (ProposalStore, ThemeRelationStore, RelationProposalStore, MonitoringReviewStore):
        cls.initialize(root)
    relations = ThemeRelationStore.open(root)
    relations.append_assertion(sourced(ROOT_A, ROOT_B, at=day(3)))
    retracted = causal(ROOT_B, ROOT_A, at=day(3))
    relations.append_assertion(retracted)
    relations.append_event(retraction(retracted, at=day(4)))
    RelationProposalStore.open(root).append_proposal(
        relation_candidate(ROOT_B, ROOT_A, relation_type=RelationType.CAUSES, at=day(5)))
    proposals = ProposalStore.open(root)
    open_candidate = evidence_candidate(created_at=day(1))
    proposals.append_proposal(open_candidate)
    deferred = evidence_candidate(created_at=day(2), reason="deferred candidate for the monitoring e2e gate")
    proposals.append_proposal(deferred)
    proposals.append_decision(decision(deferred.proposal_id, DecisionKind.DEFER, at=day(3)))
    forked = evidence_candidate(created_at=day(2), reason="forked candidate for the monitoring e2e gate")
    proposals.append_proposal(forked)
    first = decision(forked.proposal_id, DecisionKind.DEFER, at=day(3))
    path = proposal_paths(root)["decisions"]
    for record in (first, decision(forked.proposal_id, DecisionKind.ACCEPT, at=day(4), supersedes=first.decision_id),
                   decision(forked.proposal_id, DecisionKind.REJECT, at=day(5), supersedes=first.decision_id)):
        path.write_bytes(path.read_bytes() + canonical_proposal_line(record).encode("utf-8"))
    return {"open": open_candidate.proposal_id, "deferred": deferred.proposal_id, "forked": forked.proposal_id,
            "revision": revised.observation_id}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("monitoring_e2e") / "data"
    ids = _seed_world(root)
    return root, ids


@pytest.fixture()
def copied(world, tmp_path: Path) -> Path:
    target = tmp_path / "copy" / "data"
    shutil.copytree(world[0], target)
    return target


def run(root: Path, *, cutoff, policy=POLICY, rules=None, **kw):
    kw.setdefault("recorded_at", cutoff)
    kw.setdefault("root_ids", SCOPE)
    return run_monitoring(data_root=root, cutoff=cutoff, lifecycle_policy=policy, ruleset=rules or RULES, **kw)


def observations(ids: dict) -> MonitoringObservations:
    return MonitoringObservations(arrived_attachment_keys={ROOT_A: (ARRIVED,)},
                                  semantic_revision_observation_ids={ROOT_C: ids["revision"]},
                                  discovery_outcome_tokens={ids["open"]: "NO_ACCEPTED_PROPOSAL",
                                                            ids["deferred"]: "NO_OBSERVED_EFFECT"})


def full_run(root: Path, ids: dict):
    return run(root, cutoff=day(70), policy=STALE_POLICY, observations=observations(ids),
               knowledge_drift=(("taxonomy", "0.1.0", "0.2.0"),))


# ---------------------------------------------------------------- §C cross-layer E2E

#: cross-layer で到達した condition と、それを出した cutoff（報告の coverage matrix と 1:1）
CROSS_LAYER_EXPECTED = {
    "day70": {"THEME_CONTRADICTION_EVIDENCE_PRESENT", "THEME_INVALIDATION_EVIDENCE_PRESENT", "THEME_EVIDENCE_STALE",
              "ACCEPTED_THEME_SEMANTIC_REVISION", "RETIRED_ROOT_RECEIVED_EVIDENCE", "GOVERNANCE_EVIDENCE_DIVERGENCE",
              "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD", "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD",
              "PROPOSAL_DECISION_CHAIN_UNRESOLVED", "DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL",
              "ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT", "KNOWLEDGE_VERSION_DRIFT",
              "RETRACTED_RELATION_HAS_NEW_PROPOSAL", "SOURCE_ASSERTED_RELATION_CONTESTED"},
    "retired": {"RELATION_ENDPOINT_NOT_ACTIVE", "AUTHORITY_STATE_UNUSABLE"},
    "genesis": {"THEME_WITHOUT_COUNTED_EVIDENCE"},
}
#: store が load 時に fail closed するため、runner 経路では per-edge では出ない condition
CROSS_LAYER_UNREACHABLE = {"RELATION_GOVERNANCE_CHAIN_UNRESOLVED"}


def test_c01_the_full_cross_layer_run_fires_the_expected_conditions(world) -> None:
    root, ids = world
    result = full_run(root, ids)
    assert result.report.status is MonitoringRunStatus.COMPLETE
    assert {f.condition_id for f in result.findings} == CROSS_LAYER_EXPECTED["day70"]


def test_c02_earlier_cutoffs_reach_the_remaining_conditions(world) -> None:
    root, _ = world
    retired = {f.condition_id for f in run(root, cutoff=CHECKPOINTS["retired"]).findings}
    genesis = {f.condition_id for f in run(root, cutoff=CHECKPOINTS["genesis_visible"], root_ids=(ROOT_A,)).findings}
    assert CROSS_LAYER_EXPECTED["retired"] <= retired
    assert CROSS_LAYER_EXPECTED["genesis"] <= genesis


def test_c03_cross_layer_coverage_is_seventeen_of_eighteen(world) -> None:
    root, ids = world
    reached = set(CROSS_LAYER_EXPECTED["day70"]) | CROSS_LAYER_EXPECTED["retired"] | CROSS_LAYER_EXPECTED["genesis"]
    assert reached | CROSS_LAYER_UNREACHABLE == set(CONDITION_IDS)
    assert len(reached) == 17 and len(CROSS_LAYER_UNREACHABLE) == 1


@pytest.mark.parametrize("build,expected", [
    (lambda edge: (retraction(edge, at=day(4)), retraction(edge, reason="withdrawn once more", at=day(5))),
     RelationResolutionStatus.INVALID_HISTORY),
    (lambda edge: (retraction(edge, previous="thrgov_" + "a" * 24, at=day(4)),),
     RelationResolutionStatus.INVALID_HISTORY),
])
def test_c04_a_broken_relation_governance_chain_fails_closed_at_the_store(tmp_path: Path, build, expected) -> None:
    """`RELATION_GOVERNANCE_CHAIN_UNRESOLVED` が runner 経路で出ない理由を明示的に固定する。

    B5B store は per-edge の unresolved chain を load 時に拒否するため、runner は authority 全体の
    失敗（`AUTHORITY_STATE_UNUSABLE` ＋ PARTIAL）として表す。**黙って健全にはならない。**
    """
    root = tmp_path / "data"
    store = ThemeRelationStore.initialize(root)
    edge = causal(ROOT_A, ROOT_B, at=day(3))
    store.append_assertion(edge)
    path = relation_paths(root)["governance"]
    for record in build(edge):
        path.write_bytes(path.read_bytes() + canonical_relation_line(record).encode("utf-8"))
    lookup = endpoint_lookup_from_roots({ROOT_A: day(0), ROOT_B: day(0)})
    resolution = resolve_relations_at_data_root(root, cutoff=day(9), endpoint_lookup=lookup)
    assert resolution.status is expected and resolution.unresolved == () and resolution.edges == ()


def test_c05_the_review_lookup_is_part_of_the_cross_layer_path(world) -> None:
    root, ids = world
    result = full_run(root, ids)
    assert result.review_status is ReviewLookupStatus.AVAILABLE
    assert len(result.reviews) == len(result.findings)
    assert all(review.resolution.status is ReviewChainStatus.NONE for review in result.reviews)


# ---------------------------------------------------------------- §C review-state E2E

def test_c06_the_human_review_lifecycle_runs_end_to_end(copied: Path, world) -> None:
    _, ids = world
    present = run(copied, cutoff=CHECKPOINTS["contradiction_added"])
    target = next(f for f in present.findings if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    assert next(r for r in present.reviews
                if r.finding.finding_id == target.finding_id).resolution.status is ReviewChainStatus.NONE

    store = MonitoringReviewStore.open(copied)
    ack = ReviewItemState.build(finding_id=target.finding_id, disposition=ReviewDisposition.ACKNOWLEDGED,
                                actor_ref=REVIEWER, recorded_at=CHECKPOINTS["contradiction_added"])
    store.append_review_state(ack)
    after_ack = run(copied, cutoff=CHECKPOINTS["contradiction_added"])
    assert target.finding_id in {f.finding_id for f in after_ack.findings}          # ACK しても観測は続く
    review = next(r for r in after_ack.reviews if r.finding.finding_id == target.finding_id)
    assert review.resolution.terminal.disposition is ReviewDisposition.ACKNOWLEDGED

    frozen = review_state_path(copied).read_bytes()
    absent = run(copied, cutoff=CHECKPOINTS["first_evidence"])
    assert target.finding_id not in {f.finding_id for f in absent.findings}
    assert review_state_path(copied).read_bytes() == frozen                          # 消えても書き換えない

    back = run(copied, cutoff=day(70), policy=STALE_POLICY, observations=observations(ids))
    same = next(f for f in back.findings if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    assert same.finding_id == target.finding_id                                      # episode identity を作らない
    revived = next(r for r in back.reviews if r.finding.finding_id == target.finding_id)
    assert revived.resolution.terminal.disposition is ReviewDisposition.ACKNOWLEDGED  # 自動 reopen しない


def test_c07_a_successor_review_supersedes_its_predecessor(copied: Path) -> None:
    result = run(copied, cutoff=CHECKPOINTS["contradiction_added"])
    target = next(f for f in result.findings if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    store = MonitoringReviewStore.open(copied)
    deferred = ReviewItemState.build(finding_id=target.finding_id, disposition=ReviewDisposition.DEFERRED,
                                     actor_ref=REVIEWER, recorded_at=day(4))
    store.append_review_state(deferred)
    store.append_review_state(ReviewItemState.build(finding_id=target.finding_id,
                                                    disposition=ReviewDisposition.ACKNOWLEDGED, actor_ref=REVIEWER,
                                                    recorded_at=day(5),
                                                    supersedes_review_state_id=deferred.review_state_id))
    review = next(r for r in run(copied, cutoff=CHECKPOINTS["contradiction_added"]).reviews
                  if r.finding.finding_id == target.finding_id)
    assert review.resolution.status is ReviewChainStatus.RESOLVED
    assert review.resolution.terminal.disposition is ReviewDisposition.ACKNOWLEDGED
    assert len(review.resolution.chain) == 2


@pytest.mark.parametrize("flaw", ["fork", "dangling", "cross_finding", "non_monotonic"])
def test_c08_broken_review_histories_fail_closed_on_append(copied: Path, flaw: str) -> None:
    result = run(copied, cutoff=CHECKPOINTS["contradiction_added"])
    target = result.findings[0].finding_id
    other = "thmfind_" + "b" * 24
    store = MonitoringReviewStore.open(copied)
    first = ReviewItemState.build(finding_id=target, disposition=ReviewDisposition.DEFERRED, actor_ref=REVIEWER,
                                  recorded_at=day(4))
    store.append_review_state(first)
    builds = {
        "fork": (target, day(6), first.review_state_id),
        "dangling": (target, day(6), "thmrev_" + "9" * 24),
        "cross_finding": (other, day(6), first.review_state_id),
        "non_monotonic": (target, day(3), first.review_state_id),
    }
    if flaw == "fork":
        store.append_review_state(ReviewItemState.build(finding_id=target, disposition=ReviewDisposition.ACKNOWLEDGED,
                                                        actor_ref=REVIEWER, recorded_at=day(5),
                                                        supersedes_review_state_id=first.review_state_id))
    finding_id, at, predecessor = builds[flaw]
    with pytest.raises(ReviewAppendRejected) as exc:
        store.append_review_state(ReviewItemState.build(finding_id=finding_id, disposition=ReviewDisposition.DISMISSED,
                                                        actor_ref=REVIEWER, recorded_at=at,
                                                        supersedes_review_state_id=predecessor))
    assert exc.value.code in ("NOT_TERMINAL_PREDECESSOR", "MISSING_PREDECESSOR", "CROSS_FINDING_PREDECESSOR",
                              "NON_MONOTONIC_RECORDED_AT")


def test_c09_a_multiple_genesis_review_history_is_unresolved_not_latest_wins(copied: Path) -> None:
    result = run(copied, cutoff=CHECKPOINTS["contradiction_added"])
    target = result.findings[0].finding_id
    store = MonitoringReviewStore.open(copied)
    store.append_review_state(ReviewItemState.build(finding_id=target, disposition=ReviewDisposition.DEFERRED,
                                                    actor_ref=REVIEWER, recorded_at=day(4)))
    store.append_review_state(ReviewItemState.build(finding_id=target, disposition=ReviewDisposition.ACKNOWLEDGED,
                                                    actor_ref=REVIEWER, recorded_at=day(5)))
    review = next(r for r in run(copied, cutoff=CHECKPOINTS["contradiction_added"]).reviews
                  if r.finding.finding_id == target)
    assert review.resolution.status is ReviewChainStatus.UNRESOLVED and review.resolution.terminal is None


# ---------------------------------------------------------------- §B corruption matrix

CORRUPTIONS = {
    "malformed_json": b"{not json}\n",
    "truncated_final_line": b'{"schema_version":"x"\n',
    "noncanonical_line": b'{ "schema_version" : "x" }\n',
    "not_an_object": b"[1,2]\n",
    "blank_line": b"\n",
}
CORRUPT_TARGETS = ("themes", "proposals", "relations", "relation_proposals")


def _target_path(root: Path, family: str) -> Path:
    return {"themes": theme_paths(root)["observations"], "proposals": proposal_paths(root)["proposals"],
            "relations": relation_paths(root)["assertions"],
            "relation_proposals": relation_proposal_paths(root)["proposals"]}[family]


@pytest.mark.parametrize("family", CORRUPT_TARGETS)
@pytest.mark.parametrize("flaw", sorted(CORRUPTIONS))
def test_b01_every_corruption_fails_closed_without_repair(copied: Path, family: str, flaw: str) -> None:
    path = _target_path(copied, family)
    path.write_bytes(path.read_bytes() + CORRUPTIONS[flaw])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = run(copied, cutoff=CHECKPOINTS["retired"])
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert "AUTHORITY_STATE_UNUSABLE" in {f.condition_id for f in result.findings}
    assert result.report.unevaluated_conditions                                   # 黙って健全にならない
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before                # 自動修復しない


@pytest.mark.parametrize("family", CORRUPT_TARGETS)
def test_b02_a_missing_authority_file_fails_closed(copied: Path, family: str) -> None:
    _target_path(copied, family).unlink()
    result = run(copied, cutoff=CHECKPOINTS["retired"])
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert result.report.unevaluated_conditions


def test_b03_a_duplicate_conflicting_record_fails_closed(copied: Path) -> None:
    path = proposal_paths(copied)["proposals"]
    lines = path.read_bytes().splitlines(keepends=True)
    tampered = json.loads(lines[0])
    tampered["reason"] = "a different body under the same id"
    path.write_bytes(path.read_bytes() + json.dumps(tampered, ensure_ascii=False, sort_keys=True,
                                                    separators=(",", ":")).encode("utf-8") + b"\n")
    result = run(copied, cutoff=CHECKPOINTS["retired"])
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert any(code.startswith("PROPOSAL_AUTHORITY_UNUSABLE") for code in result.diagnostics)


def test_b04_an_unsupported_schema_and_an_unknown_field_fail_closed(copied: Path) -> None:
    path = relation_paths(copied)["assertions"]
    original = path.read_bytes()
    for mutate in ({"schema_version": "theme_relation_assertion:9.9.9"}, {"unexpected_field": "x"}):
        payload = json.loads(original.splitlines()[0])
        payload.update(mutate)
        path.write_bytes(original + json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")).encode("utf-8") + b"\n")
        result = run(copied, cutoff=CHECKPOINTS["retired"])
        assert result.report.status is MonitoringRunStatus.PARTIAL
        assert any(code.startswith("RELATION_AUTHORITY_UNUSABLE") for code in result.diagnostics)
    assert path.read_bytes().startswith(original)


@pytest.mark.parametrize("flaw", sorted(CORRUPTIONS))
def test_b05_a_corrupt_review_journal_never_looks_like_no_review(copied: Path, flaw: str) -> None:
    review_state_path(copied).write_bytes(CORRUPTIONS[flaw])
    result = run(copied, cutoff=CHECKPOINTS["retired"])
    assert result.review_status is ReviewLookupStatus.UNUSABLE and result.reviews == ()
    assert any(code.startswith("REVIEW_STORE_UNUSABLE") for code in result.diagnostics)
    with pytest.raises(ReviewStoreCorrupt):
        MonitoringReviewStore.open(copied)


def test_b06_a_corrupt_run_still_writes_nothing(copied: Path) -> None:
    path = theme_paths(copied)["observations"]
    path.write_bytes(path.read_bytes() + b"{not json}\n")
    before = inventory(copied)
    run(copied, cutoff=CHECKPOINTS["retired"])
    assert inventory(copied) == before


# ---------------------------------------------------------------- §D 決定論 / physical order / PIT

def test_d01_the_same_cutoff_replays_identically(world) -> None:
    root, ids = world
    first, second = full_run(root, ids), full_run(root, ids)
    assert first.report == second.report
    assert [canonical_monitoring_line(f) for f in first.findings] == [canonical_monitoring_line(f)
                                                                      for f in second.findings]
    assert first.diagnostics == second.diagnostics


@pytest.mark.parametrize("seed", SEEDS)
def test_d02_physical_journal_order_does_not_change_the_result(copied: Path, world, seed: int) -> None:
    """chain を持たない独立 record の物理順を入れ替えても、run は同一である（latest-wins を持たない）。"""
    _, ids = world
    baseline = full_run(copied, ids)
    for path in (relation_paths(copied)["assertions"], proposal_paths(copied)["proposals"]):
        lines = path.read_bytes().splitlines(keepends=True)
        random.Random(seed).shuffle(lines)
        path.write_bytes(b"".join(lines))
    shuffled = full_run(copied, ids)
    assert shuffled.report.run_id == baseline.report.run_id
    assert shuffled.report.input_digests == baseline.report.input_digests
    assert {f.finding_id for f in shuffled.findings} == {f.finding_id for f in baseline.findings}


def test_d03_a_different_cutoff_is_a_different_run(world) -> None:
    root, ids = world
    assert full_run(root, ids).report.run_id != run(root, cutoff=CHECKPOINTS["retired"]).report.run_id


@pytest.mark.parametrize("family,cutoff,condition", [
    ("theme_evidence_attachment", CHECKPOINTS["contradiction_added"], "THEME_CONTRADICTION_EVIDENCE_PRESENT"),
    ("theme_genesis_observation", CHECKPOINTS["genesis_visible"], "THEME_WITHOUT_COUNTED_EVIDENCE"),
    ("theme_governance_retirement", CHECKPOINTS["retired"], "RELATION_ENDPOINT_NOT_ACTIVE"),
])
def test_d04_foundation_records_are_invisible_one_microsecond_early(world, family: str, cutoff, condition) -> None:
    root, _ = world
    scope = SCOPE if family == "theme_governance_retirement" else (ROOT_A,)
    assert condition in {f.condition_id for f in run(root, cutoff=cutoff, root_ids=scope).findings}
    early = run(root, cutoff=cutoff - timedelta(microseconds=1), root_ids=scope)
    assert condition not in {f.condition_id for f in early.findings}


def test_d05_relation_assertions_and_governance_are_point_in_time(world) -> None:
    root, _ = world
    at_retraction = run(root, cutoff=day(4))
    before = run(root, cutoff=day(4) - timedelta(microseconds=1))
    assert "RETRACTED_RELATION_HAS_NEW_PROPOSAL" not in {f.condition_id for f in before.findings}
    assert "SOURCE_ASSERTED_RELATION_CONTESTED" in {f.condition_id for f in at_retraction.findings}
    未確立 = run(root, cutoff=day(3) - timedelta(microseconds=1))
    assert "SOURCE_ASSERTED_RELATION_CONTESTED" not in {f.condition_id for f in 未確立.findings}


def test_d06_review_state_is_operational_not_point_in_time(copied: Path) -> None:
    """review は derived fact ではなく運用状態であり、cutoff で濾過されない（設計上の意味論）。"""
    result = run(copied, cutoff=CHECKPOINTS["contradiction_added"])
    target = result.findings[0].finding_id
    MonitoringReviewStore.open(copied).append_review_state(
        ReviewItemState.build(finding_id=target, disposition=ReviewDisposition.ACKNOWLEDGED, actor_ref=REVIEWER,
                              recorded_at=day(60)))                     # cutoff より後に記録された review
    review = next(r for r in run(copied, cutoff=CHECKPOINTS["contradiction_added"]).reviews
                  if r.finding.finding_id == target)
    assert review.resolution.terminal.disposition is ReviewDisposition.ACKNOWLEDGED
    assert review.resolution.terminal.recorded_at == day(60)            # 現在の運用状態を答える


def test_d07_theme_proposal_records_after_the_cutoff_must_be_invisible(copied: Path) -> None:
    """PIT 契約: cutoff より後に記録された提案は、その cutoff の run から見えてはならない。"""
    store = ProposalStore.open(copied)
    future = evidence_candidate(created_at=day(40), reason="a candidate recorded after the cutoff")
    store.append_proposal(future)
    before = run(copied, cutoff=day(10)).report.input_digests
    after = run(copied, cutoff=day(50)).report.input_digests
    assert dict(before)["theme_proposals"] != dict(after)["theme_proposals"]


def test_d08_relation_proposals_after_the_cutoff_must_not_raise_a_conflict(copied: Path) -> None:
    """PIT 契約: day(20) に記録された関係提案は、day(5) の run で衝突を起こしてはならない。

    B6E（8655d8d）版はこの契約を検査できていなかった: 「未来」の提案が撤回 edge の無い A→C を指し、
    day(5) に出ていた衝突は day(5) 記録の既存提案（B→A、撤回は day(4)）による PIT 上正しい finding だった。
    R1 で、未来の提案を撤回済み edge B→A に向け、その提案 id だけを検査するよう修正した。"""
    future = relation_candidate(ROOT_B, ROOT_A, relation_type=RelationType.CAUSES, at=day(20),
                                rationale="a second relation candidate recorded after the cutoff")
    RelationProposalStore.open(copied).append_proposal(future)

    def conflicting(cutoff) -> set:
        return {dict(f.salient_state.facts)["relation_proposal_id"] for f in run(copied, cutoff=cutoff).findings
                if f.condition_id == "RETRACTED_RELATION_HAS_NEW_PROPOSAL"}

    assert future.proposal_id not in conflicting(day(5))
    assert future.proposal_id in conflicting(day(25))                   # fixture は cutoff 以後には効く


def test_d09_the_proposal_snapshot_is_cutoff_bound(world) -> None:
    """提案 family の input digest は cutoff 以前の record だけに束縛される。

    B6E（8655d8d）版は day(5) と day(50) の digest が等しいことを「欠陥の観測」としていたが、world には
    その間の提案 record が無く、修正の前後どちらでも等しくなる（判別力の無い観測だった）。R1 で置き換えた。"""
    root, _ = world
    first_day = dict(run(root, cutoff=day(1)).report.input_digests)        # 提案 day(1) だけが見える
    settled = dict(run(root, cutoff=day(5)).report.input_digests)          # 全提案・全決定が見える
    later = dict(run(root, cutoff=day(50)).report.input_digests)           # その後の提案 record は無い
    assert first_day["theme_proposals"] != settled["theme_proposals"]
    assert "theme_relation_proposals" not in first_day                     # 関係提案は day(5) 記録
    assert settled["theme_proposals"] == later["theme_proposals"]
    assert settled["theme_relation_proposals"] == later["theme_relation_proposals"]


# ---------------------------------------------------------------- §E zero-write / 権限 / security

#: B6D anchor 以降に変わってよい runtime（B6D-R1: runner、P6-B6R1: engine / adapter / runner）
CHANGED_SINCE_B6D = ("monitoring_adapter.py", "monitoring_engine.py", "monitoring_runner.py")


def test_e01_the_frozen_runtime_is_untouched() -> None:
    """B6D anchor 以降に変わってよい runtime は B6D-R1 と P6-B6R1 の remediation 対象だけである。"""
    import subprocess
    lines = subprocess.run(["git", "diff", "--name-status", "8ef09ab1db447ad783defd0c6afecd3e943edcfe", "--",
                            "src/intelligence/theme_intelligence", "knowledge/theme_intelligence"],
                           cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    changed = [path for status, path in (line.split("\t", 1) for line in lines)
               if not (status == "A" and path.startswith("src/intelligence/theme_intelligence/llm_"))]   # P6-B7 の新規 module
    assert set(changed) <= {f"src/intelligence/theme_intelligence/{name}" for name in CHANGED_SINCE_B6D}, changed
    for name in FROZEN_RUNTIME:
        if name in CHANGED_SINCE_B6D:
            continue
        anchored = subprocess.run(["git", "show", f"8ef09ab1db447ad783defd0c6afecd3e943edcfe:"
                                   f"src/intelligence/theme_intelligence/{name}"], cwd=REPO_ROOT,
                                  capture_output=True, check=True).stdout
        assert (PACKAGE_DIR / name).read_bytes() == anchored, name


def test_e02_a_run_changes_no_byte_anywhere_under_the_data_root(copied: Path, world) -> None:
    _, ids = world
    before = inventory(copied)
    full_run(copied, ids)
    run(copied, cutoff=CHECKPOINTS["retired"])
    run(copied, cutoff=CHECKPOINTS["genesis_visible"], root_ids=(ROOT_A,))
    after = inventory(copied)
    assert set(after) - set(before) == set() and set(before) - set(after) == set()
    assert after == before


def test_e03_authority_and_knowledge_hashes_are_unchanged(copied: Path, world) -> None:
    _, ids = world
    before = journal_digests(copied)
    full_run(copied, ids)
    assert journal_digests(copied) == before


def test_e04_neither_a_finding_nor_a_run_report_is_persisted(copied: Path, world) -> None:
    _, ids = world
    full_run(copied, ids)
    names = sorted(p.name for p in (copied / "theme_intelligence").glob("*"))
    assert "monitoring_findings.jsonl" not in names and "monitoring_runs.jsonl" not in names
    assert "monitoring_review_states.jsonl" in names
    for stem in ("finding_store", "monitoring_scheduler", "monitoring_notifier"):
        assert not (PACKAGE_DIR / f"{stem}.py").exists()


def test_e05_the_run_never_appends_a_review_or_a_governance_record() -> None:
    runner = executable_source(PACKAGE_DIR / "monitoring_runner.py")
    adapter = executable_source(PACKAGE_DIR / "monitoring_adapter.py")
    for token in ("append_review_state", "append_proposal", "append_decision", "append_assertion", "append_event",
                  "append_root", "append_observation", "append_governance", "execute_", "plan_relation_assertion",
                  "plan_evidence_attachment", "RelationAssertionPlan", "EvidenceAttachmentPlan"):
        assert token not in runner and token not in adapter, token


def test_e06_rr3_has_no_execution_path_from_monitoring() -> None:
    """RR-3: 受理済み提案 / plan から authority への自動実行経路は存在しない。"""
    for path in sorted(PACKAGE_DIR.glob("monitoring_*.py")):
        source = executable_source(path)
        for token in ("relation_proposal_bridge", "evidence_bridge", "ThemeStore", "ThemeRelationStore"):
            assert token not in source, (path.name, token)
    harness = SHADOW_HARNESS.read_text(encoding="utf-8")
    assert "append_" not in harness and "bridge" not in harness


def test_e07_finding_count_is_not_used_as_evidence_strength() -> None:
    """同一 origin 由来の観測が増えても finding identity は増殖しない（B4 / B5 の独立 origin 規律を壊さない）。"""
    one = evaluate(themes=(theme(evidence_roles_present=("CONTRADICTS",), arrived_attachment_keys=("a:1",)),))
    many = evaluate(themes=(theme(evidence_roles_present=("CONTRADICTS",),
                                  arrived_attachment_keys=("a:1", "a:2", "a:3")),))
    contradiction = [f for f in many.findings if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT"]
    assert len(contradiction) == 1
    assert contradiction[0].finding_id == next(f.finding_id for f in one.findings
                                               if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT")


def test_e08_a_contested_source_relation_says_only_that_evidence_disagrees() -> None:
    finding = next(f for f in evaluate(**POSITIVE["SOURCE_ASSERTED_RELATION_CONTESTED"]).findings)
    facts = dict(finding.salient_state.facts)
    assert facts["role"] == "CONTRADICTS" and finding.category is MonitoringCategory.RELATION
    for token in ("false", "disproven", "refuted", "invalid_relation", "probability"):
        assert token not in json.dumps(facts).lower(), token


def test_e09_the_validation_result_is_not_an_authority(world) -> None:
    root, ids = world
    result = full_run(root, ids)
    assert not hasattr(result, "authority") and not hasattr(result, "decision")
    payload = json.dumps({"fields": [f.name for f in dataclasses.fields(type(result))]})
    for token in ("authority", "governance", "decision", "plan", "score", "rank", "priority"):
        assert token not in payload.lower(), token


def test_e10_no_network_llm_scheduler_or_current_clock_in_the_harness() -> None:
    harness = executable_source(SHADOW_HARNESS)                     # docstring を除いた実行部分だけを見る
    for token in ("requests", "urllib", "socket", "openai", "anthropic", "schedule", "cron", "smtp", "slack",
                  "datetime.now", "utcnow", "time.time", "append_", "notify"):
        assert token not in harness, token


def test_e11_no_confidential_material_is_tracked() -> None:
    import subprocess
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True,
                             check=True).stdout.split()
    for name in tracked:
        assert not name.endswith((".pdf", ".jsonl", ".sqlite3", ".env")), name
    secrets = ("api" + "_key=", "pass" + "word", "Bear" + "er ", chr(92) + "Users" + chr(92), "D:" + chr(92))
    for path in (SHADOW_HARNESS, Path(__file__)):
        text = path.read_text(encoding="utf-8").replace(repr(secrets), "")
        hits = [token for token in secrets if text.count(token) > (1 if path == Path(__file__) else 0)]
        assert hits == [], (path.name, hits)


# ---------------------------------------------------------------- §F shadow harness / real-data precheck

def test_f01_the_shadow_harness_is_read_only_and_replays_identically(copied: Path) -> None:
    from tests.intelligence.theme_monitoring_shadow import main
    out = copied.parent / "summary.json"
    code = main(["--data-root", str(copied), "--cutoff", "2026-11-10T00:00:00+00:00", "--out", str(out)])
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0 and summary["wrote_nothing"] is True and summary["replay_identical"] is True
    assert summary["inventory_delta"] == {"new_files": [], "deleted_files": [], "modified_files": []}
    assert summary["run"]["status"] in ("COMPLETE", "PARTIAL") and summary["scope_root_count"] == 3


def test_f02_the_shadow_summary_carries_counts_and_codes_only(copied: Path) -> None:
    from tests.intelligence.theme_monitoring_shadow import SUMMARY_IS_COUNTS_ONLY, describe
    result = run(copied, cutoff=CHECKPOINTS["retired"])
    summary = json.loads(json.dumps(describe(result)))
    assert set(summary) >= {"run_id", "status", "finding_count_by_condition", "review_lookup_status",
                            "unevaluated_conditions", "input_digests"}
    for token in ("note", "rationale", "body", "quote", "reason", "actor_ref"):
        assert token not in json.dumps(summary).lower(), token
    assert SUMMARY_IS_COUNTS_ONLY.startswith("the shadow summary carries counts")


def test_f03_the_harness_refuses_a_naive_cutoff_and_a_missing_root(tmp_path: Path) -> None:
    from tests.intelligence.theme_monitoring_shadow import EXIT_UNAVAILABLE, main
    out = tmp_path / "s.json"
    assert main(["--data-root", str(tmp_path / "nope"), "--cutoff", "2026-11-10T00:00:00+00:00",
                 "--out", str(out)]) == EXIT_UNAVAILABLE
    assert json.loads(out.read_text(encoding="utf-8"))["error"] == "DATA_ROOT_NOT_FOUND"
    assert main(["--data-root", str(tmp_path), "--cutoff", "2026-11-10T00:00:00", "--out", str(out)]) == EXIT_UNAVAILABLE
    assert json.loads(out.read_text(encoding="utf-8"))["error"] == "CUTOFF_MUST_BE_AWARE"


def test_f04_no_theme_authority_data_root_exists_in_this_environment() -> None:
    """real-data shadow の precheck。Theme authority journal はこの環境に 1 件も存在しない。"""
    candidates = sorted(p for p in (REPO_ROOT / "data").rglob("*") if p.is_dir()
                        and p.name in ("themes", "theme_intelligence"))
    assert candidates == []
    for name in ("theme_observations.jsonl", "roots.jsonl", "relation_assertions.jsonl",
                 "monitoring_review_states.jsonl"):
        assert list((REPO_ROOT / "data").rglob(name)) == []


def test_f05_theme_intelligence_is_not_wired_into_any_production_entry_point() -> None:
    """shadow harness は validation 用の test helper であり、production entry point には置かない。"""
    for path in (sorted((REPO_ROOT / ".github").rglob("*.yml")) + sorted((REPO_ROOT / "scripts").glob("*.py"))
                 + [REPO_ROOT / "config.yaml"]):
        assert "theme_intelligence" not in path.read_text(encoding="utf-8"), path.name
    assert SHADOW_HARNESS.parent.name == "intelligence" and SHADOW_HARNESS.parent.parent.name == "tests"
    assert not SHADOW_HARNESS.name.startswith("test_")               # pytest に収集させない helper
