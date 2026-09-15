"""APPROVE / REJECT stress sections と Phase 3.9.5 formal_review_input（Phase 3.9.4）。

すべて証拠のみ。persistence が高くても承認ではない。production の Shadow Review 履歴と Decision state は
**読み取り専用の参照**として添える（書き込み API は import しない）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..evaluation.config import A_CONSISTENCY
from ..evaluation.models import APPROVE_RECOMMENDED, KEEP_REVIEWING, NOT_READY, REJECT_RECOMMENDED, REVIEW_RECOMMENDED
from .events import rows_by_pattern

STRESS_POSITIONS = (50, 75, 100)


def _nearest_at_or_below(history: Sequence[Mapping[str, Any]], target: int) -> Optional[Mapping[str, Any]]:
    candidates = [r for r in history if int(r["position"]) <= target]
    return candidates[-1] if candidates else None


def _reversions(history: Sequence[Mapping[str, Any]], from_state: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i in range(1, len(history)):
        if history[i - 1]["recommendation"] == from_state and history[i]["recommendation"] != from_state:
            to = history[i]["recommendation"]
            out[f"{from_state}->{to}"] = out.get(f"{from_state}->{to}", 0) + 1
    return dict(sorted(out.items()))


def approve_stress(rows: Sequence[Mapping[str, Any]], metrics: Mapping[str, Mapping[str, Any]],
                   final_position: int) -> Dict[str, Any]:
    groups = rows_by_pattern(rows)
    current = sorted(pid for pid, h in groups.items() if h[-1]["recommendation"] == APPROVE_RECOMMENDED)
    items: List[Dict[str, Any]] = []
    for pid in current:
        h = groups[pid]
        m = metrics[pid]
        at = {}
        for target in STRESS_POSITIONS:
            row = _nearest_at_or_below(h, target)
            at[str(target)] = {"position_used": int(row["position"]) if row else None,
                               "recommendation": row["recommendation"] if row else "NOT_YET_OBSERVED"}
        at["current"] = {"position_used": final_position, "recommendation": h[-1]["recommendation"]}
        first = m["first_approve_recommended_position"]
        items.append({
            "pattern_id": pid, "pattern_type": h[-1]["pattern_type"],
            "recommendation_at": at,
            "first_approve_position": first, "first_approve_date": m["first_approve_recommended_date"],
            "appeared_only_after_100": bool(first is not None and first > 100),
            "approve_persistence_ratio": m["approve_persistence_ratio"],
            "reversions": _reversions(h, APPROVE_RECOMMENDED),
            "worst_consistency_observed": m["worst_consistency_observed"],
            "consistency_ever_low": m["consistency_ever_low"],
            "positions_with_cross_regime_high": m["positions_with_cross_regime_high"],
            "positions_with_time_high": m["positions_with_time_high"],
            "snapshots_observed": m["snapshots_observed"],
            "stability_class": m["stability_class"], "provisional": m["provisional"],
        })
    return {"count": len(items), "positions": list(STRESS_POSITIONS), "items": items,
            "appeared_only_after_100": sum(1 for i in items if i["appeared_only_after_100"]),
            "ever_reverted": sum(1 for i in items if i["reversions"])}


def reject_stress(rows: Sequence[Mapping[str, Any]], metrics: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    groups = rows_by_pattern(rows)
    current = sorted(pid for pid, h in groups.items() if h[-1]["recommendation"] == REJECT_RECOMMENDED)
    items: List[Dict[str, Any]] = []
    for pid in current:
        h = groups[pid]
        m = metrics[pid]
        first_low = next((r for r in h if (r.get("axis_states") or {}).get(A_CONSISTENCY) == "LOW"), None)
        first_rej = next((i for i, r in enumerate(h) if r["recommendation"] == REJECT_RECOMMENDED), None)
        before = h[first_rej - 1]["recommendation"] if first_rej else None
        driver_row = h[first_rej] if first_rej is not None else h[-1]
        recovery = [int(h[i]["position"]) for i in range(1, len(h))
                    if (h[i - 1].get("axis_states") or {}).get(A_CONSISTENCY) == "LOW"
                    and (h[i].get("axis_states") or {}).get(A_CONSISTENCY) != "LOW"]
        items.append({
            "pattern_id": pid, "pattern_type": h[-1]["pattern_type"],
            "first_material_contradiction_position": int(first_low["position"]) if first_low else None,
            "first_reject_position": m["first_reject_recommended_position"],
            "first_reject_date": m["first_reject_recommended_date"],
            "was_review_before_reject": before == REVIEW_RECOMMENDED,
            "recommendation_before_reject": before,
            "reject_driver": str((driver_row.get("axis_reasons") or {}).get(A_CONSISTENCY, "")),
            "dna_conflicts_at_reject": int(driver_row.get("dna_conflicts", 0) or 0),
            "contradiction_at_reject": dict(driver_row.get("contradiction") or {}),
            "contradiction_recovery_positions": recovery,
            "reject_persistence_ratio": m["reject_persistence_ratio"],
            "reversions": _reversions(h, REJECT_RECOMMENDED),
            "stability_class": m["stability_class"], "provisional": m["provisional"],
        })
    return {"count": len(items), "items": items,
            "ever_recovered": sum(1 for i in items if i["contradiction_recovery_positions"])}


def read_only_production_references(production_data_root: Optional[Path], pattern_ids: Sequence[str]
                                    ) -> Dict[str, Dict[str, Any]]:
    """production の Shadow Review 履歴と Decision current state を **読むだけ**。無ければ空。"""
    out: Dict[str, Dict[str, Any]] = {pid: {"shadow_review_events": 0, "shadow_review_last_outcome": "",
                                            "decision_state": "", "source": "NOT_AVAILABLE"} for pid in pattern_ids}
    if production_data_root is None:
        return out
    try:
        from ..shadow_review.events import ShadowReviewEventStore, shadow_review_root

        store = ShadowReviewEventStore(shadow_review_root(Path(production_data_root)))
        if store.exists():
            for pid in pattern_ids:
                events = store.for_pattern(pid)
                out[pid]["shadow_review_events"] = len(events)
                out[pid]["shadow_review_last_outcome"] = events[-1].review_outcome if events else ""
                out[pid]["source"] = "PRODUCTION_READ_ONLY"
    except Exception as exc:  # noqa: BLE001 参照が読めなくても replay 本体は影響を受けない
        for pid in pattern_ids:
            out[pid]["shadow_review_error"] = type(exc).__name__
    try:
        from ..decision.state import derive_current_states
        from ..decision.store import DecisionStore, decisions_root

        dstore = DecisionStore(decisions_root(Path(production_data_root)))
        if dstore.exists():
            states = derive_current_states(dstore.records())
            for pid in pattern_ids:
                out[pid]["decision_state"] = states[pid].state if pid in states else ""
                out[pid]["source"] = "PRODUCTION_READ_ONLY"
    except Exception as exc:  # noqa: BLE001
        for pid in pattern_ids:
            out[pid]["decision_error"] = type(exc).__name__
    return out


def formal_review_input(rows: Sequence[Mapping[str, Any]], metrics: Mapping[str, Mapping[str, Any]],
                        production_refs: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    groups = rows_by_pattern(rows)
    candidates = sorted(pid for pid, h in groups.items()
                        if h[-1]["recommendation"] in (APPROVE_RECOMMENDED, REJECT_RECOMMENDED))
    items = []
    for pid in candidates:
        last = groups[pid][-1]
        m = metrics[pid]
        rec = last["recommendation"]
        items.append({
            "pattern_id": pid, "pattern_type": last["pattern_type"],
            "current_recommendation": rec, "current_axes": dict(last["axis_states"]),
            "current_lifecycle": last["lifecycle_status"],
            "first_recommendation_position": m["first_approve_recommended_position"] if rec == APPROVE_RECOMMENDED
            else m["first_reject_recommended_position"],
            "first_recommendation_date": m["first_approve_recommended_date"] if rec == APPROVE_RECOMMENDED
            else m["first_reject_recommended_date"],
            "persistence_ratio": m["approve_persistence_ratio"] if rec == APPROVE_RECOMMENDED else m["reject_persistence_ratio"],
            "reversal_count": m["recommendation_reversal_count"],
            "stability_class": m["stability_class"], "provisional": m["provisional"],
            "worst_consistency_observed": m["worst_consistency_observed"],
            "positions_with_cross_regime_high": m["positions_with_cross_regime_high"],
            "positions_with_time_high": m["positions_with_time_high"],
            "dna_classification": last["dna_classification"], "dna_conflicts": last["dna_conflicts"],
            "first_surfaced_in_main_position": m["first_surfaced_in_main_position"],
            "production_reference": dict(production_refs.get(pid) or {}),
        })
    return {"count": len(items), "items": items,
            "boundaries": ["EVIDENCE_ONLY: replay persistence never converts to APPROVED or REJECTED",
                           "NOT_PREDICTIVE: persistence measures rule consistency, not forecast quality",
                           "HUMAN_REVIEW_REQUIRED: Phase 3.9.5 decisions are written by a human through Phase 3.9.1 only"]}
