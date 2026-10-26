"""P8-A2 — PIT の市場 ／ 財務の観測の test matrix A〜BX ・CM〜CP（境界 ／ 凍結の BY〜CL は `test_screener_intelligence_boundary.py`）。

すべて合成の data（架空の anchor ・値 ・出所の参照）。J-Quants ・network ・実データ ・legacy は使わない。書き込みは tmp だけ。
A1 の identity は A1 の本物の model ／ store で作る（A2 は A1 を変えない）。
"""
from __future__ import annotations

import builtins
import io
import itertools
import json
import os
import subprocess
import sys
from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import identity_model as im
from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence import observation_model as om
from src.intelligence.screener_intelligence import observation_resolver as orr
from src.intelligence.screener_intelligence import observation_store as ost
from src.intelligence.screener_intelligence.identity_model import IdentityHistory, SourceClass
from src.intelligence.screener_intelligence.observation_model import (
    Currency, FundamentalActual, FundamentalField, FundamentalForecast, KnowledgeTime, MarketField, MarketObservation,
    Measure, ObservationCoverage, ObservationHistory, ObservationHistoryError, ObservationModelError,
    ObservationProvenance, ObservationValue, PeriodBasis, PriceBasis, ReportingPeriod, Scale, StatementBasis,
    ValueState)
from src.intelligence.screener_intelligence.observation_resolver import ObservationQuery, ObservationStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
JQS = SourceClass.JQUANTS
DISC = SourceClass.ISSUER_DISCLOSURE
HR = SourceClass.HUMAN_REVIEWED
EX = SourceClass.OFFICIAL_EXCHANGE
RAW = PriceBasis.RAW_REPORTED
ADJ = PriceBasis.PROVIDER_ADJUSTED
CONS = StatementBasis.CONSOLIDATED
F = FundamentalField


