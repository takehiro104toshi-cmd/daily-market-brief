"""P6-B6D — 上流の resolved / derived state を B6C の `MonitoringEvaluationInput` へ写す明示 adapter（純関数）。

B6C limitation #1（「snapshot の構築は engine の外にある」）をここで閉じる。**写像だけを行い、意味論を作らない。**
`CONTESTED` / `STALE` / 端点状態 / chain 解決はいずれも上流（Foundation / B2 / B3 / B5）の結果をそのまま写し、
本 module では再計算しない。

silent coercion の禁止（B6D §10）。以下はすべて「条件が偽」ではなく **評価不能** として engine へ渡す:

- `None` を false にしない。
- `UNRESOLVED` / `INVALID_HISTORY` を「存在しない」にしない。
- store の破損を「条件が無い」にしない。
- 未知 root（`UNKNOWN_ROOT` / `NO_STATE`）を「不活性」にしない。

engine 側はそれを `unevaluated_conditions` ＋ INTEGRITY finding ＋ run status `PARTIAL` に変える。

vocabulary 写像（意味の変換ではなく語彙の対応。contract doc の表と 1:1）:

- Foundation / B5 の `INVALID_HISTORY` は B6C の chain 語彙では `INVALID`。
- B2 の evidence flag `CONTESTED` / `INVALIDATION_EVIDENCE_PRESENT` は B6C の evidence role 語彙で
  `CONTRADICTS` / `INVALIDATES`。role を visible attachment から数え直さない。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..themes.model import canonical_json
from ..themes.resolver import ResolutionStatus, ThemeResolution
from .lifecycle_model import (EvidenceConditionFlag, EvidenceConditionStatus, GovernanceLifecycleState,
                              LifecyclePolicy, LifecycleViewStatus, ThemeLifecycleView)
from .monitoring_engine import (OBSERVATION_CHANNEL_CONDITIONS, AuthorityFailureSnapshot, KnowledgeDriftSnapshot,
                                MonitoringEvaluationInput, ProposalSnapshot, RelationProposalSnapshot,
                                RelationSnapshot, SubjectAvailability, ThemeSnapshot)
from .monitoring_model import MAX_KEY_LEN, MAX_REF_LEN
from .proposal_resolution import DecisionResolutionStatus, ProposalStatus
from .relation_proposal_resolution import RelationProposalStatus
from .relation_resolution import (EdgeState, ExcludedEdge, RelationResolutionStatus, ResolvedRelation, UnresolvedEdge)

MONITORING_ADAPTER_VERSION = "theme_monitoring_adapter:0.1.0"
DIGEST_PREFIX = "thmin"
LOCATOR_PREFIX = "thmloc"
#: adapter は写すだけで判定しない（contract / test で凍結する文言）
ADAPTER_MAPS_ONLY = "the adapter maps upstream results and never decides a condition"

#: authority 名（digest key と AUTHORITY_STATE_UNUSABLE の facts に現れる安定 token）
AUTHORITY_THEMES = "theme_observations"
AUTHORITY_PROPOSALS = "theme_proposals"
AUTHORITY_RELATIONS = "theme_relations"
AUTHORITY_RELATION_PROPOSALS = "theme_relation_proposals"

#: Foundation resolution の失敗をそのまま failure_class として運ぶ（新しい名前を作らない）
RESOLUTION_FAILURE_CLASS: Mapping[ResolutionStatus, str] = {
    ResolutionStatus.NO_STATE: "NO_STATE_AT_CUTOFF",
    ResolutionStatus.UNRESOLVED: "UNRESOLVED",
    ResolutionStatus.INVALID_HISTORY: "INVALID_HISTORY",
    ResolutionStatus.STORE_CORRUPTION: "STORE_CORRUPTION",
}
#: B5 の解決失敗 → B6C の chain 語彙（`BROKEN_CHAIN_STATES`）
CHAIN_STATUS_TOKENS: Mapping[RelationResolutionStatus, str] = {
    RelationResolutionStatus.UNRESOLVED: "UNRESOLVED",
    RelationResolutionStatus.INVALID_HISTORY: "INVALID",
}
#: B3 / B5C の decision chain 状態 → B6C の chain 語彙（RESOLVED / NONE は健全なので写さない）
BROKEN_DECISION_STATUSES: Tuple[DecisionResolutionStatus, ...] = (DecisionResolutionStatus.UNRESOLVED,
                                                                  DecisionResolutionStatus.INVALID)
#: B2 の evidence flag → B6C の evidence role 語彙
ROLE_BY_FLAG: Tuple[Tuple[EvidenceConditionFlag, str], ...] = (
    (EvidenceConditionFlag.CONTESTED, "CONTRADICTS"),
    (EvidenceConditionFlag.INVALIDATION_EVIDENCE_PRESENT, "INVALIDATES"),
)
CONTESTED_ROLE = "CONTRADICTS"
#: 撤回済み edge に生きた提案が乗っている、という観測の token
RETRACTED_CONFLICT_TOKEN = "OPEN_PROPOSAL_ON_RETRACTED_EDGE"
#: proposal status のうち decision chain が解けておらず「今 open か」を答えられないもの
UNUSABLE_RELATION_PROPOSAL_STATUSES: Tuple[RelationProposalStatus, ...] = (
    RelationProposalStatus.OPEN_UNRESOLVED, RelationProposalStatus.INVALID_DECISION_HISTORY)
#: 生きている relation proposal（撤回済み edge との衝突を見る対象）
LIVE_RELATION_PROPOSAL_STATUSES: Tuple[RelationProposalStatus, ...] = (RelationProposalStatus.OPEN,
                                                                       RelationProposalStatus.OPEN_DEFERRED)
EDGE_KEY_SEGMENTS_FOR_PROPOSAL = 3          # source | target | relation_type（assertion_class は受理時に決まる）
#: B6B が subject_ref / facts の値へ課す token 語彙（B6B は凍結。ここでは満たすかどうかを**先に**判定する）
TOKEN_PATTERN = "^[A-Za-z0-9][A-Za-z0-9_:.\\-|]*$"
_TOKEN_RE = re.compile(TOKEN_PATTERN)


class MonitoringAdapterError(ValueError):
    """fail closed。detail に本文・秘密値・machine path を入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise MonitoringAdapterError(code, detail)


