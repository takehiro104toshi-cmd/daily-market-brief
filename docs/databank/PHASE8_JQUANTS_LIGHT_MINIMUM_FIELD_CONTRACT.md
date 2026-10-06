# PHASE 8 / P8-LV1 — J-QUANTS LIGHT MINIMUM FIELD CONTRACT

最初の実データの Phase 8 の経路（**売上成長率 ・営業利益率**）に要る、個人向けの J-Quants API（Light）の欄の意味だけを確かめる
**狭い仕様の gate**。runtime ・adapter ・live ／ 認証つきの要求 ・A3 の指標の実装は無い。先行の Phase 8 の文書は書き換えない。

- 基準: P8-A1R `e6a750f54dc83e482e649dc65dd0d5131fb9991d`（凍結）、P8-VR `7b8d3757f3cfb0cc80749d36b05aa401ae237b1e`（凍結）。runtime と
  先行の Phase 8 の文書は `e6a750f` と byte 一致。
- 変更: 本書（新規）・`CHANGELOG.md` ・文書の登録と凍結の証明に要る Phase 8 の registry と guard だけ（§29）。
- 本書は実在の code ・社名 ・応答の本文 ・credential を載せない。

---

## 0. 結論

1. **公式の文書の本文を今回も 1 ページも開けなかった。** 2026-09-28 に、本 session の network の egress policy が公式の host
   （`jpx-jquants.com` ・`jpx.gitbook.io` ・`www.jpx.co.jp`）への接続を拒否した（proxy が CONNECT に 403 ＝ policy の拒否。WebFetch も
   `EGRESS_BLOCKED`）。1 回ずつ確かめただけで、再試行 ・迂回（mirror ・cache ・SDK ・検索の要約）はしていない（§2）。
2. したがって、対象の LUV のうち **OFFICIALLY_RESOLVED は 0**。15 件が UNRESOLVED、規約の 2 件が TERMS_REVIEW_REQUIRED（§3）。
3. 欄名は **repo の実測（REPO_ONLY_OBSERVATION: Light の口座の V2 の応答、run #1 2026-09-01）** として、そのままの綴りで記録した:
   `Sales` ・`OP` ・`DiscDate` ・`DiscTime` ・`CurPerType` ・`CurFYSt` ・`CurFYEn` ・`CurPerSt` ・`CurPerEn` ・`DiscNo` ・`DocType`（§4）。
   公式の欄の表とは照合していない。**指示の `OperatingProfit` は V2 の実測の欄に無い**（実測は `OP`。P8-OBS-48）。連結 ／ 単体と
   会計基準を示す専用の欄は、記録された欄の一覧に無い（P8-OBS-49 ・50）。
4. 知識の時刻: **TIMESTAMP を作らない**（DiscTime の意味 ・time zone ・欠損は未確認）。最大でも `DATE(DiscDate)` で、それも DiscDate が
   実の公表日より早くないことの確認が前提（P8-OBS-51）。前向きの取得の時刻だけが欄の意味に依らず安全（§11）。
5. 最小の A2 の写し（§19）: `Sales` → `REVENUE`、`OP` → `OPERATING_INCOME` は **UNRESOLVED**（期間 ・単位 ・通貨 ・基準が未確認）。
   A2 は金額に明示の桁と JPY を要求するので、確認の前は実データを構造として書けない（正しい fail closed）。
6. **売上成長率 ・営業利益率は READY_FOR_A3_SEMANTICS**（互換の条件を A2 の語で定義した。§20 ・§21）。READY_FOR_REAL_MAPPING では
   ない。A2 の実績の record に**会計基準の次元が無い**ことを互換の検査の穴として記録した（P8-OBS-50）。
7. **pilot: NO_PILOT_REQUIRED（本 gate の判断）。** 公式の文書を読めないことは pilot の理由にしない。pilot は文書を読んだ後に残る穴
   だけについて再判断する（§22）。
8. 規約: 本文を読めない → **INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED のまま**（§24）。
9. 判定: **P8_LV1_PARTIAL / OFFICIAL_DOCUMENT_ACCESS_REQUIRED**（§30）。完了には、公式の host を許可した環境での再確認か、監督が
   確かめた公式の page の抜粋（§27 の checklist）が要る。

---

## 1. 範囲と製品の境界

| 記号 | 製品 ／ 領域 | 本書での扱い |
|---|---|---|
| A | 個人向けの J-Quants API（Light plan） | **契約を決める対象。** A の公式の文書か、A の実測だけで決める |
| B | J-Quants Pro | 文脈の証拠だけ（別に印を付ける）。**B の欄の契約を A に移さない** |
| C | JPX の元の data の一般の意味 | 文脈の証拠だけ。A の欄の形 ・意味は決めない |

本書の証拠の印:

