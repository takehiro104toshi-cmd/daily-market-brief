# CONTEXT_ENGINE_SPEC — Compass Context Engine（Phase 3-B / 2026-09-01）

Phase 3-A のFactを、Morning Compassが使える **structured investment context** へ
変換する層。

## 0. 位置づけ（ロードマップ訂正の反映）

```
DATA → OBSERVATION → FACT(3-A) → CONTEXT(3-B) → NARRATIVE(3-C) → OUTLOOK → COMPASS
```

Phase 3-Bは **Context Engine であって Generator ではない**。
自然言語Compassの生成は **3-Bでは行わない**（3-Cの責務）。

| 3-Bで作る | 3-Bで作らない |
|---|---|
| 「TOPIXは25日移動平均の上」 | 「地合いは良好です」（文章） |
| 「日経はTOPIXを20営業日でアンダーパフォーム」 | 「だから循環物色が起きている」（因果） |
| 「米10-2年スプレッドはSTEEPENING」 | 「金利上昇が株を押し下げた」（因果） |
| 「NT倍率はDOWN（-0.10x）」 | 「RISK_OFF局面」（レジーム分類） |

## 1. CONTEXT ≠ FACT

| | Fact（3-A） | Context（3-B） |
|---|---|---|
| 内容 | 単一の観測・計算値 | Fact **間**の関係・相対状態 |
| 例 | `distance_from_ma25_pct = 2.55` | `index_trend_vs_ma25 = ABOVE`（同Factを**参照**） |
| 再計算 | する（calculation registry） | **しない**（既存Factを参照するだけ） |
| provenance | observation / document / record | **supporting_fact_ids**（Fact IDの集合） |

Contextは **Factを複製しない**。値は `supporting_fact_ids` を辿って取得する。

## 2. 因果を主張しない（STEP 7）

`Relationship` の統制語彙に **`CAUSES` は存在しない**（enumに定義していないので、
実装上も表現できない）。

```
CO_OCCURRING     同時に観測された（因果ではない）
CONFIRMING       同方向で相互確認
DIVERGING        逆方向
MIXED            内部で方向が割れている
INSUFFICIENT_DATA
```

`cross_asset_cooccurrence` は常に `CO_OCCURRING` を持ち、内部の一致度
（CONFIRMING / MIXED / INSUFFICIENT_DATA）は `note` に**併記するだけ**で、
関係そのものを因果に格上げしない。

## 3. 方向の統制語彙と閾値（STEP 8/9）

```
UP / DOWN / FLAT / STRONGER / WEAKER / STEEPENING / FLATTENING /
OUTPERFORM / UNDERPERFORM / ABOVE / BELOW / MIXED / UNKNOWN
```

規則版数 `direction:1.0.0`。**正当化できるflat bandのみ**を定義する。

| unit | flat band | 根拠 |
|---|---|---|
| `pct_point`（金利） | 0.001 | MOF/Treasuryの公表最小刻みが0.001 pct。それ未満は公表精度で解像できない |
| `pct`（指数・為替） | **なし**（厳密な符号） | 精度から正当化できるbandが無いため閾値を置かない |

大きさの区分（SMALL / MODERATE / LARGE）は **導入しない**
（`MAGNITUDE_CATEGORIES_ENABLED = False`）。raw magnitudeを `magnitude` /
`magnitude_unit` として保持し、区分は正当化できる根拠が得られるまで3-C以降へ委ねる。
**modelを埋めるためだけの恣意的な閾値を作らない**（STEP 9）。

## 4. Context types（最小セット）