def _bounded(value: str, limit: int = MAX_REF_LEN) -> bool:
    """B6B の token 語彙と bound を先に確かめる（engine の内部で落とさない）。"""
    return isinstance(value, str) and len(value) <= limit and bool(_TOKEN_RE.match(value))


def _locator(value: str) -> str:
    """bound を超える識別子は安定 digest に畳む。**捨てない**（無音の欠落を作らない）。"""
    return value if _bounded(value) else content_id(LOCATOR_PREFIX, str(value))


def freshness_policy_token(policy: LifecyclePolicy) -> str:
    """B2 が所有する freshness 閾値の version token。B6 は閾値そのものを持たない。"""
    _require(isinstance(policy, LifecyclePolicy), "INVALID_TYPE", "policy must be a LifecyclePolicy")
    return f"{policy.schema_version}|{policy.stale_after_days}"


# ---------------------------------------------------------------- 呼び出し側が渡す観測（B6D では導出できない channel）


#: 観測 channel の名前（engine の依存表が source of truth）
OBSERVATION_CHANNELS: Tuple[str, ...] = tuple(sorted(OBSERVATION_CHANNEL_CONDITIONS))
OBSERVATION_BINDING_PREFIX = "observation:"


def _canonical_channel(values: Mapping[str, object]) -> Dict[str, object]:
    """channel の内容を物理順に依らない形へ（key は canonical_json が、列はここで並べ替える）。"""
    return {str(key): sorted(set(value)) if isinstance(value, (tuple, list)) else value
            for key, value in values.items()}


