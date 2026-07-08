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
    # v3.2（改善3/4/5）: News Impact Score（0〜100）・情報源Tier・Major Story判定。
    # いずれもデフォルト値付きで、既存のランキング（stars・並び順）とは独立した
    # 追加の機械的スコア。既存の呼び出し箇所・表示には影響しない。
    impact_score: int = 0
    impact_breakdown: Dict[str, int] = field(default_factory=dict)
    source_tier: str = ""          # "Tier1" / "Tier2" / "Tier3" / "Tier4"
    is_major_story: bool = False    # 3社以上が同一ニュースを報道


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
class StockIntelligenceEntry:
    """「Stock Intelligence」の1銘柄分（v2.0）。

    Watchlist Intelligenceで一致した銘柄のみを対象に、Future Intelligence
    Engineの分析結果（テーマ・Momentum・Lifecycle・Catalyst・Risk・
    Confidence・関連テーマ）を1銘柄ごとの投資判断まで落とし込む。
    momentum_score/momentum_label/phase/continuity/catalysts/risks/
    confidence_score/judgment_labelは、WatchlistIntelligenceEntryと
    同じ値をそのまま引き継ぎ、Future Intelligence／Watchlist
    Intelligenceとの整合性を保つ（新たに再計算・再推定はしない）。

    why_long_term（なぜ長期で見るのか）・watch_events（今後注目する
    イベント）・cross_theme_chain（関連するテーマ）・investment_story
    （投資ストーリー）は、いずれも既存シグナル（テーマ名・Catalyst・
    Lifecycle・Momentum・theme_relations）のみから機械的に組み立てた
    ものであり、AIによる作文・新たな未来予測ではない。目標株価・PER予想・
    EPS予想・「買い」「売り」等の推奨・期待リターンは一切生成しない。
    """

    name: str
    ticker: str
    related_themes: List[str] = field(default_factory=list)
    primary_theme: str = ""
    momentum_score: int = 0
    momentum_label: str = ""
    phase: str = ""
    continuity: str = ""
    catalysts: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    confidence_score: int = 0
    judgment_label: str = "判断材料不足"
    why_long_term: str = ""
    watch_events: List[str] = field(default_factory=list)
    cross_theme_chain: List[str] = field(default_factory=list)
    investment_story: List[str] = field(default_factory=list)


