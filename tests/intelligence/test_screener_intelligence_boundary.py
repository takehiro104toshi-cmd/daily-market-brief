"""Phase 8 Screener Intelligence の境界 ／ 凍結の guard（P8-A1 の matrix BA〜BO）。

- BA〜BG: import 境界（module ごとの許可一覧 ・runtime closure）。Phase 6 ／ 7 ・P5 ・legacy ・J-Quants の transport ・
  provider ／ network ・公開 ／ 通知 ／ 売買を import しない。時計 ・乱数 ・動的 code なし。filesystem は store だけ。
- BH〜BJ: screen ・基準 ・候補 ・順位 ・score ・Theme exposure の型 ／ 名前が無い。
- BK〜BO: Phase 7 ／ 6 の凍結、Phase 8 の registry の完全一致、未登録の Phase 8 runtime の検出、他の package からの import なし。

registry: `tests/intelligence/phase8_runtime_registry.py`。契約: `docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md`。
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.intelligence.phase7_runtime_registry import (PHASE6_TEST_REGISTRATION, PHASE7_EXCLUDED_PATHSPECS,
                                                        PHASE7_RUNTIME, is_phase7_addition)
from tests.intelligence.phase8_runtime_registry import (ADDITION_STATUSES, P8_A0, PHASE7_TEST_REGISTRATION,
                                                        PHASE8_DOCS, PHASE8_PACKAGE, PHASE8_RUNTIME, PHASE8_TESTS,
                                                        is_phase8_addition, only_phase8_registration)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
MODULES = ("__init__", "identity_model", "identity_resolver", "identity_store")
PURE_MODULES = ("__init__", "identity_model", "identity_resolver")
IO_MODULE = "identity_store"
PHASE7_FINAL = "c1e95d35026652fb27c637318593fa8688219cf7"
PHASE6_COMPLETION = "5ef313a6a9477f05b4e46756fb8b79c0f0c3d685"
A1_DOC = "docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md"
PHASE7_DOCS = tuple(f"docs/databank/PHASE7_{name}.md" for name in (
    "NARRATIVE_ARCHITECTURE_AUDIT", "NARRATIVE_SEMANTICS_MODEL_CONTRACT", "NARRATIVE_PIT_INPUT_CONTRACT",
    "NARRATIVE_DETERMINISTIC_SYNTHESIS_CONTRACT", "NARRATIVE_PRESENTATION_DIFF_CONTRACT",
    "NARRATIVE_DETERMINISTIC_RENDERER_CONTRACT", "NARRATIVE_INTELLIGENCE_COMPLETION_AUDIT"))
SURFACE = ("src", "knowledge", "config.yaml", ".github", "scripts", "docs/pages", "docs/v2", "data", "main.py",
           "requirements.txt", "pyproject.toml")

_CORE = {"..core.ids", "..core.time"}
ALLOWED_IMPORTS = {
    "__init__": set(),
    "identity_model": {"__future__", "json", "re", "dataclasses", "datetime", "enum", "typing"} | _CORE,
    "identity_store": {"__future__", "os", "dataclasses", "enum", "pathlib", "typing", ".identity_model"},
    "identity_resolver": {"__future__", "dataclasses", "datetime", "enum", "typing", ".identity_model",
                          ".identity_store", "..core.time"},
}
ALLOWED_CLOSURE = {"src", "src.intelligence", "src.intelligence.core", "src.intelligence.core.ids",
                   "src.intelligence.core.time", "src.intelligence.screener_intelligence"}
EXPECTED_INTERNAL = {"__init__": set(), "identity_model": set(), "identity_store": {"identity_model"},
                     "identity_resolver": {"identity_model", "identity_store"}}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _sources():
    return [(path.stem, path) for path in sorted(PACKAGE_DIR.glob("*.py"))]


# ================================================================ BA〜BG import 境界


@pytest.mark.parametrize("name,path", _sources())
def test_ba_to_bg_modules_import_only_their_allowed_modules(name: str, path: Path) -> None:
    assert imported_modules(path) <= ALLOWED_IMPORTS[name], imported_modules(path) - ALLOWED_IMPORTS[name]


@pytest.mark.parametrize("module", MODULES)
def test_ba_to_bg_the_runtime_closure_is_core_and_this_package_only(module: str) -> None:
    target = "src.intelligence.screener_intelligence" + ("" if module == "__init__" else f".{module}")
    code = f"import sys\nimport {target}\nprint('\\n'.join(sorted(sys.modules)))\n"
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                          env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    loaded = set(proc.stdout.split())
    first_party = {m for m in loaded if m.startswith("src")}
    if module == "__init__":                                                         # package は何も import しない
        assert first_party == {"src", "src.intelligence", "src.intelligence.screener_intelligence"}
    else:
        internal = {module} | EXPECTED_INTERNAL[module]
        assert first_party == ALLOWED_CLOSURE | {f"src.intelligence.screener_intelligence.{n}" for n in internal}
    assert not loaded & {"socket", "ssl", "http", "http.client", "urllib.request", "sqlite3", "requests", "httpx",
                         "anthropic", "openai"}                                    # 乱数 ・時計の使用は AST で禁止


FORBIDDEN_MODULE_TOKENS = ("themes", "theme_intelligence", "narrative_intelligence", "predictions", "compass",
                           "reports", "facts", "context", "internals", "market", "jquants", "jquants_ops", "databank",
                           "analysis", "report", "collectors", "notifiers", "delivery", "pages", "public", "evaluation",
                           "calibration", "corpus", "formal_review", "decision", "thesis", "screening",
                           "personalization", "replay", "pipeline", "enrichment", "sources", "ingestion", "provider",
                           "providers", "anthropic", "openai", "requests", "httpx", "urllib", "socket", "sqlite3",
                           "subprocess", "trading", "portfolio", "notification", "llm")


@pytest.mark.parametrize("name,path", _sources())
def test_ba_to_bg_no_phase6_phase7_p5_legacy_jquants_provider_network_or_public_import(name: str, path: Path) -> None:
    for module in imported_modules(path):
        assert not any(token in module.split(".") for token in FORBIDDEN_MODULE_TOKENS), module


FORBIDDEN_NAMES = {"print", "input", "eval", "exec", "compile", "__import__", "getattr", "setattr", "globals",
                   "sys", "subprocess", "socket", "urllib", "requests", "sqlite3", "pickle", "shelve", "random",
                   "secrets", "uuid", "time", "new_id", "new_ulid", "environ", "getenv", "sha256_hex"}
FORBIDDEN_ATTRIBUTES = {"now", "utcnow", "today", "environ", "getenv", "urlopen", "connect", "request", "getmtime",
                        "st_mtime", "st_mtime_ns", "getpid", "urandom"}
IO_NAMES = {"open", "Path", "os"}
IO_ATTRIBUTES = {"write", "write_text", "write_bytes", "read_text", "read_bytes", "mkdir", "unlink", "touch", "rename",
                 "rmdir", "remove", "makedirs", "fsync", "flush", "replace_file", "truncate"}


@pytest.mark.parametrize("name,path", _sources())
def test_ba_to_bg_no_clock_randomness_network_or_dynamic_code_and_io_only_in_the_store(name: str, path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in FORBIDDEN_NAMES, (name, node.id)
            if name != IO_MODULE:
                assert node.id not in IO_NAMES, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in FORBIDDEN_ATTRIBUTES, (name, node.attr)
            if name != IO_MODULE:
                assert node.attr not in IO_ATTRIBUTES, (name, node.attr)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise AssertionError((name, "module state"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "://" not in node.value and "C:\\" not in node.value, (name, node.value)


def test_ba_to_bg_the_store_writes_only_through_append_and_initialize() -> None:
    tree = ast.parse((PACKAGE_DIR / "identity_store.py").read_text(encoding="utf-8"))
    writers = {}
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(func):
            if isinstance(node, ast.Constant) and node.value in ("ab", "wb", "w", "a", "r+", "w+", "a+"):
                writers.setdefault(func.name, set()).add(node.value)
            if isinstance(node, ast.Attribute) and node.attr in ("write", "mkdir", "fsync", "write_bytes", "unlink"):
                writers.setdefault(func.name, set()).add(node.attr)
    assert writers == {"__init__": {"ab", "mkdir"}, "append": {"ab", "write", "fsync"}}
    assert "sqlite" not in executable_source(PACKAGE_DIR / "identity_store.py").lower()


# ================================================================ BH〜BJ screen ・score ・Theme なし


SCREENING_WORDS = ("screen", "criterion", "criteria", "candidate_result", "rank", "score", "rating", "filter",
                   "recommend", "attractive", "target_price", "expected_return", "weight", "buy", "sell", "watchlist",
                   "portfolio", "thesis", "theme", "exposure", "beneficiar", "narrative", "forecast", "price", "fundamental")


@pytest.mark.parametrize("name,path", _sources())
def test_bh_bi_bj_no_screening_score_rank_or_theme_types(name: str, path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {node.name.lower() for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Assign) for t in node.targets
               if isinstance(t, ast.Name)}
    for word in SCREENING_WORDS:
        assert not any(word in item for item in defined | targets), (name, word)
    source = executable_source(path).lower()
    for token in ("score", "rank", "screening", "recommend", "theme", "exposure", "watchlist", "llm", "prompt"):
        assert token not in source, (name, token)


def test_bh_bi_bj_the_vocabulary_has_no_evaluative_member() -> None:
    from src.intelligence.screener_intelligence import identity_model as m
    from src.intelligence.screener_intelligence import identity_resolver as r
    members = {member.value for enum in (m.RecordKind, m.SourceClass, m.IssueClass, m.IdentifierScheme,
                                         m.RetirementReason, m.SubjectKind, m.NameKind, m.NameLanguage,
                                         m.ListingVenue, m.ListingEndReason, m.CoverageScope, r.ResolutionStatus,
                                         r.QueryKind) for member in enum}
    for word in ("RANK", "SCORE", "BUY", "SELL", "TOP", "BEST", "CANDIDATE", "PASS", "FAIL", "THEME", "EXPOSURE"):
        assert not any(word in value for value in members), word
    resolution_fields = set(r.IdentityResolution.__dataclass_fields__)
    assert not resolution_fields & {"score", "rank", "weight", "recommendation", "record_id"}


# ================================================================ BK〜BL 凍結


def test_bk_phase7_runtime_and_documents_are_byte_identical_to_the_final_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", PHASE7_FINAL, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in (*PHASE7_RUNTIME, *PHASE7_DOCS):
        assert _git("show", f"{PHASE7_FINAL}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE7_DOCS) == ""


def test_bk_phase7_tests_changed_only_by_the_declared_phase8_registration() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A0, "HEAD"], cwd=REPO_ROOT).returncode == 0
    changed = {tuple(line.split("\t")) for line in _git("diff", "--name-status", P8_A0, "--", "tests").splitlines()}
    assert changed <= {("M", path) for path in PHASE7_TEST_REGISTRATION} | {("A", path) for path in PHASE8_TESTS}
    for path in PHASE7_TEST_REGISTRATION:
        anchored = _git("show", f"{P8_A0}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase8_registration(path, anchored, current), path
        assert not only_phase8_registration(path, anchored, current + "assert True\n")        # 未登録の追加
        assert not only_phase8_registration(path, anchored, anchored)                           # 登録の欠落
    untouched = "tests/intelligence/test_narrative_phase7_e2e.py"
    text = (REPO_ROOT / untouched).read_text(encoding="utf-8")
    assert only_phase8_registration(untouched, text, text)
    assert not only_phase8_registration(untouched, text, text + "\n# edit\n")


def test_bl_phase6_runtime_knowledge_and_tests_are_frozen() -> None:
    namespaces = ("src/intelligence/themes", "src/intelligence/theme_intelligence", "knowledge")
    assert _git("diff", "--name-status", PHASE6_COMPLETION, "--", *namespaces) == ""
    phase6_tests = sorted(PHASE6_TEST_REGISTRATION)
    assert _git("diff", "--name-status", P8_A0, "--", *phase6_tests) == ""                     # Phase 6 の test を触らない


def test_bl_the_runtime_surface_since_a0_is_exactly_the_registered_phase8_runtime() -> None:
    changes = {tuple(line.split("\t")) for line in _git("diff", "--cached", "--name-status", P8_A0, "--",
                                                        *SURFACE).splitlines()}
    assert changes == {("A", path) for path in PHASE8_RUNTIME}
    pending = [line for line in _git("status", "--porcelain", "--", *(p for p in SURFACE if p != "data")).splitlines()
               if not is_phase8_addition(line[:2].strip(), line[3:])]
    assert pending == []
    docs = {tuple(line.split("\t")) for line in _git("diff", "--name-status", P8_A0, "--", "docs").splitlines()}
    assert docs <= {("A", A1_DOC)}


# ================================================================ BM〜BO registry ・未登録 ・外からの import


def test_bm_the_phase8_registry_is_exact() -> None:
    assert tuple(sorted(stem for stem, _ in _sources())) == MODULES
    assert PHASE8_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in MODULES)
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {f"{n}.py" for n in MODULES}
    assert ADDITION_STATUSES == ("A", "??")
    for path in (*PHASE8_TESTS, *PHASE8_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert A1_DOC in PHASE8_DOCS
    assert set(PHASE7_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                             "tests/intelligence/test_narrative_intelligence_boundary.py"}
    assert not any(p.startswith(("src/intelligence/themes", "src/intelligence/theme_intelligence",
                                 "src/intelligence/narrative_intelligence", "knowledge")) for p in PHASE8_RUNTIME)


def test_bn_an_unregistered_phase8_runtime_is_rejected_by_every_registry_check(tmp_path: Path) -> None:
    fake = f"{PHASE8_PACKAGE}/screen_engine.py"
    for status in ("A", "??"):
        assert not is_phase8_addition(status, fake) and not is_phase7_addition(status, fake)
    assert f":(exclude,literal){fake}" not in PHASE7_EXCLUDED_PATHSPECS
    for path in PHASE8_RUNTIME:
        assert is_phase8_addition("A", path) and is_phase7_addition("??", path)
        assert f":(exclude,literal){path}" in PHASE7_EXCLUDED_PATHSPECS
        for status in ("M", "D", "R", "R100", "C", "T", "U"):
            assert not is_phase8_addition(status, path) and not is_phase7_addition(status, path), status
    for near_miss in (PHASE8_PACKAGE, f"{PHASE8_PACKAGE}/", f"{PHASE8_PACKAGE}/sub/identity_model.py",
                      "src/intelligence/screening/identity_model.py", f"{PHASE8_PACKAGE}/identity_model.pyc"):
        assert not is_phase8_addition("A", near_miss) and not is_phase7_addition("A", near_miss), near_miss
    package = tmp_path / PHASE8_PACKAGE
    package.mkdir(parents=True)
    for _, path in _sources():
        (package / path.name).write_bytes(path.read_bytes())
    (package / "screen_engine.py").write_text('"""not registered."""\n', encoding="utf-8")
    unregistered = sorted(p.relative_to(tmp_path).as_posix() for p in package.glob("*.py")
                          if not is_phase8_addition("A", p.relative_to(tmp_path).as_posix()))
    assert unregistered == [fake]


def test_bo_no_other_package_imports_phase8() -> None:
    offenders = []
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")),
                 *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if not path.exists() or PACKAGE_DIR in path.parents:
            continue
        if "screener_intelligence" in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
    closure = runtime_closure()
    assert closure and not any("screener_intelligence" in module for module in closure)