def at(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def ts(*args) -> KnowledgeTime:
    return KnowledgeTime.exact(at(*args))


def on(year: int, month: int, day: int) -> KnowledgeTime:
    return KnowledgeTime.date_only(date(year, month, day))


def src(source: SourceClass = JQS, ref: str = "jq:rec-0001", field: str = "C", adj: str = "") -> ObservationProvenance:
    return ObservationProvenance(source_class=source, source_record_ref=ref, source_field=field, adjustment_ref=adj)


def price(amount) -> ObservationValue:
    return ObservationValue.present(Measure.PRICE, amount, currency=Currency.JPY)


def volume(amount) -> ObservationValue:
    return ObservationValue.present(Measure.TRADED_VOLUME, amount)


def money(amount, scale: Scale = Scale.MILLION) -> ObservationValue:
    return ObservationValue.present(Measure.MONETARY_AMOUNT, amount, currency=Currency.JPY, scale=scale)


def per_share(amount) -> ObservationValue:
    return ObservationValue.present(Measure.PER_SHARE_AMOUNT, amount, currency=Currency.JPY)


def shares(amount) -> ObservationValue:
    return ObservationValue.present(Measure.SHARE_COUNT, amount)


def absent(field: FundamentalField, state: ValueState) -> ObservationValue:
    return ObservationValue.absent(om.FUNDAMENTAL_MEASURES[field], state)


def market(sec, field: MarketField, value, session: date, knowledge: KnowledgeTime, *, basis: PriceBasis = RAW,
           source: SourceClass = JQS, adj: str = "", supersedes: str = "") -> MarketObservation:
    ref = f"jq:bars-{session.isoformat()}"
    return MarketObservation(security_id=sec.security_id, field=field, basis=basis, session_date=session, value=value,
                             knowledge=knowledge, provenance=src(source, ref, field.value.title(), adj),
                             supersedes=supersedes)


def actual(subject: str, field: FundamentalField, value, period: ReportingPeriod, knowledge: KnowledgeTime, *,
           source: SourceClass = JQS, supersedes: str = "") -> FundamentalActual:
    return FundamentalActual(subject=subject, field=field, statement_basis=CONS, period=period, value=value,
                             knowledge=knowledge, provenance=src(source, "disc:fy-0001", "Value"),
                             supersedes=supersedes)


def forecast(issuer_id: str, field: FundamentalField, value, period: ReportingPeriod, knowledge: KnowledgeTime, *,
             source: SourceClass = JQS, supersedes: str = "") -> FundamentalForecast:
    return FundamentalForecast(issuer_id=issuer_id, field=field, statement_basis=CONS, target_period=period,
                               value=value, knowledge=knowledge, provenance=src(source, "disc:fc-0001", "Forecast"),
                               supersedes=supersedes)


def coverage(dataset: om.CoverageDataset, start: date, end: date, through: datetime) -> ObservationCoverage:
    return ObservationCoverage(dataset=dataset, data_from=start, data_to=end, complete_through=through,
                               provenance=src(JQS, "jq:capture-0001", "", ""))


FY24 = ReportingPeriod(PeriodBasis.FISCAL_YEAR, date(2024, 4, 1), date(2025, 3, 31), date(2024, 4, 1),
                       date(2025, 3, 31))
FY25 = ReportingPeriod(PeriodBasis.FISCAL_YEAR, date(2025, 4, 1), date(2026, 3, 31), date(2025, 4, 1),
                       date(2026, 3, 31))
Q1C25 = ReportingPeriod(PeriodBasis.CUMULATIVE_YEAR_TO_DATE, date(2025, 4, 1), date(2026, 3, 31), date(2025, 4, 1),
                        date(2025, 6, 30), 1)
Q2S25 = ReportingPeriod(PeriodBasis.SINGLE_QUARTER, date(2025, 4, 1), date(2026, 3, 31), date(2025, 7, 1),
                        date(2025, 9, 30), 2)
D0602, D0603 = date(2025, 6, 2), date(2025, 6, 3)
CAPTURE = at(2026, 6, 30)


class Identity:
    """合成の A1 identity（A1 の本物の model）。S3 は 2024-06-30 まで上場、S4 は 2026 年に登録される。"""

    def __init__(self) -> None:
        k = at(2020, 1, 1)

        def p(known):
            return im.SourceProvenance(source_class=im.SourceClass.HUMAN_REVIEWED, source_record_ref="review:obs-1",
                                       known_at=known)
        self.I1 = im.IssuerRegistration(registration_anchor="hr:obs-issuer-one", provenance=p(k))
        self.I2 = im.IssuerRegistration(registration_anchor="hr:obs-issuer-two", provenance=p(k))
        self.S1 = im.SecurityRegistration(registration_anchor="hr:obs-security-one", issuer_id=self.I1.issuer_id,
                                          issue_class=im.IssueClass.COMMON_EQUITY, provenance=p(k))
        self.S3 = im.SecurityRegistration(registration_anchor="hr:obs-security-three", issuer_id=self.I2.issuer_id,
                                          issue_class=im.IssueClass.COMMON_EQUITY, provenance=p(k))
        s1_list = im.ListingStart(security_id=self.S1.security_id, venue=im.ListingVenue.TSE, effective_from=k,
                                  provenance=p(k))
        s3_list = im.ListingStart(security_id=self.S3.security_id, venue=im.ListingVenue.TSE, effective_from=k,
                                  provenance=p(k))
        cover = im.Coverage(scope=im.CoverageScope.JP_LISTED_EQUITY_IDENTITY, effective_from=k,
                            effective_to=at(2030, 1, 1), provenance=p(k))
        s3_end = im.ListingEnd(listing_record_id=s3_list.record_id, effective_to=at(2024, 6, 30, 15),
                               reason=im.ListingEndReason.DELISTED, provenance=p(at(2024, 6, 30, 15)))
        late = at(2026, 1, 5)
        self.S4 = im.SecurityRegistration(registration_anchor="hr:obs-security-late", issuer_id=self.I2.issuer_id,
                                          issue_class=im.IssueClass.COMMON_EQUITY, provenance=p(late))
        s4_list = im.ListingStart(security_id=self.S4.security_id, venue=im.ListingVenue.TSE, effective_from=late,
                                  provenance=p(late))
        self.records = [self.I1, self.I2, self.S1, self.S3, s1_list, s3_list, cover, s3_end, self.S4, s4_list]

    def history(self) -> IdentityHistory:
        return IdentityHistory(self.records)


class World:
    """合成の観測（出所は主に J-Quants 相当 ・一部は発行体の開示）。coverage は最後に宣言する。"""

    def __init__(self) -> None:
        self.ids = ids = Identity()
        s1, i1, i2 = ids.S1, ids.I1.issuer_id, ids.I2.issuer_id
        k0602 = ts(2025, 6, 2, 8, 10)
        self.open = market(s1, MarketField.OPEN, price("1000"), D0602, k0602)
        self.high = market(s1, MarketField.HIGH, price("1100"), D0602, k0602)
        self.low = market(s1, MarketField.LOW, price("990"), D0602, k0602)
        self.close = market(s1, MarketField.CLOSE, price("1050"), D0602, k0602)
        self.volume = market(s1, MarketField.VOLUME, volume("123400"), D0602, k0602)
        self.adj_close = market(s1, MarketField.CLOSE, price("1050"), D0602, k0602, basis=ADJ, adj="jq:adj-v1")
        self.adj_close_split = market(s1, MarketField.CLOSE, price("525"), D0602, ts(2025, 9, 1, 8, 10), basis=ADJ,
                                      adj="jq:adj-v2", supersedes=self.adj_close.record_id)
        self.close_date_only = market(s1, MarketField.CLOSE, price("1060"), D0603, on(2025, 6, 3))
        self.s3_close = market(ids.S3, MarketField.CLOSE, price("300"), date(2024, 7, 1), ts(2024, 7, 1, 8))
        self.s3_close_listed = market(ids.S3, MarketField.CLOSE, price("310"), date(2024, 6, 28), ts(2024, 6, 28, 8))
        self.s4_close = market(ids.S4, MarketField.CLOSE, price("700"), D0602, k0602)
        k0512 = ts(2025, 5, 12, 6, 5, 7)
        self.revenue = actual(i1, F.REVENUE, money("500000"), FY24, k0512)
        self.op_income = actual(i1, F.OPERATING_INCOME, money("40000"), FY24, k0512)
        self.net_income = actual(i1, F.NET_INCOME, money("25000"), FY24, k0512)
        self.net_income_disclosure = actual(i1, F.NET_INCOME, money("25000"), FY24, ts(2025, 5, 12, 6), source=DISC)
        self.eps = actual(i1, F.EPS, per_share("123.45"), FY24, k0512)
        self.equity = actual(i1, F.EQUITY, money("300000"), FY24, k0512)
        self.assets = actual(i1, F.TOTAL_ASSETS, money("900000"), FY24, k0512)
        self.ocf = actual(i1, F.OPERATING_CASH_FLOW, money("-6000"), FY24, k0512)
        self.shares = actual(s1.security_id, F.SHARES_OUTSTANDING, shares("200000000"), FY24, k0512)
        self.revenue_restated = actual(i1, F.REVENUE, money("498000"), FY24, ts(2025, 11, 14, 6),
                                       supersedes=self.revenue.record_id)
        self.q1_revenue = actual(i1, F.REVENUE, money("130000"), Q1C25, on(2025, 8, 8))
        self.q1_ocf = actual(i1, F.OPERATING_CASH_FLOW, absent(F.OPERATING_CASH_FLOW, ValueState.NOT_REPORTED), Q1C25,
                             on(2025, 8, 8))
        self.q2_revenue = actual(i1, F.REVENUE, money("125000"), Q2S25, ts(2025, 11, 14, 6))
        k0513 = ts(2025, 5, 13, 6)
        self.i2_net_zero = actual(i2, F.NET_INCOME, money("0"), FY24, k0513)
        self.i2_revenue_missing = actual(i2, F.REVENUE, absent(F.REVENUE, ValueState.MISSING), FY24, k0513)
        self.i2_op_na = actual(i2, F.OPERATING_INCOME, absent(F.OPERATING_INCOME, ValueState.NOT_APPLICABLE), FY24,
                               k0513)
        self.f1 = forecast(i1, F.REVENUE, money("520000"), FY25, k0512)
        self.f2 = forecast(i1, F.REVENUE, money("510000"), FY25, ts(2025, 11, 14, 6), supersedes=self.f1.record_id)
        self.fy25_actual = actual(i1, F.REVENUE, money("505000"), FY25, ts(2026, 5, 13, 6))
        self.market_cover = coverage(om.CoverageDataset.MARKET_DAILY, date(2025, 1, 1), date(2026, 1, 1), CAPTURE)
        self.fundamental_cover = coverage(om.CoverageDataset.FUNDAMENTAL_DISCLOSURE, date(2024, 1, 1),
                                          date(2027, 1, 1), CAPTURE)
        self.records = [self.open, self.high, self.low, self.close, self.volume, self.adj_close, self.adj_close_split,
                        self.close_date_only, self.s3_close, self.s3_close_listed, self.s4_close, self.revenue,
                        self.op_income, self.net_income, self.net_income_disclosure, self.eps, self.equity,
                        self.assets, self.ocf, self.shares, self.revenue_restated, self.q1_revenue, self.q1_ocf,
                        self.q2_revenue, self.i2_net_zero, self.i2_revenue_missing, self.i2_op_na, self.f1, self.f2,
                        self.fy25_actual, self.market_cover, self.fundamental_cover]

    def history(self, records=None) -> ObservationHistory:
        return ObservationHistory(self.ids.history(), self.records if records is None else records)


@pytest.fixture()
def w() -> World:
    return World()


def resolve(world: World, query: ObservationQuery, cutoff: datetime):
    return orr.resolve(world.history(), query, cutoff=cutoff)


def q_market(world: World, field: MarketField, session: date = D0602, basis: PriceBasis = RAW, sec=None):
    return ObservationQuery.market((sec or world.ids.S1).security_id, field, basis, session)


def q_actual(world: World, field: FundamentalField, period: ReportingPeriod = FY24, subject: str = None,
             source: SourceClass = None):
    return ObservationQuery.actual(subject or world.ids.I1.issuer_id, field, CONS, period, source_class=source)


def q_forecast(world: World, field: FundamentalField = F.REVENUE, period: ReportingPeriod = FY25):
    return ObservationQuery.forecast(world.ids.I1.issuer_id, field, CONS, period)


def write_world(root: Path, world: World):
    identity = ist.IdentityStore.initialize(root)
    for record in world.ids.records:
        identity.append(record)
    store = ost.ObservationStore.initialize(root)
    for record in world.records:
        store.append(record)
    return identity, store


LATE = at(2026, 6, 1)


# ================================================================ A〜G class ・主語


def test_a_market_observation_model(w: World) -> None:
    assert w.close.CLASS is om.ObservationClass.MARKET_OBSERVATION and w.close.subject_kind is im.SubjectKind.SECURITY
    assert w.close.data_date == D0602 and w.close.value.measure is Measure.PRICE
    assert w.close.AUTHORITY_CLASS == om.AUTHORITATIVE_OBSERVATION_RECORD and w.close.record_id.startswith("p8obs_")


def test_b_fundamental_actual_model(w: World) -> None:
    assert w.revenue.CLASS is om.ObservationClass.FUNDAMENTAL_ACTUAL and w.revenue.subject_kind is im.SubjectKind.ISSUER
    assert w.revenue.data_date == FY24.period_end and w.shares.subject_kind is im.SubjectKind.SECURITY


def test_c_forecast_model(w: World) -> None:
    assert w.f1.CLASS is om.ObservationClass.FUNDAMENTAL_FORECAST and w.f1.target_period == FY25
    assert w.f1.knowledge.earliest < day(FY25.period_end)                                   # 予想は期間の前に知り得る


def day(value: date) -> datetime:
    return om.day_start(value)


def test_d_observation_classes_cannot_alias(w: World) -> None:
    assert len({type(w.close), type(w.revenue), type(w.f1)}) == 3
    assert w.f1.slot_key != w.fy25_actual.slot_key                                          # 同じ主語 ・欄 ・期間でも別
    for bad in (F.EQUITY, F.TOTAL_ASSETS, F.OPERATING_CASH_FLOW, F.SHARES_OUTSTANDING):
        with pytest.raises(ObservationModelError) as exc:
            forecast(w.ids.I1.issuer_id, bad, money("1") if bad is not F.SHARES_OUTSTANDING else shares("1"), FY25,
                     ts(2025, 5, 12))
        assert exc.value.code in ("NOT_FORECASTABLE", "INVALID_SUBJECT")
    tampered = json.loads(w.f1.canonical_line())
    tampered["record_kind"] = "FUNDAMENTAL_ACTUAL"
    with pytest.raises(ObservationModelError):
        om.parse_observation_record(tampered)
    history = w.history()
    actual_answer = orr.resolve(history, q_actual(w, F.REVENUE, FY25), cutoff=at(2026, 1, 1))
    assert actual_answer.status is ObservationStatus.NOT_FOUND                               # 予想は実績として返らない


def test_e_market_observations_have_a_security_subject(w: World) -> None:
    with pytest.raises(ObservationModelError) as exc:
        MarketObservation(security_id=w.ids.I1.issuer_id, field=MarketField.CLOSE, basis=RAW, session_date=D0602,
                          value=price("1"), knowledge=ts(2025, 6, 2, 9), provenance=src())
    assert exc.value.code == "INVALID_SUBJECT"


def test_f_statement_fundamentals_have_an_issuer_subject(w: World) -> None:
    with pytest.raises(ObservationModelError):
        actual(w.ids.S1.security_id, F.REVENUE, money("1"), FY24, ts(2025, 5, 12))            # Issuer を Security にしない
    with pytest.raises(ObservationModelError):
        actual(w.ids.I1.issuer_id, F.SHARES_OUTSTANDING, shares("1"), FY24, ts(2025, 5, 12))
    with pytest.raises(ObservationModelError):
        forecast(w.ids.S1.security_id, F.REVENUE, money("1"), FY25, ts(2025, 5, 12))


def test_g_invalid_subject_class_pairings_are_rejected_in_queries(w: World) -> None:
    for build in (lambda: ObservationQuery.market(w.ids.I1.issuer_id, MarketField.CLOSE, RAW, D0602),
                  lambda: ObservationQuery.actual(w.ids.S1.security_id, F.REVENUE, CONS, FY24),
                  lambda: ObservationQuery.actual(w.ids.I1.issuer_id, F.SHARES_OUTSTANDING, CONS, FY24),
                  lambda: ObservationQuery.forecast(w.ids.I1.issuer_id, F.EQUITY, CONS, FY25),
                  lambda: ObservationQuery.market(w.ids.S1.security_id, F.REVENUE, RAW, D0602),
                  lambda: ObservationQuery.market(w.ids.S1.security_id, MarketField.CLOSE, CONS, D0602),
                  lambda: ObservationQuery.market(w.ids.S1.security_id, MarketField.CLOSE, RAW, at(2025, 6, 2))):
        with pytest.raises(ObservationModelError):
            build()


# ================================================================ H〜L 市場の欄


@pytest.mark.parametrize("field,amount,measure", [
    (MarketField.OPEN, "1000", Measure.PRICE), (MarketField.HIGH, "1100", Measure.PRICE),
    (MarketField.LOW, "990", Measure.PRICE), (MarketField.CLOSE, "1050", Measure.PRICE),
    (MarketField.VOLUME, "123400", Measure.TRADED_VOLUME)])
def test_h_to_l_open_high_low_close_volume(w: World, field: MarketField, amount: str, measure: Measure) -> None:
    result = resolve(w, q_market(w, field), at(2025, 6, 3))
    assert result.status is ObservationStatus.FOUND and result.record.field is field
    assert result.record.value.amount == amount and result.record.value.measure is measure
    assert (result.record.value.currency is Currency.JPY) is (measure is Measure.PRICE)
    with pytest.raises(ObservationModelError):
        market(w.ids.S1, field, money("1") if field is MarketField.VOLUME else volume("1"), D0602, ts(2025, 6, 2, 9))


# ================================================================ M〜P 生値と調整値


def test_m_raw_reported_price(w: World) -> None:
    result = resolve(w, q_market(w, MarketField.CLOSE), at(2025, 12, 1))
    assert result.record.basis is RAW and result.record.value.amount == "1050"
    assert result.record.provenance.adjustment_ref == ""


def test_n_provider_adjusted_is_a_distinct_slot_with_its_calculation_reference(w: World) -> None:
    assert w.adj_close.slot_key != w.close.slot_key
    assert w.adj_close.provenance.adjustment_ref == "jq:adj-v1"
    with pytest.raises(ObservationModelError) as missing_ref:
        market(w.ids.S1, MarketField.CLOSE, price("1"), D0602, ts(2025, 6, 2, 9), basis=ADJ)
    assert missing_ref.value.code == "ADJUSTMENT_REF_RULE"
    with pytest.raises(ObservationModelError):
        market(w.ids.S1, MarketField.CLOSE, price("1"), D0602, ts(2025, 6, 2, 9), adj="jq:adj-v1")   # 生値は参照なし
    with pytest.raises(ObservationModelError) as source:
        market(w.ids.S1, MarketField.CLOSE, price("1"), D0602, ts(2025, 6, 2, 9), basis=ADJ, adj="x:1", source=EX)
    assert source.value.code == "SOURCE_NOT_COMPATIBLE"


def test_o_an_adjusted_value_never_replaces_the_raw_observation(w: World) -> None:
    for cutoff in (at(2025, 6, 3), at(2025, 12, 1)):
        raw = resolve(w, q_market(w, MarketField.CLOSE), cutoff)
        assert raw.record is w.close or raw.record == w.close
        assert raw.record.value.amount == "1050"
    over_raw = market(w.ids.S1, MarketField.CLOSE, price("525"), D0602, ts(2025, 9, 1, 8, 10), basis=ADJ,
                      adj="jq:adj-v2", supersedes=w.close.record_id)                          # 調整値で生値を上書きする試み
    with pytest.raises(ObservationHistoryError) as exc:
        w.history([w.close, over_raw])
    assert exc.value.code == "PREDECESSOR_WRONG_SLOT"


def test_p_a_later_adjustment_does_not_leak_backward(w: World) -> None:
    before = resolve(w, q_market(w, MarketField.CLOSE, basis=ADJ), at(2025, 8, 31))
    after = resolve(w, q_market(w, MarketField.CLOSE, basis=ADJ), at(2025, 9, 2))
    assert before.record.value.amount == "1050" and before.lineage == (w.adj_close.record_id,)
    assert after.record.value.amount == "525"
    assert after.lineage == (w.adj_close.record_id, w.adj_close_split.record_id)


# ================================================================ Q〜S 市場の時間


def test_q_the_market_date_is_an_explicit_calendar_date(w: World) -> None:
    with pytest.raises(ObservationModelError) as exc:
        MarketObservation(security_id=w.ids.S1.security_id, field=MarketField.CLOSE, basis=RAW,
                          session_date=at(2025, 6, 2), value=price("1"), knowledge=ts(2025, 6, 2, 9), provenance=src())
    assert exc.value.code == "INVALID_DATE"
    with pytest.raises(ObservationModelError) as early:
        market(w.ids.S1, MarketField.CLOSE, price("1"), D0602, ts(2025, 6, 1, 14))            # 取引日より前に知り得ない
    assert early.value.code == "KNOWN_BEFORE_SESSION"


def test_r_knowledge_time_is_explicit_and_aware(w: World) -> None:
    with pytest.raises(ObservationModelError) as exc:
        KnowledgeTime.exact(datetime(2025, 6, 2, 9))
    assert exc.value.code == "NAIVE_DATETIME"
    with pytest.raises(ObservationModelError):
        KnowledgeTime.date_only(at(2025, 6, 2))                                                # 時刻を日付と偽らない
    with pytest.raises(ObservationModelError):
        KnowledgeTime(om.KnowledgePrecision.DATE, at=at(2025, 6, 2), on=date(2025, 6, 2))
    assert json.loads(w.close.canonical_line())["payload"]["knowledge"] == {
        "precision": "TIMESTAMP", "value": "2025-06-02T08:10:00+00:00"}


def test_s_a_future_market_record_is_ignored(w: World) -> None:
    cutoff = at(2025, 6, 2, 8, 9)
    result = resolve(w, q_market(w, MarketField.CLOSE), cutoff)
    assert result.status is ObservationStatus.NOT_FOUND
    without = orr.resolve(w.history([r for r in w.records if r is not w.close]), q_market(w, MarketField.CLOSE),
                          cutoff=cutoff)
    assert result.canonical_json() == without.canonical_json()


# ================================================================ T〜Z 実績の欄


@pytest.mark.parametrize("field,amount,measure", [
    (F.REVENUE, "498000", Measure.MONETARY_AMOUNT), (F.OPERATING_INCOME, "40000", Measure.MONETARY_AMOUNT),
    (F.NET_INCOME, "25000", Measure.MONETARY_AMOUNT), (F.EPS, "123.45", Measure.PER_SHARE_AMOUNT),
    (F.EQUITY, "300000", Measure.MONETARY_AMOUNT), (F.TOTAL_ASSETS, "900000", Measure.MONETARY_AMOUNT),
    (F.OPERATING_CASH_FLOW, "-6000", Measure.MONETARY_AMOUNT)])
def test_t_to_z_reported_actuals(w: World, field: FundamentalField, amount: str, measure: Measure) -> None:
    result = resolve(w, q_actual(w, field, source=JQS), at(2026, 1, 5))
    assert result.status is ObservationStatus.FOUND and result.record.field is field
    assert result.record.value.amount == amount and result.record.value.measure is measure
    assert result.record.CLASS is om.ObservationClass.FUNDAMENTAL_ACTUAL


def test_t_to_z_actuals_cannot_be_known_before_the_period_ends(w: World) -> None:
    with pytest.raises(ObservationModelError) as exc:
        actual(w.ids.I1.issuer_id, F.REVENUE, money("1"), FY24, ts(2025, 3, 31, 10))
    assert exc.value.code == "ACTUAL_KNOWN_BEFORE_PERIOD_END"


# ================================================================ AA〜AC 予想


def test_aa_a_forecast_is_distinct_from_an_actual(w: World) -> None:
    fc = resolve(w, q_forecast(w), at(2026, 6, 1))
    ac = resolve(w, q_actual(w, F.REVENUE, FY25), at(2026, 6, 1))
    assert fc.record.CLASS is om.ObservationClass.FUNDAMENTAL_FORECAST and fc.record.value.amount == "510000"
    assert ac.record.CLASS is om.ObservationClass.FUNDAMENTAL_ACTUAL and ac.record.value.amount == "505000"


def test_ab_forecast_revisions_resolve_point_in_time(w: World) -> None:
    assert resolve(w, q_forecast(w), at(2025, 5, 12, 6)).status is ObservationStatus.NOT_FOUND
    first = resolve(w, q_forecast(w), at(2025, 6, 1))
    second = resolve(w, q_forecast(w), at(2025, 12, 1))
    assert first.record.value.amount == "520000" and first.lineage == (w.f1.record_id,)
    assert second.record.value.amount == "510000" and second.lineage == (w.f1.record_id, w.f2.record_id)


def test_ac_a_later_actual_does_not_rewrite_forecast_history(w: World) -> None:
    for cutoff in (at(2025, 12, 1), at(2026, 6, 1)):
        assert resolve(w, q_forecast(w), cutoff).record.value.amount == "510000"
    assert resolve(w, q_actual(w, F.REVENUE, FY25), at(2025, 12, 1)).status is ObservationStatus.NOT_FOUND


# ================================================================ AD〜AG 期間


def test_ad_fiscal_year_period(w: World) -> None:
    assert FY24.basis is PeriodBasis.FISCAL_YEAR and FY24.quarter == 0
    assert w.revenue.period.as_dict() == {"basis": "FISCAL_YEAR", "fiscal_year_end": "2025-03-31",
                                          "fiscal_year_start": "2024-04-01", "period_end": "2025-03-31",
                                          "period_start": "2024-04-01", "quarter": 0}


def test_ae_quarterly_and_cumulative_periods_are_distinct(w: World) -> None:
    cumulative = resolve(w, q_actual(w, F.REVENUE, Q1C25), at(2025, 9, 1))
    single = resolve(w, q_actual(w, F.REVENUE, Q2S25), at(2025, 12, 1))
    assert cumulative.record.period.basis is PeriodBasis.CUMULATIVE_YEAR_TO_DATE and cumulative.record.value.amount == "130000"
    assert single.record.period.basis is PeriodBasis.SINGLE_QUARTER and single.record.value.amount == "125000"
    q2_cumulative = ReportingPeriod(PeriodBasis.CUMULATIVE_YEAR_TO_DATE, date(2025, 4, 1), date(2026, 3, 31),
                                    date(2025, 4, 1), date(2025, 9, 30), 2)
    assert resolve(w, q_actual(w, F.REVENUE, q2_cumulative), at(2025, 12, 1)).status is ObservationStatus.NOT_FOUND


@pytest.mark.parametrize("args", [
    (PeriodBasis.FISCAL_YEAR, date(2024, 4, 1), date(2025, 3, 31), date(2024, 4, 1), date(2025, 3, 30), 0),
    (PeriodBasis.FISCAL_YEAR, date(2024, 4, 1), date(2025, 3, 31), date(2024, 4, 1), date(2025, 3, 31), 4),
    (PeriodBasis.CUMULATIVE_YEAR_TO_DATE, date(2024, 4, 1), date(2025, 3, 31), date(2024, 5, 1), date(2024, 6, 30), 1),
    (PeriodBasis.CUMULATIVE_YEAR_TO_DATE, date(2024, 4, 1), date(2025, 3, 31), date(2024, 4, 1), date(2025, 3, 31), 4),
    (PeriodBasis.SINGLE_QUARTER, date(2024, 4, 1), date(2025, 3, 31), date(2024, 7, 1), date(2024, 6, 30), 2),
    (PeriodBasis.SINGLE_QUARTER, date(2024, 4, 1), date(2025, 3, 31), date(2024, 4, 1), date(2025, 4, 30), 1),
    (PeriodBasis.SINGLE_QUARTER, date(2024, 4, 1), date(2025, 3, 31), date(2024, 4, 1), date(2024, 6, 30), 5),
    (PeriodBasis.FISCAL_YEAR, date(2020, 4, 1), date(2025, 3, 31), date(2020, 4, 1), date(2025, 3, 31), 0)])
def test_af_period_boundaries_are_validated(args) -> None:
    with pytest.raises(ObservationModelError) as exc:
        ReportingPeriod(*args)
    assert exc.value.code == "INVALID_PERIOD"


def test_ag_no_implicit_ttm_or_annualization(w: World) -> None:
    assert {member.value for member in PeriodBasis} == {"FISCAL_YEAR", "SINGLE_QUARTER", "CUMULATIVE_YEAR_TO_DATE"}
    public = {name.lower() for module in (om, orr, ost) for name in dir(module)}
    assert not {n for n in public if "ttm" in n or "trailing" in n or "annual" in n}
    history = w.history()
    fy = orr.resolve(history, q_actual(w, F.REVENUE, FY24, source=JQS), cutoff=at(2025, 9, 1))
    assert fy.record.period == FY24 and fy.record.value.amount == "500000"                    # 四半期を合算しない


# ================================================================ AH〜AK 知識の精度


def test_ah_an_exact_disclosure_timestamp_is_preserved(w: World) -> None:
    result = resolve(w, q_actual(w, F.EPS), at(2025, 6, 1))
    assert result.record.knowledge.at == at(2025, 5, 12, 6, 5, 7)
    assert result.as_dict()["record"]["payload"]["knowledge"] == {"precision": "TIMESTAMP",
                                                                  "value": "2025-05-12T06:05:07+00:00"}
    assert resolve(w, q_actual(w, F.EPS), at(2025, 5, 12, 6, 5, 6)).status is ObservationStatus.NOT_FOUND
    assert resolve(w, q_actual(w, F.EPS), at(2025, 5, 12, 6, 5, 7)).status is ObservationStatus.FOUND


def test_ai_date_only_precision_is_represented(w: World) -> None:
    assert w.q1_revenue.knowledge.precision is om.KnowledgePrecision.DATE and w.q1_revenue.knowledge.at is None
    assert json.loads(w.q1_revenue.canonical_line())["payload"]["knowledge"] == {"precision": "DATE",
                                                                                 "value": "2025-08-08"}


@pytest.mark.parametrize("cutoff,status", [
    (at(2025, 8, 7, 14, 59), ObservationStatus.NOT_FOUND),                                     # 前日（東京）
    (at(2025, 8, 7, 15), ObservationStatus.INSUFFICIENT_TIME_PRECISION),                        # 当日 0 時（東京）
    (at(2025, 8, 8, 3), ObservationStatus.INSUFFICIENT_TIME_PRECISION),                         # 当日の昼
    (at(2025, 8, 8, 14, 59, 59), ObservationStatus.INSUFFICIENT_TIME_PRECISION),                # 当日の終わり
    (at(2025, 8, 8, 15), ObservationStatus.FOUND)])                                             # 翌日 0 時（東京）
def test_aj_an_intraday_query_cannot_overclaim_date_only_knowledge(w: World, cutoff, status) -> None:
    assert resolve(w, q_actual(w, F.REVENUE, Q1C25), cutoff).status is status


def test_ak_no_default_publication_time(w: World) -> None:
    for cutoff in (at(2025, 6, 3, 6, 30), at(2025, 6, 3, 9), at(2025, 6, 3, 14, 59)):           # 引け後でも日付だけなら不確か
        assert resolve(w, q_market(w, MarketField.CLOSE, D0603), cutoff).status is \
            ObservationStatus.INSUFFICIENT_TIME_PRECISION
    assert resolve(w, q_market(w, MarketField.CLOSE, D0603), at(2025, 6, 3, 15)).status is ObservationStatus.FOUND
    line = w.close_date_only.canonical_line()
    assert '"value":"2025-06-03"' in line and "T" not in json.loads(line)["payload"]["knowledge"]["value"]


# ================================================================ AL〜AN 訂正 ・修正


def test_al_a_restatement_leaves_the_original_record_immutable(w: World, tmp_path: Path) -> None:
    _, store = write_world(tmp_path, w)
    lines = store.canonical_lines()
    assert w.revenue.canonical_line() in lines and w.revenue_restated.canonical_line() in lines
    assert lines.index(w.revenue.canonical_line()) < lines.index(w.revenue_restated.canonical_line())
    assert w.revenue_restated.supersedes == w.revenue.record_id


def test_am_before_the_correction_the_old_value_applies(w: World) -> None:
    result = resolve(w, q_actual(w, F.REVENUE), at(2025, 11, 14, 5, 59))
    assert result.record.value.amount == "500000" and result.lineage == (w.revenue.record_id,)


def test_an_the_corrected_value_applies_only_after_it_is_known(w: World) -> None:
    result = resolve(w, q_actual(w, F.REVENUE), at(2025, 11, 14, 6))
    assert result.record.value.amount == "498000"
    assert result.lineage == (w.revenue.record_id, w.revenue_restated.record_id)


# ================================================================ AO〜AS 値


def test_ao_decimal_representation_is_deterministic(w: World) -> None:
    variants = [price("1050"), price("1050.0"), price("1050.000"), price(Decimal("1050.00")), price(1050),
                price(Decimal("1.05E+3"))]
    assert {v.amount for v in variants} == {"1050"}
    records = {market(w.ids.S1, MarketField.CLOSE, v, D0602, ts(2025, 6, 2, 8, 10)).record_id for v in variants}
    assert records == {w.close.record_id}
    assert ObservationValue.present(Measure.MONETARY_AMOUNT, "-0.50", currency=Currency.JPY).amount == "-0.5"
    for bad in (1050.0, float("nan"), True, "1e3", "1,050", "+1", " 1", "１０", Decimal("Infinity"), "0x10"):
        with pytest.raises(ObservationModelError):
            price(bad)
    with pytest.raises(ObservationModelError) as float_error:
        price(0.1)
    assert float_error.value.code == "FLOAT_REJECTED"
    tampered = json.loads(w.close.canonical_line())
    tampered["payload"]["value"]["amount"] = "1050.0"
    with pytest.raises(ObservationModelError):
        om.parse_observation_record(tampered)


def test_ap_units_are_explicit_measures() -> None:
    assert om.MARKET_MEASURES[MarketField.VOLUME] is Measure.TRADED_VOLUME
    assert om.FUNDAMENTAL_MEASURES[F.SHARES_OUTSTANDING] is Measure.SHARE_COUNT
    with pytest.raises(ObservationModelError):
        ObservationValue("PRESENT", Measure.PRICE, "1", Currency.JPY, Scale.ONE)


def test_aq_currency_is_required_where_relevant_and_forbidden_elsewhere() -> None:
    with pytest.raises(ObservationModelError) as missing:
        ObservationValue.present(Measure.PRICE, "1")
    assert missing.value.code == "INVALID_CURRENCY"
    with pytest.raises(ObservationModelError):
        ObservationValue.present(Measure.SHARE_COUNT, "1", currency=Currency.JPY)
    with pytest.raises(ObservationModelError):
        ObservationValue.present(Measure.MONETARY_AMOUNT, "1", currency="JPY")


def test_ar_per_share_values_are_distinct_from_totals(w: World) -> None:
    assert w.eps.value.measure is Measure.PER_SHARE_AMOUNT and w.revenue.value.measure is Measure.MONETARY_AMOUNT
    with pytest.raises(ObservationModelError) as exc:
        actual(w.ids.I1.issuer_id, F.EPS, money("1"), FY24, ts(2025, 5, 12))
    assert exc.value.code == "MEASURE_MISMATCH"
    with pytest.raises(ObservationModelError):
        ObservationValue.present(Measure.PER_SHARE_AMOUNT, "1", currency=Currency.JPY, scale=Scale.THOUSAND)


def test_as_scale_is_explicit_and_bounded_per_measure(w: World) -> None:
    assert w.revenue.value.scale is Scale.MILLION and w.close.value.scale is Scale.ONE
    assert money("5", Scale.ONE).amount == money("5", Scale.MILLION).amount                  # 換算しない（桁は属性）
    assert money("5", Scale.ONE) != money("5", Scale.MILLION)
    with pytest.raises(ObservationModelError) as exc:
        ObservationValue.present(Measure.PRICE, "1", currency=Currency.JPY, scale=Scale.MILLION)
    assert exc.value.code == "INVALID_SCALE"


def test_as_signs_follow_the_measure() -> None:
    for bad in (lambda: price("0"), lambda: price("-1"), lambda: volume("-1"),
                lambda: ObservationValue.present(Measure.SHARE_COUNT, "-1")):
        with pytest.raises(ObservationModelError) as exc:
            bad()
        assert exc.value.code == "INVALID_SIGN"
    assert volume("0").amount == "0" and money("-1").amount == "-1"


# ================================================================ AT〜AW 欠損 ・0


def test_at_zero_is_preserved_as_a_value(w: World) -> None:
    result = resolve(w, q_actual(w, F.NET_INCOME, subject=w.ids.I2.issuer_id), at(2025, 6, 1))
    assert result.record.value.state is ValueState.VALUE_PRESENT and result.record.value.amount == "0"


@pytest.mark.parametrize("field,state", [(F.REVENUE, ValueState.MISSING),
                                         (F.OPERATING_INCOME, ValueState.NOT_APPLICABLE)])
def test_au_aw_missing_and_not_applicable_are_states_not_zero(w: World, field, state) -> None:
    result = resolve(w, q_actual(w, field, subject=w.ids.I2.issuer_id), at(2025, 6, 1))
    assert result.status is ObservationStatus.FOUND and result.record.value.state is state
    assert result.record.value.amount is None and result.as_dict()["record"]["payload"]["value"]["amount"] is None


def test_av_not_reported_is_not_zero(w: World) -> None:
    result = resolve(w, q_actual(w, F.OPERATING_CASH_FLOW, Q1C25), at(2025, 9, 1))
    assert result.record.value.state is ValueState.NOT_REPORTED and result.record.value.amount is None
    no_record = resolve(w, q_actual(w, F.EQUITY, Q1C25), at(2025, 9, 1))
    assert no_record.status is ObservationStatus.NOT_FOUND                                   # 記録が無いことも 0 にしない


def test_au_to_aw_absent_states_cannot_carry_an_amount() -> None:
    for state in (ValueState.MISSING, ValueState.NOT_REPORTED, ValueState.NOT_APPLICABLE):
        with pytest.raises(ObservationModelError) as exc:
            ObservationValue(state, Measure.MONETARY_AMOUNT, "0")
        assert exc.value.code == "ABSENT_VALUE_HAS_AMOUNT"
    with pytest.raises(ObservationModelError):
        ObservationValue.absent(Measure.MONETARY_AMOUNT, ValueState.VALUE_PRESENT)


# ================================================================ AX〜AZ 出所


def test_ax_bounded_provenance_is_retained(w: World, tmp_path: Path) -> None:
    write_world(tmp_path, w)
    result = orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE, basis=ADJ), cutoff=at(2025, 12, 1))
    provenance = result.as_dict()["record"]["provenance"]
    assert provenance == {"adjustment_ref": "jq:adj-v2", "source_class": "JQUANTS", "source_field": "Close",
                          "source_record_ref": "jq:bars-2025-06-02"}


