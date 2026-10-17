# PHASE 8 / P8-B5B — MULTI-ISSUER RESULT SET + COMPLETENESS + SAFE PROJECTION

将来の複数発行体の実行器（B5C）が、明示の Universe 全体の screen の結果を表す型を定める **純 ・決定論** の gate。答える問いは
「宣言した Universe のすべての member に何が起きたか」で、「どの発行体が MATCH したか」だけではない。MATCH だけの出力は、財務 data の欠損 ・
identity の未解決 ・取得の失敗 ・予算の延期 ・authority の失敗 ・不適格を隠し、coverage の偏りを作る。

- 基準: P8-B5A `479de19d42a76610085bb56a18d7cd77d8b78742`（凍結。runtime 51）。full pytest の基準 6546 passed ／ 2 skipped。
- 本 gate は model ・集約 ・安全な投影だけ。実行器 ・J-Quants ・取得 ・batch ・継続の台帳 ・identity の bootstrap ・Universe の実行 ・方針の作成 ・
  Theme ・新しい指標 ・Phase 9 ・公開の出力 ・保存は無い。
- 本書 ・test の code ・発行体は合成の値（実の上場物 ・発行体ではない）。

---

## 0. 2 つの粒度（監督の決定を保つ）

| 粒度 | 単位 | 型 |
|---|---|---|
| Universe の member の結果 | provider の上場物 code（B5A の member）ごとに 1 つ | `MemberOutcome` |
| 発行体の screen の結果 | 審査済みの IssuerId ごとに 1 つ | `IssuerResult` |

複数の code が同じ発行体に解けても、発行体の評価は 1 つ（主の上場物は選ばない ・凍結の authority にその概念は無い）。発行体の結果を参照する
member は全結果の集合から派生する（`source_members(issuer_id)`。宣言の順）。identity の解決 ・適格の実行は本 gate に無い。

## 1. member の結果（`MemberOutcomeKind`。閉じた 6 つ）

| 値 | 意味 | 終端 |
|---|---|---|
| `EVALUATED` | 発行体に解け、発行体の評価に結び付いた（`issuer_id` 必須） | ○ |
| `NOT_ELIGIBLE` | D0 の master で適格でない（凍結 LIVE1 の理由の code） | ○ |
| `IDENTITY_UNRESOLVED` | 審査済みの identity に解けない | ○ |
| `ACQUISITION_FAILED` | 取得 ・authority の構築が終端で失敗した | ○ |
| `BUDGET_DEFERRED` | 予算のため後の batch に延ばした | × |
| `NOT_ATTEMPTED` | まだ試みていない | × |

EVALUATED 以外は `issuer_id` を持てず（Screener の状態を装わない）、型つきの理由の code を 1 つ以上要求する（凍結 B1 の code の形 ・整列 ・
重複なし）。追加の状態は採らなかった（P8-OBS-107）。

## 2. 発行体の結果（`IssuerResult`）

`issuer_id`（審査済みの IssuerId）＋ `evaluation`（凍結 B4A の `SafeScreenerSummary`）だけ。状態は凍結 B2 ／ B4A の語彙
（MATCH ／ NO_MATCH ／ HOLD ／ NOT_EVALUABLE ／ AUTHORITY_FAILURE）そのまま。PARTIAL_MATCH ・点数 ・確信 ・魅力 ・順位 ・推奨の状態は無い。
B4A の投影を合成するので、private の全結果も観測値 ・閾値を持たない（policy_ref ・版 ・mode ・評価の瞬間 ・基準ごとの状態 ・理由 ・件数は持つ）。

## 3. 全結果の集合（`ScreenResultSet`。private ・派生 ・保存しない）

| 欄 | 意味 |
|---|---|
| `universe_id` ・`universe_version` ・`universe_members` | 凍結 B5A の Universe の正確な id ・版 ・宣言の member（実行器が `UniverseSpec` から渡す） |
| `policy_id` ・`policy_version` | 明示の B3 の方針 |
| `authority_mode` | 1 つの mode |
| `authority_day` | 単一の authority の日 D0（`date`） |
| `evaluation_as_of` | 1 つの評価の瞬間（aware。D0 の JST の日の中） |
| `member_outcomes` | member ごとの結果（宣言の順） |
| `issuer_results` | 発行体ごとの結果（最初に参照する member の位置の順） |
| `rules_version` ・`authority_class` | `p8_screener_result_set:0.1.0` ・`DERIVED_NON_AUTHORITY_NON_PERSISTENT` |

派生: `execution_completeness` ・`member_outcome_counts` ・`screener_state_counts` ・`data_completeness_counts` ・`match_issuer_ids` ・
`source_members(issuer_id)` ・`screen_result_id` ・`as_dict()`（private の全結果）。組み立ては `assemble_result_set(...)`（member を宣言の順に、
発行体を最初の参照の順に並べ、検査は全結果の集合が行う）。

