# PHASE 11 / P11-A2 — LOOPBACK LOCAL SERVER

Phase 11 の 2 つ目の実装 gate。P11-A1 の governed な read の adapter と UI model を、**loopback だけ ・read-only ・決定論**の local な
HTTP の面で出す `local_server.py` だけを足す。**Phase 11 の凍結ではない。** browser の UI ・PWA の shell ・manifest ・service worker ・
static な file ・browser の保存 ・書き込みは無い（A3 以後）。

- 基準: `P11_BASE` ＝ `d01f6bc01fba783e77cc3a623745b8b033883e1a`。P11-A1 の runtime の commit ＝ `P11_A1`
  （`da806753868da597d50875300064722fd12e4bb8`。意味 ／ runtime の凍結 anchor ではない）。A1 の 3 file は不変。
- 経路: P10 ／ P9 の root → P11-A1 `read_ui_model` → 本 server（`LocalServer.start` → `ThreadingHTTPServer`）→ JSON。他は無い。凍結の P9 ／ P10 の store ・実行器は import しない
  （A1 の公開の API `read_ui_model` ・`ui_model_json_bytes` ・`canonical_json` ・`UiReadError` ・版の定数だけ）。

## 1. bind ・port ・root ・credential

- bind は `127.0.0.1` と完全一致だけ。全ての interface への bind ・LAN の address ・hostname（`localhost` を含む）・空 ・`::1` は `BIND_NOT_LOOPBACK` ／
  `BIND_REQUIRED` で起動を拒む（v1 は IPv4 の loopback だけ）。
- port は 0（OS が割り当て）〜 65535 の整数（`PORT_INVALID`）。特権 port の仮定は無い。bind に失敗すれば `BIND_FAILED`。
- root は明示の `--p10-root` ・`--p9-root`（自動の発見 ・環境の fallback ・既定の private な path なし。無ければ `*_ROOT_REQUIRED`）。
  root は `ServerContext` が持ち、repr ・応答 ・log ・誤り ・起動の出力に出ない。起動の出力は `{"status":"listening","url":...}` だけ。
- `JQUANTS_API_KEY` が空でなく在れば **起動の時に** `CREDENTIAL_PRESENT` で拒む（値は読まない ・出さない。要求ごとの再検査は無い:
  process の環境は起動の後に外から変わらない）。他の環境変数の広い走査はしない。

## 2. 経路 ・method

| 経路 | method | 応答 |
|---|---|---|
| `/health` | GET | 固定の `{"schema_version","status":"ok"}`（store に触れない ・件数なし） |
| `/version` | GET | 固定の schema ／ rules の版だけ |
| `/` | GET | `/health` と同じ固定の JSON（PWA の shell は A3） |
| `/api/view` | POST | P11-A1 の正準の byte をそのまま |
| 他 | — | 404 `NOT_FOUND` ／ 許されない method は 405（`Allow`） |

query の文字列は使わない（path の完全一致だけ。query 付きは 404）。書き込み ・file の閲覧 ・debug ・directory の一覧の経路は無い。

## 3. 要求の検査（`/api/view`）

`Content-Type` は `application/json`（`UNSUPPORTED_MEDIA_TYPE` 415）・`Transfer-Encoding` は拒む ・`Content-Length` は必須 ・0 は
`EMPTY_BODY` ・4096 byte 超は `PAYLOAD_TOO_LARGE` 413 ・UTF-8 ・JSON の object だけ（配列は `NOT_OBJECT`）・鍵は `at` ・`as_of_date`
の完全一致（`UNKNOWN_KEYS` ／ `MISSING_KEYS` ／ 重複は `DUPLICATE_KEY`）・値は 40 文字以下の文字列 ・`at` は offset 付きの ISO の瞬間
（`Z` ・naive ・制御文字は `AT_FORMAT`）・`as_of_date` は `YYYY-MM-DD`（`AS_OF_DATE_FORMAT`）・解析の失敗は `AT_INVALID` ／
`AS_OF_DATE_INVALID`。寛容な変換は無い。id ・文 ・private な値は受けない（鍵が無い）。

