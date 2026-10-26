"""P8-ST1 — 保留の観測（`HeldObservation`）の純 model: provider 由来の候補が A2 の authority に安全に入れなかった**事実**の運用 record。

- 何のために: 候補が A2 に入らなかったこと ・その理由（閉じた語彙）・どの provider の record から ・どの規則の版で判断したかを、
  raw の応答を持たずに監査できる形で残す。severity ・優先度 ・順位 ・score ・投資の解釈は持たない（監督の決定 D3）。
- 何を持たないか: raw の応答の本文 ・credential ・自由文の隠れた理由。欄は参照（provider の record の参照 ・digest ・解けたなら
  identity の id）と閉じた enum と規則の版だけ。`raw` ・`payload` ・`response_body` ・`api_response` という欄は無く、参照の欄は
  文字の集合と長さを制限して本文 ・JSON ・path ・URL を通さない。
- 時刻: 運用の時刻（`observed_at`）は caller が明示に渡す aware な datetime だけ。時計を読まない。省けば None。
- identity: 内容 address（`p8hld_`）。`audit_note` だけは identity に入らない（短い ・credential の印なし）。
- 自動の昇格 ・再試行 ・削除は無い。保留の解除は後の gate の明示の run と参照 record。

記録: `docs/databank/PHASE8_ST1_OPERATIONAL_STORES.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .identity_model import CREDENTIAL_MARKERS, SourceClass, canonical_json, is_issuer_id, is_security_id
from .observation_model import FundamentalField, StatementBasis
from .observation_semantics_model import SchemaFamily
from ..core.ids import content_id
from ..core.time import from_iso, to_utc_iso

HELD_SCHEMA_VERSION = "p8_held_observation:0.1.0"
HELD_RECORD_KIND = "HELD_OBSERVATION"
HELD_ID_PREFIX = "p8hld"
#: 運用 record の authority の種類（authority ではない。A2 ・A1 に入らない。指標 ・screen は読まない）
OPERATIONAL_HOLD_RECORD = "OPERATIONAL_HOLD_RECORD"
MAX_AUDIT_NOTE_LENGTH = 160
#: provider の record の参照（A2 の `source_record_ref` と同じ形: 英数と `._:#-`、160 文字まで ＝ 本文 ・JSON ・path ・URL を持てない）
_PROVIDER_RECORD_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:#-]{0,159}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RULE_VERSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}:[0-9]+\.[0-9]+\.[0-9]+$")
#: 監査の注記: 1 行 ・制御文字なし ・160 文字まで（identity に入らない）
_AUDIT_NOTE_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,160}$")


class HeldObservationModelError(ValueError):
    """record の構造 ・語彙 ・値の違反（fail closed）。detail は field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise HeldObservationModelError(code, detail)


class HeldReason(str, Enum):
    """保留の理由（閉じた語彙。A3R の設計 §7 ・§9 ・§10 と A2R の HOLD の理由から。順位 ・severity を持たない）。"""

    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    ACCOUNTING_STANDARD_UNKNOWN = "ACCOUNTING_STANDARD_UNKNOWN"
    ACCOUNTING_STANDARD_UNSUPPORTED = "ACCOUNTING_STANDARD_UNSUPPORTED"
    STATEMENT_BASIS_UNKNOWN = "STATEMENT_BASIS_UNKNOWN"
    DOCTYPE_UNRECOGNIZED = "DOCTYPE_UNRECOGNIZED"
    DOCTYPE_OUT_OF_SCOPE = "DOCTYPE_OUT_OF_SCOPE"
    CURRENCY_UNSUPPORTED = "CURRENCY_UNSUPPORTED"
    CURRENCY_UNKNOWN = "CURRENCY_UNKNOWN"
    PERIOD_UNSUPPORTED = "PERIOD_UNSUPPORTED"
    VALUE_UNPARSEABLE = "VALUE_UNPARSEABLE"
    KNOWLEDGE_TIME_INVALID = "KNOWLEDGE_TIME_INVALID"
    KNOWLEDGE_TIME_INSUFFICIENT = "KNOWLEDGE_TIME_INSUFFICIENT"
    SEMANTIC_CHAIN_CONFLICT = "SEMANTIC_CHAIN_CONFLICT"
    SEMANTICS_CONFLICT = "SEMANTICS_CONFLICT"
    PROVIDER_REVISION_CONFLICT = "PROVIDER_REVISION_CONFLICT"
    MAPPING_UNSUPPORTED = "MAPPING_UNSUPPORTED"
    TERMS_BOUNDARY = "TERMS_BOUNDARY"


