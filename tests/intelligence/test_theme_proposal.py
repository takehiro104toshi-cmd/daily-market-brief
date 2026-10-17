"""P6-B3 — proposal model / store / decision / derived status / accept bridge の契約 test（matrix 1〜30、40〜50）。

書き込みは tmp_path のみ。Foundation store には一切書かない（bytes 不変を固定）。
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence import proposal_bridge as B
from src.intelligence.theme_intelligence import proposal_resolution as R
from src.intelligence.theme_intelligence.proposal_model import (
    DECISION_SCHEMA_VERSION, DEDUP_MODEL_VERSION, PROPOSAL_SCHEMA_VERSION, ComparisonBasis, ComparisonBasisKind,
    CounterpartKind, DecisionKind, DedupClass, DedupCounterpart, DedupReviewProposal, EvidenceCandidateProposal,
    ProposalDecision, ProposalModelError, ProposalProvenance, ProposalType, ProposerClass, ThemeCandidateProposal,
    canonical_proposal_line, parse_proposal,
)
from src.intelligence.theme_intelligence.proposal_store import (
    AppendStatus, ProposalAppendRejected, ProposalConcurrentModification, ProposalConflict, ProposalInvalidHistory,
    ProposalStore, ProposalStoreCorrupt, authority_paths,
)
from src.intelligence.themes.model import (
    EvidenceKind, EvidenceRole, EvidenceTimeBasis, EvidenceTimeQuality, ProvenanceClass, ThemeObservation,
)
from src.intelligence.themes.resolver import ThemeHistory, resolve
from src.intelligence.themes.store import ThemeStore
from tests.intelligence.test_theme_model import FACT_B, ROOT_A, attachment, origin
from tests.intelligence.theme_foundation_fixtures import World, authority_bytes, build_world, day

UTC = timezone.utc
HUMAN = ProposalProvenance(ProposerClass.HUMAN, "reviewer:r9", reason="analyst draft")
RULE = ProposalProvenance(ProposerClass.RULE, "rule:theme_dedup_exact", rule_version=DEDUP_MODEL_VERSION)
T20 = day(20)


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    return build_world(tmp_path_factory.mktemp("proposal_world") / "data")


@pytest.fixture(scope="module")
def observation(world: World) -> ThemeObservation:
    return world.resolve("A", "accepted").observation


def candidate(obs: ThemeObservation, *, created_at=T20, provenance=HUMAN, **override) -> ThemeCandidateProposal:
    kwargs = dict(subject=obs.subject, mechanism=obs.mechanism, certainty_class=obs.certainty_class, scope=obs.scope,
                  invalidation_conditions=obs.invalidation_conditions, limitations=obs.limitations,
                  evidence_refs=obs.attachments, provenance=provenance, created_at=created_at)
    kwargs.update(override)
    return ThemeCandidateProposal.build(**kwargs)


def evidence_candidate(created_at=T20, **override) -> EvidenceCandidateProposal:
    kwargs = dict(evidence_kind=EvidenceKind.FACT, ref_id=FACT_B, source_origin=origin(), evidence_time=day(-2),
                  evidence_time_basis=EvidenceTimeBasis.KNOWN_AT, evidence_time_quality=EvidenceTimeQuality.RELIABLE,
                  evidence_date="2026-08-30", proposed_role=EvidenceRole.SUPPORTS, reason="topix close series moved with input cost print",
                  provenance=HUMAN, created_at=created_at)
    kwargs.update(override)
    return EvidenceCandidateProposal.build(**kwargs)


def review(subject: ThemeCandidateProposal, counterpart_root: str, observation_id: str, created_at=day(20, 1)) -> DedupReviewProposal:
    return DedupReviewProposal.build(
        subject_proposal_id=subject.proposal_id,
        counterparts=(DedupCounterpart(CounterpartKind.THEME_ROOT, counterpart_root, subject.semantic_fingerprint, observation_id),),
        dedup_class=DedupClass.EXACT_SEMANTIC_MATCH,
        comparison_basis=ComparisonBasis(ComparisonBasisKind.SEMANTIC_FINGERPRINT, subject.semantic_fingerprint),
        provenance=RULE, created_at=created_at)


def decision(proposal_id: str, kind: DecisionKind, *, at, supersedes: str = "", reason: str = "reviewed", actor="reviewer:r9") -> ProposalDecision:
    return ProposalDecision.build(proposal_id=proposal_id, decision=kind, actor_ref=actor, reason=reason, recorded_at=at,
                                  supersedes_decision_id=supersedes)


def seeded(tmp_path: Path, obs: ThemeObservation):
    store = ProposalStore.initialize(tmp_path)
    cand = candidate(obs)
    store.append_proposal(cand)
    return store, cand


# ---------------------------------------------------------------- 1〜13 model / store

def test_01_theme_candidate_is_canonical_and_round_trips(observation: ThemeObservation, world: World) -> None:
    cand = candidate(observation)
    assert cand.proposal_id.startswith("thprop_") and cand.schema_version == PROPOSAL_SCHEMA_VERSION
    assert cand.proposal_type is ProposalType.THEME_CANDIDATE
    line = canonical_proposal_line(cand)
    assert line.endswith("\n") and json.loads(line)["proposal_id"] == cand.proposal_id
    assert ThemeCandidateProposal.from_dict(json.loads(line)) == cand and parse_proposal(json.loads(line)) == cand
    derived = world.resolve("A", "accepted").derived
    assert cand.semantic_fingerprint == derived.semantic_fingerprint             # Foundation と同じ純関数・同じ値
    assert cand.identity_core_fingerprint == derived.identity_core_fingerprint
    assert "root_id" not in json.loads(line) and "observation_id" not in json.loads(line)   # Theme ではない
    with pytest.raises(ProposalModelError, match="MISSING_INVALIDATION_CONDITION"):
        candidate(observation, invalidation_conditions=())
    with pytest.raises(ProposalModelError, match="MISSING_SCOPE"):
        candidate(observation, scope=tuple(s for s in observation.scope if s.dimension.value != "PERIOD_FRAME"))
    with pytest.raises(ProposalModelError, match="FINGERPRINT_MISMATCH"):
        dataclasses.replace(cand, semantic_fingerprint="thsem_" + "0" * 24)


def test_02_evidence_candidate_is_canonical(observation: ThemeObservation) -> None:
    ev = evidence_candidate()
    assert ev.proposal_type is ProposalType.EVIDENCE_CANDIDATE and ev.proposal_id.startswith("thprop_")
    assert parse_proposal(json.loads(canonical_proposal_line(ev))) == ev
    with pytest.raises(ProposalModelError, match="REF_ID_KIND_MISMATCH"):
        evidence_candidate(ref_id="doc_" + "1" * 24)
    with pytest.raises(ProposalModelError, match="NOT_NORMALIZED"):
        evidence_candidate(reason="Mixed Case Reason")
    missing = evidence_candidate(evidence_time=None, evidence_time_basis=EvidenceTimeBasis.NONE,
                                 evidence_time_quality=EvidenceTimeQuality.MISSING, evidence_date="", proposed_role=EvidenceRole.CONTEXT)
    assert missing.evidence_time is None
    with pytest.raises(ProposalModelError, match="MISSING_EVIDENCE_TIME"):
        evidence_candidate(evidence_time_quality=EvidenceTimeQuality.MISSING)
    promoted = evidence_candidate(target_proposal_id=candidate(observation).proposal_id)
    assert promoted.proposal_id != ev.proposal_id                                  # 昇格は新 proposal、旧 proposal は不変


def test_03_dedup_review_is_canonical(observation: ThemeObservation, world: World) -> None:
    cand = candidate(observation)
    rev = review(cand, ROOT_A, observation.observation_id)
    assert rev.proposal_type is ProposalType.DEDUP_REVIEW and parse_proposal(json.loads(canonical_proposal_line(rev))) == rev
    with pytest.raises(ProposalModelError, match="DEDUP_CLASS_NOT_AUTOMATABLE"):
        dataclasses.replace(rev, dedup_class=DedupClass.SCOPE_VARIANT)
    with pytest.raises(ProposalModelError, match="INVALID_ROLE_COMBINATION"):
        DedupReviewProposal.build(subject_proposal_id=cand.proposal_id, counterparts=rev.counterparts, dedup_class=rev.dedup_class,
                                  comparison_basis=rev.comparison_basis, provenance=HUMAN, created_at=T20)
    with pytest.raises(ProposalModelError, match="identical fingerprints"):
        DedupReviewProposal.build(subject_proposal_id=cand.proposal_id,
                                  counterparts=(DedupCounterpart(CounterpartKind.THEME_ROOT, ROOT_A, "thsem_" + "1" * 24, observation.observation_id),),
                                  dedup_class=rev.dedup_class, comparison_basis=rev.comparison_basis, provenance=RULE, created_at=T20)


def test_04_aware_utc_required(observation: ThemeObservation) -> None:
    naive = datetime(2026, 9, 21, 0, 0)
    with pytest.raises(ProposalModelError, match="NAIVE_DATETIME"):
        candidate(observation, created_at=naive)
    with pytest.raises(ProposalModelError, match="NAIVE_DATETIME"):
        decision(candidate(observation).proposal_id, DecisionKind.ACCEPT, at=naive)
    with pytest.raises(ProposalModelError, match="NAIVE_DATETIME"):
        evidence_candidate(evidence_time=naive)


def test_05_content_ids_are_deterministic_and_exclude_audit_fields(observation: ThemeObservation) -> None:
    a = candidate(observation, created_at=T20)
    b = candidate(observation, created_at=day(25), provenance=ProposalProvenance(ProposerClass.RULE, "rule:x"))
    assert a.proposal_id == b.proposal_id and canonical_proposal_line(a) != canonical_proposal_line(b)   # id 同・bytes 異
    shuffled = candidate(observation, evidence_refs=tuple(reversed(observation.attachments)),
                         invalidation_conditions=tuple(reversed(observation.invalidation_conditions)))
    assert shuffled.proposal_id == a.proposal_id and shuffled == a                    # 入力順に依らない
    other = candidate(observation, evidence_refs=observation.attachments[:1])
    assert other.proposal_id != a.proposal_id                                          # evidence 参照は identity に含む
    d1 = decision(a.proposal_id, DecisionKind.ACCEPT, at=T20)
    d2 = decision(a.proposal_id, DecisionKind.ACCEPT, at=day(30))
    assert d1.decision_id == d2.decision_id and d1.schema_version == DECISION_SCHEMA_VERSION  # recorded_at は audit-only


def test_06_same_id_same_bytes_is_idempotent(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    before = authority_paths(tmp_path)["proposals"].read_bytes()
    assert store.append_proposal(cand).status is AppendStatus.ALREADY_PRESENT
    assert authority_paths(tmp_path)["proposals"].read_bytes() == before and store.counts()["proposals"] == 1


def test_07_same_id_different_bytes_is_conflict(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    later = candidate(observation, created_at=day(25))
    assert later.proposal_id == cand.proposal_id
    with pytest.raises(ProposalConflict):
        store.append_proposal(later)
    assert store.counts()["proposals"] == 1


@pytest.mark.parametrize("how,code", [("malformed", "MALFORMED_JSON"), ("noncanonical", "NON_CANONICAL_LINE"),
                                      ("truncated", "TRUNCATED_FINAL_LINE"), ("blank", "BLANK_LINE"),
                                      ("duplicate_conflict", "PHYSICAL_DUPLICATE_CONFLICTING"), ("bad_id", "INVALID_RECORD")])
def test_08_10_corruption_fails_closed(tmp_path: Path, observation: ThemeObservation, how: str, code: str) -> None:
    store, cand = seeded(tmp_path, observation)
    path = authority_paths(tmp_path)["proposals"]
    line = canonical_proposal_line(cand)
    if how == "malformed":
        path.write_bytes(path.read_bytes() + b"{not json\n")
    elif how == "noncanonical":
        spaced = json.dumps(json.loads(line), ensure_ascii=False, sort_keys=True, separators=(", ", ": "))   # 1 行だが非 canonical
        path.write_bytes(path.read_bytes() + (spaced + "\n").encode("utf-8"))
    elif how == "truncated":
        path.write_bytes(path.read_bytes()[:-1])
    elif how == "blank":
        path.write_bytes(path.read_bytes() + b"\n")
    elif how == "duplicate_conflict":
        conflicting = candidate(observation, created_at=day(25))                          # 同 id・異 bytes（canonical）
        path.write_bytes(path.read_bytes() + canonical_proposal_line(conflicting).encode("utf-8"))
    elif how == "bad_id":
        payload = json.loads(line)
        payload["proposal_id"] = "thprop_" + "0" * 24
        path.write_bytes((json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    frozen = path.read_bytes()
    with pytest.raises(ProposalStoreCorrupt) as info:
        ProposalStore.open(tmp_path, read_only=True)
    assert info.value.code == code and info.value.authority == "proposals"
    assert path.read_bytes() == frozen                                                 # 修復・truncate しない


def test_11_read_only_store_does_not_write(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    reader = ProposalStore.open(tmp_path, read_only=True)
    with pytest.raises(ProposalAppendRejected, match="READ_ONLY"):
        reader.append_decision(decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21)))
    assert reader.counts() == {"proposals": 1, "decisions": 0}
    with pytest.raises(ProposalStoreCorrupt, match="AUTHORITY_MISSING"):
        ProposalStore.open(tmp_path / "nowhere")                                       # open は作らない
    with pytest.raises(ProposalAppendRejected, match="DATA_ROOT_REQUIRED"):
        ProposalStore.open("")


def test_12_external_mutation_is_detected_before_append(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    with authority_paths(tmp_path)["decisions"].open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(ProposalConcurrentModification):
        store.append_decision(decision(cand.proposal_id, DecisionKind.DEFER, at=day(21)))


def test_13_no_repair_and_no_foundation_write(tmp_path: Path, world: World, observation: ThemeObservation) -> None:
    foundation_before = authority_bytes(world.data_root)
    store = ProposalStore.initialize(world.data_root)                                 # 同じ data_root でも別 directory
    cand = candidate(observation)
    store.append_proposal(cand)
    store.append_decision(decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21)))
    assert authority_bytes(world.data_root) == foundation_before                       # Foundation の 5 authority は不変
    assert set(authority_paths(world.data_root)) == {"proposals", "decisions"}
    assert not any(p.parent.name == "themes" for p in authority_paths(world.data_root).values())
    assert ThemeStore.open(world.data_root, read_only=True).counts()["roots"] == 3    # Foundation は proposal を知らない
    path = authority_paths(world.data_root)["decisions"]
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ProposalStoreCorrupt):
        ProposalStore.open(world.data_root)
    path.write_bytes(path.read_bytes() + b"\n")                                        # 復元（world を汚さない）
    assert ProposalStore.open(world.data_root, read_only=True).counts()["decisions"] == 1


# ---------------------------------------------------------------- 14〜24 decisions

def test_14_16_accept_reject_defer(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    for kind, status in ((DecisionKind.DEFER, R.ProposalStatus.OPEN_DEFERRED),):
        store.append_decision(decision(cand.proposal_id, kind, at=day(21)))
        assert R.derive_proposal_status(cand, store.decisions()) is status
    other = candidate(observation, evidence_refs=observation.attachments[:1])
    store.append_proposal(other)
    accept = decision(other.proposal_id, DecisionKind.ACCEPT, at=day(21))
    store.append_decision(accept)
    assert R.derive_proposal_status(other, store.decisions()) is R.ProposalStatus.ACCEPTED
    third = candidate(observation, evidence_refs=())
    store.append_proposal(third)
    store.append_decision(decision(third.proposal_id, DecisionKind.REJECT, at=day(21)))
    assert R.derive_proposal_status(third, store.decisions()) is R.ProposalStatus.REJECTED
    resolution = R.resolve_active_decision(other.proposal_id, store.decisions())
    assert resolution.status is R.DecisionResolutionStatus.RESOLVED and resolution.active_decision == accept
    with pytest.raises(ProposalModelError, match="INVALID_ROLE_COMBINATION"):        # HUMAN 以外は decision を書けない
        dataclasses.replace(accept, actor_class=ProposerClass.RULE)


def test_17_defer_then_accept(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    deferred = decision(cand.proposal_id, DecisionKind.DEFER, at=day(21))
    store.append_decision(deferred)
    accepted = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(22), supersedes=deferred.decision_id)
    store.append_decision(accepted)
    assert R.derive_proposal_status(cand, store.decisions()) is R.ProposalStatus.ACCEPTED
    assert R.resolve_active_decision(cand.proposal_id, store.decisions()).chain == (deferred.decision_id, accepted.decision_id)
    assert store.get_decision(deferred.decision_id) == deferred                       # 旧 decision は残る


def test_18_reject_then_accept_is_an_explicit_reconsideration(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    rejected = decision(cand.proposal_id, DecisionKind.REJECT, at=day(21))
    store.append_decision(rejected)
    with pytest.raises(ProposalAppendRejected, match="MISSING_PREDECESSOR"):         # 黙った再開始は不可
        store.append_decision(decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(22)))
    reconsidered = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(22), supersedes=rejected.decision_id, reason="new evidence")
    store.append_decision(reconsidered)
    assert R.derive_proposal_status(cand, store.decisions()) is R.ProposalStatus.ACCEPTED


def test_19_correction_supersedes(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    wrong = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21))
    store.append_decision(wrong)
    fixed = decision(cand.proposal_id, DecisionKind.REJECT, at=day(21, 1), supersedes=wrong.decision_id, reason="clerical error")
    store.append_decision(fixed)
    assert R.resolve_active_decision(cand.proposal_id, store.decisions()).active_decision == fixed
    with pytest.raises(ProposalAppendRejected, match="NON_TERMINAL_PREDECESSOR"):
        store.append_decision(decision(cand.proposal_id, DecisionKind.DEFER, at=day(22), supersedes=wrong.decision_id))
    with pytest.raises(ProposalAppendRejected, match="NON_MONOTONIC_RECORDED_AT"):
        store.append_decision(decision(cand.proposal_id, DecisionKind.DEFER, at=day(20, 12), supersedes=fixed.decision_id))


def test_20_fork_is_unresolved(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    first = decision(cand.proposal_id, DecisionKind.DEFER, at=day(21))
    left = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(22), supersedes=first.decision_id)
    right = decision(cand.proposal_id, DecisionKind.REJECT, at=day(23), supersedes=first.decision_id)
    resolution = R.resolve_active_decision(cand.proposal_id, (right, first, left))
    assert resolution.status is R.DecisionResolutionStatus.UNRESOLVED and "FORK" in resolution.diagnostics
    assert R.derive_proposal_status(cand, (first, left, right)) is R.ProposalStatus.OPEN_UNRESOLVED
    path = authority_paths(tmp_path)["decisions"]
    for d in (first, left, right):
        path.write_bytes(path.read_bytes() + canonical_proposal_line(d).encode("utf-8"))
    reopened = ProposalStore.open(tmp_path)
    assert [d.kind for d in reopened.diagnostics()] == ["DECISION_FORK"]
    with pytest.raises(ProposalAppendRejected, match="FORKED_PROPOSAL"):
        reopened.append_decision(decision(cand.proposal_id, DecisionKind.DEFER, at=day(24), supersedes=left.decision_id))


def test_21_dangling_predecessor_is_invalid(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    dangling = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21), supersedes="thdec_" + "9" * 24)
    assert R.resolve_active_decision(cand.proposal_id, (dangling,)).status is R.DecisionResolutionStatus.INVALID
    assert R.derive_proposal_status(cand, (dangling,)) is R.ProposalStatus.INVALID_DECISION_HISTORY
    with pytest.raises(ProposalAppendRejected, match="DANGLING_PREDECESSOR"):
        store.append_decision(dangling)
    path = authority_paths(tmp_path)["decisions"]
    path.write_bytes(path.read_bytes() + canonical_proposal_line(dangling).encode("utf-8"))
    with pytest.raises(ProposalInvalidHistory, match="DANGLING_PREDECESSOR"):
        ProposalStore.open(tmp_path)
    other = candidate(observation, evidence_refs=())
    foreign = decision(other.proposal_id, DecisionKind.DEFER, at=day(21))
    cross = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(22), supersedes=foreign.decision_id)
    assert R.resolve_active_decision(cand.proposal_id, (foreign, cross)).diagnostics == ("WRONG_PROPOSAL_PREDECESSOR",)


def test_22_cycle_is_invalid(observation: ThemeObservation) -> None:
    cand = candidate(observation)
    a = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21), supersedes="thdec_" + "a" * 24)
    b = dataclasses.replace(decision(cand.proposal_id, DecisionKind.DEFER, at=day(22), supersedes=a.decision_id),
                            decision_id="thdec_" + "a" * 24) if False else None
    # 合成: 互いを指す 2 decision（id は内容から決まるため、手で cycle を作るには id を偽る必要がある → INVALID_RECORD_ID）
    with pytest.raises(ProposalModelError, match="INVALID_RECORD_ID"):
        dataclasses.replace(a, decision_id="thdec_" + "b" * 24)
    # id 検証を通る cycle は content id では構成できない。resolver 単体には start 無しの入力で CYCLE を固定する
    loop = R.resolve_active_decision(cand.proposal_id, ())
    assert loop.status is R.DecisionResolutionStatus.NONE
    class _Fake:
        def __init__(self, decision_id, proposal_id, supersedes):
            self.decision_id, self.proposal_id, self.supersedes_decision_id = decision_id, proposal_id, supersedes
            self.decision = DecisionKind.ACCEPT
    x, y = _Fake("thdec_" + "1" * 24, cand.proposal_id, "thdec_" + "2" * 24), _Fake("thdec_" + "2" * 24, cand.proposal_id, "thdec_" + "1" * 24)
    assert R.resolve_active_decision(cand.proposal_id, (x, y)).diagnostics == ("CYCLE",)     # type: ignore[arg-type]


def test_23_physical_order_and_timestamps_pick_no_winner(tmp_path: Path, observation: ThemeObservation) -> None:
    cand = candidate(observation)
    first = decision(cand.proposal_id, DecisionKind.DEFER, at=day(21))
    late = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(30), supersedes=first.decision_id)
    early = decision(cand.proposal_id, DecisionKind.REJECT, at=day(22), supersedes=first.decision_id)
    for ordering in ((first, late, early), (early, late, first), (late, early, first)):
        resolution = R.resolve_active_decision(cand.proposal_id, ordering)
        assert resolution.status is R.DecisionResolutionStatus.UNRESOLVED and resolution.active_decision is None
    linear = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(22), supersedes=first.decision_id)
    assert R.resolve_active_decision(cand.proposal_id, (linear, first)) == R.resolve_active_decision(cand.proposal_id, (first, linear))


def test_24_not_duplicate_only_for_dedup_reviews(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    with pytest.raises(ProposalAppendRejected, match="DECISION_NOT_ALLOWED"):
        store.append_decision(decision(cand.proposal_id, DecisionKind.NOT_DUPLICATE, at=day(21)))
    rev = review(cand, ROOT_A, observation.observation_id)
    store.append_proposal(rev)
    store.append_decision(decision(rev.proposal_id, DecisionKind.NOT_DUPLICATE, at=day(21)))
    assert R.derive_proposal_status(rev, store.decisions()) is R.ProposalStatus.CLOSED_NOT_DUPLICATE
    ev = evidence_candidate()
    store.append_proposal(ev)
    with pytest.raises(ProposalAppendRejected, match="DECISION_NOT_ALLOWED"):
        store.append_decision(decision(ev.proposal_id, DecisionKind.NOT_DUPLICATE, at=day(21)))


# ---------------------------------------------------------------- 25〜30 derived status

def test_25_30_derived_statuses_and_open_proposals(tmp_path: Path, observation: ThemeObservation) -> None:
    store, open_cand = seeded(tmp_path, observation)
    deferred_cand = candidate(observation, evidence_refs=observation.attachments[:2]); store.append_proposal(deferred_cand)
    accepted_cand = candidate(observation, evidence_refs=observation.attachments[:1]); store.append_proposal(accepted_cand)
    rejected_cand = candidate(observation, evidence_refs=()); store.append_proposal(rejected_cand)
    rev = review(open_cand, ROOT_A, observation.observation_id); store.append_proposal(rev)
    store.append_decision(decision(deferred_cand.proposal_id, DecisionKind.DEFER, at=day(21)))
    store.append_decision(decision(accepted_cand.proposal_id, DecisionKind.ACCEPT, at=day(21)))
    store.append_decision(decision(rejected_cand.proposal_id, DecisionKind.REJECT, at=day(21)))
    store.append_decision(decision(rev.proposal_id, DecisionKind.NOT_DUPLICATE, at=day(21)))
    decisions = store.decisions()
    unresolved_cand = evidence_candidate(); store.append_proposal(unresolved_cand)
    fork = (decision(unresolved_cand.proposal_id, DecisionKind.ACCEPT, at=day(21)),
            decision(unresolved_cand.proposal_id, DecisionKind.REJECT, at=day(21, 1)))       # 2 start ＝ fork（合成）
    statuses = {
        "open": R.derive_proposal_status(open_cand, decisions), "deferred": R.derive_proposal_status(deferred_cand, decisions),
        "accepted": R.derive_proposal_status(accepted_cand, decisions), "rejected": R.derive_proposal_status(rejected_cand, decisions),
        "not_dup": R.derive_proposal_status(rev, decisions), "unresolved": R.derive_proposal_status(unresolved_cand, decisions + fork)}
    assert statuses == {"open": R.ProposalStatus.OPEN, "deferred": R.ProposalStatus.OPEN_DEFERRED,
                        "accepted": R.ProposalStatus.ACCEPTED, "rejected": R.ProposalStatus.REJECTED,
                        "not_dup": R.ProposalStatus.CLOSED_NOT_DUPLICATE, "unresolved": R.ProposalStatus.OPEN_UNRESOLVED}
    open_items = R.derive_open_proposals(store.proposals(), decisions + fork)
    assert {(o.proposal_id, o.status) for o in open_items} == {
        (open_cand.proposal_id, R.ProposalStatus.OPEN), (deferred_cand.proposal_id, R.ProposalStatus.OPEN_DEFERRED),
        (unresolved_cand.proposal_id, R.ProposalStatus.OPEN_UNRESOLVED)}
    assert [o.proposal_id for o in open_items] == sorted(o.proposal_id for o in open_items)   # 決定論的順序


# ---------------------------------------------------------------- 40〜50 accept bridge

def test_40_accepted_theme_candidate_yields_a_plan(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    accept = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21))
    store.append_decision(accept)
    plan = B.plan_theme_creation_from_accepted_proposal(cand, store.decisions(), created_at=day(22))
    assert plan.plan_version == B.BRIDGE_PLAN_VERSION and plan.creator_class is ProvenanceClass.HUMAN
    assert plan.subject == cand.subject and plan.mechanism == cand.mechanism and plan.scope == cand.scope
    assert [a.attachment_key for a in plan.attachments] == [a.attachment_key for a in cand.evidence_refs]
    assert all(a.attached_at == day(22) for a in plan.attachments) and plan.created_at == day(22)
    assert plan.provenance.writer_class is ProvenanceClass.HUMAN and plan.provenance.writer_ref == "reviewer:r9"
    assert plan.semantic_fingerprint == cand.semantic_fingerprint


def test_41_44_bridge_requires_an_active_accept(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    with pytest.raises(B.BridgeError, match="NOT_ACCEPTED"):                            # 41 decision なし
        B.plan_theme_creation_from_accepted_proposal(cand, store.decisions(), created_at=day(22))
    deferred = decision(cand.proposal_id, DecisionKind.DEFER, at=day(21))
    with pytest.raises(B.BridgeError, match="NOT_ACCEPTED"):                            # 42 DEFER
        B.plan_theme_creation_from_accepted_proposal(cand, (deferred,), created_at=day(22))
    rejected = decision(cand.proposal_id, DecisionKind.REJECT, at=day(21))
    with pytest.raises(B.BridgeError, match="NOT_ACCEPTED"):                            # 43 REJECT
        B.plan_theme_creation_from_accepted_proposal(cand, (rejected,), created_at=day(22))
    fork = (deferred, decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(22), supersedes=deferred.decision_id),
            decision(cand.proposal_id, DecisionKind.REJECT, at=day(23), supersedes=deferred.decision_id))
    with pytest.raises(B.BridgeError, match="NOT_ACCEPTED"):                            # 44 unresolved
        B.plan_theme_creation_from_accepted_proposal(cand, fork, created_at=day(24))
    accept = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21))
    with pytest.raises(B.BridgeError, match="CREATED_BEFORE_DECISION"):
        B.plan_theme_creation_from_accepted_proposal(cand, (accept,), created_at=day(20, 23))


def test_45_46_only_theme_candidates_bridge(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    ev = evidence_candidate(); store.append_proposal(ev)
    rev = review(cand, ROOT_A, observation.observation_id); store.append_proposal(rev)
    store.append_decision(decision(ev.proposal_id, DecisionKind.ACCEPT, at=day(21)))
    store.append_decision(decision(rev.proposal_id, DecisionKind.ACCEPT, at=day(21)))
    for proposal in (ev, rev):
        with pytest.raises(B.BridgeError, match="PROPOSAL_TYPE_NOT_BRIDGEABLE"):
            B.plan_theme_creation_from_accepted_proposal(proposal, store.decisions(), created_at=day(22))   # type: ignore[arg-type]


def test_47_48_plan_carries_provenance_and_no_root_id(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    accept = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21))
    store.append_decision(accept)
    plan = B.plan_theme_creation_from_accepted_proposal(cand, store.decisions(), created_at=day(22))
    assert plan.proposal_id == cand.proposal_id and plan.decision_id == accept.decision_id
    assert cand.proposal_id in plan.creation_provenance and accept.decision_id in plan.creation_provenance
    assert accept.decision_id in plan.provenance.reason
    assert "root_id" not in B.PLAN_FIELDS and not hasattr(plan, "root_id")
    assert not any("theme_0" in str(getattr(plan, f)) for f in B.PLAN_FIELDS)            # root id らしき値を含まない


def test_49_bridge_writes_nothing(tmp_path: Path, world: World, observation: ThemeObservation) -> None:
    store = ProposalStore.initialize(tmp_path)
    cand = candidate(observation); store.append_proposal(cand)
    store.append_decision(decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21)))
    foundation = authority_bytes(world.data_root)
    proposals = {n: p.read_bytes() for n, p in authority_paths(tmp_path).items()}
    B.plan_theme_creation_from_accepted_proposal(cand, store.decisions(), created_at=day(22))
    assert authority_bytes(world.data_root) == foundation
    assert {n: p.read_bytes() for n, p in authority_paths(tmp_path).items()} == proposals
    assert ThemeStore.open(world.data_root, read_only=True).counts()["roots"] == 3


def test_50_plan_is_deterministic(tmp_path: Path, observation: ThemeObservation) -> None:
    store, cand = seeded(tmp_path, observation)
    accept = decision(cand.proposal_id, DecisionKind.ACCEPT, at=day(21))
    store.append_decision(accept)
    first = B.plan_theme_creation_from_accepted_proposal(cand, store.decisions(), created_at=day(22))
    second = B.plan_theme_creation_from_accepted_proposal(cand, tuple(reversed(store.decisions())), created_at=day(22))
    assert first == second and hash(first) == hash(second)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.created_at = day(23)                                                       # type: ignore[misc]
