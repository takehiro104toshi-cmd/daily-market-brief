# PHASE 6 / P6-B6D — THEME MONITORING OPERATIONAL CONTRACT

monitoring の **運用層**（human review の追記専用 store ＋ read-only な run orchestration ＋
上流 derived state → 評価入力の写像 adapter）の契約。

対象 module

| module | 役割 | 書き込み |
|---|---|---|
| `src/intelligence/theme_intelligence/monitoring_store.py` | 人間の `ReviewItemState` だけの追記専用 journal | **ここだけ**（人間の明示 review） |
| `src/intelligence/theme_intelligence/monitoring_adapter.py` | 上流 resolved / derived state → `MonitoringEvaluationInput` の純写像 | なし |
| `src/intelligence/theme_intelligence/monitoring_runner.py` | `run_monitoring()`（read-only な orchestration） | **なし** |

B6B（model / 語彙）と B6C（engine / ruleset）は **凍結**。本 gate で両者の runtime は変更していない。

---

## 1. 権限境界（最上位ルール）

- monitoring は **authority ではない**。Theme / evidence / governance / proposal / relation のいずれも変更しない。
- `MonitoringFinding` は **保存しない**（B6A Option C）。finding は
  (authority bytes, knowledge versions, ruleset version, cutoff) の純関数であり、保存すると
  再導出結果との食い違いが「どちらが正か」を生み、事実上 B6 に authority を与えてしまう。
- 保存するのは **再導出できないもの**＝「人間がこの finding を見て、どう扱ったか」だけである。
- `resolved`（= derived fact。条件が今は成立していない）と
  `acknowledged`（= 人間の運用状態）は**別物**として最後まで分けて扱う。
  run はいかなる場合も review 状態を書かない。

## 2. 永続化方式の決定（A / B の比較）

| 案 | 内容 | 評価 |
|---|---|---|
| **A（採用）** | `ReviewItemState` journal **のみ** | 採用 |
| B | A ＋ `MonitoringRunReport` の運用 journal | 不採用 |

採用理由（A）

1. `MonitoringRunReport` は run identity が
   `(schema_version, cutoff, ruleset_version, knowledge_versions, input_digests)` の content id であり、
   同じ入力なら常に同じ run_id へ再導出できる。**保存しなくても失われる情報が無い。**
2. 保存すると「保存された report」と「再導出した report」の食い違いが起き得る。
   食い違いの解決には「どちらが正か」の規則が要り、それは B6 に authority を与えることになる。
3. B5C で問題になった「同 id ＋ 異 bytes ＝ CONFLICT」が、report を保存した瞬間に monitoring にも発生する
   （`recorded_at` は identity に入らないため、同じ run を別時刻に再実行すると同 id ＋ 異 bytes になる）。
   保存しなければこの問題自体が発生しない。
4. B6D の目的は「人間の operational 状態を持つこと」であり、run の履歴保存は目的ではない。
   run 履歴が要るなら、それは監査 log であって authority ではないため、別 phase の別設計で扱う。

不採用の代償（記録しておく）

- 「いつ監視が走ったか」は本 phase では残らない。必要になった時点で
  **append-only な運用 log**（authority ではない）として B6E 以降で追加する。

## 3. authority read / write map

| 層 | 対象 | 本 gate での扱い |
|---|---|---|
| Foundation | `themes/*.jsonl`（roots / observations / governance / metadata / mappings） | **READ ONLY**（`resolve_at_data_root`） |
| B2 | `ThemeLifecycleView`（derived） | READ ONLY（`derive_lifecycle`） |
| B3 | `theme_intelligence/proposals.jsonl` / `decisions.jsonl` | **READ ONLY**（`ProposalStore.open(read_only=True)`） |
| B5B | `relation_assertions.jsonl` / `relation_governance.jsonl` | **READ ONLY**（`resolve_relations_at_data_root`） |
| B5C | `relation_proposals.jsonl` / `relation_proposal_decisions.jsonl` | **READ ONLY** |
| versioned knowledge | `knowledge/theme_intelligence/monitoring_rules.<version>.yaml` | READ ONLY（version 明示） |
| **B6D** | `theme_intelligence/monitoring_review_states.jsonl` | **WRITE（`append_review_state` だけ）** |

