"""P6-A4d.1 — Theme foundation BLOCKER remediation（A4D-1 / A4D-2 / A4D-3）の回帰 test。

A4D-1: identity core の置換は canonical authority 境界（store append / load）と resolver で IDENTITY_CORE_CHANGED。
A4D-2: METADATA_CORRECTION_APPROVED（related record ＝ metadata）は固定 load 順のまま cross pass で検査され、再 open できる。
A4D-3: 宣言済み・未作成の result root は T で PENDING_EVENT ＋ 宣言由来 lineage を持ち、後日の完了で過去 T の結果は変わらない。
runtime の変更は store.py / resolver.py のみ。schema / canonical id / 語彙 / load 順 / authority file 名は不変。
"""
from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.themes import operations as O
from src.intelligence.themes.fingerprint import identity_core_fingerprint, semantic_fingerprint
from src.intelligence.themes.model import (
    ComponentType, EvidenceKind, GovernanceEventType, MetadataField, ScopeDimension, ScopeToken, ThemeModelError,
    ThemeObservation, canonical_line,
)
from src.intelligence.themes.resolver import (
    GovernanceStatus, LineageKind, MappingStatus, MetadataStatus, ResolutionStatus, ThemeHistory, resolve,
    resolve_at_data_root,
)
from src.intelligence.themes.revision import attach_evidence, revise_observation
from src.intelligence.themes.store import (
    HISTORY_REASONS, LOAD_ORDER, AppendStatus, ThemeAppendRejected, ThemeInvalidHistory, ThemeStore, ThemeStoreCorrupt,
)
from tests.intelligence.test_theme_model import (
    DOC_C, ROOT_A, ROOT_B, ROOT_C, T0, attachment, component, consequence, event, limitation, mechanism, metadata,
    observation, provenance, root_record, subject,
)
from tests.intelligence.test_theme_store import SimulatedCrash, interrupt_after, rejected, seeded
from tests.intelligence.test_theme_store_operations import KEY_A, ROOT_D, ROOT_E, genesis_spec, merge_plan, split_plan, successor_plan, two_roots
from tests.intelligence.theme_foundation_fixtures import ROOT_Q, authority_bytes, day, knowable_digest

H1 = timedelta(hours=1)
S1 = timedelta(seconds=1)
META_UNKNOWN = "thmeta_" + "9" * 24


def rebuilt(obs: ThemeObservation, **override) -> ThemeObservation:
    """revise_observation（純 helper）を経由せず、predecessor を指す observation を直接組む（store 境界の検査対象）。"""
    kwargs = dict(root_id=obs.root_id, previous_observation_id=obs.observation_id, subject=obs.subject,
                  mechanism=obs.mechanism, certainty_class=obs.certainty_class, scope=obs.scope,
                  limitations=obs.limitations, invalidation_conditions=obs.invalidation_conditions,
                  attachments=obs.attachments, provenance=provenance(), recorded_at=obs.recorded_at + H1)
    kwargs.update(override)
    return ThemeObservation.build(**kwargs)


IDENTITY_BREAKS = {
    "driver": lambda: dict(mechanism=mechanism(drivers=(component(category="POLICY_RATE", typed_reference="rates:boj"),))),
    "channel": lambda: dict(mechanism=mechanism(channels=(component(ComponentType.TRANSMISSION_CHANNEL, "ch1",
                                                                     "CAPEX_CYCLE", ""),))),
    "domain": lambda: dict(mechanism=mechanism(domains=(component(ComponentType.AFFECTED_DOMAIN, "dom1", "REGION",
                                                                   "region:jp"),))),
    "subject": lambda: dict(subject=subject("other subject", "")),
}


def append_raw(path: Path, record) -> None:
    """store を経由せず canonical 行を file に追記する（既存 journal 内の違反 / 破損の再現）。"""
    with path.open("ab") as handle:
        handle.write(canonical_line(record).encode("utf-8"))


# ================================================================ A4D-1 identity core enforcement

