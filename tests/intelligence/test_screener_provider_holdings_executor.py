"""P8-OBS60-F1 — `ProviderHoldingsCoverage` の producer（取得 ＋ manifest ＋ A2 → 保持 store）の test。

model ・store の test は `test_screener_provider_holdings.py`、遡及の解決の意味は `test_screener_observation_retrospective.py`、
境界 ／ 凍結の guard は `test_screener_intelligence_boundary.py`。
すべて合成。network ・時計 ・実データ ・LLM ・raw の応答 ・credential は使わない。A2 の `ObservationCoverage` は決して作らない。
"""
from __future__ import annotations

import ast
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import provider_holdings_executor as fx
from src.intelligence.screener_intelligence.acquisition_event_model import AcquisitionStatus, RequestScope
from src.intelligence.screener_intelligence.acquisition_manifest_store import ManifestStore
from src.intelligence.screener_intelligence.jquants_live_model import MASTER_PATH
from src.intelligence.screener_intelligence.observation_model import ObservationHistory, StatementBasis
from src.intelligence.screener_intelligence.observation_resolver import resolve
from src.intelligence.screener_intelligence.observation_store import ObservationAppendRejected, ObservationStore
from src.intelligence.screener_intelligence.provider_holdings_executor import (HoldingsExecutionResult,
                                                                              HoldingsExecutionStatus,
                                                                              execute_provider_holdings)
from src.intelligence.screener_intelligence.provider_holdings_model import ProviderHoldingsCoverage
from src.intelligence.screener_intelligence.provider_holdings_store import ProviderHoldingsStore
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence.acquisition_event_store import AcquisitionEventStore
from src.intelligence.screener_intelligence.held_observation_store import HeldObservationStore
from src.intelligence.screener_intelligence.semantic_metadata_store import SemanticMetadataStore
from tests.intelligence.test_screener_acquisition_manifest import (ACQ1, ACQ2, CTX1, CTX2, I1, IDS, built, execute,
                                                                   fins_event)
from tests.intelligence.test_screener_acquisition_manifest import root as manifest_root  # noqa: F401  fixture
from tests.intelligence.test_screener_jquants_adapter import quarterly, row
from tests.intelligence.test_screener_jquants_execution import FOREIGN
from tests.intelligence.test_screener_observation_retrospective import (FAR, FUND, P_1Q, P_FY, F, S, history_of,
                                                                        holdings_of, legacy_cover, query, retro)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
X = HoldingsExecutionStatus
NC = StatementBasis.NON_CONSOLIDATED
NC_DOC = "FYFinancialStatements_NonConsolidated_JP"
BROKEN = row(Sales="1,000")                                                                   # UNSUPPORTED ・期間 FY 既知
UNKNOWN = row(CurPerType="4Q", DiscNo="20250512000002")                                      # UNSUPPORTED ・期間 None
HELD_FY = row(DocType=FOREIGN, DiscNo="20250512000003")                                      # HELD_SEMANTIC ・期間 FY 既知
EMPTY_FY = row(Sales="", OP="", NP="", TA="", DiscNo="20250512000004")                        # NOT_REPORTED_ONLY ・期間 FY
EMPTY_2Q = quarterly("2Q", Sales="", OP="", NP="", TA="", DiscNo="20250512000008")            # NOT_REPORTED_ONLY ・期間 2Q
NC_BROKEN = row(DocType=NC_DOC, DiscNo="20250512000002", Sales="1,000")                      # UNSUPPORTED ・期間 FY ・単体
NC_FIXED = row(DocType=NC_DOC, DiscNo="20250512000002", Sales="1000")                        # provider の修正
CORRECTED = row(DiscNo="20250512000005", DiscDate="2025-05-20", Sales="500000000001")       # 同じ期間の訂正（別 DiscNo）
JOURNAL = "screener_intelligence/provider_holdings_coverage.jsonl"


@pytest.fixture
def root(manifest_root: Path) -> Path:
    ProviderHoldingsStore.initialize(manifest_root)
    return manifest_root


def acquire(root: Path, rows, context=CTX1):
    """EXE → manifest（store に記録）→ COMPLETE な取得 event。保持 record はまだ無い（F1 が作る）。"""
    manifest = built(root, rows, context)
    ManifestStore.open(root).append(manifest)
    return fins_event(rows, acquired_at=context.acquired_at), manifest


