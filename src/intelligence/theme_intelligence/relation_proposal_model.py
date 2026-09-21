"""P6-B5C — relation の提案と人間の決定の不変 record model（純）。

`RelationProposal` は **authority ではない**。`RelationProposalDecision` の ACCEPT も authority ではない。
B5B の `ThemeRelationAssertion` を書けるのは、将来の明示的な実行 gate だけである。

- 提案 type は `RELATION_CANDIDATE` の 1 つだけ。relation_type は field であり、型ごとに提案種別を増やさない。
- 提案者 class（HUMAN / SOURCE / RULE / LLM）は「誰が提案したか」であり、**authority の主張 class ではない**。
  B5B の主張 class は HUMAN_ASSERTED / SOURCE_ASSERTED のままで、RULE / LLM に相当する値は存在しない。
- 提案 identity は「候補となる主張そのもの」を表す。発見機構（提案者）は identity の外に置く。
  ただし出典の帰属は意味を変えるので identity に入る（出典 X の主張 ≠ 出典 Y の主張）。
- 決定の actor は人間だけ。自動 ACCEPT は無い。ACCEPT は最終的な主張 authority を明示する。
- score / 確信度 / 順位 / 確率 / 強度は持たない。
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
from ..themes.model import ProvenanceClass, canonical_json, is_root_id
from .relation_model import (ASSERTION_ID_PREFIX, AssertionClass, RELATION_VOCAB_VERSION, RelationEvidenceRef,
                             RelationType, SourceAttribution)

RELATION_PROPOSAL_SCHEMA_VERSION = "theme_relation_proposal:0.1.0"
RELATION_DECISION_SCHEMA_VERSION = "theme_relation_proposal_decision:0.1.0"
PROPOSAL_ID_PREFIX = "threlprop"
DECISION_ID_PREFIX = "threldec"
MAX_TEXT_LEN = 240
MAX_REF_LEN = 200

_ID_RE = {PROPOSAL_ID_PREFIX: re.compile(r"^threlprop_[0-9a-f]{24}$"),
          DECISION_ID_PREFIX: re.compile(r"^threldec_[0-9a-f]{24}$"),
          ASSERTION_ID_PREFIX: re.compile(r"^threl_[0-9a-f]{24}$")}
_USERINFO_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@")
_SECRET_QUERY_RE = re.compile(r"(?i)[?&](api[_-]?key|access[_-]?token|secret|signature|sig|password)=")
_DRIVE_PATH_RE = re.compile(r"(?:^|[\s\"'(\[])[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\")


class RelationProposalError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _fail(code: str, detail: str = "") -> None:
    raise RelationProposalError(code, detail)


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


def _is_id(value: object, prefix: str) -> bool:
    return isinstance(value, str) and bool(_ID_RE[prefix].match(value))


def _str(data: Mapping[str, object], key: str, default: Optional[str] = None) -> str:
    value = data.get(key, default)
    _require(isinstance(value, str), "INVALID_TYPE", f"{key} must be str")
    return str(value)


def _reject_unknown(data: Mapping[str, object], allowed: Sequence[str]) -> None:
    unknown = sorted(set(data) - set(allowed))
    _require(not unknown, "UNKNOWN_FIELD", f"unknown fields {unknown}")


# ---------------------------------------------------------------- 語彙


class RelationProposalType(str, Enum):
    RELATION_CANDIDATE = "RELATION_CANDIDATE"


class RelationProposerClass(str, Enum):
    """誰が提案したか。authority の主張 class ではない。"""

    HUMAN = "HUMAN"
    SOURCE = "SOURCE"
    RULE = "RULE"
    LLM = "LLM"


class RelationChangeKind(str, Enum):
    NEW_RELATION = "NEW_RELATION"
    CORRECTION = "CORRECTION"


class RelationDecisionKind(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"


#: ACCEPT が指定できる最終 authority（B5B の語彙そのまま。増やさない）
ACCEPTABLE_ASSERTION_CLASSES: Tuple[AssertionClass, ...] = (AssertionClass.HUMAN_ASSERTED, AssertionClass.SOURCE_ASSERTED)
#: 提案者 class と authority の主張 class は別物であることを凍結する文言
PROPOSER_IS_NOT_AUTHORITY = "a proposer class describes who proposed, not who asserts"


@dataclass(frozen=True, kw_only=True)
class RelationProposalProvenance:
    """提案の出自。ACCEPT 後も plan に残り、authority と混同されない。"""

    proposer_class: RelationProposerClass
    proposer_ref: str
    rule_version: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        _enum(self.proposer_class, RelationProposerClass, "proposer_class")
        object.__setattr__(self, "proposer_ref", _text(self.proposer_ref, "proposer_ref", max_len=MAX_REF_LEN,
                                                       required=True))
        object.__setattr__(self, "rule_version", _text(self.rule_version, "rule_version", max_len=MAX_REF_LEN))
        object.__setattr__(self, "note", _text(self.note, "note", max_len=MAX_TEXT_LEN))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "RelationProposalProvenance":
        _reject_unknown(data, ("proposer_class", "proposer_ref", "rule_version", "note"))
        return cls(proposer_class=_parse_enum(data.get("proposer_class"), RelationProposerClass, "proposer_class"),
                   proposer_ref=_str(data, "proposer_ref"), rule_version=_str(data, "rule_version", ""),
                   note=_str(data, "note", ""))


# ---------------------------------------------------------------- proposal


PROPOSAL_FIELDS = ("schema_version", "proposal_type", "relation_vocab_version", "proposal_id",
                   "source_theme_root_id", "target_theme_root_id", "relation_type", "change_kind",
                   "previous_assertion_id", "source_attribution", "rationale", "evidence_refs", "provenance",
                   "created_at")


@dataclass(frozen=True, kw_only=True)
class RelationProposal:
    """関係の候補。authority ではない。人間の ACCEPT があってはじめて plan になりうる。"""

    schema_version: str = RELATION_PROPOSAL_SCHEMA_VERSION
    proposal_type: RelationProposalType = RelationProposalType.RELATION_CANDIDATE
    relation_vocab_version: str = RELATION_VOCAB_VERSION
    proposal_id: str
    source_theme_root_id: str
    target_theme_root_id: str
    relation_type: RelationType
    change_kind: RelationChangeKind = RelationChangeKind.NEW_RELATION
    previous_assertion_id: str = ""
    source_attribution: Optional[SourceAttribution] = None
    rationale: str
    evidence_refs: Tuple[RelationEvidenceRef, ...] = ()
    provenance: RelationProposalProvenance
    created_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == RELATION_PROPOSAL_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version)
        _require(self.relation_vocab_version == RELATION_VOCAB_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 self.relation_vocab_version)
        _enum(self.proposal_type, RelationProposalType, "proposal_type")
        for name in ("source_theme_root_id", "target_theme_root_id"):
            _require(is_root_id(getattr(self, name)), "UNKNOWN_THEME_ROOT", f"{name} must be a Theme root id")
        _require(self.source_theme_root_id != self.target_theme_root_id, "SELF_RELATION",
                 "a relation candidate connects two distinct Theme roots")
        _enum(self.relation_type, RelationType, "relation_type")
        change_kind = _enum(self.change_kind, RelationChangeKind, "change_kind")
        object.__setattr__(self, "previous_assertion_id", _text(self.previous_assertion_id, "previous_assertion_id",
                                                                max_len=MAX_REF_LEN))
        if change_kind is RelationChangeKind.CORRECTION:
            _require(_is_id(self.previous_assertion_id, ASSERTION_ID_PREFIX), "MISSING_PREDECESSOR",
                     "a correction names the assertion it corrects")
        else:
            _require(self.previous_assertion_id == "", "PREDECESSOR_FORBIDDEN",
                     "a new relation candidate has no predecessor assertion")
        _require(isinstance(self.provenance, RelationProposalProvenance), "INVALID_TYPE",
                 "provenance must be RelationProposalProvenance")
        object.__setattr__(self, "rationale", _text(self.rationale, "rationale", max_len=MAX_TEXT_LEN, required=True))
        _require(isinstance(self.evidence_refs, tuple) and all(isinstance(e, RelationEvidenceRef) for e in self.evidence_refs),
                 "INVALID_TYPE", "evidence_refs must be a tuple of RelationEvidenceRef")
        keys = [e.evidence_key for e in self.evidence_refs]
        _require(len(keys) == len(set(keys)), "DUPLICATE_EVIDENCE_REF", "an evidence item appears at most once")
        object.__setattr__(self, "evidence_refs", tuple(sorted(self.evidence_refs, key=canonical_json)))
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        for item in self.evidence_refs:
            if item.evidence_time is not None:
                _require(item.evidence_time <= self.created_at, "EVIDENCE_AFTER_RECORD",
                         "evidence_time must not be later than created_at")
        if self.source_attribution is not None:
            _require(isinstance(self.source_attribution, SourceAttribution), "INVALID_TYPE",
                     "source_attribution must be SourceAttribution")
        if self.provenance.proposer_class is RelationProposerClass.SOURCE:
            _require(self.source_attribution is not None, "MISSING_SOURCE_ATTRIBUTION",
                     "a source proposal names the source that asserted the relation")
            _require(len(self.evidence_refs) >= 1, "MISSING_SOURCE_CITATION",
                     "a source proposal cites where the source asserted it")
        _require(self.proposal_id == _proposal_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "proposal_id does not match the candidate content")

    @classmethod
    def build(cls, *, source_theme_root_id: str, target_theme_root_id: str, relation_type: RelationType,
              rationale: str, provenance: RelationProposalProvenance, created_at: datetime,
              change_kind: RelationChangeKind = RelationChangeKind.NEW_RELATION, previous_assertion_id: str = "",
              source_attribution: Optional[SourceAttribution] = None,
              evidence_refs: Sequence[RelationEvidenceRef] = ()) -> "RelationProposal":
        shell = object.__new__(cls)
        values = dict(schema_version=RELATION_PROPOSAL_SCHEMA_VERSION,
                      proposal_type=RelationProposalType.RELATION_CANDIDATE,
                      relation_vocab_version=RELATION_VOCAB_VERSION, source_theme_root_id=source_theme_root_id,
                      target_theme_root_id=target_theme_root_id, relation_type=relation_type, change_kind=change_kind,
                      previous_assertion_id=previous_assertion_id, source_attribution=source_attribution,
                      rationale=rationale, evidence_refs=tuple(sorted(evidence_refs, key=canonical_json)))
        for name, value in values.items():
            object.__setattr__(shell, name, value)
        return cls(proposal_id=_proposal_id(RelationProposal.identity_payload(shell)), provenance=provenance,
                   created_at=created_at, **values)

    def identity_payload(self) -> Dict[str, object]:
        """候補となる主張そのもの。提案者（発見機構）と created_at は含まない。出典の帰属は意味を変えるので含む。"""
        return {
            "schema_version": self.schema_version, "proposal_type": self.proposal_type.value,
            "relation_vocab_version": self.relation_vocab_version,
            "source_theme_root_id": self.source_theme_root_id, "target_theme_root_id": self.target_theme_root_id,
            "relation_type": self.relation_type.value, "change_kind": self.change_kind.value,
            "previous_assertion_id": self.previous_assertion_id,
            "source_attribution": _plain(self.source_attribution) if self.source_attribution is not None else None,
            "rationale": self.rationale, "evidence_refs": [_plain(e) for e in self.evidence_refs],
        }

    def as_dict(self) -> Dict[str, object]:
        return _plain(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "RelationProposal":
        _reject_unknown(data, PROPOSAL_FIELDS)
        attribution = data.get("source_attribution")
        refs = data.get("evidence_refs") or ()
        _require(isinstance(refs, (list, tuple)), "INVALID_TYPE", "evidence_refs must be a list")
        return cls(schema_version=_str(data, "schema_version"),
                   proposal_type=_parse_enum(data.get("proposal_type"), RelationProposalType, "proposal_type"),
                   relation_vocab_version=_str(data, "relation_vocab_version"), proposal_id=_str(data, "proposal_id"),
                   source_theme_root_id=_str(data, "source_theme_root_id"),
                   target_theme_root_id=_str(data, "target_theme_root_id"),
                   relation_type=_parse_enum(data.get("relation_type"), RelationType, "relation_type"),
                   change_kind=_parse_enum(data.get("change_kind"), RelationChangeKind, "change_kind"),
                   previous_assertion_id=_str(data, "previous_assertion_id", ""),
                   source_attribution=SourceAttribution.from_dict(attribution) if isinstance(attribution, dict) else None,
                   rationale=_str(data, "rationale"),
                   evidence_refs=tuple(RelationEvidenceRef.from_dict(r) for r in refs),
                   provenance=RelationProposalProvenance.from_dict(data.get("provenance") or {}),
                   created_at=from_iso(_str(data, "created_at")))


# ---------------------------------------------------------------- decision


DECISION_FIELDS = ("schema_version", "decision_id", "proposal_id", "decision", "accepted_assertion_class",
                   "actor_class", "actor_ref", "reason", "supersedes_decision_id", "recorded_at")


@dataclass(frozen=True, kw_only=True)
class RelationProposalDecision:
    """人間の決定。自動 ACCEPT は無く、ACCEPT は最終的な主張 authority を明示する。"""

    schema_version: str = RELATION_DECISION_SCHEMA_VERSION
    decision_id: str
    proposal_id: str
    decision: RelationDecisionKind
    accepted_assertion_class: Optional[AssertionClass] = None
    actor_class: ProvenanceClass = ProvenanceClass.HUMAN
    actor_ref: str
    reason: str
    supersedes_decision_id: str = ""
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == RELATION_DECISION_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version)
        _require(_is_id(self.proposal_id, PROPOSAL_ID_PREFIX), "INVALID_RECORD_ID", "proposal_id")
        decision = _enum(self.decision, RelationDecisionKind, "decision")
        _enum(self.actor_class, ProvenanceClass, "actor_class")
        _require(self.actor_class is ProvenanceClass.HUMAN, "FORBIDDEN_DECISION_AUTHORITY",
                 "relation proposal decisions are made by a person")
        if decision is RelationDecisionKind.ACCEPT:
            _require(self.accepted_assertion_class in ACCEPTABLE_ASSERTION_CLASSES, "MISSING_ACCEPTED_AUTHORITY",
                     "an acceptance names the final assertion authority")
        else:
            _require(self.accepted_assertion_class is None, "ACCEPTED_AUTHORITY_FORBIDDEN",
                     "only an acceptance names a final assertion authority")
        object.__setattr__(self, "actor_ref", _text(self.actor_ref, "actor_ref", max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "reason", _text(self.reason, "reason", max_len=MAX_TEXT_LEN, required=True))
        object.__setattr__(self, "supersedes_decision_id", _text(self.supersedes_decision_id, "supersedes_decision_id",
                                                                 max_len=MAX_REF_LEN))
        _require(self.supersedes_decision_id == "" or _is_id(self.supersedes_decision_id, DECISION_ID_PREFIX),
                 "INVALID_RECORD_ID", "supersedes_decision_id")
        _require(self.supersedes_decision_id != self.decision_id, "INVALID_RECORD", "a decision cannot supersede itself")
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))
        _require(self.decision_id == _decision_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "decision_id does not match the decision content")

    @classmethod
    def build(cls, *, proposal_id: str, decision: RelationDecisionKind, actor_ref: str, reason: str,
              recorded_at: datetime, accepted_assertion_class: Optional[AssertionClass] = None,
              supersedes_decision_id: str = "") -> "RelationProposalDecision":
        shell = object.__new__(cls)
        values = dict(schema_version=RELATION_DECISION_SCHEMA_VERSION, proposal_id=proposal_id, decision=decision,
                      accepted_assertion_class=accepted_assertion_class, actor_class=ProvenanceClass.HUMAN,
                      actor_ref=actor_ref, reason=reason, supersedes_decision_id=supersedes_decision_id)
        for name, value in values.items():
            object.__setattr__(shell, name, value)
        return cls(decision_id=_decision_id(RelationProposalDecision.identity_payload(shell)), recorded_at=recorded_at,
                   **values)

    def identity_payload(self) -> Dict[str, object]:
        return {"schema_version": self.schema_version, "proposal_id": self.proposal_id, "decision": self.decision.value,
                "accepted_assertion_class": (self.accepted_assertion_class.value
                                             if self.accepted_assertion_class is not None else None),
                "actor_class": self.actor_class.value, "actor_ref": self.actor_ref, "reason": self.reason,
                "supersedes_decision_id": self.supersedes_decision_id}

    def as_dict(self) -> Dict[str, object]:
        return _plain(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "RelationProposalDecision":
        _reject_unknown(data, DECISION_FIELDS)
        accepted = data.get("accepted_assertion_class")
        return cls(schema_version=_str(data, "schema_version"), decision_id=_str(data, "decision_id"),
                   proposal_id=_str(data, "proposal_id"),
                   decision=_parse_enum(data.get("decision"), RelationDecisionKind, "decision"),
                   accepted_assertion_class=(_parse_enum(accepted, AssertionClass, "accepted_assertion_class")
                                             if accepted is not None else None),
                   actor_class=_parse_enum(data.get("actor_class"), ProvenanceClass, "actor_class"),
                   actor_ref=_str(data, "actor_ref"), reason=_str(data, "reason"),
                   supersedes_decision_id=_str(data, "supersedes_decision_id", ""),
                   recorded_at=from_iso(_str(data, "recorded_at")))


# ---------------------------------------------------------------- identity / 直列化


def _proposal_id(payload: Mapping[str, object]) -> str:
    return content_id(PROPOSAL_ID_PREFIX, canonical_json(payload))


def _decision_id(payload: Mapping[str, object]) -> str:
    return content_id(DECISION_ID_PREFIX, canonical_json(payload))


def canonical_proposal_record_line(record) -> str:
    return canonical_json(record.as_dict()) + "\n"


def parse_proposal_record(payload: Mapping[str, object]):
    _require(isinstance(payload, Mapping), "INVALID_TYPE", "record must be a mapping")
    schema = payload.get("schema_version")
    if schema == RELATION_PROPOSAL_SCHEMA_VERSION:
        return RelationProposal.from_dict(payload)
    if schema == RELATION_DECISION_SCHEMA_VERSION:
        return RelationProposalDecision.from_dict(payload)
    _fail("UNSUPPORTED_SCHEMA_VERSION", f"unknown relation proposal schema {schema!r}")


def source_authority_available(proposal: RelationProposal) -> bool:
    """SOURCE_ASSERTED として受理できる材料が提案にあるか（提案者 class では代替できない）。"""
    return proposal.source_attribution is not None and len(proposal.evidence_refs) >= 1


__all__ = ["ACCEPTABLE_ASSERTION_CLASSES", "DECISION_ID_PREFIX", "PROPOSAL_ID_PREFIX", "PROPOSER_IS_NOT_AUTHORITY",
           "RELATION_DECISION_SCHEMA_VERSION", "RELATION_PROPOSAL_SCHEMA_VERSION", "RelationChangeKind",
           "RelationDecisionKind", "RelationProposal", "RelationProposalDecision", "RelationProposalError",
           "RelationProposalProvenance", "RelationProposalType", "RelationProposerClass",
           "canonical_proposal_record_line", "parse_proposal_record", "source_authority_available"]
