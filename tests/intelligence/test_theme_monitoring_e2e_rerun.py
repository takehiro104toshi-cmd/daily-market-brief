"""P6-B6E-RERUN — PIT remediation（B6D-R1）後の B6 monitoring 再検証（TEST / AUDIT ONLY）。

runtime は変更しない。B6E（`test_theme_monitoring_e2e.py`）と B6D-R1（`test_theme_monitoring_runner_pit.py`）を
補い、次を固定する:

- §1  frozen surface（R1 anchor 以降 runtime diff 0）
- §2  BLOCKER-1 の close 基準（B6E の world 上で、R1 とは独立の fixture で再確認）
- §3  解決前濾過の証明（「解決してから補正する」設計では通らないことの負の対照を含む）
- §4  PIT 保証の境界（妥当な journal では未来 record が過去を変えない／不正な journal は全 cutoff で fail closed）
- §5  corruption の追加 matrix（B3 / B5C の unsupported schema / unknown field / invalid history / 重複）
- §6  review state と authority の分離（DISMISSED / DEFERRED / ACK は authority を変えない）
- §7  RR-3（monitoring から authority 変更への経路が無い）
- §8  blind spot の実験（**現挙動を正当化するためではなく、disposition 判断の evidence として**固定する）
- §9  condition #17 の分類（store 経路では到達不能・in-memory 解決では到達可能な防御的 condition）
- §10 shadow harness の read-only / replay 契約、security

データはすべて synthetic。書き込みは `tmp_path` のみ。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence import monitoring_runner as R
from src.intelligence.theme_intelligence.monitoring_adapter import (MonitoringObservations, build_evaluation_input,
                                                                    unresolved_relation_snapshot)
from src.intelligence.theme_intelligence.monitoring_engine import evaluate_monitoring
from src.intelligence.theme_intelligence.monitoring_model import (MonitoringRunStatus, ReviewChainStatus,
                                                                  ReviewDisposition, ReviewItemState,
                                                                  canonical_monitoring_line)
from src.intelligence.theme_intelligence.monitoring_store import MonitoringReviewStore, review_state_path
from src.intelligence.theme_intelligence.proposal_model import DecisionKind, canonical_proposal_line
from src.intelligence.theme_intelligence.proposal_resolution import DecisionResolutionStatus, resolve_active_decision
from src.intelligence.theme_intelligence.proposal_store import ProposalStore
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.relation_model import RelationType
from src.intelligence.theme_intelligence.relation_proposal_model import (RelationDecisionKind,
                                                                         canonical_proposal_record_line)
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as relation_proposal_paths
from src.intelligence.theme_intelligence.relation_resolution import (RelationResolutionStatus,
                                                                     endpoint_lookup_from_roots,
                                                                     resolve_relation_graph)
from src.intelligence.themes.resolver import resolve_at_data_root
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B, ROOT_C
from tests.intelligence.test_theme_monitoring_e2e import (ARRIVED, RULES, SCOPE, STALE_POLICY, _seed_world,
                                                          journal_digests, run)
from tests.intelligence.test_theme_proposal import decision, evidence_candidate
from tests.intelligence.test_theme_relation import causal, retraction
from tests.intelligence.test_theme_relation_proposal import decide
from tests.intelligence.test_theme_relation_proposal import proposal as relation_candidate
from tests.intelligence.theme_foundation_fixtures import day

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
R1_ANCHOR = "e67a5462d41507ad6c70f8c539f91fd8d6ffc8f1"
B6E_ANCHOR = "8655d8d03a02e953c67a4dd8dac1edf805307a80"
MONITORING_RUNTIME = ("monitoring_model.py", "monitoring_engine.py", "monitoring_rules.py", "monitoring_store.py",
                      "monitoring_adapter.py", "monitoring_runner.py")
PAST = day(10)
REVIEWER = "reviewer:r1"
#: 観測 channel と、その channel が無いと成立し得なくなる condition（B6D contract §8 / §19）
CHANNEL_CONDITIONS = {
    "arrived_attachment_keys": ("RETIRED_ROOT_RECEIVED_EVIDENCE",),
    "semantic_revision_observation_ids": ("ACCEPTED_THEME_SEMANTIC_REVISION",),
    "discovery_outcome_tokens": ("DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL",
                                 "ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT"),
}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("monitoring_rerun") / "data"
    return root, _seed_world(root)


@pytest.fixture()
def copied(world, tmp_path: Path) -> Path:
    target = tmp_path / "rerun" / "data"
    shutil.copytree(world[0], target)
    return target


def signature(result) -> tuple:
    """過去 run の同一性（run_id・input digest・status・finding bytes・report / runner diagnostics）。"""
    return (result.report.run_id, result.report.input_digests, result.report.status,
            tuple(canonical_monitoring_line(f) for f in result.findings), result.report.diagnostics,
            result.diagnostics)


def fired(result) -> set:
    return {finding.condition_id for finding in result.findings}


def normalized(text: str) -> str:
    return text.replace("_", " ").casefold()


def append_raw(path: Path, line: str) -> None:
    path.write_bytes(path.read_bytes() + line.encode("utf-8"))


# ---------------------------------------------------------------- §1 frozen surface

def test_01_no_runtime_surface_changed_since_the_r1_anchor() -> None:
    changed = subprocess.run(["git", "diff", "--name-only", R1_ANCHOR, "--", "src", "knowledge", "config.yaml",
                              ".github", "scripts"], cwd=REPO_ROOT, capture_output=True, text=True,
                             check=True).stdout.split()
    assert changed == [], changed


@pytest.mark.parametrize("name", MONITORING_RUNTIME)
def test_02_every_monitoring_module_is_byte_identical_to_the_r1_anchor(name: str) -> None:
    anchored = subprocess.run(["git", "show", f"{R1_ANCHOR}:src/intelligence/theme_intelligence/{name}"],
                              cwd=REPO_ROOT, capture_output=True, check=True).stdout
    assert (PACKAGE_DIR / name).read_bytes() == anchored


def test_03_the_original_b6e_evidence_commit_is_still_in_history() -> None:
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", B6E_ANCHOR, "HEAD"], cwd=REPO_ROOT)
    assert ancestry.returncode == 0                                   # revert / squash / rewrite していない


# ---------------------------------------------------------------- §2 BLOCKER-1 close 基準

def _assert_past_unchanged(root: Path, mutate) -> None:
    before = signature(run(root, cutoff=PAST))
    mutate(root)
    assert signature(run(root, cutoff=PAST)) == before


def test_10_a_future_b3_proposal_does_not_affect_a_past_run(copied: Path) -> None:
    def mutate(root):
        store = ProposalStore.open(root)
        future = evidence_candidate(created_at=day(40), reason="a candidate recorded after the past cutoff")
        store.append_proposal(future)
        store.append_decision(decision(future.proposal_id, DecisionKind.DEFER, at=day(41)))
    _assert_past_unchanged(copied, mutate)


def test_11_a_future_b3_decision_does_not_affect_a_past_run(copied: Path, world) -> None:
    _, ids = world
    _assert_past_unchanged(copied, lambda root: ProposalStore.open(root).append_decision(
        decision(ids["open"], DecisionKind.ACCEPT, at=day(40))))


def test_12_a_future_b5c_proposal_does_not_affect_a_past_run(copied: Path) -> None:
    _assert_past_unchanged(copied, lambda root: RelationProposalStore.open(root).append_proposal(
        relation_candidate(ROOT_B, ROOT_A, relation_type=RelationType.CAUSES, at=day(40),
                           rationale="a relation candidate recorded after the past cutoff")))


def test_13_a_future_b5c_decision_does_not_affect_a_past_run(copied: Path) -> None:
    candidate = RelationProposalStore.open(copied, read_only=True).proposals()[0]
    _assert_past_unchanged(copied, lambda root: RelationProposalStore.open(root).append_decision(
        decide(candidate, RelationDecisionKind.REJECT, at=day(40))))


def test_14_a_future_b3_successor_does_not_change_the_past_terminal(copied: Path, world) -> None:
    _, ids = world
    terminal = resolve_active_decision(ids["deferred"],
                                       ProposalStore.open(copied, read_only=True).decisions_for(ids["deferred"]))
    _assert_past_unchanged(copied, lambda root: ProposalStore.open(root).append_decision(
        decision(ids["deferred"], DecisionKind.REJECT, at=day(40), supersedes=terminal.active_decision.decision_id)))


def test_15_a_future_b5c_successor_does_not_change_the_past_terminal(copied: Path) -> None:
    store = RelationProposalStore.open(copied)
    candidate = store.proposals()[0]
    first = decide(candidate, RelationDecisionKind.DEFER, at=day(6))
    store.append_decision(first)
    _assert_past_unchanged(copied, lambda root: RelationProposalStore.open(root).append_decision(
        decide(candidate, RelationDecisionKind.REJECT, at=day(40), supersedes=first.decision_id)))


def test_16_a_future_b3_fork_does_not_make_the_past_chain_unresolved(copied: Path, world) -> None:
    _, ids = world
    terminal = resolve_active_decision(ids["deferred"],
                                       ProposalStore.open(copied, read_only=True).decisions_for(ids["deferred"]))
    predecessor = terminal.active_decision.decision_id

    def mutate(root):
        path = proposal_paths(root)["decisions"]
        for kind, at in ((DecisionKind.ACCEPT, day(40)), (DecisionKind.REJECT, day(41))):
            append_raw(path, canonical_proposal_line(decision(ids["deferred"], kind, at=at, supersedes=predecessor)))
    _assert_past_unchanged(copied, mutate)
    later = run(copied, cutoff=day(50))
    assert any(dict(f.salient_state.facts).get("subject_token") == ids["deferred"] for f in later.findings
               if f.condition_id == "PROPOSAL_DECISION_CHAIN_UNRESOLVED")          # fork は cutoff 以後には見える


def test_17_the_close_criteria_cover_every_part_of_the_past_run(copied: Path) -> None:
    """signature が run_id・input digest・findings・diagnostics・status のすべてを含むこと自体を固定する。"""
    result = run(copied, cutoff=PAST)
    parts = signature(result)
    assert parts[0] == result.report.run_id and parts[1] == result.report.input_digests
    assert parts[2] is result.report.status and parts[4] == result.report.diagnostics
    assert parts[5] == result.diagnostics and len(parts[3]) == len(result.findings)


# ---------------------------------------------------------------- §3 解決前濾過の証明

def _future_fork(root: Path) -> str:
    candidate = evidence_candidate(created_at=day(1), reason="chain that forks only after the cutoff")
    store = ProposalStore.open(root)
    store.append_proposal(candidate)
    first = decision(candidate.proposal_id, DecisionKind.DEFER, at=day(3))
    store.append_decision(first)
    path = proposal_paths(root)["decisions"]
    for kind, at in ((DecisionKind.ACCEPT, day(80)), (DecisionKind.REJECT, day(81))):
        append_raw(path, canonical_proposal_line(decision(candidate.proposal_id, kind, at=at,
                                                          supersedes=first.decision_id)))
    return candidate.proposal_id


def _chain_findings(result, proposal_id: str) -> list:
    return [f for f in result.findings if f.condition_id == "PROPOSAL_DECISION_CHAIN_UNRESOLVED"
            and dict(f.salient_state.facts).get("subject_token") == proposal_id]


def test_20_the_runner_filters_before_the_resolver_runs(copied: Path) -> None:
    proposal_id = _future_fork(copied)
    assert _chain_findings(run(copied, cutoff=day(70)), proposal_id) == []
    assert _chain_findings(run(copied, cutoff=day(90)), proposal_id)


def test_21_a_resolve_first_design_has_nothing_left_to_correct(copied: Path) -> None:
    """全 record を解いた結果には、過去時点の終端を復元する情報が残っていない（事後補正では通らない）。"""
    proposal_id = _future_fork(copied)
    resolution = resolve_active_decision(proposal_id, ProposalStore.open(copied, read_only=True).decisions_for(proposal_id))
    assert resolution.status is DecisionResolutionStatus.UNRESOLVED
    assert resolution.active_decision is None and resolution.chain == ()


def test_22_negative_control_an_unfiltered_runner_leaks_the_future_fork(copied: Path, monkeypatch) -> None:
    """濾過を外した runner（runtime は変えず test 内で差し替え）では同じ test が落ちることを示す。"""
    proposal_id = _future_fork(copied)
    monkeypatch.setattr(R, "_visible_at", lambda records, attribute, cutoff: tuple(records))
    assert _chain_findings(run(copied, cutoff=day(70)), proposal_id)          # 漏れる＝test に判別力がある


# ---------------------------------------------------------------- §4 PIT 保証の境界

def test_30_a_fork_can_only_reach_a_journal_out_of_band(copied: Path) -> None:
    """正規の append 経路では B3 / B5C どちらも fork を書けない（PIT 不変性の対象は妥当な journal）。"""
    theme = ProposalStore.open(copied)
    candidate = evidence_candidate(created_at=day(1), reason="append path fork attempt")
    theme.append_proposal(candidate)
    first = decision(candidate.proposal_id, DecisionKind.DEFER, at=day(3))
    theme.append_decision(first)
    theme.append_decision(decision(candidate.proposal_id, DecisionKind.ACCEPT, at=day(4),
                                   supersedes=first.decision_id))
    with pytest.raises(Exception) as b3:
        theme.append_decision(decision(candidate.proposal_id, DecisionKind.REJECT, at=day(5),
                                       supersedes=first.decision_id))
    relation = RelationProposalStore.open(copied)
    subject = relation.proposals()[0]
    origin = decide(subject, RelationDecisionKind.DEFER, at=day(6))
    relation.append_decision(origin)
    relation.append_decision(decide(subject, RelationDecisionKind.REJECT, at=day(7), supersedes=origin.decision_id))
    with pytest.raises(Exception) as b5c:
        relation.append_decision(decide(subject, RelationDecisionKind.DEFER, at=day(8),
                                        supersedes=origin.decision_id))
    assert "PREDECESSOR" in str(b3.value) or "FORK" in str(b3.value)
    assert "PREDECESSOR" in str(b5c.value)


def test_31_an_out_of_band_b5c_fork_fails_the_authority_closed_at_every_cutoff(copied: Path) -> None:
    """B5C store は fork を load 時に拒否する。未来の時刻でも「読み飛ばして過去を健全に見せる」ことはしない。"""
    store = RelationProposalStore.open(copied)
    subject = store.proposals()[0]
    origin = decide(subject, RelationDecisionKind.DEFER, at=day(6))
    store.append_decision(origin)
    path = relation_proposal_paths(copied)["decisions"]
    for kind, at in ((RelationDecisionKind.REJECT, day(40)), (RelationDecisionKind.DEFER, day(41))):
        append_raw(path, canonical_proposal_record_line(decide(subject, kind, at=at, supersedes=origin.decision_id)))
    for cutoff in (PAST, day(50)):
        result = run(copied, cutoff=cutoff)
        assert result.report.status is MonitoringRunStatus.PARTIAL
        assert "RELATION_PROPOSAL_AUTHORITY_UNUSABLE:NOT_TERMINAL_PREDECESSOR" in result.diagnostics
        assert "RETRACTED_RELATION_HAS_NEW_PROPOSAL" in result.report.unevaluated_conditions


# ---------------------------------------------------------------- §5 corruption の追加 matrix

def _mutated_line(path: Path, **changes) -> str:
    payload = json.loads(path.read_bytes().splitlines()[0])
    payload.update(changes)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


@pytest.mark.parametrize("family", ["proposals", "relation_proposals"])
@pytest.mark.parametrize("flaw", ["unsupported_schema", "unknown_field", "conflicting_duplicate"])
def test_40_b3_and_b5c_record_flaws_fail_closed(copied: Path, family: str, flaw: str) -> None:
    path = (proposal_paths(copied) if family == "proposals" else relation_proposal_paths(copied))["proposals"]
    changes = {"unsupported_schema": {"schema_version": "theme_proposal:9.9.9"},
               "unknown_field": {"unexpected_field": "x"},
               "conflicting_duplicate": {"created_at": "2026-09-02T12:00:00Z"}}[flaw]
    original = path.read_bytes()
    append_raw(path, _mutated_line(path, **changes))
    result = run(copied, cutoff=PAST)
    prefix = "PROPOSAL_AUTHORITY_UNUSABLE" if family == "proposals" else "RELATION_PROPOSAL_AUTHORITY_UNUSABLE"
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert any(code.startswith(prefix) for code in result.diagnostics)
    assert path.read_bytes().startswith(original)                              # 修復しない


@pytest.mark.parametrize("family", ["proposals", "relation_proposals"])
def test_41_a_dangling_decision_predecessor_is_invalid_history(copied: Path, world, family: str) -> None:
    _, ids = world
    if family == "proposals":
        line = canonical_proposal_line(decision(ids["open"], DecisionKind.DEFER, at=day(6),
                                                supersedes="thdec_" + "9" * 24))
        path, prefix = proposal_paths(copied)["decisions"], "PROPOSAL_AUTHORITY_UNUSABLE"
    else:
        subject = RelationProposalStore.open(copied, read_only=True).proposals()[0]
        line = canonical_proposal_record_line(decide(subject, RelationDecisionKind.DEFER, at=day(6),
                                                     supersedes="threldec_" + "9" * 24))
        path, prefix = relation_proposal_paths(copied)["decisions"], "RELATION_PROPOSAL_AUTHORITY_UNUSABLE"
    append_raw(path, line)
    result = run(copied, cutoff=PAST)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert any(code.startswith(prefix) for code in result.diagnostics)


def test_42_a_future_dated_malformed_line_is_not_ignored(copied: Path) -> None:
    for path in (proposal_paths(copied)["decisions"], relation_proposal_paths(copied)["decisions"]):
        original = path.read_bytes()
        append_raw(path, '{"recorded_at":"2099-01-01T00:00:00Z","decision":\n')
        assert run(copied, cutoff=PAST).report.status is MonitoringRunStatus.PARTIAL
        path.write_bytes(original)


# ---------------------------------------------------------------- §6 review state と authority の分離

def _proposal_aging(result, proposal_id: str) -> set:
    return {f.condition_id for f in result.findings if dict(f.salient_state.facts).get("proposal_id") == proposal_id}


@pytest.mark.parametrize("disposition", list(ReviewDisposition))
def test_50_a_review_changes_no_authority_and_no_finding(copied: Path, world, disposition: ReviewDisposition) -> None:
    root, ids = copied, world[1]
    before = run(root, cutoff=day(70), policy=STALE_POLICY)
    target = next(f for f in before.findings if f.condition_id == "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD")
    hashes = {k: v for k, v in journal_digests(root).items() if k != "review_states"}
    theme = resolve_at_data_root(root, ROOT_A, day(70))
    MonitoringReviewStore.open(root).append_review_state(ReviewItemState.build(
        finding_id=target.finding_id, disposition=disposition, actor_ref=REVIEWER, recorded_at=day(70)))
    after = run(root, cutoff=day(70), policy=STALE_POLICY)
    assert [canonical_monitoring_line(f) for f in after.findings] == [canonical_monitoring_line(f)
                                                                      for f in before.findings]
    assert _proposal_aging(after, ids["deferred"]) == _proposal_aging(before, ids["deferred"])
    assert {k: v for k, v in journal_digests(root).items() if k != "review_states"} == hashes
    assert resolve_at_data_root(root, ROOT_A, day(70)) == theme                # review journal は Theme authority ではない
    review = next(r for r in after.reviews if r.finding.finding_id == target.finding_id)
    assert review.resolution.status is ReviewChainStatus.RESOLVED and review.resolution.terminal.disposition is disposition


def test_51_a_review_deferral_is_not_a_proposal_deferral(copied: Path, world) -> None:
    """review の DEFERRED は B3 の DEFER 決定を作らない（B3 journal は byte 不変）。"""
    _, ids = world
    result = run(copied, cutoff=day(70), policy=STALE_POLICY)
    target = next(f for f in result.findings if f.condition_id == "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD")
    decisions = proposal_paths(copied)["decisions"].read_bytes()
    MonitoringReviewStore.open(copied).append_review_state(ReviewItemState.build(
        finding_id=target.finding_id, disposition=ReviewDisposition.DEFERRED, actor_ref=REVIEWER, recorded_at=day(70)))
    after = run(copied, cutoff=day(70), policy=STALE_POLICY)
    assert proposal_paths(copied)["decisions"].read_bytes() == decisions
    assert "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD" in _proposal_aging(after, ids["open"])   # OPEN のまま


# ---------------------------------------------------------------- §7 RR-3

def test_60_monitoring_builds_no_authority_record() -> None:
    for name in ("monitoring_runner.py", "monitoring_adapter.py", "monitoring_store.py"):
        tree = ast.parse((PACKAGE_DIR / name).read_text(encoding="utf-8"))
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        assert not [c for c in calls if c.endswith(".build") and "ReviewItemState" not in c], (name, calls)
        source = executable_source(PACKAGE_DIR / name)
        # 撤回 edge を「読む」こと（EdgeState / RETRACTED_CONFLICT_TOKEN）は read 側。禁止するのは event の構築
        for token in ("RelationGovernanceEventType", "GovernanceEventType", "ThemeRelationGovernanceEvent",
                      "ThemeGovernanceEvent.build", "RelationAssertionPlan", "EvidenceAttachmentPlan", "bridge",
                      "append_assertion",
                      "append_event", "append_governance", "append_observation", "append_decision",
                      "append_proposal", "attach_evidence", "execute"):
            assert token not in source, (name, token)


def test_61_no_monitoring_module_imports_a_write_side_or_execution_module() -> None:
    for path in sorted(PACKAGE_DIR.glob("monitoring_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        for forbidden in ("proposal_bridge", "relation_proposal_bridge", "evidence_bridge", "themes.operations",
                          "themes.revision", "themes.store"):
            assert not any(m.endswith(forbidden) for m in modules), (path.name, forbidden)


# ---------------------------------------------------------------- §8 blind spot の実験（evidence）

def _channels(ids: dict) -> dict:
    return {"arrived_attachment_keys": {ROOT_A: (ARRIVED,)},
            "semantic_revision_observation_ids": {ROOT_C: ids["revision"]},
            "discovery_outcome_tokens": {ids["open"]: "NO_ACCEPTED_PROPOSAL", ids["deferred"]: "NO_OBSERVED_EFFECT"}}


BLIND_CONDITIONS = frozenset(c for group in CHANNEL_CONDITIONS.values() for c in group)
CASES = ("all_supplied", "all_omitted") + tuple(f"omit:{name}" for name in CHANNEL_CONDITIONS)


def _supplied(case: str, ids: dict) -> dict:
    channels = _channels(ids)
    if case == "all_supplied":
        return channels
    if case == "all_omitted":
        return {}
    return {k: v for k, v in channels.items() if k != case.split(":", 1)[1]}


@pytest.mark.parametrize("case", CASES)
def test_70_blind_spot_current_behavior(world, case: str) -> None:
    """現挙動の記録。チャネルが欠けても report は COMPLETE・未評価 0・report diagnostics 空のまま、
    そのチャネルに依存する condition だけが黙る。runner の diagnostics だけが欠落を述べる。"""
    root, ids = world
    supplied = _supplied(case, ids)
    result = run(root, cutoff=day(70), policy=STALE_POLICY, observations=MonitoringObservations(**supplied))
    omitted = [name for name in CHANNEL_CONDITIONS if name not in supplied]
    silenced = {c for name in omitted for c in CHANNEL_CONDITIONS[name]}
    assert result.report.status is MonitoringRunStatus.COMPLETE
    assert result.report.unevaluated_conditions == ()
    assert result.report.diagnostics == ()                                    # report には痕跡が無い
    assert fired(result) & BLIND_CONDITIONS == BLIND_CONDITIONS - silenced
    assert sorted(code.split(":", 1)[1] for code in result.diagnostics
                  if code.startswith("OBSERVATION_NOT_SUPPLIED:")) == sorted(omitted)


def test_71_the_report_alone_cannot_tell_an_omitted_channel_from_an_empty_one(world) -> None:
    """report が束縛するのは snapshot の digest だけで、「供給されなかった」は読み取れない。"""
    root, ids = world
    omitted = run(root, cutoff=day(70), policy=STALE_POLICY)
    empty = run(root, cutoff=day(70), policy=STALE_POLICY, observations=MonitoringObservations(
        arrived_attachment_keys={ROOT_B: ()}, semantic_revision_observation_ids={ROOT_B: ""},
        discovery_outcome_tokens={ids["forked"]: ""}))
    assert omitted.report.status is empty.report.status is MonitoringRunStatus.COMPLETE
    assert omitted.report.unevaluated_conditions == empty.report.unevaluated_conditions == ()
    assert omitted.report.diagnostics == empty.report.diagnostics == ()
    assert any(code.startswith("OBSERVATION_NOT_SUPPLIED:") for code in omitted.diagnostics)
    assert not any(code.startswith("OBSERVATION_NOT_SUPPLIED:") for code in empty.diagnostics)


def test_72_the_engine_already_marks_a_missing_required_input_unevaluated() -> None:
    """B6C の先例: 必要な入力が無い condition は未評価になる（freshness token / created_at）。"""
    from src.intelligence.theme_intelligence.monitoring_engine import ProposalSnapshot, ThemeSnapshot
    evaluation = evaluate_monitoring(build_evaluation_input(
        cutoff=day(70), themes=(ThemeSnapshot(theme_root_id=ROOT_A, evidence_flags=("STALE",)),),
        proposals=(ProposalSnapshot(proposal_id="thprop_" + "a" * 24, proposal_status="OPEN"),)),
        ruleset=RULES, recorded_at=day(70))
    assert evaluation.report.status is MonitoringRunStatus.PARTIAL
    assert {"THEME_EVIDENCE_STALE", "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD"} <= set(
        evaluation.report.unevaluated_conditions)
    assert {"FRESHNESS_POLICY_TOKEN_MISSING", "PROPOSAL_CREATED_AT_MISSING"} <= set(evaluation.report.diagnostics)


def test_73_the_runner_has_no_source_for_the_three_channels() -> None:
    """runner 自身はこの 3 channel を authority から導かない（呼び出し側が渡さない限り常に未供給）。"""
    source = executable_source(PACKAGE_DIR / "monitoring_runner.py")
    for name in CHANNEL_CONDITIONS:
        # channel は呼び出し側の `observations.<name>` から読むだけで、store から導く経路が無い
        # （同名の出現は adapter への keyword 受け渡し `<name>=` だけ）
        assert source.count(f"observations.{name}") >= 1, name
        stray = re.findall(rf"(?<!observations\.)\b{name}\b(?!=)", source)
        assert stray == [], (name, stray)
    assert "MonitoringObservations()" in source                              # 既定は空の channel


# ---------------------------------------------------------------- §9 condition #17 の分類

def test_80_condition_17_is_reachable_from_an_in_memory_resolution() -> None:
    """store を通さない解決（in-memory）では UnresolvedEdge が生じ、adapter → engine で #17 が出る。

    store 経路では B5B が load 時に拒否するため到達しない（B6E `test_c04`）。dead code ではなく防御的 condition。"""
    edge = causal(ROOT_A, ROOT_B, at=day(3))
    events = (retraction(edge, at=day(4)), retraction(edge, reason="withdrawn once more", at=day(5)))
    resolution = resolve_relation_graph((edge,), events, cutoff=day(9),
                                        endpoint_lookup=endpoint_lookup_from_roots({ROOT_A: day(0), ROOT_B: day(0)}))
    assert resolution.status is RelationResolutionStatus.UNRESOLVED and len(resolution.unresolved) == 1
    evaluation = evaluate_monitoring(build_evaluation_input(
        cutoff=day(9), relations=(unresolved_relation_snapshot(resolution.unresolved[0]),)),
        ruleset=RULES, recorded_at=day(9))
    assert "RELATION_GOVERNANCE_CHAIN_UNRESOLVED" in {f.condition_id for f in evaluation.findings}


# ---------------------------------------------------------------- §10 shadow harness / security

def test_90_the_shadow_harness_replays_itself_identically(copied: Path) -> None:
    from tests.intelligence.theme_monitoring_shadow import main
    outs = []
    for index in range(2):
        out = copied.parent / f"summary_{index}.json"
        assert main(["--data-root", str(copied), "--cutoff", "2026-11-10T00:00:00+00:00", "--out", str(out)]) == 0
        outs.append(json.loads(out.read_text(encoding="utf-8")))
    assert outs[0] == outs[1]
    assert outs[0]["wrote_nothing"] is True and outs[0]["replay_identical"] is True


def test_91_tracked_files_carry_no_production_or_confidential_material() -> None:
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True,
                             check=True).stdout.split()
    assert not [n for n in tracked if n.endswith((".pdf", ".jsonl", ".sqlite3", ".env"))]
    machine_paths = ("C:" + chr(92) + "Users", "D:" + chr(92), "/Users/")
    credentials = ("api" + "_key=", "Bear" + "er ", "BEGIN " + "PRIVATE")
    monitoring_files = [n for n in tracked if "monitoring" in n and n.endswith((".py", ".md"))]
    assert monitoring_files
    for name in monitoring_files:
        if name == "tests/intelligence/test_theme_monitoring_e2e_rerun.py":
            continue                                                          # 本 file は検査語そのものを持つ
        lines = (REPO_ROOT / name).read_text(encoding="utf-8").splitlines()
        assert not [p for p in machine_paths for line in lines if p in line], name
        for line in lines:
            hits = [p for p in credentials if p in line]
            if not hits:
                continue
            # src / docs には一切置かない。test では guard の adversarial fixture（予約 domain）か denylist 走査だけ
            assert name.startswith("tests/"), (name, hits)
            assert "example." in line or "for token in" in line, (name, line.strip())


def test_92_no_real_theme_authority_exists_to_shadow() -> None:
    data = REPO_ROOT / "data"
    for name in ("roots.jsonl", "theme_observations.jsonl", "proposals.jsonl", "relation_assertions.jsonl",
                 "relation_proposals.jsonl", "monitoring_review_states.jsonl"):
        assert list(data.rglob(name)) == [], name
