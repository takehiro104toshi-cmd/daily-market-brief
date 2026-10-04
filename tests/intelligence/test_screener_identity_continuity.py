"""P8-OBS60-I1 — identity の継続 coverage の authority（model I3）の test。

tmp_path の private root に凍結 ID2 で合成の identity を登録し、凍結 ACQ0 の取得 event を置いてから継続の executor を動かす。
合成の master の行だけ。J-Quants ・network ・時計 ・乱数 ・LLM は使わない。A1 ・ID1 ・ID2 ・ACQ0 の module は変えない。
"""
from __future__ import annotations

import ast
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import identity_continuity_coverage as cc
from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence.acquisition_event_model import (AcquisitionEvent, AcquisitionStatus,
                                                                            RequestScope, bounded_content_digest)
from src.intelligence.screener_intelligence.acquisition_event_store import AcquisitionEventStore
from src.intelligence.screener_intelligence.identity_bootstrap_model import BootstrapBatch
from src.intelligence.screener_intelligence.identity_continuity_coverage import (ContinuityError, ContinuityOutcome,
                                                                                 ContinuityReason, ContinuityResult,
                                                                                 ReviewOrigin,
                                                                                 execute_identity_continuity)
from src.intelligence.screener_intelligence.identity_model import (Coverage, CoverageScope, IdentifierAssignment,
                                                                   IdentifierRetirement, IdentifierScheme, IssueClass,
                                                                   IssuerRegistration, ListingEnd, ListingEndReason,
                                                                   ListingStart, ListingVenue, RecordKind,
                                                                   RetirementReason, SecurityRegistration,
                                                                   SourceClass, SourceProvenance)
from src.intelligence.screener_intelligence.identity_resolver import IdentityQuery, ResolutionStatus, resolve
from src.intelligence.screener_intelligence.jquants_live_model import FINS_SUMMARY_PATH, MASTER_PATH
from src.intelligence.screener_intelligence.observation_model import TOKYO
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_identity_bootstrap import master
from tests.intelligence.test_screener_identity_registration import ACCEPTED, BATCH, lines, reviewed_for, rewrite
from tests.intelligence.test_screener_identity_registration import run as register

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
MARKETS = ("0111", "0112", "0113")
D0 = date(2026, 6, 30)                                                                   # bootstrap の snapshot の日
T = date(2026, 7, 2)                                                                     # 継続を確かめる日（審査の後）
ACQUIRED = datetime(2026, 7, 2, 18, 0, tzinfo=TOKYO)                                     # T の夕方の取得（test が渡す）
O = ContinuityOutcome
R = ContinuityReason


def snap(code: str = "13010", day: date = T, **overrides) -> dict:
    """T の bounded な master の行（LIVE1 の 6 欄: ID1 の 5 欄 ＋ ProdCat）。"""
    row = master(code, day=day.isoformat(), ProdCat="011")
    row.update(overrides)
    return row


def record_event(root: Path, day: date = T, rows=None, *, status=AcquisitionStatus.COMPLETE, acquired=ACQUIRED,
                 endpoint: str = MASTER_PATH, pagination: bool = False, failure_code: str = "") -> str:
    rows = [snap()] if rows is None else rows
    scope = RequestScope.of(endpoint, {"date": day.isoformat()} if endpoint == MASTER_PATH else {"code": "13010"})
    content = bounded_content_digest(endpoint, rows) if endpoint == MASTER_PATH else None
    if endpoint != MASTER_PATH:
        status = AcquisitionStatus.EMPTY                                                  # fins の event（0 行）
    event = AcquisitionEvent(provider=SourceClass.JQUANTS, scope=scope, acquired_at=acquired, status=status,
                             row_count=content.row_count if content else 0, pagination_key_present=pagination,
                             pages_followed=0 if status is AcquisitionStatus.FAILED else 1,
                             content_digest=content.digest if content
                             else bounded_content_digest(FINS_SUMMARY_PATH, []).digest, failure_code=failure_code)
    try:
        store = AcquisitionEventStore.open(root)
    except Exception:                                                                    # noqa: BLE001 - test only
        store = AcquisitionEventStore.initialize(root)
    store.append(event)
    return event.reference


def run(root: Path, day: date = T, rows=None, reference: str = "", markets=MARKETS) -> ContinuityResult:
    rows = [snap()] if rows is None else rows
    return execute_identity_continuity(data_root=root, day=day, rows=rows, event_reference=reference,
                                       supported_markets=markets)


