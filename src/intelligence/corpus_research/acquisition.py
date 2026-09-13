"""Coverage-guided acquisition recommendations（Phase 3.8 §40）。研究資料の取得推奨であり market advice ではない。"""
from __future__ import annotations

from typing import Dict, List, Mapping

ACQUISITION_VERSION = "1.0.0"

DESCRIPTIONS: Dict[str, str] = {
    "yen_direction=YEN_STRONGER": "円高局面の号",
    "yen_direction=YEN_WEAKER": "円安局面の号",
    "volatility_state=HIGH": "高ボラティリティ（VIX > 25）局面の号",
    "volatility_state=LOW": "低ボラティリティ（VIX < 15）局面の号",
    "japan_rate_direction=DOWN": "日本金利低下局面の号",
    "japan_rate_direction=UP": "日本金利上昇局面の号",
    "us_rate_direction=DOWN": "米金利低下局面の号",
    "growth_value_state=VALUE_LEAD": "バリュー優位の相場の号",
    "growth_value_state=GROWTH_LEAD": "グロース優位の相場の号",
    "equity_direction=FLAT": "小動きの日の号",
    "equity_direction=DOWN": "下落日の号",
    "turnover_state=STABLE": "売買代金が横ばいの日の号",
    "major_event_state=EARNINGS": "決算集中期の号",
    "major_event_state=MACRO_DATA": "主要経済指標発表週の号",
    "major_event_state=GEOPOLITICS": "地政学イベント局面の号",
    "major_event_state=NONE_DETECTED": "大きなイベントの無い週の号",
    "breadth_state=BROAD": "物色の裾野が広い局面（Context 供給が必要）",
    "breadth_state=NARROW": "物色が集中した局面（Context 供給が必要）",
    "sector_leadership=CYCLICAL": "景気敏感株主導の局面（Context 供給が必要）",
    "sector_leadership=DEFENSIVE": "ディフェンシブ主導の局面（Context 供給が必要）",
}


def recommendations(coverage_report: Mapping[str, object]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    dims = dict(coverage_report.get("dimensions") or {})
    for regime in coverage_report.get("missing_regimes") or []:
        dim, _, label = str(regime).partition("=")
        needs_context = dim in ("breadth_state", "sector_leadership")
        out.append({"priority": "HIGH" if not needs_context else "DATA_SUPPLY",
                    "dimension": dim, "label": label, "current_count": 0,
                    "description_ja": DESCRIPTIONS.get(str(regime), f"{dim}={label} の局面の号"),
                    "rationale": "coverage gap: no document in this regime" if not needs_context
                    else "label requires Context (J-Quants) supply rather than more documents",
                    "kind": "research_acquisition"})
    for regime in coverage_report.get("underrepresented_regimes") or []:
        dim, _, label = str(regime).partition("=")
        count = int((dims.get(dim) or {}).get("counts", {}).get(label, 0))
        out.append({"priority": "MEDIUM", "dimension": dim, "label": label, "current_count": count,
                    "description_ja": DESCRIPTIONS.get(str(regime), f"{dim}={label} の局面の号"),
                    "rationale": f"underrepresented: {count} document(s) below well-represented threshold",
                    "kind": "research_acquisition"})
    order = {"HIGH": 0, "MEDIUM": 1, "DATA_SUPPLY": 2}
    out.sort(key=lambda r: (order.get(str(r["priority"]), 9), str(r["dimension"]), str(r["label"])))
    return out
