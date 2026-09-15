"""Outlook model（Phase 3-C §19 / §20 / §21）。

**決定論的**に、Evidence Packageの中のContextだけから
- 各Contextの「日本株にとっての材料の向き」（Compass DNA経験則を参照）
- outlook direction（UPWARD_BIAS / DOWNWARD_BIAS / RANGE_BOUND / MIXED / UNCERTAIN）
- confidence（HIGH / MEDIUM / LOW。0-100の疑似精度を作らない）
- 反対材料（counter contexts）と無効化条件
を導く。

因果は主張しない。「経験則では追い風／逆風とみられる材料」という**傾向の分類**であり、
`knowledge/compass_dna/market_rules.yaml` の rule_id を参照として残す。
数値目標は持たない（Compass DNA: 予測は方向＋メカニズム＋無効化条件）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from ..context.builders import (
    CURVE_SHAPE,
    EVENT_PROXIMITY,
    FX_DIRECTION,
    INDEX_DIRECTION,
    JGB10Y,
    NIKKEI,
    RATE_DIRECTION,
    TOPIX,
    TREND_VS_MA,
    UST10Y,
)
from ..context.model import ContextItem, ContextStatus, Direction
from .evidence_package import EvidencePackage
from .model import Confidence, OutlookDirection, CompassOutlook

OUTLOOK_RULE_VERSION = "outlook:1.0.0"

POSITIVE = "POSITIVE"      # 日本株にとって追い風とみられる材料
NEGATIVE = "NEGATIVE"      # 逆風とみられる材料
NEUTRAL = "NEUTRAL"        # 向きを持たない（相対状態・同時性・イベント距離）
UNKNOWN = "UNKNOWN"

#: 中核次元（欠けると確度を下げる）
CORE_DIMENSIONS: Tuple[str, ...] = ("japan_equities", "usd_jpy", "us_rates_10y")


@dataclass(frozen=True)
class Implication:
    """Context 1件の材料の向きと、参照したCompass DNA rule。"""

    context_id: str
    sign: str
    rule_ref: str          # market_rules.yaml の rule_id（該当なしなら空）
    reason: str            # 機械的な理由（自由文ではない）
    risk_tag: str = ""     # RISK claimへ回す性質（overheat / pre_event 等）


def classify_context(item: ContextItem) -> Implication:
    """**決定論的**な材料分類。テーブル外はUNKNOWN（勝手に解釈しない）。"""
    ctype, subject, direction = item.context_type, item.subject.subject_id, item.direction
    cid = item.context_id
    if ctype == INDEX_DIRECTION and subject in (TOPIX, NIKKEI):
        if direction is Direction.UP:
            return Implication(cid, POSITIVE, "JP_DIR_001", "prior_session_momentum_up")
        if direction is Direction.DOWN:
            return Implication(cid, NEGATIVE, "JP_DIR_001", "prior_session_momentum_down")
        if direction is Direction.FLAT:
            return Implication(cid, NEUTRAL, "JP_DIR_001", "prior_session_flat")
        return Implication(cid, UNKNOWN, "", "direction_unknown")
    if ctype == RATE_DIRECTION and subject in (JGB10Y, UST10Y):
        if direction is Direction.UP:
            return Implication(cid, NEGATIVE, "JP_US_001", "long_yield_rising")
        if direction is Direction.DOWN:
            return Implication(cid, POSITIVE, "JP_US_001", "long_yield_falling")
        if direction is Direction.FLAT:
            return Implication(cid, NEUTRAL, "JP_US_001", "long_yield_flat")
        return Implication(cid, UNKNOWN, "", "direction_unknown")
    if ctype == FX_DIRECTION:
        if direction is Direction.WEAKER:
            return Implication(cid, POSITIVE, "JP_FX_001", "yen_weaker_exporter_tailwind")
        if direction is Direction.STRONGER:
            return Implication(cid, NEGATIVE, "JP_FX_001", "yen_stronger_exporter_headwind")
        if direction is Direction.FLAT:
            return Implication(cid, NEUTRAL, "JP_FX_001", "fx_flat")
        return Implication(cid, UNKNOWN, "", "direction_unknown")
    if ctype == TREND_VS_MA:
        tag = "ma_deviation_above" if direction is Direction.ABOVE else "ma_deviation_below"
        return Implication(cid, NEUTRAL, "JP_INT_003", "ma25_deviation_reference", tag)
    if ctype == EVENT_PROXIMITY:
        return Implication(cid, NEUTRAL, "JP_DIR_004", "event_proximity", "pre_event")
    if ctype == CURVE_SHAPE:
        return Implication(cid, NEUTRAL, "", "curve_shape_reference")
    return Implication(cid, NEUTRAL, "", "relational_state")


def _is_reliable(item: ContextItem) -> bool:
    return item.status is ContextStatus.AVAILABLE


def _is_fresh(item: ContextItem, package: EvidencePackage) -> bool:
    """支持／反対材料に使える**前営業日**のContextか。

    item自体がAVAILABLEでも、参照sessionより古いもの（次元がSTALE）は
    見通しの根拠にしない（古いドル円で「円安が追い風」と語らない）。
    """
    if not _is_reliable(item) or item.time.session_date != package.reference_session:
        return False
    for dimension, cid in package.dimension_context_ids.items():
        if cid == item.context_id:
            return package.dimension_status.get(dimension) is ContextStatus.AVAILABLE
    return True


def _near_event(item: ContextItem, near_event_days: int) -> bool:
    return (item.context_type == EVENT_PROXIMITY and item.magnitude is not None
            and item.magnitude <= Decimal(near_event_days))


def counter_contexts_for(direction: OutlookDirection,
                         implications: Sequence[Implication]) -> List[str]:
    """outlookに対する**反対材料**（Compass DNA: 反対材料の常設）。"""
    if direction is OutlookDirection.UPWARD_BIAS:
        return [i.context_id for i in implications if i.sign == NEGATIVE]
    if direction is OutlookDirection.DOWNWARD_BIAS:
        return [i.context_id for i in implications if i.sign == POSITIVE]
    # MIXED / RANGE_BOUND / UNCERTAIN: 向きのある材料は全て「反対側になり得る」
    return [i.context_id for i in implications if i.sign in (POSITIVE, NEGATIVE)]


def invalidation_conditions(direction: OutlookDirection,
                            supporters: Sequence[ContextItem]) -> List[str]:
    """支持材料が**反転した場合**を無効化条件とする（根拠に無い材料は挙げない）。"""
    out: List[str] = []
    for item in supporters:
        name = item.subject.display_name or item.subject.subject_id
        if item.context_type == INDEX_DIRECTION:
            out.append(f"{name}が前営業日の方向（{item.direction.value}）と逆に動く場合")
        elif item.context_type == RATE_DIRECTION:
            out.append(f"{name}の方向（{item.direction.value}）が反転する場合")
        elif item.context_type == FX_DIRECTION:
            out.append(f"{name}が{'円高' if item.direction is Direction.WEAKER else '円安'}"
                       "方向へ反転する場合")
    if not out:
        out.append("根拠となるContextが朝の時点で成立していない場合")
    return list(dict.fromkeys(out))      # 同じ条件は1回だけ（順序維持）


def build_outlook(package: EvidencePackage, *, horizon: str = "next_tokyo_session",
                  near_event_days: int = 2) -> Tuple[CompassOutlook, Dict[str, Implication]]:
    """Evidence Packageから見通しを組む。戻り値は (outlook, context_id→Implication)。"""
    implications: Dict[str, Implication] = {}
    signed: List[Implication] = []
    reliable_items: Dict[str, ContextItem] = {}
    for item in package.contexts:
        imp = classify_context(item)
        implications[item.context_id] = imp
        if not _is_fresh(item, package):
            continue                       # STALE / CONFLICTED / LIMITED_USE / 古いsession は根拠にしない
        reliable_items[item.context_id] = item
        if imp.sign in (POSITIVE, NEGATIVE):
            signed.append(imp)
    positives = [i for i in signed if i.sign == POSITIVE]
    negatives = [i for i in signed if i.sign == NEGATIVE]
    lead = package.dimension_context("japan_equities")
    lead_sign = implications[lead.context_id].sign if lead is not None else UNKNOWN

    if not signed:
        if lead is not None and lead.direction is Direction.FLAT and _is_fresh(lead, package):
            direction = OutlookDirection.RANGE_BOUND
        else:
            direction = OutlookDirection.UNCERTAIN
    elif positives and not negatives:
        direction = OutlookDirection.UPWARD_BIAS
    elif negatives and not positives:
        direction = OutlookDirection.DOWNWARD_BIAS
    elif len(positives) > len(negatives):
        direction = OutlookDirection.UPWARD_BIAS
    elif len(negatives) > len(positives):
        direction = OutlookDirection.DOWNWARD_BIAS
    elif lead_sign == POSITIVE:
        direction = OutlookDirection.UPWARD_BIAS      # 同数ならlead（TOPIX）に従う
    elif lead_sign == NEGATIVE:
        direction = OutlookDirection.DOWNWARD_BIAS
    else:
        direction = OutlookDirection.MIXED

    if direction is OutlookDirection.UPWARD_BIAS:
        supporters = [i.context_id for i in positives]
    elif direction is OutlookDirection.DOWNWARD_BIAS:
        supporters = [i.context_id for i in negatives]
    else:
        supporters = []
    counters = counter_contexts_for(direction, signed)

    missing_core = [d for d in CORE_DIMENSIONS
                    if package.dimension_status.get(d) is not ContextStatus.AVAILABLE]
    near_events = [c.context_id for c in package.contexts
                   if _near_event(c, near_event_days)]
    unreliable_used = [c.context_id for c in package.contexts if not _is_fresh(c, package)]

    # ---- confidence ladder（決定論的。要素は全てcomponentsへ残す）
    if direction in (OutlookDirection.MIXED, OutlookDirection.UNCERTAIN):
        confidence = Confidence.LOW
    elif (len(supporters) >= 3 and not counters and not missing_core
          and not near_events and lead is not None):
        confidence = Confidence.HIGH
    elif (len(supporters) >= 2 and len(supporters) > len(counters)
          and len(missing_core) <= 1 and not near_events):
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    support_items = [reliable_items[c] for c in supporters if c in reliable_items]
    outlook = CompassOutlook(
        direction=direction, confidence=confidence, horizon=horizon,
        supporting_context_ids=tuple(supporters),
        counter_context_ids=tuple(counters),
        invalidation_conditions=tuple(invalidation_conditions(direction, support_items)),
        rule_version=OUTLOOK_RULE_VERSION,
        components={
            "positive": str(len(positives)), "negative": str(len(negatives)),
            "lead_sign": lead_sign, "lead_context_id": lead.context_id if lead else "",
            "missing_core_dimensions": ",".join(missing_core),
            "near_event_contexts": str(len(near_events)),
            "unreliable_contexts": str(len(unreliable_used)),
            "rule_refs": ",".join(sorted({i.rule_ref for i in signed if i.rule_ref})),
        })
    return outlook, implications


#: outlook文の語彙 → 方向（validatorがOUTLOOK claimの整合を見る）
BIAS_LEXICON: Tuple[Tuple[str, OutlookDirection], ...] = (
    ("堅調", OutlookDirection.UPWARD_BIAS), ("上値を試す", OutlookDirection.UPWARD_BIAS),
    ("強含み", OutlookDirection.UPWARD_BIAS),
    ("軟調", OutlookDirection.DOWNWARD_BIAS), ("下値を試す", OutlookDirection.DOWNWARD_BIAS),
    ("弱含み", OutlookDirection.DOWNWARD_BIAS),
    ("方向感に乏しい", OutlookDirection.RANGE_BOUND), ("レンジ", OutlookDirection.RANGE_BOUND),
    ("強弱材料が交錯", OutlookDirection.MIXED), ("交錯", OutlookDirection.MIXED),
    ("見通しの確度が低い", OutlookDirection.UNCERTAIN), ("不透明", OutlookDirection.UNCERTAIN),
)


def asserted_bias(text: str) -> Optional[OutlookDirection]:
    """文中の見通し語彙から主張されている方向を読む（最初に一致したもの）。"""
    hits = [(text.find(word), direction) for word, direction in BIAS_LEXICON
            if word in text]
    if not hits:
        return None
    return min(hits, key=lambda h: h[0])[1]