@dataclass
class InvestmentThesisEntry:
    """「Investment Thesis」の1テーマ分（v2.4）。

    macro_themeごとの長期投資仮説。すべてのフィールドは既存シグナル
    （Theme Momentum・Lifecycle・Catalyst・Risk・Confidence・causal_rules・
    theme_relations・中長期テーマの割り付け）のみから機械的に組み立てる。
    AIによる新たな未来予測・目標株価・PER/EPS予想・「買い」「売り」等の
    推奨・期待リターンは一切生成しない。

    - current_situation: 現在何が起きているか（Theme Momentum Scoreのreasonを転記）
    - expected_change: 今後起こりそうな変化（Catalystからの非断定的な整理・AI分析）
    - beneficiary_industries: 恩恵を受ける業界（causal_rules.beneficiary_sectors）
    - beneficiary_names: 恩恵企業（既存の恩恵銘柄ロジックの結果を転記）
    - secondary_beneficiary_names: 二次的恩恵企業（theme_relationsで1段階
      隣接するテーマの恩恵企業）
    - less_watched_names: まだ注目されにくい企業（theme_relationsで2段階
      離れたテーマの恩恵企業＝因果チェーン上、直接の恩恵銘柄として
      言及されにくい銘柄。新たな銘柄推定ではない）
    - horizons: 投資期間（既存の中長期テーマ割り付け（半年/1年/3年/5年/10年）
      のうち、このテーマが属する時間軸をそのまま転記）
    - watch_indicators: 監視指標（Momentum推移・関連ニュース件数＋既存の
      テーマ→イベント対応表からの機械的な列挙）
    - breakdown_conditions: 崩れる条件（テーマ別診断のRisk（失速要因）を転記）
    - thesis_summary: 投資仮説まとめ（Stock Intelligenceと同じ
      investment_storyロジックによる時系列の因果チェーン）
    """

    label: str
    current_situation: str = ""
    expected_change: str = ""
    beneficiary_industries: List[str] = field(default_factory=list)
    beneficiary_names: List[str] = field(default_factory=list)
    secondary_beneficiary_names: List[str] = field(default_factory=list)
    less_watched_names: List[str] = field(default_factory=list)
    horizons: List[str] = field(default_factory=list)
    watch_indicators: List[str] = field(default_factory=list)
    breakdown_conditions: List[str] = field(default_factory=list)
    thesis_summary: List[str] = field(default_factory=list)
    momentum_score: int = 0
    momentum_label: str = ""
    phase: str = ""
    continuity: str = ""
    confidence_score: int = 0


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
    v2.0: Stock Intelligence（stock_intelligence）を追加。Watchlist
    Intelligenceで一致した銘柄のみを対象に、なぜ長期で見るのか・今後
    注目するイベント・関連するテーマ・投資ストーリーを、既存シグナルの
    みから機械的に組み立てる。目標株価・PER/EPS予想・売買推奨・期待
    リターンなど新たな未来予測は一切行わない。
    v2.4: Investment Thesis（investment_theses）を追加。macro_theme
    ごとの長期投資仮説（現在の状況→今後の変化→恩恵業界→恩恵企業→
    二次的恩恵企業→まだ注目されにくい企業→投資期間→監視指標→
    崩れる条件→投資仮説まとめ）を、既存シグナルのみから機械的に
    組み立てる。営業利用ではなく自分自身の長期資産形成・投資判断を
    最優先目的とする。
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
    stock_intelligence: List[StockIntelligenceEntry] = field(default_factory=list)
    investment_theses: List[InvestmentThesisEntry] = field(default_factory=list)


@dataclass
class LearningHistoryEntry:
    """「Learning History」の1日分（v2.8・①）。

    Investment Journal（data/investment_journal/journal.json）に記録した
    過去のAI判断と、30/90/180日後の実際の市場データを比較した答え合わせの
    結果を表示するための入れ物。評価はルールベース（記録時の参照価格と
    現在価格の比較）で、AIが新たな予測を生成するものではない。
    """

    date: str
    headline: str = ""
    theme: str = ""
    scenario_summary: str = ""
    days_elapsed: int = 0
    evaluated: bool = False
    evaluation_horizon: int = 0        # 30 / 90 / 180
    evaluation_stars: str = ""
    evaluation_status: str = "評価待ち"  # 評価待ち / 的中 / 部分的中 / 外れ
    evaluation_note: str = ""


@dataclass
class ThemeLearningStat:
    """「Theme Confidence Learning」の1テーマ分（v2.8・②）。

    data/theme_learning/theme_learning.json に毎日追記した予想と、後日の
    実績（テーマ関連の代表指標の騰落）を突き合わせた勝率・平均リターン等の
    集計結果を表示するための入れ物。Confidence補正にも使う。
    """

    label: str
    first_seen: str = ""
    samples: int = 0
    wins: int = 0
    win_rate: Optional[float] = None       # 0.0〜1.0（サンプルが無ければNone）
    avg_return_pct: Optional[float] = None
    avg_duration_days: Optional[float] = None
    success_condition: str = ""
    failure_condition: str = ""


@dataclass
class ScenarioV2Entry:
    """「Scenario Engine v2」の1シナリオ分（v2.8・③）。

    既存のScenarioForecast（強気/中立/弱気の確率・理由）と既存シグナル
    （業種の追い風/逆風・ウォッチリスト・因果チェーン）のみから機械的に
    組み立てる。新たな確率予測・目標株価・断定的な過去事例は生成しない。
    期待値（＝確率）の高い順に最大3つだけを提示する。
    """

    rank: int
    title: str
    probability: int          # %（ScenarioForecastの配分をそのまま使用）
    stars: str
    trigger_condition: str    # 発生条件
    market_impact: str        # マーケット影響
    beneficiary_sectors: List[str] = field(default_factory=list)
    adverse_sectors: List[str] = field(default_factory=list)
    watch_names: List[str] = field(default_factory=list)
    causal_chain: str = ""    # 詳しく: 因果関係
    time_horizon: str = ""    # 詳しく: 時間軸
    historical_note: str = "" # 詳しく: 一般的な反応パターン（特定過去日の断定ではない）


