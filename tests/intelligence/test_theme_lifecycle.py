"""P6-B2 — Theme lifecycle view（`theme_intelligence.lifecycle`）の契約 test（test matrix 1〜41）。

入力は A4d 代表 world と合成 ThemeHistory。書き込みは tmp_path のみ。B1 ChangeSet は入力にしない（snapshot 意味論）。
"""
from __future__ import annotations

import dataclasses
import random
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.theme_intelligence import lifecycle as L
from src.intelligence.theme_intelligence.lifecycle_model import (
    DEFAULT_STALE_AFTER_DAYS, LIFECYCLE_MODEL_VERSION, LIFECYCLE_POLICY_SCHEMA_VERSION, LIFECYCLE_VIEW_SCHEMA_VERSION,
    EvidenceConditionFlag, EvidenceConditionStatus, GovernanceLifecycleState, LifecyclePolicy, LifecycleViewStatus,
    ThemeLifecycleError, ThemeLifecycleView, default_lifecycle_policy,
)
from src.intelligence.themes import operations as O
from src.intelligence.themes.model import EvidenceRole, EvidenceTimeQuality, GovernanceEventType
from src.intelligence.themes.qualification import QualificationStatus
from src.intelligence.themes.resolver import (
    GovernanceStatus, ResolutionStatus, ThemeHistory, resolve, resolve_at_data_root,
)
from src.intelligence.themes.revision import attach_evidence, revise_observation
from src.intelligence.themes.store import ThemeStore
from tests.intelligence.test_theme_foundation_e2e import split_world, successor_world
from tests.intelligence.test_theme_foundation_remediation import IDENTITY_BREAKS, rebuilt
from tests.intelligence.test_theme_change import extended, forked_semantic, invalidated, shuffled, terminal
from tests.intelligence.test_theme_model import (
    FACT_A, ROOT_A, ROOT_B, ROOT_C, attachment, event, mapping, metadata, provenance,
)
from tests.intelligence.theme_foundation_fixtures import (
    CHECKPOINTS, ROOT_M, ROOT_N, ROOT_X, ROOT_Y, ROOT_Z, World, build_world, day,
)

F = EvidenceConditionFlag
G = GovernanceLifecycleState
POLICY = default_lifecycle_policy()
NEWS_TIME = day(-4)                                          # world の最新 counted evidence（2026-08-28）


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    return build_world(tmp_path_factory.mktemp("lifecycle_world") / "data")


@pytest.fixture(scope="module")
def history(world: World) -> ThemeHistory:
    return ThemeHistory.from_store(ThemeStore.open(world.data_root, read_only=True))


def view(world: World, root_key: str, checkpoint: str, **kw) -> ThemeLifecycleView:
    return L.derive_lifecycle(world.resolve(root_key, checkpoint), policy=POLICY, **kw)


def at(history: ThemeHistory, root_id: str, cutoff, **kw) -> ThemeLifecycleView:
    return L.derive_lifecycle(resolve(history, root_id, cutoff), policy=kw.pop("policy", POLICY), **kw)


def flags(v: ThemeLifecycleView) -> set:
    return set(v.evidence.flags)


# ---------------------------------------------------------------- 1〜10 governance layer

def test_01_unreviewed(world: World) -> None:
    v = view(world, "A", "genesis_visible")
    assert v.governance.state is G.UNREVIEWED and v.governance.status is GovernanceStatus.NO_GOVERNANCE
    assert v.governance.effective_event_type is None and v.status is LifecycleViewStatus.AVAILABLE
    assert v.schema_version == LIFECYCLE_VIEW_SCHEMA_VERSION and v.lifecycle_model_version == LIFECYCLE_MODEL_VERSION


def test_02_accepted(world: World) -> None:
    v = view(world, "A", "accepted")
    assert v.governance.state is G.ACCEPTED and v.governance.effective_event_type is GovernanceEventType.CANDIDATE_ACCEPTED
    assert v.governance.effective_event_id == world.ids["A.accepted"] == v.governance.state_event_id


