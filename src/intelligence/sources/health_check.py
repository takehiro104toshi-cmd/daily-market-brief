"""フィード死活チェック（Phase 1-B）。

設計方針:
- **transport注入式**: HTTP実装は外部から渡す（Protocol）。本開発環境はegress遮断で
  live実行不可のため、実行はネットワークのある環境（GitHub Actions等）に委ね、
  判定ロジック自体は注入transportでオフラインテスト可能にする。
- **最小アクセスのみ**: 1フィード=1リクエスト・先頭サンプルのみ読む。bulk収集・
  全文ダウンロード・バックフィルは行わない（P1-C以降の責務）。
- **Secretを扱わない**: 認証が要るエンドポイントへは資格情報を付けず、401等を
  AUTH_REQUIREDとして記録するだけ（AuthTypeは列挙のみ。docs/security/参照）。
- 判定結果は SourceHealthObservation（時系列レコード）として積む。現在状態は
  観測列から導出する（導出値を正とする方針。二重保存しない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Protocol, Tuple, runtime_checkable
import re

from ..core.ids import new_id
from .model import FeedFormat, HealthState, SourceEndpoint, SourceHealthObservation

#: 「新鮮」とみなす既定の許容経過時間（30日）。低頻度の公式フィードを誤検知しない値。
DEFAULT_FRESH_WITHIN_HOURS = 24 * 30

#: サンプルとして読む最大文字数の目安（transport実装への推奨値。強制はしない）
SAMPLE_CHARS = 8192


@dataclass(frozen=True, kw_only=True)
class FetchResult:
    """transportが返す取得結果。bodyは先頭サンプルのみでよい。"""

    status: int = 0  # 0 = リクエスト不成立（DNS/timeout/プロキシ遮断等）
    final_url: str = ""
    permanent_redirect: bool = False  # 301/308経由で到達した場合True
    content_type: str = ""
    etag_present: bool = False
    last_modified: Optional[datetime] = None
    body_sample: str = ""  # 先頭サンプル（デコード済みテキスト）
    error: str = ""  # 不成立時の理由（例外文字列等。Secretを含めないこと）


@runtime_checkable
class Transport(Protocol):
    """HTTP GET 1回分の抽象。実装例: urllib/httpx/テスト用スタブ。"""

    def get(self, url: str, *, timeout: float = 20.0) -> FetchResult:  # pragma: no cover
        ...


def classify_format(sample: str) -> FeedFormat:
    """先頭サンプルからフィード形式を推定する（P1-Cパーサー選定の入力）。"""
    head = sample.lstrip()[:2048].lower()
    if not head:
        return FeedFormat.UNKNOWN
    if "<rdf:rdf" in head or "rdf-syntax-ns" in head:
        return FeedFormat.RDF
    if "<feed" in head and ("w3.org/2005/atom" in head or "<entry" in sample.lower()):
        return FeedFormat.ATOM
    if "<rss" in head:
        return FeedFormat.RSS2
    if head.startswith("{") or head.startswith("["):
        return FeedFormat.JSON_API
    if "<!doctype html" in head or "<html" in head:
        return FeedFormat.HTML
    return FeedFormat.UNKNOWN


_DATE_TAG = re.compile(
    r"<(pubDate|updated|published|dc:date|lastBuildDate)>\s*([^<]+?)\s*</\1>",
    re.IGNORECASE,
)


def _parse_feed_datetime(text: str) -> Optional[datetime]:
    """RFC822/ISO8601日付をtz-awareに限って返す（naiveはNone=不明扱い。推測しない）。"""
    try:
        dt = parsedate_to_datetime(text)
        if dt is not None and dt.tzinfo is not None:
            return dt
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt
    except ValueError:
        pass
    return None


def extract_latest_item_at(sample: str) -> Optional[datetime]:
    """サンプル中の日付タグから最新時刻を返す（tz-aware確定分のみ）。"""
    candidates = []
    for _tag, raw in _DATE_TAG.findall(sample):
        dt = _parse_feed_datetime(raw)
        if dt is not None:
            candidates.append(dt)
    return max(candidates) if candidates else None


def _hosts_differ(url_a: str, url_b: str) -> bool:
    def host(u: str) -> str:
        return u.split("//", 1)[-1].split("/", 1)[0].lower()

    return bool(url_a) and bool(url_b) and host(url_a) != host(url_b)


def evaluate(
    result: FetchResult,
    *,
    now: datetime,
    canonical_url: str = "",
    fresh_within_hours: int = DEFAULT_FRESH_WITHIN_HOURS,
) -> Tuple[HealthState, str]:
    """取得結果 → (HealthState, note)。判定表: docs/sources/SOURCE_HEALTH_AUDIT.md §2。"""
    if result.status == 0:
        return HealthState.UNVERIFIED, f"リクエスト不成立: {result.error or 'unknown'}"
    if result.status == 401:
        return HealthState.AUTH_REQUIRED, "401 Unauthorized（資格情報なしで確認）"
    if result.status == 429:
        return HealthState.RATE_LIMITED, "429 Too Many Requests"
    if result.status in (404, 410):
        return HealthState.DEAD, f"{result.status}（恒常なら提供終了）"
    if result.status == 403:
        return HealthState.DEGRADED, "403 Forbidden（UA/クライアント条件ブロック疑い）"
    if result.status >= 400:
        return HealthState.DEGRADED, f"HTTP {result.status}"
    # 2xx/3xx到達
    if result.permanent_redirect and _hosts_differ(canonical_url, result.final_url):
        return HealthState.MOVED, f"恒久移転: {result.final_url}"
    fmt = classify_format(result.body_sample)
    if fmt in (FeedFormat.HTML, FeedFormat.UNKNOWN):
        return HealthState.DEGRADED, f"応答はあるがフィードとして解釈不能（detected={fmt.value}）"
    if fmt is FeedFormat.JSON_API:
        return HealthState.HEALTHY, "JSON API到達（アイテム構造の検証はP1-Cアダプタの責務）"
    latest = extract_latest_item_at(result.body_sample)
    if latest is None:
        return HealthState.DEGRADED, "フィードは有効だが日付付きアイテムをサンプル内で確認できず"
    age_hours = (now - latest.astimezone(timezone.utc)).total_seconds() / 3600
    if age_hours > fresh_within_hours:
        return HealthState.DEGRADED, f"stale: 最新アイテムが{int(age_hours)}時間前"
    return HealthState.HEALTHY, ""


def check_endpoint(
    endpoint: SourceEndpoint,
    transport: Transport,
    *,
    now: Optional[datetime] = None,
    fresh_within_hours: int = DEFAULT_FRESH_WITHIN_HOURS,
    timeout: float = 20.0,
) -> SourceHealthObservation:
    """1エンドポイントを1リクエストで死活判定し、観測レコードを返す。"""
    checked_at = now or datetime.now(timezone.utc)
    try:
        result = transport.get(endpoint.url, timeout=timeout)
    except Exception as exc:  # transport実装の想定外例外もUNVERIFIED観測として残す
        result = FetchResult(status=0, error=f"{type(exc).__name__}: {exc}")
    state, note = evaluate(
        result,
        now=checked_at,
        canonical_url=endpoint.url,
        fresh_within_hours=fresh_within_hours,
    )
    latest = extract_latest_item_at(result.body_sample)
    freshness: Optional[int] = None
    if latest is not None:
        freshness = int((checked_at - latest.astimezone(timezone.utc)).total_seconds() // 3600)
    return SourceHealthObservation(
        health_obs_id=new_id("shealth", checked_at),
        source_id=endpoint.source_id,
        checked_at=checked_at,
        state=state,
        http_status=result.status,
        final_url=result.final_url,
        permanent_redirect=result.permanent_redirect,
        content_type=result.content_type,
        detected_format=classify_format(result.body_sample),
        etag_present=result.etag_present,
        last_modified=result.last_modified,
        latest_item_at=latest,
        freshness_age_hours=freshness,
        method="live_http",
        note=note,
    )


def derive_current_state(
    observations: Tuple[SourceHealthObservation, ...],
) -> Optional[SourceHealthObservation]:
    """観測列から「現在状態」を導出する（最新checked_atの観測。二重保存しない）。"""
    return max(observations, key=lambda o: o.checked_at) if observations else None
