# PHASE 8 / P8-A3A — DETERMINISTIC FUNDAMENTAL METRICS FOUNDATION（売上成長率 ・営業利益率）

Phase 8 の最初の決定論の財務の指標の層。監督の決定（P8-A2R-IMPL ＝ PASS ／ CLOSED ／ FROZEN `4d3540c`、GO → P8-A3A）に従い、
**売上成長率と営業利益率だけ**を、凍結した A2（観測 ・resolver）と A2R（会計の意味の注記 ・互換の gate）の上に**追加だけ**で置く。
指標の architecture を確立する gate で、screen ・順位 ・推奨 ・他の指標は含まない。

- 基準: P8-A2R-IMPL `4d3540cf209b5fb0a99fc6c5e32ba17c35f21ae8`（凍結）、P8-A2R 再実行 `45a516f`、P8-A2 `b686b00`、P8-A1 `4162e9c`。
  full pytest の基準 5475 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・財務の実の値を載せない。J-Quants の data API への要求は 0 回。LLM は使わない。

---

## 0. 結論

1. 追加した runtime は 2 module: `metric_model`（結果の型 ・status ・理由の語彙）と `fundamental_metrics`（`revenue_growth` ・
   `operating_margin`）。A1 ・A2 ・A1R ・A2R は無変更（凍結の guard で byte 一致を証明）。
2. 指標は **派生 ・非 authority ・非永続**（`DERIVED_NON_AUTHORITY_NON_PERSISTENT`）。record id ・保存 ・時計 ・乱数 ・IO ・float は無い。
3. revision の選択は凍結した A2 の `resolve` だけ（競合する resolver を作らない）。会計の意味の互換は凍結した A2R の
   `decide_compatibility` だけ。注記が無い ・UNKNOWN ・違う → fail closed。
4. **会計基準の変更は revision ではなく意味の不連続**（監督の決定 P8-OBS-57）。JP_GAAP ↔ IFRS ・US_GAAP ・JMIS など基準が違えば
   `NOT_COMPARABLE(ACCOUNTING_STANDARD_DIFFERS)`。橋渡しの authority は存在しない（test で両方向を実証）。
5. 期間の関係は保守的に 2 つだけ: 年度 ↔ 直前の年度、年度の初めからの累計 ↔ 直前の年度の同じ四半期の累計（累計の値は公式に
   DOCUMENTED、A2 の `CUMULATIVE_YEAR_TO_DATE` は構造で「期首から」を保証）。単独の四半期 ・4Q ・5Q ・OtherPeriod ・不規則な長さの
   年度は fail closed。年率化 ・TTM ・補間 ・累計から単独の四半期への変換はしない。
6. 判定: **P8_A3A_FUNDAMENTAL_METRICS_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§13）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `4d3540cf209b5fb0a99fc6c5e32ba17c35f21ae8`（期待どおり。working tree は clean） |
| A1 ／ A2 ／ A2R の凍結 | `4162e9c` ／ `b686b00` ／ `4d3540c` と byte 一致（開始時に確認。A2R の 3 module を含む 13 module） |
| full pytest の基準 | 5475 passed ／ 2 skipped |

---

## 2. authority の種類

| 事項 | 値 |
|---|---|
| 結果 | `MetricResult`（frozen dataclass）。`authority_class = DERIVED_NON_AUTHORITY_NON_PERSISTENT` |
| ではないもの | 推奨 ・score ・順位 ・screen の判定 ・Theme の証拠 ・Production DNA ・watchlist |
| 保存 | 無い（record id ・canonical_line ・store は無い） |
| 入力 | caller が開いた A2 の `ObservationHistory`（読むだけ）、明示の aware な `cutoff`、A2R の注記の lookup（観測の record id → `ObservationSemantics`） |

---

## 3. 支える指標と式

