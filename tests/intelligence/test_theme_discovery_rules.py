"""P6-B4C — discovery ruleset（versioned knowledge）の test matrix 1〜14 ＋ 補助。

公開 ruleset（discovery_rules 0.1.0）と tmp ruleset で、digest / version / cutoff / pin / rule 構造 / 参照検証の fail closed を固定する。
"""
from __future__ import annotations

import copy
from datetime import timedelta, timezone

import pytest
import yaml

from src.intelligence.theme_intelligence.discovery_model import (DISCOVERY_RULESET_SCHEMA_VERSION, DiscoveryRule, InputKind, Predicate,
                                                                 PredicateKind, RuleOutputType, RuleStatus)
from src.intelligence.theme_intelligence.discovery_rules import (check_ruleset_pins, compute_discovery_rules_digest, discovery_rules_path,
                                                                 load_discovery_rules_version, rule_reference_diagnostics)
from src.intelligence.theme_intelligence.knowledge_loader import KnowledgeError, KnowledgeOrigin, KnowledgeProvenance, content_digest
from src.intelligence.themes.model import EvidenceRole
from tests.intelligence.test_theme_discovery import (CUTOFF, GOLDEN_RULESET_DIGEST, KNOWLEDGE_ROOT, T_RULESET, catalog, load_rules, rule,
                                                     ruleset, ruleset_doc, taxonomy, theme_rule, write_ruleset)

UTC = timezone.utc
__all__ = ["taxonomy", "catalog", "ruleset"]          # fixtures re-exported for pytest collection


def expect(tmp_path, code: str, rules, taxonomy=None, catalog=None, **kw) -> None:
    with pytest.raises(KnowledgeError) as info:
        load_rules(tmp_path, rules, taxonomy, catalog, **kw)
    assert info.value.code == code, (info.value.code, str(info.value))


def test_01_canonical_published_ruleset(ruleset) -> None:
    assert discovery_rules_path(KNOWLEDGE_ROOT, "0.1.0") == KNOWLEDGE_ROOT / "theme_intelligence" / "discovery_rules.0.1.0.yaml"
    assert ruleset.content_digest == GOLDEN_RULESET_DIGEST and ruleset.schema_version == DISCOVERY_RULESET_SCHEMA_VERSION
    assert (ruleset.taxonomy_version, ruleset.catalog_version) == ("0.2.0", "0.2.0") and ruleset.published_at == T_RULESET
    assert [r.rule_id for r in ruleset.rules] == sorted(r.rule_id for r in ruleset.rules)
    assert len(ruleset.rules) == 7 and len(ruleset.in_force_rules()) == 6
    assert ruleset.rule("legacy_supply_chain_evidence").status is RuleStatus.DEPRECATED
    outputs = {r.rule_id: r.output_type for r in ruleset.rules}
    assert outputs["jp_data_center_power_demand_theme"] is RuleOutputType.THEME_CANDIDATE
    assert {r.proposed_role for r in ruleset.rules} <= {EvidenceRole.SUPPORTS, EvidenceRole.CONTEXT}
    assert all(r.provenance.origin is KnowledgeOrigin.SUPERVISOR_DECISION for r in ruleset.rules)


def test_02_digest_is_deterministic_and_order_independent(tmp_path, ruleset) -> None:
    assert content_digest(ruleset.semantic_payload()) == GOLDEN_RULESET_DIGEST
    assert compute_discovery_rules_digest(discovery_rules_path(KNOWLEDGE_ROOT, "0.1.0")) == GOLDEN_RULESET_DIGEST
    rules = [rule("a"), theme_rule("b")]
    base = load_rules(tmp_path / "base", rules)
    shuffled = list(reversed(copy.deepcopy(rules)))
    for item in shuffled:
        item["input_kinds"] = list(reversed(item["input_kinds"]))
        reordered = {k: item[k] for k in reversed(list(item))}
        item.clear()
        item.update(reordered)
    doc = ruleset_doc(shuffled)
    path = write_ruleset(tmp_path / "flow", doc, text=yaml.safe_dump(doc, allow_unicode=True, sort_keys=True, default_flow_style=True))
    assert compute_discovery_rules_digest(path) == base.content_digest
    changed = copy.deepcopy(rules)
    changed[0]["provenance"]["reason"] = "another reason"
    assert load_rules(tmp_path / "changed", changed).content_digest != base.content_digest


