# PHASE 8 / P8-A2R-IMPL — ACCOUNTING SEMANTICS SAFETY REMEDIATION（実装の記録）

P8-A2R（公式の仕様の確認 `45a516f`）で確定した欠陥 G1 —— **A2 の財務の観測の slot の identity（主語 ・欄 ・`statement_basis` ・
期間）に会計基準の次元が無く、違う会計基準の観測が同じ revision の鎖に入り得る** —— を、凍結した A2 の 3 module を 1 byte も
変えずに、**追加だけ**で fail closed にする gate。監督の決定（GO → P8-A2R-IMPL。A3 は始めない）に従う。

- 基準: P8-A2R 再実行 `45a516f4886a679063acc2843df2cca321199312`（凍結）、P8-A2 `b686b00`、P8-A1 `4162e9c`。full pytest の基準
  5349 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・財務の実の値を載せない。J-Quants の data API への要求は 0 回。LLM は使わない。
- 分類: **DOCUMENTED**（公式の文書）／ **OBSERVED_IN_PILOT**（PILOT1 の実の応答）／ **SUPERVISOR_APPROVED_MAPPING_RULE**（監督の
  決定 d2）／ **UNKNOWN**。実装の record はこの区別をそのまま持つ（DOCUMENTED に潰さない）。

---

## 0. 結論

1. 追加した runtime は 3 module（`src/intelligence/screener_intelligence/`）: `observation_semantics_model`（canonical の意味の
   注記 ・provider の写しの provenance）、`observation_semantics_mapping`（公式の `DocType` の列挙の版つき表引き）、
   `observation_semantics_gate`（互換の gate ・追記の plan）。A1 ・A2 ・A1R の module は無変更（凍結の guard で byte 一致を証明）。
2. 会計基準の語彙は監督の決定 d1 のとおり `JP_GAAP` ・`US_GAAP` ・`IFRS` ・`JMIS` ・`UNKNOWN`。`Foreign` ・`REIT` は会計基準ではない
   （`UNKNOWN`）。連結の区分は A2 の `StatementBasis` を再利用し、不明は `None`（競合する語彙を作らない）。
3. `DocType` の写しは**公式に列挙された 45 値の完全一致の表引き**（版 `p8_jquants_v2_fins_summary_doctype:0.1.0`）。文字列の分解 ・
   部分一致 ・接尾辞の判定を意味の authority にしない（test で AST の水準で禁止）。表に無い値は `UNRECOGNIZED` で両方の次元が
   `UNKNOWN`。
4. `NonConsolidated` の行の接頭辞の無い欄 → `NON_CONSOLIDATED` は、PILOT1 で観測した 4 値（`{1Q,2Q,3Q,FY}FinancialStatements_
   NonConsolidated_JP`）に限り、根拠 `(OBSERVED_IN_PILOT, SUPERVISOR_APPROVED_MAPPING_RULE)` の組で写す（d2）。DOCUMENTED と主張しない
   （test で明示）。観測していない `NonConsolidated`（IFRS ・Foreign ・OtherPeriod）は `UNKNOWN`。
5. 予想の修正の行（`EarnForecastRevision` 等）は会計基準 ・連結の区分とも `UNKNOWN`。他の行 ・先行の開示 ・同じ発行体 ・同じ年度から
   継承しない（写しの関数は `DocType` と欄の family しか受けない。d3）。
6. 互換の gate: KNOWN どうしで同じ → `COMPATIBLE`（比べ得る、の意）、違う → `INCOMPATIBLE`、どちらかが `UNKNOWN` → `INELIGIBLE`。
   理由の code は閉じた語彙。順位 ・score ・指標 ・A2 の変更は無い。
7. 追記の plan: `UNKNOWN`、鎖の先頭と違う、注記の不一致、slot ・`supersedes` の不一致 → `HOLD`（理由つき）。すべて満たす →
   `ELIGIBLE`。plan は追記しない ・捨てない ・補わない ・record にならない（`DERIVED_NON_AUTHORITY_NON_PERSISTENT`）。**A2 の store
   の `append` は本 gate の外**（ELIGIBLE の plan だけを caller が渡す。A2 の凍結の検査はそのまま働く）。
