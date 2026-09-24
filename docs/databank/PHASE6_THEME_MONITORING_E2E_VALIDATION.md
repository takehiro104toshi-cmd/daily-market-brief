# PHASE 6 / P6-B6E — THEME MONITORING E2E VALIDATION REPORT

B6A architecture / B6B model / B6C engine / B6D operational layer を **1 系として** 検証した記録。
本 gate は実装 gate ではない。runtime は 1 byte も変更していない。

**判定: BLOCKER_FOUND。** B3 / B5C の提案 record が run cutoff で濾過されず、
cutoff より後に記録された関係提案が過去 cutoff の run で finding を生む。詳細は §10。

> **状態更新（P6-B6D-R1）: BLOCKER-1 = REMEDIATED_PENDING_RERUN。** runner の読み取り境界で
> B3 / B5C の提案・決定を cutoff 濾過するよう修正した（§23）。**B6E の PASS も BLOCKER の CLOSE もまだ判定していない。**
> それは B6E-RERUN の判定事項である。本 report の §1〜§22 は 8655d8d 時点の記録として残す。

finding の件数を Theme の重要度・市場の重要度・投資妥当性・予測確度として解釈してはならない。
本 report の数値はすべて synthetic fixture 上の descriptive metrics である。

---

## 1. 検証対象と凍結

| module | 役割 | 本 gate での変更 |
|---|---|---|
| `monitoring_model.py` | B6B record model / 語彙 | なし |
| `monitoring_engine.py` | B6C 決定論 engine | なし |
| `monitoring_rules.py` / `monitoring_rules.0.1.0.yaml` | B6C versioned ruleset | なし |
| `monitoring_store.py` | B6D review journal | なし |
| `monitoring_adapter.py` | B6D snapshot 写像 | なし |
| `monitoring_runner.py` | B6D read-only orchestration | なし |

`git diff --name-only 8ef09ab -- src/intelligence/theme_intelligence knowledge/theme_intelligence` が空であることを
`test_e01` が固定する。

## 2. 検証層

| 層 | 内容 | file |
|---|---|---|
| A | 18 condition の positive / negative matrix（adapter → engine） | `tests/intelligence/test_theme_monitoring_e2e.py` §A |
| B | corruption matrix（store → runner） | 同 §B |
| C | cross-layer E2E（authority → resolver → B2/B3/B5 → adapter → engine → review） | 同 §C |
| D | 決定論 replay / physical order / PIT matrix | 同 §D |
| E | zero-write / hidden authority / RR-3 / source-origin / security | 同 §E |
| F | read-only shadow harness と real-data precheck | 同 §F ＋ `tests/intelligence/theme_monitoring_shadow.py` |

## 3. 18 condition coverage matrix

`P` = synthetic positive、`N` = synthetic negative、`X` = cross-layer（実 authority fixture から到達）。