def test_03_explicit_version_only(tmp_path) -> None:
    path = write_ruleset(tmp_path, ruleset_doc([rule("a")], version="0.3.0"))
    assert load_discovery_rules_version(path, expected_version="0.3.0", cutoff=CUTOFF).ruleset_version == "0.3.0"
    with pytest.raises(KnowledgeError) as info:
        load_discovery_rules_version(path, expected_version="0.1.0", cutoff=CUTOFF)
    assert info.value.code == "VERSION_MISMATCH"
    with pytest.raises(KnowledgeError) as info:
        load_discovery_rules_version(path, expected_version="latest", cutoff=CUTOFF)
    assert info.value.code == "INVALID_VERSION"


def test_04_future_version_fails(tmp_path) -> None:
    path = write_ruleset(tmp_path, ruleset_doc([rule("a")], published=CUTOFF + timedelta(hours=1)))
    with pytest.raises(KnowledgeError) as info:
        load_discovery_rules_version(path, expected_version="0.1.0", cutoff=CUTOFF)
    assert info.value.code == "FUTURE_VERSION"
    assert load_discovery_rules_version(path, expected_version="0.1.0", cutoff=CUTOFF + timedelta(hours=1)).ruleset_version == "0.1.0"


def test_05_taxonomy_pin_mismatch_fails(tmp_path, taxonomy, catalog) -> None:
    expect(tmp_path, "TAXONOMY_PIN_MISMATCH", [rule("a")], taxonomy, catalog, taxonomy_version="0.1.0")
    unpinned = load_rules(tmp_path / "u", [rule("a")], taxonomy_version="0.1.0")
    with pytest.raises(KnowledgeError) as info:
        check_ruleset_pins(unpinned, taxonomy, catalog)
    assert info.value.code == "TAXONOMY_PIN_MISMATCH"


def test_06_catalog_pin_mismatch_fails(tmp_path, taxonomy, catalog) -> None:
    expect(tmp_path, "CATALOG_PIN_MISMATCH", [rule("a")], taxonomy, catalog, catalog_version="0.1.0")
    with pytest.raises(KnowledgeError) as info:
        load_rules(tmp_path / "half", [rule("a")], taxonomy, None)
    assert info.value.code == "MISSING_PIN_TARGET"


def test_07_duplicate_rule_fails(tmp_path) -> None:
    expect(tmp_path, "DUPLICATE_RULE", [rule("a"), rule("a", rule_version="0.2.0")])
    expect(tmp_path, "DUPLICATE_RULE", [rule("a"), rule("a")])


def test_08_unknown_or_malformed_predicates_fail(tmp_path) -> None:
    expect(tmp_path, "INVALID_VOCABULARY", [rule("a", predicate={"kind": "REGEX"})])
    expect(tmp_path, "UNKNOWN_FIELD", [rule("a", predicate={"kind": "REGEX", "pattern": ".*"})])
    expect(tmp_path, "UNKNOWN_FIELD", [rule("a", predicate={"kind": "ENTITY_PRESENT", "entity_id": "central_bank:boj", "fuzzy": True})])
    expect(tmp_path, "INVALID_PREDICATE", [rule("a", predicate={"kind": "MIN_DISTINCT", "dimension": "INPUT_ID", "min_count": 2})])
    expect(tmp_path, "UNDECLARED_ENTITY_REF", [rule("a", entity_refs=[], predicate={"kind": "ENTITY_PRESENT", "entity_id": "central_bank:boj"})])
    expect(tmp_path, "UNDECLARED_TAXONOMY_REF", [rule("a", predicate={"kind": "TAXONOMY_SIGNAL", "slug": "power"})])
    expect(tmp_path, "INVALID_PREDICATE", [rule("a", aggregate_predicates=[{"kind": "ENTITY_PRESENT", "entity_id": "central_bank:boj"}])])
    expect(tmp_path, "INVALID_PREDICATE", [rule("a", predicate={"kind": "NOT", "children": []})])
    expect(tmp_path, "INVALID_PREDICATE", [rule("a", predicate={"kind": "SOURCE_KIND", "source_kind": "UNKNOWN"})])
    with pytest.raises(KnowledgeError):
        Predicate(kind=PredicateKind.MIN_DISTINCT)


