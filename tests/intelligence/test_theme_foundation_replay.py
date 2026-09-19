"""P6-A4d — byte-level replay 決定論、入力順独立、future leakage 行列、physical order ≠ time order。"""
from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.themes.resolver import ResolutionStatus, ThemeHistory, resolve, resolve_at_data_root
from src.intelligence.themes.store import ThemeStore
from tests.intelligence.test_theme_model import ROOT_A, ROOT_C, mapping, observation, root_record
from tests.intelligence.theme_foundation_fixtures import (
    CHECKPOINTS, ROOT_KEYS, ROOT_Q, TIMES, World, authority_bytes, build_world, copy_world, day, knowable_digest,
    records_from_bytes, replay, resolution_digest,
)
from tests.intelligence.test_theme_model import FACT_A, attachment

H1 = timedelta(hours=1)


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    return build_world(tmp_path_factory.mktemp("world") / "data")


def all_resolutions(root: Path):
    return {(k, name): resolve_at_data_root(root, root_id, cutoff)
            for k, root_id in ROOT_KEYS.items() for name, cutoff in CHECKPOINTS.items()}


# ---------------------------------------------------------------- §5 byte-level replay

def test_byte_level_replay_reproduces_authorities_and_results(world: World, tmp_path: Path) -> None:
    source = authority_bytes(world.data_root)
    assert all(source.values())
    dest = tmp_path / "replayed"
    replayed = replay(source, dest)
    assert authority_bytes(dest) == source                                                     # bytes まで一致
    original_records = records_from_bytes(source)
    replayed_records = records_from_bytes(authority_bytes(dest))
    assert original_records == replayed_records                                                # id / record 一致
    assert replayed.counts() == ThemeStore.open(world.data_root, read_only=True).counts()
    assert all_resolutions(dest) == all_resolutions(world.data_root)                           # resolver / derived / 診断一致
    assert ThemeStore.audit(dest).pending == ThemeStore.audit(world.data_root).pending == ()
    assert {r.root_id for r in replayed_records["roots"]} == {r.root_id for r in original_records["roots"]}   # root id 再生成なし


def test_replay_is_itself_deterministic(world: World, tmp_path: Path) -> None:
    source = authority_bytes(world.data_root)
    replay(source, tmp_path / "one")
    replay(source, tmp_path / "two")
    assert authority_bytes(tmp_path / "one") == authority_bytes(tmp_path / "two") == source


# ---------------------------------------------------------------- §6 input order determinism

def test_shuffled_history_gives_identical_resolutions(world: World) -> None:
    history = ThemeHistory.from_store(ThemeStore.open(world.data_root, read_only=True))
    for seed in (3, 11, 29, 101):
        rng = random.Random(seed)
        parts = []
        for records in (history.roots, history.observations, history.events, history.metadata, history.mappings):
            items = list(records)
            rng.shuffle(items)
            parts.append(tuple(items))
        shuffled = ThemeHistory(*parts)
        for root_id in ROOT_KEYS.values():
            for cutoff in CHECKPOINTS.values():
                assert resolve(shuffled, root_id, cutoff) == resolve(history, root_id, cutoff), seed


# ---------------------------------------------------------------- §7 future leakage

#: BLOCKER A4D-3: 宣言済みだが RootRecord が未作成の result root を解決すると、resolver は UNKNOWN_ROOT を返し
#: PENDING_EVENT / lineage を付けない。後日 RootRecord が書かれると同じ T で PENDING_EVENT / lineage が現れる
#: （後の record が過去 T の診断を変える）。state facet は不変。下の strict xfail に固定する。
A4D_3_KEYS = {("C", "merge_declared_incomplete"), ("C", "merge_root_declared_genesis_missing")}


def test_every_later_stage_leaves_earlier_checkpoints_unchanged(world: World) -> None:
    """stage s 完了時点の (root, checkpoint) の結果 ＝ 完成 world での結果（cutoff < 次 stage 時刻 のすべて）。"""
    final = all_resolutions(world.data_root)
    compared = 0
    for stage in world.stage_order:
        for key, snapshot in world.snapshots[stage].items():
            if key in A4D_3_KEYS and stage in ("merge_declared", "merge_root"):
                continue                                                          # A4D-3（別 test で xfail 固定）
            assert knowable_digest(snapshot) == knowable_digest(final[key]), (stage, key)
            if snapshot.status is not ResolutionStatus.NO_STATE:
                assert snapshot == final[key], (stage, key)                      # state があるものは完全一致
            compared += 1
    assert compared > 300


@pytest.mark.xfail(strict=True, reason="BLOCKER A4D-3: resolver reports PENDING_EVENT / lineage for a declared result root "
                                       "only once its RootRecord exists, so a later RootRecord changes the diagnostics at an "
                                       "earlier cutoff")
