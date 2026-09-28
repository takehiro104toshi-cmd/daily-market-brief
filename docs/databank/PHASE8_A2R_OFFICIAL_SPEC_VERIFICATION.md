# PHASE 8 / P8-A2R（再実行）— J-QUANTS `/v2/fins/summary` OFFICIAL SPEC VERIFICATION

P8-A2R（`739ece2`、P8_A2R_OFFICIAL_SPEC_BLOCKER）の再実行。監督が Cloud Environment の Network Access を CUSTOM にし、公式の host
（`jpx-jquants.com` ・`jpx.gitbook.io` ・`www.jpx.co.jp`）を許可した後の session で、PILOT1 の観測の意味を**公式の文書で**確かめ、
P8-A2 の意味の remediation の要否を最終判断できる状態にする。**実装 ・A3 ・adapter ・J-Quants の data API への要求は無い。**

- 基準: P8-A2R `739ece233d7f99ec28da96254f408d3613229f6b`（前回の BLOCKER。report は削除 ・変更しない）、P8-PILOT1 `cbf86cc`、
  P8-A2 `b686b00`、P8-A1 `4162e9c`。full pytest の基準 5348 passed ／ 2 skipped。
- 本書は credential ・header ・raw の応答 ・財務の実の値を載せない。J-Quants の data API（`api.jquants.com`）への要求は **0 回**。
- 分類: **DOCUMENTED**（公式の本文に書かれている）／ **OBSERVED_IN_PILOT**（PILOT1 の実の応答だけ）／ **INFERRED**（公式 ・観測からの
  推論）／ **UNKNOWN**。公式の本文どうしが食い違う所は **DOC_CONFLICT** と明記する。

---

## 0. 結論

1. **公式の文書に到達できた。** `jpx-jquants.com`（J-Quants API の現行の V2 の公式 reference）と `www.jpx.co.jp` は HTTP 200。
   `jpx.gitbook.io` は `app.gitbook.com` へ redirect され、その host が proxy で 403（許可の外）。迂回はしていない。gitbook は V1 の
   旧文書で、V2 の field は `jpx-jquants.com` の現行の文書が authority なので、本 gate の判断に影響しない（§2）。
2. **`/v2/fins/summary` の公式の field の一覧は 111 欄で、PILOT1 の観測した 111 欄と完全に一致**（名前の綴りも一致。§5.1）。
   `OP` ＝ 営業利益、`OperatingProfit` は V2 の field に無い（P8-OBS-48 CLOSED）。
3. **DocType は公式の閉じた列挙（45 値）**。会計基準の token は `JP`（日本基準）・`US`（米国基準）・`IFRS` ・`JMIS`、加えて
   `Foreign`（外国株。会計基準ではない）・`REIT`。予想の修正は `EarnForecastRevision` ・`DividendForecastRevision` ・
   `REITEarnForecastRevision` ・`REITDividendForecastRevision` で、**連結の区分 ・会計基準の token を持たない**（§4）。
4. **DiscDate ／ DiscTime は「TDnet の開示日 ／ 開示時刻（JST）」と公式に定義**。A2 の `TIMESTAMP` ／ `DATE` の写しは公式に正当化
   できる（固定の時刻は作らない）。ただし Light の API への反映は日次（18:00 頃 速報 ／ 24:30 頃 確報）で、開示時刻とは別（§6）。
5. **単位**: 金額は XBRL の値に基づき**円単位（換算 ・丸めなし）**（DOCUMENTED）。scale は ONE。**ただし `/fins/details` の公式の
   文書は、ある発行体（銘柄コード 62690）が 2022 年 2 月以降 米ドルで表示され、その data も米ドルと記す**。`/fins/summary` には通貨の
   欄が無く、この発行体の summary の通貨は UNKNOWN（DOC_CONFLICT。§10）。`DivUnit` は単位の欄ではなく **REIT の 1 口当たり分配金**。
6. **期間**: `Sales` ・`OP` ・`OdP` ・`NP` は**期首からの累計**（JGAAP ・IFRS ・米国基準で共通）と公式の FAQ に明記。`CurPerType` の
   値の集合は `1Q 2Q 3Q 4Q 5Q FY`（DOCUMENTED）。
7. **空文字 `""` は「開示書類に記載が無い」ことだけを示す**（前回からの変更の有無 ・予想の撤回 ・未定を表さない）。IFRS ・米国基準の
   `OdP` は概念が無いため空（DOCUMENTED）。
8. **G1（会計基準の次元が A2 の slot の identity に無い）は実の欠陥**と判断する。予想の slot は、会計基準の変更をまたいで違う基準の
   値が同じ鎖に入り得て、修正の行は基準の token を持たない（§7）。ただし **凍結した A2 の 3 module を変える必要は無い**。追加だけの
   remediation（Option E ＝ Option D ＋ 取り込みの入口の基準の一致の guard）で fail closed にできる（§8）。
9. **P8-OBS-50: REQUIRES_A2_REMEDIATION**（provider の側は公式の仕様で解けた。残りは A2 の側の表現。§11）。
10. A3 の最初の候補（売上成長率 ・営業利益率）は **意味の上では READY_WITH_RESTRICTIONS** だが、**A2 の追加の remediation の実装の
    前は開始できない**（D-P8-A2R-6）。実データは実の identity の登録の前は BLOCKED_BY_IDENTITY（§12）。
11. 判定: **P8_A2_REMEDIATION_REQUIRED**（§18）。runtime は 1 byte も変えていない。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| HEAD（開始時） | `739ece233d7f99ec28da96254f408d3613229f6b`（期待どおり） |
| working tree（開始時） | clean |
| 実行日 | 2026-09-28（公式の page の取得は 14:40〜14:50 UTC 頃） |
| J-Quants data API への要求 | 0 回（PILOT1 の観測は完了済み。本 gate は文書だけ） |

---

## 2. 公式の文書への到達（FIRST ACTION）

| host | 結果 | 備考 |
|---|---|---|
| `jpx-jquants.com` | **200**（`/` → `/ja`） | V2 の API reference ・FAQ ・release。各 page の `.md` 版（`text/markdown`。公式の同じ page の Markdown 表示）も 200 |
| `www.jpx.co.jp` | **200** | 到達を確かめた。J-Quants の公式の文書で足りたので、本 gate の意味の authority には使っていない |
| `jpx.gitbook.io` | `/j-quants-en` が `app.gitbook.com/...` へ redirect され、proxy が CONNECT に **403** | `app.gitbook.com` は許可の外。**迂回していない**。V1 の旧文書で、V2 の定義は `jpx-jquants.com` が現行の公式 |

非公式の出所（blog ・Qiita ・Q&A ・GitHub ・SNS ・検索の要約）は一切使っていない。

---

## 3. 読んだ公式の出所