| 印 | 意味 | 仕様の根拠になるか |
|---|---|---|
| `OFFICIAL_A` | 本 session で読んだ A の公式の page | なる（**本 gate では 0 件**） |
| `SV_A` | 監督が確かめた A の公式の証拠（SV-01 ・SV-02。SV-02 は過去の plan の資料） | 述べた範囲だけ。過去の資料を現在の entitlement にしない |
| `CONTEXT_B` ／ `CONTEXT_C` | Pro ／ JPX 一般の証拠（SV-04 など） | ならない（文脈だけ） |
| `REPO_ONLY_OBSERVATION` | repo の Light の実測の記録（run #1 2026-09-01、run #21 2026-09-02） | ならない。A の実際の応答の日付つきの事実で、欄名の綴りの記録に使う |
| `LEGACY_INFERENCE` | 既存の code の命名 ・comment ・fixture | ならない |

使わないもの（監督指示 §2）: blog ・Q&A ・wrapper ・SDK ・legacy の挙動 ・検索の要約。本 gate は web 検索を使っていない。

---

## 2. 公式の出所の台帳

公式の page の id と URL は P8-V（`fc91ee1`）の §2 と同じ。本 gate の対象に関わるものだけを載せる。

| id | page | URL | 答える LUV | 本 gate の状態 |
|---|---|---|---|---|
| S01 | 財務情報（/fins/summary）— API reference | https://jpx-jquants.com/ja/spec/fin-summary ・/en/spec/fin-summary | 01〜08 ・16〜20 | DOC_ACCESS_BLOCKED |
| S02 | 開示書類種別 | https://jpx-jquants.com/ja/spec/fin-summary/typeofdocument | 06 ・19 | DOC_ACCESS_BLOCKED |
| S07 | 提供データの更新タイミング | https://jpx-jquants.com/ja/spec/data-update | 01 ・19 | DOC_ACCESS_BLOCKED |
| S08 | 契約ごとに利用可能なAPIとデータ格納期間 | https://jpx-jquants.com/ja/spec/data-spec | 21 ・22 | DOC_ACCESS_BLOCKED |
| S09 | V1 API から V2 API への変更点 | https://jpx-jquants.com/ja/spec/migration-v1-v2 | 欄名の対応（§4） | DOC_ACCESS_BLOCKED |
| S10 | データ内容・仕様（Help） | https://jpx-jquants.com/ja/help/data | 04 ・05 ・16 ・17 ・18 | DOC_ACCESS_BLOCKED |
| S14 | 利用目的・ライセンス（Help） | https://jpx-jquants.com/ja/help/usage | 23 ・24 | DOC_ACCESS_BLOCKED |
| S15 | J-Quants APIサービス利用規約 | https://jpx-jquants.com/termsofservice | 23 ・24 | DOC_ACCESS_BLOCKED |
| S16 | 財務情報（/fins/statements）（V1 の文書） | https://jpx.gitbook.io/j-quants-ja/api-reference/statements | V1 の欄名の文脈だけ | DOC_ACCESS_BLOCKED |
| S17 | API共通の留意事項（V1 の文書） | https://jpx.gitbook.io/j-quants-ja/api-reference/attention | 18 の文脈だけ | DOC_ACCESS_BLOCKED |

到達の記録（2026-09-28、credential なし ・data の path なし、各 1 回）:

| host | shell | WebFetch |
|---|---|---|
| `jpx-jquants.com` | proxy が CONNECT に 403（policy の拒否） | `EGRESS_BLOCKED` |
| `jpx.gitbook.io` | 同上 | 試していない（同じ policy） |
| `www.jpx.co.jp` | 同上 | 試していない（同じ policy） |

監督の証拠: SV-01 ・SV-02（A）、SV-04（B。文脈だけ）。内容は P8-VR §2 のまま。

---

## 3. 対象の LUV の処分

分類: `OFFICIALLY_RESOLVED` ／ `PARTIALLY_RESOLVED` ／ `UNRESOLVED` ／ `PILOT_REQUIRED` ／ `TERMS_REVIEW_REQUIRED`。

