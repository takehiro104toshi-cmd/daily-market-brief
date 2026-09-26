"""P7-A5 — Phase 7 の敵対的 end-to-end 検証（明示の範囲 ／ cutoff → A2 → A3 → A4a → A4b、差分）の matrix E01〜E44。

すべて tmp の合成 data_root 上で、本物の Phase 6 store API で書いた authority から本物の chain を通す（意味の中核を
mock しない）。git に依存する凍結の確認（A1〜A4b・Phase 6）は `test_narrative_intelligence_boundary.py` の A5 節。

契約・監査: `docs/databank/PHASE7_NARRATIVE_INTELLIGENCE_COMPLETION_AUDIT.md`。
"""
from __future__ import annotations

import ast
import builtins
import copy
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.intelligence.narrative_intelligence import render_templates_ja as RT
from src.intelligence.narrative_intelligence import synthesis_model as A1
from src.intelligence.narrative_intelligence import text_renderer as TR
from src.intelligence.narrative_intelligence.input_model import (EvidenceConditionFlag, NarrativeInputError,
                                                                 NarrativeInputRequest)
from src.intelligence.narrative_intelligence.narrative_diff import diff_syntheses
from src.intelligence.narrative_intelligence.pit_assembler import assemble_input_snapshot
from src.intelligence.narrative_intelligence.presentation_model import (DiffCategory, NarrativePresentation,
                                                                        NarrativePresentationError,
                                                                        PresentationSection, SectionKind, Visibility)
from src.intelligence.narrative_intelligence.presentation_planner import plan_presentation
from src.intelligence.narrative_intelligence.rendered_model import NarrativeRenderError
from src.intelligence.narrative_intelligence.synthesis_engine import NarrativeSynthesisError, synthesize
from src.intelligence.narrative_intelligence.text_renderer import render_diff, render_presentation
from src.intelligence.predictions.evaluation_store import evaluations_path
from src.intelligence.predictions.prediction_store import journal_path as predictions_path
from src.intelligence.theme_intelligence.llm_generation_journal import generation_journal_path
from src.intelligence.theme_intelligence.monitoring_store import review_state_path
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as relation_proposal_paths
from src.intelligence.theme_intelligence.relation_store import authority_paths as relation_paths
from src.intelligence.themes.model import ComponentType, DroppedAttachment, MechanismCertainty
from src.intelligence.themes.model import EvidenceKind as K
from src.intelligence.themes.revision import attach_evidence, revise_observation
from src.intelligence.themes.store import ThemeStore
from src.intelligence.themes.store import authority_paths as theme_paths
from tests.intelligence.test_narrative_pit_assembler import (CANARY_EXCERPT, CANARY_NOTE, CANARY_REASON,
                                                             CANARY_SUBJECT, CUT, DOC_P, EARLY, FACT_LATE, FACT_P,
                                                             FACT_UNDATED, INV_P, NEWS_P, OBS_P, P, Q, R, S, STMT_P,
                                                             add_future, day, poison)
from tests.intelligence.test_narrative_synthesis_engine import BARE, CTX, DOC_CTX, build_engine_world
from tests.intelligence.test_prediction_record import imported_modules
from tests.intelligence.test_theme_model import (attachment, component, condition, event, mechanism, observation,
                                                 provenance, root_record, subject)
from tests.intelligence.test_theme_relation_proposal import proposal as relation_candidate
from tests.intelligence.theme_foundation_fixtures import CHECKPOINTS, ROOT_A, build_world

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "narrative_intelligence"
AUDIT = REPO_ROOT / "docs" / "databank" / "PHASE7_NARRATIVE_INTELLIGENCE_COMPLETION_AUDIT.md"
V_SUPPORTED, V_URL, V_JOURNAL, V_SECRET, V_NEWLINE = ("theme_0123456789ABCDEFGHJKMNPQV" + c for c in "01234")
FACT_LATE_Q, FACT_V = "fact_" + "c" * 24, "fact_" + "e" * 24
EVALUATIVE = ("強ま", "弱ま", "改善", "悪化", "加速", "減速", "好転", "強気", "弱気", "楽観", "悲観", "増した", "減った",
              "良くな", "悪くな", "解消された")
RANKING = ("本命", "有力", "第一候補", "最も", "最重要", "中心テーマ", "主役", "一番", "上位", "優先")
RECOMMENDATION = ("買い", "売り", "推奨", "保有", "投資判断", "目標株価", "期待リターン", "ポジション", "受益")
SCORE_KEYS = {"confidence", "probability", "likelihood", "score", "rank", "ranking", "importance", "centrality",
              "pagerank", "winner", "weight", "priority", "strength", "dominant_theme", "primary_theme"}
RECOMMENDATION_KEYS = {"recommendation", "signal", "target_price", "expected_return", "position_size", "buy", "sell",
                       "hold", "beneficiary", "beneficiaries", "direction", "prediction", "forecast"}


# ================================================================ world と chain

@dataclass(frozen=True)
class Chain:
    snapshot: Any
    synthesis: Any
    presentation: Any
    rendered: Any

    def layers(self):
        return tuple(x.to_canonical_json() for x in (self.snapshot, self.synthesis, self.presentation, self.rendered))

    def texts(self):
        return [item.text for item in self.rendered.items()]


def chain(root, kind="THEME_STATE", roots=(P,), cutoff=CUT, comparison=None, stale=90) -> Chain:
    """本物の chain: 明示の要求 → A2 → A3 → A4a → A4b（mock なし）。"""
    request = NarrativeInputRequest(kind=kind, root_ids=tuple(roots), cutoff=cutoff, stale_after_days=stale,
                                    comparison_cutoff=comparison)
    snapshot = assemble_input_snapshot(data_root=root, request=request)
    synthesis = synthesize(snapshot)
    presentation = plan_presentation(synthesis)
    return Chain(snapshot, synthesis, presentation, render_presentation(presentation=presentation,
                                                                          synthesis=synthesis))


def rendered_diff(before: Chain, after: Chain):
    diff = diff_syntheses(previous=before.synthesis, current=after.synthesis)
    return diff, render_diff(diff=diff, previous=before.synthesis, current=after.synthesis)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("narrative_e2e") / "data"
    return root, build_engine_world(root)


def fresh(world, tmp_path: Path) -> Path:
    target = tmp_path / "copy" / "data"
    shutil.copytree(world[0], target)
    return target


def add_theme(root: Path, root_id: str, **override) -> str:
    """受理済みの Theme を 1 つ足す（本物の Phase 6 store API）。"""
    at = day(0, 9)
    genesis = observation(root_id=root_id, subject=subject("e2e theme", ""), recorded_at=at,
                          attachments=(attachment(FACT_V, day="2026-08-20", attached=at),),
                          provenance=provenance(reason="e2e"), **override)
    store = ThemeStore.open(root)
    store.append_root(root_record(genesis, created_at=at))
    store.append_observation(genesis)
    store.append_governance(event(subject_roots=(root_id,), related_observations=(genesis.observation_id,),
                                  recorded_at=day(2)))
    return genesis.observation_id


def add_future_q(root: Path, ids: dict) -> None:
    """cutoff の後だけ: Q の新しい observation（新しい SUPPORTS）。"""
    store = ThemeStore.open(root)
    store.append_observation(attach_evidence(store.get_observation(ids[Q]),
                                             (attachment(FACT_LATE_Q, K.FACT, day="2026-09-12", attached=day(13)),),
                                             recorded_at=day(13), provenance=provenance(reason="late q")))


