"""Fetcher（Phase 1-C）: retry・304・redirect・冪等・redaction・失敗の構造化記録。

すべて注入スタブtransportによる完全オフラインテスト（実ネットワークへ出ない）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from src.intelligence.ingestion.fetcher import Fetcher, RetryPolicy
from src.intelligence.ingestion.model import FetchRequest, FetchResponse
from src.intelligence.ingestion.raw_store import JsonlRawRepository
from src.intelligence.sources.model import SourceEndpoint

NOW = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
RSS_BODY = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    b"<item><title>a</title><link>https://e.org/1</link></item></channel></rss>"
)


def make_endpoint(url: str = "https://example.org/feed.xml") -> SourceEndpoint:
    return SourceEndpoint(source_id="example_feed", url=url)


class ScriptedTransport:
    """呼び出しごとに用意したFetchResponseを順に返すスタブ。"""

    def __init__(self, responses: List[FetchResponse]):
        self._responses = list(responses)
        self.requests: List[FetchRequest] = []

    def send(self, request: FetchRequest, *, timeout: float = 20.0) -> FetchResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def ok_response(body: bytes = RSS_BODY, **kw) -> FetchResponse:
    defaults = dict(
        status_code=200,
        final_url="https://example.org/feed.xml",
        content_type='application/rss+xml; charset=utf-8',
        etag='W/"v1"',
        last_modified="Fri, 28 Aug 2026 09:00:00 GMT",
        body=body,
        retrieved_at=NOW,
        elapsed_ms=42,
    )
    defaults.update(kw)
    return FetchResponse(**defaults)


def make_fetcher(tmp_path: Path, transport, **kw) -> tuple[Fetcher, JsonlRawRepository]:
    repo = JsonlRawRepository(tmp_path)
    sleeps: List[float] = []
    fetcher = Fetcher(
        transport, repo, sleeper=sleeps.append, clock=lambda: NOW, **kw
    )
    fetcher.test_sleeps = sleeps  # type: ignore[attr-defined]
    return fetcher, repo


def test_success_creates_attempt_and_raw_item(tmp_path: Path) -> None:
    transport = ScriptedTransport([ok_response()])
    fetcher, repo = make_fetcher(tmp_path, transport)
    outcome = fetcher.fetch(make_endpoint())
    assert outcome.attempt.status_code == 200
    assert outcome.attempt.requested_at.tzinfo is not None
    assert outcome.raw_item is not None and outcome.body_created
    assert outcome.raw_item.content_hash and outcome.raw_item.encoding == "utf-8"
    assert outcome.raw_item.fetch_attempt_id == outcome.attempt.attempt_id
    assert outcome.attempt.raw_item_id == outcome.raw_item.raw_item_id
    assert repo.read_body(outcome.raw_item) == RSS_BODY  # SHA-256一致のroundtrip
    assert repo.blobs.verify_blob(outcome.raw_item.content_hash)


def test_conditional_get_uses_previous_validators(tmp_path: Path) -> None:
    transport = ScriptedTransport([
        ok_response(),
        FetchResponse(status_code=304, retrieved_at=NOW, etag='W/"v1"'),
    ])
    fetcher, repo = make_fetcher(tmp_path, transport)
    fetcher.fetch(make_endpoint())
    outcome2 = fetcher.fetch(make_endpoint())
    # 2回目のリクエストへ前回のvalidatorが載る（観測列からの導出。二重保存しない）
    req2 = transport.requests[1]
    assert req2.etag == 'W/"v1"'
    assert req2.last_modified == "Fri, 28 Aug 2026 09:00:00 GMT"
    # 304: RawItemは作られないがattemptは記録される
    assert outcome2.raw_item is None
    assert outcome2.attempt.not_modified and outcome2.attempt.conditional_used
    assert len(list(repo.iter_attempts())) == 2
    assert len(list(repo.iter_raw_items())) == 1


def test_refetch_same_content_is_idempotent(tmp_path: Path) -> None:
    """同じresponseの二重処理: blob重複なし・item冪等・provenanceは試行ごとに残る。"""
    transport = ScriptedTransport([ok_response(), ok_response()])
    fetcher, repo = make_fetcher(tmp_path, transport)
    o1 = fetcher.fetch(make_endpoint())
    o2 = fetcher.fetch(make_endpoint())
    assert o1.raw_item.raw_item_id == o2.raw_item.raw_item_id
    assert o1.body_created and not o2.body_created  # 物理blobは1つ
    assert len(list(repo.iter_raw_items())) == 1  # itemも1つ（冪等）
    attempts = list(repo.iter_attempts())
    assert len(attempts) == 2  # fetch provenanceは失わない
    assert all(a.raw_item_id == o1.raw_item.raw_item_id for a in attempts)


def test_changed_content_same_url_creates_new_item_keeps_old(tmp_path: Path) -> None:
    """RAW DATA IS IMMUTABLE: 同一URLの内容更新は新RawItem。旧versionは消えない。"""
    body_v2 = RSS_BODY.replace(b"<title>a</title>", b"<title>a (updated)</title>")
    transport = ScriptedTransport([ok_response(), ok_response(body=body_v2)])
    fetcher, repo = make_fetcher(tmp_path, transport)
    o1 = fetcher.fetch(make_endpoint())
    o2 = fetcher.fetch(make_endpoint())
    assert o1.raw_item.raw_item_id != o2.raw_item.raw_item_id
    items = list(repo.iter_raw_items())
    assert len(items) == 2
    assert repo.read_body(o1.raw_item) == RSS_BODY  # 旧本文も無傷


def test_duplicate_body_across_sources_shares_blob_keeps_provenance(tmp_path: Path) -> None:
    transport = ScriptedTransport([ok_response(), ok_response()])
    fetcher, repo = make_fetcher(tmp_path, transport)
    o1 = fetcher.fetch(make_endpoint("https://example.org/feed.xml"))
    o2 = fetcher.fetch(SourceEndpoint(source_id="mirror_feed", url="https://mirror.example/feed.xml"))
    assert o1.raw_item.content_hash == o2.raw_item.content_hash  # 同一body
    assert not o2.body_created  # physical dedup
    assert o1.raw_item.raw_item_id != o2.raw_item.raw_item_id  # provenanceは別レコード
    assert {i.source_id for i in repo.iter_raw_items()} == {"example_feed", "mirror_feed"}


def test_403_is_recorded_without_retry(tmp_path: Path) -> None:
    transport = ScriptedTransport([FetchResponse(status_code=403, retrieved_at=NOW)])
    fetcher, repo = make_fetcher(tmp_path, transport)
    outcome = fetcher.fetch(make_endpoint())
    assert len(transport.requests) == 1  # 4xxはretryしない
    assert outcome.raw_item is None
    assert outcome.attempt.status_code == 403  # FetchAttempt without RawItem
    assert fetcher.test_sleeps == []


def test_429_respects_retry_after_then_succeeds(tmp_path: Path) -> None:
    transport = ScriptedTransport([
        FetchResponse(status_code=429, retry_after="7", retrieved_at=NOW),
        ok_response(),
    ])
    fetcher, _repo = make_fetcher(tmp_path, transport)
    outcome = fetcher.fetch(make_endpoint())
    assert fetcher.test_sleeps == [7.0]  # Retry-After尊重
    assert outcome.attempt.status_code == 200 and outcome.attempt.retries == 1


def test_500_retries_with_backoff_then_records_failure(tmp_path: Path) -> None:
    transport = ScriptedTransport([
        FetchResponse(status_code=500, retrieved_at=NOW),
        FetchResponse(status_code=500, retrieved_at=NOW),
        FetchResponse(status_code=500, retrieved_at=NOW),
    ])
    fetcher, repo = make_fetcher(tmp_path, transport, policy=RetryPolicy(max_attempts=3))
    outcome = fetcher.fetch(make_endpoint())
    assert len(transport.requests) == 3  # 無限retryなし（最大回数で停止）
    assert fetcher.test_sleeps == [2.0, 4.0]  # 指数backoff
    assert outcome.raw_item is None and outcome.attempt.status_code == 500
    assert list(repo.iter_attempts())[0].retries == 2


def test_timeout_is_retryable_and_recorded_structured(tmp_path: Path) -> None:
    transport = ScriptedTransport([
        FetchResponse(status_code=0, error_kind="timeout", error_detail="timed out", retrieved_at=NOW),
        FetchResponse(status_code=0, error_kind="timeout", error_detail="timed out", retrieved_at=NOW),
        FetchResponse(status_code=0, error_kind="timeout", error_detail="timed out", retrieved_at=NOW),
    ])
    fetcher, repo = make_fetcher(tmp_path, transport)
    outcome = fetcher.fetch(make_endpoint())
    assert outcome.attempt.status_code == 0
    assert outcome.attempt.error_kind == "timeout"  # structured failure（silentにしない）
    assert outcome.attempt.error_detail
    assert len(list(repo.iter_attempts())) == 1


def test_redirect_chain_preserved_and_registry_untouched(tmp_path: Path) -> None:
    transport = ScriptedTransport([
        ok_response(
            final_url="https://feeds.new-host.example/feed.xml",
            redirect_chain=("https://feeds.new-host.example/feed.xml",),
            permanent_redirect=True,
        )
    ])
    fetcher, _repo = make_fetcher(tmp_path, transport)
    outcome = fetcher.fetch(make_endpoint())
    assert outcome.attempt.permanent_redirect  # Registry更新の候補として記録のみ
    assert outcome.attempt.redirect_chain == ("https://feeds.new-host.example/feed.xml",)
    assert outcome.attempt.final_url == "https://feeds.new-host.example/feed.xml"


def test_secret_redaction_in_persisted_urls(tmp_path: Path) -> None:
    url = "https://api.example.org/docs.json?type=2&Subscription-Key=REALSECRET"
    transport = ScriptedTransport([
        ok_response(final_url=url, redirect_chain=(url,), body=b'{"ok":1}')
    ])
    fetcher, repo = make_fetcher(tmp_path, transport)
    outcome = fetcher.fetch(SourceEndpoint(source_id="edinet", url=url))
    for text in (
        outcome.attempt.url, outcome.attempt.final_url,
        *outcome.attempt.redirect_chain, outcome.raw_item.locator,
    ):
        assert "REALSECRET" not in text and "REDACTED" in text
    # 永続ファイルにもSecretが残らない
    for p in ("raw_items.jsonl", "fetch_attempts.jsonl"):
        assert "REALSECRET" not in (tmp_path / p).read_text(encoding="utf-8")


def test_transport_exception_becomes_structured_attempt(tmp_path: Path) -> None:
    class ExplodingTransport:
        def send(self, request, *, timeout: float = 20.0):
            raise RuntimeError("boom")

    fetcher, repo = make_fetcher(tmp_path, ExplodingTransport())
    outcome = fetcher.fetch(make_endpoint())
    assert outcome.attempt.status_code == 0
    assert outcome.attempt.error_kind == "unknown" and "boom" in outcome.attempt.error_detail


def test_repository_satisfies_protocols(tmp_path: Path) -> None:
    from src.intelligence.core.contracts import FetchAttemptRepository, RawRepository

    repo = JsonlRawRepository(tmp_path)
    assert isinstance(repo, RawRepository)
    assert isinstance(repo, FetchAttemptRepository)
