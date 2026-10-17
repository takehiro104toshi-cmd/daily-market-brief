"""P11-A1 — Phase 11（personal_ui）の境界の guard。

- registry の完全一致 ・P11_BASE 以後の面は登録した P11 の追加だけ ・凍結の P7 ／ P8 ／ P9 ／ P10 の test の差分は宣言した登録の行だけ。
- P7 〜 P10 の runtime は凍結 anchor と git の object で一致（locale ・改行に依らない）。
- adapter の import は凍結 P10 の governed な read の API の完全一致だけ（store ・実行器 ・直列化 ・管理の初期化 ・private な P9 の
  snapshot ・P9 の store ・P8 ・J-Quants ・公開 ・通知 ・network ・LLM は無い）。stdlib も狭い。書き込み ・環境変数 ・時計なし。
- production runtime closure の外 ・公開の Pages の workflow ／ script ／ 公開の report の code から参照されない ・公開の report の code は
  P8 〜 P11 の package を import しない。
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from tests.intelligence.phase7_runtime_registry import PHASE7_RUNTIME
from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import P9_A5, PHASE9_RUNTIME
from tests.intelligence.phase10_runtime_registry import P10_A4, PHASE10_PACKAGE, PHASE10_RUNTIME
from tests.intelligence.phase11_runtime_registry import (FORBIDDEN_P11_IMPORT_PARTS, P11_ADAPTER, P11_BASE,
                                                         P11_UI_MODEL, PHASE11_A1_RUNTIME, PHASE11_DOCS,
                                                         PHASE11_PACKAGE, PHASE11_RUNTIME, PHASE11_TEST_REGISTRATION,
                                                         PHASE11_TESTS, SANCTIONED_P11_MODULES,
                                                         SANCTIONED_P11_P10_IMPORTERS, SANCTIONED_P11_P10_IMPORTS,
                                                         only_phase11_registration)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE11_PACKAGE
CONTRACT_DOC = "docs/databank/PHASE11_A1_GOVERNED_READ_ADAPTER.md"
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "main.py", "requirements.txt",
                  "pyproject.toml", "cloudflare", "notifiers", "src/report")
STDLIB_IMPORTS = {"__future__", "dataclasses", "datetime", "json", "re", "typing"}
FORBIDDEN_NAMES = {"open", "write", "write_text", "write_bytes", "read_text", "read_bytes", "mkdir", "unlink", "remove",
                   "rename", "environ", "getenv", "now", "today", "utcnow", "print", "input", "sleep", "eval", "exec",
                   "getattr_static", "setattr", "random", "urandom", "uuid4", "system", "popen", "initialize",
                   "append_profile_revision", "append_attention_revision", "apply_decision", "dry_run_decision",
                   "read_p9_private_snapshot", "ProfileStore", "AttentionStore", "PersonalAuthorityStores"}
FORBIDDEN_WORDS = {"rank", "ranking", "score", "scoring", "recommend", "recommendation", "buy", "sell", "portfolio",
                   "allocation", "conviction", "priority", "weight", "rating", "position", "trade", "urgency",
                   "confidence", "return", "returns", "price", "holding", "holdings", "rebalance", "suitability",
                   "llm", "prompt", "latest", "current", "now", "automation", "schedule", "cron", "push", "notify"}
FORBIDDEN_COMPOUNDS = ("target_price", "target_return", "expected_return", "risk_score", "position_size")
PUBLIC_CODE = ("main.py", "src/report", "notifiers", "scripts", ".github", "docs/pages", "cloudflare")
PRIVATE_PACKAGES = ("screener_intelligence", "watchlist_thesis_intelligence", "personal_intelligence", "personal_ui")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, encoding="utf-8", errors="strict",
                          check=True).stdout


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _blob_ids(anchor: str, paths) -> tuple:
    anchored = tuple(_git("rev-parse", *(f"{anchor}:{path}" for path in paths)).split())
    current = tuple(_git("hash-object", "--", *paths).split())
    return anchored, current


def _imports(path: Path):
    relative, absolute = {}, set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + (node.module or ""), set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


def _files_under(*roots: str):
    for root in roots:
        path = REPO_ROOT / root
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (p for p in sorted(path.rglob("*")) if p.is_file() and p.suffix in (".py", ".yml", ".yaml",
                                                                                           ".html", ".js", ".toml"))


# ================================================ registry ・面 ・凍結の test の登録


def test_p11_a1_the_registry_is_exact_and_disjoint_from_earlier_phases() -> None:
    assert P11_BASE == "d01f6bc01fba783e77cc3a623745b8b033883e1a"
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P11_BASE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert PHASE11_A1_RUNTIME == (f"{PHASE11_PACKAGE}/__init__.py", P11_ADAPTER, P11_UI_MODEL)
    assert PHASE11_RUNTIME == tuple(sorted(PHASE11_A1_RUNTIME)) and len(PHASE11_RUNTIME) == 3
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE11_RUNTIME}
    for path in (*PHASE11_RUNTIME, *PHASE11_TESTS, *PHASE11_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert not set(PHASE11_RUNTIME) & (set(PHASE10_RUNTIME) | set(PHASE9_RUNTIME) | set(PHASE8_RUNTIME)
                                       | set(PHASE7_RUNTIME))
    assert not any(_git("ls-tree", P11_BASE, "--", p).strip() for p in (*PHASE11_RUNTIME, *PHASE11_TESTS,
                                                                       *PHASE11_DOCS))
    assert set(SANCTIONED_P11_P10_IMPORTERS) == {P11_ADAPTER}                        # Phase 10 の importer は 1 file だけ
    assert set(SANCTIONED_P11_MODULES) == set(PHASE11_RUNTIME)


def test_p11_a1_since_the_base_only_registered_phase11_files_and_declared_registration_changed() -> None:
    assert _changes("--cached", "--name-status", P11_BASE, "--", "src") == {("A", p) for p in PHASE11_RUNTIME}
    assert _git("diff", "--cached", "--name-status", P11_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P11_BASE, "--", "docs") <= {("A", p) for p in PHASE11_DOCS}
    assert _changes("--cached", "--name-status", P11_BASE, "--", "tests") <= {
        ("A", p) for p in PHASE11_TESTS} | {("M", p) for p in PHASE11_TEST_REGISTRATION}
    assert set(PHASE11_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                              "tests/intelligence/test_narrative_intelligence_boundary.py",
                                              "tests/intelligence/test_screener_intelligence_boundary.py",
                                              "tests/intelligence/test_watchlist_thesis_boundary.py",
                                              "tests/intelligence/test_personal_intelligence_boundary.py"}
    for path in PHASE11_TEST_REGISTRATION:                                            # 凍結の P7 〜 P10 の test の狭い再開
        anchored = _git("show", f"{P11_BASE}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase11_registration(path, anchored, current), path
        assert not only_phase11_registration(path, anchored, current + "assert True\n")
        assert not only_phase11_registration(path, anchored, anchored)
    for registry in ("tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/phase9_runtime_registry.py",
                     "tests/intelligence/phase10_runtime_registry.py"):
        assert _git("diff", "--name-status", P11_BASE, "--", registry) == "", registry   # 前の phase の registry は不変


def test_p11_a1_frozen_phase_runtime_is_object_identical_to_its_anchor() -> None:
    for anchor, runtime in ((P10_A4, PHASE10_RUNTIME), (P9_A5, PHASE9_RUNTIME), (P8_B5C, PHASE8_RUNTIME)):
        anchored, current = _blob_ids(anchor, runtime)
        assert len(anchored) == len(current) == len(runtime)
        assert [p for p, a, c in zip(runtime, anchored, current) if a != c] == []
    assert len(PHASE10_RUNTIME) == 17 and len(PHASE9_RUNTIME) == 18 and len(PHASE8_RUNTIME) == 54
    assert _git("diff", "--name-status", P11_BASE, "--", *PHASE7_RUNTIME, PHASE10_PACKAGE,
                "src/intelligence/watchlist_thesis_intelligence", "src/intelligence/screener_intelligence") == ""
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME, *PHASE9_RUNTIME,
                *PHASE10_RUNTIME) == ""


# ================================================ import の面 ・書き込み ・語彙


def test_p11_a1_imports_are_exactly_the_sanctioned_governed_read_surfaces() -> None:
    for path in PHASE11_RUNTIME:
        relative, absolute = _imports(REPO_ROOT / path)
        assert absolute <= STDLIB_IMPORTS, (path, absolute - STDLIB_IMPORTS)
        assert set(relative) == SANCTIONED_P11_MODULES[path], (path, set(relative))
        if path == P11_ADAPTER:
            assert {m: n for m, n in relative.items() if m.startswith("..")} == SANCTIONED_P11_P10_IMPORTS
            assert relative[".ui_model"] == {"UiModel", "UiReadError", "UiReviewEntry"}
        for module in (*relative, *absolute):                                          # module の部品の完全一致で禁止
            components = set(module.lstrip(".").split("."))
            assert not components & set(FORBIDDEN_P11_IMPORT_PARTS), (path, module)
        assert not any(n.startswith("_") for names in relative.values() for n in names)
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        for token in ("JQUANTS_API_KEY", "x-api-key", "api.jquants.com", "://", "config.yaml", "watchlist:",
                      "AuthorityStores", "read_p9_private_snapshot", "executor", "store_io"):
            assert token not in source, (path, token)


def test_p11_a1_the_runtime_never_writes_reads_files_env_or_clock_and_has_no_investment_vocabulary() -> None:
    for path in PHASE11_RUNTIME:
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        words = set()
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_NAMES, (path, node.id)
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_NAMES, (path, node.attr)
                identifiers.add(node.attr)
            elif isinstance(node, ast.arg):
                identifiers.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                identifiers.add(node.name)
            assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")))), "broad except"
        for name in identifiers:
            words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}
        assert not words & FORBIDDEN_WORDS, (path, words & FORBIDDEN_WORDS)
        lowered = {n.lower() for n in identifiers}
        for compound in FORBIDDEN_COMPOUNDS:
            assert not any(compound in n for n in lowered), compound


def test_p11_a1_is_outside_production_pages_and_public_code_and_public_code_imports_no_private_phase() -> None:
    assert not any("personal_ui" in module for module in runtime_closure())
    for path in _files_under(*PUBLIC_CODE):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "personal_ui" not in text, path                                        # Pages ・公開 ・script から参照されない
    for path in _files_under("main.py", "src/report", "notifiers"):                   # 公開の report の code は P8 〜 P11 を import しない
        text = path.read_text(encoding="utf-8", errors="replace")
        for package in PRIVATE_PACKAGES:
            assert package not in text, (path, package)
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")),
                 *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if PACKAGE_DIR in path.parents:
            continue
        assert "personal_ui" not in path.read_text(encoding="utf-8", errors="replace"), path


def test_p11_a1_the_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in (P11_BASE, "read_personal_review", "personal_safe_projection", "read_p9_safe_view", "ordinal",
                   "p9_root_id", "issuer_id", "INPUT_INVALID", "P10_UNAVAILABLE", "P9_UNAVAILABLE",
                   "PHASE11_TEST_REGISTRATION", "P11-OBS-016", "Phase 11 の凍結ではない", "read-only"):
        assert clause in text, clause
    for banned in ("p9wat_", "p10prf_", "human:", "D:\\"):
        assert banned not in text, banned
