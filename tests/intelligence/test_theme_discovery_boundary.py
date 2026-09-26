"""P6-B4C — discovery の boundary / security test（matrix 74〜79 と補助。69〜73・80・81 は git / full suite で gate 報告時に検証）。

store 書き込みなし、network / LLM なし、score / rank / confidence なし、public / customer 内容なし、config / workflow 非参照、
production closure 排除、Foundation / B1 / B2 / B3 / B4B が B4C を import しないこと、入力 model の import が model module に限られることを固定する。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.intelligence.theme_intelligence.discovery import discover
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_discovery import catalog, fact, news, observation, ruleset, taxonomy  # noqa: F401  (fixtures)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
KNOWLEDGE_DIR = REPO_ROOT / "knowledge" / "theme_intelligence"
RULESET_FILE = KNOWLEDGE_DIR / "discovery_rules.0.1.0.yaml"
B4C_MODULES = ("discovery_model", "discovery_predicates", "discovery_rules", "discovery_adapter", "discovery")
FROZEN_MODULES = ("model", "change", "lifecycle_model", "lifecycle", "proposal_model", "proposal_store", "proposal_resolution", "dedup",
                  "proposal_bridge", "knowledge_loader", "taxonomy_model", "taxonomy", "entity_model", "entity_catalog")
CUTOFF = datetime(2026, 9, 21, tzinfo=timezone.utc)

NO_WRITE_TOKENS = ("write_text(", "write_bytes(", ".write(", "open(", "mkdir(", "unlink(", "os.rename", "os.replace", "shutil", "fsync", "jsonl",
                   "sqlite", "data_root", "INTELLIGENCE_DATA_ROOT", "read_text(", "read_bytes(")
NO_STORE_TOKENS = ("ThemeStore", "ProposalStore", "themes.store", "themes.operations", "themes.revision", "proposal_store", "execute_",
                   "append_proposal", "append_decision", "append_root", "plan_candidate", "new_root_id", "proposal_bridge")
NO_NETWORK_LLM_TOKENS = ("requests", "urllib", "socket", "http", "aiohttp", "openai", "anthropic", "llm", "LLM", "embedding", "cosine", "similarity",
                         "rapidfuzz", "Levenshtein", "difflib", "SequenceMatcher", "fuzz")
NO_CLOCK_TOKENS = (".now(", "utcnow", "time.time", "today(", "perf_counter", "monotonic")
NO_SCORE_TOKENS = ("score", "rank", "confidence", "investment_stance", "weight", "BUY", "SELL", "target_price", "beneficiar", "recommend")
CONFIDENTIAL_TOKENS = ("Compass", "compass", "羅針盤", "CONFIRMED", "THEME_DISCOVERY_RULES", "watchlist", "Watchlist", "DNA")
MACHINE_PATH_RE = re.compile(r"[A-Za-z]:\\|/Users/|/home/[a-z]+/|\\\\")
ISSUE_REF_RE = re.compile(r"(?<![0-9.])\b\d{1,2}/\d{1,2}\b")


def _sources() -> dict:
    return {name: executable_source(PACKAGE_DIR / f"{name}.py") for name in B4C_MODULES}


def test_74_no_store_writes_and_discover_writes_nothing(tmp_path, taxonomy, catalog, ruleset) -> None:
    before = sorted((p.name, p.stat().st_size) for p in KNOWLEDGE_DIR.iterdir())
    discover([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan"), observation("o"), fact("f")],
             taxonomy=taxonomy, entity_catalog=catalog, ruleset=ruleset, cutoff=CUTOFF, run_created_at=CUTOFF)
    assert sorted((p.name, p.stat().st_size) for p in KNOWLEDGE_DIR.iterdir()) == before and not list(tmp_path.iterdir())
    for name, source in _sources().items():
        for token in NO_WRITE_TOKENS + NO_STORE_TOKENS:
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any(m.endswith(("themes.store", "themes.operations", "themes.revision", "proposal_store", "proposal_bridge")) for m in imports), name
        assert "yaml" not in imports, name                                             # YAML は B4B knowledge_loader だけが読む


def test_75_no_network_llm_fuzzy_or_clock() -> None:
    for name, source in _sources().items():
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        for token in NO_NETWORK_LLM_TOKENS:
            assert not any(re.search(rf"(^|\.){token}(\.|$)", m) for m in imports), (name, token)
            assert token not in source, (name, token)
        for token in NO_CLOCK_TOKENS:
            assert token not in source, (name, token)
        assert not ({"random", "secrets", "subprocess", "numpy", "sklearn"} & imports), name
    adapter = _sources()["discovery_adapter"]
    assert "re.escape(" in adapter and "(?<![a-z0-9])" in adapter                       # alias は escape 済み literal の境界一致のみ
    assert ".body" not in adapter and "full_text" not in adapter and "content" not in adapter.replace("content_hash", "")


def test_76_no_score_rank_confidence_in_sources_or_report(taxonomy, catalog, ruleset) -> None:
    for name, source in _sources().items():
        for token in NO_SCORE_TOKENS:
            assert token not in source, (name, token)
    result = discover([news("1", "Data centre power in Japan"), news("2", "Datacenter electric power in Japan"), observation("o")],
                      taxonomy=taxonomy, entity_catalog=catalog, ruleset=ruleset, cutoff=CUTOFF, run_created_at=CUTOFF)
    plain = json.dumps(result.run_report.to_plain()).lower()
    for token in ("score", "rank", "confidence", "stance", "weight", "buy", "sell"):
        assert token not in plain, token
    assert all(not hasattr(p, "score") and not hasattr(p, "rank") for p in result.proposals)


def test_77_no_public_customer_or_confidential_content_in_ruleset() -> None:
    text = RULESET_FILE.read_text(encoding="utf-8")
    semantic = yaml.safe_dump(yaml.safe_load(text), allow_unicode=True)
    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    names, tickers = set(), set()
    for group in (config.get("watchlist") or {}).values():
        for item in group or []:
            if isinstance(item, dict):
                names.add(str(item.get("name", ""))) if item.get("name") else None
                tickers.add(str(item.get("ticker", ""))) if item.get("ticker") else None
    assert names and tickers
    for company in names | tickers:
        assert company not in text, company
    for token in CONFIDENTIAL_TOKENS + ("customer", "顧客", "buy", "sell", "recommend", "beneficiar", "target price"):
        assert token not in semantic, token
    assert "羅針盤" not in text and "CONFIRMED" not in text and not MACHINE_PATH_RE.search(text) and not ISSUE_REF_RE.search(semantic)
    document = yaml.safe_load(text)
    for rule in document["rules"]:
        assert rule["provenance"]["origin"] in ("SUPERVISOR_DECISION", "MVP_FIXTURE", "PUBLIC_STANDARD")
        assert "company:" not in json.dumps(rule.get("entity_refs", []))              # MVP ruleset は企業 entity を trigger にしない
        assert rule["proposed_role"] in ("SUPPORTS", "CONTEXT")
    assert sorted(p.name for p in KNOWLEDGE_DIR.glob("discovery_rules.*.yaml")) == ["discovery_rules.0.1.0.yaml"]


def test_78_no_config_workflow_or_frozen_module_references_b4c() -> None:
    for path in (REPO_ROOT / ".github").rglob("*.yml"):
        assert "theme_intelligence" not in path.read_text(encoding="utf-8"), path.name
    assert "theme_intelligence" not in (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    for path in (REPO_ROOT / "scripts").glob("*.py"):
        assert "theme_intelligence" not in path.read_text(encoding="utf-8"), path.name
    for name in FROZEN_MODULES:
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        for module in B4C_MODULES:
            assert f"theme_intelligence.{module}" not in source and f"from .{module} import" not in source, (name, module)
    for path in (REPO_ROOT / "src" / "intelligence" / "themes").glob("*.py"):
        for module in B4C_MODULES:
            assert f"theme_intelligence.{module}" not in path.read_text(encoding="utf-8"), path.name


def test_79_production_closure_excludes_discovery_and_inputs_are_model_modules_only() -> None:
    closure = runtime_closure()
    assert closure and not any("theme_intelligence" in m for m in closure)
    adapter_imports = imported_modules(PACKAGE_DIR / "discovery_adapter.py")
    upstream = {m for m in adapter_imports if m.startswith("..")}
    assert upstream == {"..core.types", "..databank.news_model", "..facts.model", "..market.model", "..sources.model", "..themes.model"}
    for name in B4C_MODULES:
        if name != "discovery_adapter":
            assert not any(m.startswith(("..facts", "..market", "..sources", "..databank", "..core.types")) for m in imported_modules(PACKAGE_DIR / f"{name}.py")), name
    for module in ("facts", "market", "sources", "databank"):
        init = (REPO_ROOT / "src" / "intelligence" / module / "__init__.py").read_text(encoding="utf-8")
        assert not re.search(r"^(from|import) ", init, flags=re.M), module              # package init が store / provider を引き込まない
