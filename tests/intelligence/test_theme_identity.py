"""P6-A4a — identity: content-ID payload の凍結・golden vector・fingerprint の材料 / 除外・同一 root revision の保護。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from src.intelligence.core.ids import content_id
from src.intelligence.themes import fingerprint as F
from src.intelligence.themes import model as M
from src.intelligence.themes import qualification as Q
from src.intelligence.themes import revision as R
from src.intelligence.themes.model import (
    ComponentType, EvidenceRole, ExpectedChange, GovernanceEventType, MechanismCertainty, MetadataField,
    ProvenanceClass, ScopeDimension, ScopeToken, ThemeModelError, canonical_json,
)
from tests.intelligence.test_theme_model import (
    FACT_A, FACT_B, ROOT_A, ROOT_B, T0, attachment, component, condition, consequence, event, inferred_link,
    limitation, mapping, mechanism, metadata, observation, provenance, raises, subject,
)

#: golden vectors（fixture 固定。canonical payload が変われば必ず変わる ＝ 契約違反の検出器）
GOLDEN = {
    "observation_id": "thobs_e522b3e33a429e3b1a563465",
    "identity_core": "thcore_655bd1db5b36a7e96ebf113c",
    "semantic": "thsem_ec75fd2fafb8a1e96e7276c0",
    "event_id": "thgov_aae49671a3630c21ae259b0f",
    "metadata_id": "thmeta_e711257a6b74ad6aedc29124",
    "mapping_id": "thmap_4c89e234e6997cef2ef07624",
}


# ---------------------------------------------------------------- identity payloads

def test_observation_identity_payload_keys_and_golden() -> None:
    obs = observation()
    payload = obs.identity_payload()
    assert set(payload) == {"schema_version", "mechanism_vocabulary_version", "root_id", "previous_observation_id",
                            "subject", "mechanism", "certainty_class", "scope", "limitations",
                            "invalidation_conditions", "inferred_links", "attachments"}
    assert "provenance" not in payload and "recorded_at" not in payload and "observation_id" not in payload
    assert obs.observation_id == content_id("thobs", canonical_json(payload)) == GOLDEN["observation_id"]
    assert obs.canonical_identity == canonical_json(payload)


def test_governance_identity_payload_and_golden() -> None:
    ev = event()
    payload = ev.identity_payload()
    assert set(payload) == {"schema_version", "governance_vocabulary_version", "event_type", "subject_roots",
                            "result_roots", "related_observations", "previous_event_ids", "reverses_event_id",
                            "evidence_allocation", "reason", "actor_class"}
    assert canonical_json(payload) == (
        '{"actor_class":"HUMAN","event_type":"CANDIDATE_ACCEPTED","evidence_allocation":[],'
        '"governance_vocabulary_version":"governance_vocabulary:0.1.0","previous_event_ids":[],"reason":"reviewed",'
        '"related_observations":[],"result_roots":[],"reverses_event_id":"",'
        '"schema_version":"theme_governance:0.1.0","subject_roots":["' + ROOT_A + '"]}')
    assert ev.event_id == content_id("thgov", canonical_json(payload)) == GOLDEN["event_id"]


def test_metadata_identity_payload_and_golden() -> None:
    record = metadata()
    payload = record.identity_payload()
    assert canonical_json(payload) == (
        '{"field":"LABEL","governance_event_id":"","metadata_field_vocabulary_version":"metadata_field_vocabulary:0.1.0",'
        '"previous_metadata_id":"","provenance_class":"HUMAN","root_id":"' + ROOT_A + '",'
        '"schema_version":"theme_metadata:0.1.0","value":["Yen weakness / input cost"]}')
    assert record.metadata_id == content_id("thmeta", canonical_json(payload)) == GOLDEN["metadata_id"]
    # provenance_ref / reason / recorded_at は id 外
    same = metadata(provenance_ref="reviewer:r2", reason="typo", recorded_at=T0 + timedelta(days=9))
    assert same.metadata_id == record.metadata_id


def test_mapping_identity_payload_and_golden() -> None:
    record = mapping()
    payload = record.identity_payload()
    assert canonical_json(payload) == (
        '{"consequence_ref":"c1","expected_relation":"UNSPECIFIED","mapping_role":"CONFIRMATION_CANDIDATE",'
        '"provenance_class":"HUMAN","root_id":"' + ROOT_A + '","schema_version":"theme_series_mapping:0.1.0",'
        '"series_ref":"index:topix.close.closing.tokyo","supersedes_mapping_id":"","valid_from":"2026-09-01T00:00:00+00:00"}')
    assert record.mapping_id == content_id("thmap", canonical_json(payload)) == GOLDEN["mapping_id"]
    assert mapping(reason="x", recorded_at=T0 + timedelta(days=1)).mapping_id == record.mapping_id


def test_fingerprint_golden_vectors() -> None:
    obs = observation()
    assert F.identity_core_fingerprint(obs) == GOLDEN["identity_core"]
    assert F.semantic_fingerprint(obs) == GOLDEN["semantic"]
    assert F.identity_core_payload(obs) == {
        "subject": ["yen weakness and import input cost", "fx:usdjpy"],
        "components": sorted([["AFFECTED_DOMAIN", "SECTOR", "sector:s17:05"], ["DRIVER", "FX_RATE", "fx:usdjpy"],
                              ["TRANSMISSION_CHANNEL", "INPUT_COST", ""]])}
    assert F.semantic_payload(obs)["consequences"] == [["EARNINGS_METRIC", "sector:s17:05.margin", "DECREASE"]]
    assert F.semantic_payload(obs)["scope"] == [["PERIOD_FRAME", "multi_quarter"], ["REGION", "jp"]]


# ---------------------------------------------------------------- fingerprint 材料 / 除外

def test_fingerprints_exclude_root_evidence_class_links_limitations_timestamps_provenance() -> None:
    base = observation()
    variants = (
        observation(root_id=ROOT_B),
        observation(attachments=()),
        observation(attachments=(attachment(FACT_A), attachment(FACT_B, day="2026-08-21"),
                                 attachment("doc_" + "9" * 24, kind=M.EvidenceKind.SOURCE_DOCUMENT))),
        observation(certainty_class=MechanismCertainty.OBSERVED_ASSOCIATION),
        observation(inferred_links=(inferred_link(),)),
        observation(limitations=()),
        observation(invalidation_conditions=(condition("inv9", "other condition"),)),
        observation(recorded_at=T0 + timedelta(days=30), provenance=provenance(ProvenanceClass.RULE, "rule:R2@1")),
        observation(previous_observation_id=base.observation_id),
    )
    for variant in variants:
        assert F.identity_core_fingerprint(variant) == F.identity_core_fingerprint(base)
        assert F.semantic_fingerprint(variant) == F.semantic_fingerprint(base)
    # metadata（label / taxonomy）は observation に存在しないので fingerprint に入りようがない
    assert "label" not in canonical_json(F.semantic_payload(base))


def test_semantic_fingerprint_tracks_consequence_and_scope_but_core_does_not() -> None:
    base = observation()
    refined_scope = observation(scope=(ScopeToken(dimension=ScopeDimension.REGION, value="jp"),
                                       ScopeToken(dimension=ScopeDimension.INDUSTRY, value="food processing"),
                                       ScopeToken(dimension=ScopeDimension.PERIOD_FRAME, value="multi_quarter")))
    new_consequence = observation(mechanism=mechanism(consequences=(consequence(change=ExpectedChange.INCREASE),)))
    for variant in (refined_scope, new_consequence):
        assert F.identity_core_fingerprint(variant) == F.identity_core_fingerprint(base)
        assert F.semantic_fingerprint(variant) != F.semantic_fingerprint(base)


def test_identity_core_tracks_subject_driver_channel_domain() -> None:
    base = observation()
    variants = (
        observation(subject=subject("tourism inflow and service demand", "")),
        observation(mechanism=mechanism(drivers=(component(category="POLICY_RATE", typed_reference="rates:boj"),))),
        observation(mechanism=mechanism(drivers=(component(typed_reference="fx:EURJPY"),))),
        observation(mechanism=mechanism(channels=(component(ComponentType.TRANSMISSION_CHANNEL, "ch1",
                                                            "PRICING_POWER", ""),))),
        observation(mechanism=mechanism(domains=(component(ComponentType.AFFECTED_DOMAIN, "dom1", "SECTOR",
                                                           "sector:s17:07"),))),
    )
    for variant in variants:
        assert F.identity_core_fingerprint(variant) != F.identity_core_fingerprint(base)


def test_identity_core_ignores_statement_wording_unless_category_other() -> None:
    base = observation(mechanism=mechanism(drivers=(component(statement="usd jpy depreciation"),)))
    reworded = observation(mechanism=mechanism(drivers=(component(statement="weaker yen versus dollar"),)))
    assert F.identity_core_fingerprint(base) == F.identity_core_fingerprint(reworded)
    other_a = observation(mechanism=mechanism(drivers=(component(category="OTHER", typed_reference="",
                                                                 statement="tourism inflow"),)))
    other_b = observation(mechanism=mechanism(drivers=(component(category="OTHER", typed_reference="",
                                                                 statement="pilgrimage season"),)))
    assert F.identity_core_fingerprint(other_a) != F.identity_core_fingerprint(other_b)


def test_fingerprint_equality_is_not_identity_and_no_merge_helper_exists() -> None:
    a = observation(root_id=ROOT_A)
    b = observation(root_id=ROOT_B)
    assert F.semantic_fingerprint(a) == F.semantic_fingerprint(b)
    assert a.root_id != b.root_id and a.observation_id != b.observation_id
    for module in (M, F, Q, R):
        assert not [n for n in dir(module) if "merge" in n.lower() or "dedup" in n.lower()]
    assert not any(a.__class__.__dict__.get(n) for n in ("merge", "merge_into"))


# ---------------------------------------------------------------- 同一 root の revision helper

def test_revise_observation_preserves_root_and_links_previous() -> None:
    first = observation()
    second = R.revise_observation(first, recorded_at=first.recorded_at + timedelta(hours=1),
                                  provenance=provenance(reason="scope refined"),
                                  scope=(ScopeToken(dimension=ScopeDimension.REGION, value="jp"),
                                         ScopeToken(dimension=ScopeDimension.PERIOD_FRAME, value="multi_year")))
    assert second.root_id == first.root_id
    assert second.previous_observation_id == first.observation_id
    assert second.observation_id != first.observation_id and not second.is_genesis and first.is_genesis
    assert F.identity_core_fingerprint(second) == F.identity_core_fingerprint(first)
    assert second.attachments == first.attachments      # 引き継ぎ（attached_at 不変）


def test_revise_observation_rejects_identity_core_changes() -> None:
    first = observation()
    later = first.recorded_at + timedelta(hours=1)
    with raises("IDENTITY_CORE_CHANGED"):
        R.revise_observation(first, recorded_at=later, provenance=provenance(),
                             mechanism=mechanism(drivers=(component(category="POLICY_RATE", typed_reference=""),)))
    with raises("IDENTITY_CORE_CHANGED"):
        R.revise_observation(first, recorded_at=later, provenance=provenance(),
                             mechanism=mechanism(channels=(component(ComponentType.TRANSMISSION_CHANNEL, "ch1",
                                                                     "CAPEX_CYCLE", ""),)))
    with raises("IDENTITY_CORE_CHANGED"):
        R.revise_observation(first, recorded_at=later, provenance=provenance(),
                             mechanism=mechanism(domains=(component(ComponentType.AFFECTED_DOMAIN, "dom1",
                                                                    "REGION", "region:jp"),)))
    with raises("IDENTITY_CORE_CHANGED"):
        R.revise_observation(first, recorded_at=later, provenance=provenance(), subject=subject("other subject", ""))


def test_revise_observation_allows_same_root_changes_from_a2_table() -> None:
    first = observation()
    later = first.recorded_at + timedelta(hours=1)
    changes = (
        dict(certainty_class=MechanismCertainty.OBSERVED_ASSOCIATION),
        dict(limitations=(limitation("new limitation"),)),
        dict(invalidation_conditions=(condition("inv1", "margins expand despite weak yen"),
                                      condition("inv2", "import volumes collapse"))),
        dict(mechanism=mechanism(consequences=(consequence(), consequence("c2", "PRICE_LEVEL", "sector:s17:05.px",
                                                                          ExpectedChange.DECREASE)))),
        dict(inferred_links=(inferred_link(),)),
        dict(attachments=first.attachments + (attachment("doc_" + "7" * 24, kind=M.EvidenceKind.SOURCE_DOCUMENT,
                                                         role=EvidenceRole.CONTRADICTS, attached=later),)),
    )
    for change in changes:
        revised = R.revise_observation(first, recorded_at=later, provenance=provenance(), **change)
        assert revised.root_id == first.root_id and revised.previous_observation_id == first.observation_id


def test_revise_observation_rejects_non_monotonic_recorded_at() -> None:
    first = observation()
    with raises("NON_MONOTONIC_RECORDED_AT"):
        R.revise_observation(first, recorded_at=first.recorded_at - timedelta(seconds=1), provenance=provenance(),
                             limitations=())


def test_attach_evidence_keeps_original_attached_at_and_requires_input() -> None:
    first = observation()
    later = first.recorded_at + timedelta(days=1)
    new = attachment("news_" + "5" * 24, kind=M.EvidenceKind.NEWS_ITEM, attached=later, day="2026-08-30",
                     src=M.SourceOrigin(origin_kind=M.OriginKind.PUBLISHER_ARTICLE, origin_key="article:art_x",
                                        source_ids=("feed_a",)))
    second = R.attach_evidence(first, (new,), recorded_at=later, provenance=provenance())
    originals = {a.ref_id: a.attached_at for a in first.attachments}
    for a in second.attachments:
        if a.ref_id in originals:
            assert a.attached_at == originals[a.ref_id]
    assert new in second.attachments and len(second.attachments) == 3
    with raises("MISSING_FIELD"):
        R.attach_evidence(first, (), recorded_at=later, provenance=provenance())
    with raises("ATTACHED_AT_OUT_OF_RANGE"):
        R.attach_evidence(first, (new,), recorded_at=first.recorded_at, provenance=provenance())


def test_revert_is_a_new_terminal_observation_not_a_fork() -> None:
    first = observation()
    second = R.revise_observation(first, recorded_at=first.recorded_at + timedelta(hours=1), provenance=provenance(),
                                  limitations=())
    reverted = R.revise_observation(second, recorded_at=second.recorded_at + timedelta(hours=1),
                                    provenance=provenance(reason="revert"), limitations=first.limitations)
    assert reverted.previous_observation_id == second.observation_id
    assert reverted.observation_id not in (first.observation_id, second.observation_id)
    assert reverted.limitations == first.limitations
    with pytest.raises(ThemeModelError, match="^INVALID_TYPE"):
        R.revise_observation("not an observation", recorded_at=T0, provenance=provenance())  # type: ignore[arg-type]


def test_root_id_is_generated_not_content_derived() -> None:
    a = M.new_root_id(T0)
    b = M.new_root_id(T0)
    assert a != b and M.is_root_id(a)
    obs_a = observation(root_id=a)
    obs_b = observation(root_id=b)
    assert obs_a.identity_payload()["root_id"] == a
    assert F.semantic_fingerprint(obs_a) == F.semantic_fingerprint(obs_b)   # 同じ内容でも root は別
    assert not M.is_content_id(a, "thobs")
