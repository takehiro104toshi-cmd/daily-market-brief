"""P7-A4b — 決定論の日本語の描画（A4a の提示 ／ 差分 → 描画済み Narrative）の test matrix A〜BS。

git に依存する境界（BT〜BY: A1 / A2 / A3 / A4a / Phase 6 の byte 凍結・未登録 runtime の検出・runtime の import closure・
module 状態なし）は `test_narrative_intelligence_boundary.py` にある。提示は A2 / A3 の本物の world の synthesis から
A4a の planner で作る。

契約: `docs/databank/PHASE7_NARRATIVE_DETERMINISTIC_RENDERER_CONTRACT.md`。
"""
from __future__ import annotations

import builtins
import copy
import inspect
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.intelligence.core.ids import content_id
from src.intelligence.narrative_intelligence import presentation_model as PM
from src.intelligence.narrative_intelligence import render_templates_ja as RT
from src.intelligence.narrative_intelligence import rendered_model as RM
from src.intelligence.narrative_intelligence import synthesis_model as A1
from src.intelligence.narrative_intelligence import text_renderer as TR
from src.intelligence.narrative_intelligence.narrative_diff import diff_syntheses
from src.intelligence.narrative_intelligence.presentation_model import NarrativePresentation, PresentationSection
from src.intelligence.narrative_intelligence.presentation_planner import plan_presentation
from src.intelligence.narrative_intelligence.rendered_model import NarrativeRenderError, check_text
from src.intelligence.narrative_intelligence.synthesis_engine import synthesize
from src.intelligence.narrative_intelligence.text_renderer import render_diff, render_presentation
from tests.intelligence.test_narrative_pit_assembler import CUT, EARLY, FACT_P, P, Q, R, add_future, day, snap
from tests.intelligence.test_narrative_synthesis_engine import BARE, CTX, build_engine_world
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "docs" / "databank" / "PHASE7_NARRATIVE_DETERMINISTIC_RENDERER_CONTRACT.md"
A4B_MODULES = (RM, RT, TR)
DIGEST = "narinp_" + "0" * 24
#: 描画の registry の digest（version ごとに固定。文言を変えたら RENDERER_VERSION を上げて足す）
REGISTRY_DIGESTS = {"0.1.0": "nartpl_b7488c34dfe57d88908ed19f"}
INTERPRETATION_QUALIFIERS = ("整理されています", "主張しています")
EVALUATIVE_WORDS = ("強ま", "弱ま", "改善", "悪化", "加速", "減速", "上昇", "下落", "好転", "強気", "弱気", "楽観",
                    "悲観", "bullish", "bearish", "良くな", "悪くな", "増した", "減った")
RANKING_WORDS = ("本命", "有力", "第一候補", "最も", "最重要", "中心テーマ", "主役", "一番", "上位", "優先")
RECOMMENDATION_WORDS = ("買い", "売り", "推奨", "投資判断", "目標株価", "期待リターン", "ポジション", "buy", "sell",
                        "recommend")
PERSONA_WORDS = ("初心者", "営業", "顧客", "積極", "保守的", "あなた", "ポートフォリオ")


# ================================================================ world と helper

def syn(root, kind="THEME_STATE", roots=(P,), cutoff=CUT, comparison=None):
    return synthesize(snap(root, kind, roots, cutoff=cutoff, comparison=comparison))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("narrative_renderer") / "data"
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
    root = tmp_path_factory.mktemp("narrative_renderer_future") / "data"
    add_future(root, build_engine_world(root))
    return syn(root, "THEME_SET", (Q, R), cutoff=day(10)), syn(root, "THEME_SET", (Q, R), cutoff=day(15))


def rendered(s):
    return render_presentation(presentation=plan_presentation(s), synthesis=s)


def rendered_diff(before, after):
    return render_diff(diff=diff_syntheses(previous=before, current=after), previous=before, current=after)


def variant(s, *, cutoff, drop=lambda claim: False, extra=()):
    return A1.NarrativeSynthesis(kind=s.kind, subject_root_ids=s.subject_root_ids, cutoff=cutoff,
                                 knowledge_pins=s.knowledge_pins, input_digest=DIGEST,
                                 claims=tuple(c for c in s.claims if not drop(c)) + tuple(extra))


def fails(code, fn, *args, **kwargs):
    with pytest.raises(NarrativeRenderError) as info:
        fn(*args, **kwargs)
    assert info.value.code == code, (info.value.code, info.value.detail)
    return info.value


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


def texts(r):
    return [item.text for item in r.items()] + [s.heading for s in getattr(r, "sections", ())] + [
        g.heading for g in getattr(r, "groups", ())] + [r.title]


def by_rule(r, *rules):
    return [item for item in r.items() if item.rule_id in rules]


def claims_of(s):
    return {c.claim_id: c for c in s.claims}


def attachment_of(claim):
    return [ref for ref in claim.refs if isinstance(ref, A1.EvidenceAttachmentRef)][0]


def labels_of(r):
    return dict(r.theme_labels)


LABEL_RE = "テーマ〈[0-9A-Z]{8}〉"
FIELD_RE = {"theme": LABEL_RE, "source": LABEL_RE, "target": LABEL_RE, "themes": f"{LABEL_RE}(?:、{LABEL_RE})+",
            "relation": "|".join(re.escape(label) for _, label in RT.RELATION_LABELS)}


def pattern_match(item):
    template = next(t for t in RT.TEMPLATES if t.template_id == item.template_id)
    regex = re.escape(template.pattern)
    for name in template.fields:
        regex = regex.replace(re.escape("{" + name + "}"), f"(?P<{name}>{FIELD_RE.get(name, '.+?')})")
    return template, re.fullmatch(regex, item.text)


def all_rendered(state, bare, ctx, theme_set):
    return [rendered(s) for s in (state, bare, ctx, theme_set)]


# ================================================================ A〜D 描画の基本と決定性

