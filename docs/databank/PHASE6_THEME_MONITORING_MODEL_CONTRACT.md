# PHASE 6 / P6-B6B — THEME MONITORING MODEL / VOCABULARY CONTRACT

対象: `src/intelligence/theme_intelligence/monitoring_model.py`（純。model と語彙のみ）。

B6B は **model gate** である。monitoring engine / ruleset YAML / condition evaluator / operational store /
runner / notification adapter はいずれも実装していない。実データ監視も行っていない。

B6A（anchor `08c59fe`）で凍結した決定 D-B6-1〜D-B6-14 を設計前提とし、変更していない。

---

## 1. authority 境界

```
knowledge   MonitoringConditionDefinition（ruleset）      … B6C。本 gate に無い
DERIVED     MonitoringFinding                             … 既定で永続化しない
DERIVED     MonitoringRunReport                           … authority ではない
OPERATIONAL ReviewItemState                               … 再導出できない人間入力
AUTHORITY   Foundation / B3 / B5C の governance           … B6 の外
```

凍結文言:

- `FINDING_MEANING = "a deterministic observation that a condition holds for a subject"`
- `FINDING_NON_MEANING = "an instruction to change any authority"`
- `REVIEW_IS_NOT_GOVERNANCE = "a review disposition records that a person looked, not that a person decided"`
- `CONDITION_ID_IS_SEMANTIC = "a condition_id names the meaning; a changed meaning needs a new condition_id"`

---

## 2. package / import 境界

`monitoring_model` が import するのは **`..core.ids` / `..core.time` / `..themes.model` と stdlib だけ**である。
B1〜B5 の runtime module を 1 つも import しない。したがって:

- Foundation → B6 の依存は無い。
- B1〜B5 → B6 の依存は無い（`src/` 全体で `monitoring_model` を参照する module は本体以外に 0 件）。
- B6 → B1〜B5 の依存も無い（本 gate では不要だった）。

`tests/intelligence/test_theme_intelligence_import_boundary.py` に additive に登録した
（`MODULES` と、`content_id` を使う `IDENTITY_MODULES`）。

---

## 3. 語彙

### 3.1 `MonitoringCategory`（名義尺度。順序を持たない）

```
EVIDENCE / SEMANTIC / LIFECYCLE / PROPOSAL / DISCOVERY / RELATION / INTEGRITY
```

`TECHNICAL_CATEGORIES = (INTEGRITY,)`。技術的 / 構造的な失敗と、investment intelligence 上の
review condition を category で分ける（D-B6-9）。

**severity / priority / importance / confidence / strength / risk の意味を持たない。**
enum の並びを ranking として使える設計にしていない。LOW / MEDIUM / HIGH の値は存在しない（D-B6-6）。

### 3.2 `MonitoringSubjectKind`（閉じた列挙。自由形式の subject type を作らない）

```
THEME_ROOT / THEME_PROPOSAL / EVIDENCE_PROPOSAL / RELATION_EDGE / RELATION_PROPOSAL /
GOVERNANCE_CHAIN / AUTHORITY_STORE / KNOWLEDGE_VERSION
```

`OTHER` / `GENERIC` は無い。`subject_kind` ＋ `subject_ref` の組で対象を決定論的に特定する。
`THEME_ROOT` のときは `subject_ref` が Theme root id であることを強制する。

### 3.3 `MonitoringRunStatus`

```
COMPLETE / PARTIAL
```

**`FAILED` は report に存在しない。** report を出せない run は report を持たない（runner 側の失敗であり、
「何も知らない」と主張する report を残さない）。

### 3.4 `ReviewDisposition`

```
ACKNOWLEDGED / DISMISSED / DEFERRED
```

**`RESOLVED` は存在しない。** 条件が消えたことは「次の run で finding が導出されない」という derived な事実であり、
人間が宣言するものではない（B6A の分離を維持）。`APPROVED` / `REJECTED` / `ACCEPTED` / `PROMOTED` /
`EXECUTED` / `RETIRED` も存在しない（B3 / B5C の governance decision と混同しないため）。

---

## 4. `MonitoringFinding`

```
schema_version / monitoring_vocab_version
finding_id
condition_id / condition_version
category / subject_kind / subject_ref
salient_state
message_key
cutoff / ruleset_version / knowledge_versions
trigger_refs / supporting_refs
diagnostics
```

