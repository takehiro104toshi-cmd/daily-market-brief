"""P6-A4b — 宣言先行の論理操作（candidate / merge / split / successor）、crash 境界ごとの PENDING と冪等な再試行、evidence 配分。"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.themes import operations as O
from src.intelligence.themes.model import (
    CreationMethod, EvidenceAllocation, EvidenceKind, GovernanceEventType, MechanismCertainty, ProvenanceClass,
    ThemeGovernanceEvent, ThemeObservation, canonical_line, make_root_record,
)
from src.intelligence.themes.store import AppendStatus, PendingKind, ThemeAppendRejected, ThemeStore
from tests.intelligence.test_theme_model import (
    FACT_A, FACT_B, ROOT_A, ROOT_B, ROOT_C, T0, attachment, condition, event, mechanism, observation, provenance,
    root_record, scope, subject,
)
from tests.intelligence.test_theme_store import SimulatedCrash, file_bytes, interrupt_after, seeded

ROOT_D = "theme_0123456789ABCDEFGHJKMNPQRW"
ROOT_E = "theme_0123456789ABCDEFGHJKMNPQRX"
KEY_A = f"{FACT_A}#c1"
KEY_B = f"{FACT_B}#c1"


def genesis_spec(recorded_at, reason="result", **override) -> O.GenesisSpec:
    kwargs = dict(subject=subject(), mechanism=mechanism(), certainty_class=MechanismCertainty.HYPOTHESIZED_MECHANISM,
                  scope=scope(), invalidation_conditions=(condition(),), provenance=provenance(reason=reason),
                  recorded_at=recorded_at)
    kwargs.update(override)
    return O.GenesisSpec(**kwargs)


def result_spec(root_id, source_obs, keys, day_offset=3, **override) -> O.ResultRootSpec:
    created = T0 + timedelta(days=day_offset)
    kwargs = dict(root_id=root_id, created_at=created, creation_provenance="reviewer:r1",
                  genesis=genesis_spec(created + timedelta(hours=1)),
                  carried=tuple((source_obs.observation_id, k) for k in keys))
    kwargs.update(override)
    return O.ResultRootSpec(**kwargs)


def two_roots(tmp_path: Path):
    """root A（genesis obs）と root B（別主題）を持つ store。"""
    store, root_a, obs_a = seeded(tmp_path)
    obs_b = observation(root_id=ROOT_B, subject=subject("tourism inflow and service demand", ""))
    store.append_root(root_record(obs_b))
    store.append_observation(obs_b)
    return store, obs_a, obs_b


def merge_plan(store, obs_a, obs_b, previous=None):
    previous = O.terminal_previous_events(store, (ROOT_A, ROOT_B)) if previous is None else previous
    return O.plan_merge(store, subject_roots=(ROOT_A, ROOT_B),
                        result=result_spec(ROOT_C, obs_a, (KEY_A,)), reason="same mechanism", actor_ref="reviewer:r1",
                        recorded_at=T0 + timedelta(days=2), previous_event_ids=previous)


def split_plan(store, obs_a, previous=None):
    previous = O.terminal_previous_events(store, (ROOT_A,)) if previous is None else previous
    children = (result_spec(ROOT_D, obs_a, (KEY_A,)), result_spec(ROOT_E, obs_a, (KEY_B,)))
    return O.plan_split(store, subject_root=ROOT_A, children=children, reason="two domains", actor_ref="reviewer:r1",
                        recorded_at=T0 + timedelta(days=2), previous_event_ids=previous)


def successor_plan(store, obs_a, previous=None):
    previous = O.terminal_previous_events(store, (ROOT_A,)) if previous is None else previous
    return O.plan_successor(store, subject_root=ROOT_A, result=result_spec(ROOT_D, obs_a, (KEY_A,)),
                            reason="driver replaced", actor_ref="reviewer:r1", recorded_at=T0 + timedelta(days=2),
                            previous_event_ids=previous)


def crash_then_retry(tmp_path: Path, store, plan, allowed_writes: int, expected_pending_kinds, expected_missing: int):
    """allowed_writes 回の write の後で crash → 再 open → PENDING 確認 → 同じ plan で再実行 → 完了。"""
    interrupt_after(store, allowed_writes)
    with pytest.raises(SimulatedCrash):
        O.execute_declaration(store, plan)
    reopened = ThemeStore.open(tmp_path)
    pending = reopened.pending()
    assert [p.kind for p in pending] == expected_pending_kinds
    assert sum(len(p.missing) for p in pending) == expected_missing
    before = {n: file_bytes(reopened, n) for n in ("roots", "observations", "governance")}
    assert {n: file_bytes(ThemeStore.open(tmp_path), n) for n in before} == before   # load は補完しない
    result = O.execute_declaration(reopened, plan)
    assert result.status is O.OperationStatus.COMPLETE and reopened.pending() == ()
    return reopened, result


# ---------------------------------------------------------------- candidate

def test_candidate_plan_is_deterministic_and_execution_is_idempotent(tmp_path: Path) -> None:
    store = ThemeStore.initialize(tmp_path)
    spec = genesis_spec(T0 + timedelta(hours=1), reason="draft")
    plan = O.plan_candidate(root_id=ROOT_A, created_at=T0, creator_class=ProvenanceClass.HUMAN,
                            creation_provenance="reviewer:r1", genesis=spec,
                            attachments=(attachment(FACT_A), attachment(FACT_B, day="2026-08-21")))
    again = O.plan_candidate(root_id=ROOT_A, created_at=T0, creator_class=ProvenanceClass.HUMAN,
                             creation_provenance="reviewer:r1", genesis=spec,
                             attachments=(attachment(FACT_B, day="2026-08-21"), attachment(FACT_A)))
    assert plan == again and plan.root.genesis_observation_id == plan.genesis.observation_id
    first = O.execute_candidate(store, plan)
    assert first.status is O.OperationStatus.COMPLETE and [s.status for s in first.steps] == [AppendStatus.APPENDED] * 2
    second = O.execute_candidate(store, plan)
    assert [s.status for s in second.steps] == [AppendStatus.ALREADY_PRESENT] * 2
    assert store.counts() == {"roots": 1, "observations": 1, "governance": 0, "metadata": 0, "mappings": 0}


def test_candidate_crash_after_root_before_genesis(tmp_path: Path) -> None:
    store = ThemeStore.initialize(tmp_path)
    plan = O.plan_candidate(root_id=ROOT_A, created_at=T0, creator_class=ProvenanceClass.HUMAN,
                            creation_provenance="reviewer:r1", genesis=genesis_spec(T0 + timedelta(hours=1)),
                            attachments=(attachment(FACT_A),))
    interrupt_after(store, 1)
    with pytest.raises(SimulatedCrash):
        O.execute_candidate(store, plan)
    reopened = ThemeStore.open(tmp_path)
    assert [(p.kind, p.subject_id, p.missing) for p in reopened.pending()] == [
        (PendingKind.PENDING_GENESIS, ROOT_A, (plan.genesis.observation_id,))]
    assert reopened.counts()["observations"] == 0
    result = O.execute_candidate(reopened, plan)
    assert result.status is O.OperationStatus.COMPLETE
    assert [s.status for s in result.steps] == [AppendStatus.ALREADY_PRESENT, AppendStatus.APPENDED]
    assert reopened.counts() == {"roots": 1, "observations": 1, "governance": 0, "metadata": 0, "mappings": 0}


# ---------------------------------------------------------------- merge

def test_merge_declaration_first_and_order_is_enforced(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    root_c, genesis_c = plan.results[0]
    with pytest.raises(ThemeAppendRejected, match="ORIGIN_EVENT_MISSING"):
        store.append_root(root_c)                                          # event より先の root は拒否
    with pytest.raises(ThemeAppendRejected, match="ROOT_NOT_FOUND"):
        store.append_observation(genesis_c)                                # root より先の genesis は拒否
    result = O.execute_declaration(store, plan)
    assert result.status is O.OperationStatus.COMPLETE and result.operation == "MERGE"
    assert [s.authority for s in result.steps] == ["governance", "roots", "observations"]
    assert store.get_root(ROOT_C).creation_method is CreationMethod.MERGE_RESULT
    assert store.get_root(ROOT_C).origin_event_id == plan.event.event_id
    assert store.physical_terminal_events(ROOT_A) == (plan.event.event_id,)
    assert store.physical_terminal_events(ROOT_B) == (plan.event.event_id,)
    assert store.physical_terminal_events(ROOT_C) == (plan.event.event_id,)
    carried = store.get_observation(genesis_c.observation_id).attachment(KEY_A)
    original = obs_a.attachment(KEY_A)
    assert canonical_line(store.get_observation(obs_a.observation_id)) == canonical_line(obs_a)   # source 不変
    assert carried == original and carried.attached_at == original.attached_at
    assert carried.role_provenance is original.role_provenance
    assert store.get_observation(genesis_c.observation_id).provenance.governance_event_id == plan.event.event_id


@pytest.mark.parametrize("writes,kinds,missing", [
    (1, [PendingKind.PENDING_EVENT], 1),                                   # event の後
    (2, [PendingKind.PENDING_GENESIS, PendingKind.PENDING_EVENT], 2),      # result root の後、genesis の前
])
def test_merge_crash_boundaries(tmp_path: Path, writes, kinds, missing) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    previous = O.terminal_previous_events(store, (ROOT_A, ROOT_B))
    plan = merge_plan(store, obs_a, obs_b, previous)
    reopened, result = crash_then_retry(tmp_path, store, plan, writes, kinds, missing)
    replanned = merge_plan(reopened, obs_a, obs_b, previous)           # 同じ入力 → 同じ id（置換 id を生まない）
    assert replanned == plan
    assert reopened.counts() == {"roots": 3, "observations": 3, "governance": 1, "metadata": 0, "mappings": 0}
    assert [s.status for s in result.steps][:writes] == [AppendStatus.ALREADY_PRESENT] * writes


def test_terminal_previous_events_must_be_captured_before_the_first_attempt(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    interrupt_after(store, 1)
    with pytest.raises(SimulatedCrash):
        O.execute_declaration(store, plan)
    reopened = ThemeStore.open(tmp_path)
    late = merge_plan(reopened, obs_a, obs_b)                             # crash 後に terminal を取り直すと event が変わる
    assert late.event.event_id != plan.event.event_id
    with pytest.raises(ThemeAppendRejected, match="RESULT_ROOT_REDECLARED"):
        O.execute_declaration(reopened, late)
    assert reopened.pending()[0].subject_id == plan.event.event_id      # 元の宣言は PENDING のまま
    assert O.execute_declaration(reopened, plan).status is O.OperationStatus.COMPLETE


# ---------------------------------------------------------------- split

@pytest.mark.parametrize("writes,kinds,missing", [
    (1, [PendingKind.PENDING_EVENT], 2),                                   # event の後（子 root 2 つが未作成）
    (2, [PendingKind.PENDING_GENESIS, PendingKind.PENDING_EVENT], 3),      # 最初の子 root の後
    (3, [PendingKind.PENDING_EVENT], 1),                                   # 最初の子 genesis の後
    (4, [PendingKind.PENDING_GENESIS, PendingKind.PENDING_EVENT], 2),      # 2 つ目の子 root の後、genesis の前
])
def test_split_crash_boundaries(tmp_path: Path, writes, kinds, missing) -> None:
    store, root_a, obs_a = seeded(tmp_path)
    previous = O.terminal_previous_events(store, (ROOT_A,))
    plan = split_plan(store, obs_a, previous)
    assert plan.event.event_type is GovernanceEventType.SPLIT and len(plan.results) == 2
    reopened, result = crash_then_retry(tmp_path, store, plan, writes, kinds, missing)
    assert split_plan(reopened, obs_a, previous) == plan
    assert reopened.counts() == {"roots": 3, "observations": 3, "governance": 1, "metadata": 0, "mappings": 0}
    assert reopened.get_observation(reopened.get_root(ROOT_D).genesis_observation_id).attachment(KEY_A) == obs_a.attachment(KEY_A)
    assert reopened.get_observation(reopened.get_root(ROOT_E).genesis_observation_id).attachment(KEY_B) == obs_a.attachment(KEY_B)
    assert reopened.get_observation(reopened.get_root(ROOT_E).genesis_observation_id).attachment(KEY_A) is None
    assert canonical_line(reopened.get_observation(obs_a.observation_id)) == canonical_line(obs_a)


# ---------------------------------------------------------------- successor

@pytest.mark.parametrize("writes,kinds,missing", [
    (1, [PendingKind.PENDING_EVENT], 1),
    (2, [PendingKind.PENDING_GENESIS, PendingKind.PENDING_EVENT], 2),
])
def test_successor_crash_boundaries(tmp_path: Path, writes, kinds, missing) -> None:
    store, root_a, obs_a = seeded(tmp_path)
    previous = O.terminal_previous_events(store, (ROOT_A,))
    plan = successor_plan(store, obs_a, previous)
    assert plan.event.event_type is GovernanceEventType.SUPERSEDED_BY_ROOT
    reopened, _ = crash_then_retry(tmp_path, store, plan, writes, kinds, missing)
    assert reopened.get_root(ROOT_D).creation_method is CreationMethod.SUCCESSOR_RESULT
    assert reopened.physical_terminal_events(ROOT_A) == (plan.event.event_id,)


# ---------------------------------------------------------------- evidence allocation

def test_allocation_must_reference_existing_source_attachments(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    with pytest.raises(ThemeAppendRejected, match="ALLOCATION_VIOLATION"):
        O.plan_merge(store, subject_roots=(ROOT_A, ROOT_B), result=result_spec(ROOT_C, obs_a, ("fact_nope#c1",)),
                     reason="x", actor_ref="reviewer:r1", recorded_at=T0 + timedelta(days=2), previous_event_ids=())
    bad_event = ThemeGovernanceEvent.build(
        event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A, ROOT_B), result_roots=(ROOT_C,), reason="x",
        actor_ref="reviewer:r1", recorded_at=T0 + timedelta(days=2),
        evidence_allocation=(EvidenceAllocation(source_observation_id=obs_a.observation_id, attachment_key="fact_nope#c1",
                                                result_root_id=ROOT_C),))
    with pytest.raises(ThemeAppendRejected, match="ALLOCATION_VIOLATION"):
        store.append_governance(bad_event)
    foreign = ThemeGovernanceEvent.build(
        event_type=GovernanceEventType.SUPERSEDED_BY_ROOT, subject_roots=(ROOT_A,), result_roots=(ROOT_C,), reason="x",
        actor_ref="reviewer:r1", recorded_at=T0 + timedelta(days=2),
        evidence_allocation=(EvidenceAllocation(source_observation_id=obs_b.observation_id, attachment_key=KEY_A,
                                                result_root_id=ROOT_C),))
    with pytest.raises(ThemeAppendRejected, match="ALLOCATION_VIOLATION"):
        store.append_governance(foreign)                                   # subject 外の root からは配分できない


def _declared_result(store, plan, genesis):
    """plan の event を append し、与えた genesis を宣言する結果 RootRecord を append する（検証用の手組み）。"""
    store.append_governance(plan.event)
    root = make_root_record(root_id=ROOT_C, created_at=T0 + timedelta(days=3), creation_method=CreationMethod.MERGE_RESULT,
                            creator_class=ProvenanceClass.HUMAN, creation_provenance="reviewer:r1",
                            origin_event_id=plan.event.event_id, genesis_observation_id=genesis.observation_id)
    store.append_root(root)
    return root


def _genesis_c(spec, attachments):
    return ThemeObservation.build(root_id=ROOT_C, subject=spec.subject, mechanism=spec.mechanism,
                                  certainty_class=spec.certainty_class, scope=spec.scope,
                                  invalidation_conditions=spec.invalidation_conditions, attachments=attachments,
                                  provenance=spec.provenance, recorded_at=spec.recorded_at)


def test_result_genesis_rejects_unallocated_attachments(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)                                   # KEY_A だけを ROOT_C へ配分
    spec = genesis_spec(T0 + timedelta(days=3, hours=1))
    extra = _genesis_c(spec, (obs_a.attachment(KEY_A), obs_a.attachment(KEY_B)))   # KEY_B は未配分
    _declared_result(store, plan, extra)
    with pytest.raises(ThemeAppendRejected, match="ALLOCATION_VIOLATION") as info:
        store.append_observation(extra)
    assert "not allocated" in info.value.detail
    assert store.pending()[0].kind is PendingKind.PENDING_GENESIS          # 拒否後も宣言は残り、補完されない


def test_result_genesis_rejects_carried_attachment_that_is_not_byte_identical(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    spec = genesis_spec(T0 + timedelta(days=3, hours=1))
    modified = attachment(FACT_A, attached=T0 + timedelta(days=3), day="2026-08-20")   # attached_at を付け替えた carry
    altered = _genesis_c(spec, (modified,))
    _declared_result(store, plan, altered)
    with pytest.raises(ThemeAppendRejected, match="ALLOCATION_VIOLATION") as info:
        store.append_observation(altered)
    assert "differs" in info.value.detail


def test_result_genesis_carries_only_allocated_attachments_byte_identically(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    store.append_governance(plan.event)
    root_c, genesis_c = plan.results[0]
    store.append_root(root_c)
    spec = genesis_spec(root_c.created_at + timedelta(hours=1))
    with pytest.raises(ThemeAppendRejected, match="GENESIS_MISMATCH"):
        store.append_observation(_genesis_c(spec, ()))                        # 配分の部分集合でも宣言 genesis でなければ不可
    assert store.append_observation(genesis_c).status is AppendStatus.APPENDED
    stored = store.get_observation(genesis_c.observation_id)
    assert len(stored.attachments) == 1 and stored.attachment(KEY_A) == obs_a.attachment(KEY_A)   # 暗黙の carry なし
    assert stored.attachment(KEY_B) is None


def test_result_root_cannot_be_redeclared_or_created_as_candidate(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    store.append_governance(plan.event)
    other = ThemeGovernanceEvent.build(event_type=GovernanceEventType.SUPERSEDED_BY_ROOT, subject_roots=(ROOT_B,),
                                       result_roots=(ROOT_C,), reason="y", actor_ref="reviewer:r1",
                                       recorded_at=T0 + timedelta(days=2),
                                       previous_event_ids=((ROOT_B, plan.event.event_id),))
    with pytest.raises(ThemeAppendRejected, match="RESULT_ROOT_REDECLARED"):
        store.append_governance(other)
    with pytest.raises(ThemeAppendRejected, match="RESULT_ROOT_DECLARED_ELSEWHERE"):
        store.append_root(root_record(observation(root_id=ROOT_C)))
    wrong_origin = make_root_record(root_id=ROOT_C, created_at=T0 + timedelta(days=3),
                                    creation_method=CreationMethod.SPLIT_RESULT, creator_class=ProvenanceClass.HUMAN,
                                    creation_provenance="reviewer:r1", origin_event_id=plan.event.event_id,
                                    genesis_observation_id=plan.results[0][1].observation_id)
    with pytest.raises(ThemeAppendRejected, match="ORIGIN_EVENT_MISMATCH"):
        store.append_root(wrong_origin)
    with pytest.raises(ThemeAppendRejected, match="NON_MONOTONIC_RECORDED_AT"):
        store.append_root(make_root_record(root_id=ROOT_C, created_at=T0, creation_method=CreationMethod.MERGE_RESULT,
                                           creator_class=ProvenanceClass.HUMAN, creation_provenance="reviewer:r1",
                                           origin_event_id=plan.event.event_id,
                                           genesis_observation_id=plan.results[0][1].observation_id))


def test_completed_operations_survive_reload_and_source_roots_are_untouched(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    before_a = canonical_line(obs_a)
    plan = merge_plan(store, obs_a, obs_b)
    O.execute_declaration(store, plan)
    reopened = ThemeStore.open(tmp_path)
    assert reopened.pending() == () and reopened.diagnostics() == ()
    assert reopened.canonical_lines("observations")[0] == before_a
    assert reopened.physical_terminal_observations(ROOT_A) == (obs_a.observation_id,)
    assert reopened.get_root(ROOT_A).creation_method is CreationMethod.CANDIDATE
    assert O.execute_declaration(reopened, plan).status is O.OperationStatus.COMPLETE   # 完了後の再実行は全 no-op
    assert reopened.counts()["governance"] == 1
