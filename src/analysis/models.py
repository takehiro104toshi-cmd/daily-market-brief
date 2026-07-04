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
    """「Theme Momentum Score」の1テーマ分（v1.1、v1.4で信号を拡張）。

    momentum_score（0〜100）は、本日の関連見出し件数・重要ニュースとの一致・
    Executive Summaryとの一致・causal_rules該当・durable_themes該当・
    関連セクター/関連銘柄の有無という既存シグナルのみから機械的に算出する。
    前日比・週次比較は行わない（履歴データを保持していないため）。
    related_sector / beneficiary_names は、既存のcausal_rules恩恵銘柄ロジック
    をそのまま流用した参考情報（v1.4で追加、デフォルト値付きのため既存の
    呼び出し箇所にも影響しない）。
    """

    label: str
    momentum_score: int
    momentum_label: str  # 急加速 / 加速 / 横ばい / 減速
    reason: str
    related_sector: str = ""
    beneficiary_names: List[str] = field(default_factory=list)


@dataclass
class EarlySignalEntry:
    """「Early Signal Detection」の1テーマ分（v1.1、v1.4で営業トークを追加）。

    本日の見出し件数はまだ少ないが、causal_rules該当・durable_themes該当・
    恩恵銘柄が解決できる、という条件をすべて満たすテーマを「初動シグナル」
    として抽出する。
    sales_talk は、関連セクター・関連銘柄という既存の実データのみから機械的に
    組み立てた営業向けの話しかけポイント（v1.4で追加、デフォルト値付きの
    ため既存の呼び出し箇所にも影響しない。具体的な数値の断定はしない）。
    """

    label: str
    stars: str
    reason: str
    related_sector: str
    beneficiary_names: List[str] = field(default_factory=list)
    sales_talk: str = ""


@dataclass
class ThemeMaturityNote:
    """「テーマ成熟度メモ」の1テーマ分。

    config.yaml の theme_maturity_notes に手動登録があればそれを優先表示する
    （source_label="登録情報"）。未登録の場合は、本日の関連見出し件数・
    durable_themes該当・causal_rules該当・恩恵銘柄という既存シグナルのみから
    ルールベースで導いた定性的なAI分析を表示する（source_label="AI分析"、
    具体的な市場規模・補助金額・企業名の断定はしない）。根拠となる信号が
    何もない場合は source_label="分析材料不足" とする（v1.3）。
    """

    label: str
    market_stage: str = "分析材料不足"
    market_size_note: str = "分析材料不足"
    adoption_note: str = "分析材料不足"
    competition_note: str = "分析材料不足"
    barrier_note: str = "分析材料不足"
    risk_note: str = "分析材料不足"
    basis: str = ""
    source_label: str = "分析材料不足"


@dataclass
class NationalStrategyNote:
    """「国家戦略メモ」の1国・地域分。

    config.yaml の national_strategy_notes に手動登録があればそれを優先表示
    する（source_label="登録情報"）。未登録の場合は、config.yaml の
    national_focus_areas（人手による重点分野の対応付け・AIによる生成では
    ない参考情報）と、本日のテーマ動向（既存シグナル）から、ルールベースで
    導いた定性的なAI分析を表示する（source_label="AI分析"、具体的な政策名・
    法案名・補助金額の断定はしない）。対象は日本／米国／中国／EU／インド／
    中東の6地域固定。根拠となる信号が何もない場合は source_label="分析材料不足"
    とする（v1.3）。
    """

    region: str
    focus_areas: List[str] = field(default_factory=list)
    policy_note: str = "分析材料不足"
    regulation_note: str = "分析材料不足"
    market_impact_note: str = "分析材料不足"
    basis: str = ""
    source_label: str = "分析材料不足"


@dataclass
class CapitalFlowNote:
    """「世界のお金の流れ（市場シグナルベース）」の1テーマ分（v1.5）。

    実際の資金流入額・機関投資家ポジションは取得していないため、公開市場
    データ（指数・為替・金利・コモディティ）とTheme Momentum Score・
    Early Signal Detection・Sector Ranking・causal_rules・durable_themesと
    いう既存シグナルのみから、資金の「向かいやすさ」を機械的に推定する
    （実際の資金フローの断定はしない。「資金が向かいやすい」「物色されやすい」
    等の非断定表現に統一し、「資金が流入している」「◯億円流入」等の断定・
    捏造した金額は生成しない）。
    """

    label: str
    direction_label: str  # 流入しやすい／中立／流出しやすい／判断材料不足
    reason: str
    related_themes: List[str] = field(default_factory=list)
    related_sectors: List[str] = field(default_factory=list)
    sales_talk: str = ""


