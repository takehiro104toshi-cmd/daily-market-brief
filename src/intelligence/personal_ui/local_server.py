"""P11-A2 — 決定論の loopback の local server（read-only ・private ・stdlib だけ）。

P10 ／ P9 の root → P11-A1 の adapter（`read_ui_model`）→ 本 server → JSON。他の経路は無い。

- bind は `127.0.0.1` だけ（全ての interface ・LAN ・hostname ・空 ・`::1` は v1 で拒む）。port は 0（OS が割り当て）〜 65535 の整数。
- 起動は明示の `--p10-root` ・`--p9-root`（自動の発見 ・環境の fallback ・既定の private な path は無い）。root は応答 ・log ・誤り ・
  起動の出力に出さない（`ServerContext` の repr も隠す）。`JQUANTS_API_KEY` が空でなく在れば起動を拒む（値は見ない ・出さない）。
- 経路: `GET /health` ・`GET /version` ・`GET /`（固定の JSON）・`POST /api/view`（body の JSON `{"at","as_of_date"}` だけ ・query は
  使わない）。他は 404 ・他の method は 405。書き込み ・file の閲覧 ・debug ・directory の一覧は無い。
- `Host` は `127.0.0.1:<bound port>` と完全一致だけ（`localhost` ・`X-Forwarded-*` は信じない）。`/api/*` は `Sec-Fetch-Site` が
  在れば `same-origin` ／ `none` だけ ・`Origin` が在れば自分の origin だけ（無ければ CLI ／ test の client として許す。Host ・loopback が
  守る）。CORS の header は出さない。
- static な shell（P11-A3）: `/app/` の下の **allowlist の経路だけ**を、起動の時に package の `static/` から読んだ committed な byte の
  まま配る（directory の一覧 ・任意の file ・path の露出は無い）。`Cache-Control: no-cache` ・CSP（`'self'` だけ）・COOP。
- 応答は P11-A1 の正準の byte をそのまま（再直列化しない）。header は固定（`Cache-Control: no-store` 他）。`Date` ・`Server` は出さない
  （`send_response_only`）。result の cache ・memo は無い（毎回 governed な read）。
- 誤りは正準の JSON `{"code","detail","schema_version"}`。detail は大文字の code だけ。予期しない例外は `INTERNAL_ERROR`（traceback ・
  path ・id は出ない）。log は既定で無し。`on_event(method, route, status, kind)` に安全な事柄だけ渡せる（body ・瞬間 ・Host は渡さない）。

記録: `docs/databank/PHASE11_A2_LOOPBACK_SERVER.md`。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .p10_read_adapter import ADAPTER_RULES_VERSION, read_ui_model
from .ui_model import UI_ERROR_SCHEMA_VERSION, UI_MODEL_SCHEMA_VERSION, UiReadError, canonical_json, ui_model_json_bytes

SERVER_SCHEMA_VERSION = "p11_local_server:0.1.0"
LOOPBACK_BIND = "127.0.0.1"
MAX_BODY_BYTES = 4096
MAX_VALUE_CHARS = 40
CREDENTIAL_VARIABLE = "JQUANTS_API_KEY"
VIEW_ROUTE = "/api/view"
GET_ROUTES = ("/", "/health", "/version")
KNOWN_ROUTES = GET_ROUTES + (VIEW_ROUTE,)
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
COMMON_HEADERS: Tuple[Tuple[str, str], ...] = (("Pragma", "no-cache"), ("X-Content-Type-Options", "nosniff"),
                                               ("Referrer-Policy", "no-referrer"),
                                               ("Cross-Origin-Resource-Policy", "same-origin"))
SAFE_HEADERS: Tuple[Tuple[str, str], ...] = (("Cache-Control", "no-store"),) + COMMON_HEADERS
#: static な shell（P11-A3）: 経路 → (package の static/ の file, Content-Type)。この allowlist の外は配らない
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_ROUTES: Mapping[str, Tuple[str, str]] = {
    "/app/": ("index.html", "text/html; charset=utf-8"),
    "/app/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/app/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/app/icon-192.png": ("icon-192.png", "image/png"),
    "/app/icon-512.png": ("icon-512.png", "image/png"),
}
STATIC_CACHE_CONTROL = "no-cache"
CONTENT_SECURITY_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
                           "manifest-src 'self'; worker-src 'self'; base-uri 'none'; form-action 'self'; "
                           "frame-ancestors 'none'; object-src 'none'")
STATIC_EXTRA_HEADERS: Tuple[Tuple[str, str], ...] = (("Content-Security-Policy", CONTENT_SECURITY_POLICY),
                                                     ("Cross-Origin-Opener-Policy", "same-origin"))
_AT_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?[+-]\d{2}:\d{2}\Z")   # 末尾の改行も拒む
_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_SAFE_DETAIL_RE = re.compile(r"^[A-Z0-9_:]{1,80}$")
_STATUS_CODES = {400: "BAD_REQUEST", 403: "FETCH_SITE_REJECTED", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
                 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 503: "VIEW_UNAVAILABLE",
                 500: "INTERNAL_ERROR"}
EventSink = Callable[[str, str, int, str], None]


class ServerStartupError(RuntimeError):
    """起動の拒否（安全な code だけ）。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Refusal(Exception):
    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail


