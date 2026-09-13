"""Phase 1-A JSONL参照実装ストアのテスト（repository契約・重複ID規約・往復）。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src.intelligence.core import contracts
from src.intelligence.evidence.jsonl_store import JsonlEvidenceStore

from . import evidence_fixtures as fx


@pytest.fixture()
def store(tmp_path):
    return JsonlEvidenceStore(tmp_path / "evidence")


def test_satisfies_repository_protocols(store) -> None:
    assert isinstance(store, contracts.EvidenceRepository)
    assert isinstance(store, contracts.MarketRepository)


def test_document_statement_link_roundtrip(store) -> None:
    doc, fact, link = fx.boj_statement()
    assert store.add_documents([doc]) == 1
    assert store.add_statements([fact]) == 1
    assert store.add_links([link]) == 1
    assert store.get_document(doc.source_document_id) == doc
    assert store.links_for(fact.statement_id) == [link]
    from datetime import timezone

    day = fact.created_at.astimezone(timezone.utc).date()  # 契約: UTC暦日
    assert fact in store.statements_on(day)
    assert store.statements_on(date(2020, 1, 1)) == []


def test_duplicate_same_content_is_idempotent(store) -> None:
    doc, fact, link = fx.boj_statement()
    assert store.add_statements([fact]) == 1
    assert store.add_statements([fact]) == 0  # 冪等スキップ
    assert len(store.all_statements()) == 1


def test_duplicate_different_content_rejected(store) -> None:
    _, fact, _ = fx.boj_statement()
    store.add_statements([fact])
    tampered = replace(fact, text=fact.text + "（改変）")
    with pytest.raises(ValueError):
        store.add_statements([tampered])  # Evidenceは不変。改定は新ID＋revision_of


def test_observation_series_sorted(store) -> None:
    base = fx.jp_stock_observation()
    derived = fx.derived_observation(base)
    assert store.record([base, derived]) == 2
    day = base.as_of.date()
    series = store.series(base.entity_id, "close", day, day)
    assert series == [base]
    dev = store.series(base.entity_id, "dev_25dma", day, day)
    assert dev == [derived]
    assert dev[0].inputs == (base.observation_id,)  # 派生のprovenanceが保存されている


def test_revision_pair_coexists(store) -> None:
    doc, first, revised = fx.cpi_release_with_revision()
    store.add_documents([doc])
    assert store.record([first, revised]) == 2  # 過去値を上書きしない
    day = first.as_of.date()
    values = store.series("macro:us_cpi", "yoy_pct", day, day)
    assert {str(v.value) for v in values} == {"4.1", "4.2"}


def test_full_synthetic_corpus_persists(store, tmp_path) -> None:
    """全フィクスチャを保存→別インスタンスで再読込しても等価。"""
    chain = fx.causal_chain()
    docs = [chain[0]]
    stmts = [chain[1], chain[3], chain[4], fx.unsupported_ai_claim()]
    links = [chain[2], chain[5], chain[6]]
    store.add_documents(docs)
    store.add_statements(stmts)
    store.add_links(links)
    reopened = JsonlEvidenceStore(store.root)
    assert sorted(s.statement_id for s in reopened.all_statements()) == sorted(
        s.statement_id for s in stmts
    )
    assert len(reopened.all_links()) == 3