def drop_contradiction(root: Path, ids: dict, at) -> None:
    """P の改訂で反証の attachment を外す（本物の revision API。旧 observation は残る）。"""
    store = ThemeStore.open(root)
    previous = store.get_observation(ids[P])
    store.append_observation(revise_observation(
        previous, recorded_at=at, attachments=tuple(a for a in previous.attachments if a.ref_id != NEWS_P),
        provenance=provenance(reason="withdrawn", dropped=(DroppedAttachment(ref_id=NEWS_P, reason="withdrawn"),))))


def inventory(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else b"dir") for p in sorted(root.rglob("*"))}


def strings(payload):
    out = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            out.append(key)
            out += strings(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            out += strings(value)
    elif isinstance(payload, str):
        out.append(payload)
    return out


def numbers(payload):
    if isinstance(payload, dict):
        return [n for value in payload.values() for n in numbers(value)]
    if isinstance(payload, list):
        return [n for value in payload for n in numbers(value)]
    return [payload] if isinstance(payload, (int, float)) and not isinstance(payload, bool) else []


def keys(payload):
    if isinstance(payload, dict):
        return set(payload) | {k for value in payload.values() for k in keys(value)}
    if isinstance(payload, list):
        return {k for value in payload for k in keys(value)}
    return set()


def item_of(c: Chain, claim_id: str):
    return {item.claim_id: item for item in c.presentation.items()}[claim_id]


def rendered_of(c: Chain, claim_id: str):
    return {item.claim_ids[0]: item for item in c.rendered.items()}[claim_id]


def claims_where(c: Chain, predicate: str, **match):
    out = []
    for claim in c.synthesis.claims:
        if claim.predicate.value != predicate:
            continue
        refs = [r.to_dict() for r in claim.refs]
        if all(any(r.get(k) == v for r in refs) for k, v in match.items()):
            out.append(claim)
    return out


def fails(error_type, code, fn, *args, **kwargs):
    with pytest.raises(error_type) as info:
        fn(*args, **kwargs)
    assert info.value.code == code, (info.value.code, info.value.detail)
    return info.value


def label(root_id: str) -> str:
    return f"テーマ〈{root_id[-8:]}〉"


# ================================================================ E01〜E02 THEME_STATE ／ THEME_SET

def test_e01_theme_state_end_to_end(world) -> None:
    c = chain(world[0])
    assert c.snapshot.root_ids == (P,) and c.synthesis.input_digest == c.snapshot.snapshot_id
    assert c.presentation.source_synthesis_id == c.synthesis.synthesis_id
    assert c.rendered.presentation_id == c.presentation.presentation_id
    assert Counter(item.template_id for item in c.rendered.items()) == Counter({
        "T01_STATE": 1, "T02_MECHANISM_COMPONENT": 4, "T03_SUPPORTS": 3, "T04_CONTEXT": 1, "T05_CONTRADICTS": 1,
        "T06_INVALIDATES": 1, "T07_OBSERVED_FACT": 2, "T08_INVALIDATION_CONDITION": 1, "T09_INVALIDATING_EVIDENCE": 1,
        "T13_CONTESTED_EVIDENCE": 1, "T14_MECHANISM_HYPOTHESIZED": 1})
    assert c.rendered.title == f"{label(P)}についての整理"
    assert [s.heading for s in c.rendered.sections] == ["テーマの状態", "機構", "材料", "矛盾する材料",
                                                         "無効化の条件と材料", "不確実性"]


def test_e02_theme_set_end_to_end_without_ranking(world) -> None:
    c = chain(world[0], "THEME_SET", (P, Q, R), comparison=EARLY)
    templates = Counter(item.template_id for item in c.rendered.items())
    assert templates["T01_STATE"] == 3 and templates["T16_HUMAN_ASSERTED_RELATION"] == 1
    assert templates["T17_SOURCE_ASSERTED_RELATION"] == 1 and templates["T18_ALTERNATIVES"] == 1
    assert templates["T05_CONTRADICTS"] == 1 and templates["T15_CHANGE"] == 3
    assert c.rendered.title == "複数のテーマについての整理（順不同）"
    assert [item.theme_root_ids for item in c.rendered.items() if item.template_id == "T01_STATE"] == [
        (root,) for root in sorted((P, Q, R))]                                              # root id の順（順位ではない）
    shared = [a.ref_id for t in c.snapshot.themes for a in t.attachments if a.role.value == "SUPPORTS"]
    assert shared.count(FACT_P) == 2                                                          # P と Q が共有する材料
    single = chain(world[0])                                                                  # 集合に入っても同じ claim
    assert {cl.claim_id for cl in single.synthesis.claims if not isinstance(cl.refs[0], A1.EvidenceItemRef)} <= {
        cl.claim_id for cl in c.synthesis.claims}
    for text in c.texts() + [c.rendered.title]:
        assert not any(word in text for word in RANKING)


# ================================================================ E03〜E07 PIT の再現と未来の隔離

@pytest.mark.parametrize("kind,roots,comparison", [("THEME_STATE", (P,), None), ("THEME_STATE", (Q,), EARLY),
                                                   ("THEME_SET", (P, Q, R), EARLY), ("THEME_SET", (Q, R), None)])
def test_e03_historical_replay_is_byte_identical_at_every_layer(world, tmp_path, kind, roots, comparison) -> None:
    root = fresh(world, tmp_path)
    before = chain(root, kind, roots, comparison=comparison).layers()
    add_future(root, world[1])                                          # 退役・新 observation / evidence・relation
    add_future_q(root, world[1])
    assert chain(root, kind, roots, comparison=comparison).layers() == before           # 4 層すべて byte 一致


def test_e03_foundation_history_with_retirement_reversal_and_merge_replays_identically(tmp_path) -> None:
    partial = build_world(tmp_path / "partial", stop_after="reversed")
    full = build_world(tmp_path / "full")                                               # 退役 → 取り消し → merge
    for checkpoint in ("accepted", "semantic_revision", "delayed_evidence_after_attachment", "retirement_reversed",
                       "before_merge"):
        cutoff = CHECKPOINTS[checkpoint]
        assert chain(partial.data_root, roots=(ROOT_A,), cutoff=cutoff).layers() == chain(
            full.data_root, roots=(ROOT_A,), cutoff=cutoff).layers(), checkpoint
    for checkpoint in ("retired", "merge_completed"):                                   # その時点では ACCEPTED でない
        fails(NarrativeInputError, "ROOT_NOT_ACCEPTED_AT_CUTOFF", chain, full.data_root, roots=(ROOT_A,),
              cutoff=CHECKPOINTS[checkpoint])


def test_e04_future_governance_is_isolated(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    before = chain(root)
    add_future(root, world[1])                                                          # P は day 12 に退役
    after = chain(root)
    assert after.layers() == before.layers()
    assert after.snapshot.themes[0].observation.governance_position.value == "ACCEPTED"
    fails(NarrativeInputError, "ROOT_NOT_ACCEPTED_AT_CUTOFF", chain, root, cutoff=day(12))


def test_e04b_the_adapter_filters_governance_events_by_the_cutoff_before_lifecycle() -> None:
    """多重防御: B2 は event を correction の chain の id 引きにしか使わないが、A2 は cutoff より後の event を渡さない。"""
    tree = ast.parse((PACKAGE_DIR / "pit_assembler.py").read_text(encoding="utf-8"))
    filters = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)
               and isinstance(node.left, ast.Attribute) and node.left.attr == "recorded_at"
               and [type(op) for op in node.ops] == [ast.LtE]
               and isinstance(node.comparators[0], ast.Attribute) and node.comparators[0].attr == "cutoff"]
    assert len(filters) == 1
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id in ("_resolve", "_eligible", "_project")]
    assert all(not any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("replace", "now")
                       for arg in call.args for n in ast.walk(arg)) for call in calls)   # 未来の時点で解かない


