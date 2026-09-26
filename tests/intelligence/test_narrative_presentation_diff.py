"""P7-A4a — 提示の構造と差分（`NarrativeSynthesis` → `NarrativePresentation`、2 つの synthesis → `NarrativeDiff`）の
test matrix A〜BH。

git に依存する境界（BI〜BM: A1 / A2 / A3 / Phase 6 の byte 凍結・未登録 runtime の検出・runtime の import closure・
module 状態なし）は `test_narrative_intelligence_boundary.py` にある。synthesis は A2 の本物の組み立て（tmp の合成
data_root）と A3 の engine から作る。差分の片方を A1 の constructor で作る場合も、A1 の検査をすべて通したものだけを使う。

契約: `docs/databank/PHASE7_NARRATIVE_PRESENTATION_DIFF_CONTRACT.md`。
"""
from __future__ import annotations

import builtins
import copy
import dataclasses
import inspect
import os
import re
import socket
import subprocess
import sys
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.core.ids import content_id
from src.intelligence.narrative_intelligence import narrative_diff as D
from src.intelligence.narrative_intelligence import presentation_model as PM
from src.intelligence.narrative_intelligence import presentation_planner as PL
from src.intelligence.narrative_intelligence import synthesis_engine as E
from src.intelligence.narrative_intelligence import synthesis_model as A1
from src.intelligence.narrative_intelligence.narrative_diff import diff_syntheses
from src.intelligence.narrative_intelligence.presentation_model import (DiffCategory, NarrativeDiff, NarrativeDiffItem,
                                                                        NarrativePresentation,
                                                                        NarrativePresentationError, PresentationItem,
                                                                        PresentationSection, SectionKind, Visibility)
from src.intelligence.narrative_intelligence.presentation_planner import (plan_presentation, revalidate_synthesis,
                                                                          validate_display_selection)
from src.intelligence.narrative_intelligence.synthesis_engine import synthesize
from tests.intelligence.test_narrative_pit_assembler import (CUT, DOC_P, EARLY, FACT_P, INV_P, NEWS_P, P, Q, R,
                                                             add_future, day, snap)
from tests.intelligence.test_narrative_synthesis_engine import BARE, CTX, DOC_CTX, build_engine_world, permuted
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "narrative_intelligence"
CONTRACT = REPO_ROOT / "docs" / "databank" / "PHASE7_NARRATIVE_PRESENTATION_DIFF_CONTRACT.md"
A4A_MODULES = (PM, PL, D)
DIGEST = "narinp_" + "0" * 24
TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")
ID_RE = re.compile(r"^(theme|narclm|narsyn|narprs|nardif)_[0-9A-Za-z]+$")
ITEM_KEYS = {"claim_id", "theme_root_ids", "epistemic_class", "claim_kind", "predicate", "uncertainty_code",
             "evidence_role", "assertion_class", "rule_id", "section", "visibility"}
S = SectionKind


# ================================================================ world と helper

def syn(root, kind="THEME_STATE", roots=(P,), cutoff=CUT, comparison=None):
    return synthesize(snap(root, kind, roots, cutoff=cutoff, comparison=comparison))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("narrative_presentation") / "data"
    return root, build_engine_world(root)


@pytest.fixture(scope="module")
def state(world):
    return syn(world[0])


@pytest.fixture(scope="module")
def bare(world):
    return syn(world[0], roots=(BARE,))


@pytest.fixture(scope="module")
def ctx(world):
    return syn(world[0], roots=(CTX,))


@pytest.fixture(scope="module")
def theme_set(world):
    return syn(world[0], "THEME_SET", (P, Q, R), comparison=EARLY)


@pytest.fixture(scope="module")
def early_set(world):
    return syn(world[0], "THEME_SET", (P, Q, R), cutoff=day(3))


@pytest.fixture(scope="module")
def late_set(world):
    return syn(world[0], "THEME_SET", (P, Q, R), cutoff=day(10))


@pytest.fixture(scope="module")
def future_pair(tmp_path_factory):
    """cutoff の後に R→Q の relation が記録される world の (day 10, day 15)。"""
    root = tmp_path_factory.mktemp("narrative_presentation_future") / "data"
    add_future(root, build_engine_world(root))
    return syn(root, "THEME_SET", (Q, R), cutoff=day(10)), syn(root, "THEME_SET", (Q, R), cutoff=day(15))


def variant(s, *, cutoff, drop=lambda claim: False, extra=(), pins=None, subjects=None, kind=None):
    """A1 の constructor で作る別の synthesis（A1 の検査をすべて通るものだけ）。"""
    return A1.NarrativeSynthesis(kind=kind or s.kind, subject_root_ids=subjects or s.subject_root_ids, cutoff=cutoff,
                                 knowledge_pins=pins or s.knowledge_pins, input_digest=DIGEST,
                                 claims=tuple(c for c in s.claims if not drop(c)) + tuple(extra))


def fails(code, fn, *args, **kwargs):
    with pytest.raises(NarrativePresentationError) as info:
        fn(*args, **kwargs)
    assert info.value.code == code, (info.value.code, info.value.detail)
    return info.value


def attachment_of(claim):
    return [r for r in claim.refs if isinstance(r, A1.EvidenceAttachmentRef)][0]


def is_attached(claim, role, ref_id=None):
    return (claim.predicate is A1.Predicate.EVIDENCE_ATTACHED and attachment_of(claim).role.value == role
            and (ref_id is None or attachment_of(claim).ref_id == ref_id))


def section(presentation, kind):
    found = [s for s in presentation.sections if s.section is kind]
    return found[0].items if found else ()


def walk(node, keys=None, values=None):
    keys = set() if keys is None else keys
    values = [] if values is None else values
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            walk(value, keys, values)
    elif isinstance(node, list):
        for value in node:
            walk(value, keys, values)
    else:
        values.append(node)
    return keys, values


def vocabulary(payload):
    """id 以外の値（閉じた語彙・version の token だけのはず）。"""
    return {v for v in walk(payload)[1] if isinstance(v, str) and not ID_RE.fullmatch(v)}


def expected_placement(claim):
    """規則表を planner と独立に書き下した (section, 義務)。"""
    predicate = claim.predicate.value
    if predicate == "EVIDENCE_ATTACHED":
        return {"SUPPORTS": ("EVIDENCE", "ELIGIBLE"), "CONTEXT": ("EVIDENCE", "ELIGIBLE"),
                "CONTRADICTS": ("CONTRADICTION", "REQUIRED"),
                "INVALIDATES": ("INVALIDATION", "REQUIRED")}[attachment_of(claim).role.value]
    return {"THEME_REVIEWED_STATE": ("STATE", "ELIGIBLE"), "RECORDS_MECHANISM_COMPONENT": ("MECHANISM", "ELIGIBLE"),
            "EVIDENCE_ITEM_OBSERVED": ("EVIDENCE", "ELIGIBLE"), "CHANGED_BETWEEN_CUTOFFS": ("CHANGE", "ELIGIBLE"),
            "HUMAN_ASSERTED_RELATION": ("RELATION", "ELIGIBLE"), "SOURCE_ASSERTED_RELATION": ("RELATION", "ELIGIBLE"),
            "RECORDS_INVALIDATION_CONDITION": ("INVALIDATION", "REQUIRED"),
            "INVALIDATING_EVIDENCE_ATTACHED": ("INVALIDATION", "REQUIRED"), "IS_UNCERTAIN": ("UNCERTAINTY", "REQUIRED"),
            "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE": ("ALTERNATIVES", "REQUIRED")}[predicate]


