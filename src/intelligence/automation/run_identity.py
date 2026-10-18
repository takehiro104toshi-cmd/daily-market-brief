"""P12-A1 — AutomationRun の不変の identity。

- 意味の identity の入力は schedule_id ・slot_id ・scheduled_for（UTC に正規化）・runtime_anchor ・attempt だけ。
  `run_id = sha256("p12.automation_run.v1" + "\\0" + canonical_json(identity))`（domain を分けた digest ・独立に再計算できる）。
- 含めない: started_at ・completed_at ・selection_clock_at ・可変の status ・成果物の path。
- `retry_of` ・`supersedes` は **metadata**（identity の内容ではない）: retry_of は同じ scheduled_for の前の attempt から導けるし、
  supersedes は人の backfill の結び付きで、どちらも「何が ・どの code で ・何回目に」予定されたかを変えない。identity に入れると
  別の operator が同じ予定を独立に再計算した時に run_id が食い違う。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional

from .canonical import date_iso, domain_digest, is_digest, is_git_anchor, require_aware, utc_iso
from .failure_codes import AutomationError
from .run_planning import MAX_ATTEMPT, OPERATORS, PlannedRun
from .schedule_model import TIMEZONE_V1, _require_id

RUN_ID_DOMAIN = "p12.automation_run.v1"
RUN_SCHEMA_VERSION = "p12_automation_run:0.1.0"


@dataclass(frozen=True)
class RunIdentity:
    schedule_id: str
    slot_id: str
    scheduled_for: datetime
    runtime_anchor: str
    attempt: int

    def __post_init__(self) -> None:
        _require_id(self.schedule_id, "SCHEDULE")
        _require_id(self.slot_id, "SLOT")
        require_aware(self.scheduled_for, "SCHEMA_INVALID")
        if not is_git_anchor(self.runtime_anchor):
            raise AutomationError("SCHEMA_INVALID", "RUNTIME_ANCHOR")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or not 1 <= self.attempt <= MAX_ATTEMPT:
            raise AutomationError("SCHEMA_INVALID", "ATTEMPT_RANGE")

    def content(self) -> Dict[str, Any]:
        return {"schedule_id": self.schedule_id, "slot_id": self.slot_id, "scheduled_for": utc_iso(self.scheduled_for),
                "runtime_anchor": self.runtime_anchor, "attempt": self.attempt}

    @property
    def run_id(self) -> str:
        return domain_digest(RUN_ID_DOMAIN, self.content())


def run_id_for(identity: RunIdentity) -> str:
    return identity.run_id


@dataclass(frozen=True)
class AutomationRun:
    """予定された run の不変の記述（identity ＋ metadata）。status は ledger の record が持つ（ここは可変の state を持たない）。"""

    identity: RunIdentity
    schedule_digest: str
    as_of_date: date
    session_date: date
    timezone: str
    operator: str
    readiness_only: bool
    retry_of: Optional[str] = None                 # 前の attempt の run_id（metadata）
    supersedes: Optional[str] = None               # 人の backfill が置き換える run の run_id（metadata）
    schema_version: str = RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_SCHEMA_VERSION:
            raise AutomationError("SCHEMA_INVALID", "RUN_SCHEMA_VERSION")
        if not isinstance(self.identity, RunIdentity):
            raise AutomationError("SCHEMA_INVALID", "IDENTITY_TYPE")
        if not is_digest(self.schedule_digest):
            raise AutomationError("SCHEMA_INVALID", "SCHEDULE_DIGEST")
        if self.timezone != TIMEZONE_V1 or self.operator not in OPERATORS or not isinstance(self.readiness_only, bool):
            raise AutomationError("SCHEMA_INVALID", "RUN_FIELDS")
        if self.session_date > self.as_of_date:
            raise AutomationError("SCHEMA_INVALID", "SESSION_AFTER_AS_OF")
        for linked in (self.retry_of, self.supersedes):
            if linked is not None and not is_digest(linked):
                raise AutomationError("SCHEMA_INVALID", "LINKED_RUN_ID")
        if self.retry_of is not None and self.identity.attempt < 2:
            raise AutomationError("SCHEMA_INVALID", "RETRY_ATTEMPT")
        if self.retry_of == self.identity.run_id or self.supersedes == self.identity.run_id:
            raise AutomationError("SCHEMA_INVALID", "SELF_LINK")

    @property
    def run_id(self) -> str:
        return self.identity.run_id

    @classmethod
    def from_planned(cls, planned: PlannedRun, runtime_anchor: str, *, retry_of: Optional[str] = None,
                     supersedes: Optional[str] = None) -> "AutomationRun":
        if not isinstance(planned, PlannedRun):
            raise AutomationError("SCHEMA_INVALID", "PLANNED_TYPE")
        identity = RunIdentity(schedule_id=planned.schedule_id, slot_id=planned.slot_id,
                               scheduled_for=planned.scheduled_for, runtime_anchor=runtime_anchor, attempt=planned.attempt)
        return cls(identity=identity, schedule_digest=planned.schedule_digest, as_of_date=planned.as_of_date,
                   session_date=planned.session_date, timezone=planned.timezone, operator=planned.operator,
                   readiness_only=planned.readiness_only, retry_of=retry_of, supersedes=supersedes)

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "run_id": self.run_id, **self.identity.content(),
                "schedule_digest": self.schedule_digest, "as_of_date": date_iso(self.as_of_date),
                "session_date": date_iso(self.session_date), "timezone": self.timezone, "operator": self.operator,
                "readiness_only": self.readiness_only, "retry_of": self.retry_of, "supersedes": self.supersedes}


__all__ = ["RUN_ID_DOMAIN", "RUN_SCHEMA_VERSION", "AutomationRun", "RunIdentity", "run_id_for"]
