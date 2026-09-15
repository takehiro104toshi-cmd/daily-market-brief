"""tank記事レコード互換normalizer（Phase 1-D）。

Stage 1.5で実測したtank記事ストア（3,056記事・2026-06-22..07-22）の記事dictを
P1-D SourceDocumentへ変換できることを保証する（Phase 2正式backfillの受け皿）。

**P1-Dでは代表sampleの互換性テストのみ**（3,056件のfull migrationは禁止）。

mapping方針:
- tankのINTERPRETED系フィールド（importance_score / themes / sentiment /
  expected_direction等）は**意図的に取り込まない**（INTERPRETED層はP1-E以降。
  RAW/PARSED/NORMALIZEDの分離を破らない）。
- tank date_inferred=True は published_inferred=True / inferred_from="tank_fetched_at"
  として機械可読に引き継ぐ（tankはfetched_atへ補正済みの値を保持している）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Mapping, Optional, Tuple

from ..core.ids import content_id, new_id, sha256_hex
from ..sources.model import SourceDocument
from .feed_normalizer import SourceMeta
from .language import normalize_language
from .model import (
    NormalizationEvent,
    NormalizationIssue,
    NormalizationResult,
    NormalizationStatus,
)
from .text import content_fingerprint, normalize_text, normalize_title
from ..ingestion.url_normalize import normalize_url

NORMALIZER_NAME = "tank_article"
NORMALIZER_VERSION = "1.0.0"


def _parse_aware(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def normalize_tank_article(
    article: Mapping[str, object],
    meta: SourceMeta,
    *,
    raw_item_id: str = "",
    normalizer_version: str = NORMALIZER_VERSION,
    now: Optional[datetime] = None,
) -> NormalizationResult:
    """tank記事dict 1件 → SourceDocument。例外を投げない（issueへ構造化）。"""
    issues: List[NormalizationIssue] = []
    documents: List[SourceDocument] = []

    def s(key: str) -> str:
        v = article.get(key, "")
        return v if isinstance(v, str) else ""

    article_id = s("article_id")
    entry_ref = article_id or s("canonical_url")
    title = normalize_title(s("title_original"))
    retrieved_at = _parse_aware(s("fetched_at_utc"))

    if not title:
        issues.append(NormalizationIssue(code="missing_title", entry_ref=entry_ref))
    if retrieved_at is None:
        issues.append(NormalizationIssue(
            code="missing_required_field", entry_ref=entry_ref, detail="fetched_at_utc"))

    if title and retrieved_at is not None:
        locator = s("canonical_url")
        if not locator:
            issues.append(NormalizationIssue(code="missing_locator", entry_ref=entry_ref))
        published = _parse_aware(s("published_at_utc"))
        date_inferred = bool(article.get("date_inferred", False))
        published_raw = s("raw_published_at") or s("published_at_utc")
        if published is None:
            issues.append(NormalizationIssue(code="missing_date", entry_ref=entry_ref))

        summary = normalize_text(s("description"))[:400]
        fingerprint = content_fingerprint(title, summary)
        content_hash = s("content_hash") or sha256_hex(
            (title + "\x1f" + summary).encode("utf-8"))
        documents.append(SourceDocument(
            source_document_id=content_id(
                "doc", entry_ref, NORMALIZER_NAME, normalizer_version),
            source_id=meta.source_id,
            source_tier=meta.tier,
            title=title,
            locator=locator or "tank:" + entry_ref,
            canonical_locator=normalize_url(locator) if locator else "",
            retrieved_at=retrieved_at,
            published_at=published,
            published_raw=published_raw,
            # tank補正値: date_inferred=Trueならfetched_at由来の推定値（機械可読に引き継ぐ）
            published_inferred=date_inferred,
            published_inferred_from="tank_fetched_at" if date_inferred else "",
            date_quality=("source_provided_tz" if published is not None and not date_inferred
                          else "missing"),
            publisher=s("source_name") or meta.publisher,
            language=normalize_language(s("language") or meta.default_language),
            content_hash=content_hash,
            raw_item_id=raw_item_id,  # tank記事はraw非保存（空=原文非保存の明示）
            summary=summary,
            guid=article_id,
            media_type="text/html",
            content_fingerprint=fingerprint,
            normalizer_name=NORMALIZER_NAME,
            normalizer_version=normalizer_version,
        ))

    if not documents:
        status = NormalizationStatus.REJECTED
    elif issues:
        status = NormalizationStatus.PARTIAL
    else:
        status = NormalizationStatus.NORMALIZED

    normalized_at = now or datetime.now(timezone.utc)
    event = NormalizationEvent(
        event_id=new_id("norm", normalized_at),
        raw_item_id=raw_item_id or "tank:no_raw",
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
