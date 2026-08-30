# MARKET_SERIES_CATALOG_SPEC — MarketSeries正式カタログ仕様（Phase 2-D PART B）

原則: **A NUMBER WITHOUT IDENTITY AND CONTEXT IS NOT MARKET DATA**

## 1. カタログの所在と形式

- 正: `knowledge/market_series/core_series.yaml`（versioned config・v1.0.0）。
  巨大なPython hardcode一覧は作らない（P2-A決定の実装）。
- loader/validator: `src/intelligence/market/series_catalog.py`（読み取り専用・
  検証失敗はValueErrorで黙って通さない）。
- 系列identity本体は P2-A の `databank/market_model.MarketSeries` を**そのまま**使用。
  series_idは `make_series_id(instrument_id, metric, observation_type, session)` から
  決定論導出され、load時に照合される（規約外IDはカタログエラー）。

## 2. 系列フィールド

identity（MarketSeries）: series_id / instrument_id / metric / observation_type
（closing / intraday_quote / official_fixing / economic_statistic / derived_metric）/
market_session / unit / currency。

運用（SeriesSpec）: display_name / asset_class / timezone / close_time_local /
**as_of_policy** / calendar（weekdays・all_days） / provider_symbols /
preferred_source / fallback_sources / frequency / adjustment / enabled / probe /
role（CORE・EXTENDED） / identity_notes。

## 3. SERIES IDENTITY安全（雑な同一視の禁止を構造で強制）

| 危険な同一視 | 本カタログでの扱い |
|---|---|
| 指数 vs ETF vs 先物 | instrument_idの名前空間分離（`index:spx` ≠ SPY ≠ ES。先物継続は`futures:wti_cont`と明示） |
| USDJPY spot終値 vs 仲値fixing vs 東京/NYクローズ | observation_type×sessionで別series_id。現行は`fx:USDJPY.rate.closing.global`（provider日足close）のみ定義。fixing等は**新series追加**でしか表現できない |
| Nasdaq総合 vs Nasdaq100 | 別instrument（`index:nasdaq_composite` / `index:nasdaq100`）。テストで非混同を固定 |
| 米金利: 流通市場利回り vs 財務省CMT vs 入札結果 | identity_notesで「流通市場ベンチマーク（provider供給値）」と明記。CMT/入札は将来別series |
| 調整後 vs 未調整終値 | adjustmentフィールド（既定unadjusted）。指数・FX・金利は調整概念なし。個別株導入時に効く |

## 4. RATES規約（unitの固定）

利回り系列（metric=yield）は **unit=pct固定**（4.25% → 値`4.25`）。ratio表現
（0.0425）の混入は`SeriesSpec.__post_init__`が拒否する。bps換算は派生側の責務。

## 5. as_of_policy（セッションモデルの規約）

- `exchange_close`: as_of = trading_date + close_time_local（取引所tz）→UTC変換。
  日経/TOPIX 15:30 JST・米指数 16:00 ET・VIX 16:15 ET。
- `day_end_utc`: 単一クローズが定義できない系列（FX spot連続・先物継続・
  流通市場金利・暗号資産）の固定規約: as_of = trading_date 23:59:59Z。
  「当日中のどこか」を明示する規約であり、**個別値ごとの時刻捏造をしない**。

## 6. provider種別（PART C: 供給元の格の混同禁止）

`providers:` セクションで PRIMARY_OFFICIAL / **MARKET_DATA_PROVIDER** / SECONDARY を
区別。Stooqは MARKET_DATA_PROVIDER（tier2）——取引所・中央銀行の公式公表値ではない。
PRIMARY_OFFICIAL経路（JPX・FRB H.15等）の確保はSOURCE GAPトラック。

## 7. enabled / probe / GAPの意味論

- `enabled: false` … identityのみ定義（収集しない）。Growth250（provider symbol
  未確認）・任意系列（Nasdaq100・UST30Y・Brent）。
- `probe: true` … legacy実績のないsymbol（SOX・UST2Y・JGB10Y・BTC）。取得失敗は
  **SOURCE GAP（gap）** として記録され、エラー（failed）とは区別される。
- symbol未確認の系列をenabledにすることはloaderが拒否する（捏造単一防衛線）。

## 8. 派生系列（PART F・foundation only）

- `derivations.per_series`: return_1d / return_5d / ma25 / dist_25dma
  （series_idはbaseから決定論導出: `index:nikkei225.return_1d.derived_metric.tokyo`）。
- `derivations.cross_series`: `rates:UST10Y_UST2Y.spread.derived_metric`（pct_point）・
  `index:nikkei225_topix.nt_ratio.derived_metric`（x）。inputsの実在をloaderが検証。

## 9. market internals

`internals_placeholder`: 騰落銘柄数等はidentityの予約のみ（供給元未確保のため
収集しない——PRIMARY_OFFICIAL経路確保後に正式定義）。

## 10. 変更管理

カタログ変更は `version` を上げる（run manifestに使用versionが記録され、
どのrunがどの定義で取得したか監査可能）。既存series_idの意味変更は禁止
（意味が変わるなら新series_id）。
