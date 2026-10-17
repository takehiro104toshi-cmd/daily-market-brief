"""P8-EXE — 安全な append executor の結果の model（派生 ・非 authority ・非永続。結果は record ではなく、どこにも書かれない）。

- 結果 `ExecutionResult`: 行 1 つの実行の帰結。`APPENDED` ／ `REUSED` ／ `HELD` ／ `REJECTED` ／ `PARTIAL_FAILURE` ／
  `NO_REPORTED_FIELDS`。score ・severity ・順位は無い。
- `AuthorityWrites`: **実際に**書いた ／ 収束（byte 一致で再利用）した authority の record id を authority ごとに列挙する。
  `APPENDED` は要る書き込みがすべて終わったときだけ。
- `FieldExecution`: 支える 4 欄それぞれの扱い（append ・再利用 ・記載なし ・未試行 ・失敗）と、書いた record の id ・`supersedes`。
- 理由 `ExecutionReason`: 閉じた型つきの code。error の本文に provider の値 ・raw の応答 ・traceback を入れない（code だけ）。

記録: `docs/databank/PHASE8_EXE_SAFE_APPEND_EXECUTOR.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .held_observation_model import HeldReason
from .jquants_adapter_model import DERIVED_NON_AUTHORITY_NON_PERSISTENT, ProviderRecordIdentity
from .observation_model import FundamentalField

EXECUTION_RULES_VERSION = "p8_jquants_execution:0.1.0"
#: 実行の結果の authority の種類（record ではない ・保存しない ・後段は信用せず再導出する）
EXECUTION_RESULT_CLASS = DERIVED_NON_AUTHORITY_NON_PERSISTENT
_CODE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"


class ExecutionOutcome(str, Enum):
    APPENDED = "APPENDED"                      # 要る authority の書き込みがすべて終わった（再利用を含んでよい）
    REUSED = "REUSED"                          # 何も新しく書かず、既存の authority に収束した（正確な replay）
    HELD = "HELD"                              # 保留の store にだけ書いた（A2 ・注記には書かない）
    REJECTED = "REJECTED"                      # 何も書かなかった（入力 ・前検査 ・store の不在 ／ 破損 ・cross-check の不一致）
    PARTIAL_FAILURE = "PARTIAL_FAILURE"        # 一部の authority の書き込みの後に失敗した（rollback ・削除 ・上書きは無い）
    NO_REPORTED_FIELDS = "NO_REPORTED_FIELDS"  # 支える 4 欄がすべて記載なしで、書くものが無い


class ExecutionReason(str, Enum):
    ADAPTER_HELD = "ADAPTER_HELD"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    PRIOR_RESULT_MISMATCH = "PRIOR_RESULT_MISMATCH"
    SEMANTIC_CONFLICT = "SEMANTIC_CONFLICT"
    SEMANTIC_CHAIN_HOLD = "SEMANTIC_CHAIN_HOLD"
    OBSERVATION_CONFLICT = "OBSERVATION_CONFLICT"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    STORE_WRITE_FAILED = "STORE_WRITE_FAILED"
    PARTIAL_WRITE = "PARTIAL_WRITE"
    CORRUPT_STORE = "CORRUPT_STORE"
    STORE_MISSING = "STORE_MISSING"
    INVALID_INPUT = "INVALID_INPUT"


_REASON_ORDER = {reason: index for index, reason in enumerate(ExecutionReason)}


class WriteState(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"
    NOT_REQUIRED = "NOT_REQUIRED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    FAILED = "FAILED"


class FieldDisposition(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"
    NOT_REPORTED = "NOT_REPORTED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    FAILED = "FAILED"


class ExecutionModelError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ExecutionModelError(code, detail)


def _code(value: Any, field_name: str) -> str:
    """失敗の code（大文字 ・数字 ・`_` だけ。provider の値 ・本文 ・path を通さない）。空でよい。"""
    _require(isinstance(value, str) and len(value) <= 64 and all(c in _CODE_CHARS for c in value), "INVALID_CODE",
             field_name)
    return value


def ordered_execution_reasons(reasons: Any) -> Tuple[ExecutionReason, ...]:
    """閉じた理由の集合を固定の順に並べる（重複なし）。"""
    _require(isinstance(reasons, (tuple, list)), "INVALID_REASONS", "reasons")
    for reason in reasons:
        _require(isinstance(reason, ExecutionReason), "INVALID_REASONS", "reasons")
    return tuple(sorted(set(reasons), key=_REASON_ORDER.__getitem__))


@dataclass(frozen=True, kw_only=True)
class FieldExecution:
    """支える 1 欄の実行の扱い。書いた record の id は authority の id そのもの（写しではない）。"""

    provider_field: str
    field: FundamentalField
    disposition: FieldDisposition
    observation_id: str = ""
    supersedes: str = ""
    provenance_id: str = ""
    semantics_id: str = ""
    provenance_write: WriteState = WriteState.NOT_ATTEMPTED
    semantics_write: WriteState = WriteState.NOT_ATTEMPTED
    observation_write: WriteState = WriteState.NOT_ATTEMPTED
    failure_code: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.provider_field, str) and self.provider_field != "", "INVALID_FIELD", "provider_field")
        _require(isinstance(self.field, FundamentalField), "INVALID_FIELD", "field")
        _require(isinstance(self.disposition, FieldDisposition), "INVALID_FIELD", "disposition")
        for name in ("provenance_write", "semantics_write", "observation_write"):
            _require(isinstance(self.__dict__[name], WriteState), "INVALID_FIELD", name)
        for name in ("observation_id", "supersedes", "provenance_id", "semantics_id"):
            _require(isinstance(self.__dict__[name], str), "INVALID_FIELD", name)
        _code(self.failure_code, "failure_code")
        if self.disposition is FieldDisposition.NOT_REPORTED:
            _require(self.observation_id == "" and self.observation_write is WriteState.NOT_REQUIRED, "INVALID_FIELD",
                     "not_reported")
        if self.disposition in (FieldDisposition.APPENDED, FieldDisposition.REUSED):
            _require(self.observation_id != "" and self.semantics_id != "" and self.provenance_id != "",
                     "INVALID_FIELD", "ids")
            _require(self.observation_write in (WriteState.APPENDED, WriteState.REUSED), "INVALID_FIELD",
                     "observation_write")
        if self.disposition is FieldDisposition.APPENDED:
            _require(WriteState.APPENDED in (self.provenance_write, self.semantics_write, self.observation_write),
                     "INVALID_FIELD", "appended")
        if self.disposition is FieldDisposition.REUSED:
            _require(self.observation_write is WriteState.REUSED and self.semantics_write is WriteState.REUSED
                     and self.provenance_write is WriteState.REUSED, "INVALID_FIELD", "reused")

    def as_dict(self) -> Dict[str, Any]:
        return {"disposition": self.disposition.value, "failure_code": self.failure_code, "field": self.field.value,
                "observation_id": self.observation_id, "observation_write": self.observation_write.value,
                "provenance_id": self.provenance_id, "provenance_write": self.provenance_write.value,
                "provider_field": self.provider_field, "semantics_id": self.semantics_id,
                "semantics_write": self.semantics_write.value, "supersedes": self.supersedes}


@dataclass(frozen=True, kw_only=True)
class AuthorityWrites:
    """実際に書いた ／ 収束した authority の record id（authority ごと。実行の順）。"""

    semantic_metadata_appended: Tuple[str, ...] = ()
    semantic_metadata_reused: Tuple[str, ...] = ()
    observations_appended: Tuple[str, ...] = ()
    observations_reused: Tuple[str, ...] = ()
    held_appended: str = ""
    held_reused: str = ""

    def __post_init__(self) -> None:
        for name in ("semantic_metadata_appended", "semantic_metadata_reused", "observations_appended",
                     "observations_reused"):
            value = self.__dict__[name]
            _require(isinstance(value, tuple) and all(isinstance(item, str) and item for item in value),
                     "INVALID_WRITES", name)
        _require(isinstance(self.held_appended, str) and isinstance(self.held_reused, str), "INVALID_WRITES", "held")
        _require(not (self.held_appended and self.held_reused), "INVALID_WRITES", "held")

    @property
    def any_appended(self) -> bool:
        return bool(self.semantic_metadata_appended or self.observations_appended or self.held_appended)

    @property
    def any_reused(self) -> bool:
        return bool(self.semantic_metadata_reused or self.observations_reused or self.held_reused)

    def as_dict(self) -> Dict[str, Any]:
        return {"held_appended": self.held_appended, "held_reused": self.held_reused,
                "observations_appended": list(self.observations_appended),
                "observations_reused": list(self.observations_reused),
                "semantic_metadata_appended": list(self.semantic_metadata_appended),
                "semantic_metadata_reused": list(self.semantic_metadata_reused)}


@dataclass(frozen=True, kw_only=True)
class ExecutionResult:
    """行 1 つの実行の結果（派生 ・非 authority ・非永続）。raw の行 ・provider の値 ・traceback は無い。"""

    outcome: ExecutionOutcome
    reasons: Tuple[ExecutionReason, ...]
    provider_record: Optional[ProviderRecordIdentity]
    issuer_id: str = ""
    fields: Tuple[FieldExecution, ...] = ()
    writes: AuthorityWrites = AuthorityWrites()
    held_reasons: Tuple[HeldReason, ...] = ()
    held_record_id: str = ""
    failure_code: str = ""
    mapping_rule_version: str = ""
    rules_version: str = EXECUTION_RULES_VERSION
    authority_class: str = EXECUTION_RESULT_CLASS

    def __post_init__(self) -> None:
        _require(isinstance(self.outcome, ExecutionOutcome), "INVALID_RESULT", "outcome")
        _require(self.reasons == ordered_execution_reasons(self.reasons), "INVALID_RESULT", "reasons")
        _require(self.provider_record is None or isinstance(self.provider_record, ProviderRecordIdentity),
                 "INVALID_RESULT", "provider_record")
        _require(isinstance(self.fields, tuple) and all(isinstance(f, FieldExecution) for f in self.fields),
                 "INVALID_RESULT", "fields")
        _require(isinstance(self.writes, AuthorityWrites), "INVALID_RESULT", "writes")
        _require(isinstance(self.held_reasons, tuple) and all(isinstance(r, HeldReason) for r in self.held_reasons),
                 "INVALID_RESULT", "held_reasons")
        _code(self.failure_code, "failure_code")
        dispositions = {f.disposition for f in self.fields}
        outcome = self.outcome
        if outcome is ExecutionOutcome.APPENDED:
            _require(self.reasons == () and self.writes.any_appended and not self.writes.held_appended
                     and not self.writes.held_reused and FieldDisposition.APPENDED in dispositions
                     and not dispositions & {FieldDisposition.FAILED, FieldDisposition.NOT_ATTEMPTED},
                     "INVALID_RESULT", "appended")
        elif outcome is ExecutionOutcome.REUSED:
            _require(self.reasons == () and not self.writes.any_appended and self.writes.any_reused
                     and dispositions <= {FieldDisposition.REUSED, FieldDisposition.NOT_REPORTED}
                     and FieldDisposition.REUSED in dispositions, "INVALID_RESULT", "reused")
        elif outcome is ExecutionOutcome.HELD:
            _require(self.held_record_id != "" and self.held_reasons != ()
                     and (self.writes.held_appended or self.writes.held_reused)
                     and not self.writes.semantic_metadata_appended and not self.writes.observations_appended,
                     "INVALID_RESULT", "held")
        elif outcome is ExecutionOutcome.REJECTED:
            _require(self.reasons != () and not self.writes.any_appended, "INVALID_RESULT", "rejected")
        elif outcome is ExecutionOutcome.PARTIAL_FAILURE:
            _require(ExecutionReason.PARTIAL_WRITE in self.reasons and self.writes.any_appended
                     and FieldDisposition.FAILED in dispositions, "INVALID_RESULT", "partial")
        else:
            _require(self.reasons == () and not self.writes.any_appended and not self.writes.any_reused
                     and dispositions == {FieldDisposition.NOT_REPORTED}, "INVALID_RESULT", "no_reported_fields")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "failure_code": self.failure_code,
                "fields": [f.as_dict() for f in self.fields], "held_reasons": [r.value for r in self.held_reasons],
                "held_record_id": self.held_record_id, "issuer_id": self.issuer_id,
                "mapping_rule_version": self.mapping_rule_version, "outcome": self.outcome.value,
                "provider_record": self.provider_record.as_dict() if self.provider_record else None,
                "reasons": [r.value for r in self.reasons], "rules_version": self.rules_version,
                "writes": self.writes.as_dict()}


__all__ = ["EXECUTION_RESULT_CLASS", "EXECUTION_RULES_VERSION", "AuthorityWrites", "ExecutionModelError",
           "ExecutionOutcome", "ExecutionReason", "ExecutionResult", "FieldDisposition", "FieldExecution",
           "WriteState", "ordered_execution_reasons"]
