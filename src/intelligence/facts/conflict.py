"""Source conflict の表現（Phase 3-A STEP 15）。

**勝手に片方を正解にしない**。同一Fact候補（同じsubject × fact_type × 日付）が
複数sourceから異なる値で来た場合、状態を付けて**両方保持**する。

Phase 3-Aでは**複雑なtruth arbitration engineを作らない**。
既存Source Registryのtier（PRIMARY_OFFICIAL > MARKET_DATA_PROVIDER > SECONDARY）を
**参考情報として提示するだけ**で、自動で勝者を決めない。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

from .model import ConflictState, Fact

#: 既存Source Registryのsource_type順（**参考**。自動arbitrationはしない）
SOURCE_PREFERENCE = ("PRIMARY_OFFICIAL", "MARKET_DATA_PROVIDER", "SECONDARY")


def group_key(fact: Fact) -> Tuple[str, str, str]:
    """同一Fact候補とみなす単位。"""
    return (fact.subject.key(), fact.fact_type, fact.time.primary_date)


def _value_key(fact: Fact) -> str:
    return (str(fact.value.value) if fact.value.value is not None
            else fact.value.text_value)


def assess_conflicts(facts: Sequence[Fact]) -> List[Fact]:
    """同一候補グループごとにconflict stateを付けて返す（値は変更しない）。

    - 1件のみ → `UNKNOWN`（比較相手がいない。AGREEと断定しない）
    - 全て同値 → `AGREE`
    - 値が割れる → 全件 `CONFLICT` ＋ 相手のfact_idを保持
    """
    grouped: Dict[Tuple[str, str, str], List[Fact]] = defaultdict(list)
    for fact in facts:
        grouped[group_key(fact)].append(fact)

    out: List[Fact] = []
    for group in grouped.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        values = {_value_key(f) for f in group}
        if len(values) == 1:
            for fact in group:
                others = tuple(sorted(f.fact_id for f in group
                                      if f.fact_id != fact.fact_id))
                out.append(_with(fact, ConflictState.AGREE, others))
            continue
        for fact in group:
            others = tuple(sorted(f.fact_id for f in group
                                  if f.fact_id != fact.fact_id))
            out.append(_with(fact, ConflictState.CONFLICT, others))
    return out


def _with(fact: Fact, state: ConflictState, others: Tuple[str, ...]) -> Fact:
    from dataclasses import replace
    return replace(fact, conflict_state=state, conflicting_fact_ids=others)


def conflicted(facts: Iterable[Fact]) -> List[Fact]:
    return [f for f in facts if f.conflict_state is ConflictState.CONFLICT]
