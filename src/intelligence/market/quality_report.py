"""Market Data Bank品質レポート（Phase 2-D PART J）。

CORE系列ごとに coverage / 欠落セッション / provider / QA判定 / 改定 / fallback を
機械可読（dict）で導出する。**検知・報告のみ**——欠測の補完・値の補正はしない。

「期待セッション数」はカタログのcalendar（weekdays / all_days）から機械的に数える。
取引所休日カレンダーは未導入のため、weekdays系列のmissingには**祝日が含まれる**
（正直な申告としてレポートに明記する。祝日辞書での「補正」はしない——将来の
PRIMARY_OFFICIALカレンダー導入時に精緻化する）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

from .model import latest_revisions
from .series_catalog import SeriesCatalog
from .store import MarketBankStore


def _expected_sessions(first: str, last: str, calendar: str) -> int:
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    if calendar == "all_days":
        return (end - start).days + 1
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def build_quality_report(store: MarketBankStore, catalog: SeriesCatalog) -> Dict:
    """全enabled系列の品質サマリ（canonicalから導出。indexへ依存しない）。"""
    latest_decision: Dict[str, str] = {}
    for a in store.qa.iter_assessments():
        latest_decision[a.record_id] = a.decision.value

    series_reports: List[Dict] = []
    for spec in catalog.enabled_series():
        all_obs = store.observations_for_series(spec.series_id)
        raw = tuple(o for o in all_obs if o.kind.value == "raw")
        current = latest_revisions(raw)
        observed = sorted(o.trading_date for o in current if o.value is not None)
        missing_value = sum(1 for o in current if o.value is None)
        revisions = sum(1 for o in raw if o.revision_of)
        decisions: Dict[str, int] = {}
        for o in raw:
            d = latest_decision.get(o.observation_id, "unassessed")
            decisions[d] = decisions.get(d, 0) + 1
        providers = sorted({o.source_id for o in raw if o.source_id})
        report = {
            "series_id": spec.series_id,
            "display_name": spec.display_name,
            "asset_class": spec.asset_class,
            "unit": spec.unit,
            "provider": providers,
            "fallback_used": len(providers) > 1,  # 複数providerが混在=fallback発動の痕跡
            "observations": len(current),
            "first": observed[0] if observed else "",
            "last": observed[-1] if observed else "",
            "missing_value_rows": missing_value,
            "revisions": revisions,
            "qa_decisions": decisions,
            "probe": spec.probe,
        }
        if observed:
            expected = _expected_sessions(observed[0], observed[-1], spec.calendar)
            report["expected_sessions"] = expected
            report["missing_sessions"] = expected - len(set(observed))
            report["missing_sessions_note"] = (
                "weekdays暦基準のためweekdays系列は祝日を含む（補完はしない）"
                if spec.calendar == "weekdays" else "")
        series_reports.append(report)

    derived_count = sum(
        1 for o in store.normalized.iter_observations() if o.kind.value == "derived")
    return {
        "series": series_reports,
        "series_with_data": sum(1 for r in series_reports if r["observations"]),
        "series_empty": [r["series_id"] for r in series_reports if not r["observations"]],
        "derived_observations": derived_count,
        "cross_source_comparison": "not_exercised_single_provider",
    }
