"""P6-B6B — monitoring の不変 record model と語彙（純）。

B6 は **governance authority ではない**（D-B6-1）。本 module が定義するのは次の 3 つだけである。

- `MonitoringFinding`: 条件が成立したことの **derived** record。既定で永続化しない（D-B6-2）。
- `MonitoringRunReport`: 1 回の run の **derived** 要約。authority ではない。
- `ReviewItemState`: finding を人間がどう扱ったかの **operational** record。governance decision ではない。

規律:

- identity は内容から決まる（content id）。finding identity に cutoff / run 時刻 / version / 表示文言を
  混ぜない（D-B6-3）。同じ状態は何度観測しても同じ finding になる。
- `salient_state` は自由な JSON ではない。`SalientStateKind` ごとに key 集合を凍結した typed value object で、
  値は bounded な文字列だけを取る。数値・時刻・score を構造的に持てない。
- score / 順位 / 確率 / 強度 / severity / 優先度は存在しない（D-B6-6）。category は名義尺度で順序を持たない。
- 現在時刻・乱数・IO・network を使わない。時刻はすべて呼び出し側が渡す aware datetime（D-B6-4）。
- 人間の処理 class は ACKNOWLEDGED / DISMISSED / DEFERRED の 3 つだけ。RESOLVED は人間が付けるものではなく、
  「今この finding が導出されない」という derived な事実である（D-B6-13 の分離）。
- governance 語彙（approve / reject / promote / execute / attach）を持たない。B5 の plan を authority 入力として
  信用する field も持たない（B5 RR-3 POLICY LOCK の継承）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware, from_iso, to_utc_iso
from ..themes.model import ProvenanceClass, canonical_json, is_root_id

MONITORING_FINDING_SCHEMA_VERSION = "theme_monitoring_finding:0.1.0"
MONITORING_RUN_REPORT_SCHEMA_VERSION = "theme_monitoring_run_report:0.1.0"
REVIEW_ITEM_STATE_SCHEMA_VERSION = "theme_monitoring_review_item_state:0.1.0"
MONITORING_VOCAB_VERSION = "theme_monitoring_vocabulary:0.1.0"
FINDING_ID_PREFIX = "thmfind"
RUN_ID_PREFIX = "thmrun"
REVIEW_STATE_ID_PREFIX = "thmrev"
MAX_REF_LEN = 200
MAX_TEXT_LEN = 240
MAX_KEY_LEN = 64
MAX_FACTS = 8
MAX_REFS = 24
MAX_DIAGNOSTICS = 64

#: finding は観測であって指示ではない（contract / test で凍結する文言）
FINDING_MEANING = "a deterministic observation that a condition holds for a subject"
#: finding が意味しないこと
FINDING_NON_MEANING = "an instruction to change any authority"
#: 人間の処理は「見た」であって「決めた」ではない
REVIEW_IS_NOT_GOVERNANCE = "a review disposition records that a person looked, not that a person decided"
#: 条件の意味が変わったら version を上げるのではなく condition_id を変える
CONDITION_ID_IS_SEMANTIC = "a condition_id names the meaning; a changed meaning needs a new condition_id"

_ID_RE: Dict[str, "re.Pattern[str]"] = {}
_USERINFO_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@")
_SECRET_QUERY_RE = re.compile(r"(?i)[?&](api[_-]?key|access[_-]?token|secret|signature|sig|password)=")
_DRIVE_PATH_RE = re.compile(r"(?:^|[\s\"'(\[])[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_:.\-|]*$")


class MonitoringModelError(ValueError):
    """fail closed。code は安定した語彙、detail は短い説明（本文・秘密値を含めない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _fail(code: str, detail: str = "") -> None:
    raise MonitoringModelError(code, detail)


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


def _token(value: object, name: str, *, max_len: int = MAX_REF_LEN) -> str:
    """identity を担う値。単一行・bounded に加えて、空白を含まない安定 token であることを要求する。"""
    text = _text(value, name, max_len=max_len, required=True)
    _require(bool(_TOKEN_RE.match(text)), "INVALID_TOKEN", f"{name} must be a stable token")
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
    pattern = _ID_RE.get(prefix)
    if pattern is None:
        pattern = _ID_RE[prefix] = re.compile(rf"^{re.escape(prefix)}_[0-9a-f]{{24}}$")
    return isinstance(value, str) and bool(pattern.match(value))


def _str(data: Mapping[str, object], key: str, default: Optional[str] = None) -> str:
    value = data.get(key, default)
    _require(isinstance(value, str), "INVALID_TYPE", f"{key} must be str")
    return str(value)


def _reject_unknown(data: Mapping[str, object], allowed: Sequence[str]) -> None:
    unknown = sorted(set(data) - set(allowed))
    _require(not unknown, "UNKNOWN_FIELD", f"unknown fields {unknown}")


