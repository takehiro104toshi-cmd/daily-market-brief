"""Market Data Bankストレージ（Phase 2-D PART A/I）。

構成（news bank（P2-C）と同型: JSONL canonical＝正・SQLite＝再構築可能index）:

    <market_bank_root>/
    ├── raw/                  … provider生CSV（BlobStore）＋RawItem/FetchAttempt（P1-C再利用）
    ├── normalized/           … observations.jsonl（canonical・append-only・冪等）
    ├── evidence_qa/          … assessments.jsonl（append-only監査履歴）
    ├── index/market.sqlite3  … 検索index（canonicalから全再構築可能。正ではない）
    └── backfill_runs.jsonl   … 取得run manifest（append-only）

LATEST SEMANTICS（PART I: 「最新」の多義性を型で明示する）:
- latest_trading_session … 最新の**取引セッション日**の値（改定解決済み）。
  「昨晩の米国終値」はこれ（閲覧日のUTC日付ではない）。
- latest_as_of           … as_of時刻が最も新しい値（セッション日と通常一致するが、
  exchange_close/day_end_utcの規約差で日跨ぎがありうるため別クエリとして提供）。
- latest_revision_for    … ある(series, trading_date)の**最新改定版**（旧値は残る）。
- 「最新に取得した」はindexの責務ではなくrun manifest（backfill_runs.jsonl）の責務。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..core import serialization
from ..evidence_qa.model import EvidenceAssessment
from ..evidence_qa.store import JsonlAssessmentStore
from ..ingestion.model import FetchAttempt
from ..ingestion.raw_store import JsonlRawRepository
from ..normalization.store import JsonlNormalizedStore
from ..sources.model import RawItem
from .model import Observation, latest_revisions
from .providers import ProviderFetchResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    series_id      TEXT NOT NULL,
    trading_date   TEXT NOT NULL,
    as_of_utc      TEXT NOT NULL,
    value          TEXT,            -- Decimal文字列（floatにしない）。NULL=欠測
    unit           TEXT NOT NULL,
    currency       TEXT NOT NULL DEFAULT '',
    kind           TEXT NOT NULL,
    metric         TEXT NOT NULL,
    source_id      TEXT NOT NULL DEFAULT '',
    revision_of    TEXT NOT NULL DEFAULT '',
    seq            INTEGER          -- 取込順（同日同系列の安定順序）
);
CREATE INDEX IF NOT EXISTS idx_obs_series_date ON observations(series_id, trading_date);
CREATE INDEX IF NOT EXISTS idx_obs_series_asof ON observations(series_id, as_of_utc);
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id  TEXT PRIMARY KEY,
    record_id      TEXT NOT NULL,
    decision       TEXT NOT NULL,
    policy_name    TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    assessed_at    TEXT NOT NULL,
    seq            INTEGER
);
CREATE INDEX IF NOT EXISTS idx_assess_record ON assessments(record_id);
"""

#: 「非改定（現在有効）」条件: 同一series内で自分をrevision_ofに持つ行が無い
_NOT_SUPERSEDED = (
    "NOT EXISTS (SELECT 1 FROM observations n "
    "WHERE n.series_id = o.series_id AND n.revision_of = o.observation_id)"
)