@pytest.mark.parametrize("which", ["driver", "channel", "domain", "subject"])
def test_a4d1_identity_core_change_is_rejected_at_append(tmp_path: Path, which: str) -> None:
    """1 / 2: 同一 root の driver / channel（＋ domain / subject）置換は append で IDENTITY_CORE_CHANGED。何も書かれない。"""
    store, _root, obs = seeded(tmp_path)
    changed = rebuilt(obs, **IDENTITY_BREAKS[which]())
    assert identity_core_fingerprint(changed) != identity_core_fingerprint(obs)
    before = authority_bytes(tmp_path)
    with rejected("IDENTITY_CORE_CHANGED"):
        store.append_observation(changed)
    assert authority_bytes(tmp_path) == before and store.counts()["observations"] == 1
    with pytest.raises(ThemeModelError, match="IDENTITY_CORE_CHANGED"):          # 純 helper と同じ判定（A2 §2.3）
        revise_observation(obs, recorded_at=obs.recorded_at + H1, provenance=provenance(), **IDENTITY_BREAKS[which]())
    assert "IDENTITY_CORE_CHANGED" in HISTORY_REASONS


def test_a4d1_allowed_semantic_revision_is_still_accepted(tmp_path: Path) -> None:
    """3: A2 で SAME_ROOT_NEW_OBSERVATION とされる変更（scope / consequence / limitation / evidence 追加）は引き続き可。"""
    store, _root, obs = seeded(tmp_path)
    scoped = revise_observation(obs, recorded_at=obs.recorded_at + H1, provenance=provenance(reason="scope refined"),
                                scope=(ScopeToken(dimension=ScopeDimension.REGION, value="jp"),
                                       ScopeToken(dimension=ScopeDimension.PERIOD_FRAME, value="multi_year")),
                                limitations=(limitation("data lag"),))
    widened = revise_observation(scoped, recorded_at=obs.recorded_at + 2 * H1, provenance=provenance(reason="consequence"),
                                 mechanism=mechanism(consequences=(consequence(), consequence(key="c2",
                                                                                            target="fx:USDJPY.vol"))))
    evidenced = attach_evidence(widened, (attachment(DOC_C, EvidenceKind.SOURCE_DOCUMENT, day="2026-08-22",
                                                     attached=obs.recorded_at + 3 * H1),),
                                recorded_at=obs.recorded_at + 3 * H1, provenance=provenance(reason="evidence"))
    for record in (scoped, widened, evidenced):
        assert store.append_observation(record).status is AppendStatus.APPENDED
        assert identity_core_fingerprint(record) == identity_core_fingerprint(obs)
    assert semantic_fingerprint(widened) != semantic_fingerprint(obs)               # semantic 変化は禁止しない
    reopened = ThemeStore.open(tmp_path, read_only=True)
    assert reopened.counts()["observations"] == 4 and reopened.physical_terminal_observations(ROOT_A) == (evidenced.observation_id,)
    at = resolve_at_data_root(tmp_path, ROOT_A, obs.recorded_at + 4 * H1)
    assert at.status is ResolutionStatus.RESOLVED and at.observation == evidenced and len(at.evidence.visible) == 3


def test_a4d1_preexisting_identity_core_break_is_rejected_on_reopen(tmp_path: Path) -> None:
    """4: 既に canonical file にある identity-core-breaking chain は再 open（writable / read-only / audit / resolver 入口）
    で INVALID_HISTORY。skip も修復もしない。"""
    store, _root, obs = seeded(tmp_path)
    changed = rebuilt(obs, **IDENTITY_BREAKS["driver"]())
    append_raw(store.paths["observations"], changed)
    frozen = authority_bytes(tmp_path)
    for opener in (lambda: ThemeStore.open(tmp_path), lambda: ThemeStore.open(tmp_path, read_only=True),
                   lambda: ThemeStore.audit(tmp_path)):
        with pytest.raises(ThemeInvalidHistory) as info:
            opener()
        assert (info.value.code, info.value.authority, info.value.line_number) == ("IDENTITY_CORE_CHANGED", "observations", 2)
    res = resolve_at_data_root(tmp_path, ROOT_A, changed.recorded_at + H1)
    assert res.status is ResolutionStatus.INVALID_HISTORY and res.observation is None
    assert [d.kind for d in res.diagnostics] == ["IDENTITY_CORE_CHANGED"]
    assert res.governance.status is GovernanceStatus.NOT_EVALUATED
    assert authority_bytes(tmp_path) == frozen                                     # 失敗した open は何も書かない


