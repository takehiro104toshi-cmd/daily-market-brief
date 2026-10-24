"""P6-B6R1 — 観測 channel の coverage-completeness（B6-DEF-1 の remediation）の回帰 matrix。

契約:

- channel は 3 状態を持つ: 未供給（`None`、既定）/ 空で供給（`{}`）/ 非空で供給。
- 未供給の channel に依存する condition は未評価になり、run は `COMPLETE` にならない（B6B の COMPLETE 定義を保持）。
- 未供給は report 単体（status・unevaluated_conditions・diagnostics・input digest）で判別できる。
- 未供給は finding ではない。review state を作らない。authority を変えない。finding identity を変えない。

データはすべて synthetic。書き込みは `tmp_path` のみ。
"""
from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.monitoring_adapter import (OBSERVATION_BINDING_PREFIX, OBSERVATION_CHANNELS,
                                                                    MonitoringAdapterError, MonitoringObservations,
                                                                    build_evaluation_input)
from src.intelligence.theme_intelligence.monitoring_engine import (NO_CHANNEL_SUPPLIED,
                                                                   OBSERVATION_CHANNEL_CONDITIONS,
                                                                   OBSERVATION_PRESENCE_KEY, MonitoringEngineError,
                                                                   MonitoringEvaluationInput, ProposalSnapshot,
                                                                   ThemeSnapshot, evaluate_monitoring)
from src.intelligence.theme_intelligence.monitoring_model import MonitoringRunStatus, canonical_monitoring_line
from src.intelligence.theme_intelligence.monitoring_rules import CONDITION_REGISTRY
from src.intelligence.theme_intelligence.monitoring_store import review_state_path
from src.intelligence.theme_intelligence.proposal_store import ProposalStore
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.proposal_model import DecisionKind
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B, ROOT_C
from tests.intelligence.test_theme_monitoring_e2e import (ARRIVED, RULES, STALE_POLICY, _seed_world, journal_digests,
                                                          run)
from tests.intelligence.test_theme_proposal import decision, evidence_candidate
from tests.intelligence.theme_foundation_fixtures import day

CUTOFF = day(70)
#: 依存表（frozen engine の `_theme` / `_proposal` が読む snapshot field から導いたもの。docs §2 と 1:1）
EXPECTED_DEPENDENCIES = {
    "arrived_attachment_keys": ("RETIRED_ROOT_RECEIVED_EVIDENCE",),
    "semantic_revision_observation_ids": ("ACCEPTED_THEME_SEMANTIC_REVISION",),
    "discovery_outcome_tokens": ("DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL",
                                 "ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT"),
}
DEPENDENT = frozenset(c for group in EXPECTED_DEPENDENCIES.values() for c in group)
EMPTY = {name: {} for name in OBSERVATION_CHANNELS}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("monitoring_coverage") / "data"
    return root, _seed_world(root)


@pytest.fixture()
def copied(world, tmp_path: Path) -> Path:
    target = tmp_path / "coverage" / "data"
    shutil.copytree(world[0], target)
    return target


def nonempty(ids: dict) -> dict:
    return {"arrived_attachment_keys": {ROOT_A: (ARRIVED,)},
            "semantic_revision_observation_ids": {ROOT_C: ids["revision"]},
            "discovery_outcome_tokens": {ids["open"]: "NO_ACCEPTED_PROPOSAL", ids["deferred"]: "NO_OBSERVED_EFFECT"}}


def monitor(root: Path, channels=None, **kw):
    observations = None if channels is None else MonitoringObservations(**channels)
    return run(root, cutoff=CUTOFF, policy=STALE_POLICY, observations=observations, **kw)


def report_line(result) -> str:
    return canonical_monitoring_line(result.report)


def signature(result) -> tuple:
    return (report_line(result), tuple(canonical_monitoring_line(f) for f in result.findings), result.diagnostics)


def not_supplied_codes(codes) -> list:
    return sorted(code.split(":", 1)[1] for code in codes if code.startswith("OBSERVATION_NOT_SUPPLIED:"))


# ---------------------------------------------------------------- 依存表と既定値

def test_00_the_dependency_map_is_exact_and_matches_the_observation_fields() -> None:
    assert dict(OBSERVATION_CHANNEL_CONDITIONS) == EXPECTED_DEPENDENCIES
    assert set(OBSERVATION_CHANNELS) == {f.name for f in dataclasses.fields(MonitoringObservations)}
    assert DEPENDENT <= set(CONDITION_REGISTRY) and len(DEPENDENT) == 4


