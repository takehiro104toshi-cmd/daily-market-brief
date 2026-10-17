"""Phase 5 P5-2A — EvaluationRecord schema ＋ deterministic identity ＋ realized outcome 契約の凍結ガード。

gate §20 の 50 項目を、市場データ・カレンダー・network・store に触れずに証明する。
"""
from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.predictions import evaluation_record as er
from src.intelligence.predictions.evaluation_record import (
    EVALUATION_ID_PREFIX,
    EVALUATION_RECORD_SCHEMA_VERSION,
    IDENTITY_KEYS,
    NEUTRAL_BAND,
    NEUTRAL_BAND_RULE_VERSION,
    SUPPORTED_CLASSIFICATION_VERSIONS,
    SUPPORTED_TARGETS,
    TARGET_TOPIX,
    DeferReason,
    EvaluationRecord,
    EvaluationStatus,
    InvalidEvaluationRecord,
    RealizedOutcome,
    SessionVerification,
    canonical_decimal,
    canonical_identity,
    classify_realized_return,
    make_evaluation_id,
    make_evaluation_record,
    parse_canonical_decimal,
)
from src.intelligence.predictions.prediction_record import (
    PREDICTION_RECORD_SCHEMA_VERSION,
    PredictionOrigin,
    make_prediction_record,
)
from src.intelligence.reports.market_signal import SignalLevel
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import (
    abstained_kwargs,
    base_kwargs,
    executable_source,
    imported_modules,
    make,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "evaluation_record.py"

CREATED_AT = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)
PREDICTION_ID = "pred_02899d141d42096adcea4f48"          # P5-1A golden（available / LIVE）
REFERENCE_CLOSE, TARGET_CLOSE = Decimal("2700"), Decimal("2718.25")
RETURN = TARGET_CLOSE / REFERENCE_CLOSE - Decimal(1)   # 0.006759259259259259259259259

GOLDEN_EVALUATED_CANONICAL = (
    '{"classification_version":"topix_neutral_band:1.0.0","defer_reason":"",'
    '"prediction_id":"pred_02899d141d42096adcea4f48","realized_outcome":"UP",'
    '"realized_return":"0.006759259259259259259259259","reference_session":"2026-09-16",'
    '"schema_version":"evaluation_record:0.1.0","session_date":"2026-09-17",'
    '"status":"EVALUATED","supersedes_evaluation_id":"",'
    '"target":"index:topix.close.closing.tokyo"}'
)
GOLDEN_EVALUATED_ID = "eval_376c6c939d675d044104a6ea"
GOLDEN_DEFERRED_CANONICAL = (
    '{"classification_version":"topix_neutral_band:1.0.0",'
    '"defer_reason":"target_close_unavailable","prediction_id":"pred_02899d141d42096adcea4f48",'
    '"realized_outcome":"","realized_return":"","reference_session":"2026-09-16",'
    '"schema_version":"evaluation_record:0.1.0","session_date":"2026-09-17",'
    '"status":"DEFERRED","supersedes_evaluation_id":"",'
    '"target":"index:topix.close.closing.tokyo"}'
)
GOLDEN_DEFERRED_ID = "eval_63ca6ce9f3ffaea33b352dda"

FORBIDDEN_FIELD_FRAGMENTS = ("hit", "miss", "correct", "accuracy", "score", "win", "loss",
                             "label", "display", "text", "delivery", "markdown", "html",
                             "path", "level", "confidence", "horizon", "available", "origin")
FORBIDDEN_KWARGS = {"hit": True, "direction_correct": True, "accuracy": "1.0", "score": 1,
                    "label": "上昇", "display_text": "上昇", "delivery_id": "deliv_x",
                    "markdown_sha256": "0" * 64, "level": "UPWARD_LEAN", "available": True}


# ---------------------------------------------------------------- helpers

def verification(**override) -> SessionVerification:
    kwargs = dict(calendar_source_id="jquants:/v2/markets/calendar", trading_divisions=("1",),
                  checked_dates=10, agreements=10, disagreement_count=0,
                  verified_session="2026-09-17", verified_previous_session="2026-09-16")
    kwargs.update(override)
    return SessionVerification(**kwargs)


def evaluated_kwargs(**override) -> dict:
    kwargs = dict(prediction_id=PREDICTION_ID, reference_session="2026-09-16",
                  session_date="2026-09-17", status=EvaluationStatus.EVALUATED,
                  created_at=CREATED_AT, realized_return=RETURN,
                  reference_close=REFERENCE_CLOSE, target_close=TARGET_CLOSE,
                  reference_observation_id="obs_01K3W2AAAAAAAAAAAAAAAAAAAA",
                  target_observation_id="obs_01K3W2BBBBBBBBBBBBBBBBBBBB",
                  source_id="jquants", market_schema_version="0.1.0",
                  session_verification=verification())
    kwargs.update(override)
    return kwargs


