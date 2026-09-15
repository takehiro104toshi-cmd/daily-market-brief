"""Corpus store（Phase 3.7 §4）。Data Bank 原則を再利用:

- canonical: JSONL append-only（corpus metadata と analysis artifact を **別ファイル** に分離）
- index: SQLite（canonical から `rebuild_index()` で再構築可能）
- idempotent: 各ファイルの key が既知なら追記しない
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Sequence

from ..core.paths import data_root
from .config import CORPUS_ROOT_NAME
from .source import SourceDocument, source_from_dict

#: canonical ファイル名 → key 列
CANONICAL: Dict[str, tuple] = {
    "documents": ("documents.jsonl", "document_id"),
    "document_updates": ("document_updates.jsonl", "update_id"),   # recovery 等による row の改訂（append-only）
    "status_events": ("status_events.jsonl", "event_id"),
    "duplicates": ("duplicates.jsonl", "duplicate_id"),
    "temporal": ("temporal.jsonl", "temporal_id"),
    "extractions": ("extractions.jsonl", "extraction_id"),
    "artifacts": ("artifacts.jsonl", "artifact_id"),
    "analyses": ("analyses.jsonl", "record_id"),
    "quality": ("quality.jsonl", "quality_id"),
    "coverage": ("coverage_labels.jsonl", "label_id"),
    "alignments": ("alignments.jsonl", "alignment_id"),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  document_id TEXT PRIMARY KEY, sha256 TEXT, original_filename TEXT, source_type TEXT,
  received_at TEXT, document_date TEXT, date_sequence INTEGER, page_count INTEGER,
  byte_size INTEGER, media_type TEXT, storage_locator TEXT, family TEXT,
  family_confidence TEXT, publication_date TEXT, schema_version TEXT);
CREATE INDEX IF NOT EXISTS ix_doc_sha ON documents(sha256);
CREATE INDEX IF NOT EXISTS ix_doc_date ON documents(document_date, date_sequence);
CREATE TABLE IF NOT EXISTS status_events (
  event_id TEXT PRIMARY KEY, document_id TEXT, status TEXT, reason TEXT, at TEXT, version TEXT);
CREATE INDEX IF NOT EXISTS ix_se_doc ON status_events(document_id);
CREATE TABLE IF NOT EXISTS duplicates (
  duplicate_id TEXT PRIMARY KEY, sha256 TEXT, original_filename TEXT, received_at TEXT,
  existing_document_id TEXT, source_type TEXT);
CREATE TABLE IF NOT EXISTS temporal (
  temporal_id TEXT PRIMARY KEY, document_id TEXT, document_date TEXT, publication_date TEXT,
  received_at TEXT, referenced_market_session TEXT, referenced_session_basis TEXT,
  payload_json TEXT);
CREATE INDEX IF NOT EXISTS ix_temporal_doc ON temporal(document_id);
CREATE TABLE IF NOT EXISTS extractions (
  extraction_id TEXT PRIMARY KEY, document_id TEXT, extractor_name TEXT, extractor_version TEXT,
  page_count INTEGER, text_layer_present INTEGER, ocr_attempted INTEGER, artifact_count INTEGER,
  created_at TEXT, payload_json TEXT);
CREATE INDEX IF NOT EXISTS ix_ext_doc ON extractions(document_id);
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY, document_id TEXT, extractor_version TEXT, page INTEGER,
  block_index INTEGER, line_start INTEGER, line_end INTEGER, kind TEXT, quality TEXT,
  ocr_derived INTEGER, text TEXT);
CREATE INDEX IF NOT EXISTS ix_art_doc ON artifacts(document_id, extractor_version, page, block_index);
CREATE TABLE IF NOT EXISTS analyses (
  record_id TEXT PRIMARY KEY, document_id TEXT, analysis_version TEXT, analyzer_name TEXT,
  supersedes TEXT, created_at TEXT, p2_mode TEXT, payload_json TEXT);
CREATE INDEX IF NOT EXISTS ix_ana_doc ON analyses(document_id, analysis_version);
CREATE TABLE IF NOT EXISTS observations (
  observation_id TEXT PRIMARY KEY, record_id TEXT, document_id TEXT, level TEXT, category TEXT,
  page INTEGER, artifact_id TEXT, key TEXT, value TEXT, confidence_ladder INTEGER);
CREATE INDEX IF NOT EXISTS ix_obs_record ON observations(record_id, category);
CREATE INDEX IF NOT EXISTS ix_obs_level ON observations(level);
CREATE TABLE IF NOT EXISTS quality (
  quality_id TEXT PRIMARY KEY, document_id TEXT, quality TEXT, analysis_version TEXT,
  extractor_version TEXT, eligible INTEGER, created_at TEXT, reasons TEXT);
CREATE INDEX IF NOT EXISTS ix_q_doc ON quality(document_id);
CREATE TABLE IF NOT EXISTS coverage_labels (
  label_id TEXT, document_id TEXT, dimension TEXT, label TEXT, source TEXT,
  thresholds_version TEXT, analysis_version TEXT, created_at TEXT,
  PRIMARY KEY (label_id, dimension));
CREATE INDEX IF NOT EXISTS ix_cov_doc ON coverage_labels(document_id);
CREATE INDEX IF NOT EXISTS ix_cov_dim ON coverage_labels(dimension, label);
CREATE TABLE IF NOT EXISTS alignments (
  alignment_id TEXT PRIMARY KEY, document_id TEXT, key TEXT, series_id TEXT, session TEXT,
  document_value TEXT, market_value TEXT, status TEXT, diff_pct TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_al_doc ON alignments(document_id);
"""

