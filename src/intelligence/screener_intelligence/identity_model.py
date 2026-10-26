"""P8-A1 — Issuer ／ Security の identity の純 model（Phase 8 の authority の record・語彙・検査・履歴の不変条件）。

- Issuer（発行体）と Security（個々の上場物）は別の identity。1 つの Issuer が複数の Security を持てる。
- `IssuerId` ／ `SecurityId` は不透明で安定した id。登録の anchor（登録した authority の handle）と実体の種類からだけ導く。
  code ・ticker ・名前 ・市場の code から導かない（それらは時間つきの割り当て ／ 表示の属性）。
- 外部の識別子（J-Quants の code ・4 桁の local code）は有効期間つきの割り当て（`IdentifierAssignment`）で、終わりは
  別の record（`IdentifierRetirement`）で表す。名前は `DisplayName`、上場の期間は `ListingStart` ／ `ListingEnd`、
  authority が完全だと宣言する有効時間の範囲は `Coverage`。
- すべての record は不変・追記専用・内容 address（`record_id`）。時計・乱数・path・運用 metadata は identity に入らない。
- 時間は aware な datetime だけ。`known_at`（authority がそれを知った時刻）と有効時間（`effective_from` ／ `effective_to`）を
  分ける。履歴は `known_at` の非減少の順に並び、未来の record が過去の解決を変えられない。
- 曖昧な対応・重なる割り当て・自動の継続・自動の統合は fail closed で拒む。

契約: `docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md`。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from ..core.ids import content_id
from ..core.time import from_iso, to_utc_iso

SCHEMA_VERSION = "p8_identity_record:0.1.0"
AUTHORITY_RULES_VERSION = "p8_identity_authority_rules:0.1.0"
ISSUER_ID_PREFIX = "p8iss"
SECURITY_ID_PREFIX = "p8sec"
RECORD_ID_PREFIX = "p8idr"
#: record の authority の種類（契約 §16）
AUTHORITATIVE_IDENTITY_RECORD = "AUTHORITATIVE_IDENTITY_RECORD"

MAX_NAME_LEN = 120
_ID_RE = {prefix: re.compile(rf"^{prefix}_[0-9a-f]{{24}}$") for prefix in (ISSUER_ID_PREFIX, SECURITY_ID_PREFIX,
                                                                         RECORD_ID_PREFIX)}
#: 登録の anchor: `<authority>:<handle>`（不透明。code ・名前を使わない。契約 §3）
_ANCHOR_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
#: 出所の record の参照（`/`・`\\`・空白を含めない＝path ・URL ・本文を持てない。長さも上限つき）
_SOURCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:#-]{0,159}$")
#: 認証情報に見える語を参照に入れない（契約 §23）
CREDENTIAL_MARKERS = ("apikey", "api_key", "api-key", "token", "password", "passwd", "secret", "bearer",
                      "authorization")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class IdentityModelError(ValueError):
    """構造・語彙・値の違反（fail closed）。detail は field 名だけで、値を入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class IdentityHistoryError(ValueError):
    """履歴の不変条件の違反（参照先の欠落・重なり・分岐・継続の権限なし・時刻の逆行）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise IdentityModelError(code, detail)


# ---------------------------------------------------------------- 語彙（閉じた集合）


class RecordKind(str, Enum):
    ISSUER_REGISTRATION = "ISSUER_REGISTRATION"
    SECURITY_REGISTRATION = "SECURITY_REGISTRATION"
    IDENTIFIER_ASSIGNMENT = "IDENTIFIER_ASSIGNMENT"
    IDENTIFIER_RETIREMENT = "IDENTIFIER_RETIREMENT"
    DISPLAY_NAME = "DISPLAY_NAME"
    LISTING_START = "LISTING_START"
    LISTING_END = "LISTING_END"
    COVERAGE = "COVERAGE"


class SourceClass(str, Enum):
    OFFICIAL_EXCHANGE = "OFFICIAL_EXCHANGE"
    JQUANTS = "JQUANTS"
    ISSUER_DISCLOSURE = "ISSUER_DISCLOSURE"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"


class IssueClass(str, Enum):
    COMMON_EQUITY = "COMMON_EQUITY"
    PREFERRED_EQUITY = "PREFERRED_EQUITY"
    OTHER = "OTHER"


class IdentifierScheme(str, Enum):
    JQUANTS_CODE = "JQUANTS_CODE"
    LOCAL_CODE = "LOCAL_CODE"


class RetirementReason(str, Enum):
    RETIRED = "RETIRED"
    REPLACED = "REPLACED"


class SubjectKind(str, Enum):
    ISSUER = "ISSUER"
    SECURITY = "SECURITY"


class NameKind(str, Enum):
    ISSUER_NAME = "ISSUER_NAME"
    SECURITY_NAME = "SECURITY_NAME"


class NameLanguage(str, Enum):
    JA = "JA"
    EN = "EN"


class ListingVenue(str, Enum):
    TSE = "TSE"


class ListingEndReason(str, Enum):
    DELISTED = "DELISTED"


class CoverageScope(str, Enum):
    JP_LISTED_EQUITY_IDENTITY = "JP_LISTED_EQUITY_IDENTITY"


#: 識別子の値の形（scheme ごと。英字を含む code を許す。数として扱わない）
IDENTIFIER_PATTERNS: Mapping[IdentifierScheme, "re.Pattern[str]"] = {
    IdentifierScheme.JQUANTS_CODE: re.compile(r"^[0-9A-Z]{5}$"),
    IdentifierScheme.LOCAL_CODE: re.compile(r"^[0-9A-Z]{4}$"),
}
NAME_KIND_FOR_SUBJECT: Mapping[SubjectKind, NameKind] = {SubjectKind.ISSUER: NameKind.ISSUER_NAME,
                                                         SubjectKind.SECURITY: NameKind.SECURITY_NAME}

_ALL_SOURCES = frozenset(SourceClass)
#: record の種類ごとに authority を持てる出所（契約 §15。出所の優先順位の heuristic は持たない）
ALLOWED_SOURCE_CLASSES: Mapping[RecordKind, FrozenSet[SourceClass]] = {
    RecordKind.ISSUER_REGISTRATION: frozenset({SourceClass.OFFICIAL_EXCHANGE, SourceClass.ISSUER_DISCLOSURE,
                                               SourceClass.HUMAN_REVIEWED}),
    RecordKind.SECURITY_REGISTRATION: frozenset({SourceClass.OFFICIAL_EXCHANGE, SourceClass.ISSUER_DISCLOSURE,
                                                 SourceClass.HUMAN_REVIEWED}),
    RecordKind.IDENTIFIER_ASSIGNMENT: _ALL_SOURCES,
    RecordKind.IDENTIFIER_RETIREMENT: _ALL_SOURCES,
    RecordKind.DISPLAY_NAME: _ALL_SOURCES,
    RecordKind.LISTING_START: _ALL_SOURCES,
    RecordKind.LISTING_END: _ALL_SOURCES,
    RecordKind.COVERAGE: frozenset({SourceClass.OFFICIAL_EXCHANGE, SourceClass.JQUANTS, SourceClass.HUMAN_REVIEWED}),
}
#: 同じ Security の 2 本目の識別子（code の変更）と再上場の継続を立てられる出所（J-Quants は継続を示せない）
CONTINUITY_SOURCE_CLASSES: FrozenSet[SourceClass] = frozenset({SourceClass.OFFICIAL_EXCHANGE,
                                                               SourceClass.ISSUER_DISCLOSURE,
                                                               SourceClass.HUMAN_REVIEWED})


# ---------------------------------------------------------------- 値の検査


def _enum(value: Any, enum_type, field_name: str):
    if isinstance(value, enum_type):
        return value
    raise IdentityModelError("INVALID_VOCABULARY", field_name)


def _parse_enum(value: Any, enum_type, field_name: str):
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        raise IdentityModelError("INVALID_VOCABULARY", field_name) from None


def _aware(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_DATETIME", field_name)
    _require(value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None, "NAIVE_DATETIME", field_name)
    return value


def _parse_datetime(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, str), "INVALID_DATETIME", field_name)
    try:
        return from_iso(value)
    except ValueError:
        raise IdentityModelError("INVALID_DATETIME", field_name) from None


def _no_credential_marker(value: str, field_name: str) -> None:
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)


def _check_id(value: Any, prefix: str, field_name: str) -> str:
    _require(isinstance(value, str) and bool(_ID_RE[prefix].match(value)), "INVALID_ID", field_name)
    return value


def _check_anchor(value: Any, field_name: str) -> str:
    _require(isinstance(value, str) and bool(_ANCHOR_RE.match(value)), "INVALID_ANCHOR", field_name)
    _no_credential_marker(value, field_name)
    return value


def _check_name(value: Any, field_name: str) -> str:
    _require(isinstance(value, str) and 0 < len(value) <= MAX_NAME_LEN, "INVALID_NAME", field_name)
    _require(value == value.strip() and not _CONTROL_RE.search(value), "INVALID_NAME", field_name)
    _require("\\" not in value and "//" not in value, "INVALID_NAME", field_name)   # path ・URL の形を拒む
    return value


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def derive_issuer_id(registration_anchor: str) -> str:
    """IssuerId は anchor と実体の種類だけから導く（名前・code ・市場を入れない）。"""
    anchor = _check_anchor(registration_anchor, "registration_anchor")
    return content_id(ISSUER_ID_PREFIX, canonical_json({"anchor": anchor, "entity": SubjectKind.ISSUER.value}))


def derive_security_id(registration_anchor: str) -> str:
    """SecurityId は anchor と実体の種類だけから導く（code ・Issuer ・名前を入れない）。"""
    anchor = _check_anchor(registration_anchor, "registration_anchor")
    return content_id(SECURITY_ID_PREFIX, canonical_json({"anchor": anchor, "entity": SubjectKind.SECURITY.value}))


def is_issuer_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE[ISSUER_ID_PREFIX].match(value))


def is_security_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE[SECURITY_ID_PREFIX].match(value))


def _reject_unknown(data: Mapping[str, Any], allowed: Iterable[str], name: str) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", name)
    _require(set(data) <= set(allowed), "UNKNOWN_FIELD", name)
    _require(set(allowed) <= set(data), "MISSING_FIELD", name)


# ---------------------------------------------------------------- 出所


@dataclass(frozen=True, kw_only=True)
class SourceProvenance:
    """出所（閉じた class ・参照 ・既知の時刻）。raw の本文 ・path ・credential を持たない。"""

    source_class: SourceClass
    source_record_ref: str
    known_at: datetime

    def __post_init__(self) -> None:
        _enum(self.source_class, SourceClass, "source_class")
        _require(isinstance(self.source_record_ref, str) and bool(_SOURCE_REF_RE.match(self.source_record_ref)),
                 "INVALID_SOURCE_REF", "source_record_ref")
        _no_credential_marker(self.source_record_ref, "source_record_ref")
        _aware(self.known_at, "known_at")

    def as_dict(self) -> Dict[str, Any]:
        return {"known_at": to_utc_iso(self.known_at), "source_class": self.source_class.value,
                "source_record_ref": self.source_record_ref}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceProvenance":
        _reject_unknown(data, ("known_at", "source_class", "source_record_ref"), "provenance")
        return cls(source_class=_parse_enum(data["source_class"], SourceClass, "source_class"),
                   source_record_ref=data["source_record_ref"],
                   known_at=_parse_datetime(data["known_at"], "known_at"))


# ---------------------------------------------------------------- record


class _Record:
    """record の共通部（不変・内容 address）。本体の field は各 subclass の `_payload` が決める。"""

    KIND: ClassVar[RecordKind]
    AUTHORITY_CLASS: ClassVar[str] = AUTHORITATIVE_IDENTITY_RECORD
    provenance: SourceProvenance

    def _payload(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _check_provenance(self) -> None:
        _require(isinstance(self.provenance, SourceProvenance), "INVALID_PROVENANCE", "provenance")
        _require(self.provenance.source_class in ALLOWED_SOURCE_CLASSES[self.KIND], "SOURCE_CLASS_NOT_AUTHORIZED",
                 self.KIND.value)

    @property
    def known_at(self) -> datetime:
        return self.provenance.known_at

    def identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "record_kind": self.KIND.value, "payload": self._payload(),
                "provenance": self.provenance.as_dict()}

    @property
    def record_id(self) -> str:
        return content_id(RECORD_ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "record_id": self.record_id}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"


@dataclass(frozen=True, kw_only=True)
class IssuerRegistration(_Record):
    KIND: ClassVar[RecordKind] = RecordKind.ISSUER_REGISTRATION
    registration_anchor: str
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        _check_anchor(self.registration_anchor, "registration_anchor")
        self._check_provenance()

    @property
    def issuer_id(self) -> str:
        return derive_issuer_id(self.registration_anchor)

    def _payload(self) -> Dict[str, Any]:
        return {"issuer_id": self.issuer_id, "registration_anchor": self.registration_anchor}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: SourceProvenance) -> "IssuerRegistration":
        _reject_unknown(payload, ("issuer_id", "registration_anchor"), cls.KIND.value)
        record = cls(registration_anchor=payload["registration_anchor"], provenance=provenance)
        _require(payload["issuer_id"] == record.issuer_id, "ID_MISMATCH", "issuer_id")
        return record


@dataclass(frozen=True, kw_only=True)
class SecurityRegistration(_Record):
    KIND: ClassVar[RecordKind] = RecordKind.SECURITY_REGISTRATION
    registration_anchor: str
    issuer_id: str
    issue_class: IssueClass
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        _check_anchor(self.registration_anchor, "registration_anchor")
        _check_id(self.issuer_id, ISSUER_ID_PREFIX, "issuer_id")
        _enum(self.issue_class, IssueClass, "issue_class")
        self._check_provenance()

    @property
    def security_id(self) -> str:
        return derive_security_id(self.registration_anchor)

    def _payload(self) -> Dict[str, Any]:
        return {"issue_class": self.issue_class.value, "issuer_id": self.issuer_id,
                "registration_anchor": self.registration_anchor, "security_id": self.security_id}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: SourceProvenance) -> "SecurityRegistration":
        _reject_unknown(payload, ("issue_class", "issuer_id", "registration_anchor", "security_id"), cls.KIND.value)
        record = cls(registration_anchor=payload["registration_anchor"], issuer_id=payload["issuer_id"],
                     issue_class=_parse_enum(payload["issue_class"], IssueClass, "issue_class"), provenance=provenance)
        _require(payload["security_id"] == record.security_id, "ID_MISMATCH", "security_id")
        return record


@dataclass(frozen=True, kw_only=True)
class IdentifierAssignment(_Record):
    """外部の識別子の Security への割り当て（`effective_from` から。終わりは `IdentifierRetirement`）。"""

    KIND: ClassVar[RecordKind] = RecordKind.IDENTIFIER_ASSIGNMENT
    security_id: str
    scheme: IdentifierScheme
    value: str
    effective_from: datetime
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        _check_id(self.security_id, SECURITY_ID_PREFIX, "security_id")
        _enum(self.scheme, IdentifierScheme, "scheme")
        _require(isinstance(self.value, str) and bool(IDENTIFIER_PATTERNS[self.scheme].match(self.value)),
                 "INVALID_IDENTIFIER", "value")
        _aware(self.effective_from, "effective_from")
        self._check_provenance()

    def _payload(self) -> Dict[str, Any]:
        return {"effective_from": to_utc_iso(self.effective_from), "scheme": self.scheme.value,
                "security_id": self.security_id, "value": self.value}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: SourceProvenance) -> "IdentifierAssignment":
        _reject_unknown(payload, ("effective_from", "scheme", "security_id", "value"), cls.KIND.value)
        return cls(security_id=payload["security_id"],
                   scheme=_parse_enum(payload["scheme"], IdentifierScheme, "scheme"), value=payload["value"],
                   effective_from=_parse_datetime(payload["effective_from"], "effective_from"), provenance=provenance)


@dataclass(frozen=True, kw_only=True)
class IdentifierRetirement(_Record):
    """割り当ての終わり（`effective_to` は排他。1 つの割り当てに 1 つだけ）。"""

    KIND: ClassVar[RecordKind] = RecordKind.IDENTIFIER_RETIREMENT
    assignment_record_id: str
    effective_to: datetime
    reason: RetirementReason
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        _check_id(self.assignment_record_id, RECORD_ID_PREFIX, "assignment_record_id")
        _aware(self.effective_to, "effective_to")
        _enum(self.reason, RetirementReason, "reason")
        self._check_provenance()

    def _payload(self) -> Dict[str, Any]:
        return {"assignment_record_id": self.assignment_record_id, "effective_to": to_utc_iso(self.effective_to),
                "reason": self.reason.value}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: SourceProvenance) -> "IdentifierRetirement":
        _reject_unknown(payload, ("assignment_record_id", "effective_to", "reason"), cls.KIND.value)
        return cls(assignment_record_id=payload["assignment_record_id"],
                   effective_to=_parse_datetime(payload["effective_to"], "effective_to"),
                   reason=_parse_enum(payload["reason"], RetirementReason, "reason"), provenance=provenance)


@dataclass(frozen=True, kw_only=True)
class DisplayName(_Record):
    """表示の名前（identity ではない。名前の変更は新しい record で、id を変えない）。"""

    KIND: ClassVar[RecordKind] = RecordKind.DISPLAY_NAME
    subject_kind: SubjectKind
    subject_id: str
    name_kind: NameKind
    language: NameLanguage
    value: str
    effective_from: datetime
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        _enum(self.subject_kind, SubjectKind, "subject_kind")
        prefix = ISSUER_ID_PREFIX if self.subject_kind is SubjectKind.ISSUER else SECURITY_ID_PREFIX
        _check_id(self.subject_id, prefix, "subject_id")
        _enum(self.name_kind, NameKind, "name_kind")
        _require(NAME_KIND_FOR_SUBJECT[self.subject_kind] is self.name_kind, "INVALID_VOCABULARY", "name_kind")
        _enum(self.language, NameLanguage, "language")
        _check_name(self.value, "value")
        _aware(self.effective_from, "effective_from")
        self._check_provenance()

    def _payload(self) -> Dict[str, Any]:
        return {"effective_from": to_utc_iso(self.effective_from), "language": self.language.value,
                "name_kind": self.name_kind.value, "subject_id": self.subject_id,
                "subject_kind": self.subject_kind.value, "value": self.value}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: SourceProvenance) -> "DisplayName":
        _reject_unknown(payload, ("effective_from", "language", "name_kind", "subject_id", "subject_kind", "value"),
                        cls.KIND.value)
        return cls(subject_kind=_parse_enum(payload["subject_kind"], SubjectKind, "subject_kind"),
                   subject_id=payload["subject_id"],
                   name_kind=_parse_enum(payload["name_kind"], NameKind, "name_kind"),
                   language=_parse_enum(payload["language"], NameLanguage, "language"), value=payload["value"],
                   effective_from=_parse_datetime(payload["effective_from"], "effective_from"), provenance=provenance)


@dataclass(frozen=True, kw_only=True)
class ListingStart(_Record):
    KIND: ClassVar[RecordKind] = RecordKind.LISTING_START
    security_id: str
    venue: ListingVenue
    effective_from: datetime
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        _check_id(self.security_id, SECURITY_ID_PREFIX, "security_id")
        _enum(self.venue, ListingVenue, "venue")
        _aware(self.effective_from, "effective_from")
        self._check_provenance()

    def _payload(self) -> Dict[str, Any]:
        return {"effective_from": to_utc_iso(self.effective_from), "security_id": self.security_id,
                "venue": self.venue.value}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: SourceProvenance) -> "ListingStart":
        _reject_unknown(payload, ("effective_from", "security_id", "venue"), cls.KIND.value)
        return cls(security_id=payload["security_id"], venue=_parse_enum(payload["venue"], ListingVenue, "venue"),
                   effective_from=_parse_datetime(payload["effective_from"], "effective_from"), provenance=provenance)


@dataclass(frozen=True, kw_only=True)
class ListingEnd(_Record):
    """上場の終わり（identity を消さない。`effective_to` は排他。1 つの上場に 1 つだけ）。"""

    KIND: ClassVar[RecordKind] = RecordKind.LISTING_END
    listing_record_id: str
    effective_to: datetime
    reason: ListingEndReason
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        _check_id(self.listing_record_id, RECORD_ID_PREFIX, "listing_record_id")
        _aware(self.effective_to, "effective_to")
        _enum(self.reason, ListingEndReason, "reason")
        self._check_provenance()

    def _payload(self) -> Dict[str, Any]:
        return {"effective_to": to_utc_iso(self.effective_to), "listing_record_id": self.listing_record_id,
                "reason": self.reason.value}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: SourceProvenance) -> "ListingEnd":
        _reject_unknown(payload, ("effective_to", "listing_record_id", "reason"), cls.KIND.value)
        return cls(listing_record_id=payload["listing_record_id"],
                   effective_to=_parse_datetime(payload["effective_to"], "effective_to"),
                   reason=_parse_enum(payload["reason"], ListingEndReason, "reason"), provenance=provenance)


@dataclass(frozen=True, kw_only=True)
class Coverage(_Record):
    """authority が完全だと宣言する有効時間の範囲 `[effective_from, effective_to)`（上限は必須。開いた範囲を認めない）。"""

    KIND: ClassVar[RecordKind] = RecordKind.COVERAGE
    scope: CoverageScope
    effective_from: datetime
    effective_to: datetime
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        _enum(self.scope, CoverageScope, "scope")
        _aware(self.effective_from, "effective_from")
        _aware(self.effective_to, "effective_to")
        _require(self.effective_from < self.effective_to, "INVALID_INTERVAL", "coverage")
        self._check_provenance()

    def covers(self, instant: datetime) -> bool:
        return self.effective_from <= instant < self.effective_to

    def _payload(self) -> Dict[str, Any]:
        return {"effective_from": to_utc_iso(self.effective_from), "effective_to": to_utc_iso(self.effective_to),
                "scope": self.scope.value}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: SourceProvenance) -> "Coverage":
        _reject_unknown(payload, ("effective_from", "effective_to", "scope"), cls.KIND.value)
        return cls(scope=_parse_enum(payload["scope"], CoverageScope, "scope"),
                   effective_from=_parse_datetime(payload["effective_from"], "effective_from"),
                   effective_to=_parse_datetime(payload["effective_to"], "effective_to"), provenance=provenance)


RECORD_TYPES: Mapping[RecordKind, type] = {cls.KIND: cls for cls in (
    IssuerRegistration, SecurityRegistration, IdentifierAssignment, IdentifierRetirement, DisplayName, ListingStart,
    ListingEnd, Coverage)}
IDENTITY_RECORD_TYPES: Tuple[type, ...] = tuple(RECORD_TYPES.values())


def is_identity_record(value: Any) -> bool:
    return type(value) in IDENTITY_RECORD_TYPES


def parse_identity_record(data: Mapping[str, Any]):
    """直列化された 1 record を検査して復元する（未知の field ・版 ・id の不一致を拒む）。"""
    _reject_unknown(data, ("payload", "provenance", "record_id", "record_kind", "schema_version"), "record")
    _require(data["schema_version"] == SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", "schema_version")
    kind = _parse_enum(data["record_kind"], RecordKind, "record_kind")
    provenance = SourceProvenance.from_dict(data["provenance"])
    _require(isinstance(data["payload"], Mapping), "INVALID_RECORD", "payload")
    record = RECORD_TYPES[kind]._from_payload(data["payload"], provenance)
    _require(data["record_id"] == record.record_id, "ID_MISMATCH", "record_id")
    return record


def parse_canonical_line(line: str):
    """1 行を復元し、それが record の正準の直列化と byte 一致することを確かめる。"""
    try:
        data = json.loads(line)
    except ValueError:
        raise IdentityModelError("MALFORMED_JSON", "line") from None
    _require(isinstance(data, dict), "NOT_AN_OBJECT", "line")
    record = parse_identity_record(data)
    _require(record.canonical_line() == line, "NON_CANONICAL_LINE", "line")
    return record


# ---------------------------------------------------------------- 履歴（順序つきの不変条件）


def _overlaps_open_from(start: datetime, end: Optional[datetime], new_start: datetime) -> bool:
    """既存の `[start, end)`（end=None は開いた範囲）と、新しい開いた範囲 `[new_start, ∞)` が重なるか。"""
    return end is None or end > new_start or start >= new_start


class IdentityHistory:
    """append 順の record 列に履歴の不変条件を適用した、検証済みの authority の像。

    - `known_at` は append 順に非減少（過去の知識を後から差し込めない）。
    - 参照先（Issuer ・Security ・割り当て ・上場）は先に知られていなければならない。
    - 同じ識別子の値の割り当ては、どの Security についても有効期間が重ならない。1 つの Security は scheme ごとに
      同時に 1 つの識別子しか持たない。上場の期間も重ならない。終わりの record は 1 つの対象に 1 つだけ（分岐なし）。
    - 同じ Security の 2 本目の識別子（code の変更）と再上場には、継続を立てられる出所が要る。
    - 同じ id の別の登録は衝突（自動の統合をしない）。byte 一致の同じ record は収束する（何もしない）。
    """

    def __init__(self, records: Iterable[Any] = ()) -> None:
        self._records: List[Any] = []
        self._record_ids: Dict[str, Any] = {}
        self.issuers: Dict[str, IssuerRegistration] = {}
        self.securities: Dict[str, SecurityRegistration] = {}
        self.assignments: Dict[str, IdentifierAssignment] = {}
        self.retirements: Dict[str, IdentifierRetirement] = {}
        self.names: List[DisplayName] = []
        self.listings: Dict[str, ListingStart] = {}
        self.listing_ends: Dict[str, ListingEnd] = {}
        self.coverages: List[Coverage] = []
        self._last_known_at: Optional[datetime] = None
        for record in records:
            self.add(record)

    @property
    def records(self) -> Tuple[Any, ...]:
        return tuple(self._records)

    def contains(self, record_id: str) -> bool:
        return record_id in self._record_ids

    def add(self, record: Any) -> bool:
        """検査して加える。byte 一致の同じ record なら何もしない（False）。"""
        if is_identity_record(record) and record.record_id in self._record_ids:
            return False
        self.check(record)
        self._apply(record)
        return True

    # ------------------------------------------------------------ 検査（状態を変えない）

    def check(self, record: Any) -> None:
        if not is_identity_record(record):
            raise IdentityHistoryError("INVALID_TYPE", "not an identity record")
        if self._last_known_at is not None and record.known_at < self._last_known_at:
            raise IdentityHistoryError("NON_MONOTONIC_KNOWN_AT", record.KIND.value)
        checkers = {RecordKind.ISSUER_REGISTRATION: self._check_issuer_registration,
                    RecordKind.SECURITY_REGISTRATION: self._check_security_registration,
                    RecordKind.IDENTIFIER_ASSIGNMENT: self._check_identifier_assignment,
                    RecordKind.IDENTIFIER_RETIREMENT: self._check_identifier_retirement,
                    RecordKind.DISPLAY_NAME: self._check_display_name,
                    RecordKind.LISTING_START: self._check_listing_start,
                    RecordKind.LISTING_END: self._check_listing_end,
                    RecordKind.COVERAGE: self._check_coverage}
        checkers[record.KIND](record)

    def _check_issuer_registration(self, record: IssuerRegistration) -> None:
        if record.issuer_id in self.issuers:
            raise IdentityHistoryError("REGISTRATION_CONFLICT", "issuer_id")

    def _check_security_registration(self, record: SecurityRegistration) -> None:
        if record.security_id in self.securities:
            raise IdentityHistoryError("REGISTRATION_CONFLICT", "security_id")
        if record.issuer_id not in self.issuers:
            raise IdentityHistoryError("UNKNOWN_ISSUER", "issuer_id")

    def _check_identifier_assignment(self, record: IdentifierAssignment) -> None:
        if record.security_id not in self.securities:
            raise IdentityHistoryError("UNKNOWN_SECURITY", "security_id")
        prior_same_security = False
        for rid, existing in self.assignments.items():
            if existing.scheme is not record.scheme:
                continue
            same_value = existing.value == record.value
            same_security = existing.security_id == record.security_id
            if not (same_value or same_security):
                continue
            end = self.retirements[rid].effective_to if rid in self.retirements else None
            if _overlaps_open_from(existing.effective_from, end, record.effective_from):
                raise IdentityHistoryError("CONFLICTING_ASSIGNMENT", record.scheme.value)
            prior_same_security = prior_same_security or same_security
        if prior_same_security and record.provenance.source_class not in CONTINUITY_SOURCE_CLASSES:
            raise IdentityHistoryError("CONTINUITY_NOT_AUTHORIZED", "identifier change")

    def _check_identifier_retirement(self, record: IdentifierRetirement) -> None:
        assignment = self.assignments.get(record.assignment_record_id)
        if assignment is None:
            raise IdentityHistoryError("UNKNOWN_ASSIGNMENT", "assignment_record_id")
        if record.assignment_record_id in self.retirements:
            raise IdentityHistoryError("DUPLICATE_RETIREMENT", "assignment_record_id")
        if record.effective_to <= assignment.effective_from:
            raise IdentityHistoryError("INVALID_INTERVAL", "retirement")

    def _check_display_name(self, record: DisplayName) -> None:
        known = self.issuers if record.subject_kind is SubjectKind.ISSUER else self.securities
        if record.subject_id not in known:
            raise IdentityHistoryError("UNKNOWN_SUBJECT", record.subject_kind.value)
        for existing in self.names:
            if (existing.subject_id, existing.name_kind, existing.language, existing.effective_from) == (
                    record.subject_id, record.name_kind, record.language, record.effective_from) \
                    and existing.value != record.value:
                raise IdentityHistoryError("CONFLICTING_NAME", "same subject, kind, language and effective_from")

    def _check_listing_start(self, record: ListingStart) -> None:
        if record.security_id not in self.securities:
            raise IdentityHistoryError("UNKNOWN_SECURITY", "security_id")
        prior = False
        for rid, existing in self.listings.items():
            if existing.security_id != record.security_id:
                continue
            end = self.listing_ends[rid].effective_to if rid in self.listing_ends else None
            if _overlaps_open_from(existing.effective_from, end, record.effective_from):
                raise IdentityHistoryError("OVERLAPPING_LISTING", "security_id")
            prior = True
        if prior and record.provenance.source_class not in CONTINUITY_SOURCE_CLASSES:
            raise IdentityHistoryError("CONTINUITY_NOT_AUTHORIZED", "relisting")

    def _check_listing_end(self, record: ListingEnd) -> None:
        listing = self.listings.get(record.listing_record_id)
        if listing is None:
            raise IdentityHistoryError("UNKNOWN_LISTING", "listing_record_id")
        if record.listing_record_id in self.listing_ends:
            raise IdentityHistoryError("DUPLICATE_LISTING_END", "listing_record_id")
        if record.effective_to <= listing.effective_from:
            raise IdentityHistoryError("INVALID_INTERVAL", "listing end")

    def _check_coverage(self, record: Coverage) -> None:
        return None

    # ------------------------------------------------------------ 適用

    def _apply(self, record: Any) -> None:
        self._records.append(record)
        self._record_ids[record.record_id] = record
        self._last_known_at = record.known_at
        kind = record.KIND
        if kind is RecordKind.ISSUER_REGISTRATION:
            self.issuers[record.issuer_id] = record
        elif kind is RecordKind.SECURITY_REGISTRATION:
            self.securities[record.security_id] = record
        elif kind is RecordKind.IDENTIFIER_ASSIGNMENT:
            self.assignments[record.record_id] = record
        elif kind is RecordKind.IDENTIFIER_RETIREMENT:
            self.retirements[record.assignment_record_id] = record
        elif kind is RecordKind.DISPLAY_NAME:
            self.names.append(record)
        elif kind is RecordKind.LISTING_START:
            self.listings[record.record_id] = record
        elif kind is RecordKind.LISTING_END:
            self.listing_ends[record.listing_record_id] = record
        else:
            self.coverages.append(record)

    def known_by(self, cutoff: datetime) -> "IdentityHistory":
        """`known_at <= cutoff` の record だけの像（`known_at` は非減少なので append 順の接頭辞）。"""
        return IdentityHistory(r for r in self._records if r.known_at <= cutoff)


__all__ = ["ALLOWED_SOURCE_CLASSES", "AUTHORITATIVE_IDENTITY_RECORD", "AUTHORITY_RULES_VERSION",
           "CONTINUITY_SOURCE_CLASSES", "CREDENTIAL_MARKERS", "Coverage", "CoverageScope", "DisplayName",
           "IDENTIFIER_PATTERNS", "IDENTITY_RECORD_TYPES", "ISSUER_ID_PREFIX", "IdentifierAssignment",
           "IdentifierRetirement", "IdentifierScheme", "IdentityHistory", "IdentityHistoryError",
           "IdentityModelError", "IssueClass", "IssuerRegistration", "ListingEnd", "ListingEndReason",
           "ListingStart", "ListingVenue", "MAX_NAME_LEN", "NAME_KIND_FOR_SUBJECT", "NameKind", "NameLanguage",
           "RECORD_ID_PREFIX", "RECORD_TYPES", "RecordKind", "RetirementReason", "SCHEMA_VERSION",
           "SECURITY_ID_PREFIX", "SecurityRegistration", "SourceClass", "SourceProvenance", "SubjectKind",
           "canonical_json", "derive_issuer_id", "derive_security_id", "is_identity_record", "is_issuer_id",
           "is_security_id", "parse_canonical_line", "parse_identity_record"]
