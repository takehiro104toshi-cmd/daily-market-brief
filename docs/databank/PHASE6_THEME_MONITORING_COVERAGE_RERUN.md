# PHASE 6 / P6-B6R1-RERUN — COVERAGE-COMPLETENESS REMEDIATION の独立再検証

TEST / AUDIT / DOC ONLY。B6R1 anchor `3620901` の runtime をそのまま検証した。
**runtime（`src/`・`knowledge/`・`config.yaml`・`.github/`・`scripts/`）は変更していない**（`3620901` との diff 0）。

**結論: B6-DEF-1 は CLOSED であることを独立に確認した。** B6R1 は finding の意味・PIT・決定論・zero-write・
authority 分離・review 分離・fail closed のいずれも壊していない。runtime の defect は見つからなかった。

検証の本体は `tests/intelligence/test_theme_monitoring_coverage_rerun.py`（112 tests）。B6R1 の regression matrix
（`test_theme_monitoring_coverage.py`）の helper・world・期待値の定数は使わず、別の fixture と別の構築経路で確かめた。
データはすべて synthetic。書き込みは `tmp_path` のみ。

---

## 1. runtime freeze

| 検査 | 結果 |
|---|---|
| `3620901` からの runtime diff（src / knowledge / config.yaml / .github / scripts、作業木を含む） | **0** |
| B6 freeze `99d45ef` からの runtime diff | `monitoring_adapter.py` / `monitoring_engine.py` / `monitoring_runner.py` の 3 file のみ（B6R1 で承認済み） |
| `monitoring_model.py` / `monitoring_rules.py` / `monitoring_store.py` / ruleset YAML | `99d45ef` と byte 同一 |
| Foundation / B1〜B5 / legacy / config / .github / scripts | 変更なし |
| `99d45ef` / `3620901` の履歴 | どちらも HEAD の祖先（rewrite なし） |

## 2. 依存表（source から再導出）

期待値を写さず、source の AST から導いた。

1. runner の source から「snapshot field ← `observations.<channel>`」の対応を取り出す
   （`arrived_attachment_keys` ← `arrived_attachment_keys`、`semantic_revision_observation_id` ←
   `semantic_revision_observation_ids`、`discovery_outcome_token` ← `discovery_outcome_tokens`）。
2. engine の source で、その field を `if` / `for` の条件で読む分岐の中にある `emit("<condition_id>")` を集める。

| channel | source から導いた依存 condition | 監督指示の期待値 | engine が強制する表 |
|---|---|---|---|
| `semantic_revision_observation_ids` | `ACCEPTED_THEME_SEMANTIC_REVISION` | 一致 | 一致 |
| `arrived_attachment_keys` | `RETIRED_ROOT_RECEIVED_EVIDENCE` | 一致 | 一致 |
| `discovery_outcome_tokens` | `DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL`, `ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT` | 一致 | 一致 |

`arrived_attachment_keys` は `THEME_CONTRADICTION_EVIDENCE_PRESENT` / `THEME_INVALIDATION_EVIDENCE_PRESENT` の
`supporting_refs` にも入るが、発火条件ではなく identity にも入らない（§7 で確認）。source と期待値の不一致は無かった。

## 3. blind spot の独立再現（A〜F）

| 経路 | 構築 |
|---|---|
| engine 経路 | snapshot を手で組み（ROOT_A RETIRED・ROOT_B ACCEPTED・提案 2 件）、adapter / runner を通さずに `evaluate_monitoring` へ渡す。呼び出し側 digest は全 case で同一 |
| runner 経路 | 代表 world を `retired` stage で止め（merge 前）、B6R1 の world と重ならない提案 2 件・撤回済み relation・新規 relation 提案を足した data root。cutoff は ROOT_A ACCEPTED の時点（CA）と RETIRED の時点（CR）の 2 点 |
| 旧 runtime | B6 freeze の `src/` を git から一時展開し、別 process で同じ data root を評価（§7） |

