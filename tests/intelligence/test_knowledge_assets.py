"""knowledge/ 配下のYAML知識資産の検証。

- 全YAMLがパース可能で、共通メタデータ（id/version/description/source/status）を持つ
- ルールIDがファイル横断で一意
- テーマグラフの参照整合性
- Tier閾値との整合
- Secret・アカウント識別子の混入なし（SECURITY PRINCIPLE）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"

REQUIRED_METADATA = ("id", "version", "description", "source", "status")
ALLOWED_STATUS = {"active", "draft", "deprecated"}
ALLOWED_CONFIDENCE = {"confirmed", "likely", "hypothesis"}
ALLOWED_VERIFICATION = {"unverified", "likely_dead", "verified", "dead"}


def knowledge_yaml_paths() -> list[Path]:
    paths = sorted(KNOWLEDGE_DIR.rglob("*.yaml"))
    assert paths, "knowledge/ にYAML資産が存在すること"
    return paths


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"{path} はトップレベルがマッピングであること"
    return data


@pytest.mark.parametrize("path", knowledge_yaml_paths(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_parses_and_has_required_metadata(path: Path) -> None:
    data = load(path)
    for key in REQUIRED_METADATA:
        assert key in data and data[key], f"{path.name}: メタデータ '{key}' が必要"
    assert data["status"] in ALLOWED_STATUS
    assert re.match(r"^\d+\.\d+\.\d+$", str(data["version"])), f"{path.name}: versionはsemver形式"


def _iter_rules():
    """ルール型エントリ（causal_rules/compass_dna）を (path, rule_id, rule) で列挙する。"""
    for path in knowledge_yaml_paths():
        data = load(path)
        for rule in data.get("rules", []) or []:
            rule_id = rule.get("id") or rule.get("rule_id")
            yield path, rule_id, rule


def test_rule_ids_present_and_unique_across_files() -> None:
    seen: dict[str, Path] = {}
    count = 0
    for path, rule_id, _rule in _iter_rules():
        count += 1
        assert rule_id, f"{path.name}: 全ルールに id / rule_id が必要"
        assert rule_id not in seen, (
            f"ルールID重複: {rule_id}（{seen.get(rule_id)} と {path.name}）"
        )
        seen[rule_id] = path
    assert count >= 20, "causal_rules 18本 + compass_dna ルールが読み込めていること"


def test_causal_rules_have_required_fields() -> None:
    for name in ("market.yaml", "rates.yaml", "fx.yaml"):
        data = load(KNOWLEDGE_DIR / "causal_rules" / name)
        assert data["rules"], f"{name}: ルールが空でないこと"
        for rule in data["rules"]:
            for key in ("id", "trigger_keywords", "theme", "beneficiary_sectors",
                        "negative_sectors", "durable", "note", "confidence", "status"):
                assert key in rule, f"{name}:{rule.get('id')}: '{key}' が必要"
            assert rule["confidence"] in ALLOWED_CONFIDENCE
            assert isinstance(rule["durable"], bool)
            assert rule["trigger_keywords"], "trigger_keywordsは1件以上"


def test_theme_graph_references_are_resolvable() -> None:
    themes = load(KNOWLEDGE_DIR / "theme_relations" / "themes.yaml")
    graph = load(KNOWLEDGE_DIR / "theme_relations" / "theme_graph.yaml")
    labels = {t["label"] for t in themes["themes"]}
    assert len(labels) == len(themes["themes"]), "テーマlabelは一意であること"
    known = labels | set(graph.get("supplementary_nodes", [])) | set(graph["relations"].keys())
    for node, related in graph["relations"].items():
        assert isinstance(related, list) and related
        assert node not in related, f"{node}: 自己参照エッジは不可"
        for target in related:
            assert target in known, (
                f"theme_graph: '{node}' の関連先 '{target}' が未定義"
                "（themes.yaml か supplementary_nodes に定義が必要）"
            )


def test_source_tiers_consistent_with_thresholds() -> None:
    data = load(KNOWLEDGE_DIR / "source_reliability" / "source_tiers.yaml")
    t1 = data["tier_thresholds"]["tier1_min"]
    t2 = data["tier_thresholds"]["tier2_min"]
    names = set()
    for src in data["sources"]:
        assert src["name"] not in names, f"ソース名重複: {src['name']}"
        names.add(src["name"])
        rel = src["reliability"]
        assert 0.0 <= rel <= 1.0
        expected = 1 if rel >= t1 else (2 if rel >= t2 else 3)
        assert src["tier"] == expected, (
            f"{src['name']}: reliability={rel} なら tier {expected} のはず（実際: {src['tier']}）"
        )


def test_source_feeds_catalog_shape() -> None:
    data = load(KNOWLEDGE_DIR / "source_reliability" / "source_feeds.yaml")
    ids = set()
    for feed in data["feeds"]:
        for key in ("id", "name", "url", "lang", "format", "verification"):
            assert key in feed, f"feed {feed.get('id')}: '{key}' が必要"
        assert feed["id"] not in ids, f"feed id重複: {feed['id']}"
        ids.add(feed["id"])
        assert feed["url"].startswith("https://"), f"{feed['id']}: URLはhttpsであること"
        assert feed["verification"] in ALLOWED_VERIFICATION


def test_no_secrets_or_account_identifiers() -> None:
    """SECURITY PRINCIPLE: knowledge/へSecret・アカウント識別子を持ち込まない。"""
    forbidden_patterns = [
        r"sk-ant", r"AKIA[0-9A-Z]{8,}", r"ghp_[A-Za-z0-9]{10,}", r"x-api-key",
        r"Bearer\s+[A-Za-z0-9._\-]{8,}", r"workers\.dev", r"[\w.+-]+@[\w-]+\.[\w.]+",
    ]
    for path in knowledge_yaml_paths() + [KNOWLEDGE_DIR / "README.md"]:
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert not re.search(pattern, text), f"{path.name}: 禁止パターン検出 ({pattern})"
