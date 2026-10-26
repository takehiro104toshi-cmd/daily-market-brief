"""P8-A1 — Issuer ／ Security の identity の test matrix A〜AZ（境界 ／ 凍結の BA〜BO は `test_screener_intelligence_boundary.py`）。

すべて合成の identity（架空の anchor ・code ・名前）。J-Quants ・network ・実データ ・legacy の watchlist は使わない。
store の書き込みは tmp だけ。
"""
from __future__ import annotations

import builtins
import io
import itertools
import json
import os
import subprocess
import sys
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import identity_model as m
from src.intelligence.screener_intelligence import identity_resolver as r
from src.intelligence.screener_intelligence import identity_store as s
from src.intelligence.screener_intelligence.identity_model import (Coverage, CoverageScope, DisplayName,
                                                                   IdentifierAssignment, IdentifierRetirement,
                                                                   IdentifierScheme, IdentityHistory,
                                                                   IdentityHistoryError, IdentityModelError,
                                                                   IssueClass, IssuerRegistration, ListingEnd,
                                                                   ListingEndReason, ListingStart, ListingVenue,
                                                                   NameKind, NameLanguage, RetirementReason,
                                                                   SecurityRegistration, SourceClass,
                                                                   SourceProvenance, SubjectKind)
from src.intelligence.screener_intelligence.identity_resolver import IdentityQuery, ResolutionStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
JQ = IdentifierScheme.JQUANTS_CODE
HR = SourceClass.HUMAN_REVIEWED
EX = SourceClass.OFFICIAL_EXCHANGE
JQS = SourceClass.JQUANTS
COMMON = IssueClass.COMMON_EQUITY
PREFERRED = IssueClass.PREFERRED_EQUITY


