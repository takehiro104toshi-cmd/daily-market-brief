"""P6-B7C — LLM 入力 manifest（point-in-time grounding）の test。

「caller が決めた cutoff 時点で、LLM に何を見せてよかったか」を、決定論・最小投影・opaque handle・非 authority・
replay 可能・fail closed の各面から固定する。LLM・provider・意味検証・bridge・store は無い。

データはすべて synthetic（Foundation 代表 world ＋ B5B relation ＋ B4 の合成入力）。書き込みは `tmp_path` のみ。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.facts.model import FactStatus
from src.intelligence.theme_intelligence import llm_manifest_builder as B
from src.intelligence.theme_intelligence import llm_manifest_model as M
from src.intelligence.theme_intelligence.entity_catalog import entity_catalog_path, load_entity_catalog_version
from src.intelligence.theme_intelligence.lifecycle_model import default_lifecycle_policy
from src.intelligence.theme_intelligence.llm_manifest_builder import LlmManifestScope, build_input_manifest
from src.intelligence.theme_intelligence.llm_manifest_model import (MANIFEST_SCHEMA_VERSION, LlmInputManifest,
                                                                    ManifestError, ManifestFamily)
from src.intelligence.theme_intelligence.llm_proposal_model import (GenerationOutcome, HandleKind,
                                                                    LlmGenerationRecord, LlmGenerationRequest, LlmTask,
                                                                    handle_kind)
from src.intelligence.theme_intelligence.monitoring_model import MonitoringCategory, MonitoringSubjectKind, SalientStateKind
from src.intelligence.theme_intelligence.monitoring_runner import run_monitoring
from src.intelligence.theme_intelligence.monitoring_store import MonitoringReviewStore
from src.intelligence.theme_intelligence.proposal_model import DecisionKind
from src.intelligence.theme_intelligence.proposal_store import ProposalStore
from src.intelligence.theme_intelligence.proposal_store import authority_paths as proposal_paths
from src.intelligence.theme_intelligence.relation_model import RelationType
from src.intelligence.theme_intelligence.relation_proposal_model import RelationDecisionKind
from src.intelligence.theme_intelligence.relation_proposal_store import RelationProposalStore
from src.intelligence.theme_intelligence.relation_proposal_store import authority_paths as relation_proposal_paths
from src.intelligence.theme_intelligence.relation_store import ThemeRelationStore
from src.intelligence.theme_intelligence.relation_store import authority_paths as relation_paths
from src.intelligence.theme_intelligence.taxonomy import load_taxonomy_version, taxonomy_path
from src.intelligence.themes.model import EvidenceKind, EvidenceRole, GovernanceEventType
from src.intelligence.themes.resolver import resolve_at_data_root
from src.intelligence.themes.revision import attach_evidence
from src.intelligence.themes.store import ThemeStore
from src.intelligence.themes.store import authority_paths as theme_paths
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_discovery import document, fact, news, observation
from tests.intelligence.test_theme_model import ROOT_A, ROOT_B, ROOT_C, attachment, event, provenance
from tests.intelligence.test_theme_monitoring_e2e import RULES
from tests.intelligence.test_theme_monitoring_model import finding as synthetic_finding
from tests.intelligence.test_theme_monitoring_model import state
from tests.intelligence.test_theme_proposal import decision, evidence_candidate
from tests.intelligence.test_theme_relation import causal, retraction, sourced
from tests.intelligence.test_theme_relation_proposal import decide
from tests.intelligence.test_theme_relation_proposal import proposal as relation_candidate
from tests.intelligence.theme_foundation_fixtures import build_world, day
from tests.intelligence.theme_freeze_pins import is_new_llm_module

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
B7B_ANCHOR = "e2aa991490d2e05dd30fe65bbea3f3ee091be66c"
CUT = datetime(2026, 9, 22, tzinfo=UTC)                  # taxonomy / catalog 0.2.0 の公開後
FUTURE = datetime(2026, 9, 25, 12, tzinfo=UTC)
LATER = datetime(2026, 9, 27, tzinfo=UTC)
SCOPE = (ROOT_A, ROOT_B)
ALL_TASKS = tuple(LlmTask)


# ---------------------------------------------------------------- fixtures（synthetic）


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUT)


@pytest.fixture(scope="module")
def catalog():
    return load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0",
                                       cutoff=CUT)


def _seed(root: Path) -> dict:
    """merge 前の代表 world（ROOT_A は RETIRED、ROOT_B は候補）＋ B5B の 2 辺 ＋ 空の B3 / B5C / review store。"""
    world = build_world(root, stop_after="retired")
    for cls in (ThemeRelationStore, ProposalStore, RelationProposalStore, MonitoringReviewStore):
        cls.initialize(root)
    relations = ThemeRelationStore.open(root)
    asserted = sourced(ROOT_A, ROOT_B, at=day(5))
    relations.append_assertion(asserted)
    relations.append_assertion(causal(ROOT_B, ROOT_A, at=day(6)))
    return {"asserted": asserted, "b_genesis": world.ids["B.genesis"]}


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = tmp_path_factory.mktemp("llm_manifest") / "data"
    return root, _seed(root)


@pytest.fixture()
def copied(base, tmp_path: Path) -> Path:
    target = tmp_path / "manifest_copy" / "data"
    shutil.copytree(base[0], target)
    return target


def evidence_inputs() -> tuple:
    return (news("1", "Data centre power demand rises in Japan", summary="Utilities report higher load"),
            document("2", "Power utilities raise capex"), fact("3"), observation("4"))


def build(root: Path, task: LlmTask = LlmTask.EVIDENCE_EXTRACTION, *, themes=SCOPE, evidence=None, findings=None,
          cutoff=CUT, taxonomy=None, catalog=None) -> LlmInputManifest:
    return build_input_manifest(
        data_root=root, scope=LlmManifestScope(task=task, cutoff=cutoff, theme_root_ids=themes,
                                              evidence_inputs=evidence_inputs() if evidence is None else evidence,
                                              monitoring_findings=findings),
        taxonomy=taxonomy, entity_catalog=catalog)


def themes_for(task: LlmTask):
    return None if task is LlmTask.THEME_PROPOSAL else SCOPE


def fails(code: str, fn) -> ManifestError:
    with pytest.raises(ManifestError) as exc:
        fn()
    assert exc.value.code == code, exc.value
    return exc.value


def signature(manifest: LlmInputManifest) -> tuple:
    return (manifest.manifest_digest(), manifest.visible_json(), manifest.resolution, manifest.knowledge_versions,
            manifest.scope_presence)


def inventory(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------- A〜D: 時刻と scope


@pytest.mark.parametrize("cutoff", [None, "2026-09-22", 1758499200])
def test_a_an_explicit_cutoff_is_required(cutoff) -> None:
    fails("MISSING_CUTOFF", lambda: LlmManifestScope(task=LlmTask.EVIDENCE_EXTRACTION, cutoff=cutoff,
                                                     theme_root_ids=SCOPE, evidence_inputs=()))


def test_b_a_naive_cutoff_is_rejected() -> None:
    fails("NAIVE_CUTOFF", lambda: LlmManifestScope(task=LlmTask.EVIDENCE_EXTRACTION, cutoff=datetime(2026, 9, 22),
                                                   theme_root_ids=SCOPE, evidence_inputs=()))


@pytest.mark.parametrize("task,field", [(LlmTask.EVIDENCE_EXTRACTION, "evidence"), (LlmTask.EVIDENCE_EXTRACTION, "themes"),
                                        (LlmTask.THEME_PROPOSAL, "evidence"), (LlmTask.RELATION_PROPOSAL, "themes"),
                                        (LlmTask.CONTRADICTION_PROPOSAL, "evidence")])
def test_c_an_omitted_required_scope_fails_closed(base, taxonomy, catalog, task: LlmTask, field: str) -> None:
    kwargs = dict(task=task, cutoff=CUT, theme_root_ids=themes_for(task), evidence_inputs=evidence_inputs())
    kwargs["theme_root_ids" if field == "themes" else "evidence_inputs"] = None
    fails("SCOPE_OMITTED", lambda: build_input_manifest(data_root=base[0], scope=LlmManifestScope(**kwargs),
                                                        taxonomy=taxonomy, entity_catalog=catalog))


def test_d_an_explicit_empty_scope_is_distinguished(base, taxonomy, catalog) -> None:
    root, _ = base
    full = build(root, taxonomy=taxonomy, catalog=catalog)
    empty_evidence = build(root, evidence=(), taxonomy=taxonomy, catalog=catalog)
    empty_themes = build(root, themes=(), taxonomy=taxonomy, catalog=catalog)
    assert dict(empty_evidence.scope_presence)["EVIDENCE"] == "SUPPLIED_EMPTY" and empty_evidence.evidence == ()
    assert dict(empty_themes.scope_presence)["THEME"] == "SUPPLIED_EMPTY" and empty_themes.themes == ()
    assert len({full.manifest_digest(), empty_evidence.manifest_digest(), empty_themes.manifest_digest()}) == 3
    # 任意 family（CONTRADICTION の finding）は「渡さない」と「空で渡す」の両方を許し、区別する
    omitted = build(root, LlmTask.CONTRADICTION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    empty = build(root, LlmTask.CONTRADICTION_PROPOSAL, findings=(), taxonomy=taxonomy, catalog=catalog)
    assert dict(omitted.scope_presence)["MONITORING"] == "NOT_SUPPLIED"
    assert dict(empty.scope_presence)["MONITORING"] == "SUPPLIED_EMPTY"
    assert omitted.manifest_digest() != empty.manifest_digest()


def test_d2_there_is_no_hidden_all_themes_default(base, taxonomy, catalog) -> None:
    manifest = build(base[0], themes=(), taxonomy=taxonomy, catalog=catalog)
    assert manifest.themes == () and not any(r.family == "THEME" for r in manifest.resolution)


# ---------------------------------------------------------------- E〜I: handle と決定論


def test_e_handles_are_assigned_deterministically_by_ref(base, taxonomy, catalog) -> None:
    manifest = build(base[0], taxonomy=taxonomy, catalog=catalog)
    assert [t.handle for t in manifest.themes] == ["TH_001", "TH_002"]
    assert manifest.resolve("TH_001").ref == ROOT_A and manifest.resolve("TH_002").ref == ROOT_B
    evidence_refs = [manifest.resolve(e.handle).ref for e in manifest.evidence]
    assert evidence_refs == sorted(evidence_refs) and [e.handle for e in manifest.evidence] == [
        "EV_001", "EV_002", "EV_003", "EV_004"]
    assert signature(manifest) == signature(build(base[0], taxonomy=taxonomy, catalog=catalog))


def test_f_opaque_handles_hide_authority_refs(base, taxonomy, catalog) -> None:
    root, ids = base
    for task in ALL_TASKS:
        manifest = build(root, task, themes=themes_for(task), taxonomy=taxonomy, catalog=catalog)
        visible = manifest.visible_json()
        for ref in manifest.resolution:
            assert ref.ref not in visible, (task, ref.family)
            hidden = dict(ref.detail)
            for key in ("observation_id", "edge_key", "source_origin", "known_at", "evidence_time"):
                assert f'"{key}"' not in visible, (task, key)                       # 内部 detail の key は見えない
                if hidden.get(key):
                    assert hidden[key] not in visible, (task, key)
        for token in ("index:", "central_bank:", "|", ids["asserted"].relation_assertion_id):
            assert token not in visible, (task, token)
        for shape in (r"theme_[0-9A-Z]{26}", r"(?:news|doc|fact)_[0-9a-z]{24}", r"obs_01J[0-9A-Z]{22}",
                      r"th[a-z]+_[0-9a-f]{24}"):                                        # authority id の形
            assert not re.search(shape, visible), (task, shape)
        assert "resolution" not in manifest.visible_payload()


def test_f2_every_visible_handle_is_a_b7b_handle_of_the_right_kind(base, taxonomy, catalog) -> None:
    kinds = {"THEME": HandleKind.TH, "THEME_CONSEQUENCE": HandleKind.CQ, "THEME_INVALIDATION": HandleKind.IC,
             "RELATION": HandleKind.REL, "ENTITY": HandleKind.ENT, "EVIDENCE": HandleKind.EV, "MONITORING": HandleKind.MON}
    for task in ALL_TASKS:
        manifest = build(base[0], task, themes=themes_for(task), taxonomy=taxonomy, catalog=catalog)
        for ref in manifest.resolution:
            assert handle_kind(ref.handle) is kinds[ref.family]


def test_g_the_reverse_map_resolves_to_the_authority_refs(base, taxonomy, catalog) -> None:
    root, ids = base
    manifest = build(root, LlmTask.CONTRADICTION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    observation_b = resolve_at_data_root(root, ROOT_B, CUT).observation
    th_b = manifest.resolve("TH_002")
    assert th_b.ref == ROOT_B and dict(th_b.detail)["observation_id"] == observation_b.observation_id
    cq = [r for r in manifest.resolution if r.family == "THEME_CONSEQUENCE" and r.ref == ROOT_B]
    assert {dict(r.detail)["component_key"] for r in cq} == set(observation_b.mechanism.consequence_keys)
    ic = [r for r in manifest.resolution if r.family == "THEME_INVALIDATION" and r.ref == ROOT_B]
    assert {dict(r.detail)["condition_key"] for r in ic} == {c.condition_key for c in observation_b.invalidation_conditions}
    evidence = {manifest.resolve(e.handle).ref for e in manifest.evidence}
    assert evidence == {i.news_item_id if hasattr(i, "news_item_id") else getattr(i, "source_document_id", None)
                        or getattr(i, "fact_id", None) or i.observation_id for i in evidence_inputs()}
    relation = build(root, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    refs = {relation.resolve(r.handle).ref for r in relation.relations}
    assert ids["asserted"].relation_assertion_id in refs
    fails("UNKNOWN_HANDLE", lambda: manifest.resolve("EV_999"))


def test_h_path_and_mtime_do_not_change_the_manifest(base, copied: Path, taxonomy, catalog) -> None:
    before = signature(build(base[0], LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog))
    for path in copied.rglob("*"):
        if path.is_file():
            os.utime(path, (1_000_000_000, 1_000_000_000))
    assert signature(build(copied, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)) == before


@pytest.mark.parametrize("seed", range(5))
def test_i_input_order_does_not_change_the_manifest(base, taxonomy, catalog, seed: int) -> None:
    reference = signature(build(base[0], LlmTask.CONTRADICTION_PROPOSAL, taxonomy=taxonomy, catalog=catalog))
    shuffled = list(evidence_inputs())
    random.Random(seed).shuffle(shuffled)
    themes = list(SCOPE)
    random.Random(seed + 7).shuffle(themes)
    assert signature(build(base[0], LlmTask.CONTRADICTION_PROPOSAL, themes=tuple(themes), evidence=tuple(shuffled),
                           taxonomy=taxonomy, catalog=catalog)) == reference


def test_i2_a_separate_process_builds_the_same_manifest(base, taxonomy, catalog) -> None:
    code = ("import json,sys\n"
            "from datetime import datetime, timezone\n"
            "from pathlib import Path\n"
            "from tests.intelligence.test_theme_llm_input_manifest import build, CUT\n"
            "from src.intelligence.theme_intelligence.taxonomy import load_taxonomy_version, taxonomy_path\n"
            "from src.intelligence.theme_intelligence.entity_catalog import entity_catalog_path, load_entity_catalog_version\n"
            "k = Path('knowledge')\n"
            "t = load_taxonomy_version(taxonomy_path(k, '0.2.0'), expected_version='0.2.0', cutoff=CUT)\n"
            "c = load_entity_catalog_version(entity_catalog_path(k, '0.2.0'), expected_version='0.2.0', cutoff=CUT)\n"
            "print(build(Path(sys.argv[1]), taxonomy=t, catalog=c).manifest_digest())\n")
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONHASHSEED": "12345"}
    done = subprocess.run([os.sys.executable, "-c", code, str(base[0])], cwd=REPO_ROOT, env=env, capture_output=True,
                          text=True, check=True)
    assert done.stdout.strip() == build(base[0], taxonomy=taxonomy, catalog=catalog).manifest_digest()


def test_i3_the_pure_model_orders_its_inputs_itself(base, taxonomy, catalog) -> None:
    """builder の並べ替えに頼らない: 純 model に逆順で渡しても handle と bytes は同じ。"""
    from src.intelligence.theme_intelligence.discovery_adapter import adapt_inputs
    root, _ = base
    records = list(adapt_inputs(list(evidence_inputs()), taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUT).records)
    themes = [(r, resolve_at_data_root(root, r, CUT).observation) for r in SCOPE]
    common = dict(task=LlmTask.CONTRADICTION_PROPOSAL, cutoff=CUT, presence={}, knowledge_versions=(),
                  entity_lookup=catalog.entity)
    forward = M.assemble_manifest(themes=themes, evidence=records, **common)
    backward = M.assemble_manifest(themes=list(reversed(themes)), evidence=list(reversed(records)), **common)
    assert signature(forward) == signature(backward)


# ---------------------------------------------------------------- J〜N: 未来の record は過去の manifest を変えない


def _assert_past_unchanged(root: Path, taxonomy, catalog, mutate, *, task=LlmTask.RELATION_PROPOSAL) -> tuple:
    before = signature(build(root, task, taxonomy=taxonomy, catalog=catalog))
    mutate(root)
    assert signature(build(root, task, taxonomy=taxonomy, catalog=catalog)) == before
    return before


def test_j_future_evidence_is_invisible(base, copied: Path, taxonomy, catalog) -> None:
    reference = build(copied, taxonomy=taxonomy, catalog=catalog)
    later = evidence_inputs() + (news("9", "A later headline", published=FUTURE), fact("8", known_at=FUTURE),
                                 document("7", "A later release", published=FUTURE, retrieved=FUTURE),
                                 observation("6", as_of=FUTURE))
    assert signature(build(copied, evidence=later, taxonomy=taxonomy, catalog=catalog)) == signature(reference)

    def attach_future_evidence(root: Path) -> None:
        store = ThemeStore.open(root)
        current = resolve_at_data_root(root, ROOT_B, CUT).observation
        future = attachment("doc_" + "f" * 24, EvidenceKind.SOURCE_DOCUMENT, day="2026-09-24", attached=FUTURE,
                            role=EvidenceRole.SUPPORTS, cref=current.mechanism.consequence_keys[0])
        store.append_observation(attach_evidence(current, (future,), recorded_at=FUTURE,
                                                 provenance=provenance(reason="future evidence")))

    _assert_past_unchanged(copied, taxonomy, catalog, attach_future_evidence, task=LlmTask.CONTRADICTION_PROPOSAL)


def test_k_future_governance_is_invisible(copied: Path, taxonomy, catalog) -> None:
    def accept_later(root: Path) -> None:
        ThemeStore.open(root).append_governance(event(event_type=GovernanceEventType.CANDIDATE_ACCEPTED,
                                                      subject_roots=(ROOT_B,), reason="accepted after the cutoff",
                                                      recorded_at=FUTURE))

    _assert_past_unchanged(copied, taxonomy, catalog, accept_later)


def test_l_future_b3_proposals_and_decisions_are_invisible(copied: Path, taxonomy, catalog) -> None:
    def propose_later(root: Path) -> None:
        store = ProposalStore.open(root)
        candidate = evidence_candidate(created_at=FUTURE, reason="a candidate recorded after the cutoff")
        store.append_proposal(candidate)
        store.append_decision(decision(candidate.proposal_id, DecisionKind.ACCEPT, at=LATER))

    _assert_past_unchanged(copied, taxonomy, catalog, propose_later, task=LlmTask.EVIDENCE_EXTRACTION)


def test_m_future_relation_assertions_and_governance_are_invisible(base, copied: Path, taxonomy, catalog) -> None:
    _, ids = base

    def relate_later(root: Path) -> None:
        store = ThemeRelationStore.open(root)
        store.append_assertion(causal(ROOT_A, ROOT_B, at=FUTURE))
        store.append_event(retraction(ids["asserted"], at=FUTURE))

    before = _assert_past_unchanged(copied, taxonomy, catalog, relate_later)
    after = build(copied, LlmTask.RELATION_PROPOSAL, cutoff=LATER, taxonomy=taxonomy, catalog=catalog)
    assert signature(after) != before                                     # fixture は cutoff の後には効く
    assert ids["asserted"].relation_assertion_id not in {r.ref for r in after.resolution}


def test_n_future_b5c_proposals_and_decisions_are_invisible(copied: Path, taxonomy, catalog) -> None:
    def propose_relation_later(root: Path) -> None:
        store = RelationProposalStore.open(root)
        candidate = relation_candidate(ROOT_A, ROOT_B, relation_type=RelationType.DEPENDS_ON, at=FUTURE,
                                       rationale="a relation candidate recorded after the cutoff")
        store.append_proposal(candidate)
        store.append_decision(decide(candidate, RelationDecisionKind.REJECT, at=LATER))

    _assert_past_unchanged(copied, taxonomy, catalog, propose_relation_later)


def test_n2_present_b3_and_b5c_state_is_not_read_at_all(copied: Path, taxonomy, catalog) -> None:
    """B3 / B5C の提案状態は生成の入力ではない（check-then-reuse は B7F）。破損していても manifest は変わらない。"""
    before = signature(build(copied, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog))
    for path in (proposal_paths(copied)["proposals"], relation_proposal_paths(copied)["proposals"]):
        path.write_bytes(path.read_bytes() + b"{not json}\n")
    assert signature(build(copied, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)) == before


# ---------------------------------------------------------------- O: 破損は未来日付でも fail closed


def test_o_a_corrupt_future_theme_record_fails_closed(copied: Path, taxonomy, catalog) -> None:
    path = theme_paths(copied)["observations"]
    damaged = path.read_bytes() + b'{"recorded_at":"2099-01-01T00:00:00+00:00","root_id":\n'
    path.write_bytes(damaged)
    error = fails("THEME_NOT_RESOLVED", lambda: build(copied, taxonomy=taxonomy, catalog=catalog))
    assert error.detail == "STORE_CORRUPTION"
    assert path.read_bytes() == damaged                                                # 修復しない


def test_o2_a_corrupt_future_relation_record_fails_closed_where_relations_are_read(copied: Path, taxonomy, catalog) -> None:
    path = relation_paths(copied)["assertions"]
    damaged = path.read_bytes() + b'{"recorded_at":"2099-01-01T00:00:00+00:00"\n'
    path.write_bytes(damaged)
    error = fails("RELATION_NOT_RESOLVED", lambda: build(copied, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy,
                                                         catalog=catalog))
    assert error.detail == "STORE_CORRUPTION" and path.read_bytes() == damaged
    build(copied, LlmTask.EVIDENCE_EXTRACTION, taxonomy=taxonomy, catalog=catalog)     # relation を読まない task は影響なし


def test_o3_a_missing_relation_authority_is_not_an_empty_graph(copied: Path, taxonomy, catalog) -> None:
    shutil.rmtree(relation_paths(copied)["assertions"].parent)
    with pytest.raises(ManifestError) as exc:                                        # B5B は欠落を破損として返す
        build(copied, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    assert exc.value.code in ("RELATION_NOT_RESOLVED", "RELATION_AUTHORITY_UNAVAILABLE")


@pytest.mark.parametrize("root_id,code", [(ROOT_C, "THEME_NOT_RESOLVED"), ("not-a-root", "INVALID_SCOPE_ENTRY")])
def test_o4_a_theme_that_is_not_visible_at_the_cutoff_fails_closed(base, taxonomy, catalog, root_id: str, code: str) -> None:
    fails(code, lambda: build(base[0], themes=(ROOT_A, root_id), taxonomy=taxonomy, catalog=catalog))


def test_o5_a_root_without_state_at_the_cutoff_is_named_not_skipped(base, taxonomy, catalog) -> None:
    """merge 前の world に ROOT_C は存在しない。scope に在っても黙って落とさず NO_STATE で止まる。"""
    error = fails("THEME_NOT_RESOLVED", lambda: build(base[0], themes=(ROOT_A, ROOT_B, ROOT_C), taxonomy=taxonomy,
                                                      catalog=catalog))
    assert error.detail == "NO_STATE"


@pytest.mark.parametrize("bad,code", [
    ("an unsupported object", "EVIDENCE_INPUT_REJECTED"),
    (fact("5", status=FactStatus.UNUSABLE), "EVIDENCE_INPUT_REJECTED"),
])
def test_o6_rejected_evidence_is_not_silently_dropped(base, taxonomy, catalog, bad, code: str) -> None:
    fails(code, lambda: build(base[0], evidence=evidence_inputs() + (bad,), taxonomy=taxonomy, catalog=catalog))


def test_o7_knowledge_published_after_the_cutoff_is_refused(base, taxonomy, catalog) -> None:
    early = datetime(2026, 9, 19, tzinfo=UTC)
    fails("FUTURE_KNOWLEDGE", lambda: build(base[0], cutoff=early, taxonomy=taxonomy, catalog=catalog))
    fails("MISSING_KNOWLEDGE", lambda: build(base[0], taxonomy=None, catalog=catalog))


# ---------------------------------------------------------------- P〜Q: 最小投影と除外


def test_p_the_projection_exposes_only_the_declared_fields(base, taxonomy, catalog) -> None:
    manifest = build(base[0], LlmTask.CONTRADICTION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    payload = manifest.visible_payload()
    assert set(payload) == {"schema_version", "task", "cutoff", "knowledge_versions", "scope_presence", "evidence",
                            "themes", "relations", "entities", "findings"}
    assert set(payload["evidence"][0]) == {"handle", "evidence_kind", "evidence_date", "source_kind", "fact_type",
                                           "observation_series", "taxonomy_slugs", "entity_handles", "text_surfaces"}
    assert set(payload["themes"][0]) == {"handle", "subject_statement", "drivers", "channels", "domains",
                                         "consequences", "invalidation_conditions", "scope"}
    text = manifest.visible_json()
    for absent in ("certainty", "governance", "attachment", "limitation", "provenance", "recorded_at", "locator",
                   "publisher", "author", "url", "canonical_url", "body", "content_hash", "origin_key", "known_at",
                   "evidence_time", "lineage", "reason", "note"):
        assert f'"{absent}' not in text, absent
    surfaces = {field for item in payload["evidence"] for field, _text in item["text_surfaces"]}
    assert surfaces <= {"headline", "summary", "title"}                                # B4 の限定面だけ


def test_q_confidential_and_secret_surfaces_are_absent(base, taxonomy, catalog) -> None:
    for task in ALL_TASKS:
        text = build(base[0], task, themes=themes_for(task), taxonomy=taxonomy, catalog=catalog).visible_json()
        for token in ("Compass", "compass", "formal_review", "PROMOTED", "KEEP_REVIEWING", "portfolio", "api_key",
                      "password", "secret", "credential", "system", "instruction", "prompt", "reasoning", "C:\\",
                      "/home/", "/Users/", "journal", ".jsonl", "calibration", "prediction", "recommend"):
            assert token not in text, (task, token)


@pytest.mark.parametrize("text", ["see C:\\Users\\someone\\notes", "stored under /home/someone/data",
                                  "read https://example.com/a", "fetch ?api_key=abc", "two\nlines"])
def test_q2_input_text_with_paths_urls_or_secrets_fails_closed(base, taxonomy, catalog, text: str) -> None:
    code = "INVALID_INPUT_TEXT" if "\n" in text else "PROHIBITED_CONTENT_IN_INPUT"
    fails(code, lambda: build(base[0], evidence=(news("5", "Clean headline", summary=text),), taxonomy=taxonomy,
                              catalog=catalog))


def test_q3_oversized_input_text_is_refused_not_truncated(base, taxonomy, catalog) -> None:
    fails("SURFACE_TOO_LONG", lambda: build(base[0], evidence=(news("5", "x" * (M.MAX_SURFACE_LEN + 1)),),
                                            taxonomy=taxonomy, catalog=catalog))


def test_q4_the_modules_never_reach_confidential_or_production_sources() -> None:
    for module in (M, B):
        imports = imported_modules(Path(module.__file__))
        for token in ("compass", "corpus", "formal_review", "decision", "market_principles", "market_rules",
                      "predictions", "reports", "notifiers", "internals", "context"):
            assert not any(token in m for m in imports), (module.__name__, token)


# ---------------------------------------------------------------- R: task ごとの family


def test_r_each_task_gets_only_its_families(base, taxonomy, catalog) -> None:
    root, _ = base
    evidence = build(root, LlmTask.EVIDENCE_EXTRACTION, taxonomy=taxonomy, catalog=catalog)
    contradiction = build(root, LlmTask.CONTRADICTION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    theme = build(root, LlmTask.THEME_PROPOSAL, themes=None, taxonomy=taxonomy, catalog=catalog)
    relation = build(root, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    families = lambda m: {r.family for r in m.resolution}                             # noqa: E731
    assert families(evidence) == {"EVIDENCE", "THEME", "THEME_CONSEQUENCE"}
    assert families(contradiction) == {"EVIDENCE", "THEME", "THEME_CONSEQUENCE", "THEME_INVALIDATION"}
    assert families(theme) == {"EVIDENCE", "ENTITY"}
    assert families(relation) == {"EVIDENCE", "THEME", "RELATION"}
    assert all(not e.entity_handles for e in evidence.evidence)                         # entity は THEME task だけ
    assert all(not c.handle for t in relation.themes for c in t.consequences)


@pytest.mark.parametrize("task,kwargs", [(LlmTask.THEME_PROPOSAL, {"themes": SCOPE}),
                                         (LlmTask.EVIDENCE_EXTRACTION, {"findings": ()}),
                                         (LlmTask.RELATION_PROPOSAL, {"findings": ()})])
def test_r2_a_family_the_task_does_not_take_is_refused_not_dropped(base, taxonomy, catalog, task, kwargs) -> None:
    kwargs.setdefault("themes", themes_for(task))
    fails("FAMILY_NOT_ALLOWED_FOR_TASK", lambda: build(base[0], task, taxonomy=taxonomy, catalog=catalog, **kwargs))


# ---------------------------------------------------------------- S: monitoring finding は非 authority の文脈


@pytest.fixture(scope="module")
def live_findings(base):
    result = run_monitoring(data_root=base[0], cutoff=CUT, recorded_at=CUT, ruleset=RULES, root_ids=SCOPE,
                            lifecycle_policy=default_lifecycle_policy())
    allowed = tuple(f for f in result.findings if f.condition_id in M.MONITORING_CONTEXT_CONDITIONS)
    assert allowed, "the synthetic world should hold a contradiction finding"
    return allowed


def test_s_findings_are_projected_minimally_and_stay_non_authoritative(base, taxonomy, catalog, live_findings) -> None:
    manifest = build(base[0], LlmTask.CONTRADICTION_PROPOSAL, findings=live_findings, taxonomy=taxonomy,
                     catalog=catalog)
    assert manifest.findings and dict(manifest.scope_presence)["MONITORING"] == "SUPPLIED"
    payload = manifest.visible_payload()
    assert set(payload["findings"][0]) == {"handle", "condition_id", "subject_handle", "facts"}
    for item in payload["findings"]:
        assert item["subject_handle"].startswith("TH_")
        assert {key for key, _value in item["facts"]} <= {"role", "absence_kind", "evidence_condition"}
    text = manifest.visible_json()
    for absent in ("finding_id", "ruleset_version", "disposition", "ACKNOWLEDGED", "DISMISSED", "DEFERRED",
                   "severity", "supporting_refs", "trigger_refs", "thmf_"):
        assert absent not in text, absent
    assert ("monitoring_rules", RULES.ruleset_version) in manifest.knowledge_versions


@pytest.mark.parametrize("make,code", [
    (lambda: synthetic_finding(cutoff=CUT - timedelta(days=1), subject_ref=ROOT_A,
                               condition_id="THEME_CONTRADICTION_EVIDENCE_PRESENT",
                               salient=state(theme_root_id=ROOT_A)), "FINDING_CUTOFF_MISMATCH"),
    (lambda: synthetic_finding(cutoff=CUT, subject_ref=ROOT_A, condition_id="AUTHORITY_STATE_UNUSABLE",
                               category=MonitoringCategory.INTEGRITY, subject_kind=MonitoringSubjectKind.AUTHORITY_STORE,
                               salient=state(SalientStateKind.AUTHORITY_INTEGRITY)), "FINDING_NOT_ALLOWED"),
    (lambda: synthetic_finding(cutoff=CUT, subject_ref=ROOT_A, condition_id="THEME_EVIDENCE_STALE",
                               salient=state(SalientStateKind.FRESHNESS_THRESHOLD, theme_root_id=ROOT_A)),
     "FINDING_NOT_ALLOWED"),
    (lambda: synthetic_finding(cutoff=CUT, subject_ref=ROOT_C, condition_id="THEME_CONTRADICTION_EVIDENCE_PRESENT",
                               salient=state(theme_root_id=ROOT_C)), "FINDING_OUT_OF_SCOPE"),
    (lambda: "not a finding", "INVALID_TYPE"),
])
def test_s2_findings_outside_the_contract_are_refused(base, taxonomy, catalog, make, code: str) -> None:
    fails(code, lambda: build(base[0], LlmTask.CONTRADICTION_PROPOSAL, findings=(make(),), taxonomy=taxonomy,
                              catalog=catalog))


# ---------------------------------------------------------------- T〜U: relation の意味と score の不在


def test_t_source_asserted_is_carried_verbatim_and_never_becomes_truth(base, taxonomy, catalog) -> None:
    manifest = build(base[0], LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    classes = sorted(r.assertion_class for r in manifest.relations)
    assert classes == ["HUMAN_ASSERTED", "SOURCE_ASSERTED"]
    assert set(manifest.visible_payload()["relations"][0]) == {"handle", "source_handle", "target_handle",
                                                                "relation_type", "assertion_class"}
    for absent in ("verified", "true", "fact", "confirmed", "attribution", "certainty", "centrality", "pagerank",
                   "transitive", "inferred"):
        assert all(absent not in json.dumps(r.__dict__).lower() for r in manifest.relations), absent


def test_t2_only_active_relations_between_scoped_themes_are_visible(base, copied: Path, taxonomy, catalog) -> None:
    _, ids = base
    ThemeRelationStore.open(copied).append_event(retraction(ids["asserted"], at=day(8)))
    manifest = build(copied, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    assert [r.assertion_class for r in manifest.relations] == ["HUMAN_ASSERTED"]
    only_a = build(copied, LlmTask.RELATION_PROPOSAL, themes=(ROOT_A,), taxonomy=taxonomy, catalog=catalog)
    assert only_a.relations == ()                                                     # 片端だけの関係は見せない


def _numbers(value) -> list:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers(v)]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]
    return []


def test_u_the_manifest_carries_no_number_score_rank_or_importance(base, taxonomy, catalog, live_findings) -> None:
    for task in ALL_TASKS:
        manifest = build(base[0], task, themes=themes_for(task), taxonomy=taxonomy, catalog=catalog,
                         findings=live_findings if task is LlmTask.CONTRADICTION_PROPOSAL else None)
        payload = manifest.visible_payload()
        assert _numbers(payload) == []
        keys = json.dumps(payload)
        for token in ("score", "rank", "importance", "centrality", "weight", "confidence", "probability", "priority",
                      "count", "salience"):
            assert f'"{token}' not in keys, (task, token)


# ---------------------------------------------------------------- V〜Z: 書かない・replay・digest・pin


def test_v_building_writes_nothing(copied: Path, taxonomy, catalog, live_findings) -> None:
    before = inventory(copied)
    for task in ALL_TASKS:
        build(copied, task, themes=themes_for(task), taxonomy=taxonomy, catalog=catalog,
              findings=live_findings if task is LlmTask.CONTRADICTION_PROPOSAL else None)
    assert inventory(copied) == before


def test_v2_no_clock_random_network_or_write_in_the_sources() -> None:
    for module in (M, B):
        source = executable_source(Path(module.__file__))
        for token in (".now(", "utcnow", "today(", "time.time", "random", "uuid", "open(", ".write", "mkdir", "unlink",
                      "append_", "requests", "urllib", "socket", "anthropic", "openai", "environ", "getmtime", "stat("):
            assert token not in source, (module.__name__, token)
    assert "data_root" not in executable_source(Path(M.__file__))                   # 純 model は data root を知らない


def test_w_the_canonical_form_replays(base, taxonomy, catalog) -> None:
    manifest = build(base[0], LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    text = manifest.visible_json()
    assert json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True, separators=(",", ":")) == text
    assert manifest == build(base[0], LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    assert manifest.schema_version == MANIFEST_SCHEMA_VERSION


def test_x_visible_semantic_changes_change_the_digest(base, taxonomy, catalog) -> None:
    root, _ = base
    reference = build(root, taxonomy=taxonomy, catalog=catalog)
    for other in (build(root, evidence=evidence_inputs() + (news("5", "Another visible headline"),), taxonomy=taxonomy,
                        catalog=catalog),
                  build(root, themes=(ROOT_B,), taxonomy=taxonomy, catalog=catalog),
                  build(root, LlmTask.CONTRADICTION_PROPOSAL, taxonomy=taxonomy, catalog=catalog),
                  build(root, cutoff=CUT + timedelta(hours=1), taxonomy=taxonomy, catalog=catalog)):
        assert other.manifest_digest() != reference.manifest_digest()


def test_x2_the_digest_binds_hidden_refs_even_when_the_visible_view_is_equal(base, taxonomy, catalog) -> None:
    root, _ = base
    one = build(root, evidence=(news("1", "Same headline"),), taxonomy=taxonomy, catalog=catalog)
    two = build(root, evidence=(news("2", "Same headline"),), taxonomy=taxonomy, catalog=catalog)
    assert one.visible_json() == two.visible_json() and one.visible_digest() == two.visible_digest()
    assert one.manifest_digest() != two.manifest_digest()                            # 別の record を指す


def test_y_only_future_input_leaves_the_digest_unchanged(base, taxonomy, catalog) -> None:
    reference = build(base[0], taxonomy=taxonomy, catalog=catalog)
    later = build(base[0], evidence=evidence_inputs() + (news("9", "Later", published=FUTURE),), taxonomy=taxonomy,
                  catalog=catalog)
    assert later.manifest_digest() == reference.manifest_digest()


def test_z_only_consumed_knowledge_is_pinned(base, taxonomy, catalog, live_findings) -> None:
    root, _ = base
    pins = lambda **kw: dict(build(root, taxonomy=taxonomy, catalog=catalog, **kw).knowledge_versions)   # noqa: E731
    assert pins() == {"entity_catalog": "0.2.0", "taxonomy": "0.2.0", "mechanism_vocabulary": "0.1.0"}
    assert pins(themes=()) == {"entity_catalog": "0.2.0", "taxonomy": "0.2.0"}                    # Theme を投影しない
    assert dict(build(root, LlmTask.THEME_PROPOSAL, themes=None, taxonomy=taxonomy, catalog=catalog)
                .knowledge_versions) == {"entity_catalog": "0.2.0", "taxonomy": "0.2.0"}
    assert "theme_relation_vocabulary" in dict(build(root, LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy,
                                                     catalog=catalog).knowledge_versions)
    with_findings = dict(build(root, LlmTask.CONTRADICTION_PROPOSAL, findings=live_findings, taxonomy=taxonomy,
                               catalog=catalog).knowledge_versions)
    assert with_findings["monitoring_rules"] == RULES.ruleset_version
    assert "monitoring_rules" not in dict(build(root, LlmTask.CONTRADICTION_PROPOSAL, taxonomy=taxonomy,
                                                catalog=catalog).knowledge_versions)


# ---------------------------------------------------------------- 重複の扱い


def test_dup_1_the_same_record_supplied_twice_is_one_item(base, taxonomy, catalog) -> None:
    once = build(base[0], taxonomy=taxonomy, catalog=catalog)
    twice = build(base[0], evidence=evidence_inputs() + evidence_inputs(), taxonomy=taxonomy, catalog=catalog)
    assert signature(once) == signature(twice)


def test_dup_2_two_different_records_under_one_id_fail_closed(base, taxonomy, catalog) -> None:
    fails("CONFLICTING_EVIDENCE_INPUT", lambda: build(base[0], evidence=(news("1", "One"), news("1", "Two")),
                                                      taxonomy=taxonomy, catalog=catalog))


def test_dup_3_distinct_records_with_the_same_projection_fail_closed(base, taxonomy, catalog) -> None:
    fails("DUPLICATE_PROJECTION", lambda: build(base[0], evidence=(news("1", "Same"), news("2", "Same")),
                                                taxonomy=taxonomy, catalog=catalog))


def test_dup_4_a_merged_source_and_its_successor_are_not_conflated(tmp_path: Path, taxonomy, catalog) -> None:
    root = tmp_path / "merged" / "data"
    build_world(root)                                                                 # ROOT_A と ROOT_C は同じ意味を持つ
    ThemeRelationStore.initialize(root)
    fails("DUPLICATE_PROJECTION", lambda: build(root, themes=(ROOT_A, ROOT_C), taxonomy=taxonomy, catalog=catalog))
    assert build(root, themes=(ROOT_B, ROOT_C), taxonomy=taxonomy, catalog=catalog).themes


def test_dup_5_a_theme_named_twice_is_a_caller_error(base, taxonomy, catalog) -> None:
    fails("DUPLICATE_SCOPE_ENTRY", lambda: build(base[0], themes=(ROOT_A, ROOT_A), taxonomy=taxonomy, catalog=catalog))


# ---------------------------------------------------------------- manifest ≠ prompt、B7B との接続、凍結


def test_prompt_the_manifest_is_data_not_a_prompt(base, taxonomy, catalog) -> None:
    payload = build(base[0], taxonomy=taxonomy, catalog=catalog).visible_payload()
    keys = set(payload) | {k for item in payload["evidence"] + payload["themes"] for k in item}
    assert not keys & {"system", "role", "instruction", "instructions", "prompt", "template", "messages", "task_text"}
    assert M.MANIFEST_IS_NOT_A_PROMPT == "an input manifest is data; instructions belong to a later generation gate"
    assert M.MANIFEST_IS_NOT_AUTHORITY == ("an input manifest is a derived view of what the llm may see, "
                                           "never an authority record")


def test_b7b_the_manifest_plugs_into_a_generation_request(base, taxonomy, catalog) -> None:
    manifest = build(base[0], LlmTask.RELATION_PROPOSAL, taxonomy=taxonomy, catalog=catalog)
    request = LlmGenerationRequest(task=manifest.task, cutoff=manifest.cutoff, generated_at=CUT + timedelta(hours=1),
                                   prompt_contract_version="theme_llm_prompt:0.1.0",
                                   manifest_digest=manifest.manifest_digest(),
                                   knowledge_versions=manifest.knowledge_versions)
    record = LlmGenerationRecord.build(request, provider_ref="fake_provider", model_ref="fake_model",
                                       generation_config_ref="default", outcome=GenerationOutcome.RETRYABLE_FAILURE,
                                       rejection_codes=("PROVIDER_UNAVAILABLE",))
    assert record.request.manifest_digest == manifest.manifest_digest()


def test_frozen_the_b7b_model_is_byte_identical_to_its_anchor() -> None:
    path = "src/intelligence/theme_intelligence/llm_proposal_model.py"
    anchored = subprocess.run(["git", "show", f"{B7B_ANCHOR}:{path}"], cwd=REPO_ROOT, capture_output=True,
                              check=True).stdout
    assert (REPO_ROOT / path).read_bytes() == anchored


@pytest.mark.parametrize("status,path,exempt", [
    ("A", "src/intelligence/theme_intelligence/llm_manifest_model.py", True),
    ("??", "src/intelligence/theme_intelligence/llm_new_module.py", True),
    ("M", "src/intelligence/theme_intelligence/llm_proposal_model.py", False),     # 凍結済み B7 module の変更
    ("M", "src/intelligence/theme_intelligence/monitoring_engine.py", False),      # 凍結済み B6 module の変更
    ("D", "src/intelligence/theme_intelligence/llm_manifest_model.py", False),
    ("A", "src/intelligence/theme_intelligence/llm_sub/monitoring_engine.py", False),
    ("A", "src/intelligence/theme_intelligence/monitoring_llm_patch.py", False),
    ("A", "src/intelligence/themes/llm_patch.py", False),
    ("A", "src/intelligence/theme_intelligence/llm_x.pyc", False),
    ("R100", "src/intelligence/theme_intelligence/llm_x.py", False),
])
def test_pins_the_b6_freeze_pins_exempt_only_new_llm_modules(status: str, path: str, exempt: bool) -> None:
    assert is_new_llm_module(status, path) is exempt


def test_scope_is_frozen_and_has_no_hidden_default() -> None:
    fields = {f.name: f.default for f in dataclasses.fields(LlmManifestScope)}
    assert fields["theme_root_ids"] is None and fields["evidence_inputs"] is None
    assert fields["monitoring_findings"] is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        LlmManifestScope(task=LlmTask.THEME_PROPOSAL, cutoff=CUT, evidence_inputs=()).cutoff = LATER  # type: ignore[misc]
    fails("INVALID_SCOPE", lambda: LlmManifestScope(task=LlmTask.THEME_PROPOSAL, cutoff=CUT, evidence_inputs=[]))
    assert set(M.TASK_FAMILIES) == set(LlmTask)
    assert M.TASK_FAMILIES[LlmTask.THEME_PROPOSAL].required == (ManifestFamily.EVIDENCE,)
