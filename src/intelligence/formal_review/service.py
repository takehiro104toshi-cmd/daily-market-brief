"""FormalReviewService（Phase 3.9.5）— 読み取り専用の入力から packet / queue を作り、guard を通した formal Decision
だけを Phase 3.9.1 DecisionService へ渡す。

唯一の mutating path: FormalReviewGuard → DecisionRequest → DecisionService.validate → DecisionService.decide
→ DecisionStore.append。service 自身も guard も DecisionStore に触れない。derived 出力は compass_formal_review/ のみ。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..corpus_research.config import ResearchConfig, load_research_config
from ..corpus_research.store import ResearchStore, research_root
from ..decision.corpus_state import CorpusState, corpus_state_from_data_root
from ..decision.evidence import build_evidence_snapshot
from ..decision.models import ACTOR_HUMAN
from ..decision.policy import DecisionPolicy, load_decision_policy
from ..decision.service import DecisionRequest, DecisionService
from ..decision.state import derive_current_states
from ..decision.store import DecisionStore, decisions_root
from ..evaluation.config import EvaluationPolicy, RecommendationPolicy, load_policies
from ..evaluation.models import APPROVE_RECOMMENDED
from ..evaluation.store import EvaluationStore, evaluation_root
from ..replay.config import ReplayPolicy, load_replay_policy
from ..replay.store import MANIFEST_FILE as REPLAY_MANIFEST_FILE, SUMMARY_FILE as REPLAY_SUMMARY_FILE, ReplayStore, replay_root
from ..shadow_review.config import ShadowReviewPolicy, load_shadow_review_policy
from ..shadow_review.events import ShadowReviewEventStore, shadow_review_root
from ..shadow_review.material import material_digest
from ..shadow_review.state import derive_current_reviews
from .config import ACTIONS, APPROVED, KEEP_REVIEWING, REJECTED, FormalReviewPolicy, load_formal_review_policy
from .errors import BatchForbidden, CandidateMissing, FormalReviewPolicyError, PacketMissing, PacketPatternMismatch
from .groups import build_groups, group_context
from .guard import FormalReviewGuard
from .metrics import assert_operational_only, compute_metrics
from .ordering import order_queue
from .packet import build_packet, shadow_history_block
from .population import select_population
from .reopen import reopen_eligibility
from .store import FormalReviewStore, formal_review_root
from .warnings import compute_warnings

BOUNDARIES = (
    "NOT_AUTOMATIC_APPROVAL: APPROVE_RECOMMENDED is not APPROVED; only a human writes a formal decision",
    "NOT_DNA_PROMOTION: APPROVED is not a promotion to Compass DNA; every formal decision stays NOT_PROMOTED",
    "EVIDENCE_PACKET_BOUND: a decision is accepted only against the exact packet the human reviewed",
    "HUMAN_ONE_AT_A_TIME: one pattern per decision, no batch approval or rejection",
    "SHADOW_HISTORY_IS_EVIDENCE: AGREE is not APPROVED and DISAGREE is not REJECTED",
)


@dataclass
class FormalReviewInputs:
    evaluations: Dict[str, Dict[str, Any]]
    evaluation_snapshot: Dict[str, Any]
    pattern_records: Dict[str, Dict[str, Any]]
    dna_comparisons: Dict[str, Dict[str, Any]]
    conflicts: Dict[str, List[Dict[str, Any]]]
    shadow_events: Dict[str, List[Dict[str, Any]]]
    decision_records: List[Dict[str, Any]]
    decision_heads: Dict[str, Dict[str, Any]]
    decision_states: Dict[str, str]
    replay: Optional[Dict[str, Any]]
    corpus: CorpusState
    material: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FormalDecisionRequest:
    pattern_id: str
    action: str                       # CLI action（approve / reject / ...）または decision_type
    packet_id: str
    reason: str
    actor: str
    actor_type: str = ACTOR_HUMAN
    acknowledge_siblings: Sequence[str] = ()
    related_pattern_id: str = ""
    replacement_pattern_id: str = ""
    reason_category: str = ""
    disposition: str = ""

    @property
    def decision_type(self) -> str:
        return ACTIONS.get(self.action, self.action)


class FormalReviewService:
    def __init__(self, data_root: Path, *, policy: Optional[FormalReviewPolicy] = None,
                 evaluation_policy: Optional[EvaluationPolicy] = None,
                 recommendation_policy: Optional[RecommendationPolicy] = None,
                 shadow_policy: Optional[ShadowReviewPolicy] = None, replay_policy: Optional[ReplayPolicy] = None,
                 decision_policy: Optional[DecisionPolicy] = None, research_config: Optional[ResearchConfig] = None,
                 corpus_state_resolver: Optional[Callable[[], CorpusState]] = None,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self.root = Path(data_root)
        self.policy = policy or load_formal_review_policy()
        self.policy.validate()
        if evaluation_policy is None or recommendation_policy is None:
            default_e, default_r = load_policies()
            evaluation_policy = evaluation_policy or default_e
            recommendation_policy = recommendation_policy or default_r
        self.epol, self.rpol = evaluation_policy, recommendation_policy
        self.spol = shadow_policy or load_shadow_review_policy()
        self.replay_policy = replay_policy or load_replay_policy()
        self.dpol = decision_policy or load_decision_policy()
        self.rconfig = research_config or load_research_config()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.corpus_state_resolver = corpus_state_resolver or (lambda: corpus_state_from_data_root(self.root, self.clock()))
        self.store = FormalReviewStore(formal_review_root(self.root))
        self.decision_store = DecisionStore(decisions_root(self.root))
        self.guard = FormalReviewGuard(self.policy, self.dpol.formal_review_min_corpus)

    # ------------------------------------------------------------- policy binding
    def policy_digests(self) -> Dict[str, str]:
        return {"evaluation": self.epol.digest(), "recommendation": self.rpol.digest(), "shadow_review": self.spol.digest(),
                "replay": self.replay_policy.digest(), "decision": self.dpol.digest(), "formal_review": self.policy.digest()}

    def policy_versions(self) -> Dict[str, str]:
        return {"evaluation": self.epol.policy_version, "recommendation": self.rpol.policy_version,
                "shadow_review": self.spol.policy_version, "replay": self.replay_policy.policy_version,
                "decision": self.dpol.policy_version, "formal_review": self.policy.policy_version}

    def assert_no_policy_drift(self) -> None:
        stored = dict((self.store.manifest().get("policies") or {}).get("formal_review") or {})
        if stored and stored.get("version") == self.policy.policy_version and stored.get("digest") != self.policy.digest():
            raise FormalReviewPolicyError(f"compass_formal_review {self.policy.policy_version} already recorded with digest "
                                          f"{stored.get('digest')}; bump policy_version instead of changing it in place")

    # ------------------------------------------------------------- inputs（read-only・fail closed）
    def load_inputs(self) -> FormalReviewInputs:
        estore = EvaluationStore(evaluation_root(self.root))
        evaluations = {str(r["pattern_id"]): dict(r) for r in estore.records()} if estore.exists() else {}
        research = ResearchStore(research_root(self.root)) if (research_root(self.root) / "patterns.jsonl").is_file() else None
        pattern_records = dict(research.pattern_records_current(self.rconfig.pattern_version)) if research else {}
        dna: Dict[str, Dict[str, Any]] = {}
        conflicts: Dict[str, List[Dict[str, Any]]] = {}
        if research:
            for row in research.rows("dna_comparisons"):
                dna[str(row.get("pattern_id"))] = dict(row)                 # append 順 = 最後が最新
            for row in research.rows("conflicts"):
                conflicts.setdefault(str(row.get("pattern_id")), []).append(dict(row))
        sstore = ShadowReviewEventStore(shadow_review_root(self.root))
        shadow: Dict[str, List[Dict[str, Any]]] = {}
        if sstore.exists():
            for event in sstore.records():                                   # corrupt → ShadowReviewStoreCorrupt
                shadow.setdefault(event.pattern_id, []).append(event.as_dict())
        records = [r.as_dict() for r in self.decision_store.records()]       # corrupt → DecisionStoreCorrupt
        states = derive_current_states(self.decision_store.records())
        heads = {pid: rec for pid, rec in ((r["pattern_id"], r) for r in sorted(records, key=lambda r: r["sequence"]))}
        inputs = FormalReviewInputs(
            evaluations=evaluations, evaluation_snapshot=estore.snapshot() if estore.exists() else {},
            pattern_records={pid: dict(rec) for pid, rec in pattern_records.items()}, dna_comparisons=dna,
            conflicts=conflicts, shadow_events=shadow, decision_records=records, decision_heads=heads,
            decision_states={pid: s.state for pid, s in states.items()}, replay=self._load_replay(),
            corpus=self.corpus_state_resolver())
        inputs.material = {pid: material_digest(row, str((pattern_records.get(pid) or {}).get("status", "")), self.spol)
                           for pid, row in evaluations.items()}
        return inputs

    def _load_replay(self) -> Optional[Dict[str, Any]]:
        rstore = ReplayStore(replay_root(self.root))
        latest = rstore.latest()
        run_id = str(latest.get("run_id", ""))
        if not run_id:
            return None
        summary = rstore.read_json(run_id, REPLAY_SUMMARY_FILE)
        manifest = rstore.read_json(run_id, REPLAY_MANIFEST_FILE)
        if not summary:
            return None
        stress: Dict[str, Dict[str, Any]] = {}
        for section in ("approve_stress", "reject_stress"):
            for item in (dict(summary.get(section) or {})).get("items") or []:
                stress[str(item.get("pattern_id"))] = dict(item)
        return {"run_id": run_id, "run_digest": str(summary.get("run_digest", "")),
                "captured_eligible": int(summary.get("captured_eligible", 0) or 0),
                "policy_digests": dict(summary.get("policy_digests") or {}),
                "replay_policy": dict(manifest.get("replay_policy") or {}),
                "pattern_metrics": dict(summary.get("pattern_metrics") or {}), "stress": stress}

    def replay_evidence_for(self, pattern_id: str, recommendation: str, inputs: FormalReviewInputs) -> Optional[Dict[str, Any]]:
        replay = inputs.replay
        if not replay or pattern_id not in replay["pattern_metrics"]:
            return None
        metrics = dict(replay["pattern_metrics"][pattern_id])
        reasons: List[str] = []
        current = self.policy_digests()
        for layer in ("evaluation", "recommendation", "shadow_review", "replay"):
            if str(replay["policy_digests"].get(layer, "")) != current[layer]:
                reasons.append(f"POLICY_DIGEST_MISMATCH:{layer}")
        if str(metrics.get("current_recommendation", "")) != recommendation:
            reasons.append("RECOMMENDATION_DIFFERS_FROM_REPLAY")
        if replay["captured_eligible"] > int(inputs.corpus.eligible):
            reasons.append("CAPTURED_EXCEEDS_CURRENT_ELIGIBLE")
        return {"run_id": replay["run_id"], "run_digest": replay["run_digest"], "captured_eligible": replay["captured_eligible"],
                "metrics": metrics, "stress": dict(replay["stress"].get(pattern_id) or {}),
                "current_compatible": not reasons, "compatibility_reasons": reasons}

    # ------------------------------------------------------------- packets
    def assemble_packet(self, pattern_id: str, inputs: FormalReviewInputs, groups: Mapping[str, Sequence[str]],
                        built_at: str) -> Dict[str, Any]:
        evaluation = inputs.evaluations[pattern_id]
        record = inputs.pattern_records.get(pattern_id) or {}
        head = inputs.decision_heads.get(pattern_id)
        events = inputs.shadow_events.get(pattern_id) or []
        current_review = None
        if events:
            sstore_events = ShadowReviewEventStore(shadow_review_root(self.root)).for_pattern(pattern_id)
            reviews = derive_current_reviews(sstore_events, self.spol,
                                             {pattern_id: {"material_digest": inputs.material[pattern_id],
                                                           "recommendation": evaluation["recommendation"]}},
                                             now=self.clock())
            current_review = reviews[pattern_id].as_dict() if pattern_id in reviews else None
        state = derive_current_states(self.decision_store.records()).get(pattern_id)
        decision = {"state": state.state if state else "", "decision_id": state.decision_id if state else "",
                    "history_length": state.history_length if state else 0,
                    "promotion_status": state.promotion_status if state else "NOT_PROMOTED"}
        packet = build_packet(
            pattern_id=pattern_id, evaluation=evaluation, pattern_record=record,
            dna_comparison=inputs.dna_comparisons.get(pattern_id) or {}, conflicts=inputs.conflicts.get(pattern_id) or [],
            replay=self.replay_evidence_for(pattern_id, str(evaluation["recommendation"]), inputs),
            shadow_history=shadow_history_block(events, current_review), decision=decision,
            group=group_context(pattern_id, inputs.pattern_records, groups, inputs.evaluations, inputs.decision_states,
                                inputs.material),
            material_digest=inputs.material[pattern_id], policy_digests=self.policy_digests(),
            policy_versions=self.policy_versions(), corpus_eligible=int(inputs.corpus.eligible),
            reopen=reopen_eligibility(head, inputs.material[pattern_id]), policy=self.policy, built_at=built_at)
        packet["warnings"] = compute_warnings(packet, self.policy)
        return packet

    def current_packet(self, pattern_id: str, inputs: Optional[FormalReviewInputs] = None) -> Dict[str, Any]:
        inputs = inputs or self.load_inputs()
        if pattern_id not in inputs.evaluations:
            raise PacketMissing(f"pattern {pattern_id} has no current evaluation")
        groups = build_groups(inputs.pattern_records)
        return self.assemble_packet(pattern_id, inputs, groups, built_at="")

    # ------------------------------------------------------------- build（derived only）
    def build(self) -> Dict[str, Any]:
        self.assert_no_policy_drift()
        built_at = self.clock().astimezone(timezone.utc).isoformat()
        inputs = self.load_inputs()
        groups = build_groups(inputs.pattern_records)
        reopen_flags = {pid: reopen_eligibility(inputs.decision_heads.get(pid), inputs.material[pid])["eligible"]
                        for pid in inputs.evaluations if pid in inputs.decision_heads}
        population = select_population(inputs.evaluations, inputs.decision_states, reopen_flags, groups, inputs.pattern_records)
        # packet は candidate / reopen / context / decided（SUPERSEDED・RETIRED・reopen 判断のため）に作る。
        # queue に載るのは primary と reopen だけ。context は決められない。decided は head に応じた action のみ。
        packets = {pid: self.assemble_packet(pid, inputs, groups, built_at)
                   for pid in sorted(set(population.primary) | set(population.reopen_eligible) | set(population.context)
                                     | set(population.decided))}
        queue_sections = order_queue(packets, population.primary, population.reopen_eligible, self.policy)
        context_rows = [{"pattern_id": pid, "recommendation": packets[pid]["recommendation"]["recommendation"],
                         "decision_state": packets[pid]["decision"]["current_state"],
                         "sibling_group_key": packets[pid]["group"]["sibling_group_key"], "role": "CONTEXT_ONLY"}
                        for pid in population.context]
        decided_rows = [{"pattern_id": pid, "packet_id": packets[pid]["identity"]["packet_id"],
                         "recommendation": packets[pid]["recommendation"]["recommendation"],
                         "decision_state": packets[pid]["decision"]["current_state"],
                         "allowed_next_actions": list(packets[pid]["decision"]["allowed_next_actions"]),
                         "reopen": packets[pid]["decision"]["reopen"].get("status"), "role": "DECIDED"}
                        for pid in population.decided]
        metrics = compute_metrics(population=population.as_dict(), packets=packets, decision_states=inputs.decision_states,
                                  decision_records=inputs.decision_records, corpus_eligible=int(inputs.corpus.eligible),
                                  replay_captured_eligible=int((inputs.replay or {}).get("captured_eligible", 0) or 0))
        assert_operational_only(metrics)
        policies = {name: {"version": v, "digest": d} for name, v, d in
                    ((k, self.policy_versions()[k], self.policy_digests()[k]) for k in self.policy_digests())}
        manifest = {
            "built_at": built_at, "packet_schema_version": self.policy.packet_schema_version, "policies": policies,
            "corpus": inputs.corpus.as_dict(),
            "inputs": {"evaluations": len(inputs.evaluations), "pattern_records": len(inputs.pattern_records),
                       "shadow_events": sum(len(v) for v in inputs.shadow_events.values()),
                       "decision_records": len(inputs.decision_records),
                       "replay_run_id": (inputs.replay or {}).get("run_id", ""),
                       "replay_run_digest": (inputs.replay or {}).get("run_digest", ""),
                       "replay_captured_eligible": (inputs.replay or {}).get("captured_eligible"),
                       # 選ばれた run が記録している policy digest（現行 replay policy と違えば evidence は非互換）
                       "replay_run_policy_digests": dict((inputs.replay or {}).get("policy_digests") or {}),
                       "replay_run_replay_policy": dict((inputs.replay or {}).get("replay_policy") or {})},
            "population": population.as_dict(),
            "packets": {pid: {"packet_id": p["identity"]["packet_id"], "packet_evidence_digest": p["freshness"]["packet_evidence_digest"],
                              "material_digest": p["freshness"]["material_digest"]} for pid, p in sorted(packets.items())},
            "boundaries": list(BOUNDARIES),
        }
        queue = {"built_at": built_at, "sections": queue_sections, "context": context_rows, "decided": decided_rows,
                 "section_order": list(queue_sections), "policies": policies, "boundaries": list(BOUNDARIES)}
        summary = {"built_at": built_at, "metrics": metrics, "population": population.as_dict(), "policies": policies,
                   "corpus_eligible": int(inputs.corpus.eligible), "boundaries": list(BOUNDARIES)}
        self.store.write_build(manifest=manifest, queue=queue, summary=summary, packets=packets)
        return {"built_at": built_at, "packets": len(packets), "primary": len(population.primary),
                "context": len(population.context), "reopen_eligible": len(population.reopen_eligible),
                "sections": {k: len(v) for k, v in queue_sections.items()}, "metrics": metrics,
                "mutation": "DERIVED_ONLY (compass_formal_review/)"}

    # ------------------------------------------------------------- decide（唯一の formal write path）
    def decision_service(self) -> DecisionService:
        return DecisionService(self.decision_store, self.dpol, self.corpus_state_resolver,
                               lambda pid: build_evidence_snapshot(research_root(self.root), pid, self.rconfig.pattern_version),
                               clock=self.clock)

    def decide(self, request: FormalDecisionRequest, *, dry_run: bool) -> Dict[str, Any]:
        if isinstance(request.pattern_id, (list, tuple)) or "," in str(request.pattern_id):
            raise BatchForbidden("one pattern per decision")
        pattern_id = str(request.pattern_id).strip()
        reviewed = self.store.packet(pattern_id)
        if reviewed is None:
            raise PacketMissing(f"no built packet for {pattern_id}; run build first")
        if str(request.packet_id) != reviewed["identity"]["packet_id"]:
            raise PacketPatternMismatch("packet_id does not match the built packet for this pattern")
        queue = self.store.queue()
        listed = {row["pattern_id"] for rows in (queue.get("sections") or {}).values() for row in rows}
        listed |= {row["pattern_id"] for row in queue.get("decided") or []}      # APPROVED → supersede / retire、REJECTED → reopen 判定
        if pattern_id not in listed:
            raise CandidateMissing(f"pattern {pattern_id} is context-only or not in the built queue; it cannot be decided here")
        inputs = self.load_inputs()                                   # 1-2: store corrupt → 例外で fail closed
        head = inputs.decision_heads.get(pattern_id)
        if head and self._is_retry_of_head(head, request, reviewed["identity"]["packet_id"]):
            # この packet を消費した decision そのものの retry: 重複 row を作らず、既存 row を返す（DecisionService と同じ semantics）
            return {"pattern_id": pattern_id, "action": request.decision_type, "packet_id": request.packet_id, "dry_run": dry_run,
                    "guard": {"checks_passed": ["RETRY_OF_HEAD_DECISION"], "acknowledged_siblings": []},
                    "metadata": dict(head.get("metadata") or {}), "promotion_status": str(head.get("promotion_status", "NOT_PROMOTED")),
                    "validation": {"ok": True, "errors": [], "duplicate_of_head": head.get("decision_id")},
                    "outcome": {"appended": False, "decision_id": head.get("decision_id"), "store_reason": "DUPLICATE_OF_HEAD_IDEMPOTENT",
                                "record": dict(head)},
                    "mutation": "NONE (DUPLICATE_OF_HEAD_IDEMPOTENT)"}
        if pattern_id not in inputs.evaluations:
            raise CandidateMissing(f"pattern {pattern_id} has no current evaluation")
        current = self.current_packet(pattern_id, inputs)
        guard = self.guard.check(
            action=request.decision_type, pattern_id=pattern_id, reviewed=reviewed, current=current,
            head=inputs.decision_heads.get(pattern_id), corpus_eligible=int(inputs.corpus.eligible),
            actor_type=request.actor_type, reason=request.reason, acknowledge_siblings=tuple(request.acknowledge_siblings),
            related_pattern_id=request.related_pattern_id, replacement_pattern_id=request.replacement_pattern_id,
            reason_category=request.reason_category, disposition=request.disposition,
            pattern_ids=sorted(set(inputs.evaluations) | set(inputs.pattern_records)))
        decision_request = DecisionRequest(pattern_id=pattern_id, decision_type=request.decision_type,
                                           reason=str(request.reason).strip(), actor=str(request.actor).strip(),
                                           actor_type=request.actor_type, metadata=guard["metadata"],
                                           idempotency_key=reviewed["identity"]["packet_id"])
        service = self.decision_service()
        validation = service.validate(decision_request)               # 21
        out: Dict[str, Any] = {"pattern_id": pattern_id, "action": request.decision_type, "packet_id": request.packet_id,
                               "guard": {"checks_passed": guard["checks_passed"],
                                         "acknowledged_siblings": guard["acknowledged_siblings"]},
                               "metadata": guard["metadata"], "validation": validation.as_dict(),
                               "promotion_status": "NOT_PROMOTED", "dry_run": dry_run}
        if dry_run or not validation.ok:
            out["mutation"] = "NONE (dry run)" if dry_run else "NONE (validation failed)"
            return out
        outcome = service.decide(decision_request)                     # 22: 唯一の書き込み（DecisionStore.append 経由）
        out["outcome"] = outcome.as_dict()
        out["mutation"] = "APPEND decisions.jsonl" if outcome.appended else f"NONE ({outcome.store_reason})"
        return out

    @staticmethod
    def _is_retry_of_head(head: Mapping[str, Any], request: FormalDecisionRequest, packet_id: str) -> bool:
        return (str(head.get("idempotency_key", "")) == packet_id and str(head.get("decision_type", "")) == request.decision_type
                and str(head.get("reason", "")) == str(request.reason or "").strip()
                and str(head.get("actor", "")) == str(request.actor or "").strip())

    # ------------------------------------------------------------- read helpers
    def reopen_check(self) -> List[Dict[str, Any]]:
        inputs = self.load_inputs()
        out = []
        for pid, head in sorted(inputs.decision_heads.items()):
            if head.get("decision_type") != REJECTED or pid not in inputs.material:
                continue
            out.append({"pattern_id": pid, **reopen_eligibility(head, inputs.material[pid]),
                        "human_action_required": "REOPENED_FOR_REVIEW is written only by a human"})
        return out