def evaluated(**override) -> EvaluationRecord:
    return make_evaluation_record(**evaluated_kwargs(**override))


def deferred_kwargs(**override) -> dict:
    kwargs = dict(prediction_id=PREDICTION_ID, reference_session="2026-09-16",
                  session_date="2026-09-17", status=EvaluationStatus.DEFERRED,
                  created_at=CREATED_AT, defer_reason=DeferReason.TARGET_CLOSE_UNAVAILABLE,
                  reference_close=REFERENCE_CLOSE)
    kwargs.update(override)
    return kwargs


def deferred(**override) -> EvaluationRecord:
    return make_evaluation_record(**deferred_kwargs(**override))


def sha_id(canonical: str) -> str:
    return "eval_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def source() -> str:
    return executable_source(MODULE_PATH)


# ---------------------------------------------------------------- 1–2 valid records

def test_valid_evaluated_record() -> None:                                                # 1
    rec = evaluated()
    assert rec.status is EvaluationStatus.EVALUATED and not rec.is_deferred
    assert rec.realized_outcome is RealizedOutcome.UP
    assert rec.realized_return == RETURN and rec.defer_reason is None
    assert rec.target == TARGET_TOPIX and rec.classification_version == NEUTRAL_BAND_RULE_VERSION
    assert rec.evaluation_id.startswith(EVALUATION_ID_PREFIX + "_") and len(rec.evaluation_id) == 29


def test_valid_deferred_record() -> None:                                                 # 2
    rec = deferred()
    assert rec.is_deferred and rec.realized_return is None and rec.realized_outcome is None
    assert rec.defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE
    assert rec.reference_close == REFERENCE_CLOSE and rec.target_close is None
    assert rec.session_verification is None


# ---------------------------------------------------------------- 3–7 classification boundaries

@pytest.mark.parametrize("text,outcome", [
    ("0.003", RealizedOutcome.RANGE),                 # 3 exact +0.30%
    ("0.003000000000000000000000000000", RealizedOutcome.RANGE),
    ("-0.003", RealizedOutcome.RANGE),                # 4 exact -0.30%
    ("0.0030000000000000000000000000001", RealizedOutcome.UP),      # 5
    ("0.0031", RealizedOutcome.UP),
    ("0.25", RealizedOutcome.UP),
    ("-0.0030000000000000000000000000001", RealizedOutcome.DOWN),   # 6
    ("-0.0031", RealizedOutcome.DOWN),
    ("0", RealizedOutcome.RANGE),                     # 7 zero
    ("-0", RealizedOutcome.RANGE),
    ("0.00299999999", RealizedOutcome.RANGE),
    ("-0.00299999999", RealizedOutcome.RANGE),
])
def test_classification_boundaries_are_decimal_and_inclusive(text: str, outcome: RealizedOutcome) -> None:
    assert classify_realized_return(Decimal(text)) is outcome
    assert NEUTRAL_BAND == Decimal("0.003")
    if outcome is RealizedOutcome.RANGE:
        assert -NEUTRAL_BAND <= Decimal(text) <= NEUTRAL_BAND


def test_boundary_records_round_trip_as_range() -> None:
    for text in ("0.003", "-0.003", "0"):
        rec = evaluated(realized_return=Decimal(text), target_close=REFERENCE_CLOSE * (1 + Decimal(text)))
        assert rec.realized_outcome is RealizedOutcome.RANGE
        assert EvaluationRecord.from_dict(rec.as_dict()) == rec


# ---------------------------------------------------------------- 8–14 Decimal canonicalization

@pytest.mark.parametrize("text,expected", [
    ("0", "0"), ("-0", "0"), ("0E-10", "0"), ("-0.000", "0"), ("0.0100", "0.01"), ("0.01", "0.01"),
    ("1E-7", "0.0000001"), ("1E+3", "1000"), ("3E0", "3"), ("1.50", "1.5"), ("100", "100"),
    ("-0.003", "-0.003"), ("0.003000", "0.003"), ("-123.4500", "-123.45"),
    ("-1E-30", "-0.000000000000000000000000000001"),
])
def test_decimal_canonicalization_table(text: str, expected: str) -> None:                # 8
    assert canonical_decimal(Decimal(text)) == expected
    assert Decimal(expected) == Decimal(text)                       # 情報を落とさない
    assert parse_canonical_decimal(expected, "x") == Decimal(text)


