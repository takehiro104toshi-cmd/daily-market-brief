# PHASE 8 / P8-ADP0R — MULTI-STANDARD PILOT ELIGIBILITY REMEDIATION（ADP0 の定数 1 つの狭い再開）

実 PILOT2（本人の private な Windows 環境。P8-PILOT2A の runner）の結果 `PILOT_PARTIAL` と、その読み取り専用の原因監査 P8-PILOT2R0
（PASS ／ CLOSED）を受けた監督の決定に従い、凍結 ADP0 の pilot の方針 D4 を**定数 1 つだけ**改定した gate。
実の J-Quants への request ・private の pilot の file の参照 ・保留 record の修復 ・OBS-60 の実装は**無い**。

- 基準: P8-PILOT2A `6e042732acd52ed6c1c25c9e39688e78844b7589`（凍結。runtime 32 ＝ package 30 ＋ transport ＋ runner）。
  full pytest の基準 5939 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・財務の実の値 ・会社名 ・銘柄 code を載せない。実 pilot については安全な要約の数値だけを引く。

---

## 0. 結論

1. **実 PILOT2 の症状**: target 1 ・ELIGIBLE_FOR_ID1 1 ・HUMAN APPROVE 1 ・ID2 APPENDED ・identity 確認 OK ・request 2 ／ 8 ・
   fins 成功 1 ・行 21 → **EXE は 21 行すべて `HELD`（`ADAPTER_HELD`）**。保留の理由は `ACCOUNTING_STANDARD_UNSUPPORTED` 21 ・
   `CURRENCY_UNKNOWN` 21 だけ。A3 の 4 指標は `UNAVAILABLE / NO_FISCAL_YEAR_OBSERVATION`。store はすべて OK。
2. **原因（P8-PILOT2R0）**: 凍結 ADP0 の `PILOT_ELIGIBLE_STANDARDS = (JP_GAAP,)`（監督の決定 D4。一時的な pilot の方針）。21 行は凍結
   A2R の表で認識され（`DOCTYPE_UNRECOGNIZED` ・`DOCTYPE_OUT_OF_SCOPE` ・`STATEMENT_BASIS_UNKNOWN` ・`PERIOD_UNSUPPORTED` ・
   `VALUE_UNPARSEABLE` が無い）、この門だけで止まった。`CURRENCY_UNKNOWN` は同じ門が機械的に添える保守的な理由で、payload の通貨の
   失敗の証拠ではない（`/v2/fins/summary` に通貨の欄は無い）。LIVE1 ・LIVE2 ・A2R の写し ・ID1 ・ID2 ・EXE は無関係。
3. **D4 の前後**: `(JP_GAAP,)` → `(JP_GAAP, US_GAAP, IFRS, JMIS)`。adapter の他の部分は PILOT2A の anchor と AST が一致する
   （guard `test_adp0r_the_adapter_differs_from_the_pilot2a_anchor_only_in_the_pilot_eligible_standards_tuple`）。
4. **通貨の意味**: 適格な財務諸表の行の金額に `Currency.JPY` ・`Scale.ONE` を付けるのは、公式に確認済みの provider の契約
   （金額は円単位 ・換算なし。P8-A2R 公式仕様の確認 §10）の**正規化**である。「発行体が円で報告している」「発行体の報告通貨は円」という
   主張では**ない**。provenance の `source_class` ・`source_record_ref` ・`source_field` は provider の record を指し、発行体の通貨の
   authority を名乗らない。
5. **P8-OBS-53（非円の表示の発行体）**: KNOWN_RESIDUAL_RISK ／ DEFERRED のまま。発行体 ・銘柄の除外一覧は作らない。code ・会社の
   identity ・市場 ・会計基準 ・名前 ・国の仮定から報告通貨を推定しない。別の endpoint を取らない。LLM の推論を使わない。
6. **fail closed のまま**: `UNKNOWN`（`Foreign` の行 ・REIT ・表に無い DocType ・予想の修正）は従来どおり HOLD
   （`ACCOUNTING_STANDARD_UNKNOWN` ＋ `CURRENCY_UNKNOWN`、該当すれば `STATEMENT_BASIS_UNKNOWN` ・`DOCTYPE_OUT_OF_SCOPE` ・
   `DOCTYPE_UNRECOGNIZED`）。`AccountingStandard` の語彙は変えない。
7. **予想 ・区分の規則は凍結のまま**: 予想の修正は基準 ・区分 UNKNOWN で HOLD。他の行から継承しない。`NonConsolidated` は監督の
   決定 d2 の 4 値（JP）だけ `NON_CONSOLIDATED`、他（IFRS ・Foreign ・OtherPeriod）は `STATEMENT_BASIS_UNKNOWN`。公式の表に無い
   `NonConsolidated_US` ・`NonConsolidated_JMIS` は `DOCTYPE_UNRECOGNIZED`。基準の間の橋渡しはしない: 同じ slot に基準の違う行が
   来れば凍結 A2R の `plan_append` が拒み、EXE は `SEMANTIC_CHAIN_CONFLICT` で保留する（P8-OBS-57。test で固定）。