取得日はすべて 2026-09-28。URL の `.md` は同じ page の公式の Markdown 表示（page の「Markdownを表示」の link）。

| id | page | URL | 使った節 |
|---|---|---|---|
| O1 | 財務情報（/fins/summary）日本語 | https://jpx-jquants.com/ja/spec/fin-summary （＋ `.md`） | 本APIの留意点 ・データ更新・訂正のポリシー ・パラメータ ・データ項目概要 ・レスポンスサンプル |
| O2 | Financial Data (Summary only) 英語 | https://jpx-jquants.com/en/spec/fin-summary.md | Attention ・Data update and correction policy ・Data Item（field 表） |
| O3 | 開示書類種別（TypeOfDocument）日本語 | https://jpx-jquants.com/ja/spec/fin-summary/typeofdocument （＋ `.md`） | 書類種別一覧 |
| O4 | Type of Document 英語 | https://jpx-jquants.com/en/spec/fin-summary/typeofdocument.md | Document Type 表 |
| O5 | 提供データの更新タイミング | https://jpx-jquants.com/ja/spec/data-update | 財務情報の行 ・データ更新の完了確認・訂正の反映について |
| O6 | V1 API から V2 API への変更点 | https://jpx-jquants.com/ja/spec/migration-v1-v2 | エンドポイントの対応表 ・カラム名の変更例 |
| O7 | FAQ データ内容・仕様 | https://jpx-jquants.com/ja/help/data | 累計値か ・発行済み株式総数 ・時価総額 ・Point-in-Time ・訂正 ・財務情報は開示後すぐ取得できるか ・コーポレートアクション |
| O8 | データ修正履歴・制約事項 | https://jpx-jquants.com/ja/spec/fix-data-info.md | データ修正履歴（財務情報の行）・制約事項 |
| O9 | リリース | https://jpx-jquants.com/ja/spec/release.md | 2026.09.14 財務情報APIに自己資本・自己資本利益率を追加 ・2026.06.08 随時更新（Premium）・2024.07.22 |
| O10 | 財務諸表（BS/PL/CF）（/fins/details） | https://jpx-jquants.com/ja/spec/fin-details | 表示通貨について（参照だけ。/fins/details の意味は本 gate の対象外） |
| O11 | バリュエーション指標（/equities/valuation） | https://jpx-jquants.com/ja/spec/eq-valuation.md | 本APIの留意点 ・データ項目概要（A3 の準備度の参照） |
| O12 | 指標の算出方法 | https://jpx-jquants.com/ja/spec/eq-valuation/calc.md | 各指標の定義 ・Null の条件（A3 の準備度の参照） |
| O13 | 株価四本値（/equities/bars/daily） | https://jpx-jquants.com/ja/spec/eq-bars-daily.md | 本APIの留意点 ・データ項目概要（A3 の準備度の参照） |
| O14 | 契約ごとに利用可能なAPIとデータ格納期間 | https://jpx-jquants.com/ja/spec/data-spec.md | プラン別の表（Light の範囲） |

---

## 4. DocType（A）

### 4.1 公式の値の全集合（O3 ・O4。DOCUMENTED）

| 群 | 値（`<期間>` は `FY` ・`1Q` ・`2Q` ・`3Q` ・`OtherPeriod`） | 公式の概要 |
|---|---|---|
| 連結 ・日本基準 | `<期間>FinancialStatements_Consolidated_JP` | 決算短信（連結・日本基準）/ Consolidated, JP GAAP |
| 連結 ・米国基準 | `<期間>FinancialStatements_Consolidated_US` | （連結・米国基準）/ US GAAP |
| 非連結 ・日本基準 | `<期間>FinancialStatements_NonConsolidated_JP` | （非連結・日本基準）/ Non-consolidated, JP GAAP |
| 連結 ・JMIS | `<期間>FinancialStatements_Consolidated_JMIS` | （連結・ＪＭＩＳ） |
| 非連結 ・IFRS | `<期間>FinancialStatements_NonConsolidated_IFRS` | （非連結・ＩＦＲＳ） |
| 連結 ・IFRS | `<期間>FinancialStatements_Consolidated_IFRS` | （連結・ＩＦＲＳ） |
| 非連結 ・外国株 | `<期間>FinancialStatements_NonConsolidated_Foreign` | （非連結・外国株）/ Non-consolidated, Foreign |
| 連結 ・外国株 | `<期間>FinancialStatements_Consolidated_Foreign` | （連結・外国株）/ Consolidated, Foreign |
| REIT | `FYFinancialStatements_Consolidated_REIT` | 決算短信（REIT） |
| 予想の修正 | `DividendForecastRevision` ・`EarnForecastRevision` ・`REITDividendForecastRevision` ・`REITEarnForecastRevision` | 配当予想の修正 ・業績予想の修正 ・分配予想の修正 ・利益予想の修正 |

計 **45 値**（8 群 × 5 期間 ＝ 40 ＋ REIT 1 ＋ 修正 4）。

### 4.2 確かめた事

| 項目 | 分類 | 根拠 |
|---|---|---|
| 値の全集合 | DOCUMENTED | O3 ・O4 の表（「財務情報APIのTypeOfDocumentの項目一覧」）。PILOT1 の観測した 14 値はすべてこの表にある |
| 文法 `<期間>FinancialStatements_<連結の区分>_<基準>` | INFERRED | 公式は**列挙**で、文法を定義していない。写しは token の分解ではなく、**公式の列挙との完全一致の表引き**にする（未知の値は UNKNOWN で fail closed） |
| `Consolidated` ／ `NonConsolidated` の意味 | DOCUMENTED | 概要の「連結」／「非連結」 |
| `JP` の意味 | DOCUMENTED | 「日本基準」／「JP GAAP」 |
| `US` ・`IFRS` ・`JMIS` | DOCUMENTED | 「米国基準」「ＩＦＲＳ」「ＪＭＩＳ」。**USGAAP ・JMIS は存在する**（PILOT1 では未観測） |
| `Foreign` | DOCUMENTED（「外国株」）／ 会計基準は UNKNOWN | 会計基準の名前ではなく発行体の種別。どの会計基準かは示されない |
| `REIT` | DOCUMENTED | REIT の決算短信。財務の指標の対象外にする |
| `OtherPeriod` | DOCUMENTED | 「その他四半期決算短信」（`CurPerType` の `4Q` ・`5Q` と対応するかは INFERRED） |
| 公式の列挙に無い組（`NonConsolidated_US` ・`NonConsolidated_JMIS` 等） | UNKNOWN | 列挙に無いだけで、存在しないとは言わない。来たら UNKNOWN で保留 |
| 修正の行の連結の区分 ・会計基準 | DOCUMENTED（token が無い） | 修正の 4 値は区分 ・基準の token を含まない。O1 ・O2 に別の欄も無い（field 表 §5） |

---

