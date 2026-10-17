# PHASE 6 / P6-B6R1 — MONITORING COVERAGE-COMPLETENESS REMEDIATION

対象: B6-DEF-1（Observation channel completeness blind spot）。
**目的はこの一点だけ**: 観測 channel が未供給のとき、依存する condition を未評価とし、`COMPLETE` を返さないこと。
B6B の `COMPLETE` 定義（「要求されたすべての条件を評価できた」）は変更しない。`FAILED` は復活させない。

---

## 1. 根本原因（編集前の監査）

1. **表現の欠落**: `MonitoringObservations` の 3 channel は `default_factory=dict` で、
   `supplied_channels()` は mapping の真偽で判定していた。そのため
   「供給されたが空（`{}`）」と「供給されていない」を区別する手段が型の上に無かった。
2. **経路の欠落**: 未供給の情報は runner の `MonitoringRunResult.diagnostics` にしか届かず、
   engine（`MonitoringEvaluationInput`）には渡らなかった。engine は snapshot の空欄を
   「評価したが該当なし」として扱い、report は `COMPLETE`・未評価 0 を返した。
3. **identity の欠落**: channel の有無は input digest に束縛されず、未供給と空供給の run は
   run_id も canonical report も同一になり得た。

## 2. channel 依存表（frozen engine の source から導出）

| channel（`MonitoringObservations`） | snapshot の field | engine が読む箇所 | 依存する condition_id |
|---|---|---|---|
| `arrived_attachment_keys` | `ThemeSnapshot.arrived_attachment_keys` | `_theme`: 終了済み root への到着 | `RETIRED_ROOT_RECEIVED_EVIDENCE` |
| `semantic_revision_observation_ids` | `ThemeSnapshot.semantic_revision_observation_id` | `_theme`: 受理済み root の意味改訂 | `ACCEPTED_THEME_SEMANTIC_REVISION` |
| `discovery_outcome_tokens` | `ProposalSnapshot.discovery_outcome_token` | `_proposal`: discovery outcome | `DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL`, `ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT` |

補足: `arrived_attachment_keys` は contradiction / invalidation finding の `supporting_refs` にも使われるが、
`supporting_refs` は finding identity に入らず、finding の発火条件でもないため依存には含めない。

## 3. 設計案の比較

| 案 | 内容 | B6B COMPLETE を守る | 空供給と未供給を区別 | report に未評価が残る | finding を作らない | identity churn | 既定値 |
|---|---|---|---|---|---|---|---|
| A. runner で presence を明示 | runner が未供給 channel ごとに `AuthorityFailureSnapshot(blocked_condition_ids=…)` を渡す | ○ | ×（`MonitoringObservations` が区別できないまま） | ○ | **×**（`AUTHORITY_STATE_UNUSABLE` の INTEGRITY finding が出る） | 小 | runner だけ |
| A'. runner が report を作り直す | engine の report を捨て、runner が未評価を足して再発行 | ○ | × | ○ | ○ | 小 | 依存表が engine から離れ、status の決定が 2 箇所に分かれる |
| B. 入力の型で presence を保持 | `MonitoringObservations` を Optional にし、presence を評価入力へ運ぶ | — | ○ | 単独では×（engine が使わなければ未評価にならない） | ○ | なし | adapter |
| C. engine で未供給を未評価化 | engine が presence を受け取り、依存 condition を未評価にする | ○ | 単独では×（入力に presence が無い） | ○ | ○ | なし | engine |

A は要件 N（channel 欠落は finding ではない）に反する。A' は status を決める場所を engine と runner に分け、
依存表を engine の外に置くため drift の危険がある。B と C はそれぞれ単独では足りない。

## 4. 選定: B ＋ C（最小で最も fail-closed）