def test_a_a_valid_theme_state_render(state) -> None:
    p = plan_presentation(state)
    r = rendered(state)
    assert (r.kind, r.presentation_id, r.source_synthesis_id, r.subject_root_ids) == (
        A1.NarrativeKind.THEME_STATE, p.presentation_id, state.synthesis_id, (P,))
    assert r.title == f"{labels_of(r)[P]}についての整理"
    assert [s.section for s in r.sections] == [s.section.value for s in p.sections]
    assert r.to_dict()["language"] == "ja" and all(item.text.endswith("。") for item in r.items())


def test_b_a_valid_theme_set_render(theme_set) -> None:
    r = rendered(theme_set)
    assert r.kind is A1.NarrativeKind.THEME_SET and r.title == "複数のテーマについての整理（順不同）"
    assert [s.section for s in r.sections] == [s.value for s in PM.SECTION_ORDER]
    assert [root for root, _ in r.theme_labels] == sorted((P, Q, R))


def test_c_replay_is_byte_identical_in_process_and_across_processes(theme_set, tmp_path) -> None:
    first = rendered(theme_set).to_canonical_json()
    assert rendered(theme_set).to_canonical_json() == first
    source = tmp_path / "synthesis.json"
    source.write_text(theme_set.to_canonical_json(), encoding="utf-8")
    code = ("import sys\nfrom src.intelligence.narrative_intelligence.synthesis_model import NarrativeSynthesis\n"
            "from src.intelligence.narrative_intelligence.presentation_planner import plan_presentation\n"
            "from src.intelligence.narrative_intelligence.text_renderer import render_presentation\n"
            "s = NarrativeSynthesis.from_json(open(sys.argv[1], encoding='utf-8').read())\n"
            "sys.stdout.buffer.write(render_presentation(presentation=plan_presentation(s), synthesis=s)"
            ".to_canonical_json().encode('utf-8'))\n")
    for seed in ("0", "4242"):
        out = subprocess.run([sys.executable, "-c", code, str(source)], cwd=REPO_ROOT, capture_output=True,
                             check=True, env={"PYTHONPATH": str(REPO_ROOT), "PATH": "", "PYTHONHASHSEED": seed,
                                              "LC_ALL": "C", "LANG": "C"})
        assert out.stdout.decode("utf-8") == first


GOLDEN_STATE_LINES = (
    "テーマ〈JKMNPQRY〉についての整理",
    "【テーマの状態】",
    "・テーマ〈JKMNPQRY〉は、レビュー済みのテーマとして整理されています。［参照 57b72c85］",
    "【機構】",
    "・テーマ〈JKMNPQRY〉では、機構の影響を受ける領域として「dom1」が整理されています。［参照 01bac98a］",
    "・テーマ〈JKMNPQRY〉では、機構の観測が見込まれる帰結として「c1」が整理されています。［参照 1003f229］",
    "・テーマ〈JKMNPQRY〉では、機構の駆動要因として「d1」が整理されています。［参照 52db7227］",
    "・テーマ〈JKMNPQRY〉では、機構の波及経路として「ch1」が整理されています。［参照 90ff198d］",
    "【材料】",
    "・2026-08-20 00:00 UTC時点の事実の記録が存在します（時刻の扱い: 信頼できる時刻）。［参照 923e91d1］",
    "・2026-08-21 00:00 UTC時点の観測の記録が存在します（時刻の扱い: 信頼できる時刻）。［参照 b33b39a1］",
    "・テーマ〈JKMNPQRY〉に関する文脈の材料として、文書が整理されています。［参照 3be6d7a0］",
    "・テーマ〈JKMNPQRY〉の見方を支持する材料として、事実の記録が整理されています。［参照 73ff8be2］",
    "・テーマ〈JKMNPQRY〉の見方を支持する材料として、観測の記録が整理されています。［参照 b9124159］",
    "・テーマ〈JKMNPQRY〉の見方を支持する材料として、発言が整理されています。［参照 e177fc49］",
    "【矛盾する材料】",
    "・一方、テーマ〈JKMNPQRY〉の見方と矛盾する材料として、報道が整理されています。［参照 1f7cc4a6］",
    "【無効化の条件と材料】",
    "・テーマ〈JKMNPQRY〉の無効化条件「inv1」に関係する材料として、文書が整理されています。［参照 4a637b4f］",
    "・テーマ〈JKMNPQRY〉の解釈が成り立たなくなる条件として、「inv1」が整理されています。［参照 512c2e2a］",
    "・テーマ〈JKMNPQRY〉の無効化条件「inv1」には、関係する材料（文書）が結び付けられていると整理されています。"
    "これはテーマの状態を変えるものではありません。［参照 ba7bebc4］",
    "【不確実性】",
    "・テーマ〈JKMNPQRY〉には、支持する材料と矛盾する材料が併存しています。［参照 6c231e69］",
    "・テーマ〈JKMNPQRY〉の機構は、仮説の段階として整理されています。［参照 b320d2d4］",
)


def test_d_canonical_serialization_and_the_golden_rendering_are_stable(state) -> None:
    r = rendered(state)
    assert r.to_canonical_json() == A1.canonical_json(r.to_dict())
    assert json.loads(r.to_canonical_json()) == r.to_dict()
    assert r.lines() == GOLDEN_STATE_LINES                                                # 文言の変化は検出される
    digest = content_id("nartpl", A1.canonical_json(RT.registry_payload()))
    assert REGISTRY_DIGESTS[RM.RENDERER_VERSION] == digest                               # 文言を変えたら version を上げる


# ================================================================ E〜H 追跡・孤立なし・新しい意味なし

def test_e_every_semantic_item_traces_to_its_presentation_item(theme_set) -> None:
    p = plan_presentation(theme_set)
    r = rendered(theme_set)
    assert [item.claim_ids[0] for item in r.items()] == list(p.claim_ids())
    for item, source in zip(r.items(), p.items()):
        assert item.presentation_item_id == content_id("narpit", A1.canonical_json(
            {"presentation_id": p.presentation_id, "item": source.to_dict()}))
        assert (item.section, item.rule_id, item.visibility, item.theme_root_ids) == (
            source.section.value, source.rule_id, source.visibility.value, source.theme_root_ids)


