"""J-Quants data health snapshot（Phase 3.6 §23）。

dataset ごとに machine-readable な健全性を出す:
latest_expected / latest_available / latest_stored / freshness / gap_count / coverage /
last_fetch / last_success / last_error / entitlement。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Mapping, Optional, Sequence

from ..internals.ingest import FetchOutcome
from ..market.jquants_light_store import JQuantsLightStore
from .registry import REGISTRY, ROLE_NONE, JQUANTS_DATASETS
from .session_gap import CURRENT as GAP_CURRENT, GapReport

FRESH_CURRENT = "CURRENT"
FRESH_STALE = "STALE"
FRESH_MISSING = "MISSING"
FRESH_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class DatasetHealth:
    dataset: str
    role: str
    frequency_class: str
    latest_expected: str
    latest_available: str
    latest_stored: str
    freshness: str
    gap_count: int
    coverage: str
    last_fetch: str
    last_success: str
    last_error: str
    entitlement: str

    def as_dict(self) -> Dict[str, object]:
        return {"dataset": self.dataset, "role": self.role,
                "frequency_class": self.frequency_class,
                "latest_expected": self.latest_expected,
                "latest_available": self.latest_available, "latest_stored": self.latest_stored,
                "freshness": self.freshness, "gap_count": self.gap_count,
                "coverage": self.coverage, "last_fetch": self.last_fetch,
                "last_success": self.last_success, "last_error": self.last_error,
                "entitlement": self.entitlement}


def _outcome_info(outcomes: Sequence[FetchOutcome], dataset: str, now: datetime
                  ) -> Dict[str, str]:
    mine = [o for o in outcomes if o.dataset == dataset]
    if not mine:
        return {"last_fetch": "", "last_success": "", "last_error": "", "entitlement": ""}
    last = mine[-1]
    success = [o for o in mine if o.ok]
    errors = [o for o in mine if not o.ok]
    stamp = now.isoformat()
    return {"last_fetch": stamp, "last_success": stamp if success else "",
            "last_error": (f"{errors[-1].error_kind}:http_{errors[-1].http}" if errors else ""),
            "entitlement": last.entitlement or ("AVAILABLE" if last.ok else "")}


def health_snapshot(*, light: JQuantsLightStore, latest_completed: str, now: datetime,
                    outcomes: Sequence[FetchOutcome] = (), daily_gap: Optional[GapReport] = None,
                    master_refresh_days: int = 7, flow_max_age_days: int = 14,
                    topix_latest: str = "") -> Dict[str, DatasetHealth]:
    out: Dict[str, DatasetHealth] = {}
    today = now.date()

    def make(dataset: str, **kw) -> DatasetHealth:
        cap = REGISTRY[dataset]
        info = _outcome_info(outcomes, dataset, now)
        info["entitlement"] = info["entitlement"] or cap.entitlement_status
        return DatasetHealth(dataset=dataset, role=cap.morning_role,
                             frequency_class=cap.frequency_class, **{**info, **kw})

    # ---- daily bars（gap report）
    price_dates = light.price_dates()
    stored_latest = price_dates[-1] if price_dates else ""
    if daily_gap is not None:
        gap_count = len(daily_gap.missing) + len(daily_gap.partial)
        current = sum(1 for s in daily_gap.states if s.status == GAP_CURRENT)
        coverage = f"{current}/{len(daily_gap.states)}"
        fresh = (FRESH_CURRENT if daily_gap.overall == GAP_CURRENT
                 else FRESH_MISSING if not stored_latest else FRESH_STALE
                 if daily_gap.overall == "STALE" else FRESH_CURRENT
                 if daily_gap.latest_stored == latest_completed else FRESH_STALE)
    else:
        gap_count, coverage = 0, ""
        fresh = FRESH_UNKNOWN if not latest_completed else (
            FRESH_CURRENT if stored_latest == latest_completed else
            FRESH_MISSING if not stored_latest else FRESH_STALE)
    out["daily_bars"] = make("daily_bars", latest_expected=latest_completed,
                             latest_available=latest_completed, latest_stored=stored_latest,
                             freshness=fresh, gap_count=gap_count, coverage=coverage)

    # ---- listed master
    eff = light.security_effective_dates()
    latest_eff = eff[-1] if eff else ""
    master_fresh = FRESH_MISSING if not latest_eff else (
        FRESH_CURRENT if (today - date.fromisoformat(latest_eff)).days <= master_refresh_days
        else FRESH_STALE)
    out["listed_master"] = make(
        "listed_master", latest_expected=f"<= {master_refresh_days}d old",
        latest_available=today.isoformat(), latest_stored=latest_eff, freshness=master_fresh,
        gap_count=0, coverage=f"{len(eff)} snapshots")

    # ---- calendar
    cal = light.calendar_range("1900-01-01", "2999-12-31")
    cal_dates = [r["calendar_date"] for r in cal]
    cal_latest = max(cal_dates) if cal_dates else ""
    forward_ok = bool(cal_latest) and cal_latest >= (today + timedelta(days=30)).isoformat()
    covers_latest = bool(latest_completed) and latest_completed in set(cal_dates)
    out["markets_calendar"] = make(
        "markets_calendar", latest_expected=(today + timedelta(days=30)).isoformat(),
        latest_available="", latest_stored=cal_latest,
        freshness=(FRESH_CURRENT if forward_ok and covers_latest else
                   FRESH_MISSING if not cal_dates else FRESH_STALE),
        gap_count=0 if covers_latest else 1, coverage=f"{len(cal_dates)} days")

    # ---- investor types（週次）
    flows = light.investor_flows_published_by("9999-12-31")
    latest_period = max((str(r["period_end"]) for r in flows), default="")
    if latest_period:
        age = (date.fromisoformat(latest_completed or today.isoformat())
               - date.fromisoformat(latest_period)).days
        flow_fresh = FRESH_CURRENT if age <= flow_max_age_days else FRESH_STALE
    else:
        flow_fresh = FRESH_MISSING
    out["investor_types"] = make(
        "investor_types",
        latest_expected=f"period_end >= {(today - timedelta(days=flow_max_age_days)).isoformat()}",
        latest_available="", latest_stored=latest_period, freshness=flow_fresh,
        gap_count=0, coverage=f"{len({(r['section'], r['period_end']) for r in flows})} section-weeks")

    # ---- earnings calendar
    earnings = light.earnings_within(today.isoformat(), (today + timedelta(days=90)).isoformat())
    out["equities_earnings_cal"] = make(
        "equities_earnings_cal", latest_expected=f"{today.isoformat()}..+90d",
        latest_available="", latest_stored=max((str(r["announcement_date"]) for r in earnings),
                                               default=""),
        freshness=FRESH_CURRENT if earnings else FRESH_MISSING, gap_count=0,
        coverage=f"{len(earnings)} schedules")

    # ---- TOPIX（Market Data Bank）
    out["topix"] = make(
        "topix", latest_expected=latest_completed, latest_available=latest_completed,
        latest_stored=topix_latest,
        freshness=(FRESH_UNKNOWN if not topix_latest else FRESH_CURRENT
                   if topix_latest == latest_completed else FRESH_STALE),
        gap_count=0 if topix_latest == latest_completed else 1, coverage="")

    # ---- fins summary（NONE role・情報のみ）
    fins = light.count("fins_summary")
    out["fins_summary"] = make("fins_summary", latest_expected="event-driven",
                               latest_available="", latest_stored=str(fins),
                               freshness=FRESH_UNKNOWN, gap_count=0, coverage=f"{fins} records")
    return out


def snapshot_rows(health: Mapping[str, DatasetHealth]) -> List[Dict[str, object]]:
    return [h.as_dict() for h in health.values()]