def test_numerically_equal_representations_share_an_identity() -> None:                   # 9
    a = evaluated(realized_return=Decimal("0.01"), target_close=Decimal("2727"))
    b = evaluated(realized_return=Decimal("0.0100"), target_close=Decimal("2727.00"))
    c = evaluated(realized_return=Decimal("1E-2"), target_close=Decimal("2.727E3"))
    assert a.evaluation_id == b.evaluation_id == c.evaluation_id
    assert a.canonical == b.canonical == c.canonical
    assert a.as_dict()["realized_return"] == "0.01"


def test_negative_zero_canonicalizes_to_zero() -> None:                                   # 10
    assert canonical_decimal(Decimal("-0")) == canonical_decimal(Decimal("0")) == "0"
    a = evaluated(realized_return=Decimal("0"), target_close=REFERENCE_CLOSE)
    b = evaluated(realized_return=Decimal("-0.0"), target_close=REFERENCE_CLOSE)
    assert a.evaluation_id == b.evaluation_id and a.realized_outcome is RealizedOutcome.RANGE
    with pytest.raises(InvalidEvaluationRecord):
        parse_canonical_decimal("-0", "x")


def test_very_small_and_high_precision_decimals_are_preserved() -> None:                  # 11
    tiny = Decimal("-1E-30")
    rec = evaluated(realized_return=tiny, target_close=REFERENCE_CLOSE)
    assert rec.realized_outcome is RealizedOutcome.RANGE
    assert EvaluationRecord.from_dict(rec.as_dict()).realized_return == tiny
    forty = Decimal("0." + "1" * 40)
    assert canonical_decimal(forty) == "0." + "1" * 40 and Decimal(canonical_decimal(forty)) == forty
    assert "quantize" not in source() and "round(" not in source()


@pytest.mark.parametrize("field", ["realized_return", "reference_close", "target_close"])
def test_float_is_never_accepted(field: str) -> None:                                     # 12
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(**{field: 0.0067})
    with pytest.raises(InvalidEvaluationRecord):
        canonical_decimal(0.003)                       # type: ignore[arg-type]
    with pytest.raises(InvalidEvaluationRecord):
        classify_realized_return(0.003)                # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["NaN", "sNaN", "-NaN"])
def test_nan_is_rejected(bad: str) -> None:                                               # 13
    with pytest.raises(InvalidEvaluationRecord):
        canonical_decimal(Decimal(bad))
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(realized_return=Decimal(bad))


@pytest.mark.parametrize("bad", ["Infinity", "-Infinity"])
def test_infinity_is_rejected(bad: str) -> None:                                          # 14
    with pytest.raises(InvalidEvaluationRecord):
        canonical_decimal(Decimal(bad))
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(realized_return=Decimal(bad))


@pytest.mark.parametrize("text", ["", "1E-7", "0.0100", "+0.01", " 0.01", "0.01 ", "-0", "1_000",
                                  "0x10", "abc", "1.", ".5", "00.5"])
def test_noncanonical_decimal_strings_are_rejected_on_strict_parse(text: str) -> None:
    with pytest.raises(InvalidEvaluationRecord):
        parse_canonical_decimal(text, "x")


# ---------------------------------------------------------------- 15–17 identity inputs

@pytest.mark.parametrize("bad", ["", "brief_" + "a" * 24, "pred_" + "0" * 23, "pred_" + "G" * 24,
                                 "pred_" + "A" * 24, "PRED_" + "0" * 24, None, 12])
def test_prediction_id_is_required_and_must_be_well_formed(bad) -> None:                 # 15
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(prediction_id=bad)


@pytest.mark.parametrize("bad", ["index:nikkei225.close.closing.tokyo", "TOPIX", "", "index:topix"])
def test_target_is_topix_only(bad: str) -> None:                                          # 16
    assert SUPPORTED_TARGETS == (TARGET_TOPIX,) == ("index:topix.close.closing.tokyo",)
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(target=bad)


@pytest.mark.parametrize("reference,session", [
    ("2026-09-17", "2026-09-17"), ("2026-09-18", "2026-09-17"), ("2026/09/16", "2026-09-17"),
    ("2026-09-16", "20260917"), ("2026-9-16", "2026-09-17"), ("", "2026-09-17"),
])
def test_reference_session_must_precede_session_date_schema_locally(reference: str, session: str) -> None:  # 17
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(reference_session=reference, session_date=session,
                  session_verification=verification(verified_session="2026-09-17",
                                                    verified_previous_session="2026-09-16"))
    assert evaluated(reference_session="2026-09-10",
                     session_verification=verification(verified_previous_session="2026-09-10")
                     ).reference_session == "2026-09-10"   # 隣接性は schema ではなく証拠で担保


# ---------------------------------------------------------------- 18–21 session verification / defer