| # | condition_id | category | subject kind | P | N | X | cross-layer cutoff |
|---|---|---|---|---|---|---|---|
| 1 | THEME_CONTRADICTION_EVIDENCE_PRESENT | EVIDENCE | THEME_ROOT | ✅ | ✅ | ✅ | day70 / contradiction_added |
| 2 | THEME_INVALIDATION_EVIDENCE_PRESENT | EVIDENCE | THEME_ROOT | ✅ | ✅ | ✅ | day70 |
| 3 | THEME_WITHOUT_COUNTED_EVIDENCE | EVIDENCE | THEME_ROOT | ✅ | ✅ | ✅ | genesis_visible |
| 4 | THEME_EVIDENCE_STALE | EVIDENCE | THEME_ROOT | ✅ | ✅ | ✅ | day70（policy stale_after_days=1） |
| 5 | ACCEPTED_THEME_SEMANTIC_REVISION | SEMANTIC | THEME_ROOT | ✅ | ✅ | ✅ | day70（observation id は実 record） |
| 6 | RETIRED_ROOT_RECEIVED_EVIDENCE | LIFECYCLE | THEME_ROOT | ✅ | ✅ | ✅ | day70（arrival は呼び出し側 channel） |
| 7 | GOVERNANCE_EVIDENCE_DIVERGENCE | LIFECYCLE | THEME_ROOT | ✅ | ✅ | ✅ | day70 |
| 8 | THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD | PROPOSAL | THEME_PROPOSAL | ✅ | ✅ | ✅ | day70 |
| 9 | THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD | PROPOSAL | THEME_PROPOSAL | ✅ | ✅ | ✅ | day70 |
| 10 | PROPOSAL_DECISION_CHAIN_UNRESOLVED | INTEGRITY | GOVERNANCE_CHAIN | ✅ | ✅ | ✅ | day70（実 fork） |
| 11 | DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL | DISCOVERY | THEME_PROPOSAL | ✅ | ✅ | ✅ | day70（呼び出し側 channel） |
| 12 | ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT | DISCOVERY | THEME_PROPOSAL | ✅ | ✅ | ✅ | day70（呼び出し側 channel） |
| 13 | KNOWLEDGE_VERSION_DRIFT | DISCOVERY | KNOWLEDGE_VERSION | ✅ | ✅ | ✅ | day70（明示入力） |
| 14 | RELATION_ENDPOINT_NOT_ACTIVE | RELATION | RELATION_EDGE | ✅ | ✅ | ✅ | retired |
| 15 | RETRACTED_RELATION_HAS_NEW_PROPOSAL | RELATION | RELATION_PROPOSAL | ✅ | ✅ | ✅ | day70 |
| 16 | SOURCE_ASSERTED_RELATION_CONTESTED | RELATION | RELATION_EDGE | ✅ | ✅ | ✅ | day70 |
| 17 | RELATION_GOVERNANCE_CHAIN_UNRESOLVED | INTEGRITY | GOVERNANCE_CHAIN | ✅ | ✅ | ❌ | §9 参照 |
| 18 | AUTHORITY_STATE_UNUSABLE | INTEGRITY | AUTHORITY_STORE | ✅ | ✅ | ✅ | retired ほか |

synthetic: **18/18 positive ＋ 18/18 negative**。cross-layer: **17/18**。

各 positive で category / subject_kind / salient_state_kind / ruleset_version / cutoff を検証し、
別 cutoff でも `finding_id` が一致すること（cutoff は identity に入らない）を固定した。
aging の 2 件は閾値 token が identity に入るため、閾値が変わらない限り経過日数に依らず同一 id である（`test_a04`）。

## 4. cross-layer E2E

合成 world（A4d 代表 world ＋ B3 / B5B / B5C 合成 record）1 本で、

`authority journal → resolver（PIT）→ B2 lifecycle view / B3 status / B5 relation resolution → monitoring_adapter
→ monitoring_engine → MonitoringFinding → review lookup`

を通し、day70 で 14 condition、retired で 2 condition、genesis_visible で 1 condition を発火させた。
day70 の run は `COMPLETE`（`unevaluated_conditions == ()`）である。

## 5. review-state E2E

1 本の sequence で以下を通した（`test_c06`）。

```
finding 出現 → review 無し（NONE）
→ 人間の明示 ACK を append → 同じ finding は出続ける（ACK は運用状態）
→ 条件が消える cutoff → review journal は 1 byte も変わらない
→ 条件が戻る cutoff → 同じ finding_id → 以前の ACK がそのまま残る（自動 reopen なし）
```

別 sequence で `DEFERRED → 後継 ACKNOWLEDGED` の predecessor graph を確認（`test_c07`）。
fork / dangling / cross-finding / non-monotonic は append で fail closed（`test_c08`）、
multiple genesis は `UNRESOLVED` で終端を選ばない（`test_c09`）。

## 6. zero-write 証明

- `test_e02`: data_root 配下の**全 file** の sha256 inventory を run 前後で比較。new = 0 / deleted = 0 / modified = 0。
  3 種の cutoff で連続実行しても同一。
