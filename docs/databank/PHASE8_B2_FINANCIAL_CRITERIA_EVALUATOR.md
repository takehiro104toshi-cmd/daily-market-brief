# PHASE 8 / P8-B2 — FINANCIAL CRITERIA EVALUATOR（財務の基準の決定論の評価器）

凍結 P8-B1 の意味の model（`Criterion` ・`CriteriaPolicy` ・`EvaluationContext` ・`CriterionResult` ・`ScreenerResult`）の上に、
**財務の基準の評価だけ**を足す gate。答える問いは「この発行体は、名前と版のある人が書いた財務の方針を、明示の authority mode と評価の文脈の下で
満たすか」の 1 つ。良い会社か ・買うべきか ・魅力 ・最良 ・順位 ・期待 return ・watchlist ・portfolio ・Theme は答えない。方針の保存（B3）・
Theme の exposure（B6）・security への投影（B7）・配線 ・実 request ・LLM は無い。

- 基準: P8-B1 `a5df74ccce2153a088dab0b4f193931a12d84f9d`（凍結。runtime 44）。full pytest の基準 6349 passed ／ 2 skipped。
- 本書は会社名 ・code ・実の閾値 ・実の値を載せない。test の閾値は評価の検証のための合成の値で、投資の方針ではない。
- 本 gate でも実 J-Quants request ・private root の参照 ・journal の変更 ・公開の出力は無い。

---

## 0. 入口と凍結の層

| 層 | 使う入口（public だけ） | 変更 |
|---|---|---|
| 凍結 B1 model | `Criterion` ・`CriteriaPolicy` ・`EvaluationContext` ・`CriterionResult` ・`ScreenerResult` ・`PeriodRule` ・`CriterionOperator` ・`CriterionState` ・`ScreenerState` ・`ScreenerAuthorityMode` ・`ScreenerDimension` ・`CriteriaComposition` ・`completeness_of` ・`SCREENER_RULES_VERSION` | なし（byte 一致） |
| 凍結 A3 STRICT | `fundamental_metrics.operating_margin` ・`fundamental_metrics.revenue_growth` ・`fundamental_metrics_extended.net_margin` ・`fundamental_metrics_extended.roa_point_in_time`（cutoff ＝ `evaluation_as_of`） | なし |
| 凍結 A3-RA | `retrospective_metric_resolver.resolve_retrospective_metric`（`authority_as_of` ＝ `evaluation_as_of`、`identity_valid_at` ＝ 文脈の値、holdings ・manifests ・corrections ・semantics は明示の像） | なし |
| 凍結 model | `metric_model.MetricKind / MetricResult / MetricStatus / ReasonCode`、`observation_model.FundamentalActual / ObservationHistory / PeriodBasis / ReportingPeriod`、`RetrospectiveMetricResult / RetrospectiveMetricStatus` | なし |

private helper（`_resolve_leg` ・`_Leg` ・`_period_relation` …）は使わない。runner `jquants_pilot2_local` は runtime から import しない（test だけが
一致の証明のために import する）。式 ・保持の解決 ・identity の解決の複製は無い。

## 1. module（`src/intelligence/screener_intelligence/screener_evaluator.py`）

| 名前 | 役割 |
|---|---|
| `EvaluationInputs(history, semantics, holdings=None, manifests=None, corrections=None)` | runtime の像（読むだけ）。STRICT は history ・semantics、RETROSPECTIVE はさらに保持 ・manifest ・A1R の修正の authority。意味の文脈は凍結 `EvaluationContext` のまま |
| `evaluate_policy(policy, context, inputs) -> ScreenerResult` | 方針の全基準を順に評価（短絡しない）し、ALL_OF で集約。完全性は凍結 `completeness_of` |
| `evaluate_criterion(criterion, context, inputs) -> CriterionResult` | 1 基準の評価（§2〜§5） |
| `visible_periods(criterion, context, inputs)` | authority に見える期間（period_end → 期間の集合） |
| `select_target(periods, rule) -> (period | None, code)` | 単一の期間の規則の選択 |
| `compare(operator, value, threshold, threshold_high) -> bool` | Decimal だけの比較 |
| `aggregate(states) -> ScreenerState` | 固定の優先の集約 |
| `ScreenerEvaluationError(code, detail)` | 契約の違反だけ（§6） |
| 定数 | `AGGREGATION_PRECEDENCE` ・`COMPARISON_RULE` ・`SUPPORTED_TARGET_BASES` ・`PERIOD_RELATION_CODES` ・`EVALUATOR_RULES_VERSION = "p8_screener_evaluator:0.1.0"` |

結果の `rules_version` は凍結 B1 の `SCREENER_RULES_VERSION`（結果の型の語彙）。評価器の版は module の定数で、結果の型は変えない。

## 2. authority mode（2 つ ・fallback なし）

