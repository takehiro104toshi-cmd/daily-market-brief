"""Phase 6 completion — Theme Intelligence 全体の凍結の連鎖と境界を git の履歴から独立に確かめる（runtime は変えない）。

`docs/databank/PHASE6_THEME_INTELLIGENCE_COMPLETION_AUDIT.md` の「凍結の連鎖」「Production DNA / 公開の境界」を固定する:

- anchor は Phase 5 closeout → Foundation → B1 → … → B7 → HEAD の一本の祖先鎖。
- 各 gate の runtime 差分は、その gate の新規 file の**追加だけ**（後の gate が前の gate の runtime を変えていない）。
- Phase 5 closeout 以降、Phase 6 の 3 名前空間（`themes`・`theme_intelligence`・`knowledge/theme_intelligence`）の外の
  runtime・knowledge（compass_dna を含む）・config・workflow・scripts・公開出力・data・legacy entry は変わっていない。
- Foundation は Foundation anchor と byte 一致。
- Phase 6 の package を import する module は Phase 6 の外に無い。
- 後の gate が前の gate の test に加えた変更は、登録済みの guard / pin の追加だけ（test 側だけの変更）。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPLETION_DOC = REPO_ROOT / "docs" / "databank" / "PHASE6_THEME_INTELLIGENCE_COMPLETION_AUDIT.md"
PHASE5_CLOSEOUT = "edbd0f203fd2b96a5dbfff921ccf0ba584cbef88"
THEMES = "src/intelligence/themes"
LAYER = "src/intelligence/theme_intelligence"
KNOWLEDGE = "knowledge/theme_intelligence"
#: gate → (凍結 anchor, その gate が追加した runtime / knowledge file)
GATES = {
    "Foundation": ("12847bf2783330cbd310d24c8310d3bf46469f6a", tuple(f"{THEMES}/{n}.py" for n in (
        "__init__", "fingerprint", "model", "operations", "qualification", "resolver", "revision", "store"))),
    "B1": ("e2d5168cb9e595478451b2534ae0080a31ac98d5", tuple(f"{LAYER}/{n}.py" for n in ("__init__", "change", "model"))),
    "B2": ("ce2402a085523e526b6b8d2be1202e0e2cd74b8b", tuple(f"{LAYER}/{n}.py" for n in ("lifecycle", "lifecycle_model"))),
    "B3": ("4808f5e7c0d8cf22709f7597edc44fb4bc4bdb4c", tuple(f"{LAYER}/{n}.py" for n in (
        "dedup", "proposal_bridge", "proposal_model", "proposal_resolution", "proposal_store"))),
    "B4": ("10b44839d0aa33f83b6517552ab8a6b7ed06a3fa", tuple(f"{LAYER}/{n}.py" for n in (
        "discovery", "discovery_adapter", "discovery_model", "discovery_predicates", "discovery_rules", "entity_catalog",
        "entity_model", "evidence_bridge", "evidence_bridge_model", "knowledge_loader", "taxonomy", "taxonomy_model"))
        + tuple(f"{KNOWLEDGE}/{n}.yaml" for n in ("discovery_rules.0.1.0", "entity_catalog.0.1.0", "entity_catalog.0.2.0",
                                                  "theme_taxonomy.0.1.0", "theme_taxonomy.0.2.0"))),
    "B5": ("8322cb1db6a991191500863afc05b66168e9a747", tuple(f"{LAYER}/{n}.py" for n in (
        "relation_graph", "relation_model", "relation_proposal_bridge", "relation_proposal_model",
        "relation_proposal_resolution", "relation_proposal_store", "relation_resolution", "relation_store"))),
    "B6": ("7a8f8a473e6668a5cc782930dedf262818525b08", tuple(f"{LAYER}/{n}.py" for n in (
        "monitoring_adapter", "monitoring_engine", "monitoring_model", "monitoring_rules", "monitoring_runner",
        "monitoring_store")) + (f"{KNOWLEDGE}/monitoring_rules.0.1.0.yaml",)),
    "B7": ("785837fc387178d1f963f4b012a03fbe950acedf", tuple(f"{LAYER}/{n}.py" for n in (
        "llm_generation", "llm_generation_input", "llm_generation_journal", "llm_generation_model", "llm_manifest_builder",
        "llm_manifest_model", "llm_plan_model", "llm_proposal_model", "llm_provider", "llm_submission",
        "llm_submission_model", "llm_validator"))),
}
ORDER = ("Foundation", "B1", "B2", "B3", "B4", "B5", "B6", "B7")
#: runtime・knowledge・config・workflow・scripts・公開出力（Pages）・data・legacy entry・依存
SURFACE = ("src", "knowledge", "config.yaml", ".github", "scripts", "docs/pages", "data", "main.py", "requirements.txt",
           "pyproject.toml")
#: 後の gate が前の gate の test に加えた変更（guard / pin の登録だけ。runtime には効かない）
TEST_ACCOMMODATIONS = {
    "B1": {"test_theme_import_boundary.py"},
    "B2": {"test_theme_intelligence_import_boundary.py"},
    "B3": {"test_theme_intelligence_import_boundary.py"},
    "B4": {"test_theme_intelligence_import_boundary.py"},
    "B5": {"test_theme_intelligence_import_boundary.py"},
    "B6": {"test_theme_intelligence_import_boundary.py", "test_theme_relation_rerun.py",
           "test_theme_taxonomy_entity_boundary.py"},
    "B7": {"test_theme_intelligence_import_boundary.py", "test_theme_monitoring_coverage_rerun.py",
           "test_theme_monitoring_e2e.py", "test_theme_monitoring_e2e_rerun.py", "test_theme_monitoring_model.py"},
}


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=check)


def _changes(old: str, new: str, *paths: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", "--name-status", old, new, "--", *paths).stdout.splitlines()}


def _previous(gate: str) -> str:
    return PHASE5_CLOSEOUT if gate == "Foundation" else GATES[ORDER[ORDER.index(gate) - 1]][0]


def test_the_phase6_anchor_chain_is_one_linear_ancestry() -> None:
    chain = [PHASE5_CLOSEOUT] + [GATES[g][0] for g in ORDER] + ["HEAD"]
    for older, newer in zip(chain, chain[1:]):
        assert _git("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0, (older, newer)


@pytest.mark.parametrize("gate", ORDER)
def test_each_gate_only_added_its_own_runtime(gate: str) -> None:
    assert _changes(_previous(gate), GATES[gate][0], *SURFACE) == {("A", path) for path in GATES[gate][1]}


@pytest.mark.parametrize("gate", ORDER[1:])
def test_later_gates_changed_earlier_tests_only_to_register_guards(gate: str) -> None:
    modified = {Path(path).name for status, path in _changes(_previous(gate), GATES[gate][0], "tests") if status != "A"}
    assert modified <= TEST_ACCOMMODATIONS[gate], modified


def test_nothing_outside_the_phase6_namespaces_changed_since_phase5_closeout() -> None:
    changes = _changes(PHASE5_CLOSEOUT, "HEAD", *SURFACE)
    declared = {path for _, paths in GATES.values() for path in paths}
    assert changes == {("A", path) for path in declared}                              # 追加だけ・宣言どおり
    assert _changes(PHASE5_CLOSEOUT, "HEAD", "knowledge/compass_dna") == set()        # Production DNA は不変
    assert _changes(GATES["B7"][0], "HEAD", *SURFACE) == set()
    assert _git("status", "--porcelain", "--", *(p for p in SURFACE if p != "data")).stdout == ""


def test_the_foundation_is_byte_identical_to_its_anchor() -> None:
    assert _git("diff", "--stat", GATES["Foundation"][0], "--", THEMES).stdout == ""
    for path in GATES["Foundation"][1]:
        assert _git("show", f"{GATES['Foundation'][0]}:{path}").stdout == (REPO_ROOT / path).read_text(encoding="utf-8")


def test_no_module_outside_phase6_imports_the_phase6_packages() -> None:
    pattern = re.compile(r"(intelligence\.themes\b|intelligence\.theme_intelligence\b|from \.+themes\b|"
                         r"from \.+theme_intelligence\b)")
    offenders = []
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")), *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if not path.exists() or (REPO_ROOT / THEMES) in path.parents or (REPO_ROOT / LAYER) in path.parents:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_the_phase6_packages_reference_no_production_dna_or_p4_p5_module() -> None:
    forbidden = re.compile(r"^\s*(from|import)\s+[.\w]*(compass|reports|predictions|evaluation|calibration|internals|"
                           r"corpus|formal_review|personalization|thesis|screening|decision)\b", re.MULTILINE)
    for package in (THEMES, LAYER):
        for path in sorted((REPO_ROOT / package).glob("*.py")):
            assert not forbidden.search(path.read_text(encoding="utf-8")), path.name


def test_the_completion_document_names_exactly_the_audited_anchors() -> None:
    text = COMPLETION_DOC.read_text(encoding="utf-8")
    assert set(re.findall(r"\b[0-9a-f]{40}\b", text)) == {PHASE5_CLOSEOUT} | {anchor for anchor, _ in GATES.values()}
    assert "P6_THEME_INTELLIGENCE_COMPLETE / READY_FOR_PHASE7_PLANNING" in text
