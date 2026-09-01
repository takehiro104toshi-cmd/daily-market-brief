"""Phase 3-A Evidence-Grounded Fact Layer のオフラインテスト（ネットワーク不使用）。

監督者指定の最低テスト項目を網羅する:
deterministic fact ID / fact revision / provenance trace / raw→fact traceability /
derived input IDs / Decimal handling / unit / trading session semantics /
as_of semantics / morning availability / look-ahead prevention /
same-date NT ratio / moving average insufficient-history rejection /
source conflict / QA rejected evidence exclusion / canonical append-only /
SQLite rebuild / idempotency / incremental generation / query。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.facts import calculations as calc
from src.intelligence.facts.availability import (
    available_at,
    is_known_by,
    leaked_facts,
    morning_cutoff,
    morning_snapshot,
)
from src.intelligence.facts.conflict import assess_conflicts, conflicted
from src.intelligence.facts.market_builder import (
    DISTANCE_FROM_MA25,
    INDEX_CHANGE,
    INDEX_CHANGE_PCT,
    INDEX_CLOSE,
    MOVING_AVERAGE_25,
    NT_RATIO,
    RETURN_5D,
    RETURN_20D,
    SessionPoint,
    YIELD_LEVEL,
    build_cross_series_fact,
    build_series_facts,
)
from src.intelligence.facts.model import (
    ConflictState,
    DateRole,
    EvidenceKind,
    Fact,
    FactCalculation,
    FactEvidenceRef,
    FactStatus,
    FactSubject,
    FactTimeContext,
    FactValue,
    make_fact_id,
    value_token,
)
from src.intelligence.facts.store import FactStore

TOPIX = "index:topix.close.closing.tokyo"
NIKKEI = "index:nikkei225.close.closing.tokyo"
JGB10Y = "rates:JGB10Y.yield.closing.tokyo"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def sessions(count: int, *, end=datetime(2026, 9, 1).date()):
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(d.isoformat() for d in days)


def point(date_str, value, *, prefix="tp", qa="accept", unit="index", source="jquants"):
    return SessionPoint(
        trading_date=date_str,
        value=Decimal(str(value)) if value is not None else None,
        observation_id=f"obs_{prefix}_{date_str}",
        as_of=datetime.fromisoformat(f"{date_str}T06:30:00+00:00"),
        source_id=source, qa_decision=qa, unit=unit)


def series_points(values, *, prefix="tp", qa="accept", unit="index"):
    days = sessions(len(values))
    return [point(d, v, prefix=prefix, qa=qa, unit=unit)
            for d, v in zip(days, values)]


# ============================================================ id / revision

class TestDeterministicId:
    def test_same_ground_truth_gives_same_id(self):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)
        a = make_fact_id(fact_type=INDEX_CLOSE, subject=subject,
                         primary_date="2026-09-01",
                         value_token=value_token(Decimal("4181.86")))
        b = make_fact_id(fact_type=INDEX_CLOSE, subject=subject,
                         primary_date="2026-09-01",
                         value_token=value_token(Decimal("4181.86")))
        assert a == b and a.startswith("fact_")

    def test_decimal_scale_is_normalized(self):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)
        a = make_fact_id(fact_type=INDEX_CLOSE, subject=subject,
                         primary_date="2026-09-01",
                         value_token=value_token(Decimal("4181.86")))
        b = make_fact_id(fact_type=INDEX_CLOSE, subject=subject,
                         primary_date="2026-09-01",
                         value_token=value_token(Decimal("4181.860")))
        assert a == b

    def test_different_value_gives_different_id(self):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)
        a = make_fact_id(fact_type=INDEX_CLOSE, subject=subject,
                         primary_date="2026-09-01",
                         value_token=value_token(Decimal("4181.86")))
        b = make_fact_id(fact_type=INDEX_CLOSE, subject=subject,
                         primary_date="2026-09-01",
                         value_token=value_token(Decimal("4200.00")))
        assert a != b

    def test_id_does_not_depend_on_processing_time(self):
        """created_atが違ってもIDは変わらない（処理時刻でIDが揺れない）。"""
        pts = series_points([100, 101])
        first = build_series_facts(TOPIX, pts, now=NOW)
        later = build_series_facts(TOPIX, pts, now=NOW + timedelta(days=3))
        assert [f.fact_id for f in first] == [f.fact_id for f in later]

    def test_calculation_method_participates_in_id(self):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)
        a = make_fact_id(fact_type=RETURN_5D, subject=subject,
                         primary_date="2026-09-01", value_token="1.5",
                         calculation_method="return_pct:1.0.0")
        b = make_fact_id(fact_type=RETURN_5D, subject=subject,
                         primary_date="2026-09-01", value_token="1.5",
                         calculation_method="return_pct:2.0.0")
        assert a != b


# ============================================================ model invariants

class TestFactInvariants:
    def _fact(self, **kwargs):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)
        base = dict(
            fact_id="fact_x", fact_type=INDEX_CLOSE, subject=subject,
            value=FactValue(value=Decimal("1"), unit="index"),
            time=FactTimeContext(primary_date="2026-09-01",
                                 date_role=DateRole.TRADING_DATE),
            evidence=(FactEvidenceRef(kind=EvidenceKind.OBSERVATION, ref_id="obs_1"),))
        base.update(kwargs)
        return Fact(**base)

    def test_usable_fact_requires_evidence(self):
        with pytest.raises(ValueError, match="evidence"):
            self._fact(evidence=())

    def test_usable_fact_requires_value(self):
        with pytest.raises(ValueError, match="value"):
            self._fact(value=FactValue(unit="index"))

    def test_float_value_is_rejected(self):
        with pytest.raises(TypeError):
            FactValue(value=1.23, unit="index")

    def test_unusable_fact_may_omit_evidence(self):
        fact = self._fact(status=FactStatus.UNUSABLE, evidence=(),
                          value=FactValue(unit="index"))
        assert fact.status is FactStatus.UNUSABLE

    def test_naive_datetime_rejected(self):
        with pytest.raises(Exception):
            FactTimeContext(primary_date="2026-09-01",
                            date_role=DateRole.TRADING_DATE,
                            known_at=datetime(2026, 9, 1))


# ============================================================ calculations

class TestCalculations:
    def test_moving_average_rejects_insufficient_history(self):
        values = [Decimal(i) for i in range(24)]
        assert calc.moving_average(values, 25) is None      # 不足なら作らない

    def test_moving_average_rejects_gap_in_window(self):
        values = [Decimal(1)] * 24 + [None]
        assert calc.moving_average(values, 25) is None      # 部分平均で誤魔化さない

    def test_moving_average_exact_window(self):
        values = [Decimal(10)] * 25
        assert calc.moving_average(values, 25) == Decimal("10.000000")

    def test_return_pct_zero_base_is_none(self):
        assert calc.return_pct(Decimal(1), Decimal(0)) is None

    def test_missing_input_returns_none_not_zero(self):
        assert calc.change_abs(Decimal(1), None) is None
        assert calc.return_pct(None, Decimal(1)) is None
        assert calc.nt_ratio(Decimal(1), None) is None
        assert calc.yield_spread(None, Decimal(1)) is None

    def test_nt_ratio_zero_denominator(self):
        assert calc.nt_ratio(Decimal(39000), Decimal(0)) is None

    def test_registry_versions_present(self):
        assert calc.REGISTRY["return_pct"] == "1.0.0"
        assert calc.REGISTRY["moving_average"] == "1.0.0"


# ============================================================ market builder

class TestMarketFactBuilder:
    def test_level_and_change_facts(self):
        facts = build_series_facts(TOPIX, series_points([100, 110]), now=NOW)
        types = {f.fact_type: f for f in facts}
        assert types[INDEX_CLOSE].value.value == Decimal("110")
        assert types[INDEX_CHANGE].value.value == Decimal("10.000000")
        assert types[INDEX_CHANGE_PCT].value.value == Decimal("10.000000")
        assert types[INDEX_CHANGE_PCT].value.unit == "pct"

    def test_single_session_has_no_change_fact(self):
        facts = build_series_facts(TOPIX, series_points([100]), now=NOW)
        assert {f.fact_type for f in facts} == {INDEX_CLOSE}

    def test_n_session_returns_use_sessions_not_calendar_days(self):
        facts = build_series_facts(TOPIX, series_points(list(range(100, 121))), now=NOW)
        by_type = {f.fact_type: f for f in facts}
        assert RETURN_5D in by_type
        r5 = by_type[RETURN_5D]
        assert r5.calculation.parameters["sessions"] == "5"
        # 5営業日前の観測が基準（暦日ではない）
        expected_base = [p.trading_date
                         for p in series_points(list(range(100, 121)))][-6]
        assert r5.calculation.inputs[0].endswith(expected_base)
        assert r5.calculation.parameters["base_trading_date"] == expected_base
        assert r5.time.session_count == 6

    def test_20_session_return_requires_21_sessions(self):
        short = build_series_facts(TOPIX, series_points(list(range(100, 120))), now=NOW)
        assert RETURN_20D not in {f.fact_type for f in short}     # 20本では不足
        enough = build_series_facts(TOPIX, series_points(list(range(100, 121))), now=NOW)
        assert RETURN_20D in {f.fact_type for f in enough}        # 21本で成立

    def test_zero_base_value_produces_no_return_fact(self):
        """基準が0の変化率は作らない（無限大や0埋めを生まない）。"""
        facts = build_series_facts(TOPIX, series_points([0, 110]), now=NOW)
        assert INDEX_CHANGE_PCT not in {f.fact_type for f in facts}
        assert INDEX_CHANGE in {f.fact_type for f in facts}       # 絶対変化は作れる

    def test_ma25_requires_25_sessions(self):
        short = build_series_facts(TOPIX, series_points([100] * 24), now=NOW)
        assert MOVING_AVERAGE_25 not in {f.fact_type for f in short}
        enough = build_series_facts(TOPIX, series_points([100] * 25), now=NOW)
        by_type = {f.fact_type: f for f in enough}
        assert by_type[MOVING_AVERAGE_25].value.value == Decimal("100.000000")
        assert by_type[DISTANCE_FROM_MA25].value.value == Decimal("0.000000")

    def test_ma_fact_records_all_window_inputs(self):
        facts = build_series_facts(TOPIX, series_points([100] * 25), now=NOW)
        ma = {f.fact_type: f for f in facts}[MOVING_AVERAGE_25]
        assert len(ma.calculation.inputs) == 25
        assert ma.calculation.parameters["window_sessions"] == "25"
        assert len(ma.evidence) == 25          # provenanceは全入力へ辿れる

    def test_rates_series_has_no_percent_change_fact(self):
        facts = build_series_facts(JGB10Y, series_points([2.9, 2.95], unit="pct"),
                                   now=NOW)
        types = {f.fact_type for f in facts}
        assert YIELD_LEVEL in types
        assert INDEX_CHANGE_PCT not in types   # 金利は%変化を作らない
        change = {f.fact_type: f for f in facts}["yield_change"]
        assert change.value.unit == "pct_point"

    def test_rejected_qa_produces_no_facts(self):
        facts = build_series_facts(TOPIX, series_points([100, 110], qa="reject"),
                                   now=NOW)
        assert facts == []                     # REJECT由来はproduction Factにしない

    def test_limited_use_qa_is_marked_not_hidden(self):
        facts = build_series_facts(TOPIX, series_points([100, 110], qa="limited_use"),
                                   now=NOW)
        assert facts and all(f.status is FactStatus.LIMITED_USE for f in facts)
        assert all(f.qa_decision == "limited_use" for f in facts)

    def test_missing_value_sessions_are_excluded(self):
        pts = series_points([100, None, 120])
        facts = build_series_facts(TOPIX, pts, now=NOW)
        change = {f.fact_type: f for f in facts}[INDEX_CHANGE]
        # 欠測日をまたいで「直前の値のあるセッション」を基準にする（0埋めしない）
        assert change.value.value == Decimal("20.000000")

    def test_provenance_reaches_observation_ids(self):
        facts = build_series_facts(TOPIX, series_points([100, 110]), now=NOW)
        for fact in facts:
            assert fact.evidence
            for ref in fact.evidence:
                assert ref.kind is EvidenceKind.OBSERVATION
                assert ref.ref_id.startswith("obs_")

    def test_as_of_and_trading_date_are_distinct(self):
        facts = build_series_facts(TOPIX, series_points([100, 110]), now=NOW)
        close = {f.fact_type: f for f in facts}[INDEX_CLOSE]
        assert close.time.date_role is DateRole.TRADING_DATE
        assert close.time.as_of.isoformat().startswith(close.time.primary_date)
        assert close.time.as_of != close.created_at


class TestCrossSeriesFacts:
    def test_nt_ratio_same_trading_date_only(self):
        days = sessions(3)
        nikkei = [point(d, 39000, prefix="nk") for d in days]
        topix = [point(d, 2700, prefix="tp") for d in days[:-1]]   # 最新日が欠落
        fact = build_cross_series_fact(
            NT_RATIO, NIKKEI, TOPIX, nikkei, topix,
            subject_id="index:nikkei225_topix", unit="x",
            calculation_name=calc.NT_RATIO, now=NOW)
        assert fact.time.primary_date == days[-2]      # 揃っている最新日を使う
        assert fact.value.value == (Decimal(39000) / Decimal(2700)).quantize(
            Decimal("0.000001"))

    def test_nt_ratio_none_when_no_overlap(self):
        nikkei = [point("2026-09-01", 39000, prefix="nk")]
        topix = [point("2026-08-31", 2700, prefix="tp")]
        assert build_cross_series_fact(
            NT_RATIO, NIKKEI, TOPIX, nikkei, topix,
            subject_id="index:nikkei225_topix", unit="x",
            calculation_name=calc.NT_RATIO, now=NOW) is None

    def test_cross_fact_keeps_both_input_ids(self):
        days = sessions(2)
        fact = build_cross_series_fact(
            NT_RATIO, NIKKEI, TOPIX,
            [point(d, 39000, prefix="nk") for d in days],
            [point(d, 2700, prefix="tp") for d in days],
            subject_id="index:nikkei225_topix", unit="x",
            calculation_name=calc.NT_RATIO, now=NOW)
        assert len(fact.calculation.inputs) == 2
        assert fact.calculation.method == "nt_ratio:1.0.0"
        assert len(fact.evidence) == 2

    def test_yield_spread_same_date(self):
        days = sessions(2)
        fact = build_cross_series_fact(
            "yield_spread", "rates:UST10Y_par", "rates:UST2Y_par",
            [point(d, "4.75", prefix="l", unit="pct") for d in days],
            [point(d, "4.34", prefix="s", unit="pct") for d in days],
            subject_id="rates:UST10Y_UST2Y", unit="pct_point",
            calculation_name=calc.YIELD_SPREAD, now=NOW)
        assert fact.value.value == Decimal("0.410000")
        assert fact.value.unit == "pct_point"


# ============================================================ availability

class TestMorningAvailabilityAndLookAhead:
    def _fact_known_at(self, known_at, date_str="2026-08-31"):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)
        return Fact(
            fact_id=f"fact_{date_str}_{known_at.isoformat()}", fact_type=INDEX_CLOSE,
            subject=subject, value=FactValue(value=Decimal("100"), unit="index"),
            time=FactTimeContext(primary_date=date_str,
                                 date_role=DateRole.TRADING_DATE, known_at=known_at),
            evidence=(FactEvidenceRef(kind=EvidenceKind.OBSERVATION, ref_id="obs_1"),))

    def test_morning_cutoff_is_jst_morning(self):
        cutoff = morning_cutoff("2026-09-01")
        assert cutoff == datetime(2026, 8, 31, 21, 0, tzinfo=timezone.utc)  # JST 6:00

    def test_previous_session_close_is_available_in_the_morning(self):
        fact = self._fact_known_at(
            datetime(2026, 8, 31, 6, 30, tzinfo=timezone.utc))   # 前日15:30 JST
        assert is_known_by(fact, morning_cutoff("2026-09-01"))

    def test_information_published_after_cutoff_is_excluded(self):
        fact = self._fact_known_at(
            datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc))     # JST 10:00（朝より後）
        assert not is_known_by(fact, morning_cutoff("2026-09-01"))

    def test_fact_without_known_at_is_treated_as_unknown(self):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)
        fact = Fact(
            fact_id="fact_no_known", fact_type=INDEX_CLOSE, subject=subject,
            value=FactValue(value=Decimal("100"), unit="index"),
            time=FactTimeContext(primary_date="2026-08-31",
                                 date_role=DateRole.TRADING_DATE),
            evidence=(FactEvidenceRef(kind=EvidenceKind.OBSERVATION, ref_id="o"),))
        assert not is_known_by(fact, morning_cutoff("2026-09-01"))   # FAIL-CLOSED

    def test_snapshot_excludes_future_information(self):
        past = self._fact_known_at(datetime(2026, 8, 20, 6, 30, tzinfo=timezone.utc),
                                   "2026-08-20")
        future = self._fact_known_at(datetime(2026, 8, 25, 6, 30, tzinfo=timezone.utc),
                                     "2026-08-25")
        snapshot = morning_snapshot([past, future], "2026-08-21")
        assert [f.time.primary_date for f in snapshot] == ["2026-08-20"]
        assert leaked_facts(snapshot, morning_cutoff("2026-08-21")) == []

    def test_snapshot_excludes_limited_use_by_default(self):
        from dataclasses import replace
        fact = self._fact_known_at(datetime(2026, 8, 20, 6, 30, tzinfo=timezone.utc),
                                   "2026-08-20")
        limited = replace(fact, status=FactStatus.LIMITED_USE)
        assert morning_snapshot([limited], "2026-08-21") == []
        assert len(morning_snapshot([limited], "2026-08-21",
                                    include_limited_use=True)) == 1

    def test_available_at_filters(self):
        a = self._fact_known_at(datetime(2026, 8, 20, 6, 30, tzinfo=timezone.utc))
        b = self._fact_known_at(datetime(2026, 8, 30, 6, 30, tzinfo=timezone.utc))
        cutoff = datetime(2026, 8, 25, tzinfo=timezone.utc)
        assert available_at([a, b], cutoff) == [a]


# ============================================================ conflict

class TestSourceConflict:
    def _fact(self, value, source, fact_id):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)
        return Fact(
            fact_id=fact_id, fact_type=INDEX_CLOSE, subject=subject,
            value=FactValue(value=Decimal(str(value)), unit="index"),
            time=FactTimeContext(primary_date="2026-09-01",
                                 date_role=DateRole.TRADING_DATE),
            evidence=(FactEvidenceRef(kind=EvidenceKind.OBSERVATION,
                                      ref_id=f"obs_{source}"),),
            source_ids=(source,))

    def test_same_value_from_two_sources_is_agree(self):
        out = assess_conflicts([self._fact(100, "a", "f1"), self._fact(100, "b", "f2")])
        assert all(f.conflict_state is ConflictState.AGREE for f in out)
        assert all(f.conflicting_fact_ids for f in out)

    def test_different_values_are_conflict_and_both_kept(self):
        out = assess_conflicts([self._fact(100, "a", "f1"), self._fact(101, "b", "f2")])
        assert len(out) == 2                     # 片方を捨てない
        assert all(f.conflict_state is ConflictState.CONFLICT for f in out)
        assert len(conflicted(out)) == 2

    def test_single_source_stays_unknown_not_agree(self):
        out = assess_conflicts([self._fact(100, "a", "f1")])
        assert out[0].conflict_state is ConflictState.UNKNOWN

    def test_conflict_does_not_alter_values(self):
        out = assess_conflicts([self._fact(100, "a", "f1"), self._fact(101, "b", "f2")])
        assert sorted(str(f.value.value) for f in out) == ["100", "101"]


# ============================================================ store / query

@pytest.fixture()
def store(tmp_path):
    s = FactStore(tmp_path)
    yield s
    s.close()


class TestFactStore:
    def _facts(self):
        return build_series_facts(TOPIX, series_points([100] * 24 + [110]), now=NOW)

    def test_add_is_idempotent(self, store):
        facts = self._facts()
        first = store.add(facts)
        second = store.add(facts)
        assert first["added"] == len(facts)
        assert second["added"] == 0 and second["skipped"] == len(facts)
        assert store.count() == len(facts)

    def test_canonical_is_append_only_jsonl(self, store):
        store.add(self._facts())
        lines = [json.loads(l) for l in
                 store.canonical_path.read_text(encoding="utf-8").splitlines() if l]
        assert lines and all("fact_id" in r for r in lines)
        assert all(r["schema_version"] for r in lines)

    def test_revision_supersedes_previous_but_keeps_history(self, store):
        subject_points = series_points([100, 110])
        store.add(build_series_facts(TOPIX, subject_points, now=NOW))
        revised = series_points([100, 111])       # 同一日付・値が変わった
        result = store.add(build_series_facts(TOPIX, revised, now=NOW))
        assert result["superseded"] >= 1
        latest = store.latest_fact(TOPIX, INDEX_CLOSE)
        assert latest["value"] == "111"
        # 旧値はcanonicalに残る
        values = {r["value"] for r in store.iter_canonical()
                  if r["fact_type"] == INDEX_CLOSE}
        assert {"110", "111"} <= values

    def test_sqlite_rebuilds_from_canonical_only(self, store):
        store.add(self._facts())
        before = store.count()
        assert store.rebuild_index() == before
        assert store.count() == before

    def test_rebuild_restores_superseded_state(self, store):
        store.add(build_series_facts(TOPIX, series_points([100, 110]), now=NOW))
        store.add(build_series_facts(TOPIX, series_points([100, 111]), now=NOW))
        store.rebuild_index()
        assert store.latest_fact(TOPIX, INDEX_CLOSE)["value"] == "111"

    def test_query_latest_and_by_date(self, store):
        facts = self._facts()
        store.add(facts)
        latest = store.latest_fact(TOPIX, INDEX_CLOSE)
        assert latest["value"] == "110"
        assert store.facts_on(facts[0].time.primary_date)
        assert store.facts_between("2026-01-01", "2026-12-31")

    def test_query_by_series_and_subject(self, store):
        store.add(self._facts())
        assert store.facts_for_series(TOPIX)
        assert store.facts_for_subject(TOPIX)

    def test_query_by_evidence_source(self, store):
        facts = self._facts()
        store.add(facts)
        ref = facts[0].evidence[0].ref_id
        assert store.facts_by_evidence(ref)

    def test_derived_inputs_are_queryable(self, store):
        facts = self._facts()
        store.add(facts)
        ma = [f for f in facts if f.fact_type == MOVING_AVERAGE_25][0]
        assert len(store.derived_inputs(ma.fact_id)) == 25

    def test_conflicted_query(self, store):
        subject = FactSubject(subject_type="series", subject_id=TOPIX)

        def mk(value, fid, source):
            return Fact(
                fact_id=fid, fact_type=INDEX_CLOSE, subject=subject,
                value=FactValue(value=Decimal(value), unit="index"),
                time=FactTimeContext(primary_date="2026-09-01",
                                     date_role=DateRole.TRADING_DATE),
                evidence=(FactEvidenceRef(kind=EvidenceKind.OBSERVATION,
                                          ref_id=f"obs_{source}"),),
                source_ids=(source,))

        store.add(assess_conflicts([mk("100", "fa", "a"), mk("101", "fb", "b")]))
        assert len(store.conflicted_facts()) == 2

    def test_evidence_refs_queryable_for_citation(self, store):
        facts = self._facts()
        store.add(facts)
        refs = store.evidence_refs(facts[0].fact_id)
        assert refs and refs[0]["ref_id"].startswith("obs_")

    def test_incremental_generation_adds_only_new(self, store):
        store.add(build_series_facts(TOPIX, series_points([100, 110]), now=NOW))
        before = store.count()
        extended = series_points([100, 110, 120])
        result = store.add(build_series_facts(TOPIX, extended, now=NOW))
        assert result["added"] > 0
        assert store.count() > before


# ============================================================ pilot end-to-end (offline)

class TestPilotEndToEndOffline:
    """pilot本体を合成Data Bankで通す（live runを使わず実行時エラーを検知する）。"""

    def _seed_market_bank(self, tmp_path):
        from src.intelligence.core.paths import market_bank_root
        from src.intelligence.market.ingest import as_of_for
        from src.intelligence.market.model import Observation, ObservationKind
        from src.intelligence.market.series_catalog import load_catalog
        from src.intelligence.market.store import MarketBankStore

        catalog = load_catalog(Path("knowledge/market_series/core_series.yaml"))
        store = MarketBankStore(market_bank_root(tmp_path))
        days = sessions(30)
        observations = []
        # observation_idは**明示tag**で作る（series_idの接頭辞は
        # rates:UST2Y_par / rates:UST10Y_par で衝突する）
        for tag, series_id, base in (("topix", TOPIX, 2700),
                                     ("nikkei", NIKKEI, 39000),
                                     ("jgb10y", JGB10Y, 2),
                                     ("usdjpy", "fx:USDJPY.rate.closing.global", 150),
                                     ("ust2y", "rates:UST2Y_par.yield.closing.us", 4),
                                     ("ust10y", "rates:UST10Y_par.yield.closing.us", 5)):
            spec = catalog.get(series_id)
            if spec is None:
                continue
            for i, day in enumerate(days):
                observations.append(Observation(
                    observation_id=f"obs_{tag}_{day}",
                    entity_id=spec.series.instrument_id, metric=spec.series.metric,
                    value=Decimal(base + i), unit=spec.unit,
                    as_of=as_of_for(spec, day), kind=ObservationKind.RAW,
                    series_id=series_id, trading_date=day, source_id="test"))
        store.add_observations(observations)
        store.close()

    def test_pilot_runs_and_emits_markers(self, tmp_path, monkeypatch, capsys):
        from src.intelligence.facts import pilot

        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
        self._seed_market_bank(tmp_path)
        assert pilot.main(["--sessions", "3"]) == 0
        out = capsys.readouterr().out

        for marker in ("::P3A_INPUT::", "::P3A_FACTS::", "::P3A_REPLAY::",
                       "::P3A_SNAPSHOT::", "::P3A_QUERY::", "::P3A_QUALITY::"):
            assert marker in out, marker

        facts = json.loads(out.split("::P3A_FACTS::")[1].splitlines()[0])
        assert facts["generated"] > 0
        assert facts["rebuild_match"] is True
        assert facts["with_provenance"] == facts["generated"]

        quality = json.loads(out.split("::P3A_QUALITY::")[1].splitlines()[0])
        assert quality["missing_provenance"] == 0
        assert quality["derived_missing_inputs"] == 0
        assert quality["duplicate_fact_ids"] == 0

        snapshot = json.loads(out.split("::P3A_SNAPSHOT::")[1].splitlines()[0])
        assert snapshot["look_ahead_total_leaks"] == 0
        assert all(s["no_future_dates"] for s in snapshot["sessions"])

        replay = json.loads(out.split("::P3A_REPLAY::")[1].splitlines()[0])
        assert replay["nt_ratio"] is not None
        assert any(r["level"] for r in replay["series"])

    def test_pilot_skips_cleanly_without_market_bank(self, tmp_path, monkeypatch, capsys):
        from src.intelligence.facts import pilot

        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
        assert pilot.main([]) == 0
        assert "::P3A_PILOT_SKIP::" in capsys.readouterr().out

    def test_pilot_is_idempotent_across_runs(self, tmp_path, monkeypatch, capsys):
        from src.intelligence.facts import pilot

        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
        self._seed_market_bank(tmp_path)
        pilot.main(["--sessions", "2"])
        first = json.loads(
            capsys.readouterr().out.split("::P3A_FACTS::")[1].splitlines()[0])
        pilot.main(["--sessions", "2"])
        second = json.loads(
            capsys.readouterr().out.split("::P3A_FACTS::")[1].splitlines()[0])
        assert second["store_added"] == 0          # 再実行で増えない
        assert second["store_skipped"] == first["store_added"]
        assert second["canonical_rows"] == first["canonical_rows"]


# ============================================================ builders: jquants / news

class TestJQuantsFactInputs:
    def _record(self):
        from src.intelligence.market.jquants_records import (
            RecordProvenance, parse_financial_summary)
        prov = RecordProvenance(endpoint="/fins/summary",
                                retrieved_at="2026-09-01T00:00:00+00:00",
                                raw_item_id="raw_1", fetch_attempt_id="att_1")
        return parse_financial_summary({
            "Code": "72030", "DiscDate": "2026-08-05", "CurPerSt": "2025-04-01",
            "CurPerEn": "2026-03-31", "Sales": "45000", "OP": "5000",
            "NP": "3800", "EPS": "290.5",
            "FSales": "46000", "FOP": "5100", "FNP": "3900", "FEPS": "300.0",
        }, prov)

    def test_reported_and_forecast_are_separate_fact_types(self):
        from src.intelligence.facts.jquants_builder import (
            COMPANY_FORECAST_VALUE, REPORTED_FINANCIAL_VALUE, build_financial_facts)

        facts = build_financial_facts([self._record()], now=NOW)
        types = {f.fact_type for f in facts}
        assert types == {REPORTED_FINANCIAL_VALUE, COMPANY_FORECAST_VALUE}
        reported = {f.note: f for f in facts
                    if f.fact_type == REPORTED_FINANCIAL_VALUE}
        forecast = {f.note: f for f in facts
                    if f.fact_type == COMPANY_FORECAST_VALUE}
        assert reported["metric=net_sales"].value.value == Decimal("45000")
        assert forecast["metric=net_sales"].value.value == Decimal("46000")

    def test_missing_metric_creates_no_fact(self):
        from src.intelligence.market.jquants_records import (
            RecordProvenance, parse_financial_summary)
        from src.intelligence.facts.jquants_builder import build_financial_facts

        prov = RecordProvenance(endpoint="/fins/summary",
                                retrieved_at="2026-09-01T00:00:00+00:00")
        record = parse_financial_summary(
            {"Code": "1", "DiscDate": "2026-08-05", "Sales": ""}, prov)
        assert build_financial_facts([record], now=NOW) == []   # 0で埋めない

    def test_facts_carry_record_provenance(self):
        from src.intelligence.facts.jquants_builder import build_financial_facts
        from src.intelligence.facts.model import EvidenceKind

        facts = build_financial_facts([self._record()], now=NOW)
        for fact in facts:
            assert fact.evidence[0].kind is EvidenceKind.RECORD
            assert fact.evidence[0].ref_id.startswith("fin_")
            assert "/fins/summary#" in fact.evidence[0].locator

    def test_known_at_uses_disclosure_not_retrieval(self):
        from src.intelligence.facts.jquants_builder import build_financial_facts

        fact = build_financial_facts([self._record()], now=NOW)[0]
        assert fact.time.known_at.date().isoformat() == "2026-08-05"

    def test_earnings_schedule_fact(self):
        from src.intelligence.market.jquants_records import (
            RecordProvenance, parse_earnings_schedule)
        from src.intelligence.facts.jquants_builder import (
            EARNINGS_SCHEDULE, build_earnings_schedule_facts)

        prov = RecordProvenance(endpoint="/equities/earnings-calendar",
                                retrieved_at="2026-09-01T00:00:00+00:00")
        record = parse_earnings_schedule(
            {"Code": "72030", "Date": "2026-11-05", "CoName": "X", "FQ": "2",
             "FY": "2027"}, prov)
        facts = build_earnings_schedule_facts([record], now=NOW)
        assert facts[0].fact_type == EARNINGS_SCHEDULE
        assert facts[0].time.primary_date == "2026-11-05"
        assert facts[0].time.date_role.value == "event_date"


class TestNewsFactBoundary:
    class _Doc:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def _doc(self, **overrides):
        base = dict(document_id="doc_1", title="日銀が政策金利を据え置き",
                    published_at=datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc),
                    source_id="nhk_business", qa_decision="accept",
                    body="前段。日銀が政策金利を据え置き。後段。")
        base.update(overrides)
        return self._Doc(**base)

    def test_document_published_fact_is_citation_ready(self):
        from src.intelligence.facts.news_builder import (
            DOCUMENT_PUBLISHED, build_document_facts)

        fact = build_document_facts([self._doc()], now=NOW)[0]
        assert fact.fact_type == DOCUMENT_PUBLISHED
        ref = fact.evidence[0]
        assert ref.ref_id == "doc_1"
        assert ref.excerpt_start >= 0 and ref.excerpt_end > ref.excerpt_start
        assert ref.excerpt == "日銀が政策金利を据え置き"

    def test_title_is_kept_verbatim_not_summarized(self):
        from src.intelligence.facts.news_builder import build_document_facts

        fact = build_document_facts([self._doc()], now=NOW)[0]
        assert fact.value.text_value == "日銀が政策金利を据え置き"

    def test_rejected_documents_produce_no_facts(self):
        from src.intelligence.facts.news_builder import build_document_facts

        assert build_document_facts([self._doc(qa_decision="reject")], now=NOW) == []

    def test_limited_use_documents_are_marked(self):
        from src.intelligence.facts.news_builder import build_document_facts

        fact = build_document_facts([self._doc(qa_decision="limited_use")], now=NOW)[0]
        assert fact.status is FactStatus.LIMITED_USE

    def test_publication_date_role_and_known_at(self):
        from src.intelligence.facts.news_builder import build_document_facts

        fact = build_document_facts([self._doc()], now=NOW)[0]
        assert fact.time.date_role is DateRole.PUBLICATION_DATE
        assert fact.time.known_at == datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)

    def test_document_without_title_or_date_is_skipped(self):
        from src.intelligence.facts.news_builder import build_document_facts

        assert build_document_facts([self._doc(title="")], now=NOW) == []
        assert build_document_facts([self._doc(published_at=None)], now=NOW) == []
