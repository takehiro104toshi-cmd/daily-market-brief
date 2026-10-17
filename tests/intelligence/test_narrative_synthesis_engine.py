"""P7-A3 — 決定論の synthesis engine（`NarrativeInputSnapshot` → `NarrativeSynthesis`）の test matrix A〜BN。

静的な境界（import・AST の guard、A1 / A2 / Phase 6 の byte 凍結、未登録 runtime の検出）は
`test_narrative_intelligence_boundary.py` にもある。snapshot は A2 の本物の組み立て（tmp の合成 data_root）から作る。

契約: `docs/databank/PHASE7_NARRATIVE_DETERMINISTIC_SYNTHESIS_CONTRACT.md`。
"""
from __future__ import annotations

import builtins
import copy
import dataclasses
import inspect
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.narrative_intelligence import input_model
from src.intelligence.narrative_intelligence import synthesis_engine as E
from src.intelligence.narrative_intelligence import synthesis_model as A1
from src.intelligence.narrative_intelligence.input_model import (EvidenceSource, NarrativeInputSnapshot,
                                                                 SourceCapability, ThemeInput)
from src.intelligence.narrative_intelligence.synthesis_engine import (NarrativeSynthesisError, revalidate,
                                                                      synthesis_from_claims, synthesize)
from src.intelligence.themes.model import EvidenceKind as K
from src.intelligence.themes.model import EvidenceRole as Role
from src.intelligence.themes.store import ThemeStore
from tests.intelligence.test_narrative_pit_assembler import (CUT, DOC_P, EARLY, FACT_P, INV_P, NEWS_P, OBS_P, P, Q, R,
                                                             STMT_P, add_future, build_narrative_world, day, snap)
from tests.intelligence.test_theme_model import attachment, event, observation, provenance, root_record, subject
from tests.intelligence.theme_foundation_fixtures import MOF, ROOT_N, ROOT_Q

REPO_ROOT = Path(__file__).resolve().parents[2]
BARE, CTX = ROOT_N, ROOT_Q                                   # 付与なしの Theme・CONTEXT だけの Theme
DOC_CTX = "doc_" + "d" * 24


def build_engine_world(root: Path) -> dict:
    """A2 の world（P・Q・R・S）に、evidence の無い受理済み Theme と CONTEXT だけの受理済み Theme を足す。"""
    ids = build_narrative_world(root)
    store = ThemeStore.open(root)
    for index, (root_id, evidence) in enumerate(((BARE, ()), (CTX, (DOC_CTX,)))):
        at = day(0, 6 + index)
        attachments = tuple(attachment(ref, K.SOURCE_DOCUMENT, src=MOF, day="2026-08-29", attached=at,
                                       role=Role.CONTEXT, cref="") for ref in evidence)
        genesis = observation(root_id=root_id, subject=subject(f"engine theme {index}", ""), attachments=attachments,
                              recorded_at=at, provenance=provenance(reason="engine world"))
        store.append_root(root_record(genesis, created_at=at))
        store.append_observation(genesis)
        store.append_governance(event(subject_roots=(root_id,), related_observations=(genesis.observation_id,),
                                      recorded_at=day(2)))
        ids[root_id] = genesis.observation_id
    return ids


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("narrative_engine") / "data"
    ids = build_engine_world(root)
    return root, ids


@pytest.fixture(scope="module")
def state_snapshot(world):
    return snap(world[0])


@pytest.fixture(scope="module")
def set_snapshot(world):
    return snap(world[0], "THEME_SET", (P, Q, R), comparison=EARLY)


def fails(code, fn, *args, **kwargs):
    with pytest.raises(NarrativeSynthesisError) as info:
        fn(*args, **kwargs)
    assert info.value.code == code, (info.value.code, info.value.detail)
    return info.value


def claims_of(synthesis, predicate=None, code=None):
    return [c for c in synthesis.claims if (predicate is None or c.predicate.value == predicate)
            and (code is None or (c.uncertainty_code and c.uncertainty_code.value == code))]


def signature(claim):
    return (claim.epistemic_class.value, claim.claim_kind.value, claim.predicate.value,
            claim.uncertainty_code.value if claim.uncertainty_code else None,
            frozenset(A1.canonical_json(r.to_dict()) for r in claim.refs))


