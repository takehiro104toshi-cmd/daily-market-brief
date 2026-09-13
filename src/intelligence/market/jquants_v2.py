"""J-Quants **V2** TOPIX provider（Phase 2-G.2 / V1→V2 migration）。

背景（監督者訂正・2026-08-30）:
- **J-Quants V1 APIは2026-06-01に終了**した。`api.jquants.com/v1/...` および
  V1のtoken認証（mail/password → refreshToken → idToken）は**現行仕様ではない**。
- したがって run #7〜#12 で観測した403は「credential不正」ではなく
  `LEGACY_V1_ENDPOINT_USED` / `API_VERSION_MISMATCH` を主要原因とする
  （過去の実測記録は改竄せず append-only で保全する）。

本モジュールはV2**だけ**を実装する（V1実装 `jquants_topix.py` とは完全に分離。
V1のコードパス・エンドポイント・認証方式を一切参照しない）。共有するのは
秘密安全の基礎部品（Secret / CredentialResolution / scrub）のみで、これらは
API版数に依存しない。

確認済みのV2公式仕様（一次情報。推測でV1から変換していない）:
- Base URL: ``https://api.jquants.com/v2``（公式クイックスタート V2 の
  ``API_URL`` 実値。run #13の実測でも ``/v1`` 配下のみが旧ルートとして残存し、
  V2の未知パスは「The requested endpoint does not exist ... API version」
  という別メッセージを返すことを確認）
- 認証: **API Key をヘッダ ``x-api-key`` で送る**（V1のtoken交換は廃止。
  ダッシュボード発行のAPI Keyに有効期限なし）
- TOPIX四本値: ``GET /v2/indices/bars/daily/topix``（TOPIX専用パス。
  ``from`` / ``to`` / ``pagination_key`` を受け付ける）
- 応答: ``{"data": [...], "pagination_key": ...}``（V1の ``{"topix": [...]}``
  ではない。項目名はV2で短縮され OHLC は ``O`` / ``H`` / ``L`` / ``C``）
- 提供プラン: TOPIX四本値は**Light以上**（Freeでは提供対象外）
- 更新時刻: **毎営業日16:30頃**

credential規律（P2-G.1から継続。V2でも変更なし）:
- 環境変数からの**runtime injectionのみ**。Git commit / config平文 / logs /
  例外メッセージ / FetchAttempt / raw payload / レポートへ秘密を出さない。
- API Keyは**ヘッダのみ**で送る（URLクエリに載せない——URLは永続化される）。
- 応答本文にcredentialのエコーが混ざる可能性に備え、
  `scrub_response_text()` で**部分一致でも**遮断してから診断文へ載せる。
"""
from __future__ import annotations

import json
import os
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Callable, Dict, Mapping, Optional, Protocol, Tuple, runtime_checkable

from .jquants_topix import CredentialResolution, Secret, scrub
from .providers import ProviderFetchResult, ProviderRecord
from .series_catalog import SeriesSpec

#: provenanceのprovider識別子はV1と同一（供給元は同じJ-Quants）。
#: 版数は `API_VERSION` として区別し、永続化locatorのURLにも `/v2/` が残る。
JQUANTS_PROVIDER_ID = "jquants"
API_VERSION = "v2"

JQUANTS_V2_BASE = "https://api.jquants.com/v2"
TOPIX_PATH = "/indices/bars/daily/topix"

#: V2の認証方式（**唯一**。V1のtoken交換方式はV2の既定にしない）
AUTH_HEADER = "x-api-key"
METHOD_API_KEY_HEADER = "api_key_header"
METHOD_MISSING = "missing"

ENV_API_KEY = "JQUANTS_API_KEY"
ACCEPTED_ENV_VARS = (ENV_API_KEY,)

#: V2応答のエンベロープ／項目名（公式クイックスタートV2の実コードで確認）
DATA_KEY = "data"
PAGINATION_KEY = "pagination_key"
DATE_FIELD = "Date"
CLOSE_FIELD = "C"
OPEN_FIELD = "O"
HIGH_FIELD = "H"
LOW_FIELD = "L"

#: TOPIXの指数コード（`Code`項目が存在する場合のみ照合する）。
#: 個別銘柄コード（1306等のETF）が現れたらidentity_mismatchで拒否する。
TOPIX_INDEX_CODE = "0000"

#: 指数系列に現れてはならない項目（ETFのNAV・先物の限月/清算値・個別銘柄）
_FORBIDDEN_FIELDS = frozenset({
    "netassetvalue", "nav", "fundcode", "contractmonth", "settlementprice",
    "issue", "securitiescode", "centralcontractmonthflag",
})

