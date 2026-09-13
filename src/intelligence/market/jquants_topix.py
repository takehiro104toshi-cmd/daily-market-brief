"""J-Quants TOPIX provider（Phase 2-G / P2-G.1 credentialed closeout）。

**LEGACY / SUPERSEDED — 現行のproduction pathではない（2026-09-01時点）**

- J-Quants **V1 APIは2026-06-01に終了**しており、本モジュールが叩く
  `https://api.jquants.com/v1/...` と V1のtoken認証（mail/password →
  refreshToken → idToken）は**現行仕様ではない**。
- 現行のTOPIX取得は `jquants_v2.JQuantsV2TopixProvider`（V2・API Keyヘッダ認証・
  `/v2/indices/bars/daily/topix`）が担う。catalog・pilot_runner・workflowの
  いずれからも本モジュールのproviderは呼ばれない（テストで固定）。
- 本モジュールは**当時の実測記録を再現・参照するためのhistorical reference**
  として残す。新規のproduction配線へ組み込まないこと。
- なお `Secret` / `CredentialResolution` / `scrub` はAPI版数に依存しない
  秘密安全の基礎部品であり、V2からも共有している（V1固有の資産ではない）。

series identity:
- J-Quants（JPX子会社 JPX Market Innovation & Research 運営の公式データAPI）の
  指数四本値エンドポイント（/v1/indices/topix）が返す**TOPIX Price Index値そのもの**。
- **TOPIX ≠ TOPIX ETF（1306.T等）のNAV ≠ TOPIX先物**——ETF/先物を指数seriesへ
  投入しない（NO PROXY SUBSTITUTION）。銘柄コード等を含む応答は
  identity_mismatchとして**拒否**する（黙って取り込まない）。

credential規律（P2-G.1）:
- **runtime injectionのみ**（環境変数）。Git commit / config平文 / logs /
  例外メッセージ / FetchAttempt / raw payload へ秘密を出さない。
- 認証方式は `JQuantsCredentialResolver` 契約の背後に隔離する——J-Quantsの
  仕様変更（token方式・API key方式等）はresolverの差し替えで吸収でき、
  fetch側は変更不要。env変数名を「永久に正しい仕様」と仮定しない。
- 秘密値は `Secret` でラップし、repr/strを潰す（うっかりログ出力を型で防ぐ）。
  全error_detailは既知の秘密値を除去（scrub）してから返す。
- credential未設定時は**ネットワークを1回も叩かず**に
  error_kind="no_credentials" で正常停止する（大量retryしない）。

値の忠実性:
- 応答JSONは `parse_float=str` で読み、数値トークンをstringのまま保持する
  （float非経由——P2-Dの値規律の維持）。bodyはAPI応答bytesそのまま保存
  （複数ページ時は改行連結し、その事実をparse_issuesへ申告）。
"""
from __future__ import annotations

import json
import os
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Dict, Mapping, Optional, Protocol, Tuple, runtime_checkable

from .providers import ProviderFetchResult, ProviderRecord
from .series_catalog import SeriesSpec

JQUANTS_PROVIDER_ID = "jquants"
JQUANTS_BASE = "https://api.jquants.com/v1"
_TIMEOUT = 30.0

#: 認証方式（resolverが宣言する。将来方式の追加はここへ）
METHOD_ID_TOKEN = "id_token"
METHOD_REFRESH_TOKEN = "refresh_token"
METHOD_MAIL_PASSWORD = "mail_password"
#: 型が宣言されていない汎用credential（利用者が「API Key」として投入した値）。
#: **どの搬送方式が正しいかは実APIでの成功をもって決める**（推測で断定しない）。
METHOD_API_KEY = "api_key"
METHOD_MISSING = "missing"

#: api_key方式で試す搬送メカニズム（順序固定・上限2回。無制限の総当たりはしない）
MECHANISM_AS_REFRESH_TOKEN = "api_key_as_refresh_token"
MECHANISM_AS_BEARER = "api_key_as_bearer"

