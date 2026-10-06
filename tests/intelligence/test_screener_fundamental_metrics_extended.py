"""P8-A3B — 純利益率 ・ROA（時点の分母）の test matrix A〜D（境界 ／ 凍結は `test_screener_intelligence_boundary.py`）。

すべて合成の観測（A2 の凍結の test の合成の identity ・架空の値）。J-Quants ・network ・実データ ・LLM ・時計 ・乱数は使わない。
A1 ・A2 ・A1R ・A2R ・A3A の `fundamental_metrics` は変えない（`metric_model` は enum の 4 行の追加だけ。境界の guard が差分を固定する）。
"""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import fundamental_metrics_extended as fx
from src.intelligence.screener_intelligence import metric_model as mm
from src.intelligence.screener_intelligence.metric_model import (MetricKind, MetricLeg, MetricPeriodLabel, MetricResult,
                                                                 MetricStatus, ReasonCode)
from src.intelligence.screener_intelligence.observation_model import (CoverageDataset, FundamentalField,
                                                                      ObservationHistory, Scale, StatementBasis,
                                                                      ValueState)
from src.intelligence.screener_intelligence.observation_semantics_mapping import derive_observation_semantics
from src.intelligence.screener_intelligence.observation_semantics_model import FieldFamily
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_fundamental_metrics import (CONS, FOREIGN, FY21, FY22, FY23, FY24, FY25, I1, I2,
                                                                  IDS, IFRS_CONS, IFRS_NONCONS, JP_CONS, JP_NONCONS,
                                                                  K_FY23, K_FY24, K_FY25, K_RESTATED, LONG_FY, NONCONS,
                                                                  Q1_25, SINGLE_Q2_25, US_CONS, C_2025_06, C_2025_12,
                                                                  C_2026_06, jst, rec, reasons)
from tests.intelligence.test_screener_observation import absent, at, coverage, on, ts

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
REV, NI, TA, OP = (FundamentalField.REVENUE, FundamentalField.NET_INCOME, FundamentalField.TOTAL_ASSETS,
                   FundamentalField.OPERATING_INCOME)


class World:
    """合成の財務の観測。I1 は JP 基準 ・連結の通常の発行体。I2 は端の場合（売上 ・総資産の 0 ／ 負 ・欠損）。"""

    def __init__(self) -> None:
        self.rev23 = rec(I1, REV, "400000", FY23, K_FY23)
        self.ni23 = rec(I1, NI, "25000", FY23, K_FY23)
        self.ta23 = rec(I1, TA, "800000", FY23, K_FY23)
        self.rev24 = rec(I1, REV, "500000", FY24, K_FY24)
        self.ni24 = rec(I1, NI, "30000", FY24, K_FY24)
        self.ni24_restated = rec(I1, NI, "31000", FY24, K_RESTATED, supersedes=self.ni24.record_id)
        self.ta24 = rec(I1, TA, "900000", FY24, K_FY24)
        self.op24 = rec(I1, OP, "40000", FY24, K_FY24)
        self.ni22 = rec(I1, NI, "20000", FY22, ts(2023, 5, 10, 6))                          # 売上 ・総資産の無い年度
        self.rev25 = rec(I1, REV, "505000", FY25, K_FY25)                                   # 純利益 ・総資産は無い
        self.q1_25_rev = rec(I1, REV, "130000", Q1_25, on(2025, 8, 8))                      # 日付だけの知識
        self.q1_25_ni = rec(I1, NI, "7800", Q1_25, on(2025, 8, 8))
        self.q1_25_ta = rec(I1, TA, "905000", Q1_25, on(2025, 8, 8))
        self.i2_rev24 = rec(I2, REV, "1000", FY24, K_FY24)
        self.i2_ni24 = rec(I2, NI, "-50", FY24, K_FY24)                                     # 負の純利益
        self.i2_ta24 = rec(I2, TA, "5000", FY24, K_FY24)
        self.i2_rev23_zero = rec(I2, REV, "0", FY23, K_FY23)                                # 売上 0 ・総資産 0
        self.i2_ni23 = rec(I2, NI, "5", FY23, K_FY23)
        self.i2_ta23_zero = rec(I2, TA, "0", FY23, K_FY23)
        self.i2_rev22_negative = rec(I2, REV, "-100", FY22, ts(2023, 5, 10, 6))            # 負の売上 ・負の総資産
        self.i2_ni22 = rec(I2, NI, "1", FY22, ts(2023, 5, 10, 6))
        self.i2_ta22_negative = rec(I2, TA, "-5", FY22, ts(2023, 5, 10, 6))
        self.i2_rev22_nc = rec(I2, REV, "1000", FY22, ts(2023, 5, 10, 6), basis=NONCONS)   # 純利益 0（単体）
        self.i2_ni22_nc_zero = rec(I2, NI, "0", FY22, ts(2023, 5, 10, 6), basis=NONCONS)
        self.i2_ta22_nc = rec(I2, TA, "4000", FY22, ts(2023, 5, 10, 6), basis=NONCONS)
        self.i2_rev21 = rec(I2, REV, "1000", FY21, ts(2022, 5, 10, 6))                      # 純利益は MISSING の値
        self.i2_ni21_missing = rec(I2, NI, absent(NI, ValueState.MISSING), FY21, ts(2022, 5, 10, 6))
        self.i2_ta21 = rec(I2, TA, "4000", FY21, ts(2022, 5, 10, 6))
        self.cover = coverage(CoverageDataset.FUNDAMENTAL_DISCLOSURE, at(2022, 1, 1).date(), at(2027, 1, 1).date(),
                              at(2026, 6, 30))
        self.records = [self.rev23, self.ni23, self.ta23, self.rev24, self.ni24, self.ni24_restated, self.ta24,
                        self.op24, self.ni22, self.rev25, self.q1_25_rev, self.q1_25_ni, self.q1_25_ta, self.i2_rev24,
                        self.i2_ni24, self.i2_ta24, self.i2_rev23_zero, self.i2_ni23, self.i2_ta23_zero,
                        self.i2_rev22_negative, self.i2_ni22, self.i2_ta22_negative, self.i2_rev22_nc,
                        self.i2_ni22_nc_zero, self.i2_ta22_nc, self.i2_rev21, self.i2_ni21_missing, self.i2_ta21,
                        self.cover]

    def history(self, records=None) -> ObservationHistory:
        return ObservationHistory(IDS.history(), self.records if records is None else records)

    def semantics(self, overrides=None) -> dict:
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