def expected_signatures(snapshot):
    """規則表を engine とは独立に書き下した期待（どの claim も snapshot の材料 1 つ以上に対応する）。"""
    J = lambda *refs: frozenset(A1.canonical_json(r.to_dict()) for r in refs)          # noqa: E731
    RI, UN = "REVIEWED_INTERPRETATION", "UNCERTAINTY"
    out = set()
    for t in snapshot.themes:
        o = t.observation
        out.add((RI, "STATE", "THEME_REVIEWED_STATE", None, J(o)))
        out |= {(RI, "MECHANISM", "RECORDS_MECHANISM_COMPONENT", None, J(c)) for c in t.components}
        if t.components and o.mechanism_certainty.value == "HYPOTHESIZED_MECHANISM":
            out.add((UN, "MECHANISM", "IS_UNCERTAIN", "MECHANISM_HYPOTHESIZED", J(o)))
        out |= {(RI, "EVIDENCE", "EVIDENCE_ATTACHED", None, J(a)) for a in t.attachments}
        sup = [a for a in t.attachments if a.role.value == "SUPPORTS"]
        con = [a for a in t.attachments if a.role.value == "CONTRADICTS"]
        if sup and con:
            out.add((UN, "EVIDENCE", "IS_UNCERTAIN", "CONTESTED_EVIDENCE", J(o, *sup, *con)))
        flags = {f.value for f in t.evidence_condition_flags}
        if "NO_VISIBLE_EVIDENCE" in flags and not sup:
            out.add((UN, "EVIDENCE", "IS_UNCERTAIN", "NO_SUPPORTING_EVIDENCE", J(o)))
        for flag, code in (("SINGLE_SOURCE", "SINGLE_SOURCE_EVIDENCE"), ("STALE", "STALE_EVIDENCE")):
            if flag in flags:
                out.add((UN, "EVIDENCE", "IS_UNCERTAIN", code, J(o)))
        conditions = {c.condition_key: c for c in t.invalidation_conditions}
        out |= {(RI, "INVALIDATION", "RECORDS_INVALIDATION_CONDITION", None, J(c)) for c in t.invalidation_conditions}
        out |= {(RI, "INVALIDATION", "INVALIDATING_EVIDENCE_ATTACHED", None,
                 J(conditions[a.invalidation_condition_key], a)) for a in t.attachments if a.role.value == "INVALIDATES"}
        out |= {("DERIVED_SYNTHESIS", "CHANGE", "CHANGED_BETWEEN_CUTOFFS", None, J(c)) for c in t.changes or ()}
    out |= {("OBSERVED_FACT", "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", None, J(s.item)) for s in snapshot.evidence_sources
            if s.capability.value == "OBSERVATIONAL_RECORD"}
    obs = {t.root_id: t.observation for t in snapshot.themes}
    for r in snapshot.relations or ():
        predicate = "SOURCE_ASSERTED_RELATION" if r.assertion_class.value == "SOURCE_ASSERTED" else "HUMAN_ASSERTED_RELATION"
        out.add((RI, "RELATION", predicate, None, J(r, obs[r.source_root_id], obs[r.target_root_id])))
    if snapshot.kind.value == "THEME_SET":
        shared = {}
        for t in snapshot.themes:
            for a in sorted(t.attachments, key=lambda a: a.attachment_key):
                if a.role.value == "SUPPORTS":
                    shared.setdefault(a.ref_id, {}).setdefault(t.root_id, (t.observation, a))
        out |= {("ALTERNATIVE_HYPOTHESIS", "MECHANISM", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE", None,
                 J(*[ref for pair in by_root.values() for ref in pair])) for by_root in shared.values() if len(by_root) > 1}
    return out


# ================================================================ A〜D 正しい synthesis と決定論

def test_a_a_valid_theme_state_synthesis(state_snapshot) -> None:
    synthesis = synthesize(state_snapshot)
    assert isinstance(synthesis, A1.NarrativeSynthesis) and synthesis.kind is A1.NarrativeKind.THEME_STATE
    assert synthesis.subject_root_ids == (P,) and synthesis.cutoff == CUT
    assert synthesis.input_digest == state_snapshot.snapshot_id                          # snapshot の provenance
    assert synthesis.knowledge_pins == tuple(sorted(state_snapshot.reader_versions
                                                   + (("narrative_synthesis_rules", "0.1.0"),)))   # 余計な pin なし
    assert A1.NarrativeSynthesis.from_json(synthesis.to_canonical_json()) == synthesis


def test_b_a_valid_theme_set_synthesis(set_snapshot) -> None:
    synthesis = synthesize(set_snapshot)
    assert synthesis.kind is A1.NarrativeKind.THEME_SET and synthesis.subject_root_ids == tuple(sorted((P, Q, R)))
    assert {signature(c) for c in synthesis.claims} == expected_signatures(set_snapshot)


def test_c_replay_is_byte_identical_in_process_and_across_processes(world, set_snapshot) -> None:
    first = synthesize(set_snapshot).to_canonical_json()
    assert all(synthesize(set_snapshot).to_canonical_json() == first for _ in range(3))
    code = ("import sys\nfrom src.intelligence.narrative_intelligence.synthesis_engine import synthesize\n"
            "from tests.intelligence.test_narrative_pit_assembler import snap, P, Q, R, EARLY\n"
            "print(synthesize(snap(sys.argv[1], 'THEME_SET', (R, P, Q), comparison=EARLY)).to_canonical_json())\n")
    outputs = {subprocess.run([sys.executable, "-c", code, str(world[0])], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True, env={"PYTHONPATH": str(REPO_ROOT), "PYTHONHASHSEED": seed,
                                                          "PATH": os.environ.get("PATH", "")}).stdout
               for seed in ("3", "4")}
    assert outputs == {first + "\n"}


