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
    """AI Executive Summary（レポート冒頭・今日最重要ニュース）の1件分。

    beneficiary_stocks / negative_stocks / strategist_view は
    「岡三ストラテジスト視点」パイプライン向けに追加したフィールド
    （デフォルト値付きのため既存の呼び出し箇所にも影響しない）。
    """

    rank: int
    headline: Headline
    stars: str
    conclusion: str
    reason: str
    jp_stock_impact: str
    usdjpy_impact: str
    rate_impact: str
    sales_talk: str
    beneficiary_stocks: str = ""
    negative_stocks: str = ""
    strategist_view: str = ""


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
    ランキング」向けに追加したフィールド。beneficiary_tickers /
    negative_tickers は「岡三ストラテジスト視点」パイプライン向けに追加した、
    このニュースの恩恵銘柄・悪影響銘柄（ティッカー）。
    いずれもデフォルト値付きのため、既存の呼び出し箇所（これらを指定しない
    構築）にも影響しない。
    """

    rank: int
    stars: str
    headline: Headline
    is_top_pick: bool = False
    reason: str = ""
    affected_market: str = ""
    affected_sector: str = ""
    sales_talk: str = ""
    beneficiary_tickers: List[str] = field(default_factory=list)
    negative_tickers: List[str] = field(default_factory=list)


@dataclass
class StarScoreBreakdown:
    """ニュース重要度の8軸★スコア（各1〜5）。

    「羅針盤」資料から学習したストラテジストの評価軸を一般化し、
    ①市場インパクト ②継続性 ③営業利用価値 ④日本株影響度 ⑤米国株影響度
    ⑥個別株へ展開できるか ⑦テーマ株へ展開できるか ⑧今後数週間重要か
    の8項目でニュースを評価する、ルールベースの機械的スコアリング。
    """

    market_impact: int
    continuity: int
    sales_value: int
    jp_impact: int
    us_impact: int
    stock_expansion: int
    theme_expansion: int
    weeks_ahead: int

    @property
    def total(self) -> int:
        return (
            self.market_impact
            + self.continuity
            + self.sales_value
            + self.jp_impact
            + self.us_impact
            + self.stock_expansion
            + self.theme_expansion
            + self.weeks_ahead
        )

    @property
    def overall_stars(self) -> int:
        avg = self.total / 8
        return min(5, max(1, round(avg)))


@dataclass
class StrategistView:
    """「岡三ストラテジスト視点」パイプラインの1ニュース分。

    ニュース → 岡三ストラテジストならどう見るか → 重要テーマ →
    関連セクター → 恩恵銘柄 → 悪影響銘柄 → 営業で話すポイント → 重要度、
    という処理順で整理した結果を保持する。あくまで公開見出しとルールベースの
    因果チェーン設定（config.yaml の causal_rules）から機械的に導いた
    考察であり、断定的な投資助言ではない。
    """

    headline: Headline
    strategist_take: str
    theme: str
    related_sector: str
    beneficiary_names: List[str] = field(default_factory=list)
    negative_names: List[str] = field(default_factory=list)
    sales_point: str = ""
    importance_stars: str = ""
    score: Optional[StarScoreBreakdown] = None


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
class MegatrendEntry:
    """「Future Intelligence Engine」の「世界のメガトレンド」1テーマ分。

    stars / phase / continuity は、本日の関連見出し件数と durable_themes
    への該当有無から機械的に導いた定性的なラベルであり、具体的な残り年数・
    市場規模等の断定的な数値は含まない。
    """

    label: str
    stars: str
    headline_count: int
    why_growing: str
    phase: str  # 黎明期 / 成長初期 / 急成長期 / 成熟期 / 減速期
    continuity: str  # 高い / 中程度 / 限定的


@dataclass
class IndustryMomentumEntry:
    """「次に来る業界」ランキングの1件（本日のモメンタム順）。"""

    rank: int
    label: str
    headline_count: int
    reason: str


@dataclass
class SupplyChainNote:
    """「サプライチェーン分析」の1件（causal_rulesの因果チェーンをそのまま表示）。"""

    theme: str
    chain_text: str


@dataclass
class HorizonThemeGroup:
    """「中長期テーマ」の1期間分（半年／1年／3年／5年／10年）。"""

    horizon: str
    themes: List[str] = field(default_factory=list)


@dataclass
class JpStockImpactEntry:
    """「日本株への波及」の1テーマ分（恩恵銘柄。大型/中小型は区分不明として明記）。"""

    theme: str
    beneficiary_names: List[str] = field(default_factory=list)
    cap_note: str = "大型・中小型の区分は時価総額データ未取得のため区分不明です。"


@dataclass
class ThemeMomentumEntry:
    """「Theme Momentum Score」の1テーマ分（v1.1）。

    momentum_score（0〜100）は、本日の関連見出し件数・重要ニュースとの一致・
    causal_rules該当・durable_themes該当という既存シグナルのみから機械的に
    算出する。前日比・週次比較は行わない（履歴データを保持していないため）。
    """

    label: str
    momentum_score: int
    momentum_label: str  # 急加速 / 加速 / 横ばい / 減速
    reason: str


@dataclass
class EarlySignalEntry:
    """「Early Signal Detection」の1テーマ分（v1.1）。

    本日の見出し件数はまだ少ないが、causal_rules該当・durable_themes該当・
    恩恵銘柄が解決できる、という条件をすべて満たすテーマを「初動シグナル」
    として抽出する。
    """

    label: str
    stars: str
    reason: str
    related_sector: str
    beneficiary_names: List[str] = field(default_factory=list)


@dataclass
class FutureIntelligenceBundle:
    """「Future Intelligence Engine」の計算結果一式。

    v1.0: megatrends / industry_momentum / supply_chains / horizon_groups /
    jp_stock_impact（グループAのみ）。
    v1.1: theme_momentum（Theme Momentum Score）/ early_signals
    （Early Signal Detection）を追加。
    テーマ成熟度・国家戦略分析・世界のお金の流れはさらに先の版に見送り、
    本バンドルには含まない。
    """

    megatrends: List[MegatrendEntry] = field(default_factory=list)
    industry_momentum: List[IndustryMomentumEntry] = field(default_factory=list)
    supply_chains: List[SupplyChainNote] = field(default_factory=list)
    horizon_groups: List[HorizonThemeGroup] = field(default_factory=list)
    jp_stock_impact: List[JpStockImpactEntry] = field(default_factory=list)
    theme_momentum: List[ThemeMomentumEntry] = field(default_factory=list)
    early_signals: List[EarlySignalEntry] = field(default_factory=list)


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
    strategist_views: List[StrategistView] = field(default_factory=list)
    future_intelligence: FutureIntelligenceBundle = field(default_factory=FutureIntelligenceBundle)
