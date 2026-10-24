"""Proposal decision resolution（P6-B3）— decision chain の純関数解決と derived proposal status。

- decision は `supersedes_decision_id` で chain を成す。唯一の terminal → RESOLVED、fork / 複数 start → UNRESOLVED、
  dangling predecessor / cycle / 別 proposal への参照 → INVALID。recorded_at や物理順で勝者を選ばない（P5 / Foundation と同じ）。
- derived status: OPEN / OPEN_DEFERRED / OPEN_UNRESOLVED / ACCEPTED / REJECTED / CLOSED_NOT_DUPLICATE
  （＋ INVALID_DECISION_HISTORY: 構造的に不可能な decision 履歴を「変化なし」に潰さない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .proposal_model import DecisionKind, Proposal, ProposalDecision, ProposalType


class DecisionResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NONE = "NONE"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


class ProposalStatus(str, Enum):
    OPEN = "OPEN"
    OPEN_DEFERRED = "OPEN_DEFERRED"
    OPEN_UNRESOLVED = "OPEN_UNRESOLVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLOSED_NOT_DUPLICATE = "CLOSED_NOT_DUPLICATE"
    INVALID_DECISION_HISTORY = "INVALID_DECISION_HISTORY"


OPEN_STATUSES: Tuple[ProposalStatus, ...] = (ProposalStatus.OPEN, ProposalStatus.OPEN_DEFERRED, ProposalStatus.OPEN_UNRESOLVED)


@dataclass(frozen=True)
class ProposalDecisionResolution:
    proposal_id: str
    status: DecisionResolutionStatus
    active_decision: Optional[ProposalDecision]
    chain: Tuple[str, ...]              # start → terminal（RESOLVED のとき）
    diagnostics: Tuple[str, ...]        # FORK / MULTIPLE_STARTS / DANGLING_PREDECESSOR / WRONG_PROPOSAL_PREDECESSOR / CYCLE


@dataclass(frozen=True)
class OpenProposal:
    proposal_id: str
    proposal_type: ProposalType
    status: ProposalStatus
    active_decision_id: str = ""


def resolve_active_decision(proposal_id: str, decisions: Iterable[ProposalDecision]) -> ProposalDecisionResolution:
    """proposal の decision chain を predecessor graph だけで解決する（時刻・物理順は使わない）。"""
    by_id: Dict[str, ProposalDecision] = {d.decision_id: d for d in decisions}
    mine = {d.decision_id: d for d in by_id.values() if d.proposal_id == proposal_id}
    if not mine:
        return ProposalDecisionResolution(proposal_id, DecisionResolutionStatus.NONE, None, (), ())
    for decision_id in sorted(mine):
        predecessor = mine[decision_id].supersedes_decision_id
        if predecessor and predecessor not in mine:
            code = "WRONG_PROPOSAL_PREDECESSOR" if predecessor in by_id else "DANGLING_PREDECESSOR"
            return ProposalDecisionResolution(proposal_id, DecisionResolutionStatus.INVALID, None, (), (code,))
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
        return ProposalDecisionResolution(proposal_id, DecisionResolutionStatus.INVALID, None, (), ("CYCLE",))
    if diagnostics:
        return ProposalDecisionResolution(proposal_id, DecisionResolutionStatus.UNRESOLVED, None, (), tuple(diagnostics))
    order: List[str] = []
    cursor: Optional[str] = starts[0]
    seen = set()
    while cursor:
        if cursor in seen:
            return ProposalDecisionResolution(proposal_id, DecisionResolutionStatus.INVALID, None, (), ("CYCLE",))
        seen.add(cursor)
        order.append(cursor)
        nxt = children.get(cursor, [])
        cursor = nxt[0] if nxt else None
    if len(order) != len(mine):     # start から辿れない decision がある ＝ cycle（別 component）
        return ProposalDecisionResolution(proposal_id, DecisionResolutionStatus.INVALID, None, (), ("CYCLE",))
    return ProposalDecisionResolution(proposal_id, DecisionResolutionStatus.RESOLVED, mine[order[-1]], tuple(order), ())


def derive_proposal_status(proposal: Proposal, decisions: Iterable[ProposalDecision]) -> ProposalStatus:
    resolution = resolve_active_decision(proposal.proposal_id, decisions)
    if resolution.status is DecisionResolutionStatus.NONE:
        return ProposalStatus.OPEN
    if resolution.status is DecisionResolutionStatus.UNRESOLVED:
        return ProposalStatus.OPEN_UNRESOLVED
    if resolution.status is DecisionResolutionStatus.INVALID:
        return ProposalStatus.INVALID_DECISION_HISTORY
    kind = resolution.active_decision.decision
    if kind is DecisionKind.DEFER:
        return ProposalStatus.OPEN_DEFERRED
    if kind is DecisionKind.ACCEPT:
        return ProposalStatus.ACCEPTED
    if kind is DecisionKind.REJECT:
        return ProposalStatus.REJECTED
    return ProposalStatus.CLOSED_NOT_DUPLICATE          # NOT_DUPLICATE（store が DEDUP_REVIEW だけに許す）


def derive_open_proposals(proposals: Iterable[Proposal], decisions: Sequence[ProposalDecision]) -> Tuple[OpenProposal, ...]:
    """active ACCEPT / REJECT / NOT_DUPLICATE で閉じていない proposal（DEFER と UNRESOLVED は open のまま）。"""
    decisions = tuple(decisions)
    out: List[OpenProposal] = []
    for proposal in sorted(proposals, key=lambda p: p.proposal_id):
        status = derive_proposal_status(proposal, decisions)
        if status in OPEN_STATUSES:
            resolution = resolve_active_decision(proposal.proposal_id, decisions)
            active = resolution.active_decision.decision_id if resolution.active_decision else ""
            out.append(OpenProposal(proposal.proposal_id, proposal.proposal_type, status, active))
    return tuple(out)


__all__ = ["DecisionResolutionStatus", "ProposalStatus", "OPEN_STATUSES", "ProposalDecisionResolution", "OpenProposal",
           "resolve_active_decision", "derive_proposal_status", "derive_open_proposals"]
