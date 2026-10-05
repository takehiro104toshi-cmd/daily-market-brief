"""P8-EPOCH1 — 取得 manifest（明示の membership authority）の model ・store ・builder の test。

境界 ／ 凍結の guard は `test_screener_intelligence_boundary.py`。
すべて合成（架空の code ・日付 ・行）。network ・時計 ・実データ ・LLM ・raw の応答は使わない。`acquired_at` は test が明示に渡す。
tmp_path の private root の store にだけ書く。EXE は凍結のまま呼ぶ（manifest の層は EXE を再実行しない）。
"""
from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import acquisition_manifest_builder as mb
from src.intelligence.screener_intelligence import acquisition_manifest_model as mm
from src.intelligence.screener_intelligence import acquisition_manifest_store as ms
from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence import observation_store as ost
from src.intelligence.screener_intelligence.acquisition_event_model import (AcquisitionEvent, AcquisitionModelError,
                                                                            AcquisitionStatus, RequestScope,
                                                                            bounded_content_digest)
from src.intelligence.screener_intelligence.acquisition_event_store import AcquisitionEventStore
from src.intelligence.screener_intelligence.acquisition_manifest_builder import (ManifestBuildResult, ManifestOutcome,
                                                                                 build_manifest, record_manifest)
from src.intelligence.screener_intelligence.acquisition_manifest_model import (AcquisitionManifest,
                                                                               ManifestDisposition, ManifestEntry,
                                                                               ManifestExecution, ManifestModelError,
                                                                               is_manifest_reference,
                                                                               manifest_reference)
from src.intelligence.screener_intelligence.acquisition_manifest_store import (AppendStatus, ManifestAppendRejected,
                                                                               ManifestConcurrentModification,
                                                                               ManifestStore, ManifestStoreCorrupt,
                                                                               ManifestStoreMissing)
from src.intelligence.screener_intelligence.held_observation_store import HeldObservationStore
from src.intelligence.screener_intelligence.identity_model import SourceClass
from src.intelligence.screener_intelligence.jquants_adapter_model import AdapterContext
from src.intelligence.screener_intelligence.jquants_execution_model import (ExecutionOutcome, ExecutionReason,
                                                                            FieldDisposition, WriteState,
                                                                            ordered_execution_reasons)
from src.intelligence.screener_intelligence.jquants_financial_summary_executor import execute_financial_summary_row
from src.intelligence.screener_intelligence.jquants_live_model import FINS_SUMMARY_PATH, MASTER_PATH
from src.intelligence.screener_intelligence.observation_model import (FundamentalField, ObservationHistory,
                                                                      PeriodBasis, ReportingPeriod, StatementBasis)
from src.intelligence.screener_intelligence.semantic_metadata_store import SemanticMetadataStore
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_jquants_adapter import quarterly, row
from tests.intelligence.test_screener_jquants_execution import FOREIGN, counts, lines
from tests.intelligence.test_screener_observation import Identity

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
IDS = Identity()
I1 = IDS.I1.issuer_id
I2 = IDS.I2.issuer_id
JST = timezone(timedelta(hours=9))
ACQ1 = datetime(2026, 10, 5, 18, 0, tzinfo=JST)                                         # 取得 E1（test が明示に渡す）
ACQ2 = ACQ1 + timedelta(days=7)                                                          # 取得 E2
CTX1 = AdapterContext(issuer_id=I1, acquired_at=ACQ1)
CTX2 = AdapterContext(issuer_id=I1, acquired_at=ACQ2)
CODE = "00010"                                                                           # 合成の adapter の test の code
KOREA = "FYFinancialStatements_Consolidated_KOREA"
MODIFIED = {"Sales": "500000000009"}                                                     # 同じ自然 key ・内容だけ違う
D = ManifestDisposition
X = ManifestExecution
MO = ManifestOutcome
EPOCH1_MODULES = ("acquisition_manifest_model", "acquisition_manifest_store", "acquisition_manifest_builder")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    private = tmp_path / "private_root"
    identity = ist.IdentityStore.initialize(private)
    for record in IDS.records:
        identity.append(record)
    ost.ObservationStore.initialize(private)
    SemanticMetadataStore.initialize(private)
    HeldObservationStore.initialize(private)
    AcquisitionEventStore.initialize(private)
    ManifestStore.initialize(private)
    return private


def fins_event(rows, *, code: str = CODE, acquired_at: datetime = ACQ1, status=AcquisitionStatus.COMPLETE,
               pagination: bool = False, failure_code: str = "", params=None) -> AcquisitionEvent:
    scope = RequestScope.of(FINS_SUMMARY_PATH, params if params is not None else {"code": code})
    content = bounded_content_digest(FINS_SUMMARY_PATH, rows)
    return AcquisitionEvent(provider=SourceClass.JQUANTS, scope=scope, acquired_at=acquired_at, status=status,
                            row_count=content.row_count, pagination_key_present=pagination,
                            pages_followed=0 if status is AcquisitionStatus.FAILED else 1,
                            content_digest=content.digest, failure_code=failure_code)


def execute(root: Path, rows, context: AdapterContext = CTX1) -> list:
    return [execute_financial_summary_row(mapping, context, root) for mapping in rows]


def views(root: Path):
    return ost.ObservationStore.open(root, read_only=True).history, HeldObservationStore.open(root, read_only=True)


def build(root: Path, rows, results, *, event: AcquisitionEvent = None, subject: str = I1, history=None,
          held=None) -> ManifestBuildResult:
    view_history, view_held = views(root)
    return build_manifest(event=event or fins_event(rows), rows=rows, results=results,
                          history=history or view_history, held_view=held or view_held, subject_id=subject)