#: 原因分類（V1 EOLを起点とする診断コード。過去記録の再解釈にも使う）
CAUSE_LEGACY_V1_ENDPOINT = "legacy_v1_endpoint"
CAUSE_API_VERSION_MISMATCH = "api_version_mismatch"
CAUSE_PLAN_NOT_ENTITLED = "plan_not_entitled"
CAUSE_CREDENTIAL_REJECTED = "credential_rejected"

_TIMEOUT = 30.0

#: http_fn(url, method, headers, payload) -> (status_code, body_bytes)
HttpFn = Callable[[str, str, dict, bytes], Tuple[int, bytes]]


@runtime_checkable
class JQuantsV2CredentialResolverProtocol(Protocol):
    """V2認証情報の解決契約（方式変更をproviderから隔離する）。"""

    def resolve(self) -> CredentialResolution:  # pragma: no cover - Protocol
        ...


class JQuantsV2CredentialResolver:
    """環境変数 ``JQUANTS_API_KEY`` からのruntime injection（V2の正式方式）。

    V1のenv名（JQUANTS_MAIL / JQUANTS_PASSWORD / JQUANTS_REFRESH_TOKEN /
    JQUANTS_ID_TOKEN）は**V2では受理しない**——V1方式をV2の既定へ持ち込まない
    （旧仕様を推測でV2へ変換しない、という監督者指示の実装上の担保）。
    """

    def __init__(self, env: Mapping[str, str] = os.environ) -> None:
        self._env = env

    def resolve(self) -> CredentialResolution:
        api_key = self._env.get(ENV_API_KEY, "").strip()
        if api_key:
            return CredentialResolution(
                method=METHOD_API_KEY_HEADER,
                secrets={"api_key": Secret(api_key)},
                source_names=(ENV_API_KEY,),
                detail=f"API Key をヘッダ {AUTH_HEADER} で送信（V2公式方式・"
                       "token交換なし）")
        return CredentialResolution(
            method=METHOD_MISSING,
            detail="credential未設定（V2はruntime injectionの "
                   f"{ENV_API_KEY} のみ受理）")


def scrub_response_text(text: str, secrets: Tuple[str, ...]) -> str:
    """応答本文をエラー診断へ載せる前の遮断（**部分一致でも落とす**）。

    API Gatewayは不正なAuthorizationヘッダに対し、値のSHA-256/Base64ダイジェスト
    を含むメッセージを返すことがある（run #13実測）。ダイジェスト自体は原文では
    ないが、原文断片のエコーと区別せず**両方**を落とす方針にする。
    """
    out = scrub(text, secrets)
    marker = "(hashed with SHA-256"
    if marker in out:
        out = out.split(marker)[0].rstrip() + " [digest-echo-removed]"
    for value in secrets:
        for i in range(0, max(0, len(value) - 7)):
            if value[i:i + 8] in out:
                return "[redacted_possible_credential_echo]"
    return out


def classify_v2_failure(status: int, message: str) -> str:
    """HTTPステータス＋応答メッセージ → 原因分類（推測で断定しない）。

    - 「エンドポイントが存在しない」旨のメッセージ＝**版数不整合**であって
      credential不正ではない（V1 EOL後の主要原因候補）。
    - プラン非対象は認証失敗と区別する（access tierの問題）。
    """
    lowered = message.lower()
    if "does not exist" in lowered or "api version" in lowered:
        return CAUSE_API_VERSION_MISMATCH
    if "plan" in lowered or "subscription" in lowered or "not available" in lowered:
        return CAUSE_PLAN_NOT_ENTITLED
    if status in (401, 403):
        return CAUSE_CREDENTIAL_REJECTED
    return ""


def validate_topix_v2_payload(payload: object) -> Tuple[str, Tuple[str, ...]]:
    """V2 TOPIX応答のschema/identity検証 → (error_kind, issues)。

    期待: ``{"data": [{"Date": ..., "O"/"H"/"L"/"C": ...}, ...]}``
    **identity guard**: ETFのNAV・先物の限月/清算値・個別銘柄コードを含む応答は
    `identity_mismatch` として1行も取り込まない（NO PROXY SUBSTITUTION）。
    """
    if not isinstance(payload, dict):
        return "schema_error", ("payload_not_object",)
    if DATA_KEY not in payload:
        return "schema_error", (
            f"missing_data_key:keys={','.join(sorted(map(str, payload)))[:60]}",)
    rows = payload.get(DATA_KEY)
    if not isinstance(rows, list):
        return "schema_error", ("data_not_array",)
    issues = []
    for i, row in enumerate(rows[:50]):  # 先頭サンプルで構造検査（全件はingest側）
        if not isinstance(row, dict):
            return "schema_error", (f"row{i}_not_object",)
        lowered = {str(k).lower() for k in row}
        overlap = sorted(lowered & _FORBIDDEN_FIELDS)
        if overlap:
            return "identity_mismatch", (f"non_index_fields:{','.join(overlap)}",)
        code = row.get("Code", row.get("code"))
        if code is not None and not _is_topix_code(code):
            # 誤検知（"0000" と 0 の表記差）を吸収しつつ、別指数・個別銘柄は拒否する。
            # 取り違えて取り込むより、GAPとして可視化するほうが安全。
            return "identity_mismatch", (f"unexpected_index_code:{str(code)[:12]}",)
        for required in (DATE_FIELD, CLOSE_FIELD):
            if required not in row:
                issues.append(f"row{i}_missing_{required.lower()}")
    return "", tuple(issues)


