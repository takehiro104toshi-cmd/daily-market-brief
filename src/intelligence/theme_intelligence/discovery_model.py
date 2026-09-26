"""P6-B4C — deterministic Theme discovery の純 model（YAML を読まない、store を持たない、時計を持たない）。

- ruleset（VERSIONED KNOWLEDGE。B4B taxonomy / entity と同じ authority class）: `DiscoveryRuleset` / `DiscoveryRule` /
  `Predicate` / template 群。ruleset は taxonomy_version と catalog_version を **正確に pin** する（D-B4-9 / §23）。
- 入力の共通形: `DiscoveryInputRecord`（adapter が SourceDocument / NewsItem / Fact / Observation から作る）。
- 評価結果: `PredicateOutcome` / `RuleHit` / `RuleEvaluation` / `DiscoveryRunReport` / `DiscoveryResult`。

Discovery は提案するだけで、Theme root を作らず、Foundation に書かず、decision を変えず、score / rank / 順位を持たない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..themes.model import (MECHANISM_CATEGORIES, OTHER_CATEGORY, SINGLE_PERIOD_FRAMES, ComponentType, EvidenceKind,
                            EvidenceRole, EvidenceTimeBasis, EvidenceTimeQuality, ExpectedChange, LimitationCategory,
                            MechanismCertainty, OriginKind, ScopeDimension, SourceOrigin, normalize_text)
from .knowledge_loader import (MAX_NOTE_LEN, MAX_REF_LEN, MAX_TEXT_LEN, KnowledgeError, KnowledgeProvenance, checked_text,
                               is_digest, normalize_token, parse_enum, parse_version, plain_list_of_mappings, plain_mapping,
                               plain_str, plain_str_list, require_keys, sorted_unique, to_utc_iso)

DISCOVERY_RULESET_SCHEMA_VERSION = "theme_discovery_rules:0.1.0"
DISCOVERY_MODEL_VERSION = "theme_discovery:0.1.0"
DISCOVERY_ADAPTER_VERSION = "theme_discovery_adapter:0.1.0"
RUN_REPORT_SCHEMA_VERSION = "theme_discovery_run_report:0.1.0"
RULE_REF_PREFIX = "rule:"
#: template 由来の assertion / role の provenance_ref。rule id / version を含めない（等価な提案が rule を跨いで同一 id に収束するため）
TEMPLATE_PROVENANCE_REF = "discovery:mechanism_template"
#: THEME_CANDIDATE の certainty は固定（D-B4-6）
FIXED_CERTAINTY = MechanismCertainty.HYPOTHESIZED_MECHANISM
ALLOWED_PROPOSED_ROLES: Tuple[EvidenceRole, ...] = (EvidenceRole.SUPPORTS, EvidenceRole.CONTEXT)
BINDING_ENTITY = "${entity}"
BINDING_ENTITY_ATTRIBUTE_PREFIX = "${entity."
BINDING_SERIES = "${series}"
MAX_PREDICATE_DEPTH = 6
MAX_MIN_DISTINCT = 64


class DiscoveryError(ValueError):
    """discovery run の失敗（pin 不一致・時刻不正・入力型不正）。knowledge の失敗は `KnowledgeError`。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _fail(code: str, detail: str = "", *, where: str = "") -> None:
    raise KnowledgeError(code, detail, where=where)


def _require(condition: bool, code: str, detail: str = "", *, where: str = "") -> None:
    if not condition:
        _fail(code, detail, where=where)


# ---------------------------------------------------------------- vocabularies


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class RuleOutputType(str, Enum):
    EVIDENCE_CANDIDATE = "EVIDENCE_CANDIDATE"
    THEME_CANDIDATE = "THEME_CANDIDATE"


class InputKind(str, Enum):
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    NEWS_ITEM = "NEWS_ITEM"
    FACT = "FACT"
    OBSERVATION = "OBSERVATION"


EVIDENCE_KIND_BY_INPUT_KIND: Mapping[InputKind, EvidenceKind] = {
    InputKind.SOURCE_DOCUMENT: EvidenceKind.SOURCE_DOCUMENT,
    InputKind.NEWS_ITEM: EvidenceKind.NEWS_ITEM,
    InputKind.FACT: EvidenceKind.FACT,
    InputKind.OBSERVATION: EvidenceKind.OBSERVATION,
}


class MatchLevel(str, Enum):
    L1 = "L1"     # 構造化された明示値の完全一致
    L2 = "L2"     # 限定 text 面（title / headline / summary）に対する alias / slug の正規化完全一致


class PredicateKind(str, Enum):
    ALL = "ALL"
    ANY = "ANY"
    NOT = "NOT"
    ENTITY_PRESENT = "ENTITY_PRESENT"
    TAXONOMY_SIGNAL = "TAXONOMY_SIGNAL"
    FACT_TYPE = "FACT_TYPE"
    OBSERVATION_SERIES = "OBSERVATION_SERIES"
    SOURCE_KIND = "SOURCE_KIND"
    MIN_DISTINCT = "MIN_DISTINCT"


class DistinctDimension(str, Enum):
    INPUT_ID = "INPUT_ID"                # rule 単位（集約）のみ
    EVIDENCE_REF = "EVIDENCE_REF"        # rule 単位（集約）のみ
    ENTITY_ID = "ENTITY_ID"              # 入力単位・集約の両方
    TAXONOMY_TOKEN = "TAXONOMY_TOKEN"    # 入力単位・集約の両方


