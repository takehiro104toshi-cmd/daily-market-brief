"""記事evidence → 構造的Fact（Phase 3-A STEP 13/14）。

**NEWS FACT EXTRACTION BOUNDARY**:
- **LLMによる自由要約をFactとして保存しない**。
- source articleで**明示されていること**だけを対象にし、推論を混ぜない。
- Phase 3-Aは「構造的に確定できるもの」に限定する。現時点で安全に確定できるのは
  **文書メタデータ由来の事実**（誰がいつ何を公表したか）と、
  **正規化本文中の該当箇所を特定できる引用**である。

したがって本モジュールが作るのは:
- `document_published` … 「その情報源がその日時にその見出しを公表した」という事実。
  見出し本文は解釈せず原文のまま `text_value` に保持し、excerpt spanで
  正規化本文中の位置を指す（citation-ready）。

数値抽出・イベント分類・企業紐付けの自動化は**Phase 3-B以降**の責務。
ここでは citation-ready architecture（Factから「記事のどこが根拠か」へ辿れる形）
までを用意する。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

from .model import (
    ConflictState,
    DateRole,
    EvidenceKind,
    Fact,
    FactEvidenceRef,
    FactStatus,
    FactSubject,
    FactTimeContext,
    FactValue,
    make_fact_id,
    value_token,
)

DOCUMENT_PUBLISHED = "document_published"

#: QA判定がこれらならproduction Factを作らない
_QA_BLOCKS = {"reject"}
_QA_LIMITED = {"limited_use"}


def build_document_facts(
    documents: Iterable,
    *,
    now: Optional[datetime] = None,
    max_excerpt: int = 200,
) -> List[Fact]:
    """正規化済み文書 → `document_published` Fact（citation-ready）。

    `documents` の各要素は以下の属性を持つ想定（既存NewsItem/Article互換）:
    `document_id` / `title` / `published_at` / `source_id` / `qa_decision`。
    本文位置が取れる場合は `body` を使ってexcerpt spanを付ける。
    """
    created_at = now or datetime.now(timezone.utc)
    facts: List[Fact] = []
    for doc in documents:
        document_id = getattr(doc, "document_id", "") or getattr(doc, "item_id", "")
        title = (getattr(doc, "title", "") or "").strip()
        published = getattr(doc, "published_at", None)
        source_id = getattr(doc, "source_id", "") or ""
        qa_decision = (getattr(doc, "qa_decision", "") or "").lower()
        if not document_id or not title or published is None:
            continue                      # 構造的に確定できないものはFactにしない
        if qa_decision in _QA_BLOCKS:
            continue                      # REJECT evidenceからFactを作らない

        published_date = (published.date().isoformat()
                          if hasattr(published, "date") else str(published)[:10])
        body = getattr(doc, "body", "") or ""
        start = body.find(title) if body and title else -1
        end = start + len(title) if start >= 0 else -1
        excerpt = title[:max_excerpt]

        subject = FactSubject(subject_type="entity",
                              subject_id=f"source:{source_id}" if source_id else "source:unknown",
                              display_name=source_id)
        status = (FactStatus.LIMITED_USE if qa_decision in _QA_LIMITED
                  else FactStatus.USABLE)
        facts.append(Fact(
            fact_id=make_fact_id(
                fact_type=DOCUMENT_PUBLISHED, subject=subject,
                primary_date=published_date,
                value_token=value_token(None, f"{document_id}|{title}")),
            fact_type=DOCUMENT_PUBLISHED, subject=subject,
            value=FactValue(text_value=title),
            time=FactTimeContext(
                primary_date=published_date, date_role=DateRole.PUBLICATION_DATE,
                as_of=published if hasattr(published, "tzinfo") and published.tzinfo else None,
                known_at=published if hasattr(published, "tzinfo") and published.tzinfo else None),
            evidence=(FactEvidenceRef(
                kind=EvidenceKind.DOCUMENT, ref_id=document_id,
                locator="title", excerpt=excerpt,
                excerpt_start=start, excerpt_end=end,
                qa_decision=qa_decision),),
            status=status, conflict_state=ConflictState.UNKNOWN,
            source_ids=(source_id,) if source_id else (), qa_decision=qa_decision,
            created_at=created_at))
    return facts
