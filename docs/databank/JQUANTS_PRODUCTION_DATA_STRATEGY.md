# JQUANTS_PRODUCTION_DATA_STRATEGY — J-Quants Light の production 運用設計（Phase 3.6 / 2026-09-02）

Phase 3.5 で実測した J-Quants Light（daily bars / master / calendar / investor-types /
financial summary / earnings calendar / TOPIX）を、pilot data source から
**production-grade incremental market data source** へ昇格させるための運用設計。
新しい分析機能は追加しない。実装は `src/intelligence/jquants_ops/`。

## 1. J-Quants First（project-wide rule）

`docs/databank/JQUANTS_FIRST_RULE.md` と `CLAUDE.md` に導入。registry（`registry.py`）と
gate（`capability_gate.py`）を通してから data source を決める。

## 2. Capability registry（`registry.py`）

| dataset | endpoint | plan | entitlement | strategy | class | role | verified |
|---|---|---|---|---|---|---|---|
| topix | /indices/bars/daily/topix | Light | AVAILABLE | ALREADY_INGESTED（Market Data Bank） | DAILY | REQUIRED | run #20 |
| markets_calendar | /markets/calendar | Free/Light | AVAILABLE | ALREADY_INGESTED | REFERENCE | REQUIRED | run #20 |
| daily_bars | /equities/bars/daily | Free/Light | AVAILABLE | ALREADY_INGESTED | DAILY | INTERNALS | run #20（date指定 46 sessions） |
| listed_master | /equities/master | Free/Light | AVAILABLE | ALREADY_INGESTED | REFERENCE | INTERNALS | run #20（date指定可） |
| investor_types | /equities/investor-types | Light | AVAILABLE | ALREADY_INGESTED | WEEKLY | OPTIONAL | run #20 |
| fins_summary | /fins/summary | Free/Light | AVAILABLE | ALREADY_INGESTED | EVENT_DRIVEN | NONE | P2-H run #3 / run #19 |
| equities_earnings_cal | /equities/earnings-calendar | Free/Light | AVAILABLE | ALREADY_INGESTED | EVENT_DRIVEN | OPTIONAL | P2-H run #3 |
| fins_earnings_date | /fins/earnings-date | Free | UNKNOWN（HTTP 400） | DEFERRED | EVENT_DRIVEN | NONE | P2-H run #1 |
| indices_bars_daily | /indices/bars/daily | Standard | NOT_ENTITLED | PLAN_UPGRADE_CANDIDATE | DAILY | NONE | run #1 403 |
| markets_short_ratio | /markets/short-ratio | Standard | NOT_ENTITLED | PLAN_UPGRADE_CANDIDATE | DAILY | NONE | run #1 403 |
| fins_dividend / fins_details | /fins/dividend, /fins/details | Standard | NOT_ENTITLED | DEFERRED | EVENT_DRIVEN | NONE | run #1 403 |
| equities_bars_am / markets_breakdown | /equities/bars/daily/am, /markets/breakdown | Premium | NOT_ENTITLED | DEFERRED | DAILY | NONE | run #1 403 |
| nikkei225 / usd_jpy / us_treasury_par / jgb10y | （J-Quants外） | n/a | — | ALTERNATIVE_APPROVED_SOURCE | DAILY | REQUIRED/OPTIONAL | run #20 |

各 entry は publication_semantics / historical_depth / pagination / request_pattern /
canonical_store / consumers / fallback_policy / refresh_policy / known_at_rule /
last_live_verified_at を持つ（`registry_rows()`）。**既知の 403 endpoint は再 probe しない**。

## 3. Dataset frequency classification

DAILY: daily_bars, topix（＋代替 source の Nikkei/FX/金利）／ WEEKLY: investor_types／
EVENT_DRIVEN: fins_summary（開示）, equities_earnings_cal（予定・毎朝 refresh）／
REFERENCE: markets_calendar, listed_master（週1 refresh）／ ON_DEMAND: なし（現時点）。

## 4. Morning data contract（`morning_contract.py`）

cutoff = 朝 06:00 JST。DAILY は **前営業日（latest completed session）**、WEEKLY は cutoff までに
**公表済み**の最新週（対象週 ≠ 公表日）、REFERENCE は前営業日以前で最新の snapshot（master は
7 日以内に refresh）、EVENT は公表済み予定（未来の予定日は look-ahead ではない）。
「今日のセッション」は入力にならない。REQUIRED（topix / calendar / Nikkei）が欠ければ Compass 不可、
INTERNALS（daily_bars / master）が欠ければ DEGRADED、OPTIONAL が欠ければ警告。

## 5. Rolling window（`rolling_window.py` / `config.yaml: jquants_ops`）

