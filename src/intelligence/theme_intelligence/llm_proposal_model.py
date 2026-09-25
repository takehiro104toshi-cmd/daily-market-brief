"""P6-B7B — LLM 提案層の純 model / schema（provider・network・bridge・store を持たない）。

層を混ぜない（どれも authority ではない）:

- A. `LlmGenerationRequest`: 呼び出し側が決める生成要求の記述。時刻は caller 注入。
- B. `LlmGenerationEnvelope`: LLM が返してよい構造化出力の全体。`CANDIDATES` か `ABSTAIN` のどちらか 1 つ。
- C. `LlmCandidate` と kind 別 payload（EVIDENCE / THEME / RELATION）: 既存 authority 型（B3 EVIDENCE_CANDIDATE /
  THEME_CANDIDATE、B5C RELATION_CANDIDATE）の材料の**下書き**。proposal でも decision でもない。
- D. `LlmAbstention`: 有界な棄権理由。
- E. `LlmGenerationRecord`: 生成の監査 metadata。raw response の本文を持たない（digest だけ）。

規律:

- 検査は**構造だけ**。handle が実在するか・evidence が主張を支えるか・PIT・現行 knowledge の語彙・既存提案との重複は
  B7C / B7D の責務であり、ここでは判定しない。
- 違反が 1 つでもあれば生成全体を拒否する。部分採用・黙った修復・切り詰めをしない。
- 引用は opaque handle（`EV_001` など）だけ。handle は authority の id ではなく、解決は B7C。
- provenance（HUMAN / RULE / SOURCE_CLAIM など）・decision・lifecycle・数値の値を表す field は schema に存在しない。
- 現在時刻・乱数・UUID・filesystem・network を使わない。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from ..core.ids import content_id
from ..core.time import ensure_aware
from ..themes.model import (MECHANISM_CATEGORIES, OTHER_CATEGORY, ComponentType, EvidenceRole, ExpectedChange,
                            LimitationCategory, ScopeDimension, canonical_json)
from .relation_model import RelationType

REQUEST_SCHEMA_VERSION = "theme_llm_generation_request:0.1.0"
OUTPUT_SCHEMA_VERSION = "theme_llm_generation_output:0.1.0"
RECORD_SCHEMA_VERSION = "theme_llm_generation_record:0.1.0"
REQUEST_ID_PREFIX = "thllmreq"
GENERATION_ID_PREFIX = "thllmgen"
RESPONSE_DIGEST_PREFIX = "thllmresp"
OUTPUT_DIGEST_PREFIX = "thllmout"
MANIFEST_DIGEST_PREFIX = "thllmin"

#: 構造の上限（schema の一部。超えたら生成全体を拒否する）
MAX_OUTPUT_CHARS = 20000
MAX_CANDIDATES = 16
MAX_HANDLES = 16
MAX_COMPONENTS = 8
MAX_SCOPE_TOKENS = 8
MAX_INVALIDATIONS = 8
MAX_LIMITATIONS = 8
MAX_RATIONALE_LEN = 240           # 最も狭い受け皿（B5C provenance.note）に収まる長さ
MAX_STATEMENT_LEN = 240           # Foundation の statement 上限と同じ
MAX_TARGET_LEN = 200              # Foundation の ref 上限と同じ
MAX_KNOWLEDGE_PINS = 16
MAX_REJECTION_CODES = 16

#: 生成の出力は authority ではない（contract / test で固定する文言）
OUTPUT_IS_NOT_AUTHORITY = "an llm generation is a draft for human review, never an authority record"
#: handle は authority の id ではない
HANDLE_IS_NOT_AUTHORITY_ID = "an opaque handle names an input of one request, never an authority record"


class LlmModelError(ValueError):
    """構造の違反（fail closed）。code は安定した語彙。detail に本文・秘密値を入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise LlmModelError(code, detail)


# ---------------------------------------------------------------- 語彙


class LlmTask(str, Enum):
    """生成要求の種別。許される candidate kind は `TASK_CANDIDATE_KINDS` が決める。"""

    EVIDENCE_EXTRACTION = "EVIDENCE_EXTRACTION"
    THEME_PROPOSAL = "THEME_PROPOSAL"
    RELATION_PROPOSAL = "RELATION_PROPOSAL"
    CONTRADICTION_PROPOSAL = "CONTRADICTION_PROPOSAL"


class CandidateKind(str, Enum):
    """既存 authority 型への対応だけ（新しい authority 型ではない）。DEDUP_REVIEW は存在しない。"""

    EVIDENCE = "EVIDENCE"         # → B3 EVIDENCE_CANDIDATE（反証・無効化も role で表す）
    THEME = "THEME"               # → B3 THEME_CANDIDATE
    RELATION = "RELATION"         # → B5C RELATION_CANDIDATE


class EnvelopeOutcome(str, Enum):
    CANDIDATES = "CANDIDATES"
    ABSTAIN = "ABSTAIN"


class AbstentionReason(str, Enum):
    NO_SUPPORTED_PROPOSAL = "NO_SUPPORTED_PROPOSAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED_TASK = "UNSUPPORTED_TASK"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class HandleKind(str, Enum):
    """opaque handle の種別（prefix）。実体への解決は B7C。"""

    EV = "EV"                     # evidence 入力
    TH = "TH"                     # Theme（root または THEME 提案）
    REL = "REL"                   # relation（既存 assertion / edge）
    ENT = "ENT"                   # entity
    MON = "MON"                   # monitoring finding（文脈のみ。evidence ではない）
    CQ = "CQ"                     # 既存 Theme の期待 consequence
    IC = "IC"                     # 既存 Theme の無効化条件


class GenerationOutcome(str, Enum):
    """生成 1 回の監査上の結末（B7A §19 の生成単位の分類）。"""

    CANDIDATES = "CANDIDATES"
    NO_PROPOSAL = "NO_PROPOSAL"
    REJECTED_GENERATION = "REJECTED_GENERATION"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"