def test_e05_e06_future_observation_and_evidence_are_isolated_and_visible_only_later(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    before = chain(root, roots=(Q,))
    add_future_q(root, world[1])
    add_future(root, world[1])
    at_cut = chain(root, roots=(Q,))
    assert at_cut.layers() == before.layers()
    for layer in at_cut.layers():
        assert FACT_LATE_Q not in layer and FACT_LATE not in layer
    later = chain(root, roots=(Q,), cutoff=day(14))
    assert later.snapshot.themes[0].observation.observation_id != at_cut.snapshot.themes[0].observation.observation_id
    assert FACT_LATE_Q in later.snapshot.to_canonical_json() and FACT_LATE_Q in later.synthesis.to_canonical_json()
    assert Counter(i.template_id for i in later.rendered.items())["T03_SUPPORTS"] == Counter(
        i.template_id for i in at_cut.rendered.items())["T03_SUPPORTS"] + 1


def test_e07_future_relation_is_isolated(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    before = chain(root, "THEME_SET", (Q, R))
    add_future(root, world[1])                                                          # R→Q は day 14
    assert chain(root, "THEME_SET", (Q, R)).layers() == before.layers()
    assert f"{label(R)}が{label(Q)}を引き起こす" not in "".join(before.texts())
    later = chain(root, "THEME_SET", (Q, R), cutoff=day(15))
    assert (R, Q) in {(r.source_root_id, r.target_root_id) for r in later.snapshot.relations}
    assert any(f"{label(R)}が{label(Q)}を引き起こす" in text for text in later.texts())


def test_e06b_current_versus_historical_differs_only_by_pit_visible_changes(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    add_future_q(root, world[1])
    t1, t2 = chain(root, roots=(Q,)), chain(root, roots=(Q,), cutoff=day(14))
    store = ThemeStore.open(root, read_only=True)
    visible_t2 = {a.ref_id for a in store.get_observation(t2.snapshot.themes[0].observation.observation_id).attachments}
    visible_t1 = {a.ref_id for a in t1.snapshot.themes[0].attachments}
    assert {a.ref_id for a in t2.snapshot.themes[0].attachments} - visible_t1 == {FACT_LATE_Q} <= visible_t2
    assert t1.layers() == chain(fresh(world, tmp_path / "pristine"), roots=(Q,)).layers()   # 現在の状態で T1 を説明しない


# ================================================================ E08〜E14 意味が層を通って保たれる

def test_e08_contradiction_survives_every_layer(world) -> None:
    store = ThemeStore.open(world[0], read_only=True)
    assert [a.role.value for a in store.get_observation(world[1][P]).attachments if a.ref_id == NEWS_P] == [
        "CONTRADICTS"]                                                                          # Phase 6
    c = chain(world[0])
    theme = c.snapshot.themes[0]
    assert [a.role.value for a in theme.attachments if a.ref_id == NEWS_P] == ["CONTRADICTS"]  # A2
    assert EvidenceConditionFlag.CONTESTED in theme.evidence_condition_flags
    [claim] = claims_where(c, "EVIDENCE_ATTACHED", ref_id=NEWS_P)                                # A3
    assert claim.refs[0].role.value == "CONTRADICTS"
    assert claims_where(c, "IS_UNCERTAIN") and any(cl.uncertainty_code.value == "CONTESTED_EVIDENCE"
                                                   for cl in claims_where(c, "IS_UNCERTAIN"))
    item = item_of(c, claim.claim_id)                                                          # A4a
    assert (item.section, item.visibility) == (SectionKind.CONTRADICTION, Visibility.REQUIRED)
    text = rendered_of(c, claim.claim_id).text                                                 # A4b（FULL に必ず出る）
    assert text.startswith("一方、") and "矛盾する材料" in text and "報道" in text
    assert any(line.startswith("・一方、") for line in c.rendered.lines())


def test_e09_the_invalidation_condition_survives_distinctly(world) -> None:
    store = ThemeStore.open(world[0], read_only=True)
    assert [x.condition_key for x in store.get_observation(world[1][P]).invalidation_conditions] == ["inv1"]
    c = chain(world[0])
    assert [x.condition_key for x in c.snapshot.themes[0].invalidation_conditions] == ["inv1"]
    [claim] = claims_where(c, "RECORDS_INVALIDATION_CONDITION")
    assert item_of(c, claim.claim_id).rule_id == "P08_INVALIDATION_CONDITION"
    text = rendered_of(c, claim.claim_id).text
    assert "成り立たなくなる条件" in text and "「inv1」" in text and "材料" not in text


def test_e10_invalidating_evidence_survives_distinctly_and_mutates_no_governance(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    governance_before = theme_paths(root)["governance"].read_bytes()
    c = chain(root)
    theme = c.snapshot.themes[0]
    [attached] = [a for a in theme.attachments if a.ref_id == INV_P]
    assert (attached.role.value, attached.invalidation_condition_key) == ("INVALIDATES", "inv1")
    assert EvidenceConditionFlag.INVALIDATION_EVIDENCE_PRESENT in theme.evidence_condition_flags
    [evidence_claim] = claims_where(c, "EVIDENCE_ATTACHED", ref_id=INV_P)
    [link_claim] = claims_where(c, "INVALIDATING_EVIDENCE_ATTACHED")
    [condition_claim] = claims_where(c, "RECORDS_INVALIDATION_CONDITION")
    assert len({evidence_claim.claim_id, link_claim.claim_id, condition_claim.claim_id}) == 3
    assert [item_of(c, x.claim_id).rule_id for x in (evidence_claim, link_claim, condition_claim)] == [
        "P06_INVALIDATES", "P09_INVALIDATING_EVIDENCE", "P08_INVALIDATION_CONDITION"]
    assert rendered_of(c, link_claim.claim_id).text.endswith("これはテーマの状態を変えるものではありません。")
    assert all(ref.governance_position.value == "ACCEPTED" for cl in c.synthesis.claims for ref in cl.refs
               if isinstance(ref, A1.ThemeObservationRef))
    assert not any(word in text for text in c.texts() for word in ("は無効です", "無効になりました", "無効化されました"))
    assert theme_paths(root)["governance"].read_bytes() == governance_before                 # governance は書かれない


def test_e11_context_survives_as_context(world) -> None:
    for roots, ref_id in (((P,), DOC_P), ((CTX,), DOC_CTX)):
        c = chain(world[0], roots=roots)
        assert [a.role.value for a in c.snapshot.themes[0].attachments if a.ref_id == ref_id] == ["CONTEXT"]
        [claim] = claims_where(c, "EVIDENCE_ATTACHED", ref_id=ref_id)
        assert claim.refs[0].role.value == "CONTEXT" and not claims_where(c, "EVIDENCE_ITEM_OBSERVED", ref_id=ref_id)
        item = item_of(c, claim.claim_id)
        assert (item.evidence_role.value, item.section) == ("CONTEXT", SectionKind.EVIDENCE)
        text = rendered_of(c, claim.claim_id).text
        assert "文脈の材料" in text and not any(w in text for w in ("支持", "裏付", "反証", "証明", "存在します"))
    ctx = chain(world[0], roots=(CTX,))
    assert any(i.template_id == "T10_NO_SUPPORTING_EVIDENCE" for i in ctx.rendered.items())


def test_e12_source_capability_ceiling(world) -> None:
    c = chain(world[0])
    capabilities = {s.item.ref_id: s.capability.value for s in c.snapshot.evidence_sources}
    assert capabilities == {FACT_P: "OBSERVATIONAL_RECORD", OBS_P: "OBSERVATIONAL_RECORD", DOC_P: "SOURCE_CONTENT",
                            NEWS_P: "SOURCE_CONTENT", STMT_P: "SOURCE_CONTENT", INV_P: "SOURCE_CONTENT"}
    facts = {ref.ref_id for cl in claims_where(c, "EVIDENCE_ITEM_OBSERVED") for ref in cl.refs}
    assert facts == {FACT_P, OBS_P}                                                          # 文書・報道・発言は事実にならない
    observed = [i for i in c.rendered.items() if i.template_id == "T07_OBSERVED_FACT"]
    assert sorted(i.text.split("時点の")[1].split("が存在します")[0] for i in observed) == ["事実の記録", "観測の記録"]
    for layer in c.layers():
        assert FACT_UNDATED not in layer                                                     # 時刻の無い材料は投影されない


def test_e13_reviewed_interpretation_ceiling(world) -> None:
    for kind, roots in (("THEME_STATE", (P,)), ("THEME_SET", (P, Q, R))):
        c = chain(world[0], kind, roots)
        for claim in c.synthesis.claims:
            text = rendered_of(c, claim.claim_id).text
            if claim.epistemic_class is A1.EpistemicClass.REVIEWED_INTERPRETATION:
                assert "整理されています" in text or "主張しています" in text, text
            if claim.epistemic_class is A1.EpistemicClass.OBSERVED_FACT:
                assert not any(isinstance(ref, A1.INTERPRETATION_REF_TYPES) for ref in claim.refs)
        assert all(item_of(c, i.claim_ids[0]).epistemic_class is A1.EpistemicClass.OBSERVED_FACT
                   for i in c.rendered.items() if i.template_id == "T07_OBSERVED_FACT")


def test_e14_mechanism_certainty_is_never_strengthened(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    add_theme(root, V_SUPPORTED, certainty_class=MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM)
    for root_id, certainty, hypothesized in ((P, "HYPOTHESIZED_MECHANISM", True),
                                             (V_SUPPORTED, "EVIDENCE_SUPPORTED_MECHANISM", False)):
        c = chain(root, roots=(root_id,))
        assert c.snapshot.themes[0].observation.mechanism_certainty.value == certainty
        assert {ref.mechanism_certainty.value for cl in c.synthesis.claims for ref in cl.refs
                if isinstance(ref, A1.ThemeObservationRef)} == {certainty}
        assert any(i.template_id == "T14_MECHANISM_HYPOTHESIZED" for i in c.rendered.items()) is hypothesized
        for text in c.texts():
            assert not any(word in text for word in ("確立", "因果関係が確認", "証明", "確定", "明らかに"))
        assert all(t.endswith("が整理されています。") for t in c.texts() if "機構の" in t and "として「" in t)


# ================================================================ E15〜E17 relation・SOURCE_ASSERTED・代替

def test_e15_relation_endpoints_direction_type_and_class_survive(world) -> None:
    c = chain(world[0], "THEME_SET", (P, Q, R))
    expected = {(P, Q, "CAUSES", "HUMAN_ASSERTED"), (Q, R, "AMPLIFIES", "SOURCE_ASSERTED")}
    assert {(r.source_root_id, r.target_root_id, r.relation_type.value, r.assertion_class.value)
            for r in c.snapshot.relations} == expected                                        # A2
    claims = claims_where(c, "HUMAN_ASSERTED_RELATION") + claims_where(c, "SOURCE_ASSERTED_RELATION")
    refs = [[r for r in cl.refs if isinstance(r, A1.RelationAssertionRef)][0] for cl in claims]
    assert {(r.source_root_id, r.target_root_id, r.relation_type.value, r.assertion_class.value)
            for r in refs} == expected                                                         # A3（逆・推移なし）
    for claim, ref in zip(claims, refs):
        item = item_of(c, claim.claim_id)                                                      # A4a
        assert item.theme_root_ids == tuple(sorted((ref.source_root_id, ref.target_root_id)))
        assert item.assertion_class is ref.assertion_class
        verb = dict(RT.RELATION_LABELS)[ref.relation_type.value]                               # A4b（向きのまま）
        assert f"{label(ref.source_root_id)}が{label(ref.target_root_id)}{verb}" in rendered_of(c, claim.claim_id).text
    joined = "".join(c.texts())
    for source, target in ((Q, P), (R, Q), (P, R), (R, P), (P, S)):                           # 逆・推移・撤回済み・範囲外
        assert not re.search(f"{label(source)}が{label(target)}(を|に)", joined)
    assert label(S) not in joined


def test_e16_source_asserted_stays_source_qualified_and_its_removal_fails(world, monkeypatch) -> None:
    c = chain(world[0], "THEME_SET", (Q, R))
    [claim] = claims_where(c, "SOURCE_ASSERTED_RELATION")
    text = rendered_of(c, claim.claim_id).text
    assert text.startswith("出典は、") and "出典による主張であり、この説明が主張する関係ではありません" in text

    def relation_of(value):
        return [r for r in value.refs if isinstance(r, A1.RelationAssertionRef)][0]
    snapshot = copy.deepcopy(c.snapshot)                                                     # A2 → A3 で外す
    object.__setattr__(snapshot.relations[0], "assertion_class", A1.AssertionClass.HUMAN_ASSERTED)
    fails(NarrativeSynthesisError, "SNAPSHOT_INTEGRITY_FAILURE", synthesize, snapshot)
    synthesis = copy.deepcopy(c.synthesis)                                                   # A3 → A4a ／ A4b で外す
    object.__setattr__(relation_of([x for x in synthesis.claims if x.claim_id == claim.claim_id][0]),
                       "assertion_class", A1.AssertionClass.HUMAN_ASSERTED)
    fails(NarrativePresentationError, "SYNTHESIS_INTEGRITY_FAILURE", plan_presentation, synthesis)
    fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=c.presentation,
          synthesis=synthesis)
    presentation = copy.deepcopy(c.presentation)                                             # A4a → A4b で外す
    target = [i for s in presentation.sections for i in s.items if i.claim_id == claim.claim_id][0]
    object.__setattr__(target, "assertion_class", A1.AssertionClass.HUMAN_ASSERTED)
    fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=presentation,
          synthesis=c.synthesis)
    monkeypatch.setattr(RT, "TEMPLATES", tuple(t for t in RT.TEMPLATES if t.template_id != "T17_SOURCE_ASSERTED_RELATION"))
    fails(NarrativeRenderError, "UNSUPPORTED_TEMPLATE", render_presentation, presentation=c.presentation,
          synthesis=c.synthesis)                                                             # 限定なしの文言に落ちない


def test_e17_alternatives_stay_parallel_unranked_and_non_preferred(world) -> None:
    c = chain(world[0], "THEME_SET", (P, Q, R))
    [claim] = claims_where(c, "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE")
    attachments = [r for r in claim.refs if isinstance(r, A1.EvidenceAttachmentRef)]
    assert {a.ref_id for a in attachments} == {FACT_P} and {a.role.value for a in attachments} == {"SUPPORTS"}
    item = item_of(c, claim.claim_id)
    assert item.theme_root_ids == tuple(sorted((P, Q))) and item.visibility is Visibility.REQUIRED
    text = rendered_of(c, claim.claim_id).text
    assert text.index(label(min(P, Q))) < text.index(label(max(P, Q))) and "並列" in text and "順不同" in text
    assert not any(word in text for word in RANKING + ("優れ", "勝", "採用"))
    assert chain(world[0], "THEME_SET", (R, Q, P)).rendered.to_canonical_json() == c.rendered.to_canonical_json()


# ================================================================ E18〜E21 REQUIRED・D-P7-A4B-1（検証済みの裏付け）

def without(presentation, *, section=None, claim_id=None):
    sections = []
    for group in presentation.sections:
        if group.section is section:
            continue
        items = tuple(item for item in group.items if item.claim_id != claim_id)
        if items:
            sections.append(PresentationSection(section=group.section, items=items))
    return NarrativePresentation(kind=presentation.kind, subject_root_ids=presentation.subject_root_ids,
                                 source_synthesis_id=presentation.source_synthesis_id, sections=tuple(sections))


def test_e18_required_items_cannot_be_omitted_end_to_end(world) -> None:
    for kind, roots in (("THEME_STATE", (P,)), ("THEME_SET", (P, Q, R))):
        c = chain(world[0], kind, roots)
        required = [item for item in c.presentation.items() if item.visibility is Visibility.REQUIRED]
        assert {i.section for i in required} >= {SectionKind.CONTRADICTION, SectionKind.INVALIDATION,
                                                 SectionKind.UNCERTAINTY}
        assert {i.claim_id for i in required} <= {r.claim_ids[0] for r in c.rendered.items()}   # FULL は全部出す
        for item in required:
            fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation,
                  presentation=without(c.presentation, claim_id=item.claim_id), synthesis=c.synthesis)
        for section in {i.section for i in required}:
            fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation,
                  presentation=without(c.presentation, section=section), synthesis=c.synthesis)


def with_extra_claim(synthesis, key="extra_backing_key"):
    """A1 としては有効な synthesis Y ＝ X ＋ 追加の claim（機構 component）。"""
    component_claim = next(cl for cl in synthesis.claims if cl.predicate is A1.Predicate.RECORDS_MECHANISM_COMPONENT)
    ref = component_claim.refs[0]
    extra = A1.NarrativeClaim(epistemic_class=component_claim.epistemic_class, claim_kind=component_claim.claim_kind,
                              predicate=component_claim.predicate,
                              refs=(A1.MechanismComponentRef(root_id=ref.root_id, observation_id=ref.observation_id,
                                                             component_type=ref.component_type, component_key=key),))
    return A1.NarrativeSynthesis(kind=synthesis.kind, subject_root_ids=synthesis.subject_root_ids,
                                 cutoff=synthesis.cutoff, knowledge_pins=synthesis.knowledge_pins,
                                 input_digest=synthesis.input_digest, claims=synthesis.claims + (extra,)), extra


def test_e19_a4b_backing_matching_succeeds_and_mismatch_fails(world, tmp_path) -> None:
    x = chain(world[0])
    assert render_presentation(presentation=x.presentation, synthesis=x.synthesis).to_canonical_json() == (
        x.rendered.to_canonical_json())                                                          # A
    same = A1.NarrativeSynthesis.from_json(x.synthesis.to_canonical_json())                   # 同じ内容は受ける
    assert render_presentation(presentation=x.presentation, synthesis=same).rendered_id == x.rendered.rendered_id
    for other in (chain(world[0], roots=(BARE,)).synthesis, chain(world[0], cutoff=day(11)).synthesis,
                  chain(world[0], roots=(Q,)).synthesis):                                        # B: X の提示 ＋ Y
        fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation,
              presentation=x.presentation, synthesis=other)


