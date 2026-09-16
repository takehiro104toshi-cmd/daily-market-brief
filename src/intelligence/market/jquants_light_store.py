"""J-Quants Light core の永続化とquery（Phase 2-H STEP 13/14）。

既存Data Bank規律を維持する:
- canonical: **JSONL append-only**（監査可能・履歴を上書きしない）
- operational: **SQLite（再構築可能）**——canonicalから何度でも作り直せる
- 生応答は既存の `JsonlRawRepository`（blob＋RawItem＋FetchAttempt）へ保存し、
  raw provenanceを共有する（P2-Hで別系統のraw保管を作らない）
- 大量データをGitへcommitしない（保存先は INTELLIGENCE_DATA_ROOT 配下）

冪等性: record_idが同一なら追記しない（再実行しても増えない）。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from ..ingestion.raw_store import JsonlRawRepository

#: canonical JSONLのファイル名（dataset key → ファイル）
CANONICAL_FILES = {
    "listed_master": "security_master.jsonl",
    "daily_bars": "daily_prices.jsonl",
    "fins_summary": "financial_summaries.jsonl",
    "equities_earnings_cal": "earnings_schedule.jsonl",
    "markets_calendar": "trading_calendar.jsonl",
    "investor_types": "investor_type_flows.jsonl",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS securities (
  record_id TEXT PRIMARY KEY, security_id TEXT, code TEXT, company_name TEXT,
  company_name_en TEXT, market_code TEXT, market_name TEXT,
  sector17_code TEXT, sector17_name TEXT, sector33_code TEXT, sector33_name TEXT,
  scale_category TEXT, effective_date TEXT, listing_status TEXT, api_version TEXT);
CREATE INDEX IF NOT EXISTS ix_sec_code ON securities(code);
CREATE INDEX IF NOT EXISTS ix_sec_name ON securities(company_name);
CREATE INDEX IF NOT EXISTS ix_sec_s33 ON securities(sector33_code);

CREATE TABLE IF NOT EXISTS daily_prices (
  record_id TEXT PRIMARY KEY, security_id TEXT, code TEXT, trading_date TEXT,
  close TEXT, adjusted_close TEXT, adjustment_factor TEXT, volume TEXT,
  turnover_value TEXT, market_cap TEXT, api_version TEXT);
CREATE INDEX IF NOT EXISTS ix_px_code_date ON daily_prices(code, trading_date);
CREATE INDEX IF NOT EXISTS ix_px_date ON daily_prices(trading_date);

CREATE TABLE IF NOT EXISTS financial_summaries (
  record_id TEXT PRIMARY KEY, security_id TEXT, code TEXT, disclosed_date TEXT,
  period_type TEXT, period_end TEXT, net_sales TEXT, operating_profit TEXT,
  ordinary_profit TEXT, net_profit TEXT, eps TEXT, bps TEXT, roe TEXT,
  forecast_net_sales TEXT, forecast_operating_profit TEXT, forecast_net_profit TEXT,
  forecast_eps TEXT, api_version TEXT);
CREATE INDEX IF NOT EXISTS ix_fin_code_date ON financial_summaries(code, disclosed_date);

CREATE TABLE IF NOT EXISTS earnings_schedule (
  record_id TEXT PRIMARY KEY, security_id TEXT, code TEXT, announcement_date TEXT,
  company_name TEXT, fiscal_quarter TEXT, fiscal_year TEXT, section TEXT,
  api_version TEXT);
CREATE INDEX IF NOT EXISTS ix_ern_date ON earnings_schedule(announcement_date);
CREATE INDEX IF NOT EXISTS ix_ern_code ON earnings_schedule(code);

CREATE TABLE IF NOT EXISTS trading_calendar (
  record_id TEXT PRIMARY KEY, calendar_date TEXT, holiday_division TEXT,
  api_version TEXT);
CREATE INDEX IF NOT EXISTS ix_cal_date ON trading_calendar(calendar_date);

CREATE TABLE IF NOT EXISTS investor_type_flows (
  record_id TEXT PRIMARY KEY, section TEXT, published_date TEXT,
  period_start TEXT, period_end TEXT, frequency TEXT, flows_json TEXT,
  api_version TEXT);
CREATE INDEX IF NOT EXISTS ix_flow_period ON investor_type_flows(period_end);
"""

