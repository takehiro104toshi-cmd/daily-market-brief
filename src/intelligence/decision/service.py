"""Decision service（Phase 3.9.1）— validate（読むだけ）→ decide（唯一の append path）。

依存は注入（store / policy / corpus state resolver / evidence builder / clock）。CLI にも analyzer にも結合しない。
Phase 3.8 / 3.75 のどの自動経路からも呼ばれない（tests で証明）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .corpus_state import CorpusState
from .evidence import EvidenceSnapshot
from .gates import approval_gate_error, formal_review_gate, human_action_error, reason_error
from .models import (
    ACTOR_HUMAN,
    ACTOR_TYPES,
    NOT_PROMOTED,
    SCHEMA_VERSION,
    DecisionRecord,
    decision_id_for,
    validate_record,
)
from .policy import DECISION_STATES, REOPENED_FOR_REVIEW, SUPERSEDED, DecisionPolicy, PolicyError
from .state import CurrentState, allowed_next_states, derive_current_states, transition_allowed
from .store import DecisionStore

E_POLICY_INVALID = "POLICY_INVALID"
E_AUTO_APPROVAL_FORBIDDEN = "AUTO_APPROVAL_FORBIDDEN"
E_PATTERN_ID_MISSING = "PATTERN_ID_MISSING"
E_DECISION_TYPE_UNKNOWN = "DECISION_TYPE_UNKNOWN"
E_ACTOR_MISSING = "ACTOR_MISSING"
E_ACTOR_TYPE_UNKNOWN = "ACTOR_TYPE_UNKNOWN"
E_PATTERN_NOT_IN_REGISTRY = "PATTERN_NOT_IN_REGISTRY"
E_TRANSITION_NOT_ALLOWED = "TRANSITION_NOT_ALLOWED"
E_POLICY_CHANGED_WITHOUT_VERSION_BUMP = "POLICY_CHANGED_WITHOUT_VERSION_BUMP"
E_SCHEMA = "SCHEMA_INVALID"


@dataclass(frozen=True)
class DecisionRequest:
    pattern_id: str
    decision_type: str
    reason: str
    actor: str
    actor_type: str = ACTOR_HUMAN
    notes: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    idempotency_key: str = ""


@dataclass
class ValidationResult:
    ok: bool
    errors: List[Dict[str, str]]
    proposed: Optional[Dict[str, Any]]
    gate: Dict[str, object]
    previous_state: str
    previous_decision_id: str
    allowed_next: List[str]
    duplicate_of_head: str = ""                 # 非空 = head と同一内容（retry）。append 不要

    def as_dict(self) -> Dict[str, object]:
        return {"ok": self.ok, "errors": list(self.errors), "gate": dict(self.gate),
                "previous_state": self.previous_state or "NONE", "previous_decision_id": self.previous_decision_id,
                "allowed_next_states": list(self.allowed_next), "duplicate_of_head": self.duplicate_of_head,
                "proposed": dict(self.proposed) if self.proposed else None}


@dataclass
class DecisionOutcome:
    appended: bool
    decision_id: str
    record: Optional[Dict[str, Any]]
    current_state: Optional[Dict[str, object]]
    validation: ValidationResult
    store_reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"appended": self.appended, "decision_id": self.decision_id, "store_reason": self.store_reason,
                "record": self.record, "current_state": self.current_state, "validation": self.validation.as_dict()}


def _err(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message}


class DecisionService:
    def __init__(self, store: DecisionStore, policy: DecisionPolicy,
                 corpus_state_resolver: Callable[[], CorpusState],
                 evidence_builder: Callable[[str], EvidenceSnapshot],
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self.store = store
        self.policy = policy
        self.corpus_state_resolver = corpus_state_resolver
        self.evidence_builder = evidence_builder
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------- read（non-mutating）
    def gate_status(self) -> Dict[str, object]:
        corpus = self.corpus_state_resolver()
        gate = formal_review_gate(corpus, self.policy)
        return {"gate": gate.as_dict(), "corpus": corpus.as_dict(), "policy": self.policy.as_dict(),
                "policy_digest": self.policy.digest(), "schema_version": SCHEMA_VERSION}

    def current_states(self) -> List[Dict[str, object]]:
        return [s.as_dict() for _, s in sorted(derive_current_states(self.store.records()).items())]

    def current_state(self, pattern_id: str) -> Optional[CurrentState]:
        return derive_current_states(self.store.for_pattern(pattern_id)).get(pattern_id)

    def history(self, pattern_id: str) -> List[Dict[str, Any]]:
        return [r.as_dict() for r in self.store.for_pattern(pattern_id)]

    def get(self, decision_id: str) -> Optional[Dict[str, Any]]:
        r = self.store.get(decision_id)
        return r.as_dict() if r else None

    # ------------------------------------------------------------- validate（読むだけ・書かない）
    def validate(self, request: DecisionRequest) -> ValidationResult:
        errors: List[Dict[str, str]] = []
        try:
            self.policy.validate()
        except PolicyError as exc:
            errors.append(_err(E_POLICY_INVALID, str(exc)))
        if self.policy.auto_approval:
            errors.append(_err(E_AUTO_APPROVAL_FORBIDDEN, "auto approval is not part of Phase 3.9"))
        pid = str(request.pattern_id or "").strip()
        dtype = str(request.decision_type or "")
        if not pid:
            errors.append(_err(E_PATTERN_ID_MISSING, "pattern_id is required"))
        if dtype not in DECISION_STATES:
            errors.append(_err(E_DECISION_TYPE_UNKNOWN, f"decision_type must be one of {list(DECISION_STATES)}"))
        if not str(request.actor or "").strip():
            errors.append(_err(E_ACTOR_MISSING, "actor is required"))
        if request.actor_type not in ACTOR_TYPES:
            errors.append(_err(E_ACTOR_TYPE_UNKNOWN, f"actor_type must be one of {list(ACTOR_TYPES)}"))
        code = human_action_error(dtype, request.actor_type, self.policy)
        if code:
            errors.append(_err(code, f"{dtype} requires an explicit human actor (actor_type=HUMAN)"))
        code = reason_error(dtype, request.reason, self.policy)
        if code:
            errors.append(_err(code, f"{dtype} requires a non-empty reason"))

        corpus = self.corpus_state_resolver()
        gate = formal_review_gate(corpus, self.policy)
        code = approval_gate_error(dtype, gate)
        if code:
            errors.append(_err(code, f"formal APPROVED requires corpus eligible >= {gate.required} (now {gate.corpus_size}); "
                                     "SHADOW MODE"))

        head = self.store.head(pid) if pid else None
        previous_state = head.decision_type if head else ""
        previous_id = head.decision_id if head else ""
        allowed = allowed_next_states(previous_state or None)
        duplicate_of_head = head is not None and self._same_content(head, request, dtype)
        if duplicate_of_head:                     # retry 安全: head と同一内容 → append しない（新情報なし）
            return ValidationResult(ok=True, errors=[], proposed=None, gate=gate.as_dict(),
                                    previous_state=previous_state, previous_decision_id=previous_id,
                                    allowed_next=allowed, duplicate_of_head=head.decision_id)
        if dtype in DECISION_STATES and not transition_allowed(previous_state or None, dtype):
            errors.append(_err(E_TRANSITION_NOT_ALLOWED,
                               f"{previous_state or 'NONE'} -> {dtype} is not allowed; allowed: {allowed}"))
        for r in self.store.records():
            if r.policy_version == self.policy.policy_version and r.policy_digest != self.policy.digest():
                errors.append(_err(E_POLICY_CHANGED_WITHOUT_VERSION_BUMP,
                                   f"policy_version {self.policy.policy_version} already recorded with a different digest"))
                break

        evidence = self.evidence_builder(pid) if pid else None
        if evidence is None or not evidence.pattern_found:
            errors.append(_err(E_PATTERN_NOT_IN_REGISTRY, "pattern is not in the current Phase 3.8 pattern registry"))

        proposed: Optional[Dict[str, Any]] = None
        if not errors and evidence is not None:
            proposed = self._proposed(request, pid, dtype, corpus, gate.review_mode, previous_state, previous_id, evidence)
            schema_errors = validate_record(proposed, allow_unsealed=True)
            if schema_errors:
                errors.append(_err(E_SCHEMA, ",".join(schema_errors)))
                proposed = None
        return ValidationResult(ok=not errors, errors=errors, proposed=proposed, gate=gate.as_dict(),
                                previous_state=previous_state, previous_decision_id=previous_id, allowed_next=allowed)

    @staticmethod
    def _same_content(head: DecisionRecord, request: DecisionRequest, dtype: str) -> bool:
        return (head.decision_type == dtype and head.reason == str(request.reason or "").strip()
                and head.actor == str(request.actor or "").strip() and head.actor_type == request.actor_type
                and head.idempotency_key == str(request.idempotency_key or ""))

    def _proposed(self, request: DecisionRequest, pid: str, dtype: str, corpus: CorpusState, review_mode: str,
                  previous_state: str, previous_id: str, evidence: EvidenceSnapshot) -> Dict[str, Any]:
        decision_id = decision_id_for(pattern_id=pid, decision_type=dtype, reason=request.reason, actor=request.actor,
                                      actor_type=request.actor_type, policy_version=self.policy.policy_version,
                                      previous_decision_id=previous_id, idempotency_key=request.idempotency_key)
        record = DecisionRecord(
            decision_id=decision_id, pattern_id=pid, decision_type=dtype, reason=str(request.reason).strip(),
            actor=str(request.actor).strip(), actor_type=request.actor_type,
            decided_at=self.clock().astimezone(timezone.utc).isoformat(),
            policy_version=self.policy.policy_version, policy_digest=self.policy.digest(), review_mode=review_mode,
            corpus_size=int(corpus.eligible), corpus_documents=int(corpus.documents), corpus_usable=int(corpus.usable),
            corpus_milestone=str(corpus.milestone), previous_state=previous_state, previous_decision_id=previous_id,
            evidence=evidence.as_dict(), evidence_digest=evidence.digest(),
            supersedes_decision_id=previous_id if dtype == SUPERSEDED else "",
            reopens_decision_id=previous_id if dtype == REOPENED_FOR_REVIEW else "",
            promotion_status=NOT_PROMOTED, notes=str(request.notes or ""),
            metadata={str(k): str(v) for k, v in dict(request.metadata or {}).items()},
            idempotency_key=str(request.idempotency_key or ""), schema_version=SCHEMA_VERSION)
        return record.as_dict()

    # ------------------------------------------------------------- decide（唯一の mutating path）
    def decide(self, request: DecisionRequest) -> DecisionOutcome:
        validation = self.validate(request)
        if validation.ok and validation.duplicate_of_head:
            existing = self.store.get(validation.duplicate_of_head)
            state = self.current_state(existing.pattern_id) if existing else None
            return DecisionOutcome(appended=False, decision_id=validation.duplicate_of_head,
                                   record=existing.as_dict() if existing else None,
                                   current_state=state.as_dict() if state else None,
                                   validation=validation, store_reason="DUPLICATE_OF_HEAD_IDEMPOTENT")
        if not validation.ok or validation.proposed is None:
            return DecisionOutcome(appended=False, decision_id="", record=None, current_state=None,
                                   validation=validation, store_reason="VALIDATION_FAILED")
        result = self.store.append(validation.proposed)
        record: DecisionRecord = result["record"]
        state = self.current_state(record.pattern_id)
        return DecisionOutcome(appended=bool(result["appended"]), decision_id=record.decision_id,
                               record=record.as_dict(), current_state=state.as_dict() if state else None,
                               validation=validation, store_reason=str(result.get("reason", "")))
