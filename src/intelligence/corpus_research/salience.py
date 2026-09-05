"""Versioned salience（Phase 3.8 §7）。何が強調されたかの決定的表現。**語数では決めない**。

signals: headline（P1 ●ボレット）/ section placement（P1 > P2 > アイデア）/ first occurrence /
repetition（上限あり）/ dedicated heading（【】見出し）/ explicit outlook linkage / explicit why linkage。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Mapping, Sequence

from ..corpus.page_sections import GLOBAL_STRATEGY, P1_JP_OUTLOOK
from ..corpus.structured_record import OUTLOOK
from .categories import OTHER, UNKNOWN, categorize
from .links import AnalyticalLink, EXPLICIT_CONNECTIVE
from .statements import Statement

SALIENCE_VERSION = "1.0.0"

WEIGHTS: Dict[str, Decimal] = {
    "headline": Decimal("3.0"),
    "section_p1": Decimal("2.0"),
    "section_p2": Decimal("1.0"),
    "first_occurrence_rank1": Decimal("1.5"),
    "first_occurrence_rank2": Decimal("1.0"),
    "first_occurrence_rank3": Decimal("0.5"),
    "repetition_step": Decimal("1.0"),      # 2 文目以降 1 文ごと（上限 2）
    "repetition_cap": Decimal("2.0"),
    "dedicated_heading": Decimal("2.0"),
    "outlook_linked": Decimal("1.5"),
    "why_linked": Decimal("1.5"),
}


@dataclass(frozen=True)
class CategorySalience:
    category: str
    score: Decimal
    rank: int
    signals: Mapping[str, object]
    observation_ids: tuple

    def as_dict(self) -> Dict[str, object]:
        return {"category": self.category, "score": str(self.score), "rank": self.rank,
                "signals": dict(self.signals), "observation_ids": list(self.observation_ids)}


def salience_profile(statements: Sequence[Statement], links: Sequence[AnalyticalLink],
                     main_theme_text: str = "") -> List[CategorySalience]:
    per: Dict[str, Dict[str, object]] = {}
    by_obs = {s.observation_id: s for s in statements if s.observation_id}
    outlook_sources = {l.source_observation_id for l in links if l.link_type.endswith("TO_OUTLOOK")}
    why_sources = {l.source_observation_id for l in links if l.basis == EXPLICIT_CONNECTIVE}
    heading_categories = set(categorize(main_theme_text)) if main_theme_text else set()
    first_seen: Dict[str, int] = {}
    for st in statements:
        for cat in st.categories:
            d = per.setdefault(cat, {"headline": False, "section": 9, "count": 0, "outlook_linked": False,
                                     "why_linked": False, "dedicated_heading": cat in heading_categories,
                                     "obs": []})
            d["count"] = int(d["count"]) + 1
            d["obs"].append(st.observation_id)
            if st.headline:
                d["headline"] = True
            sec = 1 if st.section == P1_JP_OUTLOOK else 2 if st.section == GLOBAL_STRATEGY else 3
            d["section"] = min(int(d["section"]), sec)
            if st.level == OUTLOOK or st.observation_id in outlook_sources:
                d["outlook_linked"] = True
            if st.observation_id in why_sources:
                d["why_linked"] = True
            first_seen.setdefault(cat, st.order)
    ordered_first = sorted(first_seen.items(), key=lambda kv: kv[1])
    first_rank = {cat: i + 1 for i, (cat, _) in enumerate(ordered_first)}
    out: List[CategorySalience] = []
    for cat, d in per.items():
        if cat in (OTHER, UNKNOWN):
            continue
        score = Decimal("0")
        signals: Dict[str, object] = {}
        if d["headline"]:
            score += WEIGHTS["headline"]
            signals["headline"] = True
        if d["section"] == 1:
            score += WEIGHTS["section_p1"]
        elif d["section"] == 2:
            score += WEIGHTS["section_p2"]
        signals["section_placement"] = int(d["section"])
        fr = first_rank.get(cat, 99)
        signals["first_occurrence_rank"] = fr
        if fr == 1:
            score += WEIGHTS["first_occurrence_rank1"]
        elif fr == 2:
            score += WEIGHTS["first_occurrence_rank2"]
        elif fr == 3:
            score += WEIGHTS["first_occurrence_rank3"]
        rep = max(0, int(d["count"]) - 1)
        signals["repetition"] = int(d["count"])
        score += min(WEIGHTS["repetition_cap"], WEIGHTS["repetition_step"] * rep)
        if d["dedicated_heading"]:
            score += WEIGHTS["dedicated_heading"]
            signals["dedicated_heading"] = True
        if d["outlook_linked"]:
            score += WEIGHTS["outlook_linked"]
            signals["outlook_linked"] = True
        if d["why_linked"]:
            score += WEIGHTS["why_linked"]
            signals["why_linked"] = True
        out.append(CategorySalience(category=cat, score=score, rank=0, signals=signals,
                                    observation_ids=tuple(x for x in d["obs"] if x)))
    out.sort(key=lambda c: (-c.score, c.category))
    return [CategorySalience(c.category, c.score, i + 1, c.signals, c.observation_ids) for i, c in enumerate(out)]
