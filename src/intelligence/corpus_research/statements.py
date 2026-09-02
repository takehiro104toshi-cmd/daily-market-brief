"""3.7 の observation を文単位 Statement へ統合した index（salience / link / why / outlook / risk の共通入力）。

Statement は document 内順序（page → block → 文の位置）を持つ。text は解析中のみメモリに置き、
research artifact には **observation_id と text_hash** だけを残す（本文を複製しない）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Sequence, Tuple

from ..corpus.page_sections import GLOBAL_STRATEGY, INVESTMENT_IDEA, P1_JP_OUTLOOK
from ..corpus.structured_record import (
    ANALYST_INTERPRETATION,
    OUTLOOK,
    RISK,
    SOURCE_STATEMENT,
)
from .categories import categorize, primary_category

STATEMENT_LEVELS = (SOURCE_STATEMENT, ANALYST_INTERPRETATION, OUTLOOK, RISK)


@dataclass
class Statement:
    key: str
    text: str
    text_hash: str
    level: str
    page: int
    artifact_id: str
    block_order: Tuple[int, int]
    position: int
    section: str
    observation_ids: List[str] = field(default_factory=list)
    corpus_categories: List[str] = field(default_factory=list)   # 3.7 category（mention 群）
    categories: Tuple[str, ...] = ()                              # 3.8 controlled vocabulary
    primary_category: str = ""
    headline: bool = False
    ladder: object = None
    order: int = 0

    @property
    def observation_id(self) -> str:
        return self.observation_ids[0] if self.observation_ids else ""

    def as_ref(self) -> Dict[str, object]:
        return {"observation_id": self.observation_id, "text_hash": self.text_hash, "level": self.level,
                "page": self.page, "artifact_id": self.artifact_id, "primary_category": self.primary_category,
                "categories": list(self.categories), "headline": self.headline, "order": self.order}


def text_hash(text: str) -> str:
    return "th_" + hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def build_statements(record: Mapping[str, object], artifacts: Sequence[Mapping[str, object]]) -> List[Statement]:
    """current analysis record（3.7 as_dict）＋ artifacts → 順序付き Statement 一覧。"""
    block_of: Dict[str, Tuple[int, int]] = {}
    text_of: Dict[str, str] = {}
    for a in artifacts:
        block_of[str(a["artifact_id"])] = (int(a["page"]), int(a["block_index"]))
        text_of[str(a["artifact_id"])] = str(a.get("text") or "")
    sections = list(record.get("sections") or [])
    by_key: Dict[str, Statement] = {}
    observations = dict(record.get("observations") or {})
    for category, items in observations.items():
        for o in items:
            level = str(o.get("level", ""))
            if level not in STATEMENT_LEVELS:
                continue
            text = str(o.get("text") or "")
            if not text:
                continue
            aid = str(o.get("artifact_id") or "")
            key = f"{aid}|{text_hash(text)}"
            st = by_key.get(key)
            if st is None:
                page = int(o.get("page", 0) or 0)
                pos = text_of.get(aid, "").find(text[:24]) if aid else -1
                st = Statement(
                    key=key, text=text, text_hash=text_hash(text), level=level, page=page,
                    artifact_id=aid, block_order=block_of.get(aid, (page, 0)),
                    position=pos if pos >= 0 else 10_000, section=sections[page - 1] if 0 < page <= len(sections) else "",
                    ladder=o.get("confidence_ladder"))
                by_key[key] = st
            st.observation_ids.append(str(o.get("observation_id") or ""))
            if category not in st.corpus_categories:
                st.corpus_categories.append(category)
            if category == "selected_topics":
                st.headline = True
            # level の優先: OUTLOOK > RISK > INTERPRETATION > SOURCE（同一文が複数 level で登録され得る）
            rank = {OUTLOOK: 3, RISK: 2, ANALYST_INTERPRETATION: 1, SOURCE_STATEMENT: 0}
            if rank.get(level, 0) > rank.get(st.level, 0):
                st.level = level
                st.ladder = o.get("confidence_ladder")
    statements = sorted(by_key.values(), key=lambda s: (s.block_order, s.position, s.text_hash))
    for i, st in enumerate(statements):
        st.order = i
        st.categories = categorize(st.text)
        st.primary_category = primary_category(st.text)
    return statements


def statements_in_analysis_sections(statements: Sequence[Statement]) -> List[Statement]:
    return [s for s in statements if s.section in (P1_JP_OUTLOOK, GLOBAL_STRATEGY, INVESTMENT_IDEA)]


def by_block(statements: Sequence[Statement]) -> Dict[str, List[Statement]]:
    out: Dict[str, List[Statement]] = {}
    for s in statements:
        out.setdefault(s.artifact_id, []).append(s)
    return out
