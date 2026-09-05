"""Phase 3.9.5 First Formal DNA Review — 合成 data root で population / packet / digest / guard / decide / CLI を検証。

すべて temp root。実 CompassData には触れない。formal Decision は temp の decisions.jsonl にだけ書かれる。
"""
from __future__ import annotations

import ast
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.decision.models import ACTOR_HUMAN
from src.intelligence.decision.corpus_state import CorpusState
from src.intelligence.decision.policy import load_decision_policy
from src.intelligence.decision.store import DecisionStore, decisions_root
from src.intelligence.evaluation.config import A_CONSISTENCY, A_CROSS, A_NOVELTY, A_QUALITY, A_STRENGTH, A_TIME, AXES, load_policies
from src.intelligence.evaluation.models import (
    APPROVE_RECOMMENDED,
    KEEP_REVIEWING as REC_KEEP_REVIEWING,
    NOT_READY,
    REJECT_RECOMMENDED,
    REVIEW_RECOMMENDED,
)
from src.intelligence.evaluation.rules import R_APPROVE, R_KEEP, R_REJECT, R_REVIEW
from src.intelligence.evaluation.store import evaluation_root
from src.intelligence.formal_review import cli as fr_cli
from src.intelligence.formal_review.config import (
    ACTIONS,
    APPROVED,
    KEEP_REVIEWING,
    REJECTED,
    REOPENED_FOR_REVIEW,
    RETIRED,
    SUPERSEDED,
    FormalReviewPolicy,
    formal_review_policy_from_mapping,
    load_formal_review_policy,
)
from src.intelligence.formal_review.errors import (
    ActionNotAllowed,
    ApproveAgainstRecommendationBlocked,
    DecisionHeadChanged,
    FormalReviewError,
    FormalReviewPolicyError,
    MaterialDigestChanged,
    PacketEvidenceDigestChanged,
    PacketMissing,
    PacketPatternMismatch,
    PolicyDigestMismatch,
    ReasonNotSubstantive,
    ReasonTooShort,
    RecommendationMismatch,
    RejectAgainstRecommendationBlocked,
    ReopenNotEligible,
    ReplacementPatternRequired,
    ReplayEvidenceRequired,
    SiblingAcknowledgementRequired,
    SiblingConflictBlocked,
    StaleReviewPacket,
)
from src.intelligence.formal_review.groups import build_groups, sibling_key
from src.intelligence.formal_review.metrics import assert_operational_only
from src.intelligence.formal_review.ordering import SECTION_APPROVE, SECTION_REJECT, SECTION_REOPEN
from src.intelligence.formal_review.packet import evidence_view, packet_evidence_digest
from src.intelligence.formal_review.service import FormalDecisionRequest, FormalReviewService
from src.intelligence.formal_review.store import formal_review_root
from src.intelligence.replay.config import load_replay_policy
from src.intelligence.replay.store import ReplayStore, replay_root
from src.intelligence.shadow_review.config import AGREE, DISAGREE, load_shadow_review_policy
from src.intelligence.shadow_review.events import ShadowReviewEventStore, shadow_review_root
from src.intelligence.shadow_review.material import material_digest
from src.intelligence.shadow_review.models import find_forbidden_keys, shadow_review_id_for

_spec = importlib.util.spec_from_file_location("_tsr", Path(__file__).with_name("test_shadow_review.py"))
_tsr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tsr)
evaluation_row = _tsr.evaluation

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "src" / "intelligence" / "formal_review"
EVAL_POLICY, REC_POLICY = load_policies()
SHADOW_POLICY = load_shadow_review_policy()
REPLAY_POLICY = load_replay_policy()
DECISION_POLICY = load_decision_policy()
FR_POLICY = load_formal_review_policy()
NOW = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)
ELIGIBLE = 139
REASON_OK = "Approved after reviewing six axes, replay persistence and sibling context in detail."
REASON_REJECT = "Rejected: repeated UP/DOWN contradiction across supporting documents remains active."
REASON_KEEP = "Keep reviewing until more regimes are covered."

# ---------------------------------------------------------------- synthetic universe
COMP_A = {"pattern_type": "EVIDENCE_OUTLOOK", "evidence": ["FX", "US_EQUITY"], "outlook": ["dir=UP", "target=JAPAN_EQUITY"],
          "market_state": [], "theme": "UNKNOWN", "why": "NO_WHY", "risk": ""}
COMP_B = {**COMP_A, "outlook": ["dir=DOWN", "target=JAPAN_EQUITY"]}            # pA の反対方向 sibling
COMP_C = {**COMP_A, "outlook": ["dir=UP", "target=JAPAN_EQUITY", "horizon=1W"]}  # 同方向 sibling（context）
COMP_K = {"pattern_type": "STATE_OUTLOOK", "evidence": [], "outlook": ["dir=UP", "target=JAPAN_EQUITY"],
          "market_state": ["equity_direction=UP"], "theme": "UNKNOWN", "why": "", "risk": ""}
COMP_R = {"pattern_type": "EVIDENCE_OUTLOOK", "evidence": ["JAPAN_RATES"], "outlook": ["dir=DOWN", "target=JAPAN_EQUITY"],
          "market_state": [], "theme": "UNKNOWN", "why": "NO_WHY", "risk": ""}
COMP_T = {"pattern_type": "THEME_OUTLOOK", "evidence": [], "outlook": ["dir=DOWN", "target=SECTOR"], "market_state": [],
          "theme": "THEME", "why": "", "risk": ""}


def approve_eval(pid, pattern_type="EVIDENCE_OUTLOOK", **kw):
    kw.setdefault("support", 6); kw.setdefault("span", 130); kw.setdefault("months", 5); kw.setdefault("cells", 3)
    kw.setdefault("classification", "NEW_PATTERN_CANDIDATE")
    return evaluation_row(pid, pattern_type=pattern_type, recommendation=APPROVE_RECOMMENDED, triggered_rule=R_APPROVE,
                          states={a: "HIGH" for a in AXES}, supporting=("DATA_QUALITY_HIGH", "CONSISTENCY_HIGH"),
                          corpus_size=ELIGIBLE, corpus_milestone="CORPUS_100", **kw)


def reject_eval(pid, pattern_type="EVIDENCE_OUTLOOK", **kw):
    states = {a: "MEDIUM" for a in AXES}
    states[A_CONSISTENCY] = "LOW"; states[A_STRENGTH] = "HIGH"; states[A_TIME] = "MEDIUM"
    kw.setdefault("support", 5)
    return evaluation_row(pid, pattern_type=pattern_type, recommendation=REJECT_RECOMMENDED, triggered_rule=R_REJECT,
                          states=states, contradiction=True, contradiction_repeated=True,
                          supporting=("CONSISTENCY_LOW", "CONTRADICTION_REPEATED"), corpus_size=ELIGIBLE,
                          corpus_milestone="CORPUS_100", **kw)


def review_eval(pid, pattern_type="EVIDENCE_OUTLOOK", **kw):
    return evaluation_row(pid, pattern_type=pattern_type, recommendation=REVIEW_RECOMMENDED, triggered_rule=R_REVIEW,
                          corpus_size=ELIGIBLE, corpus_milestone="CORPUS_100", **kw)


def metrics_for(pid, rec, *, first=78, persistence="1.0000", reversals=0, in_state=61, history=139,
                stability="STABLE", worst="HIGH", time_high=61, cross_high=61, main_first=80):
    approve = rec == APPROVE_RECOMMENDED
    return {"pattern_id": pid, "current_recommendation": rec, "current_lifecycle": "STRONG_PATTERN_CANDIDATE",
            "recommendation_transition_count": reversals + 1, "recommendation_reversal_count": reversals,
            "first_approve_recommended_position": first if approve else None,
            "first_approve_recommended_date": "2026-07-01" if approve else None,
            "first_reject_recommended_position": None if approve else first,
            "first_reject_recommended_date": None if approve else "2026-05-10",
            "approve_persistence_ratio": persistence if approve else None,
            "reject_persistence_ratio": None if approve else persistence,
            "state_persistence_ratio": persistence, "eligible_documents_in_current_state": in_state,
            "history_eligible_documents": history, "stability_class": stability,
            "calibration_state": REPLAY_POLICY.stability_calibration_state, "provisional": False,
            "worst_consistency_observed": worst, "positions_with_time_high": time_high,
            "positions_with_cross_regime_high": cross_high, "main_appearance_count": 3,
            "first_surfaced_in_main_position": main_first}


