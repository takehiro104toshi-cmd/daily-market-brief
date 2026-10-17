"""Theme proposal / decision model（P6-B3）— Foundation とは別の append-only proposal authority の record 型。

- **Proposal ≠ Theme。** proposal が存在しても ThemeRootRecord / ThemeObservation / governance は作られない。
- 3 種の proposal（THEME_CANDIDATE / EVIDENCE_CANDIDATE / DEDUP_REVIEW）と ProposalDecision（HUMAN のみ）。
- id は content-addressed（`thprop_` / `thdec_`）。identity payload は proposal 種別・構造化内容・evidence 参照・dedup basis を
  含み、created_at / recorded_at / provenance（audit-only）を含めない。同 id ＋ 異 bytes は store で CONFLICT。
- Theme candidate は Foundation A1 / A2 の Theme 定義を満たす構造（主題・機構 4 component・確度 class・scope（PERIOD_FRAME
  ちょうど 1）・無効化条件 ≥ 1）を持つが、ThemeObservation そのものは保存しない。fingerprint は Foundation の純関数で
  proposal 内容から計算する（duck typing。observation と同じ材料 → 同じ値）。
- 全 datetime は aware UTC、caller 注入。現在時刻は呼ばない。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from enum import Enum
from typing import Dict, Mapping, Optional, Sequence, Tuple, Union

from ..core.ids import content_id
from ..core.time import ensure_aware, from_iso
from ..themes.fingerprint import identity_core_fingerprint, semantic_fingerprint
from ..themes.model import (REF_ID_PREFIX_BY_KIND, EvidenceAttachment, EvidenceKind, EvidenceRole, EvidenceTimeBasis,
                            EvidenceTimeQuality, InferredExposureLink, InvalidationCondition, Limitation, Mechanism,
                            MechanismCertainty, ScopeDimension, ScopeToken, SourceOrigin, ThemeSubject, canonical_json,
                            is_root_id, normalize_text)

PROPOSAL_SCHEMA_VERSION = "theme_proposal:0.1.0"
DECISION_SCHEMA_VERSION = "theme_proposal_decision:0.1.0"
DEDUP_MODEL_VERSION = "theme_dedup:0.1.0"
PROPOSAL_ID_PREFIX = "thprop"
DECISION_ID_PREFIX = "thdec"
MAX_TEXT_LEN = 240
MAX_REF_LEN = 200
MAX_NOTE_LEN = 500
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DRIVE_PATH_RE = re.compile(r"(?:^|[\s\"'(\[])[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\")
_USERINFO_URL_RE = re.compile(r"://[^/\s]*@")
_SECRET_QUERY_RE = re.compile(r"[?&](?:token|key|api_key|apikey|password|secret|signature|sig)=", re.IGNORECASE)
_CONTENT_ID_RE: Dict[str, "re.Pattern[str]"] = {}


def is_content_id(value: object, prefix: str) -> bool:
    """`<prefix>_<sha256 先頭 24 hex>`（core.ids.content_id の形式）。Foundation の validator は自 prefix しか知らないため独自に持つ。"""
    pattern = _CONTENT_ID_RE.get(prefix)
    if pattern is None:
        pattern = _CONTENT_ID_RE[prefix] = re.compile(rf"^{re.escape(prefix)}_[0-9a-f]{{24}}$")
    return isinstance(value, str) and bool(pattern.match(value))


class ProposalModelError(Exception):
    """record が契約を満たさない（fail closed）。"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def _fail(code: str, message: str = "") -> None:
    raise ProposalModelError(code, message)


def _require(condition: bool, code: str, message: str = "") -> None:
    if not condition:
        _fail(code, message)


class ProposalType(str, Enum):
    THEME_CANDIDATE = "THEME_CANDIDATE"
    EVIDENCE_CANDIDATE = "EVIDENCE_CANDIDATE"
    DEDUP_REVIEW = "DEDUP_REVIEW"


class ProposerClass(str, Enum):
    RULE = "RULE"
    HUMAN = "HUMAN"
    LLM_PROPOSAL = "LLM_PROPOSAL"      # 予約: reviewed でも evidence でも Theme authority でもない