#: 受理する環境変数名（**名前のみ**を報告に使う。値は決して出さない）
ENV_ID_TOKEN = "JQUANTS_ID_TOKEN"
ENV_REFRESH_TOKEN = "JQUANTS_REFRESH_TOKEN"
ENV_MAIL = "JQUANTS_MAIL"
ENV_PASSWORD = "JQUANTS_PASSWORD"
ENV_API_KEY = "JQUANTS_API_KEY"
ACCEPTED_ENV_VARS = (ENV_ID_TOKEN, ENV_REFRESH_TOKEN, ENV_MAIL, ENV_PASSWORD,
                     ENV_API_KEY)

#: http_fn(url, method, headers, payload) -> (status_code, body_bytes)
HttpFn = Callable[[str, str, dict, bytes], Tuple[int, bytes]]


class Secret:
    """秘密値のラッパ（repr/strを潰し、ログ・例外への漏出を型で防ぐ）。"""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """実値の取り出し（HTTPリクエスト構築の1箇所でのみ使う）。"""
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:  # pragma: no cover - 表示専用
        return "Secret(***)"

    __str__ = __repr__


@dataclass(frozen=True, kw_only=True)
class CredentialResolution:
    """resolverの返す認証計画（**秘密の説明は名前のみ**）。"""

    method: str                                   # METHOD_* のいずれか
    secrets: Mapping[str, Secret] = field(default_factory=dict)
    source_names: Tuple[str, ...] = ()            # 由来（env変数名等・値は含まない）
    detail: str = ""                              # 人間向け説明（秘密を含まない）

    @property
    def present(self) -> bool:
        return self.method != METHOD_MISSING

    def secret_values(self) -> Tuple[str, ...]:
        """scrub用の実値列（**この戻り値を出力へ出さないこと**）。"""
        return tuple(s.reveal() for s in self.secrets.values() if s.reveal())


@runtime_checkable
class JQuantsCredentialResolver(Protocol):
    """認証情報の解決契約（方式変更をproviderから隔離する）。"""

    def resolve(self) -> CredentialResolution:  # pragma: no cover - Protocol
        ...


class EnvCredentialResolver:
    """環境変数からのruntime injection（現行J-Quants仕様に対応）。

    優先順位: idToken直接 > refreshToken > mail/password
    （前段ほどネットワーク往復が少なく、秘密の露出面も小さい）。
    """

    def __init__(self, env: Mapping[str, str] = os.environ) -> None:
        self._env = env

    def resolve(self) -> CredentialResolution:
        id_token = self._env.get(ENV_ID_TOKEN, "").strip()
        if id_token:
            return CredentialResolution(
                method=METHOD_ID_TOKEN, secrets={"id_token": Secret(id_token)},
                source_names=(ENV_ID_TOKEN,),
                detail="idToken直接注入（認証往復なし）")
        refresh = self._env.get(ENV_REFRESH_TOKEN, "").strip()
        if refresh:
            return CredentialResolution(
                method=METHOD_REFRESH_TOKEN, secrets={"refresh_token": Secret(refresh)},
                source_names=(ENV_REFRESH_TOKEN,),
                detail="refreshToken → idToken交換（auth_refresh 1回）")
        mail = self._env.get(ENV_MAIL, "").strip()
        password = self._env.get(ENV_PASSWORD, "").strip()
        if mail and password:
            return CredentialResolution(
                method=METHOD_MAIL_PASSWORD,
                secrets={"mail": Secret(mail), "password": Secret(password)},
                source_names=(ENV_MAIL, ENV_PASSWORD),
                detail="mail/password → refreshToken → idToken（auth 2往復）")
        api_key = self._env.get(ENV_API_KEY, "").strip()
        if api_key:
            # 型宣言のない値。搬送方式は実APIで確かめる（下のnegotiate参照）
            return CredentialResolution(
                method=METHOD_API_KEY, secrets={"api_key": Secret(api_key)},
                source_names=(ENV_API_KEY,),
                detail="API Key（搬送方式は実API応答で判定。"
                       f"試行順: {MECHANISM_AS_REFRESH_TOKEN} → "
                       f"{MECHANISM_AS_BEARER}・上限2回）")
        return CredentialResolution(
            method=METHOD_MISSING,
            detail="credential未設定（runtime injectionのみ受理: "
                   + " / ".join(ACCEPTED_ENV_VARS) + "）")


