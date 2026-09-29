"""P6-B5D-RERUN — B5C-R1 に対する独立再検証 gate（test only。runtime を変更しない）。

R1 の報告を前提にせず、runtime の挙動から直接確かめる。中心の問い:

    citation の存在だけで `SOURCE_ASSERTED` 適格が成立する経路が、**どこかに残っていないか**。

そのため受理述語を呼びうる runtime 経路（決定の構築 / 決定の解決 / plan の構築 / 直列化と復元 /
store からの load / 適格判定）を列挙し、2 つ目の弱い述語が無いことを固定する。
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.relation_model import (AssertionClass, RelationType, SourceAttribution,
                                                                ThemeRelationAssertion, canonical_relation_line)
from src.intelligence.theme_intelligence.relation_proposal_bridge import (RelationBridgeError,
                                                                          RelationVerificationOrigin,
                                                                          plan_relation_assertion_from_accepted_proposal)
from src.intelligence.theme_intelligence.relation_proposal_model import (RelationChangeKind, RelationDecisionKind,
                                                                         RelationProposal, RelationProposalDecision,
                                                                         RelationProposalError,
                                                                         RelationProposerClass,
                                                                         SOURCE_ASSERTED_REFUSAL_CODES,
                                                                         SourceClaimVerification,
                                                                         canonical_proposal_record_line,
                                                                         source_asserted_refusal,
                                                                         source_authority_available)
from src.intelligence.theme_intelligence.relation_proposal_resolution import (RelationProposalStatus,
                                                                              derive_relation_proposal_status)
from src.intelligence.theme_intelligence.relation_proposal_store import (AppendStatus,
                                                                         RelationProposalAppendRejected,
                                                                         RelationProposalConflict,
                                                                         RelationProposalInvalidHistory,
                                                                         RelationProposalStore,
                                                                         RelationProposalStoreCorrupt)
from src.intelligence.theme_intelligence.relation_store import authority_paths as relation_authority_paths
from src.intelligence.themes.model import EvidenceKind, ProvenanceClass, normalize_text
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_relation import A, ACTOR, ATTRIBUTION, B, C, D, T0, evidence
from tests.intelligence.test_theme_relation_e2e import (B5_RUNTIME_MODULES, PROPOSER_CLASSES, accept, candidate_of,
                                                        cited, plan_of, refuses, store_at)
from tests.intelligence.test_theme_relation_proposal import (DECIDED_AT, OTHER_SOURCE, PLANNED_AT, decide, proposal,
                                                             verification)

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
B5C_MODULES = ("relation_proposal_model", "relation_proposal_resolution", "relation_proposal_bridge",
               "relation_proposal_store")
SEEDS = tuple(range(11))


def backed(proposer=RelationProposerClass.LLM, *, tag="r", attribution=ATTRIBUTION, locator="section:4",
           **kw) -> RelationProposal:
    """出典裏付きの候補（帰属と、その帰属を指す citation を持つ）。"""
    return candidate_of(proposer, attribution=attribution,
                        refs=(cited(tag, attribution=attribution.attributed_to if attribution else "",
                                    locator=locator),),
                        rationale="the release states the first theme drives the second", **kw)


# ================================================================ §2 受理述語の一意性（bypass 探索）


def test_rr_01_the_runtime_holds_exactly_one_source_asserted_gate() -> None:
    """適格判定を行う runtime 経路は `source_asserted_refusal` の 2 呼び出しだけである。"""
    call_sites = []
    for name in B5_RUNTIME_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for line in source.split("\n"):
            if "source_asserted_refusal(" in line and "def " not in line:
                call_sites.append(name)
    assert sorted(call_sites) == ["relation_proposal_bridge", "relation_proposal_store"]


def test_rr_02_the_weak_predicate_has_no_runtime_call_site() -> None:
    """`source_authority_available` は helper として残るが、runtime の gate としては呼ばれていない。"""
    callers = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        source = executable_source(path)
        for line in source.split("\n"):
            if "source_authority_available(" in line and not line.lstrip().startswith("def "):
                callers.append(str(path.relative_to(REPO_ROOT)))
    assert callers == [], callers


@pytest.mark.parametrize("name", B5C_MODULES)
def test_rr_03_06_no_module_decides_source_asserted_on_its_own(name) -> None:
    """`AssertionClass.SOURCE_ASSERTED` を見て分岐する箇所は、必ず共有述語を伴う。"""
    source = executable_source(PACKAGE_DIR / f"{name}.py")
    branches = [line for line in source.split("\n")
                if "SOURCE_ASSERTED" in line and ("if " in line or "elif " in line)]
    if name == "relation_proposal_model":
        assert len(branches) == 1                                  # decision の確認必須化のみ
        assert "source_claim_verification" in source.split(branches[0])[1][:400]
    elif name in ("relation_proposal_store", "relation_proposal_bridge"):
        assert len(branches) == 1 and "source_asserted_refusal" in source.split(branches[0])[1][:400]
    else:
        assert branches == []


def test_rr_07_the_refusal_vocabulary_is_closed_and_shared() -> None:
    assert SOURCE_ASSERTED_REFUSAL_CODES == (
        "MISSING_SOURCE_ATTRIBUTION", "MISSING_SOURCE_CITATION", "MISSING_SOURCE_CLAIM_VERIFICATION",
        "VERIFICATION_ATTRIBUTION_MISMATCH", "VERIFICATION_CITATION_MISMATCH",
        "VERIFICATION_CITATION_ATTRIBUTION_MISMATCH", "VERIFICATION_ENDPOINT_MISMATCH",
        "VERIFICATION_RELATION_TYPE_MISMATCH", "VERIFICATION_BEFORE_PROPOSAL")
    from src.intelligence.theme_intelligence.relation_proposal_store import HISTORY_REASONS
    assert set(SOURCE_ASSERTED_REFUSAL_CODES) <= set(HISTORY_REASONS)


def test_rr_08_a_source_asserted_accept_cannot_be_built_without_a_verification() -> None:
    """決定の構築経路。`build` でも直接構築でも確認なしでは組み立てられない。"""
    candidate = backed()
    with pytest.raises(RelationProposalError) as info:
        RelationProposalDecision.build(proposal_id=candidate.proposal_id, decision=RelationDecisionKind.ACCEPT,
                                       accepted_assertion_class=AssertionClass.SOURCE_ASSERTED,
                                       actor_ref="reviewer:r1", reason="no verification", recorded_at=DECIDED_AT)
    assert info.value.code == "MISSING_SOURCE_CLAIM_VERIFICATION"
    good = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    with pytest.raises(RelationProposalError) as info:
        dataclasses.replace(good, source_claim_verification=None)
    assert info.value.code == "MISSING_SOURCE_CLAIM_VERIFICATION"


def test_rr_09_deserialization_is_not_a_bypass() -> None:
    """直列化と復元の経路。確認を落とした payload も、型を壊した payload も復元できない。"""
    candidate = backed()
    payload = accept(candidate, AssertionClass.SOURCE_ASSERTED).as_dict()
    stripped = {**payload, "source_claim_verification": None}
    with pytest.raises(RelationProposalError) as info:
        RelationProposalDecision.from_dict(stripped)
    assert info.value.code == "MISSING_SOURCE_CLAIM_VERIFICATION"
    for broken in ("", [], 0, "yes"):
        with pytest.raises(RelationProposalError):
            RelationProposalDecision.from_dict({**payload, "source_claim_verification": broken})
    assert RelationProposalDecision.from_dict(payload).source_claim_verification is not None


def test_rr_10_a_tampered_verification_breaks_the_decision_identity() -> None:
    candidate = backed()
    payload = accept(candidate, AssertionClass.SOURCE_ASSERTED).as_dict()
    shifted = json.loads(json.dumps(payload))
    shifted["source_claim_verification"]["assertion_locus"] = "section:99"
    with pytest.raises(RelationProposalError) as info:
        RelationProposalDecision.from_dict(shifted)
    assert info.value.code == "INVALID_RECORD_ID"


# ================================================================ §3 A〜N matrix（独立再実行）


def matrix_rows():
    exact = backed()
    yield "A", exact, accept(exact, AssertionClass.SOURCE_ASSERTED), ""
    unrelated = candidate_of(RelationProposerClass.LLM, attribution=ATTRIBUTION,
                             refs=(cited("b", attribution=OTHER_SOURCE.attributed_to),),
                             rationale="inferred, citation attached for context")
    yield "B", unrelated, accept(unrelated, AssertionClass.SOURCE_ASSERTED), "VERIFICATION_CITATION_ATTRIBUTION_MISMATCH"
    blank = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited("c", attribution=""),))
    yield "Bp", blank, accept(blank, AssertionClass.SOURCE_ASSERTED), "VERIFICATION_CITATION_ATTRIBUTION_MISMATCH"
    missing_attribution = candidate_of(RelationProposerClass.LLM, refs=(cited("f"),),
                                       rationale="the source is not named")
    yield "D", missing_attribution, accept(missing_attribution, AssertionClass.SOURCE_ASSERTED), \
        "MISSING_SOURCE_ATTRIBUTION"
    uncited = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION)
    yield "E", uncited, accept(uncited, AssertionClass.SOURCE_ASSERTED), "MISSING_SOURCE_CITATION"
    for label, shift, code in (("G", dict(attributed_to=OTHER_SOURCE.attributed_to), "VERIFICATION_ATTRIBUTION_MISMATCH"),
                               ("H", dict(evidence_ref=cited("z", attribution=ATTRIBUTION.attributed_to)),
                                "VERIFICATION_CITATION_MISMATCH"),
                               ("I", dict(source=C), "VERIFICATION_ENDPOINT_MISMATCH"),
                               ("J", dict(target=D), "VERIFICATION_ENDPOINT_MISMATCH"),
                               ("K", dict(relation_type=RelationType.MITIGATES),
                                "VERIFICATION_RELATION_TYPE_MISMATCH")):
        subject = backed()
        yield label, subject, accept(subject, AssertionClass.SOURCE_ASSERTED,
                                     verified=verification(subject, **shift)), code


MATRIX = tuple(matrix_rows())


@pytest.mark.parametrize("label,candidate,decision,code", MATRIX, ids=[row[0] for row in MATRIX])
def test_rr_11_21_the_a_to_n_matrix_returns_the_exact_code(label, candidate, decision, code) -> None:
    assert source_asserted_refusal(candidate, decision) == code, label
    if code:
        assert refuses(code, candidate, (decision,)).code == code
    else:
        assert plan_of(candidate, (decision,)).assertion_class is AssertionClass.SOURCE_ASSERTED


@pytest.mark.parametrize("label,candidate,decision,code", MATRIX, ids=[row[0] for row in MATRIX])
def test_rr_22_32_the_store_returns_the_same_code_as_the_bridge(tmp_path, label, candidate, decision, code) -> None:
    store = store_at(tmp_path, name=f"data_{label}")
    store.append_proposal(candidate)
    if not code:
        assert store.append_decision(decision).status is AppendStatus.APPENDED
        return
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(decision)
    assert info.value.code == code, label
    assert store.counts()["decisions"] == 0


def test_rr_33_case_c_a_mention_only_citation_needs_an_explicit_verification() -> None:
    """C: 出典が entity / topic に言及しただけの場合、人間の明示的な確認なしには受理できない。"""
    mention_only = backed(RelationProposerClass.RULE, tag="d", locator="section:1")
    with pytest.raises(RelationProposalError) as info:
        accept(mention_only, AssertionClass.SOURCE_ASSERTED, verified=None)
    assert info.value.code == "MISSING_SOURCE_CLAIM_VERIFICATION"
    human = RelationProposalDecision.build(proposal_id=mention_only.proposal_id,
                                           decision=RelationDecisionKind.ACCEPT,
                                           accepted_assertion_class=AssertionClass.HUMAN_ASSERTED,
                                           actor_ref="reviewer:r1", reason="accepted on my own authority",
                                           recorded_at=DECIDED_AT)
    assert source_asserted_refusal(mention_only, human) == "MISSING_SOURCE_CLAIM_VERIFICATION"
    assert plan_of(mention_only, (human,)).assertion_class is AssertionClass.HUMAN_ASSERTED


def test_rr_34_case_f_an_llm_proposal_reaches_human_asserted_unchanged() -> None:
    machine = backed(RelationProposerClass.LLM, tag="g")
    plan = plan_of(machine, (accept(machine, AssertionClass.HUMAN_ASSERTED),))
    assert plan.assertion_class is AssertionClass.HUMAN_ASSERTED and plan.source_attribution is None
    assert plan.verification_origin is None
    assert plan.proposal_origin.proposer_class is RelationProposerClass.LLM


def test_rr_35_case_l_a_non_human_verifier_is_refused() -> None:
    candidate = backed()
    base = verification(candidate).as_dict()
    for actor in [value.value for value in ProvenanceClass if value is not ProvenanceClass.HUMAN]:
        with pytest.raises(RelationProposalError) as info:
            SourceClaimVerification.from_dict({**base, "verifier_class": actor})
        assert info.value.code == "FORBIDDEN_VERIFICATION_AUTHORITY", actor
    with pytest.raises(RelationProposalError) as info:                   # 語彙外は別 code で fail closed
        SourceClaimVerification.from_dict({**base, "verifier_class": "SOURCE"})
    assert info.value.code == "INVALID_VOCABULARY"
    assert {value.value for value in ProvenanceClass} == {"RULE", "HUMAN", "LLM_PROPOSAL"}


def test_rr_36_case_m_a_verification_later_than_its_decision_is_refused() -> None:
    candidate = backed()
    with pytest.raises(RelationProposalError) as info:
        accept(candidate, AssertionClass.SOURCE_ASSERTED,
               verified=verification(candidate, at=DECIDED_AT + timedelta(microseconds=1)))
    assert info.value.code == "VERIFICATION_AFTER_DECISION"
    assert accept(candidate, AssertionClass.SOURCE_ASSERTED,
                  verified=verification(candidate, at=DECIDED_AT)).source_claim_verification.verified_at == DECIDED_AT


@pytest.mark.parametrize("shift,code", [(dict(relation_type=RelationType.CAUSES), "VERIFICATION_RELATION_TYPE_MISMATCH"),
                                        (dict(target=C), "VERIFICATION_ENDPOINT_MISMATCH"),
                                        (dict(source=C), "VERIFICATION_ENDPOINT_MISMATCH")])
def test_rr_37_39_case_n_a_verification_cannot_be_reused_across_semantics(shift, code) -> None:
    donor = backed()
    other = backed(**shift)
    assert other.proposal_id != donor.proposal_id
    borrowed = accept(other, AssertionClass.SOURCE_ASSERTED, verified=verification(donor))
    assert source_asserted_refusal(other, borrowed) == code
    refuses(code, other, (borrowed,))


# ================================================================ §4 RULE / LLM 抽出 matrix


@pytest.mark.parametrize("proposer", [RelationProposerClass.RULE, RelationProposerClass.LLM])
def test_rr_40_41_a_source_backed_machine_proposal_reaches_source_asserted(proposer) -> None:
    """A / B: 機械が出典裏付きで提案し、人間が所在を確認して受理すれば SOURCE_ASSERTED になる。"""
    candidate = backed(proposer, tag="m")
    plan = plan_of(candidate, (accept(candidate, AssertionClass.SOURCE_ASSERTED),))
    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert plan.proposal_origin.proposer_class is proposer          # 提案者は HUMAN に書き換えられない
    assert plan.proposal_origin.proposer_ref == f"{proposer.value.lower()}:relation_candidate"
    assert plan.verification_origin.verifier_class is ProvenanceClass.HUMAN
    assert plan.decision_origin.actor_class is ProvenanceClass.HUMAN
    assert json.loads(plan.canonical_line())["proposal_origin"]["proposer_class"] == proposer.value


@pytest.mark.parametrize("proposer", [RelationProposerClass.RULE, RelationProposerClass.LLM])
def test_rr_42_43_a_machine_inference_with_a_bare_citation_is_refused(proposer) -> None:
    """C / D: citation を貼っただけの機械推論は受理されない。"""
    candidate = candidate_of(proposer, refs=(cited("n"),), rationale="inferred without a source claim")
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    assert source_asserted_refusal(candidate, decision) == "MISSING_SOURCE_ATTRIBUTION"
    refuses("MISSING_SOURCE_ATTRIBUTION", candidate, (decision,))
    dressed = candidate_of(proposer, attribution=ATTRIBUTION, refs=(cited("n", attribution=""),),
                           rationale="inferred, generic citation attached")
    refuses("VERIFICATION_CITATION_ATTRIBUTION_MISMATCH", dressed,
            (accept(dressed, AssertionClass.SOURCE_ASSERTED),))


@pytest.mark.parametrize("proposer", PROPOSER_CLASSES)
def test_rr_44_47_the_proposer_class_survives_every_acceptance(proposer) -> None:
    candidate = backed(proposer, tag="p")
    for accepted in (AssertionClass.HUMAN_ASSERTED, AssertionClass.SOURCE_ASSERTED):
        plan = plan_of(candidate, (accept(candidate, accepted),))
        assert plan.proposal_origin.proposer_class is proposer
        assert ProvenanceClass.HUMAN is plan.decision_origin.actor_class
        assert plan.proposal_origin.proposer_class.value not in ("HUMAN_ASSERTED", "SOURCE_ASSERTED")


# ================================================================ §5 確認の identity と再利用


def test_rr_48_the_verification_binds_nine_axes_and_carries_no_truth_flag() -> None:
    subject = verification(backed())
    fields = set(dataclasses.asdict(subject))
    assert fields == {"schema_version", "attributed_to", "evidence_kind", "evidence_ref_id", "assertion_locus",
                      "claim_summary", "source_theme_root_id", "target_theme_root_id", "relation_type",
                      "verifier_class", "verified_by", "verified_at"}
    assert not [name for name in fields if name in ("verified", "is_valid", "ok", "approved", "trusted")]
    with pytest.raises(dataclasses.FrozenInstanceError):
        subject.claim_summary = "x"                                  # type: ignore[misc]


@pytest.mark.parametrize("field,value", [("assertion_locus", "section:9"), ("claim_summary", "a different reading"),
                                         ("attributed_to", "publisher:other_wire"), ("verified_by", "reviewer:r2"),
                                         ("verified_at", T0 - timedelta(hours=1))])
def test_rr_49_53_changing_an_authorization_field_changes_the_decision_identity(field, value) -> None:
    candidate = backed()
    base = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    shifted = accept(candidate, AssertionClass.SOURCE_ASSERTED,
                     verified=dataclasses.replace(base.source_claim_verification, **{field: value}))
    assert shifted.decision_id != base.decision_id, field
    assert shifted.identity_payload()["source_claim_verification"] \
        != base.identity_payload()["source_claim_verification"]


def test_rr_54_an_identical_authorization_converges_on_one_decision_id() -> None:
    candidate = backed()
    left = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    right = accept(candidate, AssertionClass.SOURCE_ASSERTED, verified=verification(candidate))
    assert left.decision_id == right.decision_id
    assert canonical_proposal_record_line(left) == canonical_proposal_record_line(right)


def test_rr_55_a_verification_cannot_be_replaced_after_the_acceptance() -> None:
    candidate = backed()
    decided = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    for swap in (verification(candidate, locus="section:9"), verification(candidate, verifier="reviewer:r2")):
        with pytest.raises(RelationProposalError) as info:
            dataclasses.replace(decided, source_claim_verification=swap)
        assert info.value.code == "INVALID_RECORD_ID"


# ================================================================ §6 帰属 / citation の束縛


def test_rr_56_matching_is_the_shared_deterministic_normalization_not_a_fuzzy_match() -> None:
    """一致は NFKC → 空白圧縮 → strip → casefold の後の**完全一致**。B5B の attribution_key と同じ規約。"""
    candidate = backed()
    named = ATTRIBUTION.attributed_to
    assert normalize_text("  Publisher:Example_Wire ") == normalize_text(named)
    cased = accept(candidate, AssertionClass.SOURCE_ASSERTED,
                   verified=verification(candidate, attributed_to=" Publisher:Example_Wire "))
    assert source_asserted_refusal(candidate, cased) == ""            # 正規化の範囲は一致する
    for near in ("publisher:example wire", "publisher:examplewire", "publisher:example_wires", "example_wire"):
        assert normalize_text(near) != normalize_text(named)
        drifted = accept(candidate, AssertionClass.SOURCE_ASSERTED,
                         verified=verification(candidate, attributed_to=near))
        assert source_asserted_refusal(candidate, drifted) == "VERIFICATION_ATTRIBUTION_MISMATCH", near


def test_rr_57_no_publisher_or_entity_equivalence_is_inferred() -> None:
    """同じ発行体を指す別表記は等価と見なされない（推定をしない）。"""
    candidate = candidate_of(RelationProposerClass.RULE, attribution=SourceAttribution(attributed_to="publisher:mof"),
                             refs=(cited("q", attribution="publisher:mof"),))
    for alias in ("publisher:ministry_of_finance", "mof", "publisher:mof_japan"):
        drifted = accept(candidate, AssertionClass.SOURCE_ASSERTED,
                         verified=verification(candidate, attributed_to=alias))
        assert source_asserted_refusal(candidate, drifted) == "VERIFICATION_ATTRIBUTION_MISMATCH", alias


def test_rr_58_a_citation_outside_the_proposal_evidence_set_is_refused() -> None:
    candidate = backed()
    stranger = accept(candidate, AssertionClass.SOURCE_ASSERTED,
                      verified=verification(candidate, evidence_ref=cited("zz",
                                                                          attribution=ATTRIBUTION.attributed_to)))
    assert source_asserted_refusal(candidate, stranger) == "VERIFICATION_CITATION_MISMATCH"


def test_rr_59_only_the_verified_citation_needs_to_carry_the_attribution() -> None:
    """複数 citation のうち確認された 1 件が帰属を担う。他の citation の帰属は問わない。"""
    verified_ref = cited("s1", attribution=ATTRIBUTION.attributed_to, locator="section:3")
    other_ref = cited("s2", attribution="")
    candidate = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(verified_ref, other_ref),
                             rationale="two citations, one carries the claim")
    good = accept(candidate, AssertionClass.SOURCE_ASSERTED, verified=verification(candidate, evidence_ref=verified_ref))
    assert source_asserted_refusal(candidate, good) == ""
    plan = plan_of(candidate, (good,))
    assert plan.verification_origin.evidence_ref_id == verified_ref.ref_id
    assert len(plan.evidence_refs) == 2                              # 提案の citation は落とさない
    bad = accept(candidate, AssertionClass.SOURCE_ASSERTED, verified=verification(candidate, evidence_ref=other_ref))
    assert source_asserted_refusal(candidate, bad) == "VERIFICATION_CITATION_ATTRIBUTION_MISMATCH"


def test_rr_60_the_evidence_kind_is_part_of_the_citation_identity() -> None:
    candidate = backed()
    subject = verification(candidate)
    assert subject.evidence_key == f"{EvidenceKind.SOURCE_DOCUMENT.value}:{subject.evidence_ref_id}"
    assert candidate.evidence_refs[0].evidence_key == subject.evidence_key


# ================================================================ §7 主張の所在


def test_rr_61_the_locus_and_the_claim_summary_are_required_and_bounded() -> None:
    from src.intelligence.theme_intelligence.relation_proposal_model import MAX_LOCUS_LEN, MAX_TEXT_LEN
    base = verification(backed()).as_dict()
    for field, limit in (("assertion_locus", MAX_LOCUS_LEN), ("claim_summary", MAX_TEXT_LEN)):
        with pytest.raises(RelationProposalError) as info:
            SourceClaimVerification.from_dict({**base, field: ""})
        assert info.value.code == "MISSING_FIELD", field
        with pytest.raises(RelationProposalError) as info:
            SourceClaimVerification.from_dict({**base, field: "x" * (limit + 1)})
        assert info.value.code == "FIELD_TOO_LONG", field
        assert SourceClaimVerification.from_dict({**base, field: "x" * limit})
    assert (MAX_LOCUS_LEN, MAX_TEXT_LEN) == (200, 240)               # 長文引用を要求しない


def test_rr_62_the_locus_carries_the_prohibited_content_guard() -> None:
    base = verification(backed()).as_dict()
    drive = "D" + ":" + chr(92) + "research" + chr(92) + "note"
    unc = chr(92) * 2 + "host" + chr(92) + "share"
    for field in ("assertion_locus", "claim_summary"):
        for bad in (drive, unc, "https://user:pw@example.invalid/x", "https://example.invalid/x?api_key=zz"):
            with pytest.raises(RelationProposalError) as info:
                SourceClaimVerification.from_dict({**base, field: bad})
            assert info.value.code == "PROHIBITED_CONTENT", (field, bad[:12])


def test_rr_63_the_locus_is_free_text_with_no_normalization_scheme() -> None:
    """既知の限界: 所在の表記規約は強制していない（本 gate では導入しない）。"""
    base = verification(backed()).as_dict()
    for shape in ("section:2", "p.14", "paragraph 3", "annex-b#2"):
        assert SourceClaimVerification.from_dict({**base, "assertion_locus": shape}).assertion_locus == shape
    source = executable_source(PACKAGE_DIR / "relation_proposal_model.py")
    for token in ("locus_key", "normalize_locus", "canonical_locus"):
        assert token not in source, token


# ================================================================ §8 時刻 / PIT


def test_rr_64_the_four_times_form_one_monotone_chain() -> None:
    candidate = backed(at=T0)
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED, at=DECIDED_AT,
                      verified=verification(candidate, at=T0 + timedelta(minutes=30)))
    plan = plan_of(candidate, (decision,), at=PLANNED_AT)
    verified_at = decision.source_claim_verification.verified_at
    assert candidate.created_at <= verified_at <= decision.recorded_at <= plan.recorded_at


def test_rr_65_every_boundary_is_inclusive_and_one_microsecond_is_not() -> None:
    candidate = backed(at=T0)
    flat = accept(candidate, AssertionClass.SOURCE_ASSERTED, at=T0, verified=verification(candidate, at=T0))
    assert plan_of(candidate, (flat,), at=T0).recorded_at == T0          # すべて同時刻は許される
    tick = timedelta(microseconds=1)
    with pytest.raises(RelationProposalError) as info:
        accept(candidate, AssertionClass.SOURCE_ASSERTED, at=T0, verified=verification(candidate, at=T0 + tick))
    assert info.value.code == "VERIFICATION_AFTER_DECISION"
    early = accept(candidate, AssertionClass.SOURCE_ASSERTED, at=T0, verified=verification(candidate, at=T0 - tick))
    assert source_asserted_refusal(candidate, early) == "VERIFICATION_BEFORE_PROPOSAL"
    refuses("PLAN_BEFORE_PROPOSAL", candidate, (flat,), at=T0 - tick)     # 提案時刻の検査が先に当たる
    later = accept(candidate, AssertionClass.SOURCE_ASSERTED, at=DECIDED_AT, verified=verification(candidate, at=T0))
    assert plan_of(candidate, (later,), at=DECIDED_AT).recorded_at == DECIDED_AT
    refuses("PLAN_BEFORE_DECISION", candidate, (later,), at=DECIDED_AT - tick)


def test_rr_66_a_naive_verification_time_fails_closed_on_every_path() -> None:
    """構築経路は `INVALID_TIME`、復元経路は素の ValueError。store はどちらも INVALID_RECORD にする。

    復元経路が `RelationProposalError` でないのは B5C 既存の `from_iso` 規約であり、R1 が持ち込んだものではない
    （提案の `created_at`・決定の `recorded_at` も同じ）。いずれも fail closed で、bypass にはならない。
    """
    candidate = backed()
    base = verification(candidate)
    with pytest.raises(RelationProposalError) as info:
        dataclasses.replace(base, verified_at=datetime(2026, 9, 20))
    assert info.value.code == "INVALID_TIME"
    with pytest.raises(ValueError):
        SourceClaimVerification.from_dict({**base.as_dict(), "verified_at": "2026-09-20T00:00:00"})
    with pytest.raises(ValueError):                                       # 既存 field も同じ規約
        RelationProposalDecision.from_dict({**accept(candidate, AssertionClass.SOURCE_ASSERTED).as_dict(),
                                            "recorded_at": "2026-09-20T01:00:00"})


def test_rr_66b_a_naive_time_in_a_stored_line_is_store_corruption(tmp_path) -> None:
    store = store_at(tmp_path, name="naive")
    candidate = backed()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    store.append_proposal(candidate)
    store.append_decision(decision)
    payload = json.loads(canonical_proposal_record_line(decision))
    payload["source_claim_verification"]["verified_at"] = "2026-09-20T00:00:00"
    store.paths["decisions"].write_bytes(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n")
    with pytest.raises(RelationProposalStoreCorrupt) as info:
        RelationProposalStore.open(tmp_path / "naive")
    assert info.value.code == "INVALID_RECORD"


def test_rr_67_the_r1_surface_reads_no_current_clock_and_no_randomness() -> None:
    for name in B5_RUNTIME_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in (".now(", "utcnow", "time.time", "random.", "secrets.", "uuid", "monotonic"):
            assert token not in source, f"{name}:{token}"


@pytest.mark.parametrize("seed", SEEDS)
def test_rr_68_a_verified_chain_replays_deterministically(seed) -> None:
    candidate = backed()
    chain = [decide(candidate, RelationDecisionKind.DEFER, reason="hold")]
    for index in range(1, 3):
        chain.append(decide(candidate, RelationDecisionKind.DEFER, at=DECIDED_AT + timedelta(hours=index),
                            supersedes=chain[-1].decision_id, reason=f"hold {index}"))
    chain.append(accept(candidate, AssertionClass.SOURCE_ASSERTED, at=DECIDED_AT + timedelta(hours=3),
                        supersedes=chain[-1].decision_id, reason="locus confirmed"))
    ordered = plan_of(candidate, tuple(chain), at=PLANNED_AT + timedelta(hours=3)).canonical_line()
    shuffled = list(chain)
    random.Random(seed).shuffle(shuffled)
    assert plan_of(candidate, tuple(shuffled), at=PLANNED_AT + timedelta(hours=3)).canonical_line() == ordered


# ================================================================ §9 決定 graph（R1 で変わっていないこと）


def test_rr_69_the_decision_graph_rules_are_untouched_by_the_verification() -> None:
    candidate = backed()
    assert derive_relation_proposal_status(candidate, ()) is RelationProposalStatus.OPEN
    first = decide(candidate, RelationDecisionKind.DEFER, reason="hold")
    assert derive_relation_proposal_status(candidate, (first,)) is RelationProposalStatus.OPEN_DEFERRED
    accepted = accept(candidate, AssertionClass.SOURCE_ASSERTED, at=DECIDED_AT + timedelta(hours=1),
                      supersedes=first.decision_id, reason="verified")
    assert derive_relation_proposal_status(candidate, (first, accepted)) is RelationProposalStatus.ACCEPTED
    rejected = decide(candidate, RelationDecisionKind.REJECT, at=DECIDED_AT + timedelta(hours=2),
                      supersedes=accepted.decision_id, reason="withdrawn")
    chain = (first, accepted, rejected)
    assert derive_relation_proposal_status(candidate, chain) is RelationProposalStatus.REJECTED
    refuses("PROPOSAL_NOT_ACCEPTED", candidate, chain, at=PLANNED_AT + timedelta(hours=2))


def test_rr_70_a_forked_or_multi_genesis_verified_history_stays_unresolved() -> None:
    candidate = backed()
    seed = accept(candidate, AssertionClass.SOURCE_ASSERTED, reason="first")
    left = decide(candidate, RelationDecisionKind.REJECT, at=DECIDED_AT + timedelta(hours=1),
                  supersedes=seed.decision_id, reason="branch one")
    right = decide(candidate, RelationDecisionKind.DEFER, at=DECIDED_AT + timedelta(hours=2),
                   supersedes=seed.decision_id, reason="branch two")
    assert derive_relation_proposal_status(candidate, (seed, left, right)) is RelationProposalStatus.OPEN_UNRESOLVED
    twin = accept(candidate, AssertionClass.SOURCE_ASSERTED, reason="second genesis")
    assert derive_relation_proposal_status(candidate, (seed, twin)) is RelationProposalStatus.OPEN_UNRESOLVED


def test_rr_71_a_chain_external_newer_verified_accept_never_wins() -> None:
    candidate = backed()
    first = decide(candidate, RelationDecisionKind.DEFER, reason="first")
    terminal = decide(candidate, RelationDecisionKind.REJECT, at=DECIDED_AT + timedelta(hours=1),
                      supersedes=first.decision_id, reason="terminal reject")
    stray = accept(candidate, AssertionClass.SOURCE_ASSERTED, at=DECIDED_AT + timedelta(days=9),
                   reason="late but outside the chain")
    assert derive_relation_proposal_status(candidate, (first, terminal, stray)) \
        is RelationProposalStatus.OPEN_UNRESOLVED


# ================================================================ §10 HUMAN_ASSERTED の非退行


@pytest.mark.parametrize("proposer", PROPOSER_CLASSES)
def test_rr_72_75_every_proposer_class_still_reaches_human_asserted(proposer) -> None:
    candidate = candidate_of(proposer)
    plan = plan_of(candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),))
    assert plan.assertion_class is AssertionClass.HUMAN_ASSERTED
    assert plan.source_attribution is None                            # B5B の ATTRIBUTION_FORBIDDEN
    assert plan.verification_origin is None                           # 確認は要求されない
    assert plan.proposal_origin.proposer_class is proposer
    assembled = ThemeRelationAssertion.build(
        source_theme_root_id=plan.source_theme_root_id, target_theme_root_id=plan.target_theme_root_id,
        relation_type=plan.relation_type, assertion_class=plan.assertion_class, rationale=plan.rationale,
        evidence_refs=plan.evidence_refs, source_attribution=plan.source_attribution,
        previous_assertion_id=plan.previous_assertion_id, provenance=ACTOR, recorded_at=plan.recorded_at)
    assert assembled.source_attribution is None


def test_rr_76_a_human_asserted_accept_rejects_an_attached_verification() -> None:
    candidate = backed()
    with pytest.raises(RelationProposalError) as info:
        accept(candidate, AssertionClass.HUMAN_ASSERTED, verified=verification(candidate))
    assert info.value.code == "SOURCE_CLAIM_VERIFICATION_FORBIDDEN"
    plan = plan_of(candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),))
    assert plan.proposal_origin.proposal_source_attribution == ATTRIBUTION.attributed_to   # 提案側は保持される


# ================================================================ §11 B5B 互換性 / §12 authority 非改変


def test_rr_77_the_r1_plan_constructs_the_frozen_b5b_assertion(tmp_path) -> None:
    candidate = backed()
    plan = plan_of(candidate, (accept(candidate, AssertionClass.SOURCE_ASSERTED),))
    assembled = ThemeRelationAssertion.build(
        source_theme_root_id=plan.source_theme_root_id, target_theme_root_id=plan.target_theme_root_id,
        relation_type=plan.relation_type, assertion_class=plan.assertion_class, rationale=plan.rationale,
        evidence_refs=plan.evidence_refs, source_attribution=plan.source_attribution,
        previous_assertion_id=plan.previous_assertion_id, provenance=ACTOR, recorded_at=plan.recorded_at)
    body = json.loads(canonical_relation_line(assembled))
    assert set(body) == {"schema_version", "relation_vocab_version", "relation_assertion_id", "source_theme_root_id",
                         "target_theme_root_id", "relation_type", "assertion_class", "source_attribution",
                         "rationale", "evidence_refs", "previous_assertion_id", "provenance", "recorded_at"}
    for token in ("verification", "assertion_locus", "claim_summary", "verified_by", "verified_at"):
        assert token not in json.dumps(body), token
    assert not any(path.exists() for path in relation_authority_paths(tmp_path / "data").values())


def test_rr_78_the_verification_never_becomes_a_b5b_field() -> None:
    from src.intelligence.theme_intelligence import relation_model
    assert "source_claim_verification" not in relation_model.ASSERTION_FIELDS
    assert "SourceClaimVerification" not in executable_source(PACKAGE_DIR / "relation_model.py")
    assert "SourceClaimVerification" not in executable_source(PACKAGE_DIR / "relation_store.py")


def test_rr_79_the_whole_chain_leaves_foundation_and_b5b_byte_identical(tmp_path) -> None:
    from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
    from tests.intelligence.theme_foundation_fixtures import authority_bytes, build_world, resolution_digest
    world = build_world(tmp_path / "data", stop_after="accepted")
    ThemeRelationStore.initialize(world.data_root)
    foundation_before = authority_bytes(world.data_root)
    relation_before = {name: path.read_bytes() for name, path in relation_authority_paths(world.data_root).items()}
    digest_before = [resolution_digest(world.resolve(key, "accepted")) for key in ("A", "B")]

    store = RelationProposalStore.initialize(world.data_root)
    candidate = backed()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    store.append_proposal(candidate)
    store.append_decision(decision)
    plan = plan_of(candidate, (decision,))

    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert authority_bytes(world.data_root) == foundation_before and len(foundation_before) == 5
    assert {name: path.read_bytes() for name, path in relation_authority_paths(world.data_root).items()} \
        == relation_before
    assert [resolution_digest(world.resolve(key, "accepted")) for key in ("A", "B")] == digest_before
    assert ThemeRelationStore.open(world.data_root).counts() == {"assertions": 0, "governance": 0}
    assert store.counts() == {"proposals": 1, "decisions": 1}


def test_rr_80_an_accept_is_not_an_assertion_append_and_a_plan_is_not_authority() -> None:
    plan = plan_of(backed(), (accept(backed(), AssertionClass.SOURCE_ASSERTED),))
    assert not hasattr(plan, "relation_assertion_id")
    assert "relation_assertion_id" not in plan.to_plain()
    bridge = executable_source(PACKAGE_DIR / "relation_proposal_bridge.py")
    for token in ("append_assertion", "append_event", "ThemeRelationStore", "relation_store"):
        assert token not in bridge, token


# ================================================================ §13 因果安全性 corpus（synthetic gate result only）


def test_rr_81_no_overlap_signal_creates_relation_authority(tmp_path) -> None:
    """共起 / entity / taxonomy / evidence / 時間近接 / 相関 / rule 出力 / LLM 出力 — いずれも authority を作らない。

    本節の結果は **synthetic gate result only**。実世界の precision / recall を主張しない。
    """
    from tests.intelligence.test_theme_relation_causal_safety import CORPUS, SYNTHETIC_RESULT_LABEL, authored
    assert SYNTHETIC_RESULT_LABEL == "synthetic gate result only" and len(CORPUS) == 14
    store = store_at(tmp_path, name="corpus")
    assert store.counts() == {"proposals": 0, "decisions": 0}
    for row in CORPUS:
        candidate = authored(row)
        assert derive_relation_proposal_status(candidate, ()) is RelationProposalStatus.OPEN
    assert RelationProposalStore.open(tmp_path / "corpus").counts()["proposals"] == 0
    assert not any(path.exists() for path in relation_authority_paths(tmp_path / "corpus").values())


def test_rr_82_every_corpus_row_needs_the_human_source_claim_contract() -> None:
    from tests.intelligence.test_theme_relation_causal_safety import CORPUS, authored
    for row in CORPUS:
        candidate = authored(row)
        human = RelationProposalDecision.build(proposal_id=candidate.proposal_id,
                                               decision=RelationDecisionKind.ACCEPT,
                                               accepted_assertion_class=AssertionClass.HUMAN_ASSERTED,
                                               actor_ref="reviewer:r1", reason=f"reviewed {row.key}",
                                               recorded_at=T0 + timedelta(hours=1))
        refusal = source_asserted_refusal(candidate, human)
        assert refusal in ("MISSING_SOURCE_ATTRIBUTION", "MISSING_SOURCE_CITATION",
                           "MISSING_SOURCE_CLAIM_VERIFICATION"), (row.key, refusal)


# ================================================================ §14 推移的推論


def test_rr_83_two_causal_edges_still_produce_no_third() -> None:
    from src.intelligence.theme_intelligence.relation_graph import build_relation_graph_view
    from src.intelligence.theme_intelligence.relation_resolution import resolve_relation_graph
    from tests.intelligence.test_theme_relation_proposal import b5b_assertion, lookup
    first = b5b_assertion(source=A, target=B, relation_type=RelationType.CAUSES, refs=(cited("t"),))
    second = b5b_assertion(source=B, target=C, relation_type=RelationType.CAUSES, refs=(cited("u"),))
    resolution = resolve_relation_graph([first, second], [], cutoff=T0 + timedelta(days=7), endpoint_lookup=lookup())
    view = build_relation_graph_view(resolution)
    assert len(resolution.edges) == 2 and view.relations_between(A, C) == ()
    implied = proposal(source=A, target=C, relation_type=RelationType.CAUSES, refs=(cited("v"),),
                       rationale="implied by the two recorded causal edges")
    refuses("PROPOSAL_NOT_ACCEPTED", implied, (), existing=resolution.edges)
    refuses("MISSING_SOURCE_ATTRIBUTION", implied, (accept(implied, AssertionClass.SOURCE_ASSERTED),),
            existing=resolution.edges)


def test_rr_84_no_ranking_centrality_or_path_surface_exists() -> None:
    from src.intelligence.theme_intelligence import relation_graph
    methods = {name for name in dir(relation_graph.ThemeRelationGraphView) if not name.startswith("_")}
    assert methods == {"outgoing", "incoming", "neighbors", "relations_between", "relations_by_type", "roots",
                       "to_plain"}
    for name in B5_RUNTIME_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("centrality", "pagerank", "closure", "transitive", "shortest", "degree_rank"):
            assert token not in source.lower(), f"{name}:{token}"


# ================================================================ §15 提案収束（R1 で変わっていないこと）


def test_rr_85_the_proposal_identity_payload_is_unchanged_by_r1() -> None:
    identity = executable_source(PACKAGE_DIR / "relation_proposal_model.py")
    body = identity.split("def identity_payload")[1].split("def ")[0]
    for token in ("provenance", "created_at", "proposer", "verification"):
        assert token not in body, token
    keys = set(backed().identity_payload())
    assert keys == {"schema_version", "proposal_type", "relation_vocab_version", "source_theme_root_id",
                    "target_theme_root_id", "relation_type", "change_kind", "previous_assertion_id",
                    "source_attribution", "rationale", "evidence_refs"}


def test_rr_86_the_convergence_matrix_behaves_as_before(tmp_path) -> None:
    shared = dict(attribution=ATTRIBUTION, refs=(cited("m", attribution=ATTRIBUTION.attributed_to),),
                  rationale="the release links the two themes")
    left = candidate_of(RelationProposerClass.RULE, **shared)
    right = candidate_of(RelationProposerClass.LLM, **shared)
    assert left.proposal_id == right.proposal_id and left.identity_payload() == right.identity_payload()
    assert canonical_proposal_record_line(left) != canonical_proposal_record_line(right)
    store = store_at(tmp_path, name="converge")
    assert store.append_proposal(left).status is AppendStatus.APPENDED
    with pytest.raises(RelationProposalConflict):
        store.append_proposal(right)
    assert store.append_proposal(left).status is AppendStatus.ALREADY_PRESENT
    versioned = proposal(proposer=RelationProposerClass.RULE, proposer_ref="rule:alpha", rule_version="2.0.0", **shared)
    assert versioned.proposal_id == left.proposal_id
    with pytest.raises(RelationProposalConflict):
        store.append_proposal(versioned)


def test_rr_87_no_convergence_helper_was_introduced() -> None:
    for name in B5C_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("CONVERGENT_PROPOSAL", "append_or_reuse", "co_discovery", "converged_proposal_ids"):
            assert token not in source, f"{name}:{token}"


# ================================================================ §16 store 安全性 ＋ 改ざんされた確認 record


def test_rr_88_the_store_discipline_is_unchanged(tmp_path) -> None:
    store = store_at(tmp_path, name="disc")
    candidate = backed()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    store.append_proposal(candidate)
    store.append_decision(decision)
    sizes = {name: path.stat().st_size for name, path in store.paths.items()}
    assert store.append_decision(decision).status is AppendStatus.ALREADY_PRESENT
    assert {name: path.stat().st_size for name, path in store.paths.items()} == sizes
    with store.paths["decisions"].open("ab") as handle:
        handle.write(b" ")
    from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalConcurrentModification
    with pytest.raises(RelationProposalConcurrentModification):
        store.append_decision(decide(candidate, RelationDecisionKind.DEFER, reason="second"))
    source = executable_source(PACKAGE_DIR / "relation_proposal_store.py")
    for token in ("migrat", "repair", "os.replace", "truncate(", "unlink("):
        assert token not in source, token
    assert "fsync" in source


@pytest.mark.parametrize("payload,reason", [
    (b"not json\n", "MALFORMED_JSON"),
    (b'[1,2]\n', "NOT_AN_OBJECT"),
    (b"\n", "BLANK_LINE"),
    (b'{"schema_version":"theme_relation_unknown:9.9.9"}\n', "UNSUPPORTED_SCHEMA_VERSION"),
])
def test_rr_89_92_corrupt_decision_bytes_fail_closed(tmp_path, payload, reason) -> None:
    store = store_at(tmp_path, name=reason.lower())
    store.paths["decisions"].write_bytes(payload)
    with pytest.raises(RelationProposalStoreCorrupt) as info:
        RelationProposalStore.open(tmp_path / reason.lower())
    assert info.value.code == reason


def test_rr_93_a_stored_source_asserted_accept_without_a_verification_is_corruption(tmp_path) -> None:
    """復元経路は runtime の構築規律を回避させない。"""
    store = store_at(tmp_path, name="stripped")
    candidate = backed()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    store.append_proposal(candidate)
    store.append_decision(decision)
    payload = json.loads(canonical_proposal_record_line(decision))
    payload["source_claim_verification"] = None
    store.paths["decisions"].write_bytes(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n")
    with pytest.raises(RelationProposalStoreCorrupt) as info:
        RelationProposalStore.open(tmp_path / "stripped")
    assert info.value.code == "INVALID_RECORD"


def test_rr_94_a_stored_verification_that_mismatches_its_proposal_is_invalid_history(tmp_path) -> None:
    """record 単体としては妥当でも、提案との束縛が崩れていれば load で fail closed になる。"""
    store = store_at(tmp_path, name="mismatch")
    subject = backed()
    donor = backed(target=C)
    store.append_proposal(subject)
    crossed = RelationProposalDecision.build(proposal_id=subject.proposal_id, decision=RelationDecisionKind.ACCEPT,
                                             accepted_assertion_class=AssertionClass.SOURCE_ASSERTED,
                                             source_claim_verification=verification(donor), actor_ref="reviewer:r1",
                                             reason="borrowed verification", recorded_at=DECIDED_AT)
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(crossed)
    assert info.value.code == "VERIFICATION_ENDPOINT_MISMATCH"
    store.paths["decisions"].write_bytes(canonical_proposal_record_line(crossed).encode("utf-8"))
    with pytest.raises(RelationProposalInvalidHistory) as info:
        RelationProposalStore.open(tmp_path / "mismatch")
    assert info.value.code == "VERIFICATION_ENDPOINT_MISMATCH"


def test_rr_95_a_noncanonical_verification_line_is_refused(tmp_path) -> None:
    store = store_at(tmp_path, name="noncanon")
    candidate = backed()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    store.append_proposal(candidate)
    store.append_decision(decision)
    line = canonical_proposal_record_line(decision)
    store.paths["decisions"].write_bytes(line.replace('"source_claim_verification":{',
                                                      '"source_claim_verification": {').encode("utf-8"))
    with pytest.raises(RelationProposalStoreCorrupt) as info:
        RelationProposalStore.open(tmp_path / "noncanon")
    assert info.value.code in ("NON_CANONICAL_LINE", "INVALID_RECORD"), info.value.code


# ================================================================ §17 import / 自動化の境界


@pytest.mark.parametrize("name", B5_RUNTIME_MODULES)
def test_rr_96_103_no_verifier_network_or_automation_surface(name) -> None:
    source = executable_source(PACKAGE_DIR / f"{name}.py")
    modules = imported_modules(PACKAGE_DIR / f"{name}.py")
    for token in ("nltk", "spacy", "transformers", "embedding", "classifier", "tokenize", "anthropic", "openai",
                  "requests", "urllib", "socket", "httpx", "sqlite", "subprocess"):
        assert token not in source.lower(), f"{name}:{token}"
        assert not any(token in module.lower() for module in modules), f"{name}:{token}"
    for token in ("auto_accept", "auto_verify", "verify_claim", "classify", "infer_relation", "discover"):
        assert token not in source, f"{name}:{token}"


def test_rr_104_nothing_in_the_package_appends_to_the_relation_authority() -> None:
    for name in B5C_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("append_assertion", "append_event", "ThemeRelationStore", "relation_store"):
            assert token not in source, f"{name}:{token}"


def test_rr_105_the_package_module_set_is_unchanged_by_r1() -> None:
    """R1 が B5 の module 集合を変えていないこと。package 全体の inventory は import boundary guard が持つ
    （後続 phase が module を追加しても、この test は B5 の面だけを見る）。"""
    present = sorted(p.stem for p in PACKAGE_DIR.glob("*.py"))
    assert present.count("relation_proposal_model") == 1
    assert sorted(p.stem for p in PACKAGE_DIR.glob("relation*.py")) == sorted(B5_RUNTIME_MODULES)
    assert not list(PACKAGE_DIR.glob("*.jsonl")) and not list(PACKAGE_DIR.glob("*.sqlite3"))


# ================================================================ §24 既知の限界（将来 gate への申し送り）


def test_rr_106_the_plan_value_object_carries_no_validation_of_its_own() -> None:
    """`RelationAssertionPlan` は値 object であり、直接構築すれば bridge の検査を経ない。

    plan は authority ではなく、B5B へ追記する実行 gate は本 phase に存在しないため安全である。
    ただし将来の実行 gate は、渡された plan object を信頼せず、提案と決定から再導出するか再検査すること。
    """
    from src.intelligence.theme_intelligence.relation_proposal_bridge import RelationAssertionPlan
    assert "__post_init__" not in vars(RelationAssertionPlan)
    candidate = backed()
    genuine = plan_of(candidate, (accept(candidate, AssertionClass.SOURCE_ASSERTED),))
    forged = dataclasses.replace(genuine, verification_origin=None)     # 検査なしで確認を落とせてしまう
    assert forged.assertion_class is AssertionClass.SOURCE_ASSERTED and forged.verification_origin is None
    assert not hasattr(forged, "relation_assertion_id")                 # だが authority にはならない
    bridge = executable_source(PACKAGE_DIR / "relation_proposal_bridge.py")
    assert "append" not in bridge.lower().replace("plan_relation_assertion_from_accepted_proposal", "")


def test_rr_107_the_store_module_docstring_still_carries_the_pre_r1_wording() -> None:
    """NON-BLOCKING の記録: store の module docstring だけが R1 前の文言のまま残っている。

    実行経路は `source_asserted_refusal` に一本化済みで挙動は正しい（test_rr_01 / test_rr_02）。
    本 gate は TEST / DOC ONLY のため src/ を修正しない。docstring のみの後続修正として申し送る。
    """
    import src.intelligence.theme_intelligence.relation_proposal_store as store_module
    docstring = store_module.__doc__ or ""
    stale = "SOURCE_ASSERTED としての受理は提案に出典の帰属と citation が実在する場合にのみ許すこと"
    assert stale in docstring, "docstring drift was fixed; update this record"
    assert "SourceClaimVerification" not in docstring
    executable = executable_source(PACKAGE_DIR / "relation_proposal_store.py")
    assert stale not in executable and "source_asserted_refusal" in executable   # 実行経路は R1 のまま