def test_e20_an_extra_eligible_claim_in_the_synthesis_is_never_read(world) -> None:
    x = chain(world[0])
    y, extra = with_extra_claim(x.synthesis)
    assert plan_presentation(y).presentation_id != x.presentation.presentation_id
    fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=x.presentation,
          synthesis=y)                                                                             # C: 黙って読まない
    authorized = render_presentation(presentation=plan_presentation(y), synthesis=y)             # 提示が許せば出る
    assert "「extra_backing_key」" in "".join(i.text for i in authorized.items())
    assert "extra_backing_key" not in x.rendered.to_canonical_json()


class RecordingClaims(dict):
    """claim の索引への参照を記録し、走査（探索）を禁じる。"""

    def __init__(self, data, log):
        super().__init__(data)
        self.log = log

    def get(self, key, default=None):
        self.log.append(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.log.append(key)
        return super().__getitem__(key)

    def _forbidden(self, *args, **kwargs):
        raise AssertionError("the renderer searched the synthesis")

    __iter__ = keys = values = items = _forbidden


def test_e21_the_renderer_resolves_only_refs_reachable_from_presentation_items(world, monkeypatch) -> None:
    x = chain(world[0], "THEME_SET", (P, Q, R), comparison=EARLY)
    y, extra = with_extra_claim(x.synthesis)
    forged = copy.deepcopy(plan_presentation(y))                                               # D: 合成だけの claim を選ぶ
    fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation,
          presentation=without(forged, claim_id=next(iter(x.presentation.claim_ids()))), synthesis=y)
    fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=forged,
          synthesis=x.synthesis)
    tampered = copy.deepcopy(x.presentation)
    object.__setattr__(tampered.sections[1].items[0], "claim_id", extra.claim_id)
    fails(NarrativeRenderError, "PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=tampered,
          synthesis=y)
    log: list = []                                                                              # E / F / H: 走査しない
    original = TR._rendered_item
    monkeypatch.setattr(TR, "_rendered_item", lambda pid, item, claims, labels: original(
        pid, item, RecordingClaims(claims, log), labels))
    again = render_presentation(presentation=x.presentation, synthesis=x.synthesis)
    assert log == list(x.presentation.claim_ids())                                              # item の claim id だけ
    assert again.to_canonical_json() == x.rendered.to_canonical_json()                          # G: 無関係な claim は無い
    assert {text for _, text in again.theme_labels} == {label(r) for r in (P, Q, R)}
    before, after = chain(world[0], "THEME_SET", (P, Q, R), cutoff=day(3)), chain(world[0], "THEME_SET", (P, Q, R))
    diff = diff_syntheses(previous=before.synthesis, current=after.synthesis)
    log.clear()
    render_diff(diff=diff, previous=before.synthesis, current=after.synthesis)
    assert log == [entry.item.claim_id for entry in diff.items]