@pytest.mark.parametrize("label,proof", [
    ("missing", None),
    ("no calendar checked", verification(checked_dates=0, agreements=0)),
    ("disagreement", verification(checked_dates=10, agreements=9, disagreement_count=1)),
    ("wrong session", verification(verified_session="2026-09-18", verified_previous_session="2026-09-17")),
    ("wrong previous session", verification(verified_previous_session="2026-09-15")),
    ("empty source", verification(calendar_source_id="")),
])
def test_evaluated_requires_validated_session_verification(label: str, proof) -> None:   # 18
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(session_verification=proof)
    rec = evaluated()
    assert rec.session_verification.validated
    assert rec.session_verification.verified_session == rec.session_date
    assert rec.session_verification.verified_previous_session == rec.reference_session


def test_deferred_calendar_unverified_is_representable() -> None:                        # 19
    rec = deferred(defer_reason=DeferReason.CALENDAR_UNVERIFIED, reference_close=None)
    assert rec.is_deferred and rec.defer_reason is DeferReason.CALENDAR_UNVERIFIED
    partial = deferred(defer_reason=DeferReason.CALENDAR_UNVERIFIED,
                       session_verification=verification(checked_dates=5, agreements=4, disagreement_count=1))
    assert partial.session_verification is not None and not partial.session_verification.validated
    with pytest.raises(InvalidEvaluationRecord):        # 検証済みカレンダーと矛盾
        deferred(defer_reason=DeferReason.CALENDAR_UNVERIFIED, session_verification=verification())
    unrelated = deferred(defer_reason=DeferReason.REFERENCE_SESSION_UNVERIFIED,
                         session_verification=verification(verified_previous_session="2026-09-12"))
    assert unrelated.defer_reason is DeferReason.REFERENCE_SESSION_UNVERIFIED


def test_deferred_missing_reference_close_is_representable() -> None:                    # 20
    rec = deferred(defer_reason=DeferReason.REFERENCE_CLOSE_UNAVAILABLE, reference_close=None,
                   target_close=TARGET_CLOSE, session_verification=verification())
    assert rec.reference_close is None and rec.target_close == TARGET_CLOSE
    with pytest.raises(InvalidEvaluationRecord):
        deferred(defer_reason=DeferReason.REFERENCE_CLOSE_UNAVAILABLE, reference_close=REFERENCE_CLOSE)


def test_deferred_missing_target_close_is_representable() -> None:                       # 21
    rec = deferred(defer_reason=DeferReason.TARGET_CLOSE_UNAVAILABLE)
    assert rec.target_close is None and rec.reference_close == REFERENCE_CLOSE
    with pytest.raises(InvalidEvaluationRecord):
        deferred(defer_reason=DeferReason.TARGET_CLOSE_UNAVAILABLE, target_close=TARGET_CLOSE)


def test_defer_reason_vocabulary_is_small_and_fail_closed() -> None:
    assert [r.value for r in DeferReason] == [
        "calendar_unverified", "reference_session_unverified", "reference_close_unavailable",
        "target_close_unavailable", "observation_invalid", "source_unsupported"]
    for reason in DeferReason:
        rec = deferred(defer_reason=reason, reference_close=None)
        assert rec.is_deferred and rec.defer_reason is reason
    with pytest.raises(InvalidEvaluationRecord):
        deferred(defer_reason="abstained")             # type: ignore[arg-type]


# ---------------------------------------------------------------- 22–25 contradictions / versions

@pytest.mark.parametrize("override", [
    dict(realized_return=None, realized_outcome=None),          # return 無し
    dict(realized_return=None, realized_outcome=RealizedOutcome.UP),
    dict(realized_outcome=None, realized_return=None),
    dict(defer_reason=DeferReason.OBSERVATION_INVALID),         # defer reason あり
    dict(reference_close=None),                                 # provenance 無し
    dict(target_close=None),
    dict(reference_close=Decimal("0")),                         # 非正の close
    dict(target_close=Decimal("-1")),
])
def test_evaluated_contradictions_are_rejected(override: dict) -> None:                  # 22
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(**override)


def test_evaluated_without_outcome_is_rejected_at_the_dataclass_boundary() -> None:
    rec = evaluated()
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord(**{**dataclasses.asdict(rec), "realized_outcome": None,
                            "session_verification": rec.session_verification})


@pytest.mark.parametrize("override", [
    dict(realized_return=RETURN),                               # return あり
    dict(realized_outcome=RealizedOutcome.RANGE),               # outcome あり
    dict(defer_reason=None),                                    # reason 無し
    dict(defer_reason="target_close_unavailable"),              # enum でない
])
def test_deferred_contradictions_are_rejected(override: dict) -> None:                   # 23
    with pytest.raises(InvalidEvaluationRecord):
        deferred(**override)