| 条件 | 結果 |
|---|---|
| `criterion.authority_mode is context.authority_mode` でない | `CriterionState.AUTHORITY_FAILURE`、reason `POLICY_AUTHORITY_MODE_MISMATCH`、上流の呼び出しなし（例外ではなく結果）。期間 ・値 ・provenance は空 |
| `STRICT_PIT` | 凍結 A3 の public の 4 関数。cutoff ＝ `evaluation_as_of`。保持 ・manifest は読まない |
| `RETROSPECTIVE_PROVIDER_AUTHORITY` | 凍結 A3-RA。`holdings` ・`manifests` ・`corrections` の像が無ければ `ScreenerEvaluationError("RETROSPECTIVE_INPUTS_REQUIRED")`（契約の違反） |

`ScreenerResult.authority_mode` は文脈の mode。B1 の `CriteriaPolicy` は全基準が方針の mode と一致することを保証するので、不一致は「文脈 ≠ 方針」の時に
全基準に同じ失敗として現れる（集約は AUTHORITY_FAILURE ・完全性 NONE）。

## 3. target の期間の選択（authority に見える期間だけ ・意味で選ぶ）

| mode | authority に見える期間 |
|---|---|
| RETROSPECTIVE | `holdings.for_subject(subject)` の record のうち `holdings_as_of <= evaluation_as_of` のもの × `manifests.by_acquisition(acquisition_ref)` の **CANONICAL** entry（同じ period_end ・同じ statement_basis）。manifest が無い record は飛ばす（authority の失敗は A3-RA が報告する）。HELD ・UNSUPPORTED の行は期間を作らない |
| STRICT | `history.records` の `FundamentalActual`（同じ subject ・同じ statement_basis）のうち `knowledge.certain_by <= evaluation_as_of` のものの期間（cutoff までに確かに知られた期間だけ。2026-05 の知識は 2025-06 の評価に見えない） |

| `PeriodRule` | 選択 |
|---|---|
| `NEWEST_SUPPORTED_FY_OR_CUMULATIVE`（利益率） | period_end の降順で最初の、FISCAL_YEAR ／ CUMULATIVE_YEAR_TO_DATE の候補 |
| `NEWEST_FY`（ROA） | period_end の降順で最初の FISCAL_YEAR の候補 |
| `NEWEST_WITH_COMPARABLE_PRIOR`（売上成長率） | target を降順に見て、prior（より古い period_end ・支える種類が 1 つ）を降順に試し、凍結 A3 の期間の関係の code（`PERIOD_BASIS_UNSUPPORTED` ・`FISCAL_YEAR_IRREGULAR` ・`PERIOD_BASIS_MISMATCH` ・`PERIOD_QUARTER_DIFFERS` ・`PERIOD_NOT_ADJACENT`）が内側の理由に無い最初の対を採る |

| 失敗 | 結果 |
|---|---|
| 支える候補が無い | `NOT_EVALUABLE / TARGET_UNAVAILABLE` |
| 同じ period_end に支える期間が 2 つ以上（例: 同じ末日の別の年度） | `NOT_EVALUABLE / TARGET_AMBIGUOUS`（任意に選ばない。NEWEST_FY でも同じ） |
| 売上成長率に comparable な prior が無い | `NOT_EVALUABLE / NO_COMPARABLE_PRIOR_PERIOD` |

**PILOT2B との等価**: RETROSPECTIVE の `visible_periods` は runner の `_target_candidates`（保持 record × manifest の CANONICAL の期間）、`select_target`
は `_select_target`、売上成長率の対の探索は `_revenue_growth_entry` と同じ規則。test `test_f_*` が同じ root で両者の出力の一致 ・A3-RA の呼び出しの順
（利益率 → 最新の累計、ROA → 年度、成長率 → 最初の comparable な対）を pin する。差は 2 つだけ: (a) statement_basis は基準の値（runner は連結だけ）、
(b) 候補なしの code は B1 の語彙 `TARGET_UNAVAILABLE`（runner は `NO_SUPPORTED_TARGET`）。journal の物理の位置 ・provider の行の順 ・file の順は使わない。

## 4. 状態の写像（真に写す ・閉じた表）

| A3-RA の外側 | B2 |
|---|---|
| `VALUE` | Decimal の比較 → `MATCH` ／ `NO_MATCH` |
| `SEMANTIC_HOLD` | `HOLD` |
| `INSUFFICIENT_DATA` ・`INSUFFICIENT_TIME_PRECISION` ・`NOT_COMPARABLE` ・`UNDEFINED` | `NOT_EVALUABLE` |
| `AUTHORITY_FAILURE` ・`AMBIGUOUS_AUTHORITY` ・`INVALID_INPUT` | `AUTHORITY_FAILURE` |

| STRICT `MetricStatus` | B2 |
|---|---|
| `VALUE` | 比較 → `MATCH` ／ `NO_MATCH` |
| `INSUFFICIENT_DATA`（`OUTSIDE_COVERAGE` ・`BEFORE_COVERAGE` ・`NOT_FOUND` ・`NOT_YET_KNOWN` …）・`INSUFFICIENT_TIME_PRECISION` ・`NOT_COMPARABLE` ・`UNDEFINED` | `NOT_EVALUABLE` |
| `INVALID_INPUT` | `AUTHORITY_FAILURE` |