| LUV | 問い | 公式（A） | 他の証拠（根拠にしない） | 分類 | 解く page |
|---|---|---|---|---|---|
| 01 | DiscTime の意味 | 未読 | 欄は実測にある（REPO） | UNRESOLVED | S01 ・S07 |
| 02 | DiscTime の time zone | 未読 | — | UNRESOLVED | S01 |
| 03 | DiscTime が無い時 | 未読 | — | UNRESOLVED | S01 ・S10 |
| 04 | CurPerType の値の全集合 | 未読 | 欄は実測にある。値は HEAD に記録なし | UNRESOLVED | S01 ・S10 |
| 05 | 累計か単独か | 未読 | A2.5 は累計と推定（INFERRED） | UNRESOLVED | S10 ・S01 |
| 06 | 連結 ／ 単体 ・会計基準 | 未読 | 単体は `NC` で始まる別の欄として併存（REPO の注記。名前は未記録） | UNRESOLVED | S01 ・S02 |
| 07 | 売上の意味 | 未読 | legacy は `net_sales` と命名（LEGACY_INFERENCE） | UNRESOLVED | S01 |
| 08 | 営業利益の意味 ・有無 | 未読 | — | UNRESOLVED | S01 ・S02 |
| 16 | 単位 ・桁 | 未読 | — | UNRESOLVED | S01 ・S10 |
| 17 | 通貨 | 未読 | — | UNRESOLVED | S01 ・S10 |
| 18 | null ／ 空 ／ key なし ／ 0 | 未読 | legacy の parser は 3 つの表現を潰す（P8-OBS-26） | UNRESOLVED | S10 ・S17（V1 の文脈） |
| 19 | 訂正開示の挙動 | 未読 | SV-04（B）は財務の領域が改訂に敏感なことだけ | UNRESOLVED | S01 ・S07 ・S10 |
| 20 | 開示の record の identity（DiscNo） | 未読 | 欄は実測にある | UNRESOLVED | S01 |
| 21 | 現在の Light の履歴の深さ | 未読 | SV-02 の 5 年は過去の案内（現在に使わない） | UNRESOLVED（PLAN_UNRESOLVED） | S08 |
| 22 | 現在の Light の entitlement | 未読 | REPO: 2026-09-01 に 200。SV-02 は過去の資料 | UNRESOLVED（PLAN_UNRESOLVED） | S08 |
| 23 | 保存 ・cache の規約 | 未読 | — | TERMS_REVIEW_REQUIRED | S14 ・S15 |
| 24 | 派生の出力 ・公開の規約 | 未読 | — | TERMS_REVIEW_REQUIRED | S14 ・S15 |

集計: OFFICIALLY_RESOLVED 0 ／ PARTIALLY_RESOLVED 0 ／ UNRESOLVED 15 ／ PILOT_REQUIRED 0 ／ TERMS_REVIEW_REQUIRED 2。

- `PILOT_REQUIRED` を 1 件も付けない理由: 文書を読めていないので、「文書では解けない」ことを示せない（§22）。
- 他の LUV（09〜15 ・25〜27）は P8-VR §8 のまま引き継ぐ（本 gate の対象外）。

---

## 4. 欄名の表

欄名は repo の実測（run #1、`src/intelligence/market/jquants_light_datasets.py` の `observed_fields`）の綴りのまま。大文字 ／ 小文字を
正規化しない。公式の欄名の列は S01 を読むまで空ける。

| 目的 | 実測の欄名（V2 ・REPO） | 公式の欄名（S01） | 注記 |
|---|---|---|---|
| 売上 | `Sales` | 未確認 | 項目の正式名（売上高 ・営業収益 ・収益 など）は未確認 |
| 営業利益 | `OP` | 未確認 | **`OperatingProfit` は V2 の実測に無い。** V1 の欄名かどうか ・V2 との対応は S09 ・S16 を読むまで未確認。別名として使わない（P8-OBS-48） |
| 開示日 | `DiscDate` | 未確認 | run #21 で日付の引数の鍵として使えた（REPO） |
| 開示時刻 | `DiscTime` | 未確認 | 書式 ・time zone ・欠損は未確認 |
| 当期の期間の種類 | `CurPerType` | 未確認 | 値の集合は未確認 |
| 当期の会計年度の初め ／ 終わり | `CurFYSt` ／ `CurFYEn` | 未確認 | 日付の書式 ・両端を含むかは未確認 |
| 当期の期間の初め ／ 終わり | `CurPerSt` ／ `CurPerEn` | 未確認 | 同上 |
| 開示の identity | `DiscNo`（と `Code`） | 未確認 | 一意の範囲 ・安定性は未確認 |
| 書類の種類 | `DocType` | 未確認 | 値の集合 ・連結 ／ 会計基準を含むかは未確認 |
| 連結 ／ 単体の印 | **専用の欄は記録に無い** | 未確認 | 単体の値は `NC` で始まる別の欄として同じ行に併存（REPO の注記）。名前は未記録（P8-OBS-49） |
| 会計基準の印 | **記録に無い** | 未確認 | P8-OBS-50 |
| 遡及修正の印 | `RetroRst` | 未確認 | 本 gate の 2 指標に直接は要らない。訂正（LUV-19）の手掛かりの候補 |

規則: 出所の契約を記録する前に正規化しない。V1 の欄名を V2 の別名にしない。記録された `observed_fields` は網羅ではない
（`NC` の欄が載っていない）ので、schema として使わない。

---

## 5. 売上（`Sales`）の意味

