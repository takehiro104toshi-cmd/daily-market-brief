"""J-Quants V2 汎用クライアント（Phase 2-H STEP 1/11）。

P2-G.2で実証した**TOPIX専用provider**の接続部分を、他datasetからも再利用できる
最小の共通経路へ昇格させる。

再利用の方針（既存機能を再実装しない）:
- credential解決・秘密のscrub・原因分類・HTTP実行は `jquants_v2` の実装を
  **そのままimportして使う**（V2の認証仕様はTOPIXと共通なので二重実装しない）。
- `jquants_v2.JQuantsV2TopixProvider` は**一切変更しない**——P2-G.2でlive実証済みの
  経路であり、リファクタで壊すリスクを取らない（TOPIX regressionを守る）。
- 本モジュールが足すのは「任意path＋任意params＋pagination＋entitlement判定」
  という汎用部分のみ。

FAIL-CLOSED:
- credential未設定なら**ネットワークを1回も叩かず**停止する。
- 200以外は行を1件も返さない（部分的な成功を成功として扱わない）。
- プラン非対象（403 + plan message）は `NOT_ENTITLED` として明示し、
  **別プランのendpointへ迂回しない**。
"""
from __future__ import annotations

import json
import time as _time
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .jquants_v2 import (
    API_VERSION,
    AUTH_HEADER,
    DATA_KEY,
    JQUANTS_PROVIDER_ID,
    JQUANTS_V2_BASE,
    PAGINATION_KEY,
    CAUSE_PLAN_NOT_ENTITLED,
    JQuantsV2CredentialResolver,
    JQuantsV2CredentialResolverProtocol,
    classify_v2_failure,
    scrub_response_text,
)
from .jquants_v2 import _default_http as _http

#: entitlement判定（実証ベース。推測でAVAILABLE扱いしない）
AVAILABLE = "AVAILABLE"
NOT_ENTITLED = "NOT_ENTITLED"
UNKNOWN = "UNKNOWN"

#: 1リクエストあたりの安全上限（1datasetの暴走を防ぐ）
MAX_PAGES = 50
#: pagination間の待機（fair access。rate limitに対する礼儀）
PAGE_INTERVAL_SECONDS = 0.2

HttpFn = Callable[[str, str, dict, bytes], Tuple[int, bytes]]


@dataclass(frozen=True, kw_only=True)
class JQuantsFetchResult:
    """1 dataset・1リクエスト分の取得結果（transient。永続化は呼び出し側）。"""

    dataset: str
    path: str
    url: str                      # 永続化されるlocator（**秘密を含まない**）
    status_code: int = 0
    rows: Tuple[dict, ...] = ()
    bodies: Tuple[bytes, ...] = ()
    pages: int = 0
    elapsed_ms: int = 0
    retrieved_at: str = ""
    entitlement: str = UNKNOWN
    error_kind: str = ""          # "" / no_credentials / auth_error / http_error /
                                  # parse_error / schema_error / connection
    error_detail: str = ""
    failure_cause: str = ""
    observed_row_fields: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.error_kind == "" and self.status_code == 200

    @property
    def raw_body(self) -> bytes:
        """複数ページは改行連結（連結した事実はpagesで申告する）。"""
        return b"\n".join(self.bodies)


