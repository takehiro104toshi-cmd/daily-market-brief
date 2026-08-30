# CRITICAL_MARKET_SOURCE_GAP_CLOSURE — Phase 2-G報告（2026-08-30）

対象は監督者指定の3系列のみ: **TOPIX / JGB10Y / UST2Y**。
最上位原則: **NO PROXY SUBSTITUTION**（TOPIX→ETF・JGB10Y→別年限/入札・
UST2Y→別概念yield/ETF/futures impliedの代用禁止——全て遵守）。

## 1. 調査（probe run #6・実ネットワーク実測）

- Treasury年別CSV: 200/text/csv（fair-access UAで可・全履歴変種は403）
- 財務省jgbcm: `jgbcm_all.csv`（1974〜前月末・1.17MB）＋`jgbcm.csv`（当月分）の
  2ファイル構成を実測確認
- JPX公式サイト: 到達可だが自動取得向け公開機械可読データ確認できず
- J-Quants API: 到達実証（credential無しは403 JSON）

## 2. 接続結果（live run #7・conclusion=success）

| series | source | 経路 | live結果 |
|---|---|---|---|
| `rates:UST2Y_par.yield.closing.us`【新設】 | **U.S. Treasury** Daily Treasury Par Yield Curve「2 Yr」 | TreasuryParYieldProvider（年別CSV連結・申告付き） | **success 274行** 2025-07-28〜2026-08-28・latest **4.34 pct**・as_of 15:30 ET |
| `rates:UST10Y_par.yield.closing.us`【新設・optional parallel】 | 同「10 Yr」 | 同 | **success 274行**・latest **4.73 pct**（^TNX系列は無変更で併存） |
| `rates:JGB10Y.yield.closing.tokyo` | **財務省 国債金利情報**「10年」 | MofJgbYieldProvider（全履歴＋当月・cp932・和暦→ISO） | **success 265行** 2025-07-28〜2026-08-27・latest **2.897 pct**・as_of 15:00 JST |
| `index:topix.close.closing.tokyo` | **J-Quants**（JPX公式系API）/indices/topix | JQuantsTopixProvider（env credentialのみ） | **gap: no_credentials**（正直な欠測。捏造・代用なし） |

run #7全体: requested 16 = success 15 + gap 1 + failed 0 / raw 4,245・derived
16,444 / 別プロセスpersistence 20,689観測・index再構築一致・latest 15/15 /
backup manifest verify 0/0/0。

## 3. 派生系列

- **UST10Y-UST2Y spread**: `rates:UST10Y_par_UST2Y_par.spread.derived_metric`
  **274行**生成（latest 2026-08-28 = **0.390000 pct_point** = 4.73−4.34 ✓）。
  入力observation_id＋`yield_spread:1.0.0` のcalculation provenance付き。
  **概念整合**: official par同士のみ。^TNX（市場実勢index）×official parの
  混合spreadは生成しない（旧カタログ定義は実データゼロのまま置換）。
- **NT倍率**: 定義済み（inputs=日経225×TOPIX。両方とも現物指数15:30終値で
  概念整合）。TOPIXデータ未取得のため**0行**——入力が無い派生は出力しない。

## 4. QA / 会計

- 初回取込はHISTORICAL v1.0.0でaccept_with_warnings（missing_supporting_
  evidence_ref）→ **MARKET_OBSERVATION v1.0.0再評価で raw 4,245全件ACCEPT・
  該当warning 0**（provider経路provenance実証・旧評価保持）。
- 公式系列のissue 0・missing_value_rows 0。JGB10Yのlast=8/27は財務省の
  公表ラグ（当日分は翌営業日掲載）——欠測は欠測のまま。
- raw保存: Treasury=年別CSVそのまま（2年分は連結を申告）、MOF=2ファイル連結を
  申告、いずれもsha256付きblob。**fake raw無し**。既知の限界: 連結bodyの
  FetchAttempt locatorは最終リクエストURL（連結の内訳はparse_issuesに申告）。

## 5. GAP状態（証拠付き・「コードを書いた」ではRESOLVEDにしない）

| gap | 状態 | 証拠 |
|---|---|---|
| **G11 UST2Y** | **RESOLVED** | run #7 live success・274行（25DMA可能・約13ヶ月）・identity/unit/as_of/QA/persistence/query PASS |
| **G11 JGB10Y** | **RESOLVED** | run #7 live success・265行・同上 |
| **G10 TOPIX** | **PARTIALLY_RESOLVED** | 供給元決定（J-Quants公式系）・adapter/カタログ/テスト完成・API到達実証。**live取得はユーザーのJ-Quants登録＋secrets投入待ち**（投入後は同pilotが自動実証→probe:false化でRESOLVED） |

カタログ1.1.0: live実証済み3系列（JGB10Y/UST2Y_par/UST10Y_par）はprobe:false化。
TOPIXはprobe:true維持。healthの`phase3_readiness`はカタログ＋ローカル実データから
状態を機械導出（TOPIX未解決の間BLOCKED）。

## 6. Phase 3 readiness gate判定

- UST2Y: live＋historical **PASS** / JGB10Y: live＋historical **PASS** /
  TOPIX: **PENDING**（credential）
- → 総合 **PHASE2G_PARTIAL**（3系列全解決ではないため正直にPARTIALで停止。
  TOPIX live成功後にPHASE2G_CRITICAL_MARKET_GAPS_CLOSEDへ昇格可能）
