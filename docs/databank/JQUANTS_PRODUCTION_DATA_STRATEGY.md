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
  上限 200）。`date` 指定の可否は run #21 で実測。実績／当期予想／翌期予想の分離維持。
- equities_earnings_cal: 今日〜+90日を毎朝 1 request。known_at = 取得時刻（公表済み予定のみ）。
  日程変更は新 record（旧 record は残す。消費側は code ごとに最新 retrieved_at）。
- topix: 既存 V2 provider 不変。毎朝 1 request（差分）。Nikkei との same-session alignment を確認。

## 11. Storage / request budget（`storage_budget.py` / `request_budget.py`）

（§14 に live 実測を記載）

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

（live evidence をここに記録する）
