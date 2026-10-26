"""P6-B4E — ACCEPTED EvidenceCandidateProposal → EvidenceAttachmentPlan（failure matrix 1〜45）。

実 Foundation world（A4d fixture）の read-only resolution を対象にする。bridge は store を読まず書かず、
proposal / decision 履歴を変えず、資格判定を計算せず、現在時刻・乱数・network・LLM を使わない。
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.evidence_bridge import plan_evidence_attachment_from_accepted_proposal
from src.intelligence.theme_intelligence.evidence_bridge_model import (BRIDGE_MODEL_VERSION, EvidenceAttachmentPlan,
                                                                       EvidenceBridgeError)
from src.intelligence.theme_intelligence.proposal_model import (DecisionKind, DedupClass, DedupCounterpart,
                                                                DedupReviewProposal, ComparisonBasis, ComparisonBasisKind,
                                                                CounterpartKind, EvidenceCandidateProposal,
                                                                ProposalDecision, ProposalProvenance, ProposerClass)
from src.intelligence.themes.model import (EvidenceAttachment, EvidenceAuthorityClass, EvidenceKind, EvidenceRole,
                                           EvidenceTimeBasis, EvidenceTimeQuality, ProvenanceClass)
from src.intelligence.themes.resolver import ResolutionStatus
from tests.intelligence import theme_foundation_fixtures as F
from tests.intelligence.test_theme_model import FACT_A, origin

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
B4E_MODULES = ("evidence_bridge_model", "evidence_bridge")
T_ACCEPTED = F.TIMES["T8_accepted"]
EVIDENCE_AT = T_ACCEPTED - timedelta(days=1)
DECIDED_AT = T_ACCEPTED + timedelta(hours=1)
PLANNED_AT = T_ACCEPTED + timedelta(hours=2)
NEW_FACT = "fact_" + "9" * 24
NEW_DOC = "doc_" + "9" * 24
MISSING_DECISION_ID = "thdec_" + "0" * 24


# ---------------------------------------------------------------- Foundation world（read-only）


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return F.build_world(tmp_path_factory.mktemp("b4e_world") / "data", stop_after="accepted")


@pytest.fixture(scope="module")
def resolved(world):
    resolution = world.resolve("A", "accepted")
    assert resolution.status is ResolutionStatus.RESOLVED and resolution.observation is not None
    assert resolution.observation.mechanism.consequence_keys == ("c1",)
    return resolution


# ---------------------------------------------------------------- proposal / decision builders（合成）


def candidate(*, ref_id: str = NEW_FACT, kind: EvidenceKind = EvidenceKind.FACT, role: EvidenceRole = EvidenceRole.SUPPORTS,
              root_id: str = "", target_proposal_id: str = "", quality: EvidenceTimeQuality = EvidenceTimeQuality.DECLARED,
              basis: EvidenceTimeBasis = EvidenceTimeBasis.KNOWN_AT, evidence_time=EVIDENCE_AT,
              evidence_date: str = "2026-08-27", locator: str = "", note: str = "", created_at=T_ACCEPTED,
              provenance=None) -> EvidenceCandidateProposal:
    if quality is EvidenceTimeQuality.MISSING:
        evidence_time, basis, evidence_date = None, EvidenceTimeBasis.NONE, ""
    return EvidenceCandidateProposal.build(
        evidence_kind=kind, ref_id=ref_id, source_origin=origin(), evidence_time=evidence_time, evidence_time_basis=basis,
        evidence_time_quality=quality, evidence_date=evidence_date, proposed_role=role,
        reason="discovery evidence candidate supports fact", target_root_id=root_id, target_proposal_id=target_proposal_id,
        locator=locator, note=note,
        provenance=provenance or ProposalProvenance(ProposerClass.RULE, "rule:policy_rate_fact_evidence", rule_version="0.1.0",
                                                    reason="pins taxonomy=0.2.0 catalog=0.2.0 ruleset=0.1.0"),
        created_at=created_at)


def decide(proposal, kind: DecisionKind = DecisionKind.ACCEPT, *, at=DECIDED_AT, actor: str = "reviewer:r1",
           reason: str = "verified against the official release", supersedes: str = "") -> ProposalDecision:
    return ProposalDecision.build(proposal_id=proposal.proposal_id, decision=kind, actor_ref=actor, reason=reason,
                                  recorded_at=at, supersedes_decision_id=supersedes)


def plan(proposal, decisions, target, *, created_at=PLANNED_AT, consequence_ref="c1", invalidation_ref=None):
    return plan_evidence_attachment_from_accepted_proposal(proposal, decisions, target_resolution=target,
                                                           created_at=created_at, consequence_ref=consequence_ref,
                                                           invalidation_ref=invalidation_ref)


def fails(code: str, *args, **kw) -> EvidenceBridgeError:
    with pytest.raises(EvidenceBridgeError) as info:
        plan(*args, **kw)
    assert info.value.code == code, info.value.code
    return info.value


def accepted_supports(root_id: str, **kw):
    proposal = candidate(root_id=root_id, **kw)
    return proposal, (decide(proposal),)


# ---------------------------------------------------------------- 1〜2 happy path


def test_01_accepted_supports_candidate_produces_a_plan(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    result = plan(proposal, decisions, resolved)
    assert isinstance(result, EvidenceAttachmentPlan) and result.bridge_model_version == BRIDGE_MODEL_VERSION
    assert result.target_root_id == resolved.root_id and result.target_observation_id == resolved.observation.observation_id
    assert result.target_resolver_version == resolved.resolver_version and result.target_cutoff == resolved.cutoff
    assert result.role is EvidenceRole.SUPPORTS and result.consequence_ref == "c1"
    assert result.attachment_key == f"{NEW_FACT}#c1" and result.attached_at == PLANNED_AT
    assert result.authority_class is EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL and result.limited_use is False


def test_02_accepted_context_candidate_produces_a_plan(resolved) -> None:
    proposal = candidate(root_id=resolved.root_id, role=EvidenceRole.CONTEXT, ref_id=NEW_DOC,
                         kind=EvidenceKind.SOURCE_DOCUMENT, basis=EvidenceTimeBasis.PUBLISHED_AT)
    result = plan(proposal, (decide(proposal),), resolved, consequence_ref=None)
    assert result.role is EvidenceRole.CONTEXT and result.consequence_ref == "" and result.attachment_key == f"{NEW_DOC}#"
    assert result.invalidation_condition_ref == ""


def test_03_plan_carries_everything_needed_to_build_a_foundation_attachment(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    result = plan(proposal, decisions, resolved)
    attachment = EvidenceAttachment(
        evidence_kind=result.evidence_kind, authority_class=result.authority_class, ref_id=result.ref_id,
        source_origin=result.source_origin, evidence_time=result.evidence_time, evidence_time_basis=result.evidence_time_basis,
        evidence_time_quality=result.evidence_time_quality, evidence_date=result.evidence_date,
        attached_at=result.attached_at, role=result.role, role_provenance=result.role_provenance,
        role_asserted_by=result.role_asserted_by, consequence_ref=result.consequence_ref,
        invalidation_condition_ref=result.invalidation_condition_ref, limited_use=result.limited_use,
        locator=result.locator, note=result.note)
    assert attachment.attachment_key == result.attachment_key and attachment.role_provenance is ProvenanceClass.HUMAN


# ---------------------------------------------------------------- 3〜7 acceptance


def _fork(proposal):
    return (decide(proposal, reason="first look"), decide(proposal, reason="second look"))


@pytest.mark.parametrize("build,status", [
    (lambda p: (), "OPEN"),
    (lambda p: (decide(p, DecisionKind.DEFER),), "OPEN_DEFERRED"),
    (lambda p: (decide(p, DecisionKind.REJECT),), "REJECTED"),
    (lambda p: (decide(p, DecisionKind.NOT_DUPLICATE),), "CLOSED_NOT_DUPLICATE"),
    (_fork, "OPEN_UNRESOLVED"),
    (lambda p: (decide(p, supersedes=MISSING_DECISION_ID),), "INVALID_DECISION_HISTORY")])
def test_04_only_an_accepted_proposal_can_be_bridged(resolved, build, status) -> None:
    proposal = candidate(root_id=resolved.root_id)
    error = fails("PROPOSAL_NOT_ACCEPTED", proposal, build(proposal), resolved)
    assert error.detail == status


def test_05_a_superseded_rejection_followed_by_acceptance_is_bridgeable(resolved) -> None:
    proposal = candidate(root_id=resolved.root_id)
    rejected = decide(proposal, DecisionKind.REJECT, reason="not verified yet")
    accepted = decide(proposal, DecisionKind.ACCEPT, at=DECIDED_AT + timedelta(hours=1), supersedes=rejected.decision_id)
    result = plan(proposal, (rejected, accepted), resolved)
    assert result.decision.decision_id == accepted.decision_id and result.decision.supersedes_decision_id == rejected.decision_id
    assert result.role_asserted_by == accepted.actor_ref


# ---------------------------------------------------------------- 8〜14 proposal type / target


def test_06_only_evidence_candidate_proposals_are_bridgeable(resolved, world) -> None:
    theme = _theme_proposal(world)
    fails("INVALID_PROPOSAL_TYPE", theme, (decide(theme),), resolved)
    review = DedupReviewProposal.build(
        subject_proposal_id=theme.proposal_id,
        counterparts=(DedupCounterpart(CounterpartKind.THEME_ROOT, resolved.root_id, theme.semantic_fingerprint,
                                       resolved.observation.observation_id),),
        dedup_class=DedupClass.EXACT_SEMANTIC_MATCH,
        comparison_basis=ComparisonBasis(ComparisonBasisKind.SEMANTIC_FINGERPRINT, theme.semantic_fingerprint),
        provenance=ProposalProvenance(ProposerClass.RULE, "rule:theme_dedup_exact"), created_at=T_ACCEPTED,
        dedup_model_version="theme_dedup:0.1.0")
    fails("INVALID_PROPOSAL_TYPE", review, (decide(review),), resolved)
    fails("INVALID_PROPOSAL_TYPE", object(), (), resolved)


def _theme_proposal(world):
    from tests.intelligence.test_theme_model import condition, mechanism, scope, subject
    from src.intelligence.theme_intelligence.proposal_model import ThemeCandidateProposal
    from src.intelligence.themes.model import MechanismCertainty
    return ThemeCandidateProposal.build(
        subject=subject(), mechanism=mechanism(), certainty_class=MechanismCertainty.HYPOTHESIZED_MECHANISM,
        scope=scope(), invalidation_conditions=(condition(),),
        provenance=ProposalProvenance(ProposerClass.RULE, "rule:x"), created_at=T_ACCEPTED)


def test_07_a_proposal_target_is_not_a_foundation_root(resolved, world) -> None:
    theme = _theme_proposal(world)
    proposal = candidate(target_proposal_id=theme.proposal_id)
    fails("TARGET_NOT_FOUNDATION_ROOT", proposal, (decide(proposal),), resolved)
    untargeted = candidate()
    fails("TARGET_NOT_FOUNDATION_ROOT", untargeted, (decide(untargeted),), resolved)


def test_08_target_resolution_must_describe_the_declared_root(resolved, world) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    other = world.resolve("B", "accepted")
    assert other.root_id != resolved.root_id
    fails("TARGET_ROOT_MISMATCH", proposal, decisions, other)
    fails("INVALID_TYPE", proposal, decisions, object())


@pytest.mark.parametrize("status", [ResolutionStatus.NO_STATE, ResolutionStatus.UNRESOLVED,
                                    ResolutionStatus.INVALID_HISTORY, ResolutionStatus.STORE_CORRUPTION])
def test_09_target_must_be_a_resolved_theme_state(resolved, world, status) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    target = world.resolve("A", "root_only") if status is ResolutionStatus.NO_STATE else replace(resolved, status=status)
    assert target.status is status
    error = fails("TARGET_NOT_RESOLVED", proposal, decisions, target)
    assert error.detail == status.value


def test_10_a_resolved_target_without_an_observation_is_refused(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    fails("TARGET_NOT_RESOLVED", proposal, decisions, replace(resolved, observation=None))


# ---------------------------------------------------------------- 15〜18 consequence / invalidation / role


def test_11_supports_requires_an_explicit_existing_consequence(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    fails("CONSEQUENCE_REF_REQUIRED", proposal, decisions, resolved, consequence_ref=None)
    fails("CONSEQUENCE_REF_REQUIRED", proposal, decisions, resolved, consequence_ref="")
    fails("UNKNOWN_CONSEQUENCE_REF", proposal, decisions, resolved, consequence_ref="c2")
    fails("INVALID_TYPE", proposal, decisions, resolved, consequence_ref=1)


def test_12_context_forbids_a_consequence_ref(resolved) -> None:
    proposal = candidate(root_id=resolved.root_id, role=EvidenceRole.CONTEXT, ref_id=NEW_DOC,
                         kind=EvidenceKind.SOURCE_DOCUMENT, basis=EvidenceTimeBasis.PUBLISHED_AT)
    fails("CONSEQUENCE_REF_FORBIDDEN", proposal, (decide(proposal),), resolved, consequence_ref="c1")


@pytest.mark.parametrize("value", ["cond_1", ""])
def test_13_invalidation_is_never_bridged(resolved, value) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    fails("INVALIDATION_REF_FORBIDDEN", proposal, decisions, resolved, invalidation_ref=value)


@pytest.mark.parametrize("role", [EvidenceRole.CONTRADICTS, EvidenceRole.INVALIDATES])
def test_14_roles_outside_the_bridge_policy_fail_closed(resolved, role) -> None:
    proposal = candidate(root_id=resolved.root_id, role=role)
    error = fails("FORBIDDEN_BRIDGE_ROLE", proposal, (decide(proposal),), resolved)
    assert error.detail == role.value


def test_15_evidence_without_a_time_may_only_be_context(resolved) -> None:
    supports = candidate(root_id=resolved.root_id, quality=EvidenceTimeQuality.MISSING, ref_id=NEW_DOC,
                         kind=EvidenceKind.SOURCE_DOCUMENT)
    fails("ROLE_REQUIRES_EVIDENCE_TIME", supports, (decide(supports),), resolved)
    context = candidate(root_id=resolved.root_id, role=EvidenceRole.CONTEXT, quality=EvidenceTimeQuality.MISSING,
                        ref_id=NEW_DOC, kind=EvidenceKind.SOURCE_DOCUMENT)
    result = plan(context, (decide(context),), resolved, consequence_ref=None)
    assert result.evidence_time is None and result.evidence_time_basis is EvidenceTimeBasis.NONE and result.evidence_date == ""


def test_16_inferred_evidence_time_becomes_limited_use(resolved) -> None:
    proposal = candidate(root_id=resolved.root_id, ref_id=NEW_DOC, kind=EvidenceKind.SOURCE_DOCUMENT,
                         quality=EvidenceTimeQuality.INFERRED, basis=EvidenceTimeBasis.PUBLISHED_AT)
    result = plan(proposal, (decide(proposal),), resolved)
    assert result.limited_use is True and result.evidence_time_quality is EvidenceTimeQuality.INFERRED


# ---------------------------------------------------------------- 19 duplicate


def test_17_an_attachment_already_present_is_refused(resolved) -> None:
    proposal = candidate(root_id=resolved.root_id, ref_id=FACT_A)
    error = fails("ATTACHMENT_ALREADY_PRESENT", proposal, (decide(proposal),), resolved)
    assert error.detail == f"{FACT_A}#c1"
    assert f"{FACT_A}#c1" in {a.attachment_key for a in resolved.observation.attachments}


def test_18_the_same_ref_under_a_different_consequence_is_a_different_key(resolved) -> None:
    extended = replace(resolved.observation.mechanism,
                       consequences=resolved.observation.mechanism.consequences)
    assert extended.consequence_keys == ("c1",)                     # target の consequence 集合は bridge では拡張されない
    proposal = candidate(root_id=resolved.root_id, ref_id=FACT_A)
    fails("UNKNOWN_CONSEQUENCE_REF", proposal, (decide(proposal),), resolved, consequence_ref="c9")


# ---------------------------------------------------------------- 20〜23 time semantics


def test_19_created_at_must_be_aware_and_not_precede_its_inputs(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    fails("INVALID_CREATED_AT", proposal, decisions, resolved, created_at=datetime(2026, 9, 8))
    fails("INVALID_CREATED_AT", proposal, decisions, resolved, created_at="2026-09-08T00:00:00+00:00")
    fails("CREATED_BEFORE_DECISION", proposal, decisions, resolved, created_at=DECIDED_AT - timedelta(seconds=1))
    early = candidate(root_id=resolved.root_id, created_at=PLANNED_AT + timedelta(days=1))
    fails("CREATED_BEFORE_PROPOSAL", early, (decide(early, at=PLANNED_AT + timedelta(days=1)),), resolved,
          created_at=PLANNED_AT)
    late_evidence = candidate(root_id=resolved.root_id, evidence_time=PLANNED_AT + timedelta(days=2))
    fails("CREATED_BEFORE_EVIDENCE_TIME", late_evidence, (decide(late_evidence),), resolved, created_at=PLANNED_AT)


def test_20_equality_at_every_time_boundary_is_allowed(resolved) -> None:
    proposal = candidate(root_id=resolved.root_id, created_at=DECIDED_AT, evidence_time=DECIDED_AT)
    result = plan(proposal, (decide(proposal),), resolved, created_at=DECIDED_AT)
    assert result.attached_at == DECIDED_AT == result.evidence_time


# ---------------------------------------------------------------- 24〜30 preservation


def test_21_evidence_reference_identity_is_preserved_verbatim(resolved) -> None:
    proposal = candidate(root_id=resolved.root_id, locator="https://example.invalid/release", note="reviewer supplied note")
    result = plan(proposal, (decide(proposal),), resolved)
    assert (result.evidence_kind, result.ref_id, result.evidence_time, result.evidence_time_basis,
            result.evidence_time_quality, result.evidence_date) == (
        proposal.evidence_kind, proposal.ref_id, proposal.evidence_time, proposal.evidence_time_basis,
        proposal.evidence_time_quality, proposal.evidence_date)
    assert result.source_origin == proposal.source_origin and result.source_origin is proposal.source_origin
    assert result.locator == proposal.locator and result.note == proposal.note


def test_22_a_missing_proposal_note_falls_back_to_the_human_acceptance_reason(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    assert proposal.note == ""
    result = plan(proposal, decisions, resolved)
    assert result.note == decisions[0].reason and result.proposal.proposal_note == ""


def test_23_role_authority_is_human_while_the_suggestion_origin_stays_auditable(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    result = plan(proposal, decisions, resolved)
    assert result.role_provenance is ProvenanceClass.HUMAN and result.role_asserted_by == "reviewer:r1"
    assert result.proposal.proposer_class is ProposerClass.RULE
    assert result.proposal.proposer_ref == "rule:policy_rate_fact_evidence" and result.proposal.rule_version == "0.1.0"
    assert result.proposal.provenance_reason == proposal.provenance.reason
    assert result.proposal.candidate_reason == proposal.reason and result.proposal.proposal_id == proposal.proposal_id
    assert result.proposal.proposal_created_at == proposal.created_at
    assert result.decision.decision is DecisionKind.ACCEPT and result.decision.actor_class is ProposerClass.HUMAN
    assert result.decision.decision_id == decisions[0].decision_id and result.decision.reason == decisions[0].reason
    assert result.decision.recorded_at == decisions[0].recorded_at


# ---------------------------------------------------------------- 31〜32 no qualification / independence claim


def test_24_the_plan_states_no_qualification_or_source_independence(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    result = plan(proposal, decisions, resolved)
    plain = json.dumps(result.to_plain()).lower()
    for token in ("qualif", "independent", "diversity", "score", "rank", "confidence", "contested", "invalidated",
                  "lifecycle", "change_set", "counted"):
        assert token not in plain, token
    for attribute in ("qualification", "independent_origin_count", "lifecycle_state", "score"):
        assert not hasattr(result, attribute)


# ---------------------------------------------------------------- 33〜35, 42〜45 no mutation


def test_25_planning_writes_nothing_and_changes_no_authority(world, resolved, tmp_path) -> None:
    before = F.authority_bytes(world.data_root)
    proposal, decisions = accepted_supports(resolved.root_id)
    proposal_before = proposal.as_dict()
    decision_before = decisions[0].as_dict()
    target_before = json.dumps(F.resolution_digest(resolved), sort_keys=True, default=str)
    plan(proposal, decisions, resolved)
    assert F.authority_bytes(world.data_root) == before
    assert proposal.as_dict() == proposal_before and decisions[0].as_dict() == decision_before
    assert json.dumps(F.resolution_digest(resolved), sort_keys=True, default=str) == target_before
    assert resolved.status is ResolutionStatus.RESOLVED and not list(tmp_path.iterdir())
    again = world.resolve("A", "accepted")
    assert json.dumps(F.resolution_digest(again), sort_keys=True, default=str) == target_before


# ---------------------------------------------------------------- 40〜41 determinism


def test_26_repeated_and_reordered_calls_produce_an_equal_plan(resolved) -> None:
    proposal = candidate(root_id=resolved.root_id)
    rejected = decide(proposal, DecisionKind.REJECT, reason="not verified yet")
    accepted = decide(proposal, DecisionKind.ACCEPT, at=DECIDED_AT + timedelta(hours=1), supersedes=rejected.decision_id)
    base = plan(proposal, (rejected, accepted), resolved)
    assert plan(proposal, (rejected, accepted), resolved) == base
    for seed in range(10):
        shuffled = [rejected, accepted]
        random.Random(seed).shuffle(shuffled)
        again = plan(proposal, tuple(shuffled), resolved)
        assert again == base and again.canonical_line() == base.canonical_line(), seed
        assert again.to_plain() == base.to_plain(), seed


def test_27_the_canonical_line_is_stable_and_sorted(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    line = plan(proposal, decisions, resolved).canonical_line()
    decoded = json.loads(line)
    assert list(decoded) == sorted(decoded) and "\n" not in line
    assert decoded["role_provenance"] == "HUMAN" and decoded["attachment_key"] == f"{NEW_FACT}#c1"
    assert decoded["bridge_model_version"] == BRIDGE_MODEL_VERSION


# ---------------------------------------------------------------- 36〜39 boundary（source / import）


def test_28_bridge_modules_never_execute_or_persist_anything() -> None:
    from tests.intelligence.test_prediction_record import executable_source, imported_modules

    for name in B4E_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("ThemeStore", "themes.store", "themes.operations", "themes.revision", "proposal_store",
                      "proposal_bridge", "execute_", "plan_candidate", "plan_merge", "append_root", "append_observation",
                      "append_governance", "append_metadata", "append_mapping", "new_root_id", "new_id(", "content_id(",
                      "attach_evidence", "revise_observation", "open(", "write_text(", "read_text(", ".write(", "jsonl",
                      "sqlite", "data_root", "requests", "urllib", "socket", "openai", "anthropic", "embedding",
                      "similarity", "cosine", ".now(", "utcnow", "time.time", "random.", "secrets."):
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any(m.endswith(("themes.store", "themes.operations", "themes.revision", ".proposal_store",
                                   ".proposal_bridge", ".discovery", ".lifecycle", ".change")) for m in imports), name
        assert "yaml" not in imports and "pathlib" not in imports, name


def test_29_the_bridge_reuses_the_b3_decision_resolver(resolved) -> None:
    from tests.intelligence.test_prediction_record import executable_source

    source = executable_source(PACKAGE_DIR / "evidence_bridge.py")
    assert "derive_proposal_status" in source and "resolve_active_decision" in source
    assert "recorded_at >" not in source and "max(" not in source and "sorted(" not in source


def test_30_no_theme_root_creation_or_revision_vocabulary_in_the_plan(resolved) -> None:
    proposal, decisions = accepted_supports(resolved.root_id)
    plain = plan(proposal, decisions, resolved).to_plain()
    assert "previous_observation_id" not in plain and "observation_id" not in plain
    assert plain["target_observation_id"] == resolved.observation.observation_id
    assert not any(re.search(r"(^|_)(root|observation)$", key) for key in plain)
