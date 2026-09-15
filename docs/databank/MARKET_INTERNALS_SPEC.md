# MARKET_INTERNALS_SPEC — Japan Market Internals（Phase 3.5 / 2026-09-02）

日本株市場の「指数の値」だけでなく **市場内部で何が起きているか** を
Evidence-Grounded に観測可能にする層。

```
J-Quants Light（daily bars / master / investor-types）
  → universe（version付き）→ Movement → 集計（manifest）
  → FACT（3-A）→ CONTEXT（3-B）→ Morning snapshot（market_internals 次元）
  → Compass Evidence Package（通常Contextとして受け取る）→ Compass claims（既存validator）
```

因果説明はしない。週次データを日次として語らない。取得できないものを推測しない。
Standard / Premium 限定データを迂回取得しない。恣意的なscoreを作らない。

## 0. Phase 3-C pre-flight（language safety）

### A. Investment Interpretation ≠ Fact

live one-liner 例「米10年国債利回りは前日比+0.040ptの上昇となったことは、株式にとって
逆風とみられる。」は **RISK claim（Investment Interpretation）** であり Fact ではない。

| 確認項目 | 結果 |
|---|---|
| どの rule が許可するか | Compass DNA `JP_US_001`（rates_up_growth_down_banks_up）。`outlook.classify_context` が RATE_DIRECTION(UST10Y/JGB10Y) UP → NEGATIVE に写像 |
| supporting Context | `rate_direction`（米10年国債利回り）。supporting Fact は `yield_change` の観測Factのみ |
| 一般的市場知識を暗黙Factにしていないか | していない。含意は **経験則カタログ**（`knowledge/compass_dna/market_rules.yaml`）への参照として claim に構造化される |
| unsupported causal claim との境界 | 「〜を受けて／〜により」等の因果語彙は language validator が error。含意は「同時に観測され…とみられる（因果関係は特定しない）」の形に限定 |

追加した分離機構:

- `CompassClaim.rule_ref / interpretation_type / market_principle_version`（FACTUALは空）
- `compass/market_principles.py`: 経験則 registry（JP_DIR_001 / JP_US_001 / JP_FX_001 /
  JP_INT_003 / JP_DIR_004 / JP_INT_001）。全idがカタログに存在することをテストで固定
- `compass/principle_validation.py`: `interpretation_without_principle`（warning）/
  `unknown_market_principle` / `principle_context_mismatch` / `factual_with_principle`（error）

### B. confidence → 言語強度

| confidence | 見通し句（`lexicon.OUTLOOK_PHRASES`） |
|---|---|
| HIGH | 堅調な展開が見込まれる |
| MEDIUM | 堅調に推移する可能性がある |
| LOW | 方向感が限定的ながら上値を試す余地がある |

`compass/confidence_validation.py` が OUTLOOK claim の強度マーカー（見込まれる／可能性がある／
余地がある）と `outlook.confidence` を照合し、食い違えば `confidence_language_mismatch`（error）。
旧形「〜となろう」は強い表現（HIGH相当）として扱う。targeted regression:
`tests/intelligence/test_compass_language_safety.py`（34件）。Phase 3-C の live evidence
（`COMPASS_GENERATOR_SPEC.md` §11）は改変していない。

## 1. データ可用性監査（§3 / §4）

| データ | 出所 | Light | 状態 |
|---|---|---|---|
| individual security daily bars | `/equities/bars/daily` | AVAILABLE | **date指定**（1 session=1リクエスト）の可否は live pilot の実応答で判定（§10参照） |
| security master（Mkt / S17 / S33 / ScaleCat） | `/equities/master` | AVAILABLE | 現在snapshot。過去日付指定の可否は実応答で判定 |
| TOPIX / Nikkei | Market Data Bank（3-A/3-B） | — | 既存Fact/Contextを再利用 |
| market turnover | daily bars `Va` の合算 | AVAILABLE | 実装 |
| investor-types（週次） | `/equities/investor-types` | AVAILABLE | 実装（publication gating） |
| market calendar | `/markets/calendar` | AVAILABLE | session決定に使用 |
| 業種別空売り比率 / 売買内訳 / 前場四本値 / TOPIX以外の指数 | Standard / Premium | NOT_ENTITLED | **迂回しない**（DEFER） |
| 52週高値/安値 | 250 session 履歴が必要 | — | 今回は履歴不足のため **実装しない**（近似値を作らない） |

## 2. Universe（§5 / §6）

`config.yaml: market_internals.universe`（`tse_prime_common:1.0.0`）