def test_03_rejected(history: ThemeHistory) -> None:
    rejected = event(event_type=GovernanceEventType.CANDIDATE_REJECTED, subject_roots=(ROOT_B,), reason="no mechanism",
                     recorded_at=day(1))
    v = at(extended(history, events=(rejected,)), ROOT_B, day(2))
    assert v.governance.state is G.REJECTED and v.status is LifecycleViewStatus.AVAILABLE


def test_04_retired(world: World) -> None:
    assert view(world, "A", "retired").governance.state is G.RETIRED


def test_05_merge(world: World) -> None:
    subject = view(world, "A", "merge_completed")
    assert subject.governance.state is G.MERGED and subject.governance.effective_event_type is GovernanceEventType.MERGE
    result = view(world, "C", "merge_completed")
    assert result.governance.state is G.UNREVIEWED and result.governance.effective_event_type is GovernanceEventType.MERGE
    assert [d.code for d in result.diagnostics] == ["ORIGIN_EVENT_ONLY"]          # 宣言 event は受理決定ではない
    assert view(world, "A", "merge_declared_incomplete").governance.state is G.MERGED   # 宣言だけでも subject は MERGED


def test_06_split(tmp_path: Path) -> None:
    root = tmp_path / "split"
    times, _genesis, plan = split_world(root)
    assert O.execute_declaration(ThemeStore.open(root), plan).status is O.OperationStatus.COMPLETE
    cutoff = max(times.values()) + timedelta(hours=1)
    subject = L.derive_lifecycle(resolve_at_data_root(root, ROOT_X, cutoff), policy=POLICY)
    assert subject.governance.state is G.SPLIT
    for child in (ROOT_Y, ROOT_Z):
        v = L.derive_lifecycle(resolve_at_data_root(root, child, cutoff), policy=POLICY)
        assert v.governance.state is G.UNREVIEWED and [d.code for d in v.diagnostics] == ["ORIGIN_EVENT_ONLY"]


def test_07_superseded(tmp_path: Path) -> None:
    root = tmp_path / "successor"
    times, _genesis, plan = successor_world(root)
    assert O.execute_declaration(ThemeStore.open(root), plan).status is O.OperationStatus.COMPLETE
    cutoff = max(times.values()) + timedelta(hours=1)
    old = L.derive_lifecycle(resolve_at_data_root(root, ROOT_M, cutoff), policy=POLICY)
    new = L.derive_lifecycle(resolve_at_data_root(root, ROOT_N, cutoff), policy=POLICY)
    assert old.governance.state is G.SUPERSEDED and old.governance.effective_event_type is GovernanceEventType.SUPERSEDED_BY_ROOT
    assert new.governance.state is G.UNREVIEWED and [d.code for d in new.diagnostics] == ["ORIGIN_EVENT_ONLY"]


def test_08_event_reversed_restores_prior_state(world: World) -> None:
    v = view(world, "A", "retirement_reversed")
    assert v.governance.state is G.ACCEPTED and v.governance.effective_event_type is GovernanceEventType.CANDIDATE_ACCEPTED
    assert v.governance.effective_event_id == world.ids["A.accepted"]
    assert view(world, "A", "retired").governance.state is G.RETIRED


def corrected(world: World, history: ThemeHistory):
    obs = terminal(world, history)
    corrected_attachments = tuple(dataclasses.replace(a, role=EvidenceRole.CONTRADICTS) if a.ref_id == FACT_A else a
                                  for a in obs.attachments)
    revised = revise_observation(obs, recorded_at=day(13), provenance=provenance(reason="role"), attachments=corrected_attachments)
    approval = event(event_type=GovernanceEventType.ROLE_CORRECTION_APPROVED, related_observations=(revised.observation_id,),
                     previous_event_ids=((ROOT_A, world.ids["A.reversed"]),), reason="role corrected", recorded_at=day(13, 1))
    return extended(history, revised, events=(approval,)), approval