8. G1 の実証（test K）: JP 基準の鎖に IFRS 基準の revision を足すと、凍結した A2 の `ObservationHistory.check` は通すが、本 gate は
   `HOLD(ACCOUNTING_STANDARD_DIFFERS_FROM_CHAIN)` で止める。
9. 判定: **P8_A2R_IMPLEMENTATION_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§14）。A3 は始めていない。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `45a516f4886a679063acc2843df2cca321199312`（期待どおり。working tree は clean） |
| P8-A1 ／ P8-A2 の凍結 | `4162e9c` ／ `b686b00` と byte 一致（開始時に確認） |
| `PHASE8_A2R_OFFICIAL_SPEC_VERIFICATION.md` | 存在 |
| full pytest の基準 | 5349 passed ／ 2 skipped（開始時に確認） |

---

## 2. 追加した architecture

```
A2（凍結）: observation_model ・observation_store ・observation_resolver     ← 1 byte も変えない
A2R-IMPL（追加）:
  observation_semantics_model    canonical の注記 ObservationSemantics（p8sem_）・写しの provenance SemanticMappingProvenance（p8map_）
  observation_semantics_mapping  DOCUMENTED_DOC_TYPES（公式の 45 値）・map_row_semantics ・derive_observation_semantics
  observation_semantics_gate     decide_compatibility → CompatibilityDecision ／ plan_append → AppendPlan（ELIGIBLE ／ HOLD）
流れ:  provider の行（DocType ・欄の family）→ 注記 ＋ provenance → 互換の判定 → 追記の plan → [caller が ELIGIBLE だけ A2 の append へ]
```

| 制約 | 実装 |
|---|---|
| A2 の core を変えない | 3 module は A2 の `StatementBasis` ・`FundamentalActual` ・`FundamentalForecast` の型だけを使う。store ・resolver ・`ObservationHistory` を import しない（test N ・境界の guard） |
| A1 の identity を変えない | A1 からは `SourceClass` ・`canonical_json` ・`CREDENTIAL_MARKERS` だけ。A1R の module を使わない |
| 決定論 ・不変 | frozen dataclass、内容 address の id（`content_id`）、時計 ・乱数 ・IO ・float なし（境界の guard の AST 検査を追加の module にも適用） |
| 非 authority | 注記は `SEMANTIC_METADATA_RECORD`（A2 の store に入らない）。判定 ・plan は `DERIVED_NON_AUTHORITY_NON_PERSISTENT`（record id なし） |
| 他の package から見えない | production runtime closure に含まれない（既存の guard BO） |

---

## 3. canonical の意味の metadata（`ObservationSemantics`）

| field | 型 | 意味 |
|---|---|---|
| `observation_id` | `p8obs_…`（A2 の観測の record id） | 注記の対象。A2 の id は内容 address なので追記の前に決まる |
| `accounting_standard` | `AccountingStandard` | `JP_GAAP` ・`US_GAAP` ・`IFRS` ・`JMIS` ・`UNKNOWN`（d1） |
| `statement_basis` | `StatementBasis` か `None` | A2 の語彙を再利用。`None` ＝ UNKNOWN |
| `semantic_status` | `SemanticStatus` | `KNOWN` ／ `ACCOUNTING_STANDARD_UNKNOWN` ／ `STATEMENT_BASIS_UNKNOWN` ／ 両方。2 つの次元から決定論で決まり、食い違えば `STATUS_MISMATCH` で拒む |
| `mapping_rule_version` | `name:semver` | 写しの規則の版 |
| `mapping_provenance_id` | `p8map_…` | 根拠の provenance の record の参照 |

- 直列化: `as_dict` ／ `from_dict` ／ `canonical_line`（未知の欄 ・schema ・kind ・id の改竄 ・状態の不一致を拒む）。
- 会計基準の `Foreign` は語彙に無い（`from_dict` で `INVALID_VOCABULARY`）。

## 4. provider の写しの provenance（`SemanticMappingProvenance`）

