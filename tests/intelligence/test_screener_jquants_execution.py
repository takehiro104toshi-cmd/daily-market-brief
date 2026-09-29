"""P8-EXE — 安全な append executor の test matrix（happy ・held ・再検証 ・revision ・前検査 ・部分失敗 ・破損 ・architecture）。

書き込みは tmp_path の private root だけ。合成の行 ・合成の identity だけ。J-Quants ・network ・時計 ・乱数 ・LLM は使わない。
A1 ・A2 ・A2R ・A3 ・ST1 ・ADP0 の module は変えない。
"""
from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence import jquants_execution_model as xm
from src.intelligence.screener_intelligence import observation_store as ost
from src.intelligence.screener_intelligence.held_observation_store import HeldObservationStore
from src.intelligence.screener_intelligence.jquants_adapter_model import AdapterContext, AdapterResult
from src.intelligence.screener_intelligence.jquants_execution_model import (AuthorityWrites, ExecutionModelError,
                                                                            ExecutionOutcome, ExecutionReason,
                                                                            ExecutionResult, FieldDisposition,
                                                                            WriteState)
from src.intelligence.screener_intelligence.jquants_financial_summary_adapter import adapt_financial_summary_row
from src.intelligence.screener_intelligence.jquants_financial_summary_executor import execute_financial_summary_row
from src.intelligence.screener_intelligence.observation_model import TOKYO, FundamentalField, ValueState
from src.intelligence.screener_intelligence.observation_semantics_mapping import derive_observation_semantics
from src.intelligence.screener_intelligence.observation_semantics_model import FieldFamily
from src.intelligence.screener_intelligence.semantic_metadata_store import SemanticMetadataStore
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_jquants_adapter import quarterly, row
from tests.intelligence.test_screener_observation import Identity, at

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
IDS = Identity()
I1 = IDS.I1.issuer_id
CTX = AdapterContext(issuer_id=I1)
IFRS = "FYFinancialStatements_Consolidated_IFRS"
O = ExecutionOutcome
R = ExecutionReason
D = FieldDisposition


@pytest.fixture
def root(tmp_path: Path) -> Path:
    private = tmp_path / "private_root"
    identity = ist.IdentityStore.initialize(private)
    for record in IDS.records:
        identity.append(record)
    ost.ObservationStore.initialize(private)
    SemanticMetadataStore.initialize(private)
    HeldObservationStore.initialize(private)
    return private


def run(root: Path, mapping: dict, context: AdapterContext = CTX, prior=None) -> ExecutionResult:
    return execute_financial_summary_row(mapping, context, root, prior_adapter_result=prior)


def dispositions(result: ExecutionResult) -> list:
    return [f.disposition.value for f in result.fields]


def lines(root: Path, name: str) -> list:
    text = (root / "screener_intelligence" / name).read_text(encoding="utf-8")
    return text.splitlines()


def counts(root: Path) -> tuple:
    return (len(lines(root, "observation_records.jsonl")), len(lines(root, "semantic_metadata.jsonl")),
            len(lines(root, "held_observations.jsonl")))


# ================================================================ happy path


def test_happy_all_four_reported_fields_append_semantics_then_observation(root: Path) -> None:
    result = run(root, row())
    assert result.outcome is O.APPENDED and result.reasons == () and dispositions(result) == ["APPENDED"] * 4
    assert len(result.writes.observations_appended) == 4 and len(result.writes.semantic_metadata_appended) == 8
    assert result.writes.held_appended == "" and result.issuer_id == I1
    assert counts(root) == (4, 8, 0)
    store = ost.ObservationStore.open(root)
    semantic = SemanticMetadataStore.open(root)
    for field in result.fields:
        record = store.history.get(field.observation_id)
        assert record is not None and record.supersedes == "" and record.provenance.source_field == field.provider_field
        assert record.value.state is ValueState.VALUE_PRESENT and record.subject == I1
        assert semantic.semantics_for(field.observation_id).record_id == field.semantics_id
        assert semantic.provenance_for(field.observation_id).record_id == field.provenance_id
        assert field.provenance_write is WriteState.APPENDED and field.observation_write is WriteState.APPENDED
    assert [f.field for f in result.fields] == [FundamentalField.REVENUE, FundamentalField.OPERATING_INCOME,
                                                FundamentalField.NET_INCOME, FundamentalField.TOTAL_ASSETS]
    ordered = lines(root, "semantic_metadata.jsonl")
    assert '"SEMANTIC_MAPPING_PROVENANCE"' in ordered[0] and '"OBSERVATION_SEMANTICS"' in ordered[1]
    assert result.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
    assert result.rules_version == "p8_jquants_execution:0.1.0"


