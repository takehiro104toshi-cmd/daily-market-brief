"""Identity Decision Ledger（Phase 2-F PART C——P2-C open questionの解決）。

- IdentityDecision（confidence / matched_signals / failed_signals / reason_codes /
  algorithm_version——P2-Bで型定義済み）を**永続化**するledger。
- derivation区別（黙って混ぜない）:
    "live"                 … ingest時にruntimeが記録した判定そのもの
    "post_hoc_full_corpus" … 既存CANDIDATE等について、現在の全corpusに対して
                             決定論的に再導出した監査用判定（**元のruntime判定の
                             主張ではない**。当時のingest順の状態は再現しない）
- **migration-safe**: backfillはledgerレコードだけを書く。article events・
  Article状態には一切触れない（既存3,001 Articleを再identityしない）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

from ..core import serialization
from ..core.ids import content_id
from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION
from ..databank.article_store import IdentityEventType, JsonlArticleStore
from ..databank.identity_blocking import BlockingIndex
from ..databank.identity_decision import IdentityDecision
from ..databank.identity_resolver import DEFAULT_THRESHOLDS, resolve

DERIVATIONS = ("live", "post_hoc_full_corpus")


@dataclass(frozen=True, kw_only=True)
class IdentityLedgerEntry:
    ledger_id: str  # idl_<sha256[:24]>（doc×algorithm×derivationから決定論）
    document_id: str
    article_id: str            # 当該documentが属するArticle
    original_decision_kind: str  # eventに残るruntime判定（trace）
    derivation: str            # DERIVATIONS参照
    decision: IdentityDecision  # signals/confidence/algorithm_version入りの完全判定
    source_event_id: str = ""  # 対応するArticleIdentityEvent
    created_at: datetime
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.ledger_id or not self.document_id:
            raise ValueError("ledger_id / document_id are required")
        if self.derivation not in DERIVATIONS:
            raise ValueError(f"unknown derivation: {self.derivation}")
        ensure_aware(self.created_at, "IdentityLedgerEntry.created_at")

    @staticmethod
    def make_id(document_id: str, algorithm_version: str, derivation: str) -> str:
        return content_id("idl", document_id, algorithm_version, derivation)


class JsonlIdentityLedger:
    """identity_decision_ledger.jsonl（append-only・冪等）。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        serialization.register_domain_types()
        self._path = self.root / "identity_decision_ledger.jsonl"
        self._entries: Dict[str, IdentityLedgerEntry] = {}
        self.recovered_lines = 0
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = serialization.decode(json.loads(line))
                    self._entries[entry.ledger_id] = entry
                except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                    self.recovered_lines += 1

    def add(self, entry: IdentityLedgerEntry) -> bool:
        if entry.ledger_id in self._entries:
            return False  # 冪等
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(serialization.encode(entry), ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._entries[entry.ledger_id] = entry
        return True

    def iter_entries(self) -> Iterator[IdentityLedgerEntry]:
        return iter(list(self._entries.values()))

    def entries_for_document(self, document_id: str) -> Tuple[IdentityLedgerEntry, ...]:
        return tuple(e for e in self._entries.values() if e.document_id == document_id)


def backfill_candidate_ledger(
    ledger: JsonlIdentityLedger,
    article_store: JsonlArticleStore,
    documents,  # Iterable[SourceDocument]（corpus全文書）
    *,
    now: datetime,
    thresholds=DEFAULT_THRESHOLDS,
) -> int:
    """既存CANDIDATEへのdecision ledger backfill（**migration-safe**）。

    現在の全corpusに対しsignalsを決定論再導出してledgerへ書くのみ。
    article events / Article状態は一切変更しない。
    """
    docs = {}
    blocking = BlockingIndex()
    for doc in documents:
        docs[doc.source_document_id] = doc
        blocking.add(doc)

    added = 0
    for event in article_store.iter_events():
        if event.event_type is not IdentityEventType.CREATE or \
                event.decision_kind != "candidate":
            continue
        doc = docs.get(event.document_id)
        if doc is None:
            continue
        # 候補article（自article・自document除外）をblockingで生成しresolverで再判定
        by_article: Dict[str, tuple] = {}
        for candidate_id in sorted(blocking.candidates(doc)):
            if candidate_id == doc.source_document_id or candidate_id not in docs:
                continue
            identity = article_store.identity_for_document(candidate_id)
            if identity is None or identity.article_id == event.article_id:
                continue
            by_article.setdefault(identity.article_id, (identity, []))[1].append(
                docs[candidate_id])
        decision = resolve(doc, list(by_article.values()), thresholds=thresholds)
        entry = IdentityLedgerEntry(
            ledger_id=IdentityLedgerEntry.make_id(
                doc.source_document_id, decision.algorithm_version,
                "post_hoc_full_corpus"),
            document_id=doc.source_document_id,
            article_id=event.article_id,
            original_decision_kind="candidate",
            derivation="post_hoc_full_corpus",
            decision=decision,
            source_event_id=event.event_id,
            created_at=now,
        )
        added += 1 if ledger.add(entry) else 0
    return added


def record_live_decision(
    ledger: JsonlIdentityLedger,
    decision: IdentityDecision,
    *,
    article_id: str,
    source_event_id: str = "",
    now: datetime,
) -> bool:
    """今後のingest経路用: runtime判定をそのままledgerへ記録する（derivation=live）。"""
    return ledger.add(IdentityLedgerEntry(
        ledger_id=IdentityLedgerEntry.make_id(
            decision.document_id, decision.algorithm_version, "live"),
        document_id=decision.document_id,
        article_id=article_id,
        original_decision_kind=decision.decision.value,
        derivation="live",
        decision=decision,
        source_event_id=source_event_id,
        created_at=now,
    ))
