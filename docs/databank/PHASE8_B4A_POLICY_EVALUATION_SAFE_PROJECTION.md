# PHASE 8 / P8-B4A — POLICY-TO-EVALUATOR INTEGRATION + SAFE RESULT PROJECTION

凍結の 3 層（B3 の人が審査した方針の authority → B1 の `CriteriaPolicy` → B2 の決定論の評価器）を、合成だけの決定論の統合でつなぎ、private の
`ScreenerResult` から **metadata ・状態 ・件数だけ** の安全な投影を作る gate。証明するのは「明示に選んだ方針の authority を、正確に解決 ・検証 ・
評価 ・安全に投影できる」ことで、暗黙の方針の選択 ・順位 ・推奨 ・provider の値の漏れ ・Git の中の実の閾値 ・runner との結合は持ち込まない。

- 基準: P8-B3 `6dbea7e0aad3fe7db20689e173c08829ef198155`（凍結。runtime 47）。full pytest の基準 6450 passed ／ 2 skipped。
- 本書 ・CHANGELOG ・test ・source は実の閾値 ・実の方針 ・会社名 ・code を載せない。例と test の値は明らかに合成の値。
- PILOT2B runner ・J-Quants ・private の pilot root ・Theme ・UniverseSpec ・security への投影 ・B4B は触れない。

---

## 0. 凍結の入力（変更なし）

| 層 | 使う入口 |
|---|---|
| B1 `screener_criteria_model` | `CriteriaPolicy` ・`EvaluationContext` ・`ScreenerResult` ・`CriterionResult` ・状態の enum |
| B2 `screener_evaluator` | `evaluate_policy` ・`EvaluationInputs` ・`ScreenerEvaluationError` |
| B3 `screener_policy_authority_model` ／ `_store` | `PolicyAuthorityRecord` ・`HUMAN_REVIEWED_SCREENING_POLICY` ・`PolicyAuthorityStore.validate / open(read_only) / get_by_policy_id / get_by_key_version` |

## 1. orchestration（`screener_policy_evaluation.py`）

| 名前 | 意味 |
|---|---|
| `PolicySelector(policy_id=None, policy_key=None, version=None)` | 正確な選択子。`policy_id` か `(policy_key, version)` のちょうど 1 つ。両方 ・どちらも無し ・形の違う id ・int でない版は `SELECTOR_INVALID` |
| `open_verified_store(data_root)` | `PolicyAuthorityStore.validate` → OK でなければ `STORE_INTEGRITY_FAILURE`（code は store の失敗 code ・行番号）→ read-only で開く |
| `resolve_policy(store, selector)` | 正確な解決だけ。無ければ `POLICY_NOT_FOUND` ／ `KEY_VERSION_NOT_FOUND`。authority の分類は `HUMAN_REVIEWED_SCREENING_POLICY` の完全一致（違えば `AUTHORITY_CLASS_MISMATCH`）。record_id ＝ policy_id の再確認 |
| `evaluate_selected_policy(data_root, selector, context, inputs) -> PolicyEvaluationOutcome` | store → 方針 → `context.policy_id` ＝ 解決した policy_id（違えば `CONTEXT_POLICY_MISMATCH`）→ 方針の mode ＝ 文脈の mode（違えば `AUTHORITY_MODE_MISMATCH`）→ 凍結 B2 `evaluate_policy`。B2 の契約の違反は `EVALUATOR_CONTRACT_FAILURE` |
| `PolicyEvaluationOutcome(selector, record, result, rules_version)` | 解決した record ・凍結の方針（`.policy`）・private の `ScreenerResult`。保存しない |
| `PolicyEvaluationError(failure: PolicyEvaluationFailure, code, detail)` | 型つきの失敗（下表） |

**選択の規則** `EXPLICIT_POLICY_ID_OR_EXACT_KEY_VERSION_ONLY_NO_AUTOMATIC_SELECTION`: latest ・current ・active ・default ・最高の版 ・最新の
reviewed_at ・自動の発見 ・fallback は無い（source に `list_metadata` ・`sorted` ・`[-1]` ・`[0]` が無いことを test が pin する）。
caller が渡す方針の内容は使わない。store が方針の唯一の源で、B2 に渡る `CriteriaPolicy` は解決した record の `policy` そのもの。

### 失敗（`PolicyEvaluationFailure`）