def item_kwargs(item, **changes):
    base = {name: getattr(item, name) for name in ("claim_id", "theme_root_ids", "epistemic_class", "claim_kind",
                                                   "predicate", "uncertainty_code", "evidence_role",
                                                   "assertion_class")}
    return dict(base, **changes)


def tampered(s, mutate):
    clone = copy.deepcopy(s)
    mutate(clone)
    return clone


# ================================================================ A〜D 提示の基本と決定性

def test_a_theme_state_presentation(state) -> None:
    p = plan_presentation(state)
    assert p.kind is A1.NarrativeKind.THEME_STATE and p.subject_root_ids == (P,)
    assert p.source_synthesis_id == state.synthesis_id
    assert [s.section for s in p.sections] == [S.STATE, S.MECHANISM, S.EVIDENCE, S.CONTRADICTION, S.INVALIDATION,
                                              S.UNCERTAINTY]
    assert all(item.theme_root_ids in ((P,), ()) for item in p.items())                  # 明示の Theme が中心
    assert sorted(p.claim_ids()) == sorted(c.claim_id for c in state.claims)


def test_a_theme_state_stays_centered_and_never_gains_a_related_theme(state, theme_set) -> None:
    relation = next(c for c in theme_set.claims if c.predicate is A1.Predicate.HUMAN_ASSERTED_RELATION)
    widened = variant(state, cutoff=state.cutoff, extra=(relation,))                      # A1 としては有効
    assert P in relation.roots() and set(relation.roots()) - {P}
    fails("SYNTHESIS_INTEGRITY_FAILURE", plan_presentation, widened)                       # 関係する Theme を足さない
    p = plan_presentation(state)
    fails("PRESENTATION_CONFLICT", NarrativePresentation, kind=p.kind, subject_root_ids=(Q,),
          source_synthesis_id=p.source_synthesis_id, sections=p.sections)


def test_b_theme_set_presentation(theme_set) -> None:
    p = plan_presentation(theme_set)
    assert p.kind is A1.NarrativeKind.THEME_SET and p.subject_root_ids == tuple(sorted((P, Q, R)))
    assert [s.section for s in p.sections] == list(PM.SECTION_ORDER)                     # この world では 9 つすべて
    assert [item.theme_root_ids for item in section(p, S.STATE)] == [(root,) for root in sorted((P, Q, R))]
    assert sorted(p.claim_ids()) == sorted(c.claim_id for c in theme_set.claims)


def test_c_replay_is_byte_identical_in_process_and_across_processes(theme_set, tmp_path) -> None:
    first = plan_presentation(theme_set).to_canonical_json()
    assert plan_presentation(theme_set).to_canonical_json() == first
    assert plan_presentation(A1.NarrativeSynthesis.from_json(theme_set.to_canonical_json())).to_canonical_json() == first
    source = tmp_path / "synthesis.json"
    source.write_text(theme_set.to_canonical_json(), encoding="utf-8")
    code = ("import sys\nfrom src.intelligence.narrative_intelligence.synthesis_model import NarrativeSynthesis\n"
            "from src.intelligence.narrative_intelligence.presentation_planner import plan_presentation\n"
            "s = NarrativeSynthesis.from_json(open(sys.argv[1], encoding='utf-8').read())\n"
            "sys.stdout.write(plan_presentation(s).to_canonical_json())\n")
    for seed in ("0", "4242"):
        out = subprocess.run([sys.executable, "-c", code, str(source)], cwd=REPO_ROOT, capture_output=True, text=True,
                             check=True, env={"PYTHONPATH": str(REPO_ROOT), "PATH": "", "PYTHONHASHSEED": seed})
        assert out.stdout == first


def test_d_nonsemantic_input_permutations_do_not_change_the_presentation(world, theme_set) -> None:
    expected = plan_presentation(theme_set).to_canonical_json()
    reordered = A1.NarrativeSynthesis(kind=theme_set.kind, subject_root_ids=tuple(reversed(theme_set.subject_root_ids)),
                                      cutoff=theme_set.cutoff.astimezone(timezone(timedelta(hours=9))),
                                      knowledge_pins=tuple(reversed(theme_set.knowledge_pins)),
                                      input_digest=theme_set.input_digest, claims=tuple(reversed(theme_set.claims)))
    assert reordered.synthesis_id == theme_set.synthesis_id
    assert plan_presentation(reordered).to_canonical_json() == expected
    again = synthesize(permuted(snap(world[0], "THEME_SET", (P, Q, R), comparison=EARLY)))
    assert plan_presentation(again).to_canonical_json() == expected


# ================================================================ E〜H 追跡・対応・新しい意味なし

def test_e_every_item_traces_to_exactly_one_claim_with_the_same_structure(theme_set) -> None:
    claims = {c.claim_id: c for c in theme_set.claims}
    for item in plan_presentation(theme_set).items():
        claim = claims[item.claim_id]
        assert (item.epistemic_class, item.claim_kind, item.predicate, item.uncertainty_code, item.theme_root_ids) == (
            claim.epistemic_class, claim.claim_kind, claim.predicate, claim.uncertainty_code, claim.roots())
        role = attachment_of(claim).role if claim.predicate is A1.Predicate.EVIDENCE_ATTACHED else None
        relation = [r.assertion_class for r in claim.refs if isinstance(r, A1.RelationAssertionRef)]
        assert item.evidence_role is role
        assert item.assertion_class is (relation[0] if claim.predicate in A1.RELATION_PREDICATES else None)


def test_f_no_orphan_item_exists_or_can_be_passed_off(theme_set) -> None:
    p = plan_presentation(theme_set)
    assert len(p.claim_ids()) == len(set(p.claim_ids())) == len(theme_set.claims)
    base = section(p, S.STATE)[0]
    for bad in ("", "summary", "narclm_" + "x" * 24, None, "narsyn_" + "0" * 24):
        fails("PRESENTATION_CONFLICT", PresentationItem, **item_kwargs(base, claim_id=bad))
    with pytest.raises(TypeError):
        PresentationItem(**{k: v for k, v in item_kwargs(base).items() if k != "claim_id"})
    forged_item = PresentationItem(**item_kwargs(base, claim_id="narclm_" + "f" * 24))
    sections = tuple(PresentationSection(section=s.section, items=tuple(sorted(
        s.items + ((forged_item,) if s.section is S.STATE else ()), key=PM.item_order_key))) for s in p.sections)
    forged = NarrativePresentation(kind=p.kind, subject_root_ids=p.subject_root_ids,
                                   source_synthesis_id=p.source_synthesis_id, sections=sections)
    assert forged.presentation_id != p.presentation_id                                   # 作り直すと一致しない
    fails("PRESENTATION_CONFLICT", PresentationSection, section=S.STATE, items=section(p, S.STATE) * 2)


