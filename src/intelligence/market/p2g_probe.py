"""P2-G公式ソース実測プローブ（研究用・GitHub Actionsで実行）。

CRITICAL MARKET SOURCE GAP CLOSURE（TOPIX / JGB10Y / UST2Y）のsource調査:
- U.S. Treasury Daily Treasury Par Yield Curve Rates（CSVエンドポイント変種）
- 財務省 国債金利情報（jgbcm CSV・Shift_JIS）
- JPX TOPIXページ到達性
- J-Quants API到達性（credentialは環境変数からのruntime injectionのみ。
  未設定なら到達性チェックのみ——Git/configへのsecret保存は禁止）

**取得はしない・保存もしない**（応答の先頭/末尾スニペットと件数をmarkerとして
印字するだけの読み取り調査）。本番取込はprovider adapter側で行う。

出力: ::P2G_PROBE::{json} （logから機械抽出）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 30.0

#: 政府系サイトはWAFで非ブラウザUAを拒否することがあるため両方を実測する
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 market-brief-bot/1.0"
)
HONEST_UA = (
    "daily-market-brief-vnext/0.2 "
    "(+https://github.com/takehiro104toshi-cmd/daily-market-brief)"
)

TREASURY_BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv"
)


def _printable(text: str, limit: int) -> str:
    return "".join(c for c in text[:limit] if c.isprintable() or c in " \t")


def probe(name: str, url: str, *, ua: str = BROWSER_UA, method: str = "GET",
          payload: bytes = b"", encoding: str = "utf-8", note: str = "",
          redact_body: bool = False) -> dict:
    out = {"name": name, "url": url, "ua": "browser" if ua == BROWSER_UA else "honest",
           "status": 0, "bytes": 0, "content_type": "", "head": "", "tail": "",
           "lines": 0, "error": "", "note": note}
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", ua)
    request.add_header("Accept", "text/csv, text/plain, application/json, */*;q=0.5")
    if payload:
        request.add_header("Content-Type", "application/json")
        request.data = payload
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            body = resp.read(4 * 1024 * 1024)
            out["status"] = resp.status
            out["content_type"] = str(resp.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        body = exc.read(4096) if exc.fp else b""
        out["status"] = exc.code
        out["content_type"] = str(exc.headers.get("Content-Type", "")) if exc.headers else ""
    except Exception as exc:  # noqa: BLE001 研究プローブ——例外種別を記録して続行
        out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        print("::P2G_PROBE::" + json.dumps(out, ensure_ascii=False))
        return out
    out["bytes"] = len(body)
    text = body.decode(encoding, errors="replace")
    stripped = text.strip()
    lines = stripped.splitlines()
    out["lines"] = len(lines)
    if redact_body:
        # token等を含み得る応答はスニペットを一切印字しない（キー名の有無だけ申告）
        out["head"] = "REDACTED(token_response) has_refreshToken=" + str(
            "refreshToken" in text)
        out["tail"] = "REDACTED"
    else:
        out["head"] = _printable("\n".join(lines[:3]), 240)
        out["tail"] = _printable("\n".join(lines[-2:]), 200)
    print("::P2G_PROBE::" + json.dumps(out, ensure_ascii=False))
    return out


def main() -> int:
    # --- U.S. Treasury Daily Treasury Par Yield Curve Rates ---
    t2026 = (f"{TREASURY_BASE}/2026/all?type=daily_treasury_yield_curve"
             f"&field_tdr_date_value=2026&page&_format=csv")
    probe("treasury_2026_csv", t2026)
    probe("treasury_2026_csv_honest_ua", t2026, ua=HONEST_UA,
          note="UA要件の切り分け（fair-access UAが通るならそちらを使う）")
    probe("treasury_2025_csv",
          f"{TREASURY_BASE}/2025/all?type=daily_treasury_yield_curve"
          f"&field_tdr_date_value=2025&page&_format=csv")
    probe("treasury_all_csv",
          f"{TREASURY_BASE}/all/all?type=daily_treasury_yield_curve"
          f"&field_tdr_date_value=all&page&_format=csv",
          note="全履歴1ファイル変種の存在確認（有効なら1リクエストで期間充足）")

    # --- 財務省 国債金利情報（Shift_JIS CSV・和暦日付） ---
    probe("mof_jgbcm_current",
          "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv",
          encoding="cp932")
    probe("mof_jgbcm_all",
          "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv",
          encoding="cp932", note="全履歴ファイル（1974〜）")
    probe("mof_jgbcm_english",
          "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcm.csv",
          encoding="cp932", note="英語ページ側パスの確認")

    # --- JPX TOPIX（公式ページ到達性・公開データ形態の確認） ---
    probe("jpx_topix_page",
          "https://www.jpx.co.jp/english/markets/indices/topix/index.html",
          note="ページ到達性のみ（bulkはしない）")

    # --- J-Quants API（JPX子会社の公式API） ---
    mail = os.environ.get("JQUANTS_MAIL", "")
    password = os.environ.get("JQUANTS_PASSWORD", "")
    if mail and password:
        auth = probe("jquants_auth_user",
                     "https://api.jquants.com/v1/token/auth_user", method="POST",
                     payload=json.dumps({"mailaddress": mail,
                                         "password": password}).encode(),
                     note="credentialあり（runtime injection）——実認証",
                     redact_body=True)
        if auth["status"] == 200:
            print("::P2G_PROBE::" + json.dumps(
                {"name": "jquants_authenticated", "note":
                 "auth成功——本取得はprovider adapter側で実施"}, ensure_ascii=False))
    else:
        probe("jquants_reachability",
              "https://api.jquants.com/v1/token/auth_user", method="POST",
              payload=b"{}",
              note="credential未設定——到達性のみ（4xx JSONが返れば到達）")
    print("::P2G_PROBE_DONE::")
    return 0


if __name__ == "__main__":
    sys.exit(main())