| 問い | 答え |
|---|---|
| Sales ・Revenue ・NetSales ・他の開示の項目のどれか | UNRESOLVED（S01）。legacy の `net_sales` は命名で根拠ではない |
| どの期間の値か | UNRESOLVED（S01 ・S10） |
| 会計年度の初めからの累計か | UNRESOLVED（LUV-05） |
| 会計基準 ・業種で意味が変わるか | UNRESOLVED（S01 ・S02） |
| 単位 | UNRESOLVED（LUV-16） |
| 通貨 | UNRESOLVED（LUV-17） |

---

## 6. 営業利益（`OP`）の意味

| 問い | 答え |
|---|---|
| どの期間の値か ・累計か | UNRESOLVED（LUV-05） |
| 会計基準 ・発行体によって無い ／ 当てはまらないことがあるか | UNRESOLVED（LUV-08） |
| 無い時の表し方 | UNRESOLVED（LUV-18） |
| 単位 ・通貨 | UNRESOLVED（LUV-16 ・17） |

**空欄を 0 にしない。** 無い値は `MISSING`（§16）。当てはまらない（`NOT_APPLICABLE`）とは公式の文書が定めた時だけ言う。

---

## 7. 期間の種類（`CurPerType`）

値の全集合は UNRESOLVED。したがって、下の対応の**値の列はすべて空**で、実データは写さない。

| 目的の期間 | A2 の `PeriodBasis` ／ quarter | `CurPerType` の値 | 状態 |
|---|---|---|---|
| 第 1 四半期の累計 | `CUMULATIVE_YEAR_TO_DATE` ／ 1 | 未確認 | UNRESOLVED |
| 上半期（第 2 四半期）の累計 | `CUMULATIVE_YEAR_TO_DATE` ／ 2 | 未確認 | UNRESOLVED |
| 第 3 四半期の累計 | `CUMULATIVE_YEAR_TO_DATE` ／ 3 | 未確認 | UNRESOLVED |
| 年度 | `FISCAL_YEAR` ／ 0 | 未確認 | UNRESOLVED |
| その他 | 写さない（保留） | — | — |

- **単独の四半期（`SINGLE_QUARTER`）を作らない**: この出所から単独の値を作る規則は無く、累計の引き算もしない。
- 日付の整合は必要条件の検査に使う（十分条件ではない）: 年度は `CurPerSt` ＝ `CurFYSt` かつ `CurPerEn` ＝ `CurFYEn`、累計は
  `CurPerSt` ＝ `CurFYSt` かつ `CurPerEn` ＜ `CurFYEn`。値の種類と日付が合わなければ保留。
- 値の種類を日付だけから決めない（公式の値の意味が要る）。

---

## 8. 期間の境界

| 欄 | 実測 | 意味 | A2 の `ReportingPeriod` |
|---|---|---|---|
| `CurFYSt` ／ `CurFYEn` | あり | UNRESOLVED | `fiscal_year_start` ／ `fiscal_year_end`（両端を含む） |
| `CurPerSt` ／ `CurPerEn` | あり | UNRESOLVED | `period_start` ／ `period_end`（両端を含む） |

売上成長率は、互換な期間どうしだけを比べる。次は黙って比べない（`NOT_COMPARABLE` として止める）:

- 期間の種類が違う（例: 第 1 四半期の累計と年度）。
- 期間の長さが違う（決算期の変更で会計年度が 12 か月でない場合を含む。A2 は 550 日まで受けるが、比べられるかは別）。
- 期間の種類 ・長さのどちらかが不明。

---

## 9. 連結 ／ 単体

- 実測（REPO の注記）: 単体の値は `NC` で始まる別の欄として同じ行に併存する。欄名は記録されていない。
- 接頭辞の無い欄 ＝ 連結は LEGACY_INFERENCE（既存の comment）。連結の無い発行体で接頭辞の無い欄が何を持つかは UNRESOLVED。
- 同じ発行体 ・期間に 2 つの基準が別の行で来ることがあるかは UNRESOLVED。
- 規則: 指標の identity に `StatementBasis` を含める。**優先順位を作らない**（連結が無い時に単体へ落とさない）。

---

## 10. 会計基準

- 明示の欄は記録に無い。`DocType` が会計基準を含むかは UNRESOLVED（P8-V の手掛かりは使わない）。
- 基準が違う値の比較可能性を仮定しない。将来の A3 の制約:
  - 比べる 2 つの観測で会計基準が同じと確かめられる時だけ比べる。どちらかが不明 → `NOT_COMPARABLE`。
  - 期間の間で基準が変わった → `NOT_COMPARABLE`（組み替えない）。
  - 営業利益が基準によって無い場合（LUV-08）は `MISSING` のまま伝える。