## 5. field の意味（`/v2/fins/summary`）

### 5.1 field の集合（DOCUMENTED ＋ OBSERVED_IN_PILOT）

- O2 の Data Item の表は 111 欄。PILOT1 §6.1 の 111 欄と**集合として完全に一致**し（公式にあって未観測 0、観測して公式に無い 0）、
  O1 のレスポンスサンプルの key も同じ 111。綴り（`FNP` と `NxFNp` など）も公式どおり。
- O2 は全欄を `Required` とする（key は常にある。値は空文字になり得る）。
- 全欄は **JSON の文字列**。数の欄も文字列（DOCUMENTED、O1 ・O2「すべての項目をJSON文字列（string）で返却」）。

### 5.2 識別 ・時刻 ・期間

| field | 公式の意味（O1 ／ O2） | 分類 ・注記 |
|---|---|---|
| `DiscDate` | TDnetの開示日(JST) ／ Disclosed date on TDnet (JST) | DOCUMENTED（§6） |
| `DiscTime` | TDnetの開示時刻(JST) ／ Disclosed time on TDnet (JST) | DOCUMENTED（§6） |
| `Code` | 銘柄コード（5桁） | DOCUMENTED |
| `DiscNo` | 開示番号。JSON は開示番号の昇順 | DOCUMENTED。**開示の順序を保証しない**（順序は DiscDate ・DiscTime）。訂正には新しい DiscNo（§9.3） |
| `DocType` | 開示書類種別 | DOCUMENTED（§4） |
| `CurPerType` | 当会計期間の種類 `[1Q, 2Q, 3Q, 4Q, 5Q, FY]` | DOCUMENTED |
| `CurPerSt` ／ `CurPerEn` | 当会計期間開始日 ／ 終了日 | DOCUMENTED（両端を含むかは UNKNOWN） |
| `CurFYSt` ／ `CurFYEn` | 当事業年度開始日 ／ 終了日 | DOCUMENTED。決算期の変更を示す欄は無く、`CurFYEn` の変化で判断（O1） |
| `NxtFYSt` ／ `NxtFYEn` | 翌事業年度開始日 ／ 終了日。翌事業年度の開示情報が無い場合は空 | DOCUMENTED |

### 5.3 実績（接頭辞なし）・単体（`NC*`）

| field | 公式の意味 | 実績 ／ 予想 | 連結 ／ 単体 | 期間 | 単位 ・通貨 |
|---|---|---|---|---|---|
| `Sales` | 売上高 ／ Net Sales | 実績 | 行の DocType の区分（§8.2。INFERRED ＋ OBSERVED） | 期首からの累計（O7。DOCUMENTED） | 円 ・ONE（O1。§10） |
| `OP` | 営業利益 ／ Operating Profit | 実績 | 同上 | 累計（DOCUMENTED） | 同上 |
| `OdP` | 経常利益 ／ Ordinary Profit。IFRS ・米国基準では概念が無く空 | 実績 | 同上 | 累計（DOCUMENTED） | 同上 |
| `NP` | 当期純利益。**親会社株主に帰属する当期純利益**（非支配株主持分を含む合計ではない） | 実績 | 同上 | 累計（DOCUMENTED） | 同上 |
| `EPS` ／ `DEPS` | 一株あたり当期純利益 ／ 潜在株式調整後 | 実績 | 同上 | 累計か UNKNOWN（O7 は 4 欄だけを明記） | 1 株当たり。円は INFERRED（O1 の「金額項目は円単位」に含むと推論） |
| `TA` ・`Eq` ・`ShEq` | 総資産 ・純資産 ・自己資本 | 実績（残高） | 同上（O9 は `ShEq` を「連結」と記す。§8.2） | 期末の残高（INFERRED） | 円 ・ONE |
| `EqAR` ・`ROE` | 自己資本比率 ・自己資本利益率 | 実績 | 同上 | UNKNOWN | 比率。小数か百分率かは UNKNOWN（サンプルの値の形は小数に見える ＝ INFERRED） |
| `BPS` | 一株あたり純資産 | 実績 | 同上 | 期末 | 1 株当たり |
| `CFO` ・`CFI` ・`CFF` ・`CashEq` | 営業 ・投資 ・財務の CF、現金及び現金同等物期末残高 | 実績 | 同上 | CF の累計は UNKNOWN | 円 ・ONE |
| `NC*`（`NCSales` ・`NCOP` ・`NCOdP` ・`NCNP` ・`NCEPS` ・`NCTA` ・`NCEq` ・`NCEqAR` ・`NCBPS` ・`NCShEq` ・`NCROE`） | 各項目の「_非連結」／ Non-consolidated | 実績 | **非連結**（DOCUMENTED） | 同上 | 同上。**会計基準は UNKNOWN**（行の基準 token が `NC*` に当たるかは公式に無い） |

### 5.4 予想

| field | 公式の意味 | 対象の期間 |
|---|---|---|
| `FSales` ・`FOP` ・`FOdP` ・`FNP` ・`FEPS` | 〜_予想_期末 ／ Forecast ... Fiscal Year End | 当事業年度の通期（DOCUMENTED：「期末」と「翌事業年度期末」の対比。同じ行の `CurFYSt` ／ `CurFYEn` との結び付けは INFERRED） |
| `FSales2Q` ・`FOP2Q` ・`FOdP2Q` ・`FNP2Q` ・`FEPS2Q` | 〜_予想_第2四半期末 | 当事業年度の第 2 四半期末（累計 ＝ 上半期かは INFERRED） |
| `NxFSales` ・`NxFOP` ・`NxFOdP` ・`NxFNp` ・`NxFEPS` | 〜_予想_翌事業年度期末 | 翌事業年度（`NxtFYSt` ／ `NxtFYEn`。DOCUMENTED） |
| `NxF*2Q` | 〜_予想_翌事業年度第2四半期末 | 翌事業年度の第 2 四半期末 |
| `FNC*` ・`NxFNC*`（`2Q` を含む） | 上の各項目の「_非連結」 | 同上。**非連結**（DOCUMENTED） |
| 配当の予想 `FDiv*` ・`NxFDiv*` | 一株あたり配当予想（`FDivAnn` ・`NxFDivAnn` は「日本円、1株当たり」） | 当期 ／ 翌期 |
| `FDivUnit` ・`NxFDivUnit` | **1口当たり予想分配金（REIT）** | 単位の欄ではない |
| `FDivTotalAnn` ・`FPayoutRatioAnn` ・`NxFPayoutRatioAnn` | 予想配当金総額 ・予想配当性向 | — |

- 予想は**単一の値で開示された予想だけ**を収録し、**レンジ形式の予想は収録しない**（O1。DOCUMENTED）。
- 予想の欄の連結の区分: `F*`（接頭辞 `NC` なし）が連結か、行の区分に従うかは公式に無い（UNKNOWN。§9）。

