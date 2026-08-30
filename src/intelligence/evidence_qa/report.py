"""QAレポート・品質メトリクス（Phase 1-E）。Black Box判定禁止の実装。

- summarize(): 将来監視用の最低限集計（accepted/warning/limited/rejected件数、
  issue別件数）。
- render_report(): 「なぜACCEPT/REJECTになったか」を人間が読めるMarkdownで出力。
  offline生成のみ（スケジューラ・配信はPhase 12）。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Sequence, Tuple

from .model import DimensionStatus, EvidenceAssessment, GateDecision

_DECISION_LABEL = {
    GateDecision.ACCEPT: "ACCEPT（利用可）",
    GateDecision.ACCEPT_WITH_WARNINGS: "ACCEPT_WITH_WARNINGS（注意付き利用可）",
    GateDecision.LIMITED_USE: "LIMITED_USE（用途限定）",
    GateDecision.REJECT: "REJECT（分析利用不可）",
}

_STATUS_MARK = {
    DimensionStatus.PASS: "OK",
    DimensionStatus.WARN: "WARN",
    DimensionStatus.LIMIT: "LIMIT",
    DimensionStatus.FAIL: "FAIL",
    DimensionStatus.NOT_APPLICABLE: "—",
}


@dataclass(frozen=True, kw_only=True)
class QAMetrics:
    """最低限の品質集計（QUALITY METRICS SPEC準拠）。"""

    total: int = 0
    accepted: int = 0
    accepted_with_warnings: int = 0
    limited: int = 0
    rejected: int = 0
    issue_counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def by_decision(self) -> Mapping[str, int]:
        return {
            "accept": self.accepted,
            "accept_with_warnings": self.accepted_with_warnings,
            "limited_use": self.limited,
            "reject": self.rejected,
        }


def summarize(assessments: Sequence[EvidenceAssessment]) -> QAMetrics:
    decisions = Counter(a.decision for a in assessments)
    issues = Counter(i.code for a in assessments for i in a.issues)
    return QAMetrics(
        total=len(assessments),
        accepted=decisions[GateDecision.ACCEPT],
        accepted_with_warnings=decisions[GateDecision.ACCEPT_WITH_WARNINGS],
        limited=decisions[GateDecision.LIMITED_USE],
        rejected=decisions[GateDecision.REJECT],
        issue_counts=dict(issues),
    )


def render_report(
    assessments: Sequence[EvidenceAssessment],
    *,
    title: str = "Evidence QA Report",
    labels: Mapping[str, str] = {},
) -> str:
    """人間可読のQAレポート（Markdown）。判定理由を必ず明示する。"""
    metrics = summarize(assessments)
    lines = [f"# {title}", ""]
    lines.append(
        f"総数 {metrics.total} 件 — ACCEPT {metrics.accepted} / "
        f"WARN付 {metrics.accepted_with_warnings} / "
        f"LIMITED {metrics.limited} / REJECT {metrics.rejected}"
    )
    if metrics.issue_counts:
        lines.append("")
        lines.append("## issue集計")
        lines.append("")
        for code, count in sorted(metrics.issue_counts.items(),
                                  key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- {code}: {count}件")
    lines.append("")
    lines.append("## 個別判定（なぜこの判定か）")
    for a in assessments:
        label = labels.get(a.record_id, "")
        lines.append("")
        lines.append(f"### {a.record_id}" + (f" — {label}" if label else ""))
        lines.append(
            f"- 判定: **{_DECISION_LABEL[a.decision]}**"
            f"（policy: {a.policy_name} v{a.policy_version}"
            + (f", horizon: {a.horizon.value}" if a.horizon else "") + "）"
        )
        if a.decision_reasons:
            lines.append(f"- 決定根拠: {', '.join(a.decision_reasons)}")
        lines.append("- 次元別:")
        for d in a.dimensions:
            codes = f" [{', '.join(d.reason_codes)}]" if d.reason_codes else ""
            detail = f" — {d.detail}" if d.detail else ""
            lines.append(f"  - {d.dimension.value}: {_STATUS_MARK[d.status]}{codes}{detail}")
    lines.append("")
    return "\n".join(lines)