def _pairs(value: object, name: str, *, max_items: int) -> Tuple[Tuple[str, str], ...]:
    """(name, value) の対を canonical に正規化する。dict でも対の列でも受ける。"""
    if isinstance(value, Mapping):
        items = list(value.items())
    else:
        _require(isinstance(value, (list, tuple)), "INVALID_TYPE", f"{name} must be a mapping or a sequence of pairs")
        items = []
        for item in value:
            _require(isinstance(item, (list, tuple)) and len(item) == 2, "INVALID_TYPE", f"{name} holds pairs")
            items.append((item[0], item[1]))
    _require(len(items) <= max_items, "TOO_MANY_ITEMS", f"{name} holds at most {max_items} entries")
    keys = [_token(k, f"{name} key", max_len=MAX_KEY_LEN) for k, _ in items]
    _require(len(keys) == len(set(keys)), "DUPLICATE_KEY", f"{name} names each key once")
    return tuple(sorted(((key, _token(raw, f"{name}[{key}]")) for key, (_, raw) in zip(keys, items)),
                        key=lambda pair: pair[0]))


# ---------------------------------------------------------------- 語彙


class MonitoringCategory(str, Enum):
    """名義尺度。順序を持たず、重要度 / 優先度 / 危険度の意味を持たない（D-B6-6）。"""

    EVIDENCE = "EVIDENCE"
    SEMANTIC = "SEMANTIC"
    LIFECYCLE = "LIFECYCLE"
    PROPOSAL = "PROPOSAL"
    DISCOVERY = "DISCOVERY"
    RELATION = "RELATION"
    INTEGRITY = "INTEGRITY"


#: 技術的 / 構造的な失敗を表す category（D-B6-9 で intelligence 側と分離する）
TECHNICAL_CATEGORIES: Tuple[MonitoringCategory, ...] = (MonitoringCategory.INTEGRITY,)


class MonitoringSubjectKind(str, Enum):
    """finding が何を指しているか。自由形式の subject type を作らない。"""

    THEME_ROOT = "THEME_ROOT"
    THEME_PROPOSAL = "THEME_PROPOSAL"
    EVIDENCE_PROPOSAL = "EVIDENCE_PROPOSAL"
    RELATION_EDGE = "RELATION_EDGE"
    RELATION_PROPOSAL = "RELATION_PROPOSAL"
    GOVERNANCE_CHAIN = "GOVERNANCE_CHAIN"
    AUTHORITY_STORE = "AUTHORITY_STORE"
    KNOWLEDGE_VERSION = "KNOWLEDGE_VERSION"


class SalientStateKind(str, Enum):
    """identity を担う状態の family。B6A MVP の条件群を覆う（D-B6-3 / §8）。"""

    EVIDENCE_ROLE_PRESENCE = "EVIDENCE_ROLE_PRESENCE"
    EVIDENCE_ABSENCE = "EVIDENCE_ABSENCE"
    FRESHNESS_THRESHOLD = "FRESHNESS_THRESHOLD"
    SEMANTIC_REVISION = "SEMANTIC_REVISION"
    LIFECYCLE_DIVERGENCE = "LIFECYCLE_DIVERGENCE"
    RETIRED_ROOT_EVIDENCE = "RETIRED_ROOT_EVIDENCE"
    DECISION_BACKLOG = "DECISION_BACKLOG"
    CHAIN_UNRESOLVED = "CHAIN_UNRESOLVED"
    DISCOVERY_OUTCOME = "DISCOVERY_OUTCOME"
    VERSION_DRIFT = "VERSION_DRIFT"
    RELATION_ENDPOINT_STATE = "RELATION_ENDPOINT_STATE"
    RELATION_PROPOSAL_CONFLICT = "RELATION_PROPOSAL_CONFLICT"
    RELATION_SOURCE_CONTESTED = "RELATION_SOURCE_CONTESTED"
    AUTHORITY_INTEGRITY = "AUTHORITY_INTEGRITY"


#: kind ごとに identity を担う key 集合を凍結する。過不足はどちらも拒否する。
SALIENT_STATE_KEYS: Mapping[SalientStateKind, Tuple[str, ...]] = {
    SalientStateKind.EVIDENCE_ROLE_PRESENCE: ("role", "theme_root_id"),
    SalientStateKind.EVIDENCE_ABSENCE: ("absence_kind", "theme_root_id"),
    SalientStateKind.FRESHNESS_THRESHOLD: ("theme_root_id", "threshold_token"),
    SalientStateKind.SEMANTIC_REVISION: ("observation_id", "theme_root_id"),
    SalientStateKind.LIFECYCLE_DIVERGENCE: ("evidence_condition", "governance_state", "theme_root_id"),
    SalientStateKind.RETIRED_ROOT_EVIDENCE: ("attachment_key", "theme_root_id"),
    SalientStateKind.DECISION_BACKLOG: ("proposal_id", "proposal_status", "threshold_token"),
    SalientStateKind.CHAIN_UNRESOLVED: ("chain_kind", "diagnostic_code", "subject_token"),
    SalientStateKind.DISCOVERY_OUTCOME: ("outcome_token", "proposal_id"),
    SalientStateKind.VERSION_DRIFT: ("from_version", "knowledge_name", "to_version"),
    SalientStateKind.RELATION_ENDPOINT_STATE: ("edge_key", "endpoint_role", "endpoint_state"),
    SalientStateKind.RELATION_PROPOSAL_CONFLICT: ("conflict_token", "edge_key", "relation_proposal_id"),
    SalientStateKind.RELATION_SOURCE_CONTESTED: ("edge_key", "role", "theme_root_id"),
    SalientStateKind.AUTHORITY_INTEGRITY: ("authority_name", "failure_class", "locator_token"),
}


