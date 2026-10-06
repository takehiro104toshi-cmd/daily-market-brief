"""P6-A4a — ThemeGovernanceEvent / ThemeMetadataRecord の構造検証（状態解決は A4c。ここでは形だけ）。"""
from __future__ import annotations

from datetime import timedelta

from src.intelligence.themes import model as M
from src.intelligence.themes.model import (
    CreationMethod, EvidenceAllocation, GovernanceEventType, MetadataField, ProvenanceClass, ThemeGovernanceEvent,
)
from tests.intelligence.test_theme_model import (
    FACT_A, ROOT_A, ROOT_B, ROOT_C, T0, event, metadata, observation, raises, root_record,
)

GOV_1 = "thgov_" + "1" * 24
GOV_2 = "thgov_" + "2" * 24
META_1 = "thmeta_" + "1" * 24


def allocation(result=ROOT_C, obs=None, key=f"{FACT_A}#c1"):
    obs = obs or observation()
    return EvidenceAllocation(source_observation_id=obs.observation_id, attachment_key=key, result_root_id=result)


def test_event_round_trip_and_previous_event_chain() -> None:
    ev = event(previous_event_ids=((ROOT_A, GOV_1),))
    assert ThemeGovernanceEvent.from_dict(ev.as_dict()) == ev
    assert ev.previous_event_ids == ((ROOT_A, GOV_1),)
    with raises("MALFORMED_GOVERNANCE_EVENT"):
        event(previous_event_ids=((ROOT_B, GOV_1),))               # subject でない root の previous は不可
    with raises("MALFORMED_GOVERNANCE_EVENT"):
        event(previous_event_ids=((ROOT_A, GOV_1), (ROOT_A, GOV_2)))  # root ごとに 1 つ


def test_merge_shape() -> None:
    ok = event(event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A, ROOT_B), result_roots=(ROOT_C,),
               evidence_allocation=(allocation(),))
    assert ok.subject_roots == (ROOT_A, ROOT_B) and ok.result_roots == (ROOT_C,)
    with raises("MALFORMED_MERGE"):
        event(event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A,), result_roots=(ROOT_C,))
    with raises("MALFORMED_MERGE"):
        event(event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A, ROOT_B), result_roots=())
    with raises("MALFORMED_MERGE"):
        event(event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A, ROOT_B),
              result_roots=(ROOT_C, "theme_0123456789ABCDEFGHJKMNPQRW"))
    with raises("MALFORMED_GOVERNANCE_EVENT"):
        event(event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A, ROOT_B), result_roots=(ROOT_A,))


def test_split_shape() -> None:
    ok = event(event_type=GovernanceEventType.SPLIT, subject_roots=(ROOT_A,), result_roots=(ROOT_B, ROOT_C),
               evidence_allocation=(allocation(ROOT_B), allocation(ROOT_C)))   # 同じ attachment を両方へ ＝ 明示列挙
    assert len(ok.evidence_allocation) == 2
    with raises("MALFORMED_SPLIT"):
        event(event_type=GovernanceEventType.SPLIT, subject_roots=(ROOT_A,), result_roots=(ROOT_B,))
    with raises("MALFORMED_SPLIT"):
        event(event_type=GovernanceEventType.SPLIT, subject_roots=(ROOT_A, ROOT_B), result_roots=(ROOT_C,))


def test_superseded_by_root_shape() -> None:
    ok = event(event_type=GovernanceEventType.SUPERSEDED_BY_ROOT, subject_roots=(ROOT_A,), result_roots=(ROOT_B,))
    assert ok.result_roots == (ROOT_B,)
    with raises("MALFORMED_SUCCESSOR"):
        event(event_type=GovernanceEventType.SUPERSEDED_BY_ROOT, subject_roots=(ROOT_A,), result_roots=())
    with raises("MALFORMED_SUCCESSOR"):
        event(event_type=GovernanceEventType.SUPERSEDED_BY_ROOT, subject_roots=(ROOT_A,), result_roots=(ROOT_B, ROOT_C))