def _safe_detail(detail: Any) -> str:
    return detail if isinstance(detail, str) and _SAFE_DETAIL_RE.match(detail) else ""


def error_bytes(code: str, detail: str = "") -> bytes:
    return canonical_json({"code": code, "detail": _safe_detail(detail),
                           "schema_version": SERVER_SCHEMA_VERSION}).encode("utf-8")


STATUS_BYTES = canonical_json({"schema_version": SERVER_SCHEMA_VERSION, "status": "ok"}).encode("utf-8")
VERSION_BYTES = canonical_json({"adapter_rules_version": ADAPTER_RULES_VERSION, "schema_version": SERVER_SCHEMA_VERSION,
                                "ui_error_schema_version": UI_ERROR_SCHEMA_VERSION,
                                "ui_model_schema_version": UI_MODEL_SCHEMA_VERSION}).encode("utf-8")


@dataclass(frozen=True, repr=False)
class ServerContext:
    """server が読み込みに使う private な文脈。repr ・str に root を出さない。"""

    p10_root: Any
    p9_root: Any
    port: int
    on_event: Optional[EventSink] = None
    static_assets: Mapping[str, bytes] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"ServerContext(port={self.port}, roots=<private>)"

    __str__ = __repr__


# ---------------------------------------------------------------- 起動の検査


def _check_credential_absent() -> None:
    if os.environ.get(CREDENTIAL_VARIABLE, "") != "":                              # 値は見ない ・出さない
        raise ServerStartupError("CREDENTIAL_PRESENT")


def _check_bind(bind: Any) -> str:
    if not isinstance(bind, str) or bind.strip() == "":
        raise ServerStartupError("BIND_REQUIRED")
    try:
        address = ipaddress.ip_address(bind)
    except ValueError:
        raise ServerStartupError("BIND_NOT_LOOPBACK") from None
    if address != ipaddress.IPv4Address(LOOPBACK_BIND):
        raise ServerStartupError("BIND_NOT_LOOPBACK")
    return LOOPBACK_BIND


def _check_port(port: Any) -> int:
    if type(port) is not int or not 0 <= port <= 65535:
        raise ServerStartupError("PORT_INVALID")
    return port


def _load_static_assets() -> Dict[str, bytes]:
    """起動の時に allowlist の asset を package の static/ から読む（committed な byte のまま ・無ければ起動を拒む）。"""
    loaded: Dict[str, bytes] = {}
    for route, (name, _content_type) in STATIC_ROUTES.items():
        try:
            loaded[route] = (STATIC_DIR / name).read_bytes()
        except OSError:
            raise ServerStartupError("STATIC_ASSET_MISSING") from None
    return loaded


def _check_root(value: Any, code: str) -> Any:
    if isinstance(value, str):
        ok = value.strip() != ""
    else:
        ok = hasattr(value, "__fspath__")
    if not ok:
        raise ServerStartupError(code)
    return value