def at(year: int, month: int = 1, day: int = 1, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def prov(known_at: datetime, source: SourceClass = HR, ref: str = "review:p8-0001") -> SourceProvenance:
    return SourceProvenance(source_class=source, source_record_ref=ref, known_at=known_at)


def issuer(anchor: str, known_at: datetime, source: SourceClass = HR) -> IssuerRegistration:
    return IssuerRegistration(registration_anchor=anchor, provenance=prov(known_at, source))


def security(owner: IssuerRegistration, anchor: str, known_at: datetime, issue_class: IssueClass = COMMON,
             source: SourceClass = HR) -> SecurityRegistration:
    return SecurityRegistration(registration_anchor=anchor, issuer_id=owner.issuer_id, issue_class=issue_class,
                                provenance=prov(known_at, source))


def assign(sec: SecurityRegistration, value: str, start: datetime, known_at: datetime, source: SourceClass = JQS,
           scheme: IdentifierScheme = JQ) -> IdentifierAssignment:
    return IdentifierAssignment(security_id=sec.security_id, scheme=scheme, value=value, effective_from=start,
                                provenance=prov(known_at, source, "jq:master-snapshot"))


def retire(assignment: IdentifierAssignment, end: datetime, known_at: datetime,
           reason: RetirementReason = RetirementReason.RETIRED, source: SourceClass = EX) -> IdentifierRetirement:
    return IdentifierRetirement(assignment_record_id=assignment.record_id, effective_to=end, reason=reason,
                                provenance=prov(known_at, source, "exchange:notice-1"))


def name(subject, value: str, start: datetime, known_at: datetime, language: NameLanguage = NameLanguage.JA,
         source: SourceClass = HR) -> DisplayName:
    if isinstance(subject, IssuerRegistration):
        kind, sid, name_kind = SubjectKind.ISSUER, subject.issuer_id, NameKind.ISSUER_NAME
    else:
        kind, sid, name_kind = SubjectKind.SECURITY, subject.security_id, NameKind.SECURITY_NAME
    return DisplayName(subject_kind=kind, subject_id=sid, name_kind=name_kind, language=language, value=value,
                       effective_from=start, provenance=prov(known_at, source))


def listing(sec: SecurityRegistration, start: datetime, known_at: datetime, source: SourceClass = EX) -> ListingStart:
    return ListingStart(security_id=sec.security_id, venue=ListingVenue.TSE, effective_from=start,
                        provenance=prov(known_at, source, "exchange:listing"))


def end_listing(start_record: ListingStart, end: datetime, known_at: datetime, source: SourceClass = EX) -> ListingEnd:
    return ListingEnd(listing_record_id=start_record.record_id, effective_to=end, reason=ListingEndReason.DELISTED,
                      provenance=prov(known_at, source, "exchange:delisting"))


def cover(start: datetime, end: datetime, known_at: datetime, source: SourceClass = HR) -> Coverage:
    return Coverage(scope=CoverageScope.JP_LISTED_EQUITY_IDENTITY, effective_from=start, effective_to=end,
                    provenance=prov(known_at, source, "review:coverage"))


class World:
    """合成の年表（`known_at` の順に並ぶ record）。毎年 1 月 1 日に、その 1 年の coverage を宣言する。"""

    def __init__(self) -> None:
        k2010 = at(2010)
        self.A = issuer("hr:issuer-alpha", k2010)
        self.B = issuer("hr:issuer-beta", k2010)
        self.C = issuer("hr:issuer-gamma", k2010)
        self.A1 = security(self.A, "hr:security-alpha-common", k2010)
        self.B1 = security(self.B, "hr:security-beta-common", k2010)
        self.C1 = security(self.C, "hr:security-gamma-common", k2010)
        self.a1_code = assign(self.A1, "10010", k2010, k2010)
        self.b1_code = assign(self.B1, "20020", k2010, k2010)
        self.c1_code = assign(self.C1, "30030", k2010, k2010)
        self.a1_list = listing(self.A1, k2010, k2010)
        self.b1_list = listing(self.B1, k2010, k2010)
        self.c1_list = listing(self.C1, k2010, k2010)
        self.a_name_old = name(self.A, "アルファ工業", k2010, k2010)
        self.a_name_new = name(self.A, "アルファホールディングス", at(2015, 6, 1), at(2015, 6, 1))
        self.a1_name = name(self.A1, "アルファ工業 普通株式", k2010, k2010)
        self.A2 = security(self.A, "hr:security-alpha-preferred", at(2018, 4, 2), PREFERRED)
        self.a2_code = assign(self.A2, "10015", at(2018, 4, 2), at(2018, 4, 2))
        self.a2_list = listing(self.A2, at(2018, 4, 2), at(2018, 4, 2))
        self.c1_retire = retire(self.c1_code, at(2019, 4, 1), at(2019, 4, 1))
        self.c1_end = end_listing(self.c1_list, at(2019, 4, 1), at(2019, 4, 1))
        self.b1_end = end_listing(self.b1_list, at(2021, 6, 30), at(2021, 7, 1))      # 翌日に知る（遡った終わり）
        self.a1_code_retire = retire(self.a1_code, at(2022, 10, 3), at(2022, 10, 3), RetirementReason.REPLACED)
        self.a1_code_new = assign(self.A1, "10019", at(2022, 10, 3), at(2022, 10, 3), EX)   # 明示の継続
        self.D = issuer("hr:issuer-delta", at(2023, 4, 3))
        self.D1 = security(self.D, "hr:security-delta-common", at(2023, 4, 3))
        self.d1_code = assign(self.D1, "30030", at(2023, 4, 3), at(2023, 4, 3))          # 再利用された code
        self.d1_list = listing(self.D1, at(2023, 4, 3), at(2023, 4, 3))
        events = [self.A, self.B, self.C, self.A1, self.B1, self.C1, self.a1_code, self.b1_code, self.c1_code,
                  self.a1_list, self.b1_list, self.c1_list, self.a_name_old, self.a1_name, self.a_name_new,
                  self.A2, self.a2_code, self.a2_list, self.c1_retire, self.c1_end, self.b1_end,
                  self.a1_code_retire, self.a1_code_new, self.D, self.D1, self.d1_code, self.d1_list]
        events += [cover(at(year), at(year + 1), at(year)) for year in range(2010, 2027)]
        self.records = sorted(events, key=lambda rec: rec.known_at)                        # 安定 sort（依存の順を保つ）

    def history(self, until: datetime = None) -> IdentityHistory:
        return IdentityHistory(rec for rec in self.records if until is None or rec.known_at <= until)


@pytest.fixture()
def w() -> World:
    return World()


def query_code(value: str) -> IdentityQuery:
    return IdentityQuery.for_identifier(JQ, value)


def write_store(root: Path, records) -> s.IdentityStore:
    store = s.IdentityStore.initialize(root)
    for record in records:
        store.append(record)
    return store


# ================================================================ A〜D id


def test_a_issuer_id_is_opaque_and_derived_from_the_anchor_only(w: World) -> None:
    assert m.is_issuer_id(w.A.issuer_id) and w.A.issuer_id.startswith("p8iss_") and len(w.A.issuer_id) == 30
    assert w.A.issuer_id == m.derive_issuer_id("hr:issuer-alpha")
    again = issuer("hr:issuer-alpha", at(2030), EX)
    assert again.issuer_id == w.A.issuer_id                                                 # 出所 ／ 時刻は id に入らない
    for text in ("アルファ", "10010", "TSE", "hr:issuer-alpha"):
        assert text not in w.A.issuer_id
    assert w.A.issuer_id == PINNED_ISSUER_ID


def test_b_security_id_is_opaque_and_not_the_code_the_issuer_or_a_name(w: World) -> None:
    assert m.is_security_id(w.A1.security_id) and w.A1.security_id.startswith("p8sec_")
    assert w.A1.security_id == m.derive_security_id("hr:security-alpha-common")
    for other in ("10010", "10019", w.A.issuer_id, "アルファ工業 普通株式"):
        assert w.A1.security_id != other and other not in w.A1.security_id
    moved = security(w.B, "hr:security-alpha-common", at(2030))
    assert moved.security_id == w.A1.security_id                                            # issuer は id に入らない


def test_c_issuer_and_security_namespaces_are_distinct() -> None:
    same_anchor_issuer = m.derive_issuer_id("hr:shared-anchor")
    same_anchor_security = m.derive_security_id("hr:shared-anchor")
    assert same_anchor_issuer[6:] != same_anchor_security[6:]
    assert m.is_issuer_id(same_anchor_issuer) and not m.is_security_id(same_anchor_issuer)
    assert m.is_security_id(same_anchor_security) and not m.is_issuer_id(same_anchor_security)
    with pytest.raises(IdentityModelError):
        IdentityQuery.for_security(same_anchor_issuer)
    with pytest.raises(IdentityModelError):
        IdentityQuery.for_issuer(same_anchor_security)


@pytest.mark.parametrize("bad", ["10010", "12340", "p8sec_10010", "p8sec_" + "A" * 24, "p8sec_" + "0" * 23,
                                 "P8SEC_" + "0" * 24, "p8iss_" + "0" * 24, "", None, 10010])
def test_d_invalid_security_ids_are_rejected_everywhere(w: World, bad) -> None:
    with pytest.raises(IdentityModelError):
        IdentityQuery.for_security(bad)
    with pytest.raises(IdentityModelError):
        IdentifierAssignment(security_id=bad, scheme=JQ, value="10010", effective_from=at(2020), provenance=prov(at(2020)))


@pytest.mark.parametrize("anchor", ["10010", "issuer-alpha", "HR:issuer", "hr:", "hr:issuer alpha", "hr:a/b",
                                    "hr:x\\y", "hr:token-1", "hr:api_key", "x" * 200])
def test_d_invalid_anchors_are_rejected(anchor) -> None:
    with pytest.raises(IdentityModelError):
        m.derive_issuer_id(anchor)
    with pytest.raises(IdentityModelError):
        IssuerRegistration(registration_anchor=anchor, provenance=prov(at(2020)))


# ================================================================ E〜H 登録


def test_e_issuer_registration_requires_an_issuer_authority() -> None:
    assert issuer("hr:issuer-one", at(2020), HR).KIND is m.RecordKind.ISSUER_REGISTRATION
    for source in (EX, SourceClass.ISSUER_DISCLOSURE):
        issuer("hr:issuer-one", at(2020), source)
    with pytest.raises(IdentityModelError) as exc:
        issuer("hr:issuer-one", at(2020), JQS)                                               # vendor は発行体を立てない
    assert exc.value.code == "SOURCE_CLASS_NOT_AUTHORIZED"


def test_f_security_registration_binds_an_issuer_and_an_issue_class(w: World) -> None:
    assert w.A1.issuer_id == w.A.issuer_id and w.A1.issue_class is COMMON
    with pytest.raises(IdentityModelError):
        security(w.A, "hr:security-x", at(2020), source=JQS)
    with pytest.raises(IdentityModelError):
        SecurityRegistration(registration_anchor="hr:s", issuer_id=w.A.issuer_id, issue_class="COMMON_EQUITY",
                             provenance=prov(at(2020)))


def test_g_every_security_references_a_registered_issuer(w: World) -> None:
    history = w.history()
    for sec in history.securities.values():
        assert sec.issuer_id in history.issuers


def test_h_a_security_of_an_unregistered_issuer_is_rejected(tmp_path: Path) -> None:
    orphan_owner = issuer("hr:issuer-unregistered", at(2020))
    orphan = security(orphan_owner, "hr:security-orphan", at(2020))
    with pytest.raises(IdentityHistoryError) as exc:
        IdentityHistory([orphan])
    assert exc.value.code == "UNKNOWN_ISSUER"
    store = s.IdentityStore.initialize(tmp_path)
    with pytest.raises(s.IdentityAppendRejected) as rejected:
        store.append(orphan)
    assert rejected.value.code == "UNKNOWN_ISSUER"
    assert store.path.read_bytes() == b""


# ================================================================ I〜L 割り当て ・表示 ・名前の変更 ・code の変更


def test_i_identifier_assignments_are_time_bounded_and_scheme_checked(w: World) -> None:
    assert assign(w.A1, "593A0", at(2020), at(2020)).value == "593A0"                         # 英字の code を許す
    for bad in ("1001", "100100", "10o10", " 1001", 10010):
        with pytest.raises(IdentityModelError):
            assign(w.A1, bad, at(2020), at(2020))
    local = assign(w.A1, "1001", at(2020), at(2020), scheme=IdentifierScheme.LOCAL_CODE)
    assert local.scheme is IdentifierScheme.LOCAL_CODE
    with pytest.raises(IdentityModelError):
        assign(w.A1, "10010", datetime(2020, 1, 1), at(2020))
    view = r.resolve(w.history(), query_code("10010"), cutoff=at(2020, 6, 1)).security
    assert [(i.scheme, i.value, i.effective_from, i.effective_to) for i in view.identifiers] == [
        (JQ, "10010", at(2010), None)]                                                       # 2020 には終わりが未知


def test_j_display_names_are_metadata_resolved_at_the_cutoff(w: World) -> None:
    before = r.resolve(w.history(), IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2014)).issuer
    after = r.resolve(w.history(), IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2016)).issuer
    assert [n.value for n in before.names] == ["アルファ工業"]
    assert [n.value for n in after.names] == ["アルファホールディングス"]
    with pytest.raises(IdentityModelError):
        DisplayName(subject_kind=SubjectKind.ISSUER, subject_id=w.A.issuer_id, name_kind=NameKind.SECURITY_NAME,
                    language=NameLanguage.JA, value="x", effective_from=at(2020), provenance=prov(at(2020)))
    for bad in ("", " アルファ", "a\nb", "C:\\data", "https://example", "x" * 121):
        with pytest.raises(IdentityModelError):
            name(w.A, bad, at(2020), at(2020))


