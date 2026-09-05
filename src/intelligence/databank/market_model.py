"""Market Data Bankドメインモデル（Phase 2-A / schema 0.3.0）。

Market Observation（P1-A）を長期保存・検索するためのseries参照モデル。

区別を型で強制する:
- **MarketSeries** … 系列のidentity（instrument×metric×観測種別×市場セッション）。
  同じUSDJPYでも spot / Tokyo close / NY close は**別series**（雑に同一視しない）。
- ObservationType … closing / intraday quote / official fixing /
  economic statistic / derived metric の区別。
- 巨大hardcode一覧は作らない（seriesはreference modelとして必要都度定義。
  正規カタログ化はP2-D。ここでは決定論的なseries_id導出規約を定める）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from ..core.types import SCHEMA_VERSION


class ObservationType(str, Enum):
    CLOSING = "closing"                    # 終値観測
    INTRADAY_QUOTE = "intraday_quote"      # ザラ場quote
    OFFICIAL_FIXING = "official_fixing"    # 公式フィキシング（仲値等）
    ECONOMIC_STATISTIC = "economic_statistic"  # 経済統計
    DERIVED_METRIC = "derived_metric"      # 派生指標（MA乖離等）


def make_series_id(
    instrument_id: str, metric: str, observation_type: str, market_session: str = ""
) -> str:
    """決定論的series_id。例:
    index:nikkei225 / close / closing / tokyo → "index:nikkei225.close.closing.tokyo"
    fx:USDJPY / rate / intraday_quote / ""    → "fx:USDJPY.rate.intraday_quote"
    """
    parts = [instrument_id, metric, observation_type]
    if market_session:
        parts.append(market_session)
    return ".".join(parts)


@dataclass(frozen=True, kw_only=True)
class MarketSeries:
    """市場系列のidentity（Observationはseries_idでここへ紐づく）。"""

    series_id: str
    instrument_id: str  # 例: "index:nikkei225", "fx:USDJPY", "rates:UST10Y", "macro:jp_cpi"
    metric: str  # 例: "close", "rate", "yield", "yoy_pct"
    observation_type: ObservationType
    market_session: str = ""  # 例: "tokyo", "ny", "london"。統計等は空
    unit: str = ""
    currency: str = ""
    description: str = ""
    preferred_source_ids: Tuple[str, ...] = ()  # 取得優先順（カタログslug）
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.instrument_id or not self.metric:
            raise ValueError("instrument_id / metric are required")
        expected = make_series_id(
            self.instrument_id, self.metric, self.observation_type.value, self.market_session
        )
        if self.series_id != expected:
            raise ValueError(
                f"series_idは規約から導出すること: expected={expected} got={self.series_id}"
            )
