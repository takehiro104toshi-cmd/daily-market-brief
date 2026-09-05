# Compass First Formal DNA Review 仕様（Phase 3.9.5）

**NOT_AUTOMATIC_APPROVAL / NOT_DNA_PROMOTION / EVIDENCE_PACKET_BOUND / HUMAN_ONE_AT_A_TIME**

Phase 3.9.2 は「engine が何を推奨するか」、Phase 3.9.3 は「今日人間が何を見るべきか」、Phase 3.9.4 は
「推奨がどれだけ持続したか」を答える。Phase 3.9.5 は、それらを **人間が実際に見る証拠 packet** にまとめ、
freshness / 整合性 guard を通したうえで、人間の formal Decision を Phase 3.9.1 に書く層である。

```
APPROVE_RECOMMENDED ≠ APPROVED      REJECT_RECOMMENDED ≠ REJECTED      APPROVED ≠ PROMOTED_TO_DNA
```

自動承認・自動却下・新しい recommendation state・DNA 書き込みはない。実装は `src/intelligence/formal_review/`
（1 機能 = 1 ファイル）、設定は `config.yaml: compass_formal_review`（1.0.0 / digest `cca7b43627b9a355`）。

## 1. review unit と population

- 原子的 formal review unit = **単一 pattern_id**（Phase 3.9.1 Decision が pattern 単位）。group 単位の Decision は作らない。
- primary candidate = 現在の recommendation が APPROVE_RECOMMENDED / REJECT_RECOMMENDED で、Decision head が
  NONE / KEEP_REVIEWING / REOPENED_FOR_REVIEW。head が APPROVED / REJECTED / SUPERSEDED / RETIRED は decided。
- REJECTED は material change が検出されたときだけ REOPEN_ELIGIBLE section に載る。NOT_READY は除外。
- context = candidate の sibling group member（recommendation を問わず）。表示のみで、queue から決められない。
- 件数は実行時に必ず動的に決まる（実装に固定値なし）。

## 2. sibling / group（v1 凍結）

関係 = Phase 3.9.2 contradiction index と同じ key: **EVIDENCE_OUTLOOK** の `evidence` categories + outlook `target`。
STATE_OUTLOOK / THEME_OUTLOOK には広げない。member ごとに direction / recommendation / decision state / DNA
classification / eligible_support / relationship（OPPOSITE・SAME・NON_COMMITTED）を示し、
`group_state_digest`（member の pattern_id・direction・recommendation・decision_state・material_digest）で束縛する。

## 3. packet

`<data_root>/compass_formal_review/packets/<pattern_id>.json`。block: identity / recommendation / axes /
reference（`NON_DECISIONAL_REFERENCE_ONLY`）/ consistency / dna / replay / shadow_history / decision / group /
freshness / warnings。原文・ファイル名・path は入らない（Phase 3.9.3 forbidden key を再利用して scan）。

### 3.1 二つの digest

| digest | 意味 | 用途 |
|---|---|---|
| `material_digest` | Phase 3.9.3 の凍結 semantics（recommendation・axis state・applicability・eligible_support・2D cells・contradiction block・lifecycle・policy digest 2 種） | 機械側の material change 追跡、REOPEN 適格、「何が変わったか」 |
| `packet_evidence_digest` | 人間が見た証拠そのもの（identity・recommendation 規則・6 軸・consistency・dna・replay run digest と指標・shadow 現在状態と履歴 digest・decision head・group state・全 policy digest） | formal Decision 書き込み前の freshness anchor |

`packet_evidence_digest` に含めないもの: 生成時刻、`corpus_size` / `corpus_milestone` / `corpus_eligible_at_build` /
`evidence_age_eligible_docs`（corpus 増加だけで変わる）、`evaluation_id` / `inputs_digest`（corpus_size を含むため
informational）、replay_run_id（run_digest で束縛）、warnings（証拠から派生）。
`packet_id = frp_ + sha256(pattern_id | packet_evidence_digest | schema | formal review digest)[:16]`（決定的）。

