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
           "monitoring_store", "monitoring_adapter", "monitoring_runner",
           # P6-B7B: LLM 提案層の純 model / schema（provider・network・bridge・store なし）
           "llm_proposal_model",
           # P6-B7C: LLM 入力 manifest（純 model と、PIT 入口だけを読む read-only builder）
           "llm_manifest_model", "llm_manifest_builder",
           # P6-B7D: 検証済み提案 plan の純 model と決定論的な意味検証（純。data root・store・provider を持たない）
           "llm_plan_model", "llm_validator",
           # P6-B7E: 生成入力・provider protocol（fake / recorded のみ）・生成結果 / 監査 record・生成監査 journal・orchestration
           "llm_generation_input", "llm_provider", "llm_generation_model", "llm_generation_journal", "llm_generation",
           # P6-B7F: 検証済み plan → 既存 B3 / B5C 提案 authority の check-then-reuse 提出（decision・実行なし）
           "llm_submission_model", "llm_submission")
#: P6-B7: LLM 提案層（authority の手前の非 authority 層）。上流は B7 を import しない
LLM_MODULES = ("llm_proposal_model", "llm_manifest_model", "llm_manifest_builder", "llm_plan_model", "llm_validator",
               "llm_generation_input", "llm_provider", "llm_generation_model", "llm_generation_journal",
               "llm_generation", "llm_submission_model", "llm_submission")
#: B7 のうち I/O を一切持たない純 module
LLM_PURE_MODULES = ("llm_proposal_model", "llm_manifest_model", "llm_plan_model", "llm_validator",
                    "llm_generation_input", "llm_provider", "llm_generation_model", "llm_generation",
                    "llm_submission_model")
#: P6-B7E: B7 で唯一の書き込み面（生成監査 journal。authority ではない）。書いてよいのは自分の 1 file だけ
LLM_AUDIT_JOURNAL_MODULES = ("llm_generation_journal",)
LLM_AUDIT_JOURNAL_TOKENS = ("open(", "write", "mkdir")
#: P6-B7F: 既存の B3 / B5C 提案 authority にだけ `append_proposal` で追記する提出 bridge（decision・実行・他 store なし）
LLM_SUBMISSION_MODULES = ("llm_submission",)
LLM_SUBMISSION_IMPORTS = {".proposal_store": {"ProposalStore", "ProposalStoreError"},
                          ".relation_proposal_store": {"RelationProposalStore", "RelationProposalStoreError"}}
LLM_SUBMISSION_TOKENS = ("Store", "append_")
#: B7 のうち既存の PIT 入口（read-only）だけを通して data root を読む module。許すのは data_root という語と次の import だけ
LLM_READ_MODULES = ("llm_manifest_builder",)
LLM_READ_ENTRY_POINTS = {"..themes.resolver": {"ResolutionStatus", "resolve_at_data_root"},
                         ".relation_store": {"resolve_relations_at_data_root"}}
#: P6-B6: B5 の read-only な解決結果を読む層（package 内の逆方向依存ではない）
MONITORING_MODULES = ("monitoring_model", "monitoring_rules", "monitoring_engine", "monitoring_store",
                      "monitoring_adapter", "monitoring_runner")
IO_MODULES = ("proposal_store", "relation_store", "relation_proposal_store",
              "monitoring_store", "monitoring_runner", "llm_generation_journal")   # 追記専用 JSONL と read-only な読み取りのみ
