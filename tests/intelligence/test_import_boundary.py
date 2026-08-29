"""Import境界の静的検査（QUALITY GATE: vNext skeleton独立）。

- vNext（src/intelligence）→ Legacy（src.analysis / src.report / src.collectors /
  src.data / src.date / notifiers / main / scripts）への import 禁止
- vNext core → ベンダーLLM SDK（anthropic / openai 等）への import 禁止（provider中立）
- Legacy → vNext への import が（Stage 1時点で）存在しないことの確認
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VNEXT_DIR = REPO_ROOT / "src" / "intelligence"

LEGACY_FORBIDDEN_PREFIXES = (
    "src.analysis", "src.report", "src.collectors", "src.data", "src.date",
    "notifiers", "main", "scripts",
)
VENDOR_SDK_PREFIXES = ("anthropic", "openai", "google.generativeai", "mistralai", "cohere")


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # 相対import: パッケージ内なので resolve してチェック対象に含める
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                module = node.module or ""
                rel = base.relative_to(REPO_ROOT)
                names.append(".".join(filter(None, [str(rel).replace("/", "."), module])))
            else:
                names.append(node.module or "")
    return names


def vnext_py_files() -> list[Path]:
    files = sorted(p for p in VNEXT_DIR.rglob("*.py") if "__pycache__" not in p.parts)
    assert files, "src/intelligence/ にPythonファイルが存在すること"
    return files


def test_vnext_does_not_import_legacy() -> None:
    violations = []
    for path in vnext_py_files():
        for name in _imports_of(path):
            if any(name == p or name.startswith(p + ".") for p in LEGACY_FORBIDDEN_PREFIXES):
                violations.append(f"{path.relative_to(REPO_ROOT)} imports {name}")
    assert not violations, "vNext→Legacyのimportは禁止:\n" + "\n".join(violations)


def test_vnext_core_is_llm_vendor_neutral() -> None:
    violations = []
    for path in (VNEXT_DIR / "core").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for name in _imports_of(path):
            if any(name == p or name.startswith(p + ".") for p in VENDOR_SDK_PREFIXES):
                violations.append(f"{path.relative_to(REPO_ROOT)} imports {name}")
    assert not violations, "core層はLLMベンダーSDKに依存しない:\n" + "\n".join(violations)


def test_legacy_does_not_import_vnext_yet() -> None:
    """Stage 1時点の状態確認。Stage 3以降は承認済みadapterのみ例外として許可される。"""
    legacy_roots = [
        REPO_ROOT / "main.py",
        REPO_ROOT / "src" / "analysis",
        REPO_ROOT / "src" / "report",
        REPO_ROOT / "src" / "collectors",
        REPO_ROOT / "src" / "data",
        REPO_ROOT / "notifiers",
    ]
    violations = []
    for root in legacy_roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            if "__pycache__" in path.parts:
                continue
            for name in _imports_of(path):
                if name.startswith("src.intelligence") or name == "intelligence":
                    violations.append(f"{path.relative_to(REPO_ROOT)} imports {name}")
    assert not violations, "Legacy→vNextのimportはStage 1では存在しないはず:\n" + "\n".join(violations)


def test_vnext_packages_have_boundary_docstrings() -> None:
    """各パッケージが purpose/boundary を説明するdocstringを持つこと（意味のあるSkeleton）。"""
    for init in sorted(VNEXT_DIR.glob("*/__init__.py")):
        tree = ast.parse(init.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree) or ""
        assert len(doc) >= 40, f"{init.relative_to(REPO_ROOT)}: 責務を説明するdocstringが必要"
