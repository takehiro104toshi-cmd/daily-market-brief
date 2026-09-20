"""P6-B1 — theme_intelligence package の import 境界・production bundle からの排除・Foundation からの非参照・
IO / 時計 / 乱数 / store / lifecycle 語彙の不在（test matrix 40〜44）。"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_import_boundary import ALLOWED_CLOSURE as THEMES_CLOSURE

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
THEMES_DIR = REPO_ROOT / "src" / "intelligence" / "themes"
MODULES = ("__init__", "model", "change", "lifecycle_model", "lifecycle", "proposal_model", "proposal_store",
           "proposal_resolution", "dedup", "proposal_bridge",
           # P6-B4B: versioned knowledge（taxonomy / entity catalog）。YAML は knowledge_loader だけが読む
           "knowledge_loader", "taxonomy_model", "taxonomy", "entity_model", "entity_catalog")
IO_MODULES = ("proposal_store",)                                         # 追記専用 JSONL のみ（P6-B3）
IDENTITY_MODULES = ("proposal_model",)                                   # content id（thprop_ / thdec_）を計算する唯一の module
KNOWLEDGE_YAML_MODULES = ("knowledge_loader",)                           # P6-B4B: read-only YAML loader（書き込みなし）
KNOWLEDGE_PATH_MODULES = ("taxonomy", "entity_catalog")                  # P6-B4B: pathlib.Path を型として受けるだけ
ALLOWED_STDLIB = {"__future__", "dataclasses", "datetime", "enum", "typing", "json", "re"}
ALLOWED_STDLIB_IO = ALLOWED_STDLIB | {"os", "pathlib"}
ALLOWED_STDLIB_KNOWLEDGE_PATH = ALLOWED_STDLIB | {"pathlib"}
ALLOWED_STDLIB_KNOWLEDGE_YAML = ALLOWED_STDLIB | {"pathlib", "hashlib", "unicodedata", "yaml"}
ALLOWED_RELATIVE = {"..core.ids", "..core.time", "..themes.model", "..themes.fingerprint", "..themes.qualification",
                    "..themes.resolver", ".model", ".lifecycle_model", ".proposal_model", ".proposal_resolution",
                    ".knowledge_loader", ".taxonomy_model", ".entity_model"}
#: resolver が store を import するため closure に store は含まれる（read-only API の到達性）。operations / revision は含まれない
ALLOWED_CLOSURE = (THEMES_CLOSURE - {"src.intelligence.themes.operations", "src.intelligence.themes.revision"}) | {
    "src.intelligence.theme_intelligence", "src.intelligence.theme_intelligence.model",
    "src.intelligence.theme_intelligence.change", "src.intelligence.theme_intelligence.lifecycle_model",
    "src.intelligence.theme_intelligence.lifecycle", "src.intelligence.theme_intelligence.proposal_model",
    "src.intelligence.theme_intelligence.proposal_store", "src.intelligence.theme_intelligence.proposal_resolution",
    "src.intelligence.theme_intelligence.dedup", "src.intelligence.theme_intelligence.proposal_bridge",
    "src.intelligence.theme_intelligence.knowledge_loader", "src.intelligence.theme_intelligence.taxonomy_model",
    "src.intelligence.theme_intelligence.taxonomy", "src.intelligence.theme_intelligence.entity_model",
    "src.intelligence.theme_intelligence.entity_catalog"}
FORBIDDEN_MODULE_TOKENS = ("compass", "reports", "predictions", "internals", "context", "market", "ingestion",
                           "normalization", "databank", "sources", "facts", "evidence", "notifiers", "analysis",
                           "collectors", "legacy", "paths", "sqlite3", "requests", "urllib", "socket", "http",
                           "subprocess", "yaml", "random", "secrets", "store", "operations", "revision")
FORBIDDEN_SOURCE_TOKENS = ("sqlite", "open(", "Path(", "read_bytes(", "read_text(", "requests.", "urllib", "socket.",
                           ".now(", "utcnow", "time.time", "random.", "secrets.", "os.path", "subprocess", "yaml.",
                           "data/vnext", "INTELLIGENCE_DATA_ROOT", "data_root", "jsonl", ".write(", "fsync",
                           "ThemeStore", "append_", "reload(", "initialize(", "content_id(", "new_root_id",
                           "latest_wins", "def latest", "def current", "def active", "def state_at", "float(",
                           # P6-B2（L-5）: P5 / 較正 / 価格 / production authority を lifecycle 入力にしない
                           "calibration", "prediction", "MarketSignal", "MorningBrief", "CompassDraft", "price",
                           "momentum", "market_return", "formal_review")
LIFECYCLE_TOKENS = ("EMERGING", "ACCELERATING", "MATURE", "WEAKENING", "STRONG", "WEAK", "BULLISH", "BEARISH",
                    "WINNING", "LOSING", "DORMANT", "ESTABLISHED", "PROMOTED", "DEMOTED", "score", "rank", "weight",
                    "confidence", "BUY", "SELL", "target_price", "HOT", "COLD", "CONVICTION", "tier")


def test_package_contains_only_authorized_modules() -> None:
    files = sorted(p.stem for p in PACKAGE_DIR.glob("*.py"))
    assert files == sorted(MODULES)
    assert not list(PACKAGE_DIR.glob("*.jsonl")) and not list(PACKAGE_DIR.glob("*.sqlite3"))


def test_modules_import_only_the_pure_read_only_foundation_surface() -> None:
    for name in MODULES:
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        stdlib = {m for m in imports if not m.startswith(".")}
        relative = {m for m in imports if m.startswith(".")}
        allowed = (ALLOWED_STDLIB_IO if name in IO_MODULES else ALLOWED_STDLIB_KNOWLEDGE_YAML if name in KNOWLEDGE_YAML_MODULES
                   else ALLOWED_STDLIB_KNOWLEDGE_PATH if name in KNOWLEDGE_PATH_MODULES else ALLOWED_STDLIB)
        assert stdlib <= allowed, (name, stdlib - allowed)
        assert relative <= ALLOWED_RELATIVE, (name, relative - ALLOWED_RELATIVE)
        for token in FORBIDDEN_MODULE_TOKENS:
            if token == "yaml" and name in KNOWLEDGE_YAML_MODULES:                    # P6-B4B: YAML は loader module だけ
                continue
            assert not any(re.search(rf"(^|\.){token}(\.|$)", m) for m in imports), (name, token)


def test_runtime_closure_is_foundation_read_surface_and_this_package_only() -> None:
    code = ("import sys\n"
            "import src.intelligence.theme_intelligence.model, src.intelligence.theme_intelligence.change\n"
            "import src.intelligence.theme_intelligence.lifecycle_model, src.intelligence.theme_intelligence.lifecycle\n"
            "import src.intelligence.theme_intelligence.proposal_model, src.intelligence.theme_intelligence.proposal_store\n"
            "import src.intelligence.theme_intelligence.proposal_resolution, src.intelligence.theme_intelligence.dedup\n"
            "import src.intelligence.theme_intelligence.proposal_bridge\n"
            "import src.intelligence.theme_intelligence.knowledge_loader, src.intelligence.theme_intelligence.taxonomy_model\n"
            "import src.intelligence.theme_intelligence.taxonomy, src.intelligence.theme_intelligence.entity_model\n"
            "import src.intelligence.theme_intelligence.entity_catalog\n"
            "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('src.'))))\n")
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                          env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    closure = set(proc.stdout.split())
    assert closure <= ALLOWED_CLOSURE, closure - ALLOWED_CLOSURE
    assert {"src.intelligence.theme_intelligence.change", "src.intelligence.theme_intelligence.lifecycle",
            "src.intelligence.theme_intelligence.dedup", "src.intelligence.theme_intelligence.proposal_bridge"} <= closure
    assert not any(token in m for m in closure for token in ("compass", "reports", "predictions", "internals", "context"))


def test_foundation_and_frozen_packages_never_import_theme_intelligence() -> None:
    offenders = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        if PACKAGE_DIR in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "theme_intelligence" in node.module.split("."):
                offenders.append(str(path))
            if isinstance(node, ast.Import) and any("theme_intelligence" in a.name.split(".") for a in node.names):
                offenders.append(str(path))
    assert offenders == []
    for path in THEMES_DIR.glob("*.py"):
        assert "theme_intelligence" not in path.read_text(encoding="utf-8")


def test_excluded_from_production_bundle_closure() -> None:
    closure = runtime_closure()
    assert closure, "runtime closure could not be computed"
    assert not any("theme_intelligence" in m for m in closure)
    assert not any(".themes" in m or "/themes/" in m for m in closure)          # P4 bundle は Foundation も含まない
    assert "themes" in EXCLUDED_PACKAGES


IO_ALLOWED_TOKENS = ("open(", "Path(", "read_bytes(", ".write(", "fsync", "data_root", "jsonl", "append_", "reload(",
                     "initialize(")   # proposal_store のみ（追記専用 store の API）
KNOWLEDGE_READ_ALLOWED_TOKENS = ("read_text(", "yaml.")   # knowledge_loader のみ（読み取り専用。書き込み token は一切許さない）
FORBIDDEN_IO_SOURCE_TOKENS = ("sqlite", "requests.", "urllib", "socket.", ".now(", "utcnow", "time.time", "random.", "secrets.",
                              "subprocess", "yaml.", "core.paths", "ThemeStore", "execute_", "truncate(", '"w"', "'w'", '"r+"',
                              "os.replace", "os.rename", "os.remove", "unlink(", "themes/")


def test_no_io_clock_random_network_store_or_score_in_sources() -> None:
    for name in MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        forbidden = (tuple(t for t in FORBIDDEN_SOURCE_TOKENS if t not in IO_ALLOWED_TOKENS) + FORBIDDEN_IO_SOURCE_TOKENS
                     if name in IO_MODULES else FORBIDDEN_SOURCE_TOKENS)
        if name in KNOWLEDGE_YAML_MODULES:                                              # P6-B4B: 読み取りのみ許可
            forbidden = tuple(t for t in FORBIDDEN_SOURCE_TOKENS + FORBIDDEN_IO_SOURCE_TOKENS
                              if t not in KNOWLEDGE_READ_ALLOWED_TOKENS)
        if name in IDENTITY_MODULES:                                                    # proposal / decision の content id を計算する module
            forbidden = tuple(t for t in forbidden if t != "content_id(")
        for token in forbidden:
            assert token not in source, (name, token)
        for token in LIFECYCLE_TOKENS:
            assert token not in source, (name, token)
    store_source = executable_source(PACKAGE_DIR / "proposal_store.py")
    assert "open('ab'" in store_source and "fsync" in store_source                      # 唯一の書き込み経路は追記のみ


def test_proposal_modules_never_execute_foundation_operations_or_append_to_foundation() -> None:
    """P6-B3 §15 / §22: bridge / dedup / store は Foundation に書かない・operations を実行しない・root id を生成しない。"""
    for name in ("proposal_model", "proposal_store", "proposal_resolution", "dedup", "proposal_bridge"):
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("execute_candidate", "execute_declaration", "plan_candidate", "plan_merge", "append_root",
                      "append_observation", "append_governance", "append_metadata", "append_mapping", "new_root_id", "new_id(",
                      "new_ulid", "ThemeStore", "embedding", "cosine", "similarity", "nearest", "top_n", "rank"):
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any(m.endswith("themes.store") or m.endswith("themes.operations") for m in imports), (name, imports)


def test_change_module_does_not_reimplement_store_or_resolver_semantics() -> None:
    source = executable_source(PACKAGE_DIR / "change.py")
    assert "def resolve(" not in source and "def _resolve(" not in source and "class ThemeHistory" not in source
    assert "source_origin_groups" not in source and "independent_origin_count" not in source   # diversity は DerivedView を比較
    assert "resolve(" in source and "compare_resolutions" in source


def test_lifecycle_module_uses_foundation_results_without_recounting() -> None:
    """P6-B2 §7: independent origin / counted attachment / qualification / flag は Foundation の結果を参照する。"""
    source = executable_source(PACKAGE_DIR / "lifecycle.py")
    for token in ("source_origin_groups", "independent_origin_count(", "evaluate_qualification(", "counted_attachments(",
                  "has_source_diversity", "has_temporal_diversity", "compare_resolutions", "ThemeChangeSet"):
        assert token not in source, token
    assert "derived.qualification" in source and "has_contradicting_evidence" in source