def margin(w: World, period=FY24, *, cutoff=C_2025_06, issuer=I1, basis=CONS, semantics=None, history=None,
           **extra) -> MetricResult:
    return fx.net_margin(w.history() if history is None else history, issuer_id=issuer, statement_basis=basis,
                         period=period, cutoff=cutoff, semantics=w.semantics() if semantics is None else semantics,
                         **extra)


def roa(w: World, fiscal_year=FY24, *, cutoff=C_2025_06, issuer=I1, basis=CONS, semantics=None, history=None,
        **extra) -> MetricResult:
    return fx.roa_point_in_time(w.history() if history is None else history, issuer_id=issuer, statement_basis=basis,
                                fiscal_year=fiscal_year, cutoff=cutoff,
                                semantics=w.semantics() if semantics is None else semantics, **extra)


# ================================================================ A 純利益率


def test_a_positive_net_margin(w: World) -> None:
    result = margin(w)
    assert result.status is MetricStatus.VALUE and result.value == "0.06" and result.reasons == ()   # 30000 ／ 500000
    assert result.metric is MetricKind.NET_MARGIN and result.period_label is MetricPeriodLabel.FISCAL_YEAR
    assert result.input_record_ids == (w.rev24.record_id, w.ni24.record_id) and result.quarter == 0
    assert result.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"


def test_a_negative_and_zero_net_income(w: World) -> None:
    assert margin(w, issuer=I2).value == "-0.05"                                             # −50 ／ 1000
    assert margin(w, issuer=I2, period=FY22, basis=NONCONS).value == "0"                    # 0 ／ 1000


def test_a_zero_or_negative_revenue_is_undefined(w: World) -> None:
    zero = margin(w, issuer=I2, period=FY23)
    assert zero.status is MetricStatus.UNDEFINED and reasons(zero) == ["PAIR:DENOMINATOR_ZERO"] and zero.value is None
    negative = margin(w, issuer=I2, period=FY22)
    assert negative.status is MetricStatus.UNDEFINED and reasons(negative) == ["PAIR:DENOMINATOR_NEGATIVE"]


