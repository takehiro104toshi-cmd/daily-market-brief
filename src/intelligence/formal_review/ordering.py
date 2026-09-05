"""Deterministic ordering（Phase 3.9.5・凍結）— section は交互に混ぜない。

Section 1 REJECT_RECOMMENDED: first_reject_position ASC, reject_persistence_ratio DESC, eligible_support DESC, pattern_id
Section 2 APPROVE_RECOMMENDED: stability rank, first_approve_position ASC, eligible_support DESC, span_days DESC, pattern_id
Section 3 REOPEN_ELIGIBLE: first_reject_position ASC, pattern_id
replay 値が無い candidate は各 key で最後尾（決定的）。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED
from .config import FormalReviewPolicy

SECTION_REJECT = "REJECT_RECOMMENDED"
SECTION_APPROVE = "APPROVE_RECOMMENDED"
SECTION_REOPEN = "REOPEN_ELIGIBLE"
_LAST = 10 ** 9


def _pos(value: Any) -> int:
    try:
        return int(value) if value is not None else _LAST
    except (TypeError, ValueError):
        return _LAST


def _ratio_desc(value: Any) -> Decimal:
    try:
        return -Decimal(str(value)) if value is not None and value != "" else Decimal(_LAST)
    except InvalidOperation:
        return Decimal(_LAST)


def reject_key(packet: Mapping[str, Any]) -> Tuple:
    replay = dict(packet.get("replay") or {})
    return (_pos(replay.get("first_recommendation_position")), _ratio_desc(replay.get("persistence_ratio")),
            -int((packet.get("axes") or {}).get("eligible_support", 0) or 0), packet["identity"]["pattern_id"])


def approve_key(packet: Mapping[str, Any], policy: FormalReviewPolicy) -> Tuple:
    replay = dict(packet.get("replay") or {})
    cls = str(replay.get("stability_class", ""))
    rank = policy.stability_rank.index(cls) if cls in policy.stability_rank else len(policy.stability_rank)
    axes = dict(packet.get("axes") or {})
    return (rank, _pos(replay.get("first_recommendation_position")), -int(axes.get("eligible_support", 0) or 0),
            -int(axes.get("span_days", 0) or 0), packet["identity"]["pattern_id"])


def reopen_key(packet: Mapping[str, Any]) -> Tuple:
    replay = dict(packet.get("replay") or {})
    return (_pos(replay.get("first_recommendation_position")), packet["identity"]["pattern_id"])


def order_queue(packets: Mapping[str, Mapping[str, Any]], primary: Sequence[str], reopen: Sequence[str],
                policy: FormalReviewPolicy) -> Dict[str, List[Dict[str, Any]]]:
    rejects = [packets[p] for p in primary if packets[p]["recommendation"]["recommendation"] == REJECT_RECOMMENDED]
    approves = [packets[p] for p in primary if packets[p]["recommendation"]["recommendation"] == APPROVE_RECOMMENDED]
    reopens = [packets[p] for p in reopen if p in packets]
    sections = {
        SECTION_REJECT: sorted(rejects, key=reject_key),
        SECTION_APPROVE: sorted(approves, key=lambda p: approve_key(p, policy)),
        SECTION_REOPEN: sorted(reopens, key=reopen_key),
    }
    out: Dict[str, List[Dict[str, Any]]] = {}
    rank = 0
    for name, items in sections.items():
        rows = []
        for packet in items:
            rank += 1
            rows.append(_queue_row(packet, name, rank))
        out[name] = rows
    return out


def _queue_row(packet: Mapping[str, Any], section: str, rank: int) -> Dict[str, Any]:
    replay = dict(packet.get("replay") or {})
    return {"queue_rank": rank, "section": section, "pattern_id": packet["identity"]["pattern_id"],
            "packet_id": packet["identity"]["packet_id"], "pattern_type": packet["identity"]["pattern_type"],
            "recommendation": packet["recommendation"]["recommendation"],
            "decision_state": packet["decision"]["current_state"],
            "allowed_next_actions": list(packet["decision"]["allowed_next_actions"]),
            "stability_class": replay.get("stability_class", ""),
            "first_recommendation_position": replay.get("first_recommendation_position"),
            "persistence_ratio": replay.get("persistence_ratio"),
            "eligible_support": (packet.get("axes") or {}).get("eligible_support"),
            "span_days": (packet.get("axes") or {}).get("span_days"),
            "sibling_group_key": (packet.get("group") or {}).get("sibling_group_key", ""),
            "warnings": [w["code"] for w in packet.get("warnings") or []],
            "packet_evidence_digest": packet["freshness"]["packet_evidence_digest"]}
