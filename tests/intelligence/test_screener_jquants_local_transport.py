"""P8-LIVE2 — 本人の環境でだけ使う実 HTTPS transport の test（合成の HTTP 境界だけ。実 network ・実 credential は使わない）。

`http.client.HTTPSConnection` の位置に fake を差し、request ・header ・回数 ・redirect ・本文の上限 ・error の赦免を確かめる。
credential は合成の値を環境変数に置く（本 repo の cloud の credential は読まない ・表示しない）。凍結 LIVE1 ・ID1 ・ID2 ・ADP0 ・EXE は変えない。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.intelligence import jquants_local_transport as lt
from src.intelligence.jquants_local_transport import LocalHttpsTransport
from src.intelligence.screener_intelligence.jquants_live_client import JQuantsLiveClient
from src.intelligence.screener_intelligence.jquants_live_model import (BudgetExhausted, LiveInputError, RequestBudget,
                                                                       Transport, TransportResponse)
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "src" / "intelligence" / "jquants_local_transport.py"
SECRET = "synthetic-key-9f8e7d6c-not-real"                                      # 合成。本物の key ではない
ENV = "JQUANTS_API_KEY"
MASTER = "/v2/equities/master"
FINS = "/v2/fins/summary"


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers=None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, amount=None) -> bytes:
        return self._body if amount is None else self._body[:amount]


class FakeConnection:
    """`http.client.HTTPSConnection` の位置に差す fake。開いた host ・request ・header ・回数を記録する。"""

    log: list = []
    script: list = []

    def __init__(self, host, port, timeout=None, context=None) -> None:
        FakeConnection.log.append(("open", host, port, timeout, context is not None))

    def request(self, method, url, headers=None) -> None:
        FakeConnection.log.append(("request", method, url, dict(headers or {})))

    def getresponse(self):
        action = FakeConnection.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    def close(self) -> None:
        FakeConnection.log.append(("close",))


@pytest.fixture
def fake(monkeypatch):
    FakeConnection.log = []
    FakeConnection.script = []
    monkeypatch.setattr(lt, "_HTTPSConnection", FakeConnection)
    monkeypatch.setenv(ENV, SECRET)
    return FakeConnection


def ok(payload: dict) -> FakeResponse:
    return FakeResponse(200, json.dumps(payload).encode("utf-8"))


def requests_made(fake) -> list:
    return [entry for entry in fake.log if entry[0] == "request"]


# ================================================================ sanctioned requests


def test_master_request_is_sanctioned_https_get_with_auth_header(fake) -> None:
    fake.script.append(ok({"data": []}))
    transport = LocalHttpsTransport()
    response = transport.get(MASTER, {"date": "2026-06-30"})
    assert isinstance(response, TransportResponse) and response.status == 200
    assert json.loads(response.body) == {"data": []}
    opened = [e for e in fake.log if e[0] == "open"]
    assert opened == [("open", "api.jquants.com", 443, 20.0, True)]       # 固定の host ・HTTPS ・timeout ・TLS context
    (_, method, url, headers), = requests_made(fake)
    assert method == "GET" and url == "/v2/equities/master?date=2026-06-30"
    assert headers["x-api-key"] == SECRET and set(headers) == {"x-api-key", "Accept"}
    assert fake.log[-1] == ("close",) and transport.attempts == 1


def test_fins_request_is_sanctioned_and_pagination_key_is_passed_only_when_given(fake) -> None:
    fake.script.extend([ok({"data": [], "pagination_key": "p2"}), ok({"data": []})])
    transport = LocalHttpsTransport()
    transport.get(FINS, {"code": "13010"})
    transport.get(FINS, {"code": "13010", "pagination_key": "p2"})
    urls = [e[2] for e in requests_made(fake)]
    assert urls == ["/v2/fins/summary?code=13010", "/v2/fins/summary?code=13010&pagination_key=p2"]
    assert transport.attempts == 2


def test_isinstance_of_frozen_live1_transport_and_client_integration(fake) -> None:
    fake.script.append(ok({"data": []}))
    transport = LocalHttpsTransport()
    assert isinstance(transport, Transport)
    budget = RequestBudget(2)
    client = JQuantsLiveClient(transport, budget)
    fetch = client.fetch_master("2026-06-30")
    assert fetch.results == () and budget.used == 1 and transport.attempts == 1


# ================================================================ credential


def test_secret_is_absent_from_public_representations_and_errors(fake) -> None:
    fake.script.append(FakeResponse(500, b'{"message": "server says ' + SECRET.encode() + b'"}'))
    transport = LocalHttpsTransport()
    assert SECRET not in repr(transport) and SECRET not in str(transport)
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert SECRET not in str(info.value) and SECRET not in info.value.code and SECRET not in info.value.detail
    assert "server says" not in str(info.value)
    assert not any(SECRET in str(v) for v in vars(transport).values())                    # object に保持しない
    assert "credential" not in {k.lower() for k in vars(transport)} or "_credential_env" in vars(transport)
    assert all(not k.endswith("key") and "secret" not in k for k in vars(transport))


def test_missing_or_empty_credential_fails_before_any_network_call(fake, monkeypatch) -> None:
    transport = LocalHttpsTransport()
    monkeypatch.delenv(ENV, raising=False)
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert info.value.code == "CREDENTIAL_MISSING" and fake.log == [] and transport.attempts == 0
    monkeypatch.setenv(ENV, "   ")
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert info.value.code == "CREDENTIAL_MISSING" and fake.log == []
    monkeypatch.setenv("OTHER_KEY_NAME", SECRET)                                              # 他の変数は読まない
    with pytest.raises(LiveInputError):
        transport.get(MASTER, {"date": "2026-06-30"})
    assert fake.log == []
    with pytest.raises(LiveInputError):
        LocalHttpsTransport(credential_env="lower-case")
    with pytest.raises(LiveInputError):
        LocalHttpsTransport(credential_env="1KEY")
    named = LocalHttpsTransport(credential_env="OTHER_KEY_NAME")                            # caller が名を選ぶ
    fake.script.append(ok({"data": []}))
    named.get(MASTER, {"date": "2026-06-30"})
    assert requests_made(fake)[0][3]["x-api-key"] == SECRET


def test_credential_can_never_travel_in_the_query(fake) -> None:
    transport = LocalHttpsTransport()
    for params in ({"x-api-key": SECRET}, {"apikey": SECRET}, {"token": SECRET}, {"Authorization": "Bearer " + SECRET},
                   {"date": "2026-06-30", "api_key": SECRET}):
        with pytest.raises(LiveInputError) as info:
            transport.get(MASTER, params)
        assert info.value.code == "CREDENTIAL_IN_QUERY" and SECRET not in str(info.value)
    assert fake.log == [] and transport.attempts == 0


# ================================================================ host / path lock


def test_absolute_urls_other_hosts_unknown_paths_and_unsupported_query_keys_are_rejected(fake) -> None:
    transport = LocalHttpsTransport()
    for path in ("https://api.jquants.com/v2/equities/master", "https://evil.example/v2/equities/master",
                 "//api.jquants.com/v2/equities/master", "/v2/equities/bars/daily", "/v2/fins/details", "",
                 "/v2/equities/master/"):
        with pytest.raises(LiveInputError) as info:
            transport.get(path, {"date": "2026-06-30"})
        assert info.value.code == "PATH_NOT_ALLOWED", path
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"limit": "10"})
    assert info.value.code == "QUERY_KEY_NOT_ALLOWED"
    with pytest.raises(LiveInputError):
        transport.get(MASTER, {"date": "2026-06-30 OR 1=1"})
    assert fake.log == [] and transport.attempts == 0
    assert lt.SANCTIONED_HOST == "api.jquants.com" and lt.SANCTIONED_PORT == 443
    signature = LocalHttpsTransport.__init__.__code__.co_varnames
    assert "host" not in signature and "base_url" not in signature and "url" not in signature


# ================================================================ one attempt / no retry / redirect


def test_one_get_is_one_network_attempt_and_no_retry_after_timeout_or_500(fake) -> None:
    transport = LocalHttpsTransport()
    fake.script.append(TimeoutError("timed out"))
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert info.value.code == "NETWORK_TIMEOUT" and len(requests_made(fake)) == 1 and transport.attempts == 1
    assert "timed out" not in str(info.value)
    fake.script.append(FakeResponse(500, b"internal detail"))
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert info.value.code == "HTTP_STATUS_500" and len(requests_made(fake)) == 2 and transport.attempts == 2
    assert "internal detail" not in str(info.value)
    for status in (401, 403, 429):
        fake.script.append(FakeResponse(status, b'{"message": "provider text"}'))
        with pytest.raises(LiveInputError) as info:
            transport.get(MASTER, {"date": "2026-06-30"})
        assert info.value.code == f"HTTP_STATUS_{status}" and "provider text" not in str(info.value)
    assert transport.attempts == 5 and fake.log.count(("close",)) == 5


def test_redirects_are_not_followed_and_the_credential_is_not_forwarded(fake) -> None:
    transport = LocalHttpsTransport()
    for status in (301, 302, 307, 308):
        fake.script.append(FakeResponse(status, b"", {"Location": "https://evil.example/v2/equities/master"}))
        with pytest.raises(LiveInputError) as info:
            transport.get(MASTER, {"date": "2026-06-30"})
        assert info.value.code == f"HTTP_STATUS_{status}" and "evil.example" not in str(info.value)
    opened = [e[1] for e in fake.log if e[0] == "open"]
    assert opened == ["api.jquants.com"] * 4 and len(requests_made(fake)) == 4                # 別の origin へ request しない


def test_network_and_tls_failures_are_sanitized(fake) -> None:
    import http.client
    import ssl
    transport = LocalHttpsTransport()
    for exc, code in ((OSError(-2, "Name or service not known api.jquants.com"), "NETWORK_ERROR"),
                      (ConnectionResetError("reset by peer"), "NETWORK_ERROR"),
                      (http.client.RemoteDisconnected("gone"), "NETWORK_ERROR"),
                      (http.client.IncompleteRead(b"partial body"), "NETWORK_ERROR"),
                      (ssl.SSLError("certificate verify failed"), "TLS_ERROR")):
        fake.script.append(exc)
        with pytest.raises(LiveInputError) as info:
            transport.get(MASTER, {"date": "2026-06-30"})
        assert info.value.code == code and info.value.detail == "connection"
        assert "service not known" not in str(info.value) and "partial body" not in str(info.value)
    assert transport.attempts == 5


# ================================================================ response boundary


def test_invalid_json_non_object_and_oversize_bodies_fail_closed_without_exposing_content(fake) -> None:
    transport = LocalHttpsTransport(max_response_bytes=1024)
    fake.script.append(FakeResponse(200, b"<html>provider maintenance page</html>"))
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert info.value.code == "RESPONSE_NOT_JSON" and "maintenance" not in str(info.value)
    fake.script.append(FakeResponse(200, b"[1, 2, 3]"))
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert info.value.code == "RESPONSE_NOT_OBJECT"
    fake.script.append(FakeResponse(200, b"\xff\xfe\x00"))
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert info.value.code == "RESPONSE_NOT_JSON"
    oversize = json.dumps({"data": [{"CoName": "x" * 2000}]}).encode("utf-8")
    fake.script.append(FakeResponse(200, oversize))
    with pytest.raises(LiveInputError) as info:
        transport.get(MASTER, {"date": "2026-06-30"})
    assert info.value.code == "RESPONSE_TOO_LARGE" and "xxxx" not in str(info.value)
    exact = json.dumps({"data": []}).encode("utf-8")
    fake.script.append(FakeResponse(200, exact + b" " * (1024 - len(exact))))
    assert transport.get(MASTER, {"date": "2026-06-30"}).status == 200                       # 上限ちょうどは通る
    with pytest.raises(LiveInputError):
        LocalHttpsTransport(max_response_bytes=lt.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(LiveInputError):
        LocalHttpsTransport(timeout_seconds=0)
    with pytest.raises(LiveInputError):
        LocalHttpsTransport(timeout_seconds=lt.MAX_TIMEOUT_SECONDS + 1)


def test_response_body_is_not_retained_or_cached_and_nothing_is_written(fake, tmp_path: Path) -> None:
    transport = LocalHttpsTransport()
    marker = {"data": [{"CoName": "RETAIN_SENTINEL"}]}
    fake.script.append(ok(marker))
    first = transport.get(MASTER, {"date": "2026-06-30"})
    assert "RETAIN_SENTINEL" in first.body
    assert not any("RETAIN_SENTINEL" in str(v) for v in vars(transport).values())
    fake.script.append(ok({"data": []}))
    second = transport.get(MASTER, {"date": "2026-06-30"})                                    # cache なし: 2 回目も request
    assert second.body != first.body and len(requests_made(fake)) == 2
    assert list(tmp_path.iterdir()) == [] and not (REPO_ROOT / "data" / "screener_intelligence").exists()
    assert "RETAIN_SENTINEL" not in repr(first)


# ================================================================ frozen LIVE1 budget still governs


def test_frozen_live1_request_budget_controls_total_calls_and_ninth_request_never_reaches_transport(fake) -> None:
    fake.script.extend([ok({"data": []}) for _ in range(8)])
    transport = LocalHttpsTransport()
    client = JQuantsLiveClient(transport, RequestBudget())
    for _ in range(8):
        client.fetch_master("2026-06-30")
    assert transport.attempts == 8 and len(requests_made(fake)) == 8
    with pytest.raises(BudgetExhausted):
        client.fetch_master("2026-06-30")
    assert transport.attempts == 8 and len(requests_made(fake)) == 8 and fake.script == []
    assert not hasattr(transport, "budget") and not hasattr(transport, "retries")            # 第 2 の予算 ・retry は無い


# ================================================================ architecture


def test_architecture_stdlib_only_no_logging_no_filesystem_no_retry_loop_and_locked_host() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(("." * node.level) + node.module)
    assert imported == {"http.client", "json", "os", "ssl", "typing", "urllib.parse", "__future__",
                        ".screener_intelligence.jquants_live_model"}
    assert "requests" not in imported and "logging" not in imported and "time" not in imported
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "print", "eval", "exec", "getattr", "Path", "input"}, node.id
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"write", "write_text", "write_bytes", "sleep", "warning", "info", "debug",
                                     "error", "environ_items", "items"} or node.attr == "items", node.attr
        if isinstance(node, (ast.While, ast.Global, ast.Nonlocal)):
            raise AssertionError("retry loop or module state")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "://" not in node.value and "http://" not in node.value, node.value
    environ_reads = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "environ"]
    assert len(environ_reads) == 1                                                            # 名を指定した 1 変数の読みだけ
    lowered = executable_source(MODULE).lower()
    for token in ("screening", "rank", "score", "recommend", "theme", "llm", "prompt", "anthropic", "openai", "pages",
                  "morning", "sqlite", "retry", "cache", "print(", "logging", "actions", "cron"):
        assert token not in lowered, token
    assert source.count('"api.jquants.com"') == 1 and "SANCTIONED_HOST" in source
    assert 'AUTH_HEADER = "x-api-key"' in source and "Bearer" not in source
    assert "def get(" in source and source.count("connection.request(") == 1


def test_transport_is_not_wired_into_production_pages_or_workflows() -> None:
    for root in ("main.py", "src/intelligence/reports", "src/intelligence/narrative_intelligence",
                 "src/intelligence/theme_intelligence", "src/intelligence/market", "scripts", ".github"):
        path = REPO_ROOT / root
        files = [path] if path.is_file() else list(path.rglob("*")) if path.exists() else []
        for file in files:
            if file.is_file() and file.suffix in (".py", ".yml", ".yaml", ".toml", ".sh"):
                assert "jquants_local_transport" not in file.read_text(encoding="utf-8", errors="replace"), file
    from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
    closure = runtime_closure()
    assert not any("jquants_local_transport" in module for module in closure)
