"""P6-A4a — themes package の import 境界（A0.5 §7）・production bundle からの排除・IO / 時計 / 乱数 / store 不在。"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
THEMES_DIR = REPO_ROOT / "src" / "intelligence" / "themes"
MODULES = ("__init__", "model", "fingerprint", "qualification", "revision", "store", "operations")
PURE_MODULES = ("__init__", "model", "fingerprint", "qualification", "revision")   # IO / 時計 / 乱数を持たない
IO_MODULES = ("store", "operations")                                                # 追記専用 JSONL のみ

ALLOWED_STDLIB = {"__future__", "json", "re", "unicodedata", "dataclasses", "datetime", "enum", "typing"}
ALLOWED_STDLIB_IO = ALLOWED_STDLIB | {"os", "pathlib"}
ALLOWED_RELATIVE = {"..core.ids", "..core.time", ".model", ".fingerprint", ".store"}
ALLOWED_CLOSURE = {
    "src.intelligence", "src.intelligence.core", "src.intelligence.core.ids", "src.intelligence.core.time",
    "src.intelligence.themes", "src.intelligence.themes.model", "src.intelligence.themes.fingerprint",
    "src.intelligence.themes.qualification", "src.intelligence.themes.revision", "src.intelligence.themes.store",
    "src.intelligence.themes.operations",
}
FORBIDDEN_MODULE_TOKENS = ("compass", "reports", "predictions", "internals", "context", "market", "ingestion",
                           "normalization", "databank", "sources", "facts", "evidence", "notifiers", "analysis",
                           "collectors", "legacy", "paths", "sqlite3", "requests", "urllib", "socket", "http",
                           "subprocess", "yaml", "random", "secrets")
FORBIDDEN_SOURCE_TOKENS = ("sqlite", "open(", "Path(", "requests.", "urllib", "socket.", ".now(", "utcnow", "time.time",
                           "random.", "secrets.", "os.path", "subprocess", "yaml.", "data/vnext", "INTELLIGENCE_DATA_ROOT",
                           "data_root", "jsonl", ".write(", "fsync", "class ThemeStore", "def resolve", "def append",
                           "latest_wins", "def merge", "PENDING")
#: store / operations にも許さない token（IO は許すが resolver / 時計 / 乱数 / network / SQLite / repository fallback は不可）
FORBIDDEN_IO_SOURCE_TOKENS = ("sqlite", "requests.", "urllib", "socket.", ".now(", "utcnow", "time.time", "random.",
                              "secrets.", "subprocess", "yaml.", "data/vnext", "INTELLIGENCE_DATA_ROOT", "core.paths",
                              "theme_learning", "def resolve", "latest_wins", "def merge", "state_at", "current_theme",
                              "latest_theme", "active_theme", "governance_state", "metadata_at", "mapping_at",
                              "truncate(", '"w"', "'w'", '"r+"', "os.replace", "os.rename", "os.remove", "unlink(")


def test_package_contains_only_authorized_modules() -> None:
    files = sorted(p.stem for p in THEMES_DIR.glob("*.py"))
    assert files == sorted(MODULES)
    assert not list(THEMES_DIR.glob("*.jsonl")) and not list(THEMES_DIR.glob("*.sqlite3"))


def test_theme_modules_import_only_core_ids_and_core_time() -> None:
    for name in MODULES:
        imports = imported_modules(THEMES_DIR / f"{name}.py")
        stdlib = {m for m in imports if not m.startswith(".")}
        relative = {m for m in imports if m.startswith(".")}
        allowed = ALLOWED_STDLIB_IO if name in IO_MODULES else ALLOWED_STDLIB
        assert stdlib <= allowed, (name, stdlib - allowed)
        assert relative <= ALLOWED_RELATIVE, (name, relative - ALLOWED_RELATIVE)
        for token in FORBIDDEN_MODULE_TOKENS:
            assert not any(re.search(rf"(^|\.){token}(\.|$)", m) for m in imports), (name, token)


def test_theme_runtime_closure_is_core_ids_time_and_themes_only() -> None:
    code = ("import sys\n"
            "import src.intelligence.themes.model, src.intelligence.themes.fingerprint\n"
            "import src.intelligence.themes.qualification, src.intelligence.themes.revision\n"
            "import src.intelligence.themes.store, src.intelligence.themes.operations\n"
            "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('src.'))))\n")
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                          env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    closure = set(proc.stdout.split())
    assert closure == ALLOWED_CLOSURE and len(closure) == 11


def test_themes_is_excluded_from_production_bundle_and_no_frozen_package_imports_it() -> None:
    assert "themes" in EXCLUDED_PACKAGES
    assert not any(".themes" in m for m in runtime_closure())
    offenders = []   # vNext（src/intelligence）の凍結 package は themes を import しない（legacy src.analysis の同名 module は対象外）
    for path in (REPO_ROOT / "src" / "intelligence").rglob("*.py"):
        if THEMES_DIR in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "themes" in node.module.split("."):
                offenders.append(str(path))
            if isinstance(node, ast.Import) and any("themes" in a.name.split(".") for a in node.names):
                offenders.append(str(path))
    assert offenders == []


def test_no_io_network_clock_random_store_or_resolver_in_theme_sources() -> None:
    for name in PURE_MODULES:
        source = executable_source(THEMES_DIR / f"{name}.py")
        for token in FORBIDDEN_SOURCE_TOKENS:
            assert token not in source, (name, token)
    for name in IO_MODULES:
        source = executable_source(THEMES_DIR / f"{name}.py")
        for token in FORBIDDEN_IO_SOURCE_TOKENS:
            assert token not in source, (name, token)
        # 唯一の open mode は追記（'a'）。読み取りは read_bytes / stat のみ（ast.unparse は文字列を単引用符で出す）
        if name == "store":
            assert "open('a'" in source
        for mode in ("open('w'", "open('wb'", "open('r+'", "open('a+'", "write_bytes(", "write_text("):
            assert mode not in source, (name, mode)


def test_root_id_generation_is_the_only_nondeterministic_primitive() -> None:
    source = executable_source(THEMES_DIR / "model.py")
    tree = ast.parse((THEMES_DIR / "model.py").read_text(encoding="utf-8"))
    callers = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and getattr(inner.func, "id", "") == "new_id":
                    callers.add(node.name)
    assert callers == {"new_root_id"}
    assert "new_root_id(" not in source.replace("def new_root_id(", "")
