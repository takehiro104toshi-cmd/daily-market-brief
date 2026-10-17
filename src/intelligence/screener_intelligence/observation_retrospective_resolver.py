"""P8-A2C ／ P8-A2C-R — RETROSPECTIVE_PROVIDER_AUTHORITY: 取得の軸で、明示の epoch membership（凍結 EPOCH1R の manifest）だけから解く。

2 つの時間軸（R1。監督の決定）:
- STRICT_PIT（凍結 A2 の `resolve`）: 世界 ／ 公開の知識の軸。`ObservationCoverage.complete_through` と観測の `knowledge` で「その時点で
  確かに知り得たか」。本 module は触らない。
- RETROSPECTIVE_PROVIDER_AUTHORITY（本 module の `resolve_retrospective`）: system ／ 取得の軸。「`authority_as_of` までに system が
  保持していた COMPLETE な provider の取得（epoch）のうち最後のものによれば、この slot に何が在ったか」。世界の知識の主張ではない。

P8-A2C-R（監督の決定 C1）: epoch の源は **`ProviderHoldingsCoverage`**（別 journal。`complete_through` を持たない）。A2 の
`ObservationCoverage` は遡及の epoch の選択に使わない（黙って fallback しない）。`ObservationHistory` は canonical の観測の像としてだけ読む。

手順（すべて fail closed ・時計なし ・既定なし ・書かない）:
1. identity: 凍結 A1R の `RETROSPECTIVE_AUTHORITY`（`effective_at = identity_valid_at`、`authority_as_of`）。period_end から推定
   しない。
2. epoch: 主語 ・period_end（＝ data の日。G3: 一致だけ）が合い ・`holdings_as_of <= authority_as_of` の保持 record から `holdings_as_of` が最大。
   同じ瞬間に別の record → AMBIGUOUS。journal の位置 ・現在時刻 ・`complete_through` は使わない。
3. manifest: 保持 record の `acquisition_ref` の manifest がちょうど 1 つで、`manifest_ref` ・主語 ・取得 ・その period_end の CANONICAL の数が
   一致。合わない → fail closed。
4. membership: 期間 ・区分が合う CANONICAL の entry の欄 → 観測 id → A2 の像で検証。同じ鎖の member が複数なら鎖の順で最後。
5. 不在の authority（監督の決定。EPOCH1R の期間 metadata を使う）: manifest 全体に period が None の HELD_SEMANTIC ／ UNSUPPORTED が 1 つでも
   → 取得全体で汚染（非 member の slot は `SEMANTIC_HOLD / UNKNOWN_PERIOD_HELD_ROW_IN_EPOCH`）。period_end が P の HELD_SEMANTIC ／
   UNSUPPORTED（区分は問わない。None も） → P で汚染（`SEMANTIC_HOLD / HELD_ROW_AT_PERIOD`）。canonical の member は汚染があっても FOUND。
   汚染が無く、同じ期間 ・区分の CANONICAL の行に欄が無い → `VALUE_ABSENT / FIELD_NOT_REPORTED_IN_EPOCH`。NOT_REPORTED_ONLY が同じ期間 ・
   区分 → `VALUE_ABSENT / NOT_REPORTED_ROW_AT_PERIOD`（汚染しない）。それ以外だけ `NOT_FOUND`。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple

from .acquisition_manifest_model import AcquisitionManifest, ManifestDisposition
from .identity_model import SourceClass, SubjectKind
from .identity_remediation_resolver import RemediationStatus, ResolutionMode, resolve_remediated
from .identity_resolver import IdentityQuery
from .observation_model import (DATASET_FOR_CLASS, FundamentalActual, ObservationClass, ObservationHistory,
                                ObservationModelError)
from .observation_resolver import ObservationQuery, ObservationResolution, ObservationStatus
from .provider_holdings_model import ProviderHoldingsCoverage, is_holdings_reference

RETROSPECTIVE_RESOLVER_VERSION = "p8_observation_retrospective_resolver:0.2.0"
RESOLUTION_MODE = "RETROSPECTIVE_PROVIDER_AUTHORITY"
STRICT_RESOLUTION_MODE = "STRICT_PIT"
INTERPRETATION = "ACCORDING_TO_PROVIDER_HOLDINGS_AT_AUTHORITY_AS_OF_NOT_A_WORLD_KNOWLEDGE_CLAIM"
#: epoch の id は選んだ `ProviderHoldingsCoverage` の参照（epoch の authority そのもの）。journal の行番号 ・A2 の coverage の id ではない
COVERAGE_EPOCH_ID_RULE = "PROVIDER_HOLDINGS_REFERENCE"
EPOCH_SOURCE = "PROVIDER_HOLDINGS_COVERAGE"
EPOCH_SELECTION_RULE = "GREATEST_HOLDINGS_AS_OF_NOT_AFTER_AUTHORITY_AS_OF"
_IDENTITY_OK = (RemediationStatus.FOUND, RemediationStatus.NOT_ACTIVE_AT_CUTOFF)
_IDENTITY_PASS_THROUGH = {RemediationStatus.AUTHORITY_MISSING: ObservationStatus.AUTHORITY_MISSING,
                          RemediationStatus.STORE_CORRUPTION: ObservationStatus.STORE_CORRUPTION}
_HELD = (ManifestDisposition.HELD_SEMANTIC, ManifestDisposition.UNSUPPORTED)


def _fail(code: str, detail: str = "") -> None:
    raise ObservationModelError(code, detail)


def _aware(value: Any, missing_code: str, name: str) -> datetime:
    if not isinstance(value, datetime):
        _fail(missing_code, name)
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        _fail("NAIVE_DATETIME", name)
    return value


class _Stop(Exception):
    def __init__(self, status: ObservationStatus, diagnostic: str = "", candidates: Tuple[str, ...] = ()) -> None:
        super().__init__(status.value)
        self.status = status
        self.diagnostic = diagnostic
        self.candidates = candidates


def _identity_status(corrections: Any, query: ObservationQuery, identity_valid_at: datetime,
                     authority_as_of: datetime) -> str:
    if query.subject_kind is SubjectKind.SECURITY:
        identity_query = IdentityQuery.for_security(query.subject_id)
    else:
        identity_query = IdentityQuery.for_issuer(query.subject_id)
    result = resolve_remediated(corrections, identity_query, mode=ResolutionMode.RETROSPECTIVE_AUTHORITY,
                                effective_at=identity_valid_at, authority_as_of=authority_as_of)
    if result.status in _IDENTITY_PASS_THROUGH:
        raise _Stop(_IDENTITY_PASS_THROUGH[result.status], result.diagnostic)
    if result.status not in _IDENTITY_OK:
        raise _Stop(ObservationStatus.SUBJECT_NOT_RESOLVED, result.status.value)
    return result.status.value


def _select_epoch(holdings: Any, query: ObservationQuery, authority_as_of: datetime) -> ProviderHoldingsCoverage:
    """主語 ・period_end の保持 record から、`holdings_as_of` が最大で `authority_as_of` 以前のものを選ぶ。"""
    dataset = DATASET_FOR_CLASS[query.observation_class]
    for_subject = tuple(holdings.for_subject(query.subject_id))
    for record in for_subject:                                                   # 像の record は authority の型 ・主語 ・dataset
        if not isinstance(record, ProviderHoldingsCoverage) or record.subject_id != query.subject_id \
                or record.dataset is not dataset:
            raise _Stop(ObservationStatus.MANIFEST_CONFLICT, "PROVIDER_HOLDINGS_CONFLICT")
    covering = [record for record in for_subject if record.covers(query.data_date)]
    if not covering:
        if for_subject and query.data_date < min(record.period_end for record in for_subject):
            raise _Stop(ObservationStatus.BEFORE_COVERAGE, "NO_PROVIDER_HOLDINGS_EPOCH_BEFORE_FIRST")
        raise _Stop(ObservationStatus.OUTSIDE_COVERAGE, "NO_PROVIDER_HOLDINGS_EPOCH")
    eligible = [record for record in covering if record.holdings_as_of <= authority_as_of]
    if not eligible:                                                             # 全部 authority_as_of より後の取得
        raise _Stop(ObservationStatus.NOT_YET_KNOWN, "FUTURE_PROVIDER_HOLDINGS_EPOCH")
    newest = max(record.holdings_as_of for record in eligible)
    selected = sorted((r for r in eligible if r.holdings_as_of == newest), key=lambda r: r.record_id)
    if len(selected) > 1:
        raise _Stop(ObservationStatus.AMBIGUOUS, "AMBIGUOUS_PROVIDER_HOLDINGS_EPOCH",
                    tuple(record.record_id for record in selected))
    return selected[0]


def _manifest_for(epoch: ProviderHoldingsCoverage, manifests: Any, query: ObservationQuery) -> AcquisitionManifest:
    manifest = manifests.by_acquisition(epoch.acquisition_ref)                   # manifest の store が取得の参照の authority
    if manifest is None:
        raise _Stop(ObservationStatus.MANIFEST_MISSING, "NO_MANIFEST_FOR_ACQUISITION")
    if not isinstance(manifest, AcquisitionManifest) or manifest.acquisition_ref != epoch.acquisition_ref:
        raise _Stop(ObservationStatus.MANIFEST_CONFLICT, "MANIFEST_ACQUISITION_MISMATCH")
    if manifest.reference != epoch.manifest_ref:
        raise _Stop(ObservationStatus.MANIFEST_CONFLICT, "PROVIDER_HOLDINGS_CONFLICT")
    if manifest.subject_id != query.subject_id or manifest.subject_id != epoch.subject_id:
        raise _Stop(ObservationStatus.MANIFEST_CONFLICT, "MANIFEST_SUBJECT_MISMATCH")
    canonical_at_period = sum(1 for entry in manifest.entries
                              if entry.disposition is ManifestDisposition.CANONICAL
                              and entry.period is not None and entry.period.period_end == epoch.period_end)
    if canonical_at_period != epoch.canonical_entry_count:
        raise _Stop(ObservationStatus.MEMBERSHIP_INVALID, "CANONICAL_ENTRY_COUNT_MISMATCH")
    return manifest


def _absence_contamination(manifest: AcquisitionManifest, query: ObservationQuery) -> str:
    """P の不在の authority を汚す保留の行（期間不明 → 取得全体、期間 P → その P。区分は問わない）。無ければ空。"""
    held = [entry for entry in manifest.entries if entry.disposition in _HELD]
    if any(entry.period is None for entry in held):
        return "UNKNOWN_PERIOD_HELD_ROW_IN_EPOCH"
    if any(entry.period.period_end == query.data_date for entry in held):
        return "HELD_ROW_AT_PERIOD"
    return ""


def _member_records(manifest: AcquisitionManifest, history: ObservationHistory,
                    query: ObservationQuery) -> Tuple[List[FundamentalActual], bool, bool]:
    """(期間 ・区分が合う CANONICAL の欄の member の観測, canonical の行があるか, 記載なしの行があるか)。"""
    members: List[FundamentalActual] = []
    canonical_slot = not_reported_slot = False
    for entry in manifest.entries:
        if entry.disposition in _HELD:
            continue
        if entry.disposition is ManifestDisposition.NOT_REPORTED_ONLY:
            if entry.period is None or entry.statement_basis is None:          # 凍結の適格の経路では起き得ない → 捏造せず fail closed
                raise _Stop(ObservationStatus.MEMBERSHIP_INVALID, "NOT_REPORTED_ENTRY_WITHOUT_PERIOD_OR_BASIS")
            if entry.period == query.period and entry.statement_basis is query.basis:
                not_reported_slot = True
            continue
        if entry.period != query.period or entry.statement_basis is not query.basis:
            continue
        canonical_slot = True
        for field, observation_id in entry.fields:
            if field is not query.field:
                continue
            record = history.get(observation_id)
            if not isinstance(record, FundamentalActual):
                raise _Stop(ObservationStatus.MEMBERSHIP_INVALID, "OBSERVATION_MISSING", (observation_id,))
            if record.subject != query.subject_id:
                raise _Stop(ObservationStatus.MEMBERSHIP_INVALID, "OBSERVATION_SUBJECT_MISMATCH", (observation_id,))
            if record.field is not query.field:
                raise _Stop(ObservationStatus.MEMBERSHIP_INVALID, "OBSERVATION_FIELD_MISMATCH", (observation_id,))
            if record.provenance.source_class is not SourceClass.JQUANTS \
                    or record.provenance.source_record_ref != entry.provider_record_ref:
                raise _Stop(ObservationStatus.MEMBERSHIP_INVALID, "OBSERVATION_PROVENANCE_MISMATCH",
                            (observation_id,))
            if record.period != query.period or record.statement_basis is not query.basis:
                raise _Stop(ObservationStatus.MEMBERSHIP_INVALID, "OBSERVATION_PERIOD_BASIS_MISMATCH",
                            (observation_id,))
            members.append(record)
    return members, canonical_slot, not_reported_slot


def _head(members: List[FundamentalActual], history: ObservationHistory) -> Tuple[FundamentalActual, Tuple[str, ...]]:
    """同じ鎖の member は鎖の順で最後のもの。鎖（出所）が 2 つ以上なら曖昧。"""
    slots: Dict[str, List[str]] = {}
    for record in members:
        slots.setdefault(record.slot_key, []).append(record.record_id)
    if len(slots) > 1:
        raise _Stop(ObservationStatus.AMBIGUOUS, "AMBIGUOUS_CHAIN", tuple(sorted(r.record_id for r in members)))
    (slot_key, member_ids), = slots.items()
    chain = history.chains.get(slot_key, [])
    lineage = tuple(record.record_id for record in chain if record.record_id in set(member_ids))
    if len(lineage) != len(set(member_ids)):
        raise _Stop(ObservationStatus.MEMBERSHIP_INVALID, "MEMBER_NOT_IN_CHAIN", tuple(sorted(member_ids)))
    return history.get(lineage[-1]), lineage


def resolve_retrospective(history: Any, query: Any, *, authority_as_of: Any, identity_valid_at: Any, manifests: Any,
                          corrections: Any, holdings: Any) -> ObservationResolution:
    """取得の軸で解く。`authority_as_of` ・`identity_valid_at` ・manifest の像 ・A1R の authority ・保持 epoch の像はすべて明示（既定 ・時計なし）。"""
    authority_as_of = _aware(authority_as_of, "AUTHORITY_AS_OF_REQUIRED", "authority_as_of")
    identity_valid_at = _aware(identity_valid_at, "IDENTITY_VALID_AT_REQUIRED", "identity_valid_at")
    if identity_valid_at > authority_as_of:
        _fail("RETROSPECTIVE_REQUIRES_LATER_AUTHORITY", "authority_as_of")
    if not isinstance(query, ObservationQuery):
        _fail("INVALID_QUERY", "query")
    if query.observation_class is not ObservationClass.FUNDAMENTAL_ACTUAL:
        _fail("INVALID_QUERY", "retrospective provider authority covers fundamental actuals only")
    if query.source_class not in (None, SourceClass.JQUANTS):
        _fail("INVALID_QUERY", "source_class")
    if not isinstance(history, ObservationHistory):
        _fail("INVALID_HISTORY", "history")
    if not hasattr(manifests, "by_acquisition") or not callable(manifests.by_acquisition):
        _fail("MANIFEST_VIEW_REQUIRED", "manifests")
    if corrections is None:
        _fail("CORRECTION_AUTHORITY_REQUIRED", "corrections")
    if not hasattr(holdings, "for_subject") or not callable(holdings.for_subject):
        _fail("PROVIDER_HOLDINGS_VIEW_REQUIRED", "holdings")                   # A2 の coverage には fallback しない

    def result(status: ObservationStatus, **extra: Any) -> ObservationResolution:
        return ObservationResolution(status, query, authority_as_of, resolver_version=RETROSPECTIVE_RESOLVER_VERSION,
                                     resolution_mode=RESOLUTION_MODE, authority_as_of=authority_as_of,
                                     interpretation=INTERPRETATION, **extra)

    identity_status = ""
    epoch_ids: Tuple[str, ...] = ()
    epoch_id = ""
    try:
        identity_status = _identity_status(corrections, query, identity_valid_at, authority_as_of)
        epoch = _select_epoch(holdings, query, authority_as_of)
        epoch_ids, epoch_id = (epoch.record_id,), epoch.reference
        manifest = _manifest_for(epoch, manifests, query)
        members, canonical_slot, not_reported_slot = _member_records(manifest, history, query)
        if members:                                                              # canonical の member は汚染があっても答える
            head, lineage = _head(members, history)
            return result(ObservationStatus.FOUND, record=head, lineage=lineage, coverage_record_ids=epoch_ids,
                          coverage_epoch_id=epoch_id, identity_status=identity_status)
        contamination = _absence_contamination(manifest, query)
        if contamination:
            raise _Stop(ObservationStatus.SEMANTIC_HOLD, contamination)
        if canonical_slot:                                                       # 行は在った。この欄は記載なし
            raise _Stop(ObservationStatus.VALUE_ABSENT, "FIELD_NOT_REPORTED_IN_EPOCH")
        if not_reported_slot:                                                    # 行は在った。全欄記載なし
            raise _Stop(ObservationStatus.VALUE_ABSENT, "NOT_REPORTED_ROW_AT_PERIOD")
        return result(ObservationStatus.NOT_FOUND, coverage_record_ids=epoch_ids, coverage_epoch_id=epoch_id,
                      identity_status=identity_status, diagnostic="NO_CANONICAL_MEMBER_FOR_COVERED_SLOT")
    except _Stop as stop:
        if stop.status is ObservationStatus.SUBJECT_NOT_RESOLVED:
            identity_status = stop.diagnostic
        return result(stop.status, candidates=stop.candidates, coverage_record_ids=epoch_ids,
                      coverage_epoch_id=epoch_id, identity_status=identity_status, diagnostic=stop.diagnostic)


def is_retrospective(resolution: Any) -> bool:
    return isinstance(resolution, ObservationResolution) and resolution.resolution_mode == RESOLUTION_MODE \
        and (resolution.coverage_epoch_id == "" or is_holdings_reference(resolution.coverage_epoch_id))


__all__ = ["COVERAGE_EPOCH_ID_RULE", "EPOCH_SELECTION_RULE", "EPOCH_SOURCE", "INTERPRETATION", "RESOLUTION_MODE",
           "RETROSPECTIVE_RESOLVER_VERSION", "STRICT_RESOLUTION_MODE", "is_retrospective", "resolve_retrospective"]
