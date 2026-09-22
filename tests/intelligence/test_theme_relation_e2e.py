"""P6-B5D — relation の E2E / authority laundering / 収束 gate（test only。runtime を変更しない）。

鎖は `RelationProposal` → 人間の決定 → `RelationAssertionPlan` までで**止める**。
`relation_assertions.jsonl` / `relation_governance.jsonl` へは本 gate では一切書かない。

本 file は現行 runtime の**実際の挙動**を固定する。保証されていないことを保証として書かない
（SOURCE_ASSERTED の意味論的検査は runtime に無いため、その不在を不在として記録する）。
"""
from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence.relation_graph import build_relation_graph_view
from src.intelligence.theme_intelligence.relation_model import (AssertionClass, EVIDENCE_REQUIRED_TYPES,
                                                                RelationEvidenceRef, RelationType,
                                                                SOURCE_ASSERTED_MEANING, SOURCE_ASSERTED_NON_MEANING,
                                                                SourceAttribution, ThemeRelationAssertion,
                                                                canonical_relation_line, edge_key_of)
from src.intelligence.theme_intelligence.relation_proposal_bridge import (RELATION_PLAN_VERSION,
                                                                          RelationBridgeError,
                                                                          plan_relation_assertion_from_accepted_proposal)
from src.intelligence.theme_intelligence.relation_proposal_model import (ACCEPTABLE_ASSERTION_CLASSES,
                                                                         PROPOSER_IS_NOT_AUTHORITY,
                                                                         RelationChangeKind, RelationDecisionKind,
                                                                         RelationProposal, RelationProposalDecision,
                                                                         RelationProposerClass,
                                                                         canonical_proposal_record_line,
                                                                         source_authority_available)
from src.intelligence.theme_intelligence.relation_proposal_resolution import (DecisionResolutionStatus,
                                                                              RelationProposalStatus,
                                                                              derive_relation_proposal_status,
                                                                              resolve_active_relation_decision)
from src.intelligence.theme_intelligence.relation_proposal_store import (AppendStatus,
                                                                         RelationProposalAppendRejected,
                                                                         RelationProposalConcurrentModification,
                                                                         RelationProposalConflict,
                                                                         RelationProposalStore,
                                                                         RelationProposalStoreCorrupt)
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as proposal_authority_paths
from src.intelligence.theme_intelligence.relation_resolution import EndpointState, endpoint_lookup_from_roots
from src.intelligence.theme_intelligence.relation_store import authority_paths as relation_authority_paths
from src.intelligence.themes.model import EvidenceKind, ProvenanceClass
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_theme_relation import (A, ACTOR, ATTRIBUTION, B, C, D, ORIGIN, T0, evidence, restoration,
                                                    retraction)
from tests.intelligence.test_theme_relation_proposal import (DECIDED_AT, MISSING_ASSERTION_ID, OTHER_SOURCE, PLANNED_AT,
                                                             authority_edges, b5b_assertion, causal, decide, lookup,
                                                             plan_of, proposal, provenance, sourced)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
B5_RUNTIME_MODULES = ("relation_model", "relation_resolution", "relation_graph", "relation_store",
                      "relation_proposal_model", "relation_proposal_resolution", "relation_proposal_bridge",
                      "relation_proposal_store")
#: B5D が固定する authority laundering matrix の軸
PROPOSER_CLASSES = (RelationProposerClass.HUMAN, RelationProposerClass.SOURCE, RelationProposerClass.RULE,
                    RelationProposerClass.LLM)
DEEP_SEEDS = tuple(range(11))


def store_at(tmp_path: Path, name: str = "data") -> RelationProposalStore:
    return RelationProposalStore.initialize(tmp_path / name)


def cited(tag: str = "a", *, attribution: str = "publisher:example_wire", locator: str = "", at=None) -> RelationEvidenceRef:
    """出典参照。`attribution` は「その evidence の中で誰が述べたか」の自由 text（runtime は帰属と突き合わせない）。"""
    return RelationEvidenceRef(evidence_kind=EvidenceKind.SOURCE_DOCUMENT, ref_id="doc_" + (tag * 24)[:24],
                               source_origin=ORIGIN, evidence_time=at, locator=locator, attribution=attribution)


def candidate_of(proposer: RelationProposerClass, *, attribution=None, refs=(), rationale=None, **kw) -> RelationProposal:
    """提案者 class を軸にした候補。SOURCE class だけは model が帰属と citation を要求する。"""
    if proposer is RelationProposerClass.SOURCE:
        attribution = attribution or ATTRIBUTION
        refs = refs or (cited(),)
    return proposal(proposer=proposer, proposer_ref=f"{proposer.value.lower()}:relation_candidate",
                    attribution=attribution, refs=refs,
                    rationale=rationale or "construction demand lifts electricity use", **kw)


def accept(candidate, accepted: AssertionClass, **kw):
    return decide(candidate, RelationDecisionKind.ACCEPT, accepted=accepted, **kw)


def recorded(store: RelationProposalStore, candidate, decisions=()):
    store.append_proposal(candidate)
    for item in decisions:
        store.append_decision(item)
    return store


def bytes_of(paths) -> dict:
    return {name: path.read_bytes() for name, path in paths.items() if path.exists()}


def refuses(code: str, candidate, decisions, **kw) -> RelationBridgeError:
    with pytest.raises(RelationBridgeError) as info:
        plan_of(candidate, decisions, **kw)
    assert info.value.code == code, info.value.code
    return info.value


# ================================================================ §1 鎖の E2E（plan で止める）


