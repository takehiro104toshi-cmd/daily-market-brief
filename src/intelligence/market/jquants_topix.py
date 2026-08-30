"""J-Quants TOPIX provider（Phase 2-G / JPX公式系API）。

series identity:
- J-Quants（JPX子会社 JPX Market Innovation & Research 運営の公式データAPI）の
  指数四本値エンドポイント（/v1/indices/topix）が返す**TOPIX指数値そのもの**。
- **TOPIX ≠ TOPIX ETF（1306.T等） ≠ TOPIX先物**——ETF/先物を指数seriesへ
  投入しない（NO PROXY SUBSTITUTION）。

credential規律:
- 認証情報は環境変数（JQUANTS_MAIL / JQUANTS_PASSWORD、または
  JQUANTS_REFRESH_TOKEN）からの**runtime injectionのみ**。Git/config/カタログへ
  保存しない。未設定なら error_kind="no_credentials"（捏造・代用をしない）。
- 永続化されるURL（FetchAttempt/RawItem locator）は/indices/topixのみで、
  token類をクエリへ含めない。認証リクエスト自体は永続化しない。

値の忠実性:
- 応答JSONは `parse_float=str` で読み、数値トークンをstringのまま保持する
  （float非経由——P2-Dの値規律の維持）。bodyはAPI応答bytesそのまま保存
  （複数ページ時は改行連結し、その事実をparse_issuesへ申告）。
"""
from __future__ import annotations

import json
import os
import time as _time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Callable, Optional, Tuple

from .providers import ProviderFetchResult, ProviderRecord
from .series_catalog import SeriesSpec

JQUANTS_PROVIDER_ID = "jquants"
JQUANTS_BASE = "https://api.jquants.com/v1"
_TIMEOUT = 30.0

#: http_fn(url, method, headers, payload) -> (status_code, body_bytes)
HttpFn = Callable[[str, str, dict, bytes], Tuple[int, bytes]]


def _default_http(url: str, method: str, headers: dict, payload: bytes) -> Tuple[int, bytes]:
    request = urllib.request.Request(url, method=method)
    for key, value in headers.items():
        request.add_header(key, value)
    if payload:
        request.data = payload
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
        return resp.status, resp.read()


class JQuantsTopixProvider:
    """J-Quants /indices/topix のMarketDataProvider実装。"""

    def __init__(self, http_fn: Optional[HttpFn] = None, *, env=os.environ) -> None:
        self._http = http_fn or _default_http
        self._env = env

    @property
    def provider_id(self) -> str:
        return JQUANTS_PROVIDER_ID

    # ------------------------------------------------------------- auth

    def _id_token(self) -> str:
        """env credential → idToken。失敗はValueError（呼び出し側でerror化）。"""
        refresh = self._env.get("JQUANTS_REFRESH_TOKEN", "")
        if not refresh:
            mail = self._env.get("JQUANTS_MAIL", "")
            password = self._env.get("JQUANTS_PASSWORD", "")
            if not mail or not password:
                raise ValueError("no_credentials")
            status, body = self._http(
                f"{JQUANTS_BASE}/token/auth_user", "POST",
                {"Content-Type": "application/json"},
                json.dumps({"mailaddress": mail, "password": password}).encode())
            if status != 200:
                raise ValueError(f"auth_user_http_{status}")
            refresh = json.loads(body).get("refreshToken", "")
            if not refresh:
                raise ValueError("auth_user_no_refresh_token")
        status, body = self._http(
            f"{JQUANTS_BASE}/token/auth_refresh?refreshtoken="
            + urllib.parse.quote(refresh), "POST", {}, b"")
        if status != 200:
            raise ValueError(f"auth_refresh_http_{status}")
        id_token = json.loads(body).get("idToken", "")
        if not id_token:
            raise ValueError("auth_refresh_no_id_token")
        return id_token

    # ------------------------------------------------------------- fetch

    def fetch_daily_history(
        self, spec: SeriesSpec, *, start: date, end: date
    ) -> ProviderFetchResult:
        symbol = spec.symbol_for(self.provider_id) or ""
        now = datetime.now(timezone.utc)
        #: 永続化されるlocator（token・pagination_keyを含めない）
        public_url = f"{JQUANTS_BASE}/indices/topix?from={start.isoformat()}&to={end.isoformat()}"
        base = dict(provider_id=self.provider_id, series_id=spec.series_id,
                    symbol=symbol, url=public_url, retrieved_at=now)
        if not symbol:
            return ProviderFetchResult(
                **base, url="", error_kind="no_symbol",
                error_detail="catalogに本providerのsymbolなし")
        started = _time.monotonic()
        try:
            id_token = self._id_token()
        except ValueError as exc:
            return ProviderFetchResult(
                **base, error_kind=str(exc) if str(exc) == "no_credentials" else "auth_error",
                error_detail=("JQUANTS_MAIL/JQUANTS_PASSWORD（またはJQUANTS_REFRESH_TOKEN）"
                              "未設定——runtime injectionのみ・Git/configへ保存しない"
                              if str(exc) == "no_credentials" else str(exc)))
        except Exception as exc:  # noqa: BLE001
            return ProviderFetchResult(
                **base, error_kind="connection",
                error_detail=f"{type(exc).__name__}: {str(exc)[:120]}")

        headers = {"Authorization": f"Bearer {id_token}"}
        bodies = []
        rows = []
        issues = []
        pagination_key = ""
        status = 0
        for page in range(20):  # 安全上限（400日日足は通常1ページ）
            url = public_url + (
                f"&pagination_key={urllib.parse.quote(pagination_key)}"
                if pagination_key else "")
            try:
                status, body = self._http(url, "GET", headers, b"")
            except Exception as exc:  # noqa: BLE001
                return ProviderFetchResult(
                    **base, error_kind="connection", status_code=status,
                    error_detail=f"{type(exc).__name__}: {str(exc)[:120]}")
            if status != 200:
                return ProviderFetchResult(
                    **base, status_code=status, body=b"",
                    error_kind="http_error", error_detail=f"HTTP {status}")
            bodies.append(body)
            payload = json.loads(body, parse_float=str)
            rows.extend(payload.get("topix") or [])
            pagination_key = str(payload.get("pagination_key") or "")
            if not pagination_key:
                break
        if len(bodies) > 1:
            issues.append(f"paginated_response:{len(bodies)}pages")

        elapsed = int((_time.monotonic() - started) * 1000)
        raw_body = b"\n".join(bodies)
        if not rows:
            return ProviderFetchResult(
                **base, status_code=status, elapsed_ms=elapsed, body=raw_body,
                parse_issues=tuple(issues), error_kind="no_data",
                error_detail="empty topix payload")
        records = []
        for line_no, row in enumerate(sorted(rows, key=lambda r: str(r.get("Date", ""))),
                                      start=1):
            day = str(row.get("Date", ""))
            try:
                date.fromisoformat(day)
            except ValueError:
                issues.append(f"row{line_no}:invalid_date:{day[:20]}")
                continue
            token = row.get("Close", "")
            token = "" if token is None else str(token)
            records.append(ProviderRecord(trading_date=day, close=token,
                                          open=str(row.get("Open", "") or ""),
                                          high=str(row.get("High", "") or ""),
                                          low=str(row.get("Low", "") or ""),
                                          line_no=line_no))
        return ProviderFetchResult(
            **base, status_code=status, elapsed_ms=elapsed, body=raw_body,
            records=tuple(records), parse_issues=tuple(issues),
            media_type="application/json")