def test_a_missing_revenue_or_net_income(w: World) -> None:
    no_revenue = margin(w, period=FY22)                                                     # I1 の FY22 は純利益だけ
    assert no_revenue.status is MetricStatus.INSUFFICIENT_DATA and reasons(no_revenue) == ["REVENUE:NOT_FOUND"]
    no_income = margin(w, period=FY25, cutoff=C_2026_06)                                    # FY25 は売上だけ
    assert reasons(no_income) == ["NET_INCOME:NOT_FOUND"]
    absent_income = margin(w, issuer=I2, period=FY21)                                       # 純利益は MISSING の値
    assert reasons(absent_income) == ["NET_INCOME:VALUE_ABSENT"]
    assert margin(w, period=FY23, cutoff=at(2024, 5, 1)).status is MetricStatus.INSUFFICIENT_DATA   # 期間の不一致 ／ 未知


def test_a_operating_or_other_profit_is_never_substituted(w: World) -> None:
    history = w.history([w.rev24, w.op24, w.cover])                                        # 営業利益はあるが純利益は無い
    result = margin(w, history=history)
    assert result.status is MetricStatus.INSUFFICIENT_DATA and reasons(result) == ["NET_INCOME:NOT_FOUND"]
    assert w.op24.record_id not in result.input_record_ids


def test_a_different_standard_or_basis_and_unknown_semantics_fail_closed(w: World) -> None:
    ifrs = margin(w, semantics=w.semantics({w.ni24.record_id: IFRS_CONS}))
    assert ifrs.status is MetricStatus.NOT_COMPARABLE and reasons(ifrs) == ["PAIR:ACCOUNTING_STANDARD_DIFFERS"]
    us = margin(w, semantics=w.semantics({w.rev24.record_id: US_CONS}))
    assert reasons(us) == ["PAIR:ACCOUNTING_STANDARD_DIFFERS"]
    inconsistent = margin(w, semantics=w.semantics({w.ni24.record_id: JP_NONCONS}))         # 注記は単体、観測は連結
    assert inconsistent.status is MetricStatus.INVALID_INPUT
    assert reasons(inconsistent) == ["NET_INCOME:SEMANTICS_MISMATCH"]
    foreign = margin(w, semantics=w.semantics({w.rev24.record_id: FOREIGN}))
    assert foreign.status is MetricStatus.NOT_COMPARABLE and reasons(foreign) == ["REVENUE:ACCOUNTING_STANDARD_UNKNOWN"]
    unknown_basis = margin(w, issuer=I2, period=FY22, basis=NONCONS,
                           semantics=w.semantics({w.i2_ni22_nc_zero.record_id: IFRS_NONCONS}))
    assert reasons(unknown_basis) == ["NET_INCOME:STATEMENT_BASIS_UNKNOWN"]
    revision = margin(w, semantics=w.semantics({w.ni24.record_id: "EarnForecastRevision"}))
    assert reasons(revision) == ["NET_INCOME:ACCOUNTING_STANDARD_UNKNOWN", "NET_INCOME:STATEMENT_BASIS_UNKNOWN"]
    missing = w.semantics()
    del missing[w.ni24.record_id]
    assert reasons(margin(w, semantics=missing)) == ["NET_INCOME:SEMANTICS_MISSING"]
    assert margin(w, semantics=w.semantics({w.rev24.record_id: IFRS_CONS, w.ni24.record_id: IFRS_CONS})).value == "0.06"


def test_a_pit_future_observation_and_revision_stability(w: World) -> None:
    early = margin(w, cutoff=at(2025, 5, 1))
    assert early.status is MetricStatus.INSUFFICIENT_DATA and reasons(early) == ["REVENUE:NOT_FOUND",
                                                                                 "NET_INCOME:NOT_FOUND"]
    first = margin(w, cutoff=C_2025_06)
    assert first.value == "0.06" and first.input_record_ids[1] == w.ni24.record_id             # 元の値
    later = margin(w, cutoff=C_2025_12)
    assert later.value == "0.062" and later.input_record_ids[1] == w.ni24_restated.record_id   # 訂正 31000
    again = margin(w, cutoff=C_2025_06)
    assert again == first and again.as_dict() == first.as_dict()                              # 過去は変わらない
    without = w.history([r for r in w.records if r is not w.ni24_restated])
    assert margin(w, cutoff=C_2025_06, history=without) == first


