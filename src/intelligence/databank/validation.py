"""Data Bank投入前validation gate（Phase 2-A）。

Data Bankへレコード群を入れる前に整合性を機械検査する。silent failureなし
（全問題をstructured issueで返す。修正・削除はしない——報告のみ）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from ..evidence_qa.model import EvidenceAssessment
from ..market.model import Observation
from ..sources.model import RawItem, SourceDocument
from .news_model import ArticleIdentity, NewsClassification, NewsDocumentLink, NewsItem

#: issue語彙（監督者指定の検証項目に対応）
VALIDATION_CODES = (
    "duplicate_id",
    "orphan_reference",
    "missing_provenance",
    "invalid_datetime",
    "invalid_decimal",
    "unknown_enum",
    "broken_revision_relation",
    "raw_document_mismatch",
    "qa_result_missing",
)


@dataclass(frozen=True, kw_only=True)
class ValidationIssue:
    code: str
    record_id: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.code not in VALIDATION_CODES:
            raise ValueError(f"unknown validation code: {self.code}")


def _dupes(ids: Sequence[str]) -> List[str]:
    seen, dupes = set(), []
    for i in ids:
        if i in seen:
            dupes.append(i)
        seen.add(i)
    return dupes


def validate_data_bank(
    *,
    documents: Sequence[SourceDocument] = (),
    raw_items: Sequence[RawItem] = (),
    observations: Sequence[Observation] = (),
    news_items: Sequence[NewsItem] = (),
    article_identities: Sequence[ArticleIdentity] = (),
    document_links: Sequence[NewsDocumentLink] = (),
    classifications: Sequence[NewsClassification] = (),
    assessments: Sequence[EvidenceAssessment] = (),
    require_qa: bool = False,
) -> Tuple[ValidationIssue, ...]:
    """投入候補一式の整合性検査。issue空 = validation gate通過。"""
    issues: List[ValidationIssue] = []
    doc_ids = {d.source_document_id for d in documents}
    raw_ids = {r.raw_item_id for r in raw_items}
    news_ids = {n.news_item_id for n in news_items}
    article_ids = {a.article_id for a in article_identities}
    assessed_ids = {a.record_id for a in assessments}
    raw_by_id = {r.raw_item_id: r for r in raw_items}

    # duplicate IDs
    for kind, ids in (
        ("document", [d.source_document_id for d in documents]),
        ("raw", [r.raw_item_id for r in raw_items]),
        ("observation", [o.observation_id for o in observations]),
        ("news", [n.news_item_id for n in news_items]),
        ("article", [a.article_id for a in article_identities]),
    ):
        for dup in _dupes(ids):
            issues.append(ValidationIssue(code="duplicate_id", record_id=dup, detail=kind))

    # documents: provenance / datetime / revision / raw対応
    for d in documents:
        if not d.source_id or not d.content_hash:
            issues.append(ValidationIssue(
                code="missing_provenance", record_id=d.source_document_id))
        if d.published_at is not None and d.published_at.tzinfo is None:
            issues.append(ValidationIssue(
                code="invalid_datetime", record_id=d.source_document_id))
        if d.revision_of and d.revision_of not in doc_ids:
            issues.append(ValidationIssue(
                code="broken_revision_relation", record_id=d.source_document_id,
                detail=f"revision_of={d.revision_of}"))
        if d.raw_item_id:
            if raw_items and d.raw_item_id not in raw_ids:
                issues.append(ValidationIssue(
                    code="orphan_reference", record_id=d.source_document_id,
                    detail=f"raw_item {d.raw_item_id}"))
            else:
                raw = raw_by_id.get(d.raw_item_id)
                # raw/document不一致: 文書のcontent_hashはentry由来のため、
                # 照合対象は「由来rawのsource_id一致」（同一取得系統か）
                if raw is not None and raw.source_id != d.source_id:
                    issues.append(ValidationIssue(
                        code="raw_document_mismatch", record_id=d.source_document_id,
                        detail=f"doc.source={d.source_id} raw.source={raw.source_id}"))
        if require_qa and d.source_document_id not in assessed_ids:
            issues.append(ValidationIssue(
                code="qa_result_missing", record_id=d.source_document_id))

    # observations: Decimal / datetime / derived provenance
    for o in observations:
        if o.value is not None:
            if not isinstance(o.value, Decimal):
                issues.append(ValidationIssue(code="invalid_decimal",
                                              record_id=o.observation_id))
            elif o.value.is_nan() or o.value.is_infinite():
                issues.append(ValidationIssue(code="invalid_decimal",
                                              record_id=o.observation_id, detail=str(o.value)))
        if o.kind.value == "derived" and not o.inputs:
            issues.append(ValidationIssue(code="missing_provenance",
                                          record_id=o.observation_id, detail="derived inputs"))
        if require_qa and o.observation_id not in assessed_ids:
            issues.append(ValidationIssue(code="qa_result_missing",
                                          record_id=o.observation_id))

    # documents: revision cycle検出（P2-B。chainを辿りループを検知）
    doc_by_id = {d.source_document_id: d for d in documents}
    for d in documents:
        seen = {d.source_document_id}
        cursor = d.revision_of
        while cursor:
            if cursor in seen:
                issues.append(ValidationIssue(
                    code="broken_revision_relation", record_id=d.source_document_id,
                    detail="revision cycle"))
                break
            seen.add(cursor)
            nxt = doc_by_id.get(cursor)
            cursor = nxt.revision_of if nxt else None

    # news layer: 参照整合
    articles_by_id = {a.article_id: a for a in article_identities}
    for a in article_identities:
        if len(a.member_document_ids) != len(set(a.member_document_ids)):
            issues.append(ValidationIssue(code="duplicate_id", record_id=a.article_id,
                                          detail="duplicate member document"))
        for did in a.member_document_ids:
            if documents and did not in doc_ids:
                issues.append(ValidationIssue(code="orphan_reference", record_id=a.article_id,
                                              detail=f"member document {did}"))
    for n in news_items:
        if article_identities and n.article_id not in article_ids:
            issues.append(ValidationIssue(code="orphan_reference", record_id=n.news_item_id,
                                          detail=f"article {n.article_id}"))
        if documents and n.primary_document_id not in doc_ids:
            issues.append(ValidationIssue(code="orphan_reference", record_id=n.news_item_id,
                                          detail=f"primary document {n.primary_document_id}"))
        # P2-B: primaryは所属articleのmemberであること
        owner = articles_by_id.get(n.article_id)
        if owner is not None and n.primary_document_id not in owner.member_document_ids:
            issues.append(ValidationIssue(
                code="orphan_reference", record_id=n.news_item_id,
                detail=f"primary {n.primary_document_id} not in article members"))
    for link in document_links:
        if news_items and link.news_item_id not in news_ids:
            issues.append(ValidationIssue(code="orphan_reference",
                                          record_id=link.news_item_id, detail="link→news"))
        if documents and link.source_document_id not in doc_ids:
            issues.append(ValidationIssue(code="orphan_reference",
                                          record_id=link.source_document_id, detail="link→doc"))
    for c in classifications:
        if news_items and c.news_item_id not in news_ids:
            issues.append(ValidationIssue(code="orphan_reference",
                                          record_id=c.classification_id, detail="cls→news"))

    return tuple(issues)
