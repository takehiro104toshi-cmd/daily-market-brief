"""Phase 5 P5-1A — PredictionRecord schema ＋ deterministic identity の凍結ガード。

証明する柱（`docs/databank/PHASE5_ENTRY_CONTRACT.md` N-1 / §5 / §6 / §7 / §11）:

- identity は**意味論だけ**から決まる（provenance / audit / 表示を変えても同じ ID）
- 意味論のどれか 1 つを変えれば**別 ID**（LIVE / REPLAY を含む）
- canonical 直列化は独立実装（hashlib）で再現できる golden 値に一致する
- P4 凍結語彙の外・矛盾状態・session 順序違反・naive datetime は fail closed
- 表示文字列 / delivery_id / realized outcome / 評価状態を**受け取る口が無い**
- 不変（frozen）・偽造 prediction_id の拒否・round-trip
- dependency boundary（network / store / calendar / jquants / persistence を import しない）
- 本番 runtime closure から到達不能（`predictions` は EXCLUDED_PACKAGES）
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.compass.config import CompassConfig
from src.intelligence.compass.model import Confidence
from src.intelligence.predictions import prediction_record as pr
from src.intelligence.predictions.prediction_record import (
    APPROVED_LEVEL_CONFIDENCE_PAIRS,
    CONFIDENCES,
    IDENTITY_KEYS,
    KNOWN_HORIZONS,
    PREDICTION_ID_PREFIX,
    PREDICTION_RECORD_SCHEMA_VERSION,
    REASONS_WITH_OUTLOOK_STATE,
    SIGNAL_LEVELS,
    UNAVAILABLE_REASONS,
    InvalidPredictionRecord,
    PredictionOrigin,
    PredictionRecord,
    canonical_identity,
    identity_payload,
    make_prediction_id,
    make_prediction_record,
)
from src.intelligence.reports import delivery
from src.intelligence.reports.market_signal import (
    APPROVED_UNAVAILABLE_REASONS,
    LEVEL_BY_STATE,
    MARKET_SIGNAL_SCHEMA_VERSION,
    SignalLevel,
)
from src.intelligence.reports.model import MORNING_BRIEF_SCHEMA_VERSION
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "prediction_record.py"

RECORDED_AT = datetime(2026, 9, 17, 6, 30, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)
JST = timezone(timedelta(hours=9))

#: golden（テスト内で hashlib により独立再計算する。module の実装に依存しない）
GOLDEN_AVAILABLE_CANONICAL = (
    '{"available":true,"confidence":"HIGH","horizon":"next_tokyo_session",'
    '"level":"UPWARD_LEAN","origin":"LIVE","reference_session":"2026-09-16",'
    '"schema_version":"prediction_record:0.1.0","session_date":"2026-09-17",'
    '"unavailable_reason":""}'
)
GOLDEN_AVAILABLE_ID = "pred_02899d141d42096adcea4f48"
GOLDEN_ABSTAINED_CANONICAL = (
    '{"available":false,"confidence":"","horizon":"","level":"","origin":"LIVE",'
    '"reference_session":"2026-09-16","schema_version":"prediction_record:0.1.0",'
    '"session_date":"2026-09-17","unavailable_reason":"draft_abstained"}'
)
GOLDEN_ABSTAINED_ID = "pred_498520a7861eede97e821711"

#: 表示 / 配信 / 結果 / 評価に属し、schema に**存在してはならない**名前の断片
FORBIDDEN_FIELD_FRAGMENTS = (
    "realized", "outcome", "evaluation", "evaluated", "threshold", "band", "return",
    "close", "markdown", "delivery", "label", "display", "text", "html", "score", "hit",
)

#: 受け取る口が無いことを証明する kwargs
FORBIDDEN_KWARGS = {
    "display_text": "上昇バイアス",
    "label": "上昇バイアス",
    "delivery_id": "deliv_x",
    "markdown_sha256": "0" * 64,
    "realized_return": "0.0031",
    "realized_outcome": "UP",
    "evaluation_status": "PENDING",
    "neutral_band_version": "topix_neutral_band:1.0.0",
}


# ---------------------------------------------------------------- helpers

def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return tree


def executable_source(path: Path = MODULE_PATH) -> str:
    return ast.unparse(_strip_docstrings(ast.parse(path.read_text(encoding="utf-8"))))


def imported_modules(path: Path = MODULE_PATH) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(("." * node.level) + node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def base_kwargs(**override) -> dict:
    kwargs = dict(
        session_date="2026-09-17", reference_session="2026-09-16",
        origin=PredictionOrigin.LIVE, available=True, level=SignalLevel.UPWARD_LEAN,
        confidence=Confidence.HIGH.value, horizon="next_tokyo_session", unavailable_reason="",
        brief_id="brief_" + "a" * 24, signal_id="sig_" + "b" * 24,
        morning_brief_schema_version=MORNING_BRIEF_SCHEMA_VERSION,
        market_signal_schema_version=MARKET_SIGNAL_SCHEMA_VERSION,
        recorded_at=RECORDED_AT,
    )
    kwargs.update(override)
    return kwargs


def make(**override) -> PredictionRecord:
    return make_prediction_record(**base_kwargs(**override))


def abstained_kwargs(**override) -> dict:
    return base_kwargs(**{"available": False, "level": None, "confidence": "", "horizon": "",
                          "unavailable_reason": "draft_abstained", **override})


def mixed_kwargs(**override) -> dict:
    return base_kwargs(**{"available": False, "level": None,
                          "confidence": Confidence.MEDIUM.value,
                          "horizon": "next_tokyo_session",
                          "unavailable_reason": "direction_mixed", **override})


def sha_id(canonical: str) -> str:
    """module に依存しない独立実装（N-1 の直列化契約そのもの）。"""
    return "pred_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------- valid records（§6 / §11-3）

def test_available_record_is_valid_and_not_abstention() -> None:
    rec = make()
    assert rec.available is True
    assert rec.level is SignalLevel.UPWARD_LEAN
    assert rec.is_abstention is False
    assert rec.prediction_id.startswith(PREDICTION_ID_PREFIX + "_")
    assert len(rec.prediction_id) == len(PREDICTION_ID_PREFIX) + 1 + 24


def test_neutral_range_is_available_and_not_abstention() -> None:
    rec = make(level=SignalLevel.NEUTRAL_RANGE, confidence=Confidence.LOW.value)
    assert rec.available is True
    assert rec.level is SignalLevel.NEUTRAL_RANGE
    assert rec.is_abstention is False


def test_abstained_record_carries_no_level_confidence_or_horizon() -> None:
    rec = make_prediction_record(**abstained_kwargs())
    assert rec.is_abstention is True
    assert rec.level is None and rec.confidence == "" and rec.horizon == ""
    assert rec.unavailable_reason == "draft_abstained"


@pytest.mark.parametrize("reason", REASONS_WITH_OUTLOOK_STATE)
def test_direction_unavailable_keeps_outlook_confidence_and_horizon(reason: str) -> None:
    rec = make_prediction_record(**mixed_kwargs(unavailable_reason=reason))
    assert rec.is_abstention is True
    assert rec.level is None
    assert rec.confidence == Confidence.MEDIUM.value
    assert rec.horizon == "next_tokyo_session"


@pytest.mark.parametrize("reason", [r for r in UNAVAILABLE_REASONS
                                    if r not in REASONS_WITH_OUTLOOK_STATE])
def test_every_non_direction_unavailable_reason_is_accepted_with_empty_state(reason: str) -> None:
    rec = make_prediction_record(**abstained_kwargs(unavailable_reason=reason))
    assert rec.unavailable_reason == reason and rec.confidence == "" and rec.horizon == ""


@pytest.mark.parametrize("level,confidence", APPROVED_LEVEL_CONFIDENCE_PAIRS)
def test_every_p4_producible_state_is_accepted(level: str, confidence: str) -> None:
    rec = make(level=SignalLevel(level), confidence=confidence)
    assert (rec.level.value, rec.confidence) == (level, confidence)


# ---------------------------------------------------------------- contradictory states（fail closed）

@pytest.mark.parametrize("override", [
    dict(level=None),                                    # available なのに level 無し
    dict(unavailable_reason="draft_abstained"),          # available なのに理由あり
    dict(confidence=""),                                 # available なのに confidence 空
    dict(horizon=""),                                    # available なのに horizon 空
])
def test_available_contradictions_are_rejected(override: dict) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(**override)


@pytest.mark.parametrize("override", [
    dict(level=SignalLevel.UPWARD_LEAN),                 # unavailable なのに level あり
    dict(unavailable_reason=""),                         # unavailable なのに理由無し
    dict(confidence=Confidence.LOW.value),               # draft_abstained に confidence
    dict(horizon="next_tokyo_session"),                  # draft_abstained に horizon
])
def test_unavailable_contradictions_are_rejected(override: dict) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make_prediction_record(**abstained_kwargs(**override))


@pytest.mark.parametrize("override", [
    dict(confidence=""),                                 # direction_mixed は confidence を持つ
    dict(horizon=""),                                    # direction_mixed は horizon を持つ
    dict(level=SignalLevel.NEUTRAL_RANGE),               # MIXED を中立に畳まない
])
def test_direction_mixed_contradictions_are_rejected(override: dict) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make_prediction_record(**mixed_kwargs(**override))


def test_available_must_be_a_real_bool() -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(available=1)   # type: ignore[arg-type]


# ---------------------------------------------------------------- vocabulary（frozen P4）

@pytest.mark.parametrize("bad_level", ["MIXED", "UNCERTAIN", "UP", "NEUTRAL", "upward_lean"])
def test_non_signal_level_values_are_rejected(bad_level: str) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(level=bad_level)   # type: ignore[arg-type]


@pytest.mark.parametrize("bad_confidence", ["VERY_HIGH", "high", "", "NONE"])
def test_unknown_confidence_is_rejected(bad_confidence: str) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(confidence=bad_confidence)


@pytest.mark.parametrize("bad_horizon", ["next_week", "next_session", "NEXT_TOKYO_SESSION", "1d"])
def test_unknown_horizon_is_rejected(bad_horizon: str) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(horizon=bad_horizon)


@pytest.mark.parametrize("level,confidence", [
    (SignalLevel.NEUTRAL_RANGE, Confidence.HIGH.value),
    (SignalLevel.NEUTRAL_RANGE, Confidence.MEDIUM.value),
    (SignalLevel.UPWARD_LEAN, Confidence.LOW.value),
    (SignalLevel.DOWNWARD_LEAN, Confidence.LOW.value),
    (SignalLevel.SLIGHT_UPWARD_LEAN, Confidence.HIGH.value),
    (SignalLevel.SLIGHT_DOWNWARD_LEAN, Confidence.MEDIUM.value),
])
def test_pairs_p4_never_produces_are_rejected(level: SignalLevel, confidence: str) -> None:
    assert (level.value, confidence) not in APPROVED_LEVEL_CONFIDENCE_PAIRS
    with pytest.raises(InvalidPredictionRecord):
        make(level=level, confidence=confidence)


@pytest.mark.parametrize("bad_reason", ["unknown", "MIXED", "abstained", "direction_mixed "])
def test_unknown_unavailable_reason_is_rejected(bad_reason: str) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make_prediction_record(**abstained_kwargs(unavailable_reason=bad_reason))


def test_origin_must_be_the_enum() -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(origin="LIVE")   # type: ignore[arg-type]


# ---------------------------------------------------------------- sessions（schema-local only）

@pytest.mark.parametrize("reference", ["2026-09-17", "2026-09-18", "2027-01-01"])
def test_reference_session_must_precede_session_date(reference: str) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(reference_session=reference)


@pytest.mark.parametrize("field,value", [
    ("session_date", "2026/09/17"), ("session_date", "20260917"), ("session_date", "2026-9-17"),
    ("session_date", ""), ("reference_session", "2026-09-16T00:00:00"),
    ("reference_session", "yesterday"), ("reference_session", "2026-09-16 "),
])
def test_non_canonical_iso_dates_are_rejected(field: str, value: str) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(**{field: value})


def test_schema_does_not_require_adjacent_sessions() -> None:
    """「直前の**検証済み**取引 session」は P5-2 の verified-calendar 境界。schema は順序のみ。"""
    rec = make(reference_session="2026-09-10")
    assert rec.reference_session == "2026-09-10"


def test_module_holds_no_calendar_or_weekday_logic() -> None:
    src = executable_source()
    for token in ("weekday(", "timedelta(", "isoweekday(", "calendar", "trading_days",
                  "latest_completed_session"):
        assert token not in src, token


# ---------------------------------------------------------------- deterministic identity（N-1）

def test_golden_canonical_and_id_for_available_record() -> None:
    rec = make()
    assert rec.canonical == GOLDEN_AVAILABLE_CANONICAL
    assert rec.prediction_id == GOLDEN_AVAILABLE_ID == sha_id(GOLDEN_AVAILABLE_CANONICAL)


def test_golden_canonical_and_id_for_abstained_record() -> None:
    rec = make_prediction_record(**abstained_kwargs())
    assert rec.canonical == GOLDEN_ABSTAINED_CANONICAL
    assert rec.prediction_id == GOLDEN_ABSTAINED_ID == sha_id(GOLDEN_ABSTAINED_CANONICAL)


def test_identity_is_reproducible_across_independent_constructions() -> None:
    assert make().prediction_id == make().prediction_id
    a = make_prediction_record(**mixed_kwargs())
    b = make_prediction_record(**mixed_kwargs())
    assert a.prediction_id == b.prediction_id


def test_identity_payload_has_exactly_the_nine_sorted_keys_and_no_null() -> None:
    assert IDENTITY_KEYS == tuple(sorted(IDENTITY_KEYS)) and len(IDENTITY_KEYS) == 9
    for rec in (make(), make_prediction_record(**abstained_kwargs())):
        payload = rec.identity_payload()
        assert tuple(sorted(payload)) == IDENTITY_KEYS
        assert None not in payload.values()
        assert all(isinstance(v, (str, bool)) for v in payload.values())
        for forbidden in ("brief_id", "signal_id", "package_id", "draft_id", "recorded_at",
                          "cutoff", "principle_refs", "market_principle_version",
                          "morning_brief_schema_version", "market_signal_schema_version",
                          "prediction_id"):
            assert forbidden not in payload


def test_canonical_serialization_is_compact_sorted_utf8_json() -> None:
    canonical = make().canonical
    assert " " not in canonical and "\n" not in canonical
    assert json.loads(canonical) == make().identity_payload()
    assert list(json.loads(canonical)) == list(IDENTITY_KEYS)


def test_canonical_identity_rejects_drifted_keys() -> None:
    payload = make().identity_payload()
    with pytest.raises(InvalidPredictionRecord):
        canonical_identity({**payload, "brief_id": "brief_x"})
    with pytest.raises(InvalidPredictionRecord):
        canonical_identity({k: v for k, v in payload.items() if k != "origin"})


def test_make_prediction_id_uses_prefix_and_24_hex() -> None:
    pid = make_prediction_id(make().identity_payload())
    assert pid[:5] == PREDICTION_ID_PREFIX + "_"
    assert len(pid) == 29 and all(c in "0123456789abcdef" for c in pid[5:])


# ---------------------------------------------------------------- provenance exclusion（N-1）

@pytest.mark.parametrize("override", [
    dict(brief_id="brief_" + "c" * 24),
    dict(signal_id="sig_" + "d" * 24),
    dict(package_id="pkg_" + "e" * 24),
    dict(draft_id="draft_" + "f" * 24),
    dict(recorded_at=RECORDED_AT + timedelta(days=3)),
    dict(cutoff=CUTOFF),
    dict(principle_refs=("MP-01", "MP-07")),
    dict(market_principle_version="market_rules:9.9.9"),
    dict(outlook_rule_version="outlook:1.0.0"),
])
def test_same_semantics_with_different_provenance_or_audit_gives_same_id(override: dict) -> None:
    base = make()
    other = make(**override)
    assert other != base                       # provenance / audit は違う
    assert other.prediction_id == base.prediction_id
    assert other.canonical == base.canonical


def test_same_instant_in_another_timezone_is_the_same_record_and_id() -> None:
    base, other = make(), make(recorded_at=RECORDED_AT.astimezone(JST))
    assert other == base and other.prediction_id == base.prediction_id
    assert other.as_dict()["recorded_at"] == base.as_dict()["recorded_at"]


def test_same_semantics_with_all_provenance_changed_at_once_gives_same_id() -> None:
    other = make(brief_id="brief_" + "1" * 24, signal_id="sig_" + "2" * 24,
                 package_id="pkg_" + "3" * 24, draft_id="draft_" + "4" * 24,
                 recorded_at=RECORDED_AT + timedelta(hours=9), cutoff=CUTOFF,
                 principle_refs=("MP-03",), market_principle_version="x",
                 outlook_rule_version="outlook:1.0.0")
    assert other.prediction_id == GOLDEN_AVAILABLE_ID


# ---------------------------------------------------------------- semantic inclusion（N-1）

@pytest.mark.parametrize("override", [
    dict(session_date="2026-09-18"),
    dict(reference_session="2026-09-15"),
    dict(origin=PredictionOrigin.REPLAY),
    dict(level=SignalLevel.DOWNWARD_LEAN),
    dict(level=SignalLevel.SLIGHT_UPWARD_LEAN, confidence=Confidence.LOW.value),
    dict(level=SignalLevel.NEUTRAL_RANGE, confidence=Confidence.LOW.value),
    dict(confidence=Confidence.MEDIUM.value),
])
def test_changing_any_semantic_input_changes_the_id(override: dict) -> None:
    assert make(**override).prediction_id != make().prediction_id


def test_available_versus_unavailable_changes_the_id() -> None:
    assert make().prediction_id != make_prediction_record(**abstained_kwargs()).prediction_id


def test_each_unavailable_reason_has_its_own_id() -> None:
    ids = set()
    for reason in UNAVAILABLE_REASONS:
        kwargs = mixed_kwargs if reason in REASONS_WITH_OUTLOOK_STATE else abstained_kwargs
        ids.add(make_prediction_record(**kwargs(unavailable_reason=reason)).prediction_id)
    assert len(ids) == len(UNAVAILABLE_REASONS) == 6


def test_every_level_yields_a_distinct_id() -> None:
    ids = {make(level=SignalLevel(level), confidence=confidence).prediction_id
           for level, confidence in APPROVED_LEVEL_CONFIDENCE_PAIRS}
    assert len(ids) == len(APPROVED_LEVEL_CONFIDENCE_PAIRS)


def test_live_and_replay_are_distinct_but_each_deterministic() -> None:
    live, replay = make(), make(origin=PredictionOrigin.REPLAY)
    assert live.prediction_id != replay.prediction_id
    assert replay.prediction_id == make(origin=PredictionOrigin.REPLAY).prediction_id


def test_horizon_and_schema_version_participate_in_identity_at_payload_level() -> None:
    """有効な値が 1 つずつしか無い field も hash に**入っている**ことを payload 水準で証明する。"""
    base = make().identity_payload()
    assert make_prediction_id({**base, "horizon": "other_horizon"}) != make_prediction_id(base)
    assert make_prediction_id({**base, "schema_version": "prediction_record:0.2.0"}) \
        != make_prediction_id(base)


def test_identity_payload_for_direction_mixed_keeps_confidence_and_horizon() -> None:
    payload = make_prediction_record(**mixed_kwargs()).identity_payload()
    assert payload["available"] is False and payload["level"] == ""
    assert payload["confidence"] == "MEDIUM" and payload["horizon"] == "next_tokyo_session"
    assert payload["unavailable_reason"] == "direction_mixed"


# ---------------------------------------------------------------- forbidden inputs（§5 E）

@pytest.mark.parametrize("name,value", sorted(FORBIDDEN_KWARGS.items()))
def test_factory_has_no_argument_for_display_delivery_or_outcome(name: str, value) -> None:
    with pytest.raises(TypeError):
        make_prediction_record(**base_kwargs(), **{name: value})


@pytest.mark.parametrize("name,value", sorted(FORBIDDEN_KWARGS.items()))
def test_dataclass_has_no_field_for_display_delivery_or_outcome(name: str, value) -> None:
    fields_of_valid_record = dataclasses.asdict(make())
    with pytest.raises(TypeError):
        PredictionRecord(**fields_of_valid_record, **{name: value})


def test_no_field_name_refers_to_outcome_evaluation_display_or_delivery() -> None:
    names = [f.name for f in dataclasses.fields(PredictionRecord)]
    for name in names:
        for fragment in FORBIDDEN_FIELD_FRAGMENTS:
            assert fragment not in name.lower(), (name, fragment)


def test_from_dict_rejects_unknown_fields() -> None:
    data = make().as_dict()
    for name, value in FORBIDDEN_KWARGS.items():
        with pytest.raises(InvalidPredictionRecord):
            PredictionRecord.from_dict({**data, name: value})


def test_as_dict_carries_no_display_or_outcome_keys() -> None:
    keys = set(make().as_dict())
    assert keys == {f.name for f in dataclasses.fields(PredictionRecord)}
    assert keys.isdisjoint(FORBIDDEN_KWARGS)


def test_schema_version_is_distinct_from_the_neutral_band_rule_version() -> None:
    assert PREDICTION_RECORD_SCHEMA_VERSION == "prediction_record:0.1.0"
    assert "topix_neutral_band" not in PREDICTION_RECORD_SCHEMA_VERSION
    assert "topix_neutral_band" not in executable_source()


# ---------------------------------------------------------------- immutability / forgery（§7）

def test_record_is_frozen() -> None:
    rec = make()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.level = SignalLevel.DOWNWARD_LEAN   # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.prediction_id = "pred_" + "0" * 24  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        del rec.brief_id                        # type: ignore[attr-defined]


def test_module_exposes_no_mutation_or_supersede_api() -> None:
    src = executable_source()
    for token in ("def update", "def replace", "def supersede", "def overwrite",
                  "dataclasses.replace", "object.__setattr__"):
        assert token not in src, token


@pytest.mark.parametrize("forged", ["pred_" + "0" * 24, "", GOLDEN_ABSTAINED_ID, "brief_x"])
def test_forged_prediction_id_is_rejected(forged: str) -> None:
    kwargs = base_kwargs()
    with pytest.raises(InvalidPredictionRecord):
        PredictionRecord(prediction_id=forged, **kwargs)


def test_unsupported_record_schema_version_is_rejected() -> None:
    data = make().as_dict()
    with pytest.raises(InvalidPredictionRecord):
        PredictionRecord.from_dict({**data, "schema_version": "prediction_record:0.2.0"})


@pytest.mark.parametrize("field,value", [
    ("morning_brief_schema_version", "0.1.0"),
    ("market_signal_schema_version", "0.2.0"),
    ("brief_id", ""), ("signal_id", ""),
])
def test_provenance_requirements_are_enforced(field: str, value: str) -> None:
    with pytest.raises(InvalidPredictionRecord):
        make(**{field: value})


@pytest.mark.parametrize("field", ["recorded_at", "cutoff"])
def test_naive_datetimes_are_rejected(field: str) -> None:
    with pytest.raises(ValueError):
        make(**{field: datetime(2026, 9, 17, 6, 30)})


def test_principle_refs_must_be_a_tuple_of_non_empty_strings() -> None:
    kwargs = base_kwargs()
    with pytest.raises(InvalidPredictionRecord):
        PredictionRecord(prediction_id=GOLDEN_AVAILABLE_ID, **kwargs,
                         principle_refs=["MP-01"])   # type: ignore[arg-type]
    with pytest.raises(InvalidPredictionRecord):
        make(principle_refs=("MP-01", ""))
    assert make(principle_refs=["MP-01"]).principle_refs == ("MP-01",)   # factory は tuple 化


# ---------------------------------------------------------------- round-trip（§8 前提）

@pytest.mark.parametrize("factory", [
    lambda: make(cutoff=CUTOFF, principle_refs=("MP-01", "MP-02"),
                 market_principle_version="market_rules:1.0.0", package_id="pkg_x",
                 draft_id="draft_y", outlook_rule_version="outlook:1.0.0"),
    lambda: make_prediction_record(**abstained_kwargs()),
    lambda: make_prediction_record(**mixed_kwargs(origin=PredictionOrigin.REPLAY)),
])
def test_as_dict_round_trips_through_json(factory) -> None:
    rec = factory()
    encoded = json.dumps(rec.as_dict(), ensure_ascii=False, sort_keys=True)
    back = PredictionRecord.from_dict(json.loads(encoded))
    assert back == rec
    assert back.prediction_id == rec.prediction_id
    assert json.dumps(back.as_dict(), ensure_ascii=False, sort_keys=True) == encoded


def test_as_dict_is_json_native_and_deterministic() -> None:
    a, b = make(cutoff=CUTOFF).as_dict(), make(cutoff=CUTOFF).as_dict()
    assert a == b
    assert a["origin"] == "LIVE" and a["level"] == "UPWARD_LEAN"
    assert a["recorded_at"] == "2026-09-17T06:30:00+00:00"
    assert a["cutoff"] == "2026-09-17T06:00:00+00:00"
    assert a["principle_refs"] == []
    abstained = make_prediction_record(**abstained_kwargs()).as_dict()
    assert abstained["level"] == "" and abstained["cutoff"] is None


def test_from_dict_recomputes_and_verifies_identity() -> None:
    data = make().as_dict()
    tampered = {**data, "level": "DOWNWARD_LEAN"}       # 意味論を変えたのに ID はそのまま
    with pytest.raises(InvalidPredictionRecord):
        PredictionRecord.from_dict(tampered)


# ---------------------------------------------------------------- vocabulary alignment（P4 frozen）

def test_vocabulary_is_imported_from_the_frozen_p4_sources() -> None:
    assert SIGNAL_LEVELS == tuple(level.value for level in SignalLevel) and len(SIGNAL_LEVELS) == 5
    assert CONFIDENCES == ("HIGH", "MEDIUM", "LOW")
    assert UNAVAILABLE_REASONS == tuple(APPROVED_UNAVAILABLE_REASONS)
    assert UNAVAILABLE_REASONS == tuple(delivery.PUBLIC_UNAVAILABLE_REASONS)
    assert len(UNAVAILABLE_REASONS) == 6


def test_approved_pairs_are_exactly_the_p4_level_by_state_range() -> None:
    expected = tuple(sorted({(level.value, confidence)
                             for (_d, confidence), level in LEVEL_BY_STATE.items()}))
    assert APPROVED_LEVEL_CONFIDENCE_PAIRS == expected
    assert len(APPROVED_LEVEL_CONFIDENCE_PAIRS) == 7
    assert ("NEUTRAL_RANGE", "LOW") in APPROVED_LEVEL_CONFIDENCE_PAIRS
    assert ("NEUTRAL_RANGE", "HIGH") not in APPROVED_LEVEL_CONFIDENCE_PAIRS


def test_outlook_rule_version_is_audit_only_and_accepts_the_p4_value() -> None:
    """権威 `compass.outlook.OUTLOOK_RULE_VERSION` は module 側で import しない（境界）。
    値は文字列としてそのまま運び、identity には入らない。"""
    from src.intelligence.compass.outlook import OUTLOOK_RULE_VERSION
    rec = make(outlook_rule_version=OUTLOOK_RULE_VERSION)
    assert rec.outlook_rule_version == "outlook:1.0.0"
    assert "outlook_rule_version" not in rec.identity_payload()
    assert rec.prediction_id == GOLDEN_AVAILABLE_ID
    assert make_prediction_record(**abstained_kwargs()).outlook_rule_version == ""
    with pytest.raises(InvalidPredictionRecord):
        PredictionRecord(**{**dataclasses.asdict(make()), "outlook_rule_version": None})


def test_known_horizons_match_the_p4_compass_default() -> None:
    assert KNOWN_HORIZONS == (CompassConfig().outlook_horizon,) == ("next_tokyo_session",)


def test_reasons_with_outlook_state_are_the_direction_reasons() -> None:
    assert REASONS_WITH_OUTLOOK_STATE == ("direction_mixed", "direction_uncertain")


def test_no_vocabulary_literal_is_hand_copied_into_the_module() -> None:
    src = executable_source()
    for literal in ("'UPWARD_LEAN'", "'draft_abstained'", "'tier3_unavailable'", "'HIGH'"):
        assert literal not in src, literal


# ---------------------------------------------------------------- dependency boundary（N-6 / §9）

def test_imports_are_limited_to_frozen_p4_vocabulary_and_core_helpers() -> None:
    allowed_local = {"..compass.model", "..core.ids", "..core.time",
                     "..reports.market_signal", "..reports.model"}
    allowed_stdlib = {"__future__", "json", "dataclasses", "datetime", "enum", "typing"}
    assert imported_modules() <= allowed_local | allowed_stdlib


def test_module_never_touches_network_persistence_or_market_data() -> None:
    src = executable_source()
    for token in ("urllib", "requests", "http", "socket", "sqlite3", "open(", "Path(",
                  "os.", "subprocess", "yaml", "jquants", "market.store", "market.backfill",
                  "tokyo_calendar", "investment_journal", "delivery", "render_markdown",
                  "pages", "publication", "environ", "getenv"):
        assert token not in src, token


def test_predictions_package_stays_excluded_from_the_production_closure() -> None:
    assert "predictions" in EXCLUDED_PACKAGES


def test_no_production_module_imports_the_prediction_record() -> None:
    offenders = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        if path.parent == MODULE_PATH.parent:
            continue
        text = path.read_text(encoding="utf-8")
        if "prediction_record" in text or "predictions import" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    for path in (REPO_ROOT / "scripts").rglob("*.py"):
        if "prediction" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_module_defines_no_persistence_ingestion_or_evaluation_entry_points() -> None:
    src = executable_source()
    for token in ("def append", "def save", "def load", "def ingest", "def evaluate",
                  "def from_signal", "def from_brief", "def from_market_signal",
                  "def main", "__main__", "argparse"):
        assert token not in src, token