def built(root: Path, rows, context: AdapterContext = CTX1, *, event: AcquisitionEvent = None) -> AcquisitionManifest:
    result = build(root, rows, execute(root, rows, context),
                   event=event or fins_event(rows, acquired_at=context.acquired_at))
    assert result.outcome is MO.BUILT and result.manifest is not None, (result.outcome, result.failure_code)
    return result.manifest


def observation_ids(manifest: AcquisitionManifest, index: int = 0) -> list:
    return list(manifest.entries[index].observation_ids)


# ================================================================ A model（entry ・manifest ・id ・参照 ・往復）


def test_a_the_manifest_round_trips_and_its_id_and_reference_are_deterministic(root: Path) -> None:
    rows = [row(), quarterly("1Q")]
    manifest = built(root, rows)
    data = json.loads(manifest.canonical_line())
    assert data["record_kind"] == "ACQUISITION_MANIFEST" and data["schema_version"] == mm.MANIFEST_SCHEMA_VERSION
    assert data["entry_count"] == 2 and data["canonical_observation_count"] == 8 and data["provider_code"] == CODE
    assert data["entry_order"] == "ACQ0_HANDOFF_ORDER_AS_RECEIVED" and data["subject_id"] == I1
    again = AcquisitionManifest.from_dict(data)
    assert again == manifest and again.canonical_line() == manifest.canonical_line()
    assert manifest.record_id.startswith("p8man_") and len(manifest.record_id) == 30
    assert manifest.reference == "jq.man:" + manifest.record_id[6:] and is_manifest_reference(manifest.reference)
    assert manifest_reference(manifest.record_id) == manifest.reference
    rebuilt = AcquisitionManifest(acquisition_ref=manifest.acquisition_ref,
                                  acquisition_content_digest=manifest.acquisition_content_digest, subject_id=I1,
                                  provider_code=CODE, executor_rules_version=manifest.executor_rules_version,
                                  mapping_rule_version=manifest.mapping_rule_version, entries=manifest.entries)
    assert rebuilt.record_id == manifest.record_id and rebuilt.reference == manifest.reference      # 同じ内容 → 同じ id
    reordered = replace(manifest, entries=tuple(reversed(manifest.entries)))
    assert reordered.record_id != manifest.record_id                                                 # 順も membership


def test_a_exact_replay_of_the_builder_yields_the_same_manifest(root: Path) -> None:
    rows = [row(), quarterly("1Q"), row(Sales="", OP="", NP="", TA="", DiscNo="20250512000009")]
    first = built(root, rows)
    results = execute(root, rows)                                                        # EXE は REUSED ・manifest は同じ
    assert [r.outcome.value for r in results] == ["REUSED", "REUSED", "NO_REPORTED_FIELDS"]
    second = build(root, rows, results).manifest
    assert first == second and first.record_id == second.record_id                       # 書いた ／ 収束したは membership でない
    assert [e.execution_outcome for e in first.entries] == [X.MATERIALIZED, X.MATERIALIZED, X.NO_REPORTED_FIELDS]
    store = ManifestStore.open(root)
    assert store.append(first).status is AppendStatus.APPENDED and store.append(second).status is AppendStatus.REUSED


def test_a_exact_replay_of_the_same_results_is_identical(root: Path) -> None:
    rows = [row(), quarterly("1Q")]
    results = execute(root, rows)
    one, two = build(root, rows, results), build(root, rows, results)
    assert one == two and one.manifest.record_id == two.manifest.record_id


def _entry(**overrides) -> ManifestEntry:
    base = dict(provider_record_ref=f"jq.fins_summary:{CODE}.20250512000001.FYFinancialStatements_Consolidated_JP:"
                                    + "a" * 24, provider_record_digest="a" * 64, disposition=D.CANONICAL,
                execution_outcome=X.MATERIALIZED, fields=((FundamentalField.REVENUE, "p8obs_" + "b" * 24),),
                period=ReportingPeriod(basis=PeriodBasis.FISCAL_YEAR, fiscal_year_start=datetime(2024, 4, 1).date(),
                                       fiscal_year_end=datetime(2025, 3, 31).date(),
                                       period_start=datetime(2024, 4, 1).date(),
                                       period_end=datetime(2025, 3, 31).date()),
                statement_basis=StatementBasis.CONSOLIDATED)
    return ManifestEntry(**{**base, **overrides})


@pytest.mark.parametrize("overrides,code", [
    ({"fields": ()}, "CANONICAL_REQUIRES_OBSERVATION"),
    ({"held_record_id": "p8hld_" + "c" * 24}, "CANONICAL_HAS_HELD"),
    ({"period": None}, "CANONICAL_REQUIRES_PERIOD"),
    ({"disposition": D.HELD_SEMANTIC, "fields": (), "execution_outcome": X.HELD}, "HELD_REQUIRES_HELD_ID"),
    ({"disposition": D.UNSUPPORTED, "fields": (), "execution_outcome": X.HELD}, "HELD_REQUIRES_HELD_ID"),
    ({"disposition": D.HELD_SEMANTIC, "held_record_id": "p8hld_" + "c" * 24, "execution_outcome": X.HELD},
     "NON_CANONICAL_HAS_OBSERVATION"),
    ({"disposition": D.NOT_REPORTED_ONLY, "fields": (), "held_record_id": "p8hld_" + "c" * 24,
      "execution_outcome": X.NO_REPORTED_FIELDS}, "NOT_REPORTED_HAS_HELD"),
    ({"disposition": D.HELD_SEMANTIC, "fields": (), "held_record_id": "p8hld_" + "c" * 24},
     "EXECUTION_DISPOSITION_MISMATCH"),
    ({"execution_outcome": "APPENDED"}, "INVALID_VOCABULARY"),
    ({"provider_record_digest": "f" * 64}, "DIGEST_REF_MISMATCH"),
    ({"provider_record_ref": "jq.acq:" + "a" * 24}, "INVALID_PROVIDER_REF"),
    ({"fields": ((FundamentalField.REVENUE, "p8obs_" + "b" * 24), (FundamentalField.REVENUE, "p8obs_" + "d" * 24))},
     "DUPLICATE_FIELD"),
    ({"fields": ((FundamentalField.TOTAL_ASSETS, "p8obs_" + "b" * 24),
                 (FundamentalField.REVENUE, "p8obs_" + "d" * 24))}, "FIELDS_NOT_CANONICAL"),
    ({"fields": ((FundamentalField.REVENUE, "500000000000"),)}, "INVALID_OBSERVATION_ID"),
    ({"disposition": "CANONICAL"}, "INVALID_VOCABULARY")])
