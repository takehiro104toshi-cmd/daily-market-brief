"""Operational metrics（Phase 3.9.5）— 運用状態だけ。accuracy / precision / hit rate / forecast 系の指標は作らない。"""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, List, Mapping, Sequence

from .config import DECISION_STATES

FORBIDDEN_METRIC_WORDS = ("accuracy", "precision", "recall", "hit_rate", "hit rate", "forecast", "predict")


def compute_metrics(*, population: Mapping[str, Any], packets: Mapping[str, Mapping[str, Any]],
                    decision_states: Mapping[str, str], decision_records: Sequence[Mapping[str, Any]],
                    corpus_eligible: int, replay_captured_eligible: int) -> Dict[str, Any]:
    primary = list(population.get("primary") or [])
    outcomes = {state: 0 for state in DECISION_STATES}
    for rec in decision_records:
        state = str(rec.get("decision_type", ""))
        if state in outcomes:
            outcomes[state] += 1
    ages: List[int] = []
    blocked = ack_pending = 0
    for pid in primary:
        packet = packets.get(pid) or {}
        codes = {w.get("code") for w in packet.get("warnings") or []}
        blocked += 1 if "W_SIBLING_OPPOSITE_APPROVED" in codes else 0          # APPROVED は C1 で block される candidate
        ack_pending += 1 if "W_SIBLING_OPPOSITE_APPROVE_RECOMMENDED" in codes else 0
        first = (packet.get("replay") or {}).get("first_recommendation_position")
        if isinstance(first, int):
            ages.append(max(0, int(corpus_eligible) - first))
    formal_bound = sum(1 for rec in decision_records if dict(rec.get("metadata") or {}).get("packet_id"))
    acknowledged = sum(1 for rec in decision_records if dict(rec.get("metadata") or {}).get("acknowledged_sibling"))
    return {
        "formal_review_candidates": len(primary),
        "by_recommendation": dict(population.get("by_recommendation") or {}),
        "context_patterns": len(population.get("context") or []),
        "pending_count": len(primary),
        "reviewed_count": len(population.get("decided") or []),
        "outcomes": outcomes,
        "decisions_bound_to_packet": formal_bound,
        "stale_packet_count": 0,                                   # build 時点では 0。decide 時の stale は CLI が集計
        "blocked_conflict_count": blocked,
        "acknowledged_sibling_count": acknowledged,
        "sibling_acknowledgement_pending_count": ack_pending,
        "reopen_eligible_count": len(population.get("reopen_eligible") or []),
        "median_candidate_age_eligible_docs": int(median(ages)) if ages else None,
        "replay_evidence_age_eligible_docs": max(0, int(corpus_eligible) - int(replay_captured_eligible)) if replay_captured_eligible else None,
    }


def assert_operational_only(metrics: Mapping[str, Any]) -> None:
    for key in metrics:
        low = str(key).lower()
        if any(word in low for word in FORBIDDEN_METRIC_WORDS):
            raise ValueError(f"metric name suggests predictive performance: {key}")
