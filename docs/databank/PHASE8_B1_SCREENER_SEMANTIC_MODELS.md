# PHASE 8 / P8-B1 — SCREENER SEMANTIC MODELS（Screener v1 の閉じた意味の model）

P8-B0 の設計監査（監督: APPROVED）に基づく最初の Screener の実装 gate。**型と不変条件だけ**で、評価の実行（B2）・方針の保存（B3: private
authority store）・Theme の exposure（B6）・security への投影（B7）は無い。実 request ・private root の参照 ・LLM ・順位 ・推奨 ・score は無い。

- 基準: P8-PILOT2B `6347588001a8531d60414e10dc2f94e306bdb877`（凍結。runtime 43 ・実データの検証 PASS）。full pytest の基準 6325 passed ／ 2 skipped。
- 本書は会社名 ・code ・実の閾値を載せない。test の閾値は model の検証のための合成の値で、投資の方針ではない。

---

## 0. 監督の決定（B0 → B1）

| 決定 | 内容 | B1 の扱い |
|---|---|---|
| P8-OBS-61 | runtime の語彙は `ScreenerResult`（`is_match`）。`candidate` の識別子の禁止は弱めない | 「Candidate」は文書の概念だけ |
| P8-OBS-62 | 人が審査した Theme → 発行体の exposure authority は無い。捏造しない | `ScreenerDimension.THEME_EXPOSURE` は予約の member だけで、基準を構築できない |
| P8-OBS-63 | 方針は PRIVATE AUTHORITY STORE（人が書く ・版つき ・追記専用 ・repo ／ 公開の設定の外） | 保存は B3。B1 は model だけ |
| P8-OBS-64 | UniverseSpec ・複数発行体は延期 | 持たない |
| P8-OBS-65 | `STRICT_PIT` は第一級の真の mode。fallback ・coverage の捏造は無い | mode は 2 つ。方針 ・基準 ・文脈 ・結果が同じ mode を持つ |
| P8-OBS-66 | 期間の規則は Screener の型の契約。PILOT2B の runner から import しない | `PeriodRule` ＋ `METRIC_PERIOD_RULES` |
| B0 からの変更 | `threshold_distance` を置かない（距離 ・大きさ ・score の数の面を作らない） | 結果に距離 ・点数 ・重みの欄は無い（guard） |

## 1. model（`screener_criteria_model.py`）

| 型 | 欄 | 不変条件 |
|---|---|---|
| `Criterion` | dimension ・subject_kind ・metric ・operator ・threshold ・threshold_high ・period_rule ・authority_mode ・statement_basis ・missing_policy ・rules_version | FINANCIAL だけ構築できる ・ISSUER だけ ・凍結 `MetricKind` の 4 つ ・operator は LT ／ LE ／ GT ／ GE ／ BETWEEN ・閾値は文字列だけ受け正準の Decimal に正規化（float ・int ・bool ・NaN ・Infinity ・不正な形は拒む）・BETWEEN だけ 2 つ目の閾値（昇順で異なる）・期間の規則は指標と合う ・欠損の扱いは `NOT_EVALUABLE_IS_NOT_MATCH` の 1 つ |
| `CriteriaPolicy` | policy_key ・version（≥ 1 の int）・author_ref ・reviewed_at（aware）・intent（≤ 500 字 ・禁止の語なし ・credential なし）・criteria（順序つき ・≥ 1 ・重複なし）・authority_mode ・composition（`ALL_OF` だけ）・rules_version | 全基準の authority mode が方針と一致 |
| `EvaluationContext` | subject_id（Issuer）・evaluation_as_of ・identity_valid_at（aware ・≤ evaluation_as_of）・authority_mode ・policy_id ・rules_version | 像（history ・holdings ・manifests ・corrections ・semantics）は B2 の runtime の入力で、意味の文脈には入れない |
| `CriterionResult` | criterion_id ・state ・metric ・operator ・threshold(_high) ・authority_mode ・has_value ・observed_value ・target_period ・comparison_period ・observation_ids ・coverage_epoch_ids ・manifest_refs ・reason_codes ・inner_metric_status | 値は MATCH ／ NO_MATCH の時だけ（`has_value` と一致）・参照は形を検査 ・理由の code は整列 ・`as_dict()` は値を出さず `include_value=True`（private）だけが出す |
| `ScreenerResult` | subject_id ・policy_id ・policy_version ・evaluation_as_of ・identity_valid_at ・authority_mode ・criterion_results ・state ・completeness ・rules_version ・authority_class | `MATCH` ⇔ 全基準が MATCH ・completeness は `completeness_of` と一致 ・authority_class は `DERIVED_NON_AUTHORITY_NON_PERSISTENT` |

