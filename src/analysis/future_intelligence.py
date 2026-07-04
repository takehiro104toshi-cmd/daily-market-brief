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

世界のお金の流れは今後の版に見送る。具体的な残り年数・市場規模・
補助金額・政策内容等、実データの裏付けがない数値・情報は一切生成しない
（決定論的なルールベースの定性ラベル、config.yamlの手動登録内容のそのまま
表示、または既存シグナルからの定性的なAI分析のみ）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..collectors.news import Headline
from ..report.format_utils import stars
from .models import (
    EarlySignalEntry,
    FutureIntelligenceBundle,
    HorizonThemeGroup,
    IndustryMomentumEntry,
    JpStockImpactEntry,
    MegatrendEntry,
    NationalStrategyNote,
    NewsRankingItem,
    SupplyChainNote,
    ThemeMaturityNote,
    ThemeMomentumEntry,
)
from .strategist_engine import CausalRule, parse_causal_rules, resolve_tickers, ticker_names

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


def _momentum_score(headline_count: int, causal_matched: bool, durable: bool, top_news_matched: bool) -> int:
    """本日の見出し密度・重要ニュースとの一致・causal_rules一致・durable_themes
    一致という既存シグナルのみから、0〜100の定性スコアを機械的に算出する。
    履歴データを保持していないため、前日比・週次比較は行わない。
    """
    score = min(headline_count, 5) * 10
    if causal_matched:
        score += 20
    if durable:
        score += 15
    if top_news_matched:
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


def _momentum_reason(headline_count: int, causal_matched: bool, durable: bool, top_news_matched: bool) -> str:
    parts = []
    if headline_count > 0:
        parts.append(f"本日{headline_count}件の関連見出しが確認されています")
    if top_news_matched:
        parts.append("本日の重要ニュースにも関連しています")
    if causal_matched:
        parts.append("既存の因果チェーン（causal_rules）にも該当します")
    if durable:
        parts.append("継続性の高い構造的テーマに位置づけられています")
    if not parts:
        parts.append("本日時点では目立った関連ニュースは確認されていません")
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


def build_future_intelligence(
    headlines: List[Headline],
    config: dict,
    sectors: Dict,
    ticker_lookup: Dict,
    news_ranking_items: Optional[List[NewsRankingItem]] = None,
) -> FutureIntelligenceBundle:
    macro_themes_cfg = config.get("macro_themes", [])
    durable_themes = config.get("durable_themes", [])
    causal_rules = parse_causal_rules(config.get("causal_rules", []))

    top_news_titles = [item.headline.title for item in (news_ranking_items or [])[:TOP_NEWS_FOR_MOMENTUM]]

    megatrends: List[MegatrendEntry] = []
    theme_momentum: List[ThemeMomentumEntry] = []
    theme_rule_map: Dict[str, Optional[CausalRule]] = {}
    theme_keywords_map: Dict[str, List[str]] = {}

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

        top_news_matched = any(kw in title for kw in keywords for title in top_news_titles)
        score = _momentum_score(count, rule is not None, durable, top_news_matched)
        theme_momentum.append(
            ThemeMomentumEntry(
                label=label,
                momentum_score=score,
                momentum_label=_momentum_label(score),
                reason=_momentum_reason(count, rule is not None, durable, top_news_matched),
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
    )