- market: `Mkt=0111`（プライム。P2-H実測）
- security type: 5桁コード末尾 "0" ＝ 普通株（優先株等の5桁目≠0を除外）
- 業種未設定（S33 = "" / "9999"）を除外（ETF / REIT 等）
- effective date: session 以前で最新の master。無ければ最古の master を遡及適用し
  `master_applied_backwards=True` を manifest に残す（survivorship bias の LIMITATION）
- price validity: universe membership と価格の有無は別に数える（coverage を報告）

## 3. Price movement（§7）

`raw_close_vs_previous_session_raw_close:1.0.0`

- 生終値（C）どうしの比較。adjusted（AdjC）は corporate action の検知にだけ使う
- 当日 `AdjFactor ≠ 1`、または raw と adjusted の騰落率が食い違う日は `corporate_action`
  として**判定しない**（誤方向を数えない）
- 終値なし → `no_close`、前営業日に有効な終値なし（新規上場等）→ `no_previous_close`

## 4. Breadth / aggregation provenance（§14 / §20 / §21）

Fact: `market_advancers / market_decliners / market_unchanged / market_priced_securities /
market_universe_size / advance_decline_ratio / advance_decline_net / advance_ratio_pct`

`AggregationManifest`: `manifest_id / input_count / input_set_hash / universe_version /
universe_hash / calculation_version / price_movement_version / session_date /
input_record_ids`。Fact は manifest_id を evidence（RECORD）と `calculation.inputs` に持ち、
`InternalsStore.manifest_inputs()` で数千件の入力 record_id を再構築できる。

## 5. Turnover / sector / size / trend（§8 / §9 / §11 / §13 / §15）

- turnover: `market_turnover_value`（Σ Va）, `turnover_5session_avg`, `turnover_20session_avg`,
  `turnover_vs_20session_avg_ratio`（揃わなければ INSUFFICIENT_HISTORY）
- sector: **S17（17業種）**。`sector_return_ew_pct`（等ウェイト）, `sector_relative_return_pct_point`
  （universe 等ウェイト平均との差）, `sector_advance_ratio_pct`, `sector_turnover_value`。
  leaders / laggards は差の上位／下位 3（差 < 0.30pt は選ばない）
- size: ScaleCat（source定義）。TOPIX 100 = Core30+Large70 / Mid400 / Small = Small 1+Small 2。
  `size_large_vs_small_pct_point`
- 25日騰落レシオ: Σ値上がり(25) ÷ Σ値下がり(25) × 100（`advance_decline_ratio_25session`）。
  published 値とは universe 差で乖離し得る（LIMITATION）
- breadth trend: 値上がり比率の 5 vs 20 セッション平均差（閾値 3.0pt・version化）

## 6. Investor-type flow（§17–§19）

- Fact `investor_flow_net`: primary_date = period_end（PERIOD_END）、known_at = 公表日 16:00 JST
  （config `publication_hour_jst`）。未公表の週は朝の snapshot に入らない
- Context `investor_flow_state`: UP=買い越し / DOWN=売り越し。note に `frequency=weekly`
- 文は「直近公表週（…、公表日…）では、海外投資家は売り越しであった（週次データ）」に限定。
  「本日は海外投資家が…」は `language:weekly_flow_as_daily` で REJECTED

## 7. Context / snapshot / Compass 統合（§12 / §22–§27）

| Context | direction | tier |
|---|---|---|
| breadth_state | UP / DOWN / FLAT | PRIMARY |
| index_leadership | OUTPERFORM=NIKKEI_LED / UNDERPERFORM=TOPIX_LED × CONFIRMING=BROAD / DIVERGING=NARROW | PRIMARY |
| breadth_trend / turnover_state / sector_leadership / size_leadership / investor_flow_state | 統制語彙 | SECONDARY |

- `CompassContextSnapshot.internals_status`（breadth / turnover / sector_leadership /
  size_leadership / investor_flow → AVAILABLE / MISSING / STALE / INSUFFICIENT_HISTORY / NOT_ENTITLED）
- Evidence Package は internals Context を通常Contextとして受け取り、次元代表を core に固定
  （業種 leaders/laggards は要約と一緒に固定）。`dimension_status` に internals 次元を併合
- Generator は `internals_claims()` を1回呼ぶだけ（validator経路は既存のまま）
- claim 境界: FACTUAL（銘柄数）/ RELATIONAL（上回った）/ INTERPRETIVE（広がり。**JP_INT_001** 参照）