@pytest.mark.parametrize("text,wrong", [
    ("0.01", RealizedOutcome.RANGE), ("0.01", RealizedOutcome.DOWN),
    ("0.003", RealizedOutcome.UP), ("-0.003", RealizedOutcome.DOWN),
    ("-0.02", RealizedOutcome.RANGE), ("0", RealizedOutcome.UP),
])
def test_outcome_inconsistent_with_return_is_rejected(text: str, wrong: RealizedOutcome) -> None:  # 24
    with pytest.raises(InvalidEvaluationRecord, match="contradicts"):
        evaluated(realized_return=Decimal(text), realized_outcome=wrong)


def test_three_version_concepts_are_separate_and_unknown_versions_fail() -> None:        # 25
    assert EVALUATION_RECORD_SCHEMA_VERSION == "evaluation_record:0.1.0"
    assert NEUTRAL_BAND_RULE_VERSION == "topix_neutral_band:1.0.0"
    assert PREDICTION_RECORD_SCHEMA_VERSION == "prediction_record:0.1.0"
    assert len({EVALUATION_RECORD_SCHEMA_VERSION, NEUTRAL_BAND_RULE_VERSION,
                PREDICTION_RECORD_SCHEMA_VERSION}) == 3
    assert SUPPORTED_CLASSIFICATION_VERSIONS == (NEUTRAL_BAND_RULE_VERSION,)
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(classification_version="topix_neutral_band:1.1.0")
    with pytest.raises(InvalidEvaluationRecord):
        classify_realized_return(Decimal("0.01"), classification_version="topix_neutral_band:2.0.0")
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord.from_dict({**evaluated().as_dict(), "schema_version": "evaluation_record:0.2.0"})
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord.from_dict({**evaluated().as_dict(), "schema_version": "prediction_record:0.1.0"})


# ---------------------------------------------------------------- 26–31 identity

def test_deterministic_evaluation_id_matches_golden_and_independent_sha256() -> None:    # 26
    rec = evaluated()
    assert rec.canonical == GOLDEN_EVALUATED_CANONICAL
    assert rec.evaluation_id == GOLDEN_EVALUATED_ID == sha_id(GOLDEN_EVALUATED_CANONICAL)
    d = deferred()
    assert d.canonical == GOLDEN_DEFERRED_CANONICAL
    assert d.evaluation_id == GOLDEN_DEFERRED_ID == sha_id(GOLDEN_DEFERRED_CANONICAL)
    assert evaluated().evaluation_id == rec.evaluation_id
    assert IDENTITY_KEYS == tuple(sorted(IDENTITY_KEYS)) and len(IDENTITY_KEYS) == 11
    assert tuple(sorted(rec.identity_payload())) == IDENTITY_KEYS
    assert None not in rec.identity_payload().values()
    with pytest.raises(InvalidEvaluationRecord):
        canonical_identity({**rec.identity_payload(), "created_at": "x"})


def test_created_at_change_does_not_change_evaluation_id() -> None:                      # 27
    a, b = evaluated(), evaluated(created_at=CREATED_AT + timedelta(days=3))
    assert a.evaluation_id == b.evaluation_id and a != b
    assert "created_at" not in a.identity_payload()


@pytest.mark.parametrize("override", [
    dict(reference_close=Decimal("2700.00")),                     # 同値の別表現
    dict(reference_observation_id="obs_01K3W2CCCCCCCCCCCCCCCCCCCC"),
    dict(target_observation_id=""),
    dict(source_id="jquants_v2"),
    dict(market_schema_version="0.2.0"),
    dict(session_verification=verification(checked_dates=250, agreements=250)),
])
def test_provenance_change_keeps_identity_but_not_equality(override: dict) -> None:      # 28
    base, other = evaluated(), evaluated(**override)
    assert other.evaluation_id == base.evaluation_id
    assert (other == base) is (override == dict(reference_close=Decimal("2700.00")))
    for key in ("reference_close", "target_close", "reference_observation_id",
                "target_observation_id", "source_id", "market_schema_version",
                "session_verification"):
        assert key not in base.identity_payload()


@pytest.mark.parametrize("override", [
    dict(realized_return=Decimal("0.0068"), target_close=Decimal("2718.36")),
    dict(realized_return=Decimal("-0.01"), target_close=Decimal("2673")),
    dict(session_date="2026-09-18", session_verification=verification(verified_session="2026-09-18", verified_previous_session="2026-09-16")),
    dict(reference_session="2026-09-15", session_verification=verification(verified_previous_session="2026-09-15")),
])
def test_semantic_change_changes_evaluation_id(override: dict) -> None:                  # 29
    assert evaluated(**override).evaluation_id != evaluated().evaluation_id