| case | status | unevaluated_conditions | report diagnostics | presence 束縛 | 依存 finding |
|---|---|---|---|---|---|
| A 全 channel 空で供給 | COMPLETE | なし | なし | 3 channel | 出ない（該当なし） |
| B 全 channel 非空で供給 | COMPLETE | なし | なし | 3 channel | cutoff で到達し得るものが出る |
| C 全 channel 省略 | PARTIAL | 依存 4 condition | `OBSERVATION_NOT_SUPPLIED:` ×3 | `none` | 出ない |
| D arrived のみ省略 | PARTIAL | `RETIRED_ROOT_RECEIVED_EVIDENCE` のみ | arrived のみ | 2 channel | 省略 channel の依存だけ出ない |
| E semantic revision のみ省略 | PARTIAL | `ACCEPTED_THEME_SEMANTIC_REVISION` のみ | semantic revision のみ | 2 channel | 同上 |
| F discovery のみ省略 | PARTIAL | discovery の 2 condition のみ | discovery のみ | 2 channel | 同上 |

- 両経路・両 cutoff で上表どおり（過不足なし）。runner 経路では A〜F の run_id・input digest・canonical report が
  すべて異なる。依存しない finding の identity は case に依らず同一。
- engine 経路では、未供給と宣言した channel の値を snapshot に紛れ込ませても依存 condition は発火せず、
  report は紛れ込みが無い場合と byte 同一（多重防御）。
- **旧 runtime での再現**: 同じ data root・同じ cutoff で、B6 freeze の runtime は channel 省略でも
  `COMPLETE`・未評価 0 を返した（B6-DEF-1 を独立に再現）。B6R1 の runtime は `PARTIAL`・依存 4 condition 未評価を返す。
  finding の bytes は両者で同一（未評価が報告されるようになっただけ）。

## 4. 未供給 / 空供給 / 非空供給

`NOT_SUPPLIED ≠ SUPPLIED_EMPTY ≠ SUPPLIED_NONEMPTY` を channel ごとに確認した（他の channel は空で供給して固定）。
3 状態の run_id・input digest・canonical report はすべて異なる。`observation:<channel>` の束縛は未供給で無し、
空供給と非空供給で異なる値。`COMPLETE` かつ未評価ありの report は、どの case でも生じない。

## 5. report 単体での判別

report の canonical 1 行だけ（`MonitoringRunReport.from_dict` で復元しても同じ bytes）から、runner の結果も
runner diagnostics も使わずに次を読めることを A〜F で確認した。

- 評価が不完全か（`status`）
- どの condition が未評価か（`unevaluated_conditions`）
- どの channel が未供給か（`input_digests["observation_channels_supplied"]` と diagnostics の両方で一致）
- どの channel の内容が束縛されたか（`input_digests["observation:<channel>"]`）

runner diagnostics を空にした結果でも読み取りは変わらない。**coverage の正しさは runner diagnostics に依存していない。**

## 6. input digest / run identity

- 同一 cutoff・同一 authority で、coverage が異なる入力は input digest・run_id・canonical report で区別される。
- 同じ意味の入力を別に組み立てて再実行すると、report・finding は byte 同一、run_id も同一。
- channel の mapping 順・列順・列内の重複、scope の順、data root の場所だけが違う場合、report・finding は byte 同一。
- engine は供給状況（presence）を束縛し、内容の束縛は adapter の input digest が担う（run identity の契約どおり。
  engine 経路では呼び出し側 digest が同じなら「全空供給」と「全非空供給」は同じ presence・同じ run_id になる）。

## 7. finding identity の非回帰

- B6 freeze の runtime（B6R1 前）と B6R1 の runtime で、同じ data root・同じ cutoff（CA / CR）・同じ全非空供給の入力は
  **finding の canonical bytes と `finding_ids` が完全一致**し、どちらも `COMPLETE`。全空供給でも finding bytes は一致。
- 旧 runtime の評価は別 process・一時展開した `src/` で行い、import された engine が一時展開側であること、
  coverage の依存表を持たないこと（= B6R1 前であること）を確認した。旧 runtime の run も data root を 1 byte も変えない。
- coverage metadata（presence key・`OBSERVATION_NOT_SUPPLIED`・`observation:`）は finding に入らない。
- 到着 key は contradiction finding の `supporting_refs` に付くため bytes は変わるが、`finding_id` は変わらない。

finding の件数を重要度として扱っていない。

## 8. condition / ruleset の非回帰

- ruleset YAML・`monitoring_rules.py` は B6 freeze と byte 同一。18 condition の id 集合は registry と一致。
- engine の AST を B6 freeze と比べ、変わった top-level 定義は `MonitoringEvaluationInput` / `_Collector` /
  `evaluate_monitoring` / `__all__` のみ、追加は依存表・presence key・`none` の 3 定数のみ。
