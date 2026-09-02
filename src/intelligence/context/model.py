"""Context domain model（Phase 3-B STEP 4/5/7/8/9/22/26）。

**CONTEXT ≠ FACT**: Factは単一の観測事実、ContextはFact間の
RELATIONSHIP / RELATIVE STATE を表す。

**NO CAUSAL CLAIMS**: 関係語彙に `CAUSES` は**存在しない**。同時に起きたことは
`CO_OCCURRING` としてのみ記録する（「金利上昇が株価を押し下げた」等は作らない）。

**NO RECOMMENDATION**: bullish/bearish/buy/sell/target等の語彙を持たない。

**LLM非依存**: 生成は完全に決定論的（prompt分類・LLMランキングを使わない）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware_or_none

CONTEXT_SCHEMA_VERSION = "0.1.0"


class Direction(str, Enum):
    """方向の統制語彙（自由文字列を使わない）。"""

    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"
    STRONGER = "STRONGER"
    WEAKER = "WEAKER"
    STEEPENING = "STEEPENING"
    FLATTENING = "FLATTENING"
    OUTPERFORM = "OUTPERFORM"
    UNDERPERFORM = "UNDERPERFORM"
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class Relationship(str, Enum):
    """Fact間の関係。**因果を表す値は意図的に存在しない**。"""

    CO_OCCURRING = "CO_OCCURRING"        # 同時に起きた（因果ではない）
    CONFIRMING = "CONFIRMING"            # 同方向で相互確認
    DIVERGING = "DIVERGING"              # 逆方向
    MIXED = "MIXED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ContextStatus(str, Enum):
    """次元ごとの充足状況（**欠けているものを黙って省略しない**）。"""

    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    STALE = "STALE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    CONFLICTED = "CONFLICTED"
    LIMITED_USE = "LIMITED_USE"
    NOT_ENTITLED = "NOT_ENTITLED"        # 契約上取得できない（Phase 3.5: Light plan制約）


class PriorityTier(str, Enum):
    """salienceの段階（0-100の疑似精度スコアを作らない——STEP 13）。"""

    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    BACKGROUND = "BACKGROUND"


# --------------------------------------------------------------- thresholds

#: 方向判定の規則版数（閾値を変えたら上げる）
DIRECTION_RULE = "direction:1.0.0"

#: **正当化できる flat band のみ**を定義する（恣意的な閾値を置かない）。
#: 金利は公表値の最小刻みが 0.001 pct（MOF/Treasuryの実測値: 2.943 / 4.34）。
#: それ未満の差は**公表精度で解像できない**ため FLAT とする。
#: 株価指数・為替の変化率については、精度から正当化できる band が無いため
#: **閾値を導入しない**（厳密な符号で判定し、大きさは magnitude として別に持つ）。
FLAT_BAND_BY_UNIT: Mapping[str, Decimal] = {
    "pct_point": Decimal("0.001"),
}
#: 大きさの区分（SMALL/MODERATE/LARGE）は**導入しない**。
#: 正当化できる閾値が現時点のデータからは得られないため、raw magnitudeを保持し
#: 区分はPhase 3-C以降へ委ねる（STEP 9「根拠のない閾値を作らない」）。
MAGNITUDE_CATEGORIES_ENABLED = False


def flat_band_for(unit: str) -> Decimal:
    return FLAT_BAND_BY_UNIT.get(unit, Decimal(0))


def direction_of(delta: Optional[Decimal], *, unit: str = "") -> Direction:
    """符号（＋正当化できる場合のみflat band）から方向を決める。"""
    if delta is None:
        return Direction.UNKNOWN
    band = flat_band_for(unit)
    if abs(delta) <= band:
        return Direction.FLAT
    return Direction.UP if delta > 0 else Direction.DOWN


def compare_direction(left: Optional[Decimal],
                      right: Optional[Decimal]) -> Direction:
    """相対比較（OUTPERFORM / UNDERPERFORM / FLAT）。"""
    if left is None or right is None:
        return Direction.UNKNOWN
    if left == right:
        return Direction.FLAT
    return Direction.OUTPERFORM if left > right else Direction.UNDERPERFORM


# --------------------------------------------------------------- model

@dataclass(frozen=True, kw_only=True)
class ContextSubject:
    """Contextの対象。複数系列の比較では**両方**を保持する。"""

    subject_type: str            # "series" / "series_pair" / "security" / "market"
    subject_id: str
    display_name: str = ""
    related_subject_ids: Tuple[str, ...] = ()

    def key(self) -> str:
        related = ",".join(self.related_subject_ids)
        return f"{self.subject_type}:{self.subject_id}" + (f"|{related}" if related else "")

    def __post_init__(self) -> None:
        if not self.subject_type or not self.subject_id:
            raise ValueError("ContextSubject requires subject_type and subject_id")


@dataclass(frozen=True, kw_only=True)
class ContextTimeContext:
    """Contextの時間軸（Phase 3-Aの意味論を再利用する）。"""

    session_date: str                    # 対象のtrading session
    known_at: Optional[datetime] = None  # **全支持Factが既知になった時点**（最も遅い）
    session_count: int = 0               # 比較に使ったセッション数

    def __post_init__(self) -> None:
        if not self.session_date:
            raise ValueError("ContextTimeContext requires session_date")
        ensure_aware_or_none(self.known_at, "ContextTimeContext.known_at")


@dataclass(frozen=True, kw_only=True)
class ContextItem:
    """1件のstructured context。

    `direction` / `relationship` / `magnitude` を分離して持つ
    （方向と大きさを混ぜない——STEP 9）。
    """

    context_id: str
    context_type: str
    subject: ContextSubject
    time: ContextTimeContext
    direction: Direction = Direction.UNKNOWN
    relationship: Optional[Relationship] = None
    magnitude: Optional[Decimal] = None
    magnitude_unit: str = ""
    supporting_fact_ids: Tuple[str, ...] = ()
    rule_name: str = ""
    rule_version: str = ""
    status: ContextStatus = ContextStatus.AVAILABLE
    quality: str = ""                    # 支持Factのうち最も弱いQA判定
    priority_tier: PriorityTier = PriorityTier.BACKGROUND
    priority_components: Mapping[str, str] = field(default_factory=dict)
    priority_rule_version: str = ""
    revision_of: str = ""
    created_at: Optional[datetime] = None
    schema_version: str = CONTEXT_SCHEMA_VERSION
    note: str = ""

    def __post_init__(self) -> None:
        if not self.context_id or not self.context_type:
            raise ValueError("ContextItem requires context_id and context_type")
        ensure_aware_or_none(self.created_at, "ContextItem.created_at")
        if self.status is ContextStatus.AVAILABLE and not self.supporting_fact_ids:
            # provenance無しのContextをAVAILABLEにしない（FAIL-CLOSED）
            raise ValueError("available ContextItem requires supporting_fact_ids")
        if self.magnitude is not None and not isinstance(self.magnitude, Decimal):
            raise TypeError("ContextItem.magnitude must be Decimal")

    @property
    def rule(self) -> str:
        return f"{self.rule_name}:{self.rule_version}" if self.rule_name else ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "context_id": self.context_id,
            "context_type": self.context_type,
            "subject_type": self.subject.subject_type,
            "subject_id": self.subject.subject_id,
            "display_name": self.subject.display_name,
            "related_subject_ids": list(self.subject.related_subject_ids),
            "session_date": self.time.session_date,
            "known_at": self.time.known_at.isoformat() if self.time.known_at else "",
            "session_count": self.time.session_count,
            "direction": self.direction.value,
            "relationship": self.relationship.value if self.relationship else "",
            "magnitude": str(self.magnitude) if self.magnitude is not None else "",
            "magnitude_unit": self.magnitude_unit,
            "supporting_fact_ids": list(self.supporting_fact_ids),
            "rule": self.rule,
            "status": self.status.value,
            "quality": self.quality,
            "priority_tier": self.priority_tier.value,
            "priority_components": dict(self.priority_components),
            "priority_rule_version": self.priority_rule_version,
            "revision_of": self.revision_of,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "schema_version": self.schema_version,
            "note": self.note,
        }


def make_context_id(
    *,
    context_type: str,
    subject: ContextSubject,
    session_date: str,
    rule: str,
    direction: Direction,
    magnitude: Optional[Decimal],
    supporting_fact_ids: Sequence[str],
) -> str:
    """**決定論的**なcontext_id。

    同じ context type × subjects × 時点 × inputs × rule version からは
    常に同じIDになる。**処理時刻を含めない**（再実行が冪等）。
    支持Factが変われば別IDになるため、`revision_of` で履歴を辿れる。
    """
    magnitude_token = format(magnitude.normalize(), "f") if magnitude is not None else ""
    return content_id(
        "ctx", context_type, subject.key(), session_date, rule,
        direction.value, magnitude_token, "|".join(sorted(supporting_fact_ids)))


# --------------------------------------------------------------- market state

#: Market State Vectorの次元（**RISK_ON等の解釈分類は作らない**——STEP 11）
STATE_DIMENSIONS: Tuple[str, ...] = (
    "japan_equities",
    "nikkei_vs_topix",
    "nt_ratio",
    "japan_rates",
    "us_rates_2y",
    "us_rates_10y",
    "us_curve",
    "usd_jpy",
)


@dataclass(frozen=True, kw_only=True)
class MarketState:
    """構造化されたmarket state vector。欠けている次元は `UNKNOWN` のまま。"""

    values: Mapping[str, Direction]
    statuses: Mapping[str, ContextStatus]

    def as_dict(self) -> Dict[str, str]:
        return {dim: self.values.get(dim, Direction.UNKNOWN).value
                for dim in STATE_DIMENSIONS}

    def status_dict(self) -> Dict[str, str]:
        return {dim: self.statuses.get(dim, ContextStatus.MISSING).value
                for dim in STATE_DIMENSIONS}

    @property
    def unknown_dimensions(self) -> Tuple[str, ...]:
        return tuple(d for d in STATE_DIMENSIONS
                     if self.values.get(d, Direction.UNKNOWN) is Direction.UNKNOWN)


@dataclass(frozen=True, kw_only=True)
class CompassContextSnapshot:
    """あるTokyo sessionの朝時点で成立していたContext一式（Phase 3-Cの直接入力）。

    **自然言語のテキストを持たない**。
    """

    session_date: str
    cutoff: datetime
    items: Tuple[ContextItem, ...]
    market_state: MarketState
    dimension_status: Mapping[str, ContextStatus]
    missing_dimensions: Tuple[str, ...] = ()
    #: cutoff時点で**実際に利用できた最新session**（通常は前営業日）。
    #: 朝のCompassは当日クローズを知り得ないため、鮮度はこのsession基準で見る。
    reference_session: str = ""
    generated_at: Optional[datetime] = None
    schema_version: str = CONTEXT_SCHEMA_VERSION
    #: Phase 3.5: market_internals 次元（breadth / turnover / sector_leadership /
    #: size_leadership / investor_flow）の充足状況。internalsを付けない場合は空。
    internals_status: Mapping[str, ContextStatus] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "session_date": self.session_date,
            "reference_session": self.reference_session,
            "cutoff": self.cutoff.isoformat(),
            "market_state": self.market_state.as_dict(),
            "market_state_status": self.market_state.status_dict(),
            "dimension_status": {k: v.value for k, v in self.dimension_status.items()},
            "internals_status": {k: v.value for k, v in self.internals_status.items()},
            "missing_dimensions": list(self.missing_dimensions),
            "context_count": len(self.items),
            "priority_contexts": [
                {"context_type": i.context_type, "subject_id": i.subject.subject_id,
                 "direction": i.direction.value,
                 "magnitude": str(i.magnitude) if i.magnitude is not None else "",
                 "magnitude_unit": i.magnitude_unit,
                 "priority_tier": i.priority_tier.value,
                 "supporting_fact_ids": list(i.supporting_fact_ids),
                 "rule": i.rule}
                for i in self.items],
            "schema_version": self.schema_version,
        }