### 5.5 配当 ・株数 ・印

| field | 公式の意味 | 注記 |
|---|---|---|
| `Div1Q`〜`DivFY` ・`DivAnn` | 一株あたり配当実績（日本円、1株当たり） | DOCUMENTED。**分割 ・併合の遡及調整なし**。分割の年の記載は会社ごとに異なる（O1） |
| `DivUnit` | **1口当たり分配金（REIT）** | PILOT1 の「単位の欄か」の疑いは解消（単位ではない） |
| `DivTotalAnn` ・`PayoutRatioAnn` | 配当金総額 ・配当性向 | — |
| `ShOutFY` | 期末発行済株式数（**自己株式を含む**） | DOCUMENTED（O2「Including Treasury Stock」、O7） |
| `TrShFY` | 期末自己株式数 | DOCUMENTED。`ShOutFY − TrShFY` で自己株式を除く株数（O7） |
| `AvgSh` | 期中平均株式数 | DOCUMENTED |
| `MatChgSub` ・`SigChgInC` ・`ChgByASRev` ・`ChgNoASRev` ・`ChgAcEst` ・`RetroRst` | 重要な子会社の異動 ・連結範囲の重要な変更（2024-07-21 以前の date は値なし）・会計基準等の改正に伴う会計方針の変更 ・それ以外の変更 ・会計上の見積りの変更 ・修正再表示 | DOCUMENTED（値の形 `true` ／ `false` ／ `""` は OBSERVED_IN_PILOT） |

### 5.6 欠損（H）

- 値が無い項目は `null` ではなく**空文字 `""`**（O1 ・O2。DOCUMENTED。PILOT1 と一致）。
- **空文字は「当該の開示書類に値の記載が無かった」ことだけを示す**。前回の開示からの変更の有無、予想の撤回 ・未定を表さない（O1）。
- IFRS ・米国基準の `OdP` は概念が無いので空（O1 ・O7）。JMIS の `OdP` は UNKNOWN。
- A2 への写しの推奨: `""` → `NOT_REPORTED`（公式の意味そのもの）。「概念なし」の `NOT_APPLICABLE` は公式が明記した組
  （`OdP` × IFRS ／ US）だけに限り、それ以外は推定しない。**`""` を 0 や前回値で埋めない。予想の撤回と読まない。**

---

## 6. DiscDate ／ DiscTime（G。CRITICAL。P8-OBS-1 ・17 ・51）

| 問い | 答え | 分類 ・出所 |
|---|---|---|
| 公表 ／ 開示の時刻か | **TDnet の開示日 ・開示時刻** | DOCUMENTED（O1 ・O2） |
| time zone | **JST** | DOCUMENTED（O1 ・O2） |
| 形 | `YYYY-MM-DD` ／ `HH:MM:SS`（O1 のサンプル `2023-01-30` ／ `12:00:00`） | DOCUMENTED（サンプル）＋ OBSERVED_IN_PILOT |
| DiscTime の欠損 | field 表は `Required`。空になり得るかは明記なし（一般の規則は「値が無ければ `""`」） | UNKNOWN（PILOT1 の 1,533 行では空 0） |
| 日付だけの応答 | 公式に記述なし | UNKNOWN |
| 開示の順序 | DiscNo は順序を保証しない。順序は DiscDate ・DiscTime | DOCUMENTED（O1） |
| API の record はその時点で公開 ／ 既知か | 開示の**内容**は DiscTime に TDnet で公開された。**J-Quants の API への反映は別**: Light 等（Premium 以外）は日次（18:00 頃 速報 ／ 24:30 頃 確報）、時刻は約束されない。開示の検知後に短い間隔で問い合わせても日次の反映まで返らない（O5 ・O7） | DOCUMENTED |
| 後から取った値は開示時点の値か | 各 record は開示時点の基準の値を保持し、分割調整 ・訂正の遡及修正をしない。訂正は新しい DiscNo の別の record（O1）。**ただし業者の不備の修正は上書きで、版番号 ・ETag は無い**（O5 ・O8。財務情報は 2024-02-28 ・2024-08-02 ・2025-05-02 に「データ全般を修正」） | DOCUMENTED |

**A2 の写しの評価（A2 は変えない）:**

| 条件 | A2 の `KnowledgeTime` | 公式の正当化 |
|---|---|---|
| DiscDate と DiscTime が正しい形 | `TIMESTAMP`（DiscDate ＋ DiscTime、**JST**。丸めない） | DOCUMENTED（TDnet の開示時刻 ・JST）。A2 の `TOKYO` は固定の UTC+9 で JST と一致 |
| DiscTime が `""` ・解釈できない | `DATE(DiscDate)`（東京の暦日） | DOCUMENTED（開示日 ・JST）。時刻を作らない |
| `DATE` の日の途中の cutoff | resolver は `INSUFFICIENT_TIME_PRECISION` | 公式の意味と矛盾しない（時刻は不明） |
| DiscDate が無い ・不正 | 行を保留 | — |

- **固定の時刻（15:30 JST ・18:00 ・24:30 等）を作らない。** O5 の 18:00 ／ 24:30 は「頃」の目安で約束ではない（O5 に明記）。
- `TIMESTAMP(DiscDate DiscTime)` が表すのは「開示が TDnet で公開された時刻」。**J-Quants Light だけを読む系が値を得られた時刻では
  ない**。backtest ・運用の再現で「API から得られた時刻」が要る場合は、別の軸（取得の時刻 ／ 反映の遅れの方針）として adapter ・A3 の
  契約で扱う（P8-OBS-17。本 gate は決めない）。
- 速報 ／ 確報の 2 回の更新の間に record の値が変わり得るかは UNKNOWN（O5 は時刻だけを示す）。

---

## 7. 会計基準 ・連結の区分の隔たり G1 の再評価（B ・C）

### 7.1 公式の仕様から分かった事

- 会計基準と連結の区分は、**財務諸表の行の DocType だけ**が示す（専用の欄は無い。field 表 §5）。値の集合は公式の列挙（§4）。
- 修正の行（`EarnForecastRevision` 等）は**どちらも示さない**（DOCUMENTED）。
- 予想は同じ対象の年度について複数の行に現れる: 年度の行の `NxF*`（翌事業年度）と、翌年度の四半期の行の `F*`（当事業年度）、
  さらに修正の行の `F*`（DOCUMENTED の field の定義からの構造）。
- 会計基準の変更は公式に想定されている（`ChgByASRev` 等の欄。決算期の変更は `CurFYEn` で判断 ＝ O1）。

### 7.2 G1 の判断: **real defect（実の欠陥）。ただし slot の identity の変更は必須ではない**

