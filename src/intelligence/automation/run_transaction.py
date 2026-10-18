"""P12-A3 — 1 つの明示の run の運用の transaction（A2 の実行 → finalize 済み artifact → 追記専用 ledger の commit → status の projection）。

**ledger が commit の authority**: run が運用上 SUCCEEDED なのは、検証に通る commit 済みの ledger の record が SUCCEEDED と言う時だけ。
run の directory ・snapshot ・digests.json ・status.json だけでは成功を立てられない。

順（`STAGES`）:
 1. LEDGER_VERIFIED       ledger ＋ head checkpoint を検証（不正 ・遅れは fail closed）・資格情報の不在 ・重複の分類
 2. PLANNED_RECORDED      record（→ PLANNED）を追記 ＋ checkpoint
 3. RUNNING_RECORDED      record（PLANNED → RUNNING）を追記 ＋ checkpoint
 4. EXECUTED              A2 `execute_run`（成功なら run の directory は原子的に finalize 済み ＝ FINALIZED_PENDING_LEDGER）
 5. TERMINAL_RECORDED     record（RUNNING → SUCCEEDED ／ FAILED）を追記 ＋ fsync ＋ checkpoint を原子的に置換
 6. LEDGER_REVERIFIED     file から読み直して鎖 ・checkpoint ・run の状態を再検証
 7. STATUS_PROJECTED      status.json を原子的に再生成
 8. 戻り: SUCCEEDED（ledger が言う時だけ）／ FAILED（code）

crash の窓（A4 が回復。A3 は `classify_run` で区別できる証拠を残す）:
 A. 4 と 5 の間  final の directory は在るが ledger の最後は RUNNING → ORPHANED_FINALIZATION
 B. 5 の追記と checkpoint の間  ledger に正しい尾 ・checkpoint が遅れ → LEDGER_COMMITTED_CHECKPOINT_STALE
 C. 5 ／ 6 と 7 の間  ledger と checkpoint は一致 ・status が古い → STATUS_STALE
重複: 同じ run_id が SUCCEEDED → ALREADY_SUCCEEDED ・final が在って成功の record が無い → ORPHANED_FINALIZATION（上書きしない）・
`.partial` が在る → DUPLICATE_INVOCATION:PARTIAL_EXISTS（A4 に予約）・ledger で開いている ／ 終端の同じ run_id → DUPLICATE_INVOCATION。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .canonical import utc_iso
from .crash_classification import classify_run
from .execution_request import AutomationExecutionRequest
from .execution_result import AutomationExecutionResult
from .failure_codes import AutomationError
from .finalization import FINALIZED_PENDING_LEDGER, PARTIAL_SUFFIX, run_directory
from .ledger_model import LedgerError, make_record
from .ledger_store import LedgerStore
from .network_deny import NetworkPolicy
from .preconditions import PrivateRoots, credential_present
from .run_executor import execute_run
from .run_state import RunState, is_terminal
from .status_store import write_status

STAGES: Tuple[str, ...] = ("LEDGER_VERIFIED", "PLANNED_RECORDED", "RUNNING_RECORDED", "EXECUTED", "TERMINAL_RECORDED",
                           "LEDGER_REVERIFIED", "STATUS_PROJECTED")
TRANSACTION_SCHEMA_VERSION = "p12_run_transaction:0.1.0"
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class TransactionResult:
    run_id: str
    status: str                                # SUCCEEDED ／ FAILED
    failure_code: Optional[str]
    stages_completed: Tuple[str, ...]
    ledger_record_count: Optional[int]
    ledger_head_digest: Optional[str]
    execution: Optional[AutomationExecutionResult]
    status_projection_written: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": TRANSACTION_SCHEMA_VERSION, "run_id": self.run_id, "status": self.status,
                "failure_code": self.failure_code, "stages_completed": list(self.stages_completed),
                "ledger_record_count": self.ledger_record_count, "ledger_head_digest": self.ledger_head_digest,
                "execution": None if self.execution is None else self.execution.to_dict(),
                "status_projection_written": self.status_projection_written}


def _preflight(store: LedgerStore, request: AutomationExecutionRequest, roots: PrivateRoots, environment: Mapping[str, str]) -> Any:
    if credential_present(environment):
        raise AutomationError("CREDENTIAL_PRESENT")                                     # orchestration の前に
    state = store.open_verified()
    final = run_directory(roots.p12_root, request.run_id)
    if final.with_name(final.name + PARTIAL_SUFFIX).exists():
        raise AutomationError("DUPLICATE_INVOCATION", "PARTIAL_EXISTS")                 # A4 の分類に予約
    run_state = state.run_states.get(request.run_id)
    if run_state is RunState.SUCCEEDED:
        raise AutomationError("ALREADY_SUCCEEDED")
    if final.exists():
        raise AutomationError("ORPHANED_FINALIZATION")                                  # final が在って成功の record が無い: 上書きしない
    if run_state is not None:
        raise AutomationError("DUPLICATE_INVOCATION", "RUN_TERMINAL" if is_terminal(run_state) else "RUN_OPEN")
    return state


def commit_run(request: AutomationExecutionRequest, roots: PrivateRoots, *, repo_root: Any, runtime_root: Any,
               environment: Mapping[str, str], clock: Clock, policy: Optional[NetworkPolicy] = None) -> TransactionResult:
    """1 run の運用の transaction。例外は投げない（想定内の失敗は code。想定外は caller ＝ process の crash と同じ）。"""
    if not isinstance(request, AutomationExecutionRequest) or not isinstance(roots, PrivateRoots):
        raise AutomationError("SCHEMA_INVALID", "TRANSACTION_INPUT")
    if not callable(clock):
        raise AutomationError("SCHEMA_INVALID", "CLOCK_REQUIRED")                      # telemetry の時計も暗黙には読まない
    store = LedgerStore(roots.p12_root)
    stages = []
    run = request.run

    def failed(code: str, execution: Optional[AutomationExecutionResult] = None, state: Any = None) -> TransactionResult:
        return TransactionResult(run_id=request.run_id, status="FAILED", failure_code=code, stages_completed=tuple(stages),
                                 ledger_record_count=None if state is None else state.summary.record_count,
                                 ledger_head_digest=None if state is None else state.summary.head_digest, execution=execution,
                                 status_projection_written=False)

    try:
        state = _preflight(store, request, roots, environment)
    except AutomationError as exc:
        return failed(exc.public_code)
    stages.append("LEDGER_VERIFIED")
    try:
        previous = state.records[-1] if state.records else None
        planned = make_record(previous, run, transition_to=RunState.PLANNED, recorded_at=utc_iso(clock()))
        state = store.append(planned)
        stages.append("PLANNED_RECORDED")
        running = make_record(planned, run, transition_from=RunState.PLANNED, transition_to=RunState.RUNNING,
                              recorded_at=utc_iso(clock()))
        state = store.append(running)
        stages.append("RUNNING_RECORDED")
    except AutomationError as exc:
        return failed(exc.public_code, state=state)
    execution = execute_run(request, roots, repo_root=repo_root, runtime_root=runtime_root, environment=environment,
                            policy=policy, clock=clock)
    stages.append("EXECUTED")
    succeeded = execution.status == FINALIZED_PENDING_LEDGER
    try:
        terminal = make_record(running, run, transition_from=RunState.RUNNING,
                               transition_to=RunState.SUCCEEDED if succeeded else RunState.FAILED,
                               recorded_at=utc_iso(clock()), failure_code=None if succeeded else execution.failure_code,
                               step_results=execution.step_results, artifact_digests=execution.artifact_digests)
        state = store.append(terminal)
        stages.append("TERMINAL_RECORDED")
        reverified = store.open_verified()                                              # file から読み直す
        if reverified.summary.head_digest != terminal.record_digest or reverified.run_states.get(request.run_id) is not terminal.transition_to:
            raise LedgerError("REVERIFY_MISMATCH")
        state = reverified
        stages.append("LEDGER_REVERIFIED")
    except AutomationError as exc:
        return failed(exc.public_code, execution, state)
    try:
        write_status(roots.p12_root, state, runtime_anchor=request.runtime_anchor, schedule_id=request.schedule_id, as_of=clock())
        stages.append("STATUS_PROJECTED")
    except AutomationError as exc:
        return TransactionResult(run_id=request.run_id, status="FAILED", failure_code=exc.public_code,
                                 stages_completed=tuple(stages), ledger_record_count=state.summary.record_count,
                                 ledger_head_digest=state.summary.head_digest, execution=execution, status_projection_written=False)
    return TransactionResult(run_id=request.run_id, status="SUCCEEDED" if succeeded else "FAILED",
                             failure_code=None if succeeded else execution.failure_code, stages_completed=tuple(stages),
                             ledger_record_count=state.summary.record_count, ledger_head_digest=state.summary.head_digest,
                             execution=execution, status_projection_written=True)


def classify_after_crash(roots: PrivateRoots, run_id: str) -> Dict[str, Any]:
    """crash の後の証拠の分類（読むだけ）。ledger 自体が不正なら `LEDGER_INVALID:*` を返す。"""
    store = LedgerStore(roots.p12_root)
    try:
        state = store.open_verified(allow_stale_checkpoint=True)
    except AutomationError as exc:
        return {"run_id": run_id, "classification": exc.public_code}
    return classify_run(roots.p12_root, run_id, state).to_dict()


__all__ = ["STAGES", "TRANSACTION_SCHEMA_VERSION", "TransactionResult", "classify_after_crash", "commit_run"]
