"""P6-B4B — Entity catalog の versioned knowledge model（純 model。YAML を読まない）。

- `EntityType`: 監督者決定 D-B4-2 の 9 種のみ。各 type は Foundation `ThemeEntityKind` に 1:1 で写像し、entity_id の
  接頭辞は Foundation kind の値（`company:` 等）。PERSON / TICKER / TECHNOLOGY / POLICY_PROGRAM は語彙に存在しない。
- `EntityIdentifier`: 型付き識別子（TICKER / INSTRUMENT_ID / ISO_COUNTRY / ISO_CURRENCY）。ticker は identifier であって
  identity ではない。
- `EntityRecord`: entity_id（`<kind>:<immutable-slug>`）、canonical_name、aliases_safe / aliases_context ＋ context_terms、
  identifiers、attributes、valid_from / valid_to（世界時間の存在期間。開始含む・終了含まない）、superseded_by、
  provenance、since_version、retired_in_version（catalog 上の retire。世界時間の主張ではない）。
- `EntityCatalogSnapshot`: schema_version / catalog_version / published_at / content_digest / entities。構築時に
  id / slug 一意、safe alias 所有の一意、context alias の shadow 禁止、identifier 衝突、lifecycle 整合を検証し fail closed。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Mapping, Optional, Tuple

from ..themes.model import ThemeEntityKind
from .knowledge_loader import (MAX_NOTE_LEN, MAX_REF_LEN, MAX_TEXT_LEN, KnowledgeError, KnowledgeProvenance, checked_text,
                               is_digest, is_slug, normalize_token, parse_date, parse_enum, parse_version, plain_list_of_mappings,
                               plain_mapping, plain_str, plain_str_list, plain_str_mapping, require_keys, sorted_unique,
                               to_utc_iso)

ENTITY_CATALOG_SCHEMA_VERSION = "theme_entity_catalog:0.1.0"


class EntityType(str, Enum):
    COMPANY = "COMPANY"
    INDEX = "INDEX"
    SECTOR = "SECTOR"
    INDUSTRY = "INDUSTRY"
    COMMODITY = "COMMODITY"
    CURRENCY = "CURRENCY"
    COUNTRY = "COUNTRY"
    CENTRAL_BANK = "CENTRAL_BANK"
    GOVERNMENT = "GOVERNMENT"


#: Foundation `ThemeEntityKind` への完全写像（test で双方向に検証。OTHER fallback は無い）
FOUNDATION_KIND_BY_ENTITY_TYPE: Mapping[EntityType, ThemeEntityKind] = {
    EntityType.COMPANY: ThemeEntityKind.COMPANY,
    EntityType.INDEX: ThemeEntityKind.INDEX,
    EntityType.SECTOR: ThemeEntityKind.SECTOR,
    EntityType.INDUSTRY: ThemeEntityKind.INDUSTRY,
    EntityType.COMMODITY: ThemeEntityKind.COMMODITY,
    EntityType.CURRENCY: ThemeEntityKind.CURRENCY,
    EntityType.COUNTRY: ThemeEntityKind.COUNTRY,
    EntityType.CENTRAL_BANK: ThemeEntityKind.CENTRAL_BANK,
    EntityType.GOVERNMENT: ThemeEntityKind.GOVERNMENT,
}


class IdentifierType(str, Enum):
    TICKER = "TICKER"                 # scheme ＝ 取引所 / 市場 code（必須）
    INSTRUMENT_ID = "INSTRUMENT_ID"   # market catalog（knowledge/market_series）の instrument_id
    ISO_COUNTRY = "ISO_COUNTRY"       # ISO 3166-1 alpha-2
    ISO_CURRENCY = "ISO_CURRENCY"     # ISO 4217 alpha-3


#: entity type ごとに許す identifier type（それ以外は INVALID_IDENTIFIER_TYPE）
IDENTIFIER_TYPES_BY_ENTITY_TYPE: Mapping[EntityType, Tuple[IdentifierType, ...]] = {
    EntityType.COMPANY: (IdentifierType.TICKER, IdentifierType.INSTRUMENT_ID),
    EntityType.INDEX: (IdentifierType.INSTRUMENT_ID,),
    EntityType.SECTOR: (),
    EntityType.INDUSTRY: (),
    EntityType.COMMODITY: (IdentifierType.INSTRUMENT_ID,),
    EntityType.CURRENCY: (IdentifierType.ISO_CURRENCY,),
    EntityType.COUNTRY: (IdentifierType.ISO_COUNTRY,),
    EntityType.CENTRAL_BANK: (),
    EntityType.GOVERNMENT: (),
}
#: 別 entity による再利用を「有効期間が重ならない場合に限り」許す identifier type（type 意味論による明示の例外）
REUSABLE_IDENTIFIER_TYPES: Tuple[IdentifierType, ...] = (IdentifierType.TICKER,)
_ISO_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ATTRIBUTE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

ENTITY_FIELDS = ("entity_id", "entity_type", "canonical_name", "aliases_safe", "aliases_context", "context_terms",
                 "identifiers", "attributes", "valid_from", "valid_to", "superseded_by", "provenance", "since_version",
                 "retired_in_version")
ENTITY_REQUIRED_FIELDS = ("entity_id", "entity_type", "canonical_name", "provenance", "since_version")
IDENTIFIER_FIELDS = ("identifier_type", "value", "scheme", "valid_from", "valid_to")


def _fail(code: str, detail: str = "", *, where: str = "") -> None:
    raise KnowledgeError(code, detail, where=where)


def _require(condition: bool, code: str, detail: str = "", *, where: str = "") -> None:
    if not condition:
        _fail(code, detail, where=where)


def foundation_entity_kind(entity_type: EntityType) -> ThemeEntityKind:
    _require(isinstance(entity_type, EntityType), "INVALID_VOCABULARY", "entity_type must be EntityType")
    return FOUNDATION_KIND_BY_ENTITY_TYPE[entity_type]


def entity_id_prefix(entity_type: EntityType) -> str:
    return foundation_entity_kind(entity_type).value + ":"


def split_entity_id(entity_id: object, *, where: str) -> Tuple[EntityType, str]:
    _require(isinstance(entity_id, str) and entity_id.count(":") == 1, "INVALID_ENTITY_ID",
             f"{where} must be <kind>:<slug>", where=where)
    kind_value, slug = str(entity_id).split(":", 1)
    matches = [t for t, k in FOUNDATION_KIND_BY_ENTITY_TYPE.items() if k.value == kind_value]
    _require(len(matches) == 1, "INVALID_ENTITY_ID", f"{where} has unknown kind prefix {kind_value!r}", where=where)
    _require(is_slug(slug), "INVALID_ENTITY_ID", f"{where} slug must match ^[a-z][a-z0-9_]{{0,63}}$", where=where)
    return matches[0], slug


def _optional_date(value: object, *, where: str) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return parse_date(value, where=where)


def _within(day: date, start: Optional[date], end: Optional[date]) -> bool:
    return (start is None or start <= day) and (end is None or day < end)


def _disjoint(a_start: Optional[date], a_end: Optional[date], b_start: Optional[date], b_end: Optional[date]) -> bool:
    """両区間が重ならない（開始含む・終了含まない）。片側が無限なら重なるとみなす（fail closed）。"""
    if a_end is not None and b_start is not None and a_end <= b_start:
        return True
    if b_end is not None and a_start is not None and b_end <= a_start:
        return True
    return False


# ---------------------------------------------------------------- identifier


@dataclass(frozen=True, kw_only=True)
class EntityIdentifier:
    identifier_type: IdentifierType
    value: str
    scheme: str = ""
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None

    def __post_init__(self) -> None:
        where = "identifier"
        _require(isinstance(self.identifier_type, IdentifierType), "INVALID_VOCABULARY", "identifier_type", where=where)
        object.__setattr__(self, "value", checked_text(self.value, f"{where}.value", max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "scheme", checked_text(self.scheme, f"{where}.scheme", max_len=MAX_REF_LEN))
        if self.identifier_type is IdentifierType.TICKER:
            _require(self.scheme != "", "MISSING_FIELD", "TICKER requires a scheme (exchange / market code)", where=where)
        if self.identifier_type is IdentifierType.ISO_COUNTRY:
            _require(_ISO_COUNTRY_RE.match(self.value) is not None, "INVALID_IDENTIFIER", "ISO_COUNTRY must be 2 upper letters",
                     where=where)
        if self.identifier_type is IdentifierType.ISO_CURRENCY:
            _require(_ISO_CURRENCY_RE.match(self.value) is not None, "INVALID_IDENTIFIER", "ISO_CURRENCY must be 3 upper letters",
                     where=where)
        object.__setattr__(self, "valid_from", _optional_date(self.valid_from, where=f"{where}.valid_from"))
        object.__setattr__(self, "valid_to", _optional_date(self.valid_to, where=f"{where}.valid_to"))
        if self.valid_from is not None and self.valid_to is not None:
            _require(self.valid_from < self.valid_to, "INVALID_INTERVAL", "identifier valid_from must be before valid_to",
                     where=where)

    def key(self) -> Tuple[str, str, str]:
        return (self.identifier_type.value, self.scheme, self.value)

    def semantic_payload(self) -> Dict[str, object]:
        return {"identifier_type": self.identifier_type.value, "value": self.value, "scheme": self.scheme,
                "valid_from": self.valid_from.isoformat() if self.valid_from else "",
                "valid_to": self.valid_to.isoformat() if self.valid_to else ""}

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "EntityIdentifier":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=IDENTIFIER_FIELDS, required=("identifier_type", "value"), where=where)
        return cls(identifier_type=parse_enum(mapping["identifier_type"], IdentifierType, where=f"{where}.identifier_type"),
                   value=plain_str(mapping, "value", where=where), scheme=plain_str(mapping, "scheme", where=where, default=""),
                   valid_from=_optional_date(mapping.get("valid_from"), where=f"{where}.valid_from"),
                   valid_to=_optional_date(mapping.get("valid_to"), where=f"{where}.valid_to"))


# ---------------------------------------------------------------- entity


@dataclass(frozen=True, kw_only=True)
class EntityRecord:
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases_safe: Tuple[str, ...] = ()
    aliases_context: Tuple[str, ...] = ()
    context_terms: Tuple[str, ...] = ()
    identifiers: Tuple[EntityIdentifier, ...] = ()
    attributes: Tuple[Tuple[str, str], ...] = ()
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    superseded_by: Tuple[str, ...] = ()
    provenance: KnowledgeProvenance
    since_version: str
    retired_in_version: str = ""

    def __post_init__(self) -> None:
        where = f"entity[{self.entity_id!r}]"
        kind, _slug = split_entity_id(self.entity_id, where=f"{where}.entity_id")
        _require(isinstance(self.entity_type, EntityType), "INVALID_VOCABULARY", f"{where}.entity_type", where=where)
        _require(kind is self.entity_type, "ENTITY_ID_KIND_MISMATCH",
                 f"{where} prefix {entity_id_prefix(kind)!r} does not match entity_type {self.entity_type.value}", where=where)
        object.__setattr__(self, "canonical_name", checked_text(self.canonical_name, f"{where}.canonical_name",
                                                                max_len=MAX_TEXT_LEN, required=True))
        safe = tuple(checked_text(a, f"{where}.aliases_safe", max_len=MAX_TEXT_LEN, required=True) for a in self.aliases_safe)
        context = tuple(checked_text(a, f"{where}.aliases_context", max_len=MAX_TEXT_LEN, required=True)
                        for a in self.aliases_context)
        terms = tuple(checked_text(t, f"{where}.context_terms", max_len=MAX_TEXT_LEN, required=True) for t in self.context_terms)
        normalized_aliases = [normalize_token(a) for a in safe + context]
        _require(all(n != "" for n in normalized_aliases), "INVALID_ALIAS", f"{where} has an alias normalizing to empty", where=where)
        _require(len(set(normalized_aliases)) == len(normalized_aliases), "ALIAS_DUPLICATE",
                 f"{where} repeats an alias after normalization (safe and context lists are one namespace)", where=where)
        normalized_terms = [normalize_token(t) for t in terms]
        _require(all(n != "" for n in normalized_terms), "INVALID_ALIAS", f"{where} has a context term normalizing to empty",
                 where=where)
        _require(len(set(normalized_terms)) == len(normalized_terms), "ALIAS_DUPLICATE", f"{where} repeats a context term",
                 where=where)
        _require(not context or terms, "CONTEXT_TERMS_REQUIRED", f"{where} has context aliases but no context_terms", where=where)
        _require(not terms or context, "CONTEXT_TERMS_WITHOUT_ALIAS", f"{where} has context_terms but no context alias",
                 where=where)
        object.__setattr__(self, "aliases_safe", tuple(sorted(safe, key=normalize_token)))
        object.__setattr__(self, "aliases_context", tuple(sorted(context, key=normalize_token)))
        object.__setattr__(self, "context_terms", tuple(sorted(terms, key=normalize_token)))
        _require(all(isinstance(i, EntityIdentifier) for i in self.identifiers), "INVALID_TYPE", f"{where}.identifiers",
                 where=where)
        keys = [i.key() for i in self.identifiers]
        _require(len(set(keys)) == len(keys), "IDENTIFIER_DUPLICATE", f"{where} repeats an identifier", where=where)
        allowed = IDENTIFIER_TYPES_BY_ENTITY_TYPE[self.entity_type]
        for identifier in self.identifiers:
            _require(identifier.identifier_type in allowed, "INVALID_IDENTIFIER_TYPE",
                     f"{where} {self.entity_type.value} cannot carry {identifier.identifier_type.value}", where=where)
        object.__setattr__(self, "identifiers", tuple(sorted(self.identifiers, key=lambda i: i.key())))
        attrs: List[Tuple[str, str]] = []
        for pair in self.attributes:
            _require(isinstance(pair, tuple) and len(pair) == 2, "INVALID_TYPE", f"{where}.attributes", where=where)
            name, value = pair
            _require(isinstance(name, str) and _ATTRIBUTE_KEY_RE.match(name) is not None, "INVALID_ATTRIBUTE",
                     f"{where} attribute key {name!r} must be snake_case", where=where)
            attrs.append((name, checked_text(value, f"{where}.attributes.{name}", max_len=MAX_TEXT_LEN, required=True)))
        names = [n for n, _ in attrs]
        _require(len(set(names)) == len(names), "INVALID_ATTRIBUTE", f"{where} repeats an attribute key", where=where)
        object.__setattr__(self, "attributes", tuple(sorted(attrs)))
        object.__setattr__(self, "valid_from", _optional_date(self.valid_from, where=f"{where}.valid_from"))
        object.__setattr__(self, "valid_to", _optional_date(self.valid_to, where=f"{where}.valid_to"))
        if self.valid_from is not None and self.valid_to is not None:
            _require(self.valid_from < self.valid_to, "INVALID_INTERVAL", f"{where} valid_from must be before valid_to", where=where)
        successors = []
        for successor in self.superseded_by:
            split_entity_id(successor, where=f"{where}.superseded_by")
            _require(successor != self.entity_id, "INVALID_SUPERSESSION", f"{where} supersedes itself", where=where)
            successors.append(str(successor))
        _require(not successors or self.valid_to is not None, "SUPERSESSION_WITHOUT_END",
                 f"{where} names successors but has no valid_to", where=where)
        object.__setattr__(self, "superseded_by", sorted_unique(successors, where=f"{where}.superseded_by"))
        _require(isinstance(self.provenance, KnowledgeProvenance), "INVALID_TYPE", f"{where}.provenance", where=where)
        since = parse_version(self.since_version, where=f"{where}.since_version")
        _require(isinstance(self.retired_in_version, str), "INVALID_TYPE", f"{where}.retired_in_version", where=where)
        if self.retired_in_version != "":
            retired = parse_version(self.retired_in_version, where=f"{where}.retired_in_version")
            _require(retired >= since, "INVALID_LIFECYCLE", f"{where} retired before it was introduced", where=where)

    # -- derived（純）
    @property
    def slug(self) -> str:
        return self.entity_id.split(":", 1)[1]

    @property
    def foundation_kind(self) -> ThemeEntityKind:
        return foundation_entity_kind(self.entity_type)

    @property
    def is_retired(self) -> bool:
        return self.retired_in_version != ""

    def in_force_on(self, day: date) -> bool:
        return _within(day, self.valid_from, self.valid_to)

    def normalized_safe_aliases(self) -> Tuple[str, ...]:
        return tuple(normalize_token(a) for a in self.aliases_safe)

    def normalized_context_aliases(self) -> Tuple[str, ...]:
        return tuple(normalize_token(a) for a in self.aliases_context)

    def normalized_context_terms(self) -> Tuple[str, ...]:
        return tuple(normalize_token(t) for t in self.context_terms)

    def semantic_payload(self) -> Dict[str, object]:
        return {
            "entity_id": self.entity_id, "entity_type": self.entity_type.value, "canonical_name": self.canonical_name,
            "aliases_safe": list(self.aliases_safe), "aliases_context": list(self.aliases_context),
            "context_terms": list(self.context_terms), "identifiers": [i.semantic_payload() for i in self.identifiers],
            "attributes": {k: v for k, v in self.attributes},
            "valid_from": self.valid_from.isoformat() if self.valid_from else "",
            "valid_to": self.valid_to.isoformat() if self.valid_to else "",
            "superseded_by": list(self.superseded_by), "provenance": self.provenance.to_plain(),
            "since_version": self.since_version, "retired_in_version": self.retired_in_version,
        }

    def to_plain(self) -> Dict[str, object]:
        return self.semantic_payload()

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "EntityRecord":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=ENTITY_FIELDS, required=ENTITY_REQUIRED_FIELDS, where=where)
        identifiers = tuple(EntityIdentifier.from_plain(item, where=f"{where}.identifiers[{index}]")
                            for index, item in enumerate(plain_list_of_mappings(mapping, "identifiers", where=where))
                            ) if "identifiers" in mapping else ()
        return cls(
            entity_id=plain_str(mapping, "entity_id", where=where),
            entity_type=parse_enum(mapping["entity_type"], EntityType, where=f"{where}.entity_type"),
            canonical_name=plain_str(mapping, "canonical_name", where=where),
            aliases_safe=plain_str_list(mapping, "aliases_safe", where=where),
            aliases_context=plain_str_list(mapping, "aliases_context", where=where),
            context_terms=plain_str_list(mapping, "context_terms", where=where),
            identifiers=identifiers, attributes=plain_str_mapping(mapping, "attributes", where=where),
            valid_from=_optional_date(mapping.get("valid_from"), where=f"{where}.valid_from"),
            valid_to=_optional_date(mapping.get("valid_to"), where=f"{where}.valid_to"),
            superseded_by=plain_str_list(mapping, "superseded_by", where=where),
            provenance=KnowledgeProvenance.from_plain(mapping["provenance"], where=f"{where}.provenance"),
            since_version=plain_str(mapping, "since_version", where=where),
            retired_in_version=plain_str(mapping, "retired_in_version", where=where, default=""),
        )


# ---------------------------------------------------------------- catalog snapshot


@dataclass(frozen=True, kw_only=True)
class EntityCatalogSnapshot:
    schema_version: str = ENTITY_CATALOG_SCHEMA_VERSION
    catalog_version: str
    published_at: datetime
    content_digest: str
    entities: Tuple[EntityRecord, ...]
    _by_id: Mapping[str, EntityRecord] = field(init=False, repr=False, compare=False, default_factory=dict)
    _safe_owner: Mapping[str, str] = field(init=False, repr=False, compare=False, default_factory=dict)
    _context_owners: Mapping[str, Tuple[str, ...]] = field(init=False, repr=False, compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        where = f"entity_catalog[{self.catalog_version}]"
        _require(self.schema_version == ENTITY_CATALOG_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version,
                 where=where)
        version = parse_version(self.catalog_version, where=f"{where}.catalog_version")
        _require(isinstance(self.published_at, datetime) and self.published_at.tzinfo is not None, "INVALID_DATETIME",
                 f"{where}.published_at must be aware", where=where)
        _require(is_digest(self.content_digest), "INVALID_DIGEST", f"{where}.content_digest", where=where)
        _require(isinstance(self.entities, tuple) and all(isinstance(e, EntityRecord) for e in self.entities), "INVALID_TYPE",
                 f"{where}.entities must be EntityRecord tuple", where=where)
        entities = tuple(sorted(self.entities, key=lambda e: e.entity_id))
        by_id: Dict[str, EntityRecord] = {}
        slugs: Dict[str, str] = {}
        for entity in entities:
            _require(entity.entity_id not in by_id, "DUPLICATE_ENTITY_ID", f"{entity.entity_id!r} appears twice", where=where)
            _require(entity.slug not in slugs, "SLUG_COLLISION",
                     f"slug {entity.slug!r} is used by {slugs.get(entity.slug)!r} and {entity.entity_id!r}", where=where)
            by_id[entity.entity_id] = entity
            slugs[entity.slug] = entity.entity_id
        for entity in entities:
            ewhere = f"{where}.entity[{entity.entity_id!r}]"
            _require(parse_version(entity.since_version, where=ewhere) <= version, "FUTURE_ENTITY",
                     f"{ewhere} since_version is after the snapshot version", where=ewhere)
            if entity.is_retired:
                _require(parse_version(entity.retired_in_version, where=ewhere) <= version, "FUTURE_RETIREMENT",
                         f"{ewhere} retired_in_version is after the snapshot version", where=ewhere)
            for successor in entity.superseded_by:
                _require(successor in by_id, "INVALID_SUPERSESSION", f"{ewhere} successor {successor!r} does not exist", where=ewhere)
            for name, value in entity.attributes:
                if ":" in value:
                    _require(value in by_id, "DANGLING_ATTRIBUTE_REF", f"{ewhere} attribute {name} refers to unknown {value!r}",
                             where=ewhere)
        # alias 所有: safe alias は catalog 全体で一意。他 entity の id / slug と一致してはならず、他 entity の context alias を影にしない
        safe_owner: Dict[str, str] = {}
        context_owners: Dict[str, List[str]] = {}
        id_tokens = {normalize_token(e.entity_id): e.entity_id for e in entities}
        for entity in entities:
            for token in entity.normalized_context_aliases():
                context_owners.setdefault(token, []).append(entity.entity_id)
        for entity in entities:
            for token in entity.normalized_safe_aliases():
                _require(token not in safe_owner, "SAFE_ALIAS_COLLISION",
                         f"safe alias {token!r} is owned by both {safe_owner.get(token)!r} and {entity.entity_id!r}", where=where)
                _require(token not in id_tokens or id_tokens[token] == entity.entity_id, "SAFE_ALIAS_COLLISION",
                         f"safe alias {token!r} equals another entity id", where=where)
                others = [o for o in context_owners.get(token, []) if o != entity.entity_id]
                _require(not others, "CONTEXT_ALIAS_SHADOWED",
                         f"safe alias {token!r} of {entity.entity_id!r} shadows a context alias of {others}", where=where)
                safe_owner[token] = entity.entity_id
        # identifier 衝突: 同 (type, scheme, value) を別 entity が持つのは、再利用可能 type かつ期間が重ならない場合のみ
        holders: Dict[Tuple[str, str, str], List[Tuple[str, EntityIdentifier]]] = {}
        for entity in entities:
            for identifier in entity.identifiers:
                holders.setdefault(identifier.key(), []).append((entity.entity_id, identifier))
        for key, items in sorted(holders.items()):
            if len(items) < 2:
                continue
            reusable = items[0][1].identifier_type in REUSABLE_IDENTIFIER_TYPES
            for index in range(len(items)):
                for other in range(index + 1, len(items)):
                    (a_id, a), (b_id, b) = items[index], items[other]
                    _require(reusable and _disjoint(a.valid_from, a.valid_to, b.valid_from, b.valid_to), "IDENTIFIER_COLLISION",
                             f"identifier {key} is held by both {a_id!r} and {b_id!r}", where=where)
        object.__setattr__(self, "entities", entities)
        object.__setattr__(self, "_by_id", by_id)
        object.__setattr__(self, "_safe_owner", safe_owner)
        object.__setattr__(self, "_context_owners", {k: tuple(sorted(v)) for k, v in context_owners.items()})

    # -- lookup（純）
    def entity(self, entity_id: str) -> Optional[EntityRecord]:
        return self._by_id.get(entity_id)

    def entity_ids(self) -> Tuple[str, ...]:
        return tuple(e.entity_id for e in self.entities)

    def safe_alias_owner(self, normalized: str) -> Optional[str]:
        return self._safe_owner.get(normalized)

    def context_alias_owners(self, normalized: str) -> Tuple[str, ...]:
        return self._context_owners.get(normalized, ())

    def semantic_payload(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "catalog_version": self.catalog_version,
            "published_at": to_utc_iso(self.published_at),
            "entities": [e.semantic_payload() for e in self.entities],
        }