def permuted(snapshot):
    """非意味的な並び（Theme・component・attachment・flag・source・relation・reader）を逆にした同じ snapshot。"""
    themes = tuple(ThemeInput(observation=t.observation, components=tuple(reversed(t.components)),
                              invalidation_conditions=tuple(reversed(t.invalidation_conditions)),
                              attachments=tuple(reversed(t.attachments)),
                              evidence_condition_flags=tuple(reversed(t.evidence_condition_flags)),
                              changes=None if t.changes is None else tuple(reversed(t.changes)),
                              provenance_digest=t.provenance_digest) for t in reversed(snapshot.themes))
    return NarrativeInputSnapshot(kind=snapshot.kind, root_ids=tuple(reversed(snapshot.root_ids)),
                                  cutoff=snapshot.cutoff, comparison_cutoff=snapshot.comparison_cutoff, themes=themes,
                                  evidence_sources=tuple(reversed(snapshot.evidence_sources)),
                                  relations=None if snapshot.relations is None else tuple(reversed(snapshot.relations)),
                                  relation_provenance_digest=snapshot.relation_provenance_digest,
                                  reader_versions=tuple(reversed(snapshot.reader_versions)),
                                  stale_after_days=snapshot.stale_after_days)


def test_d_nonsemantic_input_permutations_do_not_change_the_output(world, set_snapshot) -> None:
    base = synthesize(set_snapshot)
    assert synthesize(permuted(set_snapshot)).to_canonical_json() == base.to_canonical_json()
    for roots in ((R, Q, P), (Q, R, P)):
        assert synthesize(snap(world[0], "THEME_SET", roots, comparison=EARLY)).synthesis_id == base.synthesis_id


# ================================================================ E〜H 解釈と機構

def test_e_each_reviewed_theme_yields_one_reviewed_interpretation_state(set_snapshot) -> None:
    states = claims_of(synthesize(set_snapshot), "THEME_REVIEWED_STATE")
    assert sorted(c.refs[0].root_id for c in states) == sorted((P, Q, R))
    assert all(c.epistemic_class.value == "REVIEWED_INTERPRETATION" for c in states)


def test_f_interpretation_never_becomes_an_observed_fact(set_snapshot) -> None:
    for claim in claims_of(synthesize(set_snapshot)):
        if claim.epistemic_class.value == "OBSERVED_FACT":
            assert [type(r).__name__ for r in claim.refs] == ["EvidenceItemRef"]
        elif any(isinstance(r, A1.EvidenceItemRef) for r in claim.refs):
            pytest.fail("an evidence item is cited outside an observed fact claim")


def test_g_mechanism_certainty_is_carried_never_strengthened(set_snapshot, world) -> None:
    synthesis = synthesize(set_snapshot)
    given = {t.root_id: t.observation.mechanism_certainty for t in set_snapshot.themes}
    for claim in synthesis.claims:
        for ref in claim.refs:
            if isinstance(ref, A1.ThemeObservationRef):
                assert ref.mechanism_certainty is given[ref.root_id]
    assert len(claims_of(synthesis, "IS_UNCERTAIN", "MECHANISM_HYPOTHESIZED")) == 3        # 仮説のまま示す


def test_h_no_new_causal_link_is_inserted(set_snapshot) -> None:
    synthesis = synthesize(set_snapshot)
    components = {A1.canonical_json(c.to_dict()) for t in set_snapshot.themes for c in t.components}
    recorded = claims_of(synthesis, "RECORDS_MECHANISM_COMPONENT")
    assert {A1.canonical_json(c.refs[0].to_dict()) for c in recorded} == components and len(recorded) == len(components)
    assert all(len(c.refs) == 1 for c in recorded)                                       # component 同士を結ばない
    assert len(claims_of(synthesis, "HUMAN_ASSERTED_RELATION") + claims_of(synthesis, "SOURCE_ASSERTED_RELATION")) \
        == len(set_snapshot.relations)


# ================================================================ I〜O evidence の role

def attached(synthesis, ref_id):
    return [c.refs[0] for c in claims_of(synthesis, "EVIDENCE_ATTACHED") if c.refs[0].ref_id == ref_id]


@pytest.mark.parametrize("ref_id,role", [(FACT_P, "SUPPORTS"), (NEWS_P, "CONTRADICTS"), (DOC_P, "CONTEXT"),
                                         (INV_P, "INVALIDATES")])
def test_i_j_m_n_every_role_surfaces_unchanged(state_snapshot, ref_id, role) -> None:
    assert [a.role.value for a in attached(synthesize(state_snapshot), ref_id)] == [role]


