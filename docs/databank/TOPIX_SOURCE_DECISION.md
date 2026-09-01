# TOPIX_SOURCE_DECISION — TOPIX供給元の決定（Phase 2-G / G10）

原則: **TOPIX ≠ TOPIX ETF（1306.T等） ≠ TOPIX先物**。ETF・先物を指数seriesへ
投入しない（NO PROXY SUBSTITUTION——監督者裁定）。

> **読む順序（2026-08-30 P2-G.2以降）**: 現行仕様は **§7（V1→V2 migration）** が正。
> §1〜§6は **J-Quants V1時代の実測記録**であり、V1は2026-06-01に終了している。
> 過去の観測はappend-onlyで保全するため削除・書き換えをしていない——
> **現行APIの仕様として §1〜§6 のエンドポイント・認証方式を使わないこと**。

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

## 7. P2-G.2 V1→V2 migration（監督者訂正・2026-08-30）

### 7.1 §6の再解釈（記録は改竄せず、解釈を訂正する）

**J-Quants V1 APIは2026-06-01に終了した**（V2が現行）。§6で「認証方式が確認
できず」と記録した run #10〜#12 の403は、**credential不正と断定できない**。
主要原因候補を `LEGACY_V1_ENDPOINT_USED` / `API_VERSION_MISMATCH` へ再分類する。

§5・§6の実測記録（403の内容・試した搬送方式・日時）は**そのまま残す**
（append-only。過去の観測を消さない・書き換えない）。変わったのは
**解釈**であって観測ではない。

run #13の実測がこれを裏づける:

| リクエスト | 実測レスポンス | 含意 |
|---|---|---|
| `GET /v1/indices/topix` | 403 `{"message":"Forbidden"}` | 旧ルートは形だけ残存 |
| `GET /v2/indices/topix` 他 `/v2/*` 8候補 | 403 `{"message":"The requested endpoint does not exist. Please check the URL, HTTP method, and API version:https://jpx-jquants.com/spec/"}` | **パス自体が存在しない**（＝認証以前の版数・パス不整合） |
| `Authorization: Bearer <key>` | 403（AWSのSigV4形式エラー） | Bearerは搬送方式として誤り |
| API Keyヘッダ（正式方式） | 上と同じ「endpoint does not exist」 | **認証は拒否されておらず、パスが誤っていた** |

→ 403の原因は「API Keyが無効」ではなく「**V1由来のパスをV2として叩いていた**」
可能性が高い。§6.3で挙げた「mail+password / refreshToken を投入せよ」という
次アクションは**撤回**する（V2ではtoken方式そのものが廃止されている）。

### 7.2 確認したV2公式仕様（一次情報。V1から推測変換していない）

| 項目 | 確認値 | 根拠 |
|---|---|---|
| Base URL | `https://api.jquants.com/v2` | 公式クイックスタート(V2)の `API_URL` 実値 |
| 認証 | ダッシュボード発行のAPI Keyをリクエストヘッダで送る（token交換は廃止・API Keyに有効期限なし） | 同上（`headers = {…: api_key}`） |
| TOPIX endpoint | `GET /v2/indices/bars/daily/topix` | 公式仕様ページ／クイックスタート(V2) |
| クエリ | `from` / `to`（`20210901` と `2021-09-01` の両表記可）・`pagination_key` | 同上 |
| 応答エンベロープ | `{"data": [ ... ], "pagination_key": ...}` | 同上（V1の `{"topix": [...]}` ではない） |
| 項目名 | V2で短縮（`Open`→`O` / `High`→`H` / `Low`→`L` / `Close`→`C`。`Date` は不変） | 公式「V1 API から V2 API への変更点」 |
| 提供プラン | TOPIX四本値は**Lightプラン以上** | 公式クイックスタート(V2)のプラン別API一覧 |
| 更新時刻 | **毎営業日16:30頃（JST）** | 同上 |
| V1の扱い | **2026-06-01終了** | 公式「V1 API から V2 API への変更点」 |

### 7.3 PLAN_CAPABILITYの現在地（過度に断定しない）

