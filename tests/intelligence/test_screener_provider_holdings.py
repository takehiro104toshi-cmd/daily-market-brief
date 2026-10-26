"""P8-A2C-R — `ProviderHoldingsCoverage`（provider の保持 epoch の authority）の model ・store の test。

遡及の解決の意味（epoch の選択 ・不在の汚染 ・VALUE_ABSENT ／ NOT_FOUND）は `test_screener_observation_retrospective.py` の D 以降。
境界 ／ 凍結の guard は `test_screener_intelligence_boundary.py`。
すべて合成。network ・時計 ・実データ ・LLM ・raw の応答は使わない。F1 の生成は無い（record は test が合成で作る）。
"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import provider_holdings_model as pm
from src.intelligence.screener_intelligence import provider_holdings_store as ps
from src.intelligence.screener_intelligence.observation_model import CoverageDataset, ObservationCoverage
from src.intelligence.screener_intelligence.observation_store import ObservationAppendRejected, ObservationStore
from src.intelligence.screener_intelligence.provider_holdings_model import (HoldingsModelError,
                                                                           ProviderHoldingsCoverage,
                                                                           holdings_reference,
                                                                           is_holdings_reference)
from src.intelligence.screener_intelligence.provider_holdings_store import (AppendStatus, HoldingsAppendRejected,
                                                                           HoldingsConcurrentModification,
                                                                           HoldingsStoreCorrupt,
                                                                           HoldingsStoreMissing,
                                                                           ProviderHoldingsStore)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_acquisition_manifest import I1, I2
from tests.intelligence.test_screener_acquisition_manifest import root as manifest_root  # noqa: F401  fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
JST = timezone(timedelta(hours=9))
ACQ = datetime(2026, 10, 5, 18, 0, tzinfo=JST)
P = date(2025, 3, 31)
FUND = CoverageDataset.FUNDAMENTAL_DISCLOSURE
ACQ_REF = "jq.acq:" + "1" * 24
MAN_REF = "jq.man:" + "2" * 24


@pytest.fixture
def root(manifest_root: Path) -> Path:
    ProviderHoldingsStore.initialize(manifest_root)
    return manifest_root


def record(**overrides) -> ProviderHoldingsCoverage:
    base = dict(dataset=FUND, subject_id=I1, period_end=P, holdings_as_of=ACQ, acquisition_ref=ACQ_REF,
                manifest_ref=MAN_REF, canonical_entry_count=1)
    return ProviderHoldingsCoverage(**{**base, **overrides})


# ================================================================ A model


def test_a_the_record_is_immutable_aware_and_round_trips_canonically() -> None:
    rec = record()
    data = rec.as_dict()
    assert set(data) == {"acquisition_ref", "canonical_entry_count", "coverage_rule", "dataset", "holdings_as_of",
                         "manifest_ref", "period_end", "record_id", "record_kind", "rules_version", "schema_version",
                         "subject_id"}                                                        # privacy: key の集合を固定
    assert data["holdings_as_of"] == "2026-10-05T09:00:00+00:00" and data["period_end"] == "2025-03-31"
    assert data["coverage_rule"] == "EXACT_PERIOD_END" and data["record_kind"] == "PROVIDER_HOLDINGS_COVERAGE"
    assert "complete_through" not in rec.canonical_line() and "knowledge" not in rec.canonical_line()
    assert ProviderHoldingsCoverage.from_dict(json.loads(rec.canonical_line())) == rec
    assert rec.record_id.startswith("p8pvh_") and len(rec.record_id) == 30
    assert rec.reference == "jq.pvh:" + rec.record_id[6:] and is_holdings_reference(rec.reference)
    assert holdings_reference(rec.record_id) == rec.reference and not is_holdings_reference(MAN_REF)
    assert rec.covers(P) and not rec.covers(P + timedelta(days=1)) and not rec.covers(P - timedelta(days=1))
    with pytest.raises(FrozenInstanceError):
        rec.period_end = P                                                                     # type: ignore[misc]
    assert pm.HOLDINGS_SCHEMA_VERSION == "p8_provider_holdings_coverage:0.1.0"
    assert pm.PROVIDER_HOLDINGS_RECORD == "PROVIDER_HOLDINGS_EPOCH_RECORD"


@pytest.mark.parametrize("overrides,code", [
    ({"dataset": CoverageDataset.MARKET_DAILY}, "DATASET_NOT_ALLOWED"), ({"dataset": "FUNDAMENTAL_DISCLOSURE"},
                                                                         "INVALID_VOCABULARY"),
    ({"subject_id": "合成一号"}, "INVALID_SUBJECT"), ({"subject_id": ""}, "INVALID_SUBJECT"),
    ({"period_end": datetime(2025, 3, 31, tzinfo=JST)}, "INVALID_DATE"), ({"period_end": "2025-03-31"}, "INVALID_DATE"),
    ({"holdings_as_of": datetime(2026, 10, 5, 18, 0)}, "NAIVE_DATETIME"), ({"holdings_as_of": P}, "NAIVE_DATETIME"),
    ({"acquisition_ref": MAN_REF}, "INVALID_ACQUISITION_REF"), ({"manifest_ref": ACQ_REF}, "INVALID_MANIFEST_REF"),
    ({"acquisition_ref": "jq.acq:token=" + "1" * 18}, "INVALID_ACQUISITION_REF"),
    ({"canonical_entry_count": 0}, "INVALID_COUNT"), ({"canonical_entry_count": True}, "INVALID_COUNT"),
    ({"canonical_entry_count": "1"}, "INVALID_COUNT"), ({"rules_version": "Rules:1.0.0"}, "INVALID_RULE_VERSION"),
    ({"rules_version": "api_key:1.0.0"}, "CREDENTIAL_LIKE_TEXT")])
def test_a_invalid_records_fail_closed(overrides, code) -> None:
    with pytest.raises(HoldingsModelError) as exc:
        record(**overrides)
    assert exc.value.code == code


def test_a_record_ids_are_deterministic_and_every_semantic_field_participates() -> None:
    rec = record()
    assert record().record_id == rec.record_id
    for overrides in ({"subject_id": I2}, {"period_end": P - timedelta(days=1)},
                      {"holdings_as_of": ACQ + timedelta(seconds=1)}, {"acquisition_ref": "jq.acq:" + "3" * 24},
                      {"manifest_ref": "jq.man:" + "4" * 24}, {"canonical_entry_count": 2}):
        assert record(**overrides).record_id != rec.record_id, overrides
    utc_same_instant = record(holdings_as_of=ACQ.astimezone(timezone.utc))
    assert utc_same_instant.record_id == rec.record_id                                         # 同じ瞬間 → 同じ id


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(complete_through="2026-10-05T09:00:00+00:00"), "UNKNOWN_FIELD"),
    (lambda d: d.pop("manifest_ref"), "MISSING_FIELD"),
    (lambda d: d.update(record_id="p8pvh_" + "0" * 24), "RECORD_ID_MISMATCH"),
    (lambda d: d.update(schema_version="p8_provider_holdings_coverage:9.9.9"), "SCHEMA_MISMATCH"),
    (lambda d: d.update(record_kind="OBSERVATION_COVERAGE"), "KIND_MISMATCH"),
    (lambda d: d.update(coverage_rule="INTERVAL"), "COVERAGE_RULE_MISMATCH"),
    (lambda d: d.update(period_end="2025-3-31"), "INVALID_DATE"),
    (lambda d: d.update(holdings_as_of="2026-10-05 18:00"), "INVALID_DATE"),
    (lambda d: d.update(dataset="MARKET_DAILY"), "DATASET_NOT_ALLOWED")])
def test_a_from_dict_rejects_unknown_fields_world_boundaries_and_forged_ids(mutate, code) -> None:
    data = record().as_dict()
    mutate(data)
    with pytest.raises(HoldingsModelError) as exc:
        ProviderHoldingsCoverage.from_dict(data)
    assert exc.value.code == code


# ================================================================ B store


def test_b_append_reused_lookups_and_order_independence(root: Path) -> None:
    store = ProviderHoldingsStore.open(root)
    one = record()
    two = record(holdings_as_of=ACQ + timedelta(days=7), acquisition_ref="jq.acq:" + "5" * 24,
                 manifest_ref="jq.man:" + "6" * 24)
    other_period = record(period_end=P - timedelta(days=90))
    assert store.append(two).status is AppendStatus.APPENDED                                  # 後の epoch を先に書く
    assert store.append(one).status is AppendStatus.APPENDED
    assert store.append(other_period).status is AppendStatus.APPENDED
    assert store.append(one).status is AppendStatus.REUSED and len(store.records()) == 3
    # holdings_as_of の順（位置ではない）
    assert store.for_slot(I1, P) == (one, two)
    assert store.for_subject(I1) == (one, other_period, two) and store.for_subject(I2) == ()
    assert store.for_slot(I1, P - timedelta(days=90)) == (other_period,) and store.for_slot(I2, P) == ()
    assert store.get(two.record_id) == two and store.by_reference(one.reference) == one
    assert store.get("p8pvh_" + "0" * 24) is None and store.by_reference("jq.pvh:" + "0" * 24) is None
    reopened = ProviderHoldingsStore.open(root, read_only=True)
    assert reopened.records() == (two, one, other_period) and reopened.for_slot(I1, P) == (one, two)
    with pytest.raises(HoldingsAppendRejected) as exc:
        reopened.append(one)
    assert exc.value.code == "READ_ONLY"
    with pytest.raises(HoldingsAppendRejected) as exc:
        store.append(ObservationCoverage(dataset=FUND, data_from=P, data_to=P + timedelta(days=1), complete_through=ACQ,
                                         provenance=__import__(
                                             "src.intelligence.screener_intelligence.observation_model",
                                             fromlist=["ObservationProvenance"]).ObservationProvenance(
                                             source_class=__import__(
                                                 "src.intelligence.screener_intelligence.identity_model",
                                                 fromlist=["SourceClass"]).SourceClass.JQUANTS,
                                             source_record_ref=ACQ_REF)))
    assert exc.value.code == "INVALID_TYPE"                                                    # A2 の coverage は入らない


def test_b_conflicts_fail_closed(root: Path) -> None:
    store = ProviderHoldingsStore.open(root)
    one = record()
    store.append(one)
    different = record(canonical_entry_count=2)                                                # 同じ取得 ・同じ P ・違う内容
    assert different.record_id != one.record_id
    with pytest.raises(HoldingsAppendRejected) as exc:
        store.append(different)
    assert exc.value.code == "PROVIDER_HOLDINGS_CONFLICT"
    other_manifest = record(manifest_ref="jq.man:" + "9" * 24)
    with pytest.raises(HoldingsAppendRejected) as exc:
        store.append(other_manifest)
    assert exc.value.code == "PROVIDER_HOLDINGS_CONFLICT"
    assert store.append(record(period_end=P - timedelta(days=90))).status is AppendStatus.APPENDED   # 別の P は別の record
    assert store.append(record(acquisition_ref="jq.acq:" + "7" * 24, manifest_ref="jq.man:" + "8" * 24,
                               holdings_as_of=ACQ + timedelta(days=1))).status is AppendStatus.APPENDED
    captured = one.record_id
    monkey = replace(one, canonical_entry_count=3)
    store._lines[captured] = monkey.canonical_line()                                           # 同じ id ・違う内容（偽装）
    with pytest.raises(HoldingsAppendRejected) as exc:
        store.append(one)
    assert exc.value.code == "HOLDINGS_CONTENT_CONFLICT"


@pytest.mark.parametrize("tail,code", [
    (b'{"record_kind": "PROVIDER_HOLDINGS_COVERAGE"', "TRUNCATED_FINAL_LINE"), (b"\n", "BLANK_LINE"),
    (b"not json\n", "INVALID_RECORD"), (b'{"record_kind": "OTHER"}\n', "INVALID_RECORD"),
    (b"\xff\xfe\n", "INVALID_ENCODING")])
def test_b_malformed_journal_fails_closed_and_is_never_repaired(root: Path, tail: bytes, code: str) -> None:
    store = ProviderHoldingsStore.open(root)
    store.append(record())
    path = root / "screener_intelligence" / "provider_holdings_coverage.jsonl"
    with path.open("ab") as handle:
        handle.write(tail)
    before = path.read_bytes()
    with pytest.raises(HoldingsStoreCorrupt) as exc:
        ProviderHoldingsStore.open(root)
    assert exc.value.code == code and path.read_bytes() == before


def test_b_physical_duplicate_non_canonical_epoch_duplicate_and_external_change_fail_closed(root: Path) -> None:
    store = ProviderHoldingsStore.open(root)
    one = record()
    store.append(one)
    path = root / "screener_intelligence" / "provider_holdings_coverage.jsonl"
    original = path.read_bytes()
    for tail, code in ((one.canonical_line().encode(), "PHYSICAL_DUPLICATE"),
                       (json.dumps(one.as_dict(), separators=(", ", ": ")).encode() + b"\n", "NON_CANONICAL_LINE"),
                       (record(canonical_entry_count=2).canonical_line().encode(), "EPOCH_PERIOD_DUPLICATE")):
        with path.open("ab") as handle:
            handle.write(tail)
        with pytest.raises(HoldingsStoreCorrupt) as exc:
            ProviderHoldingsStore.open(root)
        assert exc.value.code == code
        path.write_bytes(original)
    with path.open("ab") as handle:                                                            # 外からの変更 → 書かない
        handle.write(record(period_end=P - timedelta(days=90)).canonical_line().encode())
    with pytest.raises(HoldingsConcurrentModification):
        store.append(record(period_end=P - timedelta(days=180)))
    with pytest.raises(HoldingsStoreMissing):
        ProviderHoldingsStore.open(root / "nowhere")
    with pytest.raises(HoldingsAppendRejected) as exc:
        ProviderHoldingsStore.open("")
    assert exc.value.code == "DATA_ROOT_REQUIRED"


def test_b_the_store_is_separate_from_a2_and_touches_only_its_own_journal(root: Path) -> None:
    before = {p.name for p in (root / "screener_intelligence").iterdir()}
    ProviderHoldingsStore.open(root).append(record())
    assert {p.name for p in (root / "screener_intelligence").iterdir()} == before
    assert "provider_holdings_coverage.jsonl" in before and ps.HOLDINGS_FILENAME == "provider_holdings_coverage.jsonl"
    assert ps.HOLDINGS_DIRNAME == "screener_intelligence" and ps.AUTHORITY_CLASS == pm.PROVIDER_HOLDINGS_RECORD
    with pytest.raises(ObservationAppendRejected) as exc:                                     # A2 の store には入らない
        ObservationStore.open(root).append(record())
    assert exc.value.code == "INVALID_TYPE"
    assert ObservationStore.open(root, read_only=True).history.coverages == []                 # STRICT の coverage は増えない
    text = (root / "screener_intelligence" / "provider_holdings_coverage.jsonl").read_text(encoding="utf-8")
    for forbidden in ("complete_through", "500000000000", "Sales", "合成", "Synth", "apikey", "api_key", "token",
                      "Bearer", "://", "Authorization", "DiscDate", "knowledge", "value", "amount"):
        assert forbidden not in text, forbidden
    source = executable_source(PACKAGE_DIR / "provider_holdings_store.py")
    for token in ("unlink", "rename", "truncate", '"wb"', "write_text", "write_bytes", "sqlite", "compact", "repair",
                  "now(", "today(", "utcnow", "://"):
        assert token not in source, token
    assert "fsync" in source and "'ab'" in source
    model = executable_source(PACKAGE_DIR / "provider_holdings_model.py")
    for token in ("complete_through", "KnowledgeTime", "now(", "today(", "open(", "Path(", "ObservationCoverage",
                  "ObservationHistory"):
        assert token not in model, token
