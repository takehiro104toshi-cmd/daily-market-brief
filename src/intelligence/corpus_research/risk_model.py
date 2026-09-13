"""Risk model（Phase 3.8 §11）。explicit risk / counterargument / invalidation / uncertainty / watch item を分離。
否定的な語をすべて risk にしない（NOT_RISK を許す）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

from ..corpus.structured_record import RISK
from .statements import Statement

RISK_VERSION = "1.0.0"

EXPLICIT_RISK = "EXPLICIT_RISK"
COUNTERARGUMENT = "COUNTERARGUMENT"
INVALIDATION_CONDITION = "INVALIDATION_CONDITION"
UNCERTAINTY = "UNCERTAINTY"
WATCH_ITEM = "WATCH_ITEM"
NOT_RISK = "NOT_RISK"
RISK_TYPES = (EXPLICIT_RISK, COUNTERARGUMENT, INVALIDATION_CONDITION, UNCERTAINTY, WATCH_ITEM, NOT_RISK)

_INVALID_COND = re.compile(r"となれば|場合|次第|崩れ|割り込|下回れば|上回れば|限り")
_INVALID_NEG = re.compile(r"下落|リスク|警戒|崩れ|反落|調整|後退|悪化|逆風")
_EXPLICIT = re.compile(r"リスク|警戒|懸念|下振れ|悪材料|懸念材料")
_COUNTER = re.compile(r"もっとも|他方|一方で|ただし|とはいえ|しかし")
_UNCERT = re.compile(r"不透明|不確実|見極め|読みにくい|流動的")
_WATCH = re.compile(r"注目|焦点|動向")


@dataclass(frozen=True)
class RiskItem:
    observation_id: str
    risk_type: str
    category: str
    page: int
    artifact_id: str
    confidence_ladder: object
    categories: tuple

    def as_dict(self) -> Dict[str, object]:
        return {"observation_id": self.observation_id, "risk_type": self.risk_type, "category": self.category,
                "page": self.page, "artifact_id": self.artifact_id,
                "confidence_ladder": self.confidence_ladder, "categories": list(self.categories)}


def classify_risk(text: str) -> str:
    if _INVALID_COND.search(text) and _INVALID_NEG.search(text):
        return INVALIDATION_CONDITION
    if _EXPLICIT.search(text):
        return EXPLICIT_RISK
    if _COUNTER.search(text):
        return COUNTERARGUMENT
    if _UNCERT.search(text):
        return UNCERTAINTY
    if _WATCH.search(text):
        return WATCH_ITEM
    return NOT_RISK


def extract_risk(statements: Sequence[Statement]) -> List[RiskItem]:
    out: List[RiskItem] = []
    for st in statements:
        if not st.observation_id:
            continue
        is_watch = "watch_items" in st.corpus_categories
        if st.level != RISK and not is_watch:
            continue
        rtype = classify_risk(st.text)
        if st.level != RISK and rtype not in (WATCH_ITEM, UNCERTAINTY):
            rtype = WATCH_ITEM if is_watch else NOT_RISK
        out.append(RiskItem(observation_id=st.observation_id, risk_type=rtype,
                            category=st.primary_category, page=st.page, artifact_id=st.artifact_id,
                            confidence_ladder=st.ladder, categories=tuple(st.categories)))
    return out


def risk_summary(items: Sequence[RiskItem]) -> Dict[str, object]:
    counts = {t: 0 for t in RISK_TYPES}
    for i in items:
        counts[i.risk_type] = counts.get(i.risk_type, 0) + 1
    primary = next((i for i in items if i.risk_type in (EXPLICIT_RISK, INVALIDATION_CONDITION, COUNTERARGUMENT)), None)
    return {"counts": counts, "primary_type": primary.risk_type if primary else "NONE",
            "primary_observation_id": primary.observation_id if primary else "",
            "primary_category": primary.category if primary else ""}