| field | 値 |
|---|---|
| `provider` | `SourceClass.JQUANTS`（A1 の出所の語彙を再利用） |
| `schema_family` | `JQUANTS_V2_FINS_SUMMARY` |
| `doc_type` | provider の `DocType` の文字列そのまま（64 文字まで ・空白 ・path ・credential の印は拒む） |
| `field_family` | `UNPREFIXED_ACTUAL` ／ `NC_PREFIXED_ACTUAL` ／ `UNPREFIXED_FORECAST` ／ `NC_PREFIXED_FORECAST` |
| `document_kind` | `FINANCIAL_STATEMENTS` ／ `FORECAST_REVISION` ／ `REIT_FINANCIAL_STATEMENTS` ／ `REIT_FORECAST_REVISION` ／ `UNRECOGNIZED` |
| `mapping_rule_version` | `p8_jquants_v2_fins_summary_doctype:0.1.0` |
| `accounting_standard_evidence` ／ `statement_basis_evidence` | `SemanticEvidence` の tuple（語彙の順 ・重複なし）。空 ＝ その次元を支える根拠が無い（＝ UNKNOWN） |
| `documentation_ref` | 公式の節の token（`jquants-v2:spec.fin-summary.typeofdocument` 等。URL ・path ではない） |

raw の応答 ・header ・credential ・本文は持たない。

---

## 5. `DocType` の写し（版 0.1.0）

### 5.1 表（公式の 45 値。A2R 再実行 §4.1 の列挙と同じ）

| 群（`<期間>` ＝ FY ・1Q ・2Q ・3Q ・OtherPeriod） | 行の会計基準 | 行の区分 | 根拠 |
|---|---|---|---|
| `<期間>FinancialStatements_Consolidated_JP` | `JP_GAAP` | CONSOLIDATED | DOCUMENTED |
| `<期間>FinancialStatements_Consolidated_US` | `US_GAAP` | CONSOLIDATED | DOCUMENTED |
| `<期間>FinancialStatements_NonConsolidated_JP` | `JP_GAAP` | NON_CONSOLIDATED（行） | DOCUMENTED（行）／ 接頭辞の無い欄は §5.2 |
| `<期間>FinancialStatements_Consolidated_JMIS` | `JMIS` | CONSOLIDATED | DOCUMENTED |
| `<期間>FinancialStatements_NonConsolidated_IFRS` | `IFRS` | NON_CONSOLIDATED（行） | DOCUMENTED（行）／ 接頭辞の無い欄は UNKNOWN |
| `<期間>FinancialStatements_Consolidated_IFRS` | `IFRS` | CONSOLIDATED | DOCUMENTED |
| `<期間>FinancialStatements_NonConsolidated_Foreign` | `UNKNOWN`（外国株は基準ではない） | NON_CONSOLIDATED（行） | 基準: 根拠なし ／ 区分: DOCUMENTED（行）／ 接頭辞の無い欄は UNKNOWN |
| `<期間>FinancialStatements_Consolidated_Foreign` | `UNKNOWN` | CONSOLIDATED | 基準: 根拠なし ／ 区分: DOCUMENTED |
| `FYFinancialStatements_Consolidated_REIT` | `UNKNOWN` | UNKNOWN | 対象外 |
| `EarnForecastRevision` ・`DividendForecastRevision` | `UNKNOWN` | UNKNOWN | token なし（d3） |
| `REITEarnForecastRevision` ・`REITDividendForecastRevision` | `UNKNOWN` | UNKNOWN | 対象外 |

### 5.2 欄の family ごとの規則（`map_row_semantics(doc_type, field_family)`）

| 行の種類 | 欄の family | 会計基準 | 連結の区分 | 根拠の分類 |
|---|---|---|---|---|
| 財務諸表 ・`Consolidated` | 接頭辞なし（実績 ・予想） | 行の基準 | CONSOLIDATED | DOCUMENTED ／ DOCUMENTED |
| 財務諸表 ・`NonConsolidated_JP`（PILOT1 で観測した 4 値） | 接頭辞なし | `JP_GAAP` | NON_CONSOLIDATED | DOCUMENTED ／ **(OBSERVED_IN_PILOT, SUPERVISOR_APPROVED_MAPPING_RULE)** |
| 財務諸表 ・その他の `NonConsolidated`（IFRS ・Foreign ・OtherPeriod_JP） | 接頭辞なし | 行の基準（Foreign は UNKNOWN） | **UNKNOWN** | 区分の根拠なし |
| 財務諸表 ・予想の修正（REIT 以外） | `NC*` ・`FNC*` ・`NxFNC*` | **UNKNOWN**（行の token を `NC` の欄に継承しない） | NON_CONSOLIDATED | — ／ DOCUMENTED（欄の定義「_非連結」） |
| 予想の修正 | 接頭辞なし | UNKNOWN | UNKNOWN | 根拠なし |
| REIT の行 ・表に無い値 | すべて | UNKNOWN | UNKNOWN | 根拠なし |