| 候補 | 判断 | 理由 |
|---|---|---|
| real defect | **該当** | 予想の slot（主語 ・欄 ・`statement_basis` ・対象の期間）は、会計基準の変更をまたいで、前の基準の `NxF*` と新しい基準の `F*` の値を**同じ鎖の `supersedes` の revision** としてしか入れられない（INFERRED。公式の構造から起こり得る）。修正の行は基準を持たないので、そのまま鎖に入れば基準の不明な値が revision になる。A2 だけでは「基準の違い」と「会社の予想の修正」を区別できない |
| acceptable simplification | 非該当 | D-P8-A2R-1（会計基準は観測の意味の一部）に反する |
| metadata-only remediation sufficient | **条件つきで該当** | 比較の可否（A3 の `NOT_COMPARABLE`）は metadata で足りる。ただし metadata だけでは**違う基準の値が同じ鎖に入ること自体**を防げない → 取り込みの入口の guard が要る（§8 Option E） |
| slot identity remediation required | 非該当（必須ではない） | 入口の guard で「1 つの鎖 ＝ 1 つの会計基準 ・1 つの連結の区分」を fail closed で保てば、凍結した slot の key ・hash を壊す Option A は要らない。基準が変わる時は鎖に足さず保留し、監督の規則（別の出所の class ／ 別の record）を待つ |

実績の slot での衝突（同じ期間に違う基準の実績）は、実績が開示ごとの当期の値だけを持つ（O1）ので稀だが、訂正 ・基準の変更の年で
起こり得ないとは言えない（UNKNOWN）→ 同じ guard で扱う。

---

## 8. remediation の選択肢の再評価（設計だけ。実装しない）

### 8.1 A〜D（前回）と E（新）

| 観点 | A: 既存の record の拡張 | B: 意味の metadata | C: provider の写しの provenance | D: B ＋ C | **E: D ＋ 入口の guard（推奨）** |
|---|---|---|---|---|---|
| 凍結した A2 の 3 module | 変更（破壊的） | 不変 | 不変 | 不変 | **不変** |
| 会計基準の enum の根拠 | — | 公式の列挙で決められる（§8.3） | — | 同左 | 同左 |
| 同じ slot に違う基準 | identity で分かれる | 検知できるが防げない | 防げない | 検知だけ | **入口で保留（鎖に入れない）** |
| 修正の行（基準の token なし） | 必須の欄を埋められない | `UNKNOWN` で表せる | 写しの根拠なし ＝ `UNKNOWN` | 同左 | 同左 ＋ 既知の鎖に足さない |
| PIT ・追記専用 | 過去の record の再解釈 | 追記だけ | 追記だけ | 追記だけ | 追記だけ（guard は判定だけで履歴を変えない） |
| 公式の確認の後の妥当性 | 不要に破壊的 | 必要 | 必要 | 必要だが不足（G1 の鎖の混入） | **十分** |

**Option D は公式の確認の後も妥当**（canonical の語彙と provider の写しを分ける）。ただし G1 を fail closed にするには、D の
record に加えて**取り込みの入口の guard** が要る。これを **Option E** として推奨する。

### 8.2 連結の区分（statement basis）の表現の推奨

| 行 ／ 欄 | canonical の `StatementBasis` | 根拠の分類 |
|---|---|---|
| `*_Consolidated_*` の行の接頭辞の無い欄 | `CONSOLIDATED` | DOCUMENTED（DocType の「連結」）＋ O9（`ShEq` ＝ 連結） |
| すべての行の `NC*` ・`FNC*` ・`NxFNC*` | `NON_CONSOLIDATED` | DOCUMENTED（field の「_非連結」） |
| `*_NonConsolidated_*` の行の接頭辞の無い欄 | `NON_CONSOLIDATED`（**監督の承認が要る写し**） | OBSERVED_IN_PILOT（`NonConsolidated` の行は単体の値を接頭辞の無い欄に持ち `NC*` は空）＋ DocType の「非連結」＝ DOCUMENTED。**field の定義は接頭辞の無い欄の区分を明記せず、O9 は `ShEq` ・`ROE` を「連結」と呼ぶ（DOC_CONFLICT。P8-OBS-55）** → 承認が無ければ UNKNOWN で保留 |
| `*_NonConsolidated_*` の行の `NC*` に値がある | 保留 | 観測されない組。推定しない |
| 修正の行の接頭辞の無い予想 `F*` | **UNKNOWN**（保留） | 区分の token が無い。別の行から継承しない（D-P8-A2R-5） |
| `REIT` ・`REIT*Revision` | 対象外 | 財務の指標の対象外 |

A2 の `StatementBasis`（`CONSOLIDATED` ／ `NON_CONSOLIDATED`）の語は足りる。足りないのは「UNKNOWN」を表す場所で、これは
Option E の metadata の record が持つ（A2 の record には UNKNOWN の行を写さない）。

### 8.3 会計基準の表現の推奨

canonical の enum（監督の決定を要する。本 gate は案だけ）:

| provider の token（DocType の完全一致の表引き） | canonical の案 | 分類 |
|---|---|---|
| `JP` | `JP_GAAP` | DOCUMENTED |
| `US` | `US_GAAP` | DOCUMENTED |
| `IFRS` | `IFRS` | DOCUMENTED |
| `JMIS` | `JMIS` | DOCUMENTED |
| `Foreign` | `UNKNOWN`（発行体の種別で、会計基準ではない） | DOCUMENTED（「外国株」）→ 基準は UNKNOWN |
| `REIT` | 対象外 | DOCUMENTED |
| 修正の行（token なし） | `UNKNOWN` | DOCUMENTED（token が無い） |
| 列挙に無い値 | `UNKNOWN`（保留） | — |
| 連結の行の `NC*` の値 | `UNKNOWN` | 公式に記述なし。行の token から継承しない |

- canonical の値は**公式の列挙に閉じる**（`JP_GAAP` ・`US_GAAP` ・`IFRS` ・`JMIS` ・`UNKNOWN`）。provider の token の文字列は C の
  provenance に残し、canonical にしない（D-P8-A2R-4）。

### 8.4 Option E の範囲（実装の範囲。**今回は実装しない**）

1. **canonical の意味の metadata の record**（新しい module 1 つ。A2 の観測の record の id を参照）:
   `accounting_standard`（§8.3 の enum ＋ `UNKNOWN`）、`statement_basis_state`（KNOWN ／ UNKNOWN。KNOWN の時は A2 の観測の
   `statement_basis` と一致しなければ reject）、根拠の provenance の record の参照、独自の知識の時刻（観測の知識の時刻より前にしない）。
2. **provider の写しの provenance の record**（新しい module 1 つ）: `DocType` の文字列、出所の欄（`Sales` ／ `NCSales` 等）、写しの
   規則の id と版、公式の出所の参照（本書 O1 ・O3 の節）。写しは**公式の列挙の完全一致の表引き**。