| context_type | subject | 入力Fact | direction |
|---|---|---|---|
| `index_direction` | 日経 / TOPIX | `index_change_pct` | UP / DOWN / FLAT |
| `index_trend_vs_ma25` | 日経 / TOPIX | `distance_from_ma25_pct` | ABOVE / BELOW |
| `relative_performance` | 日経 vs TOPIX | `return_5session_pct` / `return_20session_pct` | OUTPERFORM / UNDERPERFORM / FLAT（TOPIX基準） |
| `nt_ratio_state` | NT倍率 | `nt_ratio`（当日・前営業日） | UP / DOWN / FLAT |
| `rate_direction` | JGB10Y / UST2Y / UST10Y | `yield_change` | UP / DOWN / FLAT |
| `us_curve_shape` | UST10Y-2Y | `yield_spread`（当日・前営業日） | STEEPENING / FLATTENING / FLAT |
| `fx_direction` | USDJPY | `fx_change_pct` | **WEAKER（円安）/ STRONGER（円高）** |
| `cross_asset_cooccurrence` | 日本株・金利・為替 | 上記の当日Fact 2つ以上 | MIXED / UNKNOWN＋`CO_OCCURRING` |
| `event_proximity` | 銘柄 | `earnings_schedule` | UNKNOWN＋`days_until`（magnitude） |

**USDJPY の意味論（STEP 18）**: `USDJPY UP = 円安（JPY weaker）` /
`USDJPY DOWN = 円高（JPY stronger）`。Context側は円の方向（STRONGER/WEAKER）で
保持し、対ドルの上下と取り違えない。

入力が欠ければ **Contextを作らない**（片側だけの相対比較を作らない）。
欠落は snapshot 側で `MISSING` として報告する。

## 5. 同一session比較（STEP 10）

比較は **同じ `session_date` のFact同士**でのみ行う。前営業日との比較が必要な
context（NT倍率・カーブ）は `previous_session` を明示的に受け取り、
両方のFactを `supporting_fact_ids` に含める。暦日での引き算はしない。

## 6. Market State Vector（STEP 11）

`RISK_ON` / `RISK_OFF` のような**解釈分類は作らない**。次元ごとの方向だけを持つ。

```
japan_equities / nikkei_vs_topix / nt_ratio / japan_rates /
us_rates_2y / us_rates_10y / us_curve / usd_jpy
```

各次元は `Direction`（欠ければ `UNKNOWN`）と `ContextStatus`
（`AVAILABLE / MISSING / STALE / INSUFFICIENT_HISTORY / CONFLICTED / LIMITED_USE`）
の**両方**を持つ。**欠けている次元を黙って省略しない**（STEP 26）。

## 7. Salience（STEP 12/13）

**LLMに重要度を決めさせない。0-100のブラックボックススコアを作らない。**
規則版数 `salience:1.0.0`。

| tier | 条件 |
|---|---|
| `PRIMARY` | 中核次元（指数方向・相対パフォーマンス・NT倍率・金利方向・カーブ・為替）で、基準sessionのFactに基づく |
| `SECONDARY` | 補助次元（25DMA位置・cross-asset同時性）、または7日以内のevent |
| `BACKGROUND` | それ以外（遠いevent・品質限定・方向不明） |

品質・鮮度による**降格のみ**を行い、昇格はしない（FAIL-CLOSED）。
判定に使った要素は `priority_components`（base_tier / freshness / status /
quality / direction / supporting_facts / final_tier …）へ**文字列で全て保存**し、
後から検証できるようにする。並び順は `(tier, type順, |magnitude|降順, subject,
type, context_id)` で**決定論的**。

### 鮮度の基準session

朝のCompassは**当日クローズを知り得ない**。したがって morning snapshot の鮮度は
「cutoff時点で利用できた最新session」（通常は前営業日）を基準とする
（`CompassContextSnapshot.reference_session`）。それより古いsessionしか無い次元は
`STALE` として報告する。

## 8. As-of / look-ahead（STEP 24——hard acceptance criterion）

Contextの `known_at` は **全支持Factが既知になった時点（最も遅い時刻）**。
1つでも `known_at` を持たないFactがあれば `None` ＝ **利用不可**（FAIL-CLOSED）。

`morning_context_snapshot(items, session_date)` は JST 6:00 を cutoff とし、
`known_at <= cutoff` のContextだけを返す。当日クローズ由来のContextは
その朝には**構造的に入らない**。

## 9. Provenance / ID / revision（STEP 21/22/23）