| 指標 | 式 | 脚 |
|---|---|---|
| `REVENUE_GROWTH` | `target の売上 ／ comparison の売上 − 1` | `TARGET`（後の期間）・`COMPARISON`（直前の期間） |
| `OPERATING_MARGIN` | `営業利益 ／ 売上`（同じ期間 ・同じ基準 ・同じ区分） | `REVENUE` ・`OPERATING_INCOME` |

- 値は Decimal（精度 40 で除算）、小数 6 桁に `ROUND_HALF_EVEN` で丸め、A2 と同じ `canonical_decimal` で正準の文字列
  （例 `"0.25"` ・`"-0.2"` ・`"0"` ・`"0.666667"`）。
- 桁（`Scale.ONE` ・`THOUSAND` ・`MILLION`）は正確な 10 進の倍率で揃える（意味の変換ではない）。通貨が違えば `CURRENCY_DIFFERS`。
- 営業利益は A2 の `OPERATING_INCOME` だけ。経常利益（OdP）で代用しない。売上 ＝ 0 → `UNDEFINED(DENOMINATOR_ZERO)`、売上 ＜ 0 →
  `UNDEFINED(DENOMINATOR_NEGATIVE)`。成長率の分母（comparison の売上）も同じ。

---

## 4. 適格の規則（両指標に共通）

| 条件 | 満たさない時 |
|---|---|
| 入力の型（`ObservationHistory` ・issuer id ・`StatementBasis` ・`ReportingPeriod` ・aware な cutoff ・Mapping の注記） | `INVALID_INPUT`（例外にしない。理由つき） |
| 主語は Issuer（財務諸表の値は A2 で Issuer） | `INVALID_SUBJECT` |
| 観測が cutoff で確かに知られている（A2 の `resolve` が `FOUND`） | resolver の status を理由に（`NOT_FOUND` ・`NOT_YET_KNOWN` ・`BEFORE_／OUTSIDE_COVERAGE` ・`AMBIGUOUS` ・`SUBJECT_NOT_RESOLVED` → `INSUFFICIENT_DATA`、`INSUFFICIENT_TIME_PRECISION` → 同名の status） |
| 注記がその観測のもの（`observation_id` ＝ record id、注記の区分 ＝ A2 の観測の `statement_basis`） | `SEMANTICS_MISMATCH`（`INVALID_INPUT`） |
| 注記がある | `SEMANTICS_MISSING`（`INSUFFICIENT_DATA`） |
| 値がある（`VALUE_PRESENT`） | `VALUE_ABSENT`（`INSUFFICIENT_DATA`。MISSING ・NOT_REPORTED ・NOT_APPLICABLE を 0 にしない） |
| 会計基準 ・連結の区分が KNOWN（A2R の gate） | `ACCOUNTING_STANDARD_UNKNOWN` ・`STATEMENT_BASIS_UNKNOWN`（`NOT_COMPARABLE`） |
| 2 つの脚の基準 ・区分が同じ（A2R の gate が `COMPATIBLE`） | `ACCOUNTING_STANDARD_DIFFERS` ・`STATEMENT_BASIS_DIFFERS`（`NOT_COMPARABLE`） |

売上成長率だけ: 同じ発行体（`comparison_issuer_id` を省けば同じ。違えば `SUBJECT_DIFFERS`）、同じ区分（`comparison_statement_basis`
を省けば同じ。違えば `STATEMENT_BASIS_DIFFERS`）。橋渡しはしない。

---

## 5. 期間の規則

