"""observation_normalizer / units（Phase 1-D）: Decimal・unit区別・raw/derived・明示schema。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.intelligence.core import serialization
from src.intelligence.market.model import ObservationKind
from src.intelligence.normalization import units
from src.intelligence.normalization.model import NormalizationStatus
from src.intelligence.normalization.observation_normalizer import (
    JsonProviderSpec,
    JsonRecordNormalizer,
    ObservationFieldSpec,
    derived_observation,
    normalize_json_observations,
)
from src.intelligence.sources.model import RawItem

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
RAW = RawItem(
    raw_item_id="raw_syntheticmarket000001",
    source_id="synthetic_market",
    locator="https://api.example.org/market.json",
    retrieved_at=NOW,
    media_type="application/json",
    content_hash="ab" * 32,
    storage_ref="blobs/ab/x",
)

SPEC = JsonProviderSpec(
    provider="synthetic_market_v1",
    default_as_of_path="meta.as_of",
    fields=(
        ObservationFieldSpec(value_path="data.usdjpy", entity_id="fx:USDJPY",
                             metric="rate", unit="jpy_per_usd", currency="JPY"),
        ObservationFieldSpec(value_path="data.jgb10y_pct", entity_id="rates:JGB10Y",
                             metric="yield", unit=units.UNIT_PERCENT),
        ObservationFieldSpec(value_path="data.spread_bps", entity_id="rates:SPREAD",
                             metric="spread", unit=units.UNIT_BPS),
        ObservationFieldSpec(value_path="data.optional_extra", entity_id="x:OPT",
                             metric="v", unit="index", required=False),
    ),
)

PAYLOAD = b"""{
  "meta": {"as_of": "2026-08-29T15:00:00+00:00"},
  "data": {"usdjpy": 147.25, "jgb10y_pct": 1.085, "spread_bps": 32}
}"""


def test_json_numbers_become_decimal_never_float() -> None:
    result = normalize_json_observations(RAW, PAYLOAD, SPEC, now=NOW)
    assert result.status is NormalizationStatus.NORMALIZED
    by_entity = {o.entity_id: o for o in result.observations}
    usdjpy = by_entity["fx:USDJPY"]
    assert isinstance(usdjpy.value, Decimal)
    assert usdjpy.value == Decimal("147.25")  # parse_float=Decimal（floatを経由しない）
    assert usdjpy.currency == "JPY"
    assert by_entity["rates:SPREAD"].value == Decimal("32")  # intもDecimal化


def test_raw_observation_provenance() -> None:
    obs = normalize_json_observations(RAW, PAYLOAD, SPEC, now=NOW).observations[0]
    assert obs.kind is ObservationKind.RAW
    assert obs.source_id == "synthetic_market"
    assert obs.calculation_method == "api_field:synthetic_market_v1:data.usdjpy"
    assert obs.as_of == datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc)


def test_deterministic_observation_ids() -> None:
    a = normalize_json_observations(RAW, PAYLOAD, SPEC, now=NOW)
    b = normalize_json_observations(RAW, PAYLOAD, SPEC, now=NOW)
    assert [o.observation_id for o in a.observations] == \
           [o.observation_id for o in b.observations]
    assert a.observations == b.observations  # 同一入力＋同一version→同一結果


def test_missing_required_field_and_invalid_numeric_are_partial() -> None:
    payload = b'{"meta": {"as_of": "2026-08-29T15:00:00Z"}, "data": {"jgb10y_pct": "n/a"}}'
    result = normalize_json_observations(RAW, payload, SPEC, now=NOW)
    assert result.status is NormalizationStatus.REJECTED  # 有効な観測ゼロ
    codes = [i.code for i in result.issues]
    assert "missing_required_field" in codes  # usdjpy欠損
    assert "invalid_numeric" in codes  # "n/a"


def test_optional_field_missing_is_not_an_issue() -> None:
    result = normalize_json_observations(RAW, PAYLOAD, SPEC, now=NOW)
    assert not any(i.entry_ref == "x:OPT:v" for i in result.issues)


def test_missing_as_of_never_substitutes_retrieved_at() -> None:
    payload = b'{"data": {"usdjpy": 147.25, "jgb10y_pct": 1.0, "spread_bps": 1}}'
    result = normalize_json_observations(RAW, payload, SPEC, now=NOW)
    assert result.observations == ()  # as_of不明の観測は作らない（黙って代入しない）
    assert any(i.detail == "as_of (tz-aware)" for i in result.issues)


def test_unknown_currency_is_structured_issue() -> None:
    spec = JsonProviderSpec(provider="p", default_as_of_path="meta.as_of", fields=(
        ObservationFieldSpec(value_path="data.usdjpy", entity_id="fx:X", metric="rate",
                             unit="x", currency="ZZZ"),))
    result = normalize_json_observations(RAW, PAYLOAD, spec, now=NOW)
    assert any(i.code == "unknown_currency" and i.detail == "ZZZ" for i in result.issues)


def test_malformed_json_rejected() -> None:
    result = normalize_json_observations(RAW, b"{broken", SPEC, now=NOW)
    assert result.status is NormalizationStatus.REJECTED
    assert any(i.code == "unsupported_format" for i in result.issues)


def test_derived_observation_requires_provenance() -> None:
    obs = normalize_json_observations(RAW, PAYLOAD, SPEC, now=NOW).observations[0]
    derived = derived_observation(
        entity_id="fx:USDJPY", metric="chg_pct", value=Decimal("0.35"),
        unit=units.UNIT_PERCENT, as_of=NOW, inputs=(obs.observation_id,),
        calculation_method="pct_change_vs_prev_close")
    assert derived.kind is ObservationKind.DERIVED
    assert derived.inputs == (obs.observation_id,)
    with pytest.raises(ValueError):
        derived_observation(entity_id="x", metric="m", value=Decimal("1"), unit="pct",
                            as_of=NOW, inputs=(), calculation_method="c")  # inputs必須


def test_unit_conversions_are_exact_decimal() -> None:
    pct = Decimal("4.25")
    assert units.pct_to_bps(pct) == Decimal("425")
    assert units.pct_to_ratio(pct) == Decimal("0.0425")
    assert units.ratio_to_bps(Decimal("0.0425")) == Decimal("425.0000")
    assert units.same_quantity(Decimal("4.25"), units.UNIT_PERCENT,
                               Decimal("425"), units.UNIT_BPS)
    assert units.same_quantity(Decimal("4.25"), units.UNIT_PERCENT,
                               Decimal("0.0425"), units.UNIT_RATIO)
    assert not units.same_quantity(Decimal("4.25"), units.UNIT_PERCENT,
                                   Decimal("4.25"), units.UNIT_BPS)  # unit無視の同一視を拒否


def test_unit_family_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        units.same_quantity(Decimal("1"), "jpy", Decimal("1"), units.UNIT_PERCENT)


def test_provider_normalizer_protocol_shape() -> None:
    class SyntheticNormalizer:
        def normalize(self, raw_item, body):
            return normalize_json_observations(raw_item, body, SPEC, now=NOW)

    assert isinstance(SyntheticNormalizer(), JsonRecordNormalizer)


def test_observation_serialization_roundtrip() -> None:
    serialization.register_domain_types()
    for obs in normalize_json_observations(RAW, PAYLOAD, SPEC, now=NOW).observations:
        decoded = serialization.decode(serialization.encode(obs))
        assert decoded == obs and isinstance(decoded.value, Decimal)
