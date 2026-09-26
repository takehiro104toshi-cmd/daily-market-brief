"""P6-B6D-R1 — monitoring runner の point-in-time 回帰 matrix（B6E BLOCKER-1 の remediation）。

契約（cutoff = C）:

- 提案は `created_at <= C` のものだけが見える。決定は `recorded_at <= C` のものだけが見える。
- 時刻 = C は可視、C + 1µs は不可視、C − 1µs は可視。
- 濾過は **解決の前**に行う（canonical record → PIT 可視集合 → 既存 B3 / B5C resolver）。
- C より未来の record を足しても、C の run の input digest / run_id / finding / diagnostics は変わらない。
- 時刻が PIT 判定に使えない record は読み飛ばさず、authority の失敗（PARTIAL）にする。

データはすべて synthetic。書き込みは `tmp_path` のみ。
"""
from __future__ import annotations

import dataclasses
import hashlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence import monitoring_runner as R
from src.intelligence.theme_intelligence.lifecycle_model import default_lifecycle_policy
from src.intelligence.theme_intelligence.monitoring_adapter import MonitoringObservations
from src.intelligence.theme_intelligence.monitoring_model import MonitoringRunStatus, canonical_monitoring_line
from src.intelligence.theme_intelligence.monitoring_rules import load_monitoring_rules_version, monitoring_rules_path
from src.intelligence.theme_intelligence.monitoring_runner import MonitoringRunnerError, run_monitoring
from src.intelligence.theme_intelligence.monitoring_store import MonitoringReviewStore, review_state_path
from src.intelligence.theme_intelligence.proposal_model import DecisionKind, canonical_proposal_line
from src.intelligence.theme_intelligence.proposal_store import ProposalStore
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.relation_model import AssertionClass, RelationType
from src.intelligence.theme_intelligence.relation_proposal_model import RelationDecisionKind
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as relation_proposal_paths
from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
from src.intelligence.theme_intelligence.relation_store import authority_paths as relation_paths
from src.intelligence.themes.store import authority_paths as theme_paths
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B, ROOT_C
from tests.intelligence.test_theme_proposal import decision, evidence_candidate
from tests.intelligence.test_theme_relation import causal, retraction, sourced
from tests.intelligence.test_theme_relation_proposal import decide
from tests.intelligence.test_theme_relation_proposal import proposal as relation_candidate
from tests.intelligence.theme_foundation_fixtures import CHECKPOINTS, build_world, day

UTC = timezone.utc
US = timedelta(microseconds=1)
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "src" / "intelligence" / "theme_intelligence" / "monitoring_runner.py"
POLICY = default_lifecycle_policy()
SCOPE = (ROOT_A, ROOT_B, ROOT_C)
RULES = dataclasses.replace(
    load_monitoring_rules_version(monitoring_rules_path(REPO_ROOT / "knowledge", "0.1.0"), expected_version="0.1.0",
                                  cutoff=datetime(2026, 9, 30, tzinfo=UTC)),
    published_at=datetime(2026, 8, 1, tzinfo=UTC))                 # 内容は同一。world の timeline で使えるよう前倒し
#: B3 側の基準時刻（提案 day(1)、C = day(70) で open 60 日 / deferred 30 日の aging が観測できる）
PROPOSED_AT = day(1)
C3 = day(70)
#: B5C 側の基準時刻（撤回済み edge B→A CAUSES は day(6) 撤回、C = day(10)）
C5 = day(10)
OPEN_AGING = "THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD"
DEFERRED_AGING = "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD"
DISCOVERY = "DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL"
CHAIN = "PROPOSAL_DECISION_CHAIN_UNRESOLVED"
CONFLICT = "RETRACTED_RELATION_HAS_NEW_PROPOSAL"


# ---------------------------------------------------------------- fixture

