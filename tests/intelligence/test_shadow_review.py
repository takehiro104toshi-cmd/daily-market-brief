"""Phase 3.9.3 Shadow Review のオフラインテスト（実データ・network・LLM 不使用）。

config fail-closed / ranking / type diversity / top_n / card / explanation / outcome /
event store（append-only + hash chain）/ derived state / material change / cooldown /
境界（Decision も DNA も書かない）/ CLI。合成 evaluation record と合成 research artifact のみを使う。
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.evaluation.config import (
    A_CONSISTENCY,
    A_CROSS,
    A_NOVELTY,
    A_QUALITY,
    A_STRENGTH,
    A_TIME,
    AXES,
    load_policies,
)
from src.intelligence.evaluation.models import (
    APPROVE_RECOMMENDED,
    KEEP_REVIEWING,
    NOT_READY,
    REJECT_RECOMMENDED,
    REVIEW_RECOMMENDED,
)
from src.intelligence.evaluation.rules import R_APPROVE, R_KEEP, R_REJECT, R_REVIEW
from src.intelligence.evaluation.store import EvaluationStore, evaluation_root
from src.intelligence.shadow_review import cli as sr_cli
from src.intelligence.shadow_review.config import (
    AGREE,
    DISAGREE,
    DUPLICATE_OR_OVERLAPPING,
    NEEDS_MORE_EVIDENCE,
    NOT_ACTIONABLE,
    OUTCOMES,
    RESERVED_DECISION_STATES,
    SECTION_ADVERSE_OVERFLOW,
    SECTION_MAIN,
    UNCLEAR,
    ShadowReviewPolicy,
    ShadowReviewPolicyError,
    load_shadow_review_policy,
    shadow_review_policy_from_mapping,
)
from src.intelligence.shadow_review.cooldown import effective_cooldown_days
from src.intelligence.shadow_review.diversity import round_robin
from src.intelligence.shadow_review.events import (
    ShadowReviewEventStore,
    ShadowReviewStoreCorrupt,
    shadow_review_root,
)
from src.intelligence.shadow_review.explain import ExplanationTemplateMissing, explain
from src.intelligence.shadow_review.material import material_digest
from src.intelligence.shadow_review.models import (
    ShadowReviewValidationError,
    find_forbidden_keys,
    shadow_review_id_for,
)
from src.intelligence.shadow_review.queue import (
    CURRENT_REVIEWS_FILE,
    QUEUE_FILE,
    SUMMARY_FILE,
    ShadowReviewQueueBuilder,
)
from src.intelligence.shadow_review.ranking import shadow_ordering_key
from src.intelligence.shadow_review.state import derive_current_reviews

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "src" / "intelligence" / "shadow_review"
NOW = datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc)
EVAL_POLICY, REC_POLICY = load_policies()
POLICY = load_shadow_review_policy()

SCORED = (A_STRENGTH, A_TIME, A_CROSS, A_CONSISTENCY, A_NOVELTY)


# ------------------------------------------------------------------ helpers
def evaluation(pattern_id: str, *, pattern_type: str = "STATE_OUTLOOK",
               recommendation: str = REVIEW_RECOMMENDED, triggered_rule: str = R_REVIEW,
               states=None, applicability=None, score=50.0, comparable=True,
               support: int = 3, span: int = 40, months: int = 2, cells: int = 2,
               confirmed_cells: int = 1, dna_conflicts: int = 0, contradiction: bool = False,
               contradiction_repeated: bool = False, narrow: bool = False,
               classification: str = "PARTIALLY_EXPLAINED", share=None,
               docs=("d1", "d2", "d3"), blocking=(), supporting=(),
               eval_digest: str = "", rec_digest: str = "") -> dict:
    """validate_record を通る合成 EvaluationRecord row。"""
    states = dict(states or {a: "MEDIUM" for a in AXES})
    applicability = dict(applicability or {a: "APPLICABLE" for a in AXES})
    applicable_scored = [a for a in SCORED if applicability.get(a) == "APPLICABLE"]
    weight_sum = sum(int(EVAL_POLICY.weights[a]) for a in applicable_scored)
    return {
        "evaluation_id": "cev_" + pattern_id.ljust(16, "0")[:16],
        "pattern_id": pattern_id, "pattern_type": pattern_type, "pattern_version": "1.0.0",
        "evaluated_at": NOW.isoformat(),
        "axis_states": states, "axis_applicability": applicability,
        "axis_metrics": {
            A_STRENGTH: {"eligible_support": support, "support_ranked": True},
            A_TIME: {"span_days": span, "distinct_calendar_months": months},
            A_CROSS: {"distinct_2d_cells": cells, "confirmed_2d_cells": confirmed_cells,
                      "documents_excluded_unknown": 0, "documents_counted": support},
            A_CONSISTENCY: {"identity_direction": "UP", "direction_class": "DIRECTIONAL",
                            "narrow_sibling_contradiction": narrow, "narrow_sibling_repeated": narrow,
                            "contradiction": contradiction,
                            "contradiction_repeated": contradiction_repeated,
                            "dna_conflicts": dna_conflicts, "eligible_support": support},
            A_NOVELTY: {"classification": classification, "evidence_overlap": 1,
                        "target_match": True, "direction_relation": "SAME",
                        "candidate_rule_count": 1, "has_evidence_categories": True, "has_target": True},
            A_QUALITY: {"declared_supporting_documents": len(docs),
                        "resolved_supporting_documents": len(docs),
                        "document_qualities": {"VALID": len(docs)}, "valid_ratio": "1",
                        "support_count": support, "eligible_support": support,
                        "distinct_analysis_versions": 1, "market_alignment_absent_by_design": True},
        },
        "axis_reasons": {a: "" for a in AXES},
        "reference_score": score if comparable else None,
        "reference_score_comparable": comparable,
        "applicable_axes": applicable_scored, "applicable_weight_sum": weight_sum,
        "recommendation": recommendation, "triggered_rule": triggered_rule,
        "blocking_rules": list(blocking), "supporting_rules": list(supporting),
        "evaluation_policy_version": EVAL_POLICY.policy_version,
        "evaluation_policy_digest": eval_digest or EVAL_POLICY.digest(),
        "recommendation_policy_version": REC_POLICY.policy_version,
        "recommendation_policy_digest": rec_digest or REC_POLICY.digest(),
        "shadow_mode": True, "formal_review_gate_reached": False,
        "corpus_size": 55, "corpus_milestone": "CORPUS_50",
        "inputs_digest": "deadbeefdeadbeef",
        "confirmation_3d": {"distinct_3d_cells": cells, "confirmed_3d_cells": confirmed_cells,
                            "documents_counted": support, "role": "SECONDARY_CONFIRMATION_ONLY"},
        "relative_support_share": share,
        "relative_support_applicability": "APPLICABLE" if share is not None else "NOT_APPLICABLE",
        "reopen_signal": None, "approved_adverse_signal": None, "decision_state": "",
        "limitations": ["NOT_PREDICTIVE: evaluation measures analytical reconstruction, "
                        "not forecasting accuracy"],
        "schema_version": "1.0.0",
    }


class Lab:
    """合成 data root（Phase 3.8 research + Phase 3.9.2 evaluation + Shadow Review）。"""

    def __init__(self, tmp_path: Path, rows=(), lifecycles=None, dates=None, clock=None):
        self.root = tmp_path
        self.research = tmp_path / "compass_research"
        self.research.mkdir(parents=True, exist_ok=True)
        self.evaluations = EvaluationStore(evaluation_root(tmp_path))
        self.events = ShadowReviewEventStore(shadow_review_root(tmp_path))
        self.rows = list(rows)
        self.lifecycles = dict(lifecycles or {})
        self.dates = dict(dates or {})
        self.clock = clock or (lambda: NOW)
        self.write()

    def write(self):
        root = self.evaluations.root
        root.mkdir(parents=True, exist_ok=True)
        self.evaluations.path.write_text(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                    for r in sorted(self.rows, key=lambda r: r["pattern_id"])), encoding="utf-8")
        patterns = []
        for row in self.rows:
            pid = row["pattern_id"]
            patterns.append({"pattern_id": pid, "pattern_version": "1.0.0",
                             "status": self.lifecycles.get(pid, "NEW_PATTERN_CANDIDATE"),
                             "supporting_document_ids": ["d1", "d2", "d3"],
                             "components": {"pattern_type": row["pattern_type"],
                                            "evidence": ["EV_A"], "outlook": ["target=TOPIX", "dir=UP"]}})
        (self.research / "patterns.jsonl").write_text(
            "".join(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n" for p in patterns),
            encoding="utf-8")
        dates = self.dates or {"d1": "2026-07-01", "d2": "2026-07-20", "d3": "2026-08-10"}
        (self.research / "structures.jsonl").write_text(
            "".join(json.dumps({"document_id": d, "document_date": v, "eligible": True,
                                "created_at": "2026-08-10T00:00:00+00:00"},
                               ensure_ascii=False, sort_keys=True) + "\n" for d, v in dates.items()),
            encoding="utf-8")

    def builder(self, policy=None, corpus=None, clock=None) -> ShadowReviewQueueBuilder:
        return ShadowReviewQueueBuilder(
            self.research, self.evaluations, self.events, policy or POLICY, EVAL_POLICY, REC_POLICY,
            corpus_state=corpus or {"eligible": 55, "milestone": "CORPUS_50"},
            clock=clock or self.clock)

    def build(self, **kwargs):
        return self.builder(**kwargs).build()

    def event_payload(self, pattern_id: str, outcome: str, *, reason: str = "",
                      missing=(), related: str = "", reviewed_at=None, policy=None,
                      material: str = "", section: str = SECTION_MAIN, rank: int = 1) -> dict:
        policy = policy or POLICY
        row = next(r for r in self.rows if r["pattern_id"] == pattern_id)
        payload = {
            "pattern_id": pattern_id,
            "reviewed_at": (reviewed_at or NOW).isoformat(),
            "reviewer_id": policy.default_reviewer_id, "reviewer_type": "HUMAN",
            "review_outcome": outcome, "reason": reason,
            "structured_reason": {"missing": list(missing)} if missing else {},
            "related_pattern_id": related,
            "recommendation_at_review": row["recommendation"],
            "axis_states_at_review": row["axis_states"],
            "axis_applicability_at_review": row["axis_applicability"],
            "reference_score_at_review": row["reference_score"],
            "queue_rank_at_review": rank, "queue_section_at_review": section,
            "material_digest_at_review": material or material_digest(
                row, self.lifecycles.get(pattern_id, "NEW_PATTERN_CANDIDATE"), policy),
            "evaluation_id": row["evaluation_id"], "inputs_digest": row["inputs_digest"],
            "lifecycle_at_review": self.lifecycles.get(pattern_id, "NEW_PATTERN_CANDIDATE"),
            "evaluation_policy_version": EVAL_POLICY.policy_version,
            "evaluation_policy_digest": EVAL_POLICY.digest(),
            "recommendation_policy_version": REC_POLICY.policy_version,
            "recommendation_policy_digest": REC_POLICY.digest(),
            "shadow_review_policy_version": policy.policy_version,
            "shadow_review_policy_digest": policy.digest(),
            "corpus_size": 55, "corpus_milestone": "CORPUS_50",
            "shadow_mode": True, "formal_review_gate_reached": False,
            "schema_version": "1.0.0", "sequence": 0, "previous_record_hash": "", "record_hash": "",
        }
        payload["shadow_review_id"] = shadow_review_id_for(payload)
        return payload

    def record(self, pattern_id: str, outcome: str, **kwargs):
        return self.events.append(self.event_payload(pattern_id, outcome, **kwargs), POLICY)


def review_rows(n: int, pattern_type: str, prefix: str = "p", **kwargs):
    return [evaluation(f"{prefix}_{pattern_type}_{i}", pattern_type=pattern_type, **kwargs)
            for i in range(n)]


def reject_row(pattern_id: str, pattern_type: str = "EVIDENCE_WHY", **kwargs):
    states = {a: "MEDIUM" for a in AXES}
    states[A_CONSISTENCY] = "LOW"
    states[A_STRENGTH] = "HIGH"
    return evaluation(pattern_id, pattern_type=pattern_type, recommendation=REJECT_RECOMMENDED,
                      triggered_rule=R_REJECT, states=states, contradiction=True,
                      contradiction_repeated=True, **kwargs)


def approve_row(pattern_id: str, pattern_type: str = "STATE_OUTLOOK", **kwargs):
    return evaluation(pattern_id, pattern_type=pattern_type, recommendation=APPROVE_RECOMMENDED,
                      triggered_rule=R_APPROVE, states={a: "HIGH" for a in AXES},
                      supporting=("DATA_QUALITY_HIGH",), **kwargs)


# =================================================================== A. config
def test_policy_digest_is_deterministic_and_config_matches_code_default():
    assert load_shadow_review_policy().digest() == ShadowReviewPolicy().digest()
    assert ShadowReviewPolicy().digest() == ShadowReviewPolicy().digest()
    assert len(ShadowReviewPolicy().digest()) == 16
    assert POLICY.top_n == 8 and POLICY.watch_n == 0 and POLICY.default_reviewer_id == "SUPERVISOR"


def test_policy_rejects_auto_decision_write_and_auto_promotion():
    for key in ("auto_decision_write", "auto_promotion"):
        with pytest.raises(ShadowReviewPolicyError):
            shadow_review_policy_from_mapping({key: True})


def test_policy_rejects_system_reviewer_and_vocabulary_collisions():
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"allowed_reviewer_types": ["HUMAN", "SYSTEM"]})
    for banned in ("APPROVED", "REJECTED", "KEEP_REVIEWING", "OPEN"):
        with pytest.raises(ShadowReviewPolicyError):
            shadow_review_policy_from_mapping({"review_outcomes": list(OUTCOMES[:-1]) + [banned]})


def test_policy_rejects_reference_score_as_material_field_and_bad_state_priority():
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"material_change_fields": ["recommendation", "reference_score"]})
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"material_change_excluded": ["span_days"]})
    for banned in ("NOT_READY", "KEEP_REVIEWING"):
        with pytest.raises(ShadowReviewPolicyError):
            shadow_review_policy_from_mapping({"state_priority": ["REJECT_RECOMMENDED", banned]})


def test_policy_rejects_unknown_vocabulary_and_bad_numbers():
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"top_n": 0})
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"state_priority": ["NOT_A_STATE"]})
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"type_diversity": {"type_order": ["NOT_A_TYPE"]}})
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"cooldowns": {**dict(ShadowReviewPolicy().cooldowns),
                                                         "NOT_AN_OUTCOME": 5}})
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"reason_requirements": {**dict(ShadowReviewPolicy().reason_requirements),
                                                                   AGREE: "SOMETIMES"}})
    with pytest.raises(ShadowReviewPolicyError):
        shadow_review_policy_from_mapping({"ranking_order": ["reference_score", "high_axis_count"]})


def test_same_version_changed_content_is_detected_by_digest(tmp_path):
    """同一 policy_version で内容が変われば digest が変わり、build が fail closed で拒否する。"""
    lab = Lab(tmp_path, rows=review_rows(1, "STATE_OUTLOOK"))
    drifted = shadow_review_policy_from_mapping({"policy_version": "1.0.0", "top_n": 5})
    assert drifted.policy_version == POLICY.policy_version
    assert drifted.digest() != POLICY.digest()
    lab.record("p_STATE_OUTLOOK_0", AGREE)
    with pytest.raises(ShadowReviewPolicyError):
        lab.builder(policy=drifted).build()


def test_reserved_decision_vocabulary_matches_the_real_decision_policy():
    """decision package を production では import しないので、写した語彙が drift していないか test で守る。"""
    from src.intelligence.decision import policy as decision_policy

    actual = {decision_policy.KEEP_REVIEWING, decision_policy.APPROVED, decision_policy.REJECTED,
              decision_policy.REOPENED_FOR_REVIEW, decision_policy.SUPERSEDED, decision_policy.RETIRED}
    assert actual == set(RESERVED_DECISION_STATES)


# =================================================================== B. ranking
def test_high_axis_count_dominates_reference_score():
    many_high = evaluation("a", states={**{a: "MEDIUM" for a in AXES}, A_STRENGTH: "HIGH", A_TIME: "HIGH"},
                           score=10.0)
    high_score = evaluation("b", states={a: "MEDIUM" for a in AXES}, score=99.0)
    assert sorted([high_score, many_high], key=lambda r: shadow_ordering_key(r, EVAL_POLICY))[0] is many_high


def test_reference_score_breaks_ties_only_within_equal_high_count():
    low = evaluation("a", score=40.0)
    high = evaluation("b", score=90.0)
    assert [r["pattern_id"] for r in sorted([low, high], key=lambda r: shadow_ordering_key(r, EVAL_POLICY))] \
        == ["b", "a"]


def test_support_then_span_then_pattern_id_break_remaining_ties():
    base = dict(score=50.0, share=None)
    few = evaluation("a", support=2, **base)
    many = evaluation("b", support=9, **base)
    assert sorted([few, many], key=lambda r: shadow_ordering_key(r, EVAL_POLICY))[0] is many
    short = evaluation("a", support=3, span=10, **base)
    long_ = evaluation("b", support=3, span=90, **base)
    assert sorted([short, long_], key=lambda r: shadow_ordering_key(r, EVAL_POLICY))[0] is long_
    twin_b = evaluation("b", **base)
    twin_a = evaluation("a", **base)
    assert [r["pattern_id"] for r in sorted([twin_b, twin_a],
                                            key=lambda r: shadow_ordering_key(r, EVAL_POLICY))] == ["a", "b"]


def test_not_comparable_score_sorts_last_without_crashing():
    comparable = evaluation("a", score=1.0, comparable=True)
    incomparable = evaluation("b", score=None, comparable=False)
    ordered = sorted([incomparable, comparable], key=lambda r: shadow_ordering_key(r, EVAL_POLICY))
    assert [r["pattern_id"] for r in ordered] == ["a", "b"]


# =================================================================== C. diversity
def test_review_round_robin_spreads_types_and_respects_type_order():
    rows = (review_rows(6, "EVIDENCE_WHY") + review_rows(6, "EVIDENCE_RISK")
            + review_rows(1, "EVIDENCE_OUTLOOK") + review_rows(6, "STATE_OUTLOOK"))
    picked = round_robin(rows, 6, POLICY, lambda r: shadow_ordering_key(r, EVAL_POLICY))
    types = [r["pattern_type"] for r in picked]
    assert len(picked) == 6
    assert set(types) == {"EVIDENCE_WHY", "EVIDENCE_RISK", "EVIDENCE_OUTLOOK", "STATE_OUTLOOK"}
    assert max(types.count(t) for t in set(types)) <= 2                    # 1 型が独占しない
    # 全件同質なので、型の訪問順は config の type_order がそのまま決める
    assert types[:4] == ["EVIDENCE_OUTLOOK", "STATE_OUTLOOK", "EVIDENCE_WHY", "EVIDENCE_RISK"]


def test_type_order_only_breaks_ties_and_quality_wins_first():
    """質が違えば type_order より ranking が優先される（type_order は同質時の決定化だけ）。"""
    strong_risk = evaluation("z_risk", pattern_type="EVIDENCE_RISK",
                             states={**{a: "MEDIUM" for a in AXES}, A_STRENGTH: "HIGH", A_TIME: "HIGH"})
    weak_outlook = evaluation("a_outlook", pattern_type="EVIDENCE_OUTLOOK")
    picked = round_robin([weak_outlook, strong_risk], 2, POLICY,
                         lambda r: shadow_ordering_key(r, EVAL_POLICY))
    assert [r["pattern_type"] for r in picked] == ["EVIDENCE_RISK", "EVIDENCE_OUTLOOK"]


def test_round_robin_is_deterministic_and_respects_hard_caps():
    rows = review_rows(10, "EVIDENCE_WHY")
    key = lambda r: shadow_ordering_key(r, EVAL_POLICY)                    # noqa: E731
    first = [r["pattern_id"] for r in round_robin(rows, 8, POLICY, key)]
    second = [r["pattern_id"] for r in round_robin(list(reversed(rows)), 8, POLICY, key)]
    assert first == second
    assert len(first) == POLICY.type_cap("EVIDENCE_WHY") == 3              # cap が backstop として効く


def test_reject_and_approve_bypass_diversity_entirely(tmp_path):
    rows = ([reject_row(f"r{i}", "EVIDENCE_WHY") for i in range(3)]
            + [approve_row(f"a{i}", "STATE_OUTLOOK") for i in range(2)]
            + review_rows(6, "EVIDENCE_RISK"))
    report, queue, _s, _c = Lab(tmp_path, rows=rows).build()
    main = queue["main"]
    assert [c["recommendation"] for c in main[:5]] == [REJECT_RECOMMENDED] * 3 + [APPROVE_RECOMMENDED] * 2
    assert [c["pattern_type"] for c in main[:3]] == ["EVIDENCE_WHY"] * 3   # 型 cap 3 を bypass して全件先頭
    assert report.main_queue_count == 8


def test_no_escalated_item_is_silently_lost(tmp_path):
    rows = ([reject_row("r0")] + review_rows(12, "STATE_OUTLOOK") + review_rows(4, "EVIDENCE_RISK"))
    report, queue, summary, _c = Lab(tmp_path, rows=rows).build()
    accounted = report.main_queue_count + report.adverse_overflow_count + report.backlog_count
    assert accounted == report.escalated_count == 17
    assert sum(queue["backlog"]["by_recommendation"].values()) == report.backlog_count
    assert summary["escalated"] == 17


# =================================================================== D. top_n / sections
def test_top_n_is_eight_with_backlog_and_empty_watch(tmp_path):
    rows = ([reject_row("r0"), reject_row("r1", "EVIDENCE_RISK")]
            + review_rows(1, "EVIDENCE_OUTLOOK") + review_rows(6, "STATE_OUTLOOK")
            + review_rows(6, "THEME_OUTLOOK") + review_rows(3, "EVIDENCE_WHY")
            + review_rows(4, "EVIDENCE_RISK")
            + [evaluation(f"k{i}", recommendation=KEEP_REVIEWING, triggered_rule=R_KEEP)
               for i in range(20)])
    report, queue, summary, _c = Lab(tmp_path, rows=rows).build()
    assert report.main_queue_count == 8
    assert report.adverse_overflow_count == 0
    assert report.backlog_count == 14                                      # 22 escalated - 8
    assert report.watch_count == 0 and queue["watch"] == []
    assert [c["recommendation"] for c in queue["main"][:2]] == [REJECT_RECOMMENDED] * 2
    review_types = [c["pattern_type"] for c in queue["main"][2:]]
    assert set(review_types) == {"EVIDENCE_OUTLOOK", "STATE_OUTLOOK", "THEME_OUTLOOK",
                                 "EVIDENCE_WHY", "EVIDENCE_RISK"}          # 全 REVIEW 型を 1 件以上
    assert KEEP_REVIEWING not in summary["by_recommendation"]              # main pool に入らない


def test_reject_beyond_top_n_goes_to_adverse_overflow_not_hidden(tmp_path):
    rows = [reject_row(f"r{i}") for i in range(11)] + review_rows(2, "STATE_OUTLOOK")
    report, queue, summary, _c = Lab(tmp_path, rows=rows).build()
    assert report.main_queue_count == 8 and report.adverse_overflow_count == 3
    assert summary["calibration_metrics"]["adverse_overflow_count"] == 3
    assert all(c["queue_section"] == SECTION_ADVERSE_OVERFLOW for c in queue["adverse_overflow"])
    assert report.main_queue_count + report.adverse_overflow_count + report.backlog_count == 13


def test_watch_section_stays_separate_when_enabled(tmp_path):
    keep = [evaluation(f"k{i}", recommendation=KEEP_REVIEWING, triggered_rule=R_KEEP) for i in range(4)]
    rows = review_rows(2, "STATE_OUTLOOK") + keep
    lifecycles = {"k0": "OBSERVED", "k1": "NEW_PATTERN_CANDIDATE",
                  "k2": "REVIEW_CANDIDATE", "k3": "NEW_PATTERN_CANDIDATE"}
    lab = Lab(tmp_path, rows=rows, lifecycles=lifecycles)
    enabled = shadow_review_policy_from_mapping({"policy_version": "1.1.0", "watch_n": 2})
    report, queue, _s, _c = lab.builder(policy=enabled).build()
    assert report.watch_count == 2
    assert {c["pattern_id"] for c in queue["watch"]} <= {"k1", "k2", "k3"}   # OBSERVED は除外
    assert all(c["recommendation"] == KEEP_REVIEWING for c in queue["watch"])
    assert report.main_queue_count == 2                                     # watch は top_n を消費しない
    assert not ({c["pattern_id"] for c in queue["main"]} & {c["pattern_id"] for c in queue["watch"]})


def test_not_ready_never_enters_the_queue(tmp_path):
    rows = review_rows(2, "STATE_OUTLOOK") + [
        evaluation("nr", recommendation=NOT_READY, triggered_rule="NOT_READY:DATA_QUALITY_LOW",
                   states={**{a: "MEDIUM" for a in AXES}, A_QUALITY: "LOW"})]
    report, queue, _s, _c = Lab(tmp_path, rows=rows).build()
    ids = {c["pattern_id"] for c in queue["main"]} | {i["pattern_id"] for i in queue["backlog"]["items"]}
    assert "nr" not in ids and report.escalated_count == 2


# =================================================================== E. cards
def test_card_contains_required_fields_and_only_iso_dates(tmp_path):
    lab = Lab(tmp_path, rows=[reject_row("r0")], dates={"d1": "2026-07-01", "d2": "2026-08-10"})
    _r, queue, _s, _c = lab.build()
    card = queue["main"][0]
    for field_name in ("queue_rank", "queue_section", "pattern_id", "pattern_type", "lifecycle_status",
                       "recommendation", "why_surfaced", "axes", "reference_score",
                       "reference_score_comparable", "evidence", "relations", "rules", "governance",
                       "history", "supporting_document_dates", "material_digest", "limitations"):
        assert field_name in card, field_name
    assert set(card["axes"]) == set(AXES)
    assert all({"state", "applicability", "reason"} == set(v) for v in card["axes"].values())
    assert card["supporting_document_dates"] == ["2026-07-01", "2026-08-10"]
    assert card["governance"]["formal_review_min_corpus"] == 100
    assert card["governance"]["shadow_mode"] is True
    for key in ("eligible_support", "span_days", "distinct_calendar_months",
                "distinct_2d_cells", "confirmed_2d_cells"):
        assert key in card["evidence"]
    assert card["rules"]["triggered_rule"] == R_REJECT


def test_not_comparable_score_is_null_on_the_card(tmp_path):
    row = evaluation("x", score=None, comparable=False,
                     applicability={**{a: "APPLICABLE" for a in AXES}, A_CROSS: "NOT_APPLICABLE",
                                    A_STRENGTH: "NOT_APPLICABLE", A_NOVELTY: "NOT_APPLICABLE"})
    _r, queue, _s, _c = Lab(tmp_path, rows=[row]).build()
    card = queue["main"][0]
    assert card["reference_score"] is None and card["reference_score_comparable"] is False


def test_forbidden_keys_are_rejected_recursively(tmp_path):
    assert find_forbidden_keys({"a": {"b": [{"page_text": "x"}]}}) == ["page_text"]
    assert find_forbidden_keys({"a": [[{"deep": {"file_path": "c:/x"}}]]}) == ["file_path"]
    assert find_forbidden_keys({"pattern_id": "p", "reason": "ok", "eligible_support": 3}) == []
    lab = Lab(tmp_path, rows=[reject_row("r0")])
    _r, queue, summary, current = lab.build()
    for doc in (queue, summary, current):
        assert find_forbidden_keys(doc) == []


def test_queue_never_contains_paths_or_source_text(tmp_path):
    lab = Lab(tmp_path, rows=[reject_row("r0")] + review_rows(2, "STATE_OUTLOOK"))
    _r, queue, _s, _c = lab.build()
    blob = json.dumps(queue, ensure_ascii=False)
    assert str(tmp_path) not in blob
    assert ".pdf" not in blob.lower() and "compass_research" not in blob


# =================================================================== F. explanation
def test_explanation_templates_are_deterministic_per_state():
    reject = explain(reject_row("r0"), "REVIEW_CANDIDATE", True, 55, 100)
    assert "反復する矛盾" in reject and "否定レビュー" in reject
    approve = explain(approve_row("a0"), "REVIEW_CANDIDATE", True, 55, 100)
    assert "SHADOW_ONLY" in approve and "承認ではありません" in approve
    review = explain(evaluation("v", blocking=("CROSS_REGIME_NOT_HIGH",)), "", True, 55, 100)
    assert "市場レジーム" in review and "目視確認" in review
    watch = explain(evaluation("k", recommendation=KEEP_REVIEWING, triggered_rule=R_KEEP),
                    "NEW_PATTERN_CANDIDATE", True, 55, 100)
    assert "経過観察" in watch


def test_unknown_triggered_rule_fails_loud():
    with pytest.raises(ExplanationTemplateMissing) as exc:
        explain(evaluation("x", triggered_rule="REVIEW:SOMETHING_NEW"))
    assert exc.value.code == "EXPLANATION_TEMPLATE_MISSING"


def test_explanation_quotes_no_source_text():
    text = explain(reject_row("r0"), "REVIEW_CANDIDATE", True, 55, 100)
    assert "EV_A" not in text and "TOPIX" not in text


# =================================================================== G. outcomes / reasons
def test_outcome_enum_is_exact_and_disjoint_from_decision_vocabulary():
    assert OUTCOMES == ("AGREE", "DISAGREE", "NEEDS_MORE_EVIDENCE", "UNCLEAR",
                        "DUPLICATE_OR_OVERLAPPING", "NOT_ACTIONABLE")
    assert not set(OUTCOMES) & set(RESERVED_DECISION_STATES)
    for banned in ("APPROVED", "REJECTED", "KEEP_REVIEWING", "OPEN", "DEFERRED", "SKIP"):
        assert banned not in OUTCOMES


def test_reason_requirements_are_enforced_on_write(tmp_path):
    lab = Lab(tmp_path, rows=[reject_row("r0"), review_rows(1, "STATE_OUTLOOK")[0]])
    assert lab.record("r0", AGREE)["appended"] is True                     # note 任意
    with pytest.raises(ShadowReviewValidationError) as exc:
        lab.record("r0", DISAGREE, reason="短い")
    assert "REASON_REQUIRED" in exc.value.errors
    assert lab.record("r0", DISAGREE, reason="矛盾は別要因で説明できるため反対")["appended"] is True
    with pytest.raises(ShadowReviewValidationError):
        lab.record("r0", UNCLEAR, reason="?")
    with pytest.raises(ShadowReviewValidationError):
        lab.record("r0", NOT_ACTIONABLE, reason="no")


def test_needs_more_evidence_requires_structured_category(tmp_path):
    lab = Lab(tmp_path, rows=[review_rows(1, "STATE_OUTLOOK")[0]])
    pid = "p_STATE_OUTLOOK_0"
    with pytest.raises(ShadowReviewValidationError) as exc:
        lab.record(pid, NEEDS_MORE_EVIDENCE, reason="証拠が足りないと考える")
    assert "STRUCTURED_REASON_REQUIRED" in exc.value.errors
    with pytest.raises(ShadowReviewValidationError):
        lab.record(pid, NEEDS_MORE_EVIDENCE, missing=("MORE_COFFEE",))
    assert lab.record(pid, NEEDS_MORE_EVIDENCE, missing=("MORE_DOCUMENTS", "LONGER_SPAN"))["appended"]


def test_duplicate_outcome_requires_a_different_related_pattern(tmp_path):
    lab = Lab(tmp_path, rows=review_rows(2, "STATE_OUTLOOK"))
    pid, other = "p_STATE_OUTLOOK_0", "p_STATE_OUTLOOK_1"
    with pytest.raises(ShadowReviewValidationError) as exc:
        lab.record(pid, DUPLICATE_OR_OVERLAPPING, reason="同じ内容に見えるため重複")
    assert "RELATED_PATTERN_ID_REQUIRED" in exc.value.errors
    with pytest.raises(ShadowReviewValidationError) as exc:
        lab.record(pid, DUPLICATE_OR_OVERLAPPING, reason="同じ内容に見えるため重複", related=pid)
    assert "RELATED_PATTERN_ID_MUST_DIFFER" in exc.value.errors
    assert lab.record(pid, DUPLICATE_OR_OVERLAPPING, reason="同じ内容に見えるため重複",
                      related=other)["appended"]


def test_system_reviewer_is_rejected(tmp_path):
    lab = Lab(tmp_path, rows=[reject_row("r0")])
    payload = lab.event_payload("r0", AGREE)
    payload["reviewer_type"] = "SYSTEM"
    payload["shadow_review_id"] = shadow_review_id_for(payload)
    with pytest.raises(ShadowReviewValidationError) as exc:
        lab.events.append(payload, POLICY)
    assert "REVIEWER_TYPE_MUST_BE_HUMAN" in exc.value.errors


# =================================================================== H. event store
def test_events_are_append_only_with_sequence_and_hash_chain(tmp_path):
    lab = Lab(tmp_path, rows=review_rows(3, "STATE_OUTLOOK"))
    for i in range(3):
        lab.record(f"p_STATE_OUTLOOK_{i}", AGREE)
    records = lab.events.records()
    assert [r.sequence for r in records] == [1, 2, 3]
    assert records[0].previous_record_hash == ""
    assert records[1].previous_record_hash == records[0].record_hash
    assert records[2].previous_record_hash == records[1].record_hash
    assert lab.events.validate()["events"] == 3
    lab.record("p_STATE_OUTLOOK_0", UNCLEAR, reason="カードの情報では判断できない")
    assert [r.sequence for r in lab.events.records()] == [1, 2, 3, 4]      # 過去行は不変


def test_identical_retry_is_idempotent_and_conflicting_duplicate_fails(tmp_path):
    lab = Lab(tmp_path, rows=[reject_row("r0")])
    payload = lab.event_payload("r0", AGREE)
    assert lab.events.append(payload, POLICY)["appended"] is True
    again = lab.events.append(dict(payload), POLICY)
    assert again["appended"] is False and again["reason"] == "DUPLICATE_EVENT_IDEMPOTENT"
    assert len(lab.events.records()) == 1
    conflicting = dict(payload)
    conflicting["queue_rank_at_review"] = 99                                # 同じ id・違う内容
    with pytest.raises(ShadowReviewValidationError) as exc:
        lab.events.append(conflicting, POLICY)
    assert any(e.startswith("CONFLICTING_DUPLICATE") for e in exc.value.errors)


def test_corrupted_chain_and_sequence_gap_are_detected(tmp_path):
    lab = Lab(tmp_path, rows=review_rows(2, "STATE_OUTLOOK"))
    lab.record("p_STATE_OUTLOOK_0", AGREE)
    lab.record("p_STATE_OUTLOOK_1", AGREE)
    lines = lab.events.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["previous_record_hash"] = "0" * 64
    lab.events.path.write_text(lines[0] + "\n" + json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8")
    store = ShadowReviewEventStore(shadow_review_root(tmp_path))
    with pytest.raises(ShadowReviewStoreCorrupt) as exc:
        store.records()
    assert exc.value.code in ("CHAIN_BROKEN", "RECORD_HASH_MISMATCH", "SCHEMA_INVALID")
    gapped = json.loads(lines[1])
    gapped["sequence"] = 5
    lab.events.path.write_text(lines[0] + "\n" + json.dumps(gapped, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ShadowReviewStoreCorrupt):
        ShadowReviewEventStore(shadow_review_root(tmp_path)).records()


def test_event_store_has_no_delete_or_overwrite_api():
    forbidden = {"delete", "remove", "truncate", "rewrite", "replace_all", "update", "clear"}
    assert not (forbidden & set(dir(ShadowReviewEventStore)))


# =================================================================== I. derived state
def test_current_state_tracks_counts_history_and_changes(tmp_path):
    lab = Lab(tmp_path, rows=review_rows(1, "STATE_OUTLOOK"))
    pid = "p_STATE_OUTLOOK_0"
    lab.record(pid, DISAGREE, reason="この推奨には同意できない理由がある")
    lab.record(pid, DISAGREE, reason="二度目も同じ理由で同意できない",
               reviewed_at=NOW + timedelta(days=40))
    derived = derive_current_reviews(lab.events.records(), POLICY, now=NOW + timedelta(days=60))
    state = derived[pid]
    assert state.review_count == 2 and state.disagreement_count == 2
    assert state.last_outcome == DISAGREE
    assert [h["outcome"] for h in state.outcome_history] == [DISAGREE, DISAGREE]
    assert state.eligible_for_requeue is False                             # 時間経過だけでは戻らない
    changed = derive_current_reviews(
        lab.events.records(), POLICY,
        {pid: {"material_digest": "different", "recommendation": REJECT_RECOMMENDED}},
        now=NOW + timedelta(days=60))[pid]
    assert changed.materially_changed_since is True
    assert changed.recommendation_changed_since is True
    assert changed.eligible_for_requeue is True


def test_current_reviews_json_is_rebuildable_from_events(tmp_path):
    lab = Lab(tmp_path, rows=review_rows(2, "STATE_OUTLOOK"))
    lab.record("p_STATE_OUTLOOK_0", AGREE)
    _r1, _q1, _s1, current1 = lab.build()
    (shadow_review_root(tmp_path) / CURRENT_REVIEWS_FILE).unlink()
    _r2, _q2, _s2, current2 = lab.build()
    assert current1["patterns"] == current2["patterns"]
    assert (shadow_review_root(tmp_path) / CURRENT_REVIEWS_FILE).is_file()


# =================================================================== J. material digest
def test_material_digest_reacts_to_included_fields_only():
    base = evaluation("x")
    lifecycle = "NEW_PATTERN_CANDIDATE"
    original = material_digest(base, lifecycle, POLICY)
    assert material_digest(evaluation("x", score=99.0), lifecycle, POLICY) == original   # score だけ
    assert material_digest(evaluation("x", share=0.9), lifecycle, POLICY) == original    # share だけ
    assert material_digest(evaluation("x", span=999), lifecycle, POLICY) == original     # span だけ
    assert material_digest(evaluation("x", confirmed_cells=9), lifecycle, POLICY) == original
    assert material_digest(evaluation("x", support=9), lifecycle, POLICY) != original
    assert material_digest(evaluation("x", cells=9), lifecycle, POLICY) != original
    assert material_digest(evaluation("x", contradiction=True), lifecycle, POLICY) != original
    assert material_digest(evaluation("x", recommendation=REJECT_RECOMMENDED,
                                      triggered_rule=R_REJECT), lifecycle, POLICY) != original
    assert material_digest(base, "REVIEW_CANDIDATE", POLICY) != original
    assert material_digest(evaluation("x", eval_digest="other"), lifecycle, POLICY) != original
    assert material_digest(evaluation("x", rec_digest="other"), lifecycle, POLICY) != original


def test_material_digest_payload_never_contains_score_fields():
    from src.intelligence.shadow_review.material import material_payload

    payload = material_payload(evaluation("x"), "OBSERVED", POLICY)
    for banned in ("reference_score", "relative_support_share", "span_days", "confirmed_3d_cells"):
        assert banned not in payload


# =================================================================== K. cooldown
def test_cooldown_days_per_outcome():
    assert effective_cooldown_days(AGREE, POLICY) == 30
    assert effective_cooldown_days(UNCLEAR, POLICY) == 14
    assert effective_cooldown_days(DUPLICATE_OR_OVERLAPPING, POLICY) == 90
    assert effective_cooldown_days(NOT_ACTIONABLE, POLICY) == 90
    assert effective_cooldown_days(DISAGREE, POLICY) is None               # material change のみ
    assert effective_cooldown_days(NEEDS_MORE_EVIDENCE, POLICY) is None


def test_zero_cooldown_means_material_change_only_not_daily_resurfacing(tmp_path):
    """0 は「cooldown 無し」ではない。時間が経っても戻らないことを固定する。"""
    for outcome, kwargs in ((DISAGREE, {"reason": "この推奨には同意できない理由がある"}),
                            (NEEDS_MORE_EVIDENCE, {"missing": ("MORE_DOCUMENTS",)})):
        lab = Lab(tmp_path / outcome, rows=review_rows(1, "STATE_OUTLOOK"))
        pid = "p_STATE_OUTLOOK_0"
        lab.record(pid, outcome, **kwargs)
        for days in (1, 30, 365):
            report, queue, _s, _c = lab.build(clock=lambda d=days: NOW + timedelta(days=d))
            assert report.main_queue_count == 0, (outcome, days)
            assert queue["backlog"]["items"][0]["deferred_reason"] == "COOLDOWN"


def test_timed_cooldown_expires_and_material_change_bypasses_it(tmp_path):
    lab = Lab(tmp_path, rows=review_rows(1, "STATE_OUTLOOK"))
    pid = "p_STATE_OUTLOOK_0"
    lab.record(pid, AGREE)
    assert lab.build(clock=lambda: NOW + timedelta(days=29))[0].main_queue_count == 0
    assert lab.build(clock=lambda: NOW + timedelta(days=31))[0].main_queue_count == 1
    lab.rows = [evaluation(pid, support=9)]                                # material change
    lab.write()
    assert lab.build(clock=lambda: NOW + timedelta(days=1))[0].main_queue_count == 1


def test_adverse_cooldown_cap_applies_to_reject(tmp_path):
    lab = Lab(tmp_path, rows=[reject_row("r0")])
    lab.record("r0", AGREE)                                                # 通常なら 30 日
    assert lab.build(clock=lambda: NOW + timedelta(days=6))[0].main_queue_count == 0
    assert lab.build(clock=lambda: NOW + timedelta(days=8))[0].main_queue_count == 1
    assert effective_cooldown_days(DISAGREE, POLICY, current_recommendation=REJECT_RECOMMENDED) == 7


# =================================================================== L. boundary safety
def test_shadow_review_never_imports_decision_write_apis():
    write_apis = {"DecisionService", "DecisionRequest"}
    for py in sorted(PKG.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        imported = {a.asname or a.name for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom)) for a in node.names}
        assert not (imported & write_apis), (py.name, imported & write_apis)
        from_decision = {a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                         and "decision" in (node.module or "") for a in node.names}
        if from_decision:
            assert py.name == "cli.py", (py.name, from_decision)
            assert from_decision <= {"corpus_state_from_data_root"}, from_decision


def test_shadow_review_writes_nothing_outside_its_own_root(tmp_path):
    lab = Lab(tmp_path, rows=[reject_row("r0")] + review_rows(2, "STATE_OUTLOOK"))
    research_before = {p.name: p.read_bytes() for p in sorted(lab.research.iterdir())}
    evaluations_before = lab.evaluations.path.read_bytes()
    lab.build()
    lab.record("r0", AGREE)
    lab.build()
    assert {p.name: p.read_bytes() for p in sorted(lab.research.iterdir())} == research_before
    assert lab.evaluations.path.read_bytes() == evaluations_before
    assert not (tmp_path / "compass_decisions").exists()
    assert sorted(p.name for p in shadow_review_root(tmp_path).iterdir()) == [
        CURRENT_REVIEWS_FILE, QUEUE_FILE, "review_events.jsonl", SUMMARY_FILE]


def test_production_dna_and_repository_are_untouched(tmp_path):
    import hashlib

    dna = [REPO_ROOT / "src" / "intelligence" / "compass" / "market_principles.py",
           REPO_ROOT / "knowledge" / "compass_dna" / "market_rules.yaml"]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in dna if p.is_file()]
    lab = Lab(tmp_path, rows=[reject_row("r0")])
    lab.build()
    lab.record("r0", AGREE)
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in dna if p.is_file()] == before


def test_package_declares_no_approval_or_promotion_helpers():
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(PKG.glob("*.py")))
    for banned in ("def approve", "def reject_pattern", "def promote", "PROMOTED_TO_DNA"):
        assert banned not in text, banned


# =================================================================== M. CLI
def test_cli_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    lab = Lab(tmp_path, rows=[reject_row("r0")] + review_rows(2, "STATE_OUTLOOK"))
    _patch_cli(monkeypatch, tmp_path)
    assert sr_cli.main(["build", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mutation"] == "NONE" and payload["dry_run"] is True
    assert payload["main_queue_count"] == 3 and payload["watch_count"] == 0
    assert len(payload["top_n_composition"]) == 3
    for key in ("corpus_size", "corpus_milestone", "shadow_mode", "formal_review_gate_reached",
                "evaluation_policy_digest", "recommendation_policy_digest",
                "shadow_review_policy_digest", "backlog_count", "adverse_overflow_count",
                "by_recommendation", "by_pattern_type", "errors"):
        assert key in payload, key
    assert not shadow_review_root(tmp_path).exists()


def test_cli_build_then_read_only_commands(tmp_path, monkeypatch, capsys):
    lab = Lab(tmp_path, rows=[reject_row("r0")] + review_rows(2, "STATE_OUTLOOK"))
    _patch_cli(monkeypatch, tmp_path)
    assert sr_cli.main(["build"]) == 0
    assert "REPLACE" in json.loads(capsys.readouterr().out)["mutation"]
    root = shadow_review_root(tmp_path)
    fingerprint = {p.name: p.read_bytes() for p in sorted(root.iterdir())}
    for argv in (["summary"], ["list"], ["list", "--section", "BACKLOG"], ["show", "r0"],
                 ["validate-policy"], ["validate-events"]):
        assert sr_cli.main(argv) == 0, argv
        capsys.readouterr()
    assert {p.name: p.read_bytes() for p in sorted(root.iterdir())} == fingerprint
    assert sr_cli.main(["show", "nope"]) == 1
    capsys.readouterr()


def test_cli_record_appends_only_the_event_log(tmp_path, monkeypatch, capsys):
    lab = Lab(tmp_path, rows=[reject_row("r0")] + review_rows(2, "STATE_OUTLOOK"))
    _patch_cli(monkeypatch, tmp_path)
    sr_cli.main(["build"])
    capsys.readouterr()
    root = shadow_review_root(tmp_path)
    derived_before = {name: (root / name).read_bytes() for name in (QUEUE_FILE, SUMMARY_FILE,
                                                                    CURRENT_REVIEWS_FILE)}
    assert sr_cli.main(["record", "--pattern", "r0", "--outcome", "AGREE"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["appended"] is True and payload["mutation"] == "APPEND review_events.jsonl"
    assert payload["shadow_review_id"].startswith("srv_")
    assert {name: (root / name).read_bytes() for name in derived_before} == derived_before
    assert sr_cli.main(["record", "--pattern", "r0", "--outcome", "DISAGREE", "--reason", "短い"]) == 3
    assert json.loads(capsys.readouterr().out)["error"] == "SHADOW_REVIEW_WRITE_REJECTED"
    assert sr_cli.main(["history", "r0"]) == 0
    assert json.loads(capsys.readouterr().out)["review_count"] == 1
    assert sr_cli.main(["record", "--pattern", "ghost", "--outcome", "AGREE"]) == 1
    capsys.readouterr()


def test_cli_has_no_decision_or_promotion_command(tmp_path, monkeypatch, capsys):
    _patch_cli(monkeypatch, tmp_path)
    for argv in (["approve"], ["reject"], ["promote"], ["decide"]):
        with pytest.raises(SystemExit):
            sr_cli.main(argv)
        capsys.readouterr()


def _patch_cli(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(sr_cli, "resolve_root", lambda override="": root)
    monkeypatch.setattr(sr_cli, "corpus_state_for",
                        lambda _root: {"eligible": 55, "milestone": "CORPUS_50", "documents": 55})


# =================================================================== replay determinism
def test_queue_build_is_deterministic_and_replayable(tmp_path):
    rows = ([reject_row("r0"), reject_row("r1", "EVIDENCE_RISK")]
            + review_rows(4, "STATE_OUTLOOK") + review_rows(4, "THEME_OUTLOOK")
            + review_rows(3, "EVIDENCE_WHY"))
    lab = Lab(tmp_path, rows=rows)
    _r1, queue1, summary1, _c1 = lab.build()
    _r2, queue2, summary2, _c2 = lab.build()
    assert [c["pattern_id"] for c in queue1["main"]] == [c["pattern_id"] for c in queue2["main"]]
    assert queue1["backlog"] == queue2["backlog"]
    assert {k: v for k, v in summary1.items() if k != "generated_at"} == \
           {k: v for k, v in summary2.items() if k != "generated_at"}


def test_summary_metrics_are_calibration_only(tmp_path):
    lab = Lab(tmp_path, rows=[reject_row("r0")] + review_rows(2, "STATE_OUTLOOK"))
    lab.record("r0", DISAGREE, reason="この矛盾は別要因で説明できると考える")
    lab.record("p_STATE_OUTLOOK_0", AGREE)
    _r, _q, summary, _c = lab.build()
    metrics = summary["calibration_metrics"]
    for name in ("review_agreement_rate", "human_disagreement_rate",
                 "disagreement_rate_by_recommendation", "disagreement_rate_by_triggered_rule",
                 "disagreement_rate_by_pattern_type", "needs_more_evidence_rate", "unclear_rate",
                 "not_actionable_rate", "duplicate_rate", "re_review_rate",
                 "recommendation_change_after_review", "time_to_first_escalation",
                 "queue_type_distribution", "queue_coverage", "adverse_disagreement_rate",
                 "adverse_overflow_count"):
        assert name in metrics, name
    assert metrics["human_disagreement_rate"] == 0.5
    assert metrics["adverse_disagreement_rate"] == 1.0
    assert metrics["time_to_first_escalation"] == "NOT_AVAILABLE"          # 捏造しない
    for name in metrics:                                                   # 指標名に予測語彙を使わない
        for banned in ("accuracy", "precision", "hit_rate", "forecast"):
            assert banned not in name.lower(), (name, banned)
    assert "NOT_PREDICTIVE" in json.dumps(summary, ensure_ascii=False)
    assert "not prediction accuracy" in summary["metric_note"]
