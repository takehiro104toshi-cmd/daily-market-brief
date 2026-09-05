"""Sibling / group context（Phase 3.9.5）— 現行コードが実際に支持する関係だけを使う。

関係 = Phase 3.9.2 contradiction index と同じ key（EVIDENCE_OUTLOOK の evidence categories + outlook target）。
これは REJECT_RECOMMENDED を実際に駆動している関係であり、STATE_OUTLOOK / THEME_OUTLOOK には広げない（v1 凍結）。
group は表示・整合性 guard の文脈であって、group 単位の formal Decision は作らない。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..evaluation.config import T_EVIDENCE_OUTLOOK
from ..evaluation.contradiction import outlook_part, own_direction

COMMITTED_DIRECTIONS: Tuple[str, ...] = ("UP", "DOWN")     # Phase 3.9.2 consistency_committed_directions と同じ
REL_OPPOSITE = "OPPOSITE"
REL_SAME = "SAME"
REL_NON_COMMITTED = "NON_COMMITTED"


def sibling_key(components: Mapping[str, Any]) -> str:
    """EVIDENCE_OUTLOOK で target がある pattern だけ。その他は ''（group なし）。"""
    if str(components.get("pattern_type", "")) != T_EVIDENCE_OUTLOOK:
        return ""
    target = outlook_part(components, "target=")
    if not target:
        return ""
    evidence = ",".join(str(e) for e in (components.get("evidence") or []))
    return f"{evidence}|target={target}"


def build_groups(pattern_records: Mapping[str, Mapping[str, Any]]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for pid, rec in pattern_records.items():
        key = sibling_key(dict(rec.get("components") or {}))
        if key:
            groups.setdefault(key, []).append(str(pid))
    return {k: sorted(v) for k, v in groups.items()}


def relationship(own: str, other: str) -> str:
    if own in COMMITTED_DIRECTIONS and other in COMMITTED_DIRECTIONS:
        return REL_OPPOSITE if own != other else REL_SAME
    return REL_NON_COMMITTED


def group_context(pattern_id: str, pattern_records: Mapping[str, Mapping[str, Any]], groups: Mapping[str, Sequence[str]],
                  evaluations: Mapping[str, Mapping[str, Any]], decision_states: Mapping[str, str],
                  material_digests: Mapping[str, str]) -> Dict[str, Any]:
    rec = pattern_records.get(pattern_id) or {}
    comp = dict(rec.get("components") or {})
    key = sibling_key(comp)
    own_dir = own_direction(comp)
    members: List[Dict[str, Any]] = []
    for other in (groups.get(key) or []) if key else []:
        if other == pattern_id:
            continue
        orec = pattern_records.get(other) or {}
        ocomp = dict(orec.get("components") or {})
        oeval = evaluations.get(other) or {}
        novelty = dict((dict(oeval.get("axis_metrics") or {})).get("dna_novelty") or {})
        members.append({
            "pattern_id": other, "direction": own_direction(ocomp),
            "recommendation": str(oeval.get("recommendation", "")),
            "decision_state": str(decision_states.get(other, "")),
            "dna_classification": str(novelty.get("classification", "")),
            "eligible_support": _int(orec.get("eligible_support")),
            "lifecycle_status": str(orec.get("status", "")),
            "relationship": relationship(own_dir, own_direction(ocomp)),
            "material_digest": str(material_digests.get(other, "")),
        })
    members.sort(key=lambda m: m["pattern_id"])
    return {"sibling_group_key": key, "own_direction": own_dir, "relation": "EVIDENCE_OUTLOOK_NARROW_SIBLING" if key else "",
            "members": members, "group_state_digest": group_state_digest(pattern_id, own_dir, members)}


def group_state_digest(pattern_id: str, own_direction_value: str, members: Sequence[Mapping[str, Any]]) -> str:
    view = {"pattern_id": pattern_id, "own_direction": own_direction_value,
            "members": [{k: m.get(k) for k in ("pattern_id", "direction", "recommendation", "decision_state",
                                                "material_digest", "relationship")} for m in members]}
    blob = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def opposite_members(context: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(m) for m in context.get("members") or [] if m.get("relationship") == REL_OPPOSITE]


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