`run_monitoring()` は上記のうち **WRITE 行を一切通らない**。

## 4. review store contract

- 位置: `<data_root>/theme_intelligence/monitoring_review_states.jsonl`（`data_root` は明示必須）。
- `data_root` が空・空白・`~` 始まりのときは `DATA_ROOT_REQUIRED` で fail closed（暗黙の home / 既定 path は無い）。
- 追記専用。`open('ab')` → `write` → `flush` → `os.fsync`。truncate / rename / replace / unlink を持たない。
- 1 行 = `canonical_monitoring_line(record)`。非 canonical 行は `NON_CANONICAL_LINE` で fail closed。
- **同 id ＋ byte 一致 → `ALREADY_PRESENT`（冪等）／同 id ＋ 異 bytes → `CONFLICT`**。
  `recorded_at` は identity に入らないため、同内容・別時刻は「同 id ＋ 異 bytes」になり CONFLICT になる。
- 外部変更は byte 長で検知（`verify_unchanged` → `CONCURRENT_MODIFICATION`）。single writer。
- fail closed の語彙（`CORRUPTION_REASONS`）: `AUTHORITY_MISSING` / `INVALID_ENCODING` /
  `TRUNCATED_FINAL_LINE` / `BLANK_LINE` / `MALFORMED_JSON` / `NOT_AN_OBJECT` / `INVALID_RECORD` /
  `UNSUPPORTED_SCHEMA_VERSION` / `NON_CANONICAL_LINE` / `WRONG_AUTHORITY` /
  `PHYSICAL_DUPLICATE_IDENTICAL` / `PHYSICAL_DUPLICATE_CONFLICTING`。
- **修復しない・migration しない・読み飛ばさない**。破損は例外であって「条件が無い」ではない。
- 現在時刻を読まない（`recorded_at` は呼び出し側が渡す aware datetime）。
- store は **独自の latest-wins を持たない**。終端の決定は B6B の `resolve_review_state` だけが行う。

## 5. review chain の構造規律（`HISTORY_REASONS`）

append 時は `APPEND_REJECTED`、既に書かれた history の読み込み時は `INVALID_HISTORY`（Foundation / B3 と同じ分け方）。

| code | 意味 |
|---|---|
| `MISSING_PREDECESSOR` | `supersedes_review_state_id` が store に無い |
| `CROSS_FINDING_PREDECESSOR` | 前任が別の finding の review |
| `NOT_TERMINAL_PREDECESSOR` | 既に後継がある record を前任にした（fork の禁止） |
| `NON_MONOTONIC_RECORDED_AT` | 前任より前の時刻 |
| `INVALID_TYPE` | `ReviewItemState` 以外 |

`resolve_review_state`（B6B）側の結果: `RESOLVED` / `NONE` / `UNRESOLVED`（FORK / MULTIPLE_STARTS）/
`INVALID`（DANGLING / CROSS_FINDING / CYCLE）。**物理順も `recorded_at` も勝者を決めない。**

## 6. 人間だけが通る変更経路

```
MonitoringFinding（derived / 保存しない）
        │
        │  人が見る
        ▼
ReviewItemState.build(finding_id, disposition, actor_ref, recorded_at, note, supersedes)
        │  actor_class は HUMAN に固定（RULE / LLM_PROPOSAL は FORBIDDEN_REVIEW_AUTHORITY）
        ▼
MonitoringReviewStore.append_review_state(record)     ← 唯一の書き込み経路
```

- `ReviewDisposition` は `ACKNOWLEDGED` / `DISMISSED` / `DEFERRED` の 3 つだけ。
  `RESOLVED` / `CLOSED` / `AUTO_*` は語彙に存在しない。
- `run_monitoring()` は `append_review_state` を **import も参照もしない**（test で固定）。
- review は governance ではない。Theme / relation について何かを決める必要が生じた時点で、
  それは B3 / B5C の提案と決定 authority を通らなければならない。

