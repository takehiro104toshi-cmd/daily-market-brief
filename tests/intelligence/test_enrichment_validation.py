"""P2-E: enrichment整合性検証（検知のみ・自動修復なし）のテスト。"""
from __future__ import annotations

from src.intelligence.databank.news_model import (
    ClassificationDimension,
    ClassificationProvenance,
    NewsClassification,
)
from src.intelligence.enrichment.store import JsonlEnrichmentStore
from src.intelligence.enrichment.validation import validate_enrichment

from .enrichment_fixtures import NOW, catalogs, make_engine, make_item


def _cls(item_id, dimension, value, provenance, classifier="x", version="1.0.0", **kw):
    return NewsClassification(
        classification_id=NewsClassification.make_id(
            item_id, dimension.value, value, f"{classifier}:{version}"),
        news_item_id=item_id, dimension=dimension, value=value,
        provenance=provenance, classifier_name=classifier, classifier_version=version,
        created_at=NOW, **kw)


def _validate(store, item_ids, **kw):
    ec, tt, et = catalogs()
    return validate_enrichment(store, news_item_ids=set(item_ids),
                               entity_catalog=ec, theme_taxonomy=tt,
                               event_taxonomy=et, **kw)


class TestValidation:
    def test_clean_engine_output_has_no_issues(self, tmp_path):
        engine = make_engine(tmp_path)
        items = [make_item("Nvidia earnings beat estimates as AI chip demand surges",
                           summary="Semiconductor giant posted record results."),
                 make_item("日銀、利上げを見送り 円安が進行")]
        for item in items:
            engine.enrich_item(item, now=NOW)
        issues = _validate(engine.store, [i.news_item_id for i in items],
                           news_items_by_id={i.news_item_id: i for i in items},
                           document_ids={i.primary_document_id for i in items})
        assert issues == ()

    def test_orphan_classification_detected(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_ghost", ClassificationDimension.THEME, "ai",
                                      ClassificationProvenance.RULE_BASED))
        issues = _validate(store, ["news_real"])
        assert [i.check for i in issues] == ["orphan_classification"]

    def test_unknown_taxonomy_value_detected(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_a", ClassificationDimension.THEME,
                                      "not_a_theme", ClassificationProvenance.RULE_BASED))
        issues = _validate(store, ["news_a"])
        assert any(i.check == "unknown_taxonomy_value" for i in issues)

    def test_llm_unknown_label_in_canonical_detected(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_a", ClassificationDimension.THEME,
                                      "hallucinated_theme", ClassificationProvenance.LLM))
        issues = _validate(store, ["news_a"])
        assert any(i.check == "llm_unknown_label_in_canonical" for i in issues)

    def test_unknown_entity_value_detected(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_a", ClassificationDimension.COMPANY,
                                      "company:ghost_corp",
                                      ClassificationProvenance.ENTITY_DATABASE))
        issues = _validate(store, ["news_a"])
        assert any(i.check == "unknown_entity_value" for i in issues)

    def test_source_explicit_vocabulary_not_flagged(self, tmp_path):
        # source側の語彙はcanon外でも許容（機械分類のみをtaxonomyで縛る）
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_a", ClassificationDimension.THEME,
                                      "source-side-tag",
                                      ClassificationProvenance.SOURCE_EXPLICIT))
        issues = _validate(store, ["news_a"])
        assert issues == ()

    def test_duplicate_enrichment_detected(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        a = _cls("news_a", ClassificationDimension.THEME, "ai",
                 ClassificationProvenance.RULE_BASED)
        # 同一(item, dim, value, classifier, version)で別IDのレコードを手作りで注入
        b = NewsClassification(**{**a.__dict__, "classification_id": "cls_forgeddifferent0001"})
        store.add_classification(a)
        store.add_classification(b)
        issues = _validate(store, ["news_a"])
        assert any(i.check == "duplicate_enrichment" for i in issues)

    def test_evidence_span_mismatch_detected(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        item = make_item("A headline about markets")
        store.add_classification(_cls(
            item.news_item_id, ClassificationDimension.THEME, "ai",
            ClassificationProvenance.RULE_BASED,
            evidence_field="headline", evidence_text="quantum computing"))
        issues = _validate(store, [item.news_item_id],
                           news_items_by_id={item.news_item_id: item})
        assert any(i.check == "evidence_span_mismatch" for i in issues)

    def test_revision_linkage_broken_detected(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_a", ClassificationDimension.THEME, "ai",
                                      ClassificationProvenance.RULE_BASED,
                                      basis_document_id="doc_missing"))
        issues = _validate(store, ["news_a"], document_ids={"doc_other"})
        assert any(i.check == "revision_linkage_broken" for i in issues)

    def test_user_conflict_on_single_valued_dimension(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_a", ClassificationDimension.EVENT_TYPE,
                                      "EARNINGS", ClassificationProvenance.USER,
                                      classifier="user_override"))
        store.add_classification(_cls("news_a", ClassificationDimension.EVENT_TYPE,
                                      "GUIDANCE", ClassificationProvenance.USER,
                                      classifier="user_override2"))
        issues = _validate(store, ["news_a"])
        assert any(i.check == "override_conflict" for i in issues)
