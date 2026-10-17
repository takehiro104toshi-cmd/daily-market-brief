"""P6-B6C — 決定論的 monitoring engine（純関数。I/O を持たない）。

read-only な resolved intelligence state ＋ 明示 cutoff ＋ versioned ruleset から、B6B の
`MonitoringFinding` 群と `MonitoringRunReport` を導く。**新しい主張を作らず、既存の状態を指差すだけ**である。

規律:

- engine は file / network / 現在時刻 / 乱数 / 環境変数を一切触らない。入力は呼び出し側が渡す不変 snapshot。
- B1 / B2 / B4 / B5 の意味論を再実装しない。`CONTESTED` / `STALE` / 端点状態 / chain 解決は
  上流の derived 結果を **そのまま読む**。stale の日数計算を二重に持たない。
- 評価できない subject を「条件が偽」として扱わない。`unevaluated_conditions` に入れ、INTEGRITY finding を出し、
  run status を `PARTIAL` にする。静かな COMPLETE ＋ finding 0 を作らない。
- 出力順は `finding_id` の辞書順に固定する。**順序に優先度の意味は無い。**
- score / 順位 / 確率 / severity / 予測 / 投資スタンスを持たない。governance action も実行命令も生成しない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..core.time import ensure_aware
from .monitoring_model import (MonitoringCategory, MonitoringFinding, MonitoringReference, MonitoringRunReport,
                               MonitoringRunStatus, MonitoringSubjectKind, SalientState, SalientStateKind)
from .monitoring_rules import CONDITION_REGISTRY, MonitoringRuleset

MONITORING_ENGINE_VERSION = "theme_monitoring_engine:0.1.0"
#: engine は「観測」しか出さない。実行命令の語彙を持たないことを凍結する文言
ENGINE_EMITS_OBSERVATIONS_ONLY = "the engine reports observed state and never asks for an action"

#: B2 が所有する evidence 条件 flag のうち、B6 が review condition として指差すもの
ABSENCE_FLAGS: Tuple[str, ...] = ("NO_VISIBLE_EVIDENCE", "HAS_CONTEXT_ONLY")
DIVERGENCE_FLAGS: Tuple[str, ...] = ("NO_VISIBLE_EVIDENCE", "HAS_CONTEXT_ONLY", "INVALIDATION_EVIDENCE_PRESENT")
STALE_FLAG = "STALE"
#: governance 上 ACCEPTED とみなす状態（B2 の語彙をそのまま読む）
ACCEPTED_STATES: Tuple[str, ...] = ("ACCEPTED",)
#: 新しい evidence が来たら review が要る、終了済みの governance 状態
CLOSED_STATES: Tuple[str, ...] = ("RETIRED", "SUPERSEDED", "MERGED", "SPLIT", "REJECTED")
#: chain 解決が失敗しているとみなす状態（B3 / B5C / B6B の語彙をそのまま読む）
BROKEN_CHAIN_STATES: Tuple[str, ...] = ("UNRESOLVED", "INVALID")
#: 端点が活きていないとみなす状態（B5 の `EndpointState` をそのまま読む）
INACTIVE_ENDPOINT_STATES: Tuple[str, ...] = ("RETIRED", "SUPERSEDED", "NOT_CREATED_YET", "UNKNOWN_ROOT")
OPEN_STATUS = "OPEN"
DEFERRED_STATUS = "OPEN_DEFERRED"
OUTCOME_NO_ACCEPTED_PROPOSAL = "NO_ACCEPTED_PROPOSAL"
OUTCOME_NO_OBSERVED_EFFECT = "NO_OBSERVED_EFFECT"
#: P6-B6R1: 呼び出し側が供給する観測 channel → その channel が無いと評価できない condition。
#: 下の `_theme` / `_proposal` が読む snapshot field（到着 key・意味改訂 id・discovery outcome）の写しである。
OBSERVATION_CHANNEL_CONDITIONS: Mapping[str, Tuple[str, ...]] = {
    "arrived_attachment_keys": ("RETIRED_ROOT_RECEIVED_EVIDENCE",),
    "semantic_revision_observation_ids": ("ACCEPTED_THEME_SEMANTIC_REVISION",),
    "discovery_outcome_tokens": ("DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL",
                                 "ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT"),
}
#: どの channel が供給されたかを run identity（input digest）へ束縛する key と、何も供給されていないときの値
OBSERVATION_PRESENCE_KEY = "observation_channels_supplied"
NO_CHANNEL_SUPPLIED = "none"


class MonitoringEngineError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise MonitoringEngineError(code, detail)


class SubjectAvailability(str, Enum):
    """その subject を cutoff 時点で信頼して読めたか。読めていないことを「条件が偽」にしない。"""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


# ---------------------------------------------------------------- 入力 snapshot（不変・最小）


@dataclass(frozen=True, kw_only=True)
class _Subject:
    availability: SubjectAvailability = SubjectAvailability.AVAILABLE
    authority_name: str = ""
    failure_class: str = ""
    locator_token: str = ""

    def _unusable(self) -> bool:
        return self.availability is SubjectAvailability.UNAVAILABLE


@dataclass(frozen=True, kw_only=True)
class ThemeSnapshot(_Subject):
    """1 Theme root の read-only な derived 状態。B2 の結果をそのまま写す（再計算しない）。"""

    theme_root_id: str
    governance_state: str = ""
    evidence_flags: Tuple[str, ...] = ()
    evidence_roles_present: Tuple[str, ...] = ()
    arrived_attachment_keys: Tuple[str, ...] = ()
    semantic_revision_observation_id: str = ""
    freshness_policy_token: str = ""


@dataclass(frozen=True, kw_only=True)
class ProposalSnapshot(_Subject):
    """1 提案の read-only な状態。status と chain 解決は B3 / B5C の結果をそのまま写す。"""

    proposal_id: str
    proposal_status: str = ""
    created_at: Optional[datetime] = None
    decision_chain_status: str = ""
    decision_chain_diagnostic: str = ""
    discovery_outcome_token: str = ""


@dataclass(frozen=True, kw_only=True)
class RelationSnapshot(_Subject):
    """1 relation edge の read-only な状態。B5 の resolution をそのまま写す。"""

    edge_key: str
    edge_state: str = ""
    assertion_class: str = ""
    source_endpoint_state: str = ""
    target_endpoint_state: str = ""
    contested_theme_root_id: str = ""
    contested_role: str = ""
    governance_chain_status: str = ""
    governance_chain_diagnostic: str = ""


@dataclass(frozen=True, kw_only=True)
class RelationProposalSnapshot(_Subject):
    """撤回済み relation へ新しい提案が来ている、という観測。"""

    relation_proposal_id: str
    edge_key: str
    conflict_token: str = ""


@dataclass(frozen=True, kw_only=True)
class KnowledgeDriftSnapshot:
    knowledge_name: str
    from_version: str
    to_version: str


@dataclass(frozen=True, kw_only=True)
class AuthorityFailureSnapshot:
    """subject に紐づかない authority 全体の失敗（journal 破損 / PIT 解決失敗 / schema 不整合など）。"""

    authority_name: str
    failure_class: str
    locator_token: str = ""
    blocked_condition_ids: Tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class MonitoringEvaluationInput:
    """engine が条件判定に必要な最小 state。generic な dict dump を受けない。"""

    cutoff: datetime
    knowledge_versions: Tuple[Tuple[str, str], ...] = ()
    input_digests: Tuple[Tuple[str, str], ...] = ()
    themes: Tuple[ThemeSnapshot, ...] = ()
    proposals: Tuple[ProposalSnapshot, ...] = ()
    relations: Tuple[RelationSnapshot, ...] = ()
    relation_proposals: Tuple[RelationProposalSnapshot, ...] = ()
    knowledge_drift: Tuple[KnowledgeDriftSnapshot, ...] = ()
    authority_failures: Tuple[AuthorityFailureSnapshot, ...] = ()
    #: 供給された観測 channel。**既定は「何も供給されていない」**（coverage を主張する隠れた既定値を持たない）
    supplied_observation_channels: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(isinstance(self.cutoff, datetime), "INVALID_CUTOFF", "cutoff must be a datetime")
        try:
            ensure_aware(self.cutoff, "cutoff")
        except Exception:
            raise MonitoringEngineError("INVALID_CUTOFF", "cutoff must be an aware datetime") from None
        for name in ("themes", "proposals", "relations", "relation_proposals", "knowledge_drift",
                     "authority_failures", "knowledge_versions", "input_digests", "supplied_observation_channels"):
            _require(isinstance(getattr(self, name), tuple), "INVALID_TYPE", f"{name} must be a tuple")
        _require(all(isinstance(name, str) and name in OBSERVATION_CHANNEL_CONDITIONS
                     for name in self.supplied_observation_channels),
                 "INVALID_OBSERVATION_CHANNEL", "supplied_observation_channels names a known channel only")
        _require(not any(isinstance(pair, tuple) and pair[:1] == (OBSERVATION_PRESENCE_KEY,)
                         for pair in self.input_digests), "RESERVED_DIGEST_KEY",
                 f"{OBSERVATION_PRESENCE_KEY} is bound by the engine")


@dataclass(frozen=True, kw_only=True)
class MonitoringEvaluation:
    """1 回の評価の結果。findings は `finding_id` 昇順（順序に優先度の意味は無い）。"""

    engine_version: str = MONITORING_ENGINE_VERSION
    findings: Tuple[MonitoringFinding, ...]
    report: MonitoringRunReport


# ---------------------------------------------------------------- 評価 helper


@dataclass
class _Collector:
    ruleset: MonitoringRuleset
    cutoff: datetime
    findings: Dict[str, MonitoringFinding] = field(default_factory=dict)
    unevaluated: set = field(default_factory=set)
    diagnostics: set = field(default_factory=set)
    #: 必要な観測 channel が供給されず評価しない condition（finding を出さない）
    withheld: set = field(default_factory=set)

    def enabled(self, condition_id: str) -> bool:
        rule = self.ruleset.rule(condition_id)
        return bool(rule and rule.enabled)

    def emit(self, condition_id: str, subject_ref: str, facts: Mapping[str, str], *,
             trigger_refs: Sequence[MonitoringReference] = (),
             supporting_refs: Sequence[MonitoringReference] = ()) -> None:
        if condition_id in self.withheld:                     # 入力が無い condition は評価しない
            return
        rule = self.ruleset.rule(condition_id)
        if rule is None or not rule.enabled:
            return
        spec = CONDITION_REGISTRY[condition_id]
        finding = MonitoringFinding.build(
            condition_id=condition_id, category=spec.category, subject_kind=spec.subject_kind,
            subject_ref=subject_ref,
            salient_state=SalientState(state_kind=spec.salient_state_kind, facts=dict(facts)),
            cutoff=self.cutoff, condition_version=rule.condition_version, message_key=rule.message_key,
            ruleset_version=self.ruleset.ruleset_version,
            knowledge_versions=(), trigger_refs=tuple(trigger_refs), supporting_refs=tuple(supporting_refs))
        self.findings[finding.finding_id] = finding          # 同一 identity は 1 件に収束する

    def blocked(self, subject: _Subject, condition_ids: Sequence[str], subject_ref: str) -> None:
        """読めなかった subject の条件を未評価として記録し、INTEGRITY finding を 1 件出す。"""
        authority = subject.authority_name or "unknown_authority"
        failure = subject.failure_class or "UNUSABLE"
        for condition_id in condition_ids:
            if self.enabled(condition_id):
                self.unevaluated.add(condition_id)
        self.diagnostics.add(f"SUBJECT_UNUSABLE:{failure}")
        self.emit("AUTHORITY_STATE_UNUSABLE", f"authority:{authority}",
                  {"authority_name": authority, "failure_class": failure,
                   "locator_token": subject.locator_token or subject_ref})


THEME_CONDITIONS: Tuple[str, ...] = ("THEME_CONTRADICTION_EVIDENCE_PRESENT", "THEME_INVALIDATION_EVIDENCE_PRESENT",
                                     "THEME_WITHOUT_COUNTED_EVIDENCE", "THEME_EVIDENCE_STALE",
                                     "ACCEPTED_THEME_SEMANTIC_REVISION", "RETIRED_ROOT_RECEIVED_EVIDENCE",
                                     "GOVERNANCE_EVIDENCE_DIVERGENCE")
PROPOSAL_CONDITIONS: Tuple[str, ...] = ("THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD",
                                        "THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD",
                                        "PROPOSAL_DECISION_CHAIN_UNRESOLVED",
                                        "DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL",
                                        "ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT")
RELATION_CONDITIONS: Tuple[str, ...] = ("RELATION_ENDPOINT_NOT_ACTIVE", "SOURCE_ASSERTED_RELATION_CONTESTED",
                                        "RELATION_GOVERNANCE_CHAIN_UNRESOLVED")
RELATION_PROPOSAL_CONDITIONS: Tuple[str, ...] = ("RETRACTED_RELATION_HAS_NEW_PROPOSAL",)


def _theme(collector: _Collector, snapshot: ThemeSnapshot) -> None:
    if snapshot._unusable():
        collector.blocked(snapshot, THEME_CONDITIONS, snapshot.theme_root_id)
        return
    root = snapshot.theme_root_id
    flags = set(snapshot.evidence_flags)
    roles = set(snapshot.evidence_roles_present)
    refs = tuple(MonitoringReference(ref_kind="attachment", ref_id=key)
                 for key in sorted(set(snapshot.arrived_attachment_keys)))
    if "CONTRADICTS" in roles:
        collector.emit("THEME_CONTRADICTION_EVIDENCE_PRESENT", root,
                       {"theme_root_id": root, "role": "CONTRADICTS"}, supporting_refs=refs)
    if "INVALIDATES" in roles:
        collector.emit("THEME_INVALIDATION_EVIDENCE_PRESENT", root,
                       {"theme_root_id": root, "role": "INVALIDATES"}, supporting_refs=refs)
    for flag in ABSENCE_FLAGS:
        if flag in flags:
            collector.emit("THEME_WITHOUT_COUNTED_EVIDENCE", root,
                           {"theme_root_id": root, "absence_kind": flag})
    if STALE_FLAG in flags:
        if snapshot.freshness_policy_token:
            collector.emit("THEME_EVIDENCE_STALE", root,
                           {"theme_root_id": root, "threshold_token": snapshot.freshness_policy_token})
        else:                                                 # 上流 policy の version が無ければ評価しない
            if collector.enabled("THEME_EVIDENCE_STALE"):
                collector.unevaluated.add("THEME_EVIDENCE_STALE")
            collector.diagnostics.add("FRESHNESS_POLICY_TOKEN_MISSING")
    if snapshot.governance_state in ACCEPTED_STATES and snapshot.semantic_revision_observation_id:
        collector.emit("ACCEPTED_THEME_SEMANTIC_REVISION", root,
                       {"theme_root_id": root,
                        "observation_id": snapshot.semantic_revision_observation_id})
    if snapshot.governance_state in CLOSED_STATES:
        for key in sorted(set(snapshot.arrived_attachment_keys)):
            collector.emit("RETIRED_ROOT_RECEIVED_EVIDENCE", root,
                           {"theme_root_id": root, "attachment_key": key},
                           trigger_refs=(MonitoringReference(ref_kind="attachment", ref_id=key),))
    if snapshot.governance_state in ACCEPTED_STATES:
        for flag in DIVERGENCE_FLAGS:
            if flag in flags:
                collector.emit("GOVERNANCE_EVIDENCE_DIVERGENCE", root,
                               {"theme_root_id": root, "governance_state": snapshot.governance_state,
                                "evidence_condition": flag})


def _proposal(collector: _Collector, snapshot: ProposalSnapshot) -> None:
    if snapshot._unusable():
        collector.blocked(snapshot, PROPOSAL_CONDITIONS, snapshot.proposal_id)
        return
    proposal_id = snapshot.proposal_id
    for condition_id, status in (("THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD", OPEN_STATUS),
                                 ("THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD", DEFERRED_STATUS)):
        rule = collector.ruleset.rule(condition_id)
        if rule is None or not rule.enabled or snapshot.proposal_status != status:
            continue
        if snapshot.created_at is None:
            collector.unevaluated.add(condition_id)
            collector.diagnostics.add("PROPOSAL_CREATED_AT_MISSING")
            continue
        threshold = int(rule.threshold_days or 0)
        if collector.cutoff - snapshot.created_at >= timedelta(days=threshold):
            collector.emit(condition_id, proposal_id,
                           {"proposal_id": proposal_id, "proposal_status": status,
                            "threshold_token": f"{status.lower()}_after_days:{threshold}"})
    if snapshot.decision_chain_status in BROKEN_CHAIN_STATES:
        collector.emit("PROPOSAL_DECISION_CHAIN_UNRESOLVED", f"chain:{proposal_id}",
                       {"chain_kind": "PROPOSAL_DECISION",
                        "diagnostic_code": snapshot.decision_chain_diagnostic or snapshot.decision_chain_status,
                        "subject_token": proposal_id})
    if snapshot.discovery_outcome_token == OUTCOME_NO_ACCEPTED_PROPOSAL:
        collector.emit("DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL", proposal_id,
                       {"proposal_id": proposal_id, "outcome_token": OUTCOME_NO_ACCEPTED_PROPOSAL})
    if snapshot.discovery_outcome_token == OUTCOME_NO_OBSERVED_EFFECT:
        collector.emit("ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT", proposal_id,
                       {"proposal_id": proposal_id, "outcome_token": OUTCOME_NO_OBSERVED_EFFECT})


def _relation(collector: _Collector, snapshot: RelationSnapshot) -> None:
    if snapshot._unusable():
        collector.blocked(snapshot, RELATION_CONDITIONS, snapshot.edge_key)
        return
    edge = snapshot.edge_key
    if snapshot.edge_state == "ACTIVE":
        for role, endpoint_state in (("SOURCE", snapshot.source_endpoint_state),
                                     ("TARGET", snapshot.target_endpoint_state)):
            if endpoint_state in INACTIVE_ENDPOINT_STATES:
                collector.emit("RELATION_ENDPOINT_NOT_ACTIVE", edge,
                               {"edge_key": edge, "endpoint_role": role, "endpoint_state": endpoint_state})
    if snapshot.assertion_class == "SOURCE_ASSERTED" and snapshot.contested_theme_root_id:
        collector.emit("SOURCE_ASSERTED_RELATION_CONTESTED", edge,
                       {"edge_key": edge, "theme_root_id": snapshot.contested_theme_root_id,
                        "role": snapshot.contested_role or "CONTRADICTS"})
    if snapshot.governance_chain_status in BROKEN_CHAIN_STATES:
        collector.emit("RELATION_GOVERNANCE_CHAIN_UNRESOLVED", f"chain:{edge}",
                       {"chain_kind": "RELATION_GOVERNANCE",
                        "diagnostic_code": snapshot.governance_chain_diagnostic or snapshot.governance_chain_status,
                        "subject_token": edge})


def _relation_proposal(collector: _Collector, snapshot: RelationProposalSnapshot) -> None:
    if snapshot._unusable():
        collector.blocked(snapshot, RELATION_PROPOSAL_CONDITIONS, snapshot.relation_proposal_id)
        return
    if snapshot.conflict_token:
        collector.emit("RETRACTED_RELATION_HAS_NEW_PROPOSAL", snapshot.relation_proposal_id,
                       {"edge_key": snapshot.edge_key, "relation_proposal_id": snapshot.relation_proposal_id,
                        "conflict_token": snapshot.conflict_token})


def _knowledge_drift(collector: _Collector, snapshot: KnowledgeDriftSnapshot) -> None:
    if snapshot.from_version == snapshot.to_version:
        return
    collector.emit("KNOWLEDGE_VERSION_DRIFT", f"knowledge:{snapshot.knowledge_name}",
                   {"knowledge_name": snapshot.knowledge_name, "from_version": snapshot.from_version,
                    "to_version": snapshot.to_version})


def _authority_failure(collector: _Collector, snapshot: AuthorityFailureSnapshot) -> None:
    for condition_id in snapshot.blocked_condition_ids:
        _require(condition_id in CONDITION_REGISTRY, "UNKNOWN_CONDITION_ID", condition_id)
        if collector.enabled(condition_id):
            collector.unevaluated.add(condition_id)
    collector.diagnostics.add(f"AUTHORITY_UNUSABLE:{snapshot.failure_class}")
    collector.emit("AUTHORITY_STATE_UNUSABLE", f"authority:{snapshot.authority_name}",
                   {"authority_name": snapshot.authority_name, "failure_class": snapshot.failure_class,
                    "locator_token": snapshot.locator_token or "whole_authority"})


# ---------------------------------------------------------------- entry point


def evaluate_monitoring(evaluation_input: MonitoringEvaluationInput, *, ruleset: MonitoringRuleset,
                        recorded_at: datetime) -> MonitoringEvaluation:
    """read-only snapshot ＋ ruleset から findings と run report を導く（純関数。何も書かない）。"""
    _require(isinstance(evaluation_input, MonitoringEvaluationInput), "INVALID_TYPE",
             "evaluation_input must be a MonitoringEvaluationInput")
    _require(isinstance(ruleset, MonitoringRuleset), "INVALID_TYPE", "ruleset must be a MonitoringRuleset")
    _require(isinstance(recorded_at, datetime), "INVALID_RECORDED_AT", "recorded_at must be a datetime")
    try:
        ensure_aware(recorded_at, "recorded_at")
    except Exception:
        raise MonitoringEngineError("INVALID_RECORDED_AT", "recorded_at must be an aware datetime") from None
    _require(recorded_at >= evaluation_input.cutoff, "RECORDED_BEFORE_CUTOFF",
             "a run cannot be recorded before its cutoff")
    _require(ruleset.published_at <= evaluation_input.cutoff, "FUTURE_RULESET",
             "the ruleset was published after the cutoff")

    collector = _Collector(ruleset=ruleset, cutoff=evaluation_input.cutoff)
    supplied = set(evaluation_input.supplied_observation_channels)
    for channel in sorted(set(OBSERVATION_CHANNEL_CONDITIONS) - supplied):   # 未供給 ≠ 空で供給
        dependents = OBSERVATION_CHANNEL_CONDITIONS[channel]
        collector.withheld.update(dependents)
        requested = [condition_id for condition_id in dependents if collector.enabled(condition_id)]
        collector.unevaluated.update(requested)
        if requested:
            collector.diagnostics.add(f"OBSERVATION_NOT_SUPPLIED:{channel}")
    presence = "|".join(sorted(supplied)) or NO_CHANNEL_SUPPLIED
    for theme in sorted(evaluation_input.themes, key=lambda s: s.theme_root_id):
        _theme(collector, theme)
    for proposal in sorted(evaluation_input.proposals, key=lambda s: s.proposal_id):
        _proposal(collector, proposal)
    for relation in sorted(evaluation_input.relations, key=lambda s: s.edge_key):
        _relation(collector, relation)
    for candidate in sorted(evaluation_input.relation_proposals, key=lambda s: s.relation_proposal_id):
        _relation_proposal(collector, candidate)
    for drift in sorted(evaluation_input.knowledge_drift, key=lambda s: s.knowledge_name):
        _knowledge_drift(collector, drift)
    for failure in sorted(evaluation_input.authority_failures,
                          key=lambda s: (s.authority_name, s.failure_class, s.locator_token)):
        _authority_failure(collector, failure)

    findings = tuple(collector.findings[key] for key in sorted(collector.findings))
    unevaluated = tuple(sorted(collector.unevaluated))
    status = MonitoringRunStatus.PARTIAL if unevaluated else MonitoringRunStatus.COMPLETE
    report = MonitoringRunReport.build(
        cutoff=evaluation_input.cutoff, ruleset_version=ruleset.ruleset_version, recorded_at=recorded_at,
        status=status, knowledge_versions=evaluation_input.knowledge_versions,
        input_digests=evaluation_input.input_digests + ((OBSERVATION_PRESENCE_KEY, presence),),
        finding_ids=tuple(item.finding_id for item in findings), unevaluated_conditions=unevaluated,
        diagnostics=tuple(sorted(collector.diagnostics)))
    return MonitoringEvaluation(findings=findings, report=report)


__all__ = ["ABSENCE_FLAGS", "ACCEPTED_STATES", "AuthorityFailureSnapshot", "BROKEN_CHAIN_STATES", "CLOSED_STATES",
           "DIVERGENCE_FLAGS", "ENGINE_EMITS_OBSERVATIONS_ONLY", "INACTIVE_ENDPOINT_STATES",
           "MONITORING_ENGINE_VERSION", "NO_CHANNEL_SUPPLIED", "OBSERVATION_CHANNEL_CONDITIONS",
           "OBSERVATION_PRESENCE_KEY", "KnowledgeDriftSnapshot", "MonitoringEngineError", "MonitoringEvaluation",
           "MonitoringEvaluationInput", "ProposalSnapshot", "RelationProposalSnapshot", "RelationSnapshot",
           "SubjectAvailability", "ThemeSnapshot", "evaluate_monitoring"]