class Bench:
    """合成 data root: research + evaluation + shadow review + decision + replay。corpus state は注入（eligible 139）。"""

    def __init__(self, tmp_path: Path, *, eligible: int = ELIGIBLE, with_replay: bool = True, replay_captured: int = ELIGIBLE):
        self.root = Path(tmp_path) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.eligible = eligible
        self.ticks = 0
        self.components = {"pA": COMP_A, "pB": COMP_B, "pC": COMP_C, "pK": COMP_K, "pR": COMP_R, "pT": COMP_T, "pN": COMP_K}
        self.lifecycles = {pid: "STRONG_PATTERN_CANDIDATE" for pid in self.components}
        self.lifecycles["pC"] = "REVIEW_CANDIDATE"
        self.records = {pid: {"pattern_id": pid, "pattern_version": "1.0.0", "components": comp,
                              "supporting_document_ids": ["d1", "d2", "d3", "d4", "d5", "d6"], "support_count": 6,
                              "eligible_support": 6, "regime_count": 3, "regime_coverage": ["regime:aaa", "regime:bbb", "regime:ccc"],
                              "span_days": 130, "valid_ratio": "1.00", "date_range": ["2026-02-20", "2026-06-30"],
                              "first_seen": "2026-02-20", "last_seen": "2026-06-30", "limitations": [],
                              "pattern_record_id": f"cpr_{pid}"}
                        for pid, comp in self.components.items()}
        self.evals = {
            "pA": approve_eval("pA"), "pB": approve_eval("pB"), "pC": review_eval("pC"),
            "pK": approve_eval("pK", pattern_type="STATE_OUTLOOK"), "pR": reject_eval("pR"),
            "pT": reject_eval("pT", pattern_type="THEME_OUTLOOK"),
            "pN": evaluation_row("pN", pattern_type="STATE_OUTLOOK", recommendation=NOT_READY, triggered_rule="NOT_READY:DATA_QUALITY_LOW",
                                 corpus_size=ELIGIBLE, corpus_milestone="CORPUS_100"),
        }
        self.dna = {pid: {"pattern_id": pid, "classification": "NEW_PATTERN_CANDIDATE", "best_rule_id": "",
                          "direction_relation": "UNKNOWN", "candidate_rule_ids": [], "comparison_id": f"crd_{pid}"}
                    for pid in self.components}
        self.dna["pK"] = {**self.dna["pK"], "classification": "EXPLAINED_BY_EXISTING_RULE", "best_rule_id": "JP_DIR_001",
                          "direction_relation": "SAME", "candidate_rule_ids": ["JP_DIR_001"]}
        self.conflicts = []
        self.metrics = {"pA": metrics_for("pA", APPROVE_RECOMMENDED, first=78, in_state=61),
                        "pB": metrics_for("pB", APPROVE_RECOMMENDED, first=125, in_state=14, stability="RECENT_TRANSITION"),
                        "pK": metrics_for("pK", APPROVE_RECOMMENDED, first=91, in_state=48),
                        "pR": metrics_for("pR", REJECT_RECOMMENDED, first=33, in_state=106),
                        "pT": metrics_for("pT", REJECT_RECOMMENDED, first=82, in_state=57, persistence="0.9500")}
        self.replay_enabled = with_replay
        self.replay_captured = replay_captured
        self.replay_policy_digests = None
        self.write_all()

    # ------------------------------------------------------------ writers
    def write_all(self):
        self.write_research(); self.write_evaluations(); self.write_replay()

    def write_research(self):
        r = self.root / "compass_research"; r.mkdir(parents=True, exist_ok=True)
        (r / "patterns.jsonl").write_text("".join(json.dumps({**rec, "status": self.lifecycles[pid]}, ensure_ascii=False, sort_keys=True) + "\n"
                                                  for pid, rec in self.records.items()), encoding="utf-8")
        (r / "dna_comparisons.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in self.dna.values()), encoding="utf-8")
        (r / "conflicts.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in self.conflicts), encoding="utf-8")
        (r / "structures.jsonl").write_text("".join(json.dumps({"document_id": d, "document_date": f"2026-0{3 + i % 4}-1{i}", "eligible": True,
                                                                 "created_at": "2026-08-10T00:00:00+00:00"}, sort_keys=True) + "\n"
                                                    for i, d in enumerate(["d1", "d2", "d3", "d4", "d5", "d6"])), encoding="utf-8")

    def write_evaluations(self):
        root = evaluation_root(self.root); root.mkdir(parents=True, exist_ok=True)
        (root / "evaluations.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                                        for r in sorted(self.evals.values(), key=lambda r: r["pattern_id"])), encoding="utf-8")
        (root / "evaluation_snapshot.json").write_text(json.dumps({"generated_at": NOW.isoformat(), "corpus_size": ELIGIBLE}), encoding="utf-8")

    def write_replay(self):
        if not self.replay_enabled:
            return
        digests = self.replay_policy_digests or {"evaluation": EVAL_POLICY.digest(), "recommendation": REC_POLICY.digest(),
                                                 "shadow_review": SHADOW_POLICY.digest(), "replay": REPLAY_POLICY.digest()}
        approve_items = [{"pattern_id": p, "first_approve_position": m["first_approve_recommended_position"], "appeared_only_after_100": m["first_approve_recommended_position"] > 100,
                          "reversions": {}, "worst_consistency_observed": "HIGH"} for p, m in self.metrics.items() if m["current_recommendation"] == APPROVE_RECOMMENDED]
        reject_items = [{"pattern_id": p, "first_material_contradiction_position": 30, "first_reject_position": m["first_reject_recommended_position"],
                         "reject_driver": "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION", "contradiction_recovery_positions": [],
                         "was_review_before_reject": True, "recommendation_before_reject": "REVIEW_RECOMMENDED"}
                        for p, m in self.metrics.items() if m["current_recommendation"] == REJECT_RECOMMENDED]
        summary = {"run_id": "crp_test", "run_digest": "run" + str(self.replay_captured).rjust(13, "0"), "captured_eligible": self.replay_captured,
                   "policy_digests": digests, "pattern_metrics": self.metrics,
                   "approve_stress": {"count": len(approve_items), "items": approve_items},
                   "reject_stress": {"count": len(reject_items), "items": reject_items}, "run_created_at": NOW.isoformat()}
        manifest = {"run_id": "crp_test", "replay_policy": {"version": REPLAY_POLICY.policy_version, "digest": REPLAY_POLICY.digest()}}
        ReplayStore(replay_root(self.root)).write_run("crp_test", manifest=manifest, snapshots=[], timelines=[], events=[], summary=summary)

    # ------------------------------------------------------------ service
    def corpus_state(self) -> CorpusState:
        e = self.eligible
        return CorpusState(documents=e + 2, usable=e + 2, eligible=e, valid=e, milestone="CORPUS_100" if e >= 100 else "CORPUS_50")

    def clock(self) -> datetime:
        self.ticks += 1
        return NOW + timedelta(minutes=self.ticks)

    def service(self, policy: FormalReviewPolicy = None, **overrides) -> FormalReviewService:
        return FormalReviewService(self.root, policy=policy or FR_POLICY, corpus_state_resolver=self.corpus_state,
                                   clock=self.clock, **overrides)

    def build(self, policy=None):
        return self.service(policy).build()

    def packet(self, pid):
        return self.service().store.packet(pid)

    def decide(self, pid, action, reason, *, dry_run=False, packet_id=None, actor="reviewer_taro", **kw):
        pk = self.packet(pid)
        req = FormalDecisionRequest(pattern_id=pid, action=action, packet_id=packet_id or (pk["identity"]["packet_id"] if pk else "frp_missing"),
                                    reason=reason, actor=actor, **kw)
        return self.service().decide(req, dry_run=dry_run)

    def decisions(self):
        return DecisionStore(decisions_root(self.root)).records()

    def shadow(self, pid, outcome, reason="", related=""):
        row = self.evals[pid]
        payload = {"pattern_id": pid, "reviewed_at": NOW.isoformat(), "reviewer_id": "SUPERVISOR", "reviewer_type": "HUMAN",
                   "review_outcome": outcome, "reason": reason, "structured_reason": {}, "related_pattern_id": related,
                   "recommendation_at_review": row["recommendation"], "axis_states_at_review": row["axis_states"],
                   "axis_applicability_at_review": row["axis_applicability"], "reference_score_at_review": row["reference_score"],
                   "queue_rank_at_review": 1, "queue_section_at_review": "MAIN",
                   "material_digest_at_review": material_digest(row, self.lifecycles[pid], SHADOW_POLICY),
                   "evaluation_id": row["evaluation_id"], "inputs_digest": row["inputs_digest"], "lifecycle_at_review": self.lifecycles[pid],
                   "evaluation_policy_version": EVAL_POLICY.policy_version, "evaluation_policy_digest": EVAL_POLICY.digest(),
                   "recommendation_policy_version": REC_POLICY.policy_version, "recommendation_policy_digest": REC_POLICY.digest(),
                   "shadow_review_policy_version": SHADOW_POLICY.policy_version, "shadow_review_policy_digest": SHADOW_POLICY.digest(),
                   "corpus_size": ELIGIBLE, "corpus_milestone": "CORPUS_100", "shadow_mode": False, "formal_review_gate_reached": True,
                   "schema_version": "1.0.0", "sequence": 0, "previous_record_hash": "", "record_hash": ""}
        payload["shadow_review_id"] = shadow_review_id_for(payload)
        return ShadowReviewEventStore(shadow_review_root(self.root)).append(payload, SHADOW_POLICY)


@pytest.fixture()
def bench(tmp_path):
    return Bench(tmp_path)


def _sections(b):
    return b.service().store.queue()["sections"]


def _ids(rows):
    return [r["pattern_id"] for r in rows]


def _tree_digest(root: Path, exclude: str = ""):
    """root 配下の file → sha256。key は OS に依らない POSIX 形式（Windows の backslash を key に持ち込まない）。"""
    import hashlib
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and (not exclude or exclude not in p.relative_to(root).parts):
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _under_logical_dir(key: str, top: str) -> bool:
    """相対 path 文字列が論理 directory `top` 直下にあるか。POSIX / Windows どちらの区切りでも同じ答えになる。"""
    from pathlib import PurePosixPath, PureWindowsPath

    parts = PureWindowsPath(key).parts if "\\" in key else PurePosixPath(key).parts
    return len(parts) >= 2 and parts[0] == top


# ================================================================== 1-5 population
def test_dynamic_population_approve_reject_and_not_ready_excluded(bench):
    out = bench.build()
    sec = _sections(bench)
    assert _ids(sec[SECTION_APPROVE]) == ["pA", "pK", "pB"] and _ids(sec[SECTION_REJECT]) == ["pR", "pT"]
    assert out["metrics"]["by_recommendation"] == {APPROVE_RECOMMENDED: 3, REJECT_RECOMMENDED: 2}
    assert bench.service().store.manifest()["population"]["excluded_not_ready"] == 1
    assert "pN" not in bench.service().store.packet_ids()


def test_terminal_and_decided_heads_leave_the_primary_queue(bench):
    bench.build()
    bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",))
    bench.decide("pR", "reject", REASON_REJECT)
    bench.build()
    sec = _sections(bench)
    assert "pA" not in _ids(sec[SECTION_APPROVE]) and "pR" not in _ids(sec[SECTION_REJECT])
    decided = {r["pattern_id"]: r for r in bench.service().store.queue()["decided"]}
    assert decided["pA"]["allowed_next_actions"] == [SUPERSEDED, RETIRED] and decided["pR"]["allowed_next_actions"] == []
    bench.decide("pA", "supersede", "Superseded by the broader STATE_OUTLOOK pattern pK.", replacement_pattern_id="pK")
    bench.build()
    assert bench.service().store.queue()["decided"][0]["decision_state"] == SUPERSEDED
    assert bench.service().store.queue()["decided"][0]["allowed_next_actions"] == []


def test_reopen_section_only_when_material_change_detected(bench):
    bench.build()
    bench.decide("pR", "reject", REASON_REJECT)
    bench.build()
    assert _sections(bench)[SECTION_REOPEN] == []
    bench.evals["pR"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 7          # material change（支持文書が増えた）
    bench.evals["pR"]["axis_metrics"][A_QUALITY]["eligible_support"] = 7
    bench.write_evaluations()
    bench.build()
    assert _ids(_sections(bench)[SECTION_REOPEN]) == ["pR"]
    assert bench.packet("pR")["decision"]["reopen"]["status"] == "REOPEN_ELIGIBLE"


def test_review_sibling_is_context_only_and_cannot_be_decided(bench):
    bench.build()
    queue = bench.service().store.queue()
    assert [c["pattern_id"] for c in queue["context"]] == ["pC"] and queue["context"][0]["role"] == "CONTEXT_ONLY"
    assert "pC" not in {r["pattern_id"] for rows in queue["sections"].values() for r in rows}
    with pytest.raises(FormalReviewError) as exc:
        bench.decide("pC", "keep-reviewing", REASON_KEEP)
    assert exc.value.code == "CANDIDATE_MISSING"


# ================================================================== 6-8 packet schema / scan / determinism
REQUIRED_BLOCKS = {
    "identity": ("packet_id", "packet_schema_version", "built_at", "pattern_id", "pattern_type", "pattern_version", "lifecycle_status", "components"),
    "recommendation": ("recommendation", "triggered_rule", "blocking_rules", "supporting_rules", "shadow_mode", "formal_review_gate_reached", "corpus_size", "corpus_milestone"),
    "axes": ("states", "applicability", "reasons", "eligible_support", "support_count", "span_days", "distinct_calendar_months", "distinct_2d_cells", "confirmed_2d_cells", "document_qualities", "valid_ratio", "regime_coverage"),
    "reference": ("label", "reference_score", "reference_score_comparable", "relative_support_share"),
    "consistency": ("direction_counts", "document_contradiction", "document_contradiction_repeated", "narrow_sibling_contradiction", "narrow_sibling_repeated", "dna_conflicts", "direction_class"),
    "dna": ("classification", "best_rule_id", "direction_relation", "candidate_rule_count", "conflict_rule_ids", "conflict_count"),
    "replay": ("replay_run_id", "replay_run_digest", "captured_eligible", "first_recommendation_position", "first_recommendation_date", "persistence_ratio", "reversal_count", "eligible_documents_in_current_state", "stability_class", "calibration_state", "worst_consistency_observed", "positions_with_time_high", "positions_with_cross_regime_high", "first_surfaced_in_main_position", "evidence_age_eligible_docs"),
    "shadow_history": ("event_count", "outcome_history", "current_review"),
    "decision": ("current_state", "head_decision_id", "history_length", "reopen", "allowed_next_actions"),
    "group": ("sibling_group_key", "members", "group_state_digest"),
    "freshness": ("material_digest", "packet_evidence_digest", "evaluation_id", "inputs_digest", "policy_digests", "policy_versions", "corpus_eligible_at_build", "head_decision_id"),
}


def test_packet_schema_complete_and_reference_labeled(bench):
    bench.build()
    p = bench.packet("pA")
    for block, fields in REQUIRED_BLOCKS.items():
        assert set(fields) <= set(p[block]), (block, set(fields) - set(p[block]))
    assert p["reference"]["label"] == "NON_DECISIONAL_REFERENCE_ONLY" and "warnings" in p
    assert set(p["freshness"]["policy_digests"]) == {"evaluation", "recommendation", "shadow_review", "replay", "decision", "formal_review"}
    assert all(f in p["shadow_history"]["outcome_history"][0] for f in ()) and p["shadow_history"]["event_count"] == 0
    assert p["dna"]["classification"] == "NEW_PATTERN_CANDIDATE" and p["axes"]["regime_coverage"] == ["regime:aaa", "regime:bbb", "regime:ccc"]


def test_forbidden_key_scan_is_recursive_and_fails_closed(bench):
    from src.intelligence.formal_review.errors import ForbiddenKeyInPacket

    bench.build()
    assert all(find_forbidden_keys(bench.packet(pid)) == [] for pid in bench.service().store.packet_ids())
    bench.records["pA"]["components"] = {**COMP_A, "path": "leak"}
    bench.write_research()
    with pytest.raises(ForbiddenKeyInPacket):
        bench.build()


def test_packet_evidence_digest_deterministic_and_ignores_timestamps(bench):
    bench.build()
    first = bench.packet("pA")
    bench.ticks += 100                                                          # built_at が変わる
    bench.build()
    second = bench.packet("pA")
    assert first["identity"]["built_at"] != second["identity"]["built_at"]
    assert first["freshness"]["packet_evidence_digest"] == second["freshness"]["packet_evidence_digest"]
    assert first["identity"]["packet_id"] == second["identity"]["packet_id"]
    assert "built_at" not in json.dumps(evidence_view(first))


# ================================================================== 9-15 digest sensitivity
def _digest_after(bench, mutate):
    bench.build()
    before = bench.packet("pA")["freshness"]["packet_evidence_digest"]
    mutate(bench)
    bench.build()
    return before, bench.packet("pA")["freshness"]["packet_evidence_digest"]


def _rewrite(bench):
    bench.write_evaluations(); bench.write_research(); bench.write_replay()


def test_digest_changes_with_support_count(bench):
    def m(b): b.evals["pA"]["axis_metrics"][A_QUALITY]["support_count"] = 7; _rewrite(b)
    a, c = _digest_after(bench, m); assert a != c


def test_digest_changes_with_span_days(bench):
    def m(b): b.evals["pA"]["axis_metrics"][A_TIME]["span_days"] = 131; _rewrite(b)
    a, c = _digest_after(bench, m); assert a != c


def test_digest_changes_with_dna_classification(bench):
    def m(b): b.evals["pA"]["axis_metrics"][A_NOVELTY]["classification"] = "PARTIALLY_EXPLAINED"; _rewrite(b)
    a, c = _digest_after(bench, m); assert a != c


def test_digest_changes_with_replay_evidence(bench):
    def m(b): b.metrics["pA"]["positions_with_time_high"] = 12; _rewrite(b)
    a, c = _digest_after(bench, m); assert a != c


def test_digest_changes_with_group_state(bench):
    def m(b):
        b.evals["pB"]["recommendation"] = REVIEW_RECOMMENDED; b.evals["pB"]["triggered_rule"] = R_REVIEW; _rewrite(b)
    a, c = _digest_after(bench, m); assert a != c


def test_digest_changes_with_decision_head(bench):
    def m(b): b.decide("pA", "keep-reviewing", REASON_KEEP)
    a, c = _digest_after(bench, m); assert a != c


def test_digest_changes_with_shadow_history(bench):
    def m(b): b.shadow("pA", AGREE, reason="")
    a, c = _digest_after(bench, m); assert a != c


# ================================================================== 17-25 freshness / stale
def test_corpus_only_growth_does_not_stale_and_is_recorded(bench):
    bench.build()
    old_packet = bench.packet("pA")
    bench.eligible = 140
    for row in bench.evals.values():                                             # 再評価: corpus_size / inputs_digest だけ変わる
        row["corpus_size"] = 140; row["inputs_digest"] = "feedfacefeedface"; row["evaluation_id"] = "cev_" + row["pattern_id"].ljust(16, "1")[:16]
    bench.write_evaluations()
    assert bench.service().current_packet("pA")["freshness"]["packet_evidence_digest"] == old_packet["freshness"]["packet_evidence_digest"]
    out = bench.decide("pA", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pB",))
    assert out["validation"]["ok"] and out["metadata"]["corpus_eligible_at_packet"] == "139" and out["metadata"]["corpus_eligible_at_write"] == "140"


def test_recommendation_change_is_stale(bench):
    bench.build()
    bench.evals["pA"]["recommendation"] = REVIEW_RECOMMENDED; bench.evals["pA"]["triggered_rule"] = R_REVIEW; bench.write_evaluations()
    with pytest.raises(RecommendationMismatch):
        bench.decide("pA", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pB",))


def test_material_digest_change_is_stale(bench):
    bench.build()
    bench.evals["pA"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 7; bench.evals["pA"]["axis_metrics"][A_QUALITY]["eligible_support"] = 7
    bench.write_evaluations()
    with pytest.raises(MaterialDigestChanged):
        bench.decide("pA", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pB",))


def test_packet_evidence_digest_change_is_stale_even_when_material_unchanged(bench):
    bench.build()
    bench.evals["pA"]["axis_metrics"][A_TIME]["span_days"] = 140; bench.write_evaluations()   # material 外・証拠内
    with pytest.raises(PacketEvidenceDigestChanged):
        bench.decide("pA", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pB",))


@pytest.mark.parametrize("layer", ["evaluation", "recommendation", "shadow_review", "replay", "formal_review"])
def test_policy_digest_change_is_stale(bench, layer):
    import dataclasses

    bench.build()
    pk = bench.packet("pA")
    req = FormalDecisionRequest("pA", "approve", pk["identity"]["packet_id"], REASON_OK, "taro", acknowledge_siblings=("pB",))
    if layer == "formal_review":
        svc = bench.service(policy=FormalReviewPolicy(policy_version="1.1.0", replay_evidence_age_warning_eligible_docs=6))
    else:
        base = {"evaluation": EVAL_POLICY, "recommendation": REC_POLICY, "shadow_review": SHADOW_POLICY, "replay": REPLAY_POLICY}[layer]
        changed = dataclasses.replace(base, policy_version="9.9.9")
        key = {"evaluation": "evaluation_policy", "recommendation": "recommendation_policy",
               "shadow_review": "shadow_policy", "replay": "replay_policy"}[layer]
        svc = bench.service(**{key: changed})
    with pytest.raises(PolicyDigestMismatch):
        svc.decide(req, dry_run=True)


# ================================================================== 26-28 symmetry
def test_approve_only_for_approve_recommended(bench):
    bench.build()
    with pytest.raises(ApproveAgainstRecommendationBlocked):
        bench.decide("pR", "approve", REASON_OK, dry_run=True)


def test_reject_only_for_reject_recommended(bench):
    bench.build()
    with pytest.raises(RejectAgainstRecommendationBlocked):
        bench.decide("pA", "reject", REASON_REJECT, dry_run=True)


def test_human_disagreement_uses_keep_reviewing(bench):
    bench.build()
    out = bench.decide("pA", "keep-reviewing", "Disagree with approval; want one more regime first.", reason_category="MORE_REGIMES")
    rec = out["outcome"]["record"]
    assert out["mutation"] == "APPEND decisions.jsonl" and rec["decision_type"] == KEEP_REVIEWING
    assert rec["metadata"]["reason_category"] == "MORE_REGIMES" and rec["promotion_status"] == "NOT_PROMOTED"


# ================================================================== 29-33 sibling guard
def test_c1_opposite_approved_sibling_hard_blocks_without_override(bench):
    bench.build()
    bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",))
    bench.build()
    with pytest.raises(SiblingConflictBlocked):
        bench.decide("pB", "approve", REASON_OK, dry_run=True)
    with pytest.raises(SiblingConflictBlocked):                                   # acknowledgement は override にならない
        bench.decide("pB", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pA",))
    with pytest.raises(FormalReviewPolicyError):                                  # policy にも override mode は存在しない
        formal_review_policy_from_mapping({"sibling_guard": {"mode": "C1_OVERRIDE_WITH_REASON"}})


def test_c3_undecided_opposite_approve_recommended_requires_and_records_acknowledgement(bench):
    bench.build()
    with pytest.raises(SiblingAcknowledgementRequired):
        bench.decide("pA", "approve", REASON_OK, dry_run=True)
    out = bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",))
    assert out["outcome"]["record"]["metadata"]["acknowledged_sibling"] == "pB"
    assert bench.packet("pA")["warnings"][0]["code"] == "W_SIBLING_OPPOSITE_APPROVE_RECOMMENDED"


def test_no_sibling_widening_for_state_or_theme_outlook(bench):
    bench.build()
    assert bench.packet("pK")["group"]["sibling_group_key"] == "" and bench.packet("pK")["group"]["members"] == []
    assert bench.packet("pT")["group"]["sibling_group_key"] == "" and bench.packet("pT")["group"]["members"] == []
    assert set(build_groups(bench.records)) == {"FX,US_EQUITY|target=JAPAN_EQUITY", "JAPAN_RATES|target=JAPAN_EQUITY"}
    assert sibling_key(COMP_K) == "" and sibling_key(COMP_T) == "" and sibling_key(COMP_A) == sibling_key(COMP_B)
    # STATE_OUTLOOK の反対方向 pattern を APPROVED しても pK は block されない
    bench.records["pS"] = {**bench.records["pK"], "pattern_id": "pS", "components": {**COMP_K, "outlook": ["dir=DOWN", "target=JAPAN_EQUITY"]}}
    bench.lifecycles["pS"] = "STRONG_PATTERN_CANDIDATE"; bench.components["pS"] = bench.records["pS"]["components"]
    bench.evals["pS"] = approve_eval("pS", pattern_type="STATE_OUTLOOK"); bench.dna["pS"] = {**bench.dna["pA"], "pattern_id": "pS"}
    bench.metrics["pS"] = metrics_for("pS", APPROVE_RECOMMENDED, first=100); _rewrite(bench)
    bench.build()
    bench.decide("pS", "approve", REASON_OK)
    bench.build()
    assert bench.decide("pK", "approve", REASON_OK, dry_run=True)["validation"]["ok"]


# ================================================================== 34-37 replay evidence
def test_approved_and_rejected_require_replay_evidence(tmp_path):
    b = Bench(tmp_path, with_replay=False)
    b.build()
    with pytest.raises(ReplayEvidenceRequired):
        b.decide("pA", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pB",))
    with pytest.raises(ReplayEvidenceRequired):
        b.decide("pR", "reject", REASON_REJECT, dry_run=True)
    assert b.packet("pA")["warnings"][-1]["code"] != "" and "W_REPLAY_EVIDENCE_MISSING" in [w["code"] for w in b.packet("pA")["warnings"]]


def test_keep_reviewing_works_without_replay_evidence(tmp_path):
    b = Bench(tmp_path, with_replay=False)
    b.build()
    assert b.decide("pA", "keep-reviewing", REASON_KEEP)["mutation"] == "APPEND decisions.jsonl"


def test_replay_evidence_must_be_current_compatible(bench):
    bench.replay_policy_digests = {"evaluation": "0000000000000000", "recommendation": REC_POLICY.digest(),
                                   "shadow_review": SHADOW_POLICY.digest(), "replay": REPLAY_POLICY.digest()}
    bench.write_replay(); bench.build()
    p = bench.packet("pR")
    assert p["replay"]["current_compatible"] is False and "POLICY_DIGEST_MISMATCH:evaluation" in p["replay"]["compatibility_reasons"]
    assert "W_REPLAY_EVIDENCE_NOT_CURRENT" in [w["code"] for w in p["warnings"]]
    with pytest.raises(ReplayEvidenceRequired):
        bench.decide("pR", "reject", REASON_REJECT, dry_run=True)


def test_replay_age_is_warning_only(tmp_path):
    old = Bench(tmp_path / "old", replay_captured=134); old.build()
    assert "W_REPLAY_EVIDENCE_AGE" in [w["code"] for w in old.packet("pK")["warnings"]]
    assert old.packet("pK")["replay"]["evidence_age_eligible_docs"] == 5
    assert old.decide("pK", "approve", REASON_OK, dry_run=True)["validation"]["ok"]
    fresh = Bench(tmp_path / "fresh", replay_captured=135); fresh.build()
    assert "W_REPLAY_EVIDENCE_AGE" not in [w["code"] for w in fresh.packet("pK")["warnings"]]


# ================================================================== 38-40 stability warnings only
@pytest.mark.parametrize("cls,code", [("RECENT_TRANSITION", "W_RECENT_TRANSITION"), ("OSCILLATING", "W_OSCILLATING"),
                                      ("INSUFFICIENT_HISTORY", "W_INSUFFICIENT_HISTORY")])
def test_stability_classes_warn_but_never_block(bench, cls, code):
    bench.metrics["pK"]["stability_class"] = cls; bench.write_replay(); bench.build()
    assert code in [w["code"] for w in bench.packet("pK")["warnings"]]
    assert bench.decide("pK", "approve", REASON_OK, dry_run=True)["validation"]["ok"]


# ================================================================== 41-43 ordering
def test_reject_section_first_and_reject_ordering(bench):
    bench.build()
    sec = _sections(bench)
    assert [r["queue_rank"] for r in sec[SECTION_REJECT]] == [1, 2] and [r["queue_rank"] for r in sec[SECTION_APPROVE]] == [3, 4, 5]
    assert _ids(sec[SECTION_REJECT]) == ["pR", "pT"]                              # first_reject 33 < 82
    bench.metrics["pT"]["first_reject_recommended_position"] = 33; bench.write_replay(); bench.build()
    assert _ids(_sections(bench)[SECTION_REJECT]) == ["pR", "pT"]                 # 同位置 → persistence 1.0 > 0.95
    bench.metrics["pT"]["reject_persistence_ratio"] = "1.0000"; bench.records["pT"]["eligible_support"] = 6
    bench.evals["pT"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 9; _rewrite(bench); bench.build()
    assert _ids(_sections(bench)[SECTION_REJECT]) == ["pT", "pR"]                 # eligible_support 9 > 6


def test_approve_ordering_stability_then_first_position_then_support(bench):
    bench.build()
    assert _ids(_sections(bench)[SECTION_APPROVE]) == ["pA", "pK", "pB"]           # STABLE(78) STABLE(91) RECENT(125)
    bench.metrics["pK"]["first_approve_recommended_position"] = 70; bench.write_replay(); bench.build()
    assert _ids(_sections(bench)[SECTION_APPROVE]) == ["pK", "pA", "pB"]
    bench.metrics["pK"]["first_approve_recommended_position"] = 78; bench.evals["pK"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 9
    _rewrite(bench); bench.build()
    assert _ids(_sections(bench)[SECTION_APPROVE]) == ["pK", "pA", "pB"]           # 同位置 → eligible_support 9 > 6
    twice = [_ids(_sections(bench)[SECTION_APPROVE]) for _ in (bench.build(), bench.build())]
    assert twice[0] == twice[1]


# ================================================================== 44-50 reasons / disposition
def test_reason_minimums_and_label_only_rejection(bench):
    bench.build()
    with pytest.raises(ReasonTooShort):
        bench.decide("pA", "keep-reviewing", "too short", dry_run=True)                       # 9 chars < 10
    with pytest.raises(ReasonTooShort):
        bench.decide("pA", "approve", "nineteen characters", dry_run=True, acknowledge_siblings=("pB",))
    with pytest.raises(ReasonNotSubstantive):
        bench.decide("pA", "approve", "APPROVE_RECOMMENDED.", dry_run=True, acknowledge_siblings=("pB",))
    with pytest.raises(ReasonTooShort):
        bench.decide("pR", "reject", "contradiction seen", dry_run=True)
    with pytest.raises(ReasonNotSubstantive):
        bench.decide("pA", "keep-reviewing", REASON_KEEP, dry_run=True, reason_category="MORE_LUCK")


def test_superseded_retired_and_reopen_reasons(bench):
    bench.build()
    bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",))
    bench.build()
    with pytest.raises(ReplacementPatternRequired):
        bench.decide("pA", "supersede", "Superseded by a broader pattern found later.", dry_run=True)
    with pytest.raises(ReplacementPatternRequired):
        bench.decide("pA", "supersede", "Superseded by a broader pattern found later.", dry_run=True, replacement_pattern_id="pA")
    with pytest.raises(ReasonTooShort):
        bench.decide("pA", "retire", "retired now", dry_run=True)
    assert bench.decide("pA", "retire", "Retired: the regime this pattern described no longer occurs.", dry_run=True)["validation"]["ok"]
    bench.decide("pR", "reject", REASON_REJECT); bench.build()
    bench.evals["pR"]["axis_metrics"][A_STRENGTH]["eligible_support"] = 7; bench.evals["pR"]["axis_metrics"][A_QUALITY]["eligible_support"] = 7
    bench.write_evaluations(); bench.build()
    with pytest.raises(ReasonTooShort):
        bench.decide("pR", "reopen", "material change", dry_run=True)
    out = bench.decide("pR", "reopen", "Material change: supporting evidence grew from 5 to 7 eligible documents.")
    assert out["outcome"]["record"]["decision_type"] == REOPENED_FOR_REVIEW and out["outcome"]["record"]["reopens_decision_id"]


def test_duplicate_overlap_is_keep_reviewing_with_metadata(bench):
    bench.build()
    with pytest.raises(ReasonNotSubstantive):
        bench.decide("pB", "keep-reviewing", "Duplicate of another pattern.", dry_run=True, disposition="DUPLICATE_OR_OVERLAPPING")
    with pytest.raises(ReasonNotSubstantive):
        bench.decide("pB", "approve", REASON_OK, dry_run=True, disposition="DUPLICATE_OR_OVERLAPPING", related_pattern_id="pA", acknowledge_siblings=("pA",))
    out = bench.decide("pB", "keep-reviewing", "Overlaps pA; keep reviewing as one concept.", disposition="DUPLICATE_OR_OVERLAPPING", related_pattern_id="pA")
    md = out["outcome"]["record"]["metadata"]
    assert md["disposition"] == "DUPLICATE_OR_OVERLAPPING" and md["related_pattern_id"] == "pA" and out["outcome"]["record"]["decision_type"] == KEEP_REVIEWING


# ================================================================== 51-55 reopen
def test_reopen_requires_material_change_and_ignores_corpus_score_and_time(bench):
    bench.build()
    bench.decide("pR", "reject", REASON_REJECT); bench.build()
    with pytest.raises(ReopenNotEligible):
        bench.decide("pR", "reopen", "Material change: new contradicting documents arrived.", dry_run=True)
    bench.eligible = 145                                                                 # corpus growth alone
    for row in bench.evals.values():
        row["corpus_size"] = 145
    bench.evals["pR"]["reference_score"] = 61.0                                           # score only
    bench.write_evaluations(); bench.ticks += 10_000                                       # elapsed time only
    bench.build()
    assert bench.packet("pR")["decision"]["reopen"]["status"] == "NOT_ELIGIBLE"
    assert _sections(bench)[SECTION_REOPEN] == [] and bench.service().reopen_check()[0]["eligible"] is False
    rows_before = len(bench.decisions())
    bench.evals["pR"]["axis_metrics"][A_CONSISTENCY]["contradiction_repeated"] = False    # material: 矛盾の反復が消えた
    bench.write_evaluations(); bench.build()
    assert bench.packet("pR")["decision"]["reopen"]["status"] == "REOPEN_ELIGIBLE"
    assert len(bench.decisions()) == rows_before                                          # system は REOPENED を書かない
    out = bench.decide("pR", "reopen", "Material change: the repeated contradiction no longer appears in evidence.")
    assert out["outcome"]["record"]["decision_type"] == REOPENED_FOR_REVIEW
    bench.build()
    assert "pR" in _ids(_sections(bench)[SECTION_REJECT])                                  # REOPENED → 再び primary


def test_rejected_without_packet_binding_is_unverifiable(bench):
    from src.intelligence.decision.service import DecisionRequest as RawRequest

    bench.build()
    svc = bench.service().decision_service()
    svc.decide(RawRequest("pR", REJECTED, "Rejected outside formal review for the test.", "taro"))   # binding の無い REJECTED
    bench.build()
    assert bench.packet("pR")["decision"]["reopen"]["status"] == "UNVERIFIABLE_NO_PACKET_BINDING"
    with pytest.raises(ReopenNotEligible):
        bench.decide("pR", "reopen", "Material change: attempting reopen without binding.", dry_run=True)


# ================================================================== 56-61 write path / batch / dry run / idempotency
def test_decision_service_is_the_sole_write_path_static():
    for py in sorted(PKG.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        tree = ast.parse(text)
        modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        if py.name != "service.py":
            assert not any(m.endswith("decision.service") for m in modules), py.name
            assert "DecisionStore(" not in text, py.name
        for node in ast.walk(tree):                                                # store.append(...) 系の直接呼び出しなし
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append":
                assert "store" not in ast.unparse(node.func.value).lower(), (py.name, ast.unparse(node))
    service_src = (PKG / "service.py").read_text(encoding="utf-8")
    assert service_src.count("DecisionRequest(") == 1 and service_src.count("service.decide(") == 1
    cli_tree = ast.parse((PKG / "cli.py").read_text(encoding="utf-8"))
    cli_names = {n.id for n in ast.walk(cli_tree) if isinstance(n, ast.Name)} | \
        {a.name for n in ast.walk(cli_tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not cli_names & {"DecisionStore", "DecisionService", "DecisionRequest"}     # CLI は decision store / service に触れない


def test_cli_has_no_batch_command_and_decide_takes_one_pattern(bench, monkeypatch, capsys):
    parser_cmds = set()
    import argparse

    real_add = argparse._SubParsersAction.add_parser

    def spy(self, name, **kw):
        parser_cmds.add(name)
        return real_add(self, name, **kw)

    monkeypatch.setattr(argparse._SubParsersAction, "add_parser", spy)
    monkeypatch.setattr(fr_cli, "FormalReviewService", lambda root, **kw: bench.service(**kw))
    assert fr_cli.main(["--data-root", str(bench.root), "validate-policy"]) == 0
    assert parser_cmds == {"build", "list", "show", "decide", "status", "reopen-check", "validate-policy"}
    assert not any("batch" in c for c in parser_cmds)
    bench.build()
    with pytest.raises(SystemExit):                                                    # 2 つ目の positional は受け付けない
        fr_cli.main(["decide", "pA", "pB", "--packet", "x", "--action", "approve", "--reason", REASON_OK, "--actor", "t"])
    from src.intelligence.formal_review.errors import BatchForbidden
    with pytest.raises(BatchForbidden):
        bench.service().decide(FormalDecisionRequest("pA,pB", "approve", "frp_x", REASON_OK, "t"), dry_run=True)


def test_dry_run_never_writes(bench):
    bench.build()
    before_dec = len(bench.decisions()); before_tree = _tree_digest(bench.root)
    out = bench.decide("pA", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pB",))
    assert out["mutation"] == "NONE (dry run)" and out["validation"]["ok"] and "outcome" not in out
    assert len(bench.decisions()) == before_dec and _tree_digest(bench.root) == before_tree


def test_idempotent_retry_does_not_duplicate(bench):
    bench.build()
    first = bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",))
    second = bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",))
    assert first["outcome"]["appended"] is True and second["outcome"]["appended"] is False
    assert second["outcome"]["store_reason"] == "DUPLICATE_OF_HEAD_IDEMPOTENT" and len(bench.decisions()) == 1
    assert bench.decisions()[0].idempotency_key == bench.packet("pA")["identity"]["packet_id"]


def test_real_write_requires_explicit_non_dry_run(bench):
    bench.build()
    bench.decide("pR", "reject", REASON_REJECT, dry_run=True)
    assert len(bench.decisions()) == 0
    bench.decide("pR", "reject", REASON_REJECT)
    assert len(bench.decisions()) == 1 and bench.decisions()[0].decision_type == REJECTED


# ================================================================== 62-67 promotion / DNA / PDF / shadow conversion
def test_promotion_always_not_promoted_and_no_promotion_vocabulary_in_package(bench):
    bench.build()
    rec = bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",))["outcome"]["record"]
    assert rec["promotion_status"] == "NOT_PROMOTED"
    assert not any("PROMOTED" in v or "DNA_CANDIDATE" in v for v in rec["metadata"].values())
    for py in PKG.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "DNA_CANDIDATE" not in text and "PROMOTED_TO_DNA" not in text, py.name


def test_no_dna_file_writes_and_no_pdf_reads(bench):
    import hashlib

    dna = [REPO_ROOT / "knowledge" / "compass_dna" / "market_rules.yaml", REPO_ROOT / "src" / "intelligence" / "compass" / "market_principles.py"]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in dna]
    bench.build(); bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",)); bench.decide("pR", "reject", REASON_REJECT)
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in dna] == before
    banned = ("pypdf", "ingest_path", "extract_text", "market_rules.yaml", "market_principles", "open(")
    for py in PKG.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, (py.name, token)
        modules = {n.module or "" for n in ast.walk(ast.parse(text)) if isinstance(n, ast.ImportFrom)}
        assert not any(m.endswith(("corpus.pipeline", "corpus.extraction", "corpus.inbox", "compass.market_principles")) for m in modules), py.name


def test_shadow_history_is_evidence_only_and_never_converted(bench):
    bench.shadow("pA", AGREE, reason="")
    bench.shadow("pR", DISAGREE, reason="I disagree with this recommendation strongly")
    bench.build()
    assert len(bench.decisions()) == 0
    pa, pr = bench.packet("pA"), bench.packet("pR")
    assert pa["shadow_history"]["event_count"] == 1 and pa["shadow_history"]["outcome_history"][0]["review_outcome"] == AGREE
    assert pa["decision"]["current_state"] == "NONE" and pa["decision"]["allowed_next_actions"] == [APPROVED, KEEP_REVIEWING]
    assert "W_SHADOW_DISAGREEMENT_HISTORY" in [w["code"] for w in pr["warnings"]]
    assert bench.decide("pR", "reject", REASON_REJECT, dry_run=True)["validation"]["ok"]      # 履歴は authority ではない
    for py in PKG.glob("*.py"):
        names = {a.name for n in ast.walk(ast.parse(py.read_text(encoding="utf-8"))) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert not names & {"AGREE", "DISAGREE", "NEEDS_MORE_EVIDENCE", "OUTCOMES"}, py.name


# ================================================================== 68-71 metadata / policy
def test_decision_metadata_binding_and_constraints(bench):
    bench.build()
    pk = bench.packet("pA")
    md = bench.decide("pA", "approve", REASON_OK, acknowledge_siblings=("pB",))["outcome"]["record"]["metadata"]
    assert md["packet_id"] == pk["identity"]["packet_id"] and md["packet_evidence_digest"] == pk["freshness"]["packet_evidence_digest"]
    assert md["material_digest"] == pk["freshness"]["material_digest"] and md["group_state_digest"] == pk["group"]["group_state_digest"]
    assert md["replay_run_digest"] == pk["replay"]["replay_run_digest"] and md["head_decision_id_at_packet"] == ""
    assert {k.split(":")[0] for k in md["policy_digests"].split(";")} == {"evaluation", "recommendation", "shadow_review", "replay", "decision", "formal_review"}
    assert len(md) <= 20 and all(len(v) <= 500 for v in md.values()) and len(md["metadata_payload_digest"]) == 16
    assert md["formal_review_schema_version"] == "1.0.0" and md["stability_class"] == "STABLE"


def test_policy_digest_deterministic_config_matches_and_same_version_drift_fails_closed(bench):
    assert load_formal_review_policy().digest() == FormalReviewPolicy().digest() == "cca7b43627b9a355"
    bench.build()
    with pytest.raises(FormalReviewPolicyError):
        bench.build(policy=FormalReviewPolicy(replay_evidence_age_warning_eligible_docs=7))     # 同 version で内容変更
    bench.build(policy=FormalReviewPolicy(policy_version="1.1.0", replay_evidence_age_warning_eligible_docs=7))  # bump は許可
    for bad in ({"recommendation_symmetry": False}, {"batch_actions_allowed": True}, {"promotion_boundary": "DNA_CANDIDATE"},
                {"freshness": {"stale_on_corpus_growth": True}}, {"reason": {"min_chars": {"APPROVED": 5}}},
                {"ordering": {"reject": ["pattern_id"]}}, {"duplicate_disposition": "SUPERSEDED"}):
        with pytest.raises(FormalReviewPolicyError):
            formal_review_policy_from_mapping(bad)


# ================================================================== 72-76 frozen layers
def test_frozen_layer_digests_and_decision_policy_unchanged():
    from src.intelligence.decision.policy import ALLOWED_TRANSITIONS

    assert EVAL_POLICY.digest() == "1a8443098f64d679" and REC_POLICY.digest() == "0a979d8421a01d08"
    assert SHADOW_POLICY.digest() == "e6f5094cacef6fec"
    assert REPLAY_POLICY.policy_version == "1.1.0" and REPLAY_POLICY.digest() == "197db7c73eb0db77"
    d = DECISION_POLICY.as_dict()
    assert d["formal_review_min_corpus"] == 100 and d["auto_approval"] is False and DECISION_POLICY.policy_version == "1.0.0"
    assert set(d["reason_required_states"]) == set(d["human_only_states"]) == set(ACTIONS.values())
    assert {k: set(v) for k, v in ALLOWED_TRANSITIONS.items()} == {
        None: {KEEP_REVIEWING, APPROVED, REJECTED}, KEEP_REVIEWING: {KEEP_REVIEWING, APPROVED, REJECTED},
        APPROVED: {SUPERSEDED, RETIRED}, REJECTED: {REOPENED_FOR_REVIEW},
        REOPENED_FOR_REVIEW: {KEEP_REVIEWING, APPROVED, REJECTED}, SUPERSEDED: set(), RETIRED: set()}


# ================================================================== 77-80 derived rebuild / metrics / files
def test_derived_rebuild_is_deterministic(bench):
    bench.build(); q1 = bench.service().store.queue(); p1 = {pid: bench.packet(pid) for pid in bench.service().store.packet_ids()}
    bench.build(); q2 = bench.service().store.queue(); p2 = {pid: bench.packet(pid) for pid in bench.service().store.packet_ids()}
    assert q1["sections"] == q2["sections"] and q1["context"] == q2["context"]
    for pid in p1:
        a, b = dict(p1[pid]), dict(p2[pid])
        a["identity"] = {k: v for k, v in a["identity"].items() if k != "built_at"}
        b["identity"] = {k: v for k, v in b["identity"].items() if k != "built_at"}
        assert a == b


def test_metrics_are_operational_only(bench):
    out = bench.build()
    assert_operational_only(out["metrics"])
    blob = json.dumps(out["metrics"]).lower()
    for word in ("accuracy", "precision", "hit_rate", "forecast", "predict"):
        assert word not in blob
    assert set(out["metrics"]) >= {"formal_review_candidates", "by_recommendation", "context_patterns", "pending_count", "reviewed_count",
                                   "outcomes", "stale_packet_count", "blocked_conflict_count", "acknowledged_sibling_count",
                                   "reopen_eligible_count", "median_candidate_age_eligible_docs", "replay_evidence_age_eligible_docs"}


def test_build_writes_only_derived_formal_review_files(bench):
    before = _tree_digest(bench.root)
    bench.build()
    after = _tree_digest(bench.root)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed and all(_under_logical_dir(k, "compass_formal_review") for k in changed), sorted(changed)
    assert {"compass_formal_review/build_manifest.json", "compass_formal_review/queue.json", "compass_formal_review/summary.json"} <= changed
    assert all("\\" not in k for k in changed)                                     # key は常に POSIX 形式


@pytest.mark.parametrize("key,expected", [
    ("compass_formal_review/queue.json", True),
    ("compass_formal_review\\build_manifest.json", True),                          # Windows 区切り（Linux 上でも判定できる）
    ("compass_formal_review\\packets\\cpt_x.json", True),
    ("compass_formal_review/packets/cpt_x.json", True),
    ("compass_decisions\\decisions.jsonl", False),
    ("compass_decisions/decisions.jsonl", False),
    ("other\\compass_formal_review\\x.json", False),
    ("compass_formal_review", False),
])
def test_logical_dir_check_is_separator_independent(key, expected):
    assert _under_logical_dir(key, "compass_formal_review") is expected


# ================================================================== CLI
def test_cli_commands_read_only_and_decide_exit_codes(bench, monkeypatch, capsys):
    monkeypatch.setattr(fr_cli, "FormalReviewService", lambda root, **kw: bench.service(**kw))
    root = str(bench.root)
    assert fr_cli.main(["--data-root", root, "build"]) == 0
    assert fr_cli.main(["--data-root", root, "list"]) == 0
    capsys.readouterr()
    assert fr_cli.main(["--data-root", root, "show", "pA"]) == 0
    assert fr_cli.main(["--data-root", root, "status"]) == 0 and fr_cli.main(["--data-root", root, "reopen-check"]) == 0
    pk = bench.packet("pA")["identity"]["packet_id"]
    rows_before = len(bench.decisions())
    assert fr_cli.main(["--data-root", root, "decide", "pA", "--packet", pk, "--action", "approve", "--reason", REASON_OK,
                        "--actor", "taro", "--acknowledge-sibling", "pB", "--dry-run"]) == 0
    assert len(bench.decisions()) == rows_before
    assert fr_cli.main(["--data-root", root, "decide", "pA", "--packet", pk, "--action", "approve", "--reason", REASON_OK, "--actor", "taro"]) == 3
    capsys.readouterr()
    assert fr_cli.main(["--data-root", root, "decide", "pA", "--packet", "frp_wrong", "--action", "approve", "--reason", REASON_OK,
                        "--actor", "taro", "--acknowledge-sibling", "pB"]) == 3
    assert fr_cli.main(["--data-root", root, "decide", "pA", "--packet", pk, "--action", "approve", "--reason", REASON_OK,
                        "--actor", "taro", "--acknowledge-sibling", "pB"]) == 0
    assert len(bench.decisions()) == rows_before + 1


# ================================================================== validation driver (Windows packet validation)
from src.intelligence.formal_review import validation as V  # noqa: E402

EXPECTED_DIGESTS = {"decision": DECISION_POLICY.digest(), "evaluation": "1a8443098f64d679", "recommendation": "0a979d8421a01d08",
                    "shadow_review": "e6f5094cacef6fec", "replay": "197db7c73eb0db77", "formal_review": "cca7b43627b9a355"}
MARKERS = ["HEAD", "POLICY", "BASELINE", "BUILD", "DETERMINISM", "QUEUE", "REPLAY", "FRESHNESS", "SIBLINGS", "DRY_RUN",
           "SYMMETRY", "REOPEN", "METADATA", "SAFETY", "VALIDATION_OK"]


def _validate(bench, capsys, **kw):
    params = {"expected_digests": EXPECTED_DIGESTS, "skip_git": True, "corpus_state_resolver": bench.corpus_state, "clock": bench.clock}
    params.update(kw)
    v = V.RealDataPacketValidation(bench.root, REPO_ROOT, **params)
    code = v.run_all()
    out = capsys.readouterr().out
    return code, out, v


def test_validation_driver_dress_rehearsal_markers_privacy_and_no_mutation(bench, capsys):
    bench.shadow("pA", AGREE, reason="human reason text that must never reach the console output")
    bench.shadow("pR", DISAGREE, reason="another private human reason for the disagreement record")
    before_tree = _tree_digest(bench.root, exclude="compass_formal_review")
    code, out, v = _validate(bench, capsys)
    assert code == 0, out[-2000:]
    order = [m for m in MARKERS if f"::P395_{m}::" in out]
    assert order == MARKERS and "::P395_FAIL::" not in out
    assert all(ord(ch) < 128 for ch in out)                                        # ASCII only
    assert "never reach the console" not in out and "private human reason" not in out
    assert "reason_text" not in out and str(bench.root) not in out
    assert "dry_run_pass=5" in out and "real_decisions_written=0" in out and "C3_acknowledgement_passed=2" in out
    assert "SAME_EVIDENCE_UNIVERSE=true" in out and "FIXED_INPUTS_DETERMINISM=PASS" in out and "LIVE_REBUILD_DETERMINISM=PASS" in out
    assert "reject_against_recommendation=" in out and "REJECT_AGAINST_RECOMMENDATION_BLOCKED" in out
    assert "approve_against_recommendation=" in out and "APPROVE_AGAINST_RECOMMENDATION_BLOCKED" in out
    assert "metadata_required_keys_present=True" in out and "promotion_status=NOT_PROMOTED" in out
    assert len(bench.decisions()) == 0
    assert _tree_digest(bench.root, exclude="compass_formal_review") == before_tree   # formal_review 以外は不変
    # packet 内には reason 本文があってよいが console には出ない
    assert bench.packet("pA")["shadow_history"]["outcome_history"][0]["reason"].startswith("human reason")


def test_validation_driver_fails_closed_on_policy_digest_mismatch_before_build(bench, capsys):
    v = V.RealDataPacketValidation(bench.root, REPO_ROOT, expected_digests={**EXPECTED_DIGESTS, "formal_review": "0000000000000000"},
                                   skip_git=True, corpus_state_resolver=bench.corpus_state, clock=bench.clock)
    code = v.run_all()
    out = capsys.readouterr().out
    assert code == 4 and "::P395_FAIL::" in out and "section=POLICY" in out and "::P395_BUILD::" not in out
    assert not bench.service().store.exists()


def test_validation_driver_fails_on_unexpected_guard_result(bench, capsys):
    bench.eligible = 99                                                                # live gate below CORPUS_100
    code, out, _ = _validate(bench, capsys)
    assert code == 4 and "section=DRY_RUN" in out and "FORMAL_GATE_NOT_REACHED" in out


def test_validation_driver_reports_replay_evidence_required_as_legitimate(tmp_path, capsys):
    b = Bench(tmp_path, with_replay=False)
    code, out, _ = _validate(b, capsys)
    assert code == 0 and "REPLAY_EVIDENCE_REQUIRED" in out and "dry_run_pass=0" in out
    assert '"legitimate":true' in out and "replay_incompatible_candidates=5" in out


def test_validation_driver_corpus_only_growth_keeps_dry_run_valid(bench, capsys):
    class Growing:
        def __init__(self, bench):
            self.bench, self.calls = bench, 0

        def __call__(self):
            self.calls += 1
            if self.calls > 3:                                                          # build 後に eligible が増える
                self.bench.eligible = 141
            return self.bench.corpus_state()

    code, out, _ = _validate(bench, capsys, corpus_state_resolver=Growing(bench))
    assert code == 0 and "dry_run_pass=5" in out
    assert "corpus_eligible_before_after=[139,141]" in out


def test_validation_driver_stale_during_sweep_is_legitimate_only_with_intake(bench, capsys, monkeypatch):
    bench.build()
    real_decide = FormalReviewService.decide
    state = {"done": False}

    def mutate_then_decide(self, request, *, dry_run):
        if not state["done"]:                                                           # 最初の dry-run 直前に evidence が変わる
            state["done"] = True
            bench.evals["pR"]["axis_metrics"][A_TIME]["span_days"] = 200
            bench.write_evaluations()
        return real_decide(self, request, dry_run=dry_run)

    monkeypatch.setattr(FormalReviewService, "decide", mutate_then_decide)
    code, out, _ = _validate(bench, capsys)                                              # intake なし → stale は unexpected
    assert code == 4 and "PACKET_EVIDENCE_DIGEST_CHANGED" in out and "section=DRY_RUN" in out


def test_validation_driver_replay_age_warning_and_c3_are_reported(tmp_path, capsys):
    b = Bench(tmp_path, replay_captured=134)
    code, out, _ = _validate(b, capsys)
    assert code == 0 and "W_REPLAY_EVIDENCE_AGE" in out and "C3_acknowledgement_required=2" in out
    assert "replay_evidence_age_eligible_docs=5" in out


def test_validation_cli_main_arguments_and_exit_code(bench, monkeypatch, capsys):
    monkeypatch.setattr(V, "RealDataPacketValidation", lambda root, repo, **kw: _Injected(root, repo, bench, **kw))
    code = V.main(["--data-root", str(bench.root), "--skip-git", "--expect-formal-review", "cca7b43627b9a355",
                   "--expect-evaluation", "1a8443098f64d679"])
    out = capsys.readouterr().out
    assert code == 0 and "::P395_VALIDATION_OK::" in out and "formal_review_expected=cca7b43627b9a355" in out
    monkeypatch.setattr(V, "RealDataPacketValidation", lambda root, repo, **kw: _Injected(root, repo, bench, **kw))
    assert V.main(["--data-root", str(bench.root), "--skip-git", "--expect-replay", "badbadbadbadbad0"]) == 4


class _Injected(V.RealDataPacketValidation):
    def __init__(self, root, repo, bench, **kw):
        super().__init__(root, repo, corpus_state_resolver=bench.corpus_state, clock=bench.clock, **kw)


def test_fresh_compatible_replay_run_recovers_compatibility_and_dry_runs(bench):
    """Windows follow-up の再現: 旧 replay policy の run しか無い → 非互換 → 現行 policy の新 run が latest になると互換。"""
    bench.replay_policy_digests = {"evaluation": EVAL_POLICY.digest(), "recommendation": REC_POLICY.digest(),
                                   "shadow_review": SHADOW_POLICY.digest(), "replay": "d205c3763d07111b"}   # 旧 1.0.0 digest
    bench.write_replay(); bench.build()
    stale = bench.packet("pA")["replay"]
    assert stale["current_compatible"] is False and stale["compatibility_reasons"] == ["POLICY_DIGEST_MISMATCH:replay"]
    with pytest.raises(ReplayEvidenceRequired):
        bench.decide("pA", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pB",))
    manifest = bench.service().store.manifest()["inputs"]
    assert manifest["replay_run_policy_digests"]["replay"] == "d205c3763d07111b"
    # 現行 policy（1.1.0 / 197db7c73eb0db77）で最小の MILESTONE_AND_TRANSITION 相当の新 run を書く → latest.json が更新される
    bench.replay_policy_digests = None
    bench.write_replay(); bench.build()
    fresh = bench.packet("pA")["replay"]
    assert fresh["current_compatible"] is True and fresh["compatibility_reasons"] == []
    assert bench.service().store.manifest()["inputs"]["replay_run_policy_digests"]["replay"] == REPLAY_POLICY.digest()
    assert bench.decide("pA", "approve", REASON_OK, dry_run=True, acknowledge_siblings=("pB",))["validation"]["ok"]
    assert len(bench.decisions()) == 0
