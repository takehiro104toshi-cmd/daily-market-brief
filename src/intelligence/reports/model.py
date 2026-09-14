"""Morning Brief output model（Phase 4 P4-1A）。

`CompassDraft`（Phase 3-C で validate 済み）を、そのまま三段へ **projection** するための
schema。ここは「読み替え層」であり、新しい知識も新しい品質判定も持たない。

境界（`docs/databank/PHASE4_ENTRY_CONTRACT.md`）:
- verdict / grounding status は Compass の既存語彙（`QualityVerdict` / `GroundingStatus`）を
  そのまま使う。**競合する品質状態機械を作らない。**
- Decision state / formal-review pattern id / replay metadata / promotion state /
  local path / PDF 名 / 機密本文は **schema に持たない**。
- Compass DNA の `rule_ref` は claim から**そのまま**運ぶ。ここで作らない・直さない。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from ..compass.model import ClaimRole, ClaimType, GroundingStatus, QualityVerdict
from ..core.ids import content_id

#: Morning Brief schema の版（`COMPASS_SCHEMA_VERSION` とは独立に動く）
MORNING_BRIEF_SCHEMA_VERSION = "0.1.0"

# ---------------------------------------------------------------- unavailable reasons
#: tier が出せない理由は**機械可読な固定語**にする（散文で言い換えない）
R_ONE_LINER_UNAVAILABLE = "one_liner_unavailable"          # pipeline の ABSTAIN_ONE_LINER と同じ語
R_DRAFT_NOT_USABLE = "draft_not_usable"                    # verdict が ABSTAINED / REJECTED
R_NO_GROUNDED_POINTS = "no_grounded_points"                # HEADLINE / WHAT_HAPPENED が無い
R_NO_GROUNDED_OUTLOOK = "no_grounded_outlook"              # OUTLOOK claim が無い
R_NO_GROUNDED_COUNTER_CASE = "no_grounded_counter_case"    # RISK（反対材料）が無い

#: tier を出してよい draft verdict（fail-closed: これ以外は substantive 出力なし）
USABLE_VERDICTS: Tuple[QualityVerdict, ...] = (
    QualityVerdict.VALID, QualityVerdict.VALID_WITH_WARNINGS,
)

#: 各 tier が projection してよい claim role
TIER2_POINT_ROLES: Tuple[ClaimRole, ...] = (ClaimRole.HEADLINE, ClaimRole.WHAT_HAPPENED)
TIER2_COVERAGE_ROLES: Tuple[ClaimRole, ...] = (ClaimRole.COVERAGE,)
TIER3_ROLES: Tuple[ClaimRole, ...] = (ClaimRole.OUTLOOK, ClaimRole.WHY, ClaimRole.RISK)


@dataclass(frozen=True, kw_only=True)
class BriefPoint:
    """claim 1 件の projection。**本文は draft の claim.text をそのまま運ぶ。**"""

    claim_id: str
    claim_role: ClaimRole
    claim_type: ClaimType
    text: str
    grounding_status: GroundingStatus
    order: int = 0
    supporting_fact_ids: Tuple[str, ...] = ()
    supporting_context_ids: Tuple[str, ...] = ()
    rule_ref: str = ""
    interpretation_type: str = ""
    market_principle_version: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "claim_role": self.claim_role.value,
            "claim_type": self.claim_type.value,
            "text": self.text,
            "grounding_status": self.grounding_status.value,
            "order": self.order,
            "supporting_fact_ids": list(self.supporting_fact_ids),
            "supporting_context_ids": list(self.supporting_context_ids),
            "rule_ref": self.rule_ref,
            "interpretation_type": self.interpretation_type,
            "market_principle_version": self.market_principle_version,
        }


@dataclass(frozen=True, kw_only=True)
class BriefTier1:
    """30 秒版「今日のお客様向け一言」。`CompassDraft.one_liner` の完全一致のみ。"""

    available: bool
    text: str = ""
    unavailable_reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"available": self.available, "text": self.text,
                "unavailable_reason": self.unavailable_reason}


@dataclass(frozen=True, kw_only=True)
class BriefTier2:
    """3 分版「今日のポイント」。HEADLINE / WHAT_HAPPENED ＋ COVERAGE と欠落次元。"""

    available: bool
    points: Tuple[BriefPoint, ...] = ()
    coverage: Tuple[BriefPoint, ...] = ()
    missing_dimensions: Tuple[str, ...] = ()
    unreliable_dimensions: Tuple[str, ...] = ()
    unavailable_reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "available": self.available,
            "points": [p.as_dict() for p in self.points],
            "coverage": [p.as_dict() for p in self.coverage],
            "missing_dimensions": list(self.missing_dimensions),
            "unreliable_dimensions": list(self.unreliable_dimensions),
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True, kw_only=True)
class BriefOutlook:
    """Tier 3 の見通しヘッダ。`CompassOutlook` の値をそのまま運ぶ（数値目標を持たない）。"""

    direction: str
    confidence: str
    horizon: str
    supporting_context_ids: Tuple[str, ...] = ()
    counter_context_ids: Tuple[str, ...] = ()
    invalidation_conditions: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, object]:
        return {
            "direction": self.direction, "confidence": self.confidence,
            "horizon": self.horizon,
            "supporting_context_ids": list(self.supporting_context_ids),
            "counter_context_ids": list(self.counter_context_ids),
            "invalidation_conditions": list(self.invalidation_conditions),
        }


@dataclass(frozen=True, kw_only=True)
class BriefTier3:
    """詳細版「相場の見通し＋なぜ」。OUTLOOK / WHY / RISK。RISK が無ければ出さない。"""

    available: bool
    outlook: Optional[BriefOutlook] = None
    outlook_points: Tuple[BriefPoint, ...] = ()
    why: Tuple[BriefPoint, ...] = ()
    risk: Tuple[BriefPoint, ...] = ()
    principle_refs: Tuple[str, ...] = ()
    unavailable_reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "available": self.available,
            "outlook": self.outlook.as_dict() if self.outlook else None,
            "outlook_points": [p.as_dict() for p in self.outlook_points],
            "why": [p.as_dict() for p in self.why],
            "risk": [p.as_dict() for p in self.risk],
            "principle_refs": list(self.principle_refs),
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True, kw_only=True)
class MorningBrief:
    """三段 Morning Brief。`brief_id` は内容アドレス（同じ projection → 同じ ID）。"""

    brief_id: str
    session_date: str
    reference_session: str
    draft_id: str
    package_id: str
    verdict: QualityVerdict
    generator: str
    tier1: BriefTier1
    tier2: BriefTier2
    tier3: BriefTier3
    abstain_reason: str = ""
    schema_version: str = MORNING_BRIEF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.brief_id or not self.session_date:
            raise ValueError("MorningBrief requires brief_id and session_date")
        if not self.draft_id or not self.package_id:
            raise ValueError("MorningBrief requires draft_id and package_id")

    def as_dict(self) -> Dict[str, object]:
        return {"brief_id": self.brief_id, **projection_payload(
            schema_version=self.schema_version, session_date=self.session_date,
            reference_session=self.reference_session, draft_id=self.draft_id,
            package_id=self.package_id, verdict=self.verdict, generator=self.generator,
            abstain_reason=self.abstain_reason,
            tier1=self.tier1, tier2=self.tier2, tier3=self.tier3)}

    @property
    def points(self) -> Tuple[BriefPoint, ...]:
        """brief が実際に出す claim projection すべて（provenance 検査用）。"""
        return (self.tier2.points + self.tier2.coverage + self.tier3.outlook_points
                + self.tier3.why + self.tier3.risk)


def projection_payload(*, schema_version: str, session_date: str, reference_session: str,
                       draft_id: str, package_id: str, verdict: QualityVerdict,
                       generator: str, abstain_reason: str,
                       tier1: BriefTier1, tier2: BriefTier2,
                       tier3: BriefTier3) -> Dict[str, object]:
    """`brief_id` の材料であり、`as_dict()` の本体でもある正規化 payload。"""
    return {
        "schema_version": schema_version,
        "session_date": session_date,
        "reference_session": reference_session,
        "draft_id": draft_id,
        "package_id": package_id,
        "verdict": verdict.value,
        "generator": generator,
        "abstain_reason": abstain_reason,
        "tier1": tier1.as_dict(),
        "tier2": tier2.as_dict(),
        "tier3": tier3.as_dict(),
    }


def canonical_projection(payload: Mapping[str, object]) -> str:
    """決定論的な正規化文字列（key 順固定・空白なし）。時刻も path も含めない。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_brief_id(payload: Mapping[str, object]) -> str:
    """**決定論的**な brief_id。同じ projection → 同じ ID、違えば別 ID。"""
    return content_id("brief", canonical_projection(payload))
