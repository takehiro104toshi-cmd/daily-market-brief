"""「岡三ストラテジスト視点」パイプラインと8軸★スコアリングを実装する。

岡三証券 投資戦略部のストラテジストレポート（「グローバル投資の羅針盤」等）
から学習した「ニュースをどう評価し、どう投資アイデアへ変換するか」という
思考プロセスを、公開ニュース見出しに対して機械的に適用するモジュール。

学習した思考プロセス（一般化・要約。特定資料の文章の引用ではない）:
    ニュース
      ↓ 岡三ストラテジストならどう見るか（このニュースの意味づけ）
      ↓ 重要テーマ（構造的・政策的な背景を持つテーマかどうか）
      ↓ 関連セクター
      ↓ 恩恵銘柄（追い風が及ぶ業種・銘柄）
      ↓ 悪影響銘柄（逆風が及ぶ業種・銘柄）
      ↓ 営業で話すポイント
      ↓ 重要度（8軸★スコア）

スコアリングは決定論的なルールベース（生成AIではない）。
断定的な投資助言ではなく、情報整理のための考察に徹する
（「〜の可能性があります」等の非断定的な表現で統一する）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..collectors.news import Headline, _normalize_title
from ..report.format_utils import stars
from .models import NewsRankingItem, RashinbanKnowledge, StarScoreBreakdown, StrategistView

MAX_VIEWS = 5

JP_MARKET_KEYWORDS = ("日経", "東京市場", "日本株", "TOPIX", "日銀")
US_MARKET_KEYWORDS = ("米国", "NY", "ダウ", "S&P", "ナスダック", "FRB", "米国株", "米株")
SURPRISE_KEYWORDS = (
    "上方修正", "下方修正", "最高値", "最安値", "規制", "制裁", "決算",
    "提携", "買収", "増資", "上場", "撤退", "経営統合", "自社株買い",
)


@dataclass
class CausalRule:
    trigger_keywords: List[str]
    theme: str
    beneficiary_sectors: List[str]
    negative_sectors: List[str]
    durable: bool
    note: str


def parse_causal_rules(raw_rules: List[dict]) -> List[CausalRule]:
    rules: List[CausalRule] = []
    for r in raw_rules or []:
        rules.append(
            CausalRule(
                trigger_keywords=r.get("trigger_keywords", []),
                theme=r.get("theme", ""),
                beneficiary_sectors=r.get("beneficiary_sectors", []),
                negative_sectors=r.get("negative_sectors", []),
                durable=bool(r.get("durable", False)),
                note=r.get("note", ""),
            )
        )
    return rules


def match_causal_rule(headline: Headline, rules: List[CausalRule]) -> Optional[CausalRule]:
    return next((r for r in rules if any(kw in headline.title for kw in r.trigger_keywords)), None)


def matched_themes_in(headline: Headline, themes: List[str]) -> List[str]:
    return [t for t in themes if t in headline.title]


def matched_sector_name(headline: Headline, sectors: Dict) -> Optional[str]:
    for sector_name, cfg in sectors.items():
        keywords = cfg.get("keywords", []) if isinstance(cfg, dict) else cfg
        if any(kw in headline.title for kw in keywords):
            return sector_name
    return None


def sector_tickers(sector_name: str, sectors: Dict) -> List[str]:
    cfg = sectors.get(sector_name, {})
    if isinstance(cfg, dict):
        return list(cfg.get("related_tickers", []))
    return []


def resolve_tickers(sector_names: List[str], sectors: Dict) -> List[str]:
    tickers: List[str] = []
    for name in sector_names:
        for t in sector_tickers(name, sectors):
            if t not in tickers:
                tickers.append(t)
    return tickers


def ticker_names(tickers: List[str], ticker_lookup: Dict) -> List[str]:
    names = []
    for t in tickers:
        quote = ticker_lookup.get(t)
        names.append(quote.name if quote is not None else t)
    return names


def score_headline_8axis(
    headline: Headline,
    matched_themes: List[str],
    matched_sector: Optional[str],
    causal_rule: Optional[CausalRule],
    durable_themes: List[str],
    beneficiary_tickers: List[str],
    negative_tickers: List[str],
    watchlist_names: List[str],
    tank_signal: Optional[dict] = None,
) -> StarScoreBreakdown:
    """8軸（各1〜5）でニュースの重要度を評価する。

    ①市場インパクト ②継続性 ③営業利用価値 ④日本株影響度 ⑤米国株影響度
    ⑥個別株へ展開できるか ⑦テーマ株へ展開できるか ⑧今後数週間重要か

    tank_signal（v4.3・省略可能）: Data Tankの市場反応シグナル。実際の市場反応が
    確認済みのイベントは「市場インパクト」軸を+2、主要因クラスタ該当または
    市場影響度スコア0.6以上は+1する（Tank側の計測結果の転記のみ・再計算なし）。
    省略時は従来と完全に同じ採点。
    """
    has_surprise = any(kw in headline.title for kw in SURPRISE_KEYWORDS)
    has_watchlist_mention = any(name in headline.title for name in watchlist_names)
    is_durable = causal_rule is not None and causal_rule.durable
    is_durable = is_durable or any(t in durable_themes for t in matched_themes)
    n_tickers = len(beneficiary_tickers) + len(negative_tickers)

    market_impact = 2
    if has_surprise:
        market_impact += 2
    if has_watchlist_mention:
        market_impact += 1
    if tank_signal:
        if tank_signal.get("has_market_reaction"):
            market_impact += 2
        elif tank_signal.get("in_global_drivers") or tank_signal.get("market_impact_score", 0.0) >= 0.6:
            market_impact += 1

    continuity = 5 if is_durable else (3 if matched_themes else 1)

    if has_watchlist_mention:
        sales_value = 5
    elif n_tickers > 0:
        sales_value = 4
    elif matched_sector:
        sales_value = 3
    else:
        sales_value = 1

    jp_impact = 1
    if matched_sector or matched_themes:
        jp_impact = 3
    if any(kw in headline.title for kw in JP_MARKET_KEYWORDS):
        jp_impact = 5

    us_impact = 1
    if causal_rule is not None:
        us_impact = 2
    if any(kw in headline.title for kw in US_MARKET_KEYWORDS):
        us_impact = 5

    if n_tickers >= 3:
        stock_expansion = 5
    elif n_tickers >= 1:
        stock_expansion = 3
    else:
        stock_expansion = 1

    n_themes = len(matched_themes) + (1 if causal_rule else 0)
    if n_themes >= 2:
        theme_expansion = 5
    elif n_themes == 1:
        theme_expansion = 3
    else:
        theme_expansion = 1

    weeks_ahead = 5 if is_durable else (3 if matched_themes or causal_rule else 1)

    def _clip(v: int) -> int:
        return max(1, min(5, v))

    return StarScoreBreakdown(
        market_impact=_clip(market_impact),
        continuity=_clip(continuity),
        sales_value=_clip(sales_value),
        jp_impact=_clip(jp_impact),
        us_impact=_clip(us_impact),
        stock_expansion=_clip(stock_expansion),
        theme_expansion=_clip(theme_expansion),
        weeks_ahead=_clip(weeks_ahead),
    )


def _strategist_take(theme: str, sector: str, causal_rule: Optional[CausalRule]) -> str:
    if causal_rule is not None and causal_rule.note:
        return causal_rule.note
    if theme and sector:
        return f"「{theme}」というテーマの一環として、「{sector}」関連への波及が意識されやすいニュースと考えられます。"
    if theme:
        return f"「{theme}」というテーマに関連する動きとして注目されやすいニュースと考えられます。"
    if sector:
        return f"「{sector}」関連の材料として意識されやすいニュースと考えられます。"
    return "現時点では特定のテーマ・業種との明確な結びつきは確認されていません。"


def _sales_point(beneficiary_names: List[str], negative_names: List[str], sector: str) -> str:
    if beneficiary_names and negative_names:
        return (
            f"{'、'.join(beneficiary_names[:2])}などには追い風、"
            f"{'、'.join(negative_names[:2])}などには逆風が意識されやすい局面とお伝えできます。"
        )
    if beneficiary_names:
        return f"{'、'.join(beneficiary_names[:3])}など、恩恵が及びやすい銘柄として話題にできそうです。"
    if negative_names:
        return f"{'、'.join(negative_names[:3])}など、注意が必要な銘柄として話題にできそうです。"
    if sector:
        return f"「{sector}」関連の値動きを確認しておきたい局面です。"
    return "市場全体の地合いを確認する材料の一つとしてお伝えできます。"


def build_strategist_views(
    news_ranking_items: List[NewsRankingItem],
    config: dict,
    ticker_lookup: Dict,
    limit: int = MAX_VIEWS,
    rashinban: Optional[RashinbanKnowledge] = None,
    tank_signals: Optional[Dict[str, dict]] = None,
) -> List[StrategistView]:
    """news_ranking（重要度順）の上位ニュースに、8ステップのパイプラインを適用する。

    rashinban（v2.6・省略可能）: 岡三「羅針盤」学習ソースの重点テーマに
    一致するテーマの見方へ、参照した旨の一文を補足する（本文転載はしない）。
    羅針盤ファイルが無い場合はNone/空となり、従来と完全に同じ動作。

    tank_signals（v4.3・省略可能）: Data Tankの市場反応シグナル（タイトル
    正規化キー → シグナルdict）。一致した見出しは「市場インパクト」軸へ反映し、
    実際の市場反応が確認済みの場合はストラテジストの見方にも一文補足する。
    省略時（None/空）は従来と完全に同じ動作。
    """
    themes = config.get("themes", [])
    sectors = config.get("sectors", {})
    durable_themes = config.get("durable_themes", [])
    causal_rules = parse_causal_rules(config.get("causal_rules", []))

    watchlist_names = [q.name for q in ticker_lookup.values()] if ticker_lookup else []

    views: List[StrategistView] = []
    for item in news_ranking_items[:limit]:
        headline = item.headline
        matched_themes = matched_themes_in(headline, themes)
        matched_sector = matched_sector_name(headline, sectors)
        causal_rule = match_causal_rule(headline, causal_rules)

        theme = (causal_rule.theme if causal_rule else "") or (matched_themes[0] if matched_themes else "") or "特定テーマなし"
        sector = matched_sector or (
            "、".join(causal_rule.beneficiary_sectors + causal_rule.negative_sectors) if causal_rule else ""
        ) or "特定業種なし"

        beneficiary_sectors = list(causal_rule.beneficiary_sectors) if causal_rule else []
        negative_sectors = list(causal_rule.negative_sectors) if causal_rule else []
        beneficiary_tickers = resolve_tickers(beneficiary_sectors, sectors)
        negative_tickers = resolve_tickers(negative_sectors, sectors)

        beneficiary_names = ticker_names(beneficiary_tickers, ticker_lookup)
        negative_names = ticker_names(negative_tickers, ticker_lookup)

        tank_signal = (tank_signals or {}).get(_normalize_title(headline.title))

        score = score_headline_8axis(
            headline=headline,
            matched_themes=matched_themes,
            matched_sector=matched_sector,
            causal_rule=causal_rule,
            durable_themes=durable_themes,
            beneficiary_tickers=beneficiary_tickers,
            negative_tickers=negative_tickers,
            watchlist_names=watchlist_names,
            tank_signal=tank_signal,
        )

        strategist_take = _strategist_take(theme, sector, causal_rule)
        # v2.6: 羅針盤（学習ソース）の重点テーマに一致する場合のみ、参照した旨を一文補足
        if rashinban and theme in rashinban.emphasized_theme_labels:
            strategist_take += "岡三「羅針盤」（学習ソース）でも重点テーマとして言及されています。"
        # v4.3: Data Tankで実際の市場反応が計測済みのイベントは、その旨を一文補足
        if tank_signal and tank_signal.get("has_market_reaction"):
            strategist_take += "Data Tank側で実際の市場反応（値動き）が確認されたイベントに関連しており、相場への影響が既に現れている可能性があります。"

        views.append(
            StrategistView(
                headline=headline,
                strategist_take=strategist_take,
                theme=theme,
                related_sector=sector,
                beneficiary_names=beneficiary_names,
                negative_names=negative_names,
                sales_point=_sales_point(beneficiary_names, negative_names, sector),
                importance_stars=stars(score.overall_stars, max_stars=5),
                score=score,
            )
        )
    return views