def run(root: Path, event, *, manifests=None, history=None, store=None) -> HoldingsExecutionResult:
    return execute_provider_holdings(event=event, manifests=manifests or ManifestStore.open(root, read_only=True),
                                     history=history or history_of(root),
                                     store=store or ProviderHoldingsStore.open(root))


def produce(root: Path, rows, context=CTX1):
    event, manifest = acquire(root, rows, context)
    result = run(root, event)
    assert result.authoritative, (result.status, result.failure_code)
    return event, manifest, result


def holdings(root: Path) -> ProviderHoldingsStore:
    return ProviderHoldingsStore.open(root, read_only=True)


def journal_bytes(root: Path) -> bytes:
    return (root / JOURNAL).read_bytes()


class View:
    """manifest の像の代替（test だけ。F1 は `by_acquisition` しか呼ばない）。"""

    def __init__(self, manifest) -> None:
        self.manifest = manifest

    def by_acquisition(self, reference: str):
        return self.manifest


def failed(result: HoldingsExecutionResult, status: X, code: str) -> None:
    assert result.status is status and result.failure_code == code, (result.status, result.failure_code)
    assert result.appended == () and result.reused == () and result.eligible_period_count == 0
    assert not result.authoritative


# ================================================================ A 生成（G3 ・昇順 ・holdings_as_of ・count ・決定論）


def test_a_one_record_per_canonical_period_end_in_ascending_order_bound_to_the_acquisition(root: Path) -> None:
    event, manifest, result = produce(root, [row(), quarterly("1Q"), HELD_FY])
    assert result.status is X.APPENDED and result.eligible_period_count == 2 and result.reused == ()
    records = [holdings(root).get(record_id) for record_id in result.appended]
    assert [r.period_end for r in records] == [P_1Q, P_FY]                                    # 昇順（manifest の順ではない）
    for r in records:
        assert r.dataset is FUND and r.subject_id == I1 and r.holdings_as_of == event.acquired_at == ACQ1
        assert r.acquisition_ref == event.reference and r.manifest_ref == manifest.reference
        assert r.canonical_entry_count == 1 and r.rules_version == fx.F1_RULES_VERSION
    assert result.subject_id == I1 and result.acquisition_ref == event.reference
    assert result.manifest_ref == manifest.reference and result.record_ids == result.appended
    assert result.rules_version == fx.F1_RULES_VERSION and result.failure_code == ""
    assert set(result.as_dict()) == {"acquisition_ref", "appended", "eligible_period_count", "failure_code",
                                     "manifest_ref", "reused", "rules_version", "status", "subject_id"}


def test_a_canonical_entry_count_counts_entries_not_fields_and_includes_same_period_corrections(root: Path) -> None:
    _, manifest, result = produce(root, [row(), CORRECTED])
    assert manifest.canonical_observation_count == 8 and len(result.appended) == 1      # 2 entry ・8 欄 ・1 record
    record = holdings(root).get(result.appended[0])
    assert record.period_end == P_FY and record.canonical_entry_count == 2


def test_a_held_rows_with_a_known_period_do_not_count_and_not_reported_rows_do_not_count(root: Path) -> None:
    _, _, result = produce(root, [row(), HELD_FY, EMPTY_2Q, NC_BROKEN])
    record = holdings(root).get(result.appended[0])
    assert len(result.appended) == 1 and record.period_end == P_FY and record.canonical_entry_count == 1


def test_a_record_ids_are_deterministic_across_independent_roots(tmp_path: Path) -> None:
    ids = []
    for name in ("one", "two"):
        private = tmp_path / name
        identity = ist.IdentityStore.initialize(private)
        for record in IDS.records:
            identity.append(record)
        for store in (ObservationStore, SemanticMetadataStore, HeldObservationStore, AcquisitionEventStore,
                      ManifestStore, ProviderHoldingsStore):
            store.initialize(private)
        _, _, result = produce(private, [row(), quarterly("1Q")])
        ids.append(result.appended)
    assert ids[0] == ids[1] and len(ids[0]) == 2