| 項目 | 値 | 意味 |
|---|---|---|
| seed_sessions | 70 | 初期構築で取る session 数（active + buffer） |
| active_calculation_sessions | 60 | 朝の指標計算に使う直近 session |
| safety_buffer_sessions | 10 | corporate action / 欠落 / 部分 session の余裕 |
| max_metric_window | 25 | 最長の指標窓（25日騰落レシオ） |
| required_sessions | 35 | 朝に保持していなければならない最小（25 + 10） |
| retention | canonical append-only / SQLite keep-all | **rolling ≠ 削除** |

`WindowPolicy.validate()` が「active ≤ 25」「buffer < 5」「seed < active + buffer」を拒否する
（25 ちょうどの設計は禁止）。

## 6. Initial seed / daily incremental（`incremental.py`）

seed: calendar → expected sessions → master snapshot（開始日＋7日ごと＋当日）→ daily bars
（1 session = 1 request）→ investor-types → earnings calendar → validate → canonical → SQLite →
Facts → Internals。daily: latest completed session → gap detection → **欠落 session だけ取得**
→ append（record_id 冪等）→ **affected rolling metrics only**（最初の新規 session − 26 session
から末尾までを再生成。Fact/Context は決定論的 ID で重複しない）。毎朝 60 session を
全取得し直さない。

## 7. Session gap / repair（`session_gap.py`）

期待 session（validated calendar）× canonical 行数 → CURRENT / MISSING_SESSION /
PARTIAL_SESSION（行数 < 中央値 × 0.90）/ STALE / FUTURE_DATA / CALENDAR_UNKNOWN。
repair は active window 内の欠落だけ（`UpdatePlan.repair_range` を機械可読に記録）。
full rolling window 再取得を default にしない。

## 8. Listed master（`master_refresh.py`）

`?date=` で過去 snapshot を取得できる（run #20 実測）。seed 開始日＋週1回の snapshot を
append-only に蓄積し、session ごとに「session 以前で最新」を使う。
**KNOWN_LIMITATION_HISTORICAL_UNIVERSE**: snapshot 間（≤7日）の上場・廃止は反映されない。
推測で membership を補完しない。変更検出: added / removed / market / S17 / S33 / ScaleCat。
refresh は週1回＋イベント時（毎朝は取らない）。

## 9. Corporate action（`corporate_actions.py`）

breadth = 生終値 vs 前営業日生終値（corporate action 日は EXCLUDED・件数を残す）／
returns = 同じ raw change_pct の等ウェイト（除外銘柄は平均に入れない）／
rolling = 金額・件数ベースで影響なし／ AdjC = 検知のみ。version = price_movement:1.0.0。

## 10. Weekly flow / financial summary / earnings calendar / TOPIX

- investor_types: 毎朝 1 request（from = 最新 period_end − 14日）。新規公表週だけ追記。公表前は使わない。
- fins_summary: 全銘柄を毎朝取らない。**event-driven**（前営業日に決算予定があった銘柄だけ code 指定、
  上限 200）。`date` 指定は run #21 で実測済み（HTTP 200、14 行 → date mode AVAILABLE、§14.1）。実績／当期予想／翌期予想の分離維持。
- equities_earnings_cal: 今日〜+90日を毎朝 1 request。known_at = 取得時刻（公表済み予定のみ）。
  日程変更は新 record（旧 record は残す。消費側は code ごとに最新 retrieved_at）。
- topix: 既存 V2 provider 不変。毎朝 1 request（差分）。Nikkei との same-session alignment を確認。

## 11. Storage / request budget（`storage_budget.py` / `request_budget.py`）

run #21 の実測（isolated pilot root、daily_bars 32 session・master snapshot 8 本）を基に算出。

### 11.1 実測ストレージ（pilot root）

| store | 実測 |
|---|---|
| J-Quants Light canonical JSONL（master snapshot 8 本含む） | 141.3 MB |
| J-Quants Light SQLite | 38.0 MB |
| raw payload（provenance） | 51.1 MB |
| facts canonical / SQLite | 4.64 MB / 4.19 MB |
| contexts canonical / SQLite | 0.32 MB / 0.40 MB |
| price rows | 142,187 行（canonical 994 B/行） |

### 11.2 増分予算（1 session あたり）

| store | 日次 | 月次（20 session） | 年次（244 session） |
|---|---|---|---|
| canonical prices | 3.49 MB | 69.8 MB | 852.0 MB |
| light sqlite | 0.90 MB | 18.1 MB | 220.7 MB |
| master canonical（週1 snapshot） | 0.80 MB | 16.0 MB | 195.1 MB |
| internals sqlite | 0.47 MB | 9.4 MB | 114.9 MB |
| facts canonical / sqlite | 0.13 / 0.14 MB | 2.6 / 2.7 MB | 31.3 / 33.5 MB |
| contexts canonical / sqlite | 0.01 / 0.01 MB | 0.3 / 0.3 MB | 3.5 / 3.0 MB |
| **合計** | **5.96 MB** | **119.2 MB** | **1,453.9 MB** |

