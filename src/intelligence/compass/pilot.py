"""Phase 3-C Compass Generator の実データpilot（§34 / §35 / §36）。

fixtureだけで完了判定しない。Phase 3-A/3-Bと**同じ生成経路**の実Fact／Context
（Market Data Bank由来）を入力に、直近の複数Tokyo sessionの朝時点で

- Evidence Package（budget・look-ahead除外・次元status）
- Outlook / Narrative Plan（決定論的）
- claim生成 → Quality gate（全validator）→ one-liner → CompassDraft
- adversarial cases（§36: 捏造claimは必ずREJECT）
- 永続化（append-only + SQLite再構築 + 冪等性）
- 過去Compass（output/history/<date>/pre_market.html）との評価（§35）

を実測する。generatorは**決定論的**（LLM providerは本repositoryに存在しないため
接続しない・API keyを要求しない・secretを作らない）。**新規fetchは行わない**。
出力にcredential値は一切含めない（環境変数の値は読まない・表示しない）。
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from ..core.paths import data_root, market_bank_root
from ..facts import pilot as fact_pilot
from ..facts.conflict import assess_conflicts
from ..context.builders import build_session_contexts
from ..context.pilot import _event_facts
from ..context.salience import rank_contexts
from ..context.snapshot import morning_context_snapshot
from .adversarial import adversarial_summary, build_adversarial_cases, run_adversarial_cases
from .config import load_compass_config
from .generator import DETERMINISTIC
from .historical_eval import evaluate_draft, summarize_evaluations
from .model import ClaimRole, GroundingStatus
from .one_liner import sentence_count
from .pipeline import PipelineResult, run_pipeline
from .store import CompassStore

#: 秘密値を持ち得る環境変数名（**名前だけ**を扱う。値は読まない）
_SECRET_ENV_NAMES = ("JQUANTS_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def _next_weekday(session_date: str) -> str:
    """翌平日（祝日カレンダーは適用しない＝観測用の近似。Factが無い日は空のまま）。"""
    day = date.fromisoformat(session_date) + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def _claim_row(claim) -> Dict[str, object]:
    return {"claim_id": claim.claim_id, "role": claim.claim_role.value,
            "type": claim.claim_type.value, "status": claim.grounding_status.value,
            "facts": len(claim.supporting_fact_ids),
            "contexts": len(claim.supporting_context_ids),
            "issues": [f"{i.validator}:{i.code}" for i in claim.issues],
            "text": claim.text}


def _package_row(result: PipelineResult) -> Dict[str, object]:
    pkg = result.package
    return {
        "session_date": pkg.session_date, "reference_session": pkg.reference_session,
        "package_id": pkg.package_id, "cutoff_utc": pkg.cutoff.isoformat(),
        "contexts": len(pkg.contexts), "facts": len(pkg.facts),
        "core": len(pkg.core_context_ids), "supporting": len(pkg.supporting_context_ids),
        "optional": len(pkg.optional_context_ids),
        "dimension_status": {k: v.value for k, v in pkg.dimension_status.items()},
        "unreliable_dimensions": list(pkg.unreliable_dimensions),
        "excluded_look_ahead": len(pkg.excluded_look_ahead),
        "excluded_over_budget": len(pkg.excluded_over_budget),
        "excluded_unusable_fact": len(pkg.excluded_unusable_fact),
        "same_or_future_session_contexts": sum(
            1 for c in pkg.contexts if c.time.session_date >= pkg.session_date),
    }


def _gate_row(result: PipelineResult) -> Dict[str, object]:
    draft = result.draft
    roles = {r.value: len(draft.claims_for_role(r)) for r in ClaimRole}
    return {
        "session_date": draft.session_date, "draft_id": draft.draft_id,
        "verdict": draft.verdict.value, "generator": draft.generator,
        "generator_fallback": draft.generator_fallback,
        "abstain_reason": draft.abstain_reason,
        "claims": len(draft.claims), "grounded": len(draft.grounded_claims),
        "warnings": sum(1 for c in draft.claims
                        if c.grounding_status is GroundingStatus.GROUNDED_WITH_WARNINGS),
        "rejected": len(draft.rejected_claims),
        "grounded_by_role": roles,
        "issue_codes": result.gate.issue_codes(),
        "draft_issues": [f"{i.validator}:{i.code}" for i in draft.issues],
        "why_contexts_cited": sorted({
            cid for c in draft.claims_for_role(ClaimRole.WHY)
            for cid in c.supporting_context_ids}),
        "risk_present": bool(draft.claims_for_role(ClaimRole.RISK)),
        "one_liner_sentences": sentence_count(draft.one_liner),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 3-C Evidence-Grounded Compass Generator real-data pilot")
    parser.add_argument("--sessions", type=int, default=5,
                        help="Compassを生成するTokyo session数")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    root = data_root()
    bank = market_bank_root(root)
    if not (bank / "index" / "market.sqlite3").exists():
        print("::P3C_PILOT_SKIP::" + json.dumps(
            {"reason": "market_bank_not_local", "market_bank_root": str(bank)},
            ensure_ascii=False))
        return 0

    from ..market.store import MarketBankStore

    config = load_compass_config()
    market = MarketBankStore(bank)
    qa = fact_pilot._qa_decisions(market)
    points_by_series = {sid: fact_pilot.load_points(market.index, qa, sid)
                        for sid, _n, _u in fact_pilot.PILOT_SERIES}
    # Phase 3-A / 3-B と**同じ生成経路**（Fact / Context Layerを複製しない）
    facts = assess_conflicts(fact_pilot.build_all_market_facts(
        points_by_series, now=now, sessions=args.sessions + 1))
    events = _event_facts(root, now)
    fact_sessions = sorted({f.time.primary_date for f in facts})
    all_items: List = []
    for offset, session_date in enumerate(fact_sessions):
        previous = fact_sessions[offset - 1] if offset > 0 else None
        items = build_session_contexts(facts, session_date, previous_session=previous,
                                       event_facts=events, now=now)
        all_items.extend(rank_contexts(items, session_date=session_date))
    # Compassを書く朝 = 各Fact sessionの**翌**Tokyo session（前営業日の材料で書く）。
    # 最終Fact sessionの翌平日がJST今日以前なら、その朝も対象にする
    mornings = list(fact_sessions[1:])
    if fact_sessions:
        candidate = _next_weekday(fact_sessions[-1])
        if candidate <= (now + timedelta(hours=9)).date().isoformat():
            mornings.append(candidate)
    sessions = mornings[-args.sessions:]
    print("::P3C_INPUT::" + json.dumps({
        "sessions": sessions, "fact_sessions": fact_sessions,
        "next_morning_rule": "weekday_after_last_fact_session",
        "facts_total": len(facts), "contexts_total": len(all_items),
        "event_facts": len(events), "generator": config.generator,
        "config": config.as_dict(),
    }, ensure_ascii=False))

    # ---- §8–§31: session毎にpipelineを通す（決定論的generator）
    results: List[PipelineResult] = []
    snapshots = []
    for session_date in sessions:
        snapshot = morning_context_snapshot(all_items, session_date, generated_at=now)
        snapshots.append(snapshot)
        results.append(run_pipeline(snapshot, facts, generator=None, config=config,
                                    now=now))
    print("::P3C_PACKAGE::" + json.dumps({
        "per_session": [_package_row(r) for r in results],
        "look_ahead_total": sum(len(r.package.excluded_look_ahead) for r in results),
        "same_or_future_session_total": sum(
            _package_row(r)["same_or_future_session_contexts"] for r in results),
    }, ensure_ascii=False))
    print("::P3C_PLAN::" + json.dumps({
        "per_session": [{
            "session_date": r.plan.session_date, "plan_id": r.plan.plan_id,
            "can_generate": r.plan.can_generate, "abstain_reason": r.plan.abstain_reason,
            "lead_context_id": r.plan.lead_context_id,
            "supporting": len(r.plan.supporting_context_ids),
            "counter": len(r.plan.counter_context_ids),
            "risk": len(r.plan.risk_context_ids),
            "coverage_dimensions": list(r.plan.coverage_dimensions),
            "components": dict(r.plan.components)} for r in results],
    }, ensure_ascii=False))
    print("::P3C_OUTLOOK::" + json.dumps({
        "per_session": [dict(r.outlook.as_dict(), session_date=r.package.session_date)
                        for r in results],
    }, ensure_ascii=False))
    print("::P3C_GATE::" + json.dumps({
        "per_session": [_gate_row(r) for r in results],
        "verdicts": {v: sum(1 for r in results if r.draft.verdict.value == v)
                     for v in sorted({r.draft.verdict.value for r in results})},
        "rejected_total": sum(len(r.draft.rejected_claims) for r in results),
        "all_why_cite_context": all(
            all(c.supporting_context_ids for c in r.draft.claims_for_role(ClaimRole.WHY))
            for r in results),
        "all_risk_present": all(
            bool(r.draft.claims_for_role(ClaimRole.RISK)) for r in results
            if r.draft.verdict.value in ("VALID", "VALID_WITH_WARNINGS")),
    }, ensure_ascii=False))

    latest = results[-1] if results else None
    print("::P3C_CLAIMS::" + json.dumps({
        "session_date": latest.draft.session_date if latest else "",
        "draft_id": latest.draft.draft_id if latest else "",
        "claims": [_claim_row(c) for c in (latest.draft.claims if latest else [])],
    }, ensure_ascii=False))
    print("::P3C_ONE_LINER::" + json.dumps({
        "per_session": [{"session_date": r.draft.session_date,
                         "verdict": r.draft.verdict.value,
                         "sentences": sentence_count(r.draft.one_liner),
                         "one_liner": r.draft.one_liner} for r in results],
    }, ensure_ascii=False))

    # ---- §36: adversarial（最新sessionの実Evidence Package上で）
    adv_results: List[Dict[str, object]] = []
    adv_skipped: List[Dict[str, str]] = []
    if snapshots:
        cases, adv_skipped = build_adversarial_cases(snapshots[-1], facts, config=config)
        adv_results = run_adversarial_cases(cases, config=config, now=now)
    print("::P3C_ADVERSARIAL::" + json.dumps({
        "session_date": snapshots[-1].session_date if snapshots else "",
        "summary": adversarial_summary(adv_results, adv_skipped),
        "cases": [{k: v for k, v in r.items() if k != "text"} for r in adv_results],
    }, ensure_ascii=False))

    # ---- §31/§32: 永続化・再現性
    store = CompassStore(root)
    drafts = [r.draft for r in results]
    first = store.add(drafts)
    second = store.add(drafts)
    rebuilt = store.rebuild_index()
    rerun = [run_pipeline(s, facts, generator=None, config=config, now=now).draft.draft_id
             for s in snapshots]
    print("::P3C_STORE::" + json.dumps({
        "drafts": len(drafts), "added_first": first["added"],
        "added_second": second["added"], "idempotent": second["added"] == 0,
        "canonical_rows": store.count(), "rebuilt_from_canonical": rebuilt,
        "rebuild_match": rebuilt == store.count(),
        "reproducible_draft_ids": rerun == [d.draft_id for d in drafts],
        "latest_draft_found": bool(store.latest_draft(sessions[-1])) if sessions else False,
        "claims_indexed_latest": len(store.claims_for_draft(drafts[-1].draft_id))
        if drafts else 0,
        "claims_citing_first_fact": len(store.claims_citing_fact(
            drafts[-1].evidence_fact_ids[0])) if drafts and drafts[-1].evidence_fact_ids
        else 0,
        "compass_root": str(store.root),
    }, ensure_ascii=False))

    # ---- §35: 過去Compassとの評価（観測。ruleの最適化には使わない）
    evaluations = [evaluate_draft(s, r.package, r.draft,
                                  tolerance_pct=config.historical_level_tolerance_pct)
                   for s, r in zip(snapshots, results)]
    print("::P3C_HISTORICAL::" + json.dumps({
        "per_date": [e.as_dict() for e in evaluations],
        "summary": summarize_evaluations(evaluations),
    }, ensure_ascii=False))

    # ---- §26/§27: provider境界（LLMは接続しない）
    print("::P3C_PROVIDER::" + json.dumps({
        "generator_used": sorted({r.draft.generator for r in results}),
        "deterministic_only": all(r.draft.generator == DETERMINISTIC for r in results),
        "llm_provider_configured": False, "llm_calls": 0,
        "fallbacks": sorted({r.draft.generator_fallback for r in results
                             if r.draft.generator_fallback}),
        "network_used": False,
    }, ensure_ascii=False))
    # 値は読まない。存在の有無（bool）だけを出す
    import os

    print("::P3C_SECURITY::" + json.dumps({
        "secret_env_names_checked": list(_SECRET_ENV_NAMES),
        "secret_env_present": {n: n in os.environ for n in _SECRET_ENV_NAMES},
        "secret_values_printed": False, "credentials_in_drafts": False,
        "generator_prompt_used": False,
    }, ensure_ascii=False))

    market.close()
    store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
