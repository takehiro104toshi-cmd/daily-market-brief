"""P7-A1 — Narrative の意味論と純 model（派生・非 authority・非永続）。

`NarrativeSynthesis` は、caller が与えた cutoff で reviewed（L2）Theme について**構造化された claim の集合**を持つ派生物である。
fact・Theme・governance の authority ではなく、Production DNA・予測・推奨・売買 signal でもない。保存しない。

- 型は `THEME_STATE`（reviewed Theme 1 つ）と `THEME_SET`（2 つ以上。順位・主役・勝者・受益者を持たない）だけ。
- claim は {認識 class, claim kind, predicate, 型付き opaque ref の集合, 不確実性 code} で、自由文を持たない。
- 認識 class は 5 つ（SCENARIO_CONDITION は採用しない。契約 §5）。claim kind は「何について」、認識 class は「どう知っているか」。
- ref は id と閉じた語彙だけを持つ。store を読まない。path・URL・raw JSON・本文・抜粋を持たない。
- 数値の確信度・score・順位・確率・重みの field は存在しない。
- identity は内容から決まる（`content_id`）。時計・乱数・運用 metadata は identity に入らない。
- 検査は fail closed。黙った修復・切り詰め・重複の除去をしない（非意味的な集合の並びを正規化するだけ）。
- 上流（Phase 6）の語彙は複製して持つ（Phase 6 の package を import しない。一致は test で固定する）。

契約: `docs/databank/PHASE7_NARRATIVE_SEMANTICS_MODEL_CONTRACT.md`。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Type, Union

from ..core.ids import content_id
from ..core.time import from_iso, to_utc_iso

SCHEMA_VERSION = "narrative_synthesis:0.1.0"
CLAIM_SCHEMA_VERSION = "narrative_claim:0.1.0"
SYNTHESIS_ID_PREFIX = "narsyn"
CLAIM_ID_PREFIX = "narclm"
NARRATIVE_KEY_PREFIX = "narkey"

#: 構造の上限（超えたら拒否する。切り詰めない）
MAX_SUBJECTS = 16
MAX_CLAIMS = 256
MAX_REFS_PER_CLAIM = 16
MAX_KNOWLEDGE_PINS = 16

#: 契約と test で固定する文言
SYNTHESIS_IS_NOT_AUTHORITY = ("a narrative synthesis is a derived, non-authoritative, non-persistent reading of reviewed "
                              "themes; never a fact, theme or governance authority, a prediction, a recommendation or a "
                              "trading signal")
SOURCE_ASSERTED_MEANING = "a source asserted this relation; the narrative does not assert it"


class NarrativeModelError(ValueError):
    """意味論・構造の違反（fail closed）。code は安定した語彙。detail は field 名だけで、値を入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise NarrativeModelError(code, detail)


# ---------------------------------------------------------------- Narrative 自身の語彙

class NarrativeKind(str, Enum):
    THEME_STATE = "THEME_STATE"      # reviewed Theme ちょうど 1 つ
    THEME_SET = "THEME_SET"          # reviewed Theme 2 つ以上（順位・主役なし）


class EpistemicClass(str, Enum):
    """claim を「どう知っているか」。格上げ（解釈 → 事実 など）は model に存在しない。"""
    OBSERVED_FACT = "OBSERVED_FACT"                        # 上流に記録された観測そのもの
    REVIEWED_INTERPRETATION = "REVIEWED_INTERPRETATION"    # reviewed Theme / relation authority に記録された解釈
    DERIVED_SYNTHESIS = "DERIVED_SYNTHESIS"                # 決定論の code が authority から計算したこと
    UNCERTAINTY = "UNCERTAINTY"                            # 閉じた code で示す欠落・争い・仮説のまま
    ALTERNATIVE_HYPOTHESIS = "ALTERNATIVE_HYPOTHESIS"      # 並べるだけの代替の説明（勝者なし）


#: 監査で採用しなかった class 名（入力に現れたら専用 code で拒否する。契約 §5）
NOT_ADOPTED_EPISTEMIC_CLASSES = ("SCENARIO_CONDITION",)


class ClaimKind(str, Enum):
    """claim が「何について」か。§3 の WHAT / WHY / EVIDENCE / CHANGE / RELATIONS / INVALIDATION。"""
    STATE = "STATE"
    MECHANISM = "MECHANISM"
    EVIDENCE = "EVIDENCE"
    CHANGE = "CHANGE"
    RELATION = "RELATION"
    INVALIDATION = "INVALIDATION"


class Predicate(str, Enum):
    THEME_REVIEWED_STATE = "THEME_REVIEWED_STATE"
    RECORDS_MECHANISM_COMPONENT = "RECORDS_MECHANISM_COMPONENT"
    EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED"
    EVIDENCE_ITEM_OBSERVED = "EVIDENCE_ITEM_OBSERVED"
    CHANGED_BETWEEN_CUTOFFS = "CHANGED_BETWEEN_CUTOFFS"
    HUMAN_ASSERTED_RELATION = "HUMAN_ASSERTED_RELATION"
    SOURCE_ASSERTED_RELATION = "SOURCE_ASSERTED_RELATION"
    RECORDS_INVALIDATION_CONDITION = "RECORDS_INVALIDATION_CONDITION"
    INVALIDATING_EVIDENCE_ATTACHED = "INVALIDATING_EVIDENCE_ATTACHED"
    ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE = "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE"
    IS_UNCERTAIN = "IS_UNCERTAIN"


class UncertaintyCode(str, Enum):
    """確率ではない。閉じた種類だけ。"""
    NO_SUPPORTING_EVIDENCE = "NO_SUPPORTING_EVIDENCE"
    SINGLE_SOURCE_EVIDENCE = "SINGLE_SOURCE_EVIDENCE"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    CONTESTED_EVIDENCE = "CONTESTED_EVIDENCE"
    MECHANISM_HYPOTHESIZED = "MECHANISM_HYPOTHESIZED"


# ---------------------------------------------------------------- Phase 6 の語彙の複製（一致は test で固定する）

class GovernancePosition(str, Enum):
    """B2 GovernanceLifecycleState の複製。"""
    UNREVIEWED = "UNREVIEWED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"
    MERGED = "MERGED"
    SPLIT = "SPLIT"
    SUPERSEDED = "SUPERSEDED"
    UNRESOLVED = "UNRESOLVED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class MechanismCertainty(str, Enum):
    """Foundation MechanismCertainty の複製。順序・数値 rank を持たない（attribution）。"""
    OBSERVED_ASSOCIATION = "OBSERVED_ASSOCIATION"
    HYPOTHESIZED_MECHANISM = "HYPOTHESIZED_MECHANISM"
    EVIDENCE_SUPPORTED_MECHANISM = "EVIDENCE_SUPPORTED_MECHANISM"
    EXPLICIT_SOURCE_CAUSAL_CLAIM = "EXPLICIT_SOURCE_CAUSAL_CLAIM"


class ComponentType(str, Enum):
    DRIVER = "DRIVER"
    TRANSMISSION_CHANNEL = "TRANSMISSION_CHANNEL"
    AFFECTED_DOMAIN = "AFFECTED_DOMAIN"
    EXPECTED_OBSERVABLE_CONSEQUENCE = "EXPECTED_OBSERVABLE_CONSEQUENCE"


class EvidenceKind(str, Enum):
    FACT = "FACT"
    OBSERVATION = "OBSERVATION"
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    NEWS_ITEM = "NEWS_ITEM"
    STATEMENT = "STATEMENT"