- **A2 の実績の record（`FundamentalActual`）には会計基準の次元が無い**（`statement_basis` だけ）。互換の会計基準を A3 で検査するには、
  会計基準を示す出所（未確認）と、その保持の場所（A2 の拡張か別の record）が要る。A2 は凍結なので変えない（P8-OBS-50。監督の判断）。

---

## 11. 開示の知識の時刻

| 源 | 実測 | 意味 ・time zone ・欠損 | A2 の `KnowledgeTime` | 状態 |
|---|---|---|---|---|
| `DiscDate` | あり | 意味 UNRESOLVED（実の公表日か） | 最大で `DATE(DiscDate)` | UNRESOLVED（P8-OBS-51） |
| `DiscTime` | あり | すべて UNRESOLVED | **使わない**（`TIMESTAMP` を作らない） | BLOCKED |
| 取得の時刻（system） | — | 本 system が取得した時刻（UTC） | `TIMESTAMP`（前向きの取得の知識） | SAFE_WITH_RESTRICTIONS（取得より前の cutoff には使えない） |

- 一定の時刻（15:30 等）・合成の日中の時刻を作らない。
- `DATE(DiscDate)` は、DiscDate が実の公表日より早くないと確かめた時だけ過去の cutoff に使う。確かめる前は、前向きに取った値に
  取得の時刻を付ける（P8-OBS-17 ・51）。
- `DATE` 精度の日の途中の cutoff は A2 が `INSUFFICIENT_TIME_PRECISION` を返す（構造で検証済み）。

---

## 12. 出所の record の identity

- `DiscNo` は実測にある。意味 ・一意の範囲 ・安定性は UNRESOLVED（LUV-20）。
- **「訂正 ＝ 新しい DiscNo」と仮定しない。**
- A2.5 §25 の参照の形（`jq.<dataset>:<自然 key>:<digest の先頭 24 hex>`）を引き継ぐ（A2.5 は書き換えない）。digest は取った行の
  identity として安全だが、開示の identity にするには LUV-20 の確認が要る。自然 key が A2 の参照の形に合わない値は保留。

---

## 13. 訂正 ／ 改訂

| 事象 | 公式 | 扱い |
|---|---|---|
| 財務の訂正開示 | UNRESOLVED（LUV-19） | 別の開示なら A2 の revision（`supersedes`） |
| 予想の修正 | 本 gate の 2 指標は実績だけなので対象外 | 予想は写さない |
| 過去の応答が後で変わる | UNRESOLVED | **変わり得るものとして設計する。** 取った authority を上書きしない。同じ自然 key ・違う digest は業者の改訂として新しい revision（知識 ＝ 取得の時刻）＋ 印 |
| `RetroRst` | UNRESOLVED | A2 は報告どおりの値だけを持つ |

SV-04（B）は元の data が改訂に敏感なことの文脈で、A の挙動の根拠にしない。

---

## 14. 単位 ・桁

- UNRESOLVED（LUV-16）。**円 ・千円 ・百万円を暗黙に仮定しない。**
- A2 は金額（`MONETARY_AMOUNT`）に明示の `Scale`（`ONE` ／ `THOUSAND` ／ `MILLION`）を要求する → 確認の前は adapter が金額を書けない。
- 比の指標は数学的には桁が消えるが、2 つの値が同じ桁と記録された時だけ比べる。桁が違う ・不明 → `NOT_COMPARABLE`。出所の意味は
  桁が消える場合も正しく記録する。

---

## 15. 通貨

| 可能性 | 状態 |
|---|---|
| 固定（すべて円） | UNRESOLVED |
| 欄ごとに違う | UNRESOLVED |
| 発行体の報告の通貨 | UNRESOLVED |
| 明示されない | UNRESOLVED |

- A2 は JPY だけを表せる。出所が通貨を示さないなら、JPY を付けること自体が仮定になる。
- **LUV-17 を確かめるまで、実データの売上成長率は BLOCKED**（期間の間で通貨の基準が同じと言えない）。

---

## 16. 欠損

出所の表現（transport）と業務の意味を分ける。公式の意味は未読なので、写しは保守の側に倒す。

| 出所の表現 | 公式の意味 | A2 の写し（保守） |
|---|---|---|
| 数の token（`0` を含む） | UNRESOLVED（数か文字列かも未確認） | `VALUE_PRESENT`。**0 は値** |
| null | UNRESOLVED | `MISSING` |
| 空文字 | UNRESOLVED | `MISSING` |
| schema にある欄の key が行に無い | UNRESOLVED | `MISSING` ＋ schema のずれの印 |
| 数でない印（例 `-`） | UNRESOLVED | 保留（`MISSING` にも 0 にもしない） |

- 公式の文書が区別を定めるまで、`NOT_APPLICABLE` ・`NOT_REPORTED` を作らない。空 → 0 の推測は禁止。
- legacy の parser は null ・key なし ・空文字を潰す（P8-OBS-26）→ 将来の adapter は取った本文から読む。