def history(root: Path):
    return ist.IdentityStore.open(root, read_only=True).history


def issuer_of(root: Path, code: str = "13010") -> str:
    hist = history(root)
    for assignment in hist.assignments.values():
        if assignment.value == code:
            return hist.securities[assignment.security_id].issuer_id
    raise AssertionError(code)


def status_at(root: Path, when: datetime, code: str = "13010") -> ResolutionStatus:
    return resolve(history(root), IdentityQuery.for_issuer(issuer_of(root, code)), cutoff=when).status


@pytest.fixture
def root(tmp_path: Path) -> Path:
    private = tmp_path / "private_root"
    ist.IdentityStore.initialize(private)
    AcquisitionEventStore.initialize(private)
    register(private, [master()])                                                        # D0 の bootstrap（凍結 ID2）
    return private


# ================================================================ A happy path ・REUSED


def test_a_complete_matching_snapshot_with_all_reuse_appends_exactly_one_day_coverage(root: Path) -> None:
    before = lines(root)
    reference = record_event(root)
    result = run(root, reference=reference)
    assert result.outcome is O.APPENDED and result.reasons == () and result.review == ()
    assert result.active_codes == 1 and result.unregistered_codes == 0 and result.event_reference == reference
    after = lines(root)
    assert after[:-1] == before and len(after) == len(before) + 1                           # 追記は 1 行だけ
    coverage = history(root).coverages[-1]
    assert coverage.record_id == result.coverage_record_id and coverage.KIND is RecordKind.COVERAGE
    assert coverage.scope is CoverageScope.JP_LISTED_EQUITY_IDENTITY
    assert coverage.effective_from == datetime(2026, 7, 2, tzinfo=TOKYO)                   # T 00:00 JST
    assert coverage.effective_to == datetime(2026, 7, 3, tzinfo=TOKYO)                     # T＋1 日（ちょうど 1 日）
    assert coverage.provenance.source_class is SourceClass.JQUANTS
    assert coverage.provenance.source_record_ref == reference and coverage.provenance.known_at == ACQUIRED
    assert coverage == cc.coverage_for_day(T, reference, ACQUIRED)
    assert status_at(root, datetime(2026, 7, 2, 18, 0, 1, tzinfo=TOKYO)) is ResolutionStatus.FOUND
    assert status_at(root, datetime(2026, 7, 2, 12, tzinfo=TOKYO)) is ResolutionStatus.NOT_YET_KNOWN   # 取得の前
    assert status_at(root, datetime(2026, 7, 1, 12, tzinfo=TOKYO)) is ResolutionStatus.NOT_YET_KNOWN   # gap の日（厳密 PIT）
    assert result.as_dict()["outcome"] == "APPENDED" and result.as_dict()["day"] == "2026-07-02"


def test_a_exact_rerun_is_reused_and_writes_nothing(root: Path) -> None:
    reference = record_event(root)
    first = run(root, reference=reference)
    before = lines(root)
    again = run(root, reference=reference)
    assert again.outcome is O.REUSED and again.coverage_record_id == first.coverage_record_id
    assert lines(root) == before and again.as_dict()["reasons"] == []
    third = run(root, reference=reference)                                                  # 決定論 ・replay
    assert third.as_dict() == again.as_dict()


def test_a_unregistered_codes_elsewhere_in_the_market_do_not_block_the_day(root: Path) -> None:
    rows = [snap(), snap("25010", CoName="別の合成"), snap("13500", CoName="ETF 合成", ProdCat="051")]
    reference = record_event(root, rows=rows)
    result = run(root, rows=rows, reference=reference)
    assert result.outcome is O.APPENDED and result.unregistered_codes == 2 and result.review == ()
    assert len(history(root).issuers) == 1                                                 # identity は作らない


# ================================================================ B 取得 event の検査


@pytest.mark.parametrize("status,pagination,failure_code,reason", [
    (AcquisitionStatus.EMPTY, False, "", R.ACQUISITION_EMPTY),
    (AcquisitionStatus.PARTIAL_PAGINATED, True, "", R.ACQUISITION_PARTIAL_PAGINATED),
    (AcquisitionStatus.FAILED, False, "HTTP_STATUS_503", R.ACQUISITION_FAILED)])