def test_a_date_only_intraday_cutoff_and_cumulative_label(w: World) -> None:
    intraday = margin(w, period=Q1_25, cutoff=at(2025, 8, 8, 3))                            # 2025-08-08 12:00 JST
    assert intraday.status is MetricStatus.INSUFFICIENT_TIME_PRECISION
    assert reasons(intraday) == ["REVENUE:INSUFFICIENT_TIME_PRECISION", "NET_INCOME:INSUFFICIENT_TIME_PRECISION"]
    cumulative = margin(w, period=Q1_25, cutoff=jst(2025, 8, 9))
    assert cumulative.status is MetricStatus.VALUE and cumulative.value == "0.06"             # 7800 ／ 130000
    assert cumulative.period_label is MetricPeriodLabel.CUMULATIVE_YEAR_TO_DATE and cumulative.quarter == 1
    assert reasons(margin(w, period=SINGLE_Q2_25, cutoff=C_2025_12)) == ["PAIR:PERIOD_BASIS_UNSUPPORTED"]
    assert reasons(margin(w, period=LONG_FY, cutoff=C_2025_12)) == ["PAIR:FISCAL_YEAR_IRREGULAR"]


def test_a_decimal_determinism_and_scale(w: World) -> None:
    thousands = rec(I1, NI, "30000000", FY24, K_FY24, scale=Scale.THOUSAND)                  # 同じ額を千円で
    semantics = w.semantics()
    semantics[thousands.record_id] = derive_observation_semantics(thousands.record_id, JP_CONS,
                                                                  FieldFamily.UNPREFIXED_ACTUAL)[0]
    assert margin(w, history=w.history([w.rev24, thousands, w.cover]), semantics=semantics).value == "0.06"
    third = rec(I1, NI, "166667", FY24, K_FY24)
    semantics[third.record_id] = derive_observation_semantics(third.record_id, JP_CONS,
                                                              FieldFamily.UNPREFIXED_ACTUAL)[0]
    values = {margin(w, history=w.history([w.rev24, third, w.cover]), semantics=semantics).value for _ in range(3)}
    assert values == {"0.333334"}                                                             # 6 桁 ・偶数丸め ・正準
    result = margin(w)
    assert not any(isinstance(v, float) for v in result.as_dict().values())
    with pytest.raises(FrozenInstanceError):
        result.value = "1"                                                                    # type: ignore[misc]
    invalid = fx.net_margin(w.history(), issuer_id=I1, statement_basis=CONS, period="FY24",
                            cutoff=datetime(2025, 6, 1), semantics=None)
    assert invalid.status is MetricStatus.INVALID_INPUT
    assert reasons(invalid) == ["PAIR:INVALID_PERIOD", "PAIR:INVALID_CUTOFF", "PAIR:INVALID_SEMANTICS_LOOKUP"]


# ================================================================ B ROA（時点の分母）


def test_b_positive_roa_uses_fy_net_income_over_fy_end_total_assets(w: World) -> None:
    result = roa(w)
    assert result.status is MetricStatus.VALUE and result.value == "0.033333"                # 30000 ／ 900000
    assert result.metric is MetricKind.ROA_POINT_IN_TIME and result.period_label is MetricPeriodLabel.FISCAL_YEAR
    assert result.input_record_ids == (w.ta24.record_id, w.ni24.record_id)
    assert result.target_period == FY24 and result.comparison_period is None                  # 期首の総資産は使わない
    assert w.ta23.record_id not in result.input_record_ids


def test_b_negative_and_zero_net_income(w: World) -> None:
    assert roa(w, issuer=I2).value == "-0.01"                                                # −50 ／ 5000
    assert roa(w, issuer=I2, fiscal_year=FY22, basis=NONCONS).value == "0"                   # 0 ／ 4000


def test_b_zero_or_negative_assets_is_undefined(w: World) -> None:
    zero = roa(w, issuer=I2, fiscal_year=FY23)
    assert zero.status is MetricStatus.UNDEFINED and reasons(zero) == ["PAIR:DENOMINATOR_ZERO"]
    negative = roa(w, issuer=I2, fiscal_year=FY22)
    assert negative.status is MetricStatus.UNDEFINED and reasons(negative) == ["PAIR:DENOMINATOR_NEGATIVE"]


