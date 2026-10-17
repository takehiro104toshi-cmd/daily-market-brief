# PHASE 8 / P8-PILOT1 — J-QUANTS LIGHT `/fins/summary` MINIMAL REAL-RESPONSE OBSERVATION

個人向けの J-Quants API（Light）の `/v2/fins/summary` の**実の応答**を最小限だけ観測し、凍結した P8-A1 ／ A2 と P8-LV1 の契約に対して、
欄の有無 ・形 ・provider から見える意味がどこまで確かめられるかを証拠に基づいて記録する。**ingestion ・adapter ・screen ・指標の計算 ・
backtest ではない。** 監督の再発行した P8-PILOT1 の契約（2026-09-28）に従う。先行の Phase 8 の文書は書き換えない。

- 基準: P8-LV1 `7281d532937f6f68e4b3ecb839506b2616794362`（凍結。P8_LV1_PARTIAL）。runtime ・Phase 8 の test ・先行の文書は `7281d53` と byte 一致。
- 本書は credential ・header ・raw の応答の本文 ・財務の実の値を載せない。載せるのは欄名 ・有無 ・型 ／ 形 ・欠損の表現 ・件数と、
  意味の確認に要る provider の区分の token（`DocType` ・`CurPerType` ・`RetroRst` の値）だけ。

---

## 0. 結論

1. credential は Cloud Environment の proxy の注入で使えた（値は読んでいない）。`api.jquants.com` への network も使えた。
2. API の要求は **3 回 ／ 上限 5 回**。すべて `/v2/fins/summary`、すべて HTTP 200、pagination なし（§5）。
3. 応答は `{"data": [...]}`。1 行は **111 欄**で、3 回の応答の全 1,533 行で欄の集合は 1 通り（key の欠落なし）。値は JSON の
   **文字列**（要求 #1 は 111 欄すべて、#2 ・#3 は表示した欄すべて）で、欠損は **空文字 `""`** だけ（null ・key の欠落は観測されない）（§6）。
4. **`OperatingProfit` は無く `OP` がある**（P8-OBS-48 を実の応答で確認）。記録済みの `observed_fields`（42 欄）は網羅ではない
   （P8-OBS-49 を確認。`NC*` の欄名を含む 111 欄を観測）。
5. **通貨 ・金額の桁（scale）を示す欄は観測されない**（`DivUnit` ・`FDivUnit` ・`NxFDivUnit` は有るが、要求 #1 の全 20 行で空。#2 ・#3 では値を表示していない）。
6. **P8-OBS-50: PARTIALLY_RESOLVED**。連結 ／ 単体と会計基準は、`DocType` の値の中の**別の token**（`Consolidated` ／
   `NonConsolidated` と `JP` ／ `IFRS`）として、財務諸表の行では区別して現れる。ただし専用の欄は無く、token の文法 ・値の全集合 ・
   `JP` の意味は公式の文書で未確認、業績 ／ 配当の予想の修正の行には両方の token が無く、連結の行に同居する `NC*`（単体）の値の
   会計基準は示されない（§8）。
7. **接頭辞の無い欄 ＝ 連結ではない**: `NonConsolidated` の行は単体の値を接頭辞の無い欄（`Sales` ・`OP` ・`NP`）に持ち、`NC*` は空。
   LV1 §9 の LEGACY_INFERENCE を実の応答が否定する（LV1 の変更の候補。§9）。
8. **P8-A2R: SUPERVISOR_DECISION_REQUIRED**（提案。A2R は始めない）。A2 の実績 ／ 予想の record に会計基準の次元が無く、予想の修正の
   行は A2 が必須とする `statement_basis` の出所を持たない（§10）。
9. 判定: **P8_PILOT1_COMPLETE / READY_FOR_SUPERVISOR_REVIEW**（§14）。

---

## 1. 範囲