## 4. Host ・Fetch Metadata ・header

- `Host` は `127.0.0.1:<bound port>` と**完全一致だけ**（`HOST_REJECTED` 400）。`localhost` は許さない（DNS の rebinding と alias の
  曖昧さを避ける。browser には `127.0.0.1` の URL を渡す）。`X-Forwarded-Host` ・`Forwarded` は見ない。Host の値は log に出さない。
- `/api/*`: `Sec-Fetch-Site` が在れば `same-origin` ／ `none` だけ（`cross-site` ・`same-site` は `FETCH_SITE_REJECTED` 403）。
  `Origin` が在れば `http://127.0.0.1:<port>` だけ。両方が無い要求（CLI ・test の client）は許す（Host ・loopback の bind が守る。
  Fetch Metadata だけに頼らない）。
- CORS の header は出さない。全ての応答に `Cache-Control: no-store` ・`Pragma: no-cache` ・`X-Content-Type-Options: nosniff` ・
  `Referrer-Policy: no-referrer` ・`Cross-Origin-Resource-Policy: same-origin` ・`Content-Type: application/json; charset=utf-8` ・
  `Content-Length` ・`Connection: close`。`Date` ・`Server` は出さない（`send_response_only`。stdlib の解析の失敗の `send_error` も
  上書きして正準の JSON ・同じ header）。

## 5. 応答 ・誤り ・決定論 ・cache

- 成功は P11-A1 の `ui_model_json_bytes` の byte をそのまま（server で再直列化しない）。header は固定なので **応答の全体**が決定論
  （同じ P9 ／ P10 の byte ・同じ `at` ・`as_of_date` → 同じ status ・header ・body）。時刻 ・乱数 ・ETag は無い。
- 誤りは正準の JSON `{"code","detail","schema_version"}`。code: `BAD_REQUEST` ・`UNSUPPORTED_MEDIA_TYPE` ・`PAYLOAD_TOO_LARGE` ・
  `METHOD_NOT_ALLOWED` ・`NOT_FOUND` ・`HOST_REJECTED` ・`FETCH_SITE_REJECTED` ・`VIEW_INPUT_INVALID`（A1 の `INPUT_INVALID` と形の検査）・
  `VIEW_UNAVAILABLE` 503（A1 の `P10_UNAVAILABLE` ・`P9_UNAVAILABLE` ・`P10_INVALID` ・`P9_INVALID` 等。detail ＝ `<code>:<detail>`）・
  `INTERNAL_ERROR` 500（予期しない例外。traceback ・path ・id は出ない）。detail は大文字の code の文字だけ。
- result の cache ・memo は無い。毎回 governed な read（P10 の authority が変われば次の応答が変わる）。

## 6. 並行性 ・log

`ThreadingHTTPServer`（`daemon_threads` ・`request_queue_size` 8 ・handler の socket の timeout 10 秒 ・HTTP/1.0 ・`Connection: close`）。
要求ごとに adapter を呼び、共有の可変な状態は無い（A3 の store は呼び出しごとに開く read-only の像）。log は既定で無し
（`log_message` ・`log_request` ・`log_error` を無効化）。`on_event(method, route, status, kind)` に安全な事柄だけ渡せる
（route は既知の経路名か `UNKNOWN` ・kind は code か例外の class 名。body ・瞬間 ・Host ・path ・root は渡さない）。

## 7. network ・公開 ・凍結

outbound の network は無い（`requests` ・`urllib` ・`http.client` の client ・`create_connection` ・DNS を使わない。test が loopback の
server の socket だけを許して他を罠にする）。GitHub Pages の workflow ・公開の report ・Cloudflare の worker ・通知は `P11_BASE` 以後
不変（guard）。P7 〜 P10 の runtime は anchor と object 一致。

## 8. 観察

P11-OBS-001 〜 026 を引き継ぐ。P11-OBS-027 〜（gate の報告に記録）。