- **VERIFIED（entitlement次元のみ）**: TOPIX四本値は Light プラン以上。
  この1点は公式ドキュメント evidence で確定した。
- **UNVERIFIED（据え置き）**: プラン別の遅延日数・履歴取得範囲。
  「Free = 12週遅延」等は system ground truth として固定しない
  ——実取得結果（freshness verdict）で判定する。
- 更新16:30（JST）という公表時刻は、Morning Compass（JST朝）が
  **前営業日終値**を使う設計と整合する（当日終値を朝に求めない）。

### 7.4 実装（`src/intelligence/market/jquants_v2.py`・V1とは完全分離）

- `JQuantsV2TopixProvider` … V2専用。V1のパス・token交換を一切参照しない。
- `JQuantsV2CredentialResolver` … `JQUANTS_API_KEY` **のみ**受理する。
  V1のenv名（`JQUANTS_MAIL` / `JQUANTS_PASSWORD` / `JQUANTS_REFRESH_TOKEN` /
  `JQUANTS_ID_TOKEN`）は**V2では受理しない**——旧仕様をV2の既定へ持ち込まない
  ことをテストで固定している。
- provenance … provider は `jquants`（供給元は同一）、版数は `api_version = v2`。
  永続化locatorのURLに `/v2/` が残るため、保存済みデータからも版数を判別できる。
- identity guard … ETFのNAV・先物の限月/清算値・TOPIX以外の指数コードを含む
  応答は `identity_mismatch` として**1行も取り込まない**（NO PROXY SUBSTITUTION）。
- 原因分類 … `api_version_mismatch` / `plan_not_entitled` /
  `credential_rejected` を応答messageから機械分類する。**版数の問題を
  auth_failureとして報告しない**（今回の誤診断を再発させない）。
- 秘密安全 … API Keyはヘッダのみ（URLへ載せない＝永続化されない）。応答本文を
  診断へ載せる前に部分一致でも遮断し、API Gatewayが返す
  SHA-256/Base64ダイジェストのエコーも除去する。
- V1実装 `jquants_topix.py` は**参照用として残す**が、workflow・pilot・
  catalogのいずれからも現行候補として呼ばれない。

### 7.5 V2 authenticated live pilot（run #14・2026-08-30T14:37-14:48Z）

| STEP | 実測 |
|---|---|
| 1 credential presence | `present: true` / `auth_method: api_key_header` / `api_version: v2` / 由来 `JQUANTS_API_KEY` |
| 2 V2 authenticated probe | **HTTP 403**・`cause=plan_not_entitled`・応答message: *"This API is not available on your subscription. If you want more data, please check other plans: …"* |
| 3 historical | raw 0行・25DMA不可 |
| 4 freshness | `NO_DATA`（morning_usable=false・`no_topix_observations`） |
| 5 access要件 | `plan_capability: VERIFIED`（entitlement次元）。TOPIX四本値は**Lightプラン以上** |
| 6 QA / canonical | TOPIX観測0のため判定なし |
| 7 NT倍率 | 0行（入力欠落日は生成しない——片側だけで捏造しない） |
| 8 G10 | **BLOCKED**（reason: `access_level_insufficient` / `plan_not_entitled` / `error:auth_error`） |

**この応答が意味すること（run #10〜#12との決定的な差）**:

- V1時代の403は `{"message":"Forbidden"}` という**内容のない拒否**だった。
- V2では**サブスクリプションを特定したうえで**「このAPIはあなたの契約では
  利用できない」と返っている。つまり **endpoint・API版数・API Keyの搬送方式は
  正しく、サーバ側は契約を識別できている**。残る障害は**プラン権限のみ**。
- ただし `auth_method_validated` は**空のまま**にしている——data endpointの
  200を1度も得ていないため、「認証方式が実APIで検証済み」とは宣言しない
  （成功していないものをvalidatedと書かない規律を維持）。

**PLAN_CAPABILITYの現在地**:

- entitlement次元は **VERIFIED**（公式ドキュメントとlive応答の**2系統**で一致）。
- プラン別の遅延日数・履歴範囲は依然 **UNVERIFIED**（データを1行も取得できて
  いないため、実測で確定できない）。

