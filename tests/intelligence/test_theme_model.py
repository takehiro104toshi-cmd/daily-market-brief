"""P6-A4a — Theme foundation model: record 型・語彙・canonical 直列化・collection 順序独立・metadata / mapping の分離。

fixture builder は他の theme test（identity / evidence / governance）からも import される。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.core.ids import content_id
from src.intelligence.themes import model as M
from src.intelligence.themes.model import (
    AssertionProvenance, ComponentType, CreationMethod, EntityLinkClass, EntityRef, EvidenceAttachment,
    EvidenceAuthorityClass, EvidenceKind, EvidenceRole, EvidenceTimeBasis, EvidenceTimeQuality, ExpectedChange,
    ExpectedConsequence, ExpectedRelation, GovernanceEventType, InferredExposureLink, InvalidationCondition,
    Limitation, LimitationCategory, MappingRole, Mechanism, MechanismCertainty, MechanismComponent, MetadataField,
    ObservationProvenance, OriginKind, ProvenanceClass, ScopeDimension, ScopeToken, SourceOrigin, ThemeEntityKind,
    ThemeGovernanceEvent, ThemeMetadataRecord, ThemeModelError, ThemeObservation, ThemeRootRecord,
    ThemeSeriesMapping, ThemeSubject, canonical_json, canonical_line, is_root_id, new_root_id, record_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
T0 = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
ROOT_A = "theme_0123456789ABCDEFGHJKMNPQRS"
ROOT_B = "theme_0123456789ABCDEFGHJKMNPQRT"
ROOT_C = "theme_0123456789ABCDEFGHJKMNPQRV"
FACT_A = "fact_" + "a" * 24
FACT_B = "fact_" + "b" * 24
OBS_X = "obs_" + "0" * 24
DOC_C = "doc_" + "c" * 24
NEWS_D = "news_" + "d" * 24


# ---------------------------------------------------------------- builders

def component(component_type=ComponentType.DRIVER, key="d1", category="FX_RATE", typed_reference="fx:USDJPY",
              statement="", provenance=AssertionProvenance.HUMAN, provenance_ref=""):
    return MechanismComponent(component_type=component_type, component_key=key, category=category,
                              typed_reference=typed_reference, normalized_statement=statement,
                              assertion_provenance=provenance, provenance_ref=provenance_ref)


def consequence(key="c1", category="EARNINGS_METRIC", target="sector:s17:05.margin",
                change=ExpectedChange.DECREASE, statement="", provenance=AssertionProvenance.HUMAN,
                provenance_ref=""):
    return ExpectedConsequence(component_key=key, category=category, observable_target=target, expected_change=change,
                               normalized_statement=statement, assertion_provenance=provenance,
                               provenance_ref=provenance_ref)


def mechanism(drivers=None, channels=None, domains=None, consequences=None):
    return Mechanism(
        drivers=(component(),) if drivers is None else drivers,
        channels=((component(ComponentType.TRANSMISSION_CHANNEL, "ch1", "INPUT_COST", ""),)
                  if channels is None else channels),
        domains=((component(ComponentType.AFFECTED_DOMAIN, "dom1", "SECTOR", "sector:s17:05"),)
                 if domains is None else domains),
        consequences=(consequence(),) if consequences is None else consequences)


def subject(text="yen weakness and import input cost", ref="fx:USDJPY"):
    return ThemeSubject(normalized_subject=text, typed_reference=ref)


def scope(frame="multi_quarter", region="jp"):
    return (ScopeToken(dimension=ScopeDimension.REGION, value=region),
            ScopeToken(dimension=ScopeDimension.PERIOD_FRAME, value=frame))


def condition(key="inv1", text="margins expand despite weak yen"):
    return InvalidationCondition(condition_key=key, normalized_statement=text)


def limitation(text="hedging ratios unknown", category=LimitationCategory.CONFOUNDER):
    return Limitation(category=category, normalized_statement=text)


def origin(kind=OriginKind.MARKET_SERIES, key="series:jquants/index:topix.close", source_ids=("jquants",),
           lineage=(), publisher=""):
    return SourceOrigin(origin_kind=kind, origin_key=key, source_ids=source_ids, lineage_refs=lineage,
                        publisher=publisher)


def attachment(ref=FACT_A, kind=EvidenceKind.FACT, *, src=None, day="2026-08-20", role=EvidenceRole.SUPPORTS,
               cref="c1", provenance=ProvenanceClass.RULE, asserted_by="rule:R1@1", quality=EvidenceTimeQuality.RELIABLE,
               basis=None, attached=T0, evidence_time=None, **kw):
    missing = quality is EvidenceTimeQuality.MISSING
    if evidence_time is None and not missing:
        evidence_time = datetime.fromisoformat(day).replace(tzinfo=UTC)
    return EvidenceAttachment(
        evidence_kind=kind, authority_class=kw.pop("authority_class", EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL),
        ref_id=ref, source_origin=src or origin(),
        evidence_time=None if missing else evidence_time,
        evidence_time_basis=EvidenceTimeBasis.NONE if missing else (basis or M.EVIDENCE_TIME_BASIS_BY_KIND[kind][0]),
        evidence_time_quality=quality, evidence_date="" if missing else day, attached_at=attached, role=role,
        role_provenance=provenance, role_asserted_by=asserted_by, consequence_ref=cref, **kw)


def provenance(writer=ProvenanceClass.HUMAN, ref="reviewer:r1", reason="draft", governance_event_id="", dropped=()):
    return ObservationProvenance(writer_class=writer, writer_ref=ref, reason=reason,
                                 governance_event_id=governance_event_id, dropped_attachments=dropped)


def observation(**override) -> ThemeObservation:
    kwargs = dict(root_id=ROOT_A, previous_observation_id="", subject=subject(), mechanism=mechanism(),
                  certainty_class=MechanismCertainty.HYPOTHESIZED_MECHANISM, scope=scope(),
                  limitations=(limitation(),), invalidation_conditions=(condition(),), inferred_links=(),
                  attachments=(attachment(FACT_A, day="2026-08-20"), attachment(FACT_B, day="2026-08-21")),
                  provenance=provenance(), recorded_at=T0 + timedelta(hours=1))
    kwargs.update(override)
    return ThemeObservation.build(**kwargs)


def root_record(obs=None, **override) -> ThemeRootRecord:
    obs = obs or observation()
    kwargs = dict(root_id=obs.root_id, created_at=T0, creation_method=CreationMethod.CANDIDATE,
                  creator_class=ProvenanceClass.HUMAN, creation_provenance="reviewer:r1",
                  genesis_observation_id=obs.observation_id, origin_event_id="")
    kwargs.update(override)
    return ThemeRootRecord(**kwargs)


def event(**override) -> ThemeGovernanceEvent:
    kwargs = dict(event_type=GovernanceEventType.CANDIDATE_ACCEPTED, subject_roots=(ROOT_A,), reason="reviewed",
                  actor_ref="reviewer:r1", recorded_at=T0 + timedelta(days=1))
    kwargs.update(override)
    return ThemeGovernanceEvent.build(**kwargs)


def metadata(**override) -> ThemeMetadataRecord:
    kwargs = dict(root_id=ROOT_A, field=MetadataField.LABEL, value=("Yen weakness / input cost",),
                  provenance_class=ProvenanceClass.HUMAN, recorded_at=T0)
    kwargs.update(override)
    return ThemeMetadataRecord.build(**kwargs)


def mapping(**override) -> ThemeSeriesMapping:
    kwargs = dict(root_id=ROOT_A, series_ref="index:topix.close.closing.tokyo",
                  mapping_role=MappingRole.CONFIRMATION_CANDIDATE, valid_from=T0,
                  provenance_class=ProvenanceClass.HUMAN, recorded_at=T0, consequence_ref="c1")
    kwargs.update(override)
    return ThemeSeriesMapping.build(**kwargs)


def inferred_link(value="jp:security:72030", provenance=ProvenanceClass.HUMAN, ref=""):
    return InferredExposureLink(entity=EntityRef(kind=ThemeEntityKind.COMPANY, value=value),
                                exposure_kind=M.ExposureKind.ADVERSELY_EXPOSED,
                                uncertainty=M.ExposureUncertainty.HYPOTHESIZED, provenance_class=provenance,
                                provenance_ref=ref)


def raises(code: str):
    return pytest.raises(ThemeModelError, match=f"^{code}")


# ---------------------------------------------------------------- schema / vocabulary

def test_schema_versions_are_explicit_and_distinct() -> None:
    versions = M.SCHEMA_VERSIONS
    assert set(versions) == {"ThemeRootRecord", "ThemeObservation", "ThemeGovernanceEvent", "ThemeMetadataRecord",
                             "ThemeSeriesMapping"}
    assert len(set(versions.values())) == 5
    assert all(v.split(":")[1] == "0.1.0" for v in versions.values())
    assert M.MECHANISM_VOCABULARY_VERSION == "mechanism_vocabulary:0.1.0"
    assert M.GOVERNANCE_VOCABULARY_VERSION == "governance_vocabulary:0.1.0"
    assert M.METADATA_FIELD_VOCABULARY_VERSION == "metadata_field_vocabulary:0.1.0"
    for cls in M.CANONICAL_RECORD_TYPES:
        assert "schema_version" in {f.name for f in M.fields(cls)}


def test_frozen_enum_vocabularies() -> None:
    assert {e.value for e in MechanismCertainty} == {"OBSERVED_ASSOCIATION", "HYPOTHESIZED_MECHANISM",
                                                     "EVIDENCE_SUPPORTED_MECHANISM", "EXPLICIT_SOURCE_CAUSAL_CLAIM"}
    assert {e.value for e in EvidenceAuthorityClass} == {"PRIMARY_OBSERVATIONAL", "DERIVED_INTERPRETIVE",
                                                         "PROPOSAL_ONLY", "NOT_THEME_EVIDENCE"}
    assert {e.value for e in EvidenceRole} == {"SUPPORTS", "CONTRADICTS", "CONTEXT", "INVALIDATES"}
    assert {e.value for e in ProvenanceClass} == {"RULE", "HUMAN", "LLM_PROPOSAL"}
    assert {e.value for e in EvidenceKind} == {"FACT", "OBSERVATION", "SOURCE_DOCUMENT", "NEWS_ITEM", "STATEMENT"}
    assert {e.value for e in EntityLinkClass} == {"DIRECTLY_EVIDENCED", "INFERRED_EXPOSURE", "TAXONOMIC_ASSOCIATION"}
    assert {e.value for e in GovernanceEventType} == {
        "CANDIDATE_ACCEPTED", "CANDIDATE_REJECTED", "RETIRED", "REOPENED", "MERGE", "SPLIT", "SUPERSEDED_BY_ROOT",
        "ROLE_CORRECTION_APPROVED", "CERTAINTY_CHANGE_APPROVED", "METADATA_CORRECTION_APPROVED", "EVENT_REVERSED"}
    assert {e.value for e in MetadataField} == {"LABEL", "DESCRIPTION", "TAXONOMY", "ALIAS"}
    assert {e.value for e in CreationMethod} == {"CANDIDATE", "MERGE_RESULT", "SPLIT_RESULT", "SUCCESSOR_RESULT"}
    assert {e.value for e in MappingRole} == {"CONFIRMATION_CANDIDATE", "DRIVER_PROXY", "DOMAIN_PROXY"}
    assert {e.value for e in ComponentType} == {"DRIVER", "TRANSMISSION_CHANNEL", "AFFECTED_DOMAIN",
                                                "EXPECTED_OBSERVABLE_CONSEQUENCE"}
    assert {e.value for e in EvidenceTimeBasis} == {"KNOWN_AT", "AS_OF", "PUBLISHED_AT", "EVENT_TIME", "NONE"}
    assert {e.value for e in EvidenceTimeQuality} == {"RELIABLE", "DECLARED", "INFERRED", "MISSING"}
    assert "TRIGGER" not in {e.value for e in EvidenceRole}
    assert "CONTEXT_ITEM" not in {e.value for e in EvidenceKind} and M.PROHIBITED_EVIDENCE_KINDS == ("CONTEXT_ITEM",)


def test_theme_entity_kind_mirrors_news_model_entity_kind() -> None:
    from src.intelligence.databank.news_model import EntityKind  # test-only import（runtime closure には入れない）
    assert {e.value for e in ThemeEntityKind} == {e.value for e in EntityKind}


def test_mechanism_vocabulary_shape() -> None:
    for component_type, categories in M.MECHANISM_CATEGORIES.items():
        assert isinstance(component_type, ComponentType)
        assert M.OTHER_CATEGORY in categories and len(categories) == len(set(categories))
        assert all(c.isupper() and " " not in c for c in categories)


# ---------------------------------------------------------------- ThemeRootRecord

def test_root_record_round_trip_and_digest() -> None:
    record = root_record()
    assert ThemeRootRecord.from_dict(record.as_dict()) == record
    assert canonical_line(record).endswith("\n")
    digest = record_digest(record)
    assert digest.startswith("thdigest_") and digest != record.root_id and not is_root_id(digest)


def test_root_record_field_inventory_has_no_current_state() -> None:
    names = {f.name for f in M.fields(ThemeRootRecord)}
    assert names == {"schema_version", "root_id", "created_at", "creation_method", "creator_class",
                     "creation_provenance", "origin_event_id", "genesis_observation_id"}
    assert not any(n.startswith("current") or n in {"label", "lifecycle", "certainty", "taxonomy", "latest_observation_id"}
                   for n in names)


def test_root_record_rejects_naive_and_invalid_ids() -> None:
    with raises("NAIVE_DATETIME"):
        root_record(created_at=datetime(2026, 9, 1))
    with raises("INVALID_ROOT_ID"):
        root_record(root_id="theme_" + "a" * 24)                 # content-id 風（sha 24 hex）は root id ではない
    with raises("INVALID_ROOT_ID"):
        root_record(root_id=content_id("theme", "some content"))  # 内容導出 id は構造的に拒否
    with raises("INVALID_ROOT_ID"):
        root_record(root_id="theme_0123456789abcdefghjkmnpqrs")   # 小文字 ULID は不可
    with raises("INVALID_RECORD_ID"):
        root_record(genesis_observation_id="thobs_short")
    with raises("UNSUPPORTED_SCHEMA_VERSION"):
        root_record(schema_version="theme_root:9.9.9")


def test_root_record_origin_event_rules() -> None:
    gov = "thgov_" + "1" * 24
    with raises("INVALID_ORIGIN_EVENT"):
        root_record(origin_event_id=gov)                          # CANDIDATE は origin event を持たない
    with raises("INVALID_RECORD_ID"):
        root_record(creation_method=CreationMethod.MERGE_RESULT)  # MERGE_RESULT は origin event 必須
    with raises("INVALID_ROLE_COMBINATION"):
        root_record(creation_method=CreationMethod.SPLIT_RESULT, origin_event_id=gov, creator_class=ProvenanceClass.RULE)
    ok = root_record(creation_method=CreationMethod.SUCCESSOR_RESULT, origin_event_id=gov)
    assert ok.origin_event_id == gov and ok.creator_class is ProvenanceClass.HUMAN


def test_new_root_id_is_opaque_generated_and_valid() -> None:
    a, b = new_root_id(T0), new_root_id(T0)
    assert is_root_id(a) and is_root_id(b) and a != b        # 同じ時刻・同じ内容でも別 id（内容導出ではない）
    assert a[:6] == "theme_" and len(a) == 32


# ---------------------------------------------------------------- ThemeObservation

def test_observation_round_trip_and_canonical_line() -> None:
    obs = observation()
    again = ThemeObservation.from_dict(obs.as_dict())
    assert again == obs and canonical_line(again) == canonical_line(obs)
    line = canonical_line(obs)
    assert line.endswith("\n") and "\n" not in line[:-1]
    payload = json.loads(line)
    assert list(payload) == sorted(payload) and ": " not in line and ", " not in line
    assert payload["recorded_at"].endswith("+00:00")


def test_observation_field_inventory_excludes_metadata_lifecycle_and_prediction() -> None:
    names = {f.name for f in M.fields(ThemeObservation)}
    assert names == {"schema_version", "mechanism_vocabulary_version", "observation_id", "root_id",
                     "previous_observation_id", "subject", "mechanism", "certainty_class", "scope", "limitations",
                     "invalidation_conditions", "inferred_links", "attachments", "provenance", "recorded_at"}
    for forbidden in ("label", "description", "taxonomy", "alias", "lifecycle", "status", "horizon",
                      "expected_return", "target_price", "recommendation", "confidence", "fingerprint",
                      "qualification", "narrative"):
        assert forbidden not in names


def test_observation_id_excludes_provenance_and_recorded_at() -> None:
    a = observation()
    b = observation(provenance=provenance(ProvenanceClass.RULE, "rule:R9@2", reason="other"),
                    recorded_at=T0 + timedelta(days=3))
    assert a.observation_id == b.observation_id
    assert canonical_line(a) != canonical_line(b)   # 行は違う（同一 id 異 bytes → store では CONFLICT）


def test_observation_id_changes_with_semantic_content() -> None:
    base = observation()
    assert observation(limitations=()).observation_id != base.observation_id
    assert observation(previous_observation_id=base.observation_id).observation_id != base.observation_id
    assert observation(root_id=ROOT_B).observation_id != base.observation_id
    assert observation(certainty_class=MechanismCertainty.OBSERVED_ASSOCIATION).observation_id != base.observation_id
    assert observation(attachments=(attachment(FACT_A),)).observation_id != base.observation_id


def test_observation_collection_order_independence() -> None:
    forward = observation(
        scope=scope(), limitations=(limitation("a1"), limitation("b2")),
        invalidation_conditions=(condition("inv1", "x1"), condition("inv2", "x2")),
        inferred_links=(inferred_link("jp:security:1"), inferred_link("jp:security:2")),
        attachments=(attachment(FACT_A), attachment(FACT_B, day="2026-08-21")),
        mechanism=mechanism(drivers=(component(key="d1"), component(key="d2", category="POLICY_RATE",
                                                                    typed_reference="rates:boj")),
                            consequences=(consequence("c1"), consequence("c2", target="x"))))
    backward = observation(
        scope=tuple(reversed(scope())), limitations=(limitation("b2"), limitation("a1")),
        invalidation_conditions=(condition("inv2", "x2"), condition("inv1", "x1")),
        inferred_links=(inferred_link("jp:security:2"), inferred_link("jp:security:1")),
        attachments=(attachment(FACT_B, day="2026-08-21"), attachment(FACT_A)),
        mechanism=mechanism(drivers=(component(key="d2", category="POLICY_RATE", typed_reference="rates:boj"),
                                     component(key="d1")),
                            consequences=(consequence("c2", target="x"), consequence("c1"))))
    assert forward.observation_id == backward.observation_id
    assert canonical_line(forward) == canonical_line(backward)


def test_observation_structural_requirements() -> None:
    with raises("MISSING_INVALIDATION_CONDITION"):
        observation(invalidation_conditions=())
    with raises("MISSING_SCOPE"):
        observation(scope=())
    with raises("MISSING_SCOPE"):
        observation(scope=(ScopeToken(dimension=ScopeDimension.REGION, value="jp"),))
    with raises("MISSING_SCOPE"):
        observation(scope=scope() + (ScopeToken(dimension=ScopeDimension.PERIOD_FRAME, value="multi_year"),))
    with raises("DUPLICATE_KEY"):
        observation(invalidation_conditions=(condition("inv1", "a"), condition("inv1", "b")))
    with raises("NAIVE_DATETIME"):
        observation(recorded_at=datetime(2026, 9, 2))
    with raises("INVALID_ROOT_ID"):
        observation(root_id="theme_bad")
    with raises("INVALID_RECORD_ID"):
        observation(previous_observation_id="obs_" + "1" * 24)


def test_mechanism_requires_each_component_type_and_a_consequence() -> None:
    with raises("INVALID_MECHANISM"):
        mechanism(drivers=())
    with raises("INVALID_MECHANISM"):
        mechanism(channels=())
    with raises("INVALID_MECHANISM"):
        mechanism(domains=())
    with raises("MISSING_OBSERVABLE_CONSEQUENCE"):
        mechanism(consequences=())
    with raises("INVALID_MECHANISM"):
        mechanism(drivers=(component(ComponentType.TRANSMISSION_CHANNEL, "x", "INPUT_COST", ""),))
    with raises("DUPLICATE_KEY"):
        mechanism(drivers=(component(key="c1"),))
    with raises("MISSING_FIELD"):
        consequence(target="")


def test_mechanism_category_vocabulary_and_other_requires_statement() -> None:
    with raises("INVALID_VOCABULARY"):
        component(category="NOT_A_CATEGORY")
    with raises("INVALID_VOCABULARY"):
        component(category="INPUT_COST")  # channel の語彙を driver に使えない
    with raises("MISSING_FIELD"):
        component(category="OTHER")
    ok = component(category="OTHER", statement="tourism inflow")
    assert ok.category == "OTHER" and ok.normalized_statement == "tourism inflow"
    with raises("MISSING_PROVENANCE"):
        component(provenance=AssertionProvenance.RULE)
    with raises("MISSING_PROVENANCE"):
        component(provenance=AssertionProvenance.LLM_PROPOSAL)


def test_normalized_text_is_enforced_not_silently_rewritten() -> None:
    with raises("NOT_NORMALIZED"):
        subject("Yen Weakness")
    with raises("NOT_NORMALIZED"):
        limitation("double  space")
    assert M.normalize_text("Ｙen  Weakness ") == "yen weakness"
    assert subject(M.normalize_text("Yen Weakness")).normalized_subject == "yen weakness"


def test_prohibited_content_rejected_in_semantic_and_metadata_fields() -> None:
    with raises("PROHIBITED_CONTENT"):
        limitation("see d:/research/notes.txt")
    with raises("PROHIBITED_CONTENT"):
        attachment(locator="https://user:secret@example.invalid/x")
    with raises("PROHIBITED_CONTENT"):
        attachment(locator="https://example.invalid/x?token=abc")
    with raises("PROHIBITED_CONTENT"):
        metadata(field=MetadataField.DESCRIPTION, value=(r"x:\synthetic\drive\path",))
    with raises("INVALID_TEXT"):
        limitation("line one\nline two")


def test_unknown_fields_and_schema_versions_fail_closed() -> None:
    data = observation().as_dict()
    data["label"] = "sneaky"
    with raises("UNKNOWN_FIELDS"):
        ThemeObservation.from_dict(data)
    data = observation().as_dict()
    data["schema_version"] = "theme_observation:0.2.0"
    with raises("UNSUPPORTED_SCHEMA_VERSION"):
        ThemeObservation.from_dict(data)
    data = observation().as_dict()
    data["mechanism_vocabulary_version"] = "mechanism_vocabulary:0.9.0"
    with raises("UNSUPPORTED_SCHEMA_VERSION"):
        ThemeObservation.from_dict(data)
    data = observation().as_dict()
    data["observation_id"] = "thobs_" + "0" * 24
    with raises("IDENTITY_MISMATCH"):
        ThemeObservation.from_dict(data)


def test_canonical_serialization_is_deterministic_and_utc_normalized() -> None:
    jst = timezone(timedelta(hours=9))
    a = observation(attachments=(attachment(FACT_A, attached=datetime(2026, 9, 1, 9, 0, tzinfo=jst)),))
    b = observation(attachments=(attachment(FACT_A, attached=datetime(2026, 9, 1, 0, 0, tzinfo=UTC)),))
    assert a.observation_id == b.observation_id and canonical_line(a) == canonical_line(b)
    assert canonical_line(a) == canonical_line(ThemeObservation.from_dict(json.loads(canonical_line(a))))
    assert canonical_json({"b": 1, "a": "円"}) == '{"a":"円","b":1}'
    with pytest.raises(ThemeModelError, match="^NON_CANONICAL_RECORD"):
        canonical_json({"x": object()})


# ---------------------------------------------------------------- metadata / mapping separation

def test_metadata_record_round_trip_and_set_snapshot() -> None:
    record = metadata(field=MetadataField.TAXONOMY, value=("b", "a", "a"))
    assert record.value == ("a", "b")
    assert ThemeMetadataRecord.from_dict(record.as_dict()) == record
    empty = metadata(field=MetadataField.ALIAS, value=())
    assert empty.value == ()


def test_metadata_single_valued_fields() -> None:
    with raises("INVALID_METADATA_VALUE"):
        metadata(field=MetadataField.LABEL, value=("a", "b"))
    with raises("INVALID_METADATA_VALUE"):
        metadata(field=MetadataField.DESCRIPTION, value=())
    with raises("MISSING_FIELD"):
        metadata(field=MetadataField.LABEL, value=("",))
    with raises("FIELD_TOO_LONG"):
        metadata(field=MetadataField.LABEL, value=("x" * 121,))


def test_metadata_change_does_not_touch_observation_identity() -> None:
    obs = observation()
    before = obs.observation_id
    for field, value in ((MetadataField.LABEL, ("A",)), (MetadataField.LABEL, ("B",)),
                         (MetadataField.TAXONOMY, ("t1", "t2"))):
        record = metadata(field=field, value=value)
        assert record.root_id == obs.root_id and "observation" not in {f.name for f in M.fields(ThemeMetadataRecord)}
    assert obs.observation_id == before
    assert "label" not in obs.as_dict() and "taxonomy" not in canonical_line(obs)


def test_mapping_round_trip_and_isolation() -> None:
    record = mapping()
    assert ThemeSeriesMapping.from_dict(record.as_dict()) == record
    names = {f.name for f in M.fields(ThemeSeriesMapping)}
    assert names == {"schema_version", "mapping_id", "root_id", "consequence_ref", "series_ref", "mapping_role",
                     "expected_relation", "valid_from", "supersedes_mapping_id", "provenance_class",
                     "provenance_ref", "reason", "recorded_at"}
    obs = observation()
    assert "mapping" not in canonical_line(obs) and "series_ref" not in canonical_line(obs)
    other = mapping(series_ref="fx:USDJPY.close.closing.tokyo", expected_relation=ExpectedRelation.SAME_DIRECTION)
    assert other.mapping_id != record.mapping_id
    with raises("NAIVE_DATETIME"):
        mapping(valid_from=datetime(2026, 9, 1))
    with raises("INVALID_RECORD_ID"):
        mapping(supersedes_mapping_id="thmap_bad")
    with raises("MISSING_PROVENANCE"):
        mapping(provenance_class=ProvenanceClass.RULE)


def test_all_five_record_types_serialize_and_validate() -> None:
    obs = observation()
    records = (root_record(obs), obs, event(), metadata(), mapping())
    assert tuple(type(r) for r in records) == M.CANONICAL_RECORD_TYPES
    for record in records:
        again = type(record).from_dict(json.loads(canonical_line(record)))
        assert again == record
        assert record.as_dict()["schema_version"] == M.SCHEMA_VERSIONS[type(record).__name__]
        assert canonical_line(record) == canonical_line(again)
