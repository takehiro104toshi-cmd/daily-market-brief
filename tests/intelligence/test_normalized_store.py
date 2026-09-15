"""JsonlNormalizedStore（Phase 1-D）: append-only・冪等・crash-safe・Protocol充足。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.core.contracts import (
    NormalizationEventRepository,
    ObservationRepository,
    SourceDocumentRepository,
)
from src.intelligence.core.types import SourceTier
from src.intelligence.normalization.model import (
    NormalizationEvent,
    NormalizationIssue,
    NormalizationStatus,
)
from src.intelligence.normalization.store import JsonlNormalizedStore
from src.intelligence.sources.model import SourceDocument

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def make_doc(doc_id: str = "doc_a1", title: str = "T") -> SourceDocument:
    return SourceDocument(
        source_document_id=doc_id,
        source_id="s",
        source_tier=SourceTier.TIER2,
        title=title,
        locator="https://e.org/a",
        retrieved_at=NOW,
        content_hash="ab" * 32,
        raw_item_id="raw_x",
        normalizer_name="feed_entry",
        normalizer_version="1.0.0",
    )


def make_event(event_id: str = "norm_1") -> NormalizationEvent:
    return NormalizationEvent(
        event_id=event_id, raw_item_id="raw_x", normalizer_name="feed_entry",
        normalizer_version="1.0.0", normalized_at=NOW,
        status=NormalizationStatus.PARTIAL,
        issues=(NormalizationIssue(code="missing_date", entry_ref="g1"),),
        produced_document_ids=("doc_a1",),
    )


def test_roundtrip_and_reopen(tmp_path: Path) -> None:
    store = JsonlNormalizedStore(tmp_path)
    assert store.add_documents([make_doc()]) == 1
    store.add_event(make_event())
    reopened = JsonlNormalizedStore(tmp_path)
    assert reopened.get_document("doc_a1") == make_doc()
    assert reopened.documents_for_raw_item("raw_x")[0].source_document_id == "doc_a1"
    events = reopened.events_for_raw_item("raw_x")
    assert len(events) == 1 and events[0].issues[0].code == "missing_date"
    assert reopened.recovered_lines == 0


def test_idempotent_and_collision(tmp_path: Path) -> None:
    store = JsonlNormalizedStore(tmp_path)
    assert store.add_documents([make_doc(), make_doc()]) == 1  # 同一内容は冪等
    with pytest.raises(ValueError):
        store.add_documents([make_doc(title="Different")])  # 同一IDで内容差


def test_v1_v2_coexist_without_overwrite(tmp_path: Path) -> None:
    store = JsonlNormalizedStore(tmp_path)
    store.add_documents([make_doc("doc_v1")])
    store.add_documents([make_doc("doc_v2")])  # v2再処理は新ID
    assert store.get_document("doc_v1") is not None
    assert store.get_document("doc_v2") is not None
    assert len(list(store.iter_documents())) == 2


def test_crash_recovery(tmp_path: Path) -> None:
    store = JsonlNormalizedStore(tmp_path)
    store.add_documents([make_doc()])
    with (tmp_path / "source_documents.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"_type": "SourceDocument", "source_document_id": "doc_trun')
    reopened = JsonlNormalizedStore(tmp_path)
    assert len(list(reopened.iter_documents())) == 1
    assert reopened.recovered_lines == 1


def test_satisfies_repository_protocols(tmp_path: Path) -> None:
    store = JsonlNormalizedStore(tmp_path)
    assert isinstance(store, SourceDocumentRepository)
    assert isinstance(store, ObservationRepository)
    assert isinstance(store, NormalizationEventRepository)