# ================================================================ E22〜E25 提案・監視・B7・P5 は authority ではない

def full_layers(root):
    return (chain(root, comparison=EARLY).layers(), chain(root, "THEME_SET", (P, Q, R), comparison=EARLY).layers())


@pytest.mark.parametrize("paths", [
    lambda root: tuple(proposal_paths(root).values()),                                          # E22: B3
    lambda root: tuple(relation_proposal_paths(root).values()),                                 # E22: B5C
    lambda root: (root / "knowledge" / "theme_taxonomy.0.2.0.yaml",                             # E22: B4
                  root / "knowledge" / "discovery_rules.0.1.0.yaml"),
    lambda root: (review_state_path(root),),                                                    # E23: B6
    lambda root: (generation_journal_path(root),),                                              # E24: B7
    lambda root: (evaluations_path(root), predictions_path(root),                              # E25: P5
                  root / "predictions" / "calibration.json")],
    ids=["e22_b3_proposals", "e22_b5c_relation_proposals", "e22_b4_discovery", "e23_b6_monitoring",
         "e24_b7_generation", "e25_p5"])
def test_e22_to_e25_poisoned_non_authority_stores_do_not_change_any_layer(world, tmp_path, paths) -> None:
    expected = full_layers(world[0])
    root = fresh(world, tmp_path)
    for path in paths(root):
        poison(path)
    assert full_layers(root) == expected


def test_e22_populated_relation_proposals_are_not_narrative_authority(world, tmp_path) -> None:
    expected = full_layers(world[0])
    root = fresh(world, tmp_path)
    store = RelationProposalStore.initialize(root)
    store.append_proposal(relation_candidate(P, R, at=day(5)))
    store.append_proposal(relation_candidate(R, Q, at=day(6)))
    assert full_layers(root) == expected


