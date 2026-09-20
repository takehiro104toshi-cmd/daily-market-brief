"""P6-B4B — Entity catalog versioned knowledge（test matrix 25〜50 ＋ 補助）。

公開 snapshot（0.1.0 / 0.2.0）と tmp_path fixture で、version / cutoff / digest の gate、entity identity（`<kind>:<slug>`）、
9 entity type の Foundation 写像、alias 解決（safe / context / AMBIGUOUS）、identifier、corporate action、PIT を固定する。
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.intelligence.theme_intelligence.entity_catalog import (EntityResolutionStatus, compute_entity_catalog_digest,
                                                                entity_catalog_path, load_entity_catalog_version,
                                                                resolve_entity_token)
from src.intelligence.theme_intelligence.entity_model import (ENTITY_CATALOG_SCHEMA_VERSION, FOUNDATION_KIND_BY_ENTITY_TYPE,
                                                              IDENTIFIER_TYPES_BY_ENTITY_TYPE, EntityCatalogSnapshot,
                                                              EntityIdentifier, EntityRecord, EntityType, IdentifierType,
                                                              entity_id_prefix, foundation_entity_kind, split_entity_id)
from src.intelligence.theme_intelligence.knowledge_loader import KnowledgeError, KnowledgeOrigin, KnowledgeProvenance, content_digest
from src.intelligence.themes.fingerprint import identity_core_fingerprint
from src.intelligence.themes.model import ComponentType, ThemeEntityKind

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
T_010 = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
T_020 = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)
BETWEEN = datetime(2026, 9, 20, 0, 30, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 9, 21, tzinfo=timezone.utc)
GOLDEN = {"0.1.0": "6f2d43c92f8f4c790b781fae55d00f6b9af6b5e29a3fe2279d3a6e58f81e73ba",
          "0.2.0": "63a23fcadc1f8468bc5a64ca5e1672aa7c3d05873f682bfc0b30b8775327f863"}
S = EntityResolutionStatus


# ---------------------------------------------------------------- helpers


def prov(origin: str = "MVP_FIXTURE", reason: str = "fixture entity") -> dict:
    return {"origin": origin, "approver_ref": "role:test", "reason": reason}


def ident(kind: str, value: str, scheme: str = "", *, valid_from=None, valid_to=None) -> dict:
    data = {"identifier_type": kind, "value": value}
    if scheme:
        data["scheme"] = scheme
    if valid_from:
        data["valid_from"] = valid_from
    if valid_to:
        data["valid_to"] = valid_to
    return data


def entity(entity_id: str, entity_type: str, name: str, *, safe=(), context=(), terms=(), identifiers=(), attributes=None,
           valid_from=None, valid_to=None, superseded=(), since="0.1.0", retired="") -> dict:
    data = {"entity_id": entity_id, "entity_type": entity_type, "canonical_name": name, "aliases_safe": list(safe),
            "aliases_context": list(context), "context_terms": list(terms), "identifiers": list(identifiers),
            "provenance": prov(), "since_version": since}
    if attributes:
        data["attributes"] = dict(attributes)
    if valid_from:
        data["valid_from"] = valid_from
    if valid_to:
        data["valid_to"] = valid_to
    if superseded:
        data["superseded_by"] = list(superseded)
    if retired:
        data["retired_in_version"] = retired
    return data


def fixture_entities() -> list:
    return [
        entity("country:jp", "COUNTRY", "Japan", safe=["japan"], identifiers=[ident("ISO_COUNTRY", "JP")]),
        entity("central_bank:boj", "CENTRAL_BANK", "Bank of Japan", safe=["bank of japan", "boj"], attributes={"country": "country:jp"}),
        entity("company:alpha_works", "COMPANY", "Alpha Works", safe=["alpha works"], context=["alpha"], terms=["works", "factory"],
               identifiers=[ident("TICKER", "ALW1", "XMVP")], valid_from="2000-01-01"),
        entity("company:alpha_labs", "COMPANY", "Alpha Labs", safe=["alpha labs"], context=["alpha"], terms=["labs", "research"],
               identifiers=[ident("TICKER", "ALL1", "XMVP")], valid_from="2001-01-01"),
    ]


def document(entities, *, version="0.1.0", published=T_010, digest="", schema=ENTITY_CATALOG_SCHEMA_VERSION, extra=None) -> dict:
    doc = {"schema_version": schema, "catalog_version": version,
           "published_at": published.isoformat() if isinstance(published, datetime) else published,
           "content_digest": digest, "entities": entities}
    if extra:
        doc.update(extra)
    return doc


def write(tmp_path: Path, doc: dict, name: str = "catalog.yaml", *, sign: bool = True, text: str = None) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if sign and text is None and not doc.get("content_digest"):
        signed = dict(doc, content_digest=compute_entity_catalog_digest(path))
        path.write_text(yaml.safe_dump(signed, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load(tmp_path: Path, entities=None, *, version="0.1.0", cutoff=CUTOFF, **kw) -> EntityCatalogSnapshot:
    path = write(tmp_path, document(entities if entities is not None else fixture_entities(), version=version, **kw))
    return load_entity_catalog_version(path, expected_version=version, cutoff=cutoff)


def expect(tmp_path: Path, code: str, entities=None, **kw) -> None:
    with pytest.raises(KnowledgeError) as info:
        load(tmp_path, entities, **kw)
    assert info.value.code == code, (info.value.code, str(info.value))


@pytest.fixture(scope="module")
def c010() -> EntityCatalogSnapshot:
    return load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=CUTOFF)


@pytest.fixture(scope="module")
def c020() -> EntityCatalogSnapshot:
    return load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUTOFF)


# ---------------------------------------------------------------- 25〜28 snapshot / digest / version


def test_25_canonical_published_catalogs_load_and_match_golden_digests(c010, c020) -> None:
    assert entity_catalog_path(KNOWLEDGE_ROOT, "0.2.0") == KNOWLEDGE_ROOT / "theme_intelligence" / "entity_catalog.0.2.0.yaml"
    assert c010.content_digest == GOLDEN["0.1.0"] and c020.content_digest == GOLDEN["0.2.0"]
    assert c010.entities == tuple(sorted(c010.entities, key=lambda e: e.entity_id))
    kinds = {e.entity_type for e in c010.entities}
    assert kinds == set(EntityType)                                        # 9 種すべてを MVP seed が例示する
    assert all(e.provenance.origin in (KnowledgeOrigin.PUBLIC_STANDARD, KnowledgeOrigin.SUPERVISOR_DECISION,
                                       KnowledgeOrigin.MVP_FIXTURE) for e in c020.entities)
    assert all(e.provenance.origin is KnowledgeOrigin.MVP_FIXTURE for e in c020.entities if e.entity_type is EntityType.COMPANY)


def test_26_digest_is_deterministic_and_order_independent(tmp_path, c010) -> None:
    assert content_digest(c010.semantic_payload()) == c010.content_digest
    base = load(tmp_path / "base")
    shuffled = list(reversed(copy.deepcopy(fixture_entities())))
    for item in shuffled:
        for key in ("aliases_safe", "context_terms", "identifiers"):
            item[key] = list(reversed(item[key]))
        reordered = {k: item[k] for k in reversed(list(item))}
        item.clear()
        item.update(reordered)
    doc = document(shuffled)
    path = write(tmp_path / "flow", doc, text=yaml.safe_dump(doc, allow_unicode=True, sort_keys=True, default_flow_style=True))
    assert compute_entity_catalog_digest(path) == base.content_digest
    renamed = copy.deepcopy(fixture_entities())
    renamed[0]["canonical_name"] = "Nippon"
    assert load(tmp_path / "renamed", renamed).content_digest != base.content_digest


def test_27_explicit_version_load(tmp_path) -> None:
    path = write(tmp_path, document(fixture_entities(), version="1.4.2"))
    assert load_entity_catalog_version(path, expected_version="1.4.2", cutoff=CUTOFF).catalog_version == "1.4.2"
    with pytest.raises(KnowledgeError) as info:
        load_entity_catalog_version(path, expected_version="1.4.3", cutoff=CUTOFF)
    assert info.value.code == "VERSION_MISMATCH"


def test_28_future_version_fails(tmp_path) -> None:
    path = write(tmp_path, document(fixture_entities(), published=T_020))
    with pytest.raises(KnowledgeError) as info:
        load_entity_catalog_version(path, expected_version="0.1.0", cutoff=BETWEEN)
    assert info.value.code == "FUTURE_VERSION"
    with pytest.raises(KnowledgeError) as info:
        load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=BETWEEN)
    assert info.value.code == "FUTURE_VERSION"


# ---------------------------------------------------------------- 29〜33 resolution


def test_29_exact_id(c010) -> None:
    resolved = resolve_entity_token(c010, "central_bank:boj")
    assert resolved.status is S.EXACT_ID and resolved.entity_id == "central_bank:boj" and resolved.matched_by == "id"
    assert resolve_entity_token(c010, " CENTRAL_BANK:BOJ ").status is S.EXACT_ID


def test_30_safe_alias(c010) -> None:
    for token in ("Bank of Japan", "BOJ", "日銀", "日本銀行"):
        resolved = resolve_entity_token(c010, token)
        assert resolved.status is S.EXACT_SAFE_ALIAS and resolved.entity_id == "central_bank:boj", token
    assert resolve_entity_token(c010, "日経平均").entity_id == "index:nikkei225"
    assert resolve_entity_token(c010, "bank").status is S.UNKNOWN                # 部分一致なし


def test_31_context_alias_with_context(c010) -> None:
    resolved = resolve_entity_token(c010, "Fed", context=["FOMC", "statement"])
    assert resolved.status is S.CONTEXT_ALIAS and resolved.entity_id == "central_bank:fed"
    assert resolved.matched_by == "context_alias" and resolved.matched_context_terms == ("fomc",)
    assert resolve_entity_token(c010, "dollar", context=["fx"]).entity_id == "currency:usd"


def test_32_context_alias_without_context_does_not_resolve(c010) -> None:
    for context in (None, [], ["earnings", "guidance"]):
        resolved = resolve_entity_token(c010, "fed", context=context)
        assert resolved.status is S.UNKNOWN and resolved.entity_id == "" and resolved.candidates == ()
    assert resolve_entity_token(c010, "fed").diagnostics == ("CONTEXT_REQUIRED",)
    assert resolve_entity_token(c010, "fed", context=["earnings"]).diagnostics == ("CONTEXT_NOT_MATCHED",)
    with pytest.raises(KnowledgeError) as info:
        resolve_entity_token(c010, "fed", context="fomc")                           # 単一 str は sequence ではない
    assert info.value.code == "INVALID_TYPE"


def test_33_alias_ambiguity_returns_ambiguous_never_first(c020, tmp_path) -> None:
    resolved = resolve_entity_token(c020, "Example", context=["motors", "battery"])
    assert resolved.status is S.AMBIGUOUS and resolved.entity_id == ""
    assert resolved.candidates == ("company:example_battery", "company:example_motors")
    assert resolve_entity_token(c020, "example", context=["battery"]).entity_id == "company:example_battery"
    assert resolve_entity_token(c020, "example", context=["mobility"]).entity_id == "company:example_motors"
    fixture = load(tmp_path)
    assert resolve_entity_token(fixture, "alpha", context=["works", "labs"]).status is S.AMBIGUOUS
    expect(tmp_path / "collision", "SAFE_ALIAS_COLLISION", fixture_entities() + [entity("index:boj_index", "INDEX", "X", safe=["BOJ"])])
    expect(tmp_path / "shadow", "CONTEXT_ALIAS_SHADOWED", fixture_entities() + [entity("index:alpha_index", "INDEX", "X", safe=["alpha"])])
    expect(tmp_path / "terms", "CONTEXT_TERMS_REQUIRED", [entity("country:jp", "COUNTRY", "Japan", context=["nippon"])])
    expect(tmp_path / "same_ns", "ALIAS_DUPLICATE", [entity("country:jp", "COUNTRY", "Japan", safe=["japan"], context=["JAPAN"], terms=["x"])])


# ---------------------------------------------------------------- 34〜38 lifecycle / corporate action / PIT


def test_34_canonical_rename_keeps_entity_id_across_versions(c010, c020) -> None:
    assert c010.entity("company:example_motors").canonical_name == "Example Motors"
    assert c020.entity("company:example_motors").canonical_name == "Example Mobility"
    assert resolve_entity_token(c020, "example motors").entity_id == "company:example_motors"    # 旧名も alias として残る
    assert resolve_entity_token(c010, "example mobility").status is S.UNKNOWN


def test_35_ticker_change_keeps_entity_id(c010, c020) -> None:
    old = c010.entity("company:example_motors").identifiers
    new = c020.entity("company:example_motors").identifiers
    assert [i.value for i in old] == ["EXM1"] and old[0].valid_to is None
    assert [(i.value, i.valid_from, i.valid_to) for i in new] == [("EXM1", None, date(2026, 7, 1)), ("EXM2", date(2026, 7, 1), None)]
    assert all(i.identifier_type is IdentifierType.TICKER and i.scheme == "XMVP" for i in new)


def test_36_merger_superseded(c020) -> None:
    old = c020.entity("company:example_battery")
    assert old.valid_to == date(2026, 9, 1) and old.superseded_by == ("company:example_energy_systems",)
    before = resolve_entity_token(c020, "example battery", as_of=date(2026, 8, 31))
    assert before.status is S.EXACT_SAFE_ALIAS and before.entity_id == "company:example_battery"
    after = resolve_entity_token(c020, "example battery", as_of=datetime(2026, 9, 2, tzinfo=timezone.utc))
    assert after.status is S.SUPERSEDED and after.entity_id == "company:example_battery"
    assert after.superseded_by == ("company:example_energy_systems",) and after.diagnostics == ("VALID_TO:2026-09-01",)
    assert resolve_entity_token(c020, "example battery").status is S.EXACT_SAFE_ALIAS       # as_of なし ＝ 有効性判定なし
    successor = c020.entity("company:example_energy_systems")
    assert successor.since_version == "0.2.0" and successor.valid_from == date(2026, 9, 1)


def test_37_split_creates_new_ids(tmp_path) -> None:
    entities = fixture_entities() + [
        entity("company:omega_group", "COMPANY", "Omega Group", safe=["omega group"], valid_from="1990-01-01", valid_to="2026-01-01",
               superseded=["company:omega_energy", "company:omega_retail"]),
        entity("company:omega_energy", "COMPANY", "Omega Energy", safe=["omega energy"], valid_from="2026-01-01", since="0.1.0"),
        entity("company:omega_retail", "COMPANY", "Omega Retail", safe=["omega retail"], valid_from="2026-01-01", since="0.1.0"),
    ]
    snapshot = load(tmp_path, entities)
    old = resolve_entity_token(snapshot, "omega group", as_of=date(2026, 3, 1))
    assert old.status is S.SUPERSEDED and old.superseded_by == ("company:omega_energy", "company:omega_retail")
    assert resolve_entity_token(snapshot, "omega group", as_of=date(2025, 12, 31)).status is S.EXACT_SAFE_ALIAS
    early = resolve_entity_token(snapshot, "omega energy", as_of=date(2025, 12, 31))
    assert early.status is S.INACTIVE and early.diagnostics == ("VALID_FROM:2026-01-01",)
    assert {e.entity_id for e in snapshot.entities} >= {"company:omega_group", "company:omega_energy", "company:omega_retail"}


def test_38_old_cutoff_preserves_old_identity() -> None:
    old = load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=BETWEEN)
    assert old.entity("company:example_motors").canonical_name == "Example Motors"
    assert old.entity("company:example_battery").valid_to is None and old.entity("company:example_energy_systems") is None
    assert resolve_entity_token(old, "example battery", as_of=date(2026, 9, 2)).status is S.EXACT_SAFE_ALIAS


# ---------------------------------------------------------------- 39〜44 identifiers / entity types


def test_39_identifier_collision_fails_unless_disjoint_ticker_reuse(tmp_path) -> None:
    expect(tmp_path / "ticker", "IDENTIFIER_COLLISION", fixture_entities() + [
        entity("company:beta", "COMPANY", "Beta", safe=["beta"], identifiers=[ident("TICKER", "ALW1", "XMVP")])])
    reuse = load(tmp_path / "reuse", fixture_entities() + [
        entity("company:beta", "COMPANY", "Beta", safe=["beta"], identifiers=[ident("TICKER", "ZZ99", "XMVP", valid_to="2020-01-01")]),
        entity("company:gamma", "COMPANY", "Gamma", safe=["gamma"], identifiers=[ident("TICKER", "ZZ99", "XMVP", valid_from="2020-01-01")])])
    assert reuse.entity("company:gamma").identifiers[0].valid_from == date(2020, 1, 1)
    expect(tmp_path / "open_ended", "IDENTIFIER_COLLISION", fixture_entities() + [
        entity("company:beta", "COMPANY", "Beta", safe=["beta"], identifiers=[ident("TICKER", "ZZ99", "XMVP")]),
        entity("company:gamma", "COMPANY", "Gamma", safe=["gamma"], identifiers=[ident("TICKER", "ZZ99", "XMVP", valid_from="2020-01-01")])])
    expect(tmp_path / "iso", "IDENTIFIER_COLLISION", fixture_entities() + [
        entity("country:jpn_dup", "COUNTRY", "Japan dup", safe=["nippon"], identifiers=[ident("ISO_COUNTRY", "JP", valid_to="2000-01-01")])])
    expect(tmp_path / "type", "INVALID_IDENTIFIER_TYPE", [entity("country:jp", "COUNTRY", "Japan", identifiers=[ident("TICKER", "JP", "X")])])
    expect(tmp_path / "scheme", "MISSING_FIELD", [entity("company:x", "COMPANY", "X", identifiers=[ident("TICKER", "X1")])])
    expect(tmp_path / "iso_fmt", "INVALID_IDENTIFIER", [entity("currency:x", "CURRENCY", "X", identifiers=[ident("ISO_CURRENCY", "xyz")])])
    expect(tmp_path / "dup", "IDENTIFIER_DUPLICATE", [entity("company:x", "COMPANY", "X", identifiers=[ident("TICKER", "X1", "A"), ident("TICKER", "X1", "A")])])


def test_40_invalid_entity_kind_fails(tmp_path) -> None:
    expect(tmp_path / "vocab", "INVALID_VOCABULARY", [entity("company:x", "OTHER", "X")])
    expect(tmp_path / "prefix", "INVALID_ENTITY_ID", [entity("equity:x", "COMPANY", "X")])
    expect(tmp_path / "mismatch", "ENTITY_ID_KIND_MISMATCH", [entity("index:x", "COMPANY", "X")])
    expect(tmp_path / "slug", "INVALID_ENTITY_ID", [entity("company:Bad-Slug", "COMPANY", "X")])
    expect(tmp_path / "slug_collision", "SLUG_COLLISION", [entity("company:jp", "COMPANY", "X"), entity("country:jp", "COUNTRY", "Japan")])


@pytest.mark.parametrize("kind", ["PERSON", "TICKER", "TECHNOLOGY", "POLICY_PROGRAM"])
def test_41_44_excluded_entity_types_are_rejected(tmp_path, kind) -> None:
    assert kind not in EntityType.__members__
    expect(tmp_path, "INVALID_VOCABULARY", [entity(f"{kind.lower()}:x", kind, "X")])
    with pytest.raises(KnowledgeError) as info:
        split_entity_id(f"{kind.lower()}:x", where="t")
    assert info.value.code == "INVALID_ENTITY_ID"


# ---------------------------------------------------------------- 45〜50 no rewrite / loader / lifecycle / mapping


def test_45_no_automatic_theme_subject_rewrite(c020) -> None:
    """entity の supersession は Theme subject の typed_reference を書き換えない: 旧 id は旧 identity core のまま。"""
    class _Subject:
        def __init__(self, ref: str) -> None:
            self.normalized_subject, self.typed_reference = "battery makers", ref

    class _Component:
        def __init__(self, component_type: ComponentType, category: str) -> None:
            self.component_type, self.category, self.typed_reference, self.normalized_statement = component_type, category, "", ""

    class _Mechanism:
        drivers = (_Component(ComponentType.DRIVER, "DEMAND_SHIFT"),)
        channels = (_Component(ComponentType.TRANSMISSION_CHANNEL, "VOLUME_DEMAND"),)
        domains = (_Component(ComponentType.AFFECTED_DOMAIN, "INDUSTRY"),)

    class _Observation:
        def __init__(self, ref: str) -> None:
            self.subject, self.mechanism, self.scope = _Subject(ref), _Mechanism(), ()

    old_core = identity_core_fingerprint(_Observation("company:example_battery"))
    new_core = identity_core_fingerprint(_Observation("company:example_energy_systems"))
    assert old_core != new_core                                                   # id 変更 ＝ NEW_ROOT_REQUIRED 領域
    resolved = resolve_entity_token(c020, "company:example_battery", as_of=date(2026, 10, 1))
    assert resolved.status is S.SUPERSEDED and resolved.entity_id == "company:example_battery"   # 後継へ付け替えない
    import src.intelligence.theme_intelligence.entity_catalog as module
    assert not [n for n in dir(module) if "rewrite" in n.lower() or "migrate" in n.lower() or "latest" in n.lower()]


def test_46_unknown_field_fails(tmp_path) -> None:
    extra = fixture_entities()
    extra[0]["ticker"] = "JP"
    expect(tmp_path / "entity", "UNKNOWN_FIELD", extra)
    bad_ident = fixture_entities()
    bad_ident[2]["identifiers"][0]["exchange"] = "TSE"
    expect(tmp_path / "identifier", "UNKNOWN_FIELD", bad_ident)
    expect(tmp_path / "top", "UNKNOWN_FIELD", extra={"watch": []})


def test_47_digest_mismatch_fails(tmp_path) -> None:
    path = write(tmp_path, document(fixture_entities(), digest="f" * 64), sign=False)
    with pytest.raises(KnowledgeError) as info:
        load_entity_catalog_version(path, expected_version="0.1.0", cutoff=CUTOFF)
    assert info.value.code == "DIGEST_MISMATCH"
    good = write(tmp_path / "good", document(fixture_entities()))
    tampered = good.read_text(encoding="utf-8").replace("Bank of Japan", "Bank of Japon")
    (tmp_path / "good" / "tampered.yaml").write_text(tampered, encoding="utf-8")
    with pytest.raises(KnowledgeError) as info:
        load_entity_catalog_version(tmp_path / "good" / "tampered.yaml", expected_version="0.1.0", cutoff=CUTOFF)
    assert info.value.code == "DIGEST_MISMATCH"


def test_48_invalid_validity_interval_fails(tmp_path) -> None:
    expect(tmp_path / "entity", "INVALID_INTERVAL", [entity("company:x", "COMPANY", "X", valid_from="2020-01-01", valid_to="2019-12-31")])
    expect(tmp_path / "equal", "INVALID_INTERVAL", [entity("company:x", "COMPANY", "X", valid_from="2020-01-01", valid_to="2020-01-01")])
    expect(tmp_path / "identifier", "INVALID_INTERVAL", [entity("company:x", "COMPANY", "X", identifiers=[
        ident("TICKER", "X1", "A", valid_from="2020-01-01", valid_to="2019-01-01")])])
    expect(tmp_path / "date", "INVALID_DATE", [entity("company:x", "COMPANY", "X", valid_from="2020-13-01")])
    expect(tmp_path / "datetime", "INVALID_DATE", [entity("company:x", "COMPANY", "X", valid_from="2020-01-01T00:00:00+00:00")])
    with pytest.raises(KnowledgeError) as info:
        resolve_entity_token(load(tmp_path / "ok"), "japan", as_of=datetime(2026, 1, 1))                  # naive as_of
    assert info.value.code == "INVALID_AS_OF"


def test_49_superseded_target_invalid_fails(tmp_path) -> None:
    expect(tmp_path / "missing", "INVALID_SUPERSESSION", [entity("company:x", "COMPANY", "X", valid_to="2020-01-01", superseded=["company:ghost"])])
    expect(tmp_path / "self", "INVALID_SUPERSESSION", [entity("company:x", "COMPANY", "X", valid_to="2020-01-01", superseded=["company:x"])])
    expect(tmp_path / "no_end", "SUPERSESSION_WITHOUT_END", [entity("company:x", "COMPANY", "X", superseded=["company:y"]),
                                                             entity("company:y", "COMPANY", "Y")])
    expect(tmp_path / "attr", "DANGLING_ATTRIBUTE_REF", [entity("company:x", "COMPANY", "X", attributes={"country": "country:zz"})])
    expect(tmp_path / "future", "FUTURE_ENTITY", [entity("company:x", "COMPANY", "X", since="0.9.0")])
    retired = load(tmp_path / "retired", [entity("company:x", "COMPANY", "X", safe=["ex corp"], retired="0.1.0")])
    resolved = resolve_entity_token(retired, "ex corp")
    assert resolved.status is S.INACTIVE and resolved.diagnostics == ("RETIRED_IN:0.1.0",)


def test_50_foundation_kind_mapping_is_exact() -> None:
    assert set(EntityType.__members__) == {"COMPANY", "INDEX", "SECTOR", "INDUSTRY", "COMMODITY", "CURRENCY", "COUNTRY",
                                           "CENTRAL_BANK", "GOVERNMENT"}
    for entity_type in EntityType:
        kind = foundation_entity_kind(entity_type)
        assert isinstance(kind, ThemeEntityKind) and kind.name == entity_type.name
        assert entity_id_prefix(entity_type) == kind.value + ":"
        assert entity_type in IDENTIFIER_TYPES_BY_ENTITY_TYPE
    mapped = set(FOUNDATION_KIND_BY_ENTITY_TYPE.values())
    assert len(mapped) == len(EntityType) == 9                                     # 単射
    assert set(ThemeEntityKind) - mapped == {ThemeEntityKind.PERSON, ThemeEntityKind.TICKER}   # 意図的に写像しない 2 種
    assert split_entity_id("central_bank:boj", where="t") == (EntityType.CENTRAL_BANK, "boj")
    record = EntityRecord(entity_id="index:x", entity_type=EntityType.INDEX, canonical_name="X", since_version="0.1.0",
                          provenance=KnowledgeProvenance(origin=KnowledgeOrigin.MVP_FIXTURE, approver_ref="role:test", reason="r"),
                          identifiers=(EntityIdentifier(identifier_type=IdentifierType.INSTRUMENT_ID, value="index:x"),))
    assert record.foundation_kind is ThemeEntityKind.INDEX and record.slug == "x"
