"""P2-H J-Quants Light core の live pilot（STEP 6/15/16/17/18）。

小規模sampleで **V2 fetch → raw → normalize → canonical → SQLite → query** を
一本で実証し、あわせて
- TOPIX regression（P2-G.2の経路が壊れていない）
- 取引カレンダー区分の**実測検証**
- data volume / performance の概算
- dataset別 data quality
を測る。

**full-universe backfillはしない**（P2-Hのacceptance条件ではない。storage/API/
query設計を実データで確定するのが目的）。
"""
from __future__ import annotations

import argparse
import json
import os
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..core.paths import data_root
from .jquants_light_datasets import (
    ALL_DATASETS,
    INGESTED_DATASETS,
    capability_matrix,
    get_dataset,
)
from .jquants_light_store import JQuantsLightStore
from .jquants_records import PARSERS, RecordProvenance
from .jquants_v2_client import JQuantsV2Client
from .tokyo_calendar import (
    DEFAULT_TRADING_DIVISIONS,
    latest_completed_session,
    validate_divisions,
)

#: sample securitiesの選定方針（STEP 6: 全銘柄×5年をいきなり取らない）
#: 33業種の異なるsector × 規模区分（ScaleCat）が散るように決定論的に選ぶ。
SAMPLE_SIZE = 8


def light_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / "jquants_light"


def _provenance(dataset_path: str, result, raw_item_id: str, attempt_id: str) -> RecordProvenance:
    return RecordProvenance(
        endpoint=dataset_path, retrieved_at=result.retrieved_at,
        raw_item_id=raw_item_id or "", fetch_attempt_id=attempt_id or "")


def _store_raw(store: JQuantsLightStore, result, attempt_id: str) -> str:
    """生応答をblob＋RawItemとして保存し、raw_item_idを返す（秘密はURLに無い）。"""
    from ..sources.model import RawItem

    body = result.raw_body
    if not body:
        return ""
    content_hash, locator, _created = store.raw.store_body(body)
    raw_item_id = RawItem.make_id("jquants", result.url, content_hash)
    if store.raw.get_raw_item(raw_item_id) is None:
        store.raw.add_raw_item(RawItem(
            raw_item_id=raw_item_id, source_id="jquants", locator=result.url,
            retrieved_at=datetime.now(timezone.utc), media_type="application/json",
            content_hash=content_hash, size_bytes=len(body), storage_ref=locator,
            endpoint_id=f"jquants:{result.dataset}", fetch_attempt_id=attempt_id))
    return raw_item_id