@dataclass(frozen=True, kw_only=True)
class MonitoringObservations:
    """frozen な上流 view からは cutoff 1 点で導けない観測。**未供給は「無かった」ではない**。

    各 channel は 3 状態を持つ（P6-B6R1）:

    - `None`（既定）: **未供給**。依存する condition は評価不能であり、run は `PARTIAL` になる。
    - 空の mapping `{}`: **空で供給**（該当が無いことを確かめた）。評価可能。
    - 非空の mapping: 供給。評価可能。
    """

    arrived_attachment_keys: Optional[Mapping[str, Tuple[str, ...]]] = None
    semantic_revision_observation_ids: Optional[Mapping[str, str]] = None
    discovery_outcome_tokens: Optional[Mapping[str, str]] = None

    def __post_init__(self) -> None:
        for name in OBSERVATION_CHANNELS:
            value = getattr(self, name)
            _require(value is None or isinstance(value, Mapping), "INVALID_TYPE",
                     f"{name} is either not supplied (None) or a mapping")

    def supplied_channels(self) -> Tuple[str, ...]:
        return tuple(name for name in OBSERVATION_CHANNELS if getattr(self, name) is not None)

    def missing_channels(self) -> Tuple[str, ...]:
        return tuple(name for name in OBSERVATION_CHANNELS if getattr(self, name) is None)

    def channel_bindings(self) -> Tuple[Tuple[str, str], ...]:
        """供給された channel の内容 digest（空供給も digest を持つ。未供給は束縛せず、engine が presence を束縛する）。"""
        return tuple((OBSERVATION_BINDING_PREFIX + name,
                      content_id(DIGEST_PREFIX, canonical_json(_canonical_channel(getattr(self, name)))))
                     for name in self.supplied_channels())


# ---------------------------------------------------------------- Theme


def theme_failure_snapshot(root_id: str, failure_class: str) -> ThemeSnapshot:
    """読めた／解けた とは言えない Theme。条件を偽にせず、評価不能として渡す。"""
    return ThemeSnapshot(theme_root_id=_locator(root_id), availability=SubjectAvailability.UNAVAILABLE,
                         authority_name=AUTHORITY_THEMES, failure_class=failure_class,
                         locator_token=_locator(root_id))


def theme_snapshot(resolution: ThemeResolution, view: Optional[ThemeLifecycleView], *,
                   arrived_attachment_keys: Sequence[str] = (), semantic_revision_observation_id: str = "",
                   policy_token: str = "") -> ThemeSnapshot:
    """Foundation resolution ＋ B2 lifecycle view → `ThemeSnapshot`。flag も governance 状態も再計算しない。"""
    _require(isinstance(resolution, ThemeResolution), "INVALID_TYPE", "resolution must be a ThemeResolution")
    root = resolution.root_id
    failure = RESOLUTION_FAILURE_CLASS.get(resolution.status)
    if failure is not None:
        return theme_failure_snapshot(root, failure)
    if view is None:
        return theme_failure_snapshot(root, "LIFECYCLE_VIEW_MISSING")
    _require(isinstance(view, ThemeLifecycleView), "INVALID_TYPE", "view must be a ThemeLifecycleView")
    if view.status is LifecycleViewStatus.UNAVAILABLE:
        return theme_failure_snapshot(root, "LIFECYCLE_UNAVAILABLE")
    if view.governance.state is GovernanceLifecycleState.UNRESOLVED:
        return theme_failure_snapshot(root, "GOVERNANCE_UNRESOLVED")
    if view.governance.state is GovernanceLifecycleState.NOT_AVAILABLE:
        return theme_failure_snapshot(root, "GOVERNANCE_NOT_AVAILABLE")
    if view.evidence.status is not EvidenceConditionStatus.EVALUATED:
        return theme_failure_snapshot(root, f"EVIDENCE_{view.evidence.status.value}")
    if not _bounded(root):
        return theme_failure_snapshot(root, "SUBJECT_REF_TOO_LONG")
    flags = tuple(flag.value for flag in view.evidence.flags)
    roles = tuple(role for flag, role in ROLE_BY_FLAG if flag in view.evidence.flags)
    keys = tuple(sorted({_locator(key) for key in arrived_attachment_keys}))
    return ThemeSnapshot(theme_root_id=root, governance_state=view.governance.state.value,
                         evidence_flags=tuple(sorted(flags)), evidence_roles_present=roles,
                         arrived_attachment_keys=keys,
                         semantic_revision_observation_id=(semantic_revision_observation_id
                                                           if _bounded(semantic_revision_observation_id) else ""),
                         freshness_policy_token=policy_token)


# ---------------------------------------------------------------- proposal