PER_INPUT_DISTINCT_DIMENSIONS = (DistinctDimension.ENTITY_ID, DistinctDimension.TAXONOMY_TOKEN)
PREDICATE_FIELDS = ("kind", "children", "entity_id", "slug", "fact_type", "series_id", "source_kind", "dimension", "min_count")


# ---------------------------------------------------------------- predicate


@dataclass(frozen=True, kw_only=True)
class Predicate:
    kind: PredicateKind
    children: Tuple["Predicate", ...] = ()
    entity_id: str = ""
    slug: str = ""
    fact_type: str = ""
    series_id: str = ""
    source_kind: Optional[OriginKind] = None
    dimension: Optional[DistinctDimension] = None
    min_count: int = 0

    def __post_init__(self) -> None:
        where = f"predicate[{self.kind.value if isinstance(self.kind, PredicateKind) else self.kind!r}]"
        _require(isinstance(self.kind, PredicateKind), "INVALID_VOCABULARY", f"{where} unknown predicate kind", where=where)
        _require(all(isinstance(c, Predicate) for c in self.children), "INVALID_TYPE", f"{where}.children", where=where)
        kind = self.kind
        scalar = {"entity_id": self.entity_id, "slug": self.slug, "fact_type": self.fact_type, "series_id": self.series_id}
        needed = {PredicateKind.ENTITY_PRESENT: "entity_id", PredicateKind.TAXONOMY_SIGNAL: "slug",
                  PredicateKind.FACT_TYPE: "fact_type", PredicateKind.OBSERVATION_SERIES: "series_id"}
        for name, value in scalar.items():
            _require(isinstance(value, str), "INVALID_TYPE", f"{where}.{name} must be a str", where=where)
            if needed.get(kind) == name:
                _require(value != "", "MISSING_FIELD", f"{where} requires {name}", where=where)
            else:
                _require(value == "", "UNKNOWN_FIELD", f"{where} does not take {name}", where=where)
        if kind in (PredicateKind.ALL, PredicateKind.ANY):
            _require(len(self.children) >= 1, "MISSING_FIELD", f"{where} requires children", where=where)
        elif kind is PredicateKind.NOT:
            _require(len(self.children) == 1, "INVALID_PREDICATE", f"{where} takes exactly one child", where=where)
        else:
            _require(not self.children, "UNKNOWN_FIELD", f"{where} does not take children", where=where)
        if kind is PredicateKind.SOURCE_KIND:
            _require(isinstance(self.source_kind, OriginKind), "MISSING_FIELD", f"{where} requires source_kind", where=where)
            _require(self.source_kind is not OriginKind.UNKNOWN, "INVALID_PREDICATE", f"{where} cannot require UNKNOWN origin",
                     where=where)
        else:
            _require(self.source_kind is None, "UNKNOWN_FIELD", f"{where} does not take source_kind", where=where)
        if kind is PredicateKind.MIN_DISTINCT:
            _require(isinstance(self.dimension, DistinctDimension), "MISSING_FIELD", f"{where} requires dimension", where=where)
            _require(isinstance(self.min_count, int) and not isinstance(self.min_count, bool) and 1 <= self.min_count <= MAX_MIN_DISTINCT,
                     "INVALID_PREDICATE", f"{where} min_count must be 1..{MAX_MIN_DISTINCT}", where=where)
        else:
            _require(self.dimension is None and self.min_count == 0, "UNKNOWN_FIELD", f"{where} does not take dimension / min_count",
                     where=where)
        _require(self.depth() <= MAX_PREDICATE_DEPTH, "INVALID_PREDICATE", f"{where} nesting exceeds {MAX_PREDICATE_DEPTH}", where=where)

    def depth(self) -> int:
        return 1 + max((c.depth() for c in self.children), default=0)

    def walk(self) -> Tuple["Predicate", ...]:
        out: List[Predicate] = [self]
        for child in self.children:
            out.extend(child.walk())
        return tuple(out)

    def to_plain(self) -> Dict[str, object]:
        data: Dict[str, object] = {"kind": self.kind.value}
        if self.children:
            data["children"] = [c.to_plain() for c in self.children]
        for name in ("entity_id", "slug", "fact_type", "series_id"):
            if getattr(self, name):
                data[name] = getattr(self, name)
        if self.source_kind is not None:
            data["source_kind"] = self.source_kind.value
        if self.dimension is not None:
            data["dimension"] = self.dimension.value
            data["min_count"] = self.min_count
        return data

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "Predicate":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=PREDICATE_FIELDS, required=("kind",), where=where)
        children = tuple(Predicate.from_plain(c, where=f"{where}.children[{i}]")
                         for i, c in enumerate(plain_list_of_mappings(mapping, "children", where=where))) if "children" in mapping else ()
        min_count = mapping.get("min_count", 0)
        _require(isinstance(min_count, int) and not isinstance(min_count, bool), "INVALID_TYPE", f"{where}.min_count must be an int",
                 where=where)
        return cls(kind=parse_enum(mapping["kind"], PredicateKind, where=f"{where}.kind"), children=children,
                   entity_id=plain_str(mapping, "entity_id", where=where, default=""), slug=plain_str(mapping, "slug", where=where, default=""),
                   fact_type=plain_str(mapping, "fact_type", where=where, default=""),
                   series_id=plain_str(mapping, "series_id", where=where, default=""),
                   source_kind=parse_enum(mapping["source_kind"], OriginKind, where=f"{where}.source_kind") if "source_kind" in mapping else None,
                   dimension=parse_enum(mapping["dimension"], DistinctDimension, where=f"{where}.dimension") if "dimension" in mapping else None,
                   min_count=int(min_count))