def test_b5d_01_full_chain_stops_at_the_plan_and_writes_no_relation_authority(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = sourced()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    recorded(store, candidate, (decision,))
    plan = plan_of(candidate, (decision,))
    assert plan.plan_version == RELATION_PLAN_VERSION
    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert not any(path.exists() for path in relation_authority_paths(tmp_path / "data").values())
    assert store.counts() == {"proposals": 1, "decisions": 1}


def test_b5d_02_plan_carries_everything_a_b5b_assertion_needs_without_building_authority(tmp_path) -> None:
    candidate = sourced()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    plan = plan_of(candidate, (decision,))
    assembled = ThemeRelationAssertion.build(
        source_theme_root_id=plan.source_theme_root_id, target_theme_root_id=plan.target_theme_root_id,
        relation_type=plan.relation_type, assertion_class=plan.assertion_class, rationale=plan.rationale,
        evidence_refs=plan.evidence_refs, source_attribution=plan.source_attribution,
        previous_assertion_id=plan.previous_assertion_id, provenance=ACTOR, recorded_at=plan.recorded_at)
    assert assembled.edge_key == plan.edge_key
    assert canonical_relation_line(assembled).endswith("\n")
    assert not any(path.exists() for path in relation_authority_paths(tmp_path / "data").values())


def test_b5d_03_the_plan_is_never_persisted_by_the_proposal_store(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    decision = accept(candidate, AssertionClass.HUMAN_ASSERTED)
    recorded(store, candidate, (decision,))
    plan = plan_of(candidate, (decision,))
    files = sorted(p.name for p in (tmp_path / "data" / "theme_intelligence").iterdir())
    assert files == ["relation_proposal_decisions.jsonl", "relation_proposals.jsonl"]
    assert plan.canonical_line() not in "".join(store.canonical_lines("proposals"))


def test_b5d_04_the_bridge_module_never_reaches_the_relation_authority_store() -> None:
    source = executable_source(PACKAGE_DIR / "relation_proposal_bridge.py")
    for token in ("relation_store", "append_assertion", "append_event", "ThemeRelationStore"):
        assert token not in source, token


def test_b5d_05_two_stores_on_one_data_root_stay_in_their_own_files(tmp_path) -> None:
    from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
    relation_store = ThemeRelationStore.initialize(tmp_path / "data")
    before = bytes_of(relation_authority_paths(tmp_path / "data"))
    store = store_at(tmp_path)
    candidate = sourced()
    recorded(store, candidate, (accept(candidate, AssertionClass.SOURCE_ASSERTED),))
    assert bytes_of(relation_authority_paths(tmp_path / "data")) == before
    assert relation_store.counts() == {"assertions": 0, "governance": 0}


# ================================================================ §2 authority laundering matrix（4 × 2）
#
# 注意: 本節は「許可 / 拒否の matrix」では終わらせない。SOURCE_ASSERTED の意味は
#   「指定された source が relation semantics (source → relation_type → target) を主張し、
#    それを人間が SOURCE_ASSERTED として受理した」であり、「citation が存在する」ではない。
# 現行 runtime の適格判定は `source_authority_available` の 2 条件（帰属が非 None / citation 1 件以上）だけである。
# したがって A（出典の主張を抽出）と B（独自推論に citation を後付け）/ C（出典は言及のみ）は**区別されない**。
# 以下はその事実を事実として固定する。区別できるかのように PASS させない。


@pytest.mark.parametrize("proposer", PROPOSER_CLASSES)
def test_b5d_06_09_every_proposer_class_may_be_accepted_as_human_asserted(proposer) -> None:
    candidate = candidate_of(proposer)
    plan = plan_of(candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),))
    assert plan.assertion_class is AssertionClass.HUMAN_ASSERTED
    assert plan.source_attribution is None                      # B5B の ATTRIBUTION_FORBIDDEN に従う
    assert plan.proposal_origin.proposer_class is proposer       # 提案者は書き換えられない
    assert plan.decision_origin.actor_class is ProvenanceClass.HUMAN


@pytest.mark.parametrize("proposer", PROPOSER_CLASSES)
def test_b5d_10_13_source_asserted_depends_only_on_attribution_and_citation(proposer) -> None:
    """4 提案者 class すべてで、SOURCE_ASSERTED の可否は提案者ではなく帰属 ＋ citation の有無だけで決まる。"""
    bare = candidate_of(proposer) if proposer is RelationProposerClass.SOURCE else candidate_of(proposer)
    if proposer is RelationProposerClass.SOURCE:
        plan = plan_of(bare, (accept(bare, AssertionClass.SOURCE_ASSERTED),))
        assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    else:
        assert source_authority_available(bare) is False
        refuses("FORBIDDEN_SOURCE_AUTHORITY", bare, (accept(bare, AssertionClass.SOURCE_ASSERTED),))
    dressed = candidate_of(proposer, attribution=ATTRIBUTION, refs=(cited(),))
    assert source_authority_available(dressed) is True
    plan = plan_of(dressed, (accept(dressed, AssertionClass.SOURCE_ASSERTED),))
    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert plan.proposal_origin.proposer_class is proposer


def test_b5d_14_case_a_extracted_source_claim_keeps_attribution_and_proposer() -> None:
    """A: RULE / LLM が出典の主張を抽出し、帰属と citation を保ったまま人間が SOURCE_ASSERTED で受理する。"""
    extracted = candidate_of(RelationProposerClass.LLM, attribution=ATTRIBUTION,
                             refs=(cited("a", attribution="publisher:example_wire", locator="section:2"),),
                             rationale="the cited release states the tariff raises input costs")
    plan = plan_of(extracted, (accept(extracted, AssertionClass.SOURCE_ASSERTED),))
    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert plan.source_attribution == ATTRIBUTION
    assert plan.proposal_origin.proposer_class is RelationProposerClass.LLM
    assert plan.proposal_origin.proposal_source_attribution == ATTRIBUTION.attributed_to


def test_b5d_15_case_b_independent_inference_with_an_unrelated_citation_is_not_rejected() -> None:
    """B: 独自推論に無関係な citation を付けても、帰属と citation が形式的に在る限り受理は通る（GAP）。

    citation の `attribution` が帰属 `attributed_to` と別 source を指していても runtime は突き合わせない。
    """
    laundered = candidate_of(RelationProposerClass.LLM, attribution=ATTRIBUTION,
                             refs=(cited("b", attribution=OTHER_SOURCE.attributed_to),),
                             rationale="inferred from model reasoning, citation attached for context")
    assert source_authority_available(laundered) is True
    plan = plan_of(laundered, (accept(laundered, AssertionClass.SOURCE_ASSERTED),))
    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert plan.source_attribution == ATTRIBUTION
    assert {e.attribution for e in plan.evidence_refs} == {OTHER_SOURCE.attributed_to}   # 突き合わせは無い


def test_b5d_16_case_b_a_citation_with_no_attribution_at_all_is_not_rejected() -> None:
    """B': citation の帰属 field が空でも SOURCE_ASSERTED 適格になる（GAP）。"""
    generic = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited("c", attribution=""),))
    assert source_authority_available(generic) is True
    plan = plan_of(generic, (accept(generic, AssertionClass.SOURCE_ASSERTED),))
    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED
    assert [e.attribution for e in plan.evidence_refs] == [""]


def test_b5d_17_case_c_a_source_that_only_mentions_the_topic_is_indistinguishable() -> None:
    """C: 出典が entity / topic に言及しただけで relation semantics を主張していない場合も区別されない（GAP）。"""
    mention_only = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION,
                               refs=(cited("d", locator="section:1"),),
                               rationale="the release mentions both themes but asserts no link")
    assert source_authority_available(mention_only) is True
    plan = plan_of(mention_only, (accept(mention_only, AssertionClass.SOURCE_ASSERTED),))
    assert plan.assertion_class is AssertionClass.SOURCE_ASSERTED


def test_b5d_18_case_a_and_case_b_can_produce_byte_identical_plans() -> None:
    """A と B は field が同じなら plan の canonical bytes まで同一になる。record model に差が無い（GAP の核心）。"""
    shared = dict(attribution=ATTRIBUTION, refs=(cited("e"),), rationale="the release links the two themes")
    extracted = candidate_of(RelationProposerClass.LLM, **shared)
    inferred = candidate_of(RelationProposerClass.LLM, **shared)
    assert extracted.proposal_id == inferred.proposal_id
    left = plan_of(extracted, (accept(extracted, AssertionClass.SOURCE_ASSERTED),))
    right = plan_of(inferred, (accept(inferred, AssertionClass.SOURCE_ASSERTED),))
    assert left.canonical_line() == right.canonical_line()
    plain = json.loads(left.canonical_line())
    assert not any(key for key in plain if "semantic" in key or "locus" in key or "verified" in key)


