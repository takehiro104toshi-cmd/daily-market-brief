"""Future Intelligence Engine v1.0（世界の構造変化テーマの定性分析）。

「今日のニュース」ではなく、config.yaml の macro_themes に登録した長期テーマ
（AI・半導体・電力・防衛・宇宙・量子・自動運転など）を、既存の仕組み
（本日の関連見出し件数・durable_themes・causal_rules・恩恵銘柄ロジック）
だけを使って定性的に評価する。

v1.0はグループAのみを実装する:
    ①総合（本モジュールの出力をまとめて1セクションとして表示）
    ②世界のメガトレンド（★・フェーズ・継続性・なぜ伸びるか）
    ③テーマの寿命（フェーズ＋継続性の定性ラベル。具体的な残り年数は出さない）
    ⑤次に来る業界ランキング（本日のモメンタム順）
    ⑥サプライチェーン分析（causal_rulesの因果チェーンをそのまま表示）
    ⑨中長期テーマ（半年/1年/3年/5年/10年の定性的な割り付け）
    ⑩日本株への波及（恩恵銘柄。大型/中小型は区分不明として明記）
    ⑪Future Map（②〜⑨の集約一覧）

テーマ成熟度（④）・国家戦略分析（⑧）・世界のお金の流れ（⑦）はv1.1以降に
見送る。具体的な残り年数・市場規模・補助金額等、実データの裏付けがない
数値は一切生成しない（決定論的なルールベースの定性ラベルのみ）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..collectors.news import Headline
from ..report.format_utils import stars
from .models import (
    FutureIntelligenceBundle,
    HorizonThemeGroup,
    IndustryMomentumEntry,
    JpStockImpactEntry,
    MegatrendEntry,
    SupplyChainNote,
)
from .strategist_engine import CausalRule, parse_causal_rules, resolve_tickers, ticker_names

TOP_INDUSTRY_MOMENTUM = 5
MAX_TICKERS_DISPLAYED = 5

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


def _why_growing(keywords: List[str], causal_rules: List[CausalRule]) -> str:
    rule = _matched_causal_rule(keywords, causal_rules)
    if rule and rule.note:
        return rule.note
    return "本日の関連ニュースの傾向から注目が集まっているテーマと考えられます。"


def build_future_intelligence(
    headlines: List[Headline],
    config: dict,
    sectors: Dict,
    ticker_lookup: Dict,
) -> FutureIntelligenceBundle:
    macro_themes_cfg = config.get("macro_themes", [])
    durable_themes = config.get("durable_themes", [])
    causal_rules = parse_causal_rules(config.get("causal_rules", []))

    megatrends: List[MegatrendEntry] = []
    theme_keywords_map: Dict[str, List[str]] = {}
    for entry in macro_themes_cfg:
        label = entry.get("label", "")
        keywords = entry.get("keywords") or [label]
        theme_keywords_map[label] = keywords

        count = _matched_headline_count(headlines, keywords)
        level = _hit_level(count)
        durable = any(kw in durable_themes for kw in keywords) or label in durable_themes

        megatrends.append(
            MegatrendEntry(
                label=label,
                stars=stars(_STAR_TABLE[(durable, level)], max_stars=5),
                headline_count=count,
                why_growing=_why_growing(keywords, causal_rules),
                phase=_PHASE_TABLE[(durable, level)],
                continuity=_continuity_label(durable, level),
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
    supply_chains: List[SupplyChainNote] = []
    jp_stock_impact: List[JpStockImpactEntry] = []
    for m in megatrends:
        rule = _matched_causal_rule(theme_keywords_map.get(m.label, [m.label]), causal_rules)
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

    return FutureIntelligenceBundle(
        megatrends=megatrends,
        industry_momentum=industry_momentum,
        supply_chains=supply_chains,
        horizon_groups=horizon_groups,
        jp_stock_impact=jp_stock_impact,
    )