def test_k_a_name_change_keeps_the_issuer_id_and_creates_no_registration(w: World) -> None:
    history = w.history()
    assert len(history.issuers) == 4 and w.A.issuer_id in history.issuers
    before = r.resolve(history, IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2014))
    after = r.resolve(history, IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2016))
    assert before.issuer.issuer_id == after.issuer.issuer_id == w.A.issuer_id
    assert before.issuer.registration_record_id == after.issuer.registration_record_id


def test_l_a_code_change_keeps_the_security_id_with_explicit_continuity(w: World) -> None:
    history = w.history()
    old = r.resolve(history, query_code("10010"), cutoff=at(2021))
    new = r.resolve(history, query_code("10019"), cutoff=at(2023))
    assert old.status is new.status is ResolutionStatus.FOUND
    assert old.security.security_id == new.security.security_id == w.A1.security_id
    assert r.resolve(history, query_code("10010"), cutoff=at(2023)).status is ResolutionStatus.NOT_FOUND
    assert r.resolve(history, query_code("10019"), cutoff=at(2021)).status is ResolutionStatus.NOT_FOUND
    vendor_only = assign(w.A1, "10019", at(2022, 10, 3), at(2022, 10, 3), JQS)             # vendor は継続を立てない
    prefix = [rec for rec in w.records if rec.known_at < at(2022, 10, 3)] + [w.a1_code_retire]
    with pytest.raises(IdentityHistoryError) as exc:
        IdentityHistory(prefix + [vendor_only])
    assert exc.value.code == "CONTINUITY_NOT_AUTHORIZED"


# ================================================================ M〜P code の再利用


def test_m_a_reused_code_resolves_to_distinct_securities(w: World) -> None:
    history = w.history()
    early = r.resolve(history, query_code("30030"), cutoff=at(2015))
    late = r.resolve(history, query_code("30030"), cutoff=at(2024))
    assert early.security.security_id == w.C1.security_id != late.security.security_id == w.D1.security_id
    assert early.security.issuer_id != late.security.issuer_id


