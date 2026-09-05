"""Per-snapshot evaluation（Phase 3.9.4）— 一時 root で 3.9.2 evaluate と 3.9.3 build(dry_run) を走らせ、
leakage / identity / sanity 監査を通した timeline row を返す。production artifact は読まない。"""
from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..corpus.milestones import milestone_status
from ..evaluation.config import RANK, EvaluationPolicy, RecommendationPolicy
from ..evaluation.engine import EvaluationEngine
from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED
from ..evaluation.store import EvaluationStore
from ..shadow_review.config import ShadowReviewPolicy
from ..shadow_review.events import ShadowReviewEventStore
from ..shadow_review.material import material_digest
from ..shadow_review.queue import ShadowReviewQueueBuilder
from .errors import (
    ReplayIdentityAmbiguity,
    ReplayIncompleteSnapshot,
    ReplayLeakageDetected,
    ReplayMixedPolicyDigest,
)
from .ordering import OrderedDocument
from .research import ReplayResearchDriver
from .timeline import (
    SECTION_ADVERSE_OVERFLOW,
    SECTION_BACKLOG,
    SECTION_MAIN,
    SECTION_NOT_SURFACED,
    components_digest,
    rows_digest,
    timeline_row,
)


class IdentityRegistry:
    """同じ pattern_id は run 全体で同じ components でなければならない（tolerance 0）。"""

    def __init__(self) -> None:
        self._seen: Dict[str, str] = {}

    def check(self, pattern_id: str, components: Mapping[str, Any]) -> None:
        digest = components_digest(components)
        before = self._seen.setdefault(pattern_id, digest)
        if before != digest:
            raise ReplayIdentityAmbiguity(
                f"pattern {pattern_id} has components digest {digest} but {before} was seen earlier in this run")

    def size(self) -> int:
        return len(self._seen)


def _snapshot_id(input_manifest_digest: str, ordering_mode: str, position: int) -> str:
    import hashlib

    return "crs_" + hashlib.sha1(f"{input_manifest_digest}|{ordering_mode}|{position}".encode("utf-8")).hexdigest()[:16]


