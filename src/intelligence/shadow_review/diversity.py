"""Type diversity（Phase 3.9.3）— REVIEW_RECOMMENDED だけに掛かる決定的 round-robin + hard cap。

REJECT_RECOMMENDED / APPROVE_RECOMMENDED は diversity を完全に bypass する（逆行証拠と昇格候補を
型の都合で隠さない）。round-robin は 1 ラウンドにつき各型から 1 件。型の訪問順は「その型の未選択先頭要素の質」
（ranking key から pattern_id を除いた部分）で決め、同質なら config の `type_order` で決定化する。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple

from .config import ShadowReviewPolicy


def group_by_type(rows: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], Tuple]
                  ) -> Dict[str, List[Mapping[str, Any]]]:
    """pattern_type ごとに分け、各グループを ranking で整列する。"""
    groups: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("pattern_type", "")), []).append(row)
    for rows_of_type in groups.values():
        rows_of_type.sort(key=key)
    return groups


def round_robin(rows: Sequence[Mapping[str, Any]], slots: int, policy: ShadowReviewPolicy,
                key: Callable[[Mapping[str, Any]], Tuple]) -> List[Mapping[str, Any]]:
    """slots 個を型分散して選ぶ。決定的で、同じ入力からは常に同じ並びを返す。"""
    if slots <= 0 or not rows:
        return []
    groups = group_by_type(rows, key)
    order_index = {t: i for i, t in enumerate(policy.type_order)}
    unknown_rank = len(order_index)
    position: Dict[str, int] = {t: 0 for t in groups}
    taken_of_type: Dict[str, int] = {t: 0 for t in groups}
    taken: List[Mapping[str, Any]] = []
    while len(taken) < slots:
        available = [t for t in groups
                     if position[t] < len(groups[t]) and taken_of_type[t] < policy.type_cap(t)]
        if not available:
            break
        # 型の訪問順は「その型の先頭要素の質」で決める。key の末尾（pattern_id）は型間比較から外す
        # ——外さないと id のアルファベット順が勝ち、config の type_order が永久に発火しないため。
        available.sort(key=lambda t: (key(groups[t][position[t]])[:-1],
                                      order_index.get(t, unknown_rank), t))
        progressed = False
        for pattern_type in available:
            if len(taken) >= slots:
                break
            taken.append(groups[pattern_type][position[pattern_type]])
            position[pattern_type] += 1
            taken_of_type[pattern_type] += 1
            progressed = True
        if not progressed:                                  # 念のための無限ループ止め
            break
    return taken
