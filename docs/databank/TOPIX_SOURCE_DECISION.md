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

- **プラン**: Freeプラン=登録のみで利用可・**約2年分・12週間遅延**。
  Light（月額・有料）以上で遅延なしの当日値＋長期履歴。
  → **歴史バックフィルはFreeで可能・Phase 3朝の当日値運用にはLight以上が必要**
  （個人利用は規約上想定されている——最終確認はユーザーの契約時に）。
- **認証**: mailaddress/password → refreshToken → idToken（Bearer）。
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
  セッション数を提示。Freeプランの遅延はここに落ちる）
- `NO_DATA` … 観測なし

G10状態は `RESOLVED` / `HISTORICAL_RESOLVED_CURRENT_BLOCKED` /
`PARTIALLY_RESOLVED` / `BLOCKED` の4値＋reason codeで機械決定する。

### 5.6 run #8実測（credential未投入）

STEP 1で `present: false` / `auth_method: missing` → **TOPIX_CREDENTIAL_MISSING**
として正常停止（J-Quantsへの認証リクエスト0回）。以降のSTEPは
NO_DATA・0行・NT倍率0行を正直に報告し、G10は**PARTIALLY_RESOLVED**
（reason: `topix_credential_missing` / `adapter_implemented_not_live_validated`）。
