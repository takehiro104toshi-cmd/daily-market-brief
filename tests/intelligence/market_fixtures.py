"""P2-D市場データテスト共通フィクスチャ（オフライン決定論）。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.intelligence.ingestion.model import FetchRequest
from src.intelligence.ingestion.transport import DEFAULT_TIMEOUT
from src.intelligence.market.providers import (
    ProviderFetchResult,
    StooqDailyHistoryProvider,
    parse_stooq_daily_csv,
)
from src.intelligence.market.series_catalog import load_catalog

#: 全テスト共通の基準時刻（決定論。now()は使わない）
RETRIEVED = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)

#: Stooq実応答と同形式の日足CSV（金曜8/28まで。値はテスト用の架空値）
NIKKEI_CSV = b"""Date,Open,High,Low,Close,Volume
2026-08-24,38900.10,39000.00,38800.00,38975.55,1234500
2026-08-25,38980.00,39100.25,38950.00,39050.10,1200000
2026-08-26,39060.00,39200.00,39000.00,39180.75,1150000
2026-08-27,39150.00,39300.50,39100.00,39250.00,1100000
2026-08-28,39260.00,39400.00,39200.00,39310.25,1050000
"""

UST10Y_CSV = b"""Date,Open,High,Low,Close
2026-08-24,4.240,4.260,4.230,4.254
2026-08-25,4.250,4.270,4.240,4.261
2026-08-26,4.260,4.280,4.250,4.275
2026-08-27,4.270,4.290,4.255,4.268
2026-08-28,4.265,4.285,4.250,4.270
"""


def catalog():
    return load_catalog(Path("knowledge/market_series/core_series.yaml"))


def spec_for(series_id: str):
    spec = catalog().get(series_id)
    assert spec is not None, series_id
    return spec


class StubTransport:
    """URL→(status, body) 固定応答のHttpTransport（オフライン）。"""

    def __init__(self, responses):
        self.responses = responses  # {url_substring: (status, bytes)}
        self.requests = []

    def send(self, request: FetchRequest, *, timeout: float = DEFAULT_TIMEOUT):
        from src.intelligence.ingestion.model import FetchResponse

        self.requests.append(request)
        for key, (status, body) in self.responses.items():
            if key in request.url:
                return FetchResponse(
                    status_code=status, final_url=request.url, body=body,
                    content_type="text/csv", retrieved_at=RETRIEVED, elapsed_ms=5)
        return FetchResponse(
            status_code=0, retrieved_at=RETRIEVED, error_kind="dns",
            error_detail="stub: no response configured")


def stub_provider(responses) -> StooqDailyHistoryProvider:
    return StooqDailyHistoryProvider(StubTransport(responses))


def fetch_result_from_csv(spec, body: bytes, provider_id: str = "stooq") -> ProviderFetchResult:
    """CSV→ProviderFetchResult（transport経由せず直接組み立てる近道）。"""
    records, issues = parse_stooq_daily_csv(body)
    return ProviderFetchResult(
        provider_id=provider_id, series_id=spec.series_id,
        symbol=spec.symbol_for(provider_id) or "stub",
        url="https://stooq.com/q/d/l/?s=stub&i=d",
        status_code=200, retrieved_at=RETRIEVED, body=body,
        records=records, parse_issues=issues)
