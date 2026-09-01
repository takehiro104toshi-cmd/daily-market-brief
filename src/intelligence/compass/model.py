"""Compass output model（Phase 3-C §5 / §11 / §19 / §30）。

**FACT / CONTEXT / INTERPRETATION / OUTLOOK は混ぜない**——claim毎に
`claim_type` と `claim_role` を持ち、根拠（fact_id / context_id）を必ず持つ。

**推奨語彙を持たない**: bullish/bearish/buy/sell/target等はこのmodelに存在しない。
outlook direction は `UPWARD_BIAS / DOWNWARD_BIAS / RANGE_BOUND / MIXED / UNCERTAIN`
のみ、confidence は決定論的な `HIGH / MEDIUM / LOW` のみ。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware_or_none

COMPASS_SCHEMA_VERSION = "0.1.0"


class ClaimType(str, Enum):
    """claimの性質（§11）。"""

    FACTUAL = "FACTUAL"            # Factそのもの（〜した / 〜となった）
    RELATIONAL = "RELATIONAL"      # Context（同時性・相対状態。因果ではない）
    INTERPRETIVE = "INTERPRETIVE"  # 経験則に基づく読み（〜とみられる）
    OUTLOOK = "OUTLOOK"            # 見通し（〜となろう）
    RISK = "RISK"                  # 反対材料・無効化条件


class ClaimRole(str, Enum):
    """Compassの中での役割（§5 目標出力 A–F）。"""

    HEADLINE = "HEADLINE"              # A 結論先行の見出し（事実）
    WHAT_HAPPENED = "WHAT_HAPPENED"    # B 何が起きたか
    WHY = "WHY"                        # C 根拠（Context ≥ 1）
    OUTLOOK = "OUTLOOK"                # D 見通し
    RISK = "RISK"                      # E 反対材料 / 無効化条件
    COVERAGE = "COVERAGE"              # F 対象外・欠落の明示（missingness）


class GroundingStatus(str, Enum):
    PENDING = "PENDING"                          # 未検証（generator直後）
    GROUNDED = "GROUNDED"
    GROUNDED_WITH_WARNINGS = "GROUNDED_WITH_WARNINGS"
    REJECTED = "REJECTED"


class OutlookDirection(str, Enum):
    UPWARD_BIAS = "UPWARD_BIAS"
    DOWNWARD_BIAS = "DOWNWARD_BIAS"
    RANGE_BOUND = "RANGE_BOUND"
    MIXED = "MIXED"
    UNCERTAIN = "UNCERTAIN"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class QualityVerdict(str, Enum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    REJECTED = "REJECTED"
    ABSTAINED = "ABSTAINED"


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True, kw_only=True)
class ValidationIssue:
    """validatorの指摘1件（claim単位）。"""

    validator: str
    code: str
    message: str
    severity: str = SEVERITY_ERROR
    claim_id: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {"validator": self.validator, "code": self.code,
                "message": self.message, "severity": self.severity,
                "claim_id": self.claim_id}


@dataclass(frozen=True, kw_only=True)
class CompassClaim:
    """生成された1文（claim）。**根拠IDを必ず持つ**（COVERAGE roleのみ例外）。"""

    claim_id: str
    claim_type: ClaimType
    claim_role: ClaimRole
    text: str
    supporting_fact_ids: Tuple[str, ...] = ()
    supporting_context_ids: Tuple[str, ...] = ()
    grounding_status: GroundingStatus = GroundingStatus.PENDING
    issues: Tuple[ValidationIssue, ...] = ()
    generator: str = ""
    order: int = 0

    def __post_init__(self) -> None:
        if not self.claim_id or not self.text:
            raise ValueError("CompassClaim requires claim_id and text")

    def with_status(self, status: GroundingStatus,
                    issues: Sequence[ValidationIssue]) -> "CompassClaim":
        return CompassClaim(
            claim_id=self.claim_id, claim_type=self.claim_type,
            claim_role=self.claim_role, text=self.text,
            supporting_fact_ids=self.supporting_fact_ids,
            supporting_context_ids=self.supporting_context_ids,
            grounding_status=status, issues=tuple(issues),
            generator=self.generator, order=self.order)

    @property
    def is_grounded(self) -> bool:
        return self.grounding_status in (GroundingStatus.GROUNDED,
                                         GroundingStatus.GROUNDED_WITH_WARNINGS)

    def as_dict(self) -> Dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "claim_type": self.claim_type.value,
            "claim_role": self.claim_role.value,
            "text": self.text,
            "supporting_fact_ids": list(self.supporting_fact_ids),
            "supporting_context_ids": list(self.supporting_context_ids),
            "grounding_status": self.grounding_status.value,
            "issues": [i.as_dict() for i in self.issues],
            "generator": self.generator,
            "order": self.order,
        }


def make_claim_id(*, session_date: str, claim_role: ClaimRole, claim_type: ClaimType,
                  text: str, supporting_fact_ids: Sequence[str],
                  supporting_context_ids: Sequence[str]) -> str:
    """**決定論的**なclaim_id（同じ文・同じ根拠 → 同じID。処理時刻を含めない）。"""
    return content_id("claim", session_date, claim_role.value, claim_type.value,
                      text, "|".join(sorted(supporting_fact_ids)),
                      "|".join(sorted(supporting_context_ids)))


@dataclass(frozen=True, kw_only=True)
class CompassOutlook:
    """見通し（§19）。**方向＋確度＋horizon＋根拠＋反対材料＋無効化条件**。

    数値目標を持たない（Compass DNA: 予測は方向＋メカニズム＋無効化条件）。
    """

    direction: OutlookDirection
    confidence: Confidence
    horizon: str
    supporting_context_ids: Tuple[str, ...] = ()
    counter_context_ids: Tuple[str, ...] = ()
    invalidation_conditions: Tuple[str, ...] = ()
    rule_version: str = ""
    components: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "direction": self.direction.value,
            "confidence": self.confidence.value,
            "horizon": self.horizon,
            "supporting_context_ids": list(self.supporting_context_ids),
            "counter_context_ids": list(self.counter_context_ids),
            "invalidation_conditions": list(self.invalidation_conditions),
            "rule_version": self.rule_version,
            "components": dict(self.components),
        }


@dataclass(frozen=True, kw_only=True)
class CompassDraft:
    """Compass output（§30）。claims / outlook / 検証結果 / one-liner / 出典を持つ。"""

    draft_id: str
    session_date: str
    reference_session: str
    package_id: str
    plan_id: str
    generator: str
    verdict: QualityVerdict
    claims: Tuple[CompassClaim, ...] = ()
    outlook: Optional[CompassOutlook] = None
    one_liner: str = ""
    issues: Tuple[ValidationIssue, ...] = ()
    evidence_fact_ids: Tuple[str, ...] = ()
    evidence_context_ids: Tuple[str, ...] = ()
    missing_dimensions: Tuple[str, ...] = ()
    abstain_reason: str = ""
    generator_fallback: str = ""
    generated_at: Optional[datetime] = None
    schema_version: str = COMPASS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.draft_id or not self.session_date:
            raise ValueError("CompassDraft requires draft_id and session_date")
        ensure_aware_or_none(self.generated_at, "CompassDraft.generated_at")

    @property
    def grounded_claims(self) -> List[CompassClaim]:
        return [c for c in self.claims if c.is_grounded]

    @property
    def rejected_claims(self) -> List[CompassClaim]:
        return [c for c in self.claims
                if c.grounding_status is GroundingStatus.REJECTED]

    def claims_for_role(self, role: ClaimRole, *, grounded_only: bool = True
                        ) -> List[CompassClaim]:
        return [c for c in self.claims if c.claim_role is role
                and (c.is_grounded or not grounded_only)]

    def as_dict(self) -> Dict[str, object]:
        return {
            "draft_id": self.draft_id,
            "session_date": self.session_date,
            "reference_session": self.reference_session,
            "package_id": self.package_id,
            "plan_id": self.plan_id,
            "generator": self.generator,
            "verdict": self.verdict.value,
            "claims": [c.as_dict() for c in self.claims],
            "outlook": self.outlook.as_dict() if self.outlook else {},
            "one_liner": self.one_liner,
            "issues": [i.as_dict() for i in self.issues],
            "evidence_fact_ids": list(self.evidence_fact_ids),
            "evidence_context_ids": list(self.evidence_context_ids),
            "missing_dimensions": list(self.missing_dimensions),
            "abstain_reason": self.abstain_reason,
            "generator_fallback": self.generator_fallback,
            "generated_at": self.generated_at.isoformat() if self.generated_at else "",
            "schema_version": self.schema_version,
        }


def make_draft_id(*, session_date: str, package_id: str, plan_id: str,
                  generator: str, claim_ids: Sequence[str], verdict: QualityVerdict,
                  one_liner: str) -> str:
    """**決定論的**なdraft_id（同じ入力・同じgenerator出力 → 同じID）。"""
    return content_id("compass", session_date, package_id, plan_id, generator,
                      "|".join(claim_ids), verdict.value, one_liner)