- `test_e03`: Foundation 5 journal ＋ B3 2 ＋ B5B 2 ＋ B5C 2 ＋ review 1 ＋ knowledge YAML の hash が不変。
- `test_b06`: authority が破損している状態で run しても 1 byte も変わらない（自動修復しない）。
- `test_f01`: shadow harness（2 回 run）でも inventory delta が空。

## 7. 決定論 / physical order

- `test_d01`: 同一 cutoff の 2 回 run で report・findings の canonical bytes・diagnostics が完全一致。
- `test_d02`: chain を持たない独立 record（relation assertions / proposals）の**物理順を 11 seed で入れ替え**ても
  `run_id`・`input_digests`・finding 集合が一致。latest-wins は入っていない。
- `test_d03`: cutoff が違えば `run_id` も違う。

## 8. PIT matrix

| authority family | cutoff で可視 | cutoff − 1µs で不可視 | 結果 |
|---|---|---|---|
| Theme observation / evidence attachment | ✅ | ✅ | PASS（`test_d04`） |
| Theme governance | ✅ | ✅ | PASS（`test_d04`） |
| relation assertion | ✅ | ✅ | PASS（`test_d05`） |
| relation governance | ✅ | ✅ | PASS（`test_d05`） |
| **B3 theme proposal / decision** | — | ❌ | **FAIL（§10 BLOCKER）** |
| **B5C relation proposal / decision** | — | ❌ | **FAIL（§10 BLOCKER）** |
| review state | n/a | n/a | 設計上 PIT ではない（§11） |

## 9. `RELATION_GOVERNANCE_CHAIN_UNRESOLVED` が cross-layer で出ない理由

B5B の `ThemeRelationStore` は、per-edge の unresolved chain を生む history を **load 時に拒否する**。

| 仕込んだ history | store の判定 | resolution status |
|---|---|---|
| 同一 edge に 2 つの genesis governance event | `EDGE_ALREADY_STARTED` | `INVALID_HISTORY` |
| dangling `previous_event_id` | `MISSING_PREDECESSOR` | `INVALID_HISTORY` |
| 同一 predecessor からの fork | `PHYSICAL_DUPLICATE_CONFLICTING` | `STORE_CORRUPTION` |
| 不正な event 順序 | `INVALID_GOVERNANCE_SEQUENCE` | `INVALID_HISTORY` |

いずれも `ThemeRelationResolution.unresolved` は空のまま authority 全体が失敗する。runner はこれを
`AUTHORITY_STATE_UNUSABLE`（INTEGRITY）＋ `PARTIAL` として表す。**黙って健全にはならない**ので不具合ではないが、
condition #17 は現行の store 経路では到達不能な防御的 condition である（`test_c04` が固定）。

## 10. BLOCKER — 提案 authority が run cutoff で濾過されない

### 事象

`monitoring_runner._read_proposals()` と `_read_relation_proposals()` は
`ProposalStore.proposals()` / `decisions()`、`RelationProposalStore.proposals()` / `decisions()` を
**cutoff で濾過せずそのまま** snapshot にする。結果:

- `theme_proposals` と `theme_relation_proposals` の `input_digest` が **cutoff に依存しない**（`test_d09`）。
- day(20) に記録した関係提案が、day(5) の run で `RETRACTED_RELATION_HAS_NEW_PROPOSAL` を発火させる
  （`test_d08`、strict xfail）。
- cutoff より後の決定が、過去 cutoff の `proposal_status` を変える（OPEN → OPEN_DEFERRED 等）。

再現（合成 data root、実データ不要）:

```
cutoff=day(5)  → RETRACTED_RELATION_HAS_NEW_PROPOSAL が発火（提案の created_at は day(10)）
cutoff=day(12) → 同じ finding。theme_proposals digest は両者で完全一致
```

### 原因

- Foundation は `resolve_at_data_root(data_root, root_id, cutoff)`、B5B は
  `resolve_relations_at_data_root(..., cutoff=...)` という **PIT 入口**を持つ。
- B3 の `derive_proposal_status(proposal, decisions)` / `resolve_active_decision(proposal_id, decisions)` と
  B5C の `derive_relation_proposal_status(proposal, decisions)` は **cutoff 引数を持たない**（PIT API が無い）。
