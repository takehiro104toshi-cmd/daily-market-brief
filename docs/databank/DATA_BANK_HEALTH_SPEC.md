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

## 3. CRITICAL SOURCE GAPS（Phase 3 blocker・必ず表示）

`phase3_readiness` componentは以下が未解決の間**常にBLOCKED**:

| series | gap | 制約 |
|---|---|---|
| index:topix.close.closing.tokyo | G10 | ETF（1306.T）代用禁止 |
| rates:JGB10Y.yield.closing.tokyo | G11 | 別期間/商品の代用禁止 |
| rates:UST2Y.yield.closing.us | G11 | 別概念yieldの代用禁止 |

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
