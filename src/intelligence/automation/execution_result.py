"""P12-A2 — 純粋 ・安全な実行の結果（path ・private な名前 ・例外の文 ・本文は無い）。

- `status`: `FINALIZED_PENDING_LEDGER`（全 step OK ・directory は final。**成功ではない**: ledger の record の commit は後の gate）
  か `FAILED`（ある step が失敗 ・以後は SKIPPED ・成功の artifact は昇格しない）。
- 意味の欄（`semantic_dict`）は telemetry（started_at ・completed_at）を含まない。telemetry は identity ・PIT ・出力に影響しない。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from .canonical import canonical_json
from .failure_codes import AutomationError, is_safe_code
from .step_result import AutomationStepResult, validate_step_results

RESULT_SCHEMA_VERSION = "p12_execution_result:0.1.0"
EXECUTION_STATUSES: Tuple[str, ...] = ("FINALIZED_PENDING_LEDGER", "FAILED")


@dataclass(frozen=True)
class AutomationExecutionResult:
    run_id: str
    request_digest: str
    schedule_id: str
    slot_id: str
    scheduled_for: str
    as_of_date: str
    session_date: str
    runtime_anchor: str
    p11_runtime_anchor: str
    attempt: int
    operator: str
    status: str
    failure_code: Optional[str]
    step_results: Tuple[AutomationStepResult, ...]
    artifact_digests: Tuple[str, ...]
    source_manifest_digests: Mapping[str, str]      # source_id → content_digest
    snapshot_metadata: Optional[Mapping[str, Any]]  # AutomationSnapshot.to_safe_dict()（body は無い）
    readiness: Optional[Mapping[str, Any]]
    preconditions_passed: Tuple[str, ...]
    started_at: Optional[str] = None                # telemetry（意味の欄ではない）
    completed_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in EXECUTION_STATUSES:
            raise AutomationError("SCHEMA_INVALID", "RESULT_STATUS")
        if self.failure_code is not None and not is_safe_code(self.failure_code):
            raise AutomationError("SCHEMA_INVALID", "RESULT_FAILURE_CODE")
        if (self.status == "FAILED") != (self.failure_code is not None):
            raise AutomationError("SCHEMA_INVALID", "RESULT_STATUS_CODE")
        validate_step_results(self.step_results)
        if self.status == "FINALIZED_PENDING_LEDGER" and (not self.artifact_digests
                                                          or any(s.status != "OK" for s in self.step_results)):
            raise AutomationError("SCHEMA_INVALID", "RESULT_FINALIZED_SHAPE")
        if self.status == "FAILED" and self.artifact_digests:
            raise AutomationError("SCHEMA_INVALID", "RESULT_FAILED_WITH_ARTIFACTS")

    def semantic_dict(self) -> Dict[str, Any]:
        return {"schema_version": RESULT_SCHEMA_VERSION, "run_id": self.run_id, "request_digest": self.request_digest,
                "schedule_id": self.schedule_id, "slot_id": self.slot_id, "scheduled_for": self.scheduled_for,
                "as_of_date": self.as_of_date, "session_date": self.session_date, "runtime_anchor": self.runtime_anchor,
                "p11_runtime_anchor": self.p11_runtime_anchor, "attempt": self.attempt, "operator": self.operator,
                "status": self.status, "failure_code": self.failure_code,
                "step_results": [s.to_dict() for s in self.step_results], "artifact_digests": list(self.artifact_digests),
                "source_manifest_digests": dict(self.source_manifest_digests),
                "snapshot_metadata": None if self.snapshot_metadata is None else dict(self.snapshot_metadata),
                "readiness": None if self.readiness is None else dict(self.readiness),
                "preconditions_passed": list(self.preconditions_passed)}

    def to_dict(self) -> Dict[str, Any]:
        return {**self.semantic_dict(), "telemetry": {"started_at": self.started_at, "completed_at": self.completed_at}}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


__all__ = ["EXECUTION_STATUSES", "RESULT_SCHEMA_VERSION", "AutomationExecutionResult"]