3. **入口の guard**（新しい module 1 つ、または 1 ／ 2 の module の中の純関数）: A2 の store に観測を足す前に、同じ slot の鎖の
   先頭の metadata と会計基準 ・連結の区分が一致することを確かめる。**一致しない ・どちらかが UNKNOWN → 鎖に足さず保留**（fail
   closed）。A2 の store の API は変えない（呼び出す側の前段）。
4. **A3 への出し方の契約**: A3 が使えるのは metadata が会計基準 ・連結の区分ともに KNOWN の観測だけ。比べる 2 つの観測で両方が
   一致する時だけ比べる。違う ・UNKNOWN → `NOT_COMPARABLE`。
5. test: 新しい module の単体の test と、凍結した A2 の 3 module ・A1 ・A1R が byte 一致する guard。
6. **変えない**: `observation_model.py` ・`observation_resolver.py` ・`observation_store.py`、A1 ・A1R、Phase 4〜7、config ・workflow ・
   Pages ・main.py。

監督の決定が要る事: (d1) canonical の会計基準の enum（§8.3 の案で良いか）、(d2) `NonConsolidated` の行の接頭辞の無い欄を
`NON_CONSOLIDATED` に写すことの承認（P8-OBS-55）、(d3) 基準の変更で保留した予想の扱い（永久の保留か、別の規則か）。

---

## 9. 予想の修正の行（D）

| 問い | 答え | 分類 |
|---|---|---|
| 会計基準 | 行に無い（DocType に token が無く、専用の欄も無い） | DOCUMENTED（無いこと） |
| 連結 ／ 単体 | 接頭辞の無い `F*` の区分は示されない。`FNC*` は「_非連結」 | `F*`: UNKNOWN ／ `FNC*`: DOCUMENTED |
| 予想の対象の期間 | `F*` ＝ 当事業年度の期末、`F*2Q` ＝ 当事業年度の第 2 四半期末、`NxF*` ＝ 翌事業年度（field の定義）。修正の行の `CurFYSt` ／ `CurFYEn` との結び付けは公式に無い | field の定義: DOCUMENTED ／ 行の日付との結び付け: INFERRED |
| 修正後の値と修正前の値 | 修正後の値（単一の値だけ。レンジは収録しない）。**修正前の値の欄は無い** | DOCUMENTED（field 表 ・O1） |
| 開示の identity | `DiscNo` ・`DiscDate` ・`DiscTime` ・`Code` を持つ。修正を元の予想の開示に結ぶ欄は無い | DOCUMENTED |
| 空の欄 | 記載が無いだけ（撤回 ・未定ではない） | DOCUMENTED |

**扱い（推奨）**: 修正の行の予想の値は、会計基準 ・（`F*` の）連結の区分を `UNKNOWN` とし、**別の財務諸表の行から継承しない**。
A2 の `FundamentalForecast` は `statement_basis` が必須なので、`F*` は写さない（fail closed）。`FNC*` は `NON_CONSOLIDATED` だが会計基準は
`UNKNOWN` → Option E の入口の guard で既存の鎖に足さない。予想の修正を使う A3 の指標は今は無い。

---

## 10. 単位 ・通貨（F）

| 項目 | 結果 | 分類 ・出所 |
|---|---|---|
| 金額の単位 ・scale | **円単位**。決算短信の表示単位（百万円 ・千円）に依らず XBRL の値。業者の換算 ・丸めなし → A2 の `Scale.ONE` | DOCUMENTED（O1「項目のスケール、単位について」、O2） |
| 通貨 | 円（O1）。**ただし O10 は、銘柄コード 62690 が 2022 年 2 月以降 米ドルで表示し、`/fins/details` の data も米ドルと記す**。`/fins/summary` に通貨の欄は無く、同じ発行体の summary の通貨は UNKNOWN | DOCUMENTED ＋ **DOC_CONFLICT**（P8-OBS-53） |
| EPS ・BPS | 1 株当たりの額。通貨の明記は無い（金額の一般の規則に含むと推論） | INFERRED |
| 配当の実績 ・`FDivAnn` ・`NxFDivAnn` | 「日本円、1株当たり」 | DOCUMENTED |
| `FDiv1Q`〜`FDivFY` ・`NxFDiv1Q`〜`NxFDivFY` | 通貨の明記なし | INFERRED（円） |
| `DivUnit` ・`FDivUnit` ・`NxFDivUnit` | **REIT の 1 口当たり（予想）分配金**。単位 ・scale の欄ではない | DOCUMENTED |
| 株数 | 株数（`ShOutFY` ・`TrShFY` ・`AvgSh`）。scale の明記なし | 意味: DOCUMENTED ／ scale ONE: INFERRED |
| 比率（`EqAR` ・`ROE` ・`PayoutRatioAnn`） | 小数か百分率かの明記なし | UNKNOWN（サンプルの形からは小数 ＝ INFERRED） |

- **暗黙の百万円の換算は禁止のまま**。公式は「円単位 ・換算なし」なので、写しは `Scale.ONE` で、換算は不要。
- 通貨の推奨: `Currency.JPY` を付けてよいのは (a) DocType が `JP` ・`IFRS` ・`US` ・`JMIS` の財務諸表の行で、(b) 非円の表示が
  公式に記された発行体でない場合。`Foreign` の行と、非円の表示が記された発行体は保留（通貨 UNKNOWN）。

---

## 11. P8-OBS-50 の最終の処分

**REQUIRES_A2_REMEDIATION。**

- provider の側は公式の仕様で解けた（DOCUMENTED）: 会計基準 ・連結の区分は DocType の値で示され、値の全集合は公式の列挙（45 値）、
  `JP` ＝ 日本基準、`US` ・`JMIS` ・`IFRS` ・`Foreign` ・`REIT` が存在し、修正の行は区分 ・基準を持たない（§4）。
- 公式でも解けない残り（UNKNOWN。fail closed で扱える）: 連結の行の `NC*` の会計基準、修正の行の `F*` の連結の区分、
  `NonConsolidated` の行の接頭辞の無い欄の区分の公式の明記（DOC_CONFLICT。P8-OBS-55）。
- 閉じない理由: **A2 に会計基準の次元が無く、同じ slot に違う基準の値が revision として入り得る**（G1。§7）。これは A2 の側の
  表現の欠陥で、追加だけの remediation（Option E。§8.4）が要る。
- authority: O1 ・O2（field）、O3 ・O4（DocType）、O9（`ShEq` の「連結」）。

---

## 12. A3 の準備度（A3 は開始しない）

分類は provider の意味の準備度。**すべての財務の指標は、Option E の実装（A2 の追加の remediation）の前は開始できない**
（D-P8-A2R-6）。実データは実の identity の登録の前は BLOCKED_BY_IDENTITY（P8-OBS-12 ・29）。

