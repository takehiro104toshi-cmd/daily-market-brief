"""Theme lifecycle view model（P6-B2）— 点時刻 snapshot の 2 層 lifecycle。derived / rebuildable。journal に保存しない。

- **Governance layer**（`GovernanceLifecycleView`）だけが人間 review / governance 上の位置を表す。
- **Evidence layer**（`EvidenceConditionView`）は derived observation（flag 集合）であり、承認・昇格・格下げを意味しない。
- STALE は freshness diagnostic（reference cutoff から見て新しい counted evidence が一定期間観測されていない）であり、
  Theme の妥当性・支持の強さ・投資判断を意味しない。CONTESTED は Theme が偽だという意味ではなく、
  INVALIDATION_EVIDENCE_PRESENT は自動 RETIRED を意味しない。evidence 層から governance 状態を変更しない。
- 語彙に勢い・方向・投資判断・総合評価の語（EMERGING / ACCELERATING / MATURE / WEAKENING / HOT / COLD / BULLISH / BEARISH /
  WINNING / LOSING / HIGH_CONVICTION / LOW_CONVICTION 等）を含めない。件数 score / weighted score / rank / tier を作らない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..themes.model import GovernanceEventType
from ..themes.qualification import QualificationStatus
from ..themes.resolver import GovernanceStatus, ResolutionStatus

LIFECYCLE_VIEW_SCHEMA_VERSION = "theme_lifecycle_view:0.1.0"
LIFECYCLE_MODEL_VERSION = "theme_lifecycle_model:0.1.0"
LIFECYCLE_POLICY_SCHEMA_VERSION = "theme_lifecycle_policy:0.1.0"
#: 既定の freshness window（calendar days）。semantic ではなく versioned policy 値（L-7）。
DEFAULT_STALE_AFTER_DAYS = 90


class ThemeLifecycleError(Exception):
    """入力契約違反（fail closed）。resolution の失敗は例外ではなく UNAVAILABLE な view で返す。"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


class GovernanceLifecycleState(str, Enum):
    UNREVIEWED = "UNREVIEWED"          # root / semantic は存在するが effective な人間 governance decision が無い
    ACCEPTED = "ACCEPTED"              # effective ＝ CANDIDATE_ACCEPTED（REOPENED も受理状態の回復として同じ）
    REJECTED = "REJECTED"              # effective ＝ CANDIDATE_REJECTED
    RETIRED = "RETIRED"                # effective ＝ RETIRED
    MERGED = "MERGED"                  # effective ＝ MERGE で、この root が subject（MERGED_INTO）
    SPLIT = "SPLIT"                    # effective ＝ SPLIT で、この root が subject（SPLIT_INTO）
    SUPERSEDED = "SUPERSEDED"          # effective ＝ SUPERSEDED_BY_ROOT で、この root が subject（SUPERSEDED_BY）
    UNRESOLVED = "UNRESOLVED"          # Foundation governance facet が UNRESOLVED（fork 等）。lifecycle 側で解決しない
    NOT_AVAILABLE = "NOT_AVAILABLE"    # resolution が利用不能（INVALID_HISTORY / STORE_CORRUPTION）または NO_STATE


class EvidenceConditionFlag(str, Enum):
    """互いに排他ではない derived flag。順序は view 内の並び順。"""

    NO_VISIBLE_EVIDENCE = "NO_VISIBLE_EVIDENCE"                      # counted evidence が 0
    HAS_CONTEXT_ONLY = "HAS_CONTEXT_ONLY"                            # visible はあるが counted は 0（CONTEXT 等のみ）
    HAS_SUPPORT = "HAS_SUPPORT"                                      # counted evidence に SUPPORTS がある
    SINGLE_SOURCE = "SINGLE_SOURCE"                                  # counted independent origin group ＝ 1
    MULTI_SOURCE = "MULTI_SOURCE"                                    # ≥ 2
    SINGLE_EVIDENCE_DATE = "SINGLE_EVIDENCE_DATE"                    # counted evidence date set ＝ 1
    MULTI_DATE = "MULTI_DATE"                                        # ≥ 2
    QUALIFIES = "QUALIFIES"                                          # Foundation qualification ＝ QUALIFIES_SEMANTICALLY
    CONTESTED = "CONTESTED"                                          # visible current observation に CONTRADICTS が ≥ 1
    INVALIDATION_EVIDENCE_PRESENT = "INVALIDATION_EVIDENCE_PRESENT"  # INVALIDATES が ≥ 1
    STALE = "STALE"                                                  # freshness: 最新 dated counted evidence から stale_after_days 以上


class LifecycleViewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"    # いずれかの層が UNRESOLVED
    UNAVAILABLE = "UNAVAILABLE"                    # resolution 失敗、または NO_STATE


class EvidenceConditionStatus(str, Enum):
    EVALUATED = "EVALUATED"
    UNRESOLVED = "UNRESOLVED"        # semantic facet が UNRESOLVED。flag を推測しない
    NOT_EVALUATED = "NOT_EVALUATED"  # NO_STATE / resolution 失敗


@dataclass(frozen=True)
class LifecyclePolicy:
    """freshness policy（versioned、明示入力）。`stale_after_days` は calendar days。"""

    stale_after_days: int
    schema_version: str = LIFECYCLE_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.stale_after_days, bool) or not isinstance(self.stale_after_days, int):
            raise ThemeLifecycleError("INVALID_POLICY", "stale_after_days must be an int")
        if self.stale_after_days < 1:
            raise ThemeLifecycleError("INVALID_POLICY", "stale_after_days must be >= 1")
        if self.schema_version != LIFECYCLE_POLICY_SCHEMA_VERSION:
            raise ThemeLifecycleError("INVALID_POLICY", f"unsupported policy schema {self.schema_version!r}")


def default_lifecycle_policy() -> LifecyclePolicy:
    return LifecyclePolicy(stale_after_days=DEFAULT_STALE_AFTER_DAYS)


@dataclass(frozen=True)
class LifecycleDiagnostic:
    code: str
    detail: str = ""
    related: Tuple[str, ...] = ()


@dataclass(frozen=True)
class GovernanceLifecycleView:
    status: GovernanceStatus                          # Foundation governance facet の status（そのまま）
    state: GovernanceLifecycleState
    effective_event_id: str = ""
    effective_event_type: Optional[GovernanceEventType] = None
    state_event_id: str = ""                          # state を決めた event（correction が terminal のときは遡った event）


@dataclass(frozen=True)
class EvidenceConditionView:
    status: EvidenceConditionStatus
    flags: Tuple[EvidenceConditionFlag, ...] = ()
    visible_evidence_count: int = 0                   # T で visible な attachment（CONTEXT 等を含む）
    counted_evidence_count: int = 0                   # A2 §19 の算入対象（Foundation qualification の counted keys）
    independent_origin_count: int = 0
    evidence_date_count: int = 0
    qualification_status: Optional[QualificationStatus] = None
    latest_dated_evidence_time: Optional[datetime] = None
    elapsed_calendar_days: Optional[int] = None       # latest dated counted evidence の日付 → cutoff の日付
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS


@dataclass(frozen=True)
class ThemeLifecycleView:
    schema_version: str
    lifecycle_model_version: str
    policy: LifecyclePolicy
    root_id: str
    cutoff: datetime
    resolution_status: ResolutionStatus
    status: LifecycleViewStatus
    governance: GovernanceLifecycleView
    evidence: EvidenceConditionView
    diagnostics: Tuple[LifecycleDiagnostic, ...]

    def has_flag(self, flag: EvidenceConditionFlag) -> bool:
        return flag in self.evidence.flags


__all__ = [
    "LIFECYCLE_VIEW_SCHEMA_VERSION", "LIFECYCLE_MODEL_VERSION", "LIFECYCLE_POLICY_SCHEMA_VERSION",
    "DEFAULT_STALE_AFTER_DAYS", "ThemeLifecycleError", "GovernanceLifecycleState", "EvidenceConditionFlag",
    "LifecycleViewStatus", "EvidenceConditionStatus", "LifecyclePolicy", "default_lifecycle_policy",
    "LifecycleDiagnostic", "GovernanceLifecycleView", "EvidenceConditionView", "ThemeLifecycleView",
]
