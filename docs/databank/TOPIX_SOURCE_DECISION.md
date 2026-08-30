# TOPIX_SOURCE_DECISION — TOPIX供給元の決定（Phase 2-G / G10）

原則: **TOPIX ≠ TOPIX ETF（1306.T等） ≠ TOPIX先物**。ETF・先物を指数seriesへ
投入しない（NO PROXY SUBSTITUTION——監督者裁定）。

## 1. 実測監査（probe run #6・2026-08-30）

| 経路 | 実測 | 判定 |
|---|---|---|
| Stooq `^tpx`（日足history） | HTTP 200でHTML制限ページ（共有IPダウンロード制限G9。run #1〜#7で一貫） | Actionsからは不達 |
| yfinance | TOPIX指数symbolなし（legacy configは1306.T ETFを「参考」としていた——流用禁止） | 不可 |
| JPX公式サイト | ページ到達可（HTML）。**自動取得向けの公開機械可読ヒストリカルCSV/APIは確認できず** | 自動化不適 |
| **J-Quants API** | `api.jquants.com` 到達確認（credential無しは403 JSON——到達性は実証）。JPX子会社 JPX Market Innovation & Research 運営の**公式データAPI**。`/v1/indices/topix` がTOPIX四本値（指数値そのもの）を返す | **採用（第一候補）** |

## 2. J-Quants調査結果

- **プラン能力: PLAN_CAPABILITY = UNVERIFIED**（監督者訂正・P2-G.1レビュー）。
  各プランの遅延日数・履歴範囲は**公式ドキュメントから機械取得できていない**
  （§5.1のとおりdocsはJS描画）。「Free=12週遅延／Light以上=当日利用可」等を
  system ground truthとして固定しない。実credentialでの取得結果、または
  取得可能な公式documentation evidenceで確定する。
  → 必要access tierの断定は**保留**。判定は実測のfreshness verdictで行う。
- **認証**: mailaddress/password → refreshToken → idToken（Bearer）という
  一般に知られた流れをadapterのcapabilityとして実装している。ただし
  **どの方式が現行APIで実際に有効かは実認証成功をもって記録する**（§5.2/§5.7）
  ——成功していない方式をofficially supportedと断定しない。
- **取得フィールド**: Date/Open/High/Low/Close（TOPIX指数値）。

## 3. 実装（`src/intelligence/market/jquants_topix.py`）

- カタログ: `index:topix.close.closing.tokyo` preferred_source=jquants
  （PRIMARY_OFFICIAL・Tier1）。ETF/先物symbolはカタログに存在しない
  （テストで固定）。stooq ^tpxは記録として残すがchainへ入れない。
- **credential規律**: 環境変数（JQUANTS_MAIL / JQUANTS_PASSWORD または
  JQUANTS_REFRESH_TOKEN）からの**runtime injectionのみ**。Git/config/カタログへ
  保存しない。GitHub Actionsでは `secrets.JQUANTS_MAIL` 等の**参照**のみを
  workflowへ記述（値の投入はユーザー操作）。
- 値はJSONを `parse_float=str` で読みfloat非経由。応答bytesをそのままraw保存
  （複数ページは連結を申告）。永続化locatorへtoken/pagination_keyを含めない。
- credential未設定時は `no_credentials` の正直なGAP（捏造・代用をしない）。

## 4. 状態と解除条件

- 機構（provider・カタログ・パイプライン・テスト）は完成。live run #7では
  adapterがpipeline内で実行され `no_credentials` の正直なgapとして記録された
  （FetchAttempt保存・secret非含有URL・捏造ゼロ——経路の結線自体は実証済み）。
- **live実証はユーザーのJ-Quants登録＋repo secretsへのcredential追加後**、
  次のpilot runで自動実行される（成功後にカタログprobe:false化→G10判定）。
- それまでG10は**PARTIALLY_RESOLVED**（供給元決定・経路実装済み・live未実証）
  としてSOURCE_GAPS.md／health reportに正直に表示する。