- `context_id = content_id("ctx", type, subject.key(), session_date, rule,
  direction, magnitude, sorted(supporting_fact_ids))` ——**処理時刻を含めない**
  ので再実行は冪等。
- 支持Factが変われば別IDになり、同一identityの旧Contextは `revision_of` で
  繋がれて `STALE` になる（canonicalからは**消さない**）。
- `status = AVAILABLE` のContextは `supporting_fact_ids` が**必須**
  （provenance無しのContextをAVAILABLEにできない）。

## 10. Store / query（STEP 27/28）

- canonical: `<data_root>/context/contexts.jsonl`（**append-only**）
- operational: `<data_root>/context/index/context.sqlite3`（**再構築可能**）
- `contexts`（本体）と `context_facts`（context_id × fact_id）の2表。
  **Factの内容は複製しない**（IDだけを持つ）。
- query: session / type / subject / **fact_id逆引き** / high priority /
  divergence / event / supporting_facts。

## 11. 過去Compassとの整合チェック（STEP 30）

`output/history/<date>/pre_market.html` の前日比サマリー（日経平均 / ドル円 /
米10年金利）の**符号**と、同じ朝のContextの `direction` を突き合わせ、
`MATCH / PARTIAL / CONFLICT / NOT_AVAILABLE` を報告する。

- 比較するのは**方向だけ**。履歴レポートの数値はレガシー収集経路（yfinance等）
  由来で、Market Data Bank（公式ソース）とは取得経路が異なるため大きさは比較しない。
- 比較できない次元は `NOT_AVAILABLE` とし、一致率の**分母から外す**。
- **人間が書いたCompassを再現するようにruleを最適化しない**。これは観測であって
  最適化目標ではない。

## 12. LLM非依存（STEP 32）

Context生成の全経路はネットワーク・LLMを使わない純関数の集合である。
分類・ランキング・方向判定・閾値のいずれにもpromptを使わない。
Contextは**推奨を持たない**（bullish / bearish / buy / sell / target の語彙が
modelに存在しない——STEP 33）。

## 13. ファイル構成

```
src/intelligence/context/
├── model.py               Direction / Relationship / ContextItem / MarketState /
│                          CompassContextSnapshot / make_context_id / 閾値
├── builders.py            Fact → Context（決定論的）
├── salience.py            tier付与と決定論的ranking
├── snapshot.py            morning snapshot / look-ahead / market state
├── store.py               canonical JSONL ＋ SQLite ＋ query
├── compass_alignment.py   過去Compassとの方向整合チェック（STEP 30）
└── pilot.py               実データpilot（STEP 29/30）
```

## 14. 実データ実測（p2d-market-pilot run #18 / 2026-09-01 12:20-12:26 UTC）

GitHub Actions run `33507177439` / job `99853900239`（conclusion: **success**、
duration 5分22秒、Phase 3-B step 12:25:47→12:26:12）。fixtureではなく
Market Data Bankの実観測（各系列266〜285本）から生成したFactを入力にしている。

### 生成（`::P3B_INPUT::` / `::P3B_CONTEXTS::`）

| 項目 | 実測 |
|---|---|
| 対象session | 2026-08-26 / 08-27 / 08-28 / 08-31 / 09-01 |
| 入力Fact | 165（event fact 0——このdata rootにJ-Quants Light storeが無いため） |
| 生成Context | 48（session別: 12 / 13 / 8 / 13 / 2） |
| 重複context_id | **0** |
| provenance欠落 | **0** |
| 冪等性（2回目の追加） | **0件追加**（`idempotent: true`） |
| canonical → SQLite再構築 | 48 → 48（`rebuild_match: true`） |

2026-08-28 のContextが少ない（8件）のは、その営業日に片方の指数のFactしか
無かったため。**欠けた側を補完せず、相対比較・NT倍率のContextを作らなかった**
結果であり、設計どおりの挙動。

### 朝のsnapshotとlook-ahead（`::P3B_SNAPSHOT::`）