def scrub(text: str, secrets: Tuple[str, ...]) -> str:
    """既知の秘密値を除去する（logs・error_detail・例外文言の最終防波堤）。"""
    out = text
    for value in secrets:
        if value and value in out:
            out = out.replace(value, "***")
    return out


def _default_http(url: str, method: str, headers: dict, payload: bytes) -> Tuple[int, bytes]:
    """HTTP実行 → (status, body)。

    **非2xxは例外にせずステータスとして返す**（urllibはHTTPErrorを送出するため
    明示的に捕捉する）。これが無いと 401/403 が例外経路へ流れ、api_key方式の
    搬送メカニズム判定（refreshToken交換 → Bearer）が実行されない
    ——run #11実測で判明した欠陥の修正。
    """
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


class AuthError(Exception):
    """認証失敗（メッセージは秘密を含まない短いコードのみ）。"""


def validate_topix_payload(payload: object) -> Tuple[str, Tuple[str, ...]]:
    """TOPIX応答のschema/identity検証 → (error_kind, issues)。

    - 期待: {"topix": [{"Date","Open","High","Low","Close"}, ...]}
    - **identity guard**: 銘柄コード/ファンド系フィールドを持つ応答（ETF NAV・
      個別銘柄・先物等）は `identity_mismatch` として拒否する。
    """
    if not isinstance(payload, dict):
        return "schema_error", ("payload_not_object",)
    if "topix" not in payload:
        return "schema_error", (f"missing_topix_key:keys={','.join(sorted(payload))[:60]}",)
    rows = payload.get("topix")
    if not isinstance(rows, list):
        return "schema_error", ("topix_not_array",)
    forbidden = {"code", "netassetvalue", "nav", "fundcode", "contractmonth",
                 "settlementprice", "issue", "securitiescode"}
    issues = []
    for i, row in enumerate(rows[:50]):  # 先頭サンプルで構造検査（全件はingest側）
        if not isinstance(row, dict):
            return "schema_error", (f"row{i}_not_object",)
        lowered = {str(k).lower() for k in row}
        overlap = sorted(lowered & forbidden)
        if overlap:
            # 指数系列に銘柄/ファンド識別子が現れる＝TOPIX指数ではない
            return "identity_mismatch", (f"non_index_fields:{','.join(overlap)}",)
        for required in ("Date", "Close"):
            if required not in row:
                issues.append(f"row{i}_missing_{required.lower()}")
    return "", tuple(issues)


