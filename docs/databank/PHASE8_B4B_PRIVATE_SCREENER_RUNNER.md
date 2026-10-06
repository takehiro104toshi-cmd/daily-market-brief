# PHASE 8 / P8-B4B — PRIVATE SCREENER RUNNER INTEGRATION（PILOT2B runner への Screener の統合）

凍結の Screener の stack（B1 ・B2 ・B3 ・B4A）を、既存の private PILOT2B の local workflow に **明示の opt-in** で統合する gate。
明示の private の方針の authority → B4A の正確な解決 → 既存の PILOT2B の実 data の authority の chain → 凍結 B2 の評価 → private の
`ScreenerResult` → B4A の `SafeScreenerSummary` → 既存の private `safe_summary.json` の `screener` の節。runner は private ・local ・明示 ・
決定論 ・fail closed ・順位なし ・推奨なしのまま。Screener の結果は derived で authority にならない（保存しない）。

- 基準: P8-B4A `e7abbe1e67e5a3bdeca3edcd1a81bdce26bdf718`（凍結。runtime 49）。full pytest の基準 6474 passed ／ 2 skipped。
- 本 gate は合成の検証だけ。実 J-Quants request ・private の pilot root の参照 ・実の方針の作成 ・Windows の実 data の検証は行わない
  （実の検証は B4B の凍結の後、監督の別の承認の段）。
- 本書 ・CHANGELOG ・test ・source は実の閾値 ・実の方針 ・会社名 ・code を載せない。

---

## 0. 凍結の stack（変更なし）と再開した path

| 層 | 状態 |
|---|---|
| B1 `screener_criteria_model` ・B2 `screener_evaluator` ・B3 `screener_policy_authority_model` ／ `_store` ・B4A `screener_policy_evaluation` ／ `screener_result_summary` | byte 一致（P8_B4A anchor） |
| `src/intelligence/jquants_pilot2_local.py` | B4B で狭く再開（追加だけ。PREPARE ・identity ・ID2 ・ACQ0 ・manifest ・F1 ・保持 ・A3-RA ・STRICT の表示 ・予算 ・pagination ・resume ・既存の要約の欄は不変） |

runner が消費する名前（境界が完全一致で pin）: B4A `PolicyEvaluationError` ・`PolicySelector` ・`evaluate_selected_policy` ・
`open_verified_store` ・`resolve_policy` ・`project_safe_summary`、B2 `EvaluationInputs`（型だけ。評価は B4A 経由）、B1 `EvaluationContext` ・
`ScreenerModelError`。B3 の store は runner から直接 import しない（B4A が read-only で開く）。

## 1. CLI の契約（明示の opt-in だけ）

```
execute --data-root <private root> --acquired-at <aware ISO8601> [--decision <path>]
        [--screener-policy-id <p8pol_…> | --screener-policy-key <key> --screener-policy-version <int>]
```

| 入力 | 扱い |
|---|---|
| 選択子なし | legacy のまま（PILOT2A ／ PILOT2B）。要約の `screener` は `NOT_REQUESTED` の節だけ |
| `--screener-policy-id` | 正確な policy_id |
| `--screener-policy-key` ＋ `--screener-policy-version`（int） | 正確な (鍵, 版) |
| 両方 ・片方だけ ・形の違う id ・int でない版 | `SCREENER_SELECTOR_INVALID`（PilotError。network の前） |
| 選択子あり ・`--acquired-at` なし | `SCREENER_REQUIRES_ACQUIRED_AT`（PILOT2A の経路には真の authority の瞬間が無い） |

既定 ・latest ・current ・active ・自動の発見 ・最高の版 ・最新の reviewed_at の選択は無い。方針は `<data_root>/screener_intelligence/
screener_policy_authority.jsonl`（caller の private root。repo ・config.yaml の path は無い）からだけ読み、自動で作らない。

## 2. 実行の順序