### 不変条件（fail closed）

宣言の member はちょうど 1 回（欠け `MISSING_MEMBER_OUTCOME` ・余分 `EXTRA_MEMBER_OUTCOME` ・重複 `DUPLICATE_MEMBER_OUTCOME`）・member の順 ＝
宣言の順 ・EVALUATED は存在する発行体の結果をちょうど 1 つ参照（`EVALUATED_MEMBER_WITHOUT_ISSUER_RESULT`）・EVALUATED 以外は発行体を持たない ・
各発行体の結果は 1 つ以上の EVALUATED に参照される（`ORPHAN_ISSUER_RESULT`）・発行体の重複なし ・発行体の順 ＝ 最初の参照の順 ・すべての評価が
同じ方針の id と版（`POLICY_MISMATCH`）・同じ mode（`AUTHORITY_MODE_MISMATCH`）・同じ評価の瞬間（`EVALUATION_INSTANT_MISMATCH`）・評価の瞬間が
D0 の JST の日の中（`EVALUATION_OUTSIDE_AUTHORITY_DAY`）・id ・版 ・code の形。すべての状態が MATCH であることは要求しない。

### 順（非意味）

| 対象 | 規則 |
|---|---|
| member の結果 | `UNIVERSE_DECLARED_ORDER_NON_SEMANTIC`（B5A の宣言の順） |
| 発行体の結果 | `FIRST_REFERENCING_MEMBER_DECLARED_POSITION_NON_SEMANTIC` |
| MATCH の部分集合 | 発行体の結果の順 |

状態 ・満たした基準の数 ・財務の値 ・閾値との距離で並べない（AST の guard: key つきの `sorted` ・`max` ・`min` は無い）。順位 ・魅力 ・確信 ・
優先を意味しない。

## 4. 完全性（実行 ≠ 財務 data）

**実行の完全性**（`EXECUTION_COMPLETENESS_RULE = COMPLETE_IFF_NO_MEMBER_BUDGET_DEFERRED_OR_NOT_ATTEMPTED`）: すべての member が終端の試み
（EVALUATED ・NOT_ELIGIBLE ・IDENTITY_UNRESOLVED ・ACQUISITION_FAILED）に達すれば `COMPLETE`、BUDGET_DEFERRED ・NOT_ATTEMPTED が 1 つでも
あれば `PARTIAL`。NOT_EVALUABLE ・NO_MATCH ・HOLD ・AUTHORITY_FAILURE は発行体が真に試みられた終端の結果なので `COMPLETE` を妨げない。
状態は 2 つで足りる（P8-OBS-110）。

**財務 data の完全性**（件数だけ。点数 ・比率は作らない）: `screener_state_counts`（5 つの状態 ・0 を含む）・`data_completeness_counts`
（凍結 B1 の COMPLETE ／ PARTIAL ／ NONE ・発行体ごと）・`member_outcome_counts`（6 つ ・0 を含む）。

## 5. MATCH の部分集合

`match_issuer_ids` は全結果から派生するだけ（`MATCH_SUBSET_MEANING = ISSUERS_WHOSE_EVALUATION_MATCHED_EVERY_CRITERION_OF_THE_EXPLICIT_POLICY`）。
別の authority ・store ・保存 ・順位 ・上位 ・点数 ・距離は無い。private の全結果の `as_dict()` は全 member ・全発行体の後に部分集合を持つ
（部分集合だけの出力は無い）。

## 6. 安全な投影（`SafeScreenSetSummary`。private ・local。公開の承認ではない）

| 欄 | 内容 |
|---|---|
| `policy_ref` ・`policy_version` | 凍結 B4A の private ・local の判断（P8-OBS-77）と同じ |
| `universe_version` | 版だけ（Universe の id は出さない） |
| `authority_mode` ・`authority_day` | mode と D0（正確な評価の瞬間は出さない） |
| `execution_completeness` | COMPLETE ／ PARTIAL |
| `member_count` ・`issuer_count` | 構造の件数 |
| `member_outcome_counts` ・`screener_state_counts` ・`data_completeness_counts` | 件数 |
| `member_reason_code_counts` ・`evaluation_reason_code_counts` | 閉じた理由の code の件数（例: provider の欄の欠損の code。値は無い） |
| `match_subset_meaning` ・`rules_version` ・`schema_version` ・`summary_class` | 意味と版 |

構造的に無い欄（`FORBIDDEN_SET_SUMMARY_FIELDS`）: issuer_id(s) ・match_issuer_ids ・member_code(s) ・universe_members ・universe_id ・
screen_result_id ・criterion_id ・criteria ・観測値 ・閾値 ・意図 ・著者 ・evaluation_as_of ・観測 id ・epoch ・manifest の参照 ・会社 ・上場物 ・
ticker ・code ・path。member ・発行体ごとの行は写さない（件数だけ）。

