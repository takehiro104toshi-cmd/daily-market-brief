"""Candidate population（Phase 3.9.5）— 現在の evaluation state から動的に選ぶ。件数は決して固定しない。

primary candidate = 現在の recommendation が APPROVE_RECOMMENDED / REJECT_RECOMMENDED で、formal Decision head が
NONE / KEEP_REVIEWING / REOPENED_FOR_REVIEW のもの。head が APPROVED / REJECTED / SUPERSEDED / RETIRED は decided。
REJECTED は reopen 条件を満たすときだけ別 section（REOPEN_ELIGIBLE）に載る。NOT_READY は除外。
context = candidate の sibling group member（recommendation を問わず）。context は queue から決められない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from ..evaluation.models import APPROVE_RECOMMENDED, NOT_READY, REJECT_RECOMMENDED
from .config import APPROVED, KEEP_REVIEWING, REJECTED, REOPENED_FOR_REVIEW, RETIRED, SUPERSEDED

PRIMARY_RECOMMENDATIONS = (APPROVE_RECOMMENDED, REJECT_RECOMMENDED)
QUEUE_ELIGIBLE_HEADS = ("", KEEP_REVIEWING, REOPENED_FOR_REVIEW)
DECIDED_HEADS = (APPROVED, REJECTED, SUPERSEDED, RETIRED)


@dataclass(frozen=True)
class Population:
    primary: List[str] = field(default_factory=list)          # queue に載る candidate
    decided: List[str] = field(default_factory=list)          # 既に formal decision がある（primary から除く）
    reopen_eligible: List[str] = field(default_factory=list)  # REJECTED かつ material change 検出
    context: List[str] = field(default_factory=list)          # sibling context のみ
    excluded_not_ready: int = 0
    by_recommendation: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"primary": list(self.primary), "decided": list(self.decided),
                "reopen_eligible": list(self.reopen_eligible), "context": list(self.context),
                "excluded_not_ready": self.excluded_not_ready, "by_recommendation": dict(self.by_recommendation),
                "primary_count": len(self.primary), "context_count": len(self.context)}


def select_population(evaluations: Mapping[str, Mapping[str, Any]], decision_states: Mapping[str, str],
                      reopen_flags: Mapping[str, bool], groups: Mapping[str, Sequence[str]],
                      pattern_records: Mapping[str, Mapping[str, Any]]) -> Population:
    from .groups import sibling_key

    primary: List[str] = []
    decided: List[str] = []
    reopen: List[str] = []
    not_ready = 0
    by_rec: Dict[str, int] = {}
    for pid in sorted(evaluations):
        rec = str(evaluations[pid].get("recommendation", ""))
        if rec == NOT_READY:
            not_ready += 1
            continue
        if rec not in PRIMARY_RECOMMENDATIONS:
            continue
        head = str(decision_states.get(pid, ""))
        if head in QUEUE_ELIGIBLE_HEADS:
            primary.append(pid)
            by_rec[rec] = by_rec.get(rec, 0) + 1
        elif head in DECIDED_HEADS:
            decided.append(pid)
    for pid, flag in sorted(reopen_flags.items()):
        if flag and str(decision_states.get(pid, "")) == REJECTED:
            reopen.append(pid)
    context: List[str] = []
    seen = set(primary) | set(reopen)
    for pid in primary + reopen:
        key = sibling_key(dict((pattern_records.get(pid) or {}).get("components") or {}))
        for member in (groups.get(key) or []) if key else []:
            if member not in seen and member in evaluations:
                context.append(member)
                seen.add(member)
    return Population(primary=primary, decided=decided, reopen_eligible=reopen, context=sorted(context),
                      excluded_not_ready=not_ready, by_recommendation=dict(sorted(by_rec.items())))