class MonitoringRunStatus(str, Enum):
    """run の網羅性。`FAILED` は report に存在しない（report を出せない run は report を持たない）。"""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class ReviewDisposition(str, Enum):
    """人間が finding をどう扱ったか。governance decision の語彙（APPROVED / REJECTED）は持たない。

    `RESOLVED` は存在しない。条件が消えたことは「次の run で finding が導出されない」という derived な事実であり、
    人間が宣言するものではない。
    """

    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    DEFERRED = "DEFERRED"


# ---------------------------------------------------------------- salient state


@dataclass(frozen=True, kw_only=True)
class SalientState:
    """finding identity を担う最小の状態。任意 JSON ではなく、kind ごとに key 集合が凍結されている。

    値は bounded な token 文字列だけを取る。数値・時刻・score を構造的に保持できないため、
    「何日 stale か」「何件あるか」のような run ごとに動く量が identity に混入しない。
    """

    state_kind: SalientStateKind
    facts: Tuple[Tuple[str, str], ...]

    def __post_init__(self) -> None:
        kind = _enum(self.state_kind, SalientStateKind, "state_kind")
        normalized = _pairs(self.facts, "facts", max_items=MAX_FACTS)
        expected = SALIENT_STATE_KEYS[kind]
        actual = tuple(key for key, _ in normalized)
        _require(actual == expected, "SALIENT_STATE_KEY_MISMATCH",
                 f"{kind.value} requires exactly {list(expected)}")
        object.__setattr__(self, "facts", normalized)
        if "theme_root_id" in dict(normalized):
            _require(is_root_id(dict(normalized)["theme_root_id"]), "UNKNOWN_THEME_ROOT",
                     "theme_root_id must be a Theme root id")

    @property
    def fact_map(self) -> Dict[str, str]:
        return dict(self.facts)

    def to_plain(self) -> Dict[str, object]:
        return {"state_kind": self.state_kind.value, "facts": dict(self.facts)}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SalientState":
        _require(isinstance(data, Mapping), "INVALID_TYPE", "salient_state must be a mapping")
        _reject_unknown(data, ("state_kind", "facts"))
        facts = data.get("facts")
        _require(isinstance(facts, Mapping), "INVALID_TYPE", "facts must be a mapping")
        return cls(state_kind=_parse_enum(data.get("state_kind"), SalientStateKind, "state_kind"), facts=facts)