class JQuantsV2Client:
    """任意のV2 datasetを取得する最小クライアント。

    provider識別子は `jquants`、版数は `v2`（provenanceはTOPIXと同一の規約）。
    """

    def __init__(
        self,
        http_fn: Optional[HttpFn] = None,
        *,
        env: Optional[Mapping[str, str]] = None,
        resolver: Optional[JQuantsV2CredentialResolverProtocol] = None,
        sleeper: Callable[[float], None] = _time.sleep,
    ) -> None:
        self._http = http_fn or _http
        if resolver is not None:
            self._resolver: JQuantsV2CredentialResolverProtocol = resolver
        elif env is not None:
            self._resolver = JQuantsV2CredentialResolver(env)
        else:
            self._resolver = JQuantsV2CredentialResolver()
        self._sleep = sleeper
        self.request_count = 0

    @property
    def provider_id(self) -> str:
        return JQUANTS_PROVIDER_ID

    @property
    def api_version(self) -> str:
        return API_VERSION

    def credential_present(self) -> bool:
        return self._resolver.resolve().present

    # ------------------------------------------------------------------ fetch

    def fetch(
        self,
        dataset: str,
        path: str,
        params: Optional[Mapping[str, str]] = None,
        *,
        required_fields: Sequence[str] = (),
        max_pages: int = MAX_PAGES,
    ) -> JQuantsFetchResult:
        """1 datasetを取得する（paginationは自動追跡）。

        `required_fields` を渡すと、先頭行に不足があれば `schema_error` として
        **1行も返さない**（想定と違う応答を黙って取り込まない）。
        """
        query = urllib.parse.urlencode(sorted((params or {}).items()))
        public_url = f"{JQUANTS_V2_BASE}{path}" + (f"?{query}" if query else "")
        now = _now_iso()
        base = dict(dataset=dataset, path=path, url=public_url, retrieved_at=now)

        cred = self._resolver.resolve()
        if not cred.present:
            # FAIL-CLOSED: ネットワークを1回も叩かない
            return JQuantsFetchResult(
                **base, error_kind="no_credentials", error_detail=cred.detail)
        secrets = cred.secret_values()
        headers = {AUTH_HEADER: cred.secrets["api_key"].reveal()}

        started = _time.monotonic()
        bodies: List[bytes] = []
        rows: List[dict] = []
        pagination_key = ""
        status = 0
        for page in range(max_pages):
            url = public_url
            if pagination_key:
                sep = "&" if query else "?"
                url = f"{public_url}{sep}{PAGINATION_KEY}=" + urllib.parse.quote(pagination_key)
            try:
                self.request_count += 1
                status, body = self._http(url, "GET", headers, b"")
            except Exception as exc:  # noqa: BLE001 ライブラリ例外を種類へ写像
                return JQuantsFetchResult(
                    **base, status_code=status, error_kind="connection",
                    error_detail=scrub_response_text(
                        f"{type(exc).__name__}: {str(exc)[:120]}", secrets))
            if status != 200:
                message = _message_of(body)
                cause = classify_v2_failure(status, message)
                entitlement = NOT_ENTITLED if cause == CAUSE_PLAN_NOT_ENTITLED else UNKNOWN
                return JQuantsFetchResult(
                    **base, status_code=status, entitlement=entitlement,
                    error_kind=("auth_error" if status in (401, 403) else "http_error"),
                    failure_cause=cause,
                    error_detail=f"http_{status}"
                                 + (f" cause={cause}" if cause else "")
                                 + (f" message={scrub_response_text(message, secrets)[:160]}"
                                    if message else ""))
            try:
                payload = json.loads(body, parse_float=str)
            except json.JSONDecodeError:
                return JQuantsFetchResult(
                    **base, status_code=status, bodies=tuple(bodies + [body]),
                    error_kind="parse_error", error_detail="invalid_json")
            if not isinstance(payload, dict) or not isinstance(payload.get(DATA_KEY), list):
                keys = ",".join(sorted(map(str, payload))) if isinstance(payload, dict) else ""
                return JQuantsFetchResult(
                    **base, status_code=status, bodies=tuple(bodies + [body]),
                    error_kind="schema_error",
                    error_detail=f"missing_data_array:keys={keys[:80]}")
            page_rows = payload[DATA_KEY]
            if page == 0 and required_fields and page_rows:
                missing = [f for f in required_fields if f not in page_rows[0]]
                if missing:
                    return JQuantsFetchResult(
                        **base, status_code=status, bodies=tuple(bodies + [body]),
                        error_kind="schema_error",
                        error_detail=f"missing_fields:{','.join(missing)}")
            bodies.append(body)
            rows.extend(r for r in page_rows if isinstance(r, dict))
            pagination_key = str(payload.get(PAGINATION_KEY) or "")
            if not pagination_key:
                break
            self._sleep(PAGE_INTERVAL_SECONDS)

        fields = tuple(sorted(map(str, rows[0]))) if rows else ()
        return JQuantsFetchResult(
            **base, status_code=status, rows=tuple(rows), bodies=tuple(bodies),
            pages=len(bodies), elapsed_ms=int((_time.monotonic() - started) * 1000),
            entitlement=AVAILABLE, observed_row_fields=fields)


def _message_of(body: bytes) -> str:
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            return str(payload.get("message", ""))
    except Exception:  # noqa: BLE001
        pass
    return body[:120].decode("utf-8", "replace")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
