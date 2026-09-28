"""Phase 8 Screener Intelligence の境界 ／ 凍結の guard（P8-A1 の matrix BA〜BO）。

- BA〜BG: import 境界（module ごとの許可一覧 ・runtime closure）。Phase 6 ／ 7 ・P5 ・legacy ・J-Quants の transport ・
  provider ／ network ・公開 ／ 通知 ／ 売買を import しない。時計 ・乱数 ・動的 code なし。filesystem は store だけ。
- BH〜BJ: screen ・基準 ・候補 ・順位 ・score ・Theme exposure の型 ／ 名前が無い。
- BK〜BO: Phase 7 ／ 6 の凍結、Phase 8 の registry の完全一致、未登録の Phase 8 runtime の検出、他の package からの import なし。
- P8-A2（BY〜CL）: A1 の runtime は `4162e9c` と byte 一致、観測の module は許可一覧どおり（A1 の store ／ resolver の API は
  指名した module が決まった名前だけを使う）、派生指標 ・screen ・順位 ・Theme の型 ／ 語彙が無い。
- P8-A2.5: A1 ／ A2 の runtime と A2 の契約は `b686b00` と byte 一致（監査の文書は registry に登録）。
- P8-V: runtime と A2.5 の監査の文書は `5713a56` と byte 一致（公式の仕様の確認の文書は registry に登録）。
- P8-VR: runtime と A2.5 ・P8-V の文書は `fc91ee1` と byte 一致（確認の是正の文書は registry に登録）。
- P8-A1R: 訂正 ・2 軸の解決の module は許可一覧どおり（A1 の名前は決まったものだけ。A2 を使わない）、A1 ／ A2 の runtime と
  先行の Phase 8 の文書は `7b8d375` と byte 一致。

registry: `tests/intelligence/phase8_runtime_registry.py`。契約: `docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md`。
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.intelligence.phase7_runtime_registry import (PHASE6_TEST_REGISTRATION, PHASE7_EXCLUDED_PATHSPECS,
                                                        PHASE7_RUNTIME, is_phase7_addition)
from tests.intelligence.phase8_runtime_registry import (ADDITION_STATUSES, P8_A0, P8_A1, P8_A1R, P8_A2, P8_A2_5, P8_V,
                                                        P8_LV1, P8_PILOT1, P8_A2R, P8_VR,
                                                        PHASE7_TEST_REGISTRATION, PHASE8_A1R_RUNTIME, PHASE8_A1_RUNTIME,
                                                        PHASE8_A2_RUNTIME,
                                                        PHASE8_DOCS, PHASE8_PACKAGE, PHASE8_RUNTIME, PHASE8_TESTS,
                                                        is_phase8_addition, only_phase8_registration)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
MODULES = ("__init__", "identity_correction_model", "identity_correction_store", "identity_model",
           "identity_remediation_resolver", "identity_resolver", "identity_store", "observation_model",
           "observation_resolver", "observation_store")
A1_MODULES = ("__init__", "identity_model", "identity_resolver", "identity_store")
A2_MODULES = ("observation_model", "observation_resolver", "observation_store")
A1R_MODULES = ("identity_correction_model", "identity_correction_store", "identity_remediation_resolver")
IO_MODULES = ("identity_store", "observation_store", "identity_correction_store")
PHASE7_FINAL = "c1e95d35026652fb27c637318593fa8688219cf7"
PHASE6_COMPLETION = "5ef313a6a9477f05b4e46756fb8b79c0f0c3d685"
A1_DOC = "docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md"
A2_DOC = "docs/databank/PHASE8_PIT_OBSERVATION_CONTRACT.md"
A2_5_DOC = "docs/databank/PHASE8_JQUANTS_REAL_DATA_MAPPING_AUDIT.md"
V_DOC = "docs/databank/PHASE8_JQUANTS_OFFICIAL_SPEC_VERIFICATION.md"
VR_DOC = "docs/databank/PHASE8_JQUANTS_VERIFICATION_REMEDIATION.md"
A1R_DOC = "docs/databank/PHASE8_IDENTITY_REMEDIATION_CONTRACT.md"
LV1_DOC = "docs/databank/PHASE8_JQUANTS_LIGHT_MINIMUM_FIELD_CONTRACT.md"
PILOT1_DOC = "docs/databank/PHASE8_JQUANTS_LIGHT_PILOT1_REPORT.md"
A2R_DOC = "docs/databank/PHASE8_A2R_JQUANTS_SEMANTIC_REMEDIATION.md"
A2RV_DOC = "docs/databank/PHASE8_A2R_OFFICIAL_SPEC_VERIFICATION.md"
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
    "observation_model": {"__future__", "json", "re", "dataclasses", "datetime", "decimal", "enum", "typing",
                          ".identity_model"} | _CORE,
    "observation_store": {"__future__", "os", "dataclasses", "enum", "pathlib", "typing", ".identity_store",
                          ".observation_model"},
    "observation_resolver": {"__future__", "dataclasses", "datetime", "enum", "typing", ".identity_model",
                             ".identity_resolver", ".observation_model", ".observation_store", "..core.time"},
    "identity_correction_model": {"__future__", "json", "re", "dataclasses", "datetime", "enum", "typing",
                                  ".identity_model"} | _CORE,
    "identity_correction_store": {"__future__", "os", "dataclasses", "enum", "pathlib", "typing",
                                  ".identity_correction_model", ".identity_store"},
    "identity_remediation_resolver": {"__future__", "dataclasses", "datetime", "enum", "typing",
                                      ".identity_correction_model", ".identity_correction_store", ".identity_model",
                                      ".identity_resolver", "..core.time"},
}
#: A2 が使ってよい A1 の名前（module → 名前。完全一致）。A1 の store ／ resolver の API は指名した module だけが使う
SANCTIONED_A1_IMPORTS = {
    "observation_model": {".identity_model": {"CREDENTIAL_MARKERS", "IdentityHistory", "SourceClass", "SubjectKind",
                                              "canonical_json", "is_issuer_id", "is_security_id"}},
    "observation_store": {".identity_store": {"IdentityAuthorityMissing", "IdentityStoreCorrupt",
                                              "open_identity_history"}},
    "observation_resolver": {".identity_resolver": {"IdentityQuery", "ResolutionStatus", "resolve"},
                             ".identity_model": {"SourceClass", "SubjectKind", "canonical_json", "is_issuer_id",
                                                 "is_security_id"}},
}
#: A1R が使ってよい A1 の名前（module → 名前。完全一致）。A1 の store は訂正の store だけ、A1 の resolver は 2 軸の resolver だけ
SANCTIONED_A1R_IMPORTS = {
    "identity_correction_model": {".identity_model": {"AUTHORITY_RULES_VERSION", "CREDENTIAL_MARKERS", "SCHEMA_VERSION",
                                                      "IdentityHistory", "IdentityHistoryError", "IdentityModelError",
                                                      "RecordKind", "SourceClass", "canonical_json",
                                                      "is_identity_record", "parse_identity_record"}},
    "identity_correction_store": {".identity_store": {"IDENTITY_DIRNAME", "IdentityAuthorityMissing",
                                                      "IdentityStoreCorrupt", "open_identity_history"}},
    "identity_remediation_resolver": {".identity_model": {"RecordKind", "canonical_json"},
                                      ".identity_resolver": {"DERIVED_NON_AUTHORITY_NON_PERSISTENT", "IdentityQuery",
                                                             "IdentityResolution", "QueryKind", "resolve"}},
}
ALLOWED_CLOSURE = {"src", "src.intelligence", "src.intelligence.core", "src.intelligence.core.ids",
                   "src.intelligence.core.time", "src.intelligence.screener_intelligence"}
EXPECTED_INTERNAL = {"__init__": set(), "identity_model": set(), "identity_store": {"identity_model"},
                     "identity_resolver": {"identity_model", "identity_store"},
                     "observation_model": {"identity_model"},
                     "observation_store": {"identity_model", "identity_store", "observation_model"},
                     "observation_resolver": {"identity_model", "identity_store", "identity_resolver",
                                              "observation_model", "observation_store"},
                     "identity_correction_model": {"identity_model"},
                     "identity_correction_store": {"identity_model", "identity_store", "identity_correction_model"},
                     "identity_remediation_resolver": {"identity_model", "identity_store", "identity_resolver",
                                                       "identity_correction_model", "identity_correction_store"}}


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
            if name not in IO_MODULES:
                assert node.id not in IO_NAMES, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in FORBIDDEN_ATTRIBUTES, (name, node.attr)
            if name not in IO_MODULES:
                assert node.attr not in IO_ATTRIBUTES, (name, node.attr)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise AssertionError((name, "module state"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "://" not in node.value and "C:\\" not in node.value, (name, node.value)


@pytest.mark.parametrize("store,expected", [
    ("identity_store", {"__init__": {"ab", "mkdir"}, "append": {"ab", "write", "fsync"}}),
    ("observation_store", {"__init__": {"ab"}, "append": {"ab", "write", "fsync"}}),
    ("identity_correction_store", {"__init__": {"ab"}, "append": {"ab", "write", "fsync"}})])
def test_ba_to_bg_the_store_writes_only_through_append_and_initialize(store: str, expected: dict) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{store}.py").read_text(encoding="utf-8"))
    writers = {}
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(func):
            if isinstance(node, ast.Constant) and node.value in ("ab", "wb", "w", "a", "r+", "w+", "a+"):
                writers.setdefault(func.name, set()).add(node.value)
            if isinstance(node, ast.Attribute) and node.attr in ("write", "mkdir", "fsync", "write_bytes", "unlink"):
                writers.setdefault(func.name, set()).add(node.attr)
    assert writers == expected
    assert "sqlite" not in executable_source(PACKAGE_DIR / f"{store}.py").lower()


# ================================================================ BH〜BJ screen ・score ・Theme なし


SCREENING_WORDS = ("screen", "criterion", "criteria", "candidate_result", "rank", "score", "rating", "filter",
                   "recommend", "attractive", "target_price", "expected_return", "weight", "buy", "sell", "watchlist",
                   "portfolio", "thesis", "theme", "exposure", "beneficiar", "narrative", "forecast", "price", "fundamental")


@pytest.mark.parametrize("name,path", [(n, p) for n, p in _sources() if n in A1_MODULES + A1R_MODULES])
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
    assert docs <= {("A", A1_DOC), ("A", A2_DOC), ("A", A2_5_DOC), ("A", V_DOC), ("A", VR_DOC), ("A", A1R_DOC),
                    ("A", LV1_DOC), ("A", PILOT1_DOC),
                    ("A", A2R_DOC), ("A", A2RV_DOC)}


# ================================================================ BM〜BO registry ・未登録 ・外からの import


def test_bm_the_phase8_registry_is_exact() -> None:
    assert tuple(sorted(stem for stem, _ in _sources())) == MODULES
    assert PHASE8_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in MODULES)
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {f"{n}.py" for n in MODULES}
    assert ADDITION_STATUSES == ("A", "??")
    for path in (*PHASE8_TESTS, *PHASE8_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert {A1_DOC, A2_DOC, A2_5_DOC, V_DOC, VR_DOC, A1R_DOC, LV1_DOC, PILOT1_DOC, A2R_DOC,
            A2RV_DOC} <= set(PHASE8_DOCS)
    assert PHASE8_A1R_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in A1R_MODULES)
    assert set(PHASE8_RUNTIME) == set(PHASE8_A2_RUNTIME) | set(PHASE8_A1R_RUNTIME)
    assert PHASE8_A1_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in A1_MODULES)
    assert PHASE8_A2_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in sorted((*A1_MODULES, *A2_MODULES)))
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


# ================================================================ P8-A2（BY〜CL）


def test_a2_by_the_a1_runtime_is_byte_identical_to_the_a1_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A1, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in PHASE8_A1_RUNTIME:
        assert _git("show", f"{P8_A1}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A1, "--", *PHASE8_A1_RUNTIME, A1_DOC) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A1_RUNTIME) == ""


def _from_imports(path: Path) -> dict:
    found: dict = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level:
            found.setdefault("." * node.level + node.module, set()).update(alias.name for alias in node.names)
    return found


@pytest.mark.parametrize("name", A2_MODULES)
def test_a2_cc_to_ch_only_the_designated_modules_use_exactly_the_sanctioned_a1_names(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    a1_imports = {module: names for module, names in imports.items() if module.startswith(".identity_")}
    assert a1_imports == SANCTIONED_A1_IMPORTS[name]
    for module in A1_MODULES:                                                         # A1 は A2 を知らない
        if module != "__init__":
            assert not any(m.startswith(".observation_") for m in _from_imports(PACKAGE_DIR / f"{module}.py"))


DERIVED_TOKENS = {"roe", "roa", "pbr", "yield", "dividend", "volatility", "return", "returns", "growth", "margin",
                  "ttm", "trailing", "annualized", "ratio", "average", "moving", "indicator", "split", "screen",
                  "criterion", "criteria", "candidate", "rank", "score", "rating", "recommend", "recommendation",
                  "buy", "sell", "theme", "exposure", "narrative", "watchlist", "portfolio", "latest", "current", "now",
                  "llm", "prompt"}


def _words(identifier: str) -> set:
    """識別子を語に分ける（snake_case と CamelCase）。部分一致ではなく語で調べる。"""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    return {word for word in spaced.lower().split("_") if word}


DERIVED_MEMBERS = {"PER", "PBR", "ROE", "ROA", "MARKET_CAP", "TTM", "ANNUALIZED", "GROWTH", "MARGIN", "RETURN",
                   "VOLATILITY", "YIELD", "DIVIDEND", "SCORE", "RANK", "BUY", "SELL", "LATEST", "CURRENT"}


@pytest.mark.parametrize("name", A2_MODULES)
def test_a2_ci_to_cl_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS
    for clock in ("15:30", "06:30", "15:00", "09:00"):                              # 既定の公表時刻を持たない
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_a2_ci_to_cl_the_observation_vocabulary_has_no_derived_or_evaluative_member() -> None:
    from src.intelligence.screener_intelligence import observation_model as om
    from src.intelligence.screener_intelligence import observation_resolver as orr
    members = {member.value for enum in (om.ObservationClass, om.RecordKind, om.MarketField, om.FundamentalField,
                                         om.PriceBasis, om.StatementBasis, om.PeriodBasis, om.KnowledgePrecision,
                                         om.ValueState, om.Measure, om.Currency, om.Scale, om.CoverageDataset,
                                         orr.ObservationStatus) for member in enum}
    assert not members & DERIVED_MEMBERS
    for word in ("TTM", "TRAILING", "ANNUAL", "ADJUSTMENT_FACTOR", "RATIO", "SCORE", "RANK"):
        assert not any(word in value for value in members), word
    assert set(om.PeriodBasis) == {om.PeriodBasis.FISCAL_YEAR, om.PeriodBasis.SINGLE_QUARTER,
                                   om.PeriodBasis.CUMULATIVE_YEAR_TO_DATE}
    fields = set(orr.ObservationResolution.__dataclass_fields__)
    assert not fields & {"score", "rank", "weight", "recommendation", "record_id", "metric"}


# ================================================================ P8-A2.5（A2 の凍結）


def test_a2_5_the_a1_a2_runtime_and_the_a2_contract_are_byte_identical_to_the_a2_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A2, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in (*PHASE8_A2_RUNTIME, A2_DOC):
        assert _git("show", f"{P8_A2}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A2, "--", *PHASE8_A2_RUNTIME, A1_DOC, A2_DOC) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A2_RUNTIME, A1_DOC, A2_DOC) == ""


# ================================================================ P8-V（A2.5 の凍結）


def test_v_the_runtime_and_the_a2_5_audit_are_byte_identical_to_the_a2_5_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A2_5, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in (*PHASE8_A2_RUNTIME, A2_5_DOC):
        assert _git("show", f"{P8_A2_5}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A2_5, "--", *PHASE8_A2_RUNTIME, A1_DOC, A2_DOC, A2_5_DOC) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A2_RUNTIME, A2_5_DOC) == ""


# ================================================================ P8-VR（P8-V の凍結）


def test_vr_the_runtime_and_the_a2_5_and_v_records_are_byte_identical_to_the_v_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_V, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in (*PHASE8_A2_RUNTIME, A2_5_DOC, V_DOC):
        assert _git("show", f"{P8_V}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_V, "--", *PHASE8_A2_RUNTIME, A1_DOC, A2_DOC, A2_5_DOC, V_DOC) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A2_RUNTIME, A2_5_DOC, V_DOC) == ""


# ================================================================ P8-A1R（訂正 ・2 軸の解決の境界 ／ 凍結）


def test_a1r_az_bs_a1_a2_runtime_and_prior_phase8_documents_are_byte_identical_to_the_vr_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_VR, "HEAD"], cwd=REPO_ROOT).returncode == 0
    prior_docs = (A1_DOC, A2_DOC, A2_5_DOC, V_DOC, VR_DOC)
    for path in (*PHASE8_A2_RUNTIME, *prior_docs):
        assert _git("show", f"{P8_VR}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_VR, "--", *PHASE8_A2_RUNTIME, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A2_RUNTIME, *prior_docs) == ""


@pytest.mark.parametrize("name", A1R_MODULES)
def test_a1r_the_remediation_modules_use_exactly_the_sanctioned_a1_names_and_never_a2(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    a1_imports = {module: names for module, names in imports.items()
                  if module in (".identity_model", ".identity_store", ".identity_resolver")}
    assert a1_imports == SANCTIONED_A1R_IMPORTS[name]
    assert not any(module.startswith(".observation_") for module in imports)             # A2 を使わない
    for module in (*A1_MODULES, *A2_MODULES):                                             # A1 ／ A2 は A1R を知らない
        if module != "__init__":
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m in (".identity_correction_model", ".identity_correction_store",
                                 ".identity_remediation_resolver") for m in used), module


@pytest.mark.parametrize("name", A1R_MODULES)
def test_a1r_bk_bl_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS


def test_a1r_the_remediation_vocabulary_has_no_evaluative_merge_or_split_member() -> None:
    from src.intelligence.screener_intelligence import identity_correction_model as cm
    from src.intelligence.screener_intelligence import identity_remediation_resolver as rr
    members = {member.value for enum in (cm.CorrectionAction, cm.CorrectionReason, cm.ReviewerClass,
                                         rr.ResolutionMode, rr.RemediationStatus) for member in enum}
    for word in ("RANK", "SCORE", "BUY", "SELL", "TOP", "BEST", "CANDIDATE", "THEME", "EXPOSURE", "LATEST", "MERGE",
                 "SPLIT", "SPIN"):
        assert not any(word in value for value in members), word
    assert set(cm.CorrectionAction) == {cm.CorrectionAction.INVALIDATE_RECORD, cm.CorrectionAction.SUPERSEDE_RECORD}
    assert set(rr.ResolutionMode) == {rr.ResolutionMode.STRICT_KNOWLEDGE, rr.ResolutionMode.RETROSPECTIVE_AUTHORITY}


# ================================================================ P8-LV1（A1R の凍結）


def test_lv1_the_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_a1r_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A1R, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py"))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (LV1_DOC, PILOT1_DOC, A2R_DOC, A2RV_DOC))
    assert len(frozen_tests) == 3 and len(prior_docs) == 7
    for path in (*PHASE8_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A1R}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A1R, "--", *PHASE8_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_RUNTIME, *frozen_tests, *prior_docs) == ""


# ================================================================ P8-PILOT1（LV1 の凍結）


def test_pilot1_the_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_lv1_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_LV1, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py"))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (PILOT1_DOC, A2R_DOC, A2RV_DOC))
    assert len(frozen_tests) == 3 and len(prior_docs) == 8 and LV1_DOC in prior_docs
    for path in (*PHASE8_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_LV1}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_LV1, "--", *PHASE8_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_RUNTIME, *frozen_tests, *prior_docs) == ""


# ================================================================ P8-A2R（PILOT1 の凍結）


def test_a2r_the_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_pilot1_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_PILOT1, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py"))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (A2R_DOC, A2RV_DOC))
    assert len(frozen_tests) == 3 and len(prior_docs) == 9 and PILOT1_DOC in prior_docs
    for path in (*PHASE8_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_PILOT1}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_PILOT1, "--", *PHASE8_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_RUNTIME, *frozen_tests, *prior_docs) == ""


# ================================================================ P8-A2R の再実行（A2R の凍結）


def test_a2rv_the_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_a2r_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A2R, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py"))
    prior_docs = tuple(path for path in PHASE8_DOCS if path != A2RV_DOC)
    assert len(frozen_tests) == 3 and len(prior_docs) == 10 and {PILOT1_DOC, A2R_DOC} <= set(prior_docs)
    for path in (*PHASE8_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A2R}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A2R, "--", *PHASE8_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_RUNTIME, *frozen_tests, *prior_docs) == ""