@pytest.mark.parametrize("ref", ["", " jq", "jq rec", "{\"Close\": 1}", "x" * 161, "line1\nline2", "a=b"])
def test_ay_no_raw_payload(ref: str) -> None:
    with pytest.raises(ObservationModelError) as exc:
        src(JQS, ref)
    assert ref not in str(exc.value) or ref == ""
    with pytest.raises(ObservationModelError):
        src(JQS, "jq:1", "Close Price")                                                      # 欄の名前も token だけ


@pytest.mark.parametrize("ref", ["C:\\data\\x", "/var/lib/x", "../x", "file:///srv/x", "https://example.test/a",
                                 "token:abc", "api_key:1", "password:x", "secret:1", "bearer:x", "X-API-KEY:1"])
def test_az_no_path_or_credential(ref: str) -> None:
    for build in (lambda: src(JQS, ref), lambda: src(JQS, "jq:1", "C", ref)):
        with pytest.raises(ObservationModelError) as exc:
            build()
        assert ref not in str(exc.value)


# ================================================================ BA〜BE store


def test_ba_an_exact_duplicate_converges(w: World, tmp_path: Path) -> None:
    _, store = write_world(tmp_path, w)
    before = store.path.read_bytes()
    for record in (w.close, w.f2, w.market_cover):
        assert store.append(record).status is ost.AppendStatus.ALREADY_PRESENT
        again = type(record)(**{f.name: getattr(record, f.name) for f in fields(record)})
        assert store.append(again).status is ost.AppendStatus.ALREADY_PRESENT
    assert store.path.read_bytes() == before