def test_a_the_result_carries_metadata_only(root: Path) -> None:
    event, _, result = produce(root, [row()])
    text = repr(result.as_dict()) + repr(result)
    assert event.content_digest not in text and "500000000000" not in text and "api_key" not in text
    assert "Sales" not in text and "Bearer" not in text


# ================================================================ B replay ・再取得 ・混在 ・衝突


def test_b_replay_of_the_same_inputs_reuses_every_record_and_writes_nothing(root: Path) -> None:
    event, _, first = produce(root, [row(), quarterly("1Q")])
    before = journal_bytes(root)
    again = run(root, event)
    assert again.status is X.REUSED and again.reused == first.appended and again.appended == ()
    assert again.eligible_period_count == 2 and journal_bytes(root) == before
    assert len(holdings(root).records()) == 2


def test_b_reacquisition_is_a_new_epoch_and_the_first_record_is_immutable(root: Path) -> None:
    e1, _, r1 = produce(root, [row()], CTX1)
    e2, _, r2 = produce(root, [row()], CTX2)                                                 # 同じ内容 ・別の取得の瞬間
    assert e1.reference != e2.reference and r2.status is X.APPENDED and r1.appended != r2.appended
    slot = holdings(root).for_slot(I1, P_FY)
    assert [r.holdings_as_of for r in slot] == [ACQ1, ACQ2] and [r.acquisition_ref for r in slot] == [e1.reference,
                                                                                                        e2.reference]
    assert holdings(root).get(r1.appended[0]) == ProviderHoldingsCoverage.from_dict(holdings(root).get(
        r1.appended[0]).as_dict())


def test_b_mixed_append_and_reuse_when_part_of_the_acquisition_is_already_recorded(root: Path) -> None:
    event, manifest = acquire(root, [row(), quarterly("1Q")])
    existing = ProviderHoldingsCoverage(dataset=FUND, subject_id=I1, period_end=P_FY, holdings_as_of=ACQ1,
                                        acquisition_ref=event.reference, manifest_ref=manifest.reference,
                                        canonical_entry_count=1, rules_version=fx.F1_RULES_VERSION)
    ProviderHoldingsStore.open(root).append(existing)
    result = run(root, event)
    assert result.status is X.MIXED_APPEND_REUSE and result.reused == (existing.record_id,)
    assert len(result.appended) == 1 and holdings(root).get(result.appended[0]).period_end == P_1Q
    assert result.record_ids == result.appended + result.reused


def test_b_a_different_record_for_the_same_acquisition_and_period_fails_closed_before_any_write(root: Path) -> None:
    event, manifest = acquire(root, [row(), quarterly("1Q")])
    ProviderHoldingsStore.open(root).append(holdings_of(manifest, ACQ1, period_end=P_FY))   # 別の rules_version → 別 id
    before = journal_bytes(root)
    failed(run(root, event), X.STORE_FAILURE, "PROVIDER_HOLDINGS_CONFLICT")
    assert journal_bytes(root) == before                                                       # 1Q も書かない（全体 preflight）


def test_b_a_read_only_store_an_external_change_and_a_foreign_store_type_are_rejected(root: Path) -> None:
    event, _ = acquire(root, [row()])
    failed(run(root, event, store=ProviderHoldingsStore.open(root, read_only=True)), X.PRECHECK_FAILED,
           "WRITABLE_STORE_REQUIRED")
    failed(run(root, event, store=ManifestStore.open(root)), X.PRECHECK_FAILED, "WRITABLE_STORE_REQUIRED")
    writer = ProviderHoldingsStore.open(root)
    ProviderHoldingsStore.open(root).append(holdings_of(built(root, [quarterly("1Q")], CTX2), ACQ2, period_end=P_1Q))
    failed(run(root, event, store=writer), X.STORE_FAILURE, "CONCURRENT_MODIFICATION")
    assert run(root, event).status is X.APPENDED                                              # 新しい writer なら書ける


# ================================================================ C event の authority（§5）


