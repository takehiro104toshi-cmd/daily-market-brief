"""Daily incremental update（Phase 3.6 §6 / §7 / §9）。

    latest completed Tokyo session
      → gap detection（期待 session vs canonical）
      → fetch **only missing / partial sessions**（date指定・bounded retry）
      → append（record_id 冪等）
      → recompute **affected** rolling metrics only（最初の新規 session 以降。Fact/Context は
        決定論的 ID なので再実行しても重複しない）

毎朝 60 session を全取得し直さない。repair も欠落 session だけ。途中失敗後の再実行も安全。
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..context.store import ContextStore
from ..facts.store import FactStore
from ..internals.config import InternalsConfig
from ..internals.ingest import InternalsIngestor, fetch_daily_bars_by_date
from ..internals.pipeline import build_internals, internals_contexts
from ..market.jquants_light_store import JQuantsLightStore
from .failure_policy import OK, RetryPolicy, fetch_with_retry
from .rolling_window import WindowPolicy, affected_sessions, seed_sessions
from .session_gap import CALENDAR_UNKNOWN, GapReport

NOOP = "NOOP"
DAILY_UPDATE = "DAILY"
REPAIR = "REPAIR"
SEED = "SEED"
BLOCKED = "BLOCKED"


@dataclass(frozen=True, kw_only=True)
class UpdatePlan:
    dataset: str
    mode: str
    latest_completed: str
    latest_stored: str
    sessions_to_fetch: Tuple[str, ...]
    requests_estimate: int
    repair_range: Tuple[str, str] = ("", "")
    reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"dataset": self.dataset, "mode": self.mode,
                "latest_completed": self.latest_completed, "latest_stored": self.latest_stored,
                "sessions_to_fetch": list(self.sessions_to_fetch),
                "requests_estimate": self.requests_estimate,
                "repair_range": list(self.repair_range), "reason": self.reason}


def plan_update(gap: GapReport, *, policy: WindowPolicy, expected_sessions: Sequence[str],
                seed_count: int = 0) -> UpdatePlan:
    """GapReport → 何を取るか（欠落だけ）。"""
    base = dict(dataset=gap.dataset, latest_completed=gap.latest_completed,
                latest_stored=gap.latest_stored)
    if gap.overall == CALENDAR_UNKNOWN:
        return UpdatePlan(**base, mode=BLOCKED, sessions_to_fetch=(), requests_estimate=0,
                          reason="calendar unknown: expected sessions cannot be determined")
    if not gap.latest_stored:
        wanted = seed_sessions(expected_sessions, policy, count=seed_count)
        return UpdatePlan(**base, mode=SEED, sessions_to_fetch=tuple(wanted),
                          requests_estimate=len(wanted),
                          repair_range=(wanted[0], wanted[-1]) if wanted else ("", ""),
                          reason=f"no stored sessions: seed {len(wanted)} sessions")
    active = set(sorted(expected_sessions)[-(policy.active_calculation_sessions
                                              + policy.safety_buffer_sessions):])
    to_fetch = [s for s in gap.to_fetch if s in active]
    if not to_fetch:
        return UpdatePlan(**base, mode=NOOP, sessions_to_fetch=(), requests_estimate=0,
                          reason="all expected sessions in the active window are stored")
    if to_fetch == [gap.latest_completed]:
        return UpdatePlan(**base, mode=DAILY_UPDATE, sessions_to_fetch=(gap.latest_completed,),
                          requests_estimate=1, repair_range=(gap.latest_completed,
                                                             gap.latest_completed),
                          reason="only the latest completed session is missing")
    return UpdatePlan(**base, mode=REPAIR, sessions_to_fetch=tuple(to_fetch),
                      requests_estimate=len(to_fetch),
                      repair_range=(to_fetch[0], to_fetch[-1]),
                      reason=f"{len(to_fetch)} missing/partial sessions inside the active window")


@dataclass
class UpdateResult:
    plan: UpdatePlan
    fetched: List[str] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)
    requests: int = 0
    rows_added: int = 0
    attempts: Dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def as_dict(self) -> Dict[str, object]:
        return {"plan": self.plan.as_dict(), "fetched": list(self.fetched),
                "failed": dict(self.failed), "requests": self.requests,
                "rows_added": self.rows_added, "attempts": dict(self.attempts),
                "elapsed_seconds": round(self.elapsed_seconds, 2)}


def apply_update(ing: InternalsIngestor, plan: UpdatePlan, *, retry: RetryPolicy,
                 sleeper: Callable[[float], None] = _time.sleep,
                 expected_rows_min: int = 0) -> UpdateResult:
    """計画どおりに **欠落 session だけ** 取得する（bounded retry・冪等 append）。"""
    started = _time.monotonic()
    result = UpdateResult(plan=plan)
    before = ing.stats.requests
    for session in plan.sessions_to_fetch:
        outcome, kind, log = fetch_with_retry(
            lambda s=session: fetch_daily_bars_by_date(ing, s), policy=retry, sleeper=sleeper,
            expected_rows_min=expected_rows_min)
        result.attempts[session] = len(log.attempts)
        if kind == OK:
            result.fetched.append(session)
            result.rows_added += getattr(outcome, "added", 0)
        else:
            result.failed[session] = kind
    result.requests = ing.stats.requests - before
    result.elapsed_seconds = _time.monotonic() - started
    return result


@dataclass
class RecomputeResult:
    window: Tuple[str, str]
    sessions_rebuilt: int
    facts_built: int
    facts_added: int
    facts_skipped: int
    contexts_built: int
    contexts_added: int
    contexts_skipped: int
    elapsed_seconds: float

    def as_dict(self) -> Dict[str, object]:
        return {"window": list(self.window), "sessions_rebuilt": self.sessions_rebuilt,
                "facts_built": self.facts_built, "facts_added": self.facts_added,
                "facts_skipped": self.facts_skipped, "contexts_built": self.contexts_built,
                "contexts_added": self.contexts_added, "contexts_skipped": self.contexts_skipped,
                "elapsed_seconds": round(self.elapsed_seconds, 3)}


def recompute_affected(light: JQuantsLightStore, *, new_sessions: Sequence[str],
                       policy: WindowPolicy, internals_config: InternalsConfig,
                       fact_store: FactStore, context_store: ContextStore,
                       now: Optional[datetime] = None) -> RecomputeResult:
    """新規 session が影響する範囲だけ Fact / Context を再生成し、冪等に追記する。"""
    started = _time.monotonic()
    stored = light.price_dates()
    start, end = affected_sessions(new_sessions, stored, policy)
    if not start:
        return RecomputeResult(window=("", ""), sessions_rebuilt=0, facts_built=0, facts_added=0,
                               facts_skipped=0, contexts_built=0, contexts_added=0,
                               contexts_skipped=0, elapsed_seconds=0.0)
    window = [s for s in stored if start <= s <= end]
    build = build_internals(light, internals_config, window, now=now or datetime.now(timezone.utc))
    facts = build.all_facts
    f = fact_store.add(facts)
    items = internals_contexts(build, internals_config, now=now)
    c = context_store.add(items)
    return RecomputeResult(window=(start, end), sessions_rebuilt=len(build.sessions),
                           facts_built=len(facts), facts_added=f["added"],
                           facts_skipped=f["skipped"], contexts_built=len(items),
                           contexts_added=c["added"], contexts_skipped=c["skipped"],
                           elapsed_seconds=_time.monotonic() - started)