def test_n_the_historical_old_code_resolves_to_the_old_security(w: World) -> None:
    result = r.resolve(w.history(), query_code("30030"), cutoff=at(2019, 3, 31))
    assert result.status is ResolutionStatus.FOUND and result.security.security_id == w.C1.security_id


def test_o_the_later_reused_code_resolves_to_the_new_security(w: World) -> None:
    result = r.resolve(w.history(), query_code("30030"), cutoff=at(2023, 4, 3))
    assert result.status is ResolutionStatus.FOUND and result.security.security_id == w.D1.security_id


def test_p_no_cross_time_leakage_between_the_two_holders(w: World) -> None:
    gap = r.resolve(w.history(), query_code("30030"), cutoff=at(2020, 6, 1))
    assert gap.status is ResolutionStatus.NOT_FOUND and gap.security is None
    for cutoff in (at(2011), at(2015), at(2019, 3, 31)):
        full = r.resolve(w.history(), query_code("30030"), cutoff=cutoff)
        pre = r.resolve(w.history(until=cutoff), query_code("30030"), cutoff=cutoff)
        assert full.canonical_json() == pre.canonical_json()                                 # D の record は過去に無関係
        assert w.D1.security_id not in full.canonical_json()


def test_p_an_overlapping_reuse_is_rejected(w: World) -> None:
    early_reuse = assign(w.D1, "30030", at(2018), at(2023, 4, 3))                              # C1 がまだ持っている期間
    prefix = [rec for rec in w.records if rec.known_at <= at(2023, 4, 3) and rec is not w.d1_code]
    with pytest.raises(IdentityHistoryError) as exc:
        IdentityHistory(prefix + [early_reuse])
    assert exc.value.code == "CONFLICTING_ASSIGNMENT"


# ================================================================ Q〜R 複数の Security


def test_q_one_issuer_resolves_to_an_explicit_collection_of_securities(w: World) -> None:
    result = r.resolve(w.history(), IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2019))
    assert result.status is ResolutionStatus.FOUND
    assert [sv.security_id for sv in result.issuer.securities] == sorted([w.A1.security_id, w.A2.security_id])
    assert {sv.issue_class for sv in result.issuer.securities} == {COMMON, PREFERRED}


def test_r_the_resolver_never_silently_chooses_one_security(w: World) -> None:
    history = w.history()
    common = r.resolve(history, IdentityQuery.for_issuer_security(w.A.issuer_id, COMMON), cutoff=at(2019))
    assert common.status is ResolutionStatus.FOUND and common.security.security_id == w.A1.security_id
    k = at(2026, 2, 1)
    second_common = security(w.A, "hr:security-alpha-common-2", k)
    extra = [second_common, assign(second_common, "10030", k, k), listing(second_common, k, k)]
    both = IdentityHistory([*w.records, *extra])
    result = r.resolve(both, IdentityQuery.for_issuer_security(w.A.issuer_id, COMMON), cutoff=at(2026, 3, 1))
    assert result.status is ResolutionStatus.AMBIGUOUS and result.security is None
    assert result.candidates == tuple(sorted([w.A1.security_id, second_common.security_id]))
    assert r.resolve(both, IdentityQuery.for_issuer_security(w.A.issuer_id, PREFERRED),
                     cutoff=at(2026, 3, 1)).security.security_id == w.A2.security_id


# ================================================================ S〜W 上場 ・廃止


def test_s_a_listing_starts_at_its_effective_time() -> None:
    k = at(2016)
    owner = issuer("hr:issuer-pre", k)
    sec = security(owner, "hr:security-pre", k)
    records = [cover(at(2016), at(2017), k), owner, sec, listing(sec, at(2016, 3, 1), k)]
    history = IdentityHistory(records)
    before = r.resolve(history, IdentityQuery.for_security(sec.security_id), cutoff=at(2016, 2, 29))
    after = r.resolve(history, IdentityQuery.for_security(sec.security_id), cutoff=at(2016, 3, 1))
    assert before.status is ResolutionStatus.NOT_ACTIVE_AT_CUTOFF and before.security.listing is None
    assert after.status is ResolutionStatus.FOUND and after.security.active


def test_t_a_delisting_ends_activity(w: World) -> None:
    result = r.resolve(w.history(), IdentityQuery.for_security(w.B1.security_id), cutoff=at(2021, 7, 2))
    assert result.status is ResolutionStatus.NOT_ACTIVE_AT_CUTOFF and not result.security.active
    assert result.security.listing.effective_to == at(2021, 6, 30)


def test_u_resolution_before_the_delisting_is_still_possible(w: World) -> None:
    result = r.resolve(w.history(), IdentityQuery.for_security(w.B1.security_id), cutoff=at(2021, 6, 29))
    assert result.status is ResolutionStatus.FOUND and result.security.listing.effective_to is None


def test_v_after_the_delisting_the_code_resolves_to_an_inactive_security(w: World) -> None:
    result = r.resolve(w.history(), query_code("20020"), cutoff=at(2022))
    assert result.status is ResolutionStatus.NOT_ACTIVE_AT_CUTOFF
    assert result.security.security_id == w.B1.security_id and not result.security.active


def test_w_the_identity_still_exists_after_the_delisting(w: World, tmp_path: Path) -> None:
    store = write_store(tmp_path, w.records)
    result = r.resolve_at_data_root(tmp_path, IdentityQuery.for_issuer(w.B.issuer_id), cutoff=at(2026, 6, 1))
    assert result.status is ResolutionStatus.NOT_ACTIVE_AT_CUTOFF
    assert result.issuer.securities[0].security_id == w.B1.security_id
    assert w.B1.record_id in {rec.record_id for rec in store.records()}
    assert w.b1_list.record_id in store.history.listings                                     # 物理的に消えない


# ================================================================ X〜Y 再上場 ・新しい発行


