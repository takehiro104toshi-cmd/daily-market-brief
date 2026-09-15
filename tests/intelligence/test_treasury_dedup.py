"""P2-G.1 MINI TASK A: Treasury年ファイルの重複取得排除のテスト。

原則: **ONE SOURCE DOCUMENT MAY PRODUCE MULTIPLE OBSERVATIONS**
同一payloadを系列ごとにネットワーク再取得しない。ただしseries identityは
混ぜない（UST2Y_par ≠ UST10Y_par）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.intelligence.core.paths import market_bank_root
from src.intelligence.evidence_qa.policy import MARKET_OBSERVATION_V1
from src.intelligence.ingestion.model import FetchResponse
from src.intelligence.market.backfill import MarketBackfillEngine
from src.intelligence.market.ingest import build_observations
from src.intelligence.market.series_catalog import load_catalog
from src.intelligence.market.store import MarketBankStore
from src.intelligence.market.treasury_curve import TreasuryParYieldProvider

CATALOG = load_catalog(Path("knowledge/market_series/core_series.yaml"))
UST2Y = "rates:UST2Y_par.yield.closing.us"
UST10Y = "rates:UST10Y_par.yield.closing.us"
SPREAD = "rates:UST10Y_par_UST2Y_par.spread.derived_metric"
RETRIEVED = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

HEADER = ('Date,"1 Mo","2 Mo","3 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr",'
          '"7 Yr","10 Yr","20 Yr","30 Yr"')


def year_csv(year: int, days, *, two_y="4.34", ten_y="4.73"):
    lines = [HEADER]
    for i, d in enumerate(days):
        lines.append(f"{d.month:02d}/{d.day:02d}/{year},"
                     f"3.84,3.86,3.90,4.02,4.15,{two_y},4.41,4.48,4.59,{ten_y},5.21,5.22")
    return ("\n".join(lines) + "\n").encode()


def sessions(count, *, end=date(2026, 8, 28)):
    from datetime import timedelta
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


class CountingTransport:
    """年ごとの応答を返し、リクエスト回数を数えるtransport（失敗注入対応）。"""

    def __init__(self, bodies_by_year, *, fail_first: dict = None):
        self.bodies = bodies_by_year          # {year: bytes}
        self.fail_first = dict(fail_first or {})  # {year: 残り失敗回数}
        self.calls = []                        # 全リクエストURL

    def send(self, request, *, timeout=20.0):
        self.calls.append(request.url)
        year = next((y for y in self.bodies if f"/{y}/all" in request.url), None)
        if year is None:
            return FetchResponse(status_code=404, retrieved_at=RETRIEVED,
                                 error_kind="", body=b"not found")
        if self.fail_first.get(year, 0) > 0:
            self.fail_first[year] -= 1
            return FetchResponse(status_code=0, retrieved_at=RETRIEVED,
                                 error_kind="timeout",
                                 error_detail="TimeoutError: read timed out")
        return FetchResponse(status_code=200, final_url=request.url,
                             body=self.bodies[year], content_type="text/csv",
                             retrieved_at=RETRIEVED, elapsed_ms=7)

    def year_calls(self, year):
        return sum(1 for u in self.calls if f"/{year}/all" in u)


def spec(series_id):
    s = CATALOG.get(series_id)
    assert s is not None, series_id
    return s


def transport_2026(days=None, **kw):
    return CountingTransport({2026: year_csv(2026, days or sessions(30), **kw)})


class TestSinglePayloadMultipleSeries:
    def test_one_http_call_per_year_for_two_series(self):
        transport = transport_2026()
        provider = TreasuryParYieldProvider(transport)
        r2 = provider.fetch_daily_history(spec(UST2Y), start=date(2026, 1, 1),
                                          end=date(2026, 8, 28))
        r10 = provider.fetch_daily_history(spec(UST10Y), start=date(2026, 1, 1),
                                           end=date(2026, 8, 28))
        assert r2.ok and r10.ok
        assert transport.year_calls(2026) == 1        # 系列ごとに取り直さない
        assert r2.served_from_cache is False          # 初回は実取得
        assert r10.served_from_cache is True          # 2系列目はrun内再利用
        assert any("reused_run_cache_years:2026" in i for i in r10.parse_issues)

    def test_multi_year_fetches_each_year_once(self):
        transport = CountingTransport({
            2025: year_csv(2025, sessions(5, end=date(2025, 12, 31)),
                           two_y="3.47", ten_y="4.18"),
            2026: year_csv(2026, sessions(5)),
        })
        provider = TreasuryParYieldProvider(transport)
        for series_id in (UST2Y, UST10Y):
            assert provider.fetch_daily_history(
                spec(series_id), start=date(2025, 12, 1), end=date(2026, 8, 28)).ok
        assert transport.year_calls(2025) == 1
        assert transport.year_calls(2026) == 1
        assert len(transport.calls) == 2               # 合計2リクエスト（4ではない）

    def test_column_correctness_from_same_payload(self):
        transport = transport_2026()
        provider = TreasuryParYieldProvider(transport)
        r2 = provider.fetch_daily_history(spec(UST2Y), start=date(2026, 1, 1),
                                          end=date(2026, 8, 28))
        r10 = provider.fetch_daily_history(spec(UST10Y), start=date(2026, 1, 1),
                                           end=date(2026, 8, 28))
        assert {r.close for r in r2.records} == {"4.34"}
        assert {r.close for r in r10.records} == {"4.73"}

    def test_partial_column_missing_is_reported_not_guessed(self):
        # 10年債列を持たない年ファイル（同一payloadを2系列が読む状況で片方だけ欠落）
        body = ('Date,"2 Yr"\n08/28/2026,4.34\n08/27/2026,4.30\n').encode()
        transport = CountingTransport({2026: body})
        provider = TreasuryParYieldProvider(transport)
        ok = provider.fetch_daily_history(spec(UST2Y), start=date(2026, 8, 1),
                                          end=date(2026, 8, 28))
        assert ok.ok and {r.close for r in ok.records} == {"4.34", "4.30"}
        missing = provider.fetch_daily_history(spec(UST10Y), start=date(2026, 8, 1),
                                               end=date(2026, 8, 28))
        # 列が無ければ0件＋issue（欠落を推測で埋めない・他系列の値で代用しない）
        assert not missing.ok
        assert any("missing_column" in i for i in missing.parse_issues)
        assert transport.year_calls(2026) == 1  # 欠落判定のために再取得もしない


class TestPayloadRetry:
    def test_retry_once_at_payload_level(self):
        transport = CountingTransport({2026: year_csv(2026, sessions(5))},
                                      fail_first={2026: 1})
        provider = TreasuryParYieldProvider(transport)
        result = provider.fetch_daily_history(spec(UST2Y), start=date(2026, 1, 1),
                                              end=date(2026, 8, 28))
        assert result.ok                       # 1回の一時失敗は再試行で回復
        assert transport.year_calls(2026) == 2  # 初回＋再試行のみ

    def test_retry_is_bounded_and_failure_reported(self):
        transport = CountingTransport({2026: year_csv(2026, sessions(5))},
                                      fail_first={2026: 5})
        provider = TreasuryParYieldProvider(transport)
        result = provider.fetch_daily_history(spec(UST2Y), start=date(2026, 1, 1),
                                              end=date(2026, 8, 28))
        assert result.error_kind == "timeout"
        assert transport.year_calls(2026) == 2  # 無限retryしない
        # 失敗はキャッシュしない（次系列は再試行できる）
        assert provider._year_cache == {}

    def test_http_error_is_not_retried(self):
        transport = CountingTransport({})   # 全て404扱い
        provider = TreasuryParYieldProvider(transport)
        result = provider.fetch_daily_history(spec(UST2Y), start=date(2026, 1, 1),
                                              end=date(2026, 8, 28))
        assert result.error_kind == "http_error"
        assert len(transport.calls) == 1     # ステータス由来の失敗は再試行しない


class TestProvenanceAndIdentity:
    def _engine(self, tmp_path, transport):
        providers = {"treasury_gov": TreasuryParYieldProvider(transport)}
        store = MarketBankStore(market_bank_root(tmp_path))
        return MarketBackfillEngine(store, CATALOG, providers, MARKET_OBSERVATION_V1)

    def test_shared_raw_item_and_fetch_attempt_distinct_observations(self, tmp_path):
        days = sessions(30)
        transport = transport_2026(days)
        engine = self._engine(tmp_path, transport)
        run = engine.run(start=days[0], end=days[-1], series_ids=(UST2Y, UST10Y))
        by_id = {r.series_id: r for r in run.results}
        assert by_id[UST2Y].status == "success" and by_id[UST10Y].status == "success"

        # 同一source documentを共有（RawItem・FetchAttemptとも同一を参照）
        assert by_id[UST2Y].raw_item_id == by_id[UST10Y].raw_item_id != ""
        assert by_id[UST2Y].fetch_attempt_id == by_id[UST10Y].fetch_attempt_id != ""
        # 起きていない取得はFetchAttemptとして記録しない
        attempts = [a for a in engine.store.raw.iter_attempts()
                    if a.source_id == "treasury_gov"]
        assert len(attempts) == 1
        assert transport.year_calls(2026) == 1

        # NO IDENTITY MERGE: series identityは別・Observation IDも別・値も列ごと
        obs2 = engine.store.index.latest_trading_session(UST2Y)
        obs10 = engine.store.index.latest_trading_session(UST10Y)
        assert obs2["observation_id"] != obs10["observation_id"]
        assert obs2["series_id"] == UST2Y and obs10["series_id"] == UST10Y
        assert obs2["value"] == "4.34" and obs10["value"] == "4.73"
        assert obs2["unit"] == "pct" and obs10["unit"] == "pct"

    def test_spread_still_generated_from_shared_payload(self, tmp_path):
        days = sessions(30)
        engine = self._engine(tmp_path, transport_2026(days))
        engine.run(start=days[0], end=days[-1], series_ids=(UST2Y, UST10Y))
        spread = [o for o in engine.store.normalized.iter_observations()
                  if o.series_id == SPREAD]
        assert len(spread) == 30
        assert {str(o.value) for o in spread} == {"0.390000"}   # 4.73 - 4.34
        for row in spread:
            assert len(row.inputs) == 2
            assert row.calculation_method == "yield_spread:1.0.0"
            assert row.unit == "pct_point"

    def test_idempotent_rerun_adds_nothing(self, tmp_path):
        days = sessions(30)
        engine = self._engine(tmp_path, transport_2026(days))
        first = engine.run(start=days[0], end=days[-1], series_ids=(UST2Y, UST10Y))
        second = engine.run(start=days[0], end=days[-1], series_ids=(UST2Y, UST10Y))
        assert first.observations_added == 60
        assert second.observations_added == 0
        assert second.derived_added == 0

    def test_new_run_refetches_payload(self, tmp_path):
        """cache scopeはrun-local（恒久HTTP cacheではない）。"""
        days = sessions(5)
        transport = transport_2026(days)
        p1 = TreasuryParYieldProvider(transport)
        p1.fetch_daily_history(spec(UST2Y), start=days[0], end=days[-1])
        p2 = TreasuryParYieldProvider(transport)     # 別run相当
        p2.fetch_daily_history(spec(UST2Y), start=days[0], end=days[-1])
        assert transport.year_calls(2026) == 2

    def test_decimal_values_from_shared_payload(self):
        transport = transport_2026(sessions(3))
        provider = TreasuryParYieldProvider(transport)
        result = provider.fetch_daily_history(spec(UST10Y), start=date(2026, 1, 1),
                                              end=date(2026, 8, 28))
        outcome = build_observations(spec(UST10Y), result)
        assert {o.value for o in outcome.observations} == {Decimal("4.73")}
        assert all(o.series_id == UST10Y for o in outcome.observations)