@dataclass
class WeeklyEventEntry:
    """「Weekly Event Impact Calendar」の1イベント分（v2.7）。

    config.yamlのmacro_events（登録情報）と決算発表予定（公開情報）のみから
    組み立てる。重要度・影響対象・想定される影響は、イベント名キーワードと
    人手による対応表（_EVENT_RULES）の照合結果であり、AIによる新たな予測ではない。
    外部APIは使用しない。営業利用よりも自分自身の資産形成・投資判断を
    最優先目的とする（今週どのイベント前後で相場が動きやすいかの把握）。
    """

    label: str
    date_str: str = ""
    time_str: str = ""  # "21:30" 等（日本時間）。未登録なら空
    region: str = ""
    category: str = ""  # 金融政策／経済指標／決算／需給 等
    stars: str = ""
    importance: int = 0  # 100点満点（★×20）
    days_until: int = 0
    countdown_text: str = ""  # 「本日21:30」「あと1日 5時間」「あと3日」等
    impact_targets: List[str] = field(default_factory=list)
    expected_impact: str = ""
    why_important: str = ""
    watch_points: List[str] = field(default_factory=list)
    related_themes: List[str] = field(default_factory=list)
    # v3.0（③）: 取得元の見える化。config手入力なら「登録情報」、自動取得なら
    # 情報源名。source_stars は Source Trust（★1〜5）。fetched_at は取得時刻（自動取得のみ）。
    source: str = "登録情報"
    source_stars: str = ""
    fetched_at: str = ""
    # v3.2（改善6・Macro Intelligence 構造）: 市場コンセンサス・前回値・予想値・結果・
    # サプライズを保持できる構造（今回は入れ物のみ。登録・自動取得で値があれば
    # そのまま転記し、無ければ空文字＝従来表示。断定的な予測は生成しない）。
    consensus: str = ""
    previous: str = ""
    forecast: str = ""
    actual: str = ""
    surprise: str = ""


@dataclass
class RashinbanKnowledge:
    """「Rashinban Learning Source」の学習結果（v2.6）。

    data/rashinban/ に置かれた岡三「羅針盤」（.md/.txt）から、ルールベースで
    抽出した分析フレーム（型）のみを保持する。本文の転載・長文引用は行わず、
    各パターンは短い断片（80文字まで・カテゴリごと最大5件）に制限される。
    raw_excerpt_summaryは内部確認用の冒頭1行（120文字まで）で、HTMLには出さない。
    ファイルが無い場合は空のまま使われ、既存分析には一切影響しない。
    """

    source_files: List[str] = field(default_factory=list)
    latest_date: str = ""
    market_view_patterns: List[str] = field(default_factory=list)
    theme_patterns: List[str] = field(default_factory=list)
    stock_selection_patterns: List[str] = field(default_factory=list)
    risk_patterns: List[str] = field(default_factory=list)
    time_horizon_patterns: List[str] = field(default_factory=list)
    # v2.7: 投資哲学・利益確定・リスク規律など「投資の型」（知識ベース化で追加）
    philosophy_patterns: List[str] = field(default_factory=list)
    raw_excerpt_summary: str = ""
    # 羅針盤本文に登場した既存macro_themeラベル（新テーマの生成はしない）
    emphasized_theme_labels: List[str] = field(default_factory=list)

    def frame_count(self) -> int:
        """抽出した分析フレームの総数（HTML表示・ログ用）。"""
        return (
            len(self.market_view_patterns)
            + len(self.theme_patterns)
            + len(self.stock_selection_patterns)
            + len(self.risk_patterns)
            + len(self.time_horizon_patterns)
            + len(self.philosophy_patterns)
        )

    def has_content(self) -> bool:
        """羅針盤ファイルが1件以上読み込めているか。"""
        return bool(self.source_files)


