"""P6-B4D — L2 正規化 / taxonomy 階層 / entity lifecycle / negative predicate / MIN_DISTINCT の敵対 stress（§5〜§7, §10, §11）。

正規化層（B4B resolver ＋ B4C adapter）が「似ている」ことを根拠に hit を作らないことを固定する。
runtime は変更しない。期待値は contract から authoring したもので、出力の snapshot ではない。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.intelligence.databank.news_model import ClassificationProvenance, EntityKind, EntityReference
from src.intelligence.theme_intelligence.discovery_adapter import adapt_inputs
from src.intelligence.theme_intelligence.discovery_model import DistinctDimension, Predicate, PredicateKind
from src.intelligence.theme_intelligence.discovery_predicates import distinct_count, evaluate_aggregate, evaluate_predicate
from src.intelligence.theme_intelligence.entity_catalog import (EntityResolutionStatus, entity_catalog_path,
                                                                load_entity_catalog_version, resolve_entity_token)
from src.intelligence.theme_intelligence.proposal_model import ProposalType
from src.intelligence.theme_intelligence.taxonomy import TaxonomyResolutionStatus, resolve_taxonomy_token
from tests.intelligence.test_theme_discovery import (CUTOFF, JP, KNOWLEDGE_ROOT, catalog, did, document, evaluation, news, nid,  # noqa: F401
                                                     load_rules, observation, of_type, rule, ruleset, run, taxonomy, theme_rule)

UTC = timezone.utc
S = EntityResolutionStatus


def record(taxonomy, catalog, item):
    return adapt_inputs([item], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]


def entities(taxonomy, catalog, item):
    return tuple(sorted({(h.entity_id, h.level.value, h.matched_by) for h in record(taxonomy, catalog, item).entity_hits}))


def slugs(taxonomy, catalog, item):
    return tuple(sorted({h.slug for h in record(taxonomy, catalog, item).taxonomy_hits}))


# ---------------------------------------------------------------- §5 L2 正規化攻撃


@pytest.mark.parametrize("headline", ["Turbojet engine orders rise", "Japanese carmakers expand abroad", "Topixel imaging sensors ship",
                                      "Riverbanks erode slowly", "Superpowered batteries announced"])
def test_19_alias_inside_a_longer_word_never_matches(taxonomy, catalog, headline) -> None:
    """boj / japan / topix / banks / power はいずれも別語の部分文字列として現れうる。境界一致のみを許す。"""
    item = news("w", headline, refs=())
    assert entities(taxonomy, catalog, item) == () and slugs(taxonomy, catalog, item) == ()


@pytest.mark.parametrize("headline,expected", [
    ("Bank of Japan, again", ("central_bank:boj",)), ("BOJ: policy unchanged", ("central_bank:boj",)),
    ("(BOJ) statement", ("central_bank:boj",)), ("Topix -0.4% today", ("index:topix",)),
    ("boj/topix summary", ("central_bank:boj", "index:topix"))])
def test_20_punctuation_adjacent_aliases_still_match(taxonomy, catalog, headline, expected) -> None:
    assert tuple(e for e, _level, _by in entities(taxonomy, catalog, news("p", headline, refs=()))) == expected


@pytest.mark.parametrize("headline,entity_ids,slug_ids", [
    ("ＢＯＪ ｓｔａｔｅｍｅｎｔ", ("central_bank:boj",), ()),                      # NFKC 全角 → 半角
    ("ﾃﾞｰﾀｾﾝﾀｰ の増設", (), ("data_center",)),                                    # NFKC 半角カナ → 全角カナ
    ("BANK OF JAPAN HOLDS", ("central_bank:boj",), ()),                            # casefold
    ("Bank  of　Japan review", ("central_bank:boj",), ()),                      # 空白正規化（全角空白 ＋ 連続空白）
    ("  Datacenter  ", (), ("data_center",))])
def test_21_unicode_case_and_whitespace_normalization_is_shared_with_b4b(taxonomy, catalog, headline, entity_ids, slug_ids) -> None:
    item = news("n", headline, refs=())
    assert tuple(e for e, _level, _by in entities(taxonomy, catalog, item)) == entity_ids
    assert slugs(taxonomy, catalog, item) == slug_ids


def test_22_longest_alias_wins_and_shorter_overlapping_alias_is_dropped(taxonomy, catalog) -> None:
    only_long = entities(taxonomy, catalog, news("a", "Bank of Japan holds", refs=()))
    assert only_long == (("central_bank:boj", "L2", "safe_alias"),)                 # "japan" は "bank of japan" に含まれるため捨てる
    both_surfaces = entities(taxonomy, catalog, news("b", "Bank of Japan holds", refs=(), summary="Japan outlook steady"))
    assert both_surfaces == (("central_bank:boj", "L2", "safe_alias"), ("country:jp", "L2", "safe_alias"))
    overlapped = entities(taxonomy, catalog, news("c", "Japan and Bank of Japan", refs=()))
    assert overlapped == (("central_bank:boj", "L2", "safe_alias"),)                # 既知の保守側の取りこぼし（gate doc の limitation）
    structured = entities(taxonomy, catalog, news("d", "Bank of Japan holds", refs=(JP,)))
    assert ("country:jp", "L1", "structured_ref") in structured                     # 構造化 ref は text 面の判断に影響されない


def test_23_taxonomy_longest_token_wins_and_parent_is_not_added(taxonomy, catalog) -> None:
    assert slugs(taxonomy, catalog, news("a", "Power grid upgrades", refs=())) == ("grid",)
    assert slugs(taxonomy, catalog, news("b", "Nuclear power plans", refs=())) == ("nuclear",)
    assert slugs(taxonomy, catalog, news("c", "Electric power tariffs", refs=())) == ("power",)
    assert slugs(taxonomy, catalog, news("d", "Datacenter build", refs=())) == ("data_center",)


def test_24_repeated_aliases_do_not_inflate_hits_or_distinct_counts(taxonomy, catalog) -> None:
    item = news("r", "Datacenter, datacenter and another datacenter", refs=(JP, JP))
    hit = record(taxonomy, catalog, item)
    assert len(hit.taxonomy_hits) == 1 and hit.taxonomy_slugs() == ("data_center",)
    assert hit.entity_ids() == ("country:jp",) and distinct_count([hit], DistinctDimension.ENTITY_ID) == 1
    assert distinct_count([hit, hit], DistinctDimension.INPUT_ID) == 1
    spread = news("s", "Datacenter plans", refs=(), summary="another datacenter contract")
    assert record(taxonomy, catalog, spread).taxonomy_slugs() == ("data_center",)     # 面が違っても slug は 1


def test_25_only_bounded_surfaces_are_scanned_and_there_is_no_body_wide_matching(taxonomy, catalog) -> None:
    item = news("b", "Quiet headline", refs=(), summary="Nothing here", author="Bank of Japan",
                url="https://example.invalid/datacenter/bank-of-japan")
    scanned = record(taxonomy, catalog, item)
    assert [name for name, _text in scanned.bounded_text_surfaces] == ["headline", "summary"]
    assert scanned.entity_hits == () and scanned.taxonomy_hits == ()
    doc = document("b", "Quiet title", summary="", locator="https://example.invalid/bank-of-japan/datacenter")
    scanned_doc = record(taxonomy, catalog, doc)
    assert [name for name, _text in scanned_doc.bounded_text_surfaces] == ["title"]
    assert scanned_doc.entity_hits == () and scanned_doc.taxonomy_hits == ()


@pytest.mark.parametrize("headline,expected", [
    ("Fed holds after fomc", ("central_bank:fed",)), ("Fed up with delays", ()), ("Fed up after the opec meeting", ()),
    ("Oil rises as opec meets", ("commodity:crude_oil",)), ("Cooking oil prices", ()),
    ("Dollar firms as the fx market reopens", ("currency:usd",)), ("Dollar store openings", ())])
def test_26_context_aliases_resolve_only_with_their_own_context_terms(taxonomy, catalog, headline, expected) -> None:
    assert tuple(e for e, _level, _by in entities(taxonomy, catalog, news("c", headline, refs=()))) == expected


def test_27_two_context_owners_on_one_surface_stay_ambiguous(taxonomy, catalog) -> None:
    ambiguous = record(taxonomy, catalog, news("a", "Example plant: motors and battery cells", refs=()))
    assert ambiguous.entity_hits == ()
    assert "AMBIGUOUS_ENTITY:example:company:example_battery,company:example_motors" in ambiguous.diagnostics
    one_owner = record(taxonomy, catalog, news("b", "Example plant adds vehicles output", refs=()))
    assert [(h.entity_id, h.matched_by) for h in one_owner.entity_hits] == [("company:example_motors", "context_alias")]
    resolution = resolve_entity_token(catalog, "example", context=("motors", "battery"))
    assert resolution.status is S.AMBIGUOUS and resolution.entity_id == ""


def test_28_two_distinct_entities_on_one_surface_both_resolve(taxonomy, catalog) -> None:
    assert entities(taxonomy, catalog, news("t", "Bank of Japan and Topix outlook", refs=())) == (
        ("central_bank:boj", "L2", "safe_alias"), ("index:topix", "L2", "safe_alias"))


# ---------------------------------------------------------------- §6 taxonomy 階層攻撃


def test_29_child_hit_never_implies_parent_and_parent_never_implies_child(taxonomy, catalog) -> None:
    child = record(taxonomy, catalog, news("a", "送電網 expansion", refs=()))
    assert evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="grid"), child).matched
    for parent in ("power", "energy", "ai"):
        assert not evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug=parent), child).matched
    parent = record(taxonomy, catalog, news("b", "Electric power tariffs", refs=()))
    assert not evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="grid"), parent).matched
    ancestors = record(taxonomy, catalog, news("c", "Datacenter build", refs=()))
    assert not evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="ai"), ancestors).matched
    assert taxonomy.ancestors_of("data_center") == ("ai",)                            # DAG は知識としては存在するが hit を増やさない


def test_30_multi_parent_slug_produces_exactly_one_hit(taxonomy, catalog) -> None:
    hit = record(taxonomy, catalog, news("n", "原子力 policy review", refs=()))
    assert [h.slug for h in hit.taxonomy_hits] == ["nuclear"] and hit.taxonomy_slugs() == ("nuclear",)
    assert set(taxonomy.node("nuclear").parent_slugs) == {"energy", "power"}
    assert distinct_count([hit], DistinctDimension.TAXONOMY_TOKEN) == 1               # 親 2 つでも 1 token


def test_31_deprecated_slug_is_diagnosed_and_never_resolved_to_its_successor(taxonomy, catalog) -> None:
    deprecated = record(taxonomy, catalog, news("d", "supply_chain_theme review", refs=()))
    assert deprecated.taxonomy_hits == () and "DEPRECATED_TAXONOMY_TOKEN:supply_chain_theme" in deprecated.diagnostics
    resolution = resolve_taxonomy_token(taxonomy, "supply_chain_theme")
    assert resolution.status is TaxonomyResolutionStatus.DEPRECATED and resolution.superseded_by == ("supply_chain",)
    successor = record(taxonomy, catalog, news("s", "supply chain resilience", refs=()))
    assert successor.taxonomy_slugs() == ("supply_chain",)


# ---------------------------------------------------------------- §7 entity lifecycle 攻撃


@pytest.fixture(scope="module")
def catalog_010():
    return load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=CUTOFF)


def test_32_rename_keeps_the_entity_id_and_the_old_name_still_resolves(taxonomy, catalog, catalog_010) -> None:
    old_name = news("o", "Example Motors output", refs=())
    assert entities(taxonomy, catalog_010, old_name) == (("company:example_motors", "L2", "safe_alias"),)
    assert entities(taxonomy, catalog, old_name) == (("company:example_motors", "L2", "safe_alias"),)
    new_name = news("n", "Example Mobility output", refs=())
    assert entities(taxonomy, catalog, new_name) == (("company:example_motors", "L2", "safe_alias"),)
    assert entities(taxonomy, catalog_010, new_name) == ()                            # 旧 catalog は新名称を知らない（推測しない）
    assert catalog.entity("company:example_motors").canonical_name == "Example Mobility"
    assert catalog_010.entity("company:example_motors").canonical_name == "Example Motors"


def ticker(value: str):
    return EntityReference(kind=EntityKind.TICKER, value=value, provenance=ClassificationProvenance.SOURCE_EXPLICIT)


def test_33_ticker_change_keeps_the_entity_id_and_respects_validity_windows(taxonomy, catalog, catalog_010) -> None:
    after = news("a", "Quiet", refs=(ticker("EXM2"),))
    assert entities(taxonomy, catalog, after) == (("company:example_motors", "L1", "identifier"),)
    before = record(taxonomy, catalog, news("b", "Quiet", refs=(ticker("EXM1"),)))
    assert before.entity_hits == () and "IDENTIFIER_OUT_OF_VALIDITY:TICKER:exm1" in before.diagnostics
    legacy = news("c", "Quiet", refs=(ticker("EXM1"),))
    assert entities(taxonomy, catalog_010, legacy) == (("company:example_motors", "L1", "identifier"),)
    assert record(taxonomy, catalog_010, news("d", "Quiet", refs=(ticker("EXM2"),))).entity_hits == ()


def test_34_superseded_entity_is_reported_and_never_swapped_for_its_successor(taxonomy, catalog) -> None:
    merged = record(taxonomy, catalog, news("m", "Example Battery output", refs=()))
    assert merged.entity_hits == ()
    assert "SUPERSEDED_ENTITY:company:example_battery->company:example_energy_systems" in merged.diagnostics
    earlier = resolve_entity_token(catalog, "example battery", as_of=date(2026, 1, 1))
    assert earlier.status is S.EXACT_SAFE_ALIAS and earlier.entity_id == "company:example_battery"
    later = resolve_entity_token(catalog, "example battery", as_of=date(2026, 9, 18))
    assert later.status is S.SUPERSEDED and later.superseded_by == ("company:example_energy_systems",)


def test_35_inactive_entity_never_triggers(taxonomy, catalog) -> None:
    early = record(taxonomy, catalog, news("e", "Example Energy Systems plant", refs=(), published=datetime(2026, 6, 1, tzinfo=UTC)))
    assert [h.entity_id for h in early.entity_hits] == [] or "company:example_energy_systems" not in [h.entity_id for h in early.entity_hits]
    assert "INACTIVE_ENTITY:company:example_energy_systems" in early.diagnostics
    live = record(taxonomy, catalog, news("l", "Example Energy Systems plant", refs=()))
    assert ("company:example_energy_systems", "L2") in [(h.entity_id, h.level.value) for h in live.entity_hits]


def test_36_unknown_structured_refs_and_identifiers_are_never_guessed(taxonomy, catalog) -> None:
    refs = (EntityReference(kind=EntityKind.COMPANY, value="example_motor", provenance=ClassificationProvenance.SOURCE_EXPLICIT),
            ticker("EXM"), EntityReference(kind=EntityKind.COUNTRY, value="JPN", provenance=ClassificationProvenance.SOURCE_EXPLICIT))
    unknown = record(taxonomy, catalog, news("u", "Quiet", refs=refs))
    assert unknown.entity_hits == ()
    assert {"UNKNOWN_STRUCTURED_REF:company:example_motor", "UNKNOWN_IDENTIFIER:TICKER:exm",
            "UNKNOWN_STRUCTURED_REF:country:jpn"} <= set(unknown.diagnostics)


# ---------------------------------------------------------------- §10 negative predicate stress


@pytest.fixture(scope="module")
def negative_rules(tmp_path_factory, taxonomy, catalog):
    root = tmp_path_factory.mktemp("b4d_negative")
    single = rule("dc_evidence", entity_refs=[], taxonomy_refs=["data_center", "nuclear"],
                  predicate={"kind": "TAXONOMY_SIGNAL", "slug": "data_center"},
                  negative_predicates=[{"kind": "TAXONOMY_SIGNAL", "slug": "nuclear"}])
    doubled = rule("dc_evidence_twice", entity_refs=[], taxonomy_refs=["data_center", "nuclear"],
                   predicate={"kind": "TAXONOMY_SIGNAL", "slug": "data_center"},
                   negative_predicates=[{"kind": "TAXONOMY_SIGNAL", "slug": "nuclear"},
                                        {"kind": "TAXONOMY_SIGNAL", "slug": "nuclear"}])
    wide = rule("dc_power_evidence", entity_refs=["country:jp"], taxonomy_refs=["data_center", "power", "nuclear"],
                predicate={"kind": "ALL", "children": [{"kind": "ENTITY_PRESENT", "entity_id": "country:jp"},
                                                       {"kind": "TAXONOMY_SIGNAL", "slug": "data_center"},
                                                       {"kind": "TAXONOMY_SIGNAL", "slug": "power"}]},
                negative_predicates=[{"kind": "TAXONOMY_SIGNAL", "slug": "nuclear"}])
    return load_rules(root, [single, doubled, wide], taxonomy, catalog)


@pytest.mark.parametrize("headline,matched,excluded", [
    ("Datacenter build-out in Japan", True, False),                                     # positive のみ
    ("Nuclear power review in Japan", False, True),                                     # negative のみ（positive 不成立でも除外）
    ("Datacenter and nuclear power in Japan", False, True),                             # positive ＋ negative → 部分点なし
    ("Datacenter, electric power and 原子力 in Japan", False, True)])                    # 複数 positive ＋ 1 negative
def test_37_negative_predicates_exclude_the_whole_input(taxonomy, catalog, negative_rules, headline, matched, excluded) -> None:
    result = run([news("x", headline)], taxonomy, catalog, negative_rules)
    for rule_id in ("dc_evidence", "dc_evidence_twice"):
        evaluated = evaluation(result, rule_id)
        assert bool(evaluated.matched_input_ids) is matched, rule_id
        assert bool(evaluated.negative_exclusions) is excluded, rule_id
    assert bool(of_type(result, ProposalType.EVIDENCE_CANDIDATE)) is matched


def test_38_duplicate_negative_predicates_exclude_once(taxonomy, catalog, negative_rules) -> None:
    result = run([news("x", "Datacenter and nuclear power in Japan")], taxonomy, catalog, negative_rules)
    once, twice = evaluation(result, "dc_evidence"), evaluation(result, "dc_evidence_twice")
    assert once.negative_exclusions == twice.negative_exclusions == (nid("x"),)
    assert once.diagnostics == twice.diagnostics == (f"EXCLUDED_BY_NEGATIVE_PREDICATE:{nid('x')}",)
    wide = evaluation(result, "dc_power_evidence")
    assert wide.negative_exclusions == (nid("x"),) and wide.matched_input_ids == () and wide.emitted_proposal_ids == ()


def test_39_excluded_inputs_do_not_count_towards_any_aggregate(taxonomy, catalog, ruleset) -> None:
    clean = news("a", "Data centre demand lifts electric power in Japan")
    tainted = news("b", "Nuclear power and data centre demand lifts electric power in Japan")
    result = run([clean, tainted], taxonomy, catalog, ruleset)
    theme = evaluation(result, "jp_data_center_power_demand_theme")
    assert theme.matched_input_ids == (nid("a"),) and theme.negative_exclusions == (nid("b"),)
    assert "MIN_DISTINCT_NOT_MET:INPUT_ID:1<2" in theme.diagnostics and theme.emitted_proposal_ids == ()
    assert of_type(result, ProposalType.THEME_CANDIDATE) == []


# ---------------------------------------------------------------- §11 MIN_DISTINCT stress


@pytest.fixture(scope="module")
def stress_records(taxonomy, catalog):
    items = [news("a", "Data centre and electric power in Japan"), news("b", "Data centre plans in Japan"),
             news("c", "Bank of Japan and electric power note", refs=()), document("d", "Data centre plans in Japan")]
    return {r.input_id: r for r in adapt_inputs(items, taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records}


@pytest.mark.parametrize("dimension,expected", [(DistinctDimension.INPUT_ID, 4), (DistinctDimension.EVIDENCE_REF, 4),
                                                (DistinctDimension.ENTITY_ID, 2), (DistinctDimension.TAXONOMY_TOKEN, 2)])
def test_40_distinct_counts_are_per_dimension(stress_records, dimension, expected) -> None:
    assert distinct_count(list(stress_records.values()), dimension) == expected


@pytest.mark.parametrize("dimension", list(DistinctDimension))
def test_41_duplicates_never_inflate_a_distinct_count(stress_records, dimension) -> None:
    records = list(stress_records.values())
    assert distinct_count(records + records, dimension) == distinct_count(records, dimension)
    single = [stress_records[nid("a")]]
    assert distinct_count(single * 5, dimension) == distinct_count(single, dimension)


def test_42_evidence_ref_dimension_separates_wrappers_of_one_article(stress_records) -> None:
    news_record, document_record = stress_records[nid("b")], stress_records[did("d")]
    pair = [news_record, document_record]
    assert distinct_count(pair, DistinctDimension.INPUT_ID) == distinct_count(pair, DistinctDimension.EVIDENCE_REF) == 2
    assert {r.evidence_kind.value for r in pair} == {"NEWS_ITEM", "SOURCE_DOCUMENT"}
    assert len({r.source_origin.origin_key for r in pair}) == 2                        # 別 article の合成入力なので origin も別


@pytest.mark.parametrize("dimension,min_count,ok", [(DistinctDimension.INPUT_ID, 4, True), (DistinctDimension.INPUT_ID, 5, False),
                                                    (DistinctDimension.ENTITY_ID, 2, True), (DistinctDimension.ENTITY_ID, 3, False),
                                                    (DistinctDimension.TAXONOMY_TOKEN, 2, True),
                                                    (DistinctDimension.TAXONOMY_TOKEN, 3, False)])
def test_43_aggregate_min_distinct_reports_the_shortfall(stress_records, dimension, min_count, ok) -> None:
    predicate = Predicate(kind=PredicateKind.MIN_DISTINCT, dimension=dimension, min_count=min_count)
    satisfied, diagnostics = evaluate_aggregate((predicate,), list(stress_records.values()))
    assert satisfied is ok
    assert diagnostics == (() if ok else (f"MIN_DISTINCT_NOT_MET:{dimension.value}:{min_count - 1}<{min_count}",))


def test_44_per_input_min_distinct_covers_only_entity_and_taxonomy_dimensions(stress_records) -> None:
    both = stress_records[nid("a")]
    assert evaluate_predicate(Predicate(kind=PredicateKind.MIN_DISTINCT, dimension=DistinctDimension.TAXONOMY_TOKEN, min_count=2), both).matched
    assert not evaluate_predicate(Predicate(kind=PredicateKind.MIN_DISTINCT, dimension=DistinctDimension.ENTITY_ID, min_count=2), both).matched
    for dimension in (DistinctDimension.INPUT_ID, DistinctDimension.EVIDENCE_REF):
        with pytest.raises(ValueError):
            evaluate_predicate(Predicate(kind=PredicateKind.MIN_DISTINCT, dimension=dimension, min_count=1), both)


def test_45_min_distinct_is_not_an_independent_source_count(taxonomy, catalog, ruleset) -> None:
    item = news("s", "Data centre demand lifts electric power in Japan")
    linked = document("s", "Data centre demand lifts electric power in Japan")
    result = run([item, linked], taxonomy, catalog, ruleset)
    theme = evaluation(result, "jp_data_center_power_demand_theme")
    assert theme.aggregate_satisfied and len(theme.matched_input_ids) == 2
    assert "EVIDENCE_REFS:2;ORIGIN_KEYS:1;NOT_AN_INDEPENDENCE_CLAIM" in theme.diagnostics
    assert result.run_report.origin_groups == (("article:art_s", (did("s"), nid("s"))),)