**必要なユーザー操作（コード側では回避しない）**:

1. J-Quantsの契約プランを **Light以上** へ変更する（TOPIX四本値の提供条件）。
   API Key自体の再発行は不要——同じ `JQUANTS_API_KEY` のまま次のpilot runで
   STEP 2以降が自動実行される。
2. 変更後、freshnessが `CURRENT_USABLE` なら G10 = RESOLVED、
   遅延データのみなら `HISTORICAL_RESOLVED_CURRENT_BLOCKED` へ機械遷移する。

**やらないこと**: 1306.T等ETF・TOPIX先物・近似指数での代用
（NO PROXY SUBSTITUTION）。プラン制約をコードで迂回することもしない。

### 7.6 V2 live closeout（Light plan投入後・run #15・2026-09-01T09:17-09:21Z）

**G10 = RESOLVED**。監督者指定の全条件をlive実測でPASS。

| STEP | 実測 |
|---|---|
| 1 credential | `present: true` / `auth_method: api_key_header` / `api_version: v2` / 由来 `JQUANTS_API_KEY` |
| 2 V2 authenticated fetch | **HTTP 200**・`records_seen: 268`・`pages: 1`・**`auth_method_validated: api_key_header`**（初めて非空——data endpointの200で確定） |
| 2' 応答schema実測 | top keys `["data"]`／row fields `["C","Date","H","L","O"]` ——事前に確認したV2公式仕様（`{"data": [...]}`＋短縮名）と**完全一致** |
| 3 historical | **268営業日**・`2025-07-28` 〜 `2026-09-01`・25DMA可能・unit `index` |
| 4 latest trading date | **2026-09-01**・close `4181.86`・as_of `2026-09-01T06:30:00+00:00`（＝15:30 JST） |
| 5 freshness | **CURRENT_USABLE**（`gap_sessions: 0`・`lag_days: 0`・基準系列 日経平均の最新 `2026-08-31` に対しTOPIXは同一以上のセッション。`matches_reference_tokyo_session`） |
| 6 Morning Compass usability | **可**（`morning_usable: true`・`required_access_level: 現行取得内容で要件充足（実測ベース）`） |
| 7 QA | **`MARKET_OBSERVATION:accept` 268件**（issue 0）。旧HISTORICAL評価も append-only で保持 |
| 8 canonical / SQLite | 永続化検証 PASS（canonical 22,289観測＝別プロセスindex再構築22,289・`recovered_lines: 0`・latest一致16/16・mismatch 0） |
| 9 NT倍率 | **266行**・latest `2026-08-31` = `15.954596 x`・inputs 2件（Nikkei/TOPIXのobservation_id）・`calculation_method: nt_ratio:1.0.0` |
| 10 G10 | **RESOLVED**（`live_authenticated_fetch` / `history_ge_25dma` / `current_session_available` / `matches_reference_tokyo_session`） |

**NT倍率の最新日が 2026-08-31 である理由**（隠さず記録する）: TOPIXは
`2026-09-01` まで取得できているが、基準の日経平均（yfinance経路）は同時点で
`2026-08-31` までしか無い。NT倍率は**同一trading_dateの現物指数close同士**
でのみ生成するため、片側欠落の `2026-09-01` は生成していない（捏造しない）。

**PLAN_CAPABILITYの最終状態**:

- entitlement次元: **VERIFIED**（Light以上でTOPIX四本値が提供される——
  公式ドキュメント・plan変更前の403 entitlement応答・plan変更後の200 の3系統で一致）。
- 遅延・履歴範囲: 本runで**実測により確定**——Light planで
  当日（2026-09-01）終値まで取得でき、履歴は少なくとも `2025-07-28` 以降を
  取得できた（400日レンジ要求に対する実取得。プラン上限の全範囲は本runでは
  要求していない）。

**provenance**: provider `jquants` / `api_version: v2`。永続化locatorは
`https://api.jquants.com/v2/indices/bars/daily/topix?from=…&to=…`
（API Keyはヘッダのみのため**URLに秘密が残らない**）。
