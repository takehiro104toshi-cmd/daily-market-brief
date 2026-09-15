"""PART A gate: 別プロセス再オープンでの永続化検証（restart相当）のテスト。"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from src.intelligence.core.paths import market_bank_root
from src.intelligence.evidence_qa.policy import HISTORICAL_V1
from src.intelligence.market.backfill import MarketBackfillEngine
from src.intelligence.market.store import MarketBankStore

from .market_fixtures import NIKKEI_CSV, RETRIEVED, catalog, stub_provider

NIKKEI = "index:nikkei225.close.closing.tokyo"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_bank(data_root: Path) -> dict:
    """親プロセス側: bankを構築しlatestを返す。"""
    store = MarketBankStore(market_bank_root(data_root))
    engine = MarketBackfillEngine(
        store, catalog(), stub_provider({"s=^nkx": (200, NIKKEI_CSV)}), HISTORICAL_V1)
    engine.run(start=date(2026, 8, 1), end=date(2026, 8, 29), now=RETRIEVED,
               series_ids=(NIKKEI,))
    row = store.index.latest_trading_session(NIKKEI)
    latest = {"observation_id": row["observation_id"], "trading_date": row["trading_date"],
              "value": row["value"], "source_id": row["source_id"]}
    total = sum(1 for _ in store.normalized.iter_observations())
    store.close()
    return {"latest": latest, "observations": total}


class TestFreshProcessReopen:
    def test_separate_process_rebuilds_same_latest(self, tmp_path):
        parent = _build_bank(tmp_path)
        proc = subprocess.run(
            [sys.executable, "-m", "src.intelligence.market.persistence_check",
             "--data-root", str(tmp_path), "--series", NIKKEI],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)
        assert proc.returncode == 0, proc.stderr
        child = json.loads(proc.stdout.strip().splitlines()[-1])
        # メモリを共有しない別プロセスがcanonicalだけから同一のlatestへ到達する
        assert child["latest"][NIKKEI] == parent["latest"]
        assert child["canonical_observations"] == parent["observations"]
        assert child["index_rebuilt_observations"] == parent["observations"]
        assert child["recovered_lines"] == 0

    def test_env_data_root_respected_in_fresh_process(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, "-c",
             "from src.intelligence.core.paths import data_root; print(data_root())"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
            env={"INTELLIGENCE_DATA_ROOT": str(tmp_path / "persist"), "PATH": "/usr/bin:/bin"})
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == str(tmp_path / "persist")

    def test_index_deletion_recovers_from_canonical(self, tmp_path):
        parent = _build_bank(tmp_path)
        index_path = market_bank_root(tmp_path) / "index" / "market.sqlite3"
        index_path.unlink()  # indexは導出物——消えてもcanonicalから復旧できる
        store = MarketBankStore(market_bank_root(tmp_path))
        store.index.rebuild(store.normalized.iter_observations(),
                            store.qa.iter_assessments())
        row = store.index.latest_trading_session(NIKKEI)
        assert row["observation_id"] == parent["latest"]["observation_id"]
        store.close()
