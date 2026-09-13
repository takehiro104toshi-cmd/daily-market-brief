"""HTTP transport抽象（Phase 1-C）。

- `HttpTransport` はProtocol。domain / fetcher / parser / store はHTTPライブラリへ
  直接依存しない（依存するのは本ファイルの実装1箇所のみ）。
- 実装は標準ライブラリ urllib（新規依存を増やさない。requests/httpx等が必要になったら
  その時に必要性を説明して追加する）。timeout必須。
- 本開発環境はegress遮断のため、実ネットワークはGitHub Actions等で実行する。
  テストはスタブtransportで完全オフライン（tank fetcherのtransport注入パターンを移植）。
"""
from __future__ import annotations

import re
import socket
import ssl
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Protocol, Tuple, runtime_checkable

from .model import FetchRequest, FetchResponse

DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_BODY_BYTES = 8 * 1024 * 1024  # フィード用途の安全上限（bulk取得はしない）

#: 連絡先を含む正直なUA（SEC等のフェアアクセス要件。tank build_user_agentの思想を継承）
DEFAULT_USER_AGENT = (
    "daily-market-brief-vnext/0.2 "
    "(+https://github.com/takehiro104toshi-cmd/daily-market-brief)"
)

DEFAULT_ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml, "
    "text/xml;q=0.9, application/json;q=0.8, */*;q=0.5"
)

#: 資格情報キーとみなすクエリパラメータ名（値をREDACTEDへ置換して保存する）
_SECRET_QUERY_KEYS = frozenset(
    {
        "subscription-key", "appid", "api_key", "apikey", "key", "token",
        "access_token", "secret", "password", "auth", "authorization",
        "signature", "sig", "client_secret", "credential", "credentials",
    }
)


def redact_url(url: str) -> str:
    """URL中の資格情報らしきクエリ値をREDACTEDへ置換する（保存・ログ用）。

    元のURL構造（キー・順序）は保ち、値だけを潰す。Secret値を保存経路へ流さない
    （tank T7の教訓 / docs/security/DATA_CLASSIFICATION_POLICY.md）。
    """
    if not url or "?" not in url:
        return url
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    redacted = [
        (k, "REDACTED" if k.lower() in _SECRET_QUERY_KEYS else v) for k, v in pairs
    ]
    query = urllib.parse.urlencode(redacted)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def classify_error(exc: BaseException) -> Tuple[str, str]:
    """例外 → (error_kind, detail)。detailへSecretは入り得ない（URL等は含めない）。"""
    detail = f"{type(exc).__name__}: {str(exc)[:160]}"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout", detail
    if isinstance(exc, ssl.SSLError):
        return "tls", detail
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, socket.gaierror):
            return "dns", detail
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "timeout", detail
        if isinstance(reason, ssl.SSLError):
            return "tls", detail
        return "connection", detail
    if isinstance(exc, ConnectionError):
        return "connection", detail
    return "unknown", detail


@runtime_checkable
class HttpTransport(Protocol):
    """HTTP GET 1回分の抽象（redirect追従込み）。"""

    def send(self, request: FetchRequest, *, timeout: float = DEFAULT_TIMEOUT) -> FetchResponse:  # pragma: no cover
        ...