def test_a4d1_synthetic_history_resolver_returns_invalid_history(tmp_path: Path) -> None:
    """5: store を経由しない ThemeHistory でも同じ不変条件。勝者選択・自動 successor 化はしない。T 前は無影響。"""
    _store, root, obs = seeded(tmp_path)
    changed = rebuilt(obs, **IDENTITY_BREAKS["channel"]())
    history = ThemeHistory((root,), (obs, changed), (), (), ())
    broken = resolve(history, ROOT_A, changed.recorded_at + H1)
    assert broken.status is ResolutionStatus.INVALID_HISTORY and broken.observation is None and broken.derived is None
    assert [(d.kind, d.subject_id, d.related) for d in broken.diagnostics] == [
        ("IDENTITY_CORE_CHANGED", changed.observation_id, (obs.observation_id,))]
    assert broken.governance.status is GovernanceStatus.NOT_EVALUATED
    assert all(m.status is MetadataStatus.NOT_EVALUATED for m in broken.metadata)
    assert broken.mapping.status is MappingStatus.NOT_EVALUATED
    shuffled = ThemeHistory((root,), (changed, obs), (), (), ())
    assert resolve(shuffled, ROOT_A, changed.recorded_at + H1) == broken
    intact = resolve(history, ROOT_A, changed.recorded_at - S1)                     # T 以後の record は影響しない
    assert intact.status is ResolutionStatus.RESOLVED and intact.observation == obs


def test_a4d1_explicit_successor_new_root_path_remains_valid(tmp_path: Path) -> None:
    """6: driver 置換は SUPERSEDED_BY_ROOT event ＋ 新 root（SUCCESSOR_RESULT）＋ genesis の経路でのみ記録できる。"""
    store, _root, obs = seeded(tmp_path)
    created = T0 + timedelta(days=3)
    new_driver = mechanism(drivers=(component(category="POLICY_RATE", typed_reference="rates:boj"),))
    spec = O.ResultRootSpec(root_id=ROOT_D, created_at=created, creation_provenance="reviewer:r1",
                            genesis=genesis_spec(created + H1, mechanism=new_driver), carried=((obs.observation_id, KEY_A),))
    plan = O.plan_successor(store, subject_root=ROOT_A, result=spec, reason="driver replaced", actor_ref="reviewer:r1",
                            recorded_at=T0 + timedelta(days=2), previous_event_ids=O.terminal_previous_events(store, (ROOT_A,)))
    assert O.execute_declaration(store, plan).status is O.OperationStatus.COMPLETE
    reopened = ThemeStore.open(tmp_path, read_only=True)
    assert reopened.pending() == () and reopened.diagnostics() == ()
    new = resolve_at_data_root(tmp_path, ROOT_D, created + 2 * H1)
    old = resolve_at_data_root(tmp_path, ROOT_A, created + 2 * H1)
    assert new.status is ResolutionStatus.RESOLVED and old.status is ResolutionStatus.RESOLVED
    assert new.derived.identity_core_fingerprint != old.derived.identity_core_fingerprint
    assert old.observation == obs                                                   # 旧 root の semantic は不変
    assert [(l.kind, l.related_roots) for l in old.lineage] == [(LineageKind.SUPERSEDED_BY, (ROOT_D,))]
    assert [(l.kind, l.related_roots) for l in new.lineage] == [(LineageKind.SUCCESSOR_OF, (ROOT_A,))]
    assert old.governance.effective_event_type is GovernanceEventType.SUPERSEDED_BY_ROOT
    assert [c.attachment_key for c in new.carried] == [KEY_A]


# ================================================================ A4D-2 cross-authority governance reference