| failure | いつ |
|---|---|
| `SELECTOR_INVALID` | 選択子の形が正確でない |
| `POLICY_NOT_FOUND` ／ `KEY_VERSION_NOT_FOUND` | 正確に解決できない |
| `STORE_INTEGRITY_FAILURE` | `validate` が OK でない（欠落 ・破損 ・偽造 ・重複。code ・行番号を持つ） |
| `AUTHORITY_CORRUPTION` | validate と open の間の変化 ・record_id ≠ policy_id |
| `AUTHORITY_CLASS_MISMATCH` | 分類が `HUMAN_REVIEWED_SCREENING_POLICY` でない |
| `CONTEXT_POLICY_MISMATCH` | 文脈の policy_id が解決した方針と違う |
| `AUTHORITY_MODE_MISMATCH` | 方針の mode と文脈の mode が違う（B2 を呼ぶ前に型つきで止める。B2 単独では truthful な AUTHORITY_FAILURE の結果） |
| `EVALUATOR_CONTRACT_FAILURE` | 凍結 B2 の `ScreenerEvaluationError`（例: RETROSPECTIVE の像の欠落） |
| `INVALID_INPUT` | 型違い ・data_root なし |

store の破損は `NOT_EVALUABLE` に潰さない（authority の破損は市場 data の欠損ではない）。広い `except` は無い。

## 2. 安全な投影（`screener_result_summary.py`）

| 型 | 欄 |
|---|---|
| `SafeScreenerSummary` | `policy_ref`（凍結 B1 の policy_id）・`policy_version` ・`authority_mode` ・`state`（`ScreenerState`）・`completeness`（`DataCompleteness`）・`criterion_count` ・`criteria` ・`evaluation_as_of`（UTC ISO）・`rules_version` ・`schema_version` ・`summary_class` |
| `SafeCriterionSummary` | `criterion_id` ・`metric` ・`state`（`CriterionState`）・`has_value` ・`reason_codes` ・`authority_mode` ・`inner_metric_status` ・`observation_id_count` ・`coverage_epoch_ref_count` ・`manifest_ref_count` |

`as_dict()` は上の欄だけ（＋ `match_meaning = ISSUER_SATISFIED_EVERY_CRITERION_OF_THE_EXPLICITLY_SELECTED_POLICY`）。`canonical_json()` は
sort_keys ・区切りなし（決定論）。`summary_class = DERIVED_SAFE_PROJECTION_NON_AUTHORITY_NON_PERSISTENT`。private の結果は凍結 B1 の
`DERIVED_NON_AUTHORITY_NON_PERSISTENT` のまま。結果の store ・journal ・watchlist は作らない。

### 構造的に無い欄（`FORBIDDEN_SUMMARY_FIELDS`。test が型の欄 ・dict の鍵 ・直列化の文字列で pin）

observed_value ・threshold ・threshold_high ・operator ・author_ref ・intent ・company ・issuer ・subject_id ・security ・ticker ・code ・
observation_ids ・coverage_epoch_ids ・manifest_refs ・target_period ・comparison_period ・identity_valid_at ・policy_key ・生の方針 ・
threshold_distance ・score ・rank ・rating ・weight ・priority ・attractiveness ・recommendation ・target_price ・expected_return ・path ・data_root。

provenance は件数だけ。主語の identity は無い（1 方針 ・1 主語の投影で、主語は caller の文脈が知っている）。MATCH は状態の語彙だけで、
良い ・魅力 ・推奨 ・買い ・機会 ・勝者 ・上位の語は無い。「MATCH の基準の数」は作らない（`criterion_count` は構造の件数）。

### 露出の判断（privacy の根拠）

| 欄 | 判断 |
|---|---|
| `policy_ref` ＝ policy_id | 露出する。B1 の identity payload（鍵 ・版 ・著者 ・審査の瞬間 ・意図 ・構成 ・mode ・criterion_ids）の sha 内容 address で、閾値 ・値 ・主語を含まず逆算できない不透明の参照。B3 の正確な選択子として使える |
| `criterion_id` | 露出する。基準の identity payload（閾値を含む）の内容 address。hash は不透明で閾値を復元できない（P8-OBS-78 に残る注意） |
| `evaluation_as_of` | 露出する。評価の瞬間（取得の瞬間）で、値 ・主語を含まない。監督の検証に要る |
| `reason_codes` | 露出する。凍結 B1 の正規表現 `^[A-Z][A-Z0-9_]*(:[A-Za-z0-9_]+)*$` に合う閉じた語彙で、`.` ・空白を持てず数値を運べない |
| `inner_metric_status` ・`has_value` | 露出する。状態だけ |
| 件数 | 露出する。provenance の参照の個数（参照そのものは無い） |

