"""News Impact Score（v3.2・改善3/4/5）— ニュース重要度を★だけでなく100点満点で評価する。

既存の news_ranking.py（★1〜5・並び順）は一切変更せず、そのランキング結果
（NewsRankingItem）に対して、追加の機械的スコア（0〜100）を後付けで計算する。
評価軸は：市場影響・テーマ継続性・一次情報(Tier1)・複数ソース一致・日本株影響・
米国株影響・指数影響・為替影響・金利影響・セクター波及・話題性・鮮度。

生成AIの推測は使わない。各軸は NewsRankingItem に既にある構造化フィールド
（affected_market / affected_sector / stars / reason / beneficiary_tickers）と
Headline のメタ情報（source / source_count / published）だけから加点する、透明な
加点表。Tier1（公式・一次情報）と3社以上の重複報道（Major Story）を重く見る。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from ..collectors.news import parse_published_datetime
from .models import NewsRankingItem
from .source_trust import source_tier

# 3社以上が同一ニュースを報じていれば Major Story とみなす。
MAJOR_STORY_MIN_SOURCES = 3
FRESH_HOURS = 24
STALE_HOURS = 48


def _stars_count(stars: str) -> int:
    return stars.count("★") if stars else 0


def _age_hours(published: str, now: datetime) -> Optional[float]:
    dt = parse_published_datetime(published)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600


def score_news_item(item: NewsRankingItem, now: Optional[datetime] = None) -> dict:
    """1件の NewsRankingItem に対する Impact Score(0〜100) と内訳を返す。"""
    now = now or datetime.now(timezone.utc)
    h = item.headline
    market = item.affected_market or ""
    sector = item.affected_sector or ""
    tier = source_tier(h.source)
    breakdown: dict = {}

    # 既存ランキング（★）を土台として反映（0〜15点）
    breakdown["ランキング"] = min(15, _stars_count(item.stars) * 3)

    # 市場影響（特定の市場に効くか）
    breakdown["市場影響"] = 12 if market and market != "市場全体" else 4

    # 一次情報（Tier1）／二次（Tier2）
    if tier == "Tier1":
        breakdown["一次情報"] = 16
    elif tier == "Tier2":
        breakdown["一次情報"] = 8
    else:
        breakdown["一次情報"] = 2

    # 複数ソース一致（Major Story）
    sc = getattr(h, "source_count", 1) or 1
    if sc >= MAJOR_STORY_MIN_SOURCES:
        breakdown["複数ソース"] = 14
    elif sc >= 2:
        breakdown["複数ソース"] = 7
    else:
        breakdown["複数ソース"] = 0

    # 各市場軸
    breakdown["日本株影響"] = 8 if market == "日本株" else (4 if any(t.endswith(".T") for t in item.beneficiary_tickers) else 0)
    breakdown["米国株影響"] = 8 if market == "米国株" else 0
    breakdown["指数影響"] = 6 if market in ("日本株", "米国株") else 0
    breakdown["為替影響"] = 8 if market == "為替" else 0
    breakdown["金利影響"] = 8 if market == "金利" else 0

    # セクター波及
    breakdown["セクター波及"] = 10 if sector and sector != "特定業種なし" else 0

    # テーマ継続性（reason に継続性の記述があるか）
    breakdown["テーマ継続性"] = 8 if "継続" in (item.reason or "") else 0

    # 話題性（重複報道社数）
    breakdown["話題性"] = 6 if sc >= 3 else (3 if sc >= 2 else 0)

    # 鮮度
    age = _age_hours(h.published, now)
    if age is None:
        breakdown["鮮度"] = 0
    elif age <= FRESH_HOURS:
        breakdown["鮮度"] = 10
    elif age <= STALE_HOURS:
        breakdown["鮮度"] = 4
    else:
        breakdown["鮮度"] = -6

    score = max(0, min(100, sum(breakdown.values())))
    return {
        "score": score,
        "breakdown": breakdown,
        "tier": tier,
        "is_major_story": sc >= MAJOR_STORY_MIN_SOURCES,
    }


def apply_news_impact_scores(items: List[NewsRankingItem], now: Optional[datetime] = None) -> List[NewsRankingItem]:
    """各 NewsRankingItem に impact_score / impact_breakdown / source_tier /
    is_major_story を後付けで設定して返す（並び順・★は変更しない）。"""
    for item in items:
        result = score_news_item(item, now)
        item.impact_score = result["score"]
        item.impact_breakdown = result["breakdown"]
        item.source_tier = result["tier"]
        item.is_major_story = result["is_major_story"]
    return items


def count_major_stories(items: List[NewsRankingItem]) -> int:
    """Major Story（3社以上が報道）の件数（Dashboard等の表示用）。"""
    return sum(1 for it in items if getattr(it, "is_major_story", False))