def test_b_incomplete_acquisitions_never_create_coverage(root: Path, status, pagination, failure_code, reason) -> None:
    rows = [] if status is not AcquisitionStatus.PARTIAL_PAGINATED else [snap()]
    reference = record_event(root, rows=rows, status=status, pagination=pagination, failure_code=failure_code)
    before = lines(root)
    result = run(root, rows=rows, reference=reference)
    assert result.outcome is O.ACQUISITION_NOT_COMPLETE and result.reasons == (reason,)
    assert lines(root) == before and len(history(root).coverages) == 1


def test_b_event_missing_mismatched_or_tampered_inputs_fail_closed(root: Path) -> None:
    before = lines(root)
    missing = run(root, reference="jq.acq:" + "0" * 24)
    assert missing.outcome is O.ACQUISITION_MISMATCH and missing.reasons == (R.EVENT_NOT_FOUND,)
    fins = record_event(root, endpoint=FINS_SUMMARY_PATH)
    assert run(root, reference=fins).reasons == (R.EVENT_ENDPOINT_MISMATCH, R.CONTENT_DIGEST_MISMATCH)
    other_day = record_event(root, day=date(2026, 7, 3), rows=[snap(day=date(2026, 7, 3))])
    wrong_day = run(root, reference=other_day)                                              # event の日 ≠ T
    assert wrong_day.outcome is O.ACQUISITION_MISMATCH and R.EVENT_DATE_MISMATCH in wrong_day.reasons
    reference = record_event(root)
    tampered = run(root, rows=[snap(CoName="改ざん")], reference=reference)                # 行が event と違う
    assert tampered.outcome is O.ACQUISITION_MISMATCH and tampered.reasons == (R.CONTENT_DIGEST_MISMATCH,)
    unbounded = run(root, rows=[{**snap(), "S17": "1"}], reference=reference)
    assert unbounded.reasons == (R.ROWS_NOT_BOUNDED,)
    assert lines(root) == before
    with pytest.raises(ContinuityError):
        run(root, reference="not-a-reference")
    with pytest.raises(ContinuityError):
        execute_identity_continuity(data_root=root, day="2026-07-02", rows=[snap()], event_reference=reference,
                                    supported_markets=MARKETS)
    with pytest.raises(ContinuityError):
        run(root, reference=reference, markets=())


# ================================================================ C 2 時刻 ・人の審査の遅れ


def test_c_identity_not_yet_known_at_acquisition_time_gives_no_coverage(root: Path) -> None:
    early = ACCEPTED - timedelta(hours=1)                                                   # 審査の受理より前の取得
    day = date(2026, 6, 29)
    reference = record_event(root, day=day, rows=[snap(day=day)], acquired=early)
    result = run(root, day=day, rows=[snap(day=day)], reference=reference)
    assert result.outcome is O.IDENTITY_SCOPE_UNRESOLVED and result.reasons == (R.IDENTITY_NOT_KNOWN_BY_ACQUISITION,)
    assert len(history(root).coverages) == 1


def test_c_delayed_human_review_is_structurally_usable_and_known_at_is_never_backdated(root: Path) -> None:
    accepted = history(root).issuers[issuer_of(root)].known_at
    assert accepted == ACCEPTED and accepted > datetime(2026, 7, 1, tzinfo=TOKYO)           # 審査は D0 の後
    d0_coverage = history(root).coverages[0]
    reference = record_event(root)
    assert run(root, reference=reference).outcome is O.APPENDED
    coverages = history(root).coverages
    assert coverages[0] == d0_coverage and len(coverages) == 2                             # D0 の coverage は書き直さない
    assert coverages[1].known_at == ACQUIRED and coverages[1].known_at >= accepted
    assert status_at(root, datetime(2026, 7, 2, 19, tzinfo=TOKYO)) is ResolutionStatus.FOUND
    assert status_at(root, datetime(2026, 6, 30, 20, tzinfo=TOKYO)) is ResolutionStatus.NOT_YET_KNOWN  # 人はまだ知らない


def test_c_authority_known_after_acquisition_is_refused(root: Path) -> None:
    later_day = date(2026, 7, 3)
    later = record_event(root, day=later_day, rows=[snap(day=later_day)], acquired=ACQUIRED + timedelta(days=1))
    assert run(root, day=later_day, rows=[snap(day=later_day)], reference=later).outcome is O.APPENDED
    reference = record_event(root)                                                          # T の取得 event（古い known_at）
    result = run(root, reference=reference)
    assert result.outcome is O.IDENTITY_SCOPE_UNRESOLVED and result.reasons == (R.AUTHORITY_KNOWN_AFTER_ACQUISITION,)
    assert len(history(root).coverages) == 2                                               # T は埋めない（gap のまま）


