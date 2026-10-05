"""P8-EPOCH1 — 取得 manifest の純な builder ／ validator（合成の用途。配線 ・実 request ・coverage は無い）。

1 つの凍結 ACQ0 `AcquisitionEvent`（fins ・COMPLETE ・`code=C` だけの範囲）と、handed off された provider の行（handoff の順）、
行ごとの凍結 EXE `ExecutionResult`、A2 の検証済みの像（`ObservationHistory`）、保留の像（`get(record_id)`）から、
**決定論で** `AcquisitionManifest` を組み、各結び付きを確かめる。EXE を再実行しない ・store に書かない ・時計 ・network ・raw の保存は無い。

fail closed（監督の決定 E5）: 取得が COMPLETE でない ・取得と行が一致しない ・行 1 つにでも結果が無い ／ REJECTED ／ PARTIAL_FAILURE ／
identity 未解決 ・参照する観測 ／ 保留 record が像に無い ・主語 ／ 欄 ／ 出所 ／ 期間 ／ 区分が合わない、のどれでも manifest を作らない。
store への記録は `record_manifest`（APPENDED ／ REUSED ／ MANIFEST_CONFLICT ／ STORE_FAILURE）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .acquisition_event_model import AcquisitionEvent, AcquisitionModelError, AcquisitionStatus, bounded_content_digest
from .acquisition_manifest_model import (AcquisitionManifest, ManifestDisposition, ManifestEntry, ManifestExecution,
                                         ManifestModelError)
from .acquisition_manifest_store import AppendStatus, ManifestStore, ManifestStoreError
from .held_observation_model import HeldReason, is_held_observation
from .identity_model import SourceClass
from .jquants_adapter_model import AdapterContext, AdapterInputError, AdapterStatus, FinancialSummaryRow, ProviderRecordIdentity
from .jquants_financial_summary_adapter import adapt_financial_summary_row, derive_reporting_period
from .jquants_execution_model import ExecutionOutcome, ExecutionResult, FieldDisposition
from .jquants_live_model import FINS_SUMMARY_PATH
from .observation_model import FundamentalActual, ObservationHistory

BUILDER_RULES_VERSION = "p8_acquisition_manifest_builder:0.2.0"                # EPOCH1R: 保留 ／ 記載なしの期間 ・区分
#: 構造の理由で保留された行（書類種別 ・期間 ・値 ・時刻の形 ・写像 ・規約の境界）→ `UNSUPPORTED`。他の保留 → `HELD_SEMANTIC`
UNSUPPORTED_REASONS: Tuple[HeldReason, ...] = (HeldReason.DOCTYPE_UNRECOGNIZED, HeldReason.DOCTYPE_OUT_OF_SCOPE,
                                               HeldReason.PERIOD_UNSUPPORTED, HeldReason.VALUE_UNPARSEABLE,
                                               HeldReason.KNOWLEDGE_TIME_INVALID, HeldReason.MAPPING_UNSUPPORTED,
                                               HeldReason.TERMS_BOUNDARY)
_CANONICAL_FIELD = (FieldDisposition.APPENDED, FieldDisposition.REUSED)


class ManifestOutcome(str, Enum):
    """builder ／ 記録の結果の語彙（監督の指示 §22）。`BUILT` は組めただけで、まだ何も書いていない。"""

    BUILT = "BUILT"
    APPENDED = "APPENDED"
    REUSED = "REUSED"
    ACQUISITION_NOT_COMPLETE = "ACQUISITION_NOT_COMPLETE"
    ACQUISITION_MISMATCH = "ACQUISITION_MISMATCH"
    ENTRY_INVALID = "ENTRY_INVALID"
    DUPLICATE_PROVIDER_ROW = "DUPLICATE_PROVIDER_ROW"
    PROVIDER_ROWS_INCONSISTENT = "PROVIDER_ROWS_INCONSISTENT"
    EXECUTION_INCOMPLETE = "EXECUTION_INCOMPLETE"
    OBSERVATION_MISSING = "OBSERVATION_MISSING"
    HELD_RECORD_MISSING = "HELD_RECORD_MISSING"
    MANIFEST_CONFLICT = "MANIFEST_CONFLICT"
    STORE_FAILURE = "STORE_FAILURE"


@dataclass(frozen=True)
class ManifestBuildResult:
    """派生 ・非永続。manifest は `BUILT` ／ `APPENDED` ／ `REUSED` のときだけ。`row_index` は handoff の順の位置（無ければ -1）。"""

    outcome: ManifestOutcome
    manifest: Optional[AcquisitionManifest] = None
    failure_code: str = ""
    row_index: int = -1

    @property
    def authoritative(self) -> bool:
        return self.outcome in (ManifestOutcome.APPENDED, ManifestOutcome.REUSED)


class _Fail(Exception):
    def __init__(self, outcome: ManifestOutcome, code: str, row_index: int = -1) -> None:
        super().__init__(code)
        self.outcome = outcome
        self.code = code
        self.row_index = row_index


def _check(condition: bool, outcome: ManifestOutcome, code: str, row_index: int = -1) -> None:
    if not condition:
        raise _Fail(outcome, code, row_index)


def _scope_code(event: AcquisitionEvent) -> str:
    """fins ・`code=C` だけの範囲（監督の指示 §7）。他の endpoint ・`date` を含む範囲 ・複数 code は manifest の対象外。"""
    _check(event.provider is SourceClass.JQUANTS, ManifestOutcome.ACQUISITION_MISMATCH, "PROVIDER_MISMATCH")
    _check(event.scope.endpoint == FINS_SUMMARY_PATH, ManifestOutcome.ACQUISITION_MISMATCH, "ENDPOINT_MISMATCH")
    keys = tuple(key for key, _ in event.scope.params)
    _check(keys == ("code",), ManifestOutcome.ACQUISITION_MISMATCH, "SCOPE_NOT_SINGLE_CODE")
    return event.scope.params[0][1]


def _bind_acquisition(event: Any, rows: Sequence[Mapping[str, Any]], results: Sequence[Any]) -> str:
    _check(isinstance(event, AcquisitionEvent), ManifestOutcome.ACQUISITION_MISMATCH, "INVALID_EVENT")
    code = _scope_code(event)
    _check(event.status is AcquisitionStatus.COMPLETE, ManifestOutcome.ACQUISITION_NOT_COMPLETE, event.status.value)
    _check(event.row_count == len(rows), ManifestOutcome.ACQUISITION_MISMATCH, "ROW_COUNT_MISMATCH")
    try:
        content = bounded_content_digest(FINS_SUMMARY_PATH, rows)
    except AcquisitionModelError as exc:
        raise _Fail(ManifestOutcome.ACQUISITION_MISMATCH, exc.code) from None
    _check(content.digest == event.content_digest, ManifestOutcome.ACQUISITION_MISMATCH, "CONTENT_DIGEST_MISMATCH")
    _check(len(results) == len(rows), ManifestOutcome.EXECUTION_INCOMPLETE, "RESULT_COUNT_MISMATCH")
    return code


def _identity_of(row: Mapping[str, Any], code: str, index: int) -> Tuple[ProviderRecordIdentity, str]:
    try:
        parsed = row if isinstance(row, FinancialSummaryRow) else FinancialSummaryRow.from_provider_mapping(row)
    except AdapterInputError as exc:
        raise _Fail(ManifestOutcome.ENTRY_INVALID, exc.code, index) from None
    identity = ProviderRecordIdentity.of(parsed)
    _check(identity.code == code, ManifestOutcome.ACQUISITION_MISMATCH, "ROW_OUTSIDE_SCOPE", index)
    reference = identity.reference()
    _check(reference is not None, ManifestOutcome.ENTRY_INVALID, "PROVIDER_REF_UNREFERENCEABLE", index)
    return identity, reference


def _canonical_fields(result: ExecutionResult, reference: str, subject_id: str, history: ObservationHistory,
                      index: int) -> Tuple[Tuple[Tuple[Any, str], ...], Any, Any]:
    """APPENDED ／ REUSED の欄 → (欄, 観測 id)。参照する観測の主語 ・欄 ・出所 ・期間 ・区分を A2 の像で確かめる。"""
    fields: List[Tuple[Any, str]] = []
    period = basis = None
    for executed in result.fields:
        if executed.disposition not in _CANONICAL_FIELD:
            _check(executed.disposition is FieldDisposition.NOT_REPORTED, ManifestOutcome.EXECUTION_INCOMPLETE,
                   "FIELD_" + executed.disposition.value, index)
            continue
        _check(executed.observation_id != "", ManifestOutcome.OBSERVATION_MISSING, "OBSERVATION_ID_EMPTY", index)
        record = history.get(executed.observation_id)
        _check(isinstance(record, FundamentalActual), ManifestOutcome.OBSERVATION_MISSING, "OBSERVATION_NOT_IN_VIEW",
               index)
        _check(record.subject == subject_id, ManifestOutcome.ENTRY_INVALID, "OBSERVATION_SUBJECT_MISMATCH", index)
        _check(record.field is executed.field, ManifestOutcome.ENTRY_INVALID, "OBSERVATION_FIELD_MISMATCH", index)
        _check(record.provenance.source_class is SourceClass.JQUANTS
               and record.provenance.source_record_ref == reference, ManifestOutcome.ENTRY_INVALID,
               "OBSERVATION_PROVENANCE_MISMATCH", index)
        if period is None:
            period, basis = record.period, record.statement_basis
        _check(record.period == period and record.statement_basis is basis, ManifestOutcome.ENTRY_INVALID,
               "OBSERVATION_PERIOD_BASIS_MISMATCH", index)
        fields.append((executed.field, executed.observation_id))
    _check(len(fields) >= 1, ManifestOutcome.EXECUTION_INCOMPLETE, "NO_CANONICAL_FIELD", index)
    return tuple(sorted(fields, key=lambda f: f[0].value)), period, basis


def _held_period_and_basis(row: Any, held: Any, index: int) -> Tuple[Any, Any]:
    """保留の行の期間 ・区分（P8-EPOCH1R）。期間は凍結 ADP0 の公開 helper、区分は保留 record の `attempted_statement_basis`。
    凍結の保留の理由と矛盾すれば fail closed（黙って正規化しない）。確定できなければ None。"""
    try:
        period = derive_reporting_period(row)
    except AdapterInputError as exc:
        raise _Fail(ManifestOutcome.ENTRY_INVALID, exc.code, index) from None
    period_unsupported = HeldReason.PERIOD_UNSUPPORTED in held.reasons
    _check((period is None) == period_unsupported, ManifestOutcome.ENTRY_INVALID, "HELD_PERIOD_INCONSISTENT", index)
    basis = held.attempted_statement_basis
    basis_unknown = HeldReason.STATEMENT_BASIS_UNKNOWN in held.reasons
    _check((basis is None) == basis_unknown, ManifestOutcome.ENTRY_INVALID, "HELD_BASIS_INCONSISTENT", index)
    return period, basis


def _not_reported_period_and_basis(row: Any, subject_id: str, index: int) -> Tuple[Any, Any]:
    """記載なしだけの行の期間 ・区分: 凍結 ADP0 の適格の材料そのもの（純 ・書かない）。適格でなければ fail closed。"""
    try:
        adapted = adapt_financial_summary_row(row, AdapterContext(issuer_id=subject_id))
    except AdapterInputError as exc:
        raise _Fail(ManifestOutcome.ENTRY_INVALID, exc.code, index) from None
    _check(adapted.status is AdapterStatus.ELIGIBLE and adapted.eligible is not None, ManifestOutcome.ENTRY_INVALID,
           "NOT_REPORTED_ROW_NOT_ELIGIBLE", index)
    material = adapted.eligible
    _check(len(material.observations) >= 1, ManifestOutcome.ENTRY_INVALID, "NOT_REPORTED_ROW_NO_MATERIAL", index)
    return material.period, material.observations[0].statement_basis


def _held_entry(result: ExecutionResult, identity: ProviderRecordIdentity, reference: str, held_view: Any,
                row: Any, index: int) -> ManifestEntry:
    _check(HeldReason.IDENTITY_UNRESOLVED not in result.held_reasons, ManifestOutcome.EXECUTION_INCOMPLETE,
           "IDENTITY_UNRESOLVED", index)
    _check(result.held_record_id != "", ManifestOutcome.HELD_RECORD_MISSING, "HELD_ID_EMPTY", index)
    held = held_view.get(result.held_record_id)
    _check(is_held_observation(held), ManifestOutcome.HELD_RECORD_MISSING, "HELD_RECORD_NOT_IN_VIEW", index)
    _check(held.provider_record_ref == reference and held.provider_record_digest == identity.digest,
           ManifestOutcome.ENTRY_INVALID, "HELD_RECORD_MISMATCH", index)
    _check(held.reasons == result.held_reasons, ManifestOutcome.ENTRY_INVALID, "HELD_REASONS_MISMATCH", index)
    structural = any(reason in UNSUPPORTED_REASONS for reason in result.held_reasons)
    disposition = ManifestDisposition.UNSUPPORTED if structural else ManifestDisposition.HELD_SEMANTIC
    period, basis = _held_period_and_basis(row, held, index)
    return ManifestEntry(provider_record_ref=reference, provider_record_digest=identity.digest,
                         disposition=disposition, execution_outcome=ManifestExecution.HELD,
                         held_record_id=result.held_record_id, period=period, statement_basis=basis)


def _entry(result: Any, identity: ProviderRecordIdentity, reference: str, subject_id: str,
           history: ObservationHistory, held_view: Any, row: Any, index: int) -> ManifestEntry:
    _check(isinstance(result, ExecutionResult), ManifestOutcome.EXECUTION_INCOMPLETE, "RESULT_MISSING", index)
    _check(result.provider_record == identity, ManifestOutcome.ENTRY_INVALID, "PROVIDER_RECORD_MISMATCH", index)
    _check(result.outcome not in (ExecutionOutcome.REJECTED, ExecutionOutcome.PARTIAL_FAILURE),
           ManifestOutcome.EXECUTION_INCOMPLETE, result.outcome.value, index)
    _check(result.issuer_id == subject_id, ManifestOutcome.ENTRY_INVALID, "SUBJECT_MISMATCH", index)
    if result.outcome is ExecutionOutcome.HELD:
        return _held_entry(result, identity, reference, held_view, row, index)
    if result.outcome is ExecutionOutcome.NO_REPORTED_FIELDS:
        period, basis = _not_reported_period_and_basis(row, subject_id, index)
        return ManifestEntry(provider_record_ref=reference, provider_record_digest=identity.digest,
                             disposition=ManifestDisposition.NOT_REPORTED_ONLY,
                             execution_outcome=ManifestExecution.NO_REPORTED_FIELDS, period=period,
                             statement_basis=basis)
    fields, period, basis = _canonical_fields(result, reference, subject_id, history, index)
    return ManifestEntry(provider_record_ref=reference, provider_record_digest=identity.digest,
                         disposition=ManifestDisposition.CANONICAL, execution_outcome=ManifestExecution.MATERIALIZED,
                         fields=fields, period=period, statement_basis=basis)


def build_manifest(*, event: Any, rows: Any, results: Any, history: Any, held_view: Any,
                   subject_id: Any) -> ManifestBuildResult:
    """取得 event ＋ handoff の行 ＋ 行ごとの EXE の結果 ＋ A2 ／ 保留の像 → manifest（純 ・決定論 ・書かない）。"""
    try:
        _check(isinstance(rows, (list, tuple)) and all(isinstance(r, (Mapping, FinancialSummaryRow)) for r in rows),
               ManifestOutcome.ENTRY_INVALID, "INVALID_ROWS")
        _check(isinstance(results, (list, tuple)), ManifestOutcome.EXECUTION_INCOMPLETE, "INVALID_RESULTS")
        _check(isinstance(history, ObservationHistory), ManifestOutcome.OBSERVATION_MISSING, "INVALID_HISTORY")
        _check(hasattr(held_view, "get") and callable(held_view.get), ManifestOutcome.HELD_RECORD_MISSING,
               "INVALID_HELD_VIEW")
        _check(isinstance(subject_id, str) and subject_id in history.identity.issuers, ManifestOutcome.ENTRY_INVALID,
               "SUBJECT_UNKNOWN")
        code = _bind_acquisition(event, rows, results)
        entries: List[ManifestEntry] = []
        seen: Dict[str, int] = {}
        natural: Dict[str, str] = {}
        for index, (row, result) in enumerate(zip(rows, results)):
            identity, reference = _identity_of(row, code, index)
            _check(reference not in seen, ManifestOutcome.DUPLICATE_PROVIDER_ROW, "DUPLICATE_PROVIDER_REF", index)
            seen[reference] = index
            head = reference.rpartition(":")[0]
            _check(natural.setdefault(head, identity.digest) == identity.digest,
                   ManifestOutcome.PROVIDER_ROWS_INCONSISTENT, "NATURAL_KEY_DIGEST_CONFLICT", index)
            entries.append(_entry(result, identity, reference, subject_id, history, held_view, row, index))
        versions = {(r.rules_version, r.mapping_rule_version) for r in results}
        _check(len(versions) == 1, ManifestOutcome.ENTRY_INVALID, "RULES_VERSION_INCONSISTENT")
        (executor_version, mapping_version), = versions
        try:
            manifest = AcquisitionManifest(acquisition_ref=event.reference,
                                           acquisition_content_digest=event.content_digest, subject_id=subject_id,
                                           provider_code=code, executor_rules_version=executor_version,
                                           mapping_rule_version=mapping_version, entries=tuple(entries))
        except ManifestModelError as exc:
            raise _Fail(ManifestOutcome.ENTRY_INVALID, exc.code) from None
    except _Fail as fail:
        return ManifestBuildResult(outcome=fail.outcome, failure_code=fail.code, row_index=fail.row_index)
    return ManifestBuildResult(outcome=ManifestOutcome.BUILT, manifest=manifest)


def record_manifest(built: ManifestBuildResult, store: ManifestStore) -> ManifestBuildResult:
    """組めた manifest だけを store に追記する。同じ manifest は REUSED、同じ取得に違う manifest は MANIFEST_CONFLICT。"""
    if not isinstance(built, ManifestBuildResult) or built.outcome is not ManifestOutcome.BUILT \
            or built.manifest is None:
        return ManifestBuildResult(outcome=ManifestOutcome.STORE_FAILURE, failure_code="NOTHING_TO_RECORD")
    if not isinstance(store, ManifestStore):
        return ManifestBuildResult(outcome=ManifestOutcome.STORE_FAILURE, failure_code="INVALID_STORE")
    try:
        appended = store.append(built.manifest)
    except ManifestStoreError as exc:
        conflict = exc.code == "MANIFEST_CONFLICT"
        outcome = ManifestOutcome.MANIFEST_CONFLICT if conflict else ManifestOutcome.STORE_FAILURE
        return ManifestBuildResult(outcome=outcome, failure_code=exc.code)
    except OSError:
        return ManifestBuildResult(outcome=ManifestOutcome.STORE_FAILURE, failure_code="OS_ERROR")
    outcome = ManifestOutcome.APPENDED if appended.status is AppendStatus.APPENDED else ManifestOutcome.REUSED
    return ManifestBuildResult(outcome=outcome, manifest=built.manifest)


__all__ = ["BUILDER_RULES_VERSION", "UNSUPPORTED_REASONS", "ManifestBuildResult", "ManifestOutcome", "build_manifest",
           "record_manifest"]
