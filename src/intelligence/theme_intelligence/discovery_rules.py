"""P6-B4C — discovery ruleset（VERSIONED KNOWLEDGE）の version 指定 loader と cross-knowledge 検証。

- `load_discovery_rules_version(path, *, expected_version, cutoff, taxonomy=None, entity_catalog=None)`: expected_version
  完全一致・published_at ≤ cutoff・digest 一致でのみ `DiscoveryRuleset` を返す。taxonomy / entity_catalog を渡した場合は
  pin（taxonomy_version / catalog_version の完全一致）と ACTIVE rule の参照（deprecated taxonomy ref・retired / superseded
  entity ref・未知 ref・binding 属性）を fail closed で検証する。
- ruleset envelope は B4B envelope ＋ pin 2 key（taxonomy_version / catalog_version）。B4B の `knowledge_loader` は変更せず、
  pin 付き envelope の検査を本 module が行う（YAML の読み取り自体は `knowledge_loader.read_yaml_document`）。
- 「latest」解決・別 version への fallback・現在時刻はない。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .discovery_model import (BINDING_ENTITY_ATTRIBUTE_PREFIX, DISCOVERY_RULESET_SCHEMA_VERSION, DiscoveryRule, DiscoveryRuleset,
                              RuleOutputType, RuleStatus)
from .entity_model import EntityCatalogSnapshot
from .knowledge_loader import (KnowledgeError, SnapshotEnvelope, check_digest, check_version_and_cutoff, content_digest, is_digest,
                               knowledge_path, parse_published_at, parse_version, plain_list_of_mappings, plain_str,
                               read_yaml_document, require_keys)
from .taxonomy_model import TaxonomySnapshot

DISCOVERY_RULES_FILENAME_TEMPLATE = "discovery_rules.{version}.yaml"
RULESET_VERSION_KEY = "ruleset_version"
RULESET_RECORDS_KEY = "rules"
RULESET_PIN_KEYS = ("taxonomy_version", "catalog_version")
RULESET_ENVELOPE_KEYS = ("schema_version", RULESET_VERSION_KEY, "published_at", "content_digest", RULESET_RECORDS_KEY) + RULESET_PIN_KEYS


def _fail(code: str, detail: str = "", *, where: str = "") -> None:
    raise KnowledgeError(code, detail, where=where)


def _require(condition: bool, code: str, detail: str = "", *, where: str = "") -> None:
    if not condition:
        _fail(code, detail, where=where)


# ---------------------------------------------------------------- paths / envelope


def discovery_rules_path(knowledge_root: Path, version: str) -> Path:
    """`<knowledge_root>/theme_intelligence/discovery_rules.<version>.yaml`（version は caller が明示。列挙しない）。"""
    base = knowledge_path(knowledge_root, "taxonomy", version)            # directory 規約と version 形式の検査を再利用
    return base.with_name(DISCOVERY_RULES_FILENAME_TEMPLATE.format(version=version))


def _read_envelope(path: Path, *, allow_missing_digest: bool) -> Tuple[SnapshotEnvelope, str, str]:
    document = read_yaml_document(path)
    where = path.name
    required = ("schema_version", RULESET_VERSION_KEY, "published_at", RULESET_RECORDS_KEY) + RULESET_PIN_KEYS
    if not allow_missing_digest:
        required = required + ("content_digest",)
    require_keys(document, allowed=RULESET_ENVELOPE_KEYS, required=required, where=where)
    declared_schema = plain_str(document, "schema_version", where=where)
    _require(declared_schema == DISCOVERY_RULESET_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
             f"expected {DISCOVERY_RULESET_SCHEMA_VERSION}, found {declared_schema}", where=where)
    version = plain_str(document, RULESET_VERSION_KEY, where=where)
    parse_version(version, where=f"{where}.{RULESET_VERSION_KEY}")
    taxonomy_version = plain_str(document, "taxonomy_version", where=where)
    catalog_version = plain_str(document, "catalog_version", where=where)
    parse_version(taxonomy_version, where=f"{where}.taxonomy_version")
    parse_version(catalog_version, where=f"{where}.catalog_version")
    published_at = parse_published_at(document["published_at"], where=f"{where}.published_at")
    digest = plain_str(document, "content_digest", where=where, default="" if allow_missing_digest else None)
    if not allow_missing_digest:
        _require(is_digest(digest), "INVALID_DIGEST", "content_digest must be 64 lowercase hex characters", where=f"{where}.content_digest")
    records = plain_list_of_mappings(document, RULESET_RECORDS_KEY, where=where)
    envelope = SnapshotEnvelope(schema_version=declared_schema, version=version, published_at=published_at, content_digest=digest,
                                records=records, document_name=where)
    return envelope, taxonomy_version, catalog_version


def _ruleset_from_envelope(envelope: SnapshotEnvelope, *, taxonomy_version: str, catalog_version: str, digest: str) -> DiscoveryRuleset:
    rules = tuple(DiscoveryRule.from_plain(record, where=f"{envelope.document_name}.rules[{index}]")
                  for index, record in enumerate(envelope.records))
    return DiscoveryRuleset(schema_version=envelope.schema_version, ruleset_version=envelope.version, published_at=envelope.published_at,
                            content_digest=digest, taxonomy_version=taxonomy_version, catalog_version=catalog_version, rules=rules)


def compute_discovery_rules_digest(path: Path) -> str:
    """authoring 補助: 構造検証を全て行ったうえで semantic digest を返す（宣言 digest との比較だけを行わない）。"""
    envelope, taxonomy_version, catalog_version = _read_envelope(path, allow_missing_digest=True)
    ruleset = _ruleset_from_envelope(envelope, taxonomy_version=taxonomy_version, catalog_version=catalog_version, digest="0" * 64)
    return content_digest(ruleset.semantic_payload())


def load_discovery_rules_version(path: Path, *, expected_version: str, cutoff: datetime,
                                 taxonomy: Optional[TaxonomySnapshot] = None,
                                 entity_catalog: Optional[EntityCatalogSnapshot] = None) -> DiscoveryRuleset:
    envelope, taxonomy_version, catalog_version = _read_envelope(path, allow_missing_digest=False)
    check_version_and_cutoff(envelope, expected_version=expected_version, cutoff=cutoff)
    ruleset = _ruleset_from_envelope(envelope, taxonomy_version=taxonomy_version, catalog_version=catalog_version,
                                     digest=envelope.content_digest)
    check_digest(envelope, content_digest(ruleset.semantic_payload()))
    if taxonomy is not None or entity_catalog is not None:
        _require(taxonomy is not None and entity_catalog is not None, "MISSING_PIN_TARGET",
                 "taxonomy and entity_catalog must be supplied together for reference validation", where=envelope.document_name)
        validate_ruleset_refs(ruleset, taxonomy, entity_catalog)
    return ruleset


# ---------------------------------------------------------------- cross-knowledge validation（pin ＋ 参照）


def check_ruleset_pins(ruleset: DiscoveryRuleset, taxonomy: TaxonomySnapshot, entity_catalog: EntityCatalogSnapshot) -> None:
    where = f"ruleset[{ruleset.ruleset_version}]"
    _require(ruleset.taxonomy_version == taxonomy.taxonomy_version, "TAXONOMY_PIN_MISMATCH",
             f"ruleset pins taxonomy {ruleset.taxonomy_version}, supplied {taxonomy.taxonomy_version}", where=where)
    _require(ruleset.catalog_version == entity_catalog.catalog_version, "CATALOG_PIN_MISMATCH",
             f"ruleset pins catalog {ruleset.catalog_version}, supplied {entity_catalog.catalog_version}", where=where)


def rule_reference_diagnostics(rule: DiscoveryRule, taxonomy: TaxonomySnapshot, entity_catalog: EntityCatalogSnapshot) -> Tuple[str, ...]:
    """rule の taxonomy / entity 参照の問題を列挙する（ACTIVE rule ではすべて fail closed の対象）。"""
    out: List[str] = []
    for slug in rule.taxonomy_refs:
        node = taxonomy.node(slug)
        if node is None:
            out.append(f"UNKNOWN_TAXONOMY_REF:{slug}")
        elif node.is_deprecated:
            out.append(f"DEPRECATED_TAXONOMY_REF:{slug}")
    for entity_id in rule.entity_refs:
        entity = entity_catalog.entity(entity_id)
        if entity is None:
            out.append(f"UNKNOWN_ENTITY_REF:{entity_id}")
            continue
        if entity.is_retired:
            out.append(f"RETIRED_ENTITY_REF:{entity_id}")
        if entity.superseded_by:
            out.append(f"SUPERSEDED_ENTITY_REF:{entity_id}")
    if rule.output_type is RuleOutputType.THEME_CANDIDATE and rule.mechanism_template is not None:
        refs = list(rule.mechanism_template.bindings()) + [s.value for s in rule.scope_template if "${" in s.value]
        if rule.subject_template is not None and "${" in rule.subject_template.typed_reference:
            refs.append(rule.subject_template.typed_reference)
        for ref in sorted(set(refs)):
            if ref.startswith(BINDING_ENTITY_ATTRIBUTE_PREFIX):
                attribute = ref[len(BINDING_ENTITY_ATTRIBUTE_PREFIX):-1]
                entity = entity_catalog.entity(rule.entity_refs[0]) if rule.entity_refs else None
                if entity is None or attribute not in dict(entity.attributes):
                    out.append(f"UNBOUND_ENTITY_ATTRIBUTE:{ref}")
    return tuple(out)


def validate_ruleset_refs(ruleset: DiscoveryRuleset, taxonomy: TaxonomySnapshot, entity_catalog: EntityCatalogSnapshot) -> None:
    check_ruleset_pins(ruleset, taxonomy, entity_catalog)
    for rule in ruleset.rules:
        problems = rule_reference_diagnostics(rule, taxonomy, entity_catalog)
        if rule.status is RuleStatus.ACTIVE:
            _require(not problems, "INVALID_RULE_REFERENCE", f"rule {rule.rule_id!r}: {list(problems)}",
                     where=f"ruleset[{ruleset.ruleset_version}]")
        else:                                                              # DEPRECATED rule: 参照先の実在だけを要求
            unknown = [p for p in problems if p.startswith("UNKNOWN_")]
            _require(not unknown, "INVALID_RULE_REFERENCE", f"rule {rule.rule_id!r}: {unknown}",
                     where=f"ruleset[{ruleset.ruleset_version}]")