def test_b5d_19_case_d_missing_attribution_is_refused_in_store_and_bridge(tmp_path) -> None:
    """D: 出典が関係を主張していても帰属 field が無ければ SOURCE_ASSERTED にできない。"""
    unattributed = candidate_of(RelationProposerClass.LLM, refs=(cited("f"),),
                                rationale="the release asserts the link but the source is not named")
    assert source_authority_available(unattributed) is False
    decision = accept(unattributed, AssertionClass.SOURCE_ASSERTED)
    refuses("FORBIDDEN_SOURCE_AUTHORITY", unattributed, (decision,))
    store = store_at(tmp_path)
    store.append_proposal(unattributed)
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(decision)
    assert info.value.code == "FORBIDDEN_SOURCE_AUTHORITY"


def test_b5d_20_case_e_missing_citation_is_refused_in_store_and_bridge(tmp_path) -> None:
    """E: 帰属があっても citation が 1 件も無ければ SOURCE_ASSERTED にできない。"""
    uncited = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION)
    assert source_authority_available(uncited) is False
    decision = accept(uncited, AssertionClass.SOURCE_ASSERTED)
    refuses("FORBIDDEN_SOURCE_AUTHORITY", uncited, (decision,))
    store = store_at(tmp_path)
    store.append_proposal(uncited)
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(decision)
    assert info.value.code == "FORBIDDEN_SOURCE_AUTHORITY"


def test_b5d_21_case_f_llm_proposal_accepted_as_human_asserted_drops_the_attribution() -> None:
    """F: LLM 提案を人間が自分の名前で受理する。帰属は plan から落ち、提案側の帰属は origin に残る。"""
    machine = candidate_of(RelationProposerClass.LLM, attribution=ATTRIBUTION, refs=(cited("g"),))
    decision = accept(machine, AssertionClass.HUMAN_ASSERTED, reason="verified against the release myself")
    plan = plan_of(machine, (decision,))
    assert plan.assertion_class is AssertionClass.HUMAN_ASSERTED and plan.source_attribution is None
    assert plan.proposal_origin.proposer_class is RelationProposerClass.LLM
    assert plan.proposal_origin.proposal_source_attribution == ATTRIBUTION.attributed_to
    assert plan.decision_origin.actor_ref == "reviewer:r1"


def test_b5d_22_source_authority_available_is_exactly_the_two_clause_structural_predicate() -> None:
    """適格判定の全体。意味論的検査は存在しない（B5D では実装しない）。"""
    source = executable_source(PACKAGE_DIR / "relation_proposal_model.py")
    body = source.split("def source_authority_available")[1]
    assert "source_attribution is not None" in body and "len(proposal.evidence_refs) >= 1" in body
    for token in ("attribution_key", "asserts", "semantic", "verify", "locus"):
        assert token not in body.split("return")[1].split("\n")[0], token


def test_b5d_23_no_assertion_class_exists_for_rule_or_llm() -> None:
    assert tuple(AssertionClass) == (AssertionClass.HUMAN_ASSERTED, AssertionClass.SOURCE_ASSERTED)
    assert ACCEPTABLE_ASSERTION_CLASSES == tuple(AssertionClass)
    assert not [value for value in AssertionClass if value.value in ("RULE_ASSERTED", "LLM_ASSERTED")]


def test_b5d_24_the_frozen_source_asserted_meaning_is_unchanged() -> None:
    assert SOURCE_ASSERTED_MEANING == "the cited source asserted this relation"
    assert SOURCE_ASSERTED_NON_MEANING == "the system verified this relation as causal truth"
    assert PROPOSER_IS_NOT_AUTHORITY == "a proposer class describes who proposed, not who asserts"


def test_b5d_25_the_source_proposer_class_is_neither_required_nor_privileged() -> None:
    from src.intelligence.theme_intelligence.relation_proposal_model import RelationProposalError
    with pytest.raises(RelationProposalError) as info:
        proposal(proposer=RelationProposerClass.SOURCE, proposer_ref="publisher:example_wire")
    assert info.value.code == "MISSING_SOURCE_ATTRIBUTION"
    with pytest.raises(RelationProposalError) as info:
        proposal(proposer=RelationProposerClass.SOURCE, proposer_ref="publisher:example_wire", attribution=ATTRIBUTION)
    assert info.value.code == "MISSING_SOURCE_CITATION"
    rule_side = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited(),))
    source_side = candidate_of(RelationProposerClass.SOURCE, attribution=ATTRIBUTION, refs=(cited(),))
    assert rule_side.proposal_id == source_side.proposal_id          # 提案者は identity の外


# ================================================================ §3 B5C 報告 §8 の矛盾の決着


@pytest.mark.parametrize("proposer", PROPOSER_CLASSES)
def test_b5d_26_forbidden_source_authority_fires_iff_the_predicate_is_false(proposer) -> None:
    """「RULE / LLM でも帰属 ＋ citation があれば SOURCE_ASSERTED になれる」と
    「FORBIDDEN_SOURCE_AUTHORITY で拒否する」は同一述語の 2 分岐であり、矛盾ではない。"""
    for attribution, refs in ((None, ()), (ATTRIBUTION, ()), (None, (cited(),)), (ATTRIBUTION, (cited(),))):
        if proposer is RelationProposerClass.SOURCE and not (attribution and refs):
            continue                                              # SOURCE class は model 段階で形式を要求する
        candidate = candidate_of(proposer, attribution=attribution, refs=refs)
        eligible = source_authority_available(candidate)
        assert eligible is bool(attribution is not None and refs)
        decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
        if eligible:
            assert plan_of(candidate, (decision,)).assertion_class is AssertionClass.SOURCE_ASSERTED
        else:
            refuses("FORBIDDEN_SOURCE_AUTHORITY", candidate, (decision,))


def test_b5d_27_store_and_bridge_agree_on_the_predicate_for_every_proposer_class(tmp_path) -> None:
    store = store_at(tmp_path)
    for index, proposer in enumerate(PROPOSER_CLASSES):
        candidate = candidate_of(proposer, refs=(cited(chr(ord("h") + index)),),
                                 rationale=f"candidate {index} without attribution")
        store.append_proposal(candidate)
        decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
        store_refused = bridge_refused = False
        try:
            store.append_decision(decision)
        except RelationProposalAppendRejected as exc:
            store_refused = exc.code == "FORBIDDEN_SOURCE_AUTHORITY"
        try:
            plan_of(candidate, (decision,))
        except RelationBridgeError as exc:
            bridge_refused = exc.code == "FORBIDDEN_SOURCE_AUTHORITY"
        assert store_refused == bridge_refused == (not source_authority_available(candidate))


# ================================================================ §4 提案収束 matrix
#
# identity は「候補となる主張そのもの」で provenance / created_at を含まない。canonical bytes は含む。
# 帰結として「同 proposal_id ＋ 異 canonical bytes ＝ CONFLICT」が起きる。以下 5 case で確定させる。


def converging_pair(**difference):
    shared = dict(attribution=ATTRIBUTION, refs=(cited("m"),), rationale="the release links the two themes")
    left = candidate_of(RelationProposerClass.RULE, **shared)
    right = candidate_of(difference.pop("proposer", RelationProposerClass.RULE), **shared, **difference)
    return left, right


