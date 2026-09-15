"""Market data alignment foundation（Phase 3.7 §13）。

Corpus の EXTRACTED_VALUE（紙面ヘッダー表の値）を、referenced market session の
Fact / Market Bank の値と突き合わせる。**Fact Store を書き換えない**（比較結果を保持するだけ）。
lookup は callable 注入（Market Bank が無い環境では NOT_AVAILABLE）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from .header_values import HeaderValue
from .temporal import UNKNOWN as SESSION_UNKNOWN

MATCH = "MATCH"
NEAR_MATCH = "NEAR_MATCH"
CONFLICT = "CONFLICT"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_COMPARABLE = "NOT_COMPARABLE"

#: 紙面ヘッダー key → Market Data Bank series_id（context/builders.py と同一の id）
HEADER_TO_SERIES: Dict[str, str] = {
    "nikkei225_close": "index:nikkei225.close.closing.tokyo",
    "topix_close": "index:topix.close.closing.tokyo",
    "jgb10y_yield": "rates:JGB10Y.yield.closing.tokyo",
    "ust10y_yield": "rates:UST10Y_par.yield.closing.us",
    "usd_jpy": "fx:USDJPY.rate.closing.global",
}

MarketLookup = Callable[[str, str], Optional[Decimal]]   # (series_id, session_date) → value


@dataclass(frozen=True)
class AlignmentResult:
    alignment_id: str
    document_id: str
    key: str
    series_id: str
    session: str
    document_value: Optional[Decimal]
    market_value: Optional[Decimal]
    status: str
    diff_pct: Optional[Decimal]
    created_at: str

    def as_dict(self) -> Dict[str, object]:
        return {"alignment_id": self.alignment_id, "document_id": self.document_id,
                "key": self.key, "series_id": self.series_id, "session": self.session,
                "document_value": None if self.document_value is None else str(self.document_value),
                "market_value": None if self.market_value is None else str(self.market_value),
                "status": self.status,
                "diff_pct": None if self.diff_pct is None else str(self.diff_pct),
                "created_at": self.created_at}


def compare(document_value: Optional[Decimal], market_value: Optional[Decimal],
            tolerance_pct: Decimal) -> tuple:
    if document_value is None:
        return NOT_COMPARABLE, None
    if market_value is None:
        return NOT_AVAILABLE, None
    if market_value == 0:
        return (MATCH if document_value == 0 else CONFLICT), None
    diff = (document_value - market_value) / market_value * Decimal(100)
    if diff == 0:
        return MATCH, diff
    if abs(diff) <= tolerance_pct:
        return NEAR_MATCH, diff
    return CONFLICT, diff


def align_values(*, document_id: str, header_values: Sequence[HeaderValue], session: str,
                 lookup: Optional[MarketLookup], tolerance_pct: Decimal, created_at: datetime,
                 analysis_version: str,
                 mapping: Mapping[str, str] = HEADER_TO_SERIES) -> List[AlignmentResult]:
    out: List[AlignmentResult] = []
    stamp = created_at.isoformat()
    for hv in header_values:
        series = mapping.get(hv.key, "")
        if not series:
            continue
        seed = f"{document_id}|{hv.key}|{session}|{analysis_version}"
        aid = "csa_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
        if session == SESSION_UNKNOWN or not session:
            out.append(AlignmentResult(aid, document_id, hv.key, series, session, hv.level, None,
                                       NOT_COMPARABLE, None, stamp))
            continue
        market = None
        if lookup is not None:
            try:
                market = lookup(series, session)
            except Exception:  # noqa: BLE001 lookup 失敗は NOT_AVAILABLE（推測しない）
                market = None
        status, diff = compare(None if hv.closed else hv.level, market, tolerance_pct)
        out.append(AlignmentResult(aid, document_id, hv.key, series, session,
                                   None if hv.closed else hv.level, market, status,
                                   None if diff is None else diff.quantize(Decimal("0.0001")),
                                   stamp))
    return out


def alignment_summary(results: Sequence[AlignmentResult]) -> Dict[str, int]:
    out = {MATCH: 0, NEAR_MATCH: 0, CONFLICT: 0, NOT_AVAILABLE: 0, NOT_COMPARABLE: 0}
    for r in results:
        out[r.status] = out.get(r.status, 0) + 1
    return out