def test_bb_conflicts_and_forks_are_rejected(w: World, tmp_path: Path) -> None:
    _, store = write_world(tmp_path, w)
    before = store.path.read_bytes()
    k = ts(2026, 8, 1)
    cases = {
        "FORK": market(w.ids.S1, MarketField.CLOSE, price("1051"), D0602, ts(2025, 6, 2, 9)),       # 2 本目の root
        "FORK_OF_REVISION": actual(w.ids.I1.issuer_id, F.REVENUE, money("497000"), FY24, k,
                                   supersedes=w.revenue.record_id),                              # 末尾でない前を指す
        "PREDECESSOR_WRONG_SLOT": actual(w.ids.I1.issuer_id, F.EQUITY, money("1"), FY24, k,
                                         supersedes=w.revenue_restated.record_id),
        "UNKNOWN_PREDECESSOR": actual(w.ids.I1.issuer_id, F.EQUITY, money("1"), FY24, k,
                                      supersedes="p8obs_" + "0" * 24),
        "NON_MONOTONIC_KNOWLEDGE": actual(w.ids.I1.issuer_id, F.REVENUE, money("1"), FY24, ts(2025, 11, 1),
                                          supersedes=w.revenue_restated.record_id),
    }
    for code, record in cases.items():
        with pytest.raises(ost.ObservationAppendRejected) as exc:
            store.append(record)
        assert exc.value.code == code.replace("_OF_REVISION", ""), code
    assert store.path.read_bytes() == before