def approved_world(root: Path):
    """root Q ＋ genesis → label（typo）→ label 訂正 → METADATA_CORRECTION_APPROVED（related ＝ 訂正 metadata id）。"""
    store = ThemeStore.initialize(root)
    genesis = observation(root_id=ROOT_Q, recorded_at=day(0, 1))
    store.append_root(root_record(genesis, created_at=day(0)))
    store.append_observation(genesis)
    label1 = metadata(root_id=ROOT_Q, value=("Yen weakness / inpt cost",), recorded_at=day(1))
    label2 = metadata(root_id=ROOT_Q, value=("Yen weakness / input cost",), previous_metadata_id=label1.metadata_id,
                      recorded_at=day(2), reason="typo")
    store.append_metadata(label1)
    store.append_metadata(label2)
    approval = event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED, subject_roots=(ROOT_Q,),
                     related_observations=(label2.metadata_id,), reason="typo fixed", recorded_at=day(2, 1))
    return store, dict(genesis=genesis, label1=label1, label2=label2, approval=approval)


def test_a4d2_metadata_correction_approval_append_succeeds(tmp_path: Path) -> None:
    """7: append 時の検査（存在 / root / 時刻）はそのまま通り、event が記録される。"""
    store, r = approved_world(tmp_path)
    result = store.append_governance(r["approval"])
    assert result.status is AppendStatus.APPENDED and store.counts()["governance"] == 1
    assert store.append_governance(r["approval"]).status is AppendStatus.ALREADY_PRESENT       # 冪等
    assert store.pending() == () and store.diagnostics() == ()
    assert store.physical_terminal_events(ROOT_Q) == (r["approval"].event_id,)


def test_a4d2_reopen_succeeds(tmp_path: Path) -> None:
    """8: 同じ canonical journal を固定 load 順（roots → observations → governance → metadata → mappings）で再 open できる。"""
    store, r = approved_world(tmp_path)
    store.append_governance(r["approval"])
    assert LOAD_ORDER == ("roots", "observations", "governance", "metadata", "mappings")
    reopened = ThemeStore.open(tmp_path)
    assert reopened.counts() == {"roots": 1, "observations": 1, "governance": 1, "metadata": 2, "mappings": 0}
    assert reopened.get_governance_event(r["approval"].event_id) == r["approval"]
    assert reopened.pending() == () and reopened.diagnostics() == ()
    label3 = metadata(root_id=ROOT_Q, value=("Yen weakness / input cost (JPY)",), previous_metadata_id=r["label2"].metadata_id,
                      recorded_at=day(3), governance_event_id=r["approval"].event_id)
    assert reopened.append_governance(r["approval"]).status is AppendStatus.ALREADY_PRESENT
    assert reopened.append_metadata(label3).status is AppendStatus.APPENDED               # 再 open 後も writer として使える
    assert ThemeStore.open(tmp_path).counts()["metadata"] == 3


def test_a4d2_read_only_reopen_and_audit_succeed(tmp_path: Path) -> None:
    """9: read-only open / audit / resolver 入口も同じ journal を受理し、承認が governance facet に現れる。"""
    store, r = approved_world(tmp_path)
    store.append_governance(r["approval"])
    read_only = ThemeStore.open(tmp_path, read_only=True)
    assert read_only.counts()["governance"] == 1
    audit = ThemeStore.audit(tmp_path)
    assert audit.counts["governance"] == 1 and audit.pending == () and audit.diagnostics == ()
    res = resolve_at_data_root(tmp_path, ROOT_Q, day(3))
    assert res.status is ResolutionStatus.RESOLVED
    assert res.governance.status is GovernanceStatus.RESOLVED
    assert res.governance.effective_event_type is GovernanceEventType.METADATA_CORRECTION_APPROVED
    assert res.governance.chain == (r["approval"].event_id,)
    label = next(m for m in res.metadata if m.field is MetadataField.LABEL)
    assert label.value == ("Yen weakness / input cost",)
    before = resolve_at_data_root(tmp_path, ROOT_Q, day(2))                          # 承認前の T は NO_GOVERNANCE のまま
    assert before.governance.status is GovernanceStatus.NO_GOVERNANCE