def test_c_only_a_complete_fins_summary_single_code_jquants_event_is_accepted(root: Path) -> None:
    rows = [row()]
    acquire(root, rows)
    failed(run(root, fins_event(rows, status=AcquisitionStatus.PARTIAL_PAGINATED, pagination=True)),
           X.ACQUISITION_NOT_COMPLETE, "PARTIAL_PAGINATED")
    failed(run(root, fins_event([], status=AcquisitionStatus.FAILED, failure_code="HTTP_500")),
           X.ACQUISITION_NOT_COMPLETE, "FAILED")
    failed(run(root, fins_event([], status=AcquisitionStatus.EMPTY)), X.ACQUISITION_NOT_COMPLETE, "EMPTY")
    failed(run(root, fins_event(rows, params={"code": "00010", "date": "2025-05-12"})), X.ACQUISITION_MISMATCH,
           "SCOPE_NOT_SINGLE_CODE")
    failed(run(root, fins_event(rows, params={"date": "2025-05-12"})), X.ACQUISITION_MISMATCH, "SCOPE_NOT_SINGLE_CODE")
    master = replace(fins_event(rows), scope=RequestScope.of(MASTER_PATH, {"date": "2025-05-12"}))
    failed(run(root, master), X.ACQUISITION_MISMATCH, "ENDPOINT_MISMATCH")
    failed(run(root, object()), X.ACQUISITION_MISMATCH, "INVALID_EVENT")
    failed(run(root, fins_event(rows).as_dict()), X.ACQUISITION_MISMATCH, "INVALID_EVENT")
    assert journal_bytes(root) == b""


def test_c_a_malformed_history_or_manifest_view_fails_before_touching_the_event(root: Path) -> None:
    event, _ = acquire(root, [row()])
    failed(run(root, event, history=object()), X.PRECHECK_FAILED, "INVALID_HISTORY")
    failed(run(root, event, manifests=object()), X.PRECHECK_FAILED, "MANIFEST_VIEW_REQUIRED")
    assert journal_bytes(root) == b""


# ================================================================ D manifest の結び付き（§6）


def test_d_the_manifest_must_be_the_authoritative_one_for_exactly_this_acquisition(root: Path) -> None:
    rows = [row()]
    event = fins_event(rows)
    failed(run(root, event), X.MANIFEST_MISSING, "NO_MANIFEST_FOR_ACQUISITION")             # 推定しない
    _, manifest = acquire(root, rows)
    other = fins_event([row(), quarterly("1Q")])
    failed(run(root, other), X.MANIFEST_MISSING, "NO_MANIFEST_FOR_ACQUISITION")
    failed(run(root, other, manifests=View(manifest)), X.MANIFEST_CONFLICT, "MANIFEST_ACQUISITION_MISMATCH")
    failed(run(root, event, manifests=View(replace(manifest, acquisition_content_digest="f" * 64))),
           X.MANIFEST_CONFLICT, "CONTENT_DIGEST_MISMATCH")
    foreign_code = fins_event(rows, code="00020")                                            # 同じ内容 ・別の code の範囲
    failed(run(root, foreign_code, manifests=View(replace(manifest, acquisition_ref=foreign_code.reference))),
           X.MANIFEST_CONFLICT, "PROVIDER_CODE_MISMATCH")
    bigger = replace(manifest, acquisition_ref=other.reference, acquisition_content_digest=other.content_digest)
    failed(run(root, other, manifests=View(bigger)), X.MANIFEST_CONFLICT, "ROW_COUNT_MISMATCH")
    failed(run(root, event, manifests=View(replace(manifest, subject_id="p8iss_" + "0" * 24))), X.MANIFEST_CONFLICT,
           "SUBJECT_INVALID")
    failed(run(root, event, manifests=View(replace(manifest, manifest_rules_version="p8_acquisition_manifest:9.9.9"))),
           X.MANIFEST_CONFLICT, "MANIFEST_RULES_VERSION_MISMATCH")
    failed(run(root, event, manifests=View(object())), X.MANIFEST_CONFLICT, "INVALID_MANIFEST")
    assert journal_bytes(root) == b""
    assert run(root, event).status is X.APPENDED


# ================================================================ E 取得全体の保留（§7）・記載なし（§8）・G3（§9 ・§10）


