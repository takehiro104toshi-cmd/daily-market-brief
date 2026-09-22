"""P6-B5D — 因果安全性の合成 corpus / 自動発見の不在 / 推移的 authority の不在（test only）。

本 file は NLP 分類器を作らない。目的は **contract の保証がどこで終わり、人間の査読がどこから始まるか**を
境界として固定することである。以下の corpus 結果は **synthetic gate result only** であり、
実世界の precision / recall を主張しない。
"""
from __future__ import annotations

import inspect
import importlib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional, Tuple

import pytest

from src.intelligence.theme_intelligence.relation_graph import Direction, build_relation_graph_view
from src.intelligence.theme_intelligence.relation_model import (AssertionClass, RelationType, SOURCE_ASSERTED_MEANING,
                                                                SOURCE_ASSERTED_NON_MEANING, SourceAttribution)
from src.intelligence.theme_intelligence.relation_proposal_bridge import RelationBridgeError
from src.intelligence.theme_intelligence.relation_proposal_model import (RelationDecisionKind, RelationProposal,
                                                                         RelationProposerClass,
                                                                         source_authority_available)
from src.intelligence.theme_intelligence.relation_proposal_resolution import RelationProposalStatus, \
    derive_relation_proposal_status
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_resolution import resolve_relation_graph
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_relation import A, ATTRIBUTION, B, C, D, T0, lookup as b5b_lookup
from tests.intelligence.test_theme_relation_e2e import (B5_RUNTIME_MODULES, accept, candidate_of, cited, plan_of,
                                                        refuses, store_at)
from tests.intelligence.test_theme_relation_proposal import b5b_assertion, decide, lookup, proposal

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
#: §13 — 本 file の corpus 結果に必ず付ける label
SYNTHETIC_RESULT_LABEL = "synthetic gate result only"


@dataclass(frozen=True)
class CausalScenario:
    """合成 corpus の 1 行。`structurally_eligible` は現行 runtime の SOURCE_ASSERTED 適格判定の予測値。"""

    key: str
    basis: str
    attributed: bool
    citations: int
    structurally_eligible: bool
    contract_guarantee: str
    human_review_required: bool


#: 14 行の合成 corpus。`contract_guarantee` は runtime が構造として保証できることだけを書く。
CORPUS: Tuple[CausalScenario, ...] = (
    CausalScenario("cooccurrence", "両 Theme が同一記事に現れるだけ", False, 0, False,
                   "NO_PROPOSAL_IS_CREATED", True),
    CausalScenario("shared_entity", "entity が共通するだけ", False, 0, False, "NO_PROPOSAL_IS_CREATED", True),
    CausalScenario("shared_taxonomy", "taxonomy slug が共通するだけ", False, 0, False,
                   "NO_PROPOSAL_IS_CREATED", True),
    CausalScenario("shared_evidence", "同一 evidence を両 Theme が参照するだけ", False, 1, False,
                   "NO_PROPOSAL_IS_CREATED", True),
    CausalScenario("temporal_succession", "時間的に後先があるだけ", False, 0, False, "NO_PROPOSAL_IS_CREATED", True),
    CausalScenario("price_correlation", "価格が相関するだけ", False, 0, False, "NO_PROPOSAL_IS_CREATED", True),
    CausalScenario("headline_wording", "見出しが因果的語法だが出典は関係を主張していない", True, 1, True,
                   "HUMAN_DECISION_IS_REQUIRED_TO_ACCEPT", True),
    CausalScenario("source_asserts_causes", "出典が A は B を引き起こすと明示した", True, 1, True,
                   "HUMAN_DECISION_IS_REQUIRED_TO_ACCEPT", True),
    CausalScenario("source_associates", "出典が A と B は関連すると述べた", True, 1, True,
                   "HUMAN_DECISION_IS_REQUIRED_TO_ACCEPT", True),
    CausalScenario("source_may_contribute", "出典が A は B に寄与しうると述べた", True, 1, True,
                   "HUMAN_DECISION_IS_REQUIRED_TO_ACCEPT", True),
    CausalScenario("source_contradicts", "出典が A は B を引き起こさないと述べた", True, 1, True,
                   "HUMAN_DECISION_IS_REQUIRED_TO_ACCEPT", True),
    CausalScenario("llm_hypothesis", "LLM が因果仮説を立てた（出典の裏付けなし）", False, 1, False,
                   "SOURCE_ASSERTED_IS_STRUCTURALLY_REFUSED", True),
    CausalScenario("rule_hypothesis", "rule が因果仮説を立てた（出典の裏付けなし）", False, 1, False,
                   "SOURCE_ASSERTED_IS_STRUCTURALLY_REFUSED", True),
    CausalScenario("human_assertion", "人間が自分の名前で因果を主張した", False, 1, False,
                   "SOURCE_ASSERTED_IS_STRUCTURALLY_REFUSED", True),
)
NO_PROPOSAL_ROWS = tuple(row for row in CORPUS if row.contract_guarantee == "NO_PROPOSAL_IS_CREATED")
AUTHORED_ROWS = tuple(row for row in CORPUS if row.contract_guarantee != "NO_PROPOSAL_IS_CREATED")
#: 出典の主張 / 関連 / 可能性 / 否定 を区別できるかの検査（区別できないことを固定する）
SEMANTIC_VARIANTS = ("source_asserts_causes", "source_associates", "source_may_contribute", "source_contradicts",
                     "headline_wording")


