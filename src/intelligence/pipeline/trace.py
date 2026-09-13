"""End-to-End provenance trace（Phase 2-A）。

「このEvidenceはどこから来たのか」を1本のchainで人間可読に示す:

    EvidenceAssessment → SourceDocument → RawItem → FetchAttempt
    → SourceEndpoint → Source

Black Box禁止（EVIDENCE_QA原則）の運用版。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from ..evidence_qa.model import EvidenceAssessment
from ..ingestion.model import FetchAttempt
from ..sources.model import RawItem, SourceDocument


@dataclass(frozen=True, kw_only=True)
class EndToEndTrace:
    assessment: EvidenceAssessment
    document: Optional[SourceDocument] = None
    raw_item: Optional[RawItem] = None
    fetch_attempt: Optional[FetchAttempt] = None
    catalog_feed: Optional[Mapping[str, object]] = None  # endpoint/source情報

    @property
    def complete(self) -> bool:
        return all(x is not None for x in
                   (self.document, self.raw_item, self.fetch_attempt, self.catalog_feed))


def build_trace(
    assessment: EvidenceAssessment,
    *,
    normalized_store,
    raw_repository,
    catalog_by_id: Mapping[str, Mapping[str, object]],
) -> EndToEndTrace:
    """最終Assessmentから各層を**逆引き**してchainを組み立てる。"""
    document = normalized_store.get_document(assessment.record_id)
    raw_item = None
    attempt = None
    feed = None
    if document is not None:
        if document.raw_item_id:
            raw_item = raw_repository.get_raw_item(document.raw_item_id)
        feed = catalog_by_id.get(document.source_id)
    if raw_item is not None and raw_item.fetch_attempt_id:
        for a in raw_repository.iter_attempts():
            if a.attempt_id == raw_item.fetch_attempt_id:
                attempt = a
                break
    return EndToEndTrace(
        assessment=assessment, document=document, raw_item=raw_item,
        fetch_attempt=attempt, catalog_feed=feed,
    )


def render_trace(trace: EndToEndTrace) -> str:
    """human-readable trace report（Markdown）。"""
    a = trace.assessment
    lines = [
        "## End-to-End Trace",
        "",
        f"**assessment** `{a.assessment_id}`",
        f"- 判定: {a.decision.value}（policy {a.policy_name} v{a.policy_version}・"
        f"評価時刻 {a.assessed_at.isoformat()}）",
        f"- 根拠: {', '.join(a.decision_reasons) or '（全次元PASS）'}",
    ]
    doc = trace.document
    if doc is None:
        lines.append("  ↓ document: **見つからない（chain断絶）**")
        return "\n".join(lines)
    lines += [
        "  ↓",
        f"**document** `{doc.source_document_id}`",
        f"- title: {doc.title}",
        f"- published: {doc.published_at.isoformat() if doc.published_at else 'unknown'}"
        f"（quality={doc.date_quality}, inferred={doc.published_inferred}）",
        f"- locator: {doc.locator}",
        f"- normalizer: {doc.normalizer_name} v{doc.normalizer_version}",
    ]
    raw = trace.raw_item
    if raw is None:
        lines.append("  ↓ raw item: （原文非保存の明示 or 未解決）")
        return "\n".join(lines)
    lines += [
        "  ↓",
        f"**raw item** `{raw.raw_item_id}`",
        f"- retrieved_at: {raw.retrieved_at.isoformat()} / size: {raw.size_bytes}B",
        f"- content sha256: {raw.content_hash[:16]}… / blob: {raw.storage_ref}",
    ]
    attempt = trace.fetch_attempt
    if attempt is not None:
        lines += [
            "  ↓",
            f"**fetch attempt** `{attempt.attempt_id}`",
            f"- HTTP {attempt.status_code} / {attempt.elapsed_ms}ms / retries={attempt.retries}"
            f" / conditional={attempt.conditional_used}",
            f"- url: {attempt.url}",
        ]
    feed = trace.catalog_feed
    if feed is not None:
        endpoint = feed.get("endpoint", {})
        health = feed.get("current_health", {})
        lines += [
            "  ↓",
            f"**endpoint** `{raw.endpoint_id}`",
            f"- url: {endpoint.get('url', '')} / format: {endpoint.get('declared_format', '')}",
            "  ↓",
            f"**source** `{feed.get('id')}`（{feed.get('name')}）",
            f"- tier {feed.get('tier')} / role {feed.get('role')} / "
            f"health {health.get('state')}（{health.get('checked_at')}時点）",
        ]
    return "\n".join(lines)