## 7. runner architecture

```
明示入力（data_root / cutoff / recorded_at / root_ids / lifecycle_policy / ruleset|version / knowledge_versions）
   ↓  version 固定の knowledge 読み込み（latest 解決なし）
   ↓  authority を read-only で open、cutoff 固定で PIT 解決
   ↓  既存 derived view（B1/B2/B3/B5）をそのまま取得
   ↓  monitoring_adapter → MonitoringEvaluationInput（＋ input digests）
   ↓  evaluate_monitoring()（B6C 純関数）
   ↓  finding ごとに resolve_review_state()（B6B 純関数）
MonitoringRunResult
```

runner は **intelligence semantics を持たない**。条件判定は B6C、chain semantics は各 resolver、
lifecycle semantics は B2、relation semantics は B5 が答える。runner にあるのは検証・読み取り・写像・結合だけ。

`MonitoringRunResult` の field は `runner_version` / `report` / `findings` / `reviews` /
`review_status` / `diagnostics` の 6 つのみ。**governance command・実行計画・推奨 action・優先度・
severity・投資 signal・予測を持たない。**

`review_status`（`ReviewLookupStatus`）: `AVAILABLE` / `NOT_INITIALIZED` / `UNUSABLE`。
review journal が読めないことを「誰も review していない」にしない。

## 8. snapshot adapter contract（B6C limitation #1 を閉じる）

| snapshot field | source authority / view | PIT | 欠損の扱い | 未解決の扱い | 失敗の扱い |
|---|---|---|---|---|---|
| `ThemeSnapshot.governance_state` | B2 `view.governance.state` | resolver の cutoff | `NOT_AVAILABLE` → UNAVAILABLE | `UNRESOLVED` → UNAVAILABLE | resolution 失敗 → UNAVAILABLE(`RESOLUTION_FAILURE_CLASS`) |
| `ThemeSnapshot.evidence_flags` | B2 `view.evidence.flags` | 同上 | flag 無し = 条件不成立（B2 が評価済み） | `EvidenceConditionStatus != EVALUATED` → UNAVAILABLE | 同上 |
| `ThemeSnapshot.evidence_roles_present` | B2 flag → role 写像（`ROLE_BY_FLAG`） | 同上 | 同上 | 同上 | 同上 |
| `ThemeSnapshot.freshness_policy_token` | B2 `LifecyclePolicy`（`schema_version|stale_after_days`） | 不変 | 空なら B6C が `THEME_EVIDENCE_STALE` を**未評価**にする | — | — |
| `ThemeSnapshot.arrived_attachment_keys` | 呼び出し側の観測 channel | 呼び出し側 | 未供給は `OBSERVATION_NOT_SUPPLIED:` として結果に残す | — | token 語彙外の key は locator へ畳む（捨てない） |
| `ThemeSnapshot.semantic_revision_observation_id` | 呼び出し側の観測 channel | 呼び出し側 | 同上 | — | — |
| `ProposalSnapshot.proposal_status` | B3 `derive_proposal_status` | store の全 record ＋ decision chain | `None` → UNAVAILABLE（**false にしない**） | `OPEN_UNRESOLVED` はそのまま渡す | store 失敗 → authority failure |
| `ProposalSnapshot.decision_chain_status` | B3 `resolve_active_decision().status` | 同上 | `NONE` / `RESOLVED` は空文字（健全） | `UNRESOLVED` / `INVALID` をそのまま渡す | 同上 |
| `ProposalSnapshot.created_at` | B3 `proposal.created_at` | — | `None` → B6C が aging を**未評価**にする | — | — |
| `ProposalSnapshot.discovery_outcome_token` | 呼び出し側の観測 channel | 呼び出し側 | 未供給は結果の diagnostics に残す | — | — |
| `RelationSnapshot.edge_state` / `assertion_class` / 端点 | B5 `ResolvedRelation` | `resolve_relations_at_data_root` の cutoff | — | `UnresolvedEdge` → chain 語彙へ写す | `ExcludedEdge` → UNAVAILABLE（`ENDPOINT_<STATE>`） |
| `RelationSnapshot.contested_theme_root_id` | B2 の `CONTESTED` flag と B5 端点の**機械的 join** | 両者の cutoff（同一） | join 無しは空 | 端点 Theme が UNAVAILABLE なら contested 判定に入らない | — |
| `RelationSnapshot.governance_chain_status` | B5 `UnresolvedEdge.status` | 同上 | 健全なら空 | `UNRESOLVED`→`UNRESOLVED` | `INVALID_HISTORY`→`INVALID`（語彙写像） |
| `RelationProposalSnapshot.conflict_token` | B5C status ＋ B5B 撤回 edge の join | 両者の cutoff | 衝突無しは空 | chain 未解決の提案は UNAVAILABLE（**衝突なしにしない**） | relation authority 不可なら条件ごと未評価 |
| `KnowledgeDriftSnapshot` | 呼び出し側が渡す (name, from, to) | — | 未供給は drift 無し（明示入力） | — | — |
| `AuthorityFailureSnapshot` | 各 store の失敗 code | — | — | — | `blocked_condition_ids` で条件を未評価にする |

