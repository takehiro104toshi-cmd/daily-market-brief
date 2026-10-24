"""P12-A2 — 決定論の local orchestrator（A1 の step の順 ・A1 の model ・凍結の P11 の read の面だけ）。

PRECONDITIONS → ROOT_MANIFESTS → P11_MODEL_SNAPSHOT → SERVER_READINESS → FINALIZATION。
- ある step が失敗すれば以後は SKIPPED ・成功の artifact は昇格しない ・安全な失敗 code だけを記録する。
- 各 step は自分の `network_guard` の中で走る（loopback を許すのは SERVER_READINESS の間だけ。入れ子にしない）。
- telemetry の時計（`clock`）は caller が渡す（無ければ None）。identity ・PIT ・artifact の byte ・digest に影響しない。
- artifact（全て UTF-8 ・LF ・正準 JSON ・path 無し）: `request.json` ・`manifests.json`（private: root 相対の名前と digest）・
  `snapshot.json`（P11 の UI model の byte）・`snapshot_metadata.json` ・`readiness.json` ・`evidence.json`（finalize 前の step の結果）。
- 唯一の広い except は、想定外の例外を安全な code（`STEP_FAILED:UNEXPECTED`）に写すため（文は private_detail にも入れない。型の名だけ）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional

from .canonical import canonical_json, date_iso, utc_iso
from .execution_request import AutomationExecutionRequest
from .execution_result import AutomationExecutionResult
from .failure_codes import AutomationError
from .finalization import FINALIZED_PENDING_LEDGER, finalize_run
from .frozen_anchors import P11_FROZEN_ANCHOR, p11_runtime_manifest
from .network_deny import NetworkPolicy, network_guard
from .preconditions import PrivateRoots, check_preconditions
from .server_readiness import verify_server_readiness
from .snapshot_orchestrator import build_snapshot
from .source_manifests import build_root_manifest
from .step_result import STEP_ORDER, AutomationStepResult

EVIDENCE_SCHEMA_VERSION = "p12_run_evidence:0.1.0"
Clock = Callable[[], datetime]


def _json_bytes(content: Mapping[str, Any]) -> bytes:
    return (canonical_json(content) + "\n").encode("utf-8")


def _telemetry(clock: Optional[Clock]) -> Optional[str]:
    if clock is None:
        return None
    try:
        return utc_iso(clock())
    except AutomationError:
        return None


class _Execution:
    def __init__(self, request: AutomationExecutionRequest, roots: PrivateRoots, repo_root: Any, runtime_root: Any,
                 environment: Mapping[str, str], policy: NetworkPolicy) -> None:
        self.request, self.roots, self.repo_root, self.runtime_root = request, roots, repo_root, runtime_root
        self.environment, self.policy = environment, policy
        self.steps: List[AutomationStepResult] = []
        self.preconditions_passed: tuple = ()
        self.manifests: Dict[str, Any] = {}
        self.snapshot = None
        self.readiness = None
        self.finalization_outcome = None

    def _ok(self, step: str, digest: Optional[str] = None, completeness: str = "COMPLETE") -> None:
        self.steps.append(AutomationStepResult(step, "OK", digest, completeness, None))

    def preconditions(self) -> None:
        outcome = check_preconditions(self.request, self.roots, repo_root=self.repo_root, runtime_root=self.runtime_root,
                                      environment=self.environment, policy=self.policy)
        self.preconditions_passed = outcome.passed
        if not outcome.ok:
            raise AutomationError(*outcome.failure_code.split(":", 1))
        self._ok("PRECONDITIONS")

    def root_manifests(self) -> None:
        self.manifests = {"P9": build_root_manifest(self.roots.p9_root, "P9"), "P10": build_root_manifest(self.roots.p10_root, "P10")}
        self.p11_manifest = p11_runtime_manifest()
        self._ok("ROOT_MANIFESTS", self.p11_manifest["content_digest"])

    def p11_model_snapshot(self) -> None:
        self.snapshot = build_snapshot(self.request, self.roots)
        self._ok("P11_MODEL_SNAPSHOT", self.snapshot.model_digest)

    def server_readiness(self) -> None:
        self.readiness = verify_server_readiness(self.roots, self.request, self.snapshot.body)
        self._ok("SERVER_READINESS", self.readiness.api_model_digest)

    def artifacts(self) -> Dict[str, bytes]:
        evidence = {"schema_version": EVIDENCE_SCHEMA_VERSION, "run_id": self.request.run_id,
                    "request_digest": self.request.request_digest, "preconditions_passed": list(self.preconditions_passed),
                    "step_results": [s.to_dict() for s in self.steps],
                    "source_manifest_digests": self.manifest_digests(), "p11_runtime_manifest": self.p11_manifest,
                    "status": FINALIZED_PENDING_LEDGER}
        return {"request.json": self.request.to_bytes(),
                "manifests.json": _json_bytes({k: self.manifests[k].to_private_dict() for k in sorted(self.manifests)}),
                "snapshot.json": self.snapshot.body + b"\n",
                "snapshot_metadata.json": _json_bytes(self.snapshot.to_safe_dict()),
                "readiness.json": _json_bytes(self.readiness.to_dict()),
                "evidence.json": _json_bytes(evidence)}

    def finalization(self) -> None:
        self.finalization_outcome = finalize_run(self.roots.p12_root, self.request.run_id, self.artifacts())
        self._ok("FINALIZATION", None)

    def manifest_digests(self) -> Dict[str, str]:
        digests = {k: self.manifests[k].content_digest for k in sorted(self.manifests)}
        if hasattr(self, "p11_manifest"):
            digests["P11_RUNTIME"] = self.p11_manifest["content_digest"]
        return digests


def execute_run(request: AutomationExecutionRequest, roots: PrivateRoots, *, repo_root: Any, runtime_root: Any,
                environment: Mapping[str, str], policy: Optional[NetworkPolicy] = None,
                clock: Optional[Clock] = None) -> AutomationExecutionResult:
    """明示の要求 ・root ・環境で 5 step を走らせ、安全な結果を返す（例外は投げない。失敗は code）。"""
    if not isinstance(request, AutomationExecutionRequest) or not isinstance(roots, PrivateRoots):
        raise AutomationError("SCHEMA_INVALID", "EXECUTION_INPUT")
    policy = NetworkPolicy(allow_loopback=False) if policy is None else policy
    started_at = _telemetry(clock)
    execution = _Execution(request, roots, repo_root, runtime_root, environment, policy)
    handlers = {"PRECONDITIONS": execution.preconditions, "ROOT_MANIFESTS": execution.root_manifests,
                "P11_MODEL_SNAPSHOT": execution.p11_model_snapshot, "SERVER_READINESS": execution.server_readiness,
                "FINALIZATION": execution.finalization}
    failure_code: Optional[str] = None
    for step in STEP_ORDER:
        if failure_code is not None:
            execution.steps.append(AutomationStepResult(step, "SKIPPED", None, "NONE", None))
            continue
        try:
            with network_guard(NetworkPolicy(allow_loopback=(step == "SERVER_READINESS"))):   # loopback は readiness の間だけ
                handlers[step]()
        except AutomationError as exc:
            failure_code = exc.public_code
        except Exception:  # noqa: BLE001 - 想定外は安全な code に写す（文 ・型は捨てる。private な診断の置き場は後の gate）
            failure_code = "STEP_FAILED:UNEXPECTED"
        if failure_code is not None:
            completeness = "PARTIAL" if step == "PRECONDITIONS" and execution.preconditions_passed else "NONE"
            execution.steps.append(AutomationStepResult(step, "FAILED", None, completeness, failure_code))
    finalized = failure_code is None
    return AutomationExecutionResult(
        run_id=request.run_id, request_digest=request.request_digest, schedule_id=request.schedule_id,
        slot_id=request.slot_id, scheduled_for=utc_iso(request.scheduled_for), as_of_date=date_iso(request.as_of_date),
        session_date=date_iso(request.session_date), runtime_anchor=request.runtime_anchor,
        p11_runtime_anchor=P11_FROZEN_ANCHOR, attempt=request.attempt, operator=request.operator,
        status=FINALIZED_PENDING_LEDGER if finalized else "FAILED", failure_code=failure_code,
        step_results=tuple(execution.steps),
        artifact_digests=execution.finalization_outcome.artifact_digests if finalized else (),
        source_manifest_digests=execution.manifest_digests(),
        snapshot_metadata=None if execution.snapshot is None else execution.snapshot.to_safe_dict(),
        readiness=None if execution.readiness is None else execution.readiness.to_dict(),
        preconditions_passed=execution.preconditions_passed, started_at=started_at, completed_at=_telemetry(clock))


__all__ = ["EVIDENCE_SCHEMA_VERSION", "execute_run"]
