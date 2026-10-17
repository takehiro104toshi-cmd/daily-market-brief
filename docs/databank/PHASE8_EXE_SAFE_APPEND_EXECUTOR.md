# PHASE 8 / P8-EXE — SAFE APPEND EXECUTOR（合成の provider の行 → authority への最初の安全な実行の境界）

P8-ADP0 の純 adapter（PASS ／ FROZEN `a2ccc1c`）の上に、**実行時に再導出した適格の下でだけ** 凍結の A2 の観測 ・ST1 の注記 ・ST1 の
保留に append する executor を実装した gate。監督の決定 D1〜D8 に従う。合成の行 ・合成の identity ・tmp_path の private root だけ。
live の J-Quants request ・identity の登録 ・実データの pilot ・指標 ・公開の出力は**無い**。

- 基準: P8-ADP0 `a2ccc1c30543daee5269ca39a7591a4767376f1d`（凍結。runtime 21 module）。full pytest の基準 5696 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・財務の実の値を載せない。

---

## 0. 結論

1. 追加した runtime は 2 module: `jquants_execution_model`（結果の型 ・閉じた理由）、`jquants_financial_summary_executor`
   （`execute_financial_summary_row(row, context, data_root, *, prior_adapter_result=None)`）。先行の 21 module は byte 一致。
2. **信頼の境界**: 入力は元の行 ＋ caller の文脈 ＋ 明示の `data_root` だけ。executor は凍結の ADP0 を毎回再実行し、append する record
   を自分で組み立て直す。`AdapterResult` ・`AppendPlan` ・注記 ・正準の観測 ・provider の identity ・`supersedes` ・指標を受ける引数は
   **無い**（§3）。`prior_adapter_result` は任意の cross-check で、再導出と一致しなければ `REJECTED / PRIOR_RESULT_MISMATCH`（書かない。
   prior を「更新」しない）。
3. 結果 `ExecutionResult` の帰結: `APPENDED` ／ `REUSED` ／ `HELD` ／ `REJECTED` ／ `PARTIAL_FAILURE` ／ `NO_REPORTED_FIELDS`。
   score ・severity ・順位は無い。`writes` に authority ごとに**実際に**書いた ／ 収束した record id を列挙する。要る書き込みがすべて
   終わらなければ `APPENDED` にならない（model が検査する）。
4. 書く先は A2 `ObservationStore` ・`SemanticMetadataStore` ・`HeldObservationStore` の 3 つだけ。identity ・指標 ・Theme ・Narrative ・
   Production DNA ・Pages ・legacy ・raw ・adapter の結果の journal ・executor の journal には書かない（§13）。
5. `NOT_REPORTED` の欄は 0 の観測を作らず、A2 に何も書かない。他の欄は実行する。結果に欄ごとの扱いを明示する（§6）。
6. 順序: A. 全欄の前検査（0 書き込み）→ 欄ごとに B. 写しの provenance → 注記 → C. A2 の観測 → D. 結果。journal をまたぐ transaction
   は無いので、途中の失敗は `PARTIAL_FAILURE`（rollback ・削除 ・上書きは無い）。再実行は byte 一致の再利用で収束する（§8 ・§9）。
7. 孤児の注記（A2 の append が失敗した後に残る `SEMANTIC_METADATA_RECORD`）は authority にならず、参照する A2 の観測が存在するときだけ
   意味を持つ（§10）。
8. revision: 凍結の A2 の履歴から slot の鎖の末尾を再導出し `supersedes` を決める。同じ provider の revision（参照 ＝ digest）は再利用、
   内容の違う訂正は新しい不変の revision（§11）。会計基準の違いは鎖に入れない（OBS-57。§12）。
9. identity: 文脈の `issuer_id` が凍結の A1 の履歴に無ければ `HELD / IDENTITY_UNRESOLVED`。登録しない ・Code から作らない（§14）。
10. P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION** のまま（§16）。
11. 判定: **P8_EXE_SAFE_APPEND_EXECUTOR_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§18）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `a2ccc1c30543daee5269ca39a7591a4767376f1d`（期待どおり。working tree は clean） |
| 凍結の anchor | A1 `4162e9c` ／ A1R `e6a750f` ／ A2 `b686b00` ／ A2R `4d3540c` ／ A3A `84c2d52` ／ A3B `d8845f2` ／ A3R `f1c4a4e` ／ ST1 `e831996` ／ ADP0 `a2ccc1c` と byte 一致 |
| full pytest の基準 | 5696 passed ／ 2 skipped |
| network | 使わない |