**禁止した silent coercion**（すべて test で固定）

- `None` → false にしない（`PROPOSAL_STATUS_UNAVAILABLE`）。
- `UNRESOLVED` → 「存在しない」にしない（chain 語彙をそのまま渡す／UNAVAILABLE にする）。
- store 破損 → 「条件が無い」にしない（`AuthorityFailureSnapshot` ＋ PARTIAL）。
- 未知 root → 「不活性」にしない（`ENDPOINT_UNKNOWN_ROOT` として UNAVAILABLE）。
- 識別子が B6B の token 語彙・長さ制限を超える → **捨てない**。`content_id("thmloc", …)` の安定 locator へ畳む。

## 9. PIT と cutoff

- `cutoff` は呼び出し側が渡す **aware datetime**。runner は現在時刻を一切読まない（`.now()` / `utcnow` 不在を test で固定）。
- `recorded_at < cutoff` は `RECORDED_BEFORE_CUTOFF` で fail closed。
- cutoff ちょうどの record は見える。1 マイクロ秒後の record は見えない（test 15）。
- 同じ authority bytes ＋ 同じ knowledge version ＋ 同じ ruleset ＋ 同じ cutoff →
  同じ `input_digests`・同じ `run_id`・同じ findings（test 13 / 17）。

## 10. input digest

- 各 authority family の snapshot 列を canonical JSON にし、**辞書順に並べてから** `content_id("thmin", …)`。
- key は authority 名（`theme_observations` / `theme_proposals` / `theme_relations` /
  `theme_relation_proposals` / `knowledge_drift` / `authority_failures`）。
- 物理順・投入順に依存しない（test 18）。
- mtime / inode / 絶対 path / 現在時刻を **含まない**。別 path へ複製し mtime を書き換えても digest は同一（test 17 / 20）。
- snapshot は cutoff 固定で導出済みなので digest は cutoff-aware であり、`cutoff` 自体も run identity に別 field として入る。

## 11. knowledge version binding

- `ruleset` を直接渡すか、`knowledge_root` ＋ `ruleset_version` を渡すかの **排他**（両方は `AMBIGUOUS_RULESET`、
  どちらも無ければ `RULESET_REQUIRED`）。「latest」解決は存在しない。
- 解決できない version は loader が fail closed（digest / envelope / cutoff すべて検査）。
- run identity に入る knowledge は **実際に使ったものだけ**。B6D では
  `lifecycle_policy`（`theme_lifecycle_policy:0.1.0|<stale_after_days>`）のみ。
  monitoring ruleset は `MonitoringRunReport.ruleset_version` として別 field で束縛されるため重複させない。
- 呼び出し側が同じ key に別 version を渡した場合は `KNOWLEDGE_VERSION_CONFLICT` で fail closed。

## 12. PARTIAL の伝播

上流の失敗は **空 snapshot にならない**。次のいずれかで engine に届く。

