"""P10-A1 — Phase 10（Personal Intelligence）の境界の guard。

- registry の完全一致 ・P10_BASE 以後の面は登録した P10 の追加だけ ・凍結の P7 ／ P8 ／ P9 の test の差分は宣言した登録の行だけ。
- P9 runtime は凍結 anchor `P9_A5` と ・P8 runtime は `P8_B5C` と byte 一致 ・P7 runtime は P10_BASE と不変。
- `p9_view` の import の面は凍結 P9 の read-only の部品の完全一致だけ（`AuthorityStores` ・実行器 ・local の入口 ・P8 ・J-Quants ・
  network ・LLM ・P5 ・公開の出力は無い）。書き込み ・作成 ・環境変数 ・時計なし。store は P9 の read-only の型の `open` だけ。
- production runtime closure の外 ・他の package から import されない ・識別子に順位 ／ 推奨 ／ 売買の語なし。
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from tests.intelligence.phase7_runtime_registry import PHASE7_RUNTIME
from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import P9_A5, PHASE9_RUNTIME
from tests.intelligence.phase10_runtime_registry import (P10_BASE, P10_P9_VIEW, PHASE10_DOCS, PHASE10_PACKAGE,
                                                         PHASE10_RUNTIME, PHASE10_TEST_REGISTRATION, PHASE10_TESTS,
                                                         SANCTIONED_P10_P9_IMPORTERS, SANCTIONED_P10_P9_IMPORTS,
                                                         only_phase10_registration)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE10_PACKAGE
CONTRACT_DOC = "docs/databank/PHASE10_A1_P9_READONLY_ADAPTER.md"
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "docs/v2", "main.py",
                  "requirements.txt", "pyproject.toml")
STDLIB_IMPORTS = {"__future__", "dataclasses", "datetime", "typing"}
FORBIDDEN_MODULE_PARTS = ("screener_intelligence", "jquants", "predictions", "analysis", "report", "notifier",
                          "compass", "pages", "pwa", "llm", "anthropic", "openai", "http", "urllib", "requests",
                          "socket", "ssl", "subprocess", "authority_stores", "executor", "local_cli", "decision_model",
                          "p8_handoff", "p8_identity", "theme", "narrative")
FORBIDDEN_NAMES = {"AuthorityStores", "initialize", "_append_line", "append_watch", "append_thesis", "append",
                   "write", "write_text", "write_bytes", "mkdir", "unlink", "rmtree", "remove", "rename", "touch",
                   "truncate", "environ", "getenv", "now", "today", "utcnow", "print", "input", "sleep", "getattr",
                   "setattr", "eval", "exec", "fsync", "flush", "system", "popen"}
FORBIDDEN_WORDS = {"rank", "ranking", "score", "scoring", "recommend", "recommendation", "buy", "sell", "portfolio",
                   "allocation", "target", "conviction", "priority", "weight", "rating", "position", "trade",
                   "instruction", "llm", "prompt", "latest", "current", "automation", "schedule", "cron"}
P9_STORE_OPENERS = {"WatchlistStore", "ThesisStore"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _imports(path: Path):
    relative, absolute = {}, set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


# ================================================ registry ・面 ・凍結の test の登録


def test_p10_a1_the_registry_is_exact_and_disjoint_from_earlier_phases() -> None:
    assert P10_BASE == "3bfc76c6b2f76f613bb50710e6e7eb976a642326"
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P10_BASE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert PHASE10_RUNTIME == (f"{PHASE10_PACKAGE}/__init__.py", P10_P9_VIEW)
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE10_RUNTIME}
    for path in (*PHASE10_RUNTIME, *PHASE10_TESTS, *PHASE10_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert not set(PHASE10_RUNTIME) & (set(PHASE9_RUNTIME) | set(PHASE8_RUNTIME) | set(PHASE7_RUNTIME))
    assert not any(_git("ls-tree", P10_BASE, "--", p).strip() for p in (*PHASE10_RUNTIME, *PHASE10_TESTS,
                                                                       *PHASE10_DOCS))
    assert set(SANCTIONED_P10_P9_IMPORTERS) == {P10_P9_VIEW}                       # Phase 9 の importer は 1 file だけ


def test_p10_a1_since_the_base_only_registered_phase10_files_and_declared_registration_changed() -> None:
    assert _changes("--cached", "--name-status", P10_BASE, "--", "src") == {("A", p) for p in PHASE10_RUNTIME}
    assert _git("diff", "--cached", "--name-status", P10_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P10_BASE, "--", "docs") <= {("A", p) for p in PHASE10_DOCS}
    assert _changes("--cached", "--name-status", P10_BASE, "--", "tests") <= {
        ("A", p) for p in PHASE10_TESTS} | {("M", p) for p in PHASE10_TEST_REGISTRATION}
    assert set(PHASE10_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                              "tests/intelligence/test_narrative_intelligence_boundary.py",
                                              "tests/intelligence/test_screener_intelligence_boundary.py",
                                              "tests/intelligence/test_watchlist_thesis_boundary.py"}
    for path in PHASE10_TEST_REGISTRATION:                                            # 凍結の P7 ／ P8 ／ P9 の test の狭い再開
        anchored = _git("show", f"{P10_BASE}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase10_registration(path, anchored, current), path
        assert not only_phase10_registration(path, anchored, current + "assert True\n")
        assert not only_phase10_registration(path, anchored, anchored)
    for registry in ("tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/phase9_runtime_registry.py"):
        assert _git("diff", "--name-status", P10_BASE, "--", registry) == "", registry   # P8 ／ P9 の registry は不変


def test_p10_a1_earlier_phase_runtime_is_byte_identical_to_its_freeze_anchor() -> None:
    assert P9_A5 == "4c1970174f678245b569fdbb812a8a6ced52410b" and len(PHASE9_RUNTIME) == 18
    for anchor, runtime in ((P9_A5, PHASE9_RUNTIME), (P8_B5C, PHASE8_RUNTIME)):
        for path in runtime:
            assert _git("show", f"{anchor}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P10_BASE, "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME, *PHASE9_RUNTIME) == ""
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME, *PHASE9_RUNTIME) == ""


# ================================================ import の面 ・書き込み ・語彙


def test_p10_a1_imports_are_exactly_the_sanctioned_read_only_phase9_surfaces() -> None:
    for path in PHASE10_RUNTIME:
        relative, absolute = _imports(REPO_ROOT / path)
        assert absolute <= STDLIB_IMPORTS, absolute - STDLIB_IMPORTS
        if path == P10_P9_VIEW:
            assert relative == SANCTIONED_P10_P9_IMPORTS
        else:
            assert relative == {} and absolute == set()                                 # docstring だけ
        for module in (*relative, *absolute):
            assert not any(part in module for part in FORBIDDEN_MODULE_PARTS), module
        assert not any(n.startswith("_") for names in relative.values() for n in names)


def test_p10_a1_the_adapter_never_writes_creates_reads_credentials_or_uses_write_capable_p9_objects() -> None:
    for path in PHASE10_RUNTIME:
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        words = set()
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES | {"open"}), node.id
            assert not (isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES), node.attr
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open":
                assert isinstance(node.func.value, ast.Name) and node.func.value.id in P9_STORE_OPENERS, "open"
                assert len(node.args) == 1 and not node.keywords, "open(p9_root) only"
            assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")))), "broad except"
            names = [node.id] if isinstance(node, ast.Name) else [node.attr] if isinstance(node, ast.Attribute) else \
                [node.arg] if isinstance(node, ast.arg) else [node.name] if isinstance(
                    node, (ast.FunctionDef, ast.ClassDef)) else []
            for name in names:
                words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}
        assert not words & FORBIDDEN_WORDS, words & FORBIDDEN_WORDS
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        for token in ("JQUANTS_API_KEY", "x-api-key", "api.jquants.com", "://", "config.yaml", "watchlist:"):
            assert token not in source, token


def test_p10_a1_is_outside_production_and_no_other_code_imports_it() -> None:
    assert not any("personal_intelligence" in module for module in runtime_closure())
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")),
                 *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if not path.exists() or PACKAGE_DIR in path.parents:
            continue
        assert "personal_intelligence" not in path.read_text(encoding="utf-8", errors="replace"), path


def test_p10_a1_the_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in ("P9-OBS-019", "AuthorityStores", "read_p9_safe_view", "read_p9_private_snapshot", "check_world",
                   "P9_WORLD_INVALID", "P9_STORE_UNAVAILABLE", "P10_BASE", "3bfc76c6b2f76f613bb50710e6e7eb976a642326",
                   "PHASE10_TEST_REGISTRATION", "FOCUS", "Phase 10 の凍結ではない"):
        assert clause in text, clause
