"""SQLite索引（Phase 2-A / DATA_BANK_STORAGE_DECISIONの参照実装）。

役割分担（正本を持たない**再構築可能な索引**——tank実証パターン）:
    JSONL   … append-only正本（Raw / normalized / QA / news。監査・不変）
    SQLite  … 検索用operational index（**いつでもJSONL正本から再生成できる**）
    Parquet … 分析用bulk履歴（将来。Phase 5+）

規律:
- domain layerはSQLを書かない（本モジュールがRepository実装として隔離。
  将来Postgresへ差し替えてもdomain/query契約は無変更）。
- 索引は導出物: スキーマ変更時はDROPして正本から再構築（migration不安を持たない）。
- stdlib sqlite3のみ（依存追加なし）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..core.time import to_utc_iso
from ..evidence_qa.model import EvidenceAssessment
from .news_model import NewsClassification, NewsItem
from .query import NewsQuery

_SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    news_item_id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL,
    primary_document_id TEXT NOT NULL,
    headline TEXT NOT NULL,
    published_at TEXT,           -- UTC ISO（unknownはNULL）
    publisher TEXT,
    source_id TEXT,
    language TEXT,
    canonical_url TEXT,
    guid TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source_id);
CREATE INDEX IF NOT EXISTS idx_news_publisher ON news_items(publisher);

CREATE TABLE IF NOT EXISTS classifications (
    classification_id TEXT PRIMARY KEY,
    news_item_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    provenance TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cls_lookup ON classifications(dimension, value);

CREATE TABLE IF NOT EXISTS trust_decisions (
    record_id TEXT NOT NULL,
    policy_name TEXT NOT NULL,
    decision TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    PRIMARY KEY (record_id, policy_name, assessed_at)
);

CREATE TABLE IF NOT EXISTS review_items (
    review_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    review_type TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_record ON review_items(record_id);
"""

#: NewsQuery.entityが横断する entity系次元（companyを含む）
_ENTITY_DIMENSIONS_SQL = (
    "company", "central_bank", "government", "person", "index", "commodity", "currency")


