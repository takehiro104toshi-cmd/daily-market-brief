# MARKET_SOURCE_MAPPING — 供給元と系列の対応（Phase 2-D PART C）

## 1. provider種別の区分（格の混同禁止）

| 種別 | 意味 | P2-D時点 |
|---|---|---|
| PRIMARY_OFFICIAL | 取引所・中央銀行・統計局の公式公表値 | 未接続（SOURCE GAPトラック: JPX公表値・FRB H.15・財務省金利等） |
| **MARKET_DATA_PROVIDER** | 市場データ集約プロバイダ | **yfinance**（一次・legacy本番実績経路）＋**Stooq**（フォールバック） |
| SECONDARY | 報道等の二次値 | 使用しない（News Bank側の領域） |

いずれも「市場の実勢を反映するprovider供給値」であり、取引所公式の確定値ではない。
QAのSourceInfoは tier2 / health unverified（死活registry未整備の正直な申告）で
評価される。

## 2. LEGACY REUSE（既存資産の再利用と改変ゼロ）

| legacy資産 | 再利用形態 |
|---|---|
| `src/collectors/market_data.py` の**yfinance一次・Stooqフォールバック構成** | vNext provider chain（preferred: yfinance / fallback: stooq）として忠実に再現（本番Actionsで毎日実績のあるアーキテクチャ） |
| `config.yaml` indices/forex/rates/commoditiesの**Yahooティッカー**（^N225/^DJI/^GSPC/^IXIC/^VIX/^SOX/JPY=X/EURUSD=X/^TNX/CL=F/GC=F/BTC-USD） | yfinance providerのsymbolとして採用（**全て実績あり**） |
| `config.yaml` stooq_symbols（^nkx/^tpx/^dji/^spx/^ndq/^vix/usdjpy/eurusd/10usy.b/cl.f/gc.f） | Stooq providerのsymbolとして採用 |
| `src/utils.py` DEFAULT_HEADERS のUser-Agent | Stooqアダプタのrequestヘッダで同一値を使用（テストで同一性固定） |
| P1-C `ingestion/transport.py`（urllib・timeout・redact・retry思想） | Stooqアダプタがそのまま使用 |

legacyコードの変更は一切ない（adapter側で参照・複製のみ）。

## 2b. live pilotで実測したprovider制約（設計変更の根拠）

- 初回run: vNext既定UAに対しStooqがHTTP 200で非CSVを返却（全系列parse_error）。
- 2回目run（legacy実績UA使用＋body先頭snippet診断）: 応答は**HTML制限ページ**
  （`<!DOCTYPE html>…robots no…`）と確定——Stooqの日足historyエンドポイント
  （`q/d/l/`）はIP単位のダウンロード制限を持ち、**共有IP（GitHub Actionsランナー）
  からは実質利用不能**。quote endpoint（legacyが使用）はこの制限の対象外。
- 対応: legacyが本番で毎日使っている**yfinance一次**へ揃え、Stooqはフォールバック
  として保持（ローカル実行・自宅IPでは有効な経路）。診断の道具（snippet・
  error_detail）はコードに残し、将来の供給元障害の切り分けに使う。

## 3. symbol対応表（カタログ v1.0.0）

| series_id | preferred | yfinance | stooq(fallback) |
|---|---|---|---|
| index:nikkei225.close.closing.tokyo | yfinance | ^N225 | ^nkx |
| index:topix.close.closing.tokyo | stooq | —（1306.T ETFは**流用しない**） | ^tpx（probe） |
| index:dji.close.closing.us | yfinance | ^DJI | ^dji |
| index:spx.close.closing.us | yfinance | ^GSPC | ^spx |
| index:nasdaq_composite.close.closing.us | yfinance | ^IXIC | ^ndq |
| index:sox.close.closing.us | yfinance | ^SOX | ^sox |
| index:vix.close.closing.us | yfinance | ^VIX | ^vix |
| fx:USDJPY.rate.closing.global | yfinance | JPY=X | usdjpy |
| fx:EURUSD.rate.closing.global | yfinance | EURUSD=X | eurusd |
| rates:JGB10Y.yield.closing.tokyo | stooq | — | 10jpy.b（probe） |
| rates:UST2Y.yield.closing.us | stooq | — | 2usy.b（probe） |
| rates:UST10Y.yield.closing.us | yfinance | ^TNX | 10usy.b |
| futures:wti_cont.close.closing.us | yfinance | CL=F | cl.f |
| futures:gold_cont.close.closing.us | yfinance | GC=F | gc.f |
| crypto:BTCUSD.close.closing.global | yfinance | BTC-USD | btcusd |
| index:growth250.close.closing.tokyo | —（GAP） | — | — |

probe/GAPの取得失敗はSOURCE GAPとして記録され、エラー（failed）と区別される。
TOPIXへの1306.T流用禁止＝「ETF≠指数」のidentity安全（本カタログの中核原則）。

## 4. fallback規約（SILENT SWITCH禁止）

- provider chainはカタログ宣言（preferred_source→fallback_sources順）。
- 発動時の記録（全て機械記録・テスト固定）:
  1. 失敗した試行を含む**全FetchAttempt**が永続化される
  2. run manifestの `fallback_used` / `fallback_errors`（"provider:error_kind"）
  3. **Observation.source_id**（per-Observation provenance——実際に供給したprovider）
  4. 既存と別providerの値を取り込む場合: 同値→`source_change_confirmed_equal`記録・
     異値→revision＋`source_changes`（"日付:旧→新"）
- 同一seriesへの複数provider値の**黙った混在は構造的に不可能**
  （異なるsource_idはobservation_idも異なり、改定リンクか確認記録が必ず残る）。
- 品質レポートは系列内の複数provider混在を`fallback_used`として表面化する。

## 5. yfinanceの正直な扱い（生HTTPを捏造しない）

- `provider_normalized=true` … yfinanceライブラリの前処理済み応答であり生HTTPでは
  ない。blobは本adapterが決定論整形したCSVスナップショットとして保存し、
  生CSVと**区別**する。
- **float供給の事実**を全fetchに `provider_float_transit` として申告。値トークンは
  repr(float)（最短round-trip表現）→Decimal（それ以上の加工・丸めをしない）。
- adjustment=unadjustedに合わせ `auto_adjust=False` のClose列を使用
  （調整済み値の暗黙選択をしない）。
- Stooqが使える環境（ローカル・自宅IP）ではcross-source比較（PART H）の
  比較対象として機能する（自動上書きは禁止のまま）。
