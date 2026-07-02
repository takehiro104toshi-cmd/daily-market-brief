"""マクロ経済データ（FRED公開CSV、Trading Economics）。

- FRED (Federal Reserve Economic Data): fredgraph.csv エンドポイントは
  APIキー不要で公開されている
  （https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series_id>）。
  ベストエフォートで系列を取得し、失敗時は空リストとして扱う
  （呼び出し側で「取得不可」表示にする）。
- Trading Economics: 本格利用には公式のAPIキー登録が必要なため、ここでは
  公式サイトを参照リンクとしてのみ登録し、自動取得は行わない。
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from typing import List, Optional

from ..utils import SourceRegistry, safe_get

logger = logging.getLogger("market_brief")

FRED_CSV_URL_TEMPLATE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# ベストエフォート値。本番導入前に必ず動作確認すること（README参照）。
FRED_SERIES = [
    {"id": "T10Y2Y", "name": "米10年-2年金利差"},
    {"id": "UNRATE", "name": "米失業率"},
]

TRADING_ECONOMICS_URL = "https://tradingeconomics.com/calendar"
TRADING_ECONOMICS_LABEL = "Trading Economics(公式サイト・参照リンクのみ／自動取得なし)"


@dataclass
class MacroDataPoint:
    name: str
    value: str
    date: str
    source: str = "FRED"


def fetch_fred_series(
    sources: SourceRegistry,
    csv_url_template: Optional[str] = None,
    series_list: Optional[list] = None,
) -> List[MacroDataPoint]:
    """csv_url_template / series_list を指定すると既定のFREDエンドポイント・系列を
    上書きできる（テストで到達不能なローカルアドレスに差し替える用途を想定）。"""
    csv_url_template = csv_url_template or FRED_CSV_URL_TEMPLATE
    series_list = series_list if series_list is not None else FRED_SERIES
    results: List[MacroDataPoint] = []
    for series in series_list:
        url = csv_url_template.format(series_id=series["id"])
        resp = safe_get(url)
        if resp is None:
            continue
        try:
            reader = csv.reader(io.StringIO(resp.text))
            rows = [row for row in reader if row and row[0] != "DATE" and row[1] not in ("", ".")]
        except csv.Error as exc:
            logger.warning("FRED CSV解析失敗 (%s): %s", series["id"], exc)
            continue
        if not rows:
            continue
        last_date, last_value = rows[-1][0], rows[-1][1]
        sources.add(f"FRED: {series['name']}", url, "マクロ指標")
        results.append(MacroDataPoint(name=series["name"], value=last_value, date=last_date))
    return results


def register_trading_economics_reference(sources: SourceRegistry) -> None:
    sources.add(TRADING_ECONOMICS_LABEL, TRADING_ECONOMICS_URL, "参照リンク")


def fetch_macro_data(
    sources: SourceRegistry,
    csv_url_template: Optional[str] = None,
    series_list: Optional[list] = None,
) -> List[MacroDataPoint]:
    register_trading_economics_reference(sources)
    return fetch_fred_series(sources, csv_url_template=csv_url_template, series_list=series_list)
