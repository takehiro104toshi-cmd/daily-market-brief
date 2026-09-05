"""P2-F: MIGRATED_PROVENANCE＋market observation QA意味論v2のテスト。"""
from __future__ import annotations

from datetime import date, timedelta

from src.intelligence.core.types import SourceTier
from src.intelligence.evidence_qa.assess import (
    ProviderTrace,
    assess_observation,
    assess_source_document,
)
from src.intelligence.evidence_qa.model import GateDecision, SourceInfo
from src.intelligence.evidence_qa.policy import (
    HISTORICAL_V1,
    HISTORICAL_V1_1,
    MARKET_OBSERVATION_V1,
    get_policy,
)
from src.intelligence.evidence_qa.store import JsonlAssessmentStore
from src.intelligence.market.ingest import build_observations
from src.intelligence.sources.model import SourceDocument

from .enrichment_fixtures import NOW
from .market_fixtures import NIKKEI_CSV, fetch_result_from_csv, spec_for

INFO = SourceInfo(source_id="test_source", tier=SourceTier.TIER2)


def _migrated_doc() -> SourceDocument:
    return SourceDocument(
        source_document_id="doc_migrated000000000000", source_id="bbc_business",
        source_tier=SourceTier.TIER2, title="Historical article",
        locator="https://bbc.co.uk/news/1", retrieved_at=NOW,
        published_at=NOW - timedelta(days=400),
        content_hash="h" * 64, raw_item_id="",  # 原文非保存（移行由来）
        content_fingerprint="f" * 24,
        normalizer_name="tank_article", normalizer_version="1.0.0")


class TestMigratedProvenance:
    def test_v1_0_warns_missing_raw_item(self):
        a = assess_source_document(_migrated_doc(), source_info=INFO,
                                   policy=HISTORICAL_V1, reference_time=NOW)
        assert any(i.code == "missing_raw_item" for i in a.issues)
        assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS

    def test_v1_1_with_trace_passes_as_migrated(self):
        a = assess_source_document(_migrated_doc(), source_info=INFO,
                                   policy=HISTORICAL_V1_1, reference_time=NOW,
                                   migrated_trace=True)
        assert not any(i.code == "missing_raw_item" for i in a.issues)
        assert a.decision is GateDecision.ACCEPT  # provenance PASSへ（他gateは維持）
        # MIGRATED ≠ LIVE FETCH: 区別はreason codeとして残る
        prov = [d for d in a.dimensions if d.dimension.value == "provenance"][0]
        assert prov.reason_codes == ("migrated_provenance",)

    def test_without_trace_still_warns(self):
        # 単純にwarningを消すのは禁止——trace無しの原文欠落は従来どおりWARN
        a = assess_source_document(_migrated_doc(), source_info=INFO,
                                   policy=HISTORICAL_V1_1, reference_time=NOW,
                                   migrated_trace=False)
        assert any(i.code == "missing_raw_item" for i in a.issues)

    def test_old_assessments_preserved_on_reassessment(self, tmp_path):
        store = JsonlAssessmentStore(tmp_path / "qa")
        doc = _migrated_doc()
        old = assess_source_document(doc, source_info=INFO, policy=HISTORICAL_V1,
                                     reference_time=NOW)
        store.add_assessment(old)
        new = assess_source_document(doc, source_info=INFO, policy=HISTORICAL_V1_1,
                                     reference_time=NOW, migrated_trace=True)
        store.add_assessment(new)
        history = store.assessments_for(doc.source_document_id)
        assert len(history) == 2  # NO RETROACTIVE DELETE——新旧比較可能
        assert {a.policy_version for a in history} == {"1.0.0", "1.1.0"}

    def test_policy_registry_has_v1_1(self):
        assert get_policy("HISTORICAL", "1.1.0") is HISTORICAL_V1_1


