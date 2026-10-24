"""P8-ID2 — 人が承認した identity の登録 executor の test matrix（happy ・信頼 ・A1 の現在の状態 ・D0 ・部分失敗 ・破損 ・architecture）。

書く先は tmp_path の private root の A1 store だけ。合成の master の行だけ。J-Quants ・network ・時計 ・乱数 ・LLM は使わない。
A1 ・ID1 の module は変えない。
"""
from __future__ import annotations

import ast
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence.identity_bootstrap import (plan_registration, propose_bootstrap,
                                                                       review_manifest)
from src.intelligence.screener_intelligence.identity_bootstrap_model import (BootstrapBatch, BootstrapInputError,
                                                                             ProposalReview, ReviewDisposition,
                                                                             ReviewedManifest)
from src.intelligence.screener_intelligence.identity_model import (Coverage, CoverageScope, DisplayName,
                                                                   IdentifierAssignment, IdentifierRetirement,
                                                                   IdentifierScheme, IdentityHistory, IssueClass,
                                                                   IssuerRegistration, ListingEnd, ListingEndReason,
                                                                   ListingStart, ListingVenue, NameKind, NameLanguage,
                                                                   RecordKind, RetirementReason, SecurityRegistration,
                                                                   SourceClass, SourceProvenance, SubjectKind)
from src.intelligence.screener_intelligence.identity_registration_executor import execute_identity_registration
from src.intelligence.screener_intelligence.identity_registration_model import (RegistrationModelError,
                                                                                RegistrationOutcome,
                                                                                RegistrationReason,
                                                                                RegistrationResult, WriteState)
from src.intelligence.screener_intelligence.identity_resolver import IdentityQuery, ResolutionStatus, resolve
from src.intelligence.screener_intelligence.observation_model import TOKYO
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_identity_bootstrap import master

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
D0 = date(2026, 6, 30)
BATCH = BootstrapBatch(batch_id="p8boot1", d0=D0, supported_markets=("0111", "0112", "0113"))
ACCEPTED = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
ONE = [master()]
TWO = [master(), master("13020", "合成 二号", "", "0112")]
O = RegistrationOutcome
R = RegistrationReason


@pytest.fixture
def root(tmp_path: Path) -> Path:
    private = tmp_path / "private_root"
    ist.IdentityStore.initialize(private)
    return private


def reviewed_for(rows, batch=BATCH, disposition=ReviewDisposition.APPROVE, accepted=ACCEPTED, only=None):
    manifest = propose_bootstrap(rows, batch)
    reviews = [ProposalReview(proposal_id=p.proposal_id, proposal_digest=p.digest, disposition=disposition)
               for p in manifest.proposals if only is None or p.code in only]
    return review_manifest(manifest, reviews, accepted_at=accepted)


def run(root: Path, rows, reviewed=None, batch=BATCH, prior=None) -> RegistrationResult:
    return execute_identity_registration(rows, batch, reviewed or reviewed_for(rows), root, prior_plan=prior)


def lines(root: Path) -> list:
    return (root / "screener_intelligence" / "identity_records.jsonl").read_text(encoding="utf-8").splitlines()


def bundle_states(result: RegistrationResult) -> list:
    return [b.state.value for b in result.bundles]


# ================================================================ happy path


def test_happy_one_approved_bundle_is_appended_in_a1_order(root: Path) -> None:
    result = run(root, ONE)
    assert result.outcome is O.APPENDED and result.reasons == () and bundle_states(result) == ["APPENDED"]
    kinds = [w.kind.value for w in result.bundles[0].writes]
    assert kinds == ["ISSUER_REGISTRATION", "SECURITY_REGISTRATION", "IDENTIFIER_ASSIGNMENT", "DISPLAY_NAME",
                     "DISPLAY_NAME", "DISPLAY_NAME", "LISTING_START"]
    assert [c.kind.value for c in result.coverage] == ["COVERAGE"] and result.coverage[0].state is WriteState.APPENDED
    assert len(result.writes.appended) == 8 and result.writes.reused == () and len(lines(root)) == 8
    store = ist.IdentityStore.open(root)
    assert [r.KIND.value for r in store.records()] == kinds + ["COVERAGE"]                 # store の順 ＝ 書いた順
    assert set(result.writes.appended) == {r.record_id for r in store.records()}
    issuer = store.records()[0]
    assert issuer.provenance.source_class is SourceClass.HUMAN_REVIEWED and issuer.known_at == ACCEPTED
    assert result.bundles[0].issuer_id == issuer.issuer_id and result.bundles[0].code == "13010"
    assert result.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
    assert result.rules_version == "p8_identity_registration:0.1.0"
    assert len(result.manifest_digest) == len(result.reviewed_digest) == len(result.plan_digest) == 64