def test_09_correction_event_does_not_alter_lifecycle_state(world: World, history: ThemeHistory) -> None:
    h, approval = corrected(world, history)
    res = resolve(h, ROOT_A, day(13, 6))
    assert res.governance.effective_event_type is GovernanceEventType.ROLE_CORRECTION_APPROVED
    v = L.derive_lifecycle(res, policy=POLICY, governance_events=h.events)
    assert v.governance.state is G.ACCEPTED and v.governance.state_event_id == world.ids["A.accepted"]
    assert v.governance.effective_event_id == approval.event_id
    assert [d.code for d in v.diagnostics] == ["CORRECTION_TERMINAL_IGNORED"]
    with pytest.raises(ThemeLifecycleError, match="GOVERNANCE_EVENTS_REQUIRED"):       # 推測しない
        L.derive_lifecycle(res, policy=POLICY)
    with pytest.raises(ThemeLifecycleError, match="GOVERNANCE_EVENTS_INCOMPLETE"):
        L.derive_lifecycle(res, policy=POLICY, governance_events=(approval,))
    # 訂正だけで受理が無い root は UNREVIEWED のまま
    only = extended(history, events=(event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED,
                                            subject_roots=(ROOT_B,), related_observations=("thmeta_" + "1" * 24,),
                                            reason="typo", recorded_at=day(1)),))
    res_b = resolve(only, ROOT_B, day(2))
    assert res_b.governance.status is GovernanceStatus.RESOLVED
    assert L.derive_lifecycle(res_b, policy=POLICY, governance_events=only.events).governance.state is G.UNREVIEWED


def test_10_governance_unresolved(world: World, history: ThemeHistory) -> None:
    left = event(event_type=GovernanceEventType.RETIRED, reason="a", previous_event_ids=((ROOT_A, world.ids["A.reversed"]),),
                 recorded_at=day(13))
    right = event(event_type=GovernanceEventType.RETIRED, reason="b", previous_event_ids=((ROOT_A, world.ids["A.reversed"]),),
                  recorded_at=day(13, 6))
    v = at(extended(history, events=(right, left)), ROOT_A, day(13, 12))
    assert v.governance.state is G.UNRESOLVED and v.governance.status is GovernanceStatus.UNRESOLVED
    assert v.governance.effective_event_id == "" and [d.code for d in v.diagnostics] == ["GOVERNANCE_UNRESOLVED"]


# ---------------------------------------------------------------- 11〜20 evidence layer

def test_11_no_visible_evidence(world: World) -> None:
    v = view(world, "A", "genesis_visible")
    assert flags(v) == {F.NO_VISIBLE_EVIDENCE} and v.evidence.status is EvidenceConditionStatus.EVALUATED
    assert (v.evidence.visible_evidence_count, v.evidence.counted_evidence_count, v.evidence.independent_origin_count,
            v.evidence.evidence_date_count) == (0, 0, 0, 0)
    assert F.STALE not in flags(v) and [d.code for d in v.diagnostics] == ["STALE_NOT_EVALUABLE_NO_DATED_EVIDENCE"]


def test_12_single_source(world: World) -> None:
    v = view(world, "A", "first_evidence")
    assert F.SINGLE_SOURCE in flags(v) and F.MULTI_SOURCE not in flags(v) and v.evidence.independent_origin_count == 1


def test_13_multi_source(world: World) -> None:
    v = view(world, "A", "second_independent_evidence")
    assert F.MULTI_SOURCE in flags(v) and F.SINGLE_SOURCE not in flags(v) and v.evidence.independent_origin_count == 2


def test_14_single_date(world: World) -> None:
    v = view(world, "A", "first_evidence")
    assert F.SINGLE_EVIDENCE_DATE in flags(v) and v.evidence.evidence_date_count == 1


def test_15_multi_date(world: World) -> None:
    v = view(world, "A", "second_independent_evidence")
    assert F.MULTI_DATE in flags(v) and v.evidence.evidence_date_count == 2