def _is_topix_code(code: object) -> bool:
    """指数コードがTOPIX（0000）か。``"0000"`` / ``0`` の表記差を同一視する。"""
    normalized = str(code).strip().lstrip("0") or "0"
    return normalized == (TOPIX_INDEX_CODE.lstrip("0") or "0")


def _default_http(url: str, method: str, headers: dict, payload: bytes) -> Tuple[int, bytes]:
    """HTTP実行 → (status, body)。非2xxは例外にせずステータスとして返す。"""
    request = urllib.request.Request(url, method=method)
    for key, value in headers.items():
        request.add_header(key, value)
    if payload:
        request.data = payload
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read(8192) if exc.fp else b"")


class JQuantsV2TopixProvider:
    """J-Quants V2 ``/indices/bars/daily/topix`` のMarketDataProvider実装。

    catalog identity（``index:topix.close.closing.tokyo``）は維持する。
    ETF（1306.T等）・TOPIX先物・近似指数へのfallbackは**しない**。
    """

    def __init__(
        self,
        http_fn: Optional[HttpFn] = None,
        *,
        env: Optional[Mapping[str, str]] = None,
        resolver: Optional[JQuantsV2CredentialResolverProtocol] = None,
    ) -> None:
        self._http = http_fn or _default_http
        self._resolver: JQuantsV2CredentialResolverProtocol = (
            resolver or JQuantsV2CredentialResolver(
                os.environ if env is None else env))
        self.last_auth_method: str = ""
        #: **実APIのdata endpointが200を返した**方式のみを記録する
        self.last_auth_method_validated: str = ""
        #: 失敗時の原因分類（legacy_v1_endpoint / api_version_mismatch / …）
        self.last_failure_cause: str = ""
        #: 実測したV2応答の項目名（schema確認の証跡。値は含まない）
        self.observed_row_fields: Tuple[str, ...] = ()
        self.observed_top_keys: Tuple[str, ...] = ()
        self.pages_fetched: int = 0

    @property
    def provider_id(self) -> str:
        return JQUANTS_PROVIDER_ID

    @property
    def api_version(self) -> str:
        return API_VERSION

    def fetch_daily_history(
        self, spec: SeriesSpec, *, start: date, end: date
    ) -> ProviderFetchResult:
        symbol = spec.symbol_for(self.provider_id) or ""
        now = datetime.now(timezone.utc)
        #: 永続化されるlocator（API Keyはヘッダのみ。URLへ載せない）
        public_url = (f"{JQUANTS_V2_BASE}{TOPIX_PATH}"
                      f"?from={start.isoformat()}&to={end.isoformat()}")
        base = dict(provider_id=self.provider_id, series_id=spec.series_id,
                    symbol=symbol, url=public_url, retrieved_at=now)
        self.last_auth_method = ""
        self.last_auth_method_validated = ""
        self.last_failure_cause = ""
        self.observed_row_fields = ()
        self.observed_top_keys = ()
        self.pages_fetched = 0
        if not symbol:
            # baseのurlを空へ差し替える（**base と url= の二重指定はTypeError）
            return ProviderFetchResult(
                **{**base, "url": ""}, error_kind="no_symbol",
                error_detail="catalogに本providerのsymbolなし")

        # ---- STEP 1: credential presence（未設定ならネットワークを叩かない）
        cred = self._resolver.resolve()
        self.last_auth_method = cred.method
        if not cred.present:
            return ProviderFetchResult(
                **base, error_kind="no_credentials", error_detail=cred.detail)
        secrets = cred.secret_values()
        headers = {AUTH_HEADER: cred.secrets["api_key"].reveal()}

        started = _time.monotonic()
        bodies: list = []
        rows: list = []
        issues: list = []
        pagination_key = ""
        status = 0
        for _page in range(20):  # 安全上限（400日日足は通常1ページ）
            url = public_url + (
                f"&{PAGINATION_KEY}=" + urllib.parse.quote(pagination_key)
                if pagination_key else "")
            try:
                status, body = self._http(url, "GET", headers, b"")
            except Exception as exc:  # noqa: BLE001 ライブラリ例外を種類へ写像
                return ProviderFetchResult(
                    **base, error_kind="connection", status_code=status,
                    error_detail=scrub_response_text(
                        f"{type(exc).__name__}: {str(exc)[:120]}", secrets))
            if status != 200:
                message = ""
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        message = str(parsed.get("message", ""))
                except Exception:  # noqa: BLE001 非JSON応答
                    message = body[:120].decode("utf-8", "replace")
                cause = classify_v2_failure(status, message)
                self.last_failure_cause = cause
                safe = scrub_response_text(message, secrets)[:160]
                kind = ("auth_error" if status in (401, 403) else "http_error")
                return ProviderFetchResult(
                    **base, status_code=status, body=b"", error_kind=kind,
                    error_detail=f"http_{status}"
                                 + (f" cause={cause}" if cause else "")
                                 + (f" message={safe}" if safe else ""))
            try:
                payload = json.loads(body, parse_float=str)
            except json.JSONDecodeError:
                return ProviderFetchResult(
                    **base, status_code=status, body=body,
                    error_kind="parse_error", error_detail="invalid_json")
            kind, schema_issues = validate_topix_v2_payload(payload)
            if kind:
                return ProviderFetchResult(
                    **base, status_code=status, body=body,
                    parse_issues=tuple(issues) + schema_issues, error_kind=kind,
                    error_detail=";".join(schema_issues)[:160])
            issues.extend(schema_issues)
            # ここまで到達＝x-api-keyがV2 data endpointで受理された
            self.last_auth_method_validated = cred.method
            if isinstance(payload, dict):
                self.observed_top_keys = tuple(sorted(map(str, payload)))
            page_rows = payload.get(DATA_KEY) or []
            if page_rows and not self.observed_row_fields and isinstance(page_rows[0], dict):
                self.observed_row_fields = tuple(sorted(map(str, page_rows[0])))
            bodies.append(body)
            rows.extend(page_rows)
            pagination_key = str(payload.get(PAGINATION_KEY) or "")
            if not pagination_key:
                break
        self.pages_fetched = len(bodies)
        if len(bodies) > 1:
            issues.append(f"paginated_response:{len(bodies)}pages")

        elapsed = int((_time.monotonic() - started) * 1000)
        raw_body = b"\n".join(bodies)
        if not rows:
            return ProviderFetchResult(
                **base, status_code=status, elapsed_ms=elapsed, body=raw_body,
                parse_issues=tuple(issues), error_kind="no_data",
                error_detail="empty topix payload")
        records = []
        for line_no, row in enumerate(
                sorted(rows, key=lambda r: str(r.get(DATE_FIELD, ""))), start=1):
            day = _normalize_date(str(row.get(DATE_FIELD, "")))
            if not day:
                issues.append(
                    f"row{line_no}:invalid_date:{str(row.get(DATE_FIELD, ''))[:20]}")
                continue
            records.append(ProviderRecord(
                trading_date=day,
                close=_token(row.get(CLOSE_FIELD)),
                open=_token(row.get(OPEN_FIELD)),
                high=_token(row.get(HIGH_FIELD)),
                low=_token(row.get(LOW_FIELD)),
                line_no=line_no))
        return ProviderFetchResult(
            **base, status_code=status, elapsed_ms=elapsed, body=raw_body,
            records=tuple(records), parse_issues=tuple(issues),
            media_type="application/json")