class TestMarketObservationSemantics:
    def _obs(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        return build_observations(spec, fetch_result_from_csv(spec, NIKKEI_CSV)).observations[0]

    def test_v1_historical_warns_missing_support_link(self):
        a = assess_observation(self._obs(), source_info=INFO, policy=HISTORICAL_V1,
                               reference_time=NOW)
        assert any(i.code == "missing_supporting_evidence_ref" for i in a.issues)

    def test_market_policy_with_provider_trace_passes(self):
        trace = ProviderTrace(provider_id="stooq", fetch_attempt_id="fetch_X",
                              raw_payload_ref="raw_Y")
        a = assess_observation(self._obs(), source_info=INFO,
                               policy=MARKET_OBSERVATION_V1,
                               reference_time=NOW, provider_trace=trace)
        # Fact型SUPPORTS linkを必須にしない——provider経路で評価
        assert not any(i.code == "missing_supporting_evidence_ref" for i in a.issues)
        assert a.decision is GateDecision.ACCEPT
        prov = [d for d in a.dimensions if d.dimension.value == "provenance"][0]
        assert prov.reason_codes == ("provider_provenance_verified",)

    def test_provenance_gap_still_not_tolerated(self):
        # provider経路でもtrace欠落はWARN（provenance欠落は許容しない）
        a = assess_observation(self._obs(), source_info=INFO,
                               policy=MARKET_OBSERVATION_V1,
                               reference_time=NOW, provider_trace=None)
        assert any(i.code == "missing_provider_trace" for i in a.issues)
        assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS

    def test_import_provenance_counts_as_trace(self):
        trace = ProviderTrace(provider_id="stooq",
                              import_provenance="dataset_fp:7578425805b32592")
        assert trace.verified
        a = assess_observation(self._obs(), source_info=INFO,
                               policy=MARKET_OBSERVATION_V1,
                               reference_time=NOW, provider_trace=trace)
        assert a.decision is GateDecision.ACCEPT

    def test_no_fake_fetch_provenance(self):
        # 空のtraceはverifiedにならない（fake provenance禁止の型化）
        assert not ProviderTrace(provider_id="stooq").verified
        assert not ProviderTrace(provider_id="").verified


class TestEngineProviderTraceWiring:
    def test_market_backfill_with_observation_policy_accepts(self, tmp_path):
        """engineがProviderTraceを渡す→MARKET_OBSERVATION policyで全件ACCEPT。"""
        from datetime import date as date_type
        from src.intelligence.market.backfill import MarketBackfillEngine
        from src.intelligence.market.store import MarketBankStore
        from .market_fixtures import RETRIEVED, catalog, stub_provider
        engine = MarketBackfillEngine(
            MarketBankStore(tmp_path / "market"), catalog(),
            stub_provider({"s=^nkx": (200, NIKKEI_CSV)}), MARKET_OBSERVATION_V1)
        run = engine.run(start=date_type(2026, 8, 1), end=date_type(2026, 8, 29),
                         now=RETRIEVED,
                         series_ids=("index:nikkei225.close.closing.tokyo",),
                         with_derivations=False)
        nikkei = run.results[0]
        assert nikkei.qa_decisions == ("accept:5",)  # SUPPORTS link非必須・trace検証済み
        assessments = list(engine.store.qa.iter_assessments())
        assert all(not any(i.code == "missing_supporting_evidence_ref" for i in a.issues)
                   for a in assessments)

    def test_historical_policy_behavior_unchanged_with_trace(self, tmp_path):
        """従来policyではtraceは無視される（挙動不変——後方互換）。"""
        from datetime import date as date_type
        from src.intelligence.market.backfill import MarketBackfillEngine
        from src.intelligence.market.store import MarketBankStore
        from .market_fixtures import RETRIEVED, catalog, stub_provider
        engine = MarketBackfillEngine(
            MarketBankStore(tmp_path / "market"), catalog(),
            stub_provider({"s=^nkx": (200, NIKKEI_CSV)}), HISTORICAL_V1)
        run = engine.run(start=date_type(2026, 8, 1), end=date_type(2026, 8, 29),
                         now=RETRIEVED,
                         series_ids=("index:nikkei225.close.closing.tokyo",),
                         with_derivations=False)
        assert run.results[0].qa_decisions == ("accept_with_warnings:5",)