def test_16_qualifies(world: World) -> None:
    assert F.QUALIFIES not in flags(view(world, "A", "first_evidence"))
    v = view(world, "A", "second_independent_evidence")
    assert F.QUALIFIES in flags(v) and v.evidence.qualification_status is QualificationStatus.QUALIFIES_SEMANTICALLY


def test_17_contested(world: World) -> None:
    assert F.CONTESTED not in flags(view(world, "A", "second_independent_evidence"))
    assert F.CONTESTED in flags(view(world, "A", "contradiction_added"))


def test_18_invalidation_present(world: World, history: ThemeHistory) -> None:
    h, inv = invalidated(world, history)
    v = at(h, ROOT_A, day(13, 3))
    assert F.INVALIDATION_EVIDENCE_PRESENT in flags(v)
    assert F.INVALIDATION_EVIDENCE_PRESENT not in flags(at(h, ROOT_A, day(13, 9)))


def test_19_contested_and_qualifies_coexist(world: World) -> None:
    v = view(world, "A", "contradiction_added")
    assert {F.CONTESTED, F.QUALIFIES, F.MULTI_SOURCE, F.MULTI_DATE, F.HAS_SUPPORT} <= flags(v)


def test_20_invalidation_does_not_auto_retire(world: World, history: ThemeHistory) -> None:
    h, inv = invalidated(world, history)
    v = at(h, ROOT_A, day(13, 3))
    assert F.INVALIDATION_EVIDENCE_PRESENT in flags(v) and v.governance.state is G.ACCEPTED
    assert v.status is LifecycleViewStatus.AVAILABLE


# ---------------------------------------------------------------- 21〜27 freshness

@pytest.mark.parametrize("days,stale", [(89, False), (90, True), (91, True)])
def test_21_23_stale_boundary(history: ThemeHistory, days: int, stale: bool) -> None:
    v = at(history, ROOT_A, NEWS_TIME + timedelta(days=days))
    assert (F.STALE in flags(v)) is stale
    assert v.evidence.latest_dated_evidence_time == NEWS_TIME and v.evidence.elapsed_calendar_days == days
    assert v.evidence.stale_after_days == 90 and v.policy == POLICY


def test_23b_stale_uses_calendar_days_not_elapsed_hours(history: ThemeHistory) -> None:
    cutoff = NEWS_TIME + timedelta(days=89, hours=23)                    # 89 日 23 時間 ＝ calendar 89 日
    assert F.STALE not in flags(at(history, ROOT_A, cutoff))
    cutoff = NEWS_TIME + timedelta(days=90, minutes=1)
    assert F.STALE in flags(at(history, ROOT_A, cutoff))


def test_24_custom_policy_30d(history: ThemeHistory) -> None:
    policy = LifecyclePolicy(stale_after_days=30)
    cutoff = NEWS_TIME + timedelta(days=30)
    v = at(history, ROOT_A, cutoff, policy=policy)
    assert F.STALE in flags(v) and v.evidence.stale_after_days == 30 and v.policy.stale_after_days == 30
    assert F.STALE not in flags(at(history, ROOT_A, cutoff))            # 既定 90 日では STALE ではない
    assert F.STALE not in flags(at(history, ROOT_A, NEWS_TIME + timedelta(days=29), policy=policy))