def _token(value: object) -> str:
    """数値トークンをstringのまま取り出す（欠測は空文字。floatを経由しない）。"""
    return "" if value is None else str(value)


def _normalize_date(raw: str) -> str:
    """V2が受理する2表記（``20260828`` / ``2026-08-28``）をISOへ寄せる。

    仕様上どちらで返るかは応答で決まるため、**両方を決定論的に受理**する
    （推測で片方だけを前提にしない）。判定不能なら空文字＝不正日付。
    """
    text = raw.strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    try:
        date.fromisoformat(text)
    except ValueError:
        return ""
    return text


def credential_status_v2(
    resolver: Optional[JQuantsV2CredentialResolverProtocol] = None,
) -> Dict[str, object]:
    """STEP 1報告用の状態（**秘密を含まない**: 方式名・由来env名・有無のみ）。"""
    resolution = (resolver or JQuantsV2CredentialResolver()).resolve()
    return {
        "present": resolution.present,
        "api_version": API_VERSION,
        "auth_method": resolution.method,
        "auth_header": AUTH_HEADER,
        # 解決できた方式＝「使える方式」ではない。実API成功のみが検証済み
        "auth_method_validated": "",
        "source_env_names": list(resolution.source_names),
        "accepted_env_names": list(ACCEPTED_ENV_VARS),
        "detail": resolution.detail,
    }
