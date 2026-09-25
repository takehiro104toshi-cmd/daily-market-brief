"""P6-B6R1-RERUN — coverage completeness remediation の独立再検証（TEST / AUDIT ONLY）。

B6R1 の regression matrix（`test_theme_monitoring_coverage.py`）の helper・world を使わず、別の構築経路で確かめる:

- 依存表: 期待値を写さず、engine / runner の source（AST）から導いて監督指示の期待値と照合する
- engine 経路: snapshot を手で組み、adapter / runner を通さずに `evaluate_monitoring` へ渡す
- runner 経路: 代表 world を `retired` stage で止め、B6R1 とは別の提案・relation を足した data root
- finding 非回帰: B6 freeze（`99d45ef`）の runtime を git から一時展開し、別 process で同じ data root を評価する
- report 単体: canonical な report 1 行だけから coverage を読む（runner の結果・diagnostics を使わない）

runtime（src / knowledge / config / .github / scripts）は変更しない。データはすべて synthetic、書き込みは `tmp_path` のみ。
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.lifecycle_model import default_lifecycle_policy
from src.intelligence.theme_intelligence.monitoring_adapter import MonitoringObservations, build_evaluation_input
from src.intelligence.theme_intelligence.monitoring_engine import (OBSERVATION_CHANNEL_CONDITIONS,
                                                                   MonitoringEvaluationInput, ProposalSnapshot,
                                                                   ThemeSnapshot, evaluate_monitoring)
from src.intelligence.theme_intelligence.monitoring_model import (MonitoringRunReport, MonitoringRunStatus,
                                                                  ReviewDisposition, ReviewItemState,
                                                                  canonical_monitoring_line)
from src.intelligence.theme_intelligence.monitoring_rules import (CONDITION_REGISTRY, load_monitoring_rules_version,
                                                                  monitoring_rules_path)
from src.intelligence.theme_intelligence.monitoring_runner import run_monitoring
from src.intelligence.theme_intelligence.monitoring_store import MonitoringReviewStore, review_state_path
from src.intelligence.theme_intelligence.proposal_model import DecisionKind, canonical_proposal_line
from src.intelligence.theme_intelligence.proposal_store import ProposalStore
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.relation_model import RelationType
from src.intelligence.theme_intelligence.relation_proposal_model import (RelationDecisionKind,
                                                                         canonical_proposal_record_line)
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as relation_proposal_paths
from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
from src.intelligence.themes.store import authority_paths as theme_paths
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B
from tests.intelligence.test_theme_proposal import decision, evidence_candidate
from tests.intelligence.test_theme_relation import causal, retraction
from tests.intelligence.test_theme_relation_proposal import decide
from tests.intelligence.test_theme_relation_proposal import proposal as relation_candidate
from tests.intelligence.theme_foundation_fixtures import CHECKPOINTS, build_world, day

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
RULESET_PATH = "knowledge/theme_intelligence/monitoring_rules.0.1.0.yaml"
AUDIT_DOC = "docs/databank/PHASE6_THEME_B6_COMPLETION_AUDIT.md"
B6_FREEZE = "99d45ef0c1474d5bc66a19c1333eab0b28e2e339"
B6R1_ANCHOR = "36209010810641c7f6a58c5b9bd0229d45d50401"
B6R1_MODULES = ("monitoring_adapter.py", "monitoring_engine.py", "monitoring_runner.py")
RUNTIME_SURFACE = ("src", "knowledge", "config.yaml", ".github", "scripts")
POLICY = default_lifecycle_policy()
SCOPE = (ROOT_A, ROOT_B)
#: runner 経路の cutoff: CA では ROOT_A が ACCEPTED、CR では RETIRED
CA = CHECKPOINTS["semantic_revision"]
CR = CHECKPOINTS["retired"]
RULES = dataclasses.replace(
    load_monitoring_rules_version(monitoring_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0",
                                  cutoff=datetime(2026, 9, 30, tzinfo=UTC)),
    published_at=datetime(2026, 8, 1, tzinfo=UTC))                 # 内容は同一。world の timeline で使えるよう前倒し

#: 監督指示 §3 の期待値（engine の定数は使わない。source から導いた表と照合する）
DIRECTIVE_MAP = {
    "semantic_revision_observation_ids": frozenset({"ACCEPTED_THEME_SEMANTIC_REVISION"}),
    "arrived_attachment_keys": frozenset({"RETIRED_ROOT_RECEIVED_EVIDENCE"}),
    "discovery_outcome_tokens": frozenset({"DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL",
                                           "ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT"}),
}
CHANNELS = tuple(sorted(DIRECTIVE_MAP))
DEPENDENTS = frozenset().union(*DIRECTIVE_MAP.values())
PRESENCE_KEY = "observation_channels_supplied"
NOT_SUPPLIED_PREFIX = "OBSERVATION_NOT_SUPPLIED:"
EMPTY, NONEMPTY, OMITTED = "empty", "nonempty", "omitted"

_ALL = {name: NONEMPTY for name in CHANNELS}
CASES = {
    "A_all_supplied_empty": {name: EMPTY for name in CHANNELS},
    "B_all_supplied_nonempty": dict(_ALL),
    "C_all_omitted": {name: OMITTED for name in CHANNELS},
    "D_only_arrived_omitted": {**_ALL, "arrived_attachment_keys": OMITTED},
    "E_only_semantic_revision_omitted": {**_ALL, "semantic_revision_observation_ids": OMITTED},
    "F_only_discovery_omitted": {**_ALL, "discovery_outcome_tokens": OMITTED},
}


def omitted(case: dict) -> set:
    return {name for name, state in case.items() if state == OMITTED}


def expected_unevaluated(case: dict) -> set:
    return set().union(*(DIRECTIVE_MAP[name] for name in omitted(case)))


def not_supplied_codes(codes) -> set:
    return {code[len(NOT_SUPPLIED_PREFIX):] for code in codes if code.startswith(NOT_SUPPLIED_PREFIX)}


def git(*args: str, text: bool = True):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=text, check=True).stdout


# ================================================================ §1 / §18 runtime freeze

def is_b7_addition(status: str, path: str) -> bool:
    """P6-B7 以降に**新規追加**された LLM 提案層 module（`theme_intelligence/llm_*.py`）だけを除外する。既存 file の変更は除外しない。"""
    parent, _, name = path.rpartition("/")
    return (status in ("A", "??") and parent == "src/intelligence/theme_intelligence" and name.startswith("llm_")
            and name.endswith(".py"))


def runtime_changes(anchor: str) -> set:
    changed = set()
    for line in git("diff", "--name-status", anchor, "--", *RUNTIME_SURFACE).splitlines():
        status, path = line.split("\t", 1)
        if not is_b7_addition(status[:1], path):
            changed.add(path)
    return changed


def test_01_no_runtime_file_changed_since_the_b6r1_anchor() -> None:
    assert runtime_changes(B6R1_ANCHOR) == set()
    pending = [line for line in git("status", "--porcelain", "--", *RUNTIME_SURFACE).splitlines()
               if not is_b7_addition(line[:2].strip(), line[3:])]
    assert pending == []


def test_02_the_only_runtime_change_since_the_b6_freeze_is_the_three_approved_modules() -> None:
    assert runtime_changes(B6_FREEZE) == {f"src/intelligence/theme_intelligence/{name}" for name in B6R1_MODULES}


@pytest.mark.parametrize("path", ["src/intelligence/theme_intelligence/monitoring_model.py",
                                  "src/intelligence/theme_intelligence/monitoring_rules.py",
                                  "src/intelligence/theme_intelligence/monitoring_store.py", RULESET_PATH])
def test_03_model_rules_store_and_ruleset_are_byte_identical_to_the_b6_freeze(path: str) -> None:
    assert (REPO_ROOT / path).read_bytes() == git("show", f"{B6_FREEZE}:{path}", text=False)


def test_04_both_anchors_remain_in_history() -> None:
    for anchor in (B6_FREEZE, B6R1_ANCHOR):
        assert subprocess.run(["git", "merge-base", "--is-ancestor", anchor, "HEAD"], cwd=REPO_ROOT).returncode == 0


# ================================================================ §3 依存表（source から導出）

def _snapshot_field_to_channel() -> dict:
    """runner の source: snapshot field ← `observations.<channel>` の対応（keyword 引数の値に現れる属性）。"""
    tree = ast.parse((PACKAGE_DIR / "monitoring_runner.py").read_text(encoding="utf-8"))
    mapping = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg:
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == "observations":
                    mapping[node.arg] = sub.attr
    return mapping


def _guarded_emits(fields: dict) -> dict:
    """engine の source: `if` / `for` の条件で snapshot の観測 field を読んでいる分岐の中の `emit("<condition_id>")`。"""
    tree = ast.parse((PACKAGE_DIR / "monitoring_engine.py").read_text(encoding="utf-8"))
    found: dict = {}

    def reads(node) -> set:
        return {s.attr for s in ast.walk(node) if isinstance(s, ast.Attribute) and isinstance(s.value, ast.Name)
                and s.value.id == "snapshot" and s.attr in fields}

    def walk(statements, guards: frozenset) -> None:
        for stmt in statements:
            if isinstance(stmt, ast.If):
                walk(stmt.body, guards | reads(stmt.test))
                walk(stmt.orelse, guards)
            elif isinstance(stmt, ast.For):
                walk(stmt.body, guards | reads(stmt.iter))
            else:
                for call in ast.walk(stmt):
                    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "emit"
                            and call.args and isinstance(call.args[0], ast.Constant)):
                        for field_name in guards:
                            found.setdefault(fields[field_name], set()).add(call.args[0].value)

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            walk(node.body, frozenset())
    return found


def test_10_the_dependency_map_derived_from_source_equals_the_directive() -> None:
    fields = _snapshot_field_to_channel()
    assert set(fields.values()) == set(CHANNELS)
    derived = _guarded_emits(fields)
    assert {name: frozenset(ids) for name, ids in derived.items()} == DIRECTIVE_MAP


def test_11_the_map_the_engine_enforces_equals_the_derived_map() -> None:
    derived = _guarded_emits(_snapshot_field_to_channel())
    assert {name: set(ids) for name, ids in OBSERVATION_CHANNEL_CONDITIONS.items()} == derived
    assert DEPENDENTS <= set(CONDITION_REGISTRY) and len(CONDITION_REGISTRY) == 18


def test_12_arrived_keys_elsewhere_only_decorate_supporting_refs() -> None:
    """到着 key は contradiction / invalidation の `supporting_refs` にも入るが、発火条件ではない。"""
    tree = ast.parse((PACKAGE_DIR / "monitoring_engine.py").read_text(encoding="utf-8"))
    theme = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_theme")
    decorated = set()
    for call in ast.walk(theme):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "emit":
            if any(k.arg == "supporting_refs" for k in call.keywords):
                decorated.add(call.args[0].value)
    assert decorated == {"THEME_CONTRADICTION_EVIDENCE_PRESENT", "THEME_INVALIDATION_EVIDENCE_PRESENT"}
    assert not decorated & DEPENDENTS


# ================================================================ §4 blind spot — engine 経路（adapter / runner を通さない）

ENGINE_CUTOFF = datetime(2026, 10, 1, tzinfo=UTC)
P_HIT = "thprop_" + "1" * 24
P_EFFECT = "thprop_" + "2" * 24
OBS_REVISION = "thobs_" + "3" * 24
CALLER_DIGESTS = (("engine_fixture", "p6b6r1_rerun"),)


def engine_input(case: dict, *, leak: bool = False) -> MonitoringEvaluationInput:
    """case の状態から snapshot を手で組む。`leak=True` は未供給 channel の値を snapshot に紛れ込ませる。"""
    def value(channel: str, filled, blank):
        return filled if case[channel] == NONEMPTY or (leak and case[channel] == OMITTED) else blank

    themes = (ThemeSnapshot(theme_root_id=ROOT_A, governance_state="RETIRED",
                            arrived_attachment_keys=value("arrived_attachment_keys",
                                                          ("fact:rerun:engine:1", "fact:rerun:engine:2"), ())),
              ThemeSnapshot(theme_root_id=ROOT_B, governance_state="ACCEPTED",
                            semantic_revision_observation_id=value("semantic_revision_observation_ids",
                                                                   OBS_REVISION, "")))
    created = ENGINE_CUTOFF - timedelta(days=5)
    proposals = (ProposalSnapshot(proposal_id=P_HIT, proposal_status="REJECTED", created_at=created,
                                  discovery_outcome_token=value("discovery_outcome_tokens", "NO_ACCEPTED_PROPOSAL", "")),
                 ProposalSnapshot(proposal_id=P_EFFECT, proposal_status="ACCEPTED", created_at=created,
                                  discovery_outcome_token=value("discovery_outcome_tokens", "NO_OBSERVED_EFFECT", "")))
    return MonitoringEvaluationInput(cutoff=ENGINE_CUTOFF, input_digests=CALLER_DIGESTS, themes=themes,
                                     proposals=proposals,
                                     supplied_observation_channels=tuple(n for n in CHANNELS if case[n] != OMITTED))


def engine_eval(case: dict, **kw):
    return evaluate_monitoring(engine_input(case, **kw), ruleset=RULES, recorded_at=ENGINE_CUTOFF)


@pytest.mark.parametrize("label", sorted(CASES))
def test_20_engine_path_status_unevaluated_diagnostics_and_findings(label: str) -> None:
    case = CASES[label]
    evaluation = engine_eval(case)
    report = evaluation.report
    missing = omitted(case)
    assert report.status is (MonitoringRunStatus.PARTIAL if missing else MonitoringRunStatus.COMPLETE)
    assert set(report.unevaluated_conditions) == expected_unevaluated(case)                 # 過不足なし
    assert not_supplied_codes(report.diagnostics) == missing
    supplied = sorted(set(CHANNELS) - missing)
    assert dict(report.input_digests)[PRESENCE_KEY] == ("|".join(supplied) or "none")
    fired = {finding.condition_id for finding in evaluation.findings}
    for channel, dependents in DIRECTIVE_MAP.items():
        if case[channel] == NONEMPTY:
            assert dependents <= fired, (label, channel)
        else:
            assert not dependents & fired, (label, channel)


def test_21_engine_path_binds_presence_so_omitted_and_empty_never_collide() -> None:
    """engine は供給状況（presence）を束縛する。内容の束縛は adapter の input digest の責務である。"""
    run_ids = {label: engine_eval(case).report.run_id for label, case in CASES.items()}
    assert run_ids["A_all_supplied_empty"] != run_ids["C_all_omitted"]
    presence_groups = {}
    for label, case in CASES.items():
        presence_groups.setdefault(frozenset(omitted(case)), set()).add(run_ids[label])
    assert all(len(ids) == 1 for ids in presence_groups.values())
    assert len(set(run_ids.values())) == len(presence_groups) == 5                          # A と B だけが同 presence


@pytest.mark.parametrize("label", ["C_all_omitted", "D_only_arrived_omitted", "E_only_semantic_revision_omitted",
                                   "F_only_discovery_omitted"])
def test_22_engine_withholds_dependents_even_when_values_leak_into_snapshots(label: str) -> None:
    case = CASES[label]
    leaked, clean = engine_eval(case, leak=True), engine_eval(case)
    assert not {f.condition_id for f in leaked.findings} & expected_unevaluated(case)
    assert canonical_monitoring_line(leaked.report) == canonical_monitoring_line(clean.report)


def test_23_engine_default_is_not_supplied_and_complete_needs_every_requested_channel() -> None:
    default = MonitoringEvaluationInput(cutoff=ENGINE_CUTOFF, input_digests=CALLER_DIGESTS,
                                        themes=engine_input(CASES["A_all_supplied_empty"]).themes)
    report = evaluate_monitoring(default, ruleset=RULES, recorded_at=ENGINE_CUTOFF).report
    assert report.status is MonitoringRunStatus.PARTIAL and set(report.unevaluated_conditions) == set(DEPENDENTS)
    for label, case in CASES.items():
        report = engine_eval(case).report
        assert (report.status is MonitoringRunStatus.COMPLETE) == (report.unevaluated_conditions == ()), label


# ================================================================ runner 経路の world（B6R1 matrix とは別）

def _seed(root: Path) -> dict:
    """代表 world を `retired` stage で止め、B6R1 の world と重ならない提案・relation を足す。"""
    world = build_world(root, stop_after="retired")
    for cls in (ProposalStore, ThemeRelationStore, RelationProposalStore, MonitoringReviewStore):
        cls.initialize(root)
    relations = ThemeRelationStore.open(root)
    withdrawn = causal(ROOT_B, ROOT_A, at=day(2))
    relations.append_assertion(withdrawn)
    relations.append_event(retraction(withdrawn, at=day(4)))
    proposals = ProposalStore.open(root)
    hit = evidence_candidate(created_at=day(2), reason="rerun discovery hit candidate")
    effect = evidence_candidate(created_at=day(3), reason="rerun accepted candidate without an observed effect")
    for candidate in (hit, effect):
        proposals.append_proposal(candidate)
    proposals.append_decision(decision(effect.proposal_id, DecisionKind.ACCEPT, at=day(4)))
    renewed = relation_candidate(ROOT_B, ROOT_A, relation_type=RelationType.CAUSES, at=day(6),
                                 rationale="rerun renewed causal candidate")
    RelationProposalStore.open(root).append_proposal(renewed)
    return {"hit": hit.proposal_id, "effect": effect.proposal_id, "revision": world.ids["A.obs4"],
            "renewed": renewed}


@pytest.fixture(scope="module")
def rerun_world(tmp_path_factory):
    root = tmp_path_factory.mktemp("coverage_rerun") / "data"
    return root, _seed(root)


@pytest.fixture()
def copied(rerun_world, tmp_path: Path) -> Path:
    target = tmp_path / "rerun_copy" / "data"
    shutil.copytree(rerun_world[0], target)
    return target


def channel_values(ids: dict) -> dict:
    return {"arrived_attachment_keys": {ROOT_A: ("fact:rerun:arrived:2", "fact:rerun:arrived:1")},
            "semantic_revision_observation_ids": {ROOT_A: ids["revision"]},
            "discovery_outcome_tokens": {ids["hit"]: "NO_ACCEPTED_PROPOSAL", ids["effect"]: "NO_OBSERVED_EFFECT"}}


def observations_for(case: dict, ids: dict) -> MonitoringObservations:
    values = channel_values(ids)
    return MonitoringObservations(**{name: (values[name] if state == NONEMPTY else {})
                                     for name, state in case.items() if state != OMITTED})


def monitor(root: Path, cutoff: datetime, observations=None, **kw):
    kw.setdefault("root_ids", SCOPE)
    if observations is not None:
        kw["observations"] = observations
    return run_monitoring(data_root=root, cutoff=cutoff, recorded_at=cutoff, ruleset=RULES,
                          lifecycle_policy=POLICY, **kw)


#: 各 cutoff で到達し得る依存 condition（CA: ROOT_A ACCEPTED、CR: ROOT_A RETIRED）
REACHABLE = {"CA": DEPENDENTS - {"RETIRED_ROOT_RECEIVED_EVIDENCE"},
             "CR": DEPENDENTS - {"ACCEPTED_THEME_SEMANTIC_REVISION"}}
CUTOFFS = {"CA": CA, "CR": CR}


def report_bytes(result) -> str:
    return canonical_monitoring_line(result.report)


def finding_bytes(result) -> tuple:
    return tuple(canonical_monitoring_line(finding) for finding in result.findings)


# ================================================================ §4 blind spot — runner 経路

@pytest.mark.parametrize("at", sorted(CUTOFFS))
@pytest.mark.parametrize("label", sorted(CASES))
def test_30_runner_path_blind_spot_matrix(rerun_world, label: str, at: str) -> None:
    root, ids = rerun_world
    case = CASES[label]
    result = monitor(root, CUTOFFS[at], observations_for(case, ids))
    report, missing = result.report, omitted(case)
    assert report.status is (MonitoringRunStatus.PARTIAL if missing else MonitoringRunStatus.COMPLETE)
    assert set(report.unevaluated_conditions) == expected_unevaluated(case)
    assert not_supplied_codes(report.diagnostics) == missing
    digests = dict(report.input_digests)
    supplied = set(CHANNELS) - missing
    assert digests[PRESENCE_KEY] == ("|".join(sorted(supplied)) or "none")
    assert {key.split(":", 1)[1] for key in digests if key.startswith("observation:")} == supplied
    fired = {finding.condition_id for finding in result.findings}
    expected = set().union(*(DIRECTIVE_MAP[n] for n in CHANNELS if case[n] == NONEMPTY)) & REACHABLE[at]
    assert fired & DEPENDENTS == expected
    baseline = monitor(root, CUTOFFS[at], observations_for(CASES["A_all_supplied_empty"], ids))
    assert ({f.finding_id for f in result.findings if f.condition_id not in DEPENDENTS}
            == {f.finding_id for f in baseline.findings})                                  # 他の finding は動かない


@pytest.mark.parametrize("at", sorted(CUTOFFS))
def test_31_runner_path_every_coverage_case_is_a_distinct_run(rerun_world, at: str) -> None:
    root, ids = rerun_world
    results = {label: monitor(root, CUTOFFS[at], observations_for(case, ids)) for label, case in CASES.items()}
    assert len({r.report.run_id for r in results.values()}) == len(CASES)
    assert len({r.report.input_digests for r in results.values()}) == len(CASES)
    assert len({report_bytes(r) for r in results.values()}) == len(CASES)


def test_32_the_b6_def_1_scenario_is_closed_on_this_world(rerun_world) -> None:
    """B6-DEF-1 の再現条件（channel を渡さない既定 run）で、report はもう COMPLETE を名乗らない。"""
    root, _ = rerun_world
    for cutoff in CUTOFFS.values():
        report = monitor(root, cutoff).report
        assert report.status is MonitoringRunStatus.PARTIAL
        assert set(report.unevaluated_conditions) == set(DEPENDENTS)
        assert not_supplied_codes(report.diagnostics) == set(CHANNELS)


# ================================================================ §5 report 単体で判別できる

def coverage_from_report_line(line: str) -> dict:
    """report の canonical 1 行だけから coverage を読む（runner の結果も runner diagnostics も使わない）。"""
    payload = json.loads(line)
    digests = payload["input_digests"]
    supplied = set() if digests[PRESENCE_KEY] == "none" else set(digests[PRESENCE_KEY].split("|"))
    return {"complete": payload["status"] == "COMPLETE",
            "unevaluated": set(payload["unevaluated_conditions"]),
            "not_supplied": set(CHANNELS) - supplied,
            "diagnosed": not_supplied_codes(payload["diagnostics"]),
            "content_bound": {key.split(":", 1)[1] for key in digests if key.startswith("observation:")}}


@pytest.mark.parametrize("label", sorted(CASES))
def test_40_the_report_alone_reveals_incompleteness_and_what_was_not_evaluated(rerun_world, label: str) -> None:
    root, ids = rerun_world
    case = CASES[label]
    line = report_bytes(monitor(root, CR, observations_for(case, ids)))
    restored = MonitoringRunReport.from_dict(json.loads(line))                      # 永続形からの復元でも同じ
    assert canonical_monitoring_line(restored) == line
    view = coverage_from_report_line(line)
    assert view["complete"] is (not omitted(case))
    assert view["unevaluated"] == expected_unevaluated(case)
    assert view["not_supplied"] == view["diagnosed"] == omitted(case)
    assert view["content_bound"] == set(CHANNELS) - omitted(case)


def test_41_dropping_runner_diagnostics_loses_nothing_about_coverage(rerun_world) -> None:
    root, ids = rerun_world
    for label, case in CASES.items():
        result = monitor(root, CR, observations_for(case, ids))
        stripped = dataclasses.replace(result, diagnostics=())
        assert coverage_from_report_line(report_bytes(stripped)) == coverage_from_report_line(report_bytes(result))
        runner_view = not_supplied_codes(result.diagnostics)
        assert coverage_from_report_line(report_bytes(stripped))["not_supplied"] == runner_view, label


# ================================================================ §6 identity / digest

@pytest.mark.parametrize("channel", CHANNELS)
def test_50_not_supplied_empty_and_nonempty_are_three_distinct_runs(rerun_world, channel: str) -> None:
    root, ids = rerun_world
    results = {}
    for state in (OMITTED, EMPTY, NONEMPTY):
        case = {**CASES["A_all_supplied_empty"], channel: state}
        results[state] = monitor(root, CR, observations_for(case, ids))
    assert len({r.report.run_id for r in results.values()}) == 3
    assert len({r.report.input_digests for r in results.values()}) == 3
    assert len({report_bytes(r) for r in results.values()}) == 3
    bound = {state: dict(r.report.input_digests).get(f"observation:{channel}") for state, r in results.items()}
    assert bound[OMITTED] is None and bound[EMPTY] and bound[NONEMPTY] and bound[EMPTY] != bound[NONEMPTY]


@pytest.mark.parametrize("label", ["A_all_supplied_empty", "B_all_supplied_nonempty", "C_all_omitted"])
def test_51_the_same_semantic_input_replays_byte_for_byte(rerun_world, label: str) -> None:
    root, ids = rerun_world
    first = monitor(root, CR, observations_for(CASES[label], ids))
    second = monitor(root, CR, observations_for(CASES[label], dict(ids)))               # 別に組み立てた同一入力
    assert report_bytes(first) == report_bytes(second) and finding_bytes(first) == finding_bytes(second)
    assert first.report.run_id == second.report.run_id


def test_52_physical_order_location_and_duplicates_do_not_change_the_run(rerun_world, copied: Path) -> None:
    root, ids = rerun_world
    forward = channel_values(ids)
    backward = {name: dict(reversed(list(values.items()))) for name, values in forward.items()}
    backward["arrived_attachment_keys"] = {ROOT_A: ("fact:rerun:arrived:1", "fact:rerun:arrived:2",
                                                    "fact:rerun:arrived:1")}
    reference = monitor(root, CR, MonitoringObservations(**forward))
    for other_root, values in ((root, backward), (copied, forward), (copied, backward)):
        other = monitor(other_root, CR, MonitoringObservations(**values), root_ids=tuple(reversed(SCOPE)))
        assert report_bytes(other) == report_bytes(reference)
        assert finding_bytes(other) == finding_bytes(reference)


# ================================================================ §7 finding 非回帰（B6 freeze の runtime と比べる）

FROZEN_SCRIPT = r'''
import dataclasses, json, sys
from datetime import datetime, timezone
from pathlib import Path
import src.intelligence.theme_intelligence.monitoring_engine as engine
from src.intelligence.theme_intelligence.lifecycle_model import default_lifecycle_policy
from src.intelligence.theme_intelligence.monitoring_adapter import MonitoringObservations
from src.intelligence.theme_intelligence.monitoring_model import canonical_monitoring_line
from src.intelligence.theme_intelligence.monitoring_rules import load_monitoring_rules_version, monitoring_rules_path
from src.intelligence.theme_intelligence.monitoring_runner import run_monitoring
args = json.loads(sys.argv[1])
utc = timezone.utc
rules = dataclasses.replace(
    load_monitoring_rules_version(monitoring_rules_path(Path(args["knowledge"]), "0.1.0"), expected_version="0.1.0",
                                  cutoff=datetime(2026, 9, 30, tzinfo=utc)),
    published_at=datetime(2026, 8, 1, tzinfo=utc))
out = {"engine_file": engine.__file__, "has_coverage_map": hasattr(engine, "OBSERVATION_CHANNEL_CONDITIONS")}
for label, spec in args["runs"].items():
    moment = datetime.fromisoformat(spec["cutoff"])
    channels = {name: {key: tuple(value) if isinstance(value, list) else value for key, value in values.items()}
                for name, values in spec["observations"].items()}
    result = run_monitoring(data_root=Path(args["data_root"]), cutoff=moment, recorded_at=moment, ruleset=rules,
                            root_ids=tuple(args["scope"]), lifecycle_policy=default_lifecycle_policy(),
                            observations=MonitoringObservations(**channels))
    out[label] = {"findings": [canonical_monitoring_line(f) for f in result.findings],
                  "finding_ids": list(result.report.finding_ids), "status": result.report.status.value,
                  "unevaluated": list(result.report.unevaluated_conditions)}
print(json.dumps(out))
'''


@pytest.fixture(scope="module")
def frozen_runtime(tmp_path_factory) -> Path:
    """B6 freeze（B6R1 前）の `src/` を git から一時展開する（作業木には触れない）。"""
    target = tmp_path_factory.mktemp("b6_freeze_runtime")
    with tarfile.open(fileobj=io.BytesIO(git("archive", B6_FREEZE, "src", text=False))) as archive:
        if hasattr(tarfile, "data_filter"):
            archive.extractall(target, filter="data")
        else:                                                                   # pragma: no cover
            archive.extractall(target)
    return target


@pytest.fixture(scope="module")
def frozen_results(frozen_runtime: Path, rerun_world) -> dict:
    root, ids = rerun_world
    runs = {}
    for at, cutoff in CUTOFFS.items():
        for label in ("A_all_supplied_empty", "B_all_supplied_nonempty", "C_all_omitted"):
            case = CASES[label]
            values = channel_values(ids)
            channels = {name: ({key: list(v) if isinstance(v, tuple) else v for key, v in values[name].items()}
                               if state == NONEMPTY else {}) for name, state in case.items() if state != OMITTED}
            runs[f"{at}:{label}"] = {"cutoff": cutoff.isoformat(), "observations": channels}
    before = {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update({"PYTHONPATH": str(frozen_runtime), "PYTHONDONTWRITEBYTECODE": "1"})
    payload = json.dumps({"knowledge": str(KNOWLEDGE_ROOT), "data_root": str(root), "scope": list(SCOPE),
                          "runs": runs})
    done = subprocess.run([sys.executable, "-c", FROZEN_SCRIPT, payload], cwd=frozen_runtime, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
    after = {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    assert after == before                                                       # B6 freeze の runtime も書かない
    return json.loads(done.stdout)


def test_60_the_comparison_really_ran_the_pre_b6r1_runtime(frozen_results: dict, frozen_runtime: Path) -> None:
    assert Path(frozen_results["engine_file"]).resolve().is_relative_to(frozen_runtime.resolve())
    assert frozen_results["has_coverage_map"] is False


@pytest.mark.parametrize("at", sorted(CUTOFFS))
def test_61_fully_supplied_input_gives_byte_identical_findings_before_and_after_b6r1(
        rerun_world, frozen_results: dict, at: str) -> None:
    root, ids = rerun_world
    now = monitor(root, CUTOFFS[at], observations_for(CASES["B_all_supplied_nonempty"], ids))
    then = frozen_results[f"{at}:B_all_supplied_nonempty"]
    assert list(finding_bytes(now)) == then["findings"]
    assert list(now.report.finding_ids) == then["finding_ids"]
    assert now.report.status.value == then["status"] == "COMPLETE"


@pytest.mark.parametrize("at", sorted(CUTOFFS))
def test_62_supplied_empty_input_gives_byte_identical_findings_before_and_after_b6r1(
        rerun_world, frozen_results: dict, at: str) -> None:
    root, ids = rerun_world
    now = monitor(root, CUTOFFS[at], observations_for(CASES["A_all_supplied_empty"], ids))
    assert list(finding_bytes(now)) == frozen_results[f"{at}:A_all_supplied_empty"]["findings"]


@pytest.mark.parametrize("at", sorted(CUTOFFS))
def test_63_the_original_defect_reproduces_on_the_old_runtime_and_is_closed_on_the_new(
        rerun_world, frozen_results: dict, at: str) -> None:
    """同じ data root・同じ cutoff で、B6 freeze は未供給でも COMPLETE（B6-DEF-1）、B6R1 は PARTIAL。"""
    root, _ = rerun_world
    then = frozen_results[f"{at}:C_all_omitted"]
    assert then["status"] == "COMPLETE" and then["unevaluated"] == []                 # 独立に再現した欠陥
    now = monitor(root, CUTOFFS[at])
    assert now.report.status is MonitoringRunStatus.PARTIAL
    assert set(now.report.unevaluated_conditions) == set(DEPENDENTS)
    assert list(finding_bytes(now)) == then["findings"]                               # finding は同じ（未評価が増えただけ）


def test_64_coverage_metadata_never_enters_a_finding(rerun_world) -> None:
    root, ids = rerun_world
    for label, case in CASES.items():
        for finding in monitor(root, CA, observations_for(case, ids)).findings:
            line = canonical_monitoring_line(finding)
            assert PRESENCE_KEY not in line and NOT_SUPPLIED_PREFIX not in line and "observation:" not in line, label


def test_65_supporting_arrival_refs_change_bytes_but_never_identity(rerun_world) -> None:
    """CA では ROOT_A の contradiction finding に到着 key が supporting_refs として付く。identity は変わらない。"""
    root, ids = rerun_world
    empty = {f.condition_id: f for f in monitor(root, CA, observations_for(CASES["A_all_supplied_empty"], ids)).findings}
    full = {f.condition_id: f for f in monitor(root, CA, observations_for(CASES["B_all_supplied_nonempty"], ids)).findings}
    target = "THEME_CONTRADICTION_EVIDENCE_PRESENT"
    assert empty[target].finding_id == full[target].finding_id
    assert canonical_monitoring_line(empty[target]) != canonical_monitoring_line(full[target])


# ================================================================ §8 condition / ruleset 非回帰

def _top_level(source: str) -> dict:
    out = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(target, ast.Name):
                    out[target.id] = node
    return out


def _engine_versions():
    path = "src/intelligence/theme_intelligence/monitoring_engine.py"
    return _top_level(git("show", f"{B6_FREEZE}:{path}")), _top_level((REPO_ROOT / path).read_text(encoding="utf-8"))


def test_70_every_condition_evaluating_function_is_unchanged_since_the_b6_freeze() -> None:
    old, new = _engine_versions()
    changed = {name for name in old.keys() & new.keys() if ast.dump(old[name]) != ast.dump(new[name])}
    assert changed == {"MonitoringEvaluationInput", "_Collector", "evaluate_monitoring", "__all__"}
    assert set(new) - set(old) == {"OBSERVATION_CHANNEL_CONDITIONS", "OBSERVATION_PRESENCE_KEY", "NO_CHANNEL_SUPPLIED"}
    assert set(old) - set(new) == set()
    for name in ("_theme", "_proposal", "_relation", "_relation_proposal", "_knowledge_drift", "_authority_failure",
                 "ThemeSnapshot", "ProposalSnapshot", "RelationSnapshot", "RelationProposalSnapshot",
                 "AuthorityFailureSnapshot", "ACCEPTED_STATES", "CLOSED_STATES", "ABSENCE_FLAGS", "DIVERGENCE_FLAGS"):
        assert ast.dump(old[name]) == ast.dump(new[name]), name


def test_71_the_collector_only_gained_a_withheld_set_and_one_leading_guard() -> None:
    old, new = _engine_versions()
    methods = lambda cls: {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}   # noqa: E731
    before, after = methods(old["_Collector"]), methods(new["_Collector"])
    assert set(before) == set(after)
    for name in set(before) - {"emit"}:
        assert ast.dump(before[name]) == ast.dump(after[name]), name
    guard, *rest = after["emit"].body
    assert [ast.dump(s) for s in rest] == [ast.dump(s) for s in before["emit"].body]
    assert isinstance(guard, ast.If) and "withheld" in ast.dump(guard.test)
    assert [type(s) for s in guard.body] == [ast.Return]
    fields = lambda cls: [n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)]  # noqa: E731
    assert fields(new["_Collector"]) == fields(old["_Collector"]) + ["withheld"]
    assert fields(new["MonitoringEvaluationInput"]) == fields(old["MonitoringEvaluationInput"]) + [
        "supplied_observation_channels"]


def test_72_the_ruleset_still_holds_eighteen_conditions_with_the_frozen_vocabulary() -> None:
    frozen = git("show", f"{B6_FREEZE}:{RULESET_PATH}", text=False)
    assert (REPO_ROOT / RULESET_PATH).read_bytes() == frozen
    assert len(RULES.rules) == len(CONDITION_REGISTRY) == 18
    assert {rule.condition_id for rule in RULES.rules} == set(CONDITION_REGISTRY)


# ================================================================ §9 PIT（coverage を固定して比べる）

def pit_signature(result) -> tuple:
    report = result.report
    return (report.run_id, report.input_digests, report.status, report.unevaluated_conditions,
            finding_bytes(result), report.diagnostics)


def _pit_observations(ids: dict, coverage: str, extra_hit: str = ""):
    if coverage == OMITTED:
        return None
    values = channel_values(ids)
    if extra_hit:
        values["discovery_outcome_tokens"] = {**values["discovery_outcome_tokens"], extra_hit: "NO_ACCEPTED_PROPOSAL"}
    return MonitoringObservations(**values)


@pytest.mark.parametrize("coverage", [NONEMPTY, OMITTED])
def test_80_b3_future_proposal_does_not_alter_a_past_run(copied: Path, rerun_world, coverage: str) -> None:
    _, ids = rerun_world
    future = evidence_candidate(created_at=day(20), reason="rerun candidate recorded after the cutoff")
    seen = _pit_observations(ids, coverage, extra_hit=future.proposal_id)          # 同じ観測を前後で渡す
    before = pit_signature(monitor(copied, CR, seen))
    ProposalStore.open(copied).append_proposal(future)
    assert pit_signature(monitor(copied, CR, seen)) == before
    later = monitor(copied, day(25), seen)
    assert dict(later.report.input_digests)["theme_proposals"] != dict(before[1])["theme_proposals"]
    if coverage == NONEMPTY:                                                        # fixture が生きていること
        assert any(f.subject_ref == future.proposal_id for f in later.findings)


@pytest.mark.parametrize("coverage", [NONEMPTY, OMITTED])
def test_81_b3_future_decision_does_not_alter_a_past_run(copied: Path, rerun_world, coverage: str) -> None:
    _, ids = rerun_world
    seen = _pit_observations(ids, coverage)
    before = pit_signature(monitor(copied, CR, seen))
    ProposalStore.open(copied).append_decision(decision(ids["hit"], DecisionKind.DEFER, at=day(20)))
    assert pit_signature(monitor(copied, CR, seen)) == before
    later = monitor(copied, day(51), seen)                                          # deferred 30 日を越える
    assert any(f.condition_id == "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD" and f.subject_ref == ids["hit"]
               for f in later.findings)


@pytest.mark.parametrize("coverage", [NONEMPTY, OMITTED])
def test_82_b5c_future_relation_proposal_does_not_alter_a_past_run(copied: Path, rerun_world, coverage: str) -> None:
    _, ids = rerun_world
    seen = _pit_observations(ids, coverage)
    before = pit_signature(monitor(copied, CR, seen))
    future = relation_candidate(ROOT_B, ROOT_A, relation_type=RelationType.CAUSES, at=day(20),
                                rationale="rerun relation candidate recorded after the cutoff")
    RelationProposalStore.open(copied).append_proposal(future)
    assert pit_signature(monitor(copied, CR, seen)) == before
    later = monitor(copied, day(25), seen)
    assert any(f.condition_id == "RETRACTED_RELATION_HAS_NEW_PROPOSAL"
               and dict(f.salient_state.facts).get("relation_proposal_id") == future.proposal_id
               for f in later.findings)


@pytest.mark.parametrize("coverage", [NONEMPTY, OMITTED])
def test_83_b5c_future_relation_decision_does_not_alter_a_past_run(copied: Path, rerun_world, coverage: str) -> None:
    _, ids = rerun_world
    seen = _pit_observations(ids, coverage)
    renewed = ids["renewed"].proposal_id

    def conflicted(result) -> bool:
        return any(f.condition_id == "RETRACTED_RELATION_HAS_NEW_PROPOSAL"
                   and dict(f.salient_state.facts).get("relation_proposal_id") == renewed for f in result.findings)

    first = monitor(copied, CR, seen)
    assert conflicted(first)
    before = pit_signature(first)
    RelationProposalStore.open(copied).append_decision(decide(ids["renewed"], RelationDecisionKind.REJECT,
                                                              at=day(20)))
    assert pit_signature(monitor(copied, CR, seen)) == before
    assert not conflicted(monitor(copied, day(25), seen))                            # 決定は cutoff 後に効く


# ================================================================ §10 corruption / fail closed ＋ 未供給

def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _append(path: Path, raw: bytes) -> None:
    path.write_bytes(path.read_bytes() + raw)


def corrupt(root: Path, kind: str, ids: dict) -> Path:
    """B3 提案 journal（一部は決定 / B5C / Foundation journal）を 1 か所だけ壊す。修復はしない。"""
    proposals = proposal_paths(root)["proposals"]
    first = proposals.read_bytes().splitlines()[0]
    payload = json.loads(first)
    if kind == "malformed":
        _append(proposals, b"{not json}\n")
    elif kind == "truncated":
        _append(proposals, first[: len(first) // 2])
    elif kind == "blank":
        _append(proposals, b"\n")
    elif kind == "non_object":
        _append(proposals, b'"a bare string"\n')
    elif kind == "non_canonical":
        _append(proposals, json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
    elif kind == "unsupported_schema":
        _append(proposals, _canonical({**payload, "schema_version": "theme_proposal:9.9.9"}))
    elif kind == "unknown_field":
        _append(proposals, _canonical({**payload, "unexpected_field": "x"}))
    elif kind == "conflicting_duplicate":
        _append(proposals, _canonical({**payload, "reason": "a different body under the same identifier"}))
    elif kind == "invalid_history":
        _append(proposal_paths(root)["decisions"], canonical_proposal_line(
            decision(ids["hit"], DecisionKind.DEFER, at=day(5), supersedes="thdec_" + "9" * 24)).encode("utf-8"))
    elif kind == "invalid_timestamp":
        text = proposals.read_text(encoding="utf-8")
        proposals.write_text(text.replace('"created_at":"', '"created_at":"not-a-time', 1), encoding="utf-8")
    elif kind == "relation_proposal_invalid_history":
        _append(relation_proposal_paths(root)["decisions"], canonical_proposal_record_line(
            decide(ids["renewed"], RelationDecisionKind.DEFER, at=day(7), supersedes="threldec_" + "9" * 24)
        ).encode("utf-8"))
    elif kind == "theme_journal_malformed":
        _append(theme_paths(root)["observations"], b"{not json}\n")
    else:                                                                           # pragma: no cover
        raise AssertionError(kind)
    return proposals


CORRUPTIONS = ("malformed", "truncated", "blank", "non_object", "non_canonical", "unsupported_schema",
               "unknown_field", "conflicting_duplicate", "invalid_history", "invalid_timestamp",
               "relation_proposal_invalid_history", "theme_journal_malformed")


def _journal_bytes(root: Path) -> dict:
    paths = [*theme_paths(root).values(), *proposal_paths(root).values(), *relation_proposal_paths(root).values()]
    return {str(p): p.read_bytes() for p in paths if p.exists()}


@pytest.mark.parametrize("missing", ["arrived_attachment_keys", "discovery_outcome_tokens"])
@pytest.mark.parametrize("kind", CORRUPTIONS)
def test_90_corruption_and_a_missing_channel_are_both_kept(copied: Path, rerun_world, kind: str,
                                                           missing: str) -> None:
    _, ids = rerun_world
    supplied_all = MonitoringObservations(**channel_values(ids))
    lacking = MonitoringObservations(**{k: v for k, v in channel_values(ids).items() if k != missing})
    corrupt(copied, kind, ids)
    damaged = _journal_bytes(copied)
    authority_only = monitor(copied, CR, supplied_all).report
    both = monitor(copied, CR, lacking)
    assert authority_only.status is MonitoringRunStatus.PARTIAL and authority_only.unevaluated_conditions  # 黙らない
    assert not_supplied_codes(authority_only.diagnostics) == set()
    assert both.report.status is MonitoringRunStatus.PARTIAL
    assert set(both.report.unevaluated_conditions) == (set(authority_only.unevaluated_conditions)
                                                       | DIRECTIVE_MAP[missing])     # どちらの理由も失われない
    assert set(both.report.diagnostics) == set(authority_only.diagnostics) | {NOT_SUPPLIED_PREFIX + missing}
    assert "AUTHORITY_STATE_UNUSABLE" in {f.condition_id for f in both.findings}
    assert _journal_bytes(copied) == damaged                                       # 自動修復しない


# ================================================================ §11 zero-write

def inventory(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_100_no_coverage_case_writes_anything(copied: Path, rerun_world) -> None:
    _, ids = rerun_world
    before = inventory(copied)
    for case in CASES.values():
        for cutoff in CUTOFFS.values():
            monitor(copied, cutoff, observations_for(case, ids))
    monitor(copied, CR)
    after = inventory(copied)
    assert set(after) - set(before) == set()                                      # new 0（finding / report を保存しない）
    assert set(before) - set(after) == set()                                      # deleted 0
    assert {k for k in before if before[k] != after[k]} == set()                  # modified 0（review append 0）


WRITE_CALLS = {"write_text", "write_bytes", "mkdir", "unlink", "rename", "touch", "rmdir", "initialize",
               "append_review_state", "append_proposal", "append_decision", "append_assertion", "append_event",
               "append_observation", "append_governance", "append_mapping", "append_metadata"}


@pytest.mark.parametrize("name", B6R1_MODULES)
def test_101_the_remediated_modules_reach_no_write_or_authority_api(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / name).read_text(encoding="utf-8"))
    for call in ast.walk(tree):
        if isinstance(call, ast.Call):
            if isinstance(call.func, ast.Name):
                assert call.func.id != "open", name                                 # builtin open を使わない
            attr = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
            assert attr not in WRITE_CALLS, (name, attr)


# ================================================================ §12 review 分離

def test_110_existing_review_state_never_changes_the_coverage_verdict(copied: Path, rerun_world) -> None:
    _, ids = rerun_world
    runs = {label: monitor(copied, CR, observations_for(case, ids)) for label, case in CASES.items()}
    targets = {f.finding_id for f in runs["B_all_supplied_nonempty"].findings}
    store = MonitoringReviewStore.open(copied)
    for finding_id, disposition in zip(sorted(targets), [ReviewDisposition.ACKNOWLEDGED, ReviewDisposition.DISMISSED,
                                                         ReviewDisposition.DEFERRED] * 4):
        store.append_review_state(ReviewItemState.build(finding_id=finding_id, disposition=disposition,
                                                        actor_ref="reviewer:r7", recorded_at=day(11)))
    for label, case in CASES.items():
        again = monitor(copied, CR, observations_for(case, ids))
        assert report_bytes(again) == report_bytes(runs[label]), label           # review は report に入らない
        assert again.report.status is runs[label].report.status


def test_111_a_missing_channel_creates_no_review_state(copied: Path, rerun_world) -> None:
    before = review_state_path(copied).read_bytes()
    for case in CASES.values():
        monitor(copied, CR, observations_for(case, rerun_world[1]))
    monitor(copied, CR)
    assert review_state_path(copied).read_bytes() == before


@pytest.mark.parametrize("name", B6R1_MODULES)
def test_112_the_remediated_modules_do_not_speak_the_review_vocabulary(name: str) -> None:
    source = (PACKAGE_DIR / name).read_text(encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
    if name != "monitoring_runner.py":                                          # runner の review 参照は B6D の read-only lookup
        assert not names & {"ReviewDisposition", "ReviewItemState", "MonitoringReviewStore"}, name
    code = executable_source(PACKAGE_DIR / name)                               # docstring の説明文は除く
    for token in ("ACKNOWLEDGED", "DISMISSED", "append_review_state"):
        assert token not in code, (name, token)


# ================================================================ §13 authority / RR-3（B6R1 が持ち込んだ能力）

def _imports(source: str) -> set:
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            out |= {f"{node.module}:{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Import):
            out |= {alias.name for alias in node.names}
    return out


def _calls(source: str) -> set:
    return {(c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "?"))
            for c in ast.walk(ast.parse(source)) if isinstance(c, ast.Call)}


def test_120_b6r1_added_no_import_and_no_capability_beyond_coverage_bookkeeping() -> None:
    added_imports, added_calls = set(), set()
    for name in B6R1_MODULES:
        path = f"src/intelligence/theme_intelligence/{name}"
        old, new = git("show", f"{B6_FREEZE}:{path}"), (REPO_ROOT / path).read_text(encoding="utf-8")
        added_imports |= _imports(new) - _imports(old)
        added_calls |= _calls(new) - _calls(old)
    assert added_imports == {"monitoring_engine:OBSERVATION_CHANNEL_CONDITIONS"}
    assert added_calls == {"all", "any", "join", "update", "getattr", "MonitoringObservations",
                           "_canonical_channel", "channel_bindings"}


def test_121_rr3_policy_lock_monitoring_never_executes_relation_or_governance_actions() -> None:
    for name in B6R1_MODULES:
        source = (PACKAGE_DIR / name).read_text(encoding="utf-8")
        calls = _calls(source)
        assert not calls & {"append_assertion", "append_event", "append_governance", "append_decision",
                            "append_proposal", "execute", "apply", "plan_merge", "plan_split"}, name
        assert "RelationDecisionKind" not in source and "DecisionKind." not in source, name


# ================================================================ §14 default run

def test_130_the_default_run_is_intentionally_partial_and_supply_removes_it(rerun_world) -> None:
    root, ids = rerun_world
    for cutoff in CUTOFFS.values():
        default = monitor(root, cutoff)
        explicit = monitor(root, cutoff, MonitoringObservations())
        assert report_bytes(default) == report_bytes(explicit)                     # 既定 = 明示的な全未供給
        assert default.report.status is MonitoringRunStatus.PARTIAL
        assert set(default.report.unevaluated_conditions) == set(DEPENDENTS)
        for label in ("A_all_supplied_empty", "B_all_supplied_nonempty"):
            supplied = monitor(root, cutoff, observations_for(CASES[label], ids)).report
            assert supplied.status is MonitoringRunStatus.COMPLETE and supplied.unevaluated_conditions == ()
    assert build_evaluation_input(cutoff=CR).supplied_observation_channels == ()


# ================================================================ §15 synthetic shadow harness

#: harness は knowledge の ruleset（published_at 2026-09-23）をそのまま読むため、公開後の cutoff を使う
HARNESS_CUTOFF = datetime(2026, 9, 30, tzinfo=UTC)

def test_140_the_harness_default_run_is_partial_zero_write_and_replayable(copied: Path) -> None:
    from tests.intelligence.theme_monitoring_shadow import main
    out = copied.parent / "rerun_summary.json"
    assert main(["--data-root", str(copied), "--cutoff", HARNESS_CUTOFF.isoformat(), "--out", str(out)]) == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["wrote_nothing"] is True and summary["replay_identical"] is True
    assert summary["run"]["status"] == "PARTIAL"
    assert set(summary["run"]["unevaluated_conditions"]) == set(DEPENDENTS)          # この world では channel 由来のみ
    assert sorted(summary["run"]["observation_channels_not_supplied"]) == list(CHANNELS)


def _harness_run(root: Path, observations: MonitoringObservations) -> dict:
    """harness の inventory / describe / replay 判定をそのまま使い、観測を供給して 2 回実行する。"""
    from tests.intelligence.theme_monitoring_shadow import describe, inventory as harness_inventory
    from tests.intelligence.theme_monitoring_shadow import inventory_delta, replay_delta
    before = harness_inventory(root)
    first, second = (describe(monitor(root, HARNESS_CUTOFF, observations)) for _ in range(2))
    delta = inventory_delta(before, harness_inventory(root))
    return {"wrote_nothing": not any(delta.values()), "replay_identical": replay_delta(first, second) == [],
            "run": first}


def test_141_supplying_every_channel_clears_the_coverage_partial(copied: Path, rerun_world) -> None:
    summary = _harness_run(copied, MonitoringObservations(**channel_values(rerun_world[1])))
    assert summary["wrote_nothing"] is True and summary["replay_identical"] is True
    assert summary["run"]["status"] == "COMPLETE" and summary["run"]["unevaluated_conditions"] == []
    assert not any(code.startswith(NOT_SUPPLIED_PREFIX) for code in summary["run"]["report_diagnostics"])


def test_142_an_authority_reason_keeps_partial_without_a_coverage_reason(copied: Path, rerun_world) -> None:
    corrupt(copied, "relation_proposal_invalid_history", rerun_world[1])
    summary = _harness_run(copied, MonitoringObservations(**channel_values(rerun_world[1])))
    assert summary["wrote_nothing"] is True and summary["replay_identical"] is True
    assert summary["run"]["status"] == "PARTIAL"
    assert summary["run"]["unevaluated_conditions"] == ["RETRACTED_RELATION_HAS_NEW_PROPOSAL"]
    assert not any(code.startswith(NOT_SUPPLIED_PREFIX) for code in summary["run"]["report_diagnostics"])


# ================================================================ §19 履歴の保持

def test_150_the_closeout_history_is_kept_and_only_the_deadline_was_corrected() -> None:
    old = git("show", f"{B6_FREEZE}:{AUDIT_DOC}").splitlines()
    new = (REPO_ROOT / AUDIT_DOC).read_text(encoding="utf-8").splitlines()
    kept = set(new)
    for line in old:
        if line in kept:
            continue
        assert "BEFORE P7 ENTRY" in line or any(candidate.startswith(line) for candidate in new), line
    text = "\n".join(new)
    assert "NON_BLOCKING_FOR_B6_CLOSEOUT / MANDATORY_PRE_B7_REMEDIATION" in text
    assert "**BEFORE B7 ENTRY**" in text and "時点では **deferred**" in text and "**CLOSED**（P6-B6R1）" in text
    paragraphs = text.split("\n\n")
    assert all("表記ミス" in paragraph for paragraph in paragraphs if "BEFORE P7 ENTRY" in paragraph)


def test_151_the_b6_closeout_changelog_entry_is_untouched() -> None:
    def section(text: str) -> str:
        start = text.index("## v5.31 ")
        return text[start:text.index("\n## v5.30 ", start)]
    assert section((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")) == section(
        git("show", f"{B6_FREEZE}:CHANGELOG.md"))
