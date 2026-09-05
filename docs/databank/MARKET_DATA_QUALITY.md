# MARKET_DATA_QUALITY — CORE系列データ品質報告（Phase 2-D / live実測 2026-08-30）

導出: `src/intelligence/market/quality_report.py`（canonicalのみから導出。
検知・報告のみ——欠測の補完・値の補正は構造的に不在）。

## 1. カバレッジ（データあり12系列）

| series | 観測数 | first | last | 期待セッション | missing |
|---|---|---|---|---|---|
| 日経平均 | 266 | 2025-07-28 | 2026-08-28 | 285 | 19 |
| NYダウ | 275 | 2025-07-28 | 2026-08-28 | 285 | 10 |
| S&P500 | 275 | 2025-07-28 | 2026-08-28 | 285 | 10 |
| ナスダック総合 | 275 | 2025-07-28 | 2026-08-28 | 285 | 10 |
| SOX | 275 | 2025-07-28 | 2026-08-28 | 285 | 10 |
| VIX | 276 | 2025-07-28 | 2026-08-28 | 285 | 9 |
| USDJPY | 283 | 2025-07-28 | 2026-08-28 | 285 | 2 |
| EURUSD | 283 | 2025-07-28 | 2026-08-28 | 285 | 2 |
| UST10Y | 275 | 2025-07-28 | 2026-08-28 | 285 | 10 |
| WTI先物継続 | 275 | 2025-07-28 | 2026-08-28 | 285 | 10 |
| 金先物継続 | 275 | 2025-07-28 | 2026-08-28 | 285 | 10 |
| BTCUSD | 399 | 2025-07-26 | 2026-08-28 | 399 | **0** |

- 「期待セッション」はweekdays暦（祝日辞書なし）——**missingには取引所祝日が
  含まれる**（日経19≒日本の祝日数・米系10≒米祝日数・FX 2＝元日等のみ、と
  実際の市場カレンダーに整合。祝日での補完・穴埋めはしない）。
- BTC（calendar: all_days）はmissing 0——24/7市場の週末日付が「欠測扱いに
  ならない」ことのカレンダーモデル実証。
- missing_value_rows（行はあるが値なし）全系列0・revision 0（初回取込のため）。

## 2. QA判定（Evidence QA・HISTORICAL:1.0.0）

- raw 3,432件 全て **accept_with_warnings**。REJECT 0・LIMITED 0。
- warning内訳: `missing_supporting_evidence_ref`（API直取得＝由来文書なしの
  provenance申告——構造的warning）。tier2 provider由来のtier警告なし
  （tier3のみ警告対象）。範囲異常（負値・absurd値・unit/currency不整合・
  未来as_of）**検出0**。
- 派生13,080件もQA済み（依存伝播: 入力assessmentのGate結果を透過）。

## 3. データなし3系列（Phase 2-D時点のHISTORICAL RECORD）

> **現況（2026-09-01）: 本節の3系列はすべて解決済み**。
> TOPIX=J-Quants V2（G10 RESOLVED・run #15）、JGB10Y=財務省国債金利情報、
> UST2Y=Treasury official par yield（`rates:UST2Y_par`）で取得できている
> （G11 RESOLVED・run #7/#15）。cross派生（official spread・NT倍率）も出力済み。
> 以下はP2-D当時の記録であり、当時の判断根拠として保全する。


| series | 理由 | トラック |
|---|---|---|
| TOPIX | Stooq history不達（G9）。yfinanceの1306.TはETFであり指数へ流用禁止 | G10 |
| JGB10Y | Stooq 10jpy.bのみ定義（probe）・不達 | G11 |
| UST2Y | Stooq 2usy.bのみ定義（probe）・不達 | G11 |

結果としてcross派生（UST10Y-UST2Yスプレッド・NT倍率）は**未出力**
（片側入力だけからの算出・補完はしない。入力が揃えば同一コードで自動算出——
オフラインテストでは両derivationの数値正しさを固定済み）。

## 4. float transit（yfinance固有の正直な申告）

yfinanceはfloatで値を供給する（例: DJI "53559.98828125"）。トークンは
repr(float)のままDecimal化し、**丸め・整形をしない**（見かけの桁は
providerのfloat事実の忠実な保存。全fetchに`provider_float_transit`記録）。
表示用の丸めは将来の表示層の責務（Data Bankは供給値を保存する）。

## 5. cross-source比較

単一provider成功（stooq不達）のため今回未実施（`not_exercised_single_provider`
として機械記録）。Stooq到達可能環境（ローカルIP）で同一series×同日の
provider間diff比較が有効化される——**自動上書きは常に禁止**（検知・報告のみ）。
