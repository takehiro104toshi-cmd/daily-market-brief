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
class TopPickEntry:
    """朝会向け「今日の注目5銘柄」の1件分（日本株・米国株それぞれTOP5）。

    コード・企業名は quote.symbol / quote.name を使う。
    material / short_term はv4で追加した「注目材料」「短期見通し」
    （デフォルト値付きのため既存呼び出し箇所にも影響しない）。
    """

    rank: int
    quote: Quote
    stars: str
    reason: str
    material: str = ""
    short_term: str = ""


@dataclass
class InstrumentScenario:
    """個別指標（日経平均／ドル円／米国市場）ごとの短いシナリオ見立て。

    bull_text / neutral_text / bear_text は v4で追加した、指標ごとの
    強気/中立/弱気3シナリオ（デフォルト値付きのため既存呼び出し箇所にも影響しない）。
    """

    label: str
    outlook: str
    key_driver: str
    bull_text: str = ""
    neutral_text: str = ""
    bear_text: str = ""


@dataclass
class ExecutiveSummaryItem:
    """AI Executive Summary（レポート冒頭・今日最重要ニュース）の1件分。"""

    rank: int
    headline: Headline
    stars: str
    conclusion: str
    reason: str
    jp_stock_impact: str
    usdjpy_impact: str
    rate_impact: str
    sales_talk: str


@dataclass
class CallPriorityEntry:
    """「今日電話すべき顧客」の1顧客タイプ分。"""

    customer_type: str
    reason: str
    topic: str
    sales_talk: str


@dataclass
class MarketImpactEntry:
    """「マーケットインパクト」の1対象分（指数・セクターへの影響度・方向）。"""

    target: str
    stars: str
    direction: str  # "プラス" / "マイナス" / "中立"


@dataclass
class SectorStrengthEntry:
    """「セクターランキング」の1業種分（本日の強弱予測・矢印＋理由）。"""

    label: str
    arrow: str  # "↑" / "→" / "↓"
    reason: str


@dataclass
class MorningMeetingComment:
    """「朝会コメント」の3パターン（30秒・1分・3分）。"""

    short_30s: str = ""
    medium_1min: str = ""
    long_3min: str = ""


@dataclass
class OkasanSalesComments:
    """「岡三証券営業向けコメント」セクション向けの顧客タイプ別トーク。

    富裕層・法人・NISA・退職金・相続の5顧客タイプ、各約30秒で話せる長さ。
    """

    wealthy: str = ""
    corporate: str = ""
    nisa: str = ""
    retirement: str = ""
    inheritance: str = ""


@dataclass
class WatchlistEntry:
    quote: Quote
    today: str
    next_week: str
    next_month: str
    long_term: str
    risk: str = ""


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
    sales_talk: str = ""


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
class SalesComments:
    """「営業向けコメント」セクション向けの7オーディエンス別トーク（各約30秒で話せる長さ）。"""

    corporate: str = ""
    wealthy: str = ""
    retail: str = ""
    nisa_beginner: str = ""
    fx_interested: str = ""
    us_stock_interested: str = ""
    jp_stock_interested: str = ""


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
    sales_comments: SalesComments = field(default_factory=SalesComments)
    expanded_qa: List[QAItem] = field(default_factory=list)
    top_picks: Dict[str, List[TopPickEntry]] = field(default_factory=lambda: {"jp": [], "us": []})
    instrument_scenarios: List[InstrumentScenario] = field(default_factory=list)
    okasan_sales_comments: OkasanSalesComments = field(default_factory=OkasanSalesComments)
    executive_summary: List[ExecutiveSummaryItem] = field(default_factory=list)
    call_priorities: List[CallPriorityEntry] = field(default_factory=list)
    market_impact: List[MarketImpactEntry] = field(default_factory=list)
    sector_strength: List[SectorStrengthEntry] = field(default_factory=list)
    morning_meeting_comment: MorningMeetingComment = field(default_factory=MorningMeetingComment)
