"""PART G/H: backfillエンジン（manifest会計・QA・GAP・冪等）のテスト。"""
from __future__ import annotations

from datetime import date

from src.intelligence.core import serialization
from src.intelligence.evidence_qa.policy import HISTORICAL_V1
from src.intelligence.market.backfill import MarketBackfillEngine, default_range
from src.intelligence.market.store import MarketBankStore

from .market_fixtures import NIKKEI_CSV, RETRIEVED, UST10Y_CSV, catalog, stub_provider

START, END = date(2026, 8, 1), date(2026, 8, 29)

#: 成功2系列＋no_data（probe）1系列＋HTTPエラー（非probe）1系列のstub応答
RESPONSES = {
    "s=^nkx": (200, NIKKEI_CSV),
    "s=10usy.b": (200, UST10Y_CSV),
    "s=10jpy.b": (200, b"No data"),   # probe系列→GAP
    "s=^dji": (500, b"server error"),  # 非probe→FAILED
}

SERIES = (
    "index:nikkei225.close.closing.tokyo",
    "rates:UST10Y.yield.closing.us",
    "rates:JGB10Y.yield.closing.tokyo",
    "index:dji.close.closing.us",
)


def _engine(tmp_path) -> MarketBackfillEngine:
    return MarketBackfillEngine(
        MarketBankStore(tmp_path / "market"), catalog(),
        stub_provider(RESPONSES), HISTORICAL_V1)


class TestBackfillRun:
    def test_manifest_accounting(self, tmp_path):
        engine = _engine(tmp_path)
        run = engine.run(start=START, end=END, now=RETRIEVED, series_ids=SERIES)
        assert run.series_requested == 4
        assert (run.series_success, run.series_gap, run.series_failed) == (2, 1, 1)
        assert run.series_requested == run.series_success + run.series_gap + run.series_failed
        assert run.observations_added == 10  # 5+5
        assert run.trust_policy == "HISTORICAL:1.0.0"
        assert run.catalog_version == "1.2.1"
        by_id = {r.series_id: r for r in run.results}
        assert by_id["rates:JGB10Y.yield.closing.tokyo"].status == "gap"
        assert by_id["index:dji.close.closing.us"].status == "failed"
        assert by_id["index:dji.close.closing.us"].http_status == 500

    def test_qa_issued_for_every_new_observation(self, tmp_path):
        engine = _engine(tmp_path)
        run = engine.run(start=START, end=END, now=RETRIEVED, series_ids=SERIES,
                         with_derivations=False)
        assessments = list(engine.store.qa.iter_assessments())
        assert len(assessments) == run.observations_added
        assert {a.policy_name for a in assessments} == {"HISTORICAL"}
        nikkei = [r for r in run.results if "nikkei" in r.series_id][0]
        assert nikkei.qa_decisions  # "decision:count"が記録される

    def test_provenance_recorded_even_on_failure(self, tmp_path):
        engine = _engine(tmp_path)
        engine.run(start=START, end=END, now=RETRIEVED, series_ids=SERIES)
        attempts = list(engine.store.raw.iter_attempts())
        # 失敗・GAPの試行も必ず記録（P1-C原則）。JGB10Yはカタログ1.1.0でstooq経路が
        # 外れた（mof_japan専用）ため、stooqのみのstubではno_provider GAP＝fetch自体なし
        assert len(attempts) == 3
        raw_items = list(engine.store.raw.iter_raw_items())
        assert len(raw_items) == 2  # 成功応答のみRawItem化（生CSV保存）

    def test_idempotent_rerun_adds_nothing(self, tmp_path):
        engine = _engine(tmp_path)
        first = engine.run(start=START, end=END, now=RETRIEVED, series_ids=SERIES)
        qa_before = len(list(engine.store.qa.iter_assessments()))
        second = engine.run(start=START, end=END, now=RETRIEVED, series_ids=SERIES)
        assert second.observations_added == 0
        assert second.derived_added == 0
        assert len(list(engine.store.qa.iter_assessments())) == qa_before
        # canonical件数も不変
        total = sum(1 for _ in engine.store.normalized.iter_observations())
        assert total == first.observations_added + first.derived_added

    def test_run_manifest_persisted_roundtrip(self, tmp_path):
        engine = _engine(tmp_path)
        run = engine.run(start=START, end=END, now=RETRIEVED, series_ids=SERIES)
        stored = list(engine.store.iter_runs())
        assert len(stored) == 1
        assert serialization.encode(stored[0]) == serialization.encode(run)

    def test_derivations_added_with_dependency_qa(self, tmp_path):
        engine = _engine(tmp_path)
        run = engine.run(start=START, end=END, now=RETRIEVED, series_ids=SERIES)
        assert run.derived_added > 0
        derived = [o for o in engine.store.normalized.iter_observations()
                   if o.kind.value == "derived"]
        assert all(o.inputs and o.calculation_method for o in derived)
        # 派生にもQAが発行されている
        derived_ids = {o.observation_id for o in derived}
        assessed = {a.record_id for a in engine.store.qa.iter_assessments()}
        assert derived_ids <= assessed


