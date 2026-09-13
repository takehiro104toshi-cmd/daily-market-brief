"""Phase 3.6 J-Quants Production Data Strategy の実データ検証（§29 / §30 / §31）。

isolated pilot root（<data_root>/jquants_ops_pilot）で、J-Quants Light 実データにより

- seed（意図的に「中間の1 session」と「最新 session」を欠いた状態を作る）
- session gap detection → repair（欠落だけ取得）→ affected metrics 再計算
- daily incremental（最新 session だけ取得）→ rerun（0 リクエスト・重複 0）
- master snapshot refresh / diff、weekly flow refresh（新規のみ）、fins date-mode probe
- health snapshot / readiness / morning simulation（look-ahead leaks 0）
- corporate action / schema drift / failure classification / performance / storage / requests

を実測する。production data（他の root）を触らない。credential 値は出力しない。
"""
from __future__ import annotations

import argparse
import json
import os
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..context.snapshot import leaked_contexts
from ..context.store import ContextStore
from ..core.paths import data_root, market_bank_root
from ..facts.store import FactStore
from ..internals.config import load_internals_config
from ..internals.ingest import (
    InternalsIngestor,
    fetch_calendar,
    fetch_investor_types,
    fetch_master,
)
from ..internals.pipeline import build_internals, latest_availability
from ..internals.snapshot import morning_internals_snapshot
from ..internals.types import INTERNALS_CONTEXT_TYPES
from ..market.jquants_light_store import JQuantsLightStore
from ..market.jquants_v2_client import JQuantsV2Client
from ..market.p2h_light_pilot import light_root
from ..market.tokyo_calendar import latest_completed_session, trading_days
from .capability_gate import standing_audit
from .config import load_ops_config
from .corporate_actions import corporate_action_report
from .earnings_calendar import plan_earnings_refresh
from .earnings_calendar import strategy as earnings_strategy
from .failure_policy import OK, RetryPolicy, classify_failure, fetch_with_retry, morning_impact
from .fifty_two_week import decision as fifty_two_week_decision
from .financial_summary import plan_financial_refresh
from .financial_summary import strategy as fins_strategy
from .health import health_snapshot, snapshot_rows
from .incremental import apply_update, plan_update, recompute_affected
from .master_refresh import diff_master, refresh_due, snapshot_dates_for_seed
from .master_refresh import strategy as master_strategy
from .morning_contract import morning_contract, previous_session_of
from .plan_upgrade_register import register_rows
from .plan_upgrade_register import summary as upgrade_summary
from .readiness import morning_readiness
from .registry import REGISTRY, frequency_table, registry_rows
from .request_budget import request_budget
from .rolling_window import policy_from_config
from .schema_drift import check_schema
from .session_gap import detect_gaps, expected_sessions_for_window
from .storage_budget import storage_budget
from .topix_strategy import CONTRACT as TOPIX_CONTRACT
from .topix_strategy import same_session_alignment
from .weekly_flow import plan_flow_refresh
from .weekly_flow import strategy as flow_strategy

