"""P8-LIVE2 — 本人の private ／ local な環境でだけ実行する、最小の実 HTTPS transport（凍結 LIVE1 の `Transport` の実装）。

authority ・利用の境界は凍結の P8-LIVE0 ・LIVE1（private の pilot だけ ・公開なし ・raw は memory だけ ・LLM に payload を入れない）。
本 module は repo に置かれるが、**実の J-Quants への実行は、監督の承認の後の PILOT2 で、本人の環境でだけ**行う。Pages ・Morning Brief ・
GitHub Actions ・cloud の自動化 ・LLM の経路 ・顧客向けの出力には繋がない（import する物は無い。guard）。

契約:
- HTTPS だけ。host は `api.jquants.com` に固定（caller は host ・絶対 URL を渡せない）。path は凍結 LIVE1 の `ALLOWED_PATHS`、query の key は
  `ALLOWED_QUERY_KEYS` だけ（credential の key は LIVE1 の `canonical_query` が拒む）。
- `get()` 1 回 ＝ HTTP GET **最大 1 回**。retry ・pagination の自動追随 ・cache ・背景の呼び出しは無い。予算は凍結 LIVE1 の `RequestBudget`
  （client が transport の前に消費）が持ち、本 module は第 2 の予算 ・retry を持たない。
- credential は caller が名を選ぶ環境変数（既定 `JQUANTS_API_KEY`）から `get()` のたびに読み、`x-api-key` header に付けて捨てる
  （公式 V2 の認証。P8-LIVE0 L5 ・L4）。object に保持しない ・`repr` ・`str` ・例外 ・結果に出さない ・他の環境変数を列挙 ・検査しない。
  無い ・空 → network の前に `CREDENTIAL_MISSING`。
- redirect は追わない（`http.client` は追随しない）。3xx は `HTTP_STATUS_3xx` で fail closed。credential を他の origin に転送しない。
- 応答は status ＋ 本文（上限 `MAX_RESPONSE_BYTES`。超過は parse の前に `RESPONSE_TOO_LARGE`）。本文は UTF-8 の JSON object で
  なければ `RESPONSE_NOT_JSON`。200 以外は本文を捨て `HTTP_STATUS_<code>`（本文 ・header は例外に入れない）。
- timeout は有限（既定 20 秒）。network の失敗は `NETWORK_TIMEOUT` ／ `TLS_ERROR` ／ `NETWORK_ERROR`（本文 ・host 名の詳細なし）。
- filesystem ・log ・cache ・debug の出力は無い。応答の本文は返した後に保持しない。

記録: `docs/databank/PHASE8_LIVE2_LOCAL_HTTP_TRANSPORT.md`。
"""
from __future__ import annotations

import http.client
import json
import os
import ssl
from typing import Any, Mapping
from urllib.parse import urlencode

from .screener_intelligence.jquants_live_model import (ALLOWED_PATHS, LiveInputError, Transport, TransportResponse,
                                                       canonical_query)

TRANSPORT_RULES_VERSION = "p8_jquants_local_transport:0.1.0"
#: 固定の host（caller は変えられない。scheme は HTTPS だけ。URL 文字列は作らない）
SANCTIONED_HOST = "api.jquants.com"
SANCTIONED_PORT = 443
#: 公式 V2 の認証 header（P8-LIVE0 L5: `x-api-key` Required）
AUTH_HEADER = "x-api-key"
DEFAULT_CREDENTIAL_ENV = "JQUANTS_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_SECONDS = 60.0
#: 応答の本文の上限（bytes）。master の全銘柄 snapshot（約 4,500 行）を十分に受け、無限の本文を拒む
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_ENV_NAME_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
_HTTPSConnection = http.client.HTTPSConnection


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise LiveInputError(code, detail)


