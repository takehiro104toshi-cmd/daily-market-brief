"""ingestion/model.py・transport補助関数の検証（Phase 1-C）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.intelligence.core import serialization
from src.intelligence.ingestion.model import FetchAttempt, FetchRequest, FetchResponse
from src.intelligence.ingestion.transport import classify_error, redact_url

NOW = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)


def test_fetch_request_rejects_credential_headers() -> None:
    """Secret規律: 資格情報ヘッダは型レベルで拒否（transportへも渡らない）。"""
    for name in ("Authorization", "cookie", "X-Api-Key", "Subscription-Key"):
        with pytest.raises(ValueError):
            FetchRequest(
                source_id="s", endpoint_id="ep", url="https://example.org/f",
                headers=((name, "value"),), requested_at=NOW,
            )


def test_fetch_request_requires_aware_datetime_and_http_url() -> None:
    with pytest.raises(ValueError):
        FetchRequest(source_id="s", endpoint_id="e", url="https://x.example/f",
                     requested_at=datetime(2026, 8, 30))  # naive
    with pytest.raises(ValueError):
        FetchRequest(source_id="s", endpoint_id="e", url="ftp://x.example/f", requested_at=NOW)


def test_fetch_response_rejects_unknown_error_kind() -> None:
    with pytest.raises(ValueError):
        FetchResponse(retrieved_at=NOW, error_kind="weird")


def test_fetch_attempt_serialization_roundtrip() -> None:
    serialization.register_domain_types()
    attempt = FetchAttempt(
        attempt_id="fetch_01TEST",
        source_id="fed_press",
        endpoint_id="ep_abc",
        url="https://example.org/feed.xml",
        requested_at=NOW,
        status_code=200,
        final_url="https://example.org/feed.xml",
        redirect_chain=("https://example.org/old", "https://example.org/feed.xml"),
        permanent_redirect=True,
        content_type="application/rss+xml",
        body_size=1234,
        content_hash="ab" * 32,
        etag='W/"xyz"',
        conditional_used=True,
        raw_item_id="raw_deadbeef",
        retries=1,
    )
    decoded = serialization.decode(serialization.encode(attempt))
    assert decoded == attempt
    assert decoded.redirect_chain == attempt.redirect_chain


def test_fetch_attempt_requires_aware_requested_at() -> None:
    with pytest.raises(ValueError):
        FetchAttempt(attempt_id="fetch_X", source_id="s", endpoint_id="e",
                     url="https://x.example/f", requested_at=datetime(2026, 8, 30))


def test_redact_url_masks_credential_query_values() -> None:
    assert (
        redact_url("https://api.example.org/d.json?type=2&Subscription-Key=SECRETX&x=1")
        == "https://api.example.org/d.json?type=2&Subscription-Key=REDACTED&x=1"
    )
    assert redact_url("https://api.example.org/d.json?appId=SECRETY").endswith("appId=REDACTED")
    # 資格情報でないクエリ・クエリ無しURLは不変
    assert redact_url("https://example.org/feed.xml") == "https://example.org/feed.xml"
    assert redact_url("https://example.org/f?page=2") == "https://example.org/f?page=2"


def test_classify_error_maps_kinds() -> None:
    import socket
    import ssl
    import urllib.error

    assert classify_error(socket.timeout("t"))[0] == "timeout"
    assert classify_error(TimeoutError("t"))[0] == "timeout"
    assert classify_error(ssl.SSLError("tls"))[0] == "tls"
    assert classify_error(urllib.error.URLError(socket.gaierror("dns")))[0] == "dns"
    assert classify_error(urllib.error.URLError(OSError("refused")))[0] == "connection"
    assert classify_error(ConnectionResetError("r"))[0] == "connection"
    assert classify_error(RuntimeError("x"))[0] == "unknown"
