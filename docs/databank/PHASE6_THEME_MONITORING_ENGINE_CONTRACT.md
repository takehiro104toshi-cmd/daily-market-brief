# PHASE 6 / P6-B6C — MONITORING ENGINE / RULESET CONTRACT

対象:

- `src/intelligence/theme_intelligence/monitoring_engine.py`（純評価。**I/O を持たない**）
- `src/intelligence/theme_intelligence/monitoring_rules.py`（凍結 registry ＋ strict loader。file を読む）
- `knowledge/theme_intelligence/monitoring_rules.0.1.0.yaml`（versioned knowledge）

store / review-state store / runner / scheduler / notification / 実データ監視は**実装していない**。
B6B の frozen model（`MonitoringFinding` / `MonitoringRunReport` / `ReviewItemState` / `SalientStateKind` /
`resolve_review_state` 等）は変更していない。

---

## 1. 原則

monitoring は「新しい主張を作る」のではなく、「既存の authoritative / derived state の中から、
人間が review すべき既知の状態を**指差す**」だけである。したがって engine は:

Theme の正誤を判断しない ／ evidence の勝敗を判断しない ／ relation の真偽を判断しない ／
proposal を ACCEPT しない ／ governance action を提案しない ／ 投資スタンスを作らない ／ 将来を予測しない。

凍結文言: `ENGINE_EMITS_OBSERVATIONS_ONLY = "the engine reports observed state and never asks for an action"`

---

## 2. module 分割の理由

directive §9 は engine に `open()` / Path / append / fsync を禁じ、§20 は versioned ruleset を YAML から
strict に読むことを要求する。両立させるため **loader を `monitoring_rules.py` に分離**した
（`discovery_rules.py` と同じ分担。YAML の読み取り自体は `knowledge_loader.read_yaml_document`）。

```
monitoring_model   純 record / 語彙（B6B 凍結）
        ↑
monitoring_rules   凍結 registry ＋ strict loader（Path を受ける。YAML は knowledge_loader 経由）
        ↑
monitoring_engine  純評価（stdlib ＋ ..core.time ＋ 上の 2 module だけ。file も時計も乱数も無い）
```

---

## 3. MVP condition set（18 condition_id）

B6A §4 の ✅ 行は **21 行**である（intelligence 16 ＋ integrity 5）。B6A 報告本文の「16 条件」は
integrity 5 行を別勘定にした数であり、同じ集合を指す。これを次のとおり 18 の `condition_id` へ写した。

| # | condition_id | B6A 行 | category | subject_kind | salient_state_kind |
|---|---|---|---|---|---|
| 1 | `THEME_CONTRADICTION_EVIDENCE_PRESENT` | A-1 | EVIDENCE | THEME_ROOT | EVIDENCE_ROLE_PRESENCE |
| 2 | `THEME_INVALIDATION_EVIDENCE_PRESENT` | A-2 | EVIDENCE | THEME_ROOT | EVIDENCE_ROLE_PRESENCE |
| 3 | `THEME_WITHOUT_COUNTED_EVIDENCE` | A-3 | EVIDENCE | THEME_ROOT | EVIDENCE_ABSENCE |
| 4 | `THEME_EVIDENCE_STALE` | A-4 | EVIDENCE | THEME_ROOT | FRESHNESS_THRESHOLD |
| 5 | `ACCEPTED_THEME_SEMANTIC_REVISION` | B-1 | SEMANTIC | THEME_ROOT | SEMANTIC_REVISION |
| 6 | `RETIRED_ROOT_RECEIVED_EVIDENCE` | C-1 | LIFECYCLE | THEME_ROOT | RETIRED_ROOT_EVIDENCE |
| 7 | `GOVERNANCE_EVIDENCE_DIVERGENCE` | C-2 | LIFECYCLE | THEME_ROOT | LIFECYCLE_DIVERGENCE |
| 8 | `THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD` | D-1 | PROPOSAL | THEME_PROPOSAL | DECISION_BACKLOG |
| 9 | `THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD` | D-2 | PROPOSAL | THEME_PROPOSAL | DECISION_BACKLOG |
| 10 | `PROPOSAL_DECISION_CHAIN_UNRESOLVED` | D-3 ＋ G-2 | INTEGRITY | GOVERNANCE_CHAIN | CHAIN_UNRESOLVED |
| 11 | `DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL` | E-1 | DISCOVERY | THEME_PROPOSAL | DISCOVERY_OUTCOME |
| 12 | `ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT` | B6A §13 ＋ B6C §6-C | DISCOVERY | THEME_PROPOSAL | DISCOVERY_OUTCOME |
| 13 | `KNOWLEDGE_VERSION_DRIFT` | E-2 | DISCOVERY | KNOWLEDGE_VERSION | VERSION_DRIFT |
| 14 | `RELATION_ENDPOINT_NOT_ACTIVE` | F-1 | RELATION | RELATION_EDGE | RELATION_ENDPOINT_STATE |
| 15 | `RETRACTED_RELATION_HAS_NEW_PROPOSAL` | F-2 | RELATION | RELATION_PROPOSAL | RELATION_PROPOSAL_CONFLICT |
| 16 | `SOURCE_ASSERTED_RELATION_CONTESTED` | F-3 | RELATION | RELATION_EDGE | RELATION_SOURCE_CONTESTED |
| 17 | `RELATION_GOVERNANCE_CHAIN_UNRESOLVED` | F-5 ＋ G-2 | INTEGRITY | GOVERNANCE_CHAIN | CHAIN_UNRESOLVED |
| 18 | `AUTHORITY_STATE_UNUSABLE` | G-1 / G-3 / G-4 / G-5 | INTEGRITY | AUTHORITY_STORE | AUTHORITY_INTEGRITY |