| 項目 | 本 gate |
|---|---|
| endpoint | `/v2/fins/summary` だけ |
| 要求 | 最大 5 回（使ったのは 3 回） |
| 保存 | raw の応答を repo ・一時の artifact ・git に保存しない。memory の中で schema の観測にだけ使った |
| 出力 | 欄名 ・有無 ・形 ・欠損の表現 ・件数 ・区分の token だけ。財務の値 ・code の一覧は出していない |
| しない事 | A2R ・A3 ・adapter ・実データの永続化 ・実の identity の登録 ・issuer の bootstrap ・Theme ・screen ・ranking ・推奨 ・backtest ・P9 ・P10 ・公開 ／ P4 ／ Pages |

---

## 2. 環境と HEAD

| 項目 | 値 |
|---|---|
| repository ／ branch | daily-market-brief ／ `claude/investment-intelligence-phase6` |
| HEAD（開始時） | `7281d532937f6f68e4b3ecb839506b2616794362`（期待どおり） |
| working tree（開始時） | clean |
| 実行日 | 2026-09-28 |
| 環境 | Claude Code の Cloud Environment「デフォルト」。外向きの HTTPS は agent proxy を通る |

---

## 3. credential の扱い

- credential は Cloud Environment の API 認証情報として登録され、proxy が `api.jquants.com` への要求に `x-api-key` として付ける構成。
- session の環境変数に J-Quants の名前を含む変数は 0 個（名前の数だけを確かめ、値は読んでいない）。proxy の注入の構成なので、
  これを理由に CREDENTIAL_ACCESS_REQUIRED としない（契約 §2）。
- 要求の URL ・query に credential を入れていない。要求の header を出力 ・保存していない。応答の header も出力していない。
- 要求 #1 の HTTP 200 で、credential が本 session から使えることを確かめた。

---

## 4. network

- proxy の状態（local の status endpoint。J-Quants への要求ではない）: enabled、relay の失敗なし。
- `api.jquants.com` への HTTPS: 要求 #1 で HTTP 200（別の到達の確認の要求は使っていない）。

---

## 5. API の要求の台帳

| # | endpoint | 技術的な目的 | 結果 | 行 | 備考 |
|---|---|---|---|---|---|
| 1 | `/v2/fins/summary?code=72030` | credential ／ network の確認 ＋ 1 発行体の複数の開示の schema | 2xx（200） | 20（code 1 個） | pagination_key なし |
| 2 | `/v2/fins/summary?date=2026-08-07` | 1 日の横断の schema（`DocType` ・会計基準 ・連結 ／ 単体の変種） | 2xx（200） | 755（code 728 個） | pagination_key なし |
| 3 | `/v2/fins/summary?date=2026-05-14` | 年度の開示の多い日の横断（`DocType` の語彙の追加の観測） | 2xx（200） | 758（code 741 個） | pagination_key なし |

合計 **3 回 ／ 上限 5 回**。4 回目 ・5 回目は使っていない。

### 5.1 標本の選び方（technical schema observation only）

- 要求 #1 の code `72030` は、repo の既存の J-Quants の標本（`src/intelligence/market/jquants_light_datasets.py` の `fins_summary` の
  `default_params`。run #1 2026-09-01 で使った物）をそのまま使った。新しい選定をしていない。
- 要求 #1 の標本は 1 つの会計基準 ・連結の区分しか含まず、P8-OBS-50 を見られない。そのため日付の指定で横断を取った。日付は機械的に、
  四半期の開示の多い時期（8 月上旬）と年度の開示の多い時期（5 月中旬）の平日を 1 日ずつ選んだ。
- 投資の魅力 ・業績の評価 ・順位を選ぶ理由にしていない。横断の行の code ・社名 ・値は記録していない。

---

## 6. 観測した応答の形

- 最上位: `{"data": [...]}`（3 回とも key は `data` だけ。pagination_key は無い）。
- 1 行は 111 欄。3 回の全 1,533 行で欄の集合は 1 通り（行ごとの key の欠落なし）。
- 値の型: 要求 #1 は 111 欄すべてが文字列。要求 #2 ・#3 で表示した欄もすべて文字列。数の型 ・null は観測されない。
- 数の表現: 整数は数字の文字列、小数は `.` を含む文字列、負は先頭の `-`。
- 欠損: 空文字 `""` だけ。
- 日付: `9-9-9` の形の文字列（数字の列を `-` で区切る。例示の値は載せない）。`DiscTime` は `9:9:9` の形（3 つの数字の列を `:` で区切る）。
- `Code`: 数字の文字列が大部分、英字を含む物もある（要求 #2 で 16 行）。