@pytest.fixture(scope="module")
def base(tmp_path_factory) -> Path:
    """代表 world ＋ B5B（A→B SOURCE_ASSERTED を day(5)、B→A CAUSES を day(3) 主張・day(6) 撤回）。"""
    root = tmp_path_factory.mktemp("monitoring_pit") / "data"
    build_world(root)
    for cls in (ProposalStore, ThemeRelationStore, RelationProposalStore, MonitoringReviewStore):
        cls.initialize(root)
    relations = ThemeRelationStore.open(root)
    relations.append_assertion(sourced(ROOT_A, ROOT_B, at=day(5)))
    retracted = causal(ROOT_B, ROOT_A, at=day(3))
    relations.append_assertion(retracted)
    relations.append_event(retraction(retracted, at=day(6)))
    return root


@pytest.fixture()
def root(base: Path, tmp_path: Path) -> Path:
    target = tmp_path / "pit" / "data"
    shutil.copytree(base, target)
    return target


def run(data_root: Path, cutoff: datetime, **kw):
    kw.setdefault("root_ids", SCOPE)
    return run_monitoring(data_root=data_root, cutoff=cutoff, recorded_at=cutoff, lifecycle_policy=POLICY,
                          ruleset=RULES, **kw)


def fired(result) -> set:
    return {finding.condition_id for finding in result.findings}


def for_subject(result, condition_id: str, key: str, value: str) -> list:
    return [f for f in result.findings
            if f.condition_id == condition_id and dict(f.salient_state.facts).get(key) == value]


def signature(result) -> tuple:
    """過去 run の同一性を比べる観測点（identity・入力 digest・finding bytes・diagnostics・status）。"""
    return (result.report.run_id, result.report.input_digests, result.report.status,
            tuple(canonical_monitoring_line(f) for f in result.findings), result.report.diagnostics,
            result.diagnostics)


def theme_proposal(data_root: Path, created_at: datetime, reason: str):
    candidate = evidence_candidate(created_at=created_at, reason=reason.replace("_", " ").casefold())
    ProposalStore.open(data_root).append_proposal(candidate)
    return candidate


def discovered(candidate) -> MonitoringObservations:
    """提案の可視性を status に依らず観測するための channel（outcome token は status を問わず finding になる）。"""
    return MonitoringObservations(discovery_outcome_tokens={candidate.proposal_id: "NO_ACCEPTED_PROPOSAL"})


def relation_proposal(data_root: Path, created_at: datetime, rationale: str):
    candidate = relation_candidate(ROOT_B, ROOT_A, relation_type=RelationType.CAUSES, at=created_at,
                                   rationale=rationale.replace("_", " ").casefold())
    RelationProposalStore.open(data_root).append_proposal(candidate)
    return candidate


def journal_hashes(data_root: Path) -> dict:
    paths = dict(theme_paths(data_root))
    paths.update({f"p:{k}": v for k, v in proposal_paths(data_root).items()})
    paths.update({f"r:{k}": v for k, v in relation_paths(data_root).items()})
    paths.update({f"rp:{k}": v for k, v in relation_proposal_paths(data_root).items()})
    paths["review"] = review_state_path(data_root)
    return {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}


# ---------------------------------------------------------------- A〜C: B3 提案の可視性

@pytest.mark.parametrize("label,offset,visible", [("A_at_cutoff", timedelta(0), True),
                                                  ("B_cutoff_plus_1us", US, False),
                                                  ("C_cutoff_minus_1us", -US, True)])
def test_b3_proposal_visibility_boundary(root: Path, label: str, offset: timedelta, visible: bool) -> None:
    candidate = theme_proposal(root, C3 + offset, f"boundary candidate {label}")
    result = run(root, C3, observations=discovered(candidate))
    assert bool(for_subject(result, DISCOVERY, "proposal_id", candidate.proposal_id)) is visible, label


# ---------------------------------------------------------------- D〜F: B3 決定の可視性