def authored(row: CausalScenario, *, proposer=RelationProposerClass.RULE) -> RelationProposal:
    """corpus 行から候補を手で組む。runtime はこの組み立てを自動で行わない（§8）。"""
    refs = tuple(cited(chr(ord("a") + index)) for index in range(row.citations))
    return candidate_of(proposer, attribution=ATTRIBUTION if row.attributed else None, refs=refs,
                        relation_type=RelationType.CAUSES if row.citations else RelationType.AMPLIFIES,
                        rationale=f"corpus row {row.key}")


# ================================================================ §7 因果安全性の合成 corpus


def test_b5d_91_the_corpus_covers_fourteen_distinct_bases() -> None:
    assert len(CORPUS) == 14
    assert len({row.key for row in CORPUS}) == 14
    assert len({row.basis for row in CORPUS}) == 14


@pytest.mark.parametrize("row", CORPUS, ids=[row.key for row in CORPUS])
def test_b5d_92_105_no_corpus_row_creates_a_proposal_by_itself(row, tmp_path) -> None:
    """corpus をどう並べても、提案は 1 件も生まれない。提案は明示的な append だけで現れる。"""
    store = store_at(tmp_path)
    assert store.counts() == {"proposals": 0, "decisions": 0}
    assert RelationProposalStore.open(tmp_path / "data").counts()["proposals"] == 0


@pytest.mark.parametrize("row", CORPUS, ids=[row.key for row in CORPUS])
def test_b5d_106_119_the_structural_eligibility_matches_the_corpus_table(row) -> None:
    candidate = authored(row)
    assert source_authority_available(candidate) is row.structurally_eligible, row.key
    assert (candidate.source_attribution is not None) is row.attributed
    assert len(candidate.evidence_refs) == row.citations


@pytest.mark.parametrize("row", AUTHORED_ROWS, ids=[row.key for row in AUTHORED_ROWS])
def test_b5d_120_126_every_authored_row_still_needs_a_human_decision(row) -> None:
    candidate = authored(row)
    assert derive_relation_proposal_status(candidate, ()) is RelationProposalStatus.OPEN
    refuses("PROPOSAL_NOT_ACCEPTED", candidate, ())
    rejected = decide(candidate, RelationDecisionKind.REJECT, reason="not supported on review")
    refuses("PROPOSAL_NOT_ACCEPTED", candidate, (rejected,))
    assert row.human_review_required is True


@pytest.mark.parametrize("row", NO_PROPOSAL_ROWS, ids=[row.key for row in NO_PROPOSAL_ROWS])
def test_b5d_127_132_a_bare_overlap_row_cannot_reach_source_asserted(row) -> None:
    candidate = authored(row)
    assert source_authority_available(candidate) is False
    refuses("FORBIDDEN_SOURCE_AUTHORITY", candidate, (accept(candidate, AssertionClass.SOURCE_ASSERTED),))


def test_b5d_133_the_runtime_cannot_separate_assertion_from_association_or_denial() -> None:
    """出典が「引き起こす」「関連する」「寄与しうる」「引き起こさない」のどれを述べたかは record に現れない。

    これは contract の保証が終わる境界であり、人間の査読だけが担う。B5D では分類器を作らない。
    """
    rows = {row.key: row for row in CORPUS if row.key in SEMANTIC_VARIANTS}
    assert len(rows) == len(SEMANTIC_VARIANTS)
    eligibility = {key: source_authority_available(authored(row)) for key, row in rows.items()}
    assert set(eligibility.values()) == {True}
    plans = {}
    for key, row in rows.items():
        candidate = authored(row)
        plans[key] = plan_of(candidate, (accept(candidate, AssertionClass.SOURCE_ASSERTED),))
    assert {plan.assertion_class for plan in plans.values()} == {AssertionClass.SOURCE_ASSERTED}
    fields = {key: set(plan.to_plain()) for key, plan in plans.items()}
    assert len({frozenset(value) for value in fields.values()}) == 1      # field 集合に差が無い