def test_e_an_unknown_period_held_row_blocks_every_record_of_the_acquisition(root: Path) -> None:
    event, _ = acquire(root, [row(), quarterly("1Q"), UNKNOWN])
    result = run(root, event)
    failed(result, X.UNKNOWN_PERIOD_HELD_ROW, "UNKNOWN_PERIOD_HELD_ROW")
    assert result.subject_id == I1 and result.manifest_ref != "" and journal_bytes(root) == b""
    assert holdings(root).for_slot(I1, P_FY) == () and holdings(root).for_slot(I1, P_1Q) == ()
    assert retro(root, query(root, built(root, [row()], CTX1)), ACQ1).status is S.OUTSIDE_COVERAGE
    assert fx.GLOBAL_HOLD_RULE == "ANY_UNKNOWN_PERIOD_HELD_ROW_BLOCKS_THE_WHOLE_ACQUISITION"


def test_e_a_held_row_with_a_known_period_still_lets_its_period_produce_a_record(root: Path) -> None:
    _, _, result = produce(root, [row(), HELD_FY, quarterly("1Q")])
    assert [holdings(root).get(r).period_end for r in result.appended] == [P_1Q, P_FY]
    assert holdings(root).for_slot(I1, P_FY)[0].canonical_entry_count == 1
    _, _, broken = produce(root, [quarterly("1Q", DiscNo="20250512000006"), BROKEN], CTX2)     # P 既知の UNSUPPORTED
    assert [holdings(root).get(r).period_end for r in broken.appended] == [P_1Q]


def test_e_no_canonical_period_means_no_record_and_a_distinct_status(root: Path) -> None:
    for rows, context in (([BROKEN], CTX1), ([HELD_FY], CTX2), ([EMPTY_FY], replace(CTX2, acquired_at=ACQ2 +
                                                                                         timedelta(days=7)))):
        event, _ = acquire(root, rows, context)
        failed(run(root, event), X.NO_CANONICAL_PERIODS, "NO_CANONICAL_PERIODS")
    assert journal_bytes(root) == b""


def test_e_a_not_reported_entry_without_period_or_basis_fails_closed_without_contaminating(root: Path) -> None:
    event, manifest = acquire(root, [row(), EMPTY_FY])
    entries = tuple(replace(e, period=None) if e.disposition.value == "NOT_REPORTED_ONLY" else e
                    for e in manifest.entries)
    failed(run(root, event, manifests=View(replace(manifest, entries=entries))), X.PRECHECK_FAILED,
           "NOT_REPORTED_ENTRY_WITHOUT_PERIOD_OR_BASIS")
    entries = tuple(replace(e, statement_basis=None) if e.disposition.value == "NOT_REPORTED_ONLY" else e
                    for e in manifest.entries)
    failed(run(root, event, manifests=View(replace(manifest, entries=entries))), X.PRECHECK_FAILED,
           "NOT_REPORTED_ENTRY_WITHOUT_PERIOD_OR_BASIS")
    assert journal_bytes(root) == b""
    assert run(root, event).status is X.APPENDED                                              # 期間を持つ記載なしは汚染しない


# ================================================================ F canonical の観測の preflight（§12）


def test_f_every_canonical_observation_must_be_bound_to_the_a2_view_before_any_write(root: Path) -> None:
    event, manifest = acquire(root, [row(), quarterly("1Q")])
    empty = ObservationHistory(IDS.history(), [])
    failed(run(root, event, history=empty), X.MEMBERSHIP_INVALID, "OBSERVATION_MISSING")
    history = history_of(root)
    swapped = tuple(replace(e, fields=tuple((f, manifest.entries[1 - i].fields[j][1]) for j, (f, _) in enumerate(
        e.fields))) for i, e in enumerate(manifest.entries))                                   # 欄の id を別の期間の行と入れ替える
    failed(run(root, event, history=history, manifests=View(replace(manifest, entries=swapped))),
           X.MEMBERSHIP_INVALID, "OBSERVATION_PERIOD_MISMATCH")
    wrong_field = tuple(replace(e, fields=tuple((f, e.fields[(j + 1) % len(e.fields)][1]) for j, (f, _) in enumerate(
        e.fields))) for e in manifest.entries)
    failed(run(root, event, manifests=View(replace(manifest, entries=wrong_field))), X.MEMBERSHIP_INVALID,
           "OBSERVATION_FIELD_MISMATCH")
    nc_entries = tuple(replace(e, statement_basis=NC) for e in manifest.entries)
    failed(run(root, event, manifests=View(replace(manifest, entries=nc_entries))), X.MEMBERSHIP_INVALID,
           "OBSERVATION_BASIS_MISMATCH")
    other_ref = tuple(replace(e, provider_record_ref=e.provider_record_ref.rpartition(":")[0] + ":" + "0" * 24,
                              provider_record_digest="0" * 64) for e in manifest.entries)
    failed(run(root, event, manifests=View(replace(manifest, entries=other_ref))), X.MEMBERSHIP_INVALID,
           "OBSERVATION_PROVENANCE_REF_MISMATCH")
    assert journal_bytes(root) == b""
    assert run(root, event).status is X.APPENDED


