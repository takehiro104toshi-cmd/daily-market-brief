"""PART J: 品質レポート＋Observation(trading_date)のserialization roundtrip。"""
from __future__ import annotations

from datetime import date

from src.intelligence.core import serialization
from src.intelligence.evidence_qa.policy import HISTORICAL_V1
from src.intelligence.market.backfill import MarketBackfillEngine
from src.intelligence.market.ingest import build_observations
from src.intelligence.market.quality_report import build_quality_report
from src.intelligence.market.store import MarketBankStore

from .market_fixtures import NIKKEI_CSV, RETRIEVED, catalog, fetch_result_from_csv, spec_for, stub_provider

NIKKEI = "index:nikkei225.close.closing.tokyo"


class TestQualityReport:
    def _report(self, tmp_path):
        engine = MarketBackfillEngine(
            MarketBankStore(tmp_path / "market"), catalog(),
            stub_provider({"s=^nkx": (200, NIKKEI_CSV)}), HISTORICAL_V1)
        engine.run(start=date(2026, 8, 1), end=date(2026, 8, 29), now=RETRIEVED,
                   series_ids=(NIKKEI,))
        return build_quality_report(engine.store, catalog())

    def test_coverage_and_decisions(self, tmp_path):
        report = self._report(tmp_path)
        nikkei = [s for s in report["series"] if s["series_id"] == NIKKEI][0]
        assert nikkei["observations"] == 5
        assert (nikkei["first"], nikkei["last"]) == ("2026-08-24", "2026-08-28")
        assert nikkei["expected_sessions"] == 5  # 月〜金
        assert nikkei["missing_sessions"] == 0
        assert nikkei["provider"] == ["stooq"]
        assert nikkei["fallback_used"] is False
        assert sum(nikkei["qa_decisions"].values()) == 5
        assert nikkei["revisions"] == 0

    def test_empty_series_reported_honestly(self, tmp_path):
        report = self._report(tmp_path)
        assert report["series_with_data"] == 1
        assert len(report["series_empty"]) == len(catalog().enabled_series()) - 1
        assert report["cross_source_comparison"] == "not_exercised_single_provider"

    def test_weekday_gap_counts_as_missing(self, tmp_path):
        # 8/26（水）を欠いたコーパス→missing_sessions=1（補完はしない・報告のみ）
        store = MarketBankStore(tmp_path / "m2")
        spec = spec_for(NIKKEI)
        body = b"Date,Close\n2026-08-24,1\n2026-08-25,2\n2026-08-27,3\n2026-08-28,4\n"
        store.add_observations(
            build_observations(spec, fetch_result_from_csv(spec, body)).observations)
        report = build_quality_report(store, catalog())
        nikkei = [s for s in report["series"] if s["series_id"] == NIKKEI][0]
        assert nikkei["missing_sessions"] == 1
        assert "祝日" in nikkei["missing_sessions_note"]
        store.close()


class TestObservationRoundtrip:
    def test_trading_date_survives_serialization(self):
        serialization.register_domain_types()
        spec = spec_for(NIKKEI)
        obs = build_observations(spec, fetch_result_from_csv(spec, NIKKEI_CSV)).observations[0]
        decoded = serialization.decode(serialization.encode(obs))
        assert decoded == obs
        assert decoded.trading_date == "2026-08-24"
        assert str(decoded.value) == "38975.55"  # Decimal精度がstr経由で保たれる

    def test_pre_p2d_record_without_trading_date_decodes(self):
        serialization.register_domain_types()
        spec = spec_for(NIKKEI)
        obs = build_observations(spec, fetch_result_from_csv(spec, NIKKEI_CSV)).observations[0]
        encoded = serialization.encode(obs)
        del encoded["trading_date"]  # 0.3.x時代のレコード相当
        decoded = serialization.decode(encoded)
        assert decoded.trading_date == ""  # 前方互換: defaultで受ける


class TestPilotTraceRendering:
    def test_render_trace_on_populated_bank(self, tmp_path):
        # live pilot 3回目の実障害（QAIssue属性名）の再発防止: trace描画をオフラインで固定
        from src.intelligence.market.pilot_runner import render_trace
        engine = MarketBackfillEngine(
            MarketBankStore(tmp_path / "market"), catalog(),
            stub_provider({"s=^nkx": (200, NIKKEI_CSV)}), HISTORICAL_V1)
        engine.run(start=date(2026, 8, 1), end=date(2026, 8, 29), now=RETRIEVED,
                   series_ids=(NIKKEI,))
        text = render_trace(engine.store, NIKKEI)
        assert "latest observation obs_" in text
        assert "decision=accept_with_warnings" in text
        assert "policy=HISTORICAL:1.0.0" in text
        assert "index row:" in text