def test_f_every_rendered_item_retains_its_claim_reference(theme_set) -> None:
    claims = claims_of(theme_set)
    for item in rendered(theme_set).items():
        assert len(item.claim_ids) == 1 and item.claim_ids[0] in claims
        assert item.reference_marker == item.claim_ids[0][7:15]
        assert item.line().endswith(f"［参照 {item.reference_marker}］")


def test_g_no_orphan_sentence(theme_set, state) -> None:
    for s in (state, theme_set):
        r = rendered(s)
        lines = r.lines()
        headings = {h for _, h in RT.SECTION_HEADINGS}
        assert lines[0] == r.title
        for line in lines[1:]:
            assert line.startswith("・") or (line[0] == "【" and line[1:-1] in headings)
        assert len([line for line in lines if line.startswith("・")]) == len(r.items()) == len(s.claims)


def test_h_every_variable_piece_of_text_comes_from_claim_material(theme_set, state, bare, ctx) -> None:
    evidence_labels = dict(RT.EVIDENCE_KIND_LABELS)
    for s in (state, bare, ctx, theme_set):
        r = rendered(s)
        labels = labels_of(r)
        claims = claims_of(s)
        for item in r.items():
            template, match = pattern_match(item)
            assert template.rule_id == item.rule_id and match, item.text
            claim = claims[item.claim_ids[0]]
            values = match.groupdict()
            if "theme" in values:
                assert values["theme"] == labels[claim.roots()[0]]
            refs = {type(ref).__name__: ref for ref in claim.refs}
            if "key" in values:
                assert values["key"] == refs["MechanismComponentRef"].component_key
            if "condition" in values:
                assert values["condition"] in {ref.condition_key for ref in claim.refs
                                               if isinstance(ref, A1.InvalidationConditionRef)} | {
                    ref.invalidation_condition_key for ref in claim.refs if isinstance(ref, A1.EvidenceAttachmentRef)}
            if "evidence" in values:
                kinds = {ref.evidence_kind.value for ref in claim.refs if hasattr(ref, "evidence_kind")}
                assert values["evidence"] in {evidence_labels[k] for k in kinds}
            if "source" in values:
                relation = refs["RelationAssertionRef"]
                assert (values["source"], values["target"]) == (labels[relation.source_root_id],
                                                                 labels[relation.target_root_id])
            if "themes" in values:
                assert values["themes"] == "、".join(labels[root] for root in claim.roots())


# ================================================================ I〜Q 認識 class と role の文言

def test_i_observed_fact_wording_stays_factual(state) -> None:
    facts = by_rule(rendered(state), "P07_OBSERVED_FACT")
    assert len(facts) == 2
    for item in facts:
        assert "存在します" in item.text
        assert not any(word in item.text for word in ("整理", "解釈", "原因", "ため", "により", "示唆", "支持"))


def test_j_reviewed_interpretation_is_visibly_qualified(theme_set) -> None:
    p = {item.claim_id: item for item in plan_presentation(theme_set).items()}
    interpretations = [item for item in rendered(theme_set).items()
                       if p[item.claim_ids[0]].epistemic_class is A1.EpistemicClass.REVIEWED_INTERPRETATION]
    assert interpretations
    for item in interpretations:
        assert any(q in item.text for q in INTERPRETATION_QUALIFIERS), item.text
        assert not any(word in item.text for word in ("が原因です", "に違いありません", "確実", "明らかに", "断定"))
    assert {t.epistemic_class for t in RT.TEMPLATES if "整理されています" in t.pattern or "主張しています" in t.pattern} >= {
        "REVIEWED_INTERPRETATION"}


def test_k_supports_is_support_never_proof(state) -> None:
    supports = by_rule(rendered(state), "P03_SUPPORTS")
    assert len(supports) == 3
    for item in supports:
        assert "支持する材料" in item.text
        assert not any(word in item.text for word in ("証明", "確定", "間違いない", "裏付けられた", "確実"))


def test_l_contradiction_is_explicit(state) -> None:
    [item] = by_rule(rendered(state), "P05_CONTRADICTS")
    assert item.text.startswith("一方、") and "矛盾する材料" in item.text and "文脈" not in item.text
    assert item.section == "CONTRADICTION" and item.visibility == "REQUIRED"


def test_m_context_remains_context(state, ctx) -> None:
    for s in (state, ctx):
        [item] = by_rule(rendered(s), "P04_CONTEXT")
        assert "文脈の材料" in item.text
        assert not any(word in item.text for word in ("支持", "裏付", "反証", "矛盾"))


def test_n_the_invalidation_condition_is_distinguished(state) -> None:
    [item] = by_rule(rendered(state), "P08_INVALIDATION_CONDITION")
    assert "成り立たなくなる条件" in item.text and "「inv1」" in item.text and "材料" not in item.text


def test_o_invalidating_evidence_is_distinguished_and_decides_no_governance(state) -> None:
    r = rendered(state)
    [attachment] = by_rule(r, "P06_INVALIDATES")
    [link] = by_rule(r, "P09_INVALIDATING_EVIDENCE")
    assert "無効化条件「inv1」に関係する材料" in attachment.text
    assert "結び付けられている" in link.text and "テーマの状態を変えるものではありません" in link.text
    for item in (attachment, link):
        assert not any(word in item.text for word in ("は無効です", "無効になりました", "無効化されました", "取り消"))


def test_p_every_uncertainty_is_visible_without_numbers(state, bare, ctx, theme_set) -> None:
    expected = {"NO_SUPPORTING_EVIDENCE": "T10", "SINGLE_SOURCE_EVIDENCE": "T11", "STALE_EVIDENCE": "T12",
                "CONTESTED_EVIDENCE": "T13", "MECHANISM_HYPOTHESIZED": "T14"}
    seen = set()
    for s in (state, bare, ctx, theme_set):
        p = {item.claim_id: item for item in plan_presentation(s).items()}
        uncertain = [item for item in rendered(s).items() if item.section == "UNCERTAINTY"]
        assert len(uncertain) == len([c for c in s.claims if c.uncertainty_code])
        for item in uncertain:
            code = p[item.claim_ids[0]].uncertainty_code.value
            assert item.template_id.startswith(expected[code]) and item.visibility == "REQUIRED"
            assert not re.search(r"[0-9%％]", re.sub(LABEL_RE, "", item.text))            # 確率・数値の確信度なし
            seen.add(code)
    assert seen >= {"NO_SUPPORTING_EVIDENCE", "SINGLE_SOURCE_EVIDENCE", "CONTESTED_EVIDENCE", "MECHANISM_HYPOTHESIZED"}
    assert {t.variant for t in RT.TEMPLATES if t.rule_id == "P10_UNCERTAINTY"} == set(expected)