class DecisionKind(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"
    NOT_DUPLICATE = "NOT_DUPLICATE"    # DEDUP_REVIEW にのみ許される


class DedupClass(str, Enum):
    EXACT_SEMANTIC_MATCH = "EXACT_SEMANTIC_MATCH"
    EXACT_IDENTITY_CORE_MATCH = "EXACT_IDENTITY_CORE_MATCH"
    SCOPE_VARIANT = "SCOPE_VARIANT"                    # 予約（B3 では自動分類しない）
    SUBJECT_VARIANT = "SUBJECT_VARIANT"                # 予約
    MECHANISM_VARIANT = "MECHANISM_VARIANT"            # 予約
    PARENT_CHILD_CANDIDATE = "PARENT_CHILD_CANDIDATE"  # 予約


#: B3 で自動（決定論・exact 比較）に生成してよい dedup class
AUTO_DEDUP_CLASSES: Tuple[DedupClass, ...] = (DedupClass.EXACT_SEMANTIC_MATCH, DedupClass.EXACT_IDENTITY_CORE_MATCH)


class ComparisonBasisKind(str, Enum):
    SEMANTIC_FINGERPRINT = "SEMANTIC_FINGERPRINT"
    IDENTITY_CORE_FINGERPRINT = "IDENTITY_CORE_FINGERPRINT"


class CounterpartKind(str, Enum):
    THEME_ROOT = "THEME_ROOT"
    THEME_PROPOSAL = "THEME_PROPOSAL"


#: proposal 種別ごとに許される decision
ALLOWED_DECISIONS: Mapping[ProposalType, Tuple[DecisionKind, ...]] = {
    ProposalType.THEME_CANDIDATE: (DecisionKind.ACCEPT, DecisionKind.REJECT, DecisionKind.DEFER),
    ProposalType.EVIDENCE_CANDIDATE: (DecisionKind.ACCEPT, DecisionKind.REJECT, DecisionKind.DEFER),
    ProposalType.DEDUP_REVIEW: (DecisionKind.ACCEPT, DecisionKind.REJECT, DecisionKind.DEFER, DecisionKind.NOT_DUPLICATE),
}


# ---------------------------------------------------------------- helpers

def _plain(value) -> object:
    """JSON 互換の決定論的値（Foundation の canonical JSON を経由）。"""
    return json.loads(canonical_json(value))


def _text(value: object, name: str, *, max_len: int, required: bool = False) -> str:
    _require(isinstance(value, str), "INVALID_TYPE", f"{name} must be str")
    text = str(value)
    if required:
        _require(text != "", "MISSING_FIELD", f"{name} is required")
    _require(len(text) <= max_len, "FIELD_TOO_LONG", f"{name} exceeds {max_len} characters")
    _require("\n" not in text and "\r" not in text, "INVALID_TEXT", f"{name} must be single-line")
    if text and (_USERINFO_URL_RE.search(text) or _SECRET_QUERY_RE.search(text) or _DRIVE_PATH_RE.search(text)
                 or _UNC_PATH_RE.search(text)):
        _fail("PROHIBITED_CONTENT", f"{name} contains a credential-bearing URL or machine-specific path")
    return text


def _enum(value: object, enum_type, name: str):
    _require(isinstance(value, enum_type), "INVALID_TYPE", f"{name} must be {enum_type.__name__}")
    return value


def _parse_enum(value: object, enum_type, name: str):
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        _fail("INVALID_VOCABULARY", f"{name}: {value!r} is not in {enum_type.__name__}")


def _aware(value: object, name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_TYPE", f"{name} must be datetime")
    try:
        return ensure_aware(value, name)
    except Exception as exc:   # core.time は naive を拒否する
        _fail("NAIVE_DATETIME", str(exc))
    return value


def _typed_tuple(values: object, item_type, name: str) -> tuple:
    _require(isinstance(values, (tuple, list, set, frozenset)) and all(isinstance(v, item_type) for v in values), "INVALID_TYPE",
             f"{name} must be a tuple of {item_type.__name__}")
    return tuple(sorted(values, key=canonical_json))


def _str(data: Mapping[str, object], key: str, default: Optional[str] = None) -> str:
    value = data.get(key, default)
    _require(isinstance(value, str), "INVALID_RECORD", f"{key} must be str")
    return value  # type: ignore[return-value]


def _reject_unknown(data: Mapping[str, object], cls) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", f"{cls.__name__} payload must be an object")
    unknown = set(data) - {f.name for f in fields(cls)}
    _require(not unknown, "UNKNOWN_FIELD", f"{cls.__name__}: unknown fields {sorted(unknown)}")


# ---------------------------------------------------------------- provenance（audit-only）

@dataclass(frozen=True)
class ProposalProvenance:
    proposer_class: ProposerClass
    proposer_ref: str                 # 仮名 / role id / rule id。個人識別情報を置かない
    rule_version: str = ""            # RULE / LLM_PROPOSAL のとき任意
    reason: str = ""

    def __post_init__(self) -> None:
        _enum(self.proposer_class, ProposerClass, "ProposalProvenance.proposer_class")
        object.__setattr__(self, "proposer_ref", _text(self.proposer_ref, "proposer_ref", max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "rule_version", _text(self.rule_version, "rule_version", max_len=MAX_REF_LEN))
        object.__setattr__(self, "reason", _text(self.reason, "reason", max_len=MAX_NOTE_LEN))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ProposalProvenance":
        _reject_unknown(data, cls)
        return cls(proposer_class=_parse_enum(data.get("proposer_class"), ProposerClass, "proposer_class"),
                   proposer_ref=_str(data, "proposer_ref"), rule_version=_str(data, "rule_version", ""),
                   reason=_str(data, "reason", ""))


# ---------------------------------------------------------------- THEME_CANDIDATE

@dataclass(frozen=True, kw_only=True)
class ThemeCandidateProposal:
    """Foundation の Theme 定義を満たす構造を持つ候補（A1 Q1〜Q3 / Q6 の形式要件を proposal 段階で検査する）。"""

    schema_version: str = PROPOSAL_SCHEMA_VERSION
    proposal_type: ProposalType = ProposalType.THEME_CANDIDATE
    proposal_id: str
    subject: ThemeSubject
    mechanism: Mechanism
    certainty_class: MechanismCertainty
    scope: Tuple[ScopeToken, ...]
    limitations: Tuple[Limitation, ...] = ()
    invalidation_conditions: Tuple[InvalidationCondition, ...]
    inferred_links: Tuple[InferredExposureLink, ...] = ()
    evidence_refs: Tuple[EvidenceAttachment, ...] = ()     # Foundation attachment snapshot。attached_at は提案時刻（audit）
    provenance: ProposalProvenance
    created_at: datetime
    semantic_fingerprint: str
    identity_core_fingerprint: str

    def __post_init__(self) -> None:
        _require(self.schema_version == PROPOSAL_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version)
        _require(self.proposal_type is ProposalType.THEME_CANDIDATE, "INVALID_TYPE", "proposal_type mismatch")
        _require(isinstance(self.subject, ThemeSubject), "INVALID_TYPE", "subject must be ThemeSubject")
        _require(isinstance(self.mechanism, Mechanism), "INVALID_TYPE", "mechanism must be Mechanism")
        _enum(self.certainty_class, MechanismCertainty, "certainty_class")
        object.__setattr__(self, "scope", _typed_tuple(set(self.scope), ScopeToken, "scope"))
        _require(len(self.scope) >= 1, "MISSING_SCOPE", "scope must be declared (A1 Q3)")
        frames = [s for s in self.scope if s.dimension is ScopeDimension.PERIOD_FRAME]
        _require(len(frames) == 1, "MISSING_SCOPE", "scope must declare exactly one PERIOD_FRAME token")
        object.__setattr__(self, "limitations", _typed_tuple(set(self.limitations), Limitation, "limitations"))
        object.__setattr__(self, "invalidation_conditions",
                           _typed_tuple(set(self.invalidation_conditions), InvalidationCondition, "invalidation_conditions"))
        _require(len(self.invalidation_conditions) >= 1, "MISSING_INVALIDATION_CONDITION",
                 "a Theme candidate without an invalidation condition is unfalsifiable (A1 Q6)")
        keys = [c.condition_key for c in self.invalidation_conditions]
        _require(len(keys) == len(set(keys)), "DUPLICATE_KEY", "condition keys must be unique")
        object.__setattr__(self, "inferred_links", _typed_tuple(set(self.inferred_links), InferredExposureLink, "inferred_links"))
        object.__setattr__(self, "evidence_refs", _typed_tuple(self.evidence_refs, EvidenceAttachment, "evidence_refs"))
        attachment_keys = [a.attachment_key for a in self.evidence_refs]
        _require(len(attachment_keys) == len(set(attachment_keys)), "DUPLICATE_ATTACHMENT",
                 "an evidence item appears at most once per (ref_id, consequence_ref)")
        consequence_keys = {c.component_key for c in self.mechanism.consequences}
        for a in self.evidence_refs:
            if a.role in (EvidenceRole.SUPPORTS, EvidenceRole.CONTRADICTS):
                _require(a.consequence_ref in consequence_keys, "UNKNOWN_CONSEQUENCE_REF",
                         f"{a.attachment_key}: consequence_ref must name an expected consequence")
            if a.role is EvidenceRole.INVALIDATES:
                _require(a.invalidation_condition_ref in keys, "UNKNOWN_INVALIDATION_CONDITION_REF",
                         f"{a.attachment_key}: invalidation_condition_ref must name a condition")
        _require(isinstance(self.provenance, ProposalProvenance), "INVALID_TYPE", "provenance must be ProposalProvenance")
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        _require(self.semantic_fingerprint == semantic_fingerprint(self), "FINGERPRINT_MISMATCH",
                 "semantic_fingerprint does not match the proposal content")
        _require(self.identity_core_fingerprint == identity_core_fingerprint(self), "FINGERPRINT_MISMATCH",
                 "identity_core_fingerprint does not match the proposal content")
        _require(self.proposal_id == _proposal_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "proposal_id does not match the proposal content")

    @classmethod
    def build(cls, *, subject: ThemeSubject, mechanism: Mechanism, certainty_class: MechanismCertainty,
              scope: Sequence[ScopeToken], invalidation_conditions: Sequence[InvalidationCondition],
              limitations: Sequence[Limitation] = (), inferred_links: Sequence[InferredExposureLink] = (),
              evidence_refs: Sequence[EvidenceAttachment] = (), provenance: ProposalProvenance,
              created_at: datetime) -> "ThemeCandidateProposal":
        return _build_candidate(cls, subject, mechanism, certainty_class, scope, invalidation_conditions, limitations,
                                inferred_links, evidence_refs, provenance, created_at)

    def identity_payload(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "proposal_type": self.proposal_type.value,
            "subject": _plain(self.subject), "mechanism": _plain(self.mechanism),
            "certainty_class": self.certainty_class.value, "scope": _plain(self.scope),
            "limitations": _plain(self.limitations), "invalidation_conditions": _plain(self.invalidation_conditions),
            "inferred_links": _plain(self.inferred_links),
            "evidence_refs": [_attachment_identity(a) for a in self.evidence_refs],
        }

    def as_dict(self) -> Dict[str, object]:
        return _plain(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeCandidateProposal":
        _reject_unknown(data, cls)
        return cls(
            schema_version=_str(data, "schema_version"), proposal_type=_parse_enum(data.get("proposal_type"), ProposalType, "proposal_type"),
            proposal_id=_str(data, "proposal_id"), subject=ThemeSubject.from_dict(data.get("subject") or {}),
            mechanism=Mechanism.from_dict(data.get("mechanism") or {}),
            certainty_class=_parse_enum(data.get("certainty_class"), MechanismCertainty, "certainty_class"),
            scope=tuple(ScopeToken.from_dict(s) for s in (data.get("scope") or ())),
            limitations=tuple(Limitation.from_dict(l) for l in (data.get("limitations") or ())),
            invalidation_conditions=tuple(InvalidationCondition.from_dict(c) for c in (data.get("invalidation_conditions") or ())),
            inferred_links=tuple(InferredExposureLink.from_dict(l) for l in (data.get("inferred_links") or ())),
            evidence_refs=tuple(EvidenceAttachment.from_dict(a) for a in (data.get("evidence_refs") or ())),
            provenance=ProposalProvenance.from_dict(data.get("provenance") or {}),
            created_at=from_iso(_str(data, "created_at")), semantic_fingerprint=_str(data, "semantic_fingerprint"),
            identity_core_fingerprint=_str(data, "identity_core_fingerprint"))


def _build_candidate(cls, subject, mechanism, certainty_class, scope, invalidation_conditions, limitations, inferred_links,
                     evidence_refs, provenance, created_at) -> "ThemeCandidateProposal":
    """fingerprint と id を内容から計算して構築する（__post_init__ が再計算して照合する）。"""
    class _Semantics:   # fingerprint 純関数の duck-typed 入力（subject / mechanism / scope）
        pass
    probe = _Semantics()
    probe.subject, probe.mechanism = subject, mechanism
    probe.scope = tuple(sorted(set(scope), key=canonical_json))
    _require(isinstance(subject, ThemeSubject) and isinstance(mechanism, Mechanism), "INVALID_TYPE", "subject / mechanism")
    sem, core = semantic_fingerprint(probe), identity_core_fingerprint(probe)
    shell = object.__new__(cls)
    payload_source = dict(
        schema_version=PROPOSAL_SCHEMA_VERSION, proposal_type=ProposalType.THEME_CANDIDATE, subject=subject,
        mechanism=mechanism, certainty_class=certainty_class, scope=probe.scope,
        limitations=tuple(sorted(set(limitations), key=canonical_json)),
        invalidation_conditions=tuple(sorted(set(invalidation_conditions), key=canonical_json)),
        inferred_links=tuple(sorted(set(inferred_links), key=canonical_json)),
        evidence_refs=tuple(sorted(evidence_refs, key=canonical_json)))
    for name, value in payload_source.items():
        object.__setattr__(shell, name, value)
    proposal_id = _proposal_id(ThemeCandidateProposal.identity_payload(shell))
    return cls(proposal_id=proposal_id, subject=subject, mechanism=mechanism, certainty_class=certainty_class,
               scope=tuple(scope), limitations=tuple(limitations), invalidation_conditions=tuple(invalidation_conditions),
               inferred_links=tuple(inferred_links), evidence_refs=tuple(evidence_refs), provenance=provenance,
               created_at=created_at, semantic_fingerprint=sem, identity_core_fingerprint=core)


def _attachment_identity(a: EvidenceAttachment) -> Dict[str, object]:
    """attachment の identity 材料（attached_at は audit-only なので除外）。"""
    payload = _plain(a)
    payload.pop("attached_at", None)   # type: ignore[union-attr]
    return payload  # type: ignore[return-value]


def _proposal_id(payload: Mapping[str, object]) -> str:
    return content_id(PROPOSAL_ID_PREFIX, canonical_json(payload))


# ---------------------------------------------------------------- EVIDENCE_CANDIDATE

@dataclass(frozen=True, kw_only=True)
class EvidenceCandidateProposal:
    """まだ機構へ結びつけられない観測候補。THEME_CANDIDATE への昇格は新 proposal（target_proposal_id）で表す。"""

    schema_version: str = PROPOSAL_SCHEMA_VERSION
    proposal_type: ProposalType = ProposalType.EVIDENCE_CANDIDATE
    proposal_id: str
    evidence_kind: EvidenceKind
    ref_id: str
    source_origin: SourceOrigin
    evidence_time: Optional[datetime]
    evidence_time_basis: EvidenceTimeBasis
    evidence_time_quality: EvidenceTimeQuality
    evidence_date: str = ""
    proposed_role: EvidenceRole
    target_root_id: str = ""          # 既存 root への付与候補なら root id
    target_proposal_id: str = ""      # THEME_CANDIDATE proposal への付与候補なら proposal id
    reason: str                       # 構造化された短い理由（normalized）
    locator: str = ""
    note: str = ""
    provenance: ProposalProvenance
    created_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == PROPOSAL_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version)
        _require(self.proposal_type is ProposalType.EVIDENCE_CANDIDATE, "INVALID_TYPE", "proposal_type mismatch")
        _enum(self.evidence_kind, EvidenceKind, "evidence_kind")
        prefix = REF_ID_PREFIX_BY_KIND[self.evidence_kind]
        object.__setattr__(self, "ref_id", _text(self.ref_id, "ref_id", max_len=MAX_REF_LEN, required=True))
        _require(self.ref_id.startswith(prefix), "REF_ID_KIND_MISMATCH", f"{self.evidence_kind.value} ref_id must start with {prefix!r}")
        _require(isinstance(self.source_origin, SourceOrigin), "INVALID_TYPE", "source_origin must be SourceOrigin")
        _enum(self.evidence_time_basis, EvidenceTimeBasis, "evidence_time_basis")
        _enum(self.evidence_time_quality, EvidenceTimeQuality, "evidence_time_quality")
        _enum(self.proposed_role, EvidenceRole, "proposed_role")
        if self.evidence_time_quality is EvidenceTimeQuality.MISSING:
            _require(self.evidence_time is None and self.evidence_date == "" and self.evidence_time_basis is EvidenceTimeBasis.NONE,
                     "MISSING_EVIDENCE_TIME", "MISSING quality has no evidence_time / date / basis")
        else:
            object.__setattr__(self, "evidence_time", _aware(self.evidence_time, "evidence_time"))
            _require(bool(_DATE_RE.match(self.evidence_date)), "INVALID_DATE", "evidence_date must be YYYY-MM-DD")
            _require(self.evidence_time_basis is not EvidenceTimeBasis.NONE, "INVALID_VOCABULARY", "basis required")
        object.__setattr__(self, "target_root_id", _text(self.target_root_id, "target_root_id", max_len=MAX_REF_LEN))
        _require(self.target_root_id == "" or is_root_id(self.target_root_id), "INVALID_RECORD_ID", "target_root_id")
        object.__setattr__(self, "target_proposal_id", _text(self.target_proposal_id, "target_proposal_id", max_len=MAX_REF_LEN))
        _require(self.target_proposal_id == "" or is_content_id(self.target_proposal_id, PROPOSAL_ID_PREFIX),
                 "INVALID_RECORD_ID", "target_proposal_id")
        object.__setattr__(self, "reason", _text(self.reason, "reason", max_len=MAX_TEXT_LEN, required=True))
        _require(self.reason == normalize_text(self.reason), "NOT_NORMALIZED", "reason must be normalized")
        object.__setattr__(self, "locator", _text(self.locator, "locator", max_len=500))
        object.__setattr__(self, "note", _text(self.note, "note", max_len=MAX_NOTE_LEN))
        _require(isinstance(self.provenance, ProposalProvenance), "INVALID_TYPE", "provenance must be ProposalProvenance")
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        _require(self.proposal_id == _proposal_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "proposal_id does not match the proposal content")

    @classmethod
    def build(cls, *, evidence_kind: EvidenceKind, ref_id: str, source_origin: SourceOrigin,
              evidence_time: Optional[datetime], evidence_time_basis: EvidenceTimeBasis,
              evidence_time_quality: EvidenceTimeQuality, evidence_date: str = "", proposed_role: EvidenceRole,
              reason: str, target_root_id: str = "", target_proposal_id: str = "", locator: str = "", note: str = "",
              provenance: ProposalProvenance, created_at: datetime) -> "EvidenceCandidateProposal":
        kwargs = dict(evidence_kind=evidence_kind, ref_id=ref_id, source_origin=source_origin, evidence_time=evidence_time,
                      evidence_time_basis=evidence_time_basis, evidence_time_quality=evidence_time_quality,
                      evidence_date=evidence_date, proposed_role=proposed_role, target_root_id=target_root_id,
                      target_proposal_id=target_proposal_id, reason=reason, locator=locator, note=note)
        shell = object.__new__(cls)
        for name, value in kwargs.items():
            object.__setattr__(shell, name, value)
        object.__setattr__(shell, "schema_version", PROPOSAL_SCHEMA_VERSION)
        object.__setattr__(shell, "proposal_type", ProposalType.EVIDENCE_CANDIDATE)
        return cls(proposal_id=_proposal_id(EvidenceCandidateProposal.identity_payload(shell)), provenance=provenance,
                   created_at=created_at, **kwargs)

    def identity_payload(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "proposal_type": self.proposal_type.value,
            "evidence_kind": self.evidence_kind.value, "ref_id": self.ref_id, "source_origin": _plain(self.source_origin),
            "evidence_time": _plain(self.evidence_time), "evidence_time_basis": self.evidence_time_basis.value,
            "evidence_time_quality": self.evidence_time_quality.value, "evidence_date": self.evidence_date,
            "proposed_role": self.proposed_role.value, "target_root_id": self.target_root_id,
            "target_proposal_id": self.target_proposal_id, "reason": self.reason,
        }

    def as_dict(self) -> Dict[str, object]:
        return _plain(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EvidenceCandidateProposal":
        _reject_unknown(data, cls)
        raw_time = data.get("evidence_time")
        return cls(
            schema_version=_str(data, "schema_version"), proposal_type=_parse_enum(data.get("proposal_type"), ProposalType, "proposal_type"),
            proposal_id=_str(data, "proposal_id"), evidence_kind=_parse_enum(data.get("evidence_kind"), EvidenceKind, "evidence_kind"),
            ref_id=_str(data, "ref_id"), source_origin=SourceOrigin.from_dict(data.get("source_origin") or {}),
            evidence_time=from_iso(raw_time) if isinstance(raw_time, str) else None,
            evidence_time_basis=_parse_enum(data.get("evidence_time_basis"), EvidenceTimeBasis, "evidence_time_basis"),
            evidence_time_quality=_parse_enum(data.get("evidence_time_quality"), EvidenceTimeQuality, "evidence_time_quality"),
            evidence_date=_str(data, "evidence_date", ""), proposed_role=_parse_enum(data.get("proposed_role"), EvidenceRole, "proposed_role"),
            target_root_id=_str(data, "target_root_id", ""), target_proposal_id=_str(data, "target_proposal_id", ""),
            reason=_str(data, "reason"), locator=_str(data, "locator", ""), note=_str(data, "note", ""),
            provenance=ProposalProvenance.from_dict(data.get("provenance") or {}), created_at=from_iso(_str(data, "created_at")))


# ---------------------------------------------------------------- DEDUP_REVIEW

@dataclass(frozen=True)
class DedupCounterpart:
    kind: CounterpartKind
    ref_id: str                       # root id（THEME_ROOT）または proposal id（THEME_PROPOSAL）
    fingerprint: str                  # 比較 basis における counterpart 側の fingerprint 値
    observation_id: str = ""          # THEME_ROOT のとき比較した current observation

    def __post_init__(self) -> None:
        _enum(self.kind, CounterpartKind, "DedupCounterpart.kind")
        object.__setattr__(self, "ref_id", _text(self.ref_id, "ref_id", max_len=MAX_REF_LEN, required=True))
        if self.kind is CounterpartKind.THEME_ROOT:
            _require(is_root_id(self.ref_id), "INVALID_RECORD_ID", "THEME_ROOT counterpart needs a root id")
            _require(is_content_id(self.observation_id, "thobs"), "INVALID_RECORD_ID", "THEME_ROOT counterpart needs an observation id")
        else:
            _require(is_content_id(self.ref_id, PROPOSAL_ID_PREFIX), "INVALID_RECORD_ID", "THEME_PROPOSAL counterpart needs a proposal id")
            _require(self.observation_id == "", "INVALID_RECORD", "THEME_PROPOSAL counterpart has no observation id")
        object.__setattr__(self, "fingerprint", _text(self.fingerprint, "fingerprint", max_len=MAX_REF_LEN, required=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "DedupCounterpart":
        _reject_unknown(data, cls)
        return cls(kind=_parse_enum(data.get("kind"), CounterpartKind, "kind"), ref_id=_str(data, "ref_id"),
                   fingerprint=_str(data, "fingerprint"), observation_id=_str(data, "observation_id", ""))


@dataclass(frozen=True)
class ComparisonBasis:
    kind: ComparisonBasisKind
    subject_fingerprint: str          # 比較時点の subject proposal 側の fingerprint 値

    def __post_init__(self) -> None:
        _enum(self.kind, ComparisonBasisKind, "ComparisonBasis.kind")
        object.__setattr__(self, "subject_fingerprint", _text(self.subject_fingerprint, "subject_fingerprint", max_len=MAX_REF_LEN, required=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ComparisonBasis":
        _reject_unknown(data, cls)
        return cls(kind=_parse_enum(data.get("kind"), ComparisonBasisKind, "kind"), subject_fingerprint=_str(data, "subject_fingerprint"))


@dataclass(frozen=True, kw_only=True)
class DedupReviewProposal:
    """exact 比較で見つかった重複候補の review 提案。identity authority ではなく merge を起こさない。"""

    schema_version: str = PROPOSAL_SCHEMA_VERSION
    proposal_type: ProposalType = ProposalType.DEDUP_REVIEW
    proposal_id: str
    subject_proposal_id: str
    counterparts: Tuple[DedupCounterpart, ...]
    dedup_class: DedupClass
    comparison_basis: ComparisonBasis
    dedup_model_version: str = DEDUP_MODEL_VERSION
    provenance: ProposalProvenance
    created_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == PROPOSAL_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version)
        _require(self.proposal_type is ProposalType.DEDUP_REVIEW, "INVALID_TYPE", "proposal_type mismatch")
        _require(is_content_id(self.subject_proposal_id, PROPOSAL_ID_PREFIX), "INVALID_RECORD_ID", "subject_proposal_id")
        object.__setattr__(self, "counterparts", _typed_tuple(set(self.counterparts), DedupCounterpart, "counterparts"))
        _require(len(self.counterparts) >= 1, "MISSING_FIELD", "a dedup review names at least one counterpart")
        _require(all(c.ref_id != self.subject_proposal_id for c in self.counterparts), "INVALID_RECORD", "subject cannot be its own counterpart")
        _enum(self.dedup_class, DedupClass, "dedup_class")
        _require(self.dedup_class in AUTO_DEDUP_CLASSES, "DEDUP_CLASS_NOT_AUTOMATABLE",
                 f"{self.dedup_class.value} is reserved; B3 emits exact classes only")
        _require(isinstance(self.comparison_basis, ComparisonBasis), "INVALID_TYPE", "comparison_basis")
        expected_basis = (ComparisonBasisKind.SEMANTIC_FINGERPRINT if self.dedup_class is DedupClass.EXACT_SEMANTIC_MATCH
                          else ComparisonBasisKind.IDENTITY_CORE_FINGERPRINT)
        _require(self.comparison_basis.kind is expected_basis, "INVALID_RECORD", "comparison basis does not match dedup class")
        _require(all(c.fingerprint == self.comparison_basis.subject_fingerprint for c in self.counterparts), "INVALID_RECORD",
                 "an exact match requires identical fingerprints on both sides")
        object.__setattr__(self, "dedup_model_version", _text(self.dedup_model_version, "dedup_model_version", max_len=MAX_REF_LEN, required=True))
        _require(isinstance(self.provenance, ProposalProvenance), "INVALID_TYPE", "provenance")
        _require(self.provenance.proposer_class is ProposerClass.RULE, "INVALID_ROLE_COMBINATION", "dedup reviews are RULE proposals")
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        _require(self.proposal_id == _proposal_id(self.identity_payload()), "INVALID_RECORD_ID", "proposal_id does not match")

    @classmethod
    def build(cls, *, subject_proposal_id: str, counterparts: Sequence[DedupCounterpart], dedup_class: DedupClass,
              comparison_basis: ComparisonBasis, provenance: ProposalProvenance, created_at: datetime,
              dedup_model_version: str = DEDUP_MODEL_VERSION) -> "DedupReviewProposal":
        shell = object.__new__(cls)
        for name, value in dict(schema_version=PROPOSAL_SCHEMA_VERSION, proposal_type=ProposalType.DEDUP_REVIEW,
                                subject_proposal_id=subject_proposal_id,
                                counterparts=tuple(sorted(set(counterparts), key=canonical_json)), dedup_class=dedup_class,
                                comparison_basis=comparison_basis, dedup_model_version=dedup_model_version).items():
            object.__setattr__(shell, name, value)
        return cls(proposal_id=_proposal_id(DedupReviewProposal.identity_payload(shell)), subject_proposal_id=subject_proposal_id,
                   counterparts=tuple(counterparts), dedup_class=dedup_class, comparison_basis=comparison_basis,
                   dedup_model_version=dedup_model_version, provenance=provenance, created_at=created_at)

    def identity_payload(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "proposal_type": self.proposal_type.value,
            "subject_proposal_id": self.subject_proposal_id, "counterparts": _plain(self.counterparts),
            "dedup_class": self.dedup_class.value, "comparison_basis": _plain(self.comparison_basis),
            "dedup_model_version": self.dedup_model_version,
        }

    def as_dict(self) -> Dict[str, object]:
        return _plain(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "DedupReviewProposal":
        _reject_unknown(data, cls)
        return cls(
            schema_version=_str(data, "schema_version"), proposal_type=_parse_enum(data.get("proposal_type"), ProposalType, "proposal_type"),
            proposal_id=_str(data, "proposal_id"), subject_proposal_id=_str(data, "subject_proposal_id"),
            counterparts=tuple(DedupCounterpart.from_dict(c) for c in (data.get("counterparts") or ())),
            dedup_class=_parse_enum(data.get("dedup_class"), DedupClass, "dedup_class"),
            comparison_basis=ComparisonBasis.from_dict(data.get("comparison_basis") or {}),
            dedup_model_version=_str(data, "dedup_model_version"),
            provenance=ProposalProvenance.from_dict(data.get("provenance") or {}), created_at=from_iso(_str(data, "created_at")))


Proposal = Union[ThemeCandidateProposal, EvidenceCandidateProposal, DedupReviewProposal]
_PROPOSAL_TYPES = {ProposalType.THEME_CANDIDATE: ThemeCandidateProposal, ProposalType.EVIDENCE_CANDIDATE: EvidenceCandidateProposal,
                   ProposalType.DEDUP_REVIEW: DedupReviewProposal}


def parse_proposal(data: Mapping[str, object]) -> Proposal:
    _require(isinstance(data, Mapping), "INVALID_RECORD", "proposal payload must be an object")
    kind = _parse_enum(data.get("proposal_type"), ProposalType, "proposal_type")
    return _PROPOSAL_TYPES[kind].from_dict(data)


# ---------------------------------------------------------------- decision

@dataclass(frozen=True, kw_only=True)
class ProposalDecision:
    """人間の proposal decision（不変・append-only）。訂正は `supersedes_decision_id` で新 record。"""

    schema_version: str = DECISION_SCHEMA_VERSION
    decision_id: str
    proposal_id: str
    decision: DecisionKind
    actor_class: ProposerClass = ProposerClass.HUMAN
    actor_ref: str
    reason: str
    supersedes_decision_id: str = ""
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == DECISION_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version)
        _require(is_content_id(self.proposal_id, PROPOSAL_ID_PREFIX), "INVALID_RECORD_ID", "proposal_id")
        _enum(self.decision, DecisionKind, "decision")
        _require(self.actor_class is ProposerClass.HUMAN, "INVALID_ROLE_COMBINATION", "proposal decisions are HUMAN only")
        object.__setattr__(self, "actor_ref", _text(self.actor_ref, "actor_ref", max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "reason", _text(self.reason, "reason", max_len=MAX_NOTE_LEN, required=True))
        object.__setattr__(self, "supersedes_decision_id", _text(self.supersedes_decision_id, "supersedes_decision_id", max_len=MAX_REF_LEN))
        _require(self.supersedes_decision_id == "" or is_content_id(self.supersedes_decision_id, DECISION_ID_PREFIX),
                 "INVALID_RECORD_ID", "supersedes_decision_id")
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))
        _require(self.decision_id == content_id(DECISION_ID_PREFIX, canonical_json(self.identity_payload())), "INVALID_RECORD_ID",
                 "decision_id does not match the decision content")
        _require(self.decision_id != self.supersedes_decision_id, "INVALID_RECORD", "a decision cannot supersede itself")

    @classmethod
    def build(cls, *, proposal_id: str, decision: DecisionKind, actor_ref: str, reason: str, recorded_at: datetime,
              supersedes_decision_id: str = "") -> "ProposalDecision":
        payload = {"schema_version": DECISION_SCHEMA_VERSION, "proposal_id": proposal_id, "decision": decision.value,
                   "actor_class": ProposerClass.HUMAN.value, "actor_ref": actor_ref, "reason": reason,
                   "supersedes_decision_id": supersedes_decision_id}
        return cls(decision_id=content_id(DECISION_ID_PREFIX, canonical_json(payload)), proposal_id=proposal_id, decision=decision,
                   actor_ref=actor_ref, reason=reason, supersedes_decision_id=supersedes_decision_id, recorded_at=recorded_at)

    def identity_payload(self) -> Dict[str, object]:
        return {"schema_version": self.schema_version, "proposal_id": self.proposal_id, "decision": self.decision.value,
                "actor_class": self.actor_class.value, "actor_ref": self.actor_ref, "reason": self.reason,
                "supersedes_decision_id": self.supersedes_decision_id}

    def as_dict(self) -> Dict[str, object]:
        return _plain(self)  # type: ignore[return-value]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ProposalDecision":
        _reject_unknown(data, cls)
        return cls(schema_version=_str(data, "schema_version"), decision_id=_str(data, "decision_id"), proposal_id=_str(data, "proposal_id"),
                   decision=_parse_enum(data.get("decision"), DecisionKind, "decision"),
                   actor_class=_parse_enum(data.get("actor_class"), ProposerClass, "actor_class"), actor_ref=_str(data, "actor_ref"),
                   reason=_str(data, "reason"), supersedes_decision_id=_str(data, "supersedes_decision_id", ""),
                   recorded_at=from_iso(_str(data, "recorded_at")))


def canonical_proposal_line(record) -> str:
    """canonical 1 行（`\\n` 終端）。ProposalStore が append する bytes の定義。"""
    return canonical_json(record.as_dict()) + "\n"


__all__ = [
    "PROPOSAL_SCHEMA_VERSION", "DECISION_SCHEMA_VERSION", "DEDUP_MODEL_VERSION", "PROPOSAL_ID_PREFIX", "DECISION_ID_PREFIX",
    "AUTO_DEDUP_CLASSES", "ALLOWED_DECISIONS", "ProposalModelError", "ProposalType", "ProposerClass", "DecisionKind",
    "DedupClass", "ComparisonBasisKind", "CounterpartKind", "ProposalProvenance", "ThemeCandidateProposal",
    "EvidenceCandidateProposal", "DedupCounterpart", "ComparisonBasis", "DedupReviewProposal", "Proposal", "parse_proposal",
    "ProposalDecision", "canonical_proposal_line",
]
