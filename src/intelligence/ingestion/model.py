"""Raw Ingestionのドメインモデル（Phase 1-C / schema 0.2.0内の追加）。

- FetchRequest / FetchResponse … 取得1回分の入出力（**transient**。永続化しない）
- FetchAttempt … 取得試行の永続記録（時系列・append-only）。
  304・timeout・403等で**RawItemが生成されない試行も必ず記録**し、
  P1-BのSourceHealthObservation導出と後で連携できるようにする。

Secret規律:
- FetchRequestは認証系ヘッダ名を型レベルで拒否する（資格情報はtransportにも渡さない。
  認証付きAPIの資格情報注入はP1-D以降、header方式・redaction前提で設計する）。
- FetchAttemptへ保存するURL群は呼び出し側（fetcher）でredact済みであること。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Tuple

from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION

#: 資格情報を運びうるヘッダ（FetchRequestが拒否する。小文字比較）
FORBIDDEN_HEADER_NAMES = frozenset(
    {"authorization", "cookie", "proxy-authorization", "x-api-key", "x-apikey", "subscription-key"}
)

#: FetchAttempt.error_kind の語彙
ERROR_KINDS = ("", "timeout", "dns", "tls", "connection", "protocol", "unknown")


@dataclass(frozen=True, kw_only=True)
class FetchRequest:
    """取得1回分の入力（transient）。"""

    source_id: str
    endpoint_id: str
    url: str
    method: str = "GET"
    headers: Tuple[Tuple[str, str], ...] = ()  # UA/Accept等の非Secretメタデータのみ
    etag: str = ""  # If-None-Match として送る値（条件付きGET）
    last_modified: str = ""  # If-Modified-Since として送る値
    requested_at: datetime

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("url must be http(s)")
        ensure_aware(self.requested_at, "FetchRequest.requested_at")
        for name, _value in self.headers:
            if name.lower() in FORBIDDEN_HEADER_NAMES:
                raise ValueError(f"forbidden credential header: {name}")


@dataclass(frozen=True, kw_only=True)
class FetchResponse:
    """取得1回分の結果（transient。bodyはbytesのまま保持し、永続化はraw_storeが担う）。"""

    status_code: int = 0  # 0 = リクエスト不成立
    final_url: str = ""
    redirect_chain: Tuple[str, ...] = ()  # 経由URL（時系列順）
    permanent_redirect: bool = False  # 301/308を経由した
    content_type: str = ""
    etag: str = ""
    last_modified: str = ""
    retry_after: str = ""  # 429/503のRetry-Afterヘッダ生値
    body: bytes = b""
    retrieved_at: datetime
    elapsed_ms: int = 0
    error_kind: str = ""  # ERROR_KINDS参照
    error_detail: str = ""

    def __post_init__(self) -> None:
        ensure_aware(self.retrieved_at, "FetchResponse.retrieved_at")
        if self.error_kind not in ERROR_KINDS:
            raise ValueError(f"unknown error_kind: {self.error_kind}")


@dataclass(frozen=True, kw_only=True)
class FetchAttempt:
    """取得試行1回分の永続記録（append-only。上書きしない）。

    保存されるURL（url/final_url/redirect_chain）はredact済みであること。
    Secret値・認証ヘッダは構造上保持できない。
    """

    attempt_id: str  # fetch_<ULID>（時刻順）
    source_id: str
    endpoint_id: str
    url: str
    method: str = "GET"
    requested_at: datetime
    elapsed_ms: int = 0
    status_code: int = 0  # 0 = リクエスト不成立
    final_url: str = ""
    redirect_chain: Tuple[str, ...] = ()
    permanent_redirect: bool = False  # 301/308経由（Registry更新の**候補**。自動書換えはしない）
    content_type: str = ""
    body_size: int = 0
    content_hash: str = ""  # sha256 hex（本文を取得した場合のみ）
    etag: str = ""  # 受信したETag（次回If-None-Match用。Secretではない）
    last_modified: str = ""  # 受信したLast-Modifiedヘッダ生値
    not_modified: bool = False  # HTTP 304（本文なし=RawItemを作らない）
    conditional_used: bool = False  # 条件付きGETヘッダを送ったか
    raw_item_id: str = ""  # 本試行からRawItemが生成された場合のみ
    error_kind: str = ""
    error_detail: str = ""
    retries: int = 0  # 最終応答までに消費したretry回数
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise ValueError("attempt_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        ensure_aware(self.requested_at, "FetchAttempt.requested_at")
        if self.error_kind not in ERROR_KINDS:
            raise ValueError(f"unknown error_kind: {self.error_kind}")