- したがって濾過は runner が行う必要があるが、B6D の runner はそれを行っていない。

### 影響範囲

| condition | 影響 |
|---|---|
| `RETRACTED_RELATION_HAS_NEW_PROPOSAL` | 未来の提案で過去 cutoff に finding が出る（実証済み） |
| `PROPOSAL_DECISION_CHAIN_UNRESOLVED` | 未来の決定 chain が過去 cutoff の chain 判定に混ざる |
| `THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD` / `_DEFERRED_` | 未来の決定が status を変え、どちらの aging が効くかが変わる |
| `DISCOVERY_*` | 未来の提案に対しても outcome token が適用され得る |
| `input_digests` / `run_id` | 提案 family の digest が cutoff に無関係になり、replay 同一性の意味が弱まる |

zero-write・決定論・fail closed は損なわれていない。壊れているのは **point-in-time 正しさ** のみである。

### remediation を要する gate

**P6-B6D（`monitoring_runner`）**。B6B / B6C / B6A、および Foundation・B1〜B5 の runtime に変更は不要である。
B6E では修正しない（§27 方針）。想定される最小修正（提案のみ・未実装）:

- `_read_proposals()` で `proposal.created_at <= cutoff` の提案だけを対象にし、
  `decisions_for(...)` の結果を `recorded_at <= cutoff` で濾過してから
  `derive_proposal_status` / `resolve_active_decision` に渡す。
- `_read_relation_proposals()` で同様に `created_at` / `recorded_at` を濾過する。
- B6D contract §8 の PIT 列を「store の全 record」から「cutoff 以前の record」へ改訂する。
- 6 family すべてに「cutoff で可視 / +1µs で不可視」の境界 test を置く。

この修正は adapter / engine / model / ruleset / store を変更せず、runner 内で閉じる見込みである。

## 11. review state の PIT 位置づけ（欠陥ではない）

review state は derived fact ではなく **運用状態** であり、「いま誰がどう扱っているか」を答える。
そのため cutoff で濾過しない（`test_d06` が現行挙動を固定）。run の決定性は同一 bytes に対して保たれる。
これを PIT 化するかどうかは意味論の選択であり、監督者の判断事項として残す。

## 12. PARTIAL 品質監査

観測された PARTIAL の原因分類（report 上の分析分類であり、runtime 語彙は変更していない）。

| 分類 | 例 | 観測 |
|---|---|---|
| EXPECTED_DATA_ABSENCE | cutoff 時点に root の状態が無い（`NO_STATE_AT_CUTOFF`） | 早い cutoff の run で発生 |
| AUTHORITY_CORRUPTION | journal 破損 / 欠損 | corruption matrix 全 20 通りで PARTIAL |
| INVALID_HISTORY | relation governance chain の不整合 | §9 の 4 通り |
| UNKNOWN_ROOT | monitoring scope が edge 端点を含まない | `MONITORING_SCOPE_MISSES_RELATION_ENDPOINT` |
| ADAPTER_LIMITATION | lifecycle が推測を拒否（`GOVERNANCE_EVENTS_REQUIRED`） | 供給時は解消 |
| UNSUPPORTED_OBSERVATION | 観測 channel 未供給 | **PARTIAL にならない**（§13） |

**silent COMPLETE は 1 件も観測されなかった**。`COMPLETE ⟺ unevaluated_conditions == ()` は全 run で成立した。

## 13. coverage / blind-spot 監査（B6D limitation #1）

| channel | 現在の供給元 | 未供給時に blind になる condition | diagnostics に出るか | PARTIAL になるか |
|---|---|---|---|---|
| `arrived_attachment_keys` | 呼び出し側のみ | #6 RETIRED_ROOT_RECEIVED_EVIDENCE | ✅ `OBSERVATION_NOT_SUPPLIED:arrived_attachment_keys` | ❌ |
| `semantic_revision_observation_ids` | 呼び出し側のみ | #5 ACCEPTED_THEME_SEMANTIC_REVISION | ✅ 同上 | ❌ |
| `discovery_outcome_tokens` | 呼び出し側のみ | #11 / #12 DISCOVERY_* | ✅ 同上 | ❌ |
| `knowledge_drift` | 呼び出し側のみ | #13 KNOWLEDGE_VERSION_DRIFT | ❌（明示入力のため channel 扱いではない） | ❌ |