def _rewrite(path: Path, lines) -> None:
    path.write_bytes("".join(lines).encode("utf-8"))


@pytest.mark.parametrize("damage,reason", [
    ("fork", "INVALID_HISTORY"), ("physical_duplicate", "PHYSICAL_DUPLICATE"), ("truncated", "TRUNCATED_FINAL_LINE"),
    ("blank", "BLANK_LINE"), ("non_canonical", "INVALID_RECORD"), ("tampered_amount", "INVALID_RECORD"),
    ("invalid_utf8", "INVALID_ENCODING"), ("unknown_subject", "INVALID_HISTORY"), ("reordered", "INVALID_HISTORY"),
    ("contradiction", "INVALID_HISTORY")])
def test_bc_corruption_is_detected(w: World, tmp_path: Path, damage: str, reason: str) -> None:
    _, store = write_world(tmp_path, w)
    lines = list(store.canonical_lines())
    path = store.path
    if damage == "fork":
        lines.append(market(w.ids.S1, MarketField.CLOSE, price("1051"), D0602, ts(2026, 8, 1)).canonical_line())
    elif damage == "physical_duplicate":
        lines.append(lines[2])
    elif damage == "truncated":
        lines[-1] = lines[-1][:-3]
    elif damage == "blank":
        lines.insert(1, "\n")
    elif damage == "non_canonical":
        lines[0] = json.dumps(json.loads(lines[0]), sort_keys=True) + "\n"
    elif damage == "tampered_amount":
        lines[3] = lines[3].replace('"amount":"1050"', '"amount":"1049"')
    elif damage == "invalid_utf8":
        path.write_bytes(path.read_bytes() + b"\xff\n")
        lines = None
    elif damage == "unknown_subject":
        stranger = im.SecurityRegistration(registration_anchor="hr:never-registered", issuer_id=w.ids.I1.issuer_id,
                                           issue_class=im.IssueClass.COMMON_EQUITY,
                                           provenance=w.ids.S1.provenance)
        lines.append(market(stranger, MarketField.CLOSE, price("1"), D0602, ts(2026, 8, 1)).canonical_line())
    elif damage == "reordered":
        lines.insert(0, lines.pop(lines.index(w.adj_close_split.canonical_line())))              # revision が前より先
    elif damage == "contradiction":
        lines.append(market(w.ids.S1, MarketField.CLOSE, price("1"), date(2025, 7, 1),
                            ts(2025, 7, 1, 9)).canonical_line())                                   # 完全と宣言した範囲の後出し
    if lines is not None:
        _rewrite(path, lines)
    with pytest.raises(ost.ObservationStoreCorrupt) as exc:
        ost.ObservationStore.open(tmp_path, read_only=True)
    assert exc.value.code == reason and str(tmp_path) not in str(exc.value)
    result = orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE), cutoff=at(2025, 12, 1))
    assert result.status is ObservationStatus.STORE_CORRUPTION and result.record is None