def test_q_alternatives_are_neutral_parallel_and_unranked(theme_set) -> None:
    r = rendered(theme_set)
    [item] = by_rule(r, "P14_ALTERNATIVES")
    assert "並列" in item.text and "順不同" in item.text
    assert not any(word in item.text for word in RANKING_WORDS)
    labels = labels_of(r)
    positions = [item.text.index(labels[root]) for root in item.theme_root_ids]
    assert positions == sorted(positions)                                                  # root id の順（順位ではない）


# ================================================================ R〜U relation と SOURCE_ASSERTED

def relation_items(s):
    r = rendered(s)
    claims = claims_of(s)
    return r, [(item, [ref for ref in claims[item.claim_ids[0]].refs if isinstance(ref, A1.RelationAssertionRef)][0])
               for item in by_rule(r, "P12_HUMAN_ASSERTED_RELATION", "P13_SOURCE_ASSERTED_RELATION")]


def test_r_relation_direction_is_preserved(theme_set) -> None:
    r, pairs = relation_items(theme_set)
    labels = labels_of(r)
    assert len(pairs) == 2
    for item, relation in pairs:
        source, target = labels[relation.source_root_id], labels[relation.target_root_id]
        assert item.text.index(source) < item.text.index(target)
        assert f"{source}が{target}{dict(RT.RELATION_LABELS)[relation.relation_type.value]}" in item.text


def test_s_no_transitive_or_invented_relation(theme_set) -> None:
    r, pairs = relation_items(theme_set)
    assert len(pairs) == len([c for c in theme_set.claims if c.predicate in A1.RELATION_PREDICATES])
    for item, _ in pairs:
        assert sum(label in item.text for label in labels_of(r).values()) == 2
    assert not [item for item in r.items() if item.section != "RELATION" and "関係が" in item.text]


def test_t_the_source_asserted_qualifier_is_mandatory(theme_set) -> None:
    _, pairs = relation_items(theme_set)
    [(item, relation)] = [(i, rel) for i, rel in pairs if rel.assertion_class.value == "SOURCE_ASSERTED"]
    assert item.template_id == "T17_SOURCE_ASSERTED_RELATION"
    assert item.text.startswith("出典は、") and "出典による主張であり" in item.text
    assert "この説明が主張する関係ではありません" in item.text
    assert [t.template_id for t in RT.TEMPLATES if t.rule_id == "P13_SOURCE_ASSERTED_RELATION"] == [
        "T17_SOURCE_ASSERTED_RELATION"]


def test_u_source_asserted_never_reads_as_an_established_relation(theme_set) -> None:
    _, pairs = relation_items(theme_set)
    for item, relation in pairs:
        if relation.assertion_class.value == "SOURCE_ASSERTED":
            assert "レビュー済みの解釈として整理されています" not in item.text
        else:
            assert not item.text.startswith("出典は")


# ================================================================ V〜Y 変化の文言

def test_v_no_comparison_means_no_change_wording(state) -> None:
    r = rendered(state)
    assert "CHANGE" not in [s.section for s in r.sections]
    assert not [text for text in texts(r) if "変化" in text or "比較" in text]


def test_w_change_wording_is_structural(theme_set) -> None:
    changes = by_rule(rendered(theme_set), "P11_CHANGE")
    assert len(changes) == len([c for c in theme_set.claims if c.predicate is A1.Predicate.CHANGED_BETWEEN_CUTOFFS])
    labels = {label for _, label in RT.CHANGE_KIND_LABELS}
    for item in changes:
        assert "構造上の変化が導かれています" in item.text
        assert any(f"「{label}」" in item.text for label in labels)


def test_x_y_no_strengthened_weakened_bullish_or_bearish_wording(state, bare, ctx, theme_set, early_set,
                                                                 late_set) -> None:
    registry = strings(RT.registry_payload())
    outputs = [text for r in all_rendered(state, bare, ctx, theme_set) for text in texts(r)]
    outputs += texts(rendered_diff(early_set, late_set))
    for text in registry + outputs:
        assert not any(word in text.lower() for word in EVALUATIVE_WORDS), text


# ================================================================ Z〜AD 見出しと Theme の順

def test_z_headings_are_fixed_japanese(theme_set) -> None:
    fixed = dict(RT.SECTION_HEADINGS)
    assert set(fixed) == {s.value for s in PM.SectionKind}
    for section in rendered(theme_set).sections:
        assert section.heading == fixed[section.section] and not re.search(r"[A-Za-z]", section.heading)
    assert [h for _, h in RT.DIFF_HEADINGS] == ["追加された説明要素", "なくなった説明要素", "変わらず存在する説明要素"]


def test_aa_heading_order_is_deterministic(state, theme_set) -> None:
    for s in (state, theme_set):
        order = [PM.SECTION_ORDER.index(PM.SectionKind(section.section)) for section in rendered(s).sections]
        assert order == sorted(order)


def test_ab_heading_order_carries_no_importance_metadata(theme_set) -> None:
    keys = set(strings(rendered(theme_set).to_dict()))
    assert not keys & {"priority", "importance", "rank", "order", "index", "weight", "score"}
    assert RM.HEADING_ORDER_MEANING == "見出しの順は読みやすさのための提示の順で、重要度の順位ではありません"
    assert RM.HEADING_ORDER_MEANING in CONTRACT.read_text(encoding="utf-8")