def test_k_support_and_contradiction_stay_visible_together(state_snapshot) -> None:
    synthesis = synthesize(state_snapshot)
    contested = claims_of(synthesis, "IS_UNCERTAIN", "CONTESTED_EVIDENCE")
    assert len(contested) == 1
    roles = sorted(r.role.value for r in contested[0].refs if isinstance(r, A1.EvidenceAttachmentRef))
    assert "SUPPORTS" in roles and "CONTRADICTS" in roles
    assert attached(synthesis, FACT_P) and attached(synthesis, NEWS_P)                  # 片方を消さない


def walk(node, keys, values):
    if isinstance(node, dict):
        keys.update(node)
        for value in node.values():
            walk(value, keys, values)
    elif isinstance(node, list):
        for value in node:
            walk(value, keys, values)
    else:
        values.append(node)


def test_l_no_net_score_winner_or_number_exists(set_snapshot) -> None:
    keys, values = set(), []
    walk(json.loads(synthesize(set_snapshot).to_canonical_json()), keys, values)
    assert not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
    assert not keys & {"score", "net", "winner", "weight", "rank", "confidence", "probability", "balance", "primary"}


def test_m_context_never_becomes_support(set_snapshot, world) -> None:
    synthesis = synthesize(snap(world[0], "THEME_SET", (P, CTX)))
    assert [a.role.value for a in attached(synthesis, DOC_CTX)] == ["CONTEXT"]
    assert not claims_of(synthesis, "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE")
    for claim in synthesize(set_snapshot).claims:
        for ref in claim.refs:
            if isinstance(ref, A1.EvidenceAttachmentRef) and ref.ref_id == DOC_P:
                assert ref.role.value == "CONTEXT"


def test_n_o_invalidation_is_explicit_and_changes_no_governance(state_snapshot) -> None:
    synthesis = synthesize(state_snapshot)
    invalidating = claims_of(synthesis, "INVALIDATING_EVIDENCE_ATTACHED")
    assert len(invalidating) == 1
    condition, evidence = sorted(invalidating[0].refs, key=lambda r: type(r).__name__ != "InvalidationConditionRef")
    assert condition.condition_key == "inv1" and evidence.ref_id == INV_P and evidence.role.value == "INVALIDATES"
    assert [c.refs[0].condition_key for c in claims_of(synthesis, "RECORDS_INVALIDATION_CONDITION")] == ["inv1"]
    assert claims_of(synthesis, "THEME_REVIEWED_STATE")[0].refs[0].governance_position.value == "ACCEPTED"
    assert not any(w in p.value for p in A1.Predicate for w in ("INVALIDATED", "RETIRE", "FALSIFIED", "REFUTED"))


# ================================================================ P〜U 事実の天井

def observed(synthesis):
    return {c.refs[0].ref_id: c.refs[0] for c in claims_of(synthesis, "EVIDENCE_ITEM_OBSERVED")}


@pytest.mark.parametrize("ref_id,kind", [(FACT_P, "FACT"), (OBS_P, "OBSERVATION")])
def test_p_q_observational_records_may_be_observed_facts(state_snapshot, ref_id, kind) -> None:
    item = observed(synthesize(state_snapshot))[ref_id]
    assert item.evidence_kind.value == kind


@pytest.mark.parametrize("ref_id", [DOC_P, INV_P, NEWS_P, STMT_P])
def test_r_s_t_documents_news_and_statements_are_never_world_facts(state_snapshot, ref_id) -> None:
    assert ref_id not in observed(synthesize(state_snapshot))
    capability = {s.item.ref_id: s.capability for s in state_snapshot.evidence_sources}[ref_id]
    assert capability is SourceCapability.SOURCE_CONTENT


def test_u_a_reference_alone_never_yields_invented_content(state_snapshot) -> None:
    for claim in claims_of(synthesize(state_snapshot), "EVIDENCE_ITEM_OBSERVED"):
        assert set(claim.refs[0].to_dict()) == {"ref_type", "ref_id", "evidence_kind", "evidence_time", "time_quality"}
    assert {f.name for f in dataclasses.fields(A1.NarrativeClaim)} == {
        "epistemic_class", "claim_kind", "predicate", "refs", "uncertainty_code", "claim_id"}     # 本文の欄は無い


# ================================================================ V〜Y 変化

def test_v_no_comparison_means_no_change_claim(state_snapshot, world) -> None:
    assert not claims_of(synthesize(state_snapshot), "CHANGED_BETWEEN_CUTOFFS")
    assert not claims_of(synthesize(snap(world[0], "THEME_SET", (P, Q))), "CHANGED_BETWEEN_CUTOFFS")


def test_w_explicit_changes_map_one_to_one(set_snapshot, world) -> None:
    changes = claims_of(synthesize(set_snapshot), "CHANGED_BETWEEN_CUTOFFS")
    projected = [c for t in set_snapshot.themes for c in t.changes]
    assert sorted(A1.canonical_json(c.refs[0].to_dict()) for c in changes) == sorted(
        A1.canonical_json(c.to_dict()) for c in projected)
    empty = snap(world[0], comparison=day(3))                                               # 変化なしの窓
    assert empty.themes[0].changes == () and not claims_of(synthesize(empty), "CHANGED_BETWEEN_CUTOFFS")