| 上流の状態 | 写像 | 結果 |
|---|---|---|
| `STORE_CORRUPTION` / `INVALID_HISTORY`（Foundation） | `ThemeSnapshot` UNAVAILABLE | INTEGRITY finding ＋ THEME 条件が未評価 ＋ `PARTIAL` |
| `NO_STATE`（cutoff 時点に状態が無い） | `ThemeSnapshot` UNAVAILABLE(`NO_STATE_AT_CUTOFF`) | 同上 |
| `UNRESOLVED`（governance fork） | `ThemeSnapshot` UNAVAILABLE(`GOVERNANCE_UNRESOLVED`) | 同上 |
| lifecycle が推測を拒否（`GOVERNANCE_EVENTS_REQUIRED` 等） | `ThemeSnapshot` UNAVAILABLE(exc.code) | 同上 |
| proposal / relation / relation proposal journal が読めない | `AuthorityFailureSnapshot` | 該当条件が未評価 ＋ `PARTIAL` |
| relation 解決が `UNRESOLVED` / `INVALID_HISTORY` / `STORE_CORRUPTION` | `AuthorityFailureSnapshot` | RELATION 条件 ＋ 関係提案条件が未評価 ＋ `PARTIAL` |
| edge の端点が cutoff 時点で取れない（`ExcludedEdge`） | `RelationSnapshot` UNAVAILABLE | 同上（該当 edge のみ） |

`COMPLETE ⟺ unevaluated_conditions == ()` は B6B model が強制する。静かな「finding 0 件の COMPLETE」は作れない。

## 13. 「今出ている finding」と「過去の review」

`MonitoringRunResult.reviews` は `FindingReview(finding, resolution)` の列である。

- `finding` が出ていること＝**derived fact**（今この条件が成立している）。
- `resolution` が `RESOLVED` で終端が `ACKNOWLEDGED`＝**人間の運用状態**（人が見た）。
- 両者は独立。acknowledge しても finding は出続ける（test 52）。これは意図した設計であり、
  「見たら消える」挙動は operational 状態が derived fact を上書きすることを意味するため採らない。

## 14. 再出現（episode identity を作らない）

`finding_id` は `(schema_version, condition_id, category, subject_kind, subject_ref, salient_state)` の
content id であり、**cutoff を含まない**。したがって

- 同じ意味的条件は、別 cutoff でも **同じ `finding_id`** を持つ（test 55）。
- 条件が消えた run は review journal を 1 byte も変えない（test 54）。`RESOLVED` への書き換えもしない。
- 条件が戻った run でも review 状態は自動で reopen されない。前の `DEFERRED` はそのまま resolve される。
- 「今回の発生」を表す episode id は **存在しない**。

## 15. B1 / B2 / B3 / B4 / B5 の再利用（再実装していないこと）

| 意味論 | 所有者 | B6D での扱い |
|---|---|---|
| Theme PIT 解決 | Foundation `resolver` | `resolve_at_data_root` を呼ぶだけ |
| governance / evidence 条件 flag・stale 閾値 | B2 `lifecycle` ＋ `LifecyclePolicy` | view をそのまま写す。日数計算を持たない |
| proposal status / decision chain | B3 `proposal_resolution` | `derive_proposal_status` / `resolve_active_decision` を呼ぶだけ |
| relation edge / 端点 / governance chain | B5B `relation_resolution` | `resolve_relations_at_data_root` の結果をそのまま写す |
| relation proposal status | B5C `relation_proposal_resolution` | `derive_relation_proposal_status` を呼ぶだけ |
| 条件判定 | B6C `monitoring_engine` | そのまま。runner は判定を持たない |
| review chain 解決 | B6B `resolve_review_state` | そのまま。store は独自解決を持たない |

## 16. 非変更の証明（§26）

`test_21_a_run_changes_no_authority_byte` が、Foundation 5 journal ＋ B3 2 journal ＋ B5B 2 journal ＋
B5C 2 journal ＋ review journal の **SHA-256 を run 前後で比較**し、すべて一致することを固定する。
`test_22` は review journal 単体について同じことを固定する（run だけでは 1 byte も変わらない）。