- 条件判定の関数（`_theme` / `_proposal` / `_relation` / `_relation_proposal` / `_knowledge_drift` / `_authority_failure`）、
  snapshot の型、状態語彙（`ACCEPTED_STATES` / `CLOSED_STATES` / flag）は AST 同一。
- `_Collector` は `withheld` field と `emit` 冒頭の 1 つの guard（`withheld` なら return）だけが増え、`emit` の残りと
  他の method は同一。`MonitoringEvaluationInput` は末尾に `supplied_observation_channels` が増えただけ。

したがって condition_id・category・閾値・salient state・subject・finding の意味は変わっていない。

## 9. PIT

B6D-R1 の PIT suite（6 family matrix を含む）は全 green。加えて本 world で、coverage 入力を前後で同一に固定して
（全非空供給 / 全省略の 2 通り）、次の未来 record が過去 cutoff（CR）の run_id・input digest・status・未評価・
finding bytes・report diagnostics を変えないことを確認した。どの fixture も cutoff 後には効くこと（liveness）も確認した。

| family | 未来 record | liveness |
|---|---|---|
| B3 proposal | cutoff 後の提案（その id の discovery token も観測に含めたまま） | 後の cutoff で proposal digest が変わり、discovery finding が出る |
| B3 decision | cutoff 後の DEFER | 後の cutoff で deferred 滞留 finding が出る |
| B5C relation proposal | cutoff 後の relation 提案 | 後の cutoff で撤回済み relation への新提案 finding が出る |
| B5C relation proposal decision | cutoff 後の REJECT | 後の cutoff で衝突 finding が消える |

## 10. corruption / fail closed

B3 提案 journal への malformed / truncated / blank / non-object / non-canonical / unsupported schema / unknown field /
conflicting duplicate、決定 journal の invalid history（dangling supersedes）、created_at の invalid timestamp、
B5C 決定 journal の invalid history、Foundation observation journal の malformed の 12 種それぞれについて、
arrived（依存が authority と重ならない）と discovery（依存が提案 authority と重なる）の欠落と組み合わせた。

- 全 channel 供給＋破損: `PARTIAL`、未評価あり、`OBSERVATION_NOT_SUPPLIED` なし（黙って健全にならない）。
- 欠落＋破損: `PARTIAL`。未評価 = 破損のみの未評価 ∪ 欠落 channel の依存（**集合として厳密に一致**）。
  report diagnostics = 破損のみの diagnostics ∪ `OBSERVATION_NOT_SUPPLIED:<channel>`。`AUTHORITY_STATE_UNUSABLE` も残る。
- journal は run の前後で byte 同一（自動修復しない）。silent COMPLETE は無い。

## 11. zero-write

A〜F × 2 cutoff と既定 run の前後で data root の全 file（sha256）を比較し、new 0 / deleted 0 / modified 0。
finding・report は保存されない（新規 file 0）。review journal は変わらない（自動 append 0）。
B6R1 で変わった 3 module は書き込み API・authority の append API・builtin `open` を呼ばない。

## 12. review 分離

- channel の欠落は `ReviewItemState` を作らない（ACKNOWLEDGED / DISMISSED / DEFERRED のいずれも）。
- 人間の review state（ACKNOWLEDGED / DISMISSED / DEFERRED）を先に append しても、A〜F の report は byte 同一
  （review は coverage の判定にも report にも入らない）。
- engine / adapter は review の語彙を持たない。runner の review 参照は B6D の read-only lookup のみ。

## 13. authority / RR-3

B6 freeze からの差分で、B6R1 が 3 module に持ち込んだ import は `OBSERVATION_CHANNEL_CONDITIONS` の 1 つだけ、
新しい呼び出しは `all` / `any` / `join` / `update` / `getattr` / `MonitoringObservations` / `_canonical_channel` /
`channel_bindings` だけ（coverage の記帳）。Theme 変更・evidence attach・提案の ACCEPT / REJECT / DEFER・
relation assertion の実行・relation governance・Theme governance・plan 実行・authority append は導入されていない。
RR-3 POLICY LOCK は維持。

## 14. 既定 run の意味（意図した fail closed）

観測 channel を渡さない既定 run は `PARTIAL`（依存 4 condition が未評価）。これは regression ではなく
**意図した fail closed** として test で固定した。既定（`None`）と明示的な全未供給（`MonitoringObservations()`）は
byte 同一の report になる。channel を供給すれば（空でも非空でも）coverage 由来の `PARTIAL` は残らず `COMPLETE`。

