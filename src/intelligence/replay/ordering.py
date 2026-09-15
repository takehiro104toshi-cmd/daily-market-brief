"""Canonical ordering と position 計画（Phase 3.9.4）。

CHRONOLOGICAL: document_date ASC, date_sequence ASC, document_id ASC（undated は除外・記録）
INGESTION    : received_at ASC, document_id ASC
position     : eligible 文書の累積数（CORPUS_n と同じ尺度）。usable_position も併記する。
snapshot k   : k 番目の eligible 文書までの prefix（それより後の PARTIAL はまだ含まない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Sequence, Set, Tuple

from .config import (
    MODE_FULL,
    MODE_MILESTONE,
    MODE_MILESTONE_AND_TRANSITION,
    MODE_TRANSITION,
    ORDER_CHRONOLOGICAL,
    ORDER_INGESTION,
    ReplayPolicy,
)
from .errors import ReplayPolicyError, ReplayUndatedExceeded
from .manifest import EXCL_UNDATED, InputManifest, ManifestDocument


@dataclass(frozen=True)
class OrderedDocument:
    index: int                    # 0-based prefix index
    document: ManifestDocument
    eligible_position: int        # この文書を含めた eligible 累積
    usable_position: int          # この文書を含めた usable 累積


@dataclass(frozen=True)
class Ordering:
    mode: str
    items: Sequence[OrderedDocument]
    excluded_undated: Sequence[str]
    undated_ratio: Decimal

    @property
    def max_eligible(self) -> int:
        return self.items[-1].eligible_position if self.items else 0

    def prefix_for_eligible(self, k: int) -> Sequence[OrderedDocument]:
        """k 番目の eligible 文書で終わる prefix。"""
        for item in self.items:
            if item.eligible_position == k and item.document.eligible:
                return list(self.items[: item.index + 1])
        raise ValueError(f"no eligible position {k}")

    def index_for_eligible(self, k: int) -> int:
        return self.prefix_for_eligible(k)[-1].index


def canonical_order(manifest: InputManifest, mode: str, policy: ReplayPolicy) -> Ordering:
    usable = manifest.usable_documents()
    if mode == ORDER_CHRONOLOGICAL:
        undated = [d for d in usable if d.undated]
        ratio = (Decimal(len(undated)) / Decimal(len(usable))) if usable else Decimal("0")
        if ratio > policy.max_undated_ratio:
            raise ReplayUndatedExceeded(
                f"undated usable documents {len(undated)}/{len(usable)} exceed max_undated_ratio "
                f"{policy.max_undated_ratio}; refusing to invent chronology")
        dated = [d for d in usable if not d.undated]
        ordered = sorted(dated, key=lambda d: (d.document_date, d.date_sequence, d.document_id))
        excluded = sorted(d.document_id for d in undated)
    elif mode == ORDER_INGESTION:
        ordered = sorted(usable, key=lambda d: (d.received_at, d.document_id))
        excluded, ratio = [], Decimal("0")
    else:
        raise ReplayPolicyError(f"unknown ordering mode: {mode}")
    items: List[OrderedDocument] = []
    eligible = usable_count = 0
    for i, d in enumerate(ordered):
        usable_count += 1
        if d.eligible:
            eligible += 1
        items.append(OrderedDocument(index=i, document=d, eligible_position=eligible, usable_position=usable_count))
    return Ordering(mode=mode, items=tuple(items), excluded_undated=tuple(excluded), undated_ratio=ratio)


def milestone_positions(policy: ReplayPolicy, max_eligible: int) -> List[int]:
    points = [p for p in policy.milestone_points if p <= max_eligible]
    if max_eligible >= 1 and max_eligible not in points:
        points.append(max_eligible)                     # current（未表現なら追加）
    return sorted(set(points))


def coarse_positions(policy: ReplayPolicy, mode: str, max_eligible: int) -> List[int]:
    """mode ごとの評価 position（eligible 単位）。current は常に含む。"""
    if max_eligible < 1:
        return []
    if mode == MODE_FULL:
        if not policy.full_replay_enabled:
            raise ReplayPolicyError("FULL_REPLAY requested but full_replay_enabled is false")
        points = set(range(1, max_eligible + 1))
    elif mode == MODE_MILESTONE:
        points = set(milestone_positions(policy, max_eligible))
    elif mode in (MODE_TRANSITION, MODE_MILESTONE_AND_TRANSITION):
        step = policy.transition_resolution
        points = set(range(step, max_eligible + 1, step))
        if mode == MODE_MILESTONE_AND_TRANSITION:
            points |= set(milestone_positions(policy, max_eligible))
        points.add(max_eligible)
    else:
        raise ReplayPolicyError(f"unknown replay mode: {mode}")
    out = sorted(points)
    if len(out) > policy.max_snapshots:
        raise ReplayPolicyError(f"{len(out)} snapshots exceed max_snapshots {policy.max_snapshots}")
    return out