def test_bc_a_coverage_contradiction_is_rejected_on_append(w: World, tmp_path: Path) -> None:
    _, store = write_world(tmp_path, w)
    with pytest.raises(ost.ObservationAppendRejected) as exc:
        store.append(market(w.ids.S1, MarketField.CLOSE, price("1"), date(2025, 7, 1), ts(2025, 7, 1, 9)))
    assert exc.value.code == "COVERAGE_CONTRADICTION"
    later = actual(w.ids.I1.issuer_id, F.REVENUE, money("497000"), FY24, ts(2026, 8, 1),
                   supersedes=w.revenue_restated.record_id)
    assert store.append(later).status is ost.AppendStatus.APPENDED                          # 範囲の知識より後は足せる
    assert orr.resolve_at_data_root(tmp_path, q_actual(w, F.REVENUE), cutoff=at(2026, 8, 2)).status is \
        ObservationStatus.NOT_YET_KNOWN                                                     # 取り込みが cutoff に未達
    store.append(coverage(om.CoverageDataset.FUNDAMENTAL_DISCLOSURE, date(2024, 1, 1), date(2027, 1, 1),
                          at(2026, 9, 1)))
    assert orr.resolve_at_data_root(tmp_path, q_actual(w, F.REVENUE), cutoff=at(2026, 8, 2)).record.value.amount == \
        "497000"


def test_bd_no_automatic_repair(w: World, tmp_path: Path) -> None:
    _, store = write_world(tmp_path, w)
    damaged = store.path.read_bytes()[:-2]
    store.path.write_bytes(damaged)
    for _ in range(3):
        with pytest.raises(ost.ObservationStoreCorrupt):
            ost.ObservationStore.open(tmp_path)
        with pytest.raises(ost.ObservationStoreCorrupt):
            ost.ObservationStore.initialize(tmp_path)
        orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE), cutoff=at(2025, 12, 1))
    assert store.path.read_bytes() == damaged