@pytest.mark.parametrize("name", ["state", "bare", "ctx", "theme_set", "early_set", "late_set"])
def test_g_every_claim_is_accounted_for_exactly_once_in_its_section(request, name) -> None:
    s = request.getfixturevalue(name)
    p = plan_presentation(s)
    assert sorted(p.claim_ids()) == sorted(c.claim_id for c in s.claims)
    placed = {item.claim_id: (item.section.value, item.visibility.value) for item in p.items()}
    assert placed == {c.claim_id: expected_placement(c) for c in s.claims}


def test_h_no_invented_claim_semantics(theme_set) -> None:
    payload = plan_presentation(theme_set).to_dict()
    assert set(payload) == {"schema_version", "ruleset", "source_synthesis_id", "kind", "subject_root_ids", "sections",
                            "presentation_id"}
    for group in payload["sections"]:
        assert set(group) == {"section", "items"}
        assert all(set(item) == ITEM_KEYS for item in group["items"])
    enums = (A1.EpistemicClass, A1.ClaimKind, A1.Predicate, A1.UncertaintyCode, A1.EvidenceRole, A1.AssertionClass,
             A1.NarrativeKind, SectionKind, Visibility)
    allowed = {e.value for enum in enums for e in enum} | set(PM.PRESENTATION_RULE_IDS) | {
        PM.PRESENTATION_SCHEMA_VERSION, PM.PRESENTATION_RULESET_NAME, PM.PRESENTATION_RULESET_VERSION}
    assert vocabulary(payload) <= allowed
    ids = {v for v in walk(payload)[1] if isinstance(v, str) and ID_RE.fullmatch(v)}
    assert ids <= ({c.claim_id for c in theme_set.claims} | set(theme_set.subject_root_ids)
                   | {theme_set.synthesis_id, plan_presentation(theme_set).presentation_id})
    assert all(v is None or (isinstance(v, str) and TOKEN.fullmatch(v)) for v in walk(payload)[1])


# ================================================================ I〜N 見せ方の義務

def test_i_supports_are_eligible_evidence(state) -> None:
    p = plan_presentation(state)
    supports = [i for i in p.items() if i.evidence_role is A1.EvidenceRole.SUPPORTS]
    assert len(supports) == len([c for c in state.claims if is_attached(c, "SUPPORTS")]) == 3
    assert {(i.section, i.visibility) for i in supports} == {(S.EVIDENCE, Visibility.ELIGIBLE)}


def test_j_contradictions_are_required_and_separately_visible(state) -> None:
    p = plan_presentation(state)
    contradiction = section(p, S.CONTRADICTION)
    assert [i.claim_id for i in contradiction] == [c.claim_id for c in state.claims if is_attached(c, "CONTRADICTS",
                                                                                                    NEWS_P)]
    assert {(i.evidence_role, i.visibility) for i in contradiction} == {(A1.EvidenceRole.CONTRADICTS,
                                                                         Visibility.REQUIRED)}
    assert not [i for i in section(p, S.EVIDENCE) if i.evidence_role is A1.EvidenceRole.CONTRADICTS]


def test_k_invalidation_is_required_and_explicit(state) -> None:
    p = plan_presentation(state)
    invalidation = section(p, S.INVALIDATION)
    assert sorted(i.predicate.value for i in invalidation) == ["EVIDENCE_ATTACHED", "INVALIDATING_EVIDENCE_ATTACHED",
                                                              "RECORDS_INVALIDATION_CONDITION"]
    assert {i.visibility for i in invalidation} == {Visibility.REQUIRED}
    assert [c for c in state.claims if is_attached(c, "INVALIDATES", INV_P)]
    state_item = section(p, S.STATE)[0]
    fails("PRESENTATION_CONFLICT", validate_display_selection, p, {state_item.claim_id})   # 無効化を隠せない


def test_l_every_uncertainty_code_stays_visible_and_is_never_collapsed(state, bare, ctx, theme_set) -> None:
    seen = set()
    for s in (state, bare, ctx, theme_set):
        items = section(plan_presentation(s), S.UNCERTAINTY)
        assert sorted((i.uncertainty_code.value, i.claim_kind.value) for i in items) == sorted(
            (c.uncertainty_code.value, c.claim_kind.value) for c in s.claims if c.uncertainty_code)
        assert {i.visibility for i in items} == {Visibility.REQUIRED}
        seen |= {i.uncertainty_code for i in items}
    assert seen >= {A1.UncertaintyCode.CONTESTED_EVIDENCE, A1.UncertaintyCode.MECHANISM_HYPOTHESIZED,
                    A1.UncertaintyCode.SINGLE_SOURCE_EVIDENCE, A1.UncertaintyCode.NO_SUPPORTING_EVIDENCE}
    for code in A1.UncertaintyCode:                                                        # STALE を含むすべての code
        item = PresentationItem(claim_id="narclm_" + "a" * 24, theme_root_ids=(P,),
                                epistemic_class="UNCERTAINTY", claim_kind=A1.UNCERTAINTY_CLAIM_KIND[code].value,
                                predicate="IS_UNCERTAIN", uncertainty_code=code.value)
        assert (item.section, item.visibility, item.uncertainty_code) == (S.UNCERTAINTY, Visibility.REQUIRED, code)


def test_m_the_source_asserted_limitation_is_preserved(theme_set) -> None:
    relations = section(plan_presentation(theme_set), S.RELATION)
    by_predicate = {i.predicate: i for i in relations}
    source = by_predicate[A1.Predicate.SOURCE_ASSERTED_RELATION]
    human = by_predicate[A1.Predicate.HUMAN_ASSERTED_RELATION]
    assert source.assertion_class is A1.AssertionClass.SOURCE_ASSERTED
    assert human.assertion_class is A1.AssertionClass.HUMAN_ASSERTED
    fails("PRESENTATION_CONFLICT", PresentationItem, **item_kwargs(source, assertion_class="HUMAN_ASSERTED"))
    fails("PRESENTATION_CONFLICT", PresentationItem, **item_kwargs(source, assertion_class=None))
    assert A1.SOURCE_ASSERTED_MEANING == "a source asserted this relation; the narrative does not assert it"


def test_n_context_stays_context_and_never_becomes_support(state, ctx) -> None:
    for s, ref_id in ((state, DOC_P), (ctx, DOC_CTX)):
        p = plan_presentation(s)
        [claim] = [c for c in s.claims if is_attached(c, "CONTEXT", ref_id)]
        item = {i.claim_id: i for i in p.items()}[claim.claim_id]
        assert (item.section, item.visibility, item.evidence_role) == (S.EVIDENCE, Visibility.ELIGIBLE,
                                                                       A1.EvidenceRole.CONTEXT)
    p = plan_presentation(ctx)
    assert not [i for i in p.items() if i.evidence_role is A1.EvidenceRole.SUPPORTS]
    [no_support] = [i for i in section(p, S.UNCERTAINTY) if i.uncertainty_code.value == "NO_SUPPORTING_EVIDENCE"]
    [context] = [i for i in section(p, S.EVIDENCE) if i.evidence_role is A1.EvidenceRole.CONTEXT]
    fails("PRESENTATION_CONFLICT", validate_display_selection, p, {context.claim_id})    # 支持が無いことを隠せない
    required = {i.claim_id for i in p.items() if i.visibility is Visibility.REQUIRED}
    assert no_support.claim_id in required
    validate_display_selection(p, required | {context.claim_id})