不変 frozen dataclass。canonical 直列化。content-addressed identity。

---

## 5. identity contract

```
finding_id = content id over
    (schema_version, condition_id, category, subject_kind, subject_ref, salient_state)
```

**identity に含めないもの（すべて provenance）**:
`cutoff` / `condition_version` / `ruleset_version` / `knowledge_versions` / `message_key` /
`trigger_refs` / `supporting_refs` / `diagnostics` / run 時刻 / run id。

### 5.1 version binding の判断

| 問い | 答え |
|---|---|
| 同じ状態を ruleset v1 と v2 が検出したら同じ finding か | **同じ**。`ruleset_version` / `condition_version` は identity の外 |
| 同じ状態が別 cutoff でも続いていたら同じ finding か | **同じ**。`cutoff` は identity の外 |
| 条件の意味が変わったらどうするか | **`condition_id` を新しくする。version を上げない**（`CONDITION_ID_IS_SEMANTIC`） |

`condition_id` は「意味の名前」である。意味を変える改訂は新しい `condition_id` を要求するため、
version を identity に入れなくても identity collision が起きない。これは B4C が
rule id / version を提案 identity の外に置いて「等価な提案は rule を跨いで収束する」とした設計と同型である。

`schema_version` だけは identity に含める（record の形そのものの契約であるため）。

### 5.2 帰結

```
同じ状態      → 同じ finding_id → 同じ open review item（再提示しない）
状態が変わった → 別の finding_id → 新しい review item（実質的な reopen）
条件が消えた   → finding が生成されない（resolved。人間の操作は不要）
```

閾値も抑制ヒューリスティクスも持たない。

---

## 6. `salient_state` 設計

自由な JSON ではない。`SalientStateKind` ごとに **identity を担う key 集合を凍結**した typed value object である。

- 値は **bounded な token 文字列だけ**を取る（`^[A-Za-z0-9][A-Za-z0-9_:.\-|]*$`、最大 200 字）。
- したがって **数値・浮動小数・時刻・score を構造的に保持できない**。
  「何日 stale か」「何件あるか」のような run ごとに動く量が identity に混入しない。
- key 集合の過不足はどちらも `SALIENT_STATE_KEY_MISMATCH` で拒否する。未知 key を黙って受け入れない。
- `theme_root_id` を含む kind は Theme root id 形式を強制する。
- 最大 8 対。物理順に依存せず、key で canonical sort する。

### 6.1 condition family ごとの identity-bearing state

| `SalientStateKind` | identity を担う key | 除外する volatile state | 対応する B6A MVP 条件 |
|---|---|---|---|
| `EVIDENCE_ROLE_PRESENCE` | `role` / `theme_root_id` | evidence 集合・件数・時刻 | 矛盾 / 無効化 evidence の存在 |
| `EVIDENCE_ABSENCE` | `absence_kind` / `theme_root_id` | 件数 | counted evidence が 0 |
| `FRESHNESS_THRESHOLD` | `theme_root_id` / `threshold_token` | **経過日数**・最新 evidence 日付 | 陳腐化 |
| `SEMANTIC_REVISION` | `observation_id` / `theme_root_id` | 変更 field の一覧 | 意味の改訂 |
| `LIFECYCLE_DIVERGENCE` | `evidence_condition` / `governance_state` / `theme_root_id` | 件数 | governance と evidence の乖離 |
| `RETIRED_ROOT_EVIDENCE` | `attachment_key` / `theme_root_id` | 付与時刻 | 撤退 root への evidence |
| `DECISION_BACKLOG` | `proposal_id` / `proposal_status` / `threshold_token` | **経過日数** | 提案の滞留 |
| `CHAIN_UNRESOLVED` | `chain_kind` / `diagnostic_code` / `subject_token` | 件数・物理順 | 決定 chain の未解決 |
| `DISCOVERY_OUTCOME` | `outcome_token` / `proposal_id` | run id・hit 件数 | 受理提案の無い discovery |
| `VERSION_DRIFT` | `from_version` / `knowledge_name` / `to_version` | run 時刻 | knowledge version の変化 |
| `RELATION_ENDPOINT_STATE` | `edge_key` / `endpoint_role` / `endpoint_state` | 端点の時刻 | 端点が RETIRED / SUPERSEDED |
| `RELATION_PROPOSAL_CONFLICT` | `conflict_token` / `edge_key` / `relation_proposal_id` | 提案時刻 | 既存 edge との競合 |
| `RELATION_SOURCE_CONTESTED` | `edge_key` / `role` / `theme_root_id` | evidence 集合 | SOURCE_ASSERTED への矛盾 evidence |
| `AUTHORITY_INTEGRITY` | `authority_name` / `failure_class` / `locator_token` | 読み取り時刻・byte 長 | 破損 / 非 canonical |