def test_be_the_store_is_append_only(w: World, tmp_path: Path) -> None:
    identity = ist.IdentityStore.initialize(tmp_path)
    for record in w.ids.records:
        identity.append(record)
    store = ost.ObservationStore.initialize(tmp_path)
    previous = b""
    for record in w.records:
        store.append(record)
        current = store.path.read_bytes()
        assert current.startswith(previous) and current != previous
        previous = current
    public = {n for n in dir(ost.ObservationStore) if not n.startswith("_")}
    assert not public & {"delete", "remove", "update", "replace", "rewrite", "truncate", "compact", "repair",
                         "migrate", "set", "put", "latest"}
    with pytest.raises(ost.ObservationAppendRejected) as ro:
        ost.ObservationStore.open(tmp_path, read_only=True).append(w.close)
    assert ro.value.code == "READ_ONLY"
    other = ost.ObservationStore.open(tmp_path)
    store.path.write_bytes(store.path.read_bytes() + w.close.canonical_line().encode())
    with pytest.raises(ost.ObservationConcurrentModification):
        other.append(market(w.ids.S1, MarketField.OPEN, price("2"), date(2026, 2, 2), ts(2026, 8, 1)))


# ================================================================ BF〜BJ 解決の入力


def test_bf_an_explicit_cutoff_is_required(w: World, tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        orr.resolve(w.history(), q_market(w, MarketField.CLOSE))                               # type: ignore[call-arg]
    for bad in (None, "2025-06-03", date(2025, 6, 3), 0):
        with pytest.raises(ObservationModelError) as exc:
            orr.resolve(w.history(), q_market(w, MarketField.CLOSE), cutoff=bad)
        assert exc.value.code == "CUTOFF_REQUIRED" or isinstance(bad, date)
    with pytest.raises(ObservationModelError):
        orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE), cutoff=None)


def test_bg_a_naive_cutoff_is_rejected(w: World, tmp_path: Path) -> None:
    for call in (lambda: orr.resolve(w.history(), q_market(w, MarketField.CLOSE), cutoff=datetime(2025, 6, 3)),
                 lambda: orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE),
                                                  cutoff=datetime(2025, 6, 3))):
        with pytest.raises(ObservationModelError) as exc:
            call()
        assert exc.value.code == "NAIVE_DATETIME"


def test_bh_there_is_no_implicit_now_or_latest(w: World) -> None:
    import inspect
    for function in (orr.resolve, orr.resolve_at_data_root):
        cutoff = inspect.signature(function).parameters["cutoff"]
        assert cutoff.default is inspect.Parameter.empty and cutoff.kind is inspect.Parameter.KEYWORD_ONLY
    names = {n.lower() for module in (om, orr, ost) for n in dir(module)}
    assert not {n for n in names if "latest" in n or n.endswith("_now") or n == "now" or "current_value" in n}
    with pytest.raises(ObservationModelError):
        ObservationQuery.market(w.ids.S1.security_id, MarketField.CLOSE, RAW, None)          # 日を省けない


def test_bi_a_record_known_after_the_cutoff_never_affects_the_answer(w: World) -> None:
    queries = [q_market(w, MarketField.CLOSE, basis=ADJ), q_actual(w, F.REVENUE), q_forecast(w),
               q_actual(w, F.REVENUE, FY25), q_actual(w, F.NET_INCOME, source=JQS)]
    for cutoff in (at(2025, 6, 1), at(2025, 8, 31), at(2025, 12, 1), at(2026, 6, 1)):
        visible = [r for r in w.records if isinstance(r, ObservationCoverage) or r.knowledge.earliest <= cutoff]
        for query in queries:
            full = orr.resolve(w.history(), query, cutoff=cutoff).canonical_json()
            assert full == orr.resolve(w.history(visible), query, cutoff=cutoff).canonical_json()


def test_bj_ambiguity_fails_closed(w: World) -> None:
    both = resolve(w, q_actual(w, F.NET_INCOME), at(2025, 6, 1))
    assert both.status is ObservationStatus.AMBIGUOUS and both.record is None
    assert both.candidates == tuple(sorted([w.net_income.record_id, w.net_income_disclosure.record_id]))
    chosen = resolve(w, q_actual(w, F.NET_INCOME, source=DISC), at(2025, 6, 1))
    assert chosen.status is ObservationStatus.FOUND and chosen.record == w.net_income_disclosure
    only_one_known = resolve(w, q_actual(w, F.NET_INCOME), at(2025, 5, 12, 6, 1))
    assert only_one_known.status is ObservationStatus.FOUND and only_one_known.record == w.net_income_disclosure


# ================================================================ BK〜BQ status


def test_bk_found(w: World) -> None:
    result = resolve(w, q_market(w, MarketField.CLOSE), at(2025, 6, 3))
    assert result.status is ObservationStatus.FOUND and result.identity_status == "FOUND"
    assert result.coverage_record_ids == (w.market_cover.record_id,)


def test_bl_not_found_inside_coverage(w: World) -> None:
    result = resolve(w, q_market(w, MarketField.CLOSE, date(2025, 6, 4)), at(2025, 6, 10))
    assert result.status is ObservationStatus.NOT_FOUND and result.coverage_record_ids == (w.market_cover.record_id,)


def test_bm_not_yet_known_when_capture_does_not_reach_the_cutoff(w: World) -> None:
    result = resolve(w, q_market(w, MarketField.CLOSE), CAPTURE + timedelta(seconds=1))
    assert result.status is ObservationStatus.NOT_YET_KNOWN and result.record is None


def test_bn_insufficient_time_precision(w: World) -> None:
    result = resolve(w, q_market(w, MarketField.CLOSE, D0603), at(2025, 6, 3, 10))
    assert result.status is ObservationStatus.INSUFFICIENT_TIME_PRECISION and result.record is None


def test_bo_authority_missing(w: World, tmp_path: Path) -> None:
    missing_all = orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE), cutoff=at(2025, 6, 3))
    assert missing_all.status is ObservationStatus.AUTHORITY_MISSING
    assert missing_all.diagnostic == "IDENTITY_AUTHORITY_MISSING"
    with pytest.raises(ost.ObservationAuthorityMissing):
        ost.ObservationStore.initialize(tmp_path)
    assert list(tmp_path.iterdir()) == []                                                    # 何も作らない
    identity = ist.IdentityStore.initialize(tmp_path)
    for record in w.ids.records:
        identity.append(record)
    only_identity = orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE), cutoff=at(2025, 6, 3))
    assert only_identity.status is ObservationStatus.AUTHORITY_MISSING and only_identity.diagnostic == "AUTHORITY_MISSING"


def test_bp_store_corruption_includes_a_corrupt_identity_authority(w: World, tmp_path: Path) -> None:
    identity, _ = write_world(tmp_path, w)
    identity.path.write_bytes(identity.path.read_bytes()[:-1])
    result = orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE), cutoff=at(2025, 6, 3))
    assert result.status is ObservationStatus.STORE_CORRUPTION
    assert result.diagnostic.startswith("IDENTITY_STORE_CORRUPTION:") and str(tmp_path) not in result.diagnostic


@pytest.mark.parametrize("session,expected", [(date(2024, 7, 1), "NOT_ACTIVE_AT_CUTOFF"), (D0602, "NOT_FOUND")])
def test_bq_subject_not_resolved(w: World, session: date, expected: str) -> None:
    sec = w.ids.S3 if session.year == 2024 else w.ids.S4
    result = resolve(w, q_market(w, MarketField.CLOSE, session, sec=sec), at(2026, 3, 1))
    assert result.status is ObservationStatus.SUBJECT_NOT_RESOLVED and result.record is None
    assert result.identity_status == expected
    listed = resolve(w, q_market(w, MarketField.CLOSE, date(2024, 6, 28), sec=w.ids.S3), at(2026, 3, 1))
    assert listed.status is ObservationStatus.BEFORE_COVERAGE and listed.identity_status == "FOUND"


# ================================================================ BR〜BV identity ・書き込み 0


