"""フィードentry正規化（Phase 1-D）。RSS2/Atom/RDFの差をここで吸収する。

RawItem（フィード1回分の取得物）→ FeedEntry（PARSED）→ SourceDocument（NORMALIZED）。
parser固有の差異はfeed_parser（adapter）内へ閉じ込め、本normalizerは共通の
FeedEntryのみを見る（common NormalizedFeedEntry統合の実装）。

決定論: 出力（SourceDocument群）は raw body・RawItemメタ・normalizer versionのみの関数。
処理時刻はNormalizationEventだけが持つ。自由文Fact生成はしない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from ..core.ids import new_id, sha256_hex
from ..core.types import SourceTier
from ..ingestion.feed_parser import FeedEntry, parse_feed
from ..sources.model import RawItem, SourceDocument, latest_revisions
from .dates import normalize_published
from .language import normalize_language
from .model import (
    NormalizationEvent,
    NormalizationIssue,
    NormalizationResult,
    NormalizationStatus,
    derive_source_document_id,
)
from .text import content_fingerprint, normalize_text, normalize_title

NORMALIZER_NAME = "feed_entry"
NORMALIZER_VERSION = "1.0.0"


@dataclass(frozen=True, kw_only=True)
class SourceMeta:
    """カタログ由来のソースメタデータ（正規化の決定論的入力の一部）。"""

    source_id: str
    tier: SourceTier = SourceTier.TIER3
    publisher: str = ""
    default_language: str = ""


def detect_revision(
    existing_documents: Tuple[SourceDocument, ...],
    *,
    source_id: str,
    guid: str,
    fingerprint: str,
) -> Optional[str]:
    """revision_of候補の決定論的判定。曖昧な場合はrelationを付けない（None）。

    ルール: 同一source×同一guid（非空）の既存文書のうち最新版がちょうど1件で、
    そのcontent_fingerprintが新文書と異なる → その文書をrevision元とする。
    fingerprintが同じ（=同内容の再配信）はrevisionではない。
    """
    if not guid:
        return None
    candidates = tuple(
        d for d in existing_documents if d.source_id == source_id and d.guid == guid
    )
    if not candidates:
        return None
    latest = latest_revisions(candidates)
    if len(latest) != 1:
        return None  # 曖昧（分岐がある）→ 付けない
    prior = latest[0]
    if prior.content_fingerprint and prior.content_fingerprint == fingerprint:
        return None  # 同内容 → revisionではない
    return prior.source_document_id


def _normalize_entry(
    entry: FeedEntry,
    index: int,
    raw_item: RawItem,
    meta: SourceMeta,
    feed_title: str,
    existing_documents: Tuple[SourceDocument, ...],
    version: str,
) -> Tuple[Optional[SourceDocument], List[NormalizationIssue]]:
    issues: List[NormalizationIssue] = []
    entry_ref = entry.guid or entry.link_original or f"idx:{index}"

    title = normalize_title(entry.title)
    if not title:
        issues.append(NormalizationIssue(code="missing_title", entry_ref=entry_ref))
        return None, issues  # titleはSourceDocumentの必須identity → entry単位でreject

    if not entry.link_original:
        issues.append(NormalizationIssue(code="missing_locator", entry_ref=entry_ref))

    date = normalize_published(
        entry.published_raw,
        fallback_raw=entry.updated_raw,
        link=entry.link_original,
        reference_time=raw_item.retrieved_at,
    )
    if date.quality.value == "missing":
        issues.append(NormalizationIssue(code="missing_date", entry_ref=entry_ref))
    elif date.quality.value == "unparsable":
        issues.append(NormalizationIssue(
            code="invalid_date", entry_ref=entry_ref, detail=date.raw[:80]))
    elif date.quality.value == "source_provided_naive":
        issues.append(NormalizationIssue(code="naive_date", entry_ref=entry_ref))
    if date.anomaly:
        issues.append(NormalizationIssue(
            code=f"date_anomaly_{date.anomaly}", entry_ref=entry_ref, detail=date.raw[:80]))

    fingerprint = content_fingerprint(title, entry.summary_excerpt)
    doc = SourceDocument(
        source_document_id=derive_source_document_id(
            raw_item.raw_item_id, entry_ref, NORMALIZER_NAME, version),
        source_id=meta.source_id,
        source_tier=meta.tier,
        title=title,
        locator=entry.link_original or raw_item.locator,  # originalを失わない
        canonical_locator=entry.link_canonical,
        retrieved_at=raw_item.retrieved_at,
        published_at=date.adopted_utc,
        published_raw=date.raw,
        date_quality=date.quality.value,
        published_inferred=date.inferred and date.adopted_utc == date.inferred_utc,
        published_inferred_from=date.inferred_from if date.inferred else "",
        publisher=meta.publisher or feed_title,
        language=normalize_language(meta.default_language),
        content_hash=sha256_hex(entry.raw_xml.encode("utf-8")),
        raw_item_id=raw_item.raw_item_id,
        summary=normalize_text(entry.summary_excerpt),
        guid=entry.guid,
        media_type=raw_item.media_type,
        content_fingerprint=fingerprint,
        normalizer_name=NORMALIZER_NAME,
        normalizer_version=version,
        revision_of=detect_revision(
            existing_documents, source_id=meta.source_id, guid=entry.guid,
            fingerprint=fingerprint),
    )
    return doc, issues


def normalize_feed_raw_item(
    raw_item: RawItem,
    body: bytes,
    meta: SourceMeta,
    *,
    existing_documents: Tuple[SourceDocument, ...] = (),
    normalizer_version: str = NORMALIZER_VERSION,
    now: Optional[datetime] = None,
) -> NormalizationResult:
    """フィードRawItem 1件を正規化する。例外を投げない（issueとして構造化）。"""
    parsed = parse_feed(body, content_type=raw_item.media_type, source_url=raw_item.locator)
    issues: List[NormalizationIssue] = []
    documents: List[SourceDocument] = []

    if parsed.error or not parsed.entries:
        code = "unsupported_format" if "not a parseable feed" in parsed.error else (
            "malformed_entry" if parsed.error else "malformed_entry")
        if parsed.error:
            issues.append(NormalizationIssue(code=code, detail=parsed.error[:120]))
    for _ in range(parsed.skipped_items):
        issues.append(NormalizationIssue(code="malformed_entry"))

    for i, entry in enumerate(parsed.entries):
        doc, entry_issues = _normalize_entry(
            entry, i, raw_item, meta, parsed.feed_title, existing_documents,
            normalizer_version)
        issues.extend(entry_issues)
        if doc is not None:
            documents.append(doc)

    if not documents:
        status = NormalizationStatus.REJECTED  # RawItem自体は消さない
    elif issues:
        status = NormalizationStatus.PARTIAL
    else:
        status = NormalizationStatus.NORMALIZED

    normalized_at = now or datetime.now(timezone.utc)
    event = NormalizationEvent(
        event_id=new_id("norm", normalized_at),
        raw_item_id=raw_item.raw_item_id,
        normalizer_name=NORMALIZER_NAME,
        normalizer_version=normalizer_version,
        normalized_at=normalized_at,
        status=status,
        issues=tuple(issues),
        produced_document_ids=tuple(d.source_document_id for d in documents),
    )
    return NormalizationResult(
        status=status, documents=tuple(documents), issues=tuple(issues), event=event
    )
