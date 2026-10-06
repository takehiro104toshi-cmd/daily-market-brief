"""P8-A2R — 会計の意味の互換の gate と、A2 への追記の可否の plan（純関数 ・決定論 ・非 authority ・非永続。A2 を変えない追加）。

答える問い: 2 つの財務の観測は、会計基準と連結の区分の上で**比べて良い鎖に属し得るか**。そして 1 つの観測を A2 の slot の鎖に
足して良いか、それとも保留（HOLD）か。良い会社か ・指標の値 ・順位 ・screen は答えない。A2 の authority を変えない。

- 互換（`decide_compatibility`）: 両方が KNOWN で会計基準と連結の区分が同じ → `COMPATIBLE`（比べ得る、の意。比べて良いとは
  言わない）。KNOWN どうしで違う → `INCOMPATIBLE`。どちらかが UNKNOWN → `INELIGIBLE`。理由の code は閉じた語彙。
- 追記の plan（`plan_append`）: 監督の決定 d3。会計基準か連結の区分が UNKNOWN、鎖の先頭と会計基準か連結の区分が違う、注記が
  その観測のものでない、注記の区分が A2 の観測の `statement_basis` と食い違う、鎖の先頭が同じ slot でない、`supersedes` が
  鎖の先頭を指さない → `HOLD`（理由つき）。すべて満たす → `ELIGIBLE`。plan は追記しない ・捨てない ・他の行から補わない。
- 実行は本 module の外（ELIGIBLE の plan だけを caller が A2 の store の `append` に渡す。A2 の store の検査はそのまま働く）。
  plan は record にならない（`DERIVED_NON_AUTHORITY_NON_PERSISTENT`）。

記録: `docs/databank/PHASE8_A2R_IMPLEMENTATION.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .observation_model import FundamentalActual, FundamentalForecast
from .observation_semantics_model import AccountingStandard, ObservationSemantics, SemanticsModelError

GATE_RULES_VERSION = "p8_observation_semantics_gate:0.1.0"
#: 判定 ・plan の authority の種類（record ではない ・保存しない）
DERIVED_NON_AUTHORITY_NON_PERSISTENT = "DERIVED_NON_AUTHORITY_NON_PERSISTENT"


class CompatibilityVerdict(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    INELIGIBLE = "INELIGIBLE"


class CompatibilityReason(str, Enum):
    ACCOUNTING_STANDARD_DIFFERS = "ACCOUNTING_STANDARD_DIFFERS"
    STATEMENT_BASIS_DIFFERS = "STATEMENT_BASIS_DIFFERS"
    LEFT_ACCOUNTING_STANDARD_UNKNOWN = "LEFT_ACCOUNTING_STANDARD_UNKNOWN"
    LEFT_STATEMENT_BASIS_UNKNOWN = "LEFT_STATEMENT_BASIS_UNKNOWN"
    RIGHT_ACCOUNTING_STANDARD_UNKNOWN = "RIGHT_ACCOUNTING_STANDARD_UNKNOWN"
    RIGHT_STATEMENT_BASIS_UNKNOWN = "RIGHT_STATEMENT_BASIS_UNKNOWN"


class AppendEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    HOLD = "HOLD"


class HoldReason(str, Enum):
    ACCOUNTING_STANDARD_UNKNOWN = "ACCOUNTING_STANDARD_UNKNOWN"
    STATEMENT_BASIS_UNKNOWN = "STATEMENT_BASIS_UNKNOWN"
    ACCOUNTING_STANDARD_DIFFERS_FROM_CHAIN = "ACCOUNTING_STANDARD_DIFFERS_FROM_CHAIN"
    STATEMENT_BASIS_DIFFERS_FROM_CHAIN = "STATEMENT_BASIS_DIFFERS_FROM_CHAIN"
    CHAIN_ACCOUNTING_STANDARD_UNKNOWN = "CHAIN_ACCOUNTING_STANDARD_UNKNOWN"
    CHAIN_STATEMENT_BASIS_UNKNOWN = "CHAIN_STATEMENT_BASIS_UNKNOWN"
    SEMANTICS_NOT_FOR_THIS_OBSERVATION = "SEMANTICS_NOT_FOR_THIS_OBSERVATION"
    CHAIN_SEMANTICS_NOT_FOR_CHAIN_HEAD = "CHAIN_SEMANTICS_NOT_FOR_CHAIN_HEAD"
    STATEMENT_BASIS_INCONSISTENT_WITH_OBSERVATION = "STATEMENT_BASIS_INCONSISTENT_WITH_OBSERVATION"
    CHAIN_SLOT_MISMATCH = "CHAIN_SLOT_MISMATCH"
    SUPERSEDES_MISMATCH = "SUPERSEDES_MISMATCH"


_FINANCIAL = (FundamentalActual, FundamentalForecast)
_COMPATIBILITY_ORDER = {member: index for index, member in enumerate(CompatibilityReason)}
_HOLD_ORDER = {member: index for index, member in enumerate(HoldReason)}


def _fail(code: str, detail: str = "") -> None:
    raise SemanticsModelError(code, detail)


@dataclass(frozen=True)
class CompatibilityDecision:
    """2 つの注記の互換の判定（理由は語彙の順。record ではない）。"""

    verdict: CompatibilityVerdict
    reasons: Tuple[CompatibilityReason, ...]
    left_observation_id: str
    right_observation_id: str
    rules_version: str = GATE_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "left_observation_id": self.left_observation_id,
                "reasons": [reason.value for reason in self.reasons],
                "right_observation_id": self.right_observation_id, "rules_version": self.rules_version,
                "verdict": self.verdict.value}


@dataclass(frozen=True)
class AppendPlan:
    """1 つの観測を A2 の slot の鎖に足して良いかの plan（非 authority ・非永続。追記はしない）。"""

    eligibility: AppendEligibility
    reasons: Tuple[HoldReason, ...]
    observation_id: str
    slot_key: str
    chain_head_id: str
    rules_version: str = GATE_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "chain_head_id": self.chain_head_id,
                "eligibility": self.eligibility.value, "observation_id": self.observation_id,
                "reasons": [reason.value for reason in self.reasons], "rules_version": self.rules_version,
                "slot_key": self.slot_key}


def _semantics(value: Any, field_name: str) -> ObservationSemantics:
    if not isinstance(value, ObservationSemantics):
        _fail("INVALID_SEMANTICS", field_name)
    return value


def _financial(value: Any, field_name: str):
    if not isinstance(value, _FINANCIAL):
        _fail("NOT_FINANCIAL_OBSERVATION", field_name)
    return value


def decide_compatibility(left: ObservationSemantics, right: ObservationSemantics) -> CompatibilityDecision:
    """会計基準 ・連結の区分の互換（決定論）。UNKNOWN が 1 つでもあれば INELIGIBLE（違いは論じない）。"""
    _semantics(left, "left")
    _semantics(right, "right")
    reasons: List[CompatibilityReason] = []
    for side, semantics in (("LEFT", left), ("RIGHT", right)):
        if semantics.accounting_standard is AccountingStandard.UNKNOWN:
            reasons.append(CompatibilityReason(f"{side}_ACCOUNTING_STANDARD_UNKNOWN"))
        if semantics.statement_basis is None:
            reasons.append(CompatibilityReason(f"{side}_STATEMENT_BASIS_UNKNOWN"))
    if reasons:
        verdict = CompatibilityVerdict.INELIGIBLE
    else:
        if left.accounting_standard is not right.accounting_standard:
            reasons.append(CompatibilityReason.ACCOUNTING_STANDARD_DIFFERS)
        if left.statement_basis is not right.statement_basis:
            reasons.append(CompatibilityReason.STATEMENT_BASIS_DIFFERS)
        verdict = CompatibilityVerdict.INCOMPATIBLE if reasons else CompatibilityVerdict.COMPATIBLE
    return CompatibilityDecision(verdict, tuple(sorted(reasons, key=_COMPATIBILITY_ORDER.__getitem__)),
                                 left.observation_id, right.observation_id)


def plan_append(incoming: Any, incoming_semantics: ObservationSemantics, chain_head: Any = None,
                chain_head_semantics: Optional[ObservationSemantics] = None) -> AppendPlan:
    """A2 の slot の鎖への追記の可否（監督の決定 d3。fail closed）。鎖が空なら `chain_head` ・`chain_head_semantics` は None。"""
    _financial(incoming, "incoming")
    _semantics(incoming_semantics, "incoming_semantics")
    if (chain_head is None) != (chain_head_semantics is None):
        _fail("INVALID_CHAIN", "chain_head")
    reasons: List[HoldReason] = []
    if incoming_semantics.observation_id != incoming.record_id:
        reasons.append(HoldReason.SEMANTICS_NOT_FOR_THIS_OBSERVATION)
    if incoming_semantics.accounting_standard is AccountingStandard.UNKNOWN:
        reasons.append(HoldReason.ACCOUNTING_STANDARD_UNKNOWN)
    if incoming_semantics.statement_basis is None:
        reasons.append(HoldReason.STATEMENT_BASIS_UNKNOWN)
    elif incoming_semantics.statement_basis is not incoming.statement_basis:
        reasons.append(HoldReason.STATEMENT_BASIS_INCONSISTENT_WITH_OBSERVATION)
    head_id = ""
    if chain_head is None:
        if incoming.supersedes != "":
            reasons.append(HoldReason.SUPERSEDES_MISMATCH)
    else:
        _financial(chain_head, "chain_head")
        _semantics(chain_head_semantics, "chain_head_semantics")
        head_id = chain_head.record_id
        if chain_head_semantics.observation_id != head_id:
            reasons.append(HoldReason.CHAIN_SEMANTICS_NOT_FOR_CHAIN_HEAD)
        if chain_head.slot_key != incoming.slot_key:
            reasons.append(HoldReason.CHAIN_SLOT_MISMATCH)
        if incoming.supersedes != head_id:
            reasons.append(HoldReason.SUPERSEDES_MISMATCH)
        head_standard_unknown = chain_head_semantics.accounting_standard is AccountingStandard.UNKNOWN
        head_basis_unknown = chain_head_semantics.statement_basis is None
        if head_standard_unknown:
            reasons.append(HoldReason.CHAIN_ACCOUNTING_STANDARD_UNKNOWN)
        elif (incoming_semantics.accounting_standard is not AccountingStandard.UNKNOWN
              and incoming_semantics.accounting_standard is not chain_head_semantics.accounting_standard):
            reasons.append(HoldReason.ACCOUNTING_STANDARD_DIFFERS_FROM_CHAIN)
        if head_basis_unknown:
            reasons.append(HoldReason.CHAIN_STATEMENT_BASIS_UNKNOWN)
        elif (incoming_semantics.statement_basis is not None
              and incoming_semantics.statement_basis is not chain_head_semantics.statement_basis):
            reasons.append(HoldReason.STATEMENT_BASIS_DIFFERS_FROM_CHAIN)
    ordered = tuple(sorted(set(reasons), key=_HOLD_ORDER.__getitem__))
    return AppendPlan(AppendEligibility.HOLD if ordered else AppendEligibility.ELIGIBLE, ordered,
                      incoming.record_id, incoming.slot_key, head_id)