## 8. ファイル構成

```
src/intelligence/internals/
  types.py config.py universe.py price_movement.py breadth.py turnover.py sector.py size.py
  breadth_history.py investor_flow.py facts.py contexts.py snapshot.py store.py ingest.py
  quality.py compass_claims.py adversarial.py backfill_estimate.py pipeline.py pilot.py
tests/intelligence/test_market_internals.py（54件）
config.yaml: market_internals
```

## 9. 実装しないもの（§36）

full 5-year universe backfill / Standard・Premium workaround / causal inference /
theme narrative engine / stock screener / recommendation / company scoring / portfolio /
frontend / scheduler / MCP / order execution / 52週高値安値（履歴不足）

## 10. 実データ実測（p2d-market-pilot run #20 / 2026-09-02 02:55–03:06 UTC）

run: https://github.com/takehiro104toshi-cmd/daily-market-brief/actions/runs/33585035310
（job 100107306304・conclusion = success。Phase 3.5 step は 03:01:18–03:06:13 UTC＝294秒。
先行する market pilot / 3-A / 3-B / 3-C の各 step も success＝3-C regression は live でも PASS）。
credential は `JQUANTS_API_KEY` の runtime injection のみ（値は出力していない）。

### 取得（`::P35_INGEST::`）— date 指定は Light で **使える**

| dataset | mode | requests | rows | http | 備考 |
|---|---|---|---|---|---|
| daily_bars | `?date=YYYY-MM-DD` | 46 | 204,319 | 200 ×46 | 1 session = 1リクエスト・1 page・4,441行・約1.2MB・約4.8秒 |
| listed_master | snapshot / `?date=2026-06-26` | 2 | 8,879 | 200 ×2 | 過去日付の master も取得可（4,439行）→ 遡及適用 0 session |
| investor_types | range（60日前〜） | 1 | 72 | 200 | Section = TSEGrowth / TSEPrime / TSEStandard / TokyoNagoya（各18週） |
| markets_calendar | range（150日） | 1 | 151 | 200 | 営業日区分 `1`（P2-H実測検証済み） |

合計 50 リクエスト / 213,421 行 / 59.6 MB / 227.6 秒。window = 2026-06-26〜2026-09-01
（46 sessions。集計は 06-29〜09-01 の 45 sessions）。fallback（code指定sample）は不使用。

### Universe（`::P35_UNIVERSE::`）

- master（2026-06-26）: プライム 1,562 / スタンダード 1,568 / グロース 595 / その他 532 /
  TOKYO PRO MARKET 182（計 4,439）
- universe `tse_prime_common:1.0.0` = **1,555 銘柄**（除外: market_not_in_scope 2,877 /
  not_common_stock 7）。universe_hash `e347eff73b5c67d30d91c5c2`（45 session で同一）
- プライム内 ScaleCat: Core30 31 / Large70 68 / Mid400 391 / Small 1 479 / Small 2 550 /
  未設定 43（universe内 36）
- LIMITATION: window 内の上場・上場廃止は master snapshot（06-26）に反映されない

### Breadth（`::P35_BREADTH::`）— 直近 6 session

| session | priced | 値上がり | 値下がり | 変化なし | A/D ratio | net | 値上がり比率% | 騰落レシオ25 | 5s avg | 20s avg |
|---|---|---|---|---|---|---|---|---|---|---|
| 08-25 | 1,550 | 845 | 642 | 63 | 1.316 | +203 | 54.52 | 127.60 | 54.77 | 53.00 |
| 08-26 | 1,550 | 976 | 515 | 59 | 1.895 | +461 | 62.97 | 124.40 | 62.72 | 54.61 |
| 08-27 | 1,549 | 711 | 765 | 73 | 0.929 | −54 | 45.90 | 122.96 | 54.91 | 53.56 |
| 08-28 | 1,547 | 867 | 631 | 49 | 1.374 | +236 | 56.04 | 125.44 | 54.74 | 54.64 |
| 08-31 | 1,550 | 882 | 628 | 40 | 1.404 | +254 | 56.90 | 128.84 | 55.27 | 55.52 |
| 09-01 | 1,550 | 842 | 658 | 50 | 1.280 | +184 | 54.32 | 121.68 | 55.23 | 56.75 |

除外の内訳（45 session 合計）: no_close 168（約3.7/日）/ corporate_action 26 / no_previous_close 1。
priced 1,534〜1,553（coverage 98.65〜99.87%）。騰落レシオ25 は 21 session、trend（5/20）は 26 session で計算。