---

## 17. 現在の Light の entitlement

| 区別 | 証拠 | 状態 |
|---|---|---|
| endpoint がある | REPO: 2026-09-01 に Light の口座で `/fins/summary` が 200（code 指定 20 行）、2026-09-02 に日付指定 14 行 | 日付つきの実測（仕様の根拠ではない） |
| Light plan が使える（現在の公式） | S08 未読 | **PLAN_UNRESOLVED** |
| 過去の plan の資料 | SV-02: 財務情報が Light に含まれると案内されていた | 過去の事実。2026 年の現在の entitlement にしない |

---

## 18. 履歴の深さ

- 現在の Light の財務情報の深さ: **PLAN_UNRESOLVED**（S08 未読）。
- SV-02 の 5 年は過去の案内で、現在の entitlement として使わない。
- REPO: code ごとの件数（20〜31 行）は深さを示さない（最古の開示日は記録されていない）。
- 帰結: 前年同期と比べる売上成長率には、少なくとも 1 会計年度前の互換な観測が要る。過去の screen にはさらに深さが要る（LUV-21）。

---

## 19. 最小の A2 の写し

実データの adapter の code は無い。Issuer への解決は A1 ／ A1R の authority（実の登録は未実施）を通す。

| 出所の欄 | A2 の主語 | A2 の class | A2 の measure | 期間の意味 | 値の意味 | 単位 | 通貨 | known_at の精度 | source_record_ref | 状態 |
|---|---|---|---|---|---|---|---|---|---|---|
| `Sales` | Issuer（`Code` → Security → Issuer） | `FUNDAMENTAL_ACTUAL` | `REVENUE` ／ `MONETARY_AMOUNT` | `CurPerType` と 4 つの日付から（UNRESOLVED） | UNRESOLVED | UNRESOLVED（明示の `Scale` が要る） | UNRESOLVED（A2 は JPY だけ） | 最大 `DATE(DiscDate)`、確認の前は取得の時刻 | `jq.fins_summary:<DiscNo>:<digest>` | **UNRESOLVED** |
| `OP` | 同上 | `FUNDAMENTAL_ACTUAL` | `OPERATING_INCOME` ／ `MONETARY_AMOUNT` | 同上 | UNRESOLVED（有無も） | 同上 | 同上 | 同上 | 同上 | **UNRESOLVED** |
| `DiscDate` | — | 知識の時刻 | — | — | 公表日か UNRESOLVED | — | — | `DATE` | — | UNRESOLVED |
| `DiscTime` | — | 写さない | — | — | UNRESOLVED | — | — | — | — | BLOCKED |
| `CurPerType` ・`CurFYSt` ・`CurFYEn` ・`CurPerSt` ・`CurPerEn` | — | `ReportingPeriod` | — | §7 ・§8 | — | — | — | — | — | UNRESOLVED |
| `DiscNo` | — | 出所の参照の自然 key | — | — | UNRESOLVED | — | — | — | 上の参照の一部 | UNRESOLVED |
| 接頭辞なし ／ `NC` の欄 | — | `StatementBasis` | — | — | UNRESOLVED | — | — | — | — | UNRESOLVED |
| `DocType` | — | 写さない（class を決めない） | — | — | UNRESOLVED | — | — | — | — | UNRESOLVED |
| 取得の時刻（system） | — | 知識の時刻 | — | — | — | — | — | `TIMESTAMP`（前向きだけ） | — | SAFE_WITH_RESTRICTIONS |

出所の class は `JQUANTS`（A2 の `FUNDAMENTAL_ACTUAL` で許可）、出所の欄は実測の綴り（`Sales` ・`OP`）。SAFE は 0 件。

---

## 20. 売上成長率の準備度

売上成長率 ＝ 互換な売上の観測 ／ 前の互換な売上の観測（式の実装は決めない）。実データの最小の契約:

| 条件 | A2 で表せるか | 実データで要る確認 |
|---|---|---|
| 同じ Issuer | 主語（A1 ／ A1R） | 実の identity の登録（本 gate の外。LUV-25 ・26） |
| 同じ期間の種類 | `PeriodBasis` ＋ quarter | LUV-04 ・05 |
| 同じ期間の長さ ・基準 | `ReportingPeriod` の日付 | LUV-04 ・05、境界の意味（S01） |
| 同じ連結の基準 | `StatementBasis` | LUV-06 |
| 互換な会計基準 | **表せない**（P8-OBS-50） | LUV-06 ＋ 保持の場所の判断 |
| 互換な通貨の基準 | JPY だけ | LUV-17 |
| 同じ桁と記録 | `Scale` | LUV-16 |
| 実績と実績 | `FUNDAMENTAL_ACTUAL` どうし | 実績 ／ 予想の欄の区別（欄名の完全一致） |
| cutoff で知り得た | `KnowledgeTime` と revision | LUV-01〜03 ・19 ・20 |