def test_a_entry_invariants_fail_closed(overrides: dict, code: str) -> None:
    with pytest.raises(ManifestModelError) as exc:
        _entry(**overrides)
    assert exc.value.code == code


def test_a_dispositions_are_exactly_the_four_decided_by_the_supervisor() -> None:
    assert [d.value for d in D] == ["CANONICAL", "HELD_SEMANTIC", "NOT_REPORTED_ONLY", "UNSUPPORTED"]
    assert [x.value for x in X] == ["MATERIALIZED", "HELD", "NO_REPORTED_FIELDS"]
    held = _entry(disposition=D.HELD_SEMANTIC, fields=(), period=None, statement_basis=None,
                  held_record_id="p8hld_" + "c" * 24, execution_outcome=X.HELD)
    assert held.observation_ids == () and held.as_dict()["period"] is None
    unsupported = replace(held, disposition=D.UNSUPPORTED)
    not_reported = _entry(disposition=D.NOT_REPORTED_ONLY, fields=(), period=None, statement_basis=None,
                          execution_outcome=X.NO_REPORTED_FIELDS)
    for entry in (held, unsupported, not_reported):
        assert ManifestEntry.from_dict(entry.as_dict()) == entry


def _manifest(entries, **overrides) -> AcquisitionManifest:
    base = dict(acquisition_ref="jq.acq:" + "1" * 24, acquisition_content_digest="2" * 64, subject_id=I1,
                provider_code=CODE, executor_rules_version="p8_jquants_execution:0.1.0",
                mapping_rule_version="p8_jquants_v2_fins_summary_doctype:0.1.0", entries=tuple(entries))
    return AcquisitionManifest(**{**base, **overrides})


def test_a_manifest_invariants_fail_closed() -> None:
    one = _entry()
    other_digest = _entry(provider_record_ref=one.provider_record_ref[:-24] + "e" * 24, provider_record_digest="e" * 64,
                          fields=((FundamentalField.REVENUE, "p8obs_" + "e" * 24),))
    other_code = _entry(provider_record_ref=one.provider_record_ref.replace(CODE, "00020"),
                        fields=((FundamentalField.REVENUE, "p8obs_" + "e" * 24),))
    same_observation = _entry(provider_record_ref=one.provider_record_ref.replace("20250512000001", "20250512000002"))
    for entries, code in (((one, one), "DUPLICATE_PROVIDER_ROW"), ((one, other_digest), "PROVIDER_ROWS_INCONSISTENT"),
                          ((one, other_code), "ENTRY_CODE_MISMATCH"),
                          ((one, same_observation), "DUPLICATE_OBSERVATION")):
        with pytest.raises(ManifestModelError) as exc:
            _manifest(entries)
        assert exc.value.code == code
    for overrides, code in (({"acquisition_ref": "jq.man:" + "1" * 24}, "INVALID_ACQUISITION_REF"),
                            ({"acquisition_content_digest": "zz"}, "INVALID_DIGEST"),
                            ({"subject_id": "合成一号"}, "INVALID_SUBJECT"), ({"provider_code": "1301"}, "INVALID_CODE"),
                            ({"executor_rules_version": "token=abc:1.0.0"}, "INVALID_RULE_VERSION"),
                            ({"entries": (one, "x")}, "INVALID_ENTRIES")):
        entries = overrides.pop("entries", (one,))
        with pytest.raises(ManifestModelError) as exc:
            _manifest(entries, **overrides)
        assert exc.value.code == code
    empty = _manifest(())                                                                 # 構造として許すが builder は作らない
    assert empty.entry_count == 0 and empty.canonical_observation_count == 0


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(raw_rows=[]), "UNKNOWN_FIELD"), (lambda d: d.pop("entries"), "MISSING_FIELD"),
    (lambda d: d.update(record_id="p8man_" + "0" * 24), "RECORD_ID_MISMATCH"),
    (lambda d: d.update(entry_count=5), "COUNT_MISMATCH"),
    (lambda d: d.update(canonical_observation_count=0), "COUNT_MISMATCH"),
    (lambda d: d.update(schema_version="p8_acquisition_manifest:9.9.9"), "SCHEMA_MISMATCH"),
    (lambda d: d.update(record_kind="ACQUISITION_EVENT"), "KIND_MISMATCH"),
    (lambda d: d.update(entry_order="JOURNAL_POSITION"), "ENTRY_ORDER_MISMATCH"),
    (lambda d: d["entries"][0].update(amount="500000000000"), "UNKNOWN_FIELD"),
    (lambda d: d["entries"][0].update(disposition="LATEST"), "INVALID_VOCABULARY")])
def test_a_from_dict_rejects_unknown_fields_values_forged_ids_and_journal_order(mutate, code) -> None:
    data = _manifest((_entry(),)).as_dict()
    mutate(data)
    with pytest.raises(ManifestModelError) as exc:
        AcquisitionManifest.from_dict(data)
    assert exc.value.code == code


# ================================================================ B store（追記専用 ・REUSED ・衝突 ・破損）


