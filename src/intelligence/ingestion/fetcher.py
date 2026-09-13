"""Fetcher（Phase 1-C）。1エンドポイント1回分の取得を編成する。

責務（God Fetcher禁止——各段は他モジュールが担う）:
- 条件付きGET: 過去のFetchAttempt列から (etag, last_modified) を**導出**して送る
- retry: timeout/connection系・5xx・429のみ。最大回数・指数backoff・Retry-After尊重
- 記録: **RawItemが生まれない試行（304/403/timeout等）も必ずFetchAttemptとして残す**
- 保存: 200応答のbodyをBlobStoreへ（immutable）、RawItemをrepositoryへ（冪等）
- redaction: 保存するURL群（url/final_url/redirect_chain）はすべてredact_url通過後

scheduler-levelのretry・定常実行はP1-Cでは実装しない（Phase 12）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

from ..core.ids import new_id
from ..sources.model import RawItem, SourceEndpoint
from .model import FetchAttempt, FetchRequest, FetchResponse
from .transport import (
    DEFAULT_ACCEPT,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    HttpTransport,
    charset_from_content_type,
    redact_url,
)

#: retry対象のHTTPステータス（5xx・429のみ。4xx一般・認証系は無制限retryしない）
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_ERROR_KINDS = frozenset({"timeout", "connection"})


@dataclass(frozen=True, kw_only=True)
class RetryPolicy:
    """単純・明示的なretry方針（P1-C指示）。無限retryは構造上不可能。"""

    max_attempts: int = 3  # 初回含む総試行数
    backoff_base_seconds: float = 2.0  # 2, 4, 8...の指数
    max_retry_after_seconds: float = 120.0  # Retry-Afterの尊重上限

    def is_retryable(self, response: FetchResponse) -> bool:
        if response.status_code == 0:
            return response.error_kind in _RETRYABLE_ERROR_KINDS
        return response.status_code in _RETRYABLE_STATUS

    def delay_before_retry(self, response: FetchResponse, retry_index: int) -> float:
        """retry_index: 0始まり（1回目のretry前=0）。"""
        if response.retry_after:
            try:
                return min(float(response.retry_after), self.max_retry_after_seconds)
            except ValueError:
                pass  # HTTP-date形式のRetry-Afterはbackoffへフォールバック
        return self.backoff_base_seconds * (2 ** retry_index)


@dataclass(frozen=True, kw_only=True)
class FetchOutcome:
    """fetch 1回分の結果。attemptは常に存在し、raw_itemは本文取得時のみ。"""

    attempt: FetchAttempt
    raw_item: Optional[RawItem] = None
    response: Optional[FetchResponse] = None  # transient（呼び出し側のparse用。永続化しない）
    body_created: bool = False  # blobが新規作成された（False=物理dedupヒット or 本文なし）


class Fetcher:
    def __init__(
        self,
        transport: HttpTransport,
        repository,  # JsonlRawRepository（RawRepository＋FetchAttemptRepository充足）
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        policy: Optional[RetryPolicy] = None,
        timeout: float = DEFAULT_TIMEOUT,
        sleeper: Callable[[float], None] = time.sleep,  # テストで注入
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._transport = transport
        self._repo = repository
        self._user_agent = user_agent
        self._policy = policy or RetryPolicy()
        self._timeout = timeout
        self._sleep = sleeper
        self._clock = clock

    def fetch(self, endpoint: SourceEndpoint) -> FetchOutcome:
        """1エンドポイントを取得し、FetchAttempt（＋RawItem）を永続化して返す。

        例外は投げない（source isolation——1ソースの障害でrun全体を落とさない）。
        """
        requested_at = self._clock()
        etag, last_modified = self._repo.latest_conditional(endpoint.endpoint_id)
        request = FetchRequest(
            source_id=endpoint.source_id,
            endpoint_id=endpoint.endpoint_id,
            url=endpoint.url,
            headers=(("User-Agent", self._user_agent), ("Accept", DEFAULT_ACCEPT)),
            etag=etag,
            last_modified=last_modified,
            requested_at=requested_at,
        )

        response: Optional[FetchResponse] = None
        retries = 0
        for attempt_index in range(self._policy.max_attempts):
            try:
                response = self._transport.send(request, timeout=self._timeout)
            except Exception as exc:  # noqa: BLE001 transport実装の想定外例外も試行として記録
                response = FetchResponse(
                    status_code=0,
                    retrieved_at=self._clock(),
                    error_kind="unknown",
                    error_detail=f"{type(exc).__name__}: {str(exc)[:160]}",
                )
            if not self._policy.is_retryable(response) or attempt_index == self._policy.max_attempts - 1:
                break
            self._sleep(self._policy.delay_before_retry(response, attempt_index))
            retries += 1

        assert response is not None
        attempt_id = new_id("fetch", requested_at)
        raw_item: Optional[RawItem] = None
        body_created = False
        content_hash = ""
        body_size = 0

        if 200 <= response.status_code < 300 and response.body:
            content_hash, locator, body_created = self._repo.store_body(response.body)
            body_size = len(response.body)
            raw_item = RawItem(
                raw_item_id=RawItem.make_id(endpoint.source_id, endpoint.url, content_hash),
                source_id=endpoint.source_id,
                endpoint_id=endpoint.endpoint_id,
                locator=redact_url(endpoint.url),
                retrieved_at=response.retrieved_at,
                media_type=(response.content_type.split(";")[0].strip() or "application/octet-stream"),
                encoding=charset_from_content_type(response.content_type) or "",
                content_hash=content_hash,
                size_bytes=body_size,
                storage_ref=locator,
                fetch_attempt_id=attempt_id,
            )
            # 冪等: 同一内容の再取得（同一raw_item_id）はスキップされる。
            # ただし今回のattempt参照は新IDのため、既存itemがあればそれを正とする。
            existing = self._repo.get_raw_item(raw_item.raw_item_id)
            if existing is not None:
                raw_item = existing
            else:
                self._repo.add_raw_item(raw_item)

        attempt = FetchAttempt(
            attempt_id=attempt_id,
            source_id=endpoint.source_id,
            endpoint_id=endpoint.endpoint_id,
            url=redact_url(endpoint.url),
            requested_at=requested_at,
            elapsed_ms=response.elapsed_ms,
            status_code=response.status_code,
            final_url=redact_url(response.final_url),
            redirect_chain=tuple(redact_url(u) for u in response.redirect_chain),
            permanent_redirect=response.permanent_redirect,
            content_type=response.content_type,
            body_size=body_size,
            content_hash=content_hash,
            etag=response.etag,
            last_modified=response.last_modified,
            not_modified=(response.status_code == 304),
            conditional_used=bool(etag or last_modified),
            raw_item_id=(raw_item.raw_item_id if raw_item else ""),
            error_kind=response.error_kind,
            error_detail=response.error_detail,
            retries=retries,
        )
        self._repo.add_attempt(attempt)
        return FetchOutcome(
            attempt=attempt, raw_item=raw_item, response=response, body_created=body_created
        )
