"""P6-B5B — 解決済み relation 上の記述的な read view（純関数。派生であり authority ではない）。

`build_relation_graph_view(resolution) -> ThemeRelationGraphView`

- 問い合わせは記述のみ。順位付け・score・中心性・重要度・推奨は持たない（B5-D9）。
- 推移的な関係を作らない。`A CAUSES B` と `B CAUSES C` があっても `A CAUSES C` は現れない。
- 既定では ACTIVE な辺だけを返す。撤回された辺は履歴として別に保持し、明示要求でのみ返す。
- 逆辺 record は存在しない。`incoming` は同じ record 集合を逆引きするだけ。
- 出力順は edge key の辞書順で決定論的。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Tuple

from .relation_model import RelationType
from .relation_resolution import (EdgeState, ExcludedEdge, RelationDiagnostic, RelationResolutionStatus,
                                  ResolvedRelation, ThemeRelationResolution, UnresolvedEdge)

RELATION_GRAPH_VIEW_VERSION = "theme_relation_graph:0.1.0"


class Direction(str, Enum):
    """問い合わせた root から見た向き。"""

    OUTGOING = "OUTGOING"
    INCOMING = "INCOMING"


@dataclass(frozen=True, kw_only=True)
class RelationNeighbor:
    """隣接 1 件。どちらの向きで隣接しているかを必ず明示する。"""

    root_id: str
    direction: Direction
    relation: ResolvedRelation


def _ordered(relations: List[ResolvedRelation]) -> Tuple[ResolvedRelation, ...]:
    return tuple(sorted(relations, key=lambda r: r.edge_key))


@dataclass(frozen=True, kw_only=True)
class ThemeRelationGraphView:
    """解決済み relation の記述的 view。authority ではなく、保存もしない。"""

    view_version: str
    resolver_version: str
    cutoff: datetime
    status: RelationResolutionStatus
    relations: Tuple[ResolvedRelation, ...]
    retracted: Tuple[ResolvedRelation, ...]
    unresolved: Tuple[UnresolvedEdge, ...]
    excluded: Tuple[ExcludedEdge, ...]
    diagnostics: Tuple[RelationDiagnostic, ...]

    def _pool(self, include_retracted: bool) -> Tuple[ResolvedRelation, ...]:
        return _ordered(list(self.relations) + list(self.retracted)) if include_retracted else self.relations

    def roots(self) -> Tuple[str, ...]:
        """graph に現れる root（順序は辞書順。重要度ではない）。"""
        found = {r.source_theme_root_id for r in self.relations} | {r.target_theme_root_id for r in self.relations}
        return tuple(sorted(found))

    def outgoing(self, root_id: str, *, include_retracted: bool = False) -> Tuple[ResolvedRelation, ...]:
        """`root_id` を source とする辺。"""
        return _ordered([r for r in self._pool(include_retracted) if r.source_theme_root_id == root_id])

    def incoming(self, root_id: str, *, include_retracted: bool = False) -> Tuple[ResolvedRelation, ...]:
        """`root_id` を target とする辺（逆辺 record は保存していない。同じ record を逆引きする）。"""
        return _ordered([r for r in self._pool(include_retracted) if r.target_theme_root_id == root_id])

    def neighbors(self, root_id: str, *, include_retracted: bool = False) -> Tuple[RelationNeighbor, ...]:
        """入出力の両方向の隣接。各件に向きを付けて返す（無向にまとめない）。"""
        out = [RelationNeighbor(root_id=r.target_theme_root_id, direction=Direction.OUTGOING, relation=r)
               for r in self.outgoing(root_id, include_retracted=include_retracted)]
        incoming = [RelationNeighbor(root_id=r.source_theme_root_id, direction=Direction.INCOMING, relation=r)
                    for r in self.incoming(root_id, include_retracted=include_retracted)]
        return tuple(sorted(out + incoming, key=lambda n: (n.direction.value, n.relation.edge_key)))

    def relations_between(self, a: str, b: str, *, include_retracted: bool = False) -> Tuple[ResolvedRelation, ...]:
        """2 root の間の辺（両向きを返す。各件の source / target で向きを判別する）。"""
        pair = {(a, b), (b, a)}
        return _ordered([r for r in self._pool(include_retracted)
                         if (r.source_theme_root_id, r.target_theme_root_id) in pair])

    def relations_by_type(self, relation_type: RelationType, *, include_retracted: bool = False
                          ) -> Tuple[ResolvedRelation, ...]:
        return _ordered([r for r in self._pool(include_retracted) if r.relation_type is relation_type])

    def to_plain(self) -> Dict[str, object]:
        """決定論的な plain 表現（test / 監査用。保存しない）。"""
        return {
            "view_version": self.view_version, "resolver_version": self.resolver_version,
            "cutoff": self.cutoff.isoformat(), "status": self.status.value,
            "relations": [_relation_plain(r) for r in self.relations],
            "retracted": [_relation_plain(r) for r in self.retracted],
            "unresolved": [{"edge_key": u.edge_key, "status": u.status.value, "diagnostics": list(u.diagnostics)}
                           for u in self.unresolved],
            "excluded": [{"edge_key": e.edge_key, "reason": e.reason} for e in self.excluded],
            "diagnostics": [list(d.as_tuple()) for d in self.diagnostics],
        }


def _relation_plain(relation: ResolvedRelation) -> Dict[str, object]:
    return {"edge_key": relation.edge_key, "source_theme_root_id": relation.source_theme_root_id,
            "target_theme_root_id": relation.target_theme_root_id, "relation_type": relation.relation_type.value,
            "assertion_class": relation.assertion_class.value, "attribution_key": relation.attribution_key,
            "edge_state": relation.edge_state.value, "relation_assertion_id": relation.assertion.relation_assertion_id,
            "assertion_chain": list(relation.assertion_chain), "governance_chain": list(relation.governance_chain),
            "source_endpoint": relation.source_endpoint.value, "target_endpoint": relation.target_endpoint.value,
            "diagnostics": list(relation.diagnostics)}


def build_relation_graph_view(resolution: ThemeRelationResolution) -> ThemeRelationGraphView:
    """解決結果から派生 view を作る。辺を増やさない・畳まない・順位付けしない。"""
    if not isinstance(resolution, ThemeRelationResolution):
        raise TypeError("build_relation_graph_view takes a ThemeRelationResolution")
    return ThemeRelationGraphView(
        view_version=RELATION_GRAPH_VIEW_VERSION, resolver_version=resolution.resolver_version,
        cutoff=resolution.cutoff, status=resolution.status,
        relations=_ordered([e for e in resolution.edges if e.edge_state is EdgeState.ACTIVE]),
        retracted=_ordered([e for e in resolution.edges if e.edge_state is EdgeState.RETRACTED]),
        unresolved=resolution.unresolved, excluded=resolution.excluded, diagnostics=resolution.diagnostics)


__all__ = ["Direction", "RELATION_GRAPH_VIEW_VERSION", "RelationNeighbor", "ThemeRelationGraphView",
           "build_relation_graph_view"]
