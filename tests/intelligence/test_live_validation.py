"""live_validation（Phase 1-C）のオフライン検証。

実ネットワークへは出ない（scripted transport注入）。liveレスポンスへの依存は作らない
（P1-C指示「テストはofflineで再現可能であること」）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.intelligence.ingestion.fetcher import Fetcher
from src.intelligence.ingestion.live_validation import DEFAULT_SET, validate_source
from src.intelligence.ingestion.model import FetchResponse
from src.intelligence.ingestion.raw_store import JsonlRawRepository

NOW = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
RSS = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>BLS</title>'
    b"<item><title>CPI</title><link>https://e.gov/1</link>"
    b"<pubDate>Sat, 29 Aug 2026 12:00:00 +0000</pubDate></item></channel></rss>"
)


class OneShotTransport:
    def __init__(self, response: FetchResponse):
        self._response = response

    def send(self, request, *, timeout: float = 20.0) -> FetchResponse:
        return self._response


def run_validation(tmp_path: Path, response: FetchResponse) -> dict:
    repo = JsonlRawRepository(tmp_path)
    fetcher = Fetcher(OneShotTransport(response), repo, clock=lambda: NOW)
    feed = {"id": "bls_latest", "endpoint": {"url": "https://www.bls.gov/feed/bls_latest.rss"}}
    return validate_source(feed, fetcher)


def test_default_set_is_minimal_and_core_focused() -> None:
    assert len(DEFAULT_SET) <= 12, "bulk化の禁止（最小セットのみ）"
    for core_id in ("fed_press", "boj_whatsnew", "mof_whatsnew", "dmb_ecb_press", "bls_latest"):
        assert core_id in DEFAULT_SET


def test_validate_source_healthy_record_shape(tmp_path: Path) -> None:
    record = run_validation(tmp_path, FetchResponse(
        status_code=200, final_url="https://www.bls.gov/feed/bls_latest.rss",
        content_type="application/rss+xml", body=RSS, retrieved_at=NOW, etag='W/"1"',
    ))
    assert record["source_id"] == "bls_latest"
    assert record["state"] == "healthy"
    assert record["detected_format"] == "rss2" and record["parsed_format"] == "rss2"
    assert record["entries_extracted"] == 1
    assert record["content_hash"] and record["latest_item_at"].startswith("2026-08-29")
    assert record["checked_at"].endswith("+00:00")  # tz-aware


def test_validate_source_auth_required_without_secrets(tmp_path: Path) -> None:
    record = run_validation(tmp_path, FetchResponse(
        status_code=401, retrieved_at=NOW, content_type="application/json",
    ))
    assert record["state"] == "auth_required"
    assert record["entries_extracted"] == 0


def test_validate_source_network_failure_is_unverified(tmp_path: Path) -> None:
    record = run_validation(tmp_path, FetchResponse(
        status_code=0, error_kind="timeout", error_detail="timed out", retrieved_at=NOW,
    ))
    assert record["state"] == "unverified"  # DEADへ倒さない
    assert record["error_kind"] == "timeout"