def _select_sample(master_rows: Sequence[dict], size: int = SAMPLE_SIZE) -> List[str]:
    """業種・規模が散るように決定論的にsampleを選ぶ（乱数を使わない＝再現可能）。"""
    by_bucket: Dict[Tuple[str, str], List[str]] = {}
    for row in master_rows:
        code = str(row.get("Code", ""))
        if not code:
            continue
        bucket = (str(row.get("S33", "")), str(row.get("ScaleCat", "")))
        by_bucket.setdefault(bucket, []).append(code)
    chosen: List[str] = []
    for bucket in sorted(by_bucket):
        chosen.append(sorted(by_bucket[bucket])[0])
        if len(chosen) >= size:
            break
    return chosen


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P2-H J-Quants Light core live pilot")
    parser.add_argument("--days", type=int, default=365,
                        help="sample securitiesの株価取得日数（既定365＝1年）")
    parser.add_argument("--sample", type=int, default=SAMPLE_SIZE)
    args = parser.parse_args(argv)

    started = _time.monotonic()
    root = light_root()
    store = JQuantsLightStore(root)
    client = JQuantsV2Client()

    if not client.credential_present():
        print("::P2H_PILOT_SKIP::" + json.dumps(
            {"reason": "credential_missing"}, ensure_ascii=False))
        store.close()
        return 0

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=args.days)
    dataset_reports: List[Dict] = []
    attempt_seq = 0

    def ingest(key: str, params: Optional[Dict[str, str]] = None) -> Tuple[object, int]:
        """1 datasetを取得→parse→canonical→index。戻り値は(result, added)。"""
        nonlocal attempt_seq
        spec = get_dataset(key)
        attempt_seq += 1
        attempt_id = f"p2h_{attempt_seq:04d}"
        result = client.fetch(key, spec.path, params or dict(spec.default_params),
                             required_fields=spec.required_fields)
        added = 0
        if result.ok and spec.ingestion_owner == "jquants_light":
            raw_item_id = _store_raw(store, result, attempt_id)
            provenance = _provenance(spec.path, result, raw_item_id, attempt_id)
            parse = PARSERS[key]
            records = [r for r in (parse(row, provenance) for row in result.rows)
                       if r is not None]
            added = store.append(key, records)
        return result, added

    def report(key: str, result, added: int, extra: Optional[Dict] = None) -> Dict:
        spec = get_dataset(key)
        rec = {
            "dataset": key, "endpoint": spec.path,
            "entitlement_expected": spec.entitlement,
            "classification": spec.classification,
            "ingestion_owner": spec.ingestion_owner,
            "http": result.status_code, "ok": result.ok,
            "error_kind": result.error_kind,
            "error_detail": result.error_detail[:160],
            "rows": len(result.rows), "pages": result.pages,
            "added": added, "elapsed_ms": result.elapsed_ms,
            "row_fields": list(result.observed_row_fields),
            "raw_bytes": len(result.raw_body),
        }
        if extra:
            rec.update(extra)
        dataset_reports.append(rec)
        print("::P2H_DATASET::" + json.dumps(rec, ensure_ascii=False))
        return rec

    # ---- 1. security master（sample選定の母集団でもある）
    master_result, master_added = ingest("listed_master", {})
    master_codes = _select_sample(list(master_result.rows), args.sample) \
        if master_result.ok else []
    report("listed_master", master_result, master_added,
           {"sample_codes_selected": len(master_codes)})

    # ---- 2. trading calendar（東京セッション判定の基盤）
    cal_result, cal_added = ingest(
        "markets_calendar",
        {"from": (end - timedelta(days=400)).isoformat(), "to": end.isoformat()})
    report("markets_calendar", cal_result, cal_added)

    # ---- 3. earnings calendar
    ern_result, ern_added = ingest("equities_earnings_cal", {})
    report("equities_earnings_cal", ern_result, ern_added)

    # ---- 4. investor-type flow（週次。日次flowとして扱わない）
    flow_result, flow_added = ingest(
        "investor_types",
        {"from": (end - timedelta(days=120)).isoformat(), "to": end.isoformat()})
    flow_extra = {}
    if flow_result.ok and flow_result.rows:
        pub = sorted({str(r.get("PubDate", "")) for r in flow_result.rows if r.get("PubDate")})
        st = sorted({str(r.get("StDate", "")) for r in flow_result.rows if r.get("StDate")})
        en = sorted({str(r.get("EnDate", "")) for r in flow_result.rows if r.get("EnDate")})
        flow_extra = {"published_range": [pub[0], pub[-1]] if pub else [],
                      "target_period_range": [st[0] if st else "", en[-1] if en else ""],
                      "distinct_periods": len(en), "frequency": "weekly"}
    report("investor_types", flow_result, flow_added, flow_extra)

    # ---- 5. sample securities: 株価 + 財務
    price_rows = fin_rows = 0
    price_requests = 0
    per_security: List[Dict] = []
    for code in master_codes:
        px_result, px_added = ingest(
            "daily_bars",
            {"code": code, "from": start.isoformat(), "to": end.isoformat()})
        fin_result, fin_added = ingest("fins_summary", {"code": code})
        price_requests += 2
        price_rows += len(px_result.rows)
        fin_rows += len(fin_result.rows)
        dates = sorted(str(r.get("Date", "")) for r in px_result.rows if r.get("Date"))
        per_security.append({
            "code": code, "price_http": px_result.status_code,
            "price_rows": len(px_result.rows), "price_added": px_added,
            "first": dates[0] if dates else "", "last": dates[-1] if dates else "",
            "fin_http": fin_result.status_code, "fin_rows": len(fin_result.rows),
            "fin_added": fin_added,
        })
    print("::P2H_SAMPLE::" + json.dumps(
        {"securities": per_security, "requested_days": args.days}, ensure_ascii=False))

    # ---- 6. TOPIX regression（V2経路が壊れていない／light storeへは保存しない）
    topix_spec = get_dataset("topix")
    topix_result = client.fetch(
        "topix", topix_spec.path,
        {"from": (end - timedelta(days=30)).isoformat(), "to": end.isoformat()},
        required_fields=topix_spec.required_fields)
    topix_dates = sorted(str(r.get("Date", "")) for r in topix_result.rows if r.get("Date"))
    print("::P2H_TOPIX_REGRESSION::" + json.dumps({
        "http": topix_result.status_code, "ok": topix_result.ok,
        "api_version": client.api_version, "rows": len(topix_result.rows),
        "row_fields": list(topix_result.observed_row_fields),
        "first": topix_dates[0] if topix_dates else "",
        "last": topix_dates[-1] if topix_dates else "",
        "identity_fields_match_p2g2": list(topix_result.observed_row_fields) ==
                                      ["C", "Date", "H", "L", "O"],
        "written_to_light_store": False,
        "note": "TOPIXはMarket Data Bankが所有。P2-Hは二重保管しない",
    }, ensure_ascii=False))

    # ---- 7. 取引カレンダー区分の実測検証（推測でHolDivの意味を決めない）
    calendar_rows = [dict(r) for r in store.calendar_range(
        (end - timedelta(days=400)).isoformat(), end.isoformat())]
    validation = validate_divisions(calendar_rows, topix_dates)
    jst_now = datetime.now(timezone.utc) + timedelta(hours=9)
    session = latest_completed_session(calendar_rows, now=jst_now)
    print("::P2H_CALENDAR::" + json.dumps({
        "calendar_rows_indexed": len(calendar_rows),
        "validation": validation.as_dict(),
        "latest_completed_session": session,
        "topix_latest": topix_dates[-1] if topix_dates else "",
        "agrees_with_topix_latest": bool(session and topix_dates and session == topix_dates[-1]),
        "jst_now": jst_now.isoformat(),
    }, ensure_ascii=False))

    # ---- 8. persistence: SQLite再構築（canonicalのみから作り直せる）
    counts_before = {d.key: store.count(d.key) for d in INGESTED_DATASETS}
    rebuilt = store.rebuild_index()
    counts_after = {d.key: store.count(d.key) for d in INGESTED_DATASETS}
    print("::P2H_PERSISTENCE::" + json.dumps({
        "counts_before_rebuild": counts_before,
        "rebuilt_from_canonical": rebuilt,
        "counts_after_rebuild": counts_after,
        "match": counts_before == counts_after,
    }, ensure_ascii=False))

    # ---- 9. query foundation（STEP 14）
    sample_code = master_codes[0] if master_codes else ""
    sec = store.security_by_code(sample_code) if sample_code else None
    latest_px = store.latest_price(sample_code) if sample_code else None
    forecast = store.latest_company_forecast(sample_code) if sample_code else None
    history = store.price_history(sample_code) if sample_code else []
    earnings = store.earnings_within(end.isoformat(),
                                     (end + timedelta(days=120)).isoformat())
    flows = store.investor_flows_for_period(
        (end - timedelta(days=120)).isoformat(), end.isoformat())
    print("::P2H_QUERY::" + json.dumps({
        "security_by_code": bool(sec),
        "security_has_sector33": bool(sec and sec["sector33_name"]),
        "securities_by_company_name": len(
            store.securities_by_company_name(sec["company_name"][:2]) if sec else []),
        "price_history_rows": len(history),
        "latest_price_date": latest_px["trading_date"] if latest_px else "",
        "latest_price_has_raw_and_adjusted": bool(
            latest_px and latest_px["close"] and latest_px["adjusted_close"]),
        "financial_records": len(store.financials_for_security(sample_code)) if sample_code else 0,
        "latest_company_forecast": bool(forecast),
        "earnings_within_120d": len(earnings),
        "calendar_range_rows": len(calendar_rows),
        "investor_flow_periods": len(flows),
    }, ensure_ascii=False))

    # ---- 10. data quality（STEP 18）
    quality = []
    for spec in INGESTED_DATASETS:
        rows = list(store.iter_canonical(spec.key))
        ids = [r.get("record_id", "") for r in rows]
        missing_provenance = sum(
            1 for r in rows if not (r.get("provenance") or {}).get("raw_item_id"))
        quality.append({
            "dataset": spec.key, "canonical_rows": len(rows),
            "distinct_record_ids": len(set(ids)),
            "duplicate_record_ids": len(ids) - len(set(ids)),
            "rows_missing_raw_provenance": missing_provenance,
            "entitlement": spec.entitlement,
        })
    print("::P2H_QUALITY::" + json.dumps(quality, ensure_ascii=False))

    # ---- 11. volume / performance（STEP 17。full backfillはしない）
    universe = len(master_result.rows) if master_result.ok else 0
    securities_sampled = max(1, len(master_codes))
    price_rows_per_security = price_rows / securities_sampled
    sessions_per_year = price_rows_per_security / max(1, args.days / 365.0)
    canonical_bytes = sum(
        p.stat().st_size for p in (store.canonical_dir).glob("*.jsonl") if p.exists())
    bytes_per_price_row = (
        (store.canonical_dir / "daily_prices.jsonl").stat().st_size / price_rows
        if price_rows and (store.canonical_dir / "daily_prices.jsonl").exists() else 0)
    est_full_rows = universe * sessions_per_year * 5
    print("::P2H_SCALE::" + json.dumps({
        "universe_securities": universe,
        "securities_sampled": len(master_codes),
        "requested_days": args.days,
        "price_rows_total": price_rows,
        "price_rows_per_security": round(price_rows_per_security, 1),
        "sessions_per_year_observed": round(sessions_per_year, 1),
        "api_requests_this_run": client.request_count,
        "api_requests_per_security": round(price_requests / securities_sampled, 1),
        "canonical_bytes_now": canonical_bytes,
        "bytes_per_price_row": round(bytes_per_price_row, 1),
        "estimated_full_universe_5y_rows": int(est_full_rows),
        "estimated_full_universe_5y_bytes": int(est_full_rows * bytes_per_price_row),
        "estimated_full_universe_requests_by_code": universe,
        "runtime_seconds": round(_time.monotonic() - started, 1),
        "note": "full-universe backfillはP2-Hの対象外（設計確定が目的）",
    }, ensure_ascii=False))

    # ---- 12. capability matrix（STEP 19）
    print("::P2H_CAPABILITY::" + json.dumps(capability_matrix(), ensure_ascii=False))

    ok_required = all(
        r["ok"] for r in dataset_reports
        if ALL_DATASETS[r["dataset"]].classification == "REQUIRED")
    print("::P2H_SUMMARY::" + json.dumps({
        "datasets_attempted": len(dataset_reports),
        "datasets_ok": sum(1 for r in dataset_reports if r["ok"]),
        "required_all_ok": ok_required,
        "topix_regression_ok": topix_result.ok,
        "calendar_validated": validation.validated,
        "persistence_match": counts_before == counts_after,
        "total_api_requests": client.request_count,
    }, ensure_ascii=False))
    store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