@pytest.mark.parametrize("label,offset,deferred_visible", [("D_at_cutoff", timedelta(0), True),
                                                           ("E_cutoff_plus_1us", US, False),
                                                           ("F_cutoff_minus_1us", -US, True)])
def test_b3_decision_visibility_boundary(root: Path, label: str, offset: timedelta, deferred_visible: bool) -> None:
    candidate = theme_proposal(root, PROPOSED_AT, f"decision boundary {label}")
    ProposalStore.open(root).append_decision(decision(candidate.proposal_id, DecisionKind.DEFER, at=C3 + offset))
    result = run(root, C3)
    deferred = for_subject(result, DEFERRED_AGING, "proposal_id", candidate.proposal_id)
    opened = for_subject(result, OPEN_AGING, "proposal_id", candidate.proposal_id)
    assert bool(deferred) is deferred_visible and bool(opened) is (not deferred_visible), label


# ---------------------------------------------------------------- G〜I: 未来の決定・未来の提案・過去 run の不変

def test_b3_g_a_future_accept_does_not_reach_back(root: Path) -> None:
    """proposal day(1) ／ ACCEPT day(80) ／ cutoff day(70) → day(70) は ACCEPT を知らない（OPEN のまま）。"""
    candidate = theme_proposal(root, PROPOSED_AT, "visible candidate with a future accept")
    ProposalStore.open(root).append_decision(decision(candidate.proposal_id, DecisionKind.ACCEPT, at=day(80)))
    assert for_subject(run(root, C3), OPEN_AGING, "proposal_id", candidate.proposal_id)
    assert not for_subject(run(root, day(90)), OPEN_AGING, "proposal_id", candidate.proposal_id)


def test_b3_h_a_future_proposal_and_its_decision_do_not_exist(root: Path) -> None:
    candidate = theme_proposal(root, day(80), "future candidate")
    ProposalStore.open(root).append_decision(decision(candidate.proposal_id, DecisionKind.DEFER, at=day(85)))
    result = run(root, C3, observations=discovered(candidate))
    assert not [f for f in result.findings if candidate.proposal_id in canonical_monitoring_line(f)]
    assert "theme_proposals" not in dict(result.report.input_digests)       # 可視な提案が無い＝family 自体が無い


def test_b3_i_future_records_do_not_alter_a_past_run(root: Path) -> None:
    visible = theme_proposal(root, PROPOSED_AT, "the only candidate known at the cutoff")
    observed = MonitoringObservations(discovery_outcome_tokens={visible.proposal_id: "NO_ACCEPTED_PROPOSAL"})
    before = signature(run(root, C3, observations=observed))
    future = theme_proposal(root, day(80), "a candidate recorded after the cutoff")
    store = ProposalStore.open(root)
    store.append_decision(decision(future.proposal_id, DecisionKind.DEFER, at=day(81)))
    store.append_decision(decision(visible.proposal_id, DecisionKind.ACCEPT, at=day(82)))
    assert signature(run(root, C3, observations=observed)) == before
    assert signature(run(root, day(90), observations=observed)) != before   # cutoff を進めれば変わってよい


# ---------------------------------------------------------------- J〜L: B5C 提案の可視性

@pytest.mark.parametrize("label,offset,visible", [("J_at_cutoff", timedelta(0), True),
                                                  ("K_cutoff_plus_1us", US, False),
                                                  ("L_cutoff_minus_1us", -US, True)])
def test_b5c_proposal_visibility_boundary(root: Path, label: str, offset: timedelta, visible: bool) -> None:
    candidate = relation_proposal(root, C5 + offset, f"boundary relation candidate {label}")
    result = run(root, C5)
    assert bool(for_subject(result, CONFLICT, "relation_proposal_id", candidate.proposal_id)) is visible, label


# ---------------------------------------------------------------- M〜O: B5C 決定の可視性

@pytest.mark.parametrize("label,offset,decided", [("M_at_cutoff", timedelta(0), True),
                                                  ("N_cutoff_plus_1us", US, False),
                                                  ("O_cutoff_minus_1us", -US, True)])