## 17. RR-3（execution gate は作らない）

B5 の「受理 → plan → [未実装の execution gate] → authority」という境界は **触っていない**。
monitoring は plan を作らず、plan を実行せず、提案の ACCEPT / REJECT / DEFER も行わない。
`monitoring_runner` の source に `plan_` / `execute_` / `append_*`（authority 側）が存在しないことを test で固定した。

## 18. security / confidentiality

- `note` は B6B model が bounded（240 字・単一行）かつ `PROHIBITED_CONTENT` 検査済み
  （credential を含む URL・`?api_key=` 等の query・drive path・UNC path を拒否）。B6D は store 側でも
  同じ検査が append と load の両方で効くことを test で固定した。
- runner / store は例外 message を結果へ載せない。`_error_code()` が **安定 code だけ**を取り出し、
  token 以外は `AUTHORITY_UNUSABLE` に潰す（path が diagnostics へ漏れない）。
- `data_root` は常に明示。user 固有 path・home shortcut・環境変数は source に存在しない。
- 本 gate で追加した journal は synthetic な `tmp_path` 上だけ。tracked file に journal / PDF /
  portfolio / credential は 0 件。

## 19. 既知の限界（本 gate で閉じていないもの）

1. `arrived_attachment_keys` / `semantic_revision_observation_ids` / `discovery_outcome_tokens` は
   cutoff 1 点の frozen view からは導けないため **呼び出し側の観測 channel** のままである。
   未供給は `OBSERVATION_NOT_SUPPLIED:<name>` として結果に残す（黙って「無かった」にしない）が、
   供給されない限り該当条件は成立しない。
2. Foundation の attachment key は `#` を含み B6B の token 語彙に入らないため、
   `RETIRED_ROOT_RECEIVED_EVIDENCE` の `attachment_key` は安定 locator（`thmloc_…`）へ畳まれる。
   人間可読性は落ちる。token 語彙の拡張は B6B の変更になるため行っていない。
3. `UnresolvedEdge` は assertion chain の失敗と governance chain の失敗を区別できるが、
   B6C の `RELATION_GOVERNANCE_CHAIN_UNRESOLVED` は `chain_kind` を `RELATION_GOVERNANCE` に固定している。
   区別は `diagnostic_code` に残る。condition の分割は B6C の変更になるため行っていない。
4. relation proposal の decision chain 破損には専用 condition が無く、
   `AUTHORITY_STATE_UNUSABLE`（INTEGRITY）＋ PARTIAL として表れる。
5. `NO_STATE_AT_CUTOFF` は INTEGRITY 系の `AUTHORITY_STATE_UNUSABLE` として出る。
   「まだ存在しない root」と「読めない authority」が同じ category に入るのは粗い。
   condition の追加は B6C の変更になるため行っていない。
6. correction event を辿るには `governance_events_by_root` の供給が要る。未供給のまま correction が
   effective な root は `GOVERNANCE_EVENTS_REQUIRED` で UNAVAILABLE になる（推測しない）。
7. 実データでの shadow run は行っていない（B6E の gate）。本 contract の検証はすべて synthetic。

## 20. B6E への entry contract（提案。実装しない）

1. **入口**: 本 contract の `run_monitoring()` を **無変更で**、実 data_root に対し read-only で 1 回走らせる。
2. **前提条件**: 実行前後で全 authority journal の SHA-256 が一致すること（§16 と同じ方法）。
3. **観測項目**: run status（COMPLETE / PARTIAL）、`unevaluated_conditions`、condition 別の finding 件数、
   同一 cutoff の 2 回実行で `run_id` と finding 集合が完全一致すること。
4. **禁止**: review state の追記、finding の保存、scheduler、notification、public 出力、
   B5 execution gate、B7、LLM、network。
5. **判断材料**: 条件別の件数分布（noise の実測）と PARTIAL の理由分布。
   これが揃うまで ruleset の閾値調整も condition 追加も行わない。
