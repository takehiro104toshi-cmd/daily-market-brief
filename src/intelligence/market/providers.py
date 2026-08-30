"""MarketDataProvider抽象＋Stooq実装（Phase 2-D PART C）。

- domain（ingest/store/derived）はprovider実装を知らない。依存は
  `MarketDataProvider` Protocolのみ（yfinance/Stooq等の固有知識はこの層で止める）。
- Stooq daily history: 1リクエストで指定期間の日足CSV全体が返る
  （legacy src/collectors/market_data.py のquote endpointと同型の資産再利用。
  historyエンドポイントは `q/d/l/?s=SYMBOL&i=d&d1=..&d2=..`）。
- **値はstringトークンのまま**返す（Decimal化はingest側。floatを経由しない）。
- HTTP応答CSVはbytesで保持し、ingestがBlobStoreへ**生のまま**保存する
  （provider_normalized=false: ライブラリ前処理なしの生応答）。
- 取得はP1-CのHttpTransport（stdlib urllib・timeout必須・redact）を再利用。
"""
from __future__ import annotations

import csv
import io
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol, Tuple, runtime_checkable

from ..ingestion.model import FetchRequest
from ..ingestion.transport import DEFAULT_TIMEOUT, HttpTransport, redact_url
from .series_catalog import SeriesSpec

STOOQ_PROVIDER_ID = "stooq"
YFINANCE_PROVIDER_ID = "yfinance"

#: 日足history CSVエンドポイント（期間指定で過剰収集を避ける。bulk全履歴は取らない）
STOOQ_DAILY_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d&d1={d1}&d2={d2}"

#: LEGACY REUSE: legacy src/utils.py DEFAULT_HEADERS と同一のUA。
#: 本番workflowでStooq quote endpointに対し毎日実績のある値（vNext既定UAだと
#: StooqはHTTP 200でHTMLページを返すことがある——P2-D live pilot初回実測）。
STOOQ_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 market-brief-bot/1.0"
)

#: parse時に許容するCSVヘッダ名（Stooq実応答: Date,Open,High,Low,Close[,Volume]）
_DATE_KEYS = ("date",)
_FIELD_KEYS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, kw_only=True)
class ProviderRecord:
    """provider応答の1行（**transient**・stringトークンのまま。floatにしない）。"""

    trading_date: str  # "YYYY-MM-DD"（provider表記のまま検証済み）
    close: str = ""    # 空文字=そのトークンが欠測（勝手に埋めない）
    open: str = ""
    high: str = ""
    low: str = ""
    volume: str = ""
    line_no: int = 0   # CSV内の行番号（provenance・障害調査用）


@dataclass(frozen=True, kw_only=True)
class ProviderFetchResult:
    """1系列・1リクエスト分の取得結果（transient。永続化はingest/backfillが担う）。"""

    provider_id: str
    series_id: str
    symbol: str
    url: str  # redact済み（そのまま保存可能）
    status_code: int = 0
    retrieved_at: datetime
    elapsed_ms: int = 0
    body: bytes = b""  # 生CSV（BlobStoreへそのまま保存する）
    records: Tuple[ProviderRecord, ...] = ()
    parse_issues: Tuple[str, ...] = ()
    error_kind: str = ""   # "" / http_error / no_data / parse_error / transport系
    error_detail: str = ""
    provider_normalized: bool = False  # True=ライブラリ前処理済み応答（生HTTPではない）
    media_type: str = "text/csv"  # raw保存時のmedia type（JSON API providerが上書き）

    @property
    def ok(self) -> bool:
        return self.error_kind == "" and bool(self.records)


@runtime_checkable
class MarketDataProvider(Protocol):
    """市場データ供給元の抽象。domainはこのProtocolのみに依存する。"""

    @property
    def provider_id(self) -> str:  # pragma: no cover
        ...

    def fetch_daily_history(
        self, spec: SeriesSpec, *, start: date, end: date
    ) -> ProviderFetchResult:  # pragma: no cover
        ...