_REASON_ORDER: Mapping[HeldReason, int] = {member: index for index, member in enumerate(HeldReason)}


def _enum(value: Any, enum_type, field_name: str):
    _require(isinstance(value, enum_type), "INVALID_VOCABULARY", field_name)
    return value


def _parse_enum(value: Any, enum_type, field_name: str):
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        raise HeldObservationModelError("INVALID_VOCABULARY", field_name) from None


def _text(value: Any, pattern, code: str, field_name: str) -> str:
    _require(isinstance(value, str) and bool(pattern.match(value)), code, field_name)
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)
    return value


def _aware(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_DATETIME", field_name)
    _require(value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None, "NAIVE_DATETIME", field_name)
    return value


def ordered_reasons(reasons: Any) -> Tuple[HeldReason, ...]:
    """重複を除き語彙の順に並べる（正準。空は認めない）。"""
    _require(isinstance(reasons, (tuple, list, frozenset, set)), "INVALID_REASONS", "reasons")
    unique = set(reasons)
    for reason in unique:
        _enum(reason, HeldReason, "reasons")
    _require(len(unique) > 0, "INVALID_REASONS", "reasons")
    return tuple(sorted(unique, key=_REASON_ORDER.__getitem__))


def _reject_unknown(data: Mapping[str, Any], allowed: Iterable[str], name: str) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", name)
    _require(set(data) <= set(allowed), "UNKNOWN_FIELD", name)
    _require(set(allowed) <= set(data), "MISSING_FIELD", name)


@dataclass(frozen=True, kw_only=True)
class HeldObservation:
    """保留の観測の運用 record（不変 ・内容 address）。raw の本文 ・credential を持てない。"""

    KIND = HELD_RECORD_KIND
    AUTHORITY_CLASS = OPERATIONAL_HOLD_RECORD
    provider: SourceClass
    schema_family: SchemaFamily
    provider_record_ref: str
    provider_record_digest: str
    reasons: Tuple[HeldReason, ...]
    mapping_rule_version: str
    rules_version: str
    issuer_id: str = ""
    security_id: str = ""
    attempted_field: Optional[FundamentalField] = None
    attempted_statement_basis: Optional[StatementBasis] = None
    observed_at: Optional[datetime] = None
    audit_note: str = ""

    def __post_init__(self) -> None:
        _enum(self.provider, SourceClass, "provider")
        _enum(self.schema_family, SchemaFamily, "schema_family")
        _text(self.provider_record_ref, _PROVIDER_RECORD_REF_RE, "INVALID_PROVIDER_RECORD_REF", "provider_record_ref")
        _require(isinstance(self.provider_record_digest, str) and bool(_DIGEST_RE.match(self.provider_record_digest)),
                 "INVALID_DIGEST", "provider_record_digest")
        object.__setattr__(self, "reasons", ordered_reasons(self.reasons))
        _text(self.mapping_rule_version, _RULE_VERSION_RE, "INVALID_RULE_VERSION", "mapping_rule_version")
        _text(self.rules_version, _RULE_VERSION_RE, "INVALID_RULE_VERSION", "rules_version")
        _require(self.issuer_id == "" or is_issuer_id(self.issuer_id), "INVALID_SUBJECT", "issuer_id")
        _require(self.security_id == "" or is_security_id(self.security_id), "INVALID_SUBJECT", "security_id")
        if self.attempted_field is not None:
            _enum(self.attempted_field, FundamentalField, "attempted_field")
        if self.attempted_statement_basis is not None:
            _enum(self.attempted_statement_basis, StatementBasis, "attempted_statement_basis")
        if self.observed_at is not None:
            _aware(self.observed_at, "observed_at")
        _text(self.audit_note, _AUDIT_NOTE_RE, "INVALID_AUDIT_NOTE", "audit_note")

    def identity_payload(self) -> Dict[str, Any]:
        """identity に入る内容（`audit_note` は入らない）。"""
        return {"attempted_field": self.attempted_field.value if self.attempted_field else None,
                "attempted_statement_basis": (self.attempted_statement_basis.value
                                              if self.attempted_statement_basis else None),
                "issuer_id": self.issuer_id, "mapping_rule_version": self.mapping_rule_version,
                "observed_at": to_utc_iso(self.observed_at) if self.observed_at is not None else None,
                "provider": self.provider.value, "provider_record_digest": self.provider_record_digest,
                "provider_record_ref": self.provider_record_ref, "reasons": [r.value for r in self.reasons],
                "record_kind": HELD_RECORD_KIND, "rules_version": self.rules_version,
                "schema_family": self.schema_family.value, "schema_version": HELD_SCHEMA_VERSION,
                "security_id": self.security_id}

    @property
    def record_id(self) -> str:
        return content_id(HELD_ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "audit_note": self.audit_note, "record_id": self.record_id}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HeldObservation":
        _reject_unknown(data, ("attempted_field", "attempted_statement_basis", "audit_note", "issuer_id",
                               "mapping_rule_version", "observed_at", "provider", "provider_record_digest",
                               "provider_record_ref", "reasons", "record_id", "record_kind", "rules_version",
                               "schema_family", "schema_version", "security_id"), "record")
        _require(data["schema_version"] == HELD_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(data["record_kind"] == HELD_RECORD_KIND, "KIND_MISMATCH", "record_kind")
        _require(isinstance(data["reasons"], list), "INVALID_REASONS", "reasons")
        field = data["attempted_field"]
        basis = data["attempted_statement_basis"]
        observed = data["observed_at"]
        if observed is not None:
            _require(isinstance(observed, str), "INVALID_DATETIME", "observed_at")
            try:
                observed = from_iso(observed)
            except ValueError:
                raise HeldObservationModelError("INVALID_DATETIME", "observed_at") from None
        record = cls(provider=_parse_enum(data["provider"], SourceClass, "provider"),
                     schema_family=_parse_enum(data["schema_family"], SchemaFamily, "schema_family"),
                     provider_record_ref=data["provider_record_ref"],
                     provider_record_digest=data["provider_record_digest"],
                     reasons=tuple(_parse_enum(item, HeldReason, "reasons") for item in data["reasons"]),
                     mapping_rule_version=data["mapping_rule_version"], rules_version=data["rules_version"],
                     issuer_id=data["issuer_id"], security_id=data["security_id"],
                     attempted_field=None if field is None else _parse_enum(field, FundamentalField, "attempted_field"),
                     attempted_statement_basis=(None if basis is None
                                                else _parse_enum(basis, StatementBasis, "attempted_statement_basis")),
                     observed_at=observed, audit_note=data["audit_note"])
        _require([r.value for r in record.reasons] == data["reasons"], "NON_CANONICAL_REASONS", "reasons")
        _require(record.record_id == data["record_id"], "ID_MISMATCH", "record_id")
        return record


def is_held_observation(record: Any) -> bool:
    return isinstance(record, HeldObservation)


__all__ = ["HELD_ID_PREFIX", "HELD_RECORD_KIND", "HELD_SCHEMA_VERSION", "MAX_AUDIT_NOTE_LENGTH",
           "OPERATIONAL_HOLD_RECORD", "HeldObservation", "HeldObservationModelError", "HeldReason",
           "is_held_observation", "ordered_reasons"]