def test_b5c_decision_visibility_boundary(root: Path, label: str, offset: timedelta, decided: bool) -> None:
    """可視な REJECT は提案を閉じる（衝突は消える）。不可視なら提案は open のまま衝突が出る。"""
    candidate = relation_proposal(root, day(7), f"decision boundary relation candidate {label}")
    RelationProposalStore.open(root).append_decision(decide(candidate, RelationDecisionKind.REJECT, at=C5 + offset))
    conflicts = for_subject(run(root, C5), CONFLICT, "relation_proposal_id", candidate.proposal_id)
    assert bool(conflicts) is (not decided), label


# ---------------------------------------------------------------- P〜R: 未来の決定・未来の提案・過去 run の不変

@pytest.mark.parametrize("kind", [RelationDecisionKind.ACCEPT, RelationDecisionKind.REJECT,
                                  RelationDecisionKind.DEFER])
def test_b5c_p_a_future_decision_does_not_reach_back(root: Path, kind: RelationDecisionKind) -> None:
    candidate = relation_proposal(root, day(7), f"visible relation candidate with a future {kind.value}")
    before = signature(run(root, C5))
    RelationProposalStore.open(root).append_decision(decide(candidate, kind, accepted=AssertionClass.HUMAN_ASSERTED,
                                                            at=day(20)))
    after = run(root, C5)
    assert for_subject(after, CONFLICT, "relation_proposal_id", candidate.proposal_id)   # day(10) では open
    assert signature(after) == before
    closed = bool(for_subject(run(root, day(25)), CONFLICT, "relation_proposal_id", candidate.proposal_id))
    assert closed is (kind is RelationDecisionKind.DEFER)             # 受理 / 却下は閉じる。保留は open のまま


def test_b5c_q_a_future_relation_proposal_cannot_raise_a_conflict(root: Path) -> None:
    candidate = relation_proposal(root, day(20), "relation candidate recorded after the cutoff")
    assert not for_subject(run(root, C5), CONFLICT, "relation_proposal_id", candidate.proposal_id)
    assert for_subject(run(root, day(25)), CONFLICT, "relation_proposal_id", candidate.proposal_id)


def test_b5c_r_future_records_do_not_alter_a_past_run(root: Path) -> None:
    visible = relation_proposal(root, day(7), "the only relation candidate known at the cutoff")
    before = signature(run(root, C5))
    future = relation_proposal(root, day(20), "a relation candidate recorded after the cutoff")
    store = RelationProposalStore.open(root)
    store.append_decision(decide(future, RelationDecisionKind.DEFER, at=day(21)))
    store.append_decision(decide(visible, RelationDecisionKind.REJECT, at=day(22)))
    assert signature(run(root, C5)) == before
    assert signature(run(root, day(25))) != before


# ---------------------------------------------------------------- 解決の前に濾過する（§6）

def test_filter_happens_before_resolution_for_a_future_fork(root: Path) -> None:
    """未来の決定で初めて fork になる chain は、過去 cutoff では健全な chain として解ける。

    全 record を resolver に渡してから時刻で補正する設計では、過去 cutoff にも fork が見えてしまう。"""
    candidate = theme_proposal(root, PROPOSED_AT, "chain that only forks in the future")
    first = decision(candidate.proposal_id, DecisionKind.DEFER, at=day(3))
    second = decision(candidate.proposal_id, DecisionKind.DEFER, at=day(4), supersedes=first.decision_id,
                      reason="still waiting")
    store = ProposalStore.open(root)
    store.append_decision(first)
    store.append_decision(second)
    path = proposal_paths(root)["decisions"]
    fork = decision(candidate.proposal_id, DecisionKind.ACCEPT, at=day(80), supersedes=first.decision_id)
    path.write_bytes(path.read_bytes() + canonical_proposal_line(fork).encode("utf-8"))
    past = run(root, C3)
    assert not for_subject(past, CHAIN, "subject_token", candidate.proposal_id)
    assert for_subject(past, DEFERRED_AGING, "proposal_id", candidate.proposal_id)
    assert for_subject(run(root, day(90)), CHAIN, "subject_token", candidate.proposal_id)


