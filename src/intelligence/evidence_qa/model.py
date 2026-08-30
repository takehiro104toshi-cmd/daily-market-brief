"""Evidence QAドメインモデル（Phase 1-E）。God object禁止の分割:

- QADimension / DimensionStatus / DimensionResult … 次元別評価（正）
- QAIssue                                         … 構造化issue（reason code）
- GateDecision                                    … 関門判定
- EvidenceAssessment                              … 1レコード1回分の評価（永続・append-only）
- SourceInfo                                      … カタログ由来のソース品質スナップショット
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION, Horizon, SourceTier


class QADimension(str, Enum):
    """独立評価する13次元（1つの総合scoreへ潰さない）。"""

    PROVENANCE = "provenance"                  # 1. 出所チェーンの完全性
    SOURCE_QUALITY = "source_quality"          # 2. 情報源の格（Tier≠truth）
    SOURCE_HEALTH = "source_health"            # 3. 現在のソース死活（文書の正しさとは別軸）
    FRESHNESS = "freshness"                    # 4. 鮮度（用途horizon依存）
    DATE_QUALITY = "date_quality"              # 5. 日付品質
    CONTENT_INTEGRITY = "content_integrity"    # 6. 内容の完全性（hash照合等）
    CONFLICT = "conflict"                      # 7. 矛盾状態
    REVISION = "revision"                      # 8. 改定状態（superseded等）
    DUPLICATION = "duplication"                # 9. 重複・転載状態
    OBSERVATION_VALIDITY = "observation_validity"  # 10. 数値観測の妥当性
    SUPPORT = "support"                        # 11. 裏付け状態（UNSUPPORTED検出）
    USAGE_RIGHTS = "usage_rights"              # 12. 利用条件（trustと混同しない）
    NORMALIZATION_QUALITY = "normalization_quality"  # 13. 正規化品質


class DimensionStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"          # 利用可だが注意情報あり
    LIMIT = "limit"        # 用途限定でのみ利用可
    FAIL = "fail"          # この次元の要件を満たさない（gateでREJECT）
    NOT_APPLICABLE = "not_applicable"


class GateDecision(str, Enum):
    ACCEPT = "accept"
    ACCEPT_WITH_WARNINGS = "accept_with_warnings"
    LIMITED_USE = "limited_use"
    REJECT = "reject"


#: reason code語彙（機械可読。増設は追記のみ）
REASON_CODES = (
    # provenance
    "missing_source_id", "missing_raw_item", "missing_content_hash",
    "missing_retrieved_at", "missing_locator", "missing_normalizer_version",
    "missing_supporting_evidence_ref", "broken_provenance_chain",
    # source quality / health
    "tier3_general_source", "low_investment_value", "source_unverified",
    "source_dead_now", "source_degraded_now", "source_auth_required",
    # freshness / date
    "fresh", "aging", "stale_for_policy", "stale_for_horizon", "published_unknown",
    "naive_date", "inferred_date", "date_anomaly",
    # integrity
    "blob_hash_mismatch", "raw_item_not_found", "missing_fingerprint",
    "serialization_broken",
    # conflict / revision / duplication / support
    "conflicting_evidence", "contradiction_only", "superseded", "retracted",
    "syndicated_duplicate", "single_source_only", "corroborated_independent",
    "unsupported_fact", "supported",
    # observation
    "value_missing", "value_not_finite", "negative_impossible_value",
    "absurd_percentage", "unknown_unit", "currency_mismatch",
    "derived_without_inputs", "as_of_in_future",
    # normalization / usage / dependency
    "normalization_rejected", "normalization_partial", "usage_restricted",
    "dependency_rejected", "dependency_limited", "dependency_unassessed",
    "weak_supporting_evidence",
)


@dataclass(frozen=True, kw_only=True)
class DimensionResult:
    dimension: QADimension
    status: DimensionStatus
    reason_codes: Tuple[str, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        for code in self.reason_codes:
            if code not in REASON_CODES:
                raise ValueError(f"unknown reason code: {code}")


@dataclass(frozen=True, kw_only=True)
class QAIssue:
    """assessment横断で集計しやすい形の構造化issue。"""

    code: str
    dimension: QADimension
    detail: str = ""

    def __post_init__(self) -> None:
        if self.code not in REASON_CODES:
            raise ValueError(f"unknown reason code: {self.code}")


@dataclass(frozen=True, kw_only=True)
class EvidenceAssessment:
    """1レコード×1policy×1回分の品質評価（永続・append-only・上書き禁止）。"""

    assessment_id: str  # qa_<ULID>
    record_id: str
    record_type: str  # source_document / observation / fact / analysis / forecast
    assessed_at: datetime  # 評価時刻＝freshness基準時刻（決定論: 外から注入）
    policy_name: str
    policy_version: str
    horizon: Optional[Horizon] = None  # 用途コンテキスト（任意）
    dimensions: Tuple[DimensionResult, ...] = ()
    issues: Tuple[QAIssue, ...] = ()
    decision: GateDecision = GateDecision.REJECT
    decision_reasons: Tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.assessment_id:
            raise ValueError("assessment_id is required")
        if not self.record_id:
            raise ValueError("record_id is required")
        if self.record_type not in (
            "source_document", "observation", "fact", "analysis", "forecast"
        ):
            raise ValueError(f"unknown record_type: {self.record_type}")
        if not self.policy_name or not self.policy_version:
            raise ValueError("policy_name/version are required (再評価のtrace)")
        ensure_aware(self.assessed_at, "EvidenceAssessment.assessed_at")

    def dimension(self, dim: QADimension) -> Optional[DimensionResult]:
        for d in self.dimensions:
            if d.dimension is dim:
                return d
        return None


@dataclass(frozen=True, kw_only=True)
class SourceInfo:
    """source_feeds.yaml由来のソース品質スナップショット（評価入力。I/Oは呼び出し側）。"""

    source_id: str
    tier: SourceTier = SourceTier.TIER3
    investment_value: str = "MEDIUM"  # MARKET_CRITICAL / HIGH / MEDIUM / LOW
    health_state: str = "unverified"  # HealthState value
    usage_status: str = "public_feed"
    duplicate_group: str = ""