1. 入力の検証 → `acquired_at` の解析 → 選択子の解析。
2. **network の前の fail closed**: `open_verified_store(root)`（B3 の integrity）→ `resolve_policy`。無い ・破損は
   `SCREENER_POLICY_UNAVAILABLE`（detail ＝ `<failure>:<code>`。要約は書かず request は出さない）。
3. 既存の chain: ID1 の再導出 → 判断 → ID2 → identity の確認 → fins（request は PILOT2B と同じ 1 回）→ ACQ0 → EXE → manifest → F1 → A3-RA。
4. 発行体ごとに chain の後: `EvaluationContext` ＋ `EvaluationInputs` → 凍結 B4A `evaluate_selected_policy`（B3 read-only → 凍結 B2）→
   `project_safe_summary` → `screener.issuers[]`（acquisition_authority の issuers と同じ順）。
5. 要約の状態 → `screener.state == FAILED` なら `PILOT_FAILED` → `safe_summary.json`。

runner は期間の選択 ・式 ・authority の写像 ・ALL_OF ・比較を複製しない。B2 を直接呼ばない。

## 3. EvaluationContext の構築

| 軸 | 値 |
|---|---|
| `subject_id` | identity の確認で解決した発行体（`handoff.issuer_id`） |
| `evaluation_as_of` ＝ `identity_valid_at` | `acquired_at`（PILOT2B の取得の瞬間。A3-RA の `authority_as_of` ・`identity_valid_at` と同じ軸。時計は無い） |
| `authority_mode` | 解決した方針の mode（B4A は方針 ・文脈の mode の一致を要求する） |
| `policy_id` | 解決した方針の policy_id |

STRICT_PIT の方針は STRICT の意味のまま（cutoff ＝ acquired_at。coverage の宣言が無い private root では `NOT_EVALUABLE / OUTSIDE_COVERAGE`
で、coverage を捏造しない）。RETROSPECTIVE の方針は保持 ・manifest ・A1R の修正の像を渡す。

## 4. 安全な要約の `screener` の節

```
"screener": {"schema": "p8_pilot2b_screener_section:0.1.0",
             "state": "NOT_REQUESTED" | "REQUESTED" | "FAILED",
             "selector_kind": null | "POLICY_ID" | "KEY_VERSION",
             "issuers": [{"summary": <SafeScreenerSummary.as_dict()> | null, "failure_code": ""}],
             "failure_code": ""}
```

`summary` は凍結 B4A の投影そのもの（第二の schema は作らない）。節が足すのは orchestration の状態だけ。`policy_key` ・選択子の値 ・主語 ・値 ・
閾値 ・著者 ・意図 ・参照 ・path は無い。既存の `SUMMARY_SCHEMA`（`p8_pilot2_safe_summary:0.1.0`）は上げない（P8-OBS-83）。

監督の決定: criterion_id（P8-OBS-78）・正確な evaluation_as_of（P8-OBS-79）はこの **private ・local** の要約でだけ許される。公開の出力の承認ではない。

## 5. 実行の状態の意味（結果 ≠ 操作）

| 場合 | runner の状態 | `screener` |
|---|---|---|
| infrastructure 成功 ＋ MATCH ／ NO_MATCH ／ NOT_EVALUABLE ／ HOLD ／ AUTHORITY_FAILURE（結果の状態） | 既存の判定のまま（PASS ／ HOLD ／ PARTIAL） | `REQUESTED` ＋ 投影 |
| 選択子の誤り ・方針なし ・store の破損（network の前） | PilotError（CLI は exit 2。要約を書かない） | — |
| chain の後の orchestration の失敗（B4A の型つきの失敗 ・文脈の構築の失敗） | `PILOT_FAILED` | `FAILED` ＋ `failure_code`（B4A の failure） |

PILOT_PASS を MATCH で定義し直さない。NO_MATCH ・NOT_EVALUABLE は会社の評価ではなく、結果の状態の語彙だけ（良い ・悪い ・推奨の語は無い）。

## 6. resume ・idempotency

