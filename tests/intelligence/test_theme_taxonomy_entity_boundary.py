"""P6-B4B — taxonomy / entity knowledge の boundary / security test（matrix 51〜64 のうち test 化できるもの）。

51〜54（Foundation / B1 / B2 / B3 の diff 0）は git で gate 報告時に検証する。ここでは: proposal 生成なし、discovery rule
なし、network なし、現在時刻なし、fuzzy / embedding なし、顧客 watchlist 内容なし、機密 Compass 文言なし、Pages / public
closure 非混入、workflow / config 非参照、knowledge 読み込みが何も書かないことを固定する。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "intelligence" / "theme_intelligence"
KNOWLEDGE_DIR = REPO_ROOT / "knowledge" / "theme_intelligence"
B4B_MODULES = ("knowledge_loader", "taxonomy_model", "taxonomy", "entity_model", "entity_catalog")
FROZEN_MODULES = ("model", "change", "lifecycle_model", "lifecycle", "proposal_model", "proposal_store", "proposal_resolution",
                  "dedup", "proposal_bridge")
KNOWLEDGE_FILES = ("theme_taxonomy.0.1.0.yaml", "theme_taxonomy.0.2.0.yaml", "entity_catalog.0.1.0.yaml", "entity_catalog.0.2.0.yaml")
CUTOFF = datetime(2026, 9, 21, tzinfo=timezone.utc)

NO_PROPOSAL_TOKENS = ("Proposal", "proposal_", "thprop", "thdec", "DEDUP", "ThemeCandidate", "EvidenceCandidate")
NO_DISCOVERY_TOKENS = ("discovery", "Discovery", "rule_id", "ruleset", "predicate", "trigger_term", "signal", "strong_", "weak_")
NO_NETWORK_TOKENS = ("requests", "urllib", "socket", "http", "ssl", "ftplib", "smtplib", "aiohttp")
NO_CLOCK_TOKENS = (".now(", "utcnow", "time.time", "today(", "perf_counter", "monotonic")
NO_FUZZY_TOKENS = ("difflib", "SequenceMatcher", "rapidfuzz", "Levenshtein", "jellyfish", "embedding", "cosine", "similarity",
                   "fuzz", "ngram", "n_gram", "startswith(", ".find(", "in headline", "in body", "numpy", "sklearn")
NO_WRITE_TOKENS = ("write_text(", "write_bytes(", ".write(", "open(", "mkdir(", "unlink(", "os.rename", "os.replace", "shutil",
                   "fsync", "jsonl", "sqlite", "data_root", "INTELLIGENCE_DATA_ROOT")
NO_STORE_TOKENS = ("ThemeStore", "ProposalStore", "themes.store", "themes.operations", "themes.revision", "proposal_store",
                   "execute_", "append_", "plan_candidate", "new_root_id")
CONFIDENTIAL_TOKENS = ("Compass", "compass", "羅針盤", "CONFIRMED", "THEME_DISCOVERY_RULES", "watchlist", "Watchlist", "DNA")
MACHINE_PATH_RE = re.compile(r"[A-Za-z]:\\|/Users/|/home/[a-z]+/|\\\\")
ISSUE_REF_RE = re.compile(r"(?<![0-9.])\b\d{1,2}/\d{1,2}\b")            # 号 / 頁 / 日付参照（例 6/22）


def _sources() -> dict:
    return {name: executable_source(PACKAGE_DIR / f"{name}.py") for name in B4B_MODULES}


def test_55_no_proposal_generation_in_knowledge_modules() -> None:
    for name, source in _sources().items():
        for token in NO_PROPOSAL_TOKENS:
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any("proposal" in m or "dedup" in m or "bridge" in m for m in imports), (name, imports)


def test_56_no_discovery_rules_in_knowledge_modules_or_files() -> None:
    for name, source in _sources().items():
        for token in NO_DISCOVERY_TOKENS:
            assert token not in source, (name, token)
    for name in KNOWLEDGE_FILES:
        document = yaml.safe_load((KNOWLEDGE_DIR / name).read_text(encoding="utf-8"))
        assert set(document) <= {"schema_version", "taxonomy_version", "catalog_version", "published_at", "content_digest",
                                 "nodes", "entities"}
        for record in document.get("nodes", []) + document.get("entities", []):
            assert not ({"strong_signals", "weak_signals", "exclude_terms", "keywords", "related", "trigger_terms", "predicates"}
                        & set(record)), (name, record.get("slug") or record.get("entity_id"))
    assert not list(KNOWLEDGE_DIR.glob("*signal*"))
    others = sorted(p.name for p in KNOWLEDGE_DIR.iterdir() if p.name not in KNOWLEDGE_FILES)
    assert all(re.match(r"^discovery_rules\.\d+\.\d+\.\d+\.yaml$", n) for n in others), others   # P6-B4C の ruleset だけが同居できる


def test_57_58_no_network_and_no_current_clock() -> None:
    for name, source in _sources().items():
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        for token in NO_NETWORK_TOKENS:
            assert not any(re.search(rf"(^|\.){token}(\.|$)", m) for m in imports), (name, token)
            assert f"{token}." not in source, (name, token)
        for token in NO_CLOCK_TOKENS:
            assert token not in source, (name, token)
        assert "random" not in imports and "secrets" not in imports and "subprocess" not in imports


def test_59_no_fuzzy_matching_or_embedding() -> None:
    for name, source in _sources().items():
        for token in NO_FUZZY_TOKENS:
            assert token not in source, (name, token)
    # 解決 API は正規化 token の辞書引きだけで、走査 / 部分一致の道具を持たない
    for name in ("taxonomy", "entity_catalog"):
        source = _sources()[name]
        assert "re.compile" not in source and "re.search" not in source and "re.match" not in source, name


def test_60_no_customer_or_watchlist_content_in_knowledge() -> None:
    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    watch = config.get("watchlist") or {}
    names, tickers = set(), set()
    for group in watch.values():
        for item in group or []:
            if isinstance(item, dict):
                if item.get("name"):
                    names.add(str(item["name"]))
                if item.get("ticker"):
                    tickers.add(str(item["ticker"]))
    assert names and tickers, "config watchlist must be readable for this guard"
    for name in KNOWLEDGE_FILES:
        text = (KNOWLEDGE_DIR / name).read_text(encoding="utf-8")
        semantic = yaml.safe_dump(yaml.safe_load(text), allow_unicode=True)   # header comment（内容方針の説明）を除く
        for company in names:
            assert company not in text, (name, "watchlist name present")
        for ticker in tickers:
            assert ticker not in text, (name, "watchlist ticker present")
        for token in ("watchlist", "Watchlist", "customer", "顧客"):
            assert token not in semantic, (name, token)
    document = yaml.safe_load((KNOWLEDGE_DIR / "entity_catalog.0.2.0.yaml").read_text(encoding="utf-8"))
    companies = [e for e in document["entities"] if e["entity_type"] == "COMPANY"]
    assert companies and all(e["provenance"]["origin"] == "MVP_FIXTURE" and e["canonical_name"].startswith("Example ") for e in companies)
    assert all(i.get("scheme") == "XMVP" for e in companies for i in e.get("identifiers", []))   # 架空市場 code のみ
    assert not [e for e in document["entities"] if e["entity_type"] == "PERSON"]


def test_61_no_confidential_compass_text_in_knowledge_or_modules() -> None:
    for name in KNOWLEDGE_FILES:
        text = (KNOWLEDGE_DIR / name).read_text(encoding="utf-8")
        semantic = yaml.safe_dump(yaml.safe_load(text), allow_unicode=True)   # comment を除いた semantic 部分
        for token in CONFIDENTIAL_TOKENS:
            assert token not in semantic, (name, token)
        assert "羅針盤" not in text and "CONFIRMED" not in text and "THEME_DISCOVERY_RULES" not in text
        assert not MACHINE_PATH_RE.search(text) and not ISSUE_REF_RE.search(semantic), name
        assert ".pdf" not in text.lower()
    for name, source in _sources().items():
        for token in ("Compass", "羅針盤", "CONFIRMED", "watchlist", "DNA"):
            assert token not in source, (name, token)


def test_62_knowledge_layer_is_outside_pages_and_production_closure() -> None:
    closure = runtime_closure()
    assert closure and not any("theme_intelligence" in m for m in closure)
    manifest = (REPO_ROOT / "scripts" / "p43b2c_pages_manifest.py").read_text(encoding="utf-8")
    assert '"knowledge"' in manifest                                              # 公開 tree で knowledge path 断片を禁止
    for path in list((REPO_ROOT / ".github").rglob("*.yml")) + list((REPO_ROOT / "scripts").glob("*.py")):
        assert "theme_intelligence" not in path.read_text(encoding="utf-8"), path.name


def test_63_no_workflow_config_or_frozen_module_references_b4b() -> None:
    for path in (REPO_ROOT / ".github").rglob("*.yml"):
        assert "theme_intelligence" not in path.read_text(encoding="utf-8"), path.name
    assert "theme_intelligence" not in (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    for name in FROZEN_MODULES:
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        for module in B4B_MODULES:
            assert module not in source, (name, module)
    for path in (REPO_ROOT / "src" / "intelligence" / "themes").glob("*.py"):
        for module in B4B_MODULES:
            assert f"theme_intelligence.{module}" not in path.read_text(encoding="utf-8"), path.name


def test_64_loading_knowledge_writes_nothing_and_modules_have_no_write_or_store_tokens(tmp_path) -> None:
    from src.intelligence.theme_intelligence.entity_catalog import load_entity_catalog_version
    from src.intelligence.theme_intelligence.taxonomy import load_taxonomy_version

    before = sorted((p.name, p.stat().st_size) for p in KNOWLEDGE_DIR.iterdir())
    load_taxonomy_version(KNOWLEDGE_DIR / "theme_taxonomy.0.2.0.yaml", expected_version="0.2.0", cutoff=CUTOFF)
    load_entity_catalog_version(KNOWLEDGE_DIR / "entity_catalog.0.2.0.yaml", expected_version="0.2.0", cutoff=CUTOFF)
    assert sorted((p.name, p.stat().st_size) for p in KNOWLEDGE_DIR.iterdir()) == before
    assert not list(tmp_path.iterdir())
    for name, source in _sources().items():
        for token in NO_WRITE_TOKENS + NO_STORE_TOKENS:
            assert token not in source, (name, token)
        imports = imported_modules(PACKAGE_DIR / f"{name}.py")
        assert not any(m.endswith(("themes.store", "themes.operations", "themes.revision", "proposal_store")) for m in imports), name
    assert "read_text(" in _sources()["knowledge_loader"]                        # 読み取りは loader module だけ
    for name in B4B_MODULES:
        if name != "knowledge_loader":
            assert "read_text(" not in _sources()[name] and "yaml" not in imported_modules(PACKAGE_DIR / f"{name}.py"), name