def test_happy_one_reported_field_and_not_reported_fields_never_become_zero(root: Path) -> None:
    result = run(root, row(OP="", NP="", TA=""))
    assert result.outcome is O.APPENDED and dispositions(result) == ["APPENDED", "NOT_REPORTED", "NOT_REPORTED",
                                                                     "NOT_REPORTED"]
    assert counts(root) == (1, 2, 0)
    for field in result.fields[1:]:
        assert field.observation_id == "" and field.observation_write is WriteState.NOT_REQUIRED
    text = (root / "screener_intelligence" / "observation_records.jsonl").read_text(encoding="utf-8")
    assert '"amount": "0"' not in text and "NOT_REPORTED" not in text


def test_happy_one_not_reported_field(root: Path) -> None:
    result = run(root, row(TA=""))
    assert result.outcome is O.APPENDED and dispositions(result) == ["APPENDED", "APPENDED", "APPENDED", "NOT_REPORTED"]
    assert counts(root) == (3, 6, 0)


def test_happy_all_not_reported_means_nothing_to_write(root: Path) -> None:
    result = run(root, row(Sales="", OP="", NP="", TA=""))
    assert result.outcome is O.NO_REPORTED_FIELDS and result.reasons == () and counts(root) == (0, 0, 0)


def test_happy_exact_replay_is_reused_without_new_authority_writes(root: Path) -> None:
    first = run(root, row())
    again = run(root, row())
    assert again.outcome is O.REUSED and dispositions(again) == ["REUSED"] * 4 and again.reasons == ()
    assert again.writes.observations_reused == first.writes.observations_appended
    assert set(again.writes.semantic_metadata_reused) == set(first.writes.semantic_metadata_appended)
    assert not again.writes.any_appended and counts(root) == (4, 8, 0)
    assert [f.observation_id for f in again.fields] == [f.observation_id for f in first.fields]


def test_happy_replay_after_store_reopen_and_from_a_reordered_mapping(root: Path) -> None:
    run(root, row())
    reopened = ost.ObservationStore.open(root)
    assert len(reopened.records()) == 4
    again = run(root, dict(reversed(list(row().items()))))
    assert again.outcome is O.REUSED and counts(root) == (4, 8, 0)
    assert run(root, quarterly("1Q")).outcome is O.APPENDED and counts(root) == (8, 16, 0)   # 別の slot は別の鎖


# ================================================================ held path


@pytest.mark.parametrize("overrides,expected", [
    ({"DocType": IFRS}, ["ACCOUNTING_STANDARD_UNSUPPORTED", "CURRENCY_UNKNOWN"]),
    ({"DocType": "FYFinancialStatements_Consolidated_KOREA"}, ["ACCOUNTING_STANDARD_UNKNOWN", "STATEMENT_BASIS_UNKNOWN",
                                                               "DOCTYPE_UNRECOGNIZED", "CURRENCY_UNKNOWN"]),
    ({"CurPerType": "4Q"}, ["PERIOD_UNSUPPORTED"]),
    ({"Sales": "1,000"}, ["VALUE_UNPARSEABLE"]),
    ({"DiscTime": "25:00:00"}, ["KNOWLEDGE_TIME_INVALID"])])
def test_held_adapter_holds_write_only_to_the_held_store(root: Path, overrides: dict, expected: list) -> None:
    result = run(root, row(**overrides))
    assert result.outcome is O.HELD and result.reasons == (R.ADAPTER_HELD,)
    assert [r.value for r in result.held_reasons] == expected
    assert result.writes.held_appended == result.held_record_id != "" and counts(root) == (0, 0, 1)
    assert result.fields == () and result.writes.observations_appended == ()
    held = HeldObservationStore.open(root).get(result.held_record_id)
    assert held is not None and held.issuer_id == I1 and held.rules_version == "p8_jquants_fins_summary_adapter:0.1.0"