| 層 | 変更 | 理由 |
|---|---|---|
| adapter `MonitoringObservations` | 3 channel を `Optional[Mapping]`、**既定 `None` = 未供給**。`{}` は「空で供給」 | 空供給と未供給を型で区別する。既定は評価不能側（fail closed） |
| adapter `build_evaluation_input` | `observations` を受け取り、供給された channel だけ内容 digest を `observation:<channel>` として input digest に束縛し、供給済み channel 名を engine へ渡す。**省略時は全 channel 未供給** | 空供給と非空供給を digest で区別。物理順は canonical に並べ替えて除去 |
| engine `MonitoringEvaluationInput` | `supplied_observation_channels: Tuple[str, ...] = ()`（**既定 = 何も供給されていない**）。未知の channel 名は fail closed | coverage を主張する隠れた既定値を作らない |
| engine `evaluate_monitoring` | 依存表 `OBSERVATION_CHANNEL_CONDITIONS` に従い、未供給 channel の依存 condition（有効なもの）を未評価にし、`OBSERVATION_NOT_SUPPLIED:<channel>` を report diagnostics に残す。依存 condition は評価しない（finding を出さない）。供給状況を `observation_channels_supplied` として input digest に束縛 | report 単体で未評価・status・束縛から coverage 不足が分かる。依存表は engine が snapshot を読む箇所の隣に置く |
| runner | 既定 `MonitoringObservations()`（全未供給）をそのまま adapter へ渡す。snapshot 構築は `None` を空として読む | 既定 run は評価不能な condition を未評価として報告する |

変更しないもの: B6B model（`MonitoringFinding` / `MonitoringRunReport` / `ReviewItemState` の schema と identity 規則）、
ruleset（18 condition の id・閾値・分類・subject・finding の意味）、store、review の意味論、Foundation・B1〜B5。

### identity への影響

- **finding identity は不変**（`MonitoringFinding` の identity payload に触れない。channel 欠落は finding を作らない）。
- **run identity の契約は不変**（`(schema_version, cutoff, ruleset_version, knowledge_versions, input_digests)`）。
  input digest に channel の束縛が加わるため run_id の値は変わるが、run report は永続化していない（B6D Option A）ので
  保存済みの identity は存在しない。未供給と空供給は input digest が異なり、run_id も異なる（silent collision なし）。

### status の規則

| 状態 | status |
|---|---|
| 必要 channel すべて供給 ＋ authority 利用可 ＋ 全 condition 評価可 | COMPLETE |
| 必要 channel の 1 つ以上が未供給 | PARTIAL |
| authority の失敗 | PARTIAL |
| 未供給 ＋ authority の失敗 | PARTIAL（両方の原因が未評価と diagnostics に残る） |

`COMPLETE ⟺ unevaluated_conditions == ()` は B6B model が引き続き強制する。


---

## 5. 実装（変更 file と理由）

| file | 変更 | 必要な理由 |
|---|---|---|
| `monitoring_engine.py` | 依存表・`supplied_observation_channels`・依存 condition の保留と未評価化・presence の束縛 | status と `unevaluated_conditions` を決めるのは engine だけ。report 単体で判別させるにはここで扱う必要がある |
| `monitoring_adapter.py` | `MonitoringObservations` の 3 状態化・channel 内容 digest・`build_evaluation_input(observations=)` | 空供給と未供給を型で区別し、評価入力と input digest へ運ぶ |
| `monitoring_runner.py` | 観測を adapter へ渡す／snapshot 構築で `None` を空として読む（3 行） | runner は観測の受け口。PIT 濾過（R1）は不変 |

変更していない: `monitoring_model.py`・`monitoring_rules.py`・`monitoring_store.py`・`knowledge/`（ruleset YAML）・
Foundation・B1〜B5・`config.yaml`・`.github/`・`scripts/`（B6 freeze `99d45ef` との diff 0）。

## 6. 規則のまとめ

| 面 | 未供給（`None`） | 空で供給（`{}`） | 非空で供給 |
|---|---|---|---|
| 依存 condition | 評価しない ＋ 未評価（有効なもののみ） | 評価する（該当なし） | 評価する |
| status への寄与 | `PARTIAL` | なし | なし |
| report diagnostics | `OBSERVATION_NOT_SUPPLIED:<channel>` | なし | なし |
| `input_digests["observation:<channel>"]` | 束縛しない | 空 mapping の内容 digest | 内容 digest（並べ替え後） |
| `input_digests["observation_channels_supplied"]` | 含まれない（全未供給なら `none`） | 名前が含まれる | 名前が含まれる |
| finding | 作らない | — | 依存 condition の finding |