| session | reference | 利用可能Context | 充足次元 | leaks |
|---|---|---|---|---|
| 2026-08-26 | (なし) | 0 | 0/8 | 0 |
| 2026-08-27 | 2026-08-26 | 10 | 5/8 | 0 |
| 2026-08-28 | 2026-08-27 | 23 | 8/8 | 0 |
| 2026-08-31 | 2026-08-28 | 33 | 8/8 | 0 |
| 2026-09-01 | 2026-08-31 | 44 | 7/8 | 0 |

- **look-ahead leaks 合計 0 / 当日以降のsessionのContextの混入 0**
  （hard acceptance criterion）。
- 先頭の 2026-08-26 は**pilot窓の境界**で、それ以前のContextを生成していないため
  snapshotが空になる。product側の欠陥ではないが、窓の先頭1営業日はsnapshotの
  証拠にならない（改善案: Factを窓+1営業日分生成する。**未変更・提案のみ**）。
- `usd_jpy` / `nikkei_vs_topix` / `nt_ratio` が `STALE` と報告された日がある。
  最新sessionにその次元のContextが無く、前のsessionのものしか使えなかったことを
  **黙って最新のように見せず**に報告できている。

### 上位Contextの例（`::P3B_TOP::` / 2026-09-01の朝）

```
index_direction        日経平均株価      UP          +0.272112 pct        PRIMARY
index_direction        TOPIX             UP          +0.231027 pct        PRIMARY
relative_performance   日経 vs TOPIX     UNDERPERFORM -3.362312 pct_point PRIMARY (20s)
relative_performance   日経 vs TOPIX     OUTPERFORM   +1.589942 pct_point PRIMARY (5s)
rate_direction         米10年(par)       UP          +0.020000 pct_point  PRIMARY
rate_direction         日本10年          UP          +0.013000 pct_point  PRIMARY
rate_direction         米2年(par)        FLAT         0.000000 pct_point  PRIMARY
us_curve_shape         米10年-2年        STEEPENING  +0.020000 pct_point  PRIMARY
```

いずれも `supporting_fact_ids` を持ち、`priority_components` に
`base_tier / freshness=current_session / status / quality=accept / direction /
supporting_facts / final_tier` が保存されている（**説明可能**）。
自然言語の文・推奨・レジーム分類は1件も含まれない。

### 過去Compassとの方向整合（`::P3B_ALIGNMENT::`）

| 判定 | 件数 |
|---|---|
| MATCH | 3 |
| PARTIAL | 0 |
| CONFLICT | **2** |
| NOT_AVAILABLE | 10（履歴レポート未作成 6 / Context未生成 4） |

比較可能5次元中3一致（3/5）。**CONFLICT 2件は次のとおり**（未修正・観測として記録）:

| 日 | 次元 | 履歴レポート | Context |
|---|---|---|---|
| 2026-08-27 | 日経平均 | -0.15% (DOWN) | UP +0.616077%（session 08-26） |
| 2026-08-28 | 日経平均 | +0.25% (UP) | DOWN -0.196462%（session 08-27） |

同じ2日の `ドル円` / `米10年金利` はMATCHしているため、**日経平均の
「前日比」の基準セッションがレガシーレポート側とData Bank側で食い違っている**
可能性が高い（レガシー履歴では 08-23 / 08-24 / 08-25 の日経平均が同一値
-0.30% で並ぶ日もあり、値が1営業日据え置かれる挙動が見える）。

STEP 30 の指示どおり、**この不一致に合わせてContextのruleを調整していない**。
原因はレガシーレポート側のデータ経路にあると見られ、Phase 3-Bのscope外である。
調査要否の判断は監督者に委ねる（**提案のみ**）。

### query（`::P3B_QUERY::`）

`contexts_for_session` / `high_priority_contexts` / `divergences`(6) /
`event_contexts`(0) / `contexts_by_subject`(6) / `contexts_by_fact`(1) /
`supporting_facts`(1) がいずれも実データ上で動作。
`event_contexts` が0なのは、このdata rootにJ-Quants Lightのcanonicalが
無いためで、event proximity自体はoffline testで固定している。
