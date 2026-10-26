# PHASE 8 / P8-LIVE2 — LOCAL-ONLY REAL HTTPS TRANSPORT（本人の環境でだけ実行する、最小の実 transport）

PILOT2 に要る最小の実 HTTPS transport（凍結 LIVE1 の `Transport` の実装）を追加した gate。**実装と合成の test だけ**。本 gate で実の J-Quants
への request は無く、本 session の cloud の credential は読んでいない。実の実行は監督の承認の後の PILOT2 で、**本人の private ／ local な
環境でだけ**行う。

- 基準: P8-LIVE1 `7cbc85b66879b2e686ccf16cfafda8b7412a062a`（凍結。package の runtime 30 module）。full pytest の基準 5893 passed ／ 2 skipped。
- 規約の authority は凍結の P8-LIVE0。本 gate は規約を解釈し直さない。

---

## 0. 結論

1. 追加した runtime は 1 module: **`src/intelligence/jquants_local_transport.py`**（`LocalHttpsTransport`）。**package
   `screener_intelligence` の外**に置いた（§2）。package の 30 module（LIVE1 ・ID1 ・ID2 ・ADP0 ・EXE を含む）は byte 一致。
2. HTTP library: Python 標準 library の `http.client.HTTPSConnection`（＋ `ssl.create_default_context`）。依存の追加なし。`requests` は repo に
   あるが、redirect の非追随 ・本文の上限 ・1 呼び出し 1 request の契約は `http.client` の方が単純に満たせるので使わない。
3. host は `api.jquants.com`（443 ・HTTPS）に固定。caller は host ・絶対 URL を渡せない（path は凍結 LIVE1 の 2 つだけ、query の key も
   LIVE1 の 3 つだけ。`canonical_query` が credential の key を拒む）。URL 文字列（`https://…`）は作らない。
4. credential は caller が名を選ぶ環境変数（既定 `JQUANTS_API_KEY`）から `get()` のたびに読み、`x-api-key` header に付けて捨てる。
   object に保持せず、`repr` ・`str` ・例外 ・結果に出ない。無い ・空 → network の前に `CREDENTIAL_MISSING`。他の環境変数は読まない。
5. `get()` 1 回 ＝ HTTP GET 最大 1 回。retry ・cache ・pagination の自動追随 ・背景の呼び出し ・log ・filesystem の書き込みは無い。
   予算は凍結 LIVE1 の `RequestBudget` が持ち、9 回目は transport に届かない（test）。
6. redirect は追わない（3xx → `HTTP_STATUS_3xx`。credential を他の origin に送らない）。200 以外は本文を捨てて status だけの error。
   本文の上限 8 MiB（超過 → `RESPONSE_TOO_LARGE`）。JSON object でなければ `RESPONSE_NOT_JSON` ／ `RESPONSE_NOT_OBJECT`。
   timeout は有限（既定 20 秒 ・上限 60 秒）。network の失敗は `NETWORK_TIMEOUT` ／ `TLS_ERROR` ／ `NETWORK_ERROR`（本文 ・詳細なし）。
7. 判定: **P8_LIVE2_LOCAL_HTTP_TRANSPORT_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§12）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch ／ HEAD | `claude/investment-intelligence-phase6` ／ `7cbc85b66879b2e686ccf16cfafda8b7412a062a`（clean） |
| 凍結の anchor | A1 `4162e9c` … LIVE0 `17c9623` ／ LIVE1 `7cbc85b` すべて ancestor。`src` 全体が LIVE1 anchor と byte 一致 |
| full pytest の基準 | 5893 passed ／ 2 skipped |

---

## 2. なぜ package の外か（architecture の判断）

package `screener_intelligence` は authority ・純関数の層で、boundary の guard が **network ・時計 ・環境変数 ・filesystem を module ごとに禁じる**
（`FORBIDDEN_NAMES` に `urllib` ・`socket` ・`environ` ・`getenv`、`FORBIDDEN_ATTRIBUTES` に `urlopen` ・`connect` ・`request`、文字列に `://` なし。
さらに LIVE1 の guard「package に provider の host ・実 transport が無い」）。実 HTTPS transport は本質的に network と環境変数を使うので、
package の中に置くには guard に穴を開ける必要がある。監督の「LIVE1 を patch しない」「凍結の interface を実装する」に従い、**package の外**の
1 module として置き、package の純度の guard を無傷に保った。代わりに:

- registry: `PHASE8_LIVE2_RUNTIME = ("src/intelligence/jquants_local_transport.py",)` を `PHASE8_RUNTIME` に加え（surface の guard ・Phase 7 の
  除外に自動で伝わる）、`PHASE8_PACKAGE_RUNTIME` を package だけの一覧として分けた。