def test_ac_theme_order_is_not_ranking(world, theme_set) -> None:
    r = rendered(theme_set)
    assert [item.theme_root_ids[0] for item in by_rule(r, "P01_STATE")] == sorted((P, Q, R))
    other = syn(world[0], "THEME_SET", (R, Q, P), comparison=EARLY)
    assert rendered(other).to_canonical_json() == r.to_canonical_json()
    assert all(re.fullmatch("テーマ〈[0-9A-Z]{8}〉", label) and label.endswith(f"{root[-8:]}〉")
               for root, label in r.theme_labels)                                          # 序数でない中立な label


def test_ad_no_dominant_theme_wording(state, bare, ctx, theme_set) -> None:
    for r in all_rendered(state, bare, ctx, theme_set):
        for text in texts(r):
            assert not any(word in text for word in RANKING_WORDS), text
    assert not any(word in text for text in strings(RT.registry_payload()) for word in RANKING_WORDS)


# ================================================================ AE〜AJ FULL・REQUIRED を落とせない

def test_ae_full_rendering_retains_every_required_item(state, theme_set) -> None:
    for s in (state, theme_set):
        p = plan_presentation(s)
        r = rendered(s)
        required = {item.claim_id for item in p.items() if item.visibility is PM.Visibility.REQUIRED}
        assert required and required <= {item.claim_ids[0] for item in r.items()}
        assert {item.claim_ids[0] for item in r.items() if item.visibility == "REQUIRED"} == required


def test_af_there_is_no_selected_mode_to_bypass_a4a() -> None:
    for fn in (render_presentation, render_diff):
        parameters = inspect.signature(fn).parameters
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty
                   for p in parameters.values())
        assert not set(parameters) & {"selection", "claim_ids", "selected", "include", "exclude", "mode", "compact"}
    assert not [name for name in dir(TR) if "select" in name.lower()]


def without(p, *, section=None, claim_id=None):
    sections = []
    for group in p.sections:
        if group.section is section:
            continue
        items = tuple(item for item in group.items if item.claim_id != claim_id)
        if items:
            sections.append(PresentationSection(section=group.section, items=items))
    return NarrativePresentation(kind=p.kind, subject_root_ids=p.subject_root_ids,
                                 source_synthesis_id=p.source_synthesis_id, sections=tuple(sections))


@pytest.mark.parametrize("fixture,section", [("state", PM.SectionKind.CONTRADICTION),
                                             ("state", PM.SectionKind.INVALIDATION),
                                             ("state", PM.SectionKind.UNCERTAINTY),
                                             ("theme_set", PM.SectionKind.ALTERNATIVES)],
                         ids=["ag_contradiction", "ah_invalidation", "ai_uncertainty", "aj_alternatives"])
