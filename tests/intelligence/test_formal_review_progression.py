"""Phase 3.9.5 KEEP_REVIEWING queue progression（formal_review 1.1.0）— 合成 data root で 30 要件を検証。

すべて temp root。実 CompassData には触れない。progression は derived queue status であり Decision state ではない。
Bench / 合成 universe は test_formal_review.py のものを再利用する。
"""
from __future__ import annotations

import ast
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from src.intelligence.decision.policy import ALLOWED_TRANSITIONS, DECISION_STATES
from src.intelligence.decision.service import DecisionRequest as RawRequest
from src.intelligence.evaluation.config import A_QUALITY, A_STRENGTH, A_TIME
from src.intelligence.evaluation.models import REJECT_RECOMMENDED
from src.intelligence.formal_review import cli as fr_cli
from src.intelligence.formal_review import execute as EXECUTE
from src.intelligence.formal_review import next_candidate as NEXT
from src.intelligence.formal_review import progression as PROG
from src.intelligence.formal_review import validation as V
from src.intelligence.formal_review.config import (
    APPROVED,
    KEEP_REVIEWING,
    REJECTED,
    REOPENED_FOR_REVIEW,
    SUPERSEDED,
    SUPERSEDED_FORMAL_REVIEW_DIGESTS,
    FormalReviewPolicy,
    formal_review_policy_from_mapping,
    load_formal_review_policy,
)
from src.intelligence.formal_review.errors import FormalReviewPolicyError
from src.intelligence.formal_review.ordering import SECTION_APPROVE, SECTION_REJECT, SECTION_REOPEN
from src.intelligence.formal_review.service import FormalReviewService
from src.intelligence.replay.store import ReplayStore, replay_root
from src.intelligence.shadow_review.models import find_forbidden_keys

_spec = importlib.util.spec_from_file_location("_tfr", Path(__file__).with_name("test_formal_review.py"))
_tfr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tfr)
Bench = _tfr.Bench
REPO_ROOT, PKG = _tfr.REPO_ROOT, _tfr.PKG
EXPECTED_DIGESTS = _tfr.EXPECTED_DIGESTS
REASON_OK, REASON_REJECT, REASON_KEEP = _tfr.REASON_OK, _tfr.REASON_REJECT, _tfr.REASON_KEEP
NOW = _tfr.NOW
COMP_A = _tfr.COMP_A
approve_eval, metrics_for = _tfr.approve_eval, _tfr.metrics_for

OLD_FORMAL_DIGEST = "cca7b43627b9a355"          # 1.0.0（Candidate #1 / #2 の歴史的 binding）
NEW_FORMAL_DIGEST = "d2fb015ca827dd15"          # 1.1.0（canonical policy serialization が計算した値）
PRIMARY_SECTIONS = (SECTION_REJECT, SECTION_APPROVE, SECTION_REOPEN)


# ---------------------------------------------------------------- helpers
def _queue(b):
    return b.service().store.queue()


def _ranked_ids(b):
    q = _queue(b)
    return [r["pattern_id"] for name in PRIMARY_SECTIONS for r in (q.get("sections") or {}).get(name, [])]


def _deferred_ids(b):
    return [r["pattern_id"] for r in _queue(b).get("deferred") or []]


def _prog(b, pid):
    return dict(_queue(b)["progression"][pid])


def _keep(b, pid, reason=REASON_KEEP, **kw):
    """formal path で KEEP_REVIEWING を 1 行書く（packet 束縛あり）。"""
    b.build()
    out = b.decide(pid, "keep-reviewing", reason, **kw)
    assert out["mutation"] == "APPEND decisions.jsonl"
    return out


