"""Observation QA（Phase 1-E）: 数値sanity・unit/currency・stale quote・derived依存。"""
from __future__ import annotations

from decimal import Decimal

from src.intelligence.core.types import Horizon
from src.intelligence.evidence_qa.assess import assess_observation
from src.intelligence.evidence_qa.model import DimensionStatus, GateDecision, QADimension
from src.intelligence.evidence_qa.policy import DAILY_MARKET_V1, GENERIC_V1
from src.intelligence.market.model import ObservationKind
from tests.intelligence.qa_fixtures import REF, make_observation, make_source_info

INFO = make_source_info("synthetic_market", investment_value="HIGH")


def qa(obs, policy=GENERIC_V1, **kw):
    return assess_observation(obs, source_info=INFO, policy=policy,
                              reference_time=REF, **kw)


def test_valid_raw_observation_accepts() -> None:
    a = qa(make_observation())
    assert a.decision is GateDecision.ACCEPT
    assert a.record_type == "observation"


def test_nan_and_infinity_rejected() -> None:
    for bad in (Decimal("NaN"), Decimal("Infinity")):
        a = qa(make_observation(value=bad))
        assert a.decision is GateDecision.REJECT
        assert "value_not_finite" in a.decision_reasons


def test_negative_impossible_price_rejected_not_corrected() -> None:
    a = qa(make_observation(value=Decimal("-120.5"), metric="close", unit="index"))
    assert a.decision is GateDecision.REJECT
    assert "negative_impossible_value" in a.decision_reasons
    # 補正はしない（検知のみ）——値の書き換えAPIは存在しない


def test_negative_yield_is_allowed() -> None:
    """負値検査は不可能なmetricのみ（利回りのマイナスは正当）。"""
    a = qa(make_observation(value=Decimal("-0.1"), metric="yield", unit="pct",
                            currency=""))
    assert a.dimension(QADimension.OBSERVATION_VALIDITY).status is DimensionStatus.PASS


def test_absurd_percentage_limited() -> None:
    a = qa(make_observation(value=Decimal("35000"), metric="yoy", unit="pct", currency=""))
    assert a.decision is GateDecision.LIMITED_USE
    assert "absurd_percentage" in a.decision_reasons


def test_missing_value_warns_not_fabricated() -> None:
    a = qa(make_observation(value=None))
    assert a.decision is GateDecision.ACCEPT_WITH_WARNINGS
    assert "value_missing" in [i.code for i in a.issues]  # 欠測はNone＝捏造しない


def test_currency_mismatch_flagged() -> None:
    a = qa(make_observation(unit="jpy_per_usd", currency="EUR"))
    assert "currency_mismatch" in a.decision_reasons
    assert a.decision is GateDecision.LIMITED_USE


def test_as_of_in_future_flagged() -> None:
    a = qa(make_observation(as_of_age_hours=-6))  # 基準時刻より未来
    assert "as_of_in_future" in a.decision_reasons


def test_stale_market_quote_by_horizon() -> None:
    """36時間前の為替quote: GENERICでは許容、DAILY_MARKET×intradayではstale。"""
    obs = make_observation(as_of_age_hours=36)
    assert qa(obs).decision is GateDecision.ACCEPT
    daily = qa(obs, policy=DAILY_MARKET_V1, horizon=Horizon.INTRADAY)
    assert daily.decision is GateDecision.LIMITED_USE
    assert "stale_for_horizon" in daily.decision_reasons


def test_derived_with_rejected_input_is_limited() -> None:
    base = qa(make_observation("obs_bad", value=Decimal("NaN")))
    assert base.decision is GateDecision.REJECT
    derived = make_observation(
        "obs_derived", kind=ObservationKind.DERIVED, inputs=("obs_bad",),
        calculation_method="pct_change", source_id="", source_document_id="")
    a = qa(derived, input_assessments=(base,))
    assert a.decision is GateDecision.LIMITED_USE
    assert "dependency_rejected" in a.decision_reasons


def test_derived_with_clean_input_accepts() -> None:
    base = qa(make_observation())
    derived = make_observation(
        "obs_derived2", kind=ObservationKind.DERIVED, inputs=(base.record_id,),
        calculation_method="pct_change", source_id="", source_document_id="")
    a = qa(derived, input_assessments=(base,))
    assert a.decision is GateDecision.ACCEPT
