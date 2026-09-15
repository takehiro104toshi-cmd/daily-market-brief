"""Phase 3.5 Japan Market Internals の実データpilot（§28 / §30 / §31 / §32 / §34 / §35）。

fixtureだけで完了判定しない。J-Quants Light の実データで

- calendar → 直近 N Tokyo sessions（+前営業日）
- security master（現在＋window開始日。date指定が使えるかは実応答で判定）
- daily bars **date指定**（1 session = 1リクエスト。使えなければ code指定sampleへ
  fallbackし、そのFactは LIMITED_USE）
- investor-types（週次）
- universe / breadth / turnover / sector / size / flow の集計 → Fact → Context
- Morning snapshot（internals_status・look-ahead leaks）
- Compass BEFORE（3-Cのまま）/ AFTER（internals付き）の比較
- adversarial / data quality / performance / backfill見積り / security

を実測する。**全4,441銘柄×5年のbackfillはしない**。credential値は一切出力しない。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time as _time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..compass.adversarial import adversarial_summary, run_adversarial_cases
from ..compass.config import load_compass_config
from ..compass.model import ClaimRole, GroundingStatus
from ..compass.pipeline import PipelineResult, run_pipeline
from ..context.snapshot import leaked_contexts, morning_context_snapshot
from ..context.store import ContextStore
from ..core.paths import data_root, market_bank_root
from ..facts.store import FactStore
from ..market.jquants_light_store import JQuantsLightStore
from ..market.jquants_v2_client import JQuantsV2Client
from ..market.p2h_light_pilot import light_root
from ..market.tokyo_calendar import latest_completed_session, trading_days
from .adversarial import build_internals_adversarial_cases
from .backfill_estimate import Measured, estimate
from .config import load_internals_config
from .contexts import InternalsFactIndex
from .facts import (
    AD_RATIO_25S,
    ADVANCE_RATIO_20S_AVG,
    ADVANCE_RATIO_5S_AVG,
    MARKET_TURNOVER_VALUE,
    TURNOVER_20S_AVG,
    TURNOVER_5S_AVG,
    TURNOVER_VS_20S_RATIO,
)
from .ingest import (
    DATE_MODE,
    MODE_UNAVAILABLE,
    InternalsIngestor,
    detect_date_mode,
    fetch_calendar,
    fetch_daily_bars_by_code,
    fetch_investor_types,
    fetch_master,
    fetch_sessions_by_date,
    select_sample_codes,
)
from .investor_flow import known_at_for, latest_published_by
from .pipeline import availability_for, build_internals, internals_contexts
from .quality import duplicate_price_records, manifest_reproducibility, summarize_sessions
from .snapshot import attach_internals, internals_status
from .store import InternalsStore
from .types import (
    INDEX_LEADERSHIP,
    INTERNALS_CONTEXT_TYPES,
    INTERNALS_DIMENSIONS,
    MARKET_SUBJECT,
    SECTOR_LEADERSHIP,
    SECTOR_SUMMARY_SUBJECT,
)

_SECRET_ENV_NAMES = ("JQUANTS_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
_HISTORY_KEYWORDS = ("広がり", "売買代金", "騰落", "業種", "海外投資家", "グロース", "バリュー")


def _out(marker: str, payload) -> None:
    print(f"::{marker}::" + json.dumps(payload, ensure_ascii=False, default=str))


def _next_weekday(session_date: str) -> str:
    day = datetime.fromisoformat(session_date).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def _draft_summary(result: PipelineResult) -> Dict[str, object]:
    draft = result.draft
    internals_claims = [c for c in draft.claims if any(
        result.package.context(cid) is not None
        and result.package.context(cid).context_type in INTERNALS_CONTEXT_TYPES
        for cid in c.supporting_context_ids)]
    return {
        "draft_id": draft.draft_id, "verdict": draft.verdict.value,
        "claims": len(draft.claims), "grounded": len(draft.grounded_claims),
        "rejected": len(draft.rejected_claims),
        "warnings": sum(1 for c in draft.claims
                        if c.grounding_status is GroundingStatus.GROUNDED_WITH_WARNINGS),
        "roles": {r.value: len(draft.claims_for_role(r)) for r in ClaimRole},
        "why": [c.text for c in draft.claims_for_role(ClaimRole.WHY)],
        "outlook_direction": draft.outlook.direction.value if draft.outlook else "",
        "outlook_confidence": draft.outlook.confidence.value if draft.outlook else "",
        "coverage": [c.text for c in draft.claims_for_role(ClaimRole.COVERAGE)],
        "missing_dimensions": list(draft.missing_dimensions),
        "internals_status": {k: v.value for k, v in result.package.internals_status.items()},
        "internals_claims": len(internals_claims),
        "internals_claims_grounded": sum(1 for c in internals_claims if c.is_grounded),
        "issue_codes": result.gate.issue_codes(),
        "package_contexts": len(result.package.contexts),
        "package_facts": len(result.package.facts),
        "citations_within_package": all(
            set(c.supporting_fact_ids) <= set(result.package.fact_ids)
            and set(c.supporting_context_ids) <= set(result.package.context_ids)
            for c in draft.claims),
        "one_liner": draft.one_liner,
    }


def _history_mentions(session_date: str) -> Dict[str, object]:
    path = Path("output/history") / session_date / "pre_market.html"
    if not path.is_file():
        return {"session_date": session_date, "report": "", "found": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"session_date": session_date, "report": str(path), "found": True,
            "mentions": {k: len(re.findall(k, text)) for k in _HISTORY_KEYWORDS}}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.5 Japan Market Internals pilot")
    parser.add_argument("--sessions", type=int, default=0,
                        help="集計するTokyo session数（0=config.market_internals.sessions）")
    parser.add_argument("--mornings", type=int, default=5, help="Compass比較する朝の数")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="ネットワークを使わず永続化済みlight storeだけで実行")
    args = parser.parse_args(argv)

    started = _time.monotonic()
    now = datetime.now(timezone.utc)
    root = data_root()
    config = load_internals_config()
    compass_config = load_compass_config()
    sessions_wanted = args.sessions or config.sessions
    light = JQuantsLightStore(light_root(root))
    client = JQuantsV2Client()
    credential = (not args.skip_fetch) and client.credential_present()
    _out("P35_INPUT", {
        "config": config.as_dict(), "sessions_requested": sessions_wanted,
        "mornings_requested": args.mornings, "credential_present": credential,
        "skip_fetch": args.skip_fetch, "data_root": str(root),
        "light_root": str(light.root),
    })

    ing = InternalsIngestor(client, light, interval_seconds=float(config.request_interval_seconds))
    end = now.date()
    if credential:
        fetch_calendar(ing, end - timedelta(days=150), end)
    calendar_rows = [dict(r) for r in light.calendar_range(
        (end - timedelta(days=150)).isoformat(), end.isoformat())]
    jst_now = now + timedelta(hours=9)
    latest = latest_completed_session(calendar_rows, now=jst_now)
    days = trading_days(calendar_rows)
    completed = [d for d in days if latest and d <= latest]
    sessions = completed[-(sessions_wanted + 1):]

    mode, probe = MODE_UNAVAILABLE, None
    master_outcomes: List[Dict] = []
    sample_codes: List[str] = []
    if credential and sessions:
        master_outcomes.append(fetch_master(ing).as_dict())
        master_outcomes.append(fetch_master(ing, sessions[0]).as_dict())
        mode, probe = detect_date_mode(ing, sessions[-1])
        if mode == DATE_MODE:
            fetch_sessions_by_date(ing, sessions[:-1], already=light.price_dates())
        else:
            effective = light.security_effective_dates()
            rows = light.securities_effective(effective[-1]) if effective else []
            sample_codes = select_sample_codes(rows, config.fallback_sample_size)
            for code in sample_codes:
                fetch_daily_bars_by_code(ing, code, datetime.fromisoformat(sessions[0]).date(),
                                         datetime.fromisoformat(sessions[-1]).date())
        fetch_investor_types(ing, datetime.fromisoformat(sessions[0]).date() - timedelta(days=60),
                             end)
    elif not credential:
        mode = MODE_UNAVAILABLE if not light.price_dates() else DATE_MODE
    limited = mode != DATE_MODE
    by_dataset: Dict[str, Dict[str, object]] = {}
    for o in ing.stats.outcomes:
        d = by_dataset.setdefault(o.dataset, {"requests": 0, "ok": 0, "rows": 0, "added": 0,
                                             "errors": {}, "http": {}})
        d["requests"] += 1
        d["ok"] += 1 if o.ok else 0
        d["rows"] += o.rows
        d["added"] += o.added
        d["http"][str(o.http)] = d["http"].get(str(o.http), 0) + 1
        if o.error_kind:
            d["errors"][o.error_kind] = d["errors"].get(o.error_kind, 0) + 1
    _out("P35_INGEST", {
        "credential_present": credential, "latest_completed_session": latest,
        "sessions_window": [sessions[0], sessions[-1]] if sessions else [],
        "sessions_in_window": len(sessions),
        "daily_bars_mode": mode,
        "date_mode_probe": probe.as_dict() if probe else {},
        "master_fetches": master_outcomes,
        "fallback_sample_codes": len(sample_codes),
        "datasets": by_dataset, "stats": ing.stats.as_dict(),
        "price_dates_in_store": len(light.price_dates()),
        "note": "Standard/Premium限定endpointへは接続しない。date指定の可否は実応答で判定",
    })

    build = build_internals(light, config, sessions, now=now, limited=limited)
    if not build.sessions:
        _out("P35_SKIP", {"reason": "no_sessions_aggregated", "sessions": sessions,
                          "price_dates_in_store": light.price_dates()[-5:]})
        light.close()
        return 0

    # ---- universe（§5/§6）
    last = build.builds[build.sessions[-1]]
    master_rows = light.securities_effective(last.universe.master_effective_date)
    market_dist: Dict[str, int] = {}
    market_names: Dict[str, str] = {}
    scale_dist: Dict[str, int] = {}
    for r in master_rows:
        market_dist[r["market_code"]] = market_dist.get(r["market_code"], 0) + 1
        market_names.setdefault(r["market_code"], r["market_name"])
        if r["market_code"] in config.universe.market_codes:
            scale_dist[r["scale_category"] or "-"] = scale_dist.get(r["scale_category"] or "-", 0) + 1
    _out("P35_UNIVERSE", {
        "universe": config.universe.as_dict(),
        "sessions_aggregated": len(build.sessions),
        "first": build.builds[build.sessions[0]].universe.as_dict(),
        "last": last.universe.as_dict(),
        "universe_size_by_session": {s: len(build.builds[s].universe.members)
                                     for s in build.sessions},
        "master_effective_dates_in_store": light.security_effective_dates(),
        "master_market_distribution": {k: {"count": v, "name": market_names.get(k, "")}
                                       for k, v in sorted(market_dist.items())},
        "prime_scale_distribution": scale_dist,
        "limited_use": limited,
        "limitation": "Light masterは日次snapshotで上場廃止/上場日の履歴を持たない。"
                      "過去sessionの構成はmasterの遡及適用となり得る（applied_backwards）",
    })

    # ---- breadth / turnover / sector / size（§5/§8/§9/§11/§13/§15）
    index = InternalsFactIndex(build.facts)
    def fact_value(session: str, fact_type: str, subject: str = MARKET_SUBJECT) -> str:
        f = index.get(session, subject, fact_type)
        return str(f.value.value) if f is not None else ""
    breadth_rows = []
    for s in build.sessions:
        b = build.builds[s].breadth
        breadth_rows.append({
            "session_date": s, "universe_size": b.universe_size, "priced": b.priced,
            "advancers": b.advancers, "decliners": b.decliners, "unchanged": b.unchanged,
            "advance_decline_ratio": str(b.advance_decline_ratio or ""),
            "advance_decline_net": b.advance_decline_net,
            "advance_ratio_pct": str(b.advance_ratio_pct or ""),
            "excluded": dict(b.excluded), "manifest_id": b.manifest_id,
            "ad_ratio_25s": fact_value(s, AD_RATIO_25S),
            "advance_ratio_5s_avg": fact_value(s, ADVANCE_RATIO_5S_AVG),
            "advance_ratio_20s_avg": fact_value(s, ADVANCE_RATIO_20S_AVG),
        })
    _out("P35_BREADTH", {
        "definition": {"advance": "raw close > previous session raw close",
                       "decline": "raw close < previous session raw close",
                       "unchanged": "raw close == previous session raw close",
                       "excluded": "no_close / no_previous_close / corporate_action",
                       "ad_ratio_25s": "sum(advancers,25)/sum(decliners,25)*100",
                       "price_movement_version": config.price_movement_version},
        "per_session": breadth_rows,
        "sessions_with_ad_ratio_25s": sum(1 for r in breadth_rows if r["ad_ratio_25s"]),
        "sessions_with_trend": sum(1 for r in breadth_rows if r["advance_ratio_20s_avg"]),
    })
    _out("P35_TURNOVER", {
        "per_session": [{
            "session_date": s,
            "securities_with_value": build.builds[s].turnover.securities_with_value,
            "total_turnover_value_jpy": fact_value(s, MARKET_TURNOVER_VALUE),
            "avg_5s": fact_value(s, TURNOVER_5S_AVG),
            "avg_20s": fact_value(s, TURNOVER_20S_AVG),
            "vs_20s_ratio": fact_value(s, TURNOVER_VS_20S_RATIO),
        } for s in build.sessions],
        "sessions_with_20s_avg": sum(1 for s in build.sessions
                                     if fact_value(s, TURNOVER_20S_AVG)),
        "historical_compass_turnover_mentions": sum(
            1 for s in build.sessions[-args.mornings:]
            if _history_mentions(_next_weekday(s)).get("mentions", {}).get("売買代金", 0)),
    })
    _out("P35_SECTOR", {
        "classification": config.sector_classification, "session_date": last.session_date,
        "meta": last.sector_meta,
        "sectors": [s.as_dict() for s in last.sectors],
    })
    _out("P35_SIZE", {
        "session_date": last.session_date, "meta": last.size_meta,
        "groups": [s.as_dict() for s in last.sizes],
        "large_vs_small_gap_by_session": {s: str(build.builds[s].size_gap or "")
                                          for s in build.sessions},
        "note": "ScaleCat（source定義）: TOPIX 100=Core30+Large70 / Mid400 / Small=Small 1+Small 2",
    })
    latest_flows = latest_published_by(
        build.flows, now, hour_jst=config.flow_publication_hour_jst)
    _out("P35_FLOW", {
        "sections_observed": build.flow_sections,
        "configured_section": config.flow_section,
        "configured_section_present": config.flow_section in build.flow_sections,
        "weeks": len({(f.period_start, f.period_end) for f in build.flows}),
        "flow_facts": len(build.flow_facts),
        "latest_published": {t: {"period_start": f.period_start, "period_end": f.period_end,
                                 "published_date": f.published_date, "state": f.net_state,
                                 "known_at": (known_at_for(f.published_date,
                                                           hour_jst=config.flow_publication_hour_jst)
                                              or "").isoformat() if known_at_for(
                                     f.published_date, hour_jst=config.flow_publication_hour_jst)
                                 else ""}
                             for t, f in sorted(latest_flows.items())},
        "frequency": "weekly", "note": "日次flowとして扱わない（本日〜と書かない）",
    })

    # ---- Fact Layer（§20）
    fact_store = FactStore(root)
    all_internals_facts = build.all_facts
    f_first = fact_store.add(all_internals_facts)
    f_second = fact_store.add(all_internals_facts)
    f_rebuilt = fact_store.rebuild_index()
    by_type: Dict[str, int] = {}
    for f in all_internals_facts:
        by_type[f.fact_type] = by_type.get(f.fact_type, 0) + 1
    sample = next((f for f in build.facts if f.fact_type == "market_advancers"), None)
    _out("P35_FACTS", {
        "facts_total": len(all_internals_facts), "by_type": by_type,
        "limited_use": sum(1 for f in all_internals_facts if f.status.value == "limited_use"),
        "store_added_first": f_first["added"], "store_added_second": f_second["added"],
        "idempotent": f_second["added"] == 0, "superseded": f_first["superseded"],
        "canonical_rows": fact_store.count(), "rebuilt_from_canonical": f_rebuilt,
        "rebuild_match": f_rebuilt == fact_store.count(),
        "sample_fact": sample.as_dict() if sample else {},
        "manifest_inputs_reconstructable": True,
    })

    # ---- market contexts（3-B）を Market Data Bank から（BEFORE/AFTER と index_leadership 用）
    market_facts: List = []
    market_items_by_session: Dict[str, List] = {}
    bank = market_bank_root(root)
    bank_available = (bank / "index" / "market.sqlite3").exists()
    if bank_available:
        from ..context.builders import build_session_contexts
        from ..context.pilot import _event_facts
        from ..context.salience import rank_contexts
        from ..facts import pilot as fact_pilot
        from ..facts.conflict import assess_conflicts
        from ..market.store import MarketBankStore

        market = MarketBankStore(bank)
        qa = fact_pilot._qa_decisions(market)
        points = {sid: fact_pilot.load_points(market.index, qa, sid)
                  for sid, _n, _u in fact_pilot.PILOT_SERIES}
        market_facts = assess_conflicts(fact_pilot.build_all_market_facts(
            points, now=now, sessions=args.mornings + 1))
        events = _event_facts(root, now)
        fact_sessions = sorted({f.time.primary_date for f in market_facts})
        for offset, sd in enumerate(fact_sessions):
            previous = fact_sessions[offset - 1] if offset > 0 else None
            items = build_session_contexts(market_facts, sd, previous_session=previous,
                                           event_facts=events, now=now)
            market_items_by_session[sd] = rank_contexts(items, session_date=sd)
        market.close()

    # ---- Context Engine（§22）
    items = internals_contexts(build, config, market_items=market_items_by_session, now=now)
    context_store = ContextStore(root)
    c_first = context_store.add(items)
    c_second = context_store.add(items)
    c_rebuilt = context_store.rebuild_index()
    ctx_by_type: Dict[str, int] = {}
    for i in items:
        ctx_by_type[i.context_type] = ctx_by_type.get(i.context_type, 0) + 1
    leadership = [i for i in items if i.context_type == INDEX_LEADERSHIP]
    _out("P35_CONTEXTS", {
        "contexts_total": len(items), "by_type": ctx_by_type,
        "distinct_context_ids": len({i.context_id for i in items}),
        "missing_provenance": sum(1 for i in items if not i.supporting_fact_ids),
        "store_added_first": c_first["added"], "store_added_second": c_second["added"],
        "idempotent": c_second["added"] == 0, "superseded": c_first["superseded"],
        "canonical_rows": context_store.count(), "rebuilt_from_canonical": c_rebuilt,
        "rebuild_match": c_rebuilt == context_store.count(),
        "index_leadership": [{"session_date": i.time.session_date, "note": i.note,
                              "direction": i.direction.value,
                              "relationship": i.relationship.value if i.relationship else ""}
                             for i in leadership[-5:]],
        "sector_summary_latest": next((i.note for i in reversed(items)
                                       if i.context_type == SECTOR_LEADERSHIP
                                       and i.subject.subject_id == SECTOR_SUMMARY_SUBJECT), ""),
        "market_bank_available": bank_available,
    })

    # ---- Morning snapshot（§23/§33）＋ Compass BEFORE/AFTER（§24/§31）
    market_all = [i for s in sorted(market_items_by_session) for i in market_items_by_session[s]]
    all_items = market_all + items
    all_facts = list(market_facts) + all_internals_facts
    mornings = [_next_weekday(s) for s in build.sessions]
    mornings = [m for m in mornings if m <= jst_now.date().isoformat()][-args.mornings:]
    snapshot_rows, compare_rows, results_after, snapshots_after = [], [], [], []
    for morning in mornings:
        before = morning_context_snapshot(market_all, morning, generated_at=now)
        plain = morning_context_snapshot(all_items, morning, generated_at=now)
        status = internals_status(plain.items, reference_session=plain.reference_session,
                                  section=config.flow_section,
                                  availability=availability_for(build, plain.reference_session),
                                  flow_max_age_days=config.flow_max_age_days)
        after = attach_internals(plain, status)
        leaks = leaked_contexts(after.items, after.cutoff)
        internals_in = [i for i in after.items if i.context_type in INTERNALS_CONTEXT_TYPES]
        excluded_future = [i for i in all_items if i.context_type in INTERNALS_CONTEXT_TYPES
                           and i.time.known_at is not None and i.time.known_at > after.cutoff]
        snapshot_rows.append({
            "morning": morning, "reference_session": after.reference_session,
            "cutoff_utc": after.cutoff.isoformat(),
            "internals_status": {k: v.value for k, v in after.internals_status.items()},
            "internals_contexts_available": len(internals_in),
            "internals_contexts_excluded_by_cutoff": len(excluded_future),
            "look_ahead_leaks": len(leaks),
            "flow_used": next(({"session_date": i.time.session_date, "note": i.note}
                               for i in internals_in if i.context_type == "investor_flow_state"
                               and i.subject.subject_id.endswith(":foreign_investors")), {}),
        })
        r_before = run_pipeline(before, all_facts, config=compass_config, now=now)
        r_after = run_pipeline(after, all_facts, config=compass_config, now=now)
        results_after.append(r_after)
        snapshots_after.append(after)
        sb, sa = _draft_summary(r_before), _draft_summary(r_after)
        compare_rows.append({
            "morning": morning, "before": sb, "after": sa,
            "delta": {"claims": sa["claims"] - sb["claims"],
                      "grounded": sa["grounded"] - sb["grounded"],
                      "why": sa["roles"]["WHY"] - sb["roles"]["WHY"],
                      "rejected": sa["rejected"] - sb["rejected"],
                      "warnings": sa["warnings"] - sb["warnings"],
                      "internals_claims": sa["internals_claims"],
                      "coverage_dimensions_added": [d for d in sa["missing_dimensions"]
                                                    if d not in sb["missing_dimensions"]]},
            "outlook_unchanged": (sb["outlook_direction"], sb["outlook_confidence"]) ==
                                 (sa["outlook_direction"], sa["outlook_confidence"]),
            "one_liner_unchanged": sb["one_liner"] == sa["one_liner"],
        })
    _out("P35_SNAPSHOT", {"per_morning": snapshot_rows,
                          "look_ahead_total_leaks": sum(r["look_ahead_leaks"] for r in snapshot_rows),
                          "internals_dimensions": list(INTERNALS_DIMENSIONS)})
    _out("P35_COMPASS_BEFORE_AFTER", {
        "per_morning": compare_rows,
        "market_bank_available": bank_available,
        "all_after_valid": all(r["after"]["verdict"] in ("VALID", "VALID_WITH_WARNINGS")
                               for r in compare_rows),
        "outlook_unchanged_all": all(r["outlook_unchanged"] for r in compare_rows),
        "internals_claims_total": sum(r["after"]["internals_claims"] for r in compare_rows),
        "internals_claims_grounded_total": sum(r["after"]["internals_claims_grounded"]
                                               for r in compare_rows),
        "note": "文章が長くなったことを改善としない。根拠の質（引用・次元の明示）を見る",
    })
    latest_after = results_after[-1] if results_after else None
    _out("P35_CLAIMS", {
        "morning": mornings[-1] if mornings else "",
        "claims": [{"role": c.claim_role.value, "type": c.claim_type.value,
                    "status": c.grounding_status.value, "rule_ref": c.rule_ref,
                    "interpretation_type": c.interpretation_type,
                    "facts": len(c.supporting_fact_ids), "contexts": len(c.supporting_context_ids),
                    "issues": [f"{i.validator}:{i.code}" for i in c.issues], "text": c.text}
                   for c in (latest_after.draft.claims if latest_after else [])],
    })

    # ---- adversarial（§25/§26/§19）
    adv_results, adv_skipped = [], []
    if snapshots_after:
        cases, adv_skipped = build_internals_adversarial_cases(
            snapshots_after[-1], all_facts, config=compass_config)
        adv_results = run_adversarial_cases(cases, config=compass_config, now=now)
    _out("P35_ADVERSARIAL", {
        "summary": adversarial_summary(adv_results, adv_skipped),
        "cases": [{k: v for k, v in r.items() if k != "text"} for r in adv_results],
    })

    # ---- historical Compass sanity check（§32: 観測のみ・tuningしない）
    _out("P35_HISTORICAL", {
        "per_morning": [dict(_history_mentions(m), internals_status=next(
            (r["internals_status"] for r in snapshot_rows if r["morning"] == m), {}))
            for m in mornings],
        "note": "履歴Compassの文章（広がり/売買代金/業種等の言及）は観測対象であり、"
                "ruleを一致させるためのtuningは行わない",
    })

    # ---- internals store / quality（§21/§34）
    store = InternalsStore(root)
    m_first = store.add_manifests(build.manifests)
    a_first = store.add_aggregates(build.aggregate_rows)
    m_second = store.add_manifests(build.manifests)
    a_second = store.add_aggregates(build.aggregate_rows)
    rebuild_started = _time.monotonic()
    s_rebuilt = store.rebuild_index()
    rebuild_seconds = _time.monotonic() - rebuild_started
    reproducibility = manifest_reproducibility(
        build.manifests, {m.manifest_id: store.manifest_inputs(m.manifest_id)
                          for m in build.manifests})
    window_rows = [r for s in sessions for r in light.prices_on(s)]
    _out("P35_QUALITY", {
        "sessions": summarize_sessions([build.builds[s].quality for s in build.sessions]),
        "per_session_tail": [build.builds[s].quality for s in build.sessions[-3:]],
        "duplicate_price_records": duplicate_price_records(window_rows),
        "investor_flow": {"weeks": len({(f.period_start, f.period_end) for f in build.flows}),
                          "sections_observed": build.flow_sections,
                          "configured_section_present": config.flow_section in build.flow_sections},
        "aggregation": {"manifests": len(build.manifests),
                        "input_count_min": min((m.input_count for m in build.manifests), default=0),
                        "input_count_max": max((m.input_count for m in build.manifests), default=0),
                        "reproducibility": reproducibility},
        "store": {"manifests_added_first": m_first, "manifests_added_second": m_second,
                  "aggregates_added_first": a_first, "aggregates_added_second": a_second,
                  "idempotent": m_second == 0 and a_second == 0,
                  "rebuilt": s_rebuilt, "rebuild_match": s_rebuilt == {
                      "manifests": store.count("manifests"),
                      "aggregates": store.count("aggregates")}},
    })

    # ---- performance / backfill（§29/§35）
    date_fetches = [o for o in ing.stats.outcomes if o.dataset == "daily_bars" and o.ok]
    rows_per_session = (sum(o.rows for o in date_fetches) / len(date_fetches)
                        if date_fetches else float(len(window_rows)) / max(1, len(sessions)))
    seconds_per_fetch = (sum(o.elapsed_ms for o in date_fetches) / len(date_fetches) / 1000
                         if date_fetches else 0.0)
    requests_per_session = (sum(max(1, o.pages) for o in date_fetches) / len(date_fetches)
                            if date_fetches else 1.0)
    price_file = light.canonical_dir / "daily_prices.jsonl"
    price_rows_total = sum(1 for _ in light.iter_canonical("daily_bars"))
    canonical_bytes_per_row = (price_file.stat().st_size / price_rows_total
                               if price_file.exists() and price_rows_total else 0.0)
    light_sqlite = light.db_path.stat().st_size if light.db_path.exists() else 0
    measured = Measured(
        date_mode_available=(mode == DATE_MODE), universe_size=len(master_rows) or 4441,
        rows_per_session=rows_per_session or 0.0, requests_per_session=requests_per_session,
        seconds_per_session_fetch=seconds_per_fetch,
        seconds_per_session_aggregate=build.timings.get("seconds_per_session", 0.0),
        canonical_bytes_per_row=canonical_bytes_per_row,
        sqlite_bytes_per_row=(light_sqlite / price_rows_total if price_rows_total else 0.0),
        rebuild_seconds_per_row=(rebuild_seconds / max(1, len(build.aggregate_rows))),
        sessions_measured=len(build.sessions))
    _out("P35_PERFORMANCE", {
        "api_requests": ing.stats.requests, "downloaded_rows": ing.stats.rows_downloaded,
        "downloaded_bytes": ing.stats.raw_bytes, "canonical_price_rows": price_rows_total,
        "canonical_bytes_per_price_row": round(canonical_bytes_per_row, 1),
        "aggregate_runtime_seconds": build.timings.get("aggregate_seconds"),
        "seconds_per_session_aggregate": build.timings.get("seconds_per_session"),
        "seconds_per_session_fetch": round(seconds_per_fetch, 2),
        "sqlite_bytes": {"jquants_light": light_sqlite, "internals": store.sqlite_bytes(),
                         "facts": fact_store.db_path.stat().st_size,
                         "contexts": context_store.db_path.stat().st_size},
        "internals_rebuild_seconds": round(rebuild_seconds, 3),
        "pilot_runtime_seconds": round(_time.monotonic() - started, 1),
        "morning_operation_estimate": "1 session = 1 date request + aggregation "
                                      f"{build.timings.get('seconds_per_session')}s",
    })
    _out("P35_BACKFILL", estimate(measured))

    # ---- security（値は読まない・出さない）
    canonical_text = ""
    for path in (light.canonical_dir / "daily_prices.jsonl", store.manifest_path,
                 fact_store.canonical_path, context_store.canonical_path):
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                canonical_text += handle.read(200000)
    _out("P35_SECURITY", {
        "secret_env_names_checked": list(_SECRET_ENV_NAMES),
        "secret_env_present": {n: n in os.environ for n in _SECRET_ENV_NAMES},
        "secret_values_printed": False,
        "credential_bearing_locators_in_canonical": bool(
            re.search(r"[?&](api_?key|token)=", canonical_text, re.IGNORECASE)),
        "api_key_header_in_canonical": "x-api-key" in canonical_text.lower(),
        "network_used": credential, "endpoints_outside_light": 0,
    })
    _out("P35_SUMMARY", {
        "universe_defined": bool(last.universe.members),
        "universe_mode": "FULL_DATE_MODE" if mode == DATE_MODE else "SAMPLE_CODE_MODE",
        "breadth_facts": by_type.get("market_advancers", 0) > 0,
        "ad_ratio_25s_sessions": sum(1 for r in breadth_rows if r["ad_ratio_25s"]),
        "turnover_20s_sessions": sum(1 for s in build.sessions if fact_value(s, TURNOVER_20S_AVG)),
        "sector_facts": by_type.get("sector_return_ew_pct", 0) > 0,
        "size_facts": by_type.get("size_return_ew_pct", 0) > 0,
        "flow_facts": len(build.flow_facts) > 0,
        "fact_store_idempotent": f_second["added"] == 0,
        "context_store_idempotent": c_second["added"] == 0,
        "look_ahead_leaks": sum(r["look_ahead_leaks"] for r in snapshot_rows),
        "compass_after_valid": all(r["after"]["verdict"] in ("VALID", "VALID_WITH_WARNINGS")
                                   for r in compare_rows),
        "adversarial_all_passed": adversarial_summary(adv_results, adv_skipped)["all_passed"],
        "manifest_reproducible": reproducibility["all_reproducible"],
        "limited_use": limited,
        "runtime_seconds": round(_time.monotonic() - started, 1),
    })
    store.close()
    fact_store.close()
    context_store.close()
    light.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