def test_x_a_new_issue_after_delisting_is_a_new_security_id(w: World) -> None:
    k = at(2026, 2, 1)
    relisted = security(w.B, "hr:security-beta-common-relisted", k)
    history = IdentityHistory([*w.records, relisted, assign(relisted, "20021", k, k), listing(relisted, k, k)])
    result = r.resolve(history, IdentityQuery.for_issuer(w.B.issuer_id), cutoff=at(2026, 3, 1))
    ids = [sv.security_id for sv in result.issuer.securities]
    assert relisted.security_id != w.B1.security_id and set(ids) == {w.B1.security_id, relisted.security_id}
    assert {sv.security_id: sv.active for sv in result.issuer.securities} == {w.B1.security_id: False,
                                                                           relisted.security_id: True}


def test_y_no_automatic_continuity_for_a_relisting(w: World) -> None:
    k = at(2026, 2, 1)
    with pytest.raises(IdentityHistoryError) as exc:
        IdentityHistory([*w.records, listing(w.B1, k, k, JQS)])                              # vendor は継続を示せない
    assert exc.value.code == "CONTINUITY_NOT_AUTHORIZED"
    explicit = IdentityHistory([*w.records, listing(w.B1, k, k, HR)])                         # 人が明示した継続だけ
    assert r.resolve(explicit, IdentityQuery.for_security(w.B1.security_id), cutoff=at(2026, 3, 1)).status is \
        ResolutionStatus.FOUND
    with pytest.raises(IdentityHistoryError) as overlap:
        IdentityHistory([*w.records, listing(w.A1, k, k, HR)])                                # 終わっていない上場に重ねない
    assert overlap.value.code == "OVERLAPPING_LISTING"


# ================================================================ Z〜AD 時間


def test_z_an_explicit_cutoff_is_required(w: World) -> None:
    with pytest.raises(TypeError):
        r.resolve(w.history(), query_code("10010"))                                           # type: ignore[call-arg]
    for bad in (None, "2020-01-01", 0):
        with pytest.raises(IdentityModelError) as exc:
            r.resolve(w.history(), query_code("10010"), cutoff=bad)
        assert exc.value.code == "CUTOFF_REQUIRED"
    with pytest.raises(IdentityModelError):
        r.resolve_at_data_root(Path("unused"), query_code("10010"), cutoff=None)


def test_aa_a_naive_cutoff_is_rejected(w: World, tmp_path: Path) -> None:
    for call in (lambda: r.resolve(w.history(), query_code("10010"), cutoff=datetime(2020, 1, 1)),
                 lambda: r.resolve_at_data_root(tmp_path, query_code("10010"), cutoff=datetime(2020, 1, 1))):
        with pytest.raises(IdentityModelError) as exc:
            call()
        assert exc.value.code == "NAIVE_DATETIME"


def test_ab_future_records_do_not_change_a_past_resolution(w: World) -> None:
    for cutoff in (at(2012), at(2019, 3, 31), at(2021, 6, 30, 12), at(2023, 4, 2)):
        for query in (query_code("30030"), query_code("10010"), IdentityQuery.for_issuer(w.A.issuer_id),
                      IdentityQuery.for_security(w.B1.security_id)):
            full = r.resolve(w.history(), query, cutoff=cutoff).canonical_json()
            assert full == r.resolve(w.history(until=cutoff), query, cutoff=cutoff).canonical_json()


def test_ac_a_record_known_after_the_cutoff_is_ignored(w: World) -> None:
    """B1 の廃止は 2021-06-30 付だが、知ったのは 2021-07-01。その間の cutoff では上場中と答える（当時の知識）。"""
    mid = r.resolve(w.history(), IdentityQuery.for_security(w.B1.security_id), cutoff=at(2021, 6, 30, 12))
    assert mid.status is ResolutionStatus.FOUND and mid.security.listing.effective_to is None
    assert w.b1_end.record_id not in mid.supporting_record_ids


def test_ad_effective_intervals_are_half_open(w: World) -> None:
    history = w.history()
    edge = at(2022, 10, 3)
    assert r.resolve(history, query_code("10010"), cutoff=edge - timedelta(microseconds=1)).status is \
        ResolutionStatus.FOUND
    assert r.resolve(history, query_code("10010"), cutoff=edge).status is ResolutionStatus.NOT_FOUND
    assert r.resolve(history, query_code("10019"), cutoff=edge).status is ResolutionStatus.FOUND
    with pytest.raises(IdentityHistoryError) as exc:
        IdentityHistory([*w.records, retire(w.d1_code, at(2023, 4, 3), at(2026, 2, 1))])      # 始まり ≦ 終わり
    assert exc.value.code == "INVALID_INTERVAL"
    with pytest.raises(IdentityModelError):
        cover(at(2020), at(2020), at(2020))


# ================================================================ AE〜AK status


def test_ae_found(w: World) -> None:
    result = r.resolve(w.history(), IdentityQuery.for_security(w.A1.security_id), cutoff=at(2020))
    assert result.status is ResolutionStatus.FOUND and result.security.active


def test_af_not_found(w: World) -> None:
    for query in (query_code("99990"), IdentityQuery.for_security(m.derive_security_id("hr:never-registered")),
                  IdentityQuery.for_issuer(m.derive_issuer_id("hr:never-registered"))):
        result = r.resolve(w.history(), query, cutoff=at(2020))
        assert result.status is ResolutionStatus.NOT_FOUND and result.security is None and result.issuer is None


def test_ag_not_yet_known(w: World) -> None:
    assert r.resolve(w.history(), query_code("10010"), cutoff=at(2009, 12, 31)).status is ResolutionStatus.NOT_YET_KNOWN
    stale = IdentityHistory([rec for rec in w.records if rec.known_at < at(2026)])            # 2026 の coverage が未宣言
    assert r.resolve(stale, query_code("10019"), cutoff=at(2026, 3, 1)).status is ResolutionStatus.NOT_YET_KNOWN


def test_ah_not_active_at_cutoff(w: World) -> None:
    result = r.resolve(w.history(), IdentityQuery.for_security(w.C1.security_id), cutoff=at(2020))
    assert result.status is ResolutionStatus.NOT_ACTIVE_AT_CUTOFF and result.security.security_id == w.C1.security_id