| 指標 | 支える組 | label | 拒む |
|---|---|---|---|
| 売上成長率 | 年度（`FISCAL_YEAR`）↔ 直前の年度 | `FISCAL_YEAR` | 隣接しない（`PERIOD_NOT_ADJACENT`: comparison の年度末 ＋ 1 日 ≠ target の年度初）、basis が違う（`PERIOD_BASIS_MISMATCH`） |
| 売上成長率 | 累計（`CUMULATIVE_YEAR_TO_DATE`、quarter 1〜3）↔ 直前の年度の**同じ四半期**の累計 | `CUMULATIVE_YEAR_TO_DATE` ＋ `quarter` | 四半期が違う（`PERIOD_QUARTER_DIFFERS`）、隣接しない |
| 営業利益率 | 同じ期間（年度 ・累計） | 期間の basis のまま | — |
| 両方 | — | — | 単独の四半期（`PERIOD_BASIS_UNSUPPORTED`）、不規則な長さの年度（`FISCAL_YEAR_IRREGULAR`: 年度の日数が 360〜371 の外。決算期の変更の年） |

- 累計の期間の利益率 ・成長率は**累計の期間の値**で、単独の四半期の値ではない（`period_label` が示す。単独の四半期の名前を付けない）。
- 4Q ・5Q ・OtherPeriod は A2 の `CUMULATIVE_YEAR_TO_DATE`（quarter 1〜3）に写らず、A2R-IMPL の HOLD の外なので本層に届かない。届いても
  `SINGLE_QUARTER` ・不規則な年度として fail closed。
- 累計 YoY を支える根拠: `Sales` ・`OP` は期首からの累計（公式の FAQ。A2R 再実行 O7）、A2 の `ReportingPeriod` は累計の期間で
  `period_start == fiscal_year_start` を構造で要求する。同じ四半期 ・隣接する規則的な年度なら、両脚は同じ長さの累計の窓。

---

## 6. PIT ・知識の時刻 ・revision

- cutoff は caller が明示（aware）。`now` ・`latest` の既定は無い。
- 各脚は凍結した A2 の `resolve(history, query, cutoff=)` で解く。cutoff で確かに知られた鎖の先頭の record だけを使い、後の訂正は
  過去の cutoff の結果を変えない（test A: 元の値の cutoff で `0.25`、訂正の後の cutoff で `0.245`、訂正の record を史料に足しても
  元の cutoff の結果は `0.25` のまま）。
- 未来の観測（cutoff より後に知られる）は `NOT_FOUND`（coverage が cutoff まで完全なら）か `NOT_YET_KNOWN`。
- 日付だけの知識（`DATE`）の観測に日の途中の cutoff → A2 の resolver が `INSUFFICIENT_TIME_PRECISION` を返し、本層は同名の status
  で返す。時刻を作らない。
- 本層は `history.chains` ・`coverages` ・`state_at` に触れない（test D で AST 検査）。

---

## 7. 会計基準の不連続（監督の決定 P8-OBS-57）

- 基準の変更は revision ではない。前の基準と後の基準の観測は別の意味の比較の領域に属する。
- JP_GAAP ↔ IFRS ・US_GAAP ・JMIS など、どの組でも自動で橋渡ししない。発行体 ・欄 ・期間 ・Security が同じでも比べない。
- 将来の橋渡しは、別の明示の bridge-evidence の authority ／ gate だけが導入できる。P8-A3A には無い。
- 実装: A2R の `decide_compatibility` が `INCOMPATIBLE(ACCOUNTING_STANDARD_DIFFERS)` → `NOT_COMPARABLE`。test A で JP→IFRS ・IFRS→JP ・
  JP→US の 3 方向を実証。同じ基準（IFRS どうし）なら値が出ることも確かめた。

---

## 8. 結果 ・理由の語彙

