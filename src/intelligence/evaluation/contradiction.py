"""Contradiction signals（Phase 3.9.2 / Q18）— **現在の** canonical research artifact から毎回再計算する。

append-only の review_queue membership は stale になり得るため信頼しない（Phase 3.8 の queue rule と同じ
grouping を registry へ適用し直す）。narrow rule: queue の subject_id は衝突 group の全 pattern を含む
（RANGE / 方向なしの sibling まで巻き込む）ので、**自身の direction が UP / DOWN のものだけ** を LOW にする。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence, Set, Tuple

from .config import T_EVIDENCE_OUTLOOK, EvaluationPolicy

NOT_STATED = "NOT_STATED"


def outlook_part(components: Mapping[str, Any], prefix: str) -> str:
    for p in components.get("outlook") or []:
        if str(p).startswith(prefix):
            return str(p)[len(prefix):]
    return ""


def own_direction(components: Mapping[str, Any]) -> str:
    return outlook_part(components, "dir=")


@dataclass(frozen=True)
class ContradictionIndex:
    """corpus 全体で 1 度だけ構築する contradiction 索引（pattern 単位の判定はここを引くだけ）。"""
    narrow_sibling: Set[str] = field(default_factory=set)           # 自身が UP/DOWN で反対 sibling がいる
    narrow_sibling_repeated: Set[str] = field(default_factory=set)  # 双方 eligible_support >= N
    conflicting_groups: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {"narrow_sibling": len(self.narrow_sibling),
                "narrow_sibling_repeated": len(self.narrow_sibling_repeated),
                "conflicting_groups": self.conflicting_groups}


def build_contradiction_index(records: Sequence[Mapping[str, Any]], policy: EvaluationPolicy,
                              min_sibling_support: int = 2) -> ContradictionIndex:
    """EVIDENCE_OUTLOOK の (evidence, target) group に UP と DOWN が同居する場合の narrow contradiction。"""
    committed = set(policy.consistency_committed_directions)
    groups: Dict[Tuple[Tuple[str, ...], str], list] = defaultdict(list)
    for rec in records:
        comp = dict(rec.get("components") or {})
        if comp.get("pattern_type") != T_EVIDENCE_OUTLOOK:
            continue
        key = (tuple(str(e) for e in (comp.get("evidence") or [])), outlook_part(comp, "target="))
        groups[key].append(rec)
    narrow: Set[str] = set()
    repeated: Set[str] = set()
    conflicting = 0
    for members in groups.values():
        dirs = {own_direction(dict(m.get("components") or {})) for m in members}
        if not committed <= dirs:
            continue
        conflicting += 1
        for m in members:
            d = own_direction(dict(m.get("components") or {}))
            if d not in committed:
                continue                                   # RANGE / 方向なしの sibling は巻き込まない
            pid = str(m["pattern_id"])
            narrow.add(pid)
            opposites = [o for o in members
                         if own_direction(dict(o.get("components") or {})) in committed
                         and own_direction(dict(o.get("components") or {})) != d]
            if _support(m) >= min_sibling_support and any(_support(o) >= min_sibling_support for o in opposites):
                repeated.add(pid)
    return ContradictionIndex(narrow_sibling=narrow, narrow_sibling_repeated=repeated,
                              conflicting_groups=conflicting)


def _support(record: Mapping[str, Any]) -> int:
    try:
        return int(record.get("eligible_support"))
    except (TypeError, ValueError):
        return 0


def document_direction_signals(doc_directions: Sequence[str], policy: EvaluationPolicy,
                               min_each_side: int = 2) -> Dict[str, Any]:
    """supporting document の primary_direction から矛盾 / 軟化を判定する。

    UP と DOWN の同居 = 強い矛盾。committed と RANGE/MIXED/UNCERTAIN の同居 = 軟化（矛盾ではないが HIGH を塞ぐ）。
    UNKNOWN / NOT_STATED は「positive evidence が無い」であって矛盾ではない。
    """
    counts = Counter(str(d) for d in doc_directions)
    committed = tuple(policy.consistency_committed_directions)
    soft = tuple(policy.consistency_soft_directions)
    up_down = all(counts.get(d, 0) > 0 for d in committed) and len(committed) >= 2
    repeated = up_down and all(counts.get(d, 0) >= min_each_side for d in committed)
    softened = any(counts.get(d, 0) > 0 for d in committed) and any(counts.get(s, 0) > 0 for s in soft)
    return {"direction_counts": dict(counts), "contradiction": bool(up_down),
            "contradiction_repeated": bool(repeated), "softened": bool(softened)}
