"""analysis/ 配下の各モジュールが共有するデータクラス群。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..collectors.market_data import Quote
from ..collectors.news import Headline


@dataclass
class ScenarioForecast:
    """強気・中立・弱気の3シナリオ確率予測。

    bull_reason 等は「④ AIシナリオ分析強化」向けに追加した、
    シナリオごとの理由・注目指標。既存呼び出し箇所との後方互換のため
    デフォルト値付き（未指定でも従来通り動作する）。
    """

    bull_pct: int
    neutral_pct: int
    bear_pct: int
    reasoning: str
    bull_reason: str = ""
    neutral_reason: str = ""
    bear_reason: str = ""
    bull_indicator: str = ""
    neutral_indicator: str = ""
    bear_indicator: str = ""


@dataclass
class ThemeForecast:
    rank: int
    label: str
    stars: str
    why_now: str
    outlook_1w: str
    outlook_1m: str
    outlook_3m: str
    headlines: List[Headline] = field(default_factory=list)


@dataclass
class SectorRankingEntry:
    rank: int
    label: str
    stars: str
    tailwind: List[Headline] = field(default_factory=list)
    headwind: List[Headline] = field(default_factory=list)
    related: List[Quote] = field(default_factory=list)
    related_unresolved: List[str] = field(default_factory=list)
    sales_talk: str = ""


@dataclass
class StockRankingEntry:
    rank: int
    quote: Quote
    stars: str
    short_term: str
    mid_term: str
    long_term: str


@dataclass
class WatchlistEntry:
    quote: Quote
    today: str
    next_week: str
    next_month: str
    long_term: str


@dataclass
class LongTermPick:
    rank: int
    quote: Quote
    reasoning: str


@dataclass
class NewsRankingItem:
    """TOPニュースランキングの1件。

    reason / affected_market / affected_sector は「② 今日の重要ニュース
    ランキング」向けに追加したフィールド。デフォルト値付きのため、
    既存の呼び出し箇所（これらを指定しない構築）にも影響しない。
    """

    rank: int
    stars: str
    headline: Headline
    is_top_pick: bool = False
    reason: str = ""
    affected_market: str = ""
    affected_sector: str = ""


@dataclass
class EventsBreakdown:
    today: List[str] = field(default_factory=list)
    this_week: List[str] = field(default_factory=list)
    this_month: List[str] = field(default_factory=list)


@dataclass
class SalesTalkBullets:
    corporate: List[str] = field(default_factory=list)
    retail: List[str] = field(default_factory=list)
    beginner: List[str] = field(default_factory=list)
    wealthy: List[str] = field(default_factory=list)


@dataclass
class KeyLevelEntry:
    """「今日見るべき指標」の1件（為替・VIX・米10年・WTI・Goldなど）。"""

    label: str
    quote: Optional[Quote]
    key_line: Optional[float]
    note: str


@dataclass
class WatchlistQuickEntry:
    """「今日のウォッチリスト」の1件（★評価＋1行理由）。"""

    quote: Quote
    stars: str
    reason: str


@dataclass
class GlossaryItem:
    term: str
    explanation: str


@dataclass
class QAItem:
    question: str
    answer: str


@dataclass
class SalesPrep:
    """「営業準備」セクション向けの営業マン支援コンテンツ一式。"""

    ceo_lines: List[str] = field(default_factory=list)
    wealthy_topics: List[str] = field(default_factory=list)
    beginner_glossary: List[GlossaryItem] = field(default_factory=list)
    casual_topics: List[str] = field(default_factory=list)
    qa: List[QAItem] = field(default_factory=list)


@dataclass
class AnalysisBundle:
    """全AI分析モジュールの計算結果をまとめ、builder.pyへ渡すための入れ物。"""

    scenario: ScenarioForecast
    news_ranking: List[NewsRankingItem]
    causal_chain_text: str
    causal_chains: List[str]
    theme_forecasts: List[ThemeForecast]
    sector_ranking: List[SectorRankingEntry]
    stock_ranking: Dict[str, List[StockRankingEntry]]
    watchlist_analysis: Dict[str, List[WatchlistEntry]]
    watchlist_quicklist: Dict[str, List[WatchlistQuickEntry]]
    long_term_picks: List[LongTermPick]
    sales_talk_bullets: SalesTalkBullets
    sales_talk_text: str
    sales_prep: SalesPrep
    key_levels: List[KeyLevelEntry]
    chat_topics: List[str]
    events: EventsBreakdown
    ai_summary_text: str
