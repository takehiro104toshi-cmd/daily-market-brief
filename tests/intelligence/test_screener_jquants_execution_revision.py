"""P8-EXE-R — provider 側の変更（同じ自然 key ・違う digest）の知識を取得の時刻にする remediation の test。

tmp_path の private root の 3 store だけに書く。合成の行だけ。J-Quants ・network ・時計 ・乱数 ・LLM は使わない。
A1 ・A2 ・A2R ・ADP0 ・ACQ0 の module は変えない。`acquired_at` は test が明示に渡す。
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence import observation_store as ost
from src.intelligence.screener_intelligence.held_observation_store import HeldObservationStore
from src.intelligence.screener_intelligence.jquants_adapter_model import AdapterContext
from src.intelligence.screener_intelligence.jquants_execution_model import ExecutionOutcome, ExecutionReason
from src.intelligence.screener_intelligence.jquants_financial_summary_executor import execute_financial_summary_row
from src.intelligence.screener_intelligence.observation_model import TOKYO, KnowledgePrecision
from src.intelligence.screener_intelligence.observation_resolver import ObservationQuery, ObservationStatus, resolve
from src.intelligence.screener_intelligence.semantic_metadata_store import SemanticMetadataStore
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_jquants_adapter import quarterly, row
from tests.intelligence.test_screener_jquants_execution import counts, dispositions, lines
from tests.intelligence.test_screener_observation import Identity

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
IDS = Identity()
I1 = IDS.I1.issuer_id
DISCLOSED = datetime(2025, 5, 12, 15, 0, tzinfo=TOKYO)                                  # 行の DiscDate ・DiscTime（世界）
ACQUIRED = datetime(2026, 10, 5, 18, 0, tzinfo=TOKYO)                                   # 後の取得（system）
LATER = ACQUIRED + timedelta(days=31)
CTX = AdapterContext(issuer_id=I1)
CTX_ACQ = AdapterContext(issuer_id=I1, acquired_at=ACQUIRED)
CTX_LATER = AdapterContext(issuer_id=I1, acquired_at=LATER)
O = ExecutionOutcome
R = ExecutionReason
MODIFIED = {"Sales": "500000000009"}                                                     # 同じ自然 key ・内容だけ違う


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


def run(root: Path, mapping: dict, context: AdapterContext = CTX):
    return execute_financial_summary_row(mapping, context, root)


def chain_of(root: Path, result):
    history = ost.ObservationStore.open(root, read_only=True).history
    record = history.get(result.fields[0].observation_id)
    return history, history.chains[record.slot_key]


def status_at(root: Path, result, when: datetime):
    history, chain = chain_of(root, result)
    head = chain[0]
    query = ObservationQuery.actual(head.subject, head.field, head.statement_basis, head.period)
    return resolve(history, query, cutoff=when)


# ================================================================ A 初見 ・同じ digest（凍結の意味のまま）


def test_a_first_seen_record_keeps_tdnet_disclosure_knowledge_even_when_acquired_years_later(root: Path) -> None:
    result = run(root, row(), CTX_ACQ)
    assert result.outcome is O.APPENDED
    _, chain = chain_of(root, result)
    assert len(chain) == 1 and chain[0].knowledge.at == DISCLOSED                           # 取得の時刻ではない
    assert chain[0].knowledge.precision is KnowledgePrecision.TIMESTAMP and chain[0].supersedes == ""
    date_only = run(root, quarterly("1Q", DiscTime=""), CTX_ACQ)                           # 時刻なしの開示 → DATE
    _, q_chain = chain_of(root, date_only)
    assert q_chain[0].knowledge.precision is KnowledgePrecision.DATE


def test_a_exact_reacquisition_is_reused_regardless_of_acquired_at(root: Path) -> None:
    first = run(root, row())
    before = lines(root, "observation_records.jsonl")
    for context in (CTX, CTX_ACQ, CTX_LATER):
        again = run(root, row(), context)
        assert again.outcome is O.REUSED and dispositions(again) == ["REUSED"] * 4
        assert [f.observation_id for f in again.fields] == [f.observation_id for f in first.fields]
    assert lines(root, "observation_records.jsonl") == before and counts(root) == (4, 8, 0)
    _, chain = chain_of(root, first)
    assert len(chain) == 1 and chain[0].knowledge.at == DISCLOSED                           # 知識 ・id ・鎖は変わらない


# ================================================================ B 同じ自然 key ・違う digest（provider 側の変更）


def test_b_changed_digest_with_acquired_at_appends_a_revision_whose_knowledge_is_the_acquisition_instant(
        root: Path) -> None:
    original = run(root, row())
    before = lines(root, "observation_records.jsonl")
    modified = run(root, row(**MODIFIED), CTX_ACQ)
    assert modified.outcome is O.APPENDED and dispositions(modified) == ["APPENDED"] * 4
    history, chain = chain_of(root, modified)
    assert [r.record_id for r in chain] == [original.fields[0].observation_id, modified.fields[0].observation_id]
    assert chain[1].supersedes == chain[0].record_id and chain[1].knowledge.at == ACQUIRED  # 知識 ＝ 取得の時刻
    assert chain[0].knowledge.at == DISCLOSED and chain[0].value.amount == "500000000000"  # 元の record は不変
    assert chain[1].value.amount == "500000000009"
    assert chain[1].provenance.source_record_ref != chain[0].provenance.source_record_ref  # digest が違う参照
    natural = [r.provenance.source_record_ref.rpartition(":")[0] for r in chain]
    assert natural[0] == natural[1]                                                           # 自然 key は同じ
    assert lines(root, "observation_records.jsonl")[:4] == before and counts(root) == (8, 16, 0)
    for field_result in modified.fields[1:]:                                                # 4 欄すべて同じ扱い
        record = history.get(field_result.observation_id)
        assert record.knowledge.at == ACQUIRED and record.supersedes != ""


def test_b_changed_digest_without_acquired_at_fails_closed_and_writes_nothing(root: Path) -> None:
    run(root, row())
    before = (lines(root, "observation_records.jsonl"), lines(root, "semantic_metadata.jsonl"))
    result = run(root, row(**MODIFIED))                                                    # acquired_at 無し
    assert result.outcome is O.REJECTED and result.reasons == (R.PRECHECK_FAILED,)
    assert result.failure_code == "PROVIDER_REVISION_ACQUISITION_TIME_REQUIRED"
    assert (lines(root, "observation_records.jsonl"), lines(root, "semantic_metadata.jsonl")) == before
    assert counts(root) == (4, 8, 0)


def test_b_naive_acquired_at_is_rejected_before_anything_happens(root: Path) -> None:
    with pytest.raises(Exception) as exc:                                                 # 凍結 ADP0 の文脈の契約
        AdapterContext(issuer_id=I1, acquired_at=datetime(2026, 10, 5, 18, 0))
    assert getattr(exc.value, "code", "") == "INVALID_CONTEXT"


def test_b_changed_digest_revision_replays_as_reused_and_a_second_modification_chains_after_it(root: Path) -> None:
    run(root, row())
    first = run(root, row(**MODIFIED), CTX_ACQ)
    again = run(root, row(**MODIFIED), CTX_LATER)                                          # 同じ digest → 再利用
    assert again.outcome is O.REUSED and counts(root) == (8, 16, 0)
    assert [f.observation_id for f in again.fields] == [f.observation_id for f in first.fields]
    second = run(root, row(Sales="500000000010"), CTX_LATER)                               # 2 度目の変更
    assert second.outcome is O.APPENDED
    _, chain = chain_of(root, second)
    assert [r.knowledge.at for r in chain] == [DISCLOSED, ACQUIRED, LATER]
    assert chain[2].supersedes == chain[1].record_id and counts(root) == (12, 24, 0)
    earlier = run(root, row(Sales="500000000011"), CTX_ACQ)                                # 鎖の末尾より前の取得 → 拒む
    assert earlier.outcome is O.REJECTED and earlier.reasons == (R.OBSERVATION_CONFLICT,)
    assert earlier.failure_code == "NON_MONOTONIC_KNOWLEDGE" and counts(root) == (12, 24, 0)


def test_b_strict_pit_before_the_acquisition_keeps_the_original_and_after_sees_the_modification(root: Path) -> None:
    original = run(root, row())
    run(root, row(**MODIFIED), CTX_ACQ)
    before = status_at(root, original, DISCLOSED + timedelta(days=30))                    # 2025: 元の開示だけ
    assert before.status is ObservationStatus.FOUND or before.status.value.endswith("COVERAGE")
    history, chain = chain_of(root, original)
    from src.intelligence.screener_intelligence.observation_resolver import _chain_head   # 凍結の鎖の選択だけを見る
    head_before, unsure_before = _chain_head(chain, DISCLOSED + timedelta(days=30))
    head_after, unsure_after = _chain_head(chain, ACQUIRED + timedelta(seconds=1))
    assert (head_before, unsure_before) == (0, False) and chain[head_before].value.amount == "500000000000"
    assert (head_after, unsure_after) == (1, False) and chain[head_after].value.amount == "500000000009"
    head_between, _ = _chain_head(chain, ACQUIRED - timedelta(seconds=1))                 # 取得の直前も元のまま
    assert head_between == 0


# ================================================================ C 新しい DiscNo ・会計基準（従来どおり）


def test_c_new_discno_correction_keeps_its_own_tdnet_knowledge_and_is_not_a_provider_modification(root: Path) -> None:
    run(root, row())
    corrected = run(root, row(DiscNo="20250512000002", DiscDate="2025-05-20", Sales="500000000001"), CTX_ACQ)
    assert corrected.outcome is O.APPENDED
    _, chain = chain_of(root, corrected)
    assert chain[1].knowledge.at == datetime(2025, 5, 20, 15, 0, tzinfo=TOKYO)               # 訂正自身の開示日時
    assert chain[1].supersedes == chain[0].record_id and counts(root) == (8, 16, 0)
    without = run(root, row(DiscNo="20250512000003", DiscDate="2025-05-21", Sales="500000000002"))
    assert without.outcome is O.APPENDED                                                   # acquired_at 無しでも訂正は通る


def test_c_accounting_standard_discontinuity_and_adapter_holds_are_unchanged(root: Path) -> None:
    run(root, row())
    ifrs = run(root, row(DiscNo="20250512000003", DocType="FYFinancialStatements_Consolidated_IFRS"), CTX_ACQ)
    assert ifrs.outcome is O.HELD and [r.value for r in ifrs.held_reasons] == ["SEMANTIC_CHAIN_CONFLICT"]
    foreign = run(root, row(DiscNo="20250512000004", DocType="FYFinancialStatements_Consolidated_Foreign"), CTX_ACQ)
    assert foreign.outcome is O.HELD and "ACCOUNTING_STANDARD_UNKNOWN" in [r.value for r in foreign.held_reasons]
    assert counts(root) == (4, 8, 2)


def test_c_modification_of_a_date_only_disclosure_also_uses_the_acquisition_instant(root: Path) -> None:
    run(root, quarterly("1Q", DiscTime=""))
    modified = run(root, quarterly("1Q", DiscTime="", OP="40000000001"), CTX_ACQ)
    assert modified.outcome is O.APPENDED
    _, chain = chain_of(root, modified)
    assert chain[0].knowledge.precision is KnowledgePrecision.DATE and chain[1].knowledge.at == ACQUIRED


# ================================================================ D replay ・architecture


def test_d_replay_of_the_same_history_and_inputs_is_deterministic(root: Path, tmp_path: Path) -> None:
    first = [run(root, row()).as_dict(), run(root, row(**MODIFIED), CTX_ACQ).as_dict()]
    other = tmp_path / "second_root"
    identity = ist.IdentityStore.initialize(other)
    for record in IDS.records:
        identity.append(record)
    ost.ObservationStore.initialize(other)
    SemanticMetadataStore.initialize(other)
    HeldObservationStore.initialize(other)
    second = [run(other, row()).as_dict(), run(other, row(**MODIFIED), CTX_ACQ).as_dict()]
    assert first == second
    assert lines(root, "observation_records.jsonl") == lines(other, "observation_records.jsonl")


def test_d_architecture_no_clock_no_network_no_acq0_import_no_coverage() -> None:
    path = PACKAGE_DIR / "jquants_financial_summary_executor.py"
    source = executable_source(path)
    lowered = source.lower()
    for token in ("now(", "utcnow", "today(", "time.time", "urllib", "socket", "http", "://", "acquisition_event",
                  "observationcoverage", "coverage(", "complete_through", "holdings_as_of", "subject_id=",
                  "authority_as_of", "epoch"):
        assert token not in lowered, token
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "acquisition_event_model" not in imported and "acquisition_event_store" not in imported
    assert "KnowledgeTime" in source and "PROVIDER_REVISION_ACQUISITION_TIME_REQUIRED" in source
    adapter = executable_source(PACKAGE_DIR / "jquants_financial_summary_adapter.py")
    assert "acquired_at" not in adapter.replace("observed_at=context.acquired_at", "")      # ADP0 の知識は開示時刻のまま