def test_09_forbidden_roles_fail(tmp_path) -> None:
    for role in ("CONTRADICTS", "INVALIDATES"):
        expect(tmp_path / role, "FORBIDDEN_ROLE", [rule("a", proposed_role=role)])
    expect(tmp_path / "vocab", "INVALID_VOCABULARY", [rule("a", proposed_role="RECOMMENDS")])


def test_10_incomplete_mechanism_fails(tmp_path) -> None:
    incomplete = theme_rule("t")
    incomplete["mechanism_template"]["channels"] = []
    expect(tmp_path / "channels", "INCOMPLETE_MECHANISM", [incomplete])
    missing = theme_rule("t")
    del missing["mechanism_template"]
    expect(tmp_path / "missing", "INCOMPLETE_MECHANISM", [missing])
    vocab = theme_rule("t")
    vocab["mechanism_template"]["drivers"][0]["category"] = "SENTIMENT"
    expect(tmp_path / "vocab", "INVALID_VOCABULARY", [vocab])
    other = theme_rule("t")
    other["mechanism_template"]["drivers"][0] = {"category": "OTHER"}
    expect(tmp_path / "other", "MISSING_FIELD", [other])
    no_subject = theme_rule("t")
    del no_subject["subject_template"]
    expect(tmp_path / "subject", "INCOMPLETE_MECHANISM", [no_subject])
    evidence_with_template = rule("e", mechanism_template=theme_rule("t")["mechanism_template"])
    expect(tmp_path / "evidence", "UNKNOWN_FIELD", [evidence_with_template])


def test_11_missing_invalidation_or_scope_fails(tmp_path) -> None:
    expect(tmp_path / "inv", "MISSING_INVALIDATION", [theme_rule("t", invalidation_template=[])])
    expect(tmp_path / "frame", "INCOMPLETE_SCOPE", [theme_rule("t", scope_template=[{"dimension": "REGION", "value": "${entity}"}])])
    expect(tmp_path / "single", "INCOMPLETE_SCOPE", [theme_rule("t", scope_template=[{"dimension": "PERIOD_FRAME", "value": "single_session"}])])
    expect(tmp_path / "binding", "AMBIGUOUS_BINDING", [theme_rule("t", entity_refs=["country:jp", "country:us"], predicate={
        "kind": "ANY", "children": [{"kind": "ENTITY_PRESENT", "entity_id": "country:jp"}, {"kind": "ENTITY_PRESENT", "entity_id": "country:us"}]},
        taxonomy_refs=[])])
    expect(tmp_path / "series", "AMBIGUOUS_BINDING", [theme_rule("t", mechanism_template={
        **theme_rule("t")["mechanism_template"],
        "consequences": [{"category": "MACRO_STATISTIC", "observable_target": "${series}", "expected_change": "INCREASE"}]})])
    expect(tmp_path / "unknown_binding", "INVALID_BINDING", [theme_rule("t", scope_template=[{"dimension": "REGION", "value": "${country}"},
                                                                                              {"dimension": "PERIOD_FRAME", "value": "multi_year"}])])


def test_12_deprecated_taxonomy_ref_fails_for_active_rules(tmp_path, taxonomy, catalog) -> None:
    deprecated = rule("a", entity_refs=[], taxonomy_refs=["supply_chain_theme"], predicate={"kind": "TAXONOMY_SIGNAL", "slug": "supply_chain_theme"})
    expect(tmp_path / "active", "INVALID_RULE_REFERENCE", [deprecated], taxonomy, catalog)
    loaded = load_rules(tmp_path / "deprecated", [dict(deprecated, status="DEPRECATED")], taxonomy, catalog)
    assert loaded.in_force_rules() == () and loaded.rule("a").status is RuleStatus.DEPRECATED
    unknown = dict(deprecated, taxonomy_refs=["quantum"], predicate={"kind": "TAXONOMY_SIGNAL", "slug": "quantum"}, status="DEPRECATED")
    expect(tmp_path / "unknown", "INVALID_RULE_REFERENCE", [unknown], taxonomy, catalog)
    assert rule_reference_diagnostics(loaded.rule("a"), taxonomy, catalog) == ("DEPRECATED_TAXONOMY_REF:supply_chain_theme",)


