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

世界のお金の流れは今後の版に見送る。具体的な残り年数・市場規模・
補助金額・政策内容等、実データの裏付けがない数値・情報は一切生成しない
（決定論的なルールベースの定性ラベル、またはconfig.yamlの手動登録内容の
そのまま表示のみ）。
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
# に手動登録がない地域も、必ずこの6地域分を「未登録」として表示する。
NATIONAL_STRATEGY_REGIONS = ["日本", "米国", "中国", "EU", "インド", "中東"]

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


def _build_theme_maturity_notes(macro_themes_cfg: List[dict], notes_cfg: Dict) -> List[ThemeMaturityNote]:
    """config.yaml の theme_maturity_notes を、そのまま表示用データへ変換する。

    AIによる市場規模・普及率・競争環境・参入障壁・リスクの生成・推定は
    一切行わない。未登録のテーマ・項目はすべて「未登録」とする。
    """
    notes: List[ThemeMaturityNote] = []
    for entry in macro_themes_cfg:
        label = entry.get("label", "")
        raw = notes_cfg.get(label, {}) if isinstance(notes_cfg, dict) else {}
        notes.append(
            ThemeMaturityNote(
                label=label,
                market_stage=raw.get("market_stage") or NOT_REGISTERED,
                market_size_note=raw.get("market_size_note") or NOT_REGISTERED,
                adoption_note=raw.get("adoption_note") or NOT_REGISTERED,
                competition_note=raw.get("competition_note") or NOT_REGISTERED,
                barrier_note=raw.get("barrier_note") or NOT_REGISTERED,
                risk_note=raw.get("risk_note") or NOT_REGISTERED,
            )
        )
    return notes


def _build_national_strategy_notes(notes_cfg: Dict) -> List[NationalStrategyNote]:
    """config.yaml の national_strategy_notes を、そのまま表示用データへ変換する。

    AIによる補助金額・政策内容・規制内容の生成・推定は一切行わない。
    対象は日本／米国／中国／EU／インド／中東の6地域固定で、未登録の
    国・地域・項目はすべて「未登録」とする。
    """
    notes: List[NationalStrategyNote] = []
    for region in NATIONAL_STRATEGY_REGIONS:
        raw = notes_cfg.get(region, {}) if isinstance(notes_cfg, dict) else {}
        notes.append(
            NationalStrategyNote(
                region=region,
                focus_areas=list(raw.get("focus_areas", [])),
                policy_note=raw.get("policy_note") or NOT_REGISTERED,
                regulation_note=raw.get("regulation_note") or NOT_REGISTERED,
                market_impact_note=raw.get("market_impact_note") or NOT_REGISTERED,
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
    for m in megatrends:
        rule = theme_rule_map.get(m.label)
        if rule is None or not rule.beneficiary_sectors:
            continue
        beneficiary_tickers = resolve_tickers(rule.beneficiary_sectors, sectors)
        names = ticker_names(beneficiary_tickers, ticker_lookup)
        names_display = names[:MAX_TICKERS_DISPLAYED]
        if len(names) > MAX_TICKERS_DISPLAYED:
            names_display = names_display + ["など"]
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

    # テーマ成熟度メモ／国家戦略メモ（config.yamlへの手動登録内容をそのまま表示）
    theme_maturity_notes = _build_theme_maturity_notes(macro_themes_cfg, config.get("theme_maturity_notes", {}))
    national_strategy_notes = _build_national_strategy_notes(config.get("national_strategy_notes", {}))

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
