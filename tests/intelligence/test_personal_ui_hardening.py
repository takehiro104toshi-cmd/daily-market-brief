"""P11-A4 — privacy ／ offline の硬化（Python の層）。server の要求の敵対的な検査（Host ・Origin ・Fetch Metadata ・path の符号化 ・
method ・Content-Length ・Transfer-Encoding ・遅い body ・大きな header）・static の asset の integrity（通常の file ・symlink なし ・
committed な byte）・header の決定（CSP の font ／ media ・COEP なし ・cookie なし）・error ／ log の漏れ（typed error ・Host ・
Origin ・body の sentinel ・stdlib の handle_error）・Windows の移植性（body を読む前の拒否で header と body が別の segment で
届いても正準の応答が読め、未読の byte は有界に読み捨てられる）。browser の層は `test_personal_ui_browser_hardening.py`。"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from src.intelligence.personal_ui import local_server as ls
from src.intelligence.personal_ui.local_server import LocalServer
from src.intelligence.personal_ui.ui_model import UiReadError
from tests.intelligence.phase11_runtime_registry import P11_STATIC_ASSETS, P11_STATIC_ROUTES, PHASE11_STATIC_DIR
from tests.intelligence.test_personal_ui_server import (GOOD, NOTE, body_json, raw, request, running,  # noqa: F401
                                                        server, world)

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC = REPO_ROOT / PHASE11_STATIC_DIR
SENTINEL = "SENTINEL-A4-HOSTILE"
TRAVERSAL_PATHS = ("/app", "/app/.", "/app/./", "/./app/", "/app//", "/APP/", "/App/index.html", "/app/%2e%2e/",
                   "/app/../local_server.py", "/app/..%2flocal_server.py", "/app%2findex.html", "/app/..%5c..%5cwindows",
                   "/app/\\..\\local_server.py", "/app/index.html%00", "/app/index.html%2e", "/app/index.html;x",
                   "/app/?", "/app/?at=1", "/app/index.html?x", "/app/sw.js?v=2", "/app/app.js/", "/app/static/app.js",
                   "/app/.gitattributes", "/app/__init__.py", "/app/../../etc/passwd", "/app/%2e%2e%2f%2e%2e%2f",
                   "/app/%c3%a9", "/app/%c0%ae%c0%ae/", "/static/app.js", "/src/intelligence/personal_ui/static/app.js",
                   "http://127.0.0.1/app/", "/api/view/", "/api/", "/api/view?x=1", "/health/", "/version?x", "/%2f")


def _hdr(response, name: str) -> list:
    return [v for k, v in response["headers"] if k.lower() == name.lower()]


def _assert_canonical_error(response, status: int, code: str) -> None:
    assert response["status"] == status
    payload = body_json(response)
    assert payload == {"code": code, "detail": payload["detail"], "schema_version": ls.SERVER_SCHEMA_VERSION}
    assert set(payload["detail"]) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:")
    assert _hdr(response, "Set-Cookie") == [] and _hdr(response, "Server") == [] and _hdr(response, "Date") == []


# ================================================ Host ・Origin ・Fetch Metadata（DNS rebinding ・偽の Host ・cross-site）


def test_a_a_host_origin_and_fetch_metadata_are_exact_and_leak_nothing(server, capsys) -> None:
    port = server["port"]
    good_host = f"127.0.0.1:{port}"
    for host in (f"localhost:{port}", "127.0.0.1", f"127.0.0.1:{port}.", f"127.0.0.1:{port}:", f"0177.0.0.1:{port}",
                 f"127.1:{port}", f"[::1]:{port}", f"127.0.0.1:{(port % 65535) + 1}", f"127.0.0.1:0{port}",
                 f"evil.example:{port}", f"127.0.0.1.evil.example:{port}", f"user@127.0.0.1:{port}", f"http://127.0.0.1:{port}",
                 f"127.0.0.1:{port}/", "", f"{SENTINEL}:{port}"):                 # 前後の空白は parser が外す（値は同じ）
        for path in ("/app/", "/health", "/api/view"):
            response = request(port, "POST" if path == "/api/view" else "GET", path, GOOD if path == "/api/view" else None,
                               host=host)
            _assert_canonical_error(response, 400, "HOST_REJECTED")
            assert SENTINEL not in response["body"].decode("utf-8")
    duplicate = raw(port, (f"GET /health HTTP/1.0\r\nHost: {good_host}\r\nHost: {good_host}\r\n\r\n").encode())
    assert b" 400 " in duplicate.split(b"\r\n")[0] and b'"code":"HOST_REJECTED"' in duplicate
    forwarded = request(port, "GET", "/health", headers={"X-Forwarded-Host": "evil.example", "X-Forwarded-For": "1.2.3.4",
                                                         "Forwarded": "host=evil.example", "X-Real-IP": "1.2.3.4"})
    assert forwarded["status"] == 200                                                   # 転送の header は見ない（Host が本物）
    for origin in ("null", f"http://127.0.0.1:{port}/", f"https://127.0.0.1:{port}", f"http://localhost:{port}",
                   f"http://127.0.0.1:{(port % 65535) + 1}", "http://127.0.0.1", f"HTTP://127.0.0.1:{port}",
                   f"http://127.0.0.1:{port} ", f"http://{SENTINEL}", "file://", ""):
        response = request(port, "POST", "/api/view", GOOD, headers={"Origin": origin})
        _assert_canonical_error(response, 403, "FETCH_SITE_REJECTED")
        assert body_json(response)["detail"] == "ORIGIN" and SENTINEL not in response["body"].decode("utf-8")
    for site in ("cross-site", "same-site", "Same-Origin", "none ", SENTINEL, ""):
        response = request(port, "POST", "/api/view", GOOD, headers={"Sec-Fetch-Site": site})
        _assert_canonical_error(response, 403, "FETCH_SITE_REJECTED")
        assert body_json(response)["detail"] == "SEC_FETCH_SITE"
    for mode, dest in (("navigate", "document"), ("no-cors", "image"), ("cors", "empty"), ("websocket", "empty")):
        response = request(port, "POST", "/api/view", GOOD, headers={"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": mode,
                                                                     "Sec-Fetch-Dest": dest, "Origin": f"http://127.0.0.1:{port}"})
        assert response["status"] == 200                                               # same-origin の POST だけが通る
    form = request(port, "POST", "/api/view", b"at=1&as_of_date=2",
                   headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://127.0.0.1:{port}"})
    _assert_canonical_error(form, 415, "UNSUPPORTED_MEDIA_TYPE")                       # cross-site の form は型で落ちる
    text_plain = request(port, "POST", "/api/view", json.dumps(GOOD).encode(), headers={"Content-Type": "text/plain"})
    _assert_canonical_error(text_plain, 415, "UNSUPPORTED_MEDIA_TYPE")
    cross_get = request(port, "GET", "/api/view", headers={"Sec-Fetch-Site": "cross-site"})
    _assert_canonical_error(cross_get, 405, "METHOD_NOT_ALLOWED")                       # 画像 ・script としての読み込みは不可
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err and captured.out + captured.err == ""
    assert all(SENTINEL not in repr(e) for e in server["events"]) and NOTE not in repr(server["events"])


# ================================================ path の符号化 ・method


def test_a_b_encoded_paths_traversal_and_unsupported_methods_get_canonical_errors(server) -> None:
    port = server["port"]
    for path in TRAVERSAL_PATHS:
        response = request(port, "GET", path)
        _assert_canonical_error(response, 404, "NOT_FOUND")
        assert _hdr(response, "Content-Security-Policy") == [] and _hdr(response, "Allow") == [], path
        assert response["body"] not in {STATIC.joinpath(name).read_bytes() for name in P11_STATIC_ROUTES.values()}
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "TRACE", "CONNECT", "PROPFIND", "FOO"):
        for path in ("/app/", "/api/view", "/health", "/nowhere"):
            data = (f"{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n").encode()
            response = raw(port, data)
            head, _, body = response.partition(b"\r\n\r\n")
            assert head.split(b"\r\n")[0] == b"HTTP/1.0 405 Method Not Allowed", (method, path)
            assert b"Set-Cookie" not in head and b"Server:" not in head and b"Date:" not in head and b"<" not in body
            assert json.loads(body)["code"] == "METHOD_NOT_ALLOWED"
    get_on_view = request(port, "GET", "/api/view")
    _assert_canonical_error(get_on_view, 405, "METHOD_NOT_ALLOWED")
    assert _hdr(get_on_view, "Allow") == ["POST"]
    post_on_static = request(port, "POST", "/app/app.js", GOOD)
    _assert_canonical_error(post_on_static, 405, "METHOD_NOT_ALLOWED")
    assert _hdr(post_on_static, "Allow") == ["GET"]
    doubled = request(port, "GET", "//app/")                   # stdlib は先頭の連続する / を 1 つに畳む（同じ asset ・別の file ではない）
    assert doubled["status"] == 200 and doubled["body"] == request(port, "GET", "/app/")["body"]
    assert request(port, "GET", "//app/../local_server.py")["status"] == 404
    absolute = raw(port, (f"GET http://127.0.0.1:{port}/app/ HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n").encode())
    assert b" 404 " in absolute.split(b"\r\n")[0]                                        # absolute-form は allowlist の外
    http11 = raw(port, (f"GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: keep-alive\r\n\r\n").encode())
    assert http11.startswith(b"HTTP/1.0 200") and b"Connection: close" in http11          # keep-alive は受けない（1 要求 1 接続）


# ================================================ Content-Length ・Transfer-Encoding ・遅い body ・大きな header


def test_a_c_body_framing_edge_cases_and_slow_bodies_are_refused_safely(server, monkeypatch) -> None:
    port = server["port"]
    good = json.dumps(GOOD).encode()
    prefix = f"POST /api/view HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\n".encode()

    def framed(headers: bytes, body: bytes = good) -> dict:
        response = raw(port, prefix + headers + b"\r\n" + body)
        head, _, payload = response.partition(b"\r\n\r\n")
        return dict(status=int(head.split(b" ")[1]), json=json.loads(payload))

    for length in (b"\xd9\xa1", b"+5", b"5 ", b"0x10", b"-1", b"1e2", b"", b"5\t", b"99999999", "５".encode()):
        result = framed(b"Content-Length: " + length + b"\r\n")
        assert (result["status"], result["json"]["code"], result["json"]["detail"]) == (400, "BAD_REQUEST", "CONTENT_LENGTH"), length
    result = framed(f"Content-Length: {len(good)}\r\nContent-Length: {len(good)}\r\n".encode())
    assert (result["status"], result["json"]["detail"]) == (400, "CONTENT_LENGTH")        # 重複は 1 つでも同じ値でも拒む
    result = framed(f"Content-Length: {len(good)}\r\nContent-Length: 3\r\n".encode())
    assert (result["status"], result["json"]["detail"]) == (400, "CONTENT_LENGTH")
    result = framed(b"Transfer-Encoding: chunked\r\n", b"5\r\nhello\r\n0\r\n\r\n")
    assert (result["status"], result["json"]["detail"]) == (400, "TRANSFER_ENCODING")
    result = framed(f"Transfer-Encoding: chunked\r\nContent-Length: {len(good)}\r\n".encode())
    assert (result["status"], result["json"]["detail"]) == (400, "TRANSFER_ENCODING")      # TE と CL の両方も拒む
    result = framed(f"Content-Length: {ls.MAX_BODY_BYTES + 1}\r\n".encode(), b"x" * (ls.MAX_BODY_BYTES + 1))
    assert (result["status"], result["json"]["code"]) == (413, "PAYLOAD_TOO_LARGE")
    # 途切れた body（client が書き終えて閉じる）
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(prefix + f"Content-Length: {len(good) + 10}\r\n\r\n".encode() + good)
        sock.shutdown(socket.SHUT_WR)
        truncated = b""
        while chunk := sock.recv(65536):
            truncated += chunk
    assert b" 400 " in truncated.split(b"\r\n")[0] and b'"detail":"BODY_TRUNCATED"' in truncated
    # 遅い body（timeout の中で何も来ない）→ 安全な 400 ・接続は閉じる ・traceback は出ない
    monkeypatch.setattr(ls._Handler, "timeout", 0.5)
    started = time.monotonic()
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(prefix + f"Content-Length: {len(good)}\r\n\r\n".encode() + good[:3])
        slow = b""
        while chunk := sock.recv(65536):
            slow += chunk
    assert time.monotonic() - started < 8 and b" 400 " in slow.split(b"\r\n")[0] and b'"detail":"BODY_TIMEOUT"' in slow
    monkeypatch.setattr(ls._Handler, "timeout", 10)
    # 大きな header ・多すぎる header ・長すぎる要求行 → stdlib の解析の失敗も正準の JSON（HTML ・Server ・Date なし）
    for hostile in (b"GET /health HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nX-Big: %s\r\n\r\n" % (port, b"a" * 70000),
                    b"GET /health HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n%s\r\n" % (port, b"".join(b"X-%d: y\r\n" % i for i in range(150))),
                    b"GET /" + b"a" * 70000 + b" HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % port,
                    b"GARBAGE\r\n\r\n", b"GET\r\n\r\n", b"GET /health HTTP/9.9\r\nHost: 127.0.0.1:%d\r\n\r\n" % port):
        response = raw(port, hostile)
        if response.startswith(b"HTTP/"):
            head, _, body = response.partition(b"\r\n\r\n")
            assert head.split(b"\r\n")[0] in (b"HTTP/1.0 400 Bad Request", b"HTTP/1.0 405 Method Not Allowed"), hostile[:30]
            assert b"Server:" not in head and b"Date:" not in head
        else:
            body = response                                       # 版の無い要求行は stdlib が HTTP/0.9 の素の body で答える
        assert b"<" not in body and b"Python" not in response and b"Traceback" not in response
        assert json.loads(body)["code"] in ("BAD_REQUEST", "METHOD_NOT_ALLOWED")
        assert json.loads(body)["schema_version"] == ls.SERVER_SCHEMA_VERSION
    for odd in (b"Bad Header", b": no-name"):                      # stdlib は壊れた header の行を無視する（Host は本物 ・害なし）
        tolerated = raw(port, b"GET /health HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n%s\r\n\r\n" % (port, odd))
        assert tolerated.startswith(b"HTTP/1.0 200") and tolerated.endswith(ls.STATUS_BYTES)
    assert request(port, "POST", "/api/view", GOOD)["status"] == 200                  # server は生きている


# ================================================ static の asset の integrity


def test_b_a_static_assets_are_regular_committed_files_served_byte_exact_without_templating(server, world, monkeypatch,
                                                                                               tmp_path: Path) -> None:
    port = server["port"]
    for asset in P11_STATIC_ASSETS:
        path = REPO_ROOT / asset
        assert path.is_file() and not path.is_symlink(), asset
        assert subprocess.run(["git", "ls-files", "--stage", "--", asset], cwd=REPO_ROOT, capture_output=True,
                              encoding="utf-8", check=True).stdout.startswith("100644 "), asset   # 通常の file の mode
    committed = {}
    for route, name in P11_STATIC_ROUTES.items():
        show = subprocess.run(["git", "show", f":{PHASE11_STATIC_DIR}/{name}"], cwd=REPO_ROOT, capture_output=True, check=True)
        committed[route] = show.stdout
        response = request(port, "GET", route)
        assert response["status"] == 200 and response["body"] == show.stdout, route         # index の byte と同一（templating なし）
        assert _hdr(response, "Content-Type") == [ls.STATIC_ROUTES[route][1]]
        assert _hdr(response, "Content-Length") == [str(len(show.stdout))]
        assert _hdr(response, "Set-Cookie") == [] and _hdr(response, "Cross-Origin-Embedder-Policy") == []
    assert len({committed[r] for r in ("/app/", "/app/index.html")}) == 1
    source = Path(ls.__file__).read_text(encoding="utf-8")
    static_block = source[source.index("if route in STATIC_ROUTES:"):source.index("if method != \"POST\":")]
    assert ".format(" not in static_block and "%" not in static_block and "f\"" not in static_block   # 配る byte は加工しない
    if not hasattr(os, "symlink"):
        pytest.skip("symlink unsupported")
    linked = tmp_path / "static"
    linked.mkdir()
    for name in set(P11_STATIC_ROUTES.values()):
        (linked / name).write_bytes((STATIC / name).read_bytes())
    (linked / "app.js").unlink()
    try:
        os.symlink(STATIC / "app.js", linked / "app.js")
    except (OSError, NotImplementedError):
        pytest.skip("symlink not permitted here")
    monkeypatch.setattr(ls, "STATIC_DIR", linked)
    with pytest.raises(ls.ServerStartupError) as exc:
        LocalServer.start(world["p10"], world["p9"]["root"], port=0)
    assert exc.value.code == "STATIC_ASSET_INVALID" and str(tmp_path) not in str(exc.value)
    (linked / "app.js").unlink()
    (linked / "app.js").mkdir()                                                            # directory も通常の file ではない
    with pytest.raises(ls.ServerStartupError) as exc:
        LocalServer.start(world["p10"], world["p9"]["root"], port=0)
    assert exc.value.code == "STATIC_ASSET_INVALID"


# ================================================ header の決定 ・cookie なし


def test_b_b_security_headers_tightened_no_coep_no_cookies_anywhere(server) -> None:
    port = server["port"]
    csp = ls.CONTENT_SECURITY_POLICY
    for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "img-src 'self'", "connect-src 'self'",
                      "manifest-src 'self'", "worker-src 'self'", "base-uri 'none'", "form-action 'self'",
                      "frame-ancestors 'none'", "object-src 'none'", "font-src 'self'", "media-src 'none'"):
        assert directive in csp.split("; "), directive
    assert "unsafe" not in csp and "data:" not in csp and "blob:" not in csp and "*" not in csp
    responses = [request(port, "GET", route) for route in P11_STATIC_ROUTES]
    responses += [request(port, "GET", "/health"), request(port, "GET", "/version"), request(port, "GET", "/nowhere"),
                  request(port, "POST", "/api/view", GOOD), request(port, "POST", "/api/view", {"at": 1}),
                  request(port, "POST", "/app/", GOOD), request(port, "GET", "/health", host="evil")]
    for response in responses:
        assert _hdr(response, "Set-Cookie") == [] and _hdr(response, "Cross-Origin-Embedder-Policy") == []
        assert _hdr(response, "Access-Control-Allow-Origin") == [] and _hdr(response, "Server") == []
        assert _hdr(response, "Date") == [] and _hdr(response, "ETag") == [] and _hdr(response, "Last-Modified") == []
        assert _hdr(response, "X-Content-Type-Options") == ["nosniff"] and _hdr(response, "Referrer-Policy") == ["no-referrer"]
        assert _hdr(response, "Cross-Origin-Resource-Policy") == ["same-origin"] and _hdr(response, "Connection") == ["close"]
    for response in responses[:len(P11_STATIC_ROUTES)]:
        assert _hdr(response, "Cross-Origin-Opener-Policy") == ["same-origin"] and _hdr(response, "Cache-Control") == ["no-cache"]
    for response in responses[len(P11_STATIC_ROUTES):]:
        assert _hdr(response, "Cache-Control") == ["no-store"] and _hdr(response, "Content-Security-Policy") == []
    with_cookie = request(port, "POST", "/api/view", GOOD, headers={"Cookie": f"session={SENTINEL}"})
    assert with_cookie["status"] == 200 and SENTINEL not in with_cookie["body"].decode("utf-8")   # cookie は読まず ・返さず


# ================================================ error ／ log の漏れ


def test_c_a_typed_errors_hostile_headers_and_stdlib_error_paths_leak_nothing(server, monkeypatch, capsys) -> None:
    port = server["port"]
    texts = []

    def typed(*_args, **_kwargs):
        raise UiReadError("P9_VIEW_UNAVAILABLE", f"{SENTINEL} /private/path")

    monkeypatch.setattr(ls, "read_ui_model", typed)
    response = request(port, "POST", "/api/view", GOOD)
    assert (response["status"], body_json(response)) == (503, {"code": "VIEW_UNAVAILABLE", "detail": "P9_VIEW_UNAVAILABLE",
                                                               "schema_version": ls.SERVER_SCHEMA_VERSION})
    texts.append(response["body"].decode("utf-8"))

    def typed_hostile_code(*_args, **_kwargs):
        raise UiReadError(SENTINEL + " /private/path", "X")                                  # code 自体が汚れている場合

    monkeypatch.setattr(ls, "read_ui_model", typed_hostile_code)
    response = request(port, "POST", "/api/view", GOOD)
    assert (response["status"], body_json(response)) == (503, {"code": "VIEW_UNAVAILABLE", "detail": "",
                                                               "schema_version": ls.SERVER_SCHEMA_VERSION})
    texts.append(response["body"].decode("utf-8"))

    def typed_input(*_args, **_kwargs):
        raise UiReadError("INPUT_INVALID", SENTINEL.replace("-", "_").lower())

    monkeypatch.setattr(ls, "read_ui_model", typed_input)
    response = request(port, "POST", "/api/view", GOOD)
    assert (response["status"], body_json(response)["detail"]) == (400, "")
    texts.append(response["body"].decode("utf-8"))

    class Hostile(Exception):
        def __str__(self) -> str:
            return SENTINEL + " " + NOTE

    def hostile(*_args, **_kwargs):
        raise Hostile()

    monkeypatch.setattr(ls, "read_ui_model", hostile)
    response = request(port, "POST", "/api/view", GOOD)
    assert (response["status"], body_json(response)["code"]) == (500, "INTERNAL_ERROR")
    texts.append(response["body"].decode("utf-8"))
    hostile_body = request(port, "POST", "/api/view", {"at": SENTINEL, "as_of_date": NOTE})
    texts.append(hostile_body["body"].decode("utf-8") + repr(hostile_body["headers"]))
    hostile_headers = request(port, "POST", "/api/view", GOOD, headers={"Origin": f"http://{SENTINEL}", "X-Note": NOTE,
                                                                        "User-Agent": SENTINEL, "Referer": f"http://{NOTE}/"})
    texts.append(hostile_headers["body"].decode("utf-8") + repr(hostile_headers["headers"]))
    texts.append(request(port, "GET", f"/{SENTINEL}", host=NOTE)["body"].decode("utf-8"))
    texts.append(raw(port, f"GET /{SENTINEL} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nHost: {NOTE}\r\n\r\n".encode()).decode("utf-8"))
    # stdlib の handle_error（接続中の例外）は何も出さない
    try:
        raise RuntimeError(SENTINEL + " " + str(server["tmp"]))
    except RuntimeError:
        server["srv"]._server.handle_error(None, ("127.0.0.1", 1))
    captured = capsys.readouterr()
    texts.append(captured.out + captured.err)
    assert captured.out + captured.err == ""
    events_text = repr(server["events"])
    for text in texts + [events_text]:
        assert SENTINEL not in text and NOTE not in text and str(server["tmp"]) not in text and "Traceback" not in text
        assert "/private/path" not in text and "private" not in text.lower()
    assert all("Hostile" not in text for text in texts)                                   # class 名は sink にだけ
    assert ("POST", "/api/view", 500, "Hostile") in server["events"]
    out = io.StringIO()
    monkeypatch.setattr(ls, "read_ui_model", hostile)
    monkeypatch.setattr(ls.LocalServer, "serve_forever", lambda self: None)
    assert ls.main(["--p10-root", str(world_root := server["p10"]), "--p9-root", str(server["p9"]["root"])], stdout=out) == 0
    assert SENTINEL not in out.getvalue() and str(world_root) not in out.getvalue()


# ================================================ Windows の移植性（P11-A5）: body を読む前の拒否と分割送信


def _wait_for(condition, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)


def _split_send(port: int, head: bytes, body: bytes, pause: float = 0.2) -> bytes:
    """header と body を別の segment で送る（http.client は 2 回の send で送る。Windows ではこの形で応答が失われた）。
    応答を EOF まで読み切り、client の側では例外が起きないことを確かめる。"""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(head)
        time.sleep(pause)                                             # server はこの間に拒否を書き終える
        sock.sendall(body)                                            # 未読の byte として届く
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def test_a_d_split_send_early_refusals_keep_the_canonical_response_and_drain_the_unread_body(server, monkeypatch) -> None:
    from tests.intelligence.test_personal_intelligence_executor import tree
    port = server["port"]
    before = (tree(server["p10"]), tree(server["p9"]["root"]))
    drained: list = []
    real = ls.linger_close
    monkeypatch.setattr(ls, "linger_close", lambda connection, **kw: drained.append(real(connection, **kw)) or drained[-1])
    good = json.dumps(GOOD).encode()
    big = b"{" + b" " * 5000 + b"}"
    hostile = (NOTE + " " + SENTINEL).encode()
    origin = f"http://127.0.0.1:{port}".encode()
    cases = (
        ("415 media type", b"POST /api/view HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n"
         % (port, len(hostile)), hostile, 415, "UNSUPPORTED_MEDIA_TYPE", ""),
        ("413 oversized", b"POST /api/view HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
         % (port, len(big)), big, 413, "PAYLOAD_TOO_LARGE", ""),
        ("400 transfer-encoding", b"POST /api/view HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
         b"Transfer-Encoding: chunked\r\nContent-Length: %d\r\n\r\n" % (port, len(good)), good, 400, "BAD_REQUEST", "TRANSFER_ENCODING"),
        ("400 host", b"POST /api/view HTTP/1.0\r\nHost: evil.example:%d\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
         % (port, len(good)), good, 400, "HOST_REJECTED", ""),
        ("403 origin", b"POST /api/view HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nOrigin: http://evil.example\r\nContent-Type: application/json\r\n"
         b"Content-Length: %d\r\n\r\n" % (port, len(good)), good, 403, "FETCH_SITE_REJECTED", "ORIGIN"),
        ("403 fetch-site", b"POST /api/view HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nSec-Fetch-Site: cross-site\r\nOrigin: %s\r\n"
         b"Content-Type: application/json\r\nContent-Length: %d\r\n\r\n" % (port, origin, len(good)), good, 403,
         "FETCH_SITE_REJECTED", "SEC_FETCH_SITE"),
        ("405 method", b"POST /health HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
         % (port, len(good)), good, 405, "METHOD_NOT_ALLOWED", ""),
        ("404 path", b"POST /api/views HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
         % (port, len(good)), good, 404, "NOT_FOUND", ""),
    )
    for label, head, body, status, code, detail in cases:
        drained.clear()
        response = _split_send(port, head, body)
        header, _, payload = response.partition(b"\r\n\r\n")
        assert header.split(b"\r\n")[0] == b"HTTP/1.0 %d %s" % (status, {415: b"Unsupported Media Type", 413: b"Request Entity Too Large",
                                                                           400: b"Bad Request", 403: b"Forbidden", 405: b"Method Not Allowed",
                                                                           404: b"Not Found"}[status]), label
        assert json.loads(payload) == {"code": code, "detail": detail, "schema_version": ls.SERVER_SCHEMA_VERSION}, label
        assert b"Set-Cookie" not in header and b"Date:" not in header and b"Server:" not in header, label
        _wait_for(lambda: drained, 5)                                   # FIN は読み捨ての前に届く: server の側の完了を待つ
        assert drained == [len(body)], (label, drained)                 # 未読の body は server が読み捨てた（内容は使わない）
        assert SENTINEL not in response.decode("utf-8") and NOTE not in response.decode("utf-8")
    # 解析の失敗（長い要求行）の後も読み捨てる（stdlib が読まなかった残りの byte）
    drained.clear()
    long_line = b"GET /" + b"a" * 70000 + b" HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % port
    response = _split_send(port, long_line[:60000], long_line[60000:])
    assert response.startswith(b"HTTP/1.0 400") and b'"code":"BAD_REQUEST"' in response
    _wait_for(lambda: drained, 5)
    assert len(drained) == 1 and 0 <= drained[0] <= len(long_line)
    # 読み切った要求（200 の経路）では読み捨てを呼ばない ・応答は A1 の byte のまま
    drained.clear()
    ok = request(port, "POST", "/api/view", GOOD)
    assert ok["status"] == 200 and drained == []
    static = request(port, "GET", "/app/")
    assert static["status"] == 200 and drained == []
    assert (tree(server["p10"]), tree(server["p9"]["root"])) == before                 # 何も書かない
    assert all(SENTINEL not in repr(e) for e in server["events"])


def test_a_e_linger_close_is_bounded_in_bytes_and_time_and_sends_fin_first() -> None:
    assert (ls.DRAIN_TIMEOUT_SECONDS, ls.DRAIN_MAX_BYTES, ls.DRAIN_CHUNK_BYTES) == (0.5, 65536, 8192)
    assert ls._SHUT_WR == socket.SHUT_WR
    # 1. 送られた byte を全部読み捨て、peer は先に FIN（EOF）を見る
    a, b = socket.socketpair()
    with a, b:
        b.sendall(b"x" * 1000)
        assert ls.linger_close(a, timeout=0.5, cap=65536) == 1000
        b.settimeout(1)
        assert b.recv(10) == b""                                                       # FIN が届いている
    # 2. 上限で止まる（cap を越える byte は読まない）
    a, b = socket.socketpair()
    with a, b:
        b.setblocking(False)
        sent = 0
        payload = b"y" * 8192
        while sent < 200000:
            try:
                sent += b.send(payload)
            except BlockingIOError:
                break
        assert sent >= 16384 + 1024
        assert ls.linger_close(a, timeout=0.5, cap=16384) == 16384
    # 3. 何も来なければ timeout で止まる（有界 ・時計を使わない回数の上限）
    a, b = socket.socketpair()
    with a, b:
        started = time.monotonic()
        assert ls.linger_close(a, timeout=0.2, cap=16384) == 0
        assert time.monotonic() - started < 1.5
    # 4. 閉じた socket でも例外を出さない
    a, b = socket.socketpair()
    a.close(); b.close()
    assert ls.linger_close(a) == 0