def test_held_unresolved_identity_form_and_unknown_issuer(root: Path) -> None:
    malformed = run(root, row(), AdapterContext())
    assert malformed.outcome is O.HELD and malformed.reasons == (R.ADAPTER_HELD,)
    assert [r.value for r in malformed.held_reasons] == ["IDENTITY_UNRESOLVED"]
    unknown = AdapterContext(issuer_id="p8iss_" + "0" * 24)
    result = run(root, row(), unknown)
    assert result.outcome is O.HELD and result.reasons == (R.IDENTITY_UNRESOLVED,)
    assert [r.value for r in result.held_reasons] == ["IDENTITY_UNRESOLVED"] and counts(root) == (0, 0, 2)
    held = HeldObservationStore.open(root).get(result.held_record_id)
    assert held.issuer_id == unknown.issuer_id and held.rules_version == "p8_jquants_execution:0.1.0"
    assert held.attempted_statement_basis.value == "CONSOLIDATED"
    identity_lines = lines(root, "identity_records.jsonl") if (root / "screener_intelligence"
                                                              / "identity_records.jsonl").exists() else None
    assert identity_lines is None or all("00010" not in line for line in identity_lines)   # identity は登録しない


def test_held_exact_replay_reuses_the_held_record(root: Path) -> None:
    first = run(root, row(DocType=IFRS))
    again = run(root, row(DocType=IFRS))
    assert again.outcome is O.HELD and again.writes.held_reused == first.held_record_id
    assert again.writes.held_appended == "" and counts(root) == (0, 0, 1)
    unknown = AdapterContext(issuer_id="p8iss_" + "0" * 24)
    run(root, row(), unknown)
    assert run(root, row(), unknown).writes.held_reused != "" and counts(root) == (0, 0, 2)


def test_held_acquired_at_is_carried_to_the_held_record_only(root: Path) -> None:
    timed = AdapterContext(issuer_id=I1, acquired_at=at(2026, 6, 30, 12))
    held = run(root, row(DocType=IFRS), timed)
    assert HeldObservationStore.open(root).get(held.held_record_id).observed_at == at(2026, 6, 30, 12)
    appended = run(root, row(), timed)
    record = ost.ObservationStore.open(root).history.get(appended.fields[0].observation_id)
    assert record.knowledge.at == datetime(2025, 5, 12, 15, 0, tzinfo=TOKYO)                # 取得の時刻ではない


# ================================================================ revalidation / trust boundary


def test_revalidation_without_prior_result_and_with_a_matching_prior_result(root: Path) -> None:
    prior = adapt_financial_summary_row(row(), CTX)
    result = run(root, row(), prior=prior)
    assert result.outcome is O.APPENDED and counts(root) == (4, 8, 0)
    assert run(root, row(), prior=prior).outcome is O.REUSED


def test_revalidation_forged_and_stale_prior_results_are_rejected_without_writes(root: Path) -> None:
    forged = adapt_financial_summary_row(row(Sales="999"), CTX)                # 内容の違う prior（偽造）
    result = run(root, row(), prior=forged)
    assert result.outcome is O.REJECTED and result.reasons == (R.PRIOR_RESULT_MISMATCH,) and counts(root) == (0, 0, 0)
    assert result.provider_record == adapt_financial_summary_row(row(), CTX).provider_record
    stale = adapt_financial_summary_row(row(), AdapterContext(issuer_id=IDS.I2.issuer_id))   # 別の文脈の prior（古い）
    assert run(root, row(), prior=stale).reasons == (R.PRIOR_RESULT_MISMATCH,) and counts(root) == (0, 0, 0)
    held_prior = adapt_financial_summary_row(row(DocType=IFRS), CTX)
    assert run(root, row(), prior=held_prior).outcome is O.REJECTED and counts(root) == (0, 0, 0)
    assert run(root, row(), prior={"status": "ELIGIBLE"}).reasons == (R.INVALID_INPUT,)


def test_revalidation_the_caller_cannot_inject_observations_semantics_or_supersedes(root: Path) -> None:
    signature = inspect.signature(execute_financial_summary_row)
    assert list(signature.parameters) == ["row", "context", "data_root", "prior_adapter_result"]
    with pytest.raises(TypeError):
        execute_financial_summary_row(row(), CTX, root, supersedes="p8obs_" + "0" * 24)      # type: ignore[call-arg]
    with pytest.raises(TypeError):
        execute_financial_summary_row(row(), CTX, root, observations=())                      # type: ignore[call-arg]
    with pytest.raises(TypeError):
        execute_financial_summary_row(row(), CTX, root, semantics=())                         # type: ignore[call-arg]
    assert run(root, {**row(), "supersedes": "p8obs_" + "0" * 24}).reasons == (R.INVALID_INPUT,)
    assert run(root, row(), context={"issuer_id": I1}).reasons == (R.INVALID_INPUT,)         # type: ignore[arg-type]
    assert run(root, "not a row").reasons == (R.INVALID_INPUT,)
    assert counts(root) == (0, 0, 0)