8. **OBS-60 は別 ・保留のまま**: 本改定の後、IFRS 等の行は A2 に届くが、`FUNDAMENTAL_DISCLOSURE` の coverage 宣言は無いので A3 は
   typed の `INSUFFICIENT_DATA / OUTSIDE_COVERAGE` になる（PILOT2A の test で固定）。これが次の限界で、別 gate P8-OBS60 の対象。
9. **実 PILOT2 は未再実行**。先行の 21 の保留 record は旧方針の下の正しい不変の履歴として残る（削除 ・書き換え ・手動の supersede ・修復
   はしない）。再実行は新しい方針で同じ行を再導出し、ELIGIBLE の経路（`APPENDED`）になり得る。

---

## 1. 変更の範囲（監督の決定）

| 対象 | 変更 |
|---|---|
| `jquants_financial_summary_adapter.py` | `PILOT_ELIGIBLE_STANDARDS` を 4 基準に。module の docstring §5 と定数の注記を更新。実行の AST は他に差なし |
| A1 ・A2 model ・A2R の写し ・A3A ・A3B ・ST1 ・EXE ・ID1 ・ID2 ・LIVE1 ・LIVE2 ・PILOT2A runner ・P4〜P7 ・main.py ・Pages | 変更なし（PILOT2A の anchor と byte 一致。guard `test_adp0r_everything_but_the_reopened_adapter_is_byte_identical_to_the_pilot2a_anchor`） |
| `phase8_runtime_registry.py` | `P8_PILOT2A` の anchor ・本書の登録 |
| `test_screener_intelligence_boundary.py` | 再開した 5 path（adapter ・ADP0 test ・EXE test ・PILOT2A test ・ADP0 文書）を先行 anchor の byte 一致から外す `_frozen()`、新 guard `test_adp0r_*` 2 つ |
| `test_screener_jquants_adapter.py` | 4 基準の適格 ・JPY ・ONE ・`CURRENCY_UNKNOWN` の不発 ・Foreign/UNKNOWN の HOLD ・DocType token を文字列で持たない guard の更新 |
| `test_screener_jquants_execution.py` | 保留の例を Foreign に。IFRS の行は同 slot の JP の鎖に対して `SEMANTIC_CHAIN_CONFLICT` で保留（OBS-57） |
| `test_screener_pilot2_local_runner.py` | 保留の例を Foreign に。IFRS の経路の e2e（`APPENDED` 2 ・PASS ・A3 は `OUTSIDE_COVERAGE`） |
| `PHASE8_ADP0_JQUANTS_FINANCIAL_SUMMARY_ADAPTER.md` | §0 項目 8 ・§8 に D4 の前後を追記 |

---

## 2. 4 基準の適格と通貨（test で固定）

| DocType の基準 token | A2R の基準 | ADP0R の結果 |
|---|---|---|
| `JP` | `JP_GAAP` | ELIGIBLE。`JPY` ・`ONE` |
| `US` | `US_GAAP` | ELIGIBLE。`JPY` ・`ONE` |
| `IFRS` | `IFRS` | ELIGIBLE。`JPY` ・`ONE` |
| `JMIS` | `JMIS` | ELIGIBLE。`JPY` ・`ONE` |
| `Foreign` | `UNKNOWN` | HOLD `ACCOUNTING_STANDARD_UNKNOWN` ＋ `CURRENCY_UNKNOWN` |
| REIT ・予想の修正 | `UNKNOWN` | HOLD（＋ `DOCTYPE_OUT_OF_SCOPE`） |
| 表に無い値 | `UNKNOWN` | HOLD（＋ `DOCTYPE_UNRECOGNIZED`） |

`CURRENCY_UNKNOWN` は認識された US_GAAP ・IFRS ・JMIS であることだけを理由に出ることは無い（他の理由で保留する行でも添えない）。
発行体ごとの例外一覧 ・code による通貨の分岐は adapter に存在しない（guard: 5 桁の code 形の文字列定数 ・`USD` ・`Foreign` の文字列 ・
`Currency.JPY` 以外の `Currency` の参照が無い）。

---

## 3. 先行の保留 record

実 pilot の 21 の `HeldObservation` は旧方針（D4 当初）の下で正しく作られた不変の履歴で、本 gate は触らない。本書の対象外である
private の store の内容は参照していない。再実行で同じ provider の record が ELIGIBLE になった場合、保留の store の record はそのまま残り、
A2 ・注記の store に新しい record が append される（EXE の設計どおり。保留は A2 の鎖に入っていないので衝突しない）。

---

## 4. 次の gate

- 実 PILOT2 の再実行（本人の環境。identity は ID2 で `REUSED`、fins 1 request を想定）。
- 期待: EXE `APPENDED` ≥ 1、A3 は typed の `INSUFFICIENT_DATA / OUTSIDE_COVERAGE`（OBS-60）→ P8-OBS60（coverage authority の設計）。
