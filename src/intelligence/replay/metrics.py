"""Stability metrics と provisional 分類（Phase 3.9.4）。

指標は「規則の判定がどれだけ一貫していたか」であり accuracy ではない（名称に accuracy / precision /
hit / forecast を使わない）。分類の語彙は凍結、閾値は PROVISIONAL_CALIBRATION_ONLY。
単位は eligible 文書数（snapshot 数ではない）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional

from ..evaluation.config import HIGH, RANK
from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED, REVIEW_RECOMMENDED
from .config import (
    CALIBRATION_PROVISIONAL,
    INSUFFICIENT_HISTORY,
    MOSTLY_STABLE,
    OSCILLATING,
    RECENT_TRANSITION,
    STABLE,
    ReplayPolicy,
)
from .events import rows_by_pattern
from .timeline import SECTION_MAIN


def _days(a: str, b: str) -> Optional[int]:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


def _first(history: List[Mapping[str, Any]], rec: str) -> Optional[Mapping[str, Any]]:
    return next((r for r in history if r["recommendation"] == rec), None)


def pattern_metrics(history: List[Mapping[str, Any]], policy: ReplayPolicy, final_position: int) -> Dict[str, Any]:
    recs = [r["recommendation"] for r in history]
    transitions = sum(1 for i in range(1, len(recs)) if recs[i] != recs[i - 1])
    reversals = sum(1 for i in range(2, len(recs)) if recs[i] != recs[i - 1] and recs[i] == recs[i - 2])
    current = recs[-1]
    entered_idx = len(recs) - 1
    while entered_idx > 0 and recs[entered_idx - 1] == current:
        entered_idx -= 1
    entered_position = int(history[entered_idx]["position"])
    in_state_docs = final_position - entered_position
    first_row = history[0]
    first_seen_pos = int(first_row["position"])
    pattern_first_seen = str(first_row.get("pattern_first_seen") or first_row["latest_document_date"])
    fr, fa, fj = (_first(history, REVIEW_RECOMMENDED), _first(history, APPROVE_RECOMMENDED),
                  _first(history, REJECT_RECOMMENDED))

    def _ratio(num: int, den: int) -> Optional[str]:
        return str((Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"))) if den else None

    since_first_approve = [r for r in history if fa and int(r["position"]) >= int(fa["position"])]
    since_first_reject = [r for r in history if fj and int(r["position"]) >= int(fj["position"])]
    cons_states = [str((r.get("axis_states") or {}).get("evidence_consistency", "")) for r in history]
    worst = min((s for s in cons_states if s in RANK), key=lambda s: RANK[s], default="")
    return {
        "pattern_id": history[-1]["pattern_id"], "pattern_type": history[-1]["pattern_type"],
        "current_recommendation": current, "current_lifecycle": history[-1]["lifecycle_status"],
        "first_seen_position": first_seen_pos, "first_seen_date": pattern_first_seen,
        "history_eligible_documents": final_position - first_seen_pos,
        "snapshots_observed": len(history),
        "recommendation_transition_count": transitions,
        "recommendation_reversal_count": reversals,
        "first_review_recommended_position": int(fr["position"]) if fr else None,
        "first_review_recommended_date": fr["latest_document_date"] if fr else None,
        "first_approve_recommended_position": int(fa["position"]) if fa else None,
        "first_approve_recommended_date": fa["latest_document_date"] if fa else None,
        "first_reject_recommended_position": int(fj["position"]) if fj else None,
        "first_reject_recommended_date": fj["latest_document_date"] if fj else None,
        "documents_to_approve_recommended": int(fa["position"]) if fa else None,
        "documents_to_reject_recommended": int(fj["position"]) if fj else None,
        "time_to_approve_recommended_days": _days(pattern_first_seen, fa["latest_document_date"]) if fa else None,
        "time_to_reject_recommended_days": _days(pattern_first_seen, fj["latest_document_date"]) if fj else None,
        "entered_current_state_position": entered_position,
        "eligible_documents_in_current_state": in_state_docs,
        "state_persistence_ratio": _ratio(sum(1 for r in recs if r == current), len(recs)),
        "approve_persistence_ratio": _ratio(sum(1 for r in since_first_approve if r["recommendation"] == APPROVE_RECOMMENDED),
                                            len(since_first_approve)),
        "reject_persistence_ratio": _ratio(sum(1 for r in since_first_reject if r["recommendation"] == REJECT_RECOMMENDED),
                                           len(since_first_reject)),
        "worst_consistency_observed": worst,
        "consistency_ever_low": any(s == "LOW" for s in cons_states),
        "positions_with_cross_regime_high": sum(1 for r in history
                                                if (r.get("axis_states") or {}).get("cross_regime") == HIGH
                                                and (r.get("axis_applicability") or {}).get("cross_regime") == "APPLICABLE"),
        "positions_with_time_high": sum(1 for r in history if (r.get("axis_states") or {}).get("time_stability") == HIGH),
        "main_appearance_count": sum(1 for r in history if r["queue_section"] == SECTION_MAIN),
        "first_surfaced_in_main_position": next((int(r["position"]) for r in history if r["queue_section"] == SECTION_MAIN), None),
    }


def classify(metrics: Mapping[str, Any], policy: ReplayPolicy) -> Dict[str, Any]:
    """PROVISIONAL: 語彙は凍結、閾値は較正前。単位は eligible 文書数。"""
    reversals = int(metrics["recommendation_reversal_count"])
    in_state = int(metrics["eligible_documents_in_current_state"])
    history = int(metrics["history_eligible_documents"])
    ratio = Decimal(metrics["state_persistence_ratio"] or "0")
    if history < policy.stable_min_persistence:
        cls = INSUFFICIENT_HISTORY
    elif reversals >= policy.oscillating_min_reversals:
        cls = OSCILLATING
    elif in_state >= policy.stable_min_persistence and reversals == 0:
        cls = STABLE
    elif in_state >= policy.stable_min_persistence and ratio >= policy.mostly_stable_ratio:
        cls = MOSTLY_STABLE
    else:
        cls = RECENT_TRANSITION
    return {"stability_class": cls, "calibration_state": policy.stability_calibration_state,
            "provisional": policy.stability_calibration_state == CALIBRATION_PROVISIONAL,
            "unit": policy.stability_unit,
            "thresholds": {"stable_min_persistence": policy.stable_min_persistence,
                           "mostly_stable_ratio": str(policy.mostly_stable_ratio),
                           "oscillating_min_reversals": policy.oscillating_min_reversals}}


def all_pattern_metrics(rows: Iterable[Mapping[str, Any]], policy: ReplayPolicy, final_position: int
                        ) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for pid, history in sorted(rows_by_pattern(rows).items()):
        m = pattern_metrics(history, policy, final_position)
        m.update(classify(m, policy))
        out[pid] = m
    return out


def distribution(metrics: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """較正用の分布（監督者が閾値を決めるための材料）。"""
    classes: Dict[str, int] = {}
    reversals: Dict[str, int] = {}
    for m in metrics.values():
        classes[m["stability_class"]] = classes.get(m["stability_class"], 0) + 1
        key = str(m["recommendation_reversal_count"])
        reversals[key] = reversals.get(key, 0) + 1
    return {"by_stability_class": dict(sorted(classes.items())),
            "by_reversal_count": dict(sorted(reversals.items(), key=lambda kv: int(kv[0]))),
            "patterns": len(metrics)}