**21 行 → 18 condition_id の対応（coverage は減っていない）**:

- G-2（chain 未解決）は chain の種類ごとに #10 / #17 へ分かれる。`chain_kind` が区別を担う。
- G-1 / G-3 / G-4 / G-5 は #18 に集約し、`failure_class` が区別を担う
  （`STORE_CORRUPTION` / `INVALID_HISTORY` / `PIT_RESOLUTION_FAILURE` / `UNSUPPORTED_SCHEMA_VERSION` /
  `NON_CANONICAL_LINE` …）。B6B の `AUTHORITY_INTEGRITY` fingerprint
  （`authority_name` / `failure_class` / `locator_token`）がそのために設計されている。
  異なる failure_class は **異なる finding_id** になるため、区別は失われない。
- #12 は B6A §4 の表には行が無いが、B6A §13 の condition 案に挙げられ、B6C directive §6-C が
  MVP family として明示したため含めた。

18 の condition_id はすべて B6B の frozen 14 `SalientStateKind` へ写っている。**写せない condition は無かった**。

---

## 4. ruleset schema

```yaml
schema_version: "theme_monitoring_rules:0.1.0"
ruleset_version: "0.1.0"
published_at: "<RFC3339 aware>"
content_digest: "<sha256 hex>"
conditions:
  - condition_id: <registry に存在する id>
    condition_version: "<x.y.z>"
    enabled: <bool>
    category: <registry と一致>
    subject_kind: <registry と一致>
    salient_state_kind: <registry と一致>
    message_key: "<dotted identifier, <= 64>"
    threshold_days: <int 1..3650>   # B6 が所有する condition のみ
```

### 4.1 strict loader の拒否条件

`UNSUPPORTED_SCHEMA_VERSION` / `VERSION_MISMATCH` / `FUTURE_VERSION`（published_at > cutoff）/
`DIGEST_MISMATCH` / `UNKNOWN_FIELD` / `DUPLICATE_KEY`（YAML 段階）/ `DUPLICATE_CONDITION_ID` /
`MISSING_CONDITION`（registry の全 id が必要）/ `UNSUPPORTED_CONDITION_ID` /
`CONDITION_MAPPING_MISMATCH`（category / subject_kind / salient_state_kind が registry と違う）/
`PROHIBITED_RULE_KEY` / `INVALID_THRESHOLD` / `THRESHOLD_FORBIDDEN` / `MISSING_THRESHOLD` /
`INVALID_MESSAGE_KEY` / `INVALID_TYPE`。

`PROHIBITED_RULE_KEYS`（22 種）: `expression` / `python` / `eval` / `exec` / `code` / `regex` / `pattern` /
`prompt` / `model` / `llm` / `embedding` / `similarity` / `weight` / `score` / `priority` / `probability` /
`severity` / `rank` / `confidence` / `stance` / `target_price` / `threshold`。