# ================================================================ D gap ・橋なし


def test_d_failed_day_stays_a_gap_and_intervals_are_never_bridged(root: Path) -> None:
    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    failed = record_event(root, day=d1, rows=[], status=AcquisitionStatus.FAILED, failure_code="NETWORK_ERROR",
                          acquired=datetime(2026, 7, 1, 18, tzinfo=TOKYO))
    assert run(root, day=d1, rows=[], reference=failed).outcome is O.ACQUISITION_NOT_COMPLETE
    passed = record_event(root, day=d2, rows=[snap(day=d2)])
    assert run(root, day=d2, rows=[snap(day=d2)], reference=passed).outcome is O.APPENDED
    coverages = history(root).coverages
    assert [(c.effective_from, c.effective_to) for c in coverages] == [
        (datetime(2026, 6, 30, tzinfo=TOKYO), datetime(2026, 7, 1, tzinfo=TOKYO)),
        (datetime(2026, 7, 2, tzinfo=TOKYO), datetime(2026, 7, 3, tzinfo=TOKYO))]
    assert all(c.effective_to - c.effective_from == timedelta(days=1) for c in coverages)  # [D0, D3) は無い
    assert status_at(root, datetime(2026, 7, 1, 12, tzinfo=TOKYO)) is ResolutionStatus.NOT_YET_KNOWN   # D1 は gap
    assert status_at(root, datetime(2026, 7, 2, 19, tzinfo=TOKYO)) is ResolutionStatus.FOUND
    assert status_at(root, datetime(2026, 7, 3, 12, tzinfo=TOKYO)) is ResolutionStatus.NOT_YET_KNOWN  # 未確認の日


def test_d_the_bootstrap_day_itself_conflicts_with_a_differently_provenanced_coverage(root: Path) -> None:
    reference = record_event(root, day=D0, rows=[snap(day=D0)], acquired=ACCEPTED)
    result = run(root, day=D0, rows=[snap(day=D0)], reference=reference)
    assert result.outcome is O.COVERAGE_CONFLICT and result.reasons == (R.EXISTING_COVERAGE_DIFFERENT_PROVENANCE,)
    assert len(history(root).coverages) == 1


# ================================================================ E 変化 ・人の審査


def test_e_active_registered_code_missing_from_the_snapshot_requires_review(root: Path) -> None:
    rows = [snap("25010", CoName="別の合成")]
    reference = record_event(root, rows=rows)
    result = run(root, rows=rows, reference=reference)
    assert result.outcome is O.REVIEW_REQUIRED and result.reasons == (R.IDENTITY_CHANGE_SUSPECTED,)
    assert [(i.code, i.origin, i.disposition, i.reasons) for i in result.review] == [
        ("13010", ReviewOrigin.ID1_CLASSIFICATION, "HUMAN_REVIEW_REQUIRED", ("CODE_ABSENT_FROM_SNAPSHOT",))]
    assert result.review[0].existing_issuer_id == issuer_of(root) and len(history(root).coverages) == 1


def test_e_new_code_related_to_a_registered_identity_requires_review(root: Path) -> None:
    rows = [snap(), snap("13015", CoName="合成 一号 優先")]                                   # 同じ先頭 4 桁 → 複数の上場物の疑い
    reference = record_event(root, rows=rows)
    result = run(root, rows=rows, reference=reference)
    assert result.outcome is O.REVIEW_REQUIRED
    assert any(i.code == "13010" and "MULTIPLE_LISTINGS_SUSPECTED" in i.reasons for i in result.review)
    assert len(history(root).coverages) == 1 and len(history(root).issuers) == 1          # identity を作らない


def test_e_market_change_or_product_category_change_of_a_registered_code_requires_review(root: Path) -> None:
    moved = [snap(Mkt="0109")]
    reference = record_event(root, rows=moved)
    result = run(root, rows=moved, reference=reference)
    assert result.outcome is O.REVIEW_REQUIRED
    origins = {(i.origin, i.disposition) for i in result.review}
    assert (ReviewOrigin.LIVE1_ELIGIBILITY, "HOLD") in origins and all(i.code == "13010" for i in result.review)
    excluded = [snap(ProdCat="021")]
    assert run(root, rows=excluded, reference=record_event(root, rows=excluded)).outcome is O.REVIEW_REQUIRED
    assert len(history(root).coverages) == 1