retention: canonical は append-only（rolling window は計算窓であり削除ではない）。SQLite は canonical
から再構築可能。1 年運用で約 1.45 GB。**5 年 backfill はこの予算に含まれない**（実施しない）。

### 11.3 request 予算（scenario 別）

| scenario | 内訳 | 合計 |
|---|---|---|
| 通常の朝 | topix 1 / daily_bars 1 / investor_types 1 / equities_earnings_cal 1 | **4** |
| 週次 refresh | markets_calendar 1 / listed_master 1 | 2 |
| master refresh のみ | listed_master 1 | 1 |
| event refresh（決算日） | fins_summary ≤ 20（code 指定） | ≤ 20 |
| repair 日 | daily_bars 3 / listed_master 1 | 4 |
| 初期 seed | calendar 1 / master 15 / daily_bars 70 / flow 1 / earnings 1 / topix 1 | 89 |

pilot 実績: seed 40 / repair 2 / daily 1 / rerun 0 = **45 request**（全部 Light endpoint、NOT_ENTITLED probe 0）。

## 12. Failure / retry / schema drift（`failure_policy.py` / `schema_drift.py`）

AUTH_FAILURE / NOT_ENTITLED / RATE_LIMIT / TIMEOUT / HTTP_ERROR / SCHEMA_CHANGE /
EMPTY_RESPONSE / PARTIAL_DATA / SESSION_GAP / NO_CREDENTIALS。retry は RATE_LIMIT / TIMEOUT /
HTTP_ERROR のみ、最大 2 試行・backoff 2s→4s。auth / entitlement / schema は retry しない。
impact: REQUIRED 失敗 → ABSTAIN、INTERNALS → DEGRADED、OPTIONAL → CONTINUE（gap/partial は DEGRADED）。
schema: unknown field 追加（取り込み継続・registry 更新候補）と required 欠落（0 行取り込み）を区別。

## 13. Health / readiness / capability gate / plan upgrade / 52週

- `health.py`: dataset × latest_expected / latest_available / latest_stored / freshness / gap_count /
  coverage / last_fetch / last_success / last_error / entitlement。
- `readiness.py`: READY / READY_WITH_WARNINGS / DEGRADED / NOT_READY（required / internals / optional）。
- `capability_gate.py`: 監査結果は JQUANTS_FIRST_RULE.md の表のとおり。
- `plan_upgrade_register.py`: markets_short_ratio のみ P2 候補。他は LIGHT_SUFFICIENT / NOT_NEEDED。
- `fifty_two_week.py`: **IMPLEMENT_LATER**（250 session が daily incremental で自然に蓄積する。
  5年 backfill はしない。Compass DNA に rule が無いため INTERPRETIVE 化もまだ不可）。

## 14. 実データ検証（p2d-market-pilot run #21）

- run: https://github.com/takehiro104toshi-cmd/daily-market-brief/actions/runs/33588143976
  （success、03:43:53Z–03:57:46Z。Phase 3.6 step 03:53:51–03:57:43 = 231.8 s）
- 実行: `python -m src.intelligence.jquants_ops.pilot --mornings 4`、isolated root
  `<runner temp>/intelligence_data/jquants_ops_pilot`（production root 不変）。
- credential: `JQUANTS_API_KEY` のみ runtime injection。値は出力していない。

### 14.1 Calendar / seed

| 項目 | 実測 |
|---|---|
| calendar | 140 trading days（211 行、2026-11-01 まで） |
| latest_completed / previous | 2026-09-01 / 2026-08-31 |
| expected window | 2026-07-17 .. 2026-09-01（31 session） |
| seed | 29 session、40 request、179.5 s（6.19 s/session）、失敗 0 |
| 意図的欠落 | 2026-08-10（窓内）と 2026-09-01（最新）を seed から除外 |
| master snapshot | 8 本（07-17, 07-24, 07-31, 08-07, 08-14, 08-21, 08-28, 09-02）＝ `?date=` 週次 |
| その他 dataset | listed_master 4,440 / investor_types 32 / earnings_cal 1 / fins 14 行 |
| fins `?date=2026-08-31` | HTTP 200、14 行、1 page → **date mode AVAILABLE** |
| 初期 build | 28 session、facts 2,519、contexts 301、2.45 s |