# ---------------------------------------------------------------- templates（人間 authoring の因果仮説。evidence は trigger に過ぎない）


def _binding_kind(value: str) -> str:
    if value == BINDING_ENTITY:
        return "entity"
    if value.startswith(BINDING_ENTITY_ATTRIBUTE_PREFIX) and value.endswith("}"):
        return "entity_attribute"
    if value == BINDING_SERIES:
        return "series"
    _require("${" not in value, "INVALID_BINDING", f"unknown binding placeholder {value!r}")
    return "literal"


@dataclass(frozen=True, kw_only=True)
class ComponentTemplate:
    category: str
    normalized_statement: str = ""
    typed_reference: str = ""          # literal / ${entity} / ${entity.<attribute>}

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", checked_text(self.category, "component.category", max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "normalized_statement", checked_text(self.normalized_statement, "component.normalized_statement",
                                                                     max_len=MAX_TEXT_LEN))
        _require(self.normalized_statement == normalize_text(self.normalized_statement), "NOT_NORMALIZED",
                 "component.normalized_statement must be normalized")
        object.__setattr__(self, "typed_reference", checked_text(self.typed_reference, "component.typed_reference", max_len=MAX_REF_LEN))
        _binding_kind(self.typed_reference)

    def to_plain(self) -> Dict[str, str]:
        return {"category": self.category, "normalized_statement": self.normalized_statement, "typed_reference": self.typed_reference}

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "ComponentTemplate":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=("category", "normalized_statement", "typed_reference"), required=("category",), where=where)
        return cls(category=plain_str(mapping, "category", where=where),
                   normalized_statement=plain_str(mapping, "normalized_statement", where=where, default=""),
                   typed_reference=plain_str(mapping, "typed_reference", where=where, default=""))


@dataclass(frozen=True, kw_only=True)
class ConsequenceTemplate:
    category: str
    observable_target: str             # literal / ${series}
    expected_change: ExpectedChange
    normalized_statement: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", checked_text(self.category, "consequence.category", max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "observable_target", checked_text(self.observable_target, "consequence.observable_target",
                                                                  max_len=MAX_REF_LEN, required=True))
        _require(isinstance(self.expected_change, ExpectedChange), "INVALID_VOCABULARY", "consequence.expected_change")
        object.__setattr__(self, "normalized_statement", checked_text(self.normalized_statement, "consequence.normalized_statement",
                                                                     max_len=MAX_TEXT_LEN))
        _require(self.normalized_statement == normalize_text(self.normalized_statement), "NOT_NORMALIZED",
                 "consequence.normalized_statement must be normalized")
        _binding_kind(self.observable_target)

    def to_plain(self) -> Dict[str, str]:
        return {"category": self.category, "observable_target": self.observable_target,
                "expected_change": self.expected_change.value, "normalized_statement": self.normalized_statement}

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "ConsequenceTemplate":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=("category", "observable_target", "expected_change", "normalized_statement"),
                     required=("category", "observable_target", "expected_change"), where=where)
        return cls(category=plain_str(mapping, "category", where=where), observable_target=plain_str(mapping, "observable_target", where=where),
                   expected_change=parse_enum(mapping["expected_change"], ExpectedChange, where=f"{where}.expected_change"),
                   normalized_statement=plain_str(mapping, "normalized_statement", where=where, default=""))


@dataclass(frozen=True, kw_only=True)
class MechanismTemplate:
    drivers: Tuple[ComponentTemplate, ...]
    channels: Tuple[ComponentTemplate, ...]
    domains: Tuple[ComponentTemplate, ...]
    consequences: Tuple[ConsequenceTemplate, ...]

    def __post_init__(self) -> None:
        for name, component_type in (("drivers", ComponentType.DRIVER), ("channels", ComponentType.TRANSMISSION_CHANNEL),
                                     ("domains", ComponentType.AFFECTED_DOMAIN)):
            items = getattr(self, name)
            _require(isinstance(items, tuple) and len(items) >= 1 and all(isinstance(i, ComponentTemplate) for i in items),
                     "INCOMPLETE_MECHANISM", f"mechanism_template.{name} requires at least one component")
            for item in items:
                _require(item.category in MECHANISM_CATEGORIES[component_type], "INVALID_VOCABULARY",
                         f"mechanism_template.{name} category {item.category!r} is not in the Foundation vocabulary")
                _require(item.category != OTHER_CATEGORY or item.normalized_statement != "", "MISSING_FIELD",
                         f"mechanism_template.{name}: OTHER requires normalized_statement")
        _require(isinstance(self.consequences, tuple) and len(self.consequences) >= 1
                 and all(isinstance(c, ConsequenceTemplate) for c in self.consequences), "INCOMPLETE_MECHANISM",
                 "mechanism_template.consequences requires at least one consequence")
        for item in self.consequences:
            _require(item.category in MECHANISM_CATEGORIES[ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE], "INVALID_VOCABULARY",
                     f"mechanism_template.consequences category {item.category!r} is not in the Foundation vocabulary")

    def to_plain(self) -> Dict[str, object]:
        return {"drivers": [d.to_plain() for d in self.drivers], "channels": [c.to_plain() for c in self.channels],
                "domains": [d.to_plain() for d in self.domains], "consequences": [c.to_plain() for c in self.consequences]}

    def bindings(self) -> Tuple[str, ...]:
        refs = [c.typed_reference for c in self.drivers + self.channels + self.domains] + [c.observable_target for c in self.consequences]
        return tuple(sorted({r for r in refs if "${" in r}))

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "MechanismTemplate":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=("drivers", "channels", "domains", "consequences"),
                     required=("drivers", "channels", "domains", "consequences"), where=where)
        comp = lambda key: tuple(ComponentTemplate.from_plain(item, where=f"{where}.{key}[{i}]")  # noqa: E731
                                 for i, item in enumerate(plain_list_of_mappings(mapping, key, where=where)))
        return cls(drivers=comp("drivers"), channels=comp("channels"), domains=comp("domains"),
                   consequences=tuple(ConsequenceTemplate.from_plain(item, where=f"{where}.consequences[{i}]")
                                      for i, item in enumerate(plain_list_of_mappings(mapping, "consequences", where=where))))