def test_25_missing_or_uncounted_evidence_time_is_ignored_for_freshness(world: World, history: ThemeHistory) -> None:
    obs = terminal(world, history)
    missing = attachment("fact_" + "5" * 24, role=EvidenceRole.CONTEXT, quality=EvidenceTimeQuality.MISSING, cref="",
                         attached=day(13))                                            # evidence_time 無し
    dated_context = attachment("fact_" + "6" * 24, role=EvidenceRole.CONTEXT, cref="", day="2026-09-10",
                               attached=day(13))                                      # 新しいが counted ではない
    h = extended(history, attach_evidence(obs, (missing, dated_context), recorded_at=day(13),
                                          provenance=provenance(reason="context")))
    res = resolve(h, ROOT_A, day(13, 6))
    assert [a.ref_id for a in res.evidence.context_without_time] == [missing.ref_id]  # Foundation が view 外に分離
    v = L.derive_lifecycle(res, policy=POLICY)
    assert v.evidence.latest_dated_evidence_time == NEWS_TIME                          # 09-10 の CONTEXT は使わない
    assert v.evidence.visible_evidence_count == 5 and v.evidence.counted_evidence_count == 4
    assert F.HAS_CONTEXT_ONLY not in flags(v) and F.STALE not in flags(v)


def test_26_no_dated_evidence_gives_diagnostic_not_stale(world: World, history: ThemeHistory) -> None:
    v = view(world, "A", "genesis_visible")
    assert F.STALE not in flags(v) and v.evidence.latest_dated_evidence_time is None
    assert v.evidence.elapsed_calendar_days is None
    assert [d.code for d in v.diagnostics] == ["STALE_NOT_EVALUABLE_NO_DATED_EVIDENCE"]
    genesis = next(o for o in history.observations if o.observation_id == world.ids["A.genesis"])
    context_only = revise_observation(genesis, recorded_at=day(0, 2), provenance=provenance(reason="ctx"),
                                      attachments=(attachment("fact_" + "5" * 24, role=EvidenceRole.CONTEXT, cref="",
                                                              day="2026-08-30", attached=day(0, 2)),))
    forked_free = ThemeHistory(history.roots, tuple(o for o in history.observations if o.root_id != ROOT_A) + (genesis, context_only),
                               history.events, history.metadata, history.mappings)
    v = at(forked_free, ROOT_A, day(0, 3))
    assert flags(v) == {F.NO_VISIBLE_EVIDENCE, F.HAS_CONTEXT_ONLY} and v.evidence.visible_evidence_count == 1
    assert v.evidence.latest_dated_evidence_time is None                             # dated でも counted ではない
    assert [d.code for d in v.diagnostics] == ["STALE_NOT_EVALUABLE_NO_DATED_EVIDENCE"]


def test_27_future_evidence_is_invisible(world: World) -> None:
    before = view(world, "A", "delayed_evidence_before_attachment")
    after = view(world, "A", "delayed_evidence_after_attachment")
    assert before.evidence.latest_dated_evidence_time == day(-6)          # BOJ 2026-08-26
    assert after.evidence.latest_dated_evidence_time == NEWS_TIME          # NEWS 2026-08-28（付与後にだけ見える）
    assert before.evidence.counted_evidence_count == 3 and after.evidence.counted_evidence_count == 4


# ---------------------------------------------------------------- 28〜32 unresolved / no-state / partial

def test_28_semantic_unresolved(world: World, history: ThemeHistory) -> None:
    v = at(forked_semantic(world, history), ROOT_A, day(13, 12))
    assert v.evidence.status is EvidenceConditionStatus.UNRESOLVED and v.evidence.flags == ()
    assert v.governance.state is G.ACCEPTED and v.status is LifecycleViewStatus.PARTIALLY_AVAILABLE
    assert [d.code for d in v.diagnostics] == ["SEMANTIC_UNRESOLVED"]


def test_29_no_state(world: World) -> None:
    for checkpoint in ("before_root", "root_only"):
        v = view(world, "A", checkpoint)
        assert v.status is LifecycleViewStatus.UNAVAILABLE and v.resolution_status is ResolutionStatus.NO_STATE
        assert v.governance.state is G.NOT_AVAILABLE and v.evidence.status is EvidenceConditionStatus.NOT_EVALUATED
        assert v.diagnostics[0].code == "NO_THEME_STATE"
    root_only = view(world, "A", "root_only")
    assert "PENDING_GENESIS" in root_only.diagnostics[0].related
    declared = view(world, "C", "merge_declared_incomplete")
    assert declared.governance.state is G.NOT_AVAILABLE and "PENDING_EVENT" in declared.diagnostics[0].related