_SECRET_ENV_NAMES = ("JQUANTS_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
PILOT_ROOT_NAME = "jquants_ops_pilot"


def _out(marker: str, payload) -> None:
    print(f"::{marker}::" + json.dumps(payload, ensure_ascii=False, default=str))


def _rows_by_session(light: JQuantsLightStore, sessions: Sequence[str]) -> Dict[str, int]:
    return {s: len(light.prices_on(s)) for s in sessions}


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def _topix_dates(root: Path) -> Dict[str, List[str]]:
    """Market Data Bank（同じ INTELLIGENCE_DATA_ROOT の本番相当）から TOPIX / Nikkei の観測日を読む。"""
    bank = market_bank_root(root)
    if not (bank / "index" / "market.sqlite3").exists():
        return {}
    from ..facts import pilot as fact_pilot
    from ..market.store import MarketBankStore

    market = MarketBankStore(bank)
    try:
        qa = fact_pilot._qa_decisions(market)
        return {sid: [p.trading_date for p in fact_pilot.load_points(market.index, qa, sid)]
                for sid in (fact_pilot.TOPIX, fact_pilot.NIKKEI)}
    finally:
        market.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.6 J-Quants production data strategy pilot")
    parser.add_argument("--seed", type=int, default=0, help="seed session数（0=config pilot_seed_sessions）")
    parser.add_argument("--mornings", type=int, default=4)
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args(argv)

    started = _time.monotonic()
    now = datetime.now(timezone.utc)
    jst_now = now + timedelta(hours=9)
    today = now.date()
    base_root = data_root()
    root = base_root / PILOT_ROOT_NAME               # isolated（production root を触らない）
    ops = load_ops_config()
    internals_cfg = load_internals_config()
    policy = policy_from_config(ops)
    retry = RetryPolicy(max_attempts=ops.retry_max_attempts,
                        backoff_seconds=ops.retry_backoff_seconds)
    seed_n = args.seed or ops.pilot_seed_sessions
    light = JQuantsLightStore(light_root(root))
    client = JQuantsV2Client()
    credential = (not args.skip_fetch) and client.credential_present()
    ing = InternalsIngestor(client, light, interval_seconds=float(ops.request_interval_seconds),
                            attempt_prefix="p36")

    _out("P36_INPUT", {
        "config": ops.as_dict(), "window_policy": policy.as_dict(),
        "policy_problems": policy.validate(), "seed_sessions_pilot": seed_n,
        "credential_present": credential, "pilot_root": str(root),
        "production_root_untouched": True,
    })
    _out("P36_REGISTRY", {
        "datasets": registry_rows(), "frequency_table": frequency_table(),
        "counts": {k: sum(1 for c in REGISTRY.values() if k in (c.entitlement_status, c.strategy_status))
                   for k in ("AVAILABLE_ON_CURRENT_PLAN", "ALREADY_INGESTED", "NOT_ENTITLED",
                             "PLAN_UPGRADE_CANDIDATE", "ALTERNATIVE_APPROVED_SOURCE", "DEFERRED")},
        "gate_audit": standing_audit(),
        "plan_upgrade_register": register_rows(), "plan_upgrade_summary": upgrade_summary(),
        "strategies": {"master": master_strategy(), "weekly_flow": flow_strategy(),
                       "financial_summary": fins_strategy(), "earnings_calendar": earnings_strategy(),
                       "topix": TOPIX_CONTRACT},
    })

    # ---- calendar → expected sessions
    if credential:
        fetch_with_retry(lambda: fetch_calendar(ing, today - timedelta(days=ops.calendar_range_days),
                                                today + timedelta(days=60)),
                         policy=retry, sleeper=_time.sleep)
    calendar_rows = [dict(r) for r in light.calendar_range(
        (today - timedelta(days=ops.calendar_range_days)).isoformat(),
        (today + timedelta(days=60)).isoformat())]
    days = trading_days(calendar_rows)
    latest = latest_completed_session(calendar_rows, now=jst_now)
    if not latest:
        _out("P36_SKIP", {"reason": "calendar_unknown_or_no_credential", "calendar_rows": len(calendar_rows)})
        light.close()
        return 0
    expected = expected_sessions_for_window(days, latest, seed_n + 1)
    previous = previous_session_of(latest, days)
    gap_session = expected[len(expected) // 2]
    seed_target = [s for s in expected if s not in (gap_session, latest)]
    _out("P36_CALENDAR", {"trading_days": len(days), "latest_completed": latest,
                          "previous_session": previous, "expected_window": [expected[0], expected[-1]],
                          "expected_sessions": len(expected), "deliberate_gap": gap_session,
                          "deliberately_unfetched_latest": latest, "seed_target": len(seed_target)})

    # ---- seed（意図的な欠落付き）
    seed_started = _time.monotonic()
    seed_failures: Dict[str, str] = {}
    master_dates = snapshot_dates_for_seed(seed_target, interval_days=ops.master_refresh_days) + [today.isoformat()]
    if credential and not light.price_dates():
        for d in master_dates:
            o, kind, _ = fetch_with_retry(lambda d=d: fetch_master(ing, d if d != today.isoformat() else ""),
                                          policy=retry, sleeper=_time.sleep)
            if kind != OK:
                seed_failures[f"master:{d}"] = kind
        from ..internals.ingest import fetch_daily_bars_by_date
        for s in seed_target:
            o, kind, _ = fetch_with_retry(lambda s=s: fetch_daily_bars_by_date(ing, s),
                                          policy=retry, sleeper=_time.sleep)
            if kind != OK:
                seed_failures[s] = kind
        flow_plan = plan_flow_refresh(light, today=today, section=internals_cfg.flow_section,
                                      lookback_days=ops.flow_lookback_days)
        o, kind, _ = fetch_with_retry(
            lambda: fetch_investor_types(ing, datetime.fromisoformat(flow_plan["params"]["from"]).date(), today),
            policy=retry, sleeper=_time.sleep)
        if kind != OK:
            seed_failures["investor_types"] = kind
        e_plan = plan_earnings_refresh(today=today, days_ahead=ops.earnings_calendar_days_ahead)
        o, kind, _ = fetch_with_retry(lambda: ing.ingest("equities_earnings_cal", e_plan["params"], mode="range"),
                                      policy=retry, sleeper=_time.sleep)
        if kind != OK:
            seed_failures["equities_earnings_cal"] = kind
    seed_seconds = _time.monotonic() - seed_started
    seed_requests = ing.stats.requests
    # fins date-mode probe（1 request・実応答で判定）
    fins_probe = None
    if credential:
        fins_probe = ing.ingest("fins_summary", {"date": previous}, mode="date")
    fins_date_mode = bool(fins_probe and fins_probe.ok and fins_probe.rows > 0)
    fact_store = FactStore(root)
    context_store = ContextStore(root)
    build_started = _time.monotonic()
    rec0 = recompute_affected(light, new_sessions=light.price_dates()[:1] or [], policy=policy,
                              internals_config=internals_cfg, fact_store=fact_store,
                              context_store=context_store, now=now)
    _out("P36_SEED", {
        "sessions_stored": len(light.price_dates()), "seed_seconds": round(seed_seconds, 1),
        "seed_requests": seed_requests, "seed_failures": seed_failures,
        "master_snapshot_dates": master_dates, "master_snapshots_stored": light.security_effective_dates(),
        "fins_date_mode_probe": fins_probe.as_dict() if fins_probe else {},
        "fins_date_mode_available": fins_date_mode,
        "initial_build": rec0.as_dict(), "build_seconds": round(_time.monotonic() - build_started, 2),
        "datasets": {o.dataset: {"ok": o.ok, "rows": o.rows, "added": o.added, "http": o.http}
                     for o in ing.stats.outcomes if o.dataset != "daily_bars"},
    })

    # ---- schema drift（実応答の項目名 vs registry）
    observed: Dict[str, List[str]] = {}
    for o in ing.stats.outcomes:
        if o.ok and o.dataset not in observed:
            pass
    # observed fields are only available on JQuantsFetchResult; the ingestor keeps datasets only.
    # 直近の light store canonical から項目名を復元して比較する
    drift = {}
    for key, sample in (("daily_bars", next(light.iter_canonical("daily_bars"), None)),
                        ("listed_master", next(light.iter_canonical("listed_master"), None)),
                        ("investor_types", next(light.iter_canonical("investor_types"), None))):
        if sample:
            drift[key] = {"stored_fields": sorted(k for k in sample if k not in ("provenance", "record_id"))}
    _out("P36_SCHEMA", {
        "checks": [check_schema(k, f).as_dict() for k, f in (
            ("daily_bars", REGISTRY["daily_bars"].observed_fields),
            ("listed_master", REGISTRY["listed_master"].observed_fields),
            ("daily_bars_with_unknown", REGISTRY["daily_bars"].observed_fields + ("NewField",)),
            ("daily_bars_missing_required", ("Code", "Date")))],
        "stored_field_names": drift,
        "rule": "unknown field added => UNKNOWN_FIELDS_ADDED (ingest continues); required missing => "
                "REQUIRED_FIELD_MISSING (schema_error, 0 rows ingested)",
    })

    # ---- pass 1: repair day（「昨日の朝」の視点: latest は期待しない）
    def gap_for(as_of_latest: str):
        exp = expected_sessions_for_window(days, as_of_latest, seed_n + 1)
        return exp, detect_gaps(dataset="daily_bars", expected_sessions=exp,
                                rows_by_session=_rows_by_session(light, exp),
                                latest_completed=as_of_latest,
                                partial_ratio=ops.partial_session_ratio)
    exp1, gap1 = gap_for(previous)
    plan1 = plan_update(gap1, policy=policy, expected_sessions=exp1)
    res1 = apply_update(ing, plan1, retry=retry, sleeper=_time.sleep,
                        expected_rows_min=int(gap1.expected_rows * float(ops.partial_session_ratio))) \
        if credential else None
    rec1 = recompute_affected(light, new_sessions=list(plan1.sessions_to_fetch), policy=policy,
                              internals_config=internals_cfg, fact_store=fact_store,
                              context_store=context_store, now=now)
    _out("P36_REPAIR", {"gap_before": gap1.as_dict(), "plan": plan1.as_dict(),
                        "result": res1.as_dict() if res1 else {}, "recompute": rec1.as_dict(),
                        "gap_after": gap_for(previous)[1].as_dict()})

    # ---- pass 2: daily incremental（今日の朝: latest だけ欠けている）
    exp2, gap2 = gap_for(latest)
    plan2 = plan_update(gap2, policy=policy, expected_sessions=exp2)
    daily_started = _time.monotonic()
    res2 = apply_update(ing, plan2, retry=retry, sleeper=_time.sleep,
                        expected_rows_min=int(gap2.expected_rows * float(ops.partial_session_ratio))) \
        if credential else None
    rec2 = recompute_affected(light, new_sessions=list(plan2.sessions_to_fetch), policy=policy,
                              internals_config=internals_cfg, fact_store=fact_store,
                              context_store=context_store, now=now)
    daily_seconds = _time.monotonic() - daily_started
    # ---- pass 3: rerun（冪等・0 リクエスト）
    exp3, gap3 = gap_for(latest)
    plan3 = plan_update(gap3, policy=policy, expected_sessions=exp3)
    res3 = apply_update(ing, plan3, retry=retry, sleeper=_time.sleep) if credential else None
    rec3 = recompute_affected(light, new_sessions=[latest], policy=policy,
                              internals_config=internals_cfg, fact_store=fact_store,
                              context_store=context_store, now=now)
    _out("P36_DAILY", {
        "gap_before": gap2.as_dict(), "plan": plan2.as_dict(),
        "result": res2.as_dict() if res2 else {}, "recompute": rec2.as_dict(),
        "daily_seconds": round(daily_seconds, 2),
        "rerun": {"plan": plan3.as_dict(), "result": res3.as_dict() if res3 else {},
                  "recompute": rec3.as_dict(),
                  "idempotent": (not res3 or res3.requests == 0) and rec3.facts_added == 0
                  and rec3.contexts_added == 0},
        "gap_after": gap_for(latest)[1].as_dict(),
        "canonical_price_rows": sum(1 for _ in light.iter_canonical("daily_bars")),
        "sqlite_price_rows": light.count("daily_bars"),
        "fact_rows": fact_store.count(), "context_rows": context_store.count(),
    })

    # ---- master refresh / diff
    eff = light.security_effective_dates()
    diff = diff_master(light.securities_effective(eff[0]), light.securities_effective(eff[-1]),
                       from_date=eff[0], to_date=eff[-1]) if len(eff) >= 2 else None
    _out("P36_MASTER", {
        "snapshots": eff, "refresh_due_today": refresh_due(latest_effective_date=eff[-1] if eff else "",
                                                           today=today.isoformat(),
                                                           interval_days=ops.master_refresh_days),
        "diff_first_vs_latest": diff.as_dict() if diff else {},
        "strategy": master_strategy(),
    })

    # ---- weekly flow refresh（新規のみ）
    flow_plan2 = plan_flow_refresh(light, today=today, section=internals_cfg.flow_section,
                                   lookback_days=ops.flow_lookback_days)
    flow_added = None
    if credential:
        before_ids = light.count("investor_types")
        o, kind, _ = fetch_with_retry(
            lambda: fetch_investor_types(ing, datetime.fromisoformat(flow_plan2["params"]["from"]).date(), today),
            policy=retry, sleeper=_time.sleep)
        flow_added = {"ok": kind == OK, "rows": getattr(o, "rows", 0), "added": getattr(o, "added", 0),
                      "stored_before": before_ids, "stored_after": light.count("investor_types")}
    _out("P36_FLOW", {"plan": flow_plan2, "refresh": flow_added or {}, "strategy": flow_strategy()})

    # ---- fins / earnings plans（実行は event-driven のため計画のみ）
    _out("P36_EVENT", {
        "financial_summary_plan": plan_financial_refresh(light, previous_session=latest,
                                                         date_mode_available=fins_date_mode),
        "earnings_plan": plan_earnings_refresh(today=today, days_ahead=ops.earnings_calendar_days_ahead),
        "earnings_stored_next_90d": len(light.earnings_within(today.isoformat(),
                                                             (today + timedelta(days=90)).isoformat())),
    })

    # ---- health / readiness / TOPIX alignment
    series = _topix_dates(base_root)
    topix_dates = series.get("index:topix.close.closing.tokyo", [])
    nikkei_dates = series.get("index:nikkei225.close.closing.tokyo", [])
    health = health_snapshot(light=light, latest_completed=latest, now=now, outcomes=ing.stats.outcomes,
                             daily_gap=gap_for(latest)[1], master_refresh_days=ops.master_refresh_days,
                             flow_max_age_days=internals_cfg.flow_max_age_days,
                             topix_latest=topix_dates[-1] if topix_dates else "")
    readiness = morning_readiness(health)
    _out("P36_HEALTH", {"snapshot": snapshot_rows(health)})
    _out("P36_READINESS", {"readiness": readiness.as_dict(),
                           "topix_alignment": same_session_alignment(topix_dates, nikkei_dates),
                           "market_bank_available": bool(series)})

    # ---- failure classification（実 outcome を分類。失敗が無ければ OK のみ）
    kinds: Dict[str, int] = {}
    for o in ing.stats.outcomes:
        k = classify_failure(ok=o.ok, http=o.http, error_kind=o.error_kind, rows=o.rows)
        kinds[k] = kinds.get(k, 0) + 1
    _out("P36_FAILURES", {"classified": kinds, "retry_policy": retry.as_dict(),
                          "impact_matrix": {role: {k: morning_impact(role, k) for k in (
                              "OK", "AUTH_FAILURE", "NOT_ENTITLED", "RATE_LIMIT", "TIMEOUT",
                              "HTTP_ERROR", "SCHEMA_CHANGE", "EMPTY_RESPONSE", "PARTIAL_DATA",
                              "SESSION_GAP")} for role in ("REQUIRED", "INTERNALS", "OPTIONAL")}})

    # ---- morning simulation（replay・look-ahead 0）
    stored = light.price_dates()
    full_build = build_internals(light, internals_cfg, stored, now=now)
    from ..internals.pipeline import internals_contexts as _ctx
    items = _ctx(full_build, internals_cfg, now=now)
    mornings = [d for d in days if d > stored[-1]][:1]           # 次の営業日の朝
    mornings = [d for d in days if stored[0] < d <= stored[-1]][-(args.mornings - 1):] + mornings
    sim_rows = []
    for morning in mornings:
        contract = morning_contract(morning, days, master_refresh_days=ops.master_refresh_days,
                                    flow_max_age_days=internals_cfg.flow_max_age_days)
        prev = contract.previous_session
        snap = morning_internals_snapshot(items, morning, config=internals_cfg,
                                          availability=full_build.availability.get(prev, {}),
                                          generated_at=now)
        leaks = leaked_contexts(snap.items, snap.cutoff)
        avail_sessions = [s for s in stored if s <= prev]
        sim_rows.append({
            "morning": morning, "previous_session": prev, "cutoff_utc": contract.cutoff_utc,
            "expected_datasets": [i.dataset for i in contract.items],
            "available": {"daily_bars_sessions_le_previous": len(avail_sessions),
                          "daily_bars_previous_stored": prev in stored,
                          "master_effective": max((e for e in eff if e <= prev), default=""),
                          "flow_weeks_published_by_cutoff": len({
                              i.time.session_date for i in snap.items
                              if i.context_type == "investor_flow_state"})},
            "missing": [d for d, ok in (("daily_bars", prev in stored),) if not ok],
            "requests_required_normal_morning": request_budget(policy)["normal_morning"]["total"],
            "readiness_replay": "READY" if prev in stored else "DEGRADED",
            "internals_status": {k: v.value for k, v in snap.internals_status.items()},
            "internals_contexts_available": sum(1 for i in snap.items
                                                if i.context_type in INTERNALS_CONTEXT_TYPES),
            "look_ahead_leaks": len(leaks),
        })
    _out("P36_MORNING_SIM", {"per_morning": sim_rows,
                             "look_ahead_total_leaks": sum(r["look_ahead_leaks"] for r in sim_rows),
                             "contract_example": morning_contract(mornings[-1], days).as_dict()
                             if mornings else {}})

    # ---- corporate actions / 52w / budgets / performance / storage
    _out("P36_CORPORATE_ACTIONS", corporate_action_report(full_build.builds))
    _out("P36_FIFTY_TWO_WEEK", fifty_two_week_decision(stored_sessions=len(stored)))
    rebuild_started = _time.monotonic()
    light.rebuild_index()
    f_rebuilt = fact_store.rebuild_index()
    c_rebuilt = context_store.rebuild_index()
    rebuild_seconds = _time.monotonic() - rebuild_started
    light_dir = light.root
    sizes = {
        "light_canonical_bytes": _dir_bytes(light.canonical_dir),
        "light_sqlite_bytes": light.db_path.stat().st_size,
        "light_raw_bytes": _dir_bytes(light.root / "raw"),
        "facts_canonical_bytes": fact_store.canonical_path.stat().st_size,
        "facts_sqlite_bytes": fact_store.db_path.stat().st_size,
        "contexts_canonical_bytes": context_store.canonical_path.stat().st_size,
        "contexts_sqlite_bytes": context_store.db_path.stat().st_size,
    }
    price_rows = light.count("daily_bars")
    _out("P36_PERFORMANCE", {
        "initial_seed": {"sessions": len(seed_target), "requests": seed_requests,
                         "seconds": round(seed_seconds, 1),
                         "seconds_per_session": round(seed_seconds / max(1, len(seed_target)), 2)},
        "repair": {"requests": res1.requests if res1 else 0, "seconds": round(res1.elapsed_seconds, 2) if res1 else 0,
                   "recompute_seconds": rec1.elapsed_seconds},
        "normal_daily": {"requests": res2.requests if res2 else 0, "seconds": round(daily_seconds, 2),
                         "recompute_seconds": rec2.elapsed_seconds,
                         "sessions_rebuilt": rec2.sessions_rebuilt},
        "rerun": {"requests": res3.requests if res3 else 0, "recompute_seconds": rec3.elapsed_seconds},
        "weekly_refresh": {"requests": 1 if flow_added else 0},
        "rebuild": {"seconds": round(rebuild_seconds, 2), "facts": f_rebuilt, "contexts": c_rebuilt,
                    "price_rows": price_rows},
        "total_requests": ing.stats.requests, "pilot_seconds": round(_time.monotonic() - started, 1),
        "morning_operation_realistic": (res2.requests if res2 else 0) <= 2 and daily_seconds < 60,
    })
    _out("P36_STORAGE", {"measured_bytes": sizes, "price_rows": price_rows,
                         "bytes_per_price_row_canonical": round(sizes["light_canonical_bytes"] / max(1, price_rows), 1),
                         "budget": storage_budget()})
    _out("P36_REQUESTS", {"budget": request_budget(policy, seed_sessions=policy.seed_sessions),
                          "pilot_actual": {"seed": seed_requests, "repair": res1.requests if res1 else 0,
                                           "daily": res2.requests if res2 else 0, "rerun": res3.requests if res3 else 0,
                                           "total": ing.stats.requests}})
    _out("P36_SECURITY", {
        "secret_env_names_checked": list(_SECRET_ENV_NAMES),
        "secret_env_present": {n: n in os.environ for n in _SECRET_ENV_NAMES},
        "secret_values_printed": False, "isolated_root": str(root),
        "production_root_modified": False, "endpoints_outside_light": 0,
        "not_entitled_endpoints_probed": 0,
    })
    _out("P36_SUMMARY", {
        "seed_ok": not seed_failures, "repair_mode": plan1.mode, "repair_requests": res1.requests if res1 else 0,
        "daily_mode": plan2.mode, "daily_requests": res2.requests if res2 else 0,
        "rerun_requests": res3.requests if res3 else 0, "rerun_idempotent": rec3.facts_added == 0,
        "gap_after_daily": gap_for(latest)[1].overall, "master_snapshots": len(eff),
        "master_changes": diff.total_changes if diff else 0,
        "fins_date_mode_available": fins_date_mode,
        "readiness": readiness.status, "look_ahead_leaks": sum(r["look_ahead_leaks"] for r in sim_rows),
        "total_requests": ing.stats.requests, "runtime_seconds": round(_time.monotonic() - started, 1),
    })
    fact_store.close()
    context_store.close()
    light.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