**評価**: 未供給の channel は `MonitoringRunResult.diagnostics` に必ず現れるため「黙って無効化」ではない。
ただし `MonitoringRunReport.status` は `COMPLETE` のままであり、report だけを見る消費者からは
「その condition は評価済みで 0 件」と読めてしまう。B6D は報告済みの limitation #1 としてこれを開示しているが、
**report 単体では区別できない**点は改善候補として残す（本 gate では変更しない）。
`knowledge_drift` は「明示入力が無い＝drift を主張しない」という設計であり、blind spot ではない。

## 14. false-positive / noise 監査

- 健全な synthetic world（governance ACCEPTED ＋ HAS_SUPPORT ＋ QUALIFIES ＋ 端点健全 ＋ 衝突なし）で
  **finding 0 件 / COMPLETE** を確認（`test_a07`）。
- 同一の意味的条件が何度渡されても finding は 1 件に収束する（`test_a09` / `test_e07`）。
  finding 件数は evidence の強度ではない。
- condition ごとの descriptive 分類（評価ではない）:

| 分類 | condition |
|---|---|
| mechanically expected（状態から機械的に定まる） | 1, 2, 3, 7, 10, 14, 15, 16, 18 |
| potentially noisy（母集団に比例して増えやすい） | 4（stale。閾値 policy 次第）, 8, 9（backlog 規模次第） |
| requires human interpretation | 5, 16 |
| cannot assess due to missing observation | 6, 11, 12（channel 未供給時） |

## 15. corruption matrix

| 仕込み | Foundation | B3 | B5B | B5C | review |
|---|---|---|---|---|---|
| malformed JSON | PARTIAL | PARTIAL | PARTIAL | PARTIAL | UNUSABLE |
| truncated final line | PARTIAL | PARTIAL | PARTIAL | PARTIAL | UNUSABLE |
| non-canonical line | PARTIAL | PARTIAL | PARTIAL | PARTIAL | UNUSABLE |
| not an object | PARTIAL | PARTIAL | PARTIAL | PARTIAL | UNUSABLE |
| blank line | PARTIAL | PARTIAL | PARTIAL | PARTIAL | UNUSABLE |
| file 欠損 | PARTIAL | PARTIAL | PARTIAL | PARTIAL | NOT_INITIALIZED |
| duplicate conflicting id | — | PARTIAL | — | — | — |
| unsupported schema / unknown field | — | — | PARTIAL | — | — |

すべて fail closed、自動修復なし、byte 不変。review journal が読めないことは
「誰も review していない」ではなく `UNUSABLE` として区別される。

## 16. hidden authority 監査

- `MonitoringRunResult` の field は 6 つのみで、authority / governance / decision / plan / score / rank /
  priority のいずれの語も含まない（`test_e09`）。
- runner / adapter に authority 側の append API・bridge・plan 型が現れない（`test_e05` / `test_e06`）。
- finding も run report も永続化されない（`test_e04`）。
- 本 validation の結果自体も authority ではない。PASS は system safety の検証であって Theme の真偽の検証ではない。

## 17. RR-3 regression

`RelationAssertionPlan → B5B append` の経路は存在しない。monitoring の 6 module のいずれにも
`relation_proposal_bridge` / `evidence_bridge` / `ThemeStore` / `ThemeRelationStore` が現れない。
受理済み提案を見つけても自動実行しない。shadow harness も同様（`test_e06`）。

## 18. real-data shadow

### precheck 結果

| 確認項目 | 結果 |
|---|---|
| `data/` 配下の `themes/` / `theme_intelligence/` directory | **0 件** |
| `roots.jsonl` / `theme_observations.jsonl` / `relation_assertions.jsonl` / `monitoring_review_states.jsonl` | **0 件** |
| `.github/` workflow から `theme_intelligence` への参照 | **0 件** |
| production bundle closure に `themes` / `theme_intelligence` | 含まれない（`themes` は `EXCLUDED_PACKAGES`） |