def test_reversal_shape() -> None:
    ok = event(event_type=GovernanceEventType.EVENT_REVERSED, reverses_event_id=GOV_1, reason="recorded in error")
    assert ok.reverses_event_id == GOV_1
    with raises("INVALID_RECORD_ID"):
        event(event_type=GovernanceEventType.EVENT_REVERSED)                      # reverses_event_id 必須
    with raises("MALFORMED_REVERSAL"):
        event(event_type=GovernanceEventType.EVENT_REVERSED, reverses_event_id=GOV_1, result_roots=(ROOT_B,))
    with raises("MALFORMED_REVERSAL"):
        event(event_type=GovernanceEventType.RETIRED, reverses_event_id=GOV_1)     # 取消でない event は持てない


def test_single_subject_events_and_allocation_rules() -> None:
    for kind in (GovernanceEventType.CANDIDATE_ACCEPTED, GovernanceEventType.CANDIDATE_REJECTED,
                 GovernanceEventType.RETIRED, GovernanceEventType.REOPENED):
        assert event(event_type=kind).subject_roots == (ROOT_A,)
        with raises("MALFORMED_GOVERNANCE_EVENT"):
            event(event_type=kind, subject_roots=(ROOT_A, ROOT_B))
        with raises("MALFORMED_GOVERNANCE_EVENT"):
            event(event_type=kind, result_roots=(ROOT_B,))
        with raises("ALLOCATION_VIOLATION"):
            event(event_type=kind, evidence_allocation=(allocation(ROOT_A),))
    with raises("ALLOCATION_VIOLATION"):
        event(event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A, ROOT_B), result_roots=(ROOT_C,),
              evidence_allocation=(allocation("theme_0123456789ABCDEFGHJKMNPQRW"),))  # 宣言外の root へ配分不可


def test_correction_approvals_reference_the_approved_records() -> None:
    obs = observation()
    with raises("MALFORMED_GOVERNANCE_EVENT"):
        event(event_type=GovernanceEventType.ROLE_CORRECTION_APPROVED)
    with raises("MALFORMED_GOVERNANCE_EVENT"):
        event(event_type=GovernanceEventType.CERTAINTY_CHANGE_APPROVED)
    ok = event(event_type=GovernanceEventType.ROLE_CORRECTION_APPROVED, related_observations=(obs.observation_id,))
    assert ok.related_observations == (obs.observation_id,)
    with raises("INVALID_RECORD_ID"):
        event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED, related_observations=(obs.observation_id,))
    meta_ok = event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED, related_observations=(META_1,))
    assert meta_ok.related_observations == (META_1,)
    with raises("INVALID_RECORD_ID"):
        event(related_observations=(META_1,))                                       # 通常 event は observation id


def test_governance_events_are_human_decisions_with_reason_and_actor() -> None:
    for actor in (ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL):
        with raises("INVALID_ROLE_COMBINATION"):
            event(actor_class=actor)
    with raises("MISSING_FIELD"):
        event(reason="")
    with raises("MISSING_FIELD"):
        event(actor_ref="")
    with raises("NAIVE_DATETIME"):
        event(recorded_at=T0.replace(tzinfo=None))
    with raises("MALFORMED_GOVERNANCE_EVENT"):
        event(subject_roots=())


def test_event_id_excludes_actor_ref_and_recorded_at_but_includes_reason() -> None:
    base = event()
    assert event(actor_ref="reviewer:r2", recorded_at=T0 + timedelta(days=9)).event_id == base.event_id
    assert event(reason="different reason").event_id != base.event_id
    assert event(previous_event_ids=((ROOT_A, GOV_1),)).event_id != base.event_id
    assert M.canonical_line(base) != M.canonical_line(event(actor_ref="reviewer:r2"))