| status | 意味 | 主な理由の code |
|---|---|---|
| `VALUE` | 値あり（理由なし） | — |
| `INVALID_INPUT` | 入力の型 ・注記の不一致 | `INVALID_SUBJECT` ・`INVALID_STATEMENT_BASIS` ・`INVALID_PERIOD` ・`INVALID_CUTOFF` ・`INVALID_HISTORY` ・`INVALID_SEMANTICS_LOOKUP` ・`SEMANTICS_MISMATCH` |
| `INSUFFICIENT_TIME_PRECISION` | 日付だけの知識に日の途中の cutoff | `INSUFFICIENT_TIME_PRECISION` |
| `INSUFFICIENT_DATA` | 観測 ・値 ・注記が無い | `SUBJECT_NOT_RESOLVED` ・`BEFORE_COVERAGE` ・`OUTSIDE_COVERAGE` ・`NOT_YET_KNOWN` ・`NOT_FOUND` ・`AMBIGUOUS` ・`VALUE_ABSENT` ・`SEMANTICS_MISSING` |
| `NOT_COMPARABLE` | 意味 ・期間が比べられない | `SUBJECT_DIFFERS` ・`ACCOUNTING_STANDARD_UNKNOWN` ・`STATEMENT_BASIS_UNKNOWN` ・`ACCOUNTING_STANDARD_DIFFERS` ・`STATEMENT_BASIS_DIFFERS` ・`PERIOD_BASIS_UNSUPPORTED` ・`PERIOD_BASIS_MISMATCH` ・`PERIOD_QUARTER_DIFFERS` ・`PERIOD_NOT_ADJACENT` ・`FISCAL_YEAR_IRREGULAR` ・`CURRENCY_DIFFERS` |
| `UNDEFINED` | 数学的に定義できない | `DENOMINATOR_ZERO` ・`DENOMINATOR_NEGATIVE` |

- 理由は `脚:code`（脚は `TARGET` ・`COMPARISON` ・`REVENUE` ・`OPERATING_INCOME` ・`PAIR`）。重複を除き語彙の順（決定論）。
- 複数の理由があれば status は最も強いもの（`INVALID_INPUT` ＞ `INSUFFICIENT_TIME_PRECISION` ＞ `INSUFFICIENT_DATA` ＞ `NOT_COMPARABLE` ＞
  `UNDEFINED`）。失敗を None にしない。`value` は `VALUE` の時だけ。
- 結果は `input_record_ids`（使った A2 の record id）・`period_label` ・`quarter` ・`rules_version` を持つ。

---

## 9. 意図して支えない指標（将来の A3 の sub-gate）

純利益率 ・EPS 成長率 ・ROE ・ROA ・PER ・PBR ・時価総額 ・価格の return ・変動率 ・流動性。TTM ・年率化 ・単独の四半期への変換 ・
経常利益の代用 ・基準の橋渡しも支えない。

---

## 10. test（`tests/intelligence/test_screener_fundamental_metrics.py`。すべて合成 data）

| 群 | 内容 |
|---|---|
| A 売上成長率 | FY/FY の正 ・負 ・0 の成長、分母 0（`UNDEFINED`）、欠損の comparison（`NOT_FOUND` ・`VALUE_ABSENT` ・`BEFORE_COVERAGE`）、別の発行体、**JP↔IFRS ・IFRS↔JP ・JP↔US の不連続**、別の区分（単体どうしは可）、UNKNOWN の基準 ・区分 ・修正の行の注記 ・注記なし、注記の不一致、期間の不整合（隣接しない ・basis ・四半期 ・単独の四半期 ・不規則な年度。解決の前に止まる）、累計の同じ四半期の YoY（label ＝ 累計）、未来の revision の除外と過去の cutoff の安定、日付だけの知識の日の途中の cutoff、Decimal の決定論と桁の正規化、入力の誤りは型つきの結果 |
| B 営業利益率 | 正 ・負 ・0 の営業利益、売上 0（`UNDEFINED`）、売上 ・営業利益の欠損、期間の不一致、脚の間の基準の違い ・注記の不一致 ・UNKNOWN、PIT の cutoff（前 ・元の値 ・訂正の後 ・日の途中）、累計の期間の label、単独の四半期 ・不規則な年度の拒否 |
| C 結果の model | status の語彙が閉じている、code → status が全域、理由の順と重複、`VALUE` と値の整合、非永続 ・評価の field なし |
| D architecture | float ・IO ・時計 ・network ・LLM ・評価の語 ・OdP の禁止、A2 の `resolve` と A2R の gate だけを使い履歴の内部に触れない、TTM ・年率化 ・四半期の引き算なし |