Phase 6 の Theme authority は **どの環境でも一度も production へ書かれていない**。Windows 側にも
Theme data_root は存在しない（Phase 6 は workflow へ接続されていないため、書き込む経路自体が無い）。

### 判定

**REAL_DATA_SHADOW_NOT_RUN** — 実 data が存在しないため。Windows runtime の権限問題ではない。
捏造した PASS は作らない。

### 準備した 1 command harness

実 data_root が生まれた時点で、次の 1 command で shadow validation を実行できる。

```
python -m tests.intelligence.theme_monitoring_shadow --data-root <DATA_ROOT> --cutoff 2026-11-10T00:00:00+00:00
```

- READ ONLY。review append なし、finding 保存なし、scheduler / notification なし。
- 実行前後の file inventory（相対 path → sha256:size）を自動比較し `wrote_nothing` を出す。
- 同一 cutoff で 2 回実行し、`run_id` / report canonical hash / finding id 集合 / finding canonical hash /
  `unevaluated_conditions` / diagnostics / `input_digests` を自動比較して `replay_identical` を出す。
- `--second-cutoff` で PIT 観測を追加できる。
- summary は counts / 安定 id / diagnostic code / version / hash のみ。本文・引用・note・actor・絶対 path を出さない。
- exit code: 0 = zero-write ＋ replay 一致 / 1 = 差分あり / 2 = 実行不能。

合成 data root 上でこの harness 自体を検証済み（`test_f01`〜`test_f03`）。

## 19. descriptive metrics（synthetic のみ）

day70 の cross-layer run:

| 指標 | 値 |
|---|---|
| run status | COMPLETE |
| finding count | 16 |
| distinct condition | 14 |
| category 別 | EVIDENCE 5 / SEMANTIC 1 / LIFECYCLE 2 / PROPOSAL 2 / INTEGRITY 1 / DISCOVERY 3 / RELATION 2 |
| subject count | 9 |
| unevaluated condition | 0 |
| authority failure | 0 |
| review lookup | AVAILABLE（全 finding が NONE） |
| observation channel not supplied | 0（全 channel 供給時） |
| input digest | 5 family |

retired cutoff の run: PARTIAL / finding 6 / unevaluated 7 / `NO_STATE_AT_CUTOFF` 1 件。

これは performance ranking ではない。precision / recall は主張しない。

## 20. security / confidentiality

- tracked file に `.pdf` / `.jsonl` / `.sqlite3` / `.env` は 0 件（`test_e11`）。
- harness の summary に本文・引用・note・actor_ref・credential・絶対 path を含めない（`test_f02`）。
- harness に network / LLM / scheduler / 現在時刻 / append API が現れない（`test_e10`）。
- harness は `data_root` の **名前だけ** を summary に出し、絶対 path を出さない。

## 21. 限界

1. real-data shadow 未実施（実 data が存在しない）。実世界の precision / recall は一切主張していない。
2. cross-layer coverage は 17/18。#17 は現行 store 設計では到達不能（§9）。
3. 観測 channel 3 種は呼び出し側供給のままであり、未供給時も `COMPLETE` が出る（§13）。
4. review state は PIT ではない（§11）。
5. §10 の BLOCKER が未修正である。

## 22. B6 closeout entry contract（提案のみ・未実装）

1. **前提**: §10 の BLOCKER が B6D で修正され、6 family すべての PIT 境界 test が green であること。
2. 修正後に本 gate（`test_theme_monitoring_e2e.py`）を無変更で再実行し、`test_d07` / `test_d08` の
   strict xfail が **xpass ではなく通常の pass** になるよう mark を外す（これは B6D 修正の一部）。
3. §13 の blind spot について、`COMPLETE` のまま channel 未供給を許すか、
   未供給を `unevaluated_conditions` に載せるかを監督者が決める。