# ================================================================ G provider の修正 ・訂正（§20〜§23）


def test_g_provider_fix_case_a_epoch1_has_no_record_and_epoch2_produces_it(root: Path) -> None:
    e1, _ = acquire(root, [BROKEN], CTX1)
    failed(run(root, e1), X.NO_CANONICAL_PERIODS, "NO_CANONICAL_PERIODS")
    _, m2, r2 = produce(root, [row(Sales="1000")], CTX2)
    assert [holdings(root).get(r).period_end for r in r2.appended] == [P_FY]
    q = query(root, m2)
    assert retro(root, q, ACQ1).status is S.NOT_YET_KNOWN                                      # epoch 1 には record が無い
    assert retro(root, q, ACQ2).status is S.FOUND and retro(root, q, ACQ2).coverage_epoch_id.startswith("jq.pvh:")


def test_g_provider_fix_case_b_the_broken_period_is_absent_from_epoch1_but_other_periods_are_recorded(
        root: Path) -> None:
    _, m1, r1 = produce(root, [quarterly("1Q"), BROKEN], CTX1)
    assert [holdings(root).get(r).period_end for r in r1.appended] == [P_1Q]
    _, m2, r2 = produce(root, [quarterly("1Q"), row(Sales="1000")], CTX2)
    assert [holdings(root).get(r).period_end for r in r2.appended] == [P_1Q, P_FY]
    fy = query(root, m2, period=history_of(root).get(m2.entries[1].observation_ids[0]).period)
    assert retro(root, fy, ACQ1).status is S.NOT_YET_KNOWN and retro(root, fy, ACQ2).status is S.FOUND
    assert retro(root, query(root, m1), ACQ1).status is S.FOUND                                 # 1Q は epoch 1 から見える


def test_g_provider_fix_case_c_a_known_period_hold_beside_a_canonical_row_contaminates_only_non_members(
        root: Path) -> None:
    _, m1, r1 = produce(root, [row(), NC_BROKEN], CTX1)
    assert len(r1.appended) == 1
    assert retro(root, query(root, m1), ACQ1).status is S.FOUND                                 # member は FOUND
    held = retro(root, query(root, m1, basis=NC), ACQ1)
    assert held.status is S.SEMANTIC_HOLD and held.diagnostic == "HELD_ROW_AT_PERIOD"
    _, _, r2 = produce(root, [row(), NC_FIXED], CTX2)
    assert holdings(root).for_slot(I1, P_FY)[1].canonical_entry_count == 2 and len(r2.appended) == 1
    assert retro(root, query(root, m1, basis=NC), ACQ2).status is S.FOUND
    assert retro(root, query(root, m1, basis=NC), ACQ1).status is S.SEMANTIC_HOLD               # epoch 1 は不変


def test_g_a_same_period_correction_is_one_record_with_both_entries_counted(root: Path) -> None:
    _, m1, _ = produce(root, [row()], CTX1)
    _, m2, r2 = produce(root, [row(), CORRECTED], CTX2)
    assert len(r2.appended) == 1 and holdings(root).get(r2.appended[0]).canonical_entry_count == 2
    o1, o2 = m1.observation_ids[2], m2.entries[1].observation_ids[2]
    assert retro(root, query(root, m1), ACQ2 - timedelta(seconds=1)).record.record_id == o1
    assert retro(root, query(root, m1), ACQ2).record.record_id == o2


# ================================================================ H A2C-R との統合（§24）


