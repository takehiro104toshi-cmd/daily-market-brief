"""Corpus coverage model（Phase 3.7 §15 / §17）。

label は **客観的に付けられるもの** を優先する:
    CONTEXT          … Phase 3-B / 3.5 の Context（J-Quants / Fact 由来）
    EXTRACTED_VALUE  … 紙面の数値表（羅針盤が掲載した客観値）から閾値で決定
    TEXT_KEYWORD     … 本文 keyword（major_event_state のみ。最も弱い）
    UNKNOWN          … 決められない（bull/bear を本文から恣意的に決めない）
threshold は version 化（coverage_thresholds_version）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .header_values import HeaderValue
from .versioning import coverage_label_id

COVERAGE_DIMENSIONS: Tuple[str, ...] = (
    "equity_direction", "volatility_state", "nikkei_vs_topix", "yen_direction",
    "japan_rate_direction", "us_rate_direction", "turnover_state", "breadth_state",
    "growth_value_state", "sector_leadership", "major_event_state",
)

SOURCE_CONTEXT = "CONTEXT"
SOURCE_EXTRACTED = "EXTRACTED_VALUE"
SOURCE_TEXT = "TEXT_KEYWORD"
SOURCE_UNKNOWN = "UNKNOWN"
UNKNOWN = "UNKNOWN"

EXPECTED_LABELS: Dict[str, Tuple[str, ...]] = {
    "equity_direction": ("UP", "DOWN", "FLAT"),
    "volatility_state": ("LOW", "NORMAL", "HIGH"),
    "nikkei_vs_topix": ("NIKKEI_OUTPERFORM", "TOPIX_OUTPERFORM", "IN_LINE"),
    "yen_direction": ("YEN_WEAKER", "YEN_STRONGER", "FLAT"),
    "japan_rate_direction": ("UP", "DOWN", "FLAT"),
    "us_rate_direction": ("UP", "DOWN", "FLAT"),
    "turnover_state": ("EXPANDING", "CONTRACTING", "STABLE"),
    "breadth_state": ("BROAD", "NARROW", "MIXED"),
    "growth_value_state": ("GROWTH_LEAD", "VALUE_LEAD", "MIXED"),
    "sector_leadership": ("CYCLICAL", "DEFENSIVE", "FINANCIAL", "TECH", "MIXED"),
    "major_event_state": ("CENTRAL_BANK", "EARNINGS", "MACRO_DATA", "GEOPOLITICS", "NONE_DETECTED"),
}

THRESHOLDS: Dict[str, object] = {
    "version": "1.0.0",
    "equity_pct": Decimal("0.5"),
    "relative_pct": Decimal("0.3"),
    "yen_diff": Decimal("0.3"),
    "rate_pt": Decimal("0.02"),
    "turnover_trillion": Decimal("1.0"),
    "vix_low": Decimal("15"),
    "vix_high": Decimal("25"),
    "growth_value_pct": Decimal("0.3"),
}


@dataclass(frozen=True)
class CoverageLabels:
    label_id: str
    document_id: str
    document_date: str
    labels: Mapping[str, str]
    sources: Mapping[str, str]
    thresholds_version: str
    analysis_version: str
    created_at: str

    def as_dict(self) -> Dict[str, object]:
        return {"label_id": self.label_id, "document_id": self.document_id,
                "document_date": self.document_date, "labels": dict(self.labels),
                "sources": dict(self.sources), "thresholds_version": self.thresholds_version,
                "analysis_version": self.analysis_version, "created_at": self.created_at}


def _sign_label(value: Optional[Decimal], threshold: Decimal, up: str, down: str, flat: str
                ) -> Tuple[str, str]:
    if value is None:
        return UNKNOWN, SOURCE_UNKNOWN
    if value > threshold:
        return up, SOURCE_EXTRACTED
    if value < -threshold:
        return down, SOURCE_EXTRACTED
    return flat, SOURCE_EXTRACTED


def _change(values: Mapping[str, HeaderValue], key: str) -> Optional[Decimal]:
    hv = values.get(key)
    if hv is None or hv.closed:
        return None
    return hv.change


def _level(values: Mapping[str, HeaderValue], key: str) -> Optional[Decimal]:
    hv = values.get(key)
    if hv is None or hv.closed:
        return None
    return hv.level


def label_document(*, document_id: str, document_date: str,
                   header: Mapping[str, HeaderValue], secondary: Mapping[str, HeaderValue],
                   event_state_text_label: str, analysis_version: str, created_at: datetime,
                   context_labels: Optional[Mapping[str, str]] = None,
                   thresholds: Mapping[str, object] = THRESHOLDS) -> CoverageLabels:
    """決定的: 同じ入力 → 同じ label。CONTEXT label があれば常に優先する。"""
    t = thresholds
    labels: Dict[str, str] = {}
    sources: Dict[str, str] = {}

    def put(dim: str, label: str, source: str) -> None:
        ctx = (context_labels or {}).get(dim)
        if ctx:
            labels[dim], sources[dim] = str(ctx), SOURCE_CONTEXT
        else:
            labels[dim], sources[dim] = label, source

    put("equity_direction", *_sign_label(_change(header, "nikkei225_close"), Decimal(str(t["equity_pct"])),
                                         "UP", "DOWN", "FLAT"))
    vix = _level(secondary, "vix_close")
    if vix is None:
        put("volatility_state", UNKNOWN, SOURCE_UNKNOWN)
    elif vix < Decimal(str(t["vix_low"])):
        put("volatility_state", "LOW", SOURCE_EXTRACTED)
    elif vix > Decimal(str(t["vix_high"])):
        put("volatility_state", "HIGH", SOURCE_EXTRACTED)
    else:
        put("volatility_state", "NORMAL", SOURCE_EXTRACTED)
    nk, tp = _change(header, "nikkei225_close"), _change(header, "topix_close")
    rel = (nk - tp) if (nk is not None and tp is not None) else None
    put("nikkei_vs_topix", *_sign_label(rel, Decimal(str(t["relative_pct"])),
                                        "NIKKEI_OUTPERFORM", "TOPIX_OUTPERFORM", "IN_LINE"))
    put("yen_direction", *_sign_label(_change(header, "usd_jpy"), Decimal(str(t["yen_diff"])),
                                      "YEN_WEAKER", "YEN_STRONGER", "FLAT"))
    put("japan_rate_direction", *_sign_label(_change(header, "jgb10y_yield"), Decimal(str(t["rate_pt"])),
                                             "UP", "DOWN", "FLAT"))
    put("us_rate_direction", *_sign_label(_change(header, "ust10y_yield"), Decimal(str(t["rate_pt"])),
                                          "UP", "DOWN", "FLAT"))
    put("turnover_state", *_sign_label(_change(header, "prime_turnover_trillion_yen"),
                                       Decimal(str(t["turnover_trillion"])),
                                       "EXPANDING", "CONTRACTING", "STABLE"))
    put("breadth_state", UNKNOWN, SOURCE_UNKNOWN)          # CONTEXT のみ（本文から決めない）
    g, v = _change(secondary, "topix_growth_close"), _change(secondary, "topix_value_close")
    gv = (g - v) if (g is not None and v is not None) else None
    put("growth_value_state", *_sign_label(gv, Decimal(str(t["growth_value_pct"])),
                                           "GROWTH_LEAD", "VALUE_LEAD", "MIXED"))
    put("sector_leadership", UNKNOWN, SOURCE_UNKNOWN)      # CONTEXT のみ
    put("major_event_state", event_state_text_label or "NONE_DETECTED", SOURCE_TEXT)
    version = str(t.get("version", "1.0.0"))
    return CoverageLabels(
        label_id=coverage_label_id(document_id, analysis_version, version),
        document_id=document_id, document_date=document_date, labels=labels, sources=sources,
        thresholds_version=version, analysis_version=analysis_version,
        created_at=created_at.isoformat())


def coverage_report(labels: Sequence[CoverageLabels], *, min_docs_per_label: int,
                    thresholds_version: str = str(THRESHOLDS["version"])) -> Dict[str, object]:
    """coverage > raw count: dimension × label の分布と well / under / missing。"""
    dims: Dict[str, Dict[str, object]] = {}
    under: List[str] = []
    missing_all: List[str] = []
    for dim in COVERAGE_DIMENSIONS:
        counts: Dict[str, int] = {}
        sources: Dict[str, int] = {}
        for cl in labels:
            lab = cl.labels.get(dim, UNKNOWN)
            counts[lab] = counts.get(lab, 0) + 1
            src = cl.sources.get(dim, SOURCE_UNKNOWN)
            sources[src] = sources.get(src, 0) + 1
        expected = EXPECTED_LABELS.get(dim, ())
        well = [l for l in expected if counts.get(l, 0) >= min_docs_per_label]
        underrep = [l for l in expected if 0 < counts.get(l, 0) < min_docs_per_label]
        missing = [l for l in expected if counts.get(l, 0) == 0]
        dims[dim] = {"counts": counts, "sources": sources, "well_represented": well,
                     "underrepresented": underrep, "missing": missing,
                     "unknown": counts.get(UNKNOWN, 0)}
        under.extend(f"{dim}={l}" for l in underrep)
        missing_all.extend(f"{dim}={l}" for l in missing)
    return {"thresholds_version": thresholds_version, "min_docs_per_label": min_docs_per_label,
            "labeled_documents": len(labels), "dimensions": dims,
            "underrepresented_regimes": under, "missing_regimes": missing_all,
            "dimensions_fully_unknown": [d for d in COVERAGE_DIMENSIONS
                                         if dims[d]["unknown"] == len(labels) and labels]}