### 6.1 欄の一覧（実の応答の綴りのまま）

| 群 | 欄 |
|---|---|
| 開示の identity ／ 時刻 | `DiscDate` `DiscTime` `Code` `DiscNo` `DocType` |
| 期間 | `CurPerType` `CurPerSt` `CurPerEn` `CurFYSt` `CurFYEn` `NxtFYSt` `NxtFYEn` |
| 実績（接頭辞なし） | `Sales` `OP` `OdP` `NP` `EPS` `DEPS` `TA` `Eq` `EqAR` `BPS` `CFO` `CFI` `CFF` `CashEq` `ShEq` `ROE` |
| 配当の実績 | `Div1Q` `Div2Q` `Div3Q` `DivFY` `DivAnn` `DivUnit` `DivTotalAnn` `PayoutRatioAnn` |
| 当期の予想（`F`） | `FSales` `FOP` `FOdP` `FNP` `FEPS` ／ 上半期 `FSales2Q` `FOP2Q` `FOdP2Q` `FNP2Q` `FEPS2Q` ／ 配当 `FDiv1Q` `FDiv2Q` `FDiv3Q` `FDivFY` `FDivAnn` `FDivUnit` `FDivTotalAnn` `FPayoutRatioAnn` |
| 翌期の予想（`NxF`） | `NxFSales` `NxFOP` `NxFOdP` `NxFNp` `NxFEPS` ／ 上半期 `NxFSales2Q` `NxFOP2Q` `NxFOdP2Q` `NxFNp2Q` `NxFEPS2Q` ／ 配当 `NxFDiv1Q` `NxFDiv2Q` `NxFDiv3Q` `NxFDivFY` `NxFDivAnn` `NxFDivUnit` `NxFPayoutRatioAnn` |
| 単体の実績（`NC`） | `NCSales` `NCOP` `NCOdP` `NCNP` `NCEPS` `NCTA` `NCEq` `NCEqAR` `NCBPS` `NCShEq` `NCROE` |
| 単体の予想 | `FNCSales` `FNCOP` `FNCOdP` `FNCNP` `FNCEPS` ／ `FNCSales2Q` `FNCOP2Q` `FNCOdP2Q` `FNCNP2Q` `FNCEPS2Q` ／ `NxFNCSales` `NxFNCOP` `NxFNCOdP` `NxFNCNP` `NxFNCEPS` ／ `NxFNCSales2Q` `NxFNCOP2Q` `NxFNCOdP2Q` `NxFNCNP2Q` `NxFNCEPS2Q` |
| 変更 ・修正の印 | `MatChgSub` `SigChgInC` `ChgByASRev` `ChgNoASRev` `ChgAcEst` `RetroRst` |
| 株数 | `ShOutFY` `TrShFY` `AvgSh` |

綴りの注記: 当期の純利益の予想は `FNP`、翌期は `NxFNp`（`p` が小文字）。正規化しない。

### 6.2 区分の token（観測した値の集合。全集合ではない）

| 欄 | 観測した値 |
|---|---|
| `DocType` | `{1Q,2Q,3Q,FY}FinancialStatements_Consolidated_JP`、`{1Q,2Q,3Q,FY}FinancialStatements_NonConsolidated_JP`、`{1Q,2Q,3Q,FY}FinancialStatements_Consolidated_IFRS`、`EarnForecastRevision`、`DividendForecastRevision`（計 14 通り） |
| `CurPerType` | `1Q` `2Q` `3Q` `FY` |
| `RetroRst` | `false` `true` `""`（文字列） |

観測されない変種: `NonConsolidated_IFRS`、`JP` ／ `IFRS` 以外の会計基準の token。3 回の標本に無いだけで、存在しないとは言わない。

