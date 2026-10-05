"""P8-OBS60-F1 — `ProviderHoldingsCoverage` の producer（決定論 ・preflight ・追記専用）。

COMPLETE な取得 event（凍結 ACQ0）＋ その取得の authoritative な manifest（凍結 EPOCH1R）＋ A2 の canonical の像（凍結）→ period_end ごとに
1 つの `ProviderHoldingsCoverage`（凍結 A2C-R の model）→ 凍結 `ProviderHoldingsStore` に append。

- **作らないもの**: A2 の `ObservationCoverage`（世界の完全性の宣言）は決して作らない ・`ObservationHistory.coverages` に書かない ・STRICT の
  `_coverage` ・`COVERAGE_CONTRADICTION` ・A3 に触れない。`complete_through` ・知識の境界（max ／ earliest ／ certain_by）・provider の反映時刻
  を計算しない。時計 ・network ・raw の payload ・「最新」の既定は無い。
- **取得全体の保留の規則（監督の決定）**: manifest に period が None の HELD_SEMANTIC ／ UNSUPPORTED が 1 つでもあれば **0 record**
  （他の period_end にも作らない）。NOT_REPORTED_ONLY はこの規則を起こさないが、期間 ・区分が無ければ fail closed（捏造しない）。
- **G3**: CANONICAL の entry が 1 つ以上ある period_end P だけに record。期間 P が既知の保留を伴っても record は作る（不在の汚染は凍結
  A2C-R の resolver が manifest から導く）。`canonical_entry_count` ＝ P の CANONICAL の entry の数（欄ではなく entry）。
- **preflight**: event の結び付き ・manifest の整合 ・全体の保留 ・記載なしの構造 ・全 CANONICAL の観測の A2 の像との結び付き ・全出力 record ・
  store の衝突を**最初の append の前に**すべて確かめる。1 つでも失敗 → 0 write。順は period_end の昇順（manifest の entry の順 ・journal の
  位置に依らない）。同じ入力の replay は全 record REUSED。rollback ・削除 ・修復は無い。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Tuple

from .acquisition_event_model import API_VERSION, AcquisitionEvent, AcquisitionStatus
from .acquisition_manifest_model import (MANIFEST_RULES_VERSION, MANIFEST_SCHEMA_VERSION, AcquisitionManifest,
                                         ManifestDisposition)
from .identity_model import SourceClass, is_issuer_id
from .jquants_live_model import FINS_SUMMARY_PATH
from .observation_model import CoverageDataset, FundamentalActual, ObservationHistory
from .provider_holdings_model import HoldingsModelError, ProviderHoldingsCoverage
from .provider_holdings_store import HoldingsStoreError, ProviderHoldingsStore

F1_RULES_VERSION = "p8_provider_holdings_executor:0.1.0"
#: 出力の順: period_end の昇順（manifest の entry の順 ・A2 ・store の journal の位置に依らない）
OUTPUT_ORDER_RULE = "ASCENDING_PERIOD_END"
#: 取得全体の保留の規則: 期間が不明な保留が 1 つでもあれば record を 1 つも作らない
GLOBAL_HOLD_RULE = "ANY_UNKNOWN_PERIOD_HELD_ROW_BLOCKS_THE_WHOLE_ACQUISITION"
_HELD = (ManifestDisposition.HELD_SEMANTIC, ManifestDisposition.UNSUPPORTED)


class HoldingsExecutionStatus(str, Enum):
    APPENDED = "APPENDED"                                # 全 record を新しく書いた
    REUSED = "REUSED"                                    # 全 record が既に在った（正確な replay）
    MIXED_APPEND_REUSE = "MIXED_APPEND_REUSE"            # 一部は在り ・一部を書いた
    NO_CANONICAL_PERIODS = "NO_CANONICAL_PERIODS"        # CANONICAL の entry が無い（保留 ／ 記載なしだけ）→ 0 record
    UNKNOWN_PERIOD_HELD_ROW = "UNKNOWN_PERIOD_HELD_ROW"  # 期間が不明な保留 → 取得全体で 0 record
    ACQUISITION_NOT_COMPLETE = "ACQUISITION_NOT_COMPLETE"
    ACQUISITION_MISMATCH = "ACQUISITION_MISMATCH"
    MANIFEST_MISSING = "MANIFEST_MISSING"
    MANIFEST_CONFLICT = "MANIFEST_CONFLICT"
    MEMBERSHIP_INVALID = "MEMBERSHIP_INVALID"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    STORE_FAILURE = "STORE_FAILURE"


_TERMINAL_OK = (HoldingsExecutionStatus.APPENDED, HoldingsExecutionStatus.REUSED,
                HoldingsExecutionStatus.MIXED_APPEND_REUSE)


@dataclass(frozen=True)
class HoldingsExecutionResult:
    """派生 ・非永続 ・metadata だけ（値 ・会社名 ・raw の行 ・credential ・header は無い）。"""

    status: HoldingsExecutionStatus
    subject_id: str = ""
    acquisition_ref: str = ""
    manifest_ref: str = ""
    eligible_period_count: int = 0
    appended: Tuple[str, ...] = ()
    reused: Tuple[str, ...] = ()
    failure_code: str = ""
    rules_version: str = F1_RULES_VERSION

    @property
    def authoritative(self) -> bool:
        return self.status in _TERMINAL_OK

    @property
    def record_ids(self) -> Tuple[str, ...]:
        return self.appended + self.reused

    def as_dict(self) -> Dict[str, Any]:
        return {"acquisition_ref": self.acquisition_ref, "appended": list(self.appended),
                "eligible_period_count": self.eligible_period_count, "failure_code": self.failure_code,
                "manifest_ref": self.manifest_ref, "reused": list(self.reused), "rules_version": self.rules_version,
                "status": self.status.value, "subject_id": self.subject_id}


class _Fail(Exception):
    def __init__(self, status: HoldingsExecutionStatus, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _check(condition: bool, status: HoldingsExecutionStatus, code: str) -> None:
    if not condition:
        raise _Fail(status, code)


def _bind_event(event: Any) -> str:
    """凍結 ACQ0 の event の authority の要件（§5）。返すのは範囲の code。"""
    _check(isinstance(event, AcquisitionEvent), HoldingsExecutionStatus.ACQUISITION_MISMATCH, "INVALID_EVENT")
    _check(event.provider is SourceClass.JQUANTS, HoldingsExecutionStatus.ACQUISITION_MISMATCH, "PROVIDER_MISMATCH")
    _check(event.identity_payload().get("api_version") == API_VERSION, HoldingsExecutionStatus.ACQUISITION_MISMATCH,
           "API_VERSION_MISMATCH")
    _check(event.scope.endpoint == FINS_SUMMARY_PATH, HoldingsExecutionStatus.ACQUISITION_MISMATCH, "ENDPOINT_MISMATCH")
    _check(tuple(key for key, _ in event.scope.params) == ("code",), HoldingsExecutionStatus.ACQUISITION_MISMATCH,
           "SCOPE_NOT_SINGLE_CODE")
    _check(event.status is AcquisitionStatus.COMPLETE, HoldingsExecutionStatus.ACQUISITION_NOT_COMPLETE,
           event.status.value)
    return event.scope.params[0][1]


def _bind_manifest(event: AcquisitionEvent, code: str, manifests: Any,
                   history: ObservationHistory) -> AcquisitionManifest:
    """event.reference の authoritative な manifest がちょうど 1 つ（§6）。推定しない。"""
    manifest = manifests.by_acquisition(event.reference)
    _check(manifest is not None, HoldingsExecutionStatus.MANIFEST_MISSING, "NO_MANIFEST_FOR_ACQUISITION")
    _check(isinstance(manifest, AcquisitionManifest), HoldingsExecutionStatus.MANIFEST_CONFLICT, "INVALID_MANIFEST")
    _check(manifest.acquisition_ref == event.reference, HoldingsExecutionStatus.MANIFEST_CONFLICT,
           "MANIFEST_ACQUISITION_MISMATCH")
    _check(manifest.acquisition_content_digest == event.content_digest, HoldingsExecutionStatus.MANIFEST_CONFLICT,
           "CONTENT_DIGEST_MISMATCH")
    _check(manifest.provider_code == code, HoldingsExecutionStatus.MANIFEST_CONFLICT, "PROVIDER_CODE_MISMATCH")
    _check(manifest.entry_count == event.row_count, HoldingsExecutionStatus.MANIFEST_CONFLICT, "ROW_COUNT_MISMATCH")
    _check(is_issuer_id(manifest.subject_id) and manifest.subject_id in history.identity.issuers,
           HoldingsExecutionStatus.MANIFEST_CONFLICT, "SUBJECT_INVALID")
    _check(manifest.manifest_rules_version == MANIFEST_RULES_VERSION, HoldingsExecutionStatus.MANIFEST_CONFLICT,
           "MANIFEST_RULES_VERSION_MISMATCH")
    _check(manifest.identity_payload().get("schema_version") == MANIFEST_SCHEMA_VERSION,
           HoldingsExecutionStatus.MANIFEST_CONFLICT, "MANIFEST_SCHEMA_MISMATCH")
    return manifest


def _preflight_entries(manifest: AcquisitionManifest, history: ObservationHistory) -> Dict[date, int]:
    """取得全体の保留（§7）・記載なしの構造（§8）・全 CANONICAL の観測の結び付き（§12）→ period_end ごとの CANONICAL の数（§9 ・§11）。"""
    for entry in manifest.entries:
        if entry.disposition in _HELD and entry.period is None:
            raise _Fail(HoldingsExecutionStatus.UNKNOWN_PERIOD_HELD_ROW, "UNKNOWN_PERIOD_HELD_ROW")
    counts: Dict[date, int] = {}
    for entry in manifest.entries:
        if entry.disposition is ManifestDisposition.NOT_REPORTED_ONLY:
            _check(entry.period is not None and entry.statement_basis is not None,
                   HoldingsExecutionStatus.PRECHECK_FAILED, "NOT_REPORTED_ENTRY_WITHOUT_PERIOD_OR_BASIS")
            continue
        if entry.disposition is not ManifestDisposition.CANONICAL:
            continue
        for field, observation_id in entry.fields:
            record = history.get(observation_id)
            _check(isinstance(record, FundamentalActual), HoldingsExecutionStatus.MEMBERSHIP_INVALID,
                   "OBSERVATION_MISSING")
            _check(record.subject == manifest.subject_id, HoldingsExecutionStatus.MEMBERSHIP_INVALID,
                   "OBSERVATION_SUBJECT_MISMATCH")
            _check(record.field is field, HoldingsExecutionStatus.MEMBERSHIP_INVALID, "OBSERVATION_FIELD_MISMATCH")
            _check(record.period == entry.period, HoldingsExecutionStatus.MEMBERSHIP_INVALID,
                   "OBSERVATION_PERIOD_MISMATCH")
            _check(record.statement_basis is entry.statement_basis, HoldingsExecutionStatus.MEMBERSHIP_INVALID,
                   "OBSERVATION_BASIS_MISMATCH")
            _check(record.provenance.source_class is SourceClass.JQUANTS, HoldingsExecutionStatus.MEMBERSHIP_INVALID,
                   "OBSERVATION_PROVENANCE_SOURCE_MISMATCH")
            _check(record.provenance.source_record_ref == entry.provider_record_ref,
                   HoldingsExecutionStatus.MEMBERSHIP_INVALID, "OBSERVATION_PROVENANCE_REF_MISMATCH")
        period_end = entry.period.period_end
        counts[period_end] = counts.get(period_end, 0) + 1
    return counts


def _records_for(event: AcquisitionEvent, manifest: AcquisitionManifest,
                counts: Dict[date, int]) -> Tuple[ProviderHoldingsCoverage, ...]:
    """eligible な period_end ごとに 1 record（§14）。holdings_as_of ＝ event.acquired_at そのもの（§15）。昇順（§16）。"""
    records: List[ProviderHoldingsCoverage] = []
    try:
        for period_end in sorted(counts):
            records.append(ProviderHoldingsCoverage(dataset=CoverageDataset.FUNDAMENTAL_DISCLOSURE,
                                                    subject_id=manifest.subject_id, period_end=period_end,
                                                    holdings_as_of=event.acquired_at, acquisition_ref=event.reference,
                                                    manifest_ref=manifest.reference,
                                                    canonical_entry_count=counts[period_end],
                                                    rules_version=F1_RULES_VERSION))
    except HoldingsModelError as exc:
        raise _Fail(HoldingsExecutionStatus.PRECHECK_FAILED, exc.code) from None
    return tuple(records)


def _preflight_store(store: ProviderHoldingsStore, records: Tuple[ProviderHoldingsCoverage, ...]) -> None:
    """凍結 store の公開の読み口だけで、全 record の衝突を最初の append の前に確かめる（§13 ・§17）。"""
    try:
        store.verify_unchanged()
    except HoldingsStoreError as exc:
        raise _Fail(HoldingsExecutionStatus.STORE_FAILURE, exc.code) from None
    for record in records:
        existing = store.get(record.record_id)
        if existing is not None:
            _check(existing == record, HoldingsExecutionStatus.STORE_FAILURE, "HOLDINGS_CONTENT_CONFLICT")
            continue
        same_epoch = [r for r in store.for_slot(record.subject_id, record.period_end)
                      if r.acquisition_ref == record.acquisition_ref]
        _check(not same_epoch, HoldingsExecutionStatus.STORE_FAILURE, "PROVIDER_HOLDINGS_CONFLICT")


def execute_provider_holdings(*, event: Any, manifests: Any, history: Any, store: Any) -> HoldingsExecutionResult:
    """COMPLETE な取得 ＋ manifest ＋ A2 の像 → `ProviderHoldingsCoverage` を凍結 store に append（全体 preflight ・0 or all）。"""
    if not isinstance(history, ObservationHistory):
        return HoldingsExecutionResult(HoldingsExecutionStatus.PRECHECK_FAILED, failure_code="INVALID_HISTORY")
    if not hasattr(manifests, "by_acquisition") or not callable(manifests.by_acquisition):
        return HoldingsExecutionResult(HoldingsExecutionStatus.PRECHECK_FAILED, failure_code="MANIFEST_VIEW_REQUIRED")
    if not isinstance(store, ProviderHoldingsStore) or store.read_only:
        return HoldingsExecutionResult(HoldingsExecutionStatus.PRECHECK_FAILED, failure_code="WRITABLE_STORE_REQUIRED")
    subject_id = acquisition_ref = manifest_ref = ""
    try:
        code = _bind_event(event)
        acquisition_ref = event.reference
        manifest = _bind_manifest(event, code, manifests, history)
        subject_id, manifest_ref = manifest.subject_id, manifest.reference
        counts = _preflight_entries(manifest, history)
        _check(bool(counts), HoldingsExecutionStatus.NO_CANONICAL_PERIODS, "NO_CANONICAL_PERIODS")
        records = _records_for(event, manifest, counts)
        _preflight_store(store, records)
    except _Fail as fail:
        return HoldingsExecutionResult(fail.status, subject_id=subject_id, acquisition_ref=acquisition_ref,
                                       manifest_ref=manifest_ref, failure_code=fail.code)
    appended: List[str] = []
    reused: List[str] = []
    for record in records:                                                       # period_end の昇順 ・preflight 済み
        try:
            outcome = store.append(record)
        except (HoldingsStoreError, OSError) as exc:                             # 後の record が失敗しても書いた分は残る（rollback 無し）
            code = exc.code if isinstance(exc, HoldingsStoreError) else "OS_ERROR"
            return HoldingsExecutionResult(HoldingsExecutionStatus.STORE_FAILURE, subject_id=subject_id,
                                           acquisition_ref=acquisition_ref, manifest_ref=manifest_ref,
                                           eligible_period_count=len(records), appended=tuple(appended),
                                           reused=tuple(reused), failure_code=code)
        (appended if outcome.status.value == "APPENDED" else reused).append(record.record_id)
    if appended and reused:
        status = HoldingsExecutionStatus.MIXED_APPEND_REUSE
    elif appended:
        status = HoldingsExecutionStatus.APPENDED
    else:
        status = HoldingsExecutionStatus.REUSED
    return HoldingsExecutionResult(status, subject_id=subject_id, acquisition_ref=acquisition_ref,
                                   manifest_ref=manifest_ref, eligible_period_count=len(records),
                                   appended=tuple(appended), reused=tuple(reused))


__all__ = ["F1_RULES_VERSION", "GLOBAL_HOLD_RULE", "OUTPUT_ORDER_RULE", "HoldingsExecutionResult",
           "HoldingsExecutionStatus", "execute_provider_holdings"]
