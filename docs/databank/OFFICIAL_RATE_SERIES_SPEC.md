# OFFICIAL_RATE_SERIES_SPEC — 公式金利系列仕様（Phase 2-G）

原則: **NO PROXY SUBSTITUTION**——「同じ名前っぽいデータ」で埋めない。

## 1. UST2Y / UST10Y（official par yield）

**Source**: U.S. Department of the Treasury「Daily Treasury Par Yield Curve Rates」
（PRIMARY_OFFICIAL・Tier1）。暦年CSV
`daily-treasury-rates.csv/{year}/all?...&_format=csv`（probe run #6実測:
fair-access UAで200/text/csv。全履歴1ファイル変種は403のため年ファイルを
連結取得——連結の事実はparse_issuesへ申告しrawはpayloadそのまま保存）。

**Identity**（系列は `rates:UST2Y_par.yield.closing.us` / `rates:UST10Y_par...`）:

> Treasury official par yield ≠ 市場実勢利回りindex（^TNX型） ≠ 入札yield
> ≠ 2年note価格 ≠ 2Y ETF yield ≠ futures implied proxy

- par yield＝NY連銀が**約15:30 ET**に取得するindicative bid quotesから財務省が
  補間したconstant maturity par yield。`as_of = trading_date 15:30 ET`
  （exchange_close規約・DST対応）、`trading_date` はTreasury供給日付をそのまま
  使用（勝手なUTC暦日置換をしない）。
- 単位 **pct**（4.25%→値4.25）。CSVトークン→Decimal直接（float非経由）。
  空欄/N/Aは欠測のまま。
- 既存 `rates:UST10Y.yield.closing.us`（yfinance ^TNX＝CBOE 10-Year Treasury
  Note Yield Index・市場実勢系）は**削除・上書きせず併存**。official par 10Yは
  optional parallel seriesとして別instrument（`rates:UST10Y_par`）で追加。

**Spread**: `rates:UST10Y_par_UST2Y_par.spread.derived_metric` =
official par 10Y − official par 2Y（pct_point・両dateが揃う日のみ・補間なし・
入力observation_id＋calculation version付き）。**^TNX×official parの混合spreadは
概念不整合のため生成しない**（旧カタログ定義は実データゼロのまま本定義へ置換）。

## 2. JGB10Y（財務省 国債金利情報）

**Source**: 財務省「国債金利情報」CSV（PRIMARY_OFFICIAL・Tier1）。
probe run #6実測: `data/jgbcm_all.csv`（1974年〜**前月末**・1.17MB）＋
`jgbcm.csv`（**当月分**のみ）の2ファイル構成——providerは両方を取得し
連結申告付きでraw保存。Shift_JIS・和暦日付（S49.9.24 / R8.8.3）は
決定論変換（S=1925+n / H=1988+n / R=2018+n）。

**Identity**（`rates:JGB10Y.yield.closing.tokyo`——観測ゼロのままsource再定義）:

> JGB constant maturity 10Y ≠ 10年債入札平均利回り ≠ 特定銘柄利回り ≠ 表面利率

- 財務省の説明: 固定利付国債の**流通市場価格ベース**・constant maturity・
  **市場クローズ（15時）時点**。`as_of = trading_date 15:00 JST`。
  auction resultページを日次系列として使わない。
- 「10年」列をヘッダ名で照合（列位置仮定なし）。"-"は欠測のまま。単位pct。
- 旧Stooq経路（流通市場ベンチマーク・G9で不達・実績ゼロ）は概念が異なるため
  series定義から除外——既存データの再解釈は発生していない。

## 3. QA / trust

MARKET_OBSERVATION policy v1.0.0を適用——official payloadのprovider経路
provenance（FetchAttempt＋raw payload）が完備していればSUPPORTS Fact link不要。
Tier1は**source種別であってdata correctnessの絶対保証ではない**（既存原則維持）:
欠測・改定・サニティ検知はこれまで通りQA/ingestが機械記録する。
公表値の改定は revision_of チェーンで保存（上書きしない）。
