"""Analytical link model（Phase 3.8 §8）。document 構造（同一段落内の順序）と接続語が支持する関係だけを作る。

    EVIDENCE → INTERPRETATION / INTERPRETATION → OUTLOOK / EVIDENCE → OUTLOOK / EVIDENCE → RISK / EVENT → WATCH_ITEM
basis: EXPLICIT_CONNECTIVE（〜ため / 〜を受け / 背景に / ことから …）or SAME_PARAGRAPH_SEQUENCE。因果を捏造しない。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

from ..corpus.structured_record import ANALYST_INTERPRETATION, OUTLOOK, RISK, SOURCE_STATEMENT
from .categories import EVENT
from .statements import Statement, by_block, statements_in_analysis_sections

LINK_VERSION = "1.0.0"

EVIDENCE_TO_INTERPRETATION = "EVIDENCE_TO_INTERPRETATION"
INTERPRETATION_TO_OUTLOOK = "INTERPRETATION_TO_OUTLOOK"
EVIDENCE_TO_OUTLOOK = "EVIDENCE_TO_OUTLOOK"
EVIDENCE_TO_RISK = "EVIDENCE_TO_RISK"
EVENT_TO_WATCH_ITEM = "EVENT_TO_WATCH_ITEM"
LINK_TYPES = (EVIDENCE_TO_INTERPRETATION, INTERPRETATION_TO_OUTLOOK, EVIDENCE_TO_OUTLOOK,
              EVIDENCE_TO_RISK, EVENT_TO_WATCH_ITEM)

EXPLICIT_CONNECTIVE = "EXPLICIT_CONNECTIVE"
SAME_PARAGRAPH_SEQUENCE = "SAME_PARAGRAPH_SEQUENCE"

CONNECTIVES = re.compile(r"ため|を受け|受けて|背景に|ことから|によって|を反映|要因|好感|嫌気|材料視|きっかけ|につれ|に伴")
WATCH = re.compile(r"注目|焦点|見極め|動向")


@dataclass(frozen=True)
class AnalyticalLink:
    link_id: str
    link_type: str
    source_observation_id: str
    target_observation_id: str
    basis: str
    artifact_id: str
    page: int
    connective: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"link_id": self.link_id, "link_type": self.link_type,
                "source_observation_id": self.source_observation_id,
                "target_observation_id": self.target_observation_id, "basis": self.basis,
                "artifact_id": self.artifact_id, "page": self.page, "connective": self.connective}


def _link(link_type: str, src: Statement, dst: Statement) -> AnalyticalLink:
    m = CONNECTIVES.search(dst.text)
    basis = EXPLICIT_CONNECTIVE if m else SAME_PARAGRAPH_SEQUENCE
    seed = f"{link_type}|{src.observation_id}|{dst.observation_id}|{LINK_VERSION}"
    return AnalyticalLink(link_id="crl_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
                          link_type=link_type, source_observation_id=src.observation_id,
                          target_observation_id=dst.observation_id, basis=basis,
                          artifact_id=dst.artifact_id, page=dst.page, connective=m.group(0) if m else "")


def build_links(statements: Sequence[Statement]) -> List[AnalyticalLink]:
    links: List[AnalyticalLink] = []
    seen = set()
    for _, block in by_block(statements_in_analysis_sections(statements)).items():
        block = sorted(block, key=lambda s: s.order)
        last_evidence = None
        last_interpretation = None
        last_event = None
        evidence_since_interp = None
        for st in block:
            if not st.observation_id:
                continue
            if st.level == SOURCE_STATEMENT:
                last_evidence = st
                evidence_since_interp = st
                if EVENT in st.categories:
                    last_event = st
                continue
            if st.level == ANALYST_INTERPRETATION:
                if last_evidence is not None:
                    links.append(_link(EVIDENCE_TO_INTERPRETATION, last_evidence, st))
                last_interpretation = st
                evidence_since_interp = None
                if EVENT in st.categories:
                    last_event = st
                continue
            if st.level == OUTLOOK:
                if last_interpretation is not None and evidence_since_interp is None:
                    links.append(_link(INTERPRETATION_TO_OUTLOOK, last_interpretation, st))
                elif last_evidence is not None:
                    links.append(_link(EVIDENCE_TO_OUTLOOK, last_evidence, st))
                if last_event is not None and WATCH.search(st.text):
                    links.append(_link(EVENT_TO_WATCH_ITEM, last_event, st))
                continue
            if st.level == RISK:
                if last_evidence is not None:
                    links.append(_link(EVIDENCE_TO_RISK, last_evidence, st))
                if last_event is not None and WATCH.search(st.text):
                    links.append(_link(EVENT_TO_WATCH_ITEM, last_event, st))
    out: List[AnalyticalLink] = []
    for l in links:
        if l.link_id in seen:
            continue
        seen.add(l.link_id)
        out.append(l)
    return out