語彙: `ScreenerDimension`（FINANCIAL ・THEME_EXPOSURE 予約）・`ScreenerAuthorityMode`（STRICT_PIT ・RETROSPECTIVE_PROVIDER_AUTHORITY。後者は
凍結 A3-RA の `RESOLUTION_MODE` と同じ文字列）・`CriterionOperator` ・`PeriodRule`（NEWEST_SUPPORTED_FY_OR_CUMULATIVE ・NEWEST_FY ・
NEWEST_WITH_COMPARABLE_PRIOR。「latest」は Phase 8 の禁止の識別子の語なので NEWEST）・`MissingDataPolicy` ・`CriteriaComposition` ・
`CriterionState` ・`ScreenerState`（MATCH ・NO_MATCH ・HOLD ・NOT_EVALUABLE ・AUTHORITY_FAILURE）・`DataCompleteness`（COMPLETE ・PARTIAL ・NONE。
数ではない ・基準 ／ 順位の入力にならない）。

指標 ↔ 期間の規則: REVENUE_GROWTH → NEWEST_WITH_COMPARABLE_PRIOR だけ。OPERATING_MARGIN ・NET_MARGIN → NEWEST_SUPPORTED_FY_OR_CUMULATIVE ／
NEWEST_FY。ROA_POINT_IN_TIME → NEWEST_FY だけ。それ以外は `PERIOD_RULE_INCOMPATIBLE_WITH_METRIC`。

## 2. 内容 address ・直列化

- `criterion_id = p8crt_<sha256[:24]>` of canonical JSON of {authority_mode, dimension, metric, missing_policy, operator, period_rule,
  rules_version, schema_version, statement_basis, subject_kind, threshold, threshold_high}（全欄。閾値は正準化後）。
- `policy_id = p8pol_<sha256[:24]>` of {author_ref, authority_mode, composition, criterion_ids（順序つき）, intent, policy_key, reviewed_at（UTC）,
  rules_version, schema_version, version}。人の審査の metadata（著者 ・審査の瞬間）は identity に入る（ID2 の `accepted_at` と同じ扱い: 再審査は
  新しい record）。基準の順序は意味を持つ。
- 結果の直列化（`as_dict`）: 鍵は固定 ・enum は値 ・時刻は UTC ISO ・期間は `ReportingPeriod.as_dict()`。観測値は private の表面だけ。
- 時計の既定 ・naive な時刻 ・float は無い（test ・guard）。

## 3. 状態（B1 は語彙だけ。遷移 ・優先は B2）

基準: MATCH ／ NO_MATCH（値あり）・HOLD（SEMANTIC_HOLD）・NOT_EVALUABLE（欠損 ・coverage ・比較不能 ・未定義 ・target なし）・AUTHORITY_FAILURE。
結果: 同じ 5 つ。B1 の定義の不変条件は「MATCH ⇔ 全基準が MATCH」だけ。B2 の優先の意図: AUTHORITY_FAILURE ＞ HOLD ＞ 確定の NO_MATCH ＞
NOT_EVALUABLE ＞ 全基準 MATCH の時だけ MATCH。

## 4. 順位 ・推奨の無い面（guard）

- 欄: `threshold_distance` ・score ・weight ・rank ・rating ・priority ・attractiveness ・recommendation ・expected_return ・target_price は
  どの型にも無い（`model_field_names` を test ・boundary が検査）。
- module に算術（`BinOp`）・float ・round ・max ・min は無い（AST）。識別子は Phase 8 の派生の語彙（score ・rank ・latest ・candidate 等）を
  含まない（`criterion` ／ `criteria` と予約の `THEME_EXPOSURE` だけ許す）。
- 方針の意図の文は評価 ・推奨の語（buy ・sell ・recommend ・watchlist ・portfolio ・score ・rank ・rating ・best ・推奨 ・注目 ・おすすめ ・有望 ・
  割安 ・上位 ・買い ・売り 等）を拒む。
- `CriteriaComposition` は `ALL_OF` の 1 member、`MissingDataPolicy` は 1 member。

## 5. Theme の将来の境界

`ScreenerDimension.THEME_EXPOSURE` は enum の予約だけ。`CONSTRUCTIBLE_DIMENSIONS == (FINANCIAL,)` で、構築は `DIMENSION_NOT_CONSTRUCTIBLE_IN_V1`。
将来の B6 は、人が審査した exposure の主張の authority（Phase 8 自身。reviewed Theme root を参照）と Phase 6 の read API の認可した adapter を
足してから、この次元の基準（EXISTS）を別の gate で開く。Phase 6 の `InferredExposureLink` は表示の文脈だけ。Phase 7 は使わない。

## 6. 次の gate

P8-B2（評価器: 凍結 A3 ／ A3-RA の入口で脚を解き、ALL_OF と優先を実装 ・provenance）→ P8-B3（private authority store）→ P8-B4（安全な要約 ・runner の
読み出し）→ P8-B5（実データの検証）→ P8-B6（Theme exposure）→ P8-B7（security への投影）。
