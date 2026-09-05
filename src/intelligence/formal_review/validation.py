"""Phase 3.9.5 real-data packet validation（Windows 実機を 1 操作で検証する fail-closed driver）。

`python -m src.intelligence.formal_review.validation --require-commit <sha> --expect-<layer> <digest> ...`

書くのは `<data_root>/compass_formal_review/`（derived・rebuildable）だけ。formal Decision は **書かない**
（全 candidate を dry-run するだけ）。人間の Shadow Review reason 本文・原文・ファイル名・path は出力しない。
出力は ASCII の key=value 行と `::P395_*::` marker。各節で結果を明示的に検査し、材料となる失敗があれば
`::P395_FAIL::` で止まる。exit 0 = ok / 3 = FormalReviewError / 4 = validation failure・store corrupt / 5 = unexpected。
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..corpus.store import corpus_root
from ..corpus_research.store import research_root
from ..decision.corpus_state import CorpusState
from ..decision.models import MAX_METADATA_KEYS, MAX_METADATA_VALUE_CHARS
from ..decision.store import DECISIONS_FILE, DecisionStoreCorrupt, decisions_root
from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED
from ..evaluation.store import EvaluationStore, EvaluationStoreCorrupt, evaluation_root
from ..replay.snapshot import live_corpus_observation
from ..replay.validation import (  # 既存の read-only identity helper を再利用（path 名は出力しない）
    DNA_FILES,
    _dir_digest as dir_digest,
    _file_identity as file_identity,
    _git as git,
    _pdf_digest as pdf_digest,
)
from ..shadow_review.events import EVENTS_FILE as REVIEW_EVENTS_FILE, ShadowReviewStoreCorrupt, shadow_review_root
from ..shadow_review.models import find_forbidden_keys
from .config import APPROVED, KEEP_REVIEWING, REJECTED, FormalReviewPolicy
from .errors import FormalReviewError
from .groups import build_groups, opposite_members
from .guard import evidence_diff
from .ordering import SECTION_APPROVE, SECTION_REJECT, SECTION_REOPEN
from .packet import digest16
from .service import FormalDecisionRequest, FormalReviewService
from .store import BUILD_MANIFEST_FILE, QUEUE_FILE, SUMMARY_FILE, formal_review_root

EXIT_OK, EXIT_FORMAL_REVIEW, EXIT_VALIDATION, EXIT_UNEXPECTED = 0, 3, 4, 5
VALIDATION_ACTOR = "P395_VALIDATION"
REASON_APPROVE = "P395 validation dry-run of the packet-bound approval path; no decision is written by this run."
REASON_REJECT = "P395 validation dry-run of the packet-bound rejection path; no decision is written by this run."
REASON_KEEP = "P395 validation dry-run of the keep-reviewing path; nothing is written."
LEGIT_ALWAYS = ("REPLAY_EVIDENCE_REQUIRED", "SIBLING_CONFLICT_BLOCKED")
LEGIT_WITH_INTAKE = ("STALE_REVIEW_PACKET", "RECOMMENDATION_MISMATCH", "MATERIAL_DIGEST_CHANGED",
                     "PACKET_EVIDENCE_DIGEST_CHANGED", "DECISION_HEAD_CHANGED")
REQUIRED_BLOCKS = ("identity", "recommendation", "axes", "reference", "consistency", "dna", "replay", "shadow_history",
                   "decision", "group", "freshness", "warnings")
REQUIRED_METADATA_KEYS = ("packet_id", "packet_evidence_digest", "material_digest", "recommendation", "policy_digests",
                          "replay_run_id", "replay_run_digest", "group_state_digest", "stability_class",
                          "formal_review_schema_version", "corpus_eligible_at_packet", "corpus_eligible_at_write",
                          "head_decision_id_at_packet", "metadata_payload_digest")
POLICY_LAYERS = ("decision", "evaluation", "recommendation", "shadow_review", "replay", "formal_review")


class ValidationFailure(Exception):
    def __init__(self, section: str, reason: str) -> None:
        super().__init__(f"{section}: {reason}")
        self.section = section
        self.reason = reason


def _emit(key: str, value: Any) -> None:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    print(f"{key}={value}", flush=True)


def _marker(name: str) -> None:
    print(f"::P395_{name}::", flush=True)


def _safe_row(packet: Mapping[str, Any], rank: int, section: str) -> Dict[str, Any]:
    """console へ出してよい candidate 要約（reason 本文・原文・path なし）。"""
    replay = dict(packet.get("replay") or {})
    return {"queue_rank": rank, "section": section, "pattern_id": packet["identity"]["pattern_id"],
            "pattern_type": packet["identity"]["pattern_type"], "recommendation": packet["recommendation"]["recommendation"],
            "lifecycle": packet["identity"]["lifecycle_status"], "stability_class": replay.get("stability_class", ""),
            "warnings": [w["code"] for w in packet.get("warnings") or []],
            "eligible_support": packet["axes"]["eligible_support"],
            "first_recommendation_position": replay.get("first_recommendation_position"),
            "sibling_context_count": len(packet["group"].get("members") or []),
            "allowed_actions": list(packet["decision"]["allowed_next_actions"])}


class RealDataPacketValidation:
    def __init__(self, data_root: Path, repo_root: Path, *, require_commit: str = "",
                 expected_digests: Optional[Mapping[str, str]] = None, skip_git: bool = False,
                 corpus_state_resolver: Optional[Callable[[], CorpusState]] = None,
                 clock: Optional[Callable[[], datetime]] = None, policy: Optional[FormalReviewPolicy] = None) -> None:
        self.data_root = Path(data_root)
        self.repo = Path(repo_root)
        self.require_commit = require_commit
        self.expected = dict(expected_digests or {})
        self.skip_git = skip_git
        self.resolver = corpus_state_resolver
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.policy = policy
        self.t0 = time.perf_counter()
        self.baseline: Dict[str, Any] = {}
        self.tracked_before = ""
        self.build_a: Dict[str, Any] = {}
        self.queue: Dict[str, Any] = {}
        self.packets: Dict[str, Dict[str, Any]] = {}
        self.primary: List[str] = []
        self.dry_results: Dict[str, Dict[str, Any]] = {}
        self.first_pass_metadata: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------- generic
    def fail(self, section: str, reason: str) -> None:
        raise ValidationFailure(section, reason)

    def check(self, section: str, cond: bool, reason: str) -> None:
        if not cond:
            self.fail(section, reason)

    def service(self) -> FormalReviewService:
        kw: Dict[str, Any] = {"clock": self.clock}
        if self.resolver is not None:
            kw["corpus_state_resolver"] = self.resolver
        if self.policy is not None:
            kw["policy"] = self.policy
        return FormalReviewService(self.data_root, **kw)

    def _corpus_counts(self) -> Dict[str, Any]:
        croot = corpus_root(self.data_root)
        live = live_corpus_observation(croot) if (croot / "index" / "corpus.sqlite3").is_file() else {}
        state = self.service().corpus_state_resolver()
        return {"documents": live.get("documents", state.documents), "eligible": int(state.eligible),
                "milestone": state.milestone, "source": state.source}

    def _evidence_universe(self) -> Dict[str, str]:
        """candidate 証拠の入力宇宙 identity（evaluation store 全体 + research patterns + decision / shadow store）。"""
        estore = EvaluationStore(evaluation_root(self.data_root))
        return {"evaluation": estore.derived_digest()[:16] if estore.exists() else "",
                "patterns": file_identity(research_root(self.data_root) / "patterns.jsonl")["sha256"],
                "decisions": file_identity(decisions_root(self.data_root) / DECISIONS_FILE)["sha256"],
                "review_events": file_identity(shadow_review_root(self.data_root) / REVIEW_EVENTS_FILE)["sha256"]}

    # ------------------------------------------------------------- sections
    def head(self) -> None:
        _marker("HEAD")
        if self.skip_git:
            _emit("git", "SKIPPED")
        else:
            code, head = git(self.repo, "rev-parse", "HEAD")
            self.check("HEAD", code == 0 and bool(head), "git rev-parse HEAD failed")
            _emit("head", head)
            _emit("branch", git(self.repo, "rev-parse", "--abbrev-ref", "HEAD")[1])
            if self.require_commit:
                code, _ = git(self.repo, "merge-base", "--is-ancestor", self.require_commit, "HEAD")
                _emit("required_commit", self.require_commit)
                _emit("head_contains_required_commit", "YES" if code == 0 else "NO")
                self.check("HEAD", code == 0, "HEAD does not contain the required commit")
            code, status = git(self.repo, "status", "--porcelain", "--untracked-files=no")
            self.check("HEAD", code == 0, "git status failed")
            self.tracked_before = status
            _emit("tracked_worktree_clean", "YES" if not status else "NO")
            self.check("HEAD", not status, "tracked working tree is not clean")
            for ref in ("origin/main", "main"):
                code, _ = git(self.repo, "rev-parse", "--verify", "--quiet", ref)
                if code != 0:
                    _emit(f"{ref}_contains_head", "ABSENT")
                    continue
                code, _ = git(self.repo, "merge-base", "--is-ancestor", "HEAD", ref)
                _emit(f"{ref}_contains_head", "YES" if code == 0 else "NO")
                self.check("HEAD", code != 0, f"{ref} already contains HEAD (main merged)")
        _emit("data_root_leaf", self.data_root.name)
        _emit("data_root_exists", self.data_root.is_dir())
        db = corpus_root(self.data_root) / "index" / "corpus.sqlite3"
        _emit("corpus_index_exists", db.is_file())
        if self.resolver is None:
            self.check("HEAD", db.is_file(), "production corpus index not found")
        _emit("evaluation_store_exists", EvaluationStore(evaluation_root(self.data_root)).exists())
        self.check("HEAD", EvaluationStore(evaluation_root(self.data_root)).exists(), "evaluation store not found")

    def policy_section(self) -> None:
        _marker("POLICY")
        svc = self.service()
        digests, versions = svc.policy_digests(), svc.policy_versions()
        for layer in POLICY_LAYERS:
            _emit(f"{layer}_version", versions[layer])
            _emit(f"{layer}_digest", digests[layer])
            want = self.expected.get(layer, "")
            if want:
                _emit(f"{layer}_expected", want)
                self.check("POLICY", digests[layer] == want, f"{layer} digest {digests[layer]} != expected {want}")
        _emit("formal_review_policy_frozen", {"recommendation_symmetry": svc.policy.recommendation_symmetry,
                                             "sibling_guard_mode": svc.policy.sibling_guard_mode,
                                             "batch_actions_allowed": svc.policy.batch_actions_allowed,
                                             "promotion_boundary": svc.policy.promotion_boundary})
        _emit("policy_check", "PASSED")

    def _capture(self) -> Dict[str, Any]:
        dna = {}
        if not self.skip_git:
            for rel in DNA_FILES:
                _, blob = git(self.repo, "rev-parse", f"HEAD:{rel}")
                code, _ = git(self.repo, "diff", "--quiet", "HEAD", "--", rel)
                dna[rel] = {"head_blob": blob[:16], "match": code == 0}
        return {"decisions": file_identity(decisions_root(self.data_root) / DECISIONS_FILE),
                "review_events": file_identity(shadow_review_root(self.data_root) / REVIEW_EVENTS_FILE),
                "dna": dna, "pdfs": pdf_digest(self.data_root),
                "derived_research": dir_digest(research_root(self.data_root)),
                "derived_evaluation": dir_digest(evaluation_root(self.data_root)),
                "derived_shadow_review": dir_digest(shadow_review_root(self.data_root)),
                "formal_review": dir_digest(formal_review_root(self.data_root)),
                "corpus": self._corpus_counts(), "universe": self._evidence_universe()}

    def baseline_section(self) -> None:
        _marker("BASELINE")
        self.baseline = self._capture()
        for key, value in self.baseline.items():
            _emit(key, value)
        self.check("BASELINE", all(v["match"] for v in self.baseline["dna"].values()) or self.skip_git,
                   "DNA working tree differs from HEAD before validation")
        _emit("baseline_check", "PASSED")

    def build_section(self) -> None:
        _marker("BUILD")
        svc = self.service()
        t0 = time.perf_counter()
        out = svc.build()
        _emit("build_seconds", round(time.perf_counter() - t0, 3))
        self.build_a = out
        store = svc.store
        self.queue = store.queue()
        manifest = store.manifest()
        summary = store.summary()
        self.packets = {pid: store.packet(pid) for pid in store.packet_ids()}
        sections = self.queue.get("sections") or {}
        self.primary = [r["pattern_id"] for name in (SECTION_REJECT, SECTION_APPROVE) for r in sections.get(name, [])]
        pop = manifest.get("population") or {}
        _emit("corpus_documents", (manifest.get("corpus") or {}).get("documents"))
        _emit("corpus_eligible", (manifest.get("corpus") or {}).get("eligible"))
        _emit("primary_candidates", len(self.primary))
        _emit("approve_candidates", pop.get("by_recommendation", {}).get(APPROVE_RECOMMENDED, 0))
        _emit("reject_candidates", pop.get("by_recommendation", {}).get(REJECT_RECOMMENDED, 0))
        _emit("reopen_candidates", len(pop.get("reopen_eligible") or []))
        _emit("context_patterns", len(pop.get("context") or []))
        _emit("decided_patterns", len(pop.get("decided") or []))
        _emit("excluded_not_ready", pop.get("excluded_not_ready"))
        _emit("queue_section_counts", {k: len(v) for k, v in sections.items()})
        _emit("formal_review_policy", (manifest.get("policies") or {}).get("formal_review"))
        inputs = manifest.get("inputs") or {}
        _emit("replay_run_digest_used", inputs.get("replay_run_digest"))
        _emit("replay_captured_eligible", inputs.get("replay_captured_eligible"))
        _emit("replay_evidence_age_eligible_docs", (summary.get("metrics") or {}).get("replay_evidence_age_eligible_docs"))
        _emit("packets_built", len(self.packets))
        # explicit checks（exit code だけに頼らない）
        found = find_forbidden_keys(self.queue) + find_forbidden_keys(summary) + find_forbidden_keys(manifest)
        for pid, packet in self.packets.items():
            found += find_forbidden_keys(packet)
            self.check("BUILD", all(block in packet for block in REQUIRED_BLOCKS), f"packet schema incomplete for {pid}")
            self.check("BUILD", bool(packet["freshness"]["packet_evidence_digest"]), f"packet_evidence_digest missing for {pid}")
            self.check("BUILD", bool(packet["freshness"]["material_digest"]), f"material_digest missing for {pid}")
            if packet["group"]["sibling_group_key"]:
                self.check("BUILD", bool(packet["group"]["group_state_digest"]), f"group_state_digest missing for {pid}")
            replay = packet["replay"]
            self.check("BUILD", "available" in replay and ("replay_run_digest" in replay or replay.get("available") is False),
                       f"replay block malformed for {pid}")
        self.check("BUILD", not found, f"forbidden keys in derived output: {sorted(set(found))}")
        _emit("forbidden_key_scan", "CLEAN")
        after = self._capture()
        self.check("BUILD", after["decisions"] == self.baseline["decisions"], "decision store changed during build")
        _emit("decision_store_unchanged_by_build", True)
        _emit("build_check", "PASSED")

    def _semantic_queue_digest(self, queue: Mapping[str, Any]) -> str:
        return digest16({k: [{f: r.get(f) for f in r if f != "warnings"} for r in rows] for k, rows in (queue.get("sections") or {}).items()})

    def determinism_section(self) -> None:
        _marker("DETERMINISM")
        first_ids = {k: [r["pattern_id"] for r in v] for k, v in (self.queue.get("sections") or {}).items()}
        first_digests = {pid: (p["freshness"]["packet_evidence_digest"], p["group"]["group_state_digest"]) for pid, p in self.packets.items()}
        first_q = self._semantic_queue_digest(self.queue)
        universe_before = self.baseline["universe"]
        svc = self.service()
        svc.build()
        queue_b = svc.store.queue()
        packets_b = {pid: svc.store.packet(pid) for pid in svc.store.packet_ids()}
        second_ids = {k: [r["pattern_id"] for r in v] for k, v in (queue_b.get("sections") or {}).items()}
        second_digests = {pid: (p["freshness"]["packet_evidence_digest"], p["group"]["group_state_digest"]) for pid, p in packets_b.items()}
        universe_after = self._evidence_universe()
        same_universe = universe_before == universe_after
        _emit("SAME_EVIDENCE_UNIVERSE", "true" if same_universe else "false")
        _emit("candidate_set_match", first_ids == second_ids)
        _emit("packet_evidence_digests_match", first_digests == second_digests)
        _emit("queue_semantic_digest_first", first_q)
        _emit("queue_semantic_digest_second", self._semantic_queue_digest(queue_b))
        if same_universe:
            self.check("DETERMINISM", first_ids == second_ids and first_digests == second_digests
                       and first_q == self._semantic_queue_digest(queue_b), "same evidence universe but derived output differs")
            _emit("LIVE_REBUILD_DETERMINISM", "PASS")
        else:
            _emit("LIVE_REBUILD_DETERMINISM", "NOT_COMPARABLE (live intake changed the evidence universe)")
        # 固定入力での決定性（read-consistent path）: 同じ load_inputs() から 2 回 packet を組み立てる
        inputs = svc.load_inputs()
        groups = build_groups(inputs.pattern_records)
        ids = sorted(self.packets)
        one = {pid: svc.assemble_packet(pid, inputs, groups, built_at="") for pid in ids if pid in inputs.evaluations}
        two = {pid: svc.assemble_packet(pid, inputs, groups, built_at="") for pid in ids if pid in inputs.evaluations}
        fixed = all(one[p]["freshness"]["packet_evidence_digest"] == two[p]["freshness"]["packet_evidence_digest"]
                    and one[p]["identity"]["packet_id"] == two[p]["identity"]["packet_id"] for p in one)
        _emit("FIXED_INPUTS_DETERMINISM", "PASS" if fixed else "FAIL")
        self.check("DETERMINISM", fixed, "packet assembly is not deterministic on fixed inputs")
        # 以降の節は最新 build（B）の queue / packet を使う
        self.queue, self.packets = queue_b, packets_b
        sections = self.queue.get("sections") or {}
        self.primary = [r["pattern_id"] for name in (SECTION_REJECT, SECTION_APPROVE) for r in sections.get(name, [])]
        _emit("determinism_check", "PASSED")

    def queue_section(self) -> None:
        _marker("QUEUE")
        for name in (SECTION_REJECT, SECTION_APPROVE, SECTION_REOPEN):
            for row in (self.queue.get("sections") or {}).get(name, []):
                _emit("candidate", _safe_row(self.packets[row["pattern_id"]], row["queue_rank"], name))
        _emit("context", [{"pattern_id": c["pattern_id"], "recommendation": c["recommendation"], "role": c["role"]}
                          for c in self.queue.get("context") or []])
        _emit("decided", [{"pattern_id": d["pattern_id"], "decision_state": d["decision_state"], "allowed_actions": d["allowed_next_actions"]}
                          for d in self.queue.get("decided") or []])
        _emit("queue_check", "PASSED")

    def replay_section(self) -> None:
        _marker("REPLAY")
        compatible = 0
        for pid in self.primary:
            replay = dict(self.packets[pid].get("replay") or {})
            ok = bool(replay.get("available") and replay.get("current_compatible"))
            compatible += 1 if ok else 0
            _emit("replay", {"pattern_id": pid, "replay_compatible": ok,
                             "replay_evidence_age_eligible_docs": replay.get("evidence_age_eligible_docs"),
                             "stability_class": replay.get("stability_class", ""), "persistence_ratio": replay.get("persistence_ratio"),
                             "reversal_count": replay.get("reversal_count"),
                             "reasons": replay.get("compatibility_reasons") or ([replay.get("reason")] if not replay.get("available") else [])})
        _emit("replay_compatible_candidates", compatible)
        _emit("replay_incompatible_candidates", len(self.primary) - compatible)
        _emit("replay_note", "incompatible or missing replay evidence fails APPROVED/REJECTED dry-run as REPLAY_EVIDENCE_REQUIRED; no replay is generated here")

    def freshness_section(self) -> None:
        _marker("FRESHNESS")
        svc = self.service()
        inputs = svc.load_inputs()
        fresh_count = 0
        for pid in self.primary:
            reviewed = self.packets[pid]
            if pid not in inputs.evaluations:
                _emit("freshness", {"pattern_id": pid, "fresh": False, "changed_blocks": ["EVALUATION_MISSING"]})
                continue
            current = svc.current_packet(pid, inputs)
            fresh = current["freshness"]["packet_evidence_digest"] == reviewed["freshness"]["packet_evidence_digest"]
            fresh_count += 1 if fresh else 0
            _emit("freshness", {"pattern_id": pid, "material_digest_present": bool(reviewed["freshness"]["material_digest"]),
                                "packet_evidence_digest_present": bool(reviewed["freshness"]["packet_evidence_digest"]),
                                "fresh": fresh, "changed_blocks": [] if fresh else evidence_diff(reviewed, current)})
        _emit("fresh_candidates", fresh_count)
        _emit("stale_candidates", len(self.primary) - fresh_count)

    def _acknowledgements(self, packet: Mapping[str, Any]) -> List[str]:
        return sorted(m["pattern_id"] for m in opposite_members(dict(packet.get("group") or {}))
                      if m.get("recommendation") == APPROVE_RECOMMENDED and m.get("decision_state", "") in ("", KEEP_REVIEWING, "REOPENED_FOR_REVIEW"))

    def siblings_section(self) -> None:
        _marker("SIBLINGS")
        svc = self.service()
        inputs = svc.load_inputs()
        groups = build_groups(inputs.pattern_records)
        multi = sum(1 for members in groups.values() if len(members) > 1)
        opposite = c1 = c3 = 0
        for pid in self.primary:
            packet = self.packets[pid]
            opp = opposite_members(dict(packet.get("group") or {}))
            opposite += 1 if opp else 0
            if packet["recommendation"]["recommendation"] == APPROVE_RECOMMENDED:
                c1 += 1 if any(m.get("decision_state") == APPROVED for m in opp) else 0
                c3 += 1 if self._acknowledgements(packet) else 0
        _emit("groups_with_multiple_members", multi)
        _emit("candidates_with_opposite_siblings", opposite)
        _emit("C1_blocks", c1)
        _emit("C3_acknowledgement_required", c3)
        _emit("sibling_relation", "EVIDENCE_OUTLOOK_NARROW_SIBLING (not widened)")
        _emit("C1_mode", "HARD_BLOCK_NO_OVERRIDE")
        _emit("C3_mode", "EXPLICIT_ACKNOWLEDGEMENT_REQUIRED")

    def dry_run_section(self) -> None:
        _marker("DRY_RUN")
        svc = self.service()
        intake_seen = self._corpus_counts().get("documents") != self.baseline["corpus"].get("documents") \
            or self._evidence_universe()["evaluation"] != self.baseline["universe"]["evaluation"]
        passed = c3_passed = legit = 0
        outcomes: Dict[str, int] = {}
        for pid in self.primary:
            packet = self.packets[pid]
            rec = packet["recommendation"]["recommendation"]
            action = "approve" if rec == APPROVE_RECOMMENDED else "reject"
            acks = self._acknowledgements(packet) if action == "approve" else []
            request = FormalDecisionRequest(pattern_id=pid, action=action, packet_id=packet["identity"]["packet_id"],
                                            reason=REASON_APPROVE if action == "approve" else REASON_REJECT,
                                            actor=VALIDATION_ACTOR, acknowledge_siblings=tuple(acks))
            try:
                result = svc.decide(request, dry_run=True)
            except FormalReviewError as exc:
                code = exc.code
                legit_now = code in LEGIT_ALWAYS or (code in LEGIT_WITH_INTAKE and intake_seen)
                outcomes[code] = outcomes.get(code, 0) + 1
                _emit("dry_run", {"pattern_id": pid, "action": action, "result": code, "legitimate": legit_now,
                                  "acknowledged": acks, "intake_observed": intake_seen})
                self.check("DRY_RUN", legit_now, f"unexpected guard result {code} for {pid}")
                legit += 1
                self.dry_results[pid] = {"result": code}
                continue
            self.check("DRY_RUN", result["mutation"] == "NONE (dry run)", f"dry-run reported a mutation for {pid}")
            self.check("DRY_RUN", bool(result["validation"]["ok"]),
                       f"DecisionService.validate rejected the dry-run for {pid}: {[e.get('code') for e in result['validation']['errors']]}")
            passed += 1
            c3_passed += 1 if acks else 0
            outcomes["DRY_RUN_PASS"] = outcomes.get("DRY_RUN_PASS", 0) + 1
            if self.first_pass_metadata is None:
                self.first_pass_metadata = dict(result["metadata"])
            self.dry_results[pid] = {"result": "DRY_RUN_PASS", "metadata_keys": len(result["metadata"])}
            _emit("dry_run", {"pattern_id": pid, "action": action, "result": "DRY_RUN_PASS", "acknowledged": acks,
                              "checks_passed": len(result["guard"]["checks_passed"]),
                              "formal_gate_reached": bool(packet["recommendation"]["formal_review_gate_reached"])})
        _emit("dry_run_pass", passed)
        _emit("dry_run_legitimate_guard_results", legit)
        _emit("dry_run_outcomes", outcomes)
        _emit("C3_acknowledgement_passed", c3_passed)
        _emit("real_decisions_written", 0)
        _emit("dry_run_check", "PASSED")

    def symmetry_section(self) -> None:
        _marker("SYMMETRY")
        svc = self.service()
        approve = next((p for p in self.primary if self.packets[p]["recommendation"]["recommendation"] == APPROVE_RECOMMENDED), None)
        reject = next((p for p in self.primary if self.packets[p]["recommendation"]["recommendation"] == REJECT_RECOMMENDED), None)
        for pid, action, expected in ((approve, "reject", "REJECT_AGAINST_RECOMMENDATION_BLOCKED"),
                                      (reject, "approve", "APPROVE_AGAINST_RECOMMENDATION_BLOCKED")):
            if pid is None:
                _emit(f"{action}_against_recommendation", "SKIPPED_NO_CANDIDATE (covered by synthetic tests)")
                continue
            try:
                svc.decide(FormalDecisionRequest(pid, action, self.packets[pid]["identity"]["packet_id"],
                                                 REASON_REJECT if action == "reject" else REASON_APPROVE, VALIDATION_ACTOR), dry_run=True)
                self.fail("SYMMETRY", f"{action} against recommendation was not blocked for {pid}")
            except FormalReviewError as exc:
                _emit(f"{action}_against_recommendation", {"pattern_id": pid, "result": exc.code})
                self.check("SYMMETRY", exc.code == expected, f"expected {expected}, got {exc.code}")
        target = approve or reject
        if target is not None:
            try:
                result = svc.decide(FormalDecisionRequest(target, "keep-reviewing", self.packets[target]["identity"]["packet_id"],
                                                          REASON_KEEP, VALIDATION_ACTOR), dry_run=True)
                _emit("keep_reviewing_disagreement_path", {"pattern_id": target, "result": "DRY_RUN_PASS" if result["validation"]["ok"] else "VALIDATION_FAILED",
                                                           "mutation": result["mutation"]})
                self.check("SYMMETRY", result["validation"]["ok"] and result["mutation"] == "NONE (dry run)", "KEEP_REVIEWING dry-run failed")
            except FormalReviewError as exc:
                intake_seen = self._corpus_counts().get("documents") != self.baseline["corpus"].get("documents")
                _emit("keep_reviewing_disagreement_path", {"pattern_id": target, "result": exc.code})
                self.check("SYMMETRY", exc.code in LEGIT_WITH_INTAKE and intake_seen, f"KEEP_REVIEWING dry-run blocked: {exc.code}")
        _emit("symmetry_check", "PASSED")

    def reopen_section(self) -> None:
        _marker("REOPEN")
        rows = self.service().reopen_check()
        _emit("rejected_decisions", len(rows))
        _emit("reopen_eligible", sum(1 for r in rows if r.get("eligible")))
        _emit("unverifiable", sum(1 for r in rows if r.get("status") == "UNVERIFIABLE_NO_PACKET_BINDING"))
        _emit("material_change_detected", sum(1 for r in rows if r.get("status") == "REOPEN_ELIGIBLE"))
        _emit("reopened_written", 0)
        _emit("reopen_check", "PASSED")

    def metadata_section(self) -> None:
        _marker("METADATA")
        md = self.first_pass_metadata
        if md is None:
            _emit("metadata", "NO_DRY_RUN_PASS (no candidate reached the metadata binder)")
            return
        missing = [k for k in REQUIRED_METADATA_KEYS if k not in md]
        layers = {part.split(":")[0] for part in md.get("policy_digests", "").split(";") if part}
        _emit("metadata_key_count", len(md))
        _emit("metadata_required_keys_present", not missing)
        _emit("metadata_missing_keys", missing)
        _emit("metadata_values_within_500", all(len(v) <= MAX_METADATA_VALUE_CHARS for v in md.values()))
        _emit("metadata_policy_layers_bound", sorted(layers))
        _emit("metadata_replay_binding_present", bool(md.get("replay_run_digest")))
        _emit("metadata_group_binding_present", "group_state_digest" in md)
        _emit("metadata_corpus_eligible_build_write", [md.get("corpus_eligible_at_packet"), md.get("corpus_eligible_at_write")])
        _emit("promotion_status", "NOT_PROMOTED")
        self.check("METADATA", len(md) <= MAX_METADATA_KEYS and not missing and layers == set(POLICY_LAYERS), "decision metadata binding incomplete")
        _emit("metadata_check", "PASSED")

    def safety_section(self) -> None:
        _marker("SAFETY")
        after = self._capture()
        before = self.baseline
        for key in ("decisions", "review_events"):
            same = before[key] == after[key]
            _emit(f"{key}_before", before[key])
            _emit(f"{key}_after", after[key])
            _emit(f"{key}_unchanged", same)
            self.check("SAFETY", same, f"{key} changed during validation")
        dna_ok = self.skip_git or (after["dna"] == before["dna"] and all(v["match"] for v in after["dna"].values()))
        _emit("dna_blob_unchanged", dna_ok)
        self.check("SAFETY", dna_ok, "DNA blob identity changed")
        _emit("pdf_inventory_unchanged", before["pdfs"] == after["pdfs"])
        self.check("SAFETY", before["pdfs"] == after["pdfs"], "PDF inventory changed")
        growth = int(after["corpus"].get("documents") or 0) - int(before["corpus"].get("documents") or 0)
        intake = growth > 0 or before["universe"] != after["universe"]
        _emit("corpus_documents_before_after", [before["corpus"].get("documents"), after["corpus"].get("documents")])
        _emit("corpus_eligible_before_after", [before["corpus"].get("eligible"), after["corpus"].get("eligible")])
        _emit("intake_activity_observed", intake)
        for key in ("derived_research", "derived_evaluation", "derived_shadow_review"):
            changed = before[key] != after[key]
            verdict = "NONE" if not changed else ("INTAKE_ATTRIBUTED" if intake else "UNEXPECTED")
            _emit(f"{key}_change", verdict)
            self.check("SAFETY", verdict != "UNEXPECTED", f"{key} changed without intake activity")
        _emit("formal_review_derived_changed", before["formal_review"] != after["formal_review"])
        root = formal_review_root(self.data_root)
        expected_files = {BUILD_MANIFEST_FILE, QUEUE_FILE, SUMMARY_FILE}
        present = {p.name for p in root.iterdir()} if root.is_dir() else set()
        _emit("formal_review_files", sorted(present))
        self.check("SAFETY", expected_files <= present and present <= expected_files | {"packets"},
                   "unexpected files under compass_formal_review (no second truth store allowed)")
        _emit("second_truth_store", "NONE")
        _emit("formal_decisions_written", 0)
        if not self.skip_git:
            code, status = git(self.repo, "status", "--porcelain", "--untracked-files=no")
            _emit("tracked_worktree_unchanged", code == 0 and status == self.tracked_before)
            self.check("SAFETY", code == 0 and status == self.tracked_before, "tracked working tree changed")
        _emit("safety_check", "PASSED")

    # ------------------------------------------------------------- orchestration
    def run_all(self) -> int:
        try:
            self.head()
            self.policy_section()
            self.baseline_section()
            self.build_section()
            self.determinism_section()
            self.queue_section()
            self.replay_section()
            self.freshness_section()
            self.siblings_section()
            self.dry_run_section()
            self.symmetry_section()
            self.reopen_section()
            self.metadata_section()
            self.safety_section()
            _marker("VALIDATION_OK")
            _emit("total_validation_seconds", round(time.perf_counter() - self.t0, 1))
            return EXIT_OK
        except ValidationFailure as exc:
            _marker("FAIL")
            _emit("section", exc.section)
            _emit("reason", self._redact(exc.reason))
            return EXIT_VALIDATION
        except FormalReviewError as exc:
            _marker("FAIL")
            _emit("section", "FORMAL_REVIEW")
            _emit("reason", self._redact(f"{exc.code}: {exc.message}"))
            return EXIT_FORMAL_REVIEW
        except (DecisionStoreCorrupt, EvaluationStoreCorrupt, ShadowReviewStoreCorrupt) as exc:
            _marker("FAIL")
            _emit("section", "STORE_CORRUPT")
            _emit("reason", self._redact(f"{type(exc).__name__}: {exc}"))
            return EXIT_VALIDATION
        except Exception as exc:  # noqa: BLE001
            _marker("FAIL")
            _emit("section", "UNEXPECTED")
            _emit("reason", self._redact(f"{type(exc).__name__}: {exc}"))
            return EXIT_UNEXPECTED

    def _redact(self, text: str) -> str:
        out = text.replace(str(self.data_root), "<data_root>").replace(str(self.repo), "<repo>")
        tokens = []
        for tok in out.split():
            low = tok.lower()
            if ".pdf" in low or "\\" in tok or ("/" in tok and len(tok) > 24):
                tokens.append("<redacted>")
            else:
                tokens.append(tok)
        return " ".join(tokens)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.9.5 real-data packet validation (dry-run only, fail closed)")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--require-commit", default="")
    for layer in POLICY_LAYERS:
        parser.add_argument(f"--expect-{layer.replace('_', '-')}", default="", dest=f"expect_{layer}")
    parser.add_argument("--skip-git", action="store_true", help="test harness only")
    args = parser.parse_args(list(argv) if argv is not None else None)
    from .cli import resolve_root

    root = resolve_root(args.data_root)
    repo = Path(__file__).resolve().parents[3]
    expected = {layer: getattr(args, f"expect_{layer}") for layer in POLICY_LAYERS}
    return RealDataPacketValidation(root, repo, require_commit=args.require_commit, expected_digests=expected,
                                    skip_git=args.skip_git).run_all()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