_DOC_COLUMNS = ("document_id", "sha256", "original_filename", "source_type", "received_at",
                "document_date", "date_sequence", "page_count", "byte_size", "media_type",
                "storage_locator", "family", "family_confidence", "publication_date",
                "schema_version")


def corpus_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / CORPUS_ROOT_NAME


class CorpusStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "index" / "corpus.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._known: Dict[str, set] = {}

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- canonical
    def path_of(self, name: str) -> Path:
        return self.root / CANONICAL[name][0]

    def iter_canonical(self, name: str) -> Iterator[Dict]:
        path = self.path_of(name)
        if not path.exists():
            return
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def _ids(self, name: str) -> set:
        if name not in self._known:
            key = CANONICAL[name][1]
            self._known[name] = {str(d.get(key, "")) for d in self.iter_canonical(name)}
        return self._known[name]

    def _append(self, name: str, rows: Sequence[Mapping]) -> Dict[str, int]:
        key = CANONICAL[name][1]
        known = self._ids(name)
        added = skipped = 0
        with self.path_of(name).open("a", encoding="utf-8") as handle:
            for data in rows:
                rid = str(data.get(key, ""))
                if not rid or rid in known:
                    skipped += 1
                    continue
                handle.write(json.dumps(dict(data), ensure_ascii=False, default=str) + "\n")
                known.add(rid)
                self._index(name, data)
                added += 1
        self._conn.commit()
        return {"added": added, "skipped": skipped}

    # ------------------------------------------------------------- index
    def _index(self, name: str, d: Mapping) -> None:
        c = self._conn
        if name == "documents":
            c.execute(f"INSERT OR REPLACE INTO documents ({','.join(_DOC_COLUMNS)}) "
                      f"VALUES ({','.join('?' * len(_DOC_COLUMNS))})",
                      tuple(d.get(col, "") if col not in ("date_sequence", "page_count", "byte_size")
                            else int(d.get(col, 0) or 0) for col in _DOC_COLUMNS))
        elif name == "document_updates":
            doc = dict(d.get("document") or {})
            if doc.get("document_id"):
                self._index("documents", doc)               # index は最新 row（canonical は両方残る）
        elif name == "status_events":
            c.execute("INSERT OR REPLACE INTO status_events VALUES (?,?,?,?,?,?)",
                      (d["event_id"], d.get("document_id", ""), d.get("status", ""),
                       d.get("reason", ""), d.get("at", ""), d.get("version", "")))
        elif name == "duplicates":
            c.execute("INSERT OR REPLACE INTO duplicates VALUES (?,?,?,?,?,?)",
                      (d["duplicate_id"], d.get("sha256", ""), d.get("original_filename", ""),
                       d.get("received_at", ""), d.get("existing_document_id", ""),
                       d.get("source_type", "")))
        elif name == "temporal":
            c.execute("INSERT OR REPLACE INTO temporal VALUES (?,?,?,?,?,?,?,?)",
                      (d["temporal_id"], d.get("document_id", ""), d.get("document_date", ""),
                       d.get("publication_date", ""), d.get("received_at", ""),
                       d.get("referenced_market_session", ""),
                       d.get("referenced_session_basis", ""),
                       json.dumps(dict(d), ensure_ascii=False, default=str)))
        elif name == "extractions":
            c.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (d["extraction_id"], d.get("document_id", ""), d.get("extractor_name", ""),
                       d.get("extractor_version", ""), int(d.get("page_count", 0) or 0),
                       int(bool(d.get("text_layer_present"))), int(bool(d.get("ocr_attempted"))),
                       int(d.get("artifact_count", 0) or 0), d.get("created_at", ""),
                       json.dumps(dict(d), ensure_ascii=False, default=str)))
        elif name == "artifacts":
            c.execute("INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (d["artifact_id"], d.get("document_id", ""), d.get("extractor_version", ""),
                       int(d.get("page", 0) or 0), int(d.get("block_index", 0) or 0),
                       int(d.get("line_start", 0) or 0), int(d.get("line_end", 0) or 0),
                       d.get("kind", ""), d.get("quality", ""), int(bool(d.get("ocr_derived"))),
                       d.get("text", "")))
        elif name == "analyses":
            rid = d["record_id"]
            c.execute("INSERT OR REPLACE INTO analyses VALUES (?,?,?,?,?,?,?,?)",
                      (rid, d.get("document_id", ""), d.get("analysis_version", ""),
                       d.get("analyzer_name", ""), d.get("supersedes", ""), d.get("created_at", ""),
                       d.get("p2_mode", ""), json.dumps(dict(d), ensure_ascii=False, default=str)))
            c.execute("DELETE FROM observations WHERE record_id=?", (rid,))
            for cat, items in dict(d.get("observations") or {}).items():
                for o in items:
                    c.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (o.get("observation_id", ""), rid, d.get("document_id", ""),
                               o.get("level", ""), o.get("category", cat), int(o.get("page", 0) or 0),
                               o.get("artifact_id", ""), o.get("key", ""), str(o.get("value", "")),
                               o.get("confidence_ladder")))
        elif name == "quality":
            c.execute("INSERT OR REPLACE INTO quality VALUES (?,?,?,?,?,?,?,?)",
                      (d["quality_id"], d.get("document_id", ""), d.get("quality", ""),
                       d.get("analysis_version", ""), d.get("extractor_version", ""),
                       int(bool(d.get("eligible_for_pattern_evidence"))), d.get("created_at", ""),
                       json.dumps(list(d.get("reasons") or []), ensure_ascii=False)))
        elif name == "coverage":
            lid = d["label_id"]
            c.execute("DELETE FROM coverage_labels WHERE label_id=?", (lid,))
            labels = dict(d.get("labels") or {})
            sources = dict(d.get("sources") or {})
            for dim, label in labels.items():
                c.execute("INSERT OR REPLACE INTO coverage_labels VALUES (?,?,?,?,?,?,?,?)",
                          (lid, d.get("document_id", ""), dim, label, sources.get(dim, ""),
                           d.get("thresholds_version", ""), d.get("analysis_version", ""),
                           d.get("created_at", "")))
        elif name == "alignments":
            c.execute("INSERT OR REPLACE INTO alignments VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (d["alignment_id"], d.get("document_id", ""), d.get("key", ""),
                       d.get("series_id", ""), d.get("session", ""),
                       None if d.get("document_value") is None else str(d.get("document_value")),
                       None if d.get("market_value") is None else str(d.get("market_value")),
                       d.get("status", ""),
                       None if d.get("diff_pct") is None else str(d.get("diff_pct")),
                       d.get("created_at", "")))

    def rebuild_index(self) -> Dict[str, int]:
        """SQLite を捨てて canonical だけから再構築する。"""
        c = self._conn
        for table in ("documents", "status_events", "duplicates", "temporal", "extractions",
                      "artifacts", "analyses", "observations", "quality", "coverage_labels",
                      "alignments"):
            c.execute(f"DELETE FROM {table}")
        counts: Dict[str, int] = {}
        for name in CANONICAL:
            n = 0
            for d in self.iter_canonical(name):
                self._index(name, d)
                n += 1
            counts[name] = n
        c.commit()
        self._known = {}
        return counts

    # ------------------------------------------------------------- writes
    def add_document(self, doc: SourceDocument) -> bool:
        return self._append("documents", [doc.as_dict()])["added"] == 1

    def add_status_event(self, event) -> bool:
        return self._append("status_events", [event.as_dict()])["added"] == 1

    def update_document(self, doc: SourceDocument, reason: str, at: str) -> bool:
        """既存 document row の改訂（recovery 用）。canonical には update record を **追記** し、
        index の documents row を最新にする。元の row は documents.jsonl に残る（audit）。"""
        import hashlib

        update_id = "csu_" + hashlib.sha1(f"{doc.document_id}|{reason}|{at}".encode("utf-8")).hexdigest()[:16]
        return self._append("document_updates", [{"update_id": update_id, "document_id": doc.document_id,
                                                   "reason": reason, "at": at, "document": doc.as_dict()}])["added"] == 1

    def last_status_event(self, document_id: str) -> Optional[Dict]:
        rows = self._rows("SELECT * FROM status_events WHERE document_id=? ORDER BY rowid DESC LIMIT 1", (document_id,))
        return dict(rows[0]) if rows else None

    def add_duplicate(self, entry: Mapping) -> bool:
        return self._append("duplicates", [entry])["added"] == 1

    def add_temporal(self, entry: Mapping) -> bool:
        return self._append("temporal", [entry])["added"] == 1

    def add_extraction(self, summary, artifacts) -> Dict[str, int]:
        r1 = self._append("extractions", [summary.as_dict()])
        r2 = self._append("artifacts", [a.as_dict() for a in artifacts])
        return {"extraction_added": r1["added"], "artifacts_added": r2["added"],
                "artifacts_skipped": r2["skipped"]}

    def add_analysis(self, record) -> bool:
        return self._append("analyses", [record.as_dict()])["added"] == 1

    def add_quality(self, quality) -> bool:
        return self._append("quality", [quality.as_dict()])["added"] == 1

    def add_coverage(self, labels) -> bool:
        return self._append("coverage", [labels.as_dict()])["added"] == 1

    def add_alignments(self, results) -> Dict[str, int]:
        return self._append("alignments", [r.as_dict() for r in results])

    # ------------------------------------------------------------- reads
    def _rows(self, sql: str, params: Sequence = ()) -> List[sqlite3.Row]:
        return list(self._conn.execute(sql, tuple(params)).fetchall())

    def document(self, document_id: str) -> Optional[SourceDocument]:
        rows = self._rows("SELECT * FROM documents WHERE document_id=?", (document_id,))
        return source_from_dict(dict(rows[0])) if rows else None

    def document_by_sha(self, sha256: str) -> Optional[SourceDocument]:
        rows = self._rows("SELECT * FROM documents WHERE sha256=?", (sha256,))
        return source_from_dict(dict(rows[0])) if rows else None

    def documents(self) -> List[SourceDocument]:
        return [source_from_dict(dict(r)) for r in
                self._rows("SELECT * FROM documents ORDER BY document_date, date_sequence, document_id")]

    def next_date_sequence(self, document_date: str) -> int:
        rows = self._rows("SELECT COUNT(*) AS n FROM documents WHERE document_date=?", (document_date,))
        return int(rows[0]["n"]) + 1 if rows else 1

    def status_history(self, document_id: str) -> List[Dict]:
        return [dict(r) for r in self._rows(
            "SELECT * FROM status_events WHERE document_id=? ORDER BY rowid", (document_id,))]

    def current_status(self, document_id: str) -> str:
        rows = self._rows("SELECT status FROM status_events WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
                          (document_id,))
        return str(rows[0]["status"]) if rows else ""

    def status_count(self, document_id: str) -> int:
        rows = self._rows("SELECT COUNT(*) AS n FROM status_events WHERE document_id=?", (document_id,))
        return int(rows[0]["n"]) if rows else 0

    def duplicates(self) -> List[Dict]:
        return [dict(r) for r in self._rows("SELECT * FROM duplicates ORDER BY rowid")]

    def temporal_for(self, document_id: str) -> Optional[Dict]:
        rows = self._rows("SELECT payload_json FROM temporal WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
                          (document_id,))
        return json.loads(rows[0]["payload_json"]) if rows else None

    def extraction_for(self, document_id: str, extractor_version: str = "") -> Optional[Dict]:
        if extractor_version:
            rows = self._rows("SELECT payload_json FROM extractions WHERE document_id=? AND extractor_version=?",
                              (document_id, extractor_version))
        else:
            rows = self._rows("SELECT payload_json FROM extractions WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
                              (document_id,))
        return json.loads(rows[0]["payload_json"]) if rows else None

    def artifacts_for(self, document_id: str, extractor_version: str = "") -> List[Dict]:
        if extractor_version:
            sql = ("SELECT * FROM artifacts WHERE document_id=? AND extractor_version=? "
                   "ORDER BY page, block_index")
            params: Sequence = (document_id, extractor_version)
        else:
            sql = "SELECT * FROM artifacts WHERE document_id=? ORDER BY extractor_version, page, block_index"
            params = (document_id,)
        return [dict(r) for r in self._rows(sql, params)]

    def artifact(self, artifact_id: str) -> Optional[Dict]:
        rows = self._rows("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,))
        return dict(rows[0]) if rows else None

    def analyses_for(self, document_id: str) -> List[Dict]:
        return [json.loads(r["payload_json"]) for r in self._rows(
            "SELECT payload_json FROM analyses WHERE document_id=? ORDER BY rowid", (document_id,))]

    def current_analysis(self, document_id: str) -> Optional[Dict]:
        from .versioning import current_analysis as _current

        return _current(self.analyses_for(document_id))

    def observation(self, observation_id: str) -> Optional[Dict]:
        rows = self._rows("SELECT * FROM observations WHERE observation_id=?", (observation_id,))
        return dict(rows[0]) if rows else None

    def quality_for(self, document_id: str) -> Optional[Dict]:
        rows = self._rows("SELECT * FROM quality WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
                          (document_id,))
        if not rows:
            return None
        d = dict(rows[0])
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        d["eligible_for_pattern_evidence"] = bool(d.pop("eligible", 0))
        return d

    def coverage_for(self, document_id: str) -> Optional[Dict]:
        rows = self._rows("SELECT * FROM coverage_labels WHERE document_id=? ORDER BY rowid", (document_id,))
        if not rows:
            return None
        latest = rows[-1]["label_id"]
        labels = {r["dimension"]: r["label"] for r in rows if r["label_id"] == latest}
        sources = {r["dimension"]: r["source"] for r in rows if r["label_id"] == latest}
        return {"label_id": latest, "document_id": document_id, "labels": labels, "sources": sources,
                "thresholds_version": rows[-1]["thresholds_version"],
                "analysis_version": rows[-1]["analysis_version"], "created_at": rows[-1]["created_at"]}

    def alignments_for(self, document_id: str) -> List[Dict]:
        return [dict(r) for r in self._rows(
            "SELECT * FROM alignments WHERE document_id=? ORDER BY rowid", (document_id,))]

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for table in ("documents", "status_events", "duplicates", "temporal", "extractions",
                      "artifacts", "analyses", "observations", "quality", "coverage_labels",
                      "alignments"):
            out[table] = int(self._rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])
        return out

    def canonical_counts(self) -> Dict[str, int]:
        return {name: sum(1 for _ in self.iter_canonical(name)) for name in CANONICAL}

    def provenance_chain(self, observation_id: str) -> Optional[Dict]:
        """Corpus record → extraction artifact → page/location → 原本 PDF（locator + sha256）。"""
        obs = self.observation(observation_id)
        if obs is None:
            return None
        art = self.artifact(str(obs.get("artifact_id") or "")) if obs.get("artifact_id") else None
        doc = self.document(str(obs.get("document_id") or ""))
        return {
            "observation": obs,
            "record_id": obs.get("record_id"),
            "artifact": None if art is None else {k: art[k] for k in
                                                  ("artifact_id", "extractor_version", "page",
                                                   "line_start", "line_end", "kind")},
            "document": None if doc is None else {"document_id": doc.document_id,
                                                  "storage_locator": doc.storage_locator,
                                                  "sha256": doc.sha256,
                                                  "document_date": doc.document_date},
        }
