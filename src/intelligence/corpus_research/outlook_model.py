"""Outlook model（Phase 3.8 §10）。direction / horizon / confidence / target / conditions / caveat。

controlled vocabulary。horizon は明示されていなければ NOT_STATED（捏造しない）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

from ..corpus.page_sections import GLOBAL_STRATEGY, P1_JP_OUTLOOK
from ..corpus.structured_record import OUTLOOK
from .categories import FX, JAPAN_EQUITY, JAPAN_RATES, SECTOR, THEME, US_EQUITY, US_RATES
from .statements import Statement, by_block

OUTLOOK_VERSION = "1.0.0"

UP = "UP"
DOWN = "DOWN"
RANGE = "RANGE"
MIXED = "MIXED"
UNCERTAIN = "UNCERTAIN"
NOT_STATED = "NOT_STATED"
DIRECTIONS = (UP, DOWN, RANGE, MIXED, UNCERTAIN, NOT_STATED)

H_INTRADAY = "INTRADAY"
H_1D = "1D"
H_1W = "1W"
H_SHORT = "SHORT_TERM"
H_MEDIUM = "MEDIUM"
H_LONG = "LONG"
H_NOT_STATED = "NOT_STATED"
HORIZONS = (H_INTRADAY, H_1D, H_1W, H_SHORT, H_MEDIUM, H_LONG, H_NOT_STATED)

_UP = re.compile(r"上昇|堅調|底堅|反発|買い優勢|買いが先行|高い|続伸|強含|上値追い|回復|買われ|上向|追い風")
_DOWN = re.compile(r"下落|反落|軟調|利食い優勢|売り優勢|調整|続落|下押し|弱含|安い|売られ|下向|逆風|重し")
_RANGE = re.compile(r"レンジ|もみ合い|横ばい|狭い|一進一退|方向感に乏し")
_MIXED = re.compile(r"まちまち|強弱|方向感|まだら")
_UNCERTAIN = re.compile(r"不透明|見極め|流動的|読みにくい|不確実")
_HORIZON = (
    (H_INTRADAY, re.compile(r"寄り付き|前場|後場|引けにかけ|ザラ場")),
    (H_1D, re.compile(r"本日|今日|きょう")),
    (H_1W, re.compile(r"今週|週内|週後半|週前半")),
    (H_SHORT, re.compile(r"目先|当面|短期|数日")),
    (H_MEDIUM, re.compile(r"中期|年内|来期|数カ月|下期|上期|年末")),
    (H_LONG, re.compile(r"長期|中長期|数年|構造的")),
)
_CONDITION = re.compile(r"となれば|場合|次第|であれば|限り|前提")
_CAVEAT = re.compile(r"もっとも|ただし|他方|一方で|とはいえ")
_TARGETS = (JAPAN_EQUITY, US_EQUITY, FX, JAPAN_RATES, US_RATES, SECTOR, THEME)


@dataclass(frozen=True)
class OutlookItem:
    observation_id: str
    direction: str
    horizon: str
    confidence_ladder: object
    target_market: str          # 文から抽出（無ければ UNKNOWN）
    section_context: str        # section から示唆される市場（抽出ではない）
    conditional: bool
    caveat_in_paragraph: bool
    page: int
    artifact_id: str
    categories: tuple

    def as_dict(self) -> Dict[str, object]:
        return {"observation_id": self.observation_id, "direction": self.direction, "horizon": self.horizon,
                "confidence_ladder": self.confidence_ladder, "target_market": self.target_market,
                "section_context": self.section_context, "conditional": self.conditional,
                "caveat_in_paragraph": self.caveat_in_paragraph, "page": self.page,
                "artifact_id": self.artifact_id, "categories": list(self.categories)}


def classify_direction(text: str) -> str:
    up, down = bool(_UP.search(text)), bool(_DOWN.search(text))
    if _RANGE.search(text):
        return RANGE
    if up and down:
        return MIXED
    if up:
        return UP
    if down:
        return DOWN
    if _MIXED.search(text):
        return MIXED
    if _UNCERTAIN.search(text):
        return UNCERTAIN
    return NOT_STATED


def classify_horizon(text: str) -> str:
    for horizon, pattern in _HORIZON:
        if pattern.search(text):
            return horizon
    return H_NOT_STATED


def target_market(categories: Sequence[str]) -> str:
    for t in _TARGETS:
        if t in categories:
            return t
    return "UNKNOWN"


def section_context(section: str, p2_mode: str) -> str:
    if section == P1_JP_OUTLOOK:
        return JAPAN_EQUITY
    if section == GLOBAL_STRATEGY:
        return FX if p2_mode == "fx_outlook" else US_EQUITY if p2_mode == "us_equity_outlook" else "UNKNOWN"
    return "UNKNOWN"


def extract_outlook(statements: Sequence[Statement], p2_mode: str) -> List[OutlookItem]:
    blocks = by_block(statements)
    out: List[OutlookItem] = []
    for st in statements:
        if st.level != OUTLOOK or not st.observation_id:
            continue
        paragraph = "".join(s.text for s in blocks.get(st.artifact_id, []))
        out.append(OutlookItem(
            observation_id=st.observation_id, direction=classify_direction(st.text),
            horizon=classify_horizon(st.text), confidence_ladder=st.ladder,
            target_market=target_market(st.categories),
            section_context=section_context(st.section, p2_mode),
            conditional=bool(_CONDITION.search(st.text)),
            caveat_in_paragraph=bool(_CAVEAT.search(paragraph)),
            page=st.page, artifact_id=st.artifact_id, categories=tuple(st.categories)))
    return out


def outlook_summary(items: Sequence[OutlookItem]) -> Dict[str, object]:
    """primary = P1（section_context JAPAN_EQUITY）の最初の direction 付き outlook。無ければ最初の outlook。"""
    primary = next((i for i in items if i.section_context == JAPAN_EQUITY and i.direction != NOT_STATED), None)
    if primary is None:
        primary = next((i for i in items if i.direction != NOT_STATED), None)
    if primary is None and items:
        primary = items[0]
    directions: Dict[str, int] = {}
    horizons: Dict[str, int] = {}
    for i in items:
        directions[i.direction] = directions.get(i.direction, 0) + 1
        horizons[i.horizon] = horizons.get(i.horizon, 0) + 1
    return {"count": len(items),
            "primary_direction": primary.direction if primary else NOT_STATED,
            "primary_horizon": primary.horizon if primary else H_NOT_STATED,
            "primary_target": (primary.target_market if primary and primary.target_market != "UNKNOWN"
                               else primary.section_context if primary else "UNKNOWN"),
            "primary_observation_id": primary.observation_id if primary else "",
            "primary_confidence_ladder": primary.confidence_ladder if primary else None,
            "directions": directions, "horizons": horizons,
            "conditional_count": sum(1 for i in items if i.conditional),
            "with_caveat_count": sum(1 for i in items if i.caveat_in_paragraph)}
