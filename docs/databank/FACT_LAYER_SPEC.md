# FACT_LAYER_SPEC — Evidence-Grounded Fact Layer（Phase 3-A / 2026-09-01）

Data Bankの観測・記事evidence・J-Quants構造化データを、Morning Compass /
Investment Intelligenceが安全に使える **atomic fact** へ変換する層。

## 0. 最上位原則

**FACT ≠ INTERPRETATION ≠ OUTLOOK ≠ RECOMMENDATION**。
Phase 3-Aで作るのは**FACTだけ**。

| 作る | 作らない |
|---|---|
| 「TOPIX終値は4181.86」 | 「海外投資家の買いが相場を押し上げている」 |
| 「TOPIXは直近20営業日で+X%」 | 「TOPIXは今後上昇する」 |
| 「NT倍率は15.954596」 | 「この銘柄は買い」 |

## 1. 既存modelとの責務分担（同一概念を再定義しない）

| model | 責務 | Phase 3-Aとの関係 |
|---|---|---|
| `market.model.Observation` | 系列の観測値（raw/derived） | **入力**。Factの根拠として参照する |
| `evidence.model.FactStatement` | **文章としての**事実言明（`text`＋EvidenceLink） | Phase 1-A資産。**置き換えない** |
| `facts.model.Fact`【新規】 | Compassが計算・比較に使う**定量的atomic fact** | 本層。文章ではない |
| `evidence_qa` GateDecision | 出所の品質判定 | Fact生成条件として**尊重**する |
| `jquants_records` | J-Quants構造化レコード | 用途のあるものだけFact化（全件複製しない） |

## 2. Fact model

```
Fact
├── fact_id            決定論的（subject × type × 日付 × 計算 × 値）
├── fact_type          index_close / return_5session_pct / nt_ratio ...
├── subject            FactSubject（series / entity / security / market）
├── value              FactValue（Decimal・unit・currency／text_value）
├── time               FactTimeContext（primary_date + date_role + as_of + known_at）
├── evidence           FactEvidenceRef[]（observation / document / record / statement）
├── calculation        FactCalculation（name:version + inputs + parameters）
├── status             usable / limited_use / unusable / superseded
├── conflict_state     agree / conflict / stale / superseded / unknown
└── revision_of        値が変わったときの履歴リンク
```

**不変条件**: `usable` なFactは **evidence 1件以上**と**値**を必ず持つ
（provenance無しのFactをusableにしない）。`FactValue.value` は **Decimal限定**
（floatは型で拒否）。

## 3. 決定論的ID / revision

`fact_id = content_id(fact_type, subject, primary_date, calculation_method, value)`。
**処理時刻を含めない**ため、同じGround Truthからは何度生成しても同じID
（＝冪等・増分生成が可能）。値が変われば別IDになり、storeが `revision_of` を張って
旧Factを `SUPERSEDED` にする——**canonicalからは消さない**。

## 4. as-of意味論（STEP 20。混同しない）

| 日付 | 意味 | 使うfact type |
|---|---|---|
| `trading_date` | 取引日 | index_close / yield_level / fx_level / 変化率 / MA / NT倍率 |
| `event_date` | 出来事の発生・効力発生日 | earnings_schedule |
| `publication_date` | 公表日 | reported_financial_value / company_forecast_value / document_published |
| `period_end` | 対象期間の末日 | 週次needs（investor flow等・将来） |
| `as_of` | 値が指す時点 | 全fact共通 |
| **`known_at`** | **システムから見て既知になった時刻** | **morning availability / look-ahead判定はこれだけを使う** |

## 5. Morning availability / look-ahead防止（STEP 19/21）

`morning_snapshot(facts, session_date)` は当日 **JST 6:00** をcutoffに、
`known_at <= cutoff` のFactだけを返す。

**FAIL-CLOSED**: `known_at` が無いFactは「その時点で既知だった」と**見なさない**。
分からないものを使えることにしない。

## 6. 計算規律（STEP 8/12）

| calculation | version | 生成しない条件 |
|---|---|---|
| `change_abs` | 1.0.0 | 片側欠測 |
| `return_pct` | 1.0.0 | 片側欠測 / 基準が0 |
| `moving_average` | 1.0.0 | **必要session数不足** / 窓内に欠測 |
| `distance_from_ma_pct` | 1.0.0 | MA無し / MAが0 |
| `nt_ratio` | 1.0.0 | **同一trading_dateの入力が揃わない** / 分母0 |
| `yield_spread` | 1.0.0 | 同一trading_dateの入力が揃わない |

**forward fill / backfill / 0補完 / 近傍日代用はしない**。不足なら**Factを作らない**。

## 7. session-aware（STEP 9）

前営業日・N営業日リターン・移動平均は**観測が存在するセッション列**の上で数える
（暦日で数えない）。P2-Hで実測検証した東京取引カレンダー
（`tokyo_calendar`）はTOPIX freshness側で利用可能。

## 8. QA統合（STEP 16）

| 由来evidenceのQA | Fact |
|---|---|
| `accept` / `accept_with_warnings` | `USABLE` |
| `limited_use` | **`LIMITED_USE`**（黙って通常Fact扱いしない。snapshotは既定で除外） |
| `reject` | **Factを作らない** |

## 9. source conflict（STEP 15）

同一 subject × fact_type × 日付 で値が割れたら**両方保持**して全件 `CONFLICT`、
相手のfact_idを相互に記録する。**勝手に勝者を決めない**
（truth arbitration engineは作らない）。1件だけなら `UNKNOWN`（AGREEと断定しない）。

## 10. store / query（STEP 17/18）

- canonical: `<INTELLIGENCE_DATA_ROOT>/facts/facts.jsonl`（**append-only**）
- operational: `facts/index/facts.sqlite3`（**canonicalのみから再構築可能**）
- query: latest / by date / range / entity / series / **by evidence source** /
  **derived inputs** / conflicted / evidence refs（citation用）

## 11. news factの境界（STEP 13/14）

**LLMによる自由要約をFactにしない**。Phase 3-Aで作るのは
`document_published`（「その情報源がその日時にその見出しを公表した」）のみで、
見出しは**原文のまま**保持し、正規化本文中の excerpt span を持つ
（citation-ready）。数値抽出・イベント分類・企業紐付けはPhase 3-B以降の責務。

## 12. Fact Layer ≠ Data Duplication（STEP 25）

J-Quantsレコードのうちintelligence用途が説明できるものだけをFact化する:
**採用** = earnings_schedule / reported_financial_value / company_forecast_value。
**非採用** = security master（参照マスタ）/ 日次価格（現行スコープ外）/
カレンダー（session判定基盤）/ 週次需給（daily factではない）。

## 13. 実測（live pilot run #17・2026-09-01）

- 入力: Nikkei 267 / TOPIX 268 / JGB10Y 267 / UST2Y_par 275 / UST10Y_par 275 /
  USDJPY 285セッション、QA判定 22,325件
- 生成: **165 facts / 14 fact types / 5セッション**、provenance 165/165、
  derived with inputs 135
- canonical 165 → **SQLite再構築165（一致）**
- **morning snapshot 5セッション: 21 / 54 / 87 / 125 / 153 facts、
  look-ahead leak 0、全セッションで未来日付なし**
- data quality: 重複fact_id 0 / provenance欠落 0 / derived入力欠落 0 / conflict 0