@dataclass
class MarketRegime:
    """「Market Regime Engine」の判定結果（v3.2・改善1）。

    VIX・米10年債・NASDAQ・S&P500・SOX・ドル指数・ドル円・WTI・Gold・Bitcoin
    などの公開市場データのみから、現在の地合いを機械的に総合評価する。
    regime は Risk On / Risk Off / Neutral、stance は Bullish / Bearish / Neutral。
    risk_score（0〜100）は0=極端なRisk Off、100=極端なRisk Onの連続値で、
    各指標のリスクオン/オフ寄与を合算して算出する（生成AIの推測ではない）。
    signals は指標ごとの寄与（名前→+寄与/-寄与とコメント）。
    """

    regime: str = "判定不能"        # Risk On / Risk Off / Neutral / 判定不能
    stance: str = "Neutral"          # Bullish / Bearish / Neutral
    risk_score: int = 50             # 0〜100（50=中立）
    summary: str = ""
    signals: List["RegimeSignal"] = field(default_factory=list)
    evaluated_count: int = 0         # 実際に評価に使えた指標数（データ欠損の把握用）


@dataclass
class RegimeSignal:
    """Market Regime Engine の指標1件分の寄与（表示・確認用）。"""

    name: str
    value: Optional[float] = None
    contribution: float = 0.0        # リスクオン(+)/オフ(-)への寄与
    note: str = ""


@dataclass
class CrossMarketChain:
    """「Cross Market Analysis」の1本分（v3.2・改善2）。

    米金利↑→ドル高→円安→日本輸出株→半導体→設備投資→電力→電線 のように、
    公開市場データと人手による波及テンプレート（config.yaml の cross_market_rules、
    無ければ内蔵の既定ルール）から、条件成立時のみ多段の波及を機械的に組み立てる。
    生成AIの推測ではなく、trigger（発火条件）が実データで満たされた場合のみ nodes を返す。
    """

    label: str
    trigger: str
    nodes: List[str] = field(default_factory=list)
    basis: str = ""


@dataclass
class ConditionalScenario:
    """「Future Probability（条件分岐型）」の1件分（v3.2・改善7）。

    未来の断定予測ではなく、「もしAかつBなら → C」というif条件ベースの分岐。
    conditions（発火条件）が本日の公開市場データで満たされているかを機械的に
    評価し、triggered=Trueなら現在その分岐にあることを示す。生成AIの推測は行わない。
    """

    label: str
    conditions: List[str] = field(default_factory=list)
    outcome: str = ""
    triggered: bool = False
    rationale: str = ""


@dataclass
class ThemeRotationEntry:
    """「Theme Rotation」の1件分（v3.2・改善8）。

    AI→半導体→電力→電線→素材→建設 のような、テーマからテーマへの資金移動の
    「向かいやすさ」を、既存の Theme Momentum Score と config.yaml の theme_relations
    （人手によるテーマ隣接関係）のみから機械的に推定する。実際の資金フロー額は
    取得しておらず断定はしない（「資金が移りやすい」等の非断定表現に統一）。
    """

    from_theme: str
    to_theme: str
    from_momentum: int = 0
    to_momentum: int = 0
    signal: str = ""                 # 資金移動が起きやすい / 拮抗 / 逆流の可能性
    note: str = ""