def test_00b_every_layer_defaults_to_not_supplied() -> None:
    """coverage を主張する隠れた既定値は無い（既定はどの層でも「未供給」）。"""
    assert MonitoringObservations().missing_channels() == OBSERVATION_CHANNELS
    assert MonitoringEvaluationInput(cutoff=CUTOFF).supplied_observation_channels == ()
    assert build_evaluation_input(cutoff=CUTOFF).supplied_observation_channels == ()
    evaluation = evaluate_monitoring(MonitoringEvaluationInput(cutoff=CUTOFF), ruleset=RULES, recorded_at=CUTOFF)
    assert evaluation.report.status is MonitoringRunStatus.PARTIAL
    assert set(evaluation.report.unevaluated_conditions) == DEPENDENT


# ---------------------------------------------------------------- A〜F: status と未評価

def test_a_all_supplied_empty_is_complete(world) -> None:
    result = monitor(world[0], EMPTY)
    assert result.report.status is MonitoringRunStatus.COMPLETE and result.report.unevaluated_conditions == ()
    assert not_supplied_codes(result.report.diagnostics) == []


def test_b_all_supplied_nonempty_is_complete(world) -> None:
    root, ids = world
    result = monitor(root, nonempty(ids))
    assert result.report.status is MonitoringRunStatus.COMPLETE and result.report.unevaluated_conditions == ()
    assert DEPENDENT <= {f.condition_id for f in result.findings}          # 依存 condition は実際に評価された


def test_c_all_omitted_is_partial_with_every_dependent_unevaluated(world) -> None:
    result = monitor(world[0])
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert set(result.report.unevaluated_conditions) == DEPENDENT
    assert not_supplied_codes(result.report.diagnostics) == sorted(OBSERVATION_CHANNELS)


@pytest.mark.parametrize("label,channel", [("D_arrived", "arrived_attachment_keys"),
                                           ("E_semantic_revision", "semantic_revision_observation_ids"),
                                           ("F_discovery", "discovery_outcome_tokens")])
def test_def_one_omitted_channel_marks_only_its_dependents(world, label: str, channel: str) -> None:
    root, ids = world
    supplied = {k: v for k, v in nonempty(ids).items() if k != channel}
    result = monitor(root, supplied)
    assert result.report.status is MonitoringRunStatus.PARTIAL, label
    assert set(result.report.unevaluated_conditions) == set(EXPECTED_DEPENDENCIES[channel])
    assert not_supplied_codes(result.report.diagnostics) == [channel]
    assert not set(EXPECTED_DEPENDENCIES[channel]) & {f.condition_id for f in result.findings}


# ---------------------------------------------------------------- G〜I: 未供給 ≠ 空供給（report 単体で）

def test_g_omitted_and_supplied_empty_give_different_canonical_reports(world) -> None:
    assert report_line(monitor(world[0])) != report_line(monitor(world[0], EMPTY))


def test_h_omitted_and_supplied_empty_give_different_run_ids(world) -> None:
    assert monitor(world[0]).report.run_id != monitor(world[0], EMPTY).report.run_id


def test_i_omitted_and_supplied_empty_are_bound_differently(world) -> None:
    omitted = dict(monitor(world[0]).report.input_digests)
    empty = dict(monitor(world[0], EMPTY).report.input_digests)
    assert omitted[OBSERVATION_PRESENCE_KEY] == NO_CHANNEL_SUPPLIED
    assert empty[OBSERVATION_PRESENCE_KEY] == "|".join(sorted(OBSERVATION_CHANNELS))
    for name in OBSERVATION_CHANNELS:
        assert OBSERVATION_BINDING_PREFIX + name not in omitted
        assert empty[OBSERVATION_BINDING_PREFIX + name].startswith("thmin_")


def test_i2_empty_and_nonempty_supply_are_bound_differently(world) -> None:
    root, ids = world
    empty = dict(monitor(root, EMPTY).report.input_digests)
    full = dict(monitor(root, nonempty(ids)).report.input_digests)
    for name in OBSERVATION_CHANNELS:
        assert empty[OBSERVATION_BINDING_PREFIX + name] != full[OBSERVATION_BINDING_PREFIX + name]


# ---------------------------------------------------------------- J〜L: 決定論

def test_j_the_same_omitted_input_replays_identically(world) -> None:
    assert signature(monitor(world[0])) == signature(monitor(world[0]))


def test_k_the_same_supplied_empty_input_replays_identically(world) -> None:
    assert signature(monitor(world[0], EMPTY)) == signature(monitor(world[0], EMPTY))


