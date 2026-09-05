"""Executable gates（Phase 3.9.1）— CORPUS_100 formal approval gate / human action / reason。

- formal APPROVED は corpus eligible >= policy.formal_review_min_corpus のときだけ「人間が」作れる。
  それ未満は FORMAL_REVIEW_GATE_NOT_REACHED（SHADOW MODE）。到達しても自動では何も起きない。
- 全 decision は HUMAN actor と非空 reason（policy v1 は保守的に全 state へ適用）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .corpus_state import CorpusState
from .models import ACTOR_HUMAN, MODE_FORMAL, MODE_SHADOW
from .policy import APPROVED, DecisionPolicy

FORMAL_REVIEW_ELIGIBLE = "FORMAL_REVIEW_ELIGIBLE"            # CORPUS_100 到達 = FIRST_FORMAL_DNA_REVIEW_ELIGIBLE
FORMAL_REVIEW_GATE_NOT_REACHED = "FORMAL_REVIEW_GATE_NOT_REACHED"
E_HUMAN_ACTION_REQUIRED = "HUMAN_ACTION_REQUIRED"
E_REASON_REQUIRED = "REASON_REQUIRED"


@dataclass(frozen=True)
class GateResult:
    reached: bool
    code: str
    review_mode: str
    corpus_size: int
    required: int
    corpus_milestone: str
    policy_version: str
    auto_approval: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {"reached": self.reached, "code": self.code, "review_mode": self.review_mode,
                "corpus_size": self.corpus_size, "required": self.required, "corpus_milestone": self.corpus_milestone,
                "policy_version": self.policy_version, "auto_approval": self.auto_approval,
                "meaning": ("human APPROVED is technically eligible; nothing is emitted automatically"
                            if self.reached else "SHADOW MODE: formal APPROVED is blocked")}


def formal_review_gate(corpus: CorpusState, policy: DecisionPolicy) -> GateResult:
    reached = int(corpus.eligible) >= int(policy.formal_review_min_corpus)
    return GateResult(reached=reached, code=FORMAL_REVIEW_ELIGIBLE if reached else FORMAL_REVIEW_GATE_NOT_REACHED,
                      review_mode=MODE_FORMAL if reached else MODE_SHADOW, corpus_size=int(corpus.eligible),
                      required=int(policy.formal_review_min_corpus), corpus_milestone=corpus.milestone,
                      policy_version=policy.policy_version, auto_approval=bool(policy.auto_approval))


def approval_gate_error(decision_type: str, gate: GateResult) -> Optional[str]:
    """APPROVED だけを CORPUS_100 で止める（他 state の制限は frozen policy に無いので発明しない）。"""
    if decision_type == APPROVED and not gate.reached:
        return FORMAL_REVIEW_GATE_NOT_REACHED
    return None


def human_action_error(decision_type: str, actor_type: str, policy: DecisionPolicy) -> Optional[str]:
    if decision_type in policy.human_only_states and actor_type != ACTOR_HUMAN:
        return E_HUMAN_ACTION_REQUIRED
    return None


def reason_error(decision_type: str, reason: str, policy: DecisionPolicy) -> Optional[str]:
    if decision_type in policy.reason_required_states and not str(reason or "").strip():
        return E_REASON_REQUIRED
    return None
