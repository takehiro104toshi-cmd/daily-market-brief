"""P6-B6D — monitoring runner（`monitoring_runner`）と snapshot adapter（`monitoring_adapter`）の契約 test（§25 / §26）。

データはすべて synthetic（A4d 代表 world ＋ 合成 B3 / B5B / B5C record）で、書き込みは `tmp_path` のみ。
production data root / 実 journal / network / 現在時刻には一切触れない。
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence import monitoring_runner as R
from src.intelligence.theme_intelligence.lifecycle_model import (LifecyclePolicy, ThemeLifecycleError,
                                                                 default_lifecycle_policy)
from src.intelligence.theme_intelligence.monitoring_adapter import (ADAPTER_MAPS_ONLY, AUTHORITY_RELATIONS,
                                                                    AUTHORITY_THEMES, CHAIN_STATUS_TOKENS,
                                                                    MONITORING_ADAPTER_VERSION,
                                                                    MonitoringObservations, RESOLUTION_FAILURE_CLASS,
                                                                    build_evaluation_input, contested_roots,
                                                                    excluded_relation_snapshot,
                                                                    freshness_policy_token, proposal_snapshot,
                                                                    relation_authority_failure,
                                                                    relation_proposal_snapshot, relation_snapshot,
                                                                    theme_failure_snapshot, theme_snapshot,
                                                                    TOKEN_PATTERN, _locator,
                                                                    unresolved_relation_snapshot)
from src.intelligence.theme_intelligence.monitoring_engine import (NO_CHANNEL_SUPPLIED, OBSERVATION_PRESENCE_KEY,
                                                                   RELATION_CONDITIONS, SubjectAvailability,
                                                                   ThemeSnapshot)
from src.intelligence.theme_intelligence.monitoring_model import (MonitoringRunStatus, ReviewChainStatus,
                                                                  ReviewDisposition, ReviewItemState,
                                                                  canonical_monitoring_line)
from src.intelligence.theme_intelligence.monitoring_rules import load_monitoring_rules_version, monitoring_rules_path
from src.intelligence.theme_intelligence.monitoring_runner import (MONITORING_RUNNER_VERSION, MonitoringRunResult,
                                                                   MonitoringRunnerError, ReviewLookupStatus,
                                                                   RUN_IS_READ_ONLY, run_monitoring)
from src.intelligence.theme_intelligence.monitoring_store import MonitoringReviewStore, review_state_path
from src.intelligence.theme_intelligence.proposal_model import DecisionKind, canonical_proposal_line
from src.intelligence.theme_intelligence.proposal_resolution import DecisionResolutionStatus, ProposalStatus
from src.intelligence.theme_intelligence.proposal_store import ProposalStore
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.relation_model import RelationType
from src.intelligence.theme_intelligence.relation_proposal_resolution import RelationProposalStatus
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as relation_proposal_paths
from src.intelligence.theme_intelligence.relation_resolution import (EndpointState, ExcludedEdge,
                                                                     RelationResolutionStatus, UnresolvedEdge)
from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
from src.intelligence.theme_intelligence.relation_store import authority_paths as relation_paths
from src.intelligence.themes.resolver import ResolutionStatus
from src.intelligence.themes.store import authority_paths as theme_paths
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B, ROOT_C
from tests.intelligence.test_theme_proposal import decision, evidence_candidate
from tests.intelligence.test_theme_relation import causal, retraction, sourced
from tests.intelligence.test_theme_relation_proposal import proposal as relation_candidate
from tests.intelligence.theme_foundation_fixtures import CHECKPOINTS, build_world, day

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
RUNNER = PACKAGE_DIR / "monitoring_runner.py"
ADAPTER = PACKAGE_DIR / "monitoring_adapter.py"
POLICY = default_lifecycle_policy()
SCOPE = (ROOT_A, ROOT_B, ROOT_C)
AGING_CUTOFF = day(70)
PUBLISHED = datetime(2026, 8, 1, tzinfo=UTC)
LONG_EDGE = "theme_" + "0" * 26 + "|" + "x" * 250
ARRIVED_KEY = "fact_aaaaaaaaaaaaaaaaaaaaaaaa#c1"
REVIEWER = "reviewer:r1"

REAL_RULES = load_monitoring_rules_version(monitoring_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0",
                                           cutoff=datetime(2026, 9, 30, tzinfo=UTC))
#: world の timeline（2026-09）でも使えるよう published_at だけ前倒しした同一 ruleset
RULES = dataclasses.replace(REAL_RULES, published_at=PUBLISHED)


# ---------------------------------------------------------------- fixtures（synthetic data root）

def _seed_intelligence(root: Path) -> None:
    for cls in (ProposalStore, ThemeRelationStore, RelationProposalStore, MonitoringReviewStore):
        cls.initialize(root)
    relations = ThemeRelationStore.open(root)
    relations.append_assertion(sourced(ROOT_A, ROOT_B, at=day(3)))
    retracted = causal(ROOT_B, ROOT_A, at=day(3))
    relations.append_assertion(retracted)
    relations.append_event(retraction(retracted, at=day(4)))
    candidates = RelationProposalStore.open(root)
    candidates.append_proposal(relation_candidate(ROOT_B, ROOT_A, relation_type=RelationType.CAUSES, at=day(5)))
    proposals = ProposalStore.open(root)
    proposals.append_proposal(evidence_candidate(created_at=day(1)))
    forked = evidence_candidate(created_at=day(2), reason="another candidate for the same series")
    proposals.append_proposal(forked)
    first = decision(forked.proposal_id, DecisionKind.DEFER, at=day(3))
    path = proposal_paths(root)["decisions"]
    for record in (first, decision(forked.proposal_id, DecisionKind.ACCEPT, at=day(4), supersedes=first.decision_id),
                   decision(forked.proposal_id, DecisionKind.REJECT, at=day(5), supersedes=first.decision_id)):
        path.write_bytes(path.read_bytes() + canonical_proposal_line(record).encode("utf-8"))


@pytest.fixture(scope="module")
def data_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("monitoring_world") / "data"
    build_world(root)
    _seed_intelligence(root)
    return root


@pytest.fixture()
def copied(data_root: Path, tmp_path: Path) -> Path:
    target = tmp_path / "copy" / "data"
    shutil.copytree(data_root, target)
    return target


def run(root: Path, *, cutoff=CHECKPOINTS["retired"], rules=None, **kw) -> MonitoringRunResult:
    kw.setdefault("recorded_at", cutoff)
    kw.setdefault("root_ids", SCOPE)
    kw.setdefault("lifecycle_policy", POLICY)
    return run_monitoring(data_root=root, cutoff=cutoff, ruleset=rules or RULES, **kw)


def conditions(result: MonitoringRunResult) -> set:
    return {finding.condition_id for finding in result.findings}


def journal_digests(root: Path) -> dict:
    paths = {f"themes:{k}": v for k, v in theme_paths(root).items()}
    paths.update({f"proposals:{k}": v for k, v in proposal_paths(root).items()})
    paths.update({f"relations:{k}": v for k, v in relation_paths(root).items()})
    paths.update({f"relation_proposals:{k}": v for k, v in relation_proposal_paths(root).items()})
    paths["review_states"] = review_state_path(root)
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "" for name, path in paths.items()}


# ---------------------------------------------------------------- 1〜12 入力契約（explicit / fail closed）

@pytest.mark.parametrize("root", ["", "   ", None, "~/data"])
def test_01_data_root_is_explicit_and_never_a_home_shortcut(root) -> None:
    with pytest.raises(MonitoringRunnerError) as exc:
        run_monitoring(data_root=root, cutoff=CHECKPOINTS["retired"], recorded_at=CHECKPOINTS["retired"],
                       root_ids=SCOPE, lifecycle_policy=POLICY, ruleset=RULES)
    assert exc.value.code == "DATA_ROOT_REQUIRED"


@pytest.mark.parametrize("value", [datetime(2026, 9, 12), "2026-09-12T00:00:00Z", None, 0])
def test_02_cutoff_must_be_an_aware_datetime(data_root: Path, value) -> None:
    with pytest.raises(MonitoringRunnerError) as exc:
        run(data_root, cutoff=value, recorded_at=CHECKPOINTS["retired"])
    assert exc.value.code == "INVALID_TIME"


def test_03_recorded_at_cannot_precede_the_cutoff(data_root: Path) -> None:
    with pytest.raises(MonitoringRunnerError) as exc:
        run(data_root, recorded_at=CHECKPOINTS["retired"] - timedelta(seconds=1))
    assert exc.value.code == "RECORDED_BEFORE_CUTOFF"


@pytest.mark.parametrize("scope", [("not_a_root",), ("theme_short",), (ROOT_A, "")])
def test_04_monitoring_scope_holds_theme_root_ids(data_root: Path, scope) -> None:
    with pytest.raises(MonitoringRunnerError) as exc:
        run(data_root, root_ids=scope)
    assert exc.value.code == "INVALID_ROOT_ID"


def test_05_an_empty_scope_is_reported_not_silently_accepted(data_root: Path) -> None:
    result = run(data_root, root_ids=())
    assert "EMPTY_MONITORING_SCOPE" in result.diagnostics


def test_06_the_ruleset_version_is_explicit_and_there_is_no_latest(data_root: Path) -> None:
    with pytest.raises(MonitoringRunnerError) as exc:
        run_monitoring(data_root=data_root, cutoff=AGING_CUTOFF, recorded_at=AGING_CUTOFF, root_ids=SCOPE,
                       lifecycle_policy=POLICY)
    assert exc.value.code == "RULESET_REQUIRED"
    source = executable_source(RUNNER)
    for token in ("latest_wins", "glob(", "sorted(paths", "max(versions", "def latest"):
        assert token not in source, token


def test_07_a_ruleset_and_a_version_are_not_both_accepted(data_root: Path) -> None:
    with pytest.raises(MonitoringRunnerError) as exc:
        run(data_root, cutoff=AGING_CUTOFF, knowledge_root=KNOWLEDGE_ROOT, ruleset_version="0.1.0")
    assert exc.value.code == "AMBIGUOUS_RULESET"


def test_08_an_unresolvable_ruleset_version_fails_closed(data_root: Path) -> None:
    with pytest.raises(Exception) as exc:
        run_monitoring(data_root=data_root, cutoff=AGING_CUTOFF, recorded_at=AGING_CUTOFF, root_ids=SCOPE,
                       lifecycle_policy=POLICY, knowledge_root=KNOWLEDGE_ROOT, ruleset_version="9.9.9")
    assert not isinstance(exc.value, AssertionError)


def test_09_the_versioned_ruleset_loads_from_knowledge_by_version(data_root: Path) -> None:
    result = run_monitoring(data_root=data_root, cutoff=AGING_CUTOFF, recorded_at=AGING_CUTOFF, root_ids=SCOPE,
                            lifecycle_policy=POLICY, knowledge_root=KNOWLEDGE_ROOT, ruleset_version="0.1.0")
    assert result.report.ruleset_version == "0.1.0"
    assert result.report.run_id == run(data_root, cutoff=AGING_CUTOFF, rules=REAL_RULES).report.run_id


def test_10_only_the_knowledge_actually_used_is_bound_to_the_run(data_root: Path) -> None:
    result = run(data_root)
    assert dict(result.report.knowledge_versions) == {R.LIFECYCLE_POLICY_KEY: freshness_policy_token(POLICY)}
    assert result.report.ruleset_version == RULES.ruleset_version


def test_11_a_conflicting_knowledge_binding_fails_closed(data_root: Path) -> None:
    with pytest.raises(MonitoringRunnerError) as exc:
        run(data_root, knowledge_versions=((R.LIFECYCLE_POLICY_KEY, "theme_lifecycle_policy:0.1.0|7"),))
    assert exc.value.code == "KNOWLEDGE_VERSION_CONFLICT"
    with pytest.raises(MonitoringRunnerError) as other:
        run(data_root, knowledge_versions=(("taxonomy", "0.1.0"), ("taxonomy", "0.2.0")))
    assert other.value.code == "KNOWLEDGE_VERSION_CONFLICT"


@pytest.mark.parametrize("policy", [None, "90", 90, LifecyclePolicy])
def test_12_the_freshness_policy_is_an_explicit_versioned_input(data_root: Path, policy) -> None:
    with pytest.raises(Exception) as exc:
        run(data_root, lifecycle_policy=policy)
    assert getattr(exc.value, "code", "") in ("INVALID_TYPE", "INVALID_POLICY")


# ---------------------------------------------------------------- 13〜20 PIT / 決定論 / digest

def test_13_the_same_inputs_give_the_same_run(data_root: Path) -> None:
    first, second = run(data_root), run(data_root)
    assert first.report == second.report and first.findings == second.findings
    assert first.report.input_digests == second.report.input_digests


def test_14_a_different_cutoff_is_a_different_run(data_root: Path) -> None:
    early = run(data_root, cutoff=CHECKPOINTS["first_evidence"])
    late = run(data_root, cutoff=CHECKPOINTS["retired"])
    assert early.report.run_id != late.report.run_id
    assert early.report.cutoff == CHECKPOINTS["first_evidence"]


def test_15_a_record_at_the_cutoff_is_visible_and_one_microsecond_later_is_not(data_root: Path) -> None:
    moment = CHECKPOINTS["contradiction_added"]
    at_cutoff = run(data_root, cutoff=moment)
    just_before = run(data_root, cutoff=moment - timedelta(microseconds=1))
    assert "THEME_CONTRADICTION_EVIDENCE_PRESENT" in conditions(at_cutoff)
    assert "THEME_CONTRADICTION_EVIDENCE_PRESENT" not in conditions(just_before)


def test_16_the_runner_never_reads_the_current_clock() -> None:
    for path in (RUNNER, ADAPTER):
        source = executable_source(path)
        for token in (".now(", "utcnow", "time.time", "monotonic", "date.today"):
            assert token not in source, (path.name, token)


def test_17_digests_do_not_depend_on_the_location_or_the_file_times(copied: Path, data_root: Path) -> None:
    for path in sorted(copied.rglob("*.jsonl")):
        os.utime(path, (1_600_000_000, 1_600_000_000))
    assert run(copied).report.input_digests == run(data_root).report.input_digests
    assert run(copied).report.run_id == run(data_root).report.run_id


def test_18_digests_are_independent_of_the_snapshot_order() -> None:
    snapshots = [ThemeSnapshot(theme_root_id=f"theme_{i:026d}", governance_state="ACCEPTED") for i in range(6)]
    baseline = build_evaluation_input(cutoff=day(1), themes=tuple(snapshots)).input_digests
    for seed in range(5):
        shuffled = list(snapshots)
        random.Random(seed).shuffle(shuffled)
        assert build_evaluation_input(cutoff=day(1), themes=tuple(shuffled)).input_digests == baseline


def test_19_digests_name_the_authority_they_came_from(data_root: Path) -> None:
    names = [name for name, _ in run(data_root).report.input_digests]
    assert names == sorted(names) and AUTHORITY_THEMES in names and AUTHORITY_RELATIONS in names
    for name, digest in run(data_root).report.input_digests:
        if name == OBSERVATION_PRESENCE_KEY:                          # P6-B6R1: 供給状況の束縛（digest ではない）
            assert digest == NO_CHANNEL_SUPPLIED
            continue
        assert digest.startswith("thmin_")


def test_20_no_path_inode_or_wall_clock_leaks_into_the_digest() -> None:
    source = executable_source(ADAPTER)
    for token in ("st_mtime", "st_ino", "stat(", "absolute(", "resolve()", "cwd("):
        assert token not in source, token


# ---------------------------------------------------------------- 21〜28 authority を書き換えない

def test_21_a_run_changes_no_authority_byte(copied: Path) -> None:
    before = journal_digests(copied)
    run(copied)
    run(copied, cutoff=AGING_CUTOFF, rules=REAL_RULES)
    assert journal_digests(copied) == before


def test_22_a_run_does_not_touch_the_review_journal(copied: Path) -> None:
    store = MonitoringReviewStore.open(copied)
    finding = run(copied).findings[0]
    store.append_review_state(ReviewItemState.build(finding_id=finding.finding_id,
                                                    disposition=ReviewDisposition.ACKNOWLEDGED, actor_ref=REVIEWER,
                                                    recorded_at=CHECKPOINTS["retired"]))
    before = review_state_path(copied).read_bytes()
    run(copied)
    assert review_state_path(copied).read_bytes() == before


def test_23_the_runner_never_calls_the_review_append_api() -> None:
    assert "append_review_state" not in executable_source(RUNNER)      # docstring 以外に現れない
    calls = {ast.unparse(node.func)
             for node in ast.walk(ast.parse(RUNNER.read_text(encoding="utf-8"))) if isinstance(node, ast.Call)}
    appends = {name.rsplit(".", 1)[-1] for name in calls if "append" in name}
    assert appends == {"append"}, appends                              # list への追加だけ（store API を呼ばない）
    assert not any("append_" in name for name in calls)


def test_24_the_runner_reaches_no_write_side_authority_api() -> None:
    source = executable_source(RUNNER)
    for token in ("append_assertion", "append_event", "append_proposal", "append_decision", "append_root",
                  "append_observation", "append_governance", "execute_", "plan_candidate", "plan_merge",
                  "attach_evidence", "revise_observation", "ThemeStore", "notifier", "notify", "publish",
                  "send_", "smtp", "slack", "webhook", "schedule", "cron"):
        assert token not in source, token


def test_25_authorities_are_opened_read_only() -> None:
    source = executable_source(RUNNER)
    assert source.count("read_only=True") >= 3
    assert "read_only=False" not in source


def test_26_a_monitoring_run_is_read_only_by_construction_not_by_a_flag() -> None:
    source = executable_source(RUNNER)
    for token in ("shadow", "dry_run", "apply=", "commit=", "write_back"):
        assert token not in source, token
    assert RUN_IS_READ_ONLY == "a monitoring run reads authorities and writes nothing"
    assert ADAPTER_MAPS_ONLY == "the adapter maps upstream results and never decides a condition"


def test_27_the_result_carries_no_command_plan_or_ranking(data_root: Path) -> None:
    result = run(data_root)
    payload = json.dumps({"fields": [f.name for f in dataclasses.fields(MonitoringRunResult)],
                          "diagnostics": list(result.diagnostics),
                          "conditions": sorted(conditions(result))})
    for token in ("action", "command", "plan", "priority", "severity", "signal", "prediction", "recommend",
                  "score", "rank", "buy", "sell"):
        assert token not in payload.lower(), token
    source = executable_source(RUNNER)
    for token in ("recommend", "priority", "severity", "signal", "prediction"):
        assert token not in source, token


def test_28_no_network_random_or_subprocess_in_the_runner() -> None:
    for path in (RUNNER, ADAPTER):
        imports = imported_modules(path)
        for token in ("requests", "urllib", "socket", "http", "subprocess", "random", "sqlite3", "yaml"):
            assert not any(module == token or module.endswith("." + token) for module in imports), (path.name, token)


# ---------------------------------------------------------------- 29〜40 PARTIAL の伝播（silent coercion の禁止）

def test_29_complete_means_every_requested_condition_was_evaluated(data_root: Path) -> None:
    complete_inputs = MonitoringObservations(arrived_attachment_keys={}, semantic_revision_observation_ids={},
                                             discovery_outcome_tokens={})
    result = run(data_root, cutoff=CHECKPOINTS["merge_completed"], observations=complete_inputs)
    assert result.report.status is MonitoringRunStatus.COMPLETE
    assert result.report.unevaluated_conditions == ()
    omitted = run(data_root, cutoff=CHECKPOINTS["merge_completed"])  # P6-B6R1: 観測 channel 未供給は評価不能
    assert omitted.report.status is MonitoringRunStatus.PARTIAL and omitted.report.unevaluated_conditions


def test_30_a_root_without_state_at_the_cutoff_is_unevaluated_not_false(data_root: Path) -> None:
    result = run(data_root, cutoff=CHECKPOINTS["first_evidence"])
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert "AUTHORITY_STATE_UNUSABLE" in conditions(result)
    assert any("NO_STATE_AT_CUTOFF" in code for code in result.report.diagnostics)
    assert "THEME_WITHOUT_COUNTED_EVIDENCE" in result.report.unevaluated_conditions


def test_31_a_corrupt_theme_journal_becomes_partial_not_an_empty_world(copied: Path) -> None:
    path = theme_paths(copied)["observations"]
    path.write_bytes(path.read_bytes() + b"{not json}\n")
    result = run(copied)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert "AUTHORITY_STATE_UNUSABLE" in conditions(result)
    assert any("STORE_CORRUPTION" in code or "MALFORMED" in code for code in result.report.diagnostics)


@pytest.mark.parametrize("authority,blocked", [("proposals", "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD"),
                                               ("decisions", "PROPOSAL_DECISION_CHAIN_UNRESOLVED")])
def test_32_a_missing_proposal_journal_blocks_its_conditions(copied: Path, authority: str, blocked: str) -> None:
    proposal_paths(copied)[authority].unlink()
    result = run(copied)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert blocked in result.report.unevaluated_conditions
    assert any(code.startswith("PROPOSAL_AUTHORITY_UNUSABLE") for code in result.diagnostics)


def test_33_a_missing_relation_journal_blocks_the_relation_conditions(copied: Path) -> None:
    relation_paths(copied)["assertions"].unlink()
    result = run(copied)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert set(RELATION_CONDITIONS) <= set(result.report.unevaluated_conditions)
    assert "RETRACTED_RELATION_HAS_NEW_PROPOSAL" in result.report.unevaluated_conditions


def test_34_a_missing_relation_proposal_journal_blocks_its_condition(copied: Path) -> None:
    relation_proposal_paths(copied)["proposals"].unlink()
    result = run(copied)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert "RETRACTED_RELATION_HAS_NEW_PROPOSAL" in result.report.unevaluated_conditions


def test_35_a_lifecycle_failure_is_carried_not_guessed(data_root: Path, monkeypatch) -> None:
    def boom(resolution, **kw):
        raise ThemeLifecycleError("GOVERNANCE_EVENTS_REQUIRED", "the chain is not guessed")

    monkeypatch.setattr(R, "derive_lifecycle", boom)
    result = run(data_root)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert "LIFECYCLE_UNAVAILABLE:GOVERNANCE_EVENTS_REQUIRED" in result.diagnostics
    assert "THEME_CONTRADICTION_EVIDENCE_PRESENT" not in conditions(result)


def test_36_an_endpoint_outside_the_scope_is_unevaluated_not_inactive(copied: Path) -> None:
    result = run(copied, root_ids=(ROOT_C,))
    assert "MONITORING_SCOPE_MISSES_RELATION_ENDPOINT" in result.diagnostics
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert set(RELATION_CONDITIONS) <= set(result.report.unevaluated_conditions)


@pytest.mark.parametrize("status,expected", sorted(RESOLUTION_FAILURE_CLASS.items(), key=lambda kv: kv[0].value))
def test_37_every_resolution_failure_maps_to_an_unusable_subject(status: ResolutionStatus, expected: str) -> None:
    snapshot = theme_failure_snapshot(ROOT_A, expected)
    assert snapshot.availability is SubjectAvailability.UNAVAILABLE
    assert snapshot.failure_class == expected and snapshot.authority_name == AUTHORITY_THEMES
    assert RESOLUTION_FAILURE_CLASS[status] == expected


def test_38_an_absent_proposal_status_is_not_a_false_condition() -> None:
    snapshot = proposal_snapshot("thprop_" + "a" * 24, status=None, created_at=None)
    assert snapshot.availability is SubjectAvailability.UNAVAILABLE
    assert snapshot.failure_class == "PROPOSAL_STATUS_UNAVAILABLE" and snapshot.proposal_status == ""


def test_39_an_unresolved_decision_chain_is_passed_through_not_dropped() -> None:
    snapshot = proposal_snapshot("thprop_" + "a" * 24, status=ProposalStatus.OPEN_UNRESOLVED, created_at=day(1),
                                 decision_status=DecisionResolutionStatus.UNRESOLVED, decision_diagnostic="FORK")
    assert snapshot.decision_chain_status == "UNRESOLVED" and snapshot.decision_chain_diagnostic == "FORK"
    healthy = proposal_snapshot("thprop_" + "b" * 24, status=ProposalStatus.OPEN, created_at=day(1),
                                decision_status=DecisionResolutionStatus.NONE)
    assert healthy.decision_chain_status == ""


def test_40_a_relation_proposal_with_an_unresolved_chain_is_not_conflict_free() -> None:
    for status in (RelationProposalStatus.OPEN_UNRESOLVED, RelationProposalStatus.INVALID_DECISION_HISTORY):
        snapshot = relation_proposal_snapshot("threlprop_" + "a" * 24, status=status)
        assert snapshot.availability is SubjectAvailability.UNAVAILABLE
        assert snapshot.failure_class == f"DECISION_CHAIN_{status.value}"


# ---------------------------------------------------------------- 41〜48 adapter の写像規律

def test_41_an_excluded_edge_is_unusable_never_inactive() -> None:
    snapshot = excluded_relation_snapshot(ExcludedEdge(edge_key="a|b|CAUSES|HUMAN_ASSERTED|",
                                                       reason="ENDPOINT_NOT_AVAILABLE_AT_CUTOFF:UNKNOWN_ROOT"))
    assert snapshot.availability is SubjectAvailability.UNAVAILABLE
    assert snapshot.failure_class == "ENDPOINT_UNKNOWN_ROOT" and snapshot.edge_state == ""


def test_42_an_unresolved_edge_carries_the_chain_vocabulary() -> None:
    snapshot = unresolved_relation_snapshot(UnresolvedEdge(edge_key="a|b|CAUSES|HUMAN_ASSERTED|",
                                                           status=RelationResolutionStatus.INVALID_HISTORY,
                                                           diagnostics=("INVALID_GOVERNANCE_TARGET:x",)))
    assert snapshot.governance_chain_status == "INVALID" and snapshot.governance_chain_diagnostic == "INVALID_GOVERNANCE_TARGET"
    assert CHAIN_STATUS_TOKENS[RelationResolutionStatus.UNRESOLVED] == "UNRESOLVED"


def test_43_a_whole_authority_failure_blocks_the_named_conditions() -> None:
    assert relation_authority_failure(RelationResolutionStatus.RESOLVED) is None
    assert relation_authority_failure(RelationResolutionStatus.NO_STATE) is None
    failure = relation_authority_failure(RelationResolutionStatus.STORE_CORRUPTION,
                                         blocked_condition_ids=RELATION_CONDITIONS)
    assert failure.failure_class == "STORE_CORRUPTION" and failure.blocked_condition_ids == RELATION_CONDITIONS


def test_44_an_oversized_identifier_is_folded_not_dropped() -> None:
    snapshot = excluded_relation_snapshot(ExcludedEdge(edge_key=LONG_EDGE, reason="ENDPOINT_NOT_AVAILABLE:UNKNOWN_ROOT"))
    assert snapshot.locator_token.startswith("thmloc_") and len(snapshot.locator_token) <= 200


def test_45_evidence_roles_come_from_the_upstream_flags_not_a_recount() -> None:
    source = executable_source(ADAPTER)
    for token in (".visible", "attachments", "counted", "sum(", "Counter(", "qualification"):
        assert token not in source, token
    assert "ROLE_BY_FLAG" in source and "view.evidence.flags" in source


def test_46_contested_endpoints_are_a_join_of_upstream_results(data_root: Path) -> None:
    result = run(data_root)
    contested = [f for f in result.findings if f.condition_id == "SOURCE_ASSERTED_RELATION_CONTESTED"]
    assert len(contested) == 1 and dict(contested[0].salient_state.facts)["theme_root_id"] == ROOT_A
    assert contested_roots((ThemeSnapshot(theme_root_id=ROOT_A, evidence_roles_present=("CONTRADICTS",)),
                            ThemeSnapshot(theme_root_id=ROOT_B))) == (ROOT_A,)


def test_47_the_freshness_threshold_stays_owned_by_the_lifecycle_policy() -> None:
    assert freshness_policy_token(POLICY) == "theme_lifecycle_policy:0.1.0|90"
    other = freshness_policy_token(LifecyclePolicy(stale_after_days=30))
    assert other != freshness_policy_token(POLICY)
    source = executable_source(ADAPTER)
    for token in ("timedelta", "days=", "stale_after_days >"):
        assert token not in source, token


def test_48_the_adapter_is_pure_and_touches_no_file(data_root: Path) -> None:
    source = executable_source(ADAPTER)
    for token in ("open(", "Path(", "read_bytes(", "write", "data_root", "jsonl"):
        assert token not in source, token


# ---------------------------------------------------------------- 49〜58 finding と review の分離

def test_49_findings_are_never_written_anywhere(copied: Path) -> None:
    before = sorted(p.name for p in (copied / "theme_intelligence").glob("*"))
    run(copied)
    assert sorted(p.name for p in (copied / "theme_intelligence").glob("*")) == before
    assert "monitoring_findings.jsonl" not in before


def test_50_a_missing_review_journal_is_not_nobody_reviewed(copied: Path) -> None:
    review_state_path(copied).unlink()
    result = run(copied)
    assert result.review_status is ReviewLookupStatus.NOT_INITIALIZED and result.reviews == ()
    assert "REVIEW_STORE_NOT_INITIALIZED" in result.diagnostics
    assert result.findings                                          # finding は出続ける


def test_51_a_corrupt_review_journal_is_reported_not_ignored(copied: Path) -> None:
    review_state_path(copied).write_bytes(b"{not json}\n")
    result = run(copied)
    assert result.review_status is ReviewLookupStatus.UNUSABLE and result.reviews == ()
    assert any(code.startswith("REVIEW_STORE_UNUSABLE") for code in result.diagnostics)


def test_52_an_acknowledged_finding_is_still_observed(copied: Path) -> None:
    first = run(copied)
    target = sorted(first.findings, key=lambda f: f.finding_id)[0]
    MonitoringReviewStore.open(copied).append_review_state(
        ReviewItemState.build(finding_id=target.finding_id, disposition=ReviewDisposition.ACKNOWLEDGED,
                              actor_ref=REVIEWER, recorded_at=CHECKPOINTS["retired"]))
    second = run(copied)
    assert target.finding_id in {f.finding_id for f in second.findings}
    review = next(r for r in second.reviews if r.finding.finding_id == target.finding_id)
    assert review.resolution.status is ReviewChainStatus.RESOLVED
    assert review.resolution.terminal.disposition is ReviewDisposition.ACKNOWLEDGED


def test_53_an_unreviewed_finding_resolves_to_none(copied: Path) -> None:
    result = run(copied)
    assert result.review_status is ReviewLookupStatus.AVAILABLE
    assert all(r.resolution.status is ReviewChainStatus.NONE for r in result.reviews)
    assert len(result.reviews) == len(result.findings)


def test_54_a_condition_that_disappears_does_not_rewrite_the_review_state(copied: Path) -> None:
    present = run(copied, cutoff=CHECKPOINTS["contradiction_added"])
    target = next(f for f in present.findings if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    MonitoringReviewStore.open(copied).append_review_state(
        ReviewItemState.build(finding_id=target.finding_id, disposition=ReviewDisposition.ACKNOWLEDGED,
                              actor_ref=REVIEWER, recorded_at=CHECKPOINTS["contradiction_added"]))
    before = review_state_path(copied).read_bytes()
    absent = run(copied, cutoff=CHECKPOINTS["first_evidence"])
    assert target.finding_id not in {f.finding_id for f in absent.findings}
    assert review_state_path(copied).read_bytes() == before
    assert all(r.resolution.terminal is None or r.finding.finding_id != target.finding_id for r in absent.reviews)


def test_55_the_same_condition_keeps_its_identity_when_it_comes_back(copied: Path) -> None:
    first = run(copied, cutoff=CHECKPOINTS["contradiction_added"])
    target = next(f for f in first.findings if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    MonitoringReviewStore.open(copied).append_review_state(
        ReviewItemState.build(finding_id=target.finding_id, disposition=ReviewDisposition.DEFERRED,
                              actor_ref=REVIEWER, recorded_at=CHECKPOINTS["contradiction_added"]))
    run(copied, cutoff=CHECKPOINTS["first_evidence"])                      # 一度消える
    again = run(copied, cutoff=CHECKPOINTS["merge_completed"])             # 別 cutoff で戻る
    back = next(f for f in again.findings if f.condition_id == "THEME_CONTRADICTION_EVIDENCE_PRESENT")
    assert back.finding_id == target.finding_id                            # episode identity を作らない
    review = next(r for r in again.reviews if r.finding.finding_id == target.finding_id)
    assert review.resolution.terminal.disposition is ReviewDisposition.DEFERRED     # 自動 reopen しない


def test_56_a_run_never_produces_a_review_disposition(data_root: Path) -> None:
    result = run(data_root)
    payload = json.dumps([r.resolution.status.value for r in result.reviews])
    for token in ("ACKNOWLEDGED", "DISMISSED", "DEFERRED"):
        assert token not in payload, token
    source = executable_source(RUNNER)
    for token in ("ACKNOWLEDGED", "DISMISSED", "DEFERRED", "ReviewDisposition"):
        assert token not in source, token


def test_57_review_and_finding_carry_different_meanings() -> None:
    doc = R.FindingReview.__doc__ or ""
    assert "derived fact" in doc and "operational" in doc
    assert R.MonitoringRunResult.__doc__ and "governance" in R.MonitoringRunResult.__doc__


def test_58_the_result_shape_is_bounded_and_named(data_root: Path) -> None:
    result = run(data_root)
    assert {f.name for f in dataclasses.fields(MonitoringRunResult)} == {
        "runner_version", "report", "findings", "reviews", "review_status", "diagnostics"}
    assert result.runner_version == MONITORING_RUNNER_VERSION == "theme_monitoring_runner:0.1.0"
    assert MONITORING_ADAPTER_VERSION == "theme_monitoring_adapter:0.1.0"
    assert tuple(sorted(result.diagnostics)) == result.diagnostics


# ---------------------------------------------------------------- 59〜62 store / runner 分離と境界

def test_59_the_store_and_the_runner_are_separate_modules() -> None:
    store_source = executable_source(PACKAGE_DIR / "monitoring_store.py")
    assert "run_monitoring" not in store_source and "evaluate_monitoring" not in store_source
    runner_tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    functions = {node.name for node in ast.walk(runner_tree) if isinstance(node, ast.FunctionDef)}
    assert "append_review_state" not in functions


def test_60_the_runner_imports_no_foundation_write_surface() -> None:
    imports = imported_modules(RUNNER) | imported_modules(ADAPTER)
    for module in ("..themes.store", "..themes.operations", "..themes.revision"):
        assert module not in imports, module


def test_61_observations_that_were_not_supplied_are_reported(data_root: Path) -> None:
    bare = run(data_root)
    assert {"OBSERVATION_NOT_SUPPLIED:arrived_attachment_keys",
            "OBSERVATION_NOT_SUPPLIED:semantic_revision_observation_ids",
            "OBSERVATION_NOT_SUPPLIED:discovery_outcome_tokens"} <= set(bare.diagnostics)
    supplied = run(data_root, observations=MonitoringObservations(
        arrived_attachment_keys={ROOT_A: (ARRIVED_KEY,)},
        semantic_revision_observation_ids={ROOT_A: "thobs_" + "a" * 24},
        discovery_outcome_tokens={"thprop_" + "a" * 24: "NO_ACCEPTED_PROPOSAL"}))
    assert not [code for code in supplied.diagnostics if code.startswith("OBSERVATION_NOT_SUPPLIED")]


def test_62_a_supplied_arrival_on_a_closed_root_is_observed(data_root: Path) -> None:
    """Foundation の attachment key は `#` を含み B6B の token 語彙に入らないため、安定 locator へ畳む（捨てない）。"""
    result = run(data_root, cutoff=CHECKPOINTS["merge_completed"],
                 observations=MonitoringObservations(arrived_attachment_keys={ROOT_A: (ARRIVED_KEY,)}))
    arrivals = [f for f in result.findings if f.condition_id == "RETIRED_ROOT_RECEIVED_EVIDENCE"]
    assert arrivals and arrivals[0].subject_ref == ROOT_A
    folded = dict(arrivals[0].salient_state.facts)["attachment_key"]
    assert folded == _locator(ARRIVED_KEY) and folded.startswith("thmloc_")
    assert TOKEN_PATTERN == "^[A-Za-z0-9][A-Za-z0-9_:.\\-|]*$"


def test_63_a_token_safe_identifier_is_kept_as_it_is(data_root: Path) -> None:
    plain = "fact_aaaaaaaaaaaaaaaaaaaaaaaa:c1"
    result = run(data_root, cutoff=CHECKPOINTS["merge_completed"],
                 observations=MonitoringObservations(arrived_attachment_keys={ROOT_A: (plain,)}))
    arrivals = [f for f in result.findings if f.condition_id == "RETIRED_ROOT_RECEIVED_EVIDENCE"]
    assert arrivals and dict(arrivals[0].salient_state.facts)["attachment_key"] == plain