def proposal_snapshot(proposal_id: str, *, status: Optional[ProposalStatus], created_at: Optional[datetime],
                      decision_status: DecisionResolutionStatus = DecisionResolutionStatus.NONE,
                      decision_diagnostic: str = "", discovery_outcome_token: str = "") -> ProposalSnapshot:
    """B3 の derived status と decision chain 状態をそのまま写す。status が無いことを「条件が偽」にしない。"""
    if status is None or not _bounded(proposal_id):
        return ProposalSnapshot(proposal_id=_locator(proposal_id), availability=SubjectAvailability.UNAVAILABLE,
                                authority_name=AUTHORITY_PROPOSALS,
                                failure_class="PROPOSAL_STATUS_UNAVAILABLE" if status is None
                                else "SUBJECT_REF_TOO_LONG",
                                locator_token=_locator(proposal_id))
    chain_status = decision_status.value if decision_status in BROKEN_DECISION_STATUSES else ""
    diagnostic = decision_diagnostic if chain_status and _bounded(decision_diagnostic, MAX_KEY_LEN) else ""
    return ProposalSnapshot(proposal_id=proposal_id, proposal_status=status.value, created_at=created_at,
                            decision_chain_status=chain_status, decision_chain_diagnostic=diagnostic,
                            discovery_outcome_token=(discovery_outcome_token
                                                     if _bounded(discovery_outcome_token, MAX_KEY_LEN) else ""))


def relation_proposal_snapshot(proposal_id: str, *, status: Optional[RelationProposalStatus], edge_key: str = "",
                               conflict_token: str = "") -> RelationProposalSnapshot:
    """B5C の derived status を写す。chain が解けていない提案は「衝突なし」にせず評価不能にする。"""
    if status is None or not _bounded(proposal_id):
        failure = "RELATION_PROPOSAL_STATUS_UNAVAILABLE" if status is None else "SUBJECT_REF_TOO_LONG"
    elif status in UNUSABLE_RELATION_PROPOSAL_STATUSES:
        failure = f"DECISION_CHAIN_{status.value}"
    else:
        failure = ""
    if failure:
        return RelationProposalSnapshot(relation_proposal_id=_locator(proposal_id), edge_key="",
                                        availability=SubjectAvailability.UNAVAILABLE,
                                        authority_name=AUTHORITY_RELATION_PROPOSALS, failure_class=failure,
                                        locator_token=_locator(proposal_id))
    return RelationProposalSnapshot(relation_proposal_id=proposal_id, edge_key=edge_key if _bounded(edge_key) else "",
                                    conflict_token=conflict_token if conflict_token and _bounded(edge_key) else "")


def edge_prefix(source_theme_root_id: str, target_theme_root_id: str, relation_type_value: str) -> str:
    """relation proposal が指す辺の識別可能な部分（assertion_class / attribution は受理時に決まる）。"""
    return "|".join((source_theme_root_id, target_theme_root_id, relation_type_value))


def retracted_edge_prefixes(edges: Iterable[ResolvedRelation]) -> Dict[str, Tuple[str, ...]]:
    """撤回済み辺を「提案と照合できる接頭辞」で引けるようにする（機械的な join のみ）。"""
    grouped: Dict[str, list] = {}
    for edge in edges:
        if edge.edge_state is not EdgeState.RETRACTED:
            continue
        prefix = edge_prefix(edge.source_theme_root_id, edge.target_theme_root_id, edge.relation_type.value)
        grouped.setdefault(prefix, []).append(edge.edge_key)
    return {prefix: tuple(sorted(keys)) for prefix, keys in grouped.items()}


# ---------------------------------------------------------------- relation


def contested_roots(themes: Iterable[ThemeSnapshot]) -> Tuple[str, ...]:
    """CONTRADICTS を持つと B2 が言った root（adapter は数え直さない）。"""
    return tuple(sorted({snapshot.theme_root_id for snapshot in themes
                         if snapshot.availability is SubjectAvailability.AVAILABLE
                         and CONTESTED_ROLE in snapshot.evidence_roles_present}))


