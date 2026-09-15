"""Corpus milestones（Phase 3.7 §16）。usable document 数で判定し、次の milestone までの本数を出す。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

MILESTONE_MEANING: Dict[int, Tuple[str, str]] = {
    10: ("CORPUS_10", "structure validation"),
    30: ("CORPUS_30", "basic pattern validation"),
    50: ("CORPUS_50", "production evaluation minimum"),
    100: ("CORPUS_100", "Compass DNA v2 review target"),
    200: ("CORPUS_200", "regime-aware Compass DNA review target"),
}


@dataclass(frozen=True)
class MilestoneStatus:
    usable_documents: int
    reached: str                  # 到達済み最大 milestone 名 or "NONE"
    reached_threshold: int
    next_milestone: str           # "" if all reached
    next_threshold: int
    documents_needed: int
    milestones: Tuple[Dict[str, object], ...]

    def as_dict(self) -> Dict[str, object]:
        return {"usable_documents": self.usable_documents, "reached": self.reached,
                "reached_threshold": self.reached_threshold,
                "next_milestone": self.next_milestone, "next_threshold": self.next_threshold,
                "documents_needed": self.documents_needed,
                "milestones": list(self.milestones)}


def milestone_name(threshold: int) -> str:
    return MILESTONE_MEANING.get(threshold, (f"CORPUS_{threshold}", ""))[0]


def milestone_status(usable_documents: int,
                     thresholds: Sequence[int] = (10, 30, 50, 100, 200)) -> MilestoneStatus:
    ordered = sorted(int(t) for t in thresholds)
    rows: List[Dict[str, object]] = []
    reached, reached_t = "NONE", 0
    next_name, next_t = "", 0
    for t in ordered:
        name, meaning = MILESTONE_MEANING.get(t, (f"CORPUS_{t}", ""))
        done = usable_documents >= t
        rows.append({"milestone": name, "threshold": t, "meaning": meaning, "reached": done})
        if done:
            reached, reached_t = name, t
        elif not next_name:
            next_name, next_t = name, t
    needed = max(0, next_t - usable_documents) if next_name else 0
    return MilestoneStatus(usable_documents=usable_documents, reached=reached,
                           reached_threshold=reached_t, next_milestone=next_name,
                           next_threshold=next_t, documents_needed=needed,
                           milestones=tuple(rows))