def test_status_and_defer_reason_participate_in_identity() -> None:
    assert evaluated().evaluation_id != deferred().evaluation_id
    ids = {deferred(defer_reason=r, reference_close=None).evaluation_id for r in DeferReason}
    assert len(ids) == len(DeferReason)
    payload = evaluated().identity_payload()
    assert make_evaluation_id({**payload, "target": "index:other"}) != make_evaluation_id(payload)
    assert make_evaluation_id({**payload, "schema_version": "evaluation_record:0.2.0"}) != make_evaluation_id(payload)
    assert make_evaluation_id({**payload, "classification_version": "topix_neutral_band:2.0.0"}) != make_evaluation_id(payload)


def test_prediction_id_change_changes_evaluation_id() -> None:                           # 30
    other = "pred_" + "f" * 24
    assert evaluated(prediction_id=other).evaluation_id != evaluated().evaluation_id
    assert deferred(prediction_id=other).evaluation_id != deferred().evaluation_id


def test_superseding_correction_gets_a_new_evaluation_id() -> None:                      # 31
    original = evaluated()
    same_values = evaluated(supersedes_evaluation_id=original.evaluation_id)
    assert same_values.evaluation_id != original.evaluation_id and same_values.is_correction
    corrected = evaluated(realized_return=Decimal("0.0068"), target_close=Decimal("2718.36"),
                          supersedes_evaluation_id=original.evaluation_id)
    assert corrected.evaluation_id not in {original.evaluation_id, same_values.evaluation_id}
    assert corrected.supersedes_evaluation_id == original.evaluation_id
    assert not original.is_correction and original.supersedes_evaluation_id == ""
    assert "supersedes_evaluation_id" in original.identity_payload()


# ---------------------------------------------------------------- 32–36 supersession / immutability / forgery

@pytest.mark.parametrize("bad", ["eval_" + "0" * 23, "pred_" + "0" * 24, "eval_" + "A" * 24, "x", 5])
def test_malformed_supersedes_id_is_rejected(bad) -> None:
    with pytest.raises(InvalidEvaluationRecord):
        evaluated(supersedes_evaluation_id=bad)


def test_self_supersession_is_rejected() -> None:                                        # 32
    rec = evaluated()
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord(**{**dataclasses.asdict(rec), "session_verification": rec.session_verification,
                            "supersedes_evaluation_id": rec.evaluation_id})
    assert "cannot supersede itself" in source()      # id は supersedes を含む payload の hash なので構造的にも不可能


def test_original_record_remains_immutable_after_a_correction() -> None:                 # 33
    original = evaluated()
    snapshot = original.as_dict()
    corrected = evaluated(realized_return=Decimal("0.0068"), target_close=Decimal("2718.36"),
                          supersedes_evaluation_id=original.evaluation_id)
    assert original.as_dict() == snapshot and corrected.as_dict() != snapshot
    src = source()
    for token in ("def update", "def replace", "def supersede", "def correct", "dataclasses.replace",
                  "object.__setattr__", "latest", "current"):
        assert token not in src, token


def test_records_are_frozen() -> None:                                                   # 34
    rec = evaluated()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.realized_outcome = RealizedOutcome.DOWN     # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.session_verification.checked_dates = 0      # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        del rec.prediction_id                           # type: ignore[attr-defined]


@pytest.mark.parametrize("forged", ["eval_" + "0" * 24, "", GOLDEN_DEFERRED_ID, "brief_x"])
def test_forged_evaluation_id_is_rejected(forged: str) -> None:                         # 35
    rec = evaluated()
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord(**{**dataclasses.asdict(rec), "session_verification": rec.session_verification,
                            "evaluation_id": forged})
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord.from_dict({**rec.as_dict(), "evaluation_id": forged})
    tampered = {**rec.as_dict(), "realized_return": "0.0068", "target_close": "2718.36"}
    with pytest.raises(InvalidEvaluationRecord):        # 意味論を変えて id 据え置き
        EvaluationRecord.from_dict(tampered)


def test_unknown_and_missing_fields_are_rejected() -> None:                              # 36
    data = evaluated().as_dict()
    for name, value in FORBIDDEN_KWARGS.items():
        with pytest.raises(InvalidEvaluationRecord):
            EvaluationRecord.from_dict({**data, name: value})
        with pytest.raises(TypeError):
            make_evaluation_record(**evaluated_kwargs(), **{name: value})
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord.from_dict({k: v for k, v in data.items() if k != "created_at"})
    with pytest.raises(InvalidEvaluationRecord):
        EvaluationRecord.from_dict({**data, "session_verification": {**data["session_verification"], "extra": 1}})
    with pytest.raises(InvalidEvaluationRecord):
        SessionVerification.from_dict({k: v for k, v in data["session_verification"].items() if k != "agreements"})