@dataclass(frozen=True, kw_only=True)
class SubjectTemplate:
    normalized_subject: str
    typed_reference: str = ""          # literal / ${entity}

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_subject", checked_text(self.normalized_subject, "subject.normalized_subject",
                                                                   max_len=MAX_TEXT_LEN, required=True))
        _require(self.normalized_subject == normalize_text(self.normalized_subject), "NOT_NORMALIZED", "subject must be normalized")
        object.__setattr__(self, "typed_reference", checked_text(self.typed_reference, "subject.typed_reference", max_len=MAX_REF_LEN))
        _binding_kind(self.typed_reference)

    def to_plain(self) -> Dict[str, str]:
        return {"normalized_subject": self.normalized_subject, "typed_reference": self.typed_reference}

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "SubjectTemplate":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=("normalized_subject", "typed_reference"), required=("normalized_subject",), where=where)
        return cls(normalized_subject=plain_str(mapping, "normalized_subject", where=where),
                   typed_reference=plain_str(mapping, "typed_reference", where=where, default=""))


@dataclass(frozen=True, kw_only=True)
class ScopeTokenTemplate:
    dimension: ScopeDimension
    value: str                         # literal / ${entity} / ${entity.<attribute>}

    def __post_init__(self) -> None:
        _require(isinstance(self.dimension, ScopeDimension), "INVALID_VOCABULARY", "scope.dimension")
        object.__setattr__(self, "value", checked_text(self.value, "scope.value", max_len=MAX_REF_LEN, required=True))
        _binding_kind(self.value)

    def to_plain(self) -> Dict[str, str]:
        return {"dimension": self.dimension.value, "value": self.value}

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "ScopeTokenTemplate":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=("dimension", "value"), required=("dimension", "value"), where=where)
        return cls(dimension=parse_enum(mapping["dimension"], ScopeDimension, where=f"{where}.dimension"),
                   value=plain_str(mapping, "value", where=where))


@dataclass(frozen=True, kw_only=True)
class InvalidationTemplate:
    condition_key: str
    normalized_statement: str
    observable_target: str = ""
    expected_change: ExpectedChange = ExpectedChange.UNSPECIFIED

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition_key", checked_text(self.condition_key, "invalidation.condition_key", max_len=64, required=True))
        object.__setattr__(self, "normalized_statement", checked_text(self.normalized_statement, "invalidation.normalized_statement",
                                                                     max_len=MAX_TEXT_LEN, required=True))
        _require(self.normalized_statement == normalize_text(self.normalized_statement), "NOT_NORMALIZED", "invalidation statement")
        object.__setattr__(self, "observable_target", checked_text(self.observable_target, "invalidation.observable_target",
                                                                  max_len=MAX_REF_LEN))
        _require(isinstance(self.expected_change, ExpectedChange), "INVALID_VOCABULARY", "invalidation.expected_change")

    def to_plain(self) -> Dict[str, str]:
        return {"condition_key": self.condition_key, "normalized_statement": self.normalized_statement,
                "observable_target": self.observable_target, "expected_change": self.expected_change.value}

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "InvalidationTemplate":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=("condition_key", "normalized_statement", "observable_target", "expected_change"),
                     required=("condition_key", "normalized_statement"), where=where)
        return cls(condition_key=plain_str(mapping, "condition_key", where=where),
                   normalized_statement=plain_str(mapping, "normalized_statement", where=where),
                   observable_target=plain_str(mapping, "observable_target", where=where, default=""),
                   expected_change=parse_enum(mapping["expected_change"], ExpectedChange, where=f"{where}.expected_change")
                   if "expected_change" in mapping else ExpectedChange.UNSPECIFIED)


@dataclass(frozen=True, kw_only=True)
class LimitationTemplate:
    category: LimitationCategory
    normalized_statement: str

    def __post_init__(self) -> None:
        _require(isinstance(self.category, LimitationCategory), "INVALID_VOCABULARY", "limitation.category")
        object.__setattr__(self, "normalized_statement", checked_text(self.normalized_statement, "limitation.normalized_statement",
                                                                     max_len=MAX_TEXT_LEN, required=True))
        _require(self.normalized_statement == normalize_text(self.normalized_statement), "NOT_NORMALIZED", "limitation statement")

    def to_plain(self) -> Dict[str, str]:
        return {"category": self.category.value, "normalized_statement": self.normalized_statement}

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "LimitationTemplate":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=("category", "normalized_statement"), required=("category", "normalized_statement"), where=where)
        return cls(category=parse_enum(mapping["category"], LimitationCategory, where=f"{where}.category"),
                   normalized_statement=plain_str(mapping, "normalized_statement", where=where))


