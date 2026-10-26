"""P6-B5B — Theme relation authority の不変 record model（純）。

2 つの record 型だけを持つ（B5-D5）。

- `ThemeRelationAssertion`: Theme root どうしの意味論的主張。訂正は `previous_assertion_id` の chain で表す。
- `ThemeRelationGovernanceEvent`: 主張そのものではない行為（RETRACTED / RESTORED）。撤回を主張の改訂として表さない。

規律:

- 語彙は CAUSES / AMPLIFIES / MITIGATES / DEPENDS_ON の 4 型だけ（B5-D2）。すべて有向で、逆辺 record は作らない。
- authority になれる主張 class は HUMAN_ASSERTED / SOURCE_ASSERTED の 2 つだけ（B5-D3）。rule / LLM の値は存在しない。
- SOURCE_ASSERTED は「引用した出典がその関係を主張した」ことの記録であり、系がその因果を検証したという意味ではない。
- CAUSES は両 class とも evidence 参照を必須にする（B5-D8）。
- identity は内容から決まる（content id）。provenance と recorded_at は identity の外（ただし canonical bytes には入る）。
- Foundation の root は所有しない。root id を参照するだけで、ThemeRootRecord を複製しない。
- Theme の資格判定・独立 source 数・score・順位付けは持たない。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware, from_iso
from ..themes.model import (REF_ID_PREFIX_BY_KIND, EvidenceKind, ProvenanceClass, SourceOrigin, canonical_json,
                            is_root_id, normalize_text)

RELATION_ASSERTION_SCHEMA_VERSION = "theme_relation_assertion:0.1.0"
RELATION_GOVERNANCE_SCHEMA_VERSION = "theme_relation_governance:0.1.0"
RELATION_VOCAB_VERSION = "theme_relation_vocabulary:0.1.0"
ASSERTION_ID_PREFIX = "threl"
GOVERNANCE_ID_PREFIX = "thrgov"
EDGE_KEY_SEPARATOR = "|"
EDGE_KEY_SEGMENTS = 5
MAX_TEXT_LEN = 240
MAX_REF_LEN = 200
MAX_LOCATOR_LEN = 500

_ID_RE = {ASSERTION_ID_PREFIX: re.compile(r"^threl_[0-9a-f]{24}$"),
          GOVERNANCE_ID_PREFIX: re.compile(r"^thrgov_[0-9a-f]{24}$")}
_USERINFO_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@")
_SECRET_QUERY_RE = re.compile(r"(?i)[?&](api[_-]?key|access[_-]?token|secret|signature|sig|password)=")
_DRIVE_PATH_RE = re.compile(r"(?:^|[\s\"'(\[])[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\")


class RelationModelError(ValueError):
    """fail closed。code は安定した語彙、detail は短い説明（本文・秘密値を含めない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _fail(code: str, detail: str = "") -> None:
    raise RelationModelError(code, detail)


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        _fail(code, detail)


def _text(value: object, name: str, *, max_len: int, required: bool = False) -> str:
    _require(isinstance(value, str), "INVALID_TYPE", f"{name} must be str")
    text = str(value)
    if required:
        _require(text != "", "MISSING_FIELD", f"{name} is required")
    _require(len(text) <= max_len, "FIELD_TOO_LONG", f"{name} exceeds {max_len} characters")
    _require("\n" not in text and "\r" not in text, "INVALID_TEXT", f"{name} must be single-line")
    if text and (_USERINFO_URL_RE.search(text) or _SECRET_QUERY_RE.search(text) or _DRIVE_PATH_RE.search(text)
                 or _UNC_PATH_RE.search(text)):
        _fail("PROHIBITED_CONTENT", f"{name} carries a credential-bearing URL or a machine specific path")
    return text


def _enum(value: object, enum_type, name: str):
    _require(isinstance(value, enum_type), "INVALID_TYPE", f"{name} must be {enum_type.__name__}")
    return value


def _parse_enum(value: object, enum_type, name: str):
    try:
        return enum_type(value)
    except ValueError:
        _fail("INVALID_VOCABULARY", f"{name}: unknown {enum_type.__name__} value {value!r}")