TASK_CANDIDATE_KINDS: Mapping[LlmTask, Tuple[CandidateKind, ...]] = {
    LlmTask.EVIDENCE_EXTRACTION: (CandidateKind.EVIDENCE,),
    LlmTask.THEME_PROPOSAL: (CandidateKind.THEME,),
    LlmTask.RELATION_PROPOSAL: (CandidateKind.RELATION,),
    LlmTask.CONTRADICTION_PROPOSAL: (CandidateKind.EVIDENCE,),
}
TASK_EVIDENCE_ROLES: Mapping[LlmTask, Tuple[EvidenceRole, ...]] = {
    LlmTask.EVIDENCE_EXTRACTION: (EvidenceRole.SUPPORTS, EvidenceRole.CONTEXT),
    LlmTask.CONTRADICTION_PROPOSAL: (EvidenceRole.CONTRADICTS, EvidenceRole.INVALIDATES),
}
#: evidence role ごとに指してよい既存 Theme の component（B4E / Foundation の consequence / 無効化条件の対応と同じ）
ROLE_COMPONENT_HANDLES: Mapping[EvidenceRole, Tuple[HandleKind, ...]] = {
    EvidenceRole.SUPPORTS: (HandleKind.CQ,),
    EvidenceRole.CONTRADICTS: (HandleKind.CQ,),
    EvidenceRole.INVALIDATES: (HandleKind.IC,),
    EvidenceRole.CONTEXT: (),
}