- 表引きは完全一致（大文字小文字 ・空白 ・接尾辞の違いは別の値 ＝ UNRECOGNIZED）。写しの module に `split` ・`endswith` ・
  `startswith` ・`find` ・部分一致の `in` が無いことを test が AST で確かめる。

---

## 6. 互換の gate（`decide_compatibility`）

| 左 ・右 | 判定 | 理由の code |
|---|---|---|
| KNOWN ・KNOWN、基準も区分も同じ | `COMPATIBLE` | なし |
| KNOWN ・KNOWN、基準が違う | `INCOMPATIBLE` | `ACCOUNTING_STANDARD_DIFFERS` |
| KNOWN ・KNOWN、区分が違う | `INCOMPATIBLE` | `STATEMENT_BASIS_DIFFERS` |
| どちらかに UNKNOWN | `INELIGIBLE` | `LEFT_／RIGHT_ACCOUNTING_STANDARD_UNKNOWN` ・`LEFT_／RIGHT_STATEMENT_BASIS_UNKNOWN`（違いは論じない） |
| UNKNOWN ・UNKNOWN | `INELIGIBLE` | 左右 4 つ |

`COMPATIBLE` は「比べ得る」で、比べて良い（期間 ・累計 ・通貨 ・決算期の変更）は A3 の規則。順位 ・score ・指標は作らない。

## 7. 追記の plan（`plan_append`。監督の決定 d3）

| 条件 | 結果 |
|---|---|
| 注記の `observation_id` ≠ 観測の record id | `HOLD(SEMANTICS_NOT_FOR_THIS_OBSERVATION)` |
| 会計基準 UNKNOWN ／ 区分 UNKNOWN | `HOLD(ACCOUNTING_STANDARD_UNKNOWN)` ／ `HOLD(STATEMENT_BASIS_UNKNOWN)` |
| 注記の区分 ≠ A2 の観測の `statement_basis` | `HOLD(STATEMENT_BASIS_INCONSISTENT_WITH_OBSERVATION)` |
| 鎖が空で `supersedes` ≠ "" | `HOLD(SUPERSEDES_MISMATCH)` |
| 鎖の先頭あり: 先頭の注記が先頭のものでない ／ slot が違う ／ `supersedes` が先頭を指さない | `HOLD(CHAIN_SEMANTICS_NOT_FOR_CHAIN_HEAD ／ CHAIN_SLOT_MISMATCH ／ SUPERSEDES_MISMATCH)` |
| 先頭の基準 ／ 区分が UNKNOWN | `HOLD(CHAIN_ACCOUNTING_STANDARD_UNKNOWN ／ CHAIN_STATEMENT_BASIS_UNKNOWN)` |
| 先頭と基準 ／ 区分が違う | `HOLD(ACCOUNTING_STANDARD_DIFFERS_FROM_CHAIN ／ STATEMENT_BASIS_DIFFERS_FROM_CHAIN)` |
| すべて満たす | `ELIGIBLE` |

- 理由は集合として集め、語彙の順で並べる（決定論）。plan は `observation_id` ・`slot_key` ・`chain_head_id` ・規則の版を持つ。
- **実行の境界**: plan は追記しない。A2 の store への `append` は本 layer の外で、ELIGIBLE の plan だけを渡す。凍結の A2 の検査
  （鎖の分岐 ・知識の逆行 ・coverage）はそのまま働く。HOLD の観測は捨てず、caller が保留として保つ（保留の store は本 gate の外。§12）。
- 市場の観測 ・注記でない物 ・片方だけの鎖は例外（`NOT_FINANCIAL_OBSERVATION` ・`INVALID_SEMANTICS` ・`INVALID_CHAIN`）。

---

## 8. 意味の分類の一覧（本 layer が主張する事 ・しない事）

