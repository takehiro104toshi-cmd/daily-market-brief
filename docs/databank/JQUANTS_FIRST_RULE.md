# JQUANTS_FIRST_RULE — J-Quants First（project-wide data rule / Phase 3.6）

## ルール

market / company data を必要とする Phase・機能は、**最初に J-Quants capability を確認する**。

1. `src/intelligence/jquants_ops/registry.py` の台帳（P2-H run #1/#3・Phase 3.5 run #20 の
   live evidence）で dataset を照合する。
2. `capability_gate.evaluate_capability(CapabilityRequest(...))` の結果を FINAL REPORT に載せる。

| gate 結果 | 意味 | 次の行動 |
|---|---|---|
| ALREADY_AVAILABLE | 現契約で取得可能かつ canonical に取り込み済み（または承認済み代替 source） | 既存 store を消費する。重複実装しない |
| CURRENT_PLAN_SUPPORTED | 現契約で取得可能（未取り込み） | 既存 ingest 経路（JQuantsV2Client + light store）へ dataset を追加 |
| NEEDS_NEW_ENDPOINT | registry に無い / 必要項目が実測項目に無い | 1 リクエストの entitlement probe（実応答で判定）→ registry へ追記 |
| PLAN_UPGRADE_CANDIDATE | Standard / Premium 契約が必要（403 実測済み） | `plan_upgrade_register.py` へ記載し監督者判断。**迂回しない・自動 upgrade しない** |
| CURRENT_PLAN_UNSUPPORTED | entitlement 未確定 / DEFERRED | DEFER または承認済み代替 source |
| DEFER | 必要履歴が実測深さを超える等 | daily incremental の蓄積後に再判定 |

## 分類語彙（registry）

- entitlement_status: `AVAILABLE_ON_CURRENT_PLAN` / `NOT_ENTITLED` / `ENTITLEMENT_UNKNOWN`
- strategy_status: `ALREADY_INGESTED` / `NEW_ENDPOINT_AVAILABLE` / `PLAN_UPGRADE_CANDIDATE` /
  `ALTERNATIVE_APPROVED_SOURCE` / `DEFERRED` / `NOT_REQUIRED`
- frequency_class: `DAILY` / `WEEKLY` / `EVENT_DRIVEN` / `REFERENCE` / `ON_DEMAND`
- morning_role: `REQUIRED` / `INTERNALS` / `OPTIONAL` / `NONE`

## 禁止

- Standard / Premium endpoint の迂回（別 endpoint・別 provider による代用）
- 既知の 403 endpoint の再 probe（registry の `last_live_verified_at` を参照する）
- 現契約で取得できるデータを別 source で重複実装すること
- plan upgrade の自動実施

## 既存 Phase の監査結果（`capability_gate.standing_audit()`）

| request | 結果 | dataset |
|---|---|---|
| japan_market_breadth | ALREADY_AVAILABLE | daily_bars |
| topix_close | ALREADY_AVAILABLE | topix |
| nikkei225_close | ALREADY_AVAILABLE（承認済み代替）| nikkei225（legacy yfinance / Market Data Bank） |
| sector_short_ratio | PLAN_UPGRADE_CANDIDATE | markets_short_ratio（Standard） |
| fifty_two_week_high_low | DEFER | daily_bars（250 session の蓄積待ち） |
| weekly_investor_flow | ALREADY_AVAILABLE | investor_types |
| usd_jpy_close | ALREADY_AVAILABLE（承認済み代替）| usd_jpy |
| intraday_am_close | PLAN_UPGRADE_CANDIDATE | equities_bars_am（Premium） |