# ================================================================ revision / supersedes


def test_revision_a_corrected_row_becomes_a_new_immutable_revision_with_correct_supersedes(root: Path) -> None:
    original = run(root, row())
    before = lines(root, "observation_records.jsonl")
    corrected = run(root, row(DiscNo="20250512000002", DiscDate="2025-05-20", Sales="500000000001"))
    assert corrected.outcome is O.APPENDED and dispositions(corrected) == ["APPENDED"] * 4
    store = ost.ObservationStore.open(root)
    for old, new in zip(original.fields, corrected.fields):
        assert new.supersedes == old.observation_id and new.observation_id != old.observation_id
        record = store.history.get(new.observation_id)
        assert record.supersedes == old.observation_id and store.history.get(old.observation_id) is not None
        chain = store.history.chains[record.slot_key]
        assert [r.record_id for r in chain] == [old.observation_id, new.observation_id]
    assert lines(root, "observation_records.jsonl")[:4] == before                      # 先の record は不変
    assert counts(root) == (8, 16, 0)
    assert store.history.get(corrected.fields[0].observation_id).value.amount == "500000000001"


def test_revision_replaying_the_corrected_row_converges_and_the_original_row_stays_reused(root: Path) -> None:
    run(root, row())
    corrected = row(DiscNo="20250512000002", DiscDate="2025-05-20", Sales="500000000001")
    run(root, corrected)
    again = run(root, corrected)
    assert again.outcome is O.REUSED and counts(root) == (8, 16, 0)
    original_again = run(root, row())                                                   # 古い revision の replay も再利用
    assert original_again.outcome is O.REUSED and counts(root) == (8, 16, 0)


def test_revision_known_before_predecessor_is_an_observation_conflict_with_zero_writes(root: Path) -> None:
    run(root, row(DiscDate="2025-05-20"))
    result = run(root, row(DiscDate="2025-05-12", DiscNo="20250512000009", Sales="1"))
    assert result.outcome is O.REJECTED and result.reasons == (R.OBSERVATION_CONFLICT,)
    assert result.failure_code == "NON_MONOTONIC_KNOWLEDGE" and counts(root) == (4, 8, 0)


def test_revision_accounting_standard_discontinuity_never_joins_the_chain(root: Path) -> None:
    run(root, row())
    non_consolidated = run(root, row(DocType="FYFinancialStatements_NonConsolidated_JP"))   # 別の slot（区分）
    assert non_consolidated.outcome is O.APPENDED and counts(root) == (8, 16, 0)
    ifrs = run(root, row(DiscNo="20250512000003", DocType=IFRS))                             # pilot の方針で保留
    assert ifrs.outcome is O.HELD and counts(root) == (8, 16, 1)
    assert "ACCOUNTING_STANDARD_UNSUPPORTED" in [r.value for r in ifrs.held_reasons]
    store = ost.ObservationStore.open(root)
    for chain in store.history.chains.values():
        assert len(chain) == 1 and chain[0].supersedes == ""


def test_revision_chain_semantics_hold_is_a_regression_guard(root: Path, monkeypatch) -> None:
    """鎖の末尾の注記が JP_GAAP でない（別の経路で書かれた）なら、凍結の A2R の gate が HOLD → 保留に入り、鎖に入らない。"""
    run(root, row())
    semantic = SemanticMetadataStore.open(root)
    head_ids = [f.observation_id for f in run(root, row()).fields]
    original_semantics_for = SemanticMetadataStore.semantics_for

    def foreign_head(self, observation_id):
        if observation_id in head_ids:
            semantics, _ = derive_observation_semantics(observation_id, IFRS, FieldFamily.UNPREFIXED_ACTUAL)
            return semantics
        return original_semantics_for(self, observation_id)

    monkeypatch.setattr(SemanticMetadataStore, "semantics_for", foreign_head)
    result = run(root, row(DiscNo="20250512000002", Sales="1"))
    assert result.outcome is O.HELD and result.reasons == (R.SEMANTIC_CHAIN_HOLD,)
    assert [r.value for r in result.held_reasons] == ["SEMANTIC_CHAIN_CONFLICT"] and counts(root) == (4, 8, 1)
    assert semantic.counts() == SemanticMetadataStore.open(root).counts()


