"""PART D/E: 正規化（Decimal・セッションモデル・欠測・改定）のテスト。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.intelligence.market.ingest import as_of_for, build_observations, observation_id_for
from src.intelligence.market.model import ObservationKind

from .market_fixtures import NIKKEI_CSV, UST10Y_CSV, fetch_result_from_csv, spec_for


class TestSessionModel:
    def test_exchange_close_tokyo_to_utc(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        as_of = as_of_for(spec, "2026-08-28")
        # 15:30 JST = 06:30 UTC（trading_dateとas_ofのUTC日付が同日でも別概念）
        assert as_of == datetime(2026, 8, 28, 6, 30, tzinfo=timezone.utc)

    def test_exchange_close_ny_crosses_utc_date(self):
        spec = spec_for("index:spx.close.closing.us")
        as_of = as_of_for(spec, "2026-08-28")
        # 16:00 ET（EDT）= 20:00 UTC。冬時間なら21:00になる（zoneinfoが吸収）
        assert as_of == datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)
        winter = as_of_for(spec, "2026-01-15")
        assert winter == datetime(2026, 1, 15, 21, 0, tzinfo=timezone.utc)

    def test_day_end_utc_policy(self):
        spec = spec_for("fx:USDJPY.rate.closing.global")
        assert as_of_for(spec, "2026-08-28") == \
            datetime(2026, 8, 28, 23, 59, 59, tzinfo=timezone.utc)

    def test_trading_date_recorded_separately(self):
        spec = spec_for("index:spx.close.closing.us")
        outcome = build_observations(spec, fetch_result_from_csv(spec, NIKKEI_CSV))
        obs = outcome.observations[-1]
        assert obs.trading_date == "2026-08-28"
        assert obs.as_of.date().isoformat() == "2026-08-28"  # ET closeはUTC同日20時


class TestDecimalDiscipline:
    def test_value_is_exact_decimal_from_token(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        outcome = build_observations(spec, fetch_result_from_csv(spec, NIKKEI_CSV))
        obs = outcome.observations[0]
        assert obs.value == Decimal("38975.55")
        assert str(obs.value) == "38975.55"  # float経由なら桁が壊れる

    def test_yield_pct_convention(self):
        spec = spec_for("rates:UST10Y.yield.closing.us")
        outcome = build_observations(spec, fetch_result_from_csv(spec, UST10Y_CSV))
        obs = outcome.observations[0]
        assert obs.value == Decimal("4.254") and obs.unit == "pct"  # 0.04254にしない


class TestMissingAndSanity:
    def test_missing_token_stays_missing(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        body = b"Date,Close\n2026-08-27,\n2026-08-28,100.5\n"
        outcome = build_observations(spec, fetch_result_from_csv(spec, body))
        missing = outcome.observations[0]
        assert missing.value is None  # 0・前日値・補間で埋めない
        assert any(i.startswith("missing_close_token") for i in outcome.issues)

    def test_invalid_token_skipped_with_issue_not_fabricated(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        body = b"Date,Close\n2026-08-27,abc\n2026-08-28,100.5\n"
        outcome = build_observations(spec, fetch_result_from_csv(spec, body))
        assert len(outcome.observations) == 1 and outcome.skipped == 1
        assert any(i.startswith("invalid_close_token") for i in outcome.issues)

    def test_weekend_detected_not_corrected(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        body = b"Date,Close\n2026-08-30,100.5\n"  # 日曜
        outcome = build_observations(spec, fetch_result_from_csv(spec, body))
        assert len(outcome.observations) == 1  # 保存はする（検知のみ）
        assert any(i.startswith("weekend_trading_date") for i in outcome.issues)

    def test_crypto_weekend_is_normal(self):
        spec = spec_for("crypto:BTCUSD.close.closing.global")
        body = b"Date,Close\n2026-08-30,65000.10\n"
        outcome = build_observations(spec, fetch_result_from_csv(spec, body))
        assert not any("weekend" in i for i in outcome.issues)

    def test_duplicate_trading_date_kept_first(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        body = b"Date,Close\n2026-08-28,100.5\n2026-08-28,101.5\n"
        outcome = build_observations(spec, fetch_result_from_csv(spec, body))
        assert len(outcome.observations) == 1
        assert any(i.startswith("duplicate_trading_date") for i in outcome.issues)


class TestIdempotencyAndRevision:
    def test_observation_id_deterministic(self):
        a = observation_id_for("s", "2026-08-28", "stooq", "close", "100.5")
        b = observation_id_for("s", "2026-08-28", "stooq", "close", "100.5")
        c = observation_id_for("s", "2026-08-28", "stooq", "close", "100.6")
        assert a == b and a != c and a.startswith("obs_")

    def test_same_value_refetch_produces_nothing(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        result = fetch_result_from_csv(spec, NIKKEI_CSV)
        first = build_observations(spec, result)
        existing = {o.trading_date: o for o in first.observations}
        second = build_observations(spec, result, existing_by_date=existing)
        assert second.observations == ()  # 完全冪等（重複appendしない）

    def test_changed_value_creates_revision_not_overwrite(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        first = build_observations(spec, fetch_result_from_csv(
            spec, b"Date,Close\n2026-08-28,100.5\n"))
        existing = {o.trading_date: o for o in first.observations}
        revised = build_observations(spec, fetch_result_from_csv(
            spec, b"Date,Close\n2026-08-28,100.7\n"), existing_by_date=existing)
        assert len(revised.observations) == 1
        new = revised.observations[0]
        old = first.observations[0]
        assert new.revision_of == old.observation_id  # 旧値は消えない
        assert new.observation_id != old.observation_id
        assert revised.new_revisions == ((old.observation_id, new.observation_id),)

    def test_provider_switch_is_never_silent(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        first = build_observations(spec, fetch_result_from_csv(
            spec, b"Date,Close\n2026-08-28,100.5\n", provider_id="stooq"))
        existing = {o.trading_date: o for o in first.observations}
        # 別providerが異なる値→revision＋source_changes記録
        other = build_observations(spec, fetch_result_from_csv(
            spec, b"Date,Close\n2026-08-28,100.9\n", provider_id="other"),
            existing_by_date=existing)
        assert other.source_changes == ("2026-08-28:stooq->other",)
        assert other.observations[0].revision_of == first.observations[0].observation_id
        # 別providerが同値→重複保存せず確認記録のみ
        same = build_observations(spec, fetch_result_from_csv(
            spec, b"Date,Close\n2026-08-28,100.5\n", provider_id="other"),
            existing_by_date=existing)
        assert same.observations == ()
        assert any(i.startswith("source_change_confirmed_equal") for i in same.issues)

    def test_observation_shape(self):
        spec = spec_for("index:nikkei225.close.closing.tokyo")
        outcome = build_observations(spec, fetch_result_from_csv(spec, NIKKEI_CSV))
        obs = outcome.observations[0]
        assert obs.kind is ObservationKind.RAW
        assert obs.series_id == spec.series_id
        assert obs.entity_id == "index:nikkei225"
        assert obs.source_id == "stooq"  # per-Observation source provenance
