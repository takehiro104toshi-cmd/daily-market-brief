"""calibration_analyzer — Phase 5 P5-3B（純粋 OFFLINE 較正 analyzer）。

    Iterable[PredictionRecord] ＋ Iterable[EvaluationRecord] ＋ 明示 CohortBoundary
        → 決定論的 CalibrationReport（`calibration_report:0.1.0`）

凍結 P5-3A（`calibration_contract`）の写像・resolver・cohort・分母・sample disclosure・
`summarize_returns`・digest を**そのまま適用**するだけであり、第二の metric 契約を発明しない。
市場データの取得・TOPIX 評価・evaluation_engine の呼び出し・journal / store の変更・較正の永続化・
P4 / Compass DNA の変更・閾値 / confidence の調整・売買推奨は**行わない**。

入力の権威（§2）: PredictionRecord と EvaluationRecord の iterable のみ。store を要求せず、
filesystem / 環境変数 / network / market / calendar に触れない（後段の adapter が
`store.iter_records()` を渡してよい）。

cohort（§3）: `CohortBoundary`（origin ＋ session_date 閉区間）で選ぶ。EvaluationRecord.created_at・
物理位置・現在日付は使わない。cohort 外の予測はどの metric にも影響しない。同一 session の複数
prediction_id は複数の観測のまま（`prediction_count` と `unique_session_count` を両方報告）。

評価の対応付け（§4 / §5）: `prediction_id` だけで対応付け、予測ごとに凍結
`resolve_active_evaluation()` を呼ぶ（第二の resolver・「最新」選択・created_at 順の選択は無い）。
coverage は ACTIVE_EVALUATED / ACTIVE_DEFERRED / NO_EVALUATION / UNRESOLVED のいずれか 1 つ。
UNRESOLVED（FORK / MULTIPLE_TERMINALS / DANGLING_SUPERSESSION / SUBJECT_MISMATCH / DUPLICATE_ID /
CYCLE）は件数と診断別件数で露出し、outcome / exact match の分母に入らない。unresolved の率は凍結
METRIC_DEFINITIONS に無いため**件数のみ**（registry を変えない）。

foreign evaluation（§6）: cohort 外の prediction_id を持つ EvaluationRecord は metric に影響しない。
凍結 `CalibrationLineage` の `prediction_record_count` / `evaluation_record_count` は**供給された
source record の件数**（重複検査後）を意味し、`cohort_digest` は選ばれた予測の id 集合、
`active_evaluation_digest` は cohort 内予測の active evaluation（または診断 status）の digest である。
cohort 内の `associated_evaluation_count` と `foreign_evaluation_count` は report 本体に別途載せる
（P5-3A の lineage 型は変えない）。

cohort（§7）: total / available / abstained と棄権率。棄権予測は ALL coverage に残り、ABSTAINED
診断（active EVALUATED の outcome / return）に入り、方向 exact match の分母に入らない。方向を
捏造しない。confidence 別集計は **AVAILABLE 予測のみ**を対象にする（unavailable の
direction_mixed / direction_uncertain が持つ confidence は outlook の属性であり、方向予測が無い）。

方向 exact match（§9）: 凍結 `directional_exact_match`。分母 = available かつ active EVALUATED。
5 × 3 混同行列（§10）: 同じ eligible 集合、行は 5 level・列は UP / RANGE / DOWN、零行も可視、
合計 = exact match の分母。level 別（§11）/ confidence 別（§12）/ level × confidence（§13）/
棄権（§14）/ 連続 return（§15。凍結 `summarize_returns`）/ sample disclosure（§16。凍結
`sample_disclosure:1.0.0`。exact match は分母、頻度は outcome 件数、ReturnSummary は n）。

空 cohort（§21）は例外ではなく、件数 0・分母 0・値 None・NO_DATA・5 行・3 bucket・15 cell の
有効な report。決定論（§22）: 入力 iterable の順序は counts / resolver / rates / summaries / matrix /
digest のいずれにも影響しない（集計のためだけに id でソートする）。重複 id（§23）は
`CalibrationInputError` で fail closed（黙って二重計上しない）。read-only（§25）: 入力 record を
変更しない。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..reports.market_signal import SignalLevel
from .calibration_contract import (
    ACTIVE_EVALUATION_RESOLVER_VERSION,
    CALIBRATION_CONTRACT_VERSION,
    CONFIDENCE_BUCKETS,
    LEVEL_ROWS,
    OUTCOME_COLUMNS,
    PREDICTION_DIRECTION_MAPPING_VERSION,
    SAMPLE_DISCLOSURE_VERSION,
    ActiveEvaluation,
    CalibrationLineage,
    CohortBoundary,
    EvaluationCoverage,
    OutcomeCounts,
    Rate,
    ResolutionStatus,
    ReturnSummary,
    active_evaluation_digest,
    cohort_digest,
    count_outcomes,
    directional_exact_match,
    resolve_active_evaluation,
    summarize_returns,
    unique_session_count,
)
from .evaluation_record import EvaluationRecord, RealizedOutcome
from .prediction_record import PredictionRecord

#: analyzer 出力の schema 版（写像 / resolver / disclosure / 分類の版とは別概念）
CALIBRATION_REPORT_SCHEMA_VERSION = "calibration_report:0.1.0"

#: UNRESOLVED に数える resolver 診断（凍結 ResolutionStatus のうち RESOLVED / NO_EVALUATION 以外）
UNRESOLVED_STATUSES: Tuple[ResolutionStatus, ...] = tuple(
    s for s in ResolutionStatus if s not in (ResolutionStatus.RESOLVED, ResolutionStatus.NO_EVALUATION))


class CalibrationInputError(ValueError):
    """契約外の入力（型・重複 id）。黙って二重計上せず fail closed。"""


# ---------------------------------------------------------------- report model（frozen）

@dataclass(frozen=True)
class CoverageCounts:
    """予測集合の評価 coverage（各予測はちょうど 1 つの bucket に入る）。"""

    predictions: int
    active_evaluated: int
    active_deferred: int
    no_evaluation: int
    unresolved: int
    unresolved_by_status: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.active_evaluated + self.active_deferred + self.no_evaluation + self.unresolved != self.predictions:
            raise CalibrationInputError("coverage buckets must partition the predictions")

    @property
    def completion_rate(self) -> Rate:          # evaluation_completion_rate（分母 predictions_in_cohort）
        return Rate(self.active_evaluated, self.predictions)

    @property
    def active_deferred_rate(self) -> Rate:
        return Rate(self.active_deferred, self.predictions)

    @property
    def no_evaluation_rate(self) -> Rate:
        return Rate(self.no_evaluation, self.predictions)

    def as_dict(self) -> Dict[str, object]:
        return {
            "predictions": self.predictions,
            "active_evaluated": self.active_evaluated,
            "active_deferred": self.active_deferred,
            "no_evaluation": self.no_evaluation,
            "unresolved": self.unresolved,
            "unresolved_by_status": {s.value: self.unresolved_by_status.get(s.value, 0)
                                     for s in UNRESOLVED_STATUSES},
            "evaluation_completion_rate": self.completion_rate.as_dict(),
            "active_deferred_rate": self.active_deferred_rate.as_dict(),
            "no_evaluation_rate": self.no_evaluation_rate.as_dict(),
        }


@dataclass(frozen=True)
class OutcomeSummary:
    """eligible な active EVALUATED 観測の outcome 件数・歴史的頻度・連続 return 要約。"""

    outcomes: OutcomeCounts
    returns: ReturnSummary

    def frequency(self, outcome: RealizedOutcome) -> Rate:
        count = {RealizedOutcome.UP: self.outcomes.up, RealizedOutcome.RANGE: self.outcomes.range,
                 RealizedOutcome.DOWN: self.outcomes.down}[outcome]
        return Rate(count, self.outcomes.total)

    def as_dict(self) -> Dict[str, object]:
        return {
            "outcomes": self.outcomes.as_dict(),
            "outcome_frequencies": {o.value: self.frequency(o).as_dict() for o in OUTCOME_COLUMNS},
            "returns": self.returns.as_dict(),
        }


@dataclass(frozen=True)
class GroupSummary:
    """level / confidence / level × confidence の共通要約（available 予測の部分集合）。"""

    key: str
    coverage: CoverageCounts
    directional_match: Rate                  # 分母 = この group の available かつ active EVALUATED
    outcome: OutcomeSummary

    def as_dict(self) -> Dict[str, object]:
        return {"key": self.key, "coverage": self.coverage.as_dict(),
                "directional_exact_match": self.directional_match.as_dict(),
                **self.outcome.as_dict()}


@dataclass(frozen=True)
class AbstentionSummary:
    """棄権予測の診断（方向 exact match は計算しない・方向を捏造しない）。"""

    total_predictions: int
    available: int
    abstained: int
    coverage: CoverageCounts                 # abstained 予測の coverage
    outcome: OutcomeSummary                  # abstained かつ active EVALUATED の市場 outcome

    @property
    def abstention_rate(self) -> Rate:       # abstention_rate（分母 total_predictions）
        return Rate(self.abstained, self.total_predictions)

    def as_dict(self) -> Dict[str, object]:
        return {"total_predictions": self.total_predictions, "available": self.available,
                "abstained": self.abstained, "abstention_rate": self.abstention_rate.as_dict(),
                "coverage": self.coverage.as_dict(), **self.outcome.as_dict()}


@dataclass(frozen=True)
class ConfusionMatrix:
    """5 level × 3 realized outcome の件数（eligible = available かつ active EVALUATED）。"""

    rows: Mapping[SignalLevel, OutcomeCounts]

    def __post_init__(self) -> None:
        if tuple(self.rows) != LEVEL_ROWS:
            raise CalibrationInputError("confusion matrix must carry exactly the five level rows")

    @property
    def total(self) -> int:
        return sum(c.total for c in self.rows.values())

    def as_dict(self) -> Dict[str, object]:
        return {
            "rows": {level.value: {**self.rows[level].as_dict(),
                                   "row_frequencies": {o.value: Rate(getattr(self.rows[level], o.value.lower()),
                                                                     self.rows[level].total).as_dict()
                                                       for o in OUTCOME_COLUMNS}}
                     for level in LEVEL_ROWS},
            "columns": [o.value for o in OUTCOME_COLUMNS],
            "total": self.total,
        }


@dataclass(frozen=True)
class CalibrationReport:
    schema_version: str
    cohort: CohortBoundary
    prediction_count: int
    unique_session_count: int
    supplied_prediction_count: int
    supplied_evaluation_count: int
    associated_evaluation_count: int
    foreign_evaluation_count: int
    coverage: CoverageCounts
    abstention: AbstentionSummary
    directional_match: Rate                  # AVAILABLE かつ active EVALUATED（cohort 全体）
    overall: OutcomeSummary                  # AVAILABLE かつ active EVALUATED の outcome / return
    confusion_matrix: ConfusionMatrix
    level_summaries: Tuple[GroupSummary, ...]
    confidence_summaries: Tuple[GroupSummary, ...]
    level_confidence: Tuple[GroupSummary, ...]
    classification_versions: Tuple[str, ...]
    unresolved_prediction_ids: Tuple[str, ...]
    lineage: CalibrationLineage

    def as_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "versions": {
                "calibration_report": self.schema_version,
                "calibration_contract": CALIBRATION_CONTRACT_VERSION,
                "prediction_direction_mapping": PREDICTION_DIRECTION_MAPPING_VERSION,
                "active_evaluation_resolver": ACTIVE_EVALUATION_RESOLVER_VERSION,
                "sample_disclosure": SAMPLE_DISCLOSURE_VERSION,
                "realized_classification": list(self.classification_versions),
            },
            "cohort": self.cohort.as_dict(),
            "prediction_count": self.prediction_count,
            "unique_session_count": self.unique_session_count,
            "supplied_prediction_count": self.supplied_prediction_count,
            "supplied_evaluation_count": self.supplied_evaluation_count,
            "associated_evaluation_count": self.associated_evaluation_count,
            "foreign_evaluation_count": self.foreign_evaluation_count,
            "coverage": self.coverage.as_dict(),
            "abstention": self.abstention.as_dict(),
            "directional_exact_match": self.directional_match.as_dict(),
            "overall": self.overall.as_dict(),
            "confusion_matrix": self.confusion_matrix.as_dict(),
            "level_summaries": [s.as_dict() for s in self.level_summaries],
            "confidence_summaries": [s.as_dict() for s in self.confidence_summaries],
            "level_confidence": [s.as_dict() for s in self.level_confidence],
            "unresolved_prediction_ids": list(self.unresolved_prediction_ids),
            "lineage": self.lineage.as_dict(),
        }


# ---------------------------------------------------------------- analyzer

@dataclass(frozen=True)
class _Association:
    """選ばれた予測 1 件と凍結 resolver の結果（内部）。"""

    prediction: PredictionRecord
    resolution: ActiveEvaluation

    @property
    def coverage(self) -> EvaluationCoverage:
        return self.resolution.coverage

    @property
    def eligible(self) -> bool:
        """方向 exact match / outcome / 混同行列の eligible: available かつ active EVALUATED。"""
        return self.prediction.available and self.coverage is EvaluationCoverage.ACTIVE_EVALUATED

    @property
    def active(self) -> Optional[EvaluationRecord]:
        return self.resolution.active if self.coverage is EvaluationCoverage.ACTIVE_EVALUATED else None


def analyze_calibration(predictions: Iterable[PredictionRecord],
                        evaluations: Iterable[EvaluationRecord],
                        cohort: CohortBoundary) -> CalibrationReport:
    """凍結 record と明示 cohort → 決定論的 CalibrationReport（純関数・read-only）。"""
    if not isinstance(cohort, CohortBoundary):
        raise CalibrationInputError("cohort must be a CohortBoundary")
    supplied_predictions = _unique_predictions(predictions)
    supplied_evaluations = _unique_evaluations(evaluations)

    selected = cohort.select(supplied_predictions.values())                # prediction_id 順
    selected_ids = {p.prediction_id for p in selected}
    by_prediction: Dict[str, List[EvaluationRecord]] = {}
    for evaluation in sorted(supplied_evaluations.values(), key=lambda e: e.evaluation_id):
        if evaluation.prediction_id in selected_ids:
            by_prediction.setdefault(evaluation.prediction_id, []).append(evaluation)
    associated = sum(len(v) for v in by_prediction.values())

    associations = tuple(_Association(
        prediction=p,
        resolution=resolve_active_evaluation(p.prediction_id, by_prediction.get(p.prediction_id, ())))
        for p in selected)

    available = tuple(o for o in associations if o.prediction.available)
    abstained = tuple(o for o in associations if not o.prediction.available)
    eligible = tuple(o for o in available if o.eligible)

    level_summaries = tuple(
        _group_summary(level.value, tuple(o for o in available if o.prediction.level is level))
        for level in LEVEL_ROWS)
    confidence_summaries = tuple(
        _group_summary(confidence, tuple(o for o in available if o.prediction.confidence == confidence))
        for confidence in CONFIDENCE_BUCKETS)
    level_confidence = tuple(
        _group_summary(f"{level.value}|{confidence}",
                       tuple(o for o in available
                             if o.prediction.level is level and o.prediction.confidence == confidence))
        for level in LEVEL_ROWS for confidence in CONFIDENCE_BUCKETS)

    matrix = ConfusionMatrix(rows={
        level: count_outcomes(o.active.realized_outcome for o in eligible if o.prediction.level is level)
        for level in LEVEL_ROWS})

    abstained_evaluated = tuple(o for o in abstained if o.coverage is EvaluationCoverage.ACTIVE_EVALUATED)
    abstention = AbstentionSummary(
        total_predictions=len(associations), available=len(available), abstained=len(abstained),
        coverage=_coverage(abstained), outcome=_outcome_summary(abstained_evaluated))

    versions = tuple(sorted({o.active.classification_version for o in associations
                             if o.coverage is EvaluationCoverage.ACTIVE_EVALUATED}))
    unresolved_ids = tuple(o.prediction.prediction_id for o in associations
                           if o.coverage is EvaluationCoverage.UNRESOLVED)

    lineage = CalibrationLineage(
        prediction_record_count=len(supplied_predictions),
        evaluation_record_count=len(supplied_evaluations),
        cohort_digest=cohort_digest(selected),
        active_evaluation_digest=active_evaluation_digest(o.resolution for o in associations))

    return CalibrationReport(
        schema_version=CALIBRATION_REPORT_SCHEMA_VERSION,
        cohort=cohort,
        prediction_count=len(associations),
        unique_session_count=unique_session_count(selected),
        supplied_prediction_count=len(supplied_predictions),
        supplied_evaluation_count=len(supplied_evaluations),
        associated_evaluation_count=associated,
        foreign_evaluation_count=len(supplied_evaluations) - associated,
        coverage=_coverage(associations),
        abstention=abstention,
        directional_match=_directional_match(eligible),
        overall=_outcome_summary(eligible),
        confusion_matrix=matrix,
        level_summaries=level_summaries,
        confidence_summaries=confidence_summaries,
        level_confidence=level_confidence,
        classification_versions=versions,
        unresolved_prediction_ids=unresolved_ids,
        lineage=lineage,
    )


# ---------------------------------------------------------------- internals（凍結 helper の組み合わせのみ）

def _unique_predictions(predictions: Iterable[PredictionRecord]) -> Dict[str, PredictionRecord]:
    out: Dict[str, PredictionRecord] = {}
    for record in predictions:
        if not isinstance(record, PredictionRecord):
            raise CalibrationInputError("predictions must contain PredictionRecord only")
        if record.prediction_id in out:
            raise CalibrationInputError(f"duplicate prediction_id in input: {record.prediction_id}")
        out[record.prediction_id] = record
    return out


def _unique_evaluations(evaluations: Iterable[EvaluationRecord]) -> Dict[str, EvaluationRecord]:
    out: Dict[str, EvaluationRecord] = {}
    for record in evaluations:
        if not isinstance(record, EvaluationRecord):
            raise CalibrationInputError("evaluations must contain EvaluationRecord only")
        if record.evaluation_id in out:
            raise CalibrationInputError(f"duplicate evaluation_id in input: {record.evaluation_id}")
        out[record.evaluation_id] = record
    return out


def _coverage(associations: Sequence[_Association]) -> CoverageCounts:
    buckets = {c: 0 for c in EvaluationCoverage}
    by_status: Dict[str, int] = {}
    for o in associations:
        buckets[o.coverage] += 1
        if o.coverage is EvaluationCoverage.UNRESOLVED:
            key = o.resolution.status.value
            by_status[key] = by_status.get(key, 0) + 1
    return CoverageCounts(
        predictions=len(associations),
        active_evaluated=buckets[EvaluationCoverage.ACTIVE_EVALUATED],
        active_deferred=buckets[EvaluationCoverage.ACTIVE_DEFERRED],
        no_evaluation=buckets[EvaluationCoverage.NO_EVALUATION],
        unresolved=buckets[EvaluationCoverage.UNRESOLVED],
        unresolved_by_status=dict(sorted(by_status.items())))


def _directional_match(eligible: Sequence[_Association]) -> Rate:
    matches = sum(1 for o in eligible
                  if directional_exact_match(o.prediction.level, o.active.realized_outcome))
    return Rate(matches, len(eligible))


def _outcome_summary(evaluated: Sequence[_Association]) -> OutcomeSummary:
    records = tuple(o.active for o in evaluated)
    return OutcomeSummary(outcomes=count_outcomes(r.realized_outcome for r in records),
                          returns=summarize_returns(records))


def _group_summary(key: str, members: Sequence[_Association]) -> GroupSummary:
    eligible = tuple(o for o in members if o.eligible)
    return GroupSummary(key=key, coverage=_coverage(members),
                        directional_match=_directional_match(eligible),
                        outcome=_outcome_summary(eligible))