### Turnover（`::P35_TURNOVER::`）

| session | 売買代金（円） | 5s avg | 20s avg | 当日/20s |
|---|---|---|---|---|
| 08-27 | 7,869,513,153,090 | 7.31兆 | 9.48兆 | 0.830 |
| 08-28 | 8,121,689,315,840 | 7.35兆 | 9.26兆 | 0.877 |
| 08-31 | 9,358,035,299,720 | 7.81兆 | 9.22兆 | 1.015 |
| 09-01 | 7,501,188,808,510 | 7.91兆 | 9.01兆 | 0.833 |

履歴Compass HTML に「売買代金」の数値は無く（言及 0）、水準比較は NOT_AVAILABLE（観測のみ）。

### Sector（S17 / 2026-09-01・universe 等ウェイト +0.24%）

leaders: 電気・ガス（+2.95pt, 22銘柄, 値上がり比率 90.9%）/ エネルギー資源（+2.53pt）/
鉄鋼・非鉄（+1.26pt）。laggards: 情報通信・サービスその他（−0.67pt, 344銘柄）/
電機・精密（−0.54pt, 150銘柄, 売買代金 3.13兆円で最大）/ 小売（−0.43pt）。sector_unknown 0。

### Size（ScaleCat / 2026-09-01）

TOPIX 100（99銘柄）+0.74% / Mid400（391）+0.82% / Small（1,029）−0.00% → 大型−小型 = **+0.744pt**
（LARGE_LED）。直近6 session の gap: +0.31 / −0.31 / −0.12 / +0.50 / −0.24 / +0.74。未分類 36。

### Investor-type flow（`::P35_FLOW::`）

最新公表週（run時点）: 対象 2026-08-17〜08-21・公表 2026-08-27（known_at 07:00Z）:
海外投資家 NET_SELL / 個人 NET_BUY / 信託銀行 NET_SELL / 事業法人 NET_BUY。
18週 × 4部門 = 72 flow Fact。09-02 の朝の snapshot でもこの週が使われ（次週は未公表）、
文は「直近公表週（2026-08-17〜2026-08-21、公表日2026-08-27）では、海外投資家は売り越しであった（週次データ）」。

### Fact / Context / Store（`::P35_FACTS::` / `::P35_CONTEXTS::` / `::P35_QUALITY::`）

- Fact 4,123（breadth 8種×45、turnover 2×45、sector 4×765、size 135+135+45、履歴 41/26/26/41/26/21、
  flow 72）。FactStore added 4,123 → 2回目 0（冪等）、rebuild 4,288 = count、LIMITED_USE 0。
  sample: `market_advancers` 2026-06-29 = 1,085、manifest `agg_41cc4a2915287b0cc373369d`
  （input_count 3,106・input_set_hash 記録）
- Context 535（breadth_state 45 / sector_leadership 314 / size_leadership 45 / breadth_trend 26 /
  turnover_state 26 / index_leadership 7 / investor_flow_state 72）。provenance 欠落 0。
  ContextStore 冪等・rebuild 594 一致
- index_leadership 例: 08-26 `NIKKEI_LED|BROAD_CONFIRMATION`、08-27 `TOPIX_LED|NARROW_LEADERSHIP`
  （指数 UP・breadth DOWN）、09-01 `TOPIX_LED|BROAD_CONFIRMATION`
- InternalsStore: manifests 90 / aggregates 990、2回目追加 0、rebuild 一致、
  **manifest 再現性 90/90**（入力 record_id から input_set_hash を再計算して一致）
- duplicate price records 0（204,319 distinct）

### Morning snapshot / look-ahead（`::P35_SNAPSHOT::`）

5 mornings（08-27 / 08-28 / 08-31 / 09-01 / 09-02）すべて internals 5次元 AVAILABLE、
**look-ahead leaks 0**。cutoff で除外された internals Context: 52 / 36 / 24 / 12 / 0
（当日以降の集計は朝には見えない）。

### Compass BEFORE / AFTER（`::P35_COMPASS_BEFORE_AFTER::`）