def test_happy_multiple_bundles_and_exact_replay_is_reused(root: Path) -> None:
    first = run(root, TWO)
    assert first.outcome is O.APPENDED and bundle_states(first) == ["APPENDED", "APPENDED"]
    assert len(first.writes.appended) == 14 and len(lines(root)) == 14
    again = run(root, TWO)
    assert again.outcome is O.REUSED and bundle_states(again) == ["REUSED", "REUSED"]
    assert again.writes.appended == () and set(again.writes.reused) == set(first.writes.appended)
    assert again.coverage[0].state is WriteState.REUSED and len(lines(root)) == 14
    reopened = ist.IdentityStore.open(root)                                                # store を開き直して replay
    assert len(reopened.records()) == 14
    assert run(root, TWO).outcome is O.REUSED and len(lines(root)) == 14
    assert run(root, list(reversed(TWO))).outcome is O.REUSED                              # 行の順序に依らない


@pytest.mark.parametrize("disposition", [ReviewDisposition.REJECT, ReviewDisposition.DEFER])
def test_happy_reject_and_defer_produce_no_writes(root: Path, disposition: ReviewDisposition) -> None:
    result = run(root, TWO, reviewed_for(TWO, disposition=disposition))
    assert result.outcome is O.NO_AUTHORIZED_ITEMS and result.bundles == () and lines(root) == []


def test_happy_unreviewed_and_partially_reviewed(root: Path) -> None:
    unreviewed = review_manifest(propose_bootstrap(TWO, BATCH), [], accepted_at=ACCEPTED)
    assert run(root, TWO, unreviewed).outcome is O.NO_AUTHORIZED_ITEMS and lines(root) == []
    partial = run(root, TWO, reviewed_for(TWO, only=("13020",)))
    assert partial.outcome is O.APPENDED and [b.code for b in partial.bundles] == ["13020"] and len(lines(root)) == 7
    none = execute_identity_registration(TWO, BATCH, None, root)                            # type: ignore[arg-type]
    assert none.outcome is O.REJECTED and none.reasons == (R.INVALID_INPUT,)


# ================================================================ trust / revalidation


def test_trust_execution_reruns_id1_and_accepts_only_a_matching_prior_plan(root: Path) -> None:
    manifest = propose_bootstrap(ONE, BATCH)
    reviewed = reviewed_for(ONE)
    plan = plan_registration(manifest, reviewed)
    result = run(root, ONE, reviewed, prior=plan)
    assert result.outcome is O.APPENDED and result.plan_digest == plan.plan_digest
    forged = plan_registration(manifest, reviewed_for(ONE, accepted=ACCEPTED + timedelta(hours=1)))
    rejected = run(root, ONE, reviewed, prior=forged)
    assert rejected.outcome is O.REJECTED and rejected.reasons == (R.PRIOR_PLAN_MISMATCH,) and len(lines(root)) == 8
    stale = plan_registration(propose_bootstrap([master(name="合成 一号 改")], BATCH),
                              reviewed_for([master(name="合成 一号 改")]))
    assert run(root, ONE, reviewed, prior=stale).reasons == (R.PRIOR_PLAN_MISMATCH,)
    assert run(root, ONE, reviewed, prior={"plan": 1}).reasons == (R.INVALID_INPUT,)         # type: ignore[arg-type]


def test_trust_changed_proposal_manifest_or_review_binding_is_rejected_without_writes(root: Path) -> None:
    reviewed = reviewed_for(ONE)
    changed = run(root, [master(name="合成 一号 改")], reviewed)                              # 審査の後に提案が変わった
    assert changed.outcome is O.REJECTED and changed.reasons == (R.MANIFEST_DIGEST_MISMATCH,)
    grown = run(root, TWO, reviewed)                                                        # manifest が変わった
    assert grown.outcome is O.REJECTED and grown.reasons == (R.MANIFEST_DIGEST_MISMATCH,)
    manifest = propose_bootstrap(TWO, BATCH)
    other = propose_bootstrap([master(name="合成 一号 改")], BATCH).proposals[0]
    rebound = ReviewedManifest(manifest_digest=manifest.manifest_digest, accepted_at=ACCEPTED, reviews=(
        ProposalReview(proposal_id=other.proposal_id, proposal_digest=other.digest,
                       disposition=ReviewDisposition.APPROVE),))                            # 別の提案への審査を結び付ける
    binding = run(root, TWO, rebound)
    assert binding.outcome is O.REJECTED and binding.reasons == (R.REVIEW_BINDING_INVALID,)
    assert lines(root) == []


