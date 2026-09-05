"""P2-G.1 認証方式判定プローブ（**HISTORICAL PROBE — production pathではない**）。

run #10〜#12 の調査で使用。V1エンドポイントに対する搬送方式の総当たり判定で、
**V1 EOLにより現行仕様ではない**（当時の403の記録はdocsに保全済み）。

隔離規律（tests/intelligence/test_legacy_isolation.py で固定）:
- production配線モジュール（pilot_runner / backfill / store 等）から参照しない
- workflowの実行ステップに入れない
- 当時の実測evidenceはdocs/へappend-onlyで保全してあるため、本ファイルは
  **再現・参照用**として残す（削除しない）

--- 以下、当時の実装ノート ---
J-Quants認証方式の実測プローブ（P2-G.1 / credential投入後）。

目的: **JQUANTS_API_KEY が現行の正式な認証方式か**を、公式ドキュメントと
実API応答から確定する。旧方式（mail/password → refreshToken → idToken）を
推測で使わないための証拠収集。

秘密の取り扱い（絶対規律）:
- API Key・token値は **stdout / URL / エラー文言 / 例外 へ一切出さない**。
  出力するのは候補方式名・HTTPステータス・応答キーの有無・件数・日付のみ。
- クエリに秘密を載せる候補ではURLをredactして表示する。
- 応答本文はそのまま印字しない（tokenを含み得るため、キー有無と長さだけ）。
- 全出力を最終scrubに通す（万一の混入を型で潰す）。

出力marker: ::P2G1_AUTH::{json}
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.jquants.com/v1"
TIMEOUT = 30.0
UA = ("daily-market-brief-vnext/0.2 "
      "(+https://github.com/takehiro104toshi-cmd/daily-market-brief)")

#: 動作確認に使う軽量なTOPIX問い合わせ（1営業日分）
TOPIX_PATH = "/indices/topix?from=2026-08-24&to=2026-08-28"


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret and secret in text else text


def _request(url: str, *, method: str = "GET", headers: dict = None,
             payload: bytes = b"") -> tuple:
    """(status, body_bytes, error_str) — 例外は種別のみへ写像する。"""
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", UA)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if payload:
        request.add_header("Content-Type", "application/json")
        request.data = payload
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(2 * 1024 * 1024), ""
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read(4096) if exc.fp else b""), ""
    except Exception as exc:  # noqa: BLE001
        return 0, b"", type(exc).__name__


def _summarize(status: int, body: bytes, secret: str) -> dict:
    """応答の**安全な要約**（token値は出さない・キー有無と件数のみ）。"""
    out = {"status": status, "bytes": len(body)}
    try:
        payload = json.loads(body or b"{}")
    except Exception:  # noqa: BLE001
        out["json"] = False
        return out
    out["json"] = True
    if isinstance(payload, dict):
        out["keys"] = sorted(payload)[:8]
        out["has_id_token"] = bool(payload.get("idToken"))
        out["has_refresh_token"] = bool(payload.get("refreshToken"))
        rows = payload.get("topix")
        if isinstance(rows, list):
            out["topix_rows"] = len(rows)
            if rows:
                dates = [str(r.get("Date", "")) for r in rows if isinstance(r, dict)]
                out["first_date"] = min(dates) if dates else ""
                out["last_date"] = max(dates) if dates else ""
                out["row_keys"] = sorted(rows[0])[:10] if isinstance(rows[0], dict) else []
        message = payload.get("message")
        if isinstance(message, str):
            out["message"] = _scrub(message[:120], secret)
    return out


def probe_candidate(name: str, secret: str, *, note: str) -> dict:
    """候補方式を1つ試す（秘密は出力しない）。"""
    if name == "api_key_as_refresh_token_query":
        url = f"{BASE}/token/auth_refresh?refreshtoken=" + urllib.parse.quote(secret)
        display = f"{BASE}/token/auth_refresh?refreshtoken=REDACTED"
        status, body, err = _request(url, method="POST")
    elif name == "api_key_as_refresh_token_body":
        url = display = f"{BASE}/token/auth_refresh"
        status, body, err = _request(
            url, method="POST", payload=json.dumps({"refreshtoken": secret}).encode())
    elif name == "api_key_as_id_token_bearer":
        url = display = f"{BASE}{TOPIX_PATH}"
        status, body, err = _request(url, headers={"Authorization": f"Bearer {secret}"})
    elif name == "api_key_header_x_api_key":
        url = display = f"{BASE}{TOPIX_PATH}"
        status, body, err = _request(url, headers={"x-api-key": secret})
    elif name == "api_key_authorization_raw":
        url = display = f"{BASE}{TOPIX_PATH}"
        status, body, err = _request(url, headers={"Authorization": secret})
    else:
        raise ValueError(name)
    result = {"candidate": name, "url": display, "note": note, "error": err}
    result.update(_summarize(status, body, secret))
    return result


def main() -> int:
    secret = os.environ.get("JQUANTS_API_KEY", "").strip()
    if not secret:
        print("::P2G1_AUTH::" + json.dumps(
            {"credential_present": False,
             "detail": "JQUANTS_API_KEY未設定——候補試行なし（ネットワークを叩かない）"},
            ensure_ascii=False))
        return 0

    # ---- 公式ドキュメント/仕様の機械取得可能性（本文が取れるか） ----
    docs = []
    for label, url in (
        ("openapi_v1", f"{BASE}/openapi.json"),
        ("openapi_root", "https://api.jquants.com/openapi.json"),
        ("api_root", BASE),
        ("docs_gitbook_en", "https://jpx.gitbook.io/j-quants-en/api-reference/refreshtoken"),
        ("docs_gitbook_ja", "https://jpx.gitbook.io/j-quants-ja/api-reference/refreshtoken"),
    ):
        status, body, err = _request(url)
        text = body.decode("utf-8", errors="replace")[:400]
        machine_readable = bool(text.strip().startswith(("{", "[")))
        docs.append({"doc": label, "status": status, "bytes": len(body),
                     "error": err, "machine_readable_body": machine_readable})
    print("::P2G1_AUTH_DOCS::" + json.dumps(docs, ensure_ascii=False))

    # ---- 候補方式の実測（どれが現行APIで通るか） ----
    candidates = [
        ("api_key_as_refresh_token_query",
         "J-Quants従来仕様: refreshtokenをクエリで渡しidTokenを得る"),
        ("api_key_as_refresh_token_body", "同・body渡しの可能性"),
        ("api_key_as_id_token_bearer", "API KeyがidToken相当でBearer直挿しの可能性"),
        ("api_key_header_x_api_key", "x-api-keyヘッダ方式の可能性"),
        ("api_key_authorization_raw", "Authorizationへ生値を入れる方式の可能性"),
    ]
    results = []
    for name, note in candidates:
        try:
            results.append(probe_candidate(name, secret, note=note))
        except Exception as exc:  # noqa: BLE001
            results.append({"candidate": name, "error": type(exc).__name__})
    for row in results:
        print("::P2G1_AUTH::" + _scrub(json.dumps(row, ensure_ascii=False), secret))

    # ---- 2段階（API Key→idToken→data）が通るかの結線確認 ----
    chained = {"chain": "refresh_token_query -> bearer -> topix"}
    url = f"{BASE}/token/auth_refresh?refreshtoken=" + urllib.parse.quote(secret)
    status, body, err = _request(url, method="POST")
    chained["auth_status"] = status
    id_token = ""
    if status == 200:
        try:
            id_token = str(json.loads(body).get("idToken", ""))
        except Exception:  # noqa: BLE001
            id_token = ""
    chained["got_id_token"] = bool(id_token)
    if id_token:
        status2, body2, err2 = _request(
            f"{BASE}{TOPIX_PATH}", headers={"Authorization": f"Bearer {id_token}"})
        summary = _summarize(status2, body2, id_token)
        summary.pop("keys", None)
        chained["data_fetch"] = summary
        chained["data_error"] = err2
    print("::P2G1_AUTH::" + _scrub(
        _scrub(json.dumps(chained, ensure_ascii=False), secret), id_token))
    print("::P2G1_AUTH_DONE::")
    return 0


if __name__ == "__main__":
    sys.exit(main())