def test_b_append_reused_lookups_and_order_independence(root: Path) -> None:
    store = ManifestStore.open(root)
    first = built(root, [row()])
    second = built(root, [row(), quarterly("1Q")], CTX2)
    assert store.append(first).status is AppendStatus.APPENDED
    assert store.append(first).status is AppendStatus.REUSED and len(store.records()) == 1
    assert store.append(second).status is AppendStatus.APPENDED
    assert store.get(second.record_id) == second and store.by_reference(first.reference) == first
    assert store.by_acquisition(second.acquisition_ref) == second and store.by_acquisition("jq.acq:" + "0" * 24) is None
    assert store.get("p8man_" + "0" * 24) is None and store.counts() == {"CANONICAL": 3}
    reopened = ManifestStore.open(root, read_only=True)
    assert reopened.records() == (first, second) and reopened.canonical_lines() == store.canonical_lines()
    with pytest.raises(ManifestAppendRejected) as exc:
        reopened.append(first)
    assert exc.value.code == "READ_ONLY"
    other = ManifestStore.initialize(root / "other")                                     # 物理の順が違っても同じ答え
    other.append(second)
    other.append(first)
    assert other.by_acquisition(first.acquisition_ref) == first and other.get(second.record_id) == second


def test_b_same_acquisition_with_a_different_manifest_is_a_conflict(root: Path) -> None:
    store = ManifestStore.open(root)
    rows = [row(), quarterly("1Q")]
    manifest = built(root, rows)
    store.append(manifest)
    different = replace(manifest, entries=manifest.entries[:1])                           # 同じ取得 ・違う membership
    assert different.acquisition_ref == manifest.acquisition_ref and different.record_id != manifest.record_id
    before = store.canonical_lines()
    with pytest.raises(ManifestAppendRejected) as exc:
        store.append(different)
    assert exc.value.code == "MANIFEST_CONFLICT" and store.canonical_lines() == before
    recorded = record_manifest(ManifestBuildResult(outcome=MO.BUILT, manifest=different), store)
    assert recorded.outcome is MO.MANIFEST_CONFLICT and recorded.manifest is None and not recorded.authoritative
    with pytest.raises(ManifestAppendRejected) as exc:
        store.append(fins_event(rows))
    assert exc.value.code == "INVALID_TYPE"


@pytest.mark.parametrize("tail,code", [
    (b'{"record_kind": "ACQUISITION_MANIFEST"', "TRUNCATED_FINAL_LINE"), (b"\n", "BLANK_LINE"),
    (b"not json\n", "INVALID_RECORD"), (b'{"record_kind": "OTHER"}\n', "INVALID_RECORD"),
    (b"\xff\xfe\n", "INVALID_ENCODING")])
def test_b_malformed_journal_fails_closed_and_is_never_repaired(root: Path, tail: bytes, code: str) -> None:
    store = ManifestStore.open(root)
    store.append(built(root, [row()]))
    path = root / "screener_intelligence" / "acquisition_manifests.jsonl"
    with path.open("ab") as handle:
        handle.write(tail)
    before = path.read_bytes()
    with pytest.raises(ManifestStoreCorrupt) as exc:
        ManifestStore.open(root)
    assert exc.value.code == code and path.read_bytes() == before


def test_b_non_canonical_duplicates_conflicting_lines_and_external_change_fail_closed(root: Path) -> None:
    store = ManifestStore.open(root)
    manifest = built(root, [row()])
    store.append(manifest)
    path = root / "screener_intelligence" / "acquisition_manifests.jsonl"
    original = path.read_bytes()
    for tail, code in ((manifest.canonical_line().encode(), "PHYSICAL_DUPLICATE"),
                       (json.dumps(manifest.as_dict(), separators=(", ", ": ")).encode() + b"\n", "NON_CANONICAL_LINE"),
                       (replace(manifest, entries=()).canonical_line().encode(), "ACQUISITION_DUPLICATE")):
        with path.open("ab") as handle:
            handle.write(tail)
        with pytest.raises(ManifestStoreCorrupt) as exc:
            ManifestStore.open(root)
        assert exc.value.code == code
        path.write_bytes(original)
    with path.open("ab") as handle:                                                      # 外からの変更 → 書かない
        handle.write(built(root, [quarterly("1Q")], CTX2).canonical_line().encode())
    with pytest.raises(ManifestConcurrentModification):
        store.append(built(root, [quarterly("2Q")], CTX2))
    assert path.read_bytes() != original
    with pytest.raises(ManifestStoreMissing):
        ManifestStore.open(root / "nowhere")
    with pytest.raises(ManifestAppendRejected) as exc:
        ManifestStore.open("")
    assert exc.value.code == "DATA_ROOT_REQUIRED"


def test_b_the_store_touches_only_its_own_journal_and_writes_through_append_only(root: Path) -> None:
    before = {p.name for p in (root / "screener_intelligence").iterdir()}
    ManifestStore.open(root).append(built(root, [row()]))
    assert {p.name for p in (root / "screener_intelligence").iterdir()} == before
    assert "acquisition_manifests.jsonl" in before and ms.MANIFEST_FILENAME == "acquisition_manifests.jsonl"
    assert ms.MANIFEST_DIRNAME == "screener_intelligence" and ms.AUTHORITY_CLASS == mm.MEMBERSHIP_AUTHORITY_RECORD
    source = executable_source(PACKAGE_DIR / "acquisition_manifest_store.py")
    for token in ("unlink", "rename", "truncate", '"wb"', '"w"', "write_text", "write_bytes", "sqlite", "compact",
                  "repair", "rewrite"):
        assert token not in source, token
    assert "fsync" in source and "'ab'" in source


# ================================================================ C ACQ0 の結び付き


