"""event-sourced Article Store（Phase 2-B）: append-only・replay導出・manual優先。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.core import serialization
from src.intelligence.core.contracts import ArticleIdentityRepository
from src.intelligence.core.ids import new_id
from src.intelligence.databank.article_store import (
    ArticleIdentityEvent,
    IdentityEventType,
    JsonlArticleStore,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def event(event_type: IdentityEventType, article_id: str = "art_1", **kw) -> ArticleIdentityEvent:
    defaults = dict(event_id=new_id("aie", NOW), article_id=article_id,
                    created_at=NOW, actor="algorithm:1.0.0")
    defaults.update(kw)
    return ArticleIdentityEvent(event_type=event_type, **defaults)


def test_create_and_replay_derives_identity(tmp_path: Path) -> None:
    store = JsonlArticleStore(tmp_path)
    store.append_event(event(IdentityEventType.CREATE, document_id="doc_1",
                             identity_basis="exact_canonical_url",
                             canonical_url="https://e.org/a",
                             representative_title="BOJ holds"))
    store.append_event(event(IdentityEventType.MARK_SYNDICATED, document_id="doc_2"))
    identity = store.get_identity("art_1")
    assert identity.member_document_ids == ("doc_1", "doc_2")
    assert store.identity_for_document("doc_2").article_id == "art_1"
    # 再オープン=eventのreplayで同一状態（導出値を正とする）
    reopened = JsonlArticleStore(tmp_path)
    assert reopened.get_identity("art_1") == identity
    assert len(list(reopened.iter_events())) == 2


def test_duplicate_member_not_added(tmp_path: Path) -> None:
    store = JsonlArticleStore(tmp_path)
    store.append_event(event(IdentityEventType.CREATE, document_id="doc_1"))
    store.append_event(event(IdentityEventType.ADD_DOCUMENT, document_id="doc_1"))
    assert store.get_identity("art_1").member_document_ids == ("doc_1",)


def test_set_primary_only_within_members(tmp_path: Path) -> None:
    store = JsonlArticleStore(tmp_path)
    store.append_event(event(IdentityEventType.CREATE, document_id="doc_1"))
    store.append_event(event(IdentityEventType.ADD_DOCUMENT, document_id="doc_2"))
    store.append_event(event(IdentityEventType.SET_PRIMARY, primary_document_id="doc_2"))
    assert store.primary_document_id("art_1") == "doc_2"
    store.append_event(event(IdentityEventType.SET_PRIMARY, primary_document_id="doc_ghost"))
    assert store.primary_document_id("art_1") == "doc_2"  # member外は無視


def test_manual_split_overrides_algorithm_and_keeps_history(tmp_path: Path) -> None:
    """manual correction基盤: 人手の分離はalgorithmより優先・履歴は全て残る。"""
    store = JsonlArticleStore(tmp_path)
    store.append_event(event(IdentityEventType.CREATE, document_id="doc_1"))
    store.append_event(event(IdentityEventType.ADD_DOCUMENT, document_id="doc_wrong"))
    store.append_event(event(IdentityEventType.MANUAL_SPLIT, document_id="doc_wrong",
                             actor="user:takehiro", note="誤結合の修正"))
    identity = store.get_identity("art_1")
    assert "doc_wrong" not in identity.member_document_ids
    # algorithmが誤って戻そうとしても受け付けない（manual優先）
    store.append_event(event(IdentityEventType.ADD_DOCUMENT, document_id="doc_wrong"))
    assert "doc_wrong" not in store.get_identity("art_1").member_document_ids
    # 履歴はappend-onlyで全て残る（4イベント）
    assert len(list(store.iter_events())) == 4
    reopened = JsonlArticleStore(tmp_path)  # replayでも同一結論
    assert "doc_wrong" not in reopened.get_identity("art_1").member_document_ids


def test_manual_merge_moves_members_and_records_history(tmp_path: Path) -> None:
    store = JsonlArticleStore(tmp_path)
    store.append_event(event(IdentityEventType.CREATE, "art_1", document_id="doc_1"))
    store.append_event(event(IdentityEventType.CREATE, "art_2", document_id="doc_2"))
    store.append_event(event(IdentityEventType.MANUAL_MERGE, "art_1",
                             merged_from_article_id="art_2", actor="user:takehiro"))
    merged = store.get_identity("art_1")
    assert set(merged.member_document_ids) == {"doc_1", "doc_2"}
    assert store.get_identity("art_2") is None  # 空になったidentityは存在しない
    assert store.identity_for_document("doc_2").article_id == "art_1"


def test_store_satisfies_repository_protocol(tmp_path: Path) -> None:
    store = JsonlArticleStore(tmp_path)
    assert isinstance(store, ArticleIdentityRepository)


def test_event_serialization_roundtrip_and_crash_recovery(tmp_path: Path) -> None:
    serialization.register_domain_types()
    store = JsonlArticleStore(tmp_path)
    e = event(IdentityEventType.CREATE, document_id="doc_1",
              identity_basis="exact_guid", decision_kind="distinct")
    store.append_event(e)
    decoded = serialization.decode(serialization.encode(e))
    assert decoded == e
    with (tmp_path / "article_identity_events.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"_type": "ArticleIdentityEvent", "event_id": "aie_trunc')
    reopened = JsonlArticleStore(tmp_path)
    assert reopened.recovered_lines == 1
    assert reopened.get_identity("art_1") is not None


def test_event_requires_actor() -> None:
    with pytest.raises(ValueError):
        ArticleIdentityEvent(event_id="aie_x", article_id="art_1",
                             event_type=IdentityEventType.CREATE,
                             created_at=NOW, actor="")