def test_b_missing_net_income_or_assets_and_mismatched_fiscal_year(w: World) -> None:
    assert reasons(roa(w, fiscal_year=FY22)) == ["TOTAL_ASSETS:NOT_FOUND"]                  # I1 の FY22 は純利益だけ
    assert reasons(roa(w, fiscal_year=FY25, cutoff=C_2026_06)) == ["NET_INCOME:NOT_FOUND",
                                                                  "TOTAL_ASSETS:NOT_FOUND"]   # 脚の語彙の順
    assert reasons(roa(w, issuer=I2, fiscal_year=FY21)) == ["NET_INCOME:VALUE_ABSENT"]
    history = w.history([w.ni24, w.ta23, w.cover])                                          # 総資産は前の年度にしかない
    mismatched = roa(w, history=history)
    assert mismatched.status is MetricStatus.INSUFFICIENT_DATA and reasons(mismatched) == ["TOTAL_ASSETS:NOT_FOUND"]


def test_b_non_fiscal_year_periods_are_rejected(w: World) -> None:
    quarterly = roa(w, fiscal_year=Q1_25, cutoff=jst(2025, 8, 9))                            # 累計でも ROA は年度だけ
    assert quarterly.status is MetricStatus.NOT_COMPARABLE and reasons(quarterly) == ["PAIR:PERIOD_BASIS_UNSUPPORTED"]
    assert quarterly.input_record_ids == ()                                                  # 解決の前に止まる
    assert reasons(roa(w, fiscal_year=SINGLE_Q2_25, cutoff=C_2025_12)) == ["PAIR:PERIOD_BASIS_UNSUPPORTED"]
    assert reasons(roa(w, fiscal_year=LONG_FY, cutoff=C_2025_12)) == ["PAIR:FISCAL_YEAR_IRREGULAR"]


def test_b_different_standard_or_basis_and_unknown_semantics_fail_closed(w: World) -> None:
    ifrs = roa(w, semantics=w.semantics({w.ta24.record_id: IFRS_CONS}))
    assert ifrs.status is MetricStatus.NOT_COMPARABLE and reasons(ifrs) == ["PAIR:ACCOUNTING_STANDARD_DIFFERS"]
    assert reasons(roa(w, semantics=w.semantics({w.ni24.record_id: US_CONS}))) == ["PAIR:ACCOUNTING_STANDARD_DIFFERS"]
    inconsistent = roa(w, semantics=w.semantics({w.ta24.record_id: JP_NONCONS}))
    assert inconsistent.status is MetricStatus.INVALID_INPUT
    assert reasons(inconsistent) == ["TOTAL_ASSETS:SEMANTICS_MISMATCH"]
    foreign = roa(w, semantics=w.semantics({w.ni24.record_id: FOREIGN}))
    assert reasons(foreign) == ["NET_INCOME:ACCOUNTING_STANDARD_UNKNOWN"]
    unknown_basis = roa(w, issuer=I2, fiscal_year=FY22, basis=NONCONS,
                        semantics=w.semantics({w.i2_ta22_nc.record_id: IFRS_NONCONS}))
    assert reasons(unknown_basis) == ["TOTAL_ASSETS:STATEMENT_BASIS_UNKNOWN"]
    missing = w.semantics()
    del missing[w.ta24.record_id]
    assert reasons(roa(w, semantics=missing)) == ["TOTAL_ASSETS:SEMANTICS_MISSING"]
    assert roa(w, semantics=w.semantics({w.ta24.record_id: IFRS_CONS, w.ni24.record_id: IFRS_CONS})).value == "0.033333"


def test_b_pit_future_observation_revision_stability_and_intraday_ambiguity(w: World) -> None:
    early = roa(w, cutoff=at(2025, 5, 1))
    assert early.status is MetricStatus.INSUFFICIENT_DATA and reasons(early) == ["NET_INCOME:NOT_FOUND",
                                                                                 "TOTAL_ASSETS:NOT_FOUND"]
    first = roa(w, cutoff=C_2025_06)
    assert first.value == "0.033333" and first.input_record_ids[1] == w.ni24.record_id
    later = roa(w, cutoff=C_2025_12)
    assert later.value == "0.034444" and later.input_record_ids[1] == w.ni24_restated.record_id   # 31000 ／ 900000
    assert roa(w, cutoff=C_2025_06) == first and roa(w, cutoff=C_2025_06).as_dict() == first.as_dict()
    without = w.history([r for r in w.records if r is not w.ni24_restated])
    assert roa(w, cutoff=C_2025_06, history=without) == first
    fy_intraday = rec(I1, TA, "900000", FY24, on(2025, 5, 12))                              # 日付だけの知識の総資産
    semantics = w.semantics()
    semantics[fy_intraday.record_id] = derive_observation_semantics(fy_intraday.record_id, JP_CONS,
                                                                    FieldFamily.UNPREFIXED_ACTUAL)[0]
    ambiguous = roa(w, history=w.history([w.ni24, fy_intraday, w.cover]), semantics=semantics,
                    cutoff=at(2025, 5, 12, 6))
    assert ambiguous.status is MetricStatus.INSUFFICIENT_TIME_PRECISION
    assert reasons(ambiguous) == ["TOTAL_ASSETS:INSUFFICIENT_TIME_PRECISION"]