---

## 7. 観測の matrix

分類: CONFIRMED ／ PARTIALLY_CONFIRMED ／ NOT_OBSERVED ／ AMBIGUOUS ／ NOT_TESTED ／ UNKNOWN（契約 §9）。

### 7.A 開示の identity ／ 時刻

| 観測 | 実の応答の事実 | 分類 | 残る事 |
|---|---|---|---|
| `DiscDate` | 全行にあり、`9-9-9` の形の文字列、空は 0 行 | PARTIALLY_CONFIRMED | 実の公表日か（P8-OBS-51）は UNKNOWN |
| `DiscTime` | 全行にあり、`9:9:9` の形の文字列、空は 0 行 | PARTIALLY_CONFIRMED | time zone を示す印は NOT_OBSERVED。意味（公表の時刻か）は UNKNOWN。TIMESTAMP を作らない（LV1 §11 のまま） |
| `DiscNo` | 全行にあり、数字の文字列。各応答の中で全行が異なる（20 ／ 755 ／ 758 通り） | PARTIALLY_CONFIRMED | 一意の範囲 ・安定性 ・訂正との関係は UNKNOWN（1 回の観測では示せない） |
| `DocType` | 全行にあり、14 通りの値（§6.2） | CONFIRMED（欄と観測した値） | 値の全集合 ・文法は UNKNOWN |

### 7.B 期間

| 観測 | 実の応答の事実 | 分類 | 残る事 |
|---|---|---|---|
| `CurPerType` | 全行にあり、値は `1Q` `2Q` `3Q` `FY`。予想の修正の行にもある | CONFIRMED（欄と観測した値） | 値の全集合は UNKNOWN |
| `CurPerSt` ／ `CurPerEn` | 全行にあり、日付の形、空は 0 行 | CONFIRMED（有無 ・形） | 両端を含むかは UNKNOWN |
| `CurFYSt` ／ `CurFYEn` | 全行にあり、日付の形、空は 0 行 | CONFIRMED（有無 ・形） | 同上 |
| `NxtFYSt` ／ `NxtFYEn` | 全行に key があり、値は一部だけ（要求 #1: 5 ／ 20、#2: 28 ／ 755）。値のある行の数は `FY` の財務諸表の行の数と一致 | PARTIALLY_CONFIRMED | 行ごとの対応は件数の一致だけで、意味は UNKNOWN |
| 期間の境界の整合 | 1,533 行すべてで `CurPerSt` ＝ `CurFYSt`。`CurPerEn` ＝ `CurFYEn` は `CurPerType` が `FY` の行だけ（1Q ／ 2Q ／ 3Q は 0 行） | PARTIALLY_CONFIRMED | 期間の日付は年度の初めからの累計の幅と一致する。値が累計か（LUV-05）は日付だけでは確定しない（UNKNOWN） |

### 7.C 実績の財務の欄

| 観測 | 実の応答の事実 | 分類 | 残る事 |
|---|---|---|---|
| 売上 `Sales` | 全行に key。財務諸表の行ではほぼ値あり（空は一部の行）。整数の文字列 | CONFIRMED（欄 ・形） | 項目の意味（売上高 ／ 営業収益 等）は UNKNOWN |
| 営業利益 `OP` | 全行に key。整数の文字列、負は `-`。財務諸表の行でも空の行がある（例: 要求 #2 の `1QFinancialStatements_Consolidated_JP` で 457 ／ 476 行だけ値あり） | CONFIRMED（欄 ・形） | 空が「無い」か「当てはまらない」か（LUV-08）は AMBIGUOUS |
| `OperatingProfit` | key として存在しない | NOT_OBSERVED | P8-OBS-48 を確認 |
| 純利益の群 `NP` | 全行に key。整数の文字列、負あり | PARTIALLY_CONFIRMED | 親会社株主に帰属する利益か当期利益かは UNKNOWN。`ProfitAttributableToOwnersOfParent` 等の key は NOT_OBSERVED |
| 経常利益 `OdP` | 全行に key。`IFRS` の行では観測した全行で空、`JP` の行では値あり | PARTIALLY_CONFIRMED | 空が「当てはまらない」を意味するかは UNKNOWN（表現は欠損と同じ `""`） |
| 単体の実績 `NC*` | 年度の連結の行（`FYFinancialStatements_Consolidated_JP` ・`_IFRS`）の多くで値あり、四半期の行と `NonConsolidated` の行では空 | CONFIRMED（観測した同居） | §8 |

