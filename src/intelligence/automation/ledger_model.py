"""P12-A1 — 追記専用の hash 鎖の ledger の正準な record と鎖の検証（live の書き手は後の gate）。

- record は run の遷移 1 つ（transition_from → transition_to）。欄: record_version ・sequence ・previous_record_digest ・run の
  metadata（run_id ・identity ・operator）・transition ・status（＝ transition_to）・failure_code ・step_results ・artifact_digests ・
  recorded_at（telemetry: identity には入らないが record の内容には入る）。
- `record_digest = sha256("p12.ledger_record.v1" + "\\0" + canonical_json(record without record_digest))`。
- 鎖: sequence は 0 から連続 ・previous_record_digest は前の record の digest（最初は GENESIS）・digest は再計算と一致 ・
  run ごとの遷移は状態機械に合う ・終端の後に record は無い。削除 ・挿入 ・並べ替え ・改変は検出する。
- **保証と非保証**: 鎖は改変の検出（tamper-evidence）と一貫性だけを与える。file 全体を書き換えられる攻撃者に対する真正性 ・
  認証（署名 ・鍵）は無い。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .canonical import canonical_json, domain_digest, is_digest, parse_utc_iso, require_fields, utc_iso
from .failure_codes import AutomationError, is_safe_code
from .run_identity import AutomationRun
from .run_planning import OPERATORS
from .run_state import INITIAL_STATE, RunState, is_terminal, parse_state, transition
from .step_result import AutomationStepResult, validate_step_results

LEDGER_RECORD_VERSION = "p12_ledger_record:0.1.0"
LEDGER_DIGEST_DOMAIN = "p12.ledger_record.v1"
GENESIS_DIGEST = "0" * 64
_RECORD_FIELDS = frozenset({"record_version", "sequence", "previous_record_digest", "record_digest", "run_id",
                            "schedule_id", "slot_id", "scheduled_for", "runtime_anchor", "attempt", "operator",
                            "transition_from", "transition_to", "status", "failure_code", "step_results",
                            "artifact_digests", "recorded_at"})


class LedgerError(AutomationError):
    def __init__(self, detail: str, sequence: Optional[int] = None) -> None:
        super().__init__("LEDGER_INVALID", detail)
        self.sequence = sequence


@dataclass(frozen=True)
class LedgerRecord:
    sequence: int
    previous_record_digest: str
    run_id: str
    schedule_id: str
    slot_id: str
    scheduled_for: str                             # UTC ISO
    runtime_anchor: str
    attempt: int
    operator: str
    transition_from: Optional[RunState]
    transition_to: RunState
    failure_code: Optional[str]
    step_results: Tuple[AutomationStepResult, ...]
    artifact_digests: Tuple[str, ...]
    recorded_at: str                               # telemetry（UTC ISO）。identity には影響しない
    record_version: str = LEDGER_RECORD_VERSION

    def __post_init__(self) -> None:
        if self.record_version != LEDGER_RECORD_VERSION:
            raise AutomationError("SCHEMA_INVALID", "RECORD_VERSION")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise AutomationError("SCHEMA_INVALID", "RECORD_SEQUENCE")
        if not is_digest(self.previous_record_digest) or not is_digest(self.run_id):
            raise AutomationError("SCHEMA_INVALID", "RECORD_DIGESTS")
        if utc_iso(parse_utc_iso(self.scheduled_for)) != self.scheduled_for:
            raise AutomationError("SCHEMA_INVALID", "RECORD_SCHEDULED_FOR")
        if utc_iso(parse_utc_iso(self.recorded_at)) != self.recorded_at:
            raise AutomationError("SCHEMA_INVALID", "RECORD_RECORDED_AT")
        if len(self.runtime_anchor) != 40 or any(c not in "0123456789abcdef" for c in self.runtime_anchor):
            raise AutomationError("SCHEMA_INVALID", "RECORD_ANCHOR")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise AutomationError("SCHEMA_INVALID", "RECORD_ATTEMPT")
        if self.operator not in OPERATORS:
            raise AutomationError("SCHEMA_INVALID", "RECORD_OPERATOR")
        if self.transition_from is not None and not isinstance(self.transition_from, RunState):
            raise AutomationError("SCHEMA_INVALID", "RECORD_TRANSITION_FROM")
        if not isinstance(self.transition_to, RunState):
            raise AutomationError("SCHEMA_INVALID", "RECORD_TRANSITION_TO")
        if self.transition_from is None and self.transition_to is not INITIAL_STATE:
            raise AutomationError("SCHEMA_INVALID", "RECORD_FIRST_NOT_PLANNED")
        if self.transition_from is not None:
            transition(self.transition_from, self.transition_to)                       # 不正なら IllegalTransition
        if self.failure_code is not None and not is_safe_code(self.failure_code):
            raise AutomationError("SCHEMA_INVALID", "RECORD_FAILURE_CODE")
        if self.transition_to in (RunState.FAILED, RunState.SKIPPED, RunState.CRASHED, RunState.ORPHANED_FINALIZATION,
                                  RunState.CANCELLED) and self.failure_code is None:
            raise AutomationError("SCHEMA_INVALID", "RECORD_TERMINAL_WITHOUT_CODE")
        if self.transition_to in (RunState.PLANNED, RunState.RUNNING, RunState.SUCCEEDED) and self.failure_code is not None:
            raise AutomationError("SCHEMA_INVALID", "RECORD_CODE_WITHOUT_FAILURE")
        validate_step_results(self.step_results)
        if not isinstance(self.artifact_digests, tuple) or list(self.artifact_digests) != sorted(set(self.artifact_digests)) \
                or not all(is_digest(d) for d in self.artifact_digests):
            raise AutomationError("SCHEMA_INVALID", "RECORD_ARTIFACTS")

    @property
    def status(self) -> RunState:
        return self.transition_to

    def content(self) -> Dict[str, Any]:
        return {"record_version": self.record_version, "sequence": self.sequence,
                "previous_record_digest": self.previous_record_digest, "run_id": self.run_id,
                "schedule_id": self.schedule_id, "slot_id": self.slot_id, "scheduled_for": self.scheduled_for,
                "runtime_anchor": self.runtime_anchor, "attempt": self.attempt, "operator": self.operator,
                "transition_from": None if self.transition_from is None else self.transition_from.value,
                "transition_to": self.transition_to.value, "status": self.transition_to.value,
                "failure_code": self.failure_code, "step_results": [s.to_dict() for s in self.step_results],
                "artifact_digests": list(self.artifact_digests), "recorded_at": self.recorded_at}

    @property
    def record_digest(self) -> str:
        return domain_digest(LEDGER_DIGEST_DOMAIN, self.content())

    def to_dict(self) -> Dict[str, Any]:
        return {**self.content(), "record_digest": self.record_digest}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "LedgerRecord":
        fields = require_fields(data, _RECORD_FIELDS, "RECORD")
        if not isinstance(fields["step_results"], list) or not isinstance(fields["artifact_digests"], list):
            raise AutomationError("SCHEMA_INVALID", "RECORD_LISTS")
        if fields["status"] != fields["transition_to"]:
            raise AutomationError("SCHEMA_INVALID", "RECORD_STATUS_MISMATCH")
        record = cls(sequence=fields["sequence"], previous_record_digest=fields["previous_record_digest"],
                     run_id=fields["run_id"], schedule_id=fields["schedule_id"], slot_id=fields["slot_id"],
                     scheduled_for=fields["scheduled_for"], runtime_anchor=fields["runtime_anchor"],
                     attempt=fields["attempt"], operator=fields["operator"],
                     transition_from=None if fields["transition_from"] is None else parse_state(fields["transition_from"]),
                     transition_to=parse_state(fields["transition_to"]), failure_code=fields["failure_code"],
                     step_results=tuple(AutomationStepResult.from_dict(s) for s in fields["step_results"]),
                     artifact_digests=tuple(fields["artifact_digests"]), recorded_at=fields["recorded_at"],
                     record_version=fields["record_version"])
        if fields["record_digest"] != record.record_digest:
            raise LedgerError("RECORD_DIGEST_MISMATCH", record.sequence)
        return record


def make_record(previous: Optional[LedgerRecord], run: AutomationRun, *, transition_to: RunState, recorded_at: str,
                transition_from: Optional[RunState] = None, failure_code: Optional[str] = None,
                step_results: Sequence[AutomationStepResult] = (), artifact_digests: Sequence[str] = ()) -> LedgerRecord:
    """前の record に続く record を組む（live の追記は後の gate。ここは純粋な構成だけ）。"""
    if not isinstance(run, AutomationRun):
        raise AutomationError("SCHEMA_INVALID", "RUN_TYPE")
    sequence = 0 if previous is None else previous.sequence + 1
    previous_digest = GENESIS_DIGEST if previous is None else previous.record_digest
    return LedgerRecord(sequence=sequence, previous_record_digest=previous_digest, run_id=run.run_id,
                        schedule_id=run.identity.schedule_id, slot_id=run.identity.slot_id,
                        scheduled_for=utc_iso(run.identity.scheduled_for), runtime_anchor=run.identity.runtime_anchor,
                        attempt=run.identity.attempt, operator=run.operator, transition_from=transition_from,
                        transition_to=transition_to, failure_code=failure_code, step_results=tuple(step_results),
                        artifact_digests=tuple(sorted(set(artifact_digests))), recorded_at=recorded_at)


@dataclass(frozen=True)
class ChainSummary:
    record_count: int
    head_digest: str
    run_states: Mapping[str, RunState]            # run_id → 最後の状態


def verify_chain(records: Sequence[LedgerRecord]) -> ChainSummary:
    """鎖の検証。削除（sequence の飛び）・挿入（鎖の切れ）・並べ替え ・改変（digest）・不正な遷移を `LedgerError` で止める。"""
    expected_previous = GENESIS_DIGEST
    states: Dict[str, RunState] = {}
    for index, record in enumerate(records):
        if not isinstance(record, LedgerRecord):
            raise LedgerError("RECORD_TYPE", index)
        if record.sequence != index:
            raise LedgerError("SEQUENCE_BREAK", index)
        if record.previous_record_digest != expected_previous:
            raise LedgerError("CHAIN_BREAK", index)
        previous_state = states.get(record.run_id)
        if previous_state is None:
            if record.transition_from is not None:
                raise LedgerError("RUN_NOT_OPENED", index)
        else:
            if is_terminal(previous_state):
                raise LedgerError("RUN_AFTER_TERMINAL", index)
            if record.transition_from is not previous_state:
                raise LedgerError("TRANSITION_FROM_MISMATCH", index)
        states[record.run_id] = record.transition_to
        expected_previous = record.record_digest
    return ChainSummary(record_count=len(records), head_digest=expected_previous, run_states=dict(states))


def parse_records(lines: Sequence[str]) -> Tuple[LedgerRecord, ...]:
    """正準 JSON の行 → record（行ごとに正準の形を要求し、digest を照合する）。"""
    records = []
    for index, line in enumerate(lines):
        try:
            data = json.loads(line)
        except ValueError:
            raise LedgerError("RECORD_NOT_JSON", index) from None
        record = LedgerRecord.from_dict(data)
        if record.to_json() != line:
            raise LedgerError("RECORD_NOT_CANONICAL", index)
        records.append(record)
    return tuple(records)


__all__ = ["ChainSummary", "GENESIS_DIGEST", "LEDGER_DIGEST_DOMAIN", "LEDGER_RECORD_VERSION", "LedgerError",
           "LedgerRecord", "make_record", "parse_records", "verify_chain"]
