# JQUANTS_LIGHT_CAPABILITY_MATRIX — J-Quants Light plan 能力一覧（Phase 2-H / 2026-09-01）

**すべて実測**（live probe run #1 / live pilot run #3・2026-09-01）。公式ドキュメント
からの類推でAVAILABLE扱いしたものは無い。今後Standard/Premiumへ上げる必要性を
判断するための基礎資料。

## 1. entitlement 実測結果

`api_version = v2` / 認証はAPI Keyヘッダ（`JQUANTS_API_KEY` のruntime injection）。

| dataset | endpoint | Light | 分類 | 頻度 | 実装状況 | 投資インテリジェンス上の用途 |
|---|---|---|---|---|---|---|
| listed_master | `/equities/master` | **AVAILABLE** | REQUIRED | snapshot | INGESTED（light store） | security master。Company Intelligence / Screener / Market Internals の母集団定義 |
| daily_bars | `/equities/bars/daily` | **AVAILABLE** | REQUIRED | daily | INGESTED（light store） | 個別銘柄の日次価格。Morning Compass / Internals / Screener の一次入力 |
| fins_summary | `/fins/summary` | **AVAILABLE** | REQUIRED | event | INGESTED（light store） | 財務サマリー（実績＋会社予想）。Company Intelligence / Screener |
| equities_earnings_cal | `/equities/earnings-calendar` | **AVAILABLE** | REQUIRED | event | INGESTED（light store） | 決算発表予定。「決算まで何日」の基盤 |
| markets_calendar | `/markets/calendar` | **AVAILABLE** | REQUIRED | snapshot | INGESTED（light store） | 東京取引カレンダー。latest completed session 判定 |
| topix | `/indices/bars/daily/topix` | **AVAILABLE** | REQUIRED | daily | INGESTED（**Market Data Bank**） | TOPIX指数（G10 RESOLVED）。NT倍率・東京ベンチマーク |
| investor_types | `/equities/investor-types` | **AVAILABLE** | USEFUL | **weekly** | INGESTED（light store） | 投資部門別売買動向。Internals の需給観測 |
| fins_earnings_date | `/fins/earnings-date` | **UNKNOWN** | DEFER | event | 未実装 | HTTP 400（パラメータ契約違い）。entitlement未確定のためAVAILABLE扱いしない |
| indices_bars_daily | `/indices/bars/daily` | **NOT_ENTITLED** | DEFER | daily | 未実装 | TOPIX以外の指数四本値 |
| fins_dividend | `/fins/dividend` | **NOT_ENTITLED** | DEFER | event | 未実装 | 配当 |
| fins_details | `/fins/details` | **NOT_ENTITLED** | DEFER | event | 未実装 | 詳細財務 |
| markets_short_ratio | `/markets/short-ratio` | **NOT_ENTITLED** | DEFER | daily | 未実装 | 業種別空売り比率 |
| equities_bars_am | `/equities/bars/daily/am` | **NOT_ENTITLED** | DEFER | daily | 未実装 | 前場四本値 |
| markets_breakdown | `/markets/breakdown` | **NOT_ENTITLED** | DEFER | daily | 未実装 | 売買内訳 |

NOT_ENTITLEDはすべて `HTTP 403 "This API is not available on your subscription."`
で確認。**別endpointによる迂回実装はしない**（プラン制約をコードで回避しない）。

## 2. 履歴・鮮度（実測）

| dataset | 実測レンジ | 件数 | 備考 |
|---|---|---|---|
| listed_master | Date=2026-09-01 | 4,441銘柄 | 当日スナップショット・pagination無し |
| daily_bars | 2025-09-01〜2026-09-01 | 244セッション/銘柄 | 1年で244営業日 |
| fins_summary | code指定 | 22〜31件/銘柄 | 過去開示が複数世代 |
| markets_calendar | 2025-07-28〜2026-09-01（401暦日） | 401 | HolDiv: `1`=268 / `0`=118 / `3`=15 |
| investor_types | 直近120日 | 68件・64期間 | **週次** |
| topix | — | — | G10 RESOLVED（P2-G.2） |

## 3. 取引カレンダーの区分値（**推測せず実測検証**）

`HolDiv` の意味はsourceのコード値であり、こちらで断定しない。
TOPIXの観測日（＝確実に営業日）と突き合わせて検証した:

- 検証: **21日照合 / 21一致 / 不一致0 → validated = true**
- 採用する営業日区分: **`1` のみ**。`0` `3` は営業日扱いしない（未検証の値を
  営業日と見なさない＝FAIL-CLOSED）。
- `latest_completed_session` = 2026-09-01 で、TOPIX最新日と一致。

## 4. Standard / Premium 昇格の判断材料

現在Lightで**できないこと**（用途が発生したら昇格を検討）:

| 欲しくなる場面 | 必要dataset | 必要プラン |
|---|---|---|
| TOPIX以外の指数（グロース250等）を系列として持つ | indices_bars_daily | Standard |
| 配当・詳細財務でScreenerを深くする | fins_dividend / fins_details | Standard |
| 空売り比率・売買内訳で需給を見る | markets_short_ratio / markets_breakdown | Standard / Premium |
| 前場終値で「当日朝」の速報性を上げる | equities_bars_am | Premium |

**現時点でPhase 3（Compass）に必要なcore dataはLightで充足している**
（TOPIX・日次価格・security master・カレンダー）。昇格は用途が確定してから。
