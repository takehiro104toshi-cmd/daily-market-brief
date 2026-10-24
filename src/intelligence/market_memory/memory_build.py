"""P13-A3 — 明示の cutoff の計画から Memory の generation を作り、store の狭い面で公開する（filesystem の呼び出しは無い）。

手順: 計画の検証（`at` は厳密に増加 ・重複は拒む）→ plan digest → source の root と memory root の重なりの検査 → writer lock →
staging が空 ・公開の pointer が検証できる（または未公開）→ A2a の `sample_review_state` だけで各 cutoff を読む →
- 1 つでも SAMPLED でなければ **公開しない**: 安全な試行の証拠（計画の digest ・cutoff ・状態 ・固定の code）だけを残し、pointer は変えない。
- 全て SAMPLED なら generation（標本 ・端点の差）を作り、store が stage ・検証 ・不変の directory ・pointer の置換 ・読み戻しの検証を行う。
lock は全ての経路で所有を検証して解放する（検証できなければ残す）。結果は固定の code ・digest だけ（root ・値 ・時刻は無い）。
時計 ・telemetry（`sampled_at` ・host ・process）は使わない ・残さない。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Optional, Sequence

from .governed_review_source import ADAPTER_RULES_VERSION, SUPPORTED_VIEW_IDENTITY, sample_review_state
from .memory_generation import PLAN_DIGEST_MISMATCH, MemoryGenerationError, attempt_from_outcomes, build_generation, plan_digest
from .memory_store import (LOCK_NOT_ACQUIRED, PUBLICATION_NOT_VERIFIED, MemoryStore, MemoryStoreError, PublishStatus, ReadStatus,
                           WriterLock)
from .review_state_sample import OutcomeStatus, ReviewStateError, SampleCutoff

BUILD_INPUT_INVALID = "BUILD_INPUT_INVALID"
PLAN_INCOMPLETE = "PLAN_INCOMPLETE"
SOURCE_LABELS = ("SOURCE_P10", "SOURCE_P9")


class BuildStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    REUSED = "REUSED"
    INCOMPLETE = "INCOMPLETE"
    REFUSED = "REFUSED"
    FAILED = "FAILED"


class MemoryBuildError(ValueError):
    """呼び出し側の入力の誤り（store の型 ・計画の形 ・cutoff の順序）。source は読まない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, kw_only=True)
class BuildResult:
    """build の結果（固定の code ・digest だけ）。`publication_*` は build の後に読み戻して検証した pointer の状態。"""

    status: BuildStatus
    code: str
    plan_digest: str
    generation_digest: Optional[str] = None
    manifest_digest: Optional[str] = None
    attempt_digest: Optional[str] = None
    attempt_code: Optional[str] = None
    lock_release: str = LOCK_NOT_ACQUIRED
    publication_status: Optional[ReadStatus] = None
    publication_generation_digest: Optional[str] = None


_PUBLISH_TO_BUILD = {PublishStatus.PUBLISHED: BuildStatus.PUBLISHED, PublishStatus.REUSED: BuildStatus.REUSED,
                     PublishStatus.FAILED: BuildStatus.FAILED, PublishStatus.REFUSED: BuildStatus.REFUSED}


def _build_locked(store: MemoryStore, lock: WriterLock, plan: str, cutoffs: tuple, p10_root: Any, p9_root: Any) -> BuildResult:
    try:
        store.check_writable(lock)                                                       # 中断の staging が在れば書かない
    except MemoryStoreError as exc:
        return BuildResult(status=BuildStatus.REFUSED, code=exc.code, plan_digest=plan)
    prior = store.read_publication()
    if prior.status not in (ReadStatus.VERIFIED, ReadStatus.NOT_PUBLISHED):              # 検証できない pointer の上には公開しない
        return BuildResult(status=BuildStatus.REFUSED, code=PUBLICATION_NOT_VERIFIED, plan_digest=plan)
    outcomes = []
    for cutoff in cutoffs:
        try:
            outcomes.append(sample_review_state(p10_root, p9_root, cutoff=cutoff, rules_version=ADAPTER_RULES_VERSION))
        except ReviewStateError as exc:
            return BuildResult(status=BuildStatus.REFUSED, code=exc.code, plan_digest=plan)
    failed = [o for o in outcomes if o.status is not OutcomeStatus.SAMPLED]
    if failed:                                                                           # 不完全な計画は公開しない（証拠だけ）
        attempt = attempt_from_outcomes(plan, cutoffs, outcomes)
        try:
            recorded = store.record_attempt(lock, attempt)
        except MemoryStoreError as exc:
            return BuildResult(status=BuildStatus.FAILED, code=exc.code, plan_digest=plan, attempt_digest=attempt.attempt_digest)
        return BuildResult(status=BuildStatus.INCOMPLETE, code=failed[0].failure_code or PLAN_INCOMPLETE, plan_digest=plan,
                           attempt_digest=attempt.attempt_digest, attempt_code=recorded)
    try:
        generation = build_generation(cutoffs, SUPPORTED_VIEW_IDENTITY, adapter_rules_version=ADAPTER_RULES_VERSION,
                                      samples=[o.sample for o in outcomes])
    except MemoryGenerationError as exc:
        return BuildResult(status=BuildStatus.FAILED, code=exc.code, plan_digest=plan)
    if generation.plan_digest != plan:
        return BuildResult(status=BuildStatus.FAILED, code=PLAN_DIGEST_MISMATCH, plan_digest=plan)
    outcome = store.publish_generation(lock, generation)
    return BuildResult(status=_PUBLISH_TO_BUILD[outcome.status], code=outcome.code, plan_digest=plan,
                       generation_digest=outcome.generation_digest, manifest_digest=outcome.manifest_digest)


def build_memory(store: MemoryStore, p10_root: Any, p9_root: Any, *, cutoffs: Sequence[SampleCutoff]) -> BuildResult:
    """明示の計画で P10 の governed な view を読み、完全な結果だけを公開する（不完全なら試行の証拠だけ ・pointer は不変）。"""
    if not isinstance(store, MemoryStore):
        raise MemoryBuildError(BUILD_INPUT_INVALID, "STORE")
    try:
        plan = plan_digest(cutoffs, SUPPORTED_VIEW_IDENTITY, adapter_rules_version=ADAPTER_RULES_VERSION)
    except MemoryGenerationError as exc:
        raise MemoryBuildError(BUILD_INPUT_INVALID, exc.code) from None
    planned = tuple(cutoffs)
    try:
        store.check_disjoint(dict(zip(SOURCE_LABELS, (p10_root, p9_root))))            # 渡された source の root は memory root の外
    except MemoryStoreError as exc:
        return BuildResult(status=BuildStatus.REFUSED, code=exc.code, plan_digest=plan)
    try:
        lock = store.acquire_writer_lock(operation="BUILD", plan=plan)
    except MemoryStoreError as exc:
        return BuildResult(status=BuildStatus.REFUSED, code=exc.code, plan_digest=plan)
    try:
        result = _build_locked(store, lock, plan, planned, p10_root, p9_root)
    finally:
        release = lock.release()                                                         # 全ての経路（所有を検証できなければ残す）
    after = store.read_publication()
    return replace(result, lock_release=release, publication_status=after.status,
                   publication_generation_digest=after.generation_digest)


__all__ = ["BUILD_INPUT_INVALID", "BuildResult", "BuildStatus", "MemoryBuildError", "PLAN_INCOMPLETE", "SOURCE_LABELS", "build_memory"]
