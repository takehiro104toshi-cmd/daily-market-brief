# Compass Decision Foundation（Phase 3.9.1）

Phase 3.8（何が観測されたか）と production Compass DNA の間に置く **supervised Decision Layer の土台**。
評価知能（推奨・重み付け・ranking・replay・promotion）は含まない（3.9.2 以降）。実装は
`src/intelligence/decision/`（1機能=1ファイル）、設定は `config.yaml: compass_decision`、テストは
`tests/intelligence/test_decision_foundation.py`（22 件）。

```
Compass PDF → Corpus（3.7）→ Phase 3.8 evidence（読むだけ）
  → Phase 3.9 decision（append-only history・人間の明示 action）
  → APPROVED ≠ PROMOTED_TO_DNA（promotion は別 gate。3.9.1 では未実装 = 常に NOT_PROMOTED）
```

## 1. Frozen policy（PHASE_3_9_SPECIFICATION_FREEZE_V1）と executable 化

| policy | 実装 |
|---|---|
| CORPUS_100 未満は SHADOW MODE、formal APPROVED 禁止 | `gates.formal_review_gate()`: corpus `eligible_for_pattern_evidence` < `formal_review_min_corpus`（100、下限 100）→ `FORMAL_REVIEW_GATE_NOT_REACHED`。APPROVED の validate / decide が fail closed |
| 人間の明示 action | 全 decision は `actor_type=HUMAN` のみ（`HUMAN_ACTION_REQUIRED`）。CLI は常に HUMAN。SYSTEM actor は gate 到達後も拒否 |
| auto approval なし | policy `auto_approval` は false 固定（true は `PolicyError`）。3.8 analyzer / corpus intake / 3.75 processor は decision package を import しない（test で検証） |
| APPROVED ≠ production DNA | record / current state に `promotion_status`（3.9.1 は `NOT_PROMOTED` のみ schema が許す）。`market_rules.yaml` / `market_principles.py` は hash 不変（test） |
| decision history は append-only | JSONL 1 行 = 1 event。`sequence` 連番 + `previous_record_hash → record_hash` chain。store に update / delete API なし |
| reason 必須 | policy v1 は保守的に **全 state** で非空 reason（KEEP_REVIEWING 含む） |
| REJECTED は reopen 可 | `REJECTED → REOPENED_FOR_REVIEW`（人間 decision、`reopens_decision_id`）。current state の `reopen_eligible` は派生属性で、自動では変わらない |
| policy_version | 全 record に `policy_version` と `policy_digest`。同じ version で digest が変わると append 拒否（`POLICY_CHANGED_WITHOUT_VERSION_BUMP`） |
| Compass DNA ≠ Personal DNA | Personal DNA 機能なし |

## 2. Decision model

Phase 3.8 の research status（OBSERVED … STRONG_PATTERN_CANDIDATE）と Phase 3.9 の decision state は別概念。
registry / review queue には書かない（evidence snapshot に読み取り値を写すだけ）。

states: `KEEP_REVIEWING / APPROVED / REJECTED / REOPENED_FOR_REVIEW / SUPERSEDED / RETIRED`

allowed transitions（previous effective state → next。それ以外は `TRANSITION_NOT_ALLOWED`）:

| from | to |
|---|---|
| （履歴なし） | KEEP_REVIEWING, APPROVED, REJECTED |
| KEEP_REVIEWING | KEEP_REVIEWING, APPROVED, REJECTED |
| APPROVED | SUPERSEDED, RETIRED |
| REJECTED | REOPENED_FOR_REVIEW |
| REOPENED_FOR_REVIEW | KEEP_REVIEWING, APPROVED, REJECTED |
| SUPERSEDED / RETIRED | （v1 terminal。reopen 可否は監督者判断） |

current state = pattern ごとの最後の event（`sequence` 順）。決定的（入力順序に依存しない）。

## 3. Record（schema 1.0.0）

`decision_id`（deterministic: pattern / type / reason / actor / actor_type / policy_version / previous_decision_id /
idempotency_key の hash。timestamp を含まない）, `pattern_id`, `decision_type`, `reason`, `notes`, `actor`,
`actor_type`, `decided_at`, `policy_version`, `policy_digest`, `review_mode`（SHADOW / FORMAL）, `corpus_size`
（eligible）, `corpus_documents`, `corpus_usable`, `corpus_milestone`, `previous_state`, `previous_decision_id`,
`supersedes_decision_id`, `reopens_decision_id`, `evidence`, `evidence_digest`, `promotion_status`, `metadata`
（将来の priority 等を載せる小さな文字列 map）, `idempotency_key`, `schema_version`, `sequence`,
`previous_record_hash`, `record_hash`。

idempotency: head（同じ pattern の最後の record）と同一内容（type / reason / actor / actor_type / idempotency_key）
の再実行は append しない（`DUPLICATE_OF_HEAD_IDEMPOTENT`）。内容が変われば新 event。

## 4. Evidence snapshot（schema 1.0.0）

decision 時点の Phase 3.8 artifact を **id / count / label / version だけ** で写す（本文・observation text・PDF path なし）:
pattern type / research status / record id / support / eligible support / regime count / span / date range /
valid ratio / evidence categories / theme / outlook / risk / supporting document count と id（先頭 20）/
evidence reference count / DNA classification と best rule / conflict count と rule ids / limitations /
research snapshot id・生成時刻・analyzer versions / research corpus count。`evidence_digest` で同一性を検証できる。
pattern が current registry に無い decision は拒否（`PATTERN_NOT_IN_REGISTRY`）。

## 5. Store / corruption

`<data_root>/compass_decisions/decisions.jsonl`（corpus / research と同じ data root 規約。Windows 実機では
既存の local config が指す CompassData 配下。tracked directory には置かない）。load 時に不正 JSON / schema 不一致 /
連番不一致 / chain 断裂 / id 重複を検出すると `DecisionStoreCorrupt`（黙って読み飛ばさず、state を導出しない）。

## 6. CLI（`python -m src.intelligence.decision.cli`）

read（書かない）: `gate` / `list` / `history --pattern` / `show --decision` / `validate --pattern --type --reason --actor`。
mutating（明示）: `decide --pattern --type --reason --actor [--notes] [--idempotency-key] [--dry-run]`。
`--data-root` で root を上書き（既定は processor / batch_import と同じ解決順）。exit 0 / 1（validation・gate）/ 2（policy・corrupt）。

## 7. Deferred（3.9.2 以降）

recommendation scoring・support weighting・priority ranking・replay / simulation・shadow review・formal DNA review・
promotion（DNA_CANDIDATE / PROMOTED_TO_DNA）・auto approval（CORPUS 500–1000 以降の別 gate）・UI / PWA・
SUPERSEDED / RETIRED からの reopen・review queue の resolution state・Phase 3.8 limitations の修正。
