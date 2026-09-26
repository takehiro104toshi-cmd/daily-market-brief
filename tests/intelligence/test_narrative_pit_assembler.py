"""P7-A2 — point-in-time 入力の組み立て（`NarrativeInputSnapshot`）の test matrix A〜AX。

境界の guard（AY〜BH: A1 の凍結・Phase 6 の凍結・認可された importer・network / 永続化 / 時計なし）は
`test_narrative_intelligence_boundary.py`。すべて tmp の合成 data_root 上（本物の Phase 6 store API で書いた journal）。

契約: `docs/databank/PHASE7_NARRATIVE_PIT_INPUT_CONTRACT.md`。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.narrative_intelligence import synthesis_model as A1
from src.intelligence.narrative_intelligence.input_model import (EvidenceConditionFlag, EvidenceSource,
                                                                 NarrativeInputError, NarrativeInputRequest,
                                                                 SourceCapability)
from src.intelligence.narrative_intelligence.pit_assembler import assemble_input_snapshot
from src.intelligence.predictions.evaluation_store import evaluations_path
from src.intelligence.theme_intelligence.llm_generation_journal import generation_journal_path
from src.intelligence.theme_intelligence.monitoring_store import review_state_path
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.relation_model import RelationType
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as relation_proposal_paths
from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
from src.intelligence.theme_intelligence.relation_store import authority_paths as relation_paths
from src.intelligence.themes.model import EvidenceKind as K
from src.intelligence.themes.model import EvidenceRole as Role
from src.intelligence.themes.model import EvidenceTimeQuality, GovernanceEventType, ProvenanceClass, canonical_line
from src.intelligence.themes.revision import attach_evidence
from src.intelligence.themes.store import ThemeStore
from src.intelligence.themes.store import authority_paths as theme_paths
from tests.intelligence.test_theme_model import (ROOT_A, ROOT_B, ROOT_C, T0, attachment, event, observation,
                                                 provenance, root_record, subject)
from tests.intelligence.test_theme_relation import assertion, causal, retraction, sourced
from tests.intelligence.test_theme_relation_proposal import proposal as relation_candidate
from tests.intelligence.theme_foundation_fixtures import (BOJ, CHECKPOINTS, MOF, ROOT_M, ROOT_X, ROOT_Y, ROOT_Z, WIRE,
                                                          build_world)

REPO_ROOT = Path(__file__).resolve().parents[2]
P, Q, R, S = ROOT_X, ROOT_Y, ROOT_Z, ROOT_M
FACT_P, OBS_P, DOC_P, NEWS_P, STMT_P, INV_P = ("fact_" + "1" * 24, "obs_" + "2" * 24, "doc_" + "3" * 24,
                                               "news_" + "4" * 24, "stmt_" + "5" * 24, "doc_" + "6" * 24)
FACT_Q, FACT_R, FACT_S, FACT_LATE, FACT_UNDATED = ("fact_" + c * 24 for c in "789ab")
CANARY_SUBJECT = "canary-subject-4417 rates and bank margins"
CANARY_REASON = "canary-reason-7730 reviewed by committee"
CANARY_NOTE = "canary-note-5511 human judgement on the statement"
CANARY_EXCERPT = "canary-excerpt-9902 the minister said"


def day(n: float, hours: float = 0):
    return T0 + timedelta(days=n, hours=hours)


CUT = day(10)
EARLY = day(1)                                           # 受理（day 2）より前の比較 cutoff


def p_evidence(at):
    return (attachment(FACT_P, K.FACT, day="2026-08-20", attached=at),
            attachment(OBS_P, K.OBSERVATION, day="2026-08-21", attached=at),
            attachment(DOC_P, K.SOURCE_DOCUMENT, src=MOF, day="2026-08-22", attached=at, role=Role.CONTEXT, cref=""),
            attachment(NEWS_P, K.NEWS_ITEM, src=WIRE, day="2026-08-23", attached=at, role=Role.CONTRADICTS, cref=""),
            attachment(STMT_P, K.STATEMENT, src=BOJ, day="2026-08-24", attached=at, provenance=ProvenanceClass.HUMAN,
                       asserted_by="reviewer:r2", note=CANARY_NOTE, excerpt=CANARY_EXCERPT, locator="https://example.invalid/s"),
            attachment(INV_P, K.SOURCE_DOCUMENT, src=MOF, day="2026-08-25", attached=at, role=Role.INVALIDATES, cref="",
                       invalidation_condition_ref="inv1"),
            attachment(FACT_UNDATED, K.FACT, attached=at, role=Role.CONTEXT, cref="",            # 時刻なし（view の外）
                       quality=EvidenceTimeQuality.MISSING))


EVIDENCE = {P: p_evidence,
            Q: lambda at: (attachment(FACT_P, K.FACT, day="2026-08-20", attached=at),
                           attachment(FACT_Q, K.FACT, day="2026-08-26", attached=at)),
            R: lambda at: (attachment(FACT_R, K.FACT, day="2026-08-27", attached=at),),
            S: lambda at: (attachment(FACT_S, K.FACT, day="2026-08-28", attached=at),)}


def build_narrative_world(root: Path) -> dict:
    """P・Q・R は day 2 に受理、S は候補のまま。relation: P→Q（HUMAN）、Q→R（SOURCE）、P→S（集合の外）、R→P（撤回済み）。"""
    store = ThemeStore.initialize(root)
    ids = {}
    for index, root_id in enumerate((P, Q, R, S)):
        at = day(0, index + 1)
        genesis = observation(root_id=root_id, subject=subject(f"{CANARY_SUBJECT} {index}", ""),
                              attachments=EVIDENCE[root_id](at), recorded_at=at,
                              provenance=provenance(reason=CANARY_REASON))
        store.append_root(root_record(genesis, created_at=at))
        store.append_observation(genesis)
        ids[root_id] = genesis.observation_id
    for root_id in (P, Q, R):
        accepted = event(subject_roots=(root_id,), related_observations=(ids[root_id],), recorded_at=day(2),
                         reason=CANARY_REASON)
        store.append_governance(accepted)
        ids[f"{root_id}.accepted"] = accepted.event_id
    relations = ThemeRelationStore.initialize(root)
    relations.append_assertion(causal(P, Q, at=day(3)))
    relations.append_assertion(sourced(Q, R, at=day(3)))
    relations.append_assertion(causal(P, S, at=day(3)))
    withdrawn = assertion(R, P, relation_type=RelationType.MITIGATES, at=day(3))
    relations.append_assertion(withdrawn)
    relations.append_event(retraction(withdrawn, at=day(4)))
    return ids


def add_future(root: Path, ids: dict) -> None:
    """cutoff（day 10）より後だけの記録: P の退役・P の新しい observation と evidence・R→Q の relation。"""
    store = ThemeStore.open(root)
    store.append_governance(event(event_type=GovernanceEventType.RETIRED, subject_roots=(P,), reason="later",
                                  previous_event_ids=((P, ids[f"{P}.accepted"]),), recorded_at=day(12)))
    late = attach_evidence(store.get_observation(ids[P]), (attachment(FACT_LATE, K.FACT, day="2026-09-12",
                                                                      attached=day(13)),),
                           recorded_at=day(13), provenance=provenance(reason="late evidence"))
    store.append_observation(late)
    ThemeRelationStore.open(root).append_assertion(causal(R, Q, at=day(14)))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("narrative_pit") / "data"
    ids = build_narrative_world(root)
    return root, ids


def fresh(world, tmp_path: Path) -> Path:
    target = tmp_path / "copy" / "data"
    shutil.copytree(world[0], target)
    return target


def request(kind="THEME_STATE", roots=(P,), cutoff=CUT, stale=90, comparison=None):
    return NarrativeInputRequest(kind=kind, root_ids=tuple(roots), cutoff=cutoff, stale_after_days=stale,
                                 comparison_cutoff=comparison)


def snap(root, kind="THEME_STATE", roots=(P,), **kw):
    return assemble_input_snapshot(data_root=root, request=request(kind, roots, **kw))


def fails(code, fn, *args, **kwargs):
    with pytest.raises(NarrativeInputError) as info:
        fn(*args, **kwargs)
    assert info.value.code == code, (info.value.code, info.value.detail)
    return info.value


def inventory(root: Path) -> dict:
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir")
            for p in sorted(root.rglob("*"))}


# ================================================================ A〜F 要求と範囲

def test_a_a_valid_theme_state_snapshot(world) -> None:
    snapshot = snap(world[0])
    theme = snapshot.themes[0]
    assert snapshot.kind is A1.NarrativeKind.THEME_STATE and snapshot.root_ids == (P,)
    assert theme.observation.governance_position is A1.GovernancePosition.ACCEPTED
    assert theme.observation.observation_id == world[1][P]
    assert theme.observation.mechanism_certainty is A1.MechanismCertainty.HYPOTHESIZED_MECHANISM
    assert {(c.component_type.value, c.component_key) for c in theme.components} == {
        ("DRIVER", "d1"), ("TRANSMISSION_CHANNEL", "ch1"), ("AFFECTED_DOMAIN", "dom1"),
        ("EXPECTED_OBSERVABLE_CONSEQUENCE", "c1")}
    assert [c.condition_key for c in theme.invalidation_conditions] == ["inv1"]
    assert {a.ref_id for a in theme.attachments} == {FACT_P, OBS_P, DOC_P, NEWS_P, STMT_P, INV_P}
    assert snapshot.relations is None and snapshot.relation_provenance_digest is None
    assert theme.changes is None and snapshot.comparison_cutoff is None
    assert dict(snapshot.reader_versions) == {"theme_resolver": "0.1.0", "theme_lifecycle_model": "0.1.0",
                                              "theme_lifecycle_policy": "0.1.0"}
    assert snapshot.snapshot_id.startswith("narinp_")


def test_b_a_valid_theme_set_snapshot(world) -> None:
    snapshot = snap(world[0], "THEME_SET", (R, P, Q))
    assert snapshot.root_ids == tuple(sorted((P, Q, R))) and [t.root_id for t in snapshot.themes] == sorted((P, Q, R))
    assert {(r.source_root_id, r.target_root_id, r.relation_type.value, r.assertion_class.value)
            for r in snapshot.relations} == {(P, Q, "CAUSES", "HUMAN_ASSERTED"), (Q, R, "AMPLIFIES", "SOURCE_ASSERTED")}
    assert dict(snapshot.reader_versions)["theme_relation_resolver"] == "0.1.0"
    assert snapshot.relation_provenance_digest.startswith("narprv_")


@pytest.mark.parametrize("roots", [(), (P, Q)])
def test_c_theme_state_takes_exactly_one_root(roots) -> None:
    fails("INVALID_SCOPE", request, "THEME_STATE", roots)


def test_d_theme_set_takes_two_or_more_distinct_roots() -> None:
    fails("INVALID_SCOPE", request, "THEME_SET", (P,))
    fails("INVALID_SCOPE", request, "THEME_SET", (P, P))
    fails("INVALID_SCOPE", request, "THEME_SET", tuple(f"theme_01K{'0' * 21}{n:02d}" for n in range(17)))


def test_e_scope_cutoff_and_policy_must_be_explicit(world) -> None:
    for bad in (None, P, [P.lower()], ("all",), ("*",)):
        fails("INVALID_SCOPE", NarrativeInputRequest, kind="THEME_STATE", root_ids=bad, cutoff=CUT,
              stale_after_days=90)
    for cutoff in (None, "latest", "now", CUT.replace(tzinfo=None)):
        fails("INVALID_CUTOFF", request, cutoff=cutoff)
    for stale in (0, -1, True, 90.0, "90", 3651):
        fails("INVALID_POLICY", request, stale=stale)
    with pytest.raises(TypeError):
        NarrativeInputRequest(kind="THEME_STATE", root_ids=(P,), cutoff=CUT)          # policy に既定値は無い
    fails("INVALID_KIND", request, "MARKET_STATE")
    fails("INVALID_REQUEST", assemble_input_snapshot, data_root=world[0], request={"root_ids": [P]})
    for data_root in (None, "", "   "):
        fails("INVALID_DATA_ROOT", assemble_input_snapshot, data_root=data_root, request=request())


def test_f_no_implicit_enumeration_of_themes_or_relations(world) -> None:
    single = snap(world[0])
    assert single.root_ids == (P,) and {s.item.ref_id for s in single.evidence_sources} == {
        FACT_P, OBS_P, DOC_P, NEWS_P, STMT_P, INV_P}                                     # Q・R・S の evidence は入らない
    pair = snap(world[0], "THEME_SET", (P, Q))
    assert pair.root_ids == tuple(sorted((P, Q)))
    assert [(r.source_root_id, r.target_root_id) for r in pair.relations] == [(P, Q)]    # Q→R は R を要求していない
    assert FACT_R not in {s.item.ref_id for s in pair.evidence_sources}


# ================================================================ G〜L 資格と歴史

def test_g_an_accepted_root_is_eligible(world) -> None:
    assert snap(world[0], roots=(Q,)).themes[0].observation.governance_position.value == "ACCEPTED"


def test_h_missing_roots_are_rejected_without_leaking_future_existence(world, tmp_path) -> None:
    error = fails("ROOT_NOT_FOUND", snap, world[0], roots=("theme_" + "Z" * 26,))
    assert error.root_id == "theme_" + "Z" * 26 and error.failures == (("theme_" + "Z" * 26, "ROOT_NOT_FOUND"),)
    fails("ROOT_NOT_FOUND", snap, world[0], cutoff=day(0))                              # P は day 0 + 1h に作成
    foundation = build_world(tmp_path / "foundation", stop_after="genesis_a")
    fails("ROOT_NOT_FOUND", snap, foundation.data_root, roots=(ROOT_A,), cutoff=CHECKPOINTS["before_root"])


def test_i_unresolved_roots_are_rejected(world, tmp_path) -> None:
    foundation = build_world(tmp_path / "foundation", stop_after="genesis_a")
    fails("ROOT_NOT_RESOLVED", snap, foundation.data_root, roots=(ROOT_A,), cutoff=CHECKPOINTS["root_only"])
    root = fresh(world, tmp_path)
    genesis = ThemeStore.open(root, read_only=True).get_observation(world[1][P])
    path = theme_paths(root)["observations"]
    for tag in ("b", "c"):                                          # 同じ前任の 2 つの後継（fork）。store の append は拒むので行を直接
        fork = attach_evidence(genesis, (attachment("fact_" + tag * 24, attached=day(5)),), recorded_at=day(5),
                               provenance=provenance(reason=tag))
        path.write_bytes(path.read_bytes() + canonical_line(fork).encode("utf-8"))
    fails("ROOT_NOT_RESOLVED", snap, root)


def test_j_non_accepted_roots_are_rejected_and_never_dropped(world, tmp_path) -> None:
    fails("ROOT_NOT_ACCEPTED_AT_CUTOFF", snap, world[0], roots=(S,))
    fails("ROOT_NOT_ACCEPTED_AT_CUTOFF", snap, world[0], cutoff=day(1))                  # 受理（day 2）より前
    error = fails("ROOT_NOT_ACCEPTED_AT_CUTOFF", snap, world[0], "THEME_SET", (P, Q, S))
    assert error.failures == ((S, "ROOT_NOT_ACCEPTED_AT_CUTOFF"),)                       # 部分的な snapshot は作らない
    foundation = build_world(tmp_path / "foundation")
    for key, checkpoint in (("A", "retired"), ("A", "merge_completed"), ("B", "merge_completed"),
                            ("C", "merge_completed")):
        root_id = {"A": ROOT_A, "B": ROOT_B, "C": ROOT_C}[key]
        fails("ROOT_NOT_ACCEPTED_AT_CUTOFF", snap, foundation.data_root, roots=(root_id,),
              cutoff=CHECKPOINTS[checkpoint])


def test_k_a_root_accepted_at_the_cutoff_is_reconstructed_despite_later_retirement_and_merge(tmp_path) -> None:
    foundation = build_world(tmp_path / "foundation")                                     # A は後で退役・合併される
    for checkpoint in ("accepted", "semantic_revision", "delayed_evidence_after_attachment", "retirement_reversed"):
        snapshot = snap(foundation.data_root, roots=(ROOT_A,), cutoff=CHECKPOINTS[checkpoint])
        assert snapshot.themes[0].observation.governance_position.value == "ACCEPTED"


def test_l_future_governance_does_not_leak_backward(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    before = snap(root)
    add_future(root, world[1])
    after = snap(root)
    assert after.to_canonical_json() == before.to_canonical_json()                      # 退役（day 12）は見えない
    fails("ROOT_NOT_ACCEPTED_AT_CUTOFF", snap, root, cutoff=day(12))


# ================================================================ M〜P 観測・evidence・lineage・破損

def test_m_future_observations_do_not_alter_the_past(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    before = snap(root, "THEME_SET", (P, Q, R))
    add_future(root, world[1])
    assert snap(root, "THEME_SET", (P, Q, R)).to_canonical_json() == before.to_canonical_json()
    assert snap(root, cutoff=day(11)).themes[0].observation.observation_id == world[1][P]


def test_n_future_evidence_attachments_are_invisible(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    add_future(root, world[1])
    assert FACT_LATE not in {a.ref_id for a in snap(root).themes[0].attachments}
    assert FACT_LATE not in snap(root).to_canonical_json()


def test_o_future_successor_merge_split_do_not_alter_the_past(tmp_path) -> None:
    partial = build_world(tmp_path / "partial", stop_after="reversed")
    full = build_world(tmp_path / "full")                                                  # merge 宣言・結果 root・genesis
    for checkpoint in ("accepted", "retirement_reversed", "before_merge"):
        cutoff = CHECKPOINTS[checkpoint]
        assert (snap(partial.data_root, roots=(ROOT_A,), cutoff=cutoff).to_canonical_json()
                == snap(full.data_root, roots=(ROOT_A,), cutoff=cutoff).to_canonical_json())


def test_p_corruption_is_detected_before_pit_filtering(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    path = theme_paths(root)["governance"]
    path.write_bytes(path.read_bytes() + b'{"event_type":"RETIRED","recorded_at":"2099-01-01T00:00:00+00:00"\n')
    error = fails("AUTHORITY_CORRUPTION", snap, root)                                    # 未来の行でも全体を止める
    assert str(root) not in str(error) and "2099" not in str(error)


# ================================================================ Q〜U evidence の role と本文

@pytest.mark.parametrize("ref_id,role", [(FACT_P, "SUPPORTS"), (NEWS_P, "CONTRADICTS"), (DOC_P, "CONTEXT"),
                                         (INV_P, "INVALIDATES")])
def test_q_to_t_every_role_is_projected_exactly(world, ref_id, role) -> None:
    source = ThemeStore.open(world[0], read_only=True).get_observation(world[1][P]).attachment(
        f"{ref_id}#{'c1' if role == 'SUPPORTS' else ''}")
    projected = {a.ref_id: a for a in snap(world[0]).themes[0].attachments}[ref_id]
    assert projected.role.value == role == source.role.value
    assert projected.role_provenance.value == source.role_provenance.value
    assert projected.attachment_key == source.attachment_key and projected.attached_at == source.attached_at
    assert projected.invalidation_condition_key == source.invalidation_condition_ref


def test_n_evidence_without_a_known_time_stays_outside_the_projection(world) -> None:
    snapshot = snap(world[0])
    assert FACT_UNDATED not in {a.ref_id for a in snapshot.themes[0].attachments}           # resolver の view の外
    assert FACT_UNDATED not in {s.item.ref_id for s in snapshot.evidence_sources}
    stored = ThemeStore.open(world[0], read_only=True).get_observation(world[1][P])
    assert FACT_UNDATED in {a.ref_id for a in stored.attachments}                            # authority には在る


def test_t_invalidating_evidence_keeps_its_condition_and_is_not_executed(world) -> None:
    theme = snap(world[0]).themes[0]
    invalidating = [a for a in theme.attachments if a.role.value == "INVALIDATES"]
    assert [(a.ref_id, a.invalidation_condition_key) for a in invalidating] == [(INV_P, "inv1")]
    assert EvidenceConditionFlag.INVALIDATION_EVIDENCE_PRESENT in theme.evidence_condition_flags
    assert theme.observation.governance_position.value == "ACCEPTED"                       # 無効化 evidence は状態を変えない


def test_u_no_raw_evidence_body_or_human_text_reaches_the_snapshot(world) -> None:
    text = snap(world[0], "THEME_SET", (P, Q, R), comparison=EARLY).to_canonical_json()
    for secret in ("canary-subject-4417", "canary-reason-7730", "canary-note-5511", "canary-excerpt-9902", "margins expand despite weak yen", "hedging ratios",
                   "reviewer:r1", "reviewer:r2", "rule:R1@1", "policy shift lifts construction demand",
                   "publisher:example_wire", "https://", "example.invalid", "release:", "series:jquants", "mof_japan"):
        assert secret not in text, secret
    keys = set()

    def walk(node):
        if isinstance(node, dict):
            keys.update(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(json.loads(text))
    assert not keys & {"excerpt", "locator", "note", "rationale", "statement", "normalized_statement", "reason",
                       "actor_ref", "role_asserted_by", "source_origin", "text", "body", "before", "after", "detail"}


# ================================================================ V〜Y 出所の能力（事実の天井）

@pytest.mark.parametrize("ref_id,capability", [(FACT_P, "OBSERVATIONAL_RECORD"), (OBS_P, "OBSERVATIONAL_RECORD"),
                                               (DOC_P, "SOURCE_CONTENT"), (NEWS_P, "SOURCE_CONTENT"),
                                               (STMT_P, "SOURCE_CONTENT")])
def test_v_to_y_source_capability_follows_the_evidence_kind(world, ref_id, capability) -> None:
    source = {s.item.ref_id: s for s in snap(world[0]).evidence_sources}[ref_id]
    assert source.capability.value == capability


@pytest.mark.parametrize("ref_id", [DOC_P, NEWS_P, STMT_P])
def test_x_y_source_content_cannot_be_promoted_to_a_fact(world, ref_id) -> None:
    item = {s.item.ref_id: s for s in snap(world[0]).evidence_sources}[ref_id].item
    with pytest.raises(NarrativeInputError) as info:
        EvidenceSource(item=item, capability=SourceCapability.OBSERVATIONAL_RECORD)
    assert info.value.code == "SOURCE_CAPABILITY_MISMATCH"
    with pytest.raises(A1.NarrativeModelError) as fact:                                     # A1 の事実の天井も同じ
        A1.NarrativeClaim(epistemic_class="OBSERVED_FACT", claim_kind="EVIDENCE", predicate="EVIDENCE_ITEM_OBSERVED",
                          refs=(item,))
    assert fact.value.code == "FACT_REQUIRES_OBSERVATIONAL_EVIDENCE"


# ================================================================ Z〜AC 変化と比較 cutoff

def test_z_without_a_comparison_cutoff_there_is_no_change_projection(world) -> None:
    snapshot = snap(world[0], "THEME_SET", (P, Q))
    assert all(t.changes is None for t in snapshot.themes)
    assert "theme_change_model" not in dict(snapshot.reader_versions)


def test_aa_a_valid_comparison_cutoff_projects_b1_changes(world) -> None:
    snapshot = snap(world[0], comparison=EARLY)
    changes = snapshot.themes[0].changes
    assert changes and all(c.from_cutoff == EARLY and c.to_cutoff == CUT for c in changes)
    assert {c.change_kind.value for c in changes} == {"GOVERNANCE_CHANGED"}                  # day 1 → day 10 は受理だけ
    assert dict(snapshot.reader_versions)["theme_change_model"] == "0.1.0"
    assert snap(world[0], comparison=day(3)).themes[0].changes == ()                        # 変化なしは空（None ではない）


@pytest.mark.parametrize("comparison", [CUT, CUT + timedelta(seconds=1), EARLY.replace(tzinfo=None), "yesterday"])
def test_ab_comparison_cutoff_must_be_aware_and_strictly_earlier(comparison) -> None:
    fails("INVALID_COMPARISON_CUTOFF", request, comparison=comparison)


def test_ac_future_records_do_not_enter_the_change_window(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    before = snap(root, comparison=EARLY)
    add_future(root, world[1])
    assert snap(root, comparison=EARLY).to_canonical_json() == before.to_canonical_json()


# ================================================================ AD〜AH relation

def test_ad_in_scope_relations_are_projected(world) -> None:
    assert (P, Q) in {(r.source_root_id, r.target_root_id) for r in snap(world[0], "THEME_SET", (P, Q)).relations}


def test_ae_out_of_scope_retracted_and_future_relations_are_excluded(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    add_future(root, world[1])
    pairs = {(r.source_root_id, r.target_root_id) for r in snap(root, "THEME_SET", (P, Q, R)).relations}
    assert pairs == {(P, Q), (Q, R)}                                        # P→S は集合の外・R→P は撤回・R→Q は未来


def test_ae_theme_state_does_not_project_relations(world) -> None:
    assert snap(world[0]).relations is None


def test_af_relation_proposals_are_never_projected(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    RelationProposalStore.initialize(root).append_proposal(relation_candidate(P, R, at=day(5)))
    assert snap(root, "THEME_SET", (P, Q, R)).to_canonical_json() == snap(world[0], "THEME_SET",
                                                                         (P, Q, R)).to_canonical_json()


def test_ag_no_transitive_or_inferred_relation(world) -> None:
    pairs = {(r.source_root_id, r.target_root_id) for r in snap(world[0], "THEME_SET", (P, Q, R)).relations}
    assert (P, R) not in pairs and (R, P) not in pairs                                   # P→Q→R から P→R を作らない


def test_ah_source_asserted_stays_attributed(world) -> None:
    relation = [r for r in snap(world[0], "THEME_SET", (Q, R)).relations][0]
    assert relation.assertion_class is A1.AssertionClass.SOURCE_ASSERTED
    endpoints = (A1.ThemeObservationRef(root_id=Q, observation_id=world[1][Q], governance_position="ACCEPTED",
                                        mechanism_certainty="HYPOTHESIZED_MECHANISM"),
                 A1.ThemeObservationRef(root_id=R, observation_id=world[1][R], governance_position="ACCEPTED",
                                        mechanism_certainty="HYPOTHESIZED_MECHANISM"))
    with pytest.raises(A1.NarrativeModelError) as info:
        A1.NarrativeClaim(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="RELATION",
                          predicate="HUMAN_ASSERTED_RELATION", refs=(relation, *endpoints))
    assert info.value.code == "ASSERTION_CLASS_MISMATCH"


# ================================================================ AI〜AM 除外される入力

def poison(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00not-json-poison\n{broken\n")


@pytest.mark.parametrize("paths", [
    lambda root: tuple(proposal_paths(root).values()),                                     # AI: B3
    lambda root: tuple(relation_proposal_paths(root).values()),                            # AF: B5C
    lambda root: (review_state_path(root),),                                               # AK: B6 review
    lambda root: (generation_journal_path(root),),                                         # AL: B7
    lambda root: (evaluations_path(root), root / "predictions" / "predictions.jsonl"),    # AM: P5
    lambda root: (root / "knowledge" / "theme_taxonomy.0.2.0.yaml",                        # AJ: B4 knowledge
                  root / "knowledge" / "discovery_rules.0.1.0.yaml")],
    ids=["b3_proposals", "b5c_relation_proposals", "b6_review_state", "b7_generation", "p5", "b4_knowledge"])
def test_ai_to_am_excluded_authorities_are_never_read(world, tmp_path, paths) -> None:
    root = fresh(world, tmp_path)
    for path in paths(root):
        poison(path)
    expected = {kind: snap(world[0], kind, roots, comparison=EARLY).to_canonical_json()
                for kind, roots in (("THEME_STATE", (P,)), ("THEME_SET", (P, Q, R)))}
    for kind, roots in (("THEME_STATE", (P,)), ("THEME_SET", (P, Q, R))):
        assert snap(root, kind, roots, comparison=EARLY).to_canonical_json() == expected[kind]


# ================================================================ AN〜AS identity

def test_an_the_snapshot_id_is_deterministic_across_processes(world) -> None:
    code = ("import sys\nfrom src.intelligence.narrative_intelligence.input_model import NarrativeInputRequest\n"
            "from src.intelligence.narrative_intelligence.pit_assembler import assemble_input_snapshot\n"
            "from tests.intelligence.test_narrative_pit_assembler import P, Q, R, CUT, EARLY\n"
            "req = NarrativeInputRequest(kind='THEME_SET', root_ids=(R, Q, P), cutoff=CUT, stale_after_days=90, "
            "comparison_cutoff=EARLY)\n"
            "print(assemble_input_snapshot(data_root=sys.argv[1], request=req).to_canonical_json())\n")
    outputs = {subprocess.run([sys.executable, "-c", code, str(world[0])], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True, env={"PYTHONPATH": str(REPO_ROOT), "PYTHONHASHSEED": seed,
                                                          "PATH": os.environ.get("PATH", "")}).stdout
               for seed in ("1", "2")}
    assert outputs == {snap(world[0], "THEME_SET", (P, Q, R), comparison=EARLY).to_canonical_json() + "\n"}


def test_ao_nonsemantic_order_does_not_change_the_snapshot(world, tmp_path) -> None:
    orders = [snap(world[0], "THEME_SET", roots).to_canonical_json() for roots in ((P, Q, R), (R, Q, P), (Q, P, R))]
    assert len(set(orders)) == 1
    root = fresh(world, tmp_path)
    path = theme_paths(root)["roots"]                                                     # 互いに独立な root 行の物理順
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(reversed(lines)))
    assert snap(root, "THEME_SET", (P, Q, R)).to_canonical_json() == orders[0]


def test_ap_the_cutoff_is_part_of_the_identity(world) -> None:
    base = snap(world[0])
    later = snap(world[0], cutoff=CUT + timedelta(seconds=1))
    assert later.themes == base.themes and later.snapshot_id != base.snapshot_id


def test_aq_the_comparison_cutoff_is_part_of_the_identity(world) -> None:
    assert snap(world[0], comparison=day(3)).snapshot_id != snap(world[0], comparison=day(4)).snapshot_id
    assert snap(world[0], comparison=day(3)).snapshot_id != snap(world[0]).snapshot_id


def test_ar_semantic_authority_changes_change_the_identity(world, tmp_path) -> None:
    base = snap(world[0])
    root = fresh(world, tmp_path)
    store = ThemeStore.open(root)
    store.append_observation(attach_evidence(store.get_observation(world[1][P]),
                                             (attachment(FACT_LATE, K.FACT, day="2026-09-05", attached=day(6)),),
                                             recorded_at=day(6), provenance=provenance(reason="more")))
    assert snap(root).snapshot_id != base.snapshot_id
    reviewed = fresh(world, tmp_path / "b")                                                # 退役して取り消す（投影は同じ）
    store = ThemeStore.open(reviewed)
    retired = event(event_type=GovernanceEventType.RETIRED, subject_roots=(P,), reason="x",
                    previous_event_ids=((P, world[1][f"{P}.accepted"]),), recorded_at=day(5))
    store.append_governance(retired)
    store.append_governance(event(event_type=GovernanceEventType.EVENT_REVERSED, subject_roots=(P,), reason="y",
                                  reverses_event_id=retired.event_id, previous_event_ids=((P, retired.event_id),),
                                  recorded_at=day(6)))
    changed = snap(reviewed)
    assert changed.themes[0].attachments == base.themes[0].attachments
    assert changed.themes[0].provenance_digest != base.themes[0].provenance_digest
    assert changed.snapshot_id != base.snapshot_id
    assert snap(world[0], stale=30).snapshot_id != base.snapshot_id                       # policy は identity に入る


def test_as_path_and_mtime_do_not_change_the_identity(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    for path in root.rglob("*"):
        os.utime(path, (1_000_000_000, 1_000_000_000))
    for kind, roots in (("THEME_STATE", (P,)), ("THEME_SET", (P, Q, R))):
        assert (snap(root, kind, roots, comparison=EARLY).to_canonical_json()
                == snap(world[0], kind, roots, comparison=EARLY).to_canonical_json())
    assert str(root) not in snap(root).to_canonical_json() and str(world[0]) not in snap(world[0]).to_canonical_json()


# ================================================================ AT〜AX 書き込みなし・破損

def test_at_au_assembly_writes_zero_bytes_and_creates_no_file(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    before = inventory(root)
    snap(root)
    snap(root, "THEME_SET", (P, Q, R), comparison=EARLY)
    for bad in ((S,), ("theme_" + "Z" * 26,)):
        with pytest.raises(NarrativeInputError):
            snap(root, roots=bad)
    assert inventory(root) == before
    bare = tmp_path / "bare"
    ThemeStore.initialize(bare)
    before = inventory(bare)
    with pytest.raises(NarrativeInputError):
        snap(bare)
    fails("AUTHORITY_UNAVAILABLE", snap, tmp_path / "missing")
    assert inventory(bare) == before and not (tmp_path / "missing").exists()


def test_au_a_missing_relation_authority_fails_closed_without_being_created(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    for path in relation_paths(root).values():
        path.unlink()
    before = inventory(root)
    assert snap(root).themes                                                              # THEME_STATE は relation を読まない
    fails("RELATION_AUTHORITY_UNAVAILABLE", snap, root, "THEME_SET", (P, Q))              # 空として扱わない
    assert inventory(root) == before


@pytest.mark.parametrize("authority", ["roots", "observations", "governance"])
def test_av_aw_a_corrupt_theme_or_evidence_journal_fails_closed(world, tmp_path, authority) -> None:
    root = fresh(world, tmp_path)
    path = theme_paths(root)[authority]
    path.write_bytes(path.read_bytes()[:-7] + b"\n")                                      # 最後の行を切り詰める
    fails("AUTHORITY_CORRUPTION", snap, root)


def test_aw_a_rewritten_evidence_role_in_the_journal_is_rejected_not_projected(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    path = theme_paths(root)["observations"]
    text = path.read_text(encoding="utf-8")
    assert '"role":"CONTRADICTS"' in text
    path.write_text(text.replace('"role":"CONTRADICTS"', '"role":"SUPPORTS"', 1), encoding="utf-8")
    error = fails("AUTHORITY_CORRUPTION", snap, root)
    assert "SUPPORTS" not in str(error)


def test_ax_a_corrupt_relation_journal_fails_closed_for_theme_sets(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    path = relation_paths(root)["assertions"]
    path.write_bytes(path.read_bytes() + b"{not json\n")
    fails("AUTHORITY_CORRUPTION", snap, root, "THEME_SET", (P, Q))
    assert snap(root).themes                                                              # THEME_STATE は読まない（契約 §13）


def test_errors_carry_codes_not_paths_or_content(world, tmp_path) -> None:
    for attempt in (lambda: snap(tmp_path / "missing"), lambda: snap(world[0], roots=(S,)),
                    lambda: snap(world[0], "THEME_SET", (P, S))):
        with pytest.raises(NarrativeInputError) as info:
            attempt()
        text = str(info.value) + info.value.detail
        assert str(tmp_path) not in text and str(world[0]) not in text and "canary" not in text


# ================================================================ A3 への引き継ぎ（test 側の写像。runtime の A3 ではない）

def test_the_snapshot_refs_are_directly_usable_by_the_frozen_a1_model(world) -> None:
    """snapshot の ref だけで A1 の NarrativeSynthesis が組める（隠さない規則も満たせる）ことの確認。"""
    snapshot = snap(world[0], "THEME_SET", (P, Q, R), comparison=EARLY)
    C = A1.NarrativeClaim
    claims = []
    for theme in snapshot.themes:
        obs = theme.observation
        claims.append(C(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="STATE",
                        predicate="THEME_REVIEWED_STATE", refs=(obs,)))
        claims += [C(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="MECHANISM",
                     predicate="RECORDS_MECHANISM_COMPONENT", refs=(c,)) for c in theme.components]
        claims.append(C(epistemic_class="UNCERTAINTY", claim_kind="MECHANISM", predicate="IS_UNCERTAIN", refs=(obs,),
                        uncertainty_code="MECHANISM_HYPOTHESIZED"))
        claims += [C(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="INVALIDATION",
                     predicate="RECORDS_INVALIDATION_CONDITION", refs=(c,)) for c in theme.invalidation_conditions]
        conditions = {c.condition_key: c for c in theme.invalidation_conditions}
        for att in theme.attachments:
            claims.append(C(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="EVIDENCE",
                            predicate="EVIDENCE_ATTACHED", refs=(att,)))
            if att.role.value == "INVALIDATES":
                claims.append(C(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="INVALIDATION",
                                predicate="INVALIDATING_EVIDENCE_ATTACHED",
                                refs=(conditions[att.invalidation_condition_key], att)))
        roles = {a.role.value for a in theme.attachments}
        if {"SUPPORTS", "CONTRADICTS"} <= roles:
            claims.append(C(epistemic_class="UNCERTAINTY", claim_kind="EVIDENCE", predicate="IS_UNCERTAIN",
                            refs=(obs, *[a for a in theme.attachments if a.role.value in ("SUPPORTS", "CONTRADICTS")]),
                            uncertainty_code="CONTESTED_EVIDENCE"))
        claims += [C(epistemic_class="DERIVED_SYNTHESIS", claim_kind="CHANGE", predicate="CHANGED_BETWEEN_CUTOFFS",
                     refs=(c,)) for c in theme.changes]
    claims += [C(epistemic_class="OBSERVED_FACT", claim_kind="EVIDENCE", predicate="EVIDENCE_ITEM_OBSERVED",
                 refs=(s.item,)) for s in snapshot.evidence_sources
               if s.capability is SourceCapability.OBSERVATIONAL_RECORD]
    observations = {t.root_id: t.observation for t in snapshot.themes}
    for relation in snapshot.relations:
        predicate = ("SOURCE_ASSERTED_RELATION" if relation.assertion_class.value == "SOURCE_ASSERTED"
                     else "HUMAN_ASSERTED_RELATION")
        claims.append(C(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="RELATION", predicate=predicate,
                        refs=(relation, observations[relation.source_root_id], observations[relation.target_root_id])))
    synthesis = A1.NarrativeSynthesis(kind="THEME_SET", subject_root_ids=snapshot.root_ids, cutoff=snapshot.cutoff,
                                      knowledge_pins=snapshot.reader_versions,
                                      input_digest=snapshot.snapshot_id, claims=tuple(claims))
    assert A1.NarrativeSynthesis.from_json(synthesis.to_canonical_json()) == synthesis


def test_the_snapshot_states_its_authority_and_has_no_restore_api() -> None:
    from src.intelligence.narrative_intelligence import input_model
    assert "non-authoritative" in input_model.SNAPSHOT_IS_NOT_AUTHORITY
    assert "non-persistent" in input_model.SNAPSHOT_IS_NOT_AUTHORITY
    assert not hasattr(input_model.NarrativeInputSnapshot, "from_dict")
    assert not hasattr(input_model.NarrativeInputSnapshot, "from_json")