def test_c_only_a_complete_fins_single_code_acquisition_yields_a_manifest(root: Path) -> None:
    rows = [row()]
    results = execute(root, rows)
    assert build(root, rows, results).outcome is MO.BUILT
    for kwargs in ({"status": AcquisitionStatus.PARTIAL_PAGINATED, "pagination": True},
                   {"status": AcquisitionStatus.FAILED, "failure_code": "HTTP_STATUS_500"}):
        result = build(root, rows, results, event=fins_event(rows, **kwargs))
        assert result.outcome is MO.ACQUISITION_NOT_COMPLETE and result.failure_code == kwargs["status"].value
    empty = fins_event([], status=AcquisitionStatus.EMPTY)
    result = build(root, [], [], event=empty)
    assert result.outcome is MO.ACQUISITION_NOT_COMPLETE and result.failure_code == "EMPTY" and result.manifest is None


def test_c_wrong_endpoint_provider_scope_digest_and_row_count_are_rejected(root: Path) -> None:
    rows = [row()]
    results = execute(root, rows)
    master_rows = [{"Date": "2026-07-01", "Code": "13010", "CoName": "合成", "CoNameEn": "Synth", "Mkt": "0111",
                    "ProdCat": "011"}]
    master = AcquisitionEvent(provider=SourceClass.JQUANTS, scope=RequestScope.of(MASTER_PATH, {"date": "2026-07-01"}),
                              acquired_at=ACQ1, status=AcquisitionStatus.COMPLETE, row_count=1,
                              pagination_key_present=False, pages_followed=1,
                              content_digest=bounded_content_digest(MASTER_PATH, master_rows).digest)
    assert build(root, rows, results, event=master).failure_code == "ENDPOINT_MISMATCH"
    with pytest.raises(AcquisitionModelError) as exc:                           # 凍結 ACQ0: provider は JQUANTS だけ
        replace(fins_event(rows), provider=SourceClass.OFFICIAL_EXCHANGE)
    assert exc.value.code == "PROVIDER_NOT_ALLOWED"

    class NotAnEvent:                                                                    # 「同等」の偽物は拒む
        provider, status, row_count = SourceClass.JQUANTS, AcquisitionStatus.COMPLETE, 1
        reference = content_digest = ""
        scope = fins_event(rows).scope
    assert build(root, rows, results, event=NotAnEvent()).failure_code == "INVALID_EVENT"
    with_date = build(root, rows, results, event=fins_event(rows, params={"code": CODE, "date": "2025-05-12"}))
    assert with_date.outcome is MO.ACQUISITION_MISMATCH and with_date.failure_code == "SCOPE_NOT_SINGLE_CODE"
    other_code = build(root, rows, results, event=fins_event(rows, code="13010"))
    assert other_code.outcome is MO.ACQUISITION_MISMATCH and other_code.failure_code == "ROW_OUTSIDE_SCOPE"
    digest = build(root, rows, results, event=fins_event([row(**MODIFIED)]))
    assert digest.outcome is MO.ACQUISITION_MISMATCH and digest.failure_code == "CONTENT_DIGEST_MISMATCH"
    two = [row(), quarterly("1Q")]
    reordered = build(root, two, execute(root, two), event=fins_event(list(reversed(two))))
    assert reordered.failure_code == "CONTENT_DIGEST_MISMATCH"                            # handoff の順も内容
    count = build(root, two, execute(root, two), event=fins_event(rows))
    assert count.outcome is MO.ACQUISITION_MISMATCH and count.failure_code == "ROW_COUNT_MISMATCH"
    assert build(root, rows, results, event=replace(fins_event(rows), acquired_at=ACQ2)).outcome is MO.BUILT
    assert counts(root) == (8, 16, 0)                                                     # builder は何も書かない


# ================================================================ D provider の行の結び付き ・EXE の結び付き


def test_d_one_row_is_exactly_one_entry_in_handoff_order(root: Path) -> None:
    rows = [quarterly("1Q"), row(), row(Sales="", OP="", NP="", TA="", DiscNo="20250512000009")]
    manifest = built(root, rows)
    assert manifest.entry_count == 3 and [e.disposition for e in manifest.entries] == [D.CANONICAL, D.CANONICAL,
                                                                                       D.NOT_REPORTED_ONLY]
    refs = [e.provider_record_ref for e in manifest.entries]
    assert refs[0].split(":")[1].split(".")[1] == "20250512000001" and ".1QFinancialStatements" in refs[0]
    assert refs[2].split(":")[1].split(".")[1] == "20250512000009" and manifest.canonical_observation_count == 8
    assert manifest.entries[0].period.quarter == 1 and manifest.entries[1].period.quarter == 0   # 参照する観測から
    assert manifest.entries[1].statement_basis is StatementBasis.CONSOLIDATED


def test_d_duplicate_rows_inconsistent_digests_and_missing_results_fail_closed(root: Path) -> None:
    rows = [row(), row()]
    results = execute(root, rows)
    result = build(root, rows, results)
    assert result.outcome is MO.DUPLICATE_PROVIDER_ROW and result.row_index == 1
    rows = [row(), row(**MODIFIED)]
    results = execute(root, rows, CTX1)
    assert [r.outcome.value for r in results] == ["REUSED", "APPENDED"]                  # EXE-R: revision は書ける
    result = build(root, rows, results)
    assert result.outcome is MO.PROVIDER_ROWS_INCONSISTENT and result.row_index == 1      # だが 1 取得に 2 revision は無い
    rows = [row(), quarterly("1Q")]
    results = execute(root, rows)
    missing = build(root, rows, results[:1])
    assert missing.outcome is MO.EXECUTION_INCOMPLETE and missing.failure_code == "RESULT_COUNT_MISMATCH"
    none = build(root, rows, [results[0], None])
    assert none.outcome is MO.EXECUTION_INCOMPLETE and none.failure_code == "RESULT_MISSING" and none.row_index == 1
    swapped = build(root, rows, list(reversed(results)))
    assert swapped.outcome is MO.ENTRY_INVALID and swapped.failure_code == "PROVIDER_RECORD_MISMATCH"
    bad_row = build(root, [{**row(), "Sales": None}], results[:1], event=fins_event(rows[:1]))
    assert bad_row.outcome is MO.ACQUISITION_MISMATCH and bad_row.failure_code == "INVALID_ROW"   # 凍結 ACQ0 が先に拒む


