"""P8-A3A — 決定論の財務の指標（売上成長率 ・営業利益率）の test matrix A〜E（境界 ／ 凍結は `test_screener_intelligence_boundary.py`）。

すべて合成の観測（A2 の凍結の test の合成の identity ・架空の値）。J-Quants ・network ・実データ ・LLM ・時計 ・乱数は使わない。
A1 ・A2 ・A1R ・A2R の module は変えない。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import fundamental_metrics as fm
from src.intelligence.screener_intelligence import metric_model as mm
from src.intelligence.screener_intelligence.identity_model import SourceClass
from src.intelligence.screener_intelligence.metric_model import (MetricKind, MetricLeg, MetricPeriodLabel,
                                                                 MetricReason, MetricResult, MetricStatus,
                                                                 ReasonCode)
from src.intelligence.screener_intelligence.observation_model import (CoverageDataset, FundamentalActual,
                                                                      FundamentalField, KnowledgeTime,
                                                                      ObservationHistory, PeriodBasis,
                                                                      ReportingPeriod, Scale, StatementBasis,
                                                                      ValueState)
from src.intelligence.screener_intelligence.observation_semantics_mapping import derive_observation_semantics
from src.intelligence.screener_intelligence.observation_semantics_model import FieldFamily
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_observation import (Identity, absent, at, coverage, money, on, src, ts)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
JST = timezone(timedelta(hours=9))
CONS, NONCONS = StatementBasis.CONSOLIDATED, StatementBasis.NON_CONSOLIDATED
REV, OP = FundamentalField.REVENUE, FundamentalField.OPERATING_INCOME
JP_CONS, IFRS_CONS, US_CONS = ("FYFinancialStatements_Consolidated_JP", "FYFinancialStatements_Consolidated_IFRS",
                               "FYFinancialStatements_Consolidated_US")
JP_NONCONS, IFRS_NONCONS, FOREIGN = ("FYFinancialStatements_NonConsolidated_JP",
                                     "FYFinancialStatements_NonConsolidated_IFRS",
                                     "FYFinancialStatements_Consolidated_Foreign")


def jst(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=JST)


def fy(year: int) -> ReportingPeriod:
    return ReportingPeriod(PeriodBasis.FISCAL_YEAR, date(year, 4, 1), date(year + 1, 3, 31), date(year, 4, 1),
                           date(year + 1, 3, 31))


def q(year: int, quarter: int) -> ReportingPeriod:
    end = {1: date(year, 6, 30), 2: date(year, 9, 30), 3: date(year, 12, 31)}[quarter]
    return ReportingPeriod(PeriodBasis.CUMULATIVE_YEAR_TO_DATE, date(year, 4, 1), date(year + 1, 3, 31),
                           date(year, 4, 1), end, quarter)


FY21, FY22, FY23, FY24, FY25 = fy(2021), fy(2022), fy(2023), fy(2024), fy(2025)
Q1_24, Q1_25, Q2_25 = q(2024, 1), q(2025, 1), q(2025, 2)
SINGLE_Q2_25 = ReportingPeriod(PeriodBasis.SINGLE_QUARTER, date(2025, 4, 1), date(2026, 3, 31), date(2025, 7, 1),
                               date(2025, 9, 30), 2)
LONG_FY = ReportingPeriod(PeriodBasis.FISCAL_YEAR, date(2024, 4, 1), date(2025, 6, 30), date(2024, 4, 1),
                          date(2025, 6, 30))                                          # 15 か月の年度（決算期の変更）
IDS = Identity()
I1, I2 = IDS.I1.issuer_id, IDS.I2.issuer_id
K_FY23, K_FY24, K_RESTATED, K_FY25 = ts(2024, 5, 10, 6), ts(2025, 5, 12, 6), ts(2025, 11, 14, 6), ts(2026, 5, 13, 6)
C_2025_06 = at(2025, 6, 1)                     # FY24 の元の値だけが知られている cutoff
C_2025_12 = at(2025, 12, 1)                    # FY24 の訂正が知られている cutoff
C_2026_06 = at(2026, 6, 1)


def rec(issuer: str, field: FundamentalField, amount, period: ReportingPeriod, known: KnowledgeTime, *,
        basis: StatementBasis = CONS, supersedes: str = "", scale: Scale = Scale.MILLION,
        source: SourceClass = SourceClass.JQUANTS) -> FundamentalActual:
    value = amount if not isinstance(amount, str) else money(amount, scale)
    return FundamentalActual(subject=issuer, field=field, statement_basis=basis, period=period, value=value,
                             knowledge=known, provenance=src(source, "jq:fs-0001", field.value.title()),
                             supersedes=supersedes)


class World:
    """合成の財務の観測。I1 は JP 基準 ・連結。I2 は端の場合（売上 0 ・欠損）。"""

    def __init__(self) -> None:
        self.rev23 = rec(I1, REV, "400000", FY23, K_FY23)
        self.op23 = rec(I1, OP, "30000", FY23, K_FY23)
        self.rev24 = rec(I1, REV, "500000", FY24, K_FY24)
        self.op24 = rec(I1, OP, "40000", FY24, K_FY24)
        self.rev24_restated = rec(I1, REV, "498000", FY24, K_RESTATED, supersedes=self.rev24.record_id)
        self.rev25 = rec(I1, REV, "505000", FY25, K_FY25)
        self.q1_24 = rec(I1, REV, "120000", Q1_24, ts(2024, 8, 8, 6))
        self.q1_25 = rec(I1, REV, "130000", Q1_25, on(2025, 8, 8))                    # 日付だけの知識
        self.q1_25_op = rec(I1, OP, "9100", Q1_25, on(2025, 8, 8))
        self.q2_25 = rec(I1, REV, "260000", Q2_25, ts(2025, 11, 14, 6))
        self.rev23_noncons = rec(I1, REV, "300000", FY23, K_FY23, basis=NONCONS)
        self.rev24_noncons = rec(I1, REV, "330000", FY24, K_FY24, basis=NONCONS)
        self.i2_rev23_zero = rec(I2, REV, "0", FY23, K_FY23)
        self.i2_rev24 = rec(I2, REV, "1000", FY24, K_FY24)
        self.i2_op24 = rec(I2, OP, "-50", FY24, K_FY24)
        self.i2_rev22 = rec(I2, REV, "900", FY22, ts(2023, 5, 10, 6))
        self.i2_op22 = rec(I2, OP, "0", FY22, ts(2023, 5, 10, 6))
        self.i2_rev21_missing = rec(I2, REV, absent(REV, ValueState.MISSING), FY21, ts(2022, 5, 10, 6))
        self.i2_op21 = rec(I2, OP, "10", FY21, ts(2022, 5, 10, 6))
        self.i2_rev22_zero_only_op = rec(I2, REV, "0", FY22, ts(2023, 5, 10, 6), basis=NONCONS)
        self.i2_op22_noncons = rec(I2, OP, "7", FY22, ts(2023, 5, 10, 6), basis=NONCONS)
        self.cover = coverage(CoverageDataset.FUNDAMENTAL_DISCLOSURE, date(2022, 1, 1), date(2027, 1, 1),
                              at(2026, 6, 30))
        self.records = [self.rev23, self.op23, self.rev24, self.op24, self.rev24_restated, self.rev25, self.q1_24,
                        self.q1_25, self.q1_25_op, self.q2_25, self.rev23_noncons, self.rev24_noncons,
                        self.i2_rev23_zero, self.i2_rev24, self.i2_op24, self.i2_rev22, self.i2_op22,
                        self.i2_rev21_missing, self.i2_op21, self.i2_rev22_zero_only_op, self.i2_op22_noncons,
                        self.cover]

    def history(self, records=None) -> ObservationHistory:
        return ObservationHistory(IDS.history(), self.records if records is None else records)

    def semantics(self, overrides=None) -> dict:
        """既定はすべて JP 基準（単体の record は NonConsolidated_JP）。`overrides` は record → DocType。"""
        lookup = {}
        for record in self.records:
            if record.KIND.value != "FUNDAMENTAL_ACTUAL":
                continue
            doc = (overrides or {}).get(record.record_id, JP_NONCONS if record.statement_basis is NONCONS else JP_CONS)
            lookup[record.record_id] = derive_observation_semantics(record.record_id, doc,
                                                                    FieldFamily.UNPREFIXED_ACTUAL)[0]
        return lookup


@pytest.fixture()
def w() -> World:
    return World()


def growth(w: World, target=FY24, comparison=FY23, *, cutoff=C_2025_06, issuer=I1, basis=CONS, semantics=None,
           history=None, **extra) -> MetricResult:
    return fm.revenue_growth(w.history() if history is None else history, issuer_id=issuer, statement_basis=basis,
                             target_period=target, comparison_period=comparison, cutoff=cutoff,
                             semantics=w.semantics() if semantics is None else semantics, **extra)


def margin(w: World, period=FY24, *, cutoff=C_2025_06, issuer=I1, basis=CONS, semantics=None, history=None,
           **extra) -> MetricResult:
    return fm.operating_margin(w.history() if history is None else history, issuer_id=issuer, statement_basis=basis,
                               period=period, cutoff=cutoff,
                               semantics=w.semantics() if semantics is None else semantics, **extra)


def reasons(result: MetricResult) -> list:
    return [reason.as_text() for reason in result.reasons]


# ================================================================ A 売上成長率


def test_a_fy_to_fy_positive_growth(w: World) -> None:
    result = growth(w)
    assert result.status is MetricStatus.VALUE and result.value == "0.25" and result.reasons == ()
    assert result.metric is MetricKind.REVENUE_GROWTH and result.period_label is MetricPeriodLabel.FISCAL_YEAR
    assert result.quarter == 0 and result.input_record_ids == (w.rev24.record_id, w.rev23.record_id)
    assert result.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT" and result.rules_version == \
        mm.METRIC_RULES_VERSION


def test_a_negative_and_zero_growth(w: World) -> None:
    assert growth(w, target=FY23, comparison=FY24, cutoff=C_2025_12).status is MetricStatus.NOT_COMPARABLE  # 逆の並び
    history = w.history([rec(I1, REV, "500000", FY23, K_FY23), w.rev24, w.cover])
    semantics = w.semantics()
    down = rec(I1, REV, "500000", FY23, K_FY23)
    semantics[down.record_id] = derive_observation_semantics(down.record_id, JP_CONS, FieldFamily.UNPREFIXED_ACTUAL)[0]
    assert growth(w, history=history, semantics=semantics).value == "0"                  # 500000 → 500000
    lower = rec(I1, REV, "400000", FY24, K_FY24)
    semantics[lower.record_id] = derive_observation_semantics(lower.record_id, JP_CONS,
                                                              FieldFamily.UNPREFIXED_ACTUAL)[0]
    history = w.history([down, lower, w.cover])
    assert growth(w, history=history, semantics=semantics).value == "-0.2"                # 500000 → 400000


def test_a_prior_revenue_zero_is_undefined_not_a_value(w: World) -> None:
    result = growth(w, issuer=I2)
    assert result.status is MetricStatus.UNDEFINED and reasons(result) == ["PAIR:DENOMINATOR_ZERO"]
    assert result.value is None and result.period_label is None


def test_a_missing_prior_is_insufficient_data(w: World) -> None:
    result = growth(w, target=FY23, comparison=FY22)                                     # I1 の FY22 は無い
    assert result.status is MetricStatus.INSUFFICIENT_DATA and reasons(result) == ["COMPARISON:NOT_FOUND"]
    before = growth(w, target=FY22, comparison=FY21, issuer=I2, cutoff=C_2025_12)
    assert "COMPARISON:VALUE_ABSENT" in reasons(before)                                  # FY21 は MISSING の値
    assert growth(w, target=fy(2020), comparison=fy(2019), issuer=I2).reasons[0].code is ReasonCode.BEFORE_COVERAGE


def test_a_different_issuer_is_not_comparable(w: World) -> None:
    result = growth(w, comparison_issuer_id=I2)
    assert result.status is MetricStatus.NOT_COMPARABLE and reasons(result) == ["PAIR:SUBJECT_DIFFERS"]


def test_a_semantic_discontinuity_jp_gaap_to_ifrs_is_not_comparable_in_both_directions(w: World) -> None:
    ifrs_target = w.semantics({w.rev24.record_id: IFRS_CONS})                             # FY23 JP → FY24 IFRS
    result = growth(w, semantics=ifrs_target)
    assert result.status is MetricStatus.NOT_COMPARABLE and reasons(result) == ["PAIR:ACCOUNTING_STANDARD_DIFFERS"]
    assert result.value is None
    ifrs_prior = w.semantics({w.rev23.record_id: IFRS_CONS})                              # FY23 IFRS → FY24 JP
    assert reasons(growth(w, semantics=ifrs_prior)) == ["PAIR:ACCOUNTING_STANDARD_DIFFERS"]
    us = w.semantics({w.rev23.record_id: US_CONS})
    assert reasons(growth(w, semantics=us)) == ["PAIR:ACCOUNTING_STANDARD_DIFFERS"]
    both_ifrs = w.semantics({w.rev23.record_id: IFRS_CONS, w.rev24.record_id: IFRS_CONS})  # 同じ基準なら比べられる
    assert growth(w, semantics=both_ifrs).value == "0.25"


def test_a_different_statement_basis_is_not_comparable(w: World) -> None:
    result = growth(w, comparison_statement_basis=NONCONS)
    assert result.status is MetricStatus.NOT_COMPARABLE and reasons(result) == ["PAIR:STATEMENT_BASIS_DIFFERS"]
    assert growth(w, basis=NONCONS).value == "0.1"                                        # 単体どうしなら比べられる


def test_a_unknown_standard_or_basis_fails_closed(w: World) -> None:
    foreign = growth(w, semantics=w.semantics({w.rev24.record_id: FOREIGN}))
    assert foreign.status is MetricStatus.NOT_COMPARABLE and reasons(foreign) == ["TARGET:ACCOUNTING_STANDARD_UNKNOWN"]
    unknown_basis = growth(w, basis=NONCONS, semantics=w.semantics({w.rev23_noncons.record_id: IFRS_NONCONS}))
    assert unknown_basis.status is MetricStatus.NOT_COMPARABLE
    assert reasons(unknown_basis) == ["COMPARISON:STATEMENT_BASIS_UNKNOWN"]
    revision_row = growth(w, semantics=w.semantics({w.rev23.record_id: "EarnForecastRevision"}))
    assert reasons(revision_row) == ["COMPARISON:ACCOUNTING_STANDARD_UNKNOWN", "COMPARISON:STATEMENT_BASIS_UNKNOWN"]
    missing = w.semantics()
    del missing[w.rev24.record_id]
    assert reasons(growth(w, semantics=missing)) == ["TARGET:SEMANTICS_MISSING"]
    assert growth(w, semantics=missing).status is MetricStatus.INSUFFICIENT_DATA


def test_a_semantics_must_annotate_the_resolved_record(w: World) -> None:
    swapped = w.semantics()
    swapped[w.rev24.record_id] = swapped[w.rev23.record_id]                               # 別の観測の注記
    result = growth(w, semantics=swapped)
    assert result.status is MetricStatus.INVALID_INPUT and reasons(result) == ["TARGET:SEMANTICS_MISMATCH"]
    inconsistent = w.semantics({w.rev24.record_id: JP_NONCONS})                          # 注記は単体、観測は連結
    assert reasons(growth(w, semantics=inconsistent)) == ["TARGET:SEMANTICS_MISMATCH"]


def test_a_incompatible_periods_are_not_comparable(w: World) -> None:
    assert reasons(growth(w, target=FY24, comparison=FY22)) == ["PAIR:PERIOD_NOT_ADJACENT"]
    assert reasons(growth(w, target=FY24, comparison=Q1_24)) == ["PAIR:PERIOD_BASIS_MISMATCH",
                                                                 "PAIR:PERIOD_NOT_ADJACENT"]
    assert reasons(growth(w, target=Q2_25, comparison=Q1_24, cutoff=C_2025_12)) == ["PAIR:PERIOD_QUARTER_DIFFERS"]
    assert reasons(growth(w, target=SINGLE_Q2_25, comparison=Q1_24, cutoff=C_2025_12)) == \
        ["TARGET:PERIOD_BASIS_UNSUPPORTED"]
    assert reasons(growth(w, target=LONG_FY, comparison=FY23)) == ["TARGET:FISCAL_YEAR_IRREGULAR"]
    for result in (growth(w, target=FY24, comparison=FY22), growth(w, target=LONG_FY, comparison=FY23)):
        assert result.status is MetricStatus.NOT_COMPARABLE and result.input_record_ids == ()   # 解決の前に止まる


def test_a_cumulative_same_quarter_yoy_is_supported_and_labelled_cumulative(w: World) -> None:
    result = growth(w, target=Q1_25, comparison=Q1_24, cutoff=jst(2025, 8, 9))
    assert result.status is MetricStatus.VALUE and result.value == "0.083333"
    assert result.period_label is MetricPeriodLabel.CUMULATIVE_YEAR_TO_DATE and result.quarter == 1
    assert "SINGLE_QUARTER" not in json.dumps(result.as_dict())


def test_a_future_revision_is_excluded_and_historical_results_are_stable(w: World) -> None:
    assert growth(w, cutoff=C_2025_06).value == "0.25"                                    # 元の値 500000
    assert growth(w, cutoff=C_2025_12).value == "0.245"                                   # 訂正 498000
    without_restatement = w.history([r for r in w.records if r is not w.rev24_restated])
    assert growth(w, cutoff=C_2025_06, history=without_restatement).value == "0.25"       # 訂正の追加で過去は変わらない
    assert growth(w, cutoff=C_2025_06).input_record_ids[0] == w.rev24.record_id
    assert growth(w, cutoff=C_2025_12).input_record_ids[0] == w.rev24_restated.record_id
    future = growth(w, target=FY25, comparison=FY24, cutoff=C_2025_12)                    # FY25 は 2026 年に知られる
    assert future.status is MetricStatus.INSUFFICIENT_DATA and reasons(future) == ["TARGET:NOT_FOUND"]
    assert growth(w, target=FY25, comparison=FY24, cutoff=C_2026_06).value == "0.014056"  # 505000 / 498000 − 1


def test_a_date_only_knowledge_with_an_intraday_cutoff_is_insufficient_time_precision(w: World) -> None:
    intraday = growth(w, target=Q1_25, comparison=Q1_24, cutoff=at(2025, 8, 8, 3))        # 2025-08-08 12:00 JST
    assert intraday.status is MetricStatus.INSUFFICIENT_TIME_PRECISION
    assert reasons(intraday) == ["TARGET:INSUFFICIENT_TIME_PRECISION"] and intraday.value is None
    assert growth(w, target=Q1_25, comparison=Q1_24, cutoff=at(2025, 8, 7, 3)).status is MetricStatus.INSUFFICIENT_DATA
    assert growth(w, target=Q1_25, comparison=Q1_24, cutoff=jst(2025, 8, 9)).status is MetricStatus.VALUE


def test_a_decimal_determinism_and_scale_normalisation(w: World) -> None:
    thousands = rec(I1, REV, "400000000", FY23, K_FY23, scale=Scale.THOUSAND)              # 同じ額を千円で
    history = w.history([thousands, w.rev24, w.cover])
    semantics = w.semantics()
    semantics[thousands.record_id] = derive_observation_semantics(thousands.record_id, JP_CONS,
                                                                  FieldFamily.UNPREFIXED_ACTUAL)[0]
    assert growth(w, history=history, semantics=semantics).value == "0.25"
    third = rec(I1, REV, "300000", FY23, K_FY23)
    semantics[third.record_id] = derive_observation_semantics(third.record_id, JP_CONS,
                                                              FieldFamily.UNPREFIXED_ACTUAL)[0]
    repeated = {growth(w, history=w.history([third, w.rev24, w.cover]), semantics=semantics).value for _ in range(3)}
    assert repeated == {"0.666667"}                                                       # 6 桁 ・偶数丸め ・正準
    result = growth(w)
    assert result == growth(w) and result.as_dict() == growth(w).as_dict()
    assert not any(isinstance(v, float) for v in result.as_dict().values())
    with pytest.raises(FrozenInstanceError):
        result.value = "1"                                                                 # type: ignore[misc]


def test_a_invalid_inputs_are_typed_results_not_exceptions(w: World) -> None:
    result = fm.revenue_growth(w.history(), issuer_id="issuer-1", statement_basis="CONSOLIDATED", target_period=FY24,
                               comparison_period="FY23", cutoff=datetime(2025, 6, 1), semantics=None)
    assert result.status is MetricStatus.INVALID_INPUT
    assert reasons(result) == ["COMPARISON:INVALID_SUBJECT", "COMPARISON:INVALID_STATEMENT_BASIS",
                               "COMPARISON:INVALID_PERIOD", "PAIR:INVALID_SUBJECT", "PAIR:INVALID_STATEMENT_BASIS",
                               "PAIR:INVALID_CUTOFF", "PAIR:INVALID_SEMANTICS_LOOKUP"]      # comparison は target の既定を継ぐ
    assert result.cutoff is None and result.statement_basis is None and result.comparison_period is None
    no_history = fm.revenue_growth(None, issuer_id=I1, statement_basis=CONS, target_period=FY24,
                                   comparison_period=FY23, cutoff=C_2025_06, semantics={})
    assert reasons(no_history) == ["PAIR:INVALID_HISTORY"]


# ================================================================ B 営業利益率


def test_b_positive_margin_same_period(w: World) -> None:
    result = margin(w)
    assert result.status is MetricStatus.VALUE and result.value == "0.08"
    assert result.metric is MetricKind.OPERATING_MARGIN and result.period_label is MetricPeriodLabel.FISCAL_YEAR
    assert result.input_record_ids == (w.rev24.record_id, w.op24.record_id) and result.comparison_period is None


def test_b_negative_and_zero_operating_income(w: World) -> None:
    assert margin(w, issuer=I2).value == "-0.05"                                          # −50 ／ 1000
    assert margin(w, issuer=I2, period=FY22).value == "0"                                 # 0 ／ 900


def test_b_zero_revenue_is_undefined(w: World) -> None:
    result = margin(w, issuer=I2, period=FY23)                                            # 売上 0、営業利益なし → 先に欠落
    assert result.status is MetricStatus.INSUFFICIENT_DATA and reasons(result) == ["OPERATING_INCOME:NOT_FOUND"]
    zero = margin(w, issuer=I2, period=FY22, basis=NONCONS)                               # 売上 0 ・営業利益 7
    assert zero.status is MetricStatus.UNDEFINED and reasons(zero) == ["PAIR:DENOMINATOR_ZERO"]


def test_b_missing_sales_or_operating_income(w: World) -> None:
    no_sales = margin(w, issuer=I2, period=FY21)                                          # 売上は MISSING の値
    assert no_sales.status is MetricStatus.INSUFFICIENT_DATA and reasons(no_sales) == ["REVENUE:VALUE_ABSENT"]
    no_op = margin(w, period=FY25, cutoff=C_2026_06)                                      # FY25 の営業利益は無い
    assert reasons(no_op) == ["OPERATING_INCOME:NOT_FOUND"]
    mismatched = margin(w, issuer=I2, period=FY23)                                        # 売上だけの期間
    assert reasons(mismatched) == ["OPERATING_INCOME:NOT_FOUND"]


def test_b_different_standard_or_basis_between_the_legs_fails_closed(w: World) -> None:
    ifrs_op = margin(w, semantics=w.semantics({w.op24.record_id: IFRS_CONS}))
    assert ifrs_op.status is MetricStatus.NOT_COMPARABLE and reasons(ifrs_op) == ["PAIR:ACCOUNTING_STANDARD_DIFFERS"]
    inconsistent = margin(w, semantics=w.semantics({w.op24.record_id: JP_NONCONS}))       # 注記は単体、観測は連結
    assert inconsistent.status is MetricStatus.INVALID_INPUT
    assert reasons(inconsistent) == ["OPERATING_INCOME:SEMANTICS_MISMATCH"]
    foreign = margin(w, semantics=w.semantics({w.rev24.record_id: FOREIGN}))
    assert reasons(foreign) == ["REVENUE:ACCOUNTING_STANDARD_UNKNOWN"]
    revision = margin(w, semantics=w.semantics({w.op24.record_id: "EarnForecastRevision"}))
    assert reasons(revision) == ["OPERATING_INCOME:ACCOUNTING_STANDARD_UNKNOWN",
                                 "OPERATING_INCOME:STATEMENT_BASIS_UNKNOWN"]
    assert margin(w, semantics=w.semantics({w.rev24.record_id: IFRS_CONS, w.op24.record_id: IFRS_CONS})).value == "0.08"


def test_b_pit_cutoff_behaviour(w: World) -> None:
    early = margin(w, cutoff=at(2025, 5, 1))
    assert early.status is MetricStatus.INSUFFICIENT_DATA
    assert reasons(early) == ["REVENUE:NOT_FOUND", "OPERATING_INCOME:NOT_FOUND"]
    assert margin(w, cutoff=C_2025_06).value == "0.08"
    assert margin(w, cutoff=C_2025_12).value == "0.080321"                                # 40000 ／ 498000（訂正の後）
    intraday = margin(w, period=Q1_25, cutoff=at(2025, 8, 8, 3))
    assert intraday.status is MetricStatus.INSUFFICIENT_TIME_PRECISION
    assert reasons(intraday) == ["REVENUE:INSUFFICIENT_TIME_PRECISION", "OPERATING_INCOME:INSUFFICIENT_TIME_PRECISION"]


def test_b_cumulative_period_margin_is_labelled_cumulative_not_single_quarter(w: World) -> None:
    result = margin(w, period=Q1_25, cutoff=jst(2025, 8, 9))
    assert result.status is MetricStatus.VALUE and result.value == "0.07"
    assert result.period_label is MetricPeriodLabel.CUMULATIVE_YEAR_TO_DATE and result.quarter == 1
    assert reasons(margin(w, period=SINGLE_Q2_25, cutoff=C_2025_12)) == ["PAIR:PERIOD_BASIS_UNSUPPORTED"]
    assert reasons(margin(w, period=LONG_FY, cutoff=C_2025_12)) == ["PAIR:FISCAL_YEAR_IRREGULAR"]


def test_b_invalid_inputs_are_typed(w: World) -> None:
    result = fm.operating_margin(w.history(), issuer_id=I1, statement_basis=CONS, period="FY24", cutoff=C_2025_06,
                                 semantics={})
    assert result.status is MetricStatus.INVALID_INPUT and reasons(result) == ["PAIR:INVALID_PERIOD"]


# ================================================================ C 結果の model


def test_c_result_taxonomy_is_closed_and_failures_are_never_none() -> None:
    assert {s.value for s in MetricStatus} == {"VALUE", "NOT_COMPARABLE", "INSUFFICIENT_DATA", "INVALID_INPUT",
                                                "INSUFFICIENT_TIME_PRECISION", "UNDEFINED"}
    assert set(mm.STATUS_FOR_CODE) == set(ReasonCode)
    assert set(mm.STATUS_FOR_CODE.values()) == set(MetricStatus) - {MetricStatus.VALUE}
    assert mm.status_for(()) is MetricStatus.VALUE
    mixed = mm.ordered_reasons([MetricReason(MetricLeg.PAIR, ReasonCode.DENOMINATOR_ZERO),
                                MetricReason(MetricLeg.TARGET, ReasonCode.NOT_FOUND),
                                MetricReason(MetricLeg.TARGET, ReasonCode.NOT_FOUND)])
    assert [r.as_text() for r in mixed] == ["TARGET:NOT_FOUND", "PAIR:DENOMINATOR_ZERO"]
    assert mm.status_for(mixed) is MetricStatus.INSUFFICIENT_DATA                          # 最も強い status
    with pytest.raises(mm.MetricModelError):
        MetricResult(metric=MetricKind.REVENUE_GROWTH, status=MetricStatus.VALUE, reasons=(), value=None,
                     subject_id=I1, statement_basis=CONS, cutoff=C_2025_06, target_period=FY24,
                     period_label=MetricPeriodLabel.FISCAL_YEAR)
    with pytest.raises(mm.MetricModelError):
        MetricResult(metric=MetricKind.REVENUE_GROWTH, status=MetricStatus.NOT_COMPARABLE, reasons=(), value=None,
                     subject_id=I1, statement_basis=CONS, cutoff=C_2025_06, target_period=FY24)
    with pytest.raises(mm.MetricModelError):
        MetricReason("PAIR", ReasonCode.NOT_FOUND)                                          # type: ignore[arg-type]


def test_c_result_is_non_persistent_and_carries_no_evaluative_field(w: World) -> None:
    result = growth(w)
    assert not hasattr(result, "record_id") and not hasattr(result, "canonical_line")
    assert not set(MetricResult.__dataclass_fields__) & {"score", "rank", "weight", "recommendation", "record_id",
                                                          "metric_id", "signal"}
    assert set(result.as_dict()) == {"authority_class", "comparison_period", "cutoff", "input_record_ids", "metric",
                                     "period_label", "quarter", "reasons", "rules_version", "statement_basis", "status",
                                     "subject_id", "target_period", "value"}
    assert result.as_dict()["cutoff"].endswith("Z") or "+" in result.as_dict()["cutoff"]


# ================================================================ D architecture


@pytest.mark.parametrize("name", ["metric_model", "fundamental_metrics"])
def test_d_no_float_persistence_clock_network_llm_or_evaluation(name: str) -> None:
    source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float), (name, node.value)
        if isinstance(node, ast.Name):
            assert node.id not in {"float", "open", "Path", "os", "sys", "time", "random", "print"}, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "write", "append_record", "urlopen"}, (name, node.attr)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "store" not in node.module and "resolver" not in node.module or name == "fundamental_metrics"
    lowered = executable_source(PACKAGE_DIR / f"{name}.py").lower()                       # docstring ・comment を除く
    for token in ("screen", "rank", "score", "recommend", "theme", "exposure", "watchlist", "llm", "prompt",
                  "anthropic", "openai", "sqlite", "calibration", "production", "ttm", "annualiz", "trailing", "odp",
                  "ordinary"):
        assert token not in lowered, (name, token)
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in source


def test_d_the_metric_layer_uses_the_frozen_a2_resolver_and_a2r_gate_and_writes_nothing() -> None:
    source = (PACKAGE_DIR / "fundamental_metrics.py").read_text(encoding="utf-8")
    assert "from .observation_resolver import" in source and "resolve(" in source
    assert "from .observation_semantics_gate import" in source and "decide_compatibility(" in source
    assert ".observation_store" not in source and "ObservationStore" not in source and "history.add(" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):                                                           # 鎖の先頭を自分で選ばない
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"chains", "coverages", "state_at", "earliest", "certain_by"}, node.attr


def test_d_no_ttm_annualisation_or_standalone_quarter_conversion(w: World) -> None:
    result = growth(w, target=Q1_25, comparison=Q1_24, cutoff=jst(2025, 8, 9))
    assert Decimal_eq(result.value, "130000", "120000")                                   # 累計 ／ 累計、換算なし
    assert reasons(growth(w, target=Q2_25, comparison=Q1_25, cutoff=C_2025_12)) == \
        ["PAIR:PERIOD_QUARTER_DIFFERS", "PAIR:PERIOD_NOT_ADJACENT"]                      # 四半期の引き算はしない
    assert fm.REGULAR_FISCAL_YEAR_DAYS == (360, 371)


def Decimal_eq(value: str, numerator: str, denominator: str) -> bool:
    from decimal import Decimal
    return Decimal(value) == (Decimal(numerator) / Decimal(denominator) - 1).quantize(Decimal("0.000001"))