@dataclass(frozen=True, kw_only=True)
class MonitoringReference:
    """finding の根拠を監査するための参照。**identity を担わない**（provenance のみ）。

    参照 identity だけを保持し、本文・抜粋・引用を保持しない。
    """

    ref_kind: str
    ref_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_kind", _token(self.ref_kind, "ref_kind", max_len=MAX_KEY_LEN))
        object.__setattr__(self, "ref_id", _token(self.ref_id, "ref_id"))

    @property
    def reference_key(self) -> str:
        return f"{self.ref_kind}:{self.ref_id}"

    def to_plain(self) -> Dict[str, object]:
        return {"ref_kind": self.ref_kind, "ref_id": self.ref_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MonitoringReference":
        _require(isinstance(data, Mapping), "INVALID_TYPE", "reference must be a mapping")
        _reject_unknown(data, ("ref_kind", "ref_id"))
        return cls(ref_kind=_str(data, "ref_kind"), ref_id=_str(data, "ref_id"))


def _references(value: object, name: str) -> Tuple[MonitoringReference, ...]:
    _require(isinstance(value, (list, tuple)), "INVALID_TYPE", f"{name} must be a sequence")
    items = tuple(value)
    _require(len(items) <= MAX_REFS, "TOO_MANY_ITEMS", f"{name} holds at most {MAX_REFS} references")
    _require(all(isinstance(item, MonitoringReference) for item in items), "INVALID_TYPE",
             f"{name} holds MonitoringReference values")
    keys = [item.reference_key for item in items]
    _require(len(keys) == len(set(keys)), "DUPLICATE_REFERENCE", f"{name} names each reference once")
    return tuple(sorted(items, key=canonical_json))


def _codes(value: object, name: str) -> Tuple[str, ...]:
    _require(isinstance(value, (list, tuple)), "INVALID_TYPE", f"{name} must be a sequence")
    items = tuple(_token(item, name, max_len=MAX_KEY_LEN) for item in value)
    _require(len(items) <= MAX_DIAGNOSTICS, "TOO_MANY_ITEMS", f"{name} holds at most {MAX_DIAGNOSTICS} entries")
    _require(len(items) == len(set(items)), "DUPLICATE_CODE", f"{name} names each code once")
    return tuple(sorted(items))


# ---------------------------------------------------------------- finding


FINDING_FIELDS = ("schema_version", "monitoring_vocab_version", "finding_id", "condition_id", "condition_version",
                  "category", "subject_kind", "subject_ref", "salient_state", "message_key", "cutoff",
                  "ruleset_version", "knowledge_versions", "trigger_refs", "supporting_refs", "diagnostics")


@dataclass(frozen=True, kw_only=True)
class MonitoringFinding:
    """条件が成立したことの derived record。authority ではなく、既定で永続化しない。

    identity は「どの条件が・どの対象で・どんな状態として成立したか」だけで決まる。
    cutoff / ruleset version / knowledge version / 表示文言 / 参照 / diagnostics は provenance であり
    identity に入らない。したがって同じ状態は run を跨いで同じ finding になる。
    """

    schema_version: str = MONITORING_FINDING_SCHEMA_VERSION
    monitoring_vocab_version: str = MONITORING_VOCAB_VERSION
    finding_id: str
    condition_id: str
    condition_version: str = ""
    category: MonitoringCategory
    subject_kind: MonitoringSubjectKind
    subject_ref: str
    salient_state: SalientState
    message_key: str = ""
    cutoff: datetime
    ruleset_version: str = ""
    knowledge_versions: Tuple[Tuple[str, str], ...] = ()
    trigger_refs: Tuple[MonitoringReference, ...] = ()
    supporting_refs: Tuple[MonitoringReference, ...] = ()
    diagnostics: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(self.schema_version == MONITORING_FINDING_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 self.schema_version)
        _require(self.monitoring_vocab_version == MONITORING_VOCAB_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 self.monitoring_vocab_version)
        object.__setattr__(self, "condition_id", _token(self.condition_id, "condition_id", max_len=MAX_KEY_LEN))
        object.__setattr__(self, "condition_version", _text(self.condition_version, "condition_version",
                                                            max_len=MAX_KEY_LEN))
        category = _enum(self.category, MonitoringCategory, "category")
        subject_kind = _enum(self.subject_kind, MonitoringSubjectKind, "subject_kind")
        object.__setattr__(self, "subject_ref", _token(self.subject_ref, "subject_ref"))
        if subject_kind is MonitoringSubjectKind.THEME_ROOT:
            _require(is_root_id(self.subject_ref), "UNKNOWN_THEME_ROOT", "subject_ref must be a Theme root id")
        _require(isinstance(self.salient_state, SalientState), "INVALID_TYPE", "salient_state must be SalientState")
        _require(category in ALLOWED_CATEGORIES_BY_STATE_KIND[self.salient_state.state_kind],
                 "CATEGORY_STATE_MISMATCH",
                 f"{self.salient_state.state_kind.value} does not belong to {category.value}")
        object.__setattr__(self, "message_key", _text(self.message_key, "message_key", max_len=MAX_KEY_LEN))
        object.__setattr__(self, "cutoff", _aware(self.cutoff, "cutoff"))
        object.__setattr__(self, "ruleset_version", _text(self.ruleset_version, "ruleset_version", max_len=MAX_KEY_LEN))
        object.__setattr__(self, "knowledge_versions", _pairs(self.knowledge_versions, "knowledge_versions",
                                                              max_items=MAX_REFS))
        object.__setattr__(self, "trigger_refs", _references(self.trigger_refs, "trigger_refs"))
        object.__setattr__(self, "supporting_refs", _references(self.supporting_refs, "supporting_refs"))
        object.__setattr__(self, "diagnostics", _codes(self.diagnostics, "diagnostics"))
        _require(self.finding_id == _finding_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "finding_id does not match the observed condition and state")

    @classmethod
    def build(cls, *, condition_id: str, category: MonitoringCategory, subject_kind: MonitoringSubjectKind,
              subject_ref: str, salient_state: SalientState, cutoff: datetime, condition_version: str = "",
              message_key: str = "", ruleset_version: str = "", knowledge_versions=(), trigger_refs=(),
              supporting_refs=(), diagnostics=()) -> "MonitoringFinding":
        shell = object.__new__(cls)
        identity = dict(schema_version=MONITORING_FINDING_SCHEMA_VERSION, condition_id=condition_id,
                        category=category, subject_kind=subject_kind, subject_ref=subject_ref,
                        salient_state=salient_state)
        for name, value in identity.items():
            object.__setattr__(shell, name, value)
        return cls(finding_id=_finding_id(MonitoringFinding.identity_payload(shell)),
                   monitoring_vocab_version=MONITORING_VOCAB_VERSION, condition_version=condition_version,
                   message_key=message_key, cutoff=cutoff, ruleset_version=ruleset_version,
                   knowledge_versions=knowledge_versions, trigger_refs=trigger_refs,
                   supporting_refs=supporting_refs, diagnostics=diagnostics, **identity)

    def identity_payload(self) -> Dict[str, object]:
        """観測された事実そのもの。cutoff / version / 文言 / 参照 / diagnostics は含まない。"""
        return {"schema_version": self.schema_version, "condition_id": self.condition_id,
                "category": self.category.value, "subject_kind": self.subject_kind.value,
                "subject_ref": self.subject_ref, "salient_state": self.salient_state.to_plain()}

    def as_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "monitoring_vocab_version": self.monitoring_vocab_version,
            "finding_id": self.finding_id, "condition_id": self.condition_id,
            "condition_version": self.condition_version, "category": self.category.value,
            "subject_kind": self.subject_kind.value, "subject_ref": self.subject_ref,
            "salient_state": self.salient_state.to_plain(), "message_key": self.message_key,
            "cutoff": to_utc_iso(self.cutoff), "ruleset_version": self.ruleset_version,
            "knowledge_versions": dict(self.knowledge_versions),
            "trigger_refs": [r.to_plain() for r in self.trigger_refs],
            "supporting_refs": [r.to_plain() for r in self.supporting_refs], "diagnostics": list(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MonitoringFinding":
        _reject_unknown(data, FINDING_FIELDS)
        return cls(schema_version=_str(data, "schema_version"),
                   monitoring_vocab_version=_str(data, "monitoring_vocab_version"),
                   finding_id=_str(data, "finding_id"), condition_id=_str(data, "condition_id"),
                   condition_version=_str(data, "condition_version", ""),
                   category=_parse_enum(data.get("category"), MonitoringCategory, "category"),
                   subject_kind=_parse_enum(data.get("subject_kind"), MonitoringSubjectKind, "subject_kind"),
                   subject_ref=_str(data, "subject_ref"),
                   salient_state=SalientState.from_dict(data.get("salient_state") or {}),
                   message_key=_str(data, "message_key", ""), cutoff=from_iso(_str(data, "cutoff")),
                   ruleset_version=_str(data, "ruleset_version", ""),
                   knowledge_versions=data.get("knowledge_versions") or {},
                   trigger_refs=tuple(MonitoringReference.from_dict(r) for r in (data.get("trigger_refs") or ())),
                   supporting_refs=tuple(MonitoringReference.from_dict(r) for r in (data.get("supporting_refs") or ())),
                   diagnostics=tuple(data.get("diagnostics") or ()))


#: state kind ごとに許す category。技術的 integrity と intelligence の review condition を混ぜない（D-B6-9）
ALLOWED_CATEGORIES_BY_STATE_KIND: Mapping[SalientStateKind, Tuple[MonitoringCategory, ...]] = {
    SalientStateKind.EVIDENCE_ROLE_PRESENCE: (MonitoringCategory.EVIDENCE,),
    SalientStateKind.EVIDENCE_ABSENCE: (MonitoringCategory.EVIDENCE,),
    SalientStateKind.FRESHNESS_THRESHOLD: (MonitoringCategory.EVIDENCE,),
    SalientStateKind.SEMANTIC_REVISION: (MonitoringCategory.SEMANTIC,),
    SalientStateKind.LIFECYCLE_DIVERGENCE: (MonitoringCategory.LIFECYCLE,),
    SalientStateKind.RETIRED_ROOT_EVIDENCE: (MonitoringCategory.LIFECYCLE,),
    SalientStateKind.DECISION_BACKLOG: (MonitoringCategory.PROPOSAL,),
    SalientStateKind.CHAIN_UNRESOLVED: (MonitoringCategory.INTEGRITY,),
    SalientStateKind.DISCOVERY_OUTCOME: (MonitoringCategory.DISCOVERY,),
    SalientStateKind.VERSION_DRIFT: (MonitoringCategory.DISCOVERY,),
    SalientStateKind.RELATION_ENDPOINT_STATE: (MonitoringCategory.RELATION,),
    SalientStateKind.RELATION_PROPOSAL_CONFLICT: (MonitoringCategory.RELATION,),
    SalientStateKind.RELATION_SOURCE_CONTESTED: (MonitoringCategory.RELATION,),
    SalientStateKind.AUTHORITY_INTEGRITY: (MonitoringCategory.INTEGRITY,),
}


# ---------------------------------------------------------------- run report


RUN_REPORT_FIELDS = ("schema_version", "monitoring_vocab_version", "run_id", "cutoff", "ruleset_version",
                     "knowledge_versions", "input_digests", "status", "finding_ids", "unevaluated_conditions",
                     "diagnostics", "recorded_at")


@dataclass(frozen=True, kw_only=True)
class MonitoringRunReport:
    """1 回の run の derived 要約。authority ではない。

    `COMPLETE` は「要求されたすべての条件を評価できた」ことを意味する。authority が読めずに評価できなかった
    条件が 1 つでもあれば `PARTIAL` でなければならない。静かな無検出（finding 0 件の COMPLETE）を作らせない。
    """

    schema_version: str = MONITORING_RUN_REPORT_SCHEMA_VERSION
    monitoring_vocab_version: str = MONITORING_VOCAB_VERSION
    run_id: str
    cutoff: datetime
    ruleset_version: str
    knowledge_versions: Tuple[Tuple[str, str], ...] = ()
    input_digests: Tuple[Tuple[str, str], ...] = ()
    status: MonitoringRunStatus
    finding_ids: Tuple[str, ...] = ()
    unevaluated_conditions: Tuple[str, ...] = ()
    diagnostics: Tuple[str, ...] = ()
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == MONITORING_RUN_REPORT_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 self.schema_version)
        _require(self.monitoring_vocab_version == MONITORING_VOCAB_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 self.monitoring_vocab_version)
        object.__setattr__(self, "cutoff", _aware(self.cutoff, "cutoff"))
        object.__setattr__(self, "ruleset_version", _token(self.ruleset_version, "ruleset_version",
                                                           max_len=MAX_KEY_LEN))
        object.__setattr__(self, "knowledge_versions", _pairs(self.knowledge_versions, "knowledge_versions",
                                                              max_items=MAX_REFS))
        object.__setattr__(self, "input_digests", _pairs(self.input_digests, "input_digests", max_items=MAX_REFS))
        status = _enum(self.status, MonitoringRunStatus, "status")
        ids = tuple(_token(item, "finding_ids") for item in self.finding_ids)
        _require(all(_is_id(item, FINDING_ID_PREFIX) for item in ids), "INVALID_RECORD_ID",
                 "finding_ids holds monitoring finding ids")
        _require(len(ids) == len(set(ids)), "DUPLICATE_CODE", "finding_ids names each finding once")
        object.__setattr__(self, "finding_ids", tuple(sorted(ids)))
        object.__setattr__(self, "unevaluated_conditions", _codes(self.unevaluated_conditions,
                                                                  "unevaluated_conditions"))
        object.__setattr__(self, "diagnostics", _codes(self.diagnostics, "diagnostics"))
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))
        _require(self.recorded_at >= self.cutoff, "REPORT_BEFORE_CUTOFF", "a run cannot be recorded before its cutoff")
        if status is MonitoringRunStatus.COMPLETE:
            _require(self.unevaluated_conditions == (), "INCOMPLETE_RUN_MARKED_COMPLETE",
                     "a complete run leaves no condition unevaluated")
        else:
            _require(self.unevaluated_conditions != (), "PARTIAL_RUN_WITHOUT_REASON",
                     "a partial run names the conditions it could not evaluate")
        _require(self.run_id == _run_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "run_id does not match the run coordinates")

    @classmethod
    def build(cls, *, cutoff: datetime, ruleset_version: str, recorded_at: datetime,
              status: MonitoringRunStatus = MonitoringRunStatus.COMPLETE, knowledge_versions=(), input_digests=(),
              finding_ids=(), unevaluated_conditions=(), diagnostics=()) -> "MonitoringRunReport":
        shell = object.__new__(cls)
        identity = dict(schema_version=MONITORING_RUN_REPORT_SCHEMA_VERSION, cutoff=cutoff,
                        ruleset_version=ruleset_version, knowledge_versions=knowledge_versions,
                        input_digests=input_digests)
        for name, value in identity.items():
            object.__setattr__(shell, name, value)
        object.__setattr__(shell, "cutoff", _aware(cutoff, "cutoff"))
        object.__setattr__(shell, "knowledge_versions", _pairs(knowledge_versions, "knowledge_versions",
                                                               max_items=MAX_REFS))
        object.__setattr__(shell, "input_digests", _pairs(input_digests, "input_digests", max_items=MAX_REFS))
        return cls(run_id=_run_id(MonitoringRunReport.identity_payload(shell)),
                   monitoring_vocab_version=MONITORING_VOCAB_VERSION, status=status, finding_ids=finding_ids,
                   unevaluated_conditions=unevaluated_conditions, diagnostics=diagnostics, recorded_at=recorded_at,
                   **identity)

    def identity_payload(self) -> Dict[str, object]:
        """run の座標。**cutoff と version と入力 digest を含む**（finding とは逆に cutoff が identity を担う）。

        実行時刻・物理順・結果（findings / diagnostics）は含まない。
        """
        return {"schema_version": self.schema_version, "cutoff": to_utc_iso(self.cutoff),
                "ruleset_version": self.ruleset_version, "knowledge_versions": dict(self.knowledge_versions),
                "input_digests": dict(self.input_digests)}

    def as_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "monitoring_vocab_version": self.monitoring_vocab_version,
            "run_id": self.run_id, "cutoff": to_utc_iso(self.cutoff), "ruleset_version": self.ruleset_version,
            "knowledge_versions": dict(self.knowledge_versions), "input_digests": dict(self.input_digests),
            "status": self.status.value, "finding_ids": list(self.finding_ids),
            "unevaluated_conditions": list(self.unevaluated_conditions), "diagnostics": list(self.diagnostics),
            "recorded_at": to_utc_iso(self.recorded_at),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MonitoringRunReport":
        _reject_unknown(data, RUN_REPORT_FIELDS)
        return cls(schema_version=_str(data, "schema_version"),
                   monitoring_vocab_version=_str(data, "monitoring_vocab_version"), run_id=_str(data, "run_id"),
                   cutoff=from_iso(_str(data, "cutoff")), ruleset_version=_str(data, "ruleset_version"),
                   knowledge_versions=data.get("knowledge_versions") or {},
                   input_digests=data.get("input_digests") or {},
                   status=_parse_enum(data.get("status"), MonitoringRunStatus, "status"),
                   finding_ids=tuple(data.get("finding_ids") or ()),
                   unevaluated_conditions=tuple(data.get("unevaluated_conditions") or ()),
                   diagnostics=tuple(data.get("diagnostics") or ()),
                   recorded_at=from_iso(_str(data, "recorded_at")))