class TestDefaultRange:
    def test_covers_over_one_year_without_bulk(self):
        start, end = default_range(days=400, today=date(2026, 8, 30))
        assert (end - start).days == 400
        assert start == date(2025, 7, 26)


class TestProviderFallback:
    """PART C: provider fallback——発動は必ず記録される（silent switch禁止）。"""

    def _providers(self, yf_rows=None, yf_error=False):
        from src.intelligence.market.providers import YfinanceDailyHistoryProvider

        def history(symbol, start, end):
            if yf_error:
                raise RuntimeError("yahoo down")
            return yf_rows or []

        return {
            "yfinance": YfinanceDailyHistoryProvider(history_fn=history),
            "stooq": stub_provider({"s=^nkx": (200, NIKKEI_CSV)}),
        }

    NIKKEI = "index:nikkei225.close.closing.tokyo"

    def test_preferred_success_never_calls_fallback(self, tmp_path):
        engine = MarketBackfillEngine(
            MarketBankStore(tmp_path / "m"), catalog(),
            self._providers(yf_rows=[("2026-08-28", 39310.25, None)]), HISTORICAL_V1)
        run = engine.run(start=START, end=END, now=RETRIEVED, series_ids=(self.NIKKEI,),
                         with_derivations=False)
        r = run.results[0]
        assert (r.status, r.provider_id, r.fallback_used) == ("success", "yfinance", False)
        assert r.fallback_errors == ()

    def test_fallback_engages_and_is_recorded(self, tmp_path):
        engine = MarketBackfillEngine(
            MarketBankStore(tmp_path / "m"), catalog(),
            self._providers(yf_error=True), HISTORICAL_V1)
        run = engine.run(start=START, end=END, now=RETRIEVED, series_ids=(self.NIKKEI,),
                         with_derivations=False)
        r = run.results[0]
        assert (r.status, r.provider_id) == ("success", "stooq")
        assert r.fallback_used is True  # 黙って切り替わらない——runへ明記
        assert r.fallback_errors == ("yfinance:connection",)
        # per-Observation provenance: 実際に取得したproviderが刻まれる
        obs = list(engine.store.normalized.iter_observations())
        assert {o.source_id for o in obs} == {"stooq"}
        # 失敗した試行もFetchAttemptとして残る（2 attempts）
        assert len(list(engine.store.raw.iter_attempts())) == 2

    def test_all_fail_reports_chain(self, tmp_path):
        providers = {
            "yfinance": self._providers(yf_error=True)["yfinance"],
            "stooq": stub_provider({}),  # dnsエラー
        }
        engine = MarketBackfillEngine(
            MarketBankStore(tmp_path / "m"), catalog(), providers, HISTORICAL_V1)
        run = engine.run(start=START, end=END, now=RETRIEVED, series_ids=(self.NIKKEI,),
                         with_derivations=False)
        r = run.results[0]
        assert r.status == "failed"
        # chain全試行が記録される（最後の失敗はerror_kind/error_detailにも出る）
        assert r.fallback_errors == ("yfinance:connection", "stooq:dns")
        assert r.error_kind == "dns"
