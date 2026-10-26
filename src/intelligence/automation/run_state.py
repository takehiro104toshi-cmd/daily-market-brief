"""P12-A1 — run の状態機械（決定論 ・不正な遷移は domain の誤り）。

PLANNED → RUNNING ・SKIPPED ・CANCELLED ・CRASHED
RUNNING → SUCCEEDED ・FAILED ・CANCELLED ・CRASHED ・ORPHANED_FINALIZATION
終端（SUCCEEDED ・FAILED ・SKIPPED ・CANCELLED ・CRASHED ・ORPHANED_FINALIZATION）からの遷移は無い。retry は新しい run。
`ORPHANED_FINALIZATION`: 成果物の directory は finalize されているのに ledger に成功の record が無い状態。成功と解釈しない ・
証拠を残す ・黙って消さない ・黙って昇格しない ・黙って修復しない（回復の実装は A4）。
"""
from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Mapping

from .failure_codes import AutomationError


class RunState(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    CRASHED = "CRASHED"
    ORPHANED_FINALIZATION = "ORPHANED_FINALIZATION"


TERMINAL_STATES: FrozenSet[RunState] = frozenset({RunState.SUCCEEDED, RunState.FAILED, RunState.SKIPPED,
                                                  RunState.CANCELLED, RunState.CRASHED, RunState.ORPHANED_FINALIZATION})
TRANSITIONS: Mapping[RunState, FrozenSet[RunState]] = {
    RunState.PLANNED: frozenset({RunState.RUNNING, RunState.SKIPPED, RunState.CANCELLED, RunState.CRASHED}),
    RunState.RUNNING: frozenset({RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED, RunState.CRASHED,
                                 RunState.ORPHANED_FINALIZATION}),
    RunState.SUCCEEDED: frozenset(), RunState.FAILED: frozenset(), RunState.SKIPPED: frozenset(),
    RunState.CANCELLED: frozenset(), RunState.CRASHED: frozenset(), RunState.ORPHANED_FINALIZATION: frozenset(),
}
INITIAL_STATE = RunState.PLANNED


class IllegalTransition(AutomationError):
    def __init__(self, from_state: RunState, to_state: RunState) -> None:
        super().__init__("ILLEGAL_TRANSITION", f"{from_state.value}_TO_{to_state.value}")
        self.from_state = from_state
        self.to_state = to_state


def parse_state(value: object) -> RunState:
    if isinstance(value, RunState):
        return value
    try:
        return RunState(value)  # type: ignore[arg-type]
    except ValueError:
        raise AutomationError("SCHEMA_INVALID", "RUN_STATE") from None


def is_terminal(state: RunState) -> bool:
    return parse_state(state) in TERMINAL_STATES


def can_transition(from_state: RunState, to_state: RunState) -> bool:
    return parse_state(to_state) in TRANSITIONS[parse_state(from_state)]


def transition(from_state: RunState, to_state: RunState) -> RunState:
    """合法なら `to_state` を返す。終端からの遷移 ・表に無い遷移は `IllegalTransition`（決定論の code）。"""
    source, target = parse_state(from_state), parse_state(to_state)
    if target not in TRANSITIONS[source]:
        raise IllegalTransition(source, target)
    return target


__all__ = ["INITIAL_STATE", "IllegalTransition", "RunState", "TERMINAL_STATES", "TRANSITIONS", "can_transition",
           "is_terminal", "parse_state", "transition"]