分類: **READY_FOR_A3_SEMANTICS**（上の条件で合成 data の意味論を作れる）。READY_FOR_REAL_MAPPING ではない（LUV-01〜07 ・16 ・17 ・19 ・20 ・
22 と会計基準の次元が未確定）。

---

## 21. 営業利益率の準備度

営業利益率 ＝ 営業利益 ／ 売上（式の実装は決めない）。実データの最小の契約:

| 条件 | A2 で表せるか | 実データで要る確認 |
|---|---|---|
| 同じ Issuer | 主語 | 実の identity の登録 |
| 同じ報告の期間 | 同じ `ReportingPeriod` | LUV-04 ・05 |
| 同じ連結の基準 | `StatementBasis` | LUV-06 |
| 互換な会計基準 | **表せない**（P8-OBS-50） | LUV-06 |
| 同じ通貨 ・桁 | JPY ・`Scale` | LUV-16 ・17 |
| 両方が実績 | `FUNDAMENTAL_ACTUAL` | — |
| 両方が cutoff で知り得た | `KnowledgeTime` | LUV-01〜03 |
| 営業利益の有無 | `MISSING` の伝播（0 にしない） | LUV-08 ・18 |
| 片方だけ訂正された組を作らない | revision の知識の時刻 | LUV-19 ・20（組の規則は A3 で決める） |

分類: **READY_FOR_A3_SEMANTICS**。READY_FOR_REAL_MAPPING ではない（売上成長率の穴 ＋ LUV-08）。

---

## 22. pilot の判断

**NO_PILOT_REQUIRED（本 gate の判断）。**

- 監督指示 §22 の規則: pilot は、公開の公式の文書では解けない時だけ要る。本 gate は文書を読めなかったので、「解けない」ことを示して
  いない。**文書を読めないことを pilot の理由にしない。**
- 次の gate で文書を読んだ後、残った穴についてだけ再判断する。見込み:
  - pilot で確かめ得る: 実際の応答の欠損の表現（LUV-18）・数の token の型 ・現在の口座で使えるか（LUV-22 の口座の側）。
  - pilot では確かめられない: 値の全集合（LUV-04）・訂正の一般の挙動（LUV-19）・DiscNo の安定性（LUV-20）・plan の深さの約束（LUV-21）。
    1 回の観測は「ある」は示せても「常に」「すべて」は示せない。

---

## 23. pilot の設計

本 gate では不要（§22）。再判断で要るとなった時の制約だけを先に定める（実行しない）:

- read-only。raw の本文は、別に認可されない限り保存しない。secret を log ・出力 ・文書に出さない。
- endpoint は `/fins/summary` だけ、呼び出しは最小（目安 1〜2 回）。顧客 ・portfolio の data を使わない。公開の artifact を作らない。
- 見るのは schema と意味（欄名 ・型 ・欠損の表現 ・行の数）だけで、値を記録しない。対象の発行体は監督が決める。
- 各観測について「示せる事 ／ 示せない事」を先に書き、§22 の区別に従って結論を限る。

---

## 24. 規約

S14 ・S15 は開けていない。保存 ・cache ・派生の data ・公開について、本書は何も記録しない（法的な結論も出さない）。
**`INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED` のまま**（P8-OBS-32 ・36 ・41）。Pro の license（SV-08）を当てない。

---

## 25. A1R の境界

- A1R は `e6a750f` で凍結。財務の欄の結果で変えない。本 gate は A1R の runtime ・test ・文書に触れていない。
- 実の identity の bootstrap は無い。LUV-21 ・25 ・26 は将来の bootstrap に効くが、本 gate の runtime には関わらない（runtime は無い）。

---

## 26. 所見の登録

先行の文書は書き換えない。本 gate に関わる引き継ぎの所見の状態（P8-V ／ P8-VR の処分のまま）:

| id | 所見 | 状態 |
|---|---|---|
| P8-OBS-17 | 真の公表時刻 | ADAPTER_REQUIRED のまま（§11） |
| P8-OBS-22 | 財務の期間の意味 | STILL_UNRESOLVED のまま（§7 ・§8） |
| P8-OBS-26 | legacy の parser が欠損の表現を潰す | ADAPTER_REQUIRED のまま（§16） |
| P8-OBS-32 ・36 ・41 | 規約と保存 ・公開 | INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED のまま（§24） |
| P8-OBS-33 | 履歴の深さ | STILL_UNRESOLVED のまま（§18） |
| P8-OBS-35 | 公式の host が環境で拒否 | STILL_UNRESOLVED（2026-09-28 に再確認） |
| P8-OBS-42〜47 | A1R の所見 | A1R の付録のまま |

