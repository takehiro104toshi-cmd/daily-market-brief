"""Trust Policy（Phase 1-E）。QA判定の閾値・用途別の使い分けをpolicyとして分離する。

- policyは name＋version を持ち、Assessmentへ必ず記録される（POLICY VERSIONING）。
  ルール変更は新versionのpolicyを追加して**再評価**する（旧assessmentは上書きしない）。
- P1-Eでは GENERIC と DAILY_MARKET の2 contextでfreshness差を実証する
  （STRUCTURAL_THEME / LONG_TERM_EQUITY等は将来追加）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

from ..core.types import Horizon
from .model import DimensionStatus


@dataclass(frozen=True, kw_only=True)
class TrustPolicy:
    """Evidence QAの判定パラメータ一式（決定論の入力。変更=新version）。"""

    name: str
    version: str
    # freshness（時間）: fresh ≤ fresh_hours < aging ≤ stale_hours < stale
    fresh_hours: int
    stale_hours: int
    # horizon別の許容age上限（時間）。未定義horizonは制約なし
    horizon_max_age_hours: Mapping[str, int] = field(default_factory=dict)
    # 状態別の扱い（次元status）: 用途によって同じ事実への厳しさが変わる
    stale_status: DimensionStatus = DimensionStatus.LIMIT
    published_unknown_status: DimensionStatus = DimensionStatus.WARN
    superseded_status: DimensionStatus = DimensionStatus.LIMIT
    conflicting_status: DimensionStatus = DimensionStatus.LIMIT
    tier3_status: DimensionStatus = DimensionStatus.WARN
    source_dead_status: DimensionStatus = DimensionStatus.WARN  # 死活≠文書の正しさ（分離）
    usage_restricted_status: DimensionStatus = DimensionStatus.WARN
    dependency_rejected_status: DimensionStatus = DimensionStatus.LIMIT  # 自動削除しない

    def freshness_status(self, age_hours: float) -> Tuple[DimensionStatus, str]:
        if age_hours <= self.fresh_hours:
            return DimensionStatus.PASS, "fresh"
        if age_hours <= self.stale_hours:
            return DimensionStatus.WARN, "aging"
        return self.stale_status, "stale_for_policy"

    def horizon_ok(self, age_hours: float, horizon: Optional[Horizon]) -> bool:
        if horizon is None:
            return True
        limit = self.horizon_max_age_hours.get(horizon.value)
        return True if limit is None else age_hours <= limit


#: 汎用policy v1: 一般的なEvidence利用（構造分析寄り。ゆるめのfreshness）
GENERIC_V1 = TrustPolicy(
    name="GENERIC",
    version="1.0.0",
    fresh_hours=72,
    stale_hours=24 * 30,
    horizon_max_age_hours={
        Horizon.INTRADAY.value: 24,
        Horizon.ONE_DAY.value: 72,
        Horizon.ONE_WEEK.value: 24 * 14,
        Horizon.MEDIUM.value: 24 * 90,
        Horizon.LONG.value: 24 * 365,
    },
    superseded_status=DimensionStatus.WARN,  # 歴史・文脈用途を広く許す
)

#: 日次相場policy v1: Morning Brief等の「今日の材料」用途（厳しいfreshness）
DAILY_MARKET_V1 = TrustPolicy(
    name="DAILY_MARKET",
    version="1.0.0",
    fresh_hours=24,
    stale_hours=72,
    horizon_max_age_hours={
        Horizon.INTRADAY.value: 12,
        Horizon.ONE_DAY.value: 48,
        Horizon.ONE_WEEK.value: 24 * 7,
    },
    stale_status=DimensionStatus.LIMIT,
    published_unknown_status=DimensionStatus.LIMIT,  # 日付不明は当日材料として限定
    superseded_status=DimensionStatus.LIMIT,  # 現在値用途では旧版を限定
)

_REGISTRY: Dict[Tuple[str, str], TrustPolicy] = {
    (p.name, p.version): p for p in (GENERIC_V1, DAILY_MARKET_V1)
}


def register_policy(policy: TrustPolicy) -> None:
    """新policy（またはルール変更＝新version）の登録。既存versionの上書きは禁止。"""
    key = (policy.name, policy.version)
    if key in _REGISTRY:
        raise ValueError(f"policy already registered (versionを上げること): {key}")
    _REGISTRY[key] = policy


def get_policy(name: str, version: str) -> TrustPolicy:
    return _REGISTRY[(name, version)]


def registered_policies() -> Tuple[TrustPolicy, ...]:
    return tuple(_REGISTRY.values())
