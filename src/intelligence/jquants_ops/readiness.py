"""Morning readiness（Phase 3.6 §24）。

health snapshot から **決定論的**に READY / READY_WITH_WARNINGS / DEGRADED / NOT_READY を決める。
単一 dataset の失敗で必ず全停止しない（required / internals / optional を区別）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Tuple

from .health import FRESH_CURRENT, FRESH_UNKNOWN, DatasetHealth
from .registry import ROLE_INTERNALS, ROLE_OPTIONAL, ROLE_REQUIRED

READY = "READY"
READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
DEGRADED = "DEGRADED"
NOT_READY = "NOT_READY"


@dataclass(frozen=True, kw_only=True)
class Readiness:
    status: str
    reasons: Tuple[str, ...]
    required_ok: bool
    internals_ok: bool
    optional_ok: bool

    def as_dict(self) -> Dict[str, object]:
        return {"status": self.status, "reasons": list(self.reasons),
                "required_ok": self.required_ok, "internals_ok": self.internals_ok,
                "optional_ok": self.optional_ok}


def morning_readiness(health: Mapping[str, DatasetHealth]) -> Readiness:
    reasons: List[str] = []
    required_ok = internals_ok = optional_ok = True
    for h in health.values():
        fresh = h.freshness == FRESH_CURRENT
        if h.role == ROLE_REQUIRED and not fresh:
            if h.dataset == "markets_calendar" and h.freshness != FRESH_UNKNOWN and h.latest_stored:
                # calendar が古いだけなら参照系列で latest session を決められる（DEGRADED）
                internals_ok = False
                reasons.append(f"{h.dataset}: {h.freshness} (fallback to reference series)")
                continue
            required_ok = False
            reasons.append(f"{h.dataset}: {h.freshness}")
        elif h.role == ROLE_INTERNALS and not fresh:
            internals_ok = False
            reasons.append(f"{h.dataset}: {h.freshness} (gap_count={h.gap_count})")
        elif h.role == ROLE_OPTIONAL and not fresh:
            optional_ok = False
            reasons.append(f"{h.dataset}: {h.freshness}")
    if not required_ok:
        status = NOT_READY
    elif not internals_ok:
        status = DEGRADED
    elif not optional_ok:
        status = READY_WITH_WARNINGS
    else:
        status = READY
    return Readiness(status=status, reasons=tuple(reasons), required_ok=required_ok,
                     internals_ok=internals_ok, optional_ok=optional_ok)
