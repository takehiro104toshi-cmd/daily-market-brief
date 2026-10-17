"""evaluation_engine — Phase 5 P5-2C（OFFLINE 評価 engine）。

    PredictionRecord ＋ 検証済み東京 session 証拠 ＋ TOPIX close 観測 → EvaluationRecord

答える問い: 「既に手元にある point-in-time の予測と市場 / カレンダー証拠から、正しい不変の
EvaluationRecord を決定論的に生成できるか」。engine が評価するのは**市場 outcome**であり、
予測が正しかったかは評価しない（hit / miss / correct / accuracy / score / 5 level → 3 state の
写像は存在しない。較正は P5-3）。

権威となる入力境界（§3 / §18 / §19。既存の不変 domain object をそのまま使い、第二の市場 schema を
作らない）:

- 予測: 凍結 `PredictionRecord`（`prediction_id` / `session_date` / `reference_session`）。
  `available` は outcome 評価の前提条件ではない（§9）。
- カレンダー証拠: `CalendarEvidence`（J-Quants `/markets/calendar` 由来の行 ＋ その source id ＋
  信頼する区分値）。検証は既存 `market.tokyo_calendar` の `validate_divisions`（区分値の実測検証）
  と `trading_days` で行い、結果を情報を落とさず凍結 `SessionVerification` へ写す。
  **weekday 演算・金→月の推定・`reference_session < session_date` だけからの推定はしない。**
- 市場証拠: 既存 `market.model.Observation`（`series_id == index:topix.close.closing.tokyo`、
  `kind == raw`）。session は `trading_date` の**完全一致**で選ぶ（nearest / forward fill /
  backward fill / 補間 / latest close は無い）。改定は既存の権威 `latest_revisions()` で解決し、
  それでも同一 session に複数残れば曖昧として defer する（「最新が勝つ」を発明しない）。

realized return（§7）: `close(session_date) / close(reference_session) − 1` を Decimal で計算する。
算術 context は `RETURN_CONTEXT`（prec 28 / ROUND_HALF_EVEN）に固定し、呼び出し側の decimal
context に依存しない。分類は凍結 P5-2A の `classify_realized_return`（`make_evaluation_record`
経由）に委ね、閾値定数を本 module に持たない。

defer の優先順位（§10。同じ入力なら list の順序に関わらず同じ理由）:

    1. source_unsupported            … 選ばれた観測の source / schema 版が未対応、または reference と
                                       target の source / schema が一致しない（provenance は 1 つの
                                       coherent な source を要求する）
    2. calendar_unverified           … 区分値の実測検証が成立しない（rows 無し・source id 無し・食い違い・
                                       検証材料となる TOPIX 観測日がカレンダー範囲内に 1 つも無い）
    3. reference_session_unverified  … session_date が検証済み取引日でない、または直前の検証済み
                                       取引日が reference_session と一致しない
    4. observation_invalid           … 同一 session に複数の未解決観測 / 欠測値 / 非正 / 非有限 /
                                       系列識別の矛盾（entity / metric / unit）/ 失効（valid_until）
    5. reference_close_unavailable   … reference_session の観測が無い
    6. target_close_unavailable      … session_date の観測が無い

DEFERRED の provenance（§12）: 検証結果（SessionVerification）と、支持・妥当性検査を通った側の
close / observation id / source / schema を、凍結 schema が許す範囲で保持する。捏造も消去もしない。

純粋 / offline（§17）: filesystem・環境変数・network・J-Quants・現在時刻・乱数・git に触れない。
`created_at` と任意の `supersedes_evaluation_id` は呼び出し側が明示する（前の評価の自動探索・
chain 解決はしない）。`evaluate_and_append` は `evaluate_prediction` → 凍結
`EvaluationStore.append` を呼ぶだけの薄い helper であり、conflict を握り潰さない。

look-ahead 汚染の禁止（§20）: 本 module は評価専用の下流であり、PredictionRecord / MorningBrief /
MarketSignal / CompassDraft / P4 生成へ流れる経路を持たない（P4 本番 closure から到達不能）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION as OBSERVATION_SCHEMA_VERSION
from ..market.model import Observation, ObservationKind, latest_revisions
from ..market.tokyo_calendar import DEFAULT_TRADING_DIVISIONS, trading_days, validate_divisions
from .evaluation_record import (
    TARGET_TOPIX,
    DeferReason,
    EvaluationRecord,
    EvaluationStatus,
    SessionVerification,
    make_evaluation_record,
)
from .evaluation_store import EvaluationAppendResult, EvaluationStore
from .prediction_record import PredictionRecord

#: 本番 TOPIX 取り込みの provider id（`market.ingest` は `result.provider_id` を source_id に写す。
#: J-Quants First / NO PROXY SUBSTITUTION: 別 source の close を代用しない）
SUPPORTED_SOURCE_IDS: Tuple[str, ...] = ("jquants",)
#: 受理する Observation schema 版（`core.types.SCHEMA_VERSION` が権威。未知版は best effort しない）
SUPPORTED_OBSERVATION_SCHEMA_VERSIONS: Tuple[str, ...] = (OBSERVATION_SCHEMA_VERSION,)

#: TOPIX close 観測の系列識別（`knowledge/market_series/core_series.yaml` の凍結 identity）
TARGET_SERIES_ID = TARGET_TOPIX
TARGET_ENTITY_ID = "index:topix"
TARGET_METRIC = "close"
TARGET_UNIT = "index"

#: realized return の算術 context（呼び出し側の context に依存しない決定論的 Decimal 算術）
RETURN_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)

#: defer の優先順位（凍結。同じ入力 → 同じ理由）
DEFER_PRECEDENCE: Tuple[DeferReason, ...] = (
    DeferReason.SOURCE_UNSUPPORTED,
    DeferReason.CALENDAR_UNVERIFIED,
    DeferReason.REFERENCE_SESSION_UNVERIFIED,
    DeferReason.OBSERVATION_INVALID,
    DeferReason.REFERENCE_CLOSE_UNAVAILABLE,
    DeferReason.TARGET_CLOSE_UNAVAILABLE,
)


class EvaluationInputError(ValueError):
    """入力そのものが契約外（型・naive datetime 等）。defer ではなく fail closed。"""


@dataclass(frozen=True)
class CalendarEvidence:
    """東京取引カレンダーの証拠（J-Quants `/markets/calendar` 由来の行と、その source id）。"""

    calendar_source_id: str
    rows: Tuple[Mapping[str, object], ...]
    trading_divisions: Tuple[str, ...] = DEFAULT_TRADING_DIVISIONS

    def __post_init__(self) -> None:
        if not isinstance(self.calendar_source_id, str):
            raise EvaluationInputError("calendar_source_id must be str")
        if not isinstance(self.rows, tuple) or not all(isinstance(r, Mapping) for r in self.rows):
            raise EvaluationInputError("rows must be a tuple of mappings")
        if (not isinstance(self.trading_divisions, tuple) or not self.trading_divisions
                or not all(isinstance(d, str) and d for d in self.trading_divisions)):
            raise EvaluationInputError("trading_divisions must be a non-empty tuple of strings")


@dataclass(frozen=True)
class _SessionEvidence:
    """1 session 分の観測選択結果（内部。決定論的に導出）。"""

    session: str
    candidates: Tuple[Observation, ...]      # 改定解決後に trading_date が一致した観測（0 / 1 / 複数）

    @property
    def observation(self) -> Optional[Observation]:
        return self.candidates[0] if len(self.candidates) == 1 else None

    @property
    def invalid(self) -> bool:
        if not self.candidates:
            return False                                       # 欠落は「無効」ではなく「無し」
        if len(self.candidates) != 1:
            return True                                        # 未解決の複数観測は曖昧
        return not _observation_is_valid(self.candidates[0])

    @property
    def usable(self) -> bool:
        return self.observation is not None and not self.invalid


# ---------------------------------------------------------------- calendar（§5 / §18）

def verify_sessions(calendar: CalendarEvidence, *, session_date: str,
                    observed_trading_dates: Sequence[str]) -> SessionVerification:
    """既存 `validate_divisions` / `trading_days` の結果を凍結 `SessionVerification` へ写す。

    `verified_session` は session_date が検証済み取引日のときだけ、`verified_previous_session` は
    カレンダー範囲内でその直前の取引日が存在するときだけ埋まる（無ければ空 = 立証できない）。
    """
    if not isinstance(calendar, CalendarEvidence):
        raise EvaluationInputError("calendar_evidence must be CalendarEvidence")
    rows = [dict(r) for r in calendar.rows]
    validation = validate_divisions(rows, sorted(set(observed_trading_dates)),
                                    trading_divisions=calendar.trading_divisions)
    days = trading_days(rows, trading_divisions=calendar.trading_divisions)
    verified_session = session_date if session_date in days else ""
    previous = [d for d in days if d < session_date]
    verified_previous = previous[-1] if verified_session and previous else ""
    return SessionVerification(
        calendar_source_id=calendar.calendar_source_id,
        trading_divisions=tuple(calendar.trading_divisions),
        checked_dates=validation.checked_dates,
        agreements=validation.agreements,
        disagreement_count=len(validation.disagreements),
        verified_session=verified_session,
        verified_previous_session=verified_previous,
    )


# ---------------------------------------------------------------- market（§6 / §14 / §19）

def _observation_is_valid(observation: Observation) -> bool:
    value = observation.value
    return (
        observation.entity_id == TARGET_ENTITY_ID
        and observation.metric == TARGET_METRIC
        and observation.unit == TARGET_UNIT
        and observation.valid_until is None
        and isinstance(value, Decimal)
        and value.is_finite()
        and value > 0
    )


def resolve_topix_observations(market_evidence: Sequence[Observation]) -> Tuple[Observation, ...]:
    """供給された証拠から TOPIX raw 観測だけを決定論的順序で取り出し、改定を既存規則で解決する。

    返る観測の `trading_date` 全体がカレンダー区分の実測検証（`validate_divisions`）の材料になる
    （非取引日に観測があればカレンダーを信頼しない = 既存 store / 研究 driver と同じ意味論）。
    """
    for observation in market_evidence:
        if not isinstance(observation, Observation):
            raise EvaluationInputError("market_evidence must contain market.model.Observation only")
    candidates = sorted(
        (o for o in market_evidence
         if o.series_id == TARGET_SERIES_ID and o.kind is ObservationKind.RAW),
        key=lambda o: (o.trading_date, o.observation_id))
    return latest_revisions(tuple(candidates))


def select_session_evidence(market_evidence: Sequence[Observation],
                            sessions: Sequence[str]) -> Dict[str, _SessionEvidence]:
    """TOPIX raw 観測を session ごとに**完全一致**で選ぶ（順序非依存・改定は既存規則で解決）。"""
    return _group_by_session(resolve_topix_observations(market_evidence), sessions)


def _group_by_session(resolved: Sequence[Observation],
                      sessions: Sequence[str]) -> Dict[str, _SessionEvidence]:
    return {
        session: _SessionEvidence(
            session=session,
            candidates=tuple(o for o in resolved if o.trading_date == session))
        for session in sessions
    }


def _source_problem(evidence: Sequence[_SessionEvidence]) -> bool:
    """選ばれた観測の source / schema が未対応、または session 間で一致しない。"""
    selected = [o for e in evidence for o in e.candidates]
    if not selected:
        return False
    for o in selected:
        if o.source_id not in SUPPORTED_SOURCE_IDS:
            return True
        if o.schema_version not in SUPPORTED_OBSERVATION_SCHEMA_VERSIONS:
            return True
    return len({o.source_id for o in selected}) > 1 or len({o.schema_version for o in selected}) > 1


# ---------------------------------------------------------------- engine（§16）

def evaluate_prediction(
    prediction: PredictionRecord,
    calendar_evidence: CalendarEvidence,
    market_evidence: Sequence[Observation],
    *,
    created_at: datetime,
    supersedes_evaluation_id: str = "",
) -> EvaluationRecord:
    """凍結 PredictionRecord ＋ 証拠 → 凍結 EvaluationRecord（純関数・決定論的・offline）。"""
    if not isinstance(prediction, PredictionRecord):
        raise EvaluationInputError("prediction must be a frozen PredictionRecord")
    if not isinstance(calendar_evidence, CalendarEvidence):
        raise EvaluationInputError("calendar_evidence must be CalendarEvidence")
    if not isinstance(created_at, datetime):
        raise EvaluationInputError("created_at must be an explicit aware datetime")
    ensure_aware(created_at, "evaluate_prediction.created_at")
    if not isinstance(supersedes_evaluation_id, str):
        raise EvaluationInputError("supersedes_evaluation_id must be str")

    reference, target = prediction.reference_session, prediction.session_date
    resolved = resolve_topix_observations(market_evidence)
    by_session = _group_by_session(resolved, (reference, target))
    ref_evidence, tgt_evidence = by_session[reference], by_session[target]
    observed_dates = sorted({o.trading_date for o in resolved if o.trading_date})
    verification = verify_sessions(calendar_evidence, session_date=target,
                                   observed_trading_dates=observed_dates)

    defer_reason = _decide_defer(ref_evidence, tgt_evidence, verification, prediction)
    supported = not _source_problem((ref_evidence, tgt_evidence))
    ref_obs = ref_evidence.observation if (supported and ref_evidence.usable) else None
    tgt_obs = tgt_evidence.observation if (supported and tgt_evidence.usable) else None
    coherent = ref_obs or tgt_obs
    provenance = dict(
        reference_close=None if ref_obs is None else ref_obs.value,
        target_close=None if tgt_obs is None else tgt_obs.value,
        reference_observation_id="" if ref_obs is None else ref_obs.observation_id,
        target_observation_id="" if tgt_obs is None else tgt_obs.observation_id,
        source_id="" if coherent is None else coherent.source_id,
        market_schema_version="" if coherent is None else coherent.schema_version,
        session_verification=verification,
    )

    if defer_reason is not None:
        if defer_reason is DeferReason.REFERENCE_CLOSE_UNAVAILABLE:
            provenance.update(reference_close=None, reference_observation_id="")
        if defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE:
            provenance.update(target_close=None, target_observation_id="")
        return make_evaluation_record(
            prediction_id=prediction.prediction_id, reference_session=reference,
            session_date=target, status=EvaluationStatus.DEFERRED, created_at=created_at,
            defer_reason=defer_reason, supersedes_evaluation_id=supersedes_evaluation_id,
            **provenance)

    assert ref_obs is not None and tgt_obs is not None       # _decide_defer が保証する
    with localcontext(RETURN_CONTEXT):
        realized_return = (tgt_obs.value / ref_obs.value) - Decimal(1)
    return make_evaluation_record(
        prediction_id=prediction.prediction_id, reference_session=reference,
        session_date=target, status=EvaluationStatus.EVALUATED, created_at=created_at,
        realized_return=realized_return, supersedes_evaluation_id=supersedes_evaluation_id,
        **provenance)


def _decide_defer(ref: _SessionEvidence, tgt: _SessionEvidence,
                  verification: SessionVerification,
                  prediction: PredictionRecord) -> Optional[DeferReason]:
    """凍結優先順位で最初に成立する defer 理由（無ければ None = EVALUATED 可能）。"""
    problems = {
        DeferReason.SOURCE_UNSUPPORTED: _source_problem((ref, tgt)),
        DeferReason.CALENDAR_UNVERIFIED: not verification.validated,
        DeferReason.REFERENCE_SESSION_UNVERIFIED: (
            verification.verified_session != prediction.session_date
            or verification.verified_previous_session != prediction.reference_session),
        DeferReason.OBSERVATION_INVALID: ref.invalid or tgt.invalid,
        DeferReason.REFERENCE_CLOSE_UNAVAILABLE: not ref.candidates,
        DeferReason.TARGET_CLOSE_UNAVAILABLE: not tgt.candidates,
    }
    for reason in DEFER_PRECEDENCE:
        if problems[reason]:
            return reason
    return None


def evaluate_and_append(
    store: EvaluationStore,
    prediction: PredictionRecord,
    calendar_evidence: CalendarEvidence,
    market_evidence: Sequence[Observation],
    *,
    created_at: datetime,
    supersedes_evaluation_id: str = "",
) -> Tuple[EvaluationRecord, EvaluationAppendResult]:
    """薄い helper: `evaluate_prediction` → 凍結 `EvaluationStore.append`（conflict は伝播）。"""
    if not isinstance(store, EvaluationStore):
        raise EvaluationInputError("store must be an EvaluationStore")
    record = evaluate_prediction(prediction, calendar_evidence, market_evidence,
                                 created_at=created_at,
                                 supersedes_evaluation_id=supersedes_evaluation_id)
    return record, store.append(record)
