"""Backfillエンジン（Phase 2-C）: inventory・fingerprint・checkpoint/resume・冪等・
reject ledger・legacy隔離・会計一致。全て合成mini-shard（実tankへは触れない）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.intelligence.databank.backfill import (
    BackfillEngine,
    open_stores,
    reconcile,
)
from src.intelligence.databank.backfill_inventory import build_inventory
from src.intelligence.evidence_qa.policy import HISTORICAL_V1

CATALOG = {"feeds": [
    {"id": "bbc_business", "name": "BBC News — Business", "tier": 2},
    {"id": "nhk_business", "name": "NHKニュース 経済", "tier": 2},
]}

RECORDS = [
    {"article_id": "art_ok1", "source_name": "BBC News — Business",
     "source_domain": "bbc.co.uk", "language": "en",
     "title_original": "West Africa signs off $25bn gas pipeline plan",
     "description": "Leaders approved the pipeline after a decade of talks.",
     "canonical_url": "https://bbc.example/gas", "importance_score": 0.7,
     "themes": ["energy"], "sentiment": "neutral",
     "published_at_utc": "2026-07-20T09:00:00+00:00",
     "fetched_at_utc": "2026-07-20T10:00:00+00:00", "content_hash": "aa" * 32},
    {"article_id": "art_ok2", "source_name": "NHKニュース 経済",
     "source_domain": "nhk.or.jp", "language": "ja",
     "title_original": "日銀、政策金利を維持",
     "description": "日銀は政策金利の維持を決めた。",
     "canonical_url": "https://nhk.example/boj",
     "published_at_utc": "2026-07-31T04:00:00+00:00",
     "fetched_at_utc": "2026-07-31T05:00:00+00:00", "content_hash": "bb" * 32},
    {"article_id": "art_unknown_src", "source_name": "謎の情報源",
     "source_domain": "mystery.example", "language": "ja",
     "title_original": "未知ソースの記事",
     "description": "本文。",
     "canonical_url": "https://mystery.example/x",
     "published_at_utc": "2026-07-21T00:00:00+00:00",
     "fetched_at_utc": "2026-07-21T01:00:00+00:00"},
    {"article_id": "art_no_title", "source_name": "BBC News — Business",
     "source_domain": "bbc.co.uk", "language": "en",
     "title_original": "",  # 必須identity欠落 → REJECT
     "canonical_url": "https://bbc.example/broken",
     "published_at_utc": "2026-07-22T09:00:00+00:00",
     "fetched_at_utc": "2026-07-22T10:00:00+00:00"},
    {"article_id": "art_no_date", "source_name": "BBC News — Business",
     "source_domain": "bbc.co.uk", "language": "en",
     "title_original": "Article without published date",
     "description": "Optional欠損はREJECTにしない。",
     "canonical_url": "https://bbc.example/nodate",
     "fetched_at_utc": "2026-07-23T10:00:00+00:00"},  # published欠損 → PARTIAL
]


@pytest.fixture()
def dataset(tmp_path: Path) -> Path:
    root = tmp_path / "shards"
    day_dir = root / "2026" / "07"
    day_dir.mkdir(parents=True)
    shard1 = day_dir / "2026-07-20.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in RECORDS[:3]]
    lines.append("{broken json line")  # invalid JSON → reject ledger
    shard1.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shard2 = day_dir / "2026-07-22.jsonl"
    shard2.write_text("\n".join(
        json.dumps(r, ensure_ascii=False) for r in RECORDS[3:]) + "\n", encoding="utf-8")
    return root


def run_backfill(dataset: Path, workdir: Path, **kw):
    stores = open_stores(workdir)
    engine = BackfillEngine(dataset, stores, HISTORICAL_V1, CATALOG, chunk_size=2)
    inventory = build_inventory(dataset)
    run = engine.run(inventory, **kw)
    return stores, engine, inventory, run


def test_inventory_measures_input(dataset: Path) -> None:
    inv = build_inventory(dataset)
    assert inv.total_records == 5 and inv.invalid_json_lines == 1
    assert inv.shard_count == 2
    assert inv.language_counts == {"en": 3, "ja": 2}
    assert inv.missing_field_counts["title_original"] == 1
    assert inv.missing_field_counts["published_at_utc"] == 1
    assert inv.legacy_annotation_present == 1
    assert inv.date_range[0].startswith("2026-07-20")


def test_input_fingerprint_detects_dataset_change(dataset: Path) -> None:
    fp1 = build_inventory(dataset).input_fingerprint
    assert fp1 == build_inventory(dataset).input_fingerprint  # 安定
    next(dataset.rglob("*.jsonl")).write_text("{}\n", encoding="utf-8")
    assert build_inventory(dataset).input_fingerprint != fp1  # 変化を検出


def test_full_run_counts_and_reconciliation(dataset: Path, tmp_path: Path) -> None:
    stores, _e, inv, run = run_backfill(dataset, tmp_path / "bank")
    assert run.status == "completed"
    assert run.records_seen == 6  # 5 records + invalid line
    assert run.records_success == 3  # ok1/ok2/unknown_src
    assert run.records_partial == 1  # no_date（optional欠損はREJECTしない）
    assert run.records_rejected == 2  # invalid json + no_title
    assert run.records_failed == 0
    ok, detail = reconcile(run)
    assert ok, detail
    assert run.trust_policy == "HISTORICAL:1.0.0"
    assert run.input_fingerprint == inv.input_fingerprint
    assert run.normalizer_version and run.identity_algorithm_version


def test_canonical_outputs_and_news_items(dataset: Path, tmp_path: Path) -> None:
    stores, _e, _inv, _run = run_backfill(dataset, tmp_path / "bank")
    docs = list(stores.normalized.iter_documents())
    assert len(docs) == 4  # success 3 + partial 1
    assert all(d.normalizer_name == "tank_article" for d in docs)  # migration由来の区別
    assert all(d.raw_item_id == "" for d in docs)  # fetch provenance捏造なし
    assert len(list(stores.news_bank.iter_news_items())) == 4
    assert len(list(stores.articles.iter_identities())) == 4
    assessments = list(stores.qa.iter_assessments())
    assert len(assessments) == 4
    assert all(a.policy_name == "HISTORICAL" for a in assessments)  # HISTORICAL QA適用


def test_reject_ledger_records_reasons(dataset: Path, tmp_path: Path) -> None:
    stores, _e, _inv, run = run_backfill(dataset, tmp_path / "bank")
    rejects = stores.news_bank.iter_rejects()
    assert len(rejects) == 2
    by_stage = {r.stage: r for r in rejects}
    assert "invalid_json" in by_stage["input"].reason_codes
    assert "missing_title" in by_stage["normalization"].reason_codes
    assert by_stage["normalization"].legacy_id == "art_no_title"
    assert all(r.run_id == run.run_id for r in rejects)
    assert all(":" in r.legacy_locator for r in rejects)  # shard:line形式


def test_legacy_annotation_isolation_and_provenance(dataset: Path, tmp_path: Path) -> None:
    stores, _e, _inv, _run = run_backfill(dataset, tmp_path / "bank")
    anns = {dict(a.annotations).get("legacy_article_id"): a
            for a in stores.news_bank.iter_annotations()}
    ann = anns["art_ok1"]
    fields = dict(ann.annotations)
    assert ann.origin == "legacy_tank"
    assert fields["not_ground_truth"] == "true"
    assert fields["importance_score"] == "0.7"  # 隔離（新Truthへ昇格しない）
    assert "2026-07-20.jsonl" in fields["legacy_shard_locator"]  # historical provenance
    assert fields["source_mapping_confidence"] == "exact_name"
    unknown = anns["art_unknown_src"]
    assert dict(unknown.annotations)["source_mapping_confidence"] == "unmatched"


def test_unknown_source_is_migration_safe_not_guessed(dataset: Path, tmp_path: Path) -> None:
    stores, _e, _inv, _run = run_backfill(dataset, tmp_path / "bank")
    docs = {d.guid: d for d in stores.normalized.iter_documents()}
    assert docs["art_unknown_src"].source_id == "legacy_unknown:mystery_example"


def test_idempotent_rerun_no_duplicates(dataset: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "bank"
    stores1, _e, inv, run1 = run_backfill(dataset, workdir)
    docs_before = len(list(stores1.normalized.iter_documents()))
    # 再実行（resume=True）: checkpoint済みのため何も処理されない
    stores2, _e2, _inv2, run2 = run_backfill(dataset, workdir)
    assert run2.records_seen == 0
    assert len(list(stores2.normalized.iter_documents())) == docs_before
    # resume=Falseの完全再実行でもcanonicalは二重化しない（決定論的ID＋冪等add）
    stores3, _e3, _inv3, run3 = run_backfill(dataset, workdir, resume=False)
    assert run3.records_seen == 6
    assert len(list(stores3.normalized.iter_documents())) == docs_before
    assert len(list(stores3.news_bank.iter_news_items())) == docs_before
    assert len(list(stores3.articles.iter_identities())) == docs_before


def test_crash_and_resume_reaches_same_state(dataset: Path, tmp_path: Path) -> None:
    """途中crash → resume → clean一発実行と同一のcanonical状態。"""
    class Boom(Exception):
        pass

    crash_dir = tmp_path / "crash"

    def bomb(index: int) -> None:
        if index == 3:
            raise Boom()

    stores = open_stores(crash_dir)
    engine = BackfillEngine(dataset, stores, HISTORICAL_V1, CATALOG, chunk_size=2)
    inv = build_inventory(dataset)
    with pytest.raises(Boom):
        engine.run(inv, fail_injector=bomb)
    crashed = stores.news_bank.iter_runs()[-1]
    assert crashed.status == "crashed" and crashed.checkpoint == 3

    # resume（新プロセス相当: store再オープン＋preload）
    stores_r, _e, _inv, run2 = run_backfill(dataset, crash_dir)
    assert run2.records_seen == 3  # 残り3件のみ（重複生成なし）
    clean_stores, _e2, _inv2, _run = run_backfill(dataset, tmp_path / "clean")
    assert (sorted(d.source_document_id for d in stores_r.normalized.iter_documents())
            == sorted(d.source_document_id for d in clean_stores.normalized.iter_documents()))
    assert (sorted(n.news_item_id for n in stores_r.news_bank.iter_news_items())
            == sorted(n.news_item_id for n in clean_stores.news_bank.iter_news_items()))


def test_no_fetch_attempts_created(dataset: Path, tmp_path: Path) -> None:
    """missing live FetchAttempt ≠ fabricated FetchAttempt。"""
    workdir = tmp_path / "bank"
    run_backfill(dataset, workdir)
    assert not (workdir / "raw").exists() or not any(
        (workdir / "raw").rglob("fetch_attempts.jsonl"))