- boundary: 「他の package は Phase 8 を import しない」guard（`test_bo`）に**この 1 file だけ**の例外を置き、その import が
  `jquants_live_model` の 5 つの名前（`ALLOWED_PATHS` ・`LiveInputError` ・`Transport` ・`TransportResponse` ・`canonical_query`）と
  完全一致することを要求する。package の module は transport を import しない（guard）。
- 専用の guard（`test_live2_*` ＋ LIVE2 の test）: 標準 library だけ ・logging ・filesystem ・retry loop なし ・host の literal は 1 つ ・
  `.github` ・`scripts` ・`main.py` ・本番の import 閉包に現れない。

凍結 LIVE1 の `Transport` interface（`get(path, params) -> TransportResponse`）は安全な実装を支えた。`P8_LIVE1_TRANSPORT_CONTRACT_BLOCKER`
は無い。

---

## 3. 契約の表

| 項目 | 値 |
|---|---|
| host ／ port ／ scheme | `api.jquants.com` ／ 443 ／ HTTPS（固定。caller は変えられない。URL 文字列を作らない） |
| path | 凍結 LIVE1 `ALLOWED_PATHS`: `/v2/equities/master` ・`/v2/fins/summary`。他 ・絶対 URL ・`//host` → `PATH_NOT_ALLOWED`（network の前） |
| query | 凍結 LIVE1 `canonical_query`: `code` ・`date` ・`pagination_key` だけ。credential の key → `CREDENTIAL_IN_QUERY`、他 → `QUERY_KEY_NOT_ALLOWED` |
| credential の出所 | 環境変数（既定 `JQUANTS_API_KEY`。名は `[A-Z][A-Z0-9_]{0,63}`）。`get()` のたびに `os.environ.get(<name>)` だけを読む |
| 認証 header | `x-api-key: <値>`（公式 V2。P8-LIVE0 L5 「Headers: x-api-key Required」・L4 「V2 では x-api-key ヘッダーのみ」）。`Accept: application/json` |
| timeout | 既定 20 秒 ・上限 60 秒（`HTTPSConnection(timeout=…)`。connect ・read の両方） |
| 本文の上限 | 既定 8 MiB（1 KiB〜8 MiB で設定可）。`read(limit＋1)` で超過を検知し `RESPONSE_TOO_LARGE`（parse の前） |
| redirect | 追わない（`http.client` は追随しない）。3xx → `HTTP_STATUS_3xx`。`Location` は読まない ・出さない |
| 200 以外 | 本文を捨て `HTTP_STATUS_<code>`（detail `status`）。provider の error 本文は例外に入らない |
| JSON | UTF-8 の JSON object だけ。違えば `RESPONSE_NOT_JSON` ／ `RESPONSE_NOT_OBJECT`（本文は例外に入らない） |
| network の失敗 | `TimeoutError` → `NETWORK_TIMEOUT`、`ssl.SSLError` → `TLS_ERROR`、他の `OSError` ・`http.client.HTTPException` → `NETWORK_ERROR`。detail は `connection` だけ |
| retry ・cache ・log | 無し。`get()` 1 回 ＝ `connection.request` 1 回（source に 1 箇所。`while` なし）。応答の本文は返した後に保持しない。`attempts` は回数だけ |
| 予算 | 凍結 LIVE1 の `RequestBudget`（client が transport の前に消費）。transport に第 2 の予算 ・retry は無い |
| 結果 | 凍結 LIVE1 の `TransportResponse(status, body_text)`（`repr` に本文は出ない） |
| `repr` | host ・環境変数の**名** ・timeout ・上限だけ（値は無い） |

---

## 4. error の赦免

`LiveInputError(code, detail)`（凍結 LIVE1）: code は大文字の code、detail は field 名だけを model が文字の集合で強制する。よって
credential ・本文 ・URL ・host の詳細 ・`Location` ・OS の message は例外に**入り得ない**。test は合成の secret ・本文の sentinel が
`repr` ・`str(exception)` ・`code` ・`detail` ・object の属性に無いことを確かめる。

## 5. memory ・log

filesystem ・log ・cache ・debug の出力の code は無い（`logging` ・`open` ・`Path` ・`write` の不在を guard）。応答の本文は
`TransportResponse` として返した後、transport は参照を持たない。実の data から fixture を作らない（test は合成）。

## 6. 合成の test（`tests/intelligence/test_screener_jquants_local_transport.py`。15 test）