IDENTITY_MODULES = ("proposal_model", "relation_model", "relation_proposal_model",
                    "monitoring_model", "monitoring_adapter", "llm_proposal_model", "llm_manifest_model",
                    "llm_plan_model", "llm_generation_input", "llm_generation_model")            # content id を計算する module
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
                    ".relation_proposal_resolution",
                    # P6-B7B / P6-B7C / P6-B7D（B7 内部の依存。上流から B7 への import は別 test が禁止する）
                    ".llm_proposal_model", ".llm_manifest_model", ".llm_plan_model",
                    # P6-B7E（orchestration が B7B〜B7D と生成監査 journal を読む）
                    ".llm_validator", ".llm_generation_input", ".llm_provider", ".llm_generation_model",
                    ".llm_generation_journal",
                    # P6-B7F（提出 bridge が提出結果 model を読む）
                    ".llm_submission_model"}
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
    "src.intelligence.theme_intelligence.relation_proposal_store",
    # P6-B7B: LLM 提案層の純 model（Foundation の語彙と B5B の relation 語彙だけを読む）
    "src.intelligence.theme_intelligence.llm_proposal_model",
    # P6-B7C: LLM 入力 manifest（純 model と read-only builder）。B6 の純 model は finding の型としてだけ読む（B7 → B6 の向き）
    "src.intelligence.theme_intelligence.llm_manifest_model", "src.intelligence.theme_intelligence.llm_manifest_builder",
    "src.intelligence.theme_intelligence.monitoring_model",
    # P6-B7D: plan model と validator（B3 / B5C の model を材料の型としてだけ読む。store / bridge は含まれない）
    "src.intelligence.theme_intelligence.llm_plan_model", "src.intelligence.theme_intelligence.llm_validator",
    # P6-B7E: 生成層（fake / recorded provider のみ。network・SDK・authority store は含まれない）
    "src.intelligence.theme_intelligence.llm_generation_input", "src.intelligence.theme_intelligence.llm_provider",
    "src.intelligence.theme_intelligence.llm_generation_model",
    "src.intelligence.theme_intelligence.llm_generation_journal", "src.intelligence.theme_intelligence.llm_generation",
    # P6-B7F: 提出 bridge（B3 / B5C の提案 store だけを読む。bridge・decision・B5B は含まれない）
    "src.intelligence.theme_intelligence.llm_submission_model", "src.intelligence.theme_intelligence.llm_submission"}
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
            "import src.intelligence.theme_intelligence.llm_proposal_model\n"
            "import src.intelligence.theme_intelligence.llm_manifest_model, src.intelligence.theme_intelligence.llm_manifest_builder\n"
            "import src.intelligence.theme_intelligence.llm_plan_model, src.intelligence.theme_intelligence.llm_validator\n"
            "import src.intelligence.theme_intelligence.llm_generation, src.intelligence.theme_intelligence.llm_provider\n"
            "import src.intelligence.theme_intelligence.llm_submission\n"
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
        if name in LLM_READ_MODULES:                                                    # P6-B7C: PIT 入口へ data root を渡すだけ
            forbidden = tuple(t for t in forbidden if t != "data_root")
        if name in LLM_SUBMISSION_MODULES:                                              # P6-B7F: 提案 store へ data root を渡し append_proposal だけ
            forbidden = tuple(t for t in forbidden if t not in ("data_root", "append_"))
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
                 "monitoring_store", "monitoring_adapter", "monitoring_runner", "llm_proposal_model",
                 "llm_manifest_model", "llm_manifest_builder", "llm_plan_model", "llm_validator",
                 "llm_generation_input", "llm_provider", "llm_generation_model", "llm_generation_journal",
                 "llm_generation", "llm_submission_model", "llm_submission"):
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
        if name in RELATION_MODULES or name in RELATION_PROPOSAL_MODULES or name in MONITORING_MODULES or name in LLM_MODULES:
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


# ---------------------------------------------------------------- P6-B7B: LLM 提案層の境界


def test_no_upstream_module_imports_the_llm_proposal_layer() -> None:
    """Foundation / B1〜B6 と src 全体は B7 を import しない（依存は B7 → 上流の一方向だけ）。"""
    for path in (REPO_ROOT / "src").rglob("*.py"):
        if path.parent == PACKAGE_DIR and path.stem in LLM_MODULES:
            continue
        imports = imported_modules(path)
        assert not any(segment.startswith("llm_") for m in imports for segment in m.split(".")), \
            str(path.relative_to(REPO_ROOT))
        assert "theme_intelligence.llm_" not in path.read_text(encoding="utf-8"), str(path.relative_to(REPO_ROOT))


def test_every_llm_module_is_registered_and_guarded() -> None:
    present = sorted(p.stem for p in PACKAGE_DIR.glob("llm_*.py"))
    assert present == sorted(LLM_MODULES) and set(LLM_MODULES) <= set(MODULES)
    groups = (set(LLM_PURE_MODULES), set(LLM_READ_MODULES), set(LLM_AUDIT_JOURNAL_MODULES), set(LLM_SUBMISSION_MODULES))
    assert set().union(*groups) == set(LLM_MODULES) and sum(len(g) for g in groups) == len(LLM_MODULES)   # 重なりなし
    assert not [p for p in PACKAGE_DIR.rglob("*.py") if p.parent != PACKAGE_DIR]          # subpackage で guard を逃れない


def test_llm_modules_reach_no_store_bridge_network_provider_or_publication_path() -> None:
    for name in LLM_MODULES:
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        reading = (set(LLM_READ_ENTRY_POINTS) if name in LLM_READ_MODULES
                   else set(LLM_SUBMISSION_IMPORTS) if name in LLM_SUBMISSION_MODULES else set())
        assert not any(m.endswith(("store", "bridge", "runner", "operations", "revision", "resolver"))
                       for m in imports - reading), (name, imports)
        assert not any(token in m for m in imports for token in ("notifier", "publish", "report", "pages", "legacy",
                                                                  "compass", "corpus", "formal_review", "decision",
                                                                  "http", "requests", "urllib", "socket", "anthropic",
                                                                  "openai", "contracts")), (name, imports)
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("append_", "execute_", "Store", "environ", "getenv", "LLMProvider", ".complete(", "uuid",
                      "open(", "write", "mkdir", "unlink"):
            if name in LLM_AUDIT_JOURNAL_MODULES and token in LLM_AUDIT_JOURNAL_TOKENS:
                continue                                    # P6-B7E: 生成監査 journal 自身の 1 file への追記だけ
            if name in LLM_SUBMISSION_MODULES and token in LLM_SUBMISSION_TOKENS:
                continue                                    # P6-B7F: 既存の提案 store と append_proposal だけ（下の test が絞る）
            assert token not in source, (name, token)
        if name in LLM_PURE_MODULES:
            assert "data_root" not in source, name


