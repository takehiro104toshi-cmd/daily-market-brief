"""P2-E: 品質レポート・legacy比較（not ground truth）・serializationのテスト。"""
from __future__ import annotations

from src.intelligence.core import serialization
from src.intelligence.core.ids import content_id
from src.intelligence.databank.news_model import LegacyAnnotation
from src.intelligence.enrichment.model import EnrichmentRun, ReviewQueueItem, ReviewReason
from src.intelligence.enrichment.quality_report import build_quality_report

from .enrichment_fixtures import NOW, catalogs, make_engine, make_item


def _corpus(engine):
    items = [
        make_item("Nvidia earnings beat estimates as AI chip demand surges"),
        make_item("日銀、利上げを見送り 円安が進行", language="ja"),
        make_item("Hot tubs and £80 rosé: festival gets a luxury makeover"),
    ]
    for i in items:
        engine.enrich_item(i, now=NOW)
    return items


class TestQualityReport:
    def test_coverage_and_unclassified(self, tmp_path):
        engine = make_engine(tmp_path)
        items = _corpus(engine)
        _ec, tt, _et = catalogs()
        report = build_quality_report(engine.store, items, theme_taxonomy=tt)
        assert report["items"] == 3
        assert report["unclassified"] == 1  # festival記事
        assert report["coverage"]["theme"]["items_tagged"] == 2
        assert report["coverage"]["company"]["items_tagged"] == 1
        assert ("ai", 1) in report["coverage"]["theme"]["top_values"]
        assert report["by_language"]["ja"]["classified_pct"] == 100.0
        assert "multi_label_theme_distribution" in report

    def test_legacy_agreement_is_reference_only(self, tmp_path):
        engine = make_engine(tmp_path)
        items = _corpus(engine)
        # tank由来のlegacyテーマ（en slug）を1件目のdocへ付与（not ground truth）
        ann = LegacyAnnotation(
            annotation_id=content_id("lga", items[0].primary_document_id, "tank"),
            target_record_id=items[0].primary_document_id,
            origin="tank",
            annotations=(("themes", "['ai', 'semiconductor']"),
                         ("importance_score", "87")),
        )
        _ec, tt, _et = catalogs()
        report = build_quality_report(engine.store, items, theme_taxonomy=tt,
                                      legacy_annotations=[ann])
        agreement = report["legacy_agreement"]
        assert "NOT ground truth" in agreement["note"]
        assert agreement["items_with_mappable_legacy_theme"] == 1
        assert agreement["any_overlap_agreement"] == 1  # ai/semiconductorsが新分類と重なる
        # legacyのimportance_scoreは新分類へ昇格していない
        assert all(c.value != "87" for c in engine.store.iter_classifications())


class TestSerializationRoundtrip:
    def test_enrichment_types_roundtrip(self, tmp_path):
        serialization.register_domain_types()
        engine = make_engine(tmp_path)
        item = make_item("Nvidia earnings beat estimates")
        engine.enrich_item(item, now=NOW)
        for c in engine.store.iter_classifications():
            assert serialization.decode(serialization.encode(c)) == c
        for e in engine.store.iter_events():
            assert serialization.decode(serialization.encode(e)) == e
        review = ReviewQueueItem(
            review_id=ReviewQueueItem.make_id("news_x", "theme", "cand", "llm_unknown_label"),
            news_item_id="news_x", dimension="theme", candidate_value="cand",
            reason=ReviewReason.LLM_UNKNOWN_LABEL, created_at=NOW)
        assert serialization.decode(serialization.encode(review)) == review
        run = EnrichmentRun(run_id="erun_TEST", started_at=NOW, records_seen=3)
        assert serialization.decode(serialization.encode(run)) == run

    def test_pre_p2e_classification_decodes(self, tmp_path):
        """0.3.x時代（confidence等なし）のNewsClassificationが前方互換で読める。"""
        serialization.register_domain_types()
        engine = make_engine(tmp_path)
        item = make_item("Nvidia earnings beat estimates")
        engine.enrich_item(item, now=NOW)
        c = list(engine.store.iter_classifications())[0]
        encoded = serialization.encode(c)
        for key in ("confidence", "confidence_type", "role", "evidence_field",
                    "evidence_text", "taxonomy_version", "basis_document_id"):
            encoded.pop(key, None)
        decoded = serialization.decode(encoded)
        assert decoded.confidence is None and decoded.role == ""