# ---------------------------------------------------------------- rule


RULE_FIELDS = ("rule_id", "rule_version", "status", "input_kinds", "taxonomy_refs", "entity_refs", "predicate", "negative_predicates",
               "aggregate_predicates", "output_type", "proposed_role", "target_root_id", "subject_template", "mechanism_template",
               "scope_template", "invalidation_template", "limitations_template", "provenance")
RULE_REQUIRED_FIELDS = ("rule_id", "rule_version", "status", "input_kinds", "predicate", "output_type", "proposed_role", "provenance")
_RULE_ID_RE_TEXT = "^[a-z][a-z0-9_]{0,63}$"


@dataclass(frozen=True, kw_only=True)
class DiscoveryRule:
    rule_id: str
    rule_version: str
    status: RuleStatus
    input_kinds: Tuple[InputKind, ...]
    taxonomy_refs: Tuple[str, ...] = ()
    entity_refs: Tuple[str, ...] = ()
    predicate: Predicate
    negative_predicates: Tuple[Predicate, ...] = ()
    aggregate_predicates: Tuple[Predicate, ...] = ()
    output_type: RuleOutputType
    proposed_role: EvidenceRole
    target_root_id: str = ""
    subject_template: Optional[SubjectTemplate] = None
    mechanism_template: Optional[MechanismTemplate] = None
    scope_template: Tuple[ScopeTokenTemplate, ...] = ()
    invalidation_template: Tuple[InvalidationTemplate, ...] = ()
    limitations_template: Tuple[LimitationTemplate, ...] = ()
    provenance: KnowledgeProvenance

    def __post_init__(self) -> None:
        import re as _re  # local: slug 検査のみ
        where = f"rule[{self.rule_id!r}]"
        _require(isinstance(self.rule_id, str) and _re.match(_RULE_ID_RE_TEXT, self.rule_id) is not None, "INVALID_RULE_ID",
                 f"{where} rule_id must match {_RULE_ID_RE_TEXT}", where=where)
        parse_version(self.rule_version, where=f"{where}.rule_version")
        _require(isinstance(self.status, RuleStatus), "INVALID_VOCABULARY", f"{where}.status", where=where)
        kinds = tuple(self.input_kinds)
        _require(kinds and all(isinstance(k, InputKind) for k in kinds), "INVALID_VOCABULARY", f"{where}.input_kinds", where=where)
        object.__setattr__(self, "input_kinds", tuple(sorted(set(kinds), key=lambda k: k.value)))
        object.__setattr__(self, "taxonomy_refs", sorted_unique(self.taxonomy_refs, where=f"{where}.taxonomy_refs"))
        object.__setattr__(self, "entity_refs", sorted_unique(self.entity_refs, where=f"{where}.entity_refs"))
        _require(isinstance(self.predicate, Predicate), "INVALID_TYPE", f"{where}.predicate", where=where)
        _require(all(isinstance(p, Predicate) for p in self.negative_predicates), "INVALID_TYPE", f"{where}.negative_predicates", where=where)
        _require(all(isinstance(p, Predicate) and p.kind is PredicateKind.MIN_DISTINCT for p in self.aggregate_predicates),
                 "INVALID_PREDICATE", f"{where}.aggregate_predicates must be MIN_DISTINCT predicates", where=where)
        for predicate in (self.predicate,) + tuple(self.negative_predicates):
            for node in predicate.walk():
                if node.kind is PredicateKind.MIN_DISTINCT:
                    _require(node.dimension in PER_INPUT_DISTINCT_DIMENSIONS, "INVALID_PREDICATE",
                             f"{where}: per-input MIN_DISTINCT supports only ENTITY_ID / TAXONOMY_TOKEN", where=where)
                if node.kind is PredicateKind.ENTITY_PRESENT:
                    _require(node.entity_id in self.entity_refs, "UNDECLARED_ENTITY_REF",
                             f"{where} predicate uses {node.entity_id!r} which is not in entity_refs", where=where)
                if node.kind is PredicateKind.TAXONOMY_SIGNAL:
                    _require(node.slug in self.taxonomy_refs, "UNDECLARED_TAXONOMY_REF",
                             f"{where} predicate uses {node.slug!r} which is not in taxonomy_refs", where=where)
        _require(isinstance(self.output_type, RuleOutputType), "INVALID_VOCABULARY", f"{where}.output_type", where=where)
        _require(isinstance(self.proposed_role, EvidenceRole) and self.proposed_role in ALLOWED_PROPOSED_ROLES, "FORBIDDEN_ROLE",
                 f"{where} proposed_role must be SUPPORTS or CONTEXT", where=where)
        object.__setattr__(self, "target_root_id", checked_text(self.target_root_id, f"{where}.target_root_id", max_len=MAX_REF_LEN))
        if self.output_type is RuleOutputType.THEME_CANDIDATE:
            _require(self.subject_template is not None, "INCOMPLETE_MECHANISM", f"{where} THEME_CANDIDATE requires subject_template", where=where)
            _require(self.mechanism_template is not None, "INCOMPLETE_MECHANISM", f"{where} THEME_CANDIDATE requires mechanism_template",
                     where=where)
            frames = [s for s in self.scope_template if s.dimension is ScopeDimension.PERIOD_FRAME]
            _require(len(frames) == 1, "INCOMPLETE_SCOPE", f"{where} scope_template requires exactly one PERIOD_FRAME", where=where)
            _require(frames[0].value not in SINGLE_PERIOD_FRAMES, "INCOMPLETE_SCOPE", f"{where} PERIOD_FRAME must not be single", where=where)
            _require(len(self.invalidation_template) >= 1, "MISSING_INVALIDATION", f"{where} requires at least one invalidation condition",
                     where=where)
            keys = [i.condition_key for i in self.invalidation_template]
            _require(len(set(keys)) == len(keys), "DUPLICATE_KEY", f"{where} invalidation condition keys must be unique", where=where)
            _require(self.target_root_id == "", "INVALID_RULE", f"{where} THEME_CANDIDATE does not take target_root_id", where=where)
            self._check_bindings(where)
        else:
            _require(self.subject_template is None and self.mechanism_template is None and not self.scope_template
                     and not self.invalidation_template and not self.limitations_template, "UNKNOWN_FIELD",
                     f"{where} EVIDENCE_CANDIDATE does not take templates", where=where)
        _require(isinstance(self.provenance, KnowledgeProvenance), "INVALID_TYPE", f"{where}.provenance", where=where)

    def _check_bindings(self, where: str) -> None:
        refs = list(self.mechanism_template.bindings()) + [s.value for s in self.scope_template if "${" in s.value]
        if self.subject_template.typed_reference and "${" in self.subject_template.typed_reference:
            refs.append(self.subject_template.typed_reference)
        kinds = {_binding_kind(r) for r in refs}
        if kinds & {"entity", "entity_attribute"}:
            _require(len(self.entity_refs) == 1, "AMBIGUOUS_BINDING",
                     f"{where} uses ${{entity}} bindings but declares {len(self.entity_refs)} entity_refs (exactly one required)", where=where)
        if "series" in kinds:
            series = {n.series_id for n in self.predicate.walk() if n.kind is PredicateKind.OBSERVATION_SERIES}
            _require(len(series) == 1, "AMBIGUOUS_BINDING", f"{where} uses ${{series}} but has {len(series)} OBSERVATION_SERIES predicates",
                     where=where)

    @property
    def rule_ref(self) -> str:
        return RULE_REF_PREFIX + self.rule_id

    def series_binding(self) -> str:
        series = sorted({n.series_id for n in self.predicate.walk() if n.kind is PredicateKind.OBSERVATION_SERIES})
        return series[0] if len(series) == 1 else ""

    def semantic_payload(self) -> Dict[str, object]:
        return {
            "rule_id": self.rule_id, "rule_version": self.rule_version, "status": self.status.value,
            "input_kinds": [k.value for k in self.input_kinds], "taxonomy_refs": list(self.taxonomy_refs),
            "entity_refs": list(self.entity_refs), "predicate": self.predicate.to_plain(),
            "negative_predicates": [p.to_plain() for p in self.negative_predicates],
            "aggregate_predicates": [p.to_plain() for p in self.aggregate_predicates],
            "output_type": self.output_type.value, "proposed_role": self.proposed_role.value, "target_root_id": self.target_root_id,
            "subject_template": self.subject_template.to_plain() if self.subject_template else None,
            "mechanism_template": self.mechanism_template.to_plain() if self.mechanism_template else None,
            "scope_template": [s.to_plain() for s in self.scope_template],
            "invalidation_template": [i.to_plain() for i in self.invalidation_template],
            "limitations_template": [l.to_plain() for l in self.limitations_template],
            "provenance": self.provenance.to_plain(),
        }

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "DiscoveryRule":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=RULE_FIELDS, required=RULE_REQUIRED_FIELDS, where=where)
        preds = lambda key: tuple(Predicate.from_plain(item, where=f"{where}.{key}[{i}]")  # noqa: E731
                                  for i, item in enumerate(plain_list_of_mappings(mapping, key, where=where))) if key in mapping else ()
        output_type = parse_enum(mapping["output_type"], RuleOutputType, where=f"{where}.output_type")
        return cls(
            rule_id=plain_str(mapping, "rule_id", where=where), rule_version=plain_str(mapping, "rule_version", where=where),
            status=parse_enum(mapping["status"], RuleStatus, where=f"{where}.status"),
            input_kinds=tuple(parse_enum(k, InputKind, where=f"{where}.input_kinds") for k in plain_str_list(mapping, "input_kinds", where=where)),
            taxonomy_refs=plain_str_list(mapping, "taxonomy_refs", where=where), entity_refs=plain_str_list(mapping, "entity_refs", where=where),
            predicate=Predicate.from_plain(mapping["predicate"], where=f"{where}.predicate"),
            negative_predicates=preds("negative_predicates"), aggregate_predicates=preds("aggregate_predicates"),
            output_type=output_type, proposed_role=parse_enum(mapping["proposed_role"], EvidenceRole, where=f"{where}.proposed_role"),
            target_root_id=plain_str(mapping, "target_root_id", where=where, default=""),
            subject_template=SubjectTemplate.from_plain(mapping["subject_template"], where=f"{where}.subject_template")
            if "subject_template" in mapping else None,
            mechanism_template=MechanismTemplate.from_plain(mapping["mechanism_template"], where=f"{where}.mechanism_template")
            if "mechanism_template" in mapping else None,
            scope_template=tuple(ScopeTokenTemplate.from_plain(item, where=f"{where}.scope_template[{i}]")
                                 for i, item in enumerate(plain_list_of_mappings(mapping, "scope_template", where=where)))
            if "scope_template" in mapping else (),
            invalidation_template=tuple(InvalidationTemplate.from_plain(item, where=f"{where}.invalidation_template[{i}]")
                                        for i, item in enumerate(plain_list_of_mappings(mapping, "invalidation_template", where=where)))
            if "invalidation_template" in mapping else (),
            limitations_template=tuple(LimitationTemplate.from_plain(item, where=f"{where}.limitations_template[{i}]")
                                       for i, item in enumerate(plain_list_of_mappings(mapping, "limitations_template", where=where)))
            if "limitations_template" in mapping else (),
            provenance=KnowledgeProvenance.from_plain(mapping["provenance"], where=f"{where}.provenance"),
        )