def test_x_no_momentum_or_trend_inference(set_snapshot) -> None:
    words = ("ACCELERAT", "WEAKEN", "STRENGTH", "EMERG", "FADING", "MOMENTUM", "TREND", "RISING", "FALLING")
    text = synthesize(set_snapshot).to_canonical_json()
    assert not any(word in text for word in words)
    assert not any(word in rule.predicate for rule in E.RULES for word in words)


def test_y_the_engine_sees_only_the_snapshot(world, tmp_path) -> None:
    assert list(inspect.signature(synthesize).parameters) == ["snapshot"]
    copy = tmp_path / "data"
    shutil.copytree(world[0], copy)
    before = snap(copy)
    add_future(copy, world[1])
    assert synthesize(snap(copy)).to_canonical_json() == synthesize(before).to_canonical_json()
    shutil.rmtree(copy)                                                                   # authority が消えても同じ
    assert synthesize(before).to_canonical_json() == synthesize(snap(world[0])).to_canonical_json()


# ================================================================ Z〜AH relation と順位なし

def relations(synthesis):
    return {(r.source_root_id, r.target_root_id, c.predicate.value) for c in synthesis.claims
            if c.claim_kind.value == "RELATION" for r in c.refs if isinstance(r, A1.RelationAssertionRef)}


def test_z_explicit_relations_become_relation_claims(set_snapshot) -> None:
    assert relations(synthesize(set_snapshot)) == {(P, Q, "HUMAN_ASSERTED_RELATION"),
                                                   (Q, R, "SOURCE_ASSERTED_RELATION")}


def test_aa_no_relation_input_means_no_relation_claim(state_snapshot, world) -> None:
    assert relations(synthesize(state_snapshot)) == set()
    assert relations(synthesize(snap(world[0], "THEME_SET", (P, Q)))) == {(P, Q, "HUMAN_ASSERTED_RELATION")}
    assert relations(synthesize(snap(world[0], "THEME_SET", (P, BARE)))) == set()


def test_ab_ac_no_transitive_or_reverse_relation(set_snapshot) -> None:
    pairs = {(s, t) for s, t, _ in relations(synthesize(set_snapshot))}
    assert (P, R) not in pairs and (Q, P) not in pairs and (R, Q) not in pairs


def test_ad_source_asserted_stays_source_asserted(set_snapshot) -> None:
    [claim] = [c for c in synthesize(set_snapshot).claims if c.predicate.value == "SOURCE_ASSERTED_RELATION"]
    assert claim.epistemic_class.value == "REVIEWED_INTERPRETATION"
    assert [r.assertion_class.value for r in claim.refs if isinstance(r, A1.RelationAssertionRef)] == ["SOURCE_ASSERTED"]
    assert A1.SOURCE_ASSERTED_MEANING == "a source asserted this relation; the narrative does not assert it"


def test_ae_af_ag_no_ranking_dominance_or_beneficiary(set_snapshot, world) -> None:
    synthesis = synthesize(set_snapshot)
    assert list(synthesis.subject_root_ids) == sorted(synthesis.subject_root_ids)
    assert [c.claim_id for c in synthesis.claims] == sorted(c.claim_id for c in synthesis.claims)
    assert {f.name for f in dataclasses.fields(A1.NarrativeSynthesis)} == {
        "kind", "subject_root_ids", "cutoff", "knowledge_pins", "input_digest", "claims", "synthesis_id"}
    text = synthesis.to_canonical_json().lower()
    assert not any(word in text for word in ("dominant", "primary", "winner", "beneficiar", "rank", "top_theme"))
    state = {c.claim_id for c in synthesize(snap(world[0])).claims}                        # 集合に入っても P の claim は同じ
    assert state <= {c.claim_id for c in synthesize(snap(world[0], "THEME_SET", (P, Q, R))).claims}


def test_ah_shared_evidence_is_never_turned_into_a_relation(set_snapshot) -> None:
    synthesis = synthesize(set_snapshot)
    [alternative] = claims_of(synthesis, "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE")
    assert alternative.claim_kind.value == "MECHANISM" and alternative.epistemic_class.value == "ALTERNATIVE_HYPOTHESIS"
    assert {(s, t) for s, t, _ in relations(synthesis)} == {(P, Q), (Q, R)}                  # P と Q の共有は relation に無い


# ================================================================ AI〜AL 不確実性と代替

