"""Shadow Review queue builder（Phase 3.9.3）— 「今日、人間が見るべき少数」を決定的に選ぶ。

Recommendation state は**読むだけ**で、再分類も新 state 生成も一切しない。
Decision も DNA も書かない。Phase 3.8 research artifact / Phase 3.9.2 evaluation record も変更しない。

出力（すべて derived・再構築可能・atomic 置換）:
    queue.json / summary.json / current_reviews.json
人間レビュー履歴（review_events.jsonl）は events.py が append-only で持ち、ここでは読むだけ。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..evaluation.config import (
    A_CONSISTENCY,
    A_CROSS,
    A_NOVELTY,
    A_QUALITY,
    A_STRENGTH,
    A_TIME,
    AXES,
    EvaluationPolicy,
    RecommendationPolicy,
    T_EVIDENCE_OUTLOOK,
)
from ..evaluation.contradiction import outlook_part
from ..evaluation.models import REJECT_RECOMMENDED
from ..evaluation.store import EvaluationStore
from .config import (
    AGREE,
    ShadowReviewPolicyError,
    DISAGREE,
    DUPLICATE_OR_OVERLAPPING,
    NEEDS_MORE_EVIDENCE,
    NOT_ACTIONABLE,
    SECTION_ADVERSE_OVERFLOW,
    SECTION_BACKLOG,
    SECTION_MAIN,
    SECTION_WATCH,
    UNCLEAR,
    ShadowReviewPolicy,
)
from .diversity import round_robin
from .explain import explain
from .events import ShadowReviewEventStore
from .material import material_digest
from .models import REVIEW_BOUNDARIES, ReviewCard, assert_no_forbidden_keys, canonical_json
from .ranking import eligible_support, shadow_ordering_key, span_days
from .state import CurrentReview, derive_current_reviews

QUEUE_FILE = "queue.json"
SUMMARY_FILE = "summary.json"
CURRENT_REVIEWS_FILE = "current_reviews.json"
NOT_AVAILABLE = "NOT_AVAILABLE"

DEFERRED_COOLDOWN = "COOLDOWN"
DEFERRED_NOT_SELECTED = "NOT_SELECTED_THIS_ROUND"


@dataclass
class QueueReport:
    dry_run: bool = False
    main_queue_count: int = 0
    adverse_overflow_count: int = 0
    backlog_count: int = 0
    watch_count: int = 0
    escalated_count: int = 0
    evaluated_count: int = 0
    by_recommendation: Dict[str, int] = field(default_factory=dict)
    by_pattern_type: Dict[str, int] = field(default_factory=dict)
    corpus_size: int = 0
    corpus_milestone: str = ""
    shadow_mode: bool = True
    formal_review_gate_reached: bool = False
    evaluation_policy_version: str = ""
    evaluation_policy_digest: str = ""
    recommendation_policy_version: str = ""
    recommendation_policy_digest: str = ""
    shadow_review_policy_version: str = ""
    shadow_review_policy_digest: str = ""
    errors: List[str] = field(default_factory=list)
    mutation: str = "NONE"

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def sibling_group_id(components: Mapping[str, Any]) -> str:
    """表示専用の兄弟グループ id。Phase 3.9.2 の (evidence, target) grouping と同じ鍵を使う。

    クラスタリングでも de-dup でもなく、identity の統合も一切しない（§18）。
    """
    if str(components.get("pattern_type", "")) != T_EVIDENCE_OUTLOOK:
        return ""
    target = outlook_part(components, "target=")
    if not target:
        return ""
    evidence = tuple(sorted(str(e) for e in (components.get("evidence") or [])))
    seed = canonical_json({"evidence": list(evidence), "target": target})
    return "sib_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]   # noqa: S324 表示用の短縮鍵


class ShadowReviewQueueBuilder:
    """Phase 3.9.2 evaluation + Phase 3.8 metadata + 人間レビュー履歴 → 決定的な queue。"""

    def __init__(self, research_root: Path, evaluation_store: EvaluationStore,
                 event_store: ShadowReviewEventStore, policy: ShadowReviewPolicy,
                 evaluation_policy: EvaluationPolicy, recommendation_policy: RecommendationPolicy,
                 corpus_state: Optional[Mapping[str, Any]] = None,
                 clock: Optional[Any] = None) -> None:
        self.research_root = Path(research_root)
        self.evaluations = evaluation_store
        self.events = event_store
        self.policy = policy
        self.evaluation_policy = evaluation_policy
        self.recommendation_policy = recommendation_policy
        self.corpus_state = dict(corpus_state or {})
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.policy.validate()

    # ------------------------------------------------------------- inputs（read-only）
    def _rows(self, name: str) -> List[Dict[str, Any]]:
        path = self.research_root / name
        if not path.is_file():
            return []
        out: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def load_research(self, pattern_version: str = "1.0.0") -> Dict[str, Any]:
        patterns: Dict[str, Dict[str, Any]] = {}
        for row in self._rows("patterns.jsonl"):
            if str(row.get("pattern_version")) == pattern_version:
                patterns[str(row.get("pattern_id"))] = row
        dates: Dict[str, str] = {}
        for s in self._rows("structures.jsonl"):
            doc = str(s.get("document_id", ""))
            date = str(s.get("document_date", ""))
            if doc and date and (doc not in dates or date > dates[doc]):
                dates[doc] = date
        return {"patterns": patterns, "document_dates": dates}

    @property
    def root(self) -> Path:
        return self.events.root

    # ------------------------------------------------------------- policy drift（fail closed）
    def assert_no_policy_drift(self) -> None:
        """同じ shadow_review policy_version で digest が違う既存 event があれば拒否する。

        review event には「そのとき人間が見ていた policy」が焼き込まれている。version を据え置いた
        まま threshold を変えると履歴の意味が壊れるので、silent な変更を fail closed で止める。
        """
        if not self.events.exists():
            return
        for event in self.events.records():
            if (event.shadow_review_policy_version == self.policy.policy_version
                    and event.shadow_review_policy_digest != self.policy.digest()):
                raise ShadowReviewPolicyError(
                    f"compass_shadow_review {self.policy.policy_version} already recorded with a "
                    "different digest; bump policy_version instead of changing it in place")

    # ------------------------------------------------------------- build
    def build(self, pattern_version: str = "1.0.0", dry_run: bool = False
              ) -> "tuple[QueueReport, Dict[str, Any], Dict[str, Any], Dict[str, Any]]":
        now = self.clock().astimezone(timezone.utc)
        self.assert_no_policy_drift()
        report = QueueReport(dry_run=dry_run)
        report.evaluation_policy_version = self.evaluation_policy.policy_version
        report.evaluation_policy_digest = self.evaluation_policy.digest()
        report.recommendation_policy_version = self.recommendation_policy.policy_version
        report.recommendation_policy_digest = self.recommendation_policy.digest()
        report.shadow_review_policy_version = self.policy.policy_version
        report.shadow_review_policy_digest = self.policy.digest()

        research = self.load_research(pattern_version)
        patterns = research["patterns"]
        document_dates = research["document_dates"]
        evaluations = self.evaluations.records() if self.evaluations.exists() else []
        report.evaluated_count = len(evaluations)

        lifecycle_of = {pid: str(row.get("status", "")) for pid, row in patterns.items()}
        digests: Dict[str, str] = {}
        current_for_state: Dict[str, Dict[str, str]] = {}
        for row in evaluations:
            pid = str(row.get("pattern_id"))
            digest = material_digest(row, lifecycle_of.get(pid, ""), self.policy)
            digests[pid] = digest
            current_for_state[pid] = {"material_digest": digest,
                                      "recommendation": str(row.get("recommendation", ""))}

        events = self.events.records() if self.events.exists() else []
        reviews = derive_current_reviews(events, self.policy, current_for_state, now)

        corpus_size = int(self.corpus_state.get("eligible", 0))
        gate_reached = corpus_size >= self.evaluation_policy.formal_review_min_corpus
        report.corpus_size = corpus_size
        report.corpus_milestone = str(self.corpus_state.get("milestone", ""))
        report.formal_review_gate_reached = gate_reached
        report.shadow_mode = not gate_reached

        # ---- escalated pool（Recommendation state は読むだけ）
        escalated = [r for r in evaluations if str(r.get("recommendation")) in self.policy.state_priority]
        report.escalated_count = len(escalated)

        def eligible(row: Mapping[str, Any]) -> bool:
            review = reviews.get(str(row.get("pattern_id")))
            return review is None or review.eligible_for_requeue

        ready = [r for r in escalated if eligible(r)]
        cooling = [r for r in escalated if not eligible(r)]

        key = lambda row: shadow_ordering_key(row, self.evaluation_policy)   # noqa: E731

        # ---- state priority → diversity（REJECT / APPROVE は bypass）
        main: List[Mapping[str, Any]] = []
        overflow: List[Mapping[str, Any]] = []
        selected_ids: set = set()
        for state in self.policy.state_priority:
            pool = sorted([r for r in ready if str(r.get("recommendation")) == state], key=key)
            slots = max(0, self.policy.top_n - len(main))
            if state in self.policy.diversity_bypass_states:
                main.extend(pool[:slots])
                if state == REJECT_RECOMMENDED:
                    # ADVERSE_OVERFLOW は「逆行証拠が top_n に収まらなかった分」専用の区画。
                    # 他の bypass state（APPROVE）の溢れをここへ入れると adverse_overflow_count が
                    # 「捌けていない逆行件数」を意味しなくなるので、backlog（件数と型内訳つき）へ回す。
                    overflow.extend(pool[slots:])
            else:
                main.extend(round_robin(pool, slots, self.policy, key))
        selected_ids = {str(r.get("pattern_id")) for r in main} | {str(r.get("pattern_id")) for r in overflow}

        # ---- WATCH（v1 は watch_n=0 なので既定で空）
        watch: List[Mapping[str, Any]] = []
        if self.policy.watch_n > 0:
            candidates = [r for r in evaluations
                          if str(r.get("recommendation")) == self.policy.watch_source_state
                          and lifecycle_of.get(str(r.get("pattern_id")), "")
                          not in self.policy.watch_excluded_lifecycles
                          and eligible(r)]
            watch = round_robin(sorted(candidates, key=key), self.policy.watch_n, self.policy, key)

        # ---- cards
        def card_for(row: Mapping[str, Any], rank: int, section: str) -> ReviewCard:
            return self._card(row, rank, section, patterns, document_dates, digests, reviews,
                              corpus_size, gate_reached)

        main_cards, overflow_cards, watch_cards = [], [], []
        for index, row in enumerate(main, start=1):
            main_cards.append(card_for(row, index, SECTION_MAIN))
        for index, row in enumerate(overflow, start=1):
            overflow_cards.append(card_for(row, index, SECTION_ADVERSE_OVERFLOW))
        for index, row in enumerate(watch, start=1):
            watch_cards.append(card_for(row, index, SECTION_WATCH))

        # ---- backlog（捨てない。件数と内訳を必ず残す）
        backlog_rows = [r for r in escalated if str(r.get("pattern_id")) not in selected_ids]
        cooling_ids = {str(r.get("pattern_id")) for r in cooling}
        backlog_items = [{
            "pattern_id": str(r.get("pattern_id")),
            "pattern_type": str(r.get("pattern_type")),
            "recommendation": str(r.get("recommendation")),
            "deferred_reason": DEFERRED_COOLDOWN if str(r.get("pattern_id")) in cooling_ids
            else DEFERRED_NOT_SELECTED,
        } for r in sorted(backlog_rows, key=key)]

        report.main_queue_count = len(main_cards)
        report.adverse_overflow_count = len(overflow_cards)
        report.watch_count = len(watch_cards)
        report.backlog_count = len(backlog_items)
        report.by_recommendation = _counts(escalated, "recommendation")
        report.by_pattern_type = _counts(escalated, "pattern_type")

        queue_doc = {
            "generated_at": now.isoformat(),
            "top_n": self.policy.top_n, "watch_n": self.policy.watch_n,
            "corpus_size": corpus_size, "corpus_milestone": report.corpus_milestone,
            "shadow_mode": report.shadow_mode, "formal_review_gate_reached": gate_reached,
            "evaluation_policy_version": report.evaluation_policy_version,
            "evaluation_policy_digest": report.evaluation_policy_digest,
            "recommendation_policy_version": report.recommendation_policy_version,
            "recommendation_policy_digest": report.recommendation_policy_digest,
            "shadow_review_policy_version": report.shadow_review_policy_version,
            "shadow_review_policy_digest": report.shadow_review_policy_digest,
            "state_priority": list(self.policy.state_priority),
            "ordering": list(self.policy.ranking_order),
            "main": [c.as_dict() for c in main_cards],
            "adverse_overflow": [c.as_dict() for c in overflow_cards],
            "watch": [c.as_dict() for c in watch_cards],
            "backlog": {"count": len(backlog_items),
                        "by_recommendation": _counts(backlog_rows, "recommendation"),
                        "by_pattern_type": _counts(backlog_rows, "pattern_type"),
                        "items": backlog_items},
            "boundaries": list(REVIEW_BOUNDARIES),
        }
        summary_doc = self._summary(now, report, evaluations, escalated, events, reviews,
                                    main_cards, backlog_rows)
        current_doc = {"generated_at": now.isoformat(),
                       "shadow_review_policy_digest": self.policy.digest(),
                       "patterns": {pid: review.as_dict() for pid, review in sorted(reviews.items())}}

        assert_no_forbidden_keys(queue_doc, "queue.json")
        assert_no_forbidden_keys(summary_doc, "summary.json")
        assert_no_forbidden_keys(current_doc, "current_reviews.json")

        if dry_run:
            report.mutation = "NONE"
        else:
            self._atomic_json(self.root / QUEUE_FILE, queue_doc)
            self._atomic_json(self.root / SUMMARY_FILE, summary_doc)
            self._atomic_json(self.root / CURRENT_REVIEWS_FILE, current_doc)
            report.mutation = f"REPLACE {QUEUE_FILE}, {SUMMARY_FILE}, {CURRENT_REVIEWS_FILE}"
        return report, queue_doc, summary_doc, current_doc

    # ------------------------------------------------------------- card
    def _card(self, row: Mapping[str, Any], rank: int, section: str,
              patterns: Mapping[str, Mapping[str, Any]], document_dates: Mapping[str, str],
              digests: Mapping[str, str], reviews: Mapping[str, CurrentReview],
              corpus_size: int, gate_reached: bool) -> ReviewCard:
        pid = str(row.get("pattern_id"))
        pattern = dict(patterns.get(pid) or {})
        components = dict(pattern.get("components") or {})
        lifecycle = str(pattern.get("status", ""))
        metrics = dict(row.get("axis_metrics") or {})
        states = dict(row.get("axis_states") or {})
        applicability = dict(row.get("axis_applicability") or {})
        reasons = dict(row.get("axis_reasons") or {})
        consistency = dict(metrics.get(A_CONSISTENCY) or {})
        cross = dict(metrics.get(A_CROSS) or {})
        time_metrics = dict(metrics.get(A_TIME) or {})
        novelty = dict(metrics.get(A_NOVELTY) or {})
        quality = dict(metrics.get(A_QUALITY) or {})
        review = reviews.get(pid)

        doc_ids = tuple(str(d) for d in (pattern.get("supporting_document_ids") or []))
        dates: Tuple[str, ...] = ()
        if self.policy.show_supporting_document_dates:
            dates = tuple(sorted({document_dates[d] for d in doc_ids if d in document_dates}))

        return ReviewCard(
            queue_rank=rank, queue_section=section, pattern_id=pid,
            pattern_type=str(row.get("pattern_type", "")), lifecycle_status=lifecycle,
            recommendation=str(row.get("recommendation", "")),
            why_surfaced=explain(row, lifecycle, not gate_reached, corpus_size,
                                 self.evaluation_policy.formal_review_min_corpus),
            axes={axis: {"state": str(states.get(axis, "")),
                         "applicability": str(applicability.get(axis, "")),
                         "reason": str(reasons.get(axis, ""))} for axis in AXES},
            reference_score=row.get("reference_score") if row.get("reference_score_comparable") else None,
            reference_score_comparable=bool(row.get("reference_score_comparable")),
            evidence={"eligible_support": _int(eligible_support(row)),
                      "span_days": _int(span_days(row)),
                      "distinct_calendar_months": int(time_metrics.get("distinct_calendar_months", 0) or 0),
                      "distinct_2d_cells": int(cross.get("distinct_2d_cells", 0) or 0),
                      "confirmed_2d_cells": int(cross.get("confirmed_2d_cells", 0) or 0),
                      "relative_support_share": row.get("relative_support_share"),
                      "relative_support_applicability": str(row.get("relative_support_applicability", "")),
                      "document_qualities": dict(quality.get("document_qualities") or {}),
                      "applicable_weight_sum": int(row.get("applicable_weight_sum", 0) or 0)},
            relations={"dna_relation": str(novelty.get("classification", "")),
                       "direction_relation": str(novelty.get("direction_relation", "")),
                       "narrow_sibling_contradiction": bool(consistency.get("narrow_sibling_contradiction")),
                       "narrow_sibling_repeated": bool(consistency.get("narrow_sibling_repeated")),
                       "document_contradiction": bool(consistency.get("contradiction")),
                       "document_contradiction_repeated": bool(consistency.get("contradiction_repeated")),
                       "dna_conflicts": int(consistency.get("dna_conflicts", 0) or 0),
                       "sibling_group_id": sibling_group_id(components)},
            rules={"triggered_rule": str(row.get("triggered_rule", "")),
                   "supporting_rules": list(row.get("supporting_rules") or []),
                   "blocking_rules": list(row.get("blocking_rules") or [])},
            governance={"shadow_mode": bool(row.get("shadow_mode", not gate_reached)),
                        "formal_review_gate_reached": gate_reached,
                        "formal_review_min_corpus": self.evaluation_policy.formal_review_min_corpus,
                        "corpus_size": corpus_size,
                        "corpus_milestone": str(self.corpus_state.get("milestone", "")),
                        "note": "AGREE is not APPROVED; no shadow review promotes to Compass DNA"},
            history={"review_count": review.review_count if review else 0,
                     "last_outcome": review.last_outcome if review else "",
                     "last_reviewed_at": review.last_reviewed_at if review else "",
                     "disagreement_count": review.disagreement_count if review else 0,
                     "materially_changed_since": review.materially_changed_since if review else None,
                     "recommendation_changed_since": review.recommendation_changed_since if review else None,
                     "cooldown_until": review.cooldown_until if review else None},
            supporting_document_dates=dates,
            supporting_document_ids=doc_ids,
            material_digest=str(digests.get(pid, "")),
            evaluation_id=str(row.get("evaluation_id", "")),
            inputs_digest=str(row.get("inputs_digest", "")),
            limitations=tuple(str(x) for x in (row.get("limitations") or ())))

    # ------------------------------------------------------------- summary（calibration metrics）
    def _summary(self, now: datetime, report: QueueReport, evaluations: Sequence[Mapping[str, Any]],
                 escalated: Sequence[Mapping[str, Any]], events: Sequence[Any],
                 reviews: Mapping[str, CurrentReview], main_cards: Sequence[ReviewCard],
                 backlog_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        total = len(events)
        rule_of = {str(r.get("pattern_id")): str(r.get("triggered_rule", "")) for r in evaluations}
        type_of = {str(r.get("pattern_id")): str(r.get("pattern_type", "")) for r in evaluations}

        def rate(count: int, denominator: int) -> Optional[float]:
            return round(count / denominator, 4) if denominator else None

        def rate_by(bucket_of) -> Dict[str, Any]:
            totals: Dict[str, int] = {}
            disagreements: Dict[str, int] = {}
            for event in events:
                bucket = bucket_of(event)
                if not bucket:
                    continue
                totals[bucket] = totals.get(bucket, 0) + 1
                if event.review_outcome == DISAGREE:
                    disagreements[bucket] = disagreements.get(bucket, 0) + 1
            return {b: rate(disagreements.get(b, 0), n) for b, n in sorted(totals.items())} or NOT_AVAILABLE

        outcome_counts: Dict[str, int] = {}
        for event in events:
            outcome_counts[event.review_outcome] = outcome_counts.get(event.review_outcome, 0) + 1
        adverse_events = [e for e in events if e.recommendation_at_review == REJECT_RECOMMENDED]
        reviewed_escalated = sum(1 for r in escalated if str(r.get("pattern_id")) in reviews)

        metrics: Dict[str, Any] = {
            "review_agreement_rate": rate(outcome_counts.get(AGREE, 0), total),
            "human_disagreement_rate": rate(outcome_counts.get(DISAGREE, 0), total),
            "disagreement_rate_by_recommendation": rate_by(lambda e: e.recommendation_at_review),
            "disagreement_rate_by_triggered_rule": rate_by(lambda e: rule_of.get(e.pattern_id, "")),
            "disagreement_rate_by_pattern_type": rate_by(lambda e: type_of.get(e.pattern_id, "")),
            "needs_more_evidence_rate": rate(outcome_counts.get(NEEDS_MORE_EVIDENCE, 0), total),
            "unclear_rate": rate(outcome_counts.get(UNCLEAR, 0), total),
            "not_actionable_rate": rate(outcome_counts.get(NOT_ACTIONABLE, 0), total),
            "duplicate_rate": rate(outcome_counts.get(DUPLICATE_OR_OVERLAPPING, 0), total),
            "re_review_rate": rate(sum(1 for r in reviews.values() if r.review_count >= 2), len(reviews)),
            "recommendation_change_after_review": sum(
                1 for r in reviews.values() if r.recommendation_changed_since),
            "time_to_first_escalation": NOT_AVAILABLE,      # escalate 時刻は未記録（捏造しない）
            "queue_type_distribution": _counts([{"pattern_type": c.pattern_type} for c in main_cards],
                                               "pattern_type"),
            "queue_coverage": rate(reviewed_escalated, len(escalated)),
            "adverse_disagreement_rate": rate(
                sum(1 for e in adverse_events if e.review_outcome == DISAGREE), len(adverse_events)),
            "adverse_overflow_count": report.adverse_overflow_count,
        }
        return {
            "generated_at": now.isoformat(),
            "shadow_mode": report.shadow_mode,
            "formal_review_gate_reached": report.formal_review_gate_reached,
            "corpus_size": report.corpus_size, "corpus_milestone": report.corpus_milestone,
            "evaluated": report.evaluated_count, "escalated": report.escalated_count,
            "main_queue_count": report.main_queue_count,
            "adverse_overflow_count": report.adverse_overflow_count,
            "backlog_count": report.backlog_count, "watch_count": report.watch_count,
            "by_recommendation": report.by_recommendation,
            "by_pattern_type": report.by_pattern_type,
            "backlog_by_recommendation": _counts(backlog_rows, "recommendation"),
            "backlog_by_pattern_type": _counts(backlog_rows, "pattern_type"),
            "review_events": total,
            "reviewed_patterns": len(reviews),
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "calibration_metrics": metrics,
            "metric_note": "calibration only; these are not prediction accuracy (Phase 3.9 is NOT_PREDICTIVE)",
            "evaluation_policy_version": report.evaluation_policy_version,
            "evaluation_policy_digest": report.evaluation_policy_digest,
            "recommendation_policy_version": report.recommendation_policy_version,
            "recommendation_policy_digest": report.recommendation_policy_digest,
            "shadow_review_policy_version": report.shadow_review_policy_version,
            "shadow_review_policy_digest": report.shadow_review_policy_digest,
            "boundaries": list(REVIEW_BOUNDARIES),
        }

    # ------------------------------------------------------------- write（derived のみ）
    def _atomic_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        text = json.dumps(dict(payload), ensure_ascii=False, indent=1, sort_keys=True, default=str)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def _counts(rows: Sequence[Mapping[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, ""))
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def _int(value: float) -> int:
    return int(value) if value and value > 0 else 0


def read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")) or {})
    except (OSError, ValueError):
        return {}