# ================================================================ E26〜E28 破損・欠落の authority

@pytest.mark.parametrize("authority", ["roots", "observations", "governance"])
def test_e26_theme_authority_corruption_fails_closed_before_any_narrative(world, tmp_path, authority) -> None:
    root = fresh(world, tmp_path)
    path = theme_paths(root)[authority]
    path.write_bytes(path.read_bytes()[:-7] + b"\n")
    for kind, roots in (("THEME_STATE", (P,)), ("THEME_SET", (P, Q, R))):
        error = fails(NarrativeInputError, "AUTHORITY_CORRUPTION", chain, root, kind, roots)
        assert str(root) not in str(error) and "canary" not in str(error)


def test_e26_a_corrupt_future_line_still_stops_the_past(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    path = theme_paths(root)["governance"]
    path.write_bytes(path.read_bytes() + b'{"event_type":"RETIRED","recorded_at":"2099-01-01T00:00:00+00:00"\n')
    fails(NarrativeInputError, "AUTHORITY_CORRUPTION", chain, root)


def test_e27_evidence_authority_corruption_fails_closed(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    path = theme_paths(root)["observations"]
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"role":"CONTRADICTS"', '"role":"SUPPORTS"', 1), encoding="utf-8")
    error = fails(NarrativeInputError, "AUTHORITY_CORRUPTION", chain, root)                    # 支持として描かない
    assert "SUPPORTS" not in str(error)


def test_e28_relation_authority_corruption_fails_closed_for_theme_sets(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    path = relation_paths(root)["assertions"]
    path.write_bytes(path.read_bytes() + b"{not json\n")
    fails(NarrativeInputError, "AUTHORITY_CORRUPTION", chain, root, "THEME_SET", (P, Q))
    assert chain(root).layers() == chain(world[0]).layers()                                    # THEME_STATE は relation を読まない


def test_e28_missing_authority_is_distinguishable_from_valid_empty_state(world, tmp_path) -> None:
    fails(NarrativeInputError, "AUTHORITY_UNAVAILABLE", chain, tmp_path / "missing")
    assert not (tmp_path / "missing").exists()
    empty = tmp_path / "empty"
    ThemeStore.initialize(empty)
    fails(NarrativeInputError, "ROOT_NOT_FOUND", chain, empty)                                # 空の Narrative にしない
    root = fresh(world, tmp_path)
    for path in relation_paths(root).values():
        path.unlink()
    fails(NarrativeInputError, "RELATION_AUTHORITY_UNAVAILABLE", chain, root, "THEME_SET", (P, Q))
    assert not relation_paths(root)["assertions"].exists()


# ================================================================ E29〜E31 範囲・cutoff・文字の攻撃

def test_e29_scope_attacks_fail_or_stay_excluded(world) -> None:
    for bad in (None, P, ("all",), ("*",), [P.lower()]):
        fails(NarrativeInputError, "INVALID_SCOPE", NarrativeInputRequest, kind="THEME_STATE", root_ids=bad,
              cutoff=CUT, stale_after_days=90)
    error = fails(NarrativeInputError, "ROOT_NOT_ACCEPTED_AT_CUTOFF", chain, world[0], "THEME_SET", (P, Q, S))
    assert error.failures == ((S, "ROOT_NOT_ACCEPTED_AT_CUTOFF"),)                              # 部分的な Narrative なし
    state = chain(world[0])
    assert all(label(r) not in "".join(state.texts()) for r in (Q, R, S))                      # 要求していない Theme
    trio = chain(world[0], "THEME_SET", (P, Q, R))
    assert label(S) not in trio.rendered.to_canonical_json()                                    # 範囲外の relation P→S
    assert chain(world[0], "THEME_SET", (Q, R, P)).rendered.to_canonical_json() == trio.rendered.to_canonical_json()


def test_e30_cutoff_attacks_are_caught(world, monkeypatch) -> None:
    for cutoff in (None, "now", "latest", CUT.replace(tzinfo=None)):
        fails(NarrativeInputError, "INVALID_CUTOFF", NarrativeInputRequest, kind="THEME_STATE", root_ids=(P,),
              cutoff=cutoff, stale_after_days=90)
    for comparison in (CUT, day(11)):
        fails(NarrativeInputError, "INVALID_COMPARISON_CUTOFF", NarrativeInputRequest, kind="THEME_STATE",
              root_ids=(P,), cutoff=CUT, stale_after_days=90, comparison_cutoff=comparison)
    early, late = chain(world[0], cutoff=day(5)), chain(world[0])
    fails(NarrativePresentationError, "INCOMPATIBLE_DIFF_INPUTS", diff_syntheses, previous=late.synthesis,
          current=early.synthesis)
    import random
    import time
    expected = chain(world[0], "THEME_SET", (P, Q, R), comparison=EARLY).layers()

    def forbidden(*args, **kwargs):
        raise AssertionError("a clock or randomness was used")
    for module, name in ((time, "time"), (time, "time_ns"), (time, "monotonic"), (time, "localtime"),
                         (random, "random"), (os, "urandom"), (os, "getenv")):
        monkeypatch.setattr(module, name, forbidden)
    assert chain(world[0], "THEME_SET", (P, Q, R), comparison=EARLY).layers() == expected     # 暗黙の現在時刻なし
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        attributes = {n.attr for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.Attribute)}
        assert not attributes & {"now", "utcnow", "today"}, path.name


@pytest.mark.parametrize("root_id,override", [
    (V_URL, {"mechanism": mechanism(drivers=(component(key="www.example.com"),))}),
    (V_JOURNAL, {"invalidation_conditions": (condition(key="journal.jsonl"),)}),
    (V_SECRET, {"mechanism": mechanism(drivers=(component(key="api_key"),))})],
    ids=["url_key", "journal_key", "secret_key"])
def test_e31_hostile_keys_fail_closed_before_any_unsafe_rendered_output(world, tmp_path, root_id, override) -> None:
    root = fresh(world, tmp_path)
    add_theme(root, root_id, **override)
    request = NarrativeInputRequest(kind="THEME_STATE", root_ids=(root_id,), cutoff=CUT, stale_after_days=90)
    synthesis = synthesize(assemble_input_snapshot(data_root=root, request=request))          # 上流は通る（key は有効な token）
    fails(NarrativeRenderError, "UNSAFE_TEXT", render_presentation, presentation=plan_presentation(synthesis),
          synthesis=synthesis)


def test_e31_markup_path_and_control_characters_are_stopped_upstream(world, tmp_path) -> None:
    for bad in ("<b>x", "a/b", "a b", "x](http", "a\\b"):
        with pytest.raises(Exception):
            component(key=bad)                                                                 # Phase 6 が書かせない
        with pytest.raises(A1.NarrativeModelError):
            A1.MechanismComponentRef(root_id=P, observation_id="thobs_" + "0" * 24, component_type="DRIVER",
                                     component_key=bad)                                        # A1 も拒否
    root = fresh(world, tmp_path)                                                              # Phase 6 が通す末尾の改行
    add_theme(root, V_NEWLINE, mechanism=mechanism(drivers=(component(key="x\n"),)))
    fails(NarrativeInputError, "REF_NOT_PROJECTABLE", chain, root, roots=(V_NEWLINE,))
    c = chain(world[0], "THEME_SET", (P, Q, R), comparison=EARLY)                               # 人間の文・本文・locator
    for layer in c.layers() + ("".join(c.rendered.lines()),):
        for canary in (CANARY_SUBJECT, CANARY_REASON, CANARY_NOTE, CANARY_EXCERPT, "example.invalid", "canary"):
            assert canary not in layer


# ================================================================ E32〜E34 推奨・順位・自己学習なし

def all_outputs(world):
    chains = [chain(world[0]), chain(world[0], roots=(BARE,)), chain(world[0], roots=(CTX,)),
              chain(world[0], "THEME_SET", (P, Q, R), comparison=EARLY)]
    diff, rendered = rendered_diff(chain(world[0], "THEME_SET", (P, Q, R), cutoff=day(3)),
                                   chain(world[0], "THEME_SET", (P, Q, R)))                      # 同じ knowledge pin の組
    return chains, diff, rendered


def test_e32_no_recommendation_can_be_produced(world) -> None:
    chains, diff, rendered = all_outputs(world)
    payloads = [x.to_dict() for c in chains for x in (c.snapshot, c.synthesis, c.presentation, c.rendered)]
    payloads += [diff.to_dict(), rendered.to_dict()]
    for payload in payloads:
        assert not keys(payload) & RECOMMENDATION_KEYS
    texts = [t for c in chains for t in c.rendered.lines()] + list(rendered.lines())
    for text in texts:
        assert not any(word in text for word in RECOMMENDATION + EVALUATIVE), text


def test_e33_no_score_rank_or_winner_exists(world) -> None:
    chains, diff, rendered = all_outputs(world)
    for c in chains:
        for payload in (c.snapshot.to_dict(), c.synthesis.to_dict(), c.presentation.to_dict(), c.rendered.to_dict()):
            assert not keys(payload) & SCORE_KEYS
        for payload in (c.synthesis.to_dict(), c.presentation.to_dict(), c.rendered.to_dict()):
            assert numbers(payload) == []                                                    # 数値は 1 つも無い
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined = {n.name.lower() for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        assert not [n for n in defined if any(w in n for w in ("score", "rank", "centrality", "pagerank", "winner",
                                                                "confidence", "probability", "weight"))], path.name


def test_e34_no_self_learning_or_feedback_loop(world) -> None:
    import importlib
    modules = [importlib.import_module(f"src.intelligence.narrative_intelligence.{p.stem}")
               for p in sorted(PACKAGE_DIR.glob("*.py")) if p.stem != "__init__"]
    state = [{k: repr(v) for k, v in vars(m).items() if not k.startswith("__")} for m in modules]
    first = [chain(world[0], roots=roots).layers() for roots in ((P,), (Q,), (BARE,))]
    reordered = [chain(world[0], roots=roots).layers() for roots in ((BARE,), (Q,), (P,))]
    assert first == list(reversed(reordered))                                                   # 前の出力に依らない
    assert [{k: repr(v) for k, v in vars(m).items() if not k.startswith("__")} for m in modules] == state
    for module in modules:
        for name in getattr(module, "__all__", ()):
            value = vars(module)[name]
            if callable(value) and not isinstance(value, type):
                import inspect
                assert not set(inspect.signature(value).parameters) & {
                    "history", "feedback", "clicks", "accuracy", "win_rate", "acceptance_rate", "calibration",
                    "previous_result", "latest", "user"}, (module.__name__, name)


# ================================================================ E35〜E37 再現・書き込みなし・import の閉包

def test_e35_deterministic_replay_across_fresh_processes(world) -> None:
    code = ("import sys, json\nfrom tests.intelligence.test_narrative_phase7_e2e import chain, rendered_diff\n"
            "from tests.intelligence.test_narrative_pit_assembler import P, Q, R, EARLY, day\n"
            "root = sys.argv[1]\nc = chain(root, 'THEME_SET', (R, Q, P), comparison=EARLY)\n"
            "d, rd = rendered_diff(chain(root, 'THEME_SET', (P, Q, R), cutoff=day(3)), chain(root, 'THEME_SET', (P, Q, R)))\n"
            "sys.stdout.buffer.write(json.dumps(list(c.layers()) + [d.to_canonical_json(), rd.to_canonical_json()])"
            ".encode('utf-8'))\n")
    expected = list(chain(world[0], "THEME_SET", (P, Q, R), comparison=EARLY).layers())
    d, rd = rendered_diff(chain(world[0], "THEME_SET", (P, Q, R), cutoff=day(3)), chain(world[0], "THEME_SET", (P, Q, R)))
    expected += [d.to_canonical_json(), rd.to_canonical_json()]
    for seed in ("0", "4242"):
        out = subprocess.run([sys.executable, "-c", code, str(world[0])], cwd=REPO_ROOT, capture_output=True, check=True,
                             env={"PYTHONPATH": str(REPO_ROOT), "PATH": os.environ.get("PATH", ""),
                                  "PYTHONHASHSEED": seed, "LC_ALL": "C"})
        assert json.loads(out.stdout.decode("utf-8")) == expected


def test_e36_the_full_end_to_end_run_writes_zero_bytes(world, tmp_path, monkeypatch) -> None:
    root = fresh(world, tmp_path)
    data_before = inventory(root)
    repo_before = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    real_open = io.open

    def read_only_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError("the pipeline opened a file for writing")
        return real_open(file, mode, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("the pipeline wrote, removed or connected")
    monkeypatch.setattr(builtins, "open", read_only_open)
    monkeypatch.setattr(io, "open", read_only_open)
    for module, name in ((os, "replace"), (os, "rename"), (os, "remove"), (os, "unlink"), (os, "rmdir"),
                         (os, "mkdir"), (os, "makedirs"), (socket, "socket"), (socket, "create_connection")):
        monkeypatch.setattr(module, name, forbidden)
    for _ in range(2):
        for kind, roots in (("THEME_STATE", (P,)), ("THEME_SET", (P, Q, R))):
            chain(root, kind, roots, comparison=EARLY)
        rendered_diff(chain(root, "THEME_SET", (P, Q, R), cutoff=day(3)), chain(root, "THEME_SET", (P, Q, R)))
        with pytest.raises(NarrativeInputError):
            chain(root, "THEME_SET", (P, S))
    monkeypatch.undo()
    assert inventory(root) == data_before
    assert subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True,
                          text=True).stdout == repo_before


PHASE6 = ("themes", "theme_intelligence")
EXPECTED_INTERNAL_GRAPH = {
    "__init__": set(), "synthesis_model": set(), "input_model": {"synthesis_model"},
    "pit_assembler": {"input_model", "synthesis_model"}, "synthesis_engine": {"input_model", "synthesis_model"},
    "presentation_model": {"synthesis_model"}, "presentation_planner": {"presentation_model", "synthesis_model"},
    "narrative_diff": {"presentation_model", "presentation_planner", "synthesis_model"},
    "rendered_model": {"presentation_model", "synthesis_model"}, "render_templates_ja": {"rendered_model"},
    "text_renderer": {"narrative_diff", "presentation_model", "presentation_planner", "render_templates_ja",
                      "rendered_model", "synthesis_model"}}


def test_e37_the_exact_import_graph_and_closure(world) -> None:
    graph, phase6 = {}, {}
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        modules = imported_modules(path)
        graph[path.stem] = {m[1:] for m in modules if m.startswith(".") and not m.startswith("..")}
        phase6[path.stem] = {m for m in modules if any(seg in m.split(".") for seg in PHASE6)}
        assert not {m for m in modules if m.startswith("..") and m.split(".")[2] not in ("core", *PHASE6)}, path.stem
    assert graph == EXPECTED_INTERNAL_GRAPH
    assert {name for name, found in phase6.items() if found} == {"pit_assembler"}           # 認可された adapter だけ

    def closure(name, seen=None):
        seen = set() if seen is None else seen
        for dependency in graph[name]:
            if dependency not in seen:
                seen.add(dependency)
                closure(dependency, seen)
        return seen
    renderer = closure("text_renderer")
    assert not renderer & {"input_model", "pit_assembler", "synthesis_engine"}              # 描画は A2 / A3 に届かない
    assert not closure("synthesis_engine") & {"pit_assembler"}
    code = ("import sys\nimport src.intelligence.narrative_intelligence.text_renderer\n"
            "print('\\n'.join(sorted(sys.modules)))\n")
    loaded = set(subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                                env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""}).stdout.split())
    assert not {m for m in loaded if any(seg in m.split(".") for seg in PHASE6 + ("pit_assembler", "input_model",
                                                                                 "synthesis_engine", "predictions"))}


# ================================================================ E38〜E40 差分と追跡の鎖

def test_e38_end_to_end_diff_categories_are_exact(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    add_future_q(root, world[1])
    add_future(root, world[1])
    for kind, roots, t2 in (("THEME_STATE", (Q,), day(14)), ("THEME_SET", (Q, R), day(15))):
        before, after = chain(root, kind, roots), chain(root, kind, roots, cutoff=t2)
        diff, rendered = rendered_diff(before, after)
        old = {c.claim_id for c in before.synthesis.claims}
        new = {c.claim_id for c in after.synthesis.claims}
        assert set(diff.claim_ids(DiffCategory.ADDED)) == new - old
        assert set(diff.claim_ids(DiffCategory.REMOVED)) == old - new
        assert set(diff.claim_ids(DiffCategory.UNCHANGED)) == old & new
        groups = {g.category: {i.claim_ids[0] for i in g.items} for g in rendered.groups}
        assert groups.get("ADDED", set()) == new - old and groups.get("REMOVED", set()) == old - new
        texts = {i.claim_ids[0]: i.text for i in after.rendered.items()} | {
            i.claim_ids[0]: i.text for i in before.rendered.items()}
        assert all(i.text == texts[i.claim_ids[0]] for i in rendered.items())
        assert [g.heading for g in rendered.groups] == [h for c, h in RT.DIFF_HEADINGS if c in groups]


def test_e39_diff_rendering_never_evaluates(world, tmp_path) -> None:
    root = fresh(world, tmp_path)
    drop_contradiction(root, world[1], day(6))                                                   # 反証が後で外れる
    before, after = chain(root, cutoff=day(5)), chain(root)
    diff, rendered = rendered_diff(before, after)
    removed = {c.claim_id for c in before.synthesis.claims} - {c.claim_id for c in after.synthesis.claims}
    contradiction = claims_where(before, "EVIDENCE_ATTACHED", ref_id=NEWS_P)[0].claim_id
    assert contradiction in removed and contradiction in diff.claim_ids(DiffCategory.REMOVED)
    assert not claims_where(after, "EVIDENCE_ATTACHED", ref_id=NEWS_P)
    grown = fresh(world, tmp_path / "grown")                                                     # SUPPORTS が後で増える
    add_future_q(grown, world[1])
    _, grown_rendered = rendered_diff(chain(grown, roots=(Q,)), chain(grown, roots=(Q,), cutoff=day(14)))
    for r in (rendered, grown_rendered):
        assert {g.category for g in r.groups} <= {"ADDED", "REMOVED", "UNCHANGED"}
        for text in r.lines():
            assert not any(word in text for word in EVALUATIVE + ("確信", "信頼度", "%", "％")), text
        assert not keys(r.to_dict()) & (SCORE_KEYS | {"delta", "trend", "momentum", "improved", "weakened"})


def test_e40_the_traceability_chain_is_complete(world) -> None:
    for kind, roots, comparison in (("THEME_STATE", (P,), None), ("THEME_SET", (P, Q, R), EARLY)):
        c = chain(world[0], kind, roots, comparison=comparison)
        material = set()
        for theme in c.snapshot.themes:
            for ref in (theme.observation, *theme.components, *theme.invalidation_conditions, *theme.attachments,
                        *(theme.changes or ())):
                material.add(A1.canonical_json(ref.to_dict()))
        material |= {A1.canonical_json(s.item.to_dict()) for s in c.snapshot.evidence_sources}
        material |= {A1.canonical_json(r.to_dict()) for r in c.snapshot.relations or ()}
        claims = {cl.claim_id: cl for cl in c.synthesis.claims}
        items = {item.claim_id: item for item in c.presentation.items()}
        store = ThemeStore.open(world[0], read_only=True)
        relation_journal = relation_paths(world[0])["assertions"].read_text(encoding="utf-8")
        for rendered in c.rendered.items():                                                      # 文 → 提示 item
            item = items[rendered.claim_ids[0]]
            claim = claims[item.claim_id]                                                        # → claim
            for ref in claim.refs:                                                               # → snapshot の材料
                assert A1.canonical_json(ref.to_dict()) in material
                if isinstance(ref, A1.EvidenceAttachmentRef):                                    # → Phase 6 authority
                    stored = [a for a in store.get_observation(ref.observation_id).attachments
                              if a.ref_id == ref.ref_id and a.consequence_ref == ref.consequence_key]
                    assert [(a.role.value, a.attached_at) for a in stored] == [(ref.role.value, ref.attached_at)]
                if isinstance(ref, A1.RelationAssertionRef):
                    assert ref.relation_assertion_id in relation_journal
        from src.intelligence.core.ids import content_id
        for rendered in c.rendered.items():
            assert rendered.presentation_item_id == content_id("narpit", A1.canonical_json(
                {"presentation_id": c.presentation.presentation_id, "item": items[rendered.claim_ids[0]].to_dict()}))


# ================================================================ E41〜E44 監査の記録

def test_e41_real_data_status_is_recorded_honestly() -> None:
    text = AUDIT.read_text(encoding="utf-8")
    assert "REAL_DATA_E2E = NOT_RUN" in text
    for limit in ("precision", "recall", "usefulness", "coverage", "false-positive", "false-negative"):
        assert limit in text, limit
    tracked = subprocess.run(["git", "ls-files", "data"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert "themes/theme_roots.jsonl" not in tracked                                            # repo に実の authority は無い


def test_e42_the_authority_map_and_deferred_register_are_complete() -> None:
    text = AUDIT.read_text(encoding="utf-8")
    for state in ("Phase 6 reviewed Theme", "EvidenceAttachment", "RelationAssertion", "NarrativeInputSnapshot",
                  "NarrativeSynthesis", "NarrativePresentation", "NarrativeDiff", "RenderedNarrative",
                  "RenderedNarrativeDiff"):
        assert f"| {state} |" in text, state
    for item in ("real-world data validation", "real Theme authority shadow", "optional LLM surface wording",
                 "LLM alternative explanation proposal", "persistence", "P4/public integration", "P8 handoff",
                 "P10 personalization", "localization/i18n", "Theme display names", "selected/compact rendering",
                 "external citations/UI expansion", "operational scheduling", "real provider"):
        assert item in text, item
    for klass in ("MANDATORY_BEFORE_PRODUCTION_INTEGRATION", "MANDATORY_BEFORE_REAL_PROVIDER", "NON_BLOCKING_DEFERRED"):
        assert klass in text


def test_e43_the_completion_audit_has_the_required_sections() -> None:
    headings = [line for line in AUDIT.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
    assert len(headings) == 28 and [h.split(".")[0] for h in headings] == [f"## {n}" for n in range(1, 29)]


def test_e44_the_verified_backing_boundary_is_recorded() -> None:
    text = AUDIT.read_text(encoding="utf-8")
    for phrase in ("D-P7-A4B-1", "byte-for-byte", "sole authority", "verified backing material"):
        assert phrase in text, phrase