- Screener は derived で保存しない。結果の journal ・結び付きの file は作らない（`pilot2/` の file の集合は不変）。
- B3 store は read-only。exact replay は同じ投影を返し、B3 ・ACQ0 ・manifest ・保持の journal の行は増えない。
- 選択子は resume に結び付けない（P8-OBS-84）。別の方針 ・別の `acquired_at` での再実行は、同じ authority の入力の上の別の derived な評価。

## 7. 合成の検証（`tests/intelligence/test_screener_pilot2b_screener_runner.py`）

| 場合 | 証拠 |
|---|---|
| A 選択子なし | 要約は legacy の欄 ＋ `screener` NOT_REQUESTED だけ。PILOT2A の経路も同じ。file の集合は不変 |
| B policy_id | 実の凍結 chain → B4A → MATCH（件数 (2,1,1) ／ (2,2,1)、evaluation_as_of ＝ acquired_at） |
| C 鍵 ・版 | 同じ投影。v3 は別の policy_ref |
| D NO_MATCH | runner は PILOT_PASS のまま。推奨の語なし |
| E NOT_EVALUABLE | STRICT の方針 → OUTSIDE_COVERAGE（捏造なし）。PILOT_PASS のまま |
| F 方針なし | network の前の PilotError（request 0 ・要約なし ・予算は prepare の 1 だけ） |
| G store の破損 | 同上。修復しない |
| H orchestration の失敗 | `FAILED` ＋ `PILOT_FAILED`。chain は無傷。replay で回復 |
| I replay | 投影は同じ。authority の行は増えない。選択子なしに戻せる |
| J 漏れ | sentinel（値 ・閾値 ・主語 ・著者 ・意図 ・参照 ・credential ・path）なし |
| K 凍結の PILOT2A ・PILOT2B の test | green（変更なし） |
| L ・M 予算 ・network | transport の呼び出し ・request の増分は Screener で変わらない |

## 8. 境界（guard）

- runtime の追加は無い（runner の狭い再開だけ）。B4B guard: runner 以外の全 runtime ・test ・文書は P8_B4A anchor と byte 一致、runner の shape の差は
  `B4B_RUNNER_DELTA`（新しい定数 ・4 つの import ・`_screener_*` の 4 関数 ・`execute` ・`_parser` ・`main`）だけ、chain ・指標 ・判定の関数は不変。
- runner の import: B4A ・B2 の `EvaluationInputs` ・B1 の `EvaluationContext` だけ（B3 の store ・B2 の `evaluate_policy` は無い）。
- 新しい J-Quants の endpoint ・network の挙動 ・方針の既定 ・順位の語彙は無い。

## 9. 観察（監督への報告。変更はしない）

- P8-OBS-83: `SUMMARY_SCHEMA` は上げなかった（追加の 1 節だけで既存の欄は不変。PILOT2B guard が `assign SUMMARY_SCHEMA` を pin する）。
  節は自分の schema `p8_pilot2b_screener_section:0.1.0` を持つ。
- P8-OBS-84: 選択子は resume に結び付けない。Screener は derived で、同じ authority の入力に対して決定論なので、方針の変更は「新しい derived な
  評価」であり拒否の対象ではない（取得の resume の結び付き `acquisition_state.json` は不変）。
- P8-OBS-85: Screener の **結果の状態** は top-level の PILOT の状態に影響しない。**orchestration の失敗**だけが `PILOT_FAILED`（fail closed）。
  network の前に検出できる失敗（選択子 ・方針なし ・store の破損）は要約を書かずに止める。
- P8-OBS-86: B4B は新しい公開 ・terms の面を作らない（private ・local の要約に投影の metadata を足すだけ。Morning Brief ・Pages ・公開の
  出力 ・LLM への経路は無い）。実の検証は別の承認の段。
- P8-OBS-87: 複数の発行体（MAX_TARGET_CODES ＝ 3）では `screener.issuers` は acquisition_authority の issuers と同じ順の位置で並ぶ
  （主語の id は無い）。複数発行体の screening ・順位は対象外。

## 10. 次の段（開始しない）

B4B の凍結の後、監督の承認の下で Windows の実 data の検証（実の方針は人が private root に書く。本 gate は作らない）。
