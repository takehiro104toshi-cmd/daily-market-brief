"""P2-E: EnrichmentEngine（層分離・provenance・冪等・禁止事項）のテスト。"""
from __future__ import annotations

from src.intelligence.databank.news_model import (
    ClassificationDimension,
    ClassificationProvenance,
    EntityKind,
    EntityReference,
    ThemeReference,
)

from .enrichment_fixtures import NOW, make_engine, make_item

HEADLINE = "Nvidia earnings beat estimates as AI chip demand surges"
SUMMARY = "The semiconductor giant posted record data center revenue."


class TestEngineProvenance:
    def test_every_classification_has_full_provenance(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item(HEADLINE, summary=SUMMARY)
        engine.enrich_item(item, now=NOW)
        classifications = engine.store.classifications_for(item.news_item_id)
        assert classifications
        for c in classifications:
            assert c.provenance in (ClassificationProvenance.ENTITY_DATABASE,
                                    ClassificationProvenance.RULE_BASED)
            assert c.classifier_name and c.classifier_version
            assert c.taxonomy_version  # 使用カタログの版
            assert c.created_at == NOW
            assert c.basis_document_id == item.primary_document_id

    def test_company_match_also_emits_ticker_dimension(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item(HEADLINE)
        engine.enrich_item(item, now=NOW)
        by_dim = {}
        for c in engine.store.classifications_for(item.news_item_id):
            by_dim.setdefault(c.dimension, []).append(c.value)
        assert "company:nvidia" in by_dim[ClassificationDimension.COMPANY]
        assert "NVDA" in by_dim[ClassificationDimension.TICKER]

    def test_evidence_span_verbatim_in_field(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item(HEADLINE, summary=SUMMARY)
        engine.enrich_item(item, now=NOW)
        for c in engine.store.classifications_for(item.news_item_id):
            if c.evidence_field == "headline":
                assert c.evidence_text.lower() in item.headline.lower()
            elif c.evidence_field == "summary":
                assert c.evidence_text.lower() in item.summary.lower()

    def test_add_events_appended_per_classification(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item(HEADLINE)
        outcome = engine.enrich_item(item, now=NOW)
        assert outcome.events_added == outcome.classifications_added
        events = [e for e in engine.store.iter_events()
                  if e.news_item_id == item.news_item_id]
        assert len(events) == outcome.classifications_added


class TestEngineIdempotency:
    def test_rerun_adds_nothing(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item(HEADLINE, summary=SUMMARY)
        first = engine.enrich_item(item, now=NOW)
        assert first.classifications_added > 0
        second = engine.enrich_item(item, now=NOW)
        assert second.classifications_added == 0
        assert second.events_added == 0
        assert second.review_queued == 0


class TestSourceExplicitLayer:
    def test_source_refs_imported_with_source_explicit(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item(
            "Some unrelated headline",
            entity_refs=(EntityReference(kind=EntityKind.TICKER, value="7203.T"),),
            theme_refs=(ThemeReference(theme_label="半導体"),))
        engine.enrich_item(item, now=NOW)
        classifications = engine.store.classifications_for(item.news_item_id)
        provs = {(c.dimension.value, c.value): c.provenance for c in classifications}
        assert provs[("ticker", "7203.T")] is ClassificationProvenance.SOURCE_EXPLICIT
        assert provs[("theme", "半導体")] is ClassificationProvenance.SOURCE_EXPLICIT


class TestProhibitions:
    """DO NOT: Fact抽出・市場影響・重要度・sentimentを生成しない。"""

    def test_only_allowed_dimensions_produced(self, tmp_path):
        engine = make_engine(tmp_path)
        for headline in (HEADLINE, "Fed holds rates steady", "Oil prices surge on sanctions"):
            engine.enrich_item(make_item(headline), now=NOW)
        allowed = set(ClassificationDimension)
        for c in engine.store.iter_classifications():
            assert c.dimension in allowed
            assert c.value not in ("bullish", "bearish", "positive", "negative")

    def test_no_scores_generated(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.enrich_item(make_item(HEADLINE), now=NOW)
        # enrichment storeにはscore系ファイル自体が存在しない
        assert not (tmp_path / "enrichment" / "scores.jsonl").exists()


class TestReviewQueueFromEngine:
    def test_ambiguous_alias_queued_once(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item("Apple falls from tree in Somerset orchard")
        first = engine.enrich_item(item, now=NOW)
        assert first.review_queued == 1
        second = engine.enrich_item(item, now=NOW)
        assert second.review_queued == 0  # 冪等（同一候補を積み上げない）
        queue = list(engine.store.iter_review_queue())
        assert len(queue) == 1 and queue[0].candidate_value == "company:apple"