## 5. P2-G.1 closeout（credential resolver・freshness gating／run #8実測）

### 5.1 認証仕様の実測確認（env名を恒久仕様と仮定しない）

runner上の実API/ドキュメント実測（run #8 probe）:

| 対象 | 実測 |
|---|---|
| `POST /v1/token/auth_refresh`（token無し） | **403** `{"message":"Forbidden"}` |
| `GET /v1/indices/topix`（無認証） | **403** `{"message":"Forbidden"}`——Authorization必須 |
| 公式ドキュメント（gitbook 2ページ） | HTTP 200だが**JavaScript SPAシェル**（9,219B・本文はJS描画）。静的取得では仕様本文を機械抽出できず |

→ **確認できたのは「両endpointが実在し認証必須」までで、フィールド名までは
positiveに確定できていない**（この事実を隠さない）。だからこそ認証方式は
`JQuantsCredentialResolver` 契約の背後へ隔離し、仕様変更時は
**resolverの差し替えのみ**で吸収できる形にした。実credential投入時の
実挙動が最終確認となる。

### 5.2 credential resolver契約（実装）

優先順位付きで解決し、方式名と由来env名**だけ**を報告する（値は出さない）:

| method | 必要env | 認証往復 |
|---|---|---|
| `id_token` | `JQUANTS_ID_TOKEN` | 0回（露出最小） |
| `refresh_token` | `JQUANTS_REFRESH_TOKEN` | 1回（auth_refresh） |
| `mail_password` | `JQUANTS_MAIL` ＋ `JQUANTS_PASSWORD` | 2回 |
| `missing` | — | **0回**（正常停止） |

将来のtoken/API key方式等は新resolverを実装して差し替える（provider本体・
fetch経路は無変更）。

### 5.3 credential safety（実装＋テスト固定）

- `Secret`型でrepr/strを封鎖（うっかりログ出力を型で防ぐ）
- 全 `error_detail` を既知の秘密値でscrub（例外文言経由の漏出も遮断）
- 認証応答（refreshToken/idToken）は**保存しない**——raw payloadはTOPIX
  endpoint応答のみ
- 永続化locator（FetchAttempt/RawItem）に token・pagination_key を含めない
- credential未設定時は**ネットワークを1回も叩かず**停止（大量retryしない）

### 5.4 identity guard（ETF NAV・先物の混入拒否）

応答行に銘柄コード・NAV・限月・清算値等のフィールドが現れた場合は
`identity_mismatch` として**1行も取り込まず**拒否する（TOPIX Price Index
以外を指数seriesへ入れない）。

### 5.5 freshness gating（DO NOT LIE ABOUT FRESHNESS）

「APIが繋がった」だけではRESOLVEDにしない。当日利用可否は
**同一東京セッションの実データ**（既定: 日経平均）を基準に判定する
（休日カレンダーを推測しない）:

- `CURRENT_USABLE` … 基準系列と同一の最新セッションまで揃っている
- `DELAYED_NOT_CURRENT` … 基準より遅れている（`gap_sessions` で遅れ
  セッション数を提示。遅延プランで取得した場合はここに落ちる）
- `NO_DATA` … 観測なし

G10状態は `RESOLVED` / `HISTORICAL_RESOLVED_CURRENT_BLOCKED` /
`PARTIALLY_RESOLVED` / `BLOCKED` の4値＋reason codeで機械決定する。

### 5.6 run #8実測（credential未投入）

STEP 1で `present: false` / `auth_method: missing` → **TOPIX_CREDENTIAL_MISSING**
として正常停止（J-Quantsへの認証リクエスト0回）。以降のSTEPは
NO_DATA・0行・NT倍率0行を正直に報告し、G10は**PARTIALLY_RESOLVED**
（reason: `topix_credential_missing` / `adapter_implemented_not_live_validated`）。

### 5.7 検証済みauth方式の記録（監督者P2-G.1レビュー反映）