def relation_snapshot(edge: ResolvedRelation, *, contested: Sequence[str] = ()) -> RelationSnapshot:
    """B5 の resolution をそのまま写す。端点も edge 状態も再計算しない。"""
    _require(isinstance(edge, ResolvedRelation), "INVALID_TYPE", "edge must be a ResolvedRelation")
    if not _bounded(edge.edge_key):
        return RelationSnapshot(edge_key=_locator(edge.edge_key), availability=SubjectAvailability.UNAVAILABLE,
                                authority_name=AUTHORITY_RELATIONS, failure_class="SUBJECT_REF_TOO_LONG",
                                locator_token=_locator(edge.edge_key))
    contested_set = set(contested)
    endpoint = next((root for root in (edge.source_theme_root_id, edge.target_theme_root_id)
                     if root in contested_set), "")
    return RelationSnapshot(edge_key=edge.edge_key, edge_state=edge.edge_state.value,
                            assertion_class=edge.assertion_class.value,
                            source_endpoint_state=edge.source_endpoint.value,
                            target_endpoint_state=edge.target_endpoint.value,
                            contested_theme_root_id=endpoint, contested_role=CONTESTED_ROLE if endpoint else "")


def unresolved_relation_snapshot(edge: UnresolvedEdge) -> RelationSnapshot:
    """chain が解けなかった辺。`RELATION_GOVERNANCE_CHAIN_UNRESOLVED` の入力として写す。"""
    _require(isinstance(edge, UnresolvedEdge), "INVALID_TYPE", "edge must be an UnresolvedEdge")
    status = CHAIN_STATUS_TOKENS.get(edge.status, "")
    diagnostic = edge.diagnostics[0].split(":")[0] if edge.diagnostics else ""
    if not status or not _bounded(edge.edge_key):
        return RelationSnapshot(edge_key=_locator(edge.edge_key), availability=SubjectAvailability.UNAVAILABLE,
                                authority_name=AUTHORITY_RELATIONS,
                                failure_class="SUBJECT_REF_TOO_LONG" if status else f"EDGE_{edge.status.value}",
                                locator_token=_locator(edge.edge_key))
    return RelationSnapshot(edge_key=edge.edge_key, governance_chain_status=status,
                            governance_chain_diagnostic=diagnostic if _bounded(diagnostic, MAX_KEY_LEN) else "")


def excluded_relation_snapshot(edge: ExcludedEdge) -> RelationSnapshot:
    """端点が cutoff 時点で取れず resolver が除外した辺。**不活性にはしない**（評価不能として渡す）。"""
    _require(isinstance(edge, ExcludedEdge), "INVALID_TYPE", "edge must be an ExcludedEdge")
    return RelationSnapshot(edge_key=_locator(edge.edge_key), availability=SubjectAvailability.UNAVAILABLE,
                            authority_name=AUTHORITY_RELATIONS,
                            failure_class=f"ENDPOINT_{str(edge.reason).split(':')[-1]}",
                            locator_token=_locator(edge.edge_key))


def relation_authority_failure(status: RelationResolutionStatus, *,
                               blocked_condition_ids: Sequence[str] = ()) -> Optional[AuthorityFailureSnapshot]:
    """relation authority 全体が読めない／解けない場合の失敗 snapshot。健全なら None。"""
    if status is RelationResolutionStatus.RESOLVED or status is RelationResolutionStatus.NO_STATE:
        return None
    return AuthorityFailureSnapshot(authority_name=AUTHORITY_RELATIONS, failure_class=status.value,
                                    locator_token="whole_authority",
                                    blocked_condition_ids=tuple(blocked_condition_ids))


def authority_failure(authority_name: str, failure_class: str, *,
                      blocked_condition_ids: Sequence[str] = ()) -> AuthorityFailureSnapshot:
    return AuthorityFailureSnapshot(authority_name=authority_name, failure_class=failure_class,
                                    locator_token="whole_authority",
                                    blocked_condition_ids=tuple(blocked_condition_ids))


def knowledge_drift_snapshot(knowledge_name: str, from_version: str, to_version: str) -> KnowledgeDriftSnapshot:
    return KnowledgeDriftSnapshot(knowledge_name=knowledge_name, from_version=from_version, to_version=to_version)


# ---------------------------------------------------------------- digest / evaluation input


