"""P6-B7F — 検証済み plan → 既存 proposal authority（B3 / B5C）の check-then-reuse 提出 bridge の test。

書いてよいのは B3 の提案 journal と B5C の関係提案 journal だけ。decision・Theme / evidence / relation / governance・
B6 review・生成監査 journal には書かない。実 LLM・network・資格情報は無い。
データはすべて synthetic（Foundation 代表 world ＋ B5B relation ＋ B4 の合成入力）。書き込みは `tmp_path` のみ。
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import socket
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence import llm_submission as S
from src.intelligence.theme_intelligence.entity_catalog import entity_catalog_path, load_entity_catalog_version
from src.intelligence.theme_intelligence.llm_generation import run_generation
from src.intelligence.theme_intelligence.llm_generation_journal import LlmGenerationJournal, generation_journal_path
from src.intelligence.theme_intelligence.llm_plan_model import (PlannedEvidenceRef, SourceClaimStatus,
                                                                ValidatedEvidenceProposalPlan,
                                                                ValidatedRelationProposalPlan,
                                                                ValidatedThemeProposalPlan)
from src.intelligence.theme_intelligence.llm_proposal_model import (OUTPUT_SCHEMA_VERSION, LlmGenerationRequest,
                                                                    LlmTask, parse_generation_output)
from src.intelligence.theme_intelligence.llm_provider import FakeProvider
from src.intelligence.theme_intelligence.llm_submission import ValidatedGeneration, submit_proposals
from src.intelligence.theme_intelligence.llm_submission_model import (PROPOSAL_IS_NOT_DECISION,
                                                                      SUBMISSION_FAILURE_CODES,
                                                                      SUBMISSION_IS_NOT_A_BACKTEST, AuthorityFamily,
                                                                      PlanSubmission, ReuseKind, SubmissionAction,
                                                                      SubmissionModelError, SubmissionResult,
                                                                      SubmissionStatus)
from src.intelligence.theme_intelligence.llm_validator import validate_generation
from src.intelligence.theme_intelligence.proposal_bridge import BridgeError, plan_theme_creation_from_accepted_proposal
from src.intelligence.theme_intelligence.proposal_model import ProposerClass
from src.intelligence.theme_intelligence.proposal_store import ProposalAppendRejected, ProposalStore
from src.intelligence.theme_intelligence.relation_model import AssertionClass
from src.intelligence.theme_intelligence.relation_proposal_model import RelationProposerClass
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.taxonomy import load_taxonomy_version, taxonomy_path
from src.intelligence.themes.model import AssertionProvenance, MechanismCertainty, ProvenanceClass
from tests.intelligence.phase7_runtime_registry import PHASE7_EXCLUDED_PATHSPECS
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_llm_input_manifest import (B7B_ANCHOR, CUT, KNOWLEDGE_ROOT, PACKAGE_DIR, REPO_ROOT,
                                                              _seed, build, inventory)
from tests.intelligence.test_theme_llm_validator import ev, rel, theme
from tests.intelligence.test_theme_model import ROOT_B
from tests.intelligence.test_theme_proposal import evidence_candidate
from tests.intelligence.theme_freeze_pins import is_new_llm_module

B7C_ANCHOR = "95e04ae48f8e28206437923e36c6386a9a512cd9"
B7D_ANCHOR = "c240f6823cc5ff3239395ac0711d17c516ebf41c"
B7E_ANCHOR = "695227a403e6582849215251c6d1190d48ce3bcd"
FROZEN_B7_MODULES = {"llm_proposal_model": B7B_ANCHOR, "llm_manifest_model": B7C_ANCHOR,
                     "llm_manifest_builder": B7C_ANCHOR, "llm_plan_model": B7D_ANCHOR, "llm_validator": B7D_ANCHOR,
                     "llm_generation_input": B7E_ANCHOR, "llm_provider": B7E_ANCHOR,
                     "llm_generation_model": B7E_ANCHOR, "llm_generation_journal": B7E_ANCHOR,
                     "llm_generation": B7E_ANCHOR}
B7F_MODULES = ("llm_submission_model", "llm_submission")
GENERATED = CUT + timedelta(hours=1)
SUBMITTED = CUT + timedelta(hours=2)
REF_A, REF_B = "thllmatt_" + "a" * 24, "thllmatt_" + "b" * 24
PROMPT = "theme_llm_prompt:0.1.0"
B3_FILES = ("theme_intelligence/proposals.jsonl",)
B5C_FILES = ("theme_intelligence/relation_proposals.jsonl",)


# ---------------------------------------------------------------- fixtures（synthetic）


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUT)


@pytest.fixture(scope="module")
def catalog():
    return load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0",
                                       cutoff=CUT)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = tmp_path_factory.mktemp("llm_submission") / "data"
    return root, _seed(root)


@pytest.fixture(scope="module")
def manifests(base, taxonomy, catalog) -> dict:
    root = base[0]
    return {LlmTask.EVIDENCE_EXTRACTION: build(root, LlmTask.EVIDENCE_EXTRACTION, taxonomy=taxonomy, catalog=catalog),
            LlmTask.THEME_PROPOSAL: build(root, LlmTask.THEME_PROPOSAL, themes=None, taxonomy=taxonomy,
                                          catalog=catalog),
            LlmTask.RELATION_PROPOSAL: build(root, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)}


@pytest.fixture()
def root(base, tmp_path: Path) -> Path:
    target = tmp_path / "submission" / "data"
    shutil.copytree(base[0], target)
    return target


def request_for(manifest, **over) -> LlmGenerationRequest:
    values = dict(task=manifest.task, cutoff=manifest.cutoff, generated_at=GENERATED, prompt_contract_version=PROMPT,
                  manifest_digest=manifest.manifest_digest(), knowledge_versions=manifest.knowledge_versions)
    values.update(over)
    return LlmGenerationRequest(**values)


def raw(*candidates: dict) -> str:
    return json.dumps({"output_schema_version": OUTPUT_SCHEMA_VERSION, "outcome": "CANDIDATES",
                       "candidates": list(candidates)}, ensure_ascii=False)


def validated(manifest, *candidates: dict):
    return validate_generation(request=request_for(manifest), envelope=parse_generation_output(raw(*candidates)),
                               manifest=manifest)


def gen(validation, ref: str = REF_A) -> ValidatedGeneration:
    return ValidatedGeneration(validation=validation, generation_ref=ref, prompt_contract_version=PROMPT)


def submit(root: Path, *generations, at=SUBMITTED) -> SubmissionResult:
    return submit_proposals(generations=list(generations), submitted_at=at, data_root=root)


def tamper(obj, **values):
    for name, value in values.items():
        object.__setattr__(obj, name, value)
    return obj


def lines(root: Path, relative: str) -> list:
    return (root / relative).read_text(encoding="utf-8").splitlines()


def refused(result: SubmissionResult, code: str, detail: str = "") -> None:
    assert result.status is SubmissionStatus.REJECTED and result.failure_code == code, result
    assert result.appended_count() == 0
    if detail:
        assert result.failure_detail == detail, result


def zero_write(root: Path, fn) -> SubmissionResult:
    before = inventory(root)
    result = fn()
    assert inventory(root) == before
    return result


# ---------------------------------------------------------------- A〜G: 新規と再利用


def test_a_an_evidence_plan_becomes_one_new_b3_proposal(root: Path, manifests) -> None:
    validation = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())
    before = lines(root, B3_FILES[0])
    result = submit(root, gen(validation))
    (action,) = result.actions
    assert result.status is SubmissionStatus.SUBMITTED and action.action is SubmissionAction.NEW_PROPOSAL_APPENDED
    assert action.line_appended and action.family is AuthorityFamily.B3_PROPOSALS
    assert len(lines(root, B3_FILES[0])) == len(before) + 1
    stored = ProposalStore(root, read_only=True).get_proposal(action.upstream_proposal_id)
    assert stored.provenance.proposer_class is ProposerClass.LLM_PROPOSAL
    assert (stored.provenance.proposer_ref, stored.provenance.rule_version) == (REF_A, PROMPT)
    assert stored.provenance.reason == f"llm generation validated as {validation.result_id}"
    assert stored.created_at == SUBMITTED and stored.reason == validation.plans[0].reason


def test_b_an_evidence_plan_is_reused_exactly_or_convergently(root: Path, manifests) -> None:
    validation = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())
    submit(root, gen(validation))
    snapshot = inventory(root)
    exact = submit(root, gen(validation))
    convergent = submit(root, gen(validation, REF_B), at=SUBMITTED + timedelta(days=3))
    assert [a.reuse for a in exact.actions] == [ReuseKind.EXACT]
    assert [a.reuse for a in convergent.actions] == [ReuseKind.CONVERGENT]
    for result in (exact, convergent):
        assert result.status is SubmissionStatus.SUBMITTED and result.appended_count() == 0
        assert result.actions[0].action is SubmissionAction.EXISTING_PROPOSAL_REUSED
    assert inventory(root) == snapshot


def test_c_a_theme_plan_becomes_one_new_b3_proposal(root: Path, manifests) -> None:
    validation = validated(manifests[LlmTask.THEME_PROPOSAL], theme())
    result = submit(root, gen(validation))
    assert result.actions[0].action is SubmissionAction.NEW_PROPOSAL_APPENDED
    stored = ProposalStore(root, read_only=True).get_proposal(result.actions[0].upstream_proposal_id)
    plan = validation.plans[0]
    assert stored.subject == plan.subject and stored.mechanism == plan.mechanism
    assert stored.certainty_class is MechanismCertainty.HYPOTHESIZED_MECHANISM
    assert set(stored.scope) == set(plan.scope) and set(stored.invalidation_conditions) == set(plan.invalidation_conditions)
    assert {(a.role.value, a.role_provenance, a.role_asserted_by) for a in stored.evidence_refs} == {
        ("CONTEXT", ProvenanceClass.LLM_PROPOSAL, "llm:proposal")}
    assert {a.attached_at for a in stored.evidence_refs} == {SUBMITTED}
    assert {c.assertion_provenance for c in stored.mechanism.all_components()} == {AssertionProvenance.LLM_PROPOSAL}


def test_d_a_theme_plan_is_reused(root: Path, manifests) -> None:
    generation = gen(validated(manifests[LlmTask.THEME_PROPOSAL], theme()))
    submit(root, generation)
    snapshot = inventory(root)
    again = submit(root, generation, at=SUBMITTED + timedelta(hours=5))
    assert again.actions[0].action is SubmissionAction.EXISTING_PROPOSAL_REUSED
    assert again.actions[0].reuse is ReuseKind.CONVERGENT and inventory(root) == snapshot


def test_e_a_relation_plan_becomes_one_new_b5c_proposal(root: Path, manifests) -> None:
    validation = validated(manifests[LlmTask.RELATION_PROPOSAL], rel())
    before = lines(root, B5C_FILES[0])
    result = submit(root, gen(validation))
    (action,) = result.actions
    assert action.family is AuthorityFamily.B5C_RELATION_PROPOSALS and action.line_appended
    assert len(lines(root, B5C_FILES[0])) == len(before) + 1
    stored = RelationProposalStore(root, read_only=True).get_proposal(action.upstream_proposal_id)
    assert stored.provenance.proposer_class is RelationProposerClass.LLM and stored.provenance.proposer_ref == REF_A
    assert stored.rationale == "relation candidate amplifies new_relation"


def test_f_a_relation_plan_is_reused(root: Path, manifests) -> None:
    generation = gen(validated(manifests[LlmTask.RELATION_PROPOSAL], rel()))
    submit(root, generation)
    snapshot = inventory(root)
    again = submit(root, generation)
    assert again.actions[0].reuse is ReuseKind.EXACT and inventory(root) == snapshot


def test_g_the_frozen_constructor_reproduces_the_plan_upstream_id(root: Path, manifests) -> None:
    for task, candidate in ((LlmTask.EVIDENCE_EXTRACTION, ev()), (LlmTask.THEME_PROPOSAL, theme()),
                            (LlmTask.RELATION_PROPOSAL, rel())):
        validation = validated(manifests[task], candidate)
        result = submit(root, gen(validation))
        assert result.actions[0].upstream_proposal_id == validation.plans[0].upstream_proposal_id
        assert result.actions[0].plan_id == validation.plans[0].plan_id


# ---------------------------------------------------------------- H〜O: 型だけを信用しない（書き込み 0 件）


def _tampered(manifests, task, candidate, **values):
    validation = validated(manifests[task], candidate)
    tamper(validation.plans[0], **values)
    return validation


@pytest.mark.parametrize("task,candidate,values,code,detail", [
    (LlmTask.EVIDENCE_EXTRACTION, ev(), {"plan_id": "thllmplan_" + "0" * 24}, "PLAN_INTEGRITY_FAILURE", "PLAN_ID_MISMATCH"),
    (LlmTask.EVIDENCE_EXTRACTION, ev(), {"upstream_proposal_id": "thprop_" + "0" * 24}, "UPSTREAM_ID_MISMATCH", ""),
    (LlmTask.EVIDENCE_EXTRACTION, ev(), {"proposer_class": ProposerClass.HUMAN}, "PLAN_INTEGRITY_FAILURE",
     "PROVENANCE_ESCALATION"),
    (LlmTask.EVIDENCE_EXTRACTION, ev(), {"proposer_class": ProposerClass.RULE}, "PLAN_INTEGRITY_FAILURE",
     "PROVENANCE_ESCALATION"),
    (LlmTask.THEME_PROPOSAL, theme(), {"certainty_class": MechanismCertainty.EXPLICIT_SOURCE_CAUSAL_CLAIM},
     "PLAN_INTEGRITY_FAILURE", "PROVENANCE_ESCALATION"),
    (LlmTask.THEME_PROPOSAL, theme(), {"certainty_class": MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM},
     "PLAN_INTEGRITY_FAILURE", "PROVENANCE_ESCALATION"),
    (LlmTask.EVIDENCE_EXTRACTION, ev(), {"reason": "evidence candidate supports news_item consequence c1 verified"},
     "PLAN_INTEGRITY_FAILURE", "NON_CANONICAL_INPUT"),
    (LlmTask.RELATION_PROPOSAL, rel(), {"rationale": "the source proves the relation"}, "PLAN_INTEGRITY_FAILURE",
     "NON_CANONICAL_INPUT"),
    (LlmTask.EVIDENCE_EXTRACTION, ev(), {"target_root_id": ROOT_B}, "PLAN_INTEGRITY_FAILURE", "PLAN_ID_MISMATCH"),
    (LlmTask.RELATION_PROPOSAL, rel(), {"proposer_class": RelationProposerClass.SOURCE}, "PLAN_INTEGRITY_FAILURE",
     "PROVENANCE_ESCALATION"),
    (LlmTask.RELATION_PROPOSAL, rel(), {"source_claim_status": "SOURCE_ASSERTED"}, "PLAN_INTEGRITY_FAILURE",
     "SOURCE_ASSERTED_UNVERIFIED"),
    (LlmTask.RELATION_PROPOSAL, rel(), {"accepted_assertion_class": AssertionClass.SOURCE_ASSERTED},
     "PLAN_INTEGRITY_FAILURE", "UNDECLARED_ATTRIBUTE"),
])
def test_h_to_o_a_tampered_plan_is_refused_before_any_write(root: Path, manifests, task, candidate, values, code,
                                                             detail) -> None:
    validation = _tampered(manifests, task, candidate, **values)
    refused(zero_write(root, lambda: submit(root, gen(validation))), code, detail)


def test_k2_nested_provenance_escalation_is_refused(root: Path, manifests) -> None:
    validation = validated(manifests[LlmTask.THEME_PROPOSAL], theme())
    tamper(validation.plans[0].mechanism.drivers[0], assertion_provenance=AssertionProvenance.HUMAN)
    refused(zero_write(root, lambda: submit(root, gen(validation))), "PLAN_INTEGRITY_FAILURE", "PROVENANCE_ESCALATION")
    validation = validated(manifests[LlmTask.THEME_PROPOSAL], theme())
    tamper(validation.plans[0].evidence_refs[0], role_provenance=ProvenanceClass.HUMAN)
    refused(zero_write(root, lambda: submit(root, gen(validation))), "PLAN_INTEGRITY_FAILURE", "PROVENANCE_ESCALATION")
    validation = validated(manifests[LlmTask.THEME_PROPOSAL], theme())
    tamper(validation.plans[0].subject, normalized_subject="NOT Normalized Subject")
    tamper(validation.plans[0], plan_id=ValidatedThemeProposalPlan.build(**{
        f.name: getattr(validation.plans[0], f.name) for f in dataclasses.fields(validation.plans[0])
        if f.name != "plan_id"}).plan_id)                                              # plan id を整合的に偽造
    refused(zero_write(root, lambda: submit(root, gen(validation))), "PLAN_INTEGRITY_FAILURE",
            "VALIDATION_RESULT_ID_MISMATCH")
    tamper(validation, result_id=type(validation).build(**{f.name: getattr(validation, f.name)
                                                          for f in dataclasses.fields(validation)
                                                          if f.name != "result_id"}).result_id)
    refused(zero_write(root, lambda: submit(root, gen(validation))), "PLAN_INTEGRITY_FAILURE",
            "NOT_NORMALIZED")                                                          # 凍結 B3 constructor が拒否する


def test_o2_a_consistently_forged_target_still_fails_on_the_upstream_id(root: Path, manifests) -> None:
    validation = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())
    plan = validation.plans[0]
    forged = ValidatedEvidenceProposalPlan.build(**{**{f.name: getattr(plan, f.name) for f in dataclasses.fields(plan)
                                                       if f.name != "plan_id"}, "target_root_id": ROOT_B})
    tamper(validation, plans=(forged,))
    result = zero_write(root, lambda: submit(root, gen(validation)))
    assert result.failure_code == "PLAN_INTEGRITY_FAILURE" and result.failure_detail == "VALIDATION_RESULT_ID_MISMATCH"
    tamper(validation, result_id=type(validation).build(**{f.name: getattr(validation, f.name)
                                                          for f in dataclasses.fields(validation)
                                                          if f.name != "result_id"}).result_id)
    refused(zero_write(root, lambda: submit(root, gen(validation))), "UPSTREAM_ID_MISMATCH")


# ---------------------------------------------------------------- P〜U: 提案は decision でも実行でもない


def test_p_source_asserted_stays_an_unverified_proposal(root: Path, manifests) -> None:
    validation = validated(manifests[LlmTask.RELATION_PROPOSAL], rel())
    assert validation.plans[0].source_claim_status is SourceClaimStatus.UNVERIFIED
    result = submit(root, gen(validation))
    stored = RelationProposalStore(root, read_only=True).get_proposal(result.actions[0].upstream_proposal_id)
    assert stored.source_attribution is not None and stored.provenance.proposer_class is RelationProposerClass.LLM
    assert not hasattr(stored, "accepted_assertion_class")
    assert RelationProposalStore(root, read_only=True).decisions() == ()
    assert PROPOSAL_IS_NOT_DECISION == ("a submitted proposal is not a decision, an accepted Theme, an evidence "
                                        "attachment or a relation assertion")


def test_q_r_no_verification_decision_or_assertion_is_written(root: Path, manifests) -> None:
    before = inventory(root)
    submit(root, gen(validated(manifests[LlmTask.RELATION_PROPOSAL], rel())))
    after = inventory(root)
    for name in ("relation_proposal_decisions.jsonl", "relation_assertions.jsonl", "relation_governance.jsonl"):
        assert after[f"theme_intelligence/{name}"] == before[f"theme_intelligence/{name}"], name
    for name in B7F_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        assert "SourceClaimVerification" not in source and "Decision" not in source, name


def test_s_t_u_no_theme_root_attachment_or_governance_is_written(root: Path, manifests) -> None:
    foundation = {k: v for k, v in inventory(root).items() if k.startswith("themes/")}
    assert foundation
    submit(root, gen(validated(manifests[LlmTask.THEME_PROPOSAL], theme())))
    submit(root, gen(validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())))
    assert {k: v for k, v in inventory(root).items() if k.startswith("themes/")} == foundation
    stored = ProposalStore(root, read_only=True)
    assert stored.decisions() == ()
    theme_proposal = next(p for p in stored.proposals() if p.proposal_type.value == "THEME_CANDIDATE")
    with pytest.raises(BridgeError) as exc:                                            # 提案は受理ではない
        plan_theme_creation_from_accepted_proposal(theme_proposal, (), created_at=SUBMITTED)
    assert exc.value.code == "NOT_ACCEPTED"


# ---------------------------------------------------------------- V〜Z: 書き込み 0 件の場合


def test_v_an_all_reuse_submission_writes_nothing(root: Path, manifests) -> None:
    generation = gen(validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev(),
                               ev(evidence="EV_001", target="TH_002", component="CQ_002")))
    submit(root, generation)
    result = zero_write(root, lambda: submit(root, generation, at=SUBMITTED + timedelta(days=1)))
    assert result.status is SubmissionStatus.SUBMITTED and result.appended_count() == 0
    assert {a.action for a in result.actions} == {SubmissionAction.EXISTING_PROPOSAL_REUSED}


def _conflicting_store(monkeypatch, target_id: str) -> None:
    """障害注入: 同じ id に意味の違う記録済み提案がある状態（凍結 store の読み取りを差し替える）。"""
    other = evidence_candidate(reason="a different recorded candidate")
    original = ProposalStore.get_proposal

    def lookup(self, proposal_id):
        return other if proposal_id == target_id else original(self, proposal_id)

    monkeypatch.setattr(ProposalStore, "get_proposal", lookup)


def test_w_a_conflicting_existing_proposal_writes_nothing(root: Path, manifests, monkeypatch) -> None:
    validation = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())
    _conflicting_store(monkeypatch, validation.plans[0].upstream_proposal_id)
    result = zero_write(root, lambda: submit(root, gen(validation)))
    refused(result, "PROPOSAL_CONFLICT", "EXISTING_CONTENT_DIFFERS")
    assert result.actions[0].failure_code == "PROPOSAL_CONFLICT"


@pytest.mark.parametrize("relative,task,candidate", [
    ("theme_intelligence/proposals.jsonl", LlmTask.EVIDENCE_EXTRACTION, ev()),
    ("theme_intelligence/proposal_decisions.jsonl", LlmTask.THEME_PROPOSAL, theme()),
    ("theme_intelligence/relation_proposals.jsonl", LlmTask.RELATION_PROPOSAL, rel()),
    ("theme_intelligence/relation_proposal_decisions.jsonl", LlmTask.RELATION_PROPOSAL, rel())])
def test_x_y_a_corrupt_proposal_authority_writes_nothing(root: Path, manifests, relative, task, candidate) -> None:
    with (root / relative).open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    result = zero_write(root, lambda: submit(root, gen(validated(manifests[task], candidate))))
    refused(result, "AUTHORITY_CORRUPTION", "MALFORMED_JSON")
    (root / relative).unlink()
    refused(zero_write(root, lambda: submit(root, gen(validated(manifests[task], candidate)))), "AUTHORITY_CORRUPTION",
            "AUTHORITY_MISSING")                                                       # store を作り直さない


def test_z_unsupported_input_writes_nothing(root: Path, manifests) -> None:
    manifest = manifests[LlmTask.EVIDENCE_EXTRACTION]
    validation = validated(manifest, ev())
    abstained = validate_generation(request=request_for(manifest), manifest=manifest, envelope=parse_generation_output(
        json.dumps({"output_schema_version": OUTPUT_SCHEMA_VERSION, "outcome": "ABSTAIN",
                    "abstention": {"reason": "AMBIGUOUS"}})))
    rejected_run = run_generation(request=request_for(manifest), manifest=manifest,
                                  provider=FakeProvider(response=raw(ev(evidence="EV_099"))))
    envelope = parse_generation_output(raw(ev()))
    cases = [
        lambda: submit_proposals(generations=[], submitted_at=SUBMITTED, data_root=root),
        lambda: submit(root, envelope),
        lambda: submit(root, raw(ev())),
        lambda: submit(root, {"candidate_kind": "EVIDENCE"}),
        lambda: submit(root, rejected_run),
        lambda: submit(root, rejected_run.audit_record),
        lambda: submit(root, validation.plans[0]),
        lambda: submit(root, gen(abstained)),
        lambda: submit(root, gen(envelope)),
        lambda: submit(root, gen(validation, ref="theme_generation_1")),
        lambda: submit(root, gen(validation, ref=validation.result_id)),
        lambda: submit(root, ValidatedGeneration(validation=validation, generation_ref=REF_A,
                                                 prompt_contract_version="Prompt With Spaces")),
        lambda: submit(root, gen(validation), at=SUBMITTED.replace(tzinfo=None)),
        lambda: submit(root, gen(validation), at="2026-09-22T02:00:00+00:00"),
        lambda: submit(root, gen(validation), at=CUT - timedelta(hours=1)),
        lambda: submit_proposals(generations=[gen(validation)], submitted_at=SUBMITTED, data_root=""),
    ]
    for case in cases:
        refused(zero_write(root, case), "INVALID_SUBMISSION_INPUT")


# ---------------------------------------------------------------- AA〜AH: 複数 plan・順序・部分書き込み


def test_aa_the_same_proposal_from_two_generations_is_appended_once(root: Path, manifests) -> None:
    validation = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())
    before = len(lines(root, B3_FILES[0]))
    result = submit(root, gen(validation, REF_B), gen(validation, REF_A))
    actions = sorted(a.action.value for a in result.actions)
    assert actions == ["DUPLICATE_IN_SUBMISSION", "NEW_PROPOSAL_APPENDED"]
    assert len(lines(root, B3_FILES[0])) == before + 1
    stored = ProposalStore(root, read_only=True).get_proposal(validation.plans[0].upstream_proposal_id)
    assert stored.provenance.proposer_ref == REF_A                                     # 決定論的な順序で先頭の生成


def test_ab_a_forged_same_id_duplicate_fails_closed_before_writing(root: Path, manifests) -> None:
    first = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())
    second = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev(evidence="EV_001", target="TH_002",
                                                                  component="CQ_002"))
    tamper(second.plans[0], upstream_proposal_id=first.plans[0].upstream_proposal_id)
    refused(zero_write(root, lambda: submit(root, gen(first), gen(second, REF_B))), "UPSTREAM_ID_MISMATCH")


def test_ab2_same_id_duplicates_are_compared_by_content_not_by_id(root: Path, manifests, monkeypatch) -> None:
    """障害注入: 2 つの異なる提案が同じ上流 id を持つ状態。id だけで畳まず、書かずに fail closed する。"""
    first = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())
    second = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev(evidence="EV_001", target="TH_002",
                                                                  component="CQ_002"))
    monkeypatch.setattr(S._Planned, "upstream_id", property(lambda self: "thprop_" + "c" * 24))
    result = zero_write(root, lambda: submit(root, gen(first), gen(second, REF_B)))
    refused(result, "PROPOSAL_CONFLICT", "IN_SUBMISSION")


def _three_evidence(manifest, order=(0, 1, 2)):
    items = [ev(), ev(evidence="EV_001", target="TH_002", component="CQ_002"),
             ev(evidence="EV_004", role="CONTEXT", component="")]
    return validated(manifest, *[items[i] for i in order])


def test_ac_new_proposals_are_appended_in_a_deterministic_order(base, manifests, tmp_path: Path) -> None:
    outputs = []
    for index, order in enumerate(((0, 1, 2), (2, 1, 0), (1, 2, 0))):
        target = tmp_path / f"order_{index}" / "data"
        shutil.copytree(base[0], target)
        result = submit(target, gen(_three_evidence(manifests[LlmTask.EVIDENCE_EXTRACTION], order)))
        added = lines(target, B3_FILES[0])[-3:]
        assert [json.loads(line)["proposal_id"] for line in added] == sorted(
            a.upstream_proposal_id for a in result.actions)
        outputs.append((target / B3_FILES[0]).read_bytes())
    assert len(set(outputs)) == 1


def test_ad_a_multi_plan_submission_succeeds(root: Path, manifests) -> None:
    result = submit(root, gen(_three_evidence(manifests[LlmTask.EVIDENCE_EXTRACTION])))
    assert result.status is SubmissionStatus.SUBMITTED and result.appended_count() == 3


def test_ae_a_conflict_in_pre_flight_writes_nothing_at_all(root: Path, manifests, monkeypatch) -> None:
    validation = _three_evidence(manifests[LlmTask.EVIDENCE_EXTRACTION])
    target = sorted(p.upstream_proposal_id for p in validation.plans)[-1]              # 追記順で最後の 1 件
    _conflicting_store(monkeypatch, target)
    result = zero_write(root, lambda: submit(root, gen(validation)))
    refused(result, "PROPOSAL_CONFLICT")
    assert {a.action for a in result.actions} == {SubmissionAction.NOT_SUBMITTED}


def test_af_corruption_in_pre_flight_writes_nothing_at_all(root: Path, manifests) -> None:
    with (root / B3_FILES[0]).open("a", encoding="utf-8") as handle:
        handle.write("\n")
    refused(zero_write(root, lambda: submit(root, gen(_three_evidence(manifests[LlmTask.EVIDENCE_EXTRACTION])))),
            "AUTHORITY_CORRUPTION", "BLANK_LINE")


def _failing_second_append(monkeypatch) -> list:
    calls = []
    original = ProposalStore.append_proposal

    def append(self, record):
        calls.append(record.proposal_id)
        if len(calls) == 2:
            raise ProposalAppendRejected("SIMULATED_FAILURE", "injected", authority="proposals")
        return original(self, record)

    monkeypatch.setattr(ProposalStore, "append_proposal", append)
    return calls


def test_ag_ah_a_failure_after_a_write_is_an_explicit_partial_submission(root: Path, manifests, monkeypatch) -> None:
    validation = _three_evidence(manifests[LlmTask.EVIDENCE_EXTRACTION])
    before = lines(root, B3_FILES[0])
    calls = _failing_second_append(monkeypatch)
    result = submit(root, gen(validation))
    assert result.status is SubmissionStatus.PARTIAL_SUBMISSION and result.failure_code == "PARTIAL_SUBMISSION"
    assert result.failure_detail == "APPEND_FAILURE:SIMULATED_FAILURE"
    order = sorted(p.upstream_proposal_id for p in validation.plans)
    assert calls == order[:2]                                                          # 決定論的な順序で 2 件目に失敗
    by_id = {a.upstream_proposal_id: a for a in result.actions}
    assert by_id[order[0]].action is SubmissionAction.NEW_PROPOSAL_APPENDED
    assert by_id[order[1]].failure_code == "APPEND_FAILURE" and by_id[order[2]].action is SubmissionAction.NOT_SUBMITTED
    after = lines(root, B3_FILES[0])
    assert after[:len(before)] == before and len(after) == len(before) + 1           # 巻き戻さない（削除しない）
    monkeypatch.undo()
    resumed = submit(root, gen(validation))
    assert sorted(a.action.value for a in resumed.actions) == ["EXISTING_PROPOSAL_REUSED", "NEW_PROPOSAL_APPENDED",
                                                               "NEW_PROPOSAL_APPENDED"]


def test_ag2_a_failure_on_the_first_write_is_rejected_with_zero_writes(root: Path, manifests, monkeypatch) -> None:
    def fail(self, record):
        raise ProposalAppendRejected("SIMULATED_FAILURE", "injected", authority="proposals")

    monkeypatch.setattr(ProposalStore, "append_proposal", fail)
    refused(zero_write(root, lambda: submit(root, gen(validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev())))),
            "APPEND_FAILURE", "SIMULATED_FAILURE")


# ---------------------------------------------------------------- AI〜AL: 冪等と identity


def test_ai_aj_the_second_run_reuses_and_leaves_bytes_unchanged(root: Path, manifests) -> None:
    generation = gen(_three_evidence(manifests[LlmTask.EVIDENCE_EXTRACTION]))
    first = submit(root, generation)
    after_first = inventory(root)
    second = submit(root, generation)
    assert {a.action for a in first.actions} == {SubmissionAction.NEW_PROPOSAL_APPENDED}
    assert {a.action for a in second.actions} == {SubmissionAction.EXISTING_PROPOSAL_REUSED}
    assert inventory(root) == after_first
    ProposalStore(root, read_only=True)                                                # 重複行が無い（load が通る）


def test_ak_provider_and_model_metadata_cannot_change_the_proposal_id(root: Path, manifests) -> None:
    manifest = manifests[LlmTask.EVIDENCE_EXTRACTION]
    runs = [run_generation(request=request_for(manifest), manifest=manifest,
                           provider=FakeProvider(response=raw(ev()), provider_ref=p, model_ref=m))
            for p, m in (("fake_a", "model_x"), ("fake_b", "model_y"))]
    ids = {r.result.plans[0].upstream_proposal_id for r in runs}
    assert len(ids) == 1
    first = submit(root, gen(runs[0].result.validation, runs[0].audit_record.attempt_id))
    second = submit(root, gen(runs[1].result.validation, runs[1].audit_record.attempt_id))
    assert first.actions[0].upstream_proposal_id == second.actions[0].upstream_proposal_id
    assert second.actions[0].reuse is ReuseKind.CONVERGENT


def test_al_the_submission_time_does_not_alter_the_semantic_id(base, manifests, tmp_path: Path) -> None:
    ids = set()
    for index, hours in enumerate((2, 48, 400)):
        target = tmp_path / f"time_{index}" / "data"
        shutil.copytree(base[0], target)
        for task, candidate in ((LlmTask.EVIDENCE_EXTRACTION, ev()), (LlmTask.THEME_PROPOSAL, theme()),
                                (LlmTask.RELATION_PROPOSAL, rel())):
            result = submit(target, gen(validated(manifests[task], candidate)), at=CUT + timedelta(hours=hours))
            ids.add((task, result.actions[0].upstream_proposal_id))
    assert len(ids) == 3


# ---------------------------------------------------------------- AM〜AS: 書き込み面


def test_am_an_ao_only_the_b3_and_b5c_proposal_journals_change(root: Path, manifests) -> None:
    journal = LlmGenerationJournal.initialize(root)
    manifest = manifests[LlmTask.EVIDENCE_EXTRACTION]
    run_generation(request=request_for(manifest), manifest=manifest, provider=FakeProvider(response=raw(ev())),
                   journal=journal)
    audit_bytes = generation_journal_path(root).read_bytes()
    before = inventory(root)
    submit(root, gen(validated(manifest, ev())))
    submit(root, gen(validated(manifests[LlmTask.RELATION_PROPOSAL], rel())))
    after = inventory(root)
    assert set(after) == set(before)                                                   # 新しい提出 journal は無い
    changed = {k for k in after if after[k] != before[k]}
    assert changed == set(B3_FILES) | set(B5C_FILES)
    assert generation_journal_path(root).read_bytes() == audit_bytes                   # 生成監査 journal は不変


def test_ap_to_as_decision_foundation_assertion_and_review_journals_do_not_change(root: Path, manifests) -> None:
    before = inventory(root)
    for task, candidate in ((LlmTask.EVIDENCE_EXTRACTION, ev()), (LlmTask.THEME_PROPOSAL, theme()),
                            (LlmTask.RELATION_PROPOSAL, rel())):
        submit(root, gen(validated(manifests[task], candidate)))
    after = inventory(root)
    for key in before:
        if key in B3_FILES + B5C_FILES:
            continue
        assert after[key] == before[key], key
    for name in ("proposal_decisions.jsonl", "relation_proposal_decisions.jsonl", "relation_assertions.jsonl",
                 "relation_governance.jsonl", "monitoring_review_states.jsonl"):
        assert f"theme_intelligence/{name}" in before, name


# ---------------------------------------------------------------- AT〜AV: security・時計・保存しないもの


def test_at_no_network_or_credential_access(root: Path, manifests, monkeypatch) -> None:
    for name in B7F_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("socket", "http", "urllib", "requests", "environ", "getenv", ".api_key", "API_KEY", "anthropic",
                      "openai", "subprocess", "keyring", "provider"):
            assert token not in source, (name, token)

    def refuse(*_args, **_kwargs):
        raise AssertionError("no network in B7F")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(os, "getenv", refuse)
    assert submit(root, gen(validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev()))).appended_count() == 1


def test_au_no_clock_or_randomness(base, manifests, tmp_path: Path) -> None:
    for name in B7F_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in (".now(", "utcnow", "today(", "time.time", "monotonic", "random", "uuid", "secrets"):
            assert token not in source, (name, token)
    outputs = []
    for index in range(2):
        target = tmp_path / f"det_{index}" / "data"
        shutil.copytree(base[0], target)
        result = submit(target, gen(_three_evidence(manifests[LlmTask.EVIDENCE_EXTRACTION])))
        outputs.append(((target / B3_FILES[0]).read_bytes(), result.canonical_json()))
    assert outputs[0] == outputs[1]


def test_av_no_prompt_response_or_source_text_is_persisted(root: Path, manifests) -> None:
    marker = "Pelican-Harbor-2217"
    submit(root, gen(validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev(rationale=marker))))
    submit(root, gen(validated(manifests[LlmTask.RELATION_PROPOSAL], rel(rationale=marker))))
    text = (root / B3_FILES[0]).read_text(encoding="utf-8") + (root / B5C_FILES[0]).read_text(encoding="utf-8")
    for token in (marker, "Data centre power demand", "Utilities report", "Power utilities raise capex",
                  "instructions", "task_contract", "rationale\":\"the", "fake_provider"):
        assert token not in text, token


# ---------------------------------------------------------------- AW〜BB: 凍結と guard


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("name,anchor", sorted(FROZEN_B7_MODULES.items()))
def test_aw_to_az_every_frozen_b7_module_is_byte_identical_to_its_anchor(name: str, anchor: str) -> None:
    path = f"src/intelligence/theme_intelligence/{name}.py"
    assert _git("show", f"{anchor}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8")


def test_ba_upstream_runtime_is_unchanged_since_the_b7e_freeze() -> None:
    surface = ("src", "knowledge", "config.yaml", ".github", "scripts")
    surface += PHASE7_EXCLUDED_PATHSPECS                                         # Phase 7 の登録済み runtime
    changes = [line.split("\t") for line in _git("diff", "--name-status", B7E_ANCHOR, "--", *surface).splitlines()]
    pending = [(line[:2].strip(), line[3:]) for line in _git("status", "--porcelain", "--", *surface).splitlines()]
    for status, path in [(c[0], c[-1]) for c in changes] + pending:
        assert is_new_llm_module(status, path), (status, path)
        assert Path(path).stem in B7F_MODULES, path


def test_bb_the_guards_register_every_b7f_module() -> None:
    from tests.intelligence import test_theme_intelligence_import_boundary as guard
    for name in B7F_MODULES:
        assert name in guard.MODULES and name in guard.LLM_MODULES
        assert f"src.intelligence.theme_intelligence.{name}" in guard.ALLOWED_CLOSURE
    assert guard.LLM_SUBMISSION_MODULES == ("llm_submission",) and "llm_submission_model" in guard.LLM_PURE_MODULES
    assert set(guard.LLM_SUBMISSION_IMPORTS) == {".proposal_store", ".relation_proposal_store"}
    imports = imported_modules(PACKAGE_DIR / "llm_submission.py")
    for forbidden in ("bridge", "relation_store", "themes.store", "monitoring", "llm_generation", "llm_validator",
                      "llm_manifest", "llm_provider", "decision", "resolution"):
        assert not any(forbidden in m for m in imports), (forbidden, imports)


# ---------------------------------------------------------------- 結果 model・文言


def test_the_result_model_is_bounded_and_self_consistent() -> None:
    assert SUBMISSION_FAILURE_CODES == ("INVALID_SUBMISSION_INPUT", "PLAN_INTEGRITY_FAILURE", "UPSTREAM_ID_MISMATCH",
                                        "AUTHORITY_CORRUPTION", "PROPOSAL_CONFLICT", "APPEND_FAILURE",
                                        "PARTIAL_SUBMISSION")
    action = dict(plan_id="thllmplan_" + "1" * 24, family=AuthorityFamily.B3_PROPOSALS,
                  upstream_proposal_id="thprop_" + "1" * 24)
    for bad in (dict(action=SubmissionAction.NEW_PROPOSAL_APPENDED, line_appended=False),
                dict(action=SubmissionAction.EXISTING_PROPOSAL_REUSED, line_appended=True, reuse=ReuseKind.EXACT),
                dict(action=SubmissionAction.EXISTING_PROPOSAL_REUSED),
                dict(action=SubmissionAction.NEW_PROPOSAL_APPENDED, line_appended=True, failure_code="APPEND_FAILURE")):
        with pytest.raises(SubmissionModelError):
            PlanSubmission(**action, **bad)
    new = PlanSubmission(**action, action=SubmissionAction.NEW_PROPOSAL_APPENDED, line_appended=True)
    with pytest.raises(SubmissionModelError):
        SubmissionResult(status=SubmissionStatus.REJECTED, actions=(new,), failure_code="PROPOSAL_CONFLICT")
    with pytest.raises(SubmissionModelError):
        SubmissionResult(status=SubmissionStatus.PARTIAL_SUBMISSION, actions=(), failure_code="PARTIAL_SUBMISSION")
    names = {f.name for f in dataclasses.fields(SubmissionResult)} | {f.name for f in dataclasses.fields(PlanSubmission)}
    for token in ("score", "rank", "confidence", "severity", "strength", "recommend", "accepted", "decision"):
        assert not any(token in name for name in names), token
    assert SUBMISSION_IS_NOT_A_BACKTEST.startswith("submission runs against the current proposal authority only")


def test_refusals_never_echo_plan_or_source_text(root: Path, manifests) -> None:
    marker = "Heron-Sextant-8812"
    validation = validated(manifests[LlmTask.EVIDENCE_EXTRACTION], ev(rationale=marker))
    tamper(validation.plans[0], reason=f"evidence candidate {marker.lower()}")
    result = submit(root, gen(validation))
    assert marker.lower() not in result.canonical_json().lower()