def test_l_the_physical_order_of_a_channel_does_not_matter(world) -> None:
    root, ids = world
    forward = nonempty(ids)
    forward["arrived_attachment_keys"] = {ROOT_A: ("fact:arrived:one", "fact:arrived:two"), ROOT_B: ("fact:arrived:x",)}
    backward = {name: dict(reversed(list(values.items()))) for name, values in forward.items()}
    backward["arrived_attachment_keys"] = {ROOT_B: ("fact:arrived:x",), ROOT_A: ("fact:arrived:two", "fact:arrived:one")}
    assert signature(monitor(root, forward)) == signature(monitor(root, backward))


# ---------------------------------------------------------------- M: 未供給 ＋ authority の失敗

@pytest.mark.parametrize("missing", ["arrived_attachment_keys", "discovery_outcome_tokens"])
def test_m_a_missing_channel_and_an_authority_failure_are_both_kept(copied: Path, world, missing: str) -> None:
    _, ids = world
    path = proposal_paths(copied)["proposals"]
    path.write_bytes(path.read_bytes() + b"{not json}\n")
    supplied = {k: v for k, v in nonempty(ids).items() if k != missing}
    result = monitor(copied, supplied)
    unevaluated = set(result.report.unevaluated_conditions)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert set(EXPECTED_DEPENDENCIES[missing]) <= unevaluated                      # channel 由来
    assert "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD" in unevaluated                   # authority 由来
    assert len(result.report.unevaluated_conditions) == len(unevaluated)           # 重複なし
    assert list(result.report.unevaluated_conditions) == sorted(unevaluated)       # canonical order
    assert not_supplied_codes(result.report.diagnostics) == [missing]
    assert any(code.startswith("AUTHORITY_UNUSABLE:") for code in result.report.diagnostics)


# ---------------------------------------------------------------- N〜P: finding / review / authority を作らない

def test_n_a_missing_channel_creates_no_finding(world) -> None:
    omitted = monitor(world[0])
    empty = monitor(world[0], EMPTY)
    assert [canonical_monitoring_line(f) for f in omitted.findings] == [canonical_monitoring_line(f)
                                                                        for f in empty.findings]
    assert "AUTHORITY_STATE_UNUSABLE" not in {f.condition_id for f in omitted.findings}


def test_n2_a_withheld_condition_is_not_evaluated_even_if_a_value_leaks_in() -> None:
    """未供給と宣言された channel の値が snapshot に紛れても、依存 condition は評価しない（多重防御）。"""
    leaked = MonitoringEvaluationInput(
        cutoff=CUTOFF, supplied_observation_channels=("arrived_attachment_keys", "semantic_revision_observation_ids"),
        proposals=(ProposalSnapshot(proposal_id="thprop_" + "a" * 24, proposal_status="REJECTED",
                                    discovery_outcome_token="NO_ACCEPTED_PROPOSAL"),))
    evaluation = evaluate_monitoring(leaked, ruleset=RULES, recorded_at=CUTOFF)
    assert "DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL" not in {f.condition_id for f in evaluation.findings}
    assert "DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL" in evaluation.report.unevaluated_conditions


def test_o_a_missing_channel_creates_no_review_state(copied: Path) -> None:
    before = review_state_path(copied).read_bytes()
    monitor(copied)
    assert review_state_path(copied).read_bytes() == before


def test_p_a_missing_channel_mutates_no_authority(copied: Path) -> None:
    before = journal_digests(copied)
    inventory = {str(p.relative_to(copied)): p.read_bytes() for p in sorted(copied.rglob("*")) if p.is_file()}
    monitor(copied)
    monitor(copied, EMPTY)
    assert journal_digests(copied) == before
    assert {str(p.relative_to(copied)): p.read_bytes() for p in sorted(copied.rglob("*")) if p.is_file()} == inventory


# ---------------------------------------------------------------- Q: finding identity は不変

def test_q_findings_that_do_not_need_a_channel_are_byte_identical(world) -> None:
    root, ids = world
    found = {label: [f for f in monitor(root, channels).findings if f.condition_id not in DEPENDENT]
             for label, channels in (("omitted", None), ("empty", EMPTY), ("nonempty", nonempty(ids)))}
    lines = {label: {canonical_monitoring_line(f) for f in group} for label, group in found.items()}
    assert lines["omitted"] == lines["empty"] and lines["omitted"]
    # 非空供給では arrived key が contradiction finding の supporting_refs に入る（identity には入らない）
    identities = {label: {f.finding_id for f in group} for label, group in found.items()}
    assert identities["omitted"] == identities["empty"] == identities["nonempty"]


