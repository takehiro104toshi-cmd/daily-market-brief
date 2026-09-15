"""Phase 1-A domain modelの不変条件テスト（schema validation）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.intelligence.core.ids import content_id, new_id, new_ulid
from src.intelligence.core.time import ensure_aware
from src.intelligence.core.types import Direction, Horizon, SourceTier, VerificationState
from src.intelligence.evidence import invariants
from src.intelligence.evidence.model import (
    AnalysisStatement,
    EvidenceLink,
    EvidenceRelation,
    FactStatement,
    ForecastMetadata,
    ForecastStatement,
)
from src.intelligence.market.model import Observation, ObservationKind, latest_revisions
from src.intelligence.sources.model import SourceDocument
from src.intelligence.sources.model import latest_revisions as latest_doc_revisions

from . import evidence_fixtures as fx

UTC_NOW = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
NAIVE = datetime(2026, 8, 28, 0, 0)


class TestTimeModel:
    def test_naive_datetime_rejected_everywhere(self) -> None:
        with pytest.raises(ValueError):
            ensure_aware(NAIVE, "x")
        with pytest.raises(ValueError):
            FactStatement(statement_id="fact_x", text="t", created_at=NAIVE)
        with pytest.raises(ValueError):
            Observation(observation_id="obs_x", entity_id="e", metric="m",
                        value=None, unit="pct", as_of=NAIVE, source_id="s")
        with pytest.raises(ValueError):
            SourceDocument(source_document_id="doc_x", source_id="s",
                           source_tier=SourceTier.TIER1, title="t", locator="l",
                           retrieved_at=NAIVE, content_hash="h")

    def test_event_published_retrieved_are_distinct_fields(self) -> None:
        doc, fact, _ = fx.boj_statement()
        assert doc.published_at is not None and doc.retrieved_at is not None
        assert doc.published_at != doc.retrieved_at
        assert fact.event_time == doc.published_at
        # タイムゾーンはJST固定でなくaware任意（USフィクスチャはEST）
        fed_doc, _, _ = fx.fed_statement()
        assert fed_doc.published_at.utcoffset() == timedelta(hours=-5)


class TestIdStrategy:
    def test_ulid_is_sortable_by_time(self) -> None:
        earlier = new_ulid(UTC_NOW)
        later = new_ulid(UTC_NOW + timedelta(seconds=2))
        assert earlier < later
        assert len(earlier) == 26

    def test_content_id_is_deterministic(self) -> None:
        a = content_id("doc", "src", "loc", "hash")
        b = content_id("doc", "src", "loc", "hash")
        c = content_id("doc", "src", "loc", "hash2")
        assert a == b and a != c and a.startswith("doc_")

    def test_prefixes(self) -> None:
        assert new_id("fact", UTC_NOW).startswith("fact_")


class TestFactModel:
    def test_unsupported_ai_claim_detected(self) -> None:
        claim = fx.unsupported_ai_claim()
        result = invariants.unsupported_facts([claim], [])
        assert result == (claim,)
        assert invariants.derive_verification(claim, ()) is VerificationState.UNSUPPORTED

    def test_supported_fact_is_verified(self) -> None:
        _, fact, link = fx.boj_statement()
        assert invariants.derive_verification(fact, (link,)) is VerificationState.VERIFIED
        assert invariants.unsupported_facts([fact], [link]) == ()

    def test_reported_attribution_preserved(self) -> None:
        _, fact, _ = fx.secondary_article()
        assert fact.attribution.value == "reported"


class TestAnalysisModel:
    def test_requires_inputs_rule_agent(self) -> None:
        base = dict(statement_id="ana_x", text="t", created_at=UTC_NOW)
        with pytest.raises(ValueError):
            AnalysisStatement(**base, inputs=(), rule_id="R", agent="a")
        with pytest.raises(ValueError):
            AnalysisStatement(**base, inputs=("fact_1",), rule_id="", agent="a")
        with pytest.raises(ValueError):
            AnalysisStatement(**base, inputs=("fact_1",), rule_id="R", agent="")

    def test_causal_chain_traces_to_root_fact(self) -> None:
        _, fed_fact, _, analysis, forecast, _, _ = fx.causal_chain()
        graph = {
            analysis.statement_id: analysis.inputs,
            forecast.statement_id: tuple(forecast.forecast.supporting_evidence),
        }
        trail = invariants.trace_analysis(graph, forecast.statement_id)
        assert fed_fact.statement_id in trail  # 予測→分析→根のFACTまで遡れる
        assert analysis.rule_id == "JP_US_001"
        assert analysis.agent == "rule_engine"


class TestForecastModel:
    def test_metadata_required(self) -> None:
        with pytest.raises(ValueError):
            ForecastStatement(statement_id="fcst_x", text="t", created_at=UTC_NOW)

    def test_invalidation_and_supporting_required(self) -> None:
        base = dict(target="index:nikkei225", direction=Direction.UP,
                    horizon=Horizon.ONE_DAY, confidence=4, generated_at=UTC_NOW,
                    predictor="rule_engine")
        with pytest.raises(ValueError):
            ForecastMetadata(**base, supporting_evidence=(),
                             invalidation_conditions=("x",))
        with pytest.raises(ValueError):
            ForecastMetadata(**base, supporting_evidence=("fact_1",),
                             invalidation_conditions=())

    @pytest.mark.parametrize("bad", [-1, 6])
    def test_confidence_bounds(self, bad: int) -> None:
        with pytest.raises(ValueError):
            ForecastMetadata(target="t", direction=Direction.FLAT, horizon=Horizon.LONG,
                             confidence=bad, generated_at=UTC_NOW, predictor="p",
                             supporting_evidence=("e",), invalidation_conditions=("i",))

    def test_range_targets_are_decimal(self) -> None:
        with pytest.raises(TypeError):
            ForecastMetadata(target="fx:usdjpy", direction=Direction.RANGE,
                             horizon=Horizon.ONE_WEEK, confidence=4,
                             generated_at=UTC_NOW, predictor="p",
                             supporting_evidence=("e",), invalidation_conditions=("i",),
                             target_low=159.0, target_high=Decimal("162"))  # type: ignore[arg-type]


class TestObservationModel:
    def test_float_rejected(self) -> None:
        with pytest.raises(TypeError):
            Observation(observation_id="obs_x", entity_id="e", metric="close",
                        value=69902.25, unit="index", as_of=UTC_NOW, source_id="s")  # type: ignore[arg-type]

    def test_missing_value_is_none(self) -> None:
        obs = Observation(observation_id="obs_x", entity_id="e", metric="close",
                          value=None, unit="index", as_of=UTC_NOW, source_id="s")
        assert obs.value is None  # 欠測は捏造しない

    def test_derived_requires_inputs_and_method(self) -> None:
        base = fx.jp_stock_observation()
        derived = fx.derived_observation(base)
        assert derived.kind is ObservationKind.DERIVED
        assert derived.inputs == (base.observation_id,)
        with pytest.raises(ValueError):
            Observation(observation_id="obs_y", entity_id="e", metric="dev",
                        value=Decimal("1"), unit="pct", as_of=UTC_NOW,
                        kind=ObservationKind.DERIVED, calculation_method="dev",
                        inputs=())

    def test_decimal_precision_kept(self) -> None:
        assert str(fx.us_stock_observation().value) == "201.34"


class TestConflictAndRevision:
    def test_conflicting_sources_both_kept(self) -> None:
        doc_a, doc_b, fact, links = fx.conflicting_sources()
        state = invariants.derive_verification(fact, links)
        assert state is VerificationState.CONFLICTING
        assert len(links) == 2  # どちらのEvidenceも削除しない
        assert invariants.conflicting_statements([fact], links) == (fact,)

    def test_observation_revision_keeps_history(self) -> None:
        _, first, revised = fx.cpi_release_with_revision()
        assert revised.revision_of == first.observation_id
        latest = latest_revisions((first, revised))
        assert latest == (revised,)  # 最新のみ抽出できるが、firstは削除されない
        assert str(first.value) == "4.1" and str(revised.value) == "4.2"

    def test_document_revision(self) -> None:
        doc, _, _ = fx.boj_statement()
        corrected = SourceDocument(
            source_document_id=SourceDocument.make_id(doc.source_id, doc.locator, "h2"),
            source_id=doc.source_id, source_tier=doc.source_tier,
            title=doc.title + "（訂正）", locator=doc.locator,
            retrieved_at=doc.retrieved_at, content_hash="h2",
            revision_of=doc.source_document_id,
        )
        assert latest_doc_revisions((doc, corrected)) == (corrected,)


class TestEvidenceLink:
    def test_many_to_many(self) -> None:
        """1文書→複数Fact / 1Fact→複数文書の両方が表現できる。"""
        doc, fact1, link1 = fx.boj_statement()
        fact2 = FactStatement(statement_id="fact_second", text="声明は政策の現状維持も示した",
                              created_at=fx.NOW)
        link2 = EvidenceLink(link_id="link_2", claim_id=fact2.statement_id,
                             evidence_id=doc.source_document_id,
                             relation=EvidenceRelation.SUPPORTS, created_at=fx.NOW)
        doc_b, _, _ = fx.secondary_article()
        link3 = EvidenceLink(link_id="link_3", claim_id=fact1.statement_id,
                             evidence_id=doc_b.source_document_id,
                             relation=EvidenceRelation.SUPPORTS, created_at=fx.NOW)
        by_claim = invariants.links_by_claim([link1, link2, link3])
        assert len(by_claim[fact1.statement_id]) == 2
        assert len(by_claim[fact2.statement_id]) == 1

    def test_self_evidence_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvidenceLink(link_id="l", claim_id="x", evidence_id="x",
                         relation=EvidenceRelation.SUPPORTS, created_at=UTC_NOW)


class TestTierIndependence:
    def test_tier_is_not_verification(self) -> None:
        """Tier1文書に支えられていても、リンクが無ければFACTはUNSUPPORTED。"""
        claim = fx.unsupported_ai_claim()
        assert invariants.derive_verification(claim, ()) is VerificationState.UNSUPPORTED
        # tierはSourceDocument側の属性であり、statementのverificationとは別軸
        doc, fact, link = fx.boj_statement()
        assert doc.source_tier is SourceTier.TIER1
        assert fact.verification is VerificationState.UNVERIFIED  # 保存値
        assert invariants.derive_verification(fact, (link,)) is VerificationState.VERIFIED