class LocalHttpsTransport(Transport):
    """本人の環境でだけ使う実 HTTPS transport。credential ・本文 ・URL を保持しない。`repr` は設定の名前だけ。"""

    def __init__(self, credential_env: str = DEFAULT_CREDENTIAL_ENV, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 max_response_bytes: int = MAX_RESPONSE_BYTES) -> None:
        _require(isinstance(credential_env, str) and 1 <= len(credential_env) <= 64
                 and all(c in _ENV_NAME_CHARS for c in credential_env) and credential_env[0].isalpha(),
                 "INVALID_CREDENTIAL_ENV", "credential_env")
        _require(isinstance(timeout_seconds, (int, float)) and not isinstance(timeout_seconds, bool)
                 and 0 < float(timeout_seconds) <= MAX_TIMEOUT_SECONDS, "INVALID_TIMEOUT", "timeout_seconds")
        _require(type(max_response_bytes) is int and 1024 <= max_response_bytes <= MAX_RESPONSE_BYTES,
                 "INVALID_RESPONSE_LIMIT", "max_response_bytes")
        self._credential_env = credential_env
        self._timeout = float(timeout_seconds)
        self._max_bytes = max_response_bytes
        self._attempts = 0

    def __repr__(self) -> str:                                                   # 名前と設定だけ（値は無い）
        return (f"LocalHttpsTransport(host={SANCTIONED_HOST!r}, credential_env={self._credential_env!r}, "
                f"timeout_seconds={self._timeout}, max_response_bytes={self._max_bytes})")

    @property
    def attempts(self) -> int:
        """発した HTTP GET の回数（失敗を含む）。`get()` 1 回につき最大 1。"""
        return self._attempts

    def _credential(self) -> str:
        value = os.environ.get(self._credential_env)                             # 名を指定した 1 変数だけを読む
        _require(isinstance(value, str) and value.strip() != "", "CREDENTIAL_MISSING", "credential_env")
        return value.strip()

    @staticmethod
    def _target(path: str, params: Mapping[str, str]) -> str:
        _require(isinstance(path, str) and path in ALLOWED_PATHS, "PATH_NOT_ALLOWED", "path")
        query = canonical_query(params)                                          # 許した key だけ ・credential の key は拒む
        return f"{path}?{urlencode(query)}" if query else path

    def get(self, path: str, params: Mapping[str, str]) -> TransportResponse:
        target = self._target(path, params)                                      # network の前に path ・query を検査
        credential = self._credential()                                          # network の前に credential を検査
        connection = None
        try:
            connection = _HTTPSConnection(SANCTIONED_HOST, SANCTIONED_PORT, timeout=self._timeout,
                                          context=ssl.create_default_context())
            self._attempts += 1                                                  # 1 回だけ。失敗しても再試行しない
            connection.request("GET", target, headers={AUTH_HEADER: credential, "Accept": "application/json"})
            response = connection.getresponse()
            status = int(response.status)
            body = response.read(self._max_bytes + 1)
        except ssl.SSLError:
            raise LiveInputError("TLS_ERROR", "connection") from None
        except TimeoutError:
            raise LiveInputError("NETWORK_TIMEOUT", "connection") from None
        except (OSError, http.client.HTTPException):
            raise LiveInputError("NETWORK_ERROR", "connection") from None
        finally:
            credential = ""
            if connection is not None:
                connection.close()
        _require(status == 200, f"HTTP_STATUS_{status}" if 100 <= status <= 599 else "HTTP_STATUS_INVALID", "status")
        _require(len(body) <= self._max_bytes, "RESPONSE_TOO_LARGE", "body")
        try:
            text = body.decode("utf-8")
            decoded: Any = json.loads(text)
        except (UnicodeDecodeError, ValueError):
            raise LiveInputError("RESPONSE_NOT_JSON", "body") from None
        _require(isinstance(decoded, dict), "RESPONSE_NOT_OBJECT", "body")
        return TransportResponse(status, text)


__all__ = ["AUTH_HEADER", "DEFAULT_CREDENTIAL_ENV", "DEFAULT_TIMEOUT_SECONDS", "MAX_RESPONSE_BYTES",
           "MAX_TIMEOUT_SECONDS", "SANCTIONED_HOST", "SANCTIONED_PORT", "TRANSPORT_RULES_VERSION",
           "LocalHttpsTransport"]