| 指標 | 分類 | 条件 ・理由 |
|---|---|---|
| **売上成長率** | **READY_WITH_RESTRICTIONS** | `Sales` ＝ 売上高（DOCUMENTED）、期首からの累計（DOCUMENTED）、円 ・ONE（DOCUMENTED）。制限: 同じ発行体 ・同じ `CurPerType` ・同じ会計基準 ・同じ連結の区分（metadata が KNOWN）、`CurFYEn` の変化（決算期の変更）は NOT_COMPARABLE、単独の四半期を引き算で作らない、`""` は NOT_REPORTED（0 にしない）、`Foreign` ・`REIT` ・`OtherPeriod`（4Q ・5Q）は除く、非円の表示の発行体は除く。項目の会計上の定義は原典（短信）に依る（O1）ので**発行体をまたぐ比較はしない** |
| **営業利益率** | **READY_WITH_RESTRICTIONS** | `OP` ／ `Sales`（同じ行）。売上成長率の制限 ＋ `OP` が `""` の行（営業利益を記載しない発行体）は算出しない。IFRS の営業利益は会社ごとの定義（原典参照）→ 基準をまたいで比べない |
| 純利益率 | READY_WITH_RESTRICTIONS | `NP` ＝ 親会社株主に帰属する当期純利益（DOCUMENTED）。同じ制限 |
| EPS 成長率 | BLOCKED_BY_UNIT_SEMANTICS | 分割 ・併合の遡及調整をしない（O1 ・O7）→ 1 株当たりの基準が期間で変わる。corporate action の参照の観測（P8-OBS-24）が要る。EPS の累計も UNKNOWN |
| ROE | BLOCKED_BY_PROVIDER_MAPPING | A2 の `EQUITY` は 1 つで定義なし、J-Quants は `Eq`（純資産）と `ShEq`（自己資本）を分ける（P8-OBS-27）。四半期の累計の年率化は A2 に無い。provider の `ROE` の算式は公式に無い |
| ROA | READY_WITH_RESTRICTIONS | `NP` ／ `TA`（DOCUMENTED）。年度の行（`FY`）だけ（年率化 ・TTM を作らない）。同じ基準 ・区分 |
| PER | BLOCKED_BY_UNIT_SEMANTICS | 自前の算出は分割の未調整の EPS と価格の日の株数の基準がずれる。公式のバリュエーション指標 API（O11 ・O12。Light で利用可 ＝ O14）の `PER` は定義が公開されているが、A2 に取り込みの class が無い → 使うなら別の gate |
| PBR | BLOCKED_BY_UNIT_SEMANTICS | PER と同じ（`BPS` の分割の基準） |
| 時価総額 | BLOCKED_BY_PROVIDER_MAPPING | 株数の意味は DOCUMENTED（`ShOutFY` は自己株式を含む、`TrShFY`）だが、A2 の `SHARES_OUTSTANDING` の定義が未決（P8-OBS-23 ・27）、四半期の行の「期末」の時点は UNKNOWN。公式の `MktCap`（O11。百万円、自己株式を控除）は別の gate |
| 価格の return | READY_WITH_RESTRICTIONS | 生値（調整前 ・円）を使う。調整値は後の corporate action で遡及して再計算される（O13。DOCUMENTED）→ PIT には生値。分割をまたぐ return は参照の観測（P8-OBS-24）が要る |
| 変動率 | READY_WITH_RESTRICTIONS | 価格の return と同じ |
| 流動性 | READY_WITH_RESTRICTIONS | A2 は `VOLUME` だけ（売買代金 `Va` は A2 に無い）。出来高の単位は普通株で株数、ETF ・REIT で口数（O13）。立会内だけ |

**最初の A3 の候補（売上成長率 ・営業利益率）**: provider の意味は **READY_WITH_RESTRICTIONS**。ただし **Option E の実装の後でなければ
開始できない**。今回は A3 を開始していない。

---

## 13. P8-OBS の登録の更新

| id | 所見 | 前の分類 | 新しい分類 | 根拠 |
|---|---|---|---|---|
| P8-OBS-1 | 財務の既知の時刻が開示時刻を無視（legacy） | BLOCKED_PENDING_OFFICIAL_VERIFICATION | **STRUCTURALLY_ADDRESSED** | DiscDate ／ DiscTime ＝ TDnet の開示日 ／ 時刻（JST）が DOCUMENTED（§6）。A2 の TIMESTAMP ／ DATE で表せ、写しは公式に正当化できる。adapter が実装するまで CLOSED にしない |
| P8-OBS-9 | 調整後価格の遡及 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | **STRUCTURALLY_ADDRESSED** | 調整済みの値は後の corporate action で遡及して再計算され、PIT には調整前の値を使うよう公式が明記（O13 ・O7）。A2 は生値と調整値を別の鎖に持つ |
| P8-OBS-17 | 知識の時刻が真の公表時刻かを store は検証できない | BLOCKED_PENDING_ADAPTER | BLOCKED_PENDING_ADAPTER（前提は公式に確認） | 訂正は新しい DiscNo で上書きしない（O1）＝ V13 の前提は DOCUMENTED。残り: 業者の不備の修正は上書きで版 ・ETag なし（O5 ・O8）、Light の反映は日次（O5）→ adapter の raw digest と取得の時刻の軸 |
| P8-OBS-18 | identity の知識の時刻の食い違い | STRUCTURALLY_ADDRESSED（P8-A1R） | STRUCTURALLY_ADDRESSED（変更なし） | 本 gate の公式の確認は影響しない |
| P8-OBS-22 | 財務の期間の意味 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | **STRUCTURALLY_ADDRESSED**（`Sales` ・`OP` ・`OdP` ・`NP`） | 期首からの累計が DOCUMENTED（O7）。`CUMULATIVE_YEAR_TO_DATE`（quarter 1〜3）／ `FISCAL_YEAR` に写せる。EPS ・CF の累計は UNKNOWN、`4Q` ・`5Q` ・`OtherPeriod` は A2 の累計（quarter 1〜3）に入らず保留（P8-OBS-52） |
| P8-OBS-23 | 株数の意味 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | BLOCKED_PENDING_OFFICIAL_VERIFICATION（狭めた） | `ShOutFY`（自己株式を含む）・`TrShFY` ・`AvgSh` は DOCUMENTED。残り: 四半期の行の「期末」の時点、株式の種類、A2 の `SHARES_OUTSTANDING` の定義（P8-OBS-27） |
| P8-OBS-31 | F* ／ NxF* の対象の会計年度が曖昧 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | **STRUCTURALLY_ADDRESSED** | `F*` ＝ 当事業年度の期末、`NxF*` ＝ 翌事業年度（`NxtFYSt` ／ `NxtFYEn`）が DOCUMENTED（§5.4）。修正の行の区分は UNKNOWN（§9） |
| P8-OBS-48 | `OperatingProfit` は V2 の実測に無い（`OP`） | UNRESOLVED | **CLOSED** | V2 の公式の field は `OP`（営業利益）。公式の 111 欄に `OperatingProfit` は無い（O1 ・O2）。V1 の欄名かは gitbook が 403 で未読（本 gate に不要） |
| P8-OBS-49 | 記録の `observed_fields` は網羅ではない | UNRESOLVED | **CLOSED** | 公式の field の一覧（111）＝ PILOT1 の観測（111）。schema の authority は公式の一覧（§5.1） |
| P8-OBS-50 | 会計基準の欄が無く、A2 に会計基準の次元が無い | BLOCKED_ON_OFFICIAL_SPEC（A2R）／ PARTIALLY_RESOLVED（PILOT1） | **REQUIRES_A2_REMEDIATION** | §11 |
| P8-OBS-51 | DiscDate が実の公表日より早くないことの確認 | UNRESOLVED | **STRUCTURALLY_ADDRESSED** | DiscDate ＝ TDnet の開示日（JST）が DOCUMENTED。`DATE(DiscDate)` は開示日と一致 |
| P8-OBS-52【新】 | `CurPerType` の `4Q` ・`5Q` と `OtherPeriod` の DocType（決算期の変更等の長い年度）は A2 の `CUMULATIVE_YEAR_TO_DATE`（quarter 1〜3）に写せない | — | NON_BLOCKING_DEFERRED | 保留（fail closed）で安全。A3 の初期の範囲から除く |
| P8-OBS-53【新】 | `/fins/summary` に通貨の欄が無く、`/fins/details` の公式の文書は米ドル表示の発行体（62690）を記す | — | BLOCKED_PENDING_ADAPTER | adapter は非円の表示の発行体 ・`Foreign` の行を保留する規則が要る（§10） |
| P8-OBS-54【新】 | 業者の不備の修正は record を上書きし、版番号 ・ETag ・通知が無い。財務情報は 1 日 2 回（速報 ・確報）の反映 | — | BLOCKED_PENDING_ADAPTER | raw の digest で業者の改訂を検知し、新しい revision（知識 ＝ 取得の時刻）にする（P8-OBS-17 の規則）。raw の保存は規約の確認まで不可のまま |
| P8-OBS-55【新】 | 接頭辞の無い欄の連結の区分: field の定義は明記せず、O9 は `ShEq` ・`ROE` を「連結」と呼ぶが、`NonConsolidated` の行は単体の値を接頭辞の無い欄に持つ（PILOT1） | — | REQUIRES_A2_REMEDIATION（監督の承認 d2） | Option E の写しの規則で DocType の区分に従わせる（§8.2）。承認までは `NonConsolidated` の行を保留 |

