"""Phase 1-A serialization roundtripテスト。"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.intelligence.core.serialization import decode, encode, register_domain_types

from . import evidence_fixtures as fx

register_domain_types()


def _roundtrip(obj):
    data = encode(obj)
    json_text = json.dumps(data, ensure_ascii=False)  # JSON互換であること
    return decode(json.loads(json_text))


def all_fixture_objects():
    objs = []
    objs += list(fx.boj_statement())
    objs += list(fx.fed_statement())
    objs += list(fx.cpi_release_with_revision())
    base = fx.jp_stock_observation()
    objs += [base, fx.us_stock_observation(), fx.derived_observation(base)]
    objs += list(fx.earnings_release())
    objs += list(fx.secondary_article())
    doc_a, doc_b, fact, links = fx.conflicting_sources()
    objs += [doc_a, doc_b, fact, *links]
    objs.append(fx.unsupported_ai_claim())
    chain = fx.causal_chain()
    objs += list(chain)
    objs.append(fx.raw_item_for(chain[0], b"fomc-body"))
    return objs


@pytest.mark.parametrize("obj", all_fixture_objects(), ids=lambda o: type(o).__name__)
def test_roundtrip_equality(obj) -> None:
    assert _roundtrip(obj) == obj


def test_datetime_roundtrip_preserves_instant_and_awareness() -> None:
    doc, _, _ = fx.boj_statement()
    restored = _roundtrip(doc)
    assert restored.published_at == doc.published_at  # JST 12:00 == UTC 03:00
    assert restored.published_at.tzinfo is not None


def test_decimal_precision_survives_roundtrip() -> None:
    obs = fx.us_stock_observation()
    restored = _roundtrip(obs)
    assert isinstance(restored.value, Decimal)
    assert str(restored.value) == "201.34"
    data = encode(obs)
    assert data["value"] == "201.34"  # 文字列表現（floatを経由しない）


def test_float_cannot_be_encoded() -> None:
    with pytest.raises(TypeError):
        from src.intelligence.core.serialization import _encode_value

        _encode_value(0.1)


def test_unknown_type_rejected() -> None:
    with pytest.raises(ValueError):
        decode({"_type": "NoSuchType"})
    with pytest.raises(ValueError):
        decode({"no_type": True})


def test_forecast_nested_metadata_roundtrip() -> None:
    forecast = fx.causal_chain()[4]
    restored = _roundtrip(forecast)
    assert restored.forecast is not None
    assert restored.forecast.confidence == 3
    assert restored.forecast.invalidation_conditions == forecast.forecast.invalidation_conditions
    assert restored.forecast.evaluate_by == forecast.forecast.evaluate_by