# ================================================================ preflight


def test_preflight_a_deterministic_failure_in_field_4_causes_zero_writes_for_fields_1_to_3(root: Path) -> None:
    run(root, row(Sales="", OP="", NP="", TA="1"), AdapterContext(issuer_id=I1))
    head = ost.ObservationStore.open(root).records()[0]
    conflicting = row(DiscNo="20250512000002", DiscDate="2025-05-01", TA="2")                # TA だけ知識が末尾より前
    result = run(root, conflicting)
    assert result.outcome is O.REJECTED and result.reasons == (R.OBSERVATION_CONFLICT,)
    assert result.fields == () and counts(root) == (1, 2, 0) and head.record_id in lines(root,
                                                                                         "observation_records.jsonl")[0]


def test_preflight_semantic_conflict_before_any_write_causes_zero_new_writes(root: Path) -> None:
    fresh = adapt_financial_summary_row(row(), CTX)
    semantic = SemanticMetadataStore.open(root)
    first_id = fresh.eligible.observations[0].record_id
    other_semantics, other_provenance = derive_observation_semantics(
        first_id, "FYFinancialStatements_NonConsolidated_JP", FieldFamily.UNPREFIXED_ACTUAL)
    semantic.append(other_provenance)
    semantic.append(other_semantics)
    result = run(root, row())
    assert result.outcome is O.REJECTED and result.reasons == (R.SEMANTIC_CONFLICT,) and counts(root) == (0, 2, 0)
    assert result.failure_code in ("SEMANTICS_CONFLICT", "PROVENANCE_CONFLICT")


def test_preflight_observation_conflict_before_any_write_causes_zero_semantic_writes(root: Path) -> None:
    fresh = adapt_financial_summary_row(row(), CTX)
    store = ost.ObservationStore.open(root)
    store.append(fresh.eligible.observations[3])                                            # 注記なしで TA の根が存在する
    result = run(root, row(DiscNo="20250512000002", Sales="1"))
    assert result.outcome is O.REJECTED and result.reasons == (R.PRECHECK_FAILED,)
    assert result.failure_code == "CHAIN_HEAD_SEMANTICS_MISSING" and counts(root) == (1, 0, 0)


def test_preflight_concurrent_modification_is_detected_before_any_write(root: Path, monkeypatch) -> None:
    original = ost.ObservationStore.verify_unchanged

    def modified(self):
        with self.path.open("ab") as handle:
            handle.write(b"")
        raise ost.ObservationConcurrentModification("CONCURRENT_MODIFICATION", "changed")

    monkeypatch.setattr(ost.ObservationStore, "verify_unchanged", modified)
    result = run(root, row())
    assert result.outcome is O.REJECTED and result.reasons == (R.PRECHECK_FAILED,)
    assert result.failure_code == "CONCURRENT_MODIFICATION" and counts(root) == (0, 0, 0)
    monkeypatch.setattr(ost.ObservationStore, "verify_unchanged", original)


# ================================================================ partial failure


def test_partial_failure_after_semantic_metadata_then_retry_converges_without_rollback(root: Path, monkeypatch) -> None:
    original_append = ost.ObservationStore.append

    def failing(self, record):
        raise OSError(28, "no space left")

    monkeypatch.setattr(ost.ObservationStore, "append", failing)
    result = run(root, row())
    assert result.outcome is O.PARTIAL_FAILURE and result.reasons == (R.STORE_WRITE_FAILED, R.PARTIAL_WRITE)
    assert dispositions(result) == ["FAILED", "NOT_ATTEMPTED", "NOT_ATTEMPTED", "NOT_ATTEMPTED"]
    first = result.fields[0]
    assert first.provenance_write is WriteState.APPENDED and first.semantics_write is WriteState.APPENDED
    assert first.observation_write is WriteState.FAILED and first.failure_code == "OS_ERROR"
    assert len(result.writes.semantic_metadata_appended) == 2 and result.writes.observations_appended == ()
    assert counts(root) == (0, 2, 0)                                                        # 注記は残る（孤児）。削除しない
    orphan = SemanticMetadataStore.open(root)
    assert orphan.semantics_for(first.observation_id) is not None and "space" not in json.dumps(result.as_dict())
    monkeypatch.setattr(ost.ObservationStore, "append", original_append)
    retry = run(root, row())
    assert retry.outcome is O.APPENDED and dispositions(retry) == ["APPENDED"] * 4
    assert retry.fields[0].semantics_write is WriteState.REUSED
    assert retry.fields[0].observation_write is WriteState.APPENDED
    assert retry.writes.semantic_metadata_reused == result.writes.semantic_metadata_appended
    assert counts(root) == (4, 8, 0)
    assert run(root, row()).outcome is O.REUSED