class _UnvalidatedView(IdentityHistory):
    """検証を経ない像（resolver の防御だけを調べる）。`known_by` は自分を返す。"""

    def known_by(self, cutoff):
        return self


def test_ai_ambiguous_is_returned_instead_of_a_silent_choice(w: World) -> None:
    k = at(2026, 2, 1)
    second_common = security(w.A, "hr:security-alpha-common-2", k)
    both = IdentityHistory([*w.records, second_common, listing(second_common, k, k)])
    result = r.resolve(both, IdentityQuery.for_issuer_security(w.A.issuer_id, COMMON), cutoff=at(2026, 3, 1))
    assert result.status is ResolutionStatus.AMBIGUOUS and result.security is None and len(result.candidates) == 2
    view = _UnvalidatedView(rec for rec in w.records if rec.known_at <= at(2015))            # 不変条件は重なりを拒むが、
    view.securities[w.D1.security_id] = w.D1                                                 # 破れた像でも 1 つを選ばない
    view.assignments["p8idr_" + "f" * 24] = replace(w.d1_code, effective_from=at(2011))
    result = r.resolve(view, query_code("30030"), cutoff=at(2015))
    assert result.status is ResolutionStatus.AMBIGUOUS and result.security is None
    assert result.candidates == tuple(sorted([w.C1.security_id, w.D1.security_id]))


def test_aj_authority_missing(tmp_path: Path) -> None:
    for root in (tmp_path, tmp_path / "absent"):
        result = r.resolve_at_data_root(root, query_code("10010"), cutoff=at(2020))
        assert result.status is ResolutionStatus.AUTHORITY_MISSING and result.diagnostic == "AUTHORITY_MISSING"
    assert list(tmp_path.iterdir()) == []                                                     # 何も作らない
    with pytest.raises(s.IdentityAppendRejected):
        r.resolve_at_data_root("", query_code("10010"), cutoff=at(2020))


def test_ak_store_corruption(w: World, tmp_path: Path) -> None:
    store = write_store(tmp_path, w.records)
    with store.path.open("ab") as handle:
        handle.write(b'{"not": "a record"}\n')
    result = r.resolve_at_data_root(tmp_path, query_code("10010"), cutoff=at(2020))
    assert result.status is ResolutionStatus.STORE_CORRUPTION and result.security is None
    assert result.diagnostic.startswith("INVALID_RECORD:") and str(tmp_path) not in result.canonical_json()


# ================================================================ AL〜AM coverage


def test_al_the_coverage_boundary_is_half_open() -> None:
    k = at(2010)
    owner = issuer("hr:issuer-cov", k)
    sec = security(owner, "hr:security-cov", k)
    records = [owner, sec, listing(sec, at(2005), k), cover(at(2010, 6, 1), at(2011), k),
               cover(at(2012), at(2013), k)]
    history = IdentityHistory(records)
    status = {cutoff: r.resolve(history, IdentityQuery.for_security(sec.security_id), cutoff=cutoff).status
              for cutoff in (at(2010, 3, 1), at(2010, 6, 1), at(2011), at(2011, 6, 1), at(2012), at(2013))}
    assert status == {at(2010, 3, 1): ResolutionStatus.BEFORE_COVERAGE, at(2010, 6, 1): ResolutionStatus.FOUND,
                      at(2011): ResolutionStatus.OUTSIDE_COVERAGE, at(2011, 6, 1): ResolutionStatus.OUTSIDE_COVERAGE,
                      at(2012): ResolutionStatus.FOUND, at(2013): ResolutionStatus.NOT_YET_KNOWN}


def test_am_before_coverage_fails_closed_even_for_a_known_identity() -> None:
    k = at(2010)
    owner = issuer("hr:issuer-cov", k)
    sec = security(owner, "hr:security-cov", k)
    history = IdentityHistory([owner, sec, assign(sec, "55550", at(2000), k), listing(sec, at(2000), k),
                               cover(at(2010, 6, 1), at(2011), k)])
    for query in (IdentityQuery.for_security(sec.security_id), query_code("55550"), query_code("99990"),
                  IdentityQuery.for_issuer(owner.issuer_id)):
        result = r.resolve(history, query, cutoff=at(2010, 3, 1))
        assert result.status is ResolutionStatus.BEFORE_COVERAGE                              # NOT_FOUND ／ FOUND にしない
        assert result.security is None and result.issuer is None and result.supporting_record_ids == ()


# ================================================================ AN〜AR store


def test_an_an_exact_duplicate_converges(w: World, tmp_path: Path) -> None:
    store = write_store(tmp_path, w.records)
    before = store.path.read_bytes()
    for record in (w.A, w.c1_retire, w.records[-1]):
        assert store.append(record).status is s.AppendStatus.ALREADY_PRESENT
        again = type(record)(**{f.name: getattr(record, f.name) for f in fields(record)})
        assert store.append(again).status is s.AppendStatus.ALREADY_PRESENT
    assert store.path.read_bytes() == before
    assert IdentityHistory([w.A, w.A]).records == (w.A,)


def test_ao_conflicting_records_are_rejected(w: World, tmp_path: Path) -> None:
    store = write_store(tmp_path, w.records)
    k = at(2026, 2, 1)
    before = store.path.read_bytes()
    cases = {"CONFLICTING_ASSIGNMENT": assign(w.D1, "10019", k, k),                         # A1 が持っている code
             "REGISTRATION_CONFLICT": security(w.A, "hr:security-alpha-common", k, PREFERRED),
             "DUPLICATE_RETIREMENT": retire(w.c1_code, at(2019, 5, 1), k),
             "DUPLICATE_LISTING_END": end_listing(w.b1_list, at(2021, 7, 30), k),
             "NON_MONOTONIC_KNOWN_AT": name(w.A, "過去の名前", at(2011), at(2011)),
             "CONFLICTING_NAME": name(w.A, "別の名前", at(2015, 6, 1), k)}
    second_code_same_scheme = assign(w.D1, "30031", k, k, EX)                                  # D1 は 30030 を持つ
    cases["CONFLICTING_ASSIGNMENT_SAME_SECURITY"] = second_code_same_scheme
    for code, record in cases.items():
        with pytest.raises(s.IdentityAppendRejected) as exc:
            store.append(record)
        assert exc.value.code == code.replace("_SAME_SECURITY", ""), code
    assert store.path.read_bytes() == before