def test_ai_uncertainty_is_generated_only_from_explicit_conditions(world) -> None:
    stale = synthesize(snap(world[0], stale=10))                                            # 最新の evidence から 10 日超
    assert claims_of(stale, "IS_UNCERTAIN", "STALE_EVIDENCE")
    assert not claims_of(synthesize(snap(world[0])), "IS_UNCERTAIN", "STALE_EVIDENCE")
    bare = synthesize(snap(world[0], roots=(BARE,)))
    assert claims_of(bare, "IS_UNCERTAIN", "NO_SUPPORTING_EVIDENCE")
    context_only = synthesize(snap(world[0], roots=(CTX,)))
    assert claims_of(context_only, "IS_UNCERTAIN", "NO_SUPPORTING_EVIDENCE")
    assert claims_of(synthesize(snap(world[0], roots=(R,))), "IS_UNCERTAIN", "SINGLE_SOURCE_EVIDENCE")
    supported = synthesize(snap(world[0], roots=(Q,)))
    assert not claims_of(supported, "IS_UNCERTAIN", "NO_SUPPORTING_EVIDENCE")


def test_aj_no_numeric_confidence_or_probability(set_snapshot) -> None:
    assert not any(c.isdigit() for code in A1.UncertaintyCode for c in code.value)
    keys, values = set(), []
    walk(json.loads(synthesize(set_snapshot).to_canonical_json()), keys, values)
    assert not keys & {"confidence", "probability", "likelihood", "score"}


def test_ak_alternatives_are_unranked_and_order_free(set_snapshot) -> None:
    [alternative] = claims_of(synthesize(set_snapshot), "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE")
    roots = sorted({r.root_id for r in alternative.refs})
    assert roots == sorted((P, Q)) and all(r.role.value == "SUPPORTS" for r in alternative.refs
                                           if isinstance(r, A1.EvidenceAttachmentRef))
    assert [A1.canonical_json(r.to_dict()) for r in alternative.refs] == sorted(
        A1.canonical_json(r.to_dict()) for r in alternative.refs)
    assert synthesize(permuted(set_snapshot)).to_canonical_json() == synthesize(set_snapshot).to_canonical_json()


def test_al_insufficient_structure_yields_no_alternative(world) -> None:
    assert not claims_of(synthesize(snap(world[0])), "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE")    # THEME_STATE
    assert not claims_of(synthesize(snap(world[0], "THEME_SET", (Q, R))),
                         "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE")                                  # 共有なし
    assert not claims_of(synthesize(snap(world[0], "THEME_SET", (CTX, R))),
                         "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE")


# ================================================================ AM〜AQ 収束・順序・identity

def test_am_duplicate_claims_converge(set_snapshot) -> None:
    claims = synthesize(set_snapshot).claims
    doubled = E._converge([("R01_REVIEWED_STATE", c) for c in claims if c.predicate.value == "THEME_REVIEWED_STATE"] * 2)
    assert len(doubled) == 3
    assert len(observed(synthesize(set_snapshot))) == len({FACT_P, OBS_P, "fact_" + "7" * 24, "fact_" + "8" * 24})


def test_an_the_same_id_with_different_material_fails_closed(state_snapshot) -> None:
    [state] = claims_of(synthesize(state_snapshot), "THEME_REVIEWED_STATE")
    forged = A1.NarrativeClaim(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="STATE",
                               predicate="THEME_REVIEWED_STATE",
                               refs=(A1.ThemeObservationRef(root_id=Q, observation_id=state.refs[0].observation_id,
                                                            governance_position="ACCEPTED",
                                                            mechanism_certainty="HYPOTHESIZED_MECHANISM"),))
    object.__setattr__(forged, "claim_id", state.claim_id)
    fails("CLAIM_CONFLICT", E._converge, [("R01_REVIEWED_STATE", state), ("R01_REVIEWED_STATE", forged)])
    trusted = revalidate(state_snapshot)
    relabelled = A1.EvidenceAttachmentRef(**{**{f.name: getattr(attached(synthesize(state_snapshot), FACT_P)[0], f.name)
                                                 for f in dataclasses.fields(A1.EvidenceAttachmentRef)},
                                              "role": "CONTEXT"})
    extra = A1.NarrativeClaim(epistemic_class="REVIEWED_INTERPRETATION", claim_kind="EVIDENCE",
                              predicate="EVIDENCE_ATTACHED", refs=(relabelled,))
    fails("CLAIM_CONFLICT", synthesis_from_claims, trusted, synthesize(state_snapshot).claims + (extra,))


def test_ao_canonical_ordering_ignores_generation_order(state_snapshot) -> None:
    claims = synthesize(state_snapshot).claims
    trusted = revalidate(state_snapshot)
    assert synthesis_from_claims(trusted, tuple(reversed(claims))).to_canonical_json() == \
        synthesis_from_claims(trusted, claims).to_canonical_json()


def test_ap_the_synthesis_id_is_the_a1_id(set_snapshot) -> None:
    synthesis = synthesize(set_snapshot)
    rebuilt = A1.NarrativeSynthesis(kind=synthesis.kind, subject_root_ids=synthesis.subject_root_ids,
                                    cutoff=synthesis.cutoff, knowledge_pins=synthesis.knowledge_pins,
                                    input_digest=synthesis.input_digest, claims=synthesis.claims)
    assert rebuilt.synthesis_id == synthesis.synthesis_id


