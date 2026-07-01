"""指数・為替・金利・コモディティ・個別銘柄の株価データ収集。

一次ソースは yfinance（Yahoo Finance の公開マーケットデータAPI）。
取得に失敗した場合は Stooq の公開CSVエンドポイントにフォールバックする。
どちらも失敗した場合は None を保持したまま返し、レポート側で
「データ取得不可」と明示する（推測値で埋めない）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from io import StringIO
from typing import Optional

import pandas as pd

from ..utils import SourceRegistry, safe_get

logger = logging.getLogger("market_brief")

try:
    import yfinance as yf
except ImportError:  # yfinance未インストールでも他機能は動かせるようにする
    yf = None

STOOQ_CSV_URL = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"


@dataclass
class Quote:
    name: str
    symbol: str
    price: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]
    source_label: str
    source_url: str


def _fetch_yfinance(symbol: str) -> Optional[dict]:
    if yf is None:
        return None
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if hist.empty or len(hist) < 2:
            return None
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        change = last - prev
        change_pct = (change / prev * 100) if prev else None
        return {"price": last, "change": change, "change_pct": change_pct}
    except Exception as exc:
        logger.warning("yfinance取得失敗 %s: %s", symbol, exc)
        return None


def _fetch_stooq(stooq_symbol: str) -> Optional[dict]:
    resp = safe_get(STOOQ_CSV_URL.format(symbol=stooq_symbol))
    if resp is None:
        return None
    try:
        df = pd.read_csv(StringIO(resp.text))
        if df.empty or "Close" not in df.columns:
            return None
        row = df.iloc[0]
        close = float(row["Close"])
        open_ = float(row["Open"])
        change = close - open_
        change_pct = (change / open_ * 100) if open_ else None
        return {"price": close, "change": change, "change_pct": change_pct}
    except Exception as exc:
        logger.warning("Stooq取得失敗 %s: %s", stooq_symbol, exc)
        return None


def fetch_quote(
    name: str,
    symbol: str,
    stooq_symbol: Optional[str],
    sources: SourceRegistry,
    category: str,
) -> Quote:
    data = _fetch_yfinance(symbol)
    source_label = "Yahoo Finance"
    source_url = f"https://finance.yahoo.com/quote/{symbol}"

    if data is None and stooq_symbol:
        data = _fetch_stooq(stooq_symbol)
        source_label = "Stooq"
        source_url = f"https://stooq.com/q/?s={stooq_symbol}"

    if data is None:
        data = {"price": None, "change": None, "change_pct": None}

    sources.add(source_label, source_url, category)
    return Quote(
        name=name,
        symbol=symbol,
        price=data["price"],
        change=data["change"],
        change_pct=data["change_pct"],
        source_label=source_label,
        source_url=source_url,
    )


def _fetch_group(items: list, sources: SourceRegistry, category: str) -> list[Quote]:
    return [
        fetch_quote(item["name"], item["symbol"], item.get("stooq_symbol"), sources, category)
        for item in items
    ]


def fetch_market_overview(config: dict, sources: SourceRegistry) -> dict:
    """主要指標・為替・金利・コモディティをまとめて取得する。"""
    return {
        "indices": _fetch_group(config.get("indices", []), sources, "主要指標"),
        "forex": _fetch_group(config.get("forex", []), sources, "為替"),
        "rates": _fetch_group(config.get("rates", []), sources, "金利"),
        "commodities": _fetch_group(config.get("commodities", []), sources, "コモディティ"),
    }


def fetch_watchlist_quotes(config: dict, sources: SourceRegistry) -> dict:
    """config.yaml の watchlist に登録された個別銘柄の株価を取得する。"""
    watchlist = config.get("watchlist", {})
    jp = [
        fetch_quote(item["name"], item["ticker"], None, sources, "日本株")
        for item in watchlist.get("jp_stocks", [])
    ]
    us = [
        fetch_quote(item["name"], item["ticker"], None, sources, "米国株")
        for item in watchlist.get("us_stocks", [])
    ]
    return {"jp_stocks": jp, "us_stocks": us}
