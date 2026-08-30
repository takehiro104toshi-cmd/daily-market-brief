"""P2-D Market Data Bank live pilot（GitHub Actions用）。

実ネットワークでCORE系列（約1年の日足）を取得し、以下を1本で実証する:
fetch→raw保存→正規化（Decimal/セッションモデル）→Evidence QA→canonical→
SQLite index→派生→クエリ→**別プロセスでの永続化検証**→backup manifest。

出力markers（logから機械抽出する）:
  ::P2D_SERIES::{...}       系列別の取得・取込結果
  ::P2D_RUN::{...}          run manifestサマリ
  ::P2D_QUALITY::{...}      品質レポート（PART J）
  ::P2D_QUERY::{...}        クエリsmoke＋latest semantics実測
  ::P2D_TRACE_BEGIN/END::   1系列のend-to-end trace（人間可読）
  ::P2D_DAILY_QA::{...}     DAILY_MARKET policyでの最新値再評価（文脈分離の実証）
  ::P2D_PERSISTENCE::{...}  別プロセス再オープン検証（PART A gate）
  ::P2D_BACKUP::{...}       backup manifest生成・照合

Secret不使用（StooqはpublicのCSVエンドポイント）。bulk禁止: 1系列=1リクエスト。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..core import serialization
from ..core.backup import verify_against_manifest, write_backup_manifest
from ..core.paths import data_root, market_bank_root
from ..evidence_qa.assess import assess_observation
from ..evidence_qa.policy import DAILY_MARKET_V1, HISTORICAL_V1
from ..ingestion.transport import UrllibTransport
from .backfill import MarketBackfillEngine, default_range, provider_source_info
from .model import Observation
from .providers import StooqDailyHistoryProvider, YfinanceDailyHistoryProvider
from .quality_report import build_quality_report
from .series_catalog import load_catalog
from .store import MarketBankStore

TRACE_SERIES = "index:nikkei225.close.closing.tokyo"


def _row_dict(row) -> dict:
    return None if row is None else {k: row[k] for k in row.keys()}


def render_trace(store: MarketBankStore, series_id: str) -> str:
    """1系列のend-to-end trace（fetch→raw→observation→QA→index→latest）。"""
    lines = [f"series: {series_id}"]
    attempts = [a for a in store.raw.iter_attempts()]
    for a in attempts:
        lines.append(
            f"  fetch_attempt {a.attempt_id} status={a.status_code} "
            f"url={a.url} body={a.body_size}B hash={a.content_hash[:16]}…")
    latest = store.index.latest_trading_session(series_id)
    if latest is None:
        lines.append("  (no data)")
        return "\n".join(lines)
    obs = store.normalized.get_observation(latest["observation_id"])
    raw_items = {i.raw_item_id: i for i in store.raw.iter_raw_items()}
    lines.append(
        f"  latest observation {obs.observation_id}: trading_date={obs.trading_date} "
        f"value={obs.value} unit={obs.unit} as_of={obs.as_of.isoformat()} "
        f"source={obs.source_id} kind={obs.kind.value}")
    assessment = None
    for a in store.qa.iter_assessments():
        if a.record_id == obs.observation_id:
            assessment = a
    if assessment is not None:
        lines.append(
            f"  qa {assessment.assessment_id}: decision={assessment.decision.value} "
            f"policy={assessment.policy_name}:{assessment.policy_version} "
            f"issues={[i.code for i in assessment.issues]}")
    for item in raw_items.values():
        if item.source_id == obs.source_id:
            lines.append(
                f"  raw csv {item.raw_item_id}: {item.size_bytes}B "
                f"sha256={item.content_hash[:16]}… storage={item.storage_ref}")
            break
    lines.append(f"  index row: {json.dumps(_row_dict(latest), ensure_ascii=False)}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="P2-D market data bank live pilot")
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--catalog", default="knowledge/market_series/core_series.yaml")
    args = parser.parse_args(argv)

    serialization.register_domain_types()
    root = data_root()
    bank_root = market_bank_root(root)
    catalog = load_catalog(Path(args.catalog))
    store = MarketBankStore(bank_root)
    from .jquants_topix import JQuantsTopixProvider
    from .mof_jgb import MofJgbYieldProvider
    from .treasury_curve import TreasuryParYieldProvider

    providers = {
        "yfinance": YfinanceDailyHistoryProvider(),  # legacy一次経路（本番実績）
        "stooq": StooqDailyHistoryProvider(UrllibTransport()),
        # P2-G: PRIMARY_OFFICIAL経路（critical source gap closure）
        "treasury_gov": TreasuryParYieldProvider(UrllibTransport()),
        "mof_japan": MofJgbYieldProvider(UrllibTransport()),
        "jquants": JQuantsTopixProvider(),  # credentialは環境変数runtime injectionのみ
    }
    engine = MarketBackfillEngine(store, catalog, providers, HISTORICAL_V1,
                                  sleeper=time.sleep)
    start, end = default_range(days=args.days)
    print(f"P2-D pilot: {len(catalog.enabled_series())} series, range {start}..{end}, "
          f"data_root={root}, at {datetime.now(timezone.utc).isoformat()}")

    run = engine.run(start=start, end=end)
    for r in run.results:
        print("::P2D_SERIES::" + json.dumps({
            "series_id": r.series_id, "symbol": r.symbol, "status": r.status,
            "provider": r.provider_id, "fallback": r.fallback_used,
            "fallback_errors": list(r.fallback_errors),
            "http": r.http_status, "error": r.error_kind,
            "error_detail": r.error_detail, "records": r.records_seen,
            "added": r.observations_added, "revisions": r.revisions,
            "issues": r.issue_count, "issue_sample": list(r.issue_sample),
            "qa": list(r.qa_decisions), "probe": r.probe,
        }, ensure_ascii=False))
    print("::P2D_RUN::" + json.dumps({
        "run_id": run.run_id, "provider": run.provider_id,
        "catalog": run.catalog_version, "ingest": run.ingest_version,
        "policy": run.trust_policy, "range": [run.range_start, run.range_end],
        "requested": run.series_requested, "success": run.series_success,
        "gap": run.series_gap, "failed": run.series_failed,
        "observations_added": run.observations_added, "derived_added": run.derived_added,
    }, ensure_ascii=False))

    print("::P2D_QUALITY::" + json.dumps(build_quality_report(store, catalog),
                                         ensure_ascii=False))

    # クエリsmoke＋latest semanticsの実測
    succeeded = [r.series_id for r in run.results if r.status == "success"]
    query_result = {"latest_semantics": {}, "range_query": {}, "decision_query": {}}
    for series_id in succeeded[:3]:
        query_result["latest_semantics"][series_id] = {
            "latest_trading_session": _row_dict(store.index.latest_trading_session(series_id)),
            "latest_as_of": _row_dict(store.index.latest_as_of(series_id)),
        }
    if succeeded:
        sid = succeeded[0]
        rows = store.index.query(series_id=sid, date_from=run.range_start,
                                 date_to=run.range_end, kind="raw")
        query_result["range_query"] = {"series": sid, "rows": len(rows)}
        accepted = store.index.query(series_id=sid, decision="accept_with_warnings")
        query_result["decision_query"] = {
            "series": sid, "accept_with_warnings": len(accepted)}
        derived = store.index.query(series_id=None, kind="derived", limit=100000)
        query_result["derived_rows"] = len(derived)
    print("::P2D_QUERY::" + json.dumps(query_result, ensure_ascii=False))

    trace_id = TRACE_SERIES if TRACE_SERIES in succeeded else (succeeded[0] if succeeded else "")
    if trace_id:
        print("::P2D_TRACE_BEGIN::")
        print(render_trace(store, trace_id))
        print("::P2D_TRACE_END::")

        # DAILY_MARKET policyでの最新値評価（HISTORICALとの文脈分離の実証・追記保存）
        latest_row = store.index.latest_trading_session(trace_id)
        obs: Observation = store.normalized.get_observation(latest_row["observation_id"])
        daily = assess_observation(
            obs, source_info=provider_source_info(catalog, obs.source_id),
            policy=DAILY_MARKET_V1, reference_time=datetime.now(timezone.utc))
        store.add_assessment(daily)
        print("::P2D_DAILY_QA::" + json.dumps({
            "observation_id": obs.observation_id, "trading_date": obs.trading_date,
            "historical_decision": "accept_with_warnings",
            "daily_market_decision": daily.decision.value,
            "daily_market_issues": [i.code for i in daily.issues],
        }, ensure_ascii=False))

    # P2-F: market observation QA意味論v2での再評価（旧HISTORICAL評価は削除せず保持——
    # NO RETROACTIVE DELETE。新旧比較を機械出力する）
    from ..evidence_qa.assess import ProviderTrace
    from ..evidence_qa.policy import MARKET_OBSERVATION_V1

    trace_by_series = {
        r.series_id: ProviderTrace(provider_id=r.provider_id,
                                   fetch_attempt_id=r.fetch_attempt_id,
                                   raw_payload_ref=r.raw_item_id)
        for r in run.results if r.status == "success"}
    old_latest = {}
    for a in store.qa.iter_assessments():
        if a.policy_name == "HISTORICAL":
            old_latest[a.record_id] = a  # append順=時系列（1パス導出）
    old_counts: dict = {}
    new_counts: dict = {}
    old_missing_ref = new_missing_ref = reassessed = 0
    reassess_ref = datetime.now(timezone.utc)
    for obs in store.normalized.iter_observations():
        if obs.kind.value != "raw":
            continue
        old = old_latest.get(obs.observation_id)
        if old is not None:
            old_counts[old.decision.value] = old_counts.get(old.decision.value, 0) + 1
            if any(i.code == "missing_supporting_evidence_ref" for i in old.issues):
                old_missing_ref += 1
        new = assess_observation(
            obs, source_info=provider_source_info(catalog, obs.source_id),
            policy=MARKET_OBSERVATION_V1, reference_time=reassess_ref,
            provider_trace=trace_by_series.get(obs.series_id))
        store.add_assessment(new)
        new_counts[new.decision.value] = new_counts.get(new.decision.value, 0) + 1
        if any(i.code == "missing_supporting_evidence_ref" for i in new.issues):
            new_missing_ref += 1
        reassessed += 1
    print("::P2F_REASSESS::" + json.dumps({
        "reassessed_raw_observations": reassessed,
        "old_policy": "HISTORICAL:1.0.0", "new_policy": "MARKET_OBSERVATION:1.0.0",
        "old_decisions": old_counts, "new_decisions": new_counts,
        "old_missing_supporting_evidence_ref": old_missing_ref,
        "new_missing_supporting_evidence_ref": new_missing_ref,
        "old_assessments_preserved": True,
    }, ensure_ascii=False))

    # P2-G: CRITICAL MARKET SOURCE GAP CLOSURE検証（official経路の実測サマリ）
    p2g_targets = {
        "index:topix.close.closing.tokyo": "G10",
        "rates:JGB10Y.yield.closing.tokyo": "G11",
        "rates:UST2Y_par.yield.closing.us": "G11",
        "rates:UST10Y_par.yield.closing.us": "G11_optional_parallel",
    }
    by_series = {r.series_id: r for r in run.results}
    gap_rows = []
    for sid, gap_id in p2g_targets.items():
        r = by_series.get(sid)
        rows = store.index.query(series_id=sid, kind="raw", limit=100000)
        gap_rows.append({
            "series_id": sid, "gap": gap_id,
            "status": r.status if r else "not_in_catalog_run",
            "provider": r.provider_id if r else "",
            "error": r.error_kind if r else "",
            "error_detail": (r.error_detail[:120] if r else ""),
            "records_added": r.observations_added if r else 0,
            "raw_rows": len(rows),
            "first": rows[0]["trading_date"] if rows else "",
            "last": rows[-1]["trading_date"] if rows else "",
            "qa": list(r.qa_decisions) if r else [],
            "issue_sample": list(r.issue_sample) if r else [],
            "latest": _row_dict(store.index.latest_trading_session(sid)),
            "dma25_capable": len(rows) >= 25,
        })
    spread_rows = store.index.query(
        series_id="rates:UST10Y_par_UST2Y_par.spread.derived_metric",
        kind="derived", limit=100000)
    nt_rows = store.index.query(
        series_id="index:nikkei225_topix.nt_ratio.derived_metric",
        kind="derived", limit=100000)
    print("::P2G_GAPS::" + json.dumps({
        "series": gap_rows,
        "spread_official_rows": len(spread_rows),
        "spread_latest": _row_dict(store.index.latest_trading_session(
            "rates:UST10Y_par_UST2Y_par.spread.derived_metric", kind="derived")),
        "nt_ratio_rows": len(nt_rows),
        "nt_ratio_latest": _row_dict(store.index.latest_trading_session(
            "index:nikkei225_topix.nt_ratio.derived_metric", kind="derived")),
    }, ensure_ascii=False))

    # P2-G.1: TOPIX CREDENTIALED LIVE CLOSEOUT（STEP 1-8。秘密は一切出力しない）
    from .jquants_topix import credential_status
    from .topix_freshness import (
        TOPIX_SERIES_ID,
        access_requirement_report,
        evaluate_topix_freshness,
        g10_state,
    )

    cred = credential_status()
    topix_result = next(
        (r for r in run.results if r.series_id == TOPIX_SERIES_ID), None)
    topix_rows = store.index.query(series_id=TOPIX_SERIES_ID, kind="raw", limit=100000)
    freshness = evaluate_topix_freshness(store.index, now=datetime.now(timezone.utc))
    state, reason_codes = g10_state(
        freshness, credential_present=bool(cred["present"]),
        fetch_error_kind=(topix_result.error_kind if topix_result else ""))
    # 実際にAPIで通った方式のみ（成功していない方式をsupportedと断定しない）
    cred["auth_method_validated"] = getattr(
        providers.get("jquants"), "last_auth_method_validated", "")

    topix_qa: dict = {}
    topix_ids = {row["observation_id"] for row in topix_rows}
    for a in store.qa.iter_assessments():
        if a.record_id in topix_ids:
            key = f"{a.policy_name}:{a.decision.value}"
            topix_qa[key] = topix_qa.get(key, 0) + 1

    nt_rows = store.index.query(
        series_id="index:nikkei225_topix.nt_ratio.derived_metric",
        kind="derived", limit=100000)
    nt_provenance = None
    if nt_rows:
        sample = store.normalized.get_observation(nt_rows[-1]["observation_id"])
        nt_provenance = {
            "observation_id": sample.observation_id,
            "trading_date": sample.trading_date,
            "value": str(sample.value),
            "unit": sample.unit,
            "input_count": len(sample.inputs),
            "inputs": list(sample.inputs),
            "calculation_method": sample.calculation_method,
        }

    print("::P2G1_TOPIX::" + json.dumps({
        "step1_credential": cred,
        "step2_api_probe": {
            "attempted": topix_result is not None,
            "status": topix_result.status if topix_result else "not_run",
            "provider": topix_result.provider_id if topix_result else "",
            "http": topix_result.http_status if topix_result else 0,
            "error_kind": topix_result.error_kind if topix_result else "",
            "error_detail": (topix_result.error_detail[:160] if topix_result else ""),
            "records_seen": topix_result.records_seen if topix_result else 0,
            "auth_method_validated": cred["auth_method_validated"],
        },
        "step3_historical": {
            "raw_rows": len(topix_rows),
            "first": topix_rows[0]["trading_date"] if topix_rows else "",
            "last": topix_rows[-1]["trading_date"] if topix_rows else "",
            "meets_25dma": len(topix_rows) >= 25,
            "unit": topix_rows[-1]["unit"] if topix_rows else "",
        },
        "step4_freshness": freshness.as_dict(),
        "step5_access_requirement": access_requirement_report(freshness),
        "step6_ingestion_qa": {
            "qa_decisions": topix_qa,
            "latest": _row_dict(store.index.latest_trading_session(TOPIX_SERIES_ID)),
        },
        "step7_nt_ratio": {
            "rows": len(nt_rows), "latest_provenance": nt_provenance,
            # TOPIXが遅延している期間のNT倍率は「current」として使わない
            "current_usable": freshness.morning_usable,
            "usability_note": ("同一trading_dateの現物指数close同士のみ生成。"
                               "TOPIXがDELAYED_NOT_CURRENTの間は当日入力として"
                               "使用しない（履歴分析用途のみ）"),
        },
        "step8_gap_state": {"gap": "G10", "state": state,
                            "reason_codes": list(reason_codes)},
    }, ensure_ascii=False))

    # P2-G.1 MINI TASK A: Treasury年ファイルの重複取得排除の実証
    treasury_attempts = [a for a in store.raw.iter_attempts()
                         if a.source_id == "treasury_gov"]
    treasury_series = [r for r in run.results if r.provider_id == "treasury_gov"
                       or r.series_id.startswith("rates:UST") and "_par" in r.series_id]
    print("::P2G1_TREASURY_DEDUP::" + json.dumps({
        "series": [{"series_id": r.series_id, "status": r.status,
                    "records": r.records_seen, "added": r.observations_added,
                    "raw_item_id": r.raw_item_id,
                    "fetch_attempt_id": r.fetch_attempt_id,
                    "issue_sample": list(r.issue_sample)}
                   for r in treasury_series],
        "treasury_fetch_attempts_recorded": len(treasury_attempts),
        "distinct_treasury_urls": len({a.url for a in treasury_attempts}),
        "shared_raw_item": (len({r.raw_item_id for r in treasury_series
                                 if r.raw_item_id}) == 1
                            and len(treasury_series) > 1),
        "shared_fetch_attempt": (len({r.fetch_attempt_id for r in treasury_series
                                      if r.fetch_attempt_id}) == 1
                                 and len(treasury_series) > 1),
    }, ensure_ascii=False))

    # PART A gate: 別プロセス（restart相当）でcanonical読み戻し＋index全再構築＋latest一致
    parent_latest = {
        sid: _row_dict(store.index.latest_trading_session(sid)) for sid in succeeded}
    store.close()
    cmd = [sys.executable, "-m", "src.intelligence.market.persistence_check",
           "--data-root", str(root)]
    for sid in succeeded:
        cmd += ["--series", sid]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        print("::P2D_PERSISTENCE::" + json.dumps(
            {"ok": False, "error": proc.stderr[-400:]}))
        return 1
    child = json.loads(proc.stdout.strip().splitlines()[-1])
    mismatches = []
    for sid in succeeded:
        parent = parent_latest[sid]
        got = child["latest"].get(sid)
        if got is None or parent is None or (
                got["observation_id"] != parent["observation_id"]
                or got["value"] != parent["value"]
                or got["trading_date"] != parent["trading_date"]):
            mismatches.append(sid)
    print("::P2D_PERSISTENCE::" + json.dumps({
        "ok": not mismatches and child["canonical_observations"] > 0,
        "fresh_process": True,
        "canonical_observations": child["canonical_observations"],
        "canonical_assessments": child["canonical_assessments"],
        "index_rebuilt_observations": child["index_rebuilt_observations"],
        "recovered_lines": child["recovered_lines"],
        "latest_match": {"checked": len(succeeded), "mismatch": mismatches},
    }, ensure_ascii=False))

    # backup基盤: manifest生成→自己照合（missing/changedゼロ）
    manifest_path = write_backup_manifest(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing, changed, extra = verify_against_manifest(root, manifest)
    print("::P2D_BACKUP::" + json.dumps({
        "manifest": manifest_path.name, "files": manifest["file_count"],
        "total_bytes": manifest["total_bytes"], "schema": manifest["schema_version"],
        "verify_missing": len(missing), "verify_changed": len(changed),
        "verify_extra": len(extra),
    }, ensure_ascii=False))

    print("done")
    return 0 if (not mismatches and run.series_success > 0) else 1


if __name__ == "__main__":
    sys.exit(main())
