"""P8-A1R — 2 つの時間軸での identity の解決（決定論・派生・非 authority・非永続）。

- 有効時間（世界でその identity の事実が成り立った時刻）と authority の知識の時刻（Phase 8 の authority がそれを知った ／
  受け入れた時刻）を分ける。
- `STRICT_KNOWLEDGE`（既定）: cutoff までに authority が知っていた record と訂正だけで、有効時間 cutoff を解く。訂正が無ければ
  凍結の A1 の解決と同じ。
- `RETROSPECTIVE_AUTHORITY`: 呼び手が明示で選んだ後の authority（`authority_as_of`）の像で、過去の有効時間（`effective_at`）を
  解く。両方の時刻が必須（無ければ fail closed）。結果には遡及の印を付ける。これは「選んだ後の審査済みの authority の像による」
  答えで、過去の事実そのものの主張ではない。
- STRICT から RETROSPECTIVE へ暗黙に切り替えない。「最新」「現在」の既定は無い。coverage は両方の mode で必須。
- 解決は凍結の A1 の resolver を、知識を固定した authority の像に対して使う（有効時間の評価は A1 のまま）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .identity_correction_model import (CorrectionHistory, CorrectionHistoryError, is_authority_version,
                                        record_subjects)
from .identity_correction_store import CorrectionAuthorityMissing, CorrectionStoreCorrupt, open_correction_history
from .identity_model import RecordKind, canonical_json
from .identity_resolver import (DERIVED_NON_AUTHORITY_NON_PERSISTENT, IdentityQuery, IdentityResolution, QueryKind,
                                resolve)
from ..core.time import to_utc_iso

REMEDIATION_RESOLVER_VERSION = "p8_identity_remediation_resolver:0.1.0"


class ResolutionMode(str, Enum):
    STRICT_KNOWLEDGE = "STRICT_KNOWLEDGE"
    RETROSPECTIVE_AUTHORITY = "RETROSPECTIVE_AUTHORITY"


DEFAULT_MODE = ResolutionMode.STRICT_KNOWLEDGE
#: 結果の読み方（事実の主張をしない）
INTERPRETATION = {
    ResolutionMode.STRICT_KNOWLEDGE: "AS_KNOWN_BY_THE_AUTHORITY_AT_THE_CUTOFF",
    ResolutionMode.RETROSPECTIVE_AUTHORITY: "ACCORDING_TO_THE_SELECTED_LATER_REVIEWED_AUTHORITY_VIEW_NOT_A_TRUTH_CLAIM",
}


class RemediationStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    NOT_YET_KNOWN = "NOT_YET_KNOWN"
    NOT_ACTIVE_AT_CUTOFF = "NOT_ACTIVE_AT_CUTOFF"
    AMBIGUOUS = "AMBIGUOUS"
    BEFORE_COVERAGE = "BEFORE_COVERAGE"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"
    AUTHORITY_MISSING = "AUTHORITY_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    CORRECTION_CONFLICT = "CORRECTION_CONFLICT"
    AUTHORITY_VERSION_MISMATCH = "AUTHORITY_VERSION_MISMATCH"


class RemediationRequestError(ValueError):
    """解決の要求の違反（mode ・時刻 ・版の欠落や矛盾）。黙って既定に落とさない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _fail(code: str, detail: str = "") -> None:
    raise RemediationRequestError(code, detail)


def _iso(value: Optional[datetime]) -> str:
    return to_utc_iso(value) if value is not None else ""


@dataclass(frozen=True)
class CorrectionLink:
    """結果に関わる訂正の鎖の 1 つの環（訂正 ・対象 ・置き換え ・審査の出所）。"""

    correction_record_id: str
    action: str
    reason: str
    target_record_id: str
    replacement_record_id: str
    accepted_at: datetime
    reviewer_class: str
    reviewed_at: datetime
    evidence_refs: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {"accepted_at": _iso(self.accepted_at), "action": self.action,
                "correction_record_id": self.correction_record_id, "evidence_refs": list(self.evidence_refs),
                "reason": self.reason, "replacement_record_id": self.replacement_record_id,
                "reviewed_at": _iso(self.reviewed_at), "reviewer_class": self.reviewer_class,
                "target_record_id": self.target_record_id}