## 15. synthetic shadow harness

synthetic data root のみで実行（real-data shadow ではない）。

| 実行 | status | 未評価 | wrote_nothing | replay_identical |
|---|---|---|---|---|
| harness 1 command（既定の観測） | PARTIAL | 依存 4 condition のみ | True | True |
| harness の inventory / describe / replay 判定 ＋ 全 channel 供給 | COMPLETE | なし | True | True |
| 同上 ＋ B5C 決定 journal の invalid history | PARTIAL | `RETRACTED_RELATION_HAS_NEW_PROPOSAL` のみ（authority 由来） | True | True |

harness は knowledge の ruleset（published_at 2026-09-23）を読むため、cutoff は 2026-09-30 を使った
（それより前の cutoff は `FUTURE_VERSION` で fail closed する。これは正しい挙動）。
harness の CLI には観測を渡す option が無いため、供給ありの確認は harness の関数（inventory / describe / replay 判定）
を使って行った。harness は変更していない。

## 16. real-data shadow

**NOT_RUN**。Theme authority はどの環境にも実在しない。real data は作っていない。Windows 側の操作も求めていない。
本 gate の検証はすべて synthetic であり、実データでの結果と同一視しない。

## 17. test の独立性（mutation 検査）

runtime を一時 copy（scratch）へ複製して 1 か所ずつ壊し、本 test file を実行した（repo の runtime は変更していない）。
git を使う test（freeze pin・旧 runtime 比較・AST 比較・履歴）は copy では動かないため除外して数えた。

| mutant | 内容 | 失敗した test |
|---|---|---|
| M1 | engine が未供給 channel を無視する | 48 |
| M2 | 依存 condition を保留するが未評価に入れない | 33 |
| M3 | presence を input digest に束縛しない | 26 |
| M4 | adapter が channel 内容を束縛しない | 18 |
| M5 | runner が観測を adapter へ渡さない | 49 |
| M6 | `emit` の withheld guard を外す | 4 |
| M7 | 供給判定を真偽値に戻す（B6R1 前の判定） | 10 |

7 mutant すべてが検出された。

## 18. 観測事項（non-blocking・B6-DEF-1 の範囲外・runtime は変更していない）

| id | 内容 | 評価 |
|---|---|---|
| B6R1-RERUN-OBS-1 | `EMPTY_MONITORING_SCOPE` は runner diagnostics だけに出る。report では `theme_observations` digest の欠如として間接的にしか分からない | scope は呼び出し側の明示入力で、観測 channel の coverage ではない。提案のみ（将来 gate で report への scope 束縛を検討） |
| B6R1-RERUN-OBS-2 | `GOVERNANCE_EVENTS_NOT_SUPPLIED` も runner diagnostics だけに出る | 必要な場合は lifecycle が `GOVERNANCE_EVENTS_REQUIRED` で fail closed し、report に UNAVAILABLE ＋ 未評価として出る（B6D limitation #6 の既知事項） |
| B6R1-RERUN-OBS-3 | harness の CLI に観測を渡す option が無い | 供給ありの確認は harness の関数で代替（§15）。追加は将来の判断 |
| B6R1-RERUN-OBS-4 | engine は presence のみを束縛し、内容の束縛は呼び出し側の input digest に委ねる | run identity の契約どおり（B6C 以来）。adapter を通さずに評価入力を組む呼び出し側は内容 digest を自ら渡す必要がある |

## 19. 履歴の保持

- B6 completion audit の §1〜§22（closeout 時点の判定）は書き換えられていない。`99d45ef` から消えた行は、
  deadline の表記訂正（「BEFORE P7 ENTRY」）と、元の文言を保ったまま注記を足した行だけである（test で固定）。
- 「B6 closeout 時点では deferred」→「P6-B6R1 で CLOSED」の履歴、Status（NON_BLOCKING_FOR_B6_CLOSEOUT /
  MANDATORY_PRE_B7_REMEDIATION）、deadline **BEFORE B7 ENTRY** は維持されている。
- CHANGELOG v5.31（B6 closeout）の記載は `99d45ef` と同一。

## 20. 判定と次の gate

B6R1 の remediation は独立再検証で PASS。B6-DEF-1 は CLOSED を確認。runtime defect・blocker なし。
**P6 B6 の最終 refreeze は監督者の判断による。** B7 は開始していない。
