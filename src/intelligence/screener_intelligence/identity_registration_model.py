"""P8-ID2 — 人が承認した identity の登録 executor の結果の model（派生 ・非 authority ・非永続。結果は record ではない）。

- `RegistrationOutcome`: `APPENDED` ／ `REUSED` ／ `REJECTED` ／ `PARTIAL_FAILURE` ／ `NO_AUTHORIZED_ITEMS`。
  score ・severity ・順位は無い。
- `RegistrationReason`: 閉じた型つきの理由（信頼の境界 ・A1 の現在の状態との衝突 ・store ・入力）。本文に provider の値を入れない。
- `RecordWrite` ／ `BundleExecution` ／ `RegistrationWrites`: **実際に** A1 に append した ／ byte 一致で再利用した record の id と種類を、
  承認された束（1 提案 ＝ Issuer ＋ Security ＋ 識別子 ＋ 名前 ＋ 上場）ごとに列挙する。`APPENDED` は要る書き込みがすべて終わったときだけ。

記録: `docs/databank/PHASE8_ID2_IDENTITY_REGISTRATION_EXECUTOR.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Tuple

from .identity_model import RecordKind
from .jquants_adapter_model import DERIVED_NON_AUTHORITY_NON_PERSISTENT

REGISTRATION_RULES_VERSION = "p8_identity_registration:0.1.0"
REGISTRATION_RESULT_CLASS = DERIVED_NON_AUTHORITY_NON_PERSISTENT
_CODE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"


class RegistrationOutcome(str, Enum):
    APPENDED = "APPENDED"                        # 要る A1 の書き込みがすべて終わった（再利用を含んでよい）
    REUSED = "REUSED"                            # 何も新しく書かず、既存の A1 の record に収束した（正確な replay）
    REJECTED = "REJECTED"                        # 何も書かなかった
    PARTIAL_FAILURE = "PARTIAL_FAILURE"          # 一部の record の append の後に失敗した（rollback ・削除 ・上書きは無い）
    NO_AUTHORIZED_ITEMS = "NO_AUTHORIZED_ITEMS"  # 承認された提案が無い（REJECT ・DEFER ・未審査だけ）


class RegistrationReason(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    MANIFEST_DIGEST_MISMATCH = "MANIFEST_DIGEST_MISMATCH"
    REVIEW_BINDING_INVALID = "REVIEW_BINDING_INVALID"
    PRIOR_PLAN_MISMATCH = "PRIOR_PLAN_MISMATCH"
    PLAN_REJECTED = "PLAN_REJECTED"
    ISSUER_CONFLICT = "ISSUER_CONFLICT"
    SECURITY_CONFLICT = "SECURITY_CONFLICT"
    ISSUER_SECURITY_RELATION_CONFLICT = "ISSUER_SECURITY_RELATION_CONFLICT"
    CODE_BOUND_TO_OTHER_IDENTITY = "CODE_BOUND_TO_OTHER_IDENTITY"
    IDENTIFIER_CONFLICT = "IDENTIFIER_CONFLICT"
    RETIRED_CODE_AMBIGUITY = "RETIRED_CODE_AMBIGUITY"
    DISPLAY_NAME_CONFLICT = "DISPLAY_NAME_CONFLICT"
    LISTING_CONFLICT = "LISTING_CONFLICT"
    LISTING_ENDED = "LISTING_ENDED"
    COVERAGE_CONFLICT = "COVERAGE_CONFLICT"
    KNOWN_AT_NOT_MONOTONIC = "KNOWN_AT_NOT_MONOTONIC"
    AUTHORITY_RULE_VIOLATION = "AUTHORITY_RULE_VIOLATION"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    STORE_MISSING = "STORE_MISSING"
    CORRUPT_STORE = "CORRUPT_STORE"
    STORE_WRITE_FAILED = "STORE_WRITE_FAILED"
    PARTIAL_WRITE = "PARTIAL_WRITE"


_REASON_ORDER = {reason: index for index, reason in enumerate(RegistrationReason)}
#: 何も書く前に決まる（前検査の）衝突の理由
CONFLICT_REASONS: Tuple[RegistrationReason, ...] = (
    RegistrationReason.ISSUER_CONFLICT, RegistrationReason.SECURITY_CONFLICT,
    RegistrationReason.ISSUER_SECURITY_RELATION_CONFLICT, RegistrationReason.CODE_BOUND_TO_OTHER_IDENTITY,
    RegistrationReason.IDENTIFIER_CONFLICT, RegistrationReason.RETIRED_CODE_AMBIGUITY,
    RegistrationReason.DISPLAY_NAME_CONFLICT, RegistrationReason.LISTING_CONFLICT, RegistrationReason.LISTING_ENDED,
    RegistrationReason.COVERAGE_CONFLICT, RegistrationReason.KNOWN_AT_NOT_MONOTONIC,
    RegistrationReason.AUTHORITY_RULE_VIOLATION)


class WriteState(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    FAILED = "FAILED"


class RegistrationModelError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise RegistrationModelError(code, detail)


def _code(value: Any, field_name: str) -> str:
    _require(isinstance(value, str) and len(value) <= 64 and all(c in _CODE_CHARS for c in value), "INVALID_CODE",
             field_name)
    return value


def ordered_registration_reasons(reasons: Any) -> Tuple[RegistrationReason, ...]:
    _require(isinstance(reasons, (tuple, list)) and all(isinstance(r, RegistrationReason) for r in reasons),
             "INVALID_REASONS", "reasons")
    return tuple(sorted(set(reasons), key=_REASON_ORDER.__getitem__))


@dataclass(frozen=True, kw_only=True)
class RecordWrite:
    """計画した 1 record の扱い（A1 の record id ・種類 ・書き込みの状態）。"""

    record_id: str
    kind: RecordKind
    state: WriteState
    failure_code: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.record_id, str) and self.record_id.startswith("p8idr_"), "INVALID_WRITE", "record_id")
        _require(isinstance(self.kind, RecordKind) and isinstance(self.state, WriteState), "INVALID_WRITE", "kind")
        _code(self.failure_code, "failure_code")

    def as_dict(self) -> Dict[str, Any]:
        return {"failure_code": self.failure_code, "kind": self.kind.value, "record_id": self.record_id,
                "state": self.state.value}


@dataclass(frozen=True, kw_only=True)
class BundleExecution:
    """承認された 1 提案（束）の実行。"""

    proposal_id: str
    code: str
    issuer_id: str
    security_id: str
    writes: Tuple[RecordWrite, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.writes, tuple) and all(isinstance(w, RecordWrite) for w in self.writes),
                 "INVALID_BUNDLE", "writes")

    @property
    def state(self) -> WriteState:
        states = {w.state for w in self.writes}
        if WriteState.FAILED in states:
            return WriteState.FAILED
        if states == {WriteState.NOT_ATTEMPTED}:
            return WriteState.NOT_ATTEMPTED
        if WriteState.APPENDED in states:
            return WriteState.APPENDED
        return WriteState.REUSED

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "issuer_id": self.issuer_id, "proposal_id": self.proposal_id,
                "security_id": self.security_id, "state": self.state.value,
                "writes": [w.as_dict() for w in self.writes]}


@dataclass(frozen=True, kw_only=True)
class RegistrationWrites:
    """実際に A1 に append した ／ 再利用した record の id（実行の順）。"""

    appended: Tuple[str, ...] = ()
    reused: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("appended", "reused"):
            value = self.__dict__[name]
            _require(isinstance(value, tuple) and all(isinstance(v, str) and v for v in value), "INVALID_WRITES", name)

    def as_dict(self) -> Dict[str, Any]:
        return {"appended": list(self.appended), "reused": list(self.reused)}


@dataclass(frozen=True, kw_only=True)
class RegistrationResult:
    """登録の実行の結果（派生 ・非 authority ・非永続）。"""

    outcome: RegistrationOutcome
    reasons: Tuple[RegistrationReason, ...]
    bundles: Tuple[BundleExecution, ...] = ()
    coverage: Tuple[RecordWrite, ...] = ()
    writes: RegistrationWrites = RegistrationWrites()
    manifest_digest: str = ""
    reviewed_digest: str = ""
    plan_digest: str = ""
    failure_code: str = ""
    rules_version: str = REGISTRATION_RULES_VERSION
    authority_class: str = REGISTRATION_RESULT_CLASS

    def __post_init__(self) -> None:
        _require(isinstance(self.outcome, RegistrationOutcome), "INVALID_RESULT", "outcome")
        _require(self.reasons == ordered_registration_reasons(self.reasons), "INVALID_RESULT", "reasons")
        _require(isinstance(self.bundles, tuple) and all(isinstance(b, BundleExecution) for b in self.bundles),
                 "INVALID_RESULT", "bundles")
        _require(isinstance(self.coverage, tuple) and all(isinstance(c, RecordWrite) for c in self.coverage),
                 "INVALID_RESULT", "coverage")
        _require(isinstance(self.writes, RegistrationWrites), "INVALID_RESULT", "writes")
        _code(self.failure_code, "failure_code")
        states = {b.state for b in self.bundles} | {c.state for c in self.coverage}
        if self.outcome is RegistrationOutcome.APPENDED:
            _require(self.reasons == () and self.writes.appended != () and states <= {WriteState.APPENDED,
                                                                                    WriteState.REUSED},
                     "INVALID_RESULT", "appended")
        elif self.outcome is RegistrationOutcome.REUSED:
            _require(self.reasons == () and self.writes.appended == () and self.writes.reused != ()
                     and states == {WriteState.REUSED}, "INVALID_RESULT", "reused")
        elif self.outcome is RegistrationOutcome.REJECTED:
            _require(self.reasons != () and self.writes.appended == (), "INVALID_RESULT", "rejected")
        elif self.outcome is RegistrationOutcome.PARTIAL_FAILURE:
            _require(RegistrationReason.PARTIAL_WRITE in self.reasons and self.writes.appended != ()
                     and WriteState.FAILED in states, "INVALID_RESULT", "partial")
        else:
            _require(self.reasons == () and self.bundles == () and self.writes.appended == ()
                     and self.writes.reused == (), "INVALID_RESULT", "no_authorized_items")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "bundles": [b.as_dict() for b in self.bundles],
                "coverage": [c.as_dict() for c in self.coverage], "failure_code": self.failure_code,
                "manifest_digest": self.manifest_digest, "outcome": self.outcome.value,
                "plan_digest": self.plan_digest, "reasons": [r.value for r in self.reasons],
                "reviewed_digest": self.reviewed_digest, "rules_version": self.rules_version,
                "writes": self.writes.as_dict()}


__all__ = ["CONFLICT_REASONS", "REGISTRATION_RESULT_CLASS", "REGISTRATION_RULES_VERSION", "BundleExecution",
           "RecordWrite", "RegistrationModelError", "RegistrationOutcome", "RegistrationReason",
           "RegistrationResult", "RegistrationWrites", "WriteState", "ordered_registration_reasons"]