STRICT は coverage を捏造しない: coverage の無い history は `OUTSIDE_COVERAGE` → `NOT_EVALUABLE`。両表は test で「status の集合 ＝ 表の鍵 ＋ VALUE」として閉じていることを pin する。
`VALUE` で値が無いことは契約の違反（`VALUE_WITHOUT_OBSERVED_VALUE`）。

## 5. 比較 ・結果 ・集約

- 比較は `Decimal(value)` と `Decimal(threshold)` だけ。`LT` ・`LE` ・`GT` ・`GE`、`BETWEEN` は `threshold <= value <= threshold_high`（両端を含む。B1 の定義）。
  丸め ・quantize ・epsilon ・tolerance ・距離 ・点数 ・float は無い（module に `BinOp` ・`float` ・`round` が無いことを guard）。
- `CriterionResult`: `has_value` ・`observed_value` は MATCH ／ NO_MATCH の時だけ。`target_period` ・`comparison_period` は選んだ期間（選べなければ None）。
  `observation_ids` は A3-RA の `observation_ids`（STRICT は `MetricResult.input_record_ids`）、`coverage_epoch_ids` ・`manifest_refs` は A3-RA の値（STRICT は空）、
  `inner_metric_status` は内側の `MetricResult.status`（外側だけの失敗は None）、`reason_codes` は内側の理由 `LEG:CODE` ＋ A3-RA の diagnostics ＋ 評価器の code
  の整列 ・重複なし。
- 集約（`ALL_OF` だけ）: `AUTHORITY_FAILURE` ＞ `HOLD` ＞ `NO_MATCH` ＞ `NOT_EVALUABLE` ＞ 全基準 `MATCH` の時だけ `MATCH`。全基準を評価する（NO_MATCH が先でも
  止まらない）。順序は方針の基準の順。完全性は凍結 `completeness_of`（COMPLETE ／ PARTIAL ／ NONE）。順位 ・score ・重み ・並べ替えは無い。

## 6. 例外と結果の境界

| 種類 | 扱い |
|---|---|
| authority の失敗 ・保留 ・不足 ・期間なし ・曖昧 ・mode の不一致 | 型つきの結果（§2〜§4） |
| 契約の違反 | `ScreenerEvaluationError(code)`: `INVALID_POLICY` ・`INVALID_CONTEXT` ・`INVALID_CRITERION` ・`INVALID_INPUTS` ・`INVALID_HISTORY` ・`INVALID_SEMANTICS_LOOKUP` ・`POLICY_CONTEXT_MISMATCH`（`context.policy_id != policy.policy_id`）・`RETROSPECTIVE_INPUTS_REQUIRED` ・`COMPOSITION_UNSUPPORTED` ・`DIMENSION_NOT_EVALUABLE` ・`BETWEEN_REQUIRES_TWO_THRESHOLDS` ・`VALUE_WITHOUT_OBSERVED_VALUE` ・`INVALID_STATES` |

広い `except` は無い。上流の例外（`ObservationModelError` など）はそのまま伝わる。

## 7. 境界（guard）

- 新規 runtime は `screener_evaluator.py` の 1 つ（P8_B1 anchor と byte 一致の凍結 runtime 43 ・Phase 8 の test ・先行の文書）。registry: `P8_B1` ・`PHASE8_B2_RUNTIME`。
- import は sanctioned の名前だけ（public。`_` 始まりなし）。`jquants_pilot2_local` ・P6 ・P7 ・Theme ・Narrative ・store の書き込み ・clock ・IO ・network ・LLM は無い。
- `retrospective_metric` ・`screener_criteria` の消費は B2 だけ（他の凍結の層は知らない）。
- 名前の語に DERIVED_TOKENS（candidate ・latest ・score ・rank …）は無い（Screener の層の語 criterion ・criteria を除く）。

## 8. 観察（監督への報告。変更はしない）

- P8-OBS-69: 保留（HELD）・UNSUPPORTED の行は manifest の CANONICAL でないので authority に見える期間を作らず、その区分の基準は `TARGET_UNAVAILABLE` になる。
  A3-RA の `SEMANTIC_HOLD` が B2 の `HOLD` に写るのは、CANONICAL の期間を選べて脚が保留の時（test は選択を固定して写像を証明する）。
- P8-OBS-70: STRICT の harness（A3 の合成の世界）は純利益 ・総資産を持たないため、STRICT の E2E は営業利益率 ・売上成長率で VALUE、純利益率 ・ROA は
  `NOT_EVALUABLE / NOT_FOUND`。これは data の事実の真の写しで、評価器の欠陥ではない。
- P8-OBS-71: runner の候補なしの code `NO_SUPPORTED_TARGET` は B1 の語彙に無いため、B2 は `TARGET_UNAVAILABLE` を使う（意味は同じ）。runner は変えない。

## 9. 次の gate（開始しない）

P8-B3（方針の private authority store）。本 gate は保存 ・読み出し ・配線 ・security の投影 ・Theme ・公開の出力を含まない。
