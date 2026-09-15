"""P2-E: LLM層（optional・provider中立・検証・reject）のテスト。"""
from __future__ import annotations

from decimal import Decimal

from src.intelligence.core.types import LLMResult
from src.intelligence.databank.news_model import ClassificationProvenance
from src.intelligence.enrichment.llm_classifier import LLMThemeEventClassifier
from src.intelligence.enrichment.model import ReviewReason

from .enrichment_fixtures import NOW, catalogs, make_engine, make_item


class StubLLM:
    """LLMProvider Protocol充足のスタブ（vendor中立の実証——SDK非依存）。"""

    def __init__(self, text: str = "", available: bool = True):
        self.text = text
        self.available = available
        self.calls = 0

    def is_available(self) -> bool:
        return self.available

    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 1024) -> LLMResult:
        self.calls += 1
        return LLMResult(text=self.text, provider="stub", model="stub-model-1")


def _classifier(stub: StubLLM) -> LLMThemeEventClassifier:
    _ec, tt, et = catalogs()
    return LLMThemeEventClassifier(stub, tt, et)


VALID = '{"themes": [{"slug": "ai", "confidence": 0.9}], "event_types": [{"type": "EARNINGS", "confidence": 0.8}]}'


class TestLLMOptionality:
    def test_unavailable_llm_skipped_and_pipeline_works(self, tmp_path):
        stub = StubLLM(available=False)
        engine = make_engine(tmp_path, llm=_classifier(stub))
        item = make_item("Nvidia earnings beat estimates as AI chip demand surges")
        outcome = engine.enrich_item(item, now=NOW)
        assert outcome.llm_used is False
        assert stub.calls == 0
        assert outcome.classifications_added > 0  # 決定論層は完走（LLMはoptional）

    def test_engine_without_llm_at_all(self, tmp_path):
        engine = make_engine(tmp_path, llm=None)
        outcome = engine.enrich_item(make_item("Nvidia earnings beat estimates"), now=NOW)
        assert outcome.classifications_added > 0


class TestLLMValidOutput:
    def test_proposals_with_provenance_and_audit(self, tmp_path):
        engine = make_engine(tmp_path, llm=_classifier(StubLLM(VALID)))
        item = make_item("Some headline without rule signals")
        engine.enrich_item(item, now=NOW)
        llm_cls = [c for c in engine.store.classifications_for(item.news_item_id)
                   if c.provenance is ClassificationProvenance.LLM]
        assert {c.value for c in llm_cls} == {"ai", "EARNINGS"}
        for c in llm_cls:
            assert c.classifier_name == "llm_classifier:stub:stub-model-1"
            assert c.confidence in (Decimal("0.9"), Decimal("0.8"))
            assert c.confidence_type == "llm_stated"
        audits = list(engine.store.iter_llm_audit())
        assert len(audits) == 1
        assert audits[0]["model"] == "stub-model-1"
        assert audits[0]["prompt_schema_version"] == "1.0.0"
        assert "raw_text" in audits[0]


class TestLLMRejection:
    def test_unknown_label_goes_to_review_not_canonical(self, tmp_path):
        text = '{"themes": [{"slug": "totally_new_theme", "confidence": 0.9}], "event_types": []}'
        engine = make_engine(tmp_path, llm=_classifier(StubLLM(text)))
        item = make_item("Plain headline")
        engine.enrich_item(item, now=NOW)
        # canonical taxonomyを汚染しない
        assert all(c.value != "totally_new_theme"
                   for c in engine.store.iter_classifications())
        queue = list(engine.store.iter_review_queue())
        assert queue[0].reason is ReviewReason.LLM_UNKNOWN_LABEL
        assert queue[0].candidate_value == "totally_new_theme"

    def test_invalid_json_rejected(self, tmp_path):
        engine = make_engine(tmp_path, llm=_classifier(StubLLM("I think this is about AI!")))
        item = make_item("Plain headline")
        outcome = engine.enrich_item(item, now=NOW)
        assert outcome.llm_rejected is True
        assert all(c.provenance is not ClassificationProvenance.LLM
                   for c in engine.store.iter_classifications())
        assert any(r.reason is ReviewReason.LLM_INVALID_OUTPUT
                   for r in engine.store.iter_review_queue())

    def test_invalid_confidence_rejected_per_label(self, tmp_path):
        text = '{"themes": [{"slug": "ai", "confidence": 1.7}], "event_types": []}'
        engine = make_engine(tmp_path, llm=_classifier(StubLLM(text)))
        item = make_item("Plain headline")
        engine.enrich_item(item, now=NOW)
        assert all(c.provenance is not ClassificationProvenance.LLM
                   for c in engine.store.iter_classifications())
        assert any(r.reason is ReviewReason.LLM_INVALID_OUTPUT
                   for r in engine.store.iter_review_queue())

    def test_json_wrapped_in_prose_still_parsed(self, tmp_path):
        text = f"Here is the result:\n{VALID}\nHope this helps!"
        engine = make_engine(tmp_path, llm=_classifier(StubLLM(text)))
        item = make_item("Plain headline")
        engine.enrich_item(item, now=NOW)
        assert any(c.provenance is ClassificationProvenance.LLM
                   for c in engine.store.classifications_for(item.news_item_id))
