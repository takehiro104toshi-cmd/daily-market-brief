"""P6-B6D — monitoring run の orchestration（**本質的に read-only**。shadow flag を持たない）。

`run_monitoring()` は authority を読むだけで、Theme / evidence / governance / proposal / relation のいずれにも
書かない。人間の review だけが `monitoring_store.append_review_state()` という **別 API** を通る。
本 module はその API を呼ばない（test で固定する）。

runner は intelligence semantics を持たない。条件判定は B6C engine、chain semantics は各 resolver、
lifecycle semantics は B2、relation semantics は B5 が答える。ここにあるのは:

1. 明示入力の検証（data_root / cutoff / recorded_at / monitoring scope / policy / ruleset version）
2. versioned knowledge の version 固定読み込み（「latest」解決をしない）
3. authority の read-only 読み取りと cutoff 固定の PIT 解決（PIT 入口を持たない B3 / B5C は、canonical に load 済みの
   record を cutoff で濾過してから既存 resolver へ渡す。解決後に補正しない）
4. 上流 derived view → `MonitoringEvaluationInput` の写像（`monitoring_adapter`）
5. `evaluate_monitoring()` の呼び出し
6. finding ごとの現在の `ReviewItemState` の解決（`resolve_review_state`）

読めなかった authority は「条件が偽」にならない。失敗 snapshot として engine へ渡り、
`unevaluated_conditions` ＋ INTEGRITY finding ＋ run status `PARTIAL` になる。

現在時刻は使わない。`cutoff` と `recorded_at` は呼び出し側が渡す aware datetime である。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from ..core.time import ensure_aware
from ..themes.model import ThemeGovernanceEvent, is_root_id
from ..themes.resolver import resolve_at_data_root
from .lifecycle import derive_lifecycle
from .lifecycle_model import GovernanceLifecycleState, LifecyclePolicy, ThemeLifecycleError
from .monitoring_adapter import (AUTHORITY_PROPOSALS, AUTHORITY_RELATION_PROPOSALS, LIVE_RELATION_PROPOSAL_STATUSES,
                                 MonitoringObservations, RETRACTED_CONFLICT_TOKEN, authority_failure,
                                 build_evaluation_input, contested_roots, edge_prefix, excluded_relation_snapshot,
                                 freshness_policy_token, knowledge_drift_snapshot, proposal_snapshot,
                                 relation_authority_failure, relation_proposal_snapshot, relation_snapshot,
                                 retracted_edge_prefixes, theme_failure_snapshot, theme_snapshot,
                                 unresolved_relation_snapshot)
from .monitoring_engine import (PROPOSAL_CONDITIONS, RELATION_CONDITIONS, RELATION_PROPOSAL_CONDITIONS,
                                THEME_CONDITIONS, ProposalSnapshot, RelationProposalSnapshot, RelationSnapshot,
                                ThemeSnapshot, evaluate_monitoring)
from .monitoring_model import (MonitoringFinding, MonitoringRunReport, ReviewChainResolution, resolve_review_state)
from .monitoring_rules import MonitoringRuleset, load_monitoring_rules_version, monitoring_rules_path
from .monitoring_store import MonitoringReviewStore
from .proposal_resolution import derive_proposal_status, resolve_active_decision
from .proposal_store import ProposalStore
from .relation_proposal_resolution import derive_relation_proposal_status
from .relation_proposal_store import RelationProposalStore
from .relation_resolution import endpoint_lookup_from_roots
from .relation_store import resolve_relations_at_data_root

MONITORING_RUNNER_VERSION = "theme_monitoring_runner:0.1.0"
#: run は observation を返すだけで、行動を要求しない（contract / test で凍結する文言）
RUN_IS_READ_ONLY = "a monitoring run reads authorities and writes nothing"
#: knowledge version の key（使っていない knowledge を run identity へ入れない）
LIFECYCLE_POLICY_KEY = "lifecycle_policy"
#: relation authority が読めないとき評価できなくなる条件（relation 提案の衝突も含む）
RELATION_BLOCKED_CONDITIONS: Tuple[str, ...] = RELATION_CONDITIONS + RELATION_PROPOSAL_CONDITIONS
MAX_DIAGNOSTIC_LEN = 64
UNKNOWN_FAILURE = "AUTHORITY_UNUSABLE"
_CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:.-")


class MonitoringRunnerError(ValueError):
    """fail closed。detail に path / 本文 / 秘密値を入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise MonitoringRunnerError(code, detail)


