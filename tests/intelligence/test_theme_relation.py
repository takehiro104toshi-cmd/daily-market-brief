"""P6-B5B — relation model / assertion chain / governance / PIT / graph view（matrix 1〜28, 40〜58）。

Foundation store を読まず書かず、端点の存在は呼び出し側が渡す read-only lookup だけが答える。
合成 root id と合成 evidence 参照のみを使う。
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from src.intelligence.theme_intelligence.relation_graph import (Direction, RELATION_GRAPH_VIEW_VERSION,
                                                                build_relation_graph_view)
from src.intelligence.theme_intelligence.relation_model import (ASSERTION_ID_PREFIX, AssertionClass,
                                                                EVIDENCE_REQUIRED_TYPES, RELATION_VOCAB_VERSION,
                                                                RelationEvidenceRef, RelationGovernanceEventType,
                                                                RelationModelError, RelationProvenance, RelationType,
                                                                SOURCE_ASSERTED_MEANING, SOURCE_ASSERTED_NON_MEANING,
                                                                SourceAttribution, ThemeRelationAssertion,
                                                                ThemeRelationGovernanceEvent, canonical_relation_line,
                                                                edge_key_of, parse_relation_record, split_edge_key)
from src.intelligence.theme_intelligence.relation_resolution import (EdgeState, EndpointState,
                                                                     RelationResolutionStatus, endpoint_lookup_from_roots,
                                                                     resolve_relation_graph)
from src.intelligence.theme_intelligence.relation_store import (RelationAppendRejected, ThemeRelationStore)
from src.intelligence.themes.model import EvidenceKind, OriginKind, ProvenanceClass, SourceOrigin

UTC = timezone.utc
T0 = datetime(2026, 9, 20, tzinfo=UTC)
A = "theme_" + "0" * 26
B = "theme_" + "1" * 26
C = "theme_" + "2" * 26
D = "theme_" + "3" * 26
MISSING_ASSERTION_ID = ASSERTION_ID_PREFIX + "_" + "0" * 24
ACTOR = RelationProvenance(actor_ref="reviewer:r1")
ATTRIBUTION = SourceAttribution(attributed_to="publisher:example_wire")
ORIGIN = SourceOrigin(origin_kind=OriginKind.OFFICIAL_RELEASE, origin_key="release:example_office/doc_a")


def evidence(tag: str = "a", *, at=None) -> RelationEvidenceRef:
    return RelationEvidenceRef(evidence_kind=EvidenceKind.SOURCE_DOCUMENT, ref_id="doc_" + (tag * 24)[:24],
                               source_origin=ORIGIN, evidence_time=at, locator="https://example.invalid/release",
                               attribution="publisher:example_wire")


def assertion(source=A, target=B, *, relation_type=RelationType.AMPLIFIES,
              assertion_class=AssertionClass.HUMAN_ASSERTED, rationale="policy shift lifts construction demand",
              refs=(), attribution=None, previous="", at=T0, provenance=ACTOR) -> ThemeRelationAssertion:
    return ThemeRelationAssertion.build(source_theme_root_id=source, target_theme_root_id=target,
                                        relation_type=relation_type, assertion_class=assertion_class,
                                        rationale=rationale, evidence_refs=refs, source_attribution=attribution,
                                        previous_assertion_id=previous, provenance=provenance, recorded_at=at)


def causal(source=A, target=B, **kw) -> ThemeRelationAssertion:
    kw.setdefault("refs", (evidence(),))
    return assertion(source, target, relation_type=RelationType.CAUSES, **kw)


def sourced(source=A, target=B, **kw) -> ThemeRelationAssertion:
    kw.setdefault("refs", (evidence(),))
    kw.setdefault("attribution", ATTRIBUTION)
    return assertion(source, target, assertion_class=AssertionClass.SOURCE_ASSERTED, **kw)


def retraction(target_assertion, *, reason="withdrawn after review", previous="", at=None) -> ThemeRelationGovernanceEvent:
    return ThemeRelationGovernanceEvent.build(event_type=RelationGovernanceEventType.RETRACTED,
                                              edge_key=target_assertion.edge_key,
                                              subject_assertion_id=target_assertion.relation_assertion_id,
                                              reason=reason, previous_event_id=previous, provenance=ACTOR,
                                              recorded_at=at or T0 + timedelta(days=1))


def restoration(target_assertion, *, previous: str, at=None) -> ThemeRelationGovernanceEvent:
    return ThemeRelationGovernanceEvent.build(event_type=RelationGovernanceEventType.RESTORED,
                                              edge_key=target_assertion.edge_key,
                                              subject_assertion_id=target_assertion.relation_assertion_id,
                                              reason="reinstated after review", previous_event_id=previous,
                                              provenance=ACTOR, recorded_at=at or T0 + timedelta(days=2))


def lookup(*roots, retired=(), superseded=(), created=None):
    return endpoint_lookup_from_roots({r: (created or T0) for r in (roots or (A, B, C, D))}, retired=retired,
                                      superseded=superseded)


def resolve(assertions, events=(), *, cutoff=None, endpoint=None):
    return resolve_relation_graph(list(assertions), list(events), cutoff=cutoff or T0 + timedelta(days=7),
                                  endpoint_lookup=endpoint or lookup())


def view_of(assertions, events=(), **kw):
    return build_relation_graph_view(resolve(assertions, events, **kw))


def fails(code: str, builder) -> RelationModelError:
    with pytest.raises(RelationModelError) as info:
        builder()
    assert info.value.code == code, info.value.code
    return info.value


# ---------------------------------------------------------------- 1〜12 model


def test_01_relation_vocabulary_is_exactly_four_directed_types() -> None:
    assert [t.value for t in RelationType] == ["CAUSES", "AMPLIFIES", "MITIGATES", "DEPENDS_ON"]
    for absent in ("RELATED_TO", "PARENT_OF", "CONSTRAINS", "ENABLES", "OTHER"):
        assert absent not in {t.value for t in RelationType}
    assert EVIDENCE_REQUIRED_TYPES == (RelationType.CAUSES,)


def test_02_unknown_relation_type_is_rejected() -> None:
    payload = assertion().as_dict()
    fails("INVALID_VOCABULARY", lambda: parse_relation_record(dict(payload, relation_type="RELATED_TO")))
    fails("INVALID_VOCABULARY", lambda: parse_relation_record(dict(payload, relation_type="PARENT_OF")))
    fails("UNSUPPORTED_SCHEMA_VERSION", lambda: parse_relation_record(dict(payload, schema_version="theme_relation:9")))


def test_03_assertion_classes_are_exactly_two_and_authority_is_human_recorded() -> None:
    assert [c.value for c in AssertionClass] == ["HUMAN_ASSERTED", "SOURCE_ASSERTED"]
    for absent in ("RULE_ASSERTED", "LLM_ASSERTED", "RULE_PROPOSED", "LLM_PROPOSED"):
        assert absent not in {c.value for c in AssertionClass}
    for actor_class in (ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL):
        fails("FORBIDDEN_ASSERTION_AUTHORITY", lambda cls=actor_class: RelationProvenance(actor_class=cls,
                                                                                          actor_ref="rule:x"))


def test_04_human_assertion_requires_a_rationale_and_forbids_attribution() -> None:
    fails("MISSING_FIELD", lambda: assertion(rationale=""))
    fails("ATTRIBUTION_FORBIDDEN", lambda: assertion(attribution=ATTRIBUTION))
    assert assertion().source_attribution is None


def test_05_source_assertion_requires_attribution_and_citation() -> None:
    fails("MISSING_SOURCE_ATTRIBUTION", lambda: assertion(assertion_class=AssertionClass.SOURCE_ASSERTED,
                                                          refs=(evidence(),)))
    fails("MISSING_SOURCE_CITATION", lambda: assertion(assertion_class=AssertionClass.SOURCE_ASSERTED,
                                                       attribution=ATTRIBUTION, refs=()))
    record = sourced()
    assert record.source_attribution.attributed_to == "publisher:example_wire" and len(record.evidence_refs) == 1
    assert SOURCE_ASSERTED_MEANING == "the cited source asserted this relation"
    assert SOURCE_ASSERTED_NON_MEANING == "the system verified this relation as causal truth"


@pytest.mark.parametrize("assertion_class,attribution", [(AssertionClass.HUMAN_ASSERTED, None),
                                                         (AssertionClass.SOURCE_ASSERTED, ATTRIBUTION)])
def test_06_causal_relations_require_evidence_for_both_classes(assertion_class, attribution) -> None:
    fails("MISSING_CAUSAL_EVIDENCE", lambda: assertion(relation_type=RelationType.CAUSES, refs=(),
                                                       assertion_class=assertion_class, attribution=attribution))
    ok = assertion(relation_type=RelationType.CAUSES, refs=(evidence(),), assertion_class=assertion_class,
                   attribution=attribution)
    assert ok.relation_type is RelationType.CAUSES and len(ok.evidence_refs) == 1


def test_07_a_relation_connects_two_distinct_roots() -> None:
    fails("SELF_RELATION", lambda: assertion(A, A))
    fails("UNKNOWN_THEME_ROOT", lambda: assertion("root_x", B))
    fails("EVIDENCE_AFTER_RECORD", lambda: assertion(refs=(evidence(at=T0 + timedelta(days=1)),)))


def test_08_10_identity_is_content_addressed_and_excludes_audit_fields() -> None:
    base = assertion()
    same = assertion()
    assert base.relation_assertion_id == same.relation_assertion_id and base.relation_assertion_id.startswith("threl_")
    other_actor = assertion(provenance=RelationProvenance(actor_ref="reviewer:r9"), at=T0 + timedelta(days=5))
    assert other_actor.relation_assertion_id == base.relation_assertion_id
    assert "provenance" not in base.identity_payload() and "recorded_at" not in base.identity_payload()
    assert "provenance" in base.as_dict() and "recorded_at" in base.as_dict()
    assert canonical_relation_line(base) != canonical_relation_line(other_actor)


def test_11_a_semantic_change_produces_a_new_identity() -> None:
    base = assertion()
    for changed in (assertion(rationale="a different stated reason"), assertion(A, C),
                    assertion(relation_type=RelationType.MITIGATES), assertion(refs=(evidence("b"),)),
                    sourced()):
        assert changed.relation_assertion_id != base.relation_assertion_id


def test_12_edge_key_is_deterministic_and_carries_five_segments() -> None:
    base = assertion()
    assert base.edge_key == edge_key_of(A, B, RelationType.AMPLIFIES, AssertionClass.HUMAN_ASSERTED, "")
    assert split_edge_key(base.edge_key) == (A, B, RelationType.AMPLIFIES, AssertionClass.HUMAN_ASSERTED, "")
    assert assertion(rationale="another reason").edge_key == base.edge_key      # 訂正は同じ辺
    assert assertion(B, A).edge_key != base.edge_key                            # 逆向きは別の辺
    assert sourced().edge_key.endswith("publisher:example_wire")
    fails("INVALID_EDGE_KEY", lambda: split_edge_key("a|b|c"))


# ---------------------------------------------------------------- 13〜21 assertion chain


def test_13_14_genesis_and_correction(tmp_path) -> None:
    store = ThemeRelationStore.initialize(tmp_path / "d")
    first = assertion()
    store.append_assertion(first)
    second = assertion(rationale="revised reason", previous=first.relation_assertion_id, at=T0 + timedelta(days=1))
    store.append_assertion(second)
    resolution = resolve(store.assertions())
    assert resolution.status is RelationResolutionStatus.RESOLVED and len(resolution.edges) == 1
    edge = resolution.edges[0]
    assert edge.assertion_chain == (first.relation_assertion_id, second.relation_assertion_id)
    assert edge.assertion == second and edge.edge_state is EdgeState.ACTIVE


@pytest.mark.parametrize("code,build", [
    ("MISSING_PREDECESSOR", lambda first: assertion(rationale="x", previous=MISSING_ASSERTION_ID, at=T0 + timedelta(days=1))),
    ("PREDECESSOR_WRONG_EDGE", lambda first: assertion(A, C, previous=first.relation_assertion_id, at=T0 + timedelta(days=1))),
    ("NON_MONOTONIC_RECORDED_AT", lambda first: assertion(rationale="x", previous=first.relation_assertion_id,
                                                          at=T0 - timedelta(days=1))),
    ("EDGE_ALREADY_STARTED", lambda first: assertion(rationale="a second genesis"))])
def test_15_17_18_append_rejects_broken_or_forking_history(tmp_path, code, build) -> None:
    store = ThemeRelationStore.initialize(tmp_path / "d")
    first = assertion()
    store.append_assertion(first)
    with pytest.raises(RelationAppendRejected) as info:
        store.append_assertion(build(first))
    assert info.value.code == code


def test_18b_append_fork_from_the_same_predecessor_is_rejected(tmp_path) -> None:
    store = ThemeRelationStore.initialize(tmp_path / "d")
    first = assertion()
    store.append_assertion(first)
    store.append_assertion(assertion(rationale="branch one", previous=first.relation_assertion_id,
                                     at=T0 + timedelta(days=1)))
    with pytest.raises(RelationAppendRejected) as info:
        store.append_assertion(assertion(rationale="branch two", previous=first.relation_assertion_id,
                                         at=T0 + timedelta(days=1)))
    assert info.value.code == "NOT_TERMINAL_PREDECESSOR"


def test_19_a_loaded_fork_is_unresolved_not_latest_wins() -> None:
    first = assertion()
    left = assertion(rationale="branch one", previous=first.relation_assertion_id, at=T0 + timedelta(days=1))
    right = assertion(rationale="branch two", previous=first.relation_assertion_id, at=T0 + timedelta(days=2))
    resolution = resolve([first, left, right])
    assert resolution.status is RelationResolutionStatus.UNRESOLVED and resolution.edges == ()
    assert resolution.unresolved[0].diagnostics == ("RELATION_FORK",)


def test_20_multiple_starts_for_one_edge_are_unresolved() -> None:
    resolution = resolve([assertion(), assertion(rationale="an independent genesis")])
    assert resolution.status is RelationResolutionStatus.UNRESOLVED
    assert resolution.unresolved[0].diagnostics == ("MULTIPLE_STARTS",)


@pytest.mark.parametrize("code,records", [
    ("DANGLING_PREDECESSOR", lambda: [assertion(rationale="orphan", previous=MISSING_ASSERTION_ID)]),
    ("PREDECESSOR_WRONG_EDGE", lambda: [assertion(), assertion(A, C, previous=assertion().relation_assertion_id)]),
    ("NON_MONOTONIC_RECORDED_AT", lambda: [assertion(at=T0 + timedelta(days=3)),
                                           assertion(rationale="earlier correction",
                                                     previous=assertion(at=T0 + timedelta(days=3)).relation_assertion_id,
                                                     at=T0)])])
def test_21a_structurally_impossible_history_is_invalid(code, records) -> None:
    resolution = resolve(records())
    assert resolution.status is RelationResolutionStatus.INVALID_HISTORY
    assert any(d.detail.startswith(code) or d.code == code for d in resolution.diagnostics)


def test_21b_physical_order_does_not_change_the_result() -> None:
    first = assertion()
    second = assertion(rationale="revised reason", previous=first.relation_assertion_id, at=T0 + timedelta(days=1))
    other = causal(B, C)
    records = [first, second, other]
    base = build_relation_graph_view(resolve(records)).to_plain()
    for seed in range(10):
        shuffled = list(records)
        random.Random(seed).shuffle(shuffled)
        assert build_relation_graph_view(resolve(shuffled)).to_plain() == base, seed


# ---------------------------------------------------------------- 22〜28 governance


def test_22_an_edge_without_governance_is_active() -> None:
    edge = resolve([assertion()]).edges[0]
    assert edge.edge_state is EdgeState.ACTIVE and edge.governance_chain == ()


def test_23_24_retraction_and_restoration() -> None:
    record = assertion()
    retracted = retraction(record)
    resolution = resolve([record], [retracted])
    assert resolution.edges[0].edge_state is EdgeState.RETRACTED
    restored = restoration(record, previous=retracted.event_id)
    again = resolve([record], [retracted, restored])
    assert again.edges[0].edge_state is EdgeState.ACTIVE
    assert again.edges[0].governance_chain == (retracted.event_id, restored.event_id)


def test_25_26_broken_governance_history(tmp_path) -> None:
    record = assertion()
    first = retraction(record)
    fork_left = restoration(record, previous=first.event_id)
    fork_right = ThemeRelationGovernanceEvent.build(
        event_type=RelationGovernanceEventType.RESTORED, edge_key=record.edge_key,
        subject_assertion_id=record.relation_assertion_id, reason="a second restoration",
        previous_event_id=first.event_id, provenance=ACTOR, recorded_at=T0 + timedelta(days=3))
    forked = resolve([record], [first, fork_left, fork_right])
    assert forked.status is RelationResolutionStatus.UNRESOLVED and forked.unresolved[0].diagnostics == ("RELATION_FORK",)
    dangling = ThemeRelationGovernanceEvent.build(
        event_type=RelationGovernanceEventType.RESTORED, edge_key=record.edge_key,
        subject_assertion_id=record.relation_assertion_id, reason="orphan restoration",
        previous_event_id="thrgov_" + "0" * 24, provenance=ACTOR, recorded_at=T0 + timedelta(days=1))
    broken = resolve([record], [dangling])
    assert broken.status is RelationResolutionStatus.INVALID_HISTORY
    sequence = resolve([record], [restoration(record, previous="")]) if False else None
    store = ThemeRelationStore.initialize(tmp_path / "d")
    store.append_assertion(record)
    with pytest.raises(RelationAppendRejected) as info:
        store.append_event(ThemeRelationGovernanceEvent.build(
            event_type=RelationGovernanceEventType.RESTORED, edge_key=record.edge_key,
            subject_assertion_id=record.relation_assertion_id, reason="restore before any retraction",
            provenance=ACTOR, recorded_at=T0 + timedelta(days=1)))
    assert info.value.code == "INVALID_GOVERNANCE_SEQUENCE" and sequence is None


def test_27_governance_order_does_not_decide_the_winner() -> None:
    record = assertion()
    first = retraction(record)
    second = restoration(record, previous=first.event_id)
    base = resolve([record], [first, second]).edges[0].edge_state
    assert base is EdgeState.ACTIVE
    for seed in range(5):
        events = [first, second]
        random.Random(seed).shuffle(events)
        assert resolve([record], events).edges[0].edge_state is base


def test_28_retraction_never_deletes_the_assertion(tmp_path) -> None:
    store = ThemeRelationStore.initialize(tmp_path / "d")
    record = assertion()
    store.append_assertion(record)
    store.append_event(retraction(record))
    assert store.get_assertion(record.relation_assertion_id) == record
    view = build_relation_graph_view(resolve(store.assertions(), store.governance_events()))
    assert view.relations == () and [r.assertion for r in view.retracted] == [record]
    assert view.outgoing(A) == () and view.outgoing(A, include_retracted=True)[0].assertion == record


def test_28b_governance_targeting_another_edge_is_refused(tmp_path) -> None:
    store = ThemeRelationStore.initialize(tmp_path / "d")
    record, other = assertion(), causal(A, C)
    store.append_assertion(record)
    store.append_assertion(other)
    with pytest.raises(RelationAppendRejected) as info:
        store.append_event(ThemeRelationGovernanceEvent.build(
            event_type=RelationGovernanceEventType.RETRACTED, edge_key=record.edge_key,
            subject_assertion_id=other.relation_assertion_id, reason="wrong subject", provenance=ACTOR,
            recorded_at=T0 + timedelta(days=1)))
    assert info.value.code == "INVALID_GOVERNANCE_TARGET"


# ---------------------------------------------------------------- 40〜48 point-in-time


def test_40_41_assertion_visibility_at_the_cutoff() -> None:
    record = assertion(at=T0)
    assert resolve([record], cutoff=T0).status is RelationResolutionStatus.RESOLVED
    later = resolve([record], cutoff=T0 - timedelta(microseconds=1))
    assert later.status is RelationResolutionStatus.NO_STATE and later.edges == ()
    assert [d.code for d in later.diagnostics] == ["FUTURE_RELATION"]


def test_42_43_governance_visibility_at_the_cutoff() -> None:
    record = assertion()
    event = retraction(record, at=T0 + timedelta(days=1))
    at_event = resolve([record], [event], cutoff=T0 + timedelta(days=1))
    assert at_event.edges[0].edge_state is EdgeState.RETRACTED
    before = resolve([record], [event], cutoff=T0 + timedelta(days=1) - timedelta(microseconds=1))
    assert before.edges[0].edge_state is EdgeState.ACTIVE
    assert [d.code for d in before.diagnostics] == ["FUTURE_GOVERNANCE"]


@pytest.mark.parametrize("missing", [A, B])
def test_44_45_an_endpoint_that_does_not_exist_yet_removes_the_edge(missing) -> None:
    created = {A: T0, B: T0}
    created[missing] = T0 + timedelta(days=30)
    resolution = resolve([assertion()], endpoint=endpoint_lookup_from_roots(created))
    assert resolution.status is RelationResolutionStatus.NO_STATE and resolution.edges == ()
    assert resolution.excluded[0].reason == "ENDPOINT_NOT_AVAILABLE_AT_CUTOFF:NOT_CREATED_YET"
    assert [d.code for d in resolution.diagnostics] == ["ENDPOINT_NOT_AVAILABLE_AT_CUTOFF"]
    unknown = resolve([assertion()], endpoint=endpoint_lookup_from_roots({A: T0}))
    assert unknown.excluded[0].reason == "ENDPOINT_NOT_AVAILABLE_AT_CUTOFF:UNKNOWN_ROOT"


def test_46_47_retired_and_superseded_endpoints_are_kept_without_rewriting() -> None:
    retired = resolve([assertion()], endpoint=lookup(A, B, retired=(B,)))
    assert retired.status is RelationResolutionStatus.RESOLVED
    assert retired.edges[0].target_endpoint is EndpointState.RETIRED
    assert "ENDPOINT_RETIRED:TARGET" in retired.edges[0].diagnostics
    superseded = resolve([assertion()], endpoint=lookup(A, B, superseded=(A,)))
    edge = superseded.edges[0]
    assert edge.source_endpoint is EndpointState.SUPERSEDED and "ENDPOINT_SUPERSEDED:SOURCE" in edge.diagnostics
    assert edge.source_theme_root_id == A and edge.target_theme_root_id == B      # 後継へ書き換えない
    assert C not in (edge.source_theme_root_id, edge.target_theme_root_id)


def test_48_no_theme_observation_is_required() -> None:
    resolution = resolve([assertion()], endpoint=lambda root_id, cutoff: EndpointState.EXISTS_AT_CUTOFF)
    assert resolution.status is RelationResolutionStatus.RESOLVED and len(resolution.edges) == 1
    from tests.intelligence.test_prediction_record import imported_modules
    from pathlib import Path

    package = Path(__file__).resolve().parents[2] / "src" / "intelligence" / "theme_intelligence"
    for name in ("relation_model", "relation_resolution", "relation_graph", "relation_store"):
        imports = imported_modules(package / f"{name}.py")
        assert not any(m.endswith(("themes.store", "themes.operations", "themes.revision", "themes.resolver"))
                       for m in imports), name


# ---------------------------------------------------------------- 49〜58 graph view


@pytest.fixture()
def sample():
    ab = causal(A, B)
    bc = assertion(B, C, relation_type=RelationType.MITIGATES)
    ba = assertion(B, A, relation_type=RelationType.DEPENDS_ON)
    cd = sourced(C, D)
    return ab, bc, ba, cd, view_of([ab, bc, ba, cd])


def test_49_51_direction_aware_queries(sample) -> None:
    ab, bc, ba, cd, view = sample
    assert [r.edge_key for r in view.outgoing(A)] == [ab.edge_key]
    assert [r.edge_key for r in view.incoming(A)] == [ba.edge_key]
    neighbours = view.neighbors(A)
    assert [(n.direction, n.root_id) for n in neighbours] == [(Direction.INCOMING, B), (Direction.OUTGOING, B)]
    assert all(n.relation.source_theme_root_id == A for n in neighbours if n.direction is Direction.OUTGOING)
    assert all(n.relation.target_theme_root_id == A for n in neighbours if n.direction is Direction.INCOMING)
    assert view.roots() == tuple(sorted({A, B, C, D}))


def test_52_53_relations_between_and_by_type(sample) -> None:
    ab, bc, ba, cd, view = sample
    between = view.relations_between(A, B)
    assert {r.edge_key for r in between} == {ab.edge_key, ba.edge_key}
    assert view.relations_between(A, D) == ()
    assert [r.edge_key for r in view.relations_by_type(RelationType.CAUSES)] == [ab.edge_key]
    assert [r.edge_key for r in view.relations_by_type(RelationType.MITIGATES)] == [bc.edge_key]
    amplifies = view.relations_by_type(RelationType.AMPLIFIES)
    assert [r.assertion_class for r in amplifies] == [AssertionClass.SOURCE_ASSERTED]
    assert amplifies[0].attribution_key == "publisher:example_wire" and amplifies[0].edge_key == cd.edge_key
    assert view.relations_by_type(RelationType.DEPENDS_ON)[0].attribution_key == ""
    assert view.view_version == RELATION_GRAPH_VIEW_VERSION


def test_54_55_opposite_directions_are_distinct_and_feedback_loops_stay_valid(sample) -> None:
    ab, bc, ba, cd, view = sample
    assert ab.edge_key != ba.edge_key and len(view.relations_between(A, B)) == 2
    assert view.status is RelationResolutionStatus.RESOLVED
    loops = [d for d in view.diagnostics if d.code == "FEEDBACK_LOOP_PRESENT"]
    assert len(loops) == 1 and set(loops[0].detail.split(",")) == {A, B}
    mutual = view_of([causal(A, B), causal(B, A)])
    assert mutual.status is RelationResolutionStatus.RESOLVED and len(mutual.relations) == 2


def test_56_the_graph_never_derives_a_transitive_relation() -> None:
    view = view_of([causal(A, B), causal(B, C)])
    assert {(r.source_theme_root_id, r.target_theme_root_id) for r in view.relations} == {(A, B), (B, C)}
    assert view.relations_between(A, C) == () and view.outgoing(A) == view.relations_by_type(RelationType.CAUSES)[:1]
    assert all(r.target_theme_root_id != C for r in view.outgoing(A))
    assert len(view.relations_by_type(RelationType.CAUSES)) == 2


def test_57_the_view_is_deterministic_and_carries_no_ranking(sample) -> None:
    ab, bc, ba, cd, view = sample
    records = [ab, bc, ba, cd]
    plain = view.to_plain()
    for seed in range(10):
        shuffled = list(records)
        random.Random(seed).shuffle(shuffled)
        assert view_of(shuffled).to_plain() == plain, seed
    assert [r["edge_key"] for r in plain["relations"]] == sorted(r["edge_key"] for r in plain["relations"])
    text = json.dumps(plain).lower()
    for token in ("score", "rank", "weight", "confidence", "centrality", "importance", "pagerank", "recommend"):
        assert token not in text, token


def test_58_retracted_edges_leave_the_active_graph_but_stay_queryable() -> None:
    record = causal(A, B)
    other = assertion(B, C)
    view = view_of([record, other], [retraction(record)])
    assert [r.assertion for r in view.relations] == [other]
    assert [r.assertion for r in view.retracted] == [record]
    assert view.relations_by_type(RelationType.CAUSES) == ()
    assert view.relations_by_type(RelationType.CAUSES, include_retracted=True)[0].assertion == record
    assert view.relations_between(A, B, include_retracted=True)[0].edge_state is EdgeState.RETRACTED
