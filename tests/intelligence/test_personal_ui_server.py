"""P11-A2 — loopback の local server の test（合成の P9 ／ P10 の root ・loopback の client だけ ・outbound は罠）。"""
from __future__ import annotations

import http.client
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.personal_intelligence.attention_model import AttentionState, AttentionTargetKind
from src.intelligence.personal_intelligence.authority_stores import PersonalAuthorityStores
from src.intelligence.personal_intelligence.decisions import AttentionCreate, ProfileCreate
from src.intelligence.personal_intelligence.executor import apply_decision
from src.intelligence.personal_ui import local_server as ls
from src.intelligence.personal_ui.local_server import LocalServer, ServerStartupError
from src.intelligence.personal_ui.p10_read_adapter import read_ui_model
from src.intelligence.personal_ui.ui_model import ui_model_json_bytes
from tests.intelligence.test_personal_intelligence_executor import build_p9, tree
from tests.intelligence.test_watchlist_thesis_semantics import HOUR, ISSUER2, T0

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHOR = "human:sentinel-author"
NOTE = "SENTINEL-HORIZON-NOTE"
REASON = "SENTINEL-EXCLUSION-REASON"
CREDENTIAL = "SENTINEL-CREDENTIAL-VALUE"
AT = (T0 + 6 * HOUR).isoformat()
AS_OF = "2026-09-25"
GOOD = {"at": AT, "as_of_date": AS_OF}
LOOPBACK = ("127.0.0.1", "localhost")
_OUTBOUND: list = []