def test_filter_happens_before_resolution_for_a_future_successor(root: Path) -> None:
    """未来の後継決定が終端を変える場合、過去 cutoff では後継を知らない終端で解く。"""
    candidate = theme_proposal(root, PROPOSED_AT, "chain whose successor is in the future")
    first = decision(candidate.proposal_id, DecisionKind.DEFER, at=day(3))
    store = ProposalStore.open(root)
    store.append_decision(first)
    store.append_decision(decision(candidate.proposal_id, DecisionKind.REJECT, at=day(80),
                                   supersedes=first.decision_id))
    assert for_subject(run(root, C3), DEFERRED_AGING, "proposal_id", candidate.proposal_id)
    assert not for_subject(run(root, day(90)), DEFERRED_AGING, "proposal_id", candidate.proposal_id)


# ---------------------------------------------------------------- fail closed（§9）

def test_a_malformed_line_is_never_skipped_as_future(root: Path) -> None:
    for path in (proposal_paths(root)["proposals"], relation_proposal_paths(root)["proposals"]):
        before = path.read_bytes()
        path.write_bytes(before + b'{"created_at":"2099-01-01T00:00:00+00:00"\n')
        result = run(root, C5)
        assert result.report.status is MonitoringRunStatus.PARTIAL
        assert path.read_bytes().endswith(b'"2099-01-01T00:00:00+00:00"\n')              # 修復しない
        path.write_bytes(before)


def test_an_unparseable_timestamp_fails_closed(root: Path) -> None:
    candidate = theme_proposal(root, PROPOSED_AT, "candidate whose time will be damaged")
    path = proposal_paths(root)["proposals"]
    text = path.read_text(encoding="utf-8")
    stamp = candidate.created_at.isoformat().replace("+00:00", "Z")
    damaged = text.replace(stamp, "not-a-time") if stamp in text else text.replace('"created_at":"', '"created_at":"x', 1)
    path.write_text(damaged, encoding="utf-8")
    result = run(root, C3)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    assert any(code.startswith("PROPOSAL_AUTHORITY_UNUSABLE") for code in result.diagnostics)


class _NaiveRecord:
    proposal_id = "thprop_" + "c" * 24
    created_at = datetime(2026, 9, 2)                                   # naive
    recorded_at = datetime(2026, 9, 2)


class _FakeStore:
    def proposals(self):
        return (_NaiveRecord(),)

    def decisions(self):
        return ()


@pytest.mark.parametrize("attribute", ["ProposalStore", "RelationProposalStore"])
def test_a_naive_timestamp_fails_closed_as_an_authority_failure(root: Path, monkeypatch, attribute: str) -> None:
    store = getattr(R, attribute)
    monkeypatch.setattr(store, "open", classmethod(lambda cls, *a, **k: _FakeStore()))
    result = run(root, C5)
    assert result.report.status is MonitoringRunStatus.PARTIAL
    prefix = "PROPOSAL_AUTHORITY_UNUSABLE" if attribute == "ProposalStore" else "RELATION_PROPOSAL_AUTHORITY_UNUSABLE"
    assert f"{prefix}:INVALID_RECORD_TIME" in result.diagnostics


def test_a_future_record_leaves_no_trace_in_diagnostics(root: Path) -> None:
    """未来の record を「除外した」という diagnostic も残さない（それ自体が未来の漏洩になる）。"""
    before = run(root, C5).diagnostics
    relation_proposal(root, day(30), "future relation candidate")
    theme_proposal(root, day(80), "future theme candidate")
    assert run(root, C5).diagnostics == before


