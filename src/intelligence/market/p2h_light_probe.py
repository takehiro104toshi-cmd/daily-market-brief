"""P2-H J-Quants **Light plan** entitlement / schema discovery probe。

目的（STEP 2）: 現在の契約（Light）で**実際に**取得できるdatasetを実APIで棚卸しし、
V2の**実際の項目名**を確認する。V2は項目名を短縮しているため（Open→O 等）、
旧仕様や他datasetからの類推でmappingしない——**実応答のfield名だけを根拠**にする。

出力規律:
- API Key値・行の**中身**は一切出力しない。出すのは
  HTTPステータス / 原因分類 / top-level key名 / 件数 / **field名** /
  日付レンジ / pagination有無 のみ。
- 会社名・銘柄名などの値も出さない（field名の存在確認までに留める）。

各datasetは AVAILABLE / NOT_ENTITLED / UNKNOWN のいずれかへ**実証ベース**で分類する
（推測でLight利用可能扱いしない）。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

from .jquants_v2 import (
    API_VERSION,
    AUTH_HEADER,
    DATA_KEY,
    ENV_API_KEY,
    JQUANTS_V2_BASE,
    PAGINATION_KEY,
    JQuantsV2CredentialResolver,
    classify_v2_failure,
    scrub_response_text,
)
from .jquants_v2 import _default_http as http_get

AVAILABLE = "AVAILABLE"
NOT_ENTITLED = "NOT_ENTITLED"
UNKNOWN = "UNKNOWN"

#: 調査対象。(key, path, [param variants]) —— variantは先に成功したもので確定する。
#: 期待プランは公式クイックスタート(V2)のプラン別API一覧に基づく**事前情報**であり、
#: 判定はあくまで実応答で行う。
CANDIDATES: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    # key,                    expected_plan, path,                          param variants
    ("listed_master",         "Free",  "/equities/master",                  ("", "?date=2026-09-01")),
    ("daily_bars",            "Free",  "/equities/bars/daily",              ("?code=72030&from=2026-08-20&to=2026-09-01",
                                                                             "?code=7203&from=2026-08-20&to=2026-09-01",
                                                                             "?date=2026-09-01")),
    ("fins_summary",          "Free",  "/fins/summary",                     ("?code=72030", "?code=7203", "?date=2026-09-01")),
    ("fins_earnings_date",    "Free",  "/fins/earnings-date",               ("", "?from=2026-09-01&to=2026-12-31")),
    ("equities_earnings_cal", "Free",  "/equities/earnings-calendar",       ("", "?from=2026-09-01&to=2026-12-31")),
    ("markets_calendar",      "Free",  "/markets/calendar",                 ("?from=2026-08-01&to=2026-09-30", "")),
    ("investor_types",        "Light", "/equities/investor-types",          ("?from=2026-07-01&to=2026-09-01", "")),
    ("topix",                 "Light", "/indices/bars/daily/topix",         ("?from=2026-08-25&to=2026-09-01",)),
    # Standard以上と見込まれるもの（NOT_ENTITLEDの確認＝迂回実装しないための証拠）
    ("indices_bars_daily",    "Standard", "/indices/bars/daily",            ("?from=2026-08-25&to=2026-09-01",)),
    ("fins_dividend",         "Standard", "/fins/dividend",                 ("?code=72030",)),
    ("fins_details",          "Standard", "/fins/details",                  ("?code=72030",)),
    ("markets_short_ratio",   "Standard", "/markets/short-ratio",           ("?from=2026-08-25&to=2026-09-01",)),
    ("equities_bars_am",      "Premium",  "/equities/bars/daily/am",        ("?date=2026-09-01",)),
    ("markets_breakdown",     "Premium",  "/markets/breakdown",             ("?date=2026-09-01",)),
)

#: 日付らしきfield名（レンジ報告用。値の中身ではなく範囲のみ出す）
_DATE_FIELD_HINTS = ("Date", "date", "AnnouncementDate", "DisclosedDate",
                     "PublishedDate", "StartDate", "EndDate", "HolidayDivision")


def _summarize(status: int, body: bytes, secrets: Tuple[str, ...]) -> Dict[str, object]:
    """応答を**値を出さずに**要約する。"""
    out: Dict[str, object] = {"status": status, "bytes": len(body)}
    try:
        payload = json.loads(body)
    except Exception:  # noqa: BLE001 非JSON
        out["json"] = False
        out["message"] = scrub_response_text(
            body[:120].decode("utf-8", "replace"), secrets)
        return out
    out["json"] = True
    if not isinstance(payload, dict):
        out["top_keys"] = []
        return out
    out["top_keys"] = sorted(map(str, payload))
    if "message" in payload:
        out["message"] = scrub_response_text(str(payload["message"]), secrets)[:200]
    rows = payload.get(DATA_KEY)
    if isinstance(rows, list):
        out["rows"] = len(rows)
        if rows and isinstance(rows[0], dict):
            # **field名のみ**（値は出さない）
            out["row_fields"] = sorted(map(str, rows[0]))
            for hint in _DATE_FIELD_HINTS:
                if hint in rows[0]:
                    values = sorted(str(r.get(hint, "")) for r in rows if r.get(hint))
                    if values:
                        out["date_field"] = hint
                        out["first_date"] = values[0]
                        out["last_date"] = values[-1]
                    break
            # 全行のfield名の差異（schemaの揺れを検出）
            all_fields = {f for r in rows if isinstance(r, dict) for f in map(str, r)}
            extra = sorted(all_fields - set(out["row_fields"]))
            if extra:
                out["fields_only_in_later_rows"] = extra
    out["has_pagination"] = PAGINATION_KEY in payload
    return out


def _classify(summary: Dict[str, object]) -> str:
    status = summary.get("status")
    if status == 200:
        return AVAILABLE if isinstance(summary.get("rows"), int) else UNKNOWN
    message = str(summary.get("message", ""))
    cause = classify_v2_failure(int(status or 0), message)
    if cause == "plan_not_entitled":
        return NOT_ENTITLED
    return UNKNOWN


def main(argv: Optional[List[str]] = None) -> int:
    resolution = JQuantsV2CredentialResolver(os.environ).resolve()
    if not resolution.present:
        print("::P2H_LIGHT_SKIP::" + json.dumps(
            {"reason": "credential_missing", "accepted_env": [ENV_API_KEY]}))
        return 0
    secrets = resolution.secret_values()
    headers = {AUTH_HEADER: resolution.secrets["api_key"].reveal()}

    results = []
    for key, expected_plan, path, variants in CANDIDATES:
        chosen: Dict[str, object] = {}
        used_variant = ""
        for variant in variants:
            status, body = http_get(f"{JQUANTS_V2_BASE}{path}{variant}", "GET",
                                    headers, b"")
            summary = _summarize(status, body, secrets)
            used_variant = variant
            chosen = summary
            # 200が出たらそこで確定（総当たりを続けない）
            if status == 200 and isinstance(summary.get("rows"), int):
                break
            # プラン非対象と判明したら他variantを試さない（無駄打ちしない）
            if _classify(summary) == NOT_ENTITLED:
                break
        record = {
            "dataset": key,
            "expected_plan": expected_plan,
            "path": path,
            "params": used_variant,
            "entitlement": _classify(chosen),
            "api_version": API_VERSION,
            **chosen,
        }
        results.append(record)
        print("::P2H_LIGHT::" + json.dumps(record, ensure_ascii=False))

    summary_line = {
        "available": sorted(r["dataset"] for r in results if r["entitlement"] == AVAILABLE),
        "not_entitled": sorted(r["dataset"] for r in results if r["entitlement"] == NOT_ENTITLED),
        "unknown": sorted(r["dataset"] for r in results if r["entitlement"] == UNKNOWN),
        "requests": len(results),
    }
    print("::P2H_LIGHT_SUMMARY::" + json.dumps(summary_line, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
