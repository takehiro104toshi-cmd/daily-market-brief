"""P11-A3 — static な PWA の shell の test（asset の集合 ・blob の pin ・manifest ・service worker の方針 ・JS の静的な検査 ・
経路 ・header ・cache ・決定論。browser は `test_personal_ui_browser.py`）。"""
from __future__ import annotations

import hashlib
import io
import json
import re
import socket
import struct
import subprocess
from pathlib import Path

import pytest

from src.intelligence.personal_ui import local_server as ls
from src.intelligence.personal_ui.local_server import LocalServer
from tests.intelligence.phase11_runtime_registry import (P11_SHELL_CACHE_NAME, P11_SHELL_PRECACHE, P11_STATIC_ASSETS,
                                                         P11_STATIC_BLOB_IDS, P11_STATIC_ROUTES, PHASE11_STATIC_DIR)
from tests.intelligence.test_personal_ui_server import GOOD, body_json, request, world  # noqa: F401 - fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC = REPO_ROOT / PHASE11_STATIC_DIR
FORBIDDEN_JS = ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "eval(", "Function(", "innerHTML",
                "outerHTML", "document.write", "insertAdjacentHTML", "WebSocket", "EventSource", "http://", "https://",
                "import(", "importScripts", "console.", "XMLHttpRequest", "sendBeacon", "postMessage", "window.open",
                "location.href", "history.pushState", "history.replaceState", "setTimeout(", "setInterval(")


def _read(name: str) -> str:
    return (STATIC / name).read_bytes().decode("utf-8")


def _blob(path: str) -> str:
    return subprocess.run(["git", "hash-object", "--", path], cwd=REPO_ROOT, capture_output=True, encoding="utf-8",
                          check=True).stdout.strip()


# ================================================ asset の集合 ・pin ・改行


def test_a_a_assets_are_exactly_the_registered_set_with_pinned_blob_ids_and_lf_only() -> None:
    assert {p.name for p in STATIC.iterdir()} == {Path(p).name for p in P11_STATIC_ASSETS}
    for asset in P11_STATIC_ASSETS:
        assert _blob(asset) == P11_STATIC_BLOB_IDS[asset], asset
        data = (REPO_ROOT / asset).read_bytes()
        if not asset.endswith(".png"):
            assert b"\r" not in data and data.endswith(b"\n"), asset                      # committed な byte は LF だけ
    assert _read(".gitattributes") == "* -text\n"                                        # Windows でも byte をそのまま
    seed = "\n".join(f"{route} {P11_STATIC_BLOB_IDS[f'{PHASE11_STATIC_DIR}/{P11_STATIC_ROUTES[route]}']}"
                     for route in sorted(P11_SHELL_PRECACHE))
    assert P11_SHELL_CACHE_NAME == "p11-shell-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]   # 内容から導く
    assert not any(re.search(r"\d{4}-\d{2}-\d{2}T", _read(n)) for n in ("sw.js", "manifest.webmanifest", "app.css"))


def test_a_b_icons_are_locally_generated_png_of_the_declared_sizes() -> None:
    for size in (192, 512):
        data = (STATIC / f"icon-{size}.png").read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
        assert struct.unpack(">II", data[16:24]) == (size, size)
        assert data.endswith(b"IEND\xaeB`\x82") and len(data) < 8192


# ================================================ manifest ・HTML ・JS ・service worker


def test_b_a_manifest_is_minimal_installable_and_private() -> None:
    manifest = json.loads(_read("manifest.webmanifest"))
    assert manifest["id"] == "/app/" and manifest["start_url"] == "/app/" and manifest["scope"] == "/app/"
    assert manifest["display"] == "standalone" and manifest["name"] and manifest["short_name"]
    assert set(manifest) == {"id", "name", "short_name", "start_url", "scope", "display", "background_color",
                             "theme_color", "lang", "icons"}
    assert [icon["src"] for icon in manifest["icons"]] == ["/app/icon-192.png", "/app/icon-512.png"]
    assert all(icon["src"] in P11_STATIC_ROUTES and icon["type"] == "image/png" for icon in manifest["icons"])
    assert "shortcuts" not in manifest and "screenshots" not in manifest and "related_applications" not in manifest
    assert "http" not in _read("manifest.webmanifest")