| morning | BEFORE claims / WHY / outlook | AFTER claims / WHY / outlook | internals claims | one-liner |
|---|---|---|---|---|
| 08-27 | 15 / 3 / UPWARD MEDIUM | 22 / 4 / UPWARD MEDIUM | 7/7 grounded | 不変 |
| 08-28 | 13 / 3 / DOWNWARD MEDIUM | 20 / 4 / DOWNWARD MEDIUM | 7/7 | 不変 |
| 08-31 | 12 / 2 / UPWARD LOW | 19 / 3 / UPWARD LOW | 7/7 | 不変 |
| 09-01 | 13 / 2 / UPWARD LOW | 20 / 3 / UPWARD LOW | 7/7 | 不変 |
| 09-02 | 13 / 3 / DOWNWARD MEDIUM | 20 / 4 / DOWNWARD MEDIUM | 7/7 | 不変 |

全 AFTER が VALID、rejected 0 / warnings 0、引用は全て package 内。outlook（方向・確度）と
one-liner は **変わらない**（internals は根拠の質＝市場内部の明示を増やし、見通しを変えない）。
COVERAGE の欠落次元も不変（usd_jpy STALE 等。internals 5次元は AVAILABLE）。

09-02 の朝の internals claims（全て GROUNDED）:

```
WHAT   東証プライムの普通株では、値上がり842銘柄・値下がり658銘柄・変化なし50銘柄であった。
WHAT   値上がり銘柄数が値下がり銘柄数を上回った。
WHY    解釈（経験則 JP_INT_001）: 値上がり銘柄数が優勢であり、指数の動きには一定の広がりが確認されたとみられる（因果関係は特定しない）。
WHAT   東証プライムの売買代金は20営業日平均の0.83倍で、平均を下回った。
WHAT   業種別では、電気・ガス・エネルギー資源・鉄鋼・非鉄が市場平均を上回り、情報通信・サービスその他・電機・精密・小売が下回った。
WHAT   規模別では、大型株が小型株を上回った（差+0.744pt）。
WHAT   直近公表週（2026-08-17〜2026-08-21、公表日2026-08-27）では、海外投資家は売り越しであった（週次データ）。
```

同じ朝の 3-C 部分は不変: HEADLINE「前営業日（2026-09-01）のTOPIXは前日比+0.62%の上昇となった。
終値は4,181.86であった。」/ OUTLOOK「次の東京セッションは軟調に推移する可能性がある（確度: 中）。…」
（confidence MEDIUM ↔ 「可能性がある」）。

### Adversarial（`::P35_ADVERSARIAL::`）

6 cases / 6 passed: fabricated_advancers → `numeric:unsupported_number`、
breadth_direction_reversed → `direction:direction_mismatch`、weekly_flow_as_daily →
`language:weekly_flow_as_daily`、sector_causal → `language:unsupported_causal_claim`、
breadth_without_internals → `missingness:missing_dimension_assertion`（＋unknown ids）、
valid_breadth_control → GROUNDED。捏造 claim は破棄され draft は決定論的生成で VALID。

### Historical Compass sanity check（`::P35_HISTORICAL::`）

08-27 / 08-28 の履歴 HTML は「広がり」36 / 35 回、「業種」107 / 108 回に言及するが、
「売買代金」「騰落」「海外投資家」の数値は無く、数値比較は NOT_AVAILABLE。人間の文章に
合わせる rule tuning は行っていない（観測のみ）。

### Performance / backfill（`::P35_PERFORMANCE::` / `::P35_BACKFILL::`）

| 指標 | 実測 |
|---|---|
| API requests | 50（daily bars 46） |
| downloaded rows / bytes | 213,421 / 59.6 MB |
| fetch 秒/session | 4.77 |
| aggregation 秒/session | 0.075（45 session で 3.37秒） |
| canonical bytes / price row | 786.1 |
| SQLite | jquants_light 41.6 MB / internals 21.2 MB / facts 6.4 MB / contexts 0.6 MB |
| internals rebuild | 0.41秒 |
| pilot runtime | 294秒 |

見積り（full universe × 5年 = 1,220 session）: records 5.42M / API 1,220 / fetch 97分 /
canonical 4.26 GB / SQLite 1.10 GB / rebuild 38分。rolling 60 session: 266,503 行 / 60 requests /
4.8分 / 210 MB。daily: 1 request / 3.5 MB / 数秒。
**推奨: ROLLING_WINDOW_RECOMMENDED**（朝の運用に必要なのは直近60 session。5年分は
52週高値/安値等の用途が確定してから判断）。5年 backfill は実行していない。

### Security（`::P35_SECURITY::`）

JQUANTS_API_KEY present（runtime injection）/ ANTHROPIC・OPENAI absent。secret値の出力 0、
canonical（prices / manifests / facts / contexts）に credential-bearing locator 0・
`x-api-key` 混入 0。Light 以外の endpoint への接続 0。