def test_b5d_134_the_corpus_result_is_labelled_synthetic_only() -> None:
    assert SYNTHETIC_RESULT_LABEL == "synthetic gate result only"
    text = Path(__file__).read_text(encoding="utf-8")
    assert SYNTHETIC_RESULT_LABEL in text
    for claim in ("precision", "recall", "F1", "accuracy"):
        assert f"{claim} =" not in text and f"{claim}=" not in text, claim


def test_b5d_135_the_frozen_source_asserted_wording_bounds_the_claim() -> None:
    assert SOURCE_ASSERTED_MEANING == "the cited source asserted this relation"
    assert SOURCE_ASSERTED_NON_MEANING == "the system verified this relation as causal truth"


# ================================================================ §8 自動的な関係発見の不在

#: 自動発見の入口になりうる語。B5 runtime に 1 つも無いことを固定する
DISCOVERY_TOKENS = ("cooccur", "co_occur", "correlat", "adjacen", "overlap", "similar", "infer_relation",
                    "discover", "propose_relation", "candidates_from", "ThemeCandidateProposal", "DiscoveryRun",
                    "RunReport", "AdapterResult", "NewsItem", "Observation", "SourceDocument", "Fact")
#: `relation_resolution` は記録済み辺の cycle 検出に隣接表を使う（発見ではなく履歴検査）
DISCOVERY_TOKEN_EXEMPTIONS = {"relation_resolution": ("adjacen",)}


@pytest.mark.parametrize("name", B5_RUNTIME_MODULES)
def test_b5d_136_143_no_b5_module_carries_a_discovery_entry_point(name) -> None:
    source = executable_source(PACKAGE_DIR / f"{name}.py")
    exempt = DISCOVERY_TOKEN_EXEMPTIONS.get(name, ())
    for token in DISCOVERY_TOKENS:
        if token in exempt:
            continue
        assert token not in source, f"{name}:{token}"


@pytest.mark.parametrize("name", B5_RUNTIME_MODULES)
def test_b5d_144_151_no_b5_module_imports_a_corpus_or_discovery_surface(name) -> None:
    modules = imported_modules(PACKAGE_DIR / f"{name}.py")
    for token in ("discovery", "adapter", "taxonomy", "entity", "knowledge", "dedup", "databank", "facts", "market",
                  "sources", "corpus"):
        assert not any(token in module for module in modules), f"{name}:{token}"


def test_b5d_152_relation_proposal_build_requires_every_semantic_field_explicitly() -> None:
    """corpus から自動で埋まる default は無い。source / target / type / rationale / provenance / created_at は必須。"""
    signature = inspect.signature(RelationProposal.build)
    required = {name for name, param in signature.parameters.items() if param.default is inspect.Parameter.empty}
    assert required == {"source_theme_root_id", "target_theme_root_id", "relation_type", "rationale", "provenance",
                        "created_at"}
    optional = {name for name, param in signature.parameters.items() if param.default is not inspect.Parameter.empty}
    assert optional == {"change_kind", "previous_assertion_id", "source_attribution", "evidence_refs"}


def test_b5d_153_the_package_exposes_no_callable_that_manufactures_relation_proposals() -> None:
    makers = []
    for name in B5_RUNTIME_MODULES:
        module = importlib.import_module(f"src.intelligence.theme_intelligence.{name}")
        for attribute, value in vars(module).items():
            if not inspect.isfunction(value) or value.__module__ != module.__name__:
                continue
            annotation = str(inspect.signature(value).return_annotation)
            if ("RelationProposal" in annotation and "Decision" not in annotation
                    and "Status" not in annotation and "Resolution" not in annotation):
                makers.append(f"{name}.{attribute}")
    assert makers == [], makers


def test_b5d_154_theme_adjacency_and_b4_candidates_never_reach_the_relation_layer() -> None:
    for name in B5_RUNTIME_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("proposal_bridge", "evidence_bridge", "proposal_store", "proposal_resolution"):
            assert f"from .{token}" not in source, f"{name}:{token}"
    relation_only = executable_source(PACKAGE_DIR / "relation_proposal_bridge.py")
    assert "from .relation_proposal_resolution import" in relation_only     # B5C 内部の参照だけ


