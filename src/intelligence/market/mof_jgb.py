"""財務省「国債金利情報」provider（Phase 2-G / PRIMARY_OFFICIAL）。

series identity（docs/databank/OFFICIAL_RATE_SERIES_SPEC.md）:
- 財務省が日次公表する国債金利（jgbcm CSV）。財務省の説明に基づき
  「固定利付国債の流通市場価格ベース・constant maturity・市場クローズ（15時）時点」
  の系列として扱う。
- **入札平均利回り・特定銘柄利回り・表面利率（クーポン）とは別物**——
  それらをJGB10Y日次系列として代用しない（NO PROXY SUBSTITUTION）。

実装方針:
- **2ファイル構成（P2-G probe実測）**: jgbcm_all.csv は1974年〜前月末まで、
  当月分は jgbcm.csv にのみ載る。両方を各1リクエストで取得し、応答bytesを
  改行連結してraw保存する（連結の事実はparse_issuesへ申告。ヘッダ再出現は
  parserが処理）。要求期間の行のみObservation化する。
- 日付は和暦（S49.9.24 / H31.4.30 / R8.8.3）→ ISOへ決定論変換。
  不正な日付トークンを持つデータ行はskipしissueへ記録（黙って捨てない）。
  タイトル行・注記行（「国債金利情報」「※…」）は構造行としてskipする。
- 値はstringトークンのまま（"-"は欠測）。Decimal化はingest側（float非経由）。
- 列は catalog symbol（例 "10年"）でヘッダ照合——列位置を仮定しない。
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Tuple

from ..ingestion.model import FetchRequest
from ..ingestion.transport import DEFAULT_TIMEOUT, HttpTransport, redact_url
from .providers import ProviderFetchResult, ProviderRecord
from .series_catalog import SeriesSpec

MOF_PROVIDER_ID = "mof_japan"

#: 全履歴CSV（財務省 国債金利情報。1974年〜**前月末**まで——probe実測）
MOF_JGBCM_ALL_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"
#: 当月分CSV（当月の営業日のみ——最新値はこちらにしか載らない）
MOF_JGBCM_CURRENT_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"

#: 政府系サイトはWAFで非ブラウザUAを拒否し得るため、Stooq providerと同系の
#: ブラウザ相当UA（連絡先識別子付き）を使う。P2-G probeで実測確認する。
MOF_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 market-brief-bot/1.0"
)

#: 和暦era → 西暦基準年（era元年 = base + 1）
_ERA_BASE = {"S": 1925, "H": 1988, "R": 2018}


def wareki_to_iso(token: str) -> str:
    """'R7.8.29' → '2025-08-29'。変換不能はValueError（呼び出し側でissue化）。"""
    text = token.strip()
    if not text or text[0].upper() not in _ERA_BASE:
        raise ValueError(f"unknown era: {token[:12]!r}")
    era = text[0].upper()
    parts = text[1:].split(".")
    if len(parts) != 3:
        raise ValueError(f"bad wareki format: {token[:12]!r}")
    year = _ERA_BASE[era] + int(parts[0])
    return date(year, int(parts[1]), int(parts[2])).isoformat()


def parse_mof_jgbcm_csv(
    body: bytes, column: str
) -> Tuple[Tuple[ProviderRecord, ...], Tuple[str, ...]]:
    """財務省jgbcm CSV（Shift_JIS・和暦日付）→ (records, issues)。

    - タイトル行（「国債金利情報 (令和8年8月)」）・注記行（「※…」）は構造行として
      skipする。「基準日」を含む行をヘッダとし、連結入力での再出現も処理する。
    - 対象年限列（例 '10年'）はヘッダ名で照合。'-' は欠測トークン。
    - 同一日付の再出現は後続をskip（全履歴＋当月ファイルの重複月対策——
      値が同じ前提を置かず、初出（全履歴側）を優先しissueへ記録する）。
    """
    issues = []
    try:
        text = body.decode("cp932", errors="replace")
    except Exception:  # noqa: BLE001
        return (), ("body_decode_failed",)
    if not text.strip():
        return (), ("empty_body",)

    records = []
    seen_dates = {}
    date_idx = None
    col_idx = None
    column_missing_reported = False
    for line_no, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        first = row[0].strip()
        if any("基準日" in cell for cell in row):
            header = [cell.strip() for cell in row]
            date_idx = next(i for i, name in enumerate(header) if "基準日" in name)
            col_idx = header.index(column) if column in header else None
            if col_idx is None and not column_missing_reported:
                issues.append(f"line{line_no}:missing_column:{column}")
                column_missing_reported = True
            continue
        if "国債金利情報" in first or first.startswith(("※", "(単位", "（単位")):
            continue  # タイトル・注記の構造行
        if date_idx is None:
            snippet = "".join(c for c in ",".join(row)[:80] if c.isprintable())
            return (), ("missing_header_row", f"body_head={snippet}")
        if col_idx is None:
            continue
        raw_date = row[date_idx].strip() if date_idx < len(row) else ""
        try:
            iso = wareki_to_iso(raw_date)
        except (ValueError, IndexError):
            issues.append(f"line{line_no}:invalid_wareki:{raw_date[:12]}")
            continue
        if iso in seen_dates:
            issues.append(f"duplicate_date_across_files:{iso}")
            continue
        seen_dates[iso] = line_no
        token = row[col_idx].strip() if col_idx < len(row) else ""
        if token in ("-", "－", "N/A"):
            token = ""
        records.append(ProviderRecord(trading_date=iso, close=token, line_no=line_no))
    if date_idx is None:
        snippet = "".join(c for c in text.strip()[:80] if c.isprintable())
        return (), ("missing_header_row", f"body_head={snippet}")
    return tuple(records), tuple(issues)


class MofJgbYieldProvider:
    """財務省国債金利のMarketDataProvider実装（全履歴＋当月CSVの2リクエスト）。"""

    def __init__(self, transport: HttpTransport, *, timeout: float = DEFAULT_TIMEOUT,
                 urls: Tuple[str, ...] = (MOF_JGBCM_ALL_URL, MOF_JGBCM_CURRENT_URL)) -> None:
        self._transport = transport
        self._timeout = timeout
        self._urls = urls

    @property
    def provider_id(self) -> str:
        return MOF_PROVIDER_ID

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
        bodies = []
        issues = []
        status = 0
        elapsed = 0
        retrieved_at = now
        last_url = ""
        for url in self._urls:
            last_url = url
            request = FetchRequest(
                source_id=self.provider_id,
                endpoint_id=f"{self.provider_id}:{url.rsplit('/', 1)[-1]}",
                url=url,
                headers=(("User-Agent", MOF_USER_AGENT),
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
                    error_kind="http_error",
                    error_detail=f"HTTP {response.status_code}")
            bodies.append(response.body)
        if len(bodies) > 1:
            issues.append("concatenated_files:jgbcm_all+jgbcm_current")
        body = b"\n".join(bodies)
        base = dict(
            provider_id=self.provider_id, series_id=spec.series_id, symbol=symbol,
            url=redact_url(last_url), status_code=status,
            retrieved_at=retrieved_at, elapsed_ms=elapsed, body=body)
        records, parse_issues = parse_mof_jgbcm_csv(body, symbol)
        issues.extend(parse_issues)
        in_range = tuple(
            r for r in records if start.isoformat() <= r.trading_date <= end.isoformat())
        if not in_range:
            kind = "parse_error" if not records else "no_data"
            return ProviderFetchResult(
                **base, parse_issues=tuple(issues), error_kind=kind,
                error_detail=(";".join(issues)[:160] or "no rows in requested range"))
        # 全履歴ファイルを含むため要求期間外の行はObservation化しない（bodyは保存）
        return ProviderFetchResult(**base, records=in_range, parse_issues=tuple(issues))