境界の guard（`test_screener_intelligence_boundary.py`）の追加: 2 module の import の許可の集合 ・閉包、A1 ／ A2 ／ A2R の名前の指名
（`SANCTIONED_A3A_IMPORTS`）、先行の層が A3A を知らない、評価の語の禁止、A2RI の anchor `4d3540c` の byte 一致（13 module ・4 test ・12 文書）。

---

## 11. 変更したファイル

- `src/intelligence/screener_intelligence/metric_model.py`【新規】
- `src/intelligence/screener_intelligence/fundamental_metrics.py`【新規】
- `tests/intelligence/test_screener_fundamental_metrics.py`【新規】
- `docs/databank/PHASE8_A3A_FUNDAMENTAL_METRICS.md`【新規】（本書）
- `tests/intelligence/phase8_runtime_registry.py`（2 module ・test ・本書の登録、`PHASE8_A3A_RUNTIME`、anchor `P8_A2RI`）
- `tests/intelligence/test_screener_intelligence_boundary.py`（2 module の境界 ・語彙 ・指名の import の guard、A2RI の凍結の guard、
  先行の anchor の guard の対象から後の gate の test ・文書を外す）
- `CHANGELOG.md`（v5.62）
- A1 ・A2 ・A1R ・A2R の runtime ・config.yaml ・knowledge ・scripts ・workflow ・Pages ・main.py ・Phase 4〜7 ・先行の文書は無変更

---

## 12. 実データまでの残る blocker と次の gate

| 事項 | 状態 |
|---|---|
| 実の identity の登録（Issuer ／ Security の bootstrap） | 未（P8-OBS-12 ・29） |
| adapter（`/v2/fins/summary` の行 → A2 の観測 ＋ A2R の注記 ＋ plan → `append`） | 未（P8-OBS-53 ・54 ・56） |
| 注記 ・HOLD の保留の store | 未（P8-OBS-56） |
| 通貨（非円の表示の発行体 ・`Foreign`）の保留の規則 | adapter の規則（P8-OBS-53） |
| 利用規約（raw の保存 ・再配布） | INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED のまま |
| 基準の橋渡し | 無い（P8-OBS-57 で閉じた。将来は別の bridge-evidence の gate） |

P8-OBS の更新: P8-OBS-57 → CLOSED（監督の決定: 基準の変更は不連続。本層は `NOT_COMPARABLE`）。P8-OBS-22 → STRUCTURALLY_ADDRESSED
のまま（累計 YoY は本層で支えるが、EPS ・CF の累計は UNKNOWN）。

次の A3 の sub-gate の準備度: 純利益率（`NP` ＝ 親会社株主に帰属する当期純利益が DOCUMENTED。同じ architecture で READY）、
ROA（`TA` ・年度のみ。READY_WITH_RESTRICTIONS）。EPS 成長率 ・PER ・PBR は分割の未調整（BLOCKED_BY_UNIT_SEMANTICS）、ROE ・時価総額は
A2 の `EQUITY` ・`SHARES_OUTSTANDING` の定義（BLOCKED_BY_PROVIDER_MAPPING）のまま。

```
P8-A3A（本 gate: VALIDATED）
  → 監督の review
  → 次の候補: (a) P8-A3B 純利益率 ・ROA（同じ architecture。合成 data）
             (b) adapter ／ 注記 store の設計（実データの前。identity の登録の方針を含む）
```

## 13. 判定

**P8_A3A_FUNDAMENTAL_METRICS_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**

他の指標 ・価格 ・valuation ・screen ・ranking ・推奨 ・Theme ・adapter ・実の identity ・Phase 9 は行っていない。
