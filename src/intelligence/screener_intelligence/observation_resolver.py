"""P8-A2 — 観測の PIT の解決（決定論 ・派生 ・非 authority ・非永続）。

caller が与えた aware な `cutoff` で、明示の主語 ・欄 ・基準 ・日 ／ 期間について、その時点で**確かに知り得た** record だけを使う。
「最新」「現在」の既定は無い。解決は record にならない（store は観測の record 以外を受け付けない）。

手順（すべて fail closed）:
1. 主語を A1 で PIT に解決する（A1 の resolver だけを使う。A1 に書かない）。市場の観測はその取引日に上場していること、
   財務は Issuer ／ Security がその時点で識別できること。できなければ `SUBJECT_NOT_RESOLVED`。
2. coverage: data の日（取引日 ／ 期間の末日）を覆い、`complete_through >= cutoff` の宣言が要る。範囲の外は
   `BEFORE_COVERAGE` ／ `OUTSIDE_COVERAGE`、取り込みが cutoff に届いていなければ `NOT_YET_KNOWN`。
3. slot の鎖ごとに、cutoff で確かに知られた最後の record を選ぶ。その次の record の知識が cutoff を跨ぐ（日付だけの知識）
   なら `INSUFFICIENT_TIME_PRECISION`（日付だけの知識に時刻を作らない）。出所の違う鎖が 2 つ以上あれば `AMBIGUOUS`
   （caller が出所を明示すれば 1 つに絞れる）。

値が無い状態（MISSING ／ NOT_REPORTED ／ NOT_APPLICABLE）は `FOUND` の record の値の状態として返り、0 にならない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .identity_resolver import IdentityQuery, ResolutionStatus, resolve as resolve_identity
from .identity_model import SourceClass, SubjectKind, canonical_json, is_issuer_id, is_security_id
from .observation_model import (DATASET_FOR_CLASS, FORECAST_FIELDS, FUNDAMENTAL_SUBJECT, FundamentalField,
                                KnowledgeState, MarketField, ObservationClass, ObservationHistory,
                                ObservationModelError, PriceBasis, ReportingPeriod, StatementBasis, day_start,
                                fundamental_slot_fields, market_slot_fields, slot_key_for)
from .observation_store import ObservationAuthorityMissing, ObservationStoreCorrupt, open_observation_history
from ..core.time import to_utc_iso

RESOLVER_VERSION = "p8_observation_resolver:0.1.0"
#: 解決の authority の種類（契約 §2。authority の record ではない）
DERIVED_NON_AUTHORITY_NON_PERSISTENT = "DERIVED_NON_AUTHORITY_NON_PERSISTENT"


class ObservationStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    NOT_YET_KNOWN = "NOT_YET_KNOWN"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_TIME_PRECISION = "INSUFFICIENT_TIME_PRECISION"
    BEFORE_COVERAGE = "BEFORE_COVERAGE"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"
    AUTHORITY_MISSING = "AUTHORITY_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"
    SUBJECT_NOT_RESOLVED = "SUBJECT_NOT_RESOLVED"


def _fail(code: str, detail: str = "") -> None:
    raise ObservationModelError(code, detail)


@dataclass(frozen=True, kw_only=True)
class ObservationQuery:
    """問い合わせ（class ・主語 ・欄 ・基準 ・日 ／ 期間はすべて明示。出所は任意の絞り込み）。"""

    observation_class: ObservationClass
    subject_id: str
    field: Any
    basis: Any
    session_date: Optional[date] = None
    period: Optional[ReportingPeriod] = None
    source_class: Optional[SourceClass] = None

    def __post_init__(self) -> None:
        if not isinstance(self.observation_class, ObservationClass):
            _fail("INVALID_QUERY", "observation_class")
        if self.source_class is not None and not isinstance(self.source_class, SourceClass):
            _fail("INVALID_QUERY", "source_class")
        if self.observation_class is ObservationClass.MARKET_OBSERVATION:
            if not (is_security_id(self.subject_id) and isinstance(self.field, MarketField)
                    and isinstance(self.basis, PriceBasis) and type(self.session_date) is date and self.period is None):
                _fail("INVALID_QUERY", "market")
            return
        if not (isinstance(self.field, FundamentalField) and isinstance(self.basis, StatementBasis)
                and isinstance(self.period, ReportingPeriod) and self.session_date is None):
            _fail("INVALID_QUERY", "fundamental")
        if self.observation_class is ObservationClass.FUNDAMENTAL_FORECAST:
            if self.field not in FORECAST_FIELDS or not is_issuer_id(self.subject_id):
                _fail("INVALID_QUERY", "forecast")
            return
        check = is_security_id if FUNDAMENTAL_SUBJECT[self.field] is SubjectKind.SECURITY else is_issuer_id
        if not check(self.subject_id):
            _fail("INVALID_QUERY", "actual")

    @classmethod
    def market(cls, security_id: str, field: MarketField, basis: PriceBasis, session_date: date, *,
               source_class: Optional[SourceClass] = None) -> "ObservationQuery":
        return cls(observation_class=ObservationClass.MARKET_OBSERVATION, subject_id=security_id, field=field,
                   basis=basis, session_date=session_date, source_class=source_class)

    @classmethod
    def actual(cls, subject_id: str, field: FundamentalField, basis: StatementBasis, period: ReportingPeriod, *,
               source_class: Optional[SourceClass] = None) -> "ObservationQuery":
        return cls(observation_class=ObservationClass.FUNDAMENTAL_ACTUAL, subject_id=subject_id, field=field,
                   basis=basis, period=period, source_class=source_class)

    @classmethod
    def forecast(cls, issuer_id: str, field: FundamentalField, basis: StatementBasis, period: ReportingPeriod, *,
                 source_class: Optional[SourceClass] = None) -> "ObservationQuery":
        return cls(observation_class=ObservationClass.FUNDAMENTAL_FORECAST, subject_id=issuer_id, field=field,
                   basis=basis, period=period, source_class=source_class)

    @property
    def subject_kind(self) -> SubjectKind:
        if self.observation_class is ObservationClass.FUNDAMENTAL_ACTUAL:
            return FUNDAMENTAL_SUBJECT[self.field]
        return SubjectKind.SECURITY if self.observation_class is ObservationClass.MARKET_OBSERVATION \
            else SubjectKind.ISSUER

    @property
    def data_date(self) -> date:
        return self.session_date if self.session_date is not None else self.period.period_end

    def slot_fields(self) -> Dict[str, Any]:
        if self.observation_class is ObservationClass.MARKET_OBSERVATION:
            return market_slot_fields(self.subject_id, self.field, self.basis, self.session_date)
        return fundamental_slot_fields(self.observation_class, self.subject_id, self.field, self.basis, self.period)

    def as_dict(self) -> Dict[str, Any]:
        return {"basis": self.basis.value, "class": self.observation_class.value, "field": self.field.value,
                "period": self.period.as_dict() if self.period else None,
                "session_date": self.session_date.isoformat() if self.session_date else None,
                "source_class": self.source_class.value if self.source_class else None,
                "subject_id": self.subject_id}


@dataclass(frozen=True)
class ObservationResolution:
    """解決の結果（派生 ・非 authority ・非永続）。record ではなく、store に書けない。"""

    status: ObservationStatus
    query: ObservationQuery
    cutoff: datetime
    record: Optional[Any] = None
    lineage: Tuple[str, ...] = ()
    candidates: Tuple[str, ...] = ()
    coverage_record_ids: Tuple[str, ...] = ()
    identity_status: str = ""
    diagnostic: str = ""
    resolver_version: str = RESOLVER_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "candidates": list(self.candidates),
                "coverage_record_ids": list(self.coverage_record_ids), "cutoff": to_utc_iso(self.cutoff),
                "diagnostic": self.diagnostic, "identity_status": self.identity_status,
                "lineage": list(self.lineage), "query": self.query.as_dict(),
                "record": self.record.as_dict() if self.record is not None else None,
                "resolver_version": self.resolver_version, "status": self.status.value}

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())


# ---------------------------------------------------------------- 解決（純）


def _checked_cutoff(cutoff: Any) -> datetime:
    if not isinstance(cutoff, datetime):
        _fail("CUTOFF_REQUIRED", "an explicit aware cutoff is required (no latest / current default)")
    if cutoff.tzinfo is None or cutoff.tzinfo.utcoffset(cutoff) is None:
        _fail("NAIVE_DATETIME", "cutoff")
    return cutoff


def _checked_query(query: Any) -> ObservationQuery:
    if not isinstance(query, ObservationQuery):
        _fail("INVALID_QUERY", "query")
    return query


def _subject_status(history: ObservationHistory, query: ObservationQuery, cutoff: datetime) -> Tuple[bool, str]:
    """A1 で主語を PIT に解決する。市場の観測はその取引日に上場していなければならない。"""
    if query.subject_kind is SubjectKind.SECURITY:
        identity_query = IdentityQuery.for_security(query.subject_id)
    else:
        identity_query = IdentityQuery.for_issuer(query.subject_id)
    if query.observation_class is ObservationClass.MARKET_OBSERVATION:
        session_end = day_start(query.session_date + timedelta(days=1))
        result = resolve_identity(history.identity, identity_query, cutoff=min(cutoff, session_end))
        return result.status is ResolutionStatus.FOUND, result.status.value
    result = resolve_identity(history.identity, identity_query, cutoff=cutoff)
    ok = result.status in (ResolutionStatus.FOUND, ResolutionStatus.NOT_ACTIVE_AT_CUTOFF)
    return ok, result.status.value


def _coverage(history: ObservationHistory, query: ObservationQuery,
              cutoff: datetime) -> Tuple[Optional[ObservationStatus], Tuple[str, ...]]:
    dataset = DATASET_FOR_CLASS[query.observation_class]
    coverages = [c for c in history.coverages if c.dataset is dataset]
    covering = [c for c in coverages if c.covers(query.data_date)]
    if not covering:
        if coverages and query.data_date < min(c.data_from for c in coverages):
            return ObservationStatus.BEFORE_COVERAGE, ()
        return ObservationStatus.OUTSIDE_COVERAGE, ()
    complete = tuple(sorted(c.record_id for c in covering if c.complete_through >= cutoff))
    if not complete:
        return ObservationStatus.NOT_YET_KNOWN, ()
    return None, complete


def _chain_head(chain: List[Any], cutoff: datetime) -> Tuple[Optional[int], bool]:
    """(cutoff で確かに知られた最後の index, その次が不確か)。鎖の知識の最初の瞬間は非減少。"""
    head: Optional[int] = None
    for index, record in enumerate(chain):
        if record.knowledge.state_at(cutoff) is KnowledgeState.KNOWN:
            head = index
    following = 0 if head is None else head + 1
    uncertain = following < len(chain) and chain[following].knowledge.state_at(cutoff) is KnowledgeState.UNCERTAIN
    return head, uncertain


def resolve(history: ObservationHistory, query: ObservationQuery, *, cutoff: datetime) -> ObservationResolution:
    """`history`（検証済み）を cutoff で解決する。入力を変えない。書き込みをしない。"""
    cutoff = _checked_cutoff(cutoff)
    query = _checked_query(query)
    if not isinstance(history, ObservationHistory):
        _fail("INVALID_HISTORY", "history")
    subject_ok, identity_status = _subject_status(history, query, cutoff)
    if not subject_ok:
        return ObservationResolution(ObservationStatus.SUBJECT_NOT_RESOLVED, query, cutoff,
                                     identity_status=identity_status)
    blocked, coverage_ids = _coverage(history, query, cutoff)
    if blocked is not None:
        return ObservationResolution(blocked, query, cutoff, identity_status=identity_status)
    sources = [query.source_class] if query.source_class is not None else list(SourceClass)
    heads, uncertain = [], False
    for source in sources:
        chain = history.chains.get(slot_key_for(query.slot_fields(), source), [])
        head, unsure = _chain_head(chain, cutoff)
        uncertain = uncertain or unsure
        if head is not None:
            heads.append((chain, head))
    if uncertain:
        return ObservationResolution(ObservationStatus.INSUFFICIENT_TIME_PRECISION, query, cutoff,
                                     coverage_record_ids=coverage_ids, identity_status=identity_status)
    if not heads:
        return ObservationResolution(ObservationStatus.NOT_FOUND, query, cutoff, coverage_record_ids=coverage_ids,
                                     identity_status=identity_status)
    if len(heads) > 1:
        return ObservationResolution(ObservationStatus.AMBIGUOUS, query, cutoff,
                                     candidates=tuple(sorted(chain[head].record_id for chain, head in heads)),
                                     coverage_record_ids=coverage_ids, identity_status=identity_status)
    chain, head = heads[0]
    return ObservationResolution(ObservationStatus.FOUND, query, cutoff, record=chain[head],
                                 lineage=tuple(r.record_id for r in chain[:head + 1]),
                                 coverage_record_ids=coverage_ids, identity_status=identity_status)


def resolve_at_data_root(data_root: Any, query: ObservationQuery, *, cutoff: datetime) -> ObservationResolution:
    """store を read-only で読んで解決する（観測にも A1 にも何も書かない）。欠落 ／ 破損は status にする。"""
    cutoff = _checked_cutoff(cutoff)
    query = _checked_query(query)
    try:
        history = open_observation_history(data_root)
    except ObservationAuthorityMissing as exc:
        return ObservationResolution(ObservationStatus.AUTHORITY_MISSING, query, cutoff, diagnostic=exc.code)
    except ObservationStoreCorrupt as exc:
        return ObservationResolution(ObservationStatus.STORE_CORRUPTION, query, cutoff,
                                     diagnostic=f"{exc.code}:{exc.detail}:{exc.line_number}")
    return resolve(history, query, cutoff=cutoff)


__all__ = ["DERIVED_NON_AUTHORITY_NON_PERSISTENT", "ObservationQuery", "ObservationResolution", "ObservationStatus",
           "RESOLVER_VERSION", "resolve", "resolve_at_data_root"]
