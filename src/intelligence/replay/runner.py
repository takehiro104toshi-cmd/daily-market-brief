"""Replay runner（Phase 3.9.4）— 固定された入力宇宙の上で回顧的安定性 replay を 1 run 実行する。

run = 一貫 corpus snapshot + 一貫 Context snapshot + 凍結 analyzer version + 凍結 policy digest 4 種。
捕捉後に production が動いても run には入らない。production へは何も書かない（PDF も開かない）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..corpus.config import CorpusConfig, load_corpus_config
from ..corpus.store import CorpusStore, corpus_root
from ..corpus_research.config import ResearchConfig, load_research_config
from ..evaluation.config import EvaluationPolicy, RecommendationPolicy, load_policies
from ..shadow_review.config import ShadowReviewPolicy, load_shadow_review_policy
from .config import MODE_FULL, MODE_MILESTONE_AND_TRANSITION, MODE_TRANSITION, ReplayPolicy, load_replay_policy
from .errors import (
    ReplayAnalyzerVersionMissing,
    ReplayError,
    ReplayInputMutated,
    ReplayPolicyError,
    ReplaySnapshotCaptureError,
    ReplayTempCorrupt,
)
from .evaluate import IdentityRegistry, SnapshotEvaluator, state_signature
from .events import derive_events
from .manifest import InputManifest, build_manifest, detect_input_mutation
from .metrics import all_pattern_metrics, distribution
from .ordering import Ordering, canonical_order, coarse_positions, milestone_positions
from .research import ReplayResearchDriver
from .snapshot import (
    CALENDAR_FILE,
    CONTEXT_FILE,
    CONTEXT_META_FILE,
    capture_corpus_snapshot,
    export_context_snapshot,
    live_context_digest,
    live_corpus_observation,
    live_document_identity,
    load_context_snapshot,
)
from .store import ReplayStore, replay_root
from .stress import approve_stress, formal_review_input, read_only_production_references, reject_stress
from .timeline import SECTION_MAIN, canonical_json
from .view import ReplayCorpusView

OWNER_MARKER = "REPLAY_OWNED_TEMP"
INPUT_LIVE_CAPTURE = "PRODUCTION_LIVE_CAPTURE"
INPUT_RETAINED_SNAPSHOT = "RETAINED_SNAPSHOT"

# 実行戦略（semantic な replay_mode とは別の実行 metadata。run_digest には入らない）
EXECUTION_TRANSITION_REFINEMENT = "TRANSITION_REFINEMENT"   # 粗い pass + 遷移区間を checkpoint 復元で 1 件刻み
EXECUTION_FULL_SINGLE_PASS = "FULL_SINGLE_PASS"             # FULL_REPLAY: 1 文書ずつの単一 pass
EXECUTION_COARSE_ONLY = "COARSE_ONLY"                       # MILESTONE_REPLAY / refine_transitions=false
PLAN_COVERAGE_COMPLETE = "COMPLETE"
PLAN_COVERAGE_PARTIAL = "PARTIAL"
# FULL fallback を採らない理由（実測: run_incremental 1 回 ≫ checkpoint 復元 1 回。単一 pass へ切り替えると
# 内側の coarse position ごとに run_incremental が 1 回増え、評価する position 集合は変わらない）
FULL_FALLBACK_REASON = ("NOT_CHOSEN: exact refinement already evaluates only the planned positions; a single forward "
                        "pass would add one run_incremental call per interior coarse position and save only the "
                        "cheaper checkpoint restores")


def workspace_base(policy: ReplayPolicy) -> Path:
    base = Path(policy.temp_workspace) if policy.temp_workspace else Path(tempfile.gettempdir())
    return base / "compass_replay_runs"


def retained_snapshot_dir(policy: ReplayPolicy, run_id: str) -> Path:
    """`--retain-temp` で保持された run の temp（= 不変入力 snapshot そのもの）の場所。"""
    return workspace_base(policy) / run_id


BOUNDARIES = (
    "NOT_PREDICTIVE: replay measures how today's frozen rules behave on historical prefixes",
    "NOT_FORMAL_APPROVAL: persistence never converts to APPROVED or REJECTED",
    "HUMAN_FEEDBACK_ONLY: historical queues are simulated with an empty event store; no human answer is fabricated",
    "IMMUTABLE_INPUT_UNIVERSE: corpus and Context were captured once at run start",
)


class ReplayRunner:
    def __init__(self, production_data_root: Path, *, replay_policy: Optional[ReplayPolicy] = None,
                 evaluation_policy: Optional[EvaluationPolicy] = None,
                 recommendation_policy: Optional[RecommendationPolicy] = None,
                 shadow_policy: Optional[ShadowReviewPolicy] = None,
                 research_config: Optional[ResearchConfig] = None, corpus_config: Optional[CorpusConfig] = None,
                 mode: str = "", ordering: str = "", retain_temp: Optional[bool] = None,
                 rules_path: Optional[Path] = None, clock: Optional[Callable[[], datetime]] = None,
                 output_root: Optional[Path] = None, input_snapshot: Optional[Path] = None) -> None:
        self.production = Path(production_data_root)
        # input_snapshot: 保持された run の temp から **同じ不変入力宇宙** を再利用する（決定性 / 較正 FULL 用）。
        # production を再捕捉しないので、live intake がいくら進んでも入力は同一。
        self.input_snapshot = Path(input_snapshot) if input_snapshot else None
        self.policy = replay_policy or load_replay_policy()
        self.policy.validate()
        if evaluation_policy is None or recommendation_policy is None:
            evaluation_policy, recommendation_policy = load_policies()
        self.epol, self.rpol = evaluation_policy, recommendation_policy
        self.spol = shadow_policy or load_shadow_review_policy()
        self.rconfig = research_config or load_research_config()
        self.cconfig = corpus_config or load_corpus_config()
        self.mode = mode or self.policy.default_mode
        self.ordering_mode = ordering or self.policy.default_ordering
        self.retain_temp = self.policy.retain_debug_runs if retain_temp is None else bool(retain_temp)
        self.rules_path = rules_path
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.output_root = Path(output_root) if output_root else replay_root(self.production)
        self.temp_root: Optional[Path] = None

    # ------------------------------------------------------------- temp workspace
    def _workspace_base(self) -> Path:
        return workspace_base(self.policy)

    def _input_source(self) -> Dict[str, str]:
        if self.input_snapshot is None:
            return {"kind": INPUT_LIVE_CAPTURE, "source_run_id": ""}
        marker = self.input_snapshot / OWNER_MARKER
        if not marker.is_file() or not (self.input_snapshot / "corpus" / "index" / "corpus.sqlite3").is_file() \
                or not (self.input_snapshot / "context" / CONTEXT_META_FILE).is_file():
            raise ReplaySnapshotCaptureError("retained input snapshot is missing or not replay-owned")
        return {"kind": INPUT_RETAINED_SNAPSHOT, "source_run_id": marker.read_text(encoding="utf-8").strip()}

    def _make_temp(self, run_id: str) -> Path:
        root = self._workspace_base() / run_id
        if root.exists():
            raise ReplayTempCorrupt(f"temp workspace for {run_id} already exists")
        root.mkdir(parents=True)
        (root / OWNER_MARKER).write_text(run_id, encoding="utf-8")
        return root

    def cleanup_temp(self) -> bool:
        """replay が自分で作った run ディレクトリだけを消す（marker と親パスを検証）。"""
        root = self.temp_root
        if root is None or not root.exists():
            return False
        base = self._workspace_base().resolve()
        resolved = root.resolve()
        if resolved.parent != base or not (resolved / OWNER_MARKER).is_file():
            raise ReplayTempCorrupt(f"refusing to delete a path replay does not own: {resolved.name}")
        shutil.rmtree(resolved)
        return True

    # ------------------------------------------------------------- policy drift（fail closed）
    def assert_no_policy_drift(self) -> None:
        """同じ replay policy_version で digest が違う run が既に保存されていれば拒否する。"""
        store = ReplayStore(self.output_root)
        latest = store.latest()
        run_id = str(latest.get("run_id", ""))
        if not run_id:
            return
        stored = dict(store.read_json(run_id, "replay_manifest.json").get("replay_policy") or {})
        if stored.get("version") == self.policy.policy_version and stored.get("digest") != self.policy.digest():
            raise ReplayPolicyError(
                f"compass_replay {self.policy.policy_version} already recorded with digest {stored.get('digest')}; "
                "bump policy_version instead of changing replay semantics in place")

    # ------------------------------------------------------------- run
    def run(self) -> Dict[str, Any]:  # noqa: C901 orchestration は 1 箇所に集める
        t_start = time.perf_counter()
        self.assert_no_policy_drift()
        input_source = self._input_source()
        run_created_at = self.clock().astimezone(timezone.utc)
        run_id = "crp_" + hashlib.sha1(
            f"{run_created_at.isoformat()}|{self.mode}|{self.ordering_mode}".encode("utf-8")).hexdigest()[:16]
        self.temp_root = self._make_temp(run_id)
        temp = self.temp_root
        timings: Dict[str, float] = {}
        store: Optional[CorpusStore] = None
        try:
            # 1) immutable input universe -----------------------------------------
            t0 = time.perf_counter()
            prod_corpus = corpus_root(self.production)
            live_start = live_corpus_observation(prod_corpus)
            capture_from = (self.input_snapshot / "corpus") if self.input_snapshot is not None else prod_corpus
            corpus_info = capture_corpus_snapshot(capture_from, temp / "corpus")
            manifest = build_manifest(temp / "corpus")
            supported = tuple(self.epol.supported_analysis_versions)
            missing = [v for v in manifest.analysis_versions if supported and v not in supported]
            if missing:
                raise ReplayAnalyzerVersionMissing(
                    f"corpus analysis versions {missing} are not supported by the frozen evaluation policy")
            if self.input_snapshot is not None:          # 保持 snapshot の Context をそのまま再利用（production は読まない）
                (temp / "context").mkdir(parents=True, exist_ok=True)
                for name in (CONTEXT_FILE, CALENDAR_FILE, CONTEXT_META_FILE):
                    shutil.copyfile(self.input_snapshot / "context" / name, temp / "context" / name)
                context = load_context_snapshot(temp / "context")
            else:
                context = export_context_snapshot(self.production, temp / "context", manifest.latest_document_date)
            timings["capture_seconds"] = round(time.perf_counter() - t0, 3)

            ordering = canonical_order(manifest, self.ordering_mode, self.policy)
            positions = coarse_positions(self.policy, self.mode, ordering.max_eligible)
            milestones = [p for p in milestone_positions(self.policy, ordering.max_eligible) if p in positions]
            refine = self.policy.refine_transitions and self.mode in (MODE_TRANSITION, MODE_MILESTONE_AND_TRANSITION)

            # 2) replay engines over the frozen snapshot --------------------------
            store = CorpusStore(temp / "corpus")
            view = ReplayCorpusView(store, ())
            driver = ReplayResearchDriver(view, temp / "research", temp / "research_ckpt", self.rconfig,
                                          self.cconfig, context.connector(), run_created_at, rules_path=self.rules_path)
            identity = IdentityRegistry()
            evaluator = SnapshotEvaluator(
                run_id=run_id, input_manifest_digest=manifest.input_manifest_digest,
                ordering_mode=self.ordering_mode, snapshot_mode=self.mode, driver=driver,
                eval_dir=temp / "evaluation", shadow_dir=temp / "shadow_review",
                evaluation_policy=self.epol, recommendation_policy=self.rpol, shadow_policy=self.spol,
                replay_policy_digest=self.policy.digest(), include_queue=self.policy.include_shadow_queue,
                milestones=self.cconfig.milestones, identity=identity)

            snapshots: Dict[int, Dict[str, Any]] = {}
            rows_by_pos: Dict[int, List[Dict[str, Any]]] = {}
            equivalence: List[Dict[str, Any]] = []
            step = 0

            # 3) forward pass（coarse positions）-----------------------------------
            t0 = time.perf_counter()
            pending: List[str] = []
            for item in ordering.items:
                pending.append(item.document.document_id)
                k = item.eligible_position
                if item.document.eligible and k in positions:
                    step += 1
                    driver.advance(pending, step)
                    pending = []
                    if refine and k != positions[-1]:      # 最終 coarse position は復元されないので checkpoint 不要（exact）
                        driver.checkpoint(k)
                    snap, rows = evaluator.evaluate(ordering.prefix_for_eligible(k), step)
                    snapshots[k], rows_by_pos[k] = snap, rows
                    if k in milestones:
                        step += 1
                        equivalence.append(driver.verify_rebuild_equivalence(k, temp / "rebuild", step))
            timings["forward_seconds"] = round(time.perf_counter() - t0, 3)

            # 4) transition refinement（checkpoint 復元 → 1 eligible 文書刻み）-------
            #    実行計画は粗い pass の結果から exact に決まる（閾値なし）。計画が最初の coarse position 以降の
            #    全 eligible position を覆う場合も、評価する position 集合は同じなので実行経路は変えない
            #    （FULL_FALLBACK_REASON）。計画と実コストは execution metadata として記録する。
            refined_intervals: List[Dict[str, int]] = []
            coarse = sorted(snapshots)
            plan = [(a, b) for a, b in zip(coarse, coarse[1:])
                    if refine and b - a > 1 and state_signature(rows_by_pos[a]) != state_signature(rows_by_pos[b])]
            planned_interior = sum(b - a - 1 for a, b in plan)
            span_from_first = (coarse[-1] - coarse[0] + 1) if coarse else 0
            coverage_complete = bool(coarse) and len(coarse) + planned_interior == span_from_first
            execution: Dict[str, Any] = {
                "strategy": (EXECUTION_FULL_SINGLE_PASS if self.mode == MODE_FULL
                             else EXECUTION_TRANSITION_REFINEMENT if refine else EXECUTION_COARSE_ONLY),
                "requested_replay_mode": self.mode,
                "coarse_positions": len(coarse), "coarse_intervals": max(0, len(coarse) - 1),
                "refinement_intervals_planned": len(plan), "planned_interior_positions": planned_interior,
                "planned_snapshot_total": len(coarse) + planned_interior,
                "eligible_positions_from_first_coarse": span_from_first,
                "planned_coverage": (PLAN_COVERAGE_COMPLETE if coverage_complete else PLAN_COVERAGE_PARTIAL) if refine else "N/A",
                "full_fallback": {"applicable": bool(refine and coverage_complete), "chosen": False,
                                  "reason": FULL_FALLBACK_REASON},
            }
            if refine:
                t0 = time.perf_counter()
                for a, b in plan:
                    driver.restore(a)
                    prefix_a = ordering.index_for_eligible(a)
                    for k in range(a + 1, b):
                        idx = ordering.index_for_eligible(k)
                        step += 1
                        driver.advance([it.document.document_id for it in ordering.items[prefix_a + 1: idx + 1]], step)
                        prefix_a = idx
                        snap, rows = evaluator.evaluate(ordering.prefix_for_eligible(k), step)
                        snapshots[k], rows_by_pos[k] = snap, rows
                    refined_intervals.append({"from": a, "to": b, "added": b - a - 1})
                timings["refine_seconds"] = round(time.perf_counter() - t0, 3)

            # 5) derived outputs ------------------------------------------------------
            final_position = ordering.max_eligible
            all_rows = [r for k in sorted(rows_by_pos) for r in rows_by_pos[k]]
            snapshot_docs = [snapshots[k] for k in sorted(snapshots)]
            events = derive_events(run_id, all_rows)
            metrics = all_pattern_metrics(all_rows, self.policy, final_position)
            candidates = sorted(pid for pid, m in metrics.items()
                                if m["current_recommendation"] in ("APPROVE_RECOMMENDED", "REJECT_RECOMMENDED"))
            refs = read_only_production_references(self.production, candidates)
            final_rows = rows_by_pos.get(final_position, [])
            top8 = [{"queue_rank": r["queue_rank"], "pattern_id": r["pattern_id"], "pattern_type": r["pattern_type"],
                     "recommendation": r["recommendation"],
                     "first_surfaced_in_main_position": metrics[r["pattern_id"]]["first_surfaced_in_main_position"],
                     "main_appearance_count": metrics[r["pattern_id"]]["main_appearance_count"]}
                    for r in sorted((x for x in final_rows if x["queue_section"] == SECTION_MAIN),
                                    key=lambda x: int(x["queue_rank"] or 0))]
            run_digest = self._run_digest(manifest, context, snapshot_docs)
            execution["work"] = {**driver.counters, "evaluations": len(snapshot_docs)}

            # 6) drift check（観測は記録・捕捉済み入力の改変は fail closed）------------
            live_end = live_corpus_observation(prod_corpus)
            mutations = detect_input_mutation(manifest, live_document_identity(prod_corpus, [d.document_id for d in manifest.documents]))
            live_ctx = live_context_digest(self.production, manifest.latest_document_date)
            context_changed = live_ctx != context.context_manifest_digest
            drift = {"captured_input_mutations": mutations, "context_changed": context_changed,
                     "live_context_digest_at_end": live_ctx,
                     "new_documents_ingested_during_run": max(0, int(live_end.get("documents", 0)) - int(live_start.get("documents", 0)))}
            if self.policy.fail_on_input_drift and (mutations or context_changed):
                raise ReplayInputMutated(
                    f"captured inputs changed during the run: {len(mutations)} document changes, "
                    f"context_changed={context_changed}; result not published")

            timings["total_seconds"] = round(time.perf_counter() - t_start, 3)
            manifest_doc = self._manifest_doc(run_id, run_created_at, manifest, ordering, corpus_info.as_dict(),
                                              context.as_dict(), live_start, live_end, drift, positions, milestones)
            manifest_doc["input_source"] = input_source
            manifest_doc["execution"] = execution
            summary = self._summary(run_id, run_created_at, run_digest, manifest, context, ordering, snapshot_docs,
                                    all_rows, metrics, equivalence, refined_intervals, top8, refs, timings, drift)
            summary["execution"] = execution
            ReplayStore(self.output_root).write_run(run_id, manifest=manifest_doc, snapshots=snapshot_docs,
                                                    timelines=all_rows, events=events, summary=summary)
            result = {"run_id": run_id, "run_digest": run_digest, "output_root": str(self.output_root),
                      "input_source": input_source,
                      "snapshots": len(snapshot_docs), "timeline_rows": len(all_rows), "events": len(events),
                      "patterns": len(metrics), "final_position": final_position, "mutation": "NONE (production)",
                      "timings": timings, "temp_retained": self.retain_temp, "execution": execution}
            return result
        except ReplayError:
            self.retain_temp = True                 # 失敗時は診断のため保持（削除しない）
            raise
        finally:
            if store is not None:
                store.close()
            if not self.retain_temp:
                self.cleanup_temp()

    # ------------------------------------------------------------- documents
    def _run_digest(self, manifest: InputManifest, context, snapshot_docs: Sequence[Mapping[str, Any]]) -> str:
        view = {"input_manifest_digest": manifest.input_manifest_digest,
                "context_manifest_digest": context.context_manifest_digest,
                "research_version_key": self.rconfig.version_key,
                "evaluation_policy_digest": self.epol.digest(), "recommendation_policy_digest": self.rpol.digest(),
                "shadow_review_policy_digest": self.spol.digest(), "replay_policy_digest": self.policy.digest(),
                "ordering_mode": self.ordering_mode, "replay_mode": self.mode,
                "snapshots": [(int(s["position"]), s["snapshot_digest"], s["research_digest"]) for s in snapshot_docs]}
        return hashlib.sha256(canonical_json(view).encode("utf-8")).hexdigest()[:16]

    def _manifest_doc(self, run_id, run_created_at, manifest: InputManifest, ordering: Ordering, corpus_info, context_info,
                      live_start, live_end, drift, positions, milestones) -> Dict[str, Any]:
        return {
            "run_id": run_id, "run_created_at": run_created_at.isoformat(),
            "ordering_mode": self.ordering_mode, "replay_mode": self.mode,
            "corpus_snapshot": corpus_info, "context_snapshot": context_info,
            "documents": [d.as_dict() for d in manifest.documents],
            "duplicates_summary": dict(manifest.duplicates_summary),
            "excluded": list(manifest.excluded) + [{"document_id": d, "reason": "UNDATED_CHRONOLOGICAL", "detail": ""}
                                                    for d in ordering.excluded_undated],
            "undated_ratio": str(ordering.undated_ratio),
            "input_manifest_digest": manifest.input_manifest_digest,
            "corpus_snapshot_digest": corpus_info["snapshot_db_sha256"][:16],
            "context_manifest_digest": context_info["context_manifest_digest"],
            "research_version_key": self.rconfig.version_key,
            "evaluation_policy": {"version": self.epol.policy_version, "digest": self.epol.digest()},
            "recommendation_policy": {"version": self.rpol.policy_version, "digest": self.rpol.digest()},
            "shadow_review_policy": {"version": self.spol.policy_version, "digest": self.spol.digest()},
            "replay_policy": {"version": self.policy.policy_version, "digest": self.policy.digest()},
            "captured_eligible": manifest.captured_eligible, "captured_usable": manifest.captured_usable,
            "captured_documents": manifest.captured_documents, "latest_document_date": manifest.latest_document_date,
            "ordered_documents": len(ordering.items), "evaluated_positions": positions, "milestone_positions": milestones,
            "live_production_corpus_at_start": live_start, "live_production_corpus_at_end": live_end,
            "new_documents_ingested_during_run": drift["new_documents_ingested_during_run"],
            "drift": drift, "boundaries": list(BOUNDARIES),
        }

    def _summary(self, run_id, run_created_at, run_digest, manifest, context, ordering, snapshot_docs, rows, metrics,
                 equivalence, refined, top8, refs, timings, drift) -> Dict[str, Any]:
        final = ordering.max_eligible
        return {
            "run_id": run_id, "run_created_at": run_created_at.isoformat(), "run_digest": run_digest,
            "ordering_mode": self.ordering_mode, "replay_mode": self.mode,
            "input_manifest_digest": manifest.input_manifest_digest,
            "context_manifest_digest": context.context_manifest_digest,
            "research_version_key": self.rconfig.version_key,
            "policy_digests": {"evaluation": self.epol.digest(), "recommendation": self.rpol.digest(),
                               "shadow_review": self.spol.digest(), "replay": self.policy.digest()},
            "captured_eligible": manifest.captured_eligible, "captured_usable": manifest.captured_usable,
            "final_position": final, "snapshots": len(snapshot_docs), "timeline_rows": len(rows),
            "patterns": len(metrics),
            "positions": [int(s["position"]) for s in snapshot_docs],
            "refined_intervals": refined,
            "rebuild_equivalence": equivalence,
            "final_distribution": {"by_recommendation": snapshot_docs[-1]["by_recommendation"] if snapshot_docs else {},
                                   "by_lifecycle": snapshot_docs[-1]["by_lifecycle"] if snapshot_docs else {}},
            "queue_over_time": [{"position": int(s["position"]), **dict(s.get("queue") or {})} for s in snapshot_docs],
            "current_top8_retrospective": top8,
            "stability_distribution": distribution(metrics),
            "stability_calibration_state": self.policy.stability_calibration_state,
            "pattern_metrics": metrics,
            "approve_stress": approve_stress(rows, metrics, final),
            "reject_stress": reject_stress(rows, metrics),
            "formal_review_input": formal_review_input(rows, metrics, refs),
            "drift": drift, "timings": timings, "boundaries": list(BOUNDARIES),
        }