**YAML の緩い型変換への対処**: `enabled` は Python の `bool` のみを受ける（`"yes"` は `INVALID_TYPE`）。
`condition_version` は `str` のみ（`1` や `0.1` は `INVALID_TYPE`）。`threshold_days` は `bool` を除く `int` のみ。

### 4.2 任意 rule 言語の不在

ruleset は **evaluator を programming する DSL ではない**。condition ごとの評価器は engine 側に bounded に
実装され、`CONDITION_REGISTRY` が id → 分類を凍結している。ruleset が持てるのは
「有効/無効」「閾値定数」「表示 key」「version provenance」だけである。

---

## 5. engine architecture

```
evaluate_monitoring(evaluation_input, *, ruleset, recorded_at) -> MonitoringEvaluation
```

`_Collector` が finding を **finding_id を key とする dict** に集め、同一 identity を自然に 1 件へ収束させる。
出力は `finding_id` 昇順（**順序に優先度の意味は無い**）。run report の `finding_ids` も同じ canonical 順。

---

## 6. 入力 model（最小・typed・不変）

`MonitoringEvaluationInput`（cutoff ／ knowledge_versions ／ input_digests ／ 5 種の snapshot 列）:

| snapshot | 主な field |
|---|---|
| `ThemeSnapshot` | theme_root_id / governance_state / evidence_flags / evidence_roles_present / arrived_attachment_keys / semantic_revision_observation_id / freshness_policy_token |
| `ProposalSnapshot` | proposal_id / proposal_status / created_at / decision_chain_status / decision_chain_diagnostic / discovery_outcome_token |
| `RelationSnapshot` | edge_key / edge_state / assertion_class / source・target_endpoint_state / contested_theme_root_id / contested_role / governance_chain_status |
| `RelationProposalSnapshot` | relation_proposal_id / edge_key / conflict_token |
| `KnowledgeDriftSnapshot` | knowledge_name / from_version / to_version |
| `AuthorityFailureSnapshot` | authority_name / failure_class / locator_token / blocked_condition_ids |

いずれも frozen dataclass。generic dict dump を受けない。`_Subject` 基底が
`availability` / `authority_name` / `failure_class` / `locator_token` を共通に持つ。

---

## 7. 既存 derived 意味論の再実装をしない

| 上流 | B6 が読む値 | B6 が**持たない**もの |
|---|---|---|
| B2 lifecycle | `governance_state` / `evidence_flags`（`CONTESTED` / `STALE` / `NO_VISIBLE_EVIDENCE` …） | 資格判定・独立 origin 数・**stale の日数計算** |
| B1 change | `semantic_revision_observation_id` / `arrived_attachment_keys` | 差分計算そのもの |
| B3 / B5C | `proposal_status` / `decision_chain_status` / diagnostic | chain 解決論理 |
| B4 | `discovery_outcome_token` | discovery 評価 |
| B5 | `edge_state` / 端点 state / `assertion_class` | relation resolution・graph 推論 |

test が `stale_after_days` / `independent_origin` / `qualification` / `resolve_relation_graph` /
`derive_lifecycle` / `endpoint_lookup` の token が engine に無いことを固定する。
engine の import は `..core.time` ／ `.monitoring_model` ／ `.monitoring_rules` ／ stdlib だけである。

---

## 8. 閾値の所有

| 閾値 | 所有者 | B6 での扱い |
|---|---|---|
| stale までの日数 | **B2 `LifecyclePolicy`** | ruleset に置かない。snapshot の `freshness_policy_token` をそのまま `threshold_token` にする。token が無ければ**評価しない**（PARTIAL） |
| 提案 OPEN の滞留日数 | **B6 ruleset**（60） | `cutoff - created_at >= days` を engine が計算。identity には `open_after_days:60` の token だけ |
| 提案 DEFERRED の滞留日数 | **B6 ruleset**（30） | 同上（`open_deferred_after_days:30`） |

**生の日数を finding identity に入れない。** 閾値を跨いだという状態だけが identity を担う。

---

## 9. evidence の意味論

- `CONTRADICTS` / `INVALIDATES` は**存在するか**だけを見る。件数を identity に入れない。
  evidence が 1 件増えても `supporting_refs` が増えるだけで `finding_id` は同じ。
- 一方 `RETIRED_ROOT_RECEIVED_EVIDENCE` は attachment ごとに review が要るため、
  `attachment_key` を identity に含め、attachment ごとに 1 finding を出す。

---