def test_d_rejected_and_partial_failure_block_the_manifest(root: Path) -> None:
    rows = [row(), row(**MODIFIED)]
    first = execute(root, rows[:1])
    rejected = execute(root, rows[1:], AdapterContext(issuer_id=I1))                     # acquired_at 無し → REJECTED
    assert rejected[0].outcome is ExecutionOutcome.REJECTED
    assert rejected[0].failure_code == "PROVIDER_REVISION_ACQUISITION_TIME_REQUIRED"
    result = build(root, rows[1:], rejected, event=fins_event(rows[1:]))
    assert result.outcome is MO.EXECUTION_INCOMPLETE and result.failure_code == "REJECTED" and result.manifest is None
    fields = first[0].fields                                                              # 凍結 EXE の形のまま合成する
    failed = replace(fields[1], disposition=FieldDisposition.FAILED, observation_id="", supersedes="",
                     observation_write=WriteState.FAILED, failure_code="STORE_WRITE_FAILED")
    partial = replace(first[0], outcome=ExecutionOutcome.PARTIAL_FAILURE,
                      reasons=ordered_execution_reasons((ExecutionReason.PARTIAL_WRITE,
                                                         ExecutionReason.STORE_WRITE_FAILED)),
                      fields=(fields[0], failed, *fields[2:]), failure_code="STORE_WRITE_FAILED")
    result = build(root, rows[:1], [partial], event=fins_event(rows[:1]))
    assert result.outcome is MO.EXECUTION_INCOMPLETE and result.failure_code == "PARTIAL_FAILURE"
    assert ManifestStore.open(root).records() == ()


# ================================================================ E 観測の結び付き（主語 ・欄 ・出所 ・期間 ・区分）


def test_e_appended_and_reused_observations_bind_to_the_a2_view(root: Path) -> None:
    rows = [row(TA="")]
    appended = execute(root, rows)
    manifest = build(root, rows, appended).manifest
    entry = manifest.entries[0]
    assert entry.disposition is D.CANONICAL and entry.execution_outcome is X.MATERIALIZED
    assert [f.value for f, _ in entry.fields] == ["NET_INCOME", "OPERATING_INCOME", "REVENUE"]  # TA は記載なし → 省く
    history, _ = views(root)
    for field, observation_id in entry.fields:
        record = history.get(observation_id)
        assert record.field is field and record.subject == I1
        assert record.provenance.source_record_ref == entry.provider_record_ref
    reused = execute(root, rows, CTX2)
    again = build(root, rows, reused, event=fins_event(rows, acquired_at=ACQ2)).manifest
    assert again.entries[0] == entry                                                      # 同じ membership
    assert again.record_id != manifest.record_id and again.acquisition_ref != manifest.acquisition_ref


def test_e_missing_wrong_subject_wrong_field_wrong_provenance_and_period_mismatch_are_rejected(root: Path,
                                                                                               tmp_path: Path) -> None:
    rows = [row()]
    results = execute(root, rows)
    empty_history = ObservationHistory(IDS.history())                                     # 観測の無い像
    missing = build(root, rows, results, history=empty_history)
    assert missing.outcome is MO.OBSERVATION_MISSING and missing.failure_code == "OBSERVATION_NOT_IN_VIEW"
    foreign = build(root, rows, results, subject=I2)
    assert foreign.outcome is MO.ENTRY_INVALID and foreign.failure_code == "SUBJECT_MISMATCH"
    relabeled = [replace(results[0], issuer_id=I2)]                                       # 結果の主語は I2 ・観測は I1
    assert build(root, rows, relabeled, subject=I2).failure_code == "OBSERVATION_SUBJECT_MISMATCH"
    fields = results[0].fields
    swapped = (replace(fields[0], field=fields[1].field), replace(fields[1], field=fields[0].field), *fields[2:])
    wrong_field = build(root, rows, [replace(results[0], fields=swapped)])
    assert wrong_field.outcome is MO.ENTRY_INVALID and wrong_field.failure_code == "OBSERVATION_FIELD_MISMATCH"
    quarter = execute(root, [quarterly("1Q")])[0]
    provenance = build(root, rows, [replace(quarter, provider_record=results[0].provider_record)])
    assert provenance.outcome is MO.ENTRY_INVALID and provenance.failure_code == "OBSERVATION_PROVENANCE_MISMATCH"
    history, _ = views(root)
    original = history.get(fields[0].observation_id)
    year_before = {name: getattr(original.period, name).replace(year=getattr(original.period, name).year - 1)
                   for name in ("fiscal_year_start", "fiscal_year_end", "period_start", "period_end")}
    shifted = replace(original, period=replace(original.period, **year_before))          # 同じ出所 ・違う期間（偽の像）
    tampered = ObservationHistory(IDS.history(), [*history.records, shifted])
    retargeted = [replace(results[0], fields=(replace(fields[0], observation_id=shifted.record_id), *fields[1:]))]
    mismatch = build(root, rows, retargeted, history=tampered)
    assert mismatch.outcome is MO.ENTRY_INVALID and mismatch.failure_code == "OBSERVATION_PERIOD_BASIS_MISMATCH"
    unknown = build(root, rows, results, subject="p8iss_" + "0" * 24)
    assert unknown.outcome is MO.ENTRY_INVALID and unknown.failure_code == "SUBJECT_UNKNOWN"


# ================================================================ F 保留 ・記載なし（行は在った、という事実を残す）


