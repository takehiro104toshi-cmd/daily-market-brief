"""Market Internals → Compass claim（Phase 3.5 §24 / §25 / §26）。

Phase 3-C の決定論的generatorへ**必要最小限**で接続する（generatorはこの関数を
1回呼ぶだけ。validator経路は既存のまま）。

生成する claim（対象次元が AVAILABLE で、代表Contextが参照sessionのものに限る）:

- FACTUAL     : 値上がり／値下がり／変化なしの銘柄数（Fact引用）
- RELATIONAL  : 値上がり銘柄数が値下がり銘柄数を上回った／下回った（Context引用）
- INTERPRETIVE: 指数の動きに広がりが確認された／限定的（**JP_INT_001** を rule_ref に持つ。
                breadth Context と index_direction Context の両方を引用）
- FACTUAL     : 売買代金 vs 20営業日平均、業種のleaders/laggards、大型 vs 小型、
                直近公表週の海外投資家（**週次**であることを文に明示）

**breadth ≠ causality**: 「なぜ上昇したか」は書かない。語彙は lexicon の統制語彙のみ。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from ..compass.evidence_package import EvidencePackage
from ..compass.lexicon import fmt_level, fmt_magnitude
from ..compass.model import ClaimRole, ClaimType
from ..compass.narrative_plan import NarrativePlan
from ..context.model import ContextItem, ContextStatus, Direction
from ..facts.model import Fact
from .facts import (
    INVESTOR_FLOW_NET,
    MARKET_ADVANCERS,
    MARKET_DECLINERS,
    MARKET_UNCHANGED,
    SIZE_LARGE_VS_SMALL,
    TURNOVER_VS_20S_RATIO,
)
from .types import (
    DIM_BREADTH,
    DIM_FLOW,
    DIM_SECTOR,
    DIM_SIZE,
    DIM_TURNOVER,
    SECTOR_LEADERSHIP,
    SECTOR_SUMMARY_SUBJECT,
)

BREADTH_PRINCIPLE = "JP_INT_001"


@dataclass(frozen=True)
class ClaimSpec:
    role: ClaimRole
    claim_type: ClaimType
    text: str
    fact_ids: Tuple[str, ...]
    context_ids: Tuple[str, ...]
    rule_ref: str = ""


def _fmt_count(value: Optional[Decimal]) -> str:
    return f"{int(value):,}" if value is not None else ""


def _fresh(item: Optional[ContextItem], package: EvidencePackage) -> bool:
    return (item is not None and item.status is ContextStatus.AVAILABLE
            and item.time.session_date == package.reference_session)


def _fact_of(package: EvidencePackage, item: ContextItem, fact_type: str) -> Optional[Fact]:
    for fact in package.facts_for_context(item.context_id):
        if fact.fact_type == fact_type:
            return fact
    return None


def _breadth_claims(package: EvidencePackage) -> List[ClaimSpec]:
    out: List[ClaimSpec] = []
    if package.dimension_status.get(DIM_BREADTH) is not ContextStatus.AVAILABLE:
        return out
    breadth = package.dimension_context(DIM_BREADTH)
    if not _fresh(breadth, package):
        return out
    adv = _fact_of(package, breadth, MARKET_ADVANCERS)
    dec = _fact_of(package, breadth, MARKET_DECLINERS)
    unch = _fact_of(package, breadth, MARKET_UNCHANGED)
    if adv is None or dec is None or unch is None:
        return out
    ids = (adv.fact_id, dec.fact_id, unch.fact_id)
    out.append(ClaimSpec(
        ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL,
        f"東証プライムの普通株では、値上がり{_fmt_count(adv.value.value)}銘柄・"
        f"値下がり{_fmt_count(dec.value.value)}銘柄・変化なし{_fmt_count(unch.value.value)}銘柄"
        "であった。", ids, (breadth.context_id,)))
    if breadth.direction is Direction.UP:
        rel = "値上がり銘柄数が値下がり銘柄数を上回った。"
    elif breadth.direction is Direction.DOWN:
        rel = "値上がり銘柄数が値下がり銘柄数を下回った。"
    else:
        rel = "値上がり銘柄数と値下がり銘柄数は同数であった。"
    out.append(ClaimSpec(ClaimRole.WHAT_HAPPENED, ClaimType.RELATIONAL, rel,
                         (adv.fact_id, dec.fact_id), (breadth.context_id,)))
    # ---- INTERPRETIVE（JP_INT_001: 上昇の持続性は広がりに条件付けられる）
    lead = package.dimension_context("japan_equities")
    if _fresh(lead, package) and lead.direction in (Direction.UP, Direction.DOWN) \
            and breadth.direction in (Direction.UP, Direction.DOWN):
        dominant = "値上がり" if breadth.direction is Direction.UP else "値下がり"
        if breadth.direction == lead.direction:
            text = (f"解釈（経験則 {BREADTH_PRINCIPLE}）: {dominant}銘柄数が優勢であり、"
                    "指数の動きには一定の広がりが確認されたとみられる（因果関係は特定しない）。")
        else:
            index_side = "値上がり" if lead.direction is Direction.UP else "値下がり"
            text = (f"解釈（経験則 {BREADTH_PRINCIPLE}）: {index_side}銘柄数が劣勢であり、"
                    "指数の動きの広がりは限定的とみられる（因果関係は特定しない）。")
        out.append(ClaimSpec(ClaimRole.WHY, ClaimType.INTERPRETIVE, text,
                             (adv.fact_id, dec.fact_id) + tuple(lead.supporting_fact_ids),
                             (breadth.context_id, lead.context_id), BREADTH_PRINCIPLE))
    return out


def _turnover_claims(package: EvidencePackage) -> List[ClaimSpec]:
    if package.dimension_status.get(DIM_TURNOVER) is not ContextStatus.AVAILABLE:
        return []
    item = package.dimension_context(DIM_TURNOVER)
    if not _fresh(item, package):
        return []
    ratio = _fact_of(package, item, TURNOVER_VS_20S_RATIO)
    if ratio is None:
        return []
    if item.direction is Direction.ABOVE:
        tail = "平均を上回った"
    elif item.direction is Direction.BELOW:
        tail = "平均を下回った"
    else:
        tail = "平均とほぼ同水準であった"
    text = (f"東証プライムの売買代金は20営業日平均の{fmt_level(ratio.value.value, 2)}倍で、"
            f"{tail}。")
    return [ClaimSpec(ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL, text, (ratio.fact_id,),
                      (item.context_id,))]


def _sector_claims(package: EvidencePackage) -> List[ClaimSpec]:
    if package.dimension_status.get(DIM_SECTOR) is not ContextStatus.AVAILABLE:
        return []
    summary = package.dimension_context(DIM_SECTOR)
    if not _fresh(summary, package):
        return []
    members = [c for c in package.contexts_of(SECTOR_LEADERSHIP)
               if c.subject.subject_id != SECTOR_SUMMARY_SUBJECT
               and c.time.session_date == summary.time.session_date]
    leaders = [c for c in members if c.direction is Direction.OUTPERFORM]
    laggards = [c for c in members if c.direction is Direction.UNDERPERFORM]
    if not leaders and not laggards:
        return [ClaimSpec(ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL,
                          "業種別では、市場平均から目立って乖離した業種はなかった。",
                          tuple(summary.supporting_fact_ids), (summary.context_id,))]
    parts: List[str] = []
    if leaders:
        parts.append("・".join(c.subject.display_name for c in leaders) + "が市場平均を上回り")
    if laggards:
        parts.append("・".join(c.subject.display_name for c in laggards) + "が下回った")
    text = "業種別では、" + "、".join(parts) + ("。" if parts[-1].endswith("った") else "。")
    if not laggards:
        text = "業種別では、" + parts[0].replace("上回り", "上回った") + "。"
    fact_ids: List[str] = []
    for c in leaders + laggards:
        fact_ids.extend(c.supporting_fact_ids)
    return [ClaimSpec(ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL, text,
                      tuple(dict.fromkeys(fact_ids)),
                      (summary.context_id,) + tuple(c.context_id for c in leaders + laggards))]


def _size_claims(package: EvidencePackage) -> List[ClaimSpec]:
    if package.dimension_status.get(DIM_SIZE) is not ContextStatus.AVAILABLE:
        return []
    item = package.dimension_context(DIM_SIZE)
    if not _fresh(item, package):
        return []
    gap = _fact_of(package, item, SIZE_LARGE_VS_SMALL)
    if gap is None:
        return []
    if item.direction is Direction.OUTPERFORM:
        text = f"規模別では、大型株が小型株を上回った（差{fmt_magnitude(gap.value.value, 'pct_point')}）。"
    elif item.direction is Direction.UNDERPERFORM:
        text = f"規模別では、大型株が小型株を下回った（差{fmt_magnitude(gap.value.value, 'pct_point')}）。"
    else:
        text = "規模別では、大型株と小型株の騰落率はほぼ同水準であった。"
    return [ClaimSpec(ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL, text, (gap.fact_id,),
                      (item.context_id,))]


def _flow_claims(package: EvidencePackage) -> List[ClaimSpec]:
    if package.dimension_status.get(DIM_FLOW) is not ContextStatus.AVAILABLE:
        return []
    item = package.dimension_context(DIM_FLOW)
    if item is None or item.status is not ContextStatus.AVAILABLE:
        return []
    fact = _fact_of(package, item, INVESTOR_FLOW_NET)
    if fact is None:
        return []
    published = ""
    for token in fact.note.split(";"):
        if token.startswith("published_date="):
            published = token.split("=", 1)[1]
    if item.direction is Direction.UP:
        state = "買い越し"
    elif item.direction is Direction.DOWN:
        state = "売り越し"
    else:
        state = "買いと売りが均衡"
    text = (f"直近公表週（{fact.time.period_start}〜{fact.time.period_end}、"
            f"公表日{published}）では、{fact.subject.display_name}は{state}であった"
            "（週次データ）。")
    return [ClaimSpec(ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL, text, (fact.fact_id,),
                      (item.context_id,))]


def internals_claims(package: EvidencePackage, plan: NarrativePlan) -> List[ClaimSpec]:
    """generatorから呼ぶ唯一の入口。internals未付与のpackageでは空を返す。"""
    if not plan.can_generate or not package.internals_status:
        return []
    out: List[ClaimSpec] = []
    out += _breadth_claims(package)
    out += _turnover_claims(package)
    out += _sector_claims(package)
    out += _size_claims(package)
    out += _flow_claims(package)
    return out