### 3.2 corpus-only growth

eligible 139 → 140 で証拠 field が不変なら packet は有効なまま。Decision metadata に
`corpus_eligible_at_packet` と `corpus_eligible_at_write` を記録する。

## 4. ordering（凍結・section は交互に混ぜない）

1. REJECT_RECOMMENDED: first_reject_position ASC → reject_persistence_ratio DESC → eligible_support DESC → pattern_id
2. APPROVE_RECOMMENDED: stability rank（STABLE, MOSTLY_STABLE, RECENT_TRANSITION, INSUFFICIENT_HISTORY, OSCILLATING）
   → first_approve_position ASC → eligible_support DESC → span_days DESC → pattern_id
3. REOPEN_ELIGIBLE: first_reject_position ASC → pattern_id

## 5. warnings（表示と並びのみ・新 gate なし）

W_SIBLING_OPPOSITE_APPROVED（C1 が block）/ W_SIBLING_OPPOSITE_APPROVE_RECOMMENDED（C3 acknowledgement）/
W_REPLAY_EVIDENCE_MISSING / W_REPLAY_EVIDENCE_NOT_CURRENT / W_OSCILLATING / W_INSUFFICIENT_HISTORY /
W_RECENT_TRANSITION / W_MOSTLY_STABLE_SHOW_HISTORY / W_REPLAY_EVIDENCE_AGE（current − captured ≥ 5）/
W_DNA_CONFLICT / W_CONTRADICTION_ACTIVE / W_APPEARED_ONLY_AFTER_100 / W_SHADOW_DISAGREEMENT_HISTORY。
RECENT_TRANSITION の APPROVE candidate は自動では block しない。

## 6. formal outcome（既存 Decision state のみ）

| head | recommendation | 許される action |
|---|---|---|
| NONE / KEEP_REVIEWING / REOPENED_FOR_REVIEW | APPROVE_RECOMMENDED | APPROVED, KEEP_REVIEWING |
| 同上 | REJECT_RECOMMENDED | REJECTED, KEEP_REVIEWING |
| APPROVED | — | SUPERSEDED（replacement_pattern_id 必須）, RETIRED |
| REJECTED | — | REOPENED_FOR_REVIEW（REOPEN_ELIGIBLE のときだけ） |
| SUPERSEDED / RETIRED | — | terminal |

symmetry は凍結: APPROVE_RECOMMENDED → REJECTED、REJECT_RECOMMENDED → APPROVED は v1 で禁止。人間が推奨に
同意しないときは KEEP_REVIEWING + reason。重複・重なりは KEEP_REVIEWING + `disposition=DUPLICATE_OR_OVERLAPPING`
+ `related_pattern_id`（新 state なし）。

## 7. reason

Phase 3.9.1 の HUMAN actor・非空 reason は不変。追加の最小: APPROVED 20 / REJECTED 20 / KEEP_REVIEWING 10 /
REOPENED_FOR_REVIEW 20 / SUPERSEDED 20 / RETIRED 20 文字。推奨ラベルだけの reason は拒否。REJECTED は packet に
active な contradiction indicator が必要。KEEP_REVIEWING は任意の `reason_category`
（MORE_DOCUMENTS / MORE_REGIMES / LONGER_SPAN / BETTER_QUALITY）。

## 8. guard（書き込み前の検査順・fail closed）

1 Decision store 有効 → 2 evaluation store 有効 → 3 candidate 存在（queue に載っている）→ 4 packet 帰属 →
5 recommendation 一致 → 6 symmetry → 7 material_digest 不変 → 8 packet_evidence_digest 不変 →
9 全 policy digest 一致 → 10 formal gate（evaluation record と live corpus）→ 11 lifecycle → 12 head 不変 →
13 transition / reopen 適格 → 14 replay evidence（APPROVED / REJECTED は current-compatible 必須）→
15 sibling C1（反対方向 sibling が APPROVED なら block・override なし）/ C3（未決 APPROVE_RECOMMENDED は
`--acknowledge-sibling` 必須・metadata に記録）→ 16 reopen → 17 HUMAN actor → 18 reason → 19 metadata 制約 →
20 forbidden key → 21 `DecisionService.validate` → 22 `DecisionService.decide`。