def test_f_held_semantic_unsupported_and_not_reported_rows_stay_in_the_manifest_without_membership(root: Path) -> None:
    rows = [row(), row(DocType=FOREIGN, DiscNo="20250512000002"), row(DocType=KOREA, DiscNo="20250512000003"),
            row(CurPerType="4Q", DiscNo="20250512000004"), row(Sales="1,000", DiscNo="20250512000005"),
            row(Sales="", OP="", NP="", TA="", DiscNo="20250512000006")]
    results = execute(root, rows)
    assert [r.outcome.value for r in results] == ["APPENDED", "HELD", "HELD", "HELD", "HELD", "NO_REPORTED_FIELDS"]
    manifest = build(root, rows, results).manifest
    assert [e.disposition for e in manifest.entries] == [D.CANONICAL, D.HELD_SEMANTIC, D.UNSUPPORTED, D.UNSUPPORTED,
                                                         D.UNSUPPORTED, D.NOT_REPORTED_ONLY]
    _, held = views(root)
    for entry, result in zip(manifest.entries[1:5], results[1:5]):
        assert entry.held_record_id == result.held_record_id and held.get(entry.held_record_id) is not None
        assert entry.fields == ()                                                           # EPOCH1R: 期間 ・区分は別 test
        assert entry.execution_outcome is X.HELD
    assert manifest.entries[5].held_record_id == "" and manifest.entries[5].fields == ()
    assert manifest.entry_count == 6 and manifest.canonical_observation_count == 4
    assert set(manifest.observation_ids) == {f.observation_id for f in results[0].fields}
    assert [r.value for r in mb.UNSUPPORTED_REASONS] == ["DOCTYPE_UNRECOGNIZED", "DOCTYPE_OUT_OF_SCOPE",
                                                         "PERIOD_UNSUPPORTED", "VALUE_UNPARSEABLE",
                                                         "KNOWLEDGE_TIME_INVALID", "MAPPING_UNSUPPORTED",
                                                         "TERMS_BOUNDARY"]


def test_f_missing_held_record_unresolved_identity_and_mismatched_held_record_fail_closed(root: Path) -> None:
    rows = [row(DocType=FOREIGN)]
    results = execute(root, rows)
    missing = build(root, rows, results, held=HeldObservationStore.initialize(root / "empty"))
    assert missing.outcome is MO.HELD_RECORD_MISSING and missing.failure_code == "HELD_RECORD_NOT_IN_VIEW"
    unresolved = execute(root, [row()], AdapterContext(issuer_id="p8iss_" + "0" * 24, acquired_at=ACQ1))
    assert unresolved[0].outcome is ExecutionOutcome.HELD
    result = build(root, [row()], [replace(unresolved[0], issuer_id=I1)], event=fins_event([row()]))
    assert result.outcome is MO.EXECUTION_INCOMPLETE and result.failure_code == "IDENTITY_UNRESOLVED"
    other = execute(root, [row(DocType=KOREA)])
    crossed = build(root, rows, [replace(results[0], held_record_id=other[0].held_record_id)])
    assert crossed.outcome is MO.ENTRY_INVALID and crossed.failure_code == "HELD_RECORD_MISMATCH"


# ================================================================ G privacy


def test_g_the_serialized_manifest_holds_metadata_only(root: Path) -> None:
    rows = [row(), row(DocType=FOREIGN, DiscNo="20250512000002"), row(Sales="", OP="", NP="", TA="",
                                                                      DiscNo="20250512000003")]
    store = ManifestStore.open(root)
    store.append(built(root, rows))
    text = (root / "screener_intelligence" / "acquisition_manifests.jsonl").read_text(encoding="utf-8")
    for forbidden in ("500000000000", "40000000000", "30000000000", "900000000000", "Sales", "\"OP\"", "\"NP\"",
                      "\"TA\"", "CoName", "合成", "Synth", "amount", "value", "raw", "payload", "header", "body",
                      "apikey", "api_key", "api-key", "token", "Bearer", "://", "x-api-key", "Authorization", "secret",
                      "DiscDate", "CurPerSt", "acquired_at", "knowledge", "journal_position", "line_number"):
        assert forbidden not in text, forbidden
    assert CODE in text and "jq.acq:" in text and "p8obs_" in text and "p8hld_" in text
    data = json.loads(text)
    assert set(data) == {"acquisition_content_digest", "acquisition_ref", "canonical_observation_count", "entries",
                         "entry_count", "entry_order", "executor_rules_version", "manifest_rules_version",
                         "mapping_rule_version", "provider_code", "record_id", "record_kind", "schema_version",
                         "subject_id"}
    assert set(data["entries"][0]) == {"disposition", "execution_outcome", "fields", "held_record_id", "period",
                                       "provider_record_digest", "provider_record_ref", "statement_basis"}
    for name in EPOCH1_MODULES:                                                           # model に値 ・名前の欄が無い
        source = executable_source(PACKAGE_DIR / f"{name}.py").lower()
        for token in ("amount", "coname", "company_name", "http", "header", "http_body", "api_key", "apikey"):
            assert token not in source, (name, token)


# ================================================================ H membership の証明（再取得 ・provider の修正 ・新しい DiscNo）


def test_h_reacquisition_two_authoritative_manifests_list_the_same_unchanged_observation(root: Path) -> None:
    rows = [row()]
    store = ManifestStore.open(root)
    one = built(root, rows, CTX1)
    two = built(root, rows, CTX2)
    assert record_manifest(ManifestBuildResult(outcome=MO.BUILT, manifest=one), store).outcome is MO.APPENDED
    recorded = record_manifest(ManifestBuildResult(outcome=MO.BUILT, manifest=two), store)
    assert recorded.outcome is MO.APPENDED and recorded.authoritative and recorded.manifest == two
    assert one.record_id != two.record_id and one.acquisition_ref != two.acquisition_ref
    assert observation_ids(one) == observation_ids(two) and len(observation_ids(one)) == 4
    history, _ = views(root)
    assert len(history.chains[history.get(observation_ids(one)[0]).slot_key]) == 1       # O は不変 ・1 つ
    assert lines(root, "observation_records.jsonl").__len__() == 4
    assert record_manifest(ManifestBuildResult(outcome=MO.BUILT, manifest=two), store).outcome is MO.REUSED