def test_q2_a_dependent_finding_id_does_not_depend_on_other_channels(world) -> None:
    root, ids = world
    full = nonempty(ids)
    only_discovery = {"discovery_outcome_tokens": full["discovery_outcome_tokens"]}
    both = {f.finding_id for f in monitor(root, full).findings if f.condition_id.startswith("DISCOVERY")}
    alone = {f.finding_id for f in monitor(root, only_discovery).findings if f.condition_id.startswith("DISCOVERY")}
    assert both == alone and both


def test_q3_findings_carry_no_coverage_metadata(world) -> None:
    for finding in monitor(world[0]).findings:
        line = canonical_monitoring_line(finding)
        assert OBSERVATION_PRESENCE_KEY not in line and "OBSERVATION_NOT_SUPPLIED" not in line


# ---------------------------------------------------------------- R: PIT 回帰

def test_r_future_records_still_do_not_alter_a_past_run(copied: Path, world) -> None:
    _, ids = world
    before = signature(monitor(copied, EMPTY))
    store = ProposalStore.open(copied)
    future = evidence_candidate(created_at=day(80), reason="a candidate recorded after the coverage cutoff")
    store.append_proposal(future)
    store.append_decision(decision(ids["open"], DecisionKind.ACCEPT, at=day(81)))
    assert signature(monitor(copied, EMPTY)) == before


# ---------------------------------------------------------------- 入力検証 / 要求された condition だけ

@pytest.mark.parametrize("channels", [("price_feed",), (["arrived_attachment_keys"],), (None,)])
def test_v1_an_unknown_channel_is_rejected(channels) -> None:
    with pytest.raises(MonitoringEngineError) as exc:
        MonitoringEvaluationInput(cutoff=CUTOFF, supplied_observation_channels=channels)
    assert exc.value.code == "INVALID_OBSERVATION_CHANNEL"


def test_v2_the_presence_binding_cannot_be_supplied_by_the_caller() -> None:
    with pytest.raises(MonitoringEngineError) as exc:
        MonitoringEvaluationInput(cutoff=CUTOFF, input_digests=((OBSERVATION_PRESENCE_KEY, "all"),))
    assert exc.value.code == "RESERVED_DIGEST_KEY"


@pytest.mark.parametrize("value", [[], "keys", 3, ("a",)])
def test_v3_a_channel_is_none_or_a_mapping(value) -> None:
    with pytest.raises(MonitoringAdapterError) as exc:
        MonitoringObservations(discovery_outcome_tokens=value)
    assert exc.value.code == "INVALID_TYPE"


def test_v4_only_requested_conditions_make_a_missing_channel_matter() -> None:
    """ruleset が依存 condition を要求していなければ、その channel の欠落は coverage を欠かない（test 内の ruleset 変種）。"""
    off = dataclasses.replace(RULES, rules=tuple(dataclasses.replace(rule, enabled=False)
                                                 if rule.condition_id in DEPENDENT else rule for rule in RULES.rules))
    evaluation = evaluate_monitoring(MonitoringEvaluationInput(cutoff=CUTOFF), ruleset=off, recorded_at=CUTOFF)
    assert evaluation.report.status is MonitoringRunStatus.COMPLETE
    assert not_supplied_codes(evaluation.report.diagnostics) == []


def test_v5_complete_never_carries_an_unevaluated_condition(world) -> None:
    root, ids = world
    for channels in (None, EMPTY, nonempty(ids), {"arrived_attachment_keys": {}}):
        report = monitor(root, channels).report
        assert (report.status is MonitoringRunStatus.COMPLETE) == (report.unevaluated_conditions == ())


# ---------------------------------------------------------------- report 単体で足りる / shadow

def test_w1_the_report_alone_exposes_the_gap_without_runner_diagnostics(world) -> None:
    payload = json.loads(report_line(monitor(world[0])))
    assert payload["status"] == "PARTIAL"
    assert set(payload["unevaluated_conditions"]) == DEPENDENT
    assert not_supplied_codes(payload["diagnostics"]) == sorted(OBSERVATION_CHANNELS)
    assert payload["input_digests"][OBSERVATION_PRESENCE_KEY] == NO_CHANNEL_SUPPLIED


def test_w2_the_shadow_harness_reports_the_default_run_as_partial(copied: Path) -> None:
    from tests.intelligence.theme_monitoring_shadow import main
    out = copied.parent / "summary.json"
    assert main(["--data-root", str(copied), "--cutoff", "2026-11-10T00:00:00+00:00", "--out", str(out)]) == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["run"]["status"] == "PARTIAL" and summary["wrote_nothing"] is True
    assert sorted(summary["run"]["observation_channels_not_supplied"]) == sorted(OBSERVATION_CHANNELS)
    assert set(summary["run"]["unevaluated_conditions"]) >= DEPENDENT