def test_e_retired_or_ended_identities_follow_frozen_id1_semantics(root: Path) -> None:
    records = list(ist.IdentityStore.open(root).records())
    listing = next(r for r in records if r.KIND is RecordKind.LISTING_START)
    provenance = SourceProvenance(source_class=SourceClass.JQUANTS, source_record_ref="jq.eq_master:end",
                                  known_at=ACCEPTED)
    ended = ListingEnd(listing_record_id=listing.record_id, effective_to=datetime(2026, 7, 1, tzinfo=TOKYO),
                       reason=ListingEndReason.DELISTED, provenance=provenance)
    rewrite(root, records + [ended])
    absent = record_event(root, rows=[snap("25010", CoName="別の合成")])
    result = run(root, rows=[snap("25010", CoName="別の合成")], reference=absent)           # 終わった identity は居なくてよい
    assert result.outcome is O.IDENTITY_SCOPE_UNRESOLVED and result.reasons == (R.NO_ACTIVE_REGISTERED_IDENTITY,)
    present = record_event(root, rows=[snap()])
    relisted = run(root, rows=[snap()], reference=present)                                 # 現れれば再上場の疑い
    assert relisted.outcome is O.REVIEW_REQUIRED
    assert relisted.review[0].reasons == ("LISTING_ENDED_IN_AUTHORITY",)
    assignment = next(r for r in records if r.KIND is RecordKind.IDENTIFIER_ASSIGNMENT)
    retired = IdentifierRetirement(assignment_record_id=assignment.record_id,
                                   effective_to=datetime(2026, 7, 1, tzinfo=TOKYO), reason=RetirementReason.REPLACED,
                                   provenance=provenance)
    rewrite(root, records + [retired])
    retired_present = run(root, rows=[snap()], reference=present)
    assert retired_present.outcome is O.REVIEW_REQUIRED
    assert retired_present.review[0].reasons == ("CODE_PREVIOUSLY_RETIRED",)
    assert len(history(root).coverages) == 1


def test_e_identity_conflicts_never_yield_coverage(root: Path) -> None:
    records = list(ist.IdentityStore.open(root).records())
    security = next(r for r in records if r.KIND is RecordKind.SECURITY_REGISTRATION)
    provider = SourceProvenance(source_class=SourceClass.JQUANTS, source_record_ref="jq.eq_master:x",
                                known_at=ACCEPTED)
    duplicate = IdentifierAssignment(security_id=security.security_id, scheme=IdentifierScheme.JQUANTS_CODE,
                                     value="13020", effective_from=datetime(2026, 6, 30, tzinfo=TOKYO),
                                     provenance=provider)
    rewrite(root, records + [duplicate])                                                    # 同じ Security に 2 つ目の code
    reference = record_event(root, rows=[snap()])
    doubled = run(root, rows=[snap()], reference=reference)
    assert doubled.outcome is O.STORE_FAILURE and doubled.failure_code == "INVALID_HISTORY"   # 凍結 A1 が履歴ごと拒む
    human = SourceProvenance(source_class=SourceClass.HUMAN_REVIEWED, source_record_ref="review:manual",
                             known_at=ACCEPTED)
    issuer = IssuerRegistration(registration_anchor="manual:iss.x1", provenance=human)
    other = SecurityRegistration(registration_anchor="manual:sec.x1", issuer_id=issuer.issuer_id,
                                 issue_class=IssueClass.COMMON_EQUITY, provenance=human)
    bound = IdentifierAssignment(security_id=other.security_id, scheme=IdentifierScheme.JQUANTS_CODE, value="13020",
                                 effective_from=datetime(2026, 6, 30, tzinfo=TOKYO), provenance=provider)
    rewrite(root, records + [issuer, other, bound])                                         # bootstrap でない anchor の結び
    rows = [snap(), snap("13020", CoName="合成 二号")]
    reference = record_event(root, rows=rows)
    result = run(root, rows=rows, reference=reference)
    assert result.outcome is O.IDENTITY_SCOPE_UNRESOLVED and result.reasons == (R.ANCHOR_NOT_BOOTSTRAP,)
    assert len(history(root).coverages) == 1