def test_declared_result_root_diagnostics_do_not_depend_on_later_root_record(world: World) -> None:
    for key in sorted(A4D_3_KEYS):
        assert knowable_digest(world.snapshots["merge_declared"][key]) == knowable_digest(world.resolve(*key))


@pytest.mark.parametrize("later_stage,root_key,checkpoint", [
    ("evidence2", "A", "first_evidence"),                          # future observation
    ("delayed", "A", "delayed_evidence_before_attachment"),        # evidence existed before T, attached after T
    ("accepted", "A", "mapping_added"),                            # future governance
    ("label", "A", "contradiction_added"),                         # future metadata
    ("mapping", "A", "taxonomy_added"),                            # future mapping recorded_at
    ("merge_declared", "A", "retirement_reversed"),                # future merge declaration
    ("merge_declared", "C", "before_merge"),
    pytest.param("merge_root", "C", "merge_declared_incomplete",
                 marks=pytest.mark.xfail(strict=True, reason="BLOCKER A4D-3 (see above)")),   # future completion of PENDING (root)
    ("merge_completed", "C", "merge_root_declared_genesis_missing"),   # future completion of PENDING (genesis)
    ("merge_completed", "A", "merge_declared_incomplete"),
])
def test_future_record_matrix(world: World, later_stage, root_key, checkpoint) -> None:
    previous_stage = world.stage_order[world.stage_order.index(later_stage) - 1]
    before = world.snapshots[previous_stage][(root_key, checkpoint)]
    after = world.snapshots[later_stage][(root_key, checkpoint)]
    assert knowable_digest(before) == knowable_digest(after) == knowable_digest(world.resolve(root_key, checkpoint))
    if before.status is not ResolutionStatus.NO_STATE:
        assert before == after == world.resolve(root_key, checkpoint)


def test_future_mapping_valid_from_and_future_split_successor_do_not_leak(world: World, tmp_path: Path) -> None:
    root = copy_world(world.data_root, tmp_path / "copy")
    cutoff = CHECKPOINTS["merge_completed"]
    baseline = resolve_at_data_root(root, ROOT_A, cutoff)
    store = ThemeStore.open(root)
    future_mapping = mapping(series_ref="rates:UST10Y_par.close", recorded_at=TIMES["TM_genesis"] + H1,
                             valid_from=day(40))                                                # 記録は T 前、有効化は T 後
    store.append_mapping(future_mapping)
    assert resolve_at_data_root(root, ROOT_A, cutoff) == baseline
    assert future_mapping.mapping_id in resolve_at_data_root(root, ROOT_A, day(41)).mapping.terminal_mapping_ids
    from tests.intelligence.test_theme_foundation_e2e import split_world, successor_world
    from src.intelligence.themes import operations as O
    for builder, name in ((split_world, "x"), (successor_world, "m")):
        other = tmp_path / name
        times, genesis, plan = builder(other)
        before = {t: resolve_at_data_root(other, plan.event.subject_roots[0], times[t]) for t in ("genesis",)}
        O.execute_declaration(ThemeStore.open(other), plan)
        assert {t: resolve_at_data_root(other, plan.event.subject_roots[0], times[t]) for t in ("genesis",)} == before


# ---------------------------------------------------------------- physical order ≠ time order

def test_backdated_root_appended_later_is_governed_by_timestamps_not_file_order(world: World, tmp_path: Path) -> None:
    root = copy_world(world.data_root, tmp_path / "copy")
    store = ThemeStore.open(root)
    at = TIMES["T2_evidence1"]
    late = observation(root_id=ROOT_Q, recorded_at=at + H1,                                    # 時刻は A の T2 直後、追記は最後
                       attachments=(attachment(FACT_A, attached=at + H1),))
    store.append_root(root_record(late, created_at=TIMES["T2_evidence1"]))
    store.append_observation(late)
    reopened = ThemeStore.open(root, read_only=True)
    assert reopened.canonical_lines("observations")[-1].startswith("{")                     # 物理的には最後の行
    assert resolve_at_data_root(root, ROOT_Q, TIMES["T3_evidence2"]).status is ResolutionStatus.RESOLVED
    assert resolve_at_data_root(root, ROOT_Q, TIMES["T2_evidence1"]).status is ResolutionStatus.NO_STATE
    assert resolve_at_data_root(root, ROOT_A, CHECKPOINTS["merge_completed"]) == world.resolve("A", "merge_completed")
    replayed = replay(authority_bytes(root), tmp_path / "replayed")                          # 物理順は file ごとに保存される
    assert authority_bytes(tmp_path / "replayed") == authority_bytes(root)
    assert replayed.counts()["roots"] == 4