def test_partial_failure_in_a_later_field_keeps_earlier_fields_appended(root: Path, monkeypatch) -> None:
    original_append = ost.ObservationStore.append
    calls = {"n": 0}

    def failing_third(self, record):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(5, "io")
        return original_append(self, record)

    monkeypatch.setattr(ost.ObservationStore, "append", failing_third)
    result = run(root, row())
    assert result.outcome is O.PARTIAL_FAILURE
    assert dispositions(result) == ["APPENDED", "APPENDED", "FAILED", "NOT_ATTEMPTED"]
    assert len(result.writes.observations_appended) == 2 and len(result.writes.semantic_metadata_appended) == 6
    assert counts(root) == (2, 6, 0)
    monkeypatch.setattr(ost.ObservationStore, "append", original_append)
    retry = run(root, row())
    assert retry.outcome is O.APPENDED and dispositions(retry) == ["REUSED", "REUSED", "APPENDED", "APPENDED"]
    assert counts(root) == (4, 8, 0)


def test_write_failure_before_any_authority_write_is_rejected_not_partial(root: Path, monkeypatch) -> None:
    def failing(self, record):
        raise OSError(30, "read-only")

    monkeypatch.setattr(SemanticMetadataStore, "append", failing)
    result = run(root, row())
    assert result.outcome is O.REJECTED and result.reasons == (R.STORE_WRITE_FAILED,) and counts(root) == (0, 0, 0)
    assert dispositions(result) == ["FAILED", "NOT_ATTEMPTED", "NOT_ATTEMPTED", "NOT_ATTEMPTED"]
    monkeypatch.setattr(HeldObservationStore, "append", failing)
    held = run(root, row(DocType=IFRS))
    assert held.outcome is O.REJECTED and held.reasons == (R.STORE_WRITE_FAILED,) and counts(root) == (0, 0, 0)


# ================================================================ corruption / missing stores


@pytest.mark.parametrize("name", ["semantic_metadata.jsonl", "held_observations.jsonl", "observation_records.jsonl"])
def test_corrupt_store_fails_closed_with_zero_writes(root: Path, name: str) -> None:
    run(root, row(OP=""))
    path = root / "screener_intelligence" / name
    with path.open("ab") as handle:
        handle.write(b'{"record_kind": "GARBAGE"}\n')
    before = path.read_bytes()
    result = run(root, row())
    assert result.outcome is O.REJECTED and result.reasons == (R.CORRUPT_STORE,)
    assert path.read_bytes() == before and result.failure_code != ""
    held = run(root, row(DocType=IFRS))
    assert held.outcome is O.REJECTED and held.reasons == (R.CORRUPT_STORE,)


@pytest.mark.parametrize("name", ["semantic_metadata.jsonl", "held_observations.jsonl", "observation_records.jsonl",
                                  "identity_records.jsonl"])
def test_missing_store_is_rejected_and_never_created(root: Path, name: str) -> None:
    path = root / "screener_intelligence" / name
    if not path.exists():
        pytest.skip("store file name not used by this layout")
    path.unlink()
    result = run(root, row())
    assert result.outcome is O.REJECTED and result.reasons == (R.STORE_MISSING,) and not path.exists()


def test_data_root_is_explicit_and_never_defaulted(root: Path) -> None:
    for bad in (None, "", "   "):
        result = execute_financial_summary_row(row(), CTX, bad)
        assert result.outcome is O.REJECTED and result.reasons == (R.INVALID_INPUT,)
        assert result.failure_code == "DATA_ROOT_REQUIRED"
    assert not (REPO_ROOT / "data" / "screener_intelligence").exists()
    source = (PACKAGE_DIR / "jquants_financial_summary_executor.py").read_text(encoding="utf-8")
    assert "data/" not in source and "config" not in source.lower().replace("configuration", "")


