"""Identity runtime（Phase 2-B）: SourceDocument → ArticleIdentity → NewsItem の接続。

NewsItemはmetadata container（Fact抽出・分類・スコア生成はしない）。

ID設計判断（NEWSITEM IDENTITY）:
- **Article = identityオブジェクト**（同一記事の束・event-sourced）
- **NewsItem = databank表現**（検索・索引・将来のNewsEvent束ねの単位）
  news_item_id = content_id("news", article_id) で1:1導出だが**別型・別名前空間**とする。
  将来NewsEvent層が入るとNewsItem粒度の再編（event単位のrepresentation）がありうるため、
  完全同義（同一ID文字列）にはしない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional, Sequence, Tuple

from ..core.ids import new_id
from ..sources.model import SourceDocument
from .article_store import ArticleIdentityEvent, IdentityEventType, JsonlArticleStore
from .identity_blocking import BlockingIndex
from .identity_decision import IdentityDecision, IdentityDecisionKind
from .identity_resolver import (
    ALGORITHM_VERSION,
    DEFAULT_THRESHOLDS,
    IdentityThresholds,
    resolve,
)
from .news_model import (
    ArticleIdentity,
    DocumentLinkRole,
    NewsDocumentLink,
    NewsItem,
)


# ---------------------------------------------------------------- primary選定


def select_primary(
    docs: Sequence[SourceDocument],
    syndicated_ids: frozenset = frozenset(),
) -> Tuple[str, str]:
    """primary document決定 → (document_id, basis説明)。

    規則（順に適用。「Tierが高い=原文」とは限らないためtierは最後の補助）:
      1. 非転載（SYNDICATED判定でないmember）を優先
      2. published_atが最も早い（原文が先に出るのが通例）
      3. tierが高い（数値が小さい）
      4. document_id辞書順（決定論的タイブレーク）
    """
    def sort_key(d: SourceDocument):
        return (
            d.source_document_id in syndicated_ids,  # False（非転載）が先
            d.published_at or datetime.max.replace(tzinfo=timezone.utc),
            int(d.source_tier.value),
            d.source_document_id,
        )

    chosen = sorted(docs, key=sort_key)[0]
    basis = []
    if chosen.source_document_id not in syndicated_ids and syndicated_ids:
        basis.append("non_syndicated")
    if chosen.published_at is not None:
        basis.append("earliest_published")
    basis.append(f"tier{chosen.source_tier.value}")
    return chosen.source_document_id, "+".join(basis)


# ---------------------------------------------------------------- runtime編成


@dataclass(frozen=True, kw_only=True)
class IngestResult:
    document_id: str
    decision: IdentityDecision
    article: Optional[ArticleIdentity] = None  # CANDIDATE時は既存不変のためNoneもあり


class IdentityRuntime:
    """resolver＋event store＋NewsItem構築の編成。"""

    def __init__(
        self,
        store: JsonlArticleStore,
        *,
        thresholds: IdentityThresholds = DEFAULT_THRESHOLDS,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._store = store
        self._thresholds = thresholds
        self._clock = clock
        self._docs: dict = {}  # document_id -> SourceDocument（member照合用）
        self._syndicated: set = set()
        # 候補生成のblocking index（総当たりO(n²)禁止——IDENTITY SCALING指示）
        self._blocking = BlockingIndex()

    def _candidate_articles(self, doc: SourceDocument):
        """blocking indexで絞った候補documentの所属articleのみをresolverへ渡す。"""
        candidate_ids = self._blocking.candidates(doc)
        by_article: dict = {}
        for doc_id in sorted(candidate_ids):
            identity = self._store.identity_for_document(doc_id)
            if identity is None or doc_id not in self._docs:
                continue
            by_article.setdefault(identity.article_id, (identity, []))[1].append(
                self._docs[doc_id])
        return list(by_article.values())

    def preload(self, documents) -> int:
        """resume用: 既存canonical文書でin-memory索引（docs/blocking/syndicated）を再構築。

        導出物の再構築であり二重保存ではない（storeのevent replayと同型の思想）。
        """
        count = 0
        for doc in documents:
            if doc.source_document_id not in self._docs:
                self._docs[doc.source_document_id] = doc
                self._blocking.add(doc)
                count += 1
        for e in self._store.iter_events():
            if e.event_type is IdentityEventType.MARK_SYNDICATED and e.document_id:
                self._syndicated.add(e.document_id)
        return count

    def ingest_document(self, doc: SourceDocument) -> IngestResult:
        """文書1件をidentity判定し、eventとして永続する。CANDIDATEはmergeしない。"""
        self._docs[doc.source_document_id] = doc
        existing = self._store.identity_for_document(doc.source_document_id)
        if existing is not None:  # 冪等（同一文書の再投入）
            return IngestResult(
                document_id=doc.source_document_id,
                decision=IdentityDecision(
                    decision=IdentityDecisionKind.EXACT_MATCH,
                    document_id=doc.source_document_id,
                    matched_article_id=existing.article_id,
                    algorithm_version=ALGORITHM_VERSION,
                    matched_signals=(), reason_codes=()),
                article=existing)

        decision = resolve(doc, self._candidate_articles(doc), thresholds=self._thresholds)
        self._blocking.add(doc)
        now = self._clock()
        actor = f"algorithm:{ALGORITHM_VERSION}"

        if decision.decision is IdentityDecisionKind.DISTINCT or (
            decision.decision is IdentityDecisionKind.CANDIDATE
        ):
            if decision.decision is IdentityDecisionKind.CANDIDATE:
                # 曖昧候補: mergeせず新Articleとして扱う（候補情報はdecisionに残る）
                pass
            article_id = ArticleIdentity.make_id(
                doc.canonical_locator or doc.guid or doc.source_document_id)
            self._store.append_event(ArticleIdentityEvent(
                event_id=new_id("aie", now), event_type=IdentityEventType.CREATE,
                article_id=article_id, created_at=now,
                document_id=doc.source_document_id,
                identity_basis="exact_canonical_url" if doc.canonical_locator else (
                    "exact_guid" if doc.guid else "exact_fingerprint"),
                canonical_url=doc.canonical_locator,
                representative_title=doc.title,
                actor=actor, decision_kind=decision.decision.value))
            return IngestResult(document_id=doc.source_document_id, decision=decision,
                                article=self._store.get_identity(article_id))

        # merge系（EXACT_MATCH / AUTO_MERGE / REVISION / SYNDICATED）
        event_type = {
            IdentityDecisionKind.EXACT_MATCH: IdentityEventType.ADD_DOCUMENT,
            IdentityDecisionKind.AUTO_MERGE: IdentityEventType.ADD_DOCUMENT,
            IdentityDecisionKind.REVISION: IdentityEventType.MARK_REVISION,
            IdentityDecisionKind.SYNDICATED: IdentityEventType.MARK_SYNDICATED,
        }[decision.decision]
        if decision.decision is IdentityDecisionKind.SYNDICATED:
            self._syndicated.add(doc.source_document_id)
        self._store.append_event(ArticleIdentityEvent(
            event_id=new_id("aie", now), event_type=event_type,
            article_id=decision.matched_article_id, created_at=now,
            document_id=doc.source_document_id, actor=actor,
            decision_kind=decision.decision.value,
            note=",".join(decision.matched_signals)))
        # primary再選定
        article = self._store.get_identity(decision.matched_article_id)
        if article is not None:
            docs = [self._docs[d] for d in article.member_document_ids if d in self._docs]
            primary_id, basis = select_primary(docs, frozenset(self._syndicated))
            self._store.append_event(ArticleIdentityEvent(
                event_id=new_id("aie", now), event_type=IdentityEventType.SET_PRIMARY,
                article_id=article.article_id, created_at=now,
                primary_document_id=primary_id, actor=actor, note=basis))
        return IngestResult(document_id=doc.source_document_id, decision=decision,
                            article=article)

    # ------------------------------------------------------------- NewsItem構築

    def build_news_item(self, article: ArticleIdentity) -> Tuple[NewsItem, Tuple[NewsDocumentLink, ...]]:
        """ArticleからNewsItem（metadata container）とdocument linksを構築する。"""
        primary_id = self._store.primary_document_id(article.article_id) or \
            article.member_document_ids[0]
        primary = self._docs[primary_id]
        news = NewsItem(
            news_item_id=NewsItem.make_id(article.article_id),
            article_id=article.article_id,
            primary_document_id=primary_id,
            headline=primary.title,
            published_at=primary.published_at,
            publisher=primary.publisher,
            source_id=primary.source_id,
            language=primary.language,
            canonical_url=primary.canonical_locator or primary.locator,
            summary=primary.summary,
            guid=primary.guid,
        )
        links = tuple(
            NewsDocumentLink(
                news_item_id=news.news_item_id,
                source_document_id=doc_id,
                role=(DocumentLinkRole.PRIMARY if doc_id == primary_id
                      else DocumentLinkRole.SYNDICATED if doc_id in self._syndicated
                      else DocumentLinkRole.UPDATE),
            )
            for doc_id in article.member_document_ids
        )
        return news, links