**粒度の 2 つの原則**:

1. 「ある役割の evidence が存在する」型の条件は、evidence 集合を identity に入れない。
   矛盾 evidence が 1 件増えても同じ finding のままである（re-surface しない）。
2. 「1 件ごとに review が要る」型の条件（撤退 root への evidence）は、その 1 件を identity に入れる。

`ALLOWED_CATEGORIES_BY_STATE_KIND` により、state kind と category の誤った組み合わせを拒否する
（`CATEGORY_STATE_MISMATCH`）。`CHAIN_UNRESOLVED` と `AUTHORITY_INTEGRITY` だけが `INTEGRITY` に属し、
それ以外はいずれも `INTEGRITY` を取れない。

---

## 7. source / evidence provenance

`MonitoringReference(ref_kind, ref_id)` は **identity を担わない**。参照 identity だけを保持し、
本文・抜粋・引用を保持しない。

- `trigger_refs`: 条件成立の直接の根拠。
- `supporting_refs`: 監査のための補助参照。

両方とも identity の外にあるため、根拠が増えても finding は同じである。
一方で根拠が完全に消えることはない（record に残る）。最大 24 件・重複不可・canonical sort。

**finding から新しい evidence authority を作らない。** 参照するだけである。

---

## 8. `MonitoringRunReport`

```
schema_version / monitoring_vocab_version
run_id
cutoff / ruleset_version / knowledge_versions / input_digests
status / finding_ids / unevaluated_conditions / diagnostics
recorded_at
```

```
run_id = content id over (schema_version, cutoff, ruleset_version, knowledge_versions, input_digests)
```

**finding とは逆に `cutoff` が identity を担う。** 実行時刻・物理順・結果（finding / diagnostics）は
identity に入らない。同一入力 ＋ 同一 version ＋ 同一 cutoff → 同一 `run_id`。

### 8.1 silent failure の禁止

- `COMPLETE` は `unevaluated_conditions == ()` を要求する（`INCOMPLETE_RUN_MARKED_COMPLETE`）。
- `PARTIAL` は `unevaluated_conditions != ()` を要求する（`PARTIAL_RUN_WITHOUT_REASON`）。
- `recorded_at >= cutoff`（`REPORT_BEFORE_CUTOFF`）。

authority が読めなかった run を「finding 0 件の COMPLETE」として残すことが**構造的にできない**。

---

## 9. integrity finding

技術的な失敗は `INTEGRITY` category ＋ `AUTHORITY_INTEGRITY` / `CHAIN_UNRESOLVED` の state kind で表す。
既存の失敗語彙（`STORE_CORRUPTION` / `INVALID_HISTORY` / `MALFORMED_JSON` / `NON_CANONICAL_LINE` /
`UNSUPPORTED_SCHEMA_VERSION` 等）を **`failure_class` / `diagnostic_code` として包む**。
新しい名前を乱造しない。

同じ障害は同じ fingerprint（`authority_name` / `failure_class` / `locator_token`）に収束するため、
run を繰り返しても finding は 1 件のままである。

**integrity finding も governance action を自動生成しない。**

---

## 10. `ReviewItemState` と chain

```
schema_version / monitoring_vocab_version
review_state_id
finding_id / disposition
actor_class（HUMAN 固定）/ actor_ref / note
supersedes_review_state_id
recorded_at
```

```
review_state_id = content id over
    (schema_version, finding_id, disposition, actor_class, actor_ref, note, supersedes_review_state_id)
```

`recorded_at` は provenance であり identity に入らない。同じ内容の記録は同じ id に収束する。

### 10.1 chain 意味論（純関数 `resolve_review_state`。実 store は B6D）

`supersedes_review_state_id` の graph だけで終端を解く。**latest-wins は無い。**