## 10. proposal の意味論

`ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT` の意味は
**「受理された決定に対応する authoritative effect が観測されていない」**までである。
`EXECUTE_NOW` / `SHOULD_EXECUTE` / `READY_TO_PROMOTE` / `AUTO_APPEND` のような命令語彙は持たない
（engine source に無いことを test が固定）。滞留も「長く OPEN / DEFERRED である」という観測のみ。

---

## 11. relation の意味論

B5B / B5C は read-only。graph traversal による推論・推移閉包・centrality・PageRank・edge strength・
自動訂正・自動撤回・自動復帰はいずれも無い。端点は既存 state を指差すだけ。
`SOURCE_ASSERTED_RELATION_CONTESTED` は「矛盾する evidence が存在する」までで、
「その relation が偽である」とは言わない。

### 11.1 RR-3 POLICY LOCK

engine は `RelationAssertionPlan` を authority 入力として扱わず、実行命令も生成しない。
`RelationAssertionPlan` / `EvidenceAttachmentPlan` / `append_assertion` の token が engine に存在しない。

---

## 12. discovery の意味論

discovery hit ≠ Theme ／ proposal ≠ Theme ／ ACCEPT ≠ mutation ／ `EvidenceAttachmentPlan` ≠ attachment authority。
monitoring はこれを短絡しない。observed token（`NO_ACCEPTED_PROPOSAL` / `NO_OBSERVED_EFFECT`）を指差すだけ。

---

## 13. integrity routing と PARTIAL

### 13.1 判定不能を「偽」にしない

subject が `UNAVAILABLE`、または `AuthorityFailureSnapshot` が与えられた場合:

1. 該当 condition を `unevaluated_conditions` に入れる（有効な condition のみ）
2. `AUTHORITY_STATE_UNUSABLE` の INTEGRITY finding を 1 件出す
3. run status を `PARTIAL` にする

`freshness_policy_token` が無い STALE、`created_at` が無い滞留判定も同じく未評価にし、
診断 code（`FRESHNESS_POLICY_TOKEN_MISSING` / `PROPOSAL_CREATED_AT_MISSING`）を残す。
**例外を握り潰して COMPLETE ＋ finding 0 にする経路は存在しない。**

### 13.2 重複生成をしない policy

| 面 | 重複の抑え方 |
|---|---|
| INTEGRITY finding | fingerprint（authority_name / failure_class / locator_token）が同じなら **finding_id が同じ**ので dict で 1 件に収束 |
| run diagnostics | `set` に集めて canonical sort（同じ code は 1 回） |
| unevaluated_conditions | `set` に集めて canonical sort |

すなわち「同じ障害」は run report 上でも finding 上でも 1 回だけ現れる。

---

## 14. version binding

run report は `cutoff` / `ruleset_version` / `knowledge_versions` / `input_digests` を明示する。
engine は存在しない version を暗黙 default にしない。ruleset は `published_at <= cutoff` を要求し
（`FUTURE_RULESET`）、loader は expected_version 完全一致と digest 一致を要求する。

---

## 15. 決定論

同じ snapshot ＋ 同じ ruleset ＋ 同じ cutoff なら、**物理入力順に関係なく**同じ findings・同じ run report・
同じ canonical bytes を返す（11 seed の shuffle test で固定）。engine に時計・乱数・環境依存は無い。

---

## 16. 合成 false-positive gate（**synthetic gate result only**）

SUPPORTS のみ ／ 十分な support を持つ ACCEPTED Theme ／ 陳腐化していない Theme ／ 閾値未満の滞留提案 ／
端点が活きている relation ／ 通常の SOURCE_ASSERTED relation ／ 健全な chain ／ version drift 無し ／
新 evidence の無い RETIRED root — **いずれも finding を出さない**。

実世界の precision / recall はここから主張しない。

---

## 17. B6D への引き継ぎ（entry contract 案）

1. B6D は `ReviewItemState` の operational store と runner を扱う。**engine を変更しない。**
2. runner は `read authorities → PIT 解決 → snapshot 構築 → evaluate_monitoring → derived 出力`
   までで、authority mutation を既定禁止にする。
3. snapshot の構築（上流 derived からの写し取り）は runner の責務であり、engine に持ち込まない。
4. store が追記してよいのは review state と（任意で）run report のみ。finding は永続化しない。
5. 実データは shadow / no-write / no-notification から始める。