# ================================================================ result model


def test_result_model_is_closed_typed_and_consistent() -> None:
    assert {m.value for m in ExecutionOutcome} == {"APPENDED", "REUSED", "HELD", "REJECTED", "PARTIAL_FAILURE",
                                                   "NO_REPORTED_FIELDS"}
    assert {"ADAPTER_HELD", "IDENTITY_UNRESOLVED", "PRIOR_RESULT_MISMATCH", "SEMANTIC_CONFLICT", "OBSERVATION_CONFLICT",
            "PRECHECK_FAILED", "STORE_WRITE_FAILED", "PARTIAL_WRITE", "CORRUPT_STORE", "INVALID_INPUT"} <= {
                m.value for m in ExecutionReason}
    assert not {"score", "severity", "rank"} & {f.lower() for f in ExecutionResult.__dataclass_fields__}
    assert not {"raw", "payload", "row", "response_body", "record_id"} & set(ExecutionResult.__dataclass_fields__)
    with pytest.raises(ExecutionModelError):
        ExecutionResult(outcome=ExecutionOutcome.APPENDED, reasons=(), provider_record=None)     # 書かずに APPENDED は不可
    with pytest.raises(ExecutionModelError):
        ExecutionResult(outcome=ExecutionOutcome.REJECTED, reasons=(), provider_record=None)
    with pytest.raises(ExecutionModelError):
        ExecutionResult(outcome=ExecutionOutcome.REJECTED, reasons=(R.INVALID_INPUT,), provider_record=None,
                        failure_code="value 1,000")                                              # code だけ
    with pytest.raises(ExecutionModelError):
        AuthorityWrites(held_appended="a", held_reused="b")
    assert xm.ordered_execution_reasons((R.PARTIAL_WRITE, R.STORE_WRITE_FAILED, R.PARTIAL_WRITE)) == (
        R.STORE_WRITE_FAILED, R.PARTIAL_WRITE)


def test_result_carries_no_provider_values(root: Path) -> None:
    result = run(root, row(Sales="123456789"))
    text = json.dumps(result.as_dict())
    assert "123456789" not in text and "500000000000" not in text and '"Sales":' not in text
    held = run(root, row(Sales="1,234"))
    assert "1,234" not in json.dumps(held.as_dict())


# ================================================================ architecture


@pytest.mark.parametrize("name", ["jquants_execution_model", "jquants_financial_summary_executor"])
def test_architecture_no_network_clock_random_uuid_llm_metrics_identity_registration_or_public_output(name) -> None:
    path = PACKAGE_DIR / f"{name}.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in {"time", "uuid", "random", "secrets", "os", "sys", "socket", "pathlib", "json",
                                       "sqlite3", "decimal"}, (name, node.module)
            assert not any(token in node.module for token in (
                "identity_store", "identity_resolver", "identity_correction", "identity_remediation", "metric",
                "fundamental_metrics", "observation_resolver", "market", "jquants_v2", "ingestion", "themes",
                "narrative", "pages", "reports", "urllib", "requests", "production")), (name, node.module)
        if isinstance(node, ast.Import):
            assert not node.names, (name, [a.name for a in node.names])
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "Path", "os", "print", "float", "eval", "exec", "getattr"}, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today", "write", "unlink", "urlopen", "uuid4", "random",
                                     "initialize", "rename", "replace", "truncate"}, (name, node.attr)
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
    lowered = executable_source(path).lower()
    for token in ("screen", "rank", "score", "recommend", "theme", "llm", "prompt", "anthropic", "sqlite", "production",
                  "x-api-key", "://", "derive_issuer_id", "issuerregistration", "rollback", "delete"):
        assert token not in lowered, (name, token)
    assert "IdentityStore" not in source and ".initialize(" not in source


def test_architecture_only_the_three_sanctioned_stores_are_written(root: Path) -> None:
    before = {p.name for p in (root / "screener_intelligence").iterdir()}
    run(root, row())
    run(root, row(DocType=IFRS))
    after = {p.name for p in (root / "screener_intelligence").iterdir()}
    assert after == before == {"identity_records.jsonl", "observation_records.jsonl", "semantic_metadata.jsonl",
                               "held_observations.jsonl"}
    assert len(lines(root, "identity_records.jsonl")) == len(IDS.records)
    assert not list(root.glob("**/*.log")) and not list(root.glob("**/*execution*"))