def test_b5d_28_case1_different_proposer_class_converges_then_conflicts(tmp_path) -> None:
    left, right = converging_pair(proposer=RelationProposerClass.LLM)
    assert left.proposal_id == right.proposal_id
    assert left.identity_payload() == right.identity_payload()
    assert canonical_proposal_record_line(left) != canonical_proposal_record_line(right)
    store = store_at(tmp_path)
    assert store.append_proposal(left).status is AppendStatus.APPENDED
    with pytest.raises(RelationProposalConflict) as info:
        store.append_proposal(right)
    assert info.value.code == "CONFLICT"


def test_b5d_29_case2_different_proposer_ref_converges_then_conflicts(tmp_path) -> None:
    shared = dict(attribution=ATTRIBUTION, refs=(cited("m"),), rationale="the release links the two themes")
    left = proposal(proposer=RelationProposerClass.RULE, proposer_ref="rule:alpha", **shared)
    right = proposal(proposer=RelationProposerClass.RULE, proposer_ref="rule:beta", **shared)
    assert left.proposal_id == right.proposal_id
    assert canonical_proposal_record_line(left) != canonical_proposal_record_line(right)
    store = store_at(tmp_path)
    store.append_proposal(left)
    with pytest.raises(RelationProposalConflict):
        store.append_proposal(right)


def test_b5d_30_case3_different_rule_version_converges_then_conflicts(tmp_path) -> None:
    shared = dict(attribution=ATTRIBUTION, refs=(cited("m"),), rationale="the release links the two themes",
                  proposer=RelationProposerClass.RULE, proposer_ref="rule:alpha")
    left = proposal(rule_version="1.0.0", **shared)
    right = proposal(rule_version="1.1.0", **shared)
    assert left.proposal_id == right.proposal_id
    assert canonical_proposal_record_line(left) != canonical_proposal_record_line(right)
    store = store_at(tmp_path)
    store.append_proposal(left)
    with pytest.raises(RelationProposalConflict):
        store.append_proposal(right)


def test_b5d_31_case4_a_materially_different_citation_set_is_a_different_proposal(tmp_path) -> None:
    left = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited("m"),))
    right = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited("m"), cited("n")))
    assert left.proposal_id != right.proposal_id
    assert left.identity_payload() != right.identity_payload()
    store = store_at(tmp_path)
    assert store.append_proposal(left).status is AppendStatus.APPENDED
    assert store.append_proposal(right).status is AppendStatus.APPENDED
    assert store.counts()["proposals"] == 2


def test_b5d_32_case5_a_materially_different_rationale_is_a_different_proposal(tmp_path) -> None:
    left = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited("m"),),
                        rationale="the release says the tariff raises input costs")
    right = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited("m"),),
                         rationale="the release says the subsidy lowers input costs")
    assert left.proposal_id != right.proposal_id
    store = store_at(tmp_path)
    store.append_proposal(left)
    store.append_proposal(right)
    assert store.counts()["proposals"] == 2


def test_b5d_33_a_byte_identical_replay_is_idempotent_not_a_conflict(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = sourced()
    assert store.append_proposal(candidate).status is AppendStatus.APPENDED
    assert store.append_proposal(candidate).status is AppendStatus.ALREADY_PRESENT
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    assert store.append_decision(decision).status is AppendStatus.APPENDED
    assert store.append_decision(decision).status is AppendStatus.ALREADY_PRESENT
    assert store.counts() == {"proposals": 1, "decisions": 1}


def test_b5d_34_a_different_created_at_converges_then_conflicts(tmp_path) -> None:
    """決定論的 replay は created_at を入力から導かねばならない。現在時刻で埋めると CONFLICT になる。"""
    left = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited("m"),), at=T0)
    right = candidate_of(RelationProposerClass.RULE, attribution=ATTRIBUTION, refs=(cited("m"),),
                         at=T0 + timedelta(seconds=1))
    assert left.proposal_id == right.proposal_id
    store = store_at(tmp_path)
    store.append_proposal(left)
    with pytest.raises(RelationProposalConflict):
        store.append_proposal(right)


def test_b5d_35_a_refused_conflict_leaves_the_first_provenance_and_the_bytes_untouched(tmp_path) -> None:
    left, right = converging_pair(proposer=RelationProposerClass.LLM)
    store = store_at(tmp_path)
    store.append_proposal(left)
    before = bytes_of(proposal_authority_paths(tmp_path / "data"))
    with pytest.raises(RelationProposalConflict):
        store.append_proposal(right)
    assert bytes_of(proposal_authority_paths(tmp_path / "data")) == before
    stored = store.get_proposal(left.proposal_id)
    assert stored.provenance.proposer_class is RelationProposerClass.RULE
    assert RelationProposalStore.open(tmp_path / "data").counts()["proposals"] == 1


def test_b5d_36_the_check_then_reuse_path_avoids_the_conflict_entirely(tmp_path) -> None:
    """運用契約: 2 番目の producer は append せず、記録済みの提案を使って決定 chain を進める。"""
    left, right = converging_pair(proposer=RelationProposerClass.LLM)
    store = store_at(tmp_path)
    store.append_proposal(left)
    existing = store.get_proposal(right.proposal_id)
    assert existing is not None and existing.proposal_id == right.proposal_id
    decision = accept(existing, AssertionClass.SOURCE_ASSERTED)
    assert store.append_decision(decision).status is AppendStatus.APPENDED
    plan = plan_of(existing, (decision,))
    assert plan.proposal_origin.proposer_class is RelationProposerClass.RULE   # 先に記録された出自が残る


def test_b5d_37_the_b4c_convergence_principle_is_the_same_identity_rule(tmp_path) -> None:
    """B4C も identity から provenance を外して収束させる（差異は producer 層の有無であって identity 規則ではない）。"""
    b3_model = executable_source(PACKAGE_DIR / "proposal_model.py")
    b4c_model = executable_source(PACKAGE_DIR / "discovery_model.py")
    assert "TEMPLATE_PROVENANCE_REF = 'discovery:mechanism_template'" in b4c_model.replace('"', "'")
    assert "rule_version" not in b3_model.split("def identity_payload")[1].split("def ")[0]
    b5c_model = executable_source(PACKAGE_DIR / "relation_proposal_model.py")
    identity = b5c_model.split("def identity_payload")[1].split("def ")[0]
    for token in ("provenance", "created_at", "proposer"):
        assert token not in identity, token


# ================================================================ §5 人間の決定の敵対的集合


def test_b5d_38_no_decision_stays_open_and_produces_no_plan() -> None:
    candidate = causal()
    assert derive_relation_proposal_status(candidate, ()) is RelationProposalStatus.OPEN
    assert refuses("PROPOSAL_NOT_ACCEPTED", candidate, ()).detail == "OPEN"


def test_b5d_39_a_single_accept_resolves_and_plans() -> None:
    candidate = causal()
    decision = accept(candidate, AssertionClass.HUMAN_ASSERTED)
    assert derive_relation_proposal_status(candidate, (decision,)) is RelationProposalStatus.ACCEPTED
    assert plan_of(candidate, (decision,)).decision_origin.decision_id == decision.decision_id