def _rewrite(path: Path, lines) -> None:
    path.write_bytes("".join(lines).encode("utf-8"))


@pytest.mark.parametrize("damage,reason", [
    ("fork", "INVALID_HISTORY"), ("physical_duplicate", "PHYSICAL_DUPLICATE"), ("truncated", "TRUNCATED_FINAL_LINE"),
    ("blank", "BLANK_LINE"), ("non_canonical", "INVALID_RECORD"), ("tampered_id", "INVALID_RECORD"),
    ("tampered_value", "INVALID_RECORD"), ("invalid_utf8", "INVALID_ENCODING"), ("reordered", "INVALID_HISTORY")])
def test_ap_forks_and_corruption_are_detected(w: World, tmp_path: Path, damage: str, reason: str) -> None:
    store = write_store(tmp_path, w.records)
    lines = list(store.canonical_lines())
    path = store.path
    if damage == "fork":                                                                     # 同じ割り当ての 2 本目の終わり
        lines.append(retire(w.c1_code, at(2019, 6, 1), at(2026, 6, 1)).canonical_line())
    elif damage == "physical_duplicate":
        lines.append(lines[3])
    elif damage == "truncated":
        lines[-1] = lines[-1][:-5]
    elif damage == "blank":
        lines.insert(2, "\n")
    elif damage == "non_canonical":
        lines[0] = json.dumps(json.loads(lines[0]), sort_keys=False, indent=1).replace("\n", " ") + "\n"
    elif damage == "tampered_id":
        lines[0] = lines[0].replace(w.A.record_id, "p8idr_" + "0" * 24)
    elif damage == "tampered_value":
        lines[6] = lines[6].replace('"10010"', '"10011"')
    elif damage == "invalid_utf8":
        path.write_bytes(path.read_bytes() + b"\xff\xfe\n")
        lines = None
    elif damage == "reordered":
        lines[0], lines[3] = lines[3], lines[0]                                             # 登録より先に Security
    if lines is not None:
        _rewrite(path, lines)
    with pytest.raises(s.IdentityStoreCorrupt) as exc:
        s.IdentityStore.open(tmp_path, read_only=True)
    assert exc.value.code == reason and exc.value.category is s.IdentityFailureCategory.STORE_CORRUPTION
    assert str(tmp_path) not in str(exc.value)
    result = r.resolve_at_data_root(tmp_path, query_code("10010"), cutoff=at(2020))
    assert result.status is ResolutionStatus.STORE_CORRUPTION and result.security is None


def test_aq_the_store_is_append_only(w: World, tmp_path: Path) -> None:
    store = s.IdentityStore.initialize(tmp_path)
    previous = b""
    for record in w.records:
        store.append(record)
        current = store.path.read_bytes()
        assert current.startswith(previous) and current != previous
        previous = current
    public = {n for n in dir(s.IdentityStore) if not n.startswith("_")}
    assert not public & {"delete", "remove", "update", "replace", "rewrite", "truncate", "compact", "repair",
                         "migrate", "set", "put"}
    with pytest.raises(s.IdentityAppendRejected) as ro:
        s.IdentityStore.open(tmp_path, read_only=True).append(w.A)
    assert ro.value.code == "READ_ONLY"
    other = s.IdentityStore.open(tmp_path)
    store.path.write_bytes(store.path.read_bytes() + w.A.canonical_line().encode())
    with pytest.raises(s.IdentityConcurrentModification):
        other.append(name(w.A, "外部変更の後", at(2026, 3, 1), at(2026, 3, 1)))


def test_ar_no_automatic_repair(w: World, tmp_path: Path) -> None:
    store = write_store(tmp_path, w.records)
    damaged = store.path.read_bytes()[:-3]
    store.path.write_bytes(damaged)
    for _ in range(3):
        with pytest.raises(s.IdentityStoreCorrupt):
            s.IdentityStore.open(tmp_path)
        r.resolve_at_data_root(tmp_path, query_code("10010"), cutoff=at(2020))
        with pytest.raises(s.IdentityStoreCorrupt):
            s.IdentityStore.initialize(tmp_path)
    assert store.path.read_bytes() == damaged


# ================================================================ AS〜AV 決定論


GOLDEN = {"issuer": "hr:issuer-alpha", "security": "hr:security-alpha-common"}


def test_as_record_ids_are_deterministic_and_bind_the_semantic_payload(w: World) -> None:
    rebuilt = World()
    assert [rec.record_id for rec in rebuilt.records] == [rec.record_id for rec in w.records]
    assert len({rec.record_id for rec in w.records}) == len(w.records)
    changed = replace(w.a1_code, value="10011")
    assert changed.record_id != w.a1_code.record_id
    later = replace(w.a1_code, provenance=prov(at(2011), JQS, "jq:master-snapshot"))
    assert later.record_id != w.a1_code.record_id                                          # 既知の時刻は意味の一部
    payload = json.loads(w.a1_code.canonical_line())
    assert set(payload) == {"payload", "provenance", "record_id", "record_kind", "schema_version"}


def test_as_pinned_identity_values() -> None:
    assert m.derive_issuer_id(GOLDEN["issuer"]) == PINNED_ISSUER_ID
    assert m.derive_security_id(GOLDEN["security"]) == PINNED_SECURITY_ID


