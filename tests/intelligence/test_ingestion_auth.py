"""runtime credential注入（DESIGN CORRECTION 1）: ephemeralのみ・永続経路ゼロ。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.intelligence.ingestion.auth import EnvCredentialResolver, make_auth_headers_provider
from src.intelligence.ingestion.model import FetchRequest
from src.intelligence.ingestion.transport import UrllibTransport

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def make_request(source_id: str = "edinet_disclosures") -> FetchRequest:
    return FetchRequest(source_id=source_id, endpoint_id="ep",
                        url="https://api.example.org/d.json", requested_at=NOW)


def test_env_resolver_injects_header_only_when_env_set(monkeypatch) -> None:
    resolver = EnvCredentialResolver(
        {"edinet_disclosures": ("Ocp-Apim-Subscription-Key", "EDINET_API_KEY")})
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    assert resolver.headers_for("edinet_disclosures") == {}  # 未設定はエラーにしない
    monkeypatch.setenv("EDINET_API_KEY", "MEMSECRET")
    assert resolver.headers_for("edinet_disclosures") == {
        "Ocp-Apim-Subscription-Key": "MEMSECRET"}
    assert resolver.headers_for("other_source") == {}


def test_transport_merges_auth_headers_ephemerally(monkeypatch) -> None:
    """送信ヘッダにのみ合成され、FetchRequest（永続形）はSecretを持たないまま。"""
    monkeypatch.setenv("EDINET_API_KEY", "MEMSECRET")
    resolver = EnvCredentialResolver(
        {"edinet_disclosures": ("Ocp-Apim-Subscription-Key", "EDINET_API_KEY")})
    transport = UrllibTransport(auth_headers_provider=make_auth_headers_provider(resolver))
    request = make_request()
    headers = transport._headers_for(request)
    assert headers["Ocp-Apim-Subscription-Key"] == "MEMSECRET"  # ephemeralヘッダのみ
    assert all("MEMSECRET" not in v for _k, v in request.headers)  # 永続形は無垢
    # FetchRequest自体へ資格情報ヘッダを積む経路は引き続き型レベルで拒否
    with pytest.raises(ValueError):
        FetchRequest(source_id="s", endpoint_id="e", url="https://x.example/f",
                     headers=(("Subscription-Key", "MEMSECRET"),), requested_at=NOW)


def test_transport_without_provider_unchanged() -> None:
    headers = UrllibTransport()._headers_for(make_request())
    assert "Ocp-Apim-Subscription-Key" not in headers
    assert "User-Agent" in headers and "Accept" in headers
