"""Compass Corpus Benchmark（Phase 3.8 §29–§31）。

測るのは **analytical reconstruction**（evidence selection / WHY / outlook / risk / alignment / pattern 安定性 /
rebuild・incremental 等価性）。市場予測精度ではない。labelled ground truth の無い precision / recall は出さない。
決定的 ground truth: P2 mode（紙面構造）、見出し（P1 ボレット）、header 表の行数。
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Sequence

from .categories import FX, US_EQUITY

BENCHMARK_VERSION = "1.0.0"
NOT_PREDICTIVE = ("This benchmark measures reconstruction of the analyst's structure, "
                  "not market forecasting accuracy (Prediction Journal is separate).")


def _ratio(num: int, den: int) -> str:
    return str((Decimal(num) / Decimal(den)).quantize(Decimal("0.001"))) if den else "n/a"


def compute_benchmark(structures: Sequence[Mapping], *, stored_assignments: Sequence[Mapping],
                      recomputed_assignments: Sequence[Mapping], rebuild_equivalence: Optional[bool],
                      incremental_equivalence: Optional[bool], inputs_digest: str,
                      version: str = BENCHMARK_VERSION) -> Dict[str, object]:
    docs = [s for s in structures]
    eligible = [s for s in docs if s.get("eligible")]
    n = len(docs)
    # category extraction agreement: P2 mode（紙面構造の ground truth）と抽出 outlook の target/section
    p2_docs = [s for s in docs if s.get("p2_mode") in ("fx_outlook", "us_equity_outlook")]
    agree = 0
    for s in p2_docs:
        expected = FX if s["p2_mode"] == "fx_outlook" else US_EQUITY
        targets = {o.get("target_market") for o in s.get("outlook") or []} | {o.get("section_context") for o in s.get("outlook") or []}
        if expected in targets:
            agree += 1
    # headline agreement: main theme category が top-3 salient に含まれる
    head_agree = sum(1 for s in docs if (s.get("main_theme") or {}).get("category") in
                     {c["category"] for c in list(s.get("salience_profile") or [])[:3]})
    outlook_any = sum(1 for s in docs if s.get("outlook"))
    outlook_dir = sum(1 for s in docs if (s.get("outlook_summary") or {}).get("primary_direction") not in (None, "", "NOT_STATED"))
    why_explicit = sum(1 for s in docs if (s.get("why_summary") or {}).get("EXPLICIT_WHY"))
    why_any = sum(1 for s in docs if (s.get("why_summary") or {}).get("EXPLICIT_WHY") or (s.get("why_summary") or {}).get("IMPLICIT_ASSOCIATION"))
    risk_any = sum(1 for s in docs if s.get("risk"))
    watch_any = sum(1 for s in docs if s.get("watch_items"))
    align_any = sum(1 for s in docs if (s.get("market_alignment") or {}).get("comparable_values", 0) > 0)
    ctx_any = sum(1 for s in docs if (s.get("regime") or {}).get("context_dimensions", 0) > 0)
    known_any = sum(1 for s in docs if (s.get("regime") or {}).get("known_dimensions", 0) > 0)
    # pattern assignment stability: stored vs recomputed（document ごとの assignment id 集合）
    def _by_doc(rows: Sequence[Mapping]) -> Dict[str, set]:
        out: Dict[str, set] = {}
        for a in rows:
            out.setdefault(str(a["document_id"]), set()).add(str(a["assignment_id"]))
        return out
    stored, recomputed = _by_doc(stored_assignments), _by_doc(recomputed_assignments)
    stable = sum(1 for d in recomputed if stored.get(d) == recomputed[d])
    metrics = {
        "documents": n, "eligible_documents": len(eligible),
        "category_extraction_agreement": _ratio(agree, len(p2_docs)),
        "headline_theme_agreement": _ratio(head_agree, n),
        "outlook_extraction_coverage": _ratio(outlook_any, n),
        "outlook_direction_coverage": _ratio(outlook_dir, n),
        "why_explicit_coverage": _ratio(why_explicit, n),
        "why_any_coverage": _ratio(why_any, n),
        "risk_extraction_coverage": _ratio(risk_any, n),
        "watch_item_coverage": _ratio(watch_any, n),
        "market_alignment_coverage": _ratio(align_any, n),
        "context_regime_coverage": _ratio(ctx_any, n),
        "any_regime_label_coverage": _ratio(known_any, n),
        "pattern_assignment_stability": _ratio(stable, len(recomputed)),
        "rebuild_equivalence": rebuild_equivalence,
        "incremental_equivalence": incremental_equivalence,
    }
    bid = "crb_" + hashlib.sha1(f"{version}|{inputs_digest}".encode("utf-8")).hexdigest()[:16]
    return {"benchmark_id": bid, "benchmark_version": version, "inputs_digest": inputs_digest,
            "metrics": metrics, "ground_truth_basis": {
                "category_extraction_agreement": "P2 page mode (fx_outlook / us_equity_outlook) from page structure",
                "headline_theme_agreement": "P1 bullet / 【】 heading vs top-3 salience",
                "coverage_metrics": "share of documents where the extractor produced the field",
                "pattern_assignment_stability": "stored assignments vs recomputation from stored structures"},
            "boundary": NOT_PREDICTIVE}