@dataclass
class MarketBreadth:
    """「Market Breadth」（v3.2・改善9）。

    市場全体の強さ（値上がり/値下がりの広がり）を保持する構造。将来、値上がり
    ・値下がり銘柄数の実データを取得できるようになった際にそのまま使えるよう、
    advancers/decliners を持てる形にする。現状は取得済みの主要指数・ウォッチリスト
    銘柄の前日比プラス/マイナス数から breadth_score（0〜100）を機械的に算出する
    （50=中立、100=全面高）。指数の代用であり、東証全銘柄の騰落ではない点を明記する。
    """

    advancers: int = 0
    decliners: int = 0
    unchanged: int = 0
    breadth_score: int = 50          # 0〜100（50=中立）
    basis: str = ""                  # 算出根拠（何を母集団にしたか）
    is_proxy: bool = True            # 全市場の実騰落ではなく取得済み銘柄からの代用か


@dataclass
class AnalysisConfidence:
    """「Analysis Confidence」（v3.2・改善10）。

    旧「AI Confidence」に代わる、レポート全体の分析根拠の充実度（0〜100）。
    「未来が当たる確率」ではなく、取得ソース数・公式情報数・重複報道数・鮮度・
    データ欠損・分析可能項目数という既存の実データのみから機械的に算出する。
    """

    score: int = 0
    grade: str = ""                  # 高 / 中 / 低 / 判定不能
    components: Dict[str, int] = field(default_factory=dict)
    basis: str = ""


@dataclass
class MarketNarrativeSummary:
    """「本日の相場総括（Market Narrative）」（v3.5・改善1）。

    ニュースと市場データ・既存の各エンジン（Market Regime / Cross Market /
    Future Intelligence / Executive Summary / Weekly Events / 異常値 /
    Analysis Confidence）の算出済み結果だけを機械的に組み合わせ、「今日の相場が
    なぜ動いたのか」「背景は何か」「今後どう見ればよいか」を端的にまとめる。
    生成AIによる作文・断定的な将来予測・売買助言（買うべき/売るべき）は行わない。
    今後の見立ては条件分岐（if条件）で表現する。
    """

    headline: str = ""                                     # 今日の相場を一言で
    market_move: List[str] = field(default_factory=list)   # 何が起きたか（主要変化）
    main_causes: List[str] = field(default_factory=list)   # なぜ動いたか
    background_factors: List[str] = field(default_factory=list)  # 背景（金利/為替/AI半導体/決算/原油/VIX/政策）
    cross_market_chain: List[str] = field(default_factory=list)  # 波及チェーン（Cross Market）
    watch_points: List[str] = field(default_factory=list)  # これから何を見るべきか
    near_term_view: str = ""                               # 短期の見立て（条件分岐）
    medium_term_view: str = ""                             # 中期の見立て（条件分岐）
    risk_factors: List[str] = field(default_factory=list)  # 注意すべきリスク
    implications: List[str] = field(default_factory=list)  # 投資判断への示唆（短期/中期/長期/注意）
    confidence: str = ""                                   # Analysis Confidence（分析根拠の充実度）
    source_items: List[str] = field(default_factory=list)  # 根拠にした既存エンジン・データ


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
    weekly_events: List[WeeklyEventEntry] = field(default_factory=list)
    scenarios_v2: List[ScenarioV2Entry] = field(default_factory=list)
    learning_history: List[LearningHistoryEntry] = field(default_factory=list)
    theme_learning_stats: List[ThemeLearningStat] = field(default_factory=list)
    # v3.2 Analysis Accuracy Upgrade（分析エンジン強化。いずれもデフォルト値付きで
    # 既存の呼び出し箇所・表示には影響しない）。
    market_regime: Optional[MarketRegime] = None                 # 改善1
    cross_market_chains: List[CrossMarketChain] = field(default_factory=list)   # 改善2
    conditional_scenarios: List[ConditionalScenario] = field(default_factory=list)  # 改善7
    theme_rotation: List[ThemeRotationEntry] = field(default_factory=list)      # 改善8
    market_breadth: Optional[MarketBreadth] = None               # 改善9
    analysis_confidence: Optional[AnalysisConfidence] = None      # 改善10
    # v3.5 Market Narrative（本日の相場総括。デフォルトNoneで既存呼び出しに影響なし）
    market_narrative: Optional[MarketNarrativeSummary] = None