### 7.D 予想の欄

| 観測 | 実の応答の事実 | 分類 | 残る事 |
|---|---|---|---|
| 実績と予想の欄の区別 | 予想は `F*` ・`NxF*` ・`F*2Q` ・`NxF*2Q` ・`FNC*` ・`NxFNC*` の接頭辞 ／ 接尾辞で、実績の欄と別の欄 | CONFIRMED（欄の水準で区別できる） | — |
| 予想の欄の意味 | 四半期の行は `F*` に値、年度の行は `NxF*` に値（観測した同居） | PARTIALLY_CONFIRMED | `F` ＝ 当期、`Nx` ＝ 翌期、`2Q` ＝ 上半期は欄名からの推定で、公式の定義は未確認 |
| 予想の修正の行 | `EarnForecastRevision` の行は実績の `Sales` ・`OP` ・`NP` が空、`F*` の一部に値。`DividendForecastRevision` は財務の値なし | CONFIRMED（観測した行） | 修正の対象の期間の意味は UNKNOWN |

### 7.E 単位 ・表現

| 観測 | 実の応答の事実 | 分類 | 残る事 |
|---|---|---|---|
| 数の表現 | JSON の文字列（要求 #1 の 111 欄すべて、#2 ・#3 で表示した欄すべて。数の型は観測されない） | CONFIRMED | 将来の adapter は文字列から読む |
| 通貨 | 通貨を示す欄 ・印は無い | NOT_OBSERVED | LUV-17 は公式の文書が要る |
| 桁 ・単位 | 金額の桁を示す欄は無い。`DivUnit` ・`FDivUnit` ・`NxFDivUnit` は全行に key があり、要求 #1 の全 20 行で空（#2 ・#3 は NOT_TESTED） | NOT_OBSERVED | LUV-16 は公式の文書が要る。`*DivUnit` の意味は UNKNOWN |
| null ／ 欠損 | 欠損は `""` だけ。null ・key の欠落 ・`-` 等の印は観測されない | CONFIRMED（表現） | `""` は欠損と「当てはまらない」（例: IFRS の `OdP`）を区別しない → 意味は AMBIGUOUS |

### 7.F 会計基準 ・連結の区分

| 観測 | 実の応答の事実 | 分類 | 残る事 |
|---|---|---|---|
| 会計基準の専用の欄 | 無い | NOT_OBSERVED | — |
| 会計基準の印 | 財務諸表の行の `DocType` の末尾の token（`JP` ／ `IFRS`） | PARTIALLY_CONFIRMED | `JP` の意味（日本の会計基準か）・他の基準の token ・文法は UNKNOWN |
| 連結 ／ 単体の専用の欄 | 無い | NOT_OBSERVED | — |
| 連結 ／ 単体の印 | 財務諸表の行の `DocType` の中の token（`Consolidated` ／ `NonConsolidated`）＋ 欄の `NC` の接頭辞 | CONFIRMED（観測した行） | §8 |
| 2 つが別の概念として区別できるか | `DocType` の中で別の位置の token。`Consolidated_JP` ・`NonConsolidated_JP` ・`Consolidated_IFRS` を観測 | PARTIALLY_CONFIRMED | §8 |

---

## 8. P8-OBS-50

問い: 実の応答から、連結 ／ 単体の区分と会計基準を、互いに別の意味の情報として区別できるか。

