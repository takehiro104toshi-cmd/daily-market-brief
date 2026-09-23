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
           "knowledge_loader", "taxonomy_model", "taxonomy", "entity_model", "entity_catalog",
           # P6-B4C: deterministic discovery（ruleset knowledge / adapter / predicates / discover）。純関数。store を持たない
           "discovery_model", "discovery_predicates", "discovery_rules", "discovery_adapter", "discovery",
           # P6-B4E: 受理済み evidence 候補 → Foundation attachment plan（純。store を読まず書かない）
           "evidence_bridge_model", "evidence_bridge",
           # P6-B5B: Theme relation authority（assertion / governance の追記専用 store と PIT resolver、記述的 view）
           "relation_model", "relation_resolution", "relation_graph", "relation_store",
           # P6-B5C: relation 候補と人間の決定（提案 authority と、受理 → assertion plan の計画境界）
           "relation_proposal_model", "relation_proposal_resolution", "relation_proposal_bridge",
           "relation_proposal_store",
           # P6-B6B: monitoring の不変 record model と語彙（純。engine / ruleset / store を持たない）
           "monitoring_model",
           # P6-B6C: 決定論的 monitoring engine（純・I/O なし）と versioned ruleset の loader
           "monitoring_rules", "monitoring_engine",
           # P6-B6D: 人間の review 状態だけの追記専用 store / 上流 → snapshot の写像 / read-only な run orchestration
           "monitoring_store", "monitoring_adapter", "monitoring_runner")
#: P6-B6: B5 の read-only な解決結果を読む層（package 内の逆方向依存ではない）
MONITORING_MODULES = ("monitoring_model", "monitoring_rules", "monitoring_engine", "monitoring_store",
                      "monitoring_adapter", "monitoring_runner")
IO_MODULES = ("proposal_store", "relation_store", "relation_proposal_store",
              "monitoring_store", "monitoring_runner")   # 追記専用 JSONL と read-only な読み取りのみ
IDENTITY_MODULES = ("proposal_model", "relation_model", "relation_proposal_model",
                    "monitoring_model", "monitoring_adapter")            # content id を計算する module
KNOWLEDGE_YAML_MODULES = ("knowledge_loader",)                           # P6-B4B: read-only YAML loader（書き込みなし）
KNOWLEDGE_PATH_MODULES = ("taxonomy", "entity_catalog", "discovery_rules", "monitoring_rules")   # P6-B4B / B4C: pathlib.Path を型として受けるだけ
INPUT_MODEL_MODULES = ("discovery_adapter",)                             # P6-B4C: 許可された入力 model module（model のみ）を import する唯一の module
INPUT_MODEL_TOKENS = ("facts", "market", "sources", "databank")
LIFECYCLE_TOKEN_EXEMPTIONS = {"discovery_adapter": ("tier",)}            # SourceDocument.source_tier（上流の source 格）は lifecycle 語彙ではない
ALLOWED_STDLIB = {"__future__", "dataclasses", "datetime", "enum", "typing", "json", "re"}
ALLOWED_STDLIB_IO = ALLOWED_STDLIB | {"os", "pathlib"}
ALLOWED_STDLIB_KNOWLEDGE_PATH = ALLOWED_STDLIB | {"pathlib"}
ALLOWED_STDLIB_KNOWLEDGE_YAML = ALLOWED_STDLIB | {"pathlib", "hashlib", "unicodedata", "yaml"}
ALLOWED_RELATIVE = {"..core.ids", "..core.time", "..themes.model", "..themes.fingerprint", "..themes.qualification",
                    "..themes.resolver", ".model", ".lifecycle_model", ".proposal_model", ".proposal_resolution",
                    ".knowledge_loader", ".taxonomy_model", ".entity_model",
                    # P6-B6
                    ".monitoring_model", ".monitoring_rules", ".monitoring_engine", ".monitoring_store",
                    ".monitoring_adapter", ".lifecycle", ".proposal_store", ".relation_store",
                    ".relation_proposal_store",
                    # P6-B4C
                    ".discovery_model", ".discovery_predicates", ".discovery_rules", ".discovery_adapter", ".entity_catalog", ".taxonomy",
                    ".dedup", "..core.types", "..facts.model", "..market.model", "..sources.model", "..databank.news_model",
                    # P6-B4E
                    ".evidence_bridge_model",
                    # P6-B5B / P6-B5C
                    ".relation_model", ".relation_resolution", ".relation_proposal_model",
                    ".relation_proposal_resolution"}