@dataclass
class ThemeDiagnosisEntry:
    """テーマ別診断（Momentum→Lifecycle→Catalyst→Risk→Confidence）の1テーマ分（v1.6）。

    このシステムの最優先目的は、営業ツールではなく「世界の変化をいち早く
    察知し、長期の資産形成・投資判断に役立てる未来分析システム」であること
    を踏まえ、各macro_themeについてMomentum Score・Lifecycle（フェーズ・
    継続性）に加えて、Catalyst（加速要因）・Risk（失速要因）・Confidence
    Score（分析根拠の充実度）を提示する。

    Catalyst / Risk は、ニュース・Executive Summary・Theme Momentum・
    Early Signal・causal_rules・durable_themes・サプライチェーン（恩恵銘柄）
    ・国家戦略メモ・世界のお金の流れという既存シグナルのみから機械的に
    導いた「AI分析」であり、具体的な数値・政策名・企業業績の断定はしない。
    Confidence Score（0〜100）は「未来が当たる確率」ではなく、上記シグナルの
    うちいくつが実際に確認できたか（＝分析根拠の充実度）を表す。
    related_themes（v1.8）は、config.yaml の theme_relations（人手による
    テーマ同士の対応付け。AIによる生成・推定ではない）をそのまま表示する
    「関連テーマ」であり、新たな未来予測ロジックではない。
    """

    label: str
    momentum_score: int
    momentum_label: str
    phase: str
    continuity: str
    related_themes: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    confidence_score: int = 0
    confidence_basis: List[str] = field(default_factory=list)


@dataclass
class WatchlistIntelligenceEntry:
    """「Watchlist Intelligence」の1銘柄分（v1.7）。

    config.yaml の watchlist（jp_stocks / us_stocks）銘柄と、Future
    Intelligence Engineが算出したテーマ診断（Momentum・Lifecycle・
    Catalyst・Risk・Confidence）を、既存のcausal_rules恩恵銘柄ロジック
    （テーマ→beneficiary_sectors→related_tickers）だけを使って照合し、
    長期の資産形成・投資判断のために「今見るべき銘柄」を整理する。
    営業利用ではなく自分自身の投資判断を最優先目的とし、断定的な売買助言
    （「買い」「売り」）は一切行わない。judgment_labelは注目継続／押し目待ち
    ／過熱警戒／材料待ち／判断材料不足のいずれかのみを用いる。
    """

    name: str
    ticker: str
    related_themes: List[str] = field(default_factory=list)
    momentum_score: int = 0
    momentum_label: str = ""
    phase: str = ""
    continuity: str = ""
    catalysts: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    confidence_score: int = 0
    judgment_label: str = "判断材料不足"
    judgment_reason: str = ""


@dataclass
class FutureIntelligenceBundle:
    """「Future Intelligence Engine」の計算結果一式。

    v1.0: megatrends / industry_momentum / supply_chains / horizon_groups /
    jp_stock_impact（グループAのみ）。
    v1.1: theme_momentum（Theme Momentum Score）/ early_signals
    （Early Signal Detection）を追加。
    v1.2: theme_maturity_notes（テーマ成熟度メモ）/ national_strategy_notes
    （国家戦略メモ）を追加。config.yamlへの手動登録があればそれを表示。
    v1.3: 手動登録がない場合に「未登録」で終わらせず、既存シグナル
    （見出し件数・durable_themes・causal_rules・恩恵銘柄・national_focus_areas）
    からのAI分析（断定はしない）、または信号が無い場合の「分析材料不足」を
    表示するよう改善。いずれも具体的な市場規模・補助金額・政策名は生成しない。
    v1.4: Theme Momentum ScoreにExecutive Summaryとの一致・関連セクター/
    関連銘柄の有無を追加。Early Signal Detectionに営業で話すポイントを追加。
    v1.5: 「世界のお金の流れ（市場シグナルベース）」を安全な縮小版として追加。
    実際の資金流入額は取得していないため断定せず、公開市場データ（指数・
    為替・金利・コモディティ）とTheme Momentum Score・Early Signal
    Detection・Sector Ranking・causal_rules・durable_themesという既存
    シグナルのみから、資金の「向かいやすさ」を定性的に推定する。
    market_mood（リスクオン/オフ・グロース/バリュー優位の参考情報）は
    文脈情報としてcapital_flow_notesとは別に保持する。
    v1.6: テーマ別診断（theme_diagnosis）を追加。macro_themeごとに
    Momentum→Lifecycle→Catalyst（加速要因・AI分析）→Risk（失速要因・
    AI分析）→Confidence Score（分析根拠の充実度、0〜100。未来が当たる
    確率ではない）を1テーマずつまとめて提示する、投資家向けの長期分析を
    最優先目的とする機能。
    v1.7: Watchlist Intelligence（watchlist_intelligence）を追加。
    config.yamlのwatchlist銘柄とtheme_diagnosisを、既存のcausal_rules
    恩恵銘柄ロジックだけで照合し、長期の資産形成・投資判断のために
    「今見るべき銘柄」を整理する。断定的な売買助言は行わない。
    """

    megatrends: List[MegatrendEntry] = field(default_factory=list)
    industry_momentum: List[IndustryMomentumEntry] = field(default_factory=list)
    supply_chains: List[SupplyChainNote] = field(default_factory=list)
    horizon_groups: List[HorizonThemeGroup] = field(default_factory=list)
    jp_stock_impact: List[JpStockImpactEntry] = field(default_factory=list)
    theme_momentum: List[ThemeMomentumEntry] = field(default_factory=list)
    early_signals: List[EarlySignalEntry] = field(default_factory=list)
    theme_maturity_notes: List[ThemeMaturityNote] = field(default_factory=list)
    national_strategy_notes: List[NationalStrategyNote] = field(default_factory=list)
    capital_flow_notes: List[CapitalFlowNote] = field(default_factory=list)
    capital_flow_market_mood: str = ""
    theme_diagnosis: List[ThemeDiagnosisEntry] = field(default_factory=list)
    watchlist_intelligence: List[WatchlistIntelligenceEntry] = field(default_factory=list)


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