def test_a4d2_missing_metadata_target_fails_closed(tmp_path: Path) -> None:
    """10: 参照先 metadata が本当に無ければ append 拒否、file 上にあれば load で INVALID_HISTORY（cross pass）。"""
    store, r = approved_world(tmp_path)
    missing = event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED, subject_roots=(ROOT_Q,),
                    related_observations=(META_UNKNOWN,), reason="dangling", recorded_at=day(2, 1))
    before = authority_bytes(tmp_path)
    with rejected("GOVERNANCE_REFERENCE_MISSING"):
        store.append_governance(missing)
    assert authority_bytes(tmp_path) == before
    append_raw(store.paths["governance"], missing)
    with pytest.raises(ThemeInvalidHistory) as info:
        ThemeStore.open(tmp_path, read_only=True)
    assert (info.value.code, info.value.authority, info.value.line_number) == ("GOVERNANCE_REFERENCE_MISSING", "governance", 1)
    res = resolve_at_data_root(tmp_path, ROOT_Q, day(3))
    assert res.status is ResolutionStatus.INVALID_HISTORY and res.diagnostics[0].kind == "GOVERNANCE_REFERENCE_MISSING"


def test_a4d2_wrong_root_metadata_target_fails_closed(tmp_path: Path) -> None:
    """11: 別 root の metadata を参照する承認は append 拒否・load INVALID_HISTORY。"""
    store, r = approved_world(tmp_path)
    other = observation(root_id=ROOT_B, subject=subject("tourism inflow and service demand", ""), recorded_at=day(0, 1))
    store.append_root(root_record(other, created_at=day(0)))
    store.append_observation(other)
    other_label = metadata(root_id=ROOT_B, value=("Inbound tourism",), recorded_at=day(1))
    store.append_metadata(other_label)
    wrong = event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED, subject_roots=(ROOT_Q,),
                  related_observations=(other_label.metadata_id,), reason="wrong root", recorded_at=day(2, 1))
    with rejected("GOVERNANCE_REFERENCE_MISSING"):
        store.append_governance(wrong)
    append_raw(store.paths["governance"], wrong)
    with pytest.raises(ThemeInvalidHistory) as info:
        ThemeStore.open(tmp_path)
    assert info.value.code == "GOVERNANCE_REFERENCE_MISSING" and "outside the event's subjects" in info.value.detail


