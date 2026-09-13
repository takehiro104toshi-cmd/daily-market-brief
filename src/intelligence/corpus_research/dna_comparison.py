"""既存 Compass DNA rule との比較（Phase 3.8 §27–§28）。rule は読むだけで **変更しない**。

rule の conditions / implication key を controlled category へ写像し、pattern component と突き合わせる:
EXPLAINED_BY_EXISTING_RULE / PARTIALLY_EXPLAINED / NEW_PATTERN_CANDIDATE / CONFLICTS_WITH_EXISTING_RULE / NOT_COMPARABLE。
conflict はどちらが正しいか決めず記録する。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .categories import (
    BREADTH,
    CENTRAL_BANK,
    EARNINGS,
    EVENT,
    FLOW,
    FX,
    JAPAN_EQUITY,
    JAPAN_RATES,
    MACRO,
    SECTOR,
    TECHNICAL,
    THEME,
    TURNOVER,
    US_EQUITY,
    US_RATES,
    VALUATION,
)

DNA_COMPARISON_VERSION = "1.0.0"

EXPLAINED = "EXPLAINED_BY_EXISTING_RULE"
PARTIAL = "PARTIALLY_EXPLAINED"
NEW = "NEW_PATTERN_CANDIDATE"
CONFLICT = "CONFLICTS_WITH_EXISTING_RULE"
NOT_COMPARABLE = "NOT_COMPARABLE"

_KEY_CATEGORY: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"us_major|sp500|nasdaq|dow|us_stock|sox"), US_EQUITY),
    (re.compile(r"nikkei|jp_|topix|prime|japan|jp$"), JAPAN_EQUITY),
    (re.compile(r"yield|rate_gap|10y"), US_RATES),
    (re.compile(r"jgb|boj"), JAPAN_RATES),
    (re.compile(r"usdjpy|fx|intervention|yen"), FX),
    (re.compile(r"turnover_share|top10|breadth|concentration"), BREADTH),
    (re.compile(r"turnover$|volume"), TURNOVER),
    (re.compile(r"wti|oil|inflation|cpi|jobs|ism|pce|macro"), MACRO),
    (re.compile(r"fomc|fed|central|tankan"), CENTRAL_BANK),
    (re.compile(r"earnings|results"), EARNINGS),
    (re.compile(r"event|calendar|election"), EVENT),
    (re.compile(r"theme|policy|government|dominant"), THEME),
    (re.compile(r"valuation|per|dividend"), VALUATION),
    (re.compile(r"dma|ma_|deviation|dev_"), TECHNICAL),
    (re.compile(r"growth|banks|financial|semis|sector|value_vs_growth|resources|consumer|laggard"), SECTOR),
    (re.compile(r"retail|flow|reinvest"), FLOW),
)
_DIR_UP = re.compile(r"positive|rebound|rerating|up|expansion|tilt|follow|easing_cost")
_DIR_DOWN = re.compile(r"negative|down|profit_taking|caution|wait")
_DIR_RANGE = re.compile(r"narrow_range|range")


def _categories_for_keys(keys: Sequence[str]) -> Tuple[str, ...]:
    out: List[str] = []
    for k in keys:
        kl = str(k).lower()
        for pattern, cat in _KEY_CATEGORY:
            if pattern.search(kl) and cat not in out:
                out.append(cat)
    return tuple(out)


def _direction_of(values: Sequence[object]) -> str:
    text = " ".join(str(v) for v in values).lower()
    if _DIR_RANGE.search(text):
        return "RANGE"
    if "follows_us_direction" in text or "follow_sox" in text or "conditional" in text:
        return "CONDITIONAL"
    up, down = bool(_DIR_UP.search(text)), bool(_DIR_DOWN.search(text))
    if up and down:
        return "MIXED"
    if up:
        return "UP"
    if down:
        return "DOWN"
    return "NOT_STATED"


@dataclass(frozen=True)
class RuleFeatures:
    rule_id: str
    name: str
    evidence_categories: Tuple[str, ...]
    target_categories: Tuple[str, ...]
    direction: str
    horizon: str
    confidence: str

    def as_dict(self) -> Dict[str, object]:
        return {"rule_id": self.rule_id, "name": self.name, "evidence_categories": list(self.evidence_categories),
                "target_categories": list(self.target_categories), "direction": self.direction,
                "horizon": self.horizon, "confidence": self.confidence}


def load_rules(path: Path) -> List[RuleFeatures]:
    path = Path(path)
    if not path.is_file():
        return []
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return []
    out: List[RuleFeatures] = []
    for r in data.get("rules") or []:
        cond = dict(r.get("conditions") or {})
        impl = {k: v for k, v in dict(r.get("implication") or {}).items() if k not in ("note", "basis", "slogan", "output_format")}
        out.append(RuleFeatures(
            rule_id=str(r.get("rule_id", "")), name=str(r.get("name", "")),
            evidence_categories=_categories_for_keys(list(cond.keys()) + [str(v) for v in cond.values() if isinstance(v, str)]),
            target_categories=_categories_for_keys(list(impl.keys())),
            direction=_direction_of(list(impl.values())), horizon=str(r.get("horizon", "")),
            confidence=str(r.get("confidence", ""))))
    return out


@dataclass(frozen=True)
class DnaComparison:
    comparison_id: str
    pattern_id: str
    classification: str
    best_rule_id: str
    evidence_overlap: Tuple[str, ...]
    target_match: bool
    direction_relation: str        # SAME / OPPOSITE / CONDITIONAL / UNKNOWN
    candidate_rule_ids: Tuple[str, ...]
    version: str = DNA_COMPARISON_VERSION

    def as_dict(self) -> Dict[str, object]:
        return {"comparison_id": self.comparison_id, "pattern_id": self.pattern_id,
                "classification": self.classification, "best_rule_id": self.best_rule_id,
                "evidence_overlap": list(self.evidence_overlap), "target_match": self.target_match,
                "direction_relation": self.direction_relation, "candidate_rule_ids": list(self.candidate_rule_ids),
                "version": self.version}


def _pattern_features(components: Mapping[str, object]) -> Tuple[Tuple[str, ...], str, str]:
    evidence = tuple(str(e) for e in components.get("evidence") or [])
    theme = str(components.get("theme") or "")
    if theme and theme not in ("UNKNOWN", "OTHER"):
        evidence = tuple(dict.fromkeys(evidence + (theme,)))
    direction, target = "", ""
    for part in components.get("outlook") or []:
        p = str(part)
        if p.startswith("dir="):
            direction = p[4:]
        elif p.startswith("target="):
            target = p[7:]
    return evidence, direction, target


def compare_pattern(pattern_id: str, components: Mapping[str, object], rules: Sequence[RuleFeatures]) -> DnaComparison:
    evidence, direction, target = _pattern_features(components)
    seed = f"{pattern_id}|{DNA_COMPARISON_VERSION}"
    cid = "crd_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
    if not evidence and not target:
        return DnaComparison(cid, pattern_id, NOT_COMPARABLE, "", (), False, "UNKNOWN", ())
    best: Optional[Tuple[int, RuleFeatures, Tuple[str, ...], bool]] = None
    candidates: List[str] = []
    for rule in rules:
        overlap = tuple(c for c in evidence if c in rule.evidence_categories)
        tmatch = bool(target) and target in rule.target_categories
        score = len(overlap) * 2 + (1 if tmatch else 0)
        if score == 0:
            continue
        candidates.append(rule.rule_id)
        if best is None or score > best[0]:
            best = (score, rule, overlap, tmatch)
    if best is None:
        return DnaComparison(cid, pattern_id, NEW, "", (), False, "UNKNOWN", ())
    _, rule, overlap, tmatch = best
    if not direction or rule.direction in ("NOT_STATED", ""):
        relation = "UNKNOWN"
    elif rule.direction == "CONDITIONAL":
        relation = "CONDITIONAL"
    elif rule.direction == direction:
        relation = "SAME"
    elif {rule.direction, direction} == {"UP", "DOWN"}:
        relation = "OPPOSITE"
    else:
        relation = "UNKNOWN"
    if overlap and tmatch and relation == "OPPOSITE":
        classification = CONFLICT
    elif overlap and tmatch and relation == "SAME":
        classification = EXPLAINED
    elif overlap and (tmatch or relation in ("CONDITIONAL", "SAME")):
        classification = PARTIAL
    elif overlap or tmatch:
        classification = PARTIAL
    else:
        classification = NEW
    return DnaComparison(cid, pattern_id, classification, rule.rule_id, overlap, tmatch, relation, tuple(candidates))


def conflict_record(comparison: DnaComparison, pattern: Mapping[str, object]) -> Dict[str, object]:
    return {"conflict_id": "crc_" + hashlib.sha1(f"{comparison.pattern_id}|{comparison.best_rule_id}|{DNA_COMPARISON_VERSION}".encode("utf-8")).hexdigest()[:16],
            "pattern_id": comparison.pattern_id, "rule_id": comparison.best_rule_id,
            "supporting_document_ids": list(pattern.get("supporting_document_ids") or []),
            "affected_regimes": list(pattern.get("regime_coverage") or []),
            "evidence_references": list(pattern.get("evidence_references") or [])[:20],
            "direction_relation": comparison.direction_relation,
            "decision": "NONE (recorded for supervisor review; neither side judged correct)",
            "version": DNA_COMPARISON_VERSION}