# ---------------------------------------------------------------- 37 round-trip

@pytest.mark.parametrize("factory", [
    lambda: evaluated(),
    lambda: evaluated(realized_return=Decimal("-0.003"), target_close=Decimal("2691.9")),
    lambda: deferred(),
    lambda: deferred(defer_reason=DeferReason.CALENDAR_UNVERIFIED, reference_close=None),
    lambda: evaluated(supersedes_evaluation_id=GOLDEN_EVALUATED_ID, realized_return=Decimal("0.0068"),
                      target_close=Decimal("2718.36")),
])
def test_deterministic_round_trip(factory) -> None:                                      # 37
    rec = factory()
    encoded = json.dumps(rec.as_dict(), ensure_ascii=False, sort_keys=True)
    back = EvaluationRecord.from_dict(json.loads(encoded))
    assert back == rec and back.evaluation_id == rec.evaluation_id
    assert json.dumps(back.as_dict(), ensure_ascii=False, sort_keys=True) == encoded
    assert set(rec.as_dict()) == {f.name for f in dataclasses.fields(EvaluationRecord)}


def test_from_dict_rejects_noncanonical_decimal_fields() -> None:
    data = evaluated().as_dict()
    for field, bad in (("realized_return", "0.006759259259259259259259259000"),
                       ("reference_close", "2700.0"), ("target_close", "2.71825E3"),
                       ("realized_return", 0.0067), ("reference_close", 2700)):
        with pytest.raises(InvalidEvaluationRecord):
            EvaluationRecord.from_dict({**data, field: bad})


def test_from_dict_rejects_bad_enums_and_timestamps() -> None:
    data = evaluated().as_dict()
    for field, bad in (("status", "PENDING"), ("realized_outcome", "NEUTRAL_RANGE"),
                       ("defer_reason", "abstained"), ("status", None),
                       ("created_at", "2026-09-18T08:00:00"), ("created_at", ""), ("created_at", None)):
        with pytest.raises(InvalidEvaluationRecord):
            EvaluationRecord.from_dict({**data, field: bad})


# ---------------------------------------------------------------- 38–40 forbidden concepts

def test_no_accuracy_hit_miss_or_prediction_copy_fields() -> None:                       # 38
    names = [f.name for f in dataclasses.fields(EvaluationRecord)] + \
            [f.name for f in dataclasses.fields(SessionVerification)]
    for name in names:
        for fragment in FORBIDDEN_FIELD_FRAGMENTS:
            assert fragment not in name.lower(), (name, fragment)
    # "missing … fields" の error 文言は miss ではなく、is_correction は supersession（訂正）であって正誤ではない
    src = source().replace("missing", "").replace("is_correction", "")
    for token in ("hit", "miss", "correct", "accuracy", "score", "win", "loss", "brier",
                  "calibration", "SignalLevel", "UPWARD_LEAN", "NEUTRAL_RANGE"):
        assert token not in src, token


def test_realized_outcome_vocabulary_is_distinct_from_prediction_levels() -> None:
    assert [o.value for o in RealizedOutcome] == ["UP", "RANGE", "DOWN"]
    assert {o.value for o in RealizedOutcome}.isdisjoint({l.value for l in SignalLevel})
    assert [s.value for s in EvaluationStatus] == ["EVALUATED", "DEFERRED"]


def test_no_display_or_customer_fields() -> None:                                        # 39
    keys = set(evaluated().as_dict())
    assert keys.isdisjoint(FORBIDDEN_KWARGS)
    src = source()
    for token in ("label", "display", "customer", "delivery", "markdown", "html", "上昇", "下落"):
        assert token not in src, token


def test_no_prediction_record_mutation_api() -> None:                                    # 40
    src = source()
    assert "PredictionRecord(" not in src and "PredictionRecord" not in src
    assert imported_modules(MODULE_PATH) & {".prediction_record"} == {".prediction_record"}
    assert "PREDICTION_ID_PREFIX" in src and "make_prediction_record" not in src
    for token in ("setattr", "__dict__", "replace("):
        assert token not in src, token
    prediction = make()
    before = prediction.as_dict()
    evaluated(prediction_id=prediction.prediction_id)
    assert prediction.as_dict() == before


# ---------------------------------------------------------------- 41–47 dependency boundary

def test_no_market_lookup() -> None:                                                     # 41
    src = source()
    for token in ("market.", "MarketBank", "observations.jsonl", "Observation(", "series_id",
                  "store", "backfill", "ingest"):
        assert token not in src, token