- adapterは3方式（`id_token` / `refresh_token` / `mail_password`）を
  **capability**として保持する。
- `auth_method`（解決できた方式）と `auth_method_validated`（**実APIのdata
  endpointが200を返した方式**）を分けて記録・報告する。後者が空の間は、
  どの方式も「現行APIで有効」と断定しない。
- run #8 / run #9時点: `auth_method: missing` / `auth_method_validated: ""`
  ——どの方式もまだ「現行APIで有効」と実証できていない。
- run #9でもcredential未投入のためTOPIXのSTEP 2-8は実行条件未達（**追加の
  network retryは行っていない**——MINI TASK B遵守）。G10は
  PARTIALLY_RESOLVED（`topix_credential_missing`）のまま変化なし。

## 6. P2-G.1 credentialed run（JQUANTS_API_KEY投入後・run #10〜#12実測）

### 6.1 認証方式の判定結果: **確認できず（NOT CONFIRMED）**

ユーザーが `JQUANTS_API_KEY` としてrepository secretsへ投入した値について、
**5つの搬送方式をすべて実APIで試した結果、全て HTTP 403 Forbidden**（run #10）:

| 試した搬送方式 | 実測 |
|---|---|
| refreshtokenクエリ（従来仕様の交換） | 403 `{"message":"Forbidden"}` |
| refreshtoken body渡し | 403 |
| `Authorization: Bearer <値>`（idToken相当） | 403 |
| `x-api-key: <値>` ヘッダ | 403 |
| `Authorization: <値>`（生値） | 403 |
| 2段階チェーン（交換→Bearer→data） | auth 403・idToken取得できず |

公式ドキュメント側も機械確認できず: `openapi.json`・API root は **403**、
gitbook 2ページは 200 だが **JS描画のシェル**（9,219B）で本文を抽出できない。

→ **「JQUANTS_API_KEY が現行の正式な認証方式である」ことは確認できていない**。
したがって旧方式（mail/password → refreshToken → idToken）を「正式仕様」として
推測適用することもしていない。実装は**実APIで成功した方式のみ**を
`mechanism_validated` へ記録する形のまま（現時点では空）。

### 6.2 pilot実測（run #12・STEP 1-8）

| STEP | 実測 |
|---|---|
| 1 credential presence | `present: true` / `auth_method: api_key` / 由来 `JQUANTS_API_KEY` |
| 2 authenticated probe | **auth_error**・http 403・`api_key_mechanism_not_accepted: api_key_as_refresh_token:http_403,api_key_as_bearer:http_403`（上限2回で停止・総当たりなし） |
| 3 historical | raw 0行・25DMA不可 |
| 4 freshness | `NO_DATA`（morning_usable=false） |
| 5 access要件 | PLAN_CAPABILITY=UNVERIFIED・必要tierは断定しない・proxy fallbackなし |
| 6 QA / canonical | TOPIX観測0のため判定なし |
| 7 NT倍率 | 0行（入力欠落日は生成しない） |
| 8 G10 | **BLOCKED**（reason: `auth_failure` / `error:auth_error`） |

API Key値は error_detail・URL・raw payload・FetchAttempt・ログのいずれにも
出力していない（構造化コードとHTTPステータスのみ）。

### 6.3 次に必要なユーザー操作（いずれか）

1. **`JQUANTS_MAIL` ＋ `JQUANTS_PASSWORD`** をrepository secretsへ設定
   （adapterは実装済み・投入されれば次runで自動判定）
2. または**有効な `JQUANTS_REFRESH_TOKEN`**（J-Quantsのリフレッシュトークンは
   有効期限が短いため、期限切れの可能性がある）
3. または `JQUANTS_ID_TOKEN`（短命・検証用途）

投入値が正しい種類・有効期限内であれば、次のpilot runでSTEP 2-8が自動実行され、
G10はA〜Dのいずれかへ機械遷移する。