def test_b5d_40_a_reject_produces_no_plan() -> None:
    candidate = causal()
    decision = decide(candidate, RelationDecisionKind.REJECT, reason="the cited release says the opposite")
    assert derive_relation_proposal_status(candidate, (decision,)) is RelationProposalStatus.REJECTED
    assert refuses("PROPOSAL_NOT_ACCEPTED", candidate, (decision,)).detail == "REJECTED"


def test_b5d_41_a_defer_produces_no_plan() -> None:
    candidate = causal()
    decision = decide(candidate, RelationDecisionKind.DEFER, reason="needs a second reader")
    assert derive_relation_proposal_status(candidate, (decision,)) is RelationProposalStatus.OPEN_DEFERRED
    assert refuses("PROPOSAL_NOT_ACCEPTED", candidate, (decision,)).detail == "OPEN_DEFERRED"


def test_b5d_42_reject_then_accept_resolves_to_the_chain_terminal(tmp_path) -> None:
    candidate = causal()
    first = decide(candidate, RelationDecisionKind.REJECT, reason="insufficient at first reading")
    second = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=DECIDED_AT + timedelta(hours=1),
                    supersedes=first.decision_id, reason="accepted after the second reading")
    chain = (first, second)
    assert derive_relation_proposal_status(candidate, chain) is RelationProposalStatus.ACCEPTED
    assert plan_of(candidate, chain, at=PLANNED_AT + timedelta(hours=1)).decision_origin.decision_id == second.decision_id
    recorded(store_at(tmp_path), candidate, chain)


def test_b5d_43_defer_then_accept_resolves_to_the_chain_terminal() -> None:
    candidate = causal()
    first = decide(candidate, RelationDecisionKind.DEFER, reason="needs a second reader")
    second = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=DECIDED_AT + timedelta(hours=1),
                    supersedes=first.decision_id, reason="second reader agreed")
    assert derive_relation_proposal_status(candidate, (first, second)) is RelationProposalStatus.ACCEPTED


def test_b5d_44_accept_then_reject_produces_no_plan_from_the_stale_accept() -> None:
    candidate = causal()
    first = accept(candidate, AssertionClass.HUMAN_ASSERTED)
    second = decide(candidate, RelationDecisionKind.REJECT, at=DECIDED_AT + timedelta(hours=1),
                    supersedes=first.decision_id, reason="withdrawn after the source was re-read")
    assert derive_relation_proposal_status(candidate, (first, second)) is RelationProposalStatus.REJECTED
    assert refuses("PROPOSAL_NOT_ACCEPTED", candidate, (first, second)).detail == "REJECTED"


def test_b5d_45_a_forked_decision_history_is_unresolved_and_plans_nothing() -> None:
    candidate = causal()
    first = accept(candidate, AssertionClass.HUMAN_ASSERTED)
    left = decide(candidate, RelationDecisionKind.REJECT, at=DECIDED_AT + timedelta(hours=1),
                  supersedes=first.decision_id, reason="branch one")
    right = decide(candidate, RelationDecisionKind.DEFER, at=DECIDED_AT + timedelta(hours=2),
                   supersedes=first.decision_id, reason="branch two")
    chain = (first, left, right)
    assert resolve_active_relation_decision(candidate.proposal_id, chain).diagnostics == ("FORK",)
    assert derive_relation_proposal_status(candidate, chain) is RelationProposalStatus.OPEN_UNRESOLVED
    refuses("PROPOSAL_NOT_ACCEPTED", candidate, chain)


def test_b5d_46_multiple_genesis_decisions_are_unresolved() -> None:
    candidate = causal()
    first = accept(candidate, AssertionClass.HUMAN_ASSERTED, reason="first genesis")
    second = accept(candidate, AssertionClass.HUMAN_ASSERTED, reason="second genesis")
    chain = (first, second)
    assert "MULTIPLE_STARTS" in resolve_active_relation_decision(candidate.proposal_id, chain).diagnostics
    assert derive_relation_proposal_status(candidate, chain) is RelationProposalStatus.OPEN_UNRESOLVED


def test_b5d_47_a_dangling_predecessor_is_an_invalid_history(tmp_path) -> None:
    candidate = causal()
    orphan = accept(candidate, AssertionClass.HUMAN_ASSERTED, supersedes="threldec_" + "0" * 24)
    resolution = resolve_active_relation_decision(candidate.proposal_id, (orphan,))
    assert resolution.status is DecisionResolutionStatus.INVALID and resolution.diagnostics == ("DANGLING_PREDECESSOR",)
    assert derive_relation_proposal_status(candidate, (orphan,)) is RelationProposalStatus.INVALID_DECISION_HISTORY
    store = store_at(tmp_path)
    store.append_proposal(candidate)
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(orphan)
    assert info.value.code == "MISSING_PREDECESSOR"


def test_b5d_48_a_predecessor_belonging_to_another_proposal_is_an_invalid_history(tmp_path) -> None:
    mine, other = causal(), causal(rationale="a different candidate entirely")
    foreign = accept(other, AssertionClass.HUMAN_ASSERTED, reason="decided the other candidate")
    crossed = accept(mine, AssertionClass.HUMAN_ASSERTED, at=DECIDED_AT + timedelta(hours=1),
                     supersedes=foreign.decision_id, reason="wrong predecessor")
    resolution = resolve_active_relation_decision(mine.proposal_id, (foreign, crossed))
    assert resolution.diagnostics == ("WRONG_PROPOSAL_PREDECESSOR",)
    assert derive_relation_proposal_status(mine, (foreign, crossed)) is RelationProposalStatus.INVALID_DECISION_HISTORY
    store = store_at(tmp_path)
    store.append_proposal(mine)
    store.append_proposal(other)
    store.append_decision(foreign)
    with pytest.raises(RelationProposalAppendRejected) as info:
        store.append_decision(crossed)
    assert info.value.code == "WRONG_PROPOSAL_PREDECESSOR"


class _DuckDecision:
    """content id では cycle を構成できないため、resolver 単体へ duck-typed な循環入力を与える。"""

    def __init__(self, decision_id: str, proposal_id: str, supersedes: str) -> None:
        self.decision_id, self.proposal_id, self.supersedes_decision_id = decision_id, proposal_id, supersedes
        self.decision = RelationDecisionKind.ACCEPT


def test_b5d_49_a_cyclic_decision_history_is_invalid() -> None:
    candidate = causal()
    seed = accept(candidate, AssertionClass.HUMAN_ASSERTED, reason="seed")
    import dataclasses
    from src.intelligence.theme_intelligence.relation_proposal_model import RelationProposalError
    with pytest.raises(RelationProposalError) as info:                 # id を偽らなければ cycle は作れない
        dataclasses.replace(seed, decision_id="threldec_" + "b" * 24)
    assert info.value.code == "INVALID_RECORD_ID"
    left = _DuckDecision("threldec_" + "1" * 24, candidate.proposal_id, "threldec_" + "2" * 24)
    right = _DuckDecision("threldec_" + "2" * 24, candidate.proposal_id, "threldec_" + "1" * 24)
    resolution = resolve_active_relation_decision(candidate.proposal_id, (left, right))
    assert resolution.status is DecisionResolutionStatus.INVALID and resolution.diagnostics == ("CYCLE",)
    assert derive_relation_proposal_status(candidate, (left, right)) is RelationProposalStatus.INVALID_DECISION_HISTORY


