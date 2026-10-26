# PHASE 8 / P8-A2 — PIT MARKET ／ FUNDAMENTAL OBSERVATION CONTRACT

Phase 8 の PIT（point-in-time）観測の基盤の契約。観測の意味論だけを実装した。合成 data だけで検証した。派生指標 ・screen ・
順位 ・score ・Theme exposure ・実 J-Quants の取り込み ・corporate action の調整は無い。

- runtime: `src/intelligence/screener_intelligence/`（`observation_model` ・`observation_store` ・`observation_resolver`。A1 の
  identity の module は `4162e9c` と byte 一致のまま）
- test: `tests/intelligence/test_screener_observation.py`（A〜BX ・CM〜CP）・`tests/intelligence/test_screener_intelligence_boundary.py`
  （BY〜CL を追加）・`tests/intelligence/phase8_runtime_registry.py`（A2 の path を登録）
- 基準: P8-A1 `4162e9c`、P8-A0 `76ebf0c`、Phase 7 `c1e95d3`、Phase 6 `5ef313a`。

---

## 1. 目的

「どの Security ／ Issuer の、どの市場の日 ／ 会計の期間について、どの出所から、どの値が観測され、それはいつ知り得たか」に
答える。「良い会社か ・割安か ・screen を通るか ・Theme の受益か ・買うべきか」には答えない。A3 の派生指標はこの観測だけを
入力にする。

## 2. authority

| 対象 | class |
|---|---|
| 観測の record（市場 ・実績 ・予想）と coverage の宣言 | `AUTHORITATIVE_OBSERVATION_RECORD`（追記専用） |
| `ObservationResolution` | `DERIVED_NON_AUTHORITY_NON_PERSISTENT`（record ではない。store に書けない） |

A2 に派生指標の authority は無い。screen の結果は存在しない。

## 3. 観測の class

| class | Python の型 | 主語 | 何か |
|---|---|---|---|
| `MARKET_OBSERVATION` | `MarketObservation` | Security | 日次の四本値 ・出来高（生値 ／ 業者の調整値） |
| `FUNDAMENTAL_ACTUAL` | `FundamentalActual` | Issuer（財務諸表）／ Security（発行済株式数） | 報告された実績 |
| `FUNDAMENTAL_FORECAST` | `FundamentalForecast` | Issuer | 会社予想 |

型 ・`record_kind` ・slot がすべて別で、互いに化けない（予想は実績の問い合わせに返らない。予想にできない欄は
`NOT_FORECASTABLE`）。`CORPORATE_ACTION_INPUT` と `REFERENCE_OBSERVATION`（業種 ・市場区分などの参照の観測）は A2 の
不変条件に要らないので延期した（§26 ・所見）。

## 4. 主語

- 主語は A1 の `SecurityId` ／ `IssuerId` で、明示する。観測から identity を作らない ・推測しない。
- 市場の観測は Security だけ。財務諸表の値（売上 ・利益 ・EPS ・純資産 ・総資産 ・営業 CF）は Issuer。発行済株式数は
  上場物の値なので Security。
- Issuer の値を Security の値に黙って変えない。同じ経済的事実を Issuer の全 Security に複製しない。

## 5. 市場の欄

`OPEN` ・`HIGH` ・`LOW` ・`CLOSE`（量 `PRICE`、通貨 JPY、桁 ONE、正の値）と `VOLUME`（量 `TRADED_VOLUME`、通貨なし、
0 以上）。technical な指標 ・return ・変動率 ・時価総額は計算しない（A3）。日中の足は範囲外。

## 6. 生値と調整値

- `PriceBasis`: `RAW_REPORTED`（配られた生値）／ `PROVIDER_ADJUSTED`（業者が計算した調整値）。基準は slot の一部で、
  2 つは別の鎖になる。調整値は生値を置き換えない（調整値で生値の record を supersede すると `PREDECESSOR_WRONG_SLOT`）。