def test_trust_non_human_review_and_naive_accepted_at_are_rejected(root: Path) -> None:
    manifest = propose_bootstrap(ONE, BATCH)
    with pytest.raises(BootstrapInputError):                                               # model が HUMAN 以外を拒む
        ReviewedManifest(manifest_digest=manifest.manifest_digest, reviews=(), accepted_at=ACCEPTED,
                         reviewer_class="MACHINE")                                          # type: ignore[arg-type]
    with pytest.raises(BootstrapInputError):
        ReviewedManifest(manifest_digest=manifest.manifest_digest, reviews=(), accepted_at=datetime(2026, 7, 1))
    assert run(root, ONE, {"reviewer_class": "HUMAN"}).reasons == (R.INVALID_INPUT,)      # type: ignore[arg-type]
    assert execute_identity_registration(ONE, {"d0": "2026-06-30"}, reviewed_for(ONE), root).reasons == (
        R.INVALID_INPUT,)
    assert execute_identity_registration(ONE, BATCH, reviewed_for(ONE), "").failure_code == "DATA_ROOT_REQUIRED"
    assert lines(root) == []


def test_accepted_at_is_review_metadata_preserved_through_revalidation(root: Path) -> None:
    result = run(root, ONE)
    for record in ist.IdentityStore.open(root).records():
        assert record.known_at == ACCEPTED                                                 # 実行の時刻ではない
        effective = record.__dict__.get("effective_from")
        assert effective is None or effective == datetime(2026, 6, 30, tzinfo=TOKYO)       # D0 ≠ accepted_at
    assert result.outcome is O.APPENDED
    for name in ("identity_registration_model", "identity_registration_executor"):
        assert "datetime(" not in executable_source(PACKAGE_DIR / f"{name}.py")


# ================================================================ A1 current state


def registered_history(root: Path, rows=ONE):
    run(root, rows)
    return list(ist.IdentityStore.open(root).records())


def rewrite(root: Path, records) -> None:
    """test の道具: 合成の A1 の履歴を store の file に置き直す（executor はこれをしない）。"""
    path = root / "screener_intelligence" / "identity_records.jsonl"
    path.write_text("".join(r.canonical_line() for r in records), encoding="utf-8")


def test_a1_empty_store_then_exact_reuse_then_conflicts_are_typed(root: Path) -> None:
    records = registered_history(root)
    assert run(root, ONE).outcome is O.REUSED
    other_batch = BootstrapBatch(batch_id="p8boot2", d0=D0, supported_markets=("0111",))
    conflict = run(root, ONE, reviewed_for(ONE, other_batch), other_batch)                # 同じ code を別の identity に
    assert conflict.outcome is O.REJECTED and conflict.reasons == (R.CODE_BOUND_TO_OTHER_IDENTITY,)
    later = SourceProvenance(source_class=SourceClass.HUMAN_REVIEWED, source_record_ref="review:other-1",
                             known_at=ACCEPTED - timedelta(days=1))
    issuer = records[0]
    foreign_issuer = IssuerRegistration(registration_anchor=issuer.registration_anchor, provenance=later)
    rewrite(root, [foreign_issuer])                                            # 同じ anchor ・別の出所 → 同じ identity
    result = run(root, ONE)
    assert result.outcome is O.APPENDED and result.bundles[0].writes[0].state is WriteState.REUSED
    assert result.bundles[0].writes[0].record_id == foreign_issuer.record_id and len(lines(root)) == 8
    assert result.writes.reused == (foreign_issuer.record_id,)
    other_issuer = IssuerRegistration(registration_anchor="p8boot9:iss.99990", provenance=later)
    foreign_security = SecurityRegistration(registration_anchor=records[1].registration_anchor,
                                            issuer_id=other_issuer.issuer_id, issue_class=IssueClass.COMMON_EQUITY,
                                            provenance=later)
    rewrite(root, [other_issuer, foreign_security, issuer])                                # Security が別の Issuer に
    relation = run(root, ONE)
    assert relation.outcome is O.REJECTED and relation.reasons == (R.ISSUER_SECURITY_RELATION_CONFLICT,)
    assert len(lines(root)) == 3