# ================================================================ O〜R 差し引き・勝者・確信度なし

def test_o_support_and_contradiction_are_both_retained_and_cannot_be_split(state) -> None:
    p = plan_presentation(state)
    supports = {i.claim_id for i in section(p, S.EVIDENCE) if i.evidence_role is A1.EvidenceRole.SUPPORTS}
    contradiction = {i.claim_id for i in section(p, S.CONTRADICTION)}
    contested = [i for i in section(p, S.UNCERTAINTY) if i.uncertainty_code.value == "CONTESTED_EVIDENCE"]
    assert supports and contradiction and len(contested) == 1
    fails("PRESENTATION_CONFLICT", validate_display_selection, p, supports)              # 支持だけは見せられない
    fails("PRESENTATION_CONFLICT", validate_display_selection, p, supports | contradiction)
    required = {i.claim_id for i in p.items() if i.visibility is Visibility.REQUIRED and P in i.theme_root_ids}
    validate_display_selection(p, supports | required)
    validate_display_selection(p, p.claim_ids())
    validate_display_selection(p, ())
    validate_display_selection(p, {i.claim_id for i in p.items() if not i.theme_root_ids})   # 観測の記録だけ
    fails("PRESENTATION_CONFLICT", validate_display_selection, p, {"narclm_" + "0" * 24})
    fails("PRESENTATION_CONFLICT", validate_display_selection, p.to_dict(), ())


FORBIDDEN_KEYS = {"score", "net", "balance", "confidence", "rank", "ranking", "weight", "priority", "importance",
                  "strength", "winner", "dominant", "primary", "top", "beneficiary", "preferred", "probability",
                  "summary", "text", "prose", "headline", "sentiment", "direction", "improved", "better", "bullish",
                  "bearish", "trend", "momentum", "delta"}


def test_p_no_net_evidence_score_or_balance(theme_set, early_set, late_set) -> None:
    for payload in (plan_presentation(theme_set).to_dict(), diff_syntheses(previous=early_set,
                                                                           current=late_set).to_dict()):
        keys, values = walk(payload)
        assert not keys & FORBIDDEN_KEYS
        assert not [v for v in values if isinstance(v, (int, float))]                   # 数値は 1 つも無い
    words = ("MOSTLY", "NET", "FAVORS", "STRONGER", "WEAKER", "BALANCE", "SUPPORTIVE")
    assert not [v for v in vocabulary(plan_presentation(theme_set).to_dict()) if any(w in v for w in words)]


def test_q_no_winner_dominant_or_top_theme(theme_set) -> None:
    words = ("winner", "dominant", "primary", "top", "best", "preferred", "rank", "score", "confidence", "weight",
             "priority", "importance", "strength")
    for model in (PresentationItem, PresentationSection, NarrativePresentation, NarrativeDiffItem, NarrativeDiff):
        for f in dataclasses.fields(model):
            assert not any(word in f.name for word in words), (model.__name__, f.name)
    states = section(plan_presentation(theme_set), S.STATE)
    assert len(states) == 3 and {(i.section, i.visibility) for i in states} == {(S.STATE, Visibility.ELIGIBLE)}


def test_r_no_confidence_is_calculated_from_counts(state) -> None:
    [support] = [c for c in state.claims if is_attached(c, "SUPPORTS", FACT_P)]
    fewer = variant(state, cutoff=day(9), drop=lambda c: c.claim_id == support.claim_id)
    more = {i.claim_id: i for i in plan_presentation(state).items()}
    less = {i.claim_id: i for i in plan_presentation(fewer).items()}
    assert set(more) - set(less) == {support.claim_id}
    assert all(less[claim_id] == more[claim_id] for claim_id in less)                    # 件数で他の item は変わらない
    assert [v.value for v in Visibility] == ["REQUIRED", "ELIGIBLE"]


# ================================================================ S〜X 分類・順序・順位なし

def test_s_the_section_taxonomy_is_closed_minimal_and_total() -> None:
    assert [s.value for s in SectionKind] == ["STATE", "MECHANISM", "EVIDENCE", "CONTRADICTION", "INVALIDATION",
                                              "UNCERTAINTY", "CHANGE", "RELATION", "ALTERNATIVES"]
    assert not {s.value for s in SectionKind} & {"RECOMMENDATION", "BUY", "SELL", "WINNER", "TOP_THEME",
                                                 "BENEFICIARY_RANKING", "SUMMARY", "OUTLOOK", "PREDICTION", "SIGNAL"}
    shapes = {(p.value, None) for p in A1.Predicate if p is not A1.Predicate.EVIDENCE_ATTACHED} | {
        ("EVIDENCE_ATTACHED", role.value) for role in A1.EvidenceRole}
    rules = PM.PRESENTATION_RULES
    assert {(r.predicate, r.evidence_role) for r in rules} == shapes and len(rules) == len(shapes)   # 全域・重複なし
    assert {r.section for r in rules} == {s.value for s in SectionKind}                  # 使わない section は無い
    assert all(r.visibility in ("REQUIRED", "ELIGIBLE") and r.reason for r in rules)
    assert PM.PRESENTATION_RULE_IDS == tuple(f"P{n:02d}_" + r.rule_id.split("_", 1)[1] for n, r in enumerate(rules, 1))
    fails("PRESENTATION_CONFLICT", PresentationSection, section="TOP_THEME", items=())


def test_t_sections_follow_the_fixed_presentational_order(state, theme_set) -> None:
    for s in (state, theme_set):
        order = [PM.SECTION_ORDER.index(group.section) for group in plan_presentation(s).sections]
        assert order == sorted(order)
    p = plan_presentation(theme_set)
    fails("PRESENTATION_CONFLICT", NarrativePresentation, kind=p.kind, subject_root_ids=p.subject_root_ids,
          source_synthesis_id=p.source_synthesis_id, sections=tuple(reversed(p.sections)))


def test_u_the_order_is_documented_as_presentational_not_importance() -> None:
    assert PM.SECTION_ORDER_MEANING == "presentational reading order only; not importance, priority or ranking"
    text = CONTRACT.read_text(encoding="utf-8")
    assert PM.SECTION_ORDER_MEANING in text and "重要度の順位ではない" in text


def test_v_items_follow_canonical_identity_order(theme_set) -> None:
    p = plan_presentation(theme_set)
    for group in p.sections:
        keys = [(i.theme_root_ids, i.claim_id) for i in group.items]
        assert keys == sorted(keys)
    busy = next(group for group in p.sections if len(group.items) > 1)
    fails("PRESENTATION_CONFLICT", PresentationSection, section=busy.section, items=tuple(reversed(busy.items)))


