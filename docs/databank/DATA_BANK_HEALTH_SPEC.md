# DATA_BANK_HEALTH_SPEC — Data Bank Health Report仕様（Phase 2-F PART H）

実装: `src/intelligence/databank/health.py`（`build_health_report(data_root)`——
読み取りのみ・自動修復しない）。

## 1. 状態モデル

**HEALTHY / DEGRADED / BLOCKED**＋**reason codes**（単一scoreは持たない——
「なぜその状態か」を機械可読コードで列挙する）。component別state＋overall。

## 2. 報告項目

| 項目 | 内容 |
|---|---|
| canonical files | bank配下のJSONL/SQLite一覧＋サイズ |
| SQLite consistency | index件数 vs canonical件数（不一致=DEGRADED。indexは導出物なのでrebuildで解消と明記） |
| schema version | 現行SCHEMA_VERSION |
| last runs | news backfill / enrichmentの最新run_id（market runはrun manifest側） |
| QA coverage | 文書のassessment被覆率 |
| classification coverage | NewsItemの分類被覆率 |
| review queue | statusごとの件数 |
| corruption | 全storeのrecovered_lines合計（>0でDEGRADED） |
| backup manifest | 最新manifest名・件数（無し=DEGRADED） |
| **critical source gaps** | **常に表示**（下記） |

## 3. CRITICAL SOURCE GAPS（**状態に関わらず常に表示**）

追跡対象（`health.CRITICAL_MARKET_GAPS` が正）:

| series | gap | 制約 | 解決を担うseries |
|---|---|---|---|
| index:topix.close.closing.tokyo | G10 | ETF（1306.T）・先物代用禁止 | 同左（J-Quants **V2**） |
| rates:JGB10Y.yield.closing.tokyo | G11 | 別期間/商品の代用禁止 | 同左（財務省国債金利情報） |
| rates:UST2Y.yield.closing.us | G11 | 別概念yieldの代用禁止 | `rates:UST2Y_par`（Treasury official par yield） |

### 3.1 状態の機械導出（documentationの文字列ではなく実データから）

**live source validation と local data availability は別次元**として扱う
（混同すると「ローカルに無い」を「供給元が無い」と誤報する）。

| 条件 | gap status | phase3_readiness |
|---|---|---|
| カタログでlive実証済み（`probe:false`）＋ローカルに25行以上 | `RESOLVED` | 非blocking |
| カタログでlive実証済み・**ローカルにデータ無し** | `SOURCE_VALIDATED_DATA_NOT_LOCAL` | 非blocking（`DEGRADED`） |
| カタログで未実証（`probe:true` / `enabled:false`） | `PARTIALLY_RESOLVED` | **BLOCKED** |

TOPIXのみ追加で**freshness次元**を見る（「APIが繋がった」だけでRESOLVEDに
しない）。`topix_freshness.g10_state()` が
`RESOLVED` / `HISTORICAL_RESOLVED_CURRENT_BLOCKED` / `PARTIALLY_RESOLVED` /
`BLOCKED` ＋reason codeを機械決定する。

blockingが1件でもあれば `phase3_readiness = BLOCKED`
（reason: `critical_market_source_gaps_unresolved`）、
0件なら `DEGRADED`（reason: `gap_closure_validated_awaiting_supervisor_promotion`
——**Claude Code側の自己承認ではなく監督者判断待ち**を意味する）。

overall stateとは別軸（データ自体が健全でもPhase 3前提は未充足、を混同しない）。

## 4. 実データ実測（2026-08-30）

- overall: **DEGRADED**（reason: market_bank_not_local——market canonicalは
  Actions runner上で実行され本rootに未蓄積、の正直な申告）
- news_bank: **HEALTHY**（documents 3,056 / articles 3,001 / items 3,001 /
  QA coverage 100% / classification coverage 59.5% / index同期 / recovered 0）
- review: HEALTHY（open 88）
- backup: manifest作成後HEALTHY（manifest_20260830T065342Z・15ファイル・29.0MB・
  verify 0/0/0）
- phase3_readiness: **BLOCKED**（critical_market_source_gaps_unresolved）

## 5. 実データ実測（2026-09-01・P2-G.2 closeout後／§4をSUPERSEDE）

G10/G11の供給元がすべてlive実証済みになったため、gap statusの導出結果が変わった
（§4は当時のHISTORICAL RECORDとして残す）:

- phase3_readiness: **DEGRADED**（`gap_closure_validated_awaiting_supervisor_promotion`）
- critical source gaps: 3件とも **SOURCE_VALIDATED_DATA_NOT_LOCAL**
  （`live_validated_on_runner` / `market_bank_not_local`）
  ——供給元は実証済み、canonicalはActions runner上にあり本rootには無い、の正直な申告。
- overall: **DEGRADED**（`market_bank_not_local`）——§4から変化なし。

**BLOCKEDでないことは「Phase 3承認」を意味しない**。次Phaseの開始判断は
監督者に残る（`gap_closure_validated_awaiting_supervisor_promotion` の含意）。
