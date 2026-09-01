"""Evidence Package（Phase 3-C §7 / §8）。

Morning Context Snapshotから、**generatorに渡してよい根拠の集合**を決定論的に
組む。generatorが見られるのはこのpackageだけ（それ以外の情報は存在しない扱い）。

規律:
- **look-ahead禁止**: 支持Factの `known_at` が朝のcutoffを超えるContextは除外し、
  除外したことを記録する（黙って落とさない）。
- **evidence budget**: salience tier（PRIMARY→core / SECONDARY→supporting /
  BACKGROUND→optional）ごとの上限で選ぶ。上限超過分は `excluded_over_budget` に残す。
- **missingness保持**: 欠落・STALE・CONFLICTED・LIMITED_USE の次元をpackageに持ち、
  generator/validatorが「語らない」判断をできるようにする。
- **Factを複製しない**: 参照するFact本体はsnapshotの外から `facts` で受け取る
  （Fact storeを読むのは呼び出し側）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..context.model import (
    CompassContextSnapshot,
    ContextItem,
    ContextStatus,
    PriorityTier,
    STATE_DIMENSIONS,
)
from ..context.snapshot import _DIMENSION_SOURCES
from ..core.ids import content_id
from ..facts.model import Fact, FactStatus
from .config import DEFAULT_BUDGET

PACKAGE_RULE_VERSION = "evidence_package:1.0.0"

#: 水準Fact（cited subjectの「いくらか」を言うために添える）
LEVEL_FACT_TYPES: Tuple[str, ...] = (
    "index_close", "yield_level", "fx_level", "nt_ratio", "yield_spread",
    "moving_average_25session",
)

_TIER_BUCKET = {PriorityTier.PRIMARY: "core", PriorityTier.SECONDARY: "supporting",
                PriorityTier.BACKGROUND: "optional"}


@dataclass(frozen=True, kw_only=True)
class EvidencePackage:
    package_id: str
    session_date: str
    reference_session: str
    cutoff: datetime
    contexts: Tuple[ContextItem, ...]
    facts: Tuple[Fact, ...]
    core_context_ids: Tuple[str, ...] = ()
    supporting_context_ids: Tuple[str, ...] = ()
    optional_context_ids: Tuple[str, ...] = ()
    dimension_status: Mapping[str, ContextStatus] = field(default_factory=dict)
    dimension_context_ids: Mapping[str, str] = field(default_factory=dict)
    excluded_look_ahead: Tuple[str, ...] = ()
    excluded_over_budget: Tuple[str, ...] = ()
    excluded_unusable_fact: Tuple[str, ...] = ()
    budget: Mapping[str, int] = field(default_factory=dict)
    rule_version: str = PACKAGE_RULE_VERSION

    # ---------------------------------------------------------------- lookup

    def context(self, context_id: str) -> Optional[ContextItem]:
        return self._contexts_by_id.get(context_id)

    def fact(self, fact_id: str) -> Optional[Fact]:
        return self._facts_by_id.get(fact_id)

    @property
    def _contexts_by_id(self) -> Dict[str, ContextItem]:
        return {c.context_id: c for c in self.contexts}

    @property
    def _facts_by_id(self) -> Dict[str, Fact]:
        return {f.fact_id: f for f in self.facts}

    @property
    def context_ids(self) -> Tuple[str, ...]:
        return tuple(c.context_id for c in self.contexts)

    @property
    def fact_ids(self) -> Tuple[str, ...]:
        return tuple(f.fact_id for f in self.facts)

    def contexts_of(self, *context_types: str) -> List[ContextItem]:
        return [c for c in self.contexts if c.context_type in context_types]

    def context_for(self, context_type: str, subject_id: str) -> Optional[ContextItem]:
        """(type, subject) の**最新session**のContext。"""
        candidates = [c for c in self.contexts if c.context_type == context_type
                      and c.subject.subject_id == subject_id]
        if not candidates:
            return None
        return max(candidates, key=lambda c: c.time.session_date)

    def dimension_context(self, dimension: str) -> Optional[ContextItem]:
        cid = self.dimension_context_ids.get(dimension)
        return self.context(cid) if cid else None

    def dimensions_with_status(self, *statuses: ContextStatus) -> Tuple[str, ...]:
        return tuple(d for d in STATE_DIMENSIONS
                     if self.dimension_status.get(d, ContextStatus.MISSING) in statuses)

    @property
    def missing_dimensions(self) -> Tuple[str, ...]:
        return self.dimensions_with_status(ContextStatus.MISSING)

    @property
    def unreliable_dimensions(self) -> Tuple[str, ...]:
        """**語ってはいけない**次元（欠落・古い・矛盾・履歴不足）。"""
        return self.dimensions_with_status(
            ContextStatus.MISSING, ContextStatus.STALE, ContextStatus.CONFLICTED,
            ContextStatus.INSUFFICIENT_HISTORY)

    def facts_for_context(self, context_id: str) -> List[Fact]:
        item = self.context(context_id)
        if item is None:
            return []
        return [f for f in (self.fact(i) for i in item.supporting_fact_ids)
                if f is not None]

    def level_facts_for(self, subject_id: str) -> List[Fact]:
        return [f for f in self.facts if f.subject.subject_id == subject_id
                and f.fact_type in LEVEL_FACT_TYPES]

    # ---------------------------------------------------------------- export

    def as_dict(self) -> Dict[str, object]:
        return {
            "package_id": self.package_id,
            "session_date": self.session_date,
            "reference_session": self.reference_session,
            "cutoff": self.cutoff.isoformat(),
            "rule_version": self.rule_version,
            "budget": dict(self.budget),
            "core_context_ids": list(self.core_context_ids),
            "supporting_context_ids": list(self.supporting_context_ids),
            "optional_context_ids": list(self.optional_context_ids),
            "context_count": len(self.contexts),
            "fact_count": len(self.facts),
            "dimension_status": {k: v.value for k, v in self.dimension_status.items()},
            "dimension_context_ids": dict(self.dimension_context_ids),
            "excluded_look_ahead": list(self.excluded_look_ahead),
            "excluded_over_budget": list(self.excluded_over_budget),
            "excluded_unusable_fact": list(self.excluded_unusable_fact),
        }

    def prompt_payload(self) -> Dict[str, object]:
        """generatorへ渡す**構造化データ**（自由文は含めない＝prompt injection境界）。

        display_name / note は人間可読ラベルだが、生成物の根拠にはならない。
        LLMへは**whitelistしたフィールドのみ**を渡す（note・excerpt・locatorは渡さない）。
        """
        return {
            "session_date": self.session_date,
            "reference_session": self.reference_session,
            "contexts": [
                {"context_id": c.context_id, "context_type": c.context_type,
                 "subject_id": c.subject.subject_id,
                 "display_name": c.subject.display_name,
                 "session_date": c.time.session_date,
                 "direction": c.direction.value,
                 "relationship": c.relationship.value if c.relationship else "",
                 "magnitude": str(c.magnitude) if c.magnitude is not None else "",
                 "magnitude_unit": c.magnitude_unit,
                 "status": c.status.value,
                 "priority_tier": c.priority_tier.value,
                 "supporting_fact_ids": list(c.supporting_fact_ids)}
                for c in self.contexts],
            "facts": [
                {"fact_id": f.fact_id, "fact_type": f.fact_type,
                 "subject_id": f.subject.subject_id,
                 "value": str(f.value.value) if f.value.value is not None else "",
                 "unit": f.value.unit, "primary_date": f.time.primary_date,
                 "session_count": f.time.session_count}
                for f in self.facts],
            "dimension_status": {k: v.value for k, v in self.dimension_status.items()},
            "missing_dimensions": list(self.missing_dimensions),
        }


def _dimension_representatives(items: Sequence[ContextItem]) -> Dict[str, ContextItem]:
    """market state 各次元を代表する**最新session**のContext（budget対象外）。"""
    latest: Dict[Tuple[str, str], ContextItem] = {}
    for c in items:
        key = (c.context_type, c.subject.subject_id)
        if key not in latest or c.time.session_date > latest[key].time.session_date:
            latest[key] = c
    out: Dict[str, ContextItem] = {}
    for dimension, source in _DIMENSION_SOURCES.items():
        item = latest.get(source)
        if item is not None:
            out[dimension] = item
    return out


def _select_by_budget(items: Sequence[ContextItem], budget: Mapping[str, int],
                      pinned: Iterable[str] = ()
                      ) -> Tuple[Dict[str, List[ContextItem]], List[ContextItem]]:
    """tier別の上限で選ぶ。入力順（salience ranking順）を保つ。

    `pinned`（market state次元の代表Context）は**予算を消費せず必ずcoreへ入る**——
    予算で次元そのものが欠落する（usd_jpyが語れなくなる等）ことを防ぐ。
    """
    pinned_ids = set(pinned)
    chosen: Dict[str, List[ContextItem]] = {"core": [], "supporting": [], "optional": []}
    dropped: List[ContextItem] = []
    counts = {"core": 0, "supporting": 0, "optional": 0}
    for item in items:
        if item.context_id in pinned_ids:
            chosen["core"].append(item)
            continue
        bucket = _TIER_BUCKET.get(item.priority_tier, "optional")
        if counts[bucket] < int(budget.get(bucket, 0)):
            chosen[bucket].append(item)
            counts[bucket] += 1
        else:
            dropped.append(item)
    return chosen, dropped


def build_evidence_package(
    snapshot: CompassContextSnapshot,
    facts: Iterable[Fact],
    *,
    budget: Optional[Mapping[str, int]] = None,
) -> EvidencePackage:
    """snapshot（朝時点のContext）と参照可能なFactからEvidence Packageを組む。"""
    budget = dict(budget or DEFAULT_BUDGET)
    facts_by_id: Dict[str, Fact] = {f.fact_id: f for f in facts}
    cutoff = snapshot.cutoff

    usable: List[ContextItem] = []
    look_ahead: List[str] = []
    unusable_fact: List[str] = []
    for item in snapshot.items:
        supporting = [facts_by_id.get(i) for i in item.supporting_fact_ids]
        if any(f is None for f in supporting):
            unusable_fact.append(item.context_id)      # provenanceを辿れない→使わない
            continue
        if any(f.time.known_at is None or f.time.known_at > cutoff for f in supporting):
            look_ahead.append(item.context_id)          # FAIL-CLOSED
            continue
        if any(f.status in (FactStatus.UNUSABLE, FactStatus.SUPERSEDED)
               for f in supporting):
            unusable_fact.append(item.context_id)
            continue
        usable.append(item)

    pinned = [c.context_id for c in _dimension_representatives(usable).values()]
    chosen, dropped = _select_by_budget(usable, budget, pinned)
    selected = chosen["core"] + chosen["supporting"] + chosen["optional"]

    fact_ids: List[str] = []
    for item in selected:
        for fid in item.supporting_fact_ids:
            if fid not in fact_ids:
                fact_ids.append(fid)
    # 水準Fact（cutoff時点で既知・usableのものだけ）
    cited_subjects = {c.subject.subject_id for c in selected}
    for subject_id in sorted(cited_subjects):
        levels = [f for f in facts_by_id.values()
                  if f.subject.subject_id == subject_id
                  and f.fact_type in LEVEL_FACT_TYPES
                  and f.status is FactStatus.USABLE
                  and f.time.known_at is not None and f.time.known_at <= cutoff
                  and f.time.primary_date == snapshot.reference_session]
        for fact in sorted(levels, key=lambda f: (f.fact_type, f.fact_id)):
            if fact.fact_id not in fact_ids:
                fact_ids.append(fact.fact_id)

    package_facts = tuple(facts_by_id[i] for i in fact_ids)
    dimension_context_ids: Dict[str, str] = {}
    selected_by_key: Dict[Tuple[str, str], ContextItem] = {}
    for c in selected:                       # 同じ次元は**最新session**のContextを採る
        key = (c.context_type, c.subject.subject_id)
        if key not in selected_by_key or c.time.session_date > selected_by_key[key].time.session_date:
            selected_by_key[key] = c
    for dimension, source in _DIMENSION_SOURCES.items():
        item = selected_by_key.get(source)
        if item is not None:
            dimension_context_ids[dimension] = item.context_id
    dimension_status: Dict[str, ContextStatus] = {}
    for dimension in STATE_DIMENSIONS:
        status = snapshot.dimension_status.get(dimension, ContextStatus.MISSING)
        if dimension not in dimension_context_ids and status is not ContextStatus.MISSING:
            status = ContextStatus.MISSING   # 除外/予算超過で使えない→欠落として扱う
        dimension_status[dimension] = status

    package_id = content_id(
        "evpkg", snapshot.session_date, snapshot.reference_session, cutoff.isoformat(),
        PACKAGE_RULE_VERSION, "|".join(c.context_id for c in selected),
        "|".join(fact_ids))
    return EvidencePackage(
        package_id=package_id, session_date=snapshot.session_date,
        reference_session=snapshot.reference_session, cutoff=cutoff,
        contexts=tuple(selected), facts=package_facts,
        core_context_ids=tuple(c.context_id for c in chosen["core"]),
        supporting_context_ids=tuple(c.context_id for c in chosen["supporting"]),
        optional_context_ids=tuple(c.context_id for c in chosen["optional"]),
        dimension_status=dimension_status,
        dimension_context_ids=dimension_context_ids,
        excluded_look_ahead=tuple(look_ahead),
        excluded_over_budget=tuple(c.context_id for c in dropped),
        excluded_unusable_fact=tuple(unusable_fact),
        budget=budget)