class EvidenceRole(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT = "CONTEXT"
    INVALIDATES = "INVALIDATES"


class ProvenanceClass(str, Enum):
    RULE = "RULE"
    HUMAN = "HUMAN"
    LLM_PROPOSAL = "LLM_PROPOSAL"


class EvidenceTimeQuality(str, Enum):
    RELIABLE = "RELIABLE"
    DECLARED = "DECLARED"
    INFERRED = "INFERRED"
    MISSING = "MISSING"


class RelationType(str, Enum):
    CAUSES = "CAUSES"
    AMPLIFIES = "AMPLIFIES"
    MITIGATES = "MITIGATES"
    DEPENDS_ON = "DEPENDS_ON"


class AssertionClass(str, Enum):
    HUMAN_ASSERTED = "HUMAN_ASSERTED"
    SOURCE_ASSERTED = "SOURCE_ASSERTED"


class ChangeKind(str, Enum):
    """B1 ChangeKind の複製。"""
    ROOT_APPEARED = "ROOT_APPEARED"
    ROOT_BECAME_OBSERVED = "ROOT_BECAME_OBSERVED"
    OBSERVATION_REVISED = "OBSERVATION_REVISED"
    SEMANTIC_FIELD_CHANGED = "SEMANTIC_FIELD_CHANGED"
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    EVIDENCE_CARRIED = "EVIDENCE_CARRIED"
    EVIDENCE_DROPPED = "EVIDENCE_DROPPED"
    EVIDENCE_ROLE_CHANGED = "EVIDENCE_ROLE_CHANGED"
    EVIDENCE_REF_REVISED = "EVIDENCE_REF_REVISED"
    EVIDENCE_ATTRIBUTE_CHANGED = "EVIDENCE_ATTRIBUTE_CHANGED"
    NEW_SOURCE_ORIGIN = "NEW_SOURCE_ORIGIN"
    NEW_EVIDENCE_DATE = "NEW_EVIDENCE_DATE"
    SOURCE_ORIGIN_LOST = "SOURCE_ORIGIN_LOST"
    EVIDENCE_DATE_LOST = "EVIDENCE_DATE_LOST"
    QUALIFICATION_CHANGED = "QUALIFICATION_CHANGED"
    CONTRADICTION_APPEARED = "CONTRADICTION_APPEARED"
    CONTRADICTION_CLEARED = "CONTRADICTION_CLEARED"
    INVALIDATION_APPEARED = "INVALIDATION_APPEARED"
    INVALIDATION_CLEARED = "INVALIDATION_CLEARED"
    GOVERNANCE_CHANGED = "GOVERNANCE_CHANGED"
    METADATA_CHANGED = "METADATA_CHANGED"
    MAPPING_CHANGED = "MAPPING_CHANGED"
    LINEAGE_CHANGED = "LINEAGE_CHANGED"
    PENDING_APPEARED = "PENDING_APPEARED"
    PENDING_CLEARED = "PENDING_CLEARED"
    SEMANTIC_BECAME_UNRESOLVED = "SEMANTIC_BECAME_UNRESOLVED"
    SEMANTIC_BECAME_RESOLVED = "SEMANTIC_BECAME_RESOLVED"
    FACET_BECAME_UNRESOLVED = "FACET_BECAME_UNRESOLVED"
    FACET_BECAME_RESOLVED = "FACET_BECAME_RESOLVED"
    DEREFERENCE_CHANGED = "DEREFERENCE_CHANGED"


#: B1 FACET_ORDER の複製（metadata は "metadata:<FIELD>"）
CHANGE_FACETS = ("root", "observation", "evidence", "derived", "governance", "metadata", "mapping", "lineage", "pending",
                 "dereference")
#: Foundation REF_ID_PREFIX_BY_KIND の複製（STATEMENT は producer 未確定のため prefix なし）
REF_ID_PREFIX_BY_KIND: Mapping[EvidenceKind, str] = {
    EvidenceKind.FACT: "fact_",
    EvidenceKind.OBSERVATION: "obs_",
    EvidenceKind.SOURCE_DOCUMENT: "doc_",
    EvidenceKind.NEWS_ITEM: "news_",
    EvidenceKind.STATEMENT: "",
}

#: 解釈の根拠にしてよい Theme の governance の位置（L2 の天井。RETIRED 等は後続 gate。契約 §7）
REVIEWED_POSITIONS: Tuple[GovernancePosition, ...] = (GovernancePosition.ACCEPTED,)
#: OBSERVED_FACT が引用してよい evidence（一次の観測だけ。文書・報道・発言の内容は出典の主張であり事実ではない）
OBSERVED_FACT_EVIDENCE_KINDS: Tuple[EvidenceKind, ...] = (EvidenceKind.FACT, EvidenceKind.OBSERVATION)
OBSERVED_FACT_TIME_QUALITIES: Tuple[EvidenceTimeQuality, ...] = (EvidenceTimeQuality.RELIABLE,
                                                                 EvidenceTimeQuality.DECLARED)

#: predicate → (認識 class, 許される claim kind)。この表の外の組み合わせは存在しない（契約 §6）
PREDICATE_SIGNATURES: Mapping[Predicate, Tuple[EpistemicClass, Tuple[ClaimKind, ...]]] = {
    Predicate.THEME_REVIEWED_STATE: (EpistemicClass.REVIEWED_INTERPRETATION, (ClaimKind.STATE,)),
    Predicate.RECORDS_MECHANISM_COMPONENT: (EpistemicClass.REVIEWED_INTERPRETATION, (ClaimKind.MECHANISM,)),
    Predicate.EVIDENCE_ATTACHED: (EpistemicClass.REVIEWED_INTERPRETATION, (ClaimKind.EVIDENCE,)),
    Predicate.EVIDENCE_ITEM_OBSERVED: (EpistemicClass.OBSERVED_FACT, (ClaimKind.EVIDENCE,)),
    Predicate.CHANGED_BETWEEN_CUTOFFS: (EpistemicClass.DERIVED_SYNTHESIS, (ClaimKind.CHANGE,)),
    Predicate.HUMAN_ASSERTED_RELATION: (EpistemicClass.REVIEWED_INTERPRETATION, (ClaimKind.RELATION,)),
    Predicate.SOURCE_ASSERTED_RELATION: (EpistemicClass.REVIEWED_INTERPRETATION, (ClaimKind.RELATION,)),
    Predicate.RECORDS_INVALIDATION_CONDITION: (EpistemicClass.REVIEWED_INTERPRETATION, (ClaimKind.INVALIDATION,)),
    Predicate.INVALIDATING_EVIDENCE_ATTACHED: (EpistemicClass.REVIEWED_INTERPRETATION, (ClaimKind.INVALIDATION,)),
    Predicate.ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE: (EpistemicClass.ALTERNATIVE_HYPOTHESIS,
                                                            (ClaimKind.MECHANISM,)),
    Predicate.IS_UNCERTAIN: (EpistemicClass.UNCERTAINTY, (ClaimKind.EVIDENCE, ClaimKind.MECHANISM)),
}
#: 不確実性 code → それが語る claim kind
UNCERTAINTY_CLAIM_KIND: Mapping[UncertaintyCode, ClaimKind] = {
    UncertaintyCode.NO_SUPPORTING_EVIDENCE: ClaimKind.EVIDENCE,
    UncertaintyCode.SINGLE_SOURCE_EVIDENCE: ClaimKind.EVIDENCE,
    UncertaintyCode.STALE_EVIDENCE: ClaimKind.EVIDENCE,
    UncertaintyCode.CONTESTED_EVIDENCE: ClaimKind.EVIDENCE,
    UncertaintyCode.MECHANISM_HYPOTHESIZED: ClaimKind.MECHANISM,
}
#: (認識 class, claim kind, predicate) の許される組の全体
ALLOWED_TRIPLES = frozenset((klass, kind, predicate) for predicate, (klass, kinds) in PREDICATE_SIGNATURES.items()
                            for kind in kinds)
RELATION_PREDICATES = (Predicate.HUMAN_ASSERTED_RELATION, Predicate.SOURCE_ASSERTED_RELATION)
ASSERTION_CLASS_BY_PREDICATE: Mapping[Predicate, AssertionClass] = {
    Predicate.HUMAN_ASSERTED_RELATION: AssertionClass.HUMAN_ASSERTED,
    Predicate.SOURCE_ASSERTED_RELATION: AssertionClass.SOURCE_ASSERTED,
}

#: model に存在しない ref の型（出てきたら専用 code で拒否する）。未審査・運用・予測・P4 生成物・P5・私的な資料
PROHIBITED_REF_TYPES = ("THEME_PROPOSAL", "EVIDENCE_PROPOSAL", "RELATION_PROPOSAL", "PROPOSAL_DECISION", "DISCOVERY_HIT",
                        "MONITORING_FINDING", "REVIEW_ITEM_STATE", "LLM_PROPOSAL", "LLM_GENERATION", "LLM_OUTPUT",
                        "PREDICTION", "EVALUATION", "CALIBRATION", "COMPASS_DRAFT", "MARKET_SIGNAL", "FORMAL_REVIEW",
                        "CORPUS_DOCUMENT", "CORPUS_RESEARCH", "DECISION", "THESIS", "SCREENING", "PERSONALIZATION",
                        "REPLAY", "RAW_PATH", "URL", "RAW_JSON")
#: 後続 gate で決める ref の型（A1 には無い。契約 §25）
DEFERRED_REF_TYPES = ("DNA_RULE", "P4_FACT", "P4_CONTEXT", "P4_INTERNALS", "THEME_LIMITATION", "THEME_LINEAGE",
                      "UNREVIEWED_CONTEXT")
#: 直列化に現れてはならない field 名（順位・確信度・予測・推奨・自由文・生の値・秘密・運用 metadata）
PROHIBITED_FIELDS = ("confidence", "score", "rank", "ranking", "probability", "likelihood", "weight", "priority",
                     "strength", "dominant_theme", "primary_theme", "winner", "beneficiary", "beneficiaries",
                     "recommendation", "signal", "prediction", "forecast", "target_price", "direction", "text", "prose",
                     "summary", "headline", "narrative_text", "display_text", "excerpt", "note", "locator", "raw",
                     "raw_payload", "url", "path", "api_key", "token", "secret", "generated_at", "created_at",
                     "recorded_at", "run_id")

_ROOT_ID_RE = re.compile(r"^theme_[0-9A-HJKMNP-TV-Z]{26}$")
_OBSERVATION_ID_RE = re.compile(r"^thobs_[0-9a-f]{24}$")
_RELATION_ID_RE = re.compile(r"^threl_[0-9a-f]{24}$")
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_EVIDENCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_CHANGE_SUBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:#-]{0,271}$")
_METADATA_FACET_RE = re.compile(r"^metadata:[A-Z][A-Z0-9_]{0,63}$")
_PIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PIN_VERSION_RE = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")
_DIGEST_RE = re.compile(r"^[a-z][a-z0-9]{1,15}_[0-9a-f]{24}$")


def canonical_json(payload: Any) -> str:
    """canonical JSON（sort_keys / compact separators / ensure_ascii=False。Phase 6 と同じ形）。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------- 検査の部品

def _enum(value: Any, enum_type: Type[Enum], code: str, name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    _require(isinstance(value, str) and value in {m.value for m in enum_type}, code, name)
    return enum_type(value)


def _token(value: Any, pattern: "re.Pattern[str]", code: str, name: str) -> str:
    _require(isinstance(value, str) and bool(pattern.fullmatch(value)), code, name)
    return value


def _time(value: Any, name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_TYPE", name)
    _require(value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None, "NAIVE_DATETIME", name)
    return value


def _evidence_ref_id(value: Any, kind: EvidenceKind, name: str) -> str:
    ref_id = _token(value, _EVIDENCE_REF_RE, "INVALID_EVIDENCE_REF_ID", name)
    _require(ref_id.startswith(REF_ID_PREFIX_BY_KIND[kind]), "REF_ID_KIND_MISMATCH", name)
    return ref_id


def _optional_key(value: Any, code: str, name: str) -> str:
    _require(isinstance(value, str), "INVALID_TYPE", name)
    return "" if value == "" else _token(value, _KEY_RE, code, name)


def _mapping(data: Any, required: Sequence[str], name: str) -> Mapping[str, Any]:
    """直列化された dict の検査（禁止 field → 未知 field → 欠落の順）。"""
    _require(isinstance(data, dict), "INVALID_TYPE", name)
    for key in data:
        _require(isinstance(key, str), "INVALID_TYPE", name)
        _require(key not in PROHIBITED_FIELDS, "PROHIBITED_FIELD", f"{name}.{key}")
        _require(key in required, "UNKNOWN_FIELD", f"{name}.{key}")
    for key in required:
        _require(key in data, "MISSING_FIELD", f"{name}.{key}")
    return data


def _ref_mapping(cls: Type[Any], data: Mapping[str, Any], required: Sequence[str]) -> None:
    _mapping(data, required, cls.REF_TYPE)
    _require(data["ref_type"] == cls.REF_TYPE, "REF_TYPE_MISMATCH", cls.REF_TYPE)


def _str(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    _require(isinstance(value, str), "INVALID_TYPE", key)
    return value


def _list(data: Mapping[str, Any], key: str) -> List[Any]:
    value = data[key]
    _require(isinstance(value, list), "INVALID_TYPE", key)
    return value


def _parse_time(data: Mapping[str, Any], key: str) -> datetime:
    text = _str(data, key)
    try:
        value = from_iso(text)
    except ValueError:
        raise NarrativeModelError("INVALID_DATETIME", key) from None
    _require(to_utc_iso(value) == text, "NON_CANONICAL_DATETIME", key)
    return value


# ---------------------------------------------------------------- 型付き opaque ref

@dataclass(frozen=True, kw_only=True)
class ThemeObservationRef:
    """cutoff で見えている reviewed Theme の observation（L2）。確度 class は表示のための attribution。"""
    REF_TYPE: ClassVar[str] = "THEME_OBSERVATION"
    root_id: str
    observation_id: str
    governance_position: GovernancePosition
    mechanism_certainty: MechanismCertainty

    def __post_init__(self) -> None:
        _token(self.root_id, _ROOT_ID_RE, "INVALID_ROOT_ID", "ThemeObservationRef.root_id")
        _token(self.observation_id, _OBSERVATION_ID_RE, "INVALID_OBSERVATION_ID", "ThemeObservationRef.observation_id")
        position = _enum(self.governance_position, GovernancePosition, "UNKNOWN_GOVERNANCE_POSITION",
                         "ThemeObservationRef.governance_position")
        _require(position in REVIEWED_POSITIONS, "THEME_NOT_REVIEWED", "ThemeObservationRef.governance_position")
        object.__setattr__(self, "governance_position", position)
        object.__setattr__(self, "mechanism_certainty", _enum(
            self.mechanism_certainty, MechanismCertainty, "UNKNOWN_MECHANISM_CERTAINTY",
            "ThemeObservationRef.mechanism_certainty"))

    def roots(self) -> Tuple[str, ...]:
        return (self.root_id,)

    def to_dict(self) -> Dict[str, Any]:
        return {"ref_type": self.REF_TYPE, "root_id": self.root_id, "observation_id": self.observation_id,
                "governance_position": self.governance_position.value,
                "mechanism_certainty": self.mechanism_certainty.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ThemeObservationRef":
        _ref_mapping(cls, data, ("ref_type", "root_id", "observation_id", "governance_position", "mechanism_certainty"))
        return cls(root_id=_str(data, "root_id"), observation_id=_str(data, "observation_id"),
                   governance_position=_str(data, "governance_position"),
                   mechanism_certainty=_str(data, "mechanism_certainty"))


@dataclass(frozen=True, kw_only=True)
class MechanismComponentRef:
    """reviewed observation に記録された機構 component（driver / channel / domain / consequence）。"""
    REF_TYPE: ClassVar[str] = "MECHANISM_COMPONENT"
    root_id: str
    observation_id: str
    component_type: ComponentType
    component_key: str

    def __post_init__(self) -> None:
        _token(self.root_id, _ROOT_ID_RE, "INVALID_ROOT_ID", "MechanismComponentRef.root_id")
        _token(self.observation_id, _OBSERVATION_ID_RE, "INVALID_OBSERVATION_ID", "MechanismComponentRef.observation_id")
        object.__setattr__(self, "component_type", _enum(self.component_type, ComponentType, "UNKNOWN_COMPONENT_TYPE",
                                                         "MechanismComponentRef.component_type"))
        _token(self.component_key, _KEY_RE, "INVALID_KEY", "MechanismComponentRef.component_key")

    def roots(self) -> Tuple[str, ...]:
        return (self.root_id,)

    def to_dict(self) -> Dict[str, Any]:
        return {"ref_type": self.REF_TYPE, "root_id": self.root_id, "observation_id": self.observation_id,
                "component_type": self.component_type.value, "component_key": self.component_key}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MechanismComponentRef":
        _ref_mapping(cls, data, ("ref_type", "root_id", "observation_id", "component_type", "component_key"))
        return cls(root_id=_str(data, "root_id"), observation_id=_str(data, "observation_id"),
                   component_type=_str(data, "component_type"), component_key=_str(data, "component_key"))


@dataclass(frozen=True, kw_only=True)
class InvalidationConditionRef:
    """reviewed observation に記録された無効化条件（条件の参照だけ。評価・実行しない）。"""
    REF_TYPE: ClassVar[str] = "INVALIDATION_CONDITION"
    root_id: str
    observation_id: str
    condition_key: str

    def __post_init__(self) -> None:
        _token(self.root_id, _ROOT_ID_RE, "INVALID_ROOT_ID", "InvalidationConditionRef.root_id")
        _token(self.observation_id, _OBSERVATION_ID_RE, "INVALID_OBSERVATION_ID",
               "InvalidationConditionRef.observation_id")
        _token(self.condition_key, _KEY_RE, "INVALID_KEY", "InvalidationConditionRef.condition_key")

    def roots(self) -> Tuple[str, ...]:
        return (self.root_id,)

    def to_dict(self) -> Dict[str, Any]:
        return {"ref_type": self.REF_TYPE, "root_id": self.root_id, "observation_id": self.observation_id,
                "condition_key": self.condition_key}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InvalidationConditionRef":
        _ref_mapping(cls, data, ("ref_type", "root_id", "observation_id", "condition_key"))
        return cls(root_id=_str(data, "root_id"), observation_id=_str(data, "observation_id"),
                   condition_key=_str(data, "condition_key"))


@dataclass(frozen=True, kw_only=True)
class EvidenceAttachmentRef:
    """reviewed observation の evidence attachment（Theme ↔ evidence の解釈上の結び付き）。role は書き換えない。"""
    REF_TYPE: ClassVar[str] = "EVIDENCE_ATTACHMENT"
    root_id: str
    observation_id: str
    ref_id: str
    evidence_kind: EvidenceKind
    consequence_key: str = ""
    role: EvidenceRole
    role_provenance: ProvenanceClass
    attached_at: datetime
    invalidation_condition_key: str = ""

    def __post_init__(self) -> None:
        _token(self.root_id, _ROOT_ID_RE, "INVALID_ROOT_ID", "EvidenceAttachmentRef.root_id")
        _token(self.observation_id, _OBSERVATION_ID_RE, "INVALID_OBSERVATION_ID", "EvidenceAttachmentRef.observation_id")
        kind = _enum(self.evidence_kind, EvidenceKind, "UNKNOWN_EVIDENCE_KIND", "EvidenceAttachmentRef.evidence_kind")
        object.__setattr__(self, "evidence_kind", kind)
        _evidence_ref_id(self.ref_id, kind, "EvidenceAttachmentRef.ref_id")
        _optional_key(self.consequence_key, "INVALID_KEY", "EvidenceAttachmentRef.consequence_key")
        role = _enum(self.role, EvidenceRole, "UNKNOWN_EVIDENCE_ROLE", "EvidenceAttachmentRef.role")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "role_provenance", _enum(self.role_provenance, ProvenanceClass,
                                                          "UNKNOWN_ROLE_PROVENANCE",
                                                          "EvidenceAttachmentRef.role_provenance"))
        _time(self.attached_at, "EvidenceAttachmentRef.attached_at")
        condition = _optional_key(self.invalidation_condition_key, "INVALID_KEY",
                                  "EvidenceAttachmentRef.invalidation_condition_key")
        if role is EvidenceRole.INVALIDATES:
            _require(condition != "", "INVALIDATION_CONDITION_REQUIRED", "EvidenceAttachmentRef")
        else:
            _require(condition == "", "INVALIDATION_CONDITION_ONLY_FOR_INVALIDATES", "EvidenceAttachmentRef")

    @property
    def attachment_key(self) -> str:
        """observation 内の attachment の identity（Foundation と同じ `ref_id#consequence`）。"""
        return f"{self.ref_id}#{self.consequence_key}"

    def roots(self) -> Tuple[str, ...]:
        return (self.root_id,)

    def to_dict(self) -> Dict[str, Any]:
        return {"ref_type": self.REF_TYPE, "root_id": self.root_id, "observation_id": self.observation_id,
                "ref_id": self.ref_id, "evidence_kind": self.evidence_kind.value,
                "consequence_key": self.consequence_key, "role": self.role.value,
                "role_provenance": self.role_provenance.value, "attached_at": to_utc_iso(self.attached_at),
                "invalidation_condition_key": self.invalidation_condition_key}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceAttachmentRef":
        _ref_mapping(cls, data, ("ref_type", "root_id", "observation_id", "ref_id", "evidence_kind", "consequence_key", "role",
                        "role_provenance", "attached_at", "invalidation_condition_key"))
        return cls(root_id=_str(data, "root_id"), observation_id=_str(data, "observation_id"),
                   ref_id=_str(data, "ref_id"), evidence_kind=_str(data, "evidence_kind"),
                   consequence_key=_str(data, "consequence_key"), role=_str(data, "role"),
                   role_provenance=_str(data, "role_provenance"), attached_at=_parse_time(data, "attached_at"),
                   invalidation_condition_key=_str(data, "invalidation_condition_key"))


@dataclass(frozen=True, kw_only=True)
class EvidenceItemRef:
    """観測された evidence item そのもの（Theme との結び付きを持たない。事実の側）。"""
    REF_TYPE: ClassVar[str] = "EVIDENCE_ITEM"
    ref_id: str
    evidence_kind: EvidenceKind
    evidence_time: datetime
    time_quality: EvidenceTimeQuality

    def __post_init__(self) -> None:
        kind = _enum(self.evidence_kind, EvidenceKind, "UNKNOWN_EVIDENCE_KIND", "EvidenceItemRef.evidence_kind")
        object.__setattr__(self, "evidence_kind", kind)
        _evidence_ref_id(self.ref_id, kind, "EvidenceItemRef.ref_id")
        _time(self.evidence_time, "EvidenceItemRef.evidence_time")
        quality = _enum(self.time_quality, EvidenceTimeQuality, "UNKNOWN_TIME_QUALITY", "EvidenceItemRef.time_quality")
        _require(quality is not EvidenceTimeQuality.MISSING, "TIME_QUALITY_INCONSISTENT", "EvidenceItemRef.time_quality")
        object.__setattr__(self, "time_quality", quality)

    def roots(self) -> Tuple[str, ...]:
        return ()

    def to_dict(self) -> Dict[str, Any]:
        return {"ref_type": self.REF_TYPE, "ref_id": self.ref_id, "evidence_kind": self.evidence_kind.value,
                "evidence_time": to_utc_iso(self.evidence_time), "time_quality": self.time_quality.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceItemRef":
        _ref_mapping(cls, data, ("ref_type", "ref_id", "evidence_kind", "evidence_time", "time_quality"))
        return cls(ref_id=_str(data, "ref_id"), evidence_kind=_str(data, "evidence_kind"),
                   evidence_time=_parse_time(data, "evidence_time"), time_quality=_str(data, "time_quality"))


@dataclass(frozen=True, kw_only=True)
class ThemeChangeRef:
    """B1 の 1 つの変化の項目（kind・facet・subject の id だけ。before / after / detail の本文を持たない）。"""
    REF_TYPE: ClassVar[str] = "THEME_CHANGE"
    root_id: str
    from_cutoff: datetime
    to_cutoff: datetime
    change_kind: ChangeKind
    facet: str
    subject_id: str

    def __post_init__(self) -> None:
        _token(self.root_id, _ROOT_ID_RE, "INVALID_ROOT_ID", "ThemeChangeRef.root_id")
        _time(self.from_cutoff, "ThemeChangeRef.from_cutoff")
        _time(self.to_cutoff, "ThemeChangeRef.to_cutoff")
        _require(self.from_cutoff < self.to_cutoff, "CHANGE_WINDOW_INVALID", "ThemeChangeRef")
        object.__setattr__(self, "change_kind", _enum(self.change_kind, ChangeKind, "UNKNOWN_CHANGE_KIND",
                                                      "ThemeChangeRef.change_kind"))
        _require(isinstance(self.facet, str) and (self.facet in CHANGE_FACETS
                                                  or bool(_METADATA_FACET_RE.fullmatch(self.facet))),
                 "UNKNOWN_CHANGE_FACET", "ThemeChangeRef.facet")
        _token(self.subject_id, _CHANGE_SUBJECT_RE, "INVALID_CHANGE_SUBJECT", "ThemeChangeRef.subject_id")

    def roots(self) -> Tuple[str, ...]:
        return (self.root_id,)

    def to_dict(self) -> Dict[str, Any]:
        return {"ref_type": self.REF_TYPE, "root_id": self.root_id, "from_cutoff": to_utc_iso(self.from_cutoff),
                "to_cutoff": to_utc_iso(self.to_cutoff), "change_kind": self.change_kind.value, "facet": self.facet,
                "subject_id": self.subject_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ThemeChangeRef":
        _ref_mapping(cls, data, ("ref_type", "root_id", "from_cutoff", "to_cutoff", "change_kind", "facet", "subject_id"))
        return cls(root_id=_str(data, "root_id"), from_cutoff=_parse_time(data, "from_cutoff"),
                   to_cutoff=_parse_time(data, "to_cutoff"), change_kind=_str(data, "change_kind"),
                   facet=_str(data, "facet"), subject_id=_str(data, "subject_id"))


@dataclass(frozen=True, kw_only=True)
class RelationAssertionRef:
    """B5B の明示的な relation assertion の直接の辺（推移辺・中心性・隠れた因果を持たない）。"""
    REF_TYPE: ClassVar[str] = "RELATION_ASSERTION"
    relation_assertion_id: str
    source_root_id: str
    target_root_id: str
    relation_type: RelationType
    assertion_class: AssertionClass

    def __post_init__(self) -> None:
        _token(self.relation_assertion_id, _RELATION_ID_RE, "INVALID_RELATION_ID",
               "RelationAssertionRef.relation_assertion_id")
        _token(self.source_root_id, _ROOT_ID_RE, "INVALID_ROOT_ID", "RelationAssertionRef.source_root_id")
        _token(self.target_root_id, _ROOT_ID_RE, "INVALID_ROOT_ID", "RelationAssertionRef.target_root_id")
        _require(self.source_root_id != self.target_root_id, "SELF_RELATION", "RelationAssertionRef")
        object.__setattr__(self, "relation_type", _enum(self.relation_type, RelationType, "UNKNOWN_RELATION_TYPE",
                                                        "RelationAssertionRef.relation_type"))
        object.__setattr__(self, "assertion_class", _enum(self.assertion_class, AssertionClass,
                                                          "UNKNOWN_ASSERTION_CLASS",
                                                          "RelationAssertionRef.assertion_class"))

    def roots(self) -> Tuple[str, ...]:
        return (self.source_root_id, self.target_root_id)

    def to_dict(self) -> Dict[str, Any]:
        return {"ref_type": self.REF_TYPE, "relation_assertion_id": self.relation_assertion_id,
                "source_root_id": self.source_root_id, "target_root_id": self.target_root_id,
                "relation_type": self.relation_type.value, "assertion_class": self.assertion_class.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationAssertionRef":
        _ref_mapping(cls, data, ("ref_type", "relation_assertion_id", "source_root_id", "target_root_id", "relation_type",
                        "assertion_class"))
        return cls(relation_assertion_id=_str(data, "relation_assertion_id"),
                   source_root_id=_str(data, "source_root_id"), target_root_id=_str(data, "target_root_id"),
                   relation_type=_str(data, "relation_type"), assertion_class=_str(data, "assertion_class"))


NarrativeRef = Union[ThemeObservationRef, MechanismComponentRef, InvalidationConditionRef, EvidenceAttachmentRef,
                     EvidenceItemRef, ThemeChangeRef, RelationAssertionRef]
REF_TYPES: Mapping[str, Type[Any]] = {cls.REF_TYPE: cls for cls in (
    ThemeObservationRef, MechanismComponentRef, InvalidationConditionRef, EvidenceAttachmentRef, EvidenceItemRef,
    ThemeChangeRef, RelationAssertionRef)}
#: Theme の解釈（OBSERVED_FACT だけを支えにできない ref）
INTERPRETATION_REF_TYPES = (ThemeObservationRef, MechanismComponentRef, InvalidationConditionRef, EvidenceAttachmentRef,
                            ThemeChangeRef, RelationAssertionRef)


def ref_from_dict(data: Any) -> NarrativeRef:
    _require(isinstance(data, dict), "INVALID_TYPE", "ref")
    ref_type = data.get("ref_type")
    _require(isinstance(ref_type, str), "INVALID_TYPE", "ref.ref_type")
    _require(ref_type not in PROHIBITED_REF_TYPES, "PROHIBITED_REF_TYPE", ref_type)
    _require(ref_type not in DEFERRED_REF_TYPES, "REF_TYPE_DEFERRED", ref_type)
    _require(ref_type in REF_TYPES, "UNKNOWN_REF_TYPE", "ref.ref_type")
    return REF_TYPES[ref_type].from_dict(data)


def _ref_sort_key(ref: NarrativeRef) -> str:
    return canonical_json(ref.to_dict())


# ---------------------------------------------------------------- claim

def _of(refs: Sequence[NarrativeRef], ref_type: Type[Any]) -> List[Any]:
    return [ref for ref in refs if isinstance(ref, ref_type)]


def _shape(refs: Sequence[NarrativeRef], **expected: Tuple[Type[Any], int, int]) -> None:
    """ref の型ごとの件数（最小・最大）。表に無い型の ref は許さない。"""
    allowed = tuple(spec[0] for spec in expected.values())
    _require(all(isinstance(ref, allowed) for ref in refs), "REF_SHAPE_INVALID", "unexpected ref type")
    for name, (ref_type, low, high) in expected.items():
        count = len(_of(refs, ref_type))
        _require(low <= count <= high, "REF_SHAPE_INVALID", name)


def _check_claim_refs(predicate: Predicate, code: Optional[UncertaintyCode], refs: Sequence[NarrativeRef]) -> None:
    one = MAX_REFS_PER_CLAIM
    if predicate is Predicate.THEME_REVIEWED_STATE:
        _shape(refs, observation=(ThemeObservationRef, 1, 1))
    elif predicate is Predicate.RECORDS_MECHANISM_COMPONENT:
        _shape(refs, component=(MechanismComponentRef, 1, 1))
    elif predicate is Predicate.EVIDENCE_ATTACHED:
        _shape(refs, attachment=(EvidenceAttachmentRef, 1, 1))
    elif predicate is Predicate.EVIDENCE_ITEM_OBSERVED:
        items = _of(refs, EvidenceItemRef)
        _require(bool(items), "FACT_CITES_ONLY_INTERPRETATION", "OBSERVED_FACT")
        _shape(refs, item=(EvidenceItemRef, 1, 1))
        _require(items[0].evidence_kind in OBSERVED_FACT_EVIDENCE_KINDS, "FACT_REQUIRES_OBSERVATIONAL_EVIDENCE",
                 "OBSERVED_FACT")
        _require(items[0].time_quality in OBSERVED_FACT_TIME_QUALITIES, "FACT_TIME_NOT_ESTABLISHED", "OBSERVED_FACT")
    elif predicate is Predicate.CHANGED_BETWEEN_CUTOFFS:
        _shape(refs, change=(ThemeChangeRef, 1, 1))
    elif predicate in RELATION_PREDICATES:
        relations = _of(refs, RelationAssertionRef)
        _require(bool(relations), "RELATION_REF_REQUIRED", predicate.value)
        _shape(refs, relation=(RelationAssertionRef, 1, 1), endpoints=(ThemeObservationRef, 2, 2))
        _require(relations[0].assertion_class is ASSERTION_CLASS_BY_PREDICATE[predicate], "ASSERTION_CLASS_MISMATCH",
                 predicate.value)
        _require({ref.root_id for ref in _of(refs, ThemeObservationRef)} == set(relations[0].roots()),
                 "RELATION_ENDPOINTS_REQUIRED", predicate.value)
    elif predicate is Predicate.RECORDS_INVALIDATION_CONDITION:
        _require(bool(_of(refs, InvalidationConditionRef)), "INVALIDATION_REF_REQUIRED", predicate.value)
        _shape(refs, condition=(InvalidationConditionRef, 1, 1))
    elif predicate is Predicate.INVALIDATING_EVIDENCE_ATTACHED:
        _require(bool(_of(refs, InvalidationConditionRef)), "INVALIDATION_REF_REQUIRED", predicate.value)
        _shape(refs, condition=(InvalidationConditionRef, 1, 1), attachment=(EvidenceAttachmentRef, 1, 1))
        condition, attachment = _of(refs, InvalidationConditionRef)[0], _of(refs, EvidenceAttachmentRef)[0]
        _require(attachment.role is EvidenceRole.INVALIDATES
                 and (attachment.root_id, attachment.observation_id) == (condition.root_id, condition.observation_id)
                 and attachment.invalidation_condition_key == condition.condition_key,
                 "INVALIDATION_EVIDENCE_MISMATCH", predicate.value)
    elif predicate is Predicate.ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE:
        attachments = _of(refs, EvidenceAttachmentRef)
        observations = _of(refs, ThemeObservationRef)
        _shape(refs, observation=(ThemeObservationRef, 2, one), attachment=(EvidenceAttachmentRef, 2, one))
        roots = [ref.root_id for ref in attachments]
        _require(len(set(roots)) == len(roots), "ALTERNATIVE_DUPLICATE_THEME", predicate.value)
        _require(len({ref.ref_id for ref in attachments}) == 1, "ALTERNATIVES_REQUIRE_SHARED_EVIDENCE", predicate.value)
        _require(all(ref.role is EvidenceRole.SUPPORTS for ref in attachments), "ALTERNATIVES_REQUIRE_SUPPORTS",
                 predicate.value)
        _require(sorted((ref.root_id, ref.observation_id) for ref in observations)
                 == sorted((ref.root_id, ref.observation_id) for ref in attachments),
                 "ALTERNATIVE_THEMES_MISMATCH", predicate.value)
    elif predicate is Predicate.IS_UNCERTAIN:
        _require(code is not None, "UNCERTAINTY_CODE_REQUIRED", predicate.value)
        if code is UncertaintyCode.CONTESTED_EVIDENCE:
            _shape(refs, observation=(ThemeObservationRef, 1, 1), attachment=(EvidenceAttachmentRef, 2, one))
            observation = _of(refs, ThemeObservationRef)[0]
            attachments = _of(refs, EvidenceAttachmentRef)
            roles = {ref.role for ref in attachments}
            _require(roles == {EvidenceRole.SUPPORTS, EvidenceRole.CONTRADICTS}
                     and all((ref.root_id, ref.observation_id) == (observation.root_id, observation.observation_id)
                             for ref in attachments), "UNCERTAINTY_CONTRADICTS_REFS", code.value)
        else:
            _shape(refs, observation=(ThemeObservationRef, 1, 1))
            if code is UncertaintyCode.MECHANISM_HYPOTHESIZED:
                _require(_of(refs, ThemeObservationRef)[0].mechanism_certainty
                         is MechanismCertainty.HYPOTHESIZED_MECHANISM, "UNCERTAINTY_CONTRADICTS_REFS", code.value)


@dataclass(frozen=True, kw_only=True)
class NarrativeClaim:
    """構造化された 1 つの claim。自由文・数値の確信度・順位を持たない。`claim_id` は内容から決まる。"""
    epistemic_class: EpistemicClass
    claim_kind: ClaimKind
    predicate: Predicate
    refs: Tuple[NarrativeRef, ...]
    uncertainty_code: Optional[UncertaintyCode] = None
    claim_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require(not (isinstance(self.epistemic_class, str) and self.epistemic_class in NOT_ADOPTED_EPISTEMIC_CLASSES),
                 "EPISTEMIC_CLASS_NOT_ADOPTED", "NarrativeClaim.epistemic_class")
        klass = _enum(self.epistemic_class, EpistemicClass, "UNKNOWN_EPISTEMIC_CLASS", "NarrativeClaim.epistemic_class")
        kind = _enum(self.claim_kind, ClaimKind, "UNKNOWN_CLAIM_KIND", "NarrativeClaim.claim_kind")
        predicate = _enum(self.predicate, Predicate, "UNKNOWN_PREDICATE", "NarrativeClaim.predicate")
        expected_class, expected_kinds = PREDICATE_SIGNATURES[predicate]
        _require(klass is expected_class, "EPISTEMIC_CLASS_MISMATCH", predicate.value)
        _require(kind in expected_kinds, "CLAIM_KIND_MISMATCH", predicate.value)
        code: Optional[UncertaintyCode] = None
        if predicate is Predicate.IS_UNCERTAIN:
            _require(self.uncertainty_code is not None, "UNCERTAINTY_CODE_REQUIRED", predicate.value)
            code = _enum(self.uncertainty_code, UncertaintyCode, "UNKNOWN_UNCERTAINTY_CODE",
                         "NarrativeClaim.uncertainty_code")
            _require(UNCERTAINTY_CLAIM_KIND[code] is kind, "CLAIM_KIND_MISMATCH", code.value)
        else:
            _require(self.uncertainty_code is None, "UNCERTAINTY_CODE_NOT_ALLOWED", predicate.value)
        _require(isinstance(self.refs, (tuple, list)), "INVALID_TYPE", "NarrativeClaim.refs")
        refs = tuple(self.refs)
        _require(all(isinstance(ref, tuple(REF_TYPES.values())) for ref in refs), "INVALID_REF", "NarrativeClaim.refs")
        _require(1 <= len(refs) <= MAX_REFS_PER_CLAIM, "REF_COUNT_OUT_OF_BOUNDS", "NarrativeClaim.refs")
        keys = [_ref_sort_key(ref) for ref in refs]
        _require(len(set(keys)) == len(keys), "DUPLICATE_REF", "NarrativeClaim.refs")
        _check_claim_refs(predicate, code, refs)
        object.__setattr__(self, "epistemic_class", klass)
        object.__setattr__(self, "claim_kind", kind)
        object.__setattr__(self, "predicate", predicate)
        object.__setattr__(self, "uncertainty_code", code)
        object.__setattr__(self, "refs", tuple(sorted(refs, key=_ref_sort_key)))     # 非意味的な集合の正規化
        object.__setattr__(self, "claim_id", content_id(CLAIM_ID_PREFIX, canonical_json(self._identity_payload())))

    def _identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": CLAIM_SCHEMA_VERSION, "epistemic_class": self.epistemic_class.value,
                "claim_kind": self.claim_kind.value, "predicate": self.predicate.value,
                "uncertainty_code": None if self.uncertainty_code is None else self.uncertainty_code.value,
                "refs": [ref.to_dict() for ref in self.refs]}

    def roots(self) -> Tuple[str, ...]:
        return tuple(sorted({root for ref in self.refs for root in ref.roots()}))

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._identity_payload(), claim_id=self.claim_id)

    @classmethod
    def from_dict(cls, data: Any) -> "NarrativeClaim":
        _mapping(data, ("schema_version", "claim_id", "epistemic_class", "claim_kind", "predicate", "uncertainty_code",
                        "refs"), "claim")
        _require(_str(data, "schema_version") == CLAIM_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", "claim")
        code = data["uncertainty_code"]
        _require(code is None or isinstance(code, str), "INVALID_TYPE", "uncertainty_code")
        claim = cls(epistemic_class=_str(data, "epistemic_class"), claim_kind=_str(data, "claim_kind"),
                    predicate=_str(data, "predicate"), refs=tuple(ref_from_dict(ref) for ref in _list(data, "refs")),
                    uncertainty_code=code)
        _require(_str(data, "claim_id") == claim.claim_id, "CLAIM_ID_MISMATCH", "claim")
        return claim


# ---------------------------------------------------------------- synthesis

def _knowledge_pins(value: Any) -> Tuple[Tuple[str, str], ...]:
    _require(isinstance(value, (tuple, list)), "INVALID_TYPE", "NarrativeSynthesis.knowledge_pins")
    pins = []
    for pin in value:
        _require(isinstance(pin, (tuple, list)) and len(pin) == 2, "INVALID_KNOWLEDGE_PIN", "knowledge_pins")
        name = _token(pin[0], _PIN_NAME_RE, "INVALID_KNOWLEDGE_PIN", "knowledge_pins.name")
        version = _token(pin[1], _PIN_VERSION_RE, "INVALID_KNOWLEDGE_PIN", "knowledge_pins.version")
        pins.append((name, version))
    _require(1 <= len(pins) <= MAX_KNOWLEDGE_PINS, "KNOWLEDGE_PINS_OUT_OF_BOUNDS", "knowledge_pins")
    _require(len({name for name, _ in pins}) == len(pins), "DUPLICATE_KNOWLEDGE_PIN", "knowledge_pins")
    return tuple(sorted(pins))


def _single(values: Iterable[Any], code: str, detail: str) -> None:
    _require(len(set(values)) <= 1, code, detail)


def _check_synthesis(kind: NarrativeKind, subjects: Tuple[str, ...], cutoff: datetime,
                     claims: Tuple[NarrativeClaim, ...]) -> None:
    """claim の間の不変条件（PIT・一貫性・reviewed の閉包・subject の範囲・隠さない規則）。"""
    subject_set = set(subjects)
    refs = [ref for claim in claims for ref in claim.refs]
    by_predicate: Dict[Predicate, List[NarrativeClaim]] = {}
    for claim in claims:
        by_predicate.setdefault(claim.predicate, []).append(claim)

    # PIT: cutoff より後の ref は無い
    for ref in refs:
        for moment in ((ref.attached_at,) if isinstance(ref, EvidenceAttachmentRef) else
                       (ref.evidence_time,) if isinstance(ref, EvidenceItemRef) else
                       (ref.to_cutoff,) if isinstance(ref, ThemeChangeRef) else ()):
            _require(moment <= cutoff, "REF_AFTER_CUTOFF", ref.REF_TYPE)

    # 一貫性: 1 root につき 1 observation、同じ identity の ref は同じ内容（role の書き換えなし）
    observations: Dict[str, List[str]] = {}
    for ref in refs:
        if hasattr(ref, "observation_id"):
            observations.setdefault(ref.root_id, []).append(ref.observation_id)
    for values in observations.values():
        _single(values, "OBSERVATION_INCONSISTENT", "one observation per root at the cutoff")
    grouped: Dict[Tuple[str, ...], List[str]] = {}
    for ref in refs:
        if isinstance(ref, ThemeObservationRef):
            identity: Tuple[str, ...] = (ref.REF_TYPE, ref.root_id)
        elif isinstance(ref, EvidenceAttachmentRef):
            identity = (ref.REF_TYPE, ref.root_id, ref.observation_id, ref.attachment_key)
        elif isinstance(ref, EvidenceItemRef):
            identity = (ref.REF_TYPE, ref.ref_id)
        elif isinstance(ref, RelationAssertionRef):
            identity = (ref.REF_TYPE, ref.relation_assertion_id)
        else:
            continue
        grouped.setdefault(identity, []).append(_ref_sort_key(ref))
    for identity, values in grouped.items():
        if identity[0] == EvidenceAttachmentRef.REF_TYPE:
            roles = {json.loads(value)["role"] for value in values}
            _require(len(roles) == 1, "EVIDENCE_ROLE_RELABELLED", "same attachment cited with different roles")
        _single(values, "REF_INCONSISTENT", identity[0])

    # reviewed の閉包: 参照される Theme はすべて reviewed の observation ref を持つ
    reviewed = {ref.root_id for ref in refs if isinstance(ref, ThemeObservationRef)}
    referenced = {root for ref in refs for root in ref.roots()}
    _require(referenced <= reviewed, "UNREVIEWED_THEME_REFERENCE", "every referenced theme needs a reviewed observation")

    # subject の範囲
    for claim in claims:
        roots = set(claim.roots())
        if claim.predicate in RELATION_PREDICATES:
            _require(bool(roots & subject_set), "RELATION_OUTSIDE_SUBJECTS", claim.predicate.value)
        elif claim.predicate is Predicate.ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE:
            _require(bool(roots & subject_set), "ALTERNATIVE_OUTSIDE_SUBJECTS", claim.predicate.value)
        else:
            _require(roots <= subject_set, "CLAIM_OUTSIDE_SUBJECTS", claim.predicate.value)
    stated = {claim.roots()[0] for claim in by_predicate.get(Predicate.THEME_REVIEWED_STATE, [])}
    _require(subject_set <= stated, "SUBJECT_STATE_REQUIRED", "every subject needs a reviewed state claim")

    # 事実は subject の Theme に結び付いた evidence だけ（孤立した事実を作らない）
    attachments = [ref for ref in refs if isinstance(ref, EvidenceAttachmentRef)]
    for item in (ref for ref in refs if isinstance(ref, EvidenceItemRef)):
        _require(any(att.ref_id == item.ref_id and att.evidence_kind is item.evidence_kind and att.root_id in subject_set
                     for att in attachments), "ORPHAN_OBSERVED_FACT", "observed fact is not attached to a subject")

    # 隠さない: 争い・仮説の機構・無効化の evidence は claim として表に出す
    uncertain = {(claim.uncertainty_code, claim.roots()[0]) for claim in by_predicate.get(Predicate.IS_UNCERTAIN, [])}
    roles_by_root: Dict[str, set] = {}
    for att in attachments:
        roles_by_root.setdefault(att.root_id, set()).add(att.role)
    for root, roles in roles_by_root.items():
        if {EvidenceRole.SUPPORTS, EvidenceRole.CONTRADICTS} <= roles:
            _require((UncertaintyCode.CONTESTED_EVIDENCE, root) in uncertain, "CONTESTED_EVIDENCE_NOT_SURFACED",
                     "supporting and contradicting evidence need a CONTESTED_EVIDENCE claim")
        if EvidenceRole.SUPPORTS in roles:
            _require((UncertaintyCode.NO_SUPPORTING_EVIDENCE, root) not in uncertain, "UNCERTAINTY_CONTRADICTS_REFS",
                     UncertaintyCode.NO_SUPPORTING_EVIDENCE.value)
    certainty = {ref.root_id: ref.mechanism_certainty for ref in refs if isinstance(ref, ThemeObservationRef)}
    for claim in by_predicate.get(Predicate.RECORDS_MECHANISM_COMPONENT, []):
        root = claim.roots()[0]
        if certainty[root] is MechanismCertainty.HYPOTHESIZED_MECHANISM:
            _require((UncertaintyCode.MECHANISM_HYPOTHESIZED, root) in uncertain, "HYPOTHESIZED_MECHANISM_NOT_SURFACED",
                     "a hypothesized mechanism needs a MECHANISM_HYPOTHESIZED claim")
    surfaced = {(ref.root_id, ref.attachment_key) for claim in by_predicate.get(
        Predicate.INVALIDATING_EVIDENCE_ATTACHED, []) for ref in claim.refs if isinstance(ref, EvidenceAttachmentRef)}
    for att in attachments:
        if att.role is EvidenceRole.INVALIDATES:
            _require((att.root_id, att.attachment_key) in surfaced, "INVALIDATION_EVIDENCE_NOT_SURFACED",
                     "invalidating evidence needs an INVALIDATING_EVIDENCE_ATTACHED claim")
    recorded = {(ref.root_id, ref.condition_key) for claim in by_predicate.get(
        Predicate.RECORDS_INVALIDATION_CONDITION, []) for ref in claim.refs}
    for claim in by_predicate.get(Predicate.INVALIDATING_EVIDENCE_ATTACHED, []):
        condition = _of(claim.refs, InvalidationConditionRef)[0]
        _require((condition.root_id, condition.condition_key) in recorded, "INVALIDATION_CONDITION_NOT_RECORDED",
                 "invalidating evidence needs its recorded condition")


@dataclass(frozen=True, kw_only=True)
class NarrativeSynthesis:
    """ある cutoff の reviewed Theme についての claim の集合（派生・非 authority・非永続）。

    field は最小: 型・subject（非意味的な集合）・cutoff・knowledge の pin・入力 digest・claim の集合。
    運用 metadata（生成時刻・run id 等）は持たず、identity にも入らない。
    """
    kind: NarrativeKind
    subject_root_ids: Tuple[str, ...]
    cutoff: datetime
    knowledge_pins: Tuple[Tuple[str, str], ...]
    input_digest: str
    claims: Tuple[NarrativeClaim, ...]
    synthesis_id: str = field(init=False)

    def __post_init__(self) -> None:
        kind = _enum(self.kind, NarrativeKind, "UNKNOWN_NARRATIVE_KIND", "NarrativeSynthesis.kind")
        _require(isinstance(self.subject_root_ids, (tuple, list)), "INVALID_TYPE", "NarrativeSynthesis.subject_root_ids")
        subjects = tuple(_token(root, _ROOT_ID_RE, "INVALID_ROOT_ID", "NarrativeSynthesis.subject_root_ids")
                         for root in self.subject_root_ids)
        _require(len(set(subjects)) == len(subjects), "DUPLICATE_SUBJECT", "NarrativeSynthesis.subject_root_ids")
        if kind is NarrativeKind.THEME_STATE:
            _require(len(subjects) == 1, "THEME_STATE_REQUIRES_ONE_SUBJECT", "NarrativeSynthesis.subject_root_ids")
        else:
            _require(len(subjects) >= 2, "THEME_SET_REQUIRES_TWO_OR_MORE_SUBJECTS",
                     "NarrativeSynthesis.subject_root_ids")
            _require(len(subjects) <= MAX_SUBJECTS, "TOO_MANY_SUBJECTS", "NarrativeSynthesis.subject_root_ids")
        cutoff = _time(self.cutoff, "NarrativeSynthesis.cutoff")
        pins = _knowledge_pins(self.knowledge_pins)
        _token(self.input_digest, _DIGEST_RE, "INVALID_INPUT_DIGEST", "NarrativeSynthesis.input_digest")
        _require(isinstance(self.claims, (tuple, list)), "INVALID_TYPE", "NarrativeSynthesis.claims")
        claims = tuple(self.claims)
        _require(all(isinstance(claim, NarrativeClaim) for claim in claims), "INVALID_CLAIM", "NarrativeSynthesis.claims")
        _require(1 <= len(claims) <= MAX_CLAIMS, "CLAIM_COUNT_OUT_OF_BOUNDS", "NarrativeSynthesis.claims")
        _require(len({claim.claim_id for claim in claims}) == len(claims), "DUPLICATE_CLAIM", "NarrativeSynthesis.claims")
        subjects = tuple(sorted(subjects))                                             # 非意味的な集合（順位ではない）
        claims = tuple(sorted(claims, key=lambda claim: claim.claim_id))               # 非意味的な集合
        _check_synthesis(kind, subjects, cutoff, claims)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "subject_root_ids", subjects)
        object.__setattr__(self, "knowledge_pins", pins)
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "synthesis_id", content_id(SYNTHESIS_ID_PREFIX, canonical_json(self._identity_payload())))

    def _identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "kind": self.kind.value,
                "subject_root_ids": list(self.subject_root_ids), "cutoff": to_utc_iso(self.cutoff),
                "knowledge_pins": [{"name": name, "version": version} for name, version in self.knowledge_pins],
                "input_digest": self.input_digest, "claim_ids": [claim.claim_id for claim in self.claims]}

    @property
    def narrative_key(self) -> str:
        """同じ問い（型と subject の組）を表す key。cutoff・入力・claim に依らない（保存しない）。"""
        return content_id(NARRATIVE_KEY_PREFIX, canonical_json({"schema_version": SCHEMA_VERSION,
                                                                "kind": self.kind.value,
                                                                "subject_root_ids": list(self.subject_root_ids)}))

    def to_dict(self) -> Dict[str, Any]:
        payload = self._identity_payload()
        del payload["claim_ids"]
        return dict(payload, synthesis_id=self.synthesis_id, claims=[claim.to_dict() for claim in self.claims])

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "NarrativeSynthesis":
        """厳格な復元。未知 / 禁止 / 欠落 field・型違い・id の不一致・非 canonical な直列化はすべて拒否する。"""
        _mapping(data, ("schema_version", "synthesis_id", "kind", "subject_root_ids", "cutoff", "knowledge_pins",
                        "input_digest", "claims"), "synthesis")
        _require(_str(data, "schema_version") == SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", "synthesis")
        pins = []
        for pin in _list(data, "knowledge_pins"):
            _mapping(pin, ("name", "version"), "knowledge_pin")
            pins.append((_str(pin, "name"), _str(pin, "version")))
        subjects = _list(data, "subject_root_ids")
        synthesis = cls(kind=_str(data, "kind"), subject_root_ids=tuple(subjects), cutoff=_parse_time(data, "cutoff"),
                        knowledge_pins=tuple(pins), input_digest=_str(data, "input_digest"),
                        claims=tuple(NarrativeClaim.from_dict(claim) for claim in _list(data, "claims")))
        _require(_str(data, "synthesis_id") == synthesis.synthesis_id, "SYNTHESIS_ID_MISMATCH", "synthesis")
        _require(canonical_json(data) == synthesis.to_canonical_json(), "NON_CANONICAL_SERIALIZATION", "synthesis")
        return synthesis

    @classmethod
    def from_json(cls, text: Any) -> "NarrativeSynthesis":
        _require(isinstance(text, str), "INVALID_TYPE", "synthesis json")
        try:
            data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except ValueError as error:
            if isinstance(error, NarrativeModelError):
                raise
            raise NarrativeModelError("INVALID_JSON", "synthesis json") from None
        synthesis = cls.from_dict(data)
        _require(text == synthesis.to_canonical_json(), "NON_CANONICAL_SERIALIZATION", "synthesis json")
        return synthesis


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    keys = [key for key, _ in pairs]
    _require(len(set(keys)) == len(keys), "DUPLICATE_JSON_KEY", "synthesis json")
    return dict(pairs)


__all__ = [
    "ALLOWED_TRIPLES", "ASSERTION_CLASS_BY_PREDICATE", "AssertionClass", "CHANGE_FACETS", "CLAIM_ID_PREFIX",
    "CLAIM_SCHEMA_VERSION", "ChangeKind", "ClaimKind", "ComponentType", "DEFERRED_REF_TYPES", "EpistemicClass",
    "EvidenceAttachmentRef", "EvidenceItemRef", "EvidenceKind", "EvidenceRole", "EvidenceTimeQuality",
    "GovernancePosition", "INTERPRETATION_REF_TYPES", "InvalidationConditionRef", "MAX_CLAIMS", "MAX_KNOWLEDGE_PINS",
    "MAX_REFS_PER_CLAIM", "MAX_SUBJECTS", "MechanismCertainty", "MechanismComponentRef", "NARRATIVE_KEY_PREFIX",
    "NOT_ADOPTED_EPISTEMIC_CLASSES", "NarrativeClaim", "NarrativeKind", "NarrativeModelError", "NarrativeRef",
    "NarrativeSynthesis", "OBSERVED_FACT_EVIDENCE_KINDS", "OBSERVED_FACT_TIME_QUALITIES", "PREDICATE_SIGNATURES",
    "PROHIBITED_FIELDS", "PROHIBITED_REF_TYPES", "Predicate", "ProvenanceClass", "REF_ID_PREFIX_BY_KIND", "REF_TYPES",
    "RELATION_PREDICATES", "REVIEWED_POSITIONS", "RelationAssertionRef", "RelationType", "SCHEMA_VERSION",
    "SOURCE_ASSERTED_MEANING", "SYNTHESIS_ID_PREFIX", "SYNTHESIS_IS_NOT_AUTHORITY", "ThemeChangeRef",
    "ThemeObservationRef", "UNCERTAINTY_CLAIM_KIND", "UncertaintyCode", "canonical_json", "ref_from_dict",
]