def test_a1_display_name_listing_coverage_and_retired_code_conflicts(root: Path) -> None:
    records = registered_history(root)
    issuer, security = records[0], records[1]
    earlier = SourceProvenance(source_class=SourceClass.JQUANTS, source_record_ref="jq.eq_master:other",
                               known_at=ACCEPTED)
    d0 = datetime(2026, 6, 30, tzinfo=TOKYO)
    name = DisplayName(subject_kind=SubjectKind.ISSUER, subject_id=issuer.issuer_id, name_kind=NameKind.ISSUER_NAME,
                       language=NameLanguage.JA, value="別の名前", effective_from=d0, provenance=earlier)
    rewrite(root, [issuer, security, name])
    result = run(root, ONE)
    assert result.reasons == (R.DISPLAY_NAME_CONFLICT,) and result.outcome is O.REJECTED and len(lines(root)) == 3
    listing = ListingStart(security_id=security.security_id, venue=ListingVenue.TSE,
                           effective_from=d0 - timedelta(days=10), provenance=earlier)
    rewrite(root, [issuer, security, listing])
    assert run(root, ONE).reasons == (R.LISTING_CONFLICT,)
    same_listing = ListingStart(security_id=security.security_id, venue=ListingVenue.TSE, effective_from=d0,
                                provenance=earlier)
    rewrite(root, [issuer, security, same_listing])                                        # 同じ上場 ・別の出所 → 再利用
    same = run(root, ONE)
    assert same.outcome is O.APPENDED and same.bundles[0].writes[-1].record_id == same_listing.record_id
    ended = ListingEnd(listing_record_id=listing.record_id, effective_to=d0 - timedelta(days=1),
                       reason=ListingEndReason.DELISTED, provenance=earlier)
    rewrite(root, [issuer, security, listing, ended])
    assert run(root, ONE).reasons == (R.LISTING_ENDED,)
    coverage = Coverage(scope=CoverageScope.JP_LISTED_EQUITY_IDENTITY, effective_from=d0 - timedelta(days=1),
                        effective_to=d0 + timedelta(hours=12), provenance=earlier)
    rewrite(root, [coverage])
    assert run(root, ONE).reasons == (R.COVERAGE_CONFLICT,) and len(lines(root)) == 1
    same_interval = Coverage(scope=CoverageScope.JP_LISTED_EQUITY_IDENTITY, effective_from=d0,
                             effective_to=d0 + timedelta(days=1), provenance=earlier)
    rewrite(root, [same_interval])
    reused_coverage = run(root, ONE)                                                       # 同じ区間 → coverage は再利用
    assert reused_coverage.outcome is O.APPENDED and reused_coverage.coverage[0].state is WriteState.REUSED
    assert reused_coverage.coverage[0].record_id == same_interval.record_id and len(lines(root)) == 8
    assignment = IdentifierAssignment(security_id=security.security_id, scheme=IdentifierScheme.JQUANTS_CODE,
                                      value="13010", effective_from=d0 - timedelta(days=30), provenance=earlier)
    retired = IdentifierRetirement(assignment_record_id=assignment.record_id, effective_to=d0 - timedelta(days=1),
                                   reason=RetirementReason.REPLACED, provenance=earlier)
    rewrite(root, [issuer, security, assignment, retired])
    assert run(root, ONE).reasons == (R.RETIRED_CODE_AMBIGUITY,) and len(lines(root)) == 4
    late = SourceProvenance(source_class=SourceClass.HUMAN_REVIEWED, source_record_ref="review:late",
                            known_at=ACCEPTED + timedelta(days=1))
    rewrite(root, [IssuerRegistration(registration_anchor="p8boot9:iss.99990", provenance=late)])
    assert run(root, ONE).reasons == (R.KNOWN_AT_NOT_MONOTONIC,)


def test_a1_preflight_conflict_in_a_later_bundle_causes_zero_writes(root: Path) -> None:
    other_batch = BootstrapBatch(batch_id="p8boot2", d0=D0, supported_markets=("0111", "0112"))
    run(root, [master("13020", "合成 二号", "", "0112")], reviewed_for([master("13020", "合成 二号", "", "0112")],
                                                                other_batch), other_batch)
    before = lines(root)
    result = run(root, TWO)                                                                 # 13010 は新規 ・13020 は衝突
    assert result.outcome is O.REJECTED and result.reasons == (R.CODE_BOUND_TO_OTHER_IDENTITY,)
    assert result.bundles == () and lines(root) == before