# ---------------------------------------------------------------- review state


REVIEW_STATE_FIELDS = ("schema_version", "monitoring_vocab_version", "review_state_id", "finding_id", "disposition",
                       "actor_class", "actor_ref", "note", "supersedes_review_state_id", "recorded_at")


@dataclass(frozen=True, kw_only=True)
class ReviewItemState:
    """finding を人間がどう扱ったかの operational record。**governance decision ではない**。

    記録するのは「人間がこの finding を見た」ことであって、「人間が Theme や relation について決めた」ことではない。
    後者が必要になった時点で、それは B3 / B5C の提案と決定 authority を通らなければならない。
    """

    schema_version: str = REVIEW_ITEM_STATE_SCHEMA_VERSION
    monitoring_vocab_version: str = MONITORING_VOCAB_VERSION
    review_state_id: str
    finding_id: str
    disposition: ReviewDisposition
    actor_class: ProvenanceClass = ProvenanceClass.HUMAN
    actor_ref: str
    note: str = ""
    supersedes_review_state_id: str = ""
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == REVIEW_ITEM_STATE_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 self.schema_version)
        _require(self.monitoring_vocab_version == MONITORING_VOCAB_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 self.monitoring_vocab_version)
        _require(_is_id(self.finding_id, FINDING_ID_PREFIX), "INVALID_RECORD_ID", "finding_id")
        _enum(self.disposition, ReviewDisposition, "disposition")
        _enum(self.actor_class, ProvenanceClass, "actor_class")
        _require(self.actor_class is ProvenanceClass.HUMAN, "FORBIDDEN_REVIEW_AUTHORITY",
                 "a monitoring finding is reviewed by a person")
        object.__setattr__(self, "actor_ref", _text(self.actor_ref, "actor_ref", max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "note", _text(self.note, "note", max_len=MAX_TEXT_LEN))
        object.__setattr__(self, "supersedes_review_state_id", _text(self.supersedes_review_state_id,
                                                                     "supersedes_review_state_id", max_len=MAX_REF_LEN))
        _require(self.supersedes_review_state_id == ""
                 or _is_id(self.supersedes_review_state_id, REVIEW_STATE_ID_PREFIX), "INVALID_RECORD_ID",
                 "supersedes_review_state_id")
        _require(self.supersedes_review_state_id != self.review_state_id, "INVALID_RECORD",
                 "a review state cannot supersede itself")
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))
        _require(self.review_state_id == _review_state_id(self.identity_payload()), "INVALID_RECORD_ID",
                 "review_state_id does not match the review content")

    @classmethod
    def build(cls, *, finding_id: str, disposition: ReviewDisposition, actor_ref: str, recorded_at: datetime,
              note: str = "", supersedes_review_state_id: str = "") -> "ReviewItemState":
        shell = object.__new__(cls)
        values = dict(schema_version=REVIEW_ITEM_STATE_SCHEMA_VERSION, finding_id=finding_id,
                      disposition=disposition, actor_class=ProvenanceClass.HUMAN, actor_ref=actor_ref, note=note,
                      supersedes_review_state_id=supersedes_review_state_id)
        for name, value in values.items():
            object.__setattr__(shell, name, value)
        return cls(review_state_id=_review_state_id(ReviewItemState.identity_payload(shell)),
                   monitoring_vocab_version=MONITORING_VOCAB_VERSION, recorded_at=recorded_at, **values)

    def identity_payload(self) -> Dict[str, object]:
        """人間が何を・どう扱ったか。`recorded_at` は provenance であり identity に入らない。"""
        return {"schema_version": self.schema_version, "finding_id": self.finding_id,
                "disposition": self.disposition.value, "actor_class": self.actor_class.value,
                "actor_ref": self.actor_ref, "note": self.note,
                "supersedes_review_state_id": self.supersedes_review_state_id}

    def as_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "monitoring_vocab_version": self.monitoring_vocab_version,
            "review_state_id": self.review_state_id, "finding_id": self.finding_id,
            "disposition": self.disposition.value, "actor_class": self.actor_class.value,
            "actor_ref": self.actor_ref, "note": self.note,
            "supersedes_review_state_id": self.supersedes_review_state_id,
            "recorded_at": to_utc_iso(self.recorded_at),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ReviewItemState":
        _reject_unknown(data, REVIEW_STATE_FIELDS)
        return cls(schema_version=_str(data, "schema_version"),
                   monitoring_vocab_version=_str(data, "monitoring_vocab_version"),
                   review_state_id=_str(data, "review_state_id"), finding_id=_str(data, "finding_id"),
                   disposition=_parse_enum(data.get("disposition"), ReviewDisposition, "disposition"),
                   actor_class=_parse_enum(data.get("actor_class"), ProvenanceClass, "actor_class"),
                   actor_ref=_str(data, "actor_ref"), note=_str(data, "note", ""),
                   supersedes_review_state_id=_str(data, "supersedes_review_state_id", ""),
                   recorded_at=from_iso(_str(data, "recorded_at")))