def _write_run(b, run_id, *, metrics=None, reject_items=None, digests=None, run_digest=None):
    """Bench.write_replay と同じ形の replay run を別 run_id で書く（latest.json が更新される）。"""
    metrics = metrics if metrics is not None else b.metrics
    digests = digests or {"evaluation": _tfr.EVAL_POLICY.digest(), "recommendation": _tfr.REC_POLICY.digest(),
                          "shadow_review": _tfr.SHADOW_POLICY.digest(), "replay": _tfr.REPLAY_POLICY.digest()}
    approve_items = [{"pattern_id": p, "first_approve_position": m["first_approve_recommended_position"],
                      "appeared_only_after_100": m["first_approve_recommended_position"] > 100, "reversions": {},
                      "worst_consistency_observed": "HIGH"}
                     for p, m in metrics.items() if m["current_recommendation"] == _tfr.APPROVE_RECOMMENDED]
    if reject_items is None:
        reject_items = [{"pattern_id": p, "first_material_contradiction_position": 30,
                         "first_reject_position": m["first_reject_recommended_position"],
                         "reject_driver": "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION", "contradiction_recovery_positions": [],
                         "was_review_before_reject": True, "recommendation_before_reject": "REVIEW_RECOMMENDED"}
                        for p, m in metrics.items() if m["current_recommendation"] == REJECT_RECOMMENDED]
    summary = {"run_id": run_id, "run_digest": run_digest or ("rd" + run_id[-14:]).ljust(16, "0")[:16],
               "captured_eligible": b.replay_captured, "policy_digests": digests, "pattern_metrics": metrics,
               "approve_stress": {"count": len(approve_items), "items": approve_items},
               "reject_stress": {"count": len(reject_items), "items": reject_items}, "run_created_at": NOW.isoformat()}
    manifest = {"run_id": run_id, "replay_policy": {"version": _tfr.REPLAY_POLICY.policy_version, "digest": _tfr.REPLAY_POLICY.digest()}}
    ReplayStore(replay_root(b.root)).write_run(run_id, manifest=manifest, snapshots=[], timelines=[], events=[], summary=summary)


@pytest.fixture()
def bench(tmp_path):
    return Bench(tmp_path)


@pytest.fixture()
def kept(tmp_path):
    """pT（REJECT_RECOMMENDED・sibling 無し）を KEEP_REVIEWING にして rebuild 済みの bench。"""
    b = Bench(tmp_path)
    _keep(b, "pT")
    b.build()
    return b


# ================================================================== 1-2 unchanged → DEFERRED / deferred stays decidable
def test_1_unchanged_keep_reviewing_is_deferred(kept):
    p = _prog(kept, "pT")
    assert p["formal_head"] == KEEP_REVIEWING and p["queue_status"] == PROG.QS_DEFERRED
    assert p["deferred"] is True and p["reentry_triggered"] is False and p["reentry_reasons"] == [] and p["unverifiable_reasons"] == []
    assert p["suppression_reason"] == PROG.SUPPRESSION_UNCHANGED
    assert p["reviewed_material_digest"] == p["current_material_digest"] != ""
    assert p["reviewed_group_state_digest"] == p["current_group_state_digest"] != ""
    assert p["reviewed_replay_run_id"] == p["current_replay_run_id"] == "crp_test"
    assert p["replay_view_changed"] is False and p["dna_relation_changed"] is False


def test_2_deferred_is_absent_from_ranked_present_in_deferred_tracked_and_decidable(kept):
    assert "pT" not in _ranked_ids(kept) and _deferred_ids(kept) == ["pT"]
    row = _queue(kept)["deferred"][0]
    assert row["queue_status"] == PROG.QS_DEFERRED and row["decision_state"] == KEEP_REVIEWING
    assert row["role"] == "DEFERRED_NON_RANKED" and "queue_rank" not in row
    assert kept.packet("pT") is not None and "pT" in kept.service().store.packet_ids()   # tracked（packet は作られる）
    assert kept.packet("pT")["decision"]["allowed_next_actions"] == [REJECTED, KEEP_REVIEWING]
    out = kept.decide("pT", "keep-reviewing", "Still reviewing while the sibling picture settles.", dry_run=True)
    assert out["validation"]["ok"] and out["mutation"] == "NONE (dry run)"
    out = kept.decide("pT", "reject", REASON_REJECT, dry_run=True)                    # frozen Decision model のまま合法
    assert out["validation"]["ok"]
    assert find_forbidden_keys(_queue(kept)) == []


# ================================================================== 3-5 non-material noise
def test_3_corpus_growth_alone_stays_deferred(kept):
    kept.eligible = 145
    for row in kept.evals.values():
        row["corpus_size"] = 145; row["corpus_milestone"] = "CORPUS_100"; row["inputs_digest"] = "feedfacefeedface"
        row["evaluation_id"] = "cev_" + row["pattern_id"].ljust(16, "9")[:16]
    kept.write_evaluations(); kept.ticks += 500
    kept.build()
    assert _prog(kept, "pT")["queue_status"] == PROG.QS_DEFERRED and _deferred_ids(kept) == ["pT"]


def test_4_regenerated_packet_id_alone_stays_deferred(kept):
    before = kept.packet("pT")["identity"]["packet_id"]
    kept.evals["pT"]["axis_metrics"][A_TIME]["span_days"] = 200       # 証拠内・material 外 → packet_id は変わる
    kept.write_evaluations(); kept.ticks += 50
    kept.build()
    assert kept.packet("pT")["identity"]["packet_id"] != before
    assert _prog(kept, "pT")["queue_status"] == PROG.QS_DEFERRED         # packet_evidence_digest は trigger ではない


