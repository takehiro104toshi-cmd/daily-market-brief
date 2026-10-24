"""P8-ID1 — identity bootstrap の test matrix（happy ・審査 ・identity ・D0 ・複雑な場合 ・architecture）。

合成の master の行 ・合成の A1 の履歴だけ。A1 の store ・A2 ・注記 ・保留には書かない（manifest の直列化の往復だけ tmp_path）。
J-Quants ・network ・時計 ・乱数 ・LLM ・名前の類似は使わない。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import identity_bootstrap as ib
from src.intelligence.screener_intelligence import identity_bootstrap_model as bm
from src.intelligence.screener_intelligence.identity_bootstrap import (BootstrapPlanError, plan_registration,
                                                                       propose_bootstrap, review_manifest)
from src.intelligence.screener_intelligence.identity_bootstrap_model import (BootstrapBatch, BootstrapInputError,
                                                                             BootstrapManifest, IdentityProposal,
                                                                             MasterRow, PlanSkipReason,
                                                                             ProposalDisposition, ProposalReview,
                                                                             ReviewDisposition, ReviewedManifest,
                                                                             ReviewerClass)
from src.intelligence.screener_intelligence.identity_model import (IdentifierRetirement, IdentityHistory,
                                                                   IdentifierScheme, IssueClass, ListingEnd,
                                                                   ListingEndReason, RecordKind, RetirementReason,
                                                                   SourceClass, SourceProvenance, derive_issuer_id,
                                                                   derive_security_id, is_issuer_id, is_security_id)
from src.intelligence.screener_intelligence.observation_model import TOKYO
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
D0 = date(2026, 6, 30)
BATCH = BootstrapBatch(batch_id="p8boot1", d0=D0, supported_markets=("0111", "0112", "0113"))
ACCEPTED = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
R = bm.BootstrapReason
P = ProposalDisposition


def master(code: str = "13010", name: str = "合成 一号", name_en: str = "Synth One", mkt: str = "0111",
           day: str = "2026-06-30", **extra) -> dict:
    return {"Date": day, "Code": code, "CoName": name, "CoNameEn": name_en, "Mkt": mkt, **extra}


def propose(rows, existing=None) -> BootstrapManifest:
    return propose_bootstrap(rows, BATCH, existing)


def approve_all(manifest: BootstrapManifest, disposition=ReviewDisposition.APPROVE, accepted=ACCEPTED):
    reviews = [ProposalReview(proposal_id=p.proposal_id, proposal_digest=p.digest, disposition=disposition)
               for p in manifest.proposals]
    return review_manifest(manifest, reviews, accepted_at=accepted)


def items(manifest: BootstrapManifest) -> dict:
    return {i.code: (i.disposition.value, [r.value for r in i.reasons]) for i in manifest.review_items}


def registered(rows) -> IdentityHistory:
    """合成の行を承認 ・plan し、その record だけの凍結 A1 の履歴（memory 内）を返す。store には書かない。"""
    manifest = propose(rows)
    plan = plan_registration(manifest, approve_all(manifest))
    return IdentityHistory(plan.records)


# ================================================================ happy path


def test_happy_eligible_ordinary_listed_security_yields_deterministic_issuer_and_security_proposals() -> None:
    manifest = propose([master()])
    assert len(manifest.proposals) == 1 and manifest.review_items == ()
    proposal = manifest.proposals[0]
    assert proposal.issuer_anchor == "p8boot1:iss.13010" and proposal.security_anchor == "p8boot1:sec.13010"
    assert proposal.issuer_id == derive_issuer_id("p8boot1:iss.13010") and is_issuer_id(proposal.issuer_id)
    assert proposal.security_id == derive_security_id("p8boot1:sec.13010") and is_security_id(proposal.security_id)
    assert proposal.issue_class is IssueClass.COMMON_EQUITY and proposal.d0 == D0 and proposal.market == "0111"
    assert proposal.name_ja == "合成 一号" and proposal.name_en == "Synth One"
    assert proposal.provider_record_ref.startswith("jq.eq_master:13010.2026-06-30:")
    assert proposal.proposal_id.startswith("p8prop_") and len(proposal.digest) == 64
    assert propose([master()]).proposals[0] == proposal                                   # 決定論
    assert manifest.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
    assert manifest.schema_version == "p8_bootstrap_manifest:0.1.0"


def test_happy_manifest_review_and_registration_plan() -> None:
    manifest = propose([master(), master("13020", "合成 二号", "")])
    reviewed = approve_all(manifest)
    assert reviewed.reviewer_class is ReviewerClass.HUMAN and reviewed.manifest_digest == manifest.manifest_digest
    plan = plan_registration(manifest, reviewed)
    assert plan.manifest_digest == manifest.manifest_digest and plan.reviewed_digest == reviewed.reviewed_digest
    assert [e.code for e in plan.entries] == ["13010", "13020"] and plan.skipped == ()
    kinds = [r.KIND.value for r in plan.entries[0].records]
    assert kinds == ["ISSUER_REGISTRATION", "SECURITY_REGISTRATION", "IDENTIFIER_ASSIGNMENT", "DISPLAY_NAME",
                     "DISPLAY_NAME", "DISPLAY_NAME", "LISTING_START"]
    assert [r.KIND.value for r in plan.entries[1].records].count("DISPLAY_NAME") == 2       # 英名が空なら EN は無い
    assert [r.KIND.value for r in plan.coverage] == ["COVERAGE"]
    issuer, security, assignment = plan.entries[0].records[:3]
    assert issuer.provenance.source_class is SourceClass.HUMAN_REVIEWED
    assert issuer.provenance.source_record_ref == f"review:p8boot1.{reviewed.reviewed_digest[:24]}"
    assert issuer.known_at == ACCEPTED and security.issuer_id == issuer.issuer_id
    assert assignment.scheme is IdentifierScheme.JQUANTS_CODE and assignment.value == "13010"
    assert assignment.provenance.source_class is SourceClass.JQUANTS
    assert assignment.effective_from == datetime(2026, 6, 30, tzinfo=TOKYO)
    assert plan.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT" and len(plan.plan_digest) == 64
    history = IdentityHistory(plan.records)                                                # 凍結 A1 の不変条件を満たす
    assert set(history.issuers) == {plan.entries[0].issuer_id, plan.entries[1].issuer_id}


def test_happy_manifest_digest_is_independent_of_row_order_and_duplicate_rows_converge() -> None:
    rows = [master(), master("13020", "合成 二号", ""), master("13030", "合成 三号", "Synth Three", "0113")]
    first = propose(rows)
    assert propose(list(reversed(rows))).manifest_digest == first.manifest_digest
    assert propose(rows + [master()]).manifest_digest == first.manifest_digest              # byte 一致の重複は収束
    assert [p.code for p in first.proposals] == ["13010", "13020", "13030"]


def test_happy_manifest_serialization_roundtrip_via_explicit_tmp_path(tmp_path: Path) -> None:
    manifest = propose([master(), master("13025", "優先", "", "0111")])
    target = tmp_path / "review" / "p8boot1_manifest.json"
    target.parent.mkdir()
    target.write_text(json.dumps(manifest.as_dict(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    loaded = BootstrapManifest.from_dict(json.loads(target.read_text(encoding="utf-8")))
    assert loaded == manifest and loaded.manifest_digest == manifest.manifest_digest
    tampered = json.loads(target.read_text(encoding="utf-8"))
    tampered["proposals"][0]["name_ja"] = "別の名前"
    with pytest.raises(BootstrapInputError) as info:
        BootstrapManifest.from_dict(tampered)
    assert info.value.code in ("PROPOSAL_DIGEST_MISMATCH", "MANIFEST_DIGEST_MISMATCH")
    text = target.read_text(encoding="utf-8")
    assert "MktNm" not in text and "S17" not in text and "apikey" not in text.lower()


# ================================================================ review


def test_review_unreviewed_rejected_and_deferred_cannot_plan_but_approve_can() -> None:
    manifest = propose([master(), master("13020", "合成 二号", "")])
    with pytest.raises(BootstrapPlanError) as info:
        plan_registration(manifest, None)
    assert info.value.code == "UNREVIEWED_MANIFEST"
    partial = review_manifest(manifest, [ProposalReview(proposal_id=manifest.proposals[0].proposal_id,
                                                        proposal_digest=manifest.proposals[0].digest,
                                                        disposition=ReviewDisposition.APPROVE)], accepted_at=ACCEPTED)
    plan = plan_registration(manifest, partial)
    assert [e.code for e in plan.entries] == ["13010"]
    assert plan.skipped == ((manifest.proposals[1].proposal_id, PlanSkipReason.NOT_REVIEWED),)
    for disposition, reason in ((ReviewDisposition.REJECT, PlanSkipReason.REJECTED),
                                (ReviewDisposition.DEFER, PlanSkipReason.DEFERRED)):
        plan = plan_registration(manifest, approve_all(manifest, disposition))
        assert plan.entries == () and plan.coverage == () and plan.records == ()
        assert {reason_ for _, reason_ in plan.skipped} == {reason}
    empty = review_manifest(manifest, [], accepted_at=ACCEPTED)                          # 審査なし ＝ 承認なし
    assert plan_registration(manifest, empty).entries == ()


def test_review_changed_proposal_or_manifest_invalidates_approval() -> None:
    manifest = propose([master()])
    reviewed = approve_all(manifest)
    changed = propose([master(name="合成 一号 改")])                                       # 提案の内容が変わった
    with pytest.raises(BootstrapPlanError) as info:
        plan_registration(changed, reviewed)
    assert info.value.code == "MANIFEST_DIGEST_MISMATCH"
    grown = propose([master(), master("13020", "合成 二号", "")])                           # manifest が変わった
    with pytest.raises(BootstrapPlanError):
        plan_registration(grown, reviewed)
    forged = ReviewedManifest(manifest_digest=changed.manifest_digest, reviews=reviewed.reviews, accepted_at=ACCEPTED)
    carried = plan_registration(changed, forged)                                          # 承認の持ち越しは権限を持たない
    assert carried.entries == () and carried.records == ()
    assert carried.skipped == ((changed.proposals[0].proposal_id, PlanSkipReason.NOT_REVIEWED),)
    with pytest.raises(BootstrapPlanError) as info:
        review_manifest(changed, list(reviewed.reviews), accepted_at=ACCEPTED)
    assert info.value.code == "REVIEW_TARGET_UNKNOWN"
    same_content = ProposalReview(proposal_id=manifest.proposals[0].proposal_id,
                                  proposal_digest=manifest.proposals[0].digest, disposition=ReviewDisposition.APPROVE)
    rebound = review_manifest(grown, [same_content], accepted_at=ACCEPTED)                # 同じ内容の提案には結び直せる
    assert rebound.manifest_digest == grown.manifest_digest and rebound.reviewed_digest != reviewed.reviewed_digest


def test_review_digest_is_deterministic_and_bound_to_content() -> None:
    manifest = propose([master()])
    first = approve_all(manifest)
    assert first.reviewed_digest == approve_all(manifest).reviewed_digest
    assert approve_all(manifest, ReviewDisposition.REJECT).reviewed_digest != first.reviewed_digest
    later = approve_all(manifest, accepted=ACCEPTED + timedelta(hours=1))
    assert later.reviewed_digest != first.reviewed_digest
    with pytest.raises(BootstrapInputError):
        ReviewedManifest(manifest_digest=manifest.manifest_digest, reviews=(), accepted_at=datetime(2026, 7, 1))
    with pytest.raises(BootstrapInputError):                                               # reviewer は HUMAN だけ
        ReviewedManifest(manifest_digest=manifest.manifest_digest, reviews=(), accepted_at=ACCEPTED,
                         reviewer_class="MACHINE")                                          # type: ignore[arg-type]
    with pytest.raises(BootstrapInputError):
        ProposalReview(proposal_id=manifest.proposals[0].proposal_id, proposal_digest="ab" * 32,
                       disposition=ReviewDisposition.APPROVE)
    with pytest.raises(BootstrapInputError):
        ProposalReview(proposal_id=manifest.proposals[0].proposal_id, proposal_digest=manifest.proposals[0].digest,
                       disposition=ReviewDisposition.APPROVE, note="x" * 201)
    assert {d.value for d in ReviewDisposition} == {"APPROVE", "REJECT", "DEFER"}
    assert {c.value for c in ReviewerClass} == {"HUMAN"}


# ================================================================ identity


def test_identity_provider_code_never_becomes_a_canonical_id() -> None:
    proposal = propose([master()]).proposals[0]
    assert "13010" not in proposal.issuer_id and "13010" not in proposal.security_id
    assert proposal.issuer_id != derive_issuer_id("p8boot1:iss.13020")
    other_batch = BootstrapBatch(batch_id="p8boot2", d0=D0, supported_markets=("0111",))
    later = propose_bootstrap([master()], other_batch).proposals[0]
    assert later.issuer_id != proposal.issuer_id and later.security_id != proposal.security_id   # anchor は一括ごと
    for name in ("identity_bootstrap_model", "identity_bootstrap"):
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        assert "IssuerId(" not in source and "SecurityId(" not in source and "p8iss_" not in source
    with pytest.raises(BootstrapInputError):                                               # 提案の id は anchor からだけ
        IdentityProposal(**{**{k: v for k, v in proposal.__dict__.items()}, "issuer_id": "p8iss_" + "0" * 24})


@pytest.mark.parametrize("code,reason", [("1301", "CODE_MALFORMED"), ("130100", "CODE_MALFORMED"),
                                         ("1301a", "CODE_MALFORMED"), ("", "CODE_MALFORMED"),
                                         ("13015", "CODE_NOT_COMMON_EQUITY"), ("1301A", "CODE_NOT_COMMON_EQUITY"),
                                         ("A3010", "CODE_NOT_COMMON_EQUITY")])
def test_identity_malformed_or_non_common_equity_codes_are_held(code: str, reason: str) -> None:
    manifest = propose([master(code)])
    assert manifest.proposals == () and list(items(manifest)) == [code]
    disposition, reasons = items(manifest)[code]
    assert disposition == "HELD" and reason in reasons


def test_identity_missing_name_conflicting_rows_and_unsupported_market_are_held() -> None:
    manifest = propose([master(name=""), master("13020", "合成 二号", "", "0999"),
                        master("13030", "合成 三号", ""), master("13030", "合成 三号 別", "")])
    assert manifest.proposals == ()
    assert items(manifest) == {"13010": ("HELD", ["NAME_MISSING"]), "13020": ("HELD", ["MARKET_UNSUPPORTED"]),
                               "13030": ("HELD", ["CODE_CONFLICTING_ROWS"])}
    assert manifest.review_items[2].provider_record_digest == ""                           # どちらの行も採らない


def test_identity_existing_exact_identity_is_reused_and_a_code_bound_elsewhere_is_a_conflict() -> None:
    history = registered([master()])
    again = propose([master()], history)
    assert again.proposals == () and items(again) == {"13010": ("REUSE", [])}
    reuse = again.review_items[0]
    assert reuse.existing_issuer_id == derive_issuer_id("p8boot1:iss.13010")
    plan = plan_registration(again, approve_all(again), history)
    assert plan.entries == () and plan.records == ()                                      # 重複の登録なし
    other = BootstrapBatch(batch_id="p8boot2", d0=D0, supported_markets=("0111",))
    conflict = propose_bootstrap([master()], other, history)
    assert items(conflict) == {"13010": ("CONFLICT", ["CODE_BOUND_TO_OTHER_IDENTITY"])}
    assert conflict.review_items[0].existing_security_id == derive_security_id("p8boot1:sec.13010")


def test_identity_plan_is_checked_against_frozen_a1_rules_without_appending() -> None:
    history = registered([master()])
    manifest = propose([master("13020", "合成 二号", "")])
    earlier = approve_all(manifest, accepted=ACCEPTED - timedelta(days=1))                 # A1 より前の known_at
    with pytest.raises(BootstrapPlanError) as info:
        plan_registration(manifest, earlier, history)
    assert info.value.code == "PLAN_REJECTED_BY_AUTHORITY_RULES" and info.value.detail == "NON_MONOTONIC_KNOWN_AT"
    plan = plan_registration(manifest, approve_all(manifest), history)
    assert len(history.records) == 8 and len(plan.records) == 7                            # history は変わらない


# ================================================================ D0


def test_d0_is_explicit_and_coverage_never_precedes_it() -> None:
    with pytest.raises(BootstrapInputError):
        BootstrapBatch(batch_id="p8boot1", d0=datetime(2026, 6, 30), supported_markets=("0111",))  # type: ignore
    with pytest.raises(BootstrapInputError):
        BootstrapBatch(batch_id="p8boot1", d0=D0, supported_markets=())                    # 市場の既定なし
    with pytest.raises(BootstrapInputError):
        BootstrapBatch(batch_id="boot1", d0=D0, supported_markets=("0111",))
    manifest = propose([master()])
    plan = plan_registration(manifest, approve_all(manifest))
    coverage = plan.coverage[0]
    assert coverage.effective_from == datetime(2026, 6, 30, tzinfo=TOKYO)
    assert coverage.effective_to == datetime(2026, 7, 1, tzinfo=TOKYO)
    for record in plan.records:
        effective = record.__dict__.get("effective_from")
        assert effective is None or effective == datetime(2026, 6, 30, tzinfo=TOKYO)
    mismatch = propose([master(day="2026-06-29")])                                          # 別の日の snapshot
    assert items(mismatch) == {"13010": ("HELD", ["SNAPSHOT_DATE_MISMATCH"])}
    assert "now" not in executable_source(PACKAGE_DIR / "identity_bootstrap.py").lower().replace("known", "")


def test_d0_retrospective_history_is_not_created() -> None:
    plan = plan_registration(propose([master()]), approve_all(propose([master()])))
    history = IdentityHistory(plan.records)
    from src.intelligence.screener_intelligence.identity_resolver import IdentityQuery, resolve
    before = resolve(history, IdentityQuery.for_issuer(plan.entries[0].issuer_id),
                     cutoff=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert before.status.value != "FOUND"
    assert all(r.KIND is not RecordKind.LISTING_END for r in plan.records)
    assert not any(r.KIND is RecordKind.IDENTIFIER_RETIREMENT for r in plan.records)


# ================================================================ complex cases → human review


def test_complex_multiple_listings_and_shared_code_stem_require_human_review() -> None:
    manifest = propose([master("13010"), master("13015", "合成 一号 優先", "")])
    assert items(manifest) == {"13010": ("HUMAN_REVIEW_REQUIRED", ["MULTIPLE_LISTINGS_SUSPECTED"]),
                               "13015": ("HELD", ["CODE_NOT_COMMON_EQUITY"])}
    assert manifest.proposals == ()


def test_complex_code_change_delist_and_relist_are_human_governed() -> None:
    history = registered([master(), master("13020", "合成 二号", "")])
    absent = propose([master()], history)                                                 # 13020 が snapshot から消えた
    assert items(absent) == {"13010": ("REUSE", []), "13020": ("HUMAN_REVIEW_REQUIRED", ["CODE_ABSENT_FROM_SNAPSHOT"])}
    assert absent.proposals == ()
    new_code = propose([master(), master("13020", "合成 二号", ""), master("13990", "合成 二号", "")], history)
    assert new_code.proposals[0].code == "13990"                                            # 同名でも結ばない（人の判断）
    assert new_code.proposals[0].issuer_id != derive_issuer_id("p8boot1:iss.13020")
    records = list(history.records)
    assignment = next(r for r in records if r.KIND is RecordKind.IDENTIFIER_ASSIGNMENT and r.value == "13020")
    listing = next(r for r in records if r.KIND is RecordKind.LISTING_START
                   and r.security_id == assignment.security_id)
    later = SourceProvenance(source_class=SourceClass.HUMAN_REVIEWED, source_record_ref="review:delist-1",
                             known_at=ACCEPTED + timedelta(days=1))
    delisted = IdentityHistory(records + [ListingEnd(listing_record_id=listing.record_id,
                                                     effective_to=ACCEPTED + timedelta(days=1),
                                                     reason=ListingEndReason.DELISTED, provenance=later)])
    relist = propose([master(), master("13020", "合成 二号", "")], delisted)
    assert items(relist)["13020"] == ("HUMAN_REVIEW_REQUIRED", ["LISTING_ENDED_IN_AUTHORITY"])
    retired = IdentityHistory(records + [IdentifierRetirement(assignment_record_id=assignment.record_id,
                                                              effective_to=ACCEPTED + timedelta(days=1),
                                                              reason=RetirementReason.REPLACED, provenance=later)])
    code_change = propose([master(), master("13020", "合成 二号", "")], retired)
    assert items(code_change)["13020"] == ("HUMAN_REVIEW_REQUIRED", ["CODE_PREVIOUSLY_RETIRED"])
    assert code_change.review_items[1].existing_security_id == assignment.security_id


def test_complex_incomplete_or_conflicting_issuer_security_relation_requires_human_review() -> None:
    plan = plan_registration(propose([master()]), approve_all(propose([master()])))
    partial = IdentityHistory(plan.records[:1])                                            # Issuer だけ登録済み
    assert items(propose([master()], partial)) == {"13010": ("HUMAN_REVIEW_REQUIRED", ["EXISTING_IDENTITY_INCOMPLETE"])}
    both = IdentityHistory(plan.records[:2])                                               # code の割り当てが無い
    item = propose([master()], both).review_items[0]
    assert item.disposition is P.HUMAN_REVIEW_REQUIRED and item.existing_security_id == plan.entries[0].security_id


# ================================================================ input contract


def test_input_contract_is_strict_and_retains_nothing_else() -> None:
    parsed = MasterRow.from_provider_mapping(master(MktNm="プライム", S17="1", S17Nm="食品", ScaleCat="TOPIX Small 1",
                                                    Mrgn="1", MrgnNm="信用", ProdCat="1", S33="50", S33Nm="食料品"))
    assert set(parsed.supported_values()) == set(bm.SUPPORTED_MASTER_FIELDS) and "MktNm" not in parsed.__dict__
    with pytest.raises(BootstrapInputError) as info:
        MasterRow.from_provider_mapping(master(Payload="x"))
    assert info.value.code == "PROVIDER_FIELD_UNKNOWN"
    with pytest.raises(BootstrapInputError) as info:
        MasterRow.from_provider_mapping({k: v for k, v in master().items() if k != "Mkt"})
    assert info.value.code == "PROVIDER_FIELD_MISSING" and info.value.detail == "Mkt"
    with pytest.raises(BootstrapInputError) as info:
        MasterRow.from_provider_mapping(master(Code=13010))
    assert info.value.code == "PROVIDER_VALUE_NOT_TEXT"
    with pytest.raises(BootstrapInputError):
        MasterRow.from_provider_mapping(master(name="x" * 121))
    with pytest.raises(BootstrapInputError):
        MasterRow.from_provider_mapping(master(name="token abc"))
    with pytest.raises(BootstrapInputError):
        propose_bootstrap({"Code": "13010"}, BATCH)
    with pytest.raises(BootstrapInputError):
        propose_bootstrap([master()], {"batch_id": "p8boot1"})
    with pytest.raises(BootstrapInputError):
        propose_bootstrap([master()], BATCH, existing={"issuers": {}})
    assert len(bm.OFFICIAL_MASTER_FIELDS) == 14 and set(bm.SUPPORTED_MASTER_FIELDS) <= set(bm.OFFICIAL_MASTER_FIELDS)
    with pytest.raises(FrozenInstanceError):
        parsed.Code = "x"                                                                  # type: ignore[misc]


# ================================================================ architecture


@pytest.mark.parametrize("name", ["identity_bootstrap_model", "identity_bootstrap"])
def test_architecture_no_store_append_network_clock_random_uuid_llm_or_fuzzy_matching(name: str) -> None:
    path = PACKAGE_DIR / f"{name}.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in {"time", "uuid", "random", "secrets", "os", "sys", "socket", "pathlib", "json",
                                       "difflib", "unicodedata"}, (name, node.module)
            assert not any(token in node.module for token in (
                "store", "resolver", "executor", "execution", "metric", "market", "jquants_v2", "ingestion", "themes",
                "narrative", "pages", "reports", "urllib", "requests", "correction", "remediation")), \
                (name, node.module)
        if isinstance(node, ast.Import):
            assert all(a.name in ("hashlib", "re") for a in node.names), (name, [a.name for a in node.names])
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "Path", "os", "print", "float", "eval", "exec", "getattr"}, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today", "append_record", "write", "urlopen", "uuid4", "random",
                                     "initialize", "ratio", "quick_ratio", "get_close_matches"}, (name, node.attr)
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
    lowered = executable_source(path).lower()
    for token in ("screen", "rank", "score", "recommend", "theme", "llm", "prompt", "anthropic", "sqlite", "production",
                  "x-api-key", "://", "similar", "fuzzy", "levenshtein", "identitystore", "observationstore",
                  "heldobservationstore", "semanticmetadatastore", "execute_financial_summary_row"):
        assert token not in lowered, (name, token)
    for node in ast.walk(tree):                                                            # store の append を呼ばない
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            assert isinstance(node.func.value, ast.Name) and node.func.value.id in (
                "proposals", "items", "entries", "skipped", "reasons", "active", "retired", "rows_for_code",
                "stem_codes"), (name, ast.dump(node))


def test_architecture_nothing_is_written_anywhere(tmp_path: Path) -> None:
    before = sorted(p for p in REPO_ROOT.glob("data/**/*") if "screener_intelligence" in str(p))
    history = registered([master(), master("13020", "合成 二号", "")])
    propose([master()], history)
    assert sorted(p for p in REPO_ROOT.glob("data/**/*") if "screener_intelligence" in str(p)) == before
    assert list(tmp_path.iterdir()) == []
    assert not (REPO_ROOT / "data" / "screener_intelligence").exists()