def test_e_two_batches_are_each_checked_with_their_own_anchor(root: Path) -> None:
    second = BootstrapBatch(batch_id="p8boot2", d0=D0, supported_markets=MARKETS)
    rows2 = [master("13020", "合成 二号", "", "0112")]
    assert register(root, rows2, reviewed=reviewed_for(rows2, batch=second), batch=second).outcome.value == "APPENDED"
    rows = [snap(), snap("13020", CoName="合成 二号", CoNameEn="", Mkt="0112")]
    reference = record_event(root, rows=rows)
    result = run(root, rows=rows, reference=reference)
    assert result.outcome is O.APPENDED and result.active_codes == 2
    missing_second = [snap()]
    reference = record_event(root, day=date(2026, 7, 3), rows=[snap(day=date(2026, 7, 3))],
                             acquired=ACQUIRED + timedelta(days=1))
    result = run(root, day=date(2026, 7, 3), rows=[snap(day=date(2026, 7, 3))], reference=reference)
    assert result.outcome is O.REVIEW_REQUIRED and [i.code for i in result.review] == ["13020"]
    assert missing_second and len(history(root).coverages) == 2


# ================================================================ F store ・architecture


def test_f_store_failures_are_typed_and_write_nothing(root: Path, tmp_path: Path) -> None:
    reference = record_event(root)
    path = root / "screener_intelligence" / "identity_records.jsonl"
    before = path.read_bytes()
    with path.open("ab") as handle:
        handle.write(b'{"record_kind": "GARBAGE"}\n')
    result = run(root, reference=reference)
    assert result.outcome is O.STORE_FAILURE and result.reasons == (R.STORE_ERROR,) and result.failure_code != ""
    assert path.read_bytes() == before + b'{"record_kind": "GARBAGE"}\n'                    # 修復 ・削除しない
    empty = tmp_path / "no_acq"
    ist.IdentityStore.initialize(empty)
    missing = run(empty, reference=reference)
    assert missing.outcome is O.STORE_FAILURE and missing.failure_code == "STORE_MISSING"


def test_f_the_writer_appends_coverage_only_and_touches_no_other_store(root: Path) -> None:
    before = {p.name for p in (root / "screener_intelligence").iterdir()}
    reference = record_event(root)
    kinds_before = [r.KIND for r in ist.IdentityStore.open(root).records()]
    run(root, reference=reference)
    kinds_after = [r.KIND for r in ist.IdentityStore.open(root).records()]
    assert kinds_after == kinds_before + [RecordKind.COVERAGE]
    assert {p.name for p in (root / "screener_intelligence").iterdir()} == before
    source = executable_source(PACKAGE_DIR / "identity_continuity_coverage.py")
    for token in ("IssuerRegistration(", "SecurityRegistration(", "IdentifierAssignment(", "DisplayName(",
                  "ListingStart(", "ListingEnd(", "IdentifierRetirement(", "ObservationStore", "ObservationCoverage",
                  "FundamentalActual", "plan_registration", "execute_identity_registration"):
        assert token not in source, token
    assert source.count("Coverage(") == 1                                                   # 作る record は Coverage だけ


def test_f_architecture_no_fallback_fuzzy_llm_network_or_clock() -> None:
    source = executable_source(PACKAGE_DIR / "identity_continuity_coverage.py")
    lowered = source.lower()
    for token in ("fallback", "fuzzy", "similar", "levenshtein", "difflib", "llm", "prompt", "anthropic", "openai",
                  "urllib", "socket", "http", "://", "now(", "utcnow", "today(", "pathlib", "import os"):
        assert token not in lowered, token
    assert not re.search(r"(?<![.\w])open\(", source)                                       # 自分では file を開かない
    tree = ast.parse((PACKAGE_DIR / "identity_continuity_coverage.py").read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported == {"acquisition_event_model", "acquisition_event_store", "identity_bootstrap",
                        "identity_bootstrap_model", "identity_model", "identity_store", "jquants_adapter_model",
                        "jquants_live_model", "jquants_master_ingress", "dataclasses", "datetime", "enum", "typing",
                        "__future__"}
    assert cc.CONTINUITY_CONDITION == "ALL_RELEVANT_REGISTERED_IDENTITIES_REUSE"
    assert [o.value for o in ContinuityOutcome] == ["APPENDED", "REUSED", "REVIEW_REQUIRED", "ACQUISITION_NOT_COMPLETE",
                                                    "ACQUISITION_MISMATCH", "IDENTITY_SCOPE_UNRESOLVED",
                                                    "COVERAGE_CONFLICT", "STORE_FAILURE"]
    for path in (REPO_ROOT / "src" / "intelligence" / "jquants_pilot2_local.py", REPO_ROOT / "main.py"):
        assert "identity_continuity" not in path.read_text(encoding="utf-8"), path.name  # 配線は後の gate