- 調整値は計算の参照（`adjustment_ref`。業者の計算の版 ／ 出所の record の identity）を必須にし、生値は参照を持てない
  （`ADJUSTMENT_REF_RULE`）。調整値の出所は J-Quants だけ。
- 後の調整（分割の後の再計算）は、業者が公表した時刻を知識の時刻に持つ新しい revision。古い調整値の record は書き換え
  ない。それより前の cutoff では古い調整値が返る（test P）。A2 は調整を自分で計算しない。

## 7. 市場の時間

- `session_date`: 取引日（東京の暦日。datetime を拒む）。
- 知識の時刻は取引日の始まり（東京）より前であってはならない（`KNOWN_BEFORE_SESSION`）。
- 取引日の引けの時刻を作らない。出所が日付しか持たなければ DATE の精度で持ち、その日の途中の cutoff には答えない
  （§12）。

## 8. 財務の実績

`REVENUE` ・`OPERATING_INCOME` ・`NET_INCOME` ・`EPS` ・`EQUITY` ・`TOTAL_ASSETS` ・`OPERATING_CASH_FLOW` ・`SHARES_OUTSTANDING`。
比率（ROE ・PER ・PBR 等）・利益率 ・成長率 ・TTM は作らない。実績は期間の末日の翌日（東京）より前に知り得ない
（`ACTUAL_KNOWN_BEFORE_PERIOD_END`）。連結 ／ 単体（`StatementBasis`）は slot の一部。

## 9. 会社予想

- 別の class。欄は `REVENUE` ・`OPERATING_INCOME` ・`NET_INCOME` ・`EPS` だけ。対象の期間（`target_period`）と知識の時刻を持つ。
- 期間の前に知り得てよい。予想の修正は同じ鎖の revision。
- 後の実績は予想の履歴を書き換えない: 予想 F1（T1）→ 修正 F2（T2）→ 実績 A（T3）はそれぞれ別の不変の record で、
  予想の問い合わせは T3 の後も F2 を返し、実績の問い合わせは T3 より前は NOT_FOUND（test AA〜AC）。

## 10. 期間

`ReportingPeriod{basis, fiscal_year_start, fiscal_year_end, period_start, period_end, quarter}`（日付は両端を含む）。

| basis | 規則 |
|---|---|
| `FISCAL_YEAR` | 期間 ＝ 会計年度、quarter 0 |
| `CUMULATIVE_YEAR_TO_DATE` | 年度の始まりから、quarter 1〜3、年度の終わりより前 |
| `SINGLE_QUARTER` | 年度の中の 1 四半期、quarter 1〜4 |

年度は 550 日以内。TTM ・年率換算の基準は無く、四半期を合算しない（test AG）。

## 11. 知識の時刻（known_at）

すべての観測は `KnowledgeTime` を持つ。出所が正確な開示時刻を持つなら TIMESTAMP（aware。秒まで保つ）、開示日しか
無ければ DATE。**既定の公表時刻（15:30 等）を持たない**。これは P8-OBS-1（開示時刻の無視）を model の上で閉じる形で、
実データの adapter が DiscDate ＋ DiscTime を正しく対応付けるまで所見は閉じない。

## 12. 知識の精度

| 精度 | 知り得た最初の瞬間 | 確かに知られている瞬間 |
|---|---|---|
| TIMESTAMP | その時刻 | その時刻 |
| DATE | その日の 0 時（東京） | 翌日の 0 時（東京） |

cutoff での状態: 確かに知られている → KNOWN、最初の瞬間より前 → UNKNOWN、その間 → UNCERTAIN。日付だけの知識を
0 時 ・開場 ・引けとみなさない。UNCERTAIN が答えを変え得るとき、解決は `INSUFFICIENT_TIME_PRECISION`（test AJ ・AK）。

## 13. 訂正 ／ 修正