# ---------------------------------------------------------------- 要求の検査（/api/view）


def _no_duplicate_pairs(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _Refusal(400, "BAD_REQUEST", "DUPLICATE_KEY")
    return dict(pairs)


def _reject_constant(_name: str) -> None:
    raise _Refusal(400, "BAD_REQUEST", "MALFORMED_JSON")


def parse_view_request(body: bytes) -> Tuple[datetime, date]:
    """body の JSON → (aware な瞬間, 日)。鍵は `at` ・`as_of_date` だけ ・文字列 ・短い ・ISO の形。寛容な変換はしない。"""
    if body == b"":
        raise _Refusal(400, "BAD_REQUEST", "EMPTY_BODY")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise _Refusal(400, "BAD_REQUEST", "BODY_NOT_UTF8") from None
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_pairs, parse_constant=_reject_constant)
    except ValueError:
        raise _Refusal(400, "BAD_REQUEST", "MALFORMED_JSON") from None
    if not isinstance(payload, dict):
        raise _Refusal(400, "BAD_REQUEST", "NOT_OBJECT")
    if set(payload) - {"at", "as_of_date"}:
        raise _Refusal(400, "BAD_REQUEST", "UNKNOWN_KEYS")
    if {"at", "as_of_date"} - set(payload):
        raise _Refusal(400, "BAD_REQUEST", "MISSING_KEYS")
    for key in ("at", "as_of_date"):
        value = payload[key]
        if not isinstance(value, str):
            raise _Refusal(400, "BAD_REQUEST", f"VALUE_NOT_STRING:{key.upper()}")
        if len(value) > MAX_VALUE_CHARS:
            raise _Refusal(400, "BAD_REQUEST", f"VALUE_TOO_LONG:{key.upper()}")
    if not _AT_RE.match(payload["at"]):
        raise _Refusal(400, "VIEW_INPUT_INVALID", "AT_FORMAT")
    if not _DATE_RE.match(payload["as_of_date"]):
        raise _Refusal(400, "VIEW_INPUT_INVALID", "AS_OF_DATE_FORMAT")
    try:
        at = datetime.fromisoformat(payload["at"])
    except ValueError:
        raise _Refusal(400, "VIEW_INPUT_INVALID", "AT_INVALID") from None
    try:
        as_of = date.fromisoformat(payload["as_of_date"])
    except ValueError:
        raise _Refusal(400, "VIEW_INPUT_INVALID", "AS_OF_DATE_INVALID") from None
    return at, as_of


def _map_read_error(exc: UiReadError) -> _Refusal:
    if exc.code == "INPUT_INVALID":
        return _Refusal(400, "VIEW_INPUT_INVALID", exc.detail)
    return _Refusal(503, "VIEW_UNAVAILABLE", f"{exc.code}:{exc.detail}" if exc.detail else exc.code)


