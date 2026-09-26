"""P6-B4B — Theme taxonomy versioned knowledge（test matrix 1〜24 ＋ 補助）。

knowledge/theme_intelligence の公開 snapshot（0.1.0 / 0.2.0）と tmp_path 上の fixture の両方で、version / cutoff / digest の
gate、DAG 規則、正規化、PIT、Foundation METADATA TAXONOMY 値検証（書き込みなし）を固定する。
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.intelligence.theme_intelligence.knowledge_loader import (KnowledgeError, KnowledgeOrigin, KnowledgeProvenance,
                                                                  content_digest, knowledge_path, normalize_token)
from src.intelligence.theme_intelligence.taxonomy import (TaxonomyRefStatus, TaxonomyResolutionStatus, compute_taxonomy_digest,
                                                          load_taxonomy_version, resolve_taxonomy_token, taxonomy_path,
                                                          validate_theme_taxonomy_refs)
from src.intelligence.theme_intelligence.taxonomy_model import TAXONOMY_SCHEMA_VERSION, TaxonomyNode, TaxonomySnapshot
from src.intelligence.themes.model import SET_VALUED_METADATA_FIELDS, MetadataField

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
T_010 = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
T_020 = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 9, 21, tzinfo=timezone.utc)
BETWEEN = datetime(2026, 9, 20, 0, 30, tzinfo=timezone.utc)
GOLDEN = {"0.1.0": "f33aa28c5ce7ccb3650c17c85d77433c6b5cc1d130e611eaa4fe82aa93b79b60",
          "0.2.0": "75c0ae8c0c2d47c278737375a63db0aff8770d66c05dc4b37777ffc1627d757c"}


# ---------------------------------------------------------------- helpers


def prov(origin: str = "MVP_FIXTURE", reason: str = "fixture node") -> dict:
    return {"origin": origin, "approver_ref": "role:test", "reason": reason}


def node(slug: str, *, parents=(), aliases=(), since="0.1.0", deprecated="", superseded=(), label=None, description=None) -> dict:
    data = {"slug": slug, "label": label or slug.replace("_", " ").title(), "description": description or f"fixture node {slug}",
            "parent_slugs": list(parents), "aliases": list(aliases), "since_version": since, "provenance": prov()}
    if deprecated:
        data["deprecated_in_version"] = deprecated
    if superseded:
        data["superseded_by"] = list(superseded)
    return data


def fixture_nodes() -> list:
    return [node("ai", aliases=["artificial intelligence"]), node("power"), node("energy"),
            node("data_center", parents=["ai"], aliases=["data centre"]), node("nuclear", parents=["energy", "power"]),
            node("old_name", aliases=["old alias"])]


def document(nodes, *, version="0.1.0", published=T_010, digest="", schema=TAXONOMY_SCHEMA_VERSION, extra=None) -> dict:
    doc = {"schema_version": schema, "taxonomy_version": version,
           "published_at": published.isoformat() if isinstance(published, datetime) else published,
           "content_digest": digest, "nodes": nodes}
    if extra:
        doc.update(extra)
    return doc


def write(tmp_path: Path, doc: dict, name: str = "taxonomy.yaml", *, sign: bool = True, text: str = None) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if sign and text is None and not doc.get("content_digest"):
        signed = dict(doc, content_digest=compute_taxonomy_digest(path))
        path.write_text(yaml.safe_dump(signed, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load(tmp_path: Path, nodes=None, *, version="0.1.0", cutoff=CUTOFF, **kw) -> TaxonomySnapshot:
    path = write(tmp_path, document(nodes if nodes is not None else fixture_nodes(), version=version, **kw))
    return load_taxonomy_version(path, expected_version=version, cutoff=cutoff)


def expect(tmp_path: Path, code: str, nodes=None, **kw) -> None:
    with pytest.raises(KnowledgeError) as info:
        load(tmp_path, nodes, **kw)
    assert info.value.code == code, (info.value.code, str(info.value))


@pytest.fixture(scope="module")
def v010() -> TaxonomySnapshot:
    return load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=CUTOFF)


@pytest.fixture(scope="module")
def v020() -> TaxonomySnapshot:
    return load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUTOFF)


# ---------------------------------------------------------------- 1〜7 snapshot / digest / version / PIT


def test_01_canonical_published_snapshots_load_and_match_golden_digests(v010, v020) -> None:
    assert taxonomy_path(KNOWLEDGE_ROOT, "0.1.0") == KNOWLEDGE_ROOT / "theme_intelligence" / "theme_taxonomy.0.1.0.yaml"
    assert v010.content_digest == GOLDEN["0.1.0"] and v020.content_digest == GOLDEN["0.2.0"]
    assert v010.slugs() == ("ai", "data_center", "energy", "grid", "nuclear", "power", "semiconductors", "supply_chain_theme")
    assert v020.in_force_slugs() == ("ai", "data_center", "energy", "grid", "nuclear", "power", "semiconductors", "supply_chain")
    assert v010.nodes == tuple(sorted(v010.nodes, key=lambda n: n.slug))
    assert all(n.provenance.origin in (KnowledgeOrigin.HISTORICAL_SLUG_SEED, KnowledgeOrigin.SUPERVISOR_DECISION) for n in v020.nodes)


def test_02_digest_is_deterministic_and_recomputable(tmp_path, v010) -> None:
    assert content_digest(v010.semantic_payload()) == v010.content_digest
    assert compute_taxonomy_digest(taxonomy_path(KNOWLEDGE_ROOT, "0.1.0")) == GOLDEN["0.1.0"]
    a = load(tmp_path / "a")
    b = load(tmp_path / "b")
    assert a.content_digest == b.content_digest and a == b
    assert "content_digest" not in a.semantic_payload()
    with pytest.raises(KnowledgeError) as info:
        content_digest({"content_digest": "x"})
    assert info.value.code == "INVALID_DIGEST_PAYLOAD"


def test_03_digest_is_independent_of_yaml_order_and_formatting(tmp_path) -> None:
    nodes = fixture_nodes()
    base = load(tmp_path / "base", nodes)
    shuffled = list(reversed(copy.deepcopy(nodes)))
    for item in shuffled:                                  # key 順・alias 順・parent 順を入れ替える
        item["aliases"] = list(reversed(item["aliases"]))
        item["parent_slugs"] = list(reversed(item["parent_slugs"]))
        reordered = {k: item[k] for k in reversed(list(item))}
        item.clear()
        item.update(reordered)
    doc = document(shuffled)
    doc = {k: doc[k] for k in reversed(list(doc))}
    flow = yaml.safe_dump(doc, allow_unicode=True, sort_keys=True, default_flow_style=True)
    path = write(tmp_path / "flow", doc, text=flow)
    assert compute_taxonomy_digest(path) == base.content_digest
    changed = copy.deepcopy(nodes)
    changed[0]["label"] = "Artificial Intelligence"
    assert load(tmp_path / "changed", changed).content_digest != base.content_digest


def test_04_05_explicit_version_load_and_mismatch(tmp_path) -> None:
    path = write(tmp_path, document(fixture_nodes(), version="0.3.0"))
    snapshot = load_taxonomy_version(path, expected_version="0.3.0", cutoff=CUTOFF)
    assert snapshot.taxonomy_version == "0.3.0"
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(path, expected_version="0.2.0", cutoff=CUTOFF)
    assert info.value.code == "VERSION_MISMATCH"
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(path, expected_version="latest", cutoff=CUTOFF)
    assert info.value.code == "INVALID_VERSION"


def test_06_future_published_at_fails_closed(tmp_path) -> None:
    path = write(tmp_path, document(fixture_nodes(), published=T_020))
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(path, expected_version="0.1.0", cutoff=BETWEEN)
    assert info.value.code == "FUTURE_VERSION"
    assert load_taxonomy_version(path, expected_version="0.1.0", cutoff=T_020).taxonomy_version == "0.1.0"   # published == cutoff
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(path, expected_version="0.1.0", cutoff=datetime(2026, 9, 21))                # naive cutoff
    assert info.value.code == "INVALID_CUTOFF"


def test_07_past_snapshot_replays_old_identity_and_future_snapshot_is_invisible() -> None:
    old = load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=BETWEEN)
    assert "supply_chain_theme" in old.in_force_slugs() and old.node("supply_chain") is None
    assert resolve_taxonomy_token(old, "supply chain").slug == "supply_chain_theme"
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=BETWEEN)
    assert info.value.code == "FUTURE_VERSION"


# ---------------------------------------------------------------- 8〜14 graph rules


def test_08_duplicate_slug_fails(tmp_path) -> None:
    expect(tmp_path, "DUPLICATE_SLUG", fixture_nodes() + [node("ai", label="AI again")])


def test_09_duplicate_alias_ownership_fails(tmp_path) -> None:
    expect(tmp_path, "ALIAS_COLLISION", fixture_nodes() + [node("robotics", aliases=["ARTIFICIAL  INTELLIGENCE"])])
    expect(tmp_path, "ALIAS_COLLISION", fixture_nodes() + [node("robotics", aliases=["Power"])])      # alias が他 node の slug
    expect(tmp_path, "ALIAS_EQUALS_SLUG", [node("ai", aliases=["AI"])])
    expect(tmp_path, "ALIAS_DUPLICATE", [node("ai", aliases=["ａｉ chips", "ai chips"])])


def test_10_missing_parent_fails(tmp_path) -> None:
    expect(tmp_path, "MISSING_PARENT", fixture_nodes() + [node("cpo", parents=["optical"])])


def test_11_self_parent_fails(tmp_path) -> None:
    expect(tmp_path, "SELF_PARENT", [node("ai", parents=["ai"])])


def test_12_cycle_fails(tmp_path) -> None:
    expect(tmp_path, "CYCLE", [node("a", parents=["b"]), node("b", parents=["c"]), node("c", parents=["a"])])


def test_13_multi_parent_is_valid(tmp_path, v010) -> None:
    snapshot = load(tmp_path)
    assert snapshot.node("nuclear").parent_slugs == ("energy", "power")
    assert v010.node("nuclear").parent_slugs == ("energy", "power")
    assert snapshot.ancestors_of("nuclear") == ("energy", "power") and v010.ancestors_of("data_center") == ("ai",)


def test_14_no_parent_propagation(tmp_path) -> None:
    snapshot = load(tmp_path)
    resolved = resolve_taxonomy_token(snapshot, "data centre")
    assert resolved.slug == "data_center" and not hasattr(resolved, "parent_slugs") and resolved.candidates == ()
    validation = validate_theme_taxonomy_refs(snapshot, ["data_center"])
    assert validation.valid_slugs == ("data_center",)                         # ai は自動で付かない
    assert resolve_taxonomy_token(snapshot, "ai").slug == "ai"


# ---------------------------------------------------------------- 15〜20 normalization / lifecycle


def test_15_exact_slug(tmp_path) -> None:
    snapshot = load(tmp_path)
    for token in ("ai", "AI", "  Ai ", "ＡＩ"):
        resolved = resolve_taxonomy_token(snapshot, token)
        assert resolved.status is TaxonomyResolutionStatus.EXACT_SLUG and resolved.slug == "ai" and resolved.matched_by == "slug"
    assert normalize_token("ＡＩ") == "ai"


def test_16_exact_alias(tmp_path) -> None:
    resolved = resolve_taxonomy_token(load(tmp_path), "Artificial   Intelligence")
    assert resolved.status is TaxonomyResolutionStatus.EXACT_ALIAS and resolved.slug == "ai" and resolved.matched_by == "alias"


def test_17_unknown_and_no_substring_guessing(tmp_path) -> None:
    snapshot = load(tmp_path)
    for token in ("quantum", "artificial", "data", "ai chips", "nuclear power plant"):
        assert resolve_taxonomy_token(snapshot, token).status is TaxonomyResolutionStatus.UNKNOWN
    empty = resolve_taxonomy_token(snapshot, "   ")
    assert empty.status is TaxonomyResolutionStatus.UNKNOWN and empty.diagnostics == ("EMPTY_TOKEN",)
    with pytest.raises(KnowledgeError):
        resolve_taxonomy_token(snapshot, None)  # type: ignore[arg-type]


def test_18_deprecated_node_resolves_as_deprecated_with_successors(v020) -> None:
    resolved = resolve_taxonomy_token(v020, "supply_chain_theme")
    assert resolved.status is TaxonomyResolutionStatus.DEPRECATED and resolved.superseded_by == ("supply_chain",)
    assert resolved.diagnostics == ("DEPRECATED_IN:0.2.0",)
    moved = resolve_taxonomy_token(v020, "supply chain")
    assert moved.status is TaxonomyResolutionStatus.EXACT_ALIAS and moved.slug == "supply_chain"
    assert v020.node("supply_chain_theme") is not None                    # 歴史的に load 可能（削除しない）


def test_19_superseded_node_rules(tmp_path) -> None:
    ok = load(tmp_path / "ok", [node("new_name", since="0.2.0"), node("old_name", deprecated="0.2.0", superseded=["new_name"])],
              version="0.2.0")
    assert ok.node("old_name").is_deprecated and ok.node("old_name").superseded_by == ("new_name",)
    expect(tmp_path / "missing", "INVALID_SUPERSESSION", [node("old_name", deprecated="0.2.0", superseded=["ghost"])],
           version="0.2.0")
    expect(tmp_path / "nodep", "SUPERSESSION_WITHOUT_DEPRECATION", [node("new_name"), node("old_name", superseded=["new_name"])])
    expect(tmp_path / "chain", "INVALID_SUPERSESSION",
           [node("a", deprecated="0.2.0", superseded=["b"]), node("b", deprecated="0.2.0"), node("c")], version="0.2.0")
    expect(tmp_path / "parent", "DEPRECATED_PARENT", [node("old_name", deprecated="0.2.0"), node("child", parents=["old_name"])],
           version="0.2.0")
    expect(tmp_path / "self", "INVALID_SUPERSESSION", [node("a", deprecated="0.2.0", superseded=["a"])], version="0.2.0")
    expect(tmp_path / "future_dep", "FUTURE_DEPRECATION", [node("a", deprecated="0.9.0")])
    expect(tmp_path / "future_node", "FUTURE_NODE", [node("a", since="0.9.0")])
    expect(tmp_path / "lifecycle", "INVALID_LIFECYCLE", [node("a", since="0.2.0", deprecated="0.1.0")], version="0.2.0")


def test_20_rename_via_new_slug_across_published_versions(v010, v020) -> None:
    assert v010.node("supply_chain") is None and not v010.node("supply_chain_theme").is_deprecated
    assert v020.node("supply_chain").since_version == "0.2.0"
    assert v020.node("supply_chain_theme").deprecated_in_version == "0.2.0"
    assert validate_theme_taxonomy_refs(v010, ["supply_chain_theme"]).status is TaxonomyRefStatus.VALID
    stale = validate_theme_taxonomy_refs(v020, ["supply_chain_theme"])
    assert stale.status is TaxonomyRefStatus.INVALID and stale.deprecated_slugs == ("supply_chain_theme",)
    assert stale.diagnostics == ("SUPERSEDED:supply_chain_theme->supply_chain",)
    assert set(v010.slugs()) <= set(v020.slugs())                          # 削除による rename なし


# ---------------------------------------------------------------- 21〜23 loader fail closed


def test_21_unknown_fields_fail(tmp_path) -> None:
    related = fixture_nodes()
    related[0]["related"] = ["power"]
    expect(tmp_path / "node", "UNKNOWN_FIELD", related)
    expect(tmp_path / "top", "UNKNOWN_FIELD", extra={"notes": "x"})
    bad_prov = fixture_nodes()
    bad_prov[0]["provenance"]["source_page"] = "3"
    expect(tmp_path / "prov", "UNKNOWN_FIELD", bad_prov)


def test_22_unsupported_schema_fails(tmp_path) -> None:
    expect(tmp_path, "UNSUPPORTED_SCHEMA_VERSION", schema="theme_taxonomy:9.9.9")


def test_23_invalid_datetime_and_types_fail(tmp_path) -> None:
    expect(tmp_path / "naive", "INVALID_DATETIME", published="2026-09-20T00:00:00")
    expect(tmp_path / "garbage", "INVALID_DATETIME", published="not-a-date")
    expect(tmp_path / "int", "INVALID_DATETIME", published=20260920)  # type: ignore[arg-type]
    typed = fixture_nodes()
    typed[0]["aliases"] = "artificial intelligence"
    expect(tmp_path / "type", "INVALID_TYPE", typed)
    typed = fixture_nodes()
    typed[0]["since_version"] = 0.1
    expect(tmp_path / "version", "INVALID_TYPE", typed)                        # YAML の数値 0.1 は str ではない
    typed = fixture_nodes()
    typed[0]["since_version"] = "1.0"
    expect(tmp_path / "semver", "INVALID_VERSION", typed)
    text = yaml.safe_dump(document(fixture_nodes(), digest="0" * 64), allow_unicode=True, sort_keys=False)
    dup = write(tmp_path / "dup", {}, text=text.replace("taxonomy_version: 0.1.0", "taxonomy_version: 0.1.0\ntaxonomy_version: 0.1.0"))
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(dup, expected_version="0.1.0", cutoff=CUTOFF)
    assert info.value.code == "DUPLICATE_KEY"
    wrong = write(tmp_path / "digest", document(fixture_nodes(), digest="0" * 64), sign=False)
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(wrong, expected_version="0.1.0", cutoff=CUTOFF)
    assert info.value.code == "DIGEST_MISMATCH"
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(tmp_path / "missing.yaml", expected_version="0.1.0", cutoff=CUTOFF)
    assert info.value.code == "FILE_MISSING"
    with pytest.raises(KnowledgeError) as info:
        knowledge_path(KNOWLEDGE_ROOT, "taxonomy", "1.0")
    assert info.value.code == "INVALID_VERSION"


# ---------------------------------------------------------------- 24 Foundation METADATA TAXONOMY 値検証（純・書かない）


def test_24_theme_taxonomy_ref_validation_is_pure_and_writes_nothing(tmp_path, v020) -> None:
    before = sorted(p.name for p in (KNOWLEDGE_ROOT / "theme_intelligence").iterdir())
    ok = validate_theme_taxonomy_refs(v020, ("ai", "data_center", "nuclear"))
    assert ok.status is TaxonomyRefStatus.VALID and ok.valid_slugs == ("ai", "data_center", "nuclear")
    assert MetadataField.TAXONOMY in SET_VALUED_METADATA_FIELDS                # 複数 slug は Foundation 側でも set 値
    bad = validate_theme_taxonomy_refs(v020, ["ai", "ai", "quantum", "supply_chain_theme", " power", ""])
    assert bad.status is TaxonomyRefStatus.INVALID
    assert bad.duplicate_slugs == ("ai",) and bad.unknown_slugs == ("quantum",) and bad.deprecated_slugs == ("supply_chain_theme",)
    assert bad.malformed_values == ("", " power")
    assert validate_theme_taxonomy_refs(v020, ["artificial intelligence"]).unknown_slugs == ("artificial intelligence",)  # alias 不可
    assert validate_theme_taxonomy_refs(v020, []).status is TaxonomyRefStatus.INVALID
    assert sorted(p.name for p in (KNOWLEDGE_ROOT / "theme_intelligence").iterdir()) == before
    assert not list(tmp_path.iterdir())


def test_model_construction_direct_and_provenance_rules() -> None:
    provenance = KnowledgeProvenance(origin=KnowledgeOrigin.MVP_FIXTURE, approver_ref="role:test", reason="ok")
    made = TaxonomyNode(slug="ai", label="AI", description="d", since_version="0.1.0", provenance=provenance,
                        aliases=("Zeta", "alpha"))
    assert made.aliases == ("alpha", "Zeta") and not made.is_deprecated
    with pytest.raises(KnowledgeError) as info:
        KnowledgeProvenance(origin=KnowledgeOrigin.MVP_FIXTURE, approver_ref="role:test", reason="see X:\\share\\doc")
    assert info.value.code == "PROHIBITED_CONTENT"
    with pytest.raises(KnowledgeError) as info:
        TaxonomyNode(slug="Bad-Slug", label="x", description="d", since_version="0.1.0", provenance=provenance)
    assert info.value.code == "INVALID_SLUG"