def test_aq_the_ruleset_version_is_part_of_the_identity(state_snapshot, monkeypatch) -> None:
    base = synthesize(state_snapshot)
    monkeypatch.setattr(E, "RULESET_VERSION", "0.2.0")
    bumped = synthesize(state_snapshot)
    assert bumped.claims == base.claims and bumped.synthesis_id != base.synthesis_id
    assert dict(bumped.knowledge_pins)["narrative_synthesis_rules"] == "0.2.0"


# ================================================================ AR〜AW 改ざんと version

def tampered(snapshot, mutate):
    clone = copy.deepcopy(snapshot)                                                        # fixture を汚さない深い複製
    assert clone.to_canonical_json() == snapshot.to_canonical_json()
    mutate(clone)
    return clone


def test_ar_a_tampered_snapshot_id_is_rejected(state_snapshot) -> None:
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize,
          tampered(state_snapshot, lambda s: object.__setattr__(s, "snapshot_id", "narinp_" + "0" * 24)))


def test_as_a_tampered_role_is_rejected(state_snapshot) -> None:
    def flip(s):
        target = [a for a in s.themes[0].attachments if a.ref_id == NEWS_P][0]
        object.__setattr__(target, "role", A1.EvidenceRole.SUPPORTS)
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize, tampered(state_snapshot, flip))
    def raw(s):
        object.__setattr__(s.themes[0].attachments[0], "role", "SUPPORTS")               # enum の代わりの生の文字列
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize, tampered(state_snapshot, raw))


def test_at_a_tampered_source_capability_is_rejected(state_snapshot) -> None:
    def promote(s):
        source = [x for x in s.evidence_sources if x.item.ref_id == DOC_P][0]
        object.__setattr__(source, "capability", SourceCapability.OBSERVATIONAL_RECORD)
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize, tampered(state_snapshot, promote))


def test_au_a_tampered_relation_is_rejected(set_snapshot) -> None:
    def objectify(s):
        source_asserted = [r for r in s.relations if r.assertion_class.value == "SOURCE_ASSERTED"][0]
        object.__setattr__(source_asserted, "assertion_class", A1.AssertionClass.HUMAN_ASSERTED)
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize, tampered(set_snapshot, objectify))
    def reverse(s):
        object.__setattr__(s.relations[0], "source_root_id", s.relations[0].target_root_id)
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize, tampered(set_snapshot, reverse))
    def inject(s):
        object.__setattr__(s.themes[0], "confidence", "0.9")                              # 後から足した属性
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize, tampered(set_snapshot, inject))


def test_av_invalid_kind_or_cardinality_is_rejected(set_snapshot, state_snapshot) -> None:
    fails("UNSUPPORTED_KIND", synthesize, tampered(state_snapshot, lambda s: object.__setattr__(s, "kind", "MARKET_STATE")))
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize,
          tampered(state_snapshot, lambda s: object.__setattr__(s, "kind", A1.NarrativeKind.THEME_SET)))
    fails("SNAPSHOT_INTEGRITY_FAILURE", synthesize,
          tampered(set_snapshot, lambda s: object.__setattr__(s, "root_ids", s.root_ids[:1])))
    for bad in (None, {}, "narinp_" + "0" * 24, synthesize(state_snapshot)):
        fails("INVALID_SNAPSHOT", synthesize, bad)


def test_aw_unsupported_snapshot_versions_are_rejected(state_snapshot, monkeypatch) -> None:
    newer = NarrativeInputSnapshot(kind=state_snapshot.kind, root_ids=state_snapshot.root_ids,
                                   cutoff=state_snapshot.cutoff, comparison_cutoff=None, themes=state_snapshot.themes,
                                   evidence_sources=state_snapshot.evidence_sources, relations=None,
                                   relation_provenance_digest=None,
                                   reader_versions=(("theme_resolver", "0.2.0"), ("theme_lifecycle_model", "0.1.0"),
                                                    ("theme_lifecycle_policy", "0.1.0")),
                                   stale_after_days=state_snapshot.stale_after_days)
    fails("UNSUPPORTED_SNAPSHOT_VERSION", synthesize, newer)
    monkeypatch.setattr(input_model, "INPUT_SCHEMA_VERSION", "narrative_input_snapshot:0.2.0")
    fails("UNSUPPORTED_SNAPSHOT_VERSION", synthesize, state_snapshot)


# ================================================================ AX〜AZ 空・埋め草・文章

def test_ax_zero_justified_claims_fail_closed(state_snapshot) -> None:
    fails("NO_JUSTIFIED_CLAIMS", synthesis_from_claims, revalidate(state_snapshot), ())
    with pytest.raises(A1.NarrativeModelError):                                            # A1 は claim 0 を許さない
        A1.NarrativeSynthesis(kind="THEME_STATE", subject_root_ids=(P,), cutoff=CUT,
                              knowledge_pins=(("narrative_synthesis_rules", "0.1.0"),),
                              input_digest=state_snapshot.snapshot_id, claims=())