| 事実（実の応答） | 意味 |
|---|---|
| 財務諸表の行の `DocType` は `<期間>FinancialStatements_<連結の区分>_<会計基準>` の形の 3 つの token を持つ（観測した 12 通り） | 2 つの概念は同じ文字列の**別の token** として現れる。観測した行では区別できる |
| 連結の区分と会計基準の組は独立に変わる（`Consolidated_JP` と `Consolidated_IFRS`、`Consolidated_JP` と `NonConsolidated_JP`） | 一方から他方は決まらない |
| 専用の欄は無い | 区別には provider の文字列の分解が要る。文法は公式に未確認 |
| `EarnForecastRevision` ・`DividendForecastRevision` の行は両方の token を持たない | これらの行では区分も会計基準も NOT_OBSERVED |
| `NonConsolidated` の行は単体の値を接頭辞の無い欄に持ち、`NC*` は空 | 接頭辞の無い欄の基準は行の `DocType` で決まる（欄名では決まらない） |
| 年度の連結の行（`_JP` ・`_IFRS`）は `NC*` に単体の値を同居させる | 行の会計基準の token が `NC*` の値にも当たるかは示されない（AMBIGUOUS） |

**処分: PARTIALLY_RESOLVED。**

- 解けた事: 実の応答は、財務諸表の行で連結の区分と会計基準を別々の token として出す。混同せずに観測できる。
- 残る事: (a) token の文法 ・値の全集合 ・`JP` の意味（公式の文書）、(b) 予想の修正の行の区分 ・会計基準、(c) 連結の行に同居する
  `NC*` の値の会計基準、(d) A2 に会計基準の次元が無いこと（保持の場所は監督の判断）。
- 推測で CONFIRMED にしていない: `JP` ＝ 日本の会計基準、`NC*` の会計基準 ＝ 行の基準は、どちらも名前 ・企業の知識からの推定で、
  本 gate では採らない。

---

## 9. LV1 ／ LUV への影響（変更の候補だけ。LV1 は変えない）

| 区別 | 項目 | 内容 |
|---|---|---|
| 観測した provider の事実 | LUV-04 | `CurPerType` の値 `1Q` `2Q` `3Q` `FY` を観測（全集合ではない） |
| 観測した provider の事実 | LUV-05 | 期間の日付は全行で年度の初めから（累計の幅）。値の累計は未確定 |
| 観測した provider の事実 | LUV-18 | 数は文字列、欠損は `""` だけ（null ・key の欠落なし） |
| 観測した provider の事実 | LUV-22（口座の側） | 2026-09-28 に本 session の credential で `/v2/fins/summary` が 200（plan の約束ではない） |
| 観測した provider の事実 | P8-OBS-48 ・49 | `OP` あり ・`OperatingProfit` なし ／ 実の欄は 111 で、記録の 42 欄は網羅ではない |
| LV1 の契約との食い違い（変更の候補） | LV1 §9 ・§19 | 「接頭辞の無い欄 ＝ 連結」（LEGACY_INFERENCE）は `NonConsolidated` の行で成り立たない。`StatementBasis` の出所は `DocType` の token と `NC` の接頭辞の組（候補） |
| LV1 の契約との食い違い（変更の候補） | LV1 §16 | 表の「数の token」は実際には文字列。「数でない印（`-`）」は観測されない |
| LV1 の契約との食い違い（変更の候補） | LV1 §4 | 連結 ／ 単体 ・会計基準の「専用の欄は記録に無い」は実の応答でも専用の欄は無いが、`DocType` の token として現れる |
| 未解決の意味 | LUV-01〜03 ・16 ・17 ・19 ・20 ・21 | DiscTime の time zone ・意味、桁、通貨、訂正、DiscNo の安定性、深さ（実の応答だけでは解けない） |
| 監督の判断が要る | P8-OBS-50 ・LUV-06 ・08 | 会計基準の保持の場所、`DocType` の分解を authority にするか、`""` の扱い（MISSING のまま） |

LV1 の判定 P8_LV1_PARTIAL と LV1 の文書は変えていない。

---

## 10. P8-A2R の推奨

**SUPERVISOR_DECISION_REQUIRED**（提案だけ。A2R は始めない）。

