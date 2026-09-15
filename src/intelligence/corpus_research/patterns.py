"""Pattern identity / components / assignments（Phase 3.8 §16–§17）。

pattern ≒ MARKET STATE + SELECTED EVIDENCE + INTERPRETATION/WHY + OUTLOOK or RISK。
component が欠ける partial pattern type を許す。粒度の異なる pattern を同時に割り当てる
（FULL は個別性が高く、粗い型は支持が蓄積しやすい）。identity は canonical component 文字列の hash。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from .regime import CORE_REGIME_DIMENSIONS

PATTERN_VERSION = "1.0.0"

P_FULL = "FULL"                       # market_state + evidence + why + outlook + risk
P_EVIDENCE_OUTLOOK = "EVIDENCE_OUTLOOK"
P_STATE_OUTLOOK = "STATE_OUTLOOK"
P_THEME_OUTLOOK = "THEME_OUTLOOK"
P_EVIDENCE_WHY = "EVIDENCE_WHY"
P_EVIDENCE_RISK = "EVIDENCE_RISK"
PATTERN_TYPES = (P_FULL, P_EVIDENCE_OUTLOOK, P_STATE_OUTLOOK, P_THEME_OUTLOOK, P_EVIDENCE_WHY, P_EVIDENCE_RISK)


@dataclass(frozen=True)
class PatternComponents:
    pattern_type: str
    market_state: Tuple[str, ...]      # ("equity_direction=UP", …) or ()
    evidence: Tuple[str, ...]          # salient evidence categories（sorted）
    theme: str
    why: str                           # EXPLICIT_WHY / IMPLICIT_ASSOCIATION / NO_WHY / "" (not used)
    outlook: Tuple[str, ...]           # ("dir=UP", "target=JAPAN_EQUITY", "horizon=1D")
    risk: str                          # primary risk type or ""

    def canonical(self) -> str:
        return "|".join([self.pattern_type, ",".join(self.market_state), ",".join(self.evidence), self.theme,
                         self.why, ",".join(self.outlook), self.risk])

    def as_dict(self) -> Dict[str, object]:
        return {"pattern_type": self.pattern_type, "market_state": list(self.market_state),
                "evidence": list(self.evidence), "theme": self.theme, "why": self.why,
                "outlook": list(self.outlook), "risk": self.risk}


def pattern_id_for(components: PatternComponents, version: str = PATTERN_VERSION) -> str:
    return "cpt_" + hashlib.sha1(f"{components.canonical()}|{version}".encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PatternAssignment:
    assignment_id: str
    document_id: str
    document_date: str
    pattern_id: str
    pattern_type: str
    pattern_version: str
    components: Mapping[str, object]
    evidence_refs: Tuple[str, ...]      # observation ids（provenance）
    regime_key: str
    quality: str
    eligible: bool

    def as_dict(self) -> Dict[str, object]:
        return {"assignment_id": self.assignment_id, "document_id": self.document_id,
                "document_date": self.document_date, "pattern_id": self.pattern_id,
                "pattern_type": self.pattern_type, "pattern_version": self.pattern_version,
                "components": dict(self.components), "evidence_refs": list(self.evidence_refs),
                "regime_key": self.regime_key, "quality": self.quality, "eligible": self.eligible}


def _outlook_tuple(summary: Mapping[str, object]) -> Tuple[str, ...]:
    parts = []
    d = str(summary.get("primary_direction", "NOT_STATED"))
    if d != "NOT_STATED":
        parts.append(f"dir={d}")
    t = str(summary.get("primary_target", "UNKNOWN"))
    if t != "UNKNOWN":
        parts.append(f"target={t}")
    h = str(summary.get("primary_horizon", "NOT_STATED"))
    if h != "NOT_STATED":
        parts.append(f"horizon={h}")
    return tuple(parts)


def derive_assignments(structure: Mapping[str, object], *, evidence_categories: int,
                       version: str = PATTERN_VERSION) -> List[PatternAssignment]:
    labels = dict(structure.get("market_state") or {})
    state = tuple(f"{d}={labels[d]}" for d in CORE_REGIME_DIMENSIONS if labels.get(d) and labels[d] != "UNKNOWN")
    evidence = tuple(sorted(str(c["category"]) for c in list(structure.get("selected_evidence") or [])[:evidence_categories]))
    theme = str((structure.get("main_theme") or {}).get("category", "UNKNOWN"))
    ws = dict(structure.get("why_summary") or {})
    why = "EXPLICIT_WHY" if ws.get("EXPLICIT_WHY") else "IMPLICIT_ASSOCIATION" if ws.get("IMPLICIT_ASSOCIATION") else "NO_WHY"
    outlook = _outlook_tuple(dict(structure.get("outlook_summary") or {}))
    risk = str((structure.get("risk_summary") or {}).get("primary_type", "NONE"))
    risk = "" if risk == "NONE" else risk
    refs: List[str] = []
    for c in list(structure.get("selected_evidence") or [])[:evidence_categories]:
        refs.extend(str(x) for x in c.get("observation_ids", [])[:2])
    os_ = dict(structure.get("outlook_summary") or {})
    if os_.get("primary_observation_id"):
        refs.append(str(os_["primary_observation_id"]))
    rs = dict(structure.get("risk_summary") or {})
    if rs.get("primary_observation_id"):
        refs.append(str(rs["primary_observation_id"]))

    candidates: List[PatternComponents] = []
    if evidence:
        if state and outlook:
            candidates.append(PatternComponents(P_FULL, state, evidence, theme, why, outlook, risk))
        if outlook:
            candidates.append(PatternComponents(P_EVIDENCE_OUTLOOK, (), evidence, "", "", outlook, ""))
        candidates.append(PatternComponents(P_EVIDENCE_WHY, (), evidence, "", why, (), ""))
        if risk:
            candidates.append(PatternComponents(P_EVIDENCE_RISK, (), evidence, "", "", (), risk))
    if state and outlook:
        core = tuple(s for s in state if s.startswith("equity_direction=") or s.startswith("yen_direction=")
                     or s.startswith("us_rate_direction="))
        if core:
            candidates.append(PatternComponents(P_STATE_OUTLOOK, core, (), "", "", outlook, ""))
    if theme not in ("", "UNKNOWN", "OTHER") and outlook:
        candidates.append(PatternComponents(P_THEME_OUTLOOK, (), (), theme, "", outlook, ""))

    out: List[PatternAssignment] = []
    doc = str(structure["document_id"])
    for comp in candidates:
        pid = pattern_id_for(comp, version)
        aid = "cpa_" + hashlib.sha1(f"{doc}|{pid}|{version}".encode("utf-8")).hexdigest()[:16]
        out.append(PatternAssignment(
            assignment_id=aid, document_id=doc, document_date=str(structure.get("document_date", "")),
            pattern_id=pid, pattern_type=comp.pattern_type, pattern_version=version,
            components=comp.as_dict(), evidence_refs=tuple(dict.fromkeys(refs)),
            regime_key=str((structure.get("regime") or {}).get("regime_key", "regime:UNKNOWN")),
            quality=str(structure.get("quality", "")), eligible=bool(structure.get("eligible"))))
    return out
