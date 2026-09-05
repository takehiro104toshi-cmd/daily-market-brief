"""P2-F: TradingWindow・cross-domain window query・timezone安全のテスト。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.intelligence.databank.cross_domain import fetch_window_slice
from src.intelligence.databank.market_window import (
    event_window,
    jst_morning_window,
    previous_us_session_window,
    same_japan_trading_day_window,
)
from src.intelligence.databank.query import NewsQuery
from src.intelligence.databank.sqlite_index import SqliteNewsIndex
from src.intelligence.evidence_qa.policy import HISTORICAL_V1
from src.intelligence.market.backfill import MarketBackfillEngine
from src.intelligence.market.store import MarketBankStore

from .enrichment_fixtures import make_engine, make_item, NOW
from .market_fixtures import NIKKEI_CSV, RETRIEVED, catalog, stub_provider

SPX = "index:spx.close.closing.us"
NIKKEI = "index:nikkei225.close.closing.tokyo"

#: 米指数の合成CSV（NIKKEI_CSVと同じ日付・別値）
SPX_CSV = b"""Date,Close
2026-08-24,7650.10
2026-08-25,7660.20
2026-08-26,7671.30
2026-08-27,7680.40
2026-08-28,7711.75
"""


def _market(tmp_path) -> MarketBankStore:
    store = MarketBankStore(tmp_path / "market")
    MarketBackfillEngine(
        store, catalog(),
        stub_provider({"s=^nkx": (200, NIKKEI_CSV), "s=^spx": (200, SPX_CSV)}),
        HISTORICAL_V1,
    ).run(start=date(2026, 8, 1), end=date(2026, 8, 29), now=RETRIEVED,
          series_ids=(NIKKEI, SPX), with_derivations=False)
    return store


class TestTradingWindows:
    def test_jst_morning_is_utc_aware(self):
        w = jst_morning_window(date(2026, 8, 29))
        # 6:00-9:00 JST = 前日21:00-当日0:00 UTC（UTC暦日join禁止の実例）
        assert w.start_utc == datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
        assert w.end_utc == datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)

    def test_tokyo_session_window(self):
        w = same_japan_trading_day_window(date(2026, 8, 28))
        assert w.trading_date == "2026-08-28" and w.session == "tokyo"
        assert w.start_utc == datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
        assert w.end_utc == datetime(2026, 8, 28, 6, 30, tzinfo=timezone.utc)

    def test_previous_us_session_from_real_data(self, tmp_path):
        store = _market(tmp_path)
        # 8/29(土)のJST朝に見る「前の米国セッション」= データ上の8/28
        w = previous_us_session_window(store.index, SPX,
                                       before_jst_date=date(2026, 8, 29))
        assert w is not None and w.trading_date == "2026-08-28"
        assert w.session == "us"
        # 休日推測なし: データが無い期間はNone
        assert previous_us_session_window(store.index, SPX,
                                          before_jst_date=date(2026, 8, 24)) is None

    def test_event_window_requires_aware(self):
        import pytest
        with pytest.raises(ValueError, match="aware"):
            event_window(datetime(2026, 8, 28, 12, 0),
                         before=timedelta(hours=1), after=timedelta(hours=24))


class TestCrossDomainSlice:
    def test_same_window_news_and_market(self, tmp_path):
        market = _market(tmp_path)
        engine = make_engine(tmp_path)
        published = datetime(2026, 8, 28, 5, 0, tzinfo=timezone.utc)  # 東京セッション中
        inside = make_item("Nikkei rallies as chip stocks surge", published=published)
        outside = make_item("Old story", published=published - timedelta(days=10))
        news_index = SqliteNewsIndex(tmp_path / "news.sqlite3")
        news_index.index_news_items([inside, outside])
        for item in (inside, outside):
            engine.enrich_item(item, now=NOW)
        news_index.index_classifications(list(engine.store.iter_classifications()))

        w = same_japan_trading_day_window(date(2026, 8, 28))
        piece = fetch_window_slice(news_index, market.index, w,
                                   series_ids=(NIKKEI, SPX))
        assert [n.news_item_id for n in piece.news_items] == [inside.news_item_id]
        # trading_dateで紐付け（UTC暦日ではなくセッション日——TIMEZONE SAFETY）
        assert {o["series_id"] for o in piece.observations} == {NIKKEI, SPX}
        assert all(o["trading_date"] == "2026-08-28" for o in piece.observations)
        assert "no causal analysis" in piece.note  # 分析はしない（取得まで）

    def test_time_window_without_trading_date(self, tmp_path):
        market = _market(tmp_path)
        news_index = SqliteNewsIndex(tmp_path / "news.sqlite3")
        w = event_window(datetime(2026, 8, 28, 6, 0, tzinfo=timezone.utc),
                         before=timedelta(hours=1), after=timedelta(hours=1))
        piece = fetch_window_slice(news_index, market.index, w, series_ids=(NIKKEI,))
        # as_of=06:30Z（15:30 JST）が窓内
        assert [o["trading_date"] for o in piece.observations] == ["2026-08-28"]