def test_13_inactive_or_superseded_entity_ref_fails_for_active_rules(tmp_path, taxonomy, catalog) -> None:
    superseded = rule("a", entity_refs=["company:example_battery"], predicate={"kind": "ENTITY_PRESENT", "entity_id": "company:example_battery"})
    expect(tmp_path / "superseded", "INVALID_RULE_REFERENCE", [superseded], taxonomy, catalog)
    unknown = rule("a", entity_refs=["company:ghost"], predicate={"kind": "ENTITY_PRESENT", "entity_id": "company:ghost"})
    expect(tmp_path / "unknown", "INVALID_RULE_REFERENCE", [unknown], taxonomy, catalog)
    attribute = theme_rule("t", scope_template=[{"dimension": "REGION", "value": "${entity.sector}"},
                                                {"dimension": "PERIOD_FRAME", "value": "multi_year"}])
    expect(tmp_path / "attribute", "INVALID_RULE_REFERENCE", [attribute], taxonomy, catalog)
    ok = theme_rule("t", entity_refs=["industry:banks"], predicate={"kind": "ALL", "children": [
        {"kind": "ENTITY_PRESENT", "entity_id": "industry:banks"}, {"kind": "TAXONOMY_SIGNAL", "slug": "power"}]}, taxonomy_refs=["power"],
        scope_template=[{"dimension": "INDUSTRY", "value": "${entity}"}, {"dimension": "REGION", "value": "${entity.sector}"},
                        {"dimension": "PERIOD_FRAME", "value": "multi_year"}])
    assert load_rules(tmp_path / "ok", [ok], taxonomy, catalog).rule("t").entity_refs == ("industry:banks",)


def test_14_unknown_fields_fail(tmp_path) -> None:
    expect(tmp_path / "rule", "UNKNOWN_FIELD", [rule("a", weight=1)])
    expect(tmp_path / "top", "UNKNOWN_FIELD", [rule("a")], extra={"notes": "x"})
    doc = ruleset_doc([rule("a")])
    del doc["taxonomy_version"]
    path = write_ruleset(tmp_path / "nopin", doc, sign=False)
    with pytest.raises(KnowledgeError) as info:
        compute_discovery_rules_digest(path)
    assert info.value.code == "MISSING_FIELD"
    expect(tmp_path / "schema", "UNSUPPORTED_SCHEMA_VERSION", [rule("a")], schema="theme_discovery_rules:9.0.0")
    expect(tmp_path / "kind", "INVALID_VOCABULARY", [rule("a", input_kinds=["STATEMENT"])])
    expect(tmp_path / "status", "INVALID_VOCABULARY", [rule("a", status="DRAFT")])
    expect(tmp_path / "output", "INVALID_VOCABULARY", [rule("a", output_type="RELATION_CANDIDATE")])
    expect(tmp_path / "target", "INVALID_RULE", [theme_rule("t", target_root_id="thm_" + "0" * 24)])


def test_rule_model_direct_construction() -> None:
    provenance = KnowledgeProvenance(origin=KnowledgeOrigin.MVP_FIXTURE, approver_ref="role:test", reason="r")
    made = DiscoveryRule(rule_id="direct", rule_version="0.1.0", status=RuleStatus.ACTIVE, input_kinds=(InputKind.NEWS_ITEM,),
                         entity_refs=("central_bank:boj",), predicate=Predicate(kind=PredicateKind.ENTITY_PRESENT, entity_id="central_bank:boj"),
                         output_type=RuleOutputType.EVIDENCE_CANDIDATE, proposed_role=EvidenceRole.CONTEXT, provenance=provenance)
    assert made.rule_ref == "rule:direct" and made.input_kinds == (InputKind.NEWS_ITEM,)
    with pytest.raises(KnowledgeError) as info:
        DiscoveryRule(rule_id="Bad Rule", rule_version="0.1.0", status=RuleStatus.ACTIVE, input_kinds=(), predicate=Predicate(
            kind=PredicateKind.ENTITY_PRESENT, entity_id="x"), output_type=RuleOutputType.EVIDENCE_CANDIDATE, proposed_role=EvidenceRole.CONTEXT,
            provenance=provenance)
    assert info.value.code == "INVALID_RULE_ID"