4. real data_root が生まれた時点で §18 の 1 command を実行し、`wrote_nothing` と `replay_identical` を確認する。
5. その 3 点が揃うまで ruleset の閾値調整も condition 追加も行わない。

## 23. P6-B6D-R1 remediation 状態（REMEDIATED_PENDING_RERUN）

- **修正箇所**: `src/intelligence/theme_intelligence/monitoring_runner.py` のみ。`_visible_at()` が canonical に
  load 済みの record を `created_at <= cutoff`（提案）/ `recorded_at <= cutoff`（決定）で濾過し、
  その後で既存 B3 / B5C resolver に渡す。model / engine / rules / YAML / store / adapter、Foundation・B1〜B5 は無変更。
- **回帰 matrix**: `tests/intelligence/test_theme_monitoring_runner_pit.py`（A〜R ＋ 解決前濾過 ＋ fail closed ＋
  six-family 境界 ＋ zero-write）。修正前の runner で 17 件が fail、修正後に全件 pass することを確認した。
- **strict xfail 2 件**: xfail mark を除去し、通常の test として pass。

### B6E 証跡の訂正（8655d8d の記述のうち誤っていたもの）

R1 の作業中に、B6E の PIT test のうち 3 件が主張どおりのものを検査していなかったことが分かった。
BLOCKER-1 そのものは実在する（`test_d07` と §10 の再現手順が正しく示しており、R1 の回帰 matrix でも再確認した）が、
証跡の帰属を次のとおり訂正する。

| test | 8655d8d での状態 | 実際に起きていたこと | R1 での扱い |
|---|---|---|---|
| `test_d07` | strict xfail | 正しく欠陥を検出していた | mark 除去のみ（assertion 不変） |
| `test_d08` | strict xfail | **欠陥を検査していなかった。** 「未来」の提案が撤回 edge の無い A→C を指し、day(5) の衝突は day(5) 記録の既存提案（B→A、撤回 day(4)）による **PIT 上正しい finding** だった。修正後も fail し続けたことで判明 | 未来の提案を撤回済み edge B→A に向け、その提案 id だけを検査するよう修正。契約（day(20) の提案は day(5) で衝突を起こさない）は不変 |
| `test_d09` | pass | 判別力が無かった。day(5) と day(50) の間に提案 record が無く、修正の前後どちらでも digest が等しい | 「提案 family の digest は cutoff 以前の record に束縛される」を day(1) / day(5) / day(50) で検査する test に置換 |
| `test_d04` | pass | `theme_governance` と名付けた case が実際は genesis observation の境界だった | label を `theme_genesis_observation` に訂正し、本物の governance 境界（退役 event）を追加 |

`test_d07` / `test_d08` / `test_d09` の修正版は、**修正前の runner（8ef09ab）で fail し、修正後の runner で pass する**
ことを確認済み（判別力のある test であることの証明）。§10 の「影響範囲」表は正しい。
§10 で `test_d08` / `test_d09` を証拠として挙げた箇所は、上表の訂正に従って読むこと。

### 6 family PIT 境界（R1 時点）

| family | t − 1µs | t | t + 1µs |
|---|---|---|---|
| Theme observation / evidence | 不可視 | 可視 | 可視 |
| Theme governance（退役） | 不可視 | 可視 | 可視 |
| B3 theme proposal / decision | 不可視 | 可視 | 可視 |
| B5B relation assertion | 不可視 | 可視 | 可視 |
| B5B relation governance | 不可視 | 可視 | 可視 |
| B5C relation proposal / decision | 不可視 | 可視 | 可視 |

（cutoff を record 時刻 t の前後へ動かした観測。t = cutoff で可視、cutoff = t − 1µs は「record が cutoff + 1µs」に相当）

### 本 remediation で扱っていないもの

- §13 の blind spot（`OBSERVATION_NOT_SUPPLIED` があっても report は `COMPLETE`）: 変更していない。test も削除・弱体化していない。
- §9 の #17 到達性、condition 語彙、閾値、ruleset、finding / run identity、review 意味論: 変更していない。
- real-data shadow、B6 closeout、B7: 開始していない。

