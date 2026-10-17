"""P8-A1 — identity の PIT 解決（決定論・派生・非 authority・非永続）。

caller が与えた aware な `cutoff` で、`known_at <= cutoff` の record だけを使い、有効時間 `cutoff` の状態を返す。
「最新」「現在」の既定は無い。解決の結果は record にならない（store は identity の record 以外を受け付けない）。

- 有効時間 `cutoff` を覆う authority の coverage が無ければ fail closed（BEFORE_COVERAGE ／ OUTSIDE_COVERAGE ／
  NOT_YET_KNOWN）。一致する identity が無いこと（NOT_FOUND）と区別する。
- Issuer → Security は明示の集合で返す。1 つを要する問い合わせは、明示の基準（issue class）で 1 つに決まらなければ
  AMBIGUOUS（黙って選ばない）。
- 上場の終わった Security は識別できるまま、NOT_ACTIVE_AT_CUTOFF として返す（identity を消さない）。
- 名前で探さない（あいまい一致なし）。code は明示の scheme と完全一致だけ。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .identity_model import (IDENTIFIER_PATTERNS, IdentifierScheme, IdentityHistory, IdentityModelError, IssueClass,
                             canonical_json, is_issuer_id, is_security_id)
from .identity_store import IdentityAuthorityMissing, IdentityStoreCorrupt, open_identity_history
from ..core.time import to_utc_iso

RESOLVER_VERSION = "p8_identity_resolver:0.1.0"
#: 解決の authority の種類（契約 §16。authority の record ではない）
DERIVED_NON_AUTHORITY_NON_PERSISTENT = "DERIVED_NON_AUTHORITY_NON_PERSISTENT"


class ResolutionStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    NOT_YET_KNOWN = "NOT_YET_KNOWN"
    NOT_ACTIVE_AT_CUTOFF = "NOT_ACTIVE_AT_CUTOFF"
    AMBIGUOUS = "AMBIGUOUS"
    BEFORE_COVERAGE = "BEFORE_COVERAGE"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"
    AUTHORITY_MISSING = "AUTHORITY_MISSING"
    STORE_CORRUPTION = "STORE_CORRUPTION"


class QueryKind(str, Enum):
    SECURITY = "SECURITY"
    ISSUER = "ISSUER"
    IDENTIFIER = "IDENTIFIER"
    ISSUER_SECURITY = "ISSUER_SECURITY"


def _fail(code: str, detail: str = "") -> None:
    raise IdentityModelError(code, detail)


@dataclass(frozen=True, kw_only=True)
class IdentityQuery:
    """問い合わせ（種類ごとに必要な field だけを持つ。名前での検索は無い）。"""

    kind: QueryKind
    security_id: str = ""
    issuer_id: str = ""
    scheme: Optional[IdentifierScheme] = None
    value: str = ""
    issue_class: Optional[IssueClass] = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, QueryKind):
            _fail("INVALID_VOCABULARY", "kind")
        needed = {QueryKind.SECURITY: {"security_id"}, QueryKind.ISSUER: {"issuer_id"},
                  QueryKind.IDENTIFIER: {"scheme", "value"},
                  QueryKind.ISSUER_SECURITY: {"issuer_id", "issue_class"}}[self.kind]
        present = {name for name in ("security_id", "issuer_id", "scheme", "value", "issue_class")
                   if _query_field(self, name) not in ("", None)}
        if present != needed:
            _fail("INVALID_QUERY", self.kind.value)
        if "security_id" in needed and not is_security_id(self.security_id):
            _fail("INVALID_ID", "security_id")
        if "issuer_id" in needed and not is_issuer_id(self.issuer_id):
            _fail("INVALID_ID", "issuer_id")
        if "scheme" in needed and (not isinstance(self.scheme, IdentifierScheme) or not isinstance(self.value, str)
                                   or not IDENTIFIER_PATTERNS[self.scheme].match(self.value)):
            _fail("INVALID_QUERY", "scheme")
        if "issue_class" in needed and not isinstance(self.issue_class, IssueClass):
            _fail("INVALID_QUERY", "issue_class")

    @classmethod
    def for_security(cls, security_id: str) -> "IdentityQuery":
        return cls(kind=QueryKind.SECURITY, security_id=security_id)

    @classmethod
    def for_issuer(cls, issuer_id: str) -> "IdentityQuery":
        return cls(kind=QueryKind.ISSUER, issuer_id=issuer_id)

    @classmethod
    def for_identifier(cls, scheme: IdentifierScheme, value: str) -> "IdentityQuery":
        return cls(kind=QueryKind.IDENTIFIER, scheme=scheme, value=value)

    @classmethod
    def for_issuer_security(cls, issuer_id: str, issue_class: IssueClass) -> "IdentityQuery":
        return cls(kind=QueryKind.ISSUER_SECURITY, issuer_id=issuer_id, issue_class=issue_class)

    def as_dict(self) -> Dict[str, Any]:
        return {"issue_class": self.issue_class.value if self.issue_class else "", "issuer_id": self.issuer_id,
                "kind": self.kind.value, "scheme": self.scheme.value if self.scheme else "",
                "security_id": self.security_id, "value": self.value}


def _query_field(query: IdentityQuery, name: str) -> Any:
    return {"security_id": query.security_id, "issuer_id": query.issuer_id, "scheme": query.scheme,
            "value": query.value, "issue_class": query.issue_class}[name]


def _iso(value: Optional[datetime]) -> str:
    return to_utc_iso(value) if value is not None else ""


@dataclass(frozen=True)
class IdentifierView:
    scheme: IdentifierScheme
    value: str
    effective_from: datetime
    effective_to: Optional[datetime]
    assignment_record_id: str
    retirement_record_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {"assignment_record_id": self.assignment_record_id, "effective_from": _iso(self.effective_from),
                "effective_to": _iso(self.effective_to), "retirement_record_id": self.retirement_record_id,
                "scheme": self.scheme.value, "value": self.value}


@dataclass(frozen=True)
class NameView:
    name_kind: str
    language: str
    value: str
    effective_from: datetime
    record_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {"effective_from": _iso(self.effective_from), "language": self.language, "name_kind": self.name_kind,
                "record_id": self.record_id, "value": self.value}


@dataclass(frozen=True)
class ListingView:
    venue: str
    effective_from: datetime
    effective_to: Optional[datetime]
    listing_record_id: str
    end_record_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {"effective_from": _iso(self.effective_from), "effective_to": _iso(self.effective_to),
                "end_record_id": self.end_record_id, "listing_record_id": self.listing_record_id, "venue": self.venue}


@dataclass(frozen=True)
class SecurityView:
    security_id: str
    issuer_id: str
    issue_class: IssueClass
    active: bool
    listing: Optional[ListingView]
    identifiers: Tuple[IdentifierView, ...]
    names: Tuple[NameView, ...]
    registration_record_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {"active": self.active, "identifiers": [i.as_dict() for i in self.identifiers],
                "issue_class": self.issue_class.value, "issuer_id": self.issuer_id,
                "listing": self.listing.as_dict() if self.listing else None, "names": [n.as_dict() for n in self.names],
                "registration_record_id": self.registration_record_id, "security_id": self.security_id}

    def record_ids(self) -> Tuple[str, ...]:
        ids = [self.registration_record_id, *(n.record_id for n in self.names)]
        for identifier in self.identifiers:
            ids += [identifier.assignment_record_id, identifier.retirement_record_id]
        if self.listing:
            ids += [self.listing.listing_record_id, self.listing.end_record_id]
        return tuple(i for i in ids if i)


@dataclass(frozen=True)
class IssuerView:
    issuer_id: str
    names: Tuple[NameView, ...]
    securities: Tuple[SecurityView, ...]
    registration_record_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {"issuer_id": self.issuer_id, "names": [n.as_dict() for n in self.names],
                "registration_record_id": self.registration_record_id,
                "securities": [s.as_dict() for s in self.securities]}

    def record_ids(self) -> Tuple[str, ...]:
        ids = [self.registration_record_id, *(n.record_id for n in self.names)]
        for security in self.securities:
            ids += list(security.record_ids())
        return tuple(ids)


@dataclass(frozen=True)
class IdentityResolution:
    """解決の結果（派生・非 authority・非永続）。record ではなく、store に書けない。"""

    status: ResolutionStatus
    query: IdentityQuery
    cutoff: datetime
    security: Optional[SecurityView] = None
    issuer: Optional[IssuerView] = None
    candidates: Tuple[str, ...] = ()
    coverage_record_ids: Tuple[str, ...] = ()
    diagnostic: str = ""
    resolver_version: str = RESOLVER_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    @property
    def supporting_record_ids(self) -> Tuple[str, ...]:
        ids = set(self.coverage_record_ids)
        if self.security:
            ids.update(self.security.record_ids())
        if self.issuer:
            ids.update(self.issuer.record_ids())
        return tuple(sorted(ids))

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "candidates": list(self.candidates),
                "coverage_record_ids": list(self.coverage_record_ids), "cutoff": _iso(self.cutoff),
                "diagnostic": self.diagnostic, "issuer": self.issuer.as_dict() if self.issuer else None,
                "query": self.query.as_dict(), "resolver_version": self.resolver_version,
                "security": self.security.as_dict() if self.security else None, "status": self.status.value,
                "supporting_record_ids": list(self.supporting_record_ids)}

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())


# ---------------------------------------------------------------- 解決（純）


def _checked_cutoff(cutoff: Any) -> datetime:
    if not isinstance(cutoff, datetime):
        _fail("CUTOFF_REQUIRED", "an explicit aware cutoff is required (no latest / current default)")
    if cutoff.tzinfo is None or cutoff.tzinfo.utcoffset(cutoff) is None:
        _fail("NAIVE_DATETIME", "cutoff")
    return cutoff


def _checked_query(query: Any) -> IdentityQuery:
    if not isinstance(query, IdentityQuery):
        _fail("INVALID_QUERY", "query")
    return query


def _coverage_status(visible: IdentityHistory, cutoff: datetime) -> Tuple[Optional[ResolutionStatus], Tuple[str, ...]]:
    coverages = visible.coverages
    covering = tuple(sorted(c.record_id for c in coverages if c.covers(cutoff)))
    if covering:
        return None, covering
    if not coverages:
        return ResolutionStatus.NOT_YET_KNOWN, ()
    if cutoff < min(c.effective_from for c in coverages):
        return ResolutionStatus.BEFORE_COVERAGE, ()
    if cutoff >= max(c.effective_to for c in coverages):
        return ResolutionStatus.NOT_YET_KNOWN, ()
    return ResolutionStatus.OUTSIDE_COVERAGE, ()


def _names(visible: IdentityHistory, subject_id: str, cutoff: datetime) -> Tuple[NameView, ...]:
    """(名前の種類, 言語) ごとに、cutoff までに有効になった最後の名前（同じ時刻なら record id の小さい方。値は同じ）。"""
    chosen: Dict[Tuple[str, str], Any] = {}
    for record in visible.names:
        if record.subject_id != subject_id or record.effective_from > cutoff:
            continue
        key = (record.name_kind.value, record.language.value)
        current = chosen.get(key)
        if current is None or record.effective_from > current.effective_from or (
                record.effective_from == current.effective_from and record.record_id < current.record_id):
            chosen[key] = record
    return tuple(NameView(k[0], k[1], r.value, r.effective_from, r.record_id) for k, r in sorted(chosen.items()))


def _identifiers(visible: IdentityHistory, security_id: str, cutoff: datetime) -> Tuple[IdentifierView, ...]:
    views = []
    for rid, record in visible.assignments.items():
        if record.security_id != security_id or record.effective_from > cutoff:
            continue
        retirement = visible.retirements.get(rid)
        if retirement is not None and retirement.effective_to <= cutoff:
            continue
        views.append(IdentifierView(record.scheme, record.value, record.effective_from,
                                    retirement.effective_to if retirement else None, rid,
                                    retirement.record_id if retirement else ""))
    return tuple(sorted(views, key=lambda v: (v.scheme.value, v.value, v.assignment_record_id)))


def _listing(visible: IdentityHistory, security_id: str, cutoff: datetime) -> Tuple[Optional[ListingView], bool]:
    started = [(record.effective_from, rid, record) for rid, record in visible.listings.items()
               if record.security_id == security_id and record.effective_from <= cutoff]
    if not started:
        return None, False
    _, rid, record = max(started, key=lambda item: (item[0], item[1]))
    end = visible.listing_ends.get(rid)
    view = ListingView(record.venue.value, record.effective_from, end.effective_to if end else None, rid,
                       end.record_id if end else "")
    return view, end is None or cutoff < end.effective_to


def _security_view(visible: IdentityHistory, security_id: str, cutoff: datetime) -> SecurityView:
    registration = visible.securities[security_id]
    listing, active = _listing(visible, security_id, cutoff)
    return SecurityView(security_id, registration.issuer_id, registration.issue_class, active, listing,
                        _identifiers(visible, security_id, cutoff), _names(visible, security_id, cutoff),
                        registration.record_id)


def _issuer_view(visible: IdentityHistory, issuer_id: str, cutoff: datetime) -> IssuerView:
    securities = tuple(_security_view(visible, sid, cutoff) for sid in sorted(visible.securities)
                       if visible.securities[sid].issuer_id == issuer_id)
    return IssuerView(issuer_id, _names(visible, issuer_id, cutoff), securities,
                      visible.issuers[issuer_id].record_id)


def resolve(history: IdentityHistory, query: IdentityQuery, *, cutoff: datetime) -> IdentityResolution:
    """`history`（検証済み）を cutoff で解決する。入力を変えない。書き込みをしない。"""
    cutoff = _checked_cutoff(cutoff)
    query = _checked_query(query)
    if not isinstance(history, IdentityHistory):
        _fail("INVALID_HISTORY", "history")
    visible = history.known_by(cutoff)
    blocked, coverage_ids = _coverage_status(visible, cutoff)
    if blocked is not None:
        return IdentityResolution(blocked, query, cutoff)
    found = ResolutionStatus.FOUND
    inactive = ResolutionStatus.NOT_ACTIVE_AT_CUTOFF
    if query.kind is QueryKind.SECURITY:
        if query.security_id not in visible.securities:
            return IdentityResolution(ResolutionStatus.NOT_FOUND, query, cutoff, coverage_record_ids=coverage_ids)
        view = _security_view(visible, query.security_id, cutoff)
        return IdentityResolution(found if view.active else inactive, query, cutoff, security=view,
                                  coverage_record_ids=coverage_ids)
    if query.kind is QueryKind.IDENTIFIER:
        matches = sorted({record.security_id for rid, record in visible.assignments.items()
                          if record.scheme is query.scheme and record.value == query.value
                          and record.effective_from <= cutoff
                          and not (rid in visible.retirements and visible.retirements[rid].effective_to <= cutoff)})
        if not matches:
            return IdentityResolution(ResolutionStatus.NOT_FOUND, query, cutoff, coverage_record_ids=coverage_ids)
        if len(matches) > 1:
            return IdentityResolution(ResolutionStatus.AMBIGUOUS, query, cutoff, candidates=tuple(matches),
                                      coverage_record_ids=coverage_ids)
        view = _security_view(visible, matches[0], cutoff)
        return IdentityResolution(found if view.active else inactive, query, cutoff, security=view,
                                  coverage_record_ids=coverage_ids)
    if query.issuer_id not in visible.issuers:
        return IdentityResolution(ResolutionStatus.NOT_FOUND, query, cutoff, coverage_record_ids=coverage_ids)
    issuer = _issuer_view(visible, query.issuer_id, cutoff)
    if query.kind is QueryKind.ISSUER:
        status = found if any(s.active for s in issuer.securities) else inactive
        return IdentityResolution(status, query, cutoff, issuer=issuer, coverage_record_ids=coverage_ids)
    matching = [s for s in issuer.securities if s.issue_class is query.issue_class]
    active = [s for s in matching if s.active]
    if len(active) == 1:
        return IdentityResolution(found, query, cutoff, security=active[0], issuer=issuer,
                                  coverage_record_ids=coverage_ids)
    if len(active) > 1:
        return IdentityResolution(ResolutionStatus.AMBIGUOUS, query, cutoff, issuer=issuer,
                                  candidates=tuple(s.security_id for s in active), coverage_record_ids=coverage_ids)
    status = inactive if matching else ResolutionStatus.NOT_FOUND
    return IdentityResolution(status, query, cutoff, issuer=issuer, candidates=tuple(s.security_id for s in matching),
                              coverage_record_ids=coverage_ids)


def resolve_at_data_root(data_root: Any, query: IdentityQuery, *, cutoff: datetime) -> IdentityResolution:
    """store を read-only で読んで解決する（何も書かない）。欠落 ／ 破損は status として返す（空の成功にしない）。"""
    cutoff = _checked_cutoff(cutoff)
    query = _checked_query(query)
    try:
        history = open_identity_history(data_root)
    except IdentityAuthorityMissing as exc:
        return IdentityResolution(ResolutionStatus.AUTHORITY_MISSING, query, cutoff, diagnostic=exc.code)
    except IdentityStoreCorrupt as exc:
        return IdentityResolution(ResolutionStatus.STORE_CORRUPTION, query, cutoff,
                                  diagnostic=f"{exc.code}:{exc.detail}:{exc.line_number}")
    return resolve(history, query, cutoff=cutoff)


__all__ = ["DERIVED_NON_AUTHORITY_NON_PERSISTENT", "IdentifierView", "IdentityQuery", "IdentityResolution",
           "IssuerView", "ListingView", "NameView", "QueryKind", "RESOLVER_VERSION", "ResolutionStatus",
           "SecurityView", "resolve", "resolve_at_data_root"]
