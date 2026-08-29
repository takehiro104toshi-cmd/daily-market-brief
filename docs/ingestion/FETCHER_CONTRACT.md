# FETCHER_CONTRACT — Fetcher/Transport契約（Phase 1-C）

## 1. Transport抽象

```python
class HttpTransport(Protocol):
    def send(self, request: FetchRequest, *, timeout: float = 20.0) -> FetchResponse: ...
```

- domain / parser / store はHTTPライブラリへ**直接依存しない**。実装は
  `transport.UrllibTransport`（標準ライブラリのみ。requests/httpx等の新規依存は
  必要が生じた時に理由を添えて追加する）1箇所に隔離。
- 本開発環境はegress遮断のため、テストはscripted transport注入で完全オフライン。
  実行はネットワークのあるGitHub Actions runnerで行う（プロキシ制約は迂回しない）。
- **timeout必須**（既定20秒。呼び出しごとに指定可能）。body読み込みは8MB上限。

## 2. FetchRequest（transient）

source_id / endpoint_id / url / method / headers（タプル）/ etag / last_modified /
requested_at（tz-aware必須）。

**Secret規律（型レベル強制）**: `Authorization` / `Cookie` / `X-Api-Key` /
`Subscription-Key` 等の資格情報ヘッダは構築時にValueError。資格情報の注入機構は
P1-D以降にheader方式・redaction前提で設計する（PARSER_ADAPTER_SPEC §5）。

## 3. FetchResponse（transient）

status_code（0=リクエスト不成立）/ final_url / redirect_chain / permanent_redirect /
content_type / etag / last_modified / retry_after / body(bytes) / retrieved_at /
elapsed_ms / error_kind / error_detail。永続化しない（永続はFetchAttempt＋blob）。

## 4. Retry方針（単純・明示的。無限retry構造上不可）

| 事象 | 扱い |
|---|---|
| timeout / connection系エラー | retry対象 |
| 5xx（500/502/503/504） | retry対象 |
| 429 | retry対象・**Retry-After尊重**（上限120秒。HTTP-date形式はbackoffへフォールバック） |
| 4xx一般・401・403・404・410 | retryしない |
| parser failure | retryしない（取得は成功。解析失敗はparse結果のerrorへ） |

- 総試行数上限: 既定3（RetryPolicy.max_attempts）。backoff: 2秒基数の指数（2,4,8…）。
- scheduler-level retry（別スロットでの再実行等）はP1-C未実装（Phase 12）。

## 5. Conditional GET

- 送信: 過去のFetchAttempt列から `latest_conditional(endpoint_id)` で
  (ETag, Last-Modified) を**導出**し、If-None-Match / If-Modified-Since として送る。
  cursorファイル等の二重保存はしない（tank cursorの設計を導出方式へ置換）。
- HTTP 304: **RawItemを作らない**。FetchAttempt（not_modified=True）だけ記録する
  （health observationの材料になる）。

## 6. Redirect

- redirect chainを`FetchAttempt.redirect_chain`へ全経路保持。
- 301/308経由は`permanent_redirect=True`として記録 = **Source Registry更新の候補**。
  P1-CではRegistryを自動書換えしない（人間承認事項。SOURCE_FAILURE_POLICY §2）。

## 7. 記録・redaction

- 保存されるURL（url / final_url / redirect_chain / RawItem.locator）はすべて
  `redact_url()` 通過後（資格情報らしきクエリ値→`REDACTED`）。
- ログ・error_detailへAPIキー・Authorizationヘッダ・巨大body全文・body previewを
  出さない（error_detailは例外型＋先頭160字のみ）。
- User-Agent: 連絡先（リポジトリURL）を含む正直なUA。SEC等の厳格ソースを扱う際は
  連絡先メール入りUAを環境変数で与える（tank build_user_agentの思想。コードへ固定しない）。

## 8. 例外規約

`Fetcher.fetch()` は例外を投げない（source isolation）。transportの想定外例外も
error_kind="unknown" のFetchAttemptとして記録される。
