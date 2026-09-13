"""Phase 3-A Fact Layer real-data pilot（STEP 22/23）。

**fixtureのみで完了判定しない**。Data Bankの実データ（market observations /
news documents / J-Quants records）からFactを生成し、
- 複数Tokyo sessionでのFact生成
- Compass数値replay（TOPIX / Nikkei / 25DMA / rates / FX / NT倍率）
- look-ahead混入チェック
- canonical / SQLite再構築 / query
を実測する。

TOPIX / J-Quantsのlive pathは**読み取りのみ**。P2-G.2 / P2-Hの経路は変更しない。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..core.paths import data_root, market_bank_root
from . import calculations as calc
from .availability import leaked_facts, morning_cutoff, morning_snapshot
from .conflict import assess_conflicts
from .market_builder import (
    NT_RATIO,
    SessionPoint,
    build_cross_series_history_facts,
    build_history_facts,
)
from .store import FactStore

#: pilot対象系列（既存catalogに存在し、validated dataがあるものだけ）
PILOT_SERIES = (
    ("index:nikkei225.close.closing.tokyo", "日経平均株価", "index"),
    ("index:topix.close.closing.tokyo", "TOPIX", "index"),
    ("rates:JGB10Y.yield.closing.tokyo", "日本10年国債利回り", "pct"),
    ("rates:UST2Y_par.yield.closing.us", "米2年国債利回り(par)", "pct"),
    ("rates:UST10Y_par.yield.closing.us", "米10年国債利回り(par)", "pct"),
    ("fx:USDJPY.rate.closing.global", "ドル円", "jpy_per_usd"),
)
NIKKEI = PILOT_SERIES[0][0]
TOPIX = PILOT_SERIES[1][0]
UST10Y = "rates:UST10Y_par.yield.closing.us"
UST2Y = "rates:UST2Y_par.yield.closing.us"


def _qa_decisions(store) -> Dict[str, str]:
    """observation_id → 最新QA判定（REJECTからFactを作らないために使う）。"""
    decisions: Dict[str, str] = {}
    try:
        for assessment in store.qa.iter_assessments():
            decisions[assessment.record_id] = assessment.decision.value
    except Exception:  # noqa: BLE001 QA storeが無い環境では判定なしで進む
        return {}
    return decisions


def load_points(index, qa: Dict[str, str], series_id: str,
                limit: int = 100000) -> List[SessionPoint]:
    """SQLite index上のraw観測 → SessionPoint列（trading_date昇順）。"""
    rows = index.query(series_id=series_id, kind="raw", limit=limit)
    points: List[SessionPoint] = []
    for row in rows:
        trading_date = str(row["trading_date"] or "")
        if not trading_date:
            continue
        raw_value = row["value"]
        value = Decimal(str(raw_value)) if raw_value not in (None, "") else None
        as_of = row["as_of_utc"]
        points.append(SessionPoint(
            trading_date=trading_date, value=value,
            observation_id=row["observation_id"],
            as_of=datetime.fromisoformat(as_of) if as_of else None,
            source_id=row["source_id"] or "",
            qa_decision=qa.get(row["observation_id"], ""),
            unit=row["unit"] or "", currency=row["currency"] or ""))
    points.sort(key=lambda p: p.trading_date)
    return points


def build_all_market_facts(points_by_series: Dict[str, List[SessionPoint]],
                           *, now: datetime, sessions: int = 5) -> List:
    """直近 `sessions` 本の**各セッション時点**のFactを生成する。

    各セッションはそのセッションまでの観測だけを入力にするため、
    生成物はそのままlook-ahead-freeなsnapshot素材になる。
    """
    facts: List = []
    for series_id, display_name, _unit in PILOT_SERIES:
        points = points_by_series.get(series_id, [])
        if points:
            facts.extend(build_history_facts(
                series_id, points, sessions=sessions,
                display_name=display_name, now=now))
    facts.extend(build_cross_series_history_facts(
        NT_RATIO, NIKKEI, TOPIX, points_by_series.get(NIKKEI, []),
        points_by_series.get(TOPIX, []), subject_id="index:nikkei225_topix",
        unit="x", calculation_name=calc.NT_RATIO, sessions=sessions,
        display_name="NT倍率", now=now))
    facts.extend(build_cross_series_history_facts(
        "yield_spread", UST10Y, UST2Y, points_by_series.get(UST10Y, []),
        points_by_series.get(UST2Y, []), subject_id="rates:UST10Y_par_UST2Y_par",
        unit="pct_point", calculation_name=calc.YIELD_SPREAD, sessions=sessions,
        display_name="米10年-2年スプレッド", now=now))
    return facts


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3-A Fact Layer real-data pilot")
    parser.add_argument("--sessions", type=int, default=5,
                        help="snapshot再現を試すTokyo session数")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    root = data_root()
    bank = market_bank_root(root)
    if not (bank / "index" / "market.sqlite3").exists():
        print("::P3A_PILOT_SKIP::" + json.dumps(
            {"reason": "market_bank_not_local", "market_bank_root": str(bank)},
            ensure_ascii=False))
        return 0

    from ..market.store import MarketBankStore

    market = MarketBankStore(bank)
    qa = _qa_decisions(market)
    points_by_series = {sid: load_points(market.index, qa, sid)
                        for sid, _n, _u in PILOT_SERIES}
    coverage = {sid: len(pts) for sid, pts in points_by_series.items()}
    print("::P3A_INPUT::" + json.dumps(
        {"series_coverage": coverage,
         "qa_assessments_indexed": len(qa)}, ensure_ascii=False))

    facts = build_all_market_facts(points_by_series, now=now,
                                   sessions=args.sessions)
    facts = assess_conflicts(facts)

    store = FactStore(root)
    result = store.add(facts)
    rebuilt = store.rebuild_index()

    by_type: Dict[str, int] = {}
    for fact in facts:
        by_type[fact.fact_type] = by_type.get(fact.fact_type, 0) + 1
    print("::P3A_FACTS::" + json.dumps({
        "generated": len(facts), "by_type": by_type,
        "store_added": result["added"], "store_skipped": result["skipped"],
        "store_superseded": result["superseded"],
        "canonical_rows": store.count(), "rebuilt_from_canonical": rebuilt,
        "rebuild_match": rebuilt == store.count(),
        "with_provenance": sum(1 for f in facts if f.evidence),
        "derived_with_inputs": sum(1 for f in facts if f.is_derived and f.input_ids),
    }, ensure_ascii=False))

    # ---- STEP 23: Compass数値replay（TOPIX / Nikkei / 25DMA / rates / FX / NT）
    replay = []
    for series_id, display_name, _unit in PILOT_SERIES:
        row = store.latest_fact(series_id, "index_close") \
            or store.latest_fact(series_id, "yield_level") \
            or store.latest_fact(series_id, "fx_level")
        ma = store.latest_fact(series_id, "moving_average_25session")
        dist = store.latest_fact(series_id, "distance_from_ma25_pct")
        replay.append({
            "series_id": series_id, "display_name": display_name,
            "level": row["value"] if row else "", "unit": row["unit"] if row else "",
            "trading_date": row["primary_date"] if row else "",
            "ma25": ma["value"] if ma else "",
            "distance_from_ma25_pct": dist["value"] if dist else "",
        })
    nt_row = store.latest_fact("index:nikkei225_topix", NT_RATIO)
    spread_row = store.latest_fact("rates:UST10Y_par_UST2Y_par", "yield_spread")
    print("::P3A_REPLAY::" + json.dumps({
        "series": replay,
        "nt_ratio": {"value": nt_row["value"], "trading_date": nt_row["primary_date"]}
                    if nt_row else None,
        "ust10y_2y_spread": {"value": spread_row["value"],
                             "trading_date": spread_row["primary_date"]}
                            if spread_row else None,
    }, ensure_ascii=False))

    # ---- STEP 19/21: 複数sessionのmorning snapshot＋look-ahead検査
    topix_dates = sorted({p.trading_date for p in points_by_series.get(TOPIX, [])})
    snapshots = []
    for session_date in topix_dates[-args.sessions:]:
        cutoff = morning_cutoff(session_date)
        snapshot = morning_snapshot(facts, session_date)
        leaked = leaked_facts(snapshot, cutoff)
        latest_dates = sorted({f.time.primary_date for f in snapshot})
        snapshots.append({
            "session_date": session_date, "cutoff_utc": cutoff.isoformat(),
            "facts_available": len(snapshot),
            "latest_fact_date": latest_dates[-1] if latest_dates else "",
            "look_ahead_leaks": len(leaked),
            "no_future_dates": all(d < session_date for d in latest_dates),
        })
    print("::P3A_SNAPSHOT::" + json.dumps(
        {"sessions": snapshots,
         "look_ahead_total_leaks": sum(s["look_ahead_leaks"] for s in snapshots)},
        ensure_ascii=False))

    # ---- STEP 18: query foundation
    # queryのサンプルは**derived fact**を選ぶ（入力IDの追跡を実証するため）
    sample = next((f for f in facts if f.is_derived and f.input_ids),
                  facts[0] if facts else None)
    print("::P3A_QUERY::" + json.dumps({
        "latest_topix_close": bool(store.latest_fact(TOPIX, "index_close")),
        "facts_for_series_topix": len(store.facts_for_series(TOPIX)),
        "facts_on_latest_date": len(store.facts_on(topix_dates[-1]))
                                if topix_dates else 0,
        "facts_between_range": len(store.facts_between(
            topix_dates[0], topix_dates[-1])) if topix_dates else 0,
        "facts_by_evidence": len(store.facts_by_evidence(
            sample.evidence[0].ref_id)) if sample and sample.evidence else 0,
        "derived_inputs_sample": len(store.derived_inputs(sample.fact_id))
                                 if sample else 0,
        "conflicted_facts": len(store.conflicted_facts()),
    }, ensure_ascii=False))

    # ---- data quality
    print("::P3A_QUALITY::" + json.dumps({
        "facts_total": len(facts),
        "usable": sum(1 for f in facts if f.status.value == "usable"),
        "limited_use": sum(1 for f in facts if f.status.value == "limited_use"),
        "missing_provenance": sum(1 for f in facts if not f.evidence),
        "derived_missing_inputs": sum(
            1 for f in facts if f.is_derived and not f.input_ids),
        "distinct_fact_ids": len({f.fact_id for f in facts}),
        "duplicate_fact_ids": len(facts) - len({f.fact_id for f in facts}),
        "conflicts": sum(1 for f in facts if f.conflict_state.value == "conflict"),
    }, ensure_ascii=False))

    market.close()
    store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
