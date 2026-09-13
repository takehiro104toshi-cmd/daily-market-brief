"""Revision vs Syndication精緻化（Phase 2-F PART D——P2-C open questionの解決）。

MARK_REVISIONで統合された文書関係のroleを決定論分類する:

    SAME_PUBLISHER_UPDATE    … 同一source feedの更新版（通常のrevision）
    CROSS_FEED_SAME_ARTICLE  … 同一canonical URLを別feedが配信（同一記事の別経路。
                               P2-Cで見つかったbbc_business↔bbc_scienv 2件の正体）
    SYNDICATED_COPY          … 別publisherの転載（本分類では**証明できる場合のみ**）
    UNKNOWN                  … 証明不能（**DO NOT GUESS**——review対象として残す）

semantic NewsEvent clusteringはしない（関係roleの表現整理のみ）。
分類はappend-onlyの別レコード（article events・Article状態は変更しない）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from ..core import serialization
from ..core.ids import content_id
from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION
from ..databank.article_store import IdentityEventType, JsonlArticleStore

ROLE_CLASSIFIER_VERSION = "1.0.0"


class RevisionRole(str, Enum):
    SAME_PUBLISHER_UPDATE = "same_publisher_update"
    CROSS_FEED_SAME_ARTICLE = "cross_feed_same_article"
    SYNDICATED_COPY = "syndicated_copy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class RevisionRoleRecord:
    role_id: str  # rvr_<sha256[:24]>（event×classifier versionから決定論）
    source_event_id: str
    article_id: str
    new_document_id: str
    prior_document_id: str
    role: RevisionRole
    basis: Tuple[str, ...]  # 判定根拠コード（same_source_feed / same_canonical_url等）
    classifier_version: str
    created_at: datetime
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.role_id or not self.source_event_id:
            raise ValueError("role_id / source_event_id are required")
        ensure_aware(self.created_at, "RevisionRoleRecord.created_at")


class JsonlRevisionRoleStore:
    """revision_roles.jsonl（append-only・冪等）。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        serialization.register_domain_types()
        self._path = self.root / "revision_roles.jsonl"
        self._records: Dict[str, RevisionRoleRecord] = {}
        self.recovered_lines = 0
        if self._path.exists():
            with self._path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = serialization.decode(json.loads(line))
                        self._records[r.role_id] = r
                    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                        self.recovered_lines += 1

    def add(self, record: RevisionRoleRecord) -> bool:
        if record.role_id in self._records:
            return False
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(serialization.encode(record), ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._records[record.role_id] = record
        return True

    def iter_records(self) -> Iterator[RevisionRoleRecord]:
        return iter(list(self._records.values()))


def _publisher_domain(locator: str) -> str:
    if "//" not in locator:
        return ""
    host = locator.split("//", 1)[1].split("/", 1)[0].lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_revision_roles(
    article_store: JsonlArticleStore,
    documents_by_id: Dict,
    *,
    now: datetime,
) -> List[RevisionRoleRecord]:
    """全MARK_REVISIONイベントのrole分類（決定論・読み取りのみ）。"""
    members: Dict[str, List[str]] = {}
    records: List[RevisionRoleRecord] = []
    for event in article_store.iter_events():
        if event.event_type is IdentityEventType.CREATE:
            members[event.article_id] = [event.document_id]
            continue
        if event.event_type in (IdentityEventType.ADD_DOCUMENT,
                                IdentityEventType.MARK_SYNDICATED):
            members.setdefault(event.article_id, []).append(event.document_id)
            continue
        if event.event_type is not IdentityEventType.MARK_REVISION:
            continue
        prior_ids = members.get(event.article_id, [])
        prior_id = prior_ids[-1] if prior_ids else ""
        members.setdefault(event.article_id, []).append(event.document_id)

        new_doc = documents_by_id.get(event.document_id)
        prior_doc = documents_by_id.get(prior_id)
        role = RevisionRole.UNKNOWN
        basis: List[str] = []
        if new_doc is not None and prior_doc is not None:
            same_url = bool(new_doc.canonical_locator) and \
                new_doc.canonical_locator == prior_doc.canonical_locator
            if same_url:
                basis.append("same_canonical_url")
            if new_doc.source_id == prior_doc.source_id:
                basis.append("same_source_feed")
                role = RevisionRole.SAME_PUBLISHER_UPDATE
            elif same_url:
                # 別feed×同一canonical URL＝同一記事の別配信経路（機械的に証明可能）
                basis.append("different_source_feed")
                if _publisher_domain(new_doc.canonical_locator) == \
                        _publisher_domain(prior_doc.canonical_locator):
                    basis.append("same_publisher_domain")
                role = RevisionRole.CROSS_FEED_SAME_ARTICLE
            else:
                basis.append("relation_unprovable")  # DO NOT GUESS
        else:
            basis.append("document_unavailable")
        records.append(RevisionRoleRecord(
            role_id=content_id("rvr", event.event_id, ROLE_CLASSIFIER_VERSION),
            source_event_id=event.event_id,
            article_id=event.article_id,
            new_document_id=event.document_id,
            prior_document_id=prior_id,
            role=role,
            basis=tuple(basis),
            classifier_version=ROLE_CLASSIFIER_VERSION,
            created_at=now,
        ))
    return records