def test_b_b_html_has_no_inline_code_external_references_or_private_fields() -> None:
    html = _read("index.html")
    assert html.startswith("<!doctype html>") and 'lang="ja"' in html
    assert re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S) == [""]           # 外部の app.js だけ ・inline なし
    assert re.findall(r"<script[^>]*src=\"([^\"]+)\"", html) == ["/app/app.js"]
    assert "<style" not in html and not re.search(r"\sstyle=", html) and not re.search(r"\son[a-z]+=", html)
    assert "http://" not in html and "https://" not in html and "javascript:" not in html
    for href in re.findall(r"(?:href|src)=\"([^\"]+)\"", html):
        assert href in P11_STATIC_ROUTES, href
    assert 'rel="manifest" href="/app/manifest.webmanifest"' in html
    assert "PRIVATE" in html and "READ-ONLY" in html and "App shell available offline" in html
    for private in ("issuer", "revision_id", "p9_root_id", "author_ref", "horizon_note", "exclusion_reason", "localStorage"):
        assert private not in html, private
    assert not re.search(r"\bauthor\b", html)                                            # 著者は描かない（authority とは別）
    for element in ('id="at"', 'id="as-of-date"', 'id="load"', 'id="fill-clock"', 'id="review-rows"', 'id="offline"'):
        assert element in html, element
    assert "value=" not in html                                                          # 欄は空で始まる（時計の既定なし）


def test_b_c_app_js_fetches_only_the_same_origin_view_route_and_stores_nothing() -> None:
    js = _read("app.js")
    assert js.startswith("'use strict';")
    for token in FORBIDDEN_JS:
        assert token not in js, token
    assert js.count("fetch(") == 1 and "fetch(VIEW_ROUTE" in js and "const VIEW_ROUTE = '/api/view';" in js
    for option in ("method: 'POST'", "mode: 'same-origin'", "credentials: 'omit'", "cache: 'no-store'",
                   "redirect: 'error'", "referrerPolicy: 'no-referrer'", "'Content-Type': 'application/json'"):
        assert option in js, option
    assert "JSON.stringify({ at: at, as_of_date: asOfDate })" in js                       # body だけ ・query なし
    assert "?" not in js.split("VIEW_ROUTE")[0].split("const")[-1]
    assert "textContent" in js and "createElement" in js
    assert "navigator.serviceWorker.register('/app/sw.js', { scope: '/app/' })" in js
    assert "window.location.hostname !== '127.0.0.1'" in js                             # loopback 以外では shell を登録しない
    assert "clearModel();" in js and js.count("clearModel()") >= 4                      # 失敗の時は前の model を消す
    assert "Date()" in js and "fillFromDeviceClock" in js and "event.preventDefault()" in js
    assert "addEventListener('submit', load)" in js and "addEventListener('click', fillFromDeviceClock)" in js
    assert not re.search(r"\bsort\(", js) and "score" not in js and "rank" not in js and "priorit" not in js
    for column in ("ordinal", "source_kind", "p9_status", "p9_provenance_kind", "review_due_on", "due_class",
                   "attention", "excluded_by_profile", "surface_group", "linked_watch_ordinal"):
        assert f"'{column}'" in js, column
    for private in ("issuer", "revision_id", "p9_root_id", "horizon_note", "author_ref"):
        assert private not in js, private


def test_b_d_service_worker_is_shell_only_versioned_and_never_touches_the_api() -> None:
    sw = _read("sw.js")
    assert sw.startswith("'use strict';")
    assert f"const SHELL_CACHE = '{P11_SHELL_CACHE_NAME}';" in sw
    precache = re.search(r"const PRECACHE = \[(.*?)\];", sw, flags=re.S).group(1)
    assert tuple(re.findall(r"'([^']+)'", precache)) == P11_SHELL_PRECACHE
    assert "/app/sw.js" not in precache and all(route in P11_STATIC_ROUTES for route in P11_SHELL_PRECACHE)
    assert "const NETWORK_ONLY_PREFIXES = ['/api/', '/health', '/version'];" in sw
    assert ".put(" not in sw and "cache.add(" not in sw and sw.count("addAll(") == 1   # precache は install だけ
    assert "{ cache: 'reload', credentials: 'omit' }" in sw                              # HTTP の cache を経ない
    assert "request.method !== 'GET'" in sw and "url.origin !== self.location.origin" in sw
    assert "PRECACHE.indexOf(url.pathname) === -1" in sw                                 # shell の asset 以外は触らない
    assert "name.indexOf('p11-shell-') === 0 && name !== SHELL_CACHE" in sw           # 古い P11 の shell の cache だけ消す
    for forbidden in ("'push'", "'sync'", "'periodicsync'", "'message'", "'notificationclick'", "showNotification",
                      "importScripts", "http://", "https://", "indexedDB", "localStorage", "console.", "eval(",
                      "/api/view", "fetch(url", "fetch('"):
        assert forbidden not in sw, forbidden
    assert sw.count("addEventListener(") == 3 and all(f"addEventListener('{e}'" in sw for e in ("install", "activate",
                                                                                                 "fetch"))


# ================================================ 経路 ・header ・cache ・決定論