| A2 の凍結の model | 実の provider の意味 | 食い違い |
|---|---|---|
| `FundamentalActual` ／ `FundamentalForecast` は `statement_basis` を持つが、会計基準の次元が無い | 会計基準は行の `DocType` の token で示される | 互換の会計基準の検査（LV1 §20 ・§21）を A2 の record だけで行えない。A2 の拡張か別の保持かは方針の選択 |
| `FundamentalForecast` は `statement_basis` が必須 | 予想の修正の行は連結の区分の token を持たない | adapter が推定で基準を付けない限り、その行は A2 に写せない（保留が安全） |
| `StatementBasis` は `CONSOLIDATED` ／ `NON_CONSOLIDATED` | 連結の行の `NC*` と、単体の行の接頭辞の無い欄 | A2 の語で表せる（欄 ＋ 行の token から決まる）。食い違いではない |
| 欠損は `MISSING` | `""` は欠損と「当てはまらない」を区別しない | `MISSING` に保守的に写せる。食い違いではない |
| 金額は明示の `Scale` と JPY | 応答に桁 ・通貨の印が無い | A2 の食い違いではなく公式の文書の不足（LUV-16 ・17） |

証拠は得られたが、会計基準の保持の場所と予想の修正の行の扱いは方針の選択なので C を推奨する。

---

## 11. 未解決の事項

- 公式の文書で確かめる事（LV1 §27 のまま）: `DocType` の値の全集合と文法、`JP` の意味、DiscTime の time zone、桁 ・通貨、累計 ／ 単独、
  `""` の意味、`*DivUnit` の意味、訂正 ・`RetroRst`、DiscNo の範囲、Light の深さ。
- 規約: INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED のまま（本 gate は raw を保存しない）。
- 観測されない変種: `NonConsolidated_IFRS`、他の会計基準の token。

---

## 12. 安全 ・raw の非保存の確認

- API key の値: 読んでいない。stdout ・stderr ・本書 ・diff ・git に無い。
- `Authorization` ／ `x-api-key` の値: 出力 ・保存していない（要求の header は proxy が付け、観測の code は header を扱わない）。
- raw の応答: memory の中で集計にだけ使い、file に書いていない。repo ・一時の artifact ・git に無い。
- 観測の helper の script は scratchpad にだけ置き、観測の後に削除した（repo に入れていない）。
- credential の file を作っていない。git に credential を加えていない。
- 本書の値の記載は区分の token ・件数 ・形だけ。財務の値 ・横断の code は載せていない。

---

## 13. 次の gate の推奨

```
P8-PILOT1（本 gate: COMPLETE）
  → 監督の判断: P8-OBS-50 の会計基準の保持の場所（A2 の拡張 ＝ P8-A2R か、別の record か）と予想の修正の行の扱い
  → 公式の文書の確認（LV1 §27）: `DocType` の文法 ・桁 ・通貨 ・DiscTime（P8-LV1R か監督の抜粋）
  → A3: 売上成長率 ・営業利益率（確かめた欄だけ）
```

本 gate は A2R ・A3 ・adapter に着手していない。

---

## 14. 検証と判定

### 14.1 本 gate の変更

- `docs/databank/PHASE8_JQUANTS_LIGHT_PILOT1_REPORT.md`【新規】（本書）
- `CHANGELOG.md`（v5.58）
- `tests/intelligence/phase8_runtime_registry.py`: `PHASE8_DOCS` に本書、P8-LV1 の凍結の anchor `P8_LV1`
- `tests/intelligence/test_screener_intelligence_boundary.py`: 本書の登録と、runtime ・Phase 8 の test ・先行の文書が `P8_LV1` と byte 一致する guard
- runtime ・config.yaml ・knowledge ・scripts ・workflow ・Pages ・main.py ・A1 ／ A2 ／ A1R の module と test ・先行の文書は無変更

### 14.2 検証

結果は最終報告に記す（Phase 8 の guard ・A2 ・A1 ・Phase 7 ・Phase 6 の guard ・full pytest。基準 5346 passed ／ 2 skipped）。

### 14.3 判定

**P8_PILOT1_COMPLETE / READY_FOR_SUPERVISOR_REVIEW**
