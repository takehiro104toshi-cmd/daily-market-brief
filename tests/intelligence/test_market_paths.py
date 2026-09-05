"""PART A: data root解決・backup manifest（永続化基盤）のテスト。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.intelligence.core.backup import (
    build_backup_manifest,
    verify_against_manifest,
    write_backup_manifest,
)
from src.intelligence.core.paths import (
    DATA_ROOT_ENV,
    DEFAULT_DATA_ROOT,
    data_root,
    market_bank_root,
)


class TestDataRoot:
    def test_env_override_wins(self, tmp_path):
        root = data_root(env={DATA_ROOT_ENV: "/mnt/persist/intel"},
                         config_path=tmp_path / "none.yaml")
        assert root == Path("/mnt/persist/intel")

    def test_config_yaml_value(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("vnext:\n  data_root: custom/place\n", encoding="utf-8")
        assert data_root(env={}, config_path=cfg) == Path("custom/place")

    def test_default_without_env_or_config(self, tmp_path):
        assert data_root(env={}, config_path=tmp_path / "none.yaml") == DEFAULT_DATA_ROOT

    def test_repo_config_yaml_has_vnext_key(self):
        # CLAUDE.mdルール8: config値はconfig.yamlへ。実ファイルの結線を検証
        assert data_root(env={}) == Path("data/vnext")

    def test_broken_config_falls_back(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(":::not yaml [", encoding="utf-8")
        assert data_root(env={}, config_path=cfg) == DEFAULT_DATA_ROOT

    def test_market_bank_root_layout(self):
        assert market_bank_root(Path("/x")) == Path("/x/databank/market")


class TestBackupManifest:
    def _populate(self, root: Path):
        (root / "normalized").mkdir(parents=True)
        (root / "normalized" / "observations.jsonl").write_text('{"a":1}\n', encoding="utf-8")
        (root / "index").mkdir()
        (root / "index" / "market.sqlite3").write_bytes(b"sqlite-bytes")

    def test_manifest_inventory_and_checksums(self, tmp_path):
        self._populate(tmp_path)
        manifest = build_backup_manifest(tmp_path, now=datetime(2026, 8, 30, tzinfo=timezone.utc))
        paths = {f["path"] for f in manifest["files"]}
        assert paths == {"normalized/observations.jsonl", "index/market.sqlite3"}
        assert manifest["file_count"] == 2
        assert all(len(f["sha256"]) == 64 for f in manifest["files"])
        assert manifest["schema_version"]  # スキーマ版を必ず記録

    def test_write_and_verify_clean(self, tmp_path):
        self._populate(tmp_path)
        path = write_backup_manifest(tmp_path)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        missing, changed, extra = verify_against_manifest(tmp_path, manifest)
        assert (missing, changed, extra) == ([], [], [])
        # manifest自身（backup/配下）はinventory対象外＝自己参照しない
        assert all(not f["path"].startswith("backup/") for f in manifest["files"])

    def test_verify_detects_corruption_and_loss(self, tmp_path):
        self._populate(tmp_path)
        manifest = build_backup_manifest(tmp_path)
        (tmp_path / "index" / "market.sqlite3").write_bytes(b"CORRUPTED!!!")
        (tmp_path / "normalized" / "observations.jsonl").unlink()
        missing, changed, _extra = verify_against_manifest(tmp_path, manifest)
        assert missing == ["normalized/observations.jsonl"]
        assert changed == ["index/market.sqlite3"]