def test_ag_ah_ai_aj_required_sections_cannot_be_dropped(request, fixture, section) -> None:
    s = request.getfixturevalue(fixture)
    dropped = without(plan_presentation(s), section=section)                              # A4a としては作れる
    assert dropped.presentation_id != plan_presentation(s).presentation_id
    fails("PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=dropped, synthesis=s)


# ================================================================ AK〜AO 差分の描画

def group(rd, category):
    found = [g for g in rd.groups if g.category == category]
    return found[0].items if found else ()


def test_ak_added_is_rendered_structurally(future_pair) -> None:
    before, after = future_pair
    rd = rendered_diff(before, after)
    [added] = group(rd, "ADDED")
    assert [g.heading for g in rd.groups if g.category == "ADDED"] == ["追加された説明要素"]
    current = {item.claim_ids[0]: item for item in rendered(after).items()}
    assert added.text == current[added.claim_ids[0]].text and added.rule_id == "P12_HUMAN_ASSERTED_RELATION"
    assert rd.current_presentation_id == plan_presentation(after).presentation_id


def test_al_removed_is_rendered_structurally(early_set, late_set) -> None:
    rd = rendered_diff(early_set, late_set)
    removed = group(rd, "REMOVED")
    previous = {item.claim_ids[0]: item for item in rendered(early_set).items()}
    assert removed and all(item.text == previous[item.claim_ids[0]].text for item in removed)
    assert [g.heading for g in rd.groups if g.category == "REMOVED"] == ["なくなった説明要素"]
    assert rd.title.endswith("までの説明要素の差分")


def test_am_an_added_support_is_not_strengthening(state) -> None:
    [support] = [c for c in state.claims if c.predicate is A1.Predicate.EVIDENCE_ATTACHED
                 and attachment_of(c).ref_id == FACT_P]
    earlier = variant(state, cutoff=day(9), drop=lambda c: c.claim_id == support.claim_id)
    rd = rendered_diff(earlier, state)
    [added] = group(rd, "ADDED")
    assert added.claim_ids == (support.claim_id,) and "支持する材料" in added.text
    for text in texts(rd):
        assert not any(word in text for word in EVALUATIVE_WORDS), text


def test_an_a_removed_contradiction_is_not_improvement(state) -> None:
    dropped = {c.claim_id for c in state.claims if (c.predicate is A1.Predicate.EVIDENCE_ATTACHED
                                                    and attachment_of(c).role.value == "CONTRADICTS")
               or (c.uncertainty_code and c.uncertainty_code.value == "CONTESTED_EVIDENCE")}
    later = variant(state, cutoff=day(11), drop=lambda c: c.claim_id in dropped)
    rd = rendered_diff(state, later)
    assert {item.claim_ids[0] for item in group(rd, "REMOVED")} == dropped and not group(rd, "ADDED")
    for text in texts(rd):
        assert not any(word in text for word in EVALUATIVE_WORDS + ("解消された", "安心")), text


def test_ao_no_fuzzy_diff_semantics(state) -> None:
    component = next(c for c in state.claims if c.predicate is A1.Predicate.RECORDS_MECHANISM_COMPONENT)
    ref = component.refs[0]
    similar = A1.NarrativeClaim(epistemic_class=component.epistemic_class, claim_kind=component.claim_kind,
                                predicate=component.predicate,
                                refs=(A1.MechanismComponentRef(root_id=ref.root_id, observation_id=ref.observation_id,
                                                               component_type=ref.component_type,
                                                               component_key=ref.component_key + "_v2"),))
    later = variant(state, cutoff=day(11), drop=lambda c: c.claim_id == component.claim_id, extra=(similar,))
    rd = rendered_diff(state, later)
    assert [i.claim_ids[0] for i in group(rd, "REMOVED")] == [component.claim_id]
    assert [i.claim_ids[0] for i in group(rd, "ADDED")] == [similar.claim_id]
    assert f"「{ref.component_key}_v2」" in group(rd, "ADDED")[0].text
    assert {g.category for g in rd.groups} <= {"ADDED", "REMOVED", "UNCHANGED"}


# ================================================================ AP〜AU 参照の印・path・安全な文字

def test_ap_reference_markers_are_deterministic_and_shared_by_the_diff(early_set, late_set) -> None:
    r = rendered(late_set)
    markers = [item.reference_marker for item in r.items()]
    assert len(set(markers)) == len(markers) and all(re.fullmatch(r"[0-9a-f]{8}", m) for m in markers)
    assert markers == [item.reference_marker for item in rendered(late_set).items()]
    diff_markers = {item.claim_ids[0]: item.reference_marker for item in rendered_diff(early_set, late_set).items()}
    assert all(diff_markers[item.claim_ids[0]] == item.reference_marker for item in r.items())


def test_aq_ar_no_machine_path_or_journal_name(world, state, theme_set, early_set, late_set) -> None:
    for payload in (rendered(state).to_dict(), rendered(theme_set).to_dict(),
                    rendered_diff(early_set, late_set).to_dict()):
        for text in strings(payload):
            assert "/" not in text and "\\" not in text
            assert str(world[0]) not in text and "journal" not in text and ".json" not in text


@pytest.mark.parametrize("bad", ["http", "www.example", "mailto:a", "javascript:x", "data_root.jsonl",
                                 "journal", "api_key", "<b>x</b>", "a&b", "*x*", "#x", "`x`", "[x](y)", "a|b",
                                 "a/b", "a\\b", "a\nb", "a\tb", "a\x00b", "a‮b", "~x~", "{x}", "", None])
def test_as_at_au_unsafe_text_is_rejected(bad) -> None:
    fails("UNSAFE_TEXT", check_text, bad, 100, "text")


def test_as_a_url_like_key_fails_closed(state) -> None:
    component = next(c for c in state.claims if c.predicate is A1.Predicate.RECORDS_MECHANISM_COMPONENT)
    ref = component.refs[0]
    hostile = A1.NarrativeClaim(epistemic_class=component.epistemic_class, claim_kind=component.claim_kind,
                                predicate=component.predicate,
                                refs=(A1.MechanismComponentRef(root_id=ref.root_id, observation_id=ref.observation_id,
                                                               component_type=ref.component_type,
                                                               component_key="www.example.com"),))
    s = variant(state, cutoff=state.cutoff, extra=(hostile,))
    fails("UNSAFE_TEXT", rendered, s)


def test_at_au_rendered_strings_hold_no_markup_or_control_characters(state, theme_set, early_set, late_set) -> None:
    outputs = strings(rendered(state).to_dict()) + strings(rendered(theme_set).to_dict()) + list(
        rendered(theme_set).lines()) + strings(rendered_diff(early_set, late_set).to_dict())
    for text in outputs:
        assert not re.search(r"[<>&*#`\[\]()|~{}\x00-\x1f\x7f‪-‮]", text), text


# ================================================================ AV〜AX 長さの上限・切り詰めなし

def test_av_lengths_are_bounded(theme_set) -> None:
    r = rendered(theme_set)
    assert all(len(item.text) <= RM.MAX_ITEM_TEXT and len(item.reference_marker) == 8 for item in r.items())
    assert all(len(section.heading) <= RM.MAX_HEADING for section in r.sections) and len(r.title) <= RM.MAX_TITLE
    assert len(r.items()) <= RM.MAX_RENDERED_ITEMS


def test_aw_ax_limits_fail_closed_without_truncation(state, monkeypatch) -> None:
    longest = max(len(item.text) for item in rendered(state).items())
    monkeypatch.setattr(RM, "MAX_ITEM_TEXT", longest - 1)
    fails("RENDER_LIMIT_EXCEEDED", rendered, state)                                        # 切り詰めた結果を返さない
    monkeypatch.undo()
    monkeypatch.setattr(RM, "MAX_RENDERED_ITEMS", len(state.claims) - 1)
    fails("RENDER_LIMIT_EXCEEDED", rendered, state)
    monkeypatch.undo()
    for item in rendered(state).items():
        template, match = pattern_match(item)
        assert match and item.text.endswith("。")                                            # 文は template の全体


# ================================================================ AY〜BC identity・version・言語・path・時計

def test_ay_the_rendered_id_is_content_addressed_and_stable(state, theme_set) -> None:
    r = rendered(theme_set)
    assert r.rendered_id == rendered(theme_set).rendered_id and re.fullmatch(r"narrnd_[0-9a-f]{24}", r.rendered_id)
    payload = r.to_dict()
    del payload["rendered_id"]
    assert r.rendered_id == content_id("narrnd", A1.canonical_json(payload))
    assert rendered(state).rendered_id != r.rendered_id


def test_az_ba_the_renderer_version_and_the_language_are_bound(state, monkeypatch) -> None:
    r = rendered(state)
    assert r.to_dict()["renderer"] == {"name": "narrative_renderer_ja", "version": "0.1.0"}
    assert RM.LANGUAGE == "ja" and r.to_dict()["language"] == "ja"
    monkeypatch.setattr(RM, "RENDERER_VERSION", "0.2.0")
    assert rendered(state).rendered_id != r.rendered_id
    monkeypatch.undo()
    monkeypatch.setattr(RM, "LANGUAGE", "en")
    assert rendered(state).rendered_id != r.rendered_id
    monkeypatch.undo()
    assert "language" not in inspect.signature(render_presentation).parameters             # 0.1.0 は日本語だけ


def test_bb_paths_and_mtimes_are_irrelevant(world, state, tmp_path) -> None:
    (tmp_path / "elsewhere").mkdir()
    other = tmp_path / "elsewhere" / "data"
    build_engine_world(other)
    expected = rendered(state).to_canonical_json()
    assert rendered(syn(other)).to_canonical_json() == expected
    for path in other.rglob("*"):
        if path.is_file():
            os.utime(path, (0, 0))
    assert rendered(syn(other)).to_canonical_json() == expected


def test_bc_no_clock_or_randomness_changes_the_rendering(theme_set, early_set, late_set, monkeypatch) -> None:
    import random
    import secrets
    import time
    import uuid
    expected = (rendered(theme_set).to_canonical_json(), rendered_diff(early_set, late_set).to_canonical_json())

    def forbidden(*args, **kwargs):
        raise AssertionError("A4b used a clock or randomness")
    for module, name in ((time, "time"), (time, "time_ns"), (time, "monotonic"), (time, "localtime"),
                         (random, "random"), (random, "shuffle"), (secrets, "token_hex"), (uuid, "uuid4"),
                         (os, "urandom"), (os, "getenv")):
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(os, "environ", {})
    assert (rendered(theme_set).to_canonical_json(),
            rendered_diff(early_set, late_set).to_canonical_json()) == expected


# ================================================================ BD〜BH 改ざん・未対応の template

def tampered(value, mutate):
    clone = copy.deepcopy(value)
    mutate(clone)
    return clone


def test_bd_a_tampered_presentation_id_is_rejected(state) -> None:
    p = plan_presentation(state)
    for mutate in (lambda t: object.__setattr__(t, "presentation_id", "narprs_" + "0" * 24),
                   lambda t: object.__setattr__(t, "source_synthesis_id", "narsyn_" + "0" * 24),
                   lambda t: object.__setattr__(t, "sections", t.sections[1:]),
                   lambda t: object.__setattr__(t, "score", 1)):
        fails("PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=tampered(p, mutate),
              synthesis=state)
    for value in (None, p.to_dict(), p.to_canonical_json(), state):
        fails("INVALID_PRESENTATION", render_presentation, presentation=value, synthesis=state)
    fails("INVALID_PRESENTATION", render_presentation, presentation=p, synthesis=None)


def test_be_a_tampered_item_is_rejected(state) -> None:
    p = plan_presentation(state)
    for mutate in (lambda t: object.__setattr__(t.sections[0].items[0], "claim_id", "narclm_" + "0" * 24),
                   lambda t: object.__setattr__(t.sections[3].items[0], "visibility", PM.Visibility.ELIGIBLE),
                   lambda t: object.__setattr__(t.sections[3].items[0], "section", PM.SectionKind.EVIDENCE),
                   lambda t: object.__setattr__(t.sections[3].items[0], "evidence_role", A1.EvidenceRole.CONTEXT),
                   lambda t: object.__setattr__(t.sections[0].items[0], "rule_id", "P07_OBSERVED_FACT")):
        fails("PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=tampered(p, mutate),
              synthesis=state)


def test_bf_a_missing_required_item_or_a_foreign_synthesis_is_rejected(state, bare) -> None:
    p = plan_presentation(state)
    required = [item for item in p.items() if item.visibility is PM.Visibility.REQUIRED]
    for item in required:
        fails("PRESENTATION_INTEGRITY_FAILURE", render_presentation,
              presentation=without(p, claim_id=item.claim_id), synthesis=state)
    fails("PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=p, synthesis=bare)
    tampered_synthesis = tampered(state, lambda t: object.__setattr__(t.claims[0], "claim_id", "narclm_" + "0" * 24))
    fails("PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=p, synthesis=tampered_synthesis)


def test_bg_tampered_source_asserted_metadata_is_rejected(theme_set, early_set, late_set) -> None:
    p = plan_presentation(theme_set)
    relation = [i for i, group_ in enumerate(p.sections) if group_.section is PM.SectionKind.RELATION][0]

    def source_item(t):
        return [item for item in t.sections[relation].items
                if item.assertion_class is A1.AssertionClass.SOURCE_ASSERTED][0]
    for mutate in (lambda t: object.__setattr__(source_item(t), "assertion_class", A1.AssertionClass.HUMAN_ASSERTED),
                   lambda t: object.__setattr__(source_item(t), "assertion_class", None),
                   lambda t: object.__setattr__(source_item(t), "predicate", A1.Predicate.HUMAN_ASSERTED_RELATION),
                   lambda t: object.__setattr__(source_item(t), "rule_id", "P12_HUMAN_ASSERTED_RELATION")):
        fails("PRESENTATION_INTEGRITY_FAILURE", render_presentation, presentation=tampered(p, mutate),
              synthesis=theme_set)
    d = diff_syntheses(previous=early_set, current=late_set)
    fails("PRESENTATION_INTEGRITY_FAILURE", render_diff,
          diff=tampered(d, lambda t: object.__setattr__(t.items[0], "category", PM.DiffCategory.ADDED)),
          previous=early_set, current=late_set)
    fails("PRESENTATION_INTEGRITY_FAILURE", render_diff, diff=d, previous=late_set, current=early_set)
    fails("INVALID_PRESENTATION", render_diff, diff=d.to_dict(), previous=early_set, current=late_set)


def test_bh_an_unsupported_template_or_label_fails_closed(state, theme_set, monkeypatch) -> None:
    monkeypatch.setattr(RT, "TEMPLATES", tuple(t for t in RT.TEMPLATES if t.template_id != "T17_SOURCE_ASSERTED_RELATION"))
    fails("UNSUPPORTED_TEMPLATE", rendered, theme_set)
    monkeypatch.undo()
    monkeypatch.setattr(TR, "CHANGE_KIND_LABELS", tuple(p for p in RT.CHANGE_KIND_LABELS if p[0] != "GOVERNANCE_CHANGED"))
    fails("UNSUPPORTED_TEMPLATE", rendered, theme_set)
    monkeypatch.undo()
    monkeypatch.setattr(RT, "TEMPLATES", tuple(RT.Template(t.template_id, t.rule_id, t.variant, "OBSERVED_FACT",
                                                           t.fields, t.pattern) if t.template_id == "T01_STATE" else t
                                               for t in RT.TEMPLATES))
    fails("UNSUPPORTED_TEMPLATE", rendered, state)                                        # 解釈の文型を事実に使わない
    monkeypatch.undo()
    fails("UNSUPPORTED_TEMPLATE", RT.template_for, "P99_UNKNOWN", "")
    fails("UNSUPPORTED_TEMPLATE", RT.fill, RT.TEMPLATES[0], {"theme": "x", "extra": "y"})
    assert len({(t.rule_id, t.variant) for t in RT.TEMPLATES}) == len(RT.TEMPLATES)        # 汎用の fallback なし
    rules = {rule.rule_id for rule in PM.PRESENTATION_RULES}
    assert {t.rule_id for t in RT.TEMPLATES} == rules
    for code in A1.UncertaintyCode:
        RT.template_for("P10_UNCERTAINTY", code.value)
    for enum, table in ((A1.ChangeKind, RT.CHANGE_KIND_LABELS), (A1.RelationType, RT.RELATION_LABELS),
                        (A1.ComponentType, RT.COMPONENT_LABELS), (A1.EvidenceKind, RT.EVIDENCE_KIND_LABELS)):
        assert [key for key, _ in table] == [e.value for e in enum]                         # 全域・重複なし
    assert [key for key, _ in RT.TIME_QUALITY_LABELS] == [q.value for q in A1.OBSERVED_FACT_TIME_QUALITIES]


# ================================================================ BI〜BS 永続化・純粋な実行・境界・推奨なし

def test_bi_nothing_is_persisted_or_loadable() -> None:
    for model in (RM.RenderedNarrative, RM.RenderedNarrativeDiff, RM.RenderedItem, RM.RenderedSection,
                  RM.RenderedDiffGroup):
        assert not [name for name in ("from_dict", "from_json", "save", "load", "write", "persist", "path")
                    if hasattr(model, name)], model
    for fn in (render_presentation, render_diff):
        assert not set(inspect.signature(fn).parameters) & {"data_root", "path", "root", "store", "journal", "cache",
                                                             "output", "out_dir"}


def test_bj_bk_zero_write_and_no_network(world, state, theme_set, early_set, late_set, monkeypatch) -> None:
    def inventory(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    data_before = inventory(world[0])
    repo_before = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    inputs = [s.to_canonical_json() for s in (state, theme_set, early_set, late_set)]
    constants = [{name: repr(value) for name, value in vars(module).items() if not name.startswith("__")}
                 for module in A4B_MODULES]
    expected = (rendered(theme_set).to_canonical_json(), rendered_diff(early_set, late_set).to_canonical_json())

    def forbidden(*args, **kwargs):
        raise AssertionError("A4b touched a file or the network")
    for module, name in ((builtins, "open"), (os, "open"), (os, "replace"), (os, "rename"), (os, "remove"),
                         (os, "makedirs"), (os, "mkdir"), (socket, "socket"), (socket, "create_connection")):
        monkeypatch.setattr(module, name, forbidden)
    for _ in range(5):
        assert (rendered(theme_set).to_canonical_json(),
                rendered_diff(early_set, late_set).to_canonical_json()) == expected
    monkeypatch.undo()
    assert inventory(world[0]) == data_before
    assert subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True,
                          text=True).stdout == repo_before
    assert [s.to_canonical_json() for s in (state, theme_set, early_set, late_set)] == inputs
    assert [{name: repr(value) for name, value in vars(module).items() if not name.startswith("__")}
            for module in A4B_MODULES] == constants


def test_bl_no_llm_provider_or_ai_fallback() -> None:
    for module in A4B_MODULES:
        source = executable_source(Path(module.__file__)).lower()
        words = set(re.findall(r"[a-z0-9]+", source))
        for token in ("llm", "prompt", "provider", "anthropic", "openai", "completion", "generation", "gpt",
                      "claude", "html", "markdown", "pdf", "notifier", "pages", "email", "slack", "scheduler"):
            assert token not in words, (module.__name__, token)


@pytest.mark.parametrize("module", A4B_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[1])
def test_bm_bn_bo_bp_bq_imports_are_only_a4a_a1_and_core(module) -> None:
    assert imported_modules(Path(module.__file__)) <= {
        "__future__", "re", "dataclasses", "datetime", "typing", "..core.ids", ".synthesis_model",
        ".presentation_model", ".presentation_planner", ".narrative_diff", ".rendered_model", ".render_templates_ja"}


def test_br_no_personalization(state, bare, ctx, theme_set) -> None:
    for fn in (render_presentation, render_diff):
        assert not set(inspect.signature(fn).parameters) & {"audience", "reader", "persona", "mode", "profile",
                                                             "customer", "portfolio", "risk_appetite"}
    for text in strings(RT.registry_payload()) + [t for r in all_rendered(state, bare, ctx, theme_set)
                                                  for t in texts(r)]:
        assert not any(word in text for word in PERSONA_WORDS), text


def test_bs_no_recommendation_semantics(state, bare, ctx, theme_set, early_set, late_set) -> None:
    outputs = strings(RT.registry_payload()) + [t for r in all_rendered(state, bare, ctx, theme_set) for t in texts(r)]
    outputs += texts(rendered_diff(early_set, late_set))
    for text in outputs:
        assert not any(word in text.lower() for word in RECOMMENDATION_WORDS), text


def test_the_contract_states_the_rule_and_the_authority_class() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert RM.AUTHORITY_CLASS == ("DERIVED", "NON_AUTHORITY", "NON_PERSISTENT")
    for phrase in (RM.RENDERING_RULE, *RM.FAILURE_CODES, RM.RENDERER_NAME):
        assert phrase in text, phrase
    assert (TR.SUPPORTED_PRESENTATION_SCHEMA_VERSION, TR.SUPPORTED_PRESENTATION_RULESET) == (
        PM.PRESENTATION_SCHEMA_VERSION, (PM.PRESENTATION_RULESET_NAME, PM.PRESENTATION_RULESET_VERSION))
    assert (TR.SUPPORTED_DIFF_SCHEMA_VERSION, TR.SUPPORTED_DIFF_RULESET) == (
        PM.DIFF_SCHEMA_VERSION, (PM.DIFF_RULESET_NAME, PM.DIFF_RULESET_VERSION))