def test_w_themes_are_never_ranked(world, theme_set) -> None:
    p = plan_presentation(theme_set)
    per_theme = {root: sum(root in i.theme_root_ids for i in p.items()) for root in (P, Q, R)}
    assert len(set(per_theme.values())) > 1                                              # 量で並べればずれる
    assert [i.theme_root_ids[0] for i in section(p, S.STATE)] == sorted((P, Q, R))         # それでも root id の順
    fails("PRESENTATION_CONFLICT", NarrativePresentation, kind=p.kind,
          subject_root_ids=tuple(reversed(p.subject_root_ids)), source_synthesis_id=p.source_synthesis_id,
          sections=p.sections)
    other = syn(world[0], "THEME_SET", (R, Q, P), comparison=EARLY)
    assert plan_presentation(other).to_canonical_json() == p.to_canonical_json()


def test_x_no_beneficiary_ranking(theme_set) -> None:
    payload = plan_presentation(theme_set).to_dict()
    keys, _ = walk(payload)
    assert not [k for k in keys if "benefic" in k or "rank" in k]
    assert not [v for v in vocabulary(payload) if "BENEFIC" in v or "RANK" in v]


# ================================================================ Y〜AA 代替の説明

def alternatives(p):
    return section(p, S.ALTERNATIVES)


def test_y_alternatives_are_parallel_and_cannot_be_hidden(theme_set) -> None:
    p = plan_presentation(theme_set)
    assert alternatives(p)
    for item in alternatives(p):
        assert len(item.theme_root_ids) >= 2 and list(item.theme_root_ids) == sorted(item.theme_root_ids)
        assert (item.epistemic_class, item.visibility) == (A1.EpistemicClass.ALTERNATIVE_HYPOTHESIS,
                                                           Visibility.REQUIRED)
        for root in item.theme_root_ids:                                                  # どの Theme を見せても隠せない
            [state_item] = [i for i in section(p, S.STATE) if i.theme_root_ids == (root,)]
            fails("PRESENTATION_CONFLICT", validate_display_selection, p, {state_item.claim_id})


def test_z_alternatives_carry_no_order_or_rank(theme_set) -> None:
    claims = {c.claim_id: c for c in theme_set.claims}
    for item in alternatives(plan_presentation(theme_set)):
        assert set(item.to_dict()) == ITEM_KEYS
        claim = claims[item.claim_id]
        rebuilt = A1.NarrativeClaim(epistemic_class=claim.epistemic_class, claim_kind=claim.claim_kind,
                                    predicate=claim.predicate, refs=tuple(reversed(claim.refs)))
        assert PL.item_for_claim(rebuilt) == item                                        # Theme の並びは集合


def test_aa_no_preferred_hypothesis(theme_set) -> None:
    p = plan_presentation(theme_set)
    for item in alternatives(p):
        members = [i for i in section(p, S.STATE) if i.theme_root_ids[0] in item.theme_root_ids]
        assert len(members) == len(item.theme_root_ids)
        assert len({(i.section, i.visibility, i.epistemic_class) for i in members}) == 1   # どれも同じ扱い
    with pytest.raises(TypeError):
        PresentationItem(**item_kwargs(alternatives(p)[0], preferred=True))


# ================================================================ AB〜AE identity・規則表の version・path・時計

def test_ab_the_presentation_id_is_content_addressed_and_stable(state, theme_set) -> None:
    p = plan_presentation(theme_set)
    assert p.presentation_id == plan_presentation(theme_set).presentation_id
    assert re.fullmatch(r"narprs_[0-9a-f]{24}", p.presentation_id)
    payload = p.to_dict()
    del payload["presentation_id"]
    assert p.presentation_id == content_id("narprs", A1.canonical_json(payload))
    assert plan_presentation(state).presentation_id != p.presentation_id


def test_ac_the_presentation_ruleset_version_is_bound_outside_a1_a2_a3(state, monkeypatch) -> None:
    p = plan_presentation(state)
    assert p.to_dict()["ruleset"] == {"name": "narrative_presentation_rules", "version": "0.1.0"}
    monkeypatch.setattr(PM, "PRESENTATION_RULESET_VERSION", "0.2.0")
    q = plan_presentation(state)
    assert q.presentation_id != p.presentation_id and q.to_dict()["ruleset"]["version"] == "0.2.0"
    assert "narrative_presentation_rules" not in state.to_canonical_json()               # A1 には保存しない


def test_ad_paths_and_mtimes_are_irrelevant(world, state, tmp_path) -> None:
    (tmp_path / "elsewhere").mkdir()
    other = tmp_path / "elsewhere" / "data"
    build_engine_world(other)
    expected = plan_presentation(state).to_canonical_json()
    assert plan_presentation(syn(other)).to_canonical_json() == expected
    for path in other.rglob("*"):
        if path.is_file():
            os.utime(path, (0, 0))
    assert plan_presentation(syn(other)).to_canonical_json() == expected
    assert str(other) not in expected and str(world[0]) not in expected and "data" not in vocabulary(
        plan_presentation(state).to_dict())


def test_ae_bg_no_clock_or_randomness_changes_presentation_or_diff(theme_set, early_set, late_set,
                                                                   monkeypatch) -> None:
    import random
    import secrets
    import time
    import uuid
    expected = (plan_presentation(theme_set).to_canonical_json(),
                diff_syntheses(previous=early_set, current=late_set).to_canonical_json())

    def forbidden(*args, **kwargs):
        raise AssertionError("A4a used a clock or randomness")
    for module, name in ((time, "time"), (time, "time_ns"), (time, "monotonic"), (random, "random"),
                         (random, "shuffle"), (secrets, "token_hex"), (uuid, "uuid4"), (os, "urandom")):
        monkeypatch.setattr(module, name, forbidden)
    assert (plan_presentation(theme_set).to_canonical_json(),
            diff_syntheses(previous=early_set, current=late_set).to_canonical_json()) == expected


# ================================================================ AF〜AM 差分の区分・順序・identity

def claim_ids(s):
    return {c.claim_id for c in s.claims}


def test_af_a_valid_diff(early_set, late_set) -> None:
    d = diff_syntheses(previous=early_set, current=late_set)
    assert (d.previous_synthesis_id, d.current_synthesis_id) == (early_set.synthesis_id, late_set.synthesis_id)
    assert d.kind is A1.NarrativeKind.THEME_SET and d.subject_root_ids == late_set.subject_root_ids
    assert set(d.claim_ids(DiffCategory.ADDED)) == claim_ids(late_set) - claim_ids(early_set)
    assert set(d.claim_ids(DiffCategory.REMOVED)) == claim_ids(early_set) - claim_ids(late_set)
    assert set(d.claim_ids(DiffCategory.UNCHANGED)) == claim_ids(early_set) & claim_ids(late_set)
    assert len(d.items) == len(claim_ids(early_set) | claim_ids(late_set))


def test_ag_the_same_claim_id_is_unchanged(early_set, late_set) -> None:
    d = diff_syntheses(previous=early_set, current=late_set)
    current = {i.claim_id: i for i in plan_presentation(late_set).items()}
    unchanged = [e for e in d.items if e.category is DiffCategory.UNCHANGED]
    assert unchanged and all(e.item == current[e.item.claim_id] for e in unchanged)