class JQuantsTopixProvider:
    """J-Quants /indices/topix のMarketDataProvider実装。"""

    def __init__(
        self,
        http_fn: Optional[HttpFn] = None,
        *,
        env: Optional[Mapping[str, str]] = None,
        resolver: Optional[JQuantsCredentialResolver] = None,
    ) -> None:
        self._http = http_fn or _default_http
        # resolver優先。env指定は既定resolverの入力（既存呼び出し互換）
        self._resolver: JQuantsCredentialResolver = resolver or EnvCredentialResolver(
            os.environ if env is None else env)
        self.last_auth_method: str = ""  # 解決した方式（秘密を含まない）
        #: **実際にAPIで通った**方式のみを記録する。成功していない方式を
        #: officially supportedと断定しないための区別（監督者P2-G.1レビュー）。
        self.last_auth_method_validated: str = ""
        #: api_key方式で試した搬送メカニズムの足跡（秘密を含まない）
        self.negotiation_trail: Tuple[str, ...] = ()
        #: 実APIで通った搬送メカニズム（未検証なら空）
        self.last_mechanism_validated: str = ""

    @property
    def provider_id(self) -> str:
        return JQUANTS_PROVIDER_ID

    # ------------------------------------------------------------- auth

    def _id_token(self, cred: CredentialResolution) -> Tuple[str, str]:
        """CredentialResolution → (bearer_token, mechanism)。

        失敗はAuthError（秘密を含まない短いコードのみ）。
        api_key方式は**搬送メカニズムを実APIで判定**する（上限2回）:
          1. refreshTokenとして交換 → 成功すればidTokenを得る
          2. 失敗ならBearerへ直挿し（最終判定はdata endpointの応答）
        どちらも「現行仕様である」と断定はせず、成功したものだけを記録する。
        """
        if cred.method == METHOD_ID_TOKEN:
            return cred.secrets["id_token"].reveal(), METHOD_ID_TOKEN

        if cred.method == METHOD_API_KEY:
            api_key = cred.secrets["api_key"].reveal()
            status, body = self._http(
                f"{JQUANTS_BASE}/token/auth_refresh?refreshtoken="
                + urllib.parse.quote(api_key), "POST", {}, b"")
            if status == 200:
                token = json.loads(body).get("idToken", "")
                if token:
                    return token, MECHANISM_AS_REFRESH_TOKEN
            # 交換不可 → Bearer直挿しを試す（data endpointの応答で最終判定）
            self.negotiation_trail = (f"{MECHANISM_AS_REFRESH_TOKEN}:http_{status}",)
            return api_key, MECHANISM_AS_BEARER

        if cred.method == METHOD_MAIL_PASSWORD:
            status, body = self._http(
                f"{JQUANTS_BASE}/token/auth_user", "POST",
                {"Content-Type": "application/json"},
                json.dumps({"mailaddress": cred.secrets["mail"].reveal(),
                            "password": cred.secrets["password"].reveal()}).encode())
            if status != 200:
                raise AuthError(f"auth_user_http_{status}")
            refresh = json.loads(body).get("refreshToken", "")
            if not refresh:
                raise AuthError("auth_user_no_refresh_token")
        else:
            refresh = cred.secrets["refresh_token"].reveal()

        # J-Quants仕様: refreshtokenはクエリ引数（このURLは**永続化もログ出力もしない**）
        status, body = self._http(
            f"{JQUANTS_BASE}/token/auth_refresh?refreshtoken="
            + urllib.parse.quote(refresh), "POST", {}, b"")
        if status != 200:
            raise AuthError(f"auth_refresh_http_{status}")
        id_token = json.loads(body).get("idToken", "")
        if not id_token:
            raise AuthError("auth_refresh_no_id_token")
        return id_token, cred.method

    # ------------------------------------------------------------- fetch

    def fetch_daily_history(
        self, spec: SeriesSpec, *, start: date, end: date
    ) -> ProviderFetchResult:
        symbol = spec.symbol_for(self.provider_id) or ""
        now = datetime.now(timezone.utc)
        #: 永続化されるlocator（token・pagination_keyを含めない）
        public_url = f"{JQUANTS_BASE}/indices/topix?from={start.isoformat()}&to={end.isoformat()}"
        base = dict(provider_id=self.provider_id, series_id=spec.series_id,
                    symbol=symbol, url=public_url, retrieved_at=now)
        if not symbol:
            # baseのurlを空へ差し替える（**base と url= の二重指定はTypeError）
            return ProviderFetchResult(
                **{**base, "url": ""}, error_kind="no_symbol",
                error_detail="catalogに本providerのsymbolなし")

        # ---- STEP 1: credential presence check（未設定ならネットワークを叩かない）
        cred = self._resolver.resolve()
        self.last_auth_method = cred.method
        self.last_auth_method_validated = ""
        self.last_mechanism_validated = ""
        self.negotiation_trail = ()
        if not cred.present:
            return ProviderFetchResult(
                **base, error_kind="no_credentials", error_detail=cred.detail)
        secrets = cred.secret_values()

        started = _time.monotonic()
        mechanism = ""
        try:
            id_token, mechanism = self._id_token(cred)
        except AuthError as exc:
            return ProviderFetchResult(
                **base, error_kind="auth_error",
                error_detail=scrub(str(exc)[:120], secrets))
        except Exception as exc:  # noqa: BLE001 ライブラリ例外を種類へ写像
            return ProviderFetchResult(
                **base, error_kind="auth_error",
                error_detail=scrub(f"{type(exc).__name__}: {str(exc)[:120]}", secrets))
        secrets = secrets + (id_token,)  # idToken自体も秘密（scrub対象へ追加）

        headers = {"Authorization": f"Bearer {id_token}"}
        bodies = []
        rows = []
        issues = []
        pagination_key = ""
        status = 0
        for _page in range(20):  # 安全上限（400日日足は通常1ページ）
            url = public_url + (
                f"&pagination_key={urllib.parse.quote(pagination_key)}"
                if pagination_key else "")
            try:
                status, body = self._http(url, "GET", headers, b"")
            except Exception as exc:  # noqa: BLE001
                return ProviderFetchResult(
                    **base, error_kind="connection", status_code=status,
                    error_detail=scrub(f"{type(exc).__name__}: {str(exc)[:120]}", secrets))
            if status != 200:
                if cred.method == METHOD_API_KEY and status in (401, 403):
                    trail = self.negotiation_trail + (f"{mechanism}:http_{status}",)
                    return ProviderFetchResult(
                        **base, status_code=status, body=b"",
                        error_kind="auth_error",
                        error_detail=("api_key_mechanism_not_accepted: "
                                      + ",".join(trail)))
                return ProviderFetchResult(
                    **base, status_code=status, body=b"",
                    error_kind="http_error", error_detail=f"HTTP {status}")
            try:
                payload = json.loads(body, parse_float=str)
            except json.JSONDecodeError:
                return ProviderFetchResult(
                    **base, status_code=status, body=body,
                    error_kind="parse_error", error_detail="invalid_json")
            # ---- schema / identity guard（ETF NAV・先物・個別銘柄応答を拒否）
            kind, schema_issues = validate_topix_payload(payload)
            if kind:
                return ProviderFetchResult(
                    **base, status_code=status, body=body,
                    parse_issues=tuple(issues) + schema_issues, error_kind=kind,
                    error_detail=";".join(schema_issues)[:160])
            issues.extend(schema_issues)
            # ここまで到達＝Authorizationがdata endpointで受理された
            self.last_auth_method_validated = cred.method
            self.last_mechanism_validated = mechanism
            bodies.append(body)
            rows.extend(payload.get("topix") or [])
            pagination_key = str(payload.get("pagination_key") or "")
            if not pagination_key:
                break
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
        for line_no, row in enumerate(sorted(rows, key=lambda r: str(r.get("Date", ""))),
                                      start=1):
            day = str(row.get("Date", ""))
            try:
                date.fromisoformat(day)
            except ValueError:
                issues.append(f"row{line_no}:invalid_date:{day[:20]}")
                continue
            token = row.get("Close", "")
            token = "" if token is None else str(token)
            records.append(ProviderRecord(trading_date=day, close=token,
                                          open=str(row.get("Open", "") or ""),
                                          high=str(row.get("High", "") or ""),
                                          low=str(row.get("Low", "") or ""),
                                          line_no=line_no))
        return ProviderFetchResult(
            **base, status_code=status, elapsed_ms=elapsed, body=raw_body,
            records=tuple(records), parse_issues=tuple(issues),
            media_type="application/json")


def credential_status(resolver: Optional[JQuantsCredentialResolver] = None) -> Dict[str, object]:
    """STEP 1報告用の状態（**秘密を含まない**: 方式名・由来env名・有無のみ）。"""
    resolution = (resolver or EnvCredentialResolver()).resolve()
    return {
        "present": resolution.present,
        "auth_method": resolution.method,
        # 解決できた方式＝「使える方式」ではない。実API成功のみが検証済み
        "auth_method_validated": "",
        "mechanism_validated": "",
        "source_env_names": list(resolution.source_names),
        "accepted_env_names": list(ACCEPTED_ENV_VARS),
        "detail": resolution.detail,
    }
