"""決定論的なsalience / ranking（Phase 3-B STEP 12/13）。

**LLMに重要度を決めさせない**。**ブラックボックススコアを作らない**。

STEP 13の指示どおり、根拠の無い0-100スコアではなく
**説明可能なruleによる段階（tier）＋決定論的な並び**を採用する。
全componentは `priority_components` に文字列で保存され、後から検証できる。

tier規則（`salience:1.0.0`）:
- `PRIMARY`   … 中核次元（指数方向 / 相対パフォーマンス / NT倍率 / 金利方向 /
                カーブ / 為替）で、当日セッションのFactに基づくもの
- `SECONDARY` … 中核次元だが補助的（25DMA位置・cross-asset同時性）、
                または7日以内のevent
- `BACKGROUND`… それ以外（遠いevent・品質限定・状態不明）

品質・鮮度による**降格のみ**を行い、昇格はしない（FAIL-CLOSED）。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from .builders import (
    CROSS_ASSET_COOCCURRENCE,
    CURVE_SHAPE,
    EVENT_PROXIMITY,
    FX_DIRECTION,
    INDEX_DIRECTION,
    NT_RATIO_STATE,
    RATE_DIRECTION,
    RELATIVE_PERFORMANCE,
    TREND_VS_MA,
)
from .model import ContextItem, ContextStatus, Direction, PriorityTier

SALIENCE_RULE_VERSION = "salience:1.0.0"

#: 中核次元（Morning Compassの骨格）
_PRIMARY_TYPES = frozenset({
    INDEX_DIRECTION, RELATIVE_PERFORMANCE, NT_RATIO_STATE,
    RATE_DIRECTION, CURVE_SHAPE, FX_DIRECTION,
})
#: 補助次元
_SECONDARY_TYPES = frozenset({TREND_VS_MA, CROSS_ASSET_COOCCURRENCE})
#: eventが「近い」とみなす日数（Morning Compassの実務的な視野）
_NEAR_EVENT_DAYS = 7

#: 並び順の安定化に使うtypeの序列（決定論的なranking）
_TYPE_ORDER = (
    INDEX_DIRECTION, RELATIVE_PERFORMANCE, NT_RATIO_STATE, TREND_VS_MA,
    RATE_DIRECTION, CURVE_SHAPE, FX_DIRECTION, CROSS_ASSET_COOCCURRENCE,
    EVENT_PROXIMITY,
)


def _base_tier(item: ContextItem) -> PriorityTier:
    if item.context_type in _PRIMARY_TYPES:
        return PriorityTier.PRIMARY
    if item.context_type in _SECONDARY_TYPES:
        return PriorityTier.SECONDARY
    if item.context_type == EVENT_PROXIMITY:
        near = (item.magnitude is not None
                and item.magnitude <= Decimal(_NEAR_EVENT_DAYS))
        return PriorityTier.SECONDARY if near else PriorityTier.BACKGROUND
    return PriorityTier.BACKGROUND


def _demote(tier: PriorityTier) -> PriorityTier:
    if tier is PriorityTier.PRIMARY:
        return PriorityTier.SECONDARY
    return PriorityTier.BACKGROUND


def score_item(item: ContextItem, *, session_date: str) -> ContextItem:
    """1件のContextにtierとcomponentsを付ける（値は変更しない）。"""
    components = {}
    tier = _base_tier(item)
    components["base_tier"] = tier.value
    components["context_type"] = item.context_type

    # --- freshness: 当日セッションのFactかどうか（暦日ではなくsession一致）
    fresh = item.time.session_date == session_date
    components["freshness"] = "current_session" if fresh else "older_session"
    if not fresh:
        tier = _demote(tier)
        components["demoted_by"] = "stale_session"

    # --- 品質: LIMITED_USE / CONFLICTED は降格（黙って同格に扱わない）
    if item.status in (ContextStatus.LIMITED_USE, ContextStatus.CONFLICTED):
        tier = _demote(tier)
        components["demoted_by"] = item.status.value
    components["status"] = item.status.value
    components["quality"] = item.quality or "unknown"

    # --- 方向不明は中核でも背景へ
    if item.direction is Direction.UNKNOWN and item.relationship is None:
        tier = PriorityTier.BACKGROUND
        components["demoted_by"] = "direction_unknown"
    components["direction"] = item.direction.value

    # --- 確認度: 支持Factが複数なら cross-series confirmation あり
    components["supporting_facts"] = str(len(item.supporting_fact_ids))
    components["magnitude"] = (str(item.magnitude)
                               if item.magnitude is not None else "")
    components["magnitude_unit"] = item.magnitude_unit
    components["final_tier"] = tier.value

    return replace(item, priority_tier=tier, priority_components=components,
                   priority_rule_version=SALIENCE_RULE_VERSION)


def _sort_key(item: ContextItem) -> Tuple:
    tier_order = {PriorityTier.PRIMARY: 0, PriorityTier.SECONDARY: 1,
                  PriorityTier.BACKGROUND: 2}
    try:
        type_rank = _TYPE_ORDER.index(item.context_type)
    except ValueError:
        type_rank = len(_TYPE_ORDER)
    # 大きさは**降格材料にはしない**が、同tier内の並びには使う（絶対値の大きい順）
    magnitude_rank = -abs(item.magnitude) if item.magnitude is not None else Decimal(0)
    return (tier_order[item.priority_tier], type_rank, magnitude_rank,
            item.subject.subject_id, item.context_type, item.context_id)


def rank_contexts(items: Sequence[ContextItem], *,
                  session_date: str) -> List[ContextItem]:
    """tier付与＋**決定論的**な並び替え（同じ入力なら常に同じ順序）。"""
    scored = [score_item(i, session_date=session_date) for i in items]
    return sorted(scored, key=_sort_key)


def high_priority(items: Sequence[ContextItem]) -> List[ContextItem]:
    return [i for i in items if i.priority_tier is PriorityTier.PRIMARY]