def test_ah_a_previous_only_claim_is_removed(early_set, late_set) -> None:
    d = diff_syntheses(previous=early_set, current=late_set)
    previous = {i.claim_id: i for i in plan_presentation(early_set).items()}
    removed = [e for e in d.items if e.category is DiffCategory.REMOVED]
    assert removed and all(e.item == previous[e.item.claim_id] for e in removed)
    assert all(e.item.claim_id not in claim_ids(late_set) for e in removed)


def test_ai_a_current_only_claim_is_added(future_pair) -> None:
    before, after = future_pair
    d = diff_syntheses(previous=before, current=after)
    current = {i.claim_id: i for i in plan_presentation(after).items()}
    added = [e for e in d.items if e.category is DiffCategory.ADDED]
    assert [(e.item.section, e.item.predicate) for e in added] == [(S.RELATION, A1.Predicate.HUMAN_ASSERTED_RELATION)]
    assert all(e.item == current[e.item.claim_id] and e.item.claim_id not in claim_ids(before) for e in added)


def similar_pair(state):
    """機構 component の key だけが違う「似た」claim を持つ後の synthesis。"""
    component = next(c for c in state.claims if c.predicate is A1.Predicate.RECORDS_MECHANISM_COMPONENT)
    ref = component.refs[0]
    similar = A1.NarrativeClaim(epistemic_class=component.epistemic_class, claim_kind=component.claim_kind,
                                predicate=component.predicate,
                                refs=(A1.MechanismComponentRef(root_id=ref.root_id, observation_id=ref.observation_id,
                                                               component_type=ref.component_type,
                                                               component_key=ref.component_key + "_v2"),))
    later = variant(state, cutoff=day(11), drop=lambda c: c.claim_id == component.claim_id, extra=(similar,))
    return component, similar, later


def test_aj_similar_claims_are_never_matched(state) -> None:
    component, similar, later = similar_pair(state)
    d = diff_syntheses(previous=state, current=later)
    assert d.claim_ids(DiffCategory.REMOVED) == (component.claim_id,)
    assert d.claim_ids(DiffCategory.ADDED) == (similar.claim_id,)
    assert component.claim_id not in d.claim_ids(DiffCategory.UNCHANGED)


def test_ak_no_modified_category_is_inferred(state) -> None:
    assert [c.value for c in DiffCategory] == ["ADDED", "REMOVED", "UNCHANGED"]
    _, _, later = similar_pair(state)
    d = diff_syntheses(previous=state, current=later)
    assert {e.category for e in d.items} == {DiffCategory.ADDED, DiffCategory.REMOVED, DiffCategory.UNCHANGED}
    fails("PRESENTATION_CONFLICT", NarrativeDiffItem, category="MODIFIED", item=d.items[0].item)


def test_al_the_diff_order_is_canonical_and_input_order_free(early_set, late_set) -> None:
    d = diff_syntheses(previous=early_set, current=late_set)
    keys = [PM.diff_item_order_key(e) for e in d.items]
    assert keys == sorted(keys)

    def shuffled(s):
        return A1.NarrativeSynthesis(kind=s.kind, subject_root_ids=tuple(reversed(s.subject_root_ids)),
                                     cutoff=s.cutoff, knowledge_pins=tuple(reversed(s.knowledge_pins)),
                                     input_digest=s.input_digest, claims=tuple(reversed(s.claims)))
    assert diff_syntheses(previous=shuffled(early_set), current=shuffled(late_set)).to_canonical_json() == (
        d.to_canonical_json())
    fails("PRESENTATION_CONFLICT", NarrativeDiff, kind=d.kind, subject_root_ids=d.subject_root_ids,
          previous_synthesis_id=d.previous_synthesis_id, current_synthesis_id=d.current_synthesis_id,
          items=tuple(reversed(d.items)))


def test_am_the_diff_id_is_content_addressed_and_stable(early_set, late_set, monkeypatch, tmp_path) -> None:
    d = diff_syntheses(previous=early_set, current=late_set)
    assert d.diff_id == diff_syntheses(previous=early_set, current=late_set).diff_id
    assert re.fullmatch(r"nardif_[0-9a-f]{24}", d.diff_id)
    payload = d.to_dict()
    del payload["diff_id"]
    assert d.diff_id == content_id("nardif", A1.canonical_json(payload))
    for path, s in (("previous.json", early_set), ("current.json", late_set)):
        (tmp_path / path).write_text(s.to_canonical_json(), encoding="utf-8")
    code = ("import sys\nfrom src.intelligence.narrative_intelligence.synthesis_model import NarrativeSynthesis\n"
            "from src.intelligence.narrative_intelligence.narrative_diff import diff_syntheses\n"
            "load = lambda p: NarrativeSynthesis.from_json(open(p, encoding='utf-8').read())\n"
            "sys.stdout.write(diff_syntheses(previous=load(sys.argv[1]), current=load(sys.argv[2])).to_canonical_json())\n")
    out = subprocess.run([sys.executable, "-c", code, str(tmp_path / "previous.json"), str(tmp_path / "current.json")],
                         cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(REPO_ROOT), "PATH": "", "PYTHONHASHSEED": "7"})
    assert out.stdout == d.to_canonical_json()
    monkeypatch.setattr(PM, "DIFF_RULESET_VERSION", "0.2.0")
    assert diff_syntheses(previous=early_set, current=late_set).diff_id != d.diff_id
    monkeypatch.undo()
    monkeypatch.setattr(PM, "PRESENTATION_RULESET_VERSION", "0.2.0")                    # item の写し方も束ねる
    assert diff_syntheses(previous=early_set, current=late_set).diff_id != d.diff_id


# ================================================================ AN〜AQ 方向の評価なし

DIRECTION_WORDS = {"IMPROVED", "WORSENED", "STRENGTHENED", "WEAKENED", "BETTER", "WORSE", "BULLISH", "BEARISH",
                   "POSITIVE", "NEGATIVE", "UP", "DOWN", "UPGRADE", "DOWNGRADE", "MODIFIED", "MORE_CONFIDENT",
                   "LESS_CONFIDENT"}


def test_an_an_added_support_is_only_added(state) -> None:
    [support] = [c for c in state.claims if is_attached(c, "SUPPORTS", FACT_P)]
    earlier = variant(state, cutoff=day(9), drop=lambda c: c.claim_id == support.claim_id)
    d = diff_syntheses(previous=earlier, current=state)
    added = [e for e in d.items if e.category is DiffCategory.ADDED]
    assert [(e.item.claim_id, e.item.evidence_role) for e in added] == [(support.claim_id, A1.EvidenceRole.SUPPORTS)]
    assert {e.category for e in d.items} == {DiffCategory.ADDED, DiffCategory.UNCHANGED}
    assert not vocabulary(d.to_dict()) & DIRECTION_WORDS


def removed_contradiction(state):
    contradiction = {c.claim_id for c in state.claims if is_attached(c, "CONTRADICTS")
                     or (c.uncertainty_code and c.uncertainty_code.value == "CONTESTED_EVIDENCE")}
    return contradiction, variant(state, cutoff=day(11), drop=lambda c: c.claim_id in contradiction)