### 14.2 Repair（pass 1、as-of previous session）

| 段階 | 結果 |
|---|---|
| gap 検出 | MISSING_SESSION: 2026-07-16, 2026-08-10（expected_rows 4,443 = median） |
| plan | REPAIR、sessions_to_fetch 2、request 見積 2 |
| apply | fetched 2 / 2 request / 8,887 行 / 10.13 s、各 1 attempt |
| recompute | window 07-16..08-31（30 session）、facts added 290 / skipped 2,413、contexts added 55 / skipped 268、2.50 s |
| gap 検出（後） | **CURRENT** 31/31 |

### 14.3 Daily incremental（pass 2）→ rerun（pass 3）

| 段階 | 結果 |
|---|---|
| gap 検出 | STALE: 2026-09-01 のみ欠落 |
| plan | DAILY、1 request |
| apply | 4,441 行、4.7 s、1 attempt |
| recompute | window 07-24..09-01（26 session = 25 窓 + 1）、facts added 92 / skipped 2,243、contexts added 14 / skipped 265、2.13 s |
| daily 合計 | **6.84 s**（1 request） |
| rerun | plan **NOOP**、0 request、facts/contexts added 0 → **idempotent = true** |
| 整合 | canonical 142,187 行 = SQLite 142,187 行、facts 2,901、contexts 370 |

### 14.4 Master / weekly flow / event-driven

- master: refresh_due 今日 = false。diff 07-17（4,442）→ 09-02（4,440）: added 16（593A0…617A0）、removed 18
  （191A0, 21620, …）、market change 1（57040 0113→0112）、scale change 1（166A0 - → TOPIX Small 2）、
  S17/S33 変更 0。合計 **36**。
- weekly flow: plan CHECK from 2026-08-07 to 2026-09-02（stored latest period_end 08-21 / pub 08-27）。
  1 request、12 行、added 0（32 → 32、冪等）。
- fins: plan DATE_MODE（date=2026-09-01、1 request、codes_announced 0）。earnings: 09-02..12-01 1 request、
  stored 予定 0。

### 14.5 Health / readiness / failures

| dataset | health |
|---|---|
| daily_bars | CURRENT 31/31 |
| listed_master | CURRENT（8 snapshots、latest 09-02） |
| markets_calendar | CURRENT（211 日、2026-11-01 まで） |
| investor_types | CURRENT（period_end 08-21、32 section-weeks） |
| equities_earnings_cal | MISSING（予定 0 件） |
| topix | CURRENT 09-01（Nikkei 09-01 と aligned） |
| fins_summary | UNKNOWN（14 records、morning role NONE） |

readiness = **READY_WITH_WARNINGS**（equities_earnings_cal MISSING。required_ok / internals_ok = true）。
failures 分類 = {OK: 45}（retry 発生 0）。

### 14.6 Morning simulation（4 mornings、look-ahead 0）

| morning | previous | daily_bars ≤ prev | master effective | flow weeks | readiness replay | internals | leaks |
|---|---|---|---|---|---|---|---|
| 2026-08-28 | 08-27 | 29 | 08-21 | 8 | READY | 5 dims AVAILABLE | 0 |
| 2026-08-31 | 08-28 | 30 | 08-28 | 8 | READY | 5 dims AVAILABLE | 0 |
| 2026-09-01 | 08-31 | 31 | 08-28 | 8 | READY | 5 dims AVAILABLE | 0 |
| 2026-09-02 | 09-01 | 32 | 08-28 | 8 | READY | 5 dims AVAILABLE | 0 |

各朝の normal request = 4。contract: required = topix / markets_calendar / nikkei225、internals = daily_bars /
listed_master、optional = investor_types / equities_earnings_cal / usd_jpy / us_treasury_par / jgb10y。

### 14.7 Corporate action / 52 週 / performance

- corporate action: 3 session で 7 銘柄を price movement から除外（07-30: 21630, 31930, 83090 / 08-27: 99000 /
  08-28: 76490, 80110, 92790）。
- 52 週: stored 32 session。one-time seed に 218 request / 968,290 行 / 761 MB / 17.3 分 →
  **IMPLEMENT_LATER**（daily incremental で 218 営業日後に自然到達）。
- performance: seed 6.19 s/session、repair 2 request 10.13 s + recompute 2.5 s、daily 1 request 6.84 s、
  rerun 0 request、full rebuild 2.77 s、pilot 231.4 s。**morning_operation_realistic = true**。

### 14.8 Security

- env 確認: JQUANTS_API_KEY present のみ。ANTHROPIC / OPENAI は不在。値は一切出力していない。
- endpoints outside Light = 0、NOT_ENTITLED probe = 0、production root 変更 = false。
