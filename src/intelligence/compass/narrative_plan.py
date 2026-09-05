"""Narrative Plan（Phase 3-C §10）。

Evidence Package と Outlook から、**何を語ってよいか／語ってはいけないか**を
決定論的に決める。generator（LLM／deterministic）はこの計画の範囲内でしか
書けない。

- lead   : 主役Context（原則 japan_equities＝TOPIX前日比。無ければ最上位のcore）
- support: 補助Context（lead以外の採用Context）
- counter: 反対材料（Compass DNA「反対材料の常設」。**0件なら生成不可＝abstain**）
- coverage: 語れない次元（欠落・古い・矛盾・履歴不足）＝COVERAGE claimで明示する
- prohibited: 因果断定・投資助言・数値目標・根拠外次元の言及

計画自体は自由文を持たない（IDと統制語彙だけ）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

from ..context.model import ContextStatus
from ..core.ids import content_id
from .evidence_package import EvidencePackage
from .model import ClaimRole, CompassOutlook
from .outlook import Implication

PLAN_RULE_VERSION = "narrative_plan:1.0.0"

#: 常に禁止する表現カテゴリ（language_rules / validatorsが検査する）
PROHIBITED: Tuple[str, ...] = ("causal", "advice", "numeric_target",
                               "unsupported_dimension")

#: 主役にする次元の優先順（japan_equitiesを最優先）
LEAD_DIMENSION_ORDER: Tuple[str, ...] = ("japan_equities", "usd_jpy", "us_rates_10y",
                                         "japan_rates")

ABSTAIN_NO_LEAD = "no_lead_context"
ABSTAIN_LEAD_NOT_FRESH = "lead_context_not_fresh"
ABSTAIN_NO_COUNTER = "no_counter_material"
ABSTAIN_NO_EVIDENCE = "empty_evidence_package"


@dataclass(frozen=True, kw_only=True)
class NarrativePlan:
    plan_id: str
    session_date: str
    reference_session: str
    package_id: str
    lead_context_id: str
    supporting_context_ids: Tuple[str, ...] = ()
    counter_context_ids: Tuple[str, ...] = ()
    risk_context_ids: Tuple[str, ...] = ()
    coverage_dimensions: Tuple[str, ...] = ()
    allowed_roles: Tuple[ClaimRole, ...] = ()
    prohibited: Tuple[str, ...] = PROHIBITED
    evidence_fact_ids: Tuple[str, ...] = ()
    evidence_context_ids: Tuple[str, ...] = ()
    abstain_reason: str = ""
    rule_version: str = PLAN_RULE_VERSION
    components: Mapping[str, str] = field(default_factory=dict)

    @property
    def can_generate(self) -> bool:
        return not self.abstain_reason

    def as_dict(self) -> Dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "session_date": self.session_date,
            "reference_session": self.reference_session,
            "package_id": self.package_id,
            "lead_context_id": self.lead_context_id,
            "supporting_context_ids": list(self.supporting_context_ids),
            "counter_context_ids": list(self.counter_context_ids),
            "risk_context_ids": list(self.risk_context_ids),
            "coverage_dimensions": list(self.coverage_dimensions),
            "allowed_roles": [r.value for r in self.allowed_roles],
            "prohibited": list(self.prohibited),
            "evidence_fact_ids": list(self.evidence_fact_ids),
            "evidence_context_ids": list(self.evidence_context_ids),
            "abstain_reason": self.abstain_reason,
            "rule_version": self.rule_version,
            "components": dict(self.components),
        }


def _lead(package: EvidencePackage) -> Optional[str]:
    for dimension in LEAD_DIMENSION_ORDER:
        item = package.dimension_context(dimension)
        if item is not None:
            return item.context_id
    return package.core_context_ids[0] if package.core_context_ids else None


def build_narrative_plan(package: EvidencePackage, outlook: CompassOutlook,
                         implications: Mapping[str, Implication], *,
                         min_counter: int = 1) -> NarrativePlan:
    """Evidence Package + Outlook → Narrative Plan（決定論的）。"""
    lead = _lead(package)
    risk_ids = [cid for cid, imp in implications.items()
                if imp.risk_tag and package.context(cid) is not None
                and package.context(cid).status is ContextStatus.AVAILABLE
                and package.context(cid).time.session_date == package.reference_session]
    counters = list(outlook.counter_context_ids)
    for cid in risk_ids:                # 過熱・イベント接近も反対材料として常設
        if cid not in counters:
            counters.append(cid)
    supporting = [cid for cid in package.context_ids if cid != lead]

    abstain = ""
    if not package.contexts:
        abstain = ABSTAIN_NO_EVIDENCE
    elif lead is None:
        abstain = ABSTAIN_NO_LEAD
    elif (package.context(lead).status is not ContextStatus.AVAILABLE
          or package.context(lead).time.session_date != package.reference_session):
        abstain = ABSTAIN_LEAD_NOT_FRESH   # 古い主役で「前営業日」を語らない
    elif len(counters) < min_counter:
        abstain = ABSTAIN_NO_COUNTER      # 反対材料が無い朝は語らない（捏造しない）

    roles: Tuple[ClaimRole, ...] = ()
    if not abstain:
        roles = (ClaimRole.HEADLINE, ClaimRole.WHAT_HAPPENED, ClaimRole.WHY,
                 ClaimRole.OUTLOOK, ClaimRole.RISK, ClaimRole.COVERAGE)
    coverage = tuple(package.unreliable_dimensions)
    plan_id = content_id(
        "plan", package.session_date, package.package_id, PLAN_RULE_VERSION,
        lead or "", "|".join(supporting), "|".join(counters), "|".join(coverage),
        abstain)
    return NarrativePlan(
        plan_id=plan_id, session_date=package.session_date,
        reference_session=package.reference_session, package_id=package.package_id,
        lead_context_id=lead or "",
        supporting_context_ids=tuple(supporting),
        counter_context_ids=tuple(counters), risk_context_ids=tuple(risk_ids),
        coverage_dimensions=coverage, allowed_roles=roles,
        evidence_fact_ids=package.fact_ids, evidence_context_ids=package.context_ids,
        abstain_reason=abstain,
        components={"outlook_direction": outlook.direction.value,
                    "outlook_confidence": outlook.confidence.value,
                    "min_counter": str(min_counter),
                    "counter_count": str(len(counters))})