# ---------------------------------------------------------------- ruleset snapshot


@dataclass(frozen=True, kw_only=True)
class DiscoveryRuleset:
    schema_version: str = DISCOVERY_RULESET_SCHEMA_VERSION
    ruleset_version: str
    published_at: datetime
    content_digest: str
    taxonomy_version: str
    catalog_version: str
    rules: Tuple[DiscoveryRule, ...]
    _by_id: Mapping[str, DiscoveryRule] = field(init=False, repr=False, compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        where = f"ruleset[{self.ruleset_version}]"
        _require(self.schema_version == DISCOVERY_RULESET_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version, where=where)
        parse_version(self.ruleset_version, where=f"{where}.ruleset_version")
        parse_version(self.taxonomy_version, where=f"{where}.taxonomy_version")
        parse_version(self.catalog_version, where=f"{where}.catalog_version")
        _require(isinstance(self.published_at, datetime) and self.published_at.tzinfo is not None, "INVALID_DATETIME",
                 f"{where}.published_at must be aware", where=where)
        _require(is_digest(self.content_digest), "INVALID_DIGEST", f"{where}.content_digest", where=where)
        _require(isinstance(self.rules, tuple) and all(isinstance(r, DiscoveryRule) for r in self.rules), "INVALID_TYPE",
                 f"{where}.rules", where=where)
        rules = tuple(sorted(self.rules, key=lambda r: r.rule_id))
        by_id: Dict[str, DiscoveryRule] = {}
        pairs = set()
        for rule in rules:
            _require(rule.rule_id not in by_id, "DUPLICATE_RULE", f"rule_id {rule.rule_id!r} appears twice", where=where)
            _require((rule.rule_id, rule.rule_version) not in pairs, "DUPLICATE_RULE", rule.rule_id, where=where)
            pairs.add((rule.rule_id, rule.rule_version))
            by_id[rule.rule_id] = rule
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "_by_id", by_id)

    def rule(self, rule_id: str) -> Optional[DiscoveryRule]:
        return self._by_id.get(rule_id)

    def in_force_rules(self) -> Tuple[DiscoveryRule, ...]:
        return tuple(r for r in self.rules if r.status is RuleStatus.ACTIVE)

    def semantic_payload(self) -> Dict[str, object]:
        return {"schema_version": self.schema_version, "ruleset_version": self.ruleset_version,
                "published_at": to_utc_iso(self.published_at), "taxonomy_version": self.taxonomy_version,
                "catalog_version": self.catalog_version, "rules": [r.semantic_payload() for r in self.rules]}