---

## 2. 変更の範囲（不変の宣言）

| 対象 | 状態 |
|---|---|
| `src/intelligence/screener_intelligence/jquants_execution_model.py` | **新規** |
| `src/intelligence/screener_intelligence/jquants_financial_summary_executor.py` | **新規** |
| `tests/intelligence/test_screener_jquants_execution.py` | **新規**（42 test） |
| `tests/intelligence/phase8_runtime_registry.py` ・`test_screener_intelligence_boundary.py` | EXE の登録 ・ADP0 の anchor の guard |
| 先行の 21 module ・Phase 8 の test 8 file ・先行の記録 17 | **byte 一致**（guard `test_exe_*`） |
| `main.py` ・Pages ・config ・workflow ・Secrets ・legacy ・P4/P5 ・P6 ・P7 ・Production DNA | 変更なし |

---

## 3. 信頼の境界 ・実行時の再検証

| 規則 | 内容 |
|---|---|
| 入力 | `row`（`FinancialSummaryRow` ／ Mapping）・`context`（`AdapterContext`）・`data_root`（明示。空 ／ None → `REJECTED / INVALID_INPUT`） |
| 再導出 | 毎回 `adapt_financial_summary_row(row, context)`。これが唯一の真 |
| 受けない | 正準の観測 ・注記 ・`AppendPlan` ・provider の identity ・`supersedes` ・指標（引数が無い。渡せば `TypeError`。行の中の余計な key は `INVALID_INPUT`） |
| `prior_adapter_result` | 任意。`AdapterResult` 以外は `INVALID_INPUT`。`as_dict()` が再導出と完全一致しなければ `REJECTED / PRIOR_RESULT_MISMATCH`（偽造 ・古い文脈 ・HOLD の prior を含む）。書かない |
| 結果の authority | `DERIVED_NON_AUTHORITY_NON_PERSISTENT`（record ではない。保存しない） |

---

## 4. ELIGIBLE の経路

再導出が ELIGIBLE のとき、欄ごとに: identity（凍結 A1 の履歴）→ provider の record の identity ・digest（ADP0）→ 知識の時刻 ・期間
（ADP0 ・A2 の model）→ A2R の写し（ADP0 の `map_row_semantics`）→ pilot の方針（ADP0: JP_GAAP ＋ JPY）→ 区分 → 通貨（ADP0）→
凍結 A2 の `FundamentalActual` を鎖の末尾つきで構築 → 凍結 A2R の `derive_observation_semantics` → 凍結 A2R の `plan_append`（鎖の末尾の注記
と照合）→ 凍結 A2 の `ObservationHistory.check` ・注記の journal の前検査 → 注記の append → A2 の append。指標は計算しない。

## 5. HELD の経路

再導出が HOLD → ADP0 が作った ST1 の `HeldObservation` をそのまま保留の store にだけ append（`HELD / ADAPTER_HELD`）。executor が見つけた
保留（`IDENTITY_UNRESOLVED` ・鎖の意味の HOLD → `SEMANTIC_CHAIN_CONFLICT`）は executor の版で record を作る。A2 ・注記には書かない。同じ
record の replay は `held_reused`（新しい authority の書き込みなし）。

## 6. NOT_REPORTED

`""` の欄は `FieldDisposition.NOT_REPORTED`（`observation_write = NOT_REQUIRED`）。0 の観測を作らず A2 に書かない。4 欄すべてが記載なし →
`NO_REPORTED_FIELDS`（書き込みなし）。

## 7. 前検査

全欄の計画（鎖の末尾 ・replay の検出 ・`plan_append` ・`history.check` ・注記の journal の検査）と 3 store の `verify_unchanged` を終えてから
書く。1 つでも決定論の失敗があれば **0 書き込み**: `OBSERVATION_CONFLICT`（例: `NON_MONOTONIC_KNOWLEDGE` ・`FORK`）・`SEMANTIC_CONFLICT`
・`PRECHECK_FAILED`（`CHAIN_HEAD_SEMANTICS_MISSING` ・`CONCURRENT_MODIFICATION`）・`SEMANTIC_CHAIN_HOLD`（→ HELD）。

## 8. 書く順序

