"""MarketContextWindow / TradingWindow（Phase 2-F PART F——Phase 3準備の型）。

TIMEZONE SAFETY: UTC暦日で雑にjoinしない。windowは**aware UTC時刻範囲**＋
（該当時）取引セッション日で表現し、変換はzoneinfo経由で行う。

- jst_morning_window       … 「日本の朝にブリーフを読む」文脈の時刻窓
- previous_us_session_window … 前米国セッション。**実データのtrading_dateから導出**
  （休日カレンダーを推測しない——bankに存在する直近セッションが正）
- same_japan_trading_day_window … 当日の東京現物セッション
- event_window             … イベント時刻の前後窓

causal分析はしない（同一windowのデータを取得できる契約まで）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

#: 東京現物セッション（market catalogのnikkei/topix定義と整合）
TOKYO_OPEN = time(9, 0)
TOKYO_CLOSE = time(15, 30)


@dataclass(frozen=True, kw_only=True)
class TradingWindow:
    """時刻窓（UTC・aware）＋文脈metadata。"""

    name: str
    start_utc: datetime
    end_utc: datetime
    trading_date: str = ""  # 該当する取引セッション日（"YYYY-MM-DD"。無関係なら空）
    session: str = ""       # "tokyo" / "us" / "" 等
    note: str = ""

    def __post_init__(self) -> None:
        if self.start_utc.tzinfo is None or self.end_utc.tzinfo is None:
            raise ValueError("TradingWindow requires aware datetimes")
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")

    def contains(self, ts: datetime) -> bool:
        return self.start_utc <= ts.astimezone(timezone.utc) <= self.end_utc


def jst_morning_window(day: date, *, start_hour: int = 6, end_hour: int = 9) -> TradingWindow:
    """JST朝の閲覧窓（既定6:00-9:00 JST）。夏時間なし（JSTは通年UTC+9）。"""
    start = datetime.combine(day, time(start_hour, 0), tzinfo=JST)
    end = datetime.combine(day, time(end_hour, 0), tzinfo=JST)
    return TradingWindow(
        name=f"jst_morning:{day.isoformat()}",
        start_utc=start.astimezone(timezone.utc),
        end_utc=end.astimezone(timezone.utc),
        session="", note="日本の朝の閲覧窓（セッションではなく閲覧文脈）")


def same_japan_trading_day_window(day: date) -> TradingWindow:
    """当日の東京現物セッション（9:00-15:30 JST）。祝日判定はしない
    （実データ有無はquery結果が示す——欠測を補完しない原則と同型）。"""
    start = datetime.combine(day, TOKYO_OPEN, tzinfo=JST)
    end = datetime.combine(day, TOKYO_CLOSE, tzinfo=JST)
    return TradingWindow(
        name=f"tokyo_session:{day.isoformat()}",
        start_utc=start.astimezone(timezone.utc),
        end_utc=end.astimezone(timezone.utc),
        trading_date=day.isoformat(), session="tokyo")


def previous_us_session_window(
    market_index, series_id: str, *, before_jst_date: date,
    span_hours: int = 24,
) -> Optional[TradingWindow]:
    """JST日付Dの朝に見る「前の米国セッション」を**実データから**導出する。

    bank内の当該series（例: index:spx.close.closing.us）で、
    trading_date < D のうち最新のセッションを取り、そのas_ofを終端とする窓を返す。
    休日・半日立会を推測せず、データが無ければNone（正直な欠測）。
    """
    rows = market_index.query(series_id=series_id,
                              date_to=(before_jst_date - timedelta(days=1)).isoformat(),
                              kind="raw")
    if not rows:
        return None
    last = rows[-1]  # trading_date昇順の末尾=直近セッション
    end = datetime.fromisoformat(last["as_of_utc"])
    return TradingWindow(
        name=f"previous_us_session:{last['trading_date']}",
        start_utc=end - timedelta(hours=span_hours),
        end_utc=end,
        trading_date=last["trading_date"], session="us",
        note=f"実データ導出（{series_id}の直近セッション。休日推測なし）")


def event_window(ts: datetime, *, before: timedelta, after: timedelta,
                 name: str = "") -> TradingWindow:
    """イベント時刻の前後窓（例: 発表前1h〜後24h）。"""
    if ts.tzinfo is None:
        raise ValueError("event timestamp must be aware")
    ts_utc = ts.astimezone(timezone.utc)
    return TradingWindow(
        name=name or f"event:{ts_utc.isoformat()}",
        start_utc=ts_utc - before, end_utc=ts_utc + after)