**coverage の偏り**: 「評価できた 5 発行体のうち 5 が MATCH」と「100 member のうち 95 が NOT_EVALUABLE で 5 が MATCH」は、member ・発行体の件数 ・
状態の件数 ・data の完全性の件数 ・理由の code の件数で必ず区別される（test が pin）。値 ・閾値を出して解くことはしない。

## 7. 結果の id

`screen_result_id = content_id("p8srs", canonical_json(identity_payload))`。payload は Universe の id ・版 ・member、方針の id ・版、mode、D0、
評価の瞬間（UTC に正規化）、member の結果、発行体の結果（B4A の投影の dict）、規則の版。同じ入力 ・同じ結果 ＝ 同じ id。瞬間の表現の差
（JST ／ UTC）は id に入らない。時計なし ・保存しない。採った理由: P9 が正確な結果を参照できる ・replay の一致を確かめられる。安全な投影には
出さない（P8-OBS-112）。

## 8. P8 → P9 の受け渡し（実装しない）

P8 が言えるのは「Universe U（版）・方針 P（版）・authority mode A ・評価の瞬間 T（D0）の下で、これらの発行体の評価がこれらの型つきの状態を
出した」だけ。P9 は private の `ScreenResultSet`（または `as_dict()`）を明示に read-only で受け取る: `screen_result_id` ・Universe ／ 方針の
id と版 ・mode ・D0 ・T ・全 member の結果 ・全発行体の結果（issuer_id ・凍結 B4A の評価）・件数 ・派生の MATCH の部分集合。P8 は watchlist への
追加 ・調べる順 ・買い ・最良 ・最強 ・最高の確信を言わない。P8 は発行体ごとの状態 ・実行の間の記憶を持たない。

## 9. 境界（guard）

- 新規 runtime は 2 module（他の runtime 51 ・先行の文書 ・B1 の test 以外の Phase 8 の test は P8_B5A anchor と byte 一致）。registry: `P8_B5A` ・
  `PHASE8_B5B_RUNTIME`。
- import は sanctioned の名前だけ（凍結 B1 の状態の enum ・凍結 B4A の `SafeScreenerSummary` ・identity の形 ・`day_start_jst` ・core）。network ・
  旧来 ・P5 ・P6 ／ P7 ・評価器 ・store ・identity の解決 ・適格の実行 ・IO ・時計 ・比率の演算 ・key つきの並べ替えは無い。
- 凍結 B1 の test の消費の行に `screener_result_set` を 1 つ足した（凍結 B1 の import の消費者。B4B ・B5A ・B5B の guard が pin）。

## 10. 観察（監督への報告。変更はしない）

- P8-OBS-107: member の結果の状態は 6 つで足りる。provider の保持の保留（`UNKNOWN_PERIOD_HELD_ROW`）・manifest ・F1 の失敗は
  `ACQUISITION_FAILED` ＋ 理由の code で表す。B4A の orchestration の失敗（方針の store の破損 ・評価器の契約の違反）は member ごとの結果では
  なく run 全体の fail closed（B5C で扱う）。
- P8-OBS-108: Universe の id（`p8uni_`）は member の code の内容 address で、小さい Universe は列挙で推定され得る。安全な投影には版だけを置いた。
- P8-OBS-109: 複数の code → 1 発行体では member の件数（EVALUATED）≥ 発行体の件数。安全な投影はこの差を件数で示し、どの code が束ねられたかは
  示さない。
- P8-OBS-110: 実行の完全性は 2 状態。ACQUISITION_FAILED は終端（再試行しない ・隠れた retry なし）なので COMPLETE を妨げない。再取得は新しい
  run（新しい評価の瞬間）として扱うのが B5C の課題。
- P8-OBS-111: 単一の authority の日は評価の瞬間 ∈ [D0 00:00 JST, D0＋1 日) で強制した。batch が日をまたぐと全結果の集合は構築できない
  （fail closed。I1 は延期のまま）。
- P8-OBS-112: `screen_result_id` は発行体の id を含む payload の hash なので、安全な投影には置かなかった（不要な結び付けを避ける）。
- P8-OBS-113: 安全な投影の `evaluation_reason_code_counts` は凍結 B1 の閉じた理由の語彙（`LEG:CODE` 等）で値を運べない。どの基準の理由かは
  集約で失われる（criterion_id を出さないため。意図した最小化）。
- P8-OBS-114: P9 の受け渡しで曖昧になり得るのは「MATCH の部分集合だけを読む消費者」。P8 は部分集合を全結果の一部としてだけ出し、P9 の契約で
  `execution_completeness` と件数の読み込みを必須にすることを推奨する。

## 11. 次の gate（開始しない）

P8-B5C（複数発行体の private 実行器: 台帳 ・継続 ・発行体の束ね。本 gate の型を出力に使う）。