@pytest.mark.parametrize("seed", DEEP_SEEDS)
def test_b5d_50_physical_order_never_decides_the_winner(seed) -> None:
    """latest-wins は無い。物理順を混ぜても status と plan の bytes は不変。"""
    candidate = causal()
    first = decide(candidate, RelationDecisionKind.DEFER, reason="first")
    second = decide(candidate, RelationDecisionKind.REJECT, at=DECIDED_AT + timedelta(hours=1),
                    supersedes=first.decision_id, reason="second")
    third = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=DECIDED_AT + timedelta(hours=2),
                   supersedes=second.decision_id, reason="third")
    shuffled = [first, second, third]
    random.Random(seed).shuffle(shuffled)
    assert derive_relation_proposal_status(candidate, tuple(shuffled)) is RelationProposalStatus.ACCEPTED
    plan = plan_of(candidate, tuple(shuffled), at=PLANNED_AT + timedelta(hours=2))
    assert plan.decision_origin.decision_id == third.decision_id
    assert plan.canonical_line() == plan_of(candidate, (first, second, third),
                                            at=PLANNED_AT + timedelta(hours=2)).canonical_line()


def test_b5d_51_a_later_recorded_accept_outside_the_chain_terminal_does_not_win() -> None:
    """recorded_at が最も新しい ACCEPT でも、chain の終端でなければ勝たない。"""
    candidate = causal()
    first = decide(candidate, RelationDecisionKind.DEFER, reason="first")
    terminal = decide(candidate, RelationDecisionKind.REJECT, at=DECIDED_AT + timedelta(hours=1),
                      supersedes=first.decision_id, reason="terminal reject")
    stray = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=DECIDED_AT + timedelta(days=9),
                   reason="late but not in the chain")
    chain = (first, terminal, stray)
    assert derive_relation_proposal_status(candidate, chain) is RelationProposalStatus.OPEN_UNRESOLVED
    refuses("PROPOSAL_NOT_ACCEPTED", candidate, chain, at=PLANNED_AT + timedelta(days=9))


# ================================================================ §6 訂正と B5B governance の相互作用


def correction(existing, *, rationale="revised after the correction notice", **kw) -> RelationProposal:
    return proposal(change_kind=RelationChangeKind.CORRECTION, previous=existing.relation_assertion_id,
                    rationale=rationale, **kw)


def test_b5d_52_a_terminal_correction_plans_with_its_predecessor() -> None:
    existing = b5b_assertion()
    candidate = correction(existing)
    plan = plan_of(candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),),
                   existing=authority_edges(existing))
    assert plan.change_kind is RelationChangeKind.CORRECTION
    assert plan.previous_assertion_id == existing.relation_assertion_id
    assert plan.edge_key == existing.edge_key


def test_b5d_53_a_correction_of_an_unknown_assertion_is_refused() -> None:
    candidate = proposal(change_kind=RelationChangeKind.CORRECTION, previous=MISSING_ASSERTION_ID,
                         rationale="revised after the correction notice")
    refuses("PREDECESSOR_NOT_FOUND", candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),),
            existing=authority_edges(b5b_assertion()))


def test_b5d_54_a_correction_pointing_at_another_edge_is_refused() -> None:
    other_edge = b5b_assertion(source=B, target=C)
    candidate = correction(other_edge)
    refuses("PREDECESSOR_WRONG_EDGE", candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),),
            existing=authority_edges(other_edge))


def test_b5d_55_a_correction_of_a_non_terminal_assertion_is_refused() -> None:
    first = b5b_assertion()
    second = b5b_assertion(rationale="already revised once", previous=first.relation_assertion_id,
                           at=T0 + timedelta(hours=1))
    candidate = correction(first)
    refuses("PREDECESSOR_NOT_TERMINAL", candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),),
            existing=authority_edges(first, second))


def test_b5d_56_a_correction_that_repeats_the_authoritative_semantics_is_refused() -> None:
    existing = b5b_assertion()
    candidate = correction(existing, rationale=existing.rationale)
    refuses("RELATION_ALREADY_AUTHORITATIVE", candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),),
            existing=authority_edges(existing))


def test_b5d_57_a_new_relation_on_a_started_edge_is_refused() -> None:
    existing = b5b_assertion()
    candidate = proposal(rationale="a different reading of the same edge")
    refuses("EDGE_ALREADY_STARTED", candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),),
            existing=authority_edges(existing))
    same = proposal(rationale=existing.rationale)
    refuses("RELATION_ALREADY_AUTHORITATIVE", same, (accept(same, AssertionClass.HUMAN_ASSERTED),),
            existing=authority_edges(existing))


def test_b5d_58_an_accept_alone_never_restores_a_retracted_relation() -> None:
    """撤回された関係は governance でのみ復帰する。ACCEPT だけで自動 RESTORE されない。"""
    existing = b5b_assertion()
    edges = authority_edges(existing, retracted_events=(retraction(existing),))
    assert edges[0].edge_state.value == "RETRACTED"
    for candidate in (proposal(rationale="a different reading of the same edge"), correction(existing)):
        refuses("RELATION_RETRACTED_REQUIRES_GOVERNANCE", candidate,
                (accept(candidate, AssertionClass.HUMAN_ASSERTED),), existing=edges)


def test_b5d_59_a_restored_relation_accepts_a_correction_again() -> None:
    existing = b5b_assertion()
    withdrawal = retraction(existing)
    reinstated = restoration(existing, previous=withdrawal.event_id)
    edges = authority_edges(existing, retracted_events=(withdrawal, reinstated))
    assert edges[0].edge_state.value == "ACTIVE"
    candidate = correction(existing)
    plan = plan_of(candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),), existing=edges)
    assert plan.previous_assertion_id == existing.relation_assertion_id


@pytest.mark.parametrize("state,annotation", [(EndpointState.SUPERSEDED, "ENDPOINT_SUPERSEDED:SOURCE"),
                                              (EndpointState.RETIRED, "ENDPOINT_RETIRED:SOURCE")])
def test_b5d_60_61_superseded_and_retired_endpoints_plan_with_an_annotation(state, annotation) -> None:
    candidate = proposal()
    endpoint = lookup(A, B, C, retired=(A,) if state is EndpointState.RETIRED else (),
                      superseded=(A,) if state is EndpointState.SUPERSEDED else ())
    plan = plan_of(candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),), endpoint=endpoint)
    assert plan.source_endpoint is state and annotation in plan.diagnostics


def test_b5d_62_an_unknown_or_future_endpoint_is_refused() -> None:
    candidate = proposal()
    decisions = (accept(candidate, AssertionClass.HUMAN_ASSERTED),)
    unknown = endpoint_lookup_from_roots({B: T0})
    assert refuses("ENDPOINT_NOT_AVAILABLE", candidate, decisions, endpoint=unknown).detail == "SOURCE:UNKNOWN_ROOT"
    later = endpoint_lookup_from_roots({A: T0 + timedelta(days=30), B: T0})
    assert refuses("ENDPOINT_NOT_AVAILABLE", candidate, decisions,
                   endpoint=later).detail == "SOURCE:NOT_CREATED_YET"