def test_a4d2_wrong_record_kind_fails_closed(tmp_path: Path) -> None:
    """11b: related record の種別違い（observation id を metadata 承認に、metadata id を role 承認に）は model / store で fail closed。"""
    store, r = approved_world(tmp_path)
    with pytest.raises(ThemeModelError, match="INVALID_RECORD_ID"):
        event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED, subject_roots=(ROOT_Q,),
              related_observations=(r["genesis"].observation_id,), reason="kind", recorded_at=day(2, 1))
    with pytest.raises(ThemeModelError, match="INVALID_RECORD_ID"):
        event(event_type=GovernanceEventType.ROLE_CORRECTION_APPROVED, subject_roots=(ROOT_Q,),
              related_observations=(r["label2"].metadata_id,), reason="kind", recorded_at=day(2, 1))
    payload = json.loads(canonical_line(r["approval"]))                             # bytes を直接改変した場合
    payload["related_observations"] = [r["genesis"].observation_id]
    with store.paths["governance"].open("ab") as handle:
        handle.write((json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
    with pytest.raises((ThemeStoreCorrupt, ThemeInvalidHistory)):
        ThemeStore.open(tmp_path, read_only=True)
    assert resolve_at_data_root(tmp_path, ROOT_Q, day(3)).status in (ResolutionStatus.STORE_CORRUPTION,
                                                                     ResolutionStatus.INVALID_HISTORY)


def test_a4d2_approval_before_metadata_record_is_rejected(tmp_path: Path) -> None:
    """11c: 承認が訂正 metadata より前に記録されている履歴は append / load とも NON_MONOTONIC_RECORDED_AT。"""
    store, r = approved_world(tmp_path)
    early = event(event_type=GovernanceEventType.METADATA_CORRECTION_APPROVED, subject_roots=(ROOT_Q,),
                  related_observations=(r["label2"].metadata_id,), reason="too early", recorded_at=day(1, 12))
    with rejected("NON_MONOTONIC_RECORDED_AT"):
        store.append_governance(early)
    append_raw(store.paths["governance"], early)
    with pytest.raises(ThemeInvalidHistory) as info:
        ThemeStore.open(tmp_path, read_only=True)
    assert info.value.code == "NON_MONOTONIC_RECORDED_AT" and info.value.authority == "governance"


def test_a4d2_canonical_governance_bytes_and_ids_unchanged_after_reopen(tmp_path: Path) -> None:
    """12: 再 open は bytes を 1 byte も変えず、governance 行は canonical 行そのもの、id は不変。"""
    store, r = approved_world(tmp_path)
    store.append_governance(r["approval"])
    frozen = authority_bytes(tmp_path)
    ThemeStore.open(tmp_path)
    ThemeStore.open(tmp_path, read_only=True)
    ThemeStore.audit(tmp_path)
    resolve_at_data_root(tmp_path, ROOT_Q, day(3))
    assert authority_bytes(tmp_path) == frozen
    lines = ThemeStore.open(tmp_path, read_only=True).canonical_lines("governance")
    assert lines == (canonical_line(r["approval"]),)
    assert json.loads(lines[0])["event_id"] == r["approval"].event_id
    assert json.loads(lines[0])["related_observations"] == [r["label2"].metadata_id]


# ================================================================ A4D-3 absent result root point-in-time

def declared_only(tmp_path: Path, kind: str):
    """two_roots → 宣言 event だけ書いて crash（result root は未作成）。"""
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = {"merge": lambda: merge_plan(store, obs_a, obs_b), "split": lambda: split_plan(store, obs_a),
            "successor": lambda: successor_plan(store, obs_a)}[kind]()
    interrupt_after(store, 1)
    with pytest.raises(SimulatedCrash):
        O.execute_declaration(store, plan)
    return plan, plan.event.recorded_at + H1


EXPECTED = {
    "merge": (ROOT_C, LineageKind.MERGE_OF, (ROOT_A, ROOT_B)),
    "split": (ROOT_D, LineageKind.SPLIT_FROM, (ROOT_A,)),
    "successor": (ROOT_D, LineageKind.SUCCESSOR_OF, (ROOT_A,)),
}


def assert_declared_pending(view, event_id: str, root_id: str, kind: LineageKind, related) -> None:
    assert view.status is ResolutionStatus.NO_STATE and view.root is None and view.observation is None
    assert view.evidence is None and view.derived is None and view.carried == ()
    assert [(d.kind, d.subject_id, d.related) for d in view.diagnostics] == [("ROOT_AFTER_CUTOFF", root_id, (event_id,))]
    assert [(p.kind, p.subject_id, p.missing) for p in view.pending] == [("PENDING_EVENT", event_id, (root_id,))]
    assert [(l.kind, l.event_id, l.related_roots) for l in view.lineage] == [(kind, event_id, related)]
    assert view.governance.status is GovernanceStatus.NOT_EVALUATED


@pytest.mark.parametrize("kind", ["merge", "split", "successor"])
def test_a4d3_absent_result_root_with_visible_declaration_is_pending_event(tmp_path: Path, kind: str) -> None:
    """13 / 14 / 15: merge / split / successor の宣言だけが T で可視 → result root は PENDING_EVENT ＋ 宣言由来 lineage。"""
    plan, cutoff = declared_only(tmp_path, kind)
    root_id, lineage_kind, related = EXPECTED[kind]
    view = resolve_at_data_root(tmp_path, root_id, cutoff)
    assert_declared_pending(view, plan.event.event_id, root_id, lineage_kind, related)
    for subject_root in plan.event.subject_roots:                                    # subject 側は従来どおり
        subject_view = resolve_at_data_root(tmp_path, subject_root, cutoff)
        assert subject_view.status is ResolutionStatus.RESOLVED
        assert [(p.kind, p.missing) for p in subject_view.pending] == [("PENDING_EVENT", tuple(plan.event.result_roots))]
    if kind == "split":                                                              # 2 つ目の子 root も同じ
        assert_declared_pending(resolve_at_data_root(tmp_path, ROOT_E, cutoff), plan.event.event_id, ROOT_E,
                                LineageKind.SPLIT_FROM, (ROOT_A,))


def test_a4d3_split_second_child_stays_pending_after_first_child_completes(tmp_path: Path) -> None:
    """14b: split の 1 つ目の子（root ＋ genesis）が完了しても、未作成の 2 つ目の子は宣言だけから PENDING_EVENT。"""
    store, obs_a, _obs_b = two_roots(tmp_path)
    plan = split_plan(store, obs_a)
    interrupt_after(store, 3)                                                        # event → D root → D genesis → crash
    with pytest.raises(SimulatedCrash):
        O.execute_declaration(store, plan)
    cutoff = max(plan.results[1][0].created_at, plan.results[1][1].recorded_at) + H1
    assert resolve_at_data_root(tmp_path, ROOT_D, cutoff).status is ResolutionStatus.RESOLVED
    assert_declared_pending(resolve_at_data_root(tmp_path, ROOT_E, cutoff), plan.event.event_id, ROOT_E,
                            LineageKind.SPLIT_FROM, (ROOT_A,))


@pytest.mark.parametrize("kind", ["merge", "split", "successor"])
def test_a4d3_future_completion_leaves_historical_result_exactly_unchanged(tmp_path: Path, kind: str) -> None:
    """16: journal 完成後（root ＋ genesis が T より後に追加）も、同じ T の結果は result root / subject root とも完全一致。"""
    plan, cutoff = declared_only(tmp_path, kind)
    roots = tuple(plan.event.result_roots) + tuple(plan.event.subject_roots)
    before = {r: resolve_at_data_root(tmp_path, r, cutoff) for r in roots}
    completed = O.execute_declaration(ThemeStore.open(tmp_path), plan)
    assert completed.status is O.OperationStatus.COMPLETE
    after = {r: resolve_at_data_root(tmp_path, r, cutoff) for r in roots}
    assert after == before                                                           # 診断・pending・lineage を含めて同一
    later = max(spec.created_at for spec, _ in plan.results) + timedelta(days=1)
    assert all(resolve_at_data_root(tmp_path, r, later).status is ResolutionStatus.RESOLVED for r in plan.event.result_roots)
    history = ThemeHistory.from_store(ThemeStore.open(tmp_path, read_only=True))
    rng = random.Random(7)
    shuffled = ThemeHistory(*(tuple(rng.sample(list(part), len(part))) for part in
                              (history.roots, history.observations, history.events, history.metadata, history.mappings)))
    assert all(resolve(shuffled, r, cutoff) == before[r] for r in roots)


def test_a4d3_before_declaration_is_unknown_root(tmp_path: Path) -> None:
    """17: 宣言 event が T で不可視なら result root id は従来どおり UNKNOWN_ROOT（pending / lineage なし）。完成後も同じ。"""
    plan, _cutoff = declared_only(tmp_path, "merge")
    before_event = plan.event.recorded_at - S1
    early = resolve_at_data_root(tmp_path, ROOT_C, before_event)
    assert early.status is ResolutionStatus.NO_STATE and [d.kind for d in early.diagnostics] == ["UNKNOWN_ROOT"]
    assert early.pending == () and early.lineage == ()
    O.execute_declaration(ThemeStore.open(tmp_path), plan)
    completed = resolve_at_data_root(tmp_path, ROOT_C, before_event)
    assert completed.status is ResolutionStatus.NO_STATE and completed.pending == () and completed.lineage == ()
    assert completed.root is None and completed.observation is None
    # RootRecord が履歴に存在するようになった後は A3 §13 step 1（created_at > T）の ROOT_AFTER_CUTOFF。宣言由来の
    # pending / lineage は宣言前の T には現れない（A4c 以前からの候補 root と同じ挙動）
    assert [d.kind for d in completed.diagnostics] == ["ROOT_AFTER_CUTOFF"]
    assert knowable_digest(completed) == knowable_digest(early)


def test_a4d3_arbitrary_undeclared_root_is_unknown_root(tmp_path: Path) -> None:
    """18: どの event にも宣言されていない root id は、宣言後・完成後のどの T でも UNKNOWN_ROOT。"""
    plan, cutoff = declared_only(tmp_path, "merge")
    for at in (plan.event.recorded_at - S1, cutoff, cutoff + timedelta(days=30)):
        view = resolve_at_data_root(tmp_path, ROOT_E, at)
        assert view.status is ResolutionStatus.NO_STATE and [d.kind for d in view.diagnostics] == ["UNKNOWN_ROOT"]
        assert view.pending == () and view.lineage == () and view.root is None
    O.execute_declaration(ThemeStore.open(tmp_path), plan)
    assert [d.kind for d in resolve_at_data_root(tmp_path, ROOT_E, cutoff).diagnostics] == ["UNKNOWN_ROOT"]


def test_a4d3_no_future_lineage_leak_before_declaration(tmp_path: Path) -> None:
    """19: 完成した journal でも、宣言 event より前の T では subject root にも result root にも lineage / pending が現れない。"""
    plan, _cutoff = declared_only(tmp_path, "successor")
    O.execute_declaration(ThemeStore.open(tmp_path), plan)
    before_event = plan.event.recorded_at - S1
    subject_view = resolve_at_data_root(tmp_path, ROOT_A, before_event)
    assert subject_view.status is ResolutionStatus.RESOLVED and subject_view.lineage == () and subject_view.pending == ()
    assert subject_view.governance.status is GovernanceStatus.NO_GOVERNANCE
    result_view = resolve_at_data_root(tmp_path, ROOT_D, before_event)
    assert result_view.status is ResolutionStatus.NO_STATE and result_view.lineage == () and result_view.pending == ()
    assert [d.kind for d in result_view.diagnostics] == ["ROOT_AFTER_CUTOFF"]     # A3 §13 step 1（記録済み root、T 前）
    at_event = resolve_at_data_root(tmp_path, ROOT_D, plan.event.recorded_at)     # 宣言と同時刻から可視
    assert [p.kind for p in at_event.pending] == ["PENDING_EVENT"] and at_event.lineage[0].kind is LineageKind.SUCCESSOR_OF


def test_a4d3_redeclared_result_root_is_invalid_history_not_latest_wins(tmp_path: Path) -> None:
    """19b: 同じ result root を 2 つの eligible event が宣言する履歴は latest-wins で選ばず INVALID_HISTORY（store は append で拒否）。"""
    store, obs_a, obs_b = two_roots(tmp_path)
    plan = merge_plan(store, obs_a, obs_b)
    interrupt_after(store, 1)
    with pytest.raises(SimulatedCrash):
        O.execute_declaration(store, plan)
    again = event(event_type=GovernanceEventType.MERGE, subject_roots=(ROOT_A, ROOT_B), result_roots=(ROOT_C,),
                  reason="declared twice", recorded_at=plan.event.recorded_at + H1,
                  previous_event_ids=((ROOT_A, plan.event.event_id), (ROOT_B, plan.event.event_id)))
    assert again.event_id != plan.event.event_id
    with rejected("RESULT_ROOT_REDECLARED"):
        ThemeStore.open(tmp_path).append_governance(again)
    base = ThemeHistory.from_store(ThemeStore.open(tmp_path, read_only=True))
    synthetic = ThemeHistory(base.roots, base.observations, base.events + (again,), base.metadata, base.mappings)
    view = resolve(synthetic, ROOT_C, again.recorded_at + H1)
    assert view.status is ResolutionStatus.INVALID_HISTORY and view.pending == () and view.lineage == ()
    assert [(d.kind, d.related) for d in view.diagnostics] == [("RESULT_ROOT_REDECLARED",
                                                                 tuple(sorted((plan.event.event_id, again.event_id))))]
    single = resolve(synthetic, ROOT_C, plan.event.recorded_at + timedelta(minutes=30))   # 2 つ目が不可視な T は従来どおり
    assert [p.subject_id for p in single.pending] == [plan.event.event_id]