@dataclass(frozen=True)
class RemediatedResolution:
    """2 軸の解決の結果（派生・非 authority・非永続）。mode ・有効時間 ・authority_as_of ・版 ・使った record を必ず持つ。"""

    status: RemediationStatus
    mode: ResolutionMode
    query: IdentityQuery
    effective_at: datetime
    authority_as_of: datetime
    authority_version: str = ""
    identity: Optional[IdentityResolution] = None
    correction_record_ids: Tuple[str, ...] = ()
    correction_chain: Tuple[CorrectionLink, ...] = ()
    diagnostic: str = ""
    resolver_version: str = REMEDIATION_RESOLVER_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    @property
    def retrospective(self) -> bool:
        return self.mode is ResolutionMode.RETROSPECTIVE_AUTHORITY

    @property
    def interpretation(self) -> str:
        return INTERPRETATION[self.mode]

    @property
    def authority_record_ids(self) -> Tuple[str, ...]:
        """結果を支える authority の record id（A1 の record と置き換えの claim）と、関わる訂正の id。"""
        ids = set(self.identity.supporting_record_ids) if self.identity is not None else set()
        ids.update(link.correction_record_id for link in self.correction_chain)
        return tuple(sorted(ids))

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_as_of": _iso(self.authority_as_of), "authority_class": self.authority_class,
                "authority_record_ids": list(self.authority_record_ids),
                "authority_version": self.authority_version,
                "correction_chain": [link.as_dict() for link in self.correction_chain],
                "correction_record_ids": list(self.correction_record_ids), "diagnostic": self.diagnostic,
                "effective_at": _iso(self.effective_at),
                "identity": self.identity.as_dict() if self.identity is not None else None,
                "interpretation": self.interpretation, "mode": self.mode.value, "query": self.query.as_dict(),
                "resolver_version": self.resolver_version, "retrospective": self.retrospective,
                "status": self.status.value}

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())


# ---------------------------------------------------------------- 要求の検査