def _guard_connection(address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else address
    if host not in LOOPBACK:
        _OUTBOUND.append(host)
        raise AssertionError("TRAPPED: outbound")
    return _REAL_CREATE_CONNECTION(address, *args, **kwargs)


_REAL_CREATE_CONNECTION = socket.create_connection


def _trap(*_args, **_kwargs):
    _OUTBOUND.append("trap")
    raise AssertionError("TRAPPED: outbound / jquants")


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    p9 = build_p9(tmp_path / "p9_private_root")
    p10 = tmp_path / "p10_private_root"
    p10.mkdir()
    PersonalAuthorityStores.initialize(p10)
    at = T0 + 4 * HOUR
    apply_decision(ProfileCreate(author_ref=AUTHOR, reviewed_at=at, horizon_note=NOTE, liquidity_note="",
                                 risk_context_note="", review_lookahead_days=14, excluded_issuer_ids=(ISSUER2,),
                                 exclusion_reason_note=REASON), p10_root=p10)
    apply_decision(AttentionCreate(target_kind=AttentionTargetKind.P9_WATCH_ENTRY, target_root_id=p9["w1"].watch_entry_id,
                                   observed_p9_revision_id=p9["w1b"].revision_id, state=AttentionState.FOCUS,
                                   author_ref=AUTHOR, reviewed_at=at), p10_root=p10, p9_root=p9["root"])
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", _guard_connection)              # loopback だけ
    monkeypatch.setattr("urllib.request.urlopen", _trap)
    for module_name, module in list(sys.modules.items()):
        if module is not None and "jquants" in module_name:
            for attr, value in list(vars(module).items()):
                if isinstance(value, type) and value.__module__ == module_name and ("Client" in attr
                                                                                   or "Transport" in attr):
                    monkeypatch.setattr(value, "__init__", _trap)
    _OUTBOUND.clear()
    sentinels = {NOTE, REASON, AUTHOR, CREDENTIAL, ISSUER2, str(tmp_path), "SENTINEL", p9["w1"].watch_entry_id,
                 p9["w1b"].revision_id, p9["t1"].thesis_id, "Traceback", "p9wat_", "p10prf_", "p10att_", "human:"}
    return dict(p9=p9, p10=p10, tmp=tmp_path, sentinels=sentinels)


@pytest.fixture
def running(world):
    """走っている server（outbound 0 だけを確かめる。root の不変は `server` が足す）。"""
    events: list = []
    srv = LocalServer.start(world["p10"], world["p9"]["root"], port=0, on_event=lambda *e: events.append(e))
    srv.start_in_thread()
    yield dict(srv=srv, port=srv.port, events=events, **world)
    srv.shutdown()
    assert _OUTBOUND == []                                                             # outbound は 0


@pytest.fixture
def server(running):
    before = (tree(running["p9"]["root"]), tree(running["p10"]))
    yield running
    assert (tree(running["p9"]["root"]), tree(running["p10"])) == before             # root は byte も mtime も不変


def request(port: int, method: str, path: str, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = {"Host": host if host is not None else f"127.0.0.1:{port}"}
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        hdrs.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
    else:
        data = None
    hdrs.update(headers or {})
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for k, v in hdrs.items():
        conn.putheader(k, v)
    conn.endheaders(data)
    resp = conn.getresponse()
    out = dict(status=resp.status, headers=sorted(resp.getheaders()), body=resp.read())
    conn.close()
    return out


def raw(port: int, data: bytes) -> bytes:
    with _REAL_CREATE_CONNECTION(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(data)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def body_json(response) -> dict:
    return json.loads(response["body"].decode("utf-8"))


# ================================================ 起動


def test_a_a_startup_refuses_non_loopback_bind_bad_ports_missing_roots_and_credentials(world, monkeypatch) -> None:
    def refused(code: str, **kwargs) -> None:
        args = dict(p10_root=world["p10"], p9_root=world["p9"]["root"])
        args.update(kwargs)
        with pytest.raises(ServerStartupError) as exc:
            LocalServer.start(args["p10_root"], args["p9_root"], bind=args.get("bind", "127.0.0.1"),
                              port=args.get("port", 0))
        assert exc.value.code == code

    for bind in ("0.0.0.0", "192.168.1.5", "10.0.0.1", "localhost", "::1", "127.0.0.2", "example.com"):
        refused("BIND_NOT_LOOPBACK", bind=bind)
    refused("BIND_REQUIRED", bind="")
    refused("BIND_REQUIRED", bind=None)
    for port in (-1, 65536, "80", 80.0, True):
        refused("PORT_INVALID", port=port)
    refused("P10_ROOT_REQUIRED", p10_root="")
    refused("P9_ROOT_REQUIRED", p9_root=None)
    monkeypatch.setenv("JQUANTS_API_KEY", CREDENTIAL)
    with pytest.raises(ServerStartupError) as exc:
        LocalServer.start(world["p10"], world["p9"]["root"], port=0)
    assert exc.value.code == "CREDENTIAL_PRESENT" and CREDENTIAL not in str(exc.value)
    monkeypatch.setenv("JQUANTS_API_KEY", "")                                          # 空は無いと同じ
    srv = LocalServer.start(world["p10"], world["p9"]["root"], port=0)
    try:
        assert srv.url == f"http://127.0.0.1:{srv.port}/" and 1024 <= srv.port <= 65535
        for text in (repr(srv), repr(srv._server.context), str(srv._server.context)):
            assert str(world["tmp"]) not in text                                       # root は repr に出ない
        assert "roots=<private>" in repr(srv._server.context)
    finally:
        srv.shutdown()
    busy = LocalServer.start(world["p10"], world["p9"]["root"], port=0)
    try:
        refused("BIND_FAILED", port=busy.port)                                         # 使用中の port は失敗（握らない）
    finally:
        busy.shutdown()


# ================================================ 経路 ・header ・決定論


def test_b_a_health_version_root_are_fixed_and_touch_no_stores(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    absent = tmp_path / "absent"
    srv = LocalServer.start(absent / "p10", absent / "p9", port=0)                   # root が無くても起動 ・health は動く
    srv.start_in_thread()
    try:
        health = request(srv.port, "GET", "/health")
        assert (health["status"], health["body"]) == (200, ls.STATUS_BYTES)
        assert body_json(health) == {"schema_version": ls.SERVER_SCHEMA_VERSION, "status": "ok"}
        assert request(srv.port, "GET", "/")["body"] == ls.STATUS_BYTES
        version = body_json(request(srv.port, "GET", "/version"))
        assert set(version) == {"adapter_rules_version", "schema_version", "ui_error_schema_version",
                                "ui_model_schema_version"}
        names = {k.lower() for k, _ in health["headers"]}
        assert {"cache-control", "pragma", "x-content-type-options", "referrer-policy", "cross-origin-resource-policy",
                "content-type", "content-length", "connection"} == names                 # Date ・Server ・CORS は無い
        headers = dict(health["headers"])
        assert headers["Cache-Control"] == "no-store" and headers["Content-Type"] == "application/json; charset=utf-8"
        assert not any(k.lower().startswith("access-control") for k, _ in health["headers"])
        view = request(srv.port, "POST", "/api/view", GOOD)
        assert view["status"] == 503 and body_json(view)["code"] == "VIEW_UNAVAILABLE"
        assert body_json(view)["detail"] == "P10_UNAVAILABLE:STORE_MISSING:P10_ROOT_MISSING"
        assert not absent.exists()                                                     # 作らない
    finally:
        srv.shutdown()


def test_b_b_view_passes_through_a1_canonical_bytes_and_the_whole_response_is_deterministic(server) -> None:
    port = server["port"]
    expected = ui_model_json_bytes(read_ui_model(server["p10"], server["p9"]["root"], at=datetime.fromisoformat(AT),
                                                 as_of_date=date.fromisoformat(AS_OF)))
    responses = [request(port, "POST", "/api/view", GOOD) for _ in range(3)]
    assert all(r["status"] == 200 for r in responses)
    assert responses[0]["body"] == expected                                            # A1 の byte をそのまま
    assert responses[0] == responses[1] == responses[2]                                # status ・header ・body の全体
    payload = body_json(responses[0])
    assert payload["as_of_date"] == AS_OF and len(payload["entries"]) == 3 and payload["active_profile_present"]
    assert dict(responses[0]["headers"])["Content-Length"] == str(len(expected))
    assert not any(k.lower() in ("date", "server", "etag", "last-modified", "set-cookie") for k, _ in responses[0]["headers"])
    utc_at = datetime.fromisoformat(AT).astimezone(timezone.utc).isoformat()           # 同じ瞬間を UTC で
    assert utc_at != AT and request(port, "POST", "/api/view", {"at": utc_at, "as_of_date": AS_OF})["body"] == expected
    other = request(port, "POST", "/api/view", {"at": AT, "as_of_date": "2026-10-25"})["body"]
    assert other != expected and json.loads(other)["as_of_date"] == "2026-10-25"
    assert all(e[1] == "/api/view" and e[2] == 200 and e[3] == "OK" for e in server["events"] if e[0] == "POST")
    assert all(len(e) == 4 and isinstance(e[2], int) for e in server["events"])
    for text in map(repr, server["events"]):
        assert AT not in text and AS_OF not in text and "SENTINEL" not in text         # event は安全な事柄だけ


def test_b_c_every_view_rereads_authority_without_a_cache(running) -> None:
    server = running                                                                   # この test は authority を足す
    port = server["port"]
    first = body_json(request(port, "POST", "/api/view", GOOD))
    assert first["personal_counts"]["live_mute_mark_count"] == 0
    apply_decision(AttentionCreate(target_kind=AttentionTargetKind.P9_THESIS, target_root_id=server["p9"]["t1"].thesis_id,
                                   observed_p9_revision_id=server["p9"]["t1"].revision_id, state=AttentionState.MUTE,
                                   author_ref=AUTHOR, reviewed_at=T0 + 5 * HOUR), p10_root=server["p10"],
                   p9_root=server["p9"]["root"])
    second = body_json(request(port, "POST", "/api/view", GOOD))
    assert second["personal_counts"]["live_mute_mark_count"] == 1                      # 次の応答は新しい authority を映す
    assert [e["attention"] for e in second["entries"]].count("MUTE") == 1


# ================================================ 要求の検査 ・Host ・Fetch Metadata


def test_c_a_request_validation_is_strict_and_writes_nothing(server) -> None:
    port = server["port"]

    def refused(status: int, code: str, detail: str, body=None, headers=None, method="POST", path="/api/view") -> None:
        response = request(port, method, path, body, headers)
        payload = body_json(response)
        assert (response["status"], payload["code"], payload["detail"]) == (status, code, detail), payload
        assert payload["schema_version"] == ls.SERVER_SCHEMA_VERSION and set(payload) == {"code", "detail",
                                                                                           "schema_version"}

    refused(415, "UNSUPPORTED_MEDIA_TYPE", "", b'{"at":"x"}', {"Content-Type": "text/plain"})
    refused(415, "UNSUPPORTED_MEDIA_TYPE", "", b'{"at":"x"}', {"Content-Type": "application/x-www-form-urlencoded"})
    refused(400, "BAD_REQUEST", "EMPTY_BODY", b"", None)
    refused(400, "BAD_REQUEST", "CONTENT_LENGTH", None, {"Content-Type": "application/json"})
    refused(413, "PAYLOAD_TOO_LARGE", "", b"{" + b" " * 5000 + b"}")
    refused(400, "BAD_REQUEST", "TRANSFER_ENCODING", b"{}", {"Transfer-Encoding": "chunked"})
    refused(400, "BAD_REQUEST", "MALFORMED_JSON", b"{not json")
    refused(400, "BAD_REQUEST", "MALFORMED_JSON", b'{"at": NaN, "as_of_date": "x"}')
    refused(400, "BAD_REQUEST", "BODY_NOT_UTF8", b"\xff\xfe{}")
    refused(400, "BAD_REQUEST", "NOT_OBJECT", b'["x"]')
    refused(400, "BAD_REQUEST", "DUPLICATE_KEY", f'{{"at":"{AT}","at":"{AT}","as_of_date":"{AS_OF}"}}'.encode())
    refused(400, "BAD_REQUEST", "UNKNOWN_KEYS", {**GOOD, "issuer_id": ISSUER2})
    refused(400, "BAD_REQUEST", "UNKNOWN_KEYS", {**GOOD, "p10_root": "x"})
    refused(400, "BAD_REQUEST", "MISSING_KEYS", {"at": AT})
    refused(400, "BAD_REQUEST", "VALUE_NOT_STRING:AT", {"at": 1, "as_of_date": AS_OF})
    refused(400, "BAD_REQUEST", "VALUE_NOT_STRING:AS_OF_DATE", {"at": AT, "as_of_date": None})
    refused(400, "BAD_REQUEST", "VALUE_TOO_LONG:AT", {"at": "x" * 41, "as_of_date": AS_OF})
    refused(400, "VIEW_INPUT_INVALID", "AT_FORMAT", {"at": "2026-07-01T15:00:00", "as_of_date": AS_OF})   # naive
    refused(400, "VIEW_INPUT_INVALID", "AT_FORMAT", {"at": "2026-07-01T15:00:00Z", "as_of_date": AS_OF})
    refused(400, "VIEW_INPUT_INVALID", "AT_FORMAT", {"at": AT + "\n", "as_of_date": AS_OF})
    refused(400, "VIEW_INPUT_INVALID", "AT_FORMAT", {"at": "now", "as_of_date": AS_OF})
    refused(400, "VIEW_INPUT_INVALID", "AS_OF_DATE_FORMAT", {"at": AT, "as_of_date": AT})
    refused(400, "VIEW_INPUT_INVALID", "AT_INVALID", {"at": "2026-13-01T15:00:00+09:00", "as_of_date": AS_OF})
    refused(400, "VIEW_INPUT_INVALID", "AS_OF_DATE_INVALID", {"at": AT, "as_of_date": "2026-02-30"})
    refused(405, "METHOD_NOT_ALLOWED", "", None, None, method="GET")
    assert "Allow" in dict(request(port, "GET", "/api/view")["headers"])
    refused(405, "METHOD_NOT_ALLOWED", "", GOOD, None, method="POST", path="/health")
    refused(405, "METHOD_NOT_ALLOWED", "", None, None, method="PUT")
    refused(405, "METHOD_NOT_ALLOWED", "", None, None, method="DELETE", path="/health")
    refused(404, "NOT_FOUND", "", None, None, method="GET", path="/api/view?at=x")        # query は使わない
    for path in ("/api", "/api/views", "/static/app.js", "/..", "/health/", "/debug", "/p10_private_root"):
        refused(404, "NOT_FOUND", "", None, None, method="GET", path=path)
    long_line = raw(port, b"GET /" + b"a" * 70000 + b" HTTP/1.0\r\nHost: 127.0.0.1:" + str(port).encode() + b"\r\n\r\n")
    assert long_line.startswith(b"HTTP/1.0 400") and b"<html" not in long_line.lower() and b"Date:" not in long_line
    assert b'"code":"BAD_REQUEST"' in long_line
    unknown_method = raw(port, b"BREW /health HTTP/1.0\r\nHost: 127.0.0.1:" + str(port).encode() + b"\r\n\r\n")
    assert unknown_method.startswith(b"HTTP/1.0 405") and b'"code":"METHOD_NOT_ALLOWED"' in unknown_method


def test_c_b_host_must_match_the_bound_loopback_authority_exactly(server) -> None:
    port = server["port"]
    for host in (f"localhost:{port}", "127.0.0.1", f"127.0.0.1:{port + 1}", f"evil.example:{port}", f"[::1]:{port}",
                 "", f"0.0.0.0:{port}", f"127.0.0.1:{port}x"):
        response = request(port, "POST", "/api/view", GOOD, host=host)
        assert (response["status"], body_json(response)["code"]) == (400, "HOST_REJECTED"), host
        assert request(port, "GET", "/health", host=host)["status"] == 400
    forwarded = request(port, "POST", "/api/view", GOOD, {"X-Forwarded-Host": "evil.example", "Forwarded": "host=evil"})
    assert forwarded["status"] == 200                                                   # 転送の header は見ない
    spoof = request(port, "POST", "/api/view", GOOD, {"X-Forwarded-Host": f"127.0.0.1:{port}"},
                    host=f"evil.example:{port}")
    assert spoof["status"] == 400
    no_host = raw(port, b"GET /health HTTP/1.0\r\n\r\n")
    assert no_host.startswith(b"HTTP/1.0 400") and b'"code":"HOST_REJECTED"' in no_host
    for text in map(repr, server["events"]):
        assert "evil" not in text and "localhost" not in text                           # Host の値は event に出ない


def test_c_c_fetch_metadata_and_origin_policy_apply_to_the_api(server) -> None:
    port = server["port"]
    own = f"http://127.0.0.1:{port}"
    for headers in ({"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {"Origin": own},
                    {"Sec-Fetch-Site": "same-origin", "Origin": own}, {}):
        assert request(port, "POST", "/api/view", GOOD, headers)["status"] == 200, headers
    for headers, detail in (({"Sec-Fetch-Site": "cross-site"}, "SEC_FETCH_SITE"), ({"Sec-Fetch-Site": "same-site"},
                                                                                     "SEC_FETCH_SITE"),
                            ({"Sec-Fetch-Site": "weird"}, "SEC_FETCH_SITE"), ({"Origin": "http://localhost:" + str(port)},
                                                                               "ORIGIN"),
                            ({"Origin": "https://evil.example"}, "ORIGIN"), ({"Origin": "null"}, "ORIGIN"),
                            ({"Sec-Fetch-Site": "same-origin", "Origin": "https://evil.example"}, "ORIGIN")):
        response = request(port, "POST", "/api/view", GOOD, headers)
        assert (response["status"], body_json(response)["code"], body_json(response)["detail"]) == (
            403, "FETCH_SITE_REJECTED", detail), headers
    assert request(port, "GET", "/health", headers={"Sec-Fetch-Site": "cross-site"})["status"] == 200   # /api/* だけ


# ================================================ 安全な誤り ・並行 ・CLI


def test_d_a_errors_and_events_leak_nothing_private_including_internal_errors(server, monkeypatch, capsys) -> None:
    port = server["port"]
    texts = []
    for method, path, body, headers in (("POST", "/api/view", {**GOOD, "note": NOTE}, None),
                                        ("GET", "/nowhere", None, None),
                                        ("POST", "/api/view", {"at": "2026-07-01T00:00:00+09:00", "as_of_date": AS_OF},
                                         None)):
        response = request(port, method, path, body, headers)
        texts.append(response["body"].decode("utf-8") + repr(response["headers"]))

    def boom(*_args, **_kwargs):
        raise RuntimeError("SENTINEL-INTERNAL " + str(server["tmp"]))

    monkeypatch.setattr(ls, "read_ui_model", boom)
    internal = request(port, "POST", "/api/view", GOOD)
    assert (internal["status"], body_json(internal)) == (500, {"code": "INTERNAL_ERROR", "detail": "",
                                                               "schema_version": ls.SERVER_SCHEMA_VERSION})
    texts.append(internal["body"].decode("utf-8"))
    deadline = time.monotonic() + 5                                                     # sink は body の後に呼ばれる（短い待ち）
    while server["events"][-1][2] != 500 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server["events"][-1] == ("POST", "/api/view", 500, "RuntimeError")          # class 名だけ
    texts.append(repr(server["events"]))
    captured = capsys.readouterr()
    texts.append(captured.out + captured.err)
    assert captured.err == "" and captured.out == ""                                   # 既定の log は無い
    for text in texts:
        for sentinel in server["sentinels"]:
            assert sentinel not in text, sentinel


def test_d_b_concurrent_reads_are_identical_and_leave_roots_untouched(server) -> None:
    port = server["port"]
    expected = request(port, "POST", "/api/view", GOOD)
    results: list = []
    errors: list = []

    def worker() -> None:
        try:
            for _ in range(5):
                results.append(request(port, "POST", "/api/view", GOOD))
        except Exception as exc:  # noqa: BLE001 - test は失敗を集める
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == [] and len(results) == 40
    assert all(r == expected for r in results)
    assert sum(1 for e in server["events"] if e[2] == 200 and e[1] == "/api/view") >= 41
    assert not any(p.name.endswith((".lock", ".tmp")) for root in (server["p9"]["root"], server["p10"])
                   for p in root.rglob("*"))


def test_d_c_module_entry_prints_only_the_url_and_refuses_with_a_credential(world) -> None:
    env = {k: v for k, v in os.environ.items() if k != "JQUANTS_API_KEY"}
    proc = subprocess.Popen([sys.executable, "-m", "src.intelligence.personal_ui.local_server", "--p10-root",
                             str(world["p10"]), "--p9-root", str(world["p9"]["root"]), "--port", "0"],
                            cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline()
        payload = json.loads(line)
        assert payload == {"app_url": payload["url"] + "app/", "schema_version": ls.SERVER_SCHEMA_VERSION,
                           "status": "listening", "url": payload["url"]}
        assert payload["url"].startswith("http://127.0.0.1:") and str(world["tmp"]) not in line
        port = int(payload["url"].rsplit(":", 1)[1].rstrip("/"))
        deadline = time.time() + 10
        while True:
            try:
                assert request(port, "GET", "/health")["status"] == 200
                break
            except OSError:
                assert time.time() < deadline
                time.sleep(0.1)
        assert request(port, "POST", "/api/view", GOOD)["status"] == 200
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    assert proc.stderr.read() == ""
    env["JQUANTS_API_KEY"] = CREDENTIAL
    refused = subprocess.run([sys.executable, "-m", "src.intelligence.personal_ui.local_server", "--p10-root",
                              str(world["p10"]), "--p9-root", str(world["p9"]["root"])], cwd=REPO_ROOT, env=env,
                             capture_output=True, text=True, check=False)
    assert refused.returncode == 2 and json.loads(refused.stdout) == {"code": "CREDENTIAL_PRESENT",
                                                                       "schema_version": ls.SERVER_SCHEMA_VERSION,
                                                                       "status": "refused"}
    assert CREDENTIAL not in refused.stdout + refused.stderr and str(world["tmp"]) not in refused.stdout
    out = io.StringIO()
    assert ls.main(["--p10-root", str(world["p10"]), "--p9-root", str(world["p9"]["root"]), "--bind", "0.0.0.0"],
                   stdout=out) == 2
    assert json.loads(out.getvalue())["code"] == "BIND_NOT_LOOPBACK"