| 事項 | 分類 |
|---|---|
| `DocType` の値の全集合（45） | DOCUMENTED（A2R 再実行 O3 ・O4） |
| `JP` ・`US` ・`IFRS` ・`JMIS` の意味 | DOCUMENTED |
| `Consolidated` の行の接頭辞の無い欄 ＝ 連結 | DOCUMENTED |
| `NC*` ＝ 非連結 | DOCUMENTED（欄の定義） |
| `NonConsolidated_JP`（4 値）の接頭辞の無い欄 ＝ 単体 | OBSERVED_IN_PILOT ＋ SUPERVISOR_APPROVED_MAPPING_RULE |
| その他の `NonConsolidated` の接頭辞の無い欄 | UNKNOWN |
| `NC*` の会計基準 | UNKNOWN |
| 予想の修正の行の基準 ・区分 | UNKNOWN（token なし。継承しない） |
| `Foreign` の会計基準 | UNKNOWN（会計基準ではない） |
| REIT | UNKNOWN（対象外） |
| 表に無い `DocType` | UNKNOWN（`UNRECOGNIZED`） |

---

## 9. test（`tests/intelligence/test_screener_observation_semantics.py`。すべて合成 data）

| 群 | 内容 |
|---|---|
| A | 語彙: 会計基準は d1 の 5 値、`Foreign` ・`REIT` は member でない、連結の区分は A2 の語彙の再利用（新しい Basis 型なし） |
| B | 公式の 45 値の表と一致、写しは全域で例外を出さない、UNKNOWN ⇔ 根拠なし |
| C〜E | JP_GAAP 連結 ・US_GAAP ・IFRS ・JMIS の写し（DOCUMENTED） |
| D | `NonConsolidated_JP` 4 値の接頭辞の無い欄: (OBSERVED_IN_PILOT, SUPERVISOR_APPROVED_MAPPING_RULE)、DOCUMENTED を主張しない ／ 観測していない `NonConsolidated` は UNKNOWN ／ `NC*` は非連結 ・基準を継承しない（45 値すべて） |
| F ・G | `Foreign` は会計基準ではない（HOLD）／ REIT は両方 UNKNOWN |
| H | 表に無い値（大文字小文字 ・空白 ・接尾辞 ・公式の token を含む物）は UNKNOWN ／ 写しの module に文字列の解析が無い（AST）・表の鍵は literal |
| I | 予想の修正は UNKNOWN で HOLD ／ 先行の行から継承しない（写しの関数の引数は `doc_type` ・`field_family` だけ） |
| J | 互換: 同じ ・基準が違う ・区分が違う ・KNOWN 対 UNKNOWN ・UNKNOWN 対 UNKNOWN、決定論 ・型つき ・不変 |
| K | plan: 空の鎖 ・一致する revision → ELIGIBLE ／ **G1: A2 は通すが gate は HOLD** ／ 区分の違い ・UNKNOWN ・先頭の UNKNOWN ・注記の不一致 ・slot ・`supersedes` の不一致 → HOLD ／ 市場の観測 ・片方の鎖は例外 ／ plan は record にならず store を使わない |
| L | id ・直列化: 内容 address ・往復 ・改竄 ・状態の不一致 ・根拠の順 ／ 重複 ・credential ・path ・float の拒否 |
| M | DOCUMENTED の主張は公式の本文が定める次元だけ、監督の承認は観測した 4 値だけ |
| N | store ・resolver ・`ObservationHistory` を使わない |

境界の guard（`test_screener_intelligence_boundary.py`）の追加: 3 module の import の許可の集合 ・閉包、A1 ／ A2 の名前の指名
（`SANCTIONED_A2R_IMPORTS`）、A1 ／ A2 ／ A1R が A2R を知らない、派生 ・評価の語の禁止、A2RV の anchor `45a516f` の byte 一致。

---

## 10. 凍結の証明

- `PHASE8_A2_RUNTIME`（A1 ＋ A2 の 7 module）は `b686b00` ・`4162e9c` と byte 一致（既存の guard）。A1R の 3 module は `e6a750f` と byte 一致。
- 先行の anchor（LV1 ・PILOT1 ・A2R ・A2RV）の guard は、**その anchor に存在した 10 module（`PRE_A2R_RUNTIME`）と 3 つの test file**
  を対象にするよう登録の行だけを直した（新しい module ・test ・文書はその anchor に無い）。
- Phase 6 ・7 ・4 ／ 5 ・Production DNA ・main.py ・Pages ・config ・workflow は無変更（既存の guard）。

