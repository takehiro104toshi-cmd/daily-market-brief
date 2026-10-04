"""P8-A2C — RETROSPECTIVE_PROVIDER_AUTHORITY: 取得の軸で、明示の epoch membership（凍結 EPOCH1 の manifest）だけから解く。

2 つの時間軸（R1。監督の決定）:
- STRICT_PIT（凍結 A2 の `resolve`）: 世界 ／ 公開の知識の軸。`complete_through` と観測の `knowledge` で「その時点で確かに知り得たか」。
- RETROSPECTIVE_PROVIDER_AUTHORITY（本 module の `resolve_retrospective`）: system ／ 取得の軸。「`authority_as_of` までに system が
  保持していた COMPLETE な provider の取得（epoch）のうち、最後のものによれば、この slot に何が在ったか」。世界の知識の主張ではない。

手順（すべて fail closed ・時計なし ・既定なし ・書かない）:
1. identity: 凍結 A1R の `RETROSPECTIVE_AUTHORITY`（`effective_at = identity_valid_at` ＝ 選んだ epoch の取得の営業日、
   `authority_as_of` ＝ 明示の authority の瞬間）。period_end から過去の identity を推定しない。
2. epoch: dataset ・主語が一致し ・data の日を覆い ・`holdings_as_of` を持ち ・`holdings_as_of <= authority_as_of` の主語つき coverage から
   `holdings_as_of` が最大のものを選ぶ（journal の位置 ・現在時刻は使わない）。dataset 全体の legacy の coverage は遡及の authority ではない。
3. manifest: 選んだ coverage の provenance（`jq.acq:<digest>`）の取得に authoritative な manifest が**ちょうど 1 つ**
   （manifest の store が取得の参照で探す。ACQ0 の層は読まない）。無い ／ 合わない → fail closed。
4. membership: manifest の entry だけが epoch の member。period ・区分が合う CANONICAL の entry の欄 → 観測 id → A2 の像で検証
   （主語 ・欄 ・出所 ・期間 ・区分）。同じ鎖に member が複数なら鎖の順で最後の member（凍結の鎖の規律を member に限る）。
   journal の順 ・知識の時刻 ・現在の A2 の内容から membership を推定しない。
5. 不在の意味: 行は在ったが保留（HELD_SEMANTIC ／ UNSUPPORTED）→ `SEMANTIC_HOLD`。CANONICAL の行は在ったが欄が記載なし →
   `VALUE_ABSENT`。`NOT_FOUND` は「選んだ epoch で covered な slot に一致する canonical の観測が無かった」だけを意味する。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .acquisition_manifest_model import AcquisitionManifest, ManifestDisposition, is_manifest_reference
from .identity_model import SourceClass, SubjectKind
from .identity_remediation_resolver import RemediationStatus, ResolutionMode, resolve_remediated
from .identity_resolver import IdentityQuery
from .observation_model import (DATASET_FOR_CLASS, FundamentalActual, ObservationClass, ObservationCoverage,
                                ObservationHistory, ObservationModelError)
from .observation_resolver import ObservationQuery, ObservationResolution, ObservationStatus

RETROSPECTIVE_RESOLVER_VERSION = "p8_observation_retrospective_resolver:0.1.0"
RESOLUTION_MODE = "RETROSPECTIVE_PROVIDER_AUTHORITY"
STRICT_RESOLUTION_MODE = "STRICT_PIT"
INTERPRETATION = "ACCORDING_TO_PROVIDER_HOLDINGS_AT_AUTHORITY_AS_OF_NOT_A_WORLD_KNOWLEDGE_CLAIM"
#: epoch の id は manifest の参照（membership の authority そのもの）。journal の行番号 ・coverage の位置ではない
COVERAGE_EPOCH_ID_RULE = "ACQUISITION_MANIFEST_REFERENCE"
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


def _select_epoch(history: ObservationHistory, query: ObservationQuery,
                  authority_as_of: datetime) -> ObservationCoverage:
    dataset = DATASET_FOR_CLASS[query.observation_class]
    scoped = [c for c in history.coverages if c.dataset is dataset and c.subject_id == query.subject_id
              and c.holdings_as_of is not None]                              # 主語つき ・取得の瞬間つきだけが epoch
    covering = [c for c in scoped if c.covers(query.data_date)]
    if not covering:
        if scoped and query.data_date < min(c.data_from for c in scoped):
            raise _Stop(ObservationStatus.BEFORE_COVERAGE, "NO_EPOCH_BEFORE_FIRST_COVERAGE")
        raise _Stop(ObservationStatus.OUTSIDE_COVERAGE, "NO_SUBJECT_SCOPED_EPOCH")
    eligible = [c for c in covering if c.holdings_as_of <= authority_as_of]
    if not eligible:                                                             # 全部 authority_as_of より後の取得
        raise _Stop(ObservationStatus.NOT_YET_KNOWN, "EPOCHS_AFTER_AUTHORITY_AS_OF")
    newest = max(c.holdings_as_of for c in eligible)
    selected = sorted((c for c in eligible if c.holdings_as_of == newest), key=lambda c: c.record_id)
    if len(selected) > 1:
        raise _Stop(ObservationStatus.AMBIGUOUS, "AMBIGUOUS_EPOCH", tuple(c.record_id for c in selected))
    return selected[0]


def _manifest_for(epoch: ObservationCoverage, manifests: Any, query: ObservationQuery) -> AcquisitionManifest:
    reference = epoch.provenance.source_record_ref
    if epoch.provenance.source_class is not SourceClass.JQUANTS:
        raise _Stop(ObservationStatus.MANIFEST_MISSING, "EPOCH_NOT_BOUND_TO_ACQUISITION")
    manifest = manifests.by_acquisition(reference)                               # manifest の store が取得の参照の authority
    if manifest is None:
        raise _Stop(ObservationStatus.MANIFEST_MISSING, "NO_MANIFEST_FOR_ACQUISITION")
    if not isinstance(manifest, AcquisitionManifest) or manifest.acquisition_ref != reference:
        raise _Stop(ObservationStatus.MANIFEST_CONFLICT, "MANIFEST_ACQUISITION_MISMATCH")
    if manifest.subject_id != query.subject_id:
        raise _Stop(ObservationStatus.MANIFEST_CONFLICT, "MANIFEST_SUBJECT_MISMATCH")
    return manifest


def _member_records(manifest: AcquisitionManifest, history: ObservationHistory,
                    query: ObservationQuery) -> List[FundamentalActual]:
    """query の期間 ・区分の CANONICAL の entry から、欄の member の観測を A2 の像で検証して集める。"""
    members: List[FundamentalActual] = []
    canonical_slot = False
    held_rows = not_reported_rows = 0
    for entry in manifest.entries:
        if entry.disposition in _HELD:
            held_rows += 1
            continue
        if entry.disposition is ManifestDisposition.NOT_REPORTED_ONLY:
            not_reported_rows += 1
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
    if members:
        return members
    if canonical_slot:                                                           # 行は在った。この欄は記載なし
        raise _Stop(ObservationStatus.VALUE_ABSENT, "FIELD_NOT_REPORTED_IN_EPOCH")
    if held_rows:                                                                # 行は在った（期間は確定できない）が保留
        raise _Stop(ObservationStatus.SEMANTIC_HOLD, "HELD_ROWS_IN_EPOCH_WITHOUT_CANONICAL_SLOT")
    if not_reported_rows:                                                        # 行は在った（期間は確定できない）が全欄記載なし
        raise _Stop(ObservationStatus.VALUE_ABSENT, "NOT_REPORTED_ROWS_IN_EPOCH_WITHOUT_CANONICAL_SLOT")
    return members


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
                          corrections: Any) -> ObservationResolution:
    """取得の軸で解く。`authority_as_of` ・`identity_valid_at` ・manifest の像 ・A1R の authority はすべて明示（既定 ・時計なし）。"""
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

    def result(status: ObservationStatus, **extra: Any) -> ObservationResolution:
        return ObservationResolution(status, query, authority_as_of, resolver_version=RETROSPECTIVE_RESOLVER_VERSION,
                                     resolution_mode=RESOLUTION_MODE, authority_as_of=authority_as_of,
                                     interpretation=INTERPRETATION, **extra)

    identity_status = ""
    epoch_ids: Tuple[str, ...] = ()
    epoch_id = ""
    try:
        identity_status = _identity_status(corrections, query, identity_valid_at, authority_as_of)
        epoch = _select_epoch(history, query, authority_as_of)
        epoch_ids = (epoch.record_id,)
        manifest = _manifest_for(epoch, manifests, query)
        epoch_id = manifest.reference
        members = _member_records(manifest, history, query)
        if not members:
            return result(ObservationStatus.NOT_FOUND, coverage_record_ids=epoch_ids, coverage_epoch_id=epoch_id,
                          identity_status=identity_status, diagnostic="NO_CANONICAL_MEMBER_FOR_COVERED_SLOT")
        head, lineage = _head(members, history)
    except _Stop as stop:
        if stop.status is ObservationStatus.SUBJECT_NOT_RESOLVED:
            identity_status = stop.diagnostic
        return result(stop.status, candidates=stop.candidates, coverage_record_ids=epoch_ids,
                      coverage_epoch_id=epoch_id, identity_status=identity_status, diagnostic=stop.diagnostic)
    return result(ObservationStatus.FOUND, record=head, lineage=lineage, coverage_record_ids=epoch_ids,
                  coverage_epoch_id=epoch_id, identity_status=identity_status)


def is_retrospective(resolution: Any) -> bool:
    return isinstance(resolution, ObservationResolution) and resolution.resolution_mode == RESOLUTION_MODE \
        and (resolution.coverage_epoch_id == "" or is_manifest_reference(resolution.coverage_epoch_id))


__all__ = ["COVERAGE_EPOCH_ID_RULE", "EPOCH_SELECTION_RULE", "INTERPRETATION", "RESOLUTION_MODE",
           "RETROSPECTIVE_RESOLVER_VERSION", "STRICT_RESOLUTION_MODE", "is_retrospective", "resolve_retrospective"]