- 古い record を書き換えない。訂正 ／ 修正は `supersedes` で前の record を指す新しい record。
- slot（class ・主語 ・欄 ・基準 ・日 ／ 期間 ・出所）ごとに一本の鎖: 2 本目の root ・末尾でない前を指す revision は `FORK`、
  別の slot は `PREDECESSOR_WRONG_SLOT`、未知の前は `UNKNOWN_PREDECESSOR`、前より早く知られた revision は
  `NON_MONOTONIC_KNOWLEDGE`。
- 修正の前の cutoff は古い値、修正を知った後は新しい値。結果は鎖の系譜（`lineage`）を返す。

## 14. 値の model

`ObservationValue{state, measure, amount, currency, scale}`。

- `amount` は 10 進の正準の文字列（指数なし ・末尾の 0 なし ・0 は "0"）。float ・bool ・非有限 ・指数の表記を拒む。
  整数部 20 桁 ・小数部 10 桁まで。同じ数は同じ文字列 ・同じ record id（test AO）。
- 量の種類（`PRICE` ・`TRADED_VOLUME` ・`MONETARY_AMOUNT` ・`PER_SHARE_AMOUNT` ・`SHARE_COUNT`）は欄で決まり、違えば
  `MEASURE_MISMATCH`。
- 通貨は金額 ・1 株あたり ・価格で JPY 必須、数量では持てない。桁の単位（ONE ・THOUSAND ・MILLION）は明示し、価格と
  1 株あたりは ONE だけ。A2 は桁を換算しない。
- 符号: 価格は正、出来高 ・株数は 0 以上、金額 ・1 株あたりは任意。

## 15. 欠損の意味

| 状態 | 意味 | amount |
|---|---|---|
| `VALUE_PRESENT` | 値がある（0 も値） | 数 |
| `MISSING` | 出所の record に値が無い | なし |
| `NOT_REPORTED` | 発行体がその期に開示していない | なし |
| `NOT_APPLICABLE` | 概念が当てはまらない | なし |

欠損を 0 にしない。record が無いこと（NOT_FOUND）とも区別する。出所に無い欄の観測を作らない（adapter の責務）。

## 16. 出所

