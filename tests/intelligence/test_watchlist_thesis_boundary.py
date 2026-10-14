"""P9-A1 — Phase 9（Watchlist / Thesis Intelligence）の境界の guard。

- registry の完全一致 ・P9_BASE 以後の面は登録した P9 の追加だけ ・凍結の P7 ／ P8 の test の差分は宣言した登録の行だけ。
- P8 runtime は凍結 anchor `P8_B5C` と byte 一致 ・P7 runtime は P9_BASE と不変。
- import の面は凍結の P8 の再構成の部品の完全一致だけ。P5 ・`src.analysis` ・`src.report` ・通知 ・公開 ・PWA ・LLM ・HTTP ・P8 の書き込み ・
  実行の経路を import しない。transport を作らない ・store の `open` は `read_only=True` だけ ・書き込み ・環境変数 ・時計なし。
- 順位 ・点数 ・推奨の語なし ・production runtime closure の外 ・他の package から import されない ・既存の公開の watchlist に触れない。
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from tests.intelligence.phase7_runtime_registry import PHASE7_RUNTIME
from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import (P9_BASE, P9_HANDOFF, PHASE9_A1_RUNTIME, PHASE9_DOCS,
                                                        PHASE9_PACKAGE, PHASE9_RUNTIME, PHASE9_TEST_REGISTRATION,
                                                        PHASE9_TESTS, SANCTIONED_P9_A1_IMPORTS,
                                                        only_phase9_registration)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE9_PACKAGE
CONTRACT_DOC = "docs/databank/PHASE9_A1_P8_HANDOFF_CONTRACT.md"
#: P9_BASE 以後に変わってはいけない面（data は journal の副作用があるので除く）
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "docs/v2", "main.py",
                  "requirements.txt", "pyproject.toml")
#: 外部の import として許す標準 library（module の完全一致）
STDLIB_IMPORTS = {"__future__", "dataclasses", "datetime", "os.path", "pathlib", "re", "typing"}
FORBIDDEN_MODULE_PARTS = ("predictions", "analysis", "report", "notifier", "compass", "pages", "pwa", "llm", "anthropic",
                          "openai", "http", "urllib", "requests", "socket", "ssl", "subprocess", "jquants_local_transport",
                          "jquants_live", "jquants_pilot2_local", "theme", "narrative")   # 時計 ・乱数は標準 library の完全一致で除く
FORBIDDEN_NAMES = {"execute_screen", "main", "_store_integrity", "LocalHttpsTransport", "JQuantsLiveClient", "LedgerWriter",
                   "_create_ledger", "initialize", "append", "write_text", "write_bytes", "mkdir", "unlink", "rmtree",
                   "remove", "rename", "touch", "environ", "getenv", "urlopen", "getattr", "setattr", "eval", "exec",
                   "sleep", "now", "today", "utcnow", "open", "print", "input"}
FORBIDDEN_WORDS = {"rank", "ranking", "score", "scoring", "recommend", "recommendation", "buy", "sell", "portfolio",
                   "allocation", "target", "conviction", "priority", "weight", "llm", "prompt", "morning", "cron",
                   "schedule", "latest", "promote", "promotion"}           # "watchlist" は namespace の名に含まれる


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    relative, absolute = {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


# ================================================ registry ・面 ・凍結の P7 ／ P8 の test の登録


def test_p9_a1_the_registry_is_exact_and_disjoint_from_earlier_phases() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P9_BASE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert PHASE9_RUNTIME == tuple(sorted(PHASE9_A1_RUNTIME)) and len(PHASE9_RUNTIME) == 3
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE9_RUNTIME}
    assert P9_HANDOFF in PHASE9_RUNTIME
    for path in (*PHASE9_RUNTIME, *PHASE9_TESTS, *PHASE9_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert not set(PHASE9_RUNTIME) & (set(PHASE8_RUNTIME) | set(PHASE7_RUNTIME))
    assert not any(_git("ls-tree", P9_BASE, "--", path).strip() for path in (*PHASE9_RUNTIME, *PHASE9_TESTS,
                                                                             *PHASE9_DOCS))


def test_p9_a1_since_the_base_only_the_registered_phase9_files_and_declared_registration_changed() -> None:
    assert _changes("--cached", "--name-status", P9_BASE, "--", "src") == {("A", path) for path in PHASE9_RUNTIME}
    assert _git("diff", "--cached", "--name-status", P9_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P9_BASE, "--", "docs") <= {("A", path) for path in PHASE9_DOCS}
    assert _changes("--cached", "--name-status", P9_BASE, "--", "tests") <= {
        ("A", path) for path in PHASE9_TESTS} | {("M", path) for path in PHASE9_TEST_REGISTRATION}
    for path in PHASE9_TEST_REGISTRATION:                                             # 凍結の P7 ／ P8 の test の狭い再開
        anchored = _git("show", f"{P9_BASE}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase9_registration(path, anchored, current), path
        assert not only_phase9_registration(path, anchored, current + "assert True\n")  # 未登録の追加
        assert not only_phase9_registration(path, anchored, anchored)                  # 登録の欠落
    assert set(PHASE9_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                             "tests/intelligence/test_narrative_intelligence_boundary.py",
                                             "tests/intelligence/test_screener_intelligence_boundary.py"}
    assert "tests/intelligence/phase8_runtime_registry.py" not in PHASE9_TEST_REGISTRATION   # P8 の registry は不変


def test_p9_a1_phase8_runtime_is_byte_identical_to_the_freeze_anchor_and_phase7_is_untouched() -> None:
    assert P8_B5C == "0a32d86bd80d0f9a0b9f4cecbd7c961a93dfa15f" and len(PHASE8_RUNTIME) == 54
    for path in PHASE8_RUNTIME:
        assert _git("show", f"{P8_B5C}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_B5C, "--", *PHASE8_RUNTIME) == ""
    assert _git("diff", "--name-status", P9_BASE, "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME) == ""
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME) == ""


# ================================================ import の面 ・書き込み ・network ・語彙


@pytest.mark.parametrize("path", PHASE9_RUNTIME)
def test_p9_a1_imports_are_exactly_the_sanctioned_frozen_reconstruction_surfaces(path: str) -> None:
    relative, absolute = _imports(REPO_ROOT / path)
    assert absolute <= STDLIB_IMPORTS, absolute - STDLIB_IMPORTS
    if path == P9_HANDOFF:
        assert relative == SANCTIONED_P9_A1_IMPORTS
    elif path.endswith("__init__.py"):
        assert relative == {} and absolute == set()                                     # docstring だけ
    else:
        assert relative == {}                                                           # private_root は標準 library だけ
    for module in (*relative, *absolute):
        assert not any(part in module for part in FORBIDDEN_MODULE_PARTS), module
    assert not any(n.startswith("_") for names in relative.values() for n in names)     # private な P8 の名前なし


@pytest.mark.parametrize("path", PHASE9_RUNTIME)
def test_p9_a1_never_executes_writes_reads_credentials_or_opens_stores_for_writing(path: str) -> None:
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES), node.id
        assert not (isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES - {"open"}), node.attr
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            assert any(k.arg == "read_only" and isinstance(k.value, ast.Constant) and k.value.value is True
                       for k in node.keywords), "store.open must be read_only=True"
        assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")))), "broad except"
    source = executable_source(REPO_ROOT / path)
    words = set(re.findall(r"[a-z]+", source.lower()))
    assert not words & FORBIDDEN_WORDS, words & FORBIDDEN_WORDS
    for token in ("JQUANTS_API_KEY", "x-api-key", "api.jquants.com", "://", "config.yaml", "docs/pages", "docs/v2"):
        assert token not in source, token


def test_p9_a1_is_outside_production_and_no_other_code_imports_it() -> None:
    assert not any("watchlist_thesis_intelligence" in module for module in runtime_closure())
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")),
                 *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if not path.exists() or PACKAGE_DIR in path.parents:
            continue
        assert "watchlist_thesis_intelligence" not in path.read_text(encoding="utf-8", errors="replace"), path
    for legacy in ("src/analysis/models.py", "src/report/sections.py"):                 # 既存の公開の watchlist は不変
        assert _git("diff", "--name-status", P9_BASE, "--", legacy) == ""


def test_p9_a1_the_handoff_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in ("P8 `ScreenResultSet` ≠ P9 Watchlist の項目 ≠ P9 Thesis ≠ 推奨 ≠ 売買の指示", "read-only",
                   "J-Quants の request は要らない", "`JQUANTS_API_KEY` は要らない", "COMPLETE の run だけ",
                   "P8_RUN_OPEN_INVOCATION", "P8_RUN_NOT_COMPLETE", "`run_id` と消費した `screen_result_id` の両方",
                   "P8_RESULT_DRIFT", "ONE_P8_RUN_PER_PRIVATE_ROOT_PER_D0", "Phase 9 の凍結ではない",
                   "watchlist_thesis_intelligence", "0a32d86bd80d0f9a0b9f4cecbd7c961a93dfa15f"):
        assert clause in text, clause