class _RedirectRecorder(urllib.request.HTTPRedirectHandler):
    """redirect chainと恒久移転（301/308）を記録するハンドラ。"""

    def __init__(self) -> None:
        self.chain: list = []
        self.permanent = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        self.chain.append(newurl)
        if code in (301, 308):
            self.permanent = True
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibTransport:
    """標準ライブラリのみの実HTTP実装。gzip非対応の素朴なGET（Accept-Encodingは送らない＝
    サーバは非圧縮で返す。フィード用途ではサイズ影響軽微で、依存ゼロを優先）。

    auth_headers_provider（任意）: 監督者DESIGN CORRECTION 1のruntime credential注入点。
    永続FetchRequestはSecretを持てないまま（SECRET MUST NEVER BE PERSISTED）、
    送信直前の**ephemeralなrequestヘッダにのみ**資格情報を合成する
    （SECRET MUST NEVER BE USED ではない）。providerの返す値は
    serialization・JSONL・RawItem・FetchAttempt・log・error detailへ一切流れない。
    """

    def __init__(
        self,
        *,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        auth_headers_provider=None,  # Callable[[FetchRequest], Mapping[str, str]] | None
    ) -> None:
        self.max_body_bytes = max_body_bytes
        self._auth_headers_provider = auth_headers_provider

    def _headers_for(self, request: FetchRequest) -> dict:
        """送信ヘッダの組み立て（ephemeral。テスト可能に分離）。"""
        headers = {name: value for name, value in request.headers}
        headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
        headers.setdefault("Accept", DEFAULT_ACCEPT)
        if request.etag:
            headers["If-None-Match"] = request.etag
        if request.last_modified:
            headers["If-Modified-Since"] = request.last_modified
        if self._auth_headers_provider is not None:
            headers.update(self._auth_headers_provider(request))  # メモリ内のみ
        return headers

    def send(self, request: FetchRequest, *, timeout: float = DEFAULT_TIMEOUT) -> FetchResponse:
        started = _time.monotonic()
        headers = self._headers_for(request)

        recorder = _RedirectRecorder()
        opener = urllib.request.build_opener(recorder)
        req = urllib.request.Request(request.url, headers=headers, method=request.method)

        def _elapsed() -> int:
            return int((_time.monotonic() - started) * 1000)

        def _now() -> datetime:
            return datetime.now(timezone.utc)

        try:
            with opener.open(req, timeout=timeout) as resp:
                body = resp.read(self.max_body_bytes)
                return self._from_http(
                    status=resp.status,
                    headers=resp.headers,
                    body=body,
                    final_url=resp.geturl(),
                    recorder=recorder,
                    elapsed_ms=_elapsed(),
                    retrieved_at=_now(),
                )
        except urllib.error.HTTPError as exc:
            # 304/4xx/5xxはHTTPErrorとして届く。応答自体は成立している。
            try:
                body = exc.read(self.max_body_bytes) if exc.fp else b""
            except Exception:  # noqa: BLE001
                body = b""
            return self._from_http(
                status=exc.code,
                headers=exc.headers,
                body=body,
                final_url=exc.url or request.url,
                recorder=recorder,
                elapsed_ms=_elapsed(),
                retrieved_at=_now(),
            )
        except Exception as exc:  # noqa: BLE001 ネットワーク不成立
            kind, detail = classify_error(exc)
            return FetchResponse(
                status_code=0,
                final_url="",
                redirect_chain=tuple(recorder.chain),
                permanent_redirect=recorder.permanent,
                retrieved_at=_now(),
                elapsed_ms=_elapsed(),
                error_kind=kind,
                error_detail=detail,
            )

    @staticmethod
    def _from_http(*, status, headers, body, final_url, recorder, elapsed_ms, retrieved_at) -> FetchResponse:
        def h(name: str) -> str:
            try:
                return str(headers.get(name, "") or "")
            except Exception:  # noqa: BLE001
                return ""

        return FetchResponse(
            status_code=int(status),
            final_url=final_url or "",
            redirect_chain=tuple(recorder.chain),
            permanent_redirect=recorder.permanent,
            content_type=h("Content-Type"),
            etag=h("ETag"),
            last_modified=h("Last-Modified"),
            retry_after=h("Retry-After"),
            body=body or b"",
            retrieved_at=retrieved_at,
            elapsed_ms=elapsed_ms,
        )


_CHARSET_RE = re.compile(r"charset=([\w\-]+)", re.IGNORECASE)


def charset_from_content_type(content_type: str) -> Optional[str]:
    """Content-Typeヘッダからcharsetを抽出（無ければNone）。"""
    m = _CHARSET_RE.search(content_type or "")
    return m.group(1).lower() if m else None