def test_h_the_frozen_retrospective_resolver_consumes_f1_records_for_every_outcome(root: Path) -> None:
    _, manifest, _ = produce(root, [row(), HELD_FY, quarterly("1Q")])
    assert retro(root, query(root, manifest), ACQ1).status is S.FOUND
    held = retro(root, query(root, manifest, basis=NC), ACQ1)
    assert held.status is S.SEMANTIC_HOLD and held.diagnostic == "HELD_ROW_AT_PERIOD"
    assert retro(root, query(root, manifest), ACQ1 - timedelta(seconds=1)).status is S.NOT_YET_KNOWN
    _, clean, _ = produce(root, [quarterly("1Q", DiscNo="20250512000007")], CTX2)
    eps = retro(root, query(root, clean, F.EPS), ACQ2)
    assert eps.status is S.VALUE_ABSENT and eps.diagnostic == "FIELD_NOT_REPORTED_IN_EPOCH"
    not_found = retro(root, query(root, clean, basis=NC), ACQ2)
    assert not_found.status is S.NOT_FOUND and not_found.diagnostic == "NO_CANONICAL_MEMBER_FOR_COVERED_SLOT"
    assert not_found.coverage_epoch_id == holdings(root).for_slot(I1, P_1Q)[1].reference


# ================================================================ I STRICT ・A2 ・A3 の孤立（§25 ・§27）


def test_i_f1_never_writes_a2_coverage_and_strict_resolution_and_contradiction_are_untouched(root: Path) -> None:
    event, manifest = acquire(root, [row(), NC_BROKEN])
    observations_before = (root / "screener_intelligence" / "observation_records.jsonl").read_bytes()
    assert run(root, event).status is X.APPENDED
    history = history_of(root)
    assert history.coverages == [] and (root / JOURNAL).stat().st_size > 0
    assert (root / "screener_intelligence" / "observation_records.jsonl").read_bytes() == observations_before
    q = query(root, manifest)
    assert resolve(history, q, cutoff=FAR).status is S.OUTSIDE_COVERAGE                       # STRICT に coverage は無い
    strict = ObservationHistory(IDS.history(), [*history.records, legacy_cover()])
    assert resolve(strict, query(root, manifest, basis=NC), cutoff=FAR).status is S.NOT_FOUND  # 世界の知識の答えのまま
    fixed = execute(root, [NC_FIXED], CTX2)
    assert fixed[0].outcome.value == "APPENDED"                                               # 修正は矛盾しない
    with pytest.raises(ObservationAppendRejected):
        ObservationStore.open(root).append(holdings(root).records()[0])                        # 保持 record は A2 に入らない


def test_i_the_module_has_no_clock_network_io_knowledge_boundary_or_a2_coverage_and_a_single_append_site() -> None:
    source = executable_source(PACKAGE_DIR / "provider_holdings_executor.py")
    for token in ("ObservationCoverage", "complete_through", ".coverages", "KnowledgeTime", "certain_by", "now(",
                  "today(", "utcnow", "open(", "Path(", "os.", "://", "json", "resolve(", "COVERAGE_CONTRADICTION"):
        assert token not in source, token
    assert source.count("store.append(") == 1 and "verify_unchanged()" in source and "for_slot(" in source
    assert fx.OUTPUT_ORDER_RULE == "ASCENDING_PERIOD_END"
    tree = ast.parse((PACKAGE_DIR / "provider_holdings_executor.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Name) and node.id in {"open", "Path", "os", "getattr", "time", "sys"}
                   for node in ast.walk(tree))
    assert set(fx.__all__) == {"F1_RULES_VERSION", "GLOBAL_HOLD_RULE", "OUTPUT_ORDER_RULE", "HoldingsExecutionResult",
                               "HoldingsExecutionStatus", "execute_provider_holdings"}
    assert {s.value for s in X} >= {"APPENDED", "REUSED", "MIXED_APPEND_REUSE", "NO_CANONICAL_PERIODS",
                                    "UNKNOWN_PERIOD_HELD_ROW", "PRECHECK_FAILED"}
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        if path.stem != "provider_holdings_executor":
            assert "provider_holdings_executor" not in path.read_text(encoding="utf-8"), path.name
    for path in (REPO_ROOT / "src" / "intelligence" / "jquants_pilot2_local.py",
                 REPO_ROOT / "src" / "intelligence" / "jquants_local_transport.py", REPO_ROOT / "main.py"):
        assert "provider_holdings" not in path.read_text(encoding="utf-8"), path.name            # 配線は後の gate