def test_the_read_only_builder_uses_only_the_pit_entry_points() -> None:
    """P6-B7C: builder が上流から取り込めるのは PIT 解決の入口だけ（store class・append API は取り込まない）。"""
    for name in LLM_READ_MODULES:
        tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and ("." * node.level + (node.module or "")) in LLM_READ_ENTRY_POINTS:
                module = "." * node.level + (node.module or "")
                assert {alias.name for alias in node.names} <= LLM_READ_ENTRY_POINTS[module], (name, module)


def test_the_generation_audit_journal_is_the_only_llm_write_surface() -> None:
    """P6-B7E §30: 書き込みは生成監査 journal の 1 file だけ。authority・提案・review・公開経路へは書かない。"""
    journal = PACKAGE_DIR / "llm_generation_journal.py"
    source = executable_source(journal)
    assert source.count(".jsonl") == 1 and "llm_generation_records.jsonl" in source
    assert {m for m in imported_modules(journal) if m.startswith(".")} == {".llm_generation_model"}
    for name in LLM_MODULES:
        text = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("append_proposal", "append_decision", "append_assertion", "append_event", "append_governance",
                      "append_review_state", "append_root", "append_observation", "ProposalStore",
                      "RelationProposalStore", "ThemeRelationStore", "MonitoringReviewStore", "ThemeStore",
                      "attach_evidence", "notifier", "publish_", "publication"):
            if name in LLM_SUBMISSION_MODULES and token in ("append_proposal", "ProposalStore", "RelationProposalStore"):
                continue                                    # P6-B7F: 提出 bridge は既存の提案 authority にだけ追記する
            assert token not in text, (name, token)
        if name not in LLM_AUDIT_JOURNAL_MODULES:
            assert "fsync" not in text and "open(" not in text and ".jsonl" not in text, name
    importers = sorted(str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "src").rglob("*.py")
                       if any(m.endswith("llm_generation_journal") for m in imported_modules(path)))
    assert importers == ["src/intelligence/theme_intelligence/llm_generation.py"], importers
    assert not any(m.endswith(("llm_generation_journal", "llm_generation_model", "llm_generation"))
                   for m in imported_modules(PACKAGE_DIR / "llm_generation_input.py"))   # 生成入力は journal を読まない


def test_the_submission_bridge_appends_only_proposals_to_the_existing_proposal_authorities() -> None:
    """P6-B7F §33: 提出 bridge が届くのは B7D の plan model・B3 / B5C の提案 model / store・core だけ。"""
    for name in LLM_SUBMISSION_MODULES:
        path = PACKAGE_DIR / f"{name}.py"
        source = executable_source(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and ("." * node.level + (node.module or "")) in LLM_SUBMISSION_IMPORTS:
                module = "." * node.level + (node.module or "")
                assert {alias.name for alias in node.names} <= LLM_SUBMISSION_IMPORTS[module], (name, module)
        relative = {m for m in imported_modules(path) if m.startswith(".")}
        assert relative <= {".llm_plan_model", ".llm_submission_model", ".proposal_model", ".proposal_store",
                            ".relation_proposal_model", ".relation_proposal_store", "..core.time",
                            "..themes.model"}, relative
        assert source.count("append_") == source.count("append_proposal") >= 1          # 追記は提案だけ
        for token in ("append_decision", "Decision", "SourceClaimVerification", "append_assertion", "append_event",
                      "append_governance", "append_review_state", "ThemeStore", "ThemeRelationStore",
                      "MonitoringReviewStore", "LlmGenerationJournal", "plan_theme_creation", "plan_evidence_attachment",
                      "plan_relation_assertion", "accepted_assertion_class", "initialize(", "_write_line", "open("):
            assert token not in source, (name, token)
    for name in LLM_MODULES:                                     # 提案 store に届く B7 module は提出 bridge だけ
        if name in LLM_SUBMISSION_MODULES:
            continue
        assert not any(m.endswith(("proposal_store", "relation_proposal_store"))
                       for m in imported_modules(PACKAGE_DIR / f"{name}.py")), name