#: resolver が store を import するため closure に store は含まれる（read-only API の到達性）。operations / revision は含まれない
ALLOWED_CLOSURE = (THEMES_CLOSURE - {"src.intelligence.themes.operations", "src.intelligence.themes.revision"}) | {
    "src.intelligence.theme_intelligence", "src.intelligence.theme_intelligence.model",
    "src.intelligence.theme_intelligence.change", "src.intelligence.theme_intelligence.lifecycle_model",
    "src.intelligence.theme_intelligence.lifecycle", "src.intelligence.theme_intelligence.proposal_model",
    "src.intelligence.theme_intelligence.proposal_store", "src.intelligence.theme_intelligence.proposal_resolution",
    "src.intelligence.theme_intelligence.dedup", "src.intelligence.theme_intelligence.proposal_bridge",
    "src.intelligence.theme_intelligence.knowledge_loader", "src.intelligence.theme_intelligence.taxonomy_model",
    "src.intelligence.theme_intelligence.taxonomy", "src.intelligence.theme_intelligence.entity_model",
    "src.intelligence.theme_intelligence.entity_catalog",
    # P6-B4C: discovery module と、許可された入力 model module（model のみ。store / provider / ingestion は含まれない）
    "src.intelligence.theme_intelligence.discovery_model", "src.intelligence.theme_intelligence.discovery_predicates",
    "src.intelligence.theme_intelligence.discovery_rules", "src.intelligence.theme_intelligence.discovery_adapter",
    "src.intelligence.theme_intelligence.discovery", "src.intelligence.core.types",
    "src.intelligence.facts", "src.intelligence.facts.model", "src.intelligence.market", "src.intelligence.market.model",
    "src.intelligence.sources", "src.intelligence.sources.model", "src.intelligence.databank", "src.intelligence.databank.news_model",
    # P6-B4E: attachment plan の model と bridge（Foundation の read-only resolution 型だけを参照する）
    "src.intelligence.theme_intelligence.evidence_bridge_model", "src.intelligence.theme_intelligence.evidence_bridge",
    # P6-B5B: relation authority（Foundation の store / resolver を一切引き込まない）
    "src.intelligence.theme_intelligence.relation_model", "src.intelligence.theme_intelligence.relation_resolution",
    "src.intelligence.theme_intelligence.relation_graph", "src.intelligence.theme_intelligence.relation_store",
    # P6-B5C: 提案 authority と計画境界（B5B の append API を引き込まない）
    "src.intelligence.theme_intelligence.relation_proposal_model",
    "src.intelligence.theme_intelligence.relation_proposal_resolution",
    "src.intelligence.theme_intelligence.relation_proposal_bridge",
    "src.intelligence.theme_intelligence.relation_proposal_store"}
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
            if token in INPUT_MODEL_TOKENS and name in INPUT_MODEL_MODULES:            # P6-B4C: 入力 model module（model のみ）
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
            "import src.intelligence.theme_intelligence.discovery_model, src.intelligence.theme_intelligence.discovery_predicates\n"
            "import src.intelligence.theme_intelligence.discovery_rules, src.intelligence.theme_intelligence.discovery_adapter\n"
            "import src.intelligence.theme_intelligence.discovery\n"
            "import src.intelligence.theme_intelligence.evidence_bridge_model\n"
            "import src.intelligence.theme_intelligence.evidence_bridge\n"
            "import src.intelligence.theme_intelligence.relation_model, src.intelligence.theme_intelligence.relation_store\n"
            "import src.intelligence.theme_intelligence.relation_resolution, src.intelligence.theme_intelligence.relation_graph\n"
            "import src.intelligence.theme_intelligence.relation_proposal_model, src.intelligence.theme_intelligence.relation_proposal_store\n"
            "import src.intelligence.theme_intelligence.relation_proposal_resolution, src.intelligence.theme_intelligence.relation_proposal_bridge\n"
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
            if token in LIFECYCLE_TOKEN_EXEMPTIONS.get(name, ()):
                continue
            assert token not in source, (name, token)
    store_source = executable_source(PACKAGE_DIR / "proposal_store.py")
    assert "open('ab'" in store_source and "fsync" in store_source                      # 唯一の書き込み経路は追記のみ


def test_proposal_modules_never_execute_foundation_operations_or_append_to_foundation() -> None:
    """P6-B3 §15 / §22: bridge / dedup / store は Foundation に書かない・operations を実行しない・root id を生成しない。"""
    for name in ("proposal_model", "proposal_store", "proposal_resolution", "dedup", "proposal_bridge",
                 "evidence_bridge_model", "evidence_bridge", "relation_model", "relation_resolution",
                 "relation_graph", "relation_store", "relation_proposal_model", "relation_proposal_resolution",
                 "relation_proposal_bridge", "relation_proposal_store",
                 "monitoring_store", "monitoring_adapter", "monitoring_runner"):
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


RELATION_MODULES = ("relation_model", "relation_resolution", "relation_graph", "relation_store")
RELATION_PROPOSAL_MODULES = ("relation_proposal_model", "relation_proposal_resolution", "relation_proposal_bridge",
                             "relation_proposal_store")


def test_frozen_theme_intelligence_modules_never_import_the_relation_authority() -> None:
    """P6-B5B §21: Foundation / B1 / B2 / B3 / B4 は B5B に依存しない（package 内の逆方向依存も作らない）。"""
    for name in MODULES:
        if name in RELATION_MODULES or name in RELATION_PROPOSAL_MODULES or name in MONITORING_MODULES:
            continue                                        # P6-B6D: monitoring は B5 の read-only 解決を読む下流層
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        for module in RELATION_MODULES:
            assert f"from .{module} import" not in source and f"theme_intelligence.{module}" not in source, (name, module)
    for path in THEMES_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for module in RELATION_MODULES:
            assert module not in text, (path.name, module)


def test_relation_proposal_modules_never_reach_the_relation_authority_store() -> None:
    """P6-B5C §1 / §22: 提案層は B5B の追記 API を import も参照もしない。"""
    for name in RELATION_PROPOSAL_MODULES:
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("relation_store", "ThemeRelationStore", "append_assertion", "append_event"):
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any(m.endswith(".relation_store") for m in imports), name
    for name in RELATION_MODULES:
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        for module in RELATION_PROPOSAL_MODULES:
            assert f"from .{module} import" not in source, (name, module)