新しい所見（P8-OBS-48 から）:

| id | 所見 | 分類 |
|---|---|---|
| P8-OBS-48 | 指示の欄名 `OperatingProfit` は V2 の実測の欄に無い（実測は `OP`）。V1 と V2 の欄名の対応は未確認 | UNRESOLVED（S09 ・S16）。実測か公式の V2 の綴りだけを使い、V1 の名を別名にしない |
| P8-OBS-49 | 記録された `observed_fields` は網羅ではない（単体の `NC` の欄の名前が無い） | UNRESOLVED（S01）。記録を schema として使わない |
| P8-OBS-50 | 会計基準を示す欄が記録に無く、A2 の実績の record にも会計基準の次元が無い | UNRESOLVED ＋ 設計の問い（A2 の拡張か別の保持か。監督の判断。A2 は変えない） |
| P8-OBS-51 | `DATE(DiscDate)` を過去の cutoff の知識に使うには、DiscDate が実の公表日より早くないことの確認が要る | UNRESOLVED（S01）。確認の前は取得の時刻 |

---

## 27. 公式の文書で確かめる事（次の gate の checklist）

公式の host を許可した環境で読むか、監督が該当の抜粋を渡す時に、次をそのまま答える。

| page | 確かめる事 |
|---|---|
| S01 | 応答の欄の一覧と説明の全文（`Sales` ・`OP` ・`DiscDate` ・`DiscTime` ・`DiscNo` ・`DocType` ・`CurPerType` ・4 つの日付 ・`NC` の欄 ・`RetroRst`）、型、`CurPerType` の値の全集合、DiscTime の time zone と欠損、単位 ・通貨の注記、訂正開示の注記 |
| S02 | `DocType` の値の全集合と、連結 ／ 単体 ・会計基準 ・訂正 ・予想の修正の区別 |
| S07 | 財務情報の更新の時刻（開示の時刻とは別であること） |
| S08 | 現在の Light で `/fins/summary` が使えるか、財務情報の格納期間 |
| S09 | V1 の欄名と V2 の欄名の対応（`OperatingProfit` と `OP` を含む） |
| S10 | 累計 ／ 単独、単位 ・桁、通貨、空欄 ・null の意味 |
| S14 ・S15 | 保存 ・cache ・派生の data ・公開の条項（法的な結論は出さない） |

---

## 28. 次の gate の推奨

```
P8-LV1（本 gate: PARTIAL）
  → 公式の文書へのアクセス（どちらか）
      a. 環境の network の設定で `jpx-jquants.com`（必要なら `jpx.gitbook.io`）を許可し、本 gate の範囲で確認をやり直す（P8-LV1R）
      b. 監督が §27 の checklist の該当の抜粋を確かめて渡す（SV と同じ扱い）
  → 残った穴だけで pilot を再判断（§22）
  → A3: 売上成長率 ・営業利益率（確かめた欄だけを実データに写す）
```

- A3 の合成 data の意味論（READY_FOR_A3_SEMANTICS）は LUV に依らずに設計できる。先に進めるかは監督の判断（本 gate では行わない）。
- 会計基準の次元（P8-OBS-50）は、A3 の前に監督が扱いを決める必要がある。

---

## 29. 検証と凍結の確認

### 29.1 本 gate の変更

- `docs/databank/PHASE8_JQUANTS_LIGHT_MINIMUM_FIELD_CONTRACT.md`【新規】（本書）
- `CHANGELOG.md`（v5.57）
- `tests/intelligence/phase8_runtime_registry.py`: `PHASE8_DOCS` に本書、P8-A1R の凍結の anchor `P8_A1R`
- `tests/intelligence/test_screener_intelligence_boundary.py`: 本書の登録と、runtime ・Phase 8 の test ・先行の文書が `P8_A1R` と byte 一致する guard
- runtime ・config.yaml ・workflow ・Pages ・Phase 6 ／ 7 の test ・A1 ／ A2 ／ A1R の module と test ・先行の文書は無変更

### 29.2 実行した検証

監督指示 §29 の順の結果は最終報告に記す（Phase 8 の guard ・A1R ・A1 ・A2 ・Phase 7 の凍結 ・Phase 6 の凍結 ・full pytest。基準
5345 passed ／ 2 skipped）。

### 29.3 凍結

runtime（10 module）・A1 ／ A2 ／ A1R の test ・先行の Phase 8 の文書 7 本は `e6a750f` と byte 一致。Phase 6 ／ 7 は無変更。

---

## 30. 最終の判定

**P8_LV1_PARTIAL / OFFICIAL_DOCUMENT_ACCESS_REQUIRED**

A3 ・認証つきの pilot ・adapter ・実データの取り込み ・実の identity の登録 ・screen ／ ranking は行っていない。
