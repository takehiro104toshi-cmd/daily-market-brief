"""calibration_contract — Phase 5 P5-3A（較正の分析契約 ＋ metric 仕様。SPECIFICATION FIRST）。

P5-3 は **観測的 analytics** である。凍結された PredictionRecord と EvaluationRecord の歴史的関係を
記述するだけであり、PredictionRecord / EvaluationRecord / MarketSignal / Compass DNA を書き換えず、
閾値や confidence を自動調整せず、売買推奨も因果主張も将来の予測力の主張もしない。
較正の出力は分析であって production authority ではない。

本 module が凍結するのは **契約と純粋 helper だけ**である（journal を読む analyzer は P5-3B、
persistence は無い）:

1. **分析用の方向写像**（`prediction_direction_mapping:1.0.0`）
       UPWARD_LEAN / SLIGHT_UPWARD_LEAN  → predicted_direction UP
       NEUTRAL_RANGE                     → predicted_direction RANGE
       SLIGHT_DOWNWARD_LEAN / DOWNWARD_LEAN → predicted_direction DOWN
   これは P4 `LEVEL_BY_STATE` の方向成分（UPWARD_BIAS / RANGE_BOUND / DOWNWARD_BIAS）の逆射影で
   あり、SLIGHT_* と非 SLIGHT の差は confidence LOW か否かでしかない。**分析専用**であり、保存
   record の 5 level を畳まず、MarketSignal の意味論を変えない。
2. **active evaluation の解決**（`active_evaluation_resolver:1.0.0`）: EvaluationStore は「最新 /
   現在」を定義しない。分析は supersession graph の意味論で 1 つの active evaluation を決める。
   superseded された評価は歴史的証拠として残るが outcome metric の active には使わない。
   **created_at で選ばない。物理的な最終行を意味の権威にしない。** fork（1 つの前任に 2 つ以上の
   後継）・複数の独立した terminal・dangling・subject 不一致・重複 id は fail closed
   （`ResolutionStatus` の診断付きで除外し、黙って推測しない）。
3. **cohort**: origin（LIVE / REPLAY は既定で pool しない。COMBINED headline は持たない）×
   session 範囲（PredictionRecord.session_date による閉区間。EvaluationRecord.created_at は
   期間の定義に使わない）。予測 cohort は ALL / AVAILABLE / ABSTAINED を黙って merge しない。
   同一 session_date の複数 prediction_id は date で dedupe せず、prediction 件数と
   unique session 件数を両方報告する。
4. **DEFERRED / 評価なし**: DEFERRED は realized outcome ではなく、UP / RANGE / DOWN の分母に
   入らない。coverage（ACTIVE_EVALUATED / ACTIVE_DEFERRED / NO_EVALUATION / UNRESOLVED）は別集計。
5. **棄権**: `available == false` は wrong / RANGE / zero / DEFERRED として採点しない。
   棄権予測の active EVALUATED outcome は棄権診断（「見送った日に何が起きたか」）にだけ使える。
6. **分母**: すべての rate は numerator / denominator を露出する（`Rate`）。分母は
   `Denominator` の凍結語彙で名指しし、黙って切り替えない。
7. **sample disclosure**（`sample_disclosure:1.0.0`）: N = 0 NO_DATA / 1–9 INSUFFICIENT_SAMPLE /
   10–29 LIMITED_SAMPLE / 30 以上 REPORTABLE。統計的有意性ではなく開示ラベル。生の件数は常に
   出せるが、率の解釈は disclosure を伴う。信頼区間は作らない。
8. **数値方針**: 件数は int、率と return 統計は Decimal（`RATE_CONTEXT` prec 28 / ROUND_HALF_EVEN、
   内部で黙って丸めない。表示丸めは後段）。float は権威にしない。
9. **lineage**: 版 4 種 ＋ record 件数 ＋ cohort digest（prediction_id の集合の content digest）＋
   active evaluation digest。hash chain ではない。

依存: 凍結 PredictionRecord / EvaluationRecord と `core.ids` / `reports.market_signal`（SignalLevel）
のみ。store は不要（record の iterable を受ける）。J-Quants / market Observation / tokyo_calendar /
evaluation_engine / P4 pipeline / 顧客 rendering に依存しない。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..reports.market_signal import SignalLevel
from .evaluation_record import EvaluationRecord, EvaluationStatus, RealizedOutcome, canonical_decimal
from .prediction_record import PredictionOrigin, PredictionRecord

# ---------------------------------------------------------------- versions（3 つの契約版 ＋ 本 module の版）

CALIBRATION_CONTRACT_VERSION = "calibration_contract:0.1.0"
PREDICTION_DIRECTION_MAPPING_VERSION = "prediction_direction_mapping:1.0.0"
SAMPLE_DISCLOSURE_VERSION = "sample_disclosure:1.0.0"
ACTIVE_EVALUATION_RESOLVER_VERSION = "active_evaluation_resolver:1.0.0"

#: 率・return 統計の算術 context（呼び出し側の decimal context に依存しない）
RATE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)

#: 混同行列の行（5 level・保存 record の語彙をそのまま）と列（3 realized outcome）
LEVEL_ROWS: Tuple[SignalLevel, ...] = tuple(SignalLevel)
OUTCOME_COLUMNS: Tuple[RealizedOutcome, ...] = tuple(RealizedOutcome)
CONFIDENCE_BUCKETS: Tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")


class CalibrationContractError(ValueError):
    """契約外の入力（fail closed）。"""


# ---------------------------------------------------------------- 1. 方向写像（分析専用）

class PredictedDirection(str, Enum):
    """分析用の予測方向。realized outcome（UP / RANGE / DOWN）とは別概念で、値だけを比較する。"""

    UP = "UP"
    RANGE = "RANGE"
    DOWN = "DOWN"


PREDICTION_DIRECTION_MAPPING: Mapping[SignalLevel, PredictedDirection] = {
    SignalLevel.UPWARD_LEAN: PredictedDirection.UP,
    SignalLevel.SLIGHT_UPWARD_LEAN: PredictedDirection.UP,
    SignalLevel.NEUTRAL_RANGE: PredictedDirection.RANGE,
    SignalLevel.SLIGHT_DOWNWARD_LEAN: PredictedDirection.DOWN,
    SignalLevel.DOWNWARD_LEAN: PredictedDirection.DOWN,
}


def predicted_direction(level: SignalLevel) -> PredictedDirection:
    if not isinstance(level, SignalLevel):
        raise CalibrationContractError("predicted_direction requires a SignalLevel")
    return PREDICTION_DIRECTION_MAPPING[level]


def directional_exact_match(level: SignalLevel, outcome: RealizedOutcome) -> bool:
    """歴史的な exact match（記述統計）。確率・将来精度・skill score ではない。"""
    if not isinstance(outcome, RealizedOutcome):
        raise CalibrationContractError("directional_exact_match requires a RealizedOutcome")
    return predicted_direction(level).value == outcome.value


# ---------------------------------------------------------------- 3. cohort

class PredictionCohort(str, Enum):
    ALL = "ALL"
    AVAILABLE = "AVAILABLE"
    ABSTAINED = "ABSTAINED"


def prediction_cohorts(prediction: PredictionRecord) -> Tuple[PredictionCohort, ...]:
    """予測が属する cohort（ALL ＋ AVAILABLE または ABSTAINED。黙って merge しない）。"""
    if not isinstance(prediction, PredictionRecord):
        raise CalibrationContractError("prediction_cohorts requires a PredictionRecord")
    second = PredictionCohort.AVAILABLE if prediction.available else PredictionCohort.ABSTAINED
    return (PredictionCohort.ALL, second)


@dataclass(frozen=True)
class CohortBoundary:
    """明示的な cohort 境界: origin ＋ PredictionRecord.session_date の閉区間。既定の「全履歴」は無い。"""

    origin: PredictionOrigin
    start_session: str
    end_session: str

    def __post_init__(self) -> None:
        if not isinstance(self.origin, PredictionOrigin):
            raise CalibrationContractError("origin must be PredictionOrigin (LIVE / REPLAY)")
        for name in ("start_session", "end_session"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
                raise CalibrationContractError(f"{name} must be an ISO date YYYY-MM-DD")
        if self.start_session > self.end_session:
            raise CalibrationContractError("start_session must not be after end_session")

    def contains(self, prediction: PredictionRecord) -> bool:
        if not isinstance(prediction, PredictionRecord):
            raise CalibrationContractError("contains requires a PredictionRecord")
        return (prediction.origin is self.origin
                and self.start_session <= prediction.session_date <= self.end_session)

    def select(self, predictions: Iterable[PredictionRecord]) -> Tuple[PredictionRecord, ...]:
        """境界内の予測を prediction_id 順で返す（date で dedupe しない）。"""
        return tuple(sorted((p for p in predictions if self.contains(p)), key=lambda p: p.prediction_id))

    @property
    def label(self) -> str:
        return f"{self.origin.value} {self.start_session}..{self.end_session}"

    def as_dict(self) -> Dict[str, object]:
        return {"origin": self.origin.value, "start_session": self.start_session,
                "end_session": self.end_session}


def unique_session_count(predictions: Iterable[PredictionRecord]) -> int:
    return len({p.session_date for p in predictions})


# ---------------------------------------------------------------- 7. sample disclosure

class SampleDisclosure(str, Enum):
    NO_DATA = "NO_DATA"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    LIMITED_SAMPLE = "LIMITED_SAMPLE"
    REPORTABLE = "REPORTABLE"


#: (LIMITED の下限, REPORTABLE の下限)。統計的有意性の閾値ではなく開示ラベルの境界。
SAMPLE_DISCLOSURE_THRESHOLDS: Tuple[int, int] = (10, 30)


def sample_disclosure(n: int) -> SampleDisclosure:
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise CalibrationContractError("sample size must be a non-negative int")
    limited, reportable = SAMPLE_DISCLOSURE_THRESHOLDS
    if n == 0:
        return SampleDisclosure.NO_DATA
    if n < limited:
        return SampleDisclosure.INSUFFICIENT_SAMPLE
    if n < reportable:
        return SampleDisclosure.LIMITED_SAMPLE
    return SampleDisclosure.REPORTABLE


# ---------------------------------------------------------------- 6. 分母と rate

class Denominator(str, Enum):
    TOTAL_PREDICTIONS = "total_predictions"
    AVAILABLE_PREDICTIONS = "available_predictions"
    ABSTAINED_PREDICTIONS = "abstained_predictions"
    PREDICTIONS_IN_COHORT = "predictions_in_cohort"
    AVAILABLE_WITH_ACTIVE_EVALUATED = "available_with_active_evaluated"
    ABSTAINED_WITH_ACTIVE_EVALUATED = "abstained_with_active_evaluated"
    LEVEL_WITH_ACTIVE_EVALUATED = "level_with_active_evaluated"
    CONFIDENCE_PREDICTIONS = "confidence_predictions"
    CONFIDENCE_WITH_ACTIVE_EVALUATED = "confidence_with_active_evaluated"


class MetricKind(str, Enum):
    COVERAGE = "coverage"          # 評価 / 棄権の到達度
    DESCRIPTIVE = "descriptive"    # 歴史的頻度・return の記述統計
    EXACT_MATCH = "exact_match"    # 方向写像と realized outcome の歴史的一致率（採点ではない）


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    kind: MetricKind
    numerator: str
    denominator: Denominator


#: 凍結 metric 定義（分母の切り替えを禁じる。名前を変えずに分母を変えない）
METRIC_DEFINITIONS: Tuple[MetricDefinition, ...] = (
    MetricDefinition("abstention_rate", MetricKind.COVERAGE,
                     "abstained_predictions", Denominator.TOTAL_PREDICTIONS),
    MetricDefinition("evaluation_completion_rate", MetricKind.COVERAGE,
                     "predictions_with_active_evaluated", Denominator.PREDICTIONS_IN_COHORT),
    MetricDefinition("active_deferred_rate", MetricKind.COVERAGE,
                     "predictions_with_active_deferred", Denominator.PREDICTIONS_IN_COHORT),
    MetricDefinition("no_evaluation_rate", MetricKind.COVERAGE,
                     "predictions_without_evaluation", Denominator.PREDICTIONS_IN_COHORT),
    MetricDefinition("directional_exact_match_rate", MetricKind.EXACT_MATCH,
                     "directional_exact_matches", Denominator.AVAILABLE_WITH_ACTIVE_EVALUATED),
    MetricDefinition("level_outcome_frequency", MetricKind.DESCRIPTIVE,
                     "level_outcome_count", Denominator.LEVEL_WITH_ACTIVE_EVALUATED),
    MetricDefinition("abstained_outcome_frequency", MetricKind.DESCRIPTIVE,
                     "abstained_outcome_count", Denominator.ABSTAINED_WITH_ACTIVE_EVALUATED),
    MetricDefinition("confidence_completion_rate", MetricKind.COVERAGE,
                     "confidence_with_active_evaluated", Denominator.CONFIDENCE_PREDICTIONS),
    MetricDefinition("confidence_exact_match_rate", MetricKind.EXACT_MATCH,
                     "confidence_directional_exact_matches", Denominator.CONFIDENCE_WITH_ACTIVE_EVALUATED),
)
METRIC_BY_NAME: Mapping[str, MetricDefinition] = {m.name: m for m in METRIC_DEFINITIONS}


@dataclass(frozen=True)
class Rate:
    """numerator / denominator を必ず露出する率。denominator 0 は値なし（NO_DATA）。"""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        for name in ("numerator", "denominator"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise CalibrationContractError(f"{name} must be a non-negative int")
        if self.numerator > self.denominator:
            raise CalibrationContractError("numerator cannot exceed denominator")

    @property
    def value(self) -> Optional[Decimal]:
        if self.denominator == 0:
            return None
        with localcontext(RATE_CONTEXT):
            return Decimal(self.numerator) / Decimal(self.denominator)

    @property
    def disclosure(self) -> SampleDisclosure:
        return sample_disclosure(self.denominator)

    def as_dict(self) -> Dict[str, object]:
        value = self.value
        return {"numerator": self.numerator, "denominator": self.denominator,
                "value": None if value is None else canonical_decimal(value),
                "disclosure": self.disclosure.value}


# ---------------------------------------------------------------- 2. active evaluation resolver

class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_EVALUATION = "NO_EVALUATION"
    MULTIPLE_TERMINALS = "MULTIPLE_TERMINALS"          # supersession の無い独立評価が複数
    FORK = "FORK"                                      # 1 つの前任に 2 つ以上の後継
    DANGLING_SUPERSESSION = "DANGLING_SUPERSESSION"    # 前任が与えられた評価の中に無い
    SUBJECT_MISMATCH = "SUBJECT_MISMATCH"              # 同じ prediction_id で subject が異なる
    DUPLICATE_ID = "DUPLICATE_ID"                      # 同じ evaluation_id で内容が異なる
    CYCLE = "CYCLE"


class EvaluationCoverage(str, Enum):
    ACTIVE_EVALUATED = "ACTIVE_EVALUATED"
    ACTIVE_DEFERRED = "ACTIVE_DEFERRED"
    NO_EVALUATION = "NO_EVALUATION"
    UNRESOLVED = "UNRESOLVED"                          # 診断付きで outcome metric から除外


_SUBJECT_FIELDS = ("target", "reference_session", "session_date", "classification_version")


@dataclass(frozen=True)
class ActiveEvaluation:
    prediction_id: str
    status: ResolutionStatus
    active: Optional[EvaluationRecord]
    chain_ids: Tuple[str, ...]          # root → active の supersession 経路（RESOLVED のとき）
    terminal_ids: Tuple[str, ...]       # superseded されていない評価（診断用）
    diagnostic: str = ""

    @property
    def coverage(self) -> EvaluationCoverage:
        if self.status is ResolutionStatus.NO_EVALUATION:
            return EvaluationCoverage.NO_EVALUATION
        if self.status is not ResolutionStatus.RESOLVED or self.active is None:
            return EvaluationCoverage.UNRESOLVED
        return (EvaluationCoverage.ACTIVE_EVALUATED if self.active.status is EvaluationStatus.EVALUATED
                else EvaluationCoverage.ACTIVE_DEFERRED)

    @property
    def realized_outcome(self) -> Optional[RealizedOutcome]:
        return self.active.realized_outcome if self.coverage is EvaluationCoverage.ACTIVE_EVALUATED else None

    @property
    def realized_return(self) -> Optional[Decimal]:
        return self.active.realized_return if self.coverage is EvaluationCoverage.ACTIVE_EVALUATED else None


def resolve_active_evaluation(prediction_id: str,
                              evaluations: Iterable[EvaluationRecord]) -> ActiveEvaluation:
    """supersession graph の意味論で active evaluation を 1 つ決める（順序・created_at 非依存）。"""
    mine: Dict[str, EvaluationRecord] = {}
    for record in evaluations:
        if not isinstance(record, EvaluationRecord):
            raise CalibrationContractError("evaluations must contain EvaluationRecord only")
        if record.prediction_id != prediction_id:
            continue
        existing = mine.get(record.evaluation_id)
        if existing is not None and existing != record:
            return ActiveEvaluation(prediction_id, ResolutionStatus.DUPLICATE_ID, None, (), (),
                                    f"{record.evaluation_id} appears with different content")
        mine[record.evaluation_id] = record
    if not mine:
        return ActiveEvaluation(prediction_id, ResolutionStatus.NO_EVALUATION, None, (), ())

    ordered = sorted(mine.values(), key=lambda e: e.evaluation_id)       # 決定論的な走査順（選択には使わない）
    subject = tuple(getattr(ordered[0], f) for f in _SUBJECT_FIELDS)
    for record in ordered:
        if tuple(getattr(record, f) for f in _SUBJECT_FIELDS) != subject:
            return ActiveEvaluation(prediction_id, ResolutionStatus.SUBJECT_MISMATCH, None, (),
                                    tuple(e.evaluation_id for e in ordered),
                                    f"{record.evaluation_id} has a different evaluation subject")
    successors: Dict[str, List[str]] = {}
    for record in ordered:
        predecessor = record.supersedes_evaluation_id
        if predecessor:
            if predecessor not in mine:
                return ActiveEvaluation(prediction_id, ResolutionStatus.DANGLING_SUPERSESSION, None, (),
                                        tuple(e.evaluation_id for e in ordered),
                                        f"{record.evaluation_id} supersedes unknown {predecessor}")
            successors.setdefault(predecessor, []).append(record.evaluation_id)
    for predecessor, followers in sorted(successors.items()):
        if len(followers) > 1:
            return ActiveEvaluation(prediction_id, ResolutionStatus.FORK, None, (),
                                    tuple(e.evaluation_id for e in ordered if e.evaluation_id not in successors),
                                    f"{predecessor} is superseded by {len(followers)} evaluations")
    terminals = tuple(e.evaluation_id for e in ordered if e.evaluation_id not in successors)
    if len(terminals) != 1:
        return ActiveEvaluation(prediction_id, ResolutionStatus.MULTIPLE_TERMINALS, None, (), terminals,
                                f"{len(terminals)} independent terminal evaluations")
    chain: List[str] = []
    cursor: Optional[str] = terminals[0]
    seen = set()
    while cursor:
        if cursor in seen:
            return ActiveEvaluation(prediction_id, ResolutionStatus.CYCLE, None, (), terminals,
                                    "supersession cycle")
        seen.add(cursor)
        chain.append(cursor)
        cursor = mine[cursor].supersedes_evaluation_id
    chain.reverse()
    return ActiveEvaluation(prediction_id, ResolutionStatus.RESOLVED, mine[terminals[0]],
                            tuple(chain), terminals)


# ---------------------------------------------------------------- 4 / 12. counts and return summaries

@dataclass(frozen=True)
class OutcomeCounts:
    up: int = 0
    range: int = 0
    down: int = 0

    @property
    def total(self) -> int:
        return self.up + self.range + self.down

    def as_dict(self) -> Dict[str, int]:
        return {"UP": self.up, "RANGE": self.range, "DOWN": self.down, "total": self.total}


def count_outcomes(outcomes: Iterable[RealizedOutcome]) -> OutcomeCounts:
    counts = {o: 0 for o in RealizedOutcome}
    for outcome in outcomes:
        if not isinstance(outcome, RealizedOutcome):
            raise CalibrationContractError("count_outcomes requires RealizedOutcome values")
        counts[outcome] += 1
    return OutcomeCounts(up=counts[RealizedOutcome.UP], range=counts[RealizedOutcome.RANGE],
                         down=counts[RealizedOutcome.DOWN])


@dataclass(frozen=True)
class ReturnSummary:
    """連続 realized_return の記述統計（Decimal）。Sharpe / 年率化 / P&L / 取引コストは無い。"""

    n: int
    mean: Optional[Decimal]
    median: Optional[Decimal]
    mean_abs: Optional[Decimal]
    minimum: Optional[Decimal]
    maximum: Optional[Decimal]
    outcomes: OutcomeCounts

    @property
    def disclosure(self) -> SampleDisclosure:
        return sample_disclosure(self.n)

    def as_dict(self) -> Dict[str, object]:
        opt = lambda v: None if v is None else canonical_decimal(v)      # noqa: E731
        return {"n": self.n, "mean": opt(self.mean), "median": opt(self.median),
                "mean_abs": opt(self.mean_abs), "min": opt(self.minimum), "max": opt(self.maximum),
                "outcomes": self.outcomes.as_dict(), "disclosure": self.disclosure.value}


def summarize_returns(records: Sequence[EvaluationRecord]) -> ReturnSummary:
    """EVALUATED record の realized_return を要約する（DEFERRED は fail closed）。"""
    values: List[Decimal] = []
    outcomes: List[RealizedOutcome] = []
    for record in records:
        if not isinstance(record, EvaluationRecord):
            raise CalibrationContractError("summarize_returns requires EvaluationRecord values")
        if record.status is not EvaluationStatus.EVALUATED or record.realized_return is None:
            raise CalibrationContractError("summarize_returns accepts EVALUATED records only")
        values.append(record.realized_return)
        outcomes.append(record.realized_outcome)
    counts = count_outcomes(outcomes)
    if not values:
        return ReturnSummary(0, None, None, None, None, None, counts)
    ordered = sorted(values)
    n = len(ordered)
    with localcontext(RATE_CONTEXT):
        mean = sum(ordered, Decimal(0)) / Decimal(n)
        mean_abs = sum((abs(v) for v in ordered), Decimal(0)) / Decimal(n)
        median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / Decimal(2)
    return ReturnSummary(n, mean, median, mean_abs, ordered[0], ordered[-1], counts)


# ---------------------------------------------------------------- 9. lineage / digests

def content_digest(ids: Iterable[str]) -> str:
    """決定論的な集合 digest（順序非依存・重複無視）。hash chain ではない。"""
    unique = sorted({i for i in ids if isinstance(i, str) and i})
    return content_id("cal", *unique) if unique else content_id("cal", "")


def cohort_digest(predictions: Iterable[PredictionRecord]) -> str:
    return content_digest(p.prediction_id for p in predictions)


def active_evaluation_digest(resolutions: Iterable[ActiveEvaluation]) -> str:
    """prediction ごとの active evaluation（または診断 status）の digest。訂正で active が変わると変わる。"""
    return content_digest(
        f"{r.prediction_id}:{r.active.evaluation_id if r.active is not None else r.status.value}"
        for r in resolutions)


@dataclass(frozen=True)
class CalibrationLineage:
    prediction_record_count: int
    evaluation_record_count: int
    cohort_digest: str
    active_evaluation_digest: str
    calibration_contract_version: str = CALIBRATION_CONTRACT_VERSION
    mapping_version: str = PREDICTION_DIRECTION_MAPPING_VERSION
    sample_disclosure_version: str = SAMPLE_DISCLOSURE_VERSION
    resolver_version: str = ACTIVE_EVALUATION_RESOLVER_VERSION

    def __post_init__(self) -> None:
        for name in ("prediction_record_count", "evaluation_record_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise CalibrationContractError(f"{name} must be a non-negative int")

    def as_dict(self) -> Dict[str, object]:
        return {
            "calibration_contract_version": self.calibration_contract_version,
            "mapping_version": self.mapping_version,
            "sample_disclosure_version": self.sample_disclosure_version,
            "resolver_version": self.resolver_version,
            "prediction_record_count": self.prediction_record_count,
            "evaluation_record_count": self.evaluation_record_count,
            "cohort_digest": self.cohort_digest,
            "active_evaluation_digest": self.active_evaluation_digest,
        }