def test_ao_a_removed_contradiction_is_only_removed(state) -> None:
    contradiction, later = removed_contradiction(state)
    d = diff_syntheses(previous=state, current=later)
    assert set(d.claim_ids(DiffCategory.REMOVED)) == contradiction and not d.claim_ids(DiffCategory.ADDED)
    assert {e.category for e in d.items} == {DiffCategory.REMOVED, DiffCategory.UNCHANGED}
    assert not vocabulary(d.to_dict()) & DIRECTION_WORDS


def test_ap_no_bullish_bearish_or_directional_evaluation(early_set, late_set, future_pair) -> None:
    for d in (diff_syntheses(previous=early_set, current=late_set),
              diff_syntheses(previous=future_pair[0], current=future_pair[1])):
        keys, _ = walk(d.to_dict())
        assert not vocabulary(d.to_dict()) & DIRECTION_WORDS
        assert not keys & FORBIDDEN_KEYS
    assert "whether a theme improved" in PM.DIFF_DOES_NOT_ANSWER
    assert "why the market changed" in PM.DIFF_DOES_NOT_ANSWER


def test_aq_no_confidence_change_is_inferred(state) -> None:
    _, later = removed_contradiction(state)
    d = diff_syntheses(previous=state, current=later)
    [contested] = [e for e in d.items if e.item.uncertainty_code is A1.UncertaintyCode.CONTESTED_EVIDENCE]
    assert contested.category is DiffCategory.REMOVED                                    # code のまま・数にしない
    assert not [v for v in walk(d.to_dict())[1] if isinstance(v, (int, float))]
    assert "whether confidence increased" in PM.DIFF_DOES_NOT_ANSWER


# ================================================================ AR〜AW 比べられない入力・改ざん・version

def test_ar_incompatible_kinds_are_rejected(state, theme_set) -> None:
    assert fails("INCOMPATIBLE_DIFF_INPUTS", diff_syntheses, previous=state,
                 current=theme_set).detail == "KIND_MISMATCH"


def test_as_incompatible_scope_pins_or_chronology_are_rejected(world, state, ctx, early_set, late_set) -> None:
    assert fails("INCOMPATIBLE_DIFF_INPUTS", diff_syntheses, previous=ctx, current=state).detail == "SCOPE_MISMATCH"
    narrower = syn(world[0], "THEME_SET", (P, Q), cutoff=day(3))
    assert fails("INCOMPATIBLE_DIFF_INPUTS", diff_syntheses, previous=narrower,
                 current=late_set).detail == "SCOPE_MISMATCH"
    other_reader = variant(state, cutoff=day(11), pins=tuple((n, "0.1.1" if n == "theme_resolver" else v)
                                                             for n, v in state.knowledge_pins))
    plan_presentation(other_reader)                                                        # 提示はできる
    assert fails("INCOMPATIBLE_DIFF_INPUTS", diff_syntheses, previous=state,
                 current=other_reader).detail == "KNOWLEDGE_PINS_MISMATCH"
    for before, after in ((late_set, early_set), (state, state)):
        assert fails("INCOMPATIBLE_DIFF_INPUTS", diff_syntheses, previous=before,
                     current=after).detail == "CUTOFF_ORDER"
    parameters = inspect.signature(diff_syntheses).parameters                             # 暗黙の前回を持たない
    assert [(n, p.kind, p.default) for n, p in parameters.items()] == [
        ("previous", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty),
        ("current", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty)]
    with pytest.raises(TypeError):
        diff_syntheses(current=state)
    with pytest.raises(TypeError):
        diff_syntheses(state, state)
    fails("INVALID_SYNTHESIS", diff_syntheses, previous=None, current=state)
    fails("INVALID_SYNTHESIS", diff_syntheses, previous=state, current=state.synthesis_id)


def test_at_a_tampered_synthesis_id_is_rejected(state, early_set, late_set) -> None:
    for mutate in (lambda t: object.__setattr__(t, "synthesis_id", "narsyn_" + "0" * 24),
                   lambda t: object.__setattr__(t, "cutoff", t.cutoff + timedelta(days=1)),
                   lambda t: object.__setattr__(t, "input_digest", "narinp_" + "1" * 24),
                   lambda t: object.__setattr__(t, "claims", t.claims[1:])):
        fails("SYNTHESIS_INTEGRITY_FAILURE", plan_presentation, tampered(state, mutate))
        fails("SYNTHESIS_INTEGRITY_FAILURE", diff_syntheses, previous=tampered(early_set, mutate), current=late_set)
        fails("SYNTHESIS_INTEGRITY_FAILURE", diff_syntheses, previous=early_set, current=tampered(late_set, mutate))


def test_au_a_tampered_claim_id_is_rejected(state) -> None:
    fails("SYNTHESIS_INTEGRITY_FAILURE", plan_presentation,
          tampered(state, lambda t: object.__setattr__(t.claims[0], "claim_id", "narclm_" + "0" * 24)))
    fails("SYNTHESIS_INTEGRITY_FAILURE", plan_presentation,
          tampered(state, lambda t: object.__setattr__(t.claims[0], "refs", t.claims[0].refs + t.claims[1].refs)))


def test_av_tampered_roles_classes_pins_or_types_are_rejected(state, theme_set) -> None:
    def first(t, predicate, role=None):
        return next(c for c in t.claims if c.predicate.value == predicate and (role is None or is_attached(c, role)))
    mutations = (
        lambda t: object.__setattr__(first(t, "EVIDENCE_ATTACHED", "CONTRADICTS").refs[0], "role",
                                     A1.EvidenceRole.SUPPORTS),
        lambda t: object.__setattr__(first(t, "EVIDENCE_ATTACHED", "CONTEXT").refs[0], "role",
                                     A1.EvidenceRole.SUPPORTS),
        lambda t: object.__setattr__(first(t, "THEME_REVIEWED_STATE"), "epistemic_class",
                                     A1.EpistemicClass.OBSERVED_FACT),
        lambda t: object.__setattr__(first(t, "RECORDS_MECHANISM_COMPONENT"), "claim_kind", A1.ClaimKind.STATE),
        lambda t: object.__setattr__(first(t, "IS_UNCERTAIN"), "uncertainty_code", A1.UncertaintyCode.STALE_EVIDENCE),
        lambda t: object.__setattr__(first(t, "THEME_REVIEWED_STATE"), "predicate", "THEME_REVIEWED_STATE"),
        lambda t: object.__setattr__(t, "knowledge_pins", t.knowledge_pins[:-1]),
        lambda t: object.__setattr__(t, "knowledge_pins", tuple(
            (n, "0.2.0" if n == "narrative_synthesis_rules" else v) for n, v in t.knowledge_pins)),
        lambda t: object.__setattr__(t, "score", 1),
        lambda t: object.__setattr__(t.claims[0], "confidence", 0.9),
        lambda t: object.__setattr__(t, "subject_root_ids", (Q,)),
    )
    for mutate in mutations:
        fails("SYNTHESIS_INTEGRITY_FAILURE", plan_presentation, tampered(state, mutate))
    relation = lambda t: first(t, "SOURCE_ASSERTED_RELATION")                           # noqa: E731
    fails("SYNTHESIS_INTEGRITY_FAILURE", plan_presentation, tampered(theme_set, lambda t: object.__setattr__(
        [r for r in relation(t).refs if isinstance(r, A1.RelationAssertionRef)][0], "assertion_class",
        A1.AssertionClass.HUMAN_ASSERTED)))

    class Shadow(A1.NarrativeSynthesis):
        pass
    shadow = Shadow(kind=state.kind, subject_root_ids=state.subject_root_ids, cutoff=state.cutoff,
                    knowledge_pins=state.knowledge_pins, input_digest=state.input_digest, claims=state.claims)
    fails("SYNTHESIS_INTEGRITY_FAILURE", plan_presentation, shadow)
    fails("UNSUPPORTED_PRESENTATION_KIND", plan_presentation,
          tampered(state, lambda t: object.__setattr__(t, "kind", "PORTFOLIO")))
    for value in (None, {}, state.to_dict(), state.to_canonical_json(), snap):
        fails("INVALID_SYNTHESIS", plan_presentation, value)