def _aware(value: object, name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_TYPE", f"{name} must be datetime")
    try:
        return ensure_aware(value, name)
    except Exception:
        _fail("INVALID_TIME", f"{name} must be an aware datetime")


def _plain(value) -> object:
    return json.loads(canonical_json(value))


def _is_record_id(value: object, prefix: str) -> bool:
    return isinstance(value, str) and bool(_ID_RE[prefix].match(value))


def _str(data: Mapping[str, object], key: str, default: Optional[str] = None) -> str:
    value = data.get(key, default)
    _require(isinstance(value, str), "INVALID_TYPE", f"{key} must be str")
    return str(value)


def _reject_unknown(data: Mapping[str, object], allowed: Sequence[str]) -> None:
    unknown = sorted(set(data) - set(allowed))
    _require(not unknown, "UNKNOWN_FIELD", f"unknown fields {unknown}")


# ---------------------------------------------------------------- 語彙（B5-D2 / B5-D3）


class RelationType(str, Enum):
    """MVP の関係語彙。すべて有向（A → B）。対称型も階層型も持たない。"""

    CAUSES = "CAUSES"
    AMPLIFIES = "AMPLIFIES"
    MITIGATES = "MITIGATES"
    DEPENDS_ON = "DEPENDS_ON"


class AssertionClass(str, Enum):
    """authority になれる主張 class。rule / LLM の値は意図的に存在しない。"""

    HUMAN_ASSERTED = "HUMAN_ASSERTED"
    SOURCE_ASSERTED = "SOURCE_ASSERTED"


class RelationGovernanceEventType(str, Enum):
    RETRACTED = "RETRACTED"
    RESTORED = "RESTORED"


#: evidence 参照を必須にする関係型（B5-D8）。両 assertion class に適用する
EVIDENCE_REQUIRED_TYPES: Tuple[RelationType, ...] = (RelationType.CAUSES,)
#: SOURCE_ASSERTED の意味（contract / test で凍結する文言）
SOURCE_ASSERTED_MEANING = "the cited source asserted this relation"
#: SOURCE_ASSERTED が意味しないこと
SOURCE_ASSERTED_NON_MEANING = "the system verified this relation as causal truth"


# ---------------------------------------------------------------- 補助 record


@dataclass(frozen=True, kw_only=True)
class RelationProvenance:
    """記録者。authority record は人間だけが作れる（rule / LLM は作れない）。"""

    actor_class: ProvenanceClass = ProvenanceClass.HUMAN
    actor_ref: str

    def __post_init__(self) -> None:
        _enum(self.actor_class, ProvenanceClass, "RelationProvenance.actor_class")
        _require(self.actor_class is ProvenanceClass.HUMAN, "FORBIDDEN_ASSERTION_AUTHORITY",
                 "relation authority records are recorded by a person")
        object.__setattr__(self, "actor_ref", _text(self.actor_ref, "actor_ref", max_len=MAX_REF_LEN, required=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "RelationProvenance":
        _reject_unknown(data, ("actor_class", "actor_ref"))
        return cls(actor_class=_parse_enum(data.get("actor_class"), ProvenanceClass, "actor_class"),
                   actor_ref=_str(data, "actor_ref"))


@dataclass(frozen=True, kw_only=True)
class SourceAttribution:
    """SOURCE_ASSERTED の帰属。「誰がその関係を主張したか」。仮名 / 機関 ref を置き、個人識別情報を置かない。"""

    attributed_to: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributed_to", _text(self.attributed_to, "attributed_to", max_len=MAX_REF_LEN,
                                                        required=True))

    @property
    def attribution_key(self) -> str:
        return normalize_text(self.attributed_to)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SourceAttribution":
        _reject_unknown(data, ("attributed_to",))
        return cls(attributed_to=_str(data, "attributed_to"))


@dataclass(frozen=True, kw_only=True)
class RelationEvidenceRef:
    """関係の主張を支える参照。Theme の資格 evidence ではない（件数を数えない・独立性を主張しない）。"""

    evidence_kind: EvidenceKind
    ref_id: str
    source_origin: SourceOrigin
    evidence_time: Optional[datetime] = None
    locator: str = ""
    attribution: str = ""

    def __post_init__(self) -> None:
        kind = _enum(self.evidence_kind, EvidenceKind, "RelationEvidenceRef.evidence_kind")
        ref_id = _text(self.ref_id, "ref_id", max_len=MAX_REF_LEN, required=True)
        prefix = REF_ID_PREFIX_BY_KIND[kind]
        _require(ref_id.startswith(prefix), "REF_ID_KIND_MISMATCH", f"{kind.value} ref_id must start with {prefix!r}")
        object.__setattr__(self, "ref_id", ref_id)
        _require(isinstance(self.source_origin, SourceOrigin), "INVALID_TYPE", "source_origin must be SourceOrigin")
        if self.evidence_time is not None:
            object.__setattr__(self, "evidence_time", _aware(self.evidence_time, "evidence_time"))
        object.__setattr__(self, "locator", _text(self.locator, "locator", max_len=MAX_LOCATOR_LEN))
        object.__setattr__(self, "attribution", _text(self.attribution, "attribution", max_len=MAX_REF_LEN))

    @property
    def evidence_key(self) -> str:
        return f"{self.evidence_kind.value}:{self.ref_id}"

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "RelationEvidenceRef":
        _reject_unknown(data, ("evidence_kind", "ref_id", "source_origin", "evidence_time", "locator", "attribution"))
        raw_time = data.get("evidence_time")
        return cls(evidence_kind=_parse_enum(data.get("evidence_kind"), EvidenceKind, "evidence_kind"),
                   ref_id=_str(data, "ref_id"), source_origin=SourceOrigin.from_dict(data.get("source_origin") or {}),
                   evidence_time=from_iso(raw_time) if isinstance(raw_time, str) and raw_time else None,
                   locator=_str(data, "locator", ""), attribution=_str(data, "attribution", ""))


# ---------------------------------------------------------------- 辺 key（derived。record id ではない）


def edge_key_of(source_theme_root_id: str, target_theme_root_id: str, relation_type: RelationType,
                assertion_class: AssertionClass, attribution_key: str = "") -> str:
    """同じ意味論的関係の履歴に属する assertion 群をまとめる derived key（authority record id ではない）。"""
    return EDGE_KEY_SEPARATOR.join((source_theme_root_id, target_theme_root_id, relation_type.value,
                                    assertion_class.value, attribution_key))


def split_edge_key(edge_key: str) -> Tuple[str, str, RelationType, AssertionClass, str]:
    parts = str(edge_key).split(EDGE_KEY_SEPARATOR)
    _require(len(parts) == EDGE_KEY_SEGMENTS, "INVALID_EDGE_KEY", "edge key must carry five segments")
    return (parts[0], parts[1], _parse_enum(parts[2], RelationType, "relation_type"),
            _parse_enum(parts[3], AssertionClass, "assertion_class"), parts[4])


# ---------------------------------------------------------------- assertion


ASSERTION_FIELDS = ("schema_version", "relation_vocab_version", "relation_assertion_id", "source_theme_root_id",
                    "target_theme_root_id", "relation_type", "assertion_class", "source_attribution", "rationale",
                    "evidence_refs", "previous_assertion_id", "provenance", "recorded_at")


@dataclass(frozen=True, kw_only=True)
class ThemeRelationAssertion:
    """Theme root どうしの意味論的関係の不変な主張。Foundation authority ではない。"""

    schema_version: str = RELATION_ASSERTION_SCHEMA_VERSION
    relation_vocab_version: str = RELATION_VOCAB_VERSION
    relation_assertion_id: str
    source_theme_root_id: str
    target_theme_root_id: str
    relation_type: RelationType
    assertion_class: AssertionClass
    source_attribution: Optional[SourceAttribution] = None
    rationale: str
    evidence_refs: Tuple[RelationEvidenceRef, ...] = ()
    previous_assertion_id: str = ""
    provenance: RelationProvenance
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == RELATION_ASSERTION_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version)
        _require(self.relation_vocab_version == RELATION_VOCAB_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.relation_vocab_version)
        for name in ("source_theme_root_id", "target_theme_root_id"):
            _require(is_root_id(getattr(self, name)), "UNKNOWN_THEME_ROOT", f"{name} must be a Theme root id")
        _require(self.source_theme_root_id != self.target_theme_root_id, "SELF_RELATION",
                 "a relation connects two distinct Theme roots")
        relation_type = _enum(self.relation_type, RelationType, "relation_type")
        assertion_class = _enum(self.assertion_class, AssertionClass, "assertion_class")
        if assertion_class is AssertionClass.SOURCE_ASSERTED:
            _require(isinstance(self.source_attribution, SourceAttribution), "MISSING_SOURCE_ATTRIBUTION",
                     "a source asserted relation must name the source that asserted it")
        else:
            _require(self.source_attribution is None, "ATTRIBUTION_FORBIDDEN",
                     "a human asserted relation carries no source attribution")
        object.__setattr__(self, "rationale", _text(self.rationale, "rationale", max_len=MAX_TEXT_LEN, required=True))
        _require(isinstance(self.evidence_refs, tuple) and all(isinstance(e, RelationEvidenceRef) for e in self.evidence_refs),
                 "INVALID_TYPE", "evidence_refs must be a tuple of RelationEvidenceRef")
        keys = [e.evidence_key for e in self.evidence_refs]
        _require(len(keys) == len(set(keys)), "DUPLICATE_EVIDENCE_REF", "an evidence item appears at most once")
        object.__setattr__(self, "evidence_refs", tuple(sorted(self.evidence_refs, key=canonical_json)))
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))
        for evidence in self.evidence_refs:
            if evidence.evidence_time is not None:
                _require(evidence.evidence_time <= self.recorded_at, "EVIDENCE_AFTER_RECORD",
                         "evidence_time must not be later than recorded_at")
        if relation_type in EVIDENCE_REQUIRED_TYPES:
            _require(len(self.evidence_refs) >= 1, "MISSING_CAUSAL_EVIDENCE",
                     f"{relation_type.value} requires at least one evidence reference")
        if assertion_class is AssertionClass.SOURCE_ASSERTED:
            _require(len(self.evidence_refs) >= 1, "MISSING_SOURCE_CITATION",
                     "a source asserted relation must cite where the source asserted it")
        object.__setattr__(self, "previous_assertion_id", _text(self.previous_assertion_id, "previous_assertion_id",
                                                                max_len=MAX_REF_LEN))
        _require(self.previous_assertion_id == "" or _is_record_id(self.previous_assertion_id, ASSERTION_ID_PREFIX),
                 "INVALID_RECORD_ID", "previous_assertion_id")
        _require(self.previous_assertion_id != self.relation_assertion_id, "INVALID_RECORD",
                 "an assertion cannot supersede itself")
        _require(isinstance(self.provenance, RelationProvenance), "INVALID_TYPE", "provenance must be RelationProvenance")
        _require(self.relation_assertion_id == _assertion_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "relation_assertion_id does not match the assertion content")

    @classmethod
    def build(cls, *, source_theme_root_id: str, target_theme_root_id: str, relation_type: RelationType,
              assertion_class: AssertionClass, rationale: str, source_attribution: Optional[SourceAttribution] = None,
              evidence_refs: Sequence[RelationEvidenceRef] = (), previous_assertion_id: str = "",
              provenance: RelationProvenance, recorded_at: datetime) -> "ThemeRelationAssertion":
        shell = object.__new__(cls)
        values = dict(schema_version=RELATION_ASSERTION_SCHEMA_VERSION, relation_vocab_version=RELATION_VOCAB_VERSION,
                      source_theme_root_id=source_theme_root_id, target_theme_root_id=target_theme_root_id,
                      relation_type=relation_type, assertion_class=assertion_class, source_attribution=source_attribution,
                      rationale=rationale, evidence_refs=tuple(sorted(evidence_refs, key=canonical_json)),
                      previous_assertion_id=previous_assertion_id)
        for name, value in values.items():
            object.__setattr__(shell, name, value)
        identity = ThemeRelationAssertion.identity_payload(shell)
        return cls(relation_assertion_id=_assertion_id(identity), provenance=provenance, recorded_at=recorded_at,
                   **values)

    def identity_payload(self) -> Dict[str, object]:
        """意味論的 identity の材料。provenance と recorded_at は含まない（canonical bytes には残る）。"""
        return {
            "schema_version": self.schema_version, "relation_vocab_version": self.relation_vocab_version,
            "source_theme_root_id": self.source_theme_root_id, "target_theme_root_id": self.target_theme_root_id,
            "relation_type": self.relation_type.value, "assertion_class": self.assertion_class.value,
            "source_attribution": _plain(self.source_attribution) if self.source_attribution is not None else None,
            "rationale": self.rationale, "evidence_refs": [_plain(e) for e in self.evidence_refs],
            "previous_assertion_id": self.previous_assertion_id,
        }

    @property
    def edge_key(self) -> str:
        attribution = self.source_attribution.attribution_key if self.source_attribution is not None else ""
        return edge_key_of(self.source_theme_root_id, self.target_theme_root_id, self.relation_type,
                           self.assertion_class, attribution)

    def as_dict(self) -> Dict[str, object]:
        return _plain(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeRelationAssertion":
        _reject_unknown(data, ASSERTION_FIELDS)
        attribution = data.get("source_attribution")
        refs = data.get("evidence_refs") or ()
        _require(isinstance(refs, (list, tuple)), "INVALID_TYPE", "evidence_refs must be a list")
        return cls(schema_version=_str(data, "schema_version"), relation_vocab_version=_str(data, "relation_vocab_version"),
                   relation_assertion_id=_str(data, "relation_assertion_id"),
                   source_theme_root_id=_str(data, "source_theme_root_id"),
                   target_theme_root_id=_str(data, "target_theme_root_id"),
                   relation_type=_parse_enum(data.get("relation_type"), RelationType, "relation_type"),
                   assertion_class=_parse_enum(data.get("assertion_class"), AssertionClass, "assertion_class"),
                   source_attribution=SourceAttribution.from_dict(attribution) if isinstance(attribution, dict) else None,
                   rationale=_str(data, "rationale"),
                   evidence_refs=tuple(RelationEvidenceRef.from_dict(r) for r in refs),
                   previous_assertion_id=_str(data, "previous_assertion_id", ""),
                   provenance=RelationProvenance.from_dict(data.get("provenance") or {}),
                   recorded_at=from_iso(_str(data, "recorded_at")))


# ---------------------------------------------------------------- governance event


GOVERNANCE_FIELDS = ("schema_version", "event_id", "event_type", "edge_key", "subject_assertion_id",
                     "previous_event_id", "reason", "provenance", "recorded_at")


@dataclass(frozen=True, kw_only=True)
class ThemeRelationGovernanceEvent:
    """主張そのものではない行為の不変 record。履歴を消さない（RETRACTED は削除ではない）。"""

    schema_version: str = RELATION_GOVERNANCE_SCHEMA_VERSION
    event_id: str
    event_type: RelationGovernanceEventType
    edge_key: str
    subject_assertion_id: str
    previous_event_id: str = ""
    reason: str
    provenance: RelationProvenance
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == RELATION_GOVERNANCE_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version)
        _enum(self.event_type, RelationGovernanceEventType, "event_type")
        object.__setattr__(self, "edge_key", _text(self.edge_key, "edge_key", max_len=MAX_REF_LEN * 3, required=True))
        split_edge_key(self.edge_key)
        _require(_is_record_id(self.subject_assertion_id, ASSERTION_ID_PREFIX), "INVALID_RECORD_ID", "subject_assertion_id")
        object.__setattr__(self, "previous_event_id", _text(self.previous_event_id, "previous_event_id", max_len=MAX_REF_LEN))
        _require(self.previous_event_id == "" or _is_record_id(self.previous_event_id, GOVERNANCE_ID_PREFIX),
                 "INVALID_RECORD_ID", "previous_event_id")
        _require(self.previous_event_id != self.event_id, "INVALID_RECORD", "an event cannot supersede itself")
        object.__setattr__(self, "reason", _text(self.reason, "reason", max_len=MAX_TEXT_LEN, required=True))
        _require(isinstance(self.provenance, RelationProvenance), "INVALID_TYPE", "provenance must be RelationProvenance")
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))
        _require(self.event_id == _governance_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "event_id does not match the event content")

    @classmethod
    def build(cls, *, event_type: RelationGovernanceEventType, edge_key: str, subject_assertion_id: str,
              reason: str, previous_event_id: str = "", provenance: RelationProvenance,
              recorded_at: datetime) -> "ThemeRelationGovernanceEvent":
        shell = object.__new__(cls)
        values = dict(schema_version=RELATION_GOVERNANCE_SCHEMA_VERSION, event_type=event_type, edge_key=edge_key,
                      subject_assertion_id=subject_assertion_id, previous_event_id=previous_event_id, reason=reason)
        for name, value in values.items():
            object.__setattr__(shell, name, value)
        identity = ThemeRelationGovernanceEvent.identity_payload(shell)
        return cls(event_id=_governance_id(identity), provenance=provenance, recorded_at=recorded_at, **values)

    def identity_payload(self) -> Dict[str, object]:
        return {"schema_version": self.schema_version, "event_type": self.event_type.value, "edge_key": self.edge_key,
                "subject_assertion_id": self.subject_assertion_id, "previous_event_id": self.previous_event_id,
                "reason": self.reason}

    def as_dict(self) -> Dict[str, object]:
        return _plain(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeRelationGovernanceEvent":
        _reject_unknown(data, GOVERNANCE_FIELDS)
        return cls(schema_version=_str(data, "schema_version"), event_id=_str(data, "event_id"),
                   event_type=_parse_enum(data.get("event_type"), RelationGovernanceEventType, "event_type"),
                   edge_key=_str(data, "edge_key"), subject_assertion_id=_str(data, "subject_assertion_id"),
                   previous_event_id=_str(data, "previous_event_id", ""), reason=_str(data, "reason"),
                   provenance=RelationProvenance.from_dict(data.get("provenance") or {}),
                   recorded_at=from_iso(_str(data, "recorded_at")))


# ---------------------------------------------------------------- identity / 直列化


def _assertion_id(payload: Mapping[str, object]) -> str:
    return content_id(ASSERTION_ID_PREFIX, canonical_json(payload))


def _governance_id(payload: Mapping[str, object]) -> str:
    return content_id(GOVERNANCE_ID_PREFIX, canonical_json(payload))


def canonical_relation_line(record) -> str:
    """store が append する bytes の定義（canonical JSON ＋ 改行）。"""
    return canonical_json(record.as_dict()) + "\n"


def parse_relation_record(payload: Mapping[str, object]):
    """schema_version で record 型を決める（推測しない）。"""
    _require(isinstance(payload, Mapping), "INVALID_TYPE", "record must be a mapping")
    schema = payload.get("schema_version")
    if schema == RELATION_ASSERTION_SCHEMA_VERSION:
        return ThemeRelationAssertion.from_dict(payload)
    if schema == RELATION_GOVERNANCE_SCHEMA_VERSION:
        return ThemeRelationGovernanceEvent.from_dict(payload)
    _fail("UNSUPPORTED_SCHEMA_VERSION", f"unknown relation schema {schema!r}")


__all__ = ["ASSERTION_ID_PREFIX", "AssertionClass", "EDGE_KEY_SEPARATOR", "EVIDENCE_REQUIRED_TYPES",
           "GOVERNANCE_ID_PREFIX", "RELATION_ASSERTION_SCHEMA_VERSION", "RELATION_GOVERNANCE_SCHEMA_VERSION",
           "RELATION_VOCAB_VERSION", "RelationEvidenceRef", "RelationGovernanceEventType", "RelationModelError",
           "RelationProvenance", "RelationType", "SOURCE_ASSERTED_MEANING", "SOURCE_ASSERTED_NON_MEANING",
           "SourceAttribution", "ThemeRelationAssertion", "ThemeRelationGovernanceEvent", "canonical_relation_line",
           "edge_key_of", "parse_relation_record", "split_edge_key"]
