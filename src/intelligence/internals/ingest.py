"""Market Internals の J-Quants Light 取得（Phase 3.5 §3 / §4 / §28）。

既存の `JQuantsV2Client`（FAIL-CLOSED・credential runtime injection）と
`JQuantsLightStore`（canonical JSONL + SQLite）を**そのまま**使う。新しい保管系統・
新しいcredentialを作らない。Standard / Premium 限定endpointへは接続しない。

取得モード:
- date mode : `/equities/bars/daily?date=YYYY-MM-DD`（1 session = 1リクエストで全銘柄）。
  Light契約で使えるかは**実応答で判定**する（推測しない）。
- code mode : `?code=...`（P2-Hで実証済み）。date modeが使えない場合の**限定sample**
  （universeを再現できないため、そのFactは LIMITED_USE になる）。

全リクエストは間隔（`request_interval_seconds`）を空け、回数を記録する。
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..market.jquants_light_datasets import get_dataset
from ..market.jquants_light_store import JQuantsLightStore
from ..market.jquants_records import PARSERS
from ..market.jquants_v2_client import JQuantsFetchResult, JQuantsV2Client
from ..market.p2h_light_pilot import _provenance, _store_raw

DATE_MODE = "date"
CODE_MODE = "code"
MODE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, kw_only=True)
class FetchOutcome:
    dataset: str
    mode: str
    params: Mapping[str, str]
    ok: bool
    http: int
    error_kind: str = ""
    error_detail: str = ""
    entitlement: str = ""
    rows: int = 0
    pages: int = 0
    added: int = 0
    elapsed_ms: int = 0
    raw_bytes: int = 0

    def as_dict(self) -> Dict[str, object]:
        return {
            "dataset": self.dataset, "mode": self.mode, "params": dict(self.params),
            "ok": self.ok, "http": self.http, "error_kind": self.error_kind,
            "error_detail": self.error_detail[:160], "entitlement": self.entitlement,
            "rows": self.rows, "pages": self.pages, "added": self.added,
            "elapsed_ms": self.elapsed_ms, "raw_bytes": self.raw_bytes,
        }


@dataclass
class IngestStats:
    requests: int = 0
    rows_downloaded: int = 0
    rows_added: int = 0
    raw_bytes: int = 0
    elapsed_ms: int = 0
    outcomes: List[FetchOutcome] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {"requests": self.requests, "rows_downloaded": self.rows_downloaded,
                "rows_added": self.rows_added, "raw_bytes": self.raw_bytes,
                "elapsed_ms": self.elapsed_ms, "fetches": len(self.outcomes)}


class InternalsIngestor:
    """fetch → raw → parse → canonical → index を1 datasetずつ行う（P2-Hと同じ経路）。"""

    def __init__(self, client: JQuantsV2Client, store: JQuantsLightStore, *,
                 interval_seconds: float = 0.3,
                 sleeper: Callable[[float], None] = _time.sleep,
                 attempt_prefix: str = "p35") -> None:
        self.client = client
        self.store = store
        self.interval = float(interval_seconds)
        self._sleep = sleeper
        self._prefix = attempt_prefix
        self._seq = 0
        self.stats = IngestStats()

    def ingest(self, key: str, params: Optional[Mapping[str, str]] = None, *,
               mode: str = "") -> FetchOutcome:
        spec = get_dataset(key)
        self._seq += 1
        attempt_id = f"{self._prefix}_{self._seq:04d}"
        before = self.client.request_count
        if self._seq > 1 and self.interval > 0:
            self._sleep(self.interval)
        result: JQuantsFetchResult = self.client.fetch(
            key, spec.path, dict(params or {}), required_fields=spec.required_fields)
        added = 0
        if result.ok and spec.ingestion_owner == "jquants_light":
            raw_item_id = _store_raw(self.store, result, attempt_id)
            provenance = _provenance(spec.path, result, raw_item_id, attempt_id)
            parse = PARSERS[key]
            records = [r for r in (parse(row, provenance) for row in result.rows)
                       if r is not None]
            added = self.store.append(key, records)
        outcome = FetchOutcome(
            dataset=key, mode=mode or ("date" if "date" in (params or {}) else
                                       "code" if "code" in (params or {}) else "range"),
            params=dict(params or {}), ok=result.ok, http=result.status_code,
            error_kind=result.error_kind, error_detail=result.error_detail,
            entitlement=result.entitlement, rows=len(result.rows), pages=result.pages,
            added=added, elapsed_ms=result.elapsed_ms, raw_bytes=len(result.raw_body))
        self.stats.requests += self.client.request_count - before
        self.stats.rows_downloaded += outcome.rows
        self.stats.rows_added += added
        self.stats.raw_bytes += outcome.raw_bytes
        self.stats.elapsed_ms += outcome.elapsed_ms
        self.stats.outcomes.append(outcome)
        return outcome


def fetch_calendar(ing: InternalsIngestor, start: date, end: date) -> FetchOutcome:
    return ing.ingest("markets_calendar",
                      {"from": start.isoformat(), "to": end.isoformat()}, mode="range")


def fetch_master(ing: InternalsIngestor, effective_date: str = "") -> FetchOutcome:
    params = {"date": effective_date} if effective_date else {}
    return ing.ingest("listed_master", params, mode=DATE_MODE if effective_date else "snapshot")


def fetch_investor_types(ing: InternalsIngestor, start: date, end: date) -> FetchOutcome:
    return ing.ingest("investor_types",
                      {"from": start.isoformat(), "to": end.isoformat()}, mode="range")


def fetch_daily_bars_by_date(ing: InternalsIngestor, session_date: str) -> FetchOutcome:
    return ing.ingest("daily_bars", {"date": session_date}, mode=DATE_MODE)


def fetch_daily_bars_by_code(ing: InternalsIngestor, code: str, start: date, end: date
                             ) -> FetchOutcome:
    return ing.ingest("daily_bars", {"code": code, "from": start.isoformat(),
                                     "to": end.isoformat()}, mode=CODE_MODE)


def detect_date_mode(ing: InternalsIngestor, session_date: str) -> Tuple[str, FetchOutcome]:
    """date指定取得が使えるかを**実応答**で判定する（credential無しなら unavailable）。"""
    outcome = fetch_daily_bars_by_date(ing, session_date)
    if outcome.ok and outcome.rows > 0:
        return DATE_MODE, outcome
    return MODE_UNAVAILABLE, outcome


def fetch_sessions_by_date(ing: InternalsIngestor, sessions: Sequence[str],
                           already: Sequence[str] = ()) -> List[FetchOutcome]:
    """sessionごとに全銘柄を取る（既に取得済みのsessionは再取得しない）。"""
    done = set(already)
    out: List[FetchOutcome] = []
    for session in sessions:
        if session in done:
            continue
        out.append(fetch_daily_bars_by_date(ing, session))
    return out


def select_sample_codes(master_rows: Sequence[Mapping], size: int) -> List[str]:
    """code modeのfallback用: 業種×規模が散るように決定論的に選ぶ（乱数なし）。"""
    buckets: Dict[Tuple[str, str], List[str]] = {}
    for row in master_rows:
        code = str(row["code"] if "code" in row.keys() else row.get("Code", ""))
        if not code:
            continue
        s33 = str(row["sector33_code"] if "sector33_code" in row.keys() else row.get("S33", ""))
        scale = str(row["scale_category"] if "scale_category" in row.keys()
                    else row.get("ScaleCat", ""))
        buckets.setdefault((s33, scale), []).append(code)
    chosen: List[str] = []
    while len(chosen) < size and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key]:
                chosen.append(sorted(buckets[key]).pop(0))
                buckets[key].remove(chosen[-1])
            if len(chosen) >= size:
                break
    return chosen


def window_dates(end: date, calendar_days: int) -> Tuple[date, date]:
    return end - timedelta(days=calendar_days), end