@pytest.fixture
def running(world):
    srv = LocalServer.start(world["p10"], world["p9"]["root"], port=0)
    srv.start_in_thread()
    yield dict(srv=srv, port=srv.port, **world)
    srv.shutdown()


def test_c_a_static_routes_serve_committed_bytes_with_strict_headers_and_no_listing(running) -> None:
    port = running["port"]
    for route, name in P11_STATIC_ROUTES.items():
        response = request(port, "GET", route)
        assert response["status"] == 200, route
        assert response["body"] == (STATIC / name).read_bytes(), route                   # committed な byte のまま
        assert hashlib.sha1(b"blob %d\0" % len(response["body"]) + response["body"]).hexdigest() == \
            P11_STATIC_BLOB_IDS[f"{PHASE11_STATIC_DIR}/{name}"], route                    # git の object として一致
        headers = dict(response["headers"])
        assert headers["Content-Type"] == ls.STATIC_ROUTES[route][1]
        assert headers["Cache-Control"] == "no-cache" and headers["Content-Length"] == str(len(response["body"]))
        assert headers["Content-Security-Policy"] == ls.CONTENT_SECURITY_POLICY
        assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert headers["X-Content-Type-Options"] == "nosniff" and headers["Referrer-Policy"] == "no-referrer"
        assert headers["Cross-Origin-Resource-Policy"] == "same-origin" and headers["Connection"] == "close"
        assert {k.lower() for k, _ in response["headers"]} == {"content-type", "content-length", "cache-control", "pragma",
                                                               "x-content-type-options", "referrer-policy",
                                                               "cross-origin-resource-policy", "content-security-policy",
                                                               "cross-origin-opener-policy", "connection"}
        assert request(port, "GET", route) == response                                   # 応答の全体が決定論
        refused = request(port, "POST", route, GOOD)
        assert (refused["status"], body_json(refused)["code"]) == (405, "METHOD_NOT_ALLOWED")
        assert dict(refused["headers"])["Allow"] == "GET"
    csp = ls.CONTENT_SECURITY_POLICY
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "http" not in csp
    for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "connect-src 'self'",
                      "worker-src 'self'", "manifest-src 'self'", "base-uri 'none'", "frame-ancestors 'none'",
                      "object-src 'none'", "form-action 'self'"):
        assert directive in csp, directive
    for path in ("/app", "/app/", "/app/index.html?x=1", "/app/../local_server.py", "/app/static/app.js",
                 "/app/.gitattributes", "/app/__init__.py", "/static/app.js", "/app//index.html", "/APP/", "/app/sw.js/"):
        if path == "/app/":
            continue
        response = request(port, "GET", path)
        assert (response["status"], body_json(response)["code"]) == (404, "NOT_FOUND"), path
    rejected = request(port, "GET", "/app/", host=f"localhost:{port}")                 # Host の規則は static にも
    assert (rejected["status"], body_json(rejected)["code"]) == (400, "HOST_REJECTED")
    api = request(port, "POST", "/api/view", GOOD)                                       # API の header は A2 のまま
    assert {k.lower() for k, _ in api["headers"]} == {"cache-control", "pragma", "x-content-type-options",
                                                      "referrer-policy", "cross-origin-resource-policy", "content-type",
                                                      "content-length", "connection"}
    assert dict(api["headers"])["Cache-Control"] == "no-store"
    assert "Content-Security-Policy" not in dict(api["headers"]) and "Set-Cookie" not in dict(api["headers"])


def test_c_b_startup_loads_assets_once_and_refuses_when_one_is_missing(world, monkeypatch, tmp_path: Path) -> None:
    srv = LocalServer.start(world["p10"], world["p9"]["root"], port=0)
    try:
        assert set(srv._server.context.static_assets) == set(P11_STATIC_ROUTES)
        assert srv.app_url == f"http://127.0.0.1:{srv.port}/app/"
        assert str(ls.STATIC_DIR) not in repr(srv._server.context)                       # package の path は出ない
    finally:
        srv.shutdown()
    monkeypatch.setattr(ls, "STATIC_DIR", tmp_path / "nowhere")
    with pytest.raises(ls.ServerStartupError) as exc:
        LocalServer.start(world["p10"], world["p9"]["root"], port=0)
    assert exc.value.code == "STATIC_ASSET_MISSING" and str(tmp_path) not in str(exc.value)
    out = io.StringIO()
    monkeypatch.setattr(ls, "STATIC_DIR", STATIC)
    assert ls.main(["--p10-root", str(world["p10"]), "--p9-root", str(world["p9"]["root"]), "--bind", "0.0.0.0"],
                   stdout=out) == 2
    assert socket.gethostbyname("localhost") in ("127.0.0.1",)                            # test の環境の確認だけ