def test_at_resolution_is_invariant_to_non_semantic_input_permutation(w: World) -> None:
    k = at(2026, 2, 1)
    extras = [name(w.A, "アルファHD", k, k, NameLanguage.EN), name(w.B, "Beta Denki", k, k, NameLanguage.EN),
              name(w.D1, "デルタ 普通株式", k, k)]
    results = set()
    for order in itertools.permutations(extras):
        history = IdentityHistory([*w.records, *order])
        results.add(tuple(r.resolve(history, q, cutoff=at(2026, 3, 1)).canonical_json() for q in (
            IdentityQuery.for_issuer(w.A.issuer_id), IdentityQuery.for_issuer(w.B.issuer_id), query_code("30030"))))
    assert len(results) == 1


def test_au_paths_and_mtimes_do_not_matter(w: World, tmp_path: Path) -> None:
    roots = [tmp_path / "one", tmp_path / "deeper" / "two"]
    for root in roots:
        write_store(root, w.records)
    os.utime(s.identity_path(roots[1]), (1, 1))
    lines = {s.IdentityStore.open(root, read_only=True).canonical_lines() for root in roots}
    assert len(lines) == 1
    answers = {r.resolve_at_data_root(root, IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2024)).canonical_json()
               for root in roots}
    assert len(answers) == 1 and not any(str(root) in next(iter(answers)) for root in roots)


def test_av_no_clock_or_randomness_in_identity() -> None:
    code = ("from datetime import datetime, timezone\n"
            "from src.intelligence.screener_intelligence import identity_model as m\n"
            "p = m.SourceProvenance(source_class=m.SourceClass.HUMAN_REVIEWED, source_record_ref='review:1',"
            " known_at=datetime(2020, 1, 1, tzinfo=timezone.utc))\n"
            "print(m.derive_issuer_id('hr:issuer-alpha'), m.IssuerRegistration(registration_anchor='hr:issuer-alpha',"
            " provenance=p).record_id)\n")
    outputs = {subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                              env={"PYTHONPATH": str(REPO_ROOT), "PATH": "", "PYTHONHASHSEED": seed}).stdout
               for seed in ("0", "1", "12345")}
    assert len(outputs) == 1 and next(iter(outputs)).split()[0] == PINNED_ISSUER_ID


# ================================================================ AW〜AZ 出所 ・security


def test_aw_bounded_source_provenance_is_retained(w: World, tmp_path: Path) -> None:
    store = write_store(tmp_path, w.records)
    by_id = {rec.record_id: rec for rec in store.records()}
    result = r.resolve_at_data_root(tmp_path, query_code("30030"), cutoff=at(2024))
    assert result.supporting_record_ids
    for rid in result.supporting_record_ids:
        provenance = by_id[rid].provenance
        assert provenance.source_class in SourceClass and provenance.source_record_ref and provenance.known_at
    stored = json.loads(store.canonical_lines()[0])["provenance"]
    assert set(stored) == {"known_at", "source_class", "source_record_ref"}


@pytest.mark.parametrize("ref", ["", " review", "review 1", "{\"body\": 1}", "x" * 161, "line1\nline2", "a=b"])
def test_ax_no_raw_source_body(ref: str) -> None:
    with pytest.raises(IdentityModelError) as exc:
        prov(at(2020), HR, ref)
    assert ref not in str(exc.value) or ref == ""


@pytest.mark.parametrize("ref", ["C:\\data\\x", "/var/lib/x", "../data", "file:///srv/x", "https://example.test/a",
                                 "~/data"])
def test_ay_no_machine_path(ref: str) -> None:
    with pytest.raises(IdentityModelError):
        prov(at(2020), HR, ref)
    with pytest.raises(IdentityModelError):
        IssuerRegistration(registration_anchor="hr:" + ref, provenance=prov(at(2020)))


@pytest.mark.parametrize("ref", ["token:abc", "api_key:1", "apikey-1", "password:x", "secret:1", "bearer:x",
                                 "authorization:x", "X-API-KEY:1"])
def test_az_no_credentials(ref: str) -> None:
    with pytest.raises(IdentityModelError) as exc:
        prov(at(2020), HR, ref)
    assert exc.value.code in ("CREDENTIAL_LIKE_TEXT", "INVALID_SOURCE_REF") and ref not in str(exc.value)


# ================================================================ 解決は record にならない ・書き込み 0


def test_a_resolution_is_derived_and_can_never_become_a_record(w: World, tmp_path: Path) -> None:
    store = write_store(tmp_path, w.records)
    result = r.resolve(store.history, IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2024))
    assert result.authority_class == r.DERIVED_NON_AUTHORITY_NON_PERSISTENT
    assert m.RecordKind.ISSUER_REGISTRATION.value not in result.as_dict()
    with pytest.raises(s.IdentityAppendRejected) as exc:
        store.append(result)
    assert exc.value.code == "INVALID_TYPE"
    with pytest.raises(IdentityModelError):
        m.parse_identity_record(result.as_dict())
    assert not hasattr(result, "record_id") and not hasattr(result, "canonical_line")


def test_resolution_reads_are_zero_write_and_replay_byte_identically(w: World, tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    write_store(tmp_path, w.records)
    snapshot = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in "wax+"), mode
        return real_open(file, mode, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("write attempted")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    for attr in ("mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir", "fsync", "utime", "truncate"):
        if hasattr(os, attr):
            monkeypatch.setattr(os, attr, forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    queries = (query_code("30030"), IdentityQuery.for_issuer(w.A.issuer_id), IdentityQuery.for_security(w.B1.security_id),
               IdentityQuery.for_issuer_security(w.A.issuer_id, COMMON))
    runs = [[r.resolve_at_data_root(tmp_path, q, cutoff=cutoff).canonical_json()
             for q in queries for cutoff in (at(2015), at(2021, 7, 2), at(2024))] for _ in range(3)]
    monkeypatch.undo()
    assert runs[0] == runs[1] == runs[2]
    assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()} == snapshot


#: 導出の規則が変わったら落ちる固定値（内容 address の版を上げずに id の計算を変えさせない）
PINNED_ISSUER_ID = "p8iss_ea5b6eae65191d1666dc63a2"
PINNED_SECURITY_ID = "p8sec_f81a3c86ad987fa2220b9150"