replay evidence の current-compatible = replay run の policy digest 4 種が現在と一致、pattern が replay に存在、
replay の current_recommendation が現在の recommendation と一致、captured ≤ current eligible。

## 9. Decision 書き込み経路と metadata

```
FormalReviewGuard → DecisionRequest → DecisionService.validate → DecisionService.decide → DecisionStore.append
```
guard も CLI も DecisionStore に直接触れない。`promotion_status` は常に NOT_PROMOTED（schema 1.0.0 が許す唯一の値）。
`idempotency_key = packet_id` なので、同じ fresh packet に対する同じ判断の retry は重複 row を作らない
（`DUPLICATE_OF_HEAD_IDEMPOTENT`）。

metadata（20 key / 500 chars 制約）: packet_id, packet_evidence_digest, material_digest, recommendation,
policy_digests（`layer:digest;...` 6 層を 1 key に束ねる）, replay_run_id, replay_run_digest, group_state_digest,
stability_class, formal_review_schema_version, corpus_eligible_at_packet, corpus_eligible_at_write,
head_decision_id_at_packet, metadata_payload_digest（個別 digest を含む全 binding の canonical digest）、
必要時のみ acknowledged_sibling / disposition / related_pattern_id / replacement_pattern_id / reason_category。
tradeoff: policy digest 6 個を個別 key にすると 20 key を超えるため 1 key に束ね、個別値は payload digest で束縛する。

## 10. reopen

REJECTED は `現在の material_digest ≠ REJECTED decision metadata の material_digest` のときだけ REOPEN_ELIGIBLE。
corpus 増加のみ・score のみ・経過時間のみでは変わらない。packet binding の無い REJECTED は検証不能（非適格）。
system は表示するだけで、REOPENED_FOR_REVIEW を書くのは人間だけ（`reopen-check` は read-only）。

## 11. DNA relation

表示は既存 classification のまま: EXPLAINED_BY_EXISTING_RULE / PARTIALLY_EXPLAINED / NEW_PATTERN_CANDIDATE /
CONFLICTS_WITH_EXISTING_RULE / NOT_COMPARABLE（best_rule_id・direction_relation・conflict rule ids 付き）。
APPROVED は DNA を編集しない。CONFLICTS は symmetry により v1 では APPROVED になれない。promotion は別 gate。

## 12. storage / CLI / metrics

derived: `compass_formal_review/{build_manifest.json, queue.json, summary.json, packets/}`（atomic・rebuildable）。
formal truth は `compass_decisions/decisions.jsonl` のみ。
CLI: `build` / `list` / `show <pattern_id>` / `decide <pattern_id> --packet --action --reason --actor
[--acknowledge-sibling] [--related-pattern] [--replacement-pattern] [--reason-category] [--disposition] [--dry-run]` /
`status` / `reopen-check` / `validate-policy`。batch command なし、1 invocation = 1 pattern。
`--dry-run` は guard と `DecisionService.validate` まで実行し何も書かない（Windows packet validation で使う）。
metrics は運用値のみ（candidates / by recommendation / context / pending / reviewed / outcomes / blocked / acknowledged /
reopen eligible / median age / replay age）。accuracy・precision・hit rate・forecast 系はない。

## 13. Phase 3.9.5 の閉じ方

実装完了 ≠ Phase close。実装 → local QA → 監督者実装レビュー → Windows real-data packet build → 全 candidate の
`decide --dry-run` → 監督者 process review → 明示的 HUMAN-DECISION GO → first real human formal review → 最終 audit
→ CLOSED。実装・packet validation の間に real Decision は書かない。
