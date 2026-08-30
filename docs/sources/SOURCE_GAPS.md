# SOURCE_GAPS — SOURCE_GAP / SOURCE_CONNECTIVITY TRACK（2026-08-30）

P1-D本線と分離した別管理トラック（監督者DESIGN CORRECTION 2）。
**これらはP1-D以降のblockerではない**。解決は個別に承認・実施する。
現況の一次証拠: docs/ingestion/LIVE_VALIDATION_REPORT.md（2026-08-29実測）。

| # | ギャップ | 現況（実測） | 解決候補 | 状態 |
|---|---|---|---|---|
| G1 | **MOF一次情報の空白** | mof_whatsnew（whatsnew.rdf）・jp_mof_press（new.xml）とも404＝MOF公式RSS全滅 | MOFサイトの新フィードURL調査／HTML取得の設計（要承認）。暫定代替は二次報道（nhk_business） | OPEN |
| G2 | **JP公式統計の空白** | jp_stat_release（stat.go.jp/rss/index.rdf）404 | estat_macro（e-Stat API）への移行。**e-Statキー設定のユーザー判断待ち** | OPEN |
| G3 | us_treasury到達不能 | 2回のlive実行とも全attempt timeout（bot防御疑い） | UA/経路調整（連絡先入りUA等）後に再検証 | OPEN |
| G4 | BLS UA要件 | vNext汎用UAに403（Legacy CIのUAは通る＝ソース自体は健在） | vNext実運用UA戦略の確定（連絡先メール入りUAを環境変数注入。コードへ固定しない） | OPEN |
| G5 | EDINET認証 | APIホスト到達確認済み。Subscription-Key未設定 | キー設定（ユーザー判断）。注入機構はingestion/auth.pyで準備済み（header/param方式は公式仕様確認後） | READY（キー待ち） |
| G6 | e-Stat認証 | appId未設定 | 同上（EnvCredentialResolverで対応可能） | READY（キー待ち） |
| G7 | uk_gov廃止 | announcements.atom 404（gov.uk構成変更） | 新フィードURL調査。暫定代替guardian_business | OPEN |
| G8 | RDF live実証未達 | カタログ内RDFフィード3件全滅のため、RDFアダプタはオフラインfixture検証のみ | 新規RDFソース追加時に実証 | DEFERRED |

運用メモ:
- G1/G2/G7のURL調査は外部Webアクセスが必要（開発環境はegress遮断）。
  実施時はlive validationワークフローと同様の最小アクセス原則に従う。
- 本トラックの変更がsource_feeds.yamlへ入る際は、current_healthの更新規律
  （実測evidenceのみ・歴史非上書き）に従う。

## Market Data Bank関連（Phase 2-D追加・2026-08-30）

| # | ギャップ | 現況（live pilot実測） | 解決候補 | 状態 |
|---|---|---|---|---|
| G9 | **Stooq日足history制限** | `q/d/l/`エンドポイントはIP単位ダウンロード制限。共有IP（Actionsランナー）からHTTP 200のHTML制限ページ（4run実測） | ローカルIP実行では有効な経路として保持。runnerからはyfinance一次で回避済み | MITIGATED |
| G10 | **TOPIX指数の供給元** | yfinanceに指数symbolなし（legacyの1306.TはETF——指数seriesへ流用しない）。Stooq ^tpxはG9で不達。JPX公式サイトに自動取得向け公開CSV/API確認できず（P2-G probe run #6） | **P2-G: J-Quants（JPX公式系API）採用・adapter実装済み・API到達実証**。live取得はユーザーのJ-Quants登録＋repo secrets（JQUANTS_MAIL/PASSWORD）投入後に同pilotで自動実証（run #7はno_credentialsの正直なgap記録）。ETF代用はしない | **PARTIALLY_RESOLVED**（供給元決定・経路実装済み・credential待ち） |
| G11 | **JGB10Y・UST2Yの供給元** | Stooq 10jpy.b/2usy.bのみ定義（probe）——G9で不達。yfinance相当symbolなし | **P2-G RESOLVED（live実測 run #7）**: JGB10Y=財務省国債金利情報（constant maturity 15時・265行 2025-07-28〜2026-08-27・latest 2.897 pct）。UST2Y=Treasury Daily Par Yield Curveの別概念series `rates:UST2Y_par`（274行 〜2026-08-28・latest 4.34 pct）＋official UST10Y_par並行系列＋official spread 274行。旧UST2Y（市場実勢）はidentity定義のみ維持——official値を混入しない | **RESOLVED**（両系列live成功・25DMA可能な約13ヶ月・QA/persistence/query PASS） |
| G12 | **東証グロース250指数** | provider symbol未確認（カタログにidentityのみ定義・enabled:false） | JPX公式等の調査 | OPEN |
