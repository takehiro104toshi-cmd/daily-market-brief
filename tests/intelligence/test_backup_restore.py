"""P2-F PART I: backup / restore drill（manifest→破損検知→restore→rebuild→同値）。

注意: 本テストはephemeral環境での**仕組みのvalidation**であり、
「恒久backup済み」の主張ではない（恒久性は永続媒体での運用が担う）。
"""
from __future__ import annotations

import shutil

from src.intelligence.core.backup import (
    build_backup_manifest,
    verify_against_manifest,
    write_backup_manifest,
)
from src.intelligence.databank.query import NewsQuery
from src.intelligence.databank.sqlite_index import SqliteNewsIndex

from .enrichment_fixtures import NOW, make_engine, make_item

HEADLINES = ["Nvidia earnings beat estimates as AI chip demand surges",
             "Fed holds rates steady as Powell cites inflation risks"]


def _build_root(tmp_path):
    """News Bank縮小版のdata root（enrichment込み）を構築しクエリ結果を返す。"""
    root = tmp_path / "data_root"
    bank = root / "databank"
    engine = make_engine(bank / "news")  # enrichment store: bank/news/enrichment
    items = [make_item(h) for h in HEADLINES]
    for i in items:
        engine.enrich_item(i, now=NOW)
    index = SqliteNewsIndex(bank / "index" / "news.sqlite3")
    index.index_news_items(items)
    index.index_classifications(list(engine.store.iter_classifications()))
    result = [n.news_item_id for n in index.search_news(NewsQuery(theme="ai"))]
    index.close()
    return root, items, result


class TestBackupRestoreDrill:
    def test_full_drill(self, tmp_path):
        root, items, baseline = _build_root(tmp_path)
        assert baseline  # クエリが意味を持つ状態

        # 1. manifest作成
        manifest_path = write_backup_manifest(root)
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["file_count"] > 0 and manifest["schema_version"]

        # 2. backupコピー
        backup_copy = tmp_path / "backup_copy"
        shutil.copytree(root, backup_copy)
        missing, changed, _extra = verify_against_manifest(backup_copy, manifest)
        assert (missing, changed) == ([], [])  # コピー健全

        # 3. 原本を破損（canonical改変＋index喪失）
        cls_path = root / "databank" / "news" / "enrichment" / "classifications.jsonl"
        cls_path.write_bytes(cls_path.read_bytes()[: len(cls_path.read_bytes()) // 2])
        (root / "databank" / "index" / "news.sqlite3").unlink()
        missing, changed, _extra = verify_against_manifest(root, manifest)
        assert missing and changed  # 破損・欠落が機械検知される

        # 4. restore（backupコピー→原本位置）
        restore_root = tmp_path / "restored"
        shutil.copytree(backup_copy, restore_root)
        missing, changed, _extra = verify_against_manifest(restore_root, manifest)
        assert (missing, changed) == ([], [])

        # 5. SQLite rebuild（indexは導出物——canonicalのみから再構築）
        from src.intelligence.enrichment.store import JsonlEnrichmentStore
        restored_bank = restore_root / "databank"
        enrichment = JsonlEnrichmentStore(restored_bank / "news" / "enrichment")
        index = SqliteNewsIndex(restored_bank / "index" / "news_rebuilt.sqlite3")
        index.index_news_items(items)
        index.index_classifications(list(enrichment.iter_classifications()))

        # 6. query equivalence（restore後に同一クエリ結果）
        restored = [n.news_item_id for n in index.search_news(NewsQuery(theme="ai"))]
        assert restored == baseline
        index.close()

    def test_manifest_detects_single_byte_corruption(self, tmp_path):
        root, _items, _baseline = _build_root(tmp_path)
        manifest = build_backup_manifest(root)
        target = root / "databank" / "news" / "enrichment" / "classifications.jsonl"
        data = bytearray(target.read_bytes())
        data[5] ^= 0xFF
        target.write_bytes(bytes(data))  # サイズ同一・内容1byte差
        _missing, changed, _extra = verify_against_manifest(root, manifest)
        assert any("classifications.jsonl" in c for c in changed)  # sha256が検知