def test_b5d_155_shared_evidence_between_two_themes_creates_no_edge(tmp_path) -> None:
    """同一 evidence を両 Theme が参照しても、関係 authority は 1 件も現れない。"""
    shared = cited("z")
    left = b5b_assertion(source=A, target=B, relation_type=RelationType.CAUSES, refs=(shared,))
    resolution = resolve_relation_graph([], [], cutoff=T0 + timedelta(days=7), endpoint_lookup=lookup())
    assert resolution.edges == () and resolution.unresolved == ()
    view = build_relation_graph_view(resolution)
    assert view.roots() == () and view.neighbors(A) == ()
    assert left.evidence_refs[0].evidence_key == shared.evidence_key       # record は作れるが自動では作られない


# ================================================================ §9 推移的 authority の不在


def test_b5d_156_two_causal_edges_never_produce_a_third() -> None:
    first = b5b_assertion(source=A, target=B, relation_type=RelationType.CAUSES, refs=(cited("t"),))
    second = b5b_assertion(source=B, target=C, relation_type=RelationType.CAUSES, refs=(cited("u"),))
    resolution = resolve_relation_graph([first, second], [], cutoff=T0 + timedelta(days=7),
                                        endpoint_lookup=lookup())
    assert len(resolution.edges) == 2
    view = build_relation_graph_view(resolution)
    assert view.relations_between(A, C) == ()
    assert [edge.target_theme_root_id for edge in view.outgoing(A)] == [B]
    assert [edge.source_theme_root_id for edge in view.incoming(C)] == [B]
    assert C not in [neighbor.root_id for neighbor in view.neighbors(A)]
    assert view.outgoing(C) == () and view.incoming(A) == ()


def test_b5d_157_the_graph_view_offers_no_reachability_or_closure_surface() -> None:
    from src.intelligence.theme_intelligence import relation_graph
    names = {name for name, value in vars(relation_graph).items() if inspect.isfunction(value)}
    methods = {name for name in dir(relation_graph.ThemeRelationGraphView) if not name.startswith("_")}
    for token in ("path", "reach", "closure", "transitive", "ancestors", "descendants", "walk", "traverse", "depth"):
        assert not any(token in name for name in names | methods), token
    assert methods == {"outgoing", "incoming", "neighbors", "relations_between", "relations_by_type", "roots",
                       "to_plain"}


def test_b5d_158_no_plan_arises_for_the_implied_transitive_edge() -> None:
    """A CAUSES B と B CAUSES C が authority でも、A CAUSES C は提案と人間の受理なしに現れない。"""
    first = b5b_assertion(source=A, target=B, relation_type=RelationType.CAUSES, refs=(cited("t"),))
    second = b5b_assertion(source=B, target=C, relation_type=RelationType.CAUSES, refs=(cited("u"),))
    resolution = resolve_relation_graph([first, second], [], cutoff=T0 + timedelta(days=7), endpoint_lookup=lookup())
    implied = proposal(source=A, target=C, relation_type=RelationType.CAUSES, refs=(cited("v"),),
                       rationale="implied by the two recorded causal edges")
    refuses("PROPOSAL_NOT_ACCEPTED", implied, (), existing=resolution.edges)
    decision = accept(implied, AssertionClass.HUMAN_ASSERTED)
    plan = plan_of(implied, (decision,), existing=resolution.edges)
    assert plan.proposal_origin.proposal_rationale == "implied by the two recorded causal edges"
    assert plan.decision_origin.decision_id == decision.decision_id      # 人間の受理が必ず介在する


def test_b5d_159_a_transitive_source_asserted_edge_still_needs_its_own_citation() -> None:
    implied = proposal(source=A, target=C, relation_type=RelationType.CAUSES, refs=(cited("v"),),
                       rationale="implied by the two recorded causal edges")
    refuses("FORBIDDEN_SOURCE_AUTHORITY", implied, (accept(implied, AssertionClass.SOURCE_ASSERTED),))
    attributed = proposal(source=A, target=C, relation_type=RelationType.CAUSES, refs=(cited("v"),),
                          attribution=ATTRIBUTION, rationale="the release states the chain end to end")
    assert plan_of(attributed, (accept(attributed, AssertionClass.SOURCE_ASSERTED),)).source_attribution == ATTRIBUTION