_HANDLE_RE = re.compile(r"^(EV|TH|REL|ENT|MON|CQ|IC)_[0-9]{3,6}$")
_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DIGEST_RE = re.compile(r"^[a-z]+_[0-9a-f]{24}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE_PATH_RE = re.compile(r"(?:^|[\s\"'(\[])[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\")
_POSIX_HOME_RE = re.compile(r"(?:^|[\s\"'(\[])/(?:home|Users|root)/")
_URL_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_SECRET_QUERY_RE = re.compile(r"[?&](?:token|key|api_key|apikey|password|secret|signature|sig)=", re.IGNORECASE)
_CREDENTIAL_LIKE = ("secret", "password", "passwd", "api_key", "apikey", "bearer", "credential")


# ---------------------------------------------------------------- 構造検査の helper


def _text(value: object, name: str, *, max_len: int, required: bool = True) -> str:
    """LLM 由来の文。1 行・有界・前後空白なし・制御文字なし・path / URL / 秘密 query なし。書き換えない。"""
    _require(isinstance(value, str), "INVALID_TYPE", f"{name} must be a string")
    text = str(value)
    if not text:
        _require(not required, "MISSING_FIELD", f"{name} is required")
        return text
    _require(len(text) <= max_len, "FIELD_TOO_LONG", f"{name} exceeds {max_len} characters")
    _require(not _CONTROL_RE.search(text), "INVALID_TEXT", f"{name} must be a single line without control characters")
    _require(text == text.strip() and text.strip() != "", "INVALID_TEXT", f"{name} has surrounding whitespace")
    for pattern in (_DRIVE_PATH_RE, _UNC_PATH_RE, _POSIX_HOME_RE):
        _require(not pattern.search(text), "PROHIBITED_CONTENT", f"{name} contains a machine path")
    _require(not _URL_SCHEME_RE.search(text), "PROHIBITED_CONTENT", f"{name} contains a URL")
    _require(not _SECRET_QUERY_RE.search(text), "PROHIBITED_CONTENT", f"{name} contains a secret-like query")
    return text


def _token(value: object, name: str, pattern: "re.Pattern[str]" = _VERSION_RE) -> str:
    _require(isinstance(value, str) and bool(pattern.match(str(value))), "INVALID_TOKEN", f"{name} is not a bounded token")
    lowered = str(value).lower()
    _require(not lowered.startswith("sk-") and not any(word in lowered for word in _CREDENTIAL_LIKE),
             "PROHIBITED_CONTENT", f"{name} looks like a credential")
    return str(value)


def _enum(value: object, enum: type, name: str):
    if isinstance(value, enum):
        return value
    _require(isinstance(value, str) and value in {member.value for member in enum}, "INVALID_ENUM",
             f"{name} is not a member of {enum.__name__}")
    return enum(value)


def _aware(value: object, name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_TYPE", f"{name} must be a datetime")
    try:
        return ensure_aware(value, name)  # type: ignore[arg-type]
    except ValueError:
        raise LlmModelError("NAIVE_DATETIME", f"{name} must be timezone-aware") from None


def handle_kind(handle: str) -> HandleKind:
    """handle の種別（書式だけを見る。実在は判定しない）。"""
    _require(isinstance(handle, str) and bool(_HANDLE_RE.match(handle)), "INVALID_HANDLE", "not an opaque handle")
    return HandleKind(handle.split("_", 1)[0])


def _handle(value: object, name: str, kinds: Sequence[HandleKind], *, required: bool = True) -> str:
    if value == "" and not required:
        return ""
    _require(isinstance(value, str) and value != "", "MISSING_FIELD" if value in ("", None) else "INVALID_HANDLE",
             f"{name} is required")
    _require(handle_kind(str(value)) in kinds, "HANDLE_KIND_NOT_ALLOWED", f"{name} must name one of {[k.value for k in kinds]}")
    return str(value)


def _handles(values: object, name: str, kinds: Sequence[HandleKind], *, minimum: int, maximum: int = MAX_HANDLES
             ) -> Tuple[str, ...]:
    _require(isinstance(values, (tuple, list)), "INVALID_TYPE", f"{name} must be a list")
    items = [_handle(v, name, kinds) for v in values]  # type: ignore[union-attr]
    _require(len(items) == len(set(items)), "DUPLICATE_HANDLE", f"{name} repeats a handle")
    _require(minimum <= len(items) <= maximum, "INVALID_COUNT", f"{name} needs {minimum}..{maximum} handles")
    return tuple(sorted(items))                    # 引用の順序は意味を持たない


def _items(values: object, name: str, cls: type, *, minimum: int, maximum: int) -> Tuple[object, ...]:
    _require(isinstance(values, (tuple, list)), "INVALID_TYPE", f"{name} must be a list")
    items = list(values)  # type: ignore[arg-type]
    _require(all(isinstance(item, cls) for item in items), "INVALID_TYPE", f"{name} items must be {cls.__name__}")
    keys = [canonical_json(item) for item in items]
    _require(len(keys) == len(set(keys)), "DUPLICATE_ITEM", f"{name} repeats an item")
    _require(minimum <= len(items) <= maximum, "INVALID_COUNT", f"{name} needs {minimum}..{maximum} items")
    return tuple(item for _key, item in sorted(zip(keys, items), key=lambda pair: pair[0]))   # 順序は意味を持たない


def _mapping(data: object, name: str) -> Mapping[str, object]:
    _require(isinstance(data, dict), "INVALID_TYPE", f"{name} must be an object")
    return data  # type: ignore[return-value]


def _fields(data: Mapping[str, object], name: str, required: Sequence[str], optional: Sequence[str] = ()) -> None:
    unknown = sorted(set(data) - set(required) - set(optional))
    _require(not unknown, "UNKNOWN_FIELD", f"{name}: unknown field(s) {unknown}")
    missing = sorted(set(required) - set(data))
    _require(not missing, "MISSING_FIELD", f"{name}: missing field(s) {missing}")


def _list(data: Mapping[str, object], key: str, name: str) -> List[object]:
    value = data.get(key, [])
    _require(isinstance(value, list), "INVALID_TYPE", f"{name}.{key} must be a list")
    return value  # type: ignore[return-value]


# ---------------------------------------------------------------- 下書き部品（Foundation の型ではない）


@dataclass(frozen=True)
class LimitationDraft:
    """限定条件。不確かさは数値ではなく、有界な category と説明で表す。"""

    category: LimitationCategory
    statement: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _enum(self.category, LimitationCategory, "limitation.category"))
        object.__setattr__(self, "statement", _text(self.statement, "limitation.statement", max_len=MAX_STATEMENT_LEN))

    @classmethod
    def from_dict(cls, data: object) -> "LimitationDraft":
        payload = _mapping(data, "limitation")
        _fields(payload, "limitation", ("category", "statement"))
        return cls(category=_enum(payload["category"], LimitationCategory, "limitation.category"),
                   statement=payload["statement"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class ComponentDraft:
    """機構 component（DRIVER / TRANSMISSION_CHANNEL / AFFECTED_DOMAIN）の下書き。type は置かれた欄が決める。"""

    category: str
    statement: str = ""
    entity_handle: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.category, str), "INVALID_TYPE", "component.category must be a string")
        _require(self.category != "", "MISSING_FIELD", "component.category is required")
        object.__setattr__(self, "statement", _text(self.statement, "component.statement", max_len=MAX_STATEMENT_LEN,
                                                    required=False))
        object.__setattr__(self, "entity_handle", _handle(self.entity_handle, "component.entity_handle",
                                                          (HandleKind.ENT,), required=False))

    @classmethod
    def from_dict(cls, data: object) -> "ComponentDraft":
        payload = _mapping(data, "component")
        _fields(payload, "component", ("category",), ("statement", "entity_handle"))
        return cls(category=payload["category"], statement=payload.get("statement", ""),  # type: ignore[arg-type]
                   entity_handle=payload.get("entity_handle", ""))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ConsequenceDraft:
    """期待される観測可能な帰結の下書き（価格目標・期間・正誤は持たない）。"""

    category: str
    observable_target: str
    expected_change: ExpectedChange
    statement: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.category, str) and self.category in
                 MECHANISM_CATEGORIES[ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE], "INVALID_ENUM",
                 "consequence.category is not in the mechanism vocabulary")
        object.__setattr__(self, "observable_target", _text(self.observable_target, "consequence.observable_target",
                                                            max_len=MAX_TARGET_LEN))
        object.__setattr__(self, "expected_change", _enum(self.expected_change, ExpectedChange,
                                                          "consequence.expected_change"))
        object.__setattr__(self, "statement", _text(self.statement, "consequence.statement", max_len=MAX_STATEMENT_LEN,
                                                    required=False))
        _require(self.category != OTHER_CATEGORY or self.statement != "", "MISSING_FIELD",
                 "category OTHER needs a statement")

    @classmethod
    def from_dict(cls, data: object) -> "ConsequenceDraft":
        payload = _mapping(data, "consequence")
        _fields(payload, "consequence", ("category", "observable_target", "expected_change"), ("statement",))
        return cls(category=payload["category"], observable_target=payload["observable_target"],  # type: ignore[arg-type]
                   expected_change=_enum(payload["expected_change"], ExpectedChange, "consequence.expected_change"),
                   statement=payload.get("statement", ""))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ScopeDraft:
    dimension: ScopeDimension
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension", _enum(self.dimension, ScopeDimension, "scope.dimension"))
        object.__setattr__(self, "value", _text(self.value, "scope.value", max_len=MAX_TARGET_LEN))

    @classmethod
    def from_dict(cls, data: object) -> "ScopeDraft":
        payload = _mapping(data, "scope")
        _fields(payload, "scope", ("dimension", "value"))
        return cls(dimension=_enum(payload["dimension"], ScopeDimension, "scope.dimension"),
                   value=payload["value"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class InvalidationDraft:
    """何が観測されれば候補が弱まる / 崩れるか。"""

    statement: str
    observable_target: str = ""
    expected_change: ExpectedChange = ExpectedChange.UNSPECIFIED

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", _text(self.statement, "invalidation.statement", max_len=MAX_STATEMENT_LEN))
        object.__setattr__(self, "observable_target", _text(self.observable_target, "invalidation.observable_target",
                                                            max_len=MAX_TARGET_LEN, required=False))
        object.__setattr__(self, "expected_change", _enum(self.expected_change, ExpectedChange,
                                                          "invalidation.expected_change"))

    @classmethod
    def from_dict(cls, data: object) -> "InvalidationDraft":
        payload = _mapping(data, "invalidation")
        _fields(payload, "invalidation", ("statement",), ("observable_target", "expected_change"))
        return cls(statement=payload["statement"], observable_target=payload.get("observable_target", ""),  # type: ignore[arg-type]
                   expected_change=_enum(payload.get("expected_change", ExpectedChange.UNSPECIFIED.value),
                                         ExpectedChange, "invalidation.expected_change"))


# ---------------------------------------------------------------- kind 別 payload


@dataclass(frozen=True)
class EvidenceCandidatePayload:
    """B3 EVIDENCE_CANDIDATE の材料。evidence の時刻・origin は持たない（B7D が manifest から複写する）。"""

    target_handle: str
    proposed_role: EvidenceRole
    component_handle: str = ""    # 既存 Theme の consequence（CQ）/ 無効化条件（IC）の示唆。identity には入らない予定

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_handle", _handle(self.target_handle, "evidence.target_handle", (HandleKind.TH,)))
        role = _enum(self.proposed_role, EvidenceRole, "evidence.proposed_role")
        object.__setattr__(self, "proposed_role", role)
        allowed = ROLE_COMPONENT_HANDLES[role]
        if self.component_handle != "":
            _require(bool(allowed), "HANDLE_KIND_NOT_ALLOWED", f"role {role.value} does not name a component")
        object.__setattr__(self, "component_handle", _handle(self.component_handle, "evidence.component_handle",
                                                             allowed or (HandleKind.CQ,), required=False))

    @classmethod
    def from_dict(cls, data: object) -> "EvidenceCandidatePayload":
        payload = _mapping(data, "evidence payload")
        _fields(payload, "evidence payload", ("target_handle", "proposed_role"), ("component_handle",))
        return cls(target_handle=payload["target_handle"],  # type: ignore[arg-type]
                   proposed_role=_enum(payload["proposed_role"], EvidenceRole, "evidence.proposed_role"),
                   component_handle=payload.get("component_handle", ""))  # type: ignore[arg-type]


@dataclass(frozen=True, kw_only=True)
class ThemeCandidatePayload:
    """B3 THEME_CANDIDATE の意味の材料（主題・DRIVER・CHANNEL・DOMAIN・観測可能な帰結・scope・無効化条件）。

    certainty・主張 provenance・component key・evidence attachment・root id は持たない（B7D が code で決める）。"""

    subject_statement: str
    subject_entity_handle: str = ""
    drivers: Tuple[ComponentDraft, ...]
    channels: Tuple[ComponentDraft, ...]
    domains: Tuple[ComponentDraft, ...]
    consequences: Tuple[ConsequenceDraft, ...]
    scope: Tuple[ScopeDraft, ...]
    invalidation_conditions: Tuple[InvalidationDraft, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_statement", _text(self.subject_statement, "theme.subject_statement",
                                                            max_len=MAX_STATEMENT_LEN))
        object.__setattr__(self, "subject_entity_handle", _handle(self.subject_entity_handle, "theme.subject_entity_handle",
                                                                  (HandleKind.ENT,), required=False))
        for name, component_type in (("drivers", ComponentType.DRIVER), ("channels", ComponentType.TRANSMISSION_CHANNEL),
                                     ("domains", ComponentType.AFFECTED_DOMAIN)):
            items = _items(getattr(self, name), f"theme.{name}", ComponentDraft, minimum=1, maximum=MAX_COMPONENTS)
            for item in items:
                _require(item.category in MECHANISM_CATEGORIES[component_type], "INVALID_ENUM",  # type: ignore[attr-defined]
                         f"theme.{name}: category is not in the mechanism vocabulary")
                _require(item.category != OTHER_CATEGORY or item.statement != "", "MISSING_FIELD",  # type: ignore[attr-defined]
                         f"theme.{name}: category OTHER needs a statement")
            object.__setattr__(self, name, items)
        object.__setattr__(self, "consequences", _items(self.consequences, "theme.consequences", ConsequenceDraft,
                                                        minimum=1, maximum=MAX_COMPONENTS))
        scope = _items(self.scope, "theme.scope", ScopeDraft, minimum=1, maximum=MAX_SCOPE_TOKENS)
        _require(sum(1 for s in scope if s.dimension is ScopeDimension.PERIOD_FRAME) == 1,  # type: ignore[attr-defined]
                 "INVALID_SCOPE", "scope declares exactly one PERIOD_FRAME")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "invalidation_conditions", _items(
            self.invalidation_conditions, "theme.invalidation_conditions", InvalidationDraft, minimum=1,
            maximum=MAX_INVALIDATIONS))

    @classmethod
    def from_dict(cls, data: object) -> "ThemeCandidatePayload":
        payload = _mapping(data, "theme payload")
        slots = ("drivers", "channels", "domains", "consequences", "scope", "invalidation_conditions")
        _fields(payload, "theme payload", ("subject_statement",) + slots, ("subject_entity_handle",))
        return cls(subject_statement=payload["subject_statement"],  # type: ignore[arg-type]
                   subject_entity_handle=payload.get("subject_entity_handle", ""),  # type: ignore[arg-type]
                   drivers=tuple(ComponentDraft.from_dict(v) for v in _list(payload, "drivers", "theme")),
                   channels=tuple(ComponentDraft.from_dict(v) for v in _list(payload, "channels", "theme")),
                   domains=tuple(ComponentDraft.from_dict(v) for v in _list(payload, "domains", "theme")),
                   consequences=tuple(ConsequenceDraft.from_dict(v) for v in _list(payload, "consequences", "theme")),
                   scope=tuple(ScopeDraft.from_dict(v) for v in _list(payload, "scope", "theme")),
                   invalidation_conditions=tuple(InvalidationDraft.from_dict(v)
                                                 for v in _list(payload, "invalidation_conditions", "theme")))


@dataclass(frozen=True)
class RelationCandidatePayload:
    """B5C RELATION_CANDIDATE の材料。主張 class・確認・decision・真実性・推移・重要度は持たない。"""

    source_handle: str
    target_handle: str
    relation_type: RelationType
    previous_relation_handle: str = ""       # 在れば既存 relation の訂正候補（CORRECTION）
    attribution_evidence_handle: str = ""    # 出典が主張していると LLM が読んだ evidence。真実性ではない

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_handle", _handle(self.source_handle, "relation.source_handle", (HandleKind.TH,)))
        object.__setattr__(self, "target_handle", _handle(self.target_handle, "relation.target_handle", (HandleKind.TH,)))
        _require(self.source_handle != self.target_handle, "SELF_RELATION", "a relation connects two distinct Themes")
        object.__setattr__(self, "relation_type", _enum(self.relation_type, RelationType, "relation.relation_type"))
        object.__setattr__(self, "previous_relation_handle", _handle(
            self.previous_relation_handle, "relation.previous_relation_handle", (HandleKind.REL,), required=False))
        object.__setattr__(self, "attribution_evidence_handle", _handle(
            self.attribution_evidence_handle, "relation.attribution_evidence_handle", (HandleKind.EV,), required=False))

    @classmethod
    def from_dict(cls, data: object) -> "RelationCandidatePayload":
        payload = _mapping(data, "relation payload")
        _fields(payload, "relation payload", ("source_handle", "target_handle", "relation_type"),
                ("previous_relation_handle", "attribution_evidence_handle"))
        return cls(source_handle=payload["source_handle"], target_handle=payload["target_handle"],  # type: ignore[arg-type]
                   relation_type=_enum(payload["relation_type"], RelationType, "relation.relation_type"),
                   previous_relation_handle=payload.get("previous_relation_handle", ""),  # type: ignore[arg-type]
                   attribution_evidence_handle=payload.get("attribution_evidence_handle", ""))  # type: ignore[arg-type]


CandidatePayload = Union[EvidenceCandidatePayload, ThemeCandidatePayload, RelationCandidatePayload]
PAYLOAD_TYPES: Mapping[CandidateKind, type] = {CandidateKind.EVIDENCE: EvidenceCandidatePayload,
                                               CandidateKind.THEME: ThemeCandidatePayload,
                                               CandidateKind.RELATION: RelationCandidatePayload}


# ---------------------------------------------------------------- candidate / abstention / envelope


@dataclass(frozen=True, kw_only=True)
class LlmCandidate:
    """1 つの候補の下書き。authority ではない。identity を持たない（最終 identity は B3 / B5C の内容 id）。"""

    candidate_kind: CandidateKind
    evidence_handles: Tuple[str, ...]
    context_handles: Tuple[str, ...] = ()           # MON だけ。evidence ではない
    payload: CandidatePayload
    rationale: str                                   # 説明文だけ。evidence でも authority でもない
    limitations: Tuple[LimitationDraft, ...] = ()

    def __post_init__(self) -> None:
        kind = _enum(self.candidate_kind, CandidateKind, "candidate.candidate_kind")
        object.__setattr__(self, "candidate_kind", kind)
        _require(isinstance(self.payload, PAYLOAD_TYPES[kind]), "INVALID_COMBINATION",
                 f"a {kind.value} candidate needs a {PAYLOAD_TYPES[kind].__name__}")
        minimum, maximum = (1, 1) if kind is CandidateKind.EVIDENCE else (1, MAX_HANDLES)   # 根拠の無い候補は作らない
        object.__setattr__(self, "evidence_handles", _handles(self.evidence_handles, "candidate.evidence_handles",
                                                              (HandleKind.EV,), minimum=minimum, maximum=maximum))
        object.__setattr__(self, "context_handles", _handles(self.context_handles, "candidate.context_handles",
                                                             (HandleKind.MON,), minimum=0))
        if isinstance(self.payload, RelationCandidatePayload) and self.payload.attribution_evidence_handle:
            _require(self.payload.attribution_evidence_handle in self.evidence_handles, "INVALID_COMBINATION",
                     "the attributed evidence must be one of the cited evidence handles")
        object.__setattr__(self, "rationale", _text(self.rationale, "candidate.rationale", max_len=MAX_RATIONALE_LEN))
        object.__setattr__(self, "limitations", _items(self.limitations, "candidate.limitations", LimitationDraft,
                                                       minimum=0, maximum=MAX_LIMITATIONS))

    def structural_key(self) -> str:
        """同一生成内の重複判定用の構造 key（説明文と限定条件を除く）。**identity ではない**。"""
        return canonical_json({"candidate_kind": self.candidate_kind, "evidence_handles": self.evidence_handles,
                               "context_handles": self.context_handles, "payload": self.payload})

    def as_dict(self) -> Dict[str, object]:
        return {"candidate_kind": self.candidate_kind.value, "evidence_handles": list(self.evidence_handles),
                "context_handles": list(self.context_handles), "payload": json.loads(canonical_json(self.payload)),
                "rationale": self.rationale, "limitations": json.loads(canonical_json(self.limitations))}

    @classmethod
    def from_dict(cls, data: object) -> "LlmCandidate":
        payload = _mapping(data, "candidate")
        _fields(payload, "candidate", ("candidate_kind", "evidence_handles", "payload", "rationale"),
                ("context_handles", "limitations"))
        kind = _enum(payload["candidate_kind"], CandidateKind, "candidate.candidate_kind")
        return cls(candidate_kind=kind, evidence_handles=tuple(_list(payload, "evidence_handles", "candidate")),  # type: ignore[arg-type]
                   context_handles=tuple(_list(payload, "context_handles", "candidate")),  # type: ignore[arg-type]
                   payload=PAYLOAD_TYPES[kind].from_dict(payload["payload"]),  # type: ignore[attr-defined]
                   rationale=payload["rationale"],  # type: ignore[arg-type]
                   limitations=tuple(LimitationDraft.from_dict(v) for v in _list(payload, "limitations", "candidate")))


@dataclass(frozen=True)
class LlmAbstention:
    """棄権。理由は有界な語彙。空出力は棄権ではない。"""

    reason: AbstentionReason
    limitations: Tuple[LimitationDraft, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _enum(self.reason, AbstentionReason, "abstention.reason"))
        object.__setattr__(self, "limitations", _items(self.limitations, "abstention.limitations", LimitationDraft,
                                                       minimum=0, maximum=MAX_LIMITATIONS))

    def as_dict(self) -> Dict[str, object]:
        return {"reason": self.reason.value, "limitations": json.loads(canonical_json(self.limitations))}

    @classmethod
    def from_dict(cls, data: object) -> "LlmAbstention":
        payload = _mapping(data, "abstention")
        _fields(payload, "abstention", ("reason",), ("limitations",))
        return cls(reason=_enum(payload["reason"], AbstentionReason, "abstention.reason"),
                   limitations=tuple(LimitationDraft.from_dict(v) for v in _list(payload, "limitations", "abstention")))


ENVELOPE_KEYS: Mapping[EnvelopeOutcome, Tuple[str, ...]] = {
    EnvelopeOutcome.CANDIDATES: ("output_schema_version", "outcome", "candidates"),
    EnvelopeOutcome.ABSTAIN: ("output_schema_version", "outcome", "abstention"),
}


@dataclass(frozen=True, kw_only=True)
class LlmGenerationEnvelope:
    """LLM の構造化出力の全体。outcome がちょうど 1 つで、outcome が key の集合を決める。"""

    output_schema_version: str = OUTPUT_SCHEMA_VERSION
    outcome: EnvelopeOutcome
    candidates: Tuple[LlmCandidate, ...] = ()
    abstention: Optional[LlmAbstention] = None

    def __post_init__(self) -> None:
        _require(self.output_schema_version == OUTPUT_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 "unsupported output schema version")
        outcome = _enum(self.outcome, EnvelopeOutcome, "outcome")
        object.__setattr__(self, "outcome", outcome)
        _require(isinstance(self.candidates, (tuple, list)), "INVALID_TYPE", "candidates must be a list")
        if outcome is EnvelopeOutcome.ABSTAIN:
            _require(len(self.candidates) == 0, "INVALID_COMBINATION", "an abstention carries no candidate")
            _require(isinstance(self.abstention, LlmAbstention), "INVALID_COMBINATION", "an abstention needs a reason")
            object.__setattr__(self, "candidates", ())
            return
        _require(self.abstention is None, "INVALID_COMBINATION", "candidates and an abstention are exclusive")
        candidates = list(self.candidates)
        _require(all(isinstance(c, LlmCandidate) for c in candidates), "INVALID_TYPE", "candidates must be LlmCandidate")
        _require(1 <= len(candidates) <= MAX_CANDIDATES, "INVALID_COUNT",
                 f"CANDIDATES needs 1..{MAX_CANDIDATES} candidates")
        keys = [c.structural_key() for c in candidates]
        _require(len(keys) == len(set(keys)), "DUPLICATE_CANDIDATE", "two candidates propose the same structure")
        # 候補の順序は意味を持たない（canonical 形は構造 key の順）
        object.__setattr__(self, "candidates", tuple(c for _k, c in sorted(zip(keys, candidates), key=lambda p: p[0])))

    def as_dict(self) -> Dict[str, object]:
        body: Dict[str, object] = {"output_schema_version": self.output_schema_version, "outcome": self.outcome.value}
        if self.outcome is EnvelopeOutcome.ABSTAIN:
            body["abstention"] = self.abstention.as_dict()  # type: ignore[union-attr]
        else:
            body["candidates"] = [c.as_dict() for c in self.candidates]
        return body

    def output_digest(self) -> str:
        """構造化出力（canonical 形）の digest。raw response の digest とは別物。"""
        return content_id(OUTPUT_DIGEST_PREFIX, canonical_json(self.as_dict()))

    @classmethod
    def from_dict(cls, data: object) -> "LlmGenerationEnvelope":
        payload = _mapping(data, "envelope")
        _require("output_schema_version" in payload, "MISSING_FIELD", "envelope: missing output_schema_version")
        _require(payload["output_schema_version"] == OUTPUT_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 "unsupported output schema version")
        _require("outcome" in payload, "MISSING_FIELD", "envelope: missing outcome")
        outcome = _enum(payload["outcome"], EnvelopeOutcome, "outcome")
        other = ENVELOPE_KEYS[EnvelopeOutcome.ABSTAIN if outcome is EnvelopeOutcome.CANDIDATES else EnvelopeOutcome.CANDIDATES]
        _require(not (set(payload) & (set(other) - set(ENVELOPE_KEYS[outcome]))), "INVALID_COMBINATION",
                 f"{outcome.value} does not carry {sorted(set(other) - set(ENVELOPE_KEYS[outcome]))}")
        _fields(payload, "envelope", ENVELOPE_KEYS[outcome])
        if outcome is EnvelopeOutcome.ABSTAIN:
            return cls(outcome=outcome, abstention=LlmAbstention.from_dict(payload["abstention"]))
        return cls(outcome=outcome, candidates=tuple(LlmCandidate.from_dict(v) for v in _list(payload, "candidates", "envelope")))


def _reject_duplicate_keys(pairs: List[Tuple[str, object]]) -> Dict[str, object]:
    keys = [key for key, _value in pairs]
    _require(len(keys) == len(set(keys)), "DUPLICATE_JSON_KEY", "a JSON object repeats a key")
    return dict(pairs)


def _reject_constant(value: str) -> object:
    raise LlmModelError("INVALID_JSON", "NaN / Infinity are not JSON")


def parse_generation_output(raw: object) -> LlmGenerationEnvelope:
    """LLM の応答文字列を厳格に構造化する。どこか 1 か所でも違反すれば全体を拒否する（部分採用しない）。

    許す表現差: JSON の空白・object key の順序・非意味的な list の順序（canonical 形で整列）。
    許さないもの: code fence・前後の説明文・重複 key・NaN・数値 field・未知 field・切り詰め。"""
    _require(isinstance(raw, str), "INVALID_TYPE", "a generation response is text")
    text = str(raw)
    _require(text.strip() != "", "EMPTY_OUTPUT", "an empty response is not an abstention")
    _require(len(text) <= MAX_OUTPUT_CHARS, "OVERSIZED_OUTPUT", f"response exceeds {MAX_OUTPUT_CHARS} characters")
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    except LlmModelError:
        raise
    except (ValueError, RecursionError):
        raise LlmModelError("INVALID_JSON", "the response is not a single JSON document") from None
    _require(isinstance(data, dict), "NOT_AN_OBJECT", "the response must be one JSON object")
    return LlmGenerationEnvelope.from_dict(data)


def check_task_compatibility(task: LlmTask, envelope: LlmGenerationEnvelope) -> None:
    """要求 task と出力の構造的な整合（kind と evidence role）。実在・意味の検査はしない。"""
    task = _enum(task, LlmTask, "task")
    _require(isinstance(envelope, LlmGenerationEnvelope), "INVALID_TYPE", "envelope must be LlmGenerationEnvelope")
    for candidate in envelope.candidates:
        _require(candidate.candidate_kind in TASK_CANDIDATE_KINDS[task], "CANDIDATE_KIND_NOT_ALLOWED_FOR_TASK",
                 f"{task.value} does not produce {candidate.candidate_kind.value} candidates")
        if isinstance(candidate.payload, EvidenceCandidatePayload):
            _require(candidate.payload.proposed_role in TASK_EVIDENCE_ROLES[task], "ROLE_NOT_ALLOWED_FOR_TASK",
                     f"{task.value} does not propose {candidate.payload.proposed_role.value} evidence")


def response_digest_of(raw: str) -> str:
    """raw response の digest。本文は保存しない（B7A D-B7-7 / §16）。"""
    _require(isinstance(raw, str), "INVALID_TYPE", "a generation response is text")
    return content_id(RESPONSE_DIGEST_PREFIX, raw)


# ---------------------------------------------------------------- 生成要求（caller が決める記述）


def _pins(values: object) -> Tuple[Tuple[str, str], ...]:
    _require(isinstance(values, (tuple, list)), "INVALID_TYPE", "knowledge_versions must be a list")
    pairs = []
    for item in values:  # type: ignore[union-attr]
        _require(isinstance(item, (tuple, list)) and len(item) == 2, "INVALID_TYPE", "a knowledge pin is (name, version)")
        pairs.append((_token(item[0], "knowledge name"), _token(item[1], "knowledge version")))
    names = [name for name, _version in pairs]
    _require(len(names) == len(set(names)), "DUPLICATE_ITEM", "a knowledge name is pinned twice")
    _require(len(pairs) <= MAX_KNOWLEDGE_PINS, "INVALID_COUNT", "too many knowledge pins")
    return tuple(sorted(pairs))


def _digest(value: object, name: str, prefix: str) -> str:
    _require(isinstance(value, str) and bool(_DIGEST_RE.match(str(value))) and str(value).startswith(prefix + "_"),
             "INVALID_DIGEST", f"{name} must be a {prefix} content digest")
    return str(value)


REQUEST_FIELDS = ("request_schema_version", "task", "cutoff", "generated_at", "prompt_contract_version",
                  "output_schema_version", "manifest_digest", "knowledge_versions")


@dataclass(frozen=True, kw_only=True)
class LlmGenerationRequest:
    """生成要求の記述。本文も秘密値も持たない（入力の中身は manifest digest に束縛される）。"""

    request_schema_version: str = REQUEST_SCHEMA_VERSION
    task: LlmTask
    cutoff: datetime
    generated_at: datetime                            # caller 注入。監査用で request identity に入らない
    prompt_contract_version: str
    output_schema_version: str = OUTPUT_SCHEMA_VERSION
    manifest_digest: str
    knowledge_versions: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require(self.request_schema_version == REQUEST_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 "unsupported request schema version")
        _require(self.output_schema_version == OUTPUT_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 "unsupported output schema version")
        object.__setattr__(self, "task", _enum(self.task, LlmTask, "task"))
        cutoff, generated = _aware(self.cutoff, "cutoff"), _aware(self.generated_at, "generated_at")
        _require(generated >= cutoff, "GENERATED_BEFORE_CUTOFF", "generated_at must not precede the cutoff")
        object.__setattr__(self, "prompt_contract_version", _token(self.prompt_contract_version, "prompt_contract_version"))
        object.__setattr__(self, "manifest_digest", _digest(self.manifest_digest, "manifest_digest", MANIFEST_DIGEST_PREFIX))
        object.__setattr__(self, "knowledge_versions", _pins(self.knowledge_versions))

    def identity_payload(self) -> Dict[str, object]:
        """何を頼んだか。generated_at・provider・model は含めない（誰がいつ答えたかは生成 record）。"""
        return {"request_schema_version": self.request_schema_version, "task": self.task.value,
                "cutoff": self.cutoff, "prompt_contract_version": self.prompt_contract_version,
                "output_schema_version": self.output_schema_version, "manifest_digest": self.manifest_digest,
                "knowledge_versions": [list(pair) for pair in self.knowledge_versions]}

    @property
    def request_id(self) -> str:
        return content_id(REQUEST_ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, object]:
        return json.loads(canonical_json({**self.identity_payload(), "generated_at": self.generated_at}))

    @classmethod
    def from_dict(cls, data: object) -> "LlmGenerationRequest":
        payload = _mapping(data, "request")
        _fields(payload, "request", REQUEST_FIELDS)
        for name in ("cutoff", "generated_at"):
            _require(isinstance(payload[name], str), "INVALID_TYPE", f"{name} must be an ISO datetime")
        try:
            cutoff = datetime.fromisoformat(payload["cutoff"])  # type: ignore[arg-type]
            generated = datetime.fromisoformat(payload["generated_at"])  # type: ignore[arg-type]
        except ValueError:
            raise LlmModelError("INVALID_DATETIME", "request times must be ISO datetimes") from None
        return cls(request_schema_version=payload["request_schema_version"],  # type: ignore[arg-type]
                   task=_enum(payload["task"], LlmTask, "task"), cutoff=cutoff, generated_at=generated,
                   prompt_contract_version=payload["prompt_contract_version"],  # type: ignore[arg-type]
                   output_schema_version=payload["output_schema_version"],  # type: ignore[arg-type]
                   manifest_digest=payload["manifest_digest"],  # type: ignore[arg-type]
                   knowledge_versions=tuple(payload["knowledge_versions"]))  # type: ignore[arg-type]


# ---------------------------------------------------------------- 生成の監査 record（authority ではない）


RECORD_FIELDS = ("record_schema_version", "generation_id", "request_id", "request", "provider_ref", "model_ref",
                 "generation_config_ref", "outcome", "response_digest", "output_digest", "abstention_reason",
                 "candidate_count", "rejection_codes")


@dataclass(frozen=True, kw_only=True)
class LlmGenerationRecord:
    """生成 1 回の監査 metadata。raw response・prompt・推論過程を持たない。provider / model は provenance だけ。"""

    record_schema_version: str = RECORD_SCHEMA_VERSION
    generation_id: str
    request: LlmGenerationRequest
    provider_ref: str
    model_ref: str
    generation_config_ref: str
    outcome: GenerationOutcome
    response_digest: str = ""
    output_digest: str = ""
    abstention_reason: Optional[AbstentionReason] = None
    candidate_count: int = 0
    rejection_codes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(self.record_schema_version == RECORD_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 "unsupported record schema version")
        _require(isinstance(self.request, LlmGenerationRequest), "INVALID_TYPE", "request must be LlmGenerationRequest")
        for name in ("provider_ref", "model_ref", "generation_config_ref"):
            object.__setattr__(self, name, _token(getattr(self, name), name))
        outcome = _enum(self.outcome, GenerationOutcome, "outcome")
        object.__setattr__(self, "outcome", outcome)
        if self.response_digest:
            _digest(self.response_digest, "response_digest", RESPONSE_DIGEST_PREFIX)
        if self.output_digest:
            _digest(self.output_digest, "output_digest", OUTPUT_DIGEST_PREFIX)
        if self.abstention_reason is not None:
            object.__setattr__(self, "abstention_reason", _enum(self.abstention_reason, AbstentionReason,
                                                                "abstention_reason"))
        _require(isinstance(self.candidate_count, int) and not isinstance(self.candidate_count, bool)
                 and 0 <= self.candidate_count <= MAX_CANDIDATES, "INVALID_TYPE", "candidate_count is a bounded count")
        _require(isinstance(self.rejection_codes, (tuple, list)), "INVALID_TYPE", "rejection_codes must be a list")
        codes = tuple(sorted({_token(code, "rejection code", _CODE_RE) for code in self.rejection_codes}))
        _require(len(codes) == len(self.rejection_codes) and len(codes) <= MAX_REJECTION_CODES, "DUPLICATE_ITEM",
                 "rejection codes are unique and bounded")
        object.__setattr__(self, "rejection_codes", codes)
        self._check_outcome()
        _require(self.generation_id == content_id(GENERATION_ID_PREFIX, canonical_json(self.identity_payload())),
                 "INVALID_RECORD_ID", "generation_id does not match the record content")

    def _check_outcome(self) -> None:
        answered, parsed = bool(self.response_digest), bool(self.output_digest)
        outcome = self.outcome
        if outcome is GenerationOutcome.CANDIDATES:
            ok = answered and parsed and self.candidate_count >= 1 and self.abstention_reason is None and not self.rejection_codes
        elif outcome is GenerationOutcome.NO_PROPOSAL:
            ok = (answered and parsed and self.candidate_count == 0 and self.abstention_reason is not None
                  and not self.rejection_codes)
        elif outcome is GenerationOutcome.REJECTED_GENERATION:
            ok = answered and not parsed and self.candidate_count == 0 and self.abstention_reason is None and bool(self.rejection_codes)
        elif outcome is GenerationOutcome.RETRYABLE_FAILURE:
            ok = not answered and not parsed and self.candidate_count == 0 and self.abstention_reason is None and bool(self.rejection_codes)
        else:                                                         # INTEGRITY_FAILURE
            ok = not parsed and self.candidate_count == 0 and self.abstention_reason is None and bool(self.rejection_codes)
        _require(ok, "INVALID_COMBINATION", f"fields do not fit outcome {outcome.value}")

    def identity_payload(self) -> Dict[str, object]:
        """生成という出来事の identity（監査用）。候補・Theme・evidence・relation の意味 identity とは別物。"""
        return {"record_schema_version": self.record_schema_version, "request_id": self.request.request_id,
                "request": self.request.as_dict(), "provider_ref": self.provider_ref, "model_ref": self.model_ref,
                "generation_config_ref": self.generation_config_ref, "outcome": self.outcome.value,
                "response_digest": self.response_digest, "output_digest": self.output_digest,
                "abstention_reason": self.abstention_reason.value if self.abstention_reason else None,
                "candidate_count": self.candidate_count, "rejection_codes": list(self.rejection_codes)}

    @property
    def request_id(self) -> str:
        return self.request.request_id

    def as_dict(self) -> Dict[str, object]:
        return {**self.identity_payload(), "generation_id": self.generation_id}

    @classmethod
    def build(cls, request: LlmGenerationRequest, *, provider_ref: str, model_ref: str, generation_config_ref: str,
              outcome: GenerationOutcome, response_digest: str = "", envelope: Optional[LlmGenerationEnvelope] = None,
              rejection_codes: Sequence[str] = ()) -> "LlmGenerationRecord":
        """envelope が在れば output digest・棄権理由・候補数を envelope から導く（呼び出し側に書かせない）。"""
        _require(envelope is None or isinstance(envelope, LlmGenerationEnvelope), "INVALID_TYPE",
                 "envelope must be LlmGenerationEnvelope")
        values = dict(request=request, provider_ref=provider_ref, model_ref=model_ref,
                      generation_config_ref=generation_config_ref, outcome=outcome, response_digest=response_digest,
                      output_digest=envelope.output_digest() if envelope else "",
                      abstention_reason=envelope.abstention.reason if envelope and envelope.abstention else None,
                      candidate_count=len(envelope.candidates) if envelope else 0,
                      rejection_codes=tuple(rejection_codes))
        shell = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(shell, name, value)
        object.__setattr__(shell, "record_schema_version", RECORD_SCHEMA_VERSION)
        object.__setattr__(shell, "outcome", _enum(outcome, GenerationOutcome, "outcome"))
        object.__setattr__(shell, "rejection_codes", tuple(sorted(set(rejection_codes))))
        object.__setattr__(shell, "abstention_reason", values["abstention_reason"])
        try:
            generation_id = content_id(GENERATION_ID_PREFIX, canonical_json(LlmGenerationRecord.identity_payload(shell)))
        except (AttributeError, TypeError):
            raise LlmModelError("INVALID_TYPE", "record fields are malformed") from None
        return cls(generation_id=generation_id, **values)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: object) -> "LlmGenerationRecord":
        payload = _mapping(data, "record")
        _fields(payload, "record", RECORD_FIELDS)
        request = LlmGenerationRequest.from_dict(payload["request"])
        _require(payload["request_id"] == request.request_id, "INVALID_RECORD_ID", "request_id does not match the request")
        reason = payload["abstention_reason"]
        return cls(record_schema_version=payload["record_schema_version"],  # type: ignore[arg-type]
                   generation_id=payload["generation_id"], request=request,  # type: ignore[arg-type]
                   provider_ref=payload["provider_ref"], model_ref=payload["model_ref"],  # type: ignore[arg-type]
                   generation_config_ref=payload["generation_config_ref"],  # type: ignore[arg-type]
                   outcome=_enum(payload["outcome"], GenerationOutcome, "outcome"),
                   response_digest=payload["response_digest"], output_digest=payload["output_digest"],  # type: ignore[arg-type]
                   abstention_reason=None if reason is None else _enum(reason, AbstentionReason, "abstention_reason"),
                   candidate_count=payload["candidate_count"],  # type: ignore[arg-type]
                   rejection_codes=tuple(_list(payload, "rejection_codes", "record")))  # type: ignore[arg-type]


