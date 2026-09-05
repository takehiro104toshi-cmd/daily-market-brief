"""Phase 3-B Compass Context Engine の実データpilot（STEP 29/30）。

fixtureだけで完了判定しない。Phase 3-Aと同じ実Fact（Market Data Bank由来）を
入力に、直近の複数Tokyo sessionでContextを生成し、

- session毎のfact数 / context数 / 中核次元の充足・欠落
- 朝（JST 6:00）時点のmorning context snapshotとlook-ahead混入検査
- 上位（PRIMARY）Contextの内容
- canonical append-only / SQLite再構築 / query / 冪等性
- 過去Compass（output/history/<date>/pre_market.html）との方向整合（STEP 30）

を実測する。J-Quants Light storeがあればearnings scheduleをevent factとして併用する
（無ければ正直に0件として報告する）。**新規fetchは行わない**（既存永続データのみ）。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..core.paths import data_root, market_bank_root
from ..facts import pilot as fact_pilot
from ..facts.conflict import assess_conflicts
from .builders import build_session_contexts
from .compass_alignment import align_snapshot, summarize
from .model import PriorityTier
from .salience import rank_contexts
from .snapshot import leaked_contexts, morning_context_snapshot
from .store import ContextStore


def _event_facts(root, now: datetime) -> List:
    """J-Quants Light canonicalがあれば決算発表予定をevent factとして読む。

    無い環境（TOPIXのみのpilot data root等）では**空**を返す（捏造しない）。
    """
    try:
        from ..market.jquants_light_store import CANONICAL_FILES, JQuantsLightStore
        from ..market.p2h_light_pilot import light_root
        from ..facts.jquants_builder import build_earnings_schedule_facts
        from ..facts.jquants_pilot import _revive
    except Exception:  # noqa: BLE001 依存が無ければevent無しで続行
        return []
    light = light_root(root)
    if not (light / "canonical" / CANONICAL_FILES["equities_earnings_cal"]).exists():
        return []
    store = JQuantsLightStore(light)
    try:
        rows = list(store.iter_canonical("equities_earnings_cal"))
        records = [r for r in (_revive("equities_earnings_cal", row) for row in rows) if r]
        return build_earnings_schedule_facts(records, now=now)
    finally:
        store.close()


def _describe(item) -> Dict[str, str]:
    return {
        "context_type": item.context_type,
        "subject_id": item.subject.subject_id,
        "display_name": item.subject.display_name,
        "session_date": item.time.session_date,
        "direction": item.direction.value,
        "relationship": item.relationship.value if item.relationship else "",
        "magnitude": str(item.magnitude) if item.magnitude is not None else "",
        "magnitude_unit": item.magnitude_unit,
        "priority_tier": item.priority_tier.value,
        "status": item.status.value, "quality": item.quality,
        "rule": item.rule, "supporting_facts": str(len(item.supporting_fact_ids)),
        "context_id": item.context_id,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 3-B Compass Context Engine real-data pilot")
    parser.add_argument("--sessions", type=int, default=5,
                        help="Contextを生成するTokyo session数")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    root = data_root()
    bank = market_bank_root(root)
    if not (bank / "index" / "market.sqlite3").exists():
        print("::P3B_PILOT_SKIP::" + json.dumps(
            {"reason": "market_bank_not_local", "market_bank_root": str(bank)},
            ensure_ascii=False))
        return 0

    from ..market.store import MarketBankStore

    market = MarketBankStore(bank)
    qa = fact_pilot._qa_decisions(market)
    points_by_series = {sid: fact_pilot.load_points(market.index, qa, sid)
                        for sid, _n, _u in fact_pilot.PILOT_SERIES}
    # Phase 3-Aと**同じ生成経路**のFactを使う（Fact Layerを複製しない）
    facts = assess_conflicts(fact_pilot.build_all_market_facts(
        points_by_series, now=now, sessions=args.sessions))
    events = _event_facts(root, now)
    sessions = sorted({f.time.primary_date for f in facts})[-args.sessions:]
    print("::P3B_INPUT::" + json.dumps({
        "sessions": sessions, "facts_total": len(facts),
        "event_facts": len(events),
        "series_coverage": {sid: len(pts) for sid, pts in points_by_series.items()},
    }, ensure_ascii=False))

    # ---- STEP 29: session毎のContext生成
    store = ContextStore(root)
    all_items: List = []
    per_session: List[Dict] = []
    for offset, session_date in enumerate(sessions):
        previous = sessions[offset - 1] if offset > 0 else None
        items = build_session_contexts(facts, session_date,
                                       previous_session=previous,
                                       event_facts=events, now=now)
        items = rank_contexts(items, session_date=session_date)
        all_items.extend(items)
        by_type: Dict[str, int] = {}
        for item in items:
            by_type[item.context_type] = by_type.get(item.context_type, 0) + 1
        per_session.append({
            "session_date": session_date, "previous_session": previous or "",
            "facts_for_session": sum(1 for f in facts
                                     if f.time.primary_date == session_date),
            "contexts": len(items), "by_type": by_type,
            "primary": sum(1 for i in items
                           if i.priority_tier is PriorityTier.PRIMARY),
        })
    first = store.add(all_items)
    second = store.add(all_items)              # 冪等性を実データで確認
    rebuilt = store.rebuild_index()
    print("::P3B_CONTEXTS::" + json.dumps({
        "per_session": per_session, "contexts_total": len(all_items),
        "distinct_context_ids": len({i.context_id for i in all_items}),
        "duplicate_context_ids": len(all_items) - len({i.context_id for i in all_items}),
        "store_added_first": first["added"], "store_added_second": second["added"],
        "idempotent": second["added"] == 0, "superseded": first["superseded"],
        "canonical_rows": store.count(), "rebuilt_from_canonical": rebuilt,
        "rebuild_match": rebuilt == store.count(),
        "missing_provenance": sum(1 for i in all_items
                                  if not i.supporting_fact_ids),
    }, ensure_ascii=False))

    # ---- STEP 24/25/26: 朝のsnapshotとlook-ahead検査
    snapshots = []
    snapshot_objects = []
    for session_date in sessions:
        snapshot = morning_context_snapshot(all_items, session_date,
                                            generated_at=now)
        snapshot_objects.append(snapshot)
        leaks = leaked_contexts(snapshot.items, snapshot.cutoff)
        future = [i for i in snapshot.items if i.time.session_date >= session_date]
        snapshots.append({
            "session_date": session_date,
            "reference_session": snapshot.reference_session,
            "cutoff_utc": snapshot.cutoff.isoformat(),
            "contexts_available": len(snapshot.items),
            "primary_contexts": sum(1 for i in snapshot.items
                                    if i.priority_tier is PriorityTier.PRIMARY),
            "market_state": snapshot.market_state.as_dict(),
            "dimension_status": snapshot.market_state.status_dict(),
            "missing_dimensions": list(snapshot.missing_dimensions),
            "covered_dimensions": len([
                d for d, v in snapshot.market_state.as_dict().items()
                if v != "UNKNOWN"]),
            "look_ahead_leaks": len(leaks),
            "same_or_future_session_contexts": len(future),
        })
    print("::P3B_SNAPSHOT::" + json.dumps({
        "sessions": snapshots,
        "look_ahead_total_leaks": sum(s["look_ahead_leaks"] for s in snapshots),
        "same_or_future_session_total": sum(
            s["same_or_future_session_contexts"] for s in snapshots),
    }, ensure_ascii=False))

    # ---- STEP 13: 上位Contextの中身（説明可能であることを実データで示す）
    latest = snapshot_objects[-1] if snapshot_objects else None
    top = [_describe(i) for i in (latest.items[:8] if latest else [])]
    print("::P3B_TOP::" + json.dumps({
        "session_date": latest.session_date if latest else "",
        "top_contexts": top,
        "priority_components_sample": (
            dict(latest.items[0].priority_components) if latest and latest.items
            else {}),
    }, ensure_ascii=False))

    # ---- STEP 30: 過去Compassとの方向整合（**ruleの最適化には使わない**）
    results = [align_snapshot(s) for s in snapshot_objects]
    print("::P3B_ALIGNMENT::" + json.dumps({
        "per_date": [r.as_dict() for r in results],
        "summary": summarize(results),
    }, ensure_ascii=False))

    # ---- STEP 28: query
    sample = all_items[0] if all_items else None
    print("::P3B_QUERY::" + json.dumps({
        "contexts_for_latest_session": len(
            store.contexts_for_session(sessions[-1])) if sessions else 0,
        "high_priority_latest": len(
            store.high_priority_contexts(sessions[-1])) if sessions else 0,
        "divergences": len(store.divergences()),
        "event_contexts": len(store.event_contexts()),
        "contexts_by_subject_sample": len(
            store.contexts_by_subject(sample.subject.subject_id)) if sample else 0,
        "contexts_by_fact_sample": len(store.contexts_by_fact(
            sample.supporting_fact_ids[0])) if sample and sample.supporting_fact_ids
            else 0,
        "supporting_facts_sample": len(
            store.supporting_facts(sample.context_id)) if sample else 0,
    }, ensure_ascii=False))

    market.close()
    store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