# ---------------------------------------------------------------- review chain（純。store は B6D）


class ReviewChainStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NONE = "NONE"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


@dataclass(frozen=True, kw_only=True)
class ReviewChainResolution:
    finding_id: str
    status: ReviewChainStatus
    terminal: Optional[ReviewItemState]
    chain: Tuple[str, ...]
    diagnostics: Tuple[str, ...]


def resolve_review_state(finding_id: str, states: Iterable[ReviewItemState]) -> ReviewChainResolution:
    """`supersedes_review_state_id` の graph だけで終端の処理を解く。物理順も `recorded_at` も勝者を決めない。

    governance authority の chain ではなく、「この finding を人間がどう扱ってきたか」の operational history である。
    """
    by_id: Dict[str, ReviewItemState] = {s.review_state_id: s for s in states}
    mine = {k: v for k, v in by_id.items() if v.finding_id == finding_id}
    if not mine:
        return ReviewChainResolution(finding_id=finding_id, status=ReviewChainStatus.NONE, terminal=None, chain=(),
                                     diagnostics=())
    for state_id in sorted(mine):
        predecessor = mine[state_id].supersedes_review_state_id
        if predecessor and predecessor not in mine:
            code = "CROSS_FINDING_PREDECESSOR" if predecessor in by_id else "DANGLING_PREDECESSOR"
            return ReviewChainResolution(finding_id=finding_id, status=ReviewChainStatus.INVALID, terminal=None,
                                         chain=(), diagnostics=(code,))
    children: Dict[str, List[str]] = {}
    starts: List[str] = []
    for state_id in sorted(mine):
        predecessor = mine[state_id].supersedes_review_state_id
        if predecessor == "":
            starts.append(state_id)
        else:
            children.setdefault(predecessor, []).append(state_id)
    diagnostics: List[str] = []
    if any(len(v) > 1 for v in children.values()):
        diagnostics.append("FORK")
    if len(starts) > 1:
        diagnostics.append("MULTIPLE_STARTS")
    if not starts:
        return ReviewChainResolution(finding_id=finding_id, status=ReviewChainStatus.INVALID, terminal=None,
                                     chain=(), diagnostics=("CYCLE",))
    if diagnostics:
        return ReviewChainResolution(finding_id=finding_id, status=ReviewChainStatus.UNRESOLVED, terminal=None,
                                     chain=(), diagnostics=tuple(diagnostics))
    order: List[str] = []
    seen = set()
    cursor: Optional[str] = starts[0]
    while cursor:
        if cursor in seen:
            return ReviewChainResolution(finding_id=finding_id, status=ReviewChainStatus.INVALID, terminal=None,
                                         chain=(), diagnostics=("CYCLE",))
        seen.add(cursor)
        order.append(cursor)
        following = children.get(cursor, [])
        cursor = following[0] if following else None
    if len(order) != len(mine):
        return ReviewChainResolution(finding_id=finding_id, status=ReviewChainStatus.INVALID, terminal=None,
                                     chain=(), diagnostics=("CYCLE",))
    return ReviewChainResolution(finding_id=finding_id, status=ReviewChainStatus.RESOLVED, terminal=mine[order[-1]],
                                 chain=tuple(order), diagnostics=())