def test_b5d_63_a_historical_endpoint_resolves_at_the_plan_time() -> None:
    candidate = proposal()
    endpoint = endpoint_lookup_from_roots({A: T0 - timedelta(days=400), B: T0 - timedelta(days=400)})
    plan = plan_of(candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),), endpoint=endpoint)
    assert plan.source_endpoint is EndpointState.EXISTS_AT_CUTOFF
    assert plan.target_endpoint is EndpointState.EXISTS_AT_CUTOFF


# ================================================================ §10 PIT / replay / 決定論


def test_b5d_64_the_plan_time_may_equal_the_proposal_and_decision_time() -> None:
    candidate = proposal(at=T0)
    decision = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=T0)
    plan = plan_of(candidate, (decision,), at=T0)
    assert plan.recorded_at == T0


def test_b5d_65_one_microsecond_before_the_proposal_or_decision_is_refused() -> None:
    candidate = proposal(at=T0)
    early = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=T0)
    refuses("PLAN_BEFORE_PROPOSAL", candidate, (early,), at=T0 - timedelta(microseconds=1))
    late = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=T0 + timedelta(days=1))
    refuses("PLAN_BEFORE_DECISION", candidate, (late,), at=T0 + timedelta(days=1) - timedelta(microseconds=1))


def test_b5d_66_a_future_proposal_cannot_be_planned_in_the_past() -> None:
    candidate = proposal(at=T0 + timedelta(days=30))
    decision = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=T0 + timedelta(days=30))
    refuses("PLAN_BEFORE_PROPOSAL", candidate, (decision,), at=T0)


def test_b5d_67_a_future_endpoint_is_excluded_at_the_plan_time() -> None:
    candidate = proposal(at=T0)
    decision = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=T0)
    endpoint = endpoint_lookup_from_roots({A: T0, B: T0 + timedelta(microseconds=1)})
    assert refuses("ENDPOINT_NOT_AVAILABLE", candidate, (decision,), endpoint=endpoint,
                   at=T0).detail == "TARGET:NOT_CREATED_YET"
    exact = endpoint_lookup_from_roots({A: T0, B: T0})
    assert plan_of(candidate, (decision,), endpoint=exact, at=T0).target_endpoint is EndpointState.EXISTS_AT_CUTOFF


def test_b5d_68_evidence_time_never_exceeds_the_plan_time_by_construction() -> None:
    """model が `evidence_time <= created_at` を、bridge が `plan >= created_at` を強制するため、
    `PLAN_BEFORE_EVIDENCE_TIME` は防御的分岐として到達しない（B5C contract §13 と同じ事実）。"""
    candidate = causal(refs=(cited("p", at=T0),), at=T0)
    decision = accept(candidate, AssertionClass.HUMAN_ASSERTED, at=T0)
    plan = plan_of(candidate, (decision,), at=T0)
    assert all(item.evidence_time <= plan.recorded_at for item in plan.evidence_refs)
    assert "PLAN_BEFORE_EVIDENCE_TIME" in executable_source(PACKAGE_DIR / "relation_proposal_bridge.py")


@pytest.mark.parametrize("seed", DEEP_SEEDS)
def test_b5d_69_shuffled_decision_input_yields_identical_plan_bytes(seed) -> None:
    candidate = sourced()
    chain = [decide(candidate, RelationDecisionKind.DEFER, reason="hold")]
    for index in range(1, 4):
        chain.append(decide(candidate, RelationDecisionKind.DEFER, at=DECIDED_AT + timedelta(hours=index),
                            supersedes=chain[-1].decision_id, reason=f"hold {index}"))
    chain.append(accept(candidate, AssertionClass.SOURCE_ASSERTED, at=DECIDED_AT + timedelta(hours=4),
                        supersedes=chain[-1].decision_id, reason="accepted at last"))
    ordered = plan_of(candidate, tuple(chain), at=PLANNED_AT + timedelta(hours=4)).canonical_line()
    shuffled = list(chain)
    random.Random(seed).shuffle(shuffled)
    assert plan_of(candidate, tuple(shuffled), at=PLANNED_AT + timedelta(hours=4)).canonical_line() == ordered


def test_b5d_70_canonical_proposal_and_decision_bytes_survive_a_round_trip() -> None:
    candidate = sourced()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    for record, rebuilt in ((candidate, RelationProposal.from_dict(candidate.as_dict())),
                            (decision, RelationProposalDecision.from_dict(decision.as_dict()))):
        assert canonical_proposal_record_line(record) == canonical_proposal_record_line(rebuilt)
    assert canonical_proposal_record_line(candidate).endswith("\n")