# ================================================================ D0 / coverage lock


def test_d0_snapshot_coverage_is_not_identity_validity(root: Path) -> None:
    run(root, ONE)
    history = ist.IdentityStore.open(root).history
    issuer_id = next(iter(history.issuers))
    assert not history.listing_ends and not history.retirements                            # 上場の終わり ・退役は無い
    coverage = history.coverages[0]
    assert (coverage.effective_from, coverage.effective_to) == (datetime(2026, 6, 30, tzinfo=TOKYO),
                                                                datetime(2026, 7, 1, tzinfo=TOKYO))
    same_day = reviewed_for(ONE, accepted=datetime(2026, 6, 30, 19, tzinfo=TOKYO))         # D0 の当日に受理された審査
    history = IdentityHistory(plan_registration(propose_bootstrap(ONE, BATCH), same_day).records)
    at_d0 = resolve(history, IdentityQuery.for_issuer(issuer_id), cutoff=datetime(2026, 6, 30, 20, tzinfo=TOKYO))
    assert at_d0.status is ResolutionStatus.FOUND
    after = resolve(history, IdentityQuery.for_issuer(issuer_id), cutoff=datetime(2026, 7, 5, tzinfo=TOKYO))
    assert after.status is ResolutionStatus.NOT_YET_KNOWN                                  # 「無い」でも「廃止」でもない
    before = resolve(history, IdentityQuery.for_issuer(issuer_id), cutoff=datetime(2026, 6, 1, tzinfo=TOKYO))
    assert before.status is not ResolutionStatus.FOUND                                     # D0 より前は作らない
    assert all(r.KIND is not RecordKind.LISTING_END for r in history.records)
    for record in history.records:
        assert record.__dict__.get("effective_from", coverage.effective_from) >= coverage.effective_from
    assert len(history.coverages) == 1                                                     # 継続の coverage を作らない


# ================================================================ partial failure


def test_partial_failure_after_first_append_then_retry_converges_to_clean_state(root: Path, tmp_path: Path,
                                                                                monkeypatch) -> None:
    original = ist.IdentityStore.append
    calls = {"n": 0}

    def failing_third(self, record):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(28, "no space left")
        return original(self, record)

    monkeypatch.setattr(ist.IdentityStore, "append", failing_third)
    result = run(root, TWO)
    assert result.outcome is O.PARTIAL_FAILURE and result.reasons == (R.STORE_WRITE_FAILED, R.PARTIAL_WRITE)
    assert len(result.writes.appended) == 2 and bundle_states(result) == ["FAILED", "NOT_ATTEMPTED"]
    states = [w.state.value for w in result.bundles[0].writes]
    assert states == ["APPENDED", "APPENDED", "FAILED", "NOT_ATTEMPTED", "NOT_ATTEMPTED", "NOT_ATTEMPTED",
                      "NOT_ATTEMPTED"]
    assert result.bundles[0].writes[2].failure_code == "OS_ERROR"
    assert result.coverage[0].state is WriteState.NOT_ATTEMPTED
    assert len(lines(root)) == 2 and "space" not in json.dumps(result.as_dict())
    monkeypatch.setattr(ist.IdentityStore, "append", original)
    retry = run(root, TWO)
    assert retry.outcome is O.APPENDED and bundle_states(retry) == ["APPENDED", "APPENDED"]
    assert [w.state.value for w in retry.bundles[0].writes][:2] == ["REUSED", "REUSED"]
    assert len(retry.writes.appended) == 12 and set(retry.writes.reused) == set(result.writes.appended)
    clean = tmp_path / "clean"
    ist.IdentityStore.initialize(clean)
    run(clean, TWO)
    assert lines(root) == lines(clean)                                                     # 最終の状態 ＝ 一度で書いた状態
    assert run(root, TWO).outcome is O.REUSED


def test_write_failure_before_any_append_is_rejected(root: Path, monkeypatch) -> None:
    def failing(self, record):
        raise OSError(30, "read-only")

    monkeypatch.setattr(ist.IdentityStore, "append", failing)
    result = run(root, ONE)
    assert result.outcome is O.REJECTED and result.reasons == (R.STORE_WRITE_FAILED,) and lines(root) == []


# ================================================================ corruption / missing / concurrent modification


