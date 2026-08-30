"""Data Bank query contract（Phase 2-A）。高度検索UIは作らない——契約と最小実装口のみ。

将来の検索要件（監督者指定）: date range / publisher / source / country / company /
ticker / theme / event type / importance / trust decision。
country〜themeは分類レコード（NewsClassification / EntityReference）が付き始める
P2-E以降に実データが入る。契約は今固定する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, Sequence, Tuple, runtime_checkable

from ..core.time import ensure_aware_or_none
from .news_model import NewsItem


@dataclass(frozen=True, kw_only=True)
class NewsQuery:
    """News Bank検索条件（全て任意・AND結合）。"""

    date_from: Optional[datetime] = None  # published_at範囲（aware必須）
    date_to: Optional[datetime] = None
    publisher: str = ""
    source_id: str = ""
    language: str = ""
    country: str = ""      # NewsClassification(dimension=country)
    company: str = ""
    ticker: str = ""
    theme: str = ""
    event_type: str = ""
    trust_decisions: Tuple[str, ...] = field(default=())  # GateDecision value（例: ("accept",)）
    limit: int = 100

    def __post_init__(self) -> None:
        ensure_aware_or_none(self.date_from, "NewsQuery.date_from")
        ensure_aware_or_none(self.date_to, "NewsQuery.date_to")
        if self.limit <= 0:
            raise ValueError("limit must be positive")


@dataclass(frozen=True, kw_only=True)
class MarketQuery:
    """Market Bank検索条件。"""

    series_id: str = ""
    instrument_id: str = ""
    metric: str = ""
    date_from: Optional[datetime] = None  # as_of範囲
    date_to: Optional[datetime] = None
    kinds: Tuple[str, ...] = field(default=())  # raw / derived
    limit: int = 1000

    def __post_init__(self) -> None:
        ensure_aware_or_none(self.date_from, "MarketQuery.date_from")
        ensure_aware_or_none(self.date_to, "MarketQuery.date_to")


@runtime_checkable
class NewsQueryable(Protocol):
    """News Bank検索境界（実装: databank/sqlite_index.py参照実装）。"""

    def search_news(self, query: NewsQuery) -> Sequence[NewsItem]:  # pragma: no cover
        ...