def test_b_decimal_determinism_and_no_average_assets(w: World) -> None:
    result = roa(w)
    assert {roa(w).value for _ in range(3)} == {"0.033333"}
    assert not any(isinstance(v, float) for v in result.as_dict().values())
    from decimal import Decimal
    assert Decimal(result.value) != (Decimal(30000) / ((Decimal(800000) + Decimal(900000)) / 2)).quantize(
        Decimal("0.000001"))                                                                  # 平均の総資産の値ではない
    assert Decimal(result.value) == (Decimal(30000) / Decimal(900000)).quantize(Decimal("0.000001"))
    source = executable_source(PACKAGE_DIR / "fundamental_metrics_extended.py").lower()
    assert "average" not in source and "/ 2" not in source and "+ 1" not in source and "beginning" not in source


# ================================================================ C 結果の model の変更（enum の 4 行だけ）


def test_c_metric_model_gained_only_the_a3b_members() -> None:
    assert set(MetricKind) == {MetricKind.REVENUE_GROWTH, MetricKind.OPERATING_MARGIN, MetricKind.NET_MARGIN,
                               MetricKind.ROA_POINT_IN_TIME}
    assert [m.value for m in MetricLeg] == ["TARGET", "COMPARISON", "REVENUE", "OPERATING_INCOME", "PAIR",
                                            "NET_INCOME", "TOTAL_ASSETS"]                    # 既存の順は変えない
    assert set(mm.STATUS_FOR_CODE) == set(ReasonCode) and len(ReasonCode) == 29              # 理由の code は増えていない
    assert {s.value for s in MetricStatus} == {"VALUE", "NOT_COMPARABLE", "INSUFFICIENT_DATA", "INVALID_INPUT",
                                                "INSUFFICIENT_TIME_PRECISION", "UNDEFINED"}
    ordered = mm.ordered_reasons([mm.MetricReason(MetricLeg.TOTAL_ASSETS, ReasonCode.NOT_FOUND),
                                  mm.MetricReason(MetricLeg.NET_INCOME, ReasonCode.NOT_FOUND),
                                  mm.MetricReason(MetricLeg.PAIR, ReasonCode.DENOMINATOR_ZERO)])
    assert [r.as_text() for r in ordered] == ["PAIR:DENOMINATOR_ZERO", "NET_INCOME:NOT_FOUND",
                                              "TOTAL_ASSETS:NOT_FOUND"]


# ================================================================ D architecture


def test_d_no_float_persistence_clock_network_llm_evaluation_or_substitution() -> None:
    path = PACKAGE_DIR / "fundamental_metrics_extended.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float), node.value
        if isinstance(node, ast.Name):
            assert node.id not in {"float", "open", "Path", "os", "sys", "time", "random", "print"}, node.id
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "write", "urlopen", "chains", "coverages", "state_at",
                                     "earliest", "certain_by"}, node.attr
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "store" not in node.module and "mapping" not in node.module
    lowered = executable_source(path).lower()
    for token in ("screen", "rank", "score", "recommend", "theme", "exposure", "watchlist", "llm", "prompt",
                  "anthropic", "openai", "sqlite", "calibration", "production", "ttm", "annualiz", "trailing", "odp",
                  "ordinary", "operating_income", "average"):
        assert token not in lowered, token
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in source
    assert "FundamentalField.NET_INCOME" in source and "FundamentalField.TOTAL_ASSETS" in source
    assert "from .fundamental_metrics import" in source                                        # A3A の再利用
    assert "def _resolve_leg" not in source and "def _ratio_minus" not in source                # 競合する実装なし