def test_corrupt_truncated_or_externally_modified_store_fails_closed(root: Path, monkeypatch) -> None:
    run(root, ONE)
    path = root / "screener_intelligence" / "identity_records.jsonl"
    original = path.read_bytes()
    with path.open("ab") as handle:
        handle.write(b'{"record_kind": "GARBAGE"}\n')
    result = run(root, TWO)
    assert result.outcome is O.REJECTED and result.reasons == (R.CORRUPT_STORE,) and path.read_bytes() != original
    path.write_bytes(original[:-1])                                                        # 切断された journal
    truncated = run(root, TWO)
    assert truncated.outcome is O.REJECTED and truncated.reasons == (R.CORRUPT_STORE,)
    assert truncated.failure_code == "TRUNCATED_FINAL_LINE"
    path.write_bytes(original)
    original_verify = ist.IdentityStore.verify_unchanged

    def modified(self):
        raise ist.IdentityConcurrentModification("CONCURRENT_MODIFICATION", "changed")

    monkeypatch.setattr(ist.IdentityStore, "verify_unchanged", modified)
    concurrent = run(root, TWO)
    assert concurrent.outcome is O.REJECTED and concurrent.reasons == (R.PRECHECK_FAILED,)
    assert concurrent.failure_code == "CONCURRENT_MODIFICATION" and path.read_bytes() == original
    monkeypatch.setattr(ist.IdentityStore, "verify_unchanged", original_verify)
    path.unlink()
    missing = run(root, ONE)
    assert missing.outcome is O.REJECTED and missing.reasons == (R.STORE_MISSING,) and not path.exists()


# ================================================================ result model


def test_result_model_is_closed_and_consistent() -> None:
    assert {m.value for m in RegistrationOutcome} == {"APPENDED", "REUSED", "REJECTED", "PARTIAL_FAILURE",
                                                      "NO_AUTHORIZED_ITEMS"}
    assert not {"score", "rank", "severity", "raw", "payload", "record_id"} & set(
        RegistrationResult.__dataclass_fields__)
    with pytest.raises(RegistrationModelError):
        RegistrationResult(outcome=RegistrationOutcome.APPENDED, reasons=())                # 書かずに APPENDED は不可
    with pytest.raises(RegistrationModelError):
        RegistrationResult(outcome=RegistrationOutcome.REJECTED, reasons=())
    with pytest.raises(RegistrationModelError):
        RegistrationResult(outcome=RegistrationOutcome.REJECTED, reasons=(R.INVALID_INPUT,), failure_code="13010 x")


# ================================================================ architecture


@pytest.mark.parametrize("name", ["identity_registration_model", "identity_registration_executor"])
def test_architecture_only_a1_store_no_network_clock_random_llm_or_other_stores(name: str) -> None:
    path = PACKAGE_DIR / f"{name}.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in {"time", "uuid", "random", "secrets", "os", "sys", "socket", "pathlib", "json",
                                       "difflib", "datetime"}, (name, node.module)
            assert not any(token in node.module for token in (
                "observation_store", "semantic_metadata", "held_observation", "jquants_financial_summary_executor",
                "jquants_execution", "identity_correction", "identity_remediation", "identity_resolver", "metric",
                "market", "jquants_v2", "ingestion", "themes", "narrative", "pages", "reports", "urllib",
                "requests")), (name, node.module)
        if isinstance(node, ast.Import):
            assert not node.names, (name, [a.name for a in node.names])
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "Path", "os", "print", "float", "eval", "exec", "getattr"}, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today", "write", "unlink", "urlopen", "uuid4", "random",
                                     "initialize", "rename", "replace", "truncate", "get_close_matches"}, \
                (name, node.attr)
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
    lowered = executable_source(path).lower()
    for token in ("screen", "rank", "score", "recommend", "theme", "llm", "prompt", "anthropic", "sqlite", "production",
                  "x-api-key", "://", "similar", "fuzzy", "rollback", "delete", "observationstore",
                  "heldobservationstore", "semanticmetadatastore"):
        assert token not in lowered, (name, token)


def test_architecture_only_the_identity_journal_is_written(root: Path) -> None:
    run(root, TWO)
    run(root, TWO, reviewed_for(TWO, disposition=ReviewDisposition.REJECT))
    assert {p.name for p in (root / "screener_intelligence").iterdir()} == {"identity_records.jsonl"}
    assert not list(root.glob("**/*.log")) and not list(root.glob("**/*manifest*"))
    assert not (REPO_ROOT / "data" / "screener_intelligence").exists()
    history = IdentityHistory(ist.IdentityStore.open(root).records())
    assert len(history.issuers) == 2 and len(history.securities) == 2 and len(history.coverages) == 1
