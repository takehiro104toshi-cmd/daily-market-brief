"""Identity metrics＋false merge監査レポート（Phase 2-B）。Black Box merge禁止。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .identity_decision import IdentityDecision, IdentityDecisionKind, MERGING_DECISIONS


@dataclass(frozen=True, kw_only=True)
class IdentityMetrics:
    documents: int = 0
    articles: int = 0
    exact_merges: int = 0
    semantic_auto_merges: int = 0
    revision_links: int = 0
    syndicated_links: int = 0
    candidates: int = 0
    distinct: int = 0
    by_decision: Mapping[str, int] = field(default_factory=dict)


def summarize_decisions(
    decisions: Sequence[IdentityDecision], *, articles: int = 0
) -> IdentityMetrics:
    counts = Counter(d.decision for d in decisions)
    return IdentityMetrics(
        documents=len(decisions),
        articles=articles,
        exact_merges=counts[IdentityDecisionKind.EXACT_MATCH],
        semantic_auto_merges=counts[IdentityDecisionKind.AUTO_MERGE],
        revision_links=counts[IdentityDecisionKind.REVISION],
        syndicated_links=counts[IdentityDecisionKind.SYNDICATED],
        candidates=counts[IdentityDecisionKind.CANDIDATE],
        distinct=counts[IdentityDecisionKind.DISTINCT],
        by_decision={k.value: v for k, v in counts.items()},
    )


def render_merge_audit(
    decisions: Sequence[IdentityDecision],
    *,
    labels: Mapping[str, str] = {},
    title: str = "Article Identity Merge Audit",
) -> str:
    """merge済みpairの「why merged」を人間可読で出す（Black Box merge禁止の実装）。"""
    metrics = summarize_decisions(decisions)
    lines = [f"# {title}", ""]
    lines.append(
        f"documents {metrics.documents} — exact {metrics.exact_merges} / "
        f"auto-merge {metrics.semantic_auto_merges} / revision {metrics.revision_links} / "
        f"syndicated {metrics.syndicated_links} / candidate {metrics.candidates}"
        f"（merge禁止）/ distinct {metrics.distinct}"
    )
    lines.append("")
    lines.append("## mergeされたpairとその根拠")
    merged = [d for d in decisions if d.decision in MERGING_DECISIONS]
    if not merged:
        lines.append("")
        lines.append("（mergeなし）")
    for d in merged:
        label = labels.get(d.document_id, "")
        lines.append("")
        lines.append(f"### {d.document_id}" + (f" — {label}" if label else ""))
        lines.append(f"- 判定: **{d.decision.value}** → article `{d.matched_article_id}`")
        lines.append(f"- confidence: {d.confidence} / algorithm v{d.algorithm_version}")
        lines.append(f"- matched signals: {', '.join(d.matched_signals) or '（なし）'}")
        if d.failed_signals:
            lines.append(f"- failed signals: {', '.join(d.failed_signals)}")
    candidates = [d for d in decisions if d.decision is IdentityDecisionKind.CANDIDATE]
    if candidates:
        lines.append("")
        lines.append("## CANDIDATE（mergeしていない曖昧候補）")
        for d in candidates:
            lines.append(
                f"- {d.document_id} →候補 `{d.matched_article_id}`"
                f"（confidence {d.confidence}・不足: {', '.join(d.failed_signals)}）")
    lines.append("")
    return "\n".join(lines)