`ObservationProvenance{source_class, source_record_ref, source_field, adjustment_ref}`。参照は `/` ・`\` ・空白 ・`=` を含めない
160 文字以内の token、欄は 32 文字以内の token。認証情報に見える語を拒む。raw の API 応答 ・本文 ・machine の path ・
credential を持たない。

## 17. 出所の互換

| 観測 | 認める出所 |
|---|---|
| 市場（生値） | J-Quants ・取引所 |
| 市場（業者の調整値） | J-Quants |
| 財務の実績 | 発行体の開示 ・J-Quants ・人の審査（訂正） |
| 会社予想 | 発行体の開示 ・J-Quants（人が予想を作らない） |
| coverage の宣言 | J-Quants ・取引所 ・人の審査 |

違えば `SOURCE_NOT_COMPATIBLE`。出所の優先順位の heuristic は持たない（出所ごとに別の鎖。§19 の AMBIGUOUS）。

## 18. identity との統合

- append ／ load: 主語は同じ data_root の A1 の authority に登録済みでなければならない（`UNKNOWN_SUBJECT`）。A1 は
  read-only で読み、書かない。A1 が無ければ `IDENTITY_AUTHORITY_MISSING`、壊れていれば `IDENTITY_STORE_CORRUPTION`。
- 解決: 主語を A1 で PIT に解決する。市場の観測は、取引日の終わり（と cutoff の早い方）で Security が `FOUND`（上場中）で
  なければならない。財務は Issuer ／ Security が `FOUND` か `NOT_ACTIVE_AT_CUTOFF`（廃止後も過去の財務は有効）。できなければ
  `SUBJECT_NOT_RESOLVED`（A1 の status を結果に残す）。
- A1 の store ／ resolver の API を使う module は指名した 2 つだけ（`observation_store` は `open_identity_history` と例外 2 つ、
  `observation_resolver` は `IdentityQuery` ・`ResolutionStatus` ・`resolve`）。完全一致の名前で guard が固定する。

## 19. PIT の解決

`resolve(history, query, *, cutoff)` ／ `resolve_at_data_root(data_root, query, *, cutoff)`。

- 入力: class ・主語 ・欄 ・基準 ・日 ／ 期間（すべて明示）・aware な cutoff（keyword 必須。既定なし）・任意の出所。
- 手順: 主語（§18）→ coverage（§20）→ slot の鎖ごとに cutoff で確かに知られた最後の record → その次が UNCERTAIN なら
  `INSUFFICIENT_TIME_PRECISION` → 出所の違う鎖が 2 つ以上あれば `AMBIGUOUS`（候補を返し、選ばない）。
- 知識の時刻で先に絞ってから選ぶ。後の revision は過去へ漏れない。cutoff より後に知り得た record を足しても過去の結果は
  byte 一致（test S ・BI）。

## 20. coverage

`ObservationCoverage{dataset ∈ {MARKET_DAILY, FUNDAMENTAL_DISCLOSURE}, data_from, data_to, complete_through}`: data の日
（取引日 ／ 期間の末日）`[data_from, data_to)` について、知り得た時刻が `complete_through` 以前の観測はすべて store にある、と
いう取り込みの宣言。

| 状況 | status |
|---|---|
| data の日を覆い、`complete_through >= cutoff` | 解決を続ける（FOUND ／ NOT_FOUND …） |
| 覆うが、取り込みが cutoff に届かない | `NOT_YET_KNOWN` |
| すべての宣言の始まりより前 | `BEFORE_COVERAGE` |
| 宣言が無い ・後 ・隙間 | `OUTSIDE_COVERAGE` |

- 宣言は store の metadata で、世界の事実ではない（cutoff で隠さない）。宣言を足すと fail closed の答えが確かな答えに
  変わり得るが、確かな答えは変わらない: 宣言した範囲の中へ `complete_through` 以前に知り得た観測を後から足すと
  `COVERAGE_CONTRADICTION`。
- 過去の coverage を作らない。現在の J-Quants Light で取れることを、手元に保存した authority と取り違えない。

## 21. status

| status | 意味 |
|---|---|
| `FOUND` | 観測がある（値の状態は MISSING などもあり得る） |
| `NOT_FOUND` | coverage の中で、cutoff で知り得た観測が無い |
| `NOT_YET_KNOWN` | 取り込みが cutoff に届いていない |
| `AMBIGUOUS` | 出所の違う観測が 2 つ以上（出所を明示すれば絞れる） |
| `INSUFFICIENT_TIME_PRECISION` | 日付だけの知識が cutoff を跨ぐ |
| `BEFORE_COVERAGE` ／ `OUTSIDE_COVERAGE` | §20 |
| `AUTHORITY_MISSING` | 観測 ／ A1 の authority の file が無い |
| `STORE_CORRUPTION` | 観測 ／ A1 の store の検査に失敗（診断は `code:detail:行番号`。path ・行の中身を入れない） |
| `SUBJECT_NOT_RESOLVED` | 主語が cutoff で A1 に解決できない |

入力の誤り（cutoff が無い ・naive ・問い合わせの形が違う ・data_root が無い）は status にせず例外で拒む。

## 22. store

`<data_root>/screener_intelligence/observation_records.jsonl`（1 file）。A1 と同じ規律: 正準の行 ・追記専用 ・fsync ・同じ record は
収束 ・読むたびに全行を検査（符号化 ・切断 ・空行 ・JSON ・未知の field ・版 ・id ・非正準 ・物理的な重複 ・履歴 ・coverage の
矛盾 ・未登録の主語）・fail closed ・修復しない ・外部の変更は byte 長で検知 ・read-only は何も書かない。SQLite ・索引 ・cache は
持たない（既存の J-Quants light store の索引とは無関係。P8-OBS-2 を A2 の authority に持ち込まない）。append の順序は知識の
時刻の順でなくてよい（過去の開示の取り込みを許す）。A1 の authority が無ければ初期化もしない（何も作らない）。

## 23. 決定論

- `record_id = content_id("p8obs", canonical_json({schema_version, record_kind, payload, provenance}))`。path ・mtime ・process ・
  時計 ・乱数を入れない。固定値（test で pin）: 合成の終値の record → `p8obs_4ed814b8923a2d7db3b4447d`。
- 同じ store ・同じ問い合わせ ・同じ cutoff は同じ bytes（別 process ・hash seed を変えても同じ id）。独立の record の append の
  順序は結果を変えない。解決は書き込み 0 byte（観測にも A1 にも）。
- 版: `p8_observation_record:0.1.0` ・`p8_observation_resolver:0.1.0`。

## 24. security

credential ・API key ・顧客 ・portfolio ・machine の path ・機密 PDF ・Compass の本文 ・raw の J-Quants の応答を持たない。test は
架空の anchor と値だけ（実在の銘柄 ・code を使わない）。network に接続しない。

## 25. 除外する入力

Phase 6 の Theme ・Phase 7 の Narrative ・exposure ・P5 ・Production DNA ・Compass ／ corpus ／ formal review ・legacy の watchlist ・
J-Quants の transport ／ client ・既存の J-Quants light store ・provider ・公開 ／ 通知 ・portfolio ／ 売買。import の guard で固定する。

## 26. A3 への引き継ぎ

- A3 の派生指標は、明示の cutoff での `ObservationResolution` だけを入力にする。値の状態が VALUE_PRESENT でなければ
  派生しない（欠損を 0 にしない）。量の種類 ・通貨 ・桁の単位をそろえるのは A3 の式の責務（A2 は換算しない）。
- 生値と調整値を混ぜない。調整を要する指標は業者の調整値の鎖を明示で使うか、A3 以後の corporate action の gate を待つ。
- 実績と予想を混ぜない。予想を使う指標は予想の class を明示する（D-P8-A0-11）。
- 時価総額に要る株数（`SHARES_OUTSTANDING`）の意味（自己株の扱い ・対象の株式）は実データで確かめる（所見）。
- 業種 ・市場区分などの参照の観測と corporate action の入力は A2 に無い（A3 ／ 後の gate）。

## 27. 引き継ぐ所見

| id | 所見 | A2 での状態 | 分類 |
|---|---|---|---|
| P8-OBS-1 | 財務の既知の時刻が開示時刻を無視 | model は開示時刻（TIMESTAMP）と日付だけ（DATE）を区別し、既定の時刻を持たない | MANDATORY_BEFORE_DEPENDENT_GATE（実データの adapter で対応付けを確かめるまで閉じない） |
| P8-OBS-9 | 調整後価格の遡及 | 生値 ／ 調整値は別の鎖、調整値は計算の参照 ・公表の時刻を持つ revision | MANDATORY_BEFORE_DEPENDENT_GATE（同上） |
| P8-OBS-14 | 市場 segment ／ venue の履歴が未 model | A2 は venue の継続を作らない（参照の観測は延期） | MANDATORY_BEFORE_DEPENDENT_GATE |

その他の P8-OBS-2〜16 は分類を変えずに引き継ぐ。新しい所見 P8-OBS-17〜 は最終報告に記す。

## 28. 凍結の方針

- A1 の runtime（identity の 4 module）と A1 の契約は `4162e9c` と byte 一致（Phase 8 の guard が確かめる）。
- Phase 6 ／ 7 の runtime ・test は変えていない。A2 の登録は `tests/intelligence/phase8_runtime_registry.py`（runtime 3 ・test 1 ・
  文書 1 の完全一致の path）と Phase 8 の guard の更新だけで、Phase 6 ／ 7 の guard は registry を通して自動で読む。
- 未登録の Phase 8 の file（例: 観測の cache の module）を置くと、Phase 6 ／ 7 の凍結 guard 8 件と Phase 8 の guard が落ちることを
  確かめた。
