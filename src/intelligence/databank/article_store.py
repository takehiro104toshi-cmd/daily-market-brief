"""Article Identity Store（Phase 2-B）。event-sourced・append-only。

正本 = ArticleIdentityEvent のJSONL（破壊的上書きなし）。現在状態（ArticleIdentity）
はeventの**replayで導出**する（二重保存しない——P1-B以来の「導出値を正とする」原則）。

manual correction基盤: MANUAL_SPLIT / MANUAL_MERGE はalgorithm判定より優先され、
manual操作済みのarticle/documentへのalgorithm由来の変更は無視される。履歴は全て残る。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from ..core import serialization
from ..core.ids import new_id
from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION
from .news_model import ArticleIdentity


class IdentityEventType(str, Enum):
    CREATE = "create"
    ADD_DOCUMENT = "add_document"
    MARK_REVISION = "mark_revision"
    MARK_SYNDICATED = "mark_syndicated"
    SET_PRIMARY = "set_primary"
    MANUAL_SPLIT = "manual_split"    # documentをarticleから人手で分離
    MANUAL_MERGE = "manual_merge"    # 人手でのarticle統合


@dataclass(frozen=True, kw_only=True)
class ArticleIdentityEvent:
    """identity変更1件=1イベント（append-only。semantic状態はreplayで導出）。"""

    event_id: str  # aie_<ULID>
    event_type: IdentityEventType
    article_id: str
    created_at: datetime  # processing timestamp（記事内容のsemanticsとは分離）
    document_id: str = ""
    primary_document_id: str = ""
    identity_basis: str = ""  # CREATE時
    canonical_url: str = ""
    representative_title: str = ""
    actor: str = ""  # "algorithm:<version>" / "user:<name>"（manual判定の優先制御）
    decision_kind: str = ""  # IdentityDecisionKind value（trace）
    note: str = ""
    merged_from_article_id: str = ""  # MANUAL_MERGE時
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_id or not self.article_id:
            raise ValueError("event_id / article_id are required")
        if not self.actor:
            raise ValueError("actor is required（algorithm/manualの優先制御に必須）")
        ensure_aware(self.created_at, "ArticleIdentityEvent.created_at")

    @property
    def is_manual(self) -> bool:
        return self.actor.startswith("user:")


@dataclass
class _ArticleState:
    identity_basis: str = ""
    canonical_url: str = ""
    representative_title: str = ""
    members: List[str] = field(default_factory=list)
    primary_document_id: str = ""
    manual_locked: bool = False  # manual操作後はalgorithm変更を受け付けない
    merged_into: str = ""  # MANUAL_MERGEで他articleへ吸収された場合


class JsonlArticleStore:
    """ArticleIdentityRepository実装（event JSONL正本＋replay導出状態）。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "article_identity_events.jsonl"
        serialization.register_domain_types()
        self._events: List[ArticleIdentityEvent] = []
        self._states: Dict[str, _ArticleState] = {}
        self._doc_to_article: Dict[str, str] = {}
        self._manually_split_docs: set = set()
        self.recovered_lines = 0
        self._load()

    # ------------------------------------------------------------- 永続・replay

    def _load(self) -> None:
        if self._path.exists():
            with self._path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = serialization.decode(json.loads(line))
                    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                        self.recovered_lines += 1
                        continue
                    self._events.append(event)
                    self._apply(event)

    def _apply(self, e: ArticleIdentityEvent) -> None:
        state = self._states.setdefault(e.article_id, _ArticleState())
        if state.manual_locked and not e.is_manual:
            return  # manual優先: algorithm由来の後続変更は状態へ反映しない（eventは残る）
        if e.event_type is IdentityEventType.CREATE:
            state.identity_basis = e.identity_basis
            state.canonical_url = e.canonical_url
            state.representative_title = e.representative_title
            if e.document_id and e.document_id not in state.members:
                state.members.append(e.document_id)
                state.primary_document_id = state.primary_document_id or e.document_id
                self._doc_to_article[e.document_id] = e.article_id
        elif e.event_type in (IdentityEventType.ADD_DOCUMENT,
                              IdentityEventType.MARK_REVISION,
                              IdentityEventType.MARK_SYNDICATED):
            if e.document_id in self._manually_split_docs and not e.is_manual:
                return  # 人手で分離済みのdocをalgorithmが戻すことは不可
            if e.document_id and e.document_id not in state.members:
                state.members.append(e.document_id)
                self._doc_to_article[e.document_id] = e.article_id
        elif e.event_type is IdentityEventType.SET_PRIMARY:
            if e.primary_document_id in state.members:
                state.primary_document_id = e.primary_document_id
        elif e.event_type is IdentityEventType.MANUAL_SPLIT:
            if e.document_id in state.members:
                state.members.remove(e.document_id)
                self._doc_to_article.pop(e.document_id, None)
                self._manually_split_docs.add(e.document_id)
                if state.primary_document_id == e.document_id:
                    state.primary_document_id = state.members[0] if state.members else ""
            state.manual_locked = True
        elif e.event_type is IdentityEventType.MANUAL_MERGE:
            src = self._states.get(e.merged_from_article_id)
            if src is not None:
                for doc_id in src.members:
                    if doc_id not in state.members:
                        state.members.append(doc_id)
                        self._doc_to_article[doc_id] = e.article_id
                src.members = []
                src.merged_into = e.article_id
            state.manual_locked = True

    def append_event(self, event: ArticleIdentityEvent) -> None:
        line = json.dumps(serialization.encode(event), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._events.append(event)
        self._apply(event)

    def iter_events(self) -> Iterator[ArticleIdentityEvent]:
        return iter(list(self._events))

    # ------------------------------------------------------------- 導出状態の取得

    def _to_identity(self, article_id: str, state: _ArticleState) -> Optional[ArticleIdentity]:
        if not state.members:
            return None  # 空（split/merge済み）はArticleとして存在しない
        return ArticleIdentity(
            article_id=article_id,
            member_document_ids=tuple(state.members),
            canonical_url=state.canonical_url,
            representative_title=state.representative_title,
            identity_basis=state.identity_basis or "manual",
        )

    def get_identity(self, article_id: str) -> Optional[ArticleIdentity]:
        state = self._states.get(article_id)
        return self._to_identity(article_id, state) if state else None

    def identity_for_document(self, source_document_id: str) -> Optional[ArticleIdentity]:
        article_id = self._doc_to_article.get(source_document_id)
        return self.get_identity(article_id) if article_id else None

    def iter_identities(self) -> Iterator[ArticleIdentity]:
        for article_id, state in self._states.items():
            identity = self._to_identity(article_id, state)
            if identity is not None:
                yield identity

    def primary_document_id(self, article_id: str) -> str:
        state = self._states.get(article_id)
        return state.primary_document_id if state else ""

    def add_identities(self, identities: Sequence[ArticleIdentity]) -> int:
        """ArticleIdentityRepository互換の一括登録（CREATE eventへ展開）。"""
        count = 0
        for identity in identities:
            if self.get_identity(identity.article_id) is not None:
                continue
            for i, doc_id in enumerate(identity.member_document_ids):
                self.append_event(ArticleIdentityEvent(
                    event_id=new_id("aie"),
                    event_type=(IdentityEventType.CREATE if i == 0
                                else IdentityEventType.ADD_DOCUMENT),
                    article_id=identity.article_id,
                    created_at=_now(),
                    document_id=doc_id,
                    identity_basis=identity.identity_basis,
                    canonical_url=identity.canonical_url,
                    representative_title=identity.representative_title,
                    actor="algorithm:bulk",
                ))
            count += 1
        return count


def _now() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)