# ---------------------------------------------------------------- 入力の共通形（adapter の出力）


@dataclass(frozen=True, kw_only=True)
class EntityHit:
    entity_id: str
    level: MatchLevel
    matched_by: str            # structured_ref / identifier / safe_alias / context_alias
    surface: str = ""
    field_name: str = ""


@dataclass(frozen=True, kw_only=True)
class TaxonomyHit:
    slug: str
    level: MatchLevel
    matched_by: str            # structured_token / slug / alias
    surface: str = ""
    field_name: str = ""


@dataclass(frozen=True, kw_only=True)
class DiscoveryInputRecord:
    input_kind: InputKind
    input_id: str                                     # Foundation ref_id（news_ / doc_ / fact_ / obs_）
    source_origin: SourceOrigin
    evidence_time: Optional[datetime]
    evidence_time_basis: EvidenceTimeBasis
    evidence_time_quality: EvidenceTimeQuality
    evidence_date: str = ""
    known_at: Optional[datetime] = None
    structured_entity_refs: Tuple[Tuple[str, str, str], ...] = ()   # (kind, value, provenance) の生の明示参照
    entity_hits: Tuple[EntityHit, ...] = ()
    taxonomy_tokens: Tuple[str, ...] = ()                            # 構造化 slug（L1）。現行 model は供給しないため通常空
    taxonomy_hits: Tuple[TaxonomyHit, ...] = ()
    fact_type: str = ""
    observation_series: str = ""
    source_kind: OriginKind = OriginKind.UNKNOWN
    bounded_text_surfaces: Tuple[Tuple[str, str], ...] = ()          # (field, text)
    upstream_schema_version: str = ""
    adapter_version: str = DISCOVERY_ADAPTER_VERSION
    diagnostics: Tuple[str, ...] = ()

    @property
    def evidence_kind(self) -> EvidenceKind:
        return EVIDENCE_KIND_BY_INPUT_KIND[self.input_kind]

    def entity_ids(self) -> Tuple[str, ...]:
        return tuple(sorted({h.entity_id for h in self.entity_hits}))

    def taxonomy_slugs(self) -> Tuple[str, ...]:
        return tuple(sorted(set(self.taxonomy_tokens) | {h.slug for h in self.taxonomy_hits}))