def test_br_bs_bt_subjects_are_validated_against_the_a1_authority(w: World, tmp_path: Path) -> None:
    write_world(tmp_path, w)
    store = ost.ObservationStore.open(tmp_path)
    unknown_issuer = im.derive_issuer_id("hr:never-registered-issuer")
    unknown_security = im.derive_security_id("hr:never-registered-security")
    cases = [actual(unknown_issuer, F.REVENUE, money("1"), FY24, ts(2026, 8, 1)),
             forecast(unknown_issuer, F.REVENUE, money("1"), FY25, ts(2026, 8, 1)),
             MarketObservation(security_id=unknown_security, field=MarketField.CLOSE, basis=RAW,
                               session_date=date(2026, 2, 2), value=price("1"), knowledge=ts(2026, 8, 1),
                               provenance=src()),
             actual(unknown_security, F.SHARES_OUTSTANDING, shares("1"), FY24, ts(2026, 8, 1))]
    for record in cases:
        with pytest.raises(ost.ObservationAppendRejected) as exc:
            store.append(record)
        assert exc.value.code == "UNKNOWN_SUBJECT"
    with pytest.raises(ObservationHistoryError):
        ObservationHistory(IdentityHistory(), [w.close])                                      # identity の無い主語は拒否
    with pytest.raises(ObservationHistoryError):
        ObservationHistory(None, [])                                                          # type: ignore[arg-type]


def _snapshot(root: Path) -> dict:
    return {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}


def test_bu_a2_never_writes_the_a1_authority(w: World, tmp_path: Path) -> None:
    identity, store = write_world(tmp_path, w)
    before = (identity.path.stat().st_mtime_ns, identity.path.read_bytes())
    store.append(coverage(om.CoverageDataset.MARKET_DAILY, date(2026, 1, 1), date(2027, 1, 1), at(2026, 9, 1)))
    ost.ObservationStore.open(tmp_path).reload()
    orr.resolve_at_data_root(tmp_path, q_market(w, MarketField.CLOSE), cutoff=at(2025, 6, 3))
    assert (identity.path.stat().st_mtime_ns, identity.path.read_bytes()) == before


def test_bv_resolution_is_zero_write_and_replays_byte_identically(w: World, tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    write_world(tmp_path, w)
    snapshot = _snapshot(tmp_path)
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in "wax+"), mode
        return real_open(file, mode, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("write attempted")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    for attr in ("mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir", "fsync", "utime", "truncate"):
        if hasattr(os, attr):
            monkeypatch.setattr(os, attr, forbidden)
    for attr in ("mkdir", "write_bytes", "write_text", "touch"):
        monkeypatch.setattr(Path, attr, forbidden)
    queries = [q_market(w, MarketField.CLOSE, basis=ADJ), q_actual(w, F.REVENUE), q_forecast(w),
               q_actual(w, F.NET_INCOME), q_market(w, MarketField.CLOSE, D0603)]
    runs = [[orr.resolve_at_data_root(tmp_path, q, cutoff=cutoff).canonical_json()
             for q in queries for cutoff in (at(2025, 6, 3, 10), at(2025, 9, 2), at(2026, 6, 1))] for _ in range(3)]
    monkeypatch.undo()
    assert runs[0] == runs[1] == runs[2]
    assert _snapshot(tmp_path) == snapshot


def test_bv_a_resolution_can_never_become_a_record(w: World, tmp_path: Path) -> None:
    _, store = write_world(tmp_path, w)
    result = orr.resolve(store.history, q_forecast(w), cutoff=at(2025, 12, 1))
    assert result.authority_class == orr.DERIVED_NON_AUTHORITY_NON_PERSISTENT
    with pytest.raises(ost.ObservationAppendRejected) as exc:
        store.append(result)
    assert exc.value.code == "INVALID_TYPE"
    with pytest.raises(ObservationModelError):
        om.parse_observation_record(result.as_dict())


# ================================================================ BW〜BX coverage


def test_bw_before_coverage_fails_closed(w: World) -> None:
    history = w.history([*w.records, ])
    early = market(w.ids.S1, MarketField.CLOSE, price("1000"), date(2024, 12, 30), ts(2024, 12, 30, 9))
    with_early = w.history([early, *w.records])
    for source in (history, with_early):                                                     # record があっても答えない
        result = orr.resolve(source, q_market(w, MarketField.CLOSE, date(2024, 12, 30)), cutoff=at(2025, 6, 1))
        assert result.status is ObservationStatus.BEFORE_COVERAGE and result.record is None


def test_bx_outside_coverage_is_distinct_from_no_match(w: World) -> None:
    outside = resolve(w, q_market(w, MarketField.CLOSE, date(2026, 1, 5)), at(2026, 2, 1))
    inside = resolve(w, q_market(w, MarketField.CLOSE, date(2025, 12, 30)), at(2026, 2, 1))
    assert outside.status is ObservationStatus.OUTSIDE_COVERAGE and inside.status is ObservationStatus.NOT_FOUND
    bare = w.history([r for r in w.records if not isinstance(r, ObservationCoverage)])
    assert orr.resolve(bare, q_market(w, MarketField.CLOSE), cutoff=at(2025, 6, 3)).status is \
        ObservationStatus.OUTSIDE_COVERAGE                                                   # 宣言が無ければ答えない


# ================================================================ CM〜CP 決定論


#: 導出の規則が変わったら落ちる固定値
PINNED_CLOSE_RECORD_ID = "p8obs_4ed814b8923a2d7db3b4447d"


def test_cm_record_ids_are_deterministic(w: World) -> None:
    assert [r.record_id for r in World().records] == [r.record_id for r in w.records]
    assert len({r.record_id for r in w.records}) == len(w.records)
    assert w.close.record_id == PINNED_CLOSE_RECORD_ID
    later = replace(w.close, knowledge=ts(2025, 6, 2, 8, 11))
    assert later.record_id != w.close.record_id                                               # 知識の時刻は意味の一部


def test_cn_input_order_is_non_semantic(w: World) -> None:
    independent = [w.open, w.high, w.low, w.volume, w.eps, w.equity, w.i2_net_zero]
    rest = [r for r in w.records if r not in independent]
    queries = [q_market(w, MarketField.OPEN), q_actual(w, F.EPS), q_actual(w, F.NET_INCOME, subject=w.ids.I2.issuer_id),
               q_market(w, MarketField.CLOSE, basis=ADJ)]
    answers = set()
    for order in itertools.islice(itertools.permutations(independent), 0, 120, 7):
        history = w.history([*order, *rest])
        answers.add(tuple(orr.resolve(history, q, cutoff=at(2025, 12, 1)).canonical_json() for q in queries))
    assert len(answers) == 1


def test_co_paths_and_mtimes_do_not_matter(w: World, tmp_path: Path) -> None:
    roots = [tmp_path / "one", tmp_path / "nested" / "two"]
    for root in roots:
        write_world(root, w)
    os.utime(ost.observation_path(roots[1]), (1, 1))
    assert len({ost.ObservationStore.open(root, read_only=True).canonical_lines() for root in roots}) == 1
    answers = {orr.resolve_at_data_root(root, q_forecast(w), cutoff=at(2025, 12, 1)).canonical_json() for root in roots}
    assert len(answers) == 1 and not any(str(root) in next(iter(answers)) for root in roots)


def test_cp_no_clock_or_randomness_in_identity() -> None:
    code = ("from datetime import date, datetime, timezone\n"
            "from src.intelligence.screener_intelligence import observation_model as om\n"
            "from src.intelligence.screener_intelligence import identity_model as im\n"
            "v = om.ObservationValue.present(om.Measure.PRICE, '1050', currency=om.Currency.JPY)\n"
            "p = om.ObservationProvenance(source_class=im.SourceClass.JQUANTS, source_record_ref='jq:bars-2025-06-02',"
            " source_field='Close')\n"
            "r = om.MarketObservation(security_id=im.derive_security_id('hr:obs-security-one'),"
            " field=om.MarketField.CLOSE, basis=om.PriceBasis.RAW_REPORTED, session_date=date(2025, 6, 2), value=v,"
            " knowledge=om.KnowledgeTime.exact(datetime(2025, 6, 2, 8, 10, tzinfo=timezone.utc)), provenance=p)\n"
            "print(r.record_id)\n")
    outputs = {subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                              env={"PYTHONPATH": str(REPO_ROOT), "PATH": "", "PYTHONHASHSEED": seed}).stdout.strip()
               for seed in ("0", "1", "4242")}
    assert outputs == {PINNED_CLOSE_RECORD_ID}
