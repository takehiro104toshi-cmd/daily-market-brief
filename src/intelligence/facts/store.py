"""Fact store（Phase 3-A STEP 17/18/26）。

既存Data Bank原則を維持:
- canonical: **JSONL append-only**（監査可能・過去Factを消さない）
- operational: **SQLite（再構築可能）**
- 大量データをGitへcommitしない（`INTELLIGENCE_DATA_ROOT` 配下）

**deterministic / incremental / idempotent**:
- `fact_id` が既知なら追記しない（再実行で増えない）
- 同一 subject × fact_type × primary_date で**値が変わった**Factは
  `revision_of` を付けて追記し、旧Factは `SUPERSEDED` として索引を更新する
  （canonicalからは消さない）
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from ..core.paths import data_root
from .model import ConflictState, Fact, FactStatus

CANONICAL_FILE = "facts.jsonl"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  fact_id TEXT PRIMARY KEY,
  fact_type TEXT, identity_discriminator TEXT,
  subject_type TEXT, subject_id TEXT, display_name TEXT,
  value TEXT, text_value TEXT, unit TEXT, currency TEXT,
  primary_date TEXT, date_role TEXT, as_of TEXT, known_at TEXT,
  period_start TEXT, period_end TEXT, session_count INTEGER,
  calculation_method TEXT, calculation_inputs TEXT,
  status TEXT, conflict_state TEXT, conflicting_fact_ids TEXT,
  source_ids TEXT, qa_decision TEXT, revision_of TEXT,
  created_at TEXT, schema_version TEXT, evidence_json TEXT);
CREATE INDEX IF NOT EXISTS ix_fact_subject ON facts(subject_id, fact_type, primary_date);
CREATE INDEX IF NOT EXISTS ix_fact_identity
  ON facts(subject_id, fact_type, primary_date, identity_discriminator);
CREATE INDEX IF NOT EXISTS ix_fact_date ON facts(primary_date);
CREATE INDEX IF NOT EXISTS ix_fact_type ON facts(fact_type);
CREATE INDEX IF NOT EXISTS ix_fact_status ON facts(status);
CREATE INDEX IF NOT EXISTS ix_fact_conflict ON facts(conflict_state);

CREATE TABLE IF NOT EXISTS fact_evidence (
  fact_id TEXT, kind TEXT, ref_id TEXT, locator TEXT, qa_decision TEXT);
CREATE INDEX IF NOT EXISTS ix_fev_fact ON fact_evidence(fact_id);
CREATE INDEX IF NOT EXISTS ix_fev_ref ON fact_evidence(ref_id);

CREATE TABLE IF NOT EXISTS fact_inputs (
  fact_id TEXT, input_id TEXT);
CREATE INDEX IF NOT EXISTS ix_fin_fact ON fact_inputs(fact_id);
CREATE INDEX IF NOT EXISTS ix_fin_input ON fact_inputs(input_id);
"""

_COLUMNS = (
    "fact_id", "fact_type", "identity_discriminator", "subject_type",
    "subject_id", "display_name",
    "value", "text_value", "unit", "currency", "primary_date", "date_role",
    "as_of", "known_at", "period_start", "period_end", "session_count",
    "calculation_method", "calculation_inputs", "status", "conflict_state",
    "conflicting_fact_ids", "source_ids", "qa_decision", "revision_of",
    "created_at", "schema_version", "evidence_json",
)


def fact_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / "facts"


def _row_of(data: Dict) -> Tuple:
    return (
        data["fact_id"], data["fact_type"],
        data.get("identity_discriminator", ""),
        data["subject_type"], data["subject_id"],
        data.get("display_name", ""), data.get("value", ""), data.get("text_value", ""),
        data.get("unit", ""), data.get("currency", ""), data["primary_date"],
        data["date_role"], data.get("as_of", ""), data.get("known_at", ""),
        data.get("period_start", ""), data.get("period_end", ""),
        int(data.get("session_count", 0) or 0),
        data.get("calculation_method", ""),
        json.dumps(data.get("calculation_inputs", []), ensure_ascii=False),
        data["status"], data.get("conflict_state", ""),
        json.dumps(data.get("conflicting_fact_ids", []), ensure_ascii=False),
        json.dumps(data.get("source_ids", []), ensure_ascii=False),
        data.get("qa_decision", ""), data.get("revision_of", ""),
        data.get("created_at", ""), data.get("schema_version", ""),
        json.dumps(data.get("evidence", []), ensure_ascii=False),
    )