def canonical_llm_line(record: Union[LlmGenerationEnvelope, LlmGenerationRequest, LlmGenerationRecord]) -> str:
    """canonical 1 行（key 整列・compact・非意味的な list は整列済み）。"""
    _require(isinstance(record, (LlmGenerationEnvelope, LlmGenerationRequest, LlmGenerationRecord)), "INVALID_TYPE",
             "not a B7 model object")
    return canonical_json(record.as_dict()) + "\n"


__all__ = ["AbstentionReason", "CandidateKind", "ComponentDraft", "ConsequenceDraft", "ENVELOPE_KEYS", "EnvelopeOutcome",
           "EvidenceCandidatePayload", "GENERATION_ID_PREFIX", "GenerationOutcome", "HANDLE_IS_NOT_AUTHORITY_ID",
           "HandleKind", "InvalidationDraft", "LimitationDraft", "LlmAbstention", "LlmCandidate", "LlmGenerationEnvelope",
           "LlmGenerationRecord", "LlmGenerationRequest", "LlmModelError", "LlmTask", "MANIFEST_DIGEST_PREFIX",
           "MAX_CANDIDATES", "MAX_OUTPUT_CHARS", "MAX_RATIONALE_LEN", "OUTPUT_DIGEST_PREFIX", "OUTPUT_IS_NOT_AUTHORITY",
           "OUTPUT_SCHEMA_VERSION", "PAYLOAD_TYPES", "RECORD_SCHEMA_VERSION", "REQUEST_ID_PREFIX",
           "REQUEST_SCHEMA_VERSION", "RESPONSE_DIGEST_PREFIX", "ROLE_COMPONENT_HANDLES", "RelationCandidatePayload",
           "ScopeDraft", "TASK_CANDIDATE_KINDS", "TASK_EVIDENCE_ROLES", "ThemeCandidatePayload", "canonical_llm_line",
           "check_task_compatibility", "handle_kind", "parse_generation_output", "response_digest_of"]