## 3. 合成の E2E（test `test_screener_policy_evaluation.py`）

合成の `CriteriaPolicy`（sentinel の意図 ・著者）→ `PolicyAuthorityRecord` → private B3 store → 別の read-only の open → 正確な解決 → 合成の
保持 ・manifest ・観測（F1 harness）→ 凍結 B2（実の凍結 A3-RA の経路）→ private `ScreenerResult` → 安全な投影。

| 場合 | 結果 |
|---|---|
| A. MATCH | 営業利益率 GE ・売上成長率 BETWEEN が合成の値で真。private は値を持ち、投影は MATCH ・COMPLETE ・件数 (2,1,1)/(2,2,2) |
| B. NO_MATCH | 純利益率 GT が偽 |
| C. NOT_EVALUABLE | 保持が見えない瞬間（`TARGET_UNAVAILABLE`。件数 0） |
| D. 選択の失敗 | 無い policy_id ・無い版 ・別の鍵 |
| E. authority の破損 | 不正な行 ・切断 ・物理の重複 ・偽造の policy_id ・欠落 → `STORE_INTEGRITY_FAILURE`（B2 は呼ばれない） |

leak test: 主語 id ・会社名 ・code ・観測値 ・閾値 ・著者 ・意図 ・観測 id ・epoch の参照 ・manifest の参照 ・credential ・path の sentinel が投影の直列化に
現れない。禁止の欄名は型 ・dict の鍵に無い。

## 4. 境界

- 新規 runtime は 2 module（P8_B3 anchor と byte 一致の凍結 runtime 47 ・Phase 8 の test ・先行の文書）。registry: `P8_B3` ・`PHASE8_B4A_RUNTIME`。
- import は sanctioned の名前だけ。runner ・J-Quants ・P5〜P7 ・Theme ・store の書き込み ・IO ・clock は無い（orchestration は B3 store を read-only で
  開くだけ）。算術 ・`sorted` ・`max/min/sum` は無い。
- `screener_criteria` ・`screener_evaluator` ・`policy_authority` の消費は B4A だけ（凍結 B1 の test の消費の行は B4A guard が pin）。

## 5. 観察（監督への報告。変更はしない）

- P8-OBS-77: `policy_id` の露出は安全と判断した（内容 address ・閾値なし ・逆算不可）。ただし同じ鍵 ・版 ・著者 ・意図の方針を知る者は
  policy_id を再計算して一致を確かめられる（意図した性質。authority の参照として使う）。
- P8-OBS-78: `criterion_id` は閾値を含む payload の hash。閾値の候補の集合が小さい場合（例: 0.05 刻み）に辞書攻撃で閾値を推定できる理論上の可能性が
  ある。metadata だけの private の投影では許容し、公開の出力（B4B 以降）に出す時は再検討を推奨する。
- P8-OBS-79: `evaluation_as_of` は取得の瞬間を示し、private の pilot の実行時刻と結び付く。値 ・主語は含まないので露出するが、公開の出力では
  日付への丸めを検討する。
- P8-OBS-80: `reason_codes` は B1 の正規表現で閉じ、provider の値を運べない。A3-RA の diagnostics は `LEG:STATUS:CODE` の形で同じ制約に合う。
- P8-OBS-81: B2 `CriterionResult` のうち投影に渡してはならない欄: observed_value ・threshold ・threshold_high ・operator（方向だけでも閾値の文脈）・
  target_period ・comparison_period（決算期を示す）・observation_ids ・coverage_epoch_ids ・manifest_refs。`ScreenerResult` の subject_id ・
  identity_valid_at も渡さない。投影はこれらを構造的に持たない。
- P8-OBS-82: §4 の「方針の mode ＝ 文脈の mode を要求」を B2 の前の型つきの失敗にした。B2 単独の truthful な `AUTHORITY_FAILURE /
  POLICY_AUTHORITY_MODE_MISMATCH` は直接の呼び出しで残る。orchestration では文脈の誤りを結果に写さず止める方が fail closed と判断した。

## 6. 次の gate（開始しない）

P8-B4B（1 発行体の private pilot でこの投影を使う）。本 gate は runner ・公開の出力 ・結果の保存を含まない。