def test_aw_unsupported_synthesis_versions_are_rejected(state, monkeypatch) -> None:
    newer = variant(state, cutoff=state.cutoff, pins=tuple((n, "0.2.0" if n == "narrative_synthesis_rules" else v)
                                                           for n, v in state.knowledge_pins))
    fails("UNSUPPORTED_SYNTHESIS_VERSION", plan_presentation, newer)
    unpinned = variant(state, cutoff=state.cutoff, pins=tuple(pin for pin in state.knowledge_pins
                                                               if pin[0] != "narrative_synthesis_rules"))
    fails("UNSUPPORTED_SYNTHESIS_VERSION", plan_presentation, unpinned)
    assert (PL.SYNTHESIS_RULESET_NAME, PL.SUPPORTED_SYNTHESIS_RULESET_VERSIONS) == (E.RULESET_NAME, (E.RULESET_VERSION,))
    assert (PL.SUPPORTED_SYNTHESIS_SCHEMA_VERSION, PL.SUPPORTED_CLAIM_SCHEMA_VERSION) == (A1.SCHEMA_VERSION,
                                                                                          A1.CLAIM_SCHEMA_VERSION)
    monkeypatch.setattr(A1, "SCHEMA_VERSION", "narrative_synthesis:0.2.0")
    fails("UNSUPPORTED_SYNTHESIS_VERSION", plan_presentation, state)
    monkeypatch.undo()
    monkeypatch.setattr(A1, "CLAIM_SCHEMA_VERSION", "narrative_claim:0.2.0")
    fails("UNSUPPORTED_SYNTHESIS_VERSION", plan_presentation, state)


# ================================================================ AX〜BH 永続化なし・純粋な実行・境界

def test_ax_nothing_is_persisted_or_loadable() -> None:
    for model in (NarrativePresentation, NarrativeDiff, PresentationItem, PresentationSection, NarrativeDiffItem):
        assert not [name for name in ("from_dict", "from_json", "save", "load", "write", "persist", "path")
                    if hasattr(model, name)], model
    for fn in (plan_presentation, diff_syntheses, validate_display_selection, revalidate_synthesis,
               PL.item_for_claim):
        assert not set(inspect.signature(fn).parameters) & {"data_root", "path", "root", "store", "journal", "cache",
                                                             "output", "out_dir", "previous_run", "latest"}


def test_ay_bf_bh_zero_write_no_network_and_no_authority_mutation(world, state, theme_set, early_set, late_set,
                                                                  monkeypatch) -> None:
    def inventory(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    data_before = inventory(world[0])
    repo_before = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    inputs = [s.to_canonical_json() for s in (state, theme_set, early_set, late_set)]
    constants = [{name: repr(value) for name, value in vars(module).items() if not name.startswith("__")}
                 for module in A4A_MODULES]
    expected = (plan_presentation(theme_set).to_canonical_json(),
                diff_syntheses(previous=early_set, current=late_set).to_canonical_json())

    def forbidden(*args, **kwargs):
        raise AssertionError("A4a touched a file or the network")
    for module, name in ((builtins, "open"), (os, "open"), (os, "replace"), (os, "rename"), (os, "remove"),
                         (os, "makedirs"), (os, "mkdir"), (socket, "socket"), (socket, "create_connection")):
        monkeypatch.setattr(module, name, forbidden)
    for _ in range(5):
        assert (plan_presentation(theme_set).to_canonical_json(),
                diff_syntheses(previous=early_set, current=late_set).to_canonical_json()) == expected
        validate_display_selection(plan_presentation(state), plan_presentation(state).claim_ids())
    monkeypatch.undo()
    assert inventory(world[0]) == data_before
    assert subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True,
                          text=True).stdout == repo_before
    assert [s.to_canonical_json() for s in (state, theme_set, early_set, late_set)] == inputs   # 入力を変えない
    assert [{name: repr(value) for name, value in vars(module).items() if not name.startswith("__")}
            for module in A4A_MODULES] == constants                                        # 学習・状態の蓄積なし


def test_az_ba_no_p4_public_output_llm_or_provider() -> None:
    for module in A4A_MODULES:
        source = executable_source(Path(module.__file__)).lower()
        words = set(re.findall(r"[a-z0-9]+", source))                                      # 識別子を _ で分けた語
        for token in ("html", "markdown", "pdf", "notifier", "pages", "prompt", "anthropic", "openai", "provider",
                      "llm", "compass", "narrativeplan", "narrativegenerator", "render", "publish", "notify"):
            assert token not in words, (module.__name__, token)
        for token in (".md", "docs/", "api_key", "model_name", "://"):
            assert token not in source, (module.__name__, token)
    names = set(dir(PM)) | set(dir(PL)) | set(dir(D))
    assert not names & {"NarrativePlan", "NarrativeGenerator", "render", "publish", "notify"}


@pytest.mark.parametrize("module", A4A_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[1])
def test_bb_bc_bd_be_imports_are_only_a1_and_a4a(module) -> None:
    from tests.intelligence.test_prediction_record import imported_modules
    assert imported_modules(Path(module.__file__)) <= {"__future__", "re", "dataclasses", "enum", "typing",
                                                       "..core.ids", ".synthesis_model", ".presentation_model",
                                                       ".presentation_planner"}


def test_the_contract_states_the_questions_and_the_authority_class() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert PM.AUTHORITY_CLASS == ("DERIVED", "NON_AUTHORITY", "NON_PERSISTENT")
    for phrase in (PM.PRESENTATION_ANSWERS, PM.PRESENTATION_DOES_NOT_ANSWER, PM.DIFF_ANSWERS, PM.DIFF_DOES_NOT_ANSWER,
                   PM.PRESENTATION_IS_NOT_AUTHORITY, *PM.FAILURE_CODES):
        assert phrase in text, phrase
    assert "which explanation wins" in PM.PRESENTATION_DOES_NOT_ANSWER