def snapshot_digest(name: str, payload: object) -> Tuple[str, str]:
    """入力の canonical 表現からの決定論的 digest。mtime / inode / 絶対 path / 現在時刻を含めない。"""
    return name, content_id(DIGEST_PREFIX, canonical_json(payload))


def _ordered(items: Iterable[object]) -> Tuple[str, ...]:
    """物理順に依らない canonical 表現（同じ集合なら同じ列）。"""
    return tuple(sorted(canonical_json(item) for item in items))


def build_evaluation_input(*, cutoff: datetime, knowledge_versions: Sequence[Tuple[str, str]] = (),
                           themes: Sequence[ThemeSnapshot] = (), proposals: Sequence[ProposalSnapshot] = (),
                           relations: Sequence[RelationSnapshot] = (),
                           relation_proposals: Sequence[RelationProposalSnapshot] = (),
                           knowledge_drift: Sequence[KnowledgeDriftSnapshot] = (),
                           authority_failures: Sequence[AuthorityFailureSnapshot] = (),
                           observations: Optional[MonitoringObservations] = None
                           ) -> MonitoringEvaluationInput:
    """snapshot 群 ＋ knowledge version から評価入力を組み立て、決定論的な input digest を付ける。

    `observations` を省略すると **全 channel 未供給**として扱う（fail closed）。"""
    seen = observations if observations is not None else MonitoringObservations()
    _require(isinstance(seen, MonitoringObservations), "INVALID_TYPE", "observations must be MonitoringObservations")
    families = ((AUTHORITY_THEMES, themes), (AUTHORITY_PROPOSALS, proposals), (AUTHORITY_RELATIONS, relations),
                (AUTHORITY_RELATION_PROPOSALS, relation_proposals), ("knowledge_drift", knowledge_drift),
                ("authority_failures", authority_failures))
    digests = tuple(snapshot_digest(name, _ordered(items)) for name, items in families if items)
    digests += seen.channel_bindings()
    return MonitoringEvaluationInput(
        cutoff=cutoff, knowledge_versions=tuple(sorted(knowledge_versions)), input_digests=tuple(sorted(digests)),
        themes=tuple(sorted(themes, key=lambda s: s.theme_root_id)),
        proposals=tuple(sorted(proposals, key=lambda s: s.proposal_id)),
        relations=tuple(sorted(relations, key=lambda s: s.edge_key)),
        relation_proposals=tuple(sorted(relation_proposals, key=lambda s: (s.relation_proposal_id, s.edge_key))),
        knowledge_drift=tuple(sorted(knowledge_drift, key=lambda s: s.knowledge_name)),
        authority_failures=tuple(sorted(authority_failures,
                                        key=lambda s: (s.authority_name, s.failure_class, s.locator_token))),
        supplied_observation_channels=seen.supplied_channels())


__all__ = ["ADAPTER_MAPS_ONLY", "OBSERVATION_BINDING_PREFIX", "OBSERVATION_CHANNELS", "TOKEN_PATTERN", "AUTHORITY_PROPOSALS", "AUTHORITY_RELATIONS", "AUTHORITY_RELATION_PROPOSALS",
           "AUTHORITY_THEMES", "BROKEN_DECISION_STATUSES", "CHAIN_STATUS_TOKENS", "CONTESTED_ROLE", "DIGEST_PREFIX",
           "LIVE_RELATION_PROPOSAL_STATUSES", "LOCATOR_PREFIX", "MONITORING_ADAPTER_VERSION",
           "MonitoringAdapterError", "MonitoringObservations", "RESOLUTION_FAILURE_CLASS",
           "RETRACTED_CONFLICT_TOKEN", "ROLE_BY_FLAG", "UNUSABLE_RELATION_PROPOSAL_STATUSES", "authority_failure",
           "build_evaluation_input", "contested_roots", "edge_prefix", "excluded_relation_snapshot",
           "freshness_policy_token", "knowledge_drift_snapshot", "proposal_snapshot", "relation_authority_failure",
           "relation_proposal_snapshot", "relation_snapshot", "retracted_edge_prefixes", "snapshot_digest",
           "theme_failure_snapshot", "theme_snapshot", "unresolved_relation_snapshot"]