def parse_stooq_daily_csv(body: bytes) -> Tuple[Tuple[ProviderRecord, ...], Tuple[str, ...]]:
    """Stooq日足CSV → (records, parse_issues)。ヘッダ駆動・防御的parse。

    - 列順を仮定しない（ヘッダ名で対応付け）。
    - 不正日付・列数不一致行はskipしissueへ記録（黙って捨てない）。
    - 値トークンはstringのまま（"4.254" 等。Decimal化はingest）。
    """
    issues = []
    try:
        text = body.decode("utf-8-sig", errors="replace")
    except Exception:  # noqa: BLE001
        return (), ("body_decode_failed",)
    stripped = text.strip()
    if not stripped:
        return (), ("empty_body",)
    if stripped.lower().startswith(("no data", "brak danych")):
        return (), ("no_data_response",)

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return (), ("empty_body",)
    columns = {name.strip().lower(): idx for idx, name in enumerate(header)}
    if not any(k in columns for k in _DATE_KEYS):
        # 診断用に応答先頭の安全なsnippetを添える（HTMLページ・制限ページ等の切り分け。
        # 公開市場データの応答先頭のみ・制御文字除去済み）
        snippet = "".join(c for c in stripped[:80] if c.isprintable())
        return (), ("missing_date_column", f"body_head={snippet}")

    records = []
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        raw_date = row[columns["date"]].strip() if columns["date"] < len(row) else ""
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            issues.append(f"line{line_no}:invalid_date:{raw_date[:20]}")
            continue

        def token(key: str) -> str:
            idx = columns.get(key)
            if idx is None or idx >= len(row):
                return ""
            value = row[idx].strip()
            return "" if value.upper() in ("", "N/A", "-") else value

        records.append(ProviderRecord(
            trading_date=parsed.isoformat(),
            close=token("close"),
            open=token("open"),
            high=token("high"),
            low=token("low"),
            volume=token("volume"),
            line_no=line_no,
        ))
    return tuple(records), tuple(issues)


class YfinanceDailyHistoryProvider:
    """Yahoo Finance日足history（yfinance経由・MARKET_DATA_PROVIDER）。

    LEGACY REUSE: legacyの一次経路そのもの（src/collectors/market_data.py は
    yfinance一次・Stooq quoteフォールバック構成で、本番Actionsから毎日実績がある）。
    Yahooティッカーもlegacy config.yaml（^N225/^DJI/^GSPC/^IXIC/^VIX/^SOX/
    JPY=X/EURUSD=X/^TNX/CL=F/GC=F/BTC-USD）の実績値を使う。

    正直な申告（生HTTPを捏造しない）:
    - **provider_normalized=True** … yfinanceライブラリが前処理した応答であり
      生HTTP CSVではない。blobは本adapterが決定論整形したCSVスナップショット。
    - **float経由の事実** … yfinanceはfloatを返す。トークンはrepr(float)
      （最短round-trip表現）で、Decimalはそこから生成する——providerがfloatで
      供給した事実はparse_issues("provider_float_transit")として全fetchに記録する。
    - adjustment=unadjustedに合わせ auto_adjust=False の Close 列を使う。
    """

    def __init__(self, history_fn=None) -> None:
        # history_fn(symbol, start, end) -> Sequence[(date_iso, close_float, volume)]
        # テストは決定論スタブを注入。既定実装のみyfinanceへ依存する。
        self._history_fn = history_fn or _yfinance_history

    @property
    def provider_id(self) -> str:
        return YFINANCE_PROVIDER_ID

    def fetch_daily_history(
        self, spec: SeriesSpec, *, start: date, end: date
    ) -> ProviderFetchResult:
        symbol = spec.symbol_for(self.provider_id)
        now = datetime.now(timezone.utc)
        if not symbol:
            return ProviderFetchResult(
                provider_id=self.provider_id, series_id=spec.series_id, symbol="",
                url="", retrieved_at=now, provider_normalized=True,
                error_kind="no_symbol", error_detail="catalogに本providerのsymbolなし",
            )
        url = f"https://finance.yahoo.com/quote/{symbol}"  # 参照locator（legacy踏襲）
        started = _time.monotonic()
        try:
            rows = self._history_fn(symbol, start, end)
        except Exception as exc:  # noqa: BLE001 ライブラリ例外を種類へ写像
            return ProviderFetchResult(
                provider_id=self.provider_id, series_id=spec.series_id, symbol=symbol,
                url=url, retrieved_at=now, provider_normalized=True,
                elapsed_ms=int((_time.monotonic() - started) * 1000),
                error_kind="connection",
                error_detail=f"{type(exc).__name__}: {str(exc)[:120]}")
        elapsed = int((_time.monotonic() - started) * 1000)
        if not rows:
            return ProviderFetchResult(
                provider_id=self.provider_id, series_id=spec.series_id, symbol=symbol,
                url=url, retrieved_at=now, elapsed_ms=elapsed, provider_normalized=True,
                error_kind="no_data", error_detail="empty history")
        records = []
        lines = ["Date,Close,Volume"]
        for line_no, (day_iso, close, volume) in enumerate(sorted(rows), start=2):
            token = "" if close is None else repr(float(close))
            vol_token = "" if volume in (None, "") else str(int(volume))
            records.append(ProviderRecord(
                trading_date=day_iso, close=token, volume=vol_token, line_no=line_no))
            lines.append(f"{day_iso},{token},{vol_token}")
        body = ("\n".join(lines) + "\n").encode("utf-8")  # provider-normalized snapshot
        return ProviderFetchResult(
            provider_id=self.provider_id, series_id=spec.series_id, symbol=symbol,
            url=url, status_code=200, retrieved_at=now, elapsed_ms=elapsed,
            body=body, records=tuple(records),
            parse_issues=("provider_float_transit",),  # floatで供給された事実の申告
            provider_normalized=True)