master ・fins の sanctioned request、auth header、secret の非露出（repr ・str ・例外 ・属性）、credential の欠落 ・空 ・他の変数の非読み取り、
query での credential の拒否、絶対 URL ・他 host ・未知 path ・未知 key の拒否、1 `get` ＝ 1 attempt、timeout ・500 ・401 ・403 ・429 の後に
retry なし、301 ・302 ・307 ・308 の非追随と credential の非転送、DNS ・reset ・切断 ・TLS の赦免、不正 JSON ・非 object ・不正 UTF-8 ・
超過の本文、本文の非保持 ・cache なし ・filesystem 書き込みなし、凍結 LIVE1 の予算で 9 回目が transport に届かない、architecture
（標準 library だけ ・host literal 1 つ ・`x-api-key` ・retry loop なし ・本番の閉包 ・`.github` ・`scripts` に無い）。

---

## 7. private ／ local の境界（実行の authority）

- LIVE2 の code は repo に**存在する**が、**J-Quants への実の実行は PILOT2 で、監督の承認の後、本人の private ／ local な環境でだけ**
  authorize される。本 cloud session ・GitHub Actions ・cron ・scheduled task ・cloud runner ・自動の起動 ・背景の fetch には繋がない
  （作っていない。guard が `.github` ・`scripts` ・`main.py` ・本番の import 閉包に transport が無いことを確かめる）。
- Pages ・公開 Morning Brief ・LLM ／ provider の経路 ・顧客向けの出力に配線しない（transport を import する物は無い）。
- 本 session の cloud の J-Quants credential（proxy が注入する物）は本 gate で読んでいない。LIVE2 は `JQUANTS_API_KEY` 等の**本人の環境の**
  変数からだけ読む設計で、本 session でその変数は設定していない。

## 8. PILOT2 の正確な呼び出しの境界（本人の環境で）

```
export JQUANTS_API_KEY=…            # 本人の shell だけ。file ・repo ・chat に書かない
transport = LocalHttpsTransport()   # 既定: JQUANTS_API_KEY ・20 秒 ・8 MiB
budget = RequestBudget(8)           # 凍結 LIVE1。PILOT2 の上限
client = JQuantsLiveClient(transport, budget)
fetch = client.fetch_master("<D0>")                      # request 1
rows = id1_rows(fetch.results)                           # ELIGIBLE_FOR_ID1 だけ（LIVE1）
… propose_bootstrap → 人の審査（accepted_at）→ execute_identity_registration（ID2）→ A1 の確認 …
handoff = verify_identity_for_code(IdentityStore.open(root).history, "<Code>")
fins = client.fetch_fins_summary(handoff)                # request 2〜（発行体ごと。pagination は明示）
… adapt_financial_summary_row（ADP0）→ execute_financial_summary_row（EXE）…
```

本人が行う事（LIVE0 §7 ・§8）: D0 と 1〜3 発行体の選定、`supported_markets=("0111","0112","0113")`、private の data root の初期化、
人の審査の checklist と `accepted_at` の記録、8 request の遵守、廃棄の手順の記録。

## 9. Claude ／ ChatGPT に**貼り戻してはいけない物**

- API key ・環境変数の値 ・header ・URL の全文。
- 応答の本文（raw ・JSON ・行 ・値 ・社名の一覧）。fins の値（Sales ・OP ・NP ・TA）。
- private の data root の journal の内容（A1 ・A2 ・注記 ・保留の行）。
- 例外の全文に本文が含まれる場合の全文（LIVE1 ／ LIVE2 の error は code だけなので、code と detail だけを貼る）。

貼ってよい物: outcome の名（`APPENDED` ・`REUSED` ・`HELD` …）、理由の code、件数、`budget.as_dict()`（path と回数）、digest（manifest ・
reviewed）、record の件数。

---

## 10. 変更の範囲

| 対象 | 状態 |
|---|---|
| `src/intelligence/jquants_local_transport.py` | **新規**（package の外） |
| `tests/intelligence/test_screener_jquants_local_transport.py` | **新規**（15 test） |
| `tests/intelligence/phase8_runtime_registry.py` ・`test_screener_intelligence_boundary.py` | LIVE2 の登録（`PHASE8_LIVE2_RUNTIME` ・`PHASE8_PACKAGE_RUNTIME`）・`test_bo` の 1 file の例外 ・LIVE1 anchor の guard |
| package の 30 module ・Phase 8 の test 12 file ・先行の記録 22 | **byte 一致**（guard `test_live2_*`） |
| `requirements.txt` ・`pyproject.toml` ・`.github` ・`main.py` ・Pages ・config ・legacy | 変更なし |

## 11. 検証

| 項目 | 結果 |
|---|---|
| LIVE2 の test | 15 passed |
| boundary ・registry の guard | passed |
| full pytest | 本文の最終報告 |

## 12. 判定

**P8_LIVE2_LOCAL_HTTP_TRANSPORT_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**