def _checked_time(value: Any, missing_code: str, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        _fail(missing_code, field_name)
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        _fail("NAIVE_DATETIME", field_name)
    return value


def _checked_request(mode: Any, cutoff: Any, effective_at: Any, authority_as_of: Any,
                     expected_authority_version: Any) -> Tuple[datetime, datetime]:
    """(有効時間, authority の知識の cutoff) を返す。mode と引数の組が合わなければ fail closed。"""
    if not isinstance(mode, ResolutionMode):
        _fail("INVALID_MODE", "mode")
    if expected_authority_version is not None and not is_authority_version(expected_authority_version):
        _fail("INVALID_AUTHORITY_VERSION", "expected_authority_version")
    if mode is ResolutionMode.STRICT_KNOWLEDGE:
        if effective_at is not None or authority_as_of is not None:
            _fail("MODE_PARAMETER_MISMATCH", "strict mode takes only a cutoff; retrospective needs its explicit mode")
        instant = _checked_time(cutoff, "CUTOFF_REQUIRED", "cutoff")
        return instant, instant
    if cutoff is not None:
        _fail("MODE_PARAMETER_MISMATCH", "retrospective mode takes effective_at and authority_as_of")
    effective = _checked_time(effective_at, "EFFECTIVE_AT_REQUIRED", "effective_at")
    authority = _checked_time(authority_as_of, "AUTHORITY_AS_OF_REQUIRED", "authority_as_of")
    if authority < effective:
        _fail("RETROSPECTIVE_REQUIRES_LATER_AUTHORITY", "authority_as_of")
    return effective, authority


def _checked_query(query: Any) -> IdentityQuery:
    if not isinstance(query, IdentityQuery):
        _fail("INVALID_QUERY", "query")
    return query


# ---------------------------------------------------------------- 訂正の鎖（結果に関わる環だけ）


def _chain(authority: CorrectionHistory, correction_record_ids: Tuple[str, ...], query: IdentityQuery,
           identity: IdentityResolution) -> Tuple[CorrectionLink, ...]:
    known = authority.known_records()
    subjects = {value for value in (query.security_id, query.issuer_id) if value}
    subjects.update(identity.candidates)
    if identity.security is not None:
        subjects.update((identity.security.security_id, identity.security.issuer_id))
    if identity.issuer is not None:
        subjects.add(identity.issuer.issuer_id)
        subjects.update(s.security_id for s in identity.issuer.securities)
    if query.kind is QueryKind.IDENTIFIER:
        subjects.update(record.security_id for record in known.values()
                        if record.KIND is RecordKind.IDENTIFIER_ASSIGNMENT and record.scheme is query.scheme
                        and record.value == query.value)
    pinned = set(correction_record_ids)
    links = []
    for correction in authority.records:
        if correction.record_id not in pinned:
            continue
        for target, replacement_id in correction.links():
            records = [known[target]] + ([known[replacement_id]] if replacement_id else [])
            touched = set()
            for record in records:
                touched.update(record_subjects(record, known))
            coverage = any(record.KIND is RecordKind.COVERAGE for record in records)
            if coverage or touched & subjects:
                links.append(CorrectionLink(correction.record_id, correction.action.value, correction.reason.value,
                                            target, replacement_id, correction.accepted_at,
                                            correction.review.reviewer_class.value, correction.review.reviewed_at,
                                            tuple(item.source_ref for item in correction.review.evidence)))
    return tuple(links)


# ---------------------------------------------------------------- 解決


def resolve_remediated(authority: CorrectionHistory, query: IdentityQuery, *,
                       mode: ResolutionMode = DEFAULT_MODE, cutoff: Optional[datetime] = None,
                       effective_at: Optional[datetime] = None, authority_as_of: Optional[datetime] = None,
                       expected_authority_version: Optional[str] = None) -> RemediatedResolution:
    """検証済みの authority を、mode が決める 2 つの時刻で解く。入力を変えない。書き込みをしない。"""
    effective, as_of = _checked_request(mode, cutoff, effective_at, authority_as_of, expected_authority_version)
    query = _checked_query(query)
    if not isinstance(authority, CorrectionHistory):
        _fail("INVALID_HISTORY", "authority")
    try:
        pinned = authority.pin(as_of)
    except CorrectionHistoryError as exc:
        return RemediatedResolution(RemediationStatus.CORRECTION_CONFLICT, mode, query, effective, as_of,
                                    diagnostic=f"{exc.code}:{exc.detail}")
    if expected_authority_version is not None and pinned.version != expected_authority_version:
        return RemediatedResolution(RemediationStatus.AUTHORITY_VERSION_MISMATCH, mode, query, effective, as_of,
                                    authority_version=pinned.version, diagnostic="pinned version differs")
    identity = resolve(pinned.view, query, cutoff=effective)
    return RemediatedResolution(RemediationStatus(identity.status.value), mode, query, effective, as_of,
                                authority_version=pinned.version, identity=identity,
                                correction_record_ids=pinned.correction_record_ids,
                                correction_chain=_chain(authority, pinned.correction_record_ids, query, identity))


def resolve_remediated_at_data_root(data_root: Any, query: IdentityQuery, *, mode: ResolutionMode = DEFAULT_MODE,
                                    cutoff: Optional[datetime] = None, effective_at: Optional[datetime] = None,
                                    authority_as_of: Optional[datetime] = None,
                                    expected_authority_version: Optional[str] = None) -> RemediatedResolution:
    """2 つの journal を read-only で読んで解く（何も書かない）。欠落 ／ 破損は status として返す（空の成功にしない）。"""
    effective, as_of = _checked_request(mode, cutoff, effective_at, authority_as_of, expected_authority_version)
    query = _checked_query(query)
    try:
        authority = open_correction_history(data_root)
    except CorrectionAuthorityMissing as exc:
        return RemediatedResolution(RemediationStatus.AUTHORITY_MISSING, mode, query, effective, as_of,
                                    diagnostic=exc.code)
    except CorrectionStoreCorrupt as exc:
        return RemediatedResolution(RemediationStatus.STORE_CORRUPTION, mode, query, effective, as_of,
                                    diagnostic=f"{exc.code}:{exc.detail}:{exc.line_number}")
    return resolve_remediated(authority, query, mode=mode, cutoff=cutoff, effective_at=effective_at,
                              authority_as_of=authority_as_of, expected_authority_version=expected_authority_version)


__all__ = ["CorrectionLink", "DEFAULT_MODE", "INTERPRETATION", "REMEDIATION_RESOLVER_VERSION", "RemediatedResolution",
           "RemediationRequestError", "RemediationStatus", "ResolutionMode", "resolve_remediated",
           "resolve_remediated_at_data_root"]
