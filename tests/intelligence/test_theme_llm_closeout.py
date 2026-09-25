"""P6-B7 closeout — LLM 提案層（B7A〜B7G）の凍結台帳の test（runtime は変えない）。

closeout 文書（`docs/databank/PHASE6_THEME_LLM_B7_CLOSEOUT.md`）の「凍結の連鎖」と「検証台帳の runtime 変更」欄を
git の履歴から独立に確かめる:

- anchor は B6 → B7A → … → B7G の一本の祖先鎖で、HEAD はその子孫である。
- 各 gate が変えた runtime は、その gate が宣言した新規 module の追加だけ（B7A と B7G は runtime 変更なし）。
- B7G anchor 以降、runtime・knowledge・config・workflow・scripts・公開出力は変わっていない。
- B7 の契約文書は各 anchor で凍結されている。
- B6 の凍結 pin の llm 例外（`theme_freeze_pins.py` と B6 pin の利用箇所）は導入時（B7B / B7C）から広げられていない。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.intelligence.theme_freeze_pins import ADDITION_STATUSES, NEW_LLM_MODULE_RE, is_new_llm_module

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOSEOUT_DOC = REPO_ROOT / "docs" / "databank" / "PHASE6_THEME_LLM_B7_CLOSEOUT.md"
B6 = "7a8f8a473e6668a5cc782930dedf262818525b08"
#: gate → (anchor, その gate が追加した runtime module, その gate の文書)
GATES = {
    "B7A": ("f5934e8cc45841d8224118244618376cce5ea42d", (), "PHASE6_THEME_LLM_PROPOSAL_ARCHITECTURE_AUDIT.md"),
    "B7B": ("e2aa991490d2e05dd30fe65bbea3f3ee091be66c", ("llm_proposal_model",),
            "PHASE6_THEME_LLM_PROPOSAL_MODEL_CONTRACT.md"),
    "B7C": ("95e04ae48f8e28206437923e36c6386a9a512cd9", ("llm_manifest_builder", "llm_manifest_model"),
            "PHASE6_THEME_LLM_INPUT_MANIFEST_CONTRACT.md"),
    "B7D": ("c240f6823cc5ff3239395ac0711d17c516ebf41c", ("llm_plan_model", "llm_validator"),
            "PHASE6_THEME_LLM_SEMANTIC_VALIDATOR_CONTRACT.md"),
    "B7E": ("695227a403e6582849215251c6d1190d48ce3bcd", ("llm_generation", "llm_generation_input",
                                                          "llm_generation_journal", "llm_generation_model",
                                                          "llm_provider"),
            "PHASE6_THEME_LLM_GENERATION_LAYER_CONTRACT.md"),
    "B7F": ("d06dd1b96eedca9902033df52ff80ca9c902a1aa", ("llm_submission", "llm_submission_model"),
            "PHASE6_THEME_LLM_PROPOSAL_SUBMISSION_CONTRACT.md"),
    "B7G": ("272b11d7da274dbd45cda1fd3b1d44747c854da4", (), "PHASE6_THEME_LLM_ADVERSARIAL_E2E_VALIDATION_REPORT.md"),
}
ORDER = ("B7A", "B7B", "B7C", "B7D", "B7E", "B7F", "B7G")
#: runtime・knowledge・config・workflow・scripts・公開出力（Pages）・データ root
SURFACE = ("src", "knowledge", "config.yaml", ".github", "scripts", "docs/pages", "requirements.txt", "pyproject.toml")
PACKAGE = "src/intelligence/theme_intelligence"
#: B6 の凍結 pin の llm 例外（B7B / B7C で導入）。導入後に広げていないことを確かめる
EXEMPTION_FILES = {"tests/intelligence/theme_freeze_pins.py": GATES["B7C"][0],
                   "tests/intelligence/test_theme_monitoring_e2e.py": GATES["B7C"][0],
                   "tests/intelligence/test_theme_monitoring_e2e_rerun.py": GATES["B7C"][0],
                   "tests/intelligence/test_theme_monitoring_coverage_rerun.py": GATES["B7C"][0],
                   "tests/intelligence/test_theme_monitoring_model.py": GATES["B7C"][0]}


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=check)


def _changes(old: str, new: str, *paths: str) -> set:
    lines = _git("diff", "--name-status", old, new, "--", *paths).stdout.splitlines()
    return {tuple(line.split("\t")) for line in lines}


def test_the_anchor_chain_is_one_linear_ancestry() -> None:
    chain = [B6] + [GATES[g][0] for g in ORDER] + ["HEAD"]
    for older, newer in zip(chain, chain[1:]):
        assert _git("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0, (older, newer)


@pytest.mark.parametrize("gate", ORDER)
def test_each_gate_changed_exactly_its_declared_runtime(gate: str) -> None:
    previous = B6 if gate == "B7A" else GATES[ORDER[ORDER.index(gate) - 1]][0]
    anchor, modules, doc = GATES[gate]
    assert _changes(previous, anchor, *SURFACE) == {("A", f"{PACKAGE}/{name}.py") for name in modules}
    assert ("A", f"docs/databank/{doc}") in _changes(previous, anchor, "docs/databank")


def test_since_the_b6_anchor_only_new_llm_modules_entered_the_runtime() -> None:
    changes = _changes(B6, "HEAD", *SURFACE, "data")
    assert changes and all(status in ADDITION_STATUSES and is_new_llm_module(status, path) for status, path in changes)
    declared = {name for _, modules, _ in GATES.values() for name in modules}
    assert {Path(path).stem for _, path in changes} == declared
    assert sorted(p.stem for p in (REPO_ROOT / PACKAGE).glob("llm_*.py")) == sorted(declared)


def test_no_runtime_or_public_output_change_since_the_b7g_anchor() -> None:
    assert _changes(GATES["B7G"][0], "HEAD", *SURFACE, "data") == set()
    assert _git("status", "--porcelain", "--", *SURFACE).stdout == ""


@pytest.mark.parametrize("gate", ORDER)
def test_every_b7_contract_document_is_frozen_at_its_anchor(gate: str) -> None:
    anchor, _, doc = GATES[gate]
    path = f"docs/databank/{doc}"
    assert _git("show", f"{anchor}:{path}").stdout == (REPO_ROOT / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("path,anchor", sorted(EXEMPTION_FILES.items()))
def test_the_historical_b6_llm_exemption_was_not_broadened(path: str, anchor: str) -> None:
    assert _git("show", f"{anchor}:{path}").stdout == (REPO_ROOT / path).read_text(encoding="utf-8")


def test_the_exemption_covers_only_new_top_level_llm_modules() -> None:
    assert ADDITION_STATUSES == ("A", "??")
    assert NEW_LLM_MODULE_RE.pattern == r"^src/intelligence/theme_intelligence/llm_[a-z0-9_]+\.py$"
    for status in ("M", "D", "R", "R100", "C", "T"):
        assert not is_new_llm_module(status, f"{PACKAGE}/llm_validator.py"), status
    for path in (f"{PACKAGE}/sub/llm_x.py", f"{PACKAGE}/proposal_store.py", "src/intelligence/themes/llm_x.py"):
        assert not is_new_llm_module("A", path), path


def test_the_closeout_document_names_exactly_the_audited_anchors() -> None:
    text = CLOSEOUT_DOC.read_text(encoding="utf-8")
    named = set(re.findall(r"\b[0-9a-f]{40}\b", text))
    assert named == {B6} | {anchor for anchor, _, _ in GATES.values()}
    for line in ("LLM PROPOSES.", "DETERMINISTIC CODE VALIDATES.", "HUMAN DECIDES.", "AUTHORITY LAYER RECORDS."):
        assert line in text, line
