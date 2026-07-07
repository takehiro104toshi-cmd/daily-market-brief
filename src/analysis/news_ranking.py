"""ニュース見出しを重要度でランキングし、最重要ニュースを1件選定する。

スコアリングはすべてルールベース（生成AIではない）。
- テーマ・業種キーワードに一致: 加点
- 相場インパクトの大きいサプライズ語（上方修正・規制など）に一致: 加点
- ウォッチリスト銘柄名に言及: 加点

最高スコアの見出しを「AIが本日最重要と判断したニュース」として
必ず1位に固定する。同点の場合は記事日時（pubDate）が新しいものを優先し、
日時も同じ（または解析不能）の場合のみ見出しの出現順を優先する
（v2.3: 鮮度タイブレーク。重要度スコアの算出方法自体は変更していない。
日時が取得できない記事は同点内で最後尾に回る）。

各見出しには「理由」「影響市場」「影響業種」も付与する
（②今日の重要ニュースランキング向け）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..collectors.news import Headline, parse_published_datetime
from ..report.format_utils import stars, truncate_to_chars
from .models import NewsRankingItem, RashinbanKnowledge
from .source_trust import combined_trust_for_sources
from .strategist_engine import CausalRule, match_causal_rule, parse_causal_rules, resolve_tickers

SALES_TALK_MAX_CHARS = 100

SURPRISE_KEYWORDS = [
    "上方修正", "下方修正", "最高値", "最安値", "規制", "制裁", "決算",
    "提携", "買収", "増資", "上場", "撤退", "経営統合", "自社株買い",
]

# v2.7: 鮮度最優先。24時間以内は加点、48時間超は大きく減点する。
# ただし影響期間の長いイベント（FOMC・日銀・決算・国家戦略等）は例外として
# 減点しない（鮮度だけでなく「市場への影響期間」も考慮するため）。
FRESH_BONUS_HOURS = 24
FRESH_BONUS = 2
STALE_HOURS = 48
STALE_PENALTY = 4
DURABLE_EVENT_KEYWORDS = (
    "FOMC", "日銀", "金融政策", "決算", "国家戦略", "雇用統計",
    "CPI", "PPI", "利上げ", "利下げ", "政策金利",
)

# 影響市場の判定キーワード（先に一致したものを優先）
MARKET_KEYWORDS = [
    ("為替", ["円", "ドル", "為替", "米ドル"]),
    ("米国株", ["米国", "NY", "ダウ", "S&P", "ナスダック", "FRB", "米国株", "米株"]),
    ("日本株", ["日経", "東京市場", "日本株", "TOPIX"]),
    ("金利", ["金利", "日銀", "FOMC", "利上げ", "利下げ"]),
]


@dataclass
class _HeadlineAnalysis:
    score: int
    reason: str
    affected_market: str
    affected_sector: str
    beneficiary_tickers: List[str]
    negative_tickers: List[str]
    is_durable: bool = False  # v2.7: 鮮度減点の例外判定（影響期間の長いテーマ）に使う


def _matched_theme(headline: Headline, themes: List[str]) -> Optional[str]:
    return next((theme for theme in themes if theme in headline.title), None)


def _matched_sector(headline: Headline, sectors: Dict) -> Optional[str]:
    for sector_name, cfg in sectors.items():
        keywords = cfg.get("keywords", []) if isinstance(cfg, dict) else cfg
        if any(kw in headline.title for kw in keywords):
            return sector_name
    return None


def _matched_surprise(headline: Headline) -> Optional[str]:
    return next((kw for kw in SURPRISE_KEYWORDS if kw in headline.title), None)


def _matched_watchlist_name(headline: Headline, watchlist_names: List[str]) -> Optional[str]:
    return next((name for name in watchlist_names if name in headline.title), None)


def _affected_market(headline: Headline) -> str:
    for market_label, keywords in MARKET_KEYWORDS:
        if any(kw in headline.title for kw in keywords):
            return market_label
    return "市場全体"


def _analyze_headline(
    headline: Headline,
    themes: List[str],
    sectors: Dict,
    watchlist_names: List[str],
    causal_rules: Optional[List[CausalRule]] = None,
    durable_themes: Optional[List[str]] = None,
) -> _HeadlineAnalysis:
    matched_theme = _matched_theme(headline, themes)
    matched_sector = _matched_sector(headline, sectors)
    matched_surprise = _matched_surprise(headline)
    matched_watchlist = _matched_watchlist_name(headline, watchlist_names)
    causal_rule = match_causal_rule(headline, causal_rules or [])

    beneficiary_tickers = resolve_tickers(causal_rule.beneficiary_sectors, sectors) if causal_rule else []
    negative_tickers = resolve_tickers(causal_rule.negative_sectors, sectors) if causal_rule else []
    is_durable = matched_theme in (durable_themes or []) or (causal_rule is not None and causal_rule.durable)

    score = 0
    if matched_theme:
        score += 2
    if matched_sector:
        score += 2
    if matched_surprise:
        score += 1
    if matched_watchlist:
        score += 3
    if causal_rule:
        score += 2
    if is_durable:
        score += 1

    reason_parts = []
    if matched_theme:
        reason_parts.append(f"テーマ「{matched_theme}」に関連する")
    if matched_sector:
        reason_parts.append(f"業種「{matched_sector}」に関連する")
    if matched_surprise:
        reason_parts.append(f"「{matched_surprise}」という材料を含む")
    if matched_watchlist:
        reason_parts.append(f"ウォッチリスト銘柄「{matched_watchlist}」に言及している")
    if causal_rule:
        reason_parts.append(f"「{causal_rule.theme}」の因果チェーンに該当する")
    if is_durable:
        reason_parts.append("継続性の高い構造的なテーマである")

    # v2.9（④ Duplicate/Cross Source Intelligence）: 複数の高信頼情報源が同一
    # ニュースを報じている場合、重要度を機械的に上げる（新しい評価基準の
    # 創作ではなく、既存のSource Trustスコアの集計のみ）。
    if headline.source_count >= 2:
        combined = combined_trust_for_sources(headline.source, headline.duplicate_sources)
        if combined.max_score >= 4:
            bonus = 1 if headline.source_count == 2 else 2
            score += bonus
            reason_parts.append(f"{combined.source_count}社の高信頼情報源が同一ニュースを報じている")

    if reason_parts:
        reason = "、".join(reason_parts) + "ため、重要度が高いと判断しました。"
    else:
        reason = "本日のニュースの中で相対的に注目度が高いと判断しました。"

    return _HeadlineAnalysis(
        score=score,
        reason=reason,
        affected_market=_affected_market(headline),
        affected_sector=matched_sector or "特定業種なし",
        beneficiary_tickers=beneficiary_tickers,
        negative_tickers=negative_tickers,
        is_durable=is_durable,
    )


def _published_timestamp(headline: Headline) -> float:
    """タイブレーク用: 記事日時をUNIX秒で返す。解析不能時は-inf（同点内で最後尾）。"""
    dt = parse_published_datetime(headline.published)
    return dt.timestamp() if dt is not None else float("-inf")


def _sales_talk(headline: Headline, analysis: "_HeadlineAnalysis") -> str:
    """営業現場でそのまま読める、100文字以内の営業トークを生成する（断定は避ける）。"""
    if analysis.affected_sector and analysis.affected_sector != "特定業種なし":
        text = f"「{analysis.affected_sector}」関連は材料出尽くしや利益確定売りが入りやすい局面と考えられます。"
    elif analysis.affected_market and analysis.affected_market != "市場全体":
        text = f"{analysis.affected_market}への影響が意識されており、値動きを確認したい局面です。"
    else:
        text = f"「{headline.title}」は市場全体の地合いを確認する材料の一つと考えられます。"
    return truncate_to_chars(text, SALES_TALK_MAX_CHARS)


def build_news_ranking(
    headlines: List[Headline],
    themes: List[str],
    sectors: Dict,
    watchlist_names: List[str],
    limit: int = 10,
    causal_rules: Optional[List[dict]] = None,
    durable_themes: Optional[List[str]] = None,
    rashinban: Optional[RashinbanKnowledge] = None,
    now: Optional[datetime] = None,
) -> List[NewsRankingItem]:
    """ニュースを重要度順にランキングする。

    causal_rules / durable_themes（config.yaml由来）を指定すると、
    「岡三ストラテジスト視点」パイプラインと同じ因果チェーン・継続性の
    判定をスコアリングに反映し、恩恵銘柄・悪影響銘柄も付与する。
    いずれも省略可能（省略時は従来通りのスコアリングのみ）で、
    既存の呼び出し箇所にも影響しない。

    rashinban（v2.6・省略可能）: 岡三「羅針盤」学習ソースの重点テーマ
    （既存macro_themeラベルとの照合結果）に一致する見出しへ+1の補助加点を
    行う。羅針盤ファイルが無い場合はNone/空となり、従来と完全に同じ動作。
    本文の転載は行わない（テーマラベルの一致判定のみ）。

    now（v2.7・省略可能）: 鮮度最優先の基準時刻。指定時（またはNoneなら
    現在時刻）に対して、24時間以内の記事へ+2の加点、48時間超の記事へ
    -4の減点を行う。ただし影響期間の長いイベント（FOMC・日銀・決算・
    国家戦略等＝DURABLE_EVENT_KEYWORDS一致、またはdurable判定済み）は
    例外として減点しない。日時を解析できない記事は加減点なし
    （従来通り同点内の最後尾に回るのみ）。
    """
    if not headlines:
        return []

    parsed_causal_rules = parse_causal_rules(causal_rules or [])

    analyzed = [
        (headline, _analyze_headline(headline, themes, sectors, watchlist_names, parsed_causal_rules, durable_themes))
        for headline in headlines
    ]

    # v2.6: 羅針盤の重点テーマに一致する見出しへ小さな補助加点（+1）を行う。
    # スコア算出の既存8軸は変更せず、追加の1軸としてのみ働く。
    if rashinban and rashinban.emphasized_theme_labels:
        for headline, analysis in analyzed:
            matched_label = next(
                (label for label in rashinban.emphasized_theme_labels if label in headline.title), None
            )
            if matched_label:
                analysis.score += 1
                analysis.reason += f"岡三「羅針盤」（学習ソース）の重点テーマ「{matched_label}」にも該当します。"

    # v2.7: 鮮度最優先。24時間以内は加点・48時間超は大きく減点（影響期間の
    # 長いイベントは例外）。既存8軸の算出方法自体は変更しない。
    reference = now or datetime.now(timezone.utc)
    for headline, analysis in analyzed:
        published_dt = parse_published_datetime(headline.published)
        if published_dt is None:
            continue  # 日時不明は加減点なし（タイブレークで最後尾に回る既存挙動のみ）
        age_hours = (reference - published_dt).total_seconds() / 3600
        if age_hours <= FRESH_BONUS_HOURS:
            analysis.score += FRESH_BONUS
            analysis.reason += "24時間以内の新しい記事です（鮮度加点）。"
        elif age_hours > STALE_HOURS:
            is_long_impact = analysis.is_durable or any(kw in headline.title for kw in DURABLE_EVENT_KEYWORDS)
            if is_long_impact:
                analysis.reason += "48時間超の記事ですが、影響期間の長いイベントのため鮮度減点は適用していません。"
            else:
                analysis.score -= STALE_PENALTY
                analysis.reason += "48時間を超えた記事のため、鮮度を大きく減点しています。"
    # スコア降順 → 記事日時の新しい順 → 出現順（v2.3: 同点時は新しい記事を優先。
    # 日時を解析できない記事は同点内の最後尾に回す。スコア算出自体は不変）
    ranked = sorted(
        enumerate(analyzed),
        key=lambda item: (-item[1][1].score, -_published_timestamp(item[1][0]), item[0]),
    )

    items: List[NewsRankingItem] = []
    for rank, (_, (headline, analysis)) in enumerate(ranked[:limit], start=1):
        star_score = min(5, max(1, 1 + analysis.score))
        items.append(
            NewsRankingItem(
                rank=rank,
                stars=stars(star_score, max_stars=5),
                headline=headline,
                is_top_pick=(rank == 1),
                reason=analysis.reason,
                affected_market=analysis.affected_market,
                affected_sector=analysis.affected_sector,
                sales_talk=_sales_talk(headline, analysis),
                beneficiary_tickers=analysis.beneficiary_tickers,
                negative_tickers=analysis.negative_tickers,
            )
        )
    return items
