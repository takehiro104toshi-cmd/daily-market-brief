"""P12-A1 — 不変 ・順序付きの AutomationStepResult。

- step の順は `STEP_ORDER`（v1 の正準の順）。結果の列は STEP_ORDER の部分列（重複なし ・順の逆転なし）。
- 欄は step_code ・status ・artifact_digest ・completeness_code ・failure_code だけ。自由な payload ・path ・private な値は無い。
- OK は failure_code を持たない ・FAILED は持つ ・FAILED の後の step は SKIPPED か無し。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from .canonical import is_digest, require_fields
from .failure_codes import AutomationError, is_safe_code

STEP_ORDER: Tuple[str, ...] = ("PRECONDITIONS", "ROOT_MANIFESTS", "P11_MODEL_SNAPSHOT", "SERVER_READINESS", "FINALIZATION")
STEP_STATUSES: Tuple[str, ...] = ("OK", "FAILED", "SKIPPED")
COMPLETENESS_CODES: Tuple[str, ...] = ("COMPLETE", "PARTIAL", "NONE")
_STEP_FIELDS = frozenset({"step_code", "status", "artifact_digest", "completeness_code", "failure_code"})


@dataclass(frozen=True)
class AutomationStepResult:
    step_code: str
    status: str
    artifact_digest: Optional[str]
    completeness_code: str
    failure_code: Optional[str]

    def __post_init__(self) -> None:
        if self.step_code not in STEP_ORDER:
            raise AutomationError("SCHEMA_INVALID", "STEP_CODE")
        if self.status not in STEP_STATUSES:
            raise AutomationError("SCHEMA_INVALID", "STEP_STATUS")
        if self.artifact_digest is not None and not is_digest(self.artifact_digest):
            raise AutomationError("SCHEMA_INVALID", "STEP_ARTIFACT_DIGEST")
        if self.completeness_code not in COMPLETENESS_CODES:
            raise AutomationError("SCHEMA_INVALID", "STEP_COMPLETENESS")
        if self.failure_code is not None and not is_safe_code(self.failure_code):
            raise AutomationError("SCHEMA_INVALID", "STEP_FAILURE_CODE")
        if self.status == "OK" and self.failure_code is not None:
            raise AutomationError("SCHEMA_INVALID", "STEP_OK_WITH_FAILURE")
        if self.status == "FAILED" and self.failure_code is None:
            raise AutomationError("SCHEMA_INVALID", "STEP_FAILED_WITHOUT_CODE")
        if self.status != "OK" and self.artifact_digest is not None:
            raise AutomationError("SCHEMA_INVALID", "STEP_ARTIFACT_WITHOUT_OK")
        if self.status == "SKIPPED" and self.completeness_code != "NONE":
            raise AutomationError("SCHEMA_INVALID", "STEP_SKIPPED_COMPLETENESS")

    def to_dict(self) -> Dict[str, Any]:
        return {"step_code": self.step_code, "status": self.status, "artifact_digest": self.artifact_digest,
                "completeness_code": self.completeness_code, "failure_code": self.failure_code}

    @classmethod
    def from_dict(cls, data: Any) -> "AutomationStepResult":
        fields = require_fields(data, _STEP_FIELDS, "STEP")
        return cls(**fields)


def validate_step_results(results: Sequence[AutomationStepResult]) -> Tuple[AutomationStepResult, ...]:
    """STEP_ORDER の部分列であること ・FAILED の後は SKIPPED だけであることを確かめ、tuple で返す。"""
    ordered = tuple(results)
    if not all(isinstance(r, AutomationStepResult) for r in ordered):
        raise AutomationError("SCHEMA_INVALID", "STEP_TYPE")
    indexes = [STEP_ORDER.index(r.step_code) for r in ordered]
    if indexes != sorted(indexes) or len(set(indexes)) != len(indexes):
        raise AutomationError("SCHEMA_INVALID", "STEP_ORDER")
    failed = False
    for result in ordered:
        if failed and result.status != "SKIPPED":
            raise AutomationError("SCHEMA_INVALID", "STEP_AFTER_FAILURE")
        if result.status == "FAILED":
            failed = True
    return ordered


__all__ = ["COMPLETENESS_CODES", "STEP_ORDER", "STEP_STATUSES", "AutomationStepResult", "validate_step_results"]