def test_no_calendar_lookup() -> None:                                                   # 42
    src = source()
    for token in ("tokyo_calendar", "trading_days", "latest_completed_session", "validate_divisions",
                  "weekday", "timedelta", "calendar_rows", "HolDiv"):
        assert token not in src, token


def test_no_network() -> None:                                                           # 43
    src = source()
    for token in ("urllib", "requests", "http", "socket", "environ", "getenv"):
        assert token not in src, token


def test_no_jquants() -> None:                                                           # 44
    assert "jquants" not in source().lower()


def test_no_store_or_persistence() -> None:                                              # 45
    src = source()
    for token in ("open(", "write", "jsonl", "Path(", "mkdir", "fsync", "sqlite", "prediction_store",
                  "PredictionStore", " git", "git.", "subprocess"):
        assert token not in src, token


def test_no_calibration_dependency() -> None:                                            # 46
    allowed = {"__future__", "json", "dataclasses", "datetime", "decimal", "enum", "string",
               "typing", "..core.ids", "..core.time", ".prediction_record"}
    assert imported_modules(MODULE_PATH) <= allowed
    for token in ("calibration", "aggregate", "coverage", "statistics", "mean("):
        assert token not in source(), token


def test_no_runtime_or_public_integration() -> None:                                     # 47
    assert "predictions" in EXCLUDED_PACKAGES
    assert not any("predictions" in m for m in runtime_closure())
    offenders = [str(p.relative_to(REPO_ROOT))
                 for p in list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py"))
                 if p.parent != MODULE_PATH.parent and "evaluation_record" in p.read_text(encoding="utf-8")]
    assert offenders == []
    for token in ("argparse", "__main__", "pages", "publish", "notification"):
        assert token not in source(), token


# ---------------------------------------------------------------- 48–50 origin / availability / time

def test_live_and_replay_distinction_survives_via_prediction_id() -> None:               # 48
    live = make_prediction_record(**base_kwargs())
    replay = make_prediction_record(**base_kwargs(origin=PredictionOrigin.REPLAY))
    assert live.prediction_id != replay.prediction_id
    a, b = evaluated(prediction_id=live.prediction_id), evaluated(prediction_id=replay.prediction_id)
    assert a.evaluation_id != b.evaluation_id
    assert "origin" not in {f.name for f in dataclasses.fields(EvaluationRecord)}


def test_unavailable_prediction_is_not_automatically_deferred() -> None:                 # 49
    abstained = make_prediction_record(**abstained_kwargs())
    assert abstained.is_abstention
    rec = evaluated(prediction_id=abstained.prediction_id)      # outcome は市場側の事実として表現できる
    assert rec.status is EvaluationStatus.EVALUATED and rec.realized_outcome is RealizedOutcome.UP
    assert "available" not in {f.name for f in dataclasses.fields(EvaluationRecord)}
    assert "abstain" not in source() and "is_abstention" not in source()


def test_no_datetime_now_and_created_at_is_explicit_and_aware() -> None:                 # 50
    src = source()
    for token in ("now(", "utcnow", "time.time", "date.today"):
        assert token not in src, token
    assert inspect.signature(make_evaluation_record).parameters["created_at"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        make_evaluation_record(**{k: v for k, v in evaluated_kwargs().items() if k != "created_at"})
    with pytest.raises(ValueError):
        evaluated(created_at=datetime(2026, 9, 18, 8, 0))
    assert evaluated().as_dict()["created_at"] == "2026-09-18T08:00:00+00:00"


# ---------------------------------------------------------------- SessionVerification invariants

@pytest.mark.parametrize("override", [
    dict(checked_dates=-1), dict(agreements=11), dict(disagreement_count=-1),
    dict(checked_dates=True), dict(trading_divisions=()), dict(trading_divisions=("1", "")),
    dict(verified_session="2026/09/17"), dict(verified_previous_session="2026-09-17"),
    dict(calendar_source_id=None), dict(trading_divisions=["1"]),
])
def test_session_verification_invariants(override: dict) -> None:
    with pytest.raises(InvalidEvaluationRecord):
        verification(**override)


def test_session_verification_round_trip_and_validated_rule() -> None:
    proof = verification()
    assert SessionVerification.from_dict(proof.as_dict()) == proof and proof.validated
    assert not verification(checked_dates=0, agreements=0).validated
    assert not verification(agreements=9, disagreement_count=1).validated
    assert not verification(calendar_source_id="").validated
    with pytest.raises(InvalidEvaluationRecord):
        SessionVerification.from_dict({**proof.as_dict(), "validated": True})