---

## 14. PILOT1 の観測と公式の仕様の照合

| PILOT1 の観測 | 公式 | 結果 |
|---|---|---|
| 111 欄、全て文字列、欠損は `""` | 111 欄、全て JSON 文字列、欠損は `""` | 一致（DOCUMENTED_AND_OBSERVED） |
| DocType 14 値 | 公式の 45 値に含まれる | 一致。未観測の 31 値（`US` ・`JMIS` ・`Foreign` ・`REIT` ・`OtherPeriod` ・`NonConsolidated_IFRS` 等）が公式に存在 |
| `CurPerType` `1Q 2Q 3Q FY` | `1Q 2Q 3Q 4Q 5Q FY` | 観測は部分集合 |
| `CurPerSt` ＝ `CurFYSt`（全行） | 期首からの累計（FAQ） | 整合 |
| IFRS の行の `OdP` が空 | IFRS ・米国基準は経常利益の概念なし | 一致 |
| `NonConsolidated` の行は単体の値を接頭辞の無い欄に持ち `NC*` は空 | 明記なし（O9 は接頭辞の無い `ShEq` を「連結」と呼ぶ） | OBSERVED_IN_PILOT のみ（P8-OBS-55） |
| 通貨 ・scale の欄なし、`*DivUnit` は空 | 円単位 ・換算なし。`*DivUnit` は REIT の分配金 | 解消（単位の欄は元から無い） |
| `DiscTime` は `9:9:9` の形、time zone の印なし | TDnet の開示時刻（JST） | 解消 |
| `DiscNo` は応答の中で一意 | 開示番号、昇順で返る、順序を保証しない、訂正は新しい DiscNo | 解消（一意の範囲の保証は UNKNOWN） |

PILOT1 の report は byte 一致のまま（変えていない）。

---

## 15. 変更したファイル

- `docs/databank/PHASE8_A2R_OFFICIAL_SPEC_VERIFICATION.md`【新規】（本書）
- `CHANGELOG.md`（v5.60）
- `tests/intelligence/phase8_runtime_registry.py`: `PHASE8_DOCS` に本書、P8-A2R の凍結の anchor `P8_A2R`
- `tests/intelligence/test_screener_intelligence_boundary.py`: 本書の登録と、runtime ・Phase 8 の test ・先行の文書（PILOT1 の report ・
  前回の A2R の report を含む）が `P8_A2R` と byte 一致する guard（1 件）
- runtime（A1 ・A2 ・A1R）・config.yaml ・knowledge ・scripts ・workflow ・Pages ・main.py ・Phase 4〜7 ・先行の文書は無変更

---

## 16. 検証

結果は最終報告に記す（Phase 8 の guard ・A1 ・A2 ・A1R ・Phase 7 ・Phase 6 ・Phase 4 ／ 5 の guard ・full pytest。基準 5348 passed ／
2 skipped、guard の追加 1 件で 5349 passed を期待）。

---

## 17. 次の gate の推奨

```
P8-A2R 再実行（本 gate: 公式の仕様を確認。A2 の追加の remediation が要る）
  → 監督の決定: d1 canonical の会計基準の enum（§8.3）、d2 NonConsolidated の行の写しの承認（P8-OBS-55）、d3 基準の変更で保留した予想の扱い
  → P8-A2R-IMPL: Option E（metadata の record ＋ provider の写しの provenance ＋ 入口の guard。追加だけ、凍結の A2 の 3 module は不変）
  → A3: 売上成長率 ・営業利益率（§12 の制限つき。合成 data で。実データは実の identity の登録の後）
```

---

## 18. 判定

**P8_A2_REMEDIATION_REQUIRED**

- 公式の仕様は確認できた（DOCUMENTED の主張は §4〜§10）。
- G1 は実の欠陥で、A3 の前に A2 の側の追加の remediation（Option E）が要る。凍結した A2 の 3 module の変更は要らない。
- A2 の runtime の remediation の実装 ・A3 ・metric engine ・adapter ・実の identity の登録 ・raw の保存 ・screen ・ranking ・推奨 ・
  Theme ・Phase 9 は行っていない。J-Quants の data API への要求は 0 回。