class SqliteNewsIndex:
    """News Bankの検索索引（NewsQueryable充足）。正本から再構築可能。"""

    def __init__(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(_SCHEMA)
        self._items: Dict[str, NewsItem] = {}
        self._load_items()

    def _load_items(self) -> None:
        # NewsItem全体はdomainオブジェクトとして保持（索引はキー検索のみ担当）。
        # 再構築可能な導出物なので、index_* 呼び出しで正本から埋め直す。
        pass

    # ---------------------------------------------------------------- 構築（正本→索引）

    def index_news_items(self, items: Sequence[NewsItem]) -> int:
        rows = [
            (n.news_item_id, n.article_id, n.primary_document_id, n.headline,
             to_utc_iso(n.published_at) if n.published_at else None,
             n.publisher, n.source_id, n.language, n.canonical_url, n.guid)
            for n in items
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO news_items VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        self._conn.commit()
        for n in items:
            self._items[n.news_item_id] = n
        return len(rows)

    def index_classifications(self, classifications: Sequence[NewsClassification]) -> int:
        rows = [
            (c.classification_id, c.news_item_id, c.dimension.value, c.value,
             c.provenance.value)
            for c in classifications
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO classifications VALUES (?,?,?,?,?)", rows)
        self._conn.commit()
        return len(rows)

    def index_assessments(self, assessments: Sequence[EvidenceAssessment]) -> int:
        rows = [
            (a.record_id, a.policy_name, a.decision.value, to_utc_iso(a.assessed_at))
            for a in assessments
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO trust_decisions VALUES (?,?,?,?)", rows)
        self._conn.commit()
        return len(rows)

    def index_review_items(self, items) -> int:
        """ReviewItem（latest状態）の索引（review_statusフィルタ用。P2-F追加）。"""
        rows = [(r.review_id, r.record_id, r.review_type.value, r.status.value)
                for r in items]
        self._conn.executemany(
            "INSERT OR REPLACE INTO review_items VALUES (?,?,?,?)", rows)
        self._conn.commit()
        return len(rows)

    def rebuild(self) -> None:
        """索引は導出物: 全消去して正本からindex_*で再構築する（スキーマ変更時の手順）。"""
        for table in ("news_items", "classifications", "trust_decisions", "review_items"):
            self._conn.execute(f"DELETE FROM {table}")
        self._conn.commit()
        self._items.clear()

    # ---------------------------------------------------------------- 検索（NewsQueryable）

    def search_news(self, query: NewsQuery) -> Sequence[NewsItem]:
        sql = ["SELECT DISTINCT n.news_item_id FROM news_items n"]
        params: List[str] = []
        joins: List[str] = []
        where: List[str] = []

        def cls_filter(dimension: str, value: str, alias: str) -> None:
            joins.append(
                f"JOIN classifications {alias} ON {alias}.news_item_id = n.news_item_id "
                f"AND {alias}.dimension = ? AND {alias}.value = ?")
            params.extend([dimension, value])

        if query.country:
            cls_filter("country", query.country, "c1")
        if query.company:
            cls_filter("company", query.company, "c2")
        if query.ticker:
            cls_filter("ticker", query.ticker, "c3")  # P2-E: ticker専用次元へ（entity_matcher出力）
        if query.theme:
            cls_filter("theme", query.theme, "c4")
        if query.event_type:
            cls_filter("event_type", query.event_type, "c5")
        if query.entity:  # entity系次元の横断（P2-F）
            marks = ",".join("?" for _ in _ENTITY_DIMENSIONS_SQL)
            joins.append(
                "JOIN classifications ce ON ce.news_item_id = n.news_item_id "
                f"AND ce.dimension IN ({marks}) AND ce.value = ?")
            params.extend([*_ENTITY_DIMENSIONS_SQL, query.entity])
        if query.classification_provenance:
            joins.append(
                "JOIN classifications cp ON cp.news_item_id = n.news_item_id "
                "AND cp.provenance = ?")
            params.append(query.classification_provenance)
        if query.review_status:
            joins.append(
                "JOIN review_items rv ON (rv.record_id = n.news_item_id "
                "OR rv.record_id = n.article_id) AND rv.status = ?")
            params.append(query.review_status)
        if query.trust_decisions:
            marks = ",".join("?" for _ in query.trust_decisions)
            joins.append(
                "JOIN trust_decisions t ON t.record_id = n.primary_document_id "
                f"AND t.decision IN ({marks})")
            params.extend(query.trust_decisions)
        if query.date_from:
            where.append("n.published_at >= ?")
            params.append(to_utc_iso(query.date_from))
        if query.date_to:
            where.append("n.published_at <= ?")
            params.append(to_utc_iso(query.date_to))
        for column, value in (("publisher", query.publisher), ("source_id", query.source_id),
                              ("language", query.language)):
            if value:
                where.append(f"n.{column} = ?")
                params.append(value)

        sql.extend(joins)
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY n.published_at DESC")
        sql.append(f"LIMIT {int(query.limit)}")
        rows = self._conn.execute(" ".join(sql), params).fetchall()
        return [self._items[r[0]] for r in rows if r[0] in self._items]

    # ------------------------------------------- 時系列集計foundation（Phase 2-E追加）
    # 本格Trend EngineはPhase 6——ここは件数取得のquery契約のみ（傾向の主張はしない）。

    def count_by_dimension_over_time(
        self, dimension: str, *, granularity: str = "day",
        date_from: str = "", date_to: str = "",
    ) -> List[tuple]:
        """(期間, 分類値, 件数) の列。granularity: day / week / month。"""
        fmt = {"day": "%Y-%m-%d", "week": "%Y-W%W", "month": "%Y-%m"}.get(granularity)
        if fmt is None:
            raise ValueError(f"unknown granularity: {granularity}")
        where = ["c.dimension = ?", "n.published_at IS NOT NULL"]
        params: List[str] = [dimension]
        if date_from:
            where.append("n.published_at >= ?")
            params.append(date_from)
        if date_to:
            where.append("n.published_at <= ?")
            params.append(date_to)
        sql = (
            f"SELECT strftime('{fmt}', n.published_at) AS period, c.value, "
            "COUNT(DISTINCT n.news_item_id) AS n "
            "FROM classifications c JOIN news_items n ON n.news_item_id = c.news_item_id "
            f"WHERE {' AND '.join(where)} GROUP BY period, c.value ORDER BY period, c.value")
        return list(self._conn.execute(sql, params))

    def count_publishers_over_time(
        self, *, granularity: str = "day", date_from: str = "", date_to: str = "",
    ) -> List[tuple]:
        """(期間, publisher, 記事数)。時系列集計foundation（分析判断はしない）。"""
        fmt = {"day": "%Y-%m-%d", "week": "%Y-W%W", "month": "%Y-%m"}.get(granularity)
        if fmt is None:
            raise ValueError(f"unknown granularity: {granularity}")
        where = ["published_at IS NOT NULL"]
        params: List[str] = []
        if date_from:
            where.append("published_at >= ?")
            params.append(date_from)
        if date_to:
            where.append("published_at <= ?")
            params.append(date_to)
        sql = (f"SELECT strftime('{fmt}', published_at) AS period, publisher, COUNT(*) "
               f"FROM news_items WHERE {' AND '.join(where)} "
               "GROUP BY period, publisher ORDER BY period, publisher")
        return list(self._conn.execute(sql, params))

    def count_values(self, dimension: str) -> Dict[str, int]:
        """分類値ごとの記事数（entity mention数・event type数等の基礎集計）。"""
        rows = self._conn.execute(
            "SELECT value, COUNT(DISTINCT news_item_id) FROM classifications "
            "WHERE dimension = ? GROUP BY value", (dimension,)).fetchall()
        return {value: count for value, count in rows}

    def close(self) -> None:
        self._conn.close()