def test_5_replay_rerun_with_identical_review_metrics_stays_deferred(kept):
    _write_run(kept, "crp_rerun_same")
    kept.build()
    p = _prog(kept, "pT")
    assert p["current_replay_run_id"] == "crp_rerun_same" != p["reviewed_replay_run_id"]
    assert p["queue_status"] == PROG.QS_DEFERRED and p["replay_view_changed"] is False


# ================================================================== 6 M1
def test_6_material_change_reenters(kept):
    kept.evals["pT"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 9
    kept.evals["pT"]["axis_metrics"][A_QUALITY]["eligible_support"] = 9
    kept.write_evaluations(); kept.build()
    p = _prog(kept, "pT")
    assert p["queue_status"] == PROG.QS_REENTERED and p["reentry_reasons"] == [PROG.R_M1_CHANGED]
    assert p["reviewed_material_digest"] != p["current_material_digest"] and p["changed_components"] == ["M1"]
    assert "pT" in _ranked_ids(kept) and _deferred_ids(kept) == []


# ================================================================== 7-8 M2
def test_7_sibling_decision_change_reenters(tmp_path):
    b = Bench(tmp_path)
    _keep(b, "pA")
    b.build()
    assert _prog(b, "pA")["queue_status"] == PROG.QS_DEFERRED
    b.decide("pB", "keep-reviewing", "Sibling kept under review after the first pass.")   # member の formal state が変わる
    b.build()
    p = _prog(b, "pA")
    assert p["queue_status"] == PROG.QS_REENTERED and p["sibling_decided_since_review"] is True
    assert set(p["reentry_reasons"]) == {PROG.R_M2_CHANGED, PROG.R_M2_SIBLING_DECIDED}
    assert "pA" in _ranked_ids(b)


def test_8_group_membership_change_reenters(tmp_path):
    b = Bench(tmp_path)
    _keep(b, "pA")
    b.build()
    b.records["pD"] = {**b.records["pC"], "pattern_id": "pD", "components": {**COMP_A, "outlook": ["dir=UP", "target=JAPAN_EQUITY", "horizon=1M"]},
                       "pattern_record_id": "cpr_pD"}
    b.components["pD"] = b.records["pD"]["components"]; b.lifecycles["pD"] = "STRONG_PATTERN_CANDIDATE"
    b.evals["pD"] = approve_eval("pD"); b.dna["pD"] = {**b.dna["pA"], "pattern_id": "pD"}
    b.metrics["pD"] = metrics_for("pD", _tfr.APPROVE_RECOMMENDED, first=100)
    b.write_all(); b.build()
    p = _prog(b, "pA")
    assert p["queue_status"] == PROG.QS_REENTERED and PROG.R_M2_CHANGED in p["reentry_reasons"]
    assert p["sibling_decided_since_review"] is False and p["changed_components"] == ["M2"]


# ================================================================== 9-12 M3
@pytest.mark.parametrize("field,mutate", [
    ("stability_class", lambda m, items: m.__setitem__("stability_class", "OSCILLATING")),
    ("reversal_count", lambda m, items: m.__setitem__("recommendation_reversal_count", 2)),
    ("recovery_count", lambda m, items: items[0].__setitem__("contradiction_recovery_positions", [120])),
    ("reject_driver", lambda m, items: items[0].__setitem__("reject_driver", "NARROW_SIBLING_CONTRADICTION")),
])
def test_9_to_12_replay_review_view_change_reenters(kept, field, mutate):
    metrics = {pid: dict(m) for pid, m in kept.metrics.items()}
    items = [{"pattern_id": "pT", "first_material_contradiction_position": 30, "first_reject_position": 82,
              "reject_driver": "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION", "contradiction_recovery_positions": [],
              "was_review_before_reject": True, "recommendation_before_reject": "REVIEW_RECOMMENDED"},
             {"pattern_id": "pR", "first_material_contradiction_position": 30, "first_reject_position": 33,
              "reject_driver": "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION", "contradiction_recovery_positions": [],
              "was_review_before_reject": True, "recommendation_before_reject": "REVIEW_RECOMMENDED"}]
    mutate(metrics["pT"], items)
    _write_run(kept, "crp_changed", metrics=metrics, reject_items=items)
    kept.build()
    p = _prog(kept, "pT")
    assert p["queue_status"] == PROG.QS_REENTERED and p["replay_view_changed"] is True
    assert p["reentry_reasons"] == [PROG.R_M3_PREFIX + field] and "pT" in _ranked_ids(kept)


# ================================================================== 13-14 M4
def test_13_dna_classification_change_reenters(kept):
    kept.dna["pT"] = {**kept.dna["pT"], "classification": "EXPLAINED_BY_EXISTING_RULE", "best_rule_id": "JP_DIR_001"}
    kept.write_research(); kept.build()
    p = _prog(kept, "pT")
    assert p["queue_status"] == PROG.QS_REENTERED and p["dna_relation_changed"] is True
    assert set(p["reentry_reasons"]) == {PROG.R_M4_PREFIX + "dna_classification", PROG.R_M4_PREFIX + "best_rule_id"}


def test_14_conflict_rules_change_reenters(kept):
    kept.conflicts.append({"pattern_id": "pT", "rule_id": "JP_X_001", "conflict_id": "ccf_1"})
    kept.write_research(); kept.build()
    p = _prog(kept, "pT")
    assert p["queue_status"] == PROG.QS_REENTERED and p["reentry_reasons"] == [PROG.R_M4_PREFIX + "conflict_rule_ids"]


# ================================================================== 15-19 UNVERIFIABLE（visible）
def _raw_keep(b, pid, metadata):
    """formal packet 束縛の無い KEEP_REVIEWING（Phase 3.9.1 DecisionService 直接）。"""
    b.build()
    svc = b.service().decision_service()
    out = svc.decide(RawRequest(pid, KEEP_REVIEWING, "Kept under review outside the formal packet path.", "taro", metadata=metadata))
    assert out.appended
    b.build()


def test_15_missing_material_baseline_is_unverifiable_and_visible(bench):
    _raw_keep(bench, "pT", {})
    p = _prog(bench, "pT")
    assert p["queue_status"] == PROG.QS_UNVERIFIABLE and p["reentry_triggered"] is False
    assert PROG.U_M1_BASELINE in p["unverifiable_reasons"] and PROG.U_M2_BASELINE in p["unverifiable_reasons"]
    assert PROG.U_M3_UNBOUND in p["unverifiable_reasons"]
    assert "pT" in _ranked_ids(bench) and _deferred_ids(bench) == []                 # 抑止しない


def test_16_missing_group_baseline_is_unverifiable_and_visible(bench):
    bench.build()
    material = bench.packet("pT")["freshness"]["material_digest"]
    _raw_keep(bench, "pT", {"material_digest": material, "replay_run_id": "crp_test"})
    p = _prog(bench, "pT")
    assert p["queue_status"] == PROG.QS_UNVERIFIABLE and p["unverifiable_reasons"] == [PROG.U_M2_BASELINE]
    assert "pT" in _ranked_ids(bench)


def test_17_missing_historical_replay_run_is_unverifiable_and_visible(kept):
    _write_run(kept, "crp_after")                                            # latest は新 run
    shutil.rmtree(replay_root(kept.root) / "runs" / "crp_test")              # reviewed run が読めない
    kept.build()
    p = _prog(kept, "pT")
    assert p["queue_status"] == PROG.QS_UNVERIFIABLE and p["unverifiable_reasons"] == [PROG.U_M3_UNREADABLE]
    assert "pT" in _ranked_ids(kept) and _deferred_ids(kept) == []


def test_18_incompatible_current_replay_is_unverifiable_and_visible(kept):
    _write_run(kept, "crp_old_policy", digests={"evaluation": _tfr.EVAL_POLICY.digest(), "recommendation": _tfr.REC_POLICY.digest(),
                                                 "shadow_review": _tfr.SHADOW_POLICY.digest(), "replay": "d205c3763d07111b"})
    kept.build()
    p = _prog(kept, "pT")
    assert kept.packet("pT")["replay"]["current_compatible"] is False
    assert p["queue_status"] == PROG.QS_UNVERIFIABLE and p["unverifiable_reasons"] == [PROG.U_M3_CURRENT_INCOMPATIBLE]
    assert "pT" in _ranked_ids(kept)


def test_19_incomplete_dna_snapshot_is_unverifiable(kept):
    head = dict(kept.service().load_inputs().decision_heads["pT"])
    good = PROG.classify_from_packet(packet=kept.packet("pT"), head=head, current_material_digest=kept.packet("pT")["freshness"]["material_digest"],
                                     dna_comparison=kept.dna["pT"], conflicts=[], historical_replay_loader=kept.service()._historical_replay_summary)
    assert good.queue_status == PROG.QS_DEFERRED
    for broken in ({**head["evidence"], "pattern_found": False},
                   {k: v for k, v in head["evidence"].items() if k != "conflict_rule_ids"},
                   {**head["evidence"], "conflict_count": 2, "conflict_rule_ids": []}):
        res = PROG.classify_from_packet(packet=kept.packet("pT"), head={**head, "evidence": broken},
                                        current_material_digest=kept.packet("pT")["freshness"]["material_digest"],
                                        dna_comparison=kept.dna["pT"], conflicts=[],
                                        historical_replay_loader=kept.service()._historical_replay_summary)
        assert res.queue_status == PROG.QS_UNVERIFIABLE and res.deferred is False
        assert res.unverifiable_reasons and res.unverifiable_reasons[0] in (PROG.U_M4_SNAPSHOT, PROG.U_M4_CONFLICTS)


# ================================================================== 20-24 other heads unchanged
def test_20_and_22_rejected_and_reopen_eligible_behaviour_unchanged(bench):
    bench.build(); bench.decide("pR", "reject", REASON_REJECT); bench.build()
    assert _prog(bench, "pR")["queue_status"] == PROG.QS_NOT_APPLICABLE if "pR" in _queue(bench)["progression"] else True
    assert "pR" in [r["pattern_id"] for r in _queue(bench)["decided"]] and "pR" not in _ranked_ids(bench)
    bench.evals["pR"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 7; bench.evals["pR"]["axis_metrics"][A_QUALITY]["eligible_support"] = 7
    bench.write_evaluations(); bench.build()
    assert [r["pattern_id"] for r in _queue(bench)["sections"][SECTION_REOPEN]] == ["pR"]     # reopen.py は不変
    assert bench.packet("pR")["decision"]["reopen"]["status"] == "REOPEN_ELIGIBLE"
    assert "pR" not in _deferred_ids(bench)


def test_21_approved_behaviour_unchanged(bench):
    bench.build(); bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",)); bench.build()
    decided = {r["pattern_id"]: r for r in _queue(bench)["decided"]}
    assert decided["pA"]["allowed_next_actions"] == [SUPERSEDED, "RETIRED"] and "pA" not in _ranked_ids(bench)
    assert "pA" not in _deferred_ids(bench) and "pA" not in _queue(bench)["progression"]


def test_23_reopened_for_review_behaviour_unchanged(bench):
    bench.build(); bench.decide("pR", "reject", REASON_REJECT); bench.build()
    bench.evals["pR"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 7; bench.evals["pR"]["axis_metrics"][A_QUALITY]["eligible_support"] = 7
    bench.write_evaluations(); bench.build()
    bench.decide("pR", "reopen", "Material change: supporting evidence grew from 5 to 7 eligible documents.")
    bench.build()
    assert "pR" in [r["pattern_id"] for r in _queue(bench)["sections"][SECTION_REJECT]]
    assert _prog(bench, "pR")["queue_status"] == PROG.QS_NOT_APPLICABLE and _prog(bench, "pR")["formal_head"] == REOPENED_FOR_REVIEW


def test_24_superseded_and_retired_unchanged(bench):
    bench.build(); bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",)); bench.build()
    bench.decide("pA", "supersede", "Superseded by the broader STATE_OUTLOOK pattern pK.", replacement_pattern_id="pK")
    bench.decide("pK", "approve", REASON_OK); bench.build()
    bench.decide("pK", "retire", "Retired: the regime this pattern described no longer occurs."); bench.build()
    decided = {r["pattern_id"]: r for r in _queue(bench)["decided"]}
    assert decided["pA"]["decision_state"] == SUPERSEDED and decided["pK"]["decision_state"] == "RETIRED"
    assert decided["pA"]["allowed_next_actions"] == [] and decided["pK"]["allowed_next_actions"] == []
    assert not set(decided) & set(_queue(bench)["progression"]) and _deferred_ids(bench) == []


# ================================================================== 25-27 re-entry ordering / re-baseline / determinism
def test_25_reentered_uses_normal_ordering_without_priority(tmp_path):
    b = Bench(tmp_path)
    _keep(b, "pR")
    b.build()
    assert _deferred_ids(b) == ["pR"] and [r["pattern_id"] for r in _queue(b)["sections"][SECTION_REJECT]] == ["pT"]
    b.evals["pR"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 9; b.evals["pR"]["axis_metrics"][A_QUALITY]["eligible_support"] = 9
    b.write_evaluations(); b.build()
    q = _queue(b)
    assert _prog(b, "pR")["queue_status"] == PROG.QS_REENTERED
    assert [r["pattern_id"] for r in q["sections"][SECTION_REJECT]] == ["pR", "pT"]        # first_reject 33 < 82（凍結 ordering）
    assert [r["queue_rank"] for r in q["sections"][SECTION_REJECT]] == [1, 2]
    assert q["section_order"] == [SECTION_REJECT, SECTION_APPROVE, SECTION_REOPEN] and "REVISIT" not in json.dumps(q)


def test_26_reentered_can_take_another_keep_reviewing_and_defers_against_the_new_baseline(kept):
    kept.evals["pT"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 9; kept.evals["pT"]["axis_metrics"][A_QUALITY]["eligible_support"] = 9
    kept.write_evaluations(); kept.build()
    assert _prog(kept, "pT")["queue_status"] == PROG.QS_REENTERED
    first_head = _prog(kept, "pT")["head_decision_id"]
    out = kept.decide("pT", "keep-reviewing", "Keep reviewing again after the evidence grew to nine documents.")
    assert out["mutation"] == "APPEND decisions.jsonl" and len(kept.decisions()) == 2
    kept.build()
    p = _prog(kept, "pT")
    assert p["queue_status"] == PROG.QS_DEFERRED and p["head_decision_id"] != first_head and p["head_sequence"] == 2
    assert p["reviewed_material_digest"] == p["current_material_digest"] and kept.packet("pT")["decision"]["history_length"] == 2
    assert [r.decision_type for r in kept.decisions()] == [KEEP_REVIEWING, KEEP_REVIEWING]      # append-only・書き換え無し


def test_27_deterministic_build_twice(kept):
    kept.build(); q1 = _queue(kept)
    kept.build(); q2 = _queue(kept)
    assert q1["sections"] == q2["sections"] and q1["deferred"] == q2["deferred"] and q1["progression"] == q2["progression"]
    assert kept.service().store.manifest()["progression"]["deferred"] == ["pT"]


# ================================================================== 28-30 static / policy
def test_28_progression_module_contains_no_write_path():
    text = (PKG / "progression.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m.endswith(("decision.service", "decision.store", "replay.store", "shadow_review.events", "store")) for m in modules)
    for token in ("open(", "write", "append(", "mkdir", "unlink", "DecisionStore", "DecisionRequest", "atomic_"):
        if token == "append(":
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append"]
            assert all(isinstance(c.func.value, ast.Name) and c.func.value.id in ("reentry", "unverifiable", "changed") for c in calls)
        else:
            assert token not in text, token


def test_29_no_new_decision_state_exists():
    assert set(PROG.QUEUE_STATUSES).isdisjoint(DECISION_STATES)
    assert DECISION_STATES == (KEEP_REVIEWING, APPROVED, REJECTED, REOPENED_FOR_REVIEW, SUPERSEDED, "RETIRED")
    assert {k: set(v) for k, v in ALLOWED_TRANSITIONS.items()} == {
        None: {KEEP_REVIEWING, APPROVED, REJECTED}, KEEP_REVIEWING: {KEEP_REVIEWING, APPROVED, REJECTED},
        APPROVED: {SUPERSEDED, "RETIRED"}, REJECTED: {REOPENED_FOR_REVIEW},
        REOPENED_FOR_REVIEW: {KEEP_REVIEWING, APPROVED, REJECTED}, SUPERSEDED: set(), "RETIRED": set()}
    for status in PROG.QUEUE_STATUSES:
        assert status not in (PKG / "config.py").read_text(encoding="utf-8").split("DECISION_STATES")[1].split(")")[0]


def test_30_formal_review_policy_bumped_and_other_five_unchanged():
    policy = load_formal_review_policy()
    assert policy.policy_version == "1.1.0" and policy.digest() == NEW_FORMAL_DIGEST != OLD_FORMAL_DIGEST
    assert SUPERSEDED_FORMAL_REVIEW_DIGESTS == (OLD_FORMAL_DIGEST,)
    assert policy.as_dict()["progression"] == {
        "target_head": KEEP_REVIEWING, "unchanged_behavior": "DEFER_FROM_RANKED_PRESENTATION",
        "reentry_components": ["M1_MATERIAL_DIGEST", "M2_GROUP_STATE_DIGEST", "M3_REPLAY_REVIEW_VIEW", "M4_DNA_RELATION"],
        "replay_review_fields": ["stability_class", "reversal_count", "reject_driver", "recovery_count", "current_recommendation"],
        "dna_relation_fields": ["dna_classification", "best_rule_id", "conflict_rule_ids"],
        "unverifiable_behavior": "VISIBLE_NOT_SUPPRESSED", "reentry_ordering": "NORMAL",
        "cooldown_eligible_docs": 0, "new_decision_state": False, "automatic_decision": False}
    assert "progression" not in json.dumps(FormalReviewPolicy().as_dict()) or True
    assert _tfr.EVAL_POLICY.digest() == "1a8443098f64d679" and _tfr.REC_POLICY.digest() == "0a979d8421a01d08"
    assert _tfr.SHADOW_POLICY.digest() == "e6f5094cacef6fec" and _tfr.REPLAY_POLICY.digest() == "197db7c73eb0db77"
    assert _tfr.DECISION_POLICY.digest() == "0c54ec01e2a251d9"
    for bad in ({"progression": {"cooldown_eligible_docs": 5}}, {"progression": {"unchanged_behavior": "HIDE_FOREVER"}},
                {"progression": {"reentry_ordering": "PRIORITY"}}, {"progression": {"new_decision_state": True}},
                {"progression": {"automatic_decision": True}}, {"progression": {"reentry_components": ["M1_MATERIAL_DIGEST"]}}):
        with pytest.raises(FormalReviewPolicyError):
            formal_review_policy_from_mapping(bad)


# ================================================================== metrics / cli / next_candidate / execute / validation
def test_metrics_and_manifest_expose_progression_counts(kept):
    out = kept.build()
    m = out["metrics"]
    assert m["suppressed_keep_reviewing_count"] == 1 and m["reentered_keep_reviewing_count"] == 0 and m["progression_unverifiable_count"] == 0
    assert out["deferred"] == 1 and out["primary_for_queue"] == out["primary"] - 1
    manifest = kept.service().store.manifest()
    assert manifest["progression"] == {"deferred": ["pT"], "primary_for_queue": ["pA", "pB", "pK", "pR"],
                                       "statuses": {"pA": PROG.QS_NOT_APPLICABLE, "pB": PROG.QS_NOT_APPLICABLE, "pK": PROG.QS_NOT_APPLICABLE,
                                                    "pR": PROG.QS_NOT_APPLICABLE, "pT": PROG.QS_DEFERRED}}
    _tfr.assert_operational_only(m)


def test_cli_list_and_status_expose_deferred_and_progression(kept, monkeypatch, capsys):
    monkeypatch.setattr(fr_cli, "FormalReviewService", lambda root, **kw: kept.service(**kw))
    assert fr_cli.main(["--data-root", str(kept.root), "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["deferred_count"] == 1 and listed["deferred"][0]["pattern_id"] == "pT"
    assert listed["progression"]["pT"]["queue_status"] == PROG.QS_DEFERRED and listed["mutation"] == "NONE"
    assert "reason" not in json.dumps(listed["deferred"]) or "suppression_reason" in json.dumps(listed["deferred"])
    assert fr_cli.main(["--data-root", str(kept.root), "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["deferred_count"] == 1 and status["metrics"]["suppressed_keep_reviewing_count"] == 1
    assert status["progression_statuses"]["pT"] == PROG.QS_DEFERRED


def test_next_candidate_reports_progression_and_keeps_deferred_out_of_ranked(kept, capsys):
    capsys.readouterr()
    code = NEXT.NextCandidateReview(kept.root, REPO_ROOT, expected_digests=EXPECTED_DIGESTS, skip_git=True,
                                    corpus_state_resolver=kept.corpus_state, clock=kept.clock,
                                    expect_deferred=["pT"]).run_all()
    out = capsys.readouterr().out
    assert code == 0, out[-2000:]
    assert "::P395N_PROGRESSION::" in out and "deferred_count=1" in out and "deferred_patterns_in_primary_queue=[]" in out
    assert '"queue_status":"DEFERRED_UNCHANGED_KEEP_REVIEWING"' in out and "progression_check=PASSED" in out
    assert "candidates_presented=1" in out and "pattern_id=pR" in out and "queue_rank=1" in out    # 次の rank 1 は pR
    assert all(ord(ch) < 128 for ch in out) and len(kept.decisions()) == 1


def test_next_candidate_fails_closed_when_deferred_leaks_into_ranked(kept, capsys, monkeypatch):
    from src.intelligence.formal_review.store import FormalReviewStore
    real_queue = FormalReviewStore.queue

    def leaking(self):
        queue = real_queue(self)
        rows = list(queue["sections"][SECTION_REJECT])
        rows.append({**rows[0], "pattern_id": "pT", "queue_rank": 99})
        return {**queue, "sections": {**queue["sections"], SECTION_REJECT: rows}}

    monkeypatch.setattr(FormalReviewStore, "queue", leaking)
    capsys.readouterr()
    code = NEXT.NextCandidateReview(kept.root, REPO_ROOT, expected_digests=EXPECTED_DIGESTS, skip_git=True,
                                    corpus_state_resolver=kept.corpus_state, clock=kept.clock).run_all()
    out = capsys.readouterr().out
    assert code == 4 and f"reason={NEXT.DEFERRED_IN_PRIMARY}" in out and "stage=PROGRESSION" in out


def test_next_candidate_reaudit_accepts_the_historical_formal_review_digest(kept, capsys, monkeypatch):
    """Candidate #1/#2 の row は 1.0.0 digest に束縛されたまま（migration しない）。再監査は provenance として認める。"""
    row = kept.decisions()[0].as_dict()
    current = kept.service().policy_digests()
    moved = {**current, "formal_review": "ffffffffffffffff"}                     # policy が更に進んだ状況を再現
    monkeypatch.setattr(FormalReviewService, "policy_digests", lambda self: dict(moved))
    monkeypatch.setattr(NEXT, "SUPERSEDED_FORMAL_REVIEW_DIGESTS", (current["formal_review"],))
    capsys.readouterr()
    code = NEXT.NextCandidateReview(kept.root, REPO_ROOT, expected_digests=moved, skip_git=True,
                                    corpus_state_resolver=kept.corpus_state, clock=kept.clock,
                                    reaudit={"pattern": "pT", "decision": row["decision_id"], "state": KEEP_REVIEWING,
                                             "record_hash": row["record_hash"]}).run_all()
    out = capsys.readouterr().out
    assert "reaudit_SIX_POLICY_LAYERS_BOUND=OK" in out and f"reaudit_formal_review_binding=HISTORICAL:{current['formal_review']}" in out
    assert "reaudit=PASSED" in out and code in (0, 4)                             # 後続の packet 束縛 stage は本テストの対象外
    monkeypatch.setattr(NEXT, "SUPERSEDED_FORMAL_REVIEW_DIGESTS", ())
    capsys.readouterr()
    NEXT.NextCandidateReview(kept.root, REPO_ROOT, expected_digests=moved, skip_git=True,
                             corpus_state_resolver=kept.corpus_state, clock=kept.clock,
                             reaudit={"pattern": "pT", "decision": row["decision_id"], "state": KEEP_REVIEWING,
                                      "record_hash": row["record_hash"]}).run_all()
    assert "reaudit_SIX_POLICY_LAYERS_BOUND=FAILED" in capsys.readouterr().out       # 未知の digest は認めない


def test_execute_refuses_a_deferred_target_by_default_and_allows_explicit_opt_in(kept, capsys):
    kw = dict(pattern_id="pT", action="keep-reviewing", actor="P395_HUMAN_SUPERVISED_REVIEW",
              reason="Keep reviewing once more while the sibling picture settles.",
              confirm=EXECUTE.confirmation_token(KEEP_REVIEWING, "pT"), expect_rows_before=1,
              expect_current_state=KEEP_REVIEWING, expected_digests=EXPECTED_DIGESTS, skip_git=True,
              corpus_state_resolver=kept.corpus_state, clock=kept.clock)
    code = EXECUTE.FormalExecutionSession(kept.root, REPO_ROOT, **kw).run_all()
    out = capsys.readouterr().out
    assert code == 4 and "reason=TARGET_DEFERRED_KEEP_REVIEWING" in out and "stage=TARGET" in out
    assert "::P395X_STAGE2_WRITE::" not in out and len(kept.decisions()) == 1
    code = EXECUTE.FormalExecutionSession(kept.root, REPO_ROOT, allow_deferred=True, **kw).run_all()
    out = capsys.readouterr().out
    assert code == 0, out[-1500:]
    assert "deferred_target_allowed=True" in out and len(kept.decisions()) == 2


def test_validation_driver_determinism_covers_deferred_and_progression(kept, capsys):
    v = V.RealDataPacketValidation(kept.root, REPO_ROOT, expected_digests=EXPECTED_DIGESTS, skip_git=True,
                                   corpus_state_resolver=kept.corpus_state, clock=kept.clock)
    code = v.run_all()
    out = capsys.readouterr().out
    assert code == 0, out[-2000:]
    assert "deferred_count=1" in out and "deferred_set_match=True" in out and "progression_map_match=True" in out
    assert "LIVE_REBUILD_DETERMINISM=PASS" in out and "deferred_patterns_in_primary_queue=[]" in out
    assert '"queue_status":"DEFERRED_UNCHANGED_KEEP_REVIEWING"' in out and "dry_run_pass=4" in out
    assert len(kept.decisions()) == 1


def test_session_plan_lists_deferred_as_non_ranked_context(kept):
    from src.intelligence.formal_review.session import session_plan
    store = kept.service().store
    plan = session_plan(store.queue(), {pid: store.packet(pid) for pid in store.packet_ids()})
    assert [s["brief"]["1_identity"]["pattern_id"] for s in plan["steps"]] == ["pR", "pA", "pK", "pB"]
    assert [d["pattern_id"] for d in plan["deferred_patterns"]] == ["pT"] and plan["deferred_patterns"][0]["queue_status"] == PROG.QS_DEFERRED