def test_h_provider_fix_the_second_epoch_lists_only_the_revision_and_the_original_stays_in_a2(root: Path) -> None:
    store = ManifestStore.open(root)
    e1 = built(root, [row()], CTX1)
    e2 = built(root, [row(**MODIFIED)], CTX2)                                           # 同じ自然 key ・違う digest（EXE-R）
    store.append(e1)
    store.append(e2)
    o1, o2 = observation_ids(e1), observation_ids(e2)
    assert set(o1).isdisjoint(o2) and len(o1) == len(o2) == 4
    assert e1.entries[0].provider_record_ref.rpartition(":")[0] == e2.entries[0].provider_record_ref.rpartition(":")[0]
    assert e1.entries[0].provider_record_digest != e2.entries[0].provider_record_digest
    history, _ = views(root)
    chain = history.chains[history.get(o1[0]).slot_key]
    assert [r.record_id for r in chain] == [o1[0], o2[0]] and chain[1].knowledge.at == ACQ2  # O1 は A2 に残る
    assert store.by_acquisition(e1.acquisition_ref).observation_ids == tuple(o1)
    assert store.by_acquisition(e2.acquisition_ref).observation_ids == tuple(o2)          # E2 の member は O2 だけ
    assert o1[0] not in store.by_acquisition(e2.acquisition_ref).observation_ids


def test_h_new_discno_correction_the_second_epoch_lists_both_rows_and_both_memberships(root: Path) -> None:
    corrected = row(DiscNo="20250512000002", DiscDate="2025-05-20", Sales="500000000001")
    e1 = built(root, [row()], CTX1)
    e2 = built(root, [row(), corrected], CTX2)
    o1 = observation_ids(e1)
    assert e2.entry_count == 2 and observation_ids(e2, 0) == o1                           # DiscNo A → O1 REUSED
    assert e2.entries[0] == e1.entries[0] and e2.entries[1].execution_outcome is X.MATERIALIZED
    o2 = observation_ids(e2, 1)
    assert set(o1).isdisjoint(o2) and set(e2.observation_ids) == set(o1) | set(o2)
    history, _ = views(root)
    chain = history.chains[history.get(o1[0]).slot_key]
    assert [r.record_id for r in chain] == [o1[0], o2[0]] and chain[1].supersedes == o1[0]


# ================================================================ I architecture ・語彙 ・位置の意味の不採用


def test_i_outcome_vocabulary_and_record_results() -> None:
    assert [o.value for o in MO] == ["BUILT", "APPENDED", "REUSED", "ACQUISITION_NOT_COMPLETE", "ACQUISITION_MISMATCH",
                                     "ENTRY_INVALID", "DUPLICATE_PROVIDER_ROW", "PROVIDER_ROWS_INCONSISTENT",
                                     "EXECUTION_INCOMPLETE", "OBSERVATION_MISSING", "HELD_RECORD_MISSING",
                                     "MANIFEST_CONFLICT", "STORE_FAILURE"]
    failed = ManifestBuildResult(outcome=MO.ENTRY_INVALID, failure_code="X")
    assert not failed.authoritative and record_manifest(failed, None).outcome is MO.STORE_FAILURE
    assert record_manifest(ManifestBuildResult(outcome=MO.BUILT, manifest=_manifest(())), "store").failure_code \
        == "INVALID_STORE"


def test_i_store_failure_is_typed_and_nothing_is_written(root: Path) -> None:
    store = ManifestStore.open(root)
    manifest = built(root, [row()])
    (root / "screener_intelligence" / "acquisition_manifests.jsonl").write_bytes(b"x\n")   # 外から壊された
    result = record_manifest(ManifestBuildResult(outcome=MO.BUILT, manifest=manifest), store)
    assert result.outcome is MO.STORE_FAILURE and result.failure_code == "CONCURRENT_MODIFICATION"


def test_i_no_clock_network_raw_persistence_coverage_resolver_or_journal_position_semantics() -> None:
    for name in EPOCH1_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        lowered = source.lower()
        for token in ("now(", "utcnow", "today(", "time.time", "monotonic", "perf_counter", "urllib", "socket", "http",
                      "environ", "getenv", "://", "sqlite", "random", "coverage(", "observationcoverage",
                      "complete_through", "holdings_as_of", "resolve(", "resolve_remediated", "execute_financial",
                      "line_number_of", "journal_position", "journal_order", "rowid", "fallback", "llm", "prompt"):
            assert token not in lowered, (name, token)
        tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
        if name != "acquisition_manifest_store":
            for node in ast.walk(tree):
                assert not (isinstance(node, ast.Name) and node.id in {"open", "Path", "os"}), (name, node.id)
    assert mm.ENTRY_ORDER_RULE == "ACQ0_HANDOFF_ORDER_AS_RECEIVED" and mm.MEMBERSHIP_AUTHORITY_RECORD \
        == "ACQUISITION_MEMBERSHIP_RECORD"
    assert "write" not in executable_source(PACKAGE_DIR / "acquisition_manifest_builder.py").replace("writes", "")
    for path in (REPO_ROOT / "src" / "intelligence" / "jquants_pilot2_local.py",
                 REPO_ROOT / "src" / "intelligence" / "jquants_local_transport.py", REPO_ROOT / "main.py"):
        assert "acquisition_manifest" not in path.read_text(encoding="utf-8"), path.name    # 配線は後の gate
    consumers = ("observation_retrospective_resolver",)                                      # 後の gate の consumer（A2C）
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        if path.stem not in (*EPOCH1_MODULES, *consumers):
            assert "acquisition_manifest" not in path.read_text(encoding="utf-8"), path.name  # 凍結の層は知らない