def test_30_governance_unresolved_with_semantic_resolved_is_partial(world: World, history: ThemeHistory) -> None:
    left = event(event_type=GovernanceEventType.RETIRED, reason="a", previous_event_ids=((ROOT_A, world.ids["A.reversed"]),),
                 recorded_at=day(13))
    right = event(event_type=GovernanceEventType.RETIRED, reason="b", previous_event_ids=((ROOT_A, world.ids["A.reversed"]),),
                  recorded_at=day(13, 6))
    v = at(extended(history, events=(right, left)), ROOT_A, day(13, 12))
    assert v.status is LifecycleViewStatus.PARTIALLY_AVAILABLE
    assert v.governance.state is G.UNRESOLVED and v.evidence.status is EvidenceConditionStatus.EVALUATED
    assert flags(v) == flags(view(world, "A", "retirement_reversed"))


def test_31_metadata_unresolved_has_no_effect(world: World, history: ThemeHistory) -> None:
    left = metadata(value=("L",), previous_metadata_id=world.ids["A.label1"], recorded_at=day(13))
    right = metadata(value=("R",), previous_metadata_id=world.ids["A.label1"], recorded_at=day(13, 6))
    v = at(extended(history, metadata=(right, left)), ROOT_A, day(13, 12))
    base = at(history, ROOT_A, day(13, 12))
    assert v.status is LifecycleViewStatus.AVAILABLE and v.governance == base.governance and v.evidence == base.evidence


def test_32_mapping_unresolved_has_no_effect(world: World, history: ThemeHistory) -> None:
    left = mapping(series_ref="a.series", supersedes_mapping_id=world.ids["A.map1"], recorded_at=day(13), valid_from=day(13))
    right = mapping(series_ref="b.series", supersedes_mapping_id=world.ids["A.map1"], recorded_at=day(13, 6),
                    valid_from=day(13, 6))
    v = at(extended(history, mappings=(right, left)), ROOT_A, day(13, 12))
    base = at(history, ROOT_A, day(13, 12))
    assert v.status is LifecycleViewStatus.AVAILABLE and v.governance == base.governance and v.evidence == base.evidence


# ---------------------------------------------------------------- 33〜37 determinism / policy / vocabulary

def test_33_same_resolution_is_deterministic(world: World) -> None:
    res = world.resolve("A", "contradiction_added")
    first, second = L.derive_lifecycle(res, policy=POLICY), L.derive_lifecycle(res, policy=POLICY)
    assert first == second and hash(first) == hash(second)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.status = LifecycleViewStatus.UNAVAILABLE                    # type: ignore[misc]


def test_34_shuffled_history_is_deterministic(history: ThemeHistory) -> None:
    for seed in (3, 11, 29):
        h = shuffled(history, seed)
        for root_id in (ROOT_A, ROOT_B, ROOT_C):
            for checkpoint in ("first_evidence", "accepted", "retirement_reversed", "merge_completed"):
                assert at(h, root_id, CHECKPOINTS[checkpoint]) == at(history, root_id, CHECKPOINTS[checkpoint])


def test_35_policy_value_is_reflected_in_the_output(history: ThemeHistory) -> None:
    policy = LifecyclePolicy(stale_after_days=45)
    v = at(history, ROOT_A, CHECKPOINTS["accepted"], policy=policy)
    assert v.policy is policy and v.policy.schema_version == LIFECYCLE_POLICY_SCHEMA_VERSION
    assert v.evidence.stale_after_days == 45 and default_lifecycle_policy().stale_after_days == DEFAULT_STALE_AFTER_DAYS == 90
    for bad in (0, -1, True, 1.5, "90"):
        with pytest.raises(ThemeLifecycleError, match="INVALID_POLICY"):
            LifecyclePolicy(stale_after_days=bad)                          # type: ignore[arg-type]
    with pytest.raises(ThemeLifecycleError, match="INVALID_POLICY"):
        L.derive_lifecycle(resolve(history, ROOT_A, CHECKPOINTS["accepted"]), policy=None)   # type: ignore[arg-type]