class SqliteMarketIndex:
    """observations.jsonl（canonical）から再構築可能な検索index。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- 取込・再構築

    def index_observations(self, observations: Iterable[Observation]) -> int:
        rows = [(
            o.observation_id, o.series_id, o.trading_date,
            o.as_of.isoformat(), None if o.value is None else str(o.value),
            o.unit, o.currency, o.kind.value, o.metric, o.source_id,
            o.revision_of or "",
        ) for o in observations]
        before = self._conn.total_changes
        self._conn.executemany(
            "INSERT OR IGNORE INTO observations "
            "(observation_id, series_id, trading_date, as_of_utc, value, unit, currency,"
            " kind, metric, source_id, revision_of, seq) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,"
            " (SELECT COALESCE(MAX(seq),0)+1 FROM observations))",
            rows,
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def index_assessments(self, assessments: Iterable[EvidenceAssessment]) -> int:
        rows = [(
            a.assessment_id, a.record_id, a.decision.value,
            a.policy_name, a.policy_version, a.assessed_at.isoformat(),
        ) for a in assessments]
        before = self._conn.total_changes
        self._conn.executemany(
            "INSERT OR IGNORE INTO assessments "
            "(assessment_id, record_id, decision, policy_name, policy_version, assessed_at, seq) "
            "VALUES (?,?,?,?,?,?, (SELECT COALESCE(MAX(seq),0)+1 FROM assessments))",
            rows,
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def rebuild(
        self,
        observations: Iterable[Observation],
        assessments: Iterable[EvidenceAssessment] = (),
    ) -> Tuple[int, int]:
        """空から全再構築（index破損時の復旧経路。canonicalが常に正）。"""
        self._conn.execute("DELETE FROM observations")
        self._conn.execute("DELETE FROM assessments")
        self._conn.commit()
        return self.index_observations(observations), self.index_assessments(assessments)

    # ------------------------------------------------------------- クエリ

    def _rows(self, sql: str, params: Sequence) -> List[sqlite3.Row]:
        self._conn.row_factory = sqlite3.Row
        return list(self._conn.execute(sql, tuple(params)))

    def query(
        self,
        *,
        series_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        source_id: Optional[str] = None,
        kind: Optional[str] = None,
        decision: Optional[str] = None,
        current_only: bool = True,
        limit: int = 10000,
    ) -> List[sqlite3.Row]:
        """観測の検索。current_only=True は改定解決済み（旧版を除く）。

        decision指定時はQA最新判定（record別・追記順の末尾）でフィルタする。
        """
        where = ["1=1"]
        params: List = []
        if series_id:
            where.append("o.series_id = ?"); params.append(series_id)
        if date_from:
            where.append("o.trading_date >= ?"); params.append(date_from)
        if date_to:
            where.append("o.trading_date <= ?"); params.append(date_to)
        if source_id:
            where.append("o.source_id = ?"); params.append(source_id)
        if kind:
            where.append("o.kind = ?"); params.append(kind)
        if current_only:
            where.append(_NOT_SUPERSEDED)
        if decision:
            where.append(
                "(SELECT a.decision FROM assessments a WHERE a.record_id = o.observation_id "
                " ORDER BY a.seq DESC LIMIT 1) = ?")
            params.append(decision)
        sql = (f"SELECT o.* FROM observations o WHERE {' AND '.join(where)} "
               f"ORDER BY o.series_id, o.trading_date, o.seq LIMIT ?")
        params.append(limit)
        return self._rows(sql, params)

    def latest_trading_session(self, series_id: str, *, kind: str = "raw") -> Optional[sqlite3.Row]:
        """LATEST = 最新**取引セッション日**の現在有効値（改定解決済み）。"""
        rows = self._rows(
            f"SELECT o.* FROM observations o WHERE o.series_id = ? AND o.kind = ? "
            f"AND {_NOT_SUPERSEDED} ORDER BY o.trading_date DESC, o.seq DESC LIMIT 1",
            (series_id, kind))
        return rows[0] if rows else None

    def latest_as_of(self, series_id: str, *, kind: str = "raw") -> Optional[sqlite3.Row]:
        """LATEST = as_of時刻が最新の現在有効値（セッション日基準と使い分ける）。"""
        rows = self._rows(
            f"SELECT o.* FROM observations o WHERE o.series_id = ? AND o.kind = ? "
            f"AND {_NOT_SUPERSEDED} ORDER BY o.as_of_utc DESC, o.seq DESC LIMIT 1",
            (series_id, kind))
        return rows[0] if rows else None

    def latest_revision_for(self, series_id: str, trading_date: str) -> Optional[sqlite3.Row]:
        """ある(series, セッション日)の最新改定版（旧値はcurrent_only=Falseで参照可能）。"""
        rows = self._rows(
            f"SELECT o.* FROM observations o WHERE o.series_id = ? AND o.trading_date = ? "
            f"AND {_NOT_SUPERSEDED} ORDER BY o.seq DESC LIMIT 1",
            (series_id, trading_date))
        return rows[0] if rows else None

    def search_market(self, query) -> List[sqlite3.Row]:
        """MarketQuery（databank/query.py・P2-F拡張）の実行。

        series / instrument / metric / as_of範囲 / trading_date範囲 / kind /
        source / 最新QA判定 / 改定解決 / series毎最新セッション をAND結合。
        """
        where = ["1=1"]
        params: List = []
        if query.series_id:
            where.append("o.series_id = ?"); params.append(query.series_id)
        if query.instrument_id:
            where.append("o.series_id LIKE ?"); params.append(f"{query.instrument_id}.%")
        if query.metric:
            where.append("o.metric = ?"); params.append(query.metric)
        if query.date_from:
            where.append("o.as_of_utc >= ?"); params.append(query.date_from.isoformat())
        if query.date_to:
            where.append("o.as_of_utc <= ?"); params.append(query.date_to.isoformat())
        if query.trading_date_from:
            where.append("o.trading_date >= ?"); params.append(query.trading_date_from)
        if query.trading_date_to:
            where.append("o.trading_date <= ?"); params.append(query.trading_date_to)
        if query.kinds:
            marks = ",".join("?" for _ in query.kinds)
            where.append(f"o.kind IN ({marks})"); params.extend(query.kinds)
        if query.source_id:
            where.append("o.source_id = ?"); params.append(query.source_id)
        if query.current_only:
            where.append(_NOT_SUPERSEDED)
        if query.qa_decision:
            where.append(
                "(SELECT a.decision FROM assessments a WHERE a.record_id = o.observation_id "
                " ORDER BY a.seq DESC LIMIT 1) = ?")
            params.append(query.qa_decision)
        sql = (f"SELECT o.* FROM observations o WHERE {' AND '.join(where)} "
               f"ORDER BY o.series_id, o.trading_date, o.seq LIMIT ?")
        params.append(int(query.limit) if not query.latest_session_only else 1000000)
        rows = self._rows(sql, params)
        if query.latest_session_only:
            latest: Dict[str, sqlite3.Row] = {}
            for row in rows:  # trading_date昇順→最後が最新セッション
                latest[row["series_id"]] = row
            rows = list(latest.values())[: int(query.limit)]
        return rows

    def revision_chain(self, series_id: str, trading_date: str) -> List[sqlite3.Row]:
        """(series, セッション日)の全版（旧→新。改定履歴の監査用）。"""
        return self._rows(
            "SELECT o.* FROM observations o WHERE o.series_id = ? AND o.trading_date = ? "
            "ORDER BY o.seq", (series_id, trading_date))

    def count_by_series(self) -> Dict[str, int]:
        return {row["series_id"]: row["n"] for row in self._rows(
            "SELECT series_id, COUNT(*) AS n FROM observations GROUP BY series_id", ())}


class MarketBankStore:
    """Market Data Bank全体（raw / canonical / QA / index / run manifest）。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        serialization.register_domain_types()
        self.raw = JsonlRawRepository(self.root / "raw")
        self.normalized = JsonlNormalizedStore(self.root / "normalized")
        self.qa = JsonlAssessmentStore(self.root / "evidence_qa")
        self.index = SqliteMarketIndex(self.root / "index" / "market.sqlite3")
        self._runs_path = self.root / "backfill_runs.jsonl"

    def close(self) -> None:
        self.index.close()

    # ------------------------------------------------------------- provider provenance

    def record_provider_fetch(
        self, result: ProviderFetchResult, attempt_id: str
    ) -> Tuple[str, Optional[str]]:
        """provider応答の生CSVをblob保存し、FetchAttempt＋RawItemを記録する。

        戻り値: (fetch_attempt_id, raw_item_id or None)。
        失敗応答もFetchAttemptとして必ず記録する（P1-C原則）。
        """
        raw_item_id: Optional[str] = None
        content_hash = ""
        body_size = 0
        if result.body:
            content_hash, locator, _created = self.raw.store_body(result.body)
            body_size = len(result.body)
            if not result.error_kind:
                raw_item_id = RawItem.make_id(result.provider_id, result.url, content_hash)
                existing = self.raw.get_raw_item(raw_item_id)
                if existing is not None:
                    if result.served_from_cache:
                        # run内キャッシュ由来＝**新規のネットワーク取得は起きていない**。
                        # 起きていない取得をFetchAttemptとして記録しない（捏造しない）。
                        # 同一source documentから複数系列のObservationを作る正規経路
                        # （ONE SOURCE DOCUMENT MAY PRODUCE MULTIPLE OBSERVATIONS）で、
                        # provenanceは初回のRawItem/FetchAttemptを共有する。
                        return existing.fetch_attempt_id or attempt_id, raw_item_id
                    # 同一内容の再取得: 既存RawItem（初回provenance）を保持し追記しない。
                    # 今回の試行自体は下のFetchAttemptとして必ず記録される。
                    self.raw.add_attempt(self._attempt_for(
                        result, attempt_id, content_hash, body_size, raw_item_id))
                    return attempt_id, raw_item_id
                self.raw.add_raw_item(RawItem(
                    raw_item_id=raw_item_id,
                    source_id=result.provider_id,
                    locator=result.url,
                    retrieved_at=result.retrieved_at,
                    media_type=result.media_type,
                    content_hash=content_hash,
                    size_bytes=body_size,
                    storage_ref=locator,
                    endpoint_id=f"{result.provider_id}:{result.symbol}",
                    fetch_attempt_id=attempt_id,
                ))
        self.raw.add_attempt(self._attempt_for(
            result, attempt_id, content_hash, body_size, raw_item_id))
        return attempt_id, raw_item_id

    @staticmethod
    def _attempt_for(
        result: ProviderFetchResult, attempt_id: str, content_hash: str,
        body_size: int, raw_item_id: Optional[str],
    ) -> FetchAttempt:
        return FetchAttempt(
            attempt_id=attempt_id,
            source_id=result.provider_id,
            endpoint_id=f"{result.provider_id}:{result.symbol}",
            url=result.url,
            requested_at=result.retrieved_at,
            elapsed_ms=result.elapsed_ms,
            status_code=result.status_code,
            final_url=result.url,
            content_type=result.media_type if result.body else "",
            body_size=body_size,
            content_hash=content_hash,
            raw_item_id=raw_item_id or "",
            error_kind=result.error_kind if result.error_kind in (
                "", "timeout", "dns", "tls", "connection", "protocol", "unknown") else "protocol",
            error_detail=result.error_detail,
        )

    # ------------------------------------------------------------- canonical

    def add_observations(self, observations: Sequence[Observation]) -> int:
        added = self.normalized.add_observations(observations)
        self.index.index_observations(observations)
        return added

    def add_assessment(self, assessment: EvidenceAssessment) -> None:
        self.qa.add_assessment(assessment)
        self.index.index_assessments([assessment])

    def observations_for_series(self, series_id: str) -> Tuple[Observation, ...]:
        return tuple(o for o in self.normalized.iter_observations()
                     if o.series_id == series_id)

    def current_by_date(self, series_id: str) -> Dict[str, Observation]:
        """(trading_date → 現在有効Observation)。ingestの改定検出入力。"""
        current = latest_revisions(self.observations_for_series(series_id))
        return {o.trading_date: o for o in current if o.trading_date}

    # ------------------------------------------------------------- run manifest

    def add_run(self, run) -> None:
        import json as _json
        import os as _os
        line = _json.dumps(serialization.encode(run), ensure_ascii=False)
        with self._runs_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            _os.fsync(f.fileno())

    def iter_runs(self):
        import json as _json
        if not self._runs_path.exists():
            return
        with self._runs_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield serialization.decode(_json.loads(line))
                except (ValueError, TypeError, KeyError):
                    continue  # 末尾破損行はrun manifestでも読み飛ばす