def _error_code(exc: Exception) -> str:
    """例外の安定 code だけを取り出す。message（path を含み得る）は結果へ出さない。"""
    code = getattr(exc, "code", "")
    if not isinstance(code, str) or code == "" or not set(code) <= _CODE_CHARS:
        return UNKNOWN_FAILURE
    return code[:MAX_DIAGNOSTIC_LEN]


class _UnusableRecordTime(Exception):
    """PIT 判定に使えない時刻を持つ record。読み飛ばさず、その authority の失敗として扱う。"""

    code = "INVALID_RECORD_TIME"


def _visible_at(records: Sequence[object], attribute: str, cutoff: datetime) -> Tuple[object, ...]:
    """canonical に load 済みの record のうち `attribute <= cutoff` のものだけを返す（cutoff ちょうどは可視）。

    cutoff より未来の record は **存在しない** ものとして扱い、件数も diagnostics へ残さない
    （残せばそれ自体が未来の漏洩になる）。時刻が aware datetime でない record は fail closed。"""
    visible = []
    for record in records:
        moment = getattr(record, attribute, None)
        if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
            raise _UnusableRecordTime()
        if moment <= cutoff:
            visible.append(record)
    return tuple(visible)


def _by_proposal(decisions: Sequence[object]) -> Dict[str, List]:
    grouped: Dict[str, List] = {}
    for record in decisions:
        grouped.setdefault(record.proposal_id, []).append(record)
    return grouped


class ReviewLookupStatus(str, Enum):
    """review journal を読めたか。読めないことを「誰も見ていない」にしない。"""

    AVAILABLE = "AVAILABLE"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    UNUSABLE = "UNUSABLE"


@dataclass(frozen=True, kw_only=True)
class FindingReview:
    """いま観測されている finding と、それに対する人間の operational 履歴（derived view）。

    `finding` が出ていることは「未解決」を意味しない。`resolution` が RESOLVED でも「事象が直った」ではない。
    前者は derived fact、後者は人間の運用状態であり、両者は別物である。
    """

    finding: MonitoringFinding
    resolution: ReviewChainResolution


@dataclass(frozen=True, kw_only=True)
class MonitoringRunResult:
    """1 回の run の返り値。governance command / 実行計画 / 推奨 action / 優先度 / 予測を持たない。"""

    runner_version: str = MONITORING_RUNNER_VERSION
    report: MonitoringRunReport
    findings: Tuple[MonitoringFinding, ...]
    reviews: Tuple[FindingReview, ...]
    review_status: ReviewLookupStatus
    diagnostics: Tuple[str, ...] = ()


# ---------------------------------------------------------------- 入力の検証


def _data_root(value: Union[str, "os.PathLike[str]"]) -> Union[str, "os.PathLike[str]"]:
    _require(value is not None and str(value).strip() != "", "DATA_ROOT_REQUIRED",
             "an explicit data_root is required (no fallback)")
    _require(not str(value).startswith("~"), "DATA_ROOT_REQUIRED", "data_root must not rely on a home shortcut")
    return value