class SnapshotEvaluator:
    def __init__(self, *, run_id: str, input_manifest_digest: str, ordering_mode: str, snapshot_mode: str,
                 driver: ReplayResearchDriver, eval_dir: Path, shadow_dir: Path,
                 evaluation_policy: EvaluationPolicy, recommendation_policy: RecommendationPolicy,
                 shadow_policy: ShadowReviewPolicy, replay_policy_digest: str, include_queue: bool,
                 milestones: Sequence[int], identity: IdentityRegistry) -> None:
        self.run_id = run_id
        self.input_manifest_digest = input_manifest_digest
        self.ordering_mode = ordering_mode
        self.snapshot_mode = snapshot_mode
        self.driver = driver
        self.eval_dir = Path(eval_dir)
        self.shadow_dir = Path(shadow_dir)
        self.epol = evaluation_policy
        self.rpol = recommendation_policy
        self.spol = shadow_policy
        self.include_queue = include_queue
        self.milestones = tuple(milestones)
        self.identity = identity
        self.policy_digests = {"evaluation": evaluation_policy.digest(), "recommendation": recommendation_policy.digest(),
                               "shadow_review": shadow_policy.digest(), "replay": replay_policy_digest,
                               "research_version_key": driver.rconfig.version_key}

    # ------------------------------------------------------------- one snapshot
    def evaluate(self, prefix: Sequence[OrderedDocument], step: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        position = prefix[-1].eligible_position
        usable_position = prefix[-1].usable_position
        prefix_ids = {p.document.document_id for p in prefix}
        prefix_dates = sorted({p.document.document_date for p in prefix if p.document.document_date})
        eligible_dates = sorted(p.document.document_date for p in prefix
                                if p.document.eligible and p.document.document_date)
        milestone = milestone_status(usable_position, self.milestones).reached
        now = self.driver.fixed_now(step)
        corpus_state = {"eligible": position, "usable": usable_position, "documents": usable_position,
                        "milestone": milestone, "source": "REPLAY_PREFIX"}

        # ---- Phase 3.9.2（一時 store・derived write）
        if self.eval_dir.exists():
            shutil.rmtree(self.eval_dir)
        eval_store = EvaluationStore(self.eval_dir)
        engine = EvaluationEngine(self.driver.research_dir, eval_store, self.epol, self.rpol,
                                  corpus_state=corpus_state, clock=lambda: now)
        inputs = engine.load_inputs(self.driver.rconfig.pattern_version)
        report, records = engine.evaluate_all(self.driver.rconfig.pattern_version, dry_run=False)
        if report.errors:
            raise ReplayIncompleteSnapshot(f"evaluation reported errors at position {position}: {report.errors[:5]}")
        patterns = inputs["patterns"]

        # ---- leakage audit（構造 / 支持文書 / 日付 / corpus_size）
        for doc_id, structure in inputs["structures"].items():
            if doc_id not in prefix_ids:
                raise ReplayLeakageDetected(f"structure for document outside prefix at position {position}")
        for pid, rec in patterns.items():
            for doc in rec.get("supporting_document_ids") or []:
                if str(doc) not in prefix_ids:
                    raise ReplayLeakageDetected(f"pattern {pid} supported by document outside prefix at {position}")
            first, last = (rec.get("date_range") or ["", ""])[:2]
            if prefix_dates and ((first and first < prefix_dates[0]) or (last and last > prefix_dates[-1])):
                raise ReplayLeakageDetected(f"pattern {pid} date_range escapes prefix dates at position {position}")
        if sorted(inputs["eligible_dates"]) != eligible_dates:
            raise ReplayLeakageDetected(f"eligible dates do not match prefix eligible documents at position {position}")
        if report.corpus_size != position:
            raise ReplayLeakageDetected(f"evaluation.corpus_size {report.corpus_size} != prefix eligible {position}")

        # ---- Phase 3.9.3（空 event store・dry_run）
        placement: Dict[str, Tuple[str, Optional[int]]] = {}
        queue_summary: Dict[str, Any] = {"enabled": False}
        if self.include_queue:
            if self.shadow_dir.exists():
                shutil.rmtree(self.shadow_dir)
            self.shadow_dir.mkdir(parents=True, exist_ok=True)
            builder = ShadowReviewQueueBuilder(
                self.driver.research_dir, EvaluationStore(self.eval_dir), ShadowReviewEventStore(self.shadow_dir),
                self.spol, self.epol, self.rpol, corpus_state=corpus_state, clock=lambda: now)
            qreport, queue_doc, _s, _c = builder.build(self.driver.rconfig.pattern_version, dry_run=True)
            if qreport.errors:
                raise ReplayIncompleteSnapshot(f"queue build reported errors at position {position}")
            if queue_doc.get("corpus_context_source") != "EVALUATION_SNAPSHOT":
                raise ReplayLeakageDetected("queue corpus context did not come from the evaluation snapshot")
            if (self.shadow_dir / "review_events.jsonl").exists():
                raise ReplayLeakageDetected("historical queue simulation must not write human review events")
            for card in queue_doc.get("main") or []:
                placement[str(card["pattern_id"])] = (SECTION_MAIN, int(card["queue_rank"]))
            for card in queue_doc.get("adverse_overflow") or []:
                placement[str(card["pattern_id"])] = (SECTION_ADVERSE_OVERFLOW, None)
            for item in (queue_doc.get("backlog") or {}).get("items") or []:
                placement[str(item["pattern_id"])] = (SECTION_BACKLOG, None)
            queue_summary = {"enabled": True, "main_count": qreport.main_queue_count,
                             "adverse_overflow_count": qreport.adverse_overflow_count,
                             "backlog_count": qreport.backlog_count, "watch_count": qreport.watch_count,
                             "by_recommendation": _counts([c["recommendation"] for c in queue_doc.get("main") or []]),
                             "by_type": _counts([c["pattern_type"] for c in queue_doc.get("main") or []])}

        # ---- timeline rows + identity / sanity audit
        snapshot = {"snapshot_id": _snapshot_id(self.input_manifest_digest, self.ordering_mode, position),
                    "snapshot_mode": self.snapshot_mode, "ordering_mode": self.ordering_mode,
                    "position": position, "usable_position": usable_position,
                    "latest_document_date": prefix_dates[-1] if prefix_dates else "",
                    "eligible_documents": position, "usable_documents": usable_position, "milestone": milestone}
        rows: List[Dict[str, Any]] = []
        for rec in sorted(records, key=lambda r: r.pattern_id):
            evaluation = rec.as_dict()
            if (evaluation.get("evaluation_policy_digest") != self.policy_digests["evaluation"]
                    or evaluation.get("recommendation_policy_digest") != self.policy_digests["recommendation"]):
                raise ReplayMixedPolicyDigest(
                    f"evaluation record for {rec.pattern_id} carries a different policy digest than this run")
            pattern = patterns.get(rec.pattern_id) or {}
            self.identity.check(rec.pattern_id, pattern.get("components") or {})
            section, rank = placement.get(rec.pattern_id, (SECTION_NOT_SURFACED, None))
            row = timeline_row(run_id=self.run_id, snapshot=snapshot, evaluation=evaluation, pattern=pattern,
                               queue_section=section, queue_rank=rank,
                               material_digest=material_digest(evaluation, str(pattern.get("status", "")), self.spol),
                               policy_digests=self.policy_digests)
            self._sanity(row)
            rows.append(row)

        snapshot_doc = {**snapshot, "evaluated": len(rows), "by_recommendation": _counts([r["recommendation"] for r in rows]),
                        "by_lifecycle": _counts([r["lifecycle_status"] for r in rows]),
                        "by_type": _counts([r["pattern_type"] for r in rows]),
                        "research_digest": self.driver.store.digest(self.driver.rconfig.version_key,
                                                                     self.driver.rconfig.pattern_version,
                                                                     self.driver.rconfig.similarity_version),
                        "queue": queue_summary, "snapshot_digest": rows_digest(rows),
                        "leakage_audit": "PASSED", "identity_audit": "PASSED"}
        return snapshot_doc, rows

    # ------------------------------------------------------------- frozen-rule sanity
    def _sanity(self, row: Mapping[str, Any]) -> None:
        """凍結規則の最小要件を満たさない推奨が出たら、replay 側の欠陥（漏洩 / 順序）として fail closed。"""
        rec = row["recommendation"]
        if rec == APPROVE_RECOMMENDED:
            if row["span_days"] < self.epol.time_high_span_days or \
                    row["distinct_calendar_months"] < self.epol.time_high_months:
                raise ReplayLeakageDetected(
                    f"impossible early APPROVE_RECOMMENDED for {row['pattern_id']} at position {row['position']}: "
                    f"span {row['span_days']}d / {row['distinct_calendar_months']} months")
            first = row.get("pattern_first_seen") or ""
            latest = row.get("latest_document_date") or ""
            if first and latest and (date.fromisoformat(latest) - date.fromisoformat(first)).days \
                    < self.epol.time_high_span_days:
                raise ReplayLeakageDetected(f"APPROVE_RECOMMENDED before minimum span from first_seen for {row['pattern_id']}")
        if rec == REJECT_RECOMMENDED:
            if row["eligible_support"] <= self.epol.strength_medium_max:
                raise ReplayLeakageDetected(
                    f"impossible REJECT_RECOMMENDED with eligible_support {row['eligible_support']} "
                    f"for {row['pattern_id']} at position {row['position']}")
            if row["eligible_support"] < 2 * self.rpol.reject_min_documents_each_side:
                raise ReplayLeakageDetected("REJECT_RECOMMENDED below repeated-contradiction minimum support")


def _counts(values: Sequence[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items()))


def state_signature(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Tuple[str, str, str]]:
    """遷移検出用: pattern → (recommendation, lifecycle, consistency state)。"""
    return {r["pattern_id"]: (r["recommendation"], r["lifecycle_status"],
                              str((r.get("axis_states") or {}).get("evidence_consistency", "")))
            for r in rows}
