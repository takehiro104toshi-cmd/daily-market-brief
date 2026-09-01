# JQUANTS_LIGHT_CORE_ARCHITECTURE — Light Core Data Foundation（Phase 2-H）

P2-Gで実証したJ-Quants V2接続を、**TOPIX専用provider**から
**再利用可能なcore data foundation**へ昇格させた記録。

原則: **MINIMAL / REUSABLE / AUDITABLE / FAIL-CLOSED**。
取得可能だから実装するのではなく、**どの機能で使うか説明できるdatasetだけ**を採用する。

## 1. モジュール構成（1機能=1ファイル）

| module | 責務 |
|---|---|
| `jquants_v2_client.py` | 任意path＋params＋pagination＋entitlement判定の**汎用**取得経路 |
| `jquants_light_datasets.py` | dataset registry（endpoint・必須項目・用途・分類・所有ストア） |
| `jquants_records.py` | 構造化レコード6種（God Objectを作らない）＋provenance |
| `jquants_light_store.py` | canonical JSONL（append-only）＋再構築可能SQLite＋query |
| `tokyo_calendar.py` | latest completed Tokyo session の**最小**判定 |
| `p2h_light_pilot.py` | small live pilot（fetch→raw→normalize→canonical→SQLite→query） |
| `p2h_light_probe.py` | entitlement / schema discovery（HISTORICAL PROBE） |

**既存機能を再実装していない**: credential解決・秘密のscrub・原因分類・HTTP実行は
`jquants_v2` からimportして再利用する。live実証済みの
`jquants_v2.JQuantsV2TopixProvider` は**一切変更していない**（TOPIX regressionを守る）。

## 2. identityを潰さない設計

| 区別すべきもの | 実装 |
|---|---|
| Company（企業） vs **listed security（上場銘柄）** | `SecurityMasterRecord` は `security_id`（`jp:security:<code>`）のみを持ち、company entityのidentityを張らない。既存Entity Catalogの責務を侵さない |
| **生close** vs **調整後close** | `close`（C）と `adjusted_close`（AdjC）を別フィールドで保持し、`adjustment_factor`（AdjFactor）も残す。total returnはsourceに存在しないので**作らない** |
| 実績 vs 会社予想 vs 翌期予想 | `net_sales` / `forecast_net_sales` / `next_forecast_net_sales` を別フィールドに分離（F* / NxF* を混ぜない） |
| **公表日** vs **対象期間** | `InvestorTypeFlowRecord` は `published_date`（PubDate）と `period_start`/`period_end`（StDate/EnDate）を分離。`frequency="weekly"` を明示し、日次flowとして扱わない |
| trading_date vs as_of | `DailyPriceRecord.trading_date` は取引日。`as_of` は別概念として空のまま保持 |

## 3. 二重の真実を作らない

**TOPIXはMarket Data Bankが所有**（`index:topix.close.closing.tokyo` のObservation系列）。
P2-Hのlight storeへは**保存しない**。P2-HはTOPIXを
(1) V2経路のregression確認 (2) 取引カレンダー区分の実測検証
の入力としてのみ使う（`ingestion_owner` フィールドで機械的に宣言）。

## 4. 保存規律（既存Data Bank規律の維持）

- canonical: `<INTELLIGENCE_DATA_ROOT>/jquants_light/canonical/*.jsonl`（append-only・
  `record_id` 重複は追記しない＝冪等）
- raw: 既存 `JsonlRawRepository`（blob＋RawItem＋FetchAttempt）を共有。
  **全canonical行が `raw_item_id` で生応答へ辿れる**（pilot実測 0件欠落）
- operational: `index/jquants_light.sqlite3` —— **canonicalのみから再構築可能**
  （pilot実測: 再構築前後の件数が全dataset一致）
- Gitへ大量データをcommitしない（保存先はINTELLIGENCE_DATA_ROOT配下）

## 5. FAIL-CLOSED

- credential未設定 → **ネットワークを1回も叩かず**停止
- 200以外 → 行を1件も返さない（部分成功を成功にしない）
- 必須項目が欠ける応答 → `schema_error` で**1行も取り込まない**
- プラン非対象（403）→ `NOT_ENTITLED` を明示し、**別endpointへ迂回しない**
- pagination は上限つき（loop stormを起こさない）
- 取引カレンダーは**実測検証を通った区分値のみ**営業日扱いする

## 6. P2-Hの境界（実装しないもの）

raw/normalizedまで。**score・推奨・screener・breadth・anomaly・Compass・MCP・
frontend・schedulerは作らない**。full-universe backfillもP2-Hの対象外
（storage/API/query設計を実データで確定するのが目的）。

## 7. scale見積り（pilot実測からの外挿）

| 指標 | 実測 / 概算 |
|---|---|
| universe | 4,441銘柄 |
| 営業日 | 244セッション/年 |
| canonical容量 | **794 bytes / 価格1行** |
| 全銘柄×5年 | 約 **5,418,020行 ≒ 4.3 GB** |
| APIリクエスト | 銘柄あたり1（code指定）→ 全銘柄で約4,441リクエスト |
| pilot実績 | 21リクエスト / 16.9秒 |

full backfillは**必要性・容量・速度を測ったうえで後続taskとして判断**する。
