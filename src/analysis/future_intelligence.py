"""Future Intelligence Engine（世界の構造変化テーマの定性分析）。

「今日のニュース」ではなく、config.yaml の macro_themes に登録した長期テーマ
（AI・半導体・電力・防衛・宇宙・量子・自動運転など）を、既存の仕組み
（本日の関連見出し件数・durable_themes・causal_rules・恩恵銘柄ロジック・
news_ranking の重要ニュース）だけを使って定性的に評価する。

v1.0はグループAのみを実装した:
    ①総合（本モジュールの出力をまとめて1セクションとして表示）
    ②世界のメガトレンド（★・フェーズ・継続性・なぜ伸びるか）
    ③テーマの寿命（フェーズ＋継続性の定性ラベル。具体的な残り年数は出さない）
    ⑤次に来る業界ランキング（本日のモメンタム順）
    ⑥サプライチェーン分析（causal_rulesの因果チェーンをそのまま表示）
    ⑨中長期テーマ（半年/1年/3年/5年/10年の定性的な割り付け）
    ⑩日本株への波及（恩恵銘柄。大型/中小型は区分不明として明記）
    ⑪Future Map（②〜⑨の集約一覧）

v1.1で以下を追加した:
    Theme Momentum Score（0〜100の定性スコア。前日比・週次比較は行わない）
    Early Signal Detection（見出し件数はまだ少ないが、causal_rules該当・
    durable_themes該当・恩恵銘柄が解決できるテーマを「初動シグナル」として抽出）

v1.2で以下を追加した:
    テーマ成熟度メモ（config.yaml の theme_maturity_notes を手動登録内容の
    まま表示。AIによる市場規模・普及率・競争環境等の生成は行わない）
    国家戦略メモ（config.yaml の national_strategy_notes を手動登録内容の
    まま表示。日本/米国/中国/EU/インド/中東の6地域固定。AIによる補助金額・
    政策内容の生成は行わない）

v1.4で以下を改善した:
    Theme Momentum Score: 本日の見出し密度・重要ニュースとの一致・causal_rules
    該当・durable_themes該当に加えて、Executive Summary（executive_summary.py
    が同じnews_ranking_itemsから抽出した最重要ニュース）との一致、および
    causal_rulesの恩恵銘柄ロジックから導ける関連セクター・関連銘柄の有無、
    という既存シグナルを追加した。あわせて、世界のメガトレンド評価（フェーズ
    ・★）を理由欄に文脈情報として明記する。関連セクター・関連銘柄も表示する。
    Early Signal Detection: 既存の判定条件（見出しが少ない・causal_rules該当
    ・durable_themes該当・恩恵銘柄が解決できる）は変更せず、恩恵銘柄が解決
    できるという既存条件を「営業利用価値がある」ことの根拠として明記した
    うえで、関連セクター・関連銘柄という実データのみから機械的に組み立てた
    営業向けの話しかけポイント（sales_talk）を追加した。

v1.3で以下を改善した:
    テーマ成熟度メモ／国家戦略メモとも、config.yamlへの手動登録がある場合は
    引き続きそれを最優先表示する（source_label="登録情報"）。手動登録が
    ない場合は「未登録」で終わらせず、本日の関連見出し件数・durable_themes
    該当・causal_rules該当・恩恵銘柄・national_focus_areas（国・地域と
    macro_themesの重点分野を対応付けた、人手による参考情報。AIが生成した
    ものではない）という既存シグナルのみから、ルールベースで導いた定性的な
    AI分析を表示する（source_label="AI分析"）。判断材料となる信号が
    何もない場合のみ「分析材料不足」とする（source_label="分析材料不足"）。
    いずれの場合も具体的な市場規模・補助金額・政策名・法案名は生成しない
    （断定を避けた「〜と考えられます」等の表現で統一する）。

v1.5で以下を安全な縮小版として追加した:
    「世界のお金の流れ（市場シグナルベース）」。実際の機関投資家ポジション
    ・資金流入額は取得していないため、具体的な資金フローは断定しない。
    公開市場データ（日経平均・TOPIX・NASDAQ・SOX・VIX・米10年金利・
    ドル円・WTI・金）とTheme Momentum Score・Early Signal Detection・
    Sector Ranking・causal_rules・durable_themesという既存シグナルのみ
    から、「AI・半導体」「金融・銀行」「防衛・電力・インフラ」「内需・消費」
    「コモディティ・資源」の5テーマについて、資金の「向かいやすさ」（流入
    しやすい／中立／流出しやすい／判断材料不足）を機械的に推定する。
    「資金が流入している」「機関投資家が買っている」「海外勢が買っている」
    「◯億円流入」等の断定・捏造表現は一切使わず、「資金が向かいやすい」
    「物色されやすい」「関心が高まりやすい」「相対的に選好されやすい」
    「市場シグナル上は追い風」等の非断定表現に統一する。

v1.6で以下を追加した:
    テーマ別診断（Momentum→Lifecycle→Catalyst→Risk→Confidence）。
    本システムの最優先目的は営業ツールではなく「世界の変化をいち早く察知し、
    長期の資産形成・投資判断に役立てる未来分析システム」であることを踏まえ、
    macro_themeごとにCatalyst（加速要因）・Risk（失速要因）・Confidence
    Score（分析根拠の充実度）を追加した。Catalyst/Riskは、ニュース・
    Executive Summary・Theme Momentum・Early Signal・causal_rules・
    durable_themes・サプライチェーン（恩恵銘柄）・国家戦略メモ・世界の
    お金の流れという既存シグナルのみから機械的に導いた「AI分析」であり、
    具体的な数値・政策名・企業業績の断定はしない。Confidence Score
    （0〜100）は「未来が当たる確率」ではなく、上記シグナルのうち実際に
    確認できたものの数（＝分析根拠の充実度）を表す。

v1.7で以下を追加した:
    Watchlist Intelligence。config.yaml の watchlist（jp_stocks/us_stocks）
    銘柄と、テーマ別診断（v1.6のtheme_diagnosis）を、既存のcausal_rules
    恩恵銘柄ロジック（テーマ→beneficiary_sectors→related_tickers）だけを
    使って照合し、長期の資産形成・投資判断のために「今見るべき銘柄」を
    整理する。営業利用ではなく自分自身の投資判断を最優先目的とし、
    「買い」「売り」等の断定的な売買助言は一切行わない。判断ラベルは
    注目継続／押し目待ち／過熱警戒／材料待ち／判断材料不足のいずれかのみ
    を、Momentum・Lifecycle・Confidenceという既存シグナルから機械的に導く。

v1.8で以下を改善した:
    Watchlist Intelligenceの精度向上。新しい分析ロジックは追加せず、
    config.yamlの sectors（related_tickers）・causal_rules
    （beneficiary_sectors）を、投資テーマとの経済的な因果関係（例:
    AI設備投資→半導体・データセンター運営主体・電力設備／電気工事・
    電線・冷却部材への波及）に沿って拡充し、テーマ→銘柄の紐付け精度を
    高めた（銘柄・因果関係の辞書充実のみで、AI分析の追加ではない）。
    あわせて、config.yamlのtheme_relations（人手によるテーマ同士の
    対応付け）をテーマ別診断の「関連テーマ」としてそのまま表示する
    （新たな未来予測ロジックではない）。

v1.9で以下を改善した:
    macro_themesを17拡張（自動車／EV／蓄電池／金融／金利／為替／消費／
    人材／広告／SaaS／スマートフォン／クラウド／決済／旅行／住宅／建設／
    インバウンド）し、Watchlist Intelligenceの一致率をさらに向上させた
    （新しい分析ロジックは追加せず、config.yamlの辞書・マッピング拡張のみ）。

v2.0で以下を追加した:
    Stock Intelligence。Watchlist Intelligenceで一致した銘柄のみを対象に、
    Future Intelligence Engineの分析結果（テーマ・Momentum・Lifecycle・
    Catalyst・Risk・Confidence・関連テーマ）を1銘柄ごとの投資判断まで
    落とし込む。momentum_score等はWatchlist Intelligenceと同じ値を
    そのまま引き継ぎ整合性を保つ。「なぜ長期で見るのか」「今後注目する
    イベント」「関連するテーマ」「投資ストーリー」は、いずれも既存シグナル
    のみから機械的に組み立てたものであり、AIによる作文・新たな未来予測
    ではない。目標株価・PER/EPS予想・「買い」「売り」等の推奨・期待
    リターンは一切生成しない。

具体的な残り年数・市場規模・補助金額・政策内容・資金流入額等、実データの
裏付けがない数値・情報は一切生成しない（決定論的なルールベースの定性ラベル、
config.yamlの手動登録内容のそのまま表示、または既存シグナルからの定性的な
AI分析のみ）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..collectors.news import Headline
from ..report.format_utils import find_quote, stars
from .models import (
    CapitalFlowNote,
    EarlySignalEntry,
    ExecutiveSummaryItem,
    FutureIntelligenceBundle,
    HorizonThemeGroup,
    IndustryMomentumEntry,
    InvestmentThesisEntry,
    JpStockImpactEntry,
    MegatrendEntry,
    NationalStrategyNote,
    NewsRankingItem,
    RashinbanKnowledge,
    SectorRankingEntry,
    StockIntelligenceEntry,
    SupplyChainNote,
    ThemeDiagnosisEntry,
    ThemeMaturityNote,
    ThemeMomentumEntry,
    WatchlistIntelligenceEntry,
)
from .strategist_engine import CausalRule, parse_causal_rules, resolve_tickers, ticker_names
from .theme_learning import confidence_adjustment

TOP_INDUSTRY_MOMENTUM = 5
MAX_TICKERS_DISPLAYED = 5
TOP_NEWS_FOR_MOMENTUM = 5
EARLY_SIGNAL_MAX_HEADLINES = 1
NOT_REGISTERED = "未登録"

# 「国家戦略メモ」の対象6地域（固定）。config.yaml の national_strategy_notes
# に手動登録がない地域も、必ずこの6地域分を表示する。
NATIONAL_STRATEGY_REGIONS = ["日本", "米国", "中国", "EU", "インド", "中東"]

# 国・地域とmacro_themesの重点分野を対応付けた、人手による参考情報
# （AIが生成したものではない）。national_strategy_notesが未登録の場合、
# ここで対応付けた重点分野に絞って、本日のテーマ動向からAI分析を導く。
# 具体的な政策名・補助金額はここにも含めない（テーマの分類のみ）。
NATIONAL_FOCUS_AREAS: Dict[str, List[str]] = {
    "日本": ["AI", "半導体", "防衛", "GX", "電力", "人口減少", "高齢化"],
    "米国": ["AI", "半導体", "防衛", "宇宙", "量子", "サイバーセキュリティ"],
    "中国": ["半導体", "AI", "ロボット", "電力", "資源"],
    "EU": ["GX", "電力", "サイバーセキュリティ", "食料"],
    "インド": ["AI", "半導体", "物流", "自動運転", "食料"],
    "中東": ["資源", "GX", "水インフラ", "食料"],
}

# 「世界のお金の流れ（市場シグナルベース）」の対象5テーマとmacro_themesの
# 対応付け（人手による参考情報。AIが生成したものではない）。「金融・銀行」
# 「内需・消費」はmacro_themesに対応するテーマが無いため、Sector Ranking
# ・市場データのみから判定する。
CAPITAL_FLOW_MACRO_LABELS: Dict[str, List[str]] = {
    "AI・半導体": ["AI", "半導体"],
    "防衛・電力・インフラ": ["防衛", "電力", "水インフラ"],
    "コモディティ・資源": ["資源"],
}
CAPITAL_FLOW_SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "金融・銀行": ["銀行", "金融", "保険"],
    "内需・消費": ["内需", "小売", "食品", "消費"],
}

# 本日の関連見出し件数から3段階（none/low/high）に区分し、durable_themes
# 該当有無と組み合わせて★・フェーズ・継続性を機械的に決定する。
# いずれも実データ（見出し件数・config設定）のみに基づく決定論的な対応表であり、
# 市場規模や残り年数等の外部情報を推定・捏造するものではない。
_STAR_TABLE = {
    (True, "high"): 5,
    (True, "low"): 4,
    (True, "none"): 3,
    (False, "high"): 3,
    (False, "low"): 2,
    (False, "none"): 1,
}

_PHASE_TABLE = {
    (True, "high"): "急成長期",
    (True, "low"): "成長初期",
    (True, "none"): "成熟期",
    (False, "high"): "成長初期",
    (False, "low"): "黎明期",
    (False, "none"): "減速期",
}


def _hit_level(count: int) -> str:
    if count >= 2:
        return "high"
    if count == 1:
        return "low"
    return "none"


def _continuity_label(durable: bool, level: str) -> str:
    if durable:
        return "高い"
    if level in ("high", "low"):
        return "中程度"
    return "限定的"


def _matched_headline_count(headlines: List[Headline], keywords: List[str]) -> int:
    return sum(1 for h in headlines if any(kw in h.title for kw in keywords))


def _matched_causal_rule(keywords: List[str], causal_rules: List[CausalRule]) -> Optional[CausalRule]:
    """macro_themeのキーワードが、causal_rulesのtheme名またはtrigger_keywordsと
    重なる場合に、そのルールを再利用する（新たな因果関係の推定は行わない）。"""
    for rule in causal_rules:
        if any(kw in rule.theme for kw in keywords):
            return rule
        if any(kw in rule.trigger_keywords for kw in keywords):
            return rule
    return None


def _why_growing(rule: Optional[CausalRule]) -> str:
    if rule and rule.note:
        return rule.note
    return "本日の関連ニュースの傾向から注目が集まっているテーマと考えられます。"


def _momentum_score(
    headline_count: int,
    causal_matched: bool,
    durable: bool,
    top_news_matched: bool,
    exec_summary_matched: bool,
    has_beneficiary: bool,
) -> int:
    """本日の見出し密度・重要ニュースとの一致・Executive Summaryとの一致・
    causal_rules一致・durable_themes一致・関連セクター/関連銘柄の有無という
    既存シグナルのみから、0〜100の定性スコアを機械的に算出する（v1.4で
    Executive Summaryとの一致・関連セクター/関連銘柄の有無を追加）。
    履歴データを保持していないため、前日比・週次比較は行わない。
    """
    score = min(headline_count, 5) * 6
    if causal_matched:
        score += 15
    if durable:
        score += 15
    if top_news_matched:
        score += 10
    if exec_summary_matched:
        score += 15
    if has_beneficiary:
        score += 15
    return min(100, score)


def _momentum_label(score: int) -> str:
    if score >= 70:
        return "急加速"
    if score >= 45:
        return "加速"
    if score >= 20:
        return "横ばい"
    return "減速"


def _momentum_reason(
    headline_count: int,
    causal_matched: bool,
    durable: bool,
    top_news_matched: bool,
    exec_summary_matched: bool,
    has_beneficiary: bool,
    megatrend: MegatrendEntry,
) -> str:
    parts = []
    if headline_count > 0:
        parts.append(f"本日{headline_count}件の関連見出しが確認されています")
    if exec_summary_matched:
        parts.append("本日のExecutive Summary（最重要ニュース）にも関連しています")
    elif top_news_matched:
        parts.append("本日の重要ニュースにも関連しています")
    if causal_matched:
        parts.append("既存の因果チェーン（causal_rules）にも該当します")
    if durable:
        parts.append("継続性の高い構造的テーマに位置づけられています")
    if has_beneficiary:
        parts.append("関連セクター・関連銘柄も確認できるため、サプライチェーンへの波及も期待しやすいと考えられます")
    if not parts:
        parts.append("本日時点では目立った関連ニュースは確認されていません")
    parts.append(f"Future Intelligenceのテーマ評価は{megatrend.stars}・{megatrend.phase}です")
    return "、".join(parts) + "。"


def _is_early_signal(headline_count: int, rule: Optional[CausalRule], durable: bool, beneficiary_tickers: List[str]) -> bool:
    return (
        headline_count <= EARLY_SIGNAL_MAX_HEADLINES
        and rule is not None
        and bool(rule.beneficiary_sectors)
        and durable
        and len(beneficiary_tickers) > 0
    )


def _early_signal_stars(durable: bool, beneficiary_tickers: List[str]) -> int:
    score = 3
    if durable:
        score += 1
    if len(beneficiary_tickers) >= 2:
        score += 1
    return min(5, score)


def _early_signal_sales_talk(label: str, beneficiary_sectors: List[str], beneficiary_names: List[str]) -> str:
    """初動シグナルの「営業で話すポイント」。関連セクター・関連銘柄という
    既存の実データのみから機械的に組み立て、具体的な数値の断定はしない。
    """
    parts = [f"「{label}」はまだ大きく報道されていませんが、早めに話題に出すと関心を引きやすいテーマと考えられます。"]
    if beneficiary_sectors:
        parts.append(f"関連業種として{'、'.join(beneficiary_sectors)}が挙げられます。")
    if beneficiary_names:
        names_txt = "、".join(n for n in beneficiary_names if n != "など")
        if names_txt:
            parts.append(f"具体的には{names_txt}などが関連銘柄として意識されやすいと考えられます。")
    return "".join(parts)


_MATURITY_REGISTERED_KEYS = (
    "market_stage", "market_size_note", "adoption_note", "competition_note", "barrier_note", "risk_note",
)
_STRATEGY_REGISTERED_KEYS = ("policy_note", "regulation_note", "market_impact_note", "focus_areas")


def _maturity_market_stage_ai(megatrend: MegatrendEntry) -> str:
    return f"AI分析: 現在のフェーズは「{megatrend.phase}」と推定されます。{megatrend.why_growing}"


def _maturity_adoption_ai(durable: bool, level: str) -> str:
    if durable and level != "none":
        return "AI分析: 継続的な話題化が確認されており、活用の広がりが意識されやすい局面と考えられます。"
    if durable:
        return "AI分析: 構造的なテーマに位置づけられますが、本日時点で活用状況を示す具体的な材料は確認できていません。"
    if level != "none":
        return "AI分析: 話題化が始まっている段階で、実際の普及状況を示す材料はまだ限定的と考えられます。"
    return "分析材料不足: 普及状況を推定できる材料が確認できていません。"


def _maturity_competition_ai(beneficiary_names: List[str]) -> str:
    if beneficiary_names:
        names_txt = "、".join(beneficiary_names[:3])
        return f"AI分析: {names_txt}など、関連銘柄として意識される企業を中心とした競争環境にあると考えられます。"
    return "分析材料不足: 競争環境を推定できる関連銘柄情報が確認できていません。"


def _maturity_barrier_ai(beneficiary_sectors: List[str]) -> str:
    if beneficiary_sectors:
        sectors_txt = "、".join(beneficiary_sectors)
        return f"AI分析: {sectors_txt}など関連業種の設備・技術・供給網が参入障壁になりやすいと考えられます。"
    return "分析材料不足: 参入障壁を推定できる業種情報が確認できていません。"


def _maturity_risk_ai(durable: bool, level: str) -> str:
    if level == "high":
        return "AI分析: 話題化・期待の高まりを背景に、材料出尽くしや期待先行によるボラティリティに注意が必要と考えられます。"
    if durable:
        return "AI分析: 構造的なテーマである一方、政策・規制動向や供給制約などの外部要因の影響を受けやすい可能性があります。"
    return "分析材料不足: リスク要因を推定できる材料が確認できていません。"


def _maturity_basis(durable: bool, rule_matched: bool, headline_count: int, has_beneficiary: bool) -> str:
    parts = []
    if durable:
        parts.append("durable_themes該当")
    if rule_matched:
        parts.append("causal_rules一致")
    if headline_count > 0:
        parts.append(f"本日の関連見出し{headline_count}件")
    if has_beneficiary:
        parts.append("サプライチェーン波及（恩恵銘柄）の確認")
    return "、".join(parts)


def _build_theme_maturity_notes(
    macro_themes_cfg: List[dict],
    notes_cfg: Dict,
    megatrend_map: Dict[str, MegatrendEntry],
    theme_rule_map: Dict[str, Optional[CausalRule]],
    theme_beneficiary_names_map: Dict[str, List[str]],
) -> List[ThemeMaturityNote]:
    """テーマ成熟度メモを組み立てる。

    config.yaml の theme_maturity_notes に手動登録があれば最優先で表示する
    （source_label="登録情報"）。未登録の場合は、本日の関連見出し件数・
    durable_themes該当・causal_rules該当・恩恵銘柄という既存シグナルのみ
    から、ルールベースの定性的なAI分析を組み立てる（具体的な市場規模・
    補助金額・企業名の断定はしない）。判断材料が何もない場合のみ
    「分析材料不足」とする。
    """
    notes: List[ThemeMaturityNote] = []
    for entry in macro_themes_cfg:
        label = entry.get("label", "")
        raw = notes_cfg.get(label, {}) if isinstance(notes_cfg, dict) else {}
        if isinstance(raw, dict) and any(raw.get(k) for k in _MATURITY_REGISTERED_KEYS):
            notes.append(
                ThemeMaturityNote(
                    label=label,
                    market_stage=raw.get("market_stage") or NOT_REGISTERED,
                    market_size_note=raw.get("market_size_note") or NOT_REGISTERED,
                    adoption_note=raw.get("adoption_note") or NOT_REGISTERED,
                    competition_note=raw.get("competition_note") or NOT_REGISTERED,
                    barrier_note=raw.get("barrier_note") or NOT_REGISTERED,
                    risk_note=raw.get("risk_note") or NOT_REGISTERED,
                    basis="手動登録（config.yaml）",
                    source_label="登録情報",
                )
            )
            continue

        megatrend = megatrend_map.get(label)
        rule = theme_rule_map.get(label)
        beneficiary_names = theme_beneficiary_names_map.get(label, [])
        durable = bool(megatrend and megatrend.continuity == "高い")
        headline_count = megatrend.headline_count if megatrend else 0
        level = _hit_level(headline_count)
        basis = _maturity_basis(durable, rule is not None, headline_count, bool(beneficiary_names))

        if not basis or megatrend is None:
            notes.append(ThemeMaturityNote(label=label))
            continue

        notes.append(
            ThemeMaturityNote(
                label=label,
                market_stage=megatrend.phase,
                market_size_note=_maturity_market_stage_ai(megatrend),
                adoption_note=_maturity_adoption_ai(durable, level),
                competition_note=_maturity_competition_ai(beneficiary_names),
                barrier_note=_maturity_barrier_ai(rule.beneficiary_sectors if rule else []),
                risk_note=_maturity_risk_ai(durable, level),
                basis=basis,
                source_label="AI分析",
            )
        )
    return notes


def _strategy_policy_ai(focus_themes: List[str], durable_focus: List[str], active_focus: List[str]) -> str:
    parts = [f"{'、'.join(focus_themes)}などの分野に政策関心が向かいやすいと考えられます。"]
    if durable_focus:
        parts.append(f"特に{'、'.join(durable_focus)}は継続性の高いテーマとして位置づけられます。")
    if active_focus:
        parts.append(f"本日は{'、'.join(active_focus)}に関連する見出しが確認されています。")
    return "AI分析: " + "".join(parts)


def _strategy_market_impact_ai(focus_themes: List[str], theme_rule_map: Dict[str, Optional[CausalRule]]) -> str:
    sector_names: List[str] = []
    for t in focus_themes:
        rule = theme_rule_map.get(t)
        if rule:
            for s in rule.beneficiary_sectors:
                if s not in sector_names:
                    sector_names.append(s)
    if sector_names:
        return f"AI分析: {'、'.join(sector_names)}などの関連業種に波及しやすいと考えられます。"
    return "分析材料不足: 波及先を推定できる関連業種情報が確認できていません。"


def _build_national_strategy_notes(
    notes_cfg: Dict,
    megatrend_map: Dict[str, MegatrendEntry],
    theme_rule_map: Dict[str, Optional[CausalRule]],
) -> List[NationalStrategyNote]:
    """国家戦略メモを組み立てる。

    config.yaml の national_strategy_notes に手動登録があれば最優先で表示
    する（source_label="登録情報"）。未登録の場合は、NATIONAL_FOCUS_AREAS
    （人手による重点分野の対応付け）と本日のテーマ動向（既存シグナル）から、
    ルールベースの定性的なAI分析を組み立てる（具体的な政策名・法案名・
    補助金額の断定はしない）。規制動向は本ツールに情報源がないため、
    手動登録がない限り常に「分析材料不足」とする。判断材料が何もない
    場合のみ全項目「分析材料不足」とする。対象は日本／米国／中国／EU／
    インド／中東の6地域固定。
    """
    notes: List[NationalStrategyNote] = []
    for region in NATIONAL_STRATEGY_REGIONS:
        raw = notes_cfg.get(region, {}) if isinstance(notes_cfg, dict) else {}
        if isinstance(raw, dict) and any(raw.get(k) for k in _STRATEGY_REGISTERED_KEYS):
            notes.append(
                NationalStrategyNote(
                    region=region,
                    focus_areas=list(raw.get("focus_areas", [])),
                    policy_note=raw.get("policy_note") or NOT_REGISTERED,
                    regulation_note=raw.get("regulation_note") or NOT_REGISTERED,
                    market_impact_note=raw.get("market_impact_note") or NOT_REGISTERED,
                    basis="手動登録（config.yaml）",
                    source_label="登録情報",
                )
            )
            continue

        focus_themes = [t for t in NATIONAL_FOCUS_AREAS.get(region, []) if t in megatrend_map]
        durable_focus = [t for t in focus_themes if megatrend_map[t].continuity == "高い"]
        active_focus = [t for t in focus_themes if megatrend_map[t].headline_count > 0]

        basis_parts = []
        if focus_themes:
            basis_parts.append("national_focus_areasの重点分野対応付け")
        if durable_focus:
            basis_parts.append("durable_themes該当テーマの存在")
        if active_focus:
            basis_parts.append("本日の関連見出し")
        basis = "、".join(basis_parts)

        if not basis:
            notes.append(NationalStrategyNote(region=region))
            continue

        notes.append(
            NationalStrategyNote(
                region=region,
                focus_areas=focus_themes,
                policy_note=_strategy_policy_ai(focus_themes, durable_focus, active_focus),
                regulation_note="分析材料不足: 規制動向を推定できる情報源が確認できていません。",
                market_impact_note=_strategy_market_impact_ai(focus_themes, theme_rule_map),
                basis=basis,
                source_label="AI分析",
            )
        )
    return notes


def _quote_change_pct(quotes: List, keyword: str) -> Optional[float]:
    q = find_quote(quotes, keyword)
    if q is None or q.change_pct is None:
        return None
    return q.change_pct


def _quote_price(quotes: List, keyword: str) -> Optional[float]:
    q = find_quote(quotes, keyword)
    if q is None or q.price is None:
        return None
    return q.price


def _capital_flow_market_mood(market: Dict) -> str:
    """リスクオン/オフ・グロース/バリュー優位の参考情報を、既存の慣例
    （本コードベースの他モジュールと同じくVIX20を警戒的水準の目安とする）
    に沿って機械的に組み立てる。実際の資金フローの断定はしない。
    """
    indices = market.get("indices", [])
    vix_price = _quote_price(indices, "VIX")
    if vix_price is None:
        mood_txt = "リスクオン/オフの判断材料（VIX指数）が確認できません。"
    elif vix_price < 20:
        mood_txt = f"VIX指数は{vix_price:.2f}と落ち着いた水準で、リスクオン優勢の目安です。"
    else:
        mood_txt = f"VIX指数は{vix_price:.2f}と警戒的な水準で、リスクオフ優勢の目安です。"

    nasdaq = _quote_change_pct(indices, "ナスダック")
    topix = _quote_change_pct(indices, "TOPIX")
    if nasdaq is None or topix is None:
        style_txt = "グロース優位/バリュー優位の判断材料（NASDAQ・TOPIX）が確認できません。"
    else:
        diff = nasdaq - topix
        if diff > 0.3:
            style_txt = "NASDAQがTOPIXを上回っており、グロース優位の目安です。"
        elif diff < -0.3:
            style_txt = "TOPIXがNASDAQを上回っており、バリュー優位の目安です。"
        else:
            style_txt = "グロースとバリューは拮抗している目安です。"
    return mood_txt + " " + style_txt


def _capital_flow_direction_label(score: int) -> str:
    if score >= 2:
        return "流入しやすい"
    if score <= -2:
        return "流出しやすい"
    return "中立"


def _capital_flow_note(
    label: str,
    contributions: List[tuple],
    related_themes: List[str],
    related_sectors: List[str],
) -> CapitalFlowNote:
    """判断材料（(得点, 理由の断片)のリスト）から、資金方向ラベル・理由・
    営業で話すポイントを機械的に組み立てる。判断材料が何も無い場合のみ
    「判断材料不足」とする。実際の資金流入・機関投資家の売買は断定しない。
    """
    if not contributions:
        return CapitalFlowNote(
            label=label,
            direction_label="判断材料不足",
            reason=f"{label}について、市場データ・テーマシグナルのいずれも確認できませんでした。",
            related_themes=related_themes,
            related_sectors=related_sectors,
        )

    score = sum(delta for delta, _ in contributions)
    direction = _capital_flow_direction_label(score)
    fragments = "、".join(fragment for _, fragment in contributions)

    if direction == "流入しやすい":
        tail = f"ことから、「{label}」は市場シグナル上は追い風で、資金が向かいやすい地合いと考えられます。"
        talk_tail = f"「{label}」は市場シグナル上、物色されやすい局面とお伝えできます。"
    elif direction == "流出しやすい":
        tail = f"ことから、「{label}」は市場シグナル上は向かい風で、資金が離れやすい地合いと考えられます。"
        talk_tail = f"「{label}」は市場シグナル上、関心が高まりにくい局面とお伝えできます。"
    else:
        tail = f"ことから、「{label}」への資金動向は方向感に乏しく、中立的と考えられます。"
        talk_tail = f"「{label}」は市場シグナル上、様子見が意識されやすい局面とお伝えできます。"

    return CapitalFlowNote(
        label=label,
        direction_label=direction,
        reason=fragments + tail,
        related_themes=related_themes,
        related_sectors=related_sectors,
        sales_talk=talk_tail,
    )


def _momentum_entries_for(theme_momentum: List[ThemeMomentumEntry], labels: List[str]) -> List[ThemeMomentumEntry]:
    return [tm for tm in theme_momentum if tm.label in labels]


def _early_signal_entries_for(early_signals: List[EarlySignalEntry], labels: List[str]) -> List[EarlySignalEntry]:
    return [es for es in early_signals if es.label in labels]


def _related_sectors_from_momentum(momentum_entries: List[ThemeMomentumEntry]) -> List[str]:
    sectors: List[str] = []
    for tm in momentum_entries:
        for s in tm.related_sector.split("、"):
            if s and s not in sectors:
                sectors.append(s)
    return sectors


def _capital_flow_ai_semicon(
    market: Dict, theme_momentum: List[ThemeMomentumEntry], early_signals: List[EarlySignalEntry]
) -> CapitalFlowNote:
    label = "AI・半導体"
    macro_labels = CAPITAL_FLOW_MACRO_LABELS[label]
    contributions: List[tuple] = []

    sox = _quote_change_pct(market.get("indices", []), "SOX")
    if sox is not None:
        contributions.append((1 if sox >= 0 else -1, f"SOX指数が前日比{sox:+.2f}%"))

    nasdaq = _quote_change_pct(market.get("indices", []), "ナスダック")
    if nasdaq is not None:
        contributions.append((1 if nasdaq >= 0 else -1, f"NASDAQが前日比{nasdaq:+.2f}%"))

    momentum_entries = _momentum_entries_for(theme_momentum, macro_labels)
    accel = [tm for tm in momentum_entries if tm.momentum_label in ("急加速", "加速")]
    slow = [tm for tm in momentum_entries if tm.momentum_label == "減速"]
    if accel:
        contributions.append((1, f"{'、'.join(tm.label for tm in accel)}のTheme Momentum Scoreが高め"))
    elif slow:
        contributions.append((-1, f"{'、'.join(tm.label for tm in slow)}のTheme Momentum Scoreが減速基調"))

    signal_entries = _early_signal_entries_for(early_signals, macro_labels)
    if signal_entries:
        contributions.append((1, f"{'、'.join(es.label for es in signal_entries)}がEarly Signal Detectionにも該当"))

    return _capital_flow_note(
        label, contributions, [tm.label for tm in momentum_entries], _related_sectors_from_momentum(momentum_entries)
    )


def _capital_flow_financials(market: Dict, sector_ranking_entries: List[SectorRankingEntry]) -> CapitalFlowNote:
    label = "金融・銀行"
    contributions: List[tuple] = []

    tnx_q = find_quote(market.get("rates", []), "10年")
    if tnx_q is not None and tnx_q.change is not None:
        contributions.append(
            (1 if tnx_q.change > 0 else (-1 if tnx_q.change < 0 else 0), f"米10年金利が前日比{tnx_q.change:+.3f}")
        )

    usdjpy_pct = _quote_change_pct(market.get("forex", []), "米ドル/円")
    if usdjpy_pct is not None:
        contributions.append((1 if usdjpy_pct >= 0 else -1, f"ドル円が前日比{usdjpy_pct:+.2f}%"))

    matched_sectors = [
        e.label for e in sector_ranking_entries if any(kw in e.label for kw in CAPITAL_FLOW_SECTOR_KEYWORDS[label])
    ]
    if matched_sectors:
        contributions.append((1, f"Sector Rankingでも{'、'.join(matched_sectors)}が上位に確認できる"))

    return _capital_flow_note(label, contributions, [], matched_sectors)


def _capital_flow_defense_infra(
    theme_momentum: List[ThemeMomentumEntry],
    early_signals: List[EarlySignalEntry],
    megatrend_map: Dict[str, MegatrendEntry],
) -> CapitalFlowNote:
    label = "防衛・電力・インフラ"
    macro_labels = CAPITAL_FLOW_MACRO_LABELS[label]
    contributions: List[tuple] = []

    momentum_entries = _momentum_entries_for(theme_momentum, macro_labels)
    accel = [tm for tm in momentum_entries if tm.momentum_label in ("急加速", "加速")]
    if accel:
        contributions.append((1, f"{'、'.join(tm.label for tm in accel)}のTheme Momentum Scoreが高め"))

    signal_entries = _early_signal_entries_for(early_signals, macro_labels)
    if signal_entries:
        contributions.append((1, f"{'、'.join(es.label for es in signal_entries)}がEarly Signal Detectionにも該当"))

    durable_labels = [lbl for lbl in macro_labels if megatrend_map.get(lbl) and megatrend_map[lbl].continuity == "高い"]
    if durable_labels:
        contributions.append((1, f"{'、'.join(durable_labels)}は継続性の高い構造的テーマに位置づけられる"))

    return _capital_flow_note(
        label, contributions, [tm.label for tm in momentum_entries], _related_sectors_from_momentum(momentum_entries)
    )


def _capital_flow_domestic_demand(market: Dict, sector_ranking_entries: List[SectorRankingEntry]) -> CapitalFlowNote:
    label = "内需・消費"
    contributions: List[tuple] = []

    usdjpy_pct = _quote_change_pct(market.get("forex", []), "米ドル/円")
    if usdjpy_pct is not None:
        direction_txt = "円高" if usdjpy_pct < 0 else "円安"
        contributions.append((1 if usdjpy_pct < 0 else -1, f"ドル円が前日比{usdjpy_pct:+.2f}%（{direction_txt}方向）"))

    matched_sectors = [
        e.label for e in sector_ranking_entries if any(kw in e.label for kw in CAPITAL_FLOW_SECTOR_KEYWORDS[label])
    ]
    if matched_sectors:
        contributions.append((1, f"Sector Rankingでも{'、'.join(matched_sectors)}が上位に確認できる"))

    return _capital_flow_note(label, contributions, [], matched_sectors)


def _capital_flow_commodities(
    market: Dict, theme_momentum: List[ThemeMomentumEntry], early_signals: List[EarlySignalEntry]
) -> CapitalFlowNote:
    label = "コモディティ・資源"
    macro_labels = CAPITAL_FLOW_MACRO_LABELS[label]
    contributions: List[tuple] = []

    wti_pct = _quote_change_pct(market.get("commodities", []), "WTI")
    if wti_pct is not None:
        contributions.append((1 if wti_pct >= 0 else -1, f"WTI原油が前日比{wti_pct:+.2f}%"))

    gold_pct = _quote_change_pct(market.get("commodities", []), "金")
    if gold_pct is not None:
        contributions.append((1 if gold_pct >= 0 else -1, f"金先物が前日比{gold_pct:+.2f}%"))

    momentum_entries = _momentum_entries_for(theme_momentum, macro_labels)
    accel = [tm for tm in momentum_entries if tm.momentum_label in ("急加速", "加速")]
    if accel:
        contributions.append((1, f"{'、'.join(tm.label for tm in accel)}のTheme Momentum Scoreが高め"))

    signal_entries = _early_signal_entries_for(early_signals, macro_labels)
    if signal_entries:
        contributions.append((1, f"{'、'.join(es.label for es in signal_entries)}がEarly Signal Detectionにも該当"))

    return _capital_flow_note(
        label, contributions, [tm.label for tm in momentum_entries], _related_sectors_from_momentum(momentum_entries)
    )


def _build_capital_flow_notes(
    market: Dict,
    theme_momentum: List[ThemeMomentumEntry],
    early_signals: List[EarlySignalEntry],
    sector_ranking_entries: List[SectorRankingEntry],
    megatrend_map: Dict[str, MegatrendEntry],
) -> List[CapitalFlowNote]:
    """「世界のお金の流れ（市場シグナルベース）」の5テーマ分を組み立てる。

    実際の資金流入額・機関投資家ポジションは取得していないため、公開市場
    データ（指数・為替・金利・コモディティ）とTheme Momentum Score・
    Early Signal Detection・Sector Ranking・durable_themesという既存
    シグナルのみから、資金の「向かいやすさ」を機械的に推定する。
    """
    return [
        _capital_flow_ai_semicon(market, theme_momentum, early_signals),
        _capital_flow_financials(market, sector_ranking_entries),
        _capital_flow_defense_infra(theme_momentum, early_signals, megatrend_map),
        _capital_flow_domestic_demand(market, sector_ranking_entries),
        _capital_flow_commodities(market, theme_momentum, early_signals),
    ]


def _catalyst_bullets(
    rule: Optional[CausalRule],
    momentum: ThemeMomentumEntry,
    durable: bool,
    early_signal_exists: bool,
    focus_regions: List[str],
    capital_flow: Optional[CapitalFlowNote],
) -> List[str]:
    """Catalyst（加速要因）をAI分析として組み立てる。ニュース・causal_rules・
    durable_themes・Early Signal Detection・国家戦略メモ・世界のお金の
    流れという既存シグナルのみから機械的に導き、具体的な数値・企業業績・
    政策名の断定はしない。
    """
    bullets: List[str] = []
    if rule and rule.note:
        bullets.append(f"causal_rulesが示す押し上げ要因: {rule.note}")
    if rule and rule.beneficiary_sectors:
        bullets.append(f"{'、'.join(rule.beneficiary_sectors)}への設備投資・需要拡大が続くこと")
    if momentum.momentum_label in ("急加速", "加速"):
        bullets.append("本日のニュース増加・Theme Momentum Scoreの上昇傾向が続くこと")
    if early_signal_exists:
        bullets.append("Early Signal Detectionで捕捉された初動が本格化すること")
    if durable:
        bullets.append("構造的テーマとしての継続性が意識され続けること")
    if focus_regions:
        bullets.append(f"{'、'.join(focus_regions)}などの政策的な重点分野として位置づけが強まること")
    if capital_flow is not None and capital_flow.direction_label == "流入しやすい":
        bullets.append("市場シグナル上、資金が向かいやすい地合いが続くこと")
    if not bullets:
        bullets.append("現時点では明確な加速要因は確認できていません（判断材料不足）")
    return bullets


def _risk_bullets(
    megatrend: MegatrendEntry,
    momentum: ThemeMomentumEntry,
    durable: bool,
    capital_flow: Optional[CapitalFlowNote],
) -> List[str]:
    """Risk（失速要因）をAI分析として組み立てる。Theme Momentum・durable_themes
    ・世界のお金の流れという既存シグナルのみから機械的に導き、具体的な数値・
    企業業績・政策名の断定はしない。外部環境変化は常に一般的な留意点として
    明記する（本コードベースの他モジュールと同じ慣例）。
    """
    bullets: List[str] = []
    if momentum.momentum_label == "減速":
        bullets.append("本日時点でTheme Momentum Scoreが低く、話題化の停滞が意識されやすいこと")
    if not durable:
        bullets.append("一過性の話題に留まり、構造的テーマとして定着しない可能性")
    if megatrend.phase in ("成熟期", "減速期"):
        bullets.append("テーマの成熟・鈍化に伴う材料出尽くし感")
    if capital_flow is not None and capital_flow.direction_label == "流出しやすい":
        bullets.append("市場シグナル上、資金が離れやすい地合いに転じること")
    bullets.append("金利動向・規制動向など外部環境の変化")
    return bullets


def _confidence_score(
    headline_count: int,
    exec_summary_matched: bool,
    top_news_matched: bool,
    momentum: ThemeMomentumEntry,
    early_signal_exists: bool,
    durable: bool,
    rule_matched: bool,
    sector_ranking_matched: bool,
    supply_chain_resolved: bool,
    national_strategy_matched: bool,
    capital_flow_matched: bool,
) -> tuple:
    """Confidence Score（0〜100）。「未来が当たる確率」ではなく、既存シグナル
    のうち実際に確認できたものの数（＝分析根拠の充実度）を機械的に加点する。
    """
    score = 0
    basis: List[str] = []
    if headline_count >= 2:
        score += 15
        basis.append("ニュース多数")
    elif headline_count == 1:
        score += 8
        basis.append("ニュースあり")
    if exec_summary_matched:
        score += 15
        basis.append("Executive Summary一致")
    elif top_news_matched:
        score += 8
        basis.append("重要ニュース一致")
    if momentum.momentum_label in ("急加速", "加速"):
        score += 10
        basis.append("Momentum高")
    if early_signal_exists:
        score += 10
        basis.append("Early Signal該当")
    if durable:
        score += 15
        basis.append("durable_theme")
    if rule_matched:
        score += 15
        basis.append("causal_rules一致")
    if sector_ranking_matched:
        score += 5
        basis.append("Sector Ranking該当")
    if supply_chain_resolved:
        score += 5
        basis.append("サプライチェーン解決")
    if national_strategy_matched:
        score += 5
        basis.append("国家戦略メモ該当")
    if capital_flow_matched:
        score += 5
        basis.append("資金フローシグナル該当")
    return min(100, score), basis


def _build_theme_diagnosis(
    megatrends: List[MegatrendEntry],
    theme_momentum: List[ThemeMomentumEntry],
    theme_rule_map: Dict[str, Optional[CausalRule]],
    theme_beneficiary_names_map: Dict[str, List[str]],
    early_signals: List[EarlySignalEntry],
    national_strategy_notes: List[NationalStrategyNote],
    capital_flow_notes: List[CapitalFlowNote],
    sector_ranking_entries: List[SectorRankingEntry],
    theme_exec_summary_matched_map: Dict[str, bool],
    theme_top_news_matched_map: Dict[str, bool],
    theme_relations_cfg: Dict[str, List[str]],
) -> List[ThemeDiagnosisEntry]:
    """テーマ別診断（Momentum→Lifecycle→Catalyst→Risk→Confidence）を組み立てる。

    投資家が長期の資産形成・投資判断に使うことを最優先目的とし、
    macro_themeごとにCatalyst（加速要因）・Risk（失速要因）・Confidence
    Score（分析根拠の充実度）を、既存シグナルのみから機械的に導出する。
    related_themesは、config.yamlのtheme_relations（人手によるテーマ同士の
    対応付け）をそのまま参照するのみで、新たな未来予測ロジックではない
    （v1.8）。
    """
    momentum_map = {tm.label: tm for tm in theme_momentum}
    early_signal_labels = {es.label for es in early_signals}
    configured_labels = {m.label for m in megatrends}
    capital_flow_map: Dict[str, CapitalFlowNote] = {}
    for cf in capital_flow_notes:
        for t in cf.related_themes:
            capital_flow_map[t] = cf
    focus_regions_map: Dict[str, List[str]] = {}
    for ns in national_strategy_notes:
        for t in ns.focus_areas:
            focus_regions_map.setdefault(t, []).append(ns.region)

    entries: List[ThemeDiagnosisEntry] = []
    for m in megatrends:
        label = m.label
        momentum = momentum_map.get(label)
        if momentum is None:
            continue
        rule = theme_rule_map.get(label)
        durable = m.continuity == "高い"
        early_signal_exists = label in early_signal_labels
        beneficiary_names = theme_beneficiary_names_map.get(label, [])
        capital_flow = capital_flow_map.get(label)
        focus_regions = focus_regions_map.get(label, [])
        related_themes = [t for t in theme_relations_cfg.get(label, []) if t in configured_labels and t != label]
        sector_ranking_matched = bool(
            rule
            and rule.beneficiary_sectors
            and any(any(sec in e.label for sec in rule.beneficiary_sectors) for e in sector_ranking_entries)
        )

        confidence_score, confidence_basis = _confidence_score(
            m.headline_count,
            theme_exec_summary_matched_map.get(label, False),
            theme_top_news_matched_map.get(label, False),
            momentum,
            early_signal_exists,
            durable,
            rule is not None,
            sector_ranking_matched,
            bool(beneficiary_names),
            bool(focus_regions),
            capital_flow is not None,
        )

        entries.append(
            ThemeDiagnosisEntry(
                label=label,
                momentum_score=momentum.momentum_score,
                momentum_label=momentum.momentum_label,
                phase=m.phase,
                continuity=m.continuity,
                related_themes=related_themes,
                catalysts=_catalyst_bullets(rule, momentum, durable, early_signal_exists, focus_regions, capital_flow),
                risks=_risk_bullets(m, momentum, durable, capital_flow),
                confidence_score=confidence_score,
                confidence_basis=confidence_basis,
            )
        )
    return entries


_WATCHLIST_JUDGMENT_LABELS = ("注目継続", "押し目待ち", "過熱警戒", "材料待ち", "判断材料不足")


def _ticker_theme_map(theme_rule_map: Dict[str, Optional[CausalRule]], sectors: Dict) -> Dict[str, List[str]]:
    """テーマ→beneficiary_sectors→related_tickers という既存のcausal_rules
    恩恵銘柄ロジックだけを使って、ティッカー→関連テーマの対応表を作る
    （新たな銘柄・因果関係の推定は行わない）。
    """
    mapping: Dict[str, List[str]] = {}
    for label, rule in theme_rule_map.items():
        if rule is None or not rule.beneficiary_sectors:
            continue
        for ticker in resolve_tickers(rule.beneficiary_sectors, sectors):
            mapping.setdefault(ticker, []).append(label)
    return mapping


def _watchlist_judgment_label(momentum_label: str, phase: str, continuity: str, confidence_score: int) -> str:
    """断定的な売買助言（「買い」「売り」）は行わず、Momentum・Lifecycle・
    Confidenceという既存シグナルのみから、注目継続／押し目待ち／過熱警戒／
    材料待ち／判断材料不足のいずれかを機械的に判定する。
    """
    if confidence_score < 20:
        return "判断材料不足"
    if momentum_label == "急加速" and phase in ("成熟期", "減速期"):
        return "過熱警戒"
    if momentum_label in ("急加速", "加速"):
        return "注目継続"
    if momentum_label in ("横ばい", "減速") and continuity == "高い":
        return "押し目待ち"
    return "材料待ち"


def _watchlist_judgment_reason(
    judgment_label: str, momentum_score: int, momentum_label: str, phase: str, continuity: str, confidence_score: int
) -> str:
    return (
        f"Momentumは{momentum_label}（{momentum_score}/100）、Lifecycleは{phase}"
        f"（継続性: {continuity}）、Confidenceは{confidence_score}%であることから、"
        f"「{judgment_label}」と考えられます（断定的な売買判断ではありません）。"
    )


def _stock_why_long_term(theme_label: str, catalysts: List[str], phase: str, momentum_label: str) -> str:
    """「なぜ長期で見るのか」。テーマ名・Catalyst・Lifecycle・Momentumという
    既存シグナルのみから機械的に組み立てる（AIによる作文ではない）。
    """
    driver = catalysts[0] if catalysts else f"「{theme_label}」に関連する構造的な需要"
    return (
        f"「{theme_label}」というテーマの拡大が続く限り、{driver}ことから、"
        f"関連需要は構造的に増える可能性があると考えられます"
        f"（現在のフェーズ: {phase}、Momentum: {momentum_label}）。"
    )


# 「今後注目するイベント」の機械的な対応表（人手による参考情報。AIが
# 予測したものではない）。macro_themeのラベルと一致する場合のみ追加する。
_STOCK_EVENT_THEME_MAP: Dict[str, str] = {
    "半導体": "半導体市況",
    "電力": "電力需給",
    "金利": "金利動向",
    "為替": "為替動向",
    "GX": "政府政策（GX関連）",
    "防衛": "政府政策（防衛予算）",
    "資源": "資源価格動向",
    "EV": "EV需要動向",
    "自動車": "自動車販売動向",
    "資源・エネルギー": "資源価格動向",
}


def _stock_watch_events(primary_label: str, related_themes: List[str]) -> List[str]:
    """「今後注目するイベント」。既存テーマから機械的に導けるイベントのみを
    列挙し、AIによる新たな予測は行わない。決算・設備投資動向はどの銘柄
    にも共通する一般的な確認事項として常に含める。
    """
    events = ["決算", "設備投資動向"]
    for label in [primary_label] + related_themes:
        event = _STOCK_EVENT_THEME_MAP.get(label)
        if event and event not in events:
            events.append(event)
    return events


def _stock_investment_story(primary_label: str, catalysts: List[str], cross_theme_chain: List[str]) -> List[str]:
    """「投資ストーリー」。既存のテーマ名・Catalyst・関連テーマ（cross theme
    mapping）だけを時系列の因果チェーンとして並べる。目標株価・PER/EPS
    予想・売買推奨・期待リターンなど新たな未来予測は一切生成しない。
    """
    steps = [primary_label]
    for c in catalysts[:2]:
        steps.append(c)
    if cross_theme_chain:
        steps.append(f"{'・'.join(cross_theme_chain)}への波及")
    steps.append(
        "関連需要の増加を通じて、収益機会につながる可能性があると考えられます"
        "（将来の株価・業績を保証するものではありません）"
    )
    return steps


def _thesis_expected_change(label: str, catalysts: List[str]) -> str:
    """「今後起こりそうな変化」。テーマ別診断のCatalyst（既存シグナル）を
    非断定的に言い換えるだけの機械的な整理であり、AIによる新たな未来予測
    ではない。Catalystが「判断材料不足」の場合はそのまま正直に表示する。
    """
    if not catalysts or "判断材料不足" in catalysts[0]:
        return "本日時点で確認できる加速要因（Catalyst）がないため、分析材料不足です（新たな予測は行いません）。"
    return (
        f"Catalyst「{catalysts[0]}」が実現する場合、「{label}」関連の需要・物色が"
        "広がりやすくなる可能性があります（既存シグナルの機械的な整理であり、断定ではありません）。"
    )


def _thesis_watch_indicators(label: str, related_themes: List[str]) -> List[str]:
    """「監視指標」。本システムが毎日算出しているシグナルと、既存の
    テーマ→イベント対応表（_STOCK_EVENT_THEME_MAP）だけから機械的に列挙する。
    """
    indicators = ["Theme Momentum Scoreの推移", "関連ニュース件数の変化"]
    for theme in [label] + related_themes:
        event = _STOCK_EVENT_THEME_MAP.get(theme)
        if event and event not in indicators:
            indicators.append(event)
    return indicators


def _related_beneficiary_names(
    related_themes: List[str],
    theme_beneficiary_names_map: Dict[str, List[str]],
    exclude: set,
) -> List[str]:
    """theme_relationsで隣接するテーマの恩恵企業を集める（既存の恩恵銘柄
    ロジックの結果を参照するだけで、新たな銘柄推定は行わない）。"""
    names: List[str] = []
    for theme in related_themes:
        for name in theme_beneficiary_names_map.get(theme, []):
            if name != "など" and name not in exclude and name not in names:
                names.append(name)
    return names[:MAX_TICKERS_DISPLAYED]


def _build_investment_theses(
    theme_diagnosis: List[ThemeDiagnosisEntry],
    theme_momentum: List[ThemeMomentumEntry],
    theme_rule_map: Dict[str, Optional[CausalRule]],
    theme_beneficiary_names_map: Dict[str, List[str]],
    horizon_map: Dict[str, List[str]],
) -> List[InvestmentThesisEntry]:
    """Investment Thesis（v2.4）: macro_themeごとの長期投資仮説を組み立てる。

    すべて既存シグナル（Theme Momentum・Lifecycle・Catalyst・Risk・
    Confidence・causal_rules・theme_relations・中長期テーマ割り付け）の
    転記・機械的な組み合わせのみで構成し、AIによる新たな未来予測・
    目標株価・売買推奨・期待リターンは一切生成しない。
    表示はConfidence（分析根拠の充実度）の高い順とする。
    """
    momentum_map = {tm.label: tm for tm in theme_momentum}
    diagnosis_map = {td.label: td for td in theme_diagnosis}

    theses: List[InvestmentThesisEntry] = []
    for td in theme_diagnosis:
        momentum = momentum_map.get(td.label)
        rule = theme_rule_map.get(td.label)
        primary_names = [n for n in theme_beneficiary_names_map.get(td.label, []) if n != "など"]

        # 二次的恩恵企業: theme_relationsで1段階隣接するテーマの恩恵企業
        secondary_names = _related_beneficiary_names(
            td.related_themes, theme_beneficiary_names_map, exclude=set(primary_names)
        )
        # まだ注目されにくい企業: 2段階離れたテーマの恩恵企業（1段階目・直接分は除外）
        second_hop_themes: List[str] = []
        for rel in td.related_themes:
            rel_diag = diagnosis_map.get(rel)
            for hop2 in rel_diag.related_themes if rel_diag else []:
                if hop2 != td.label and hop2 not in td.related_themes and hop2 not in second_hop_themes:
                    second_hop_themes.append(hop2)
        less_watched = _related_beneficiary_names(
            second_hop_themes, theme_beneficiary_names_map, exclude=set(primary_names) | set(secondary_names)
        )

        theses.append(
            InvestmentThesisEntry(
                label=td.label,
                current_situation=momentum.reason if momentum else "本日算出できるシグナルがありませんでした（分析材料不足）。",
                expected_change=_thesis_expected_change(td.label, td.catalysts),
                beneficiary_industries=list(rule.beneficiary_sectors) if rule and rule.beneficiary_sectors else [],
                beneficiary_names=primary_names,
                secondary_beneficiary_names=secondary_names,
                less_watched_names=less_watched,
                horizons=[h for h, themes in horizon_map.items() if td.label in themes],
                watch_indicators=_thesis_watch_indicators(td.label, td.related_themes),
                breakdown_conditions=list(td.risks),
                thesis_summary=_stock_investment_story(td.label, td.catalysts, td.related_themes),
                momentum_score=td.momentum_score,
                momentum_label=td.momentum_label,
                phase=td.phase,
                continuity=td.continuity,
                confidence_score=td.confidence_score,
            )
        )
    theses.sort(key=lambda t: -t.confidence_score)
    return theses


def _build_watchlist_intelligence(
    config: dict,
    sectors: Dict,
    theme_rule_map: Dict[str, Optional[CausalRule]],
    theme_diagnosis: List[ThemeDiagnosisEntry],
) -> tuple:
    """Watchlist Intelligence: config.yaml の watchlist 銘柄とテーマ別診断
    （v1.6）を、既存のcausal_rules恩恵銘柄ロジックだけで照合する。
    営業利用ではなく自分自身の長期投資判断を最優先目的とし、
    「買い」「売り」等の断定的な売買助言は一切行わない。

    あわせて、一致した銘柄のみを対象にStock Intelligence（v2.0）を
    組み立てる。Watchlist Intelligenceと同じmomentum_score等をそのまま
    引き継ぐことで、両セクション間の整合性を保つ。
    """
    watchlist_cfg = config.get("watchlist", {})
    stocks = list(watchlist_cfg.get("jp_stocks", [])) + list(watchlist_cfg.get("us_stocks", []))
    if not stocks:
        return [], []

    ticker_theme_map = _ticker_theme_map(theme_rule_map, sectors)
    diagnosis_map = {td.label: td for td in theme_diagnosis}

    watchlist_entries: List[WatchlistIntelligenceEntry] = []
    stock_entries: List[StockIntelligenceEntry] = []
    for stock in stocks:
        ticker = stock.get("ticker", "")
        name = stock.get("name", ticker)
        related_labels = ticker_theme_map.get(ticker, [])
        candidates = [diagnosis_map[label] for label in related_labels if label in diagnosis_map]

        if not candidates:
            watchlist_entries.append(
                WatchlistIntelligenceEntry(
                    name=name,
                    ticker=ticker,
                    related_themes=related_labels,
                    judgment_label="判断材料不足",
                    judgment_reason="現時点で一致するFuture Intelligenceのテーマ診断が確認できませんでした。",
                )
            )
            continue

        # 複数テーマに一致する場合は、Confidence（分析根拠の充実度）が
        # 最も高いテーマを代表として採用する。
        top = max(candidates, key=lambda td: td.confidence_score)
        judgment_label = _watchlist_judgment_label(top.momentum_label, top.phase, top.continuity, top.confidence_score)
        related_theme_labels = [c.label for c in candidates]
        watchlist_entries.append(
            WatchlistIntelligenceEntry(
                name=name,
                ticker=ticker,
                related_themes=related_theme_labels,
                momentum_score=top.momentum_score,
                momentum_label=top.momentum_label,
                phase=top.phase,
                continuity=top.continuity,
                catalysts=top.catalysts,
                risks=top.risks,
                confidence_score=top.confidence_score,
                judgment_label=judgment_label,
                judgment_reason=_watchlist_judgment_reason(
                    judgment_label, top.momentum_score, top.momentum_label, top.phase, top.continuity, top.confidence_score
                ),
            )
        )

        # Stock Intelligence（v2.0）: Watchlist Intelligenceで一致した
        # 銘柄のみを対象に、既存シグナルの機械的な組み立てのみで構成する。
        expanded_risks: List[str] = []
        for c in candidates:
            for r in c.risks:
                if r not in expanded_risks:
                    expanded_risks.append(r)
        stock_entries.append(
            StockIntelligenceEntry(
                name=name,
                ticker=ticker,
                related_themes=related_theme_labels,
                primary_theme=top.label,
                momentum_score=top.momentum_score,
                momentum_label=top.momentum_label,
                phase=top.phase,
                continuity=top.continuity,
                catalysts=top.catalysts,
                risks=expanded_risks,
                confidence_score=top.confidence_score,
                judgment_label=judgment_label,
                why_long_term=_stock_why_long_term(top.label, top.catalysts, top.phase, top.momentum_label),
                watch_events=_stock_watch_events(top.label, related_theme_labels),
                cross_theme_chain=top.related_themes,
                investment_story=_stock_investment_story(top.label, top.catalysts, top.related_themes),
            )
        )
    return watchlist_entries, stock_entries


def build_future_intelligence(
    headlines: List[Headline],
    config: dict,
    sectors: Dict,
    ticker_lookup: Dict,
    news_ranking_items: Optional[List[NewsRankingItem]] = None,
    executive_summary_items: Optional[List[ExecutiveSummaryItem]] = None,
    market: Optional[Dict] = None,
    sector_ranking_entries: Optional[List[SectorRankingEntry]] = None,
    rashinban: Optional[RashinbanKnowledge] = None,
    theme_win_rates: Optional[Dict[str, float]] = None,
) -> FutureIntelligenceBundle:
    market = market or {}
    sector_ranking_entries = sector_ranking_entries or []
    macro_themes_cfg = config.get("macro_themes", [])
    durable_themes = config.get("durable_themes", [])
    causal_rules = parse_causal_rules(config.get("causal_rules", []))

    top_news_titles = [item.headline.title for item in (news_ranking_items or [])[:TOP_NEWS_FOR_MOMENTUM]]
    exec_summary_titles = [item.headline.title for item in (executive_summary_items or [])]

    megatrends: List[MegatrendEntry] = []
    theme_momentum: List[ThemeMomentumEntry] = []
    theme_rule_map: Dict[str, Optional[CausalRule]] = {}
    theme_keywords_map: Dict[str, List[str]] = {}
    theme_exec_summary_matched_map: Dict[str, bool] = {}
    theme_top_news_matched_map: Dict[str, bool] = {}

    for entry in macro_themes_cfg:
        label = entry.get("label", "")
        keywords = entry.get("keywords") or [label]
        theme_keywords_map[label] = keywords

        count = _matched_headline_count(headlines, keywords)
        level = _hit_level(count)
        durable = any(kw in durable_themes for kw in keywords) or label in durable_themes
        rule = _matched_causal_rule(keywords, causal_rules)
        theme_rule_map[label] = rule

        megatrends.append(
            MegatrendEntry(
                label=label,
                stars=stars(_STAR_TABLE[(durable, level)], max_stars=5),
                headline_count=count,
                why_growing=_why_growing(rule),
                phase=_PHASE_TABLE[(durable, level)],
                continuity=_continuity_label(durable, level),
            )
        )

        # Theme Momentum Scoreの「関連セクター・関連銘柄の有無」判定用に、
        # 既存のcausal_rules恩恵銘柄ロジックをそのまま再利用する（v1.4）。
        related_sector_text = "、".join(rule.beneficiary_sectors) if rule and rule.beneficiary_sectors else ""
        momentum_beneficiary_names: List[str] = []
        if rule and rule.beneficiary_sectors:
            momentum_names = ticker_names(resolve_tickers(rule.beneficiary_sectors, sectors), ticker_lookup)
            momentum_beneficiary_names = momentum_names[:MAX_TICKERS_DISPLAYED]
            if len(momentum_names) > MAX_TICKERS_DISPLAYED:
                momentum_beneficiary_names = momentum_beneficiary_names + ["など"]

        top_news_matched = any(kw in title for kw in keywords for title in top_news_titles)
        exec_summary_matched = any(kw in title for kw in keywords for title in exec_summary_titles)
        theme_top_news_matched_map[label] = top_news_matched
        theme_exec_summary_matched_map[label] = exec_summary_matched
        has_beneficiary = bool(momentum_beneficiary_names)
        score = _momentum_score(count, rule is not None, durable, top_news_matched, exec_summary_matched, has_beneficiary)
        theme_momentum.append(
            ThemeMomentumEntry(
                label=label,
                momentum_score=score,
                momentum_label=_momentum_label(score),
                reason=_momentum_reason(
                    count, rule is not None, durable, top_news_matched, exec_summary_matched, has_beneficiary, megatrends[-1]
                ),
                related_sector=related_sector_text,
                beneficiary_names=momentum_beneficiary_names,
            )
        )

    # ⑤ 次に来る業界ランキング（本日のモメンタム＝関連見出し件数の多い順）
    ranked = sorted(megatrends, key=lambda m: m.headline_count, reverse=True)
    industry_momentum = [
        IndustryMomentumEntry(rank=i, label=m.label, headline_count=m.headline_count, reason=m.why_growing)
        for i, m in enumerate((m for m in ranked if m.headline_count > 0), start=1)
        if i <= TOP_INDUSTRY_MOMENTUM
    ]

    # ⑥ サプライチェーン分析／⑩ 日本株への波及（既存causal_rulesの恩恵銘柄をそのまま利用）
    # ／Early Signal Detection（見出しが少ない段階の初動シグナル抽出）
    supply_chains: List[SupplyChainNote] = []
    jp_stock_impact: List[JpStockImpactEntry] = []
    early_signals: List[EarlySignalEntry] = []
    theme_beneficiary_names_map: Dict[str, List[str]] = {}
    for m in megatrends:
        rule = theme_rule_map.get(m.label)
        if rule is None or not rule.beneficiary_sectors:
            continue
        beneficiary_tickers = resolve_tickers(rule.beneficiary_sectors, sectors)
        names = ticker_names(beneficiary_tickers, ticker_lookup)
        names_display = names[:MAX_TICKERS_DISPLAYED]
        if len(names) > MAX_TICKERS_DISPLAYED:
            names_display = names_display + ["など"]
        theme_beneficiary_names_map[m.label] = names_display
        chain_parts = [m.label] + rule.beneficiary_sectors + (names_display if names else [])
        supply_chains.append(SupplyChainNote(theme=m.label, chain_text=" → ".join(chain_parts)))
        if names:
            jp_stock_impact.append(JpStockImpactEntry(theme=m.label, beneficiary_names=names_display))

        durable = m.continuity == "高い"
        if _is_early_signal(m.headline_count, rule, durable, beneficiary_tickers):
            early_signals.append(
                EarlySignalEntry(
                    label=m.label,
                    stars=stars(_early_signal_stars(durable, beneficiary_tickers), max_stars=5),
                    reason=(
                        f"本日の関連見出しは{m.headline_count}件とまだ少ないものの、"
                        "既存の因果チェーン（causal_rules）・継続性の高い構造的テーマ・"
                        "サプライチェーンへの波及先（恩恵銘柄）がいずれも確認できるため、"
                        "初動シグナルとして注目できると考えられます。"
                    ),
                    related_sector="、".join(rule.beneficiary_sectors),
                    beneficiary_names=names_display,
                    sales_talk=_early_signal_sales_talk(m.label, rule.beneficiary_sectors, names_display),
                )
            )

    # ⑨ 中長期テーマ（半年/1年/3年/5年/10年への定性的な割り付け）
    horizon_labels = ["半年", "1年", "3年", "5年", "10年"]
    horizon_map: Dict[str, List[str]] = {h: [] for h in horizon_labels}
    for m in megatrends:
        durable = m.continuity == "高い"
        active = m.headline_count > 0
        if durable:
            for h in ("3年", "5年", "10年"):
                horizon_map[h].append(m.label)
            if active:
                for h in ("半年", "1年"):
                    horizon_map[h].append(m.label)
        elif active:
            for h in ("半年", "1年"):
                horizon_map[h].append(m.label)
    horizon_groups = [HorizonThemeGroup(horizon=h, themes=horizon_map[h]) for h in horizon_labels]

    # テーマ成熟度メモ／国家戦略メモ（登録情報を優先、無ければ既存シグナルからAI分析）
    megatrend_map = {m.label: m for m in megatrends}
    theme_maturity_notes = _build_theme_maturity_notes(
        macro_themes_cfg,
        config.get("theme_maturity_notes", {}),
        megatrend_map,
        theme_rule_map,
        theme_beneficiary_names_map,
    )
    national_strategy_notes = _build_national_strategy_notes(
        config.get("national_strategy_notes", {}), megatrend_map, theme_rule_map
    )

    # 世界のお金の流れ（市場シグナルベース。実際の資金流入額は取得していないため断定しない）
    capital_flow_notes = _build_capital_flow_notes(
        market, theme_momentum, early_signals, sector_ranking_entries, megatrend_map
    )
    capital_flow_market_mood = _capital_flow_market_mood(market)

    # テーマ別診断（Momentum→Lifecycle→Catalyst→Risk→Confidence）。
    # 投資家の長期の資産形成・投資判断を最優先目的とする（v1.6）。
    theme_diagnosis = _build_theme_diagnosis(
        megatrends,
        theme_momentum,
        theme_rule_map,
        theme_beneficiary_names_map,
        early_signals,
        national_strategy_notes,
        capital_flow_notes,
        sector_ranking_entries,
        theme_exec_summary_matched_map,
        theme_top_news_matched_map,
        config.get("theme_relations", {}),
    )

    # v2.8: Theme Confidence Learning による実績補正（過去勝率が与えられた時のみ）。
    # 既存のConfidence計算式・順位ロジックは変更せず、上下限つき（-20〜+10）の
    # 小さな調整を後段で加えるだけ。補正結果はInvestment Thesis等にも波及する。
    if theme_win_rates:
        for td in theme_diagnosis:
            adj = confidence_adjustment(theme_win_rates.get(td.label))
            if adj != 0:
                td.confidence_score = max(0, min(100, td.confidence_score + adj))
                wr_pct = round(theme_win_rates[td.label] * 100)
                td.confidence_basis.append(f"過去勝率{wr_pct}%による実績補正（{adj:+d}）")

    # Watchlist Intelligence: watchlist銘柄とテーマ別診断の照合（v1.7）。
    # 営業利用ではなく自分自身の長期投資判断を最優先目的とする。
    # あわせて、一致した銘柄のみを対象にStock Intelligence（v2.0）を組み立てる。
    watchlist_intelligence, stock_intelligence = _build_watchlist_intelligence(
        config, sectors, theme_rule_map, theme_diagnosis
    )

    # Investment Thesis: macro_themeごとの長期投資仮説（v2.4）。
    # 既存シグナルの転記・機械的な組み合わせのみで、新たな予測は行わない。
    investment_theses = _build_investment_theses(
        theme_diagnosis, theme_momentum, theme_rule_map, theme_beneficiary_names_map, horizon_map
    )

    # v2.6: 岡三「羅針盤」（学習ソース）の重点テーマに一致する場合のみ、
    # Theme Momentumの理由とInvestment Thesisの監視指標へ参照した旨を補足する
    # （本文転載はしない。スコア・順位の計算方法は変更しない）。
    if rashinban and rashinban.emphasized_theme_labels:
        emphasized = set(rashinban.emphasized_theme_labels)
        for tm in theme_momentum:
            if tm.label in emphasized:
                tm.reason += "岡三「羅針盤」（学習ソース）でも重点テーマとして言及されています。"
        for thesis in investment_theses:
            if thesis.label in emphasized:
                thesis.watch_indicators.append("岡三「羅針盤」（学習ソース）の重点テーマとしての言及の継続")

    return FutureIntelligenceBundle(
        megatrends=megatrends,
        industry_momentum=industry_momentum,
        supply_chains=supply_chains,
        horizon_groups=horizon_groups,
        jp_stock_impact=jp_stock_impact,
        theme_momentum=theme_momentum,
        early_signals=early_signals,
        theme_maturity_notes=theme_maturity_notes,
        national_strategy_notes=national_strategy_notes,
        capital_flow_notes=capital_flow_notes,
        capital_flow_market_mood=capital_flow_market_mood,
        theme_diagnosis=theme_diagnosis,
        watchlist_intelligence=watchlist_intelligence,
        stock_intelligence=stock_intelligence,
        investment_theses=investment_theses,
    )
