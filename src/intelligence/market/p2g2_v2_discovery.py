"""P2-G.2 V2仕様ディスカバリ・プローブ（**HISTORICAL PROBE — production pathではない**）。

run #13 で使用し、V2 base URL・TOPIXパス・API Key搬送方式を実測特定した。
仕様確定後は `jquants_v2.py` が正であり、本モジュールは再実行不要。

隔離規律（tests/intelligence/test_legacy_isolation.py で固定）:
- production配線モジュール（pilot_runner / backfill / store 等）から参照しない
- workflowの実行ステップに入れない
- 当時の実測evidenceはdocs/へappend-onlyで保全してあるため、本ファイルは
  **再現・参照用**として残す（削除しない）

--- 以下、当時の実装ノート ---
J-Quants **V2** 公式仕様の実測ディスカバリ（P2-G.2 STEP 1）。

背景（監督者訂正）: J-Quants APIはV1→V2へ移行し、**V1は2026-06-01に終了**。
run #7〜#12で観測した403は credential不正と断定せず、
**LEGACY_V1_ENDPOINT_USED / API_VERSION_MISMATCH** を主要原因候補とする。

本モジュールは「V1仕様を推測でV2へ変換」しないための証拠収集:
  Phase A: 認証なしでパス候補を叩き、**応答messageの形**でルート実在を判別する
           （AWS API Gatewayは未知ルートに "Missing Authentication Token"、
             実在ルートの認証拒否に "Forbidden"/"Unauthorized" を返す）
  Phase B: 実在らしきパスへAPI Keyを**複数の搬送方式**で送り、通る方式を特定する

秘密の規律: API Key値・token値は stdout / URL / 例外 / レポートへ**一切出さない**。
出力は候補名・HTTPステータス・JSONキー名・件数・日付・messageのみ（全てscrub通過）。

出力marker: ::P2G2_PATH:: / ::P2G2_AUTH:: / ::P2G2_DONE::
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = "https://api.jquants.com"
TIMEOUT = 30.0
UA = ("daily-market-brief-vnext/0.2 "
      "(+https://github.com/takehiro104toshi-cmd/daily-market-brief)")

#: 直近の東京セッションを含む短い期間（1リクエストあたりの負荷を最小化）
FROM_DATE = "2026-08-24"
TO_DATE = "2026-08-28"

#: パス候補（V2の正しいTOPIXリソースを応答形状から特定する）
PATH_CANDIDATES = (
    ("v2_root", "/v2"),
    ("v2_openapi", "/v2/openapi.json"),
    ("root_openapi", "/openapi.json"),
    ("v2_indices_topix", f"/v2/indices/topix?from={FROM_DATE}&to={TO_DATE}"),
    ("v2_indices", f"/v2/indices?from={FROM_DATE}&to={TO_DATE}"),
    ("v2_markets_topix", f"/v2/markets/topix?from={FROM_DATE}&to={TO_DATE}"),
    ("v2_index_topix_singular", f"/v2/index/topix?from={FROM_DATE}&to={TO_DATE}"),
    ("v2_indices_prices", f"/v2/indices/prices?from={FROM_DATE}&to={TO_DATE}"),
    ("v1_indices_topix_baseline", f"/v1/indices/topix?from={FROM_DATE}&to={TO_DATE}"),
)

#: API Keyの搬送方式候補（V2で通るものを実測で特定する）
AUTH_TRANSPORTS = (
    ("authorization_bearer", "header", "Authorization", "Bearer {key}"),
    ("authorization_raw", "header", "Authorization", "{key}"),
    ("x_api_key", "header", "x-api-key", "{key}"),
    ("apikey_header", "header", "apikey", "{key}"),
)


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret and secret in text else text


def _request(url: str, *, headers: dict = None, method: str = "GET") -> tuple:
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", UA)
    request.add_header("Accept", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(4 * 1024 * 1024), ""
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read(8192) if exc.fp else b""), ""
    except Exception as exc:  # noqa: BLE001
        return 0, b"", type(exc).__name__


def _summarize(status: int, body: bytes, secret: str) -> dict:
    """安全な要約（token値は出さない。キー名・件数・日付・messageのみ）。"""
    out = {"status": status, "bytes": len(body)}
    try:
        payload = json.loads(body or b"{}")
    except Exception:  # noqa: BLE001
        out["json"] = False
        head = body[:80].decode("utf-8", "replace")
        out["head"] = _scrub("".join(c for c in head if c.isprintable()), secret)
        return out
    out["json"] = True
    if isinstance(payload, dict):
        out["top_keys"] = sorted(payload)[:10]
        message = payload.get("message")
        if isinstance(message, str):
            out["message"] = _scrub(message[:140], secret)
        # データ配列らしきキーを探す（V2のキー名は未知——推測せず観測する）
        for key, value in payload.items():
            if isinstance(value, list) and value:
                out["array_key"] = key
                out["rows"] = len(value)
                if isinstance(value[0], dict):
                    out["row_fields"] = sorted(value[0])[:15]
                    dates = [str(r.get(f, "")) for r in value
                             for f in ("Date", "date", "TradingDate")
                             if isinstance(r, dict) and r.get(f)]
                    if dates:
                        out["first_date"] = min(dates)
                        out["last_date"] = max(dates)
                break
        out["has_pagination_key"] = bool(
            payload.get("pagination_key") or payload.get("paginationKey"))
    elif isinstance(payload, list):
        out["top_keys"] = ["<array>"]
        out["rows"] = len(payload)
    return out


def main() -> int:
    secret = os.environ.get("JQUANTS_API_KEY", "").strip()

    # ---- Phase A: 認証なしでパス実在を判別（messageの形が識別子になる）
    alive = []
    for name, path in PATH_CANDIDATES:
        status, body, err = _request(HOST + path)
        row = {"phase": "path_discovery", "candidate": name, "path": path,
               "error": err}
        row.update(_summarize(status, body, secret))
        message = str(row.get("message", ""))
        # AWS API Gateway: 未知ルート→"Missing Authentication Token"
        row["route_exists_hint"] = (
            "unknown_route" if "Missing Authentication Token" in message
            else ("exists_auth_required" if status in (401, 403) else
                  ("ok" if status == 200 else "unclear")))
        print("::P2G2_PATH::" + _scrub(json.dumps(row, ensure_ascii=False), secret))
        if row["route_exists_hint"] in ("exists_auth_required", "ok"):
            alive.append((name, path))

    if not secret:
        print("::P2G2_AUTH::" + json.dumps(
            {"credential_present": False,
             "detail": "JQUANTS_API_KEY未設定——認証試行なし"}, ensure_ascii=False))
        print("::P2G2_DONE::")
        return 0

    # ---- Phase B: 実在らしきデータパスへAPI Keyを各搬送方式で送る
    data_paths = [(n, p) for n, p in alive if "topix" in p or "indices" in p]
    if not data_paths:
        data_paths = [("v2_indices_topix",
                       f"/v2/indices/topix?from={FROM_DATE}&to={TO_DATE}")]
    for path_name, path in data_paths[:3]:
        for tname, kind, header, template in AUTH_TRANSPORTS:
            headers = {header: template.format(key=secret)} if kind == "header" else {}
            status, body, err = _request(HOST + path, headers=headers)
            row = {"phase": "auth", "path": path_name, "transport": tname,
                   "error": err}
            row.update(_summarize(status, body, secret))
            print("::P2G2_AUTH::" + _scrub(json.dumps(row, ensure_ascii=False), secret))
            if status == 200 and row.get("rows"):
                print("::P2G2_AUTH::" + json.dumps(
                    {"phase": "auth", "result": "ACCEPTED", "path": path_name,
                     "transport": tname}, ensure_ascii=False))
                print("::P2G2_DONE::")
                return 0
    print("::P2G2_DONE::")
    return 0


if __name__ == "__main__":
    sys.exit(main())
