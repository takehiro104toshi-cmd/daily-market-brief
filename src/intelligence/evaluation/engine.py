"""Evaluation engine（Phase 3.9.2）— Phase 3.8 artifact を **読むだけ** で 6 axis → score → recommendation。

境界（絶対）:
- Decision を書かない / `DecisionService.decide()` を呼ばない / decision history を触らない。
- production DNA・Corpus・Phase 3.8 research artifact を書き換えない（読み取り専用で開く）。
- auto approval も DNA promotion も無い。APPROVE_RECOMMENDED は人間への助言に過ぎない。
- formal APPROVED は Phase 3.9.1 の CORPUS_100 gate が守る。ここは shadow フラグを記録するだけ。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .axes import (
    cross_regime,
    data_quality,
    dna_novelty,
    evidence_consistency,
    evidence_strength,
    relative_support_share,
    time_stability,
)
from .config import (
    A_CONSISTENCY,
    A_CROSS,
    A_NOVELTY,
    A_QUALITY,
    A_STRENGTH,
    A_TIME,
    AXES,
    CORE_AXES,
    EvaluationPolicy,
    PolicyError,
    RecommendationPolicy,
)
from .contradiction import build_contradiction_index
from .models import (
    APPLICABLE,
    BASE_LIMITATIONS,
    CONSISTENCY_TAUTOLOGY_LIMITATION,
    APPROVE_RECOMMENDED,
    NOT_APPLICABLE,
    REJECT_RECOMMENDED,
    REVIEW_RECOMMENDED,
    AxisResult,
    EvaluationRecord,
    evaluation_id_for,
    inputs_digest_for,
)
from .rules import decide
from .score import reference_score
from .store import EvaluationStore

DECISION_REJECTED = "REJECTED"
DECISION_APPROVED = "APPROVED"


@dataclass
class EngineReport:
    evaluated: int = 0
    written: int = 0
    dry_run: bool = False
    counts: Dict[str, int] = field(default_factory=dict)
    by_type: Dict[str, Dict[str, int]] = field(default_factory=dict)
    by_status: Dict[str, Dict[str, int]] = field(default_factory=dict)
    shadow_mode: bool = True
    formal_review_gate_reached: bool = False
    corpus_size: int = 0
    corpus_milestone: str = ""
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class EvaluationEngine:
    """Phase 3.8 research root を読み、derived evaluation store へ書く（それ以外へは書かない）。"""

    def __init__(self, research_root: Path, evaluation_store: EvaluationStore,
                 evaluation_policy: EvaluationPolicy, recommendation_policy: RecommendationPolicy,
                 corpus_state: Optional[Mapping[str, Any]] = None,
                 decision_state_lookup: Optional[Callable[[str], str]] = None,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self.research_root = Path(research_root)
        self.store = evaluation_store
        self.policy = evaluation_policy
        self.rules = recommendation_policy
        self.corpus_state = dict(corpus_state or {})
        #: 任意の read-only 参照。未注入なら reopen 系フィールドは None（decision 層と結合しない）
        self.decision_state_lookup = decision_state_lookup
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.policy.validate()
        self.rules.validate()

    # ------------------------------------------------------------- inputs（read-only）
    def _rows(self, name: str) -> List[Dict[str, Any]]:
        path = self.research_root / name
        if not path.is_file():
            return []
        import json

        out: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def load_inputs(self, pattern_version: str = "1.0.0") -> Dict[str, Any]:
        patterns: Dict[str, Dict[str, Any]] = {}
        for row in self._rows("patterns.jsonl"):
            if str(row.get("pattern_version")) == pattern_version:
                patterns[str(row["pattern_id"])] = row
        structures: Dict[str, Dict[str, Any]] = {}
        for s in self._rows("structures.jsonl"):
            doc = str(s.get("document_id", ""))
            if doc and (doc not in structures
                        or str(s.get("created_at", "")) >= str(structures[doc].get("created_at", ""))):
                structures[doc] = s
        comparisons: Dict[str, Dict[str, Any]] = {}
        for c in self._rows("dna_comparisons.jsonl"):
            comparisons[str(c.get("pattern_id", ""))] = c
        conflicts: Dict[str, int] = {}
        for c in self._rows("conflicts.jsonl"):
            pid = str(c.get("pattern_id", ""))
            conflicts[pid] = conflicts.get(pid, 0) + 1
        eligible_dates = sorted(str(s.get("document_date", "")) for s in structures.values()
                                if s.get("eligible") and s.get("document_date"))
        return {"patterns": patterns, "structures": structures, "comparisons": comparisons,
                "conflicts": conflicts, "eligible_dates": eligible_dates}

    # ------------------------------------------------------------- policy drift（fail closed）
    def assert_no_policy_drift(self) -> None:
        """同じ policy_version で digest が違う既存 record があれば拒否（silent な threshold 変更を許さない）。"""
        if not self.store.exists():
            return
        for row in self.store.iter_records():
            if (str(row.get("evaluation_policy_version")) == self.policy.policy_version
                    and str(row.get("evaluation_policy_digest")) != self.policy.digest()):
                raise PolicyError(
                    f"compass_evaluation {self.policy.policy_version} already recorded with a different digest; "
                    "bump policy_version instead of changing thresholds in place")
            if (str(row.get("recommendation_policy_version")) == self.rules.policy_version
                    and str(row.get("recommendation_policy_digest")) != self.rules.digest()):
                raise PolicyError(
                    f"compass_recommendation {self.rules.policy_version} already recorded with a different digest; "
                    "bump policy_version instead of changing rules in place")

    # ------------------------------------------------------------- single pattern
    def evaluate_pattern(self, record: Mapping[str, Any], inputs: Mapping[str, Any], index) -> EvaluationRecord:
        structures_by_doc = inputs["structures"]
        declared = [str(d) for d in (record.get("supporting_document_ids") or [])]
        structures = [structures_by_doc[d] for d in declared if d in structures_by_doc]
        pid = str(record["pattern_id"])
        ptype = str(record.get("pattern_type", ""))

        strength = evidence_strength(record, self.policy)
        time_axis = time_stability(record, structures, self.policy)
        cross, confirmation = cross_regime(record, structures, self.policy)
        consistency = evidence_consistency(record, structures, index,
                                           int(inputs["conflicts"].get(pid, 0)), self.policy,
                                           self.rules.reject_min_documents_each_side)
        novelty = dna_novelty(record, inputs["comparisons"].get(pid), self.policy)
        quality = data_quality(record, structures, self.policy)
        axes: Dict[str, AxisResult] = {A_STRENGTH: strength, A_TIME: time_axis, A_CROSS: cross,
                                       A_CONSISTENCY: consistency, A_NOVELTY: novelty, A_QUALITY: quality}

        share, share_applicability, denominator = relative_support_share(record, inputs["eligible_dates"], self.policy)
        score, comparable, applicable_axes, weight_sum = reference_score(axes, self.policy)
        outcome = decide(axes, ptype, self.rules, self.policy, inputs_available=bool(structures))

        corpus_size = int(self.corpus_state.get("eligible", len(inputs["eligible_dates"])))
        gate_reached = corpus_size >= self.policy.formal_review_min_corpus
        digest_payload = {
            "pattern_id": pid, "pattern_type": ptype,
            "axis_states": {a: axes[a].state for a in AXES},
            "axis_applicability": {a: axes[a].applicability for a in AXES},
            "axis_metrics": {a: axes[a].metrics for a in AXES},
            "corpus_size": corpus_size,
        }
        inputs_digest = inputs_digest_for(digest_payload)

        limitations = list(BASE_LIMITATIONS)
        if consistency.state == "HIGH":
            limitations.append(CONSISTENCY_TAUTOLOGY_LIMITATION)
        for axis in AXES:
            if axes[axis].applicability == NOT_APPLICABLE:
                limitations.append(f"STRUCTURAL_NOT_APPLICABLE:{axis}")
        if not comparable:
            limitations.append(
                f"REFERENCE_SCORE_NOT_COMPARABLE: applicable weight {weight_sum} below floor "
                f"{self.policy.applicable_weight_floor}")
        if outcome.recommendation == APPROVE_RECOMMENDED and not gate_reached:
            limitations.append(f"{self.rules.shadow_label}: formal APPROVED is not possible below "
                               f"CORPUS_{self.policy.formal_review_min_corpus}")

        decision_state = ""
        reopen_signal: Optional[bool] = None
        adverse_signal: Optional[bool] = None
        if self.decision_state_lookup is not None:
            decision_state = str(self.decision_state_lookup(pid) or "")
            reopen_signal = (decision_state == DECISION_REJECTED
                             and outcome.recommendation in (REVIEW_RECOMMENDED, APPROVE_RECOMMENDED))
            adverse_signal = (decision_state == DECISION_APPROVED
                              and outcome.recommendation == REJECT_RECOMMENDED)

        return EvaluationRecord(
            evaluation_id=evaluation_id_for(pid, self.policy.digest(), self.rules.digest(), inputs_digest),
            pattern_id=pid, pattern_type=ptype, pattern_version=str(record.get("pattern_version", "")),
            evaluated_at=self.clock().astimezone(timezone.utc).isoformat(),
            axis_states={a: axes[a].state for a in AXES},
            axis_applicability={a: axes[a].applicability for a in AXES},
            axis_metrics={a: dict(axes[a].metrics) for a in AXES},
            axis_reasons={a: axes[a].reason for a in AXES},
            reference_score=score, reference_score_comparable=comparable,
            applicable_axes=tuple(applicable_axes), applicable_weight_sum=weight_sum,
            recommendation=outcome.recommendation, triggered_rule=outcome.triggered_rule,
            blocking_rules=outcome.blocking_rules, supporting_rules=outcome.supporting_rules,
            evaluation_policy_version=self.policy.policy_version, evaluation_policy_digest=self.policy.digest(),
            recommendation_policy_version=self.rules.policy_version,
            recommendation_policy_digest=self.rules.digest(),
            shadow_mode=not gate_reached, formal_review_gate_reached=gate_reached,
            corpus_size=corpus_size, corpus_milestone=str(self.corpus_state.get("milestone", "")),
            inputs_digest=inputs_digest, confirmation_3d=confirmation,
            relative_support_share=share, relative_support_applicability=share_applicability,
            reopen_signal=reopen_signal, approved_adverse_signal=adverse_signal, decision_state=decision_state,
            limitations=tuple(dict.fromkeys(limitations)))

    # ------------------------------------------------------------- run
    def evaluate_all(self, pattern_version: str = "1.0.0", dry_run: bool = False,
                     only_pattern: str = "") -> "tuple[EngineReport, List[EvaluationRecord]]":
        self.assert_no_policy_drift()
        inputs = self.load_inputs(pattern_version)
        patterns = inputs["patterns"]
        if only_pattern:
            patterns = {k: v for k, v in patterns.items() if k == only_pattern}
        index = build_contradiction_index(list(inputs["patterns"].values()), self.policy,
                                          self.rules.reject_min_sibling_support)
        report = EngineReport(dry_run=dry_run)
        records: List[EvaluationRecord] = []
        for pid in sorted(patterns):
            try:
                records.append(self.evaluate_pattern(patterns[pid], inputs, index))
            except Exception as exc:  # noqa: BLE001 1 pattern の失敗を run 全体へ広げない
                report.errors.append(f"{type(exc).__name__}")
        report.evaluated = len(records)
        counts: Dict[str, int] = {}
        by_type: Dict[str, Dict[str, int]] = {}
        by_status: Dict[str, Dict[str, int]] = {}
        for rec in records:
            counts[rec.recommendation] = counts.get(rec.recommendation, 0) + 1
            by_type.setdefault(rec.pattern_type, {})
            by_type[rec.pattern_type][rec.recommendation] = by_type[rec.pattern_type].get(rec.recommendation, 0) + 1
            status = str(patterns[rec.pattern_id].get("status", ""))
            by_status.setdefault(status, {})
            by_status[status][rec.recommendation] = by_status[status].get(rec.recommendation, 0) + 1
        corpus_size = int(self.corpus_state.get("eligible", len(inputs["eligible_dates"])))
        report.counts, report.by_type, report.by_status = counts, by_type, by_status
        report.corpus_size = corpus_size
        report.corpus_milestone = str(self.corpus_state.get("milestone", ""))
        report.formal_review_gate_reached = corpus_size >= self.policy.formal_review_min_corpus
        report.shadow_mode = not report.formal_review_gate_reached
        if not dry_run and not only_pattern:
            snapshot = {
                "generated_at": self.clock().astimezone(timezone.utc).isoformat(),
                "evaluated": report.evaluated, "counts": counts, "by_type": by_type, "by_status": by_status,
                "evaluation_policy_version": self.policy.policy_version,
                "evaluation_policy_digest": self.policy.digest(),
                "recommendation_policy_version": self.rules.policy_version,
                "recommendation_policy_digest": self.rules.digest(),
                "shadow_mode": report.shadow_mode,
                "formal_review_gate_reached": report.formal_review_gate_reached,
                "corpus_size": corpus_size, "corpus_milestone": report.corpus_milestone,
                "boundaries": ["APPROVE_RECOMMENDED is advice, not APPROVED",
                               "no decision is written by the evaluation engine",
                               "Reference Score never determines a recommendation state",
                               "promotion to Compass DNA requires a separate future gate"],
            }
            report.written = self.store.replace_all(records, snapshot)["written"]
        return report, records