@pytest.mark.parametrize("key,kind,roots,comparison", [
    ("state", "THEME_STATE", (P,), None), ("bare", "THEME_STATE", (BARE,), None), ("ctx", "THEME_STATE", (CTX,), None),
    ("q", "THEME_STATE", (Q,), EARLY), ("set", "THEME_SET", (P, Q, R), EARLY), ("pair", "THEME_SET", (P, BARE), None),
    ("ctxset", "THEME_SET", (CTX, Q, R), None)])
def test_ay_every_claim_is_justified_and_every_justified_claim_is_present(world, key, kind, roots, comparison) -> None:
    snapshot = snap(world[0], kind, roots, comparison=comparison)
    synthesis = synthesize(snapshot)
    assert {signature(c) for c in synthesis.claims} == expected_signatures(snapshot)       # 埋め草も欠落も無い
    assert len(synthesis.claims) == len(expected_signatures(snapshot))


TOKEN = re.compile(r"^(?:[A-Z][A-Z0-9_]*|[a-z][a-z0-9_]*(?::[0-9.]+)?|[a-z]+_[0-9A-Za-z]+|[0-9]+\.[0-9]+\.[0-9]+|"
                   r"[a-z0-9][a-z0-9_.:-]*|[A-Za-z0-9_]+#[a-z0-9_.:-]*|\d{4}-\d{2}-\d{2}T[0-9:.+]+)$")


def test_az_no_prose_is_invented(set_snapshot) -> None:
    keys, values = set(), []
    walk(json.loads(synthesize(set_snapshot).to_canonical_json()), keys, values)
    for value in values:
        assert value is None or value == "" or (isinstance(value, str) and TOKEN.fullmatch(value)), value


# ================================================================ BA〜BJ 純粋な実行

def test_ba_bb_bg_no_store_read_file_io_or_network_during_synthesis(set_snapshot, monkeypatch, tmp_path) -> None:
    expected = synthesize(set_snapshot).to_canonical_json()

    def forbidden(*args, **kwargs):
        raise AssertionError("synthesis touched a file or the network")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert synthesize(set_snapshot).to_canonical_json() == expected


def test_bb_bi_repeated_synthesis_changes_no_file_and_no_authority(world, set_snapshot) -> None:
    def inventory(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    data_before = inventory(world[0])
    repo_before = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    snapshot_bytes = set_snapshot.to_canonical_json()
    for _ in range(5):
        synthesize(set_snapshot)
    assert inventory(world[0]) == data_before
    assert subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True,
                          text=True).stdout == repo_before
    assert set_snapshot.to_canonical_json() == snapshot_bytes                              # 入力も変えない


def test_bh_no_clock_or_randomness_changes_the_output(set_snapshot, monkeypatch) -> None:
    import random
    import secrets
    import time
    import uuid
    expected = synthesize(set_snapshot).to_canonical_json()

    def forbidden(*args, **kwargs):
        raise AssertionError("synthesis used a clock or randomness")
    for module, name in ((time, "time"), (time, "time_ns"), (time, "monotonic"), (random, "random"),
                         (random, "shuffle"), (secrets, "token_hex"), (uuid, "uuid4")):
        monkeypatch.setattr(module, name, forbidden)
    assert synthesize(set_snapshot).to_canonical_json() == expected


def test_bj_no_self_learning_or_history_input(world, state_snapshot, set_snapshot) -> None:
    module_state = {name: repr(value) for name, value in vars(E).items() if not name.startswith("__")}
    first = (synthesize(state_snapshot).to_canonical_json(), synthesize(set_snapshot).to_canonical_json())
    second = (synthesize(state_snapshot).to_canonical_json(), synthesize(set_snapshot).to_canonical_json())
    reverse = tuple(reversed((synthesize(set_snapshot).to_canonical_json(),
                              synthesize(state_snapshot).to_canonical_json())))
    assert first == second == reverse
    assert {name: repr(value) for name, value in vars(E).items() if not name.startswith("__")} == module_state
    assert all(isinstance(rule, E.SynthesisRule) for rule in E.RULES) and isinstance(E.RULES, tuple)


def test_the_rule_table_is_bounded_and_consistent_with_a1() -> None:
    assert E.RULE_IDS == tuple(f"R{n:02d}_" + rule.rule_id.split("_", 1)[1] for n, rule in enumerate(E.RULES, 1))
    allowed = {(k.value, c.value, p.value) for k, c, p in A1.ALLOWED_TRIPLES}
    for rule in E.RULES:
        for predicate in rule.predicate.split(" | "):
            assert (rule.epistemic_class, rule.claim_kind, predicate) in allowed, rule.rule_id
        assert rule.suppression and rule.required_refs and rule.input_shape
    assert E.RULESET_NAME == "narrative_synthesis_rules" and E.RULESET_VERSION == "0.1.0"
    assert "which explanation wins" in E.SYNTHESIS_ENGINE_DOES_NOT_ANSWER