FORBIDDEN_WORDS = ("EMERGING", "ACCELERATING", "MATURE", "WEAKENING", "STRONG", "WEAK", "HOT", "COLD", "BULLISH", "BEARISH",
                   "WINNING", "LOSING", "HIGH_CONVICTION", "LOW_CONVICTION", "SCORE", "RANK", "TIER", "WEIGHT", "CONFIDENCE")


def test_36_no_score_or_rank_in_the_view(history: ThemeHistory) -> None:
    v = at(history, ROOT_A, CHECKPOINTS["merge_completed"])
    for cls in (ThemeLifecycleView, type(v.governance), type(v.evidence), LifecyclePolicy):
        for field in dataclasses.fields(cls):
            assert not any(word in field.name.upper() for word in FORBIDDEN_WORDS), field.name
            assert field.type not in (float, "float")
    numeric = {f.name: getattr(v.evidence, f.name) for f in dataclasses.fields(v.evidence)
               if isinstance(getattr(v.evidence, f.name), int)}
    assert set(numeric) == {"visible_evidence_count", "counted_evidence_count", "independent_origin_count",
                            "evidence_date_count", "elapsed_calendar_days", "stale_after_days"}     # 件数と日数のみ


def test_37_no_momentum_or_market_vocabulary() -> None:
    for enum in (GovernanceLifecycleState, EvidenceConditionFlag, LifecycleViewStatus, EvidenceConditionStatus):
        for member in enum:
            assert not any(word in member.value for word in FORBIDDEN_WORDS), member
    assert {s.value for s in GovernanceLifecycleState} == {"UNREVIEWED", "ACCEPTED", "REJECTED", "RETIRED", "MERGED", "SPLIT",
                                                            "SUPERSEDED", "UNRESOLVED", "NOT_AVAILABLE"}
    assert {f.value for f in EvidenceConditionFlag} >= {"NO_VISIBLE_EVIDENCE", "SINGLE_SOURCE", "SINGLE_EVIDENCE_DATE",
                                                        "MULTI_SOURCE", "MULTI_DATE", "QUALIFIES", "CONTESTED",
                                                        "INVALIDATION_EVIDENCE_PRESENT", "STALE"}


# ---------------------------------------------------------------- failure inputs

def test_invalid_or_corrupt_resolution_is_unavailable(world: World, history: ThemeHistory, tmp_path: Path) -> None:
    obs = terminal(world, history)
    broken = extended(history, rebuilt(obs, recorded_at=day(13), **IDENTITY_BREAKS["driver"]()))
    v = at(broken, ROOT_A, day(13, 12))
    assert v.status is LifecycleViewStatus.UNAVAILABLE and v.resolution_status is ResolutionStatus.INVALID_HISTORY
    assert v.governance.state is G.NOT_AVAILABLE and v.evidence.status is EvidenceConditionStatus.NOT_EVALUATED
    assert [(d.code, d.related) for d in v.diagnostics] == [("RESOLUTION_UNAVAILABLE", ("IDENTITY_CORE_CHANGED",))]
    foreign = dataclasses.replace(world.resolve("A", "accepted"), resolver_version="theme_resolver:9.9.9")
    with pytest.raises(ThemeLifecycleError, match="RESOLVER_VERSION_INCOMPATIBLE"):
        L.derive_lifecycle(foreign, policy=POLICY)


def test_lifecycle_does_not_take_change_sets_as_input() -> None:
    import inspect
    params = inspect.signature(L.derive_lifecycle).parameters
    assert list(params) == ["resolution", "policy", "governance_events"]
    assert "change" not in " ".join(params) and not hasattr(L, "derive_lifecycle_transition")