# ---------------------------------------------------------------- handler


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = 10
    server: "LoopbackHTTPServer"

    # ---- log は既定で無し（本文 ・瞬間 ・Host ・path を出さない）
    def log_message(self, format: str, *args: Any) -> None:                        # noqa: A002 - stdlib の署名
        return None

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        return None

    def log_error(self, format: str, *args: Any) -> None:                          # noqa: A002 - stdlib の署名
        return None

    def send_error(self, code: int, message: Optional[str] = None, explain: Optional[str] = None) -> None:
        """stdlib の解析の失敗（長すぎる要求行 ・不明な method 等）も正準の JSON で（HTML ・Server ・Date は出さない）。"""
        status = 405 if code == 501 else (400 if 400 <= code < 500 else 500)
        self._respond(status, error_bytes(_STATUS_CODES[status]), route="UNKNOWN", kind="PARSE")

    # ---- 応答（決定論の header ・Date ・Server なし）
    def _respond(self, status: int, body: bytes, *, route: str, kind: str = "", allow: str = "",
                 content_type: str = JSON_CONTENT_TYPE, cache_control: str = "no-store",
                 extra: Tuple[Tuple[str, str], ...] = ()) -> None:
        self.close_connection = True
        self.send_response_only(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        for name, value in COMMON_HEADERS + extra:
            self.send_header(name, value)
        if allow:
            self.send_header("Allow", allow)
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        sink = self.server.context.on_event
        if sink is not None:
            sink(self.command or "", route, status, kind)

    def _route(self) -> str:
        return self.path if (self.path in KNOWN_ROUTES or self.path in STATIC_ROUTES) else "UNKNOWN"

    def _check_host(self) -> None:
        expected = f"{LOOPBACK_BIND}:{self.server.context.port}"
        if self.headers.get("Host") != expected:                                   # 完全一致。X-Forwarded-* は見ない
            raise _Refusal(400, "HOST_REJECTED")

    def _check_fetch_site(self) -> None:
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            raise _Refusal(403, "FETCH_SITE_REJECTED", "SEC_FETCH_SITE")
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{LOOPBACK_BIND}:{self.server.context.port}":
            raise _Refusal(403, "FETCH_SITE_REJECTED", "ORIGIN")

    def _read_body(self) -> bytes:
        if self.headers.get("Transfer-Encoding") is not None:
            raise _Refusal(400, "BAD_REQUEST", "TRANSFER_ENCODING")
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise _Refusal(415, "UNSUPPORTED_MEDIA_TYPE")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            raise _Refusal(400, "BAD_REQUEST", "CONTENT_LENGTH")
        length = int(raw_length)
        if length == 0:
            raise _Refusal(400, "BAD_REQUEST", "EMPTY_BODY")
        if length > MAX_BODY_BYTES:
            raise _Refusal(413, "PAYLOAD_TOO_LARGE")
        body = self.rfile.read(length)
        if len(body) != length:
            raise _Refusal(400, "BAD_REQUEST", "BODY_TRUNCATED")
        return body

    def _dispatch(self, method: str) -> None:
        route = self._route()
        try:
            self._check_host()
            if route == "UNKNOWN":
                raise _Refusal(404, "NOT_FOUND")
            if route in GET_ROUTES:
                if method != "GET":
                    raise _Refusal(405, "METHOD_NOT_ALLOWED")
                self._respond(200, VERSION_BYTES if route == "/version" else STATUS_BYTES, route=route, kind="OK")
                return
            if route in STATIC_ROUTES:                                                 # P11-A3: committed な shell の byte
                if method != "GET":
                    raise _Refusal(405, "METHOD_NOT_ALLOWED")
                self._respond(200, self.server.context.static_assets[route], route=route, kind="OK",
                              content_type=STATIC_ROUTES[route][1], cache_control=STATIC_CACHE_CONTROL,
                              extra=STATIC_EXTRA_HEADERS)
                return
            if method != "POST":
                raise _Refusal(405, "METHOD_NOT_ALLOWED")
            self._check_fetch_site()
            at, as_of = parse_view_request(self._read_body())
            try:
                body = ui_model_json_bytes(read_ui_model(self.server.context.p10_root, self.server.context.p9_root,
                                                        at=at, as_of_date=as_of))   # P11-A1 の正準の byte をそのまま
            except UiReadError as exc:
                raise _map_read_error(exc) from None
            self._respond(200, body, route=route, kind="OK")
        except _Refusal as refusal:
            allow = ("POST" if route == VIEW_ROUTE else "GET") if refusal.status == 405 else ""
            self._respond(refusal.status, error_bytes(refusal.code, refusal.detail), route=route, kind=refusal.code,
                          allow=allow)
        except Exception as exc:  # noqa: BLE001 - 予期しない例外は安全な INTERNAL_ERROR に（内容は出さない）
            self._respond(500, error_bytes("INTERNAL_ERROR"), route=route, kind=type(exc).__name__)

    def do_GET(self) -> None:                                                      # noqa: N802 - stdlib の規約
        self._dispatch("GET")

    def do_POST(self) -> None:                                                     # noqa: N802 - stdlib の規約
        self._dispatch("POST")


class LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8
    allow_reuse_address = False

    def __init__(self, context_factory: Callable[[int], ServerContext]) -> None:
        super().__init__((LOOPBACK_BIND, 0), _Handler, bind_and_activate=False)
        self.context: ServerContext = ServerContext(p10_root="", p9_root="", port=0)
        self._context_factory = context_factory

    def bind_to(self, port: int) -> None:
        self.server_address = (LOOPBACK_BIND, port)
        self.server_bind()
        self.server_activate()
        self.context = self._context_factory(int(self.server_address[1]))


class LocalServer:
    """起動の検査 → loopback に bind した server。`url` は `http://127.0.0.1:<port>/`（root は出さない）。"""

    def __init__(self, server: LoopbackHTTPServer) -> None:
        self._server = server
        self._thread: Optional[threading.Thread] = None

    @classmethod
    def start(cls, p10_root: Any, p9_root: Any, *, bind: str = LOOPBACK_BIND, port: int = 0,
              on_event: Optional[EventSink] = None) -> "LocalServer":
        _check_credential_absent()                                                 # 起動の時だけ（値は見ない）
        _check_bind(bind)
        bound_port = _check_port(port)
        _check_root(p10_root, "P10_ROOT_REQUIRED")
        _check_root(p9_root, "P9_ROOT_REQUIRED")
        static_assets = _load_static_assets()

        def factory(actual_port: int) -> ServerContext:
            return ServerContext(p10_root=p10_root, p9_root=p9_root, port=actual_port, on_event=on_event,
                                 static_assets=static_assets)

        server = LoopbackHTTPServer(factory)
        try:
            server.bind_to(bound_port)
        except OSError:
            server.server_close()
            raise ServerStartupError("BIND_FAILED") from None
        return cls(server)

    @property
    def port(self) -> int:
        return self._server.context.port

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK_BIND}:{self.port}/"

    @property
    def app_url(self) -> str:
        return self.url + "app/"

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.2)

    def start_in_thread(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, name="p11-local-server", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        """serve の loop が走っていればそれを止め、socket を閉じる（走っていなければ閉じるだけ。待たない）。"""
        if self._thread is not None and self._thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __repr__(self) -> str:
        return f"LocalServer(url={self.url!r})"


# ---------------------------------------------------------------- CLI（private ・local だけ）


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal_ui.local_server", description="Phase 11 private loopback server")
    parser.add_argument("--p10-root", required=True)
    parser.add_argument("--p9-root", required=True)
    parser.add_argument("--bind", default=LOOPBACK_BIND)
    parser.add_argument("--port", type=int, default=0)
    return parser


def main(argv: Optional[Sequence[str]] = None, stdout: Optional[Any] = None) -> int:
    stream = stdout if stdout is not None else sys.stdout
    args = _parser().parse_args(argv)
    try:
        server = LocalServer.start(args.p10_root, args.p9_root, bind=args.bind, port=args.port)
    except ServerStartupError as exc:
        stream.write(canonical_json({"code": exc.code, "schema_version": SERVER_SCHEMA_VERSION,
                                     "status": "refused"}) + "\n")
        stream.flush()
        return 2
    stream.write(canonical_json({"app_url": server.app_url, "schema_version": SERVER_SCHEMA_VERSION,
                                 "status": "listening", "url": server.url}) + "\n")
    stream.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


__all__ = ["CONTENT_SECURITY_POLICY", "CREDENTIAL_VARIABLE", "KNOWN_ROUTES", "LOOPBACK_BIND", "LocalServer",
           "MAX_BODY_BYTES", "SAFE_HEADERS", "SERVER_SCHEMA_VERSION", "STATIC_CACHE_CONTROL", "STATIC_EXTRA_HEADERS",
           "STATIC_ROUTES", "STATUS_BYTES", "ServerContext", "ServerStartupError", "VERSION_BYTES", "VIEW_ROUTE",
           "error_bytes", "main", "parse_view_request"]


if __name__ == "__main__":
    raise SystemExit(main())
