"""P6-B3 — exact dedup review（`theme_intelligence.dedup`）の契約 test（matrix 31〜39）。"""
from __future__ import annotations

import dataclasses

import pytest

from src.intelligence.theme_intelligence import dedup as D
from src.intelligence.theme_intelligence.proposal_model import (
    DEDUP_MODEL_VERSION, ComparisonBasisKind, CounterpartKind, DecisionKind, DedupClass, DedupReviewProposal, ProposalDecision,
    ProposalProvenance, ProposerClass, ThemeCandidateProposal,
)
from src.intelligence.theme_intelligence.proposal_resolution import ProposalStatus, derive_proposal_status
from src.intelligence.themes.model import ExpectedChange, ScopeDimension, ScopeToken
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B, ROOT_C, consequence, mechanism
from tests.intelligence.test_theme_proposal import HUMAN, candidate, decision, world  # noqa: F401  (module fixture)
from tests.intelligence.theme_foundation_fixtures import World, day


@pytest.fixture(scope="module")
def resolutions(world: World):
    return {key: world.resolve(key, "merge_completed") for key in ("A", "B", "C")}


def variant(obs, **override) -> ThemeCandidateProposal:
    return candidate(obs, **override)


def test_31_exact_semantic_match_theme_vs_proposal(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    subject = candidate(obs_a)
    reviews = D.detect_exact_duplicates(subject, resolutions=list(resolutions.values()), created_at=day(20))
    assert [r.dedup_class for r in reviews] == [DedupClass.EXACT_SEMANTIC_MATCH]
    rev = reviews[0]
    assert rev.comparison_basis.kind is ComparisonBasisKind.SEMANTIC_FINGERPRINT
    assert rev.comparison_basis.subject_fingerprint == subject.semantic_fingerprint == resolutions["A"].derived.semantic_fingerprint
    counterparts = {(c.kind, c.ref_id, c.observation_id) for c in rev.counterparts}
    assert counterparts == {(CounterpartKind.THEME_ROOT, ROOT_A, obs_a.observation_id),
                            (CounterpartKind.THEME_ROOT, ROOT_C, resolutions["C"].observation.observation_id)}   # C は A と同じ semantic（merge 結果）
    assert rev.provenance.proposer_class is ProposerClass.RULE and rev.dedup_model_version == DEDUP_MODEL_VERSION
    assert rev.subject_proposal_id == subject.proposal_id


def test_32_exact_identity_core_match_theme_vs_proposal(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    widened = variant(obs_a, mechanism=mechanism(consequences=obs_a.mechanism.consequences
                                                 + (consequence(key="c2", target="fx:USDJPY.vol", change=ExpectedChange.INCREASE),)),
                      evidence_refs=())
    assert widened.identity_core_fingerprint == resolutions["A"].derived.identity_core_fingerprint
    assert widened.semantic_fingerprint != resolutions["A"].derived.semantic_fingerprint
    reviews = D.detect_exact_duplicates(widened, resolutions=list(resolutions.values()), created_at=day(20))
    assert [r.dedup_class for r in reviews] == [DedupClass.EXACT_IDENTITY_CORE_MATCH]
    assert reviews[0].comparison_basis.kind is ComparisonBasisKind.IDENTITY_CORE_FINGERPRINT
    assert {c.ref_id for c in reviews[0].counterparts} == {ROOT_A, ROOT_C} and ROOT_B not in {c.ref_id for c in reviews[0].counterparts}


def test_33_proposal_vs_proposal(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    earlier = candidate(obs_a, evidence_refs=obs_a.attachments[:1])
    subject = candidate(obs_a)
    reviews = D.detect_exact_duplicates(subject, proposals=[earlier, subject], created_at=day(20))
    assert len(reviews) == 1 and [(c.kind, c.ref_id, c.observation_id) for c in reviews[0].counterparts] == [
        (CounterpartKind.THEME_PROPOSAL, earlier.proposal_id, "")]
    rejected = decision(earlier.proposal_id, DecisionKind.REJECT, at=day(19))
    assert D.detect_exact_duplicates(subject, proposals=[earlier, subject], decisions=[rejected], created_at=day(20)) == ()   # 却下済みは counterpart にしない
    assert D.detect_exact_duplicates(subject, proposals=[subject], created_at=day(20)) == ()                              # 自分自身は比較しない


def test_34_multiple_exact_counterparts_are_all_returned(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    p1 = candidate(obs_a, evidence_refs=obs_a.attachments[:1])
    p2 = candidate(obs_a, evidence_refs=obs_a.attachments[:2])
    subject = candidate(obs_a)
    reviews = D.detect_exact_duplicates(subject, resolutions=list(resolutions.values()), proposals=[p1, p2, subject], created_at=day(20))
    assert len(reviews) == 1
    refs = [(c.kind.value, c.ref_id) for c in reviews[0].counterparts]
    assert set(refs) == {("THEME_ROOT", ROOT_A), ("THEME_ROOT", ROOT_C), ("THEME_PROPOSAL", p1.proposal_id), ("THEME_PROPOSAL", p2.proposal_id)}
    assert refs == sorted(refs)                                                          # 順序は kind / ref の辞書順のみ（勝者なし）


def test_35_no_fuzzy_classification(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    scoped = variant(obs_a, scope=tuple(s for s in obs_a.scope if s.dimension is not ScopeDimension.REGION)
                     + (ScopeToken(dimension=ScopeDimension.REGION, value="us"),), evidence_refs=())
    assert scoped.identity_core_fingerprint == resolutions["A"].derived.identity_core_fingerprint
    reviews = D.detect_exact_duplicates(scoped, resolutions=list(resolutions.values()), created_at=day(20))
    assert [r.dedup_class for r in reviews] == [DedupClass.EXACT_IDENTITY_CORE_MATCH]      # SCOPE_VARIANT とは名付けない
    assert not any(r.dedup_class in (DedupClass.SCOPE_VARIANT, DedupClass.SUBJECT_VARIANT, DedupClass.MECHANISM_VARIANT,
                                      DedupClass.PARENT_CHILD_CANDIDATE) for r in reviews)
    unrelated = variant(resolutions["B"].observation, evidence_refs=())
    assert D.detect_exact_duplicates(unrelated, resolutions=[resolutions["A"]], created_at=day(20)) == ()


def test_36_no_ranking_or_score(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    reviews = D.detect_exact_duplicates(candidate(obs_a), resolutions=list(resolutions.values()), created_at=day(20))
    for cls in (DedupReviewProposal, type(reviews[0].counterparts[0]), type(reviews[0].comparison_basis)):
        for field in dataclasses.fields(cls):
            assert not any(w in field.name.lower() for w in ("score", "rank", "confidence", "priority", "similarity", "distance", "top"))
            assert field.type not in (float, "float")
    assert not hasattr(D, "rank") and not hasattr(D, "nearest") and not hasattr(D, "similarity")


def test_37_not_duplicate_suppression(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    subject = candidate(obs_a)
    first = D.detect_exact_duplicates(subject, resolutions=[resolutions["A"]], created_at=day(20))[0]
    not_dup = decision(first.proposal_id, DecisionKind.NOT_DUPLICATE, at=day(21), reason="different regime")
    proposals, decisions = [subject, first], [not_dup]
    assert derive_proposal_status(first, decisions) is ProposalStatus.CLOSED_NOT_DUPLICATE
    assert D.detect_exact_duplicates(subject, resolutions=[resolutions["A"]], proposals=proposals, decisions=decisions, created_at=day(22)) == ()
    again = D.detect_exact_duplicates(subject, resolutions=[resolutions["A"], resolutions["C"]], proposals=proposals, decisions=decisions, created_at=day(22))
    assert [c.ref_id for c in again[0].counterparts] == [ROOT_C]                          # 未確定の counterpart だけ提示
    assert D.detect_exact_duplicates(subject, resolutions=[resolutions["A"]], proposals=proposals, decisions=[], created_at=day(22)) == ()   # 同一 id の review は既に存在 → 再提示しない
    assert proposals == [subject, first]                                                  # 履歴は削除されない


def test_38_fingerprint_change_can_reappear(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    subject = candidate(obs_a)
    first = D.detect_exact_duplicates(subject, resolutions=[resolutions["A"]], created_at=day(20))[0]
    decisions = [decision(first.proposal_id, DecisionKind.NOT_DUPLICATE, at=day(21))]
    changed = candidate(obs_a, mechanism=mechanism(consequences=obs_a.mechanism.consequences
                                                    + (consequence(key="c2", target="fx:USDJPY.vol"),)), evidence_refs=())
    reviews = D.detect_exact_duplicates(changed, resolutions=[resolutions["A"]], proposals=[subject, first, changed], decisions=decisions, created_at=day(22))
    assert [r.dedup_class for r in reviews] == [DedupClass.EXACT_IDENTITY_CORE_MATCH]      # 別 subject（別 fingerprint）→ 提示
    resolved_c = resolutions["C"]
    revised_c = dataclasses.replace(resolved_c, derived=dataclasses.replace(resolved_c.derived, semantic_fingerprint=subject.semantic_fingerprint))
    reviews = D.detect_exact_duplicates(subject, resolutions=[revised_c], proposals=[subject, first], decisions=decisions, created_at=day(22))
    assert [c.ref_id for c in reviews[0].counterparts] == [ROOT_C]                       # counterpart 側が変わっても NOT_DUPLICATE は A にだけ効く


def test_39_dedup_model_version_change_can_reappear(world: World, resolutions) -> None:
    obs_a = resolutions["A"].observation
    subject = candidate(obs_a)
    first = D.detect_exact_duplicates(subject, resolutions=[resolutions["A"]], created_at=day(20))[0]
    decisions = [decision(first.proposal_id, DecisionKind.NOT_DUPLICATE, at=day(21))]
    assert D.detect_exact_duplicates(subject, resolutions=[resolutions["A"]], proposals=[subject, first], decisions=decisions, created_at=day(22)) == ()
    reviews = D.detect_exact_duplicates(subject, resolutions=[resolutions["A"]], proposals=[subject, first], decisions=decisions,
                                        created_at=day(22), dedup_model_version="theme_dedup:0.2.0")
    assert len(reviews) == 1 and reviews[0].dedup_model_version == "theme_dedup:0.2.0" and reviews[0].proposal_id != first.proposal_id