| 入力 | 結果 |
|---|---|
| 記録なし | `NONE` |
| 単一 chain | `RESOLVED`（終端が現在の処理） |
| fork | `UNRESOLVED`（`FORK`） |
| 複数 genesis | `UNRESOLVED`（`MULTIPLE_STARTS`） |
| dangling predecessor | `INVALID`（`DANGLING_PREDECESSOR`） |
| 別 finding の predecessor | `INVALID`（`CROSS_FINDING_PREDECESSOR`） |
| cycle | `INVALID`（`CYCLE`） |

これは governance authority の chain ではなく、「この finding を人間がどう扱ってきたか」の
operational history である。

---

## 11. 時間 / PIT

- 時刻はすべて呼び出し側が渡す aware datetime。naive は `INVALID_TIME`。
- 現在時刻を読まない（`.now(` / `utcnow` / `time.time` の token が 0 件）。
- 乱数を使わない（`random.` / `secrets.` / `uuid` / `new_ulid` の token が 0 件）。
- `cutoff` は finding の provenance、run report の identity。
- `recorded_at` は provenance のみ。

---

## 12. 直列化

既存の canonical JSON 規律（`sort_keys` / compact separators / `ensure_ascii=False`）を再利用する。

- 決定論的な field 順序 / UTF-8 / enum は値文字列 / aware datetime は UTC ISO。
- 未知 field は `UNKNOWN_FIELD` で拒否。`schema_version` は厳密一致。
- 集合は canonical sort（`facts` は key 順、参照と code は canonical JSON 順 / 辞書順）。
- canonical round-trip と content id 検証を全 record で行う。
- `parse_monitoring_record` が `schema_version` で 3 型を振り分け、未知は `UNSUPPORTED_SCHEMA_VERSION`。

---

## 13. security / content hygiene

すべての text field で `PROHIBITED_CONTENT` guard（credential 付き URL / secret query / drive path /
UNC path）を適用する。加えて:

- `note` は 240 字上限、`actor_ref` / token は 200 字上限、key は 64 字上限。
- 改行を含む値を拒否する（単一行のみ）。
- 参照は identity だけを保持し、**記事本文・長い引用・機密 PDF text を保持できない**。
- 数値と時刻を `salient_state` に入れられないため、価格・score の混入経路が構造的に無い。

---

## 14. 隠れた authority の不在

`MonitoringFinding` / `MonitoringRunReport` / `ReviewItemState` のいずれにも、
`approve` / `reject` / `promote` / `mutate` / `execute` / `attach` / `buy` / `sell` /
`target_price` / `probability` / `confidence_score` / `severity` / `rank` / `priority_score` /
`weight` / `score` / `stance` / `recommendation` / `signal` を含む field が存在しない。

module source にも `RelationAssertionPlan` / `EvidenceAttachmentPlan` / `append_assertion` /
`ThemeStore` / `execute` / `promote` / `governance_action` の token が存在しない。

### 14.1 B5 RR-3 POLICY LOCK の継承

monitoring model は `RelationAssertionPlan` を authority 入力として受ける field も、
「execution が必要」という governance command も持たない。
将来の実行 gate は B6 の外にあり、B6 の finding がそれを起動する経路は存在しない。

---

## 15. 本 gate で作っていないもの

`monitoring_engine.py` / `monitoring_runner.py` / `monitoring_store.py` / monitoring ruleset YAML /
condition evaluator / rule compiler / notification adapter。
package 内の `monitoring*` module は `monitoring_model` の 1 つだけである（test で固定）。

---

## 16. B6C への引き継ぎ（entry contract 案）

B6C engine は次を満たすこと。

1. 入力は明示 cutoff ＋ 読み取り専用の authority 解決結果 ＋ versioned ruleset。現在時刻を読まない。
2. 出力は `MonitoringFinding` の集合と `MonitoringRunReport` のみ。authority を書かない。
3. 条件を評価できなかった場合は `PARTIAL` ＋ `unevaluated_conditions` を必ず埋める。
4. 各条件は `SalientStateKind` のいずれかに写像し、本 contract §6.1 の key 集合を満たす state を作る。
5. `condition_id` は意味の名前であり、意味を変える改訂では新しい `condition_id` を使う。
6. ruleset は宣言的述語のみ。任意 Python / 任意 regex / fuzzy / LLM / 確率 / 順位を持たない。