#: record種別 → (table, 列名, record属性名)
_TABLES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "listed_master": ("securities", (
        "record_id", "security_id", "code", "company_name", "company_name_en",
        "market_code", "market_name", "sector17_code", "sector17_name",
        "sector33_code", "sector33_name", "scale_category", "effective_date",
        "listing_status")),
    "daily_bars": ("daily_prices", (
        "record_id", "security_id", "code", "trading_date", "close",
        "adjusted_close", "adjustment_factor", "volume", "turnover_value",
        "market_cap")),
    "fins_summary": ("financial_summaries", (
        "record_id", "security_id", "code", "disclosed_date", "period_type",
        "period_end", "net_sales", "operating_profit", "ordinary_profit",
        "net_profit", "eps", "bps", "roe", "forecast_net_sales",
        "forecast_operating_profit", "forecast_net_profit", "forecast_eps")),
    "equities_earnings_cal": ("earnings_schedule", (
        "record_id", "security_id", "code", "announcement_date", "company_name",
        "fiscal_quarter", "fiscal_year", "section")),
    "markets_calendar": ("trading_calendar", (
        "record_id", "calendar_date", "holiday_division")),
    "investor_types": ("investor_type_flows", (
        "record_id", "section", "published_date", "period_start", "period_end",
        "frequency")),
}


def _record_to_dict(record) -> Dict:
    data = asdict(record) if is_dataclass(record) else dict(record)
    provenance = data.pop("provenance", None)
    if provenance is not None:
        data["provenance"] = provenance
    data["record_id"] = record.record_id
    return data