# ---------------------------------------------------------------- six-family PIT matrix（§13）

def _family(data_root: Path, family: str):
    """family ごとの (record 時刻, 観測する condition, 追加の run 引数)。"""
    if family == "theme_evidence":
        return CHECKPOINTS["contradiction_added"], "THEME_CONTRADICTION_EVIDENCE_PRESENT", {"root_ids": (ROOT_A,)}
    if family == "theme_governance":
        return CHECKPOINTS["retired"], "RELATION_ENDPOINT_NOT_ACTIVE", {}
    if family == "relation_assertion":
        return day(5), "SOURCE_ASSERTED_RELATION_CONTESTED", {}
    if family == "relation_governance":
        relation_proposal(data_root, day(2), "relation candidate that predates the retraction")
        return day(6), CONFLICT, {}
    if family == "theme_proposal_decision":
        candidate = theme_proposal(data_root, PROPOSED_AT, "family matrix candidate")
        ProposalStore.open(data_root).append_decision(decision(candidate.proposal_id, DecisionKind.DEFER, at=C3))
        return C3, DEFERRED_AGING, {}
    candidate = relation_proposal(data_root, day(7), "family matrix relation candidate")
    RelationProposalStore.open(data_root).append_decision(decide(candidate, RelationDecisionKind.REJECT, at=C5))
    return C5, "NOT_" + CONFLICT, {}


@pytest.mark.parametrize("family", ["theme_evidence", "theme_governance", "theme_proposal_decision",
                                    "relation_assertion", "relation_governance", "relation_proposal_decision"])
def test_six_family_pit_boundary(root: Path, family: str) -> None:
    """record 時刻 t に対し cutoff = t − 1µs で不可視、t と t + 1µs で可視。"""
    moment, condition, kw = _family(root, family)
    negate = condition.startswith("NOT_")
    target = condition[len("NOT_"):] if negate else condition
    seen = {offset: target in fired(run(root, moment + offset, **kw)) for offset in (-US, timedelta(0), US)}
    if negate:                                                          # 決定が見えると衝突が消える family
        seen = {k: not v for k, v in seen.items()}
    assert seen == {-US: False, timedelta(0): True, US: True}, (family, seen)


# ---------------------------------------------------------------- zero-write / 境界

def test_the_pit_filter_keeps_the_run_zero_write(root: Path) -> None:
    candidate = theme_proposal(root, day(80), "future candidate for the zero-write proof")
    ProposalStore.open(root).append_decision(decision(candidate.proposal_id, DecisionKind.DEFER, at=day(81)))
    relation_proposal(root, day(20), "future relation candidate for the zero-write proof")
    inventory = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(root.rglob("*")) if p.is_file()}
    hashes = journal_hashes(root)
    for cutoff in (C5, C3, day(90)):
        run(root, cutoff)
    assert {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()} == inventory
    assert journal_hashes(root) == hashes


def test_the_filter_uses_only_the_caller_cutoff() -> None:
    source = executable_source(RUNNER)
    for token in (".now(", "utcnow", "time.time", "st_mtime", "getmtime", "today("):
        assert token not in source, token
    assert "created_at" in source and "recorded_at" in source


def test_the_runner_still_reaches_no_write_side_api() -> None:
    source = executable_source(RUNNER)
    for token in ("append_proposal", "append_decision", "append_assertion", "append_event", "append_review_state",
                  "append_governance", "execute_", "plan_relation_assertion", "bridge"):
        assert token not in source, token


def test_an_aware_cutoff_is_still_required(root: Path) -> None:
    with pytest.raises(MonitoringRunnerError) as exc:
        run_monitoring(data_root=root, cutoff=datetime(2026, 9, 10), recorded_at=datetime(2026, 9, 10),
                       root_ids=SCOPE, lifecycle_policy=POLICY, ruleset=RULES)
    assert exc.value.code == "INVALID_TIME"