class FactStore:
    """canonical JSONL ＋ 再構築可能なSQLite索引。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = fact_root(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.canonical_path = self.root / CANONICAL_FILE
        self.db_path = self.root / "index" / "facts.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._known: Optional[set] = None

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- canonical

    def _known_ids(self) -> set:
        if self._known is None:
            ids = set()
            if self.canonical_path.exists():
                with self.canonical_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if line:
                            try:
                                ids.add(json.loads(line)["fact_id"])
                            except (json.JSONDecodeError, KeyError):
                                continue
            self._known = ids
        return self._known

    def add(self, facts: Sequence[Fact]) -> Dict[str, int]:
        """Factを追記する（**冪等**・増分）。戻り値: added / skipped / superseded。"""
        known = self._known_ids()
        added = skipped = superseded = 0
        rows: List[Tuple] = []
        with self.canonical_path.open("a", encoding="utf-8") as handle:
            for fact in facts:
                if fact.fact_id in known:
                    skipped += 1
                    continue
                # 同一 subject × type × date で値違いの既存Factは SUPERSEDED にする
                previous = self._current_for(fact)
                data = fact.as_dict()
                if previous is not None:
                    data["revision_of"] = previous["fact_id"]
                    self._conn.execute(
                        "UPDATE facts SET status=?, conflict_state=? WHERE fact_id=?",
                        (FactStatus.SUPERSEDED.value, ConflictState.SUPERSEDED.value,
                         previous["fact_id"]))
                    superseded += 1
                handle.write(json.dumps(data, ensure_ascii=False) + "\n")
                known.add(fact.fact_id)
                rows.append(_row_of(data))
                self._index_relations(fact)
                added += 1
        if rows:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO facts ({','.join(_COLUMNS)}) "
                f"VALUES ({','.join('?' * len(_COLUMNS))})", rows)
        self._conn.commit()
        return {"added": added, "skipped": skipped, "superseded": superseded}

    def _current_for(self, fact: Fact) -> Optional[sqlite3.Row]:
        # revisionは **discriminatorまで一致** したときだけ（同じ開示日の別metric・
        # 別会計期間を互いにsupersededにしない）
        rows = list(self._conn.execute(
            "SELECT fact_id FROM facts WHERE subject_id=? AND fact_type=? "
            "AND primary_date=? AND identity_discriminator=? AND status<>? "
            "ORDER BY created_at DESC LIMIT 1",
            (fact.subject.subject_id, fact.fact_type, fact.time.primary_date,
             fact.identity_discriminator, FactStatus.SUPERSEDED.value)))
        return rows[0] if rows else None

    def _index_relations(self, fact: Fact) -> None:
        self._conn.executemany(
            "INSERT INTO fact_evidence (fact_id, kind, ref_id, locator, qa_decision) "
            "VALUES (?,?,?,?,?)",
            [(fact.fact_id, e.kind.value, e.ref_id, e.locator, e.qa_decision)
             for e in fact.evidence])
        self._conn.executemany(
            "INSERT INTO fact_inputs (fact_id, input_id) VALUES (?,?)",
            [(fact.fact_id, i) for i in fact.input_ids])

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
        """canonicalのみからSQLiteを作り直す（operationalは常に再構築可能）。"""
        self._conn.execute("DELETE FROM facts")
        self._conn.execute("DELETE FROM fact_evidence")
        self._conn.execute("DELETE FROM fact_inputs")
        rows, evidence_rows, input_rows = [], [], []
        superseded: Dict[Tuple[str, str, str], str] = {}
        records = list(self.iter_canonical())
        for data in records:
            rows.append(_row_of(data))
            for ev in data.get("evidence", []):
                evidence_rows.append((data["fact_id"], ev.get("kind", ""),
                                      ev.get("ref_id", ""), ev.get("locator", ""),
                                      ev.get("qa_decision", "")))
            for input_id in data.get("calculation_inputs", []):
                input_rows.append((data["fact_id"], input_id))
            if data.get("revision_of"):
                superseded[(data["subject_id"], data["fact_type"],
                            data["primary_date"],
                            data.get("identity_discriminator", ""))] = data["revision_of"]
        if rows:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO facts ({','.join(_COLUMNS)}) "
                f"VALUES ({','.join('?' * len(_COLUMNS))})", rows)
        if evidence_rows:
            self._conn.executemany(
                "INSERT INTO fact_evidence (fact_id, kind, ref_id, locator, qa_decision) "
                "VALUES (?,?,?,?,?)", evidence_rows)
        if input_rows:
            self._conn.executemany(
                "INSERT INTO fact_inputs (fact_id, input_id) VALUES (?,?)", input_rows)
        # revision_ofが指す旧Factを SUPERSEDED へ戻す（canonicalの事実から再導出）
        for old_id in superseded.values():
            self._conn.execute(
                "UPDATE facts SET status=?, conflict_state=? WHERE fact_id=?",
                (FactStatus.SUPERSEDED.value, ConflictState.SUPERSEDED.value, old_id))
        self._conn.commit()
        return len(rows)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) c FROM facts").fetchone()["c"]

    # ------------------------------------------------------------- query（STEP 18）

    def _rows(self, sql: str, params: Sequence = ()) -> List[sqlite3.Row]:
        return list(self._conn.execute(sql, params))

    def latest_fact(self, subject_id: str, fact_type: str) -> Optional[sqlite3.Row]:
        rows = self._rows(
            "SELECT * FROM facts WHERE subject_id=? AND fact_type=? AND status<>? "
            "ORDER BY primary_date DESC LIMIT 1",
            (subject_id, fact_type, FactStatus.SUPERSEDED.value))
        return rows[0] if rows else None

    def facts_on(self, primary_date: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM facts WHERE primary_date=? AND status<>? "
            "ORDER BY subject_id, fact_type",
            (primary_date, FactStatus.SUPERSEDED.value))

    def facts_between(self, start: str, end: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM facts WHERE primary_date>=? AND primary_date<=? "
            "AND status<>? ORDER BY primary_date, subject_id, fact_type",
            (start, end, FactStatus.SUPERSEDED.value))

    def facts_for_subject(self, subject_id: str, limit: int = 500) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM facts WHERE subject_id=? AND status<>? "
            "ORDER BY primary_date DESC LIMIT ?",
            (subject_id, FactStatus.SUPERSEDED.value, limit))

    def facts_for_series(self, series_id: str, limit: int = 500) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM facts WHERE subject_type='series' AND subject_id=? "
            "AND status<>? ORDER BY primary_date DESC LIMIT ?",
            (series_id, FactStatus.SUPERSEDED.value, limit))

    def facts_by_evidence(self, ref_id: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT f.* FROM facts f JOIN fact_evidence e ON f.fact_id=e.fact_id "
            "WHERE e.ref_id=? ORDER BY f.primary_date", (ref_id,))

    def derived_inputs(self, fact_id: str) -> List[str]:
        return [r["input_id"] for r in self._rows(
            "SELECT input_id FROM fact_inputs WHERE fact_id=?", (fact_id,))]

    def conflicted_facts(self) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM facts WHERE conflict_state=? ORDER BY primary_date",
            (ConflictState.CONFLICT.value,))

    def evidence_refs(self, fact_id: str) -> List[sqlite3.Row]:
        return self._rows("SELECT * FROM fact_evidence WHERE fact_id=?", (fact_id,))
