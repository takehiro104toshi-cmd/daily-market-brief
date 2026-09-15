"""Market Internals の adversarial cases（Phase 3.5 §25 / §26 / §19 / §37）。

Phase 3-C と同じ仕組み（FakeNarrativeGenerator → 最初のQuality gate）で、
internals に固有の捏造・誤用を**必ずREJECT**することを確認する:

- fabricated_advancers      : 存在しない値上がり銘柄数 → numeric:unsupported_number
- breadth_direction_reversed: 上回った/下回ったの逆 → direction:direction_mismatch
- weekly_flow_as_daily      : 「本日は海外投資家が買い越し」 → language:weekly_flow_as_daily
- sector_causal             : 「金利上昇を受け銀行業が買われた」 → language:unsupported_causal_claim
- breadth_without_internals : internals無しのpackageでbreadthを語る → missingness
- valid_breadth_control     : 正しい引用 → GROUNDED（validatorが厳しすぎない証拠）
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from ..compass.adversarial import AdversarialCase, _claim
from ..compass.config import CompassConfig
from ..compass.evidence_package import build_evidence_package
from ..compass.model import ClaimRole, ClaimType
from ..context.model import CompassContextSnapshot, ContextStatus, Direction
from ..context.snapshot import morning_context_snapshot
from ..facts.model import Fact
from .facts import MARKET_ADVANCERS, MARKET_DECLINERS, MARKET_UNCHANGED
from .types import DIM_BREADTH, INTERNALS_CONTEXT_TYPES


def _fmt(value: Optional[Decimal]) -> str:
    return f"{int(value):,}" if value is not None else ""


def degraded_without_internals(snapshot: CompassContextSnapshot, facts: Sequence[Fact]
                               ) -> Tuple[CompassContextSnapshot, Tuple[Fact, ...]]:
    """internals Context / internals_status を外したsnapshotのコピー（Phase 3-C相当）。"""
    items = [i for i in snapshot.items if i.context_type not in INTERNALS_CONTEXT_TYPES]
    plain = morning_context_snapshot(items, snapshot.session_date,
                                     generated_at=snapshot.generated_at)
    return replace(plain, internals_status={}), tuple(facts)


def build_internals_adversarial_cases(snapshot: CompassContextSnapshot, facts: Sequence[Fact],
                                      *, config: Optional[CompassConfig] = None
                                      ) -> Tuple[List[AdversarialCase], List[Dict[str, str]]]:
    cfg = config or CompassConfig()
    facts = tuple(facts)
    package = build_evidence_package(snapshot, facts, budget=cfg.evidence_budget)
    sd = snapshot.session_date
    cases: List[AdversarialCase] = []
    skipped: List[Dict[str, str]] = []
    breadth = package.dimension_context(DIM_BREADTH)
    if breadth is None or package.dimension_status.get(DIM_BREADTH) is not ContextStatus.AVAILABLE:
        skipped.append({"case": "all", "reason": "breadth_context_missing"})
        return cases, skipped
    by_type = {f.fact_type: f for f in package.facts_for_context(breadth.context_id)}
    adv, dec, unch = (by_type.get(MARKET_ADVANCERS), by_type.get(MARKET_DECLINERS),
                      by_type.get(MARKET_UNCHANGED))
    if adv is None or dec is None or unch is None:
        skipped.append({"case": "all", "reason": "breadth_facts_missing"})
        return cases, skipped
    ids = (adv.fact_id, dec.fact_id, unch.fact_id)
    ctx = (breadth.context_id,)
    valid = (f"東証プライムの普通株では、値上がり{_fmt(adv.value.value)}銘柄・"
             f"値下がり{_fmt(dec.value.value)}銘柄・変化なし{_fmt(unch.value.value)}銘柄であった。")

    def add(name: str, claim, *codes: str, snap=snapshot, fs=facts, rejected: bool = True):
        cases.append(AdversarialCase(name=name, claim=claim, snapshot=snap, facts=fs,
                                     expected_codes=tuple(codes), expect_rejected=rejected))

    fabricated = (f"東証プライムの普通株では、値上がり{_fmt(adv.value.value + 123)}銘柄・"
                  f"値下がり{_fmt(dec.value.value)}銘柄・変化なし{_fmt(unch.value.value)}銘柄であった。")
    add("fabricated_advancers",
        _claim(sd, ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL, fabricated, ids, ctx),
        "numeric:unsupported_number")
    if breadth.direction in (Direction.UP, Direction.DOWN):
        wrong = ("値上がり銘柄数が値下がり銘柄数を下回った。" if breadth.direction is Direction.UP
                 else "値上がり銘柄数が値下がり銘柄数を上回った。")
        add("breadth_direction_reversed",
            _claim(sd, ClaimRole.WHAT_HAPPENED, ClaimType.RELATIONAL, wrong,
                   (adv.fact_id, dec.fact_id), ctx),
            "direction:direction_mismatch")
    else:
        skipped.append({"case": "breadth_direction_reversed", "reason": "breadth_flat"})
    add("weekly_flow_as_daily",
        _claim(sd, ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL,
               "本日は海外投資家が買い越しとなった。", ids, ctx),
        "language:weekly_flow_as_daily")
    add("sector_causal",
        _claim(sd, ClaimRole.WHY, ClaimType.INTERPRETIVE,
               "金利上昇を受けて銀行業が買われたとみられる。", ids, ctx),
        "language:unsupported_causal_claim")
    plain_snapshot, plain_facts = degraded_without_internals(snapshot, facts)
    add("breadth_without_internals",
        _claim(sd, ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL, valid, ids, ctx),
        "missingness:missing_dimension_assertion", "grounding:unknown_context_id",
        snap=plain_snapshot, fs=plain_facts)
    add("valid_breadth_control",
        _claim(sd, ClaimRole.WHAT_HAPPENED, ClaimType.FACTUAL, valid, ids, ctx),
        rejected=False)
    return cases, skipped


__all__ = ["build_internals_adversarial_cases", "degraded_without_internals"]
