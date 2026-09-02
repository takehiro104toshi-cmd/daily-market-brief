"""WHY model（Phase 3.8 §9）。co-occurrence を causality に変換しない。

EXPLICIT_WHY のみを著者の直接的な理由付け evidence として扱う。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Sequence

from ..corpus.structured_record import ANALYST_INTERPRETATION, OUTLOOK
from .links import CONNECTIVES, EXPLICIT_CONNECTIVE, SAME_PARAGRAPH_SEQUENCE, AnalyticalLink
from .statements import Statement

WHY_VERSION = "1.0.0"

EXPLICIT_WHY = "EXPLICIT_WHY"
IMPLICIT_ASSOCIATION = "IMPLICIT_ASSOCIATION"
NO_WHY = "NO_WHY"
UNKNOWN = "UNKNOWN"
WHY_TYPES = (EXPLICIT_WHY, IMPLICIT_ASSOCIATION, NO_WHY, UNKNOWN)


@dataclass(frozen=True)
class WhyLink:
    why_id: str
    target_observation_id: str
    target_level: str
    evidence_observation_id: str
    why_type: str
    connective: str
    evidence_categories: tuple
    target_categories: tuple
    page: int

    def as_dict(self) -> Dict[str, object]:
        return {"why_id": self.why_id, "target_observation_id": self.target_observation_id,
                "target_level": self.target_level, "evidence_observation_id": self.evidence_observation_id,
                "why_type": self.why_type, "connective": self.connective,
                "evidence_categories": list(self.evidence_categories),
                "target_categories": list(self.target_categories), "page": self.page}


def classify_why(statements: Sequence[Statement], links: Sequence[AnalyticalLink]) -> List[WhyLink]:
    by_obs = {s.observation_id: s for s in statements if s.observation_id}
    incoming: Dict[str, List[AnalyticalLink]] = {}
    for l in links:
        if l.link_type in ("EVIDENCE_TO_INTERPRETATION", "INTERPRETATION_TO_OUTLOOK", "EVIDENCE_TO_OUTLOOK"):
            incoming.setdefault(l.target_observation_id, []).append(l)
    out: List[WhyLink] = []
    for st in statements:
        if st.level not in (OUTLOOK, ANALYST_INTERPRETATION) or not st.observation_id:
            continue
        links_in = incoming.get(st.observation_id, [])
        explicit = [l for l in links_in if l.basis == EXPLICIT_CONNECTIVE]
        implicit = [l for l in links_in if l.basis == SAME_PARAGRAPH_SEQUENCE]
        if explicit:
            chosen, why_type = explicit[0], EXPLICIT_WHY
        elif implicit:
            chosen, why_type = implicit[0], IMPLICIT_ASSOCIATION
        elif CONNECTIVES.search(st.text):
            chosen, why_type = None, UNKNOWN            # 理由語はあるが根拠文を段落内で特定できない
        else:
            chosen, why_type = None, NO_WHY
        src = by_obs.get(chosen.source_observation_id) if chosen else None
        seed = f"{st.observation_id}|{chosen.source_observation_id if chosen else ''}|{why_type}|{WHY_VERSION}"
        out.append(WhyLink(
            why_id="crw_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
            target_observation_id=st.observation_id, target_level=st.level,
            evidence_observation_id=chosen.source_observation_id if chosen else "",
            why_type=why_type, connective=chosen.connective if chosen else "",
            evidence_categories=tuple(src.categories) if src else (),
            target_categories=tuple(st.categories), page=st.page))
    return out


def why_summary(why_links: Sequence[WhyLink]) -> Dict[str, int]:
    out = {t: 0 for t in WHY_TYPES}
    for w in why_links:
        out[w.why_type] = out.get(w.why_type, 0) + 1
    return out
