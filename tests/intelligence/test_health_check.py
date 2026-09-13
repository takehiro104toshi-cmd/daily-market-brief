"""health_check（Phase 1-B）のオフラインテスト。

transport注入で全状態遷移を検証する（実ネットワークへは一切出ない）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.intelligence.core import serialization
from src.intelligence.sources.health_check import (
    FetchResult,
    check_endpoint,
    classify_format,
    derive_current_state,
    evaluate,
    extract_latest_item_at,
)
from src.intelligence.sources.model import (
    AuthType,
    FeedFormat,
    HealthState,
    SourceEndpoint,
    SourceHealthObservation,
    UsageStatus,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

RSS2_FRESH = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    "<item><title>a</title><pubDate>Fri, 28 Aug 2026 09:00:00 +0000</pubDate></item>"
    "</channel></rss>"
)
RSS2_STALE = (
    '<?xml version="1.0"?><rss version="2.0"><channel>'
    "<item><pubDate>Mon, 05 Jan 2026 09:00:00 GMT</pubDate></item></channel></rss>"
)
ATOM_SAMPLE = (
    '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
    "<entry><updated>2026-08-28T10:30:00Z</updated></entry></feed>"
)
RDF_SAMPLE = (
    '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<item><dc:date>2026-08-29T01:00:00+09:00</dc:date></item></rdf:RDF>"
)
JSON_SAMPLE = '{"results": [{"docID": "X"}]}'
HTML_SAMPLE = "<!DOCTYPE html><html><body>Not a feed</body></html>"


def make_endpoint(url: str = "https://example.org/feed.xml") -> SourceEndpoint:
    return SourceEndpoint(
        source_id="example_feed",
        url=url,
        declared_format=FeedFormat.RSS2,
        auth_type=AuthType.NONE,
        usage_status=UsageStatus.PUBLIC_FEED,
    )


class StubTransport:
    def __init__(self, result: FetchResult | None = None, exc: Exception | None = None):
        self._result = result
        self._exc = exc
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float = 20.0) -> FetchResult:
        self.calls.append(url)
        if self._exc:
            raise self._exc
        assert self._result is not None
        return self._result


# ---------------------------------------------------------------- 形式判定


@pytest.mark.parametrize(
    "sample, expected",
    [
        (RSS2_FRESH, FeedFormat.RSS2),
        (ATOM_SAMPLE, FeedFormat.ATOM),
        (RDF_SAMPLE, FeedFormat.RDF),
        (JSON_SAMPLE, FeedFormat.JSON_API),
        (HTML_SAMPLE, FeedFormat.HTML),
        ("", FeedFormat.UNKNOWN),
        ("plain text", FeedFormat.UNKNOWN),
    ],
)
def test_classify_format(sample: str, expected: FeedFormat) -> None:
    assert classify_format(sample) is expected


def test_extract_latest_item_at_takes_max_aware_datetime() -> None:
    sample = RSS2_FRESH + ATOM_SAMPLE  # pubDate 28日09:00 と updated 28日10:30
    latest = extract_latest_item_at(sample)
    assert latest == datetime(2026, 8, 28, 10, 30, tzinfo=timezone.utc)


def test_extract_ignores_naive_dates() -> None:
    # tz情報のない日付は「不明」として扱う（source提供時刻とinferredを混同しない）
    sample = "<item><pubDate>28 Aug 2026 09:00:00</pubDate></item>"
    assert extract_latest_item_at(sample) is None


# ---------------------------------------------------------------- 判定表


def _eval(result: FetchResult, **kw):
    return evaluate(result, now=NOW, canonical_url="https://example.org/feed.xml", **kw)


def test_evaluate_healthy_fresh_rss2() -> None:
    state, note = _eval(FetchResult(status=200, body_sample=RSS2_FRESH))
    assert state is HealthState.HEALTHY
    assert note == ""


def test_evaluate_stale_feed_is_degraded() -> None:
    state, note = _eval(FetchResult(status=200, body_sample=RSS2_STALE))
    assert state is HealthState.DEGRADED
    assert "stale" in note


def test_evaluate_status_mapping() -> None:
    assert _eval(FetchResult(status=401))[0] is HealthState.AUTH_REQUIRED
    assert _eval(FetchResult(status=429))[0] is HealthState.RATE_LIMITED
    assert _eval(FetchResult(status=404))[0] is HealthState.DEAD
    assert _eval(FetchResult(status=410))[0] is HealthState.DEAD
    assert _eval(FetchResult(status=403))[0] is HealthState.DEGRADED
    assert _eval(FetchResult(status=500))[0] is HealthState.DEGRADED


def test_evaluate_network_failure_is_unverified_not_dead() -> None:
    """ネットワーク不成立（プロキシ遮断含む）はDEADでなくUNVERIFIED。"""
    state, note = _eval(FetchResult(status=0, error="proxy CONNECT 403"))
    assert state is HealthState.UNVERIFIED
    assert "proxy CONNECT 403" in note


def test_evaluate_permanent_redirect_to_other_host_is_moved() -> None:
    result = FetchResult(
        status=200,
        final_url="https://feeds.newhost.example/feed.xml",
        permanent_redirect=True,
        body_sample=RSS2_FRESH,
    )
    state, note = _eval(result)
    assert state is HealthState.MOVED
    assert "newhost" in note


def test_evaluate_same_host_redirect_is_not_moved() -> None:
    result = FetchResult(
        status=200,
        final_url="https://example.org/feed2.xml",
        permanent_redirect=True,
        body_sample=RSS2_FRESH,
    )
    assert _eval(result)[0] is HealthState.HEALTHY


def test_evaluate_html_response_is_degraded() -> None:
    state, note = _eval(FetchResult(status=200, body_sample=HTML_SAMPLE))
    assert state is HealthState.DEGRADED
    assert "html" in note


def test_evaluate_json_api_reachable_is_healthy() -> None:
    assert _eval(FetchResult(status=200, body_sample=JSON_SAMPLE))[0] is HealthState.HEALTHY


# ---------------------------------------------------------------- 観測レコード生成


def test_check_endpoint_builds_observation() -> None:
    transport = StubTransport(
        FetchResult(
            status=200,
            final_url="https://example.org/feed.xml",
            content_type="application/rss+xml",
            etag_present=True,
            body_sample=RSS2_FRESH,
        )
    )
    obs = check_endpoint(make_endpoint(), transport, now=NOW)
    assert transport.calls == ["https://example.org/feed.xml"]
    assert obs.state is HealthState.HEALTHY
    assert obs.source_id == "example_feed"
    assert obs.checked_at == NOW and obs.checked_at.tzinfo is not None
    assert obs.detected_format is FeedFormat.RSS2
    assert obs.latest_item_at == datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
    assert obs.freshness_age_hours == 27
    assert obs.health_obs_id.startswith("shealth_")
    assert obs.method == "live_http"


def test_check_endpoint_transport_exception_becomes_unverified() -> None:
    obs = check_endpoint(make_endpoint(), StubTransport(exc=OSError("connection reset")), now=NOW)
    assert obs.state is HealthState.UNVERIFIED
    assert obs.http_status == 0
    assert "connection reset" in obs.note


def test_observation_serialization_roundtrip() -> None:
    serialization.register_domain_types()
    obs = check_endpoint(
        make_endpoint(), StubTransport(FetchResult(status=200, body_sample=ATOM_SAMPLE)), now=NOW
    )
    decoded = serialization.decode(serialization.encode(obs))
    assert decoded == obs
    assert decoded.detected_format is FeedFormat.ATOM


def test_health_observation_rejects_naive_checked_at() -> None:
    with pytest.raises(ValueError):
        SourceHealthObservation(
            health_obs_id="shealth_X",
            source_id="s",
            checked_at=datetime(2026, 8, 29, 12, 0),  # naive
            state=HealthState.HEALTHY,
        )


def test_derive_current_state_returns_latest_observation() -> None:
    def obs_at(dt: datetime, state: HealthState) -> SourceHealthObservation:
        return SourceHealthObservation(
            health_obs_id=f"shealth_{dt.isoformat()}",
            source_id="s",
            checked_at=dt,
            state=state,
        )

    older = obs_at(NOW - timedelta(days=1), HealthState.HEALTHY)
    newer = obs_at(NOW, HealthState.DEGRADED)
    assert derive_current_state((older, newer)) is newer
    assert derive_current_state(()) is None
