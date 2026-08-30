"""P2-E: enrichment store（append-only・冪等・effective view・override）のテスト。"""
from __future__ import annotations

import pytest

from src.intelligence.databank.news_model import (
    ClassificationDimension,
    ClassificationProvenance,
    NewsClassification,
)
from src.intelligence.enrichment.model import EnrichmentAction
from src.intelligence.enrichment.override import apply_user_override, retract_classification
from src.intelligence.enrichment.store import JsonlEnrichmentStore

from .enrichment_fixtures import NOW, make_engine, make_item


def _cls(item_id: str, value: str, *, provenance=ClassificationProvenance.RULE_BASED,
         dimension=ClassificationDimension.THEME, classifier="theme_rule_matcher",
         version="1.0.0") -> NewsClassification:
    return NewsClassification(
        classification_id=NewsClassification.make_id(
            item_id, dimension.value, value, f"{classifier}:{version}"),
        news_item_id=item_id, dimension=dimension, value=value,
        provenance=provenance, classifier_name=classifier, classifier_version=version,
        created_at=NOW)


class TestStoreDiscipline:
    def test_idempotent_add_and_collision_guard(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        c = _cls("news_x", "ai")
        assert store.add_classification(c) is True
        assert store.add_classification(c) is False  # 冪等skip
        conflicting = NewsClassification(
            **{**c.__dict__, "evidence_text": "different"})
        with pytest.raises(ValueError, match="collision"):
            store.add_classification(conflicting)

    def test_reopen_from_jsonl(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_x", "ai"))
        store.add_classification(_cls("news_x", "semiconductors"))
        reopened = JsonlEnrichmentStore(tmp_path / "e")
        assert len(reopened.classifications_for("news_x")) == 2
        assert reopened.recovered_lines == 0

    def test_append_only_no_mutation_api(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        assert not hasattr(store, "update_classification")
        assert not hasattr(store, "delete_classification")


class TestEffectiveView:
    def test_precedence_user_over_llm_and_rules(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_x", "ai",
                                      provenance=ClassificationProvenance.LLM,
                                      classifier="llm_classifier"))
        store.add_classification(_cls("news_x", "ai",
                                      provenance=ClassificationProvenance.RULE_BASED))
        effective = store.effective_classifications("news_x")
        assert len(effective) == 1  # 同(dimension, value)は1代表
        assert effective[0].provenance is ClassificationProvenance.RULE_BASED

    def test_source_explicit_priority_over_llm(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_x", "EARNINGS",
                                      dimension=ClassificationDimension.EVENT_TYPE,
                                      provenance=ClassificationProvenance.LLM,
                                      classifier="llm_classifier"))
        store.add_classification(_cls("news_x", "EARNINGS",
                                      dimension=ClassificationDimension.EVENT_TYPE,
                                      provenance=ClassificationProvenance.SOURCE_EXPLICIT,
                                      classifier="source_metadata_import"))
        effective = store.effective_classifications("news_x")
        assert effective[0].provenance is ClassificationProvenance.SOURCE_EXPLICIT


class TestManualOverride:
    def test_override_wins_and_history_preserved(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item("Nvidia earnings beat estimates")
        engine.enrich_item(item, now=NOW)
        target = [c for c in engine.store.classifications_for(item.news_item_id)
                  if c.dimension is ClassificationDimension.EVENT_TYPE][0]
        apply_user_override(
            engine.store, news_item_id=item.news_item_id,
            dimension=ClassificationDimension.EVENT_TYPE, value="GUIDANCE",
            replaces_classification_id=target.classification_id,
            note="実際はガイダンス記事", now=NOW)
        effective = engine.store.effective_classifications(item.news_item_id)
        event_values = {c.value for c in effective
                        if c.dimension is ClassificationDimension.EVENT_TYPE}
        assert event_values == {"GUIDANCE"}  # USERが優先・旧EARNINGSは除外
        # 履歴保持: 旧レコードは消えていない＋OVERRIDEイベントが残る
        assert engine.store.get_classification(target.classification_id) is not None
        assert any(e.action is EnrichmentAction.OVERRIDE
                   for e in engine.store.iter_events())

    def test_retract_hides_but_preserves(self, tmp_path):
        engine = make_engine(tmp_path)
        item = make_item("Apple unveils new iPhone lineup")
        engine.enrich_item(item, now=NOW)
        company = [c for c in engine.store.classifications_for(item.news_item_id)
                   if c.dimension is ClassificationDimension.COMPANY][0]
        retract_classification(engine.store, classification_id=company.classification_id,
                               note="誤link", now=NOW)
        effective = engine.store.effective_classifications(item.news_item_id)
        assert all(c.dimension is not ClassificationDimension.COMPANY for c in effective)
        assert engine.store.get_classification(company.classification_id) is not None

    def test_override_cross_item_conflict_rejected(self, tmp_path):
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_a", "ai"))
        target = list(store.iter_classifications())[0]
        with pytest.raises(ValueError, match="conflict"):
            apply_user_override(
                store, news_item_id="news_b",
                dimension=ClassificationDimension.THEME, value="ai",
                replaces_classification_id=target.classification_id, now=NOW)

    def test_revision_history_versions_coexist(self, tmp_path):
        """classifier version更新の再分類は**追記**（旧versionの分類は消えない）。"""
        store = JsonlEnrichmentStore(tmp_path / "e")
        store.add_classification(_cls("news_x", "ai", version="1.0.0"))
        store.add_classification(_cls("news_x", "ai", version="2.0.0"))
        assert len(store.classifications_for("news_x")) == 2
        assert len(store.effective_classifications("news_x")) == 1  # viewは1代表
