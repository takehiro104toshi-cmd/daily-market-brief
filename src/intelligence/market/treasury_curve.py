"""U.S. Treasury「Daily Treasury Par Yield Curve Rates」provider（Phase 2-G / PRIMARY_OFFICIAL）。

series identity（docs/databank/OFFICIAL_RATE_SERIES_SPEC.md）:
- 米財務省が日次公表するpar yield curve（流通市場のindicative bid quotes
  ——NY連銀取得・15:30 ET頃——から財務省が補間したconstant maturity par yield）。
- **市場実勢利回りindex（^TNX等）・入札結果yield・2年note価格・2Y ETF・
  futures implied利回りとは別概念**——これらで代用しない（NO PROXY SUBSTITUTION）。
- カタログ上は rates:UST2Y_par / rates:UST10Y_par の**独立series**とし、
  既存 rates:UST10Y（yfinance ^TNX・市場実勢系）と混ぜない（NO SILENT MIXING）。

実装方針:
- CSVエンドポイントは暦年単位（daily-treasury-rates.csv/{year}/all&_format=csv）。
  要求期間が複数年へ跨る場合は年ファイルを各1リクエストで取得し、応答bytesを
  改行連結してraw保存する（連結の事実はparse_issuesへ申告——捏造ではなく
  取得順の生payload列。ヘッダ行の繰り返しはparserが処理する）。
- 日付はMM/DD/YYYY → ISOへ決定論変換。値はstringトークンのまま
  （Decimal化はingest側・float非経由）。空欄/N/Aは欠測。
- 対象年限列（"2 Yr" / "10 Yr"）はcatalog symbolでヘッダ照合（列位置を仮定しない）。
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import List, Tuple

from ..ingestion.model import FetchRequest
from ..ingestion.transport import DEFAULT_TIMEOUT, HttpTransport, redact_url
from .providers import ProviderFetchResult, ProviderRecord
from .series_catalog import SeriesSpec

TREASURY_PROVIDER_ID = "treasury_gov"

#: 暦年別CSV（Daily Treasury Par Yield Curve Rates）
TREASURY_YEAR_CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)

#: P2-G probe実測: 連絡先入りのfair-access UAで200/text/csvが返る（run #6）。
#: 政府サイトにはブラウザ偽装ではなく正直なUAを使う。
TREASURY_USER_AGENT = (
    "daily-market-brief-vnext/0.2 "
    "(+https://github.com/takehiro104toshi-cmd/daily-market-brief)"
)


def _norm(name: str) -> str:
    return " ".join(name.replace('"', "").split()).strip().lower()


def parse_treasury_par_yield_csv(
    body: bytes, column: str
) -> Tuple[Tuple[ProviderRecord, ...], Tuple[str, ...]]:
    """Treasury日次par yield CSV → (records, issues)。

    - ヘッダ駆動（Date列＋対象年限列を名前で照合。年により列構成が異なる）。
    - 複数年ファイル連結入力に対応（Dateヘッダ行の再出現はスキップ）。
    - 不正日付・列不足行はskipしissueへ記録（黙って捨てない）。
    """
    issues: List[str] = []
    try:
        text = body.decode("utf-8-sig", errors="replace")
    except Exception:  # noqa: BLE001
        return (), ("body_decode_failed",)
    if not text.strip():
        return (), ("empty_body",)

    target = _norm(column)
    records: List[ProviderRecord] = []
    date_idx = None
    col_idx = None
    header_seen = False
    for line_no, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        normed = [_norm(cell) for cell in row]
        if "date" in normed:
            # ヘッダ行（連結ファイルでは複数回出現し得る——年により列構成が変わる）
            header_seen = True
            date_idx = normed.index("date")
            col_idx = normed.index(target) if target in normed else None
            if col_idx is None:
                issues.append(f"line{line_no}:missing_column:{column}")
            continue
        if not header_seen or date_idx is None:
            snippet = "".join(c for c in ",".join(row)[:80] if c.isprintable())
            return (), ("missing_header_row", f"body_head={snippet}")
        if col_idx is None:
            continue  # このブロックのヘッダに対象列が無い（issue記録済み）
        raw_date = row[date_idx].strip() if date_idx < len(row) else ""
        try:
            month, day, year = raw_date.split("/")
            iso = date(int(year), int(month), int(day)).isoformat()
        except (ValueError, IndexError):
            issues.append(f"line{line_no}:invalid_date:{raw_date[:20]}")
            continue
        token = row[col_idx].strip() if col_idx < len(row) else ""
        if token.upper() in ("N/A", "-", ""):
            token = ""
        records.append(ProviderRecord(trading_date=iso, close=token, line_no=line_no))
    if not header_seen:
        snippet = "".join(c for c in text.strip()[:80] if c.isprintable())
        return (), ("missing_header_row", f"body_head={snippet}")
    return tuple(records), tuple(issues)


class TreasuryParYieldProvider:
    """Daily Treasury Par Yield CurveのMarketDataProvider実装（年ファイル単位）。"""

    def __init__(self, transport: HttpTransport, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._transport = transport
        self._timeout = timeout

    @property
    def provider_id(self) -> str:
        return TREASURY_PROVIDER_ID

    def fetch_daily_history(
        self, spec: SeriesSpec, *, start: date, end: date
    ) -> ProviderFetchResult:
        symbol = spec.symbol_for(self.provider_id)
        now = datetime.now(timezone.utc)
        if not symbol:
            return ProviderFetchResult(
                provider_id=self.provider_id, series_id=spec.series_id, symbol="",
                url="", retrieved_at=now,
                error_kind="no_symbol", error_detail="catalogに本providerのsymbolなし")

        years = list(range(start.year, end.year + 1))
        bodies: List[bytes] = []
        issues: List[str] = []
        last_url = ""
        status = 0
        elapsed = 0
        retrieved_at = now
        for year in years:
            url = TREASURY_YEAR_CSV_URL.format(year=year)
            last_url = url
            request = FetchRequest(
                source_id=self.provider_id,
                endpoint_id=f"{self.provider_id}:{year}",
                url=url,
                headers=(("User-Agent", TREASURY_USER_AGENT),
                         ("Accept", "text/csv, text/plain;q=0.9, */*;q=0.5")),
                requested_at=now,
            )
            response = self._transport.send(request, timeout=self._timeout)
            status = response.status_code
            elapsed += response.elapsed_ms
            retrieved_at = response.retrieved_at
            if response.error_kind:
                return ProviderFetchResult(
                    provider_id=self.provider_id, series_id=spec.series_id,
                    symbol=symbol, url=redact_url(url), status_code=status,
                    retrieved_at=retrieved_at, elapsed_ms=elapsed,
                    error_kind=response.error_kind, error_detail=response.error_detail)
            if response.status_code != 200:
                return ProviderFetchResult(
                    provider_id=self.provider_id, series_id=spec.series_id,
                    symbol=symbol, url=redact_url(url), status_code=status,
                    retrieved_at=retrieved_at, elapsed_ms=elapsed, body=response.body,
                    error_kind="http_error", error_detail=f"HTTP {response.status_code}")
            bodies.append(response.body)

        body = b"\n".join(bodies)
        if len(bodies) > 1:
            issues.append("concatenated_year_files:" + ",".join(str(y) for y in years))
        records, parse_issues = parse_treasury_par_yield_csv(body, symbol)
        issues.extend(parse_issues)
        in_range = tuple(
            r for r in records if start.isoformat() <= r.trading_date <= end.isoformat())
        base = dict(
            provider_id=self.provider_id, series_id=spec.series_id, symbol=symbol,
            url=redact_url(last_url), status_code=status,
            retrieved_at=retrieved_at, elapsed_ms=elapsed, body=body)
        if not in_range:
            kind = "parse_error" if not records else "no_data"
            return ProviderFetchResult(
                **base, parse_issues=tuple(issues), error_kind=kind,
                error_detail=(";".join(issues)[:160] or "no rows in requested range"))
        return ProviderFetchResult(**base, records=in_range, parse_issues=tuple(issues))
