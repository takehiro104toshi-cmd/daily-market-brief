"""P6-A4c — point-in-time resolver: cutoff 意味論・observation chain・evidence 可視性・PENDING・決定論・read-only・API 境界。

fixture は A4a builder（test_theme_model）と A4b helper（test_theme_store / test_theme_store_operations）を再利用する。
fork は store が拒否するため、検証済み record から `ThemeHistory` を直接組む（history repair なし）。
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.themes import resolver as R
from src.intelligence.themes import operations as O
from src.intelligence.themes.model import (
    EvidenceKind, EvidenceRole, EvidenceTimeQuality, MetadataField, OriginKind, ThemeModelError, ThemeObservation,
    canonical_line,
)
from src.intelligence.themes.resolver import (
    GovernanceStatus, MappingStatus, MetadataStatus, ResolutionStatus, ThemeHistory, resolve, resolve_at_data_root,
    resolve_from_store,
)
from src.intelligence.themes.revision import attach_evidence, revise_observation
from src.intelligence.themes.store import FailureCategory, ThemeStore, ThemeStoreError
from tests.intelligence.test_theme_model import (
    FACT_A, FACT_B, ROOT_A, ROOT_B, ROOT_C, T0, UTC, attachment, limitation, observation, origin, provenance,
    root_record,
)
from tests.intelligence.test_theme_store import SimulatedCrash, interrupt_after, seeded
from tests.intelligence.test_theme_store_operations import merge_plan, two_roots

MOF = origin(kind=OriginKind.OFFICIAL_RELEASE, key="release:mof_japan/doc_c", source_ids=("mof_japan",))
H1 = timedelta(hours=1)
D1 = timedelta(days=1)


def late_doc(attached):
    return attachment("doc_" + "c" * 24, EvidenceKind.SOURCE_DOCUMENT, src=MOF, day="2026-08-25", attached=attached)


def history(store: ThemeStore) -> ThemeHistory:
    return ThemeHistory.from_store(store)


def shuffled(h: ThemeHistory, seed: int) -> ThemeHistory:
    rng = random.Random(seed)
    parts = []
    for records in (h.roots, h.observations, h.events, h.metadata, h.mappings):
        items = list(records)
        rng.shuffle(items)
        parts.append(tuple(items))
    return ThemeHistory(*parts)


# ---------------------------------------------------------------- cutoff / root / genesis

def test_before_root_creation_is_no_state(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    before = resolve(history(store), ROOT_A, T0 - timedelta(seconds=1))
    assert before.status is ResolutionStatus.NO_STATE and before.observation is None and before.root is None
    assert [d.kind for d in before.diagnostics] == ["ROOT_AFTER_CUTOFF"]
    unknown = resolve(history(store), ROOT_B, T0 + D1)
    assert unknown.status is ResolutionStatus.NO_STATE and [d.kind for d in unknown.diagnostics] == ["UNKNOWN_ROOT"]
    assert unknown.governance.status is GovernanceStatus.NOT_EVALUATED
    assert all(m.status is MetadataStatus.NOT_EVALUATED for m in unknown.metadata)
    assert unknown.mapping.status is MappingStatus.NOT_EVALUATED


def test_root_before_genesis_is_no_state_with_pending_genesis(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    at = resolve(history(store), ROOT_A, T0 + timedelta(minutes=30))     # root T0、genesis T0+1h
    assert at.status is ResolutionStatus.NO_STATE and at.root == root and at.observation is None
    assert [(p.kind, p.subject_id, p.missing) for p in at.pending] == [("PENDING_GENESIS", ROOT_A, (obs.observation_id,))]
    assert [d.kind for d in at.diagnostics] == ["NOT_YET_OBSERVED"]
    assert at.governance.status is GovernanceStatus.NO_GOVERNANCE          # facet は独立に評価される
    assert at.mapping.status is MappingStatus.NO_MAPPING


def test_after_genesis_resolved(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    at = resolve(history(store), ROOT_A, obs.recorded_at)                  # recorded_at == T は eligible
    assert at.status is ResolutionStatus.RESOLVED and at.observation == obs and at.root == root
    assert [a.attachment_key for a in at.evidence.visible] == [a.attachment_key for a in obs.attachments]
    assert at.evidence.not_yet_attached == () and at.evidence.evidence_after_cutoff == ()
    assert at.governance.status is GovernanceStatus.NO_GOVERNANCE
    assert [m.status for m in at.metadata] == [MetadataStatus.NO_METADATA] * 4
    assert at.mapping.status is MappingStatus.NO_MAPPING and at.pending == () and at.lineage == () and at.carried == ()
    assert at.derived is not None and at.derived.qualification.status.value == "THEME_CANDIDATE_POSSIBLE"
    assert all(d.status.value == "NOT_CHECKED" for d in at.dereference) and len(at.dereference) == 2


def test_revision_boundary_selects_observation_by_cutoff(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    second = revise_observation(obs, recorded_at=T0 + D1, provenance=provenance(), limitations=())
    store.append_observation(second)
    h = history(store)
    assert resolve(h, ROOT_A, T0 + D1 - timedelta(seconds=1)).observation == obs
    assert resolve(h, ROOT_A, T0 + D1).observation == second
    assert resolve(h, ROOT_A, T0 + 2 * D1).observation == second


def test_future_observation_does_not_change_past_result(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    cutoff = T0 + timedelta(hours=2)
    before = resolve(history(store), ROOT_A, cutoff)
    store.append_observation(revise_observation(obs, recorded_at=T0 + D1, provenance=provenance(), limitations=()))
    after = resolve(history(store), ROOT_A, cutoff)
    assert before == after and after.observation == obs


# ---------------------------------------------------------------- evidence visibility

def test_delayed_attachment_is_invisible_before_it_was_attached(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    cutoff = T0 + 3 * D1                                                    # evidence 日付 2026-08-25 は cutoff より前
    baseline = resolve(history(store), ROOT_A, cutoff)
    second = attach_evidence(obs, (late_doc(T0 + 5 * D1),), recorded_at=T0 + 5 * D1, provenance=provenance())
    store.append_observation(second)
    h = history(store)
    at_cutoff = resolve(h, ROOT_A, cutoff)
    assert at_cutoff == baseline                                            # 知識は存在しても付与は T 後 → 見えない
    assert "doc_" + "c" * 24 not in {a.ref_id for a in at_cutoff.evidence.visible}
    later = resolve(h, ROOT_A, T0 + 6 * D1)
    assert "doc_" + "c" * 24 in {a.ref_id for a in later.evidence.visible} and later.observation == second


def test_evidence_view_checks_both_times_independently(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    second = attach_evidence(obs, (late_doc(T0 + 5 * D1),), recorded_at=T0 + 5 * D1, provenance=provenance())
    # 独立検査の固定: observation の eligibility に依らず、attachment 単位で attached_at <= T を要求する
    view = R._evidence_view(second, T0 + 2 * D1)
    assert {a.ref_id for a in view.visible} == {FACT_A, FACT_B}
    assert view.not_yet_attached == ("doc_" + "c" * 24 + "#c1",)
    both = R._evidence_view(second, T0 + 6 * D1)
    assert len(both.visible) == 3 and both.not_yet_attached == ()
    # evidence_time > T は model 上 attached_at <= evidence_time では起こりえないが、resolver は独立に検査する
    shifted = second.attachments[0]
    object.__setattr__(shifted, "evidence_time", T0 + 10 * D1)          # 検査経路の固定のみ（record は永続化しない）
    view2 = R._evidence_view(second, T0 + 6 * D1)
    assert shifted.attachment_key in view2.evidence_after_cutoff and shifted not in view2.visible
    object.__setattr__(shifted, "evidence_time", datetime(2026, 8, 20, tzinfo=UTC))


def test_context_without_time_is_separated_from_authoritative_view(tmp_path: Path) -> None:
    store = ThemeStore.initialize(tmp_path)
    ctx = attachment("doc_" + "d" * 24, EvidenceKind.SOURCE_DOCUMENT, src=MOF, quality=EvidenceTimeQuality.MISSING,
                     role=EvidenceRole.CONTEXT, cref="")
    obs = observation(attachments=(attachment(FACT_A), ctx))
    store.append_root(root_record(obs))
    store.append_observation(obs)
    at = resolve(history(store), ROOT_A, T0 + D1)
    assert [a.ref_id for a in at.evidence.visible] == [FACT_A]
    assert [a.ref_id for a in at.evidence.context_without_time] == ["doc_" + "d" * 24]
    assert at.derived.qualification.counted_attachment_keys == (f"{FACT_A}#c1",)
    assert [d.ref_id for d in at.dereference] == [FACT_A]


def test_qualification_is_recomputed_from_visible_evidence_only(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    second = attach_evidence(obs, (late_doc(T0 + 5 * D1),), recorded_at=T0 + 5 * D1, provenance=provenance())
    store.append_observation(second)
    h = history(store)
    early = resolve(h, ROOT_A, T0 + 2 * D1).derived
    late = resolve(h, ROOT_A, T0 + 6 * D1).derived
    assert early.qualification.status.value == "THEME_CANDIDATE_POSSIBLE" and early.qualification.independent_origins == 1
    assert late.qualification.status.value == "QUALIFIES_SEMANTICALLY" and late.qualification.independent_origins == 2
    assert early.semantic_fingerprint == late.semantic_fingerprint        # fingerprint は evidence に依存しない
    assert "qualification" not in second.as_dict() and "fingerprint" not in canonical_line(second)


# ---------------------------------------------------------------- fork / no latest-wins

def fork_history(store: ThemeStore, obs: ThemeObservation, *, right_later: bool = True):
    left = revise_observation(obs, recorded_at=T0 + D1, provenance=provenance(), limitations=())
    right = revise_observation(obs, recorded_at=T0 + (2 * D1 if right_later else D1), provenance=provenance(),
                               limitations=(limitation("z"),))
    base = history(store)
    return ThemeHistory(roots=base.roots, observations=base.observations + (left, right)), left, right


def test_observation_fork_is_unresolved(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    h, left, right = fork_history(store, obs)
    at = resolve(h, ROOT_A, T0 + 3 * D1)
    assert at.status is ResolutionStatus.UNRESOLVED and at.observation is None and at.evidence is None
    assert [(d.kind, d.subject_id) for d in at.diagnostics] == [("FORK", obs.observation_id)]
    assert set(at.diagnostics[0].related) == {left.observation_id, right.observation_id}
    assert at.governance.status is GovernanceStatus.NO_GOVERNANCE          # 他 facet は評価される
    assert resolve(h, ROOT_A, T0 + H1).observation == obs                  # fork 前の T は解決できる


def test_max_recorded_at_and_physical_order_are_not_winners(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    h, left, right = fork_history(store, obs, right_later=True)
    forward = resolve(h, ROOT_A, T0 + 3 * D1)
    reversed_history = ThemeHistory(roots=h.roots, observations=tuple(reversed(h.observations)))
    backward = resolve(reversed_history, ROOT_A, T0 + 3 * D1)
    assert forward.status is ResolutionStatus.UNRESOLVED and forward == backward
    assert forward.observation is None                                      # recorded_at 最大（right）を選ばない
    at_left_only = resolve(h, ROOT_A, T0 + D1 + H1)                         # right（T0+2d）が eligible になる前は線形
    assert at_left_only.status is ResolutionStatus.RESOLVED and at_left_only.observation == left


def test_multiple_starts_and_dangling_are_classified(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    base = history(store)
    other_genesis = observation(limitations=())
    mismatch = ThemeHistory(roots=base.roots, observations=base.observations + (other_genesis,))
    assert resolve(mismatch, ROOT_A, T0 + D1).status is ResolutionStatus.INVALID_HISTORY
    assert resolve(mismatch, ROOT_A, T0 + D1).diagnostics[0].kind == "GENESIS_MISMATCH"
    dangling = ThemeHistory(roots=base.roots, observations=(
        obs, observation(previous_observation_id="thobs_" + "1" * 24, recorded_at=T0 + D1)))
    invalid = resolve(dangling, ROOT_A, T0 + 2 * D1)
    assert invalid.status is ResolutionStatus.INVALID_HISTORY and invalid.diagnostics[0].kind == "DANGLING_PREDECESSOR"
    assert invalid.governance.status is GovernanceStatus.NOT_EVALUATED       # 上位 failure は facet を評価しない
    obs_b = observation(root_id=ROOT_B)
    cross = ThemeObservation.build(
        root_id=ROOT_A, previous_observation_id=obs_b.observation_id, subject=obs.subject, mechanism=obs.mechanism,
        certainty_class=obs.certainty_class, scope=obs.scope, limitations=(), invalidation_conditions=obs.invalidation_conditions,
        attachments=obs.attachments, provenance=provenance(), recorded_at=T0 + D1)
    wrong = ThemeHistory(roots=base.roots + (root_record(obs_b),), observations=(obs, obs_b, cross))
    assert resolve(wrong, ROOT_A, T0 + 2 * D1).diagnostics[0].kind == "WRONG_ROOT_PREDECESSOR"


# ---------------------------------------------------------------- PENDING at past cutoffs

def test_pending_event_is_preserved_at_past_cutoffs_after_completion(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)                                  # event T0+2d / root C T0+3d / genesis T0+3d+1h
    O.execute_declaration(store, plan)
    h = history(store)
    between = resolve(h, ROOT_A, T0 + 2 * D1 + H1)
    assert between.status is ResolutionStatus.RESOLVED and between.observation == obs_a
    assert [(p.kind, p.subject_id, p.missing) for p in between.pending] == [("PENDING_EVENT", plan.event.event_id, (ROOT_C,))]
    result_root = resolve(h, ROOT_C, T0 + 2 * D1 + H1)
    assert result_root.status is ResolutionStatus.NO_STATE and result_root.pending == between.pending
    assert [l.kind.value for l in result_root.lineage] == ["MERGE_OF"]
    genesis_pending = resolve(h, ROOT_C, T0 + 3 * D1 + timedelta(minutes=30))
    assert genesis_pending.status is ResolutionStatus.NO_STATE
    assert {p.kind for p in genesis_pending.pending} == {"PENDING_GENESIS", "PENDING_EVENT"}
    done = resolve(h, ROOT_C, T0 + 4 * D1)
    assert done.status is ResolutionStatus.RESOLVED and done.pending == ()


def test_crash_then_completion_does_not_retroact(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    previous = O.terminal_previous_events(store, (ROOT_A, ROOT_B))
    plan = merge_plan(store, obs_a, obs_b, previous)
    interrupt_after(store, 1)
    with pytest.raises(SimulatedCrash):
        O.execute_declaration(store, plan)
    cutoff = T0 + 2 * D1 + H1
    reopened = ThemeStore.open(tmp_path)
    while_pending = resolve_from_store(reopened, ROOT_A, cutoff)
    assert [p.kind for p in while_pending.pending] == ["PENDING_EVENT"]
    O.execute_declaration(reopened, plan)                                   # 後日完了（root T0+3d、genesis T0+3d+1h）
    completed = resolve_from_store(ThemeStore.open(tmp_path), ROOT_A, cutoff)
    assert completed == while_pending                                       # 過去の T へ遡及しない
    assert resolve_from_store(ThemeStore.open(tmp_path), ROOT_C, T0 + 4 * D1).status is ResolutionStatus.RESOLVED


# ---------------------------------------------------------------- determinism / purity / API boundary

def test_same_bytes_root_cutoff_give_same_result_and_input_order_is_irrelevant(tmp_path: Path) -> None:
    store, obs_a, obs_b = two_roots(tmp_path)
    O.execute_declaration(store, merge_plan(store, obs_a, obs_b))
    h = history(store)
    cutoff = T0 + 4 * D1
    first = resolve(h, ROOT_C, cutoff)
    assert first == resolve(h, ROOT_C, cutoff)
    for seed in (1, 7, 42):
        assert resolve(shuffled(h, seed), ROOT_C, cutoff) == first
    reopened = ThemeStore.open(tmp_path, read_only=True)
    assert resolve_from_store(reopened, ROOT_C, cutoff) == first
    assert resolve_at_data_root(tmp_path, ROOT_C, cutoff) == first


def test_naive_cutoff_and_invalid_root_are_rejected(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    h = history(store)
    with pytest.raises(ThemeModelError, match="^NAIVE_DATETIME"):
        resolve(h, ROOT_A, T0.replace(tzinfo=None))
    with pytest.raises(ThemeModelError, match="^INVALID_ROOT_ID"):
        resolve(h, "theme_bad", T0)
    with pytest.raises(ThemeModelError, match="^INVALID_TYPE"):
        resolve(h, ROOT_A, "2026-09-01")  # type: ignore[arg-type]
    with pytest.raises(ThemeModelError, match="^NAIVE_DATETIME"):
        resolve_at_data_root(tmp_path, ROOT_A, datetime(2026, 9, 2))
    jst = timezone(timedelta(hours=9))
    assert resolve(h, ROOT_A, datetime(2026, 9, 1, 10, 0, tzinfo=jst)) == resolve(h, ROOT_A, T0 + H1)


def test_resolver_is_read_only(tmp_path: Path, monkeypatch) -> None:
    store, root, obs = seeded(tmp_path)
    store.append_observation(revise_observation(obs, recorded_at=T0 + D1, provenance=provenance(), limitations=()))
    before = {n: (p.read_bytes(), p.stat().st_mtime_ns) for n, p in store.paths.items()}
    monkeypatch.setattr(ThemeStore, "_write_line", lambda *a, **k: (_ for _ in ()).throw(AssertionError("write")))
    for cutoff in (T0 - H1, T0 + H1, T0 + 2 * D1, T0 + 30 * D1):
        resolve_from_store(store, ROOT_A, cutoff)
        resolve_at_data_root(tmp_path, ROOT_A, cutoff)
    assert {n: (p.read_bytes(), p.stat().st_mtime_ns) for n, p in store.paths.items()} == before
    with pytest.raises(AttributeError):
        R.resolve.__self__  # type: ignore[attr-defined]  # module function（object に状態を持たない）


def test_store_failure_categories_at_the_resolver_boundary(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    with store.paths["observations"].open("ab") as handle:
        handle.write(b"{broken\n")
    corrupt = resolve_at_data_root(tmp_path, ROOT_A, T0 + D1)
    assert corrupt.status is ResolutionStatus.STORE_CORRUPTION and corrupt.diagnostics[0].kind == "MALFORMED_JSON"
    assert corrupt.diagnostics[0].facet == "store" and corrupt.governance.status is GovernanceStatus.NOT_EVALUATED
    store.paths["roots"].write_bytes(b"")                                   # genesis without root（履歴として不可能）
    invalid = resolve_at_data_root(tmp_path, ROOT_A, T0 + D1)
    assert invalid.status is ResolutionStatus.INVALID_HISTORY and invalid.diagnostics[0].kind == "ROOT_NOT_FOUND"
    with pytest.raises(ThemeStoreError) as info:
        resolve_at_data_root(tmp_path / "nowhere", ROOT_A, T0 + D1)
    assert info.value.category is FailureCategory.NOT_INITIALIZED


def test_status_vocabularies_are_distinct_and_no_convenience_api() -> None:
    assert {s.value for s in ResolutionStatus} == {"RESOLVED", "NO_STATE", "UNRESOLVED", "INVALID_HISTORY",
                                                  "STORE_CORRUPTION"}
    assert {s.value for s in GovernanceStatus} == {"RESOLVED", "NO_GOVERNANCE", "UNRESOLVED", "NOT_EVALUATED"}
    assert {s.value for s in MetadataStatus} == {"RESOLVED", "NO_METADATA", "UNRESOLVED", "NOT_EVALUATED"}
    assert {s.value for s in MappingStatus} == {"RESOLVED", "NO_MAPPING", "UNRESOLVED", "NOT_EVALUATED"}
    public = {n for n in dir(R) if not n.startswith("_")}
    for forbidden in ("current_theme", "latest_theme", "active_theme", "state_at", "governance_state", "metadata_at",
                      "mapping_at", "resolve_theme"):
        assert forbidden not in public
    assert {"resolve", "resolve_from_store", "resolve_at_data_root", "ThemeHistory", "ThemeResolution"} <= public
    assert R.RESOLVER_VERSION == "theme_resolver:0.1.0"


def test_history_from_store_rejects_duplicate_ids(tmp_path: Path) -> None:
    store, root, obs = seeded(tmp_path)
    h = history(store)
    with pytest.raises(ThemeModelError, match="^DUPLICATE_ID"):
        resolve(ThemeHistory(roots=h.roots, observations=h.observations + h.observations), ROOT_A, T0 + D1)