---

## 11. 変更したファイル

- `src/intelligence/screener_intelligence/observation_semantics_model.py`【新規】
- `src/intelligence/screener_intelligence/observation_semantics_mapping.py`【新規】
- `src/intelligence/screener_intelligence/observation_semantics_gate.py`【新規】
- `tests/intelligence/test_screener_observation_semantics.py`【新規】
- `docs/databank/PHASE8_A2R_IMPLEMENTATION.md`【新規】（本書）
- `tests/intelligence/phase8_runtime_registry.py`（3 module ・test ・本書の登録、`PHASE8_A2R_RUNTIME`、anchor `P8_A2RV`）
- `tests/intelligence/test_screener_intelligence_boundary.py`（3 module の境界 ・語彙 ・指名の import の guard、A2RV の凍結の guard、
  先行の anchor の guard の対象を `PRE_A2R_RUNTIME` に）
- `CHANGELOG.md`（v5.61）
- A1 ・A2 ・A1R の runtime ・config.yaml ・knowledge ・scripts ・workflow ・Pages ・main.py ・Phase 4〜7 ・先行の文書は無変更

---

## 12. 残る UNKNOWN と次の gate

| 事項 | 状態 |
|---|---|
| `NC*` の会計基準 | UNKNOWN（公式に無い。行から継承しない） |
| 予想の修正の行の基準 ・区分 | UNKNOWN（d3。写さず HOLD） |
| 観測していない `NonConsolidated`（IFRS ・Foreign ・OtherPeriod）の接頭辞の無い欄 | UNKNOWN（観測か監督の承認まで） |
| `Foreign` の会計基準 | UNKNOWN（会計基準ではない） |
| 注記 ・provenance の**保存**（追記専用の store）と HOLD の観測の保留の store | 本 gate の外（P8-OBS-56。record は直列化できる） |
| ELIGIBLE の plan の**実行**（A2 の store の `append` を呼ぶ adapter） | 本 gate の外（adapter の gate。A2 は変えない） |
| 基準の変更で HOLD した観測の後の扱い（新しい鎖の規則） | 監督の判断（P8-OBS-57） |
| 通貨 ・累計 ・期間 ・決算期の変更の比較の規則 | A3 の規則（A2R 再実行 §12 の制限） |

P8-OBS の更新: P8-OBS-50 → **STRUCTURALLY_ADDRESSED**（G1 を追加の layer で fail closed。CLOSED は adapter が plan を経て実データを
入れた後）。P8-OBS-55 → STRUCTURALLY_ADDRESSED（d2 の範囲 ＝ 観測した 4 値で写し、他は UNKNOWN）。新規: P8-OBS-56（注記 ・保留の
store 未実装。BLOCKED_PENDING_ADAPTER）、P8-OBS-57（基準の変更の後の鎖の規則。BLOCKED_PENDING_IDENTITY_POLICY 相当の監督の判断）。

**A3（売上成長率 ・営業利益率）の開始の可否**: 意味の safety は本 layer で満たせる。A3 は本 layer の `COMPATIBLE` かつ両方 KNOWN の
注記を持つ観測だけを使う契約になる。ただし本 gate では A3 を始めない（監督の GO が要る）。実データは実の identity の登録 ・adapter ・
注記の store の後。

```
P8-A2R-IMPL（本 gate: VALIDATED）
  → 監督の review: 本 layer の受け入れ、P8-OBS-57 の規則
  → 次の候補: (a) P8-A3（売上成長率 ・営業利益率。合成 data。COMPATIBLE ＋ KNOWN の観測だけ）
             (b) 注記 ・保留の store と adapter の設計（実データの前）
```

---

## 13. 検証

結果は最終報告に記す（新しい test ・A2 ・A1 ・A1R ・Phase 8 の境界 ／ 凍結 ・Phase 7 ・Phase 6 ・Phase 4 ／ 5 の guard ・full pytest。
基準 5349 passed ／ 2 skipped に本 gate の test の増分）。

## 14. 判定

**P8_A2R_IMPLEMENTATION_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**

A3 ・指標の計算 ・screen ・ranking ・推奨 ・Theme ・実の identity の登録 ・raw の保存 ・Phase 9 は行っていない。
