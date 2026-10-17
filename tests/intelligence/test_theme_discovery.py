"""P6-B4C — deterministic Theme discovery（test matrix 15〜68: adapter / predicates / generation / suppression / dedup / replay）。

公開 knowledge（taxonomy 0.2.0 / entity catalog 0.2.0 / discovery_rules 0.1.0）と、tmp ruleset・合成入力（NewsItem / SourceDocument /
Fact / Observation）で固定する。store も Foundation も書かない。すべての時刻は注入。
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence

import pytest
import yaml

from src.intelligence.core.types import SourceTier
from src.intelligence.databank.news_model import ClassificationProvenance, EntityKind, EntityReference, NewsDocumentLink, NewsItem
from src.intelligence.facts.model import DateRole, EvidenceKind as FactEvidenceKind, Fact, FactEvidenceRef, FactStatus, FactSubject, FactTimeContext, FactValue
from src.intelligence.market.model import Observation, ObservationKind
from src.intelligence.sources.model import SourceDocument
from src.intelligence.theme_intelligence.discovery import discover, evidence_reason
from src.intelligence.theme_intelligence.discovery_adapter import adapt_inputs
from src.intelligence.theme_intelligence.discovery_model import (DISCOVERY_MODEL_VERSION, FIXED_CERTAINTY, TEMPLATE_PROVENANCE_REF,
                                                                 DiscoveryError, DiscoveryRuleset, DistinctDimension, InputKind, MatchLevel,
                                                                 Predicate, PredicateKind, RuleStatus)
from src.intelligence.theme_intelligence.discovery_predicates import distinct_count, evaluate_aggregate, evaluate_predicate
from src.intelligence.theme_intelligence.discovery_rules import compute_discovery_rules_digest, discovery_rules_path, load_discovery_rules_version
from src.intelligence.theme_intelligence.entity_catalog import entity_catalog_path, load_entity_catalog_version
from src.intelligence.theme_intelligence.knowledge_loader import KnowledgeError
from src.intelligence.theme_intelligence.proposal_model import (DecisionKind, DedupClass, DedupReviewProposal, EvidenceCandidateProposal,
                                                                ProposalDecision, ProposalType, ProposerClass, ThemeCandidateProposal)
from src.intelligence.theme_intelligence.proposal_resolution import derive_proposal_status
from src.intelligence.theme_intelligence.taxonomy import load_taxonomy_version, taxonomy_path
from src.intelligence.themes.model import (EvidenceRole, EvidenceTimeBasis, EvidenceTimeQuality, MechanismCertainty, OriginKind, ScopeDimension)

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
UTC = timezone.utc
CUTOFF = datetime(2026, 9, 21, tzinfo=UTC)
RUN_AT = CUTOFF
T = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
T_RULESET = datetime(2026, 9, 20, 2, 0, tzinfo=UTC)
GOLDEN_RULESET_DIGEST = "95f56e5b701830f7ce1efbe667b8a94df2c087e21bff5321993396ce8183e876"
JP = EntityReference(kind=EntityKind.COUNTRY, value="JP", provenance=ClassificationProvenance.SOURCE_EXPLICIT)


# ---------------------------------------------------------------- knowledge fixtures（公開 snapshot）


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUTOFF)


@pytest.fixture(scope="module")
def catalog():
    return load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUTOFF)


@pytest.fixture(scope="module")
def ruleset(taxonomy, catalog):
    return load_discovery_rules_version(discovery_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=CUTOFF,
                                        taxonomy=taxonomy, entity_catalog=catalog)


# ---------------------------------------------------------------- input builders（合成。実在記事 / 顧客 watchlist ではない）


def nid(tag: str) -> str:
    return "news_" + (tag * 24)[:24]


def did(tag: str) -> str:
    return "doc_" + (tag * 24)[:24]


def fid(tag: str) -> str:
    return "fact_" + (tag * 24)[:24]


def oid(tag: str) -> str:
    return "obs_01J" + (tag * 22)[:22].upper()


def news(tag: str, headline: str, *, refs=(JP,), published=T, summary: str = "", article: str = "", document: str = "",
         source_id: str = "src1", publisher: str = "pub", author: str = "", url: str = "") -> NewsItem:
    return NewsItem(news_item_id=nid(tag), article_id=article or f"art_{tag}", primary_document_id=document or did(tag), headline=headline,
                    published_at=published, publisher=publisher, source_id=source_id, summary=summary, entity_refs=tuple(refs), author=author,
                    canonical_url=url)


def document(tag: str, title: str, *, tier=SourceTier.TIER2, published=T, retrieved=T, content_hash: str = "", revision_of=None,
             summary: str = "", inferred: bool = False, source_id: str = "src1", locator: str = "https://example.invalid/x") -> SourceDocument:
    return SourceDocument(source_document_id=did(tag), source_id=source_id, source_tier=tier, title=title, locator=locator, retrieved_at=retrieved,
                          published_at=published, publisher="pub", content_hash=content_hash or f"hash_{tag}", revision_of=revision_of,
                          summary=summary, published_inferred=inferred)


def observation(tag: str, entity_id: str = "index:nikkei225", *, series: str = "nikkei225_close", source_id: str = "src_m", as_of=T,
                trading_date: str = "2026-09-18", kind=ObservationKind.RAW, inputs=()) -> Observation:
    return Observation(observation_id=oid(tag), entity_id=entity_id, metric="close", value=Decimal("1"), unit="index", as_of=as_of, kind=kind,
                       calculation_method="dev" if kind is ObservationKind.DERIVED else "close", inputs=tuple(inputs), source_id=source_id,
                       series_id=series, trading_date=trading_date)


def fact(tag: str, fact_type: str = "policy_rate_decision", *, subject_id: str = "central_bank:boj", known_at=T, primary_date: str = "2026-09-18",
         refs=(("document", did("1")),), status=FactStatus.USABLE) -> Fact:
    return Fact(fact_id=fid(tag), fact_type=fact_type, subject=FactSubject(subject_type="entity", subject_id=subject_id),
                value=FactValue(text_value="hold"), time=FactTimeContext(primary_date=primary_date, date_role=DateRole.EVENT_DATE, known_at=known_at),
                evidence=tuple(FactEvidenceRef(kind=FactEvidenceKind(k), ref_id=r) for k, r in refs), status=status)


def run(inputs: Sequence[object], taxonomy, catalog, ruleset, *, cutoff=CUTOFF, run_created_at=RUN_AT, **kw):
    return discover(list(inputs), taxonomy=taxonomy, entity_catalog=catalog, ruleset=ruleset, cutoff=cutoff, run_created_at=run_created_at, **kw)


def of_type(result, proposal_type: ProposalType):
    return [p for p in result.proposals if p.proposal_type is proposal_type]


def evaluation(result, rule_id: str):
    return next(e for e in result.run_report.rule_evaluations if e.rule_id == rule_id)


# ---------------------------------------------------------------- ruleset builders（tmp。rules test と共有）


def prov(reason: str = "fixture rule") -> dict:
    return {"origin": "MVP_FIXTURE", "approver_ref": "role:test", "reason": reason}


def rule(rule_id: str, **override) -> dict:
    data = {"rule_id": rule_id, "rule_version": "0.1.0", "status": "ACTIVE", "input_kinds": ["NEWS_ITEM", "SOURCE_DOCUMENT"],
            "entity_refs": ["central_bank:boj"], "predicate": {"kind": "ENTITY_PRESENT", "entity_id": "central_bank:boj"},
            "output_type": "EVIDENCE_CANDIDATE", "proposed_role": "CONTEXT", "provenance": prov()}
    data.update(override)
    return data


def theme_templates(**override) -> dict:
    data = {
        "subject_template": {"normalized_subject": "japan electricity demand from data center construction", "typed_reference": "${entity}"},
        "mechanism_template": {
            "drivers": [{"category": "DEMAND_SHIFT", "normalized_statement": "data center construction raises electricity demand"}],
            "channels": [{"category": "VOLUME_DEMAND", "normalized_statement": "higher electricity volume is demanded"}],
            "domains": [{"category": "REGION", "typed_reference": "${entity}"}],
            "consequences": [{"category": "MACRO_STATISTIC", "observable_target": "japan electricity demand statistics",
                              "expected_change": "INCREASE"}]},
        "scope_template": [{"dimension": "REGION", "value": "${entity}"}, {"dimension": "PERIOD_FRAME", "value": "multi_year"}],
        "invalidation_template": [{"condition_key": "dc_pipeline_contraction",
                                   "normalized_statement": "announced data center construction pipeline contracts materially"}],
    }
    data.update(override)
    return data


def theme_rule(rule_id: str, **override) -> dict:
    data = rule(rule_id, entity_refs=["country:jp"], taxonomy_refs=["data_center", "power"],
                predicate={"kind": "ALL", "children": [{"kind": "ENTITY_PRESENT", "entity_id": "country:jp"},
                                                       {"kind": "TAXONOMY_SIGNAL", "slug": "data_center"},
                                                       {"kind": "TAXONOMY_SIGNAL", "slug": "power"}]},
                output_type="THEME_CANDIDATE", proposed_role="SUPPORTS")
    data.update(theme_templates())
    data.update(override)
    return data


def ruleset_doc(rules, *, version="0.1.0", published=T_RULESET, taxonomy_version="0.2.0", catalog_version="0.2.0", digest="",
                schema="theme_discovery_rules:0.1.0", extra=None) -> dict:
    doc = {"schema_version": schema, "ruleset_version": version, "published_at": published.isoformat() if isinstance(published, datetime) else published,
           "content_digest": digest, "taxonomy_version": taxonomy_version, "catalog_version": catalog_version, "rules": rules}
    if extra:
        doc.update(extra)
    return doc


def write_ruleset(tmp_path: Path, doc: dict, name: str = "rules.yaml", *, sign: bool = True, text: str = None) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if sign and text is None and not doc.get("content_digest"):
        signed = dict(doc, content_digest=compute_discovery_rules_digest(path))
        path.write_text(yaml.safe_dump(signed, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load_rules(tmp_path: Path, rules, taxonomy=None, catalog=None, *, version="0.1.0", cutoff=CUTOFF, **kw) -> DiscoveryRuleset:
    path = write_ruleset(tmp_path, ruleset_doc(rules, version=version, **kw))
    return load_discovery_rules_version(path, expected_version=version, cutoff=cutoff, taxonomy=taxonomy, entity_catalog=catalog)


# ---------------------------------------------------------------- 15〜24 adapter


def test_15_source_document_adapts_with_bounded_surfaces_and_origin(taxonomy, catalog) -> None:
    doc = document("d", "Data centre power demand", summary="Bank of Japan commentary", tier=SourceTier.TIER1)
    result = adapt_inputs([doc], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    record = result.records[0]
    assert record.input_kind is InputKind.SOURCE_DOCUMENT and record.input_id == did("d")
    assert record.evidence_time == T and record.evidence_time_basis is EvidenceTimeBasis.PUBLISHED_AT
    assert record.evidence_time_quality is EvidenceTimeQuality.RELIABLE and record.evidence_date == "2026-09-18"
    assert record.source_origin.origin_kind is OriginKind.OFFICIAL_RELEASE and record.source_origin.origin_key == "release:src1/hash_d"
    assert record.bounded_text_surfaces == (("title", "Data centre power demand"), ("summary", "Bank of Japan commentary"))
    assert {h.slug for h in record.taxonomy_hits} == {"data_center", "power"} and all(h.level is MatchLevel.L2 for h in record.taxonomy_hits)
    assert [h.entity_id for h in record.entity_hits] == ["central_bank:boj"] and record.entity_hits[0].matched_by == "safe_alias"
    inferred = adapt_inputs([document("i", "x", inferred=True)], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert inferred.evidence_time_quality is EvidenceTimeQuality.INFERRED
    publisher = adapt_inputs([document("p", "x", tier=SourceTier.TIER3)], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert publisher.source_origin.origin_kind is OriginKind.PUBLISHER_ARTICLE and publisher.source_origin.origin_key == "document:hash_p"
    missing = adapt_inputs([document("m", "x", published=None)], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert missing.evidence_time_quality is EvidenceTimeQuality.MISSING and missing.evidence_time_basis is EvidenceTimeBasis.NONE


def test_16_news_item_adapts_structured_refs_as_l1_and_aliases_as_l2(taxonomy, catalog) -> None:
    item = news("n", "Datacenter build-out in Japan", refs=(JP, EntityReference(kind=EntityKind.SECTOR, value="financials",
                                                                                     provenance=ClassificationProvenance.ENTITY_DATABASE)))
    record = adapt_inputs([item], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert record.input_kind is InputKind.NEWS_ITEM and record.source_origin.origin_key == "article:art_n"
    assert record.source_origin.origin_kind is OriginKind.PUBLISHER_ARTICLE and record.source_origin.lineage_refs == (did("n"),)
    assert record.structured_entity_refs == (("country", "JP", "source_explicit"), ("sector", "financials", "entity_database"))
    hits = {(h.entity_id, h.level.value, h.matched_by) for h in record.entity_hits}
    assert ("country:jp", "L1", "structured_ref") in hits and ("sector:financials", "L1", "structured_ref") in hits
    assert ("country:jp", "L2", "safe_alias") in hits                              # "Japan" は safe alias（text 面）
    assert {h.slug for h in record.taxonomy_hits} == {"data_center"}
    assert record.known_at == T and record.evidence_date == "2026-09-18"


def test_17_usable_fact_adapts_with_declared_known_at(taxonomy, catalog) -> None:
    record = adapt_inputs([fact("f", refs=(("observation", "obs_unknown"),))], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert record.input_kind is InputKind.FACT and record.fact_type == "policy_rate_decision"
    assert record.evidence_time_basis is EvidenceTimeBasis.KNOWN_AT and record.evidence_time_quality is EvidenceTimeQuality.DECLARED
    assert record.evidence_date == "2026-09-18" and [h.entity_id for h in record.entity_hits] == ["central_bank:boj"]
    assert record.source_origin.origin_kind is OriginKind.DERIVED and record.source_origin.origin_key == f"derived:{fid('f')}"
    assert record.source_origin.lineage_refs == ("obs_unknown",)


def test_18_unusable_or_late_facts_are_excluded(taxonomy, catalog) -> None:
    late = fact("l", known_at=CUTOFF + timedelta(hours=1))
    result = adapt_inputs([fact("u", status=FactStatus.LIMITED_USE), late], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    assert result.records == ()
    assert {(e.input_id, e.reason) for e in result.excluded} == {(fid("u"), "FACT_NOT_USABLE:limited_use"), (fid("l"), "KNOWN_AFTER_CUTOFF")}
    unusable = adapt_inputs([fact("x", status=FactStatus.UNUSABLE)], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    assert unusable.records == () and unusable.excluded[0].reason == "FACT_NOT_USABLE:unusable"
    bad_date = fact("b", primary_date="2026/09/18")
    assert adapt_inputs([bad_date], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).excluded[0].reason == "INVALID_PRIMARY_DATE"


def test_19_observation_adapts_series_and_entity(taxonomy, catalog) -> None:
    record = adapt_inputs([observation("o")], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert record.input_kind is InputKind.OBSERVATION and record.observation_series == "nikkei225_close"
    assert record.evidence_time_basis is EvidenceTimeBasis.AS_OF and record.evidence_time_quality is EvidenceTimeQuality.RELIABLE
    assert record.source_origin.origin_kind is OriginKind.MARKET_SERIES and record.source_origin.origin_key == "series:src_m/nikkei225_close"
    assert [(h.entity_id, h.level.value) for h in record.entity_hits] == [("index:nikkei225", "L1")]
    derived = observation("v", kind=ObservationKind.DERIVED, inputs=(oid("o"),))
    drecord = adapt_inputs([derived], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert drecord.source_origin.origin_kind is OriginKind.DERIVED and drecord.source_origin.lineage_refs == (oid("o"),)
    late = adapt_inputs([observation("z", as_of=CUTOFF + timedelta(seconds=1))], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    assert late.excluded[0].reason == "AFTER_CUTOFF"


def test_20_same_underlying_source_converges_to_one_origin(taxonomy, catalog) -> None:
    item = news("s", "Power grid investment in Japan", article="art_shared", document=did("s"))
    doc = document("s", "Power grid investment in Japan")
    f = fact("s", refs=(("document", did("s")),))
    result = adapt_inputs([f, doc, item], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    keys = {r.input_id: r.source_origin.origin_key for r in result.records}
    assert keys == {nid("s"): "article:art_shared", did("s"): "article:art_shared", fid("s"): "article:art_shared"}
    assert result.origin_groups == (("article:art_shared", (did("s"), fid("s"), nid("s"))),)
    linked = adapt_inputs([document("t", "x"), NewsDocumentLink(news_item_id=nid("q"), source_document_id=did("t")), news("q", "x", document=did("qq"))],
                          taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    assert {r.source_origin.origin_key for r in linked.records} == {"article:art_q"}   # NewsDocumentLink 経由の lineage
    revised = adapt_inputs([document("r1", "x", content_hash="h_r"), document("r2", "x", content_hash="h_r2", revision_of=did("r1"))],
                           taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    assert len({r.source_origin.origin_key for r in revised.records}) == 1            # 改訂 chain は root の origin


def test_21_ambiguous_entity_is_diagnosed_not_guessed(taxonomy, catalog) -> None:
    item = news("a", "Example plant: motors and battery cells", refs=())
    record = adapt_inputs([item], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert record.entity_hits == () and any(d.startswith("AMBIGUOUS_ENTITY:example:") for d in record.diagnostics)


def test_22_context_alias_requires_context_terms(taxonomy, catalog) -> None:
    with_context = adapt_inputs([news("c", "Fed statement after FOMC", refs=())], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert [(h.entity_id, h.matched_by, h.level.value) for h in with_context.entity_hits] == [("central_bank:fed", "context_alias", "L2")]
    without = adapt_inputs([news("w", "Fed up with delays", refs=())], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert without.entity_hits == ()


def test_23_unknown_entities_produce_no_hit(taxonomy, catalog) -> None:
    refs = (EntityReference(kind=EntityKind.COMPANY, value="unknown_co", provenance=ClassificationProvenance.SOURCE_EXPLICIT),
            EntityReference(kind=EntityKind.TICKER, value="ZZZZ", provenance=ClassificationProvenance.SOURCE_EXPLICIT))
    record = adapt_inputs([news("u", "Quantum widgets", refs=refs)], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert record.entity_hits == () and record.taxonomy_hits == ()
    assert "UNKNOWN_STRUCTURED_REF:company:unknown_co" in record.diagnostics and "UNKNOWN_IDENTIFIER:TICKER:zzzz" in record.diagnostics
    ticker = adapt_inputs([news("k", "x", refs=(EntityReference(kind=EntityKind.TICKER, value="EXM2", provenance=ClassificationProvenance.SOURCE_EXPLICIT),))],
                          taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert [(h.entity_id, h.matched_by) for h in ticker.entity_hits] == [("company:example_motors", "identifier")]


def test_24_only_bounded_text_surfaces_are_scanned(taxonomy, catalog) -> None:
    item = news("b", "Quiet headline", refs=(), author="Bank of Japan", url="https://example.invalid/data-centre")
    record = adapt_inputs([item], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert record.entity_hits == () and record.taxonomy_hits == () and record.bounded_text_surfaces == (("headline", "Quiet headline"),)
    doc = document("b", "Quiet title", locator="https://example.invalid/bank-of-japan")
    drecord = adapt_inputs([doc], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert drecord.entity_hits == () and drecord.bounded_text_surfaces == (("title", "Quiet title"),)
    other = adapt_inputs([object()], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    assert other.records == () and other.excluded[0].reason == "UNSUPPORTED_INPUT"


# ---------------------------------------------------------------- 25〜36 predicates


def _record(taxonomy, catalog, item):
    return adapt_inputs([item], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]


def test_25_27_all_any_not(taxonomy, catalog) -> None:
    record = _record(taxonomy, catalog, news("p", "Datacenter power use in Japan"))
    ent = Predicate(kind=PredicateKind.ENTITY_PRESENT, entity_id="country:jp")
    dc = Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="data_center")
    nuclear = Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="nuclear")
    assert evaluate_predicate(Predicate(kind=PredicateKind.ALL, children=(ent, dc)), record).matched
    assert not evaluate_predicate(Predicate(kind=PredicateKind.ALL, children=(ent, nuclear)), record).matched
    any_out = evaluate_predicate(Predicate(kind=PredicateKind.ANY, children=(nuclear, dc)), record)
    assert any_out.matched and {h.value for h in any_out.hits} == {"data_center"}
    negated = evaluate_predicate(Predicate(kind=PredicateKind.NOT, children=(nuclear,)), record)
    assert negated.matched and negated.hits == ()
    assert not evaluate_predicate(Predicate(kind=PredicateKind.NOT, children=(dc,)), record).matched


def test_28_entity_present_distinguishes_levels(taxonomy, catalog) -> None:
    structured = _record(taxonomy, catalog, news("s", "Quiet", refs=(JP,)))
    alias_only = _record(taxonomy, catalog, news("a", "Japan outlook", refs=()))
    predicate = Predicate(kind=PredicateKind.ENTITY_PRESENT, entity_id="country:jp")
    assert [h.level for h in evaluate_predicate(predicate, structured).l1_hits] == [MatchLevel.L1]
    outcome = evaluate_predicate(predicate, alias_only)
    assert outcome.matched and outcome.l1_hits == () and [h.level for h in outcome.l2_hits] == [MatchLevel.L2]
    assert not evaluate_predicate(Predicate(kind=PredicateKind.ENTITY_PRESENT, entity_id="country:us"), structured).matched


def test_29_taxonomy_signal_exact_slug_or_alias_only(taxonomy, catalog) -> None:
    record = _record(taxonomy, catalog, news("t", "人工知能 and data_center notes", refs=()))
    assert evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="ai"), record).matched
    assert evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="data_center"), record).matched
    assert not evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="semiconductors"), record).matched


def test_30_32_fact_type_series_and_source_kind(taxonomy, catalog) -> None:
    frecord = _record(taxonomy, catalog, fact("f"))
    assert evaluate_predicate(Predicate(kind=PredicateKind.FACT_TYPE, fact_type="policy_rate_decision"), frecord).l1_hits
    assert not evaluate_predicate(Predicate(kind=PredicateKind.FACT_TYPE, fact_type="cpi_print"), frecord).matched
    orecord = _record(taxonomy, catalog, observation("o"))
    assert evaluate_predicate(Predicate(kind=PredicateKind.OBSERVATION_SERIES, series_id="nikkei225_close"), orecord).l1_hits
    assert not evaluate_predicate(Predicate(kind=PredicateKind.OBSERVATION_SERIES, series_id="topix_close"), orecord).matched
    assert evaluate_predicate(Predicate(kind=PredicateKind.SOURCE_KIND, source_kind=OriginKind.MARKET_SERIES), orecord).matched
    assert not evaluate_predicate(Predicate(kind=PredicateKind.SOURCE_KIND, source_kind=OriginKind.OFFICIAL_RELEASE), orecord).matched
    with pytest.raises(KnowledgeError):
        Predicate(kind=PredicateKind.SOURCE_KIND, source_kind=OriginKind.UNKNOWN)


def test_33_34_min_distinct_aggregate_dimensions(taxonomy, catalog) -> None:
    a = _record(taxonomy, catalog, news("a", "Data centre power", refs=(JP,)))
    b = _record(taxonomy, catalog, news("b", "Data centre power", refs=(JP,)))
    ok, diag = evaluate_aggregate((Predicate(kind=PredicateKind.MIN_DISTINCT, dimension=DistinctDimension.INPUT_ID, min_count=2),), [a, b])
    assert ok and diag == ()
    ok, diag = evaluate_aggregate((Predicate(kind=PredicateKind.MIN_DISTINCT, dimension=DistinctDimension.INPUT_ID, min_count=3),), [a, b])
    assert not ok and diag == ("MIN_DISTINCT_NOT_MET:INPUT_ID:2<3",)
    assert distinct_count([a, b, a], DistinctDimension.EVIDENCE_REF) == 2 and distinct_count([a, b], DistinctDimension.ENTITY_ID) == 1
    assert distinct_count([a, b], DistinctDimension.TAXONOMY_TOKEN) == 2
    within = Predicate(kind=PredicateKind.MIN_DISTINCT, dimension=DistinctDimension.TAXONOMY_TOKEN, min_count=2)
    assert evaluate_predicate(within, a).matched and not evaluate_predicate(
        Predicate(kind=PredicateKind.MIN_DISTINCT, dimension=DistinctDimension.ENTITY_ID, min_count=2), a).matched


def test_35_negative_predicate_excludes_without_partial_credit(taxonomy, catalog, ruleset) -> None:
    inputs = [news("1", "Nuclear power and data centre demand in Japan"), news("2", "Nuclear power and datacenter growth in Japan")]
    result = run(inputs, taxonomy, catalog, ruleset)
    ev = evaluation(result, "jp_data_center_power_demand_theme")
    assert ev.negative_exclusions == (nid("1"), nid("2")) and ev.matched_input_ids == () and ev.emitted_proposal_ids == ()
    assert all(d.startswith("EXCLUDED_BY_NEGATIVE_PREDICATE:") for d in ev.diagnostics[:2])
    assert of_type(result, ProposalType.THEME_CANDIDATE) == []


def test_36_no_parent_propagation(taxonomy, catalog) -> None:
    record = _record(taxonomy, catalog, news("g", "送電網 investment", refs=()))
    assert {h.slug for h in record.taxonomy_hits} == {"grid"}
    assert evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="grid"), record).matched
    assert not evaluate_predicate(Predicate(kind=PredicateKind.TAXONOMY_SIGNAL, slug="power"), record).matched     # 親 power は数えない


# ---------------------------------------------------------------- 37〜53 generation


def test_37_evidence_candidate_from_l1_structured_hit(taxonomy, catalog, ruleset) -> None:
    result = run([observation("o")], taxonomy, catalog, ruleset)
    proposals = of_type(result, ProposalType.EVIDENCE_CANDIDATE)
    assert len(proposals) == 1 and isinstance(proposals[0], EvidenceCandidateProposal)
    p = proposals[0]
    assert p.ref_id == oid("o") and p.proposed_role is EvidenceRole.SUPPORTS and p.source_origin.origin_key == "series:src_m/nikkei225_close"
    assert p.evidence_time == T and p.evidence_time_basis is EvidenceTimeBasis.AS_OF and p.evidence_date == "2026-09-18"
    assert p.provenance.proposer_class is ProposerClass.RULE and p.provenance.proposer_ref == "rule:nikkei_series_observation_evidence"
    assert p.provenance.rule_version == "0.1.0" and p.provenance.reason == "pins taxonomy=0.2.0 catalog=0.2.0 ruleset=0.1.0"
    assert p.reason == evidence_reason(EvidenceRole.SUPPORTS, "OBSERVATION") == "discovery evidence candidate supports observation"
    ev = evaluation(result, "nikkei_series_observation_evidence")
    assert ev.l1_hit_count == 2 and ev.l2_hit_count == 0 and ev.emitted_proposal_ids == (p.proposal_id,)


def test_38_evidence_candidate_from_l2_alias_only(taxonomy, catalog, ruleset) -> None:
    result = run([news("x", "Datacenter operators expand", refs=())], taxonomy, catalog, ruleset)
    proposals = of_type(result, ProposalType.EVIDENCE_CANDIDATE)
    assert [p.provenance.proposer_ref for p in proposals] == ["rule:data_center_alias_evidence"]
    assert proposals[0].proposed_role is EvidenceRole.CONTEXT and proposals[0].target_root_id == ""
    ev = evaluation(result, "data_center_alias_evidence")
    assert ev.l1_hit_count == 0 and ev.l2_hit_count == 1


def test_39_theme_candidate_from_l1_hit_with_complete_structure(taxonomy, catalog, ruleset) -> None:
    inputs = [news("1", "Data centre construction lifts power demand in Japan"), news("2", "Datacenter operators sign electric power contracts")]
    result = run(inputs, taxonomy, catalog, ruleset)
    themes = of_type(result, ProposalType.THEME_CANDIDATE)
    assert len(themes) == 1 and isinstance(themes[0], ThemeCandidateProposal)
    cand = themes[0]
    assert cand.certainty_class is FIXED_CERTAINTY is MechanismCertainty.HYPOTHESIZED_MECHANISM
    assert cand.subject.typed_reference == "country:jp" and cand.subject.normalized_subject == "japan electricity demand from data center construction"
    assert {(s.dimension, s.value) for s in cand.scope} == {(ScopeDimension.REGION, "country:jp"), (ScopeDimension.PERIOD_FRAME, "multi_year")}
    assert [c.condition_key for c in cand.invalidation_conditions] == ["dc_pipeline_contraction"] and len(cand.limitations) == 1
    assert [a.ref_id for a in cand.evidence_refs] == [nid("1"), nid("2")]
    assert all(a.role is EvidenceRole.SUPPORTS and a.consequence_ref == "consequence_1" and a.role_asserted_by == TEMPLATE_PROVENANCE_REF
               and a.attached_at == RUN_AT for a in cand.evidence_refs)
    assert cand.provenance.proposer_ref == "rule:jp_data_center_power_demand_theme" and cand.created_at == RUN_AT
    ev = evaluation(result, "jp_data_center_power_demand_theme")
    assert ev.l1_hit_count == 2 and ev.aggregate_satisfied and ev.emitted_proposal_ids == (cand.proposal_id,)


def test_40_l2_only_hits_cannot_create_theme_candidate(taxonomy, catalog, ruleset) -> None:
    inputs = [news("1", "Japan data centre construction lifts power demand", refs=()), news("2", "Japan datacenter electric power contracts", refs=())]
    result = run(inputs, taxonomy, catalog, ruleset)
    ev = evaluation(result, "jp_data_center_power_demand_theme")
    assert ev.matched_input_ids == (nid("1"), nid("2")) and ev.l1_hit_count == 0 and ev.l2_hit_count > 0
    assert "THEME_CANDIDATE_REQUIRES_L1_HIT" in ev.diagnostics and ev.emitted_proposal_ids == ()
    assert of_type(result, ProposalType.THEME_CANDIDATE) == []
    assert of_type(result, ProposalType.EVIDENCE_CANDIDATE)                            # L2 だけでも EVIDENCE_CANDIDATE は出る


def test_41_complete_mechanism_comes_from_template_not_keywords(taxonomy, catalog, ruleset) -> None:
    result = run([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan")], taxonomy, catalog, ruleset)
    cand = of_type(result, ProposalType.THEME_CANDIDATE)[0]
    m = cand.mechanism
    assert [d.category for d in m.drivers] == ["DEMAND_SHIFT"] and [c.category for c in m.channels] == ["VOLUME_DEMAND"]
    assert [d.category for d in m.domains] == ["REGION"] and m.domains[0].typed_reference == "country:jp"
    assert [c.category for c in m.consequences] == ["MACRO_STATISTIC"] and m.consequences[0].component_key == "consequence_1"
    assert all(c.provenance_ref == TEMPLATE_PROVENANCE_REF for c in m.drivers + m.channels + m.domains + m.consequences)
    assert "datacenter" not in json.dumps(cand.mechanism.__dict__, default=str).lower()      # alias 文字列は機構に入らない


def test_42_certainty_is_fixed_and_not_authorable(tmp_path, taxonomy, catalog) -> None:
    with pytest.raises(KnowledgeError) as info:
        load_rules(tmp_path, [theme_rule("t", certainty_class="EVIDENCE_SUPPORTED_MECHANISM")], taxonomy, catalog)
    assert info.value.code == "UNKNOWN_FIELD"


def test_43_only_supports_or_context_roles_reach_attachments(tmp_path, taxonomy, catalog) -> None:
    rs = load_rules(tmp_path, [theme_rule("ctx", proposed_role="CONTEXT")], taxonomy, catalog)
    result = run([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan")], taxonomy, catalog, rs)
    cand = of_type(result, ProposalType.THEME_CANDIDATE)[0]
    assert all(a.role is EvidenceRole.CONTEXT and a.consequence_ref == "" for a in cand.evidence_refs)
    assert {a.role for p in of_type(result, ProposalType.THEME_CANDIDATE) for a in p.evidence_refs} <= {EvidenceRole.SUPPORTS, EvidenceRole.CONTEXT}


def test_44_45_same_rule_evidence_is_deterministic_and_collapsed(taxonomy, catalog, ruleset) -> None:
    a, b, c = (news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan"),
               news("3", "Electric power tariffs for data centre operators in Japan"))
    first = run([a, b, c], taxonomy, catalog, ruleset)
    second = run([c, a, b, a], taxonomy, catalog, ruleset)                                 # 順序違い ＋ 重複入力
    cand1 = of_type(first, ProposalType.THEME_CANDIDATE)
    cand2 = of_type(second, ProposalType.THEME_CANDIDATE)
    assert [p.proposal_id for p in cand1] == [p.proposal_id for p in cand2]
    assert [x.ref_id for x in cand1[0].evidence_refs] == sorted(x.ref_id for x in cand1[0].evidence_refs)
    assert len({x.ref_id for x in cand2[0].evidence_refs}) == len(cand2[0].evidence_refs) == 3
    assert f"DUPLICATE_INPUT_ID:{nid('1')}" in second.run_report.diagnostics


def test_46_same_origin_evidence_is_not_called_independent(taxonomy, catalog, ruleset) -> None:
    item = news("1", "Data centre power in Japan", article="art_same", document=did("1"))
    doc = document("1", "Data centre power in Japan")
    result = run([item, doc], taxonomy, catalog, ruleset)
    ev = evaluation(result, "jp_data_center_power_demand_theme")
    assert ev.matched_input_ids == (did("1"), nid("1")) and ev.aggregate_satisfied                 # 2 入力・1 origin
    assert "EVIDENCE_REFS:2;ORIGIN_KEYS:1;NOT_AN_INDEPENDENCE_CLAIM" in ev.diagnostics
    assert result.run_report.origin_groups == (("article:art_same", (did("1"), nid("1"))),)
    plain = json.dumps(result.run_report.to_plain())
    assert "independent_source" not in plain and "source_diversity" not in plain


def test_47_no_qualification_claim_or_scores(taxonomy, catalog, ruleset) -> None:
    result = run([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan"), observation("o")], taxonomy, catalog, ruleset)
    plain = json.dumps(result.run_report.to_plain()).lower()
    for token in ("qualif", "score", "rank", "confidence", "stance", "buy", "sell", "weight"):
        assert token not in plain, token
    cand = of_type(result, ProposalType.THEME_CANDIDATE)[0]
    assert not hasattr(cand, "qualification") and not hasattr(cand, "score")


def test_48_no_cross_rule_mechanism_assembly(tmp_path, taxonomy, catalog) -> None:
    rule_a = theme_rule("rule_a", predicate={"kind": "ALL", "children": [{"kind": "ENTITY_PRESENT", "entity_id": "country:jp"},
                                                                          {"kind": "TAXONOMY_SIGNAL", "slug": "data_center"}]},
                        taxonomy_refs=["data_center"])
    rule_b = theme_rule("rule_b", predicate={"kind": "ALL", "children": [{"kind": "ENTITY_PRESENT", "entity_id": "country:jp"},
                                                                          {"kind": "TAXONOMY_SIGNAL", "slug": "power"}]},
                        taxonomy_refs=["power"])
    rs = load_rules(tmp_path, [rule_a, rule_b], taxonomy, catalog)
    x, y = news("x", "Datacenter build in Japan"), news("y", "Electric power tariffs in Japan")
    result = run([x, y], taxonomy, catalog, rs)
    themes = of_type(result, ProposalType.THEME_CANDIDATE)
    assert len(themes) == 2 and {tuple(a.ref_id for a in t.evidence_refs) for t in themes} == {(nid("x"),), (nid("y"),)}
    assert evaluation(result, "rule_a").converged_proposal_ids == () and evaluation(result, "rule_b").converged_proposal_ids == ()


def test_49_equivalent_semantic_proposals_converge_across_rules(taxonomy, catalog, ruleset) -> None:
    inputs = [news("1", "Data centre and power grid expansion lifts electric power demand in Japan"),
              news("2", "Datacenter and 送電網 build-out raises electric power use in Japan")]
    result = run(inputs, taxonomy, catalog, ruleset)
    themes = of_type(result, ProposalType.THEME_CANDIDATE)
    assert len(themes) == 1
    dc, grid = evaluation(result, "jp_data_center_power_demand_theme"), evaluation(result, "jp_grid_power_demand_theme")
    assert dc.emitted_proposal_ids == grid.emitted_proposal_ids == (themes[0].proposal_id,)
    assert dc.converged_proposal_ids == grid.converged_proposal_ids == (themes[0].proposal_id,)
    assert result.run_report.proposal_ids.count(themes[0].proposal_id) == 1


def test_50_rule_provenance_lives_outside_semantic_identity(tmp_path, taxonomy, catalog) -> None:
    inputs = [news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan")]
    only_a = run(inputs, taxonomy, catalog, load_rules(tmp_path / "a", [theme_rule("rule_a")], taxonomy, catalog))
    only_b = run(inputs, taxonomy, catalog, load_rules(tmp_path / "b", [theme_rule("rule_b", rule_version="2.0.0")], taxonomy, catalog))
    a, b = of_type(only_a, ProposalType.THEME_CANDIDATE)[0], of_type(only_b, ProposalType.THEME_CANDIDATE)[0]
    assert a.proposal_id == b.proposal_id and a.identity_payload() == b.identity_payload()
    assert (a.provenance.proposer_ref, a.provenance.rule_version) == ("rule:rule_a", "0.1.0")
    assert (b.provenance.proposer_ref, b.provenance.rule_version) == ("rule:rule_b", "2.0.0")
    assert "provenance" not in a.identity_payload() and "rule_a" not in json.dumps(a.identity_payload())


def test_51_canonical_reason_is_rule_version_independent(tmp_path, taxonomy, catalog, ruleset) -> None:
    item = news("r", "Bank of Japan holds", refs=())
    base = of_type(run([item], taxonomy, catalog, ruleset), ProposalType.EVIDENCE_CANDIDATE)
    bumped = load_rules(tmp_path, [rule("boj_context_evidence", rule_version="0.9.3")], taxonomy, catalog)
    again = of_type(run([item], taxonomy, catalog, bumped), ProposalType.EVIDENCE_CANDIDATE)
    assert [p.proposal_id for p in base] == [p.proposal_id for p in again]
    assert again[0].reason == "discovery evidence candidate context news_item" and again[0].provenance.rule_version == "0.9.3"
    assert "0.9.3" not in again[0].reason and "boj" not in again[0].reason


def test_52_53_run_created_at_is_explicit_and_no_clock(taxonomy, catalog, ruleset) -> None:
    later = RUN_AT + timedelta(days=3)
    result = run([observation("o")], taxonomy, catalog, ruleset, run_created_at=later)
    assert all(p.created_at == later for p in result.proposals) and result.run_report.run_created_at == later
    with pytest.raises(DiscoveryError) as info:
        run([observation("o")], taxonomy, catalog, ruleset, run_created_at=CUTOFF - timedelta(seconds=1))
    assert info.value.code == "INVALID_RUN_TIME"
    with pytest.raises(DiscoveryError):
        run([observation("o")], taxonomy, catalog, ruleset, run_created_at=datetime(2026, 9, 21))                     # naive
    with pytest.raises(DiscoveryError):
        run([observation("o")], taxonomy, catalog, ruleset, cutoff=datetime(2026, 9, 21))                              # naive cutoff
    assert result.run_report.discovery_model_version == DISCOVERY_MODEL_VERSION


# ---------------------------------------------------------------- 54〜60 suppression / decisions


def _decision(proposal_id: str, kind: DecisionKind, *, at=RUN_AT + timedelta(hours=1)) -> ProposalDecision:
    return ProposalDecision.build(proposal_id=proposal_id, decision=kind, actor_ref="reviewer:r9", reason="reviewed", recorded_at=at)


@pytest.mark.parametrize("kind,status_token", [(None, "OPEN"), (DecisionKind.DEFER, "OPEN_DEFERRED"), (DecisionKind.ACCEPT, "ACCEPTED"),
                                               (DecisionKind.REJECT, "REJECTED")])
def test_54_57_existing_proposals_suppress_duplicates_and_report_decision_state(taxonomy, catalog, ruleset, kind, status_token) -> None:
    inputs = [observation("o"), news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan")]
    first = run(inputs, taxonomy, catalog, ruleset)
    decisions = tuple(_decision(p.proposal_id, kind) for p in first.proposals) if kind else ()
    second = run(inputs, taxonomy, catalog, ruleset, existing_proposals=first.proposals, existing_decisions=decisions,
                 run_created_at=RUN_AT + timedelta(days=1))
    assert second.proposals == () and set(second.run_report.suppressed_existing_ids) == {p.proposal_id for p in first.proposals}
    assert all(f"EXISTING_{status_token}_PROPOSAL:{p.proposal_id}" in second.run_report.diagnostics for p in first.proposals)
    assert all(evaluation(second, e.rule_id).emitted_proposal_ids == e.emitted_proposal_ids for e in first.run_report.rule_evaluations)


def test_58_materially_different_proposal_gets_new_id(taxonomy, catalog, ruleset) -> None:
    first = run([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan")], taxonomy, catalog, ruleset)
    old = of_type(first, ProposalType.THEME_CANDIDATE)[0]
    second = run([news("1", "Data centre power in Japan"), news("3", "Datacenter power tariffs in Japan")], taxonomy, catalog, ruleset,
                 existing_proposals=first.proposals, existing_decisions=(_decision(old.proposal_id, DecisionKind.REJECT),))
    new = of_type(second, ProposalType.THEME_CANDIDATE)
    assert len(new) == 1 and new[0].proposal_id != old.proposal_id and old.proposal_id not in second.run_report.proposal_ids
    assert new[0].semantic_fingerprint == old.semantic_fingerprint                     # 同じ機構・別 evidence ＝ 別 proposal ＋ dedup review
    first_evidence = {p.proposal_id for p in of_type(first, ProposalType.EVIDENCE_CANDIDATE)}
    assert old.proposal_id not in second.run_report.suppressed_existing_ids            # 却下済み id は再生成されず、新 id も付け替えない
    assert set(second.run_report.suppressed_existing_ids) <= first_evidence            # 共通入力の evidence 候補だけが既存として抑制される


def test_59_60_discovery_never_mutates_decisions(taxonomy, catalog, ruleset) -> None:
    inputs = [observation("o")]
    first = run(inputs, taxonomy, catalog, ruleset)
    decisions = (_decision(first.proposals[0].proposal_id, DecisionKind.REJECT),)
    before = derive_proposal_status(first.proposals[0], decisions)
    second = run(inputs, taxonomy, catalog, ruleset, existing_proposals=first.proposals, existing_decisions=decisions)
    assert derive_proposal_status(first.proposals[0], decisions) is before
    assert not any(isinstance(p, ProposalDecision) for p in second.proposals)
    assert f"EXISTING_REJECTED_PROPOSAL:{first.proposals[0].proposal_id}" in second.run_report.diagnostics


# ---------------------------------------------------------------- 61〜63 dedup


def test_61_exact_dedup_review_for_equivalent_existing_theme_candidate(taxonomy, catalog, ruleset) -> None:
    first = run([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan")], taxonomy, catalog, ruleset)
    old = of_type(first, ProposalType.THEME_CANDIDATE)[0]
    second = run([news("3", "Data centre power tariffs in Japan"), news("4", "Datacenter power contracts in Japan")], taxonomy, catalog, ruleset,
                 existing_proposals=first.proposals)
    reviews = of_type(second, ProposalType.DEDUP_REVIEW)
    assert len(reviews) == 1 and isinstance(reviews[0], DedupReviewProposal)
    review = reviews[0]
    new = of_type(second, ProposalType.THEME_CANDIDATE)[0]
    assert review.subject_proposal_id == new.proposal_id and review.dedup_class is DedupClass.EXACT_SEMANTIC_MATCH
    assert [c.ref_id for c in review.counterparts] == [old.proposal_id]
    assert second.run_report.dedup_review_ids == (review.proposal_id,) and review.proposal_id in second.run_report.proposal_ids


def test_62_not_duplicate_decision_suppresses_review(taxonomy, catalog, ruleset) -> None:
    first = run([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan")], taxonomy, catalog, ruleset)
    second_inputs = [news("3", "Data centre power tariffs in Japan"), news("4", "Datacenter power contracts in Japan")]
    second = run(second_inputs, taxonomy, catalog, ruleset, existing_proposals=first.proposals)
    review = of_type(second, ProposalType.DEDUP_REVIEW)[0]
    existing = tuple(first.proposals) + tuple(second.proposals)
    decided = (_decision(review.proposal_id, DecisionKind.NOT_DUPLICATE),)
    third = run(second_inputs, taxonomy, catalog, ruleset, existing_proposals=existing, existing_decisions=decided,
                run_created_at=RUN_AT + timedelta(days=2))
    assert of_type(third, ProposalType.DEDUP_REVIEW) == [] and third.run_report.dedup_review_ids == ()
    assert review.proposal_id in third.run_report.suppressed_existing_ids or of_type(third, ProposalType.THEME_CANDIDATE) == []


def test_63_dedup_is_exact_only_and_optional(taxonomy, catalog, ruleset) -> None:
    first = run([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan")], taxonomy, catalog, ruleset)
    second = run([news("3", "Data centre power tariffs in Japan"), news("4", "Datacenter power contracts in Japan")], taxonomy, catalog, ruleset,
                 existing_proposals=first.proposals, include_dedup=False)
    assert of_type(second, ProposalType.DEDUP_REVIEW) == []
    with_dedup = run([news("3", "Data centre power tariffs in Japan"), news("4", "Datacenter power contracts in Japan")], taxonomy, catalog, ruleset,
                     existing_proposals=first.proposals)
    assert all(r.dedup_class in (DedupClass.EXACT_SEMANTIC_MATCH, DedupClass.EXACT_IDENTITY_CORE_MATCH)
               for r in of_type(with_dedup, ProposalType.DEDUP_REVIEW))


# ---------------------------------------------------------------- 64〜68 replay / PIT


def test_64_65_shuffled_inputs_and_reloaded_knowledge_replay_identically(taxonomy, catalog, ruleset) -> None:
    inputs = [news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan"), observation("o"), fact("f"),
              document("d", "Bank of Japan on electric power"), news("3", "Nuclear power and data centre in Japan")]
    base = run(inputs, taxonomy, catalog, ruleset)
    for seed in (1, 7, 42):
        shuffled = list(inputs)
        random.Random(seed).shuffle(shuffled)
        again = run(shuffled, taxonomy, catalog, ruleset)
        assert [p.proposal_id for p in again.proposals] == [p.proposal_id for p in base.proposals]
        assert again.run_report.to_plain() == base.run_report.to_plain()
    tax2 = load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUTOFF)
    cat2 = load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUTOFF)
    rs2 = load_discovery_rules_version(discovery_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=CUTOFF, taxonomy=tax2,
                                       entity_catalog=cat2)
    assert run(inputs, tax2, cat2, rs2).run_report.to_plain() == base.run_report.to_plain()


def test_66_68_future_knowledge_never_leaks_into_an_earlier_cutoff(taxonomy, catalog, ruleset) -> None:
    early = datetime(2026, 9, 20, 0, 30, tzinfo=UTC)                                    # taxonomy / catalog 0.2.0（01:00）より前
    with pytest.raises(DiscoveryError) as info:
        run([observation("o")], taxonomy, catalog, ruleset, cutoff=early, run_created_at=early)
    assert info.value.code == "FUTURE_KNOWLEDGE" and "taxonomy" in info.value.detail
    tax1 = load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=early)
    with pytest.raises(DiscoveryError) as info:
        run([observation("o")], tax1, catalog, ruleset, cutoff=early, run_created_at=early)
    assert info.value.code == "FUTURE_KNOWLEDGE" and "entity_catalog" in info.value.detail
    mid = datetime(2026, 9, 20, 1, 30, tzinfo=UTC)                                      # ruleset 0.1.0（02:00）より前
    with pytest.raises(DiscoveryError) as info:
        run([observation("o")], taxonomy, catalog, ruleset, cutoff=mid, run_created_at=mid)
    assert info.value.code == "FUTURE_KNOWLEDGE" and "ruleset" in info.value.detail
    with pytest.raises(KnowledgeError) as info:
        load_discovery_rules_version(discovery_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=mid)
    assert info.value.code == "FUTURE_VERSION"
