"""PART F: 派生系列基盤（provenance必須・Decimal・欠測非補間）のテスト。"""
from __future__ import annotations

from decimal import Decimal

from src.intelligence.market.derived import derive_cross_series, derive_per_series
from src.intelligence.market.ingest import build_observations
from src.intelligence.market.model import ObservationKind

from .market_fixtures import NIKKEI_CSV, UST10Y_CSV, catalog, fetch_result_from_csv, spec_for


def _raw(series_id: str, body: bytes):
    spec = spec_for(series_id)
    return spec, build_observations(spec, fetch_result_from_csv(spec, body)).observations


def _csv(pairs) -> bytes:
    return ("Date,Close\n" + "".join(f"{d},{v}\n" for d, v in pairs)).encode()


NIKKEI = "index:nikkei225.close.closing.tokyo"
TOPIX = "index:topix.close.closing.tokyo"
UST10 = "rates:UST10Y.yield.closing.us"
UST2 = "rates:UST2Y.yield.closing.us"


class TestPerSeriesDerivations:
    def test_return_1d_exact_decimal(self):
        spec, raw = _raw(NIKKEI, NIKKEI_CSV)
        derived = derive_per_series(spec, catalog().per_series_derivations, raw)
        r1 = [o for o in derived if o.metric == "return_1d"]
        assert len(r1) == 4  # 5観測→4ペア
        assert r1[0].value == Decimal("0.191274")
        assert r1[-1].value == Decimal("0.153503")
        assert r1[0].unit == "pct"

    def test_provenance_mandatory_and_versioned(self):
        spec, raw = _raw(NIKKEI, NIKKEI_CSV)
        derived = derive_per_series(spec, catalog().per_series_derivations, raw)
        r1 = [o for o in derived if o.metric == "return_1d"][0]
        assert r1.kind is ObservationKind.DERIVED
        assert r1.calculation_method == "return_1d:1.0.0"
        assert r1.inputs == (raw[0].observation_id, raw[1].observation_id)
        assert r1.series_id == "index:nikkei225.return_1d.derived_metric.tokyo"

    def test_ma25_window_and_inputs(self):
        pairs = [(f"2026-07-{d:02d}" if d <= 31 else f"2026-08-{d-31:02d}", str(v))
                 for d, v in zip(range(1, 27), range(1, 27))]
        spec = spec_for(NIKKEI)
        raw = build_observations(spec, fetch_result_from_csv(spec, _csv(pairs))).observations
        derived = derive_per_series(spec, catalog().per_series_derivations, raw)
        ma = [o for o in derived if o.metric == "ma25"]
        assert len(ma) == 2  # 26観測→window 2つ
        assert ma[0].value == Decimal("13.000000")  # mean(1..25)
        assert ma[1].value == Decimal("14.000000")  # mean(2..26)
        assert len(ma[0].inputs) == 25
        dist = [o for o in derived if o.metric == "dist_25dma"]
        assert dist[0].value == Decimal("92.307692")  # (25-13)/13*100
        assert len(dist[0].inputs) == 2  # (close, ma25)——ma経由で25入力へ遡れる

    def test_insufficient_data_produces_nothing(self):
        spec, raw = _raw(NIKKEI, NIKKEI_CSV)  # 5観測のみ
        derived = derive_per_series(spec, catalog().per_series_derivations, raw)
        assert [o for o in derived if o.metric == "ma25"] == []
        assert [o for o in derived if o.metric == "return_5d"] == []  # 6観測必要

    def test_missing_values_not_interpolated(self):
        spec = spec_for(NIKKEI)
        body = b"Date,Close\n2026-08-25,100\n2026-08-26,\n2026-08-28,110\n"
        raw = build_observations(spec, fetch_result_from_csv(spec, body)).observations
        derived = derive_per_series(spec, catalog().per_series_derivations, raw)
        r1 = [o for o in derived if o.metric == "return_1d"]
        # 欠測日を補間せず、値のある観測セッション同士（25日→28日）で1本のみ
        assert len(r1) == 1
        assert r1[0].inputs[0] == raw[0].observation_id
        assert r1[0].trading_date == "2026-08-28"
        assert r1[0].value == Decimal("10.000000")

    def test_deterministic_ids(self):
        spec, raw = _raw(NIKKEI, NIKKEI_CSV)
        a = derive_per_series(spec, catalog().per_series_derivations, raw)
        b = derive_per_series(spec, catalog().per_series_derivations, raw)
        assert [o.observation_id for o in a] == [o.observation_id for o in b]


class TestCrossSeriesDerivations:
    def test_yield_spread(self):
        _, ust10 = _raw(UST10, UST10Y_CSV)
        ust2_csv = _csv([("2026-08-24", "3.601"), ("2026-08-25", "3.610"),
                         ("2026-08-26", "3.620"), ("2026-08-27", "3.615"),
                         ("2026-08-28", "3.618")])
        _, ust2 = _raw(UST2, ust2_csv)
        cross = [c for c in catalog().cross_series_derivations
                 if c.series_id.startswith("rates:")][0]
        spread = derive_cross_series(cross, ust10, ust2)
        assert len(spread) == 5
        assert spread[0].value == Decimal("0.653000")
        assert spread[0].unit == "pct_point"
        assert spread[0].series_id == "rates:UST10Y_UST2Y.spread.derived_metric"
        assert len(spread[0].inputs) == 2

    def test_nt_ratio_and_date_alignment(self):
        _, nikkei = _raw(NIKKEI, NIKKEI_CSV)
        topix_csv = _csv([("2026-08-25", "2765.55"), ("2026-08-26", "2772.30"),
                          ("2026-08-27", "2775.00"), ("2026-08-28", "2779.45")])
        _, topix = _raw(TOPIX, topix_csv)
        cross = [c for c in catalog().cross_series_derivations
                 if "nt_ratio" in c.series_id][0]
        nt = derive_cross_series(cross, nikkei, topix)
        # 8/24はTOPIX側に無い→出力しない（持ち越し・補間をしない）
        assert [o.trading_date for o in nt] == \
            ["2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
        assert nt[-1].value == Decimal("14.143176")
        assert nt[-1].unit == "x"
