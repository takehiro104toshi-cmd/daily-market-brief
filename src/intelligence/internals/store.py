"""Internals store（Phase 3.5 §14 / §21）。

保存するのは **aggregation manifest** と **集計行**（breadth / turnover / sector / size）。
Fact は Phase 3-A FactStore、Context は Phase 3-B ContextStore が所有する
（別のFact / Context保管を作らない）。

- canonical: JSONL append-only（`internals/manifests.jsonl` / `internals/aggregates.jsonl`）
- operational: SQLite（canonicalから再構築可能）。manifest → 入力record_id を引ける
- idempotent: manifest_id / record_id が既知なら追記しない
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

from ..core.paths import data_root
from .breadth import AggregationManifest

MANIFEST_FILE = "manifests.jsonl"
AGGREGATE_FILE = "aggregates.jsonl"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS manifests (
  manifest_id TEXT PRIMARY KEY, session_date TEXT, calculation TEXT,
  universe_version TEXT, universe_hash TEXT, input_count INTEGER,
  input_set_hash TEXT, master_applied_backwards INTEGER);
CREATE INDEX IF NOT EXISTS ix_manifest_session ON manifests(session_date);
CREATE TABLE IF NOT EXISTS manifest_inputs (manifest_id TEXT, record_id TEXT);
CREATE INDEX IF NOT EXISTS ix_mi_manifest ON manifest_inputs(manifest_id);
CREATE TABLE IF NOT EXISTS aggregates (
  record_id TEXT PRIMARY KEY, kind TEXT, session_date TEXT, subject TEXT,
  manifest_id TEXT, payload_json TEXT);
CREATE INDEX IF NOT EXISTS ix_agg_kind_session ON aggregates(kind, session_date);
"""


def internals_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / "internals"


class InternalsStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = internals_root(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / MANIFEST_FILE
        self.aggregate_path = self.root / AGGREGATE_FILE
        self.db_path = self.root / "index" / "internals.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._known: Dict[str, set] = {}

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- canonical

    def _ids(self, path: Path, key: str) -> set:
        cache_key = str(path)
        if cache_key in self._known:
            return self._known[cache_key]
        ids = set()
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ids.add(json.loads(line).get(key, ""))
                    except json.JSONDecodeError:
                        continue
        self._known[cache_key] = ids
        return ids

    @staticmethod
    def _iter(path: Path) -> Iterator[Dict]:
        if not path.exists():
            return
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def add_manifests(self, manifests: Sequence[AggregationManifest]) -> int:
        known = self._ids(self.manifest_path, "manifest_id")
        added = 0
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            for manifest in manifests:
                if manifest.manifest_id in known:
                    continue
                data = manifest.as_dict()
                handle.write(json.dumps(data, ensure_ascii=False) + "\n")
                known.add(manifest.manifest_id)
                self._index_manifest(data)
                added += 1
        self._conn.commit()
        return added

    def add_aggregates(self, rows: Sequence[Dict]) -> int:
        known = self._ids(self.aggregate_path, "record_id")
        added = 0
        with self.aggregate_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                rid = str(row.get("record_id", ""))
                if not rid or rid in known:
                    continue
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                known.add(rid)
                self._index_aggregate(row)
                added += 1
        self._conn.commit()
        return added

    def iter_manifests(self) -> Iterator[Dict]:
        return self._iter(self.manifest_path)

    def iter_aggregates(self) -> Iterator[Dict]:
        return self._iter(self.aggregate_path)

    # ------------------------------------------------------------- index

    def _index_manifest(self, data: Dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO manifests (manifest_id, session_date, calculation, "
            "universe_version, universe_hash, input_count, input_set_hash, "
            "master_applied_backwards) VALUES (?,?,?,?,?,?,?,?)",
            (data["manifest_id"], data.get("session_date", ""),
             f"{data.get('calculation_name', '')}:{data.get('calculation_version', '')}",
             f"{data.get('universe_id', '')}:{data.get('universe_version', '')}",
             data.get("universe_hash", ""), int(data.get("input_count", 0) or 0),
             data.get("input_set_hash", ""),
             1 if data.get("master_applied_backwards") else 0))
        self._conn.execute("DELETE FROM manifest_inputs WHERE manifest_id=?",
                           (data["manifest_id"],))
        self._conn.executemany(
            "INSERT INTO manifest_inputs (manifest_id, record_id) VALUES (?,?)",
            [(data["manifest_id"], rid) for rid in data.get("input_record_ids", [])])

    def _index_aggregate(self, row: Dict) -> None:
        subject = str(row.get("sector_code") or row.get("group") or row.get("universe_id") or "")
        self._conn.execute(
            "INSERT OR REPLACE INTO aggregates (record_id, kind, session_date, subject, "
            "manifest_id, payload_json) VALUES (?,?,?,?,?,?)",
            (row["record_id"], row.get("kind", ""), row.get("session_date", ""), subject,
             row.get("manifest_id", ""), json.dumps(row, ensure_ascii=False, default=str)))

    def rebuild_index(self) -> Dict[str, int]:
        for table in ("manifests", "manifest_inputs", "aggregates"):
            self._conn.execute(f"DELETE FROM {table}")
        counts = {"manifests": 0, "aggregates": 0}
        for data in self.iter_manifests():
            self._index_manifest(data)
            counts["manifests"] += 1
        for row in self.iter_aggregates():
            self._index_aggregate(row)
            counts["aggregates"] += 1
        self._conn.commit()
        return counts

    # ------------------------------------------------------------- query

    def _rows(self, sql: str, params: Sequence = ()) -> List[sqlite3.Row]:
        return list(self._conn.execute(sql, params))

    def count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]

    def manifest(self, manifest_id: str) -> Optional[sqlite3.Row]:
        rows = self._rows("SELECT * FROM manifests WHERE manifest_id=?", (manifest_id,))
        return rows[0] if rows else None

    def manifest_inputs(self, manifest_id: str) -> List[str]:
        return [r["record_id"] for r in self._rows(
            "SELECT record_id FROM manifest_inputs WHERE manifest_id=? ORDER BY record_id",
            (manifest_id,))]

    def manifests_for_session(self, session_date: str) -> List[sqlite3.Row]:
        return self._rows("SELECT * FROM manifests WHERE session_date=? ORDER BY calculation",
                          (session_date,))

    def aggregates_for(self, kind: str, session_date: str = "") -> List[Dict]:
        sql = "SELECT payload_json FROM aggregates WHERE kind=?"
        params: List = [kind]
        if session_date:
            sql += " AND session_date=?"
            params.append(session_date)
        sql += " ORDER BY session_date, subject"
        return [json.loads(r["payload_json"]) for r in self._rows(sql, params)]

    def sessions(self, kind: str) -> List[str]:
        return [r["session_date"] for r in self._rows(
            "SELECT DISTINCT session_date FROM aggregates WHERE kind=? ORDER BY session_date",
            (kind,))]

    def sqlite_bytes(self) -> int:
        return self.db_path.stat().st_size if self.db_path.exists() else 0