# ---------------------------------------------------------------- identity / 直列化


def _finding_id(payload: Mapping[str, object]) -> str:
    return content_id(FINDING_ID_PREFIX, canonical_json(payload))


def _run_id(payload: Mapping[str, object]) -> str:
    return content_id(RUN_ID_PREFIX, canonical_json(payload))


def _review_state_id(payload: Mapping[str, object]) -> str:
    return content_id(REVIEW_STATE_ID_PREFIX, canonical_json(payload))


def canonical_monitoring_line(record) -> str:
    return canonical_json(record.as_dict()) + "\n"


def parse_monitoring_record(payload: Mapping[str, object]):
    _require(isinstance(payload, Mapping), "INVALID_TYPE", "record must be a mapping")
    schema = payload.get("schema_version")
    if schema == MONITORING_FINDING_SCHEMA_VERSION:
        return MonitoringFinding.from_dict(payload)
    if schema == MONITORING_RUN_REPORT_SCHEMA_VERSION:
        return MonitoringRunReport.from_dict(payload)
    if schema == REVIEW_ITEM_STATE_SCHEMA_VERSION:
        return ReviewItemState.from_dict(payload)
    _fail("UNSUPPORTED_SCHEMA_VERSION", f"unknown monitoring schema {schema!r}")


__all__ = ["ALLOWED_CATEGORIES_BY_STATE_KIND", "CONDITION_ID_IS_SEMANTIC", "FINDING_ID_PREFIX", "FINDING_MEANING",
           "FINDING_NON_MEANING", "MONITORING_FINDING_SCHEMA_VERSION", "MONITORING_RUN_REPORT_SCHEMA_VERSION",
           "MONITORING_VOCAB_VERSION", "REVIEW_IS_NOT_GOVERNANCE", "REVIEW_ITEM_STATE_SCHEMA_VERSION",
           "REVIEW_STATE_ID_PREFIX", "RUN_ID_PREFIX", "SALIENT_STATE_KEYS", "TECHNICAL_CATEGORIES",
           "MonitoringCategory", "MonitoringFinding", "MonitoringModelError", "MonitoringReference",
           "MonitoringRunReport", "MonitoringRunStatus", "MonitoringSubjectKind", "ReviewChainResolution",
           "ReviewChainStatus", "ReviewDisposition", "ReviewItemState", "SalientState", "SalientStateKind",
           "canonical_monitoring_line", "parse_monitoring_record", "resolve_review_state"]