def test_b5d_71_plan_bytes_are_stable_across_a_store_reload(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = sourced()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    recorded(store, candidate, (decision,))
    first = plan_of(candidate, (decision,)).canonical_line()
    for _ in range(3):
        reopened = RelationProposalStore.open(tmp_path / "data")
        stored = reopened.get_proposal(candidate.proposal_id)
        assert plan_of(stored, reopened.decisions()).canonical_line() == first
    assert json.loads(first)["plan_version"] == RELATION_PLAN_VERSION


def test_b5d_72_no_current_clock_and_no_randomness_in_the_b5_runtime() -> None:
    for name in B5_RUNTIME_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in (".now(", "utcnow", "time.time", "random.", "secrets.", "uuid"):
            assert token not in source, f"{name}:{token}"


# ================================================================ §11 store 安全性の再検証


def test_b5d_73_both_authorities_are_idempotent_on_byte_identical_appends(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    decision = accept(candidate, AssertionClass.HUMAN_ASSERTED)
    store.append_proposal(candidate)
    store.append_decision(decision)
    sizes = {name: path.stat().st_size for name, path in store.paths.items()}
    assert store.append_proposal(candidate).status is AppendStatus.ALREADY_PRESENT
    assert store.append_decision(decision).status is AppendStatus.ALREADY_PRESENT
    assert {name: path.stat().st_size for name, path in store.paths.items()} == sizes


def test_b5d_74_a_differing_decision_under_the_same_id_is_impossible_by_content_id(tmp_path) -> None:
    """decision も content id なので、内容が違えば id が違う。同 id ＋ 異 bytes は外部改変でしか起きない。"""
    candidate = causal()
    first = accept(candidate, AssertionClass.HUMAN_ASSERTED, reason="one")
    second = accept(candidate, AssertionClass.HUMAN_ASSERTED, reason="two")
    assert first.decision_id != second.decision_id
    store = store_at(tmp_path)
    recorded(store, candidate, ())
    store.append_decision(first)
    forged = json.loads(canonical_proposal_record_line(first))
    forged["recorded_at"] = "2026-09-25T00:00:00Z"
    path = store.paths["decisions"]
    path.write_bytes(json.dumps(forged, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n")
    with pytest.raises(RelationProposalStoreCorrupt) as info:
        RelationProposalStore.open(tmp_path / "data")
    assert info.value.code in ("INVALID_RECORD", "NON_CANONICAL_LINE"), info.value.code


@pytest.mark.parametrize("payload,reason", [
    (b'{"schema_version":"theme_relation_proposal:0.1.0"}', "INVALID_RECORD"),
    (b"not json at all\n", "MALFORMED_JSON"),
    (b'{"schema_version":"theme_relation_unknown:9.9.9"}\n', "UNSUPPORTED_SCHEMA_VERSION"),
    (b'[1,2,3]\n', "NOT_AN_OBJECT"),
    (b"\n", "BLANK_LINE"),
])
def test_b5d_75_79_corrupt_proposal_bytes_fail_closed(tmp_path, payload, reason) -> None:
    store = store_at(tmp_path)
    store.paths["proposals"].write_bytes(payload)
    with pytest.raises(RelationProposalStoreCorrupt) as info:
        RelationProposalStore.open(tmp_path / "data")
    assert info.value.code == ("TRUNCATED_FINAL_LINE" if not payload.endswith(b"\n") else reason), info.value.code


def test_b5d_80_a_wrong_content_id_is_rejected_on_load(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    store.append_proposal(candidate)
    tampered = json.loads(canonical_proposal_record_line(candidate))
    tampered["proposal_id"] = "threlprop_" + "0" * 24
    store.paths["proposals"].write_bytes(json.dumps(tampered, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n")
    with pytest.raises(RelationProposalStoreCorrupt) as info:
        RelationProposalStore.open(tmp_path / "data")
    assert info.value.code == "INVALID_RECORD"


def test_b5d_81_an_external_append_is_detected_before_the_next_write(tmp_path) -> None:
    store = store_at(tmp_path)
    candidate = causal()
    store.append_proposal(candidate)
    with store.paths["proposals"].open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(RelationProposalConcurrentModification) as info:
        store.append_proposal(causal(rationale="a second candidate"))
    assert info.value.code == "CONCURRENT_MODIFICATION"


def test_b5d_82_a_read_only_store_refuses_both_appends(tmp_path) -> None:
    store_at(tmp_path)
    reader = RelationProposalStore.open(tmp_path / "data", read_only=True)
    candidate = causal()
    for call in (lambda: reader.append_proposal(candidate),
                 lambda: reader.append_decision(accept(candidate, AssertionClass.HUMAN_ASSERTED))):
        with pytest.raises(RelationProposalAppendRejected) as info:
            call()
        assert info.value.code == "READ_ONLY"


def test_b5d_83_a_failed_open_repairs_nothing_and_migrates_nothing(tmp_path) -> None:
    store = store_at(tmp_path)
    store.append_proposal(causal())
    broken = store.paths["proposals"].read_bytes() + b"{partial"
    store.paths["proposals"].write_bytes(broken)
    for _ in range(2):
        with pytest.raises(RelationProposalStoreCorrupt):
            RelationProposalStore.open(tmp_path / "data")
        assert store.paths["proposals"].read_bytes() == broken
    source = executable_source(PACKAGE_DIR / "relation_proposal_store.py")
    for token in ("migrat", "repair", "os.replace", "truncate(", "unlink("):
        assert token not in source, token
    assert "fsync" in source


def test_b5d_84_an_empty_data_root_is_refused(tmp_path) -> None:
    for value in ("", "   "):
        with pytest.raises(RelationProposalAppendRejected) as info:
            RelationProposalStore.open(value)
        assert info.value.code == "DATA_ROOT_REQUIRED"


# ================================================================ §12 Foundation / B5B authority の非改変


def full_chain_on(data_root: Path) -> None:
    """B5C の鎖を 1 本通す（提案 → ACCEPT → plan）。plan は永続化しない。"""
    store = RelationProposalStore.initialize(data_root)
    candidate = sourced()
    decision = accept(candidate, AssertionClass.SOURCE_ASSERTED)
    store.append_proposal(candidate)
    store.append_decision(decision)
    plan_of(candidate, (decision,))


def test_b5d_85_the_foundation_authorities_are_byte_identical_across_the_chain(tmp_path) -> None:
    from tests.intelligence.theme_foundation_fixtures import authority_bytes, build_world, resolution_digest
    world = build_world(tmp_path / "data", stop_after="accepted")
    before = authority_bytes(world.data_root)
    digest_before = [resolution_digest(world.resolve(key, "accepted")) for key in ("A", "B")]
    full_chain_on(world.data_root)
    assert authority_bytes(world.data_root) == before
    assert [resolution_digest(world.resolve(key, "accepted")) for key in ("A", "B")] == digest_before
    assert len(before) == 5


def test_b5d_86_the_relation_authorities_are_byte_identical_across_the_chain(tmp_path) -> None:
    from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
    ThemeRelationStore.initialize(tmp_path / "data")
    existing = b5b_assertion()
    ThemeRelationStore.open(tmp_path / "data").append_assertion(existing)
    before = bytes_of(relation_authority_paths(tmp_path / "data"))
    full_chain_on(tmp_path / "data")
    candidate = correction(existing)
    plan_of(candidate, (accept(candidate, AssertionClass.HUMAN_ASSERTED),), existing=authority_edges(existing))
    assert bytes_of(relation_authority_paths(tmp_path / "data")) == before
    assert ThemeRelationStore.open(tmp_path / "data").counts() == {"assertions": 1, "governance": 0}


def test_b5d_87_only_the_two_proposal_authorities_grow(tmp_path) -> None:
    from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
    ThemeRelationStore.initialize(tmp_path / "data")
    sizes_before = {p.name: p.stat().st_size for p in (tmp_path / "data" / "theme_intelligence").iterdir()}
    full_chain_on(tmp_path / "data")
    sizes_after = {p.name: p.stat().st_size for p in (tmp_path / "data" / "theme_intelligence").iterdir()}
    grew = {name for name, size in sizes_after.items() if size != sizes_before.get(name, 0)}
    assert grew == {"relation_proposals.jsonl", "relation_proposal_decisions.jsonl"}


# ================================================================ §14 凍結面の guard


def test_b5d_88_the_b5_runtime_module_set_is_unchanged() -> None:
    present = sorted(p.stem for p in PACKAGE_DIR.glob("relation*.py"))
    assert present == sorted(B5_RUNTIME_MODULES)


def test_b5d_89_the_b5c_modules_never_import_the_b5b_authority_store() -> None:
    for name in ("relation_proposal_model", "relation_proposal_resolution", "relation_proposal_bridge",
                 "relation_proposal_store"):
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        assert "relation_store" not in source, name
        assert "ThemeRelationStore" not in source, name


def test_b5d_90_this_gate_writes_only_under_the_pytest_tmp_root() -> None:
    """本 file が使う filesystem 面は tmp_path と repo の読み取りだけである。"""
    source = (Path(__file__)).read_text(encoding="utf-8")
    forbidden = ("data" + chr(47) + "vnext", "INTELLIGENCE" + "_DATA_ROOT", "investment" + "_journal",
                 "theme" + "_learning", "D" + ":" + chr(92), "C" + ":" + chr(92))
    for token in forbidden:
        assert token not in source, token
    assert source.count("tmp" + "_path") > 20
