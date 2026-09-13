"""Compass store（Phase 3-C §31）。

既存Data Bank原則を維持:
- canonical: **JSONL append-only**（`compass/drafts.jsonl`。上書きしない）
- operational: **SQLite（再構築可能）**（`compass/index/compass.sqlite3`）
- **idempotent**: `draft_id` が既知なら追記しない

Fact / Context の本体は複製しない——保存するのは Compass draft と、
claim → fact_id / context_id の**参照**だけ（provenance chain）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

from ..core.paths import data_root
from .model import CompassDraft

CANONICAL_FILE = "drafts.jsonl"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY, session_date TEXT, reference_session TEXT,
  package_id TEXT, plan_id TEXT, generator TEXT, verdict TEXT,
  one_liner TEXT, abstain_reason TEXT, generator_fallback TEXT,
  claim_count INTEGER, grounded_count INTEGER, rejected_count INTEGER,
  outlook_direction TEXT, outlook_confidence TEXT,
  generated_at TEXT, schema_version TEXT);
CREATE INDEX IF NOT EXISTS ix_draft_session ON drafts(session_date);
CREATE INDEX IF NOT EXISTS ix_draft_verdict ON drafts(verdict, session_date);

CREATE TABLE IF NOT EXISTS claims (
  claim_id TEXT, draft_id TEXT, claim_role TEXT, claim_type TEXT,
  grounding_status TEXT, generator TEXT, claim_order INTEGER, text TEXT,
  PRIMARY KEY (draft_id, claim_id));
CREATE INDEX IF NOT EXISTS ix_claim_draft ON claims(draft_id);
CREATE INDEX IF NOT EXISTS ix_claim_status ON claims(grounding_status);

CREATE TABLE IF NOT EXISTS claim_facts (draft_id TEXT, claim_id TEXT, fact_id TEXT);
CREATE INDEX IF NOT EXISTS ix_cfact_fact ON claim_facts(fact_id);
CREATE TABLE IF NOT EXISTS claim_contexts (draft_id TEXT, claim_id TEXT, context_id TEXT);
CREATE INDEX IF NOT EXISTS ix_cctx_context ON claim_contexts(context_id);
"""

_DRAFT_COLUMNS = (
    "draft_id", "session_date", "reference_session", "package_id", "plan_id",
    "generator", "verdict", "one_liner", "abstain_reason", "generator_fallback",
    "claim_count", "grounded_count", "rejected_count", "outlook_direction",
    "outlook_confidence", "generated_at", "schema_version",
)


def compass_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / "compass"


def _draft_row(data: Dict) -> tuple:
    claims = data.get("claims", [])
    grounded = sum(1 for c in claims
                   if c.get("grounding_status") in ("GROUNDED", "GROUNDED_WITH_WARNINGS"))
    rejected = sum(1 for c in claims if c.get("grounding_status") == "REJECTED")
    outlook = data.get("outlook") or {}
    return (
        data["draft_id"], data["session_date"], data.get("reference_session", ""),
        data.get("package_id", ""), data.get("plan_id", ""), data.get("generator", ""),
        data.get("verdict", ""), data.get("one_liner", ""), data.get("abstain_reason", ""),
        data.get("generator_fallback", ""), len(claims), grounded, rejected,
        outlook.get("direction", ""), outlook.get("confidence", ""),
        data.get("generated_at", ""), data.get("schema_version", ""),
    )


class CompassStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = compass_root(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.canonical_path = self.root / CANONICAL_FILE
        self.db_path = self.root / "index" / "compass.sqlite3"
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
            for data in self.iter_canonical():
                if "draft_id" in data:
                    ids.add(data["draft_id"])
            self._known = ids
        return self._known

    def _index(self, data: Dict) -> None:
        self._conn.execute(
            f"INSERT OR REPLACE INTO drafts ({','.join(_DRAFT_COLUMNS)}) "
            f"VALUES ({','.join('?' * len(_DRAFT_COLUMNS))})", _draft_row(data))
        did = data["draft_id"]
        self._conn.execute("DELETE FROM claims WHERE draft_id=?", (did,))
        self._conn.execute("DELETE FROM claim_facts WHERE draft_id=?", (did,))
        self._conn.execute("DELETE FROM claim_contexts WHERE draft_id=?", (did,))
        for c in data.get("claims", []):
            self._conn.execute(
                "INSERT OR REPLACE INTO claims (claim_id, draft_id, claim_role, claim_type, "
                "grounding_status, generator, claim_order, text) VALUES (?,?,?,?,?,?,?,?)",
                (c["claim_id"], did, c.get("claim_role", ""), c.get("claim_type", ""),
                 c.get("grounding_status", ""), c.get("generator", ""),
                 int(c.get("order", 0)), c.get("text", "")))
            self._conn.executemany(
                "INSERT INTO claim_facts (draft_id, claim_id, fact_id) VALUES (?,?,?)",
                [(did, c["claim_id"], f) for f in c.get("supporting_fact_ids", [])])
            self._conn.executemany(
                "INSERT INTO claim_contexts (draft_id, claim_id, context_id) VALUES (?,?,?)",
                [(did, c["claim_id"], x) for x in c.get("supporting_context_ids", [])])

    def add(self, drafts: Sequence[CompassDraft]) -> Dict[str, int]:
        """draftを追記（冪等: 既知draft_idはskip）。"""
        known = self._known_ids()
        added = skipped = 0
        with self.canonical_path.open("a", encoding="utf-8") as handle:
            for draft in drafts:
                if draft.draft_id in known:
                    skipped += 1
                    continue
                data = draft.as_dict()
                handle.write(json.dumps(data, ensure_ascii=False) + "\n")
                known.add(draft.draft_id)
                self._index(data)
                added += 1
        self._conn.commit()
        return {"added": added, "skipped": skipped}

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
        for table in ("drafts", "claims", "claim_facts", "claim_contexts"):
            self._conn.execute(f"DELETE FROM {table}")
        n = 0
        for data in self.iter_canonical():
            if "draft_id" not in data:
                continue
            self._index(data)
            n += 1
        self._conn.commit()
        return n

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) c FROM drafts").fetchone()["c"]

    # ------------------------------------------------------------------ query

    def _rows(self, sql: str, params: Sequence = ()) -> List[sqlite3.Row]:
        return list(self._conn.execute(sql, params))

    def drafts_for_session(self, session_date: str) -> List[sqlite3.Row]:
        return self._rows("SELECT * FROM drafts WHERE session_date=? ORDER BY generated_at",
                          (session_date,))

    def latest_draft(self, session_date: str = "") -> Optional[sqlite3.Row]:
        if session_date:
            rows = self._rows("SELECT * FROM drafts WHERE session_date=? "
                              "ORDER BY generated_at DESC LIMIT 1", (session_date,))
        else:
            rows = self._rows("SELECT * FROM drafts ORDER BY session_date DESC, "
                              "generated_at DESC LIMIT 1")
        return rows[0] if rows else None

    def claims_for_draft(self, draft_id: str) -> List[sqlite3.Row]:
        return self._rows("SELECT * FROM claims WHERE draft_id=? ORDER BY claim_order",
                          (draft_id,))

    def drafts_by_verdict(self, verdict: str) -> List[sqlite3.Row]:
        return self._rows("SELECT * FROM drafts WHERE verdict=? ORDER BY session_date",
                          (verdict,))

    def claims_citing_fact(self, fact_id: str) -> List[sqlite3.Row]:
        return self._rows("SELECT draft_id, claim_id FROM claim_facts WHERE fact_id=?",
                          (fact_id,))

    def claims_citing_context(self, context_id: str) -> List[sqlite3.Row]:
        return self._rows("SELECT draft_id, claim_id FROM claim_contexts WHERE context_id=?",
                          (context_id,))
