"""P6-B4C — predicate 評価（純関数）。

- 入力単位: ALL / ANY / NOT / ENTITY_PRESENT / TAXONOMY_SIGNAL / FACT_TYPE / OBSERVATION_SERIES / SOURCE_KIND /
  MIN_DISTINCT（ENTITY_ID / TAXONOMY_TOKEN を入力内で数える）。
- rule 単位（集約）: MIN_DISTINCT（INPUT_ID / EVIDENCE_REF / ENTITY_ID / TAXONOMY_TOKEN）を matched 入力集合で数える。

すべて正規化済みの構造化面に対する完全一致。件数は述語の充足だけを決め、score / 重みにはならない。
taxonomy の親は自動で hit にならない（伝播なし）。
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from .discovery_model import (DiscoveryInputRecord, DistinctDimension, MatchLevel, Predicate, PredicateHit, PredicateKind,
                              PredicateOutcome)


def _entity_hits(record: DiscoveryInputRecord, entity_id: str) -> Tuple[PredicateHit, ...]:
    return tuple(sorted({PredicateHit(kind="ENTITY", value=h.entity_id, level=h.level) for h in record.entity_hits
                         if h.entity_id == entity_id}, key=lambda h: (h.level.value, h.value)))


def _taxonomy_hits(record: DiscoveryInputRecord, slug: str) -> Tuple[PredicateHit, ...]:
    hits = set()
    if slug in record.taxonomy_tokens:
        hits.add(PredicateHit(kind="TAXONOMY", value=slug, level=MatchLevel.L1))
    for hit in record.taxonomy_hits:
        if hit.slug == slug:                                   # 親 slug は数えない（伝播なし）
            hits.add(PredicateHit(kind="TAXONOMY", value=slug, level=hit.level))
    return tuple(sorted(hits, key=lambda h: (h.level.value, h.value)))


def _distinct_within(record: DiscoveryInputRecord, dimension: DistinctDimension) -> int:
    if dimension is DistinctDimension.ENTITY_ID:
        return len(record.entity_ids())
    if dimension is DistinctDimension.TAXONOMY_TOKEN:
        return len(record.taxonomy_slugs())
    raise ValueError(f"per-input MIN_DISTINCT does not support {dimension.value}")


def evaluate_predicate(predicate: Predicate, record: DiscoveryInputRecord) -> PredicateOutcome:
    kind = predicate.kind
    if kind is PredicateKind.ALL:
        outcomes = [evaluate_predicate(c, record) for c in predicate.children]
        if all(o.matched for o in outcomes):
            return PredicateOutcome(matched=True, hits=_merge(o.hits for o in outcomes))
        return PredicateOutcome(matched=False)
    if kind is PredicateKind.ANY:
        outcomes = [evaluate_predicate(c, record) for c in predicate.children]
        matched = [o for o in outcomes if o.matched]
        if matched:
            return PredicateOutcome(matched=True, hits=_merge(o.hits for o in matched))
        return PredicateOutcome(matched=False)
    if kind is PredicateKind.NOT:
        inner = evaluate_predicate(predicate.children[0], record)
        return PredicateOutcome(matched=not inner.matched)              # 否定は hit を持たない
    if kind is PredicateKind.ENTITY_PRESENT:
        hits = _entity_hits(record, predicate.entity_id)
        return PredicateOutcome(matched=bool(hits), hits=hits)
    if kind is PredicateKind.TAXONOMY_SIGNAL:
        hits = _taxonomy_hits(record, predicate.slug)
        return PredicateOutcome(matched=bool(hits), hits=hits)
    if kind is PredicateKind.FACT_TYPE:
        matched = record.fact_type != "" and record.fact_type == predicate.fact_type
        return PredicateOutcome(matched=matched, hits=(PredicateHit(kind="FACT_TYPE", value=predicate.fact_type, level=MatchLevel.L1),)
                                if matched else ())
    if kind is PredicateKind.OBSERVATION_SERIES:
        matched = record.observation_series != "" and record.observation_series == predicate.series_id
        return PredicateOutcome(matched=matched, hits=(PredicateHit(kind="OBSERVATION_SERIES", value=predicate.series_id,
                                                                    level=MatchLevel.L1),) if matched else ())
    if kind is PredicateKind.SOURCE_KIND:
        matched = record.source_kind is predicate.source_kind
        return PredicateOutcome(matched=matched, hits=(PredicateHit(kind="SOURCE_KIND", value=predicate.source_kind.value,
                                                                    level=MatchLevel.L1),) if matched else ())
    if kind is PredicateKind.MIN_DISTINCT:
        assert predicate.dimension is not None
        return PredicateOutcome(matched=_distinct_within(record, predicate.dimension) >= predicate.min_count)
    raise ValueError(f"unsupported predicate kind {kind!r}")


def _merge(groups: Iterable[Tuple[PredicateHit, ...]]) -> Tuple[PredicateHit, ...]:
    merged = set()
    for group in groups:
        merged.update(group)
    return tuple(sorted(merged, key=lambda h: (h.kind, h.value, h.level.value)))


def distinct_count(records: Sequence[DiscoveryInputRecord], dimension: DistinctDimension) -> int:
    """matched 入力集合に対する distinct 数（集約 MIN_DISTINCT 用）。独立 source 数ではない。"""
    if dimension is DistinctDimension.INPUT_ID:
        return len({r.input_id for r in records})
    if dimension is DistinctDimension.EVIDENCE_REF:
        return len({(r.evidence_kind.value, r.input_id) for r in records})
    if dimension is DistinctDimension.ENTITY_ID:
        return len({e for r in records for e in r.entity_ids()})
    if dimension is DistinctDimension.TAXONOMY_TOKEN:
        return len({s for r in records for s in r.taxonomy_slugs()})
    raise ValueError(f"unsupported dimension {dimension!r}")


def evaluate_aggregate(predicates: Sequence[Predicate], records: Sequence[DiscoveryInputRecord]) -> Tuple[bool, Tuple[str, ...]]:
    """rule 単位の MIN_DISTINCT。(satisfied, diagnostics)。"""
    diagnostics: List[str] = []
    satisfied = True
    for predicate in predicates:
        assert predicate.kind is PredicateKind.MIN_DISTINCT and predicate.dimension is not None
        count = distinct_count(records, predicate.dimension)
        if count < predicate.min_count:
            satisfied = False
            diagnostics.append(f"MIN_DISTINCT_NOT_MET:{predicate.dimension.value}:{count}<{predicate.min_count}")
    return satisfied, tuple(diagnostics)