@dataclass(frozen=True, kw_only=True)
class ExcludedInput:
    input_id: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class AdapterResult:
    records: Tuple[DiscoveryInputRecord, ...]
    excluded: Tuple[ExcludedInput, ...]
    origin_groups: Tuple[Tuple[str, Tuple[str, ...]], ...]   # (origin_key, input ids) 同一 origin の入力（独立数ではない）
    diagnostics: Tuple[str, ...] = ()


# ---------------------------------------------------------------- 評価結果


@dataclass(frozen=True, kw_only=True)
class PredicateHit:
    kind: str            # ENTITY / TAXONOMY / FACT_TYPE / OBSERVATION_SERIES / SOURCE_KIND
    value: str
    level: MatchLevel


@dataclass(frozen=True, kw_only=True)
class PredicateOutcome:
    matched: bool
    hits: Tuple[PredicateHit, ...] = ()

    @property
    def l1_hits(self) -> Tuple[PredicateHit, ...]:
        return tuple(h for h in self.hits if h.level is MatchLevel.L1)

    @property
    def l2_hits(self) -> Tuple[PredicateHit, ...]:
        return tuple(h for h in self.hits if h.level is MatchLevel.L2)


@dataclass(frozen=True, kw_only=True)
class RuleHit:
    rule_id: str
    input_id: str
    l1_hits: Tuple[PredicateHit, ...]
    l2_hits: Tuple[PredicateHit, ...]


@dataclass(frozen=True, kw_only=True)
class RuleEvaluation:
    rule_id: str
    rule_version: str
    status: RuleStatus
    output_type: RuleOutputType
    candidate_input_ids: Tuple[str, ...]
    matched_input_ids: Tuple[str, ...]
    l1_hit_count: int
    l2_hit_count: int
    negative_exclusions: Tuple[str, ...]          # 除外された input id
    aggregate_satisfied: bool
    emitted_proposal_ids: Tuple[str, ...]
    converged_proposal_ids: Tuple[str, ...]       # 他 rule も同じ id を出した（識別は同一のまま）
    diagnostics: Tuple[str, ...]

    def to_plain(self) -> Dict[str, object]:
        return {"rule_id": self.rule_id, "rule_version": self.rule_version, "status": self.status.value,
                "output_type": self.output_type.value, "candidate_input_ids": list(self.candidate_input_ids),
                "matched_input_ids": list(self.matched_input_ids), "l1_hit_count": self.l1_hit_count,
                "l2_hit_count": self.l2_hit_count, "negative_exclusions": list(self.negative_exclusions),
                "aggregate_satisfied": self.aggregate_satisfied, "emitted_proposal_ids": list(self.emitted_proposal_ids),
                "converged_proposal_ids": list(self.converged_proposal_ids), "diagnostics": list(self.diagnostics)}


@dataclass(frozen=True, kw_only=True)
class DiscoveryRunReport:
    """derived / 再構築可能。authority ではない。score / rank / stance を持たない。"""
    schema_version: str = RUN_REPORT_SCHEMA_VERSION
    discovery_model_version: str = DISCOVERY_MODEL_VERSION
    adapter_version: str = DISCOVERY_ADAPTER_VERSION
    cutoff: datetime
    run_created_at: datetime
    taxonomy_version: str
    catalog_version: str
    ruleset_version: str
    input_count: int
    normalized_input_count: int
    excluded_inputs: Tuple[ExcludedInput, ...]
    origin_groups: Tuple[Tuple[str, Tuple[str, ...]], ...]
    rule_evaluations: Tuple[RuleEvaluation, ...]
    rule_hits: Tuple[RuleHit, ...]
    proposal_ids: Tuple[str, ...]
    suppressed_existing_ids: Tuple[str, ...]
    dedup_review_ids: Tuple[str, ...]
    diagnostics: Tuple[str, ...]

    def to_plain(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "discovery_model_version": self.discovery_model_version,
            "adapter_version": self.adapter_version, "cutoff": to_utc_iso(self.cutoff), "run_created_at": to_utc_iso(self.run_created_at),
            "taxonomy_version": self.taxonomy_version, "catalog_version": self.catalog_version, "ruleset_version": self.ruleset_version,
            "input_count": self.input_count, "normalized_input_count": self.normalized_input_count,
            "excluded_inputs": [{"input_id": e.input_id, "reason": e.reason} for e in self.excluded_inputs],
            "origin_groups": [{"origin_key": k, "input_ids": list(v)} for k, v in self.origin_groups],
            "rule_evaluations": [e.to_plain() for e in self.rule_evaluations],
            "rule_hits": [{"rule_id": h.rule_id, "input_id": h.input_id, "l1": [(x.kind, x.value) for x in h.l1_hits],
                           "l2": [(x.kind, x.value) for x in h.l2_hits]} for h in self.rule_hits],
            "proposal_ids": list(self.proposal_ids), "suppressed_existing_ids": list(self.suppressed_existing_ids),
            "dedup_review_ids": list(self.dedup_review_ids), "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, kw_only=True)
class DiscoveryResult:
    proposals: Tuple[object, ...]          # B3 Proposal（EvidenceCandidate / ThemeCandidate / DedupReview）。append 候補
    run_report: DiscoveryRunReport
