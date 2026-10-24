"""P12-A2 — 完全に明示の実行の要求（時計を読まない ・PIT の欄は全て caller が渡す）。

- 意味の欄: schedule_id ・slot_id ・scheduled_for（aware）・as_of_date ・session_date ・runtime_anchor ・attempt ・operator ・
  schedule_digest（planner が使った schedule の content_digest）。任意の系譜: retry_of ・supersedes（metadata。identity ではない）。
- 内部の一貫性: as_of_date ＝ scheduled_for の Asia/Tokyo の暦日 ・session_date ≤ as_of_date ・attempt ≥ 1 ・retry_of は attempt ≥ 2。
- `run` ＝ A1 の `AutomationRun`（run_id は A1 の RunIdentity で再計算する。ここで別の identity は作らない）。
- 正準 JSON（`to_dict` ・`to_json`）・`request_digest`（domain 付き）。path ・時計 ・private な値は無い。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional

from .canonical import (canonical_json, date_iso, domain_digest, is_digest, is_git_anchor, parse_date_iso, parse_utc_iso,
                        require_aware, require_fields, utc_iso)
from .failure_codes import AutomationError
from .run_identity import AutomationRun, RunIdentity
from .run_planning import MAX_ATTEMPT, OPERATORS
from .schedule_model import TIMEZONE_V1, TOKYO, _require_id

REQUEST_SCHEMA_VERSION = "p12_execution_request:0.1.0"
REQUEST_DIGEST_DOMAIN = "p12.execution_request.v1"
_REQUEST_FIELDS = frozenset({"schema_version", "schedule_id", "slot_id", "scheduled_for", "as_of_date", "session_date",
                             "runtime_anchor", "attempt", "operator", "schedule_digest", "retry_of", "supersedes",
                             "readiness_only", "request_digest"})


@dataclass(frozen=True)
class AutomationExecutionRequest:
    schedule_id: str
    slot_id: str
    scheduled_for: datetime
    as_of_date: date
    session_date: date
    runtime_anchor: str
    attempt: int
    operator: str
    schedule_digest: str
    retry_of: Optional[str] = None
    supersedes: Optional[str] = None
    readiness_only: bool = False
    schema_version: str = REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REQUEST_SCHEMA_VERSION:
            raise AutomationError("SCHEMA_INVALID", "REQUEST_SCHEMA_VERSION")
        _require_id(self.schedule_id, "SCHEDULE")
        _require_id(self.slot_id, "SLOT")
        require_aware(self.scheduled_for, "SCHEMA_INVALID")
        if self.scheduled_for.microsecond != 0:
            raise AutomationError("SCHEMA_INVALID", "SUBSECOND_INSTANT")
        if type(self.as_of_date) is not date or type(self.session_date) is not date:
            raise AutomationError("SCHEMA_INVALID", "REQUEST_DATE_TYPE")
        if self.scheduled_for.astimezone(TOKYO).date() != self.as_of_date:
            raise AutomationError("SCHEMA_INVALID", "AS_OF_DATE_MISMATCH")                 # PIT の欄の内部の一貫性
        if self.session_date > self.as_of_date:
            raise AutomationError("SCHEMA_INVALID", "SESSION_AFTER_AS_OF")
        if not is_git_anchor(self.runtime_anchor):
            raise AutomationError("SCHEMA_INVALID", "RUNTIME_ANCHOR")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or not 1 <= self.attempt <= MAX_ATTEMPT:
            raise AutomationError("SCHEMA_INVALID", "ATTEMPT_RANGE")
        if self.operator not in OPERATORS:
            raise AutomationError("SCHEMA_INVALID", "OPERATOR")
        if not is_digest(self.schedule_digest):
            raise AutomationError("SCHEMA_INVALID", "SCHEDULE_DIGEST")
        if not isinstance(self.readiness_only, bool):
            raise AutomationError("SCHEMA_INVALID", "READINESS_ONLY")
        self.run                                                                            # 系譜 ・自己参照 ・retry の検査は A1 の model

    @property
    def identity(self) -> RunIdentity:
        return RunIdentity(schedule_id=self.schedule_id, slot_id=self.slot_id, scheduled_for=self.scheduled_for,
                           runtime_anchor=self.runtime_anchor, attempt=self.attempt)

    @property
    def run(self) -> AutomationRun:
        return AutomationRun(identity=self.identity, schedule_digest=self.schedule_digest, as_of_date=self.as_of_date,
                             session_date=self.session_date, timezone=TIMEZONE_V1, operator=self.operator,
                             readiness_only=self.readiness_only, retry_of=self.retry_of, supersedes=self.supersedes)

    @property
    def run_id(self) -> str:
        return self.identity.run_id

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "schedule_id": self.schedule_id, "slot_id": self.slot_id,
                "scheduled_for": utc_iso(self.scheduled_for), "as_of_date": date_iso(self.as_of_date),
                "session_date": date_iso(self.session_date), "runtime_anchor": self.runtime_anchor, "attempt": self.attempt,
                "operator": self.operator, "schedule_digest": self.schedule_digest, "retry_of": self.retry_of,
                "supersedes": self.supersedes, "readiness_only": self.readiness_only}

    @property
    def request_digest(self) -> str:
        return domain_digest(REQUEST_DIGEST_DOMAIN, self.content())

    def to_dict(self) -> Dict[str, Any]:
        return {**self.content(), "request_digest": self.request_digest}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_bytes(self) -> bytes:
        return (self.to_json() + "\n").encode("utf-8")

    @classmethod
    def from_dict(cls, data: Any) -> "AutomationExecutionRequest":
        fields = require_fields(data, _REQUEST_FIELDS, "REQUEST")
        request = cls(schedule_id=fields["schedule_id"], slot_id=fields["slot_id"],
                      scheduled_for=parse_utc_iso(fields["scheduled_for"]).astimezone(TOKYO),
                      as_of_date=parse_date_iso(fields["as_of_date"]), session_date=parse_date_iso(fields["session_date"]),
                      runtime_anchor=fields["runtime_anchor"], attempt=fields["attempt"], operator=fields["operator"],
                      schedule_digest=fields["schedule_digest"], retry_of=fields["retry_of"], supersedes=fields["supersedes"],
                      readiness_only=fields["readiness_only"], schema_version=fields["schema_version"])
        if fields["request_digest"] != request.request_digest:
            raise AutomationError("SCHEMA_INVALID", "REQUEST_DIGEST_MISMATCH")
        return request


__all__ = ["REQUEST_DIGEST_DOMAIN", "REQUEST_SCHEMA_VERSION", "AutomationExecutionRequest"]
