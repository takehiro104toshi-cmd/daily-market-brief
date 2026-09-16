"""Trust Gate判定（Phase 1-E）。次元別結果 → GateDecision。

規則（明示・決定論。Black Box禁止）:
    いずれかの次元がFAIL  → REJECT
    いずれかの次元がLIMIT → LIMITED_USE
    いずれかの次元がWARN  → ACCEPT_WITH_WARNINGS
    全てPASS/N-A          → ACCEPT

decision_reasonsには判定水準を決めた次元のreason codeを列挙する
（「なぜこの判定か」が常に機械可読・人間可読で残る）。
"""
from __future__ import annotations

from typing import Sequence, Tuple

from .model import DimensionResult, DimensionStatus, GateDecision, QAIssue

_SEVERITY = {
    DimensionStatus.FAIL: 3,
    DimensionStatus.LIMIT: 2,
    DimensionStatus.WARN: 1,
    DimensionStatus.PASS: 0,
    DimensionStatus.NOT_APPLICABLE: 0,
}

_DECISION_BY_SEVERITY = {
    3: GateDecision.REJECT,
    2: GateDecision.LIMITED_USE,
    1: GateDecision.ACCEPT_WITH_WARNINGS,
    0: GateDecision.ACCEPT,
}


def decide(dimensions: Sequence[DimensionResult]) -> Tuple[GateDecision, Tuple[str, ...]]:
    """次元別結果から関門判定と根拠codeを導出する。"""
    worst = max((_SEVERITY[d.status] for d in dimensions), default=0)
    decision = _DECISION_BY_SEVERITY[worst]
    reasons = tuple(
        code
        for d in dimensions
        if _SEVERITY[d.status] == worst and worst > 0
        for code in d.reason_codes
    )
    return decision, reasons


def collect_issues(dimensions: Sequence[DimensionResult]) -> Tuple[QAIssue, ...]:
    """全次元の非PASS reason codeをQAIssueへ平坦化（集計・レポート用）。"""
    return tuple(
        QAIssue(code=code, dimension=d.dimension, detail=d.detail)
        for d in dimensions
        if d.status not in (DimensionStatus.PASS, DimensionStatus.NOT_APPLICABLE)
        for code in d.reason_codes
    )