欄の順（Sales → OP → NP → TA）に、写しの provenance → 注記（journal は provenance が先に要る）→ A2 の観測。次の欄へ。

## 9. 部分失敗

1 つの authority に書いた後の失敗 → `PARTIAL_FAILURE`（理由 `STORE_WRITE_FAILED` ＋ `PARTIAL_WRITE`）。`writes` に成功した id、`fields` に
`FAILED` の欄（どの書き込みで失敗したか）と `NOT_ATTEMPTED` の欄を明示。rollback ・削除 ・上書きは無い。再実行: 注記は byte 一致で
`REUSED`、観測は `APPENDED` → `APPENDED` に収束。何も書く前の失敗は `REJECTED / STORE_WRITE_FAILED`。

## 10. 孤児の注記

注記の class は `SEMANTIC_METADATA_RECORD` のまま。参照する A2 の観測（`observation_id`）が authority に存在するときだけ意味を持ち、
存在しなければ authority にならず、A2R の gate ・A3 の指標はそれを読まない（観測が無い）。再実行が観測を append すれば意味を持つ。
削除 ・修復はしない。

## 11. A2 の revision ・`supersedes`

| 状況 | 扱い |
|---|---|
| slot の鎖が空 | `supersedes=""`（根） |
| 鎖に同じ provider の参照（digest）がある | `REUSED`（内容が違えば `OBSERVATION_CONFLICT / PROVIDER_REVISION_CONTENT_DIFFERS`） |
| 鎖に無い（訂正 ・新しい DiscNo） | `supersedes = 鎖の末尾の record_id`。新しい不変の revision。先の record は不変 |
| 末尾より前の知識 | 凍結 A2 が拒む → `OBSERVATION_CONFLICT / NON_MONOTONIC_KNOWLEDGE` |
| caller の `supersedes` | 受けない |

revision の単位は provider の record（digest）であり、値が同じでも別の provider の revision は別の観測の revision になる。

## 12. 会計基準の不連続

pilot は JP_GAAP だけなので IFRS 等は ADP0 で HELD になり A2 に届かない。regression guard: 鎖の末尾の注記が別の基準なら凍結 A2R の
`plan_append` が `ACCOUNTING_STANDARD_DIFFERS_FROM_CHAIN` で HOLD → `HELD / SEMANTIC_CHAIN_CONFLICT`（鎖に入らない）。NonConsolidated は
別の slot。

## 13. store の境界

書く先: `observation_records.jsonl` ・`semantic_metadata.jsonl` ・`held_observations.jsonl`。`initialize` ・削除 ・rename は無い。
store が無い → `REJECTED / STORE_MISSING`（作らない）。破損 → `REJECTED / CORRUPT_STORE`。

## 14. identity

文脈の `issuer_id` が A1 の形でなければ ADP0 が HOLD。形が正しくても凍結 A1 の履歴（`ObservationStore` が読む identity）に無ければ
`HELD / IDENTITY_UNRESOLVED`。登録しない ・Code から作らない ・identity の store ・resolver を import しない。identity の投入は P8-ID1。

## 15. 失敗の分類

`ADAPTER_HELD` ・`IDENTITY_UNRESOLVED` ・`PRIOR_RESULT_MISMATCH` ・`SEMANTIC_CONFLICT` ・`SEMANTIC_CHAIN_HOLD` ・`OBSERVATION_CONFLICT` ・
`PRECHECK_FAILED` ・`STORE_WRITE_FAILED` ・`PARTIAL_WRITE` ・`CORRUPT_STORE` ・`STORE_MISSING` ・`INVALID_INPUT`。`failure_code` は大文字の
code だけ（provider の値 ・本文 ・path ・traceback は通らない）。

## 16. raw ・terms の境界 ・OBS-58/59

行は memory だけ。raw ・応答 ・credential ・header は保存しない。合成 data だけ。live の J-Quants request 無し。公開の出力無し。
P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION**。

## 17. PILOT2 の前に残る要件

1. P8-ID1: identity の投入（合成でない issuer の登録。人の確認つき）。
2. OBS-58 ・59 の terms の確認（live の取得 ・保管の可否）。
3. live の取得の client（retry ・pagination ・raw を memory に留める境界）。
4. 運用の時刻の方針（`acquired_at` を誰が渡すか）。

## 18. 判定

**P8_EXE_SAFE_APPEND_EXECUTOR_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**