def _moment(value: object, name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_TIME", f"{name} must be a datetime")
    try:
        return ensure_aware(value, name)
    except Exception:
        raise MonitoringRunnerError("INVALID_TIME", f"{name} must be an aware datetime") from None


def _scope(root_ids: Sequence[str]) -> Tuple[str, ...]:
    """monitoring scope は呼び出し側が明示する。authority 全体の列挙を暗黙に行わない。"""
    _require(isinstance(root_ids, (list, tuple)), "INVALID_TYPE", "root_ids must be a sequence")
    scope = tuple(sorted(set(root_ids)))
    for root_id in scope:
        _require(is_root_id(root_id), "INVALID_ROOT_ID", "root_ids holds Theme root ids")
    return scope


def _knowledge_versions(supplied: Sequence[Tuple[str, str]], policy: LifecyclePolicy) -> Tuple[Tuple[str, str], ...]:
    """実際に使う knowledge だけを run identity へ束縛する（unresolvable は fail closed）。"""
    versions: Dict[str, str] = {}
    _require(isinstance(supplied, (list, tuple)), "INVALID_TYPE", "knowledge_versions must be a sequence of pairs")
    for item in supplied:
        _require(isinstance(item, (list, tuple)) and len(item) == 2, "INVALID_TYPE",
                 "knowledge_versions holds (name, version) pairs")
        name, version = str(item[0]), str(item[1])
        _require(name != "" and version != "", "MISSING_KNOWLEDGE_VERSION", "a knowledge binding needs both parts")
        _require(versions.get(name, version) == version, "KNOWLEDGE_VERSION_CONFLICT", name)
        versions[name] = version
    policy_token = freshness_policy_token(policy)
    _require(versions.get(LIFECYCLE_POLICY_KEY, policy_token) == policy_token, "KNOWLEDGE_VERSION_CONFLICT",
             LIFECYCLE_POLICY_KEY)
    versions[LIFECYCLE_POLICY_KEY] = policy_token
    return tuple(sorted(versions.items()))


def _ruleset(ruleset: Optional[MonitoringRuleset], knowledge_root, ruleset_version: str,
             cutoff: datetime) -> MonitoringRuleset:
    if ruleset is not None:
        _require(knowledge_root is None and ruleset_version == "", "AMBIGUOUS_RULESET",
                 "pass either a loaded ruleset or a knowledge_root plus ruleset_version")
        _require(isinstance(ruleset, MonitoringRuleset), "INVALID_TYPE", "ruleset must be a MonitoringRuleset")
        return ruleset
    _require(knowledge_root is not None and ruleset_version != "", "RULESET_REQUIRED",
             "an explicit ruleset version is required (there is no latest)")
    return load_monitoring_rules_version(monitoring_rules_path(knowledge_root, ruleset_version),
                                         expected_version=ruleset_version, cutoff=cutoff)


# ---------------------------------------------------------------- authority ごとの読み取り（read-only）


@dataclass(frozen=True, kw_only=True)
class _ThemeReadout:
    snapshots: Tuple[ThemeSnapshot, ...]
    created_at_by_root: Mapping[str, datetime]
    retired: Tuple[str, ...]
    superseded: Tuple[str, ...]


def _read_themes(data_root, scope: Tuple[str, ...], cutoff: datetime, policy: LifecyclePolicy,
                 observations: MonitoringObservations,
                 governance_events_by_root: Mapping[str, Sequence[ThemeGovernanceEvent]],
                 diagnostics: Set[str]) -> _ThemeReadout:
    policy_token = freshness_policy_token(policy)
    snapshots: List[ThemeSnapshot] = []
    created: Dict[str, datetime] = {}
    retired: List[str] = []
    superseded: List[str] = []
    for root_id in scope:
        try:
            resolution = resolve_at_data_root(data_root, root_id, cutoff)
        except Exception as exc:                                   # store が開けない等は条件の偽ではない
            code = _error_code(exc)
            snapshots.append(theme_failure_snapshot(root_id, code))
            diagnostics.add(f"THEME_AUTHORITY_UNUSABLE:{code}"[:MAX_DIAGNOSTIC_LEN])
            continue
        if resolution.root is not None:
            created[root_id] = resolution.root.created_at
        try:
            view = derive_lifecycle(resolution, policy=policy,
                                    governance_events=governance_events_by_root.get(root_id))
        except ThemeLifecycleError as exc:                          # 例: correction chain を推測しない
            snapshots.append(theme_failure_snapshot(root_id, exc.code))
            diagnostics.add(f"LIFECYCLE_UNAVAILABLE:{exc.code}"[:MAX_DIAGNOSTIC_LEN])
            continue
        if view.governance.state is GovernanceLifecycleState.RETIRED:
            retired.append(root_id)
        elif view.governance.state is GovernanceLifecycleState.SUPERSEDED:
            superseded.append(root_id)
        snapshots.append(theme_snapshot(
            resolution, view, policy_token=policy_token,
            arrived_attachment_keys=tuple((observations.arrived_attachment_keys or {}).get(root_id, ())),
            semantic_revision_observation_id=(observations.semantic_revision_observation_ids or {}).get(root_id, "")))
    return _ThemeReadout(snapshots=tuple(snapshots), created_at_by_root=created, retired=tuple(sorted(retired)),
                         superseded=tuple(sorted(superseded)))


def _read_proposals(data_root, cutoff: datetime, observations: MonitoringObservations, failures: List,
                    diagnostics: Set[str]) -> Tuple[ProposalSnapshot, ...]:
    try:
        store = ProposalStore.open(data_root, read_only=True)
        proposals = _visible_at(store.proposals(), "created_at", cutoff)        # store 検証の後で濾過する
        decisions_by_proposal = _by_proposal(_visible_at(store.decisions(), "recorded_at", cutoff))
    except Exception as exc:
        code = _error_code(exc)
        failures.append(authority_failure(AUTHORITY_PROPOSALS, code, blocked_condition_ids=PROPOSAL_CONDITIONS))
        diagnostics.add(f"PROPOSAL_AUTHORITY_UNUSABLE:{code}"[:MAX_DIAGNOSTIC_LEN])
        return ()
    snapshots: List[ProposalSnapshot] = []
    for proposal in proposals:
        decisions = tuple(decisions_by_proposal.get(proposal.proposal_id, ()))
        chain = resolve_active_decision(proposal.proposal_id, decisions)
        snapshots.append(proposal_snapshot(
            proposal.proposal_id, status=derive_proposal_status(proposal, decisions),
            created_at=proposal.created_at, decision_status=chain.status,
            decision_diagnostic=chain.diagnostics[0] if chain.diagnostics else "",
            discovery_outcome_token=(observations.discovery_outcome_tokens or {}).get(proposal.proposal_id, "")))
    return tuple(snapshots)


def _read_relations(data_root, cutoff: datetime, readout: _ThemeReadout, failures: List, diagnostics: Set[str]
                    ) -> Tuple[Tuple[RelationSnapshot, ...], Mapping[str, Tuple[str, ...]], bool]:
    lookup = endpoint_lookup_from_roots(readout.created_at_by_root, retired=readout.retired,
                                        superseded=readout.superseded)
    try:
        resolution = resolve_relations_at_data_root(data_root, cutoff=cutoff, endpoint_lookup=lookup)
    except Exception as exc:
        code = _error_code(exc)
        failures.append(authority_failure("theme_relations", code,
                                          blocked_condition_ids=RELATION_BLOCKED_CONDITIONS))
        diagnostics.add(f"RELATION_AUTHORITY_UNUSABLE:{code}"[:MAX_DIAGNOSTIC_LEN])
        return (), {}, False
    failure = relation_authority_failure(resolution.status, blocked_condition_ids=RELATION_BLOCKED_CONDITIONS)
    if failure is not None:
        failures.append(failure)
        diagnostics.add(f"RELATION_AUTHORITY_UNUSABLE:{resolution.status.value}"[:MAX_DIAGNOSTIC_LEN])
    contested = contested_roots(readout.snapshots)
    snapshots: List[RelationSnapshot] = [relation_snapshot(edge, contested=contested) for edge in resolution.edges]
    snapshots.extend(unresolved_relation_snapshot(edge) for edge in resolution.unresolved)
    snapshots.extend(excluded_relation_snapshot(edge) for edge in resolution.excluded)
    if resolution.excluded:
        diagnostics.add("MONITORING_SCOPE_MISSES_RELATION_ENDPOINT")
    return tuple(snapshots), retracted_edge_prefixes(resolution.edges), failure is None


def _read_relation_proposals(data_root, cutoff: datetime, retracted: Mapping[str, Tuple[str, ...]],
                             relations_usable: bool, failures: List, diagnostics: Set[str]
                             ) -> Tuple[RelationProposalSnapshot, ...]:
    try:
        store = RelationProposalStore.open(data_root, read_only=True)
        proposals = _visible_at(store.proposals(), "created_at", cutoff)        # store 検証の後で濾過する
        decisions_by_proposal = _by_proposal(_visible_at(store.decisions(), "recorded_at", cutoff))
    except Exception as exc:
        code = _error_code(exc)
        failures.append(authority_failure(AUTHORITY_RELATION_PROPOSALS, code,
                                          blocked_condition_ids=RELATION_PROPOSAL_CONDITIONS))
        diagnostics.add(f"RELATION_PROPOSAL_AUTHORITY_UNUSABLE:{code}"[:MAX_DIAGNOSTIC_LEN])
        return ()
    snapshots: List[RelationProposalSnapshot] = []
    for proposal in proposals:
        decisions = decisions_by_proposal.get(proposal.proposal_id, [])
        status = derive_relation_proposal_status(proposal, decisions)
        prefix = edge_prefix(proposal.source_theme_root_id, proposal.target_theme_root_id,
                             proposal.relation_type.value)
        edge_keys = retracted.get(prefix, ()) if relations_usable else ()
        if status in LIVE_RELATION_PROPOSAL_STATUSES and edge_keys:
            snapshots.extend(relation_proposal_snapshot(proposal.proposal_id, status=status, edge_key=key,
                                                        conflict_token=RETRACTED_CONFLICT_TOKEN)
                             for key in edge_keys)
        else:
            snapshots.append(relation_proposal_snapshot(proposal.proposal_id, status=status))
    return tuple(snapshots)


def _read_reviews(data_root, findings: Sequence[MonitoringFinding], diagnostics: Set[str]
                  ) -> Tuple[Tuple[FindingReview, ...], ReviewLookupStatus]:
    """review journal は read-only で開く。ここから書き戻すことは無い（append は人間専用の別 API）。"""
    try:
        store = MonitoringReviewStore.open(data_root, read_only=True)
    except Exception as exc:
        code = _error_code(exc)
        if code == "AUTHORITY_MISSING":
            diagnostics.add("REVIEW_STORE_NOT_INITIALIZED")
            return (), ReviewLookupStatus.NOT_INITIALIZED
        diagnostics.add(f"REVIEW_STORE_UNUSABLE:{code}"[:MAX_DIAGNOSTIC_LEN])
        return (), ReviewLookupStatus.UNUSABLE
    states = store.review_states()
    reviews = tuple(FindingReview(finding=finding, resolution=resolve_review_state(finding.finding_id, states))
                    for finding in findings)
    return reviews, ReviewLookupStatus.AVAILABLE


# ---------------------------------------------------------------- entry point


def run_monitoring(*, data_root: Union[str, "os.PathLike[str]"], cutoff: datetime, recorded_at: datetime,
                   root_ids: Sequence[str], lifecycle_policy: LifecyclePolicy,
                   ruleset: Optional[MonitoringRuleset] = None, knowledge_root=None, ruleset_version: str = "",
                   knowledge_versions: Sequence[Tuple[str, str]] = (),
                   knowledge_drift: Sequence[Tuple[str, str, str]] = (),
                   governance_events_by_root: Optional[Mapping[str, Sequence[ThemeGovernanceEvent]]] = None,
                   observations: Optional[MonitoringObservations] = None) -> MonitoringRunResult:
    """authority を read-only で読み、cutoff 固定で評価し、observation と review 状態を返す。**何も書かない**。"""
    root = _data_root(data_root)
    moment = _moment(cutoff, "cutoff")
    recorded = _moment(recorded_at, "recorded_at")
    _require(recorded >= moment, "RECORDED_BEFORE_CUTOFF", "a run cannot be recorded before its cutoff")
    _require(isinstance(lifecycle_policy, LifecyclePolicy), "INVALID_TYPE",
             "lifecycle_policy must be a LifecyclePolicy")
    scope = _scope(root_ids)
    rules = _ruleset(ruleset, knowledge_root, ruleset_version, moment)
    versions = _knowledge_versions(knowledge_versions, lifecycle_policy)
    seen = observations if observations is not None else MonitoringObservations()
    _require(isinstance(seen, MonitoringObservations), "INVALID_TYPE",
             "observations must be a MonitoringObservations")
    events = dict(governance_events_by_root or {})

    diagnostics: Set[str] = {f"OBSERVATION_NOT_SUPPLIED:{name}"[:MAX_DIAGNOSTIC_LEN]
                             for name in seen.missing_channels()}
    if not scope:
        diagnostics.add("EMPTY_MONITORING_SCOPE")
    failures: List = []
    readout = _read_themes(root, scope, moment, lifecycle_policy, seen, events, diagnostics)
    if scope and not events:
        diagnostics.add("GOVERNANCE_EVENTS_NOT_SUPPLIED")
    proposals = _read_proposals(root, moment, seen, failures, diagnostics)
    relations, retracted, relations_usable = _read_relations(root, moment, readout, failures, diagnostics)
    relation_proposals = _read_relation_proposals(root, moment, retracted, relations_usable, failures, diagnostics)
    drift = tuple(knowledge_drift_snapshot(str(name), str(before), str(after))
                  for name, before, after in knowledge_drift)

    evaluation_input = build_evaluation_input(
        cutoff=moment, knowledge_versions=versions, themes=readout.snapshots, proposals=proposals,
        relations=relations, relation_proposals=relation_proposals, knowledge_drift=drift,
        authority_failures=tuple(failures), observations=seen)
    evaluation = evaluate_monitoring(evaluation_input, ruleset=rules, recorded_at=recorded)
    reviews, review_status = _read_reviews(root, evaluation.findings, diagnostics)
    return MonitoringRunResult(report=evaluation.report, findings=evaluation.findings, reviews=reviews,
                               review_status=review_status, diagnostics=tuple(sorted(diagnostics)))


__all__ = ["FindingReview", "LIFECYCLE_POLICY_KEY", "MONITORING_RUNNER_VERSION", "MonitoringRunResult",
           "MonitoringRunnerError", "RELATION_BLOCKED_CONDITIONS", "RUN_IS_READ_ONLY", "ReviewLookupStatus",
           "run_monitoring"]
