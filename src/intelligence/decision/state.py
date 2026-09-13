"""Current-state derivation（Phase 3.9.1）— append-only history から決定的に導く。history は不変。

順序規則: store の sequence（append 順）。pattern ごとの最後の event が current state。
promotion_status は decision state とは別次元（3.9.1 では常に NOT_PROMOTED）。
reopen_eligible は REJECTED の派生属性（人間の REOPENED_FOR_REVIEW decision を待つ。自動では変えない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from .models import NOT_PROMOTED, DecisionRecord
from .policy import ALLOWED_TRANSITIONS, REJECTED


@dataclass(frozen=True)
class CurrentState:
    pattern_id: str
    state: str
    decision_id: str
    sequence: int
    decided_at: str
    actor: str
    actor_type: str
    review_mode: str
    policy_version: str
    previous_state: str
    history_length: int
    promotion_status: str = NOT_PROMOTED
    reopen_eligible: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {"pattern_id": self.pattern_id, "state": self.state, "decision_id": self.decision_id,
                "sequence": self.sequence, "decided_at": self.decided_at, "actor": self.actor,
                "actor_type": self.actor_type, "review_mode": self.review_mode,
                "policy_version": self.policy_version, "previous_state": self.previous_state,
                "history_length": self.history_length, "promotion_status": self.promotion_status,
                "reopen_eligible": self.reopen_eligible}


def derive_current_states(records: Iterable[DecisionRecord]) -> Dict[str, CurrentState]:
    ordered = sorted(records, key=lambda r: r.sequence)
    counts: Dict[str, int] = {}
    last: Dict[str, DecisionRecord] = {}
    for r in ordered:
        counts[r.pattern_id] = counts.get(r.pattern_id, 0) + 1
        last[r.pattern_id] = r
    out: Dict[str, CurrentState] = {}
    for pid in sorted(last):
        r = last[pid]
        out[pid] = CurrentState(
            pattern_id=pid, state=r.decision_type, decision_id=r.decision_id, sequence=r.sequence,
            decided_at=r.decided_at, actor=r.actor, actor_type=r.actor_type, review_mode=r.review_mode,
            policy_version=r.policy_version, previous_state=r.previous_state, history_length=counts[pid],
            promotion_status=NOT_PROMOTED, reopen_eligible=(r.decision_type == REJECTED))
    return out


def current_state_for(records: Iterable[DecisionRecord], pattern_id: str) -> Optional[CurrentState]:
    return derive_current_states(r for r in records if r.pattern_id == pattern_id).get(pattern_id)


def transition_allowed(previous_state: Optional[str], new_state: str) -> bool:
    return new_state in ALLOWED_TRANSITIONS.get(previous_state or None, frozenset())


def allowed_next_states(previous_state: Optional[str]) -> List[str]:
    return sorted(ALLOWED_TRANSITIONS.get(previous_state or None, frozenset()))