- 未供給は finding ではない（`AUTHORITY_STATE_UNUSABLE` も出さない）。review state を作らない。authority を変えない。
- 未評価の集合は authority 由来と channel 由来の和集合で、canonical sort・重複なし。
- ruleset が依存 condition を要求していない（無効）なら、その channel の欠落は coverage を欠かない。
- 既定値はどの層でも「未供給」（`MonitoringObservations()`、`build_evaluation_input(observations=None)`、
  `MonitoringEvaluationInput(supplied_observation_channels=())`）。coverage を主張する隠れた既定値は無い。
- 帰結: 観測を渡さない既定 run は `PARTIAL` になる（shadow harness の既定 run も `PARTIAL`）。これは意図した fail closed。

## 7. regression matrix（`tests/intelligence/test_theme_monitoring_coverage.py`）

| # | 検証 | test | 結果 |
|---|---|---|---|
| A | 3 channel すべて空で供給 → COMPLETE・未評価 0 | `test_a_*` | PASS |
| B | 3 channel すべて非空で供給 → COMPLETE（依存 condition が実際に発火） | `test_b_*` | PASS |
| C | 3 channel すべて省略 → PARTIAL・依存 4 condition が未評価・diagnostics 3 件 | `test_c_*` | PASS |
| D | arrived のみ省略 → その依存だけ未評価 | `test_def_*[D_arrived-…]` | PASS |
| E | semantic revision のみ省略 | `test_def_*[E_semantic_revision-…]` | PASS |
| F | discovery のみ省略 | `test_def_*[F_discovery-…]` | PASS |
| G | 省略 vs 空供給 → canonical report が異なる | `test_g_*` | PASS |
| H | 省略 vs 空供給 → run_id が異なる | `test_h_*` | PASS |
| I | 省略 vs 空供給 → input digest / binding が異なる（空 vs 非空も異なる） | `test_i_*` / `test_i2_*` | PASS |
| J | 同じ省略入力 ×2 → 同一 | `test_j_*` | PASS |
| K | 同じ空供給入力 ×2 → 同一 | `test_k_*` | PASS |
| L | 非空 channel の物理順（mapping 順・列順）→ 同一 | `test_l_*` | PASS |
| M | channel 欠落 ＋ authority 破損 → PARTIAL・両原因が未評価と diagnostics に残る | `test_m_*`（2 channel） | PASS |
| N | channel 欠落は finding を作らない（値が紛れても評価しない） | `test_n_*` / `test_n2_*` | PASS |
| O | ReviewItemState を作らない | `test_o_*` | PASS |
| P | authority を変えない（data root 全 bytes 不変） | `test_p_*` | PASS |
| Q | 入力が同じなら既存 finding は byte 同一・finding_id 不変、finding に coverage 情報が入らない | `test_q_*` / `test_q2_*` / `test_q3_*` | PASS |
| R | PIT 回帰（cutoff 後の記録は過去 run を変えない） | `test_r_*` ＋ `test_theme_monitoring_runner_pit.py` | PASS |

追加: 依存表と observation field の一致・既定値（`test_00*`）、未知 channel / 予約 key / 非 mapping の拒否（`test_v1〜v3`）、
依存 condition を要求しない ruleset では COMPLETE（`test_v4`）、`COMPLETE ⟺ 未評価 0`（`test_v5`）、
report 単体での判別（`test_w1`）、shadow harness の既定 run が PARTIAL（`test_w2`）。

B6E-RERUN の `test_70` / `test_71` は削除・弱化せず期待値を反転した（省略 → PARTIAL・未評価 = 依存 condition・
diagnostics に `OBSERVATION_NOT_SUPPLIED`／省略と空供給で未評価・diagnostics・input digest・run_id が異なる）。

finding bytes の比較: 修正前後で、観測を同一に供給した run の finding canonical bytes は一致した
（synthetic world: day70 全供給 16 件、retired 既定 6 件）。

## 8. 限界

1. 観測 channel は依然として呼び出し側が供給する（frozen view から導けない点は変わらない）。本 gate は
   「供給されたか」を正しく報告するだけで、供給された内容の正しさは検証しない。
2. run_id の値は input digest の束縛追加により変わる。run report は永続化していない（B6D Option A）ため
   保存済みの run identity は存在しない。
3. 検証はすべて synthetic。real-data shadow は NOT_RUN（Theme authority がどの環境にも存在しない）。
