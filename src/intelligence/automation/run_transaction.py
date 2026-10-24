"""P12-A3 ／ A4 — 1 つの明示の run の運用の transaction（A2 の実行 → finalize 済み artifact → 追記専用 ledger の commit → status の projection）。

**ledger が commit の authority**: run が運用上 SUCCEEDED なのは、検証に通る commit 済みの ledger の record が SUCCEEDED と言う時だけ。
run の directory ・snapshot ・digests.json ・status.json だけでは成功を立てられない。

A5.1 で `preflight` ・`record_request` を公開（skip の transaction が同じ重複の分類 ・要求の証拠を使う）。
A4 で足したもの（A3 からの登録済みの再開）: run ごとの排他 lock ・ledger の commit の直列化（`LockedLedger`: lock の中で head を読み直す）・
要求の証拠（`requests/<run_id>.json`）・協調的な cancel の検査 ・決定論の注入点。lock の取得は O_CREAT | O_EXCL（Windows でも原子的）。

順（`STAGES`）:
 1. LEDGER_VERIFIED     ledger ＋ checkpoint の検証（短い ledger lock の中で読む）・資格情報の不在 ・重複の分類（ここまで何も書かない）
 2. LOCK_ACQUIRED       run の lock（在れば分類: 生きていれば DUPLICATE_INVOCATION:RUN_ACTIVE ・stale なら :LOCK_STALE ・不明なら
                        :LOCK_UNKNOWN_PROVENANCE。自動では壊さない）
 3. REQUEST_RECORDED    正準な要求を `requests/<run_id>.json` に置く（retry ・回復の証拠。同じ run_id の違う要求は拒む）
 4. PLANNED_RECORDED    ledger lock の中で record（→ PLANNED）を head に追記 ＋ checkpoint。cancel の要求が在れば → CANCELLED
 5. RUNNING_RECORDED    同じく PLANNED → RUNNING。cancel の要求が在れば → CANCELLED（実行の前が最後の検査）
 6. EXECUTED            A2 `execute_run`
 7. TERMINAL_RECORDED   RUNNING → SUCCEEDED ／ FAILED（commit point ＝ この追記の fsync）
 8. LEDGER_REVERIFIED   file から読み直して再検証
 9. STATUS_PROJECTED    status.json を原子的に再生成（ledger lock の外）
10. LOCK_RELEASED       run の lock を解放（想定内の失敗の戻りでも解放。process の死 ＝ 想定外の例外では残る → lock の分類で回復）

crash の窓（A4 の回復が処理。`classify_run` ・`classify_lock` が証拠で区別する）:
 A. 6 と 7 の間  final の directory が在るが ledger の最後は RUNNING → ORPHANED_FINALIZATION
 B. 7 の追記と checkpoint の間  ledger に正しい尾 ・checkpoint が遅れ → LEDGER_COMMITTED_CHECKPOINT_STALE
 C. 7 ／ 8 と 9 の間  ledger と checkpoint は一致 ・status が古い → STATUS_STALE
重複: 同じ run_id が SUCCEEDED → ALREADY_SUCCEEDED ・final が在って成功の record が無い → ORPHANED_FINALIZATION（上書きしない）・
`.partial` が在る → DUPLICATE_INVOCATION:PARTIAL_EXISTS ・ledger で開いている同じ run_id → lock が生きていれば RUN_ACTIVE ・
そうでなければ RUN_OPEN（回復が要る）・終端の同じ run_id → RUN_TERMINAL（retry は新しい attempt ＝ 新しい run）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .atomic_files import ensure_root_subdirectory, read_text_file, replace_atomically
from .cancel_authority import cancel_requested
from .canonical import utc_iso
from .crash_classification import classify_run
from .execution_request import AutomationExecutionRequest
from .execution_result import AutomationExecutionResult
from .failure_codes import AutomationError
from .finalization import FINALIZED_PENDING_LEDGER, PARTIAL_SUFFIX, run_directory
from .injection import NO_INJECTION, InjectionPoints
from .ledger_commit import LockedLedger
from .ledger_model import LedgerError, make_record
from .ledger_store import LedgerStore
from .network_deny import NetworkPolicy
from .operational_lock import LockHeld, acquire_lock, classify_lock, lock_is_stale, run_lock_file
from .preconditions import PrivateRoots, credential_present
from .process_probe import ProcessProbe
from .run_executor import execute_run
from .run_state import RunState, is_terminal
from .status_store import write_status

STAGES: Tuple[str, ...] = ("LEDGER_VERIFIED", "LOCK_ACQUIRED", "REQUEST_RECORDED", "PLANNED_RECORDED", "RUNNING_RECORDED", "EXECUTED",
                           "TERMINAL_RECORDED", "LEDGER_REVERIFIED", "STATUS_PROJECTED", "LOCK_RELEASED")
TRANSACTION_SCHEMA_VERSION = "p12_run_transaction:0.2.0"
REQUESTS_DIRECTORY = "requests"
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


def request_file(p12_root: Any, run_id: str):
    return run_directory(p12_root, run_id).parent.parent / REQUESTS_DIRECTORY / f"{run_id}.json"


def preflight(ledger: LockedLedger, request: AutomationExecutionRequest, roots: PrivateRoots, environment: Mapping[str, str],
               probe: ProcessProbe) -> Any:
    if credential_present(environment):
        raise AutomationError("CREDENTIAL_PRESENT")                                     # orchestration の前に
    state = ledger.read_verified(request.run_id)                                        # ledger lock の中で読む（他 process の commit の途中を見ない）
    final = run_directory(roots.p12_root, request.run_id)
    if final.with_name(final.name + PARTIAL_SUFFIX).exists():
        raise AutomationError("DUPLICATE_INVOCATION", "PARTIAL_EXISTS")                 # 回復（recover-partial）に予約
    run_state = state.run_states.get(request.run_id)
    if run_state is RunState.SUCCEEDED:
        raise AutomationError("ALREADY_SUCCEEDED")
    if final.exists():
        raise AutomationError("ORPHANED_FINALIZATION")                                  # final が在って成功の record が無い: 上書きしない
    if run_state is not None:
        if is_terminal(run_state):
            raise AutomationError("DUPLICATE_INVOCATION", "RUN_TERMINAL")
        lock_class = classify_lock(run_lock_file(roots.p12_root, request.run_id), probe=probe, ledger_state=state)["lock_class"]
        raise AutomationError("DUPLICATE_INVOCATION", "RUN_ACTIVE" if lock_class == "LOCK_LIVE" else "RUN_OPEN")
    return state


def record_request(p12_root: Any, request: AutomationExecutionRequest) -> None:
    target = request_file(p12_root, request.run_id)
    existing = read_text_file(target)
    expected = request.to_bytes().decode("utf-8")
    if existing is not None:
        if existing != expected:
            raise AutomationError("DUPLICATE_INVOCATION", "REQUEST_MISMATCH")           # 同じ run_id に違う要求
        return
    ensure_root_subdirectory(p12_root, REQUESTS_DIRECTORY)
    replace_atomically(target, request.to_bytes())


def read_recorded_request(p12_root: Any, run_id: str) -> Optional[AutomationExecutionRequest]:
    import json
    text = read_text_file(request_file(p12_root, run_id))
    if text is None:
        return None
    try:
        return AutomationExecutionRequest.from_dict(json.loads(text))
    except ValueError:
        raise AutomationError("SCHEMA_INVALID", "REQUEST_EVIDENCE_MALFORMED") from None


def commit_run(request: AutomationExecutionRequest, roots: PrivateRoots, *, repo_root: Any, runtime_root: Any,
               environment: Mapping[str, str], clock: Clock, policy: Optional[NetworkPolicy] = None,
               probe: Optional[ProcessProbe] = None, injection: InjectionPoints = NO_INJECTION) -> TransactionResult:
    """1 run の運用の transaction。想定内の失敗は code（lock は解放）。想定外の例外は process の死と同じ（lock は残る ・証拠で回復）。"""
    if not isinstance(request, AutomationExecutionRequest) or not isinstance(roots, PrivateRoots):
        raise AutomationError("SCHEMA_INVALID", "TRANSACTION_INPUT")
    if not callable(clock):
        raise AutomationError("SCHEMA_INVALID", "CLOCK_REQUIRED")                      # telemetry の時計も暗黙には読まない
    probe = ProcessProbe() if probe is None else probe
    ledger = LockedLedger(roots.p12_root, probe=probe, clock=clock, injection=injection)
    store = ledger.store
    run = request.run
    stages: list = []

    def failed(code: str, execution: Optional[AutomationExecutionResult] = None, state: Any = None,
               status_written: bool = False) -> TransactionResult:
        return TransactionResult(run_id=request.run_id, status="FAILED", failure_code=code, stages_completed=tuple(stages),
                                 ledger_record_count=None if state is None else state.summary.record_count,
                                 ledger_head_digest=None if state is None else state.summary.head_digest, execution=execution,
                                 status_projection_written=status_written)

    try:
        state = preflight(ledger, request, roots, environment, probe)
    except AutomationError as exc:
        return failed(exc.public_code)
    stages.append("LEDGER_VERIFIED")
    try:
        held = acquire_lock(roots.p12_root, "RUN", request.run_id, probe=probe, clock_instant=clock(),
                            scheduled_for=utc_iso(request.scheduled_for), attempt=request.attempt)
    except LockHeld:
        classification = classify_lock(run_lock_file(roots.p12_root, request.run_id), probe=probe, ledger_state=state)
        if classification["lock_class"] == "LOCK_LIVE":
            return failed("DUPLICATE_INVOCATION:RUN_ACTIVE", state=state)
        if lock_is_stale(classification):
            return failed("DUPLICATE_INVOCATION:LOCK_STALE", state=state)             # 人の手の release-lock
        return failed(f"DUPLICATE_INVOCATION:{classification['lock_class']}", state=state)
    except AutomationError as exc:
        return failed(exc.public_code, state=state)
    stages.append("LOCK_ACQUIRED")
    injection.fire("AFTER_LOCK_ACQUIRED")

    def finish(result: TransactionResult) -> TransactionResult:
        injection.fire("BEFORE_LOCK_RELEASE")
        held.release()
        stages.append("LOCK_RELEASED")
        return TransactionResult(**{**result.__dict__, "stages_completed": tuple(stages)})

    def project(state: Any, execution: Optional[AutomationExecutionResult]) -> Optional[str]:
        injection.fire("BEFORE_STATUS_WRITE")
        try:
            write_status(roots.p12_root, state, runtime_anchor=request.runtime_anchor, schedule_id=request.schedule_id, as_of=clock())
        except AutomationError as exc:
            return exc.public_code
        stages.append("STATUS_PROJECTED")
        injection.fire("AFTER_STATUS_WRITE")
        return None

    def transition(to_state: RunState, from_state: Optional[RunState], *, point: Optional[str] = None, **extra: Any) -> Any:
        def builder(head: Any, _state: Any) -> Any:
            return make_record(head, run, transition_from=from_state, transition_to=to_state, recorded_at=utc_iso(clock()), **extra)
        return ledger.commit(request.run_id, builder, after_append_point=point)

    def cancelled(from_state: RunState) -> TransactionResult:
        state = transition(RunState.CANCELLED, from_state, failure_code="CANCELLED")
        stages.append("TERMINAL_RECORDED")
        code = project(state, None)
        return finish(failed("CANCELLED" if code is None else code, state=state, status_written=code is None))

    try:
        record_request(roots.p12_root, request)
        stages.append("REQUEST_RECORDED")
        state = transition(RunState.PLANNED, None)
        stages.append("PLANNED_RECORDED")
        injection.fire("AFTER_PLANNED_APPEND")
        if cancel_requested(roots.p12_root, request.run_id) is not None:
            return cancelled(RunState.PLANNED)
        state = transition(RunState.RUNNING, RunState.PLANNED)
        stages.append("RUNNING_RECORDED")
        injection.fire("AFTER_RUNNING_APPEND")
        if cancel_requested(roots.p12_root, request.run_id) is not None:
            return cancelled(RunState.RUNNING)
    except AutomationError as exc:
        return finish(failed(exc.public_code, state=state))
    injection.fire("BEFORE_EXECUTION")
    execution = execute_run(request, roots, repo_root=repo_root, runtime_root=runtime_root, environment=environment,
                            policy=policy, clock=clock)
    stages.append("EXECUTED")
    injection.fire("AFTER_FINALIZATION")
    succeeded = execution.status == FINALIZED_PENDING_LEDGER
    try:
        state = transition(RunState.SUCCEEDED if succeeded else RunState.FAILED, RunState.RUNNING, point="AFTER_TERMINAL_APPEND",
                           failure_code=None if succeeded else execution.failure_code, step_results=execution.step_results,
                           artifact_digests=execution.artifact_digests)
        stages.append("TERMINAL_RECORDED")
        reverified = store.open_verified()                                              # file から読み直す
        expected = RunState.SUCCEEDED if succeeded else RunState.FAILED
        if reverified.run_states.get(request.run_id) is not expected or reverified.last_record_of(request.run_id).transition_to is not expected:
            raise LedgerError("REVERIFY_MISMATCH")
        state = reverified
        stages.append("LEDGER_REVERIFIED")
    except AutomationError as exc:
        return finish(failed(exc.public_code, execution, state))
    code = project(state, execution)
    if code is not None:
        return finish(failed(code, execution, state))
    return finish(TransactionResult(run_id=request.run_id, status="SUCCEEDED" if succeeded else "FAILED",
                                    failure_code=None if succeeded else execution.failure_code, stages_completed=tuple(stages),
                                    ledger_record_count=state.summary.record_count, ledger_head_digest=state.summary.head_digest,
                                    execution=execution, status_projection_written=True))


def classify_after_crash(roots: PrivateRoots, run_id: str, *, probe: Optional[ProcessProbe] = None) -> Dict[str, Any]:
    """crash の後の証拠の分類（読むだけ）。ledger 自体が不正なら `LEDGER_INVALID:*` を返す。lock の分類も添える。"""
    store = LedgerStore(roots.p12_root)
    probe = ProcessProbe() if probe is None else probe
    try:
        state = store.open_verified(allow_stale_checkpoint=True)
    except AutomationError as exc:
        return {"run_id": run_id, "classification": exc.public_code, "lock_class": classify_lock(
            run_lock_file(roots.p12_root, run_id), probe=probe)["lock_class"]}
    evidence = classify_run(roots.p12_root, run_id, state).to_dict()
    evidence["lock_class"] = classify_lock(run_lock_file(roots.p12_root, run_id), probe=probe, ledger_state=state)["lock_class"]
    return evidence


__all__ = ["REQUESTS_DIRECTORY", "STAGES", "TRANSACTION_SCHEMA_VERSION", "TransactionResult", "classify_after_crash", "commit_run",
           "preflight", "read_recorded_request", "record_request", "request_file"]