class JQuantsLightStore:
    """canonical JSONL（append-only）＋ 再構築可能なSQLite index。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.canonical_dir = self.root / "canonical"
        self.canonical_dir.mkdir(parents=True, exist_ok=True)
        self.raw = JsonlRawRepository(self.root / "raw")
        self.db_path = self.root / "index" / "jquants_light.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._seen: Dict[str, set] = {}

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- canonical

    def _path(self, dataset: str) -> Path:
        return self.canonical_dir / CANONICAL_FILES[dataset]

    def _existing_ids(self, dataset: str) -> set:
        if dataset in self._seen:
            return self._seen[dataset]
        ids = set()
        path = self._path(dataset)
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ids.add(json.loads(line).get("record_id", ""))
                    except json.JSONDecodeError:
                        continue      # 破損行は数えるだけ（rebuildで検出する）
        self._seen[dataset] = ids
        return ids

    def append(self, dataset: str, records: Sequence) -> int:
        """canonicalへ追記（record_id重複は追記しない＝冪等）。戻り値は新規件数。"""
        if dataset not in CANONICAL_FILES:
            raise ValueError(f"unknown dataset: {dataset}")
        known = self._existing_ids(dataset)
        added = 0
        path = self._path(dataset)
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                rid = record.record_id
                if rid in known:
                    continue
                handle.write(json.dumps(_record_to_dict(record),
                                        ensure_ascii=False, default=str) + "\n")
                known.add(rid)
                added += 1
        if added:
            self._index(dataset, records)
        return added

    def iter_canonical(self, dataset: str) -> Iterator[Dict]:
        path = self._path(dataset)
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

    # ------------------------------------------------------------- index

    def _index(self, dataset: str, records: Iterable) -> None:
        table, columns = _TABLES[dataset]
        rows = []
        for record in records:
            data = _record_to_dict(record)
            values = [data.get(c, "") for c in columns]
            api_version = (data.get("provenance") or {}).get("api_version", "")
            if dataset == "investor_types":
                rows.append(values + [json.dumps(data.get("flows", {}),
                                                 ensure_ascii=False), api_version])
            else:
                rows.append(values + [api_version])
        extra = ["flows_json", "api_version"] if dataset == "investor_types" else ["api_version"]
        cols = list(columns) + extra
        placeholders = ",".join("?" * len(cols))
        self._conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
            rows)
        self._conn.commit()

    def rebuild_index(self) -> Dict[str, int]:
        """SQLiteをcanonicalから**作り直す**（operationalは常に再構築可能）。"""
        counts: Dict[str, int] = {}
        for dataset, (table, columns) in _TABLES.items():
            self._conn.execute(f"DELETE FROM {table}")
            extra = ["flows_json", "api_version"] if dataset == "investor_types" else ["api_version"]
            cols = list(columns) + extra
            placeholders = ",".join("?" * len(cols))
            rows = []
            for data in self.iter_canonical(dataset):
                values = [data.get(c, "") for c in columns]
                api_version = (data.get("provenance") or {}).get("api_version", "")
                if dataset == "investor_types":
                    rows.append(values + [json.dumps(data.get("flows", {}),
                                                     ensure_ascii=False), api_version])
                else:
                    rows.append(values + [api_version])
            if rows:
                self._conn.executemany(
                    f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) "
                    f"VALUES ({placeholders})", rows)
            counts[dataset] = len(rows)
        self._conn.commit()
        return counts

    def count(self, dataset: str) -> int:
        table, _ = _TABLES[dataset]
        return self._conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]

    # ------------------------------------------------------------- query（STEP 14）

    def _rows(self, sql: str, params: Sequence = ()) -> List[sqlite3.Row]:
        return list(self._conn.execute(sql, params))

    def security_by_code(self, code: str) -> Optional[sqlite3.Row]:
        rows = self._rows(
            "SELECT * FROM securities WHERE code=? ORDER BY effective_date DESC LIMIT 1",
            (code,))
        return rows[0] if rows else None

    def securities_by_company_name(self, fragment: str, limit: int = 20) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM securities WHERE company_name LIKE ? "
            "ORDER BY code LIMIT ?", (f"%{fragment}%", limit))

    def price_history(self, code: str, *, start: str = "", end: str = "",
                      limit: int = 10000) -> List[sqlite3.Row]:
        sql = "SELECT * FROM daily_prices WHERE code=?"
        params: List = [code]
        if start:
            sql += " AND trading_date>=?"
            params.append(start)
        if end:
            sql += " AND trading_date<=?"
            params.append(end)
        sql += " ORDER BY trading_date LIMIT ?"
        params.append(limit)
        return self._rows(sql, params)

    def latest_price(self, code: str) -> Optional[sqlite3.Row]:
        rows = self._rows(
            "SELECT * FROM daily_prices WHERE code=? ORDER BY trading_date DESC LIMIT 1",
            (code,))
        return rows[0] if rows else None

    def financials_for_security(self, code: str, limit: int = 50) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM financial_summaries WHERE code=? "
            "ORDER BY disclosed_date DESC LIMIT ?", (code, limit))

    def latest_company_forecast(self, code: str) -> Optional[sqlite3.Row]:
        """最新開示のうち**会社予想が入っている**ものを返す（実績のみの開示は除く）。"""
        rows = self._rows(
            "SELECT * FROM financial_summaries WHERE code=? "
            "AND (forecast_net_sales<>'' OR forecast_operating_profit<>'' "
            "     OR forecast_net_profit<>'' OR forecast_eps<>'') "
            "ORDER BY disclosed_date DESC LIMIT 1", (code,))
        return rows[0] if rows else None

    def earnings_within(self, start: str, end: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM earnings_schedule WHERE announcement_date>=? "
            "AND announcement_date<=? ORDER BY announcement_date, code", (start, end))

    def calendar_range(self, start: str, end: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM trading_calendar WHERE calendar_date>=? "
            "AND calendar_date<=? ORDER BY calendar_date", (start, end))

    def investor_flows_for_period(self, start: str, end: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM investor_type_flows WHERE period_end>=? "
            "AND period_end<=? ORDER BY period_end, section", (start, end))

    # ------------------------------------------------- Phase 3.5 market internals

    def prices_on(self, trading_date: str) -> List[sqlite3.Row]:
        """1営業日の全銘柄価格（breadth集計の入力）。"""
        return self._rows(
            "SELECT * FROM daily_prices WHERE trading_date=? ORDER BY code",
            (trading_date,))

    def price_dates(self) -> List[str]:
        return [r["trading_date"] for r in self._rows(
            "SELECT DISTINCT trading_date FROM daily_prices ORDER BY trading_date")]

    def security_effective_dates(self) -> List[str]:
        return [r["effective_date"] for r in self._rows(
            "SELECT DISTINCT effective_date FROM securities ORDER BY effective_date")]

    def securities_effective(self, effective_date: str) -> List[sqlite3.Row]:
        return self._rows(
            "SELECT * FROM securities WHERE effective_date=? ORDER BY code",
            (effective_date,))

    def investor_flows_published_by(self, published_date: str,
                                    section: str = "") -> List[sqlite3.Row]:
        """公表日が `published_date` 以前のflow（新しい公表順）。look-ahead防止の入力。"""
        sql = "SELECT * FROM investor_type_flows WHERE published_date<=?"
        params: List = [published_date]
        if section:
            sql += " AND section=?"
            params.append(section)
        sql += " ORDER BY published_date DESC, period_end DESC, section"
        return self._rows(sql, params)