def test_event_field_inventory_and_no_resolution_logic_in_model() -> None:
    names = {f.name for f in M.fields(ThemeGovernanceEvent)}
    assert names == {"schema_version", "governance_vocabulary_version", "event_id", "event_type", "subject_roots",
                     "result_roots", "related_observations", "previous_event_ids", "reverses_event_id",
                     "evidence_allocation", "reason", "actor_class", "actor_ref", "recorded_at"}
    assert not [n for n in dir(M) if n.lower().startswith(("resolve", "terminal", "current_", "latest"))]
    assert not [n for n in dir(ThemeGovernanceEvent)
                if not n.startswith("__") and ("resolve" in n.lower() or "state" in n.lower())]


def test_event_from_dict_rejects_unknown_vocabulary_and_fields() -> None:
    data = event().as_dict()
    data["event_type"] = "AUTO_MERGED"
    with raises("INVALID_VOCABULARY"):
        ThemeGovernanceEvent.from_dict(data)
    data = event().as_dict()
    data["lifecycle_state"] = "ACTIVE"
    with raises("UNKNOWN_FIELDS"):
        ThemeGovernanceEvent.from_dict(data)
    data = event().as_dict()
    data["governance_vocabulary_version"] = "governance_vocabulary:0.2.0"
    with raises("UNSUPPORTED_SCHEMA_VERSION"):
        ThemeGovernanceEvent.from_dict(data)


def test_result_roots_link_back_through_root_record_origin_event() -> None:
    merge = event(event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A, ROOT_B), result_roots=(ROOT_C,))
    genesis = observation(root_id=ROOT_C)
    record = root_record(genesis, creation_method=CreationMethod.MERGE_RESULT, origin_event_id=merge.event_id)
    assert record.origin_event_id == merge.event_id and record.creation_method is CreationMethod.MERGE_RESULT
    assert record.genesis_observation_id == genesis.observation_id


# ---------------------------------------------------------------- metadata record

def test_metadata_chain_fields_and_provenance_rules() -> None:
    first = metadata()
    second = metadata(value=("Yen weakness and import costs",), previous_metadata_id=first.metadata_id,
                      recorded_at=T0 + timedelta(days=1))
    assert second.previous_metadata_id == first.metadata_id and second.metadata_id != first.metadata_id
    with raises("INVALID_RECORD_ID"):
        metadata(previous_metadata_id="thmeta_bad")
    with raises("INVALID_RECORD_ID"):
        metadata(governance_event_id="thobs_" + "1" * 24)
    with raises("MISSING_PROVENANCE"):
        metadata(provenance_class=ProvenanceClass.RULE)
    with raises("MISSING_PROVENANCE"):
        metadata(provenance_class=ProvenanceClass.LLM_PROPOSAL)
    llm = metadata(provenance_class=ProvenanceClass.LLM_PROPOSAL, provenance_ref="model:x@prompt:v3")
    assert llm.provenance_class is ProvenanceClass.LLM_PROPOSAL


def test_metadata_id_material() -> None:
    base = metadata()
    assert metadata(provenance_ref="reviewer:r2", reason="typo", recorded_at=T0 + timedelta(days=2)).metadata_id == base.metadata_id
    assert metadata(value=("Other",)).metadata_id != base.metadata_id
    assert metadata(previous_metadata_id=META_1).metadata_id != base.metadata_id
    assert metadata(governance_event_id=GOV_1).metadata_id != base.metadata_id
    assert metadata(provenance_class=ProvenanceClass.LLM_PROPOSAL, provenance_ref="m").metadata_id != base.metadata_id
    assert metadata(field=MetadataField.ALIAS, value=("Yen weakness / input cost",)).metadata_id != base.metadata_id


def test_metadata_field_inventory() -> None:
    names = {f.name for f in M.fields(M.ThemeMetadataRecord)}
    assert names == {"schema_version", "metadata_field_vocabulary_version", "metadata_id", "root_id", "field",
                     "value", "previous_metadata_id", "provenance_class", "provenance_ref", "reason",
                     "governance_event_id", "recorded_at"}
    assert M.SET_VALUED_METADATA_FIELDS == (MetadataField.TAXONOMY, MetadataField.ALIAS)
