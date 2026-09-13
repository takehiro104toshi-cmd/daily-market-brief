"""Data quality report（Phase 3.5 §34）。

報告項目（推測せず数える）:
universe coverage / missing securities / missing prices / duplicate records /
corporate-action anomalies / sector unknown / ScaleCat missing / investor flow coverage /
aggregation input count / aggregation reproducibility（manifest hash の再計算一致）
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Sequence

from .breadth import AggregationManifest, input_set_hash
from .price_movement import EXCL_CORPORATE_ACTION, EXCL_NO_CLOSE, EXCL_NO_PREVIOUS, Movement
from .universe import UniverseSnapshot


def session_quality(universe: UniverseSnapshot, movements: Mapping[str, Movement]
                    ) -> Dict[str, object]:
    codes = universe.codes
    counted = sum(1 for c in codes if c in movements and movements[c].counted)
    reasons: Dict[str, int] = {}
    for c in codes:
        m = movements.get(c)
        if m is None:
            reasons[EXCL_NO_CLOSE] = reasons.get(EXCL_NO_CLOSE, 0) + 1
        elif not m.counted:
            reasons[m.exclusion_reason] = reasons.get(m.exclusion_reason, 0) + 1
    return {
        "session_date": universe.session_date, "universe_size": len(codes),
        "counted": counted,
        "coverage_pct": (round(counted / len(codes) * 100, 2) if codes else 0.0),
        "missing_prices": reasons.get(EXCL_NO_CLOSE, 0),
        "no_previous_close": reasons.get(EXCL_NO_PREVIOUS, 0),
        "corporate_action_excluded": reasons.get(EXCL_CORPORATE_ACTION, 0),
        "exclusions": reasons,
        "sector_unknown": sum(1 for m in universe.members if not m.sector17_code),
        "scale_missing": sum(1 for m in universe.members
                             if not m.scale_category or m.scale_category == "-"),
        "master_effective_date": universe.master_effective_date,
        "master_applied_backwards": universe.master_applied_backwards,
    }


def duplicate_price_records(rows: Iterable[Mapping]) -> Dict[str, int]:
    """同一 (code, trading_date) の重複record（canonicalの冪等性の検査）。"""
    seen: Dict[tuple, int] = {}
    for row in rows:
        key = (str(row["code"]), str(row["trading_date"]))
        seen[key] = seen.get(key, 0) + 1
    duplicates = sum(1 for v in seen.values() if v > 1)
    return {"distinct_keys": len(seen), "duplicate_keys": duplicates}


def manifest_reproducibility(manifests: Sequence[AggregationManifest],
                             stored_inputs: Mapping[str, Sequence[str]]) -> Dict[str, object]:
    """manifest の input_set_hash を store の入力recordから再計算して一致を確認する。"""
    checked = matched = 0
    mismatched: List[str] = []
    for manifest in manifests:
        ids = stored_inputs.get(manifest.manifest_id)
        if ids is None:
            continue
        checked += 1
        if input_set_hash(ids) == manifest.input_set_hash and len(ids) == manifest.input_count:
            matched += 1
        else:
            mismatched.append(manifest.manifest_id)
    return {"checked": checked, "matched": matched, "mismatched": mismatched[:5],
            "all_reproducible": checked > 0 and not mismatched}


def summarize_sessions(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    if not rows:
        return {"sessions": 0}
    return {
        "sessions": len(rows),
        "universe_size_min": min(int(r["universe_size"]) for r in rows),
        "universe_size_max": max(int(r["universe_size"]) for r in rows),
        "coverage_pct_min": min(float(r["coverage_pct"]) for r in rows),
        "coverage_pct_max": max(float(r["coverage_pct"]) for r in rows),
        "missing_prices_total": sum(int(r["missing_prices"]) for r in rows),
        "no_previous_close_total": sum(int(r["no_previous_close"]) for r in rows),
        "corporate_action_excluded_total": sum(int(r["corporate_action_excluded"]) for r in rows),
        "sector_unknown_max": max(int(r["sector_unknown"]) for r in rows),
        "scale_missing_max": max(int(r["scale_missing"]) for r in rows),
        "master_applied_backwards_sessions": sum(
            1 for r in rows if r["master_applied_backwards"]),
    }
