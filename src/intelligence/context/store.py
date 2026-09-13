"""Context store（Phase 3-B STEP 23/27/28）。

既存Data Bank原則を維持:
- canonical: **JSONL append-only**（履歴を上書きしない）
- operational: **SQLite（再構築可能）**
- **incremental / idempotent**: `context_id` が既知なら追記しない

**Fact storeを複製しない**（STEP 27）——保存するのはContext成果物と
支持Fact IDへの参照だけで、Fact本体は複製しない。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

from ..core.paths import data_root
from .model import ContextItem, ContextStatus, PriorityTier

CANONICAL_FILE = "contexts.jsonl"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contexts (
  context_id TEXT PRIMARY KEY, context_type TEXT,
  subject_type TEXT, subject_id TEXT, display_name TEXT,
  related_subject_ids TEXT, session_date TEXT, known_at TEXT, session_count INTEGER,
  direction TEXT, relationship TEXT, magnitude TEXT, magnitude_unit TEXT,
  rule TEXT, status TEXT, quality TEXT, priority_tier TEXT,
  priority_rule_version TEXT, priority_components TEXT,
  revision_of TEXT, created_at TEXT, schema_version TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS ix_ctx_session ON contexts(session_date);
CREATE INDEX IF NOT EXISTS ix_ctx_type ON contexts(context_type, session_date);
CREATE INDEX IF NOT EXISTS ix_ctx_subject ON contexts(subject_id, session_date);
CREATE INDEX IF NOT EXISTS ix_ctx_priority ON contexts(priority_tier, session_date);

CREATE TABLE IF NOT EXISTS context_facts (
  context_id TEXT, fact_id TEXT);
CREATE INDEX IF NOT EXISTS ix_cf_context ON context_facts(context_id);
CREATE INDEX IF NOT EXISTS ix_cf_fact ON context_facts(fact_id);
"""

_COLUMNS = (
    "context_id", "context_type", "subject_type", "subject_id", "display_name",
    "related_subject_ids", "session_date", "known_at", "session_count",
    "direction", "relationship", "magnitude", "magnitude_unit", "rule",
    "status", "quality", "priority_tier", "priority_rule_version",
    "priority_components", "revision_of", "created_at", "schema_version", "note",
)


def context_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / "context"


def _row_of(data: Dict) -> tuple:
    return (
        data["context_id"], data["context_type"], data["subject_type"],
        data["subject_id"], data.get("display_name", ""),
        json.dumps(data.get("related_subject_ids", []), ensure_ascii=False),
        data["session_date"], data.get("known_at", ""),
        int(data.get("session_count", 0) or 0), data.get("direction", ""),
        data.get("relationship", ""), data.get("magnitude", ""),
        data.get("magnitude_unit", ""), data.get("rule", ""), data["status"],
        data.get("quality", ""), data.get("priority_tier", ""),
        data.get("priority_rule_version", ""),
        json.dumps(data.get("priority_components", {}), ensure_ascii=False),
        data.get("revision_of", ""), data.get("created_at", ""),
        data.get("schema_version", ""), data.get("note", ""),
    )


class ContextStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = context_root(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.canonical_path = self.root / CANONICAL_FILE
        self.db_path = self.root / "index" / "context.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._known: Optional[set] = None

    def close(self) -> None:
        self._conn.close()

    def _known_ids(self) -> set:
        if self._known is None:
            ids = set()
            if self.canonical_path.exists():
                with self.canonical_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if line:
                            try:
                                ids.add(json.loads(line)["context_id"])
                            except (json.JSONDecodeError, KeyError):
                                continue
            self._known = ids
        return self._known

    def add(self, items: Sequence[ContextItem]) -> Dict[str, int]:
        """Contextを追記（冪等）。同一identityで内容が変われば旧をSUPERSEDEDにする。"""
        known = self._known_ids()
        added = skipped = superseded = 0
        rows: List[tuple] = []
        with self.canonical_path.open("a", encoding="utf-8") as handle:
            for item in items:
                if item.context_id in known:
                    skipped += 1
                    continue
                previous = self._current_for(item)
                data = item.as_dict()
                if previous is not None:
                    data["revision_of"] = previous["context_id"]
                    self._conn.execute(
                        "UPDATE contexts SET status=? WHERE context_id=?",
                        (ContextStatus.STALE.value, previous["context_id"]))
                    superseded += 1
                handle.write(json.dumps(data, ensure_ascii=False) + "\n")
                known.add(item.context_id)
                rows.append(_row_of(data))
                self._conn.executemany(
                    "INSERT INTO context_facts (context_id, fact_id) VALUES (?,?)",
                    [(item.context_id, f) for f in item.supporting_fact_ids])
                added += 1
        if rows:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO contexts ({','.join(_COLUMNS)}) "
                f"VALUES ({','.join('?' * len(_COLUMNS))})", rows)
        self._conn.commit()
        return {"added": added, "skipped": skipped, "superseded": superseded}

    def _current_for(self, item: ContextItem) -> Optional[sqlite3.Row]:
        rows = list(self._conn.execute(
            "SELECT context_id FROM contexts WHERE context_type=? AND subject_id=? "
            "AND session_date=? AND status<>? ORDER BY created_at DESC LIMIT 1",
            (item.context_type, item.subject.subject_id, item.time.session_date,
             ContextStatus.STALE.value)))
        return rows[0] if rows else None

    def iter_canonical(self) -> Iterator[Dict]:
        if not self.canonical_path.exists():
            return
        with self.canonical_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def rebuild_index(self) -> int:
        self._conn.execute("DELETE FROM contexts")
        self._conn.execute("DELETE FROM context_facts")
        rows, links, stale = [], [], []
        for data in self.iter_canonical():
            rows.append(_row_of(data))
            links += [(data["context_id"], f)
                      for f in data.get("supporting_fact_ids", [])]
            if data.get("revision_of"):
                stale.append(data["revision_of"])
        if rows:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO contexts ({','.join(_COLUMNS)}) "
                f"VALUES ({','.join('?' * len(_COLUMNS))})", rows)
        if links:
            self._conn.executemany(
                "INSERT INTO context_facts (context_id, fact_id) VALUES (?,?)", links)
        for old in stale:
            self._conn.execute("UPDATE contexts SET status=? WHERE context_id=?",
                               (ContextStatus.STALE.value, old))
        self._conn.commit()
        return len(rows)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) c FROM contexts").fetchone()["c"]

    # ------------------------------------------------------------- query（STEP 28）

    def _rows(self, sql: str, params: Sequence = ()) -> List[sqlite3.Row]:
        return list(self._conn.execute(sql, params))

    def contexts_for_session(self, session_date: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM contexts WHERE session_date=? AND status<>? "
            "ORDER BY priority_tier, context_type, subject_id",
            (session_date, ContextStatus.STALE.value))

    def latest_context_by_type(self, context_type: str,
                               subject_id: str = "") -> Optional[sqlite3.Row]:
        sql = ("SELECT * FROM contexts WHERE context_type=? AND status<>?")
        params: List = [context_type, ContextStatus.STALE.value]
        if subject_id:
            sql += " AND subject_id=?"
            params.append(subject_id)
        sql += " ORDER BY session_date DESC LIMIT 1"
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def contexts_by_subject(self, subject_id: str, limit: int = 200) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM contexts WHERE subject_id=? AND status<>? "
            "ORDER BY session_date DESC LIMIT ?",
            (subject_id, ContextStatus.STALE.value, limit))

    def contexts_by_fact(self, fact_id: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT c.* FROM contexts c JOIN context_facts f "
            "ON c.context_id=f.context_id WHERE f.fact_id=? "
            "ORDER BY c.session_date", (fact_id,))

    def high_priority_contexts(self, session_date: str = "") -> List[sqlite3.Row]:
        sql = ("SELECT * FROM contexts WHERE priority_tier=? AND status<>?")
        params: List = [PriorityTier.PRIMARY.value, ContextStatus.STALE.value]
        if session_date:
            sql += " AND session_date=?"
            params.append(session_date)
        sql += " ORDER BY session_date DESC, context_type"
        return self._rows(sql, params)

    def divergences(self, session_date: str = "") -> List[sqlite3.Row]:
        sql = ("SELECT * FROM contexts WHERE relationship=? AND status<>?")
        params: List = ["DIVERGING", ContextStatus.STALE.value]
        if session_date:
            sql += " AND session_date=?"
            params.append(session_date)
        sql += " ORDER BY session_date DESC"
        return self._rows(sql, params)

    def event_contexts(self, session_date: str = "") -> List[sqlite3.Row]:
        sql = ("SELECT * FROM contexts WHERE context_type=? AND status<>?")
        params: List = ["event_proximity", ContextStatus.STALE.value]
        if session_date:
            sql += " AND session_date=?"
            params.append(session_date)
        sql += " ORDER BY magnitude"
        return self._rows(sql, params)

    def supporting_facts(self, context_id: str) -> List[str]:
        return [r["fact_id"] for r in self._rows(
            "SELECT fact_id FROM context_facts WHERE context_id=?", (context_id,))]
