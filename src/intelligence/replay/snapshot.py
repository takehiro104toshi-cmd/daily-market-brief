"""Immutable input universe の捕捉（Phase 3.9.4）— corpus と Context を run 開始時に 1 回だけ凍結する。

corpus  : SQLite online backup（`Connection.backup()`）で **論理的に一貫した** copy を作る。
          OS のファイルコピーは禁止（CompassIntake が並行して書くため torn になり得る）。
          production は `mode=ro` の URI で開き、replay は以後 copy だけを読む。
Context : production の ContextStore / trading calendar から replay に必要な行を **1 回だけ**
          canonical JSONL へ書き出し、以後は frozen callable を MarketConnector に注入する。
          run 内の全 snapshot が同一の Context 状態を使う（snapshot 20 と 100 で状態が違う torn run を防ぐ）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..corpus_research.regime import MarketConnector
from .errors import ReplayContextSnapshotError, ReplaySnapshotCaptureError

CONTEXT_FILE = "contexts.jsonl"
CALENDAR_FILE = "trading_days.json"
STALE = "STALE"
#: regime 判定が読む Context 列（context_labels が参照する field + 順序を決める field）
CONTEXT_FIELDS = ("context_id", "context_type", "subject_id", "session_date", "known_at",
                  "direction", "note", "status", "priority_tier", "revision_of")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def read_only_uri(db_path: Path) -> str:
    """production DB を書き込み不能で開く URI（Windows の drive letter も `file:///D:/...` で扱える）。"""
    return Path(db_path).resolve().as_uri() + "?mode=ro"


# ------------------------------------------------------------------- corpus
@dataclass(frozen=True)
class CorpusSnapshotInfo:
    source_db: str                 # redacted 表示用（basename のみ）
    snapshot_root: str
    snapshot_db_sha256: str        # 物理 copy の identity（run 固有。決定性 digest には使わない）
    page_count: int
    tables: Mapping[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"source_db": self.source_db, "snapshot_root": self.snapshot_root,
                "snapshot_db_sha256": self.snapshot_db_sha256, "page_count": self.page_count,
                "tables": dict(self.tables)}


def capture_corpus_snapshot(production_corpus_root: Path, snapshot_root: Path) -> CorpusSnapshotInfo:
    """production の corpus.sqlite3 を SQLite backup API で一貫コピーする（read-only で開く）。"""
    src_db = Path(production_corpus_root) / "index" / "corpus.sqlite3"
    if not src_db.is_file():
        raise ReplaySnapshotCaptureError("production corpus index not found (corpus.sqlite3 missing)")
    dst_db = Path(snapshot_root) / "index" / "corpus.sqlite3"
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    if dst_db.exists():
        raise ReplaySnapshotCaptureError("snapshot destination already exists; refusing to overwrite")
    try:
        src = sqlite3.connect(read_only_uri(src_db), uri=True)
    except sqlite3.Error as exc:
        raise ReplaySnapshotCaptureError(f"cannot open production corpus read-only: {type(exc).__name__}") from exc
    try:
        dst = sqlite3.connect(dst_db)
        try:
            src.backup(dst)                      # pages=-1: 1 step で全 page → 一貫した snapshot
            dst.commit()
            tables = {}
            for name in ("documents", "status_events", "duplicates", "quality", "analyses", "artifacts"):
                tables[name] = int(dst.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            pages = int(dst.execute("PRAGMA page_count").fetchone()[0])
        finally:
            dst.close()
    except sqlite3.Error as exc:
        raise ReplaySnapshotCaptureError(f"sqlite backup failed: {type(exc).__name__}") from exc
    finally:
        src.close()
    return CorpusSnapshotInfo(source_db=src_db.name, snapshot_root=str(snapshot_root),
                              snapshot_db_sha256=sha256_file(dst_db), page_count=pages, tables=tables)


def live_corpus_observation(production_corpus_root: Path) -> Dict[str, Any]:
    """production corpus の観測値（documents / eligible）。read-only。結果には影響させない。"""
    src_db = Path(production_corpus_root) / "index" / "corpus.sqlite3"
    if not src_db.is_file():
        return {"exists": False, "documents": 0, "eligible": 0}
    conn = sqlite3.connect(read_only_uri(src_db), uri=True)
    try:
        documents = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        eligible = int(conn.execute(
            "SELECT COUNT(*) FROM quality q WHERE q.eligible=1 AND q.rowid = "
            "(SELECT MAX(rowid) FROM quality q2 WHERE q2.document_id=q.document_id)").fetchone()[0])
        duplicates = int(conn.execute("SELECT COUNT(*) FROM duplicates").fetchone()[0])
    finally:
        conn.close()
    return {"exists": True, "documents": documents, "eligible": eligible, "duplicates": duplicates}


def live_document_identity(production_corpus_root: Path, document_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """drift 判定用: 捕捉済み文書の sha256 / 最新 status / 最新 quality を production から read-only で読む。"""
    src_db = Path(production_corpus_root) / "index" / "corpus.sqlite3"
    out: Dict[str, Dict[str, Any]] = {}
    if not src_db.is_file():
        return out
    conn = sqlite3.connect(read_only_uri(src_db), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for doc in document_ids:
            row = conn.execute("SELECT sha256, document_date, date_sequence FROM documents WHERE document_id=?",
                               (doc,)).fetchone()
            if row is None:
                out[doc] = {"missing": True}
                continue
            status = conn.execute("SELECT status FROM status_events WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
                                  (doc,)).fetchone()
            quality = conn.execute("SELECT quality, eligible FROM quality WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
                                   (doc,)).fetchone()
            out[doc] = {"sha256": row["sha256"], "document_date": row["document_date"],
                        "date_sequence": int(row["date_sequence"] or 0),
                        "status": status["status"] if status else "",
                        "quality": quality["quality"] if quality else "",
                        "eligible": bool(quality["eligible"]) if quality else False}
    finally:
        conn.close()
    return out


# ------------------------------------------------------------------- context
@dataclass(frozen=True)
class ContextSnapshot:
    rows_by_session: Mapping[str, Sequence[Mapping[str, Any]]]
    trading_days: Sequence[str]
    context_manifest_digest: str
    context_available: bool
    calendar_available: bool
    row_count: int
    session_count: int
    latest_session_date: str

    def as_dict(self) -> Dict[str, Any]:
        return {"context_manifest_digest": self.context_manifest_digest,
                "context_available": self.context_available, "calendar_available": self.calendar_available,
                "row_count": self.row_count, "session_count": self.session_count,
                "trading_days": len(self.trading_days), "latest_session_date": self.latest_session_date}

    def connector(self) -> MarketConnector:
        """run 内の全 snapshot が共有する frozen connector。live store には一切触れない。"""
        rows = {k: [dict(r) for r in v] for k, v in self.rows_by_session.items()}
        return MarketConnector(trading_days=list(self.trading_days) or None,
                               context_rows=(lambda session, _rows=rows: list(_rows.get(session, [])))
                               if self.context_available else None)


def _context_digest(rows_by_session: Mapping[str, Sequence[Mapping[str, Any]]], trading_days: Sequence[str]) -> str:
    view = {"rows": [[{k: r.get(k) for k in CONTEXT_FIELDS} for r in rows_by_session[s]]
                     for s in sorted(rows_by_session)],
            "sessions": sorted(rows_by_session), "trading_days": list(trading_days)}
    return hashlib.sha256(_canonical(view).encode("utf-8")).hexdigest()[:16]


def export_context_snapshot(production_data_root: Path, snapshot_dir: Path, upto_session_date: str
                            ) -> ContextSnapshot:
    """production Context / calendar から replay に必要な行だけを 1 回で書き出し、frozen snapshot を返す。

    範囲は session_date <= 最新の捕捉文書日付（それより後の session は cutoff 規則により
    どの文書の regime にも影響しない）。STALE 行は production の SQL と同じく除外し、
    同一 session 内の順序（priority_tier, context_type, subject_id）も保存する。
    """
    from ..context.store import context_root

    snapshot_dir = Path(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    rows_by_session: Dict[str, List[Dict[str, Any]]] = {}
    context_available = False
    croot = context_root(Path(production_data_root))
    cdb = croot / "index" / "context.sqlite3"
    if not cdb.is_file():                        # 名前が違う実装に備えて index 直下の sqlite を探す
        candidates = sorted((croot / "index").glob("*.sqlite3")) if (croot / "index").is_dir() else []
        cdb = candidates[0] if candidates else cdb
    if cdb.is_file():
        try:
            conn = sqlite3.connect(read_only_uri(cdb), uri=True)
            conn.row_factory = sqlite3.Row
            try:
                sql = ("SELECT * FROM contexts WHERE status<>? "
                       + ("AND session_date<=? " if upto_session_date else "")
                       + "ORDER BY session_date, priority_tier, context_type, subject_id")
                params = (STALE, upto_session_date) if upto_session_date else (STALE,)
                for row in conn.execute(sql, params):
                    d = {k: row[k] for k in row.keys()}
                    rows_by_session.setdefault(str(d.get("session_date", "")), []).append(d)
            finally:
                conn.close()
            context_available = True
        except sqlite3.Error as exc:
            raise ReplayContextSnapshotError(f"cannot read production context store: {type(exc).__name__}") from exc

    trading_days: List[str] = []
    calendar_available = False
    try:
        from ..market.p2h_light_pilot import light_root
        from ..market.jquants_light_store import JQuantsLightStore
        from ..market.tokyo_calendar import trading_days as _trading_days

        lroot = light_root(Path(production_data_root))
        if (lroot / "index").exists():
            light = JQuantsLightStore(lroot)
            try:
                rows = [dict(r) for r in light.calendar_range("1900-01-01", "2999-12-31")]
            finally:
                light.close()
            trading_days = [d for d in _trading_days(rows) if not upto_session_date or d <= upto_session_date]
            calendar_available = bool(trading_days)
    except Exception as exc:  # noqa: BLE001 calendar store が無い/壊れている → 利用不可として記録（捏造しない）
        calendar_available = False

    with (snapshot_dir / CONTEXT_FILE).open("w", encoding="utf-8") as handle:
        for session in sorted(rows_by_session):
            for r in rows_by_session[session]:
                handle.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    (snapshot_dir / CALENDAR_FILE).write_text(json.dumps(trading_days), encoding="utf-8")
    digest = _context_digest(rows_by_session, trading_days)
    return ContextSnapshot(rows_by_session={k: tuple(v) for k, v in rows_by_session.items()},
                           trading_days=tuple(trading_days), context_manifest_digest=digest,
                           context_available=context_available, calendar_available=calendar_available,
                           row_count=sum(len(v) for v in rows_by_session.values()),
                           session_count=len(rows_by_session),
                           latest_session_date=max(rows_by_session) if rows_by_session else "")


def live_context_digest(production_data_root: Path, upto_session_date: str) -> str:
    """drift 判定用: production Context を同じ範囲・同じ規則で再読して digest を計算する（書かない）。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        snap = export_context_snapshot(production_data_root, Path(td), upto_session_date)
    return snap.context_manifest_digest