def _yfinance_history(symbol: str, start: date, end: date):
    """既定実装（実ネットワーク。テストはhistory_fn注入でここへ来ない）。"""
    import yfinance as yf

    frame = yf.Ticker(symbol).history(
        start=start.isoformat(), end=end.isoformat(),
        interval="1d", auto_adjust=False, actions=False)
    rows = []
    for ts, row in frame.iterrows():
        close = row.get("Close")
        volume = row.get("Volume")
        rows.append((
            ts.date().isoformat(),
            None if close != close else float(close),      # NaN→None（欠測のまま）
            None if volume != volume else float(volume),
        ))
    return rows


class StooqDailyHistoryProvider:
    """Stooq無料日足history（MARKET_DATA_PROVIDER・一次公表値ではない）。"""

    def __init__(self, transport: HttpTransport, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._transport = transport
        self._timeout = timeout

    @property
    def provider_id(self) -> str:
        return STOOQ_PROVIDER_ID

    def build_url(self, symbol: str, start: date, end: date) -> str:
        return STOOQ_DAILY_URL.format(
            symbol=symbol, d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")
        )

    def fetch_daily_history(
        self, spec: SeriesSpec, *, start: date, end: date
    ) -> ProviderFetchResult:
        symbol = spec.symbol_for(self.provider_id)
        now = datetime.now(timezone.utc)
        if not symbol:
            return ProviderFetchResult(
                provider_id=self.provider_id, series_id=spec.series_id, symbol="",
                url="", retrieved_at=now,
                error_kind="no_symbol", error_detail="catalogに本providerのsymbolなし",
            )
        url = self.build_url(symbol, start, end)
        request = FetchRequest(
            source_id=self.provider_id,
            endpoint_id=f"{self.provider_id}:{symbol}",
            url=url,
            headers=(("User-Agent", STOOQ_USER_AGENT),
                     ("Accept", "text/csv, text/plain;q=0.9, */*;q=0.5")),
            requested_at=now,
        )
        response = self._transport.send(request, timeout=self._timeout)
        base = dict(
            provider_id=self.provider_id, series_id=spec.series_id, symbol=symbol,
            url=redact_url(url), status_code=response.status_code,
            retrieved_at=response.retrieved_at, elapsed_ms=response.elapsed_ms,
            body=response.body,
        )
        if response.error_kind:
            return ProviderFetchResult(
                **base, error_kind=response.error_kind, error_detail=response.error_detail)
        if response.status_code != 200:
            return ProviderFetchResult(
                **base, error_kind="http_error", error_detail=f"HTTP {response.status_code}")
        records, issues = parse_stooq_daily_csv(response.body)
        if not records:
            kind = "no_data" if any(
                i in ("no_data_response", "empty_body") for i in issues) else "parse_error"
            return ProviderFetchResult(
                **base, parse_issues=issues, error_kind=kind,
                error_detail=";".join(issues)[:160])
        return ProviderFetchResult(**base, records=records, parse_issues=issues)
