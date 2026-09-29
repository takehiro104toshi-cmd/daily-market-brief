"""P6-B5C — relation proposal の decision chain を解く純関数。

- chain は `supersedes_decision_id` の graph だけで解く。`recorded_at` も物理順も勝者を決めない（latest-wins は無い）。
- fork / 複数 start は UNRESOLVED。dangling predecessor / cycle / 別 proposal への参照は INVALID。
- derived status: OPEN / OPEN_DEFERRED / ACCEPTED / REJECTED / OPEN_UNRESOLVED / INVALID_DECISION_HISTORY。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .relation_proposal_model import RelationDecisionKind, RelationProposal, RelationProposalDecision


class DecisionResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NONE = "NONE"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


class RelationProposalStatus(str, Enum):
    OPEN = "OPEN"
    OPEN_DEFERRED = "OPEN_DEFERRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    OPEN_UNRESOLVED = "OPEN_UNRESOLVED"
    INVALID_DECISION_HISTORY = "INVALID_DECISION_HISTORY"


OPEN_STATUSES: Tuple[RelationProposalStatus, ...] = (RelationProposalStatus.OPEN, RelationProposalStatus.OPEN_DEFERRED,
                                                     RelationProposalStatus.OPEN_UNRESOLVED)


@dataclass(frozen=True, kw_only=True)
class RelationDecisionResolution:
    proposal_id: str
    status: DecisionResolutionStatus
    active_decision: Optional[RelationProposalDecision]
    chain: Tuple[str, ...]
    diagnostics: Tuple[str, ...]


def resolve_active_relation_decision(proposal_id: str, decisions: Iterable[RelationProposalDecision]
                                     ) -> RelationDecisionResolution:
    by_id: Dict[str, RelationProposalDecision] = {d.decision_id: d for d in decisions}
    mine = {k: v for k, v in by_id.items() if v.proposal_id == proposal_id}
    if not mine:
        return RelationDecisionResolution(proposal_id=proposal_id, status=DecisionResolutionStatus.NONE,
                                          active_decision=None, chain=(), diagnostics=())
    for decision_id in sorted(mine):
        predecessor = mine[decision_id].supersedes_decision_id
        if predecessor and predecessor not in mine:
            code = "WRONG_PROPOSAL_PREDECESSOR" if predecessor in by_id else "DANGLING_PREDECESSOR"
            return RelationDecisionResolution(proposal_id=proposal_id, status=DecisionResolutionStatus.INVALID,
                                              active_decision=None, chain=(), diagnostics=(code,))
    children: Dict[str, List[str]] = {}
    starts: List[str] = []
    for decision_id in sorted(mine):
        predecessor = mine[decision_id].supersedes_decision_id
        if predecessor == "":
            starts.append(decision_id)
        else:
            children.setdefault(predecessor, []).append(decision_id)
    diagnostics: List[str] = []
    if any(len(v) > 1 for v in children.values()):
        diagnostics.append("FORK")
    if len(starts) > 1:
        diagnostics.append("MULTIPLE_STARTS")
    if not starts:
        return RelationDecisionResolution(proposal_id=proposal_id, status=DecisionResolutionStatus.INVALID,
                                          active_decision=None, chain=(), diagnostics=("CYCLE",))
    if diagnostics:
        return RelationDecisionResolution(proposal_id=proposal_id, status=DecisionResolutionStatus.UNRESOLVED,
                                          active_decision=None, chain=(), diagnostics=tuple(diagnostics))
    order: List[str] = []
    seen = set()
    cursor: Optional[str] = starts[0]
    while cursor:
        if cursor in seen:
            return RelationDecisionResolution(proposal_id=proposal_id, status=DecisionResolutionStatus.INVALID,
                                              active_decision=None, chain=(), diagnostics=("CYCLE",))
        seen.add(cursor)
        order.append(cursor)
        following = children.get(cursor, [])
        cursor = following[0] if following else None
    if len(order) != len(mine):
        return RelationDecisionResolution(proposal_id=proposal_id, status=DecisionResolutionStatus.INVALID,
                                          active_decision=None, chain=(), diagnostics=("CYCLE",))
    return RelationDecisionResolution(proposal_id=proposal_id, status=DecisionResolutionStatus.RESOLVED,
                                      active_decision=mine[order[-1]], chain=tuple(order), diagnostics=())


def derive_relation_proposal_status(proposal: RelationProposal, decisions: Iterable[RelationProposalDecision]
                                    ) -> RelationProposalStatus:
    resolution = resolve_active_relation_decision(proposal.proposal_id, decisions)
    if resolution.status is DecisionResolutionStatus.NONE:
        return RelationProposalStatus.OPEN
    if resolution.status is DecisionResolutionStatus.UNRESOLVED:
        return RelationProposalStatus.OPEN_UNRESOLVED
    if resolution.status is DecisionResolutionStatus.INVALID:
        return RelationProposalStatus.INVALID_DECISION_HISTORY
    kind = resolution.active_decision.decision
    if kind is RelationDecisionKind.DEFER:
        return RelationProposalStatus.OPEN_DEFERRED
    if kind is RelationDecisionKind.ACCEPT:
        return RelationProposalStatus.ACCEPTED
    return RelationProposalStatus.REJECTED


def open_relation_proposals(proposals: Iterable[RelationProposal], decisions: Sequence[RelationProposalDecision]
                            ) -> Tuple[Tuple[str, RelationProposalStatus], ...]:
    """まだ閉じていない候補（ACCEPT / REJECT で閉じていないもの）。順位付けではない。"""
    decisions = tuple(decisions)
    rows = [(p.proposal_id, derive_relation_proposal_status(p, decisions)) for p in proposals]
    return tuple(sorted((pid, status) for pid, status in rows if status in OPEN_STATUSES))


__all__ = ["DecisionResolutionStatus", "OPEN_STATUSES", "RelationDecisionResolution", "RelationProposalStatus",
           "derive_relation_proposal_status", "open_relation_proposals", "resolve_active_relation_decision"]
